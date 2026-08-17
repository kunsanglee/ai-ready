#!/usr/bin/env python3
"""
모듈 맵을 두 위치에 idempotent 하게 갱신:

1. `docs/MODULE_MAP.md` — 전체 모듈 목록 (52+ 엔트리). 단일 출처.
2. 루트 CLAUDE.md / AGENTS.md 의 `## 모듈 맵` 섹션 — 짧은 stub:
   - 전체 목록 링크
   - 자체 `CLAUDE.md` 가 있는 "documented" 모듈만 (audit 의 모듈 경로 참조 검사 통과 + skim 용도)
   - 모듈 N 개 통계

이렇게 분리하면 매 세션 자동 로드되는 루트 분량을 ~50줄 이상 절감하면서도
모듈 검색·진입은 여전히 1-홉 (루트 → MODULE_MAP.md) 으로 가능.

모듈 요약은 그 모듈의 CLAUDE.md/AGENTS.md 첫 줄에서 가져오며, 없으면 "(설명 없음)".

ROI 규칙 (audit 의 규칙 이름 그대로 — 번호가 아니라 이름으로 가리킨다):
  - "루트 문서가 3개 이상의 모듈 경로/문서 참조" (+4점)
  - "루트 문서가 패키지 카탈로그 또는 3개 이상의 패키지 경로 참조" (+4점, 단일 모듈)
  - "루트 CLAUDE.md 상주 분량 (800~8,000바이트)" (+5점)

실행:
  python3 inject_module_map.py --target /path/to/repo
  python3 inject_module_map.py --target /path/to/repo --dry-run   # 미리보기
"""
from __future__ import annotations

import argparse
import json
import os
import re as _re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
from managed_doc import guard_overwrite, add_force_arg  # noqa: E402
from gen_index import ensure_gitattributes_union  # noqa: E402
from config_loader import load_config, module_map_root_stub_limit  # noqa: E402

DOC_NAMES = ("CLAUDE.md", "AGENTS.md")
BUILD_MANIFESTS = {
    "build.gradle.kts", "build.gradle", "pom.xml",
    "package.json", "Cargo.toml", "go.mod", "pyproject.toml", "setup.py",
    # iOS / Apple
    "Package.swift",   # Swift Package Manager
    "Podfile",         # CocoaPods
}
EXCLUDE_DIRS = {
    ".git", "node_modules", "build", "dist", "target", ".gradle", ".idea",
    "out", "bin", "vendor", ".venv", "venv", "__pycache__", ".next", ".turbo",
    ".pytest_cache", ".mypy_cache", ".ai-ready",
    "worktrees",  # git worktree(.claude/worktrees) = repo 전체 복사본 — 통째 중복 수집 방지
}

SECTION_HEADER = "## 모듈 맵"
SECTION_BEGIN = "<!-- module-map:begin (auto-generated) -->"
SECTION_END = "<!-- module-map:end -->"

MODULE_MAP_FILE = "docs/MODULE_MAP.md"

STUB_DOCUMENTED_LIMIT = 10  # 루트 stub 에 노출할 documented 모듈 최대 수 (config 의 module_map.root_stub_limit 로 재정의, 0 이면 나열 없음)


def walk(target: Path):
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        yield Path(dirpath), dirnames, filenames


def find_modules(target: Path) -> list[Path]:
    seen = set()
    out = []
    for dirpath, _, filenames in walk(target):
        for f in filenames:
            if f in BUILD_MANIFESTS:
                rel = dirpath.relative_to(target)
                if rel == Path("."):
                    break
                if rel not in seen:
                    seen.add(rel)
                    out.append(rel)
                break
    return sorted(out, key=str)


def get_module_summary(target: Path, module: Path, max_chars: int = 100) -> str:
    """모듈 디렉토리의 CLAUDE.md/AGENTS.md에서 첫 의미있는 줄 추출."""
    for name in DOC_NAMES:
        p = target / module / name
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        in_fm = False
        for i, line in enumerate(lines):
            s = line.strip()
            if i == 0 and s == "---":
                in_fm = True
                continue
            if in_fm:
                if s == "---":
                    in_fm = False
                continue
            if not s or s.startswith("#"):
                continue
            cleaned = s.lstrip("> ").rstrip()
            if not cleaned:
                continue
            if _re.fullmatch(r"_.+_", cleaned):
                continue
            if _re.match(r"^[-*]\s*(상태|일자|date|status|관련|related)\s*:", cleaned, _re.IGNORECASE):
                continue
            if len(cleaned) > max_chars:
                cleaned = cleaned[: max_chars - 1].rstrip() + "…"
            return cleaned
    return "(설명 없음)"


def has_module_doc(target: Path, module: Path) -> bool:
    return any((target / module / name).exists() for name in DOC_NAMES)


def find_root_doc(target: Path) -> Path | None:
    for name in DOC_NAMES:
        p = target / name
        if p.exists():
            return p
    return None


def build_full_map_doc(target: Path, modules: list[Path]) -> str:
    """docs/MODULE_MAP.md 전체 본문."""
    today_iso = ""  # 일자 추가 안 함 (자주 변경)
    lines = ["# 모듈 맵", ""]
    lines.append("> 빌드 매니페스트(`build.gradle.kts` 등) 로 자동 감지된 모듈 카탈로그.")
    lines.append("> 모듈별 1줄 요약은 그 모듈의 `CLAUDE.md` 첫 줄에서 추출. (설명 없음) 표시는 모듈 가이드를 추가하면 자동 채워짐.")
    lines.append("")
    lines.append(SECTION_BEGIN)
    lines.append("")
    if not modules:
        lines.append("(빌드 매니페스트로 감지된 모듈 없음)")
    else:
        for m in modules:
            summary = get_module_summary(target, m)
            lines.append(f"- `{m}` — {summary}")
    lines.append("")
    lines.append(SECTION_END)
    lines.append("")
    return "\n".join(lines)


def build_root_stub(target: Path, modules: list[Path],
                    stub_limit: int = STUB_DOCUMENTED_LIMIT) -> str:
    """루트 CLAUDE.md 의 `## 모듈 맵` stub.

    audit 의 모듈 경로 참조 검사를 통과하기 위해 documented 모듈을 일부 노출.
    `stub_limit == 0` 이면 그 나열을 생략하고 카탈로그 링크만 남긴다 — 루트 문서는 매 세션
    always-loaded 이고 모듈 요약은 그 모듈 CLAUDE.md 에 이미 있어 발췌가 중복인 레포용
    (config 의 `module_map.root_stub_limit`). 그 경우 경로 참조는 다른 곳에서 나와야 한다.
    """
    documented = [m for m in modules if has_module_doc(target, m)]
    documented_count = len(documented)
    total = len(modules)
    sample = documented[:stub_limit] if stub_limit > 0 else []

    # 자동 생성 표시는 SECTION_BEGIN 마커의 `(auto-generated)` 가 이미 한다 — 루트 문서는 매
    # 세션 always-loaded 라 같은 말을 산문으로 한 번 더 쓰면 그 분량을 매 세션 낸다.
    lines = [SECTION_HEADER, "", SECTION_BEGIN, ""]
    lines.append(f"전체 모듈 카탈로그 ({total}개): [`{MODULE_MAP_FILE}`]({MODULE_MAP_FILE})")
    if documented_count and sample:
        lines.append("")
        lines.append(f"가이드가 작성된 핵심 모듈 ({documented_count}개 중 상위 {len(sample)}개):")
        lines.append("")
        for m in sample:
            summary = get_module_summary(target, m)
            # CLAUDE.md / AGENTS.md 중 실재하는 파일로 링크 — AGENTS.md 만 있는 모듈의 깨진 링크 방지.
            doc = next((n for n in DOC_NAMES if (target / m / n).exists()), "CLAUDE.md")
            lines.append(f"- [`{m}`]({m}/{doc}) — {summary}")
        if documented_count > len(sample):
            lines.append(f"- … 외 {documented_count - len(sample)}개 (전체 목록은 위 카탈로그 링크 참조)")
    lines.append("")
    lines.append(SECTION_END)
    return "\n".join(lines)


def inject(text: str, new_section: str) -> str:
    """기존 섹션이 있으면 교체, 없으면 파일 끝에 추가.

    1) 마커가 있으면 마커 구간 교체.
    2) 마커는 없지만 손수 작성한 `## 모듈 맵` 헤더 섹션이 있으면 그 헤더부터 다음 헤딩(또는 EOF)
       까지를 마커 래핑된 새 섹션으로 *교체* 한다 — EOF 에 둘째 `## 모듈 맵` 을 덧붙여 영구 중복을
       만들던 버그 차단(inject_lazy_load_index 의 마커 없는 기존 섹션 처리와 동일한 결).
    3) 둘 다 없으면 파일 끝에 추가.
    """
    if SECTION_BEGIN in text and SECTION_END in text:
        before, _, rest = text.partition(SECTION_BEGIN)
        if before.rstrip().endswith(SECTION_HEADER):
            before = before.rstrip()[: -len(SECTION_HEADER)].rstrip() + "\n"
        _, _, after = rest.partition(SECTION_END)
        return before.rstrip() + "\n\n" + new_section + after
    # 마커 없는 손수 작성 `## 모듈 맵` 섹션이 있으면 그 자리를 교체(중복 추가 방지).
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln.strip() == SECTION_HEADER:
            j = i + 1
            while j < len(lines) and not (lines[j].startswith("## ") or lines[j].startswith("# ")):
                j += 1
            before = "\n".join(lines[:i]).rstrip()
            after = "\n".join(lines[j:]).strip("\n")
            head = (before + "\n\n") if before else ""
            tail = ("\n\n" + after + "\n") if after else "\n"
            return head + new_section + tail
    # replace 분기와 동일한 spacing 으로 통일 — 첫 실행(append)과 재실행(replace) 출력이 일치(멱등).
    return text.rstrip() + "\n\n" + new_section + "\n"


def collect_facts(target: Path) -> dict:
    """문서를 쓰지 않고 모듈 사실(경로·요약·가이드 존재)만 모아 반환.

    AI 가 이 사실 + 현재 루트 CLAUDE.md '모듈 맵'·MODULE_MAP.md 를 읽고 새 모듈만 더하고
    바뀐 요약만 고치며 사람 큐레이션을 보존한다.
    """
    modules = find_modules(target)
    return {"target": str(target), "modules": [
        {"module": str(m), "summary": get_module_summary(target, m),
         "has_doc": has_module_doc(target, m)} for m in modules]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="대상 코드베이스 경로")
    ap.add_argument("--dry-run", action="store_true", help="실제 파일은 수정하지 않고 결과만 출력")
    ap.add_argument("--json", action="store_true", dest="json_mode",
                    help="문서를 쓰지 않고 모듈 사실만 JSON 으로 출력(읽기 전용). apply 의 AI 외과 유지보수용")
    add_force_arg(ap)
    args = ap.parse_args()
    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"오류: 대상이 디렉토리가 아님: {target}", file=sys.stderr)
        sys.exit(2)
    if args.json_mode:
        print(json.dumps(collect_facts(target), ensure_ascii=False, indent=2))
        return
    root_doc = find_root_doc(target)
    if root_doc is None:
        print(f"오류: 루트 CLAUDE.md / AGENTS.md를 찾을 수 없음. 먼저 생성하세요.", file=sys.stderr)
        sys.exit(3)

    modules = find_modules(target)
    cfg = load_config(target)
    stub_limit = module_map_root_stub_limit(cfg)
    full_doc_text = build_full_map_doc(target, modules)
    stub = build_root_stub(target, modules, stub_limit)
    if stub_limit == 0:
        # 나열을 끄면 루트 문서의 모듈 경로 참조가 줄어든다 — audit 의 "루트 문서가 3개 이상의
        # 모듈 경로/문서 참조" 규칙이 이 나열에만 의존하는 레포는 점수가 내려간다. 조용히
        # 깎이지 않게 알린다.
        print("module_map.root_stub_limit=0 — 루트 stub 의 모듈 나열을 생략합니다. "
              "audit 의 모듈 경로 참조 규칙은 lazy-load 표 등 다른 경로 참조로 충족돼야 합니다.")
    full_path = target / MODULE_MAP_FILE
    original_root = root_doc.read_text(encoding="utf-8")
    new_root = inject(original_root, stub)
    original_full = full_path.read_text(encoding="utf-8") if full_path.exists() else ""

    if args.dry_run:
        print("=== dry-run: docs/MODULE_MAP.md ===")
        print(full_doc_text)
        print()
        print("=== dry-run: 루트 CLAUDE.md 의 ## 모듈 맵 stub ===")
        print(stub)
        print()
        print(f"_변경 여부: docs/MODULE_MAP.md = {'있음' if full_doc_text != original_full else '없음'}, 루트 = {'있음' if new_root != original_root else '없음'}_")
        return

    full_path.parent.mkdir(parents=True, exist_ok=True)
    if full_doc_text != original_full:
        if guard_overwrite(full_path, args.force):
            full_path.write_text(full_doc_text, encoding="utf-8")
            ensure_gitattributes_union(target, full_path)  # 집계 산출물 — 브랜치 간 머지 충돌 방지(gen_index 와 동일)
            print(f"전체 모듈 맵 갱신: {full_path}")
        else:
            print(f"건너뜀(사람 인수 추정): {full_path} — 루트 stub 은 마커 기반이라 계속 진행")
    else:
        print(f"변경 없음: {full_path}")
    if new_root != original_root:
        root_doc.write_text(new_root, encoding="utf-8")
        print(f"루트 stub 갱신: {root_doc}")
    else:
        print(f"변경 없음: {root_doc}")
    documented_count = sum(1 for m in modules if has_module_doc(target, m))
    print(f"  모듈 {len(modules)}개 (가이드 작성된 모듈 {documented_count}개)")


if __name__ == "__main__":
    main()
