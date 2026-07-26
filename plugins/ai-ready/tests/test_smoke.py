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
import inject_module_map  # noqa: E402
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
            # 훅이 가리키는 스크립트는 실재해야 신호로 인정된다(v0.9.1 죽은 훅 게이트).
            self._write(root, "gradlew", "#!/bin/sh\nexec gradle \"$@\"\n")
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


class TestModuleMapRootStubLimit(unittest.TestCase):
    """루트 stub 의 모듈 나열 분량은 config 로 정한다. 0 이면 카탈로그 링크만.

    루트 문서는 always-loaded 라 모듈 발췌가 중복인 레포가 있다. 다만 audit 의 모듈
    경로 참조 규칙이 그 나열에 의존하는 레포도 있어 기본값은 기존 10 을 유지한다.
    """

    def _repo(self, td, config=None):
        target = Path(td)
        (target / "settings.gradle.kts").write_text(
            'rootProject.name="x"\ninclude("moda","modb")\n', encoding="utf-8")
        for m in ("moda", "modb"):
            (target / m).mkdir(parents=True, exist_ok=True)
            (target / m / "build.gradle.kts").write_text("plugins { }\n", encoding="utf-8")
            (target / m / "CLAUDE.md").write_text(f"# {m}\n\n{m} 요약.\n", encoding="utf-8")
        (target / "CLAUDE.md").write_text("# CLAUDE.md\n\n## 모듈 맵\n", encoding="utf-8")
        if config is not None:
            (target / ".ai-ready").mkdir(exist_ok=True)
            (target / ".ai-ready" / "config.json").write_text(
                json.dumps(config, ensure_ascii=False), encoding="utf-8")
        return target

    def test_default_keeps_listing(self):
        with tempfile.TemporaryDirectory() as td:
            t = self._repo(td)
            stub = inject_module_map.build_root_stub(t, inject_module_map.find_modules(t))
            self.assertIn("가이드가 작성된 핵심 모듈", stub)
            self.assertIn("](moda/CLAUDE.md)", stub)

    def test_limit_zero_drops_listing_but_keeps_catalog_link(self):
        with tempfile.TemporaryDirectory() as td:
            t = self._repo(td)
            stub = inject_module_map.build_root_stub(t, inject_module_map.find_modules(t), 0)
            self.assertNotIn("가이드가 작성된 핵심 모듈", stub)
            self.assertNotIn("](moda/CLAUDE.md)", stub)
            self.assertIn(inject_module_map.MODULE_MAP_FILE, stub,
                          "카탈로그 링크는 남아야 함")

    def test_limit_truncates(self):
        with tempfile.TemporaryDirectory() as td:
            t = self._repo(td)
            stub = inject_module_map.build_root_stub(t, inject_module_map.find_modules(t), 1)
            self.assertIn("](moda/CLAUDE.md)", stub)
            self.assertNotIn("](modb/CLAUDE.md)", stub)

    def test_config_drives_limit(self):
        with tempfile.TemporaryDirectory() as td:
            t = self._repo(td, {"version": 1, "module_map": {"root_stub_limit": 0}})
            self.assertEqual(config_loader.module_map_root_stub_limit(
                config_loader.load_config(t)), 0)

    def test_bad_config_falls_back_to_default(self):
        for bad in (-1, True, "0", None, {}):
            with tempfile.TemporaryDirectory() as td:
                t = self._repo(td, {"version": 1, "module_map": {"root_stub_limit": bad}})
                self.assertEqual(config_loader.module_map_root_stub_limit(
                    config_loader.load_config(t)), 10, f"잘못된 값 {bad!r} 은 기본값으로")

    def test_full_catalog_unaffected_by_limit(self):
        with tempfile.TemporaryDirectory() as td:
            t = self._repo(td)
            full = inject_module_map.build_full_map_doc(t, inject_module_map.find_modules(t))
            self.assertIn("`moda`", full)
            self.assertIn("`modb`", full)


class TestRootDocSizeRule(unittest.TestCase):
    """루트 CLAUDE.md 상주 분량은 줄 수가 아니라 바이트로 잰다 (v0.8.9).

    한국어 마크다운은 한 줄이 표 한 행이거나 문단 하나라 줄 수가 비용을 대변하지 못한다.
    실측 사례로 46줄짜리 루트 문서가 12,029바이트(한 불릿이 2,002자)였는데 옛 200줄 규칙에서
    만점을 받으며 계속 부풀었다. 그 구멍이 다시 열리지 않게 고정한다.
    """

    def _rule(self, root_text: str) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "CLAUDE.md").write_text(root_text, encoding="utf-8")
            result = audit.run(root, root / ".ai-ready")
            for cat in result["categories"]:
                for rule in cat["rules"]:
                    if rule["name"] == audit.ROOT_DOC_SIZE_RULE:
                        return rule
        self.fail(f"규칙 '{audit.ROOT_DOC_SIZE_RULE}' 이 결과에 없음")

    @staticmethod
    def _doc_of_bytes(n: int) -> str:
        """대략 n 바이트짜리 한 줄 문서. 한글 1자 = UTF-8 3바이트."""
        head = "# proj\n- "
        filler = "가" * max(0, (n - len(head.encode()) - 1) // 3)
        return head + filler + "\n"

    def test_thin_map_scores_full(self):
        # 하한 800 과 상한 8,000 사이의 얇은 지도 문서가 만점 자리다.
        self.assertEqual(self._rule(self._doc_of_bytes(2_000))["points"], 5)

    def test_too_short_doc_scores_partial(self):
        # v0.9.0 하한 — 상한만 있으면 0바이트 루트 문서가 만점을 받는다.
        rule = self._rule("# proj\n모듈 지도만 담은 얇은 루트 문서\n")
        self.assertEqual(rule["points"], 2)
        self.assertIn("미만", rule["note"])

    def test_one_long_line_penalised_despite_tiny_line_count(self):
        # 2줄뿐인데 12,000바이트 초과 — 옛 200줄 규칙에서는 만점이던 자리다.
        rule = self._rule(self._doc_of_bytes(12_600))
        self.assertEqual(rule["points"], 0)
        self.assertTrue(rule["evidence"],
                        "0점이어도 바이트 근거는 남아야 history 에서 추이가 보인다")

    def test_mid_size_scores_partial(self):
        self.assertEqual(self._rule(self._doc_of_bytes(9_000))["points"], 2)

    def test_evidence_carries_both_bytes_and_lines(self):
        # 다이어트 방향이 갈리므로(긴 표인가 많은 문단인가) 둘 다 남긴다.
        self.assertRegex(self._rule("# proj\n지도\n")["evidence"][0], r"[\d,]+바이트 / \d+줄")

    def test_action_hint_registered_for_renamed_rule(self):
        # 규칙 이름을 바꾸면 ACTION_HINTS 키가 어긋나 리포트에서 개선 안내가 사라진다.
        self.assertIn(audit.ROOT_DOC_SIZE_RULE, audit.ACTION_HINTS)


class TestLazyLoadSelfEvident(unittest.TestCase):
    """파일명이 곧 트리거인 문서는 표 행 대신 링크 한 줄로 묶는다 (v0.8.9).

    0.8.7 이 지운 것은 '중복' 행뿐이라, 중복이 아니면서 디렉토리 목록이 이미 말해 주는
    것 이상을 담지 않은 행은 그대로 남아 매 세션 비용만 냈다.
    """

    SELF_EVIDENT = ("[`docs/NAMING.md`](docs/NAMING.md)", "클래스/패키지/메서드/DTO 명명")
    DETAILED = ("[`docs/CONVENTIONS.md`](docs/CONVENTIONS.md)", "코드 작성 detail")

    def _auto(self, rows):
        text = (
            "# CLAUDE.md\n\n## Lazy-load docs\n\n"
            + inject_lazy_load_index.USER_BEGIN + "\n\n(아직 없음)\n\n"
            + inject_lazy_load_index.USER_END + "\n\n"
            + inject_lazy_load_index.AUTO_BEGIN + "\n\n(구)\n\n"
            + inject_lazy_load_index.AUTO_END + "\n"
        )
        new_text, _, _, _ = inject_lazy_load_index.update_root(text, rows)
        return new_text.split(inject_lazy_load_index.AUTO_BEGIN)[1].split(
            inject_lazy_load_index.AUTO_END)[0]

    def test_self_evident_row_leaves_table_but_detailed_stays(self):
        auto = self._auto([self.SELF_EVIDENT, self.DETAILED])
        self.assertIn("| 코드 작성 detail |", auto)
        self.assertNotIn("| 클래스/패키지/메서드/DTO 명명 |", auto)

    def test_link_survives_so_path_reference_count_holds(self):
        # audit 규칙 1.2 는 루트 문서의 경로 참조 수를 센다 — 묶어도 링크는 남아야 한다.
        self.assertIn("](docs/NAMING.md)", self._auto([self.SELF_EVIDENT, self.DETAILED]))

    def test_only_self_evident_rows_render_no_table(self):
        auto = self._auto([self.SELF_EVIDENT])
        self.assertNotIn("|---|---|", auto, "행이 하나도 안 남으면 빈 표를 만들지 않는다")
        self.assertIn("](docs/NAMING.md)", auto)

    def test_unknown_document_stays_a_table_row(self):
        # config 로 추가된 룰은 그 레포 맥락으로 쓴 문구라 파일명이 대신하지 못한다.
        auto = self._auto([("[`docs/MY_GUIDE.md`](docs/MY_GUIDE.md)", "우리 팀 배포 절차")])
        self.assertIn("| 우리 팀 배포 절차 |", auto)

    def test_facts_expose_self_evident_flag(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "docs").mkdir()
            (root / "docs" / "NAMING.md").write_text("# n", encoding="utf-8")
            (root / "docs" / "CONVENTIONS.md").write_text("# c", encoding="utf-8")
            flags = {t["label"]: t["self_evident"]
                     for t in inject_lazy_load_index.collect_facts(root, None)["triggers"]}
            self.assertTrue(any(v for k, v in flags.items() if "NAMING" in k))
            self.assertTrue(any(not v for k, v in flags.items() if "CONVENTIONS" in k))


STUB = "# t\na\nb\n"


def _build_stub_repo(root: Path) -> None:
    """스텁만으로 채운 레포 — v0.9.0 이전에는 이 형태가 100/100 을 받았다.

    3줄짜리 문서를 채점 대상 자리마다 하나씩 두고, 루트 문서에는 금지 한 줄과
    사용 시점 한 줄만 적는다. 실질 정보는 어디에도 없다.
    """
    (root / "docs" / "adr").mkdir(parents=True)
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "contracts").mkdir()
    (root / "metrics").mkdir()
    (root / ".claude").mkdir()
    (root / "CLAUDE.md").write_text(
        "# proj\n절대 금지: 없음\nWhen to use: 이 문서\n"
        "- [`core/CLAUDE.md`](core/CLAUDE.md)\n"
        "- [`app/CLAUDE.md`](app/CLAUDE.md)\n"
        "- [`docs/INDEX.md`](docs/INDEX.md)\n"
        "## 유지보수\n갱신 트리거: 아무때나\n", encoding="utf-8")
    for mod in ("core", "app", "web"):
        (root / mod).mkdir()
        (root / mod / "build.gradle.kts").write_text("plugins {}", encoding="utf-8")
        (root / mod / "CLAUDE.md").write_text(STUB, encoding="utf-8")
    for rel in ("docs/INDEX.md", "docs/ANTIPATTERNS.md", "docs/NAMING.md",
                "docs/TESTING.md", "docs/COMMANDS.md", "ARCHITECTURE.md",
                "docs/adr/0001-x.md", "docs/adr/0002-y.md",
                "metrics/metrics.md", "openapi.yaml", "contracts/x.md"):
        (root / rel).write_text(STUB, encoding="utf-8")
    (root / ".github" / "workflows" / "ci.yml").write_text(
        "jobs:\n  t:\n    steps:\n      - run: ./gradlew test\n", encoding="utf-8")
    (root / ".claude" / "settings.json").write_text(json.dumps({
        "hooks": {
            "PreToolUse": [{"hooks": [{"type": "command", "command": "./gradlew check"}]}],
            "Stop": [{"hooks": [{"type": "command",
                                 "command": "python3 freshness_check.py claude.md"}]}],
        }
    }), encoding="utf-8")


class TestStubGate(unittest.TestCase):
    """껍데기 문서만으로 최고 등급을 받던 구멍을 막는다 (v0.9.0).

    적대 검토 실측: 3줄짜리 스텁 21개짜리 레포가 100/100 "에이전트 자율" 을 받았다.
    원인은 두 가지였다 — 최소 내용 게이트가 비공백 3줄로 느슨했고, 여러 규칙이
    그 게이트조차 거치지 않고 파일 존재나 정규식 매칭만 봤다.
    """

    def _audit_stub_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _build_stub_repo(root)
            return audit.run(root, root / ".ai-ready")

    def test_stub_repo_no_longer_reaches_top_grade(self):
        result = self._audit_stub_repo()
        self.assertLess(result["total_score"], 60,
                        f"스텁만 있는 레포가 {result['total_score']}점 — 게이트가 뚫렸다")
        self.assertNotIn("Agentic-ready", result["grade"])

    def test_every_stub_backed_rule_scores_below_max(self):
        # 스텁으로 만점이 나오는 규칙이 하나라도 있으면 그 자리가 다음 구멍이다.
        result = self._audit_stub_repo()
        gated = {
            "모듈별 CLAUDE.md 커버리지",
            "인덱스 / MOC 파일 (docs/INDEX.md 또는 wiki/index.md)",
            "명시적 안티패턴 / 절대 금지 가이드 존재",
            "'사용 시점' 가이드 존재",
            "ANTIPATTERNS.md (또는 wiki/anti-patterns/) 존재",
            "아키텍처 의사결정 기록 (ADR / wiki/decisions)",
            "네이밍 컨벤션 문서화",
            "모듈 의존성 맵 / 다이어그램 존재",
            "모듈 간 API 계약 문서화 (OpenAPI/proto/contracts)",
            "테스트 컨벤션 문서화 (CLAUDE.md 또는 TESTING.md)",
            "매트릭스 문서 / 대시보드 존재",
            "PR 리뷰 시간 / AI 사용량 / 토큰 추적",
            # v0.9.1 (2회차 적대 검토) 에서 게이트가 확대된 규칙들.
            "루트 문서가 3개 이상의 모듈 경로/문서 참조",
            "CLAUDE.md 갱신 프로토콜 문서화",
            "기계적 검증 훅 (pre-commit / AI 에이전트 hook)",
            "CLAUDE.md / 문서 갱신 훅 또는 스케줄 존재",
        }
        seen = set()
        for cat in result["categories"]:
            for rule in cat["rules"]:
                if rule["name"] in gated:
                    seen.add(rule["name"])
                    self.assertLess(rule["points"], rule["max"],
                                    f"'{rule['name']}' 이 스텁으로 만점")
        self.assertEqual(seen, gated, "게이트 대상 규칙 이름이 코드와 어긋남")

    def test_gate_needs_both_bytes_and_lines(self):
        # 한쪽만 보면 우회된다 — 아주 긴 한 줄, 또는 한 글자짜리 줄 여럿.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            long_line = root / "long.md"
            long_line.write_text("# t\n" + "가" * 500 + "\n", encoding="utf-8")
            many_lines = root / "many.md"
            many_lines.write_text("# t\n" + "a\n" * 30, encoding="utf-8")
            real = root / "real.md"
            real.write_text("# t\n" + "실제 문장을 담은 줄입니다.\n" * 12, encoding="utf-8")
            self.assertFalse(audit._has_min_content(long_line), "줄 수 미달인데 통과")
            self.assertFalse(audit._has_min_content(many_lines), "바이트 미달인데 통과")
            self.assertTrue(audit._has_min_content(real))

    def test_module_doc_average_has_a_floor(self):
        # 종전 규칙은 "평균 50줄 이하" 라 세 줄짜리 묶음이 가장 좋은 점수를 받았다.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _build_stub_repo(root)
            result = audit.run(root, root / ".ai-ready")
            rule = next(r for c in result["categories"] for r in c["rules"]
                        if r["name"] == audit.MODULE_DOC_LEN_RULE)
            self.assertEqual(rule["points"], 2)
            self.assertIn("미만", rule["note"])

    def test_donot_guide_needs_three_lines(self):
        # 한 줄짜리 "절대 금지: 없음" 으로 만점을 받던 자리.
        def points(body: str) -> int:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                # 게이트(400바이트 + 비공백 8줄)를 넉넉히 넘기는 실질 문서로 둔다 —
                # 여기서 재려는 것은 게이트가 아니라 DO-NOT 줄 수 계단이다.
                (root / "CLAUDE.md").write_text(
                    "# proj\n" + "이 줄은 게이트를 넘기기 위한 실질 문장입니다.\n" * 12 + body,
                    encoding="utf-8")
                result = audit.run(root, root / ".ai-ready")
                return next(r["points"] for c in result["categories"] for r in c["rules"]
                            if r["name"] == "명시적 안티패턴 / 절대 금지 가이드 존재")
        self.assertEqual(points("절대 금지: 없음\n"), 3)
        self.assertEqual(points("- 절대 금지: A\n- 절대 금지: B\n- 절대 금지: C\n"), 5)

    def test_count_guide_lines_does_not_double_count_one_line(self):
        # "절대 금지" 는 두 패턴에 동시에 걸린다 — 줄 단위로 세지 않으면 부풀려진다.
        self.assertEqual(audit.count_guide_lines("절대 금지: A\n", audit.DONOT_PATTERNS), 1)


class TestRound2Gates(unittest.TestCase):
    """2회차 적대 검토가 실측으로 확정한 우회로들을 막는다 (v0.9.1).

    실측: 스텁 레포에 config 자기신고(`build_deps: ["plugins"]`)와 450바이트 잡문서 하나를
    얹으면 52점이 63점이 돼 "AI 활용" 등급에 진입했고, 존재하지 않는 파일을 가리키는 링크
    3개·스텁 옆 4KB 바이너리·스텁 문서의 "갱신 트리거" 한 줄·실재하지 않는 스크립트를
    가리키는 훅 문자열이 각각 만점을 받았다.
    """

    def _rule(self, root: Path, rule_name: str) -> dict:
        result = audit.run(root, root / ".ai-ready" / "out")
        return next(r for c in result["categories"] for r in c["rules"]
                    if r["name"] == rule_name)

    def test_broken_references_do_not_count(self):
        # 존재하지 않는 파일을 가리키는 링크 3개로 4/4 를 받던 자리.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _build_stub_repo(root)
            (root / "CLAUDE.md").write_text(
                "# proj\n"
                "- [`core/NO-SUCH.md`](core/NO-SUCH.md)\n"
                "- [`app/GHOST.md`](app/GHOST.md)\n"
                "- [`docs/MISSING.md`](docs/MISSING.md)\n", encoding="utf-8")
            rule = self._rule(root, "루트 문서가 3개 이상의 모듈 경로/문서 참조")
            self.assertEqual(rule["points"], 0)
            self.assertIn("실재하지 않거나 스텁", rule["note"])

    def test_stub_reference_targets_do_not_count(self):
        # 링크 대상이 실재해도 스텁이면 참조 수에서 뺀다.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _build_stub_repo(root)  # 루트 문서의 링크 셋이 전부 스텁을 가리킨다
            rule = self._rule(root, "루트 문서가 3개 이상의 모듈 경로/문서 참조")
            self.assertEqual(rule["points"], 0)

    def test_substantive_reference_targets_count(self):
        real = "# 문서\n" + "실질 내용을 담은 문장입니다.\n" * 12
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _build_stub_repo(root)
            for rel in ("core/CLAUDE.md", "app/CLAUDE.md", "docs/INDEX.md"):
                (root / rel).write_text(real, encoding="utf-8")
            rule = self._rule(root, "루트 문서가 3개 이상의 모듈 경로/문서 참조")
            self.assertEqual(rule["points"], 4)

    def test_binary_file_does_not_satisfy_directory_gate(self):
        # 스텁 ADR 옆 4KB 바이너리 하나로 ADR 규칙이 5/5 가 되던 자리 — errors="replace" 로
        # 읽으면 무작위 바이트도 개행 덕에 줄 수를 넘긴다.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _build_stub_repo(root)
            (root / "docs" / "adr" / "diagram.png").write_bytes(os.urandom(4096))
            rule = self._rule(root, "아키텍처 의사결정 기록 (ADR / wiki/decisions)")
            self.assertEqual(rule["points"], 2)

    def test_update_protocol_needs_nonstub_doc(self):
        # 3줄 스텁의 "갱신 트리거" 한 줄로 5/5 를 받던 자리 (형제 키워드 규칙만 게이트된 비대칭).
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _build_stub_repo(root)
            (root / "CLAUDE.md").write_text("# p\n갱신 트리거: 아무때나\nx\n", encoding="utf-8")
            rule = self._rule(root, "CLAUDE.md 갱신 프로토콜 문서화")
            self.assertEqual(rule["points"], 0)
            self.assertIn("스텁 문서에만", rule["note"])

    def test_update_protocol_in_substantive_doc_scores(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "CLAUDE.md").write_text(
                "# proj\n" + "실질 내용을 담은 문장입니다.\n" * 12 +
                "## 유지보수\n갱신 트리거: 새 패키지 추가 시\n", encoding="utf-8")
            rule = self._rule(root, "CLAUDE.md 갱신 프로토콜 문서화")
            self.assertEqual(rule["points"], 5)

    def test_dead_hook_commands_score_partial(self):
        # 스텁 픽스처의 훅은 ./gradlew 와 freshness_check.py 를 가리키는데 둘 다 레포에 없다.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _build_stub_repo(root)
            verify = self._rule(root, "기계적 검증 훅 (pre-commit / AI 에이전트 hook)")
            fresh = self._rule(root, "CLAUDE.md / 문서 갱신 훅 또는 스케줄 존재")
            self.assertEqual(verify["points"], 1)
            self.assertEqual(fresh["points"], 2)

    def test_live_hook_commands_score_full(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _build_stub_repo(root)
            (root / "gradlew").write_text("#!/bin/sh\nexec gradle \"$@\"\n", encoding="utf-8")
            (root / "freshness_check.py").write_text("print('ok')\n", encoding="utf-8")
            verify = self._rule(root, "기계적 검증 훅 (pre-commit / AI 에이전트 hook)")
            fresh = self._rule(root, "CLAUDE.md / 문서 갱신 훅 또는 스케줄 존재")
            self.assertEqual(verify["points"], 3)
            self.assertEqual(fresh["points"], 5)

    def test_config_build_deps_ignores_structural_keyword(self):
        # `plugins {}` 뿐인 매니페스트에 "plugins" 를 선언해 5/5 를 받던 자기신고 우회.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _build_stub_repo(root)
            (root / ".ai-ready").mkdir()
            (root / ".ai-ready" / "config.json").write_text(json.dumps(
                {"version": 1, "rubric": {"api_contracts": {"build_deps": ["plugins"]}}}),
                encoding="utf-8")
            rule = self._rule(root, "모듈 간 API 계약 문서화 (OpenAPI/proto/contracts)")
            self.assertEqual(rule["points"], 2, "구조 키워드 자기신고가 계약 신호로 인정됨")

    def test_config_build_deps_shorter_than_four_chars_dropped(self):
        cfg = {"rubric": {"api_contracts": {"build_deps": ["api", " rpc ", "springdoc"]}}}
        self.assertEqual(config_loader.api_contract_build_deps(cfg), ["springdoc"])

    def test_antipatterns_config_hint_overrides_stub_partial(self):
        # 스텁 ANTIPATTERNS.md 의 부분점수(2)가 config 힌트 도달을 막던 비대칭 — naming 과 동일하게.
        real = "# 컨벤션\n" + "안티패턴과 이유를 담은 문장입니다.\n" * 12
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _build_stub_repo(root)
            (root / "docs" / "CONVENTIONS.md").write_text(real, encoding="utf-8")
            (root / ".ai-ready").mkdir()
            (root / ".ai-ready" / "config.json").write_text(json.dumps(
                {"version": 1, "rubric": {"antipatterns": {"doc_hints": ["docs/CONVENTIONS.md"]}}}),
                encoding="utf-8")
            rule = self._rule(root, "ANTIPATTERNS.md (또는 wiki/anti-patterns/) 존재")
            self.assertEqual(rule["points"], 5)
            self.assertIn("config", rule["note"])

    def test_report_discloses_config_awarded_points(self):
        # 자기신고 인정분은 리포트 머리에 합산 공개된다.
        real = "# 컨벤션\n" + "안티패턴과 이유를 담은 문장입니다.\n" * 12
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _build_stub_repo(root)
            (root / "docs" / "CONVENTIONS.md").write_text(real, encoding="utf-8")
            (root / ".ai-ready").mkdir()
            (root / ".ai-ready" / "config.json").write_text(json.dumps(
                {"version": 1, "rubric": {"antipatterns": {"doc_hints": ["docs/CONVENTIONS.md"]}}}),
                encoding="utf-8")
            result = audit.run(root, root / ".ai-ready" / "out")
            report = audit.render_report(result)
            self.assertIn("config 자기신고 인정", report)

    def test_report_omits_config_line_without_config(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _build_stub_repo(root)
            result = audit.run(root, root / ".ai-ready" / "out")
            self.assertNotIn("config 자기신고 인정", audit.render_report(result))

    def test_readme_artifact_table_reflects_out_dir_reality(self):
        # audit 은 dashboard.html·scaffolds/ 를 만들지 않는다 — 없는 산출물을 표에 넣고
        # "매 실행 시 갱신" 이라 적으면 audit 만 재실행한 독자가 낡은 dashboard 를 믿는다.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _build_stub_repo(root)
            out = root / ".ai-ready" / "out"
            result = audit.run(root, out)
            readme = (out / "README.md").read_text(encoding="utf-8")
            self.assertNotIn("| `dashboard.html`", readme)
            self.assertIn("dashboard.py", readme)  # 생성 방법 안내는 있어야 한다
            self.assertNotIn("| `scaffolds/", readme)
            self.assertIn("| `hooks/freshness_check.sh`", readme)  # audit 이 실제로 복사하는 산출물
            # dashboard.html 이 생기면 표에 실리되, audit 재실행으로 갱신되지 않음을 함께 말한다.
            (out / "dashboard.html").write_text("<html></html>", encoding="utf-8")
            readme2 = audit.render_readme(result, out)
            self.assertIn("| `dashboard.html`", readme2)
            self.assertIn("갱신되지 않음", readme2)


class TestRuleNameReferences(unittest.TestCase):
    """스크립트가 규칙을 번호가 아니라 이름으로 가리키는지 (v0.9.0).

    배점표에 번호 컬럼이 없어 규칙 번호는 정의된 좌표계가 없었고, 실제로
    `Rule 1.5` 는 카테고리 1 에 규칙이 넷뿐이라 이미 존재하지 않는 번호였다.
    이름은 코드의 Rule 리터럴과 같은 문자열이라 어긋나면 이 테스트가 잡는다.
    """

    # 검사 범위: 채점 스크립트 + 배점표 + 두 스킬 문서. 규칙을 가리키는 산문이 사는 곳 전부다.
    PROSE = [
        PLUGIN_ROOT / "skills" / "audit" / "RUBRIC.md",
        PLUGIN_ROOT / "skills" / "audit" / "SKILL.md",
        PLUGIN_ROOT / "skills" / "apply" / "SKILL.md",
    ]

    @staticmethod
    def _all_rule_names() -> set[str]:
        """단일 모듈 / 멀티 모듈 두 레이아웃의 규칙 이름 합집합."""
        names = set()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = audit.run(root, root / ".ai-ready")
            names |= {r["name"] for c in result["categories"] for r in c["rules"]}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for mod in ("core", "app"):
                (root / mod).mkdir()
                (root / mod / "build.gradle.kts").write_text("plugins {}", encoding="utf-8")
            result = audit.run(root, root / ".ai-ready")
            names |= {r["name"] for c in result["categories"] for r in c["rules"]}
        return names

    def test_roi_docstrings_name_real_rules(self):
        import re
        known = self._all_rule_names()
        referenced = 0
        for script in sorted(SCRIPTS.glob("*.py")):
            lines = script.read_text(encoding="utf-8").splitlines()
            inside = False
            for line in lines:
                if line.startswith("ROI 규칙"):
                    inside = True
                    continue
                if inside:
                    if not line.strip():
                        break
                    for name in re.findall(r'"([^"]+)"', line):
                        referenced += 1
                        self.assertIn(name, known,
                                      f"{script.name} 이 없는 규칙 이름을 가리킴: {name}")
        self.assertGreater(referenced, 0, "ROI 규칙 블록을 하나도 못 찾음 — 마커가 바뀌었나")

    def test_no_numeric_rule_references_remain(self):
        # 괄호형(`rule(3.2)`)까지 잡는다 — 공백만 전제한 첫 정규식이 네 건을 놓쳤다.
        import re
        pattern = re.compile(r"rule\s*\(?\s*\d+\.\d+", re.IGNORECASE)
        offenders = []
        for path in list(SCRIPTS.glob("*.py")) + self.PROSE:
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path.name}:{i}")
        self.assertEqual(offenders, [],
                         "규칙을 번호로 가리키면 규칙이 늘거나 줄 때 조용히 밀린다")


if __name__ == "__main__":
    unittest.main()
