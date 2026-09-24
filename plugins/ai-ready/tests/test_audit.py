"""audit.py 빈틈 보고서 테스트 — 사실을 옳게 모으나.

stdlib only. 플러그인 루트에서 `python3 -m unittest discover -s tests -t .` 로 돈다.

각 테스트는 "이 감지를 되돌리면 무엇이 빨개지나" 로 읽힌다. 보고서는 점수가 없으니 사실 하나하나가 계약이다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN_ROOT / "skills" / "audit" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import audit  # noqa: E402
import stacks  # noqa: E402


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

    def test_stop_hook_running_verify_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "scripts/verify.sh", "#!/bin/sh\n")
            settings = {"hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": 'bash "$CLAUDE_PROJECT_DIR/scripts/verify.sh" --stop-hook'}]}]}}
            _mk(root, ".claude/settings.json", json.dumps(settings))
            v = audit.doc_facts(root)["verification"]
            self.assertTrue(v["verify_script"])
            self.assertTrue(v["stop_hook_runs_verify"])


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
