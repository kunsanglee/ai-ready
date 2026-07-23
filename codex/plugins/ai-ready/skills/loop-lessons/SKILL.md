---
name: loop-lessons
description: "After an unattended loop ends, turn the mistakes it caught into candidate entries for the project's permanent knowledge layer, for human review. Use for AI-ready loop lessons, promoting loop findings into anti-pattern candidates, or closing the loop's learning cycle; the human decides what is adopted, this skill only drafts."
---

# AI-Ready Loop Lessons

Close the loop's learning cycle: take the mistakes an unattended loop caught and draft candidate entries for the project's permanent knowledge layer (for example `docs/ANTIPATTERNS.md`), for a human to review. This skill writes drafts only — a human decides what is added, changed, or dropped. It never edits the knowledge layer directly.

## Workflow

1. Resolve the engine path once (it ships at `_loop-engine/` under this plugin, two directories up from this skill's directory).
2. Gather the mistakes the loop caught. The primary source is the loop's history in loop scratch (for example `.loop/run/history*.jsonl`); run `bash "$ENGINE/lessons.sh" --history <file>` per history file and merge the resulting mistake list. Add any human or PR-comment corrections captured during the run.
3. For each recurring or high-signal mistake, draft a knowledge-layer candidate in the project's format (a DO NOT statement, the reason, and what to do instead), citing the finding that motivated it.
4. Present the candidates to the human as a review list. Do not write them into the knowledge layer or any rubric yourself.

## Boundaries

- Do not edit the permanent knowledge layer or a project rubric directly — a human approval gate is mandatory.
- Do not reuse fixed provider model names or Claude-only agent names.
- One-off mistakes with no recurrence risk are not candidates; keep the list to lessons worth preventing again.
