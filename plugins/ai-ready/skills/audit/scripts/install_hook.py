#!/usr/bin/env python3
"""
freshness Stop hook을 대상 프로젝트의 .claude/settings.json에 추가.

기존 settings.json이 있으면 보존하면서 hooks.Stop 배열에 추가합니다 (idempotent).
이미 설치되어 있으면 아무것도 하지 않습니다.

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
# 이 경로는 SKILL.md "Installing the Freshness Hook" + 복사본 헤더와 동일해야 한다(단일 경로).
HOOK_COMMAND = "$CLAUDE_PROJECT_DIR/.ai-ready/hooks/freshness_check.sh"


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

    # 이미 설치됐는지 확인
    for entry in stop_hooks:
        if is_freshness_hook(entry):
            return "이미 설치됨 — 변경 없음"

    # 새 entry 추가
    stop_hooks.append({
        "matcher": ".*",
        "hooks": [{"type": "command", "command": HOOK_COMMAND}],
    })
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    return f"설치 완료: {settings_path}"


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
