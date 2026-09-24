"""에이전트 정의(`agents/*.md`)의 frontmatter 계약을 확인한다.

frontmatter 가 망가지면 그 에이전트는 아예 로드되지 않고, 부르는 스킬이 "그런 에이전트 없음" 으로
멈춘다. 그리고 읽기 전용 에이전트가 코드를 고치지 않는다는 약속은 산문이 아니라 `tools` 줄에서
Edit/Write 가 빠져 있다는 사실로 지킨다. 그 사실을 여기서 센다.

표준 라이브러리만 쓴다(PyYAML 없음) — frontmatter 는 필요한 키만 정규식으로 읽는다.
"""
from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path

TREE = Path(os.environ.get("AI_READY_TREE") or Path(__file__).resolve().parents[1])
AGENTS = TREE / "agents"

# 파일을 고치지 않는 것이 존재 이유인 에이전트들. 여기 이름이 있으면 Edit/Write 를 가질 수 없다.
READ_ONLY = {"loop-lesson-synthesizer"}

_FM = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.S)


def _frontmatter(path: Path) -> dict[str, str]:
    m = _FM.match(path.read_text(encoding="utf-8"))
    if not m:
        raise AssertionError(f"{path.name}: frontmatter 를 못 찾았다 — 이 파일은 에이전트로 로드되지 않는다")
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
        self.assertGreaterEqual(len(self.files), 1,
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
                    self.assertNotIn(banned, tools, f"{f.stem} 은 파일을 고치지 않는다")
        # 파일을 지우거나 이름을 바꾸면 이 검사가 조용히 0건이 된다.
        self.assertEqual(seen, READ_ONLY,
                         f"READ_ONLY 에 적힌 에이전트를 다 못 찾았다: 없는 것 {READ_ONLY - seen}")

    def test_manifest_lists_every_agent_file(self):
        """파일을 두기만 하고 `plugin.json` 의 `agents` 에 등록하지 않으면 그 에이전트는 로드되지 않는다."""
        manifest = json.loads((TREE / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        listed = {Path(p).name for p in manifest.get("agents", [])}
        on_disk = {f.name for f in self.files}
        self.assertEqual(listed, on_disk,
                         f"등록 안 된 정의 {on_disk - listed} / 파일 없는 등록 {listed - on_disk}")

    def test_manifest_lists_every_skill_dir(self):
        manifest = json.loads((TREE / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        listed = {Path(p).name for p in manifest.get("skills", [])}
        on_disk = {d.name for d in (TREE / "skills").iterdir() if (d / "SKILL.md").is_file()}
        self.assertEqual(listed, on_disk,
                         f"등록 안 된 스킬 {on_disk - listed} / 폴더 없는 등록 {listed - on_disk}")


if __name__ == "__main__":
    unittest.main()
