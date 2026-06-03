"""Portable Markdown note writer (Task 1.1).

``write_note(spec, out_dir)`` writes ONE Markdown note from a neutral note spec
(references/prior-art.md §3) and returns a small result dict. This is the
**portable-first** path that consolidates research-workflow's Stage-7 write rules
(``research-workflow/skills/research/SKILL.md`` §7c.v — frontmatter block, body,
``## Sources`` assembly, slug/placement, never-clobber guard) into a single
callable module. There is no upstream ``write_note.py``; this authors a script
from what was previously orchestrator prose plus ``state.py`` side-effects.

This is the SHARED writer that both Magpie (structured ``{doc_id, page}``
citations, batch writes) and Research (rich frontmatter) call, so it is
deliberately robust against partial/malformed input rather than assuming a
single well-behaved caller.

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


# Characters illegal in Windows filenames (also covers the POSIX-unsafe "/").
# The slug regex is derived from this set so the two cannot drift; control chars
# (\x00-\x1f) are appended because they are unsafe everywhere but awkward to list.
_WINDOWS_UNSAFE = r'<>:"/\|?*'
_UNSAFE_RE = re.compile(f"[{re.escape(_WINDOWS_UNSAFE)}\x00-\x1f]")
_WS_RE = re.compile(r"\s+")
_DASH_RUN_RE = re.compile(r"-{2,}")


def slug(title: str) -> str:
    """Slugify ``title`` into a filesystem-safe stem.

    Lowercases, replaces whitespace runs with ``-``, strips characters unsafe on
    Windows filesystems (``<>:"/\\|?*`` and control chars), collapses repeated
    hyphens, and trims leading/trailing hyphens. Deterministic.

    May return ``""`` for a title made entirely of unsafe/whitespace characters;
    callers that need a filename stem should fall back to ``"untitled"``.
    """
    text = title.lower()
    text = _WS_RE.sub("-", text)          # whitespace runs -> single hyphen
    text = _UNSAFE_RE.sub("", text)       # drop filesystem-unsafe + control chars
    text = _DASH_RUN_RE.sub("-", text)    # collapse repeated hyphens
    text = text.strip("-")                # trim leading/trailing hyphens
    return text


class _NoAliasSafeDumper(yaml.SafeDumper):
    """SafeDumper that never emits YAML anchors/aliases.

    PyYAML emits ``&id001`` / ``*id001`` anchors when the same object is
    referenced under two keys, but Obsidian's frontmatter parser cannot read
    them. Forcing ``ignore_aliases`` to always return True makes such shared
    objects serialize by value under every key instead.
    """

    def ignore_aliases(self, data) -> bool:  # noqa: D401 - matches PyYAML API
        return True


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _render_citation(citation) -> str:
    """Render a single citation to its ``- `` bullet text (without the leading bullet).

    Shapes (prior-art §3, §5.3 — the structured-ref code path beyond plain URLs):

    * ``str`` http(s) URL          -> ``<URL>`` (angle-bracketed so Markdown auto-links).
    * other ``str``                -> the string verbatim.
    * ``{url, title?}``            -> ``[title](url)`` when both truthy, else ``<url>``.
    * ``{doc_id, page?}``          -> ``doc_id`` plus ``, p. page`` when page is not None.
    * any other ``dict``           -> compact, deterministic ``key: value`` join (sorted).

    URL and doc_id branches gate on TRUTHINESS, not key presence, so a partial or
    empty structured ref (``{"url": None}``, ``{"doc_id": ""}``) falls through to
    the generic ``key: value`` form rather than emitting junk like ``<None>`` or
    ``<>``. ``page`` is gated on ``is not None`` so a legitimate ``page == 0``
    still renders (``X, p. 0``).
    """
    if isinstance(citation, str):
        return f"<{citation}>" if _is_url(citation) else citation

    if isinstance(citation, dict):
        if citation.get("url"):
            url = citation["url"]
            title = citation.get("title")
            return f"[{title}]({url})" if title else f"<{url}>"
        if citation.get("doc_id"):
            rendered = str(citation["doc_id"])
            if citation.get("page") is not None:
                rendered += f", p. {citation['page']}"
            return rendered
        # Arbitrary / malformed dict -> deterministic compact rendering
        # (sorted key: value). Honestly shows the bad ref instead of faking a link.
        return ", ".join(f"{k}: {citation[k]}" for k in sorted(citation))

    # Fallback for any other type: deterministic str().
    return str(citation)


def _resolve_title(spec: dict) -> str:
    """Return the validated, stripped title or raise a clear error.

    ``title`` is required. Missing/``None``/non-``str``/blank-after-strip raises
    ``ValueError``/``TypeError`` (message names ``title``) instead of leaking a
    bare ``KeyError`` or producing a degenerate filename.
    """
    if "title" not in spec or spec["title"] is None:
        raise ValueError("note spec is missing required field 'title'")
    title = spec["title"]
    if not isinstance(title, str):
        raise TypeError(
            f"'title' must be a str, got {type(title).__name__}"
        )
    if not title.strip():
        raise ValueError("'title' must not be blank")
    return title


def _resolve_content(spec: dict) -> str:
    """Return the body string, treating missing/``None`` content as ``""``.

    A present ``content`` that is neither ``str`` nor ``None`` (e.g. int/list/dict)
    raises ``TypeError`` naming the field and the offending type — this is the
    shared writer, so a structured caller passing the wrong type fails loudly
    rather than stringifying a list into the body.
    """
    content = spec.get("content")
    if content is None:
        return ""
    if not isinstance(content, str):
        raise TypeError(
            f"'content' must be a str or None, got {type(content).__name__}"
        )
    return content


def _build_frontmatter(spec: dict, title: str) -> str:
    """Build the YAML frontmatter block (including the ``---`` fences).

    Title leads; remaining keys come from ``frontmatter_meta`` in their given
    order. ``sort_keys=False`` preserves order; ``allow_unicode=True`` keeps
    em-dashes / accented names intact rather than ``\\uXXXX``-escaping them;
    ``width`` is set large so long scalar values (e.g. a long ``summary:``) are
    not wrapped onto continuation lines; ``_NoAliasSafeDumper`` suppresses
    anchors/aliases that Obsidian cannot parse.
    """
    fm = OrderedDict()
    fm["title"] = title
    for key, value in spec.get("frontmatter_meta", {}).items():
        fm[key] = value

    body = yaml.dump(
        dict(fm),  # dump handles plain dicts; py3.7+ preserves insertion order
        Dumper=_NoAliasSafeDumper,
        sort_keys=False,
        allow_unicode=True,
        width=4096,  # avoid PyYAML wrapping long scalars at ~80 cols
    )
    return f"---\n{body}---\n"


def _build_sources(citations) -> str:
    """Build the ``## Sources`` section, or ``""`` when there are no citations."""
    if not citations:
        return ""
    bullets = "\n".join(f"- {_render_citation(c)}" for c in citations)
    return f"## Sources\n\n{bullets}\n"


def _build_document(spec: dict, title: str) -> str:
    """Assemble the full Markdown document text (frontmatter + body + sources).

    Pure string construction so the never-clobber guard can compare the would-be
    content against an existing file before deciding to write. ``title`` is the
    already-validated title (see :func:`_resolve_title`).
    """
    frontmatter = _build_frontmatter(spec, title)
    body = _resolve_content(spec)
    sources = _build_sources(spec.get("citations"))

    parts = [frontmatter, body]
    if sources:
        parts.append(sources)
    # Blank line between the frontmatter block, the body, and the Sources section
    # (spec: "blank line between"). rstrip each block so the joiner controls spacing.
    return "\n\n".join(part.rstrip("\n") for part in parts) + "\n"


def write_note(spec: dict, out_dir: str | Path) -> dict:
    """Write one Markdown note from ``spec`` into ``out_dir``; return a result dict.

    Result shapes:

    * wrote the file -> ``{"path": <str>, "action": "create", "skipped": False}``
    * target existed, identical content -> ``{"path", "action": "create",
      "skipped": True, "reason": "identical"}`` (idempotent re-run).
    * target existed, DIFFERENT content -> ``{"path", "action": "create",
      "skipped": True, "reason": "collision"}`` (a different note slugged to the
      same filename — honestly flagged, never overwritten).

    The never-clobber guard compares the would-be document against the existing
    file's bytes so a genuine slug collision is not silently dropped as if it
    were an idempotent re-run.

    Args:
        spec: a neutral note spec (prior-art §3). Required: ``title``. Optional:
            ``content`` (missing/None -> empty body), ``frontmatter_meta``,
            ``citations``. Other keys (``link_hints``, ``priority``, ``action``,
            ``vault_context``) are ignored by this portable writer.
        out_dir: directory to write into; created if missing.

    Raises:
        ValueError: ``title`` is missing/None/blank.
        TypeError: ``title`` is non-str, or ``content`` is a non-str/non-None type.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    title = _resolve_title(spec)
    document = _build_document(spec, title)
    target = out_dir / f"{slug(title) or 'untitled'}.md"

    # Never clobber an existing note (prior-art §5.2). Compare content so an
    # identical re-run and a distinct slug-collision are reported honestly and
    # differently — neither overwrites.
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        reason = "identical" if existing == document else "collision"
        return {
            "path": str(target),
            "action": "create",
            "skipped": True,
            "reason": reason,
        }

    target.write_text(document, encoding="utf-8")

    return {"path": str(target), "action": "create", "skipped": False}
