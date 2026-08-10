"""안티패턴 씨앗 생성기의 덮어쓰기 가드.

stdlib only. Run with:

    python3 -m unittest tests.test_antipattern_guard

이 스크립트가 유독 가드를 필요로 하는 이유는 산출물이 **초안이고 사람이 골라 옮기는 것**이
설계이기 때문이다. 관례상 `--out` 은 `.ai-ready/scaffolds/` 를 가리키지만 그것은 관례일
뿐이고, 관례는 장치가 아니다.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN_ROOT / "skills" / "audit" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import extract_antipatterns  # noqa: E402
from managed_doc import is_ai_ready_generated  # noqa: E402

SCRIPT = SCRIPTS / "extract_antipatterns.py"


def _git_repo(root: Path) -> None:
    """커밋 하나짜리 저장소. 씨앗 생성기는 git 로그를 읽으므로 대상이 저장소여야 한다."""
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "a.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fix: 뭔가 고친다"], cwd=root, check=True,
                   env={**dict(__import__("os").environ), **env})


def _run(target: Path, out: Path, *extra: str) -> int:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--target", str(target), "--out", str(out), *extra],
        capture_output=True, text=True).returncode


class TestSeedCarriesSignature(unittest.TestCase):
    def test_generated_seed_is_recognized_as_ai_ready_output(self):
        """서명이 없으면 두 번째 감사가 **자기가 만든 씨앗**에 막혀 죽는다.
        가드를 다는 것과 서명을 박는 것은 한 쌍이라 따로 갈 수 없다."""
        text = extract_antipatterns.render([], [], set(), 180)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ANTIPATTERNS.md"
            p.write_text(text, encoding="utf-8")
            self.assertTrue(is_ai_ready_generated(p))


class TestOverwriteGuard(unittest.TestCase):
    def test_new_file_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); _git_repo(root)
            out = root / "seed.md"
            self.assertEqual(_run(root, out), 0)
            self.assertTrue(out.is_file())

    def test_rerun_over_own_output_still_works(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); _git_repo(root)
            out = root / "seed.md"
            self.assertEqual(_run(root, out), 0)
            self.assertEqual(_run(root, out), 0, "자기 산출물 재생성이 막히면 감사가 2회차부터 죽는다")

    def test_human_authored_file_is_refused_and_left_intact(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); _git_repo(root)
            out = root / "docs_ANTIPATTERNS.md"
            original = "# ANTIPATTERNS\n\n손으로 추린 항목 하나.\n"
            out.write_text(original, encoding="utf-8")
            self.assertEqual(_run(root, out), 3)
            self.assertEqual(out.read_text(encoding="utf-8"), original,
                             "거부했다면 내용도 그대로여야 한다")

    def test_force_overrides(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); _git_repo(root)
            out = root / "docs_ANTIPATTERNS.md"
            out.write_text("# ANTIPATTERNS\n\n손으로 추린 항목 하나.\n", encoding="utf-8")
            self.assertEqual(_run(root, out, "--force"), 0)
            self.assertIn("초안", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
