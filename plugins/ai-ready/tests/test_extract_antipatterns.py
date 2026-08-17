"""안티패턴 씨앗 생성기가 git 을 못 읽었을 때 그 사실을 말하나.

stdlib only. Run with:

    python3 -m unittest tests.test_extract_antipatterns

산출물은 "최근 N일 git 히스토리에서 추출한 시드입니다" 라고 스스로 말한다. git 이 한 번도
실행되지 못한 채 그 문장이 담긴 문서가 나오면 읽는 쪽은 "고칠 것이 없다" 로 읽는다. 커밋이
없는 저장소와 히스토리를 못 읽은 저장소는 다른 사건이고, 문서는 앞의 것만 말해도 된다.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN_ROOT / "skills" / "audit" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import extract_antipatterns  # noqa: E402

SCRIPT = SCRIPTS / "extract_antipatterns.py"

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
}


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)


def _commit(root: Path, rel: str, body: str, subject: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", subject], cwd=root, check=True,
                   env={**os.environ, **_GIT_ENV})


def _run(target: Path, out: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--target", str(target), "--out", str(out), *extra],
        capture_output=True, text=True)


class TestGitGate(unittest.TestCase):
    def test_non_repo_target_fails_loudly_and_writes_nothing(self):
        """git 저장소가 아닌 디렉토리. 여기서 exit 0 + 문서 생성이면, 감사는 "안티패턴
        후보 없음" 이라는 거짓 결론을 산출물로 남긴다."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.py").write_text("x = 1\n", encoding="utf-8")
            out = root / "seed.md"
            r = _run(root, out)
            self.assertNotEqual(r.returncode, 0, r.stdout)
            self.assertEqual(r.returncode, extract_antipatterns.EXIT_GIT_UNAVAILABLE)
            self.assertIn("git", r.stderr)
            self.assertIn(str(root), r.stderr)
            self.assertFalse(out.exists(), "git 을 못 읽었으면 문서를 남기지 않는다")

    def test_gate_exit_code_does_not_collide_with_overwrite_guard(self):
        """3 은 덮어쓰기 거부가 이미 쓰고 SKILL.md 도 그 값으로 문서화했다. 겹치면
        호출부가 두 사건을 구분하지 못한다."""
        self.assertNotEqual(extract_antipatterns.EXIT_GIT_UNAVAILABLE,
                            extract_antipatterns.EXIT_GUARD_REFUSED)


class TestEmptyRepo(unittest.TestCase):
    def test_repo_without_commits_succeeds_with_zero_commits(self):
        """커밋 0개인 저장소에서 `git log --since=` 는 exit 128 로 끝난다. 그건 오류가
        아니라 정당한 "히스토리 없음" 이라 게이트에 걸리면 안 된다."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _git_init(root)
            out = root / "seed.md"
            r = _run(root, out)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(out.is_file())
            self.assertIn("fix류 커밋 0개", r.stdout)
            self.assertIn("등장한 파일이 없습니다", out.read_text(encoding="utf-8"))

    def test_parse_fix_commits_returns_empty_not_none(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _git_init(root)
            self.assertEqual(extract_antipatterns.parse_fix_commits(root, 180), [])


class TestRepoWithHistory(unittest.TestCase):
    def test_recurring_fix_target_reaches_the_document(self):
        """게이트를 단 뒤에도 본래 하던 일 — fix 커밋을 모아 반복 수정 위치를 짚는 것 — 을
        그대로 한다."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _git_init(root)
            _commit(root, "src/pay.py", "v0\n", "feat: 결제를 붙인다")
            for i in range(extract_antipatterns.MIN_OCCURRENCES):
                _commit(root, "src/pay.py", f"v{i + 1}\n", f"fix: 결제 정산 반올림 {i}")
            out = root / "seed.md"
            r = _run(root, out)
            self.assertEqual(r.returncode, 0, r.stderr)
            text = out.read_text(encoding="utf-8")
            self.assertIn("src/pay.py", text)
            self.assertIn("결제 정산 반올림", text)

    def test_run_git_reports_success_separately_from_output(self):
        """빈 문자열은 "결과가 없다" 와 "실행이 실패했다" 를 뭉갠다. 그 구분이 게이트의
        전제다."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _git_init(root)
            _commit(root, "a.txt", "x\n", "fix: 하나 고친다")
            ok, out = extract_antipatterns.run_git(root, ["rev-parse", "--is-inside-work-tree"])
            self.assertTrue(ok)
            self.assertEqual(out.strip(), "true")
            failed, empty = extract_antipatterns.run_git(root, ["rev-parse", "--verify", "no-such-ref"])
            self.assertFalse(failed)
            self.assertEqual(empty, "")


if __name__ == "__main__":
    unittest.main()
