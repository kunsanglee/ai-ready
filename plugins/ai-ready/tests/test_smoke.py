"""Smoke tests for ai-ready plugin scripts.

stdlib only. Run with:

    python3 -m unittest tests.test_smoke

from the plugin root, or:

    python3 tests/test_smoke.py
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
import inject_lazy_load_index  # noqa: E402
import config_loader  # noqa: E402
import dashboard  # noqa: E402
import extract_antipatterns  # noqa: E402
import install_hook  # noqa: E402
import managed_doc  # noqa: E402
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


class TestConfigAwareScoring(unittest.TestCase):
    """v0.3.0+ config rubric 섹션이 채점에 반영되는지 (없으면 기존 동작)."""

    @staticmethod
    def _write(root: Path, rel: str, content: str) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def test_design_dir_counts_as_adr_via_config(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, "docs/design/domain_member.md", "# member\n결정 이력")
            self._write(root, ".ai-ready/config.json", json.dumps(
                {"version": 1, "rubric": {"decision_records": {"dir_hints": ["docs/design"]}}}))
            cfg = config_loader.load_config(root)
            scan = audit.scan_target(root, cfg)
            self.assertTrue(any("design" in d for d in scan["adr_dirs"]))

    def test_design_dir_not_counted_without_config(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, "docs/design/domain_member.md", "# member")
            scan = audit.scan_target(root, None)
            self.assertFalse(any("design" in d for d in scan["adr_dirs"]))

    def test_springdoc_counts_as_api_contract_via_config(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, "build.gradle.kts",
                        'implementation("org.springdoc:springdoc-openapi-starter-webmvc-ui")')
            self._write(root, ".ai-ready/config.json", json.dumps(
                {"version": 1, "rubric": {"api_contracts": {"build_deps": ["springdoc"]}}}))
            cfg = config_loader.load_config(root)
            scan = audit.scan_target(root, cfg)
            self.assertIn("springdoc", scan["api_build_deps"])

    def test_claude_hook_counts_as_verification_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, ".claude/settings.json", json.dumps(
                {"hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [
                    {"type": "command", "command": "./gradlew ktlintFormat"}]}]}}))
            self.assertTrue(audit._ai_harness_verification_hooks(root))

    def test_freshness_hook_excluded_from_verification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # 픽스처는 install_hook 이 실제로 써넣는 정규 경로를 그대로 쓴다(드리프트 방지).
            self._write(root, ".claude/settings.json", json.dumps(
                {"hooks": {"Stop": [{"matcher": ".*", "hooks": [
                    {"type": "command", "command": install_hook.HOOK_COMMAND}]}]}}))
            self.assertEqual(audit._ai_harness_verification_hooks(root), [])

    def test_install_hook_command_matches_documented_path(self):
        # install_hook 이 써넣는 명령은 SKILL.md / 복사본이 안내하는 경로와 같아야 한다.
        # 프로젝트 settings.json Stop hook 은 프로젝트 컨텍스트라 $CLAUDE_PROJECT_DIR 만 해석된다.
        self.assertEqual(
            install_hook.HOOK_COMMAND,
            "$CLAUDE_PROJECT_DIR/.ai-ready/hooks/freshness_check.sh",
        )


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


class TestScoreTotalsInvariant(unittest.TestCase):
    """M2: 카테고리 max 합이 배점표(100)와 어긋나지 않는지 — 레이아웃 무관.

    배점이 코드 Rule 리터럴과 RUBRIC.md 표에 이중으로 살아 드리프트할 수 있으므로,
    실행 결과의 총합을 100 으로 고정해 한쪽만 바뀌면 CI 가 잡게 한다.
    """

    def test_category_max_sums_to_100_single_module(self):
        with tempfile.TemporaryDirectory() as td:
            result = audit.run(Path(td), Path(td) / ".ai-ready")
            self.assertEqual(result["max_score"], 100)
            self.assertEqual(sum(c["max"] for c in result["categories"]), 100)

    def test_category_max_sums_to_100_multi_module(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for mod in ("core", "app"):
                (root / mod).mkdir()
                (root / mod / "build.gradle.kts").write_text("plugins {}", encoding="utf-8")
            result = audit.run(root, root / ".ai-ready")
            self.assertEqual(sum(c["max"] for c in result["categories"]), 100)


class TestEvidenceInvariant(unittest.TestCase):
    """M4: 점수를 받은 규칙은 재검증 가능한 근거(evidence 또는 note)를 가져야 한다.

    Rule.award 는 근거 없는 점수에 stderr 경고만 낸다(비강제). 이 테스트가 그 불변식을
    실효화한다 — 근거 없이 점수를 주는 규칙이 생기면 CI 가 실패한다.
    """

    def _assert_all_points_evidenced(self, result):
        for cat in result["categories"]:
            for rule in cat["rules"]:
                if rule["points"] > 0:
                    self.assertTrue(
                        rule["evidence"] or rule["note"],
                        f"규칙 '{rule['name']}' 이 근거 없이 {rule['points']}점 — 재검증 불가",
                    )

    def test_no_unevidenced_points_on_empty(self):
        with tempfile.TemporaryDirectory() as td:
            result = audit.run(Path(td), Path(td) / ".ai-ready")
            self._assert_all_points_evidenced(result)

    def test_no_unevidenced_points_on_rich_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "CLAUDE.md").write_text(
                "# proj\n절대 금지: mocks\nWhen to use: 이 문서\n"
                "- [`docs/INDEX.md`](docs/INDEX.md)\n## 갱신 트리거\n", encoding="utf-8")
            (root / "docs").mkdir()
            (root / "docs" / "INDEX.md").write_text("# index\nlinks\nmore", encoding="utf-8")
            (root / "docs" / "ANTIPATTERNS.md").write_text("# ap\n금지1\n금지2\n금지3\n", encoding="utf-8")
            (root / "docs" / "NAMING.md").write_text("# naming\nRegisterX\nQueryX\nrule3\n", encoding="utf-8")
            (root / "ARCHITECTURE.md").write_text("# arch\nmod graph\ndeps here\n", encoding="utf-8")
            result = audit.run(root, root / ".ai-ready")
            self._assert_all_points_evidenced(result)


class TestFreshnessHookStandalone(unittest.TestCase):
    """복사된 freshness 훅이 CLAUDE_PLUGIN_ROOT 없는 프로젝트 훅 환경에서 도는지.

    install_hook.py 는 `$CLAUDE_PROJECT_DIR/.ai-ready/hooks/freshness_check.sh` 를
    등록하는데, 프로젝트 훅 실행 환경에는 CLAUDE_PLUGIN_ROOT 가 없다. 복사본이
    자기 옆의 freshness_check.py 를 찾아 self-contained 로 동작해야 한다.
    """

    def test_copied_hook_runs_without_plugin_root(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            out_dir = target / ".ai-ready"
            out_dir.mkdir()
            hook_sh = audit._copy_freshness_hook(out_dir)
            self.assertIsNotNone(hook_sh, "_copy_freshness_hook 이 .sh 를 복사해야 함")
            self.assertTrue((out_dir / "hooks" / "freshness_check.py").is_file(),
                            "freshness_check.py 가 .sh 옆에 같이 복사돼야 함")
            proc = subprocess.run(
                ["bash", str(hook_sh)],
                env={"CLAUDE_PROJECT_DIR": str(target), "PATH": os.environ["PATH"]},
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0,
                             f"advisory 훅은 항상 exit 0 이어야 함 — stderr: {proc.stderr}")
            self.assertNotIn("missing", proc.stderr,
                             ".py 동반 복사로 missing 경고가 없어야 함")


class TestLazyLoadUserDedupe(unittest.TestCase):
    """user-section 이 이미 가리키는 문서는 auto 표에서 빠져야 한다.

    루트 CLAUDE.md 는 always-loaded 라, 같은 문서를 수동 표와 자동 표가 각각 가리키면
    그 중복분이 매 세션 컨텍스트를 먹는다.
    """

    ROWS = [
        ("[`docs/CONVENTIONS.md`](docs/CONVENTIONS.md)", "코드 작성 detail"),
        ("[`docs/INDEX.md`](docs/INDEX.md)", "처음 진입"),
        ("[`docs/design/`](docs/design/)", "도메인 설계 문서"),
    ]

    def _doc(self, user_rows: str) -> str:
        return (
            "# CLAUDE.md\n\n## Lazy-load docs\n\n"
            + inject_lazy_load_index.USER_BEGIN + "\n\n" + user_rows + "\n\n"
            + inject_lazy_load_index.USER_END + "\n\n"
            + inject_lazy_load_index.AUTO_BEGIN + "\n\n(구)\n\n"
            + inject_lazy_load_index.AUTO_END + "\n"
        )

    def test_drops_row_already_in_user_section(self):
        text = self._doc("| 내 트리거 | [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) |")
        new_text, changed, mode, dropped = inject_lazy_load_index.update_root(text, self.ROWS)
        self.assertEqual(mode, "updated-auto")
        self.assertTrue(changed)
        self.assertEqual(dropped, 1, "user 가 가리키는 CONVENTIONS 행만 빠져야 함")
        auto = new_text.split(inject_lazy_load_index.AUTO_BEGIN)[1]
        self.assertNotIn("](docs/CONVENTIONS.md)", auto)
        self.assertIn("](docs/INDEX.md)", auto)

    def test_trailing_slash_normalized(self):
        # user 는 `docs/design`, auto 룰은 `docs/design/` — 후행 슬래시 유무로 갈리지 않아야 함
        text = self._doc("| 내 트리거 | [`docs/design`](docs/design) |")
        _, _, _, dropped = inject_lazy_load_index.update_root(text, self.ROWS)
        self.assertEqual(dropped, 1)

    def test_empty_user_section_drops_nothing(self):
        text = self._doc("(아직 없음)")
        new_text, _, _, dropped = inject_lazy_load_index.update_root(text, self.ROWS)
        self.assertEqual(dropped, 0)
        auto = new_text.split(inject_lazy_load_index.AUTO_BEGIN)[1]
        for label, _trigger in self.ROWS:
            self.assertIn(label, auto)

    def test_all_covered_renders_note_not_empty_table(self):
        rows_md = "\n".join(f"| t | {label} |" for label, _ in self.ROWS)
        text = self._doc(rows_md)
        new_text, _, _, dropped = inject_lazy_load_index.update_root(text, self.ROWS)
        self.assertEqual(dropped, len(self.ROWS))
        auto = new_text.split(inject_lazy_load_index.AUTO_BEGIN)[1].split(
            inject_lazy_load_index.AUTO_END)[0]
        self.assertNotIn("|---|---|", auto, "빈 표 대신 안내 문장이어야 함")
        self.assertIn("이미 등재", auto)

    def test_idempotent(self):
        text = self._doc("| 내 트리거 | [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) |")
        once, _, _, _ = inject_lazy_load_index.update_root(text, self.ROWS)
        twice, changed2, _, _ = inject_lazy_load_index.update_root(once, self.ROWS)
        self.assertEqual(once, twice)
        self.assertFalse(changed2, "두 번째 실행은 변경 없음이어야 함")


if __name__ == "__main__":
    unittest.main()
