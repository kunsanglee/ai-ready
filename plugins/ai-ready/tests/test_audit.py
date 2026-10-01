"""audit.py 빈틈 보고서 테스트 — 사실을 옳게 모으나.

stdlib only. 플러그인 루트에서 `python3 -m unittest discover -s tests -t .` 로 돈다.

각 테스트는 "이 감지를 되돌리면 무엇이 빨개지나" 로 읽힌다. 보고서는 점수가 없으니 사실 하나하나가 계약이다.
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
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN_ROOT / "skills" / "audit" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import audit  # noqa: E402
import stacks  # noqa: E402

_isolation: list = []


def setUpModule():
    # 사용자 전역·시스템 git 설정(core.hooksPath·core.excludesFile 등)이 시험에 끼지 않게 한다. audit 은 이 프로세스의
    # 환경으로 git 을 부르므로 os.environ 을 바꾼다.
    tmp = tempfile.TemporaryDirectory()
    empty = Path(tmp.name) / "gitconfig"
    empty.touch()
    env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(empty), "GIT_CONFIG_NOSYSTEM": "1"})
    env.start()
    _isolation[:] = [env, tmp]


def tearDownModule():
    env, tmp = _isolation
    env.stop()
    tmp.cleanup()


def _mk(root: Path, rel: str, text: str = "x\n") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _gradle_repo(root: Path, ci: str | None = None, lint_plugin: str = "ktlint") -> None:
    _mk(root, "settings.gradle.kts", 'include(":app")\n')
    _mk(root, "build.gradle.kts", f'plugins {{ id("org.jlleitschuh.gradle.{lint_plugin}") }}\n')
    _mk(root, "gradlew", "#!/bin/sh\n")
    _mk(root, "app/build.gradle.kts", 'dependencies { testImplementation("com.tngtech.archunit:archunit") }\n')
    _mk(root, "app/src/main/kotlin/a/App.kt", "class App\n")
    if ci is not None:
        _mk(root, ".github/workflows/ci.yml", ci)


def _tool(facts: dict, name: str) -> dict | None:
    return next((t for t in facts["enforcement"]["tools"] if t["name"] == name), None)


class TestDocFacts(unittest.TestCase):
    def test_missing_root_doc_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "package.json", "{}")
            _mk(root, "src/a/x.ts")
            facts = audit.doc_facts(root)
            self.assertFalse(facts["root"]["claude_md"])
            self.assertIn("**없음**", audit.render(audit.collect(root)))

    def test_long_root_doc_is_flagged_with_size(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "CLAUDE.md", "가" * (audit.ROOT_DOC_MAX_BYTES // 3 + 10))
            facts = audit.doc_facts(root)
            self.assertTrue(facts["root"]["too_long"])
            self.assertGreater(facts["root"]["bytes"], audit.ROOT_DOC_MAX_BYTES)

    def test_agents_symlink_is_recognised(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "CLAUDE.md", "# x\n")
            os.symlink("CLAUDE.md", root / "AGENTS.md")
            self.assertEqual(audit.doc_facts(root)["root"]["agents_md"], "CLAUDE.md 심링크")

    def test_agents_original_with_import_line_is_measured_on_agents_md(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "AGENTS.md", "가" * (audit.ROOT_DOC_MAX_BYTES // 3 + 10))
            _mk(root, "CLAUDE.md", "@AGENTS.md\n")
            r = audit.doc_facts(root)["root"]
            self.assertEqual(r["body"], "AGENTS.md")
            self.assertTrue(r["too_long"], "길이는 가져오는 한 줄이 아니라 본문으로 잰다")
            self.assertIsNone(r["proposal"])
            self.assertIn("@AGENTS.md", r["layout"])

    def test_old_symlink_layout_gets_a_transition_proposal(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "CLAUDE.md", "# x\n")
            os.symlink("CLAUDE.md", root / "AGENTS.md")
            _gradle_repo(root)
            _mk(root, "app/CLAUDE.md", "# app\n")
            os.symlink("CLAUDE.md", root / "app" / "AGENTS.md")
            facts = audit.doc_facts(root)
            self.assertIn("`@AGENTS.md`", facts["root"]["proposal"])
            app = next(m for m in facts["modules"] if m["path"] == "app")
            self.assertIn("`@AGENTS.md`", app["proposal"])
            text = audit.render(audit.collect(root))
            self.assertIn("제안", text)
            self.assertIn("자동으로 바꾸지 않는다", text)
            self.assertTrue((root / "AGENTS.md").is_symlink(), "audit 은 바꾸지 않는다")

    def test_separate_files_without_import_are_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "CLAUDE.md", "# claude\n")
            _mk(root, "AGENTS.md", "# agents\n")
            self.assertIn("CLAUDE.md` 만 읽는다", audit.doc_facts(root)["root"]["proposal"])

    @unittest.skipUnless(shutil.which("git"), "git 이 없다")
    def test_ignored_generated_paths_are_reported(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _gradle_repo(root)
            _mk(root, ".gitignore", "build/\nCLAUDE.md\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
            ignored = audit.doc_facts(root)["ignored"]
            self.assertIn("CLAUDE.md", ignored)
            self.assertIn("app/CLAUDE.md", ignored)
            self.assertIn(".gitignore:2", ignored["CLAUDE.md"])
            self.assertNotIn("AGENTS.md", ignored)
            text = audit.render(audit.collect(root))
            self.assertIn("git 이 무시하는", text)
            self.assertIn("`CLAUDE.md` — `.gitignore:2", text)
            self.assertIn("문제 없음(참고)", text, "다리 파일만 무시되면 참고로만 적는다")
            self.assertNotIn("exit 6", text)

    @unittest.skipUnless(shutil.which("git"), "git 이 없다")
    def test_ignored_original_is_reported_as_a_stop(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _gradle_repo(root)
            _mk(root, ".gitignore", "docs/\n*/CLAUDE.md\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
            text = audit.render(audit.collect(root))
            self.assertIn("원본 파일이 무시 규칙에 걸린다", text)
            self.assertIn("`docs/VERIFICATION.md` — `.gitignore:1", text)
            self.assertIn("문제 없음(참고)", text)
            self.assertIn("루트 `CLAUDE.md` 는 무시되지 않는다", text, "모듈 다리 파일만 무시되면 읽히지 않는 경우를 알린다")

    def test_ignored_check_says_so_outside_git(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertIsNone(audit.doc_facts(root)["ignored"])
            self.assertIn("git 저장소가 아니라", audit.render(audit.collect(root)))

    def test_generated_paths_cover_everything_bootstrap_writes(self):
        import bootstrap  # noqa: E402 — audit 을 import 하므로 여기서만 부른다
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            planned = {p.rel for p in bootstrap.plan(root, list(bootstrap.KINDS), [("test", "make")], None)}
            self.assertLessEqual(planned, set(audit.GENERATED_ROOT_PATHS))

    def test_module_docs_follow_logical_modules(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _gradle_repo(root)
            _mk(root, "app/CLAUDE.md", "\n".join(["줄"] * (audit.MODULE_DOC_MAX_LINES + 1)))
            facts = audit.doc_facts(root)
            self.assertEqual(facts["module_mode"], "multi")
            app = next(m for m in facts["modules"] if m["path"] == "app")
            self.assertTrue(app["claude_md"])
            self.assertTrue(app["too_long"])

    def test_design_pairs_orphans_and_union_merge(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "docs/design/README.md")
            _mk(root, "docs/design/order.md")
            _mk(root, "docs/design/order.decisions.md")
            _mk(root, "docs/design/pay.md")
            _mk(root, "docs/design/ghost.decisions.md")
            _mk(root, ".gitattributes", "docs/design/*.decisions.md merge=union\n")
            design = audit.doc_facts(root)["design"]
            self.assertEqual({x["domain"]: x["decisions"] for x in design["domains"]},
                             {"order": True, "pay": False})
            self.assertEqual(design["orphan_decisions"], ["ghost"])
            self.assertTrue(design["union_merge"])

    @unittest.skipUnless(shutil.which("git"), "git 이 없다")
    def test_pre_push_hook_running_verify_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "scripts/verify.sh", "#!/bin/sh\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
            line = "git pre-push hook(이 clone, 저장소에는 없음)이 verify.sh 실행: "
            self.assertFalse(audit.doc_facts(root)["verification"]["pre_push_hook_runs_verify"])
            self.assertIn(line + "**아니오**", audit.render(audit.collect(root)))
            hook = root / ".git" / "hooks" / "pre-push"
            shutil.copy(SCRIPTS / "project" / "pre-push", hook)
            hook.chmod(0o644)
            self.assertFalse(audit.doc_facts(root)["verification"]["pre_push_hook_runs_verify"],
                             "실행 권한이 없으면 git 이 돌리지 않는다")
            hook.chmod(0o755)
            v = audit.doc_facts(root)["verification"]
            self.assertTrue(v["verify_script"])
            self.assertTrue(v["pre_push_hook_runs_verify"])
            self.assertIn(line + "예", audit.render(audit.collect(root)))
            hook.write_text("#!/bin/sh\nnpm test\n")
            self.assertFalse(audit.doc_facts(root)["verification"]["pre_push_hook_runs_verify"])

    @unittest.skipUnless(shutil.which("git"), "git 이 없다")
    def test_pre_push_hook_is_not_judged_when_core_hooks_path_is_set(self):
        # husky 는 core.hooksPath 폴더의 얇은 래퍼가 다른 파일을 부른다. 래퍼 내용으로 예·아니오를 정하지 않는다.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "scripts/verify.sh", "#!/bin/sh\n")
            _mk(root, ".husky/_/pre-push", '#!/usr/bin/env sh\n. "$(dirname "$0")/h"\n').chmod(0o755)
            _mk(root, ".husky/pre-push", "scripts/verify.sh </dev/null || exit 1\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "core.hooksPath", ".husky/_"], cwd=root, check=True, capture_output=True)
            v = audit.doc_facts(root)["verification"]
            self.assertIsNone(v["pre_push_hook_runs_verify"])
            self.assertEqual(v["core_hooks_path"], ".husky/_")
            self.assertIn("git pre-push hook(이 clone, 저장소에는 없음)이 verify.sh 실행: "
                          "확인 못 함(core.hooksPath=`.husky/_` — 그 도구 설정을 직접 본다)",
                          audit.render(audit.collect(root)))
            subprocess.run(["git", "config", "--unset", "core.hooksPath"], cwd=root, check=True, capture_output=True)
            self.assertFalse(audit.doc_facts(root)["verification"]["pre_push_hook_runs_verify"])

    @unittest.skipUnless(shutil.which("git"), "git 이 없다")
    def test_core_hooks_path_naming_the_default_hooks_dir_is_judged_like_unset(self):
        # 값이 git 기본 hooks 폴더를 가리키면 git 은 설정이 없을 때와 같은 hook 을 돌린다.
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            root = base / "repo"
            _mk(root, "scripts/verify.sh", "#!/bin/sh\n")
            git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
            subprocess.run(git + ["init", "-q"], cwd=root, check=True, capture_output=True)
            subprocess.run(git + ["add", "-A"], cwd=root, check=True, capture_output=True)
            subprocess.run(git + ["commit", "-qm", "i"], cwd=root, check=True, capture_output=True)
            wt = base / "wt"
            subprocess.run(git + ["worktree", "add", "-q", str(wt), "-b", "wtb"], cwd=root, check=True,
                           capture_output=True)
            shutil.copy(SCRIPTS / "project" / "pre-push", root / ".git" / "hooks" / "pre-push")
            (root / ".git" / "hooks" / "pre-push").chmod(0o755)
            line = "git pre-push hook(이 clone, 저장소에는 없음)이 verify.sh 실행: 예"
            with mock.patch.dict(os.environ, {"HOME": str(base)}):
                for value, target in ((str(root / ".git" / "hooks"), root), (".git/hooks", root),
                                      ("~/repo/.git/hooks", root), (str(root / ".git" / "hooks"), wt)):
                    with self.subTest(value=value, target=target.name):
                        subprocess.run(["git", "config", "core.hooksPath", value], cwd=root, check=True,
                                       capture_output=True)
                        v = audit.doc_facts(target)["verification"]
                        self.assertEqual(v["core_hooks_path"], "")
                        self.assertTrue(v["pre_push_hook_runs_verify"])
                        self.assertIn(line, audit.render(audit.collect(target)))
                # 연결 워크트리에서는 상대 값이 그 워크트리 기준으로 풀려 공통 hooks 가 아니다.
                subprocess.run(["git", "config", "core.hooksPath", ".git/hooks"], cwd=root, check=True,
                               capture_output=True)
                self.assertIsNone(audit.doc_facts(wt)["verification"]["pre_push_hook_runs_verify"])

    @unittest.skipUnless(shutil.which("git"), "git 이 없다")
    def test_empty_core_hooks_path_is_reported_as_no_with_the_reason(self):
        # 빈 값이면 git 이 hook 을 찾지 못한다. 기본 자리에 우리 hook 이 있어도 돌지 않는다.
        # 빈 값이 든 설정 파일을 알린다. 전역 설정 파일은 git 이 경로를 따옴표로 바꿔 적는 한글·공백이 든 폴더에 둔다.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            _mk(root, "scripts/verify.sh", "#!/bin/sh\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
            shutil.copy(SCRIPTS / "project" / "pre-push", root / ".git" / "hooks" / "pre-push")
            (root / ".git" / "hooks" / "pre-push").chmod(0o755)
            self.assertTrue(audit.doc_facts(root)["verification"]["pre_push_hook_runs_verify"], "전제: 설정이 없으면 돈다")

            def assert_empty_in(path: str) -> None:
                v = audit.doc_facts(root)["verification"]
                self.assertTrue(v["core_hooks_path_empty"])
                self.assertEqual(v["core_hooks_path_origin"], path)
                self.assertIs(v["pre_push_hook_runs_verify"], False)
                self.assertIn("git pre-push hook(이 clone, 저장소에는 없음)이 verify.sh 실행: **아니오**(core.hooksPath 가 "
                              f"빈 값 — git 이 hook 을 찾지 못한다. 빈 값이 든 설정 파일({path})에서 빈 값인 core.hooksPath 줄을 "
                              "지운다 — 어느 파일인지는 `git config --show-origin --get-all core.hooksPath` 로 본다)",
                              audit.render(audit.collect(root)))

            local = os.path.realpath(root / ".git" / "config")
            subprocess.run(["git", "config", "core.hooksPath", ""], cwd=root, check=True, capture_output=True)
            assert_empty_in(local)
            subprocess.run(["git", "config", "--file", local, "--unset", "core.hooksPath"], cwd=root, check=True,
                           capture_output=True)
            self.assertTrue(audit.doc_facts(root)["verification"]["pre_push_hook_runs_verify"], "안내대로 지우면 다시 돈다")
            glob = _mk(Path(d) / "전역 설정", "gitconfig", "[core]\n\thooksPath =\n")
            with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(glob)}):
                assert_empty_in(str(glob))
                subprocess.run(["git", "config", "--file", str(glob), "--unset", "core.hooksPath"], cwd=root,
                               check=True, capture_output=True)
                self.assertTrue(audit.doc_facts(root)["verification"]["pre_push_hook_runs_verify"])

    @unittest.skipUnless(shutil.which("git"), "git 이 없다")
    def test_exported_git_dir_does_not_redirect_the_target(self):
        # 부른 쪽이 다른 저장소를 GIT_DIR·GIT_WORK_TREE 로 export 해 두어도 target 저장소의 hook 을 본다.
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a", Path(d) / "b"
            for root in (a, b):
                _mk(root, "scripts/verify.sh", "#!/bin/sh\n")
                subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
            shutil.copy(SCRIPTS / "project" / "pre-push", b / ".git" / "hooks" / "pre-push")
            (b / ".git" / "hooks" / "pre-push").chmod(0o755)
            self.assertTrue(audit.doc_facts(b)["verification"]["pre_push_hook_runs_verify"], "전제: b 에는 hook 이 있다")
            with mock.patch.dict(os.environ, {"GIT_DIR": str(b / ".git"), "GIT_WORK_TREE": str(b)}):
                self.assertFalse(audit.doc_facts(a)["verification"]["pre_push_hook_runs_verify"])

    def test_old_stop_hook_running_verify_is_reported_with_the_way_out(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "scripts/verify.sh", "#!/bin/sh\n")
            settings = {"hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": 'bash "$CLAUDE_PROJECT_DIR/scripts/verify.sh" --stop-hook'}]}]}}
            _mk(root, ".claude/settings.json", json.dumps(settings))
            v = audit.doc_facts(root)["verification"]
            self.assertTrue(v["old_stop_hook_runs_verify"])
            self.assertFalse(v["pre_push_hook_runs_verify"], "git 저장소가 아니면 pre-push hook 도 없다")
            lines = [x for x in audit.render(audit.collect(root)).splitlines() if "옛 Stop hook" in x]
            self.assertEqual(len(lines), 1)
            self.assertIn("install_verify_hook.py", lines[0])
            _mk(root, ".claude/settings.json", "{}")
            self.assertNotIn("옛 Stop hook", audit.render(audit.collect(root)))

    @unittest.skipUnless(shutil.which("git"), "git 이 없다")
    def test_old_stop_hook_at_the_repository_top_is_reported_for_a_subdir_target(self):
        # 설치기와 같은 범위를 본다. target 이 하위 폴더여도 저장소 최상위 settings.json 을 보고, 같은 파일은 한 번만.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            pkg = root / "pkg"
            _mk(pkg, "x.txt", "x\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
            settings = {"hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": 'bash "$CLAUDE_PROJECT_DIR/scripts/verify.sh" --stop-hook'}]}]}}
            _mk(root, ".claude/settings.json", json.dumps(settings))
            v = audit.doc_facts(pkg)["verification"]
            self.assertTrue(v["old_stop_hook_runs_verify"])
            self.assertEqual(v["old_stop_hook_settings"], [os.path.join("..", ".claude", "settings.json")])
            lines = [x for x in audit.render(audit.collect(pkg)).splitlines() if "옛 Stop hook" in x]
            self.assertEqual(len(lines), 1)
            self.assertIn("`../.claude/settings.json` 에 옛 Stop hook", lines[0])
            self.assertEqual(audit.doc_facts(root)["verification"]["old_stop_hook_settings"],
                             [os.path.join(".claude", "settings.json")], "target 이 최상위면 같은 파일을 한 번만 본다")
            _mk(pkg, ".claude/settings.json", json.dumps(settings))
            self.assertEqual(audit.doc_facts(pkg)["verification"]["old_stop_hook_settings"],
                             [os.path.join(".claude", "settings.json"), os.path.join("..", ".claude", "settings.json")])


class TestEnforcementFacts(unittest.TestCase):
    def test_tool_run_in_ci_is_yes_with_line(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _gradle_repo(root, ci="jobs:\n  b:\n    steps:\n      - run: ./gradlew ktlintCheck test\n")
            facts = audit.collect(root)
            ktlint = _tool(facts, "ktlint")
            self.assertEqual(ktlint["ci"], "예")
            self.assertEqual(ktlint["ci_evidence"], [".github/workflows/ci.yml:4"])
            test_row = next(c for c in facts["enforcement"]["commands"] if c["role"] == "test")
            self.assertEqual(test_row["ci"], "예")

    def test_tool_absent_from_ci_is_no(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _gradle_repo(root, ci="steps:\n  - run: ./gradlew bootJar\n")
            facts = audit.collect(root)
            self.assertEqual(_tool(facts, "ktlint")["ci"], "아니오")
            self.assertEqual(_tool(facts, "ArchUnit")["ci"], "아니오")

    def test_umbrella_task_is_indirect_not_yes(self):
        # ./gradlew build 는 check·test 를 포함할 수 있지만 설정에 따라 다르다. 예 로 적으면 거짓이 된다.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _gradle_repo(root, ci="steps:\n  - run: ./gradlew build\n")
            self.assertTrue(_tool(audit.collect(root), "ktlint")["ci"].startswith("간접"))

    def test_job_name_and_excluded_task_are_not_a_test_run(self):
        # job 이름 `test:` 과 `-x test` 의 `test` 를 근거로 삼으면 테스트를 빼는 CI 가 "예" 가 된다.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _gradle_repo(root, ci="jobs:\n  test:\n    steps:\n      - run: ./gradlew bootJar -x test\n")
            facts = audit.collect(root)
            test_row = next(c for c in facts["enforcement"]["commands"] if c["command"] == "./gradlew test")
            self.assertEqual(test_row["ci"], audit.CI_EXCLUDED)
            self.assertEqual(test_row["ci_evidence"], [".github/workflows/ci.yml:4"])
            self.assertEqual(_tool(facts, "ArchUnit")["ci"], audit.CI_EXCLUDED)

    def test_umbrella_task_that_excludes_the_tool_task_is_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _gradle_repo(root, ci="steps:\n  - run: ./gradlew build -x test -x ktlintCheck\n")
            facts = audit.collect(root)
            self.assertEqual(_tool(facts, "ArchUnit")["ci"], audit.CI_EXCLUDED)
            self.assertEqual(_tool(facts, "ktlint")["ci"], audit.CI_EXCLUDED)

    def test_bare_task_counts_only_on_runner_lines(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _gradle_repo(root, ci="jobs:\n  test:\n    steps:\n      - name: gradle test\n"
                                  "      - run: ./gradlew :app:test\n")
            test_row = next(c for c in audit.collect(root)["enforcement"]["commands"] if c["role"] == "test")
            self.assertEqual((test_row["ci"], test_row["ci_evidence"]), ("예", [".github/workflows/ci.yml:5"]))

    def test_maven_skip_tests_excludes_test_command(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "pom.xml", "<project/>\n")
            _mk(root, "Jenkinsfile", "sh 'mvn package -DskipTests'\n")
            rows = {c["command"]: c["ci"] for c in audit.collect(root)["enforcement"]["commands"]}
            self.assertEqual(rows["mvn test"], audit.CI_EXCLUDED)

    def test_no_ci_file_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _gradle_repo(root)
            facts = audit.collect(root)
            self.assertEqual(facts["enforcement"]["ci_files"], [])
            self.assertEqual(_tool(facts, "ktlint")["ci"], "CI 없음")

    def test_npm_script_indirection_counts_as_ci_run(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "package.json", json.dumps({"scripts": {"lint": "eslint .", "test": "vitest run"},
                                                  "devDependencies": {"eslint": "9", "vitest": "1"}}))
            _mk(root, "eslint.config.js", "export default []\n")
            _mk(root, ".gitlab-ci.yml", "test:\n  script:\n    - npm run lint\n")
            facts = audit.collect(root)
            self.assertEqual(_tool(facts, "eslint")["ci"], "예")
            self.assertEqual(_tool(facts, "vitest")["ci"], "아니오")

    def test_dockerfile_test_exclusion_is_listed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _gradle_repo(root)
            _mk(root, "docker/api/Dockerfile", "FROM x\nRUN ./gradlew :app:bootJar -x test --no-daemon\n")
            exclusions = audit.collect(root)["enforcement"]["exclusions"]
            self.assertEqual([x["where"] for x in exclusions], ["docker/api/Dockerfile:2"])

    def test_ci_failure_swallowing_is_listed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _gradle_repo(root, ci="steps:\n  - run: ./gradlew test || true\n  - continue-on-error: true\n")
            labels = [x["label"] for x in audit.collect(root)["enforcement"]["exclusions"]]
            self.assertEqual(labels, ["실패 무시(|| true)", "실패해도 계속"])

    def test_hook_pointing_at_missing_script_is_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            settings = {"hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": "bash $CLAUDE_PROJECT_DIR/.ai-ready/hooks/check.sh"}]}]}}
            _mk(root, ".claude/settings.json", json.dumps(settings))
            hook = audit.collect(root)["enforcement"]["agent_hooks"][0]
            self.assertEqual(hook["missing"], [".ai-ready/hooks/check.sh"])
            self.assertTrue(hook["old_ai_ready"])


class TestRuleLines(unittest.TestCase):
    def _rules(self, root: Path) -> list[str]:
        return [r["text"] for r in audit.rule_lines(root)[0]]

    def test_markers_heading_items_and_fences(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "CLAUDE.md", "\n".join([
                "# 프로젝트",
                "DO NOT call the payment API directly.",
                "컨트롤러에서 레포지토리를 직접 부르는 것은 금지한다.",
                "절대경로는 설정에서 읽는다.",
                "## 늘 지키는 규칙",
                "- 시크릿은 env 로만 읽는다.",
                "설명 문단은 항목이 아니다.",
                "## 구조",
                "- src/ 아래에 코드가 있다.",
                "```",
                "never inside a fence",
                "```",
            ]))
            rules = self._rules(root)
            self.assertIn("DO NOT call the payment API directly.", rules)
            self.assertIn("컨트롤러에서 레포지토리를 직접 부르는 것은 금지한다.", rules)
            self.assertIn("- 시크릿은 env 로만 읽는다.", rules)
            self.assertNotIn("절대경로는 설정에서 읽는다.", rules)
            self.assertNotIn("설명 문단은 항목이 아니다.", rules)
            self.assertNotIn("- src/ 아래에 코드가 있다.", rules)
            self.assertNotIn("never inside a fence", rules)

    def test_fence_closes_only_with_its_own_marker(self):
        # ~~~ 블록 안의 ``` 와 ```` 블록 안의 ``` 는 펜스를 닫지 않는다. 토글로 세면 안과 밖이 뒤집혀
        # 코드 블록 안의 줄을 규칙으로 뽑고 블록 뒤의 규칙을 놓친다.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "CLAUDE.md", "\n".join([
                "~~~markdown", "```", "never inside tilde", "```", "~~~",
                "never after tilde",
                "````", "```", "never inside quad", "````",
                "never after quad",
                "```", "never inside info-closed", "``` not a close", "```",
                "never after info",
            ]))
            self.assertEqual(self._rules(root), ["never after tilde", "never after quad", "never after info"])

    def test_fence_rule_matches_check_docs(self):
        # audit.py 와 project/check_docs.py 는 번들 경계상 서로 import 하지 않고 같은 펜스 규칙을 따로 갖는다.
        # 같은 입력에 같은 줄을 남기는지 본다.
        import importlib.util
        spec = importlib.util.spec_from_file_location("_check_docs_for_parity", SCRIPTS / "project" / "check_docs.py")
        check_docs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(check_docs)
        samples = [
            "a\n```\nb\n```\nc",
            "~~~markdown\n```\nin\n```\n~~~\nout",
            "````\n```\nin\n````\nout",
            "```\nin\n``` trailing\nstill in\n```\nout",
            "  ~~~~\nin\n~~~\nstill in\n  ~~~~~\nout",
            "```\nnever closed\nx",
            "~~~\n````\nin\n~~~ \nout",
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(list(audit._outside_fences(text)), list(check_docs._outside_fences(text)))

    def test_symlinked_agents_md_is_counted_once(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "CLAUDE.md", "You must run the tests.\n")
            os.symlink("CLAUDE.md", root / "AGENTS.md")
            rows, total = audit.rule_lines(root)
            self.assertEqual(total, 1)
            self.assertEqual(rows[0]["where"], "CLAUDE.md:1", "고칠 곳인 본문 파일 경로로 적는다")

    def test_limit_keeps_entry_docs_first(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, ".claude/skills/a/SKILL.md", "never do a\n")
            _mk(root, "docs/guide.md", "never do b\n")
            _mk(root, "CLAUDE.md", "never do c\n")
            rows, total = audit.rule_lines(root, limit=2)
            self.assertEqual(total, 3)
            self.assertEqual([r["where"] for r in rows], ["CLAUDE.md:1", "docs/guide.md:1"])

    def test_changelog_is_not_a_rule_source(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "CHANGELOG.md", "- must not regress\n")
            self.assertEqual(self._rules(root), [])


class TestReportAndCli(unittest.TestCase):
    def test_report_has_three_sections_and_no_score(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _gradle_repo(root, ci="steps:\n  - run: ./gradlew test\n")
            _mk(root, "CLAUDE.md", "- NEVER push to main.\n")
            text = audit.render(audit.collect(root))
            for heading in ("## 1. 문서 존재", "## 2. 강제 수단", "## 3. 규칙 문장"):
                self.assertIn(heading, text)
            self.assertIn("R1. `CLAUDE.md:1`", text)
            self.assertNotRegex(text, r"\d+\s*/\s*100|점수:")
            self.assertIn(f"# ai-ready 빈틈 보고서 — `{root.name}`", text)
            self.assertNotIn(str(root), text, "로컬 절대 경로를 보고서에 남기지 않는다")

    def test_cli_writes_out_file_and_json(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "pyproject.toml", "[tool.ruff]\n")
            _mk(root, "pkg/__init__.py")
            out = root / ".ai-ready" / "gaps.md"
            r = subprocess.run([sys.executable, str(SCRIPTS / "audit.py"), "--target", str(root), "--out", str(out)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("## 2. 강제 수단", out.read_text(encoding="utf-8"))
            r = subprocess.run([sys.executable, str(SCRIPTS / "audit.py"), "--target", str(root), "--json"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["enforcement"]["tools"][0]["name"], "ruff")

    def test_cli_rejects_missing_target(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "audit.py"), "--target", "/nonexistent/x"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


class TestDetectCommands(unittest.TestCase):
    def test_gradle_prefers_wrapper_and_finds_lint(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _gradle_repo(root)
            c = stacks.detect_commands(root)
            self.assertEqual((c.build_system, c.lint, c.test), ("gradle", "./gradlew ktlintCheck", "./gradlew test"))

    def test_npm_placeholder_test_script_is_not_a_test(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "package.json", json.dumps({"scripts": {
                "test": 'echo "Error: no test specified" && exit 1'}}))
            self.assertEqual(stacks.detect_commands(root).test, "")

    def test_pnpm_lockfile_picks_pnpm(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "package.json", json.dumps({"scripts": {"typecheck": "tsc -p .", "test": "vitest"}}))
            _mk(root, "pnpm-lock.yaml", "")
            c = stacks.detect_commands(root)
            self.assertEqual(c.checks(), [("typecheck", "pnpm run typecheck"), ("test", "pnpm test")])

    def test_unknown_stack_has_no_commands(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(stacks.detect_commands(Path(d)).checks(), [])


if __name__ == "__main__":
    unittest.main()
