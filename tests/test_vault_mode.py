"""Tests for the OPTIONAL vault mode (Task 1.4).

This is the Coupling-1 seam (references/prior-art.md §2): vault-index use is
CONDITIONAL on a configured vault. Two modules are under test:

* ``scripts/vault_mode.py`` — ``resolve_notes`` routes between the portable-first
  default (no index, batch-only links) and vault mode (index-resolved
  action/folder + wikilink edit plan). This is the deterministic core; the only
  I/O it does is via the adapter's sqlite, and ONLY in the vault branch.
* ``scripts/vault_index.py`` — the SQLite FTS5 (or LIKE-fallback) adapter ported
  from research-workflow. It is the SOLE module in Librarian allowed to import
  sqlite3.

The cardinal invariant these tests enforce: the **portable path never imports
sqlite/vault_index and never creates an index db**. ``test_portable_*`` assert
both (no db file anywhere under the out dir or a sibling vault dir, and the
import-graph guard in ``test_portable_path_is_sqlite_import_clean``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.taxonomy import load_taxonomy
from scripts.vault_mode import resolve_notes


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _write_note_file(vault: Path, rel: str, title: str, body: str) -> Path:
    """Write a minimal Markdown note (frontmatter title + body) into the vault."""
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\ntitle: {title}\n---\n\n{body}\n", encoding="utf-8")
    return p


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """A temp vault with 3 known notes (titles + distinctive body terms)."""
    v = tmp_path / "vault"
    v.mkdir()
    _write_note_file(
        v,
        "People/County Transit Authority.md",
        "County Transit Authority",
        "The County Transit Authority operates the regional bus network and "
        "manages the camera procurement budget.",
    )
    _write_note_file(
        v,
        "Topics/License Plate Readers.md",
        "License Plate Readers",
        "Automated license plate readers (ALPR) capture vehicle movements at "
        "fixed checkpoints. Often abbreviated ALPR.",
    )
    _write_note_file(
        v,
        "Reports/Prior Camera Audit.md",
        "Prior Camera Audit",
        "An earlier audit of camera deployments across the transit corridor.",
    )
    return v


def _find_index_dbs(root: Path) -> list[Path]:
    """Return every *.db file anywhere under root (the index db, if created)."""
    return list(root.rglob("*.db"))


# --------------------------------------------------------------------------- #
# Portable mode (default — NO vault_context)
# --------------------------------------------------------------------------- #


def test_portable_mode_basic_placement_and_links(tmp_path: Path):
    """No vault_context => mode==portable; placement under default_folder; batch+hint links only."""
    tax = load_taxonomy()  # default_folder == "Inbox"
    specs = [
        {
            "title": "New Camera Expansion Memo",
            "content": "Body about an expansion that references the budget plan.",
            "link_hints": ["County Budget Plan", "License Plate Readers"],
            "priority": "primary",
        },
        {
            "title": "County Budget Plan",
            "content": "The annual budget plan.",
            "priority": "secondary",
        },
    ]

    result = resolve_notes(specs, taxonomy=tax)

    assert result["mode"] == "portable"

    # --- placements: default_folder + slug(title), action defaults to create ---
    placements = {p["title"]: p for p in result["placements"]}
    assert placements["New Camera Expansion Memo"]["folder"] == "Inbox"
    assert (
        placements["New Camera Expansion Memo"]["path"]
        == "Inbox/new-camera-expansion-memo.md"
    )
    assert placements["New Camera Expansion Memo"]["action"] == "create"
    assert placements["County Budget Plan"]["path"] == "Inbox/county-budget-plan.md"

    # --- link plan: ONLY intra-batch titles + link_hints; no pre-existing lookup ---
    # "County Budget Plan" is BOTH a hint of note 1 and a title in the batch -> a
    # real intra-batch link. "License Plate Readers" is a hint with no batch match
    # and (crucially, portable) no index to resolve -> it stays an unresolved/stub hint.
    targets_for_memo = [
        e for e in result["link_plan"] if e["source_title"] == "New Camera Expansion Memo"
    ]
    resolved = {e["target_title"]: e for e in targets_for_memo}
    assert "County Budget Plan" in resolved
    assert resolved["County Budget Plan"]["resolved_in_batch"] is True
    # The hint with no batch match is still surfaced, but NOT resolved to a vault note.
    assert "License Plate Readers" in resolved
    assert resolved["License Plate Readers"]["resolved_in_batch"] is False
    # Portable mode never marks a hint as an existing-vault-note link.
    assert all(e.get("target_vault_path") is None for e in result["link_plan"])


def test_portable_mode_creates_no_index_db(tmp_path: Path):
    """The portable path must not create an index db anywhere (Coupling 1 invariant)."""
    tax = load_taxonomy()
    specs = [{"title": "Solo Note", "content": "x", "link_hints": []}]

    resolve_notes(specs, taxonomy=tax)

    # Nothing under tmp_path should be a .db — portable mode never touches sqlite.
    assert _find_index_dbs(tmp_path) == [], "portable mode must not create an index db"


def test_portable_path_is_sqlite_import_clean():
    """Calling resolve_notes in portable mode must not import sqlite3 or vault_index.

    The whole point of Coupling 1: the portable default is a strict subset that
    never reaches the vault adapter. We prove it structurally by dropping sqlite3
    and vault_index from sys.modules, blocking sqlite3 re-import, and asserting a
    portable call still succeeds AND left both modules unimported.
    """
    import builtins

    saved = {
        name: sys.modules.get(name)
        for name in ("sqlite3", "scripts.vault_index")
    }
    for name in saved:
        sys.modules.pop(name, None)

    real_import = builtins.__import__

    def _blocking_import(name, *args, **kwargs):
        if name == "sqlite3" or name.endswith("vault_index"):
            raise AssertionError(
                f"portable path imported {name!r} — it must stay sqlite-free"
            )
        return real_import(name, *args, **kwargs)

    builtins.__import__ = _blocking_import
    try:
        tax = load_taxonomy()
        result = resolve_notes(
            [{"title": "Clean", "content": "x", "link_hints": ["Other"]}],
            taxonomy=tax,
        )
        assert result["mode"] == "portable"
    finally:
        builtins.__import__ = real_import
        for name, mod in saved.items():
            if mod is not None:
                sys.modules[name] = mod

    # And the guarded modules must still be absent (never imported by the call).
    assert "scripts.vault_index" not in sys.modules


# --------------------------------------------------------------------------- #
# Vault mode (vault_context supplied)
# --------------------------------------------------------------------------- #


def test_vault_mode_resolves_existing_note_link(vault: Path):
    """vault_context => mode==vault; link_plan references an existing vault note via the index."""
    tax = load_taxonomy()
    specs = [
        {
            "title": "Camera Procurement Update",
            "content": (
                "The County Transit Authority approved new automated license "
                "plate readers for the corridor."
            ),
            "link_hints": ["County Transit Authority", "License Plate Readers"],
            "priority": "primary",
        }
    ]

    result = resolve_notes(
        specs, vault_context={"vault_path": str(vault)}, taxonomy=tax
    )

    assert result["mode"] == "vault"
    assert len(result["placements"]) == 1

    # The link plan must reference at least one EXISTING vault note discovered via
    # the index (not just intra-batch). Both hints match seeded notes.
    vault_links = [e for e in result["link_plan"] if e.get("target_vault_path")]
    assert vault_links, "vault mode should resolve at least one hint to an existing vault note"
    linked_titles = {e["target_title"] for e in vault_links}
    assert "County Transit Authority" in linked_titles or "License Plate Readers" in linked_titles
    # The resolved target path points at a real seeded note.
    for e in vault_links:
        assert e["target_vault_path"].endswith(".md")


def test_vault_mode_incoming_title_match_routes_update(vault: Path):
    """A spec whose title matches an existing vault note routes action==update."""
    tax = load_taxonomy()
    specs = [
        {
            # Exact title of a seeded note -> should be detected as an update target.
            "title": "Prior Camera Audit",
            "content": "Refreshed findings for the prior camera audit.",
            "link_hints": [],
            "priority": "primary",
        },
        {
            "title": "Totally New Subject Nobody Indexed",
            "content": "A brand-new topic.",
            "link_hints": [],
            "priority": "secondary",
        },
    ]

    result = resolve_notes(
        specs, vault_context={"vault_path": str(vault)}, taxonomy=tax
    )

    placements = {p["title"]: p for p in result["placements"]}
    # Existing note -> update, and placement folder comes from the index hit.
    assert placements["Prior Camera Audit"]["action"] == "update"
    assert placements["Prior Camera Audit"]["folder"] == "Reports"
    assert placements["Prior Camera Audit"]["path"] == "Reports/Prior Camera Audit.md"
    # No matching note -> stays create, default folder.
    assert placements["Totally New Subject Nobody Indexed"]["action"] == "create"
    assert placements["Totally New Subject Nobody Indexed"]["folder"] == "Inbox"


def test_vault_mode_refreshes_index_before_search(vault: Path):
    """Gap #6: the adapter refreshes the index itself; a note added just now is findable.

    No explicit update_index() call here — resolve_notes must refresh internally
    before searching, so a note written after the vault fixture is still resolved.
    """
    tax = load_taxonomy()
    _write_note_file(
        vault,
        "Topics/Fusion Center Data Sharing.md",
        "Fusion Center Data Sharing",
        "Regional fusion center data sharing agreement covering camera feeds.",
    )
    specs = [
        {
            "title": "Data Sharing Brief",
            "content": "A brief about the regional agreement.",
            "link_hints": ["Fusion Center Data Sharing"],
            "priority": "primary",
        }
    ]

    result = resolve_notes(
        specs, vault_context={"vault_path": str(vault)}, taxonomy=tax
    )

    vault_links = [e for e in result["link_plan"] if e.get("target_vault_path")]
    assert any(
        e["target_title"] == "Fusion Center Data Sharing" for e in vault_links
    ), "index must be refreshed internally so a just-added note is found"


# --------------------------------------------------------------------------- #
# Adapter unit tests (scripts/vault_index.py)
# --------------------------------------------------------------------------- #


def test_adapter_update_then_search(vault: Path):
    """update_index then search returns the expected note for a query term."""
    from scripts import vault_index

    vault_index.update_index(vault)
    hits = vault_index.search(vault, "license plate readers")

    assert hits, "search should return at least one hit for an indexed term"
    titles = {h["title"] for h in hits}
    assert "License Plate Readers" in titles
    # Every hit carries a path + title (the public hit shape callers rely on).
    for h in hits:
        assert h["path"].endswith(".md")
        assert isinstance(h["title"], str) and h["title"]


def test_adapter_note_exists(vault: Path):
    """note_exists is true for a present title, false for an absent one."""
    from scripts import vault_index

    vault_index.update_index(vault)

    assert vault_index.note_exists(vault, "County Transit Authority") is True
    assert vault_index.note_exists(vault, "No Such Note At All") is False


def test_adapter_list_notes(vault: Path):
    """list_notes enumerates every indexed .md note."""
    from scripts import vault_index

    vault_index.update_index(vault)
    notes = vault_index.list_notes(vault)

    titles = {n["title"] for n in notes}
    assert {
        "County Transit Authority",
        "License Plate Readers",
        "Prior Camera Audit",
    } <= titles


def test_adapter_db_lives_under_vault_dot_librarian(vault: Path):
    """The index db is created on demand under <vault>/.librarian/."""
    from scripts import vault_index

    vault_index.update_index(vault)
    db_files = _find_index_dbs(vault / ".librarian")
    assert db_files, "index db should be created under <vault>/.librarian/"
