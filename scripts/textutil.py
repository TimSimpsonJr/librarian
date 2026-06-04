"""Shared stdlib-only text utilities (slugging).

This module holds the single :func:`slug` implementation that BOTH the Markdown
note writer (:mod:`scripts.write_note`) and the tabular writer
(:mod:`scripts.write_table`) use for filename stems, so the two writers cannot
drift on slugging rules.

Design contract — keep this module PURE and stdlib-only:

* Stdlib only (``re``). No yaml, no pandas, no network, no clock
  (``datetime.now``/``time``), no randomness.

It deliberately carries NO frontmatter/YAML logic: ``write_table`` must be able
to import ``slug`` without transitively importing PyYAML (which lives in
:mod:`scripts.write_note`), preserving ``write_table``'s stdlib-only contract.
"""

from __future__ import annotations

import re

__all__ = ["slug"]


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
