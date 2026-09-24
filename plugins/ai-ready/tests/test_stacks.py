"""스택 어댑터 테스트 — 논리 모듈 기준점을 스택마다 옳게 잡나.

stdlib only. Run with:

    python3 -m unittest tests.test_stacks

from the plugin root, or:

    python3 tests/test_stacks.py

각 테스트는 "이 판정을 되돌리면 무엇이 빨개지나" 로 읽힌다. 어댑터를 지우거나 마커를
좁히면 대응 테스트가 실패한다.
"""
from __future__ import annotations

import shutil
import subprocess
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

    def test_single_module_scaffolds_each_logical_module(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "package.json", "{}")
            _mk(root, "src/domain/turn.ts")
            _mk(root, "src/store/row.ts")
            out = root / "out"
            self.assertEqual(scaffold.run(root, out, 5), scaffold.EXIT_OK)
            self.assertTrue((out / "src/domain/CLAUDE.md").is_file())
            self.assertTrue((out / "src/store/CLAUDE.md").is_file())


class TestAgentsBridge(unittest.TestCase):
    """모듈 초안은 AGENTS.md 가 원본이고, 옆의 CLAUDE.md 는 `@AGENTS.md` 한 줄로 그것을 가져온다.

    Codex 는 AGENTS.md 를 읽고, Claude Code 는 한 폴더에 둘이 있으면 CLAUDE.md 만 읽는다. 심볼릭 링크는
    Windows 클론에서 한 줄짜리 파일로 풀리고 Edit·Write 도구가 링크를 따라 쓰지 않아 쓰지 않는다.
    """

    def _two_modules(self, root: Path) -> None:
        _mk(root, "mod-a/build.gradle.kts")
        _mk(root, "mod-a/src/Foo.kt")
        _mk(root, "mod-b/build.gradle.kts")
        _mk(root, "mod-b/src/Bar.kt")

    def test_module_scaffold_writes_agents_md_and_import_line(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._two_modules(root)
            out = root / "out"
            self.assertEqual(scaffold.run(root, out, 5), scaffold.EXIT_OK)
            agents = out / "mod-a" / "AGENTS.md"
            claude = out / "mod-a" / "CLAUDE.md"
            self.assertFalse(agents.is_symlink())
            self.assertFalse(claude.is_symlink())
            self.assertTrue(agents.read_text(encoding="utf-8").startswith("<!-- ai-ready:apply"))
            self.assertEqual(claude.read_text(encoding="utf-8"), "@AGENTS.md\n")

    def test_rerun_keeps_the_import_line(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._two_modules(root)
            self.assertEqual(scaffold.run(root, root, 5), scaffold.EXIT_OK)
            self.assertEqual(scaffold.run(root, root, 5), scaffold.EXIT_OK)
            self.assertEqual((root / "mod-a/CLAUDE.md").read_text(encoding="utf-8"), "@AGENTS.md\n")

    def test_authored_agents_md_is_left_alone(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._two_modules(root)
            _mk(root, "mod-a/AGENTS.md", "# authored\n")
            self.assertEqual(scaffold.run(root, root, 5), scaffold.EXIT_OK)
            self.assertEqual((root / "mod-a/AGENTS.md").read_text(encoding="utf-8"), "# authored\n")
            self.assertFalse((root / "mod-a/CLAUDE.md").exists())
            self.assertTrue((root / "mod-b/AGENTS.md").is_file())
            self.assertEqual(scaffold.run(root, root, 5, ["mod-a"]), scaffold.EXIT_REFUSED)
            self.assertEqual((root / "mod-a/AGENTS.md").read_text(encoding="utf-8"), "# authored\n")

    def test_old_symlink_layout_is_not_rewritten_without_force(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._two_modules(root)
            signed = scaffold.SIGNATURE + "\n# old\n"
            _mk(root, "mod-a/CLAUDE.md", signed)
            (root / "mod-a/AGENTS.md").symlink_to("CLAUDE.md")
            self.assertEqual(scaffold.run(root, root, 5), scaffold.EXIT_OK)
            self.assertTrue((root / "mod-a/AGENTS.md").is_symlink(), "자동 선택에서는 건너뛴다")
            self.assertEqual((root / "mod-a/CLAUDE.md").read_text(encoding="utf-8"), signed)
            self.assertEqual(scaffold.run(root, root, 5, ["mod-a"]), scaffold.EXIT_REFUSED)
            self.assertTrue((root / "mod-a/AGENTS.md").is_symlink())
            self.assertEqual(scaffold.run(root, root, 5, ["mod-a"], force=True), scaffold.EXIT_OK)
            self.assertFalse((root / "mod-a/AGENTS.md").is_symlink())
            self.assertTrue((root / "mod-a/AGENTS.md").read_text(encoding="utf-8").startswith("<!-- ai-ready:apply"))
            self.assertEqual((root / "mod-a/CLAUDE.md").read_text(encoding="utf-8"), "@AGENTS.md\n")


@unittest.skipUnless(shutil.which("git"), "git 이 없다")
class TestScaffoldIgnoredPaths(unittest.TestCase):
    def test_ignored_module_doc_stops_before_writing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _mk(root, "mod-a/build.gradle.kts")
            _mk(root, "mod-a/src/Foo.kt")
            _mk(root, ".gitignore", "CLAUDE.md\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
            self.assertEqual(scaffold.run(root, root, 5), scaffold.EXIT_IGNORED)
            self.assertFalse((root / "mod-a/AGENTS.md").exists())
            self.assertFalse((root / "mod-a/CLAUDE.md").exists())
            self.assertEqual(scaffold.run(root, root, 5, dry_run=True), scaffold.EXIT_IGNORED)
            # 초안 폴더에 쓸 때는 대상 저장소의 무시 규칙과 상관없다.
            self.assertEqual(scaffold.run(root, root / ".ai-ready" / "drafts", 5), scaffold.EXIT_OK)
            self.assertEqual(scaffold.run(root, root, 5, force=True), scaffold.EXIT_OK)
            self.assertTrue((root / "mod-a/AGENTS.md").is_file())


if __name__ == "__main__":
    unittest.main()
