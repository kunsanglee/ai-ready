#!/usr/bin/env python3
"""사람이 인수한 문서를 ai-ready 가 덮어쓰지 않도록 막는 가드 (v0.4.0+).

ai-ready 생성 스크립트(gen_index / gen_arch_diagram / extract_section / inject_module_map)는
대상 파일을 *전체 덮어쓴다*. 그런데 사람이 그 문서를 직접 손보면서 자동 생성 시그니처를
지우는 경우가 있다 (예: NAMING.md / TESTING.md 를 산문으로 다듬어 권위 문서로 전환). 이때
스크립트가 무심코 덮어쓰면 사람 작업이 날아간다.

이 모듈은 출력 대상이 (1) 없거나 (2) ai-ready 자동 생성 시그니처를 그대로 가진 경우에만
덮어쓰기를 허용하고, 그 외(= 사람이 인수)에는 덮어쓰기를 거부한다. `--force` 로만 강제.

confirm 자체는 스크립트가 하지 않는다 — 결정론·헤드리스 도구이기 때문이다. 대화형 diff
confirm 은 apply 스킬(Claude) 레이어가 담당하고, 이 가드는 "사람 인수 문서를 말없이 덮어쓰는"
사고만 막는 마지막 안전장치다.

stdlib-only.
"""
from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["is_ai_ready_generated", "guard_overwrite", "add_force_arg"]

# ai-ready 생성물이 헤더에 박는 시그니처 (신형).
AUTO_SIGNATURES = (
    "자동 생성 (`ai-ready:apply`",
    "자동 추출 (`ai-ready:apply`",
    "auto-generated",
    "ai-ready:apply",
)
# 구형 / 카탈로그형 — "_자동 생성: 2026-05-06 · 대상: ..._" / "자동 생성됩니다" 같은 라인.
AUTO_SIGNATURE_PREFIXES = (
    "_자동 생성:",
    "자동 생성됩니다",
)

# 헤더 영역(앞 N줄)만 검사 — 본문에 우연히 들어간 문자열로 인한 오판 방지.
_HEADER_LINES = 15


def is_ai_ready_generated(path: Path) -> bool:
    """파일 헤더에 ai-ready 자동 생성 시그니처가 있으면 True."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            head = "".join(next(f, "") for _ in range(_HEADER_LINES))
    except OSError:
        return False
    if any(sig in head for sig in AUTO_SIGNATURES):
        return True
    return any(pref in head for pref in AUTO_SIGNATURE_PREFIXES)


def guard_overwrite(out_path: Path, force: bool = False) -> bool:
    """덮어써도 되는지 판정. 안전하면 True, 사람 인수라 막아야 하면 False (+ 경고 stderr).

    - 파일 없음 → True (새로 생성)
    - 자동 생성 시그니처 있음 → True (ai-ready 생성물, 덮어쓰기 안전)
    - 시그니처 없음 (사람 인수) → force 면 True (+ 경고), 아니면 False (+ 안내)
    """
    if not out_path.exists():
        return True
    if is_ai_ready_generated(out_path):
        return True
    if force:
        print(f"경고: {out_path} 는 사람이 인수한 문서로 보이지만 --force 로 덮어씁니다.",
              file=sys.stderr)
        return True
    print(
        f"중단: {out_path} 에 ai-ready 자동 생성 시그니처가 없습니다 — 사람이 직접 관리 중일 수 "
        f"있어 덮어쓰지 않습니다.\n"
        f"  의도한 재생성이면 --force 를, 아니면 apply 스킬에서 diff 를 확인하고 필요한 부분만 "
        f"반영하세요.",
        file=sys.stderr,
    )
    return False


def add_force_arg(parser) -> None:
    """생성 스크립트의 argparse 에 공통 --force 플래그 추가."""
    parser.add_argument(
        "--force", action="store_true",
        help="사람이 인수한(자동 생성 시그니처 없는) 문서도 덮어쓰기 강제",
    )
