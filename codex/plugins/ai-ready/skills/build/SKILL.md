---
name: build
description: "Implement a settled design unattended: decompose it into phases, take one human approval, then drive each phase to PASS with a maker/checker loop where the Codex session orchestrates and a deterministic shell engine makes the verdict. Checker lenses split by axis and review in parallel without seeing each other, and their results are merged by count so a dead axis stops the run instead of passing. Use for AI-ready build, unattended multi-phase build-out from a design or spec, or converging a single change (a one-phase decomposition); not for a one-shot read-only review (use review)."
---

# AI-Ready Build

Build a settled design out without a human per step. The Codex session is the **orchestrator**: it decomposes the design into phases, drives each phase to PASS with the maker/checker cycle below, and advances. It writes no code itself and makes no verdict itself — the deterministic engine does. This mirrors how the same loop runs on Claude: a model orchestrator plus a shell that owns the verdict.

**Converging a single change is this skill too** — that is a decomposition with one phase. It used to be a separate skill, and the only thing that separated it was maker lifetime, which is now the same on both sides (a fresh maker every cycle). Keeping them apart also left the pre-flight spec check on one side only, so the other side was a way around that gate; a check with a bypass beside it is a recommendation, not a check.

## Invariants (do not break)

1. **Maker and checker are separate subagents, and both are spawned fresh every cycle.** The orchestrator never implements and never reviews; it spawns, runs the shell, reads the verdict, and branches. A maker that survives ten cycles carries every file it read, every edit, and every build output it looked at. What the next cycle actually needs is not that conversation: what was already attempted is in the working tree, how far the phase got is in the decomposition file's step statuses, and how long a problem has persisted comes from the repeat markers described in the cycle below.
2. **The checker is several lenses that do not know about each other, and their results are merged by count.** One reviewer walking six dimensions splits its search budget across them and lets its first judgement pull the rest. Each lens sees only its own axis and writes only its own file. Counting the results is the point: when a lens dies the surviving files still look well-formed, so without a count that axis passes having never been reviewed.
3. **The shell engine assigns severity and the verdict, not the model.** The checker only classifies findings; `_loop-engine` scores them. Never declare PASS or RETRY yourself — report exactly what the engine prints.
4. **The gate runs before the checker, and the brake before either.** Build and test must pass before a review cycle; a broken gate goes straight back to the maker. Check the iteration and time brake at the top of every cycle.
5. **Irreversible areas stop the loop.** Anything touching production data DML/DDL, money, authorization, mass sends, or deletion is `AWAIT_USER` — stop and hand to a human.
6. **The findings file is the recovery path.** A delegated subagent's output does not surface in the orchestrator's event stream, so each checker lens writes its findings JSON to a file and the orchestrator reads those files, never the subagents' chat text.
7. **The decomposition is approved once, before anything runs unattended.** If the design cannot be split into self-contained steps, do not start.

## Setup

1. Resolve the Git root of the target change and the compare base (default `origin/main`; fall back to the repository's default branch). Verify the base ref actually resolves — a mis-resolved base leaves an empty diff, and an empty diff reviewed clean is a false PASS.
2. Resolve the engine path once, before doing anything else. The engine ships at `_loop-engine/` under this plugin (two directories up from this skill's directory). Capture it as an absolute path, for example `ENGINE="$(cd "<this skill dir>/../../_loop-engine" && pwd)"`, so it stays valid after you change into the target repository.
3. Create a scratch directory for loop state outside version control (for example `.loop/run/` in the target repo, git-ignored). Everything below — the decomposition, per-phase history and stall state, per-lens findings, the gate queue — lives there.
4. Read the maker, checker, and spec-checker role contracts from `references/maker-role.md`, `references/checker-role.md`, and `references/spec-checker-role.md` in this skill directory — you will pass their text inline when delegating.

## Start gate (the one human approval)

Unattended execution starts only after the decomposition is approved once.

1. Read the design or spec. Decompose it into phases, each a list of self-contained steps. A good step is self-contained, one layer, specified to a signature, and verifiable by a runnable command (build, test, lint). A phase goal must also be **enumerable** — "these five defects in these files", not "make X better", which has no end: closing one item just makes the checker find the next, and because the grade rises and falls, stall detection never fires either.
2. Write the decomposition to loop scratch (for example `.loop/run/phases.json`), with each phase and step carrying a status of `pending`, `in_progress`, `done`, or `blocked`, and a design reference. **Progress lives in this file**, not in checkmarks written back into the design document. A single change is a one-phase file — the human does not write the JSON, you transcribe what the conversation settled and they approve it.
3. **Give the decomposition the three fields an unattended run needs, and refuse to start without them.** What separates a phase that finishes unattended from one that needs a human mid-run is the spec, not the schedule — a phase whose goal was "make the thing actually locked" took six cycles and one human interruption, while a phase whose goal was written as six named mutations took four and needed nobody. So each phase carries `exit_criteria`: a non-empty array where **each item says what turns red when it is reverted** ("deleting the inertia branch fails that check"). Prose like "make X better" is not an item. Each phase also carries `irreversible`: `false` when nothing in it touches production data DML/DDL, money, authorization, mass sends, or deletion, or a string naming the area when it does. And the file carries a top-level `tiebreaks`: an ordered list of trade-offs that measurement cannot settle ("locking it down comes before matching the original's call convention"), because without them the orchestrator stalls at the first such fork and calls a human anyway. **There is no other mode to fall back to** — if a field is missing, fix the decomposition and come back.
4. **Run the spec check before asking for approval.** Presence is all a machine can verify; whether those items are usable is a separate question. Spawn one subagent with the spec-checker role contract from `references/spec-checker-role.md`, pointed at both the design document and the decomposition file, with an output path such as `.loop/run/spec-gaps.json`. Show its `gaps` on the same screen as the approval request, so the decisions it surfaced get answered while a human is still there, and fold the answers back into the design document or the decomposition before the first cycle. **This is a warning layer, not a gate** — it never blocks the start. Which gaps are load-bearing differs per project, and a machine that blocks on them only teaches people to route around it. If the check itself fails to produce a file, say so and start anyway.
5. Get human approval of the decomposition. After approval the human steps away and the orchestrator runs autonomously until PASS, brake, or AWAIT_USER.

## Phase loop

For each phase in order:

1. **Isolate phase state.** Give each phase its own history, stall, gate-failure counter, and per-lens findings files in loop scratch (suffix them by phase name), so a prior phase's cycle counts and clean-pass residue do not leak into the next phase's verdict.
2. **Re-check the three fields before consuming the file.** The start gate ran once in front of a human, but the phase loop is also entered on resume, and the decomposition can be hand-edited in between. Re-check `exit_criteria`, `irreversible`, and `tiebreaks`, and name which one is missing.
3. **Run the cycle below** until PASS, brake, stall, or AWAIT_USER.
4. **On PASS**, mark the phase `done` in the decomposition file and move to the next phase. **On AWAIT_USER, brake, or stall**, stop and hand to a human — the decomposition file records which phases are `done`, so the run resumes later from the first phase that is not `done`. Phases already `done` are not rebuilt.

The per-phase iteration budget defaults to 5 (a caller-supplied number is clamped at a hard ceiling of 10), and the time budget is per phase, so a longer decomposition does not starve its later phases.

## Cycle

Repeat until PASS, brake, or AWAIT_USER:

1. **Delegate the maker.** Spawn a **new** subagent whose task is the maker role contract plus exactly these, and nothing else. Do not implement it yourself, and do not continue a maker from a previous cycle.
   - This phase's steps (goal, layer, signature, and the AC command that verifies each) and its design reference. One or two lines on what prior `done` phases built, for context.
   - **One** input path for this cycle: the gate queue if it is non-empty, otherwise the scored findings file. Never both — see the precedence note under the gate.
   - **Repeat markers.** Which findings have persisted, and for how many cycles. The engine's stall state carries only a run-level `no_progress` counter, so derive per-finding repeats from this phase's history file: `jq -rs '[ .[] | .iteration as $it | (.findings // [])[] | {k: "\(.kind)@\(.location)", it: $it} ] | group_by(.k) | map({key: .[0].k, cycles: (map(.it) | unique)}) | map(select(.cycles | length > 1)) | .[] | "\(.cycles | length) cycles: \(.key)"' <phase history file>`. This is the only memory that crosses cycles, so a fresh maker knows the previous approach failed without being told what it was.
   - The convention doc paths, and the build command so the maker can compile-check its own work.

   Pass paths, not contents. A lint gate can produce thousands of items and the orchestrator must not hold them.
2. **Gate.** Run the project build and test commands with their combined output redirected to a file, not into your context. Compile first; if it fails, do not run the tests. On failure turn that file into a work queue — `python3 "$ENGINE/gate_parse.py" --stage <build|test|lint> <output file> >> <loop dir>/gate-queue.jsonl` — which emits one JSON item per line carrying `kind`, `file`, `line_number`, `message`, and the original `raw` line. Truncate the queue at the start of every gate run, because the gate re-runs each cycle and a leftover item makes the maker chase an error that is already fixed. Hand the queue to a maker subagent, repeat the gate, and do not proceed until it passes. Count gate failures toward the same iteration brake as scored cycles — a cycle that never reached the checker still burned a cycle.
   - The parser never emits an empty queue. With no recognised error format it keeps the output tail as a single `gate-output-unparsed` item, because an empty queue reads as a pass and that misreading is what the queue exists to prevent.
   - **A non-empty gate queue takes precedence over the findings file.** A failed gate means the checker never ran this cycle, so the findings file still holds the previous cycle's values. Fixing those first means chasing problems that no longer exist.
   - Work the queue in the order `compile-error`, `test-failure`, `lint-violation`. Test failures carry no information while compilation is broken, and lint violations do not affect behaviour.
   - Open only the `file` and `line_number` an item points at. `raw` is the fallback when the parser split a line wrongly; the full output stays in the file for reading around a specific item. Never pull it into the orchestrator's context wholesale.
   - **Before running the gate, verify the working tree actually changed.** A maker's report can be wrong; the tree cannot. If nothing changed, running the gate produces the same result and the checker the same findings, and the cycle is spent for nothing. Snapshot `HEAD` plus a checksum of the working tree's **content** before spawning the maker and compare after it returns: `git rev-parse HEAD` joined with a checksum over `git diff HEAD` and the contents of `git ls-files --others --exclude-standard`. Checksum the content, not `git status --porcelain` — porcelain prints a status letter and a path, so editing a file that was already modified leaves it byte-identical, and a maker editing the same file across cycles is the normal case rather than the exception. An unchanged tree is not a cycle, it is a stall signal — stop and hand to a human rather than looping.
   - **A maker that ends in `blocked` does not get replaced by another maker.** Hand its one-line reason to a human as `AWAIT_USER`. Routing an unfixable item back through more makers only burns cycles, and routing it through the checker instead loses the reason entirely — the checker sees only the diff and cannot know why the maker stopped.
3. **Delegate the checker lenses, in parallel, in one turn.** Spawn one subagent per lens, each with the checker role contract, and each told **its own lens name, its own dimensions, and its own output path**. The default set is three:

   | lens | dimensions | what it doubts |
   |---|---|---|
   | `contract` | compatibility · intent | is this different from what was promised |
   | `safety` | security · runtime | does it break or leak when it runs |
   | `quality` | convention · simplicity | is there a better form of this |

   What the three prompts share: the design document path with this phase's design reference and steps, **every `exit_criteria` item of this phase**, the compare base, the convention docs and knowledge-layer path (say "none" explicitly when empty), and the BASE and LOCAL rubric paths. Pass the same compare base string to all three — lenses that reviewed different diffs cannot be merged into one verdict.

   Pass `exit_criteria` because otherwise nobody measures it: the start gate only checked that the items exist, and PASS is `BLOCKER 0 AND CRITICAL 0`, which says nothing about this phase's completion. With the items in the prompt, a criterion that does not hold comes back as `intent-requirement-missing`.

   **Never put anything the maker reported into a checker prompt** (invariant 1), not even a one-line `ok`. Each lens writes `{"base": "<ref>", "reviewed": [ ... ], "findings": [ ... ]}` to its own path — `reviewed` lists the changed files it actually read. Do not review the diff yourself and do not write any findings file yourself.
4. **Merge by count, then score (deterministic).** Run exactly:

   ```
   bash "$ENGINE/merge_findings.sh" --expect 3 \
     "contract=<loop dir>/checker-<phase>-contract.json" \
     "safety=<loop dir>/checker-<phase>-safety.json" \
     "quality=<loop dir>/checker-<phase>-quality.json" > <phase findings>
   bash "$ENGINE/score.sh" <phase findings> | bash "$ENGINE/decide.sh"
   ```

   `--expect` is the count check, and it is why this step exists: a lens that died, wrote nothing, or reviewed a different base stops the run with exit 65 naming the lens, rather than letting the remaining two score a change whose third axis was never reviewed. **Check the exit status of both commands.** Exit 65 is not a verdict and there is nothing to obey — the common cause on the scoring side is a clean result whose `reviewed` list is empty, which the scorer cannot tell apart from a checker that never looked. Stop and hand to a human; do not treat an empty result as a pass.
5. **Append one history line per cycle** (iteration, verdict, findings) to this phase's history file, then run `stall.sh` on the verdict and `kindstreak.sh` on the history. `STALLED` or `REGRESS_ESCALATE` means the code is not getting fixed; `REPEATED_KIND` means one kind of finding has dominated the phase for several cycles, which is a signal about the **phase goal**, not the code — ask the human whether that goal is enumerable and where it ends.
6. **Obey the verdict.**
   - `PASS`: this phase is done. Record it and move on.
   - `RETRY` or `RETRY_SOFT`: **spawn a new maker** per cycle step 1, with the scored findings file as its one input, then return to the gate. Never resume the maker that just ran — that is the accumulation invariant 1 exists to prevent. A `simplicity` finding lands here often; if the loop stalls on one, offer the human the option of passing with that MAJOR on the record.
   - `AWAIT_USER`: stop and hand to a human — do not continue.
7. **Brake.** Stop and report if scored cycles plus gate failures reach the allowed iterations (default 5, hard ceiling 10) or the elapsed budget is exhausted. Never loop unbounded.

## Design drift is a human gate

If the maker reports that the real implementation must diverge from the design, or a checker lens finds the code is right but the design is wrong, do not let the maker rewrite the design. Stop with AWAIT_USER and let a human re-decide it. This skill implements the design; it does not change it.

## Model and effort

Model and reasoning effort are set at the session level, not hardcoded in this skill. Delegated maker and checker subagents inherit the session's model and effort — the checker inheriting the session matches the Claude loop, and effort inheritance to subagents is confirmed (a session launched at `high` runs its delegates at `high`).

- **Interactive**: the model and effort chosen in the Codex session are what the loop uses. No extra setup.
- **Headless / automated**: launch through `loop-launch.sh`, which reads `loop-profile.env` (`LOOP_MODEL`, `LOOP_EFFORT`) and starts the session with `-m <model> -c model_reasoning_effort=<effort>`. Change the model or effort in that one profile file — never in this skill.
- **Effort values** follow the neutral ladder (`minimal`, `low`, `medium`, `high`, `xhigh`, `max`); Codex accepts these tokens directly, and `xhigh` is model-dependent. See the shared effort ladder for the cross-host contract.
- This is a **uniform profile**: maker and checker lenses share the session's model and effort. Running them on different tiers (a cheaper maker, a more thorough checker) needs registered per-agent pins and an explicit launch, which is a later step.

## Completion

When every phase is `done`, report the completed phases, the cycles each took, any remaining minor findings, and a change summary taken from `git diff <base>...HEAD --stat` and `git status --short` — no maker knows the whole run, and the tree is the only record that does. Offer to run `lessons` to turn the mistakes the loop caught into knowledge-layer candidates; history is per phase, so run `lessons.sh` per history file and merge. Discard the loop scratch only after that, and only when the run is really closed — a run stopped at AWAIT_USER, stall, or brake needs its state to resume.

## Boundaries

- Do not commit, fetch, or push — the loop stops at an uncommitted working tree; a human finishes the commit and PR.
- Do not reuse fixed provider model names or Claude-only agent names in the loop logic.
- Score with the shell engine only; do not re-implement severity or the verdict in the model.
- Deciding *what* to build is out of scope. This is the execution layer, and an undecided question is what the start gate sends back.
