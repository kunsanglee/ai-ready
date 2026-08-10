"""한국어 문서를 채점기가 못 보던 세 자리 — 선언형 금지·트리거 표·카탈로그 안 의존 그래프.

stdlib only. Run with:

    python3 -m unittest tests.test_korean_detectors

각 테스트는 "이 패턴을 지우면 무엇이 빨개지나" 로 읽힌다. 그리고 마지막 클래스는 반대
방향을 잰다 — **이미 "금지" 를 쓰는 문서의 점수가 부풀지 않는가.** 지표를 넓히는 변경에서
그쪽이 안 잠기면, 다음 사람은 점수를 올리려고 같은 말을 어미만 바꿔 반복해 적게 된다.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN_ROOT / "skills" / "audit" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import audit  # noqa: E402


def donot_lines(text: str) -> int:
    return audit.count_guide_lines(text, audit.DONOT_PATTERNS)


def specific_donot_lines(text: str) -> int:
    return audit.count_specific_guide_lines(text, audit.DONOT_PATTERNS)


def usage_hit(text: str) -> bool:
    return audit.regex_any(text, audit.USAGE_PATTERNS)


class TestDeclarativeProhibition(unittest.TestCase):
    """한국어 프로젝트 규칙은 명령형보다 선언형으로 적힌다."""

    def test_declarative_negative_counts(self):
        text = "- **읽기 스키마를 그대로 다시 쓰지 않는다.** `src/encode.ts` 를 지난다.\n"
        self.assertEqual(donot_lines(text), 1)

    def test_polite_declarative_counts(self):
        self.assertEqual(donot_lines("- 토큰 값을 로그에 남기지 않습니다.\n"), 1)

    def test_nominalized_prohibition_counts(self):
        self.assertEqual(donot_lines("- 운영 DB 에 직접 쓰지 말 것.\n"), 1)

    def test_imperative_still_counts(self):
        """옛 어조를 깨뜨리지 않는다 — 선언형을 더한 것이지 바꾼 것이 아니다."""
        for line in ["- 절대 금지: main 직접 push\n", "- DO NOT commit secrets\n",
                     "- 그렇게 하지 마세요\n"]:
            with self.subTest(line=line):
                self.assertEqual(donot_lines(line), 1)

    def test_specificity_gate_still_applies(self):
        """선언형이라고 만점이 공짜가 되지 않는다. 대상을 안 가리키는 줄은 구체 줄이 아니다."""
        vague = "- 아무렇게나 하지 않는다.\n"
        self.assertEqual(donot_lines(vague), 1)
        self.assertEqual(specific_donot_lines(vague), 0)

    def test_one_line_counted_once(self):
        """"절대 ~하지 않는다" 처럼 두 패턴에 함께 걸려도 한 줄이다."""
        self.assertEqual(donot_lines("- 절대 하지 않는다: `foo/bar` 삭제\n"), 1)


class TestUsageTrigger(unittest.TestCase):
    """lazy-load 표의 '트리거' 열이 곧 '언제 읽나' 다."""

    def test_trigger_table_header_counts(self):
        self.assertTrue(usage_hit("| 트리거 | 문서 |\n|---|---|\n| 패키지 진입 | `docs/PACKAGES.md` |\n"))

    def test_prefixed_trigger_counts(self):
        self.assertTrue(usage_hit("> **읽기 트리거**: 패키지 진입 / 책임 경계 확인.\n"))

    def test_bare_trigger_prose_does_not_count(self):
        """맨 '트리거' 는 이벤트를 말하는 산문에서 흔하다. 그것까지 세면 공짜 5점이 된다."""
        self.assertFalse(usage_hit("슬랙 이벤트가 트리거되면 채널 행위자가 깨어난다.\n"))
        self.assertFalse(usage_hit("이 잡의 트리거 조건은 하루 한 번이다.\n"))

    def test_existing_markers_still_count(self):
        for text in ["## 사용 시점\n", "When to use: match the trigger\n", "언제 사용하나\n"]:
            with self.subTest(text=text):
                self.assertTrue(usage_hit(text))


class TestDependencyDiagram(unittest.TestCase):
    """그래프 하나 때문에 문서를 하나 더 만들게 하지 않는다."""

    def test_mermaid_graph_recognized(self):
        self.assertTrue(audit.has_dependency_diagram("```mermaid\ngraph TD\n  a --> b\n```\n"))

    def test_flowchart_recognized(self):
        self.assertTrue(audit.has_dependency_diagram("```mermaid\nflowchart LR\n  a --> b\n```\n"))

    def test_sequence_diagram_is_not_a_dependency_map(self):
        """순서도·상태도는 흐름을 그린 것이지 모듈 의존이 아니다."""
        self.assertFalse(audit.has_dependency_diagram("```mermaid\nsequenceDiagram\n  A->>B: x\n```\n"))
        self.assertFalse(audit.has_dependency_diagram("```mermaid\nstateDiagram-v2\n  s1 --> s2\n```\n"))

    def test_plain_code_block_is_not_a_diagram(self):
        self.assertFalse(audit.has_dependency_diagram("```\ngraph TD\n  a --> b\n```\n"))


class TestNoScoreInflation(unittest.TestCase):
    """넓힌 패턴이 이미 세던 문서의 줄 수를 부풀리지 않는가.

    이 저장소가 이 변경을 채택한 근거가 실측 하나였다 — 명령형으로 적힌 실제
    ANTIPATTERNS 문서가 40줄에서 40줄로 그대로였다는 것. 그 성질을 시험으로 잠근다.
    """

    IMPERATIVE_DOC = (
        "# 안티패턴\n"
        "- **절대 금지**: `src/main` 을 직접 고치는 것\n"
        "- DO NOT: `build/out` 을 커밋한다\n"
        "- 운영 DB 에 DDL 을 걸지 마세요\n"
    )

    def test_imperative_document_unchanged(self):
        """세 줄은 선언형 패턴 이전에도 세지던 줄이다. 어미를 더해도 셋 그대로여야 한다."""
        self.assertEqual(donot_lines(self.IMPERATIVE_DOC), 3)

    def test_repeating_the_same_rule_two_ways_is_still_one_line(self):
        """한 줄에 두 어조를 함께 적어도 한 줄이다 — 어미 농사로 점수가 안 오른다."""
        self.assertEqual(donot_lines("- 절대 금지: 그렇게 하지 않는다 (`a/b`)\n"), 1)


if __name__ == "__main__":
    unittest.main()
