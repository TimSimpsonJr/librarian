# Librarian auto-pull acceptance test (Task 1.6)

> **Status: prepared, pending a live run on a clean Claude Code profile.**
> This step cannot be executed from inside a working session — it needs a real
> install on a fresh profile. The dependency declarations are all in place (see
> "Preconditions"); run the steps below and record the result at the bottom.

## Goal

Confirm that installing a Fieldwork plugin that declares a `librarian` dependency
causes Claude Code to **auto-install `librarian`**, and document the co-install
fallback if cross-repo resolution has rough edges (design doc §9, §11).

## Preconditions (already satisfied in the repos)

- `magpie/.claude-plugin/plugin.json` → `"dependencies": ["librarian"]` (bare string).
- `research-workflow` (branch `wire-librarian-dependency`, **not yet merged**) →
  `"dependencies": ["librarian"]`.
- `fieldwork-plugins/.claude-plugin/marketplace.json` (marketplace name `fieldwork`)
  lists `magpie`, `research-workflow`, `librarian`, `prose-craft` as github-source
  members. Because `librarian` is a **member of the same `fieldwork` marketplace**,
  a `librarian` dependency declared by `magpie`/`research-workflow` resolves
  **same-marketplace** when those are installed via `fieldwork` — no
  `allowCrossMarketplaceDependenciesOn` needed.
- `magpie` and `librarian` GitHub repos are **public**.
- Bare-string dependency (no version constraint) is deliberate: a version
  constraint resolves against `{plugin-name}--v*` git tags, and `librarian` has no
  release tags yet — a constraint would disable the dependent with `no-matching-tag`.

## Scenario A — install via the Fieldwork marketplace (expected to auto-pull)

On a clean Claude Code profile:

1. `/plugin marketplace add TimSimpsonJr/fieldwork-plugins`
2. `/plugin install magpie@fieldwork`  (or `research-workflow@fieldwork`)
3. **Expected:** the install output lists `librarian` among auto-installed
   dependencies. Verify with `claude plugin list` — `librarian` present + enabled.

## Scenario B — install research-workflow standalone (the cross-repo edge)

This is the case the design flags as risky (design §11): research-workflow installed
from its **own** repo as a marketplace, where `librarian` lives in a *different* repo.

1. `/plugin marketplace add TimSimpsonJr/research-workflow`
   *(requires the `wire-librarian-dependency` branch to be merged to research-workflow's
   default branch first, AND research-workflow to expose a marketplace.json — confirm
   that exists before running this scenario; if research-workflow has no marketplace.json,
   it is installed via the `fieldwork` marketplace instead, i.e. Scenario A.)*
2. `/plugin install research-workflow@<marketplace>`
3. Run a minimal `/research` that reaches the write stage (Stage 7).
4. **Expected (best case):** `librarian` auto-installs and Stages 6/7/8 work (via the
   feature-flagged shim or natively).
   **If auto-pull FAILS** (dependency in an un-added marketplace is left unresolved):
   use the **co-install fallback** below.

## Co-install fallback (if Scenario B auto-pull fails)

```
/plugin marketplace add TimSimpsonJr/fieldwork-plugins   # makes librarian resolvable
/plugin install librarian@fieldwork
```

Then re-run `/plugin install research-workflow@...` (or `/reload-plugins`) to satisfy
the now-resolvable dependency. If this fallback is needed, file an `autonomous-safe`
issue on `research-workflow` noting the standalone-install resolution gap, and document
the fallback in the research-workflow README.

## Record the result here

- Date run:
- Scenario A (fieldwork install) auto-pulled librarian:  yes / no
- Scenario B (standalone) auto-pulled librarian:          yes / no / n-a (no standalone marketplace)
- Co-install fallback needed:                             yes / no
- Notes:
