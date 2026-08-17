"""에이전트 정의(`agents/*.md`)의 frontmatter 계약을 잠근다.

왜 필요한가. 에이전트 정의는 지금껏 어떤 시험도 안 받았는데, 여기서 조용히 깨지는 방식이
둘 있다. frontmatter 가 망가지면 그 에이전트는 **아예 안 뜨고** 호출하는 스킬이 "그런 에이전트
없음" 으로 죽는다. 그리고 **읽기 전용 계약이 도구 목록에서 새면** maker/checker 독립이라는
이 루프의 신뢰 근거가 무너지는데, 그건 실행해 보기 전엔 안 보인다.

판정 계열(checker·spec-checker·lesson-synthesizer)이 코드를 고치지 않는다는 것은 산문 약속이
아니라 `tools` 줄에서 Edit/Write 가 빠져 있다는 사실이다. 그 사실을 여기서 센다.

checker 가 런타임에 읽는 권위 문서(`_loop-engine/rubric.base.md`)의 출력 계약 문구도 같이 본다.
그 계약은 정의 파일과 이 문서에 나뉘어 적혀 있어서, 어느 쪽이 어디까지 적는가가 곧 계약이
갈라지는 자리다(TestCheckerOutputContractProse).

stdlib 만(PyYAML 없음) — frontmatter 는 필요한 키만 정규식으로 읽는다.
"""
from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path

TREE = Path(os.environ.get("AI_READY_TREE") or Path(__file__).resolve().parents[1])
AGENTS = TREE / "agents"
ENGINE = TREE / "_loop-engine"

# 코드를 고치지 않는 것이 존재 이유인 에이전트들. 여기 이름이 있으면 Edit/Write 를 가질 수 없다.
READ_ONLY = {"loop-checker", "loop-spec-checker", "loop-lesson-synthesizer"}

# checker 가 finding 하나에 다는 출력 필드 이름들. 앞머리에 나오면 안 되는 이름이기도 하다.
OUTPUT_FIELDS = ("in_scope", "force_await", "weights", "evidence", "dimension", "location")

_FM = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.S)


def _frontmatter(path: Path) -> dict[str, str]:
    m = _FM.match(path.read_text(encoding="utf-8"))
    if not m:
        raise AssertionError(f"{path.name}: frontmatter 를 못 찾았다 — 이 파일은 에이전트로 안 뜬다")
    out: dict[str, str] = {}
    for line in m.group("body").splitlines():
        # 최상위 키만 본다(들여쓴 줄은 앞 값의 연속). 값 안의 콜론은 자르지 않는다.
        if line[:1].isspace() or ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip()
    return out


class TestAgentDefinitions(unittest.TestCase):
    def setUp(self) -> None:
        self.files = sorted(AGENTS.glob("*.md"))
        # 개수를 먼저 본다 — 글롭이 빗나가 0건이어도 아래 루프는 전부 통과한다.
        self.assertGreaterEqual(len(self.files), 4,
                                f"{AGENTS} 에서 에이전트 정의를 {len(self.files)}개 찾았다 — 글롭 확인")

    def test_name_matches_filename(self):
        for f in self.files:
            with self.subTest(agent=f.name):
                self.assertEqual(_frontmatter(f).get("name"), f.stem,
                                 "frontmatter name 이 파일명과 다르면 호출부의 이름이 안 맞는다")

    def test_description_is_present_and_substantial(self):
        for f in self.files:
            with self.subTest(agent=f.name):
                desc = _frontmatter(f).get("description", "")
                # 호스트가 이 문장으로 언제 부를지 고른다 — 한 줄짜리면 사실상 안 불린다.
                self.assertGreater(len(desc), 120, "description 이 너무 짧다")

    def test_checker_description_does_not_list_output_fields(self):
        """앞머리는 "언제 부를까" 를 고르는 문장이고, 출력 계약은 본문 한 곳에만 둔다.

        1.4.0 이 finding 필드 목록을 `loop-checker.md` 본문과 앞머리 `description` 두 곳에
        적었다. 그 다음 릴리스가 `in_scope` 를 조건부로 바꾸면서 본문만 고쳤고, 앞머리에는
        무조건 다는 필드로 남았다. 어떤 검사도 그 어긋남을 잡지 못했다. 앞머리는 호스트가
        이 에이전트를 부를지 고르는 데 쓰는 문장이라 출력 계약과 애초에 독자가 다르고,
        열거를 본문 한 곳에만 두면 두 벌이 갈릴 자리 자체가 없어진다.
        """
        desc = _frontmatter(AGENTS / "loop-checker.md").get("description", "")
        for field in OUTPUT_FIELDS:
            with self.subTest(field=field):
                self.assertNotRegex(
                    desc, rf"\b{field}\b",
                    f"description 이 출력 필드 {field} 를 다시 열거한다 — 본문과 두 벌이 된다")

    def test_read_only_agents_have_no_write_tools(self):
        """읽기 전용 계약은 산문이 아니라 tools 줄이 강제한다."""
        seen = set()
        for f in self.files:
            if f.stem not in READ_ONLY:
                continue
            seen.add(f.stem)
            with self.subTest(agent=f.name):
                tools = {t.strip() for t in _frontmatter(f).get("tools", "").split(",")}
                self.assertTrue(tools & {"Read", "Grep", "Glob"},
                                "tools 가 비었다 — 기본값을 물려받으면 Edit/Write 가 딸려 온다")
                for banned in ("Edit", "Write", "NotebookEdit"):
                    self.assertNotIn(banned, tools,
                                     f"{f.stem} 은 코드를 고치지 않는 것이 존재 이유다")
        # READ_ONLY 에 적은 이름이 실제로 있는지 — 파일을 지우거나 개명하면 이 검사가 조용히 0건이 된다.
        self.assertEqual(seen, READ_ONLY,
                         f"READ_ONLY 에 적힌 에이전트를 다 못 찾았다: 없는 것 {READ_ONLY - seen}")

    def test_maker_can_write(self):
        """대조군 — 위 검사가 '모든 에이전트에 Edit 이 없다' 를 통과시키는 게 아니다."""
        tools = {t.strip() for t in _frontmatter(AGENTS / "loop-maker.md").get("tools", "").split(",")}
        self.assertIn("Edit", tools)
        self.assertIn("Write", tools)

    def test_manifest_lists_every_agent_file(self):
        """정의가 있는 것과 그 정의가 로드되는 것은 다르다.

        호스트는 `plugin.json` 의 `agents` 배열을 읽는다 — 파일을 두기만 하고 등록하지 않으면
        그 에이전트는 아예 안 뜨고, 부르는 스킬이 "없는 에이전트" 로 죽는다. 0.9.12 에서
        `loop-spec-checker` 를 만들고 등록을 빠뜨렸고, 그 호출부 둘이 **점검 실패를 삼키고
        진행하도록** 설계돼 있어 기능 전체가 경고 한 줄로 조용히 사라질 뻔했다.
        위 검사들은 디렉터리만 훑어 이 구멍을 못 본다.
        """
        manifest = json.loads((TREE / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        listed = {Path(p).name for p in manifest.get("agents", [])}
        on_disk = {f.name for f in self.files}
        self.assertEqual(listed, on_disk,
                         f"등록 안 된 정의 {on_disk - listed} / 파일 없는 등록 {listed - on_disk}")


class TestCheckerOutputContractProse(unittest.TestCase):
    """checker 가 런타임에 읽는 권위 문서가 출력 계약을 어떻게 적는지 본다."""

    def test_rubric_states_the_condition_wherever_it_says_in_scope(self):
        """`in_scope` 를 말하는 자리는 그것이 조건부라는 것을 함께 말해야 한다.

        `rubric.base.md` 는 렌즈가 런타임에 읽는 권위 문서다. `in_scope` 는 조건부 필드로,
        프롬프트가 `non_goals` 를 준 렌즈만 달고 못 받았으면 키를 아예 뺀다. 키를 빼는 것이
        "이 축은 범위를 안 쟀다" 를 전하는 유일한 방법이고, 결정론 셸이 그 미표기를
        "범위 밖" 과 따로 센다. 조건이 빠진 문장을 읽은 렌즈는 항상 필드를 달고, 그러면
        안 잰 축이 "다 범위 안" 으로 집계돼 사람이 볼 때는 측정된 것과 구분되지 않는다.

        두 방향을 다 본다. `in_scope` 문단이 하나도 없으면 조건부가 되기 전 판으로 되돌아간
        것이고, 문단은 있는데 `non_goals` 가 없으면 조건만 빠진 것이다.
        """
        text = (ENGINE / "rubric.base.md").read_text(encoding="utf-8")
        paragraphs = [p for p in re.split(r"\n\s*\n", text) if re.search(r"\bin_scope\b", p)]
        self.assertTrue(paragraphs,
                        "rubric 이 in_scope 를 아예 안 적는다 — 렌즈가 읽을 계약이 없다")
        for p in paragraphs:
            with self.subTest(paragraph=p.splitlines()[0][:60]):
                self.assertRegex(
                    p, r"\bnon_goals\b",
                    "in_scope 를 적으면서 조건(non_goals)을 안 적는다 — "
                    "렌즈가 항상 필드를 달아 안 잰 축이 측정된 것으로 집계된다")


class TestCommentKindsStayNonBlocking(unittest.TestCase):
    """주석 부류 종류가 통과를 막지 않는 등급에 머무는지 본다."""

    # KINDS 표에서 한 행을 꺼낸다. 표 밖의 산문이 같은 낱말을 써도 걸리지 않게 행 형태로 찾는다.
    @staticmethod
    def _kind_row(kind_id):
        text = (ENGINE / "rubric.base.md").read_text(encoding="utf-8")
        block = re.search(
            r"LOOP_RUBRIC:KINDS:BEGIN(.*?)LOOP_RUBRIC:KINDS:END", text, re.S)
        assert block, "KINDS 블록 자체가 없다"
        for line in block.group(1).splitlines():
            cells = [c.strip() for c in line.split("|")]
            if len(cells) > 4 and cells[1] == kind_id:
                return cells
        return None

    def test_comment_kinds_are_minor(self):
        """주석 부류는 MINOR 여야 한다 — 아니면 문구 하나가 회차를 더 쓰게 만든다.

        종료 판정이 "MINOR 만이면 Pass" 라, MAJOR 이상이면 주석 문구를 고치라고 되돌려
        보낸다. 표에 없는 종류는 dimension floor 로 채점되는데 convention 만 MINOR 이고
        simplicity·intent 는 MAJOR 라, 행이 빠지면 등급이 checker 의 태깅에 달린다.
        그래서 존재와 등급을 함께 본다 — 행을 지우면 이 검사가 실패한다.
        """
        for kind_id in ("comment-noise", "comment-rot"):
            with self.subTest(kind=kind_id):
                row = self._kind_row(kind_id)
                self.assertIsNotNone(
                    row, f"KINDS 표에 {kind_id} 행이 없다 — 등급이 dimension floor 로 갈린다")
                self.assertEqual(
                    row[4], "MINOR",
                    f"{kind_id} 가 MINOR 가 아니다 — 주석 문구가 통과를 막는다")
                self.assertEqual(
                    row[5], "no",
                    f"{kind_id} 가 사람을 부른다(force_await) — 주석 문구로 멈출 자리가 아니다")

    def test_comment_rot_states_its_carve_outs(self):
        """`comment-rot` 은 대상이 아닌 경우를 함께 적어야 한다.

        예외를 안 적으면 checker 가 안 썩는 주석까지 센다. 실측에서 오탐 셋이 났고
        전부 이 셋에 해당했다: 그 문장 안에서 세어지는 개수, 날짜 붙은 실측 기록,
        그리고 검사가 지키고 있는 사실.
        """
        row = self._kind_row("comment-rot")
        self.assertIsNotNone(row, "comment-rot 행이 없다")
        note = row[6]
        for phrase in ("대상이 아니다", "실측 기록", "검사가 지키고"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, note,
                              f"comment-rot 설명에 예외 '{phrase}' 가 없다 — 오탐이 그대로 남는다")


class TestMakerSelfVerifyContract(unittest.TestCase):
    """1.5.1 의 maker 계약(주석 최소·되돌림 확인)이 정의와 위임 지시 양쪽에 있는지 본다.

    계약이 산문 두 곳에 나뉘어 있다 — 정의(`agents/loop-maker.md`)는 행동을, 스킬
    (`skills/build/SKILL.md` Step 2-5)은 그 행동에 필요한 입력(테스트 명령·기록 경로)을
    적는다. 한쪽만 고쳐지면 maker 가 명령 없이 확인하거나 기록 없이 확인한다.
    """

    def test_maker_definition_states_the_contract(self):
        text = (AGENTS / "loop-maker.md").read_text(encoding="utf-8")
        for anchor, why in (
            ("주석은 코드가 말하지 못하는 것만", "주석 계약이 빠졌다"),
            ("mktemp -d", "사본 규약이 빠졌다 — 고정 경로는 병렬 에이전트의 사본과 섞인다"),
            ("되돌리면 실패하는 검사", "확인이 안 되는 수정의 처방이 빠졌다"),
            ("comment-rot", "주석 지적 대응 계약이 빠졌다"),
            ("기록 경로", "확인 흔적 계약이 빠졌다 — 보고 한 줄은 강제가 안 된다"),
        ):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, text, why)

    def test_build_skill_passes_the_inputs(self):
        text = (TREE / "skills" / "build" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("maker-revert-$PHASE.jsonl", text,
                      "되돌림 기록 경로를 maker 프롬프트 값으로 안 넘긴다")
        self.assertRegex(text, r"테스트 명령.*LOOP_TEST_CMD",
                         "테스트 명령을 maker 프롬프트 값으로 안 적는다 — 게이트만 알면 "
                         "maker 가 매 회차 다시 알아내거나 게이트와 다른 명령으로 잰다")


if __name__ == "__main__":
    unittest.main()
