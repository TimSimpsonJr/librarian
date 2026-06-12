---
name: Librarian
description: This skill should be used when findings, research summaries, extracted facts, or investigation notes need to be STRUCTURED into interlinked knowledge notes for follow-up and retrieval — e.g. "turn these findings into notes", "file this into my notes", "structure this research", "classify these summaries", "write up these findings as notes", or after a research/extraction pass produces summaries that need to land as Markdown notes. Librarian authors INTERNAL findings notes (Markdown + YAML frontmatter, CSV for tables), portable-first and Obsidian-vault-aware when a vault is configured. It does NOT write outward-facing prose (blog posts, articles, published copy) — that is Copydesk's job, and the two never cross-trigger. If the request is to publish or polish prose for an audience, this is the wrong skill.
version: 0.1.0
---

# Librarian: structuring findings into notes

Librarian is the output layer of the Fieldwork suite. It turns incoming
findings/summaries into **note specs** in the neutral input contract, then writes
them as Markdown notes (and CSV tables) via the bundled scripts. It is
**portable-first**: no vault, index, or network is required. When an Obsidian vault
is configured (signaled by a `vault_context`), it additionally places notes by
folder and realizes wikilinks.

This skill authors *internal* findings notes for follow-up and retrieval. It is
**not** for outward-facing prose (articles, published copy) — that is Copydesk.
Librarian and Copydesk never trigger on each other.

## The pipeline

```
incoming findings/summaries
   → classify  (this skill / agents/classify-agent.md)  → note specs
   → write     (scripts/write_note.py, scripts/write_table.py)
   → wikilink-scan  (vault mode only; later task)
```

The classify step is the focus of this skill. It produces a `notes_to_create[]`
array in the neutral contract, which `write_note` / `write_table` then consume.

## The neutral input contract

Every note spec is (see `references/prior-art.md` §3 for the full field reference):

```
{
  "title":           string,   // note title; drives the filename (slugified) in portable mode
  "content":         string,   // the note body, OR authoring guidance to expand. Inline ![[embeds]] pass through.
  "frontmatter_meta": object,  // open dict merged into YAML frontmatter: tags[], content-type, created, caller keys.
  "citations":       array,    // sources: URL strings OR structured refs ({doc_id, page, ...}). Renders ## Sources.
  "link_hints":      array,    // candidate link targets (people/orgs/topics). Realized later; merges links + stub_links.
  "priority":        string,   // "primary" | "secondary" | "scan". Drives write order so Tier-1 notes exist first.
  "action":          string    // "create" | "update". "update" in portable mode needs an explicit target.
}
```

Optional top-level sibling: `vault_context` (its PRESENCE flips Librarian from
portable to vault-aware — see Vault mode below).

Read the vocabulary, tag ordering, folders, and frontmatter fields **from the
taxonomy config** (`config/taxonomy.example.json` or a caller-supplied
`taxonomy.json`) — never hardcode them. Load and validate with
`scripts/taxonomy.py`.

## Structuring rules (how to build note specs)

Port of research-workflow SKILL.md §6 and classify-agent Steps 3–4, generalized to
the neutral contract and config-driven taxonomy.

### 1. Aggregate the inputs

Collect the incoming summaries/findings into one batch. (Upstream research-workflow
merged per-hop `summaries_hop*.json` files first; Librarian takes whatever batch the
caller hands it — there is no hop model here.) Each input item typically has a
title, a distillation, source references, and extracted entities/claims.

### 2. Load the taxonomy

```bash
python -c "import sys; sys.path.insert(0,'SCRIPTS'); from taxonomy import load_taxonomy; import json; print(json.dumps(load_taxonomy('CONFIG_PATH'), indent=2))"
```

`load_taxonomy(None)` loads the bundled neutral example; a partial caller config has
its missing keys backfilled from neutral defaults. Use its `content_types`,
`tag_order`, `tag_limit`, `default_folder`, `folder_conventions`,
`frontmatter_fields`, and `moc_pattern` — do not embed an enum or folder name in
this skill.

### 3. Classify each item

For each input item, decide:

- **Content type** — pick from the taxonomy's `content_types`. This becomes the
  first tag and/or `frontmatter_meta.type`. If nothing fits, choose the closest and
  let validation flag it as a lead (never invent a hardcoded enum).
- **Tags** — order them per `tag_order` (default: content-type first, then location,
  then domain). Keep the count within `tag_limit` (default 2–5). Apply tags
  consistently across the batch (the same entity gets the same tag in every note).
- **Citations** — carry every source backing the note into `citations`. A bare URL
  string is the simple case; a structured `{doc_id, page}` ref is supported for
  document/exhibit sources. These render the `## Sources` section.
- **Link hints** — list people/orgs/topics worth linking, in `link_hints`. Do not
  pre-split into real-vs-stub links (that collapse is intentional — the wikilink
  stage decides realization). Include cross-references between batch items.
- **Priority** — `primary` (deep coverage) / `secondary` (supporting) / `scan`
  (brief mention). Drives write order.
- **Action** — see routing below.

### 4. Placement and action routing (couplings 1 + 2)

**Portable mode (default — no `vault_context`):**

- `action` defaults to `create`. There is no index to discover that an item should
  update an existing note, so portable mode does **not** auto-deduplicate. Only honor
  `action: "update"` when the caller supplied it WITH an explicit target path in the
  spec.
- Placement falls back to the taxonomy's `default_folder` (the config analogue of
  research-workflow's hardcoded `Inbox/`). The writer derives the filename by
  slugifying the title.

**Vault mode (`vault_context` present):** see Vault mode below.

Put the chosen folder in `frontmatter_meta.folder`; `validate_note_specs` resolves
it (falling back to `default_folder` when absent).

### 5. Validate the specs

```bash
python -c "import sys, json; sys.path.insert(0,'SCRIPTS'); from taxonomy import load_taxonomy, validate_note_specs; tax=load_taxonomy('CONFIG_PATH'); specs=json.load(open('SPECS_JSON')); print(json.dumps(validate_note_specs(specs, tax), indent=2))"
```

`validate_note_specs` returns `{"normalized": [...], "warnings": [...]}`. It defaults
`priority`/`action`, resolves `folder`, and emits **warnings** (not rejections) for
an unknown content type, an out-of-range tag count, a missing title, or an invalid
priority. Treat warnings as leads to review — per the design's "flags-as-leads, not
verdicts" rule, a warning never drops a note. Fix what is genuinely wrong; otherwise
proceed with the normalized specs.

### 6. Hand off to the writers

- **Notes** → `scripts/write_note.py` `write_note(spec, out_dir)`: writes one
  Markdown note (YAML frontmatter from `title` + `frontmatter_meta`, body from
  `content`, a `## Sources` section from `citations`) and never clobbers an existing
  note. Write higher-priority notes first so later notes can reference them.
- **Tabular payloads** (stats tables, redacted exhibits) → `scripts/write_table.py`
  `write_table(rows, out_dir, name, columns=None)`: writes a CSV and returns a
  Markdown-table mirror string for embedding in a note.

The writers are deterministic and take no clock/vault/network; any `created`
timestamp must be supplied by the caller in `frontmatter_meta`.

## Vault mode (only when `vault_context` is supplied)

Portable mode never touches a vault or index. When the caller supplies a
`vault_context` (`existing_notes_found`, `suggested_moc_update`,
`folder_conventions`), Librarian additionally:

- routes `action: "update"` to an existing note discovered in the vault, merging new
  information in and never discarding existing content;
- places notes by the vault's `folder_conventions` / `folder_map` instead of the
  flat `default_folder`;
- after writing, updates any MOC/index note matching the taxonomy's `moc_pattern`
  (default `^_|MOC|Index|Hub`), and the `suggested_moc_update` target if set;
- realizes `link_hints` into `[[wikilinks]]` via the companion wikilink-scanner
  agent (a later task).

The vault-index lookups that drive update-vs-create discovery and link-target
existence live behind this `vault_context` gate (coupling 1). The index is a
*capability*, not a prerequisite; the portable path is a strict subset that never
imports it.

## The classify agent

`agents/classify-agent.md` packages steps 1–4 above as a discrete, Haiku-able unit
with the stable `notes_to_create[]` JSON contract, so Magpie and Research can
dispatch it identically. Dispatch it with: the incoming summaries/findings, the
taxonomy config, and an OPTIONAL `vault_context`. It returns the `notes_to_create[]`
array; feed that to `validate_note_specs` and then the writers.

The classify **agent's** live LLM behavior is validated by integration use, not unit
tests. The unit-tested contract is `scripts/taxonomy.py` (`load_taxonomy` +
`validate_note_specs`), covered by `tests/test_taxonomy.py`.

## Additional resources

- **`references/prior-art.md`** — the extraction map: the neutral contract field
  reference (§3), the three couplings (§2), and the source→home mapping (§1).
- **`config/taxonomy.example.json`** — the editable neutral taxonomy. Copy to
  `taxonomy.json` and override `content_types` / folders for a specific domain.
- **`scripts/taxonomy.py`** — `load_taxonomy`, `validate_note_specs`.
- **`scripts/write_note.py`**, **`scripts/write_table.py`** — the writers.
- **`agents/classify-agent.md`** — the dispatchable classify agent.
