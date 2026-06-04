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


@pytest.mark.parametrize(
    "bad_folder",
    [
        "../outside",
        "../../etc/passwd",
        "/etc",
        r"C:\Windows\system32",
        "a/../../b",
        "Cases/../../../x",
    ],
)
def test_absolute_or_traversal_folder_warns_but_does_not_drop(bad_folder):
    """Codex re-review fix: an absolute / '..' folder is flagged (lead), not rejected.

    The hard guarantee lives in scripts.vault_mode (placements can't escape the base);
    here the validator must SURFACE that the placement will be sanitized — emit a
    warning, still normalize the spec, and keep the raw folder on the normalized record
    (vault_mode does the neutering downstream).
    """
    tax = load_taxonomy()
    specs = [
        {
            "title": "Adversarial Placement",
            "frontmatter_meta": {"folder": bad_folder, "tags": ["report", "x"]},
            "priority": "primary",
            "action": "create",
        }
    ]

    result = validate_note_specs(specs, tax)

    # Not dropped: exactly one normalized record comes through.
    assert len(result["normalized"]) == 1
    # ...and a warning flags the unsafe folder for the caller.
    assert any(
        "folder" in w and ("absolute" in w or ".." in w) for w in result["warnings"]
    ), result["warnings"]


def test_benign_folder_emits_no_traversal_warning():
    """A benign 'Cases/2024' folder must NOT trip the absolute/'..' warning."""
    tax = load_taxonomy()
    specs = [
        {
            "title": "Benign Placement",
            "frontmatter_meta": {"folder": "Cases/2024", "tags": ["report", "x"]},
            "priority": "primary",
            "action": "create",
        }
    ]

    result = validate_note_specs(specs, tax)

    assert result["warnings"] == [], result["warnings"]
    [norm] = result["normalized"]
    assert norm["folder"] == "Cases/2024"


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


@pytest.mark.parametrize("bad_meta", ["oops", ["bad"], 42, ("x",)])
def test_non_dict_frontmatter_meta_warns_but_does_not_crash(bad_meta):
    """A truthy NON-dict frontmatter_meta is a LEAD, not an AttributeError.

    Pre-fix, ``spec.get("frontmatter_meta") or {}`` left a truthy non-dict value
    (e.g. ``"oops"`` / ``["bad"]``) in place, and the subsequent ``.get(...)`` raised
    AttributeError — violating the module's "flags-as-leads, nothing dropped" contract.
    The value must instead be coerced to ``{}`` with a warning, and the spec must still
    normalize to exactly one record.
    """
    tax = load_taxonomy()
    specs = [{"title": "X", "frontmatter_meta": bad_meta}]

    result = validate_note_specs(specs, tax)  # must NOT raise

    # Exactly one normalized record (nothing dropped).
    assert len(result["normalized"]) == 1
    [norm] = result["normalized"]
    assert norm["title"] == "X"
    # The bad meta was coerced to an empty dict on the normalized record.
    assert norm["frontmatter_meta"] == {}
    # Folder falls back to the taxonomy default (no usable meta.folder).
    assert norm["folder"] == "Inbox"
    # A warning flags the non-dict frontmatter_meta.
    assert any(
        "frontmatter_meta" in w and "not a dict" in w for w in result["warnings"]
    ), result["warnings"]


def test_missing_or_none_frontmatter_meta_is_not_warned():
    """An ABSENT / None frontmatter_meta is the well-formed no-metadata case (no warning).

    Only a truthy non-dict value is a lead; a missing key must stay silent so the common
    case does not spam warnings (regression guard for the coercion's None branch).
    """
    tax = load_taxonomy()
    result_absent = validate_note_specs([{"title": "No Meta"}], tax)
    result_none = validate_note_specs([{"title": "Null Meta", "frontmatter_meta": None}], tax)

    for result in (result_absent, result_none):
        assert len(result["normalized"]) == 1
        assert not any("frontmatter_meta" in w for w in result["warnings"]), result["warnings"]


def test_normalized_frontmatter_meta_does_not_alias_input():
    """The normalized record's frontmatter_meta must be a COPY, not the input object.

    The docstring promises new dicts that mutate neither argument. The fix is a shallow
    ``dict(meta)`` copy, so this guards the contract that copy promises: the normalized
    record's frontmatter_meta is a DISTINCT dict, and rebinding/adding/removing its
    top-level keys does not reach back into the caller's input spec (regression: the two
    used to be the same object, so every such edit bled through).
    """
    tax = load_taxonomy()
    spec = {
        "title": "Aliasing Guard",
        "frontmatter_meta": {"tags": ["report", "x"], "folder": "Reports"},
        "priority": "primary",
        "action": "create",
    }

    [norm] = validate_note_specs([spec], tax)["normalized"]

    # Distinct objects, not an alias.
    assert norm["frontmatter_meta"] is not spec["frontmatter_meta"]
    # Equal in value at the point of normalization.
    assert norm["frontmatter_meta"] == spec["frontmatter_meta"]

    # Top-level edits on the normalized copy must NOT bleed into the input spec:
    # add a new key, rebind an existing key, and drop a key.
    norm["frontmatter_meta"]["injected"] = True
    norm["frontmatter_meta"]["tags"] = ["replaced"]
    del norm["frontmatter_meta"]["folder"]

    assert "injected" not in spec["frontmatter_meta"]
    assert spec["frontmatter_meta"]["tags"] == ["report", "x"]
    assert spec["frontmatter_meta"]["folder"] == "Reports"
