---
name: loop-run
description: "Converge a single local change to PASS with an unattended maker/checker loop, where the Codex session orchestrates and a deterministic shell engine makes the verdict. Use for AI-ready loop run, unattended single-change convergence, or driving one change to a clean rubric verdict; not for multi-phase build-out (use loop-build) or a one-shot read-only review (use loop-review)."
---

# AI-Ready Loop Run

Drive one change to a clean verdict with an unattended loop. The Codex session is the **orchestrator**: it delegates implementation and review to subagents, runs the deterministic engine to score, and obeys the engine's verdict. This mirrors how the same loop runs on Claude — a model orchestrator plus a shell that owns the verdict.

## Invariants (do not break)

1. **Maker and checker are separate subagents.** The orchestrator never reviews its own implementation. Delegate implementation and review to distinct subagents.
2. **The shell engine assigns severity and the verdict, not the model.** The checker only classifies findings; `_loop-engine` scores them. Never declare PASS or RETRY yourself — report exactly what the engine prints.
3. **The gate runs before the checker.** Build and test must pass before a review cycle; a broken gate goes straight back to the maker.
4. **Irreversible areas stop the loop.** Anything touching production data DML/DDL, money, authorization, mass sends, or deletion is `AWAIT_USER` — stop and hand to a human.
5. **The findings file is the recovery path.** A delegated subagent's output does not surface in the orchestrator's event stream, so the checker writes its findings JSON to a file and the orchestrator reads that file, never the subagent's chat text.

## Setup

1. Resolve the Git root of the target change and the compare base (default `origin/main`; fall back to the repository's default branch).
2. Resolve the engine path once, before doing anything else. The engine ships at `_loop-engine/` under this plugin (two directories up from this skill's directory). Capture it as an absolute path, for example `ENGINE="$(cd "<this skill dir>/../../_loop-engine" && pwd)"`, so it stays valid after you change into the target repository.
3. Create a scratch directory for loop state outside version control (for example `.loop/run/` in the target repo, git-ignored) and choose a findings output path there, such as `.loop/run/findings.json`.
4. Read the maker and checker role contracts from `references/maker-role.md` and `references/checker-role.md` in this skill directory — you will pass their text inline when delegating.

## Cycle

Repeat until PASS, brake, or AWAIT_USER:

1. **Delegate the maker.** Spawn a subagent whose task is the maker role contract plus the concrete change to implement and the convention docs to follow. Do not implement it yourself.
2. **Gate.** Run the project build and test commands with their combined output redirected to a file, not into your context. Compile first; if it fails, do not run the tests. On failure turn that file into a work queue — `python3 "$ENGINE/gate_parse.py" --stage <build|test|lint> <output file> >> <loop dir>/gate-queue.jsonl` — which emits one JSON item per line carrying `kind`, `file`, `line_number`, `message`, and the original `raw` line. Truncate the queue at the start of every gate run, because the gate re-runs each cycle and a leftover item makes the maker chase an error that is already fixed. Hand the queue to a maker subagent, repeat the gate, and do not proceed until it passes.
   - The parser never emits an empty queue. With no recognised error format it keeps the output tail as a single `gate-output-unparsed` item, because an empty queue reads as a pass and that misreading is what the queue exists to prevent.
   - **A non-empty gate queue takes precedence over the findings file.** A failed gate means the checker never ran this cycle, so the findings file still holds the previous cycle's values. Fixing those first means chasing problems that no longer exist.
   - Work the queue in the order `compile-error`, `test-failure`, `lint-violation`. Test failures carry no information while compilation is broken, and lint violations do not affect behaviour.
   - Open only the `file` and `line_number` an item points at. `raw` is the fallback when the parser split a line wrongly; the full output stays in the file for reading around a specific item. Never pull it into the orchestrator's context wholesale — a lint gate can produce thousands of items.
3. **Delegate the checker.** Spawn a separate subagent whose task is the checker role contract plus the original task summary, the compare base, and the findings output path. It writes `{"base", "findings": [...]}` to that path. Do not review the diff yourself and do not write the findings file yourself.
4. **Score (deterministic).** Run exactly `bash "$ENGINE/score.sh" <findings path> | bash "$ENGINE/decide.sh"`. It prints a JSON object with a `verdict` field. Use only what it prints.
5. **Obey the verdict.**
   - `PASS`: done. Report the counts and stop.
   - `RETRY` or `RETRY_SOFT`: hand the findings file back to a maker subagent to fix, then return to the gate.
   - `AWAIT_USER`: stop and hand to a human — do not continue.
6. **Brake.** Stop and report if you have run more than the allowed iterations (default 5) or the elapsed budget is exhausted. Never loop unbounded.

## Model and effort

Model and reasoning effort are set at the session level, not hardcoded in this skill. Delegated maker and checker subagents inherit the session's model and effort — the checker inheriting the session matches the Claude loop, and effort inheritance to subagents is confirmed (a session launched at `high` runs its delegates at `high`).

- **Interactive**: the model and effort chosen in the Codex session are what the loop uses. No extra setup.
- **Headless / automated**: launch through `loop-launch.sh`, which reads `loop-profile.env` (`LOOP_MODEL`, `LOOP_EFFORT`) and starts the session with `-m <model> -c model_reasoning_effort=<effort>`. Change the model or effort in that one profile file — never in this skill.
- **Effort values** follow the neutral ladder (`minimal`, `low`, `medium`, `high`, `xhigh`, `max`); Codex accepts these tokens directly, and `xhigh` is model-dependent. See the shared effort ladder for the cross-host contract.
- This is a **uniform profile**: maker and checker share the session's model and effort. Running them on different tiers (a cheaper maker, a more thorough checker) needs registered per-agent pins and an explicit launch, which is a later step.

## Boundaries

- Do not commit, fetch, or push — the loop stops at an uncommitted working tree; a human finishes the commit and PR.
- Do not reuse fixed provider model names or Claude-only agent names in the loop logic.
- Score with the shell engine only; do not re-implement severity or the verdict in the model.
