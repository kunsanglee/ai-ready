---
name: audit
description: "Audit a repository for AI-agent readiness using a seven-category rubric and create reviewable local artifacts. Use when the user asks for an AI-ready audit, AI-agent readiness score, codebase navigation/guidance audit, module-guidance scaffolds, or anti-pattern discovery from Git history."
---

# AI-Ready Audit

Create a reproducible, reviewable readiness assessment. The audit may write only
under the selected repository's `.ai-ready/` directory; it does not alter source
code, guidance documents, Git settings, or remote systems.

## Preflight

1. Resolve the target from the user's explicit path or the current Git root. If no Git root is available, ask for a target rather than guessing.
2. Confirm the target and output path `<target>/.ai-ready/`. Do not write outside the selected target.
3. Read the closest root guidance (`AGENTS.md` or `CLAUDE.md`) before generating drafts. Treat an authored `AGENTS.md` as canonical; a bridge/symlink remains a compatibility detail.
4. Explain that the audit score measures navigation and guidance quality, not general code health or security.

## Run the baseline

Run the bundled standard-library scripts from this skill directory in this order:

```text
python3 scripts/audit.py --target <target> --out <target>/.ai-ready
python3 scripts/scaffold.py --target <target> --out <target>/.ai-ready/scaffolds --top <N>
python3 scripts/extract_antipatterns.py --target <target> --out <target>/.ai-ready/scaffolds/ANTIPATTERNS.md --days <D>
python3 scripts/dashboard.py --audit <target>/.ai-ready/audit.json --out <target>/.ai-ready/dashboard.html
```

Use `N=5` and `D=180` unless the user gives different values. Read
`references/RUBRIC.md` when interpreting category scores or recommended actions.

## Report and boundaries

1. Summarize the score, strongest and weakest categories, and the first three ROI actions from `audit-report.md`.
2. Identify generated artifacts as drafts. Never move a scaffold into the repository's live guidance path without the `apply` workflow and per-file approval.
3. Do not install lifecycle hooks, change `.claude/settings.json`, create a Codex hook, or claim automatic freshness enforcement. Use the `freshness` skill for an explicit read-only check.
4. Preserve `.ai-ready/history/` when re-running the audit so the dashboard can show trends.

## Non-goals

- Do not score a repository as secure, tested, or production-ready solely from this rubric.
- Do not overwrite human-authored `AGENTS.md`, `CLAUDE.md`, or documentation.
- Do not fetch, push, or use credentials.
