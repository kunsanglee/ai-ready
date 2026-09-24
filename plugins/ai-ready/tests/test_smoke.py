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

    def test_signature_without_body_hash_is_treated_as_edited(self):
        # 해시가 없는 옛 서명은 고쳤는지 알 수 없다. 안전한 쪽으로 고친 초안으로 보고 덮지 않는다.
        for text in ("# 문서 인덱스\n\n_자동 생성 (`ai-ready:apply`) — 재생성 시 전체를 덮어씁니다._\n",
                     "# 모듈 의존성\n\n_자동 생성: 2026-05-06 · 대상: `x`_\n"):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as td:
                p = Path(td) / "INDEX.md"
                p.write_text(text, encoding="utf-8")
                self.assertTrue(managed_doc.is_ai_ready_generated(p))
                self.assertEqual(managed_doc.draft_state(p), "edited")
                self.assertFalse(managed_doc.guard_overwrite(p, force=False))
                self.assertTrue(managed_doc.guard_overwrite(p, force=True))

    def test_signed_draft_is_overwritable_until_its_body_changes(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "AGENTS.md"
            p.write_text(managed_doc.sign(managed_doc.SIGNATURE_MD + "\n# a\n- TODO\n"), encoding="utf-8")
            self.assertEqual(managed_doc.draft_state(p), "draft")
            self.assertTrue(managed_doc.guard_overwrite(p, force=False))
            p.write_text(p.read_text(encoding="utf-8").replace("- TODO", "- 주문을 받는다"), encoding="utf-8")
            self.assertEqual(managed_doc.draft_state(p), "edited", "서명 줄을 남긴 채 채워도 고친 초안이다")
            self.assertFalse(managed_doc.guard_overwrite(p, force=False))

    def test_sign_is_stable_and_ignores_line_endings(self):
        text = managed_doc.SIGNATURE_MD + "\n# a\nbody\n"
        signed = managed_doc.sign(text)
        self.assertEqual(managed_doc.sign(signed), signed, "다시 서명해도 같은 줄")
        self.assertIn(managed_doc.HASH_KEY, signed.splitlines()[0])
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.md"
            p.write_bytes(signed.replace("\n", "\r\n").encode("utf-8"))
            self.assertEqual(managed_doc.draft_state(p), "draft", "CRLF 로 체크아웃돼도 고친 것이 아니다")

    def test_missing_file_allows_create(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(managed_doc.guard_overwrite(Path(td) / "NEW.md", force=False))


if __name__ == "__main__":
    unittest.main()
