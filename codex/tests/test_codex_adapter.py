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

    def test_audit_bundle_has_no_hook_installer(self):
        scripts = PLUGIN / "skills" / "audit" / "scripts"
        for filename in ("audit.py", "scaffold.py", "extract_antipatterns.py", "dashboard.py"):
            self.assertTrue((scripts / filename).is_file(), filename)
        self.assertFalse((scripts / "install_hook.py").exists())


if __name__ == "__main__":
    unittest.main()
