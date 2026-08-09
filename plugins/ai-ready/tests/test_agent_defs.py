"""에이전트 정의(`agents/*.md`)의 frontmatter 계약을 잠근다.

왜 필요한가. 에이전트 정의는 지금껏 어떤 시험도 안 받았는데, 여기서 조용히 깨지는 방식이
둘 있다. frontmatter 가 망가지면 그 에이전트는 **아예 안 뜨고** 호출하는 스킬이 "그런 에이전트
없음" 으로 죽는다. 그리고 **읽기 전용 계약이 도구 목록에서 새면** maker/checker 독립이라는
이 루프의 신뢰 근거가 무너지는데, 그건 실행해 보기 전엔 안 보인다.

판정 계열(checker·spec-checker·lesson-synthesizer)이 코드를 고치지 않는다는 것은 산문 약속이
아니라 `tools` 줄에서 Edit/Write 가 빠져 있다는 사실이다. 그 사실을 여기서 센다.

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

# 코드를 고치지 않는 것이 존재 이유인 에이전트들. 여기 이름이 있으면 Edit/Write 를 가질 수 없다.
READ_ONLY = {"loop-checker", "loop-spec-checker", "loop-lesson-synthesizer"}

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


if __name__ == "__main__":
    unittest.main()
