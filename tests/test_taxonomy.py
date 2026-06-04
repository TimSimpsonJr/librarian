"""Tests for the deterministic taxonomy layer (Task 1.3, scripts/taxonomy.py).

The classify AGENT's live LLM behavior (agents/classify-agent.md) is validated by
integration use, not unit tests. The unit-tested contract here is taxonomy.py:
``load_taxonomy`` (load + merge neutral defaults) and ``validate_note_specs``
(normalize neutral note specs + emit non-fatal warnings). Both are PURE/deterministic
— stdlib only, no clock/random/network/vault/yaml (references/prior-art.md §2
Coupling 3, §3 neutral contract).
"""

import json
from pathlib import Path

import pytest

from scripts.taxonomy import load_taxonomy, validate_note_specs

# Top-level keys every loaded taxonomy must expose, even from a partial override.
_REQUIRED_KEYS = {
    "content_types",
    "tag_order",
    "tag_limit",
    "default_folder",
    "folder_conventions",
    "frontmatter_fields",
    "moc_pattern",
}

# Coupling 3 neutrality guard: NONE of these may appear (case-insensitively) in the
# shipped example config. They are user-supplied overrides, never shipped values.
_FORBIDDEN_SUBSTRINGS = [
    "surveillance",
    "greenville",
    "south carolina",
    "flock",
    "alpr",
]


# --------------------------------------------------------------------------- #
# load_taxonomy
# --------------------------------------------------------------------------- #


def test_load_default_has_all_required_keys():
    """load_taxonomy() with no arg loads the bundled example with every key."""
    tax = load_taxonomy()
    assert _REQUIRED_KEYS <= set(tax), _REQUIRED_KEYS - set(tax)
    # Spot-check the neutral defaults the rest of the suite relies on.
    assert tax["default_folder"] == "Inbox"
    assert tax["tag_order"] == ["content-type", "location", "domain"]
    assert tax["tag_limit"] == {"min": 2, "max": 5}
    assert isinstance(tax["content_types"], list) and tax["content_types"]


def test_partial_config_is_filled_from_defaults(tmp_path):
    """A partial override supplying only content_types gets every other key from defaults."""
    partial = tmp_path / "taxonomy.json"
    partial.write_text(
        json.dumps({"content_types": ["custom_type_a", "custom_type_b"]}),
        encoding="utf-8",
    )

    tax = load_taxonomy(partial)

    # Caller's value wins where supplied...
    assert tax["content_types"] == ["custom_type_a", "custom_type_b"]
    # ...and every missing key is backfilled from the neutral defaults.
    assert _REQUIRED_KEYS <= set(tax)
    assert tax["default_folder"] == "Inbox"
    assert tax["moc_pattern"] == "^_|MOC|Index|Hub"


def test_shipped_example_is_neutral():
    """Coupling 3: the shipped example config carries NO domain-specific strings.

    Scans the raw JSON text of config/taxonomy.example.json case-insensitively so a
    surveillance/SC/Greenville string cannot regress into the shipped default.
    """
    example_path = (
        Path(__file__).resolve().parents[1] / "config" / "taxonomy.example.json"
    )
    raw = example_path.read_text(encoding="utf-8").lower()
    for needle in _FORBIDDEN_SUBSTRINGS:
        assert needle not in raw, f"forbidden domain string in shipped config: {needle!r}"


# --------------------------------------------------------------------------- #
# validate_note_specs
# --------------------------------------------------------------------------- #


def _clean_specs():
    """A notes_to_create[] batch in the neutral contract that should normalize cleanly."""
    return [
        {
            "title": "County Camera Deployment Report",
            "content": "Body text.",
            "frontmatter_meta": {
                "folder": "Reports",
                "tags": ["report", "north-county", "transit"],
            },
            "citations": ["https://example.org/a"],
            "link_hints": ["County Transit Authority"],
            "priority": "primary",
            "action": "create",
        }
    ]


def test_clean_specs_normalize_without_errors():
    tax = load_taxonomy()
    result = validate_note_specs(_clean_specs(), tax)

    assert result["warnings"] == []
    [norm] = result["normalized"]
    assert norm["title"] == "County Camera Deployment Report"
    assert norm["priority"] == "primary"
    assert norm["action"] == "create"
    # folder resolves from frontmatter_meta.folder when present.
    assert norm["folder"] == "Reports"


def test_unknown_content_type_warns_but_does_not_reject():
    """A content-type tag absent from the SUPPLIED taxonomy is a LEAD, not a verdict."""
    tax = {
        "content_types": ["report", "reference"],
        "tag_order": ["content-type", "location", "domain"],
        "tag_limit": {"min": 1, "max": 5},
        "default_folder": "Inbox",
        "folder_conventions": {"pattern": "{folder}/{slug}.md"},
        "frontmatter_fields": ["title", "tags", "source", "created"],
        "moc_pattern": "^_|MOC|Index|Hub",
    }
    specs = [
        {
            "title": "An Odd One",
            "frontmatter_meta": {"tags": ["mystery-type", "somewhere"]},
            "priority": "secondary",
            "action": "create",
        }
    ]

    result = validate_note_specs(specs, tax)

    # NOT rejected: the spec still normalizes through.
    assert len(result["normalized"]) == 1
    # ...but a warning flags the unknown content type.
    assert any("mystery-type" in w for w in result["warnings"])


def test_missing_title_is_flagged():
    tax = load_taxonomy()
    specs = [{"frontmatter_meta": {"tags": ["report", "x"]}, "priority": "primary"}]

    result = validate_note_specs(specs, tax)

    assert any("title" in w.lower() for w in result["warnings"])


def test_folder_defaults_to_taxonomy_default_when_absent():
    tax = load_taxonomy()  # default_folder == "Inbox"
    specs = [
        {
            "title": "No Folder Note",
            "frontmatter_meta": {"tags": ["report", "x"]},
            "priority": "primary",
            "action": "create",
        }
    ]

    [norm] = validate_note_specs(specs, tax)["normalized"]

    assert norm["folder"] == "Inbox"


def test_invalid_priority_is_defaulted_and_warned():
    tax = load_taxonomy()
    specs = [
        {
            "title": "Bad Priority",
            "frontmatter_meta": {"tags": ["report", "x"]},
            "priority": "URGENT",  # not in {primary, secondary, scan}
            "action": "create",
        }
    ]

    result = validate_note_specs(specs, tax)

    [norm] = result["normalized"]
    assert norm["priority"] == "secondary"  # defaulted
    assert any("priority" in w.lower() for w in result["warnings"])


def test_tag_count_outside_limit_warns():
    """Tag count below min or above max is a non-fatal warning."""
    tax = load_taxonomy()  # tag_limit {min: 2, max: 5}
    specs = [
        {
            "title": "Too Few Tags",
            "frontmatter_meta": {"tags": ["report"]},  # 1 < min(2)
            "priority": "primary",
            "action": "create",
        }
    ]

    result = validate_note_specs(specs, tax)

    assert len(result["normalized"]) == 1  # not rejected
    assert any("tag" in w.lower() for w in result["warnings"])
