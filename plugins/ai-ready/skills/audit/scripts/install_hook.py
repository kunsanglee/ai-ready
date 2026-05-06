#!/usr/bin/env python3
"""
freshness Stop hook을 대상 프로젝트의 .claude/settings.json에 추가.

기존 settings.json이 있으면 보존하면서 hooks.Stop 배열에 추가합니다 (idempotent).
이미 설치되어 있으면 아무것도 하지 않습니다.

ROI 액션 매핑: "freshness Stop hook 설치" (Rule 6.1, +5점).

실행:
  python3 install_hook.py --target /path/to/repo
  python3 install_hook.py --target /path/to/repo --uninstall
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HOOK_COMMAND = "$CLAUDE_PLUGIN_ROOT/skills/audit/hooks/freshness_check.sh"


def is_freshness_hook(entry: dict) -> bool:
    """이 hook entry가 우리 freshness hook인지 확인."""
    marker = "ai-ready/skills/audit/hooks/freshness_check"
    for h in entry.get("hooks", []):
        cmd = h.get("command", "") or ""
        if marker in cmd:
            return True
    return False


def install(target: Path) -> str:
    settings_path = target / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return f"오류: settings.json JSON 파싱 실패 — {e}"
    else:
        settings = {}

    hooks = settings.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])

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
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return f"오류: settings.json JSON 파싱 실패 — {e}"

    hooks = settings.get("hooks", {})
    stop_hooks = hooks.get("Stop", [])
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
