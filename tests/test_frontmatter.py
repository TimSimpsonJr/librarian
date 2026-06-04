"""Frontmatter-validity guard for every shipped skill and agent.

Task 1.3 review gap: ``agents/classify-agent.md`` shipped with YAML frontmatter that
``yaml.safe_load`` could not parse (an unquoted ``description`` scalar with an internal
``: `` mapping indicator). Nothing tested the frontmatter, so it slipped through.

This module discovers EVERY ``skills/*/SKILL.md`` and ``agents/*.md`` in the repo with
``pathlib.glob`` and asserts each one:

* begins with a ``---``-fenced YAML frontmatter block;
* whose block ``yaml.safe_load``s into a ``dict``;
* that carries non-empty ``name`` and ``description`` keys.

It guards all CURRENT and FUTURE skills/agents. The discovery list is asserted
non-empty so an empty glob (wrong path, moved files) can never make the suite pass
vacuously, and the two known files are asserted present by name.

PyYAML is a TEST-only dependency (see requirements-dev.txt); the deterministic core
under ``scripts/`` stays stdlib-only.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# Repo root is the parent of this tests/ directory.
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _split_frontmatter(text: str) -> str:
    """Return the YAML block between the first two ``---`` fences.

    Requires the file to OPEN with a ``---`` fence (line 1) and to contain a closing
    ``---`` fence on its own line. Raises AssertionError otherwise so a malformed or
    missing block fails loudly rather than parsing as ``None``.
    """
    lines = text.splitlines()
    assert lines and lines[0].strip() == "---", "file must start with a '---' frontmatter fence"
    closing = next(
        (i for i in range(1, len(lines)) if lines[i].strip() == "---"),
        None,
    )
    assert closing is not None, "frontmatter block is not closed by a second '---' fence"
    return "\n".join(lines[1:closing])


def _discover_frontmatter_files() -> list[Path]:
    """Discover every shipped skill/agent Markdown file via glob."""
    found = sorted(_REPO_ROOT.glob("skills/*/SKILL.md")) + sorted(
        _REPO_ROOT.glob("agents/*.md")
    )
    return found


# Discover once at import time so the IDs show the relative paths.
_FRONTMATTER_FILES = _discover_frontmatter_files()
_FRONTMATTER_IDS = [str(p.relative_to(_REPO_ROOT)).replace("\\", "/") for p in _FRONTMATTER_FILES]


def test_discovery_is_non_empty_and_includes_known_files():
    """Guard against a vacuous pass: the glob MUST find the known skill and agent.

    If discovery returns nothing (wrong path, moved files), the parametrized test would
    pass vacuously — so assert the list is non-empty AND contains the two files the
    reviewer cares about by name.
    """
    assert _FRONTMATTER_FILES, "no SKILL.md / agent .md files discovered — check glob paths"

    rels = set(_FRONTMATTER_IDS)
    assert "agents/classify-agent.md" in rels, rels
    assert "skills/librarian/SKILL.md" in rels, rels


@pytest.mark.parametrize("md_path", _FRONTMATTER_FILES, ids=_FRONTMATTER_IDS)
def test_frontmatter_is_valid_yaml_with_name_and_description(md_path: Path):
    """Every skill/agent has a ---fenced YAML dict with non-empty name + description."""
    text = md_path.read_text(encoding="utf-8")
    block = _split_frontmatter(text)

    data = yaml.safe_load(block)
    assert isinstance(data, dict), f"{md_path}: frontmatter did not parse to a dict (got {type(data).__name__})"

    name = data.get("name")
    assert isinstance(name, str) and name.strip(), f"{md_path}: 'name' missing or empty"

    description = data.get("description")
    assert isinstance(description, str) and description.strip(), f"{md_path}: 'description' missing or empty"
