"""vault_mode.py — portable-vs-vault routing (Task 1.4, the Coupling-1 seam).

This is the deterministic core that decides, for a batch of neutral note specs
(references/prior-art.md §3), WHERE each note is placed and WHICH wikilinks to
plan — and it is the single seam where Librarian flips between its two modes
(prior-art §2 Coupling 1):

* **Portable (DEFAULT — no ``vault_context``).** No vault, no index, no sqlite.
  Placement = ``taxonomy["default_folder"]`` + ``slug(title)``; ``action`` stays
  as the caller gave it (default ``create``); links are resolved ONLY among the
  current batch's titles plus each spec's ``link_hints`` — there is no
  pre-existing-note lookup. The ``import vault_index`` below lives INSIDE the vault
  branch, so a portable call provably never imports sqlite/vault_index
  (``tests/test_vault_mode.py::test_portable_path_is_sqlite_import_clean``).

* **Vault (``vault_context`` supplied).** Import the adapter, ``update_index``
  FIRST so the index is fresh (prior-art §5 gap #6), then per spec ``search`` the
  index to (a) route ``action`` update-vs-create + resolve the folder from a
  title-matching hit, and (b) build a wikilink edit plan linking each
  ``link_hints`` entity (and intra-batch titles) to existing vault notes.

Purity: aside from the adapter's sqlite I/O in vault mode, ``resolve_notes`` is
pure — no clock, no randomness, no network. The portable path does no I/O at all.

Return shape (both modes)::

    {
      "mode": "portable" | "vault",
      "placements": [ {title, folder, path, action, priority}, ... ],
      "link_plan":  [ {source_title, target_title, resolved_in_batch,
                       target_vault_path}, ... ],
    }

``placements[i].path`` is the relative ``<folder>/<slug>.md`` (portable) or the
index-resolved vault-relative path (vault-mode update target). Each ``link_plan``
edge says which note (``source_title``) should link to which entity
(``target_title``), whether that entity was satisfied by another note in THIS
batch (``resolved_in_batch``), and—vault mode only—the vault-relative path of the
existing note it resolves to (``target_vault_path``; ``None`` in portable mode and
for unresolved hints). The live LLM wikilink AUTHORING (exact ``find``/``replace``
text) is the wikilink-scanner agent's job; this module produces the deterministic,
unit-testable edit-plan skeleton it works from.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from scripts.taxonomy import DEFAULT_TAXONOMY, load_taxonomy
from scripts.write_note import slug

__all__ = ["resolve_notes"]

_DEFAULT_ACTION = "create"
_DEFAULT_PRIORITY = "secondary"

# How many search hits to consider when resolving a hint/title to a vault note.
_SEARCH_LIMIT = 5


def _spec_title(spec: dict) -> str:
    """Return the spec's title as a string ("" if missing/None/non-str)."""
    title = spec.get("title")
    return title if isinstance(title, str) else ""


def _spec_action(spec: dict) -> str:
    """Caller-supplied action, defaulting to ``create`` when absent/blank."""
    action = spec.get("action")
    return action if action in {"create", "update"} else _DEFAULT_ACTION


def _spec_priority(spec: dict) -> str:
    priority = spec.get("priority")
    return priority if priority in {"primary", "secondary", "scan"} else _DEFAULT_PRIORITY


def _link_hints(spec: dict) -> list[str]:
    """Return the spec's link_hints as a clean list of non-empty strings."""
    hints = spec.get("link_hints")
    if not isinstance(hints, list):
        return []
    return [h for h in hints if isinstance(h, str) and h.strip()]


def _resolve_taxonomy(taxonomy: dict | None) -> dict:
    """Use the supplied taxonomy, else load the bundled neutral default."""
    if taxonomy is None:
        return load_taxonomy()
    return taxonomy


def _default_folder(taxonomy: dict) -> str:
    return taxonomy.get("default_folder") or DEFAULT_TAXONOMY["default_folder"]


def _safe_relative_folder(folder: str, taxonomy: dict) -> str:
    """Turn a caller/classifier folder into a SAFE RELATIVE subpath under the base.

    The ``folder`` may originate from an LLM classifier running over adversarial FOIA
    content (see ``agents/classify-agent.md``), so it is UNTRUSTED: a value like
    ``../outside``, ``../../etc/passwd``, ``/etc``, ``C:\\Windows\\system32`` or
    ``a/../../b`` must never let a returned placement path escape the intended base
    (``out_dir`` in portable mode, the vault root in vault mode). This is the hard
    guarantee — :func:`scripts.taxonomy.validate_note_specs` only *flags* such folders.

    Sanitization rule (defense in depth — neuter, don't trust):

    * Split on BOTH ``/`` and ``\\`` so a Windows-style separator can't smuggle a
      component past a POSIX-only split.
    * Strip a Windows drive-letter prefix (e.g. ``C:``) from any component.
    * Drop empty components, ``.``, and ``..`` — this is what defeats upward
      traversal; a leading separator (absolute path) simply yields a leading empty
      component that is dropped, so absolute paths become relative.
    * Re-join the survivors with forward slashes.

    If nothing usable survives (the folder was entirely traversal/separators, e.g.
    ``../..`` or ``/``), fall back to the taxonomy default folder so the note still
    lands somewhere sane under the base rather than at the base root by accident.
    """
    components: list[str] = []
    # Normalize Windows separators to POSIX, then split — handles mixed a\b/c too.
    for raw in folder.replace("\\", "/").split("/"):
        component = raw.strip()
        # Strip a drive-letter prefix like "C:" (or "C:foo") so it can't anchor a path.
        if len(component) >= 2 and component[1] == ":" and component[0].isalpha():
            component = component[2:]
        if not component or component in (".", ".."):
            # Empty (leading/trailing/duplicate separator, absolute-path leading "/"),
            # current-dir ".", or upward "..": all dropped so the path stays in-base.
            continue
        components.append(component)

    if not components:
        return _default_folder(taxonomy)
    return "/".join(components)


def _spec_folder(spec: dict, taxonomy: dict) -> str:
    """Folder the classifier/validator chose for this note, else the taxonomy default.

    The neutral note spec has NO top-level ``folder``; placement lives in
    ``frontmatter_meta["folder"]`` (what :func:`scripts.taxonomy.validate_note_specs`
    reads). Honor it here so ``resolve_notes`` does not discard the chosen placement
    (the shipped contract in ``skills/librarian/SKILL.md`` and
    ``agents/classify-agent.md``). Mirrors the validator's tolerance: a non-dict
    ``frontmatter_meta`` (or a missing/blank/non-str ``folder``) falls back to the
    default rather than crashing.

    The chosen folder is UNTRUSTED (LLM-/caller-supplied) and is passed through
    :func:`_safe_relative_folder` so a traversal value (``../outside``, ``/etc``,
    ``C:\\Windows``, ``a/../../b``) cannot escape the base — every placement path this
    feeds (portable ``<folder>/<slug>.md`` and the vault create/no-match path) stays
    under ``out_dir``/the vault root. The vault UPDATE path does not use this value (it
    adopts the existing note's real folder), so adopted real folders are untouched.
    """
    meta = spec.get("frontmatter_meta")
    if isinstance(meta, dict):
        folder = meta.get("folder")
        if isinstance(folder, str) and folder:
            return _safe_relative_folder(folder, taxonomy)
    return _default_folder(taxonomy)


def _portable_path(folder: str, title: str) -> str:
    """Relative ``<folder>/<slug>.md`` placement (forward-slashed, slug fallback)."""
    stem = slug(title) or "untitled"
    return str(PurePosixPath(folder) / f"{stem}.md")


def _resolve_portable(specs: list[dict], taxonomy: dict) -> dict:
    """Portable placement + batch/hint-only link plan. NO index, NO sqlite.

    Placement is the classifier-selected ``frontmatter_meta["folder"]`` (else the
    taxonomy ``default_folder``) + slug; ``action`` is honored as given. Links are
    resolved only among this batch's titles plus each spec's ``link_hints``: a
    hint that matches another batch note's title is a real intra-batch link
    (``resolved_in_batch=True``); a hint with no batch match is still surfaced as
    an UNRESOLVED edge (``resolved_in_batch=False``, ``target_vault_path=None``) —
    there is no index to resolve it against, by design.
    """
    placements: list[dict] = []
    batch_titles: set[str] = set()
    for spec in specs:
        title = _spec_title(spec)
        batch_titles.add(title)
        # Honor the classifier-selected folder (frontmatter_meta.folder), sanitized to
        # a safe in-base relative subpath; else the taxonomy default.
        folder = _spec_folder(spec, taxonomy)
        placements.append(
            {
                "title": title,
                "folder": folder,
                "path": _portable_path(folder, title),
                "action": _spec_action(spec),
                "priority": _spec_priority(spec),
            }
        )

    link_plan: list[dict] = []
    for spec in specs:
        source_title = _spec_title(spec)
        for hint in _link_hints(spec):
            # A hint linking the note to itself is meaningless; skip it.
            if hint == source_title:
                continue
            link_plan.append(
                {
                    "source_title": source_title,
                    "target_title": hint,
                    # Resolved iff another note in THIS batch carries that title.
                    "resolved_in_batch": hint in batch_titles,
                    "target_vault_path": None,  # portable mode never resolves to a vault note
                }
            )

    return {"mode": "portable", "placements": placements, "link_plan": link_plan}


def _best_title_match(hits: list[dict], wanted: str) -> dict | None:
    """Return the hit whose title EXACTLY equals ``wanted`` (case-insensitive), else None.

    Used both for update-vs-create routing (does an incoming title already exist?)
    and for resolving a link hint to a concrete existing note. Exact title match is
    the conservative choice — a fuzzy top-hit could mislink unrelated notes.
    """
    wl = wanted.strip().lower()
    for hit in hits:
        if (hit.get("title") or "").strip().lower() == wl:
            return hit
    return None


def _resolve_vault(specs: list[dict], taxonomy: dict, vault_context: dict) -> dict:
    """Vault placement + index-resolved link plan. Imports the adapter HERE only.

    Steps (mirroring research-workflow Stage 8, prior-art §1):
      1. ``update_index`` FIRST so the index reflects the vault as it is now
         (gap #6 — the adapter owns freshness; Librarian has no Stage-0 refresh).
      2. For each spec, ``search`` by title: an exact title hit => ``action`` is
         ``update`` and the folder/path come from that existing note.
      3. For each ``link_hints`` entity (and intra-batch titles), ``search`` and
         record an edge to the matching existing vault note when one is found.

    The ``import`` is intentionally local to this function: it must NOT execute on
    the portable path, which is the whole Coupling-1 guarantee.
    """
    from scripts import vault_index  # noqa: PLC0415 — local by design (Coupling 1)

    vault_path = vault_context["vault_path"]

    # (1) Refresh the index before any query (gap #6).
    vault_index.update_index(vault_path)

    default_folder = _default_folder(taxonomy)
    batch_titles = {_spec_title(spec) for spec in specs}

    # --- (2) placements: update-vs-create routing from a title-matching hit ---
    placements: list[dict] = []
    for spec in specs:
        title = _spec_title(spec)
        action = _spec_action(spec)
        # CREATE / no-match default: honor the classifier-selected folder
        # (frontmatter_meta.folder), sanitized to a safe in-base relative subpath;
        # else taxonomy default. A title-match hit below overrides this with the
        # existing note's real folder/path (UPDATE wins, and is left un-sanitized
        # because it is the vault's own real folder, not caller input).
        folder = _spec_folder(spec, taxonomy)
        path = _portable_path(folder, title)

        if title:
            hits = vault_index.search(vault_path, title, limit=_SEARCH_LIMIT)
            match = _best_title_match(hits, title)
            if match is not None:
                # An existing note with this exact title => route as an update and
                # adopt its real vault path/folder (do not invent a new placement).
                action = "update"
                path = match["path"]
                parent = str(PurePosixPath(path).parent)
                folder = parent if parent != "." else default_folder

        placements.append(
            {
                "title": title,
                "folder": folder,
                "path": path,
                "action": action,
                "priority": _spec_priority(spec),
            }
        )

    # --- (3) link plan: resolve each hint / intra-batch title to a vault note ---
    link_plan: list[dict] = []
    for spec in specs:
        source_title = _spec_title(spec)
        for hint in _link_hints(spec):
            if hint == source_title:
                continue
            resolved_in_batch = hint in batch_titles
            target_vault_path = None
            hits = vault_index.search(vault_path, hint, limit=_SEARCH_LIMIT)
            match = _best_title_match(hits, hint)
            if match is not None:
                target_vault_path = match["path"]
            link_plan.append(
                {
                    "source_title": source_title,
                    "target_title": hint,
                    "resolved_in_batch": resolved_in_batch,
                    "target_vault_path": target_vault_path,
                }
            )

    return {"mode": "vault", "placements": placements, "link_plan": link_plan}


def resolve_notes(
    specs: list[dict],
    vault_context: dict | None = None,
    taxonomy: dict | None = None,
) -> dict:
    """Route a batch of note specs to placements + a wikilink edit plan.

    Dispatches on ``vault_context``: absent => the portable-first default (no index,
    no sqlite, batch/hint-only links); present (with a ``vault_path``) => vault mode
    (refresh index, then resolve update-vs-create and existing-note links from it).

    Args:
        specs: list of neutral note specs (prior-art §3). Each may carry ``title``,
            ``link_hints``, ``action`` (``create``/``update``), and ``priority``;
            other neutral fields are ignored here (placement/linking only).
        vault_context: ``None`` for portable (default). To enable vault mode, pass a
            dict with at least ``{"vault_path": <str>}`` (the prior-art vault signal;
            extra keys like ``existing_notes_found`` are accepted and ignored here).
        taxonomy: a taxonomy dict (from :func:`scripts.taxonomy.load_taxonomy`); when
            ``None`` the bundled neutral default is loaded. Only ``default_folder`` is
            consulted for placement.

    Returns:
        ``{"mode", "placements", "link_plan"}`` as documented at the module top.

    Raises:
        KeyError: ``vault_context`` is supplied but lacks ``vault_path``.
    """
    taxonomy = _resolve_taxonomy(taxonomy)

    if vault_context is None:
        # PORTABLE: import-clean of sqlite/vault_index — the adapter is never reached.
        return _resolve_portable(specs, taxonomy)

    if "vault_path" not in vault_context:
        raise KeyError(
            "vault_context was supplied but is missing required 'vault_path' "
            "(omit vault_context entirely for portable mode)"
        )
    return _resolve_vault(specs, taxonomy, vault_context)
