#!/usr/bin/env python3
"""사람이 인수한 파일을 ai-ready 가 덮어쓰지 않도록 막는 가드.

ai-ready 생성 스크립트(scaffold.py)는 대상 파일을 *전체 덮어쓴다*. 그런데 사람이 생성물을 받아
다듬으면서 자동 생성 서명 줄을 지우는 경우가 있다. 이때 스크립트가 무심코 덮어쓰면 사람 작업이
날아간다.

이 모듈은 출력 대상이 (1) 없거나 (2) ai-ready 자동 생성 서명을 그대로 가진 경우에만 덮어쓰기를
허용하고, 그 외(= 사람이 인수)에는 거부한다. `--force` 로만 강제한다.

문서 구조의 기본값도 여기 둔다. `AGENTS.md` 가 원본(서명이 든 일반 파일)이고, 옆의 `CLAUDE.md` 는
`@AGENTS.md` 한 줄로 그것을 가져온다. Claude Code 는 한 폴더에 둘이 있으면 `CLAUDE.md` 만 읽고, 가져오기
경로는 가져오는 파일 기준으로 푼다. 심볼릭 링크는 Windows 클론에서 한 줄짜리 파일로 풀리고 Edit·Write 도구가
링크를 따라 쓰지 않아 쓰지 않는다.

만들 파일이 git 에서 무시되면 커밋되지 않아 저장소에 남지 않는다. `ignored_paths` 가 그것을 쓰기 전에 알린다.

확인 대화는 스크립트가 하지 않는다 — 결정론·헤드리스 도구이기 때문이다. 대화형 diff 확인은
apply 스킬이 맡고, 이 가드는 "사람이 인수한 파일을 말없이 덮어쓰는" 사고만 막는 마지막 장치다.

stdlib-only.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

__all__ = ["is_ai_ready_generated", "guard_overwrite", "add_force_arg", "AGENTS_IMPORT", "BRIDGE_TEXT",
           "imports_agents", "is_bridge", "ignored_paths"]

AGENTS_IMPORT = "@AGENTS.md"
BRIDGE_TEXT = AGENTS_IMPORT + "\n"
_IMPORT_FORMS = (AGENTS_IMPORT, "@./AGENTS.md")

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


def _lines(path: Path) -> list[str] | None:
    try:
        return [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines()]
    except OSError:
        return None


def imports_agents(path: Path) -> bool:
    """이 CLAUDE.md 가 옆의 AGENTS.md 를 가져오는 줄(`@AGENTS.md`)을 가졌나."""
    return any(line in _IMPORT_FORMS for line in _lines(path) or [])


def is_bridge(path: Path) -> bool:
    """가져오는 줄 하나만 있는 CLAUDE.md. ai-ready 가 만든 것과 같아 다시 써도 잃을 것이 없다."""
    lines = [line for line in _lines(path) or [] if line]
    return len(lines) == 1 and lines[0] in _IMPORT_FORMS


def ignored_paths(root: Path, rels: list[str]) -> dict[str, str] | None:
    """rels 중 git 이 무시하는 경로 → 근거(`.gitignore:43: CLAUDE.md`). git 저장소가 아니면 None.

    이미 추적 중인 파일은 무시 규칙에 걸려도 커밋되므로 빠진다(`git check-ignore` 의 기본 동작).
    """
    if not rels:
        return {}
    try:
        r = subprocess.run(["git", "check-ignore", "-v", "-z", "--stdin"], cwd=root,
                           input="\0".join(rels).encode("utf-8") + b"\0", capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode not in (0, 1):
        return None
    fields = r.stdout.decode("utf-8", errors="replace").split("\0")
    out: dict[str, str] = {}
    for i in range(0, len(fields) - 3, 4):
        source, line, pattern, path = fields[i:i + 4]
        if pattern.startswith("!"):
            continue
        out[path] = f"{source}:{line}: {pattern}"
    return out
