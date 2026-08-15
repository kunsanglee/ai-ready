---
name: spec
description: "Derive a spec the unattended loop can run on. Enumerate the calls the current draft does not answer, then close each one by disposition: found in code (cite the path), a tuning value (set a default and move on), or a genuine guess (ask the human). The exit condition is not a rubric pass but zero unresolved, because a writer told to \"fill in the gaps\" invents answers and the next check waves them through, converging on a hallucination while every gate stays green. Use before /build when nobody has decided what done means, or when a draft reads complete but the loop would still have to guess. Derivation runs in the main session because a subagent cannot ask a human."
---

# AI-Ready Spec

Derive the definition the loop will run on. `build` assumes a spec exists and decomposes it; this skill produces that spec by closing the decisions nobody has made yet.

**What separates a phase that finishes unattended from one that needs a human is the spec, not the gate.** Two phases in the same repository on the same day: one was given "make the thing you claimed to build actually lock" and took six cycles plus a human intervention, because the goal could not be listed as items so closing one only made the checker find the next. The other was given six mutations written out in advance ("delete the inertia branch and that check goes red") and took four cycles with no human at all. The spec was the only difference.

## Invariants (do not break)

1. **Never invent an answer.** The holes in a spec live mostly in a human's head. Tell a writer to "fill in the details" and it produces something plausible; the next check reads it as settled and passes it. Every gate stays green while the spec drifts away from what anyone wanted. So every decision carries a disposition *and* its evidence, and a disposition without evidence is rejected by the check below rather than argued with.
2. **The exit condition is zero unresolved, not a passing grade.** No model decides "this is good enough". The run ends when the ledger has no `open` entries and every `asked` entry carries a human answer, and that is counted by a shell.
3. **Derivation and questioning happen in this session.** A subagent cannot address the human, so the round trip does not exist for it. Delegate the enumeration to the spec-checker role; keep disposition, questions, and write-back here.
4. **Do not ask about tuning values.** A number tuned later by feel inside a settled mechanism (timeout, page size, retry count) gets a default and a note. Only an unsettled *mechanism* reaches the human. How many retries is a tuning value; whether the operation is safe to retry at all is a decision.
5. **Deferring is allowed; deferring silently is not.** If the human says "later", the entry becomes `deferred` and the output document carries it in an open-questions section. What this skill exists to prevent is exactly a maker filling that hole with a guess downstream, so the fact that it is being handed over travels with the document.

## What you produce

Two files under `.loop/spec/<slug>/`:

- `decisions.json` — the ledger. Each entry is `{id, lens, subject, question, what_diverges, disposition, evidence?, answer?, note?}`. `disposition` is one of `open`, `resolved-from-code`, `default`, `asked`, `deferred`.
- `spec.md` — the document `build` will consume. Sections: goal, non-goals, decisions (with evidence), exit criteria, failure floor, open questions.

The exit criteria section becomes `exit_criteria` in the decomposition, the non-goals section feeds `non_goals`, and the open questions feed the `irreversible` and `tiebreaks` judgements. Writing those sections loosely means `build`'s pre-flight check stops you there instead. The non-goals section had nowhere to land in `build` for a long time; 1.4.0 added `non_goals` and connected it.

The grain differs, though: these sections are one per document, and `build`'s fields are one per phase. So they get split on the way over. This document's non-goals are what **the whole job** will not build, so they go into every phase's `non_goals`; on top of that each phase adds the surfaces **only it** is not looking at, which a later phase will. That last part is not in this document — it is settled when the work is decomposed. Copying the section verbatim into every phase produces no per-phase narrowing at all, which leaves `non_goals` decorative. `exit_criteria` splits the same way.

## Procedure

1. **Set up.** Create `.loop/spec/<slug>/` keyed by branch so two worktrees do not overwrite one ledger, and start an empty ledger if none exists — a run interrupted mid-questioning must not re-ask what was already answered. Detect the project's convention docs and knowledge layer; you pass those paths to the checker so it can tell "undecided" from "already decided elsewhere". Confirm the spec-checker role contract is readable before going further, so a broken install is distinguished from a stale session later.

2. **Gather the starting point.** Three sources: what the human already said in this conversation, the draft document if one was given, and the existing code plus convention docs. Write them into `spec.md` as a first draft. It may be thin; later rounds fill it.

3. **Enumerate.** Delegate to a subagent carrying the spec-checker role contract from `../build/references/spec-checker-role.md`, pointed at the draft, with an output path and **the subjects already disposed of in the ledger**. That last input is what keeps round two from re-asking round one's questions, which is the fastest way to make a human stop using this.

4. **Dispose.** Every gap becomes a ledger entry. Found in the code or convention docs → `resolved-from-code` with the path you read. A tuning value → `default` with the value. A genuine guess → `asked`. Each disposition demands its own evidence field, and the check in step 6 rejects the entry if it is empty.

5. **Ask only the guesses, in one screen.** Present the `asked` items together, each with its alternatives spelled out, and report the ones you settled without asking separately so the human can object. One question at a time reads better in live chat but strands a background run waiting on several separate answers. Record the human's answer verbatim; smoothing it means the next round reasons from a sentence they did not say.

6. **Check, then loop or finish.** A deterministic check counts three things: entries still unresolved, entries closed without evidence, and dispositions outside the vocabulary. Unresolved sends you back to step 3 (an answer opening a new decision is normal). Closed-without-evidence and bad vocabulary are input errors a human must fix — keep the two exits distinct, or "go around again" and "you wrote something wrong" become the same signal. **Cap the rounds at three**; past that, show what remains and ask once whether to hand it over as deferred, because an answer opening a new decision means this can otherwise run forever and the human tires first.

7. **Hand off.** Report the document path and call `build` with it.

## Not this skill's job

- **Writing the spec for the human.** Enumerate and dispose; the moment you fill in a decision nobody made, invariant 1 is gone.
- **Judging whether the spec is good.** No grade, no score. Which decisions are load-bearing differs per project, and a machine verdict there only teaches people to route around it.
- **Phase decomposition.** That is `build`. Splitting here too leaves two places holding different splits.
- **Editing code.** This layer writes documents and the ledger.
