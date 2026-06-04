# Librarian — Structural Map

Fieldwork suite **Librarian** plugin: the shared, portable-first findings-notes
output layer, extracted (decoupled) from research-workflow's classify → write →
wikilink stages. Authors *internal* notes only (never outward-facing prose).

## Stack

- **Language:** Python 3.12 (pinned 3.12.10). Plugin distributed as a Claude Code plugin (`.claude-plugin/`).
- **Runtime deps:** PyYAML 6.0.2 (frontmatter emission in `write_note.py`); stdlib `sqlite3` (vault mode only). Dev: pytest 9.0.3.
- **Shape:** `scripts/` are invoked directly by the skill/agents; `pyproject.toml` configures pytest only (not a pip package).

## Structure

```
.claude-plugin/plugin.json    Plugin manifest (name "librarian", v0.1.0, MIT; describes the portable-first notes layer).
config/
  taxonomy.example.json       Neutral default taxonomy (content_types, tag_order/limit, default_folder, folder_conventions, frontmatter_fields, moc_pattern). Copy to taxonomy.json to override; neutrality enforced by a test.
scripts/
  __init__.py                 Marks scripts/ a package (imports use `from scripts.x import ...`).
  textutil.py                 Stdlib-only `slug()` — the single slug impl shared by both writers so they cannot drift. No YAML/clock/network.
  write_note.py               Portable Markdown note writer: builds YAML frontmatter (spec title authoritative) + body + `## Sources` from citations; never-clobber guard (identical vs collision). Imports PyYAML. `action: update` is out of scope.
  write_table.py              Tabular exhibit writer: emits a CSV file + returns a GFM Markdown-table mirror string. Stdlib only; CSV overwrite is expected (regenerable). Shares textutil.slug.
  taxonomy.py                 Config load (`load_taxonomy`, backfills missing keys from DEFAULT_TAXONOMY) + spec validation (`validate_note_specs`). Pure, stdlib only. Flags-as-leads: warns, never drops a spec.
  vault_index.py              OPTIONAL SQLite FTS5 adapter (the ONLY sqlite importer). `update_index`/`search`/`note_exists`/`list_notes`/`build_index`; transparent LIKE-scan fallback when FTS5 absent. Index db under <vault>/.librarian/.
  vault_mode.py               Portable-vs-vault routing seam (`resolve_notes`) [Coupling 1]; folder sanitization (`_safe_relative_folder`) neuters untrusted/traversal folders. The sqlite import lives INSIDE the vault branch only.
agents/
  classify-agent.md          Haiku agent: structures findings → `notes_to_create[]` in the neutral contract; queries the index only in vault mode. Reads taxonomy vocab, not a hardcoded enum.
  wikilink-scanner.md        Haiku agent: plans wikilink edits (edits[] JSON) after notes are written; index query is vault-mode only; portable links among the batch + link_hints.
skills/librarian/SKILL.md    The classify/structuring skill: neutral contract, structuring rules, portable vs vault flow, writer hand-off.
config/, references/, tests/  (see below)
references/
  prior-art.md               Extraction map: research-workflow source→home table, the 3 couplings to sever, the neutral input-contract field reference (§3).
  acceptance-test.md         Auto-pull acceptance test (prepared; needs a clean-profile run) for the librarian dependency.
tests/
  test_write_portable.py     write_note: on-disk frontmatter/sources/never-clobber.
  test_write_table.py        write_table: CSV + Markdown mirror, overwrite behavior.
  test_taxonomy.py           load_taxonomy merge + validate_note_specs warnings.
  test_vault_mode.py         resolve_notes routing + the portable-path-is-sqlite-import-clean guard (Coupling 1).
  test_frontmatter.py        Every shipped skill/agent has yaml.safe_load-parseable frontmatter.
  test_plugin_manifest.py    plugin.json is well-formed.
pyproject.toml               pytest config only (pythonpath ["."], testpaths ["tests"]).
requirements.txt             Runtime: PyYAML==6.0.2.
requirements-dev.txt         -r requirements.txt + pytest==9.0.3.
README.md / LICENSE          Overview + MIT license.
```

## Key Relationships

- **Coupling 1 (portable never imports sqlite).** The portable path is a strict subset that never touches `vault_index`. `import vault_index` is local to `vault_mode._resolve_vault` (the vault branch), and `test_vault_mode.py::test_portable_path_is_sqlite_import_clean` enforces it. `vault_index.py` is the sole sqlite importer.
- **Shared slug seam.** `write_note` and `write_table` both import `slug` from the stdlib-only `textutil` (NOT from each other) so the two writers cannot drift, and `write_table` stays PyYAML-free.
- **Neutral input-contract pipeline.** `{title, content, frontmatter_meta, citations, link_hints, priority, action}` flows: `classify-agent` emits it → `taxonomy.validate_note_specs` normalizes/warns → `vault_mode.resolve_notes` places it (portable folder/slug, or vault index-resolved) → `write_note`/`write_table` render it.
- **Taxonomy is config, not code (Coupling 3).** `DEFAULT_TAXONOMY` in `taxonomy.py` mirrors `config/taxonomy.example.json`; the skill and classify-agent read these values instead of a hardcoded enum. Couplings 1–3 are defined in `references/prior-art.md` §2.
- **Determinism.** Writers and taxonomy take no clock/network/randomness; any `created` timestamp is caller-supplied via `frontmatter_meta`. The vault adapter does sqlite I/O but owns its own index freshness (update before search).
