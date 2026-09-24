#!/usr/bin/env python3
"""대상 저장소의 `.claude/settings.json` 에 Stop hook 으로 `scripts/verify.sh --stop-hook` 을 건다.

- 기존 settings.json 의 다른 키와 다른 hook 은 그대로 둔다.
- 이미 걸려 있으면 아무것도 바꾸지 않는다(여러 번 돌려도 결과가 같다).
- settings.json 이 JSON 으로 읽히지 않으면 쓰지 않고 exit 1.
- `scripts/verify.sh` 가 없으면 걸지 않고 exit 1 — 없는 스크립트를 가리키는 hook 은 매 턴 헛돈다.
- verify.sh 의 통과 기록(`git rev-parse --git-path verify-pass` 파일)이 없거나, Stop hook 실행의 실패 기록
  (`verify-fail` 파일)이 있으면 걸지 않고 exit 4. verify.sh 는 실패하면 통과 기록을 지우므로, 통과한 뒤 커밋으로
  깨진 저장소도 여기서 걸린다. 이미 실패하는 검사를 hook 으로 걸면 에이전트가 턴을 끝내려고 이번 작업과 무관한
  기존 위반을 고치며 운영 코드를 바꾼다. `--force` 로만 무시한다.
- `--uninstall` 은 이 hook 만 뺀다.

Claude Code 전용이다(codex 번들에는 없다). 사람이 승인한 뒤 명시적으로 실행한다.

  python3 install_verify_hook.py --target <repo> [--dry-run] [--uninstall] [--force] [--timeout 600]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HOOK_COMMAND = 'bash "$CLAUDE_PROJECT_DIR/scripts/verify.sh" --stop-hook'
VERIFY_REL = Path("scripts/verify.sh")
DEFAULT_TIMEOUT = 600  # 초. 테스트가 hook 기본 제한 시간보다 오래 걸리면 hook 이 중간에 끊긴다.

EXIT_OK = 0
EXIT_FAILED = 1        # verify.sh 가 없거나 settings.json 을 읽지 못했다
EXIT_NOT_PASSED = 4    # verify.sh 의 통과 기록이 없거나 마지막 Stop hook 실행이 실패했다


def pass_marker(target: Path, name: str = "verify-pass") -> Path | None:
    """verify.sh 가 남기는 기록 파일(통과 지문 `verify-pass`, 실패 지문 `verify-fail`). git 저장소가 아니면 None."""
    try:
        r = subprocess.run(["git", "rev-parse", "--git-path", name], cwd=target,
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return target / r.stdout.strip()


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


def run(args: argparse.Namespace) -> int:
    target = Path(args.target).resolve()
    settings_path = target / ".claude" / "settings.json"
    if not args.uninstall and not (target / VERIFY_REL).is_file():
        print(f"중단: {target / VERIFY_REL} 가 없다. verify.sh 를 먼저 만든다.", file=sys.stderr)
        return EXIT_FAILED
    if not args.uninstall:
        marker = pass_marker(target)
        failed = pass_marker(target, "verify-fail")
        if failed is not None and failed.is_file():
            if not args.force:
                print("중단: scripts/verify.sh 의 마지막 Stop hook 실행이 실패했다(verify-fail 기록이 있다).\n"
                      "  scripts/verify.sh 를 다시 돌려 통과시킨 뒤 건다. 기존 위반 때문에 통과하지 못하면 위반 목록을\n"
                      "  사람에게 보고하고 기준선(baseline) 방식으로 묶을지 정한다. 그래도 걸려면 --force.",
                      file=sys.stderr)
                return EXIT_NOT_PASSED
            print("경고: verify.sh 실패 기록이 있지만 --force 로 건다.", file=sys.stderr)
        if marker is None or not marker.is_file():
            if not args.force:
                print("중단: scripts/verify.sh 의 통과 기록이 없다 — 아직 통과하지 않았거나 마지막 실행이 실패했다"
                      + (" (git 저장소가 아니라 통과 기록을 확인할 수 없다)" if marker is None else "") + ".\n"
                      "  이 상태로 hook 을 걸면 에이전트가 턴을 끝내려고 이번 작업과 무관한 기존 위반을 고친다.\n"
                      "  먼저 scripts/verify.sh 를 돌려 통과시킨다. 기존 위반 때문에 통과하지 못하면 위반 목록을 사람에게\n"
                      "  보고하고 기준선(baseline) 방식으로 묶을지 정한다. 그래도 걸려면 --force.",
                      file=sys.stderr)
                return EXIT_NOT_PASSED
            print("경고: verify.sh 통과 기록이 없지만 --force 로 건다.", file=sys.stderr)
    try:
        data = load(settings_path)
    except ValueError as e:  # json.JSONDecodeError 도 ValueError 다
        print(f"중단: {settings_path} 를 읽지 못해 건드리지 않는다 ({e})", file=sys.stderr)
        return EXIT_FAILED

    before = dump(data)
    try:
        after_data = uninstall(data) if args.uninstall else install(data, args.timeout)
    except ValueError as e:
        print(f"중단: {settings_path} 구조가 예상과 다르다 ({e})", file=sys.stderr)
        return EXIT_FAILED
    after = dump(after_data)

    if after == before:
        print("변경 없음: " + ("걸린 hook 이 없다" if args.uninstall else "이미 걸려 있다"))
        return EXIT_OK
    if args.dry_run:
        sys.stdout.write(after)
        return EXIT_OK
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(after, encoding="utf-8")
    print(("뺐다: " if args.uninstall else "걸었다: ") + f"{settings_path} Stop hook → {HOOK_COMMAND}")
    return EXIT_OK


def main() -> int:
    ap = argparse.ArgumentParser(description="verify.sh 를 Claude Code Stop hook 으로 건다")
    ap.add_argument("--target", required=True)
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 결과 settings.json 을 보여 준다")
    ap.add_argument("--force", action="store_true", help="verify.sh 통과 기록이 없어도 건다")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="hook 제한 시간(초)")
    rc = run(ap.parse_args())
    if rc != EXIT_OK:
        print(f"종료 코드 {rc}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
