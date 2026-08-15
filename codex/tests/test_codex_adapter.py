import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "ai-ready"
MANIFEST = PLUGIN / ".codex-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
EXPECTED_SKILLS = {"audit", "apply", "freshness", "spec", "review", "build", "lessons"}

# 착수 게이트 항목의 시작 앵커. 항목 번호는 앞에 항목이 끼면 밀리니 문장 조각으로 잡는다.
_GATE_ANCHOR = "refuse to start without them"
# 끝은 첫 빈 줄이다. 항목에 이어지는 문단이 붙으면 거기에도 같은 이름들이 나와서, 함께 읽으면
# 게이트 문장에서 요구가 사라져도 그쪽이 대신 맞아 통과한다. 실제로 그 상태였다.
# 다음 최상위 번호 항목과 `##` 제목은 빈 줄이 없을 때를 위한 보조 종료 조건이다.
_GATE_END = re.compile(r"(?:\s*$|\d+\.\s|## )")


def _start_gate_item() -> str:
    """`build/SKILL.md` 의 착수 게이트 번호 항목만 잘라낸다.

    앵커가 밀렸을 때 조용히 빈 문자열을 돌려주면 그것을 대조하는 시험이 아무것도 안 본다.
    그래서 시작·끝 어느 쪽을 못 찾아도 여기서 실패시킨다.
    """
    skill = (PLUGIN / "skills" / "build" / "SKILL.md").read_text(encoding="utf-8")
    lines = skill.splitlines()
    starts = [i for i, line in enumerate(lines) if _GATE_ANCHOR in line]
    if len(starts) != 1:
        raise AssertionError(
            f"착수 게이트 시작 앵커({_GATE_ANCHOR!r})를 {len(starts)}개 찾았다 — 앵커를 갱신하라")
    start = starts[0]
    ends = [i for i in range(start + 1, len(lines)) if _GATE_END.match(lines[i])]
    if not ends:
        raise AssertionError(
            "착수 게이트 항목의 끝(빈 줄·다음 번호 항목·제목)을 못 찾았다 — "
            "파일 끝까지 읽으면 구간 제한이 사라진다")
    return "\n".join(lines[start:ends[0]])


class CodexAdapterTests(unittest.TestCase):
    def test_manifest_has_only_supported_components(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual("ai-ready", manifest["name"])
        self.assertEqual("./skills/", manifest["skills"])
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+(\+[\w.-]+)?$")
        self.assertNotIn("hooks", manifest)
        self.assertNotIn("mcpServers", manifest)
        self.assertNotIn("apps", manifest)
        self.assertEqual({"Read", "Write"}, set(manifest["interface"]["capabilities"]))

    def test_marketplace_points_to_this_plugin(self):
        marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
        self.assertEqual("ai-ready", marketplace["name"])
        self.assertEqual(1, len(marketplace["plugins"]))
        entry = marketplace["plugins"][0]
        self.assertEqual("ai-ready", entry["name"])
        self.assertEqual("./plugins/ai-ready", entry["source"]["path"])
        self.assertEqual("AVAILABLE", entry["policy"]["installation"])

    def test_skills_are_complete_and_provider_neutral(self):
        actual = {path.name for path in (PLUGIN / "skills").iterdir() if path.is_dir()}
        self.assertEqual(EXPECTED_SKILLS, actual)
        forbidden = ("[TODO:", "CLAUDE_PLUGIN_ROOT", "CLAUDE_PROJECT_DIR", "SendMessage")
        for name in EXPECTED_SKILLS:
            skill = (PLUGIN / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            frontmatter = re.match(r"\A---\n(.*?)\n---", skill, re.DOTALL)
            self.assertIsNotNone(frontmatter, name)
            self.assertRegex(frontmatter.group(1), rf"(?m)^name:\s*{re.escape(name)}\s*$")
            self.assertRegex(frontmatter.group(1), r"(?m)^description:\s*.+$")
            for token in forbidden:
                self.assertNotIn(token, skill, f"{name}: {token}")

    def test_checker_contract_is_stated_in_both_places(self):
        """codex 의 checker 계약은 산문 두 곳에만 있어 한쪽만 고쳐지는 사고가 실제로 났다.

        에이전트 정의 파일이 없는 트리라 `build/SKILL.md`(위임 지시)와
        `references/checker-role.md`(역할 계약)가 계약의 전부다. 0.9.7 첫 커밋에서
        후자만 갱신돼 같은 스킬 안에서 스키마가 어긋났다.
        """
        skill = (PLUGIN / "skills" / "build" / "SKILL.md").read_text(encoding="utf-8")
        role = (PLUGIN / "skills" / "build" / "references" / "checker-role.md").read_text(encoding="utf-8")
        for name, text in (("SKILL.md", skill), ("checker-role.md", role)):
            self.assertIn("reviewed", text,
                          f"{name} 가 checker 출력의 reviewed 를 안 적는다 — 계약이 갈라진다")
        # 출력 필드가 늘면 두 곳이 함께 늘어야 한다. `in_scope` 는 1.4.0 이 더한 것인데, 이
        # 시험이 `reviewed` 만 보고 있어 한쪽만 적힌 상태가 통과했다. 위 독스트링이 드는
        # 0.9.7 사고와 같은 종류라 같은 자리에서 잠근다.
        # 단어 경계로 본다 — 부분 문자열 대조는 `in_scopeZZ` 같은 접미사 개명을 그대로 통과시킨다.
        for name, text in (("SKILL.md", skill), ("checker-role.md", role)):
            self.assertRegex(text, r"\bin_scope\b",
                             f"{name} 가 checker 출력의 in_scope 를 안 적는다 — 계약이 갈라진다")
        # `in_scope` 가 적혀 있는 것과 **그것이 조건부라고** 적혀 있는 것은 다르다. 조건은 하나다.
        # 프롬프트가 `non_goals` 를 준 렌즈만 이 필드를 달고, 못 받았으면 키를 아예 뺀다. 키를
        # 빼는 것이 "이 축은 범위를 안 쟀다" 를 전하는 유일한 방법이고, 셸이 그 미표기를
        # "범위 밖" 과 따로 센다. 조건절이 지워지면 렌즈는 항상 필드를 달고, 안 잰 축이
        # 측정된 축과 같은 숫자로 올라온다. 문구 한 글자에 매이지 않게 두 방향만 요구한다.
        self.assertRegex(role, r"only when .{0,40}non_goals",
                         "checker-role.md 가 in_scope 를 다는 조건을 안 적는다")
        self.assertRegex(role, r"[Oo]mit .{0,60}non_goals",
                         "checker-role.md 가 non_goals 없을 때 키를 뺀다는 것을 안 적는다")
        # 위임 지시 쪽도 같은 조건을 적어야 두 곳이 안 갈라진다. 여기는 렌즈가 아니라
        # 오케스트레이터가 읽는 문장이라 어순이 반대다("no `non_goals` 인 렌즈는 omit 한다").
        self.assertRegex(skill, r"(?s)non_goals.{0,80}\bomits?\b",
                         "SKILL.md 가 non_goals 없는 렌즈는 필드를 뺀다는 것을 안 적는다")
        # 옛 스키마가 남아 있으면 그걸 따라 짠 checker 가 채점에서 exit 65 로 거부된다.
        for name, text in (("SKILL.md", skill), ("checker-role.md", role)):
            self.assertNotIn('{"base", "findings"', text,
                             f"{name} 에 reviewed 없는 옛 출력 스키마가 남아 있다")

    def test_spec_checker_contract_is_stated_in_both_places(self):
        """spec-checker 계약도 checker 와 같은 모양이라 같은 방식으로 갈라진다.

        0.9.12 에서 생긴 계약이고, 역시 `build/SKILL.md`(위임 지시)와
        `references/spec-checker-role.md`(역할 계약) 두 곳에만 있다. 위 checker 시험이
        막는 사고와 같은 자리라 함께 잠근다.
        """
        skill = (PLUGIN / "skills" / "build" / "SKILL.md").read_text(encoding="utf-8")
        role = (PLUGIN / "skills" / "build" / "references"
                / "spec-checker-role.md").read_text(encoding="utf-8")
        self.assertIn("spec-checker-role.md", skill,
                      "SKILL.md 가 역할 계약 파일을 안 가리킨다 — 위임할 때 넘길 텍스트가 없다")
        # 두 곳이 갈라지면 안 되는 것은 출력 키다. 한쪽만 바뀌면 결과를 읽는 쪽이 조용히 빈 목록을 본다.
        for name, text in (("SKILL.md", skill), ("spec-checker-role.md", role)):
            self.assertIn("gaps", text, f"{name} 가 출력 키 gaps 를 안 적는다")
        # 경고 층이라는 성질은 **호출부** 계약이다 — 결과를 받아 무엇을 할지는 오케스트레이터가 정한다.
        # 역할 파일은 같은 성질을 "총평을 쓰지 마라"(그 판단은 읽는 사람의 몫)로 담고 있어 문구가 다르다.
        self.assertRegex(skill, r"never blocks|not a gate|warning layer",
                         "SKILL.md 가 '시작을 막지 않는다' 를 안 적는다 — 무인 실행이 거기서 멈춘다")
        self.assertRegex(role, r"Do not put severity|overall judgement",
                         "역할 계약이 총평 금지를 안 적는다 — 등급을 매기면 경고 층이 게이트로 읽힌다")

    def test_build_start_gate_requires_the_spec_fields(self):
        """codex 트리에는 결정론 게이트가 없어 이 산문이 계약의 전부다.

        Claude 트리는 jq 두 자리가 강제하지만 codex 스킬 본문에는 셸 블록이 없다. 자리
        이름이 문서에서 빠지면 그 호스트에서는 아무것도 요구하지 않는 상태가 된다.
        1.0.0 에서 이 게이트를 안 지나던 단일 변경 경로가 `build` 로 흡수돼, 이제 이 스킬
        하나가 유일한 착수 경로다 — 여기서 빠지면 우회로가 아니라 게이트 자체가 없어진다.

        **자리가 늘면 이 목록도 늘어야 한다.** 1.4.0 이 `non_goals` 를 더했을 때 이 목록이
        안 따라와, codex 트리의 그 이름을 전부 딴 것으로 바꿔도 시험이 통과했다. claude 쪽은
        jq 두 자리와 python 여덟 건이 잠그는데 이쪽만 비어 있었다.

        **파일 전체가 아니라 게이트 항목만 본다.** 같은 이름들이 phase loop 재확인 절과
        렌즈 위임 절에도 나와서, 파일 전체를 대조하면 착수 게이트 문단에서 `non_goals`
        요구가 사라져도 다른 절의 언급이 대신 맞아 통과한다. 실제로 그 상태가 통과했다.
        """
        item = _start_gate_item()
        for field in ("exit_criteria", "irreversible", "tiebreaks", "non_goals"):
            self.assertRegex(item, rf"\b{field}\b", f"start gate 가 {field} 를 안 요구한다")

    def test_checker_lens_split_is_stated_in_both_places(self):
        """렌즈 분할도 checker 계약과 같은 두 곳에 있어 같은 방식으로 갈라진다.

        1.0.0 에서 checker 는 축이 갈린 렌즈 셋으로 병렬 기동하고 결과는 개수를 세어 합친다.
        렌즈 이름이 한쪽에만 있으면 오케스트레이터가 부르는 이름과 checker 가 자기 축이라
        믿는 이름이 어긋나고, 안 돈 축이 점검된 적 없는 채로 통과한다.
        """
        skill = (PLUGIN / "skills" / "build" / "SKILL.md").read_text(encoding="utf-8")
        role = (PLUGIN / "skills" / "build" / "references" / "checker-role.md").read_text(encoding="utf-8")
        for name, text in (("SKILL.md", skill), ("checker-role.md", role)):
            for lens in ("contract", "safety", "quality"):
                self.assertIn(f"`{lens}`", text, f"{name} 가 렌즈 {lens} 를 안 적는다")
            self.assertIn("simplicity", text, f"{name} 가 여섯째 차원 simplicity 를 안 적는다")
        # 개수 검사가 이 병렬화의 안전장치다 — 빠지면 렌즈 하나가 죽어도 남은 둘로 채점된다.
        self.assertIn("--expect 3", skill,
                      "SKILL.md 가 렌즈 개수 검사(--expect)를 안 적는다 — 죽은 축이 통과로 읽힌다")

    def test_audit_bundle_has_no_hook_installer(self):
        scripts = PLUGIN / "skills" / "audit" / "scripts"
        for filename in ("audit.py", "scaffold.py", "extract_antipatterns.py", "dashboard.py"):
            self.assertTrue((scripts / filename).is_file(), filename)
        self.assertFalse((scripts / "install_hook.py").exists())


if __name__ == "__main__":
    unittest.main()
