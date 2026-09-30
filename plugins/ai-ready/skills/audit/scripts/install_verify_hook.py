#!/usr/bin/env python3
"""대상 clone 에 git pre-push hook(`project/pre-push`)을 설치한다. 그 hook 은 push 하는 커밋이 지금 체크아웃(HEAD)일
때 `scripts/verify.sh` 를 돌리고, 실패하면 push 를 막는다.

- 먼저 2.0 이 `.claude/settings.json` 에 건 Stop hook(명령에 `verify.sh` 와 `--stop-hook` 이 함께 든 항목)을 지운다.
  `--target` 과 저장소 최상위의 settings.json 을 둘 다 본다(같은 파일이면 한 번). 다른 키·다른 hook 은 그대로 둔다.
  아래 이유로 설치를 거절할 때도 이 정리는 한다. settings.json 이 JSON 으로 읽히지 않으면 손대지 않고 경고만 한다.
- 설치 자리는 `git rev-parse --git-path hooks/pre-push` 다. 연결 워크트리에서 불러도 공통 git 폴더의 hooks 에
  들어가 그 clone 의 모든 워크트리에 걸린다. hook 은 clone 마다 따로 걸고 커밋되지 않는다.
- `core.hooksPath` 가 설정돼 있으면 쓰지 않고 exit 1. husky·lefthook 같은 도구가 관리하는 폴더일 수 있다.
  값이 git 기본 hooks 폴더(공통 git 폴더의 hooks)를 가리키면 설정이 없는 것과 같이 다룬다. 그 값이 상대 경로면
  연결 워크트리에서는 hook 이 돌지 않으므로 설치를 마칠 때 알린다.
- 같은 자리에 심볼릭 링크(가리키는 파일이 없어도)나 ai-ready 표시가 없는 pre-push 가 있으면 쓰지 않고 exit 1.
  표시가 있으면 내용이 같을 때 그대로 두고, 다르면 새 내용으로 바꾼다(여러 번 돌려도 결과가 같다).
- git 저장소가 아니거나 저장소 최상위(`git rev-parse --show-toplevel`)에 `scripts/verify.sh` 가 없으면 exit 1.
  hook 이 부르는 자리와 같다. verify.sh 의 통과 기록(`git rev-parse --git-path verify-pass` 파일)이 없으면 exit 4.
  verify.sh 는 실패하면 통과 기록을 지우므로, 통과한 뒤 커밋으로 깨진 저장소도 여기서 걸린다. 이미 실패하는 검사를
  걸면 push 가 막혀, 이번 작업과 무관한 기존 위반을 고치려고 운영 코드를 바꾸게 된다.
- `--uninstall` 은 ai-ready 표시가 있는 pre-push 와 옛 Stop hook 만 지운다. `core.hooksPath` 가 설정돼 있으면 hook
  자리는 건드리지 않는다.

사람이 승인한 뒤 명시적으로 실행한다.

  python3 install_verify_hook.py --target <repo> [--dry-run] [--uninstall]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent / "project" / "pre-push"
MARK = "ai-ready:apply"  # 설치한 hook 첫머리의 표시. 이 표시가 있는 pre-push 만 바꾸거나 지운다.
HEADER_LINES = 5
VERIFY_REL = Path("scripts/verify.sh")
SETTINGS_REL = Path(".claude/settings.json")
ADD_LINE = "bash scripts/verify.sh </dev/null || exit 1"
REPO_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")

EXIT_OK = 0
EXIT_FAILED = 1        # git 저장소가 아니다 · verify.sh 가 없다 · core.hooksPath 가 있다 · 다른 pre-push·링크가 있다
EXIT_NOT_PASSED = 4    # verify.sh 의 통과 기록이 없다


def _git(target: Path, *args: str) -> subprocess.CompletedProcess | None:
    # 부른 쪽이 저장소를 가리키는 변수를 export 해 두면 git 은 --target 대신 그 저장소를 본다. 자식 환경에서 뺀다.
    env = {k: v for k, v in os.environ.items() if k not in REPO_ENV}
    try:
        return subprocess.run(["git", *args], cwd=target, env=env, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None


def git_path(target: Path, name: str) -> Path | None:
    """`git rev-parse --git-path <name>` 이 가리키는 자리. 워크트리·core.hooksPath 를 따라 푼다. git 저장소가 아니면 None."""
    r = _git(target, "rev-parse", "--git-path", name)
    if r is None or r.returncode != 0 or not r.stdout.strip():
        return None
    # 하위 폴더에서 부르면 `../.git/hooks/pre-push` 꼴로 온다. 링크는 따라가지 않고 `..` 만 정리한다.
    return Path(os.path.normpath(target / r.stdout.strip()))


def toplevel(target: Path) -> Path | None:
    """작업 트리 최상위. hook 은 여기서 scripts/verify.sh 를 찾는다. 작업 트리가 없으면 None."""
    r = _git(target, "rev-parse", "--show-toplevel")
    if r is None or r.returncode != 0 or not r.stdout.strip():
        return None
    return Path(r.stdout.strip())


def _points_to_default_hooks(target: Path) -> bool:
    """core.hooksPath 가 git 기본 hooks 폴더(공통 git 폴더의 hooks)를 가리키는지. `--git-path hooks` 는 설정값을 git 이
    hook 을 찾는 규칙대로 푼다(상대 경로는 작업 트리 최상위 기준, `~` 는 펼친다)."""
    configured = _git(target, "rev-parse", "--git-path", "hooks")
    common = _git(target, "rev-parse", "--git-common-dir")
    if any(r is None or r.returncode != 0 or not r.stdout.strip() for r in (configured, common)):
        return False
    return (os.path.realpath(target / configured.stdout.strip())
            == os.path.realpath(target / common.stdout.strip() / "hooks"))


def relative_hooks_path(target: Path) -> str:
    """core.hooksPath 가 상대 경로면 그 값, 설정이 없거나 절대 경로(`~` 는 펼친 뒤)면 빈 문자열. 연결 워크트리는 상대
    값을 자기 작업 트리 기준으로 풀어 공통 hooks 의 hook 을 돌리지 않는다."""
    r = _git(target, "config", "--type=path", "--get", "core.hooksPath")
    if r is None or r.returncode != 0 or not r.stdout.strip():
        return ""
    value = r.stdout.strip()
    return "" if os.path.isabs(value) else value


def hooks_path_setting(target: Path) -> tuple[str, str] | None:
    """설정된 core.hooksPath 의 (값, 출처). 없거나 git 기본 hooks 폴더를 가리키면 None — 그때 git 은 설정이 없을 때와
    같은 자리의 hook 을 돌린다. 빈 값이면 값이 빈 문자열이다(git 이 hook 을 찾지 못한다)."""
    r = _git(target, "config", "--show-origin", "--get", "core.hooksPath")
    if r is None or r.returncode != 0 or not r.stdout.strip():
        return None
    if _points_to_default_hooks(target):
        return None
    origin, _, value = r.stdout.rstrip("\n").partition("\t")
    return value, origin


UNSET_HOOKS_PATH = "git config --unset core.hooksPath"


def is_ours(path: Path) -> bool:
    if path.is_symlink():
        return False
    try:
        head = path.read_text(encoding="utf-8", errors="replace").splitlines()[:HEADER_LINES]
    except OSError:
        return False
    return any(MARK in line for line in head)


def _is_old_stop_hook(hook: object) -> bool:
    command = str(hook.get("command", "")) if isinstance(hook, dict) else ""
    return "verify.sh" in command and "--stop-hook" in command


def drop_old_stop_hook(data: dict) -> list[str]:
    """data 에서 옛 Stop hook 항목을 빼고 뺀 명령 목록을 돌려준다. 비게 된 그룹·배열·`hooks` 객체도 뺀다."""
    hooks = data.get("hooks")
    if not isinstance(hooks, dict) or not isinstance(hooks.get("Stop"), list):
        return []
    removed: list[str] = []
    kept = []
    for group in hooks["Stop"]:
        if isinstance(group, dict) and isinstance(group.get("hooks"), list):
            ours = [h for h in group["hooks"] if _is_old_stop_hook(h)]
            if ours:
                removed += [str(h["command"]) for h in ours]
                rest = [h for h in group["hooks"] if not _is_old_stop_hook(h)]
                if not rest:
                    continue
                group = {**group, "hooks": rest}
        kept.append(group)
    if not removed:
        return []
    if kept:
        hooks["Stop"] = kept
    else:
        del hooks["Stop"]
    if not hooks:
        del data["hooks"]
    return removed


def settings_files(target: Path) -> list[Path]:
    """옛 Stop hook 을 찾을 settings.json. `--target` 과 저장소 최상위의 것을 보고, 같은 파일이면 한 번만 본다."""
    out: list[Path] = []
    seen: set[Path] = set()
    for base in (target, toplevel(target)):
        if base is None:
            continue
        path = base / SETTINGS_REL
        if path.resolve() not in seen:
            seen.add(path.resolve())
            out.append(path)
    return out


def _plan_settings(path: Path) -> tuple[dict | None, list[str]]:
    """(옛 Stop hook 을 뺀 settings, 뺀 명령). 뺄 것이 없거나 읽지 못하면 (None, [])."""
    if not path.is_file():
        return None, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:  # json.JSONDecodeError 도 ValueError 다
        print(f"경고: {path} 를 JSON 으로 읽지 못해 옛 Stop hook 을 확인하지 않았다 ({e}). 파일은 그대로 둔다.",
              file=sys.stderr)
        return None, []
    if not isinstance(data, dict):
        print(f"경고: {path} 의 최상위가 객체가 아니라 옛 Stop hook 을 확인하지 않았다. 파일은 그대로 둔다.", file=sys.stderr)
        return None, []
    removed = drop_old_stop_hook(data)
    return (data, removed) if removed else (None, [])


def _tracked(path: Path) -> bool:
    r = _git(path.parent, "ls-files", "--error-unmatch", "--", path.name)
    return r is not None and r.returncode == 0


def clean_settings(target: Path, dry_run: bool) -> None:
    """옛 Stop hook 을 settings.json 에서 지운다. dry_run 이면 지울 항목만 보여 준다."""
    for path in settings_files(target):
        settings, removed = _plan_settings(path)
        if not removed:
            continue
        if dry_run:
            for command in removed:
                print(f"{path} 에서 지울 옛 Stop hook: {command}")
            continue
        path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for command in removed:
            print(f"뺐다: {path} 의 옛 Stop hook — {command}")
        if _tracked(path):
            print(f"  {path} 은 git 이 추적하는 파일이라 이 변경을 커밋해야 한다.")


def _refuse_install(target: Path, hook: Path) -> int:
    """설치를 막는 이유가 있으면 알리고 종료 코드를, 없으면 EXIT_OK 를 돌려준다."""
    top = toplevel(target)
    if top is None:
        print(f"중단: {target} 에 작업 트리가 없다. pre-push hook 은 작업 트리의 scripts/verify.sh 를 부른다.",
              file=sys.stderr)
        return EXIT_FAILED
    if not (top / VERIFY_REL).is_file():
        print(f"중단: {top / VERIFY_REL} 가 없다. hook 은 저장소 최상위의 이 파일을 부른다. verify.sh 를 먼저 만든다.",
              file=sys.stderr)
        return EXIT_FAILED
    setting = hooks_path_setting(target)
    if setting and not setting[0]:
        print(f"중단: core.hooksPath 가 빈 값이다 — git 이 hook 을 찾지 못해 pre-push 가 돌지 않는다. "
              f"`{UNSET_HOOKS_PATH}` 로 지운 뒤 다시 돌린다 ({setting[1]})", file=sys.stderr)
        return EXIT_FAILED
    if setting:
        print(f"중단: core.hooksPath 가 설정돼 있다 ({setting[0]} ({setting[1]})). git 은 그 폴더의 hook 을 돌린다.\n"
              "  husky·lefthook 같은 도구가 관리하는 폴더일 수 있어 쓰지 않는다. 그 도구의 pre-push 설정에\n"
              "  아래 한 줄을 직접 넣는다(hook 은 저장소 루트에서 돈다):\n"
              f"    {ADD_LINE}", file=sys.stderr)
        return EXIT_FAILED
    if hook.is_symlink():
        print(f"중단: {hook} 가 심볼릭 링크다(→ {os.readlink(hook)}). 쓰면 링크가 가리키는 파일을 덮거나 새로 만들게\n"
              "  되어 쓰지 않는다. 그 파일에 아래 한 줄을 직접 더하거나, 링크를 치운 뒤 다시 돌린다:\n"
              f"    {ADD_LINE}", file=sys.stderr)
        return EXIT_FAILED
    if hook.exists() and not is_ours(hook):
        print(f"중단: {hook} 에 ai-ready 가 설치하지 않은 pre-push hook 이 있다. 덮어쓰지 않는다.\n"
              "  그 hook 에 아래 한 줄을 직접 더한다(hook 은 저장소 루트에서 돈다):\n"
              f"    {ADD_LINE}", file=sys.stderr)
        return EXIT_FAILED
    marker = git_path(target, "verify-pass")
    if marker is None or not marker.is_file():
        print("중단: scripts/verify.sh 의 통과 기록이 없다 — 아직 통과하지 않았거나 마지막 실행이 실패했다.\n"
              "  이 상태로 hook 을 걸면 push 가 막혀, 이번 작업과 무관한 기존 위반을 고치려고 운영 코드를 바꾸게 된다.\n"
              "  먼저 scripts/verify.sh 를 돌려 통과시킨다. 기존 위반 때문에 통과하지 못하면 위반 목록을 사람에게\n"
              "  보고하고 기준선(baseline) 방식으로 묶을지 정한다.", file=sys.stderr)
        return EXIT_NOT_PASSED
    return EXIT_OK


def uninstall(target: Path, hook: Path, dry_run: bool) -> None:
    setting = hooks_path_setting(target)
    if setting and not setting[0]:
        print(f"core.hooksPath 가 빈 값이라({setting[1]}) git 이 hook 을 찾지 못한다. hook 자리는 건드리지 않는다. "
              f"`{UNSET_HOOKS_PATH}` 로 지운다")
        return
    if setting:
        print(f"core.hooksPath 가 설정돼 있어({setting[0]} ({setting[1]})) hook 자리는 건드리지 않는다.")
        return
    if hook.is_symlink():
        print(f"그대로 둔다: {hook} 는 심볼릭 링크다")
    elif not hook.exists():
        print(f"변경 없음: pre-push hook 이 없다 ({hook})")
    elif not is_ours(hook):
        print(f"그대로 둔다: ai-ready 가 설치한 hook 이 아니다 ({hook})")
    elif dry_run:
        print(f"이 hook 을 지운다: {hook}")
    else:
        hook.unlink()
        print(f"뺐다: {hook}")


def install(target: Path, hook: Path, dry_run: bool) -> None:
    content = TEMPLATE.read_text(encoding="utf-8")
    same = (hook.is_file() and hook.read_text(encoding="utf-8", errors="replace") == content
            and os.access(hook, os.X_OK))
    # 상대 값이면 새로 쓰든 안 쓰든 연결 워크트리에서는 hook 이 돌지 않으므로 매번 알린다.
    relative = relative_hooks_path(target)
    note = (f"core.hooksPath 가 상대 경로(`{relative}`)라 이 작업 트리에서만 돈다. 연결 워크트리에서도 돌게 하려면 "
            "core.hooksPath 를 지우거나 절대 경로로 바꾼다" if relative else "")
    if dry_run:
        print(f"pre-push hook 자리: {hook}")
        if same:
            print("변경 없음: 같은 hook 이 있다" + (f" — {note}" if note else ""))
        else:
            print(("새 내용으로 바꾼다" if hook.exists() else "새로 만든다") + " (권한 755):")
            sys.stdout.write(content)
            if note:
                print(f"설치하면 {note}")
        return
    if same:
        print(f"변경 없음: 같은 hook 이 있다 ({hook})" + (f" — {note}" if note else ""))
        return
    existed = hook.exists()
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(content, encoding="utf-8")
    os.chmod(hook, 0o755)
    where = f"커밋되지 않는다. {note}" if note else "이 clone 의 모든 워크트리에 걸리고 커밋되지 않는다"
    print(f"{'새 내용으로 바꿨다' if existed else '걸었다'}: {hook} — {where}")


def run(args: argparse.Namespace) -> int:
    target = Path(args.target).resolve()
    hook = git_path(target, "hooks/pre-push")
    if hook is None:
        ignored = ("(GIT_DIR·GIT_WORK_TREE 환경변수는 무시하고 --target 폴더로 찾는다)"
                   if any(k in os.environ for k in ("GIT_DIR", "GIT_WORK_TREE")) else "")
        print(f"중단: {target} 는 git 저장소가 아니다{ignored}. pre-push hook 은 git clone 에 건다.", file=sys.stderr)
        return EXIT_FAILED
    # 옛 Stop hook 은 pre-push 를 걸 수 없을 때도 지운다.
    clean_settings(target, args.dry_run)
    if args.uninstall:
        uninstall(target, hook, args.dry_run)
        return EXIT_OK
    rc = _refuse_install(target, hook)
    if rc != EXIT_OK:
        return rc
    install(target, hook, args.dry_run)
    return EXIT_OK


def main() -> int:
    ap = argparse.ArgumentParser(description="scripts/verify.sh 를 도는 git pre-push hook 을 이 clone 에 건다")
    ap.add_argument("--target", required=True)
    ap.add_argument("--uninstall", action="store_true", help="ai-ready 가 건 pre-push 와 옛 Stop hook 을 지운다")
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 설치 자리·hook 내용·지울 옛 Stop hook 을 보여 준다")
    rc = run(ap.parse_args())
    if rc != EXIT_OK:
        print(f"종료 코드 {rc}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
