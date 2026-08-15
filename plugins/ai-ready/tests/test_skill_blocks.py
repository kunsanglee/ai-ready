"""SKILL.md 안 셸 블록을 문서에서 뽑아 프레시 셸에서 실제로 돌리는 회귀 시험.

왜 문서를 시험하나. loop 계열 스킬의 런타임 상태 배선은 SKILL.md 안 셸 블록이 전부다 —
오케스트레이터가 그 블록을 그대로 Bash 도구에 넣어 실행하므로 블록이 곧 코드다. 문법만 보는
검사(`bash -n`)는 세 가지를 못 잡는다. 프레시 셸에서 변수가 실제로 복원되는지, fail-loud
경로가 실제로 비0 으로 죽는지, 지운다고 말한 것이 실제로 지워지는지.

0.9.5 검증에서 정적 검사를 통과한 블록 셋이 실행에서 결함으로 드러났다. 종료 정리 두 블록이
빈 LOOP_DIR 로 아무것도 지우지 않으면서 종료코드 0 을 냈고, loop-build Step 0 추가 블록이
파일시스템 루트에 쓰려 했고, 트리 변경 확인이 `git status --porcelain` 만 봐 2회차부터 거짓
정체를 냈다. 그 셋을 잡은 시험이 이 파일이다.

**대조군을 함께 둔다.** 검사가 아예 돌지 않은 것과 검사가 아무것도 못 찾은 것은 출력이 같다.
그래서 "잡혀야 하는 것" 을 일부러 넣어 검사에 이가 있는지 매번 확인한다(TestControlGroups).

블록은 문서에서 뽑아 쓴다 — 여기에 다시 타이핑하면 문서가 아니라 이 파일의 기억을 시험한다.

범위는 claude 트리의 `build`·`review` 둘이다. codex 트리의 같은 스킬은
셸 블록이 하나도 없어 전부 산문 계약이고, `audit`·`apply` 의 블록은 파이썬 스크립트 호출이라
`test_smoke.py` 가 그 스크립트를 직접 시험한다.

stdlib 만. 실행:

    python3 -m unittest tests.test_skill_blocks    # plugin 루트에서
    python3 tests/test_skill_blocks.py

다른 트리를 대상으로 돌리려면(예: 설치된 캐시가 레포 작업본과 같게 동작하는지):

    AI_READY_TREE=~/.claude/plugins/cache/ai-ready/ai-ready/0.9.5 python3 tests/test_skill_blocks.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

TREE = Path(os.environ.get("AI_READY_TREE") or Path(__file__).resolve().parents[1])
SKILLS = TREE / "skills"
ENGINE = TREE / "_loop-engine"

# ── 블록 추출 ────────────────────────────────────────────────────────────────
# 들여쓴 펜스도 받는다 — 게이트 실패 카운터 블록은 불릿 안에 2칸 들여쓰여 있고,
# 들여쓰기를 무시하는 정규식은 그 블록을 조용히 빠뜨린다(그게 여덟 번째 블록이다).
_FENCE = re.compile(r"^(?P<indent>[ \t]*)```bash\n(?P<body>.*?)^(?P=indent)```", re.S | re.M)

# 문서에 있어야 하는 bash 블록 수. 늘거나 줄면 fail-loud — 새 블록은 이 하네스에 항목을 더할
# 신호이고, 준 블록은 앵커가 죽었다는 신호다. "16개 통과" 가 "16개를 봤다" 를 뜻하게 하는 장치.
EXPECTED_BLOCK_COUNTS = {"build": 12, "review": 3, "spec": 2}

# 블록 식별은 순번이 아니라 내용 앵커로 한다 — 블록이 하나 끼어들어도 나머지 항목이 밀리지 않는다.
# 앵커는 그 블록의 기능 핵심 한 줄이라, 그 줄이 사라지면 시험이 먼저 멈춘다.
ANCHORS = {
    # build — 실행층 하나로 통합된 뒤 블록 12개. 앞의 lr-*(loop-run)/lb-*(loop-build) 구분은
    # 스킬이 합쳐지며 사라졌다.
    "b-setup":      ("build", 'LOOP_DIR="$PROJECT_ROOT/.loop/run/$TICKET"'),
    "b-specgate":   ("build", "착수 전 스펙 검사 실패"),
    "b-budget":     ("build", "BUDGET_MIN_PHASE"),
    "b-phase":      ("build", 'PHASE="<이 phase 의 name>"'),
    "b-gate":       ("build", "run_gate BUILD"),
    "b-gatefail":   ("build", 'G="$LOOP_DIR/gate.fail"'),
    "b-lens":       ("build", "checker 렌즈:"),
    "b-score":      ("build", 'SCORED=$(bash "$ENG/score.sh"'),
    "b-done":       ("build", '.status = "done"'),
    "b-makerinput": ("build", "MAKER_INPUT="),
    "b-tree":       ("build", "tree.snapshot"),
    "b-cleanup":    ("build", 'PTR="$PROJECT_ROOT/.loop/run/.active-$BR"'),
    "v-detect":     ("review", "review 값:"),
    "v-findings":   ("review", ': > "$F"'),
    "v-score":      ("review", 'rm -f "$F"'),
    # spec — 도출층. 블록 둘뿐인 것은 이 층의 일이 대부분 사람과의 왕복이기 때문이고,
    # 기계가 맡는 자리는 시작 조건 확인과 종료 조건 판정 둘이다.
    "s-setup":      ("spec", 'SPEC_DIR="$PROJECT_ROOT/.loop/spec/$SLUG"'),
    "s-exit":       ("spec", "미결 0 — 산출 단계로 간다"),
}

# 스킬 폴더 자리표시자. 호스트가 스킬 본문 첫머리에 텍스트로 주입하는 "Base directory for this
# skill" 값을 오케스트레이터가 여기에 붙여 넣는다. `$CLAUDE_PLUGIN_ROOT` 는 Bash 도구의 셸에
# **없어서**(스킬 본문을 만들 때 치환되는 값이라 자식 셸로 안 내려간다) 그 자리를 대신한다.
# 치환은 run_block 이 ANCHORS 의 스킬 이름으로 자동 수행한다 — 호출부마다 적으면 아홉 군데가 되고
# 새 블록이 늘 때 빠뜨리기 쉽다. 일부러 안 치환하고 돌리는 대조군은 keep_placeholder=True 를 쓴다.
SKILL_DIR_PLACEHOLDER = '"<이 스킬 본문 첫머리의 Base directory 를 그대로 넣는다>"'

# 문서가 "재유도 프리앰블 뒤에" 라고 지시하는 블록. 프리앰블은 lr-gate 에서 뽑아 붙인다.
NEEDS_PREAMBLE = {"b-makerinput", "b-tree"}

# 프리앰블 마지막 줄 — 이 줄까지가 재유도 프리앰블이다.
_PREAMBLE_END = 'set -a; . "$LOOP_DIR/params.env"; set +a'

# LOOP_DIR 파생 상태를 쓰는 블록은 반드시 포인터에서 재유도하거나 NEEDS_PREAMBLE 이어야 한다.
_REDERIVE_MARK = ".active-$BR"
_STATE_VARS = ("$LOOP_DIR", "$PHASES", "$HIST", "$STATE", "$PHASE")


def _blocks(skill: str) -> list[str]:
    text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
    out = []
    for m in _FENCE.finditer(text):
        body = m.group("body")
        if m.group("indent"):
            body = textwrap.dedent(body)
        out.append(body)
    return out


ALL_BLOCKS: dict[str, list[str]] = {s: _blocks(s) for s in EXPECTED_BLOCK_COUNTS}


def _pick(block_id: str) -> str:
    skill, anchor = ANCHORS[block_id]
    hits = [b for b in ALL_BLOCKS[skill] if anchor in b]
    if len(hits) != 1:
        raise AssertionError(
            f"앵커 '{anchor}' 가 {skill}/SKILL.md 의 블록 {len(hits)}개에 매칭 — "
            f"1개여야 한다. 문서가 바뀠으면 ANCHORS 를 고친다."
        )
    return hits[0]


BLOCKS: dict[str, str] = {bid: _pick(bid) for bid in ANCHORS}

_pre_lines = BLOCKS["b-gate"].splitlines(keepends=True)
_pre_idx = [i for i, ln in enumerate(_pre_lines) if _PREAMBLE_END in ln]
if len(_pre_idx) != 1:
    raise AssertionError("b-gate 에서 재유도 프리앰블 끝(set -a … params.env)을 못 찾음")
PREAMBLE = "".join(_pre_lines[: _pre_idx[0] + 1])


# ── 격리 레포 ────────────────────────────────────────────────────────────────
# 가짜 gradle 래퍼. 실제 gradle 없이 게이트 층을 돌린다. 형식은 gate_parse.py 가 받는 실물
# 형식(Kotlin 2.x — 열 번호 뒤 콜론 없음)이고, GATE_LOG 로 호출 순서를 남겨 "컴파일이 깨지면
# 테스트는 돌리지 않는다" 사슬을 확인하게 한다.
FAKE_GRADLEW = """\
#!/usr/bin/env bash
[ -n "${GATE_LOG:-}" ] && echo "$*" >> "$GATE_LOG"
case "${GATE_MODE:-pass}" in
  fail-build)
    if [[ "$*" == *assemble* ]]; then
      echo "e: file://$PWD/src/Main.kt:7:14 Unresolved reference: missingSymbol"
      echo "e: file://$PWD/src/Main.kt:9:3 Type mismatch: inferred type is String but Int was expected"
      exit 1
    fi ;;
  fail-test)
    if [[ "$*" == *test* && "$*" != *assemble* ]]; then
      echo "MainTest > 합계를 낸다() FAILED"
      echo "    org.opentest4j.AssertionFailedError at MainTest.kt:16"
      exit 1
    fi ;;
esac
echo "BUILD SUCCESSFUL"
exit 0
"""

BUILD_GRADLE = """\
plugins { kotlin("jvm") version "2.0.0" }
dependencies {
    implementation("org.springframework.boot:spring-boot-starter-web")
    implementation("org.jetbrains.kotlin:kotlin-stdlib")
}
"""

MAIN_KT = "fun main() { println(\"scratch\") }\n"

# 필수 자리가 없는 옛 형식. 0.9.11 까지는 이것으로 순회가 돌았다(위임만 못 했다). 0.9.12 부터
# tiebreaks·exit_criteria·irreversible 이, 1.4.0 부터 non_goals 가 필수라 **이 판은 어느
# 자리에서도 통과하면 안 된다** — 그 전환을 잠그는 것이 아래 TestSpecGate 의 회귀 대상이다.
PHASES_2_LEGACY = {
    "phases": [
        {"name": "foundation", "status": "pending", "design_ref": "docs/design.md §C5",
         "steps": [{"id": "types", "goal": "타입 정의", "layer": "domain",
                    "signature": "data class X()", "ac_cmd": "./gradlew assemble -x test",
                    "status": "pending"}]},
        {"name": "wiring", "status": "pending", "design_ref": "docs/design.md §C6",
         "steps": [{"id": "wire", "goal": "결선", "layer": "app",
                    "signature": "class Y()", "ac_cmd": "./gradlew assemble -x test",
                    "status": "pending"}]},
    ]
}

# 기본 픽스처 — 필수 자리를 갖춘 현행 형식. 착수 전 검사와 순회 입력 검증이 **둘 다** 이것들을
# 요구하므로, 다른 시험(예산·phase 스코프·done 갱신)이 쓰는 기본판도 이것이어야 한다.
# 두 phase 가 `non_goals` 의 두 형태를 각각 든다 — 표면을 좁힌 쪽과 안 좁힌 쪽(`false`).
PHASES_2 = {
    "tiebreaks": ["잠그는 것이 원본과 호출 규약을 맞추는 것보다 앞선다"],
    "phases": [
        {**PHASES_2_LEGACY["phases"][0],
         "exit_criteria": ["관성 분기를 지우면 그 검사가 실패한다"],
         "irreversible": False,
         "non_goals": ["수신 층", "성능 튜닝"]},
        {**PHASES_2_LEGACY["phases"][1],
         "exit_criteria": ["결선을 끊으면 통합 시험이 빨개진다"],
         "irreversible": "운영 DB 마이그레이션",
         "non_goals": False},
    ],
}


_MODULE_TMP: Path | None = None
_TEMPLATE: Path | None = None


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def setUpModule() -> None:  # noqa: N802 (unittest 규약)
    global _MODULE_TMP, _TEMPLATE
    for tool in ("git", "jq", "shasum", "python3", "bash"):
        if shutil.which(tool) is None:
            raise unittest.SkipTest(f"'{tool}' 미설치 — 스킬 블록 시험을 돌릴 수 없다")
    _MODULE_TMP = Path(tempfile.mkdtemp(prefix="ai-ready-skill-blocks-"))
    _TEMPLATE = _MODULE_TMP / "template"
    origin = _TEMPLATE / "origin.git"
    work = _TEMPLATE / "work"
    origin.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
    work.mkdir()
    _git(work, "init", "-q")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "skill block test")
    _git(work, "config", "commit.gpgsign", "false")
    (work / "build.gradle.kts").write_text(BUILD_GRADLE)
    gradlew = work / "gradlew"
    gradlew.write_text(FAKE_GRADLEW)
    gradlew.chmod(0o755)
    (work / "src").mkdir()
    (work / "src" / "Main.kt").write_text(MAIN_KT)
    (work / "docs").mkdir()
    (work / "docs" / "CONVENTIONS.md").write_text("# CONVENTIONS\n\n- 약어를 풀어 쓴다.\n")
    (work / "docs" / "ANTIPATTERNS.md").write_text("# ANTIPATTERNS\n\n- DO NOT 조용히 통과.\n")
    (work / "docs" / "design.md").write_text("# 설계\n\n## §C5 데이터 모델\n\n## §C6 결선\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "feat(CCE-999): 격리 시험 레포 초기 커밋")
    _git(work, "branch", "-M", "main")
    # 상대 경로 remote — 템플릿을 통째로 copytree 해도 사본의 origin 을 가리킨다.
    _git(work, "remote", "add", "origin", "../origin.git")
    _git(work, "push", "-q", "-u", "origin", "main")
    _git(work, "checkout", "-qb", "feature/CCE-999-scratch")


def tearDownModule() -> None:  # noqa: N802
    if _MODULE_TMP is not None:
        shutil.rmtree(_MODULE_TMP, ignore_errors=True)


class Run:
    """블록 한 번 실행 결과."""

    def __init__(self, proc: subprocess.CompletedProcess):
        self.rc = proc.returncode
        self.out = proc.stdout
        self.err = proc.stderr

    def __repr__(self) -> str:  # 실패 메시지에 그대로 실린다
        return f"rc={self.rc}\n--- stdout ---\n{self.out}\n--- stderr ---\n{self.err}"


class BlockCase(unittest.TestCase):
    """격리 레포 사본 하나를 쥐고 블록을 순서대로 돌리는 베이스."""

    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="skill-block-case-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        shutil.copytree(_TEMPLATE, self.scratch / "t")
        self.work = self.scratch / "t" / "work"
        self.blockdir = self.scratch / "blocks"
        self.blockdir.mkdir()
        self._n = 0

    # -- 실행 ---------------------------------------------------------------
    def env(self, **extra: str) -> dict[str, str]:
        base = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", str(self.scratch)),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
            "CLAUDE_PROJECT_DIR": str(self.work),
            # CLAUDE_PLUGIN_ROOT 는 **일부러 안 넣는다.** Bash 도구가 띄우는 셸에 그 변수가 없다는
            # 것이 실측이고, 여기서 주입하면 블록이 실제 환경에서는 안 도는데 시험만 초록이 된다.
            # 그 주입이 `ENG="$CLAUDE_PLUGIN_ROOT/_loop-engine"` 을 오래 살려 뒀다(TestControlGroups).
            # 실제 /tmp 를 오염시키지 않는다 — review 블록이 TMPDIR 하위에 findings 를 쓴다.
            "TMPDIR": str(self.scratch / "tmpdir"),
        }
        (self.scratch / "tmpdir").mkdir(exist_ok=True)
        base.update({k: v for k, v in extra.items() if v is not None})
        return base

    def run_block(self, block_id: str, *, env: dict[str, str] | None = None,
                  subst: dict[str, str] | None = None, body: str | None = None,
                  keep_placeholder: bool = False) -> Run:
        text = BLOCKS[block_id] if body is None else body
        if block_id in NEEDS_PREAMBLE and body is None:
            text = PREAMBLE + text
        if SKILL_DIR_PLACEHOLDER in text and not keep_placeholder:
            # 오케스트레이터가 하는 일과 같다 — 그 스킬 본문 첫머리의 base directory 를 붙여 넣는다.
            skill = ANCHORS[block_id][0]
            text = text.replace(SKILL_DIR_PLACEHOLDER, f'"{SKILLS / skill}"')
        for k, v in (subst or {}).items():
            self.assertIn(k, text, f"{block_id} 에 치환 대상 '{k}' 가 없다 — 문서가 바뀠다")
            text = text.replace(k, v)
        self._n += 1
        path = self.blockdir / f"{self._n:02d}-{block_id}.sh"
        path.write_text(text)
        proc = subprocess.run(["bash", str(path)], cwd=str(self.work),
                              env=env or self.env(), capture_output=True, text=True)
        return Run(proc)

    def sh(self, script: str, *, env: dict[str, str] | None = None) -> Run:
        """시험 쪽 보조 셸(문서 블록이 아닌 것). 트리 변형·픽스처 준비용."""
        proc = subprocess.run(["bash", "-c", script], cwd=str(self.work),
                              env=env or self.env(), capture_output=True, text=True)
        return Run(proc)

    # -- 상태 조회 -----------------------------------------------------------
    @property
    def pointer(self) -> Path:
        return self.work / ".loop" / "run" / ".active-feature-CCE-999-scratch"

    @property
    def loop_dir(self) -> Path:
        return Path(self.pointer.read_text().strip())

    def param(self, key: str) -> str:
        """params.env 를 source 해서 값을 읽는다 — %q 인용을 직접 파싱하지 않는다."""
        proc = subprocess.run(
            ["bash", "-c", f'set -a; . "$1"; printf "%s" "${{{key}-}}"', "_",
             str(self.loop_dir / "params.env")],
            capture_output=True, text=True, check=True)
        return proc.stdout

    # -- 준비 ---------------------------------------------------------------
    def setup_loop(self, **extra: str) -> Run:
        r = self.run_block("b-setup", env=self.env(**extra))
        self.assertEqual(r.rc, 0, f"b-setup 실패\n{r}")
        return r

    def setup_phases(self, data: dict | None = None) -> None:
        """분해 결과를 놓는다. **Step 0 을 다시 돌리지 않는다** — PHASES 는 Step 0 이 이미
        영속했고, 재실행하면 그 블록이 params.env 를 통째로 새로 써 앞서 준 MAX_ITER 같은
        값이 기본값으로 되돌아간다(loop-build 가 따로 두던 'Step 0 추가' 블록이 Step 0 본체로
        흡수되면서 생긴 차이다). 실제 루프에서도 Step 0 은 루프당 한 번만 돈다.
        """
        (self.loop_dir / "phases.json").write_text(
            json.dumps(data if data is not None else PHASES_2, ensure_ascii=False))

    def enter_phase(self, name: str) -> Run:
        return self.run_block("b-phase", subst={'"<이 phase 의 name>"': f'"{name}"'})


# ── 1. 블록 목록·문법·구조 ───────────────────────────────────────────────────

class TestBlockInventory(unittest.TestCase):
    def test_block_counts(self):
        for skill, expected in EXPECTED_BLOCK_COUNTS.items():
            self.assertEqual(
                len(ALL_BLOCKS[skill]), expected,
                f"{skill}/SKILL.md 의 bash 블록이 {len(ALL_BLOCKS[skill])}개 — {expected}개로 알고 있다. "
                f"늘었으면 이 하네스에 그 블록 항목을 더한다(시험 안 되는 블록을 남기지 않는다).")

    def test_every_block_parses(self):
        for skill, blocks in ALL_BLOCKS.items():
            for i, body in enumerate(blocks, 1):
                with self.subTest(skill=skill, block=i):
                    proc = subprocess.run(["bash", "-n"], input=body,
                                          capture_output=True, text=True)
                    self.assertEqual(proc.returncode, 0,
                                     f"{skill} 블록 {i} 문법 오류: {proc.stderr}")

    def test_no_block_relies_on_plugin_root_env(self):
        """`$CLAUDE_PLUGIN_ROOT` 는 Bash 도구의 셸에 없다 — 블록이 거기 기대면 안 된다.

        스킬 본문을 만들 때 치환되는 값이라 자식 셸로 안 내려간다(실측: `echo` 가 빈 문자열).
        그대로 쓰면 `ENG=/_loop-engine` 처럼 **있어 보이는데 없는** 경로가 되고, 뒤따르는
        `loop_param` 이 빈 값을 내며 조용히 흘러간다. 경로는 base directory 에서 유도한다.

        주석 줄은 뺀다 — 왜 이 변수를 쓰면 안 되는지 적은 줄이 블록마다 있고, 그 설명이 사라지면
        다음 사람이 같은 실수를 되돌린다.
        """
        def code_only(body: str) -> str:
            return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))

        offenders = [f"{skill} 블록 {i}"
                     for skill, blocks in ALL_BLOCKS.items()
                     for i, body in enumerate(blocks, 1)
                     if "CLAUDE_PLUGIN_ROOT" in code_only(body)]
        self.assertEqual(
            offenders, [],
            "이 블록들이 Bash 셸에 없는 변수를 쓴다 — base directory 자리표시자로 유도한다")

    def test_state_blocks_rederive_or_are_prepended(self):
        """LOOP_DIR 파생 상태를 쓰는 블록은 포인터에서 재유도하거나 프리앰블을 붙여야 한다.

        Bash 도구는 호출마다 새 셸이라 변수 carry-over 가 없다. 이 불변을 깬 블록이 0.9.5 에서
        셋 나왔다. 새 블록이 같은 실수를 하면 여기서 먼저 걸린다.
        """
        for bid, body in BLOCKS.items():
            if bid in NEEDS_PREAMBLE:
                continue
            if not any(v in body for v in _STATE_VARS):
                continue
            with self.subTest(block=bid):
                self.assertIn(
                    _REDERIVE_MARK, body,
                    f"{bid} 가 LOOP_DIR 파생 상태를 쓰는데 포인터 재유도가 없다 — "
                    f"프레시 셸에서 빈 값으로 돈다. NEEDS_PREAMBLE 에 넣거나 프리앰블을 블록에 넣는다.")


# ── 2. build Step 0 (셋업) ─────────────────────────────────────────────────

class TestLoopRunSetup(BlockCase):
    def test_setup_creates_state(self):
        r = self.setup_loop(MAX_ITER="3")
        self.assertIn("ticket=CCE-999", r.out, repr(r))
        self.assertIn("max_iter=3", r.out, repr(r))
        self.assertTrue(self.pointer.is_file(), "브랜치별 포인터가 없다")
        self.assertEqual(self.loop_dir, self.work / ".loop" / "run" / "CCE-999")
        self.assertEqual(self.param("MAX_ITER"), "3")
        self.assertEqual(self.param("ABS_CEIL"), "10")
        self.assertTrue(self.param("BUDGET_MIN").isdigit(), "BUDGET_MIN 이 정수로 안 영속됐다")
        self.assertEqual(self.param("LOOP_BASE_BRANCH"), "origin/main")
        self.assertIn("docs/CONVENTIONS.md", self.param("LOOP_CONVENTION_DOCS"))
        self.assertEqual(self.param("LOOP_KNOWLEDGE_LAYER"), "docs/ANTIPATTERNS.md")
        self.assertTrue(self.param("LOOP_BUILD_CMD").startswith("./gradlew"))
        self.assertTrue((self.loop_dir / "started.epoch").is_file())
        self.assertEqual(self.param("PHASES"), str(self.loop_dir / "phases.json"))

    def test_setup_clears_previous_phase_history(self):
        """앞 루프의 phase 별 이력이 남으면 회차 수(=history 줄 수)가 이어져 brake 가 즉시 문다.

        history 가 phase 별 파일로 갈리면서 Step 0 의 초기화 대상이 글롭이 됐다 — 단일
        `history.jsonl` 을 지우던 판을 그대로 두면 `history-foundation.jsonl` 이 살아남는다.
        """
        self.setup_loop()
        stale = self.loop_dir / "history-foundation.jsonl"
        stale.write_text('{"iteration":1}\n{"iteration":2}\n')
        (self.loop_dir / "stall-foundation.json").write_text("{}")
        self.setup_loop()
        self.assertFalse(stale.exists(), "앞 루프의 phase 이력이 남았다 — 회차가 이어져 세진다")
        self.assertFalse((self.loop_dir / "stall-foundation.json").exists(),
                         "앞 루프의 정체 상태가 남았다 — 거짓 STALLED 를 낸다")

    def test_gitignore_gets_loop_run_and_is_idempotent(self):
        self.setup_loop()
        gi = (self.work / ".gitignore").read_text()
        self.assertIn(".loop/run/\n", gi)
        self.setup_loop()
        self.assertEqual((self.work / ".gitignore").read_text().count(".loop/run/"), 1,
                         "재실행이 .gitignore 에 같은 규칙을 또 넣었다")

    def test_gitignore_missing_trailing_newline(self):
        """마지막 줄에 개행이 없으면 >> 가 두 규칙을 붙여 둘 다 깨진다 — 문서가 보정한다고 말한다."""
        (self.work / ".gitignore").write_text("*.log")  # 개행 없음
        self.setup_loop()
        lines = (self.work / ".gitignore").read_text().splitlines()
        self.assertIn("*.log", lines)
        self.assertIn(".loop/run/", lines)

    def test_max_iter_clamped_to_ceiling(self):
        r = self.setup_loop(MAX_ITER="99")
        self.assertIn("천장 10 로 제한", r.out, repr(r))
        self.assertEqual(self.param("MAX_ITER"), "10")

    def test_design_ref_absent_is_not_an_error(self):
        """설계 문서를 안 주는 것은 정상이다 — 그때는 phases.json 의 step·exit_criteria 가 근거다.

        종전에는 여기서 brief.md 를 만들어 사람 확인을 받았다. 그 자리는 phases.json 분해 승인이
        대신하므로 폴백이 없어졌고, 안 준 경우는 빈 값으로 영속돼 그대로 진행한다.
        """
        r = self.setup_loop()
        self.assertEqual(r.rc, 0, repr(r))
        self.assertEqual(self.param("LOOP_DESIGN_REF"), "")

    def test_design_ref_nonexistent_path_stops(self):
        """준 경로가 없으면 멈춘다. 조용히 넘기면 checker 가 정합 판정의 기준을 잃는데,
        그 실패는 소리가 안 난다 — 없는 파일을 못 읽었다고 아무도 말하지 않는다."""
        r = self.run_block("b-setup", env=self.env(LOOP_DESIGN_REF="/nope/spec.md"))
        self.assertEqual(r.rc, 3, repr(r))
        self.assertIn("지정한 설계 문서", r.err)
        self.assertFalse(self.pointer.exists(), "exit 3 인데 포인터가 남았다")

    def test_design_ref_existing_path_used(self):
        spec = self.work / "docs" / "design.md"
        r = self.setup_loop(LOOP_DESIGN_REF=str(spec))
        self.assertEqual(r.rc, 0, repr(r))
        self.assertEqual(self.param("LOOP_DESIGN_REF"), str(spec))

    def test_works_without_claude_project_dir(self):
        """plugin 밖 직접 실행 — PROJECT_ROOT 가 git 루트 폴백으로 잡혀야 한다."""
        env = self.env()
        env.pop("CLAUDE_PROJECT_DIR")
        r = self.run_block("b-setup", env=env)
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("ticket=CCE-999", r.out)


# ── 3. 순회 진입 + phases.json 검증 ─────────────────────────────────────────

class TestLoopBuildSetup(BlockCase):
    def test_budget_block_without_pointer_fails_loud(self):
        """포인터가 없으면 멈춘다. 재유도 없이 돌면 BUDGET_MIN 이 미정의라 0 이 영속되고,
        그러면 모든 사이클이 즉시 brake 된다 — 조용히 도는 것보다 여기서 죽는 편이 낫다.

        종전에는 이 검사가 loop-build 의 Step 0 '추가' 블록에 붙어 있었다. 그 블록이 Step 0 본체로
        흡수되면서(PHASES 를 거기서 영속) 검사 자리가 순회 진입 블록으로 옮겨졌다 — Step 0 은
        포인터를 *만드는* 쪽이라 포인터 부재를 검사할 수 없다.
        """
        r = self.run_block("b-budget")
        self.assertEqual(r.rc, 65, repr(r))
        self.assertIn("params.env 없음", r.err)

    def test_budget_scales_by_phase_count(self):
        self.setup_loop()
        per_phase = int(self.param("BUDGET_MIN"))
        self.setup_phases()
        r = self.run_block("b-budget")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn(f"{per_phase * 2}분 (phase 당 {per_phase} × 2개)", r.out, repr(r))
        self.assertEqual(self.param("BUDGET_MIN"), str(per_phase * 2))
        self.assertEqual(self.param("BUDGET_MIN_PHASE"), str(per_phase))

    def test_budget_recompute_is_idempotent(self):
        """재개로 이 블록이 다시 돌아도 재곱하지 않는다 — 480분이 나오면 회귀다."""
        self.setup_loop()
        per_phase = int(self.param("BUDGET_MIN"))
        self.setup_phases()
        self.run_block("b-budget")
        r = self.run_block("b-budget")
        self.assertIn(f"{per_phase * 2}분 (phase 당 {per_phase} × 2개)", r.out, repr(r))
        self.assertEqual(self.param("BUDGET_MIN"), str(per_phase * 2))

    # phases.json 스키마 위반 — 무인 순회 직전 fail-loud 로 걸러야 하는 것들.
    # `.phases` 자체가 없거나 빈 경우는 여기 없다 — 그건 앞선 (1a) 스펙 검사가 먼저 잡고,
    # 아래 test_empty_or_nonarray_phases_named_by_the_spec_gate 가 그 자리를 지킨다.
    SCHEMA_VIOLATIONS = {
        "name 누락": {"phases": [{"status": "pending",
                                "steps": [{"ac_cmd": "x", "status": "pending"}]}]},
        "name 에 슬래시": {"phases": [{"name": "a/b", "status": "pending",
                                   "steps": [{"ac_cmd": "x", "status": "pending"}]}]},
        "phase status 오타": {"phases": [{"name": "a", "status": "pendign",
                                       "steps": [{"ac_cmd": "x", "status": "pending"}]}]},
        "steps 누락": {"phases": [{"name": "a", "status": "pending"}]},
        "steps 빈배열": {"phases": [{"name": "a", "status": "pending", "steps": []}]},
        "step ac_cmd 누락": {"phases": [{"name": "a", "status": "pending",
                                      "steps": [{"status": "pending"}]}]},
        "step ac_cmd 빈문자열": {"phases": [{"name": "a", "status": "pending",
                                        "steps": [{"ac_cmd": "", "status": "pending"}]}]},
        "step status 오타": {"phases": [{"name": "a", "status": "pending",
                                      "steps": [{"ac_cmd": "x", "status": "done!"}]}]},
    }

    @staticmethod
    def with_spec_fields(data: dict) -> dict:
        """위반 사례에 착수 전 검사가 요구하는 자리를 채워 넣는다.

        순회 검증이 0.9.12 부터 그 자리들을 함께 요구하므로, 채우지 않으면 모든 사례가 "그
        자리가 없어서" 죽는다 — 그러면 name 누락·status 오타를 실제로 잡는지 이 시험이 못 가린다.
        """
        out = json.loads(json.dumps(data))
        out.setdefault("tiebreaks", ["잠그는 것이 먼저다"])
        if isinstance(out.get("phases"), list):
            for p in out["phases"]:
                if isinstance(p, dict):
                    p.setdefault("exit_criteria", ["되돌리면 그 검사가 실패한다"])
                    p.setdefault("irreversible", False)
                    p.setdefault("non_goals", False)
        return out

    def test_schema_violations_stop_the_run(self):
        self.setup_loop()
        for label, data in self.SCHEMA_VIOLATIONS.items():
            with self.subTest(violation=label):
                self.setup_phases(self.with_spec_fields(data))
                r = self.run_block("b-budget")
                self.assertEqual(r.rc, 65, f"[{label}] 를 통과시켰다\n{r}")
                self.assertIn("phases.json 스키마 위반", r.err)

    def test_empty_or_nonarray_phases_named_by_the_spec_gate(self):
        """`.phases` 가 배열이 아니거나 비면 (1a) 스펙 검사가 먼저 잡고 이름을 댄다.

        `all(.phases[]; ...)` 는 빈 배열에서 **공허하게 참**이라, (1a)에 배열 조건이 없으면
        이 경우가 그 검사를 그냥 지나가 (1b)의 "스키마 위반" 한 줄로 떨어진다. 그러면 무엇이
        빠졌는지 이름으로 알려주려고 두 검사를 나눈 목적이 이 경우에만 죽는다. Step 1 의
        같은 검사에는 원래 배열 조건이 있었고 Step 2 사본에만 없던 것이라, 두 사본이 어긋난
        자리이기도 했다.
        """
        self.setup_loop()
        for label, data in (("비배열", {"phases": {}}), ("빈배열", {"phases": []})):
            with self.subTest(violation=label):
                self.setup_phases(self.with_spec_fields(data))
                r = self.run_block("b-budget")
                self.assertEqual(r.rc, 65, f"[{label}] 를 통과시켰다\n{r}")
                self.assertIn("착수 전 스펙 검사 자리가 없다", r.err, repr(r))
                self.assertIn("exit_criteria", r.err, "무엇이 빠졌는지 이름으로 안 나온다")

    # 착수 전 검사가 요구하는 자리가 빠지거나 정보가 없는 판 — 0.9.11 까지는 순회가 이걸 그대로 받았다.
    # 라벨 → (phases.json, 이름이 불려야 하는 자리 집합)
    SPEC_FIELD_VIOLATIONS = {
        "필수 자리 다 없음(0.9.11 형식)": (
            PHASES_2_LEGACY,
            {"exit_criteria", "irreversible", "tiebreaks", "non_goals"}),
        "non_goals 만 없음": (
            {"tiebreaks": PHASES_2["tiebreaks"],
             "phases": [{k: v for k, v in p.items() if k != "non_goals"}
                        for p in PHASES_2["phases"]]}, {"non_goals"}),
        # `true` 는 "좁히는데 어딘지 안 적음" 이다 — irreversible 과 같은 판정.
        "non_goals 가 true": (
            {"tiebreaks": PHASES_2["tiebreaks"],
             "phases": [{**p, "non_goals": True} for p in PHASES_2["phases"]]},
            {"non_goals"}),
        "tiebreaks 만 없음": (
            {k: v for k, v in PHASES_2.items() if k != "tiebreaks"}, {"tiebreaks"}),
        "exit_criteria 만 없음": (
            {"tiebreaks": PHASES_2["tiebreaks"],
             "phases": [{k: v for k, v in p.items() if k != "exit_criteria"}
                        for p in PHASES_2["phases"]]}, {"exit_criteria"}),
        "irreversible 만 없음": (
            {"tiebreaks": PHASES_2["tiebreaks"],
             "phases": [{k: v for k, v in p.items() if k != "irreversible"}
                        for p in PHASES_2["phases"]]}, {"irreversible"}),
        # `true` 는 "닿는데 어딘지 안 적음" 이다. 통과시키면 위임 오케스트레이터가 사람에게 올려야 할
        # 영역 이름 없이 그 자리에 선다 — 규칙이 문자열을 요구하는 이유가 그것이다.
        "irreversible 이 true": (
            {"tiebreaks": PHASES_2["tiebreaks"],
             "phases": [{**p, "irreversible": True} for p in PHASES_2["phases"]]},
            {"irreversible"}),
        # 공백만 든 문자열. length 는 문자 수라 이것을 통과시킨다 — 판정은 test("\\S") 여야 한다.
        "값이 공백문자뿐": (
            {"tiebreaks": ["   "],
             "phases": [{**p, "exit_criteria": ["  "], "irreversible": " ",
                         "non_goals": ["  "]}
                        for p in PHASES_2["phases"]]},
            {"exit_criteria", "irreversible", "tiebreaks", "non_goals"}),
    }

    def test_missing_spec_fields_also_stop_the_run(self):
        """순회 입구에도 같은 자리들이 걸린다 — 재개로 들어오는 경로에 우회로를 남기지 않는다.

        Step 1 의 검사는 사람 승인 앞에서 한 번 돌지만 재개는 Step 2 로 바로 들어온다. 여기가
        비어 있으면 그 자리들 없는 phases.json 이 재개 한 번으로 무인 순회에 올라탄다.

        **이름을 지목하는지도 함께 본다.** 이 자리에 오는 파일은 정의상 Step 1 을 안 거친 것이라
        (0.9.11 때 만들어져 진행 중이던 것, 또는 손편집), "스키마 위반" 한 줄만 받으면 사람이
        status 오타부터 찾게 된다.
        """
        self.setup_loop()
        for label, (data, expected) in self.SPEC_FIELD_VIOLATIONS.items():
            with self.subTest(violation=label):
                self.setup_phases(data)
                r = self.run_block("b-budget")
                self.assertEqual(r.rc, 65, f"[{label}] 를 순회에 태웠다\n{r}")
                self.assertIn("착수 전 스펙 검사 자리가 없다", r.err, repr(r))
                named = {f for f in TestSpecGate.FIELDS if f in r.err}
                self.assertEqual(named, expected,
                                 f"[{label}] 지목한 자리가 다르다 — 사람이 무엇을 채울지 못 읽는다\n{r}")

    def test_valid_schema_passes(self):
        """대조군 — 위 위반들이 검사 때문에 죽은 것이지, 블록이 늘 죽는 게 아니다."""
        self.setup_loop()
        self.setup_phases()
        self.assertEqual(self.run_block("b-budget").rc, 0)


# ── 3-1. 착수 전 스펙 검사 (Step 1) ────────────────────────────────────────

class TestSpecGate(BlockCase):
    """무인 완주는 사람 게이트가 아니라 스펙의 질로 갈린다 — 그 판정이 실제로 거부하는지 본다.

    이 검사가 무력해지는 방향은 둘이다. 없는 것을 통과시키거나(무인으로 돌다 결국 사람을 부른다),
    있는 것을 거부하거나(스킬 자체가 못 쓰게 된다). 그래서 위반 목록과 대조군을 함께 둔다.

    **0.9.12 에서 우회로를 없앴다.** 종전에는 이 검사가 위임 모드 전용이라 실패하면 직접 모드로
    돌면 그만이었다 — 검사 옆에 우회로가 있으면 그 검사는 권고다. 이제 실패는 시작 자체를 막고,
    같은 자리들을 순회 입구(`lb-budget`)도 요구한다.

    **여기가 잠그는 것은 착수 검사(`lb-specgate`) 쪽 두 방향뿐이다.** 순회 입구 쪽 두 방향은
    `TestLoopBuildSetup` 의 `test_missing_spec_fields_also_stop_the_run`(거부)과
    `test_valid_schema_passes`(통과)가 잠근다. 네 방향이 그 넷으로 이미 덮여, 두 블록을 한
    시험에서 연달아 돌리는 판을 따로 두면 같은 단언을 다시 재는 것이 된다.
    """

    # 라벨 → (phases.json, 이름이 불려야 하는 자리 집합).
    # **한 자리를 겨눈 판은 나머지 자리를 다 채워 둔다.** 안 채우면 그 판이 겨냥하지 않은 이름까지
    # 함께 불려, 겨눈 자리를 실제로 잡는지 가려지지 않는다. 자리가 늘 때마다 여기 리터럴에 한 줄씩
    # 더한다 — 채우는 함수를 따로 두면 호출자가 하나뿐인 우회가 된다.
    VIOLATIONS = {
        "exit_criteria 키 없음": (
            {"tiebreaks": ["t"],
             "phases": [{"name": "a", "status": "pending", "irreversible": False,
                         "non_goals": False,
                         "steps": [{"ac_cmd": "x", "status": "pending"}]}]},
            {"exit_criteria"}),
        "exit_criteria 빈 배열": (
            {"tiebreaks": ["t"],
             "phases": [{"name": "a", "status": "pending", "exit_criteria": [],
                         "irreversible": False, "non_goals": False,
                         "steps": [{"ac_cmd": "x", "status": "pending"}]}]},
            {"exit_criteria"}),
        "exit_criteria 빈 문자열 항목": (
            {"tiebreaks": ["t"],
             "phases": [{"name": "a", "status": "pending", "exit_criteria": [""],
                         "irreversible": False, "non_goals": False,
                         "steps": [{"ac_cmd": "x", "status": "pending"}]}]},
            {"exit_criteria"}),
        "phase 하나만 exit_criteria 누락": (
            {"tiebreaks": ["t"],
             "phases": [{"name": "a", "status": "pending", "exit_criteria": ["x 를 지우면 빨개진다"],
                         "irreversible": False, "non_goals": False,
                         "steps": [{"ac_cmd": "x", "status": "pending"}]},
                        {"name": "b", "status": "pending", "irreversible": False,
                         "non_goals": False,
                         "steps": [{"ac_cmd": "x", "status": "pending"}]}]},
            {"exit_criteria"}),
        "irreversible 키 없음": (
            {"tiebreaks": ["t"],
             "phases": [{"name": "a", "status": "pending", "exit_criteria": ["빨개진다"],
                         "non_goals": False,
                         "steps": [{"ac_cmd": "x", "status": "pending"}]}]},
            {"irreversible"}),
        "irreversible 빈 문자열": (
            {"tiebreaks": ["t"],
             "phases": [{"name": "a", "status": "pending", "exit_criteria": ["빨개진다"],
                         "irreversible": "", "non_goals": False,
                         "steps": [{"ac_cmd": "x", "status": "pending"}]}]},
            {"irreversible"}),
        "tiebreaks 키 없음": (
            {"phases": [{"name": "a", "status": "pending", "exit_criteria": ["빨개진다"],
                         "irreversible": False, "non_goals": False,
                         "steps": [{"ac_cmd": "x", "status": "pending"}]}]},
            {"tiebreaks"}),
        "tiebreaks 빈 배열": (
            {"tiebreaks": [],
             "phases": [{"name": "a", "status": "pending", "exit_criteria": ["빨개진다"],
                         "irreversible": False, "non_goals": False,
                         "steps": [{"ac_cmd": "x", "status": "pending"}]}]},
            {"tiebreaks"}),
        # `non_goals` 는 `irreversible` 과 같은 형태(`false` 또는 비지 않은 값)라 판정도 같아야
        # 한다. 다르면 사람이 두 자리에 다른 규칙을 외워야 한다. 네 판이 새 jq 의 서로 다른
        # 분기에 대응한다 — 존재·불리언 true 거부·배열 길이·`all(.phases[];...)` 한정자.
        "non_goals 키 없음": (
            {"tiebreaks": ["t"],
             "phases": [{"name": "a", "status": "pending", "exit_criteria": ["빨개진다"],
                         "irreversible": False,
                         "steps": [{"ac_cmd": "x", "status": "pending"}]}]},
            {"non_goals"}),
        "non_goals 가 true": (
            {"tiebreaks": ["t"],
             "phases": [{"name": "a", "status": "pending", "exit_criteria": ["빨개진다"],
                         "irreversible": False, "non_goals": True,
                         "steps": [{"ac_cmd": "x", "status": "pending"}]}]},
            {"non_goals"}),
        "non_goals 빈 배열": (
            {"tiebreaks": ["t"],
             "phases": [{"name": "a", "status": "pending", "exit_criteria": ["빨개진다"],
                         "irreversible": False, "non_goals": [],
                         "steps": [{"ac_cmd": "x", "status": "pending"}]}]},
            {"non_goals"}),
        "phase 하나만 non_goals 누락": (
            {"tiebreaks": ["t"],
             "phases": [{"name": "a", "status": "pending", "exit_criteria": ["빨개진다"],
                         "irreversible": False, "non_goals": ["수신 층"],
                         "steps": [{"ac_cmd": "x", "status": "pending"}]},
                        {"name": "b", "status": "pending", "exit_criteria": ["빨개진다"],
                         "irreversible": False,
                         "steps": [{"ac_cmd": "x", "status": "pending"}]}]},
            {"non_goals"}),
        # 값은 있는데 정보가 없는 판. 두 게이트가 같은 판정을 해야 한다(순회 입구 쪽은
        # TestLoopBuildSetup.SPEC_FIELD_VIOLATIONS 의 같은 이름 두 건).
        "irreversible 이 true": (
            {"tiebreaks": ["t"],
             "phases": [{"name": "a", "status": "pending", "exit_criteria": ["빨개진다"],
                         "irreversible": True, "non_goals": False,
                         "steps": [{"ac_cmd": "x", "status": "pending"}]}]},
            {"irreversible"}),
        "공백문자만": (
            {"tiebreaks": ["  "],
             "phases": [{"name": "a", "status": "pending", "exit_criteria": [" "],
                         "irreversible": "   ", "non_goals": ["  "],
                         "steps": [{"ac_cmd": "x", "status": "pending"}]}]},
            {"exit_criteria", "irreversible", "tiebreaks", "non_goals"}),
        # 옛 형식은 어느 자리도 안 채운 판이라 네 이름이 전부 불려야 한다.
        "필수 자리 다 없음(0.9.11 형식)": (
            PHASES_2_LEGACY,
            {"exit_criteria", "irreversible", "tiebreaks", "non_goals"}),
    }

    FIELDS = ("exit_criteria", "irreversible", "tiebreaks", "non_goals")

    def prepare(self, data: dict) -> None:
        self.setup_loop()
        self.setup_phases(data)

    def test_incomplete_spec_stops_the_start(self):
        for label, (data, expected) in self.VIOLATIONS.items():
            with self.subTest(violation=label):
                self.setUp()          # 사례마다 새 레포 사본 — 앞 사례의 params.env 가 안 섞이게
                self.prepare(data)
                r = self.run_block("b-specgate")
                self.assertEqual(r.rc, 65, f"[{label}] 를 시작 가능으로 통과시켰다\n{r}")
                self.assertIn("착수 전 스펙 검사 실패", r.err, repr(r))
                named = {f for f in self.FIELDS if f in r.err}
                self.assertEqual(named, expected,
                                 f"[{label}] 지목한 자리가 다르다 — 사람이 무엇을 더 적을지 못 읽는다\n{r}")

    def test_complete_spec_passes(self):
        """대조군 — 위 판들이 필수 자리의 부재로 죽은 것이지, 블록이 늘 죽는 게 아니다."""
        self.prepare(PHASES_2)
        r = self.run_block("b-specgate")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("착수 전 스펙 검사 통과", r.out, repr(r))

    def test_gate_without_pointer_fails_loud(self):
        """Step 0 없이 이 블록만 돌면 빈 PHASES 로 jq 가 돌아 '통과' 로 보일 자리다."""
        r = self.run_block("b-specgate")
        self.assertEqual(r.rc, 65, repr(r))
        self.assertIn("params.env 없음", r.err, repr(r))


# ── 4. phase 스코프 (진입·격리·done 갱신·재개) ──────────────────────────────

class TestPhaseScope(BlockCase):
    def prepare(self) -> None:
        self.setup_loop()
        self.setup_phases()
        self.run_block("b-budget")

    def test_phase_entry_scopes_state(self):
        self.prepare()
        (self.loop_dir / "gate.fail").write_text("2\n")
        r = self.enter_phase("foundation")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("phase 진입: foundation", r.out)
        self.assertFalse((self.loop_dir / "gate.fail").exists(),
                         "phase 진입이 게이트 실패 카운터를 리셋하지 않았다")
        # 회차 세기(brake)가 `wc -l < "$HIST"` 라, 파일이 없으면 첫 사이클에서 stderr 가 새고
        # ITER 이 빈 값이 된다. 진입이 빈 파일을 만들어 그 자리를 막는다.
        self.assertTrue((self.loop_dir / "history-foundation.jsonl").is_file(),
                        "phase 진입이 그 phase 의 history 파일을 만들지 않았다")
        self.assertEqual(self.param("PHASE"), "foundation")
        self.assertEqual(self.param("HIST"), str(self.loop_dir / "history-foundation.jsonl"))
        self.assertEqual(self.param("STATE"), str(self.loop_dir / "stall-foundation.json"))

    def test_fresh_shell_restores_phase_scope(self):
        """프레시 셸에서 프리앰블만 source 해도 phase 스코프가 복원돼야 한다."""
        self.prepare()
        self.enter_phase("foundation")
        r = self.run_block(
            "probe", body=PREAMBLE + 'echo "PHASE=$PHASE"\necho "HIST=$(basename "$HIST")"\n'
                                    'echo "STATE=$(basename "$STATE")"\n')
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("PHASE=foundation", r.out)
        self.assertIn("HIST=history-foundation.jsonl", r.out)
        self.assertIn("STATE=stall-foundation.json", r.out)

    def test_stall_state_is_per_phase(self):
        """앞 phase 의 정체 상태가 다음 phase 판정을 오염시키지 않는다."""
        self.prepare()
        self.enter_phase("foundation")
        state = self.loop_dir / "stall-foundation.json"
        feed = ('printf \'{"counts":{"CRITICAL":1,"MAJOR":0,"MINOR":0}}\' '
                f'| bash "{ENGINE}/stall.sh" --state "{state}" | jq -r .status')
        statuses = [self.sh(feed).out.strip() for _ in range(4)]
        self.assertEqual(statuses[0], "INIT", f"첫 사이클이 INIT 이 아니다: {statuses}")
        self.assertEqual(statuses[-1], "STALLED", f"같은 결과 4회에 STALLED 가 안 났다: {statuses}")
        self.assertEqual(json.loads(state.read_text())["no_progress"], 3)

        # phase 2 진입 — 새 stall 파일이라 INIT 부터 다시 센다.
        self.enter_phase("wiring")
        self.assertFalse((self.loop_dir / "stall-wiring.json").exists(),
                         "phase 2 상태 파일이 미리 있다 — 격리가 깨졌다")
        self.assertTrue(state.is_file(), "phase 1 상태 파일이 사라졌다")
        w = self.loop_dir / "stall-wiring.json"
        first = self.sh(
            'printf \'{"counts":{"CRITICAL":1,"MAJOR":0,"MINOR":0}}\' '
            f'| bash "{ENGINE}/stall.sh" --state "{w}" | jq -r .status').out.strip()
        self.assertEqual(first, "INIT", "phase 2 첫 사이클이 INIT 이 아니다")

    def test_stall_state_shared_reproduces_false_stall(self):
        """대조군 — 단일 파일을 공유시키면 phase 2 첫 사이클이 곧바로 STALLED 다.

        위 격리 시험이 실제로 무언가를 지키고 있다는 증거. 같은 입력, 상태 파일만 다르다.
        """
        self.prepare()
        self.enter_phase("foundation")
        shared = self.loop_dir / "stall-shared.json"
        feed = ('printf \'{"counts":{"CRITICAL":1,"MAJOR":0,"MINOR":0}}\' '
                f'| bash "{ENGINE}/stall.sh" --state "{shared}" | jq -r .status')
        for _ in range(4):
            last = self.sh(feed).out.strip()
        self.assertEqual(last, "STALLED")
        self.assertEqual(self.sh(feed).out.strip(), "STALLED",
                         "공유 상태에서 다음 phase 첫 사이클이 STALLED 로 안 뜬다 — 대조군이 무력하다")

    def test_done_update_and_verification(self):
        self.prepare()
        self.enter_phase("foundation")
        r = self.run_block("b-done")
        self.assertEqual(r.rc, 0, repr(r))
        phases = json.loads((self.loop_dir / "phases.json").read_text())
        self.assertEqual([p["status"] for p in phases["phases"]], ["done", "pending"])

    def test_done_update_on_unknown_phase_fails_loud(self):
        """jq 는 매칭 0건에도 exit 0 이라, 검증 줄이 없으면 조용한 no-op 이 된다."""
        self.prepare()
        self.enter_phase("nosuchphase")
        r = self.run_block("b-done")
        self.assertEqual(r.rc, 65, repr(r))
        self.assertIn("done 갱신 실패", r.err)

    def test_done_update_on_duplicate_names_fails_loud(self):
        self.prepare()
        dup = {"phases": [dict(PHASES_2["phases"][0]), dict(PHASES_2["phases"][0])]}
        (self.loop_dir / "phases.json").write_text(json.dumps(dup, ensure_ascii=False))
        self.enter_phase("foundation")
        r = self.run_block("b-done")
        self.assertEqual(r.rc, 65, repr(r))

    def test_resume_query_picks_first_unfinished_phase(self):
        self.prepare()
        self.enter_phase("foundation")
        self.run_block("b-done")
        r = self.sh(f'''jq -r '.phases[] | select(.status != "done") | .name' '''
                    f'"{self.loop_dir}/phases.json" | head -1')
        self.assertEqual(r.out.strip(), "wiring", repr(r))


# ── 5. 게이트 층 (큐·카운터·brake·빈 변경) ──────────────────────────────────

class TestGateLayer(BlockCase):
    def test_gate_pass_runs_build_then_test(self):
        self.setup_loop()
        log = self.scratch / "gate.log"
        r = self.run_block("b-gate", env=self.env(GATE_MODE="pass", GATE_LOG=str(log)))
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("게이트 BUILD 통과", r.out)
        self.assertIn("게이트 TEST 통과", r.out)
        self.assertEqual((self.loop_dir / "gate-queue.jsonl").read_text(), "",
                         "통과인데 큐가 비어있지 않다")

    def test_gate_failure_fills_queue_and_skips_test(self):
        self.setup_loop()
        log = self.scratch / "gate.log"
        r = self.run_block("b-gate", env=self.env(GATE_MODE="fail-build", GATE_LOG=str(log)))
        # 게이트 실패 경로의 종료코드는 1 이다 — 블록 마지막 줄 `[ "$TOTAL" -gt 20 ] && echo …` 가
        # 20건 이하일 때 거짓이라 그 값이 그대로 블록 rc 가 된다. 실패 자체가 정상 분기라 출력으로
        # 판단하면 되지만, 값이 바뀌면(예: || true 추가) 여기서 먼저 드러나게 박아 둔다.
        self.assertEqual(r.rc, 1, repr(r))
        self.assertIn("게이트 실패 — 항목 2 건", r.out, repr(r))
        items = [json.loads(ln) for ln in
                 (self.loop_dir / "gate-queue.jsonl").read_text().splitlines()]
        self.assertEqual(len(items), 2)
        self.assertEqual({i["kind"] for i in items}, {"compile-error"})
        self.assertEqual({Path(i["file"]).name for i in items}, {"Main.kt"})
        # 컴파일이 깨지면 테스트는 돌리지 않는다 — 사슬이 &&
        self.assertEqual(len(log.read_text().splitlines()), 1,
                         f"BUILD 실패인데 TEST 도 돌았다: {log.read_text()!r}")
        self.assertIn("assemble", log.read_text())

    def test_gate_queue_is_refilled_each_cycle(self):
        self.setup_loop()
        self.run_block("b-gate", env=self.env(GATE_MODE="fail-build"))
        self.run_block("b-gate", env=self.env(GATE_MODE="pass"))
        self.assertEqual((self.loop_dir / "gate-queue.jsonl").read_text(), "",
                         "통과 사이클이 앞 회차 항목을 지우지 않았다 — maker 가 고쳐진 오류를 쫓는다")

    def test_gate_fail_counter_increments_across_shells(self):
        self.setup_loop()
        first = self.run_block("b-gatefail")
        second = self.run_block("b-gatefail")
        self.assertEqual(first.out.strip(), "1", repr(first))
        self.assertEqual(second.out.strip(), "2",
                         f"카운터가 프레시 셸에서 리셋됐다 — brake 가 무력화된다\n{second}")

    def test_brake_fires_on_iteration_ceiling(self):
        self.setup_loop(MAX_ITER="2")
        self.setup_phases()
        self.run_block("b-budget")
        self.enter_phase("foundation")
        # 회차는 그 phase 의 history 줄 수로 센다 — phase 별 파일이라 앞 phase 가 쓴 회차가
        # 다음 phase 의 brake 를 미리 물지 않는다.
        (self.loop_dir / "history-foundation.jsonl").write_text('{"iteration":1}\n')
        (self.loop_dir / "gate.fail").write_text("1\n")
        r = self.run_block("b-gate", env=self.env(GATE_MODE="pass"))
        self.assertIn("brake 도달", r.err, repr(r))
        self.assertIn("완료 1 회 + 게이트 실패 1 회", r.out)

    def test_empty_change_set_is_not_a_pass(self):
        """베이스 오감지·빈 작업에서 finding 0 이 거짓 PASS 로 둔갑하는 것을 막는 경고."""
        self.setup_loop()
        # .gitignore 를 커밋해 origin/main 까지 올리면 diff 도 트리도 깨끗해진다.
        self.sh("git add -A && git commit -qm 'chore: gitignore' && "
                "git push -q origin HEAD:main && git fetch -q origin")
        r = self.run_block("b-gate", env=self.env(GATE_MODE="pass"))
        self.assertIn("점검 대상 변경 0건", r.err, repr(r))

    def test_change_set_present_is_quiet(self):
        """대조군 — 변경이 있으면 위 경고가 안 나온다."""
        self.setup_loop()
        self.sh("echo '// 변경' >> src/Main.kt")
        r = self.run_block("b-gate", env=self.env(GATE_MODE="pass"))
        self.assertNotIn("점검 대상 변경 0건", r.err, repr(r))


# ── 6. checker 회수 + 채점 ──────────────────────────────────────────────────

class TestCheckerAndScoring(BlockCase):
    FIXTURE = ENGINE / "fixtures" / "findings.example.json"
    LENSES = ("contract", "safety", "quality")
    CLEAN = '{"base":"origin/main","findings":[],"reviewed":["src/Main.kt"]}'

    def prepare(self) -> None:
        """실제 순회는 언제나 phase 안에서 돈다 — 상태가 phase 스코프라 진입이 전제다."""
        self.setup_loop()
        self.setup_phases()
        self.run_block("b-budget")
        self.enter_phase("foundation")

    def lens_path(self, lens: str) -> Path:
        return self.loop_dir / f"checker-foundation-{lens}.json"

    def write_lenses(self, *, findings_in: str | None = None, skip: str | None = None) -> None:
        """렌즈 셋의 결과 파일을 채운다. findings_in 렌즈만 fixture, 나머지는 깨끗한 결과.

        한 렌즈에만 finding 을 두는 이유는 병합 dedup 때문이다 — 같은 fixture 를 세 벌 넣으면
        (차원·종류·위치)가 같아 하나로 접혀, 무엇을 세고 있는지가 흐려진다.
        """
        for lens in self.LENSES:
            if lens == skip:
                continue
            if lens == findings_in:
                shutil.copy(self.FIXTURE, self.lens_path(lens))
            else:
                self.lens_path(lens).write_text(self.CLEAN)

    def test_lens_paths_are_deterministic_and_emptied(self):
        """렌즈마다 결정적 경로를 잡고 스핀 직전 비운다. 잔여가 남으면 그 축이 이번 사이클에
        안 돌았는데도 옛 결과가 채점돼, 미점검 phase 가 통과로 둔갑한다."""
        self.prepare()
        stale = self.lens_path("safety")
        stale.write_text('{"findings":[{"id":"stale"}]}')
        r = self.run_block("b-lens")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("checker 렌즈: contract safety quality", r.out, repr(r))
        self.assertIn("checker 공통 값: base=origin/main", r.out)
        self.assertIn("docs/CONVENTIONS.md", r.out, "컨벤션 문서 값이 창에 안 나왔다")
        # `non_goals` 도 같은 성질이다. 창에 안 나오면 오케스트레이터가 렌즈 프롬프트에 넣을
        # 값이 없고, 렌즈는 계약대로 `in_scope` 를 생략해 계측이 전부 미표시가 된다. 그러면
        # 착수 전 검사만 통과한 채 이 기능이 한 번도 안 도는 상태가 초록으로 남는다 —
        # 실제로 이 줄이 없을 때 그 echo 를 지워도 188건이 전부 통과했다.
        self.assertIn("이번 phase 의 non_goals: 수신 층 / 성능 튜닝", r.out,
                      "phase 의 non_goals 값이 창에 안 나왔다 — 프롬프트에 넣을 것이 없다")
        for lens in self.LENSES:
            self.assertIn(str(self.lens_path(lens)), r.out,
                          f"{lens} 렌즈 출력 경로가 창에 안 나왔다 — 프롬프트에 넣을 값이 없다")
        self.assertEqual(stale.read_text(), "",
                         "스핀 직전 비우기가 안 됐다 — 잔여가 거짓 통과를 가린다")

    def test_scoring_stops_when_a_lens_is_missing(self):
        """축 하나가 안 돌면 남은 둘로 채점하지 않는다. **병렬화가 만든 가장 큰 구멍이 여기다** —
        렌즈가 죽어도 남은 결과의 형식은 멀쩡해서, 개수를 안 세면 그 차원이 통과로 읽힌다."""
        self.prepare()
        self.write_lenses(findings_in="contract", skip="quality")
        r = self.run_block("b-score")
        self.assertEqual(r.rc, 65, repr(r))
        self.assertIn("병합 실패", r.err, repr(r))
        self.assertFalse((self.loop_dir / "history-foundation.jsonl").read_text(),
                         "실패했는데 history 에 회차가 쌓였다")

    def test_scoring_stops_when_a_lens_wrote_nothing(self):
        self.prepare()
        self.run_block("b-lens")   # 렌즈 파일 셋을 빈 파일로 만든다
        r = self.run_block("b-score")
        self.assertEqual(r.rc, 65, repr(r))
        self.assertFalse((self.loop_dir / "history-foundation.jsonl").read_text(),
                         "실패했는데 history 에 회차가 쌓였다")

    def test_scoring_appends_history_and_scored(self):
        self.prepare()
        self.write_lenses(findings_in="contract")
        r = self.run_block("b-score")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("사이클 1 → verdict=AWAIT_USER", r.out, repr(r))
        # 범위 계측이 사람 눈에 닿는 유일한 자리다. 이 줄이 없으면 `decide.sh` 가 세기만 하고
        # 아무도 안 읽는다. 픽스처 렌즈 출력에는 `in_scope` 가 없으므로 전부 미표시로 잡히고,
        # 그 상태가 "범위 밖이 없다" 가 아니라 "안 쟀다" 로 읽혀야 한다.
        self.assertIn("범위 밖(계측, 판정 무관)", r.out, "범위 계측 줄이 창에 안 나왔다")
        self.assertRegex(r.out, r"미표시=[1-9]",
                         "표시 없는 finding 이 미표시로 안 잡혔다 — 0 이면 쟀다는 뜻이 된다")
        hist = (self.loop_dir / "history-foundation.jsonl").read_text().splitlines()
        self.assertEqual(len(hist), 1)
        self.assertEqual(json.loads(hist[0])["iteration"], 1)
        scored = json.loads((self.loop_dir / "scored-foundation.json").read_text())
        self.assertTrue(all("severity" in f for f in scored["findings"]))
        # 병합이 렌즈 접두를 붙여야 id 가 전역 고유가 된다 — 안 붙이면 두 렌즈의 "c1" 이 같은
        # 이름이 되어 반복 표시와 maker 지시가 서로 다른 finding 을 같은 것으로 가리킨다.
        self.assertTrue(all(f["id"].startswith("contract-") for f in scored["findings"]),
                        f"렌즈 접두가 안 붙었다: {[f['id'] for f in scored['findings']]}")

    def test_all_lenses_clean_scores_as_pass(self):
        """대조군 — 셋 다 정상 '발견 없음' 이면 PASS 로 채점돼야 한다.

        깨끗함을 인정받으려면 `reviewed` 로 무엇을 봤는지 함께 내야 한다.
        """
        self.prepare()
        self.write_lenses()
        r = self.run_block("b-score")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("verdict=PASS", r.out)

    def test_clean_without_reviewed_stops_instead_of_passing(self):
        """`{"findings":[]}` 만으로는 통과가 아니다 — 안 본 것과 구분이 안 되기 때문이다.

        그리고 오케스트레이터가 그 exit 65 를 **삼키지 않아야** 한다. 전에는 SCORED 가 빈 문자열이
        된 채 흘러가 verdict 가 미정의가 되고, history 줄이 안 쌓여 회차 카운터까지 제자리였다.
        """
        self.prepare()
        for lens in self.LENSES:
            self.lens_path(lens).write_text('{"findings":[]}')
        r = self.run_block("b-score")
        self.assertNotEqual(r.rc, 0, repr(r))
        self.assertNotIn("verdict=", r.out)
        hist = self.loop_dir / "history-foundation.jsonl"
        self.assertFalse(hist.is_file() and hist.read_text().strip(),
                         "거부된 사이클이 history 에 줄을 남기면 안 된다")

    def test_lens_base_mismatch_stops(self):
        """렌즈마다 다른 diff 를 봤으면 합친 verdict 가 무엇에 대한 것인지 없다."""
        self.prepare()
        self.write_lenses(findings_in="contract")
        self.lens_path("quality").write_text(
            '{"base":"origin/develop","findings":[],"reviewed":["src/Main.kt"]}')
        r = self.run_block("b-score")
        self.assertEqual(r.rc, 65, repr(r))

    def test_scoring_writes_into_phase_scope(self):
        """phase 스코프를 채점 블록이 params.env 로 상속한다 — 앞 phase 와 섞이면 안 된다."""
        self.prepare()
        self.write_lenses(findings_in="safety")
        r = self.run_block("b-score")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertTrue((self.loop_dir / "history-foundation.jsonl").is_file(),
                        "phase 스코프 history 가 안 생겼다")
        self.assertFalse((self.loop_dir / "history.jsonl").exists(),
                         "phase 스코프인데 루트 history 에 썼다")


# ── 7. maker 입력 선택 ─────────────────────────────────────────────────────

class TestMakerInput(BlockCase):
    def test_gate_queue_wins_over_scored(self):
        self.setup_loop()
        (self.loop_dir / "scored.json").write_text('{"findings":[]}')
        self.run_block("b-gate", env=self.env(GATE_MODE="fail-build"))
        r = self.run_block("b-makerinput")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("maker 입력: 게이트 큐 2건", r.out, repr(r))

    def enter(self) -> None:
        self.setup_loop()
        self.setup_phases()
        self.run_block("b-budget")
        self.enter_phase("foundation")

    def test_scored_used_when_queue_empty(self):
        self.enter()
        (self.loop_dir / "scored-foundation.json").write_text('{"findings":[]}')
        self.run_block("b-gate", env=self.env(GATE_MODE="pass"))
        r = self.run_block("b-makerinput")
        self.assertIn(f"maker 입력: 채점 큐 {self.loop_dir}/scored-foundation.json",
                      r.out, repr(r))

    def test_repeat_table_lists_recurring_findings(self):
        """회차 간 유일한 기억 — 같은 kind@location 이 몇 회차째인지.

        집계 대상이 phase 별 history 라, 앞 phase 에서 반복된 finding 이 다음 phase 의 표에
        섞이지 않는다(섞이면 maker 가 이 phase 와 무관한 이력을 근거로 받는다).
        """
        self.enter()
        one = ('{"iteration":%d,"verdict":"RETRY","findings":'
               '[{"kind":"n-plus-1","location":"src/Main.kt:8"}]}')
        (self.loop_dir / "history-foundation.jsonl").write_text(
            (one % 1) + "\n" + (one % 2) + "\n")
        r = self.run_block("b-makerinput")
        self.assertIn("2회차째", r.out, repr(r))
        self.assertIn("n-plus-1@src/Main.kt:8", r.out)

    def test_repeat_table_quiet_on_first_cycle(self):
        self.setup_loop()
        r = self.run_block("b-makerinput")
        self.assertIn("반복 없음", r.out, repr(r))


# ── 8. 트리 변경 확인 (여덟 사례) ───────────────────────────────────────────

# (라벨, 트리 변형 셸, 정체 신호가 떠야 하나)
TREE_CASES = [
    ("1 첫 스냅숏",          "true",                                        False),
    ("2 무변경",             "true",                                        True),
    ("3 추적 파일 수정",      "echo '// a' >> src/Main.kt",                   False),
    ("4 같은 파일 재수정",     "echo '// b' >> src/Main.kt",                   False),
    ("5 미추적 파일 생성",     "echo 'x' > new.txt",                          False),
    ("6 미추적 파일 재수정",   "echo 'y' >> new.txt",                          False),
    ("7 git add 만",         "git add src/Main.kt",                         True),
    ("8 다시 무변경",         "true",                                        True),
]

STALL_MARK = "워킹 트리가 그대로다"

# 0.9.4 의 상태-기반 판정. 4·6 을 놓치고 7 을 오탐한다 — 대조군으로만 쓴다.
OLD_TREE_EXPR = '''\
NOW="$(git rev-parse HEAD):$(git status --porcelain | shasum | cut -d' ' -f1)"
PREV="$(cat "$LOOP_DIR/tree.snapshot" 2>/dev/null || echo none)"
printf '%s\\n' "$NOW" > "$LOOP_DIR/tree.snapshot"
if [ "$NOW" = "$PREV" ]; then echo "정체: 워킹 트리가 그대로다" >&2; fi
'''


class TestTreeSnapshot(BlockCase):
    def test_eight_mutations(self):
        self.setup_loop()
        for label, mutate, expect_stall in TREE_CASES:
            with self.subTest(case=label):
                self.sh(mutate)
                r = self.run_block("b-tree")
                self.assertEqual(r.rc, 0, repr(r))
                got = STALL_MARK in r.err
                self.assertEqual(got, expect_stall,
                                 f"[{label}] 정체 신호 기대 {expect_stall} / 실제 {got}\n{r}")

    def test_old_porcelain_expression_gets_three_cases_wrong(self):
        """대조군 — 위 여덟 사례가 실제로 판별력이 있다는 증거.

        상태만 보는 옛 판정은 4·6(같은 파일 재수정)을 '안 바뀠다' 로 놓치고 7(내용 변화 없는
        git add)을 '바뀠다' 로 오탐한다. 이 시험이 초록이면 여덟 사례가 그 셋을 가려낸다.
        """
        self.setup_loop()
        wrong = []
        for label, mutate, expect_stall in TREE_CASES:
            self.sh(mutate)
            r = self.run_block("old-tree", body=PREAMBLE + OLD_TREE_EXPR)
            self.assertEqual(r.rc, 0, repr(r))
            if (STALL_MARK in r.err) != expect_stall:
                wrong.append(label)
        self.assertEqual(wrong, ["4 같은 파일 재수정", "6 미추적 파일 재수정", "7 git add 만"],
                         f"옛 판정이 틀리는 사례 집합이 달라졌다: {wrong}")


# ── 9. 종료 정리 ───────────────────────────────────────────────────────────

# 프리앰블·가드가 없던 0.9.4 의 정리 블록. 빈 LOOP_DIR 로 아무것도 못 지우면서 rc 0 을 낸다.
OLD_CLEANUP = '''\
rm -rf "$LOOP_DIR"
rm -f "$PTR"
echo "loop: 런타임 상태 폐기 — $LOOP_DIR"
'''


class TestCleanup(BlockCase):
    def check_cleanup(self, block_id: str, label: str) -> None:
        self.setup_loop()
        loop_dir = self.loop_dir
        self.assertTrue(loop_dir.is_dir())
        r = self.run_block(block_id)
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("런타임 상태 폐기", r.out, repr(r))
        self.assertFalse(loop_dir.exists(), f"{label}: LOOP_DIR 가 남았다")
        self.assertFalse(self.pointer.exists(), f"{label}: 포인터가 남았다")
        # 재실행 안전 — 지울 게 없으면 그렇다고 말하고 rc 0
        again = self.run_block(block_id)
        self.assertEqual(again.rc, 0, repr(again))
        self.assertIn("지울 상태가 없다", again.err, repr(again))

    def test_build_cleanup(self):
        # 종전에는 loop-run Step 5-1 과 loop-build Step 3-1 이 각각 정리 블록을 갖고 있었고
        # 시험도 둘이었다. 스킬이 합쳐지며 블록이 하나가 되어(앵커도 하나) 검사도 하나다.
        self.check_cleanup("b-cleanup", "build Step 3-1")

    def test_old_cleanup_silently_deleted_nothing(self):
        """대조군 — 프리앰블 없던 판은 rc 0 을 내면서 상태를 그대로 남겼다.

        "정리했다" 는 출력까지 같았다. 그래서 정리 시험은 종료코드가 아니라 디렉터리 부재로 판정한다.
        """
        self.setup_loop()
        loop_dir = self.loop_dir
        r = self.run_block("old-cleanup", body=OLD_CLEANUP)
        self.assertEqual(r.rc, 0, "옛 블록이 비0 을 냈다면 애초에 조용한 실패가 아니었다")
        self.assertIn("런타임 상태 폐기", r.out)
        self.assertTrue(loop_dir.is_dir(), "옛 블록이 실제로 지웠다 — 대조군이 무력하다")
        self.assertTrue(self.pointer.is_file())


# ── 10. review ─────────────────────────────────────────────────────────────

class TestLoopReview(BlockCase):
    def review_findings_path(self) -> Path:
        r = self.sh('echo "${TMPDIR:-/tmp}/review-findings-$(basename "$PWD")-'
                    '$(git rev-parse --abbrev-ref HEAD | cksum | tr \' \' \'-\').json"')
        return Path(r.out.strip())

    def test_detect_prints_prompt_values(self):
        # 0.9.7 의 빈 diff 가드가 여기서도 돈다 — 점검 대상이 없으면 멈춘다. 감지 값 출력을 보려면
        # 실제로 볼 변경이 있어야 한다(리뷰는 회차가 없어 이 한 번이 전부라 더 치명적이다).
        (self.work / "Changed.kt").write_text("class Changed\n")
        r = self.run_block("v-detect")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("review 값: base=origin/main", r.out, repr(r))
        self.assertIn("docs/CONVENTIONS.md", r.out)
        self.assertIn("docs/ANTIPATTERNS.md", r.out)
        self.assertIn(str(ENGINE / "rubric.base.md"), r.out)

    def test_no_change_stops_review_instead_of_reporting_clean(self):
        """베이스가 어긋나 diff 가 통째로 비면 checker 는 깨끗하다고 답한다 — 그게 통과가 되면 안 된다.

        loop-run 에는 이 가드가 있었고 loop-review 에는 통째로 없었다.
        """
        r = self.run_block("v-detect")
        self.assertNotEqual(r.rc, 0, repr(r))
        self.assertIn("점검 대상 변경 0건", r.err)

    def test_score_rejection_stops_and_keeps_the_evidence(self):
        """채점이 거부하면 멈춰야 하고, 원인을 볼 findings 파일을 지우면 안 된다.

        loop-run 쪽은 잠갔는데 같은 결함의 형제인 여기가 안 잠겨 있었다 — 이 수정을 되돌려도
        52건이 전부 초록이었다(변이로 확인). 이 저장소가 이번 릴리스에 `test-vacuous` 라고
        이름 붙인 바로 그 결함을 스스로 낸 것이다.

        여기가 loop-run 보다 나쁜 이유가 하나 더 있다. 삼킨 뒤 `rm -f "$F"` 가 이어져
        조용한 통과가 아니라 **조용한 증거 인멸**이 된다.
        """
        (self.work / "Changed.kt").write_text("class Changed\n")
        f = self.review_findings_path()
        f.write_text('{"findings":[]}')
        r = self.run_block("v-score")
        self.assertNotEqual(r.rc, 0, repr(r))
        self.assertTrue(f.is_file(), "거부됐는데 findings 파일을 지우면 원인을 볼 수 없다")

    def test_findings_path_is_deterministic_and_emptied(self):
        expected = self.review_findings_path()
        expected.write_text('{"findings":[{"id":"stale"}]}')
        r = self.run_block("v-findings")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertTrue(expected.is_file(), f"결정적 경로에 파일이 안 생겼다: {expected}")
        self.assertEqual(expected.read_text(), "")

    def test_scoring_stops_on_empty_findings_file(self):
        self.run_block("v-findings")
        r = self.run_block("v-score")
        self.assertEqual(r.rc, 65, repr(r))
        self.assertIn("checker 가 findings 를", r.err)

    def test_scoring_consumes_and_removes_findings(self):
        f = self.review_findings_path()
        shutil.copy(ENGINE / "fixtures" / "findings.example.json", f)
        r = self.run_block("v-score")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertFalse(f.exists(), "채점 후 findings 파일이 남았다")


# ── 11. 엔진 경로 유도 대조군 ───────────────────────────────────────────────

# 0.9.8 까지의 엔진 유도. 시험 하네스가 `CLAUDE_PLUGIN_ROOT` 를 직접 주입해서 초록이었고,
class TestSpecLedger(BlockCase):
    """도출층의 두 블록 — 시작 조건 확인과 종료 조건 판정.

    이 스킬은 일의 대부분이 사람과의 왕복이라 기계가 맡는 자리가 둘뿐이다. 그래서 그 둘이
    무엇을 통과시키고 무엇을 막는지가 이 층의 계약 전부다. 특히 종료 판정은 "이만하면 됐다" 를
    모델이 말하지 못하게 하려고 존재하므로, 근거 없이 닫힌 항목을 실제로 거부하는지가 핵심이다.
    """

    def ledger(self, decisions: list[dict], *, spec_dir: Path | None = None) -> Path:
        d = spec_dir or (self.work / ".loop" / "spec" / "t")
        d.mkdir(parents=True, exist_ok=True)
        (d / "decisions.json").write_text(
            json.dumps({"round": 1, "decisions": decisions}, ensure_ascii=False))
        return d

    def exit_run(self, decisions: list[dict]) -> Run:
        d = self.ledger(decisions)
        return self.run_block("s-exit", env=self.env(SPEC_DIR=str(d)))

    # -- 시작 조건 -----------------------------------------------------------
    def test_setup_creates_empty_ledger(self) -> None:
        r = self.run_block("s-setup")
        self.assertEqual(0, r.rc, r.err)
        self.assertIn("spec 값:", r.out)
        led = list((self.work / ".loop" / "spec").glob("*/decisions.json"))
        self.assertEqual(1, len(led), f"원장이 하나 생겨야 한다: {r.out}")
        self.assertEqual([], json.loads(led[0].read_text())["decisions"])

    def test_setup_does_not_clobber_an_existing_ledger(self) -> None:
        """재시작해도 답한 것을 다시 묻지 않는다는 약속이 여기 걸려 있다.

        점검기를 못 불러 멈췄을 때 문서는 "세션을 다시 시작하고 다시 부르라" 고 말한다. 그
        재시작이 원장을 비우면 사람은 같은 질문에 두 번 답하게 되고, 그러면 우회로를 요구한다.
        """
        first = self.run_block("s-setup")
        self.assertEqual(0, first.rc, first.err)
        led = next((self.work / ".loop" / "spec").glob("*/decisions.json"))
        led.write_text(json.dumps({"round": 2, "decisions": [{"id": "g1"}]}, ensure_ascii=False))
        again = self.run_block("s-setup")
        self.assertEqual(0, again.rc, again.err)
        self.assertEqual([{"id": "g1"}], json.loads(led.read_text())["decisions"])

    def test_setup_stops_when_the_checker_definition_is_missing(self) -> None:
        """설치가 깨진 것과 세션 목록이 낡은 것은 고치는 방법이 다르다.

        이 스킬에는 대체 실행 경로가 없으므로, 점검기 정의가 없으면 도출 자체가 성립하지 않는다.
        여기서 미리 갈라 두지 않으면 사람이 Step 2 에서 죽은 뒤에야 원인을 찾기 시작한다.
        """
        body = BLOCKS["s-setup"].replace("/agents/loop-spec-checker.md",
                                         "/agents/does-not-exist.md")
        r = self.run_block("s-setup", body=body)
        self.assertEqual(65, r.rc, r.out)
        self.assertIn("점검기 정의가 없다", r.err)

    # -- 종료 조건 -----------------------------------------------------------
    def test_exit_passes_when_nothing_is_unresolved(self) -> None:
        r = self.exit_run([
            {"id": "g1", "disposition": "resolved-from-code", "evidence": "src/X.kt:3"},
            {"id": "g2", "disposition": "asked", "answer": "두 번째는 거부한다"},
            {"id": "g3", "disposition": "default", "answer": "20"},
            {"id": "g4", "disposition": "deferred", "note": "답이 오지 않았다"},
        ])
        self.assertEqual(0, r.rc, r.err)
        self.assertIn("미결 0 — 산출 단계로 간다", r.out)

    def test_exit_reports_counts_with_digits(self) -> None:
        """변수 뒤에 한글이 붙으면 셸이 그 한글까지 변수 이름으로 읽어 개수가 사라진다.

        실제로 그렇게 나갔던 자리다(zsh 는 빈 문자열, bash 는 깨진 바이트). 하필 개수가 필요한
        순간은 뭔가 잘못됐을 때라, 조용히 비어도 아무도 눈치채지 못한다.
        """
        r = self.exit_run([{"id": "g1", "disposition": "default", "answer": "20"}])
        self.assertEqual(0, r.rc, r.err)
        self.assertRegex(r.out, r"결정 1개")

    def test_exit_sends_you_back_when_something_is_open(self) -> None:
        r = self.exit_run([{"id": "g1", "disposition": "open"}])
        self.assertEqual(3, r.rc, r.out)
        self.assertIn("Step 2 로 돌아간다", r.err)

    def test_exit_treats_an_unanswered_question_as_unresolved(self) -> None:
        """`asked` 는 물었다는 뜻이지 답을 받았다는 뜻이 아니다."""
        r = self.exit_run([{"id": "g1", "disposition": "asked", "answer": "   "}])
        self.assertEqual(3, r.rc, r.out)

    def test_exit_rejects_a_decision_closed_without_evidence(self) -> None:
        """이 스킬이 막으려는 것 자체 — 지어낸 답이 근거 없이 원장에 앉는 자리다.

        종료코드가 3 이 아니라 65 인 것이 요점이다. 한 바퀴 더 돌아서 해결될 일이 아니라
        사람이 그 항목을 고쳐야 한다.
        """
        r = self.exit_run([{"id": "g1", "disposition": "resolved-from-code", "evidence": ""}])
        self.assertEqual(65, r.rc, r.out)
        self.assertIn("근거 없이 닫은 결정이 1개", r.err)

    def test_exit_rejects_a_disposition_outside_the_vocabulary(self) -> None:
        """오타로 만든 새 값은 다른 두 검사를 모두 지나간다 — select 가 아무것도 안 고르기 때문."""
        r = self.exit_run([{"id": "g1", "disposition": "resolved"}])
        self.assertEqual(65, r.rc, r.out)
        self.assertIn("어휘 밖", r.err)

    def test_exit_stops_when_the_ledger_is_missing(self) -> None:
        d = self.work / ".loop" / "spec" / "nope"
        d.mkdir(parents=True, exist_ok=True)
        r = self.run_block("s-exit", env=self.env(SPEC_DIR=str(d)))
        self.assertEqual(65, r.rc, r.out)
        self.assertIn("원장이 없다", r.err)


# 실제 Bash 도구 셸에는 그 변수가 없어 `ENG=/_loop-engine` 으로 돌았다 — 대조군으로만 쓴다.
OLD_ENGINE_DERIVATION = '''\
ENG="$CLAUDE_PLUGIN_ROOT/_loop-engine"
[ -f "$ENG/lib.sh" ] || { echo "loop: 채점 엔진을 못 찾았다 ($ENG)" >&2; exit 65; }
echo "엔진 찾음: $ENG"
'''


class TestControlGroups(BlockCase):
    """이 하네스가 실제로 무언가를 잡고 있다는 증거.

    검사가 아예 안 돈 것과 아무것도 못 찾은 것은 출력이 같다. 그래서 "잡혀야 하는 것" 을 일부러
    넣어 매번 확인한다. 여기 둘은 엔진 경로 유도 한 자리를 서로 다른 방향에서 잠근다.
    """

    def test_unsubstituted_placeholder_dies_loud(self):
        """자리표시자를 안 붙여 넣고 돌리면 그 자리에서 비0 으로 죽어야 한다.

        블록의 `[ -f "$ENG/lib.sh" ]` 가드가 이걸 보장한다. 가드를 빼면 빈 경로가 조용히 흘러가
        `loop_param` 이 빈 값을 내고 brake 가 무력화된다 — 그때 이 시험이 먼저 빨개진다.
        """
        targets = [bid for bid, body in BLOCKS.items() if SKILL_DIR_PLACEHOLDER in body]
        self.assertTrue(targets, "자리표시자를 쓰는 블록이 하나도 없다 — 문서가 바뀠다")
        for bid in targets:
            with self.subTest(block=bid):
                r = self.run_block(bid, keep_placeholder=True)
                self.assertNotEqual(r.rc, 0, f"{bid} 가 치환 없이도 통과했다\n{r}")
                # 문구는 "엔진을 못 찾았다" 까지만 요구한다. 실행층은 그 엔진으로 채점하지만
                # 도출층은 경로 감지에만 쓰므로 "채점 엔진" 이라 부르면 그 자리에서 거짓이 된다.
                # 이 시험이 잠그는 것은 메시지 문구가 아니라 **가드가 살아 있는지**다.
                self.assertIn("엔진을 못 찾았다", r.err, repr(r))

    def test_substituted_placeholder_finds_the_engine(self):
        """대조군의 대조군 — 붙여 넣으면 실제로 엔진을 찾는다(위 실패가 늘 죽는 블록 탓이 아니다)."""
        (self.work / "Changed.kt").write_text("class Changed\n")   # 빈 diff 가드를 통과할 변경
        r = self.run_block("v-detect")
        self.assertNotIn("채점 엔진을 못 찾았다", r.err, repr(r))
        self.assertIn(str(ENGINE / "rubric.base.md"), r.out, repr(r))

    def test_old_plugin_root_derivation_finds_nothing(self):
        """옛 표기는 이 셸에서 아무것도 못 찾는다 — 하네스가 그 변수를 주입하지 않기 때문이다.

        **이 시험이 `env()` 의 주입 삭제를 잠근다.** 누가 `CLAUDE_PLUGIN_ROOT` 주입을 되살리면
        옛 표기가 다시 도는 것처럼 보이면서 여기가 빨개진다. 주입이 있던 동안 실제 환경에서는
        안 도는 블록이 시험에서만 초록이었고, 그게 이 결함이 오래 산 이유다.
        """
        r = self.run_block("old-engine", body=OLD_ENGINE_DERIVATION)
        self.assertEqual(r.rc, 65, f"셸에 CLAUDE_PLUGIN_ROOT 가 있다 — 주입이 되살아났나\n{r}")
        self.assertIn("(/_loop-engine)", r.err, repr(r))


if __name__ == "__main__":
    unittest.main(verbosity=2)
