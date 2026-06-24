#!/usr/bin/env python3
"""
신선도 검사 — 오래된 CLAUDE.md / AGENTS.md를 표시.

CLAUDE.md (또는 AGENTS.md)가 있는 디렉토리마다, 해당 디렉토리 트리 안의 가장 최근
소스 파일 mtime을 찾아 비교합니다. 임계값(기본 7일)보다 더 뒤처지면 경고합니다.

Claude Code Stop hook으로 `freshness_check.sh` 를 통해 호출되도록 설계됐습니다.

종료 코드는 항상 0 (advisory) — 세션을 절대 차단하지 않습니다. 결과는 stdout 및
`<target>/.ai-ready/freshness.log` 에 기록됩니다.

M-7 fix: 단일 walk + nearest-ancestor 매핑으로 O(N²) → O(N) 알고리즘으로 변경.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

EXCLUDE_DIRS = {
    ".git", "node_modules", "build", "dist", "target", ".gradle", ".idea",
    "out", "bin", "vendor", ".venv", "venv", "__pycache__", ".next", ".turbo",
    ".pytest_cache", ".mypy_cache",
    ".ai-ready",
    "worktrees",  # git worktree(.claude/worktrees) = repo 전체 복사본 — 통째 중복 수집 방지
}

CODE_EXTS = {
    ".kt", ".java", ".scala", ".groovy",
    ".ts", ".tsx", ".js", ".jsx", ".mjs",
    ".py", ".rs", ".go", ".rb", ".php", ".cs", ".swift",
}

DOC_NAMES = {"CLAUDE.md", "AGENTS.md"}


def find_owning_doc_dir(src_path: Path, doc_dirs: set[Path]) -> Path | None:
    """src_path의 가장 가까운 ancestor doc_dir을 반환 (없으면 None)."""
    p = src_path.parent
    seen = set()
    while p not in seen:
        seen.add(p)
        if p in doc_dirs:
            return p
        if p == p.parent:
            break
        p = p.parent
    return None


def collect(target: Path) -> tuple[dict, list]:
    """단일 walk로 doc_dir 정보와 소스 파일 mtime 정보를 동시 수집.

    반환:
      - doc_dir_info: {Path: (mtime, doc_file_Path)}
      - source_records: list of (Path, mtime)
    """
    doc_dir_info: dict[Path, tuple[float, Path]] = {}
    source_records: list[tuple[Path, float]] = []

    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        dir_path = Path(dirpath)
        for f in filenames:
            full = dir_path / f
            if f in DOC_NAMES:
                try:
                    m = full.stat().st_mtime
                except OSError:
                    continue
                if dir_path not in doc_dir_info or m > doc_dir_info[dir_path][0]:
                    doc_dir_info[dir_path] = (m, full)
            elif Path(f).suffix in CODE_EXTS:
                try:
                    m = full.stat().st_mtime
                except OSError:
                    continue
                source_records.append((full, m))
    return doc_dir_info, source_records


def check(target: Path, threshold_days: int) -> list[str]:
    threshold = threshold_days * 86400
    doc_dir_info, source_records = collect(target)

    if not doc_dir_info:
        return [f"⚠️ {target} 아래에 CLAUDE.md / AGENTS.md를 찾을 수 없음"]

    doc_dirs_set = set(doc_dir_info.keys())
    # 각 doc_dir마다 자신의 scope 안에서 가장 최근 소스
    newest_per_doc: dict[Path, tuple[float, Path | None]] = {d: (0.0, None) for d in doc_dirs_set}

    for src_path, src_mtime in source_records:
        owner = find_owning_doc_dir(src_path, doc_dirs_set)
        if owner is None:
            continue
        if src_mtime > newest_per_doc[owner][0]:
            newest_per_doc[owner] = (src_mtime, src_path)

    findings = []
    for d, (d_mtime, d_path) in doc_dir_info.items():
        s_mtime, s_path = newest_per_doc.get(d, (0.0, None))
        if s_mtime == 0 or s_path is None:
            continue
        drift = s_mtime - d_mtime
        if drift > threshold:
            days = drift / 86400
            rel_d = d_path.relative_to(target)
            rel_s = s_path.relative_to(target)
            findings.append(
                f"🟡 {rel_d} 가 가장 최근 소스 ({rel_s}) 보다 {days:.0f}일 뒤처짐. "
                f"문서 재검토를 권장합니다."
            )
    if not findings:
        findings.append(
            f"✅ 문서가 있는 {len(doc_dir_info)}개 디렉토리가 모두 {threshold_days}일 신선도 윈도우 이내입니다."
        )
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="프로젝트 루트")
    ap.add_argument("--threshold-days", type=int, default=7)
    ap.add_argument("--quiet", action="store_true", help="경고가 있을 때만 출력")
    args = ap.parse_args()
    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"freshness: 대상이 디렉토리가 아님: {target}", file=sys.stderr)
        return 0
    findings = check(target, args.threshold_days)
    log_dir = target / ".ai-ready"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "freshness.log"
    stamp = datetime.now().isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"\n--- {stamp} ---\n")
        for line in findings:
            f.write(line + "\n")
    has_warnings = any(line.startswith("🟡") or line.startswith("⚠️") for line in findings)
    if args.quiet and not has_warnings:
        return 0
    for line in findings:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
