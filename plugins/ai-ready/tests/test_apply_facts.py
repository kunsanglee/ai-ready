"""apply maintain 액션용 --json 사실 수집 모드 테스트 (v0.5.0+).

스크립트가 문서를 쓰지 않고 사실만 모으는 collect_facts 의 출력 모양을 고정한다.
stdlib only. 실행:
    python3 -m unittest tests.test_apply_facts
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN_ROOT / "skills" / "audit" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import gen_index  # noqa: E402
import gen_arch_diagram  # noqa: E402
import extract_section  # noqa: E402
import inject_module_map  # noqa: E402
import inject_lazy_load_index  # noqa: E402


def _write(root: Path, rel: str, content: str = "") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class TestGenIndexFacts(unittest.TestCase):
    def test_legacy_facts_shape(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "CLAUDE.md", "# root\n프로젝트 루트 문서.")
            _write(root, "docs/GUIDE.md", "# guide\n가이드 문서.")
            facts = gen_index.collect_facts(root, None, None)
            self.assertEqual(facts["mode"], "legacy")
            self.assertTrue(all("path" in d and "summary" in d for d in facts["docs"]))
            self.assertTrue(any(d["path"] == "CLAUDE.md" for d in facts["docs"]))


class TestGenArchFacts(unittest.TestCase):
    def test_edges_and_nodes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "settings.gradle.kts", 'include("app", "core")')
            _write(root, "app/build.gradle.kts", 'implementation(project(":core"))')
            _write(root, "core/build.gradle.kts", "// leaf")
            facts = gen_arch_diagram.collect_facts(root)
            self.assertIn("edges", facts)
            self.assertIn("nodes", facts)
            # 엣지는 [from, to] 리스트의 리스트
            self.assertTrue(all(isinstance(e, list) and len(e) == 2 for e in facts["edges"]))


class TestExtractSectionFacts(unittest.TestCase):
    def test_sections_shape(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "CLAUDE.md",
                   "# root\n\n## 네이밍 규칙\n클래스는 PascalCase.\n\n## 다른 섹션\n무관.")
            facts = extract_section.collect_facts(root, "naming")
            self.assertEqual(facts["kind"], "naming")
            self.assertTrue(any("네이밍" in s["heading"] for s in facts["sections"]))
            for s in facts["sections"]:
                self.assertIn("source", s)
                self.assertIn("body", s)


class TestModuleMapFacts(unittest.TestCase):
    def test_modules_with_summary_and_doc_flag(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "settings.gradle.kts", "")
            _write(root, "auth/build.gradle.kts", "")
            _write(root, "auth/CLAUDE.md", "# auth\nJWT 인증 도메인.")
            _write(root, "feed/build.gradle.kts", "")  # 문서 없음
            facts = inject_module_map.collect_facts(root)
            mods = {m["module"]: m for m in facts["modules"]}
            self.assertIn("auth", mods)
            self.assertTrue(mods["auth"]["has_doc"])
            self.assertIn("feed", mods)
            self.assertFalse(mods["feed"]["has_doc"])


class TestLazyLoadFacts(unittest.TestCase):
    def test_triggers_present_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "docs/NAMING.md", "# naming")  # 존재
            facts = inject_lazy_load_index.collect_facts(root, None)
            self.assertIn("triggers", facts)
            # 존재하는 문서의 트리거만 — label/trigger 키
            for t in facts["triggers"]:
                self.assertIn("label", t)
                self.assertIn("trigger", t)


if __name__ == "__main__":
    unittest.main()
