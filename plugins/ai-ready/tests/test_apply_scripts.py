"""apply 가 부르는 스크립트 테스트 — scaffold 템플릿 · bootstrap · check_docs · verify.sh · pre-push hook 과 설치기.

stdlib only. 플러그인 루트에서 `python3 -m unittest discover -s tests -t .` 로 돈다.
verify.sh·hook 테스트는 bash 와 git 이 있어야 돈다(없으면 skip 으로 남는다).
"""
from __future__ import annotations

import json
import os
import shlex
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

    def _two_node_modules(self, root: Path) -> None:
        _mk(root, "package.json", "{}")
        _mk(root, "src/a/x.ts")
        _mk(root, "src/b/y.ts")

    def test_filled_draft_is_left_out_of_top_and_refused_when_named(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._two_node_modules(root)
            self.assertEqual(_quiet(scaffold.run, root, root, 5), scaffold.EXIT_OK)
            agents = root / "src/a/AGENTS.md"
            self.assertEqual(managed_doc.draft_state(agents), "draft")
            filled = agents.read_text(encoding="utf-8").replace("의존해도 되는 것: TODO", "의존해도 되는 것: src/b")
            agents.write_text(filled, encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPTS / "scaffold.py"), "--target", str(root), "--out", str(root),
                                "--top", "5", "--dry-run"], capture_output=True, text=True)
            self.assertEqual(r.returncode, scaffold.EXIT_OK, r.stderr)
            self.assertIn("건너뜀: src/a (AGENTS.md: 초안이 고쳐졌다 —", r.stderr)
            self.assertNotIn("src/a/AGENTS.md", r.stdout)
            self.assertIn("src/b/AGENTS.md", r.stdout)
            r = subprocess.run([sys.executable, str(SCRIPTS / "scaffold.py"), "--target", str(root), "--out", str(root),
                                "--modules", "src/a"], capture_output=True, text=True)
            self.assertEqual(r.returncode, scaffold.EXIT_REFUSED)
            self.assertIn("초안이 고쳐졌다", r.stderr)
            self.assertEqual(agents.read_text(encoding="utf-8"), filled)

    def test_claude_md_that_imports_agents_md_with_extra_lines_is_kept(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._two_node_modules(root)
            extra = "@AGENTS.md\n\n## Claude Code\n- plan mode 를 쓴다\n"
            _mk(root, "src/a/CLAUDE.md", extra)
            self.assertEqual(_quiet(scaffold.run, root, root, 5, ["src/a"]), scaffold.EXIT_OK)
            self.assertEqual((root / "src/a/CLAUDE.md").read_text(encoding="utf-8"), extra)
            self.assertEqual(managed_doc.draft_state(root / "src/a/AGENTS.md"), "draft")
            self.assertEqual(_quiet(scaffold.run, root, root, 5), scaffold.EXIT_OK, "--top 에서도 후보다")
            self.assertEqual((root / "src/a/CLAUDE.md").read_text(encoding="utf-8"), extra)


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

    def test_verification_doc_says_when_to_run_and_leaves_hooks_out(self):
        # hook 은 clone 마다 따로 거는 것이라 저장소 문서의 규칙이 아니다.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._node_repo(root)
            (root / ".husky").mkdir()
            text = bootstrap.render_verification(root, [("test", "npm test")])
            self.assertIn("PR 을 올리기 전에 돌린다", text)
            for gone in ("에이전트 작업 중", "Stop hook", "--stop-hook", "pre-push"):
                self.assertNotIn(gone, text)
            lines = text.splitlines()
            self.assertLess(lines.index("pre-commit: `.husky`"), lines.index("## CI 에서"),
                            "pre-commit 도구는 로컬 절에 적는다")

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
            self.assertIn("AGENTS.md 는 심볼릭 링크다", r.stderr)
            self.assertIn("CLAUDE.md — 초안이 고쳐졌다고 본다", r.stderr, "막는 이유를 모두 적는다")
            self.assertIn(f"종료 코드 {bootstrap.EXIT_REFUSED}", r.stderr)
            self.assertTrue((root / "AGENTS.md").is_symlink())
            self.assertEqual((root / "CLAUDE.md").read_text(encoding="utf-8"), old)
            self.assertEqual(_quiet(bootstrap.run, root, ["root"], [], None, force=True), bootstrap.EXIT_OK)
            self.assertFalse((root / "AGENTS.md").is_symlink())
            self.assertTrue(managed_doc.is_ai_ready_generated(root / "AGENTS.md"))
            self.assertEqual((root / "CLAUDE.md").read_text(encoding="utf-8"), "@AGENTS.md\n")

    @unittest.skipUnless(HAS_SHELL, "bash·git 이 없다")
    def test_ignored_original_path_stops_before_writing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._node_repo(root)
            _mk(root, ".gitignore", "node_modules\nAGENTS.md\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
            for extra in ([], ["--dry-run"]):
                r = subprocess.run([sys.executable, str(SCRIPTS / "bootstrap.py"), "--target", str(root),
                                    "--only", "root,antipatterns", *extra], capture_output=True, text=True)
                self.assertEqual(r.returncode, bootstrap.EXIT_IGNORED, extra)
                self.assertIn("AGENTS.md (.gitignore:2", r.stderr)
                self.assertIn(f"종료 코드 {bootstrap.EXIT_IGNORED}", r.stderr)
            for rel in ("AGENTS.md", "CLAUDE.md", "docs/ANTIPATTERNS.md"):
                self.assertFalse((root / rel).exists(), f"원본이 무시되면 아무것도 쓰지 않는다: {rel}")
            self.assertEqual(_quiet(bootstrap.run, root, ["root"], [], None, force=True), bootstrap.EXIT_OK)
            self.assertTrue((root / "AGENTS.md").is_file())

    @unittest.skipUnless(HAS_SHELL, "bash·git 이 없다")
    def test_ignored_bridge_only_is_skipped_and_the_rest_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._node_repo(root)
            _mk(root, ".gitignore", "node_modules\nCLAUDE.md\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
            args = [sys.executable, str(SCRIPTS / "bootstrap.py"), "--target", str(root), "--only", "root,antipatterns"]
            r = subprocess.run([*args, "--dry-run"], capture_output=True, text=True)
            self.assertEqual(r.returncode, bootstrap.EXIT_OK, r.stderr)
            self.assertIn("건너뜀(git 이 무시한다 — .gitignore:2: CLAUDE.md): CLAUDE.md", r.stdout)
            r = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(r.returncode, bootstrap.EXIT_OK, r.stderr)
            self.assertTrue((root / "AGENTS.md").is_file())
            self.assertTrue((root / "docs/ANTIPATTERNS.md").is_file())
            self.assertFalse((root / "CLAUDE.md").exists(), "무시되는 다리 파일은 쓰지 않는다")
            self.assertIn("CLAUDE.local.md 가 있는 사람은 거기에 `@AGENTS.md` 를 넣거나", r.stdout)
            self.assertIn("claude-md-and-agents-md", r.stdout)
            self.assertNotIn("루트 CLAUDE.md 가 있고", r.stdout, "루트 CLAUDE.md 가 없으면 경고하지 않는다")
            # 무시되는 자리에 개인 CLAUDE.md 가 있어도 쓰지 않을 파일이라 막지 않는다.
            _mk(root, "CLAUDE.md", "# 내 메모\n")
            self.assertEqual(_quiet(bootstrap.run, root, ["root"], [], None), bootstrap.EXIT_OK)
            self.assertEqual((root / "CLAUDE.md").read_text(encoding="utf-8"), "# 내 메모\n")

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
            self.assertIn("초안이 고쳐졌다", r.stderr)
            # 고친 파일은 같은 명령을 줘도 덮지 않는다. 지우고 돌리면 다시 만든다.
            self.assertEqual(_quiet(bootstrap.run, root, ["verification"], ["make a", "make b"], None),
                             bootstrap.EXIT_REFUSED)
            sh.unlink()
            self.assertEqual(_quiet(bootstrap.run, root, ["verification"], ["make a", "make b"], None), bootstrap.EXIT_OK)
            self.assertEqual(_quiet(bootstrap.run, root, ["verification"], ["make c"], None, force=True),
                             bootstrap.EXIT_OK)
            self.assertEqual(bootstrap.checks_block(sh.read_text(encoding="utf-8")), ["make c"])

    def test_unedited_verify_sh_is_rewritten_and_a_checks_change_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(_quiet(bootstrap.run, root, ["verification"], ["make a"], None), bootstrap.EXIT_OK)
            r = subprocess.run([sys.executable, str(SCRIPTS / "bootstrap.py"), "--target", str(root),
                                "--only", "verification", "--check", "make b"], capture_output=True, text=True)
            self.assertEqual(r.returncode, bootstrap.EXIT_OK, r.stderr)
            self.assertIn("CHECKS 가 바뀐다: ['make a'] → ['make b']", r.stdout)
            self.assertEqual(bootstrap.checks_block((root / "scripts/verify.sh").read_text(encoding="utf-8")), ["make b"])

    def test_filled_draft_that_keeps_its_signature_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._node_repo(root)
            self.assertEqual(_quiet(bootstrap.run, root, ["root", "verification"], [], None), bootstrap.EXIT_OK)
            for rel in ("AGENTS.md", "docs/VERIFICATION.md", "scripts/verify.sh", ):
                self.assertEqual(managed_doc.draft_state(root / rel), "draft", rel)
            agents = root / "AGENTS.md"
            filled = agents.read_text(encoding="utf-8").replace(
                "TODO: 이 저장소가 무엇인지 한두 문장으로 적는다.", "주문 배치 작업을 모은 저장소다.")
            agents.write_text(filled, encoding="utf-8")
            for extra in ([], ["--dry-run"]):
                r = subprocess.run([sys.executable, str(SCRIPTS / "bootstrap.py"), "--target", str(root),
                                    "--only", "root,verification", *extra], capture_output=True, text=True)
                self.assertEqual(r.returncode, bootstrap.EXIT_REFUSED, extra)
                self.assertIn("AGENTS.md — 초안이 고쳐졌다", r.stderr)
                self.assertNotIn("docs/VERIFICATION.md —", r.stderr, "고치지 않은 초안은 막는 이유가 아니다")
            self.assertEqual(agents.read_text(encoding="utf-8"), filled)
            self.assertEqual(_quiet(bootstrap.run, root, ["verification"], [], None), bootstrap.EXIT_OK,
                             "고친 파일이 없는 종류는 그대로 다시 쓴다")

    def test_every_written_file_but_the_bridge_carries_a_matching_body_hash(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._node_repo(root)
            _quiet(bootstrap.run, root, list(bootstrap.KINDS), [], "order")
            for rel in ("AGENTS.md", "docs/design/README.md", "docs/design/order.md", "docs/design/order.decisions.md",
                        "docs/ANTIPATTERNS.md", "docs/VERIFICATION.md", "scripts/verify.sh", "scripts/check_docs.py"):
                self.assertEqual(managed_doc.draft_state(root / rel), "draft", rel)
            self.assertEqual((root / "CLAUDE.md").read_text(encoding="utf-8"), "@AGENTS.md\n")

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
        r = self._verify()
        self.assertEqual(r.returncode, 0)
        self.assertIn("바뀐 것이 없다", r.stdout)
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

    def test_arguments_are_refused_and_point_to_the_installer(self):
        # 옛 Stop hook 이 `--stop-hook` 으로 부르면 검사를 돌리지 않고 옮기는 법을 알린다.
        r = self._verify("--stop-hook")
        self.assertEqual(r.returncode, 1)
        self.assertIn("install_verify_hook.py", r.stderr)
        self.assertEqual(self._runs(), 0)
        self.assertEqual(self._verify("anything").returncode, 1)

    def test_failing_tree_is_run_every_time(self):
        (self.root / "FAIL").write_text("")
        self.assertEqual([self._verify().returncode for _ in range(3)], [1, 1, 1])
        self.assertEqual(self._runs(), 3, "실패는 기억하지 않는다")

    def test_root_is_the_repository_that_holds_the_script(self):
        # 다른 git 저장소 안에서 불러도 스크립트가 있는 저장소를 검사한다.
        _mk(self.root, "scripts/verify.sh", bootstrap.render_verify_sh([("test", "test -f a.txt")]))
        with tempfile.TemporaryDirectory() as other:
            subprocess.run(["git", "init", "-q"], cwd=other, check=True, capture_output=True)
            r = subprocess.run(["bash", str(self.root / "scripts/verify.sh")], cwd=other, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_root_is_the_worktree_even_when_a_git_hook_sets_git_dir(self):
        # 연결 워크트리의 git hook(husky·lefthook 이 부르는 것 포함)은 GIT_DIR 을 넣은 채 verify.sh 를 부른다.
        with tempfile.TemporaryDirectory() as d:
            wt = Path(d) / "wt"
            self._git("worktree", "add", "-q", str(wt), "-b", "wtb")
            (wt / "FAIL").write_text("")
            git_dir = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=wt, capture_output=True,
                                     text=True, check=True).stdout.strip()
            r = subprocess.run(["bash", "scripts/verify.sh"], cwd=wt, capture_output=True, text=True,
                               env={**os.environ, "GIT_DIR": git_dir})
            self.assertEqual(r.returncode, 1, "워크트리 루트의 FAIL 을 본다")

    def test_failure_clears_the_pass_record(self):
        pass_file = self.root / ".git" / "verify-pass"
        self.assertEqual(self._verify().returncode, 0)
        self.assertTrue(pass_file.is_file())
        (self.root / "FAIL").write_text("")
        self._git("add", "FAIL")
        self._git("commit", "-qm", "break")
        self.assertEqual(self._verify().returncode, 1)
        self.assertFalse(pass_file.exists(), "실패하면 통과 기록을 지운다")


OLD_STOP_HOOK = 'bash "$CLAUDE_PROJECT_DIR/scripts/verify.sh" --stop-hook'


def _git_env(base: Path) -> dict[str, str]:
    """사용자 전역 git 설정(core.hooksPath 등)이 시험에 끼지 않게 빈 전역 설정을 쓴다."""
    empty = base / "gitconfig"
    empty.touch()
    return {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": str(empty), "GIT_CONFIG_NOSYSTEM": "1"}


class _HookRepo:
    """verify.sh 가 든 clone 과 bare 원격. 검사는 FAIL 파일이 없으면 통과하고, 돌 때마다 count 에 한 줄 남긴다."""

    def __init__(self, base: Path, verify_mode: int = 0o755):
        base.mkdir(parents=True, exist_ok=True)
        self.base = base
        self.env = _git_env(base)
        self.count = base / "count"
        self.remote = base / "remote.git"
        self.root = base / "repo"
        check = f"echo run >> {shlex.quote(str(self.count))}; test ! -f FAIL"
        _mk(self.root, "scripts/verify.sh", bootstrap.render_verify_sh([("test", check)])).chmod(verify_mode)
        _mk(self.root, "a.txt", "a\n")
        self.git("init", "-q", "--bare", str(self.remote))
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-qm", "init")
        self.git("remote", "add", "origin", str(self.remote))

    @property
    def hook(self) -> Path:
        return self.root / ".git" / "hooks" / "pre-push"

    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=cwd or self.root, env=self.env, capture_output=True, text=True,
                              check=check)

    def commit(self, rel: str, cwd: Path | None = None) -> None:
        _mk(cwd or self.root, rel, "")
        self.git("add", rel, cwd=cwd)
        self.git("commit", "-qm", rel, cwd=cwd)

    def verify(self, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", "scripts/verify.sh"], cwd=cwd or self.root, env=self.env, capture_output=True,
                              text=True)

    def install(self, *args: str, target: Path | None = None,
                env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPTS / "install_verify_hook.py"),
                               "--target", str(target or self.root), *args],
                              env=env or self.env, capture_output=True, text=True)

    def push(self, *refspecs: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return self.git("push", "origin", *refspecs, cwd=cwd, check=False)

    def remote_sha(self, ref: str) -> str:
        return self.git("--git-dir", str(self.remote), "rev-parse", "--verify", "-q", ref, check=False).stdout.strip()

    def head(self, cwd: Path | None = None) -> str:
        return self.git("rev-parse", "HEAD", cwd=cwd).stdout.strip()

    def runs(self) -> int:
        return len(self.count.read_text().splitlines()) if self.count.exists() else 0

    def settings(self) -> Path:
        return self.root / ".claude" / "settings.json"


@unittest.skipUnless(HAS_SHELL, "bash·git 이 없다")
class TestPrePushHook(unittest.TestCase):
    """설치한 hook 을 실제 `git push` 로 부른다."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = _HookRepo(Path(self._tmp.name))
        self.assertEqual(self.repo.verify().returncode, 0)
        r = self.repo.install()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.runs = self.repo.runs()

    def tearDown(self):
        self._tmp.cleanup()

    def test_head_push_goes_through_when_checks_pass(self):
        self.repo.commit("b.txt")
        r = self.repo.push("HEAD:refs/heads/main")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.repo.remote_sha("refs/heads/main"), self.repo.head())
        self.assertEqual(self.repo.runs(), self.runs + 1)
        self.assertIn("ai-ready pre-push:", r.stderr)

    def test_head_push_is_refused_when_checks_fail(self):
        self.assertEqual(self.repo.push("HEAD:refs/heads/main").returncode, 0)
        before = self.repo.remote_sha("refs/heads/main")
        self.repo.commit("FAIL")
        r = self.repo.push("HEAD:refs/heads/main")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.repo.remote_sha("refs/heads/main"), before, "원격 ref 가 바뀌지 않는다")
        self.assertIn("verify: 실패", r.stderr)
        self.assertIn("git push --no-verify", r.stderr)

    def test_verify_script_without_exec_bit_still_decides_the_push(self):
        repo = _HookRepo(Path(self._tmp.name) / "noexec", verify_mode=0o644)
        self.assertEqual(repo.git("ls-files", "-s", "scripts/verify.sh").stdout[:6], "100644")
        self.assertEqual(repo.verify().returncode, 0)
        self.assertEqual(repo.install().returncode, 0)
        repo.commit("b.txt")
        r = repo.push("HEAD:refs/heads/main")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(repo.remote_sha("refs/heads/main"), repo.head())
        self.assertEqual(repo.runs(), 2, "hook 이 검사를 실제로 돌렸다")
        repo.commit("FAIL")
        r = repo.push("HEAD:refs/heads/main")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("verify: 실패", r.stderr)
        self.assertNotEqual(repo.remote_sha("refs/heads/main"), repo.head())

    def test_annotated_tag_on_head_is_checked(self):
        # 주석 달린 태그는 태그 객체의 sha 로 온다. 커밋으로 벗기지 않으면 HEAD 와 달라 보여 확인 없이 나간다.
        self.repo.commit("FAIL")
        self.repo.git("tag", "-a", "v1", "-m", "v1")
        r = self.repo.push("v1")
        self.assertNotEqual(r.returncode, 0, r.stderr)
        self.assertIn("verify: 실패", r.stderr)
        self.assertEqual(self.repo.remote_sha("refs/tags/v1"), "")
        (self.repo.root / "FAIL").unlink()
        self.repo.git("commit", "-qam", "fix")
        self.repo.git("tag", "-a", "v2", "-m", "v2")
        r = self.repo.push("v2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.repo.runs(), self.runs + 2)

    def test_up_to_date_push_says_nothing(self):
        self.assertEqual(self.repo.push("HEAD:refs/heads/main").returncode, 0)
        r = self.repo.push("HEAD:refs/heads/main")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("up-to-date", r.stderr, "전제: git 이 이미 최신이라고 알린다")
        self.assertNotIn("ai-ready pre-push:", r.stderr)

    def test_pushing_a_branch_that_is_not_head_is_not_checked(self):
        self.repo.git("branch", "other")
        self.repo.commit("FAIL")
        r = self.repo.push("other")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("지금 체크아웃(HEAD)과 달라 확인하지 않는다", r.stderr)
        self.assertTrue(self.repo.remote_sha("refs/heads/other"))
        self.assertEqual(self.repo.runs(), self.runs)

    def test_deleting_a_remote_branch_is_not_checked(self):
        self.assertEqual(self.repo.push("HEAD:refs/heads/gone").returncode, 0)
        self.repo.commit("FAIL")
        r = self.repo.push(":refs/heads/gone")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.repo.remote_sha("refs/heads/gone"), "")
        self.assertEqual(self.repo.runs(), self.runs)

    def test_delete_only_push_says_nothing(self):
        self.assertEqual(self.repo.push("HEAD:refs/heads/a", "HEAD:refs/heads/b").returncode, 0)
        self.repo.commit("FAIL")
        r = self.repo.push(":refs/heads/a", ":refs/heads/b")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[deleted]", r.stderr, "전제: 두 ref 를 실제로 지웠다")
        self.assertNotIn("ai-ready pre-push:", r.stderr)
        self.assertEqual((self.repo.remote_sha("refs/heads/a"), self.repo.remote_sha("refs/heads/b")), ("", ""))
        self.assertEqual(self.repo.runs(), self.runs)

    def test_push_with_input_larger_than_the_pipe_buffer_is_decided_by_head(self):
        # hook 은 HEAD 를 찾으면 남은 줄을 비교하지 않고 한 번에 비운다. 입력이 파이프 버퍼(64KiB)를 넘어도 결과가 맞는지 본다.
        n = 1200
        line = f"refs/tags/t{n} {'f' * 40} refs/tags/t{n} {'0' * 40}\n"
        self.assertGreater(len(line) * n, 64 * 1024, "전제: hook 에 오는 입력이 파이프 버퍼를 넘는다")

        def tag_head(prefix: str) -> None:
            head = self.repo.head()
            ops = "".join(f"create refs/tags/{prefix}{i} {head}\n" for i in range(n))
            subprocess.run(["git", "update-ref", "--stdin"], cwd=self.repo.root, env=self.repo.env, input=ops,
                           text=True, check=True)

        def remote_tags(prefix: str) -> int:
            out = self.repo.git("--git-dir", str(self.repo.remote), "for-each-ref", f"refs/tags/{prefix}*").stdout
            return len(out.splitlines())

        self.repo.commit("b.txt")
        tag_head("ok")
        r = self.repo.push("HEAD:refs/heads/main", "refs/tags/*:refs/tags/*")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.repo.remote_sha("refs/heads/main"), self.repo.head())
        self.assertEqual(remote_tags("ok"), n)
        self.assertEqual(self.repo.runs(), self.runs + 1)
        before = self.repo.remote_sha("refs/heads/main")
        self.repo.commit("FAIL")
        tag_head("bad")
        r = self.repo.push("HEAD:refs/heads/main", "refs/tags/*:refs/tags/*")
        self.assertNotEqual(r.returncode, 0, r.stderr)
        self.assertIn("verify: 실패", r.stderr)
        self.assertEqual(self.repo.remote_sha("refs/heads/main"), before)
        self.assertEqual(remote_tags("bad"), 0, "확인이 실패하면 어느 ref 도 보내지 않는다")

    def test_input_left_after_head_is_found_is_drained(self):
        # 목록을 다 읽지 않으면 push 가 깨지는 git 판이 있다. 입력을 파일로 주고, hook 이 끝난 뒤 파일 위치로 끝까지 읽었는지 본다.
        head = self.repo.head()
        lines = [f"refs/heads/main {head} refs/heads/main {'0' * 40}\n"]
        lines += [f"refs/tags/t{i} {'f' * 40} refs/tags/t{i} {'0' * 40}\n" for i in range(100)]
        stdin = Path(self._tmp.name) / "stdin"
        stdin.write_text("".join(lines))
        with stdin.open("rb") as f:
            r = subprocess.run([str(self.repo.hook), "origin", str(self.repo.remote)], stdin=f, cwd=self.repo.root,
                               env=self.repo.env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("scripts/verify.sh 를 돌린다", r.stderr, "전제: 첫 줄에서 HEAD 를 찾는다")
            self.assertEqual(os.lseek(f.fileno(), 0, os.SEEK_CUR), stdin.stat().st_size)

    def test_uncommitted_change_to_a_tracked_file_refuses_the_push(self):
        (self.repo.root / "a.txt").write_text("changed\n")
        r = self.repo.push("HEAD:refs/heads/main")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("커밋하지 않은 변경", r.stderr)
        self.assertIn("git push --no-verify", r.stderr)
        self.assertEqual(self.repo.runs(), self.runs, "확인 명령을 돌리기 전에 막는다")
        self.repo.git("add", "a.txt")
        self.assertNotEqual(self.repo.push("HEAD:refs/heads/main").returncode, 0, "스테이징한 변경도 막는다")
        self.assertEqual(self.repo.remote_sha("refs/heads/main"), "")

    def test_untracked_files_only_warn_and_are_checked(self):
        _mk(self.repo.root, "new.txt", "n\n")
        r = self.repo.push("HEAD:refs/heads/main")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("추적하지 않는 파일 1개도 확인에 들어간다", r.stderr)
        self.assertEqual(self.repo.runs(), self.runs + 1)
        _mk(self.repo.root, "FAIL", "")
        self.assertNotEqual(self.repo.push("HEAD:refs/heads/later").returncode, 0, "추적 안 하는 파일도 검사한다")

    def test_commit_without_verify_script_is_not_checked(self):
        self.repo.git("rm", "-q", "scripts/verify.sh")
        self.repo.git("commit", "-qm", "drop verify")
        r = self.repo.push("HEAD:refs/heads/main")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("scripts/verify.sh 가 없어 확인하지 않는다", r.stderr)
        self.assertEqual(self.repo.remote_sha("refs/heads/main"), self.repo.head())

    def test_push_from_a_linked_worktree_runs_the_hook(self):
        # 연결 워크트리의 hook 에는 git 이 GIT_DIR 을 넣는다. 2.0 이 만든 verify.sh 는 그것을 지우지 않으므로 hook 이
        # 지워야 한다. 안 지우면 그 verify.sh 가 scripts 폴더를 루트로 잡아 워크트리 루트의 FAIL 을 못 본다.
        script = self.repo.root / "scripts" / "verify.sh"
        text = script.read_text(encoding="utf-8")
        self.assertIn("unset GIT_DIR GIT_WORK_TREE\n", text)
        script.write_text(text.replace("unset GIT_DIR GIT_WORK_TREE\n", ""), encoding="utf-8")
        self.repo.git("commit", "-qam", "2.0 verify.sh")
        wt = Path(self._tmp.name) / "wt"
        self.repo.git("worktree", "add", "-q", str(wt), "-b", "wtb")
        r = self.repo.push("wtb", cwd=wt)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.repo.runs(), self.runs + 1, "워크트리의 통과 기록은 따로라 다시 돈다")
        before = self.repo.remote_sha("refs/heads/wtb")
        # 워크트리 루트에 FAIL 이 있어야 실패한다. hook 이 루트를 잘못 잡으면 여기서 통과해 버린다.
        self.repo.commit("FAIL", cwd=wt)
        r = self.repo.push("wtb", cwd=wt)
        self.assertNotEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.repo.remote_sha("refs/heads/wtb"), before)


@unittest.skipUnless(HAS_SHELL, "bash·git 이 없다")
class TestInstallVerifyHook(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.repo = _HookRepo(self.base)

    def tearDown(self):
        self._tmp.cleanup()

    def _pass(self) -> None:
        self.assertEqual(self.repo.verify().returncode, 0)

    def _commit_settings(self, data: object) -> None:
        """settings.json 을 커밋한다. 통과 기록보다 먼저 해야 작업 트리가 통과 때와 같다."""
        text = data if isinstance(data, str) else json.dumps(data)
        _mk(self.repo.root, ".claude/settings.json", text)
        self.repo.git("add", ".claude/settings.json")
        self.repo.git("commit", "-qm", "settings")

    def test_refuses_until_verify_has_passed_once(self):
        for args in ((), ("--dry-run",)):
            r = self.repo.install(*args)
            self.assertEqual(r.returncode, install_verify_hook.EXIT_NOT_PASSED, args)
            self.assertIn("통과 기록이 없다", r.stderr)
            self.assertIn(f"종료 코드 {install_verify_hook.EXIT_NOT_PASSED}", r.stderr)
        self.assertFalse(self.repo.hook.exists())
        self._pass()
        self.assertEqual(self.repo.install().returncode, 0)
        self.assertTrue(os.access(self.repo.hook, os.X_OK))

    def test_pass_then_breaking_commit_refuses_install(self):
        self._pass()
        self.assertEqual(self.repo.install("--dry-run").returncode, 0, "통과한 뒤에는 걸 수 있다")
        self.repo.commit("FAIL")
        self.assertEqual(self.repo.verify().returncode, 1)
        r = self.repo.install()
        self.assertEqual(r.returncode, install_verify_hook.EXIT_NOT_PASSED, "옛 통과 기록으로 걸지 않는다")
        self.assertFalse(self.repo.hook.exists())

    def test_refuses_outside_git_or_without_verify_script(self):
        with tempfile.TemporaryDirectory() as d:
            plain = Path(d)
            _mk(plain, "scripts/verify.sh", "#!/bin/sh\n")
            env = {**self.repo.env, "GIT_CEILING_DIRECTORIES": str(plain.parent)}
            r = self.repo.install(target=plain, env=env)
            self.assertEqual(r.returncode, install_verify_hook.EXIT_FAILED)
            self.assertIn("git 저장소가 아니다", r.stderr)
        self._pass()
        self.repo.git("rm", "-q", "scripts/verify.sh")
        r = self.repo.install()
        self.assertEqual(r.returncode, install_verify_hook.EXIT_FAILED)
        self.assertIn("verify.sh 를 먼저 만든다", r.stderr)
        self.assertFalse(self.repo.hook.exists())

    def test_refuses_when_core_hooks_path_is_set(self):
        self._pass()
        self.repo.git("config", "core.hooksPath", ".husky")
        r = self.repo.install()
        self.assertEqual(r.returncode, install_verify_hook.EXIT_FAILED)
        self.assertIn("core.hooksPath", r.stderr)
        self.assertIn(".husky", r.stderr)
        self.assertIn("    bash scripts/verify.sh </dev/null || exit 1\n", r.stderr)
        self.assertFalse(self.repo.hook.exists())
        self.assertFalse((self.repo.root / ".husky").exists())

    def test_hooks_path_naming_the_default_hooks_dir_is_treated_as_unset(self):
        # 값이 git 기본 hooks 폴더를 가리키면 git 은 설정이 없을 때와 같은 hook 을 돌린다. 거절하지 않는다.
        self.repo.env["HOME"] = str(self.base)
        wt = self.base / "wt"
        self.repo.git("worktree", "add", "-q", str(wt), "-b", "wtb")
        self._pass()
        self.assertEqual(self.repo.verify(cwd=wt).returncode, 0)
        common = str(self.repo.root / ".git" / "hooks")
        cases = ((common, self.repo.root), (".git/hooks", self.repo.root), ("~/repo/.git/hooks", self.repo.root),
                 (common, wt))
        for i, (value, target) in enumerate(cases):
            with self.subTest(value=value, target=target.name):
                self.repo.git("config", "core.hooksPath", value)
                r = self.repo.install("--dry-run", target=target)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("새로 만든다", r.stdout)
                self.assertFalse(self.repo.hook.exists())
                r = self.repo.install(target=target)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(self.repo.hook.is_file(), "공통 git 폴더의 hooks 에 들어간다")
                if value == ".git/hooks":
                    self.assertIn("core.hooksPath 가 상대 경로(`.git/hooks`)라 이 작업 트리에서만 돈다. 연결 워크트리에서도 "
                                  "돌게 하려면 core.hooksPath 를 지우거나 절대 경로로 바꾼다", r.stdout)
                    self.assertNotIn("모든 워크트리", r.stdout)
                else:
                    self.assertIn("이 clone 의 모든 워크트리에 걸리고 커밋되지 않는다", r.stdout)
                r = self.repo.push(f"HEAD:refs/heads/p{i}", cwd=target)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("ai-ready pre-push:", r.stderr, "git 이 설치한 hook 을 돌린다")
                r = self.repo.install("--uninstall", target=target)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertNotIn("core.hooksPath", r.stdout)
                self.assertFalse(self.repo.hook.exists())
        # 연결 워크트리에서는 상대 값이 그 워크트리 기준으로 풀려 공통 hooks 가 아니다. git 도 공통 hook 을 돌리지 않는다.
        self.repo.git("config", "core.hooksPath", ".git/hooks")
        r = self.repo.install(target=wt)
        self.assertEqual(r.returncode, install_verify_hook.EXIT_FAILED)
        self.assertIn("core.hooksPath", r.stderr)
        self.assertFalse(self.repo.hook.exists())

    def test_refuses_to_touch_a_pre_push_it_did_not_install(self):
        self._pass()
        mine = "#!/bin/sh\necho mine\n"
        _mk(self.repo.root, ".git/hooks/pre-push", mine)
        r = self.repo.install()
        self.assertEqual(r.returncode, install_verify_hook.EXIT_FAILED)
        self.assertIn("    bash scripts/verify.sh </dev/null || exit 1\n", r.stderr)
        self.assertEqual(self.repo.hook.read_text(), mine)
        r = self.repo.install("--uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("그대로 둔다", r.stdout)
        self.assertEqual(self.repo.hook.read_text(), mine)

    def test_suggested_line_decides_the_push_even_without_exec_bit(self):
        repo = _HookRepo(self.base / "addline", verify_mode=0o644)
        self.assertEqual(repo.verify().returncode, 0)
        _mk(repo.root, ".git/hooks/pre-push", "#!/bin/sh\necho mine\n").chmod(0o755)
        r = repo.install()
        self.assertEqual(r.returncode, install_verify_hook.EXIT_FAILED)
        self.assertIn(install_verify_hook.ADD_LINE, r.stderr)
        repo.hook.write_text(repo.hook.read_text() + install_verify_hook.ADD_LINE + "\n")
        repo.commit("b.txt")
        r = repo.push("HEAD:refs/heads/main")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(repo.runs(), 2, "안내한 줄이 검사를 실제로 돌렸다")
        repo.commit("FAIL")
        r = repo.push("HEAD:refs/heads/main")
        self.assertNotEqual(r.returncode, 0, r.stderr)
        self.assertNotEqual(repo.remote_sha("refs/heads/main"), repo.head())

    def test_old_stop_hook_at_the_top_is_removed_for_a_subdir_target(self):
        old = {"env": {"A": "1"}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": OLD_STOP_HOOK}]}]}}
        top = self.repo.settings()
        sub = self.repo.root / "pkg" / ".claude" / "settings.json"
        _mk(self.repo.root, ".claude/settings.json", json.dumps(old))
        _mk(self.repo.root, "pkg/.claude/settings.json", json.dumps(old))
        self.repo.git("add", "-A")
        self.repo.git("commit", "-qm", "settings")
        self._pass()
        pkg = self.repo.root / "pkg"
        r = self.repo.install("--dry-run", target=pkg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("지울 옛 Stop hook"), 2)
        self.assertEqual([json.loads(p.read_text(encoding="utf-8")) for p in (top, sub)], [old, old])
        r = self.repo.install(target=pkg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([json.loads(p.read_text(encoding="utf-8")) for p in (top, sub)], [{"env": {"A": "1"}}] * 2)
        self.assertEqual(r.stdout.count("커밋해야 한다"), 2)
        top.write_text(json.dumps(old), encoding="utf-8")
        r = self.repo.install("--uninstall", target=pkg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(top.read_text(encoding="utf-8")), {"env": {"A": "1"}})
        top.write_text(json.dumps(old), encoding="utf-8")
        r = self.repo.install("--dry-run")
        self.assertEqual(r.stdout.count("지울 옛 Stop hook"), 1, "--target 이 최상위면 같은 파일을 한 번만 본다")

    def test_install_is_idempotent_and_replaces_an_older_copy_of_its_own_hook(self):
        self._pass()
        self.assertEqual(self.repo.install().returncode, 0)
        template = (SCRIPTS / "project" / "pre-push").read_text(encoding="utf-8")
        self.assertEqual(self.repo.hook.read_text(encoding="utf-8"), template)
        self.assertEqual(self.repo.hook.stat().st_mode & 0o777, 0o755)
        r = self.repo.install()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("변경 없음", r.stdout)
        self.assertEqual(self.repo.hook.read_text(encoding="utf-8"), template)
        self.repo.hook.write_text(template.replace("scripts/verify.sh 를 돌린다", "옛 문구"), encoding="utf-8")
        r = self.repo.install()
        self.assertIn("새 내용으로 바꿨다", r.stdout)
        self.assertEqual(self.repo.hook.read_text(encoding="utf-8"), template)

    def test_dry_run_writes_nothing(self):
        settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": OLD_STOP_HOOK}]}]}}
        self._commit_settings(settings)
        self._pass()
        r = self.repo.install("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(".git/hooks/pre-push", r.stdout)
        self.assertIn("ai-ready pre-push:", r.stdout, "설치할 hook 내용을 보여 준다")
        self.assertIn(f"지울 옛 Stop hook: {OLD_STOP_HOOK}", r.stdout)
        self.assertFalse(self.repo.hook.exists())
        self.assertEqual(json.loads(self.repo.settings().read_text(encoding="utf-8")), settings)

    def test_uninstall_removes_its_hook_and_needs_no_pass(self):
        self._pass()
        self.assertEqual(self.repo.install().returncode, 0)
        (self.repo.root / ".git" / "verify-pass").unlink()
        r = self.repo.install("--uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.repo.hook.exists())
        self.assertIn("변경 없음", self.repo.install("--uninstall").stdout)

    def test_only_the_old_stop_hook_is_removed_from_settings(self):
        other = {"type": "command", "command": "echo other"}
        post = [{"matcher": "Edit", "hooks": [{"type": "command", "command": "fmt"}]}]
        self._commit_settings({"permissions": {"allow": ["Bash(ls:*)"]},
                               "hooks": {"Stop": [{"hooks": [other, {"type": "command", "command": OLD_STOP_HOOK,
                                                                     "timeout": 600}]},
                                                  {"hooks": [{"type": "command", "command": OLD_STOP_HOOK}]}],
                                         "PostToolUse": post}})
        self._pass()
        r = self.repo.install()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.repo.settings().read_text(encoding="utf-8")),
                         {"permissions": {"allow": ["Bash(ls:*)"]},
                          "hooks": {"Stop": [{"hooks": [other]}], "PostToolUse": post}})
        self.assertIn("커밋해야 한다", r.stdout)
        self.assertTrue(self.repo.hook.is_file())

    def test_emptied_hooks_object_is_dropped(self):
        self._commit_settings({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": OLD_STOP_HOOK}]}]}})
        r = self.repo.install("--uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.repo.settings().read_text(encoding="utf-8")), {})

    def test_broken_settings_json_is_left_alone_and_install_goes_on(self):
        self._commit_settings("{ not json")
        self._pass()
        r = self.repo.install()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("경고:", r.stderr)
        self.assertEqual(self.repo.settings().read_text(encoding="utf-8"), "{ not json")
        self.assertTrue(self.repo.hook.is_file())

    def test_old_stop_hook_is_removed_even_when_install_is_refused(self):
        old = {"env": {"A": "1"}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": OLD_STOP_HOOK}]}]}}

        def hooks_path(repo: _HookRepo) -> None:
            repo.git("config", "core.hooksPath", ".husky")

        def foreign(repo: _HookRepo) -> None:
            _mk(repo.root, ".git/hooks/pre-push", "#!/bin/sh\necho mine\n")

        def not_passed(repo: _HookRepo) -> None:
            (repo.root / ".git" / "verify-pass").unlink()

        for name, setup, code in (("hooks-path", hooks_path, install_verify_hook.EXIT_FAILED),
                                  ("foreign", foreign, install_verify_hook.EXIT_FAILED),
                                  ("not-passed", not_passed, install_verify_hook.EXIT_NOT_PASSED)):
            with self.subTest(name):
                repo = _HookRepo(self.base / name)
                _mk(repo.root, ".claude/settings.json", json.dumps(old))
                repo.git("add", "-A")
                repo.git("commit", "-qm", "settings")
                self.assertEqual(repo.verify().returncode, 0)
                setup(repo)
                r = repo.install("--dry-run")
                self.assertEqual(r.returncode, code, r.stderr)
                self.assertIn(f"지울 옛 Stop hook: {OLD_STOP_HOOK}", r.stdout)
                self.assertEqual(json.loads(repo.settings().read_text(encoding="utf-8")), old, "dry-run 은 쓰지 않는다")
                r = repo.install()
                self.assertEqual(r.returncode, code, r.stderr)
                self.assertEqual(json.loads(repo.settings().read_text(encoding="utf-8")), {"env": {"A": "1"}})
                self.assertIn("커밋해야 한다", r.stdout)
                self.assertNotIn("걸었다", r.stdout)

    def test_uninstall_leaves_the_hooks_path_folder_alone(self):
        self._commit_settings({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": OLD_STOP_HOOK}]}]}})
        self._pass()
        self.assertEqual(self.repo.install().returncode, 0)
        ours = self.repo.hook.read_text(encoding="utf-8")
        self.repo.git("config", "core.hooksPath", ".husky")
        husky = _mk(self.repo.root, ".husky/pre-push", "#!/bin/sh\n# ai-ready:apply 문구를 적어 둔 사람 hook\nnpm test\n")
        r = self.repo.install("--uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("core.hooksPath", r.stdout)
        self.assertTrue(husky.is_file(), "도구가 관리하는 폴더의 hook 은 지우지 않는다")
        self.assertEqual(self.repo.hook.read_text(encoding="utf-8"), ours, "hook 자리는 어느 쪽도 건드리지 않는다")
        self.assertEqual(json.loads(self.repo.settings().read_text(encoding="utf-8")), {}, "옛 Stop hook 은 지운다")

    def test_refuses_a_symlinked_pre_push_even_when_its_target_is_missing(self):
        self._pass()
        target = self.base / "shared" / "pre-push"
        self.repo.hook.parent.mkdir(parents=True, exist_ok=True)
        self.repo.hook.symlink_to(target)
        r = self.repo.install()
        self.assertEqual(r.returncode, install_verify_hook.EXIT_FAILED)
        self.assertIn("심볼릭 링크", r.stderr)
        self.assertIn("    bash scripts/verify.sh </dev/null || exit 1\n", r.stderr)
        self.assertTrue(self.repo.hook.is_symlink())
        self.assertFalse(target.exists(), "링크가 가리키는 자리에 파일을 만들지 않는다")
        _mk(target.parent, "pre-push", "#!/bin/sh\n# ai-ready:apply\n")
        r = self.repo.install()
        self.assertEqual(r.returncode, install_verify_hook.EXIT_FAILED)
        self.assertEqual(target.read_text(), "#!/bin/sh\n# ai-ready:apply\n", "표시가 있어도 링크 너머는 덮지 않는다")
        r = self.repo.install("--uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.repo.hook.is_symlink() and target.is_file(), "uninstall 도 링크를 지우지 않는다")

    def test_verify_script_is_looked_up_at_the_repository_top(self):
        # hook 은 저장소 최상위의 scripts/verify.sh 를 부른다. --target 이 하위 폴더여도 같은 자리를 본다.
        _mk(self.repo.root, "pkg/x.txt", "x\n")
        self.repo.git("add", "-A")
        self.repo.git("commit", "-qm", "pkg")
        self._pass()
        r = self.repo.install(target=self.repo.root / "pkg")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.repo.hook.is_file())
        self.assertFalse((self.repo.root / "pkg" / ".git").exists())
        self.assertIn(f"걸었다: {self.repo.root.resolve() / '.git/hooks/pre-push'} —", r.stdout)
        self.assertEqual(self.repo.install("--uninstall").returncode, 0)
        _mk(self.repo.root, "pkg/scripts/verify.sh", "#!/usr/bin/env bash\nexit 0\n")
        self.repo.git("rm", "-q", "scripts/verify.sh")
        self.repo.git("add", "-A")
        self.repo.git("commit", "-qm", "verify only under pkg")
        r = self.repo.install(target=self.repo.root / "pkg")
        self.assertEqual(r.returncode, install_verify_hook.EXIT_FAILED)
        self.assertIn(f"{self.repo.root.resolve() / 'scripts/verify.sh'} 가 없다", r.stderr)
        self.assertFalse(self.repo.hook.exists())

    def test_install_from_a_linked_worktree_goes_to_the_common_hooks_dir(self):
        wt = self.base / "wt"
        self.repo.git("worktree", "add", "-q", str(wt), "-b", "wtb")
        self.assertEqual(self.repo.verify(cwd=wt).returncode, 0)
        r = self.repo.install(target=wt)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.repo.hook.is_file(), "공통 git 폴더의 hooks 에 들어간다")
        self.assertIn("이 clone 의 모든 워크트리에 걸리고 커밋되지 않는다", r.stdout)

    def test_exported_git_dir_does_not_redirect_the_target(self):
        # 부른 쪽이 다른 저장소를 GIT_DIR·GIT_WORK_TREE 로 export 해 두어도 --target 저장소만 본다.
        other = _HookRepo(self.base / "elsewhere")
        _mk(other.root, ".claude/settings.json", json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": OLD_STOP_HOOK}]}]}}))
        self._pass()
        env = {**self.repo.env, "GIT_DIR": str(other.root / ".git"), "GIT_WORK_TREE": str(other.root),
               "GIT_INDEX_FILE": str(other.root / ".git" / "index"), "GIT_COMMON_DIR": str(other.root / ".git")}
        r = self.repo.install("--dry-run", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"pre-push hook 자리: {os.path.realpath(self.repo.hook)}\n", r.stdout)
        self.assertNotIn("elsewhere", r.stdout)
        r = self.repo.install(env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.repo.hook.is_file())
        self.assertFalse(other.hook.exists())
        self.assertIn("--stop-hook", (other.root / ".claude" / "settings.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
