# Librarian Extraction Map (prior art)

**Task 1.0 deliverable.** This is the spec that governs Tasks 1.1–1.4. It maps each
piece of `research-workflow`'s findings-notes pipeline (Stages 6/7/8: classify →
write → wikilink-scan) onto its Librarian home, documents the three couplings that
must be severed to make Librarian portable-first, and defines the neutral input
contract.

**The extraction is decoupling, not rewriting** (Magpie design §5.7). research-workflow's
Stages 6/7/8 are clean agent-instruction units already; the work is to (1) make the
vault-index queries optional, (2) generalize the internal note-spec into a neutral
input contract, and (3) lift the hardcoded surveillance-vault taxonomy into config.
The prose rules, the classify schema, and the wikilink agent are ported close to
verbatim — only their vault assumptions are loosened.

All file references below were verified by reading the actual research-workflow source
(commit state as of 2026-06-03). Absolute paths are given on first reference;
thereafter paths are relative to `research-workflow/` (abbreviated `rw/`).

---

## 0. What I read (provenance)

Source repo: `C:\Users\tim\OneDrive\Documents\Projects\research-workflow\`

| File | What I confirmed it does |
|------|--------------------------|
| `skills/research/SKILL.md` (1590 lines) | The v3 orchestrator. **Stage 6 (classify)** = lines 793–874; **Stage 7 (write)** = lines 878–1068; **Stage 8 (wikilink-scan)** = lines 1071–1165. The write stage is **inline orchestrator prose**, not a script. |
| `agents/classify-agent.md` (195 lines) | Haiku agent: queries vault index, classifies content type, assigns tags/links/write_model, emits the `notes_to_create` JSON spec + `contradictions_detected`. |
| `agents/wikilink-scanner.md` (137 lines) | Haiku agent: scans new + existing notes for wikilink opportunities, emits an `edits[]` plan. |
| `scripts/vault_index.py` (200 lines) | SQLite FTS5 index over an Obsidian vault. `update_index()`, `search()`, `note_exists()`, `list_notes()`. |
| `scripts/config_manager.py` (64 lines) | JSON config at `{vault}/.research-workflow/config.json`. `default_config()` holds folder/frontmatter conventions. |
| `scripts/produce_output.py` (208 lines) | **NOT the write stage.** A downstream Ollama transformer (research note → web_article / video_script / social_post). Out of scope for Librarian; flagged below to prevent mis-porting. |
| `scripts/accumulator.py` (244 lines) | Candidate-pattern store for the v3.1 case-learning loop (Stage 10). **Out of scope** — learning is a research-workflow concern, not findings-notes. |
| `scripts/vault_lint.py` (130 lines) | Frontmatter validator; already reads `frontmatter_fields` from config. Adjacent prior art for the config-driven taxonomy idea. |
| `scripts/state.py` (lines 444–628) | Run/stage state. The write stage's tracking helpers (`append_written_note`, `save_stage_output`, `load_stage_output`, `init_topic`, `write_case_record`) live here — tightly bound to research-workflow's run model. |
| `scripts/prompts/vault_rules.txt` (29 lines) | The hardcoded wikilink + citation + **tagging** conventions, injected into Ollama note generation. The content-type tag enum and tag ordering live here AND in `classify-agent.md`. |
| Magpie design `docs/plans/2026-06-03-magpie-design.md` §5.7 | The decoupling brief this map implements. |

**Key structural finding:** there is **no `write_note.py`** in research-workflow (verified
by file search). Stage 7 is executed by the Sonnet orchestrator directly via the
Write/Read/Edit tools, following the prose rules in `SKILL.md` §7c.v, with note-tracking
side-effects going through `state.py` helpers. Librarian's `scripts/write_note.py`
(Task 1.2) is therefore a **new home for logic that currently lives as orchestrator
prose + state side-effects**, not a lift-and-shift of an existing script. This is the
single most important nuance for Task 1.2.

---

## 1. Source → home mapping table

| research-workflow source (file · section/function) | Librarian home | Port type |
|---|---|---|
| **Stage 6 classify** — `skills/research/SKILL.md` §6 (lines 793–874): aggregate summaries (6a), dispatch classify agent (6b), parse `notes_to_create` + `vault_context` + `contradictions_detected` (6c) | `skills/librarian/SKILL.md` — the "structure incoming findings into note specs" rules | Port prose; strip the per-hop/`summaries_hop*.json` aggregation (research-workflow-specific) and the learned-pattern injection (§6b learned-pattern block). |
| **classify content-type + placement + tag/link rules** — `agents/classify-agent.md` Steps 3–4 (lines 73–135) + Output schema (lines 137–195) | `skills/librarian/SKILL.md` structuring rules; **plus a Librarian classify agent is warranted** at `agents/classify-agent.md` (Librarian) because the classify step is a discrete Haiku-able unit with a stable JSON contract. Keep it as an agent so Magpie/Research can dispatch it identically. | Port agent near-verbatim; replace hardcoded enum/folders with config refs (coupling 3); make the "Step 1: Query Vault Index" block conditional (coupling 1). |
| **Stage 7 write logic** — `skills/research/SKILL.md` §7c.v "Write the note content" (lines 959–1030): frontmatter block, body callouts, wikilinks, tags, sources, format-matching, media embeds; §7b priority sort (lines 907–914); §7c.i mtime-conflict guard (lines 918–942) | `scripts/write_note.py` (Librarian) — the deterministic parts (frontmatter assembly, `## Sources` section assembly, filename/folder resolution, mtime-conflict check, priority sort, atomic write) become a callable script. The *authoring* judgement (what prose to write for `create`/`update`) stays in `skills/librarian/SKILL.md` as rules the caller follows. | **New script.** No `write_note.py` exists upstream — this consolidates inline orchestrator prose (§7c.v) + `state.py` side-effects into one portable module. Drop `research_run`/`hop_genealogy`/`confidence` frontmatter unless supplied via `frontmatter_meta`. |
| **write-stage state side-effects** — `scripts/state.py`: `append_written_note` (565–574), `save_stage_output`/`load_stage_output` (552–562), `init_topic` (444–467), `write_case_record` (617–627) | Librarian does **not** port these. They belong to research-workflow's run/resume/case model. Librarian's `write_note.py` returns a result object (paths written, conflicts skipped); the *caller* (research-workflow or Magpie) records run state. | Exclude. Boundary marker: this is where "findings notes" ends and "pipeline orchestration" begins. |
| **Stage 8 wikilink-scan** — `skills/research/SKILL.md` §8 (lines 1071–1165): refresh index (8a), determine project folder (8b), dispatch scanner (8c), apply edits (8d) | `agents/wikilink-scanner.md` (Librarian) + the apply-edits loop documented in `skills/librarian/SKILL.md` | Port. §8a "Refresh vault index" and §8c's `vault_index.search` calls become vault-mode-only (coupling 1). The edit-apply loop (§8d) is vault-agnostic and ports as-is. |
| **wikilink agent** — `agents/wikilink-scanner.md` (Steps 1–4 + Output, lines 30–137) | `agents/wikilink-scanner.md` (Librarian) | Port near-verbatim. Its **Step 2 "Query Vault Index"** (lines 39–47) is the only vault-coupled part → guard behind a configured vault; without a vault, the agent links only among the new-notes set (`new_notes`) and `link_hints`, skipping the index lookup for pre-existing vault notes. |
| **vault-index logic** — `scripts/vault_index.py` (whole file; `update_index` 130–157, `search` 166–183, `note_exists` 194–199) | Librarian's **optional vault-mode path** (Task 1.3) — wrapped so it is only imported/called when `vault_context` indicates a configured vault. | Port as the vault adapter. Portable-first default never touches it. |
| **taxonomy / folder & tag conventions (hardcoded)** — `agents/classify-agent.md` content-type enum (line 100), `Inbox/` fallback (line 93), `Projects/Surveillance/South Carolina/` + `greenville-sc`/`surveillance` examples (lines 151–158); `scripts/prompts/vault_rules.txt` content-type enum + `greenville-sc, sc` + `strategic-/tactical-/area-` prefixes (lines 25–28); `scripts/config_manager.py` `default_config` (`inbox`, `moc_pattern`, `frontmatter_fields`, lines 15–32) | `config/taxonomy.example.json` (Librarian, Task 1.4) | Lift the enum + folder conventions + tag-ordering + frontmatter fields into config; the skill/agent read them instead of hardcoding. |
| **MOC update rules** — `skills/research/SKILL.md` §7d (lines 1061–1068) + `config_manager.default_config["moc_pattern"]` (`"^_|MOC|Index|Hub"`) | `skills/librarian/SKILL.md` (vault-mode section); `moc_pattern` → `config/taxonomy.example.json` | Port as vault-mode-only; the MOC regex is already a config value upstream, so it lifts cleanly. |
| **frontmatter validation** — `scripts/vault_lint.py` (`frontmatter_fields` from config, lines 92–93) | Optional Librarian utility (not required for 1.1–1.4); informs the `frontmatter` config block | Reference only; already config-driven upstream. |

### Explicitly out of scope (do NOT port)

- `scripts/produce_output.py` — downstream publishing transformer (Ollama → web_article/
  social_post/video_script). This is *outward-facing prose* territory, which is **copydesk's**
  job, not Librarian's (design §5.7: Librarian and copydesk must never cross-trigger).
  Named here because its filename ("produce output") invites mis-porting.
- `scripts/accumulator.py`, `scripts/case_analyzer.py`, `scripts/learned_patterns.py` —
  the v3.1 case-learning loop (research-workflow Stage 10). Findings-notes is upstream of
  learning.
- `scripts/state.py` run/resume/hop machinery — research-workflow pipeline orchestration.
- Stages 0–5, 9, 10 of `SKILL.md` (config/tier detection, triage, resolve, hop loop,
  quality gate, thread discovery, complete) — not part of the findings-notes seam.

---

## 2. The three couplings to sever

### Coupling 1 — vault-index queries → make optional (portable-first)

**What it currently IS in research-workflow:**

The vault index is an SQLite FTS5 database at `{vault}/.research-workflow/vault_index.db`,
implemented in `scripts/vault_index.py`. It is queried at four points in the
findings-notes path:

1. `SKILL.md` §0c (lines 98–111) and §8a (lines 1086–1098) call
   `vault_index.update_index(VAULT)` to keep the FTS5 index current before agents query it.
2. `agents/classify-agent.md` **Step 1** (lines 46–61) runs 2–4 `vault_index.search()`
   queries to find existing notes to update/link, then derives `action: "update"` vs
   `"create"` and the target `folder` from index hits (lines 85–94).
3. `agents/wikilink-scanner.md` **Step 2** (lines 39–47) runs `vault_index.search()` per
   entity to decide whether a matching vault note already exists to link to.
4. `SKILL.md` §4e (line 565) passes `vault_index_path` to the hop-planner — outside the
   findings-notes seam, ignore.

So in research-workflow, **deduplication, update-vs-create routing, folder placement, and
"does a link target exist" all depend on a populated vault index.** No vault index ⇒ the
classify and wikilink agents have nothing to query.

**How Librarian decouples it:**

Make every `vault_index` call **conditional on a configured vault**, signaled by the
optional `vault_context` input (§3 below). Behavior matrix:

- **No vault (portable-first, default):**
  - classify never queries an index. `action` defaults to `create` unless the caller
    supplied `action: "update"` with an explicit target path in the input spec.
  - Placement falls back to a configured default folder (the config analogue of
    research-workflow's hardcoded `Inbox/`).
  - wikilink-scanner links only *within the current batch* (`new_notes`) and from
    `link_hints`; it skips the "does a pre-existing note exist" index lookup.
- **Vault present (`vault_context` supplied):** import the ported `vault_index.py`
  adapter and run the same `update_index` → `search` flow research-workflow uses today.
  The vault adapter is the only place that imports SQLite.

Net: the index becomes a *capability*, not a *prerequisite*. The portable path is a strict
subset that never imports `vault_index`.

### Coupling 2 — internal note-spec → neutral input contract

**What it currently IS in research-workflow:**

The classify agent emits a research-workflow-specific note spec. Per `agents/classify-agent.md`
Output schema (lines 145–195) and `SKILL.md` §6c (lines 849–852), each entry of
`notes_to_create` is:

```
{ title, filename, folder, action, type, write_model, content_summary,
  source_urls, tags, links, stub_links, media, priority }
```

with a sibling `vault_context` object `{ existing_notes_found, suggested_moc_update,
folder_conventions }` and a run-level `contradictions_detected[]`. This spec is welded to
research-workflow's world: `write_model` (sonnet/opus) is a research-workflow routing
decision; `type` uses the surveillance content-type enum; `source_urls` assumes web
research (not arbitrary citations); `media` is a dead v2 field (always `[]` in v3, per
classify-agent.md line 192); `filename`/`folder` assume vault layout.

**How Librarian decouples it:**

Generalize to the neutral contract (design §5.7 item 2):

```
[{title, content, frontmatter_meta, citations, link_hints, priority, action}]
```

plus an optional top-level `vault_context`. Mapping from research-workflow's current spec:

| research-workflow field | Neutral field | Notes |
|---|---|---|
| `title` | `title` | unchanged |
| `content_summary` (write guidance) **+** the note body the orchestrator authors in §7c.v | `content` | The neutral contract carries the *content* (or the guidance to produce it). Librarian no longer assumes a separate "summary vs. full body" split tied to the summarize stage. |
| `tags` + `type` | `frontmatter_meta` | `frontmatter_meta` is an open dict for frontmatter. `type`/content-type tag moves here; `tags[]` lands here. Validated against `config/taxonomy.example.json` (coupling 3), not a hardcoded enum. |
| `source_urls` | `citations` | Generalized from "web URLs" to any citation (URL, doc_id+page, evidence-manifest ref). This lets Magpie pass document/exhibit citations, not just URLs. The `## Sources` assembly (SKILL.md §7c.v "Sources", lines 1005–1017) renders from `citations`. |
| `links` + `stub_links` | `link_hints` | Both collapse into one hint list. The wikilink stage (and vault adapter) decide which become real `[[wikilinks]]`, which become `[[stub]]`s, and which are dropped — exactly the §7c.v wikilink rules, now driven by hints instead of two pre-split arrays. |
| `priority` | `priority` | unchanged (`primary`/`secondary`/`scan`); drives §7b sort order. |
| `action` | `action` | unchanged (`create`/`update`). In portable mode `update` requires an explicit target in `frontmatter_meta`/spec since there's no index to resolve it. |
| `filename`, `folder` | — | **Not in the neutral contract.** Derived by Librarian: portable mode → config default folder + slugified title; vault mode → vault adapter (index-resolved folder, as today). |
| `write_model` | — | **Dropped.** Model routing is the caller's concern, not findings-notes. (research-workflow can still choose its writer model; Librarian doesn't dictate it.) |
| `media` | — | **Dropped.** Dead v2 field (always empty in v3). Inline `![[embeds]]` already live in `content`; the §7c.v rule "preserve any `![[path]]` in source content" is honored by passing them through `content`. |
| `vault_context` (`existing_notes_found`, `suggested_moc_update`, `folder_conventions`) | `vault_context` (optional, top-level) | Retained verbatim as the *vault-mode* signal. Its presence is what flips Librarian from portable to vault-aware (coupling 1). Absent ⇒ portable. |
| `contradictions_detected[]` | carried in `frontmatter_meta` / note body callouts | Not a first-class neutral field; the contradiction callout rule (SKILL.md §7c.v body-callouts, lines 987–991) becomes a Librarian option driven by `frontmatter_meta`. |

### Coupling 3 — taxonomy → config

**What it currently IS in research-workflow (exact locations):**

Surveillance-vault conventions are hardcoded in three places:

1. **Content-type tag enum** — duplicated in:
   - `agents/classify-agent.md` line 100: `research, legislation, campaign, plan,
     reference, tracking, decision, index, resource, meta`
   - `scripts/prompts/vault_rules.txt` line 25: same list.
2. **Tag ordering + location/purpose tags** —
   - `classify-agent.md` lines 99–104: "content-type tag first, then location tags, then
     domain tags (e.g., `surveillance`, `privacy`, `policing`)", limit 2–5.
   - `vault_rules.txt` lines 26–28: location tags `greenville-sc, sc`; purpose prefixes
     `strategic-`/`tactical-`; ambiguity prefix `area-`.
   - `SKILL.md` §7c.v "Tags" (lines 1000–1003): repeats the same enum and ordering.
3. **Folder conventions** —
   - `classify-agent.md` line 93: fallback folder hardcoded to `Inbox/`.
   - `classify-agent.md` lines 151–158 (output example): `folder:
     "Projects/Surveillance/South Carolina/"`, tags `["research", "surveillance",
     "greenville-sc"]` — surveillance/SC values baked into the canonical example.
   - `scripts/config_manager.py` `default_config` (lines 15–32): `inbox: "Inbox"`,
     `moc_pattern: "^_|MOC|Index|Hub"`, `frontmatter_fields: ["title","tags","source","created"]`,
     `assets: "assets"`. (These are *already* config — the model to follow.)

**How Librarian decouples it:**

`config/taxonomy.example.json` (Task 1.4) holds, at minimum:

- `content_types`: the enum list (default: research-workflow's 10, but editable). Domains
  that aren't surveillance swap their own.
- `tag_order`: ordered tag categories (default `["content-type", "location", "domain"]`)
  and `tag_limit` (default 2–5).
- `default_folder`: the portable/no-match fallback (the config analogue of hardcoded
  `Inbox/`).
- `folder_conventions`: naming pattern + optional folder map (vault mode).
- `frontmatter_fields`: required frontmatter keys (lifts `config_manager.default_config`
  + `vault_lint`'s usage).
- `moc_pattern`: the MOC-detection regex (lifts `default_config["moc_pattern"]`).

The classify agent and `skills/librarian/SKILL.md` read these instead of embedding the
enum/folders. The shipped example carries neutral defaults (not surveillance-specific) so
Magpie's first run produces sane notes with zero config; a surveillance user overrides with
their own `taxonomy.json`. **No surveillance/SC/Greenville string survives in Librarian
code or shipped config** — those become user-supplied values.

---

## 3. Neutral input contract — field reference

Librarian accepts a list of note specs plus an optional `vault_context`:

```
[
  {
    "title":           string,   // note title; drives filename (slugified) in portable mode
    "content":         string,   // the note body, OR authoring guidance the caller/skill expands.
                                 //   Inline ![[embeds]] and inline source links pass through verbatim.
    "frontmatter_meta": object,  // open dict merged into YAML frontmatter. Carries tags[],
                                 //   content-type, and any caller metadata (confidence, run id, etc.).
                                 //   Tags validated against config/taxonomy.example.json, not a fixed enum.
    "citations":       array,    // sources backing the note. Each item is a URL string OR a
                                 //   structured ref ({doc_id, page, ...}). Renders the ## Sources section
                                 //   and inline citations. Generalizes research-workflow's source_urls.
    "link_hints":      array,    // candidate link targets (people/orgs/topics). Librarian decides which
                                 //   become [[wikilinks]] (vault) vs [[stubs]] vs intra-batch links
                                 //   (portable). Merges research-workflow's links + stub_links.
    "priority":        string,   // "primary" | "secondary" | "scan". Sort order for writing so Tier-1
                                 //   notes exist before lower tiers link to them (SKILL.md §7b).
    "action":          string    // "create" | "update". "update" in portable mode needs an explicit
                                 //   target path (no index to resolve it).
  },
  ...
]
```

Optional, top-level (sibling to the list):

```
"vault_context": {              // PRESENCE flips Librarian from portable to vault-aware.
  "existing_notes_found":  [paths],   // vault notes to read for context / merge targets
  "suggested_moc_update":  path|null, // MOC to update after writing
  "folder_conventions":    object     // naming/folder hints for placement
}                               // ABSENT  => portable-first: no index, config default folder, batch-only links.
```

**Field-by-field meaning:**

- **`title`** — human title. Portable mode derives `filename` = slugified title under the
  config `default_folder`; vault mode lets the vault adapter resolve folder/filename.
- **`content`** — the note body or the guidance to produce it. Replaces research-workflow's
  split of `content_summary` (guidance) vs. the orchestrator-authored body; Librarian no
  longer assumes an upstream summarize stage.
- **`frontmatter_meta`** — everything that lands in YAML frontmatter: `tags`, content-type,
  `created`, and any caller-specific keys (e.g., `confidence`, `research_run`). Keeping it
  an open dict is what lets research-workflow keep its richer frontmatter while Magpie keeps
  a leaner one — neither is hardcoded into Librarian.
- **`citations`** — generalized sources. Renders the `## Sources` section (SKILL.md §7c.v)
  and inline links. A URL string is the simple case; a structured object supports Magpie's
  document/exhibit/evidence-manifest references.
- **`link_hints`** — link candidates. The wikilink rules (SKILL.md §7c.v + wikilink-scanner)
  decide realization. In portable mode, only intra-batch + hint links are created (no index
  lookup for pre-existing notes).
- **`priority`** — tiering for write order (`primary` → `secondary` → `scan`), so earlier
  notes can be linked by later ones.
- **`action`** — `create` or `update`. `update` merges into an existing note (never discards
  content, per SKILL.md §7c.v "Format matching"); requires an explicit target when no index
  is available.
- **`vault_context`** — the on/off switch for vault mode (coupling 1). Carries the three
  research-workflow vault signals verbatim so the ported logic behaves identically when a
  vault is present.

---

## 4. Extraction = decoupling, not rewriting

Librarian re-homes working research-workflow logic; it does not reinvent it. Concretely:

- The **classify schema** (`classify-agent.md` Output) ports near-verbatim — only the
  hardcoded enum/folders become config refs and the index query becomes conditional.
- The **write rules** (`SKILL.md` §7c.v: frontmatter, `## Sources`, wikilinks, tags,
  format-matching, media passthrough, mtime guard, priority sort) port as the behavior of
  `scripts/write_note.py` + `skills/librarian/SKILL.md` — the same rules, now callable
  without a vault.
- The **wikilink agent** (`wikilink-scanner.md`) ports near-verbatim — only Step 2's index
  query is guarded behind a configured vault.
- The **vault index** (`vault_index.py`) ports as an optional adapter, unchanged in
  behavior, imported only in vault mode.

The three couplings are the *only* substantive edits. Everything else is a move.

### Porting sources for Tasks 1.1–1.4 (the contract for later tasks)

Each later task ports exactly these research-workflow files/sections:

- **Task 1.1 — `skills/librarian/SKILL.md` (structuring rules + portable/vault flow):**
  port from `skills/research/SKILL.md` §6 (lines 793–874), §7 (878–1068), §8 (1071–1165),
  and `agents/classify-agent.md` Steps 3–4 (73–135). Apply couplings 1–3.
- **Task 1.2 — `scripts/write_note.py` (NEW script):** port the deterministic write logic
  from `SKILL.md` §7b (priority sort, 907–914), §7c.i (mtime guard, 918–942), §7c.v
  (frontmatter + `## Sources` + tags + wikilink/format rules, 959–1030), §7c.vi (save,
  1031–1034). **Do NOT** port `state.py`'s `append_written_note`/`save_stage_output` —
  return a result object instead. There is no upstream `write_note.py`; this consolidates
  inline prose.
- **Task 1.3 — `agents/wikilink-scanner.md` + optional vault-mode (`vault_index.py`):**
  port `agents/wikilink-scanner.md` (whole file) and `scripts/vault_index.py`
  (`update_index`, `search`, `note_exists`). Guard the index queries (wikilink-scanner
  Step 2, lines 39–47; SKILL.md §8a/§8c) behind a configured vault.
- **Task 1.4 — `config/taxonomy.example.json`:** lift the hardcoded values enumerated in
  coupling 3 — `classify-agent.md` lines 93, 100, 151–158; `prompts/vault_rules.txt`
  lines 25–28; `config_manager.py` `default_config` lines 15–32 — into neutral-default
  config keys (`content_types`, `tag_order`/`tag_limit`, `default_folder`,
  `folder_conventions`, `frontmatter_fields`, `moc_pattern`).

A Librarian classify agent (`agents/classify-agent.md` in this repo) is **warranted** and
recommended as part of Task 1.1/1.2: the classify step is a discrete, Haiku-able unit with a
stable JSON contract, and keeping it an agent lets Magpie and Research dispatch it
identically. If folded into the skill instead, preserve the same JSON output contract.

---

## 5. Gaps / logic that does NOT cleanly decouple (flag for later tasks)

These are the rough edges where "decoupling, not rewriting" needs a judgement call:

1. **Stage 7 has no script to lift.** The write stage is orchestrator prose + `state.py`
   side-effects, not a `write_note.py`. Task 1.2 must *author* a script from prose. Risk:
   over- or under-capturing. Mitigation: the deterministic rules (frontmatter, sources,
   sort, mtime, atomic write) are clearly scriptable; the *authoring judgement* (what prose
   to write for `create`/`update`) must stay as skill rules, not be forced into the script.

2. **update-vs-create routing depends on the vault index.** In research-workflow, `action`
   and the merge target are *derived* from `vault_index.search()` hits
   (`classify-agent.md` lines 85–94). Remove the index and the portable path can only honor
   an `action: "update"` the caller supplies with an explicit target — it cannot *discover*
   that a note should be an update. This is an accepted capability reduction for portable
   mode (design intent), but Task 1.1 must state it so callers know portable mode won't
   auto-dedupe.

3. **`citations` generalization is wider than research-workflow's `source_urls`.** Upstream,
   sources are always web URLs and the `## Sources` renderer + inline-link rules assume that
   (SKILL.md §7c.v). Supporting structured citations (`{doc_id, page}`) for Magpie is a
   genuine *extension*, not a pure move — the renderer needs a second code path. Small, but
   it is net-new logic, not a port. Flag for Task 1.2.

4. **Body-callout features (low-confidence + contradictions) are research-workflow-coupled.**
   SKILL.md §7c.v body-callouts (lines 979–991) read `run.low_confidence`,
   `run.final_confidence_score`, and `classification.contradictions_detected` — all from the
   research-workflow run/state model. In Librarian these must be driven off `frontmatter_meta`
   (caller-supplied) instead of run state, or dropped from the portable core. Decide in Task
   1.1 whether callouts are core or a vault/caller option.

5. **MOC update + media are vault-/v2-specific.** §7d MOC updates only make sense with a
   vault (and an existing MOC); the `media` field is a dead v2 array. Both are handled above
   (MOC → vault-mode + `moc_pattern` config; media → dropped, embeds ride in `content`), but
   Task 1.1/1.2 should confirm no caller still expects the `media` array.

6. **Index freshness assumption.** classify and wikilink-scanner assume `update_index()` ran
   first (SKILL.md §0c, §8a). The vault adapter must own that refresh internally (call
   `update_index` before `search`) since Librarian has no Stage 0 to do it. Flag for Task 1.3.

None of these block the extraction; they are the spots where Tasks 1.1–1.4 must add a thin
layer rather than copy a line. Everything outside this list is a straight move.
