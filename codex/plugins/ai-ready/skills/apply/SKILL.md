---
name: apply
description: "Turn an existing AI-Ready audit into a small, reviewed set of guidance and documentation improvements. Use when the user explicitly asks to apply, implement, or prioritize actions from `.ai-ready/audit.json` or an AI-ready audit report."
---

# AI-Ready Apply

Apply only user-approved improvements from a prior audit. Preserve human curation
and treat every live-document write as a separate approval boundary.

## Preflight

1. Resolve the selected repository and read `<target>/.ai-ready/audit.json` and `audit-report.md`. Stop if they are absent or stale relative to the requested target.
2. Read the relevant root and nested `AGENTS.md`/`CLAUDE.md` files. Determine which file is canonical; do not update both independently when one is a compatibility bridge.
3. Convert the top requested actions into a short table: action, target file, evidence source, expected change, and whether it is draft-only or a live write.
4. Exclude source-code refactors, deployment, credential changes, remote actions, and lifecycle-hook installation from this workflow.

## Apply safely

1. Use bundled facts-only script modes where available to inspect document facts without rewriting a file.
2. Read the entire target document before proposing a change. Preserve its human-written grouping, order, prose, and explicit exceptions.
3. Show a concise per-file diff or exact proposed replacement. Obtain explicit approval for that file before writing it.
4. Prefer these actions in order: guidance map/index additions, document trigger improvements, anti-pattern draft adoption, and narrowly scoped architecture or convention notes.
5. Keep generated scaffolds under `.ai-ready/scaffolds/` until the user approves adoption into a live path.
6. Re-run the audit after approved changes and report score movement with its limitations.

## Codex boundary

- Do not modify `.claude/settings.json` or emulate a Claude Stop hook.
- Do not alter global Codex settings, install plugins, or configure CI/pre-commit automatically.
- Recommend the `freshness` skill, a reviewed CI check, or a project-owned hook only after explaining the required implementation.
