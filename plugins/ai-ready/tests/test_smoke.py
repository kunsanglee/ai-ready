"""Smoke tests for ai-ready plugin scripts.

stdlib only. Run with:

    python3 -m unittest tests.test_smoke

from the plugin root, or:

    python3 tests/test_smoke.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN_ROOT / "skills" / "audit" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import audit  # noqa: E402
import dashboard  # noqa: E402
import extract_antipatterns  # noqa: E402
import scaffold  # noqa: E402


class TestGradeBands(unittest.TestCase):
    def test_grade_thresholds(self):
        self.assertEqual(audit.grade_for(95), "에이전트 자율 (Agentic-ready)")
        self.assertEqual(audit.grade_for(85), "AI 맥시멀리스트 (AI-maximalist)")
        self.assertEqual(audit.grade_for(75), "AI 활용 (AI-enabled)")
        self.assertEqual(audit.grade_for(45), "AI 인지 (AI-aware)")
        self.assertEqual(audit.grade_for(20), "AI 미인지 (AI-blind)")

    def test_grade_boundaries(self):
        self.assertEqual(audit.grade_for(90), "에이전트 자율 (Agentic-ready)")
        self.assertEqual(audit.grade_for(89), "AI 맥시멀리스트 (AI-maximalist)")
        self.assertEqual(audit.grade_for(60), "AI 활용 (AI-enabled)")
        self.assertEqual(audit.grade_for(59), "AI 인지 (AI-aware)")
        self.assertEqual(audit.grade_for(0), "AI 미인지 (AI-blind)")


class TestDoNotPatterns(unittest.TestCase):
    def test_english(self):
        self.assertTrue(audit.regex_any("DO NOT use mocks", audit.DONOT_PATTERNS))
        self.assertTrue(audit.regex_any("you MUST NOT do this", audit.DONOT_PATTERNS))
        self.assertTrue(audit.regex_any("NEVER call this directly", audit.DONOT_PATTERNS))
        self.assertTrue(audit.regex_any("Don't access this", audit.DONOT_PATTERNS))

    def test_korean_imperative(self):
        self.assertTrue(audit.regex_any("절대 하지 마세요", audit.DONOT_PATTERNS))
        self.assertTrue(audit.regex_any("절대 금지", audit.DONOT_PATTERNS))
        self.assertTrue(audit.regex_any("하면 안 됩니다", audit.DONOT_PATTERNS))
        self.assertTrue(audit.regex_any("⛔ 사용하지 마세요", audit.DONOT_PATTERNS))

    def test_korean_no_false_positive_on_descriptive(self):
        # 평서문 — false positive 가능성 텍스트
        self.assertFalse(audit.regex_any("이 일을 하지 않은 사람", audit.DONOT_PATTERNS))


class TestHasAnyPathDedupe(unittest.TestCase):
    def test_dedupe_via_realpath(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            docs = root / "docs"
            docs.mkdir()
            (docs / "INDEX.md").write_text("hi")
            # case-insensitive FS 에서는 INDEX.md 와 index.md 가 같은 파일.
            # 두 candidate 모두 매칭돼도 결과는 1개여야 함.
            found = audit.has_any_path(root, ["docs/INDEX.md", "docs/index.md"])
            self.assertEqual(len(found), 1)


class TestExtractAntipatternsCluster(unittest.TestCase):
    def test_keyword_clustering(self):
        commits = [
            {"sha": "a1", "subject": "fix Controller logging issue", "files": []},
            {"sha": "b2", "subject": "fix Controller in BFF", "files": []},
            {"sha": "c3", "subject": "fix Controller crash", "files": []},
            {"sha": "d4", "subject": "feat add new module", "files": []},
        ]
        clusters = extract_antipatterns.cluster_keywords(commits)
        words = {w for w, _, _ in clusters}
        self.assertIn("controller", words)
        # stopword 는 클러스터 결과에 없어야 함
        self.assertNotIn("fix", words)
        self.assertNotIn("feat", words)


class TestScaffoldSummaryExtraction(unittest.TestCase):
    def test_extracts_summary_from_root_claude_md(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "CLAUDE.md").write_text(
                "- [`admin`](admin/CLAUDE.md) — 별도 Spring Boot 앱.\n"
                "- [`auth`](auth/CLAUDE.md) — JWT 기반 인증 도메인.\n",
                encoding="utf-8",
            )
            self.assertEqual(
                scaffold.module_summary_from_root_claude_md(tdp, "admin"),
                "별도 Spring Boot 앱.",
            )
            self.assertEqual(
                scaffold.module_summary_from_root_claude_md(tdp, "auth"),
                "JWT 기반 인증 도메인.",
            )

    def test_returns_none_for_unknown_module(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "CLAUDE.md").write_text("nothing matching here", encoding="utf-8")
            self.assertIsNone(scaffold.module_summary_from_root_claude_md(tdp, "ghost"))


class TestDashboardSparkline(unittest.TestCase):
    def test_empty_history_no_sparkline(self):
        self.assertEqual(dashboard.render_sparkline([], "#000"), "")

    def test_single_point_history_message(self):
        out = dashboard.render_sparkline(
            [{"timestamp": "2026-01-01", "total_score": 60}], "#16a34a",
        )
        self.assertIn("다음 회차부터", out)

    def test_sparkline_renders_with_multiple_points(self):
        history = [
            {"timestamp": "2026-01-01", "total_score": 60},
            {"timestamp": "2026-02-01", "total_score": 70},
            {"timestamp": "2026-03-01", "total_score": 77},
        ]
        out = dashboard.render_sparkline(history, "#16a34a")
        self.assertIn("polyline", out)
        self.assertIn("60 → 77", out)
        self.assertIn("(+17)", out)


class TestAuditEndToEndOnEmptyRepo(unittest.TestCase):
    """가장 단순한 통합 smoke — 빈 디렉토리에 audit 돌려도 안 깨지는지."""

    def test_runs_on_empty_dir_without_crash(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            out_dir = target / ".ai-ready"
            result = audit.run(target, out_dir)
            self.assertEqual(result["max_score"], 100)
            self.assertGreaterEqual(result["total_score"], 0)
            self.assertLessEqual(result["total_score"], 100)
            # 산출물 존재 확인
            self.assertTrue((out_dir / "audit.json").exists())
            self.assertTrue((out_dir / "audit-report.md").exists())
            self.assertTrue((out_dir / "README.md").exists())
            self.assertTrue((out_dir / "history").is_dir())
            archived = list((out_dir / "history").glob("*.json"))
            self.assertEqual(len(archived), 1)

    def test_self_output_excluded_from_count(self):
        """audit 가 .ai-ready/scaffolds 안의 가짜 CLAUDE.md 를 카운트하지 않아야 한다."""
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            out_dir = target / ".ai-ready"
            out_dir.mkdir()
            (out_dir / "scaffolds").mkdir()
            (out_dir / "scaffolds" / "fake-mod").mkdir()
            (out_dir / "scaffolds" / "fake-mod" / "CLAUDE.md").write_text("# fake", encoding="utf-8")
            result = audit.run(target, out_dir)
            self.assertEqual(result["claude_doc_count"], 0,
                             "scaffolds 의 CLAUDE.md 는 점수에 카운트되면 안 됨")


if __name__ == "__main__":
    unittest.main()
