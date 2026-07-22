---
name: loop-build
description: "Build out a settled design across multiple phases with an unattended loop, where the Codex session orchestrates maker/checker subagents and a deterministic shell engine makes each verdict. Use for AI-ready loop build, multi-phase unattended build-out from a design or spec, or driving a decomposed plan to completion; not for a single change (use loop-run) or a one-shot review (use loop-review)."
---

# AI-Ready Loop Build

Build a settled design out across several phases without a human in the loop per step. The Codex session is the **orchestrator**: it decomposes the design into phases, drives each phase to PASS with the same maker/checker cycle as `loop-run`, and advances. It writes no code itself and makes no verdict itself — the deterministic engine does.

This is the multi-phase wrapper around the `loop-run` cycle. Read `loop-run`'s SKILL first: its invariants, setup, cycle, model note, and boundaries all apply here unchanged. This skill adds phase decomposition and a phase loop around that cycle.

## Start gate (the one human approval)

Unattended execution starts only after phase decomposition is approved once.

1. Read the design or spec. Decompose it into phases, each a list of self-contained steps. A good step is self-contained, one layer, specified to a signature, and verifiable by a runnable command (build, test, lint). If the design cannot be split into such steps, stop and return to the human — do not start unattended.
2. Write the decomposition to loop scratch (for example `.loop/run/phases.json`), with each phase and step carrying a status of `pending`, `in_progress`, `done`, or `blocked`, and a design reference.
3. Get human approval of the decomposition. After approval the human steps away and the orchestrator runs autonomously until PASS, brake, or AWAIT_USER.

## Phase loop

Resolve the engine path once as in `loop-run` setup. Then for each phase in order:

1. **Isolate phase state.** Give each phase its own history, stall, and findings files in loop scratch (for example suffixed by phase name), so a prior phase's cycle counts and clean-pass residue do not leak into the next phase's verdict.
2. **Run the inner cycle.** Drive this phase through `loop-run`'s cycle: delegate the maker (this phase's steps plus its design reference and a one to two line summary of what prior `done` phases built), gate, delegate the checker (pointed at this phase's findings path, told to check the phase against its design reference), score with `bash "$ENGINE/score.sh" <phase findings> | bash "$ENGINE/decide.sh"`, and obey the verdict.
3. **On PASS**, mark the phase `done` in the decomposition file and move to the next phase. **On AWAIT_USER, brake, or stall**, stop and hand to a human — the decomposition file records which phases are `done` so the run can resume later from the first phase that is not `done`.

## Design drift is a human gate

If the maker reports that the real implementation must diverge from the design, or the checker finds the code is right but the design is wrong, do not let the maker rewrite the design. Stop with AWAIT_USER and let a human re-decide the design; loop-build implements the design, it does not change it.

## Completion

When every phase is `done`, report the completed phases, the cycles each took, any remaining minor findings, and a change summary. Do not commit or push — a human finishes the commit and PR. Offer to run `loop-lessons` to turn any mistakes the loop caught into knowledge-layer candidates.

## Boundaries

- All of `loop-run`'s boundaries apply. The orchestrator runs the loop; it does not write code, assign severity, or decide the verdict.
- Do not reuse fixed provider model names or Claude-only agent names in the loop logic.
