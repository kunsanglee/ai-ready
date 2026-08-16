#!/usr/bin/env python3
"""점검 범위 — 이 phase 가 실제로 만든 것만 골라낸다.

**왜 있나.** checker 는 `<base>...HEAD + uncommitted` 를 본다. 그 범위는 루프가 도는 내내
자라기만 해서, 마지막 phase 의 렌즈도 첫 phase 의 코드를 처음부터 다시 읽는다. 실측에서
회차 하나가 76분이었고 게이트는 그중 14초였다 — 나머지는 렌즈가 누적된 변경을 읽는 시간이다.

**무엇을 하나.** phase 에 들어갈 때 그 시점의 변경 상태를 파일별 해시로 적어 두고(`snapshot`),
렌즈를 띄우기 직전에 그 스냅숏 이후 **내용이 실제로 달라진 파일**만 낸다(`since`).

**경로 목록이 아니라 해시로 재는 이유.** 목록으로 재면 "앞 phase 가 만든 파일을 이번 phase 가
고친" 경우를 놓친다. 그 파일은 이미 목록에 있으니 제외 대상이 되고, 이번 변경이 통째로 안
읽힌다. 해시로 재면 내용이 달라진 것이 잡히고, 고쳤다가 되돌린 파일은 저절로 빠진다.

**커밋도 ref 도 안 만든다.** 루프가 커밋하지 않는다는 규약을 그대로 둔 채 동작해야 해서,
git 객체를 새로 쓰지 않고 작업 트리를 읽기만 한다.

**이것이 좁히는 것은 렌즈가 읽는 양이지 판정 기준이 아니다.** 좁히면 phase 끼리 부딪히는
결함이 안 보이므로 전 범위를 보는 자리가 순회에 하나는 있어야 하는데, 그것을 보장하는 것은
검사가 아니라 셸이다 — `skills/build/SKILL.md` 의 "점검 범위" 블록이 **마지막 phase 를 무조건
전 범위로 돌린다.** 중간 phase 도 분해에 `review_scope: "full"` 을 적어 그렇게 만들 수 있다.

사용법:
    review_scope.py snapshot --base <ref> --out <파일>
    review_scope.py since    --base <ref> --snapshot <파일>

`since` 는 파일 경로를 한 줄에 하나씩 낸다. 바뀐 것이 없으면 아무것도 안 낸다 — 부르는 쪽은
그 빈 출력을 "좁히지 않는다" 로 읽는다(빈 목록을 렌즈에 넘기면 아무것도 안 보게 된다).

종료코드는 0 이 정상이다. **0 이 아니면 부르는 쪽은 좁히지 말고 전 범위를 넘긴다** — 조용히
빈 목록을 내면 "이번 phase 가 아무것도 안 만들었다" 와 구분이 안 되고, 그 오독이 전 범위
점검을 빈 점검으로 바꾼다.

    2 — git 이 없거나, 저장소가 아니거나, `--root` 가 저장소 루트가 아니다.
    3 — 목록에 낼 수 없는 경로가 있다(경로에 개행). 좁히기만 포기하면 되는 자리라 2 와 가른다.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

DELETED = "-"  # 파일이 사라진 자리. 빈 해시와 구분되어야 "지웠다" 가 변경으로 잡힌다.
# **못 읽은 것과 사라진 것을 같은 값으로 접지 않는다.** 권한이 막혔거나 서브모듈 디렉터리인
# 경우가 그렇다. 같은 값이면 "읽을 수 없게 됐다" 는 변화가 안 잡히고, 그 파일은 내용이 어떻든
# 범위 밖에 머문다. 다만 계속 못 읽는 상태면 두 회차의 값이 같아 안 바뀐 것으로 남는다 —
# 그것까지 매번 범위에 넣으면 서브모듈이 회차마다 끼어든다.
UNREADABLE = "?"


def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        sys.stderr.write(f"review_scope: git {' '.join(args)} 실패\n{proc.stderr}")
        raise SystemExit(2)
    return proc.stdout


def _changed_paths(base: str, root: Path) -> set[str]:
    """base 대비 바뀐 파일 전부 — 커밋된 것과 작업 트리의 것을 합친다.

    `-z` 로 받는다. 경로에 공백이나 개행이 있으면 줄 단위 파싱이 조용히 어긋나고,
    어긋난 자리는 "이 파일은 이번 phase 가 안 만들었다" 로 떨어져 점검에서 빠진다.
    """
    out: set[str] = set()
    for args in (
        ["diff", "--name-only", "-z", f"{base}...HEAD"],  # 커밋된 변경
        ["diff", "--name-only", "-z", "HEAD"],  # 작업 트리의 수정·삭제
        ["ls-files", "-z", "--others", "--exclude-standard"],  # 미추적(무시된 것 제외)
    ):
        out.update(p for p in _git(args, root).split("\0") if p)
    return out


def _digest(root: Path, rel: str) -> str:
    path = root / rel
    try:
        with path.open("rb") as fh:
            h = hashlib.sha256()
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
            return h.hexdigest()
    except FileNotFoundError:
        return DELETED
    except (IsADirectoryError, PermissionError, OSError):
        return UNREADABLE


def _state(base: str, root: Path) -> dict[str, str]:
    return {rel: _digest(root, rel) for rel in _changed_paths(base, root)}


def _read_snapshot(path: Path) -> dict[str, str]:
    """스냅숏을 되읽는다. 없으면 빈 것으로 본다 — 첫 phase 가 그 경로다.

    **레코드 구분자가 NUL 인 이유.** git 출력을 `-z` 로 받아 개행이 든 경로를 온전히 얻어
    놓고 스냅숏을 줄 단위로 적으면, 그 경로 하나가 두 레코드로 쪼개져 다음 phase 의 비교가
    어긋난다. 어긋난 자리는 "안 바뀐 파일" 로 떨어져 점검에서 조용히 빠진다.
    """
    if not path.exists():
        return {}
    state: dict[str, str] = {}
    for record in path.read_text(encoding="utf-8").split("\0"):
        if not record:
            continue
        digest, _, rel = record.partition("\t")
        if rel:
            state[rel] = digest
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("mode", choices=("snapshot", "since"))
    parser.add_argument("--base", required=True)
    parser.add_argument("--out")
    parser.add_argument("--snapshot")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    # **저장소 루트가 아니면 거부한다.** `git diff --name-only` 는 저장소 루트 기준 경로를 주는데
    # 해시는 `root / rel` 로 연다. root 가 하위 디렉터리면 그 경로가 없어 전부 "지워짐" 으로 접히고,
    # 스냅숏과 다음 비교가 같은 값이라 **그 파일들이 영영 범위 밖에 남는다**(실측). 조용한 실패라
    # 여기서 죽이는 편이 싸다.
    top = _git(["rev-parse", "--show-toplevel"], root).strip()
    if top and Path(top).resolve() != root:
        sys.stderr.write(
            f"review_scope: --root 가 저장소 루트가 아니다\n"
            f"  받은 값: {root}\n  저장소 루트: {top}\n"
            f"  경로 기준이 섞여 변경이 통째로 '지워짐' 으로 접힌다.\n")
        raise SystemExit(2)
    state = _state(args.base, root)

    if args.mode == "snapshot":
        if not args.out:
            parser.error("snapshot 은 --out 이 필요하다")
        body = "".join(f"{state[k]}\t{k}\0" for k in sorted(state))
        Path(args.out).write_text(body, encoding="utf-8")
        print(f"review_scope: 스냅숏 {len(state)}개 파일 → {args.out}")
        return 0

    if not args.snapshot:
        parser.error("since 는 --snapshot 이 필요하다")
    before = _read_snapshot(Path(args.snapshot))
    # **양쪽 경로를 합쳐서 본다.** 지금 상태만 훑으면 이 phase 가 만들었다가 지운 미추적 파일을
    # 놓친다 — 그런 파일은 HEAD 에도 없고 미추적 목록에도 없어서 `_changed_paths` 가 못 준다.
    # 스냅숏에만 남아 있는 것이 유일한 흔적이라, 그 쪽에서 끌어와야 삭제가 변경으로 잡힌다.
    # (추적 중인 파일의 삭제는 `diff HEAD` 가 주므로 이 합집합이 그 경우를 중복 세지 않는다.)
    # **없는 쪽에 기본값을 주지 않는다.** `state.get(rel, DELETED)` 로 두면, 진입 시점에 이미
    # 지워져 있던(`-`) 추적 파일을 이번 phase 가 원래 내용으로 되살렸을 때 그 파일이 base 대비
    # 무변경이 되어 `state` 에서 빠지고, 기본값 `-` 가 스냅숏의 `-` 와 같아져 안 바뀐 것이 된다.
    # 되살리기도 이번 phase 가 한 변경이라 렌즈가 봐야 한다(실측으로 갈렸다).
    touched = sorted(
        rel for rel in set(state) | set(before) if before.get(rel) != state.get(rel)
    )

    # **개행이 든 경로가 하나라도 있으면 좁히기를 포기한다.** 이 출력은 줄 단위라 그런 경로 하나가
    # 두 줄로 쪼개지고, 쪼개진 두 조각은 **둘 다 없는 경로**다 — 정작 바뀐 파일은 목록에서 사라진다
    # (실측). 목록을 고쳐 내는 대신 전 범위로 떨어뜨리는 이유는, 이 목록이 렌즈가 무엇을 볼지
    # 정하는 값이라 한 줄이라도 못 믿으면 전체를 못 믿기 때문이다. 안전한 쪽은 넓은 쪽이다.
    bad = [r for r in touched if "\n" in r]
    if bad:
        sys.stderr.write(
            "review_scope: 경로에 개행이 들어 목록을 줄 단위로 못 낸다 — 좁히지 않는다\n"
            + "".join(f"  {r!r}\n" for r in bad))
        raise SystemExit(3)

    for rel in touched:
        print(rel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
