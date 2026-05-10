# AI-Ready Codebase Rubric (100 points)

Each category lists detection rules with point values. Total = 100.
Grade bands: 0–39 AI-blind, 40–59 AI-aware, 60–79 AI-enabled, 80–89 AI-maximalist, 90–100 Agentic-ready.

---

## 1. Navigation (15)

> Can an AI agent find the right module/file in 1–2 hops?

| Rule | Points |
|------|--------|
| Root `CLAUDE.md` (or `AGENTS.md`) exists | 3 |
| Root doc references at least 3 module-level docs / paths | 4 |
| Module-level docs exist for ≥50% of build-manifest modules | 5 |
| Module-level coverage ≥80% | +3 (max 5 in this row) |
| Index/MOC file exists (`docs/INDEX.md` preferred; `INDEX.md`, `wiki/index.md` accepted) | 3 |

## 2. Context Document Quality (20)

> Are the docs **concise, structured, and useful** rather than dump-style?

| Rule | Points |
|------|--------|
| Root `CLAUDE.md` ≤ 200 lines | 5 |
| Module docs average ≤ 50 lines | 5 |
| At least one doc has explicit "DO NOT" / "절대" / "금지" / "MUST NOT" section | 5 |
| At least one doc has explicit usage / "when to use" guidance | 5 |

## 3. Tribal Knowledge & Anti-patterns (15)

> Is the implicit knowledge captured anywhere AI can read?

| Rule | Points |
|------|--------|
| `ANTIPATTERNS.md` (or `wiki/anti-patterns/`) exists | 5 |
| Architecture decisions captured (`ADR/`, `docs/decisions/`, `wiki/decisions/`) | 5 |
| Naming conventions documented in CLAUDE.md or NAMING.md | 5 |

## 4. Cross-module Dependency Tracking (15)

> Can AI trace change impact across modules?

| Rule | Points |
|------|--------|
| Module dependency map / diagram (`ARCHITECTURE.md`, `dependencies.md`) | 5 |
| Build manifests parseable for static dep graph (gradle/maven/npm/cargo) | 5 |
| Cross-module API contracts documented (OpenAPI, proto, contracts/) | 5 |

## 5. Verification Quality Gates (10)

> Are there mechanical checks that catch AI hallucinations?

| Rule | Points |
|------|--------|
| Pre-commit hooks present (`.husky/`, `.git/hooks/pre-commit`, lefthook, etc.) | 3 |
| CI config present and references tests | 3 |
| Test convention documented (location, naming, assertion style) | 4 |

## 6. Freshness Auto-Maintenance (10)

> Does the doc layer self-maintain?

| Rule | Points |
|------|--------|
| Any hook or scheduled job touches CLAUDE.md / docs (`.claude/hooks/`, `.claude/settings.json` Stop hook, cron) | 5 |
| CLAUDE.md update protocol documented (e.g., "갱신 트리거" section, "Maintenance" section) | 5 |

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

---

## Scoring Notes

- **Half-credit when partial**: e.g. if module docs cover 60% of modules, score 5 + (60-50)/30 * 3 ≈ 6 points (rounded down).
- **Evidence required**: every awarded point must reference a file path or measurement that can be re-verified next run.
- **Don't count root README** as an AI-ready doc unless it's structured for agents (has explicit "for AI" / "agent guidelines" section).
- **One source per rule**: if `wiki/decisions/` has 12 ADRs, that still scores 5 points for rule 3.2, not 60.
- **Self-output excluded**: `.ai-ready/` (the audit's own output directory) is excluded from scans. Module-CLAUDE.md scaffolds in `.ai-ready/scaffolds/` do NOT count toward coverage — they only count once moved to the actual module.
- **Thin-index recognition**: rule 1.2 also accepts `docs/*.md` and `wiki/*.md` references (not only module paths) so thin-index style root CLAUDE.md (lazy-load trigger tables) is properly credited.
