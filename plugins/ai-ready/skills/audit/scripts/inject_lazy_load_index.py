#!/usr/bin/env python3
"""
루트 CLAUDE.md 에 Lazy-load 트리거 테이블 주입.

대상 디렉토리에 존재하는 docs/ 가이드와 광역 문서를 자동 감지해
"트리거 (대화 맥락) → 문서" 매핑을 idempotent block 으로 추가한다.

매 세션 자동 로드되는 루트 CLAUDE.md 분량을 줄이고, AI 가 작업 맥락에
맞는 detail 문서를 lazy-load 하도록 유도하는 게 목적이다.

ROI 액션 매핑: "'사용 시점' 가이드 존재" + "lazy-load 인덱스" (Rule 2.4 + 1.5).

실행:
  python3 inject_lazy_load_index.py --target /path/to/repo

  # 미리 보기 (수정 안 함)
  python3 inject_lazy_load_index.py --target /path/to/repo --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

CLAUDE_DOC_NAMES = ("CLAUDE.md", "AGENTS.md")

BEGIN_MARKER = "<!-- lazy-load:begin (auto-generated) -->"
END_MARKER = "<!-- lazy-load:end -->"

# 감지 패턴: (파일/디렉토리 경로, 문서 표기, 트리거 설명)
DETECTION_RULES = [
    ("docs/COMMANDS.md", "[`docs/COMMANDS.md`](docs/COMMANDS.md)",
        "빌드·실행·lint 등 명령어 확인"),
    ("docs/CONVENTIONS.md", "[`docs/CONVENTIONS.md`](docs/CONVENTIONS.md)",
        "코드 작성 detail (repository 패턴·DTO 분리·검증 등)"),
    ("NAMING.md", "[`NAMING.md`](NAMING.md)",
        "클래스/패키지/메서드/DTO 명명, 컬럼 네이밍"),
    ("docs/API_COMPATIBILITY.md", "[`docs/API_COMPATIBILITY.md`](docs/API_COMPATIBILITY.md)",
        "Response DTO 변경, 필드 추가/제거, 버전 호환성"),
    ("docs/ERROR_HANDLING.md", "[`docs/ERROR_HANDLING.md`](docs/ERROR_HANDLING.md)",
        "에러 코드 추가, 예외 처리, i18n 메시지"),
    ("TESTING.md", "[`TESTING.md`](TESTING.md)",
        "테스트 작성, 픽스처/Factory 추가, 베이스 클래스 사용"),
    ("docs/GIT_WORKFLOW.md", "[`docs/GIT_WORKFLOW.md`](docs/GIT_WORKFLOW.md)",
        "커밋 메시지·브랜치 네이밍·PR 본문 형식"),
    ("docs/DDL_DML.md", "[`docs/DDL_DML.md`](docs/DDL_DML.md)",
        "마이그레이션, CREATE TABLE, 인덱스 작성"),
    ("ANTIPATTERNS.md", "[`ANTIPATTERNS.md`](ANTIPATTERNS.md)",
        "신규 코드 작성·리뷰, 안티패턴 점검"),
    ("ARCHITECTURE.md", "[`ARCHITECTURE.md`](ARCHITECTURE.md)",
        "모듈 의존성 / 영향 범위 분석, 새 모듈 결합 검토"),
    ("docs/decisions", "[`docs/decisions/`](docs/decisions/) (ADR)",
        '"왜 이렇게 결정됐나?" — 아키텍처 의사결정 근거 확인'),
    ("docs/INDEX.md", "[`docs/INDEX.md`](docs/INDEX.md)",
        "처음 진입 / 모든 문서 카탈로그"),
    ("docs/pre-commit-setup.md", "[`docs/pre-commit-setup.md`](docs/pre-commit-setup.md)",
        "사전 커밋 훅 셋업·우회"),
    (".ai-ready/audit-report.md", "[`.ai-ready/audit-report.md`](.ai-ready/audit-report.md)",
        "AI 준비도 점수·추이 확인"),
]


def find_root_doc(target: Path) -> Path | None:
    for name in CLAUDE_DOC_NAMES:
        p = target / name
        if p.exists():
            return p
    return None


def detect_present(target: Path) -> list[tuple[str, str]]:
    """존재하는 detail 문서만 (문서 표기, 트리거) 튜플 리스트로 반환."""
    found = []
    for path, label, trigger in DETECTION_RULES:
        if (target / path).exists():
            found.append((label, trigger))
    return found


def render_block(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return ""
    lines = []
    lines.append("## Lazy-load docs (트리거 시 즉시 read)")
    lines.append("")
    lines.append(BEGIN_MARKER)
    lines.append("")
    lines.append("> 자동 생성됩니다. 수동 편집은 다음 갱신 시 덮어쓰여집니다.")
    lines.append("> 갱신: Claude Code 에서 `ai-ready:apply` 스킬을 호출하거나 \"lazy-load 인덱스 갱신해줘\" 라고 말하세요.")
    lines.append(">")
    lines.append("> **읽기 강제 시점**: 작업 영역이 트리거에 해당하면 사용자 추가 지시 없이도 즉시 read.")
    lines.append("> **모듈 단위**: 모듈 CLAUDE.md 는 그 모듈 파일을 Read/Edit 할 때 Claude Code 가 자동 로드.")
    lines.append("")
    lines.append("| 트리거 (대화·작업 맥락) | 문서 |")
    lines.append("|---|---|")
    for label, trigger in rows:
        lines.append(f"| {trigger} | {label} |")
    lines.append("")
    lines.append(END_MARKER)
    return "\n".join(lines)


def update_root(text: str, block: str) -> tuple[str, bool]:
    """루트 CLAUDE.md 의 lazy-load 블록을 idempotent 으로 갱신.

    - 기존 블록이 있으면 그 자리(섹션 헤딩 포함)를 새 block 으로 교체
    - 없으면 `## 모듈 맵` 섹션 직전에 삽입, 그것도 없으면 EOF 에 append
    """
    if BEGIN_MARKER in text and END_MARKER in text:
        # 섹션 헤딩 ~ END_MARKER 까지 교체
        # 안전하게 헤딩 라인부터 검색
        start_marker = "## Lazy-load docs"
        idx_heading = text.find(start_marker)
        idx_begin = text.find(BEGIN_MARKER)
        # 헤딩이 begin 보다 앞에 있고 가까우면 그 헤딩부터 교체
        if 0 <= idx_heading < idx_begin:
            start = idx_heading
        else:
            start = idx_begin
        end = text.find(END_MARKER) + len(END_MARKER)
        # END 다음의 trailing newline 1개도 같이 처리
        return text[:start] + block + text[end:], True

    # 신규 삽입 — `## 모듈 맵` 직전, 또는 EOF
    target_heading = "## 모듈 맵"
    idx = text.find(target_heading)
    if idx >= 0:
        return text[:idx] + block + "\n\n" + text[idx:], True
    # EOF append
    if not text.endswith("\n"):
        text += "\n"
    return text + "\n" + block + "\n", True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="대상 코드베이스 경로")
    ap.add_argument("--dry-run", action="store_true",
                    help="실제 파일은 수정하지 않고 결과만 출력")
    args = ap.parse_args()
    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"오류: 대상이 디렉토리가 아님: {target}", file=sys.stderr)
        sys.exit(2)
    root = find_root_doc(target)
    if not root:
        print("루트 CLAUDE.md / AGENTS.md 가 없어서 주입할 위치가 없습니다.", file=sys.stderr)
        sys.exit(1)
    rows = detect_present(target)
    if not rows:
        print("감지된 detail 문서가 없습니다 — lazy-load 인덱스를 만들 대상이 없습니다.")
        sys.exit(0)
    block = render_block(rows)
    text = root.read_text(encoding="utf-8")
    new_text, _ = update_root(text, block)
    if args.dry_run:
        print("=== dry-run 결과 ===")
        print(block)
        print()
        print(f"_변경 여부: {'있음' if new_text != text else '없음'}_")
        return
    if new_text == text:
        print(f"변경 없음: {root}  (lazy-load 인덱스 최신)")
        return
    root.write_text(new_text, encoding="utf-8")
    print(f"lazy-load 인덱스 갱신: {root}")
    print(f"  감지된 detail 문서 {len(rows)}개")


if __name__ == "__main__":
    main()
