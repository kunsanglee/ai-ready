#!/usr/bin/env python3
"""audit.py — 에이전트 작업용 문서·강제 수단의 빈틈을 사실로만 모은 보고서를 낸다.

점수는 없다. 세 절을 낸다.

1. 문서 존재 — 루트 CLAUDE.md(+AGENTS.md), 모듈별 CLAUDE.md, docs/design 결정 기록 쌍, 검증 문서.
   있음·없음·길이 과다만 적는다.
2. 강제 수단 — 감지된 lint·formatter·타입체커·테스트 러너·아키텍처 테스트·pre-commit·에이전트 hook·
   CI 설정. 그리고 CI 설정 파일 안에서 그 검사를 실제로 부르는 줄을 찾아 따로 적는다. CI·Dockerfile 에서
   테스트를 빼거나 실패를 무시하는 줄도 표시한다.
3. 규칙 문장 — 문서에서 "금지·반드시·must·never·DO NOT" 류 줄을 파일:줄 로 뽑는다. 이 줄들이 이미
   강제되는지, 싸게 강제할 수 있는지, 강제할 수 없는지, 코드와 어긋났는지는 **스크립트가 가르지 않는다.**
   그 분류는 audit 스킬 본문에서 모델이 한다.

stdlib 만 쓴다. 대상 저장소에는 아무것도 쓰지 않는다(`--out` 으로 준 파일 하나만 쓴다).

실행:
  python3 audit.py --target /path/to/repo                   # markdown 을 stdout 으로
  python3 audit.py --target /path/to/repo --out gaps.md     # 파일로
  python3 audit.py --target /path/to/repo --json            # 같은 사실을 JSON 으로
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import stacks  # noqa: E402

# 루트 CLAUDE.md 는 매 세션 통째로 읽힌다. 이 크기를 넘으면 "길이 과다" 로 적는다.
# 기준은 판정이 아니라 보고용 문턱이다 — 넘었다는 사실과 실제 크기를 함께 적는다.
ROOT_DOC_MAX_BYTES = 8_000
MODULE_DOC_MAX_LINES = 80
MAX_RULE_LINES = 400

EXCLUDE_DIRS = stacks.EXCLUDE_DIRS | {".claude-plugin"}

CI_PATHS = (
    ".github/workflows", ".gitlab-ci.yml", ".circleci", "Jenkinsfile",
    "azure-pipelines.yml", ".buildkite", "bitbucket-pipelines.yml", ".travis.yml",
    ".drone.yml", "appveyor.yml", "cloudbuild.yaml", "cloudbuild.yml",
)

# CI 설정에 그 검사를 부르는 줄이 있지만, 같은 줄의 `-x <태스크>`·`-DskipTests` 같은 인자가 실행에서 뺀다.
CI_EXCLUDED = "아니오(제외됨)"

# 테스트·검사를 빼거나 실패를 삼키는 표시. CI 설정과 Dockerfile 에서 찾는다.
EXCLUSION_PATTERNS = (
    (re.compile(r"(?<![\w-])-x\s+(test|check|\w*[Tt]est\w*)\b"), "gradle 태스크 제외"),
    (re.compile(r"--exclude-task\s+\w+"), "gradle 태스크 제외"),
    (re.compile(r"-DskipTests\b|-Dmaven\.test\.skip=true"), "maven 테스트 건너뜀"),
    (re.compile(r"continue-on-error:\s*true"), "실패해도 계속"),
    (re.compile(r"allow_failure:\s*true"), "실패 허용"),
    (re.compile(r"\b(test|lint|check|pytest|jest|vitest|eslint|ruff|mypy|tsc)\b[^#\n]*\|\|\s*(true|exit 0|:)\s*$"),
     "실패 무시(|| true)"),
    (re.compile(r"--no-verify\b"), "hook 우회"),
)


@dataclass
class Tool:
    """감지된 강제 수단 하나."""

    name: str
    kind: str                      # lint | format | typecheck | test | arch
    evidence: list[str]            # 무엇을 보고 감지했나 (파일 경로·매니페스트 표시)
    ci: str = "CI 없음"            # 예 | 간접 | 아니오 | 아니오(제외됨) | CI 없음
    ci_evidence: list[str] = field(default_factory=list)


# (이름, 종류, 설정 파일 후보, 매니페스트 안 표시, CI 에서 찾을 토큰, 간접 실행 토큰)
# 매니페스트 표시는 package.json·pyproject.toml·setup.cfg·gradle·pom·Cargo 본문을 소문자로 합친 텍스트에서 찾는다.
# 간접 실행 토큰 중 공백이 없는 것(`test`)은 맨 태스크 이름이라 러너 호출 줄에서만 찾는다.
_GRADLE_INDIRECT = ("gradlew build", "gradlew check", "gradle build", "gradle check")
_MAVEN_INDIRECT = ("mvn verify", "mvn install", "mvn package", "mvnw verify", "mvnw install", "mvnw package")
TOOL_SPECS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...] = (
    ("eslint", "lint",
     ("eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts", ".eslintrc",
      ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml", ".eslintrc.yaml"),
     ('"eslintconfig"',), ("eslint",), ()),
    ("biome", "lint", ("biome.json", "biome.jsonc"), (), ("biome",), ()),
    ("prettier", "format",
     (".prettierrc", ".prettierrc.json", ".prettierrc.js", ".prettierrc.cjs", ".prettierrc.yml",
      ".prettierrc.yaml", "prettier.config.js", "prettier.config.cjs", "prettier.config.mjs"),
     ('"prettier"',), ("prettier",), ()),
    ("tsc", "typecheck", ("tsconfig.json",), (), ("tsc",), ()),
    ("jest", "test", ("jest.config.js", "jest.config.ts", "jest.config.cjs", "jest.config.mjs"),
     ('"jest"',), ("jest",), ()),
    ("vitest", "test", ("vitest.config.ts", "vitest.config.js", "vitest.config.mts"), ('"vitest"',),
     ("vitest",), ()),
    ("dependency-cruiser", "arch",
     (".dependency-cruiser.js", ".dependency-cruiser.cjs", ".dependency-cruiser.mjs", ".dependency-cruiser.json"),
     ('"dependency-cruiser"',), ("depcruise", "dependency-cruiser"), ()),
    ("eslint-plugin-boundaries", "arch", (), ('"eslint-plugin-boundaries"',), ("eslint",), ()),
    ("ruff", "lint", ("ruff.toml", ".ruff.toml"), ("[tool.ruff",), ("ruff",), ()),
    ("flake8", "lint", (".flake8",), ("[flake8]",), ("flake8",), ()),
    ("black", "format", (), ("[tool.black",), ("black",), ()),
    ("mypy", "typecheck", ("mypy.ini", ".mypy.ini"), ("[tool.mypy", "[mypy]"), ("mypy",), ()),
    ("pyright", "typecheck", ("pyrightconfig.json",), ("[tool.pyright",), ("pyright",), ()),
    ("pytest", "test", ("pytest.ini", "conftest.py", "tests/conftest.py"), ("[tool.pytest",), ("pytest",), ()),
    ("import-linter", "arch", (".importlinter",), ("[tool.importlinter", "[importlinter"), ("lint-imports",), ()),
    ("ktlint", "lint", (), ("ktlint",), ("ktlint",), _GRADLE_INDIRECT),
    ("detekt", "lint", ("detekt.yml", "config/detekt/detekt.yml"), ("detekt",), ("detekt",), _GRADLE_INDIRECT),
    ("spotless", "format", (), ("spotless",), ("spotless",), _GRADLE_INDIRECT + _MAVEN_INDIRECT),
    ("checkstyle", "lint", ("checkstyle.xml", "config/checkstyle/checkstyle.xml"), ("checkstyle",),
     ("checkstyle",), _GRADLE_INDIRECT + _MAVEN_INDIRECT),
    ("ArchUnit", "arch", (), ("archunit",), ("archunit",), ("test",) + _GRADLE_INDIRECT + _MAVEN_INDIRECT),
    ("Konsist", "arch", (), ("konsist",), ("konsist",), ("test",) + _GRADLE_INDIRECT),
    ("golangci-lint", "lint", (".golangci.yml", ".golangci.yaml", ".golangci.toml", ".golangci.json"), (),
     ("golangci",), ()),
    ("go-arch-lint", "arch", (".go-arch-lint.yml",), (), ("go-arch-lint",), ()),
    ("clippy", "lint", ("clippy.toml", ".clippy.toml"), (), ("clippy",), ()),
    ("rustfmt", "format", ("rustfmt.toml", ".rustfmt.toml"), (), ("rustfmt", "cargo fmt"), ()),
)

PRECOMMIT_PATHS = (".pre-commit-config.yaml", ".husky", "lefthook.yml", "lefthook.yaml", ".lefthook.yml")

# 규칙 문장 표시. 영어는 단어 경계, 한국어는 명령형·금지형 표현을 본다.
# "필수"·"절대경로" 처럼 규칙이 아닌 줄에 흔한 낱말은 넣지 않는다 — 목록이 길어지면 분류하는 쪽이 지친다.
RULE_PATTERNS = (
    re.compile(r"\b(?:DO NOT|DON'?T|MUST(?: NOT)?|NEVER|SHALL NOT|SHOULD NOT|FORBIDDEN|PROHIBITED)\b", re.I),
    re.compile(r"금지|반드시|절대(?:로)?\s|하지\s*마|하면\s*안\s*(?:된|됩|돼)|말\s*것|해서는\s*안"),
)
# 이 낱말이 든 제목 아래의 목록 항목은 문장에 표시가 없어도 규칙으로 뽑는다.
RULE_HEADING = re.compile(
    r"규칙|원칙|금지|제약|불변식|안티\s*패턴|하지\s*말|\b(?:rules?|constraints?|invariants?|anti-?patterns?|"
    r"don'?ts|do not|never|must)\b", re.I)
_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")


# --- 공통 -----------------------------------------------------------------

def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _rel(target: Path, path: Path) -> str:
    try:
        return str(path.relative_to(target))
    except ValueError:
        return str(path)


def _walk_files(target: Path):
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        for f in sorted(filenames):
            yield Path(dirpath) / f


def _doc_size(path: Path) -> dict:
    text = _read(path)
    return {"bytes": len(text.encode("utf-8")), "lines": len(text.splitlines())}


# --- 1. 문서 존재 -----------------------------------------------------------

def _agents_bridge(directory: Path) -> str:
    agents = directory / "AGENTS.md"
    if agents.is_symlink():
        try:
            same = agents.resolve() == (directory / "CLAUDE.md").resolve()
        except OSError:
            same = False
        return "CLAUDE.md 심링크" if same else "다른 파일을 가리키는 심링크"
    if agents.is_file():
        return "별도 파일"
    return "없음"


def doc_facts(target: Path) -> dict:
    root_claude = target / "CLAUDE.md"
    root = {"claude_md": root_claude.is_file(), "agents_md": _agents_bridge(target)}
    if root_claude.is_file():
        root.update(_doc_size(root_claude))
        root["too_long"] = root["bytes"] > ROOT_DOC_MAX_BYTES

    ml = stacks.logical_modules(target)
    modules = []
    for rel in ml.modules:
        d = target / rel
        entry = {"path": str(rel), "claude_md": (d / "CLAUDE.md").is_file(), "agents_md": _agents_bridge(d)}
        if entry["claude_md"]:
            entry["lines"] = _doc_size(d / "CLAUDE.md")["lines"]
            entry["too_long"] = entry["lines"] > MODULE_DOC_MAX_LINES
        modules.append(entry)

    design_dir = target / "docs" / "design"
    design = {"dir": design_dir.is_dir(), "readme": (design_dir / "README.md").is_file(),
              "domains": [], "orphan_decisions": [], "union_merge": False}
    if design_dir.is_dir():
        mds = sorted(p.name for p in design_dir.glob("*.md"))
        docs = [n for n in mds if n != "README.md" and not n.endswith(".decisions.md")]
        decisions = {n[: -len(".decisions.md")] for n in mds if n.endswith(".decisions.md")}
        for n in docs:
            domain = n[: -len(".md")]
            design["domains"].append({"domain": domain, "decisions": domain in decisions})
        design["orphan_decisions"] = sorted(decisions - {n[: -len(".md")] for n in docs})
    gitattributes = _read(target / ".gitattributes")
    design["union_merge"] = bool(re.search(r"^\s*docs/design/\*\.decisions\.md\s+.*merge=union", gitattributes, re.M))

    settings = target / ".claude" / "settings.json"
    verification = {
        "doc": next((p for p in ("docs/VERIFICATION.md", "VERIFICATION.md") if (target / p).is_file()), None),
        "legacy_testing_doc": next((p for p in ("docs/TESTING.md", "TESTING.md") if (target / p).is_file()), None),
        "verify_script": (target / "scripts" / "verify.sh").is_file(),
        "doc_check_script": (target / "scripts" / "check_docs.py").is_file(),
        "stop_hook_runs_verify": any("verify.sh" in c for e, c in hook_commands(settings) if e == "Stop"),
        "antipatterns": next((p for p in ("docs/ANTIPATTERNS.md", "ANTIPATTERNS.md") if (target / p).is_file()), None),
    }
    return {"root": root, "module_mode": ml.mode, "modules": modules, "design": design,
            "verification": verification}


# --- 2. 강제 수단 -----------------------------------------------------------

def hook_commands(settings: Path) -> list[tuple[str, str]]:
    """.claude/settings.json 의 hooks 에서 (이벤트, 명령) 목록."""
    try:
        data = json.loads(_read(settings) or "{}")
    except ValueError:
        return []
    hooks = data.get("hooks") if isinstance(data, dict) else None
    out = []
    if isinstance(hooks, dict):
        for event, matchers in hooks.items():
            for m in matchers if isinstance(matchers, list) else []:
                for h in (m.get("hooks") or []) if isinstance(m, dict) else []:
                    if isinstance(h, dict) and h.get("command"):
                        out.append((str(event), str(h["command"])))
    return out


def _manifest_text(target: Path) -> str:
    names = ("package.json", "pyproject.toml", "setup.cfg", "tox.ini", "Cargo.toml", "pom.xml",
             "build.gradle.kts", "build.gradle", "settings.gradle.kts", "settings.gradle",
             "gradle/libs.versions.toml")
    text = "".join(_read(target / n) for n in names)
    # 멀티 모듈이면 하위 매니페스트에만 도구가 선언된 경우가 많다.
    for rel in stacks.find_manifest_modules(target):
        if rel == Path("."):
            continue
        for n in ("package.json", "pyproject.toml", "build.gradle.kts", "build.gradle", "pom.xml"):
            text += _read(target / rel / n)
    return text.lower()


def ci_files(target: Path) -> list[Path]:
    out = []
    for c in CI_PATHS:
        p = target / c
        if p.is_dir():
            out.extend(sorted(q for q in p.rglob("*") if q.is_file()))
        elif p.is_file():
            out.append(p)
    return out


def _dockerfiles(target: Path) -> list[Path]:
    return [p for p in _walk_files(target) if p.name == "Dockerfile" or p.name.startswith("Dockerfile.")
            or p.name.endswith(".Dockerfile")]


def _command_lines(target: Path, files: list[Path]) -> list[tuple[str, int, str]]:
    """주석을 뺀 (경로, 줄, 내용). 검사 명령 토큰을 찾는 데 쓴다."""
    out = []
    for f in files:
        for i, line in enumerate(_read(f).splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "//")):
                continue
            out.append((_rel(target, f), i, stripped))
    return out


def _npm_script_tokens(target: Path, tool_tokens: tuple[str, ...]) -> tuple[str, ...]:
    """package.json 스크립트 중 본문이 이 도구를 부르는 것 → CI 에서 그 스크립트를 부르는 형태들."""
    scripts = stacks.npm_scripts(target)
    out: list[str] = []
    for name, body in scripts.items():
        if any(t in body.lower() for t in tool_tokens):
            out += [f"npm run {name}", f"pnpm run {name}", f"yarn run {name}", f"pnpm {name}", f"yarn {name}"]
            if name == "test":
                out += ["npm test", "npm t", "pnpm test", "yarn test"]
    return tuple(out)


# 빌드·테스트 러너를 부르는 줄. `test` 같은 맨 태스크 이름은 이 줄에서만 찾는다 — 아니면 CI 의 job 이름
# `test:` 나 `-x test` 가 그 태스크를 돌린다는 근거가 된다.
_RUNNER = re.compile(r"(?<![\w.-])(?:\./)?(?:gradlew|gradle|mvnw|mvn|npm|pnpm|yarn|npx|bunx?|pytest|tox|nox|go|cargo|"
                     r"make|python3?|uv|poetry)(?![\w-])")
_GRADLE = re.compile(r"(?<![\w.-])(?:\./)?gradlew?(?![\w-])")
# YAML 의 이름표 줄(`- name: Run gradle test`)은 명령이 아니다.
_LABEL_LINE = re.compile(r"^-?\s*name\s*:")
# 같은 줄에서 태스크를 실행에서 빼는 인자. `-x` 는 gradle 줄에서만 본다(`pytest -x` 는 다른 뜻이다).
_GRADLE_EXCLUDE_ARG = re.compile(r"(?<![\w-])(?:-x|--exclude-task)(?:\s+|=)(\S+)")
_MAVEN_SKIP_TESTS = re.compile(r"(?<![\w-])-DskipTests(?:=true)?(?![=\w])")
_MAVEN_SKIP_TEST_BUILD = re.compile(r"(?<![\w-])-Dmaven\.test\.skip=true\b")


def _token_pattern(token: str) -> re.Pattern:
    """토큰이 명령으로 쓰인 자리. 뒤에 대문자로 이어지는 것은 허용한다 — gradle 태스크가 `ktlintCheck`·
    `detektMain` 처럼 도구 이름에 붙는다. 소문자로 이어지면 다른 낱말이다(`tsc` ≠ `tsconfig`)."""
    return re.compile(rf"(?<![\w-]){re.escape(token)}(?![a-z0-9_-])")


def _without_exclusions(text: str) -> tuple[str, set[str]]:
    """(제외 인자를 지운 줄, 그 줄이 실행에서 빼는 태스크 이름). `-x :app:test` 는 `test` 로 센다."""
    excluded: set[str] = set()
    if _GRADLE.search(text):
        excluded |= {m.group(1).rsplit(":", 1)[-1] for m in _GRADLE_EXCLUDE_ARG.finditer(text)}
        text = _GRADLE_EXCLUDE_ARG.sub(" ", text)
    if _MAVEN_SKIP_TESTS.search(text):
        excluded.add("test")
        text = _MAVEN_SKIP_TESTS.sub(" ", text)
    if _MAVEN_SKIP_TEST_BUILD.search(text):
        excluded |= {"test", "test-compile"}
        text = _MAVEN_SKIP_TEST_BUILD.sub(" ", text)
    return text, excluded


def _ci_hits(lines: list[tuple[str, int, str]], anywhere: tuple[str, ...], bare: tuple[str, ...] = (),
             excludes=lambda names: False) -> tuple[list[str], list[str]]:
    """(실행 근거 줄, 제외된 줄).

    anywhere 는 줄 어디서나 찾는 명령 형태(`npm test`·`gradlew build`·도구 이름), bare 는 러너 호출 줄에서만
    찾는 맨 태스크 이름이다. 제외 인자(`-x test`·`-DskipTests`) 안에서만 보인 토큰은 근거가 아니다. 러너 호출
    줄에서 `excludes(그 줄이 빼는 태스크 이름)` 가 참이면 토큰이 보여도 그 줄은 제외된 줄로 센다
    (`mvn package -DskipTests` 는 `mvn test` 를 뺀 줄이다)."""
    any_p = [_token_pattern(t) for t in anywhere if t]
    bare_p = [_token_pattern(t) for t in bare if t]
    hits, excluded = [], []
    for path, no, text in lines:
        runner = bool(_RUNNER.search(text)) and not _LABEL_LINE.match(text)
        patterns = any_p + (bare_p if runner else [])
        kept, dropped = _without_exclusions(text)
        found = any(p.search(kept) for p in patterns)
        if found and not excludes(dropped):
            hits.append(f"{path}:{no}")
        elif found or any(p.search(text) for p in patterns) or (runner and dropped and excludes(dropped)):
            excluded.append(f"{path}:{no}")
    return hits, excluded


def detect_tools(target: Path, ci_lines: list[tuple[str, int, str]], has_ci: bool) -> list[Tool]:
    manifest = _manifest_text(target)
    tools = []
    for name, kind, files, markers, ci_tokens, indirect in TOOL_SPECS:
        evidence = [f for f in files if (target / f).exists()]
        evidence += [f"매니페스트: {m.strip(chr(34) + '[')}" for m in markers if m in manifest]
        if not evidence:
            continue
        tool = Tool(name, kind, evidence)
        if has_ci:
            bare = tuple(t for t in indirect if " " not in t)
            own = [_token_pattern(t) for t in ci_tokens]

            def excludes(names: set[str], bare: tuple[str, ...] = bare, own: list = own) -> bool:
                return any(n in bare or any(p.search(n) for p in own) for n in names)

            direct, direct_x = _ci_hits(ci_lines, ci_tokens + _npm_script_tokens(target, ci_tokens),
                                        excludes=excludes)
            via, via_x = _ci_hits(ci_lines, tuple(t for t in indirect if " " in t), bare, excludes)
            if direct:
                tool.ci, tool.ci_evidence = "예", direct
            elif via:
                tool.ci, tool.ci_evidence = "간접(상위 태스크가 포함할 수 있음 — 확인 필요)", via
            elif direct_x or via_x:
                tool.ci, tool.ci_evidence = CI_EXCLUDED, sorted(set(direct_x + via_x))
            else:
                tool.ci = "아니오"
        tools.append(tool)
    return tools


def enforcement_facts(target: Path) -> dict:
    cis = ci_files(target)
    ci_lines = _command_lines(target, cis)
    tools = detect_tools(target, ci_lines, bool(cis))

    commands = stacks.detect_commands(target)
    command_rows = []
    for role, cmd in commands.checks():
        row = {"role": role, "command": cmd, "ci": "CI 없음", "ci_evidence": []}
        if cis:
            # gradle·maven 은 러너 이름을 뗀 태스크 이름으로도 찾는다(`./gradlew ktlintCheck test` 도 근거다).
            tasks: tuple[str, ...] = ()
            if cmd.startswith(("./gradlew ", "gradle ", "./mvnw ", "mvn ")):
                tasks = tuple(t for t in cmd.split()[1:] if not t.startswith("-"))
            hits, dropped = _ci_hits(ci_lines, (cmd,), tasks, lambda names, tasks=tasks: bool(names & set(tasks)))
            if hits:
                row["ci"], row["ci_evidence"] = "예", hits
            elif dropped:
                row["ci"], row["ci_evidence"] = CI_EXCLUDED, dropped
            else:
                row["ci"] = "아니오"
        command_rows.append(row)

    exclusions = []
    for path, no, text in ci_lines + _command_lines(target, _dockerfiles(target)):
        for pattern, label in EXCLUSION_PATTERNS:
            if pattern.search(text):
                exclusions.append({"where": f"{path}:{no}", "label": label, "text": text[:160]})
                break

    precommit = [p for p in PRECOMMIT_PATHS if (target / p).exists()]
    git_hook = target / ".git" / "hooks" / "pre-commit"
    if git_hook.is_file():
        precommit.append(".git/hooks/pre-commit (저장소에 커밋되지 않는 로컬 설정)")

    settings = target / ".claude" / "settings.json"
    agent_hooks = []
    for event, cmd in hook_commands(settings):
        missing = _missing_scripts(target, cmd)
        agent_hooks.append({"event": event, "command": cmd[:160], "missing": missing,
                            "old_ai_ready": ".ai-ready/" in cmd})

    return {
        "stack": _stack_label(target, commands),
        "ci_files": [_rel(target, p) for p in cis],
        "tools": [asdict(t) for t in tools],
        "commands": command_rows,
        "command_notes": list(commands.notes),
        "exclusions": exclusions,
        "precommit": precommit,
        "agent_hooks": agent_hooks,
    }


def _stack_label(target: Path, commands: stacks.Commands) -> str:
    layout = stacks.detect_layout(target)
    parts = [f"빌드 시스템 {commands.build_system}"]
    if layout is not None:
        parts.append(f"스택 {layout.stack} ({layout.evidence})")
    return " · ".join(parts)


def _missing_scripts(target: Path, cmd: str) -> list[str]:
    """hook 명령이 가리키는 저장소 상대 스크립트 중 없는 것. PATH 명령과 `$VAR` 는 판정하지 않는다."""
    missing = []
    for token in cmd.split():
        t = token.strip("'\";&|")
        for prefix in ('$CLAUDE_PROJECT_DIR/', '${CLAUDE_PROJECT_DIR}/', '"$CLAUDE_PROJECT_DIR"/'):
            t = t.replace(prefix, "")
        if "$" in t or t.startswith(("-", "/")):
            continue
        if not (t.startswith("./") or t.endswith((".py", ".sh", ".js", ".ts"))):
            continue
        rel = t[2:] if t.startswith("./") else t
        if rel and not (target / rel).exists() and t not in missing:
            missing.append(t)
    return missing


# --- 3. 규칙 문장 -----------------------------------------------------------

def _is_guidance_doc(target: Path, path: Path) -> bool:
    if path.suffix not in (".md", ".mdc"):
        return False
    name = path.name.upper()
    if name.startswith(("CHANGELOG", "HISTORY", "LICENSE")):
        return False
    return True


_ENTRY_DOCS = {"CLAUDE.md", "AGENTS.md"}


def _rule_file_order(target: Path, path: Path) -> tuple:
    """상한에서 잘릴 때 에이전트가 먼저 읽는 문서가 남도록 순서를 정한다."""
    rel = path.relative_to(target)
    if path.name in _ENTRY_DOCS:
        rank = 0
    elif rel.parts[0] == "docs":
        rank = 1
    elif not rel.parts[0].startswith("."):
        rank = 2
    else:
        rank = 3  # .claude/·.agents/ 같은 도구 설정 폴더
    return (rank, len(rel.parts), str(rel))


def rule_lines(target: Path, limit: int = MAX_RULE_LINES) -> tuple[list[dict], int]:
    """(규칙 줄 목록, 전체 개수). 목록은 limit 에서 자른다."""
    files = sorted((p for p in _walk_files(target) if _is_guidance_doc(target, p)),
                   key=lambda p: _rule_file_order(target, p))
    seen: set = set()
    rows: list[dict] = []
    total = 0
    for path in files:
        text = _read(path)
        # AGENTS.md → CLAUDE.md 심링크와 도구 폴더 사이의 복사본은 한 번만 센다.
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        in_fence = False
        rule_heading = False
        for no, line in enumerate(text.splitlines(), 1):
            if _FENCE.match(line):
                in_fence = not in_fence
                continue
            if in_fence or not line.strip():
                continue
            h = _HEADING.match(line)
            if h:
                rule_heading = bool(RULE_HEADING.search(h.group(2)))
                continue
            hit = any(p.search(line) for p in RULE_PATTERNS)
            under_heading = rule_heading and bool(_LIST_ITEM.match(line))
            if not (hit or under_heading):
                continue
            total += 1
            if len(rows) < limit:
                rows.append({"where": f"{_rel(target, path)}:{no}", "text": line.strip()[:200],
                             "via": "문장" if hit else "규칙 제목 아래 항목"})
    return rows, total


# --- 모으기·그리기 ------------------------------------------------------------

def collect(target: Path, rule_limit: int = MAX_RULE_LINES) -> dict:
    rules, total = rule_lines(target, rule_limit)
    return {
        "target": str(target),
        "docs": doc_facts(target),
        "enforcement": enforcement_facts(target),
        "rules": rules,
        "rules_total": total,
    }


def _cell(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _yes(b: bool) -> str:
    return "있음" if b else "**없음**"


def render(facts: dict) -> str:
    d, e = facts["docs"], facts["enforcement"]
    # 절대 경로는 이 장비의 사용자 이름·폴더 구조를 드러낸다. 저장소 이름만 적는다.
    out = [f"# ai-ready 빈틈 보고서 — `{Path(facts['target']).name}`", "",
           "점수는 없다. 아래는 스크립트가 확인한 사실이고, 규칙 문장의 분류(A/B/C/D)는 audit 스킬이 이어서 한다.", ""]

    out += ["## 1. 문서 존재", ""]
    r = d["root"]
    if r["claude_md"]:
        size = f"{r['bytes']:,}바이트 · {r['lines']}줄"
        flag = f" — **길이 과다** (기준 {ROOT_DOC_MAX_BYTES:,}바이트)" if r["too_long"] else ""
        out.append(f"- 루트 `CLAUDE.md`: 있음 ({size}){flag}")
    else:
        out.append("- 루트 `CLAUDE.md`: **없음**")
    out.append(f"- 루트 `AGENTS.md`: {r['agents_md']}")

    mode_label = {"multi": "멀티 모듈(하위 빌드 매니페스트)", "single": "단일 모듈(스택 기준점의 하위 디렉토리)",
                  "no-adapter": "모듈 기준점을 못 찾음 — 맞는 스택 어댑터 없음",
                  "no-code": "모듈 기준점 아래 코드 디렉토리 없음"}[d["module_mode"]]
    out += ["", f"### 모듈 CLAUDE.md — {mode_label}", ""]
    if d["modules"]:
        out += ["| 모듈 | CLAUDE.md | AGENTS.md |", "|---|---|---|"]
        for m in d["modules"]:
            if m["claude_md"]:
                doc = f"있음 ({m['lines']}줄)" + (f" — **길이 과다** (기준 {MODULE_DOC_MAX_LINES}줄)"
                                                  if m["too_long"] else "")
            else:
                doc = "**없음**"
            out.append(f"| `{_cell(m['path'])}` | {doc} | {m['agents_md']} |")
    else:
        out.append("- 모듈 목록 없음")

    ds = d["design"]
    out += ["", "### 결정 기록 (`docs/design/`)", ""]
    if not ds["dir"]:
        out.append("- `docs/design/`: **없음**")
    else:
        out.append(f"- `docs/design/README.md`: {_yes(ds['readme'])}")
        for dom in ds["domains"]:
            pair = "있음" if dom["decisions"] else "**없음**"
            out.append(f"- `{dom['domain']}.md` ↔ `{dom['domain']}.decisions.md`: 결정 카드 파일 {pair}")
        for orphan in ds["orphan_decisions"]:
            out.append(f"- `{orphan}.decisions.md`: 짝이 되는 현재 동작 문서 `{orphan}.md` **없음**")
    out.append(f"- `.gitattributes` 의 `docs/design/*.decisions.md merge=union`: {_yes(ds['union_merge'])}")

    v = d["verification"]
    out += ["", "### 검증 문서·장치", ""]
    out.append(f"- 검증 문서: {('`' + v['doc'] + '`') if v['doc'] else '**없음**'}")
    if v["legacy_testing_doc"]:
        out.append(f"- `{v['legacy_testing_doc']}`: 있음 (검증 문서로 흡수 대상)")
    out.append(f"- `scripts/verify.sh`: {_yes(v['verify_script'])}")
    out.append(f"- `scripts/check_docs.py` (문서 정합 검사): {_yes(v['doc_check_script'])}")
    out.append(f"- `.claude/settings.json` Stop hook 이 verify.sh 실행: {'예' if v['stop_hook_runs_verify'] else '**아니오**'}")
    out.append(f"- 안티패턴 원장: {('`' + v['antipatterns'] + '`') if v['antipatterns'] else '**없음**'}")

    out += ["", "## 2. 강제 수단", "", f"- {e['stack']}"]
    out.append(f"- CI 설정: {', '.join('`' + p + '`' for p in e['ci_files']) if e['ci_files'] else '**없음**'}")
    out += ["", "### 감지된 검사 도구", ""]
    if e["tools"]:
        out += ["| 도구 | 종류 | 근거 | CI 실행 | CI 근거 |", "|---|---|---|---|---|"]
        for t in e["tools"]:
            out.append(f"| {t['name']} | {t['kind']} | {_cell(', '.join(t['evidence']))} | {t['ci']} | "
                       f"{_cell(', '.join(t['ci_evidence'][:5]))} |")
    else:
        out.append("- 감지된 lint·formatter·타입체커·테스트 러너·아키텍처 테스트 없음")
    out += ["", "### 확인 명령 (매니페스트에서 추론)", ""]
    if e["commands"]:
        out += ["| 역할 | 명령 | CI 실행 | CI 근거 |", "|---|---|---|---|"]
        for c in e["commands"]:
            out.append(f"| {c['role']} | `{_cell(c['command'])}` | {c['ci']} | {_cell(', '.join(c['ci_evidence'][:5]))} |")
    else:
        out.append("- 추론한 명령 없음")
    for note in e["command_notes"]:
        out.append(f"- 참고: {note}")
    out += ["", "### 테스트 제외·실패 무시 표시 (CI·Dockerfile)", ""]
    if e["exclusions"]:
        for x in e["exclusions"]:
            out.append(f"- `{x['where']}` — {x['label']}: `{_cell(x['text'])}`")
    else:
        out.append("- 없음")
    out += ["", "### 로컬 강제 (pre-commit·에이전트 hook)", ""]
    out.append(f"- pre-commit 류: {', '.join('`' + p + '`' for p in e['precommit']) if e['precommit'] else '없음'}")
    if e["agent_hooks"]:
        for h in e["agent_hooks"]:
            extra = ""
            if h["missing"]:
                extra += f" — **가리키는 스크립트 없음**: {', '.join(h['missing'])}"
            if h["old_ai_ready"]:
                extra += " — ai-ready 옛 버전이 설치한 hook (CHANGELOG 2.0.0 이관 안내 참고)"
            out.append(f"- `.claude/settings.json` {h['event']}: `{_cell(h['command'])}`{extra}")
    else:
        out.append("- `.claude/settings.json` hook: 없음")

    out += ["", "## 3. 규칙 문장", "",
            "문서에서 규칙처럼 쓰인 줄이다. 분류는 audit 스킬이 한다 — "
            "A 이미 강제됨 / B 싸게 강제 가능 / C 강제 불가(문서에 남김) / D 코드와 어긋남·낡음.", ""]
    if facts["rules"]:
        for i, row in enumerate(facts["rules"], 1):
            via = "" if row["via"] == "문장" else " _(규칙 제목 아래 항목)_"
            out.append(f"- R{i}. `{row['where']}` — {row['text']}{via}")
        if facts["rules_total"] > len(facts["rules"]):
            out.append(f"- … 전체 {facts['rules_total']}줄 중 {len(facts['rules'])}줄만 실었다 "
                       f"(`--max-rules` 로 늘린다)")
    else:
        out.append("- 규칙 문장 없음")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="ai-ready 빈틈 보고서 (점수 없음)")
    ap.add_argument("--target", required=True, help="대상 저장소 경로")
    ap.add_argument("--out", help="보고서를 쓸 파일 (생략 시 stdout)")
    ap.add_argument("--json", action="store_true", help="markdown 대신 사실 JSON 을 낸다")
    ap.add_argument("--max-rules", type=int, default=MAX_RULE_LINES, help="규칙 문장 최대 개수")
    args = ap.parse_args()
    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"오류: 대상이 디렉토리가 아니다: {target}", file=sys.stderr)
        return 2
    facts = collect(target, args.max_rules)
    text = json.dumps(facts, ensure_ascii=False, indent=2) + "\n" if args.json else render(facts)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"보고서: {out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
