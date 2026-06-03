"""Smoke test: the librarian plugin manifest is well-formed (Task 0.4)."""

import json
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / ".claude-plugin" / "plugin.json"


def test_manifest_parses_and_has_required_keys():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for key in ("name", "description", "version"):
        assert key in data, f"plugin.json missing required key: {key}"
    assert data["name"] == "librarian"


def test_manifest_version_is_semver():
    """Magpie and Research depend on librarian, so it needs a real semver."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    parts = data["version"].split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts), data["version"]
