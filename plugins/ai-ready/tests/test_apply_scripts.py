"""apply 가 부르는 스크립트 테스트 — scaffold 템플릿 · bootstrap · check_docs · verify.sh · hook 설치기.

stdlib only. 플러그인 루트에서 `python3 -m unittest discover -s tests -t .` 로 돈다.
verify.sh 테스트는 bash 와 git 이 있어야 돈다(없으면 skip 으로 남는다).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN_ROOT / "skills" / "audit" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "project"))

import bootstrap  # noqa: E402
import check_docs  # noqa: E402
import install_verify_hook  # noqa: E402
import managed_doc  # noqa: E402
import scaffold  # noqa: E402

HAS_SHELL = shutil.which("bash") is not None and shutil.which("git") is not None


def _mk(root: Path, rel: str, text: str = "x\n") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _quiet(fn, *args, **kwargs):
    """스크립트의 안내문이 테스트 출력을 덮지 않게 한다."""
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


class TestModuleTemplate(unittest.TestCase):
    def _render(self) -> str:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "settings.gradle.kts")
            _mk(root, "app/build.gradle.kts")
            _mk(root, "app/src/main/kotlin/a/OrderService.kt", "class OrderService\n")
            return scaffold.render_module(root, Path("app"))

    def test_sections_in_order(self):
        text = self._render()
        heads = [line for line in text.splitlines() if line.startswith("## ")]
        self.assertEqual(heads, ["## 이 모듈이 하는 일", "## 경계", "## 변경 방법",
                                 "## 강제할 수 없는 규칙", "## 강제되는 규칙"])

    def test_no_history_or_counts(self):
        text = self._render()
        for banned in ("핫 파일", "Top 5", "회 변경", "소스 파일", "최근 90일"):
            self.assertNotIn(banned, text)

    def test_carries_signature_and_manifest_pointer(self):
        text = self._render()
        self.assertTrue(text.startswith("<!-- ai-ready:apply"))
        self.assertIn("정본은 `build.gradle.kts`", text)
        with tempfile.TemporaryDirectory() as d:
            p = _mk(Path(d), "CLAUDE.md", text)
            self.assertTrue(managed_doc.is_ai_ready_generated(p))

    def test_human_owned_module_doc_is_skipped_and_explicit_request_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "package.json", "{}")
            _mk(root, "src/a/x.ts")
            _mk(root, "src/b/y.ts")
            _mk(root, "src/a/CLAUDE.md", "# 사람이 쓴 문서\n")
            self.assertEqual(_quiet(scaffold.run, root, root, 5), scaffold.EXIT_OK)
            self.assertEqual((root / "src/a/CLAUDE.md").read_text(encoding="utf-8"), "# 사람이 쓴 문서\n")
            self.assertTrue((root / "src/b/CLAUDE.md").is_file())
            self.assertEqual(_quiet(scaffold.run, root, root, 5, ["src/a"]), scaffold.EXIT_REFUSED)
            self.assertEqual(_quiet(scaffold.run, root, root, 5, ["src/a"], force=True), scaffold.EXIT_OK)
            self.assertTrue(managed_doc.is_ai_ready_generated(root / "src/a/AGENTS.md"))
            self.assertEqual((root / "src/a/CLAUDE.md").read_text(encoding="utf-8"), "@AGENTS.md\n")

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "package.json", "{}")
            _mk(root, "src/a/x.ts")
            self.assertEqual(_quiet(scaffold.run, root, root, 5, dry_run=True), scaffold.EXIT_OK)
            self.assertFalse((root / "src/a/CLAUDE.md").exists())


class TestBootstrap(unittest.TestCase):
    def _node_repo(self, root: Path) -> None:
        _mk(root, "package.json", json.dumps({"scripts": {"lint": "eslint .", "test": "vitest run"}}))
        _mk(root, "src/a/x.ts")

    def test_writes_every_kind_and_passes_its_own_doc_check(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._node_repo(root)
            rc = _quiet(bootstrap.run, root, list(bootstrap.KINDS), [], "order")
            self.assertEqual(rc, bootstrap.EXIT_OK)
            for rel in ("AGENTS.md", "CLAUDE.md", "docs/design/README.md", "docs/design/order.md",
                        "docs/design/order.decisions.md", "docs/ANTIPATTERNS.md", "docs/VERIFICATION.md",
                        "scripts/verify.sh", "scripts/check_docs.py"):
                self.assertTrue((root / rel).is_file(), rel)
            self.assertFalse((root / "AGENTS.md").is_symlink())
            self.assertTrue(managed_doc.is_ai_ready_generated(root / "AGENTS.md"))
            self.assertEqual((root / "CLAUDE.md").read_text(encoding="utf-8"), "@AGENTS.md\n")
            self.assertTrue(os.access(root / "scripts/verify.sh", os.X_OK))
            self.assertIn("'npm run lint'", (root / "scripts/verify.sh").read_text(encoding="utf-8"))
            self.assertIn(bootstrap.UNION_LINE, (root / ".gitattributes").read_text(encoding="utf-8"))
            # 만든 문서끼리의 링크·카드 형식이 자기 검사를 통과해야 한다.
            errors, _ = check_docs.run(root, {})
            self.assertEqual(errors, [])

    def test_root_doc_is_short_and_has_three_parts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._node_repo(root)
            _quiet(bootstrap.run, root, ["root"], [], None)
            text = (root / "AGENTS.md").read_text(encoding="utf-8")
            for head in ("## 확인 명령", "## 문서 지도", "## 강제할 수 없는 규칙"):
                self.assertIn(head, text)
            self.assertIn("`npm test`", text)
            self.assertLess(len(text.encode("utf-8")), 2_000)

    def test_human_owned_file_blocks_the_whole_run(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._node_repo(root)
            _mk(root, "docs/ANTIPATTERNS.md", "# 우리 팀 원장\n")
            rc = _quiet(bootstrap.run, root, ["root", "antipatterns"], [], None)
            self.assertEqual(rc, bootstrap.EXIT_REFUSED)
            self.assertFalse((root / "AGENTS.md").exists(), "거부되면 다른 파일도 쓰지 않는다")
            self.assertFalse((root / "CLAUDE.md").exists(), "거부되면 다른 파일도 쓰지 않는다")
            self.assertEqual((root / "docs/ANTIPATTERNS.md").read_text(encoding="utf-8"), "# 우리 팀 원장\n")

    def test_rerun_keeps_the_import_line(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._node_repo(root)
            self.assertEqual(_quiet(bootstrap.run, root, ["root"], [], None), bootstrap.EXIT_OK)
            self.assertEqual(_quiet(bootstrap.run, root, ["root"], [], None), bootstrap.EXIT_OK)
            self.assertEqual((root / "CLAUDE.md").read_text(encoding="utf-8"), "@AGENTS.md\n")

    def test_human_claude_md_is_refused_unless_it_already_imports_agents_md(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._node_repo(root)
            _mk(root, "CLAUDE.md", "# 우리 문서\n")
            self.assertEqual(_quiet(bootstrap.run, root, ["root"], [], None), bootstrap.EXIT_REFUSED)
            self.assertFalse((root / "AGENTS.md").exists())
            _mk(root, "CLAUDE.md", "@AGENTS.md\n\n## Claude Code\n- plan mode 를 쓴다\n")
            self.assertEqual(_quiet(bootstrap.run, root, ["root"], [], None), bootstrap.EXIT_OK)
            self.assertIn("## Claude Code", (root / "CLAUDE.md").read_text(encoding="utf-8"), "이미 가져오면 그대로 둔다")
            self.assertTrue(managed_doc.is_ai_ready_generated(root / "AGENTS.md"))

    def test_old_symlink_layout_is_refused_until_force(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._node_repo(root)
            old = bootstrap.SIGNATURE_MD + "\n# old\n"
            _mk(root, "CLAUDE.md", old)
            (root / "AGENTS.md").symlink_to("CLAUDE.md")
            r = subprocess.run([sys.executable, str(SCRIPTS / "bootstrap.py"), "--target", str(root), "--only", "root"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, bootstrap.EXIT_REFUSED)
            self.assertIn("심볼릭 링크", r.stderr)
            self.assertIn(f"종료 코드 {bootstrap.EXIT_REFUSED}", r.stderr)
            self.assertTrue((root / "AGENTS.md").is_symlink())
            self.assertEqual((root / "CLAUDE.md").read_text(encoding="utf-8"), old)
            self.assertEqual(_quiet(bootstrap.run, root, ["root"], [], None, force=True), bootstrap.EXIT_OK)
            self.assertFalse((root / "AGENTS.md").is_symlink())
            self.assertTrue(managed_doc.is_ai_ready_generated(root / "AGENTS.md"))
            self.assertEqual((root / "CLAUDE.md").read_text(encoding="utf-8"), "@AGENTS.md\n")

    @unittest.skipUnless(HAS_SHELL, "bash·git 이 없다")
    def test_ignored_target_path_stops_before_writing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._node_repo(root)
            _mk(root, ".gitignore", "node_modules\nCLAUDE.md\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
            for extra in ([], ["--dry-run"]):
                r = subprocess.run([sys.executable, str(SCRIPTS / "bootstrap.py"), "--target", str(root),
                                    "--only", "root,antipatterns", *extra], capture_output=True, text=True)
                self.assertEqual(r.returncode, bootstrap.EXIT_IGNORED, extra)
                self.assertIn("CLAUDE.md", r.stderr)
                self.assertIn(".gitignore:2", r.stderr)
                self.assertIn(f"종료 코드 {bootstrap.EXIT_IGNORED}", r.stderr)
            for rel in ("AGENTS.md", "CLAUDE.md", "docs/ANTIPATTERNS.md"):
                self.assertFalse((root / rel).exists(), f"무시되는 경로가 있으면 아무것도 쓰지 않는다: {rel}")
            self.assertEqual(_quiet(bootstrap.run, root, ["root"], [], None, force=True), bootstrap.EXIT_OK)
            self.assertTrue((root / "CLAUDE.md").is_file())

    def test_signed_file_is_rewritten(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._node_repo(root)
            _quiet(bootstrap.run, root, ["antipatterns"], [], None)
            self.assertEqual(_quiet(bootstrap.run, root, ["antipatterns"], [], None), bootstrap.EXIT_OK)

    def test_gitattributes_line_is_appended_once_and_keeps_other_lines(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, ".gitattributes", "*.png binary")
            _quiet(bootstrap.run, root, ["design"], [], None)
            _quiet(bootstrap.run, root, ["design"], [], None)
            self.assertEqual((root / ".gitattributes").read_text(encoding="utf-8"),
                             "*.png binary\n" + bootstrap.UNION_LINE + "\n")

    def test_verification_without_commands_stops(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(_quiet(bootstrap.run, root, ["verification"], [], None), bootstrap.EXIT_NO_COMMANDS)
            self.assertFalse((root / "scripts/verify.sh").exists())
            self.assertEqual(_quiet(bootstrap.run, root, ["verification"], ["make check"], None), bootstrap.EXIT_OK)
            self.assertIn("'make check'", (root / "scripts/verify.sh").read_text(encoding="utf-8"))

    def test_edited_checks_in_signed_verify_sh_block_the_run(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(_quiet(bootstrap.run, root, ["verification"], ["make a"], None), bootstrap.EXIT_OK)
            sh = root / "scripts/verify.sh"
            edited = sh.read_text(encoding="utf-8").replace("  'make a'", "  'make a'\n  'make b'")
            sh.write_text(edited, encoding="utf-8")
            doc = (root / "docs/VERIFICATION.md").read_text(encoding="utf-8")
            self.assertEqual(_quiet(bootstrap.run, root, ["verification"], ["make a"], None), bootstrap.EXIT_REFUSED)
            self.assertEqual(sh.read_text(encoding="utf-8"), edited, "사람이 고친 CHECKS 를 덮어쓰지 않는다")
            self.assertEqual((root / "docs/VERIFICATION.md").read_text(encoding="utf-8"), doc, "거부되면 다른 파일도 쓰지 않는다")
            r = subprocess.run([sys.executable, str(SCRIPTS / "bootstrap.py"), "--target", str(root),
                                "--only", "verification", "--check", "make a"], capture_output=True, text=True)
            self.assertEqual(r.returncode, bootstrap.EXIT_REFUSED)
            self.assertIn("--check 'make a' --check 'make b'", r.stderr)
            # 같은 명령을 주면 CHECKS 가 같아 그대로 다시 쓴다.
            self.assertEqual(_quiet(bootstrap.run, root, ["verification"], ["make a", "make b"], None), bootstrap.EXIT_OK)
            self.assertEqual(_quiet(bootstrap.run, root, ["verification"], ["make c"], None, force=True),
                             bootstrap.EXIT_OK)
            self.assertEqual(bootstrap.checks_block(sh.read_text(encoding="utf-8")), ["make c"])

    def test_ci_line_that_excludes_the_test_task_is_written_as_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "settings.gradle.kts", 'include(":app")\n')
            _mk(root, "build.gradle.kts")
            _mk(root, "gradlew", "#!/bin/sh\n")
            _mk(root, ".github/workflows/ci.yml", "jobs:\n  test:\n    steps:\n      - run: ./gradlew bootJar -x test\n")
            _quiet(bootstrap.run, root, ["verification"], [], None)
            doc = (root / "docs/VERIFICATION.md").read_text(encoding="utf-8")
            self.assertIn("- `./gradlew test`: CI 가 이 명령을 부르는 줄에서 `-x`·`-DskipTests` 같은 옵션으로 이 검사를 뺀다 "
                          "(.github/workflows/ci.yml:4)", doc)
            self.assertNotIn("`./gradlew test`: CI 가 돌린다", doc)

    def test_existing_testing_doc_is_marked_for_absorption(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._node_repo(root)
            _mk(root, "docs/TESTING.md", "# 테스트\n")
            _quiet(bootstrap.run, root, ["verification"], [], None)
            self.assertIn("`docs/TESTING.md` 의 내용을 이 절로 옮기고",
                          (root / "docs/VERIFICATION.md").read_text(encoding="utf-8"))


class TestCheckDocs(unittest.TestCase):
    def test_broken_relative_link_is_error_and_others_are_not(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "docs/a.md", "\n".join([
                "[ok](b.md) [ok2](/docs/b.md#x) [web](https://x.y) [anchor](#top)",
                "[bad](missing.md)",
                "`[code](nope.md)`",
                "```", "[fenced](nope2.md)", "```",
                "[ref]: ../README-missing.md",
            ]))
            _mk(root, "docs/b.md")
            errors, _ = check_docs.run(root, {})
            self.assertEqual(sorted(e.split(":")[1] for e in errors), ["2", "7"])

    def test_card_header_format_and_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "docs/design/pay.md")
            _mk(root, "docs/design/pay.decisions.md", "\n".join([
                "# pay — 결정 기록",
                "## 환불은 전액만 · (PAY-2) · [accepted]",
                "## 부분 환불 · (PAY-1) · [superseded]",
                "## 부분 환불 · (PAY-1) · [accepted]",
                "## 환불은 전액만 · (PAY-2) · [accepted]",
                "## 형식 틀림 [accepted]",
                "```", "## 코드 블록 안 · (x) · [maybe]", "```",
            ]))
            errors, _ = check_docs.run(root, {})
            lines = sorted(int(e.split(":")[1]) for e in errors)
            self.assertEqual(lines, [4, 5, 6])
            self.assertTrue(any("union merge" in e for e in errors))
            self.assertTrue(any("라벨만 다르다" in e for e in errors))

    def test_frontmatter_required_keys_and_unclosed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "docs/design/a.md", "---\nowner: kim\n---\n# a\n")
            _mk(root, "docs/design/b.md", "---\nstatus: x\n---\n# b\n")
            _mk(root, "docs/c.md", "---\nowner: x\n# 닫히지 않음\n")
            errors, warnings = check_docs.run(root, {"docs/design/*.md": ("owner",)})
            self.assertEqual(len(errors), 2)
            self.assertTrue(any(e.startswith("docs/design/b.md") and "owner" in e for e in errors))
            self.assertTrue(any(e.startswith("docs/c.md") for e in errors))
            self.assertEqual(len(warnings), 2, "a.md·b.md 에 결정 카드 파일이 없다 — 경고")

    def test_fence_closes_only_with_its_own_marker(self):
        # ~~~ 블록 안의 ``` 는 펜스를 닫지 않는다. 토글로 세면 안과 밖이 뒤집힌다.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "docs/a.md", "\n".join([
                "~~~markdown", "```", "[inside](nope.md)", "```", "~~~",
                "[after](missing.md)",
                "````", "```", "[inside2](nope2.md)", "````",
            ]))
            errors, _ = check_docs.run(root, {})
            self.assertEqual([e.split(":")[1] for e in errors], ["6"])

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "docs/design/x.decisions.md", "# x\n")
            script = SCRIPTS / "project" / "check_docs.py"
            r = subprocess.run([sys.executable, str(script), "--root", str(root)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, "경고만 있으면 exit 0")
            self.assertIn("경고:", r.stderr)
            _mk(root, "README.md", "[x](gone.md)\n")
            r = subprocess.run([sys.executable, str(script), "--root", str(root)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)


@unittest.skipUnless(HAS_SHELL, "bash·git 이 없다")
class TestVerifySh(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # 명령이 몇 번 돌았는지 파일에 한 줄씩 남긴다. 캐시가 맞으면 줄이 늘지 않는다.
        check = "echo run >> .git/count; test ! -f FAIL"
        _mk(self.root, "scripts/verify.sh", bootstrap.render_verify_sh([("test", check)]))
        _mk(self.root, "a.txt", "a\n")
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t"}
        for cmd in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-qm", "init"]):
            subprocess.run(cmd, cwd=self.root, check=True, env=env, capture_output=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _verify(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", "scripts/verify.sh", *args], cwd=self.root, capture_output=True, text=True)

    def _runs(self) -> int:
        p = self.root / ".git" / "count"
        return len(p.read_text().splitlines()) if p.exists() else 0

    def test_unchanged_tree_is_not_rerun(self):
        self.assertEqual(self._verify().returncode, 0)
        self.assertEqual(self._verify().returncode, 0)
        self.assertEqual(self._runs(), 1)

    def test_tracked_and_untracked_changes_invalidate_cache(self):
        self._verify()
        (self.root / "a.txt").write_text("b\n")
        self._verify()
        self.assertEqual(self._runs(), 2)
        (self.root / "new.txt").write_text("n\n")
        self._verify()
        self.assertEqual(self._runs(), 3)
        (self.root / "new.txt").write_text("m\n")
        self._verify()
        self.assertEqual(self._runs(), 4, "추적 안 하는 파일의 내용이 바뀌어도 다시 돈다")

    def _git(self, *args: str) -> None:
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", *args], cwd=self.root, check=True, env=env, capture_output=True)

    def test_committing_a_failing_change_invalidates_cache(self):
        # 작업 트리는 깨끗한 채 HEAD 만 바뀐다. 지문에 HEAD 가 없으면 옛 통과를 그대로 믿는다.
        self.assertEqual(self._verify().returncode, 0)
        (self.root / "FAIL").write_text("")
        self._git("add", "FAIL")
        self._git("commit", "-qm", "fail")
        self.assertEqual(self._verify().returncode, 1)
        self.assertEqual(self._runs(), 2)

    def test_staged_change_invalidates_cache(self):
        self.assertEqual(self._verify().returncode, 0)
        (self.root / "FAIL").write_text("")
        self._git("add", "FAIL")
        self.assertEqual(self._verify().returncode, 1)
        self.assertEqual(self._runs(), 2)

    def test_changed_checks_invalidate_cache(self):
        # verify.sh 를 git 밖에 두어 파일 변경이 diff 에 잡히지 않게 한다. 그래도 CHECKS 가 바뀌면 다시 돈다.
        (self.root / ".gitignore").write_text("scripts/verify.sh\n")
        self._git("rm", "-q", "--cached", "scripts/verify.sh")
        self._git("add", ".gitignore")
        self._git("commit", "-qm", "ignore verify")
        self._verify()
        self._verify()
        self.assertEqual(self._runs(), 1)
        _mk(self.root, "scripts/verify.sh", bootstrap.render_verify_sh([("test", "echo run >> .git/count; true")]))
        self.assertEqual(self._verify().returncode, 0)
        self.assertEqual(self._runs(), 2)

    def test_failure_prints_only_last_lines(self):
        _mk(self.root, "scripts/verify.sh", bootstrap.render_verify_sh(
            [("test", "for i in $(seq 1 50); do echo line$i; done; exit 1")]))
        r = self._verify()
        self.assertEqual(r.returncode, 1)
        self.assertIn("line50", r.stderr)
        self.assertIn("line31", r.stderr)
        self.assertNotIn("line30\n", r.stderr)

    def test_stop_hook_blocks_three_times_then_lets_through(self):
        (self.root / "FAIL").write_text("")
        codes = [self._verify("--stop-hook").returncode for _ in range(3)]
        self.assertEqual(codes, [2, 2, 2])
        (self.root / "FAIL").unlink()
        self.assertEqual(self._verify("--stop-hook").returncode, 0)
        (self.root / "FAIL").write_text("x")
        self.assertEqual(self._verify("--stop-hook").returncode, 2, "통과하면 막은 횟수가 0 으로 돌아간다")

    def test_same_failing_tree_is_not_rerun_after_the_cap(self):
        # 상한까지 막은 뒤에는 같은 작업 트리로 몇 턴을 더 끝내도 검사를 다시 돌리지 않고 통과시킨다.
        (self.root / "FAIL").write_text("")
        results = [self._verify("--stop-hook") for _ in range(6)]
        self.assertEqual([r.returncode for r in results], [2, 2, 2, 0, 0, 0])
        self.assertEqual(self._runs(), 3, "상한 뒤의 턴은 검사를 돌리지 않는다")
        self.assertIn("다시 돌리지 않는다", results[3].stderr)
        self.assertEqual(len(results[3].stderr.strip().splitlines()), 1, "안내는 한 줄")

    def test_changed_tree_is_counted_anew(self):
        (self.root / "FAIL").write_text("")
        for _ in range(4):
            self._verify("--stop-hook")
        self.assertEqual(self._runs(), 3)
        (self.root / "FAIL").write_text("changed")
        codes = [self._verify("--stop-hook").returncode for _ in range(4)]
        self.assertEqual(codes, [2, 2, 2, 0], "트리가 바뀌면 다시 막는다")
        self.assertEqual(self._runs(), 6)

    def test_manual_run_always_runs_even_after_the_cap(self):
        (self.root / "FAIL").write_text("")
        for _ in range(4):
            self._verify("--stop-hook")
        self.assertEqual(self._runs(), 3)
        self.assertEqual(self._verify().returncode, 1)
        self.assertEqual(self._verify().returncode, 1)
        self.assertEqual(self._runs(), 5, "사람이 직접 부르면 매번 돈다")
        self.assertEqual(self._verify("--stop-hook").returncode, 0, "수동 실행은 막은 횟수를 건드리지 않는다")
        self.assertEqual(self._runs(), 5)

    def test_stop_hook_failure_tells_the_agent_not_to_fix_unrelated_violations(self):
        (self.root / "FAIL").write_text("")
        r = self._verify("--stop-hook")
        self.assertEqual(r.returncode, 2)
        self.assertIn("이번 변경과 무관한 기존 위반은 고치지 말고 멈춰서 사람에게 보고한다", r.stderr)


@unittest.skipUnless(HAS_SHELL, "bash·git 이 없다")
class TestInstallVerifyHook(unittest.TestCase):
    def _run(self, root: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPTS / "install_verify_hook.py"), "--target", str(root), *args],
                              capture_output=True, text=True)

    @staticmethod
    def _passed_repo(root: Path) -> None:
        """verify.sh 가 한 번 통과한 저장소 — 통과 지문 파일이 있다."""
        _mk(root, "scripts/verify.sh", "#!/bin/sh\n")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
        _mk(root, ".git/verify-pass", "abc\n")

    def test_refuses_until_verify_has_passed_once(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "scripts/verify.sh", "#!/bin/sh\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
            for args in ((), ("--dry-run",)):
                r = self._run(root, *args)
                self.assertEqual(r.returncode, install_verify_hook.EXIT_NOT_PASSED, args)
                self.assertIn("통과", r.stderr)
                self.assertIn(f"종료 코드 {install_verify_hook.EXIT_NOT_PASSED}", r.stderr)
            self.assertFalse((root / ".claude/settings.json").exists())
            self.assertEqual(self._run(root, "--force").returncode, 0)
            self.assertTrue((root / ".claude/settings.json").is_file())
            _mk(root, ".git/verify-pass", "abc\n")
            self.assertEqual(self._run(root, "--uninstall").returncode, 0)

    def test_uninstall_does_not_need_a_pass(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, ".claude/settings.json", json.dumps({"hooks": {"Stop": [
                {"hooks": [{"type": "command", "command": install_verify_hook.HOOK_COMMAND}]}]}}))
            self.assertEqual(self._run(root, "--uninstall").returncode, 0)
            self.assertEqual(json.loads((root / ".claude/settings.json").read_text(encoding="utf-8")), {})

    def test_merges_with_existing_settings_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._passed_repo(root)
            existing = {"permissions": {"allow": ["Bash(ls:*)"]},
                        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo other"}]}],
                                  "PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "fmt"}]}]}}
            _mk(root, ".claude/settings.json", json.dumps(existing))
            self.assertEqual(self._run(root).returncode, 0)
            first = (root / ".claude/settings.json").read_text(encoding="utf-8")
            self.assertEqual(self._run(root).returncode, 0)
            self.assertEqual((root / ".claude/settings.json").read_text(encoding="utf-8"), first)
            data = json.loads(first)
            self.assertEqual(data["permissions"], existing["permissions"])
            self.assertEqual(data["hooks"]["PostToolUse"], existing["hooks"]["PostToolUse"])
            commands = [h["command"] for g in data["hooks"]["Stop"] for h in g["hooks"]]
            self.assertEqual(commands, ["echo other", install_verify_hook.HOOK_COMMAND])

    def test_uninstall_removes_only_ours(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._passed_repo(root)
            _mk(root, ".claude/settings.json", json.dumps({"hooks": {"Stop": [
                {"hooks": [{"type": "command", "command": "echo other"}]}]}}))
            self._run(root)
            self.assertEqual(self._run(root, "--uninstall").returncode, 0)
            data = json.loads((root / ".claude/settings.json").read_text(encoding="utf-8"))
            self.assertEqual(data, {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo other"}]}]}})

    def test_refuses_without_verify_script_or_with_broken_json(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(self._run(root).returncode, 1)
            self.assertFalse((root / ".claude/settings.json").exists())
            self._passed_repo(root)
            _mk(root, ".claude/settings.json", "{ not json")
            self.assertEqual(self._run(root).returncode, 1)
            self.assertEqual((root / ".claude/settings.json").read_text(encoding="utf-8"), "{ not json")

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._passed_repo(root)
            r = self._run(root, "--dry-run")
            self.assertEqual(r.returncode, 0)
            self.assertIn("--stop-hook", r.stdout)
            self.assertFalse((root / ".claude/settings.json").exists())


if __name__ == "__main__":
    unittest.main()
