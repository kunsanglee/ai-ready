import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "ai-ready"
MANIFEST = PLUGIN / ".codex-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
EXPECTED_SKILLS = {"audit", "apply", "freshness", "loop-review", "loop-run", "loop-build", "loop-lessons"}


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

        에이전트 정의 파일이 없는 트리라 `loop-run/SKILL.md`(위임 지시)와
        `references/checker-role.md`(역할 계약)가 계약의 전부다. 0.9.7 첫 커밋에서
        후자만 갱신돼 같은 스킬 안에서 스키마가 어긋났다.
        """
        skill = (PLUGIN / "skills" / "loop-run" / "SKILL.md").read_text(encoding="utf-8")
        role = (PLUGIN / "skills" / "loop-run" / "references" / "checker-role.md").read_text(encoding="utf-8")
        for name, text in (("SKILL.md", skill), ("checker-role.md", role)):
            self.assertIn("reviewed", text,
                          f"{name} 가 checker 출력의 reviewed 를 안 적는다 — 계약이 갈라진다")
        # 옛 스키마가 남아 있으면 그걸 따라 짠 checker 가 채점에서 exit 65 로 거부된다.
        for name, text in (("SKILL.md", skill), ("checker-role.md", role)):
            self.assertNotIn('{"base", "findings"', text,
                             f"{name} 에 reviewed 없는 옛 출력 스키마가 남아 있다")

    def test_spec_checker_contract_is_stated_in_both_places(self):
        """spec-checker 계약도 checker 와 같은 모양이라 같은 방식으로 갈라진다.

        0.9.12 에서 생긴 계약이고, 역시 `loop-run/SKILL.md`(위임 지시)와
        `references/spec-checker-role.md`(역할 계약) 두 곳에만 있다. 위 checker 시험이
        막는 사고와 같은 자리라 함께 잠근다.
        """
        skill = (PLUGIN / "skills" / "loop-run" / "SKILL.md").read_text(encoding="utf-8")
        role = (PLUGIN / "skills" / "loop-run" / "references"
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

    def test_loop_build_start_gate_requires_the_three_fields(self):
        """codex 트리에는 결정론 게이트가 없어 이 산문이 계약의 전부다.

        Claude 트리는 jq 두 자리가 강제하지만 codex 스킬 본문에는 셸 블록이 없다. 세 자리
        이름이 문서에서 빠지면 그 호스트에서는 아무것도 요구하지 않는 상태가 된다.
        """
        skill = (PLUGIN / "skills" / "loop-build" / "SKILL.md").read_text(encoding="utf-8")
        for field in ("exit_criteria", "irreversible", "tiebreaks"):
            self.assertIn(field, skill, f"start gate 가 {field} 를 안 요구한다")

    def test_audit_bundle_has_no_hook_installer(self):
        scripts = PLUGIN / "skills" / "audit" / "scripts"
        for filename in ("audit.py", "scaffold.py", "extract_antipatterns.py", "dashboard.py"):
            self.assertTrue((scripts / filename).is_file(), filename)
        self.assertFalse((scripts / "install_hook.py").exists())


if __name__ == "__main__":
    unittest.main()
