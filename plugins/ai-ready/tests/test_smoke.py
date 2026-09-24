"""ai-ready 스크립트 스모크 테스트 (표준 라이브러리만).

플러그인 루트에서 `python3 -m unittest discover -s tests -t .` 로 돈다.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN_ROOT / "skills" / "audit" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import managed_doc  # noqa: E402
import scaffold  # noqa: E402


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


class TestManagedDocGuard(unittest.TestCase):
    """v0.4.0+ 사람이 인수한(자동 생성 시그니처 없는) 문서 덮어쓰기 가드."""

    def test_human_doc_blocks_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "NAMING.md"
            p.write_text("# 네이밍 컨벤션\n\n> 충돌 시 이 문서가 권위.\n", encoding="utf-8")
            self.assertFalse(managed_doc.guard_overwrite(p, force=False))
            self.assertTrue(managed_doc.guard_overwrite(p, force=True))

    def test_new_signature_allows_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "INDEX.md"
            p.write_text("# 문서 인덱스\n\n_자동 생성 (`ai-ready:apply`) — 재생성 시 전체를 덮어씁니다._\n",
                         encoding="utf-8")
            self.assertTrue(managed_doc.is_ai_ready_generated(p))
            self.assertTrue(managed_doc.guard_overwrite(p, force=False))

    def test_legacy_signature_allows_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "ARCHITECTURE.md"
            p.write_text("# 모듈 의존성\n\n_자동 생성: 2026-05-06 · 대상: `x`_\n", encoding="utf-8")
            self.assertTrue(managed_doc.guard_overwrite(p, force=False))

    def test_missing_file_allows_create(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(managed_doc.guard_overwrite(Path(td) / "NEW.md", force=False))


if __name__ == "__main__":
    unittest.main()
