# Librarian

**Fieldwork: Librarian** — a shared Claude Code skill that turns findings into
structured, interlinked, browsable knowledge notes organized for follow-up and
retrieval.

Librarian is the **output layer** for the Fieldwork suite. Magpie and Research both
depend on it (auto-pulled via plugin `dependencies`). It authors *internal* findings
notes — explicitly **not** outward-facing prose. That is Prose Craft's job, and the
two never trigger on each other.

> **Status:** Layer 0–1 extraction in progress. Librarian is being decoupled from
> research-workflow's Stages 6/7/8 (classify → write → wikilink). The extraction is
> decoupling, not rewriting (see the Magpie design doc §5.7).

## What it does

- **Portable-first output.** Markdown notes with YAML frontmatter and a `## Sources`
  section, plus CSV for tabular payloads. No vault required.
- **Vault-aware when present.** When an Obsidian vault is configured, it places notes,
  adds wikilinks (companion `wikilink-scanner` agent), and enforces the vault
  redaction policy.
- **Config-driven taxonomy.** Folder conventions and content-type tags are
  configuration, not hardcoded.

## Input contract

```
[{title, content, frontmatter_meta, citations, link_hints, priority, action}]
```

plus an optional `vault_context`.

## License

MIT — see [LICENSE](LICENSE).
