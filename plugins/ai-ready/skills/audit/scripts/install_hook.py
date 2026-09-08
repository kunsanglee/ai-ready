#!/usr/bin/env python3
"""
freshness Stop hook을 대상 프로젝트의 .claude/settings.json에 추가.

기존 settings.json이 있으면 보존하면서 hooks.Stop 배열에 추가합니다 (idempotent).
이미 같은 명령이 있으면 아무것도 하지 않고, 옛 판의 명령이 있으면 지금 명령으로 갱신합니다.

ROI 규칙 (audit 의 규칙 이름 그대로 — 번호가 아니라 이름으로 가리킨다):
  - "CLAUDE.md / 문서 갱신 훅 또는 스케줄 존재" (+5점)

실행:
  python3 install_hook.py --target /path/to/repo
  python3 install_hook.py --target /path/to/repo --uninstall
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 프로젝트 settings.json 의 Stop hook 은 *프로젝트 컨텍스트*에서 실행돼 $CLAUDE_PROJECT_DIR 만
# 안정적으로 해석된다($CLAUDE_PLUGIN_ROOT 는 플러그인 자기 hook 에만 보장 — 프로젝트 hook 에선 미해석).
# audit.py 가 freshness_check.sh 를 <target>/.ai-ready/hooks/ 로 복사하므로 그 경로를 가리킨다.
# 경로 문자열은 여기 한 곳에서만 나온다(단일 경로) — SKILL.md "Installing the Freshness Hook"
# 스니펫과 복사본 헤더가 같은 문자열을 적으므로, 바꿀 때 그 둘도 같이 고친다.
HOOK_SCRIPT_RELPATH = ".ai-ready/hooks/freshness_check.sh"
HOOK_SCRIPT_PATH = f"$CLAUDE_PROJECT_DIR/{HOOK_SCRIPT_RELPATH}"

# 스크립트를 바로 부르지 않고 존재 가드로 감싼다. 파일이 없으면 매 턴 끝에
# `/bin/sh: …/freshness_check.sh: No such file or directory` 가 찍히는데, 두 경우에 난다:
#   ① 세션을 저장소 루트가 아니라 부모 폴더에서 열어 $CLAUDE_PROJECT_DIR 이 저장소 밖을 가리킬 때
#      (2026-09-08 실측 — 대상 프로젝트에서 매 턴 소음이 나 사용자가 훅 항목을 통째로 뺐다)
#   ② audit.py 가 스크립트를 <target>/.ai-ready/hooks/ 로 복사하기 전에 install_hook.py 만 돌았거나
#      그 폴더가 지워졌을 때
# 조용히 넘기는 까닭: 이 훅은 non-blocking 이라 오류가 나도 막는 것이 없고 소음만 남는다.
# 경고할 사람이 볼 자리는 install() 의 반환 문구다(설치 시점에 한 번).
#
# sh 로 실행되므로 bash 전용 문법을 쓰지 않는다. 경로는 따옴표로 감싸 공백에 안전하고,
# $CLAUDE_PROJECT_DIR 이 비어 있으면 `/.ai-ready/...` 가 되어 -x 가 거짓 → exit 0 이다.
# exec 로 넘겨 훅 JSON 이 실린 stdin 을 스크립트가 그대로 받는다.
# 경로를 두 번 적는 것은 audit 채점(_command_missing_scripts)이 공백으로 자른 토큰 하나를
# 경로로 읽기 때문이다 — `f="…"` 꼴로 묶으면 대입 기호까지 경로에 붙어 실재하는 스크립트를
# 없다고 읽는다.
HOOK_COMMAND = f'[ -x "{HOOK_SCRIPT_PATH}" ] && exec "{HOOK_SCRIPT_PATH}"; exit 0'


def is_freshness_hook(entry: dict) -> bool:
    """이 hook entry가 우리 freshness hook인지 확인."""
    # marker 는 신·구 경로 양쪽을 잡도록 공통 꼬리로 둔다 — 새 경로
    # ($CLAUDE_PROJECT_DIR/.ai-ready/hooks/...)와 옛 경로($CLAUDE_PLUGIN_ROOT/skills/audit/hooks/...)
    # 둘 다 인식해 멱등성·제거(옛 설치분 정리 포함)가 깨지지 않게 한다.
    if not isinstance(entry, dict):
        return False
    marker = "hooks/freshness_check"
    hooks = entry.get("hooks", [])
    if not isinstance(hooks, list):
        return False
    for h in hooks:
        if not isinstance(h, dict):
            continue
        cmd = h.get("command", "") or ""
        if marker in cmd:
            return True
    return False


def script_absence_note(target: Path) -> str:
    """훅이 가리키는 스크립트가 아직 없으면 덧붙일 안내(있으면 빈 문자열).

    install_hook.py 는 audit.py 없이도 돌 수 있어, 스크립트가 복사되기 전에 훅만 심기는 상태가
    정상적으로 생긴다. 그 상태는 오류가 아니라 대기라서 설치는 그대로 하고 말로만 알린다.
    """
    if (target / HOOK_SCRIPT_RELPATH).is_file():
        return ""
    return (f" (주의: {HOOK_SCRIPT_RELPATH} 가 아직 없다 — audit.py 를 먼저 돌려 복사하라."
            " 그전까지 훅은 조용히 지나간다)")


def install(target: Path) -> str:
    settings_path = target / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as e:
            return f"오류: settings.json 읽기/파싱 실패 — {e}"
    else:
        settings = {}

    # 손상된 settings 형식 방어: hooks 가 dict 가, Stop 이 list 가 아니면 빈 것으로 시작한다
    # (잘못된 타입에 setdefault/append 를 부르면 AttributeError 로 크래시).
    if not isinstance(settings, dict):
        settings = {}
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks
    stop_hooks = hooks.get("Stop")
    if not isinstance(stop_hooks, list):
        stop_hooks = []
        hooks["Stop"] = stop_hooks

    # 이미 설치됐는지 확인. 있으면 그 명령이 지금 판인지까지 본다 — 1.5.7 이전 설치분은
    # 스크립트를 가드 없이 바로 부르는 옛 명령이라, 스크립트가 없으면 매 턴 끝에 오류를 찍는다.
    # 여기서 갱신하지 않으면 실측 결함을 겪은 바로 그 설치분이 업그레이드 후에도 그대로 남는다
    # (apply 스킬이 이 스크립트를 그 규칙의 처방으로 다시 돌리므로 그때가 유일한 갱신 기회다).
    for entry in stop_hooks:
        if not is_freshness_hook(entry):
            continue
        stale = [h for h in entry.get("hooks", [])
                 if isinstance(h, dict)
                 and "hooks/freshness_check" in (h.get("command") or "")
                 and h.get("command") != HOOK_COMMAND]
        if not stale:
            return "이미 설치됨 — 변경 없음" + script_absence_note(target)
        for h in stale:
            h["command"] = HOOK_COMMAND
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
        return f"명령 갱신함(존재 가드 추가): {settings_path}" + script_absence_note(target)

    # 새 entry 추가
    stop_hooks.append({
        "matcher": ".*",
        "hooks": [{"type": "command", "command": HOOK_COMMAND}],
    })
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    return f"설치 완료: {settings_path}" + script_absence_note(target)


def uninstall(target: Path) -> str:
    settings_path = target / ".claude" / "settings.json"
    if not settings_path.exists():
        return "settings.json 없음 — 변경 없음"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        return f"오류: settings.json 읽기/파싱 실패 — {e}"

    if not isinstance(settings, dict):
        return "settings.json 형식이 object 아님 — 변경 없음"
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return "hooks 형식이 dict 아님 — 변경 없음"
    stop_hooks = hooks.get("Stop", [])
    if not isinstance(stop_hooks, list):
        return "Stop hooks 형식이 list 아님 — 변경 없음"
    before_len = len(stop_hooks)
    new_stop_hooks = [e for e in stop_hooks if not is_freshness_hook(e)]
    if len(new_stop_hooks) == before_len:
        return "freshness hook 미설치 — 변경 없음"

    if new_stop_hooks:
        hooks["Stop"] = new_stop_hooks
    else:
        hooks.pop("Stop", None)
        if not hooks:
            settings.pop("hooks", None)

    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    return f"제거 완료: {settings_path}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--uninstall", action="store_true", help="freshness hook 제거")
    args = ap.parse_args()
    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"오류: 대상이 디렉토리가 아님: {target}", file=sys.stderr)
        sys.exit(2)
    msg = uninstall(target) if args.uninstall else install(target)
    print(msg)


if __name__ == "__main__":
    main()
