---
name: audit
description: Score a codebase for AI-readiness against a 7-category 100-point rubric and generate a markdown report, an HTML dashboard, module-level CLAUDE.md scaffolds, and an ANTIPATTERNS.md seed extracted from git history. Use this skill whenever the user wants to assess how well their codebase is set up for AI agents (Claude/Codex/Gemini), generate per-module CLAUDE.md files, extract anti-patterns, or build a navigation map for a large codebase — even if they don't explicitly say the word "audit". Trigger on phrases like "ai-ready audit", "AI 준비도", "코드베이스 감사", "score my codebase for AI agents", "generate module CLAUDE.md", "anti-patterns from git history", "AI 친화 코드베이스", "make this repo navigable for Claude", or "we have no map for AI".
---

# AI-Ready Codebase Audit

Turns a codebase into an AI-navigable one. Inspired by Meta's internal "AI had no map" → "59 module CLAUDE.md files" approach (Meta Engineering blog, 2026).

## What This Skill Produces

For a target codebase you point it at, this skill creates an `.ai-ready/` directory containing:

1. **`audit.json`** — raw scores (per-category, per-rule, evidence). Includes `single_module_mode: bool` + `package_catalog: path|null` so consumers know which layout was scored.
2. **`audit-report.md`** — human-readable report with ROI-prioritized action list
3. **`README.md`** — auto-generated guide for `.ai-ready/` consumers (artifact map, plugin install, score interpretation, re-run instructions)
4. **`dashboard.html`** — self-contained HTML dashboard with score gauge, category bars, and trend sparkline (open in browser)
5. **`history/{timestamp}.json`** — every run is archived here so the dashboard can render a trend line. Do not delete.
6. **`scaffolds/...`** — drafts for the missing docs (see "Layout-aware scaffolds" below)
7. **`scaffolds/ANTIPATTERNS.md`** — seed anti-patterns extracted from git history (clustered hotspots)
8. **`hooks/freshness_check.sh`** (+ `hooks/freshness_check.py`) — copied from the plugin so a project's `.claude/settings.json` Stop hook can reference it as `$CLAUDE_PROJECT_DIR/.ai-ready/hooks/freshness_check.sh`; the `.py` runner is copied alongside so the hook works without `CLAUDE_PLUGIN_ROOT`

### Layout-aware scaffolds

The audit auto-detects the layout from build manifests and switches scoring + scaffold output:

| Layout | Detection | Module concept | Scaffold output | Module-level doc |
|---|---|---|---|---|
| **Multi-module** | Build manifest in ≥1 non-root directory | Each manifest-bearing dir = a module | `scaffolds/<module>/CLAUDE.md` per hot module | Per-module `CLAUDE.md` |
| **Single-module** | Build manifest only at repo root | Each direct child of the **source root** = a logical module. Where the source root sits is stack-specific — see "Stack adapters" below | `scaffolds/PACKAGES.md` (one catalog for all packages) | Single `docs/PACKAGES.md` catalog |

> Single-module reasoning: spawning N package-level `CLAUDE.md` files for a single Gradle/Maven/npm module fragments context and adds maintenance burden. A single `docs/PACKAGES.md` catalog (lazy-loaded from root `CLAUDE.md`) covers the same ground while keeping the doc surface small. The audit rubric scores them on parallel rules — see `RUBRIC.md` "Layout-aware scoring".

### Stack adapters (`scripts/stacks.py`)

"Where do logical modules start?" has a different answer per language, so the answer lives in one adapter registry that both `audit.py` and `scaffold.py` consume. It used to be hardcoded to JVM in each of them separately — two copies, so adding a stack meant editing two files and fixing only one made scoring and scaffolding look at different directories.

| Stack | Detected by | Source root |
|---|---|---|
| `jvm` | `src/main/kotlin` or `src/main/java` | dir holding `*Application.kt|java`; if the project has none (a library), the package chain is walked down to where it branches |
| `node` | root `package.json` | first of `src/`, `lib/`, `app/` |
| `python` | `pyproject.toml` / `setup.py` / `setup.cfg` | the distribution package under `src/`, or the single root package with `__init__.py` |
| `go` | `go.mod` | `internal/` or `pkg/`, else the module root |
| `rust` | `Cargo.toml` | `src/` |

Adapters are tried in that order, so a Gradle project carrying a frontend `package.json` still resolves as `jvm`.

**Adding a stack**: append one `(name, fn)` entry to `ADAPTERS` in `scripts/stacks.py`. The function answers one question — which directory's children are the logical modules — and returns `SourceLayout` or `None`. Call sites iterate the registry, so nothing else changes.

**An unknown stack fails loudly, it does not pass quietly.** `scaffold.py` exits `3` when no adapter matches and `4` when the source root holds no code, naming what it saw and where to add the adapter. It used to print a note and exit `0`, which made a run that produced nothing indistinguishable from a run that succeeded.

## Inputs You Need

- **Target codebase path** (absolute path). Example: `/Users/me/projects/my-api`
- **(Optional)** Top N modules to scaffold (default: 5)
- **(Optional)** Lookback days for git anti-pattern extraction (default: 180)

## How To Run

The skill ships a baseline four-step run plus several optional action scripts (see "Additional Action Scripts" below). All scripts are stdlib-only — **no third-party dependencies**. Run the four baseline scripts in this order:

```bash
# **`$CLAUDE_PLUGIN_ROOT` does not exist in the Bash tool's shell** — it is substituted when the
# skill body is rendered, so it never reaches the child shell (measured). Using it here would make
# SKILL_DIR="/skills/audit", a path that silently does not exist. Paste the "Base directory for
# this skill" value printed at the top of this skill body instead — that directory *is* skills/audit.
SKILL_DIR="<paste the Base directory from the top of this skill body>"
[ -f "$SKILL_DIR/scripts/audit.py" ] || { echo "audit: scripts not found under $SKILL_DIR — check the base directory" >&2; exit 65; }
TARGET="<absolute path to target codebase>"
OUT="$TARGET/.ai-ready"
mkdir -p "$OUT"

# 1) Score the codebase
python3 "$SKILL_DIR/scripts/audit.py" --target "$TARGET" --out "$OUT"

# 2) Generate scaffolds (auto-branches by layout):
#    - Multi-module → per-module CLAUDE.md drafts (top N hot modules)
#    - Single-module → docs/PACKAGES.md catalog draft (one file, all packages)
python3 "$SKILL_DIR/scripts/scaffold.py" --target "$TARGET" --out "$OUT/scaffolds" --top 5

# 3) Extract anti-patterns from git history (last 180 days)
python3 "$SKILL_DIR/scripts/extract_antipatterns.py" --target "$TARGET" --out "$OUT/scaffolds/ANTIPATTERNS.md" --days 180

# 4) Render HTML dashboard from audit.json
python3 "$SKILL_DIR/scripts/dashboard.py" --audit "$OUT/audit.json" --out "$OUT/dashboard.html"
```

After it finishes, open `$OUT/dashboard.html` to see the score, then review `$OUT/audit-report.md` for the ROI action list.

## Additional Action Scripts

To raise the score by executing ROI actions directly, use the scripts below. The companion `ai-ready:apply` skill invokes them automatically, but they also work standalone — useful when you want to apply only a single action.

| Script | ROI action it covers | What it does |
|--------|---------------------|--------------|
| `gen_index.py` | "Create docs/INDEX.md (preferred) / wiki/index.md" | Builds a single-line summary index from every CLAUDE.md / AGENTS.md found. **v0.2.0+**: if `<target>/.ai-ready/config.json` exists, switches to *frontmatter-driven grouping* — feature/module sub-groups + 한영 cross-reference + ADR supersedes graph. |
| `inject_module_map.py` | "Add module map to root CLAUDE.md" | Injects an auto-regenerable "## 모듈 맵" section into root CLAUDE.md (idempotent, marker-fenced). **v0.8.8+**: the per-module excerpt length comes from config `module_map.root_stub_limit` (default 10, unchanged); 0 keeps only the catalog link — the root doc is always-loaded and each module's summary already lives in its own CLAUDE.md, so the excerpt is duplicate context where enough paths are referenced elsewhere. Setting 0 prints a notice because audit's "root doc references 3+ module/doc paths" rule counts that listing in some repos. |
| `inject_lazy_load_index.py` | "Thin index pattern" | Injects a lazy-load trigger table into root CLAUDE.md, mapping triggers to `docs/*.md`. **v0.2.0+**: splits into `lazy-load:user-begin/user-end` (never overwritten) + `lazy-load:auto-begin/auto-end` (regenerated). Legacy single-marker / unmarked tables are migrated safely. Config's `lazy_load_triggers.detect` adds project-specific rules; `override_hardcoded` removes built-in rules (e.g., when migrating `docs/decisions` → `docs/adr`). **v0.8.7+**: a detected row is dropped automatically when the user section already links the same document (trailing slashes normalized) — the root doc is always-loaded, so listing one doc in both tables costs the duplicate every session; if every detected doc is already covered the auto block renders a one-line note instead of an empty table. |
| `extract_section.py --kind testing` | "Split TESTING.md" | Lifts the testing section out of CLAUDE.md into a dedicated file |
| `extract_section.py --kind naming` | "Split NAMING.md" | Lifts the naming/conventions section out into NAMING.md |
| `install_hook.py` | "Install freshness Stop hook" | Adds the hook to `.claude/settings.json` (idempotent) |
| `gen_arch_diagram.py` | "Generate ARCHITECTURE.md with Mermaid" | Parses gradle / npm dependencies and emits a Mermaid graph |
| `scaffold.py` | "Module CLAUDE.md coverage" | Drafts CLAUDE.md for the top-N hot modules — fills module summary, dependency list, and hot-file list automatically |
| `extract_antipatterns.py` | "Seed ANTIPATTERNS.md" | Clusters `fix` / `hotfix` / `revert` (and Korean equivalents) commits by keyword and module hotspot |

Scripts that modify existing files (`inject_module_map.py`, `inject_lazy_load_index.py`, `install_hook.py`) are idempotent. `inject_module_map.py` and `inject_lazy_load_index.py` expose a `--dry-run` option so changes can be previewed first; `install_hook.py` has no `--dry-run` (it offers `--uninstall` to remove the hook instead).

**Overwrite guard.** Every script that writes a document (`gen_index`, `gen_arch_diagram`, `extract_section`, `inject_module_map`, `extract_antipatterns`) refuses to clobber a file that lacks the ai-ready generation signature — a document a human has taken over. It exits `3` and says so; `--force` overrides. This matters most for `extract_antipatterns`, whose output is *by design* a draft a human prunes and adopts: the convention is to point `--out` at `.ai-ready/scaffolds/`, but a convention is not a mechanism, and pointing it at an adopted `docs/ANTIPATTERNS.md` would otherwise replace curated entries with a git-history dump. The generated seed carries the signature itself, so re-running an audit over its own previous output stays fine.

**`--json` facts mode (v0.5.0+)**: the doc-touching scripts (`gen_index`, `gen_arch_diagram`, `extract_section`, `inject_module_map`, `inject_lazy_load_index`) accept `--json` to emit the gathered facts (doc list + summaries, dependency edges, matched sections, module summaries, present triggers) as JSON **without writing any document**. This is how `ai-ready:apply` maintains docs surgically — the script supplies read-only facts and the AI adds/updates only what changed while preserving human curation, instead of wholesale-overwriting. The `--out` write mode remains for bootstrapping a doc that does not exist yet.

## Project Config (`.ai-ready/config.json`) — v0.2.0+

Optional file at `<target>/.ai-ready/config.json` enables frontmatter-aware behavior. Without it, the v0.1.x defaults apply (backward compatible — no changes for existing users).

```json
{
  "version": 1,
  "frontmatter": {
    "required":  ["type", "feature", "module", "status", "created", "updated"],
    "search":    ["aliases", "tags"],
    "evolution": ["supersedes", "superseded-by"]
  },
  "index": {
    "groups": [
      { "id": "adr", "title": "ADR (`docs/adr/`)",
        "match": { "path_prefix": "docs/adr/" }, "sub_group_by": "feature" }
    ],
    "cross_reference": { "enabled": true, "title": "한영 검색 인덱스" },
    "evolution_graph": { "enabled": true, "title": "ADR 결정 진화", "scope": "adr" }
  },
  "lazy_load_triggers": {
    "detect":               [ { "path": "docs/adr/", "label": "[`docs/adr/`](docs/adr/)", "trigger": "ADR 조회" } ],
    "override_hardcoded":   [ "docs/decisions" ]
  },
  "rubric": {
    "decision_records": { "dir_hints": ["docs/design"] },
    "api_contracts":    { "build_deps": ["springdoc", "springfox"] }
  }
}
```

What it changes:
1. `gen_index.py` switches from hardcoded categories (claude / guides / docs-decisions / docs-other) to *config-defined groups* with frontmatter `sub_group_by` (e.g., feature/module), plus optional `cross_reference` and `evolution_graph` sections.
2. `inject_lazy_load_index.py` adds project-specific triggers (`detect`) and removes obsolete built-in ones (`override_hardcoded`).
3. Each .md file's YAML frontmatter is parsed via the bundled stdlib-only parser (`frontmatter_parser.py`) — no PyYAML dependency added.
4. **`audit.py` scoring respects the `rubric` section (v0.3.0+)**: `decision_records.dir_hints` makes the "Architecture decisions captured" rule credit a consolidated decision directory such as `docs/design/` (when a project absorbed ADR/PRD/api-doc into one living doc); `api_contracts.build_deps` makes the "Cross-module API contracts documented" rule credit code-gen dependencies such as springdoc/springfox that emit OpenAPI at runtime. Separately — no config needed — the "Mechanical verification hook" rule now also credits project-level `.claude/settings.json` hooks that run lint/test/format on edit/commit, recognizing the AI-agent harness as a mechanical verification gate.

Full schema is documented in `skills/audit/scripts/config_loader.py`.

## When To Use Each Output

- **`audit-report.md`** — read first. Tells you *what* to fix and *in what order*.
- **`dashboard.html`** — share with team / track progress over time.
- **`scaffolds/<module>/CLAUDE.md`** (multi-module) — review, edit, then move into the actual module directory.
- **`scaffolds/PACKAGES.md`** (single-module) — review, fill in the `TODO` lines, then move to `docs/PACKAGES.md` and reference it from root `CLAUDE.md` lazy-load.
- **`scaffolds/ANTIPATTERNS.md`** — review, prune false positives, then move to repo root.
- **`hooks/freshness_check.sh`** — install as a Claude Code Stop hook (instructions below).

## Installing the Freshness Hook

After reviewing the generated scaffold, add this to the target project's `.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": ".*",
        "hooks": [
          { "type": "command", "command": "$CLAUDE_PROJECT_DIR/.ai-ready/hooks/freshness_check.sh" }
        ]
      }
    ]
  }
}
```

The hook runs at session end, compares mtimes between source files and their nearest CLAUDE.md, and writes a warning if the source has drifted ahead by >7 days (configurable inside the script). The audit copies both `freshness_check.sh` and its `freshness_check.py` runner into `.ai-ready/hooks/`, so the hook is self-contained and does not depend on `CLAUDE_PLUGIN_ROOT`.

## The 7-Category Rubric (100 points)

See `RUBRIC.md` for the full criteria and detection rules. Summary:

| # | Category | Points |
|---|---|---|
| 1 | Navigation (root → modules) | 15 |
| 2 | Context Document Quality | 20 |
| 3 | Tribal Knowledge & Anti-patterns | 15 |
| 4 | Cross-module Dependency Tracking | 15 |
| 5 | Verification Quality Gates | 10 |
| 6 | Freshness Auto-Maintenance | 10 |
| 7 | Outcome Metrics | 15 |

**Grade bands**: 0-39 = AI-blind, 40-59 = AI-aware, 60-79 = AI-enabled, 80-89 = AI-maximalist, 90-100 = Agentic-ready.

## Detection Heuristics (Quick Reference)

The audit script looks at:
- Presence and line counts of `CLAUDE.md` (root + per module)
- Presence of `ANTIPATTERNS.md`, `ARCHITECTURE.md`, `ADR/`, `docs/decisions/`
- Hooks in `.git/hooks/`, `.husky/`, `.claude/hooks/`, `.claude/settings.json`
- CI configs: `.github/workflows/`, `.gitlab-ci.yml`, `.circleci/`, `Jenkinsfile`
- Build manifest signals to identify modules: `build.gradle.kts`, `build.gradle`, `pom.xml`, `package.json`, `Cargo.toml`, `go.mod`, `pyproject.toml`, `Package.swift` (Swift Package Manager), `Podfile` (CocoaPods)
- Recent git activity to find "hot" modules
- "DO NOT" / "절대" / "금지" / "MUST NOT" markers in CLAUDE.md content

## Limitations

- Heuristics-based scoring; expect ±5 points of noise. Use the trend, not the absolute number.
- Anti-pattern extraction depends on commit message hygiene. Repos with vague messages produce thin output.
- Module detection prefers conventional layouts (Gradle multi-module, npm monorepo, Python `src/` layout, Go modules, Cargo workspaces). Single-module source roots come from the stack adapters above; a stack with no adapter is reported and exits non-zero rather than being skipped silently.
- The "standard layout" rule (`controller`/`service`/`domain`/`repository`) is a JVM web convention. On other stacks it is reported as *not measured* and the catalog alone earns the points — it is never advice to restructure a non-JVM repo into that shape.
- HTML dashboard is intentionally dependency-free (vanilla CSS + inline SVG) — pretty enough but not interactive.
- **Scores the cartography (map) layer only — not code health (sanitize)**: this audit measures whether the docs/map exist and self-maintain, not whether the code underneath is healthy (test coverage, dead code, code smells). A repo can score high on the map while the terrain is still a maze — a high score on unhealthy code is a *false signal*. Treat sanitize (tests / dead-code removal / consistent conventions) as a prerequisite you ensure separately; the map only helps once the terrain is sound.
- **Does not measure token/cost**: the audit's "Outcome Metrics" category checks whether usage is *tracked*, not the cost itself. There is no session-log parser or cache-hit dashboard here — use `ccusage` / RTK `gain` for that.

## Re-running

This is meant to be run periodically (monthly is a good cadence). Each run overwrites `audit.json` / `audit-report.md` / `dashboard.html` / `README.md`, but **also archives the result to `history/{timestamp}.json`** so the dashboard can render a trend sparkline. Don't delete the `history/` directory.

**월간 정합 스캔 연계**: 대상 repo 가 living design 문서 체계 (`docs/design/{name}.md`) 를 쓰면, 월간 audit 와 *같은 날* `/sync-docs --all` (전역 드리프트 스캔) 을 함께 수행하는 리듬을 권장한다. 역할 분담 — audit 는 구조 지표 (커버리지 / 길이 / freshness 메타), 전역 스캔은 내용 정합 (문서 서술 ↔ 코드 동작의 양방향 드리프트). audit 만으로는 문서 내용이 코드와 맞는지 보장되지 않는다.
