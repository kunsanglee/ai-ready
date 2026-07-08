"""detect_build.py (loop 어댑터 감지기) 회귀 테스트.

stdlib only. 실행:
    python3 _loop-engine/test_detect_build.py
test.sh 가 마지막 섹션에서 이 파일을 호출한다.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import detect_build  # noqa: E402


def _write(root: Path, rel: str, content: str = "") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class TestDetectBuildSystem(unittest.TestCase):
    def test_gradle_with_wrapper_and_ktlint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "build.gradle.kts", 'plugins { id("org.jlleitschuh.gradle.ktlint") }')
            _write(root, "gradlew", "#!/bin/sh\n")
            b = detect_build.detect_build_system(root)
            self.assertEqual(b["build_system"], "gradle")
            self.assertEqual(b["build_cmd"], "./gradlew assemble -x test")
            self.assertEqual(b["test_cmd"], "./gradlew test")
            self.assertEqual(b["lint_cmd"], "./gradlew ktlintCheck")

    def test_gradle_without_wrapper_uses_bare_gradle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "build.gradle", "// groovy dsl")
            b = detect_build.detect_build_system(root)
            self.assertEqual(b["build_cmd"], "gradle assemble -x test")
            self.assertEqual(b["lint_cmd"], "")

    def test_npm_only_scripts_present_become_commands(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "package.json", '{"scripts": {"build": "tsc", "lint": "eslint ."}}')
            b = detect_build.detect_build_system(root)
            self.assertEqual(b["build_system"], "npm")
            self.assertEqual(b["build_cmd"], "npm run build")
            self.assertEqual(b["lint_cmd"], "npm run lint")
            self.assertEqual(b["test_cmd"], "")

    def test_pnpm_detected_from_lockfile(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "package.json", '{"scripts": {"test": "vitest"}}')
            _write(root, "pnpm-lock.yaml", "")
            b = detect_build.detect_build_system(root)
            self.assertEqual(b["build_system"], "pnpm")
            self.assertEqual(b["test_cmd"], "pnpm test")

    def test_npm_default_test_stub_treated_as_absent(self):
        # npm init 기본 스텁은 항상 exit 1 — 게이트로 채택하면 maker 가 못 고치는 공회전이 된다.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "package.json",
                   '{"scripts": {"test": "echo \\"Error: no test specified\\" && exit 1"}}')
            b = detect_build.detect_build_system(root)
            self.assertEqual(b["test_cmd"], "")

    def test_cargo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "Cargo.toml", "[package]\nname='x'")
            b = detect_build.detect_build_system(root)
            self.assertEqual(b["build_system"], "cargo")
            self.assertEqual(b["lint_cmd"], "cargo clippy")

    def test_unknown_when_no_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            b = detect_build.detect_build_system(Path(td))
            self.assertEqual(b["build_system"], "unknown")
            self.assertEqual(b["build_cmd"], "")


class TestDetectStack(unittest.TestCase):
    def test_spring_jpa_postgres_from_gradle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "build.gradle.kts",
                   'implementation("org.springframework.boot:spring-boot-starter-data-jpa")\n'
                   'runtimeOnly("org.postgresql:postgresql")')
            stack = detect_build.detect_stack(root)
            self.assertIn("spring", stack)
            self.assertIn("jpa", stack)
            self.assertIn("postgres", stack)

    def test_no_stack_for_plain_node(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "package.json", '{"dependencies": {"express": "^4"}}')
            self.assertEqual(detect_build.detect_stack(root), [])

    def test_postgres_from_application_yml_in_submodule(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "build.gradle.kts", "// no db dep here")
            _write(root, "core/src/main/resources/application.yml",
                   "spring:\n  datasource:\n    url: jdbc:postgresql://localhost/db")
            self.assertIn("postgres", detect_build.detect_stack(root))


class TestLocalKinds(unittest.TestCase):
    def test_ddl_safety_for_postgres(self):
        with tempfile.TemporaryDirectory() as td:
            kinds = detect_build.local_kinds_for_stack(Path(td), ["postgres"])
            ddl = next(k for k in kinds if k["kind_id"] == "ddl-safety")
            self.assertEqual(ddl["base_severity"], "BLOCKER")
            self.assertEqual(ddl["force_await"], "always")

    def test_i18n_requires_spring_and_error_code_signal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertEqual(detect_build.local_kinds_for_stack(root, ["spring"]), [])
            _write(root, "core-common/src/main/resources/message.properties", "x=y")
            kinds = detect_build.local_kinds_for_stack(root, ["spring"])
            self.assertIn("i18n-key-missing", [k["kind_id"] for k in kinds])

    def test_no_kinds_without_stack(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(detect_build.local_kinds_for_stack(Path(td), []), [])


class TestConventionDocs(unittest.TestCase):
    def test_collects_docs_and_picks_antipatterns_as_knowledge(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "docs/ANTIPATTERNS.md", "# ap")
            _write(root, "docs/NAMING.md", "# naming")
            docs, knowledge = detect_build.detect_convention_docs(root)
            self.assertIn("docs/ANTIPATTERNS.md", docs)
            self.assertIn("docs/NAMING.md", docs)
            self.assertEqual(knowledge, "docs/ANTIPATTERNS.md")

    def test_empty_when_no_docs(self):
        with tempfile.TemporaryDirectory() as td:
            docs, knowledge = detect_build.detect_convention_docs(Path(td))
            self.assertEqual(docs, [])
            self.assertEqual(knowledge, "")


class TestGitFallbacks(unittest.TestCase):
    def test_ticket_regex_default_on_non_git(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(detect_build.infer_ticket_regex(Path(td)), "[A-Z]+-[0-9]+")

    def test_base_branch_default_on_non_git(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(detect_build.detect_base_branch(Path(td)), "origin/main")


class TestDetectShape(unittest.TestCase):
    def test_detect_returns_all_keys(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "Cargo.toml", "[package]\nname='x'")
            d = detect_build.detect(root)
            for key in ("build_system", "build_cmd", "test_cmd", "lint_cmd", "stack",
                        "convention_docs", "knowledge_layer", "ticket_regex",
                        "base_branch", "local_kinds"):
                self.assertIn(key, d)


if __name__ == "__main__":
    unittest.main()
