#!/usr/bin/env python3
"""ai-ready 가 쓴 파일과 사람이 고친 파일을 가려, 사람 작업을 덮어쓰지 않게 막는 가드.

ai-ready 생성 스크립트(bootstrap.py·scaffold.py)는 대상 파일을 *전체 덮어쓴다*. 생성물은 헤더의 서명 줄에
서명 줄을 뺀 본문의 해시(`body-sha256:` 뒤 12자)를 적는다. 다시 쓸 때 파일은 넷 중 하나다.

  missing  없다 → 새로 만든다
  draft    서명이 있고 본문 해시가 서명의 해시와 같다 → ai-ready 가 쓴 그대로라 다시 써도 잃을 것이 없다
  edited   서명은 있는데 본문 해시가 다르거나 서명에 해시가 없다(옛 초안) → 사람이 고친 초안으로 본다
  human    서명이 없다 → 사람이 관리하는 파일

edited·human 은 덮어쓰지 않는다. `--force` 로만 강제한다. 서명을 남긴 채 TODO 를 채운 초안이 다음 실행에서
통째로 덮이던 일을 막는 것이 해시의 몫이다. 다시 만들고 싶으면 파일을 지우고 돌린다.

문서 구조의 기본값도 여기 둔다. `AGENTS.md` 가 원본(서명이 든 일반 파일)이고, 옆의 `CLAUDE.md` 는
`@AGENTS.md` 한 줄로 그것을 가져온다(이 한 줄짜리 파일을 다리 파일이라 부른다). Claude Code 는 한 폴더에 둘이
있으면 `CLAUDE.md` 만 읽고, 가져오기 경로는 가져오는 파일 기준으로 푼다. 심볼릭 링크는 Windows 클론에서 한
줄짜리 파일로 풀리고 Edit·Write 도구가 링크를 따라 쓰지 않아 쓰지 않는다.

만들 파일이 git 에서 무시되면 커밋되지 않아 저장소에 남지 않는다. `ignored_paths` 가 그것을 쓰기 전에 알린다.
무시되는 것이 다리 파일뿐이면 원본 `AGENTS.md` 는 커밋되므로 멈추지 않고 다리 파일만 건너뛴다.

확인 대화는 스크립트가 하지 않는다 — 결정론·헤드리스 도구이기 때문이다. 대화형 diff 확인은
apply 스킬이 맡고, 이 가드는 "사람이 고친 파일을 말없이 덮어쓰는" 사고만 막는 마지막 장치다.

stdlib-only.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

__all__ = ["is_ai_ready_generated", "draft_state", "sign", "body_hash", "guard_overwrite", "add_force_arg",
           "AGENTS_IMPORT", "BRIDGE_TEXT", "SIGNATURE_MD", "imports_agents", "is_bridge", "is_bridge_path", "ignored_paths",
           "bridge_skip_note"]

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

# bootstrap·scaffold 가 만드는 markdown 초안의 첫 줄. 쓸 때 `sign` 이 본문 해시를 붙인다.
SIGNATURE_MD = ("<!-- ai-ready:apply 자동 생성 초안 — 고치면 이 줄을 남겨 둬도 ai-ready 가 덮어쓰지 않는다. "
                "다시 만들려면 파일을 지우고 apply 를 돌린다 -->")

# 헤더 영역(앞 N줄)만 검사 — 본문에 우연히 들어간 문자열로 인한 오판 방지.
_HEADER_LINES = 15

# 서명 줄에 붙는 본문 해시. 서명 줄을 뺀 본문(줄 끝은 LF 로 맞춘다)의 sha256 앞 12자.
HASH_KEY = "body-sha256:"
_HASH_LEN = 12
_HASH_TOKEN = re.compile(r"\s*·?\s*" + re.escape(HASH_KEY) + r"[0-9a-f]*")
_SIGN_MARK = "ai-ready:apply"


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _signature_index(lines: list[str]) -> int | None:
    """헤더 안에서 서명이 든 첫 줄의 번호."""
    for i, line in enumerate(lines[:_HEADER_LINES]):
        if any(sig in line for sig in AUTO_SIGNATURES) or any(pref in line for pref in AUTO_SIGNATURE_PREFIXES):
            return i
    return None


def is_ai_ready_generated(path: Path) -> bool:
    """파일 헤더에 ai-ready 자동 생성 시그니처가 있으면 True. 본문이 고쳐졌는지는 보지 않는다(`draft_state`)."""
    text = _read_text(path)
    return text is not None and _signature_index(text.splitlines()) is not None


def _lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").split("\n")


def body_hash(text: str) -> str:
    """서명 줄을 뺀 본문의 해시. 서명 줄이 없으면 본문 전체의 해시."""
    lines = _lines(text)
    i = _signature_index(lines)
    if i is not None:
        del lines[i]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:_HASH_LEN]


def _recorded_hash(text: str) -> str | None:
    lines = _lines(text)
    i = _signature_index(lines)
    if i is None:
        return None
    m = re.search(re.escape(HASH_KEY) + r"([0-9a-f]{%d})\b" % _HASH_LEN, lines[i])
    return m.group(1) if m else None


def sign(text: str) -> str:
    """서명 줄에 지금 본문의 해시를 적는다(있던 해시는 바꾼다). `ai-ready:apply` 서명 줄이 없으면 ValueError."""
    lines = _lines(text)
    i = next((n for n, line in enumerate(lines[:_HEADER_LINES]) if _SIGN_MARK in line), None)
    if i is None:
        raise ValueError("서명 줄(ai-ready:apply)이 없는 내용은 서명할 수 없다")
    line = _HASH_TOKEN.sub("", lines[i]).rstrip()
    token = f" · {HASH_KEY}{body_hash(text)}"
    lines[i] = line[:-3].rstrip() + token + " -->" if line.endswith("-->") else line + token
    return "\n".join(lines)


def draft_state(path: Path) -> str:
    """missing · draft(ai-ready 가 쓴 그대로) · edited(서명은 있는데 본문이 바뀌었거나 해시가 없다) · human(서명 없음)."""
    if not path.exists():
        return "missing"
    text = _read_text(path)
    if text is None or _signature_index(text.splitlines()) is None:
        return "human"
    recorded = _recorded_hash(text)
    return "draft" if recorded is not None and recorded == body_hash(text) else "edited"


def edited_reason(path: Path) -> str:
    """edited 인 초안을 왜 고친 것으로 보는지 한 줄."""
    text = _read_text(path) or ""
    if _recorded_hash(text) is None:
        return "초안이 고쳐졌다고 본다 — 서명에 본문 해시가 없는 옛 초안이라 고쳤는지 알 수 없다"
    return "초안이 고쳐졌다 — 서명의 본문 해시와 지금 본문이 다르다"


def guard_overwrite(out_path: Path, force: bool = False) -> bool:
    """덮어써도 되는지 판정. 안전하면 True, 막아야 하면 False (+ 안내 stderr).

    - 파일 없음·ai-ready 가 쓴 그대로의 초안 → True
    - 고친 초안·서명 없는 파일 → force 면 True (+ 경고), 아니면 False (+ 안내)
    """
    state = draft_state(out_path)
    if state in ("missing", "draft"):
        return True
    if state == "edited":
        what = edited_reason(out_path)
        if force:
            print(f"경고: {out_path} — {what}. --force 로 덮어쓴다.", file=sys.stderr)
            return True
        print(f"중단: {out_path} — {what}. 덮어쓰지 않는다.\n"
              f"  고친 내용을 두려면 이 파일은 apply 스킬에서 diff 로 고친다. 다시 만들려면 파일을 지우고 돌린다.",
              file=sys.stderr)
        return False
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
        help="사람이 관리하는 문서·고친 초안·심볼릭 링크·git 이 무시하는 경로도 덮어쓰기 강제",
    )


def _stripped_lines(path: Path) -> list[str] | None:
    text = _read_text(path)
    return None if text is None else [line.strip() for line in text.splitlines()]


def imports_agents(path: Path) -> bool:
    """이 CLAUDE.md 가 옆의 AGENTS.md 를 가져오는 줄(`@AGENTS.md`)을 가졌나."""
    return any(line in _IMPORT_FORMS for line in _stripped_lines(path) or [])


def is_bridge(path: Path) -> bool:
    """가져오는 줄 하나만 있는 CLAUDE.md. ai-ready 가 만든 것과 같아 다시 써도 잃을 것이 없다."""
    lines = [line for line in _stripped_lines(path) or [] if line]
    return len(lines) == 1 and lines[0] in _IMPORT_FORMS


def is_bridge_path(rel: str) -> bool:
    """ai-ready 가 이 경로에 쓰는 것이 다리 파일(`@AGENTS.md` 한 줄짜리 CLAUDE.md)인가. 원본은 늘 AGENTS.md 다."""
    return Path(rel).name == "CLAUDE.md"


def bridge_skip_note(root_claude_committed: bool) -> str:
    """무시되는 다리 파일만 건너뛸 때 사람에게 남기는 안내."""
    note = ("참고: git 이 무시하는 것은 `@AGENTS.md` 한 줄짜리 CLAUDE.md 뿐이라 그 파일만 건너뛰고 나머지는 쓴다. "
            "원본 AGENTS.md 는 커밋된다. Claude Code v2.1.277 이상은 작업 폴더와 그 위에 CLAUDE.md 가 없으면 "
            "AGENTS.md 를 읽는다. 로컬에 개인 CLAUDE.md 나 CLAUDE.local.md 가 있는 사람은 거기에 `@AGENTS.md` 를 "
            "넣거나, `/config` 의 Project instructions 를 `claude-md-and-agents-md` 로 바꿔 둘 다 읽게 해야 "
            "AGENTS.md 가 로드된다(프로젝트 설정 파일에서는 이 값을 무시한다).")
    if root_claude_committed:
        note += ("\n  주의: 루트 CLAUDE.md 가 있고 git 이 무시하지 않는다. 기본 설정의 Claude Code 는 작업 폴더나 그 위에 CLAUDE.md 가 "
                 "있으면 하위 폴더의 AGENTS.md 를 읽지 않는다(https://code.claude.com/docs/en/memory). 모듈 AGENTS.md 를 "
                 "다른 사람도 읽게 하려면 모듈 CLAUDE.md 를 커밋할지 사람이 정한다.")
    return note


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
