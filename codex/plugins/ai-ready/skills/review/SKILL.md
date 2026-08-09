---
name: review
description: "Run a bounded, evidence-based read-only review pass over a local change and repeat only when the user requests another pass. Use for AI-ready review, rubric-based local review, or a second independent review of the current diff; do not use for unattended build loops (use build)."
---

# AI-Ready Review

Perform a bounded review cycle without changing the repository. Use a project
rubric when present, but keep the result evidence-based and scope-limited.

## Workflow

1. Resolve the Git root and requested scope. Default to the current working tree; use a branch diff only when the working tree is clean or the user requests it.
2. Read project guidance and an optional repository-local `.loop/rubric.md`. Treat the rubric as review criteria, not execution permission.
3. Review correctness, compatibility, impact, performance, security, and intent only where the change makes each dimension relevant.
4. Return findings with severity, `path:line` evidence, impact, and a concrete suggestion. State coverage limits and tests not run.
5. Stop after one pass. A second pass requires an explicit user request or new changes to review.

## Boundaries

- Do not run an unattended maker/checker loop, write findings JSON, edit code, commit, fetch, or push.
- Do not use fixed provider models or provider-specific subagent names.
- Route actual implementation to a separately approved development workflow; route a local review request to `local-code-review` when that shared skill is available.
