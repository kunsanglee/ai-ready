"""SKILL.md 가 적은 명령 옵션·종료 코드가 스크립트의 실제와 맞는지 본다.

스킬 본문은 모델이 그대로 따라 부르는 명령이라, 없는 옵션이나 스크립트가 쓰지 않는 종료 코드를 적으면 모델이 그
틀린 문장대로 움직인다. codex 사본(`codex/plugins/ai-ready`)이 같은 저장소에 있으면 그 SKILL.md 도 같이 본다.

stdlib only. 플러그인 루트에서 `python3 -m unittest discover -s tests -t .` 로 돈다.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CODEX_ROOT = PLUGIN_ROOT.parent.parent / "codex" / "plugins" / "ai-ready"

SCRIPT_NAME = re.compile(r"\b(audit\.py|bootstrap\.py|scaffold\.py|install_verify_hook\.py|check_docs\.py|verify\.sh)\b")
OPTION = re.compile(r"(?<![\w-])--[a-z][a-z-]*")
EXIT = re.compile(r"\bexit (\d+)")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
# 스크립트가 아닌 명령의 옵션(gh·git)이 적힌 줄은 옵션 대조에서 뺀다.
FOREIGN_COMMAND = re.compile(r"\b(gh|git) [a-z]")
# audit 이 CI 설정에서 찾아 적는 다른 도구의 옵션. 스크립트 옵션이 아니다.
QUOTED_TOOL_OPTIONS = {"--no-verify"}


def _script_path(plugin: Path, name: str) -> Path:
    scripts = plugin / "skills" / "audit" / "scripts"
    return scripts / "project" / name if name in ("check_docs.py", "verify.sh") else scripts / name


def _options(plugin: Path, name: str) -> set[str]:
    path = _script_path(plugin, name)
    if name == "verify.sh":
        return set(re.findall(r'"(--[a-z-]+)"', path.read_text(encoding="utf-8")))
    env = {**os.environ, "NO_COLOR": "1", "PYTHON_COLORS": "0"}
    out = subprocess.run([sys.executable, str(path), "--help"], capture_output=True, text=True, env=env).stdout
    return set(OPTION.findall(ANSI.sub("", out))) - {"--help"}


def _exit_codes(plugin: Path, name: str) -> set[int]:
    text = _script_path(plugin, name).read_text(encoding="utf-8")
    if name == "verify.sh":
        return {int(n) for n in re.findall(r"\bexit (\d+)", text)}
    codes = {0, 2}  # argparse 는 잘못된 인자에 2 로 끝난다
    codes |= {int(n) for n in re.findall(r"^EXIT_\w+ = (\d+)", text, re.M)}
    codes |= {int(n) for n in re.findall(r"\breturn (\d+)\b", text)}
    codes |= {int(n) for n in re.findall(r"sys\.exit\((\d+)\)", text)}
    return codes


def _paragraphs(skill: str) -> list[tuple[str, str]]:
    """(가장 가까운 ### 제목, 문단). 문단은 빈 줄로 나눈 덩어리다."""
    out, heading, block = [], "", []
    for line in skill.splitlines():
        if line.startswith("#"):
            if block:
                out.append((heading, "\n".join(block)))
                block = []
            heading = line
        elif line.strip():
            block.append(line)
        elif block:
            out.append((heading, "\n".join(block)))
            block = []
    if block:
        out.append((heading, "\n".join(block)))
    return out


def _skills(plugin: Path) -> list[Path]:
    return sorted((plugin / "skills").glob("*/SKILL.md"))


class _Checks:
    plugin: Path
    scripts: tuple[str, ...]

    def test_command_options_exist_on_the_script(self):
        known = {name: _options(self.plugin, name) for name in self.scripts}
        every = set().union(*known.values()) | QUOTED_TOOL_OPTIONS
        for skill in _skills(self.plugin):
            for no, line in enumerate(skill.read_text(encoding="utf-8").splitlines(), 1):
                if FOREIGN_COMMAND.search(line):
                    continue
                for opt in OPTION.findall(line):
                    self.assertIn(opt, every, f"{skill}:{no}: 어느 스크립트에도 없는 옵션 {opt}")
                # 스크립트 이름 바로 뒤 같은 명령 안의 옵션은 그 스크립트의 옵션이어야 한다.
                for m in re.finditer(r"(\w+\.(?:py|sh))([^`]*)", line):
                    name = m.group(1)
                    if name not in known:
                        continue
                    for opt in OPTION.findall(m.group(2).split(" | ")[0]):
                        if SCRIPT_NAME.search(m.group(2).split(opt)[0]):
                            break  # 뒤에 다른 스크립트가 나오면 거기서 끝
                        self.assertIn(opt, known[name], f"{skill}:{no}: {name} 에 없는 옵션 {opt}")

    def test_exit_codes_are_codes_the_named_scripts_use(self):
        codes = {name: _exit_codes(self.plugin, name) for name in self.scripts}
        for skill in _skills(self.plugin):
            for heading, para in _paragraphs(skill.read_text(encoding="utf-8")):
                said = {int(n) for n in EXIT.findall(para)}
                if not said:
                    continue
                named = set(SCRIPT_NAME.findall(para)) | set(SCRIPT_NAME.findall(heading))
                named &= set(self.scripts)
                self.assertTrue(named, f"{skill}: 어느 스크립트의 종료 코드인지 알 수 없는 문단:\n{para}")
                allowed = set().union(*(codes[n] for n in named))
                self.assertLessEqual(said, allowed, f"{skill}: {sorted(named)} 가 쓰지 않는 종료 코드:\n{para}")

    def test_apply_skill_documents_every_refusal_code(self):
        # 스크립트가 멈추며 내는 코드(0·1·2 가 아닌 것)는 apply 스킬이 모두 설명한다.
        text = (self.plugin / "skills" / "apply" / "SKILL.md").read_text(encoding="utf-8")
        for name in ("bootstrap.py", "scaffold.py", "install_verify_hook.py"):
            if name not in self.scripts:
                continue
            said = {int(n) for heading, para in _paragraphs(text)
                    if name in SCRIPT_NAME.findall(para) + SCRIPT_NAME.findall(heading)
                    for n in EXIT.findall(para)}
            path = _script_path(self.plugin, name).read_text(encoding="utf-8")
            special = {int(n) for n in re.findall(r"^EXIT_\w+ = (\d+)", path, re.M)} - {0, 1, 2}
            self.assertLessEqual(special, said, f"apply SKILL 이 {name} 의 종료 코드 {sorted(special - said)} 를 적지 않았다")


class ClaudeSkillDocs(_Checks, unittest.TestCase):
    plugin = PLUGIN_ROOT
    scripts = ("audit.py", "bootstrap.py", "scaffold.py", "install_verify_hook.py", "check_docs.py", "verify.sh")


@unittest.skipUnless(CODEX_ROOT.is_dir(), "codex 사본이 없다(플러그인만 설치된 경우)")
class CodexSkillDocs(_Checks, unittest.TestCase):
    plugin = CODEX_ROOT
    scripts = ("audit.py", "bootstrap.py", "scaffold.py", "check_docs.py", "verify.sh")


if __name__ == "__main__":
    unittest.main()
