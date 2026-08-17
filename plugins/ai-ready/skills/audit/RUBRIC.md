# AI-Ready Codebase Rubric (100 points)

Each category lists detection rules with point values. Total = 100.
Grade bands: 0–39 AI-blind, 40–59 AI-aware, 60–79 AI-enabled, 80–89 AI-maximalist, 90–100 Agentic-ready.

---

## Layout-aware scoring

This rubric scores **two layouts** with parallel rules. The audit script auto-detects layout from build manifests:

- **Multi-module**: ≥1 build manifest in non-root directories (e.g. `core/build.gradle.kts`, `app/build.gradle.kts`).
- **Single-module**: build manifest only at repo root. Packages (directories under the base source path) are treated as **logical modules**, and a single `docs/PACKAGES.md` catalog substitutes for per-module `CLAUDE.md`.

Rules below show both forms where they differ.

## 1. Navigation (15)

> Can an AI agent find the right module/file in 1–2 hops?

| Rule | Points |
|------|--------|
| Root `CLAUDE.md` (or `AGENTS.md`) exists | 3 |
| (Multi) Root doc references at least 3 module-level docs / paths<br>(Single) Root doc references the package catalog or ≥3 package paths<br>(since v0.9.1) referenced paths must exist, and a referenced *file* must be non-stub — broken or stub-pointing links don't count and are listed in the note<br>(since v1.5.3) the catalog branch is held to the same bar: naming `docs/PACKAGES.md` in the root doc scores only if that file exists and clears the stub gate, otherwise the path branch decides | 4 |
| (Multi) Module-level CLAUDE.md coverage<br>(Single) Package catalog (`docs/PACKAGES.md` etc.) exists with ≥3 package sections | 5 |
| Index/MOC file exists (MOC = Map of Content, a single doc that links every other doc; `docs/INDEX.md` preferred; `INDEX.md`, `wiki/index.md` accepted) | 3 |

## 2. Context Document Quality (20)

> Are the docs **concise, structured, and useful** rather than dump-style?

| Rule | Points |
|------|--------|
| Root `CLAUDE.md` between 800 and 8,000 bytes (≤ 12,000 scores partial; < 800 scores partial as a stub). Since v1.5.3, when the root holds both `CLAUDE.md` and `AGENTS.md` each is banded separately and the **worse** score becomes the rule score, with both sizes kept as evidence | 5 |
| (Multi) Module docs average 10–50 lines<br>(Single) Package catalog 50–300 lines (not too short, not too bloated for lazy-load) | 5 |
| At least 3 lines of explicit "DO NOT" / "절대" / "금지" / "MUST NOT" guidance across non-stub docs. Since v0.9.3 full marks count only *specific* lines — a line must also carry a backtick code reference, a path, or a CamelCase/snake_case identifier, because counting bare keyword lines made writing "금지" three times the optimal strategy (measured). Vague-only guidance still scores partial (3/5) so identifier-free but real rules aren't zeroed | 5 |
| At least one non-stub doc has explicit usage / "when to use" guidance | 5 |

## 3. Tribal Knowledge & Anti-patterns (15)

> Is the implicit knowledge captured anywhere AI can read?

| Rule | Points |
|------|--------|
| `ANTIPATTERNS.md` (or `wiki/anti-patterns/`) exists | 5 |
| Architecture decisions captured (`ADR/`, `docs/decisions/`, `wiki/decisions/`; config `rubric.decision_records.dir_hints` adds dirs, e.g. a consolidated `docs/design/` that absorbs ADRs) | 5 |
| Naming conventions documented in CLAUDE.md or NAMING.md | 5 |

## 4. Cross-module Dependency Tracking (15)

> Can AI trace change impact across modules?

| Rule | Points |
|------|--------|
| Module dependency map / diagram (`ARCHITECTURE.md`, `dependencies.md`) | 5 |
| (Multi) Build manifests parseable for static dep graph (gradle/maven/npm/cargo)<br>(Single) Package catalog with ≥3 sections **AND** ≥60% of domain packages follow standard layout (`controller/ service/ domain/ repository/` — at least 3 of 4). The layout half is a JVM web convention: since v1.5.3 a non-JVM single-module repo (node/python/go/rust) earns the full 5 from the catalog alone, since the layout is reported as *not measured* there. A JVM repo whose packages carry no controller still caps at 4 — the layout is measurable in principle, just absent | 5 |
| Cross-module API contracts documented (OpenAPI, proto, contracts/; config `rubric.api_contracts.build_deps` accepts code-gen deps, e.g. springdoc/springfox that emit OpenAPI at runtime — since v0.9.1 the declared string must be ≥4 chars and appear on a *dependency-declaration line*, not anywhere in the manifest) | 5 |

> **Why the multi vs single asymmetry is intentional**: this rule rewards a *machine-extractable dependency graph*. In a multi-module repo, ≥2 build manifests (gradle/maven/npm/cargo) **already encode inter-module dependencies natively** — the manifest *is* the graph, so its presence is the signal and no extra structural check is needed. A single-module repo has no such graph, so the equivalent signal must come from *structural consistency across packages*: when domain packages share the same shape (1) AI adds a new domain by mimicking the pattern, and (2) explicit package boundaries leave less room for cyclic dependencies. Hence single-module requires catalog + ≥60% standard layout to earn the same 5 points the manifest grants automatically — same signal, measured where it actually lives.

## 5. Verification Quality Gates (10)

> Are there mechanical checks that catch AI hallucinations?

| Rule | Points |
|------|--------|
| Mechanical verification hook present — git pre-commit (`.husky/`, `.git/hooks/pre-commit`, lefthook) **or** project-level AI-agent hook (`.claude/settings.json` PostToolUse/PreToolUse/Stop running lint/test/format/check; doc-freshness hooks excluded). Since v0.9.1 a settings hook whose command points at repo-relative scripts that don't exist (`./gradlew` with no wrapper, a missing `.py`/`.sh`) scores partial (1/3) — a dead config is not a gate. PATH commands are not checked (execution env unknown) | 3 |
| CI config present and references tests | 3 |
| Test convention documented (location, naming, assertion style) | 4 |

> **Why count AI-agent hooks**: in an AI-coding workflow the code's entry point is the agent's edit, so a `.claude/settings.json` hook that runs ktlint/test right there is the same kind of mechanical guard a git pre-commit gives — it catches AI hallucinations before they land. Only **project-level** settings (committed to the repo) count; user-global `~/.claude` hooks don't, since a teammate or CI cloning the repo won't have them.

## 6. Freshness Auto-Maintenance (10)

> Does the doc layer self-maintain?

| Rule | Points |
|------|--------|
| Any hook or scheduled job touches CLAUDE.md / docs (`.claude/hooks/`, `.claude/settings.json` Stop hook, cron). Since v0.9.1 a settings freshness hook whose commands all point at missing repo-relative scripts scores partial (2/5) | 5 |
| CLAUDE.md update protocol documented (e.g., "갱신 트리거" section, "Maintenance" section) — since v0.9.1 the keyword must live in a non-stub doc, matching the two category-2 keyword rules | 5 |

## 7. Outcome Metrics (15)

> Is AI's effectiveness actually measured?

| Rule | Points |
|------|--------|
| Metrics doc / dashboard for AI usage (`metrics/`, `analytics/`, `.claude/metrics`) | 7 |
| PR review time, AI-PR merge rate, or token usage tracking exists | 8 |

**Partial credit (since v0.1.2)**: outcome metrics often live outside the repo (Notion, Confluence, Datadog, Grafana). The audit awards partial points (3/7 or 3/8) when:
- Root `README.md` / `CLAUDE.md` / `docs/INDEX.md` references an external dashboard URL (Notion, Atlassian, Datadog, Grafana, Metabase, Mixpanel, Redash, Looker, Tableau), **or**
- The same docs mention tracking keywords (`ccusage`, `token usage`, `PR review time`, `AI PR merge rate`, `주간 보고`, `AI 사용량`)

The full credit still requires an in-repo artifact so it can be re-verified next run.

> **Scope note (cost is not measured here)**: this category checks whether AI effectiveness / usage is *tracked at all* (an in-repo metrics doc, or a pointer to an external dashboard). It does **not** measure token/cache cost itself — there is no session-log parser or cache-hit scorer in this plugin. Per-session cost/cache analysis is a separate concern (e.g. `ccusage`, RTK `gain`); this rubric only rewards that such tracking *exists*. Don't expect a token/cache dashboard from `/ai-ready:audit`.

---

## Scoring Notes

- **Coverage-proportional credit**: module-doc coverage scores `round(coverage_ratio × 5)`, capped at the rule max of 5 — e.g. 60% coverage → `round(0.6 × 5)` = 3 points. The score is proportional to coverage and never exceeds the rule max (no bonus above max). (This matches `audit.py`'s "Module-level CLAUDE.md coverage" rule; the earlier "60% → 6" example was impossible since 5 is the cap. Since v0.9.0 stub module docs are excluded from the covered count.)
- **Minimum-content gate (widened in v0.9.0, hardened in v0.9.1)**: existence-based rules require the file to carry actual content — **≥ 400 bytes AND ≥ 8 non-blank lines**, both conditions, since either one alone is trivially gamed (one very long line, or many one-character lines). An empty / stub file scores partial (2/5, 2/4, or 1/3) with a note — presence alone is not enough. The gate now covers ANTIPATTERNS, NAMING, ARCHITECTURE, TESTING, COMMANDS, the index/MOC file, ADR directories, API-contract files, per-module CLAUDE.md coverage, the two category-2 keyword rules, and (since v0.9.1) root-doc path references, the update-protocol keyword rule, and settings-hook command targets (CI configs are exempt — a workflow's working directory is unknowable from the repo root, so checking its commands would produce false positives); before v0.9.0 the threshold was 3 non-blank lines and several of those rules bypassed the gate entirely, which let a repo of 21 three-line stubs score 100/100. v0.9.1 also closes two bypasses found by a second adversarial review: binary files no longer pass the gate (a NUL byte in the first 8 KB disqualifies — random bytes read with `errors="replace"` used to clear the line count), and the *directory* gate counts only text-doc extensions (`.md .txt .rst .adoc .yaml .yml .json .proto`), so a stray image next to stub ADRs no longer satisfies it. A domain glossary (`docs/glossary.md`, `GLOSSARY.md`) is also credited under "Naming conventions documented".
- **DO-NOT full marks require repo-specific pointers (v0.9.3)**: the DO-NOT staircase counts a guidance line toward full marks only if it also contains a backtick span, a path-like token, or a CamelCase/snake_case identifier (`SPECIFIC_GUIDE_PATTERNS`). Keyword farming ("금지 1 / 금지 2 / 금지 3" in a gate-passing doc) scored 5/5 before; now it caps at the 3/5 partial. Measured on two real repos before shipping: agent kept 50 of 92 counted lines and c8c-api kept 242 of 378 — both far above the 3-line bar, so real scores did not move; what fell out was section headings ("## 불변식 (DO NOT)") and vague prose. The "when to use" rule intentionally has no such staircase (repeating the phrase would be farmed the same way — one guide per doc is normal there).
- **Self-reported config credit is disclosed (v0.9.1)**: `.ai-ready/config.json` is written by the repo being scored, yet it feeds scoring (`dir_hints`, `doc_hints`, `build_deps`). Measured attack before the fix: a stub repo plus one aggressive config and a single 450-byte junk file climbed 52 → 63 and crossed a grade band. The report now prints a "config 자기신고 인정" summary line (rule count + points) whenever config-declared signals earned points, so a reviewer sees the self-reported share at a glance; every config-credited rule carries "config" in its note (that token is the marker — don't use it in other positive-score notes).
- **Partial-credit shape is intentional, not an oversight**: partial credit differs by rule *type* because the underlying signal differs, and this variety is the policy — do not collapse it into a single formula. Coverage-type rules (continuous signal, e.g. module-doc coverage) scale proportionally (`round(ratio × max)`). Existence-type rules (discrete signal, e.g. ANTIPATTERNS / NAMING / ARCHITECTURE / TESTING) give a fixed partial (2/5, 2/4) for a present-but-stub file. External-reference rules (cat 7 outcome metrics) give a fixed partial (3/7, 3/8) for an out-of-repo dashboard/keyword pointer, reserving full credit for an in-repo artifact. Collapsing these into one formula would erase the distinction between a continuous, a discrete, and an external-pointer signal.
- **Evidence required**: every awarded point must reference a file path or measurement that can be re-verified next run. `Rule.award` emits a stderr warning if points are granted with neither evidence nor a note (invariant guard).
- **Don't count root README** as an AI-ready doc unless it's structured for agents (has explicit "for AI" / "agent guidelines" section).
- **One source per rule**: if `wiki/decisions/` has 12 ADRs, that still scores 5 points for "Architecture decisions captured", not 60.
- **Self-output excluded**: `.ai-ready/` (the audit's own output directory) is excluded from scans. Module-CLAUDE.md scaffolds in `.ai-ready/scaffolds/` do NOT count toward coverage — they only count once moved to the actual module.
- **Thin-index recognition**: "Root doc references at least 3 module-level docs / paths" also accepts `docs/*.md` and `wiki/*.md` references (not only module paths) so thin-index style root CLAUDE.md (lazy-load trigger tables) is properly credited.
- **"Root doc references at least 3 module-level docs / paths" saturates at 3 references**: three valid module/doc paths already score the full 4 points, and further references add nothing. A long trigger table is therefore *not* rewarded by this rubric — rows beyond the third cost always-loaded context for zero score. Trim the table for readability, not for points.
- **Root size is measured in bytes, not lines (changed in v0.8.9)**: a Korean markdown root doc packs a whole table row or paragraph into one line, so line count stops tracking cost — a real 46-line root doc weighed 12,029 bytes (one bullet alone was 2,002 characters) and scored full marks under the old ≤200-line rule while it kept growing. Bytes weight Hangul 3:1 against ASCII, which is closer to token share. **Score continuity note**: repos that passed the line rule may now score lower on the root-size rule; that is the intended correction, so treat the v0.8.9 boundary as a break in the trend line rather than a regression. v0.9.0 adds the 800-byte floor and widens the stub gate, which is a second deliberate break — an existing score may drop again at that boundary.
- **A root `CLAUDE.md` + `AGENTS.md` pair is two always-loaded costs, not one (v1.5.3)**: both files are banded and the worse band becomes the rule score. Summing them would be wrong for the common case where one file mirrors the other — that counts the same content twice — and picking one file was worse still: before v1.5.3 the scan collected root docs in `readdir` order, so a 20 KB `CLAUDE.md` next to a 2 KB `AGENTS.md` scored 0 or 5 depending on the filesystem. A Claude session loads only `CLAUDE.md` and a Codex session only `AGENTS.md`, so each session pays for its own file and the rule reports the worse of the two sessions. File collection is now name-sorted, which also makes every other "first root doc" rule deterministic.
