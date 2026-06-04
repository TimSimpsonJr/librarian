"""Tests for the tabular/CSV writer (Task 1.2, scripts/write_table.py).

Portable-first contract (references/prior-art.md §5.7, Magpie design §5.7):
``write_table`` is a PURE function — deterministic given (rows, out_dir, name,
columns), stdlib only, no vault/config/network/clock. A CSV exhibit is
*derived/regenerable* data, so unlike ``write_note`` it MAY overwrite an
existing file (re-running an analysis refreshes the exhibit).

These tests assert real on-disk structure: the CSV is re-read and parsed with
the stdlib ``csv`` reader (round-trip), and the Markdown mirror is inspected
line by line — rather than mocking the writer's internals.
"""

import csv
import sys
from pathlib import Path

from scripts.textutil import slug
from scripts.write_table import write_table


def _read_csv_rows(path: Path) -> list[list[str]]:
    """Re-read a CSV file with the stdlib reader (round-trip assertion helper).

    ``newline=""`` is the documented contract for the ``csv`` module so embedded
    newlines inside quoted fields are not mangled on any platform.
    """
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def _md_lines(markdown: str) -> list[str]:
    """Split the markdown table into non-trailing-empty physical lines."""
    return markdown.splitlines()


# --- Basic: header + rows, CSV round-trip, markdown mirror, return dict -------

def test_basic_table_csv_and_markdown(tmp_path):
    rows = [{"agency": "X", "count": 5}, {"agency": "Y", "count": 3}]
    result = write_table(rows, tmp_path, "Agency Counts")

    # --- return contract ---
    assert result["columns"] == ["agency", "count"]
    assert result["row_count"] == 2
    expected_path = tmp_path / f"{slug('Agency Counts')}.csv"
    assert result["csv_path"] == str(expected_path)
    assert expected_path.exists(), "CSV must be written at out_dir/<slug(name)>.csv"

    # --- CSV round-trips via the stdlib reader ---
    csv_rows = _read_csv_rows(expected_path)
    assert csv_rows[0] == ["agency", "count"], "header row = columns"
    assert csv_rows[1] == ["X", "5"]
    assert csv_rows[2] == ["Y", "3"]
    assert len(csv_rows) == 3, "header + 2 data rows"

    # --- markdown mirror: header, GFM separator, 2 data rows ---
    lines = _md_lines(result["markdown"])
    assert lines[0] == "| agency | count |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| X | 5 |"
    assert lines[3] == "| Y | 3 |"
    assert len(lines) == 4


def test_explicit_columns_order_is_respected(tmp_path):
    """An explicit ``columns`` arg fixes the order even if it reverses key order."""
    rows = [{"agency": "X", "count": 5}]
    result = write_table(rows, tmp_path, "Ordered", columns=["count", "agency"])
    assert result["columns"] == ["count", "agency"]

    csv_rows = _read_csv_rows(Path(result["csv_path"]))
    assert csv_rows[0] == ["count", "agency"]
    assert csv_rows[1] == ["5", "X"]
    assert result["markdown"].splitlines()[0] == "| count | agency |"


def test_explicit_columns_subset_drops_unlisted_keys(tmp_path):
    """Only the listed columns are emitted; extra row keys are ignored."""
    rows = [{"a": 1, "b": 2, "c": 3}]
    result = write_table(rows, tmp_path, "Subset", columns=["a", "c"])
    assert result["columns"] == ["a", "c"]
    csv_rows = _read_csv_rows(Path(result["csv_path"]))
    assert csv_rows[0] == ["a", "c"]
    assert csv_rows[1] == ["1", "3"]


# --- Heterogeneous keys: union in first-appearance order, missing -> empty ----

def test_heterogeneous_keys_union_first_appearance_order(tmp_path):
    rows = [{"a": 1}, {"b": 2}]
    result = write_table(rows, tmp_path, "Hetero")
    # union of keys in first-appearance order
    assert result["columns"] == ["a", "b"]

    csv_rows = _read_csv_rows(Path(result["csv_path"]))
    assert csv_rows[0] == ["a", "b"]
    # first row missing 'b' -> empty cell; second row missing 'a' -> empty cell
    assert csv_rows[1] == ["1", ""]
    assert csv_rows[2] == ["", "2"]

    lines = result["markdown"].splitlines()
    assert lines[0] == "| a | b |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| 1 |  |"   # missing 'b' -> empty cell
    assert lines[3] == "|  | 2 |"   # missing 'a' -> empty cell


def test_first_appearance_order_with_overlap(tmp_path):
    """Keys are added in the order first seen across rows (stable union)."""
    rows = [{"a": 1, "b": 2}, {"b": 3, "c": 4}, {"a": 5, "d": 6}]
    result = write_table(rows, tmp_path, "Overlap")
    assert result["columns"] == ["a", "b", "c", "d"]


# --- Escaping: pipe and newline handling differs between CSV and markdown -----

def test_pipe_escaped_in_markdown_but_literal_in_csv(tmp_path):
    rows = [{"val": "a|b"}]
    result = write_table(rows, tmp_path, "Pipes")

    # CSV round-trips the literal pipe (csv does not treat | specially).
    csv_rows = _read_csv_rows(Path(result["csv_path"]))
    assert csv_rows[1] == ["a|b"]

    # Markdown escapes the pipe so it does not break the table column.
    data_line = result["markdown"].splitlines()[2]
    assert data_line == r"| a\|b |"
    assert "a|b" not in data_line, "raw pipe must be escaped in markdown"


def test_newline_replaced_in_markdown_but_roundtrips_in_csv(tmp_path):
    rows = [{"val": "line1\nline2"}]
    result = write_table(rows, tmp_path, "Newlines")

    # CSV round-trips the embedded newline (quoted field) intact.
    csv_rows = _read_csv_rows(Path(result["csv_path"]))
    assert csv_rows[1] == ["line1\nline2"]

    # Markdown row must contain no raw newline (would break the table); the
    # embedded newline becomes a single space.
    lines = result["markdown"].splitlines()
    # header + separator + exactly ONE data line (no row split by the newline)
    assert len(lines) == 3
    data_line = lines[2]
    assert "\n" not in data_line
    assert data_line == "| line1 line2 |"


def test_carriage_return_replaced_in_markdown(tmp_path):
    """A CR (or CRLF) embedded in a value is also collapsed to a space in markdown."""
    rows = [{"val": "a\r\nb"}]
    result = write_table(rows, tmp_path, "CR")
    lines = result["markdown"].splitlines()
    assert len(lines) == 3, "no row split on CR/CRLF"
    assert "\r" not in lines[2]
    assert lines[2] == "| a b |"


def test_comma_and_quote_quoted_by_csv(tmp_path):
    """csv handles quoting of commas/quotes; the reader round-trips them."""
    rows = [{"val": 'has, comma and "quote"'}]
    result = write_table(rows, tmp_path, "Quoting")
    csv_rows = _read_csv_rows(Path(result["csv_path"]))
    assert csv_rows[1] == ['has, comma and "quote"']


# --- None / missing -> empty cell in both CSV and markdown --------------------

def test_none_value_is_empty_cell(tmp_path):
    rows = [{"a": None, "b": 7}]
    result = write_table(rows, tmp_path, "Nones")

    csv_rows = _read_csv_rows(Path(result["csv_path"]))
    assert csv_rows[0] == ["a", "b"]
    assert csv_rows[1] == ["", "7"], "None -> empty cell in CSV"

    lines = result["markdown"].splitlines()
    assert lines[2] == "|  | 7 |", "None -> empty cell in markdown"


def test_non_string_scalars_are_stringified(tmp_path):
    """Non-string scalars render via str() in both outputs."""
    rows = [{"n": 3.5, "flag": True, "z": 0}]
    result = write_table(rows, tmp_path, "Scalars")
    csv_rows = _read_csv_rows(Path(result["csv_path"]))
    assert csv_rows[1] == ["3.5", "True", "0"]
    assert result["markdown"].splitlines()[2] == "| 3.5 | True | 0 |"


# --- Empty payload variants ---------------------------------------------------

def test_empty_rows_no_columns(tmp_path):
    """rows == [] with no columns -> empty CSV (no header), markdown '', count 0."""
    result = write_table([], tmp_path, "Empty")
    assert result["row_count"] == 0
    assert result["columns"] == []
    assert result["markdown"] == ""

    csv_path = Path(result["csv_path"])
    assert csv_path.exists(), "an empty CSV file is still created"
    # No columns known => no header row; file is effectively empty.
    csv_rows = _read_csv_rows(csv_path)
    assert csv_rows == [], "empty payload with no columns writes no header"


def test_empty_rows_with_explicit_columns_writes_header_only(tmp_path):
    """rows == [] WITH explicit columns -> header-only CSV + header+separator md."""
    result = write_table([], tmp_path, "HeaderOnly", columns=["a", "b"])
    assert result["row_count"] == 0
    assert result["columns"] == ["a", "b"]

    csv_rows = _read_csv_rows(Path(result["csv_path"]))
    assert csv_rows == [["a", "b"]], "header-only CSV when columns are explicit"

    lines = result["markdown"].splitlines()
    assert lines == ["| a | b |", "| --- | --- |"], "header + separator, no data rows"


# --- Overwrite semantics: CSV is regenerable, overwriting is expected ---------

def test_rerun_overwrites_existing_csv(tmp_path):
    """Re-running refreshes the exhibit — no never-clobber guard (unlike write_note)."""
    write_table([{"a": 1}], tmp_path, "Refresh")
    second = write_table([{"a": 2}, {"a": 3}], tmp_path, "Refresh")

    csv_rows = _read_csv_rows(Path(second["csv_path"]))
    assert csv_rows == [["a"], ["2"], ["3"]], "second run overwrote the first"
    assert second["row_count"] == 2


def test_creates_missing_out_dir(tmp_path):
    """out_dir is created if it does not already exist."""
    nested = tmp_path / "exhibits" / "tables"
    assert not nested.exists()
    result = write_table([{"a": 1}], nested, "Nested")
    assert Path(result["csv_path"]).exists()
    assert Path(result["csv_path"]).parent == nested


# --- Stdlib-only contract: importing write_table must NOT pull in PyYAML -------

# Inline program run in a FRESH interpreter: it imports scripts.write_table and
# prints whether "yaml" leaked into sys.modules as a side effect. Run in a child
# process (not a monkeypatch) because once PyYAML is imported anywhere in THIS
# interpreter — every other test parses frontmatter with it — it can never leave
# sys.modules, so the only honest probe is a clean interpreter.
_NO_YAML_SUBPROC = r'''
import json, sys
from pathlib import Path

repo = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
sys.path.insert(0, str(repo))

# yaml must not already be loaded before we import the table writer.
assert "yaml" not in sys.modules, "yaml was imported before write_table"

import scripts.write_table  # the import under test

# Prove the writer is actually usable in this yaml-free interpreter, not just
# importable (calls slug via scripts.textutil for the CSV stem). out_dir is a
# temp dir supplied by the parent, so nothing is written into the repo tree.
result = scripts.write_table.write_table([{"a": 1, "b": 2}], out_dir, "Probe")

print(json.dumps({
    "yaml_in_modules": "yaml" in sys.modules,
    "row_count": result["row_count"],
    "columns": result["columns"],
}))
'''


def test_import_write_table_does_not_import_yaml(tmp_path):
    """Fix 1: a table-only consumer importing scripts.write_table must not load PyYAML.

    Spawns a fresh interpreter (so a yaml already loaded by the rest of THIS suite
    cannot mask the leak), imports scripts.write_table, and asserts "yaml" is absent
    from sys.modules afterward. Pre-fix, write_table imported slug from write_note,
    which imports yaml at module scope — so importing write_table transitively pulled
    in PyYAML, breaking its stdlib-only contract. The slug move to scripts.textutil
    severs that coupling.
    """
    import json
    import subprocess

    repo_root = Path(__file__).resolve().parents[1]
    probe_out = tmp_path / "probe_out"
    proc = subprocess.run(
        [sys.executable, "-c", _NO_YAML_SUBPROC, str(repo_root), str(probe_out)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"subprocess failed (rc={proc.returncode}):\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )

    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["yaml_in_modules"] is False, (
        "importing scripts.write_table must NOT import PyYAML (stdlib-only contract)"
    )
    # And the writer still works in the yaml-free interpreter.
    assert payload["row_count"] == 1
    assert payload["columns"] == ["a", "b"]
