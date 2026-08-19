"""스택 어댑터 테스트 — 논리 모듈 기준점을 스택마다 옳게 잡나.

stdlib only. Run with:

    python3 -m unittest tests.test_stacks

from the plugin root, or:

    python3 tests/test_stacks.py

각 테스트는 "이 판정을 되돌리면 무엇이 빨개지나" 로 읽힌다. 어댑터를 지우거나 마커를
좁히면 대응 테스트가 실패한다.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN_ROOT / "skills" / "audit" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import stacks  # noqa: E402
import scaffold  # noqa: E402


def _mk(root: Path, rel: str, content: str = "x") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


class TestJvmAdapter(unittest.TestCase):
    def test_application_marker_allows_prefix(self):
        """스프링 관례는 `FooApplication.kt` 다. 정확히 `Application.kt` 만 보면 실제
        프로젝트 대부분을 놓친다 — 이 저장소의 원본 봇이 그 사례였다."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "build.gradle.kts")
            _mk(root, "src/main/kotlin/com/acme/app/AgentRuntimeApplication.kt")
            layout = stacks.detect_layout(root)
            self.assertIsNotNone(layout)
            self.assertEqual(layout.stack, "jvm")
            self.assertEqual(layout.source_root, root / "src/main/kotlin/com/acme/app")

    def test_marker_choice_is_deterministic(self):
        """마커가 여럿이면 경로가 가장 짧은 것. rglob 은 순서를 보장하지 않아
        첫 매칭을 쓰면 실행마다 base package 가 달라진다."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "build.gradle.kts")
            _mk(root, "src/main/kotlin/com/acme/MainApplication.kt")
            _mk(root, "src/main/kotlin/com/acme/deep/nested/OtherApplication.kt")
            seen = {stacks.detect_layout(root).source_root for _ in range(5)}
            self.assertEqual(seen, {root / "src/main/kotlin/com/acme"})

    def test_library_without_application_falls_back_to_package_chain(self):
        """Application 클래스가 없는 라이브러리도 base package 를 얻는다."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "build.gradle.kts")
            _mk(root, "src/main/kotlin/com/acme/lib/parser/Parser.kt")
            _mk(root, "src/main/kotlin/com/acme/lib/writer/Writer.kt")
            layout = stacks.detect_layout(root)
            self.assertIsNotNone(layout)
            self.assertEqual(layout.source_root, root / "src/main/kotlin/com/acme/lib")

    def test_build_output_is_not_a_base_package(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "build.gradle.kts")
            _mk(root, "src/main/kotlin/build/generated/GenApplication.kt")
            _mk(root, "src/main/kotlin/com/acme/RealApplication.kt")
            layout = stacks.detect_layout(root)
            self.assertEqual(layout.source_root, root / "src/main/kotlin/com/acme")


class TestNodeAdapter(unittest.TestCase):
    def test_package_json_plus_src(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "package.json", "{}")
            _mk(root, "src/domain/turn.ts")
            _mk(root, "src/store/row.ts")
            layout = stacks.detect_layout(root)
            self.assertIsNotNone(layout)
            self.assertEqual(layout.stack, "node")
            self.assertEqual(layout.source_root, root / "src")

    def test_lib_layout(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "package.json", "{}")
            _mk(root, "lib/core/index.js")
            self.assertEqual(stacks.detect_layout(root).source_root, root / "lib")

    def test_package_json_without_source_dir_is_not_a_match(self):
        """소스 디렉토리가 없으면 기준점이 없다. 루트를 기준점으로 삼으면
        node_modules 나 문서 디렉토리가 논리 모듈로 둔갑한다."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "package.json", "{}")
            self.assertIsNone(stacks.detect_layout(root))


class TestPythonAdapter(unittest.TestCase):
    def test_src_layout_single_package(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "pyproject.toml")
            _mk(root, "src/myapp/__init__.py")
            _mk(root, "src/myapp/api/__init__.py")
            layout = stacks.detect_layout(root)
            self.assertEqual(layout.stack, "python")
            self.assertEqual(layout.source_root, root / "src/myapp")

    def test_flat_layout(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "setup.py")
            _mk(root, "myapp/__init__.py")
            _mk(root, "myapp/core/__init__.py")
            self.assertEqual(stacks.detect_layout(root).source_root, root / "myapp")


class TestGoAndRustAdapters(unittest.TestCase):
    def test_go_prefers_internal(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "go.mod")
            _mk(root, "internal/svc/svc.go")
            self.assertEqual(stacks.detect_layout(root).source_root, root / "internal")

    def test_go_without_internal_uses_module_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "go.mod")
            _mk(root, "handler/h.go")
            layout = stacks.detect_layout(root)
            self.assertEqual(layout.stack, "go")
            self.assertEqual(layout.source_root, root)

    def test_rust(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "Cargo.toml")
            _mk(root, "src/parser/mod.rs")
            self.assertEqual(stacks.detect_layout(root).stack, "rust")


class TestAdapterRegistry(unittest.TestCase):
    def test_jvm_wins_over_bundled_frontend_package_json(self):
        """Gradle 프로젝트에 프론트엔드용 package.json 이 함께 있어도 JVM 을 먼저 본다."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "build.gradle.kts")
            _mk(root, "package.json", "{}")
            _mk(root, "src/main/kotlin/com/acme/DemoApplication.kt")
            _mk(root, "src/ui/index.ts")
            self.assertEqual(stacks.detect_layout(root).stack, "jvm")

    def test_known_stacks_matches_registry(self):
        """호출부는 이 목록을 훑는다. 등록과 노출이 어긋나면 안내문이 거짓말을 한다."""
        self.assertEqual(stacks.known_stacks(), tuple(n for n, _ in stacks.ADAPTERS))

    def test_unsupported_message_names_what_it_saw(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "Gemfile")
            msg = stacks.unsupported_message(root)
            self.assertIn("Gemfile", msg)
            self.assertIn("ADAPTERS", msg)
            for name in stacks.known_stacks():
                self.assertIn(name, msg)


class TestScaffoldExitCodes(unittest.TestCase):
    """안내문은 사람만 읽는다. 종료코드가 있어야 호출한 쪽이 '안 만들어졌다' 를 센다."""

    def test_no_adapter_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "Gemfile")
            out = root / "out"
            self.assertEqual(scaffold.run(root, out, 5), scaffold.EXIT_NO_ADAPTER)

    def test_adapter_without_code_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "package.json", "{}")
            (root / "src").mkdir()
            out = root / "out"
            self.assertEqual(scaffold.run(root, out, 5), scaffold.EXIT_NO_PACKAGES)

    def test_success_exits_zero_and_writes_catalog(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "package.json", "{}")
            _mk(root, "src/domain/turn.ts")
            _mk(root, "src/store/row.ts")
            out = root / "out"
            self.assertEqual(scaffold.run(root, out, 5), scaffold.EXIT_OK)
            self.assertTrue((out / "PACKAGES.md").is_file())


class TestAgentsBridge(unittest.TestCase):
    """모듈 초안은 CLAUDE.md 하나만 쓰면 Codex 가 그 폴더를 빈 것으로 본다."""

    def test_module_scaffold_pairs_agents_md_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "mod-a/build.gradle.kts")
            _mk(root, "mod-a/src/Foo.kt")
            _mk(root, "mod-b/build.gradle.kts")
            _mk(root, "mod-b/src/Bar.kt")
            out = root / "out"
            self.assertEqual(scaffold.run(root, out, 5), scaffold.EXIT_OK)
            claude = out / "mod-a" / "CLAUDE.md"
            agents = out / "mod-a" / "AGENTS.md"
            self.assertTrue(claude.is_file())
            self.assertTrue(agents.is_symlink())
            self.assertEqual(agents.readlink(), Path("CLAUDE.md"))
            self.assertEqual(
                agents.read_text(encoding="utf-8"),
                claude.read_text(encoding="utf-8"),
            )

    def test_authored_agents_md_is_left_alone(self):
        with tempfile.TemporaryDirectory() as d:
            claude = Path(d) / "CLAUDE.md"
            claude.write_text("# body\n", encoding="utf-8")
            agents = Path(d) / "AGENTS.md"
            agents.write_text("# authored\n", encoding="utf-8")
            self.assertIsNone(scaffold.link_agents_beside(claude))
            self.assertFalse(agents.is_symlink())
            self.assertEqual(agents.read_text(encoding="utf-8"), "# authored\n")

    def test_existing_symlink_is_a_noop(self):
        with tempfile.TemporaryDirectory() as d:
            claude = Path(d) / "CLAUDE.md"
            claude.write_text("# body\n", encoding="utf-8")
            agents = Path(d) / "AGENTS.md"
            agents.symlink_to("CLAUDE.md")
            self.assertIsNone(scaffold.link_agents_beside(claude))
            self.assertTrue(agents.is_symlink())
            self.assertEqual(agents.readlink(), Path("CLAUDE.md"))


class TestCatalogTemplateIsStackNeutral(unittest.TestCase):
    """초안 문구가 한 스택의 어휘를 쓰면, 그 스택이 아닌 사람은 채울 수 없는 자리를 받는다."""

    SPRING_ONLY = ("Controller → Service", "@Profile", "ServiceTestSupport",
                   "IntegrationTestSupport", "부작용 빈")

    def test_placeholders_name_no_framework(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "package.json", "{}")
            _mk(root, "src/domain/turn.ts")
            out = root / "out"
            self.assertEqual(scaffold.run(root, out, 5), scaffold.EXIT_OK)
            text = (out / "PACKAGES.md").read_text(encoding="utf-8")
            for term in self.SPRING_ONLY:
                self.assertNotIn(term, text, f"스택 중립이어야 할 자리에 {term!r}")

    def test_role_is_not_asserted_when_stack_has_no_such_convention(self):
        """이름 규칙을 안 쓰는 스택에서 아무것도 안 잡힌 것은 '횡단' 이 아니라 '모른다' 다."""
        with tempfile.TemporaryDirectory() as d:
            pkg = Path(d) / "domain"
            pkg.mkdir()
            (pkg / "turn.ts").write_text("x", encoding="utf-8")
            self.assertIn("TODO", scaffold.detect_package_role(pkg, "node"))
            self.assertEqual(scaffold.detect_package_role(pkg, "jvm"), "횡단 / 설정 / 유틸")

    def test_role_still_reads_name_conventions_on_any_stack(self):
        """이름 규칙이 실제로 잡히면 스택과 무관하게 그대로 쓴다."""
        with tempfile.TemporaryDirectory() as d:
            pkg = Path(d) / "billing"
            pkg.mkdir()
            (pkg / "BillingService.ts").write_text("x", encoding="utf-8")
            self.assertIn("도메인", scaffold.detect_package_role(pkg, "node"))


if __name__ == "__main__":
    unittest.main()
