#!/usr/bin/env python3
"""대상 저장소의 `.claude/settings.json` 에 Stop hook 으로 `scripts/verify.sh --stop-hook` 을 건다.

- 기존 settings.json 의 다른 키와 다른 hook 은 그대로 둔다.
- 이미 걸려 있으면 아무것도 바꾸지 않는다(여러 번 돌려도 결과가 같다).
- settings.json 이 JSON 으로 읽히지 않으면 쓰지 않고 exit 1.
- `scripts/verify.sh` 가 없으면 걸지 않고 exit 1 — 없는 스크립트를 가리키는 hook 은 매 턴 헛돈다.
- `--uninstall` 은 이 hook 만 뺀다.

Claude Code 전용이다(codex 번들에는 없다). 사람이 승인한 뒤 명시적으로 실행한다.

  python3 install_verify_hook.py --target <repo> [--dry-run] [--uninstall] [--timeout 600]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HOOK_COMMAND = 'bash "$CLAUDE_PROJECT_DIR/scripts/verify.sh" --stop-hook'
VERIFY_REL = Path("scripts/verify.sh")
DEFAULT_TIMEOUT = 600  # 초. 테스트가 hook 기본 제한 시간보다 오래 걸리면 hook 이 중간에 끊긴다.


def _is_ours(hook: object) -> bool:
    return isinstance(hook, dict) and "scripts/verify.sh" in str(hook.get("command", "")) \
        and "--stop-hook" in str(hook.get("command", ""))


def load(settings_path: Path) -> dict:
    if not settings_path.exists():
        return {}
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("최상위가 객체가 아니다")
    return data


def installed(data: dict) -> bool:
    for group in (data.get("hooks") or {}).get("Stop") or []:
        if isinstance(group, dict) and any(_is_ours(h) for h in group.get("hooks") or []):
            return True
    return False


def install(data: dict, timeout: int) -> dict:
    if installed(data):
        return data
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("`hooks` 가 객체가 아니다")
    stop = hooks.setdefault("Stop", [])
    if not isinstance(stop, list):
        raise ValueError("`hooks.Stop` 이 배열이 아니다")
    stop.append({"hooks": [{"type": "command", "command": HOOK_COMMAND, "timeout": timeout}]})
    return data


def uninstall(data: dict) -> dict:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict) or not isinstance(hooks.get("Stop"), list):
        return data
    kept = []
    for group in hooks["Stop"]:
        if isinstance(group, dict) and isinstance(group.get("hooks"), list):
            rest = [h for h in group["hooks"] if not _is_ours(h)]
            if not rest:
                continue
            group = {**group, "hooks": rest}
        kept.append(group)
    if kept:
        hooks["Stop"] = kept
    else:
        del hooks["Stop"]
    if not hooks:
        del data["hooks"]
    return data


def dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="verify.sh 를 Claude Code Stop hook 으로 건다")
    ap.add_argument("--target", required=True)
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 결과 settings.json 을 보여 준다")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="hook 제한 시간(초)")
    args = ap.parse_args()

    target = Path(args.target).resolve()
    settings_path = target / ".claude" / "settings.json"
    if not args.uninstall and not (target / VERIFY_REL).is_file():
        print(f"중단: {target / VERIFY_REL} 가 없다. verify.sh 를 먼저 만든다.", file=sys.stderr)
        return 1
    try:
        data = load(settings_path)
    except ValueError as e:  # json.JSONDecodeError 도 ValueError 다
        print(f"중단: {settings_path} 를 읽지 못해 건드리지 않는다 ({e})", file=sys.stderr)
        return 1

    before = dump(data)
    try:
        after_data = uninstall(data) if args.uninstall else install(data, args.timeout)
    except ValueError as e:
        print(f"중단: {settings_path} 구조가 예상과 다르다 ({e})", file=sys.stderr)
        return 1
    after = dump(after_data)

    if after == before:
        print("변경 없음: " + ("걸린 hook 이 없다" if args.uninstall else "이미 걸려 있다"))
        return 0
    if args.dry_run:
        sys.stdout.write(after)
        return 0
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(after, encoding="utf-8")
    print(("뺐다: " if args.uninstall else "걸었다: ") + f"{settings_path} Stop hook → {HOOK_COMMAND}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
