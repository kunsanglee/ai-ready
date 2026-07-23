---
name: freshness
description: "Check whether repository AGENTS.md or CLAUDE.md guidance is older than nearby source changes without modifying files. Use when the user asks for a guidance freshness check, documentation drift check, or stale agent-instructions check."
---

# Guidance Freshness

Run a read-only drift check for repository guidance. This replaces the Claude
Stop-hook behavior with an explicit command that works in any harness.

## Workflow

1. Resolve a user-specified target or the current Git root.
2. Run `python3 scripts/freshness_check.py --target <target>`.
3. Use `--threshold-days <N>` only when the user specifies a different age threshold; default to the script's default.
4. Report each stale document, its newer source evidence, and the threshold. A missing document is a coverage observation, not a reason to create one automatically.
5. Offer a draft or the `apply` workflow only when the user requests a fix.

## Boundaries

- Do not write a hook, edit settings, or change documentation.
- Do not treat file mtime alone as proof that guidance content is wrong.
- Do not scan outside the selected repository.
