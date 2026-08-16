#!/usr/bin/env python3
"""review_scope.py 회귀 테스트 — 임시 git 저장소를 세워 성질을 하나씩 고정한다.

**무엇을 지키나.** 이 스크립트가 좁히는 것은 렌즈가 읽는 양이라, 잘못 좁히면 그 회차의 변경이
통째로 안 읽힌다. 그리고 그 실패는 조용하다 — 렌즈는 받은 목록만 보고 "깨끗하다" 고 답한다.
그래서 아래 성질 하나하나가 되돌리면 실패하는 모양이어야 한다.

가장 중요한 것은 `앞_phase_파일_수정이_잡힌다` 다. 경로 목록으로 좁히는 순진한 구현은 그
자리에서 틀리고, 틀린 채로도 나머지가 전부 통과한다.

Usage: python3 test_review_scope.py   (exit 0 = 전부 통과)
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "review_scope.py"

_pass = 0
_fail = 0


def check(name: str, actual, expected) -> None:
    global _pass, _fail
    if actual == expected:
        _pass += 1
    else:
        _fail += 1
        print(f"FAIL  {name}\n  기대: {expected!r}\n  실제: {actual!r}")


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    )
    return proc.stdout


def run(root: Path, *args: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--root", str(root)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"review_scope 실패 rc={proc.returncode}\n{proc.stderr}")
    return proc.stdout


def snapshot(root: Path, out: Path) -> None:
    run(root, "snapshot", "--base", "mainline", "--out", str(out))


def since(root: Path, snap: Path) -> list[str]:
    out = run(root, "since", "--base", "mainline", "--snapshot", str(snap))
    return [line for line in out.splitlines() if line]


def new_repo(tmp: Path) -> Path:
    root = tmp / "repo"
    root.mkdir()
    git(root, "init", "-q", ".")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    (root / "base.txt").write_text("base\n", encoding="utf-8")
    (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    git(root, "add", "base.txt", ".gitignore")
    git(root, "commit", "-qm", "base")
    git(root, "branch", "-q", "mainline")
    return root


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        root = new_repo(tmp)
        snaps = tmp / "snaps"
        snaps.mkdir()

        # ── phase 1: 스냅숏이 비어 있고 만든 것이 전부 범위다 ──────────────
        s1 = snaps / "s1"
        snapshot(root, s1)
        check("phase1 진입 스냅숏은 비어 있다", s1.read_text(encoding="utf-8"), "")
        (root / "a.txt").write_text("a1\n", encoding="utf-8")
        (root / "b.txt").write_text("b1\n", encoding="utf-8")
        check("phase1 범위 = 만든 것 전부", since(root, s1), ["a.txt", "b.txt"])

        # ── phase 2: 앞 phase 가 만든 파일을 고치면 잡혀야 한다 ────────────
        # **이 검사가 이 파일의 존재 이유다.** 경로 목록으로 제외하는 구현은 여기서만 틀린다.
        s2 = snaps / "s2"
        snapshot(root, s2)
        (root / "c.txt").write_text("c1\n", encoding="utf-8")
        (root / "a.txt").write_text("a1\nCHANGED\n", encoding="utf-8")
        check("앞 phase 파일 수정이 잡힌다", since(root, s2), ["a.txt", "c.txt"])
        check("안 건드린 앞 phase 파일은 빠진다", "b.txt" in since(root, s2), False)

        # ── 고쳤다 되돌리면 범위에서 빠진다 ────────────────────────────────
        s3 = snaps / "s3"
        snapshot(root, s3)
        (root / "b.txt").write_text("b1\nTOUCHED\n", encoding="utf-8")
        check("고치면 들어온다", since(root, s3), ["b.txt"])
        (root / "b.txt").write_text("b1\n", encoding="utf-8")
        check("되돌리면 빠진다", since(root, s3), [])

        # ── 지우는 것도 변경이다 ───────────────────────────────────────────
        s4 = snaps / "s4"
        snapshot(root, s4)
        (root / "c.txt").unlink()
        check("삭제가 잡힌다", since(root, s4), ["c.txt"])

        # ── 커밋해도 범위가 유지된다(작업 트리만 보는 구현이면 여기서 빠진다) ──
        s5 = snaps / "s5"
        snapshot(root, s5)
        (root / "d.txt").write_text("d1\n", encoding="utf-8")
        git(root, "add", "d.txt")
        git(root, "commit", "-qm", "phase commit")
        check("커밋된 변경도 범위에 남는다", "d.txt" in since(root, s5), True)

        # ── 무시 경로는 절대 안 들어온다 ───────────────────────────────────
        # 루프 상태(.loop/run/)가 무시 경로라, 스냅숏 파일 자체가 범위에 섞이지 않는 근거다.
        s6 = snaps / "s6"
        snapshot(root, s6)
        (root / "ignored").mkdir()
        (root / "ignored" / "state.txt").write_text("x\n", encoding="utf-8")
        check("무시 경로는 범위 밖", since(root, s6), [])

        # ── 공백이 든 경로 ─────────────────────────────────────────────────
        s7 = snaps / "s7"
        snapshot(root, s7)
        (root / "with space.txt").write_text("s\n", encoding="utf-8")
        check("공백이 든 경로가 온전히 나온다", since(root, s7), ["with space.txt"])

        # ── 개행이 든 경로가 스냅숏을 왕복해도 한 건으로 남는다 ────────────
        # 레코드 구분자를 줄바꿈으로 되돌리면 이 경로가 둘로 쪼개져, 다음 phase 의 비교에서
        # 원래 경로가 "스냅숏에 없던 것" 이 되어 안 바뀐 파일이 범위에 끌려 들어온다.
        weird = "odd\nname.txt"
        (root / weird).write_text("w\n", encoding="utf-8")
        s8 = snaps / "s8"
        snapshot(root, s8)
        check("개행 경로를 담은 뒤 다시 읽으면 변경 없음", since(root, s8), [])

        # ── 스냅숏 파일이 없으면 첫 phase 로 본다 ──────────────────────────
        missing = snaps / "nope"
        check("스냅숏 부재 = 전부 범위", "with space.txt" in since(root, missing), True)

        # ── 진입 전에 지워져 있던 파일을 되살리는 것도 이번 phase 의 변경이다 ──
        # 되살리면 base 대비 무변경이 되어 현재 상태 목록에서 통째로 빠진다. 그래서 없는 쪽에
        # "지워짐" 을 기본값으로 주면 스냅숏의 "지워짐" 과 같아져 안 바뀐 것으로 떨어진다.
        (root / "base.txt").unlink()
        s9 = snaps / "s9"
        snapshot(root, s9)
        (root / "base.txt").write_text("base\n", encoding="utf-8")
        check("지워져 있던 파일을 되살린 것이 잡힌다", since(root, s9), ["base.txt"])

    print(f"review_scope: 통과 {_pass} / 실패 {_fail}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
