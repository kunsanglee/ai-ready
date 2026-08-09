---
name: loop-build
description: "Build out a settled design across multiple phases with an unattended loop, where the Codex session orchestrates maker/checker subagents and a deterministic shell engine makes each verdict. Use for AI-ready loop build, multi-phase unattended build-out from a design or spec, or driving a decomposed plan to completion; not for a single change (use loop-run) or a one-shot review (use loop-review)."
---

# AI-Ready Loop Build

Build a settled design out across several phases without a human in the loop per step. The Codex session is the **orchestrator**: it decomposes the design into phases, drives each phase to PASS with the same maker/checker cycle as `loop-run`, and advances. It writes no code itself and makes no verdict itself — the deterministic engine does.

This is the multi-phase wrapper around the `loop-run` cycle. Read `loop-run`'s SKILL first: its invariants, setup, cycle, model note, and boundaries apply here, with the two exceptions below. This skill adds phase decomposition and a phase loop around that cycle.

**Exception 1 — the maker's lifetime is the phase, not the cycle.** `loop-run` invariant 1 spawns a fresh maker every cycle. Here the unit is the phase: one maker implements a phase's steps and stays for that phase's retry cycles, because a phase is a multi-step build where why a file was edited a certain way spans cycles. A new phase always gets a new maker, so nothing accumulates past a phase boundary. If the host cannot resume a delegated subagent, spawn a fresh maker per cycle instead and give it the phase's `design_ref` plus this cycle's one input file — the design reference and the working tree hold what a resumed maker would have remembered.

**Exception 2 — the task definition file is the design doc plus the decomposition.** `loop-run` setup step 5 requires a task definition file and writes a brief when only chat has one. Here that requirement is already met by the design or spec being decomposed plus `phases.json`, so no brief is written, and the one human gate is the decomposition approval below rather than a brief confirmation.

## Start gate (the one human approval)

Unattended execution starts only after phase decomposition is approved once.

1. Read the design or spec. Decompose it into phases, each a list of self-contained steps. A good step is self-contained, one layer, specified to a signature, and verifiable by a runnable command (build, test, lint). If the design cannot be split into such steps, stop and return to the human — do not start unattended.
2. Write the decomposition to loop scratch (for example `.loop/run/phases.json`), with each phase and step carrying a status of `pending`, `in_progress`, `done`, or `blocked`, and a design reference.
3. **Give the decomposition the three fields an unattended run needs, and refuse to start without them.** What separates a phase that finishes unattended from one that needs a human mid-run is the spec, not the schedule — a phase whose goal was "make the thing actually locked" took six cycles and one human interruption because closing one item just made the checker find the next, while a phase whose goal was written as six named mutations took four and needed nobody. So each phase carries `exit_criteria`: a non-empty array where **each item says what turns red when it is reverted** ("deleting the inertia branch fails that check"). Prose like "make X better" is not an item — it has no end. Each phase also carries `irreversible`: `false` when nothing in it touches production data DML/DDL, money, authorization, mass sends, or deletion, or a string naming the area when it does. And the file carries a top-level `tiebreaks`: an ordered list of trade-offs that measurement cannot settle ("locking it down comes before matching the original's call convention"), because without them the orchestrator stalls at the first such fork and calls a human anyway. **There is no other mode to fall back to** — if a field is missing, fix the decomposition and come back. A check with a bypass beside it is not a check.
4. **Run the spec check before asking for approval.** Presence is all a machine can verify; whether those items are usable is a separate question. Spawn one subagent with the spec-checker role contract from `loop-run`'s `references/spec-checker-role.md`, pointed at both the design document and the decomposition file, with an output path such as `.loop/run/spec-gaps.json`. Show its `gaps` together with the decomposition when you ask for approval. It is a warning layer and never blocks the start.
5. Get human approval of the decomposition. After approval the human steps away and the orchestrator runs autonomously until PASS, brake, or AWAIT_USER.

## Phase loop

Resolve the engine path once as in `loop-run` setup. Then for each phase in order:

1. **Isolate phase state.** Give each phase its own history, stall, and findings files in loop scratch (for example suffixed by phase name), so a prior phase's cycle counts and clean-pass residue do not leak into the next phase's verdict.
2. **Run the inner cycle.** Drive this phase through `loop-run`'s cycle: delegate the maker (this phase's steps plus its design reference and a one to two line summary of what prior `done` phases built), gate, delegate the checker (pointed at this phase's findings path, told to check the phase against its design reference), score with `bash "$ENGINE/score.sh" <phase findings> | bash "$ENGINE/decide.sh"`, and obey the verdict.
   - The maker contract ends at `ok` or `blocked: <one line>` by default. When a phase passes, ask that maker explicitly for the one to two line summary the next phase's maker needs — this is the one place a loop-build orchestrator wants more than a signal, and the contract allows up to 5 lines when asked.
3. **On PASS**, mark the phase `done` in the decomposition file and move to the next phase. **On AWAIT_USER, brake, or stall**, stop and hand to a human — the decomposition file records which phases are `done` so the run can resume later from the first phase that is not `done`.

## Design drift is a human gate

If the maker reports that the real implementation must diverge from the design, or the checker finds the code is right but the design is wrong, do not let the maker rewrite the design. Stop with AWAIT_USER and let a human re-decide the design; loop-build implements the design, it does not change it.

## Completion

When every phase is `done`, report the completed phases, the cycles each took, any remaining minor findings, and a change summary. Do not commit or push — a human finishes the commit and PR. Offer to run `loop-lessons` to turn any mistakes the loop caught into knowledge-layer candidates.

## Boundaries

- All of `loop-run`'s boundaries apply. The orchestrator runs the loop; it does not write code, assign severity, or decide the verdict.
- Do not reuse fixed provider model names or Claude-only agent names in the loop logic.
