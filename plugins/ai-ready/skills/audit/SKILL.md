---
name: audit
description: Score a codebase for AI-readiness against a 7-category 100-point rubric and generate a markdown report, an HTML dashboard, module-level CLAUDE.md scaffolds, and an ANTIPATTERNS.md seed extracted from git history. Use this skill whenever the user wants to assess how well their codebase is set up for AI agents (Claude/Codex/Gemini), generate per-module CLAUDE.md files, extract anti-patterns, or build a navigation map for a large codebase — even if they don't explicitly say the word "audit". Trigger on phrases like "ai-ready audit", "AI 준비도", "코드베이스 감사", "score my codebase for AI agents", "generate module CLAUDE.md", "anti-patterns from git history", "AI 친화 코드베이스", "make this repo navigable for Claude", or "we have no map for AI".
---

# AI-Ready Codebase Audit

Turns a codebase into an AI-navigable one. Inspired by Meta's internal "AI had no map" → "59 module CLAUDE.md files" approach (Meta Engineering blog, 2026).

## What This Skill Produces

For a target codebase you point it at, this skill creates an `.ai-ready/` directory containing:

1. **`audit.json`** — raw scores (per-category, per-rule, evidence)
2. **`audit-report.md`** — human-readable report with ROI-prioritized action list
3. **`README.md`** — auto-generated guide for `.ai-ready/` consumers (artifact map, plugin install, score interpretation, re-run instructions)
4. **`dashboard.html`** — self-contained HTML dashboard with score gauge, category bars, and trend sparkline (open in browser)
5. **`history/{timestamp}.json`** — every run is archived here so the dashboard can render a trend line. Do not delete.
6. **`scaffolds/<module>/CLAUDE.md`** — draft module-level CLAUDE.md files for top hot modules
7. **`scaffolds/ANTIPATTERNS.md`** — seed anti-patterns extracted from git history (clustered hotspots)
8. **`hooks/freshness_check.sh`** — copied from the plugin so a project's `.claude/settings.json` Stop hook can reference it as `$CLAUDE_PROJECT_DIR/.ai-ready/hooks/freshness_check.sh`

## Inputs You Need

- **Target codebase path** (absolute path). Example: `/Users/me/projects/my-api`
- **(Optional)** Top N modules to scaffold (default: 5)
- **(Optional)** Lookback days for git anti-pattern extraction (default: 180)

## How To Run

The skill ships a baseline four-step run plus several optional action scripts (see "Additional Action Scripts" below). All scripts are stdlib-only — **no third-party dependencies**. Run the four baseline scripts in this order:

```bash
SKILL_DIR="$CLAUDE_PLUGIN_ROOT/skills/audit"
TARGET="<absolute path to target codebase>"
OUT="$TARGET/.ai-ready"
mkdir -p "$OUT"

# 1) Score the codebase
python3 "$SKILL_DIR/scripts/audit.py" --target "$TARGET" --out "$OUT"

# 2) Generate module CLAUDE.md scaffolds (top 5 modules)
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
| `gen_index.py` | "Create docs/INDEX.md (preferred) / wiki/index.md" | Builds a single-line summary index from every CLAUDE.md / AGENTS.md found |
| `inject_module_map.py` | "Add module map to root CLAUDE.md" | Injects an auto-regenerable "## 모듈 맵" section into root CLAUDE.md (idempotent, marker-fenced) |
| `inject_lazy_load_index.py` | "Thin index pattern" | Injects a lazy-load trigger table into root CLAUDE.md, mapping triggers to `docs/*.md` for thin-index style |
| `extract_section.py --kind testing` | "Split TESTING.md" | Lifts the testing section out of CLAUDE.md into a dedicated file |
| `extract_section.py --kind naming` | "Split NAMING.md" | Lifts the naming/conventions section out into NAMING.md |
| `install_hook.py` | "Install freshness Stop hook" | Adds the hook to `.claude/settings.json` (idempotent) |
| `gen_arch_diagram.py` | "Generate ARCHITECTURE.md with Mermaid" | Parses gradle / npm dependencies and emits a Mermaid graph |
| `scaffold.py` | "Module CLAUDE.md coverage" | Drafts CLAUDE.md for the top-N hot modules — fills module summary, dependency list, and hot-file list automatically |
| `extract_antipatterns.py` | "Seed ANTIPATTERNS.md" | Clusters `fix` / `hotfix` / `revert` (and Korean equivalents) commits by keyword and module hotspot |

Scripts that modify existing files (`inject_module_map.py`, `install_hook.py`) are idempotent and expose a `--dry-run` option so changes can be previewed first.

## When To Use Each Output

- **`audit-report.md`** — read first. Tells you *what* to fix and *in what order*.
- **`dashboard.html`** — share with team / track progress over time.
- **`scaffolds/<module>/CLAUDE.md`** — review, edit, then move into the actual module directory.
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

The hook runs at session end, compares mtimes between source files and their nearest CLAUDE.md, and writes a warning if the source has drifted ahead by >7 days (configurable inside the script).

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
- The skill is language-agnostic but the module detection prefers conventional layouts (Gradle multi-module, npm monorepo, Python `src/` layout, Go modules, Cargo workspaces).
- HTML dashboard is intentionally dependency-free (vanilla CSS + inline SVG) — pretty enough but not interactive.

## Re-running

This is meant to be run periodically (monthly is a good cadence). Each run overwrites `audit.json` / `audit-report.md` / `dashboard.html` / `README.md`, but **also archives the result to `history/{timestamp}.json`** so the dashboard can render a trend sparkline. Don't delete the `history/` directory.
