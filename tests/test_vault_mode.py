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


def test_adapter_note_exists_is_case_insensitive(vault: Path):
    """Fix 3: note_exists agrees with the case-insensitive vault-mode matcher.

    The vault note is titled "Prior Camera Audit"; a caller asking with different
    casing (e.g. as a dedup guard) must get True, matching what resolve_notes would
    route as an update via _best_title_match (also case-insensitive).
    """
    from scripts import vault_index

    vault_index.update_index(vault)

    assert vault_index.note_exists(vault, "PRIOR camera AUDIT") is True
    assert vault_index.note_exists(vault, "prior camera audit") is True
    assert vault_index.note_exists(vault, "Prior Camera Audit") is True
    # Still false for a genuinely absent title regardless of case.
    assert vault_index.note_exists(vault, "no such note") is False


# --------------------------------------------------------------------------- #
# Fix 1: adversarial query strings must never crash search / resolve_notes
# --------------------------------------------------------------------------- #

# FOIA-grade titles / link hints that contain FTS5 syntax. Pre-fix, feeding any
# of these into an FTS5 MATCH raised sqlite3.OperationalError and killed the whole
# resolve_notes batch. They must now be inert (no exception, sane empty/no-op).
_ADVERSARIAL_QUERIES = [
    "Smith v. Jones (2020)",
    "Acme OR Globex",
    "NEAR(camera budget)",
    "camera AND budget",
    "license NOT plate",
    "(",
    ":",
    "-",
    "^",
    '"',
    "*",
    '"unterminated',
    "col:filter",
    "a* b* c*",
    "",
    "   ",
]


@pytest.fixture
def adversarial_vault(tmp_path: Path) -> Path:
    """A vault whose notes are titled/bodied so a SANE adversarial query still hits.

    In particular a note titled `Smith v. Jones` whose body contains the full
    `Smith v. Jones (2020)` reference, so the sanitized AND-of-tokens MATCH (which
    includes a `2020` term) still resolves the hint to this note.
    """
    v = tmp_path / "advault"
    v.mkdir()
    _write_note_file(
        v,
        "Cases/Smith v Jones.md",
        "Smith v. Jones",
        "The Smith v. Jones (2020) decision established the surveillance "
        "precedent. The court weighed the camera budget and the Acme OR Globex "
        "procurement dispute under NEAR(camera budget) review.",
    )
    _write_note_file(
        v,
        "Topics/Camera Budget.md",
        "Camera Budget",
        "The camera budget covers automated license plate readers.",
    )
    return v


def test_search_does_not_crash_on_adversarial_queries(adversarial_vault: Path):
    """Fix 1 (direct): vault_index.search tolerates every adversarial string."""
    from scripts import vault_index

    vault_index.update_index(adversarial_vault)
    for q in _ADVERSARIAL_QUERIES:
        hits = vault_index.search(adversarial_vault, q)  # must NOT raise
        assert isinstance(hits, list)
        # Pure-punctuation / empty queries tokenize to nothing => no-op [].
        if not any(ch.isalnum() for ch in q):
            assert hits == [], f"punctuation-only query {q!r} should be a no-op"


def test_search_sane_adversarial_query_still_finds_note(adversarial_vault: Path):
    """Fix 1: a real FOIA title `Smith v. Jones (2020)` still finds `Smith v. Jones`."""
    from scripts import vault_index

    vault_index.update_index(adversarial_vault)
    hits = vault_index.search(adversarial_vault, "Smith v. Jones (2020)")
    titles = {h["title"] for h in hits}
    assert "Smith v. Jones" in titles, (
        "sanitized query must still resolve the expected note, not just avoid crashing"
    )


def test_resolve_notes_vault_mode_survives_adversarial_titles_and_hints(
    adversarial_vault: Path,
):
    """Fix 1 (through resolve_notes): adversarial titles AND link_hints don't crash.

    Drives every adversarial string as BOTH a note title and a link_hint through
    the vault branch (which calls vault_index.search per spec). Pre-fix this raised
    sqlite3.OperationalError on the first FTS5-syntax string and aborted the batch.
    """
    tax = load_taxonomy()
    specs = [
        {
            "title": q,
            "content": "Body referencing the matter.",
            "link_hints": _ADVERSARIAL_QUERIES,
            "priority": "primary",
        }
        for q in _ADVERSARIAL_QUERIES
    ]

    result = resolve_notes(
        specs, vault_context={"vault_path": str(adversarial_vault)}, taxonomy=tax
    )  # must NOT raise

    assert result["mode"] == "vault"
    assert len(result["placements"]) == len(_ADVERSARIAL_QUERIES)


def test_resolve_notes_vault_mode_sane_hint_resolves_despite_adversaria(
    adversarial_vault: Path,
):
    """Fix 1: a sane hint still resolves end-to-end even amid adversarial hints.

    A plain `Camera Budget` hint must resolve to its vault note via the index even
    when the SAME spec also carries every FTS5-syntax adversarial string as a hint,
    proving sanitization preserves real recall (not just crash-avoidance) and the
    vault-mode matcher still fires. (Recall for the punctuation-bearing
    `Smith v. Jones (2020)` itself is proven at the search() level in
    test_search_sane_adversarial_query_still_finds_note; resolve_notes uses
    EXACT-title matching by design, which the `(2020)` suffix legitimately defeats —
    that matcher is intentionally left untouched.)
    """
    tax = load_taxonomy()
    specs = [
        {
            "title": "Surveillance Roundup",
            "content": "A roundup that cites the budget.",
            "link_hints": _ADVERSARIAL_QUERIES + ["Camera Budget"],
            "priority": "primary",
        }
    ]

    result = resolve_notes(
        specs, vault_context={"vault_path": str(adversarial_vault)}, taxonomy=tax
    )

    resolved = {
        e["target_title"]: e
        for e in result["link_plan"]
        if e.get("target_vault_path")
    }
    # The plain `Camera Budget` hint resolves to its note despite the adversarial
    # hints in the same batch (which earlier would have crashed the whole call).
    assert "Camera Budget" in resolved
    assert resolved["Camera Budget"]["target_vault_path"].endswith("Camera Budget.md")


# --------------------------------------------------------------------------- #
# Fix 2: LIKE-fallback parity is exercised in CI via a subprocess
# --------------------------------------------------------------------------- #


# Inline program run in a child interpreter with FTS5 forced OFF. It builds a tiny
# vault, indexes + searches it through the SAME public API, and prints a JSON
# verdict the parent asserts on. Forcing _FTS5_AVAILABLE=False BEFORE any index
# build is only safe in a fresh process (the flag is a process-wide cache), which
# is exactly why this lives in a subprocess rather than a monkeypatch.
_LIKE_SUBPROC = r'''
import json, sys
from pathlib import Path

repo = Path(sys.argv[1])
vault = Path(sys.argv[2])
sys.path.insert(0, str(repo))

from scripts import vault_index

# Force the FTS5-free LIKE backend before anything touches the db.
vault_index._FTS5_AVAILABLE = False
assert vault_index.fts5_available() is False, "probe override failed"

(vault / "Notes").mkdir(parents=True, exist_ok=True)
(vault / "Notes" / "Camera Procurement.md").write_text(
    "---\ntitle: Camera Procurement\ntags: [budget, surveillance]\n---\n\n"
    "The county camera procurement program funds automated license plate readers.\n",
    encoding="utf-8",
)
(vault / "Notes" / "Unrelated.md").write_text(
    "---\ntitle: Unrelated\n---\n\nNothing to see here about zoning.\n",
    encoding="utf-8",
)

vault_index.update_index(vault)

hits = vault_index.search(vault, "camera procurement")
hit = hits[0] if hits else {}

# Adversarial strings must not crash the LIKE path either (Fix 1 cross-check).
adversarial = ["Smith v. Jones (2020)", "Acme OR Globex", "NEAR(x)", "(", "*", '"']
adversarial_ok = True
try:
    for q in adversarial:
        vault_index.search(vault, q)
except Exception as exc:  # pragma: no cover - only on regression
    adversarial_ok = repr(exc)

print(json.dumps({
    "fts5": vault_index.fts5_available(),
    "hit_keys": sorted(hit.keys()),
    "titles": sorted({h["title"] for h in hits}),
    "note_exists_ci": vault_index.note_exists(vault, "CAMERA procurement"),
    "list_titles": sorted(n["title"] for n in vault_index.list_notes(vault)),
    "adversarial_ok": adversarial_ok,
}))
'''


def test_like_fallback_parity_in_subprocess(tmp_path: Path):
    """Fix 2: with FTS5 forced OFF, the public API keeps the same shape + finds notes.

    Spawns a child interpreter (so the process-wide _FTS5_AVAILABLE cache can be
    flipped to False before any index build), exercises search/note_exists/
    list_notes on a temp vault, and asserts FTS5<->LIKE parity: identical hit shape
    {path,title,tags,excerpt,rank}, the expected note found, case-insensitive
    note_exists, and that adversarial inputs don't crash the LIKE path.
    """
    import json
    import subprocess

    repo_root = Path(__file__).resolve().parents[1]
    sub_vault = tmp_path / "subvault"
    sub_vault.mkdir()

    proc = subprocess.run(
        [sys.executable, "-c", _LIKE_SUBPROC, str(repo_root), str(sub_vault)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"subprocess failed (rc={proc.returncode}):\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )

    payload = json.loads(proc.stdout.strip().splitlines()[-1])

    # The child really ran on the LIKE backend.
    assert payload["fts5"] is False, "subprocess should have FTS5 disabled"
    # Same hit shape the FTS5 path returns.
    assert payload["hit_keys"] == ["excerpt", "path", "rank", "tags", "title"]
    # The expected note is found by the LIKE scan.
    assert "Camera Procurement" in payload["titles"]
    # Parity for the other public entrypoints.
    assert payload["note_exists_ci"] is True, "LIKE-path note_exists must be case-insensitive"
    assert "Camera Procurement" in payload["list_titles"]
    assert "Unrelated" in payload["list_titles"]
    # Adversarial inputs do not crash the LIKE path.
    assert payload["adversarial_ok"] is True, payload["adversarial_ok"]
