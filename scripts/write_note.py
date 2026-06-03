"""Portable Markdown note writer (Task 1.1).

``write_note(spec, out_dir)`` writes ONE Markdown note from a neutral note spec
(references/prior-art.md §3) and returns a small result dict. This is the
**portable-first** path that consolidates research-workflow's Stage-7 write rules
(``research-workflow/skills/research/SKILL.md`` §7c.v — frontmatter block, body,
``## Sources`` assembly, slug/placement, never-clobber guard) into a single
callable module. There is no upstream ``write_note.py``; this authors a script
from what was previously orchestrator prose plus ``state.py`` side-effects.

Design contract — keep this function PURE and deterministic given its inputs:

* No vault, no vault-index, no wikilink lookups (those are Task 1.4).
* No network, no clock (``datetime.now``/``time``), no randomness. Any ``created``
  timestamp or other metadata is supplied by the caller via
  ``spec["frontmatter_meta"]`` — the writer never invents one (prior-art §5.4).
* No ``state.py`` side-effects: the function returns a result and lets the caller
  record run state (prior-art §1 boundary marker, §5.1).

Intentionally OUT OF SCOPE here (later tasks / would be overbuild):

* ``action: "update"`` merge logic and mtime-conflict merging. Only ``"create"``
  plus the never-clobber guard is implemented; ``"update"`` is treated as out of
  scope (an explicit-target merge belongs to a later task once a caller needs it).
* ``link_hints`` / wikilink realization, ``priority`` multi-note sorting,
  ``vault_context`` handling, config/taxonomy tag-enum validation. These keys may
  be present in the spec but are ignored by this writer.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path

import yaml

__all__ = ["write_note", "slug"]


# Characters illegal in Windows filenames, plus the slug-stripping rule from the
# Task 1.1 spec (also covers the POSIX-unsafe "/").
_WINDOWS_UNSAFE = r'<>:"/\\|?*'
_UNSAFE_RE = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")
_WS_RE = re.compile(r"\s+")
_DASH_RUN_RE = re.compile(r"-{2,}")


def slug(title: str) -> str:
    """Slugify ``title`` into a filesystem-safe stem.

    Lowercases, replaces whitespace runs with ``-``, strips characters unsafe on
    Windows filesystems (``<>:"/\\|?*`` and control chars), collapses repeated
    hyphens, and trims leading/trailing hyphens. Deterministic.
    """
    text = title.lower()
    text = _WS_RE.sub("-", text)          # whitespace runs -> single hyphen
    text = _UNSAFE_RE.sub("", text)       # drop filesystem-unsafe + control chars
    text = _DASH_RUN_RE.sub("-", text)    # collapse repeated hyphens
    text = text.strip("-")                # trim leading/trailing hyphens
    return text


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _render_citation(citation) -> str:
    """Render a single citation to its ``- `` bullet text (without the leading bullet).

    Shapes (prior-art §3, §5.3 — the structured-ref code path beyond plain URLs):

    * ``str`` http(s) URL          -> ``<URL>`` (angle-bracketed so Markdown auto-links).
    * other ``str``                -> the string verbatim.
    * ``{url, title?}``            -> ``[title](url)`` when title present, else ``<url>``.
    * ``{doc_id, page?}``          -> ``doc_id`` plus ``, p. page`` when a page is given.
    * any other ``dict``           -> compact, deterministic ``key: value`` join (sorted).
    """
    if isinstance(citation, str):
        return f"<{citation}>" if _is_url(citation) else citation

    if isinstance(citation, dict):
        if "url" in citation:
            url = citation["url"]
            title = citation.get("title")
            return f"[{title}]({url})" if title else f"<{url}>"
        if "doc_id" in citation:
            rendered = str(citation["doc_id"])
            if "page" in citation:
                rendered += f", p. {citation['page']}"
            return rendered
        # Arbitrary dict -> deterministic compact rendering (sorted key: value).
        return ", ".join(f"{k}: {citation[k]}" for k in sorted(citation))

    # Fallback for any other type: deterministic str().
    return str(citation)


def _build_frontmatter(spec: dict) -> str:
    """Build the YAML frontmatter block (including the ``---`` fences).

    Title leads; remaining keys come from ``frontmatter_meta`` in their given
    order. ``sort_keys=False`` preserves order; ``allow_unicode=True`` keeps
    em-dashes / accented names intact rather than ``\\uXXXX``-escaping them.
    """
    fm = OrderedDict()
    fm["title"] = spec["title"]
    for key, value in spec.get("frontmatter_meta", {}).items():
        fm[key] = value

    body = yaml.safe_dump(
        dict(fm),  # safe_dump handles plain dicts; py3.7+ preserves insertion order
        sort_keys=False,
        allow_unicode=True,
    )
    return f"---\n{body}---\n"


def _build_sources(citations) -> str:
    """Build the ``## Sources`` section, or ``""`` when there are no citations."""
    if not citations:
        return ""
    bullets = "\n".join(f"- {_render_citation(c)}" for c in citations)
    return f"## Sources\n\n{bullets}\n"


def write_note(spec: dict, out_dir: str | Path) -> dict:
    """Write one Markdown note from ``spec`` into ``out_dir``; return a result dict.

    Result shapes:

    * wrote the file -> ``{"path": <str>, "action": "create", "skipped": False}``
    * target existed -> ``{"path": <str>, "action": "create",
      "skipped": True, "reason": "exists"}`` (never clobbers; nothing written).

    Args:
        spec: a neutral note spec (prior-art §3). Required: ``title``, ``content``.
            Optional used here: ``frontmatter_meta``, ``citations``. Other keys
            (``link_hints``, ``priority``, ``action``, ``vault_context``) are
            ignored by this portable writer.
        out_dir: directory to write into; created if missing.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    target = out_dir / f"{slug(spec['title'])}.md"

    # Never clobber an existing note (prior-art §5.2 — portable mode cannot
    # discover an update; it only honors create + this guard).
    if target.exists():
        return {
            "path": str(target),
            "action": "create",
            "skipped": True,
            "reason": "exists",
        }

    frontmatter = _build_frontmatter(spec)
    body = spec.get("content", "")
    sources = _build_sources(spec.get("citations"))

    parts = [frontmatter, body]
    if sources:
        parts.append(sources)
    # Blank line between the frontmatter block, the body, and the Sources section
    # (spec: "blank line between"). rstrip each block so the joiner controls spacing.
    document = "\n\n".join(part.rstrip("\n") for part in parts) + "\n"

    target.write_text(document, encoding="utf-8")

    return {"path": str(target), "action": "create", "skipped": False}
