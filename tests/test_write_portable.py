"""Tests for the portable Markdown writer (Task 1.1, scripts/write_note.py).

Portable-first contract (references/prior-art.md §3, §5): write_note is a PURE
function — deterministic given (spec, out_dir), no vault, no index, no clock, no
randomness. These tests assert real on-disk structure (parse the YAML frontmatter,
inspect the rendered ## Sources bullets, confirm the never-clobber guard) rather
than mocking the writer's internals.
"""

from pathlib import Path

import yaml

from scripts.write_note import slug, write_note


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
    assert text.startswith("---\n"), "file must open with a YAML frontmatter fence"
    _, fm_block, body = text.split("---\n", 2)
    fm = yaml.safe_load(fm_block)
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
    spec = _sample_spec()
    first = write_note(spec, tmp_path)
    assert first["skipped"] is False
    written = tmp_path / "greenville-surveillance-foia-findings.md"
    original = written.read_text(encoding="utf-8")

    # Second call for the same title in the same out_dir must NOT overwrite.
    changed = dict(spec, content="COMPLETELY DIFFERENT BODY that must not land")
    second = write_note(changed, tmp_path)
    assert second["skipped"] is True
    assert second["reason"] == "exists"
    # file on disk is unchanged
    assert written.read_text(encoding="utf-8") == original
    assert "COMPLETELY DIFFERENT BODY" not in written.read_text(encoding="utf-8")


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
