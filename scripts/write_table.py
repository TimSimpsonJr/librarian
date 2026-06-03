"""Tabular/CSV exhibit writer (Task 1.2).

``write_table(rows, out_dir, name, columns=None)`` writes ONE tabular payload
(a stats table, a redacted exhibit) to BOTH a ``.csv`` file and a
GitHub-flavored Markdown-table mirror string, then returns a small result dict.
The CSV is the portable artifact; the Markdown string is for a caller to embed
inline in a note / vault (Magpie design §5.7, references/prior-art.md).

This is the tabular sibling of :mod:`scripts.write_note`. It reuses that
module's :func:`~scripts.write_note.slug` for the filename stem so the two
writers cannot drift on slugging rules.

Design contract — keep this function PURE and deterministic given its inputs:

* Stdlib only (``csv``, ``pathlib``, plus the reused ``slug``). No pandas, no
  network, no clock (``datetime.now``/``time``), no randomness.
* No vault, no config/taxonomy, no note-embedding, no vault placement. The
  Markdown mirror is *returned* for a caller to embed; this module never decides
  where it goes.

KEY semantic difference from :func:`~scripts.write_note.write_note`: a CSV
exhibit is **derived/regenerable** data, so overwriting an existing CSV is the
EXPECTED behavior — re-running an analysis refreshes the exhibit. The
never-clobber guard that ``write_note`` applies is deliberately NOT applied here.

Intentionally OUT OF SCOPE here (later tasks / would be overbuild): pandas or any
dataframe layer, note/frontmatter assembly, vault placement, config-driven
column validation.
"""

from __future__ import annotations

import csv
from pathlib import Path

from scripts.write_note import slug

__all__ = ["write_table"]


def _derive_columns(rows: list[dict]) -> list[str]:
    """Return the union of keys across ``rows`` in first-appearance order.

    Stable for heterogeneous dicts: ``[{"a": 1}, {"b": 2}]`` -> ``["a", "b"]``.
    A plain ``dict`` is used as an insertion-ordered set (py3.7+); the value is
    irrelevant, only the key order matters.
    """
    columns: dict[str, None] = {}
    for row in rows:
        for key in row:
            columns.setdefault(key, None)
    return list(columns)


def _csv_cell(value) -> str:
    """Render one value for a CSV cell: ``None``/missing -> ``""``; else ``str()``.

    The ``csv`` module itself handles quoting/escaping of commas, quotes, and
    embedded newlines, so this only normalizes ``None`` and stringifies non-str
    scalars (a str passes through unchanged).
    """
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _md_cell(value) -> str:
    """Render one value for a Markdown table cell.

    ``None``/missing -> empty; ``|`` is escaped as ``\\|`` (else it would break
    the column boundary); embedded newlines/CRs are collapsed to a single space
    (a Markdown table row cannot contain a raw newline). Other values are
    ``str()``'d. Escaping order matters: stringify first, replace newlines, then
    escape pipes.
    """
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    # Collapse any CR/LF (incl. CRLF) to single spaces so the row stays on one
    # physical line. Replace "\r\n" first so a CRLF does not become two spaces.
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    # Escape the column separator so a literal pipe does not split the cell.
    text = text.replace("|", r"\|")
    return text


def _build_markdown(rows: list[dict], columns: list[str]) -> str:
    """Build the GFM Markdown-table mirror string.

    Returns ``""`` when there are no columns (an empty payload with no explicit
    columns has nothing to render). Otherwise emits a header row, the
    ``| --- | --- |`` separator, and one row per dict (missing keys -> empty
    cells). No trailing newline — the caller controls surrounding whitespace
    when embedding.
    """
    if not columns:
        return ""
    header = "| " + " | ".join(_md_cell(c) for c in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, separator]
    for row in rows:
        cells = [_md_cell(row.get(col)) for col in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_table(
    rows: list[dict],
    out_dir: str | Path,
    name: str,
    columns: list[str] | None = None,
) -> dict:
    """Write ``rows`` as a CSV file plus a Markdown-table mirror; return a result.

    Args:
        rows: list of dicts, one per table row. Keys are column names; values are
            cell values (``None``/missing -> empty cell, non-str scalars -> their
            ``str()``).
        out_dir: directory to write the CSV into; created if missing.
        name: human name for the exhibit; the CSV stem is ``slug(name)``.
        columns: optional explicit column order. When given, exactly these
            columns are emitted in this order (row keys not listed are dropped,
            missing keys are empty cells). When ``None``, columns are the union
            of keys across all rows in first-appearance order.

    Returns:
        ``{"csv_path": str, "markdown": str, "columns": list[str],
        "row_count": int}``.

    Overwriting an existing CSV is allowed and expected (a CSV exhibit is
    regenerable; re-running an analysis refreshes it).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cols = list(columns) if columns is not None else _derive_columns(rows)

    csv_path = out_dir / f"{slug(name) or 'untitled'}.csv"
    # newline="" is the documented contract for the csv module so it controls
    # line endings itself and embedded newlines in quoted fields survive.
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # An empty payload with no explicit columns writes no header (no columns
        # are known); with explicit columns it writes a header-only file.
        if cols:
            writer.writerow(cols)
        for row in rows:
            writer.writerow([_csv_cell(row.get(col)) for col in cols])

    markdown = _build_markdown(rows, cols)

    return {
        "csv_path": str(csv_path),
        "markdown": markdown,
        "columns": cols,
        "row_count": len(rows),
    }
