"""Taxonomy-as-config + note-spec validation (Task 1.3).

This is the deterministic core of Librarian's classify/structuring layer. It does
two things, both PURE:

* :func:`load_taxonomy` — load the JSON taxonomy config (the bundled neutral example
  by default) and backfill any MISSING top-level key from built-in neutral defaults,
  so a partial caller override still yields a complete taxonomy.
* :func:`validate_note_specs` — take note specs in the neutral input contract
  (references/prior-art.md §3) and return ``{"normalized": [...], "warnings": [...]}``.

The taxonomy lifts research-workflow's hardcoded domain-specific vault conventions
into configuration (prior-art §2 Coupling 3): the content-type enum, tag
ordering/limit, the default folder, folder/frontmatter conventions, and the
MOC-detection regex. The shipped example (``config/taxonomy.example.json``) carries
NEUTRAL defaults — no place/vendor/subject-matter strings — so Magpie's first run
produces sane notes with zero config; a domain user supplies their own
``taxonomy.json`` override.

Design contract — keep this module PURE and deterministic given its inputs:

* Stdlib only (``json``, ``pathlib``). No yaml, no pandas.
* No vault, no vault-index, no network, no clock (``datetime.now``/``time``), no
  randomness. ``validate_note_specs`` never invents a ``created`` timestamp or reads
  the filesystem; it only reshapes the dicts it is handed.
* Validation follows the design's "flags-as-leads, not verdicts" rule: an unknown
  content type, an out-of-range tag count, a missing/invalid ``priority`` produce a
  WARNING and a normalized record — they never drop a spec. The only thing that marks
  a spec as unusable is a missing/blank ``title`` (still returned, but flagged).

Intentionally OUT OF SCOPE here (later tasks / would be overbuild): vault-index
lookups and update-vs-create discovery (portable mode defaults ``action`` to
``create``); wikilink/link_hint realization; folder_map resolution against a real
vault; frontmatter completeness linting against ``frontmatter_fields`` (that belongs
to the writer / an optional lint utility, not this validator).
"""

from __future__ import annotations

import json
from pathlib import Path

__all__ = ["load_taxonomy", "validate_note_specs", "DEFAULT_TAXONOMY"]

# Built-in neutral defaults. These MUST mirror config/taxonomy.example.json so a
# caller config that omits a key (or no config at all) gets the same neutral
# behavior the shipped example documents. Kept here as the in-code source of truth
# for backfill, so load_taxonomy still works even if the example file is absent.
DEFAULT_TAXONOMY: dict = {
    "content_types": [
        "report",
        "reference",
        "entity",
        "event",
        "dataset",
        "analysis",
        "timeline",
        "index",
        "source",
        "note",
    ],
    "tag_order": ["content-type", "location", "domain"],
    "tag_limit": {"min": 2, "max": 5},
    "default_folder": "Inbox",
    "folder_conventions": {"pattern": "{folder}/{slug}.md", "folder_map": {}},
    "frontmatter_fields": ["title", "tags", "source", "created"],
    "moc_pattern": "^_|MOC|Index|Hub",
}

# Allowed enums for the two closed neutral-contract fields (prior-art §3).
_VALID_PRIORITIES = {"primary", "secondary", "scan"}
_VALID_ACTIONS = {"create", "update"}
_DEFAULT_PRIORITY = "secondary"
_DEFAULT_ACTION = "create"

# Path to the bundled neutral example, resolved relative to this file so it works
# regardless of the caller's CWD (this module lives in <repo>/scripts/).
_EXAMPLE_CONFIG = Path(__file__).resolve().parent.parent / "config" / "taxonomy.example.json"


def load_taxonomy(path: str | Path | None = None) -> dict:
    """Load a taxonomy config and backfill missing top-level keys from defaults.

    Args:
        path: path to a JSON taxonomy file. When ``None`` (the default), the bundled
            neutral ``config/taxonomy.example.json`` is loaded.

    Returns:
        A merged taxonomy dict: every key the loaded config supplies wins, and every
        top-level key it OMITS is filled from :data:`DEFAULT_TAXONOMY`. So a partial
        override (e.g. only ``content_types``) still yields a complete, usable
        taxonomy. The merge is top-level only by design — a caller that overrides
        ``tag_limit`` or ``folder_conventions`` replaces the whole sub-object rather
        than deep-merging, which keeps the override semantics predictable.

    Raises:
        FileNotFoundError: an explicit ``path`` does not exist.
        json.JSONDecodeError: the file is not valid JSON.
    """
    source = Path(path) if path is not None else _EXAMPLE_CONFIG
    loaded = json.loads(source.read_text(encoding="utf-8"))

    # Top-level backfill: start from a copy of defaults, overlay the loaded config.
    # `_comment` and any other extra keys in the loaded config pass through untouched.
    merged = dict(DEFAULT_TAXONOMY)
    merged.update(loaded)
    return merged


def _tag_limit_bounds(taxonomy: dict) -> tuple[int | None, int | None]:
    """Return ``(min, max)`` from ``taxonomy['tag_limit']``, tolerating a missing key.

    A taxonomy that omits ``tag_limit`` (or supplies a non-dict) yields ``(None,
    None)`` so the caller simply skips the tag-count check rather than crashing — this
    validator is handed caller-controlled config and stays defensive about it.
    """
    limit = taxonomy.get("tag_limit")
    if not isinstance(limit, dict):
        return (None, None)
    return (limit.get("min"), limit.get("max"))


def _content_type_tag(spec: dict) -> str | None:
    """Resolve a spec's declared content type per the neutral contract.

    Precedence: ``frontmatter_meta.type`` if present, else the FIRST tag in
    ``frontmatter_meta.tags`` (the tag_order convention puts the content-type tag
    first). Returns ``None`` when neither is available.
    """
    meta = spec.get("frontmatter_meta") or {}
    declared = meta.get("type")
    if isinstance(declared, str) and declared:
        return declared
    tags = meta.get("tags")
    if isinstance(tags, list) and tags:
        first = tags[0]
        if isinstance(first, str) and first:
            return first
    return None


def validate_note_specs(specs: list[dict], taxonomy: dict) -> dict:
    """Normalize neutral note specs and collect non-fatal warnings.

    For each spec (an entry of the neutral contract's ``notes_to_create[]``), this:

    * checks ``title`` is present and non-empty (warns, with the spec index, if not);
    * defaults ``priority`` to ``"secondary"`` and ``action`` to ``"create"`` when
      absent or invalid (warning on an INVALID — but not a merely absent — value);
    * resolves ``folder`` from ``frontmatter_meta.folder`` if present, else from
      ``taxonomy['default_folder']``;
    * warns (does NOT reject) when the content-type tag is not in
      ``taxonomy['content_types']`` — per design, a flag is a lead, not a verdict;
    * warns when the tag count falls outside ``taxonomy['tag_limit']``.

    Args:
        specs: list of neutral note-spec dicts.
        taxonomy: a taxonomy dict (typically from :func:`load_taxonomy`).

    Returns:
        ``{"normalized": [...], "warnings": [...]}``. Every input spec yields exactly
        one normalized record (nothing is dropped); ``warnings`` is a flat list of
        human-readable strings, each prefixed with the offending spec's index.

    This function is pure: it reads only ``specs`` and ``taxonomy`` and returns new
    dicts, mutating neither argument.
    """
    content_types = taxonomy.get("content_types") or []
    default_folder = taxonomy.get("default_folder", DEFAULT_TAXONOMY["default_folder"])
    tag_min, tag_max = _tag_limit_bounds(taxonomy)

    normalized: list[dict] = []
    warnings: list[str] = []

    for index, spec in enumerate(specs):
        meta = spec.get("frontmatter_meta") or {}

        # --- title (the only "unusable" condition; still returned, but flagged) ---
        title = spec.get("title")
        if not (isinstance(title, str) and title.strip()):
            warnings.append(f"spec[{index}]: missing or empty 'title'")
            title = title if isinstance(title, str) else ""

        # --- priority: default + warn only on an explicit invalid value ---
        priority = spec.get("priority")
        if priority not in _VALID_PRIORITIES:
            if priority is not None:
                warnings.append(
                    f"spec[{index}]: invalid priority {priority!r}; "
                    f"defaulting to {_DEFAULT_PRIORITY!r}"
                )
            priority = _DEFAULT_PRIORITY

        # --- action: default + warn only on an explicit invalid value ---
        action = spec.get("action")
        if action not in _VALID_ACTIONS:
            if action is not None:
                warnings.append(
                    f"spec[{index}]: invalid action {action!r}; "
                    f"defaulting to {_DEFAULT_ACTION!r}"
                )
            action = _DEFAULT_ACTION

        # --- folder: frontmatter_meta.folder wins, else taxonomy default ---
        folder = meta.get("folder")
        if not (isinstance(folder, str) and folder):
            folder = default_folder

        # --- content type: warn (lead, not verdict) if outside the vocabulary ---
        ctype = _content_type_tag(spec)
        if ctype is not None and ctype not in content_types:
            warnings.append(
                f"spec[{index}]: content type {ctype!r} not in taxonomy "
                f"content_types (treated as a lead, not rejected)"
            )

        # --- tag count within configured limits ---
        tags = meta.get("tags")
        tag_count = len(tags) if isinstance(tags, list) else 0
        if tag_min is not None and tag_count < tag_min:
            warnings.append(
                f"spec[{index}]: {tag_count} tag(s) is below tag_limit min {tag_min}"
            )
        if tag_max is not None and tag_count > tag_max:
            warnings.append(
                f"spec[{index}]: {tag_count} tag(s) exceeds tag_limit max {tag_max}"
            )

        normalized.append(
            {
                "title": title,
                "content": spec.get("content", ""),
                "frontmatter_meta": meta,
                "citations": spec.get("citations", []),
                "link_hints": spec.get("link_hints", []),
                "priority": priority,
                "action": action,
                "folder": folder,
            }
        )

    return {"normalized": normalized, "warnings": warnings}
