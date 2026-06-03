"""Tests for the portable Markdown writer (Task 1.1, scripts/write_note.py).

Portable-first contract (references/prior-art.md §3, §5): write_note is a PURE
function — deterministic given (spec, out_dir), no vault, no index, no clock, no
randomness. These tests assert real on-disk structure (parse the YAML frontmatter,
inspect the rendered ## Sources bullets, confirm the never-clobber guard) rather
than mocking the writer's internals.
"""

import re
from pathlib import Path

import pytest
import yaml

from scripts.write_note import slug, write_note


def _parse_frontmatter(text: str) -> dict:
    """Parse the leading YAML frontmatter block robustly.

    Matches the opening ``---`` fence anchored at start-of-file and the closing
    fence non-greedily, so a ``---`` line *inside* a frontmatter value cannot
    mis-split the block (a naive ``text.split("---\\n")`` would). Returns the
    ``yaml.safe_load`` of the captured block.
    """
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, "file must open with a YAML frontmatter fence"
    return yaml.safe_load(m.group(1))


# A representative note spec exercising frontmatter_meta (tags list + content-type)
# and a citations list mixing a bare URL string with a structured {doc_id, page} ref.
def _sample_spec():
    return {
        "title": "Greenville Surveillance FOIA Findings",
        "content": (
            "The county deployed automated license plate readers in 2023.\n\n"
            "An inline embed rides through verbatim: ![[evidence/alpr-map.png]]"
        ),
        "frontmatter_meta": {
            "tags": ["research", "surveillance", "greenville-sc"],
            "content-type": "research",
            "created": "2026-06-03",
        },
        "citations": [
            "https://example.gov/foia/response-2023.html",
            {"doc_id": "FOIA-2023-0142", "page": 7},
        ],
        "link_hints": ["Greenville County", "ALPR"],  # IGNORED in this task (1.4)
        "priority": "primary",                          # IGNORED here
        "action": "create",
    }


def test_writes_note_with_frontmatter_and_sources(tmp_path):
    spec = _sample_spec()
    result = write_note(spec, tmp_path)

    # --- return contract ---
    assert result["skipped"] is False
    assert result["action"] == "create"
    written = tmp_path / "greenville-surveillance-foia-findings.md"
    assert result["path"] == str(written)
    assert written.exists(), "note file should be written at out_dir/<slug>.md"

    text = written.read_text(encoding="utf-8")

    # --- frontmatter is a real, parseable YAML block delimited by --- ---
    # Parse via an anchored fence regex (Fix 10): robust to a `---` line that
    # might appear inside a frontmatter value, unlike a naive split("---\n").
    assert text.startswith("---\n"), "file must open with a YAML frontmatter fence"
    fm = _parse_frontmatter(text)
    body = text[text.index("\n---\n") + len("\n---\n"):]
    assert fm["title"] == spec["title"], "title leads the frontmatter"
    assert fm["tags"] == ["research", "surveillance", "greenville-sc"]
    assert fm["content-type"] == "research"
    # title must be the FIRST key (ordering preserved, not sorted)
    assert list(fm.keys())[0] == "title"

    # --- body text appears after the frontmatter, verbatim (embed preserved) ---
    assert "automated license plate readers in 2023" in body
    assert "![[evidence/alpr-map.png]]" in body

    # --- blank line separates the frontmatter fence from the body (spec) ---
    assert "---\n\nThe county deployed" in text

    # --- ## Sources section renders both citation shapes ---
    assert "## Sources" in text
    # a blank line precedes the Sources heading (not glued to the body)
    assert "\n\n## Sources\n" in text
    sources = text.split("## Sources", 1)[1]
    # bare URL → angle-bracketed auto-link bullet
    assert "- <https://example.gov/foia/response-2023.html>" in sources
    # structured {doc_id, page} → doc_id plus page rendering
    assert "FOIA-2023-0142" in sources
    assert "p. 7" in sources


def test_em_dash_and_unicode_survive_frontmatter(tmp_path):
    """allow_unicode=True keeps em-dashes/accented names intact, not \\uXXXX escaped."""
    spec = {
        "title": "Café Naïveté — Notes",
        "content": "Body.",
        "frontmatter_meta": {"author": "José"},
        "citations": [],
    }
    result = write_note(spec, tmp_path)
    # result["path"] is an absolute path string; read it directly.
    text = Path(result["path"]).read_text(encoding="utf-8")
    assert "José" in text
    assert "Café Naïveté — Notes" in text


def test_slug_preserves_non_ascii_punctuation_per_spec(tmp_path):
    """The spec strips only Windows-unsafe chars; an em-dash is valid and survives.

    Documented as explicit behavior (not incidental): a raw em-dash in a title
    lands as a literal em-dash in the filename — it is not folded to a hyphen.
    """
    assert slug("A — B") == "a-—-b"
    spec = {"title": "Report — Final", "content": "Body.", "citations": []}
    result = write_note(spec, tmp_path)
    assert result["path"].endswith("report-—-final.md"), result["path"]
    assert Path(result["path"]).exists()


def test_empty_citations_omits_sources_section(tmp_path):
    spec = {
        "title": "No Sources Note",
        "content": "A body with no backing citations.",
        "frontmatter_meta": {"tags": ["reference"]},
        "citations": [],
    }
    result = write_note(spec, tmp_path)
    text = (tmp_path / "no-sources-note.md").read_text(encoding="utf-8")
    assert result["skipped"] is False
    assert "## Sources" not in text, "empty citations must omit the Sources section"


def test_absent_citations_key_omits_sources_section(tmp_path):
    """citations entirely absent behaves like empty (no Sources section)."""
    spec = {"title": "Bare Note", "content": "Body."}
    write_note(spec, tmp_path)
    text = (tmp_path / "bare-note.md").read_text(encoding="utf-8")
    assert "## Sources" not in text


def test_never_clobbers_existing_file(tmp_path):
    """A second write of the SAME slug with DIFFERENT content is a collision (Fix 1).

    The would-be content differs from what is on disk, so it is reported as a
    distinct-note slug collision (not a benign identical re-run) and the file is
    never overwritten.
    """
    spec = _sample_spec()
    first = write_note(spec, tmp_path)
    assert first["skipped"] is False
    written = tmp_path / "greenville-surveillance-foia-findings.md"
    original = written.read_text(encoding="utf-8")

    # Second call for the same title in the same out_dir must NOT overwrite.
    changed = dict(spec, content="COMPLETELY DIFFERENT BODY that must not land")
    second = write_note(changed, tmp_path)
    assert second["skipped"] is True
    assert second["reason"] == "collision"
    # file on disk is byte-for-byte unchanged
    assert written.read_text(encoding="utf-8") == original
    assert "COMPLETELY DIFFERENT BODY" not in written.read_text(encoding="utf-8")


def test_identical_rewrite_reports_identical(tmp_path):
    """Writing the exact same spec twice is an idempotent re-run (Fix 1).

    The second write finds on-disk content identical to what it would write, so
    it returns reason=='identical' and leaves the file untouched.
    """
    spec = _sample_spec()
    first = write_note(spec, tmp_path)
    assert first["skipped"] is False
    written = Path(first["path"])
    original = written.read_text(encoding="utf-8")

    second = write_note(spec, tmp_path)
    assert second["skipped"] is True
    assert second["reason"] == "identical"
    assert second["path"] == first["path"]
    assert written.read_text(encoding="utf-8") == original


def test_distinct_notes_same_slug_collide(tmp_path):
    """Two different titles that slug to the SAME stem collide, not silently drop (Fix 1).

    'Q3 Plan' and 'Q3  Plan' (double space) both slug to 'q3-plan'. The second is
    a genuinely different note (different title in its frontmatter) and must be
    reported reason=='collision' with the on-disk file byte-for-byte unchanged.
    """
    first = write_note({"title": "Q3 Plan", "content": "First note."}, tmp_path)
    assert first["skipped"] is False
    written = Path(first["path"])
    assert written.name == "q3-plan.md"
    original = written.read_bytes()

    # Same slug, DIFFERENT content (the title line in frontmatter differs).
    second = write_note({"title": "Q3  Plan", "content": "Second note."}, tmp_path)
    assert second["path"] == first["path"]
    assert second["skipped"] is True
    assert second["reason"] == "collision"
    # byte-for-byte unchanged: the first note's bytes are still on disk
    assert written.read_bytes() == original


def test_citation_renderers(tmp_path):
    """Each citation shape from the spec renders to its own bullet form."""
    spec = {
        "title": "Citation Render Matrix",
        "content": "Body.",
        "citations": [
            "https://a.example/page",                       # http url string
            "Smith 2021, internal memo",                     # plain string
            {"url": "https://b.example/x", "title": "Doc B"},  # dict url+title
            {"url": "https://c.example/y"},                  # dict url only
            {"doc_id": "EX-9", "page": 3},                   # doc_id + page
            {"doc_id": "EX-10"},                             # doc_id, no page
            {"exhibit": "B", "court": "DSC"},                # arbitrary dict
        ],
    }
    write_note(spec, tmp_path)
    sources = (tmp_path / "citation-render-matrix.md") \
        .read_text(encoding="utf-8").split("## Sources", 1)[1]
    assert "- <https://a.example/page>" in sources
    assert "- Smith 2021, internal memo" in sources
    assert "- [Doc B](https://b.example/x)" in sources
    assert "- <https://c.example/y>" in sources
    assert "- EX-9, p. 3" in sources
    assert "- EX-10" in sources
    # arbitrary dict → deterministic compact sorted key: value rendering
    assert "court: DSC" in sources and "exhibit: B" in sources


def test_slug_strips_windows_unsafe_chars(tmp_path):
    spec = {
        "title": 'Re: Q3 <Draft> "Plan"/Notes? *v2*',
        "content": "Body.",
        "citations": [],
    }
    result = write_note(spec, tmp_path)
    written = tmp_path / "re-q3-draft-plannotes-v2.md"
    assert written.exists(), result["path"]
    # no Windows-illegal characters survived in the filename
    name = written.name
    for bad in '<>:"/\\|?*':
        assert bad not in name


# --- Fix 2: non-string content ------------------------------------------------

def test_none_content_writes_empty_body(tmp_path):
    """content=None is treated as an empty body — no crash, valid note (Fix 2)."""
    spec = {"title": "None Content", "content": None, "citations": []}
    result = write_note(spec, tmp_path)
    assert result["skipped"] is False
    text = Path(result["path"]).read_text(encoding="utf-8")
    fm = _parse_frontmatter(text)
    assert fm["title"] == "None Content"
    # body after the closing fence is empty (only the trailing newline remains)
    body = text[text.index("\n---\n") + len("\n---\n"):]
    assert body.strip() == ""


def test_non_string_content_raises_typeerror(tmp_path):
    """content of a non-str/non-None type raises TypeError naming 'content' (Fix 2)."""
    spec = {"title": "Bad Content", "content": 123}
    with pytest.raises(TypeError) as exc:
        write_note(spec, tmp_path)
    assert "content" in str(exc.value)


# --- Fix 3: degenerate citation dicts ----------------------------------------

def test_degenerate_citation_dicts_render_honestly(tmp_path):
    """Empty/None url & doc_id fall through to generic rendering, not junk (Fix 3)."""
    spec = {
        "title": "Degenerate Citations",
        "content": "Body.",
        "citations": [
            {"url": None},                 # must NOT render <None>
            {"url": ""},                   # must NOT render <>
            {"doc_id": None, "page": 5},   # must NOT render "None, p. 5"
            {"doc_id": "X", "page": 0},    # page 0 is valid -> "X, p. 0"
        ],
    }
    write_note(spec, tmp_path)
    sources = (tmp_path / "degenerate-citations.md") \
        .read_text(encoding="utf-8").split("## Sources", 1)[1]
    assert "<None>" not in sources
    assert "<>" not in sources
    assert "None, p. 5" not in sources
    # well-formed doc_id with page 0 still renders (page gated on `is not None`)
    assert "- X, p. 0" in sources


# --- Fix 4 / Fix 5: empty slug + title validation -----------------------------

def test_punctuation_only_title_falls_back_to_untitled(tmp_path):
    """A title that slugs to empty ('???') yields 'untitled.md', not '.md' (Fix 4)."""
    spec = {"title": "???", "content": "Body."}
    result = write_note(spec, tmp_path)
    assert Path(result["path"]).name == "untitled.md"
    assert Path(result["path"]).exists()


def test_missing_title_raises_clear_error(tmp_path):
    """A spec without 'title' raises a clear error naming 'title' (Fix 5)."""
    with pytest.raises((ValueError, TypeError)) as exc:
        write_note({"content": "Body."}, tmp_path)
    assert "title" in str(exc.value)


def test_blank_title_raises_clear_error(tmp_path):
    """A whitespace-only title is rejected with a 'title' error (Fix 5)."""
    with pytest.raises((ValueError, TypeError)) as exc:
        write_note({"title": "   ", "content": "Body."}, tmp_path)
    assert "title" in str(exc.value)


def test_non_string_title_raises_clear_error(tmp_path):
    """A non-str title is rejected with a 'title' error (Fix 5)."""
    with pytest.raises((ValueError, TypeError)) as exc:
        write_note({"title": 42, "content": "Body."}, tmp_path)
    assert "title" in str(exc.value)


# --- Fix 6: no YAML line-wrap on long scalars ---------------------------------

def test_long_frontmatter_value_not_wrapped(tmp_path):
    """A long frontmatter scalar stays on one line and round-trips (Fix 6)."""
    long_value = "x" * 200
    spec = {
        "title": "Long Summary",
        "content": "Body.",
        "frontmatter_meta": {"summary": long_value},
    }
    result = write_note(spec, tmp_path)
    text = Path(result["path"]).read_text(encoding="utf-8")
    # The 200-char value appears on a single physical line (no wrapped continuation).
    summary_line = next(
        line for line in text.splitlines() if line.startswith("summary:")
    )
    assert long_value in summary_line
    # And it still parses back to the original string.
    fm = _parse_frontmatter(text)
    assert fm["summary"] == long_value


# --- Fix 7: no YAML anchors/aliases -------------------------------------------

def test_shared_object_emits_no_yaml_aliases(tmp_path):
    """The same list under two keys emits no &/* anchors and round-trips (Fix 7)."""
    shared = ["alpha", "beta"]
    spec = {
        "title": "Aliased Meta",
        "content": "Body.",
        "frontmatter_meta": {"tags": shared, "topics": shared},  # same object twice
    }
    result = write_note(spec, tmp_path)
    text = Path(result["path"]).read_text(encoding="utf-8")
    # Isolate the frontmatter block so we don't false-positive on body content.
    fm_block = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL).group(1)
    assert "&" not in fm_block, "no YAML anchor should be emitted"
    assert "*" not in fm_block, "no YAML alias should be emitted"
    fm = _parse_frontmatter(text)
    assert fm["tags"] == ["alpha", "beta"]
    assert fm["topics"] == ["alpha", "beta"]
