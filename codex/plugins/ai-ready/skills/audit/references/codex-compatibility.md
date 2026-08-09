# Codex adapter boundary

The Codex adapter supports audit, reviewed documentation apply, explicit
freshness checks, bounded read-only review, and Codex-native unattended
maker/checker loops (build, lessons). The loops run through
Codex's own session delegation and the shared deterministic `_loop-engine`; they
do not install a Claude Stop hook and do not reuse Claude-only agents or hooks.

- Treat `AGENTS.md` as the preferred guidance surface and accept `CLAUDE.md` as a compatible source or bridge.
- Preserve generated `.ai-ready/` history and drafts, but require per-file approval before touching live guidance.
- Use a project-owned CI or pre-commit implementation if mechanical freshness enforcement is needed.
- Do not copy plugin caches, credentials, global settings, or Claude agent configuration into this adapter. The loop skills orchestrate through Codex session delegation with inline role contracts, not by importing Claude agent definitions.
- The loops make no verdict in the model: severity and the PASS/RETRY/AWAIT_USER decision come only from `_loop-engine`, and the loops stop at an uncommitted working tree (a human finishes the commit and PR).
