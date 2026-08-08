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

범위는 claude 트리의 `loop-run`·`loop-build`·`loop-review` 셋이다. codex 트리의 같은 스킬은
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
# 들여쓴 펜스도 받는다 — loop-run Step 1 의 게이트 실패 카운터는 불릿 안에 2칸 들여쓰여 있고,
# 들여쓰기를 무시하는 정규식은 그 블록을 조용히 빠뜨린다(그게 여덟 번째 블록이다).
_FENCE = re.compile(r"^(?P<indent>[ \t]*)```bash\n(?P<body>.*?)^(?P=indent)```", re.S | re.M)

# 문서에 있어야 하는 bash 블록 수. 늘거나 줄면 fail-loud — 새 블록은 이 하네스에 항목을 더할
# 신호이고, 준 블록은 앵커가 죽었다는 신호다. "16개 통과" 가 "16개를 봤다" 를 뜻하게 하는 장치.
EXPECTED_BLOCK_COUNTS = {"loop-run": 8, "loop-build": 5, "loop-review": 3}

# 블록 식별은 순번이 아니라 내용 앵커로 한다 — 블록이 하나 끼어들어도 나머지 항목이 밀리지 않는다.
# 앵커는 그 블록의 기능 핵심 한 줄이라, 그 줄이 사라지면 시험이 먼저 멈춘다.
ANCHORS = {
    "lr-setup":      ("loop-run", 'LOOP_DIR="$PROJECT_ROOT/.loop/run/$TICKET"'),
    "lr-gate":       ("loop-run", "run_gate BUILD"),
    "lr-gatefail":   ("loop-run", 'G="$LOOP_DIR/gate.fail"'),
    "lr-checker":    ("loop-run", "checker 프롬프트 값:"),
    "lr-score":      ("loop-run", 'SCORED=$(bash "$ENG/score.sh"'),
    "lr-cleanup":    ("loop-run", 'PTR="$PROJECT_ROOT/.loop/run/.active-$BR"'),
    "lr-makerinput": ("loop-run", "MAKER_INPUT="),
    "lr-tree":       ("loop-run", "tree.snapshot"),
    "lb-setup":      ("loop-build", "printf 'PHASES=%q"),
    "lb-budget":     ("loop-build", "BUDGET_MIN_PHASE"),
    "lb-phase":      ("loop-build", 'PHASE="<이 phase 의 name>"'),
    "lb-done":       ("loop-build", '.status = "done"'),
    "lb-cleanup":    ("loop-build", 'PTR="$PROJECT_ROOT/.loop/run/.active-$BR"'),
    "lv-detect":     ("loop-review", "review 값:"),
    "lv-findings":   ("loop-review", ': > "$F"'),
    "lv-score":      ("loop-review", 'rm -f "$F"'),
}

# 문서가 "재유도 프리앰블 뒤에" 라고 지시하는 블록. 프리앰블은 lr-gate 에서 뽑아 붙인다.
NEEDS_PREAMBLE = {"lr-makerinput", "lr-tree"}

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

_pre_lines = BLOCKS["lr-gate"].splitlines(keepends=True)
_pre_idx = [i for i, ln in enumerate(_pre_lines) if _PREAMBLE_END in ln]
if len(_pre_idx) != 1:
    raise AssertionError("lr-gate 에서 재유도 프리앰블 끝(set -a … params.env)을 못 찾음")
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

PHASES_2 = {
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
            "CLAUDE_PLUGIN_ROOT": str(TREE),
            # 실제 /tmp 를 오염시키지 않는다 — loop-review 블록이 TMPDIR 하위에 findings 를 쓴다.
            "TMPDIR": str(self.scratch / "tmpdir"),
        }
        (self.scratch / "tmpdir").mkdir(exist_ok=True)
        base.update({k: v for k, v in extra.items() if v is not None})
        return base

    def run_block(self, block_id: str, *, env: dict[str, str] | None = None,
                  subst: dict[str, str] | None = None, body: str | None = None) -> Run:
        text = BLOCKS[block_id] if body is None else body
        if block_id in NEEDS_PREAMBLE and body is None:
            text = PREAMBLE + text
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
        r = self.run_block("lr-setup", env=self.env(**extra))
        self.assertEqual(r.rc, 0, f"lr-setup 실패\n{r}")
        return r

    def setup_phases(self, data: dict | None = None) -> None:
        self.run_block("lb-setup")
        (self.loop_dir / "phases.json").write_text(
            json.dumps(data if data is not None else PHASES_2, ensure_ascii=False))

    def enter_phase(self, name: str) -> Run:
        return self.run_block("lb-phase", subst={'"<이 phase 의 name>"': f'"{name}"'})


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


# ── 2. loop-run Step 0 (셋업) ───────────────────────────────────────────────

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
        self.assertEqual((self.loop_dir / "history.jsonl").read_text(), "")

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

    def test_design_ref_missing_falls_back_to_brief(self):
        r = self.setup_loop()
        self.assertIn("작업 지시 파일 없음", r.err, repr(r))
        self.assertEqual(self.param("LOOP_DESIGN_REF"), str(self.loop_dir / "brief.md"))

    def test_design_ref_nonexistent_path_stops(self):
        r = self.run_block("lr-setup", env=self.env(LOOP_DESIGN_REF="/nope/spec.md"))
        self.assertEqual(r.rc, 3, repr(r))
        self.assertIn("작업 지시 파일", r.err)
        self.assertFalse(self.pointer.exists(), "exit 3 인데 포인터가 남았다")

    def test_design_ref_existing_path_used(self):
        spec = self.work / "docs" / "design.md"
        r = self.setup_loop(LOOP_DESIGN_REF=str(spec))
        self.assertNotIn("작업 지시 파일 없음", r.err, repr(r))
        self.assertEqual(self.param("LOOP_DESIGN_REF"), str(spec))

    def test_works_without_claude_project_dir(self):
        """plugin 밖 직접 실행 — PROJECT_ROOT 가 git 루트 폴백으로 잡혀야 한다."""
        env = self.env()
        env.pop("CLAUDE_PROJECT_DIR")
        r = self.run_block("lr-setup", env=env)
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("ticket=CCE-999", r.out)


# ── 3. loop-build Step 0 추가 + phases.json 검증 ────────────────────────────

class TestLoopBuildSetup(BlockCase):
    def test_phases_path_persisted(self):
        self.setup_loop()
        r = self.run_block("lb-setup")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertEqual(self.param("PHASES"), str(self.loop_dir / "phases.json"))

    def test_setup_without_pointer_fails_loud(self):
        """포인터가 없으면 멈춘다. 재유도 없이 돌던 판(0.9.4)은 PHASES 가 '/phases.json' 이 됐다."""
        r = self.run_block("lb-setup")
        self.assertEqual(r.rc, 65, repr(r))
        self.assertIn("params.env 없음", r.err)

    def test_budget_scales_by_phase_count(self):
        self.setup_loop()
        per_phase = int(self.param("BUDGET_MIN"))
        self.setup_phases()
        r = self.run_block("lb-budget")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn(f"{per_phase * 2}분 (phase 당 {per_phase} × 2개)", r.out, repr(r))
        self.assertEqual(self.param("BUDGET_MIN"), str(per_phase * 2))
        self.assertEqual(self.param("BUDGET_MIN_PHASE"), str(per_phase))

    def test_budget_recompute_is_idempotent(self):
        """재개로 이 블록이 다시 돌아도 재곱하지 않는다 — 480분이 나오면 회귀다."""
        self.setup_loop()
        per_phase = int(self.param("BUDGET_MIN"))
        self.setup_phases()
        self.run_block("lb-budget")
        r = self.run_block("lb-budget")
        self.assertIn(f"{per_phase * 2}분 (phase 당 {per_phase} × 2개)", r.out, repr(r))
        self.assertEqual(self.param("BUDGET_MIN"), str(per_phase * 2))

    # phases.json 스키마 위반 — 무인 순회 직전 fail-loud 로 걸러야 하는 것들.
    SCHEMA_VIOLATIONS = {
        "phases 비배열": {"phases": {}},
        "phases 빈배열": {"phases": []},
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

    def test_schema_violations_stop_the_run(self):
        self.setup_loop()
        for label, data in self.SCHEMA_VIOLATIONS.items():
            with self.subTest(violation=label):
                self.setup_phases(data)
                r = self.run_block("lb-budget")
                self.assertEqual(r.rc, 65, f"[{label}] 를 통과시켰다\n{r}")
                self.assertIn("phases.json 스키마 위반", r.err)

    def test_valid_schema_passes(self):
        """대조군 — 위 위반 열 건이 스키마 검사 때문에 죽은 것이지, 블록이 늘 죽는 게 아니다."""
        self.setup_loop()
        self.setup_phases()
        self.assertEqual(self.run_block("lb-budget").rc, 0)


# ── 4. phase 스코프 (진입·격리·done 갱신·재개) ──────────────────────────────

class TestPhaseScope(BlockCase):
    def prepare(self) -> None:
        self.setup_loop()
        self.setup_phases()
        self.run_block("lb-budget")

    def test_phase_entry_scopes_state(self):
        self.prepare()
        (self.loop_dir / "gate.fail").write_text("2\n")
        r = self.enter_phase("foundation")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("phase 진입: foundation", r.out)
        self.assertIn("docs/CONVENTIONS.md", r.out, "checker 프롬프트 값이 창에 안 나왔다")
        self.assertFalse((self.loop_dir / "gate.fail").exists(),
                         "phase 진입이 게이트 실패 카운터를 리셋하지 않았다")
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
        r = self.run_block("lb-done")
        self.assertEqual(r.rc, 0, repr(r))
        phases = json.loads((self.loop_dir / "phases.json").read_text())
        self.assertEqual([p["status"] for p in phases["phases"]], ["done", "pending"])

    def test_done_update_on_unknown_phase_fails_loud(self):
        """jq 는 매칭 0건에도 exit 0 이라, 검증 줄이 없으면 조용한 no-op 이 된다."""
        self.prepare()
        self.enter_phase("nosuchphase")
        r = self.run_block("lb-done")
        self.assertEqual(r.rc, 65, repr(r))
        self.assertIn("done 갱신 실패", r.err)

    def test_done_update_on_duplicate_names_fails_loud(self):
        self.prepare()
        dup = {"phases": [dict(PHASES_2["phases"][0]), dict(PHASES_2["phases"][0])]}
        (self.loop_dir / "phases.json").write_text(json.dumps(dup, ensure_ascii=False))
        self.enter_phase("foundation")
        r = self.run_block("lb-done")
        self.assertEqual(r.rc, 65, repr(r))

    def test_resume_query_picks_first_unfinished_phase(self):
        self.prepare()
        self.enter_phase("foundation")
        self.run_block("lb-done")
        r = self.sh(f'''jq -r '.phases[] | select(.status != "done") | .name' '''
                    f'"{self.loop_dir}/phases.json" | head -1')
        self.assertEqual(r.out.strip(), "wiring", repr(r))


# ── 5. 게이트 층 (큐·카운터·brake·빈 변경) ──────────────────────────────────

class TestGateLayer(BlockCase):
    def test_gate_pass_runs_build_then_test(self):
        self.setup_loop()
        log = self.scratch / "gate.log"
        r = self.run_block("lr-gate", env=self.env(GATE_MODE="pass", GATE_LOG=str(log)))
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("게이트 BUILD 통과", r.out)
        self.assertIn("게이트 TEST 통과", r.out)
        self.assertEqual((self.loop_dir / "gate-queue.jsonl").read_text(), "",
                         "통과인데 큐가 비어있지 않다")

    def test_gate_failure_fills_queue_and_skips_test(self):
        self.setup_loop()
        log = self.scratch / "gate.log"
        r = self.run_block("lr-gate", env=self.env(GATE_MODE="fail-build", GATE_LOG=str(log)))
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
        self.run_block("lr-gate", env=self.env(GATE_MODE="fail-build"))
        self.run_block("lr-gate", env=self.env(GATE_MODE="pass"))
        self.assertEqual((self.loop_dir / "gate-queue.jsonl").read_text(), "",
                         "통과 사이클이 앞 회차 항목을 지우지 않았다 — maker 가 고쳐진 오류를 쫓는다")

    def test_gate_fail_counter_increments_across_shells(self):
        self.setup_loop()
        first = self.run_block("lr-gatefail")
        second = self.run_block("lr-gatefail")
        self.assertEqual(first.out.strip(), "1", repr(first))
        self.assertEqual(second.out.strip(), "2",
                         f"카운터가 프레시 셸에서 리셋됐다 — brake 가 무력화된다\n{second}")

    def test_brake_fires_on_iteration_ceiling(self):
        self.setup_loop(MAX_ITER="2")
        (self.loop_dir / "history.jsonl").write_text('{"iteration":1}\n')
        (self.loop_dir / "gate.fail").write_text("1\n")
        r = self.run_block("lr-gate", env=self.env(GATE_MODE="pass"))
        self.assertIn("brake 도달", r.err, repr(r))
        self.assertIn("완료 1 회 + 게이트 실패 1 회", r.out)

    def test_empty_change_set_is_not_a_pass(self):
        """베이스 오감지·빈 작업에서 finding 0 이 거짓 PASS 로 둔갑하는 것을 막는 경고."""
        self.setup_loop()
        # .gitignore 를 커밋해 origin/main 까지 올리면 diff 도 트리도 깨끗해진다.
        self.sh("git add -A && git commit -qm 'chore: gitignore' && "
                "git push -q origin HEAD:main && git fetch -q origin")
        r = self.run_block("lr-gate", env=self.env(GATE_MODE="pass"))
        self.assertIn("점검 대상 변경 0건", r.err, repr(r))

    def test_change_set_present_is_quiet(self):
        """대조군 — 변경이 있으면 위 경고가 안 나온다."""
        self.setup_loop()
        self.sh("echo '// 변경' >> src/Main.kt")
        r = self.run_block("lr-gate", env=self.env(GATE_MODE="pass"))
        self.assertNotIn("점검 대상 변경 0건", r.err, repr(r))


# ── 6. checker 회수 + 채점 ──────────────────────────────────────────────────

class TestCheckerAndScoring(BlockCase):
    FIXTURE = ENGINE / "fixtures" / "findings.example.json"

    def test_checker_findings_path_is_deterministic_and_emptied(self):
        self.setup_loop()
        f = self.loop_dir / "checker-findings.json"
        f.write_text('{"findings":[{"id":"stale"}]}')
        r = self.run_block("lr-checker")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("checker 프롬프트 값: base=origin/main", r.out)
        self.assertIn(str(f), r.out, "findings 경로가 창에 안 나왔다 — 프롬프트에 넣을 값이 없다")
        self.assertEqual(f.read_text(), "", "스핀 직전 비우기가 안 됐다 — 잔여가 거짓 통과를 가린다")

    def test_scoring_stops_when_checker_wrote_nothing(self):
        self.setup_loop()
        self.run_block("lr-checker")  # $F 를 빈 파일로 만든다
        r = self.run_block("lr-score")
        self.assertEqual(r.rc, 65, repr(r))
        self.assertIn("checker 가 findings 를", r.err)
        self.assertEqual((self.loop_dir / "history.jsonl").read_text(), "",
                         "실패했는데 history 에 회차가 쌓였다")

    def test_scoring_appends_history_and_scored(self):
        self.setup_loop()
        shutil.copy(self.FIXTURE, self.loop_dir / "checker-findings.json")
        r = self.run_block("lr-score")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("사이클 1 → verdict=AWAIT_USER", r.out, repr(r))
        hist = (self.loop_dir / "history.jsonl").read_text().splitlines()
        self.assertEqual(len(hist), 1)
        self.assertEqual(json.loads(hist[0])["iteration"], 1)
        scored = json.loads((self.loop_dir / "scored.json").read_text())
        self.assertTrue(all("severity" in f for f in scored["findings"]))

    def test_empty_findings_array_scores_as_pass(self):
        """대조군 — 정상 '발견 없음' 은 -s 가드를 통과해 PASS 로 채점돼야 한다.

        0.9.7 부터 깨끗함을 인정받으려면 `reviewed` 로 무엇을 봤는지 함께 내야 한다.
        """
        self.setup_loop()
        (self.loop_dir / "checker-findings.json").write_text(
            '{"findings":[],"reviewed":["src/A.kt"]}')
        r = self.run_block("lr-score")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("verdict=PASS", r.out)

    def test_clean_without_reviewed_stops_instead_of_passing(self):
        """`{"findings":[]}` 만으로는 통과가 아니다 — 안 본 것과 구분이 안 되기 때문이다.

        그리고 오케스트레이터가 그 exit 65 를 **삼키지 않아야** 한다. 전에는 SCORED 가 빈 문자열이
        된 채 흘러가 verdict 가 미정의가 되고, history 줄이 안 쌓여 회차 카운터까지 제자리였다.
        """
        self.setup_loop()
        (self.loop_dir / "checker-findings.json").write_text('{"findings":[]}')
        r = self.run_block("lr-score")
        self.assertNotEqual(r.rc, 0, repr(r))
        self.assertNotIn("verdict=", r.out)
        hist = self.loop_dir / "history.jsonl"
        self.assertFalse(hist.is_file() and hist.read_text().strip(),
                         "거부된 사이클이 history 에 줄을 남기면 안 된다")

    def test_scoring_writes_into_phase_scope(self):
        """loop-build 의 phase 스코프를 loop-run Step 3 이 params.env 로 상속한다."""
        self.setup_loop()
        self.setup_phases()
        self.run_block("lb-budget")
        self.enter_phase("foundation")
        shutil.copy(self.FIXTURE, self.loop_dir / "checker-findings.json")
        r = self.run_block("lr-score")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertTrue((self.loop_dir / "history-foundation.jsonl").is_file(),
                        "phase 스코프 history 가 안 생겼다")
        self.assertFalse((self.loop_dir / "history.jsonl").read_text(),
                         "phase 진입 후에도 루트 history 에 썼다")


# ── 7. maker 입력 선택 ─────────────────────────────────────────────────────

class TestMakerInput(BlockCase):
    def test_gate_queue_wins_over_scored(self):
        self.setup_loop()
        (self.loop_dir / "scored.json").write_text('{"findings":[]}')
        self.run_block("lr-gate", env=self.env(GATE_MODE="fail-build"))
        r = self.run_block("lr-makerinput")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("maker 입력: 게이트 큐 2건", r.out, repr(r))

    def test_scored_used_when_queue_empty(self):
        self.setup_loop()
        (self.loop_dir / "scored.json").write_text('{"findings":[]}')
        self.run_block("lr-gate", env=self.env(GATE_MODE="pass"))
        r = self.run_block("lr-makerinput")
        self.assertIn(f"maker 입력: 채점 큐 {self.loop_dir}/scored.json", r.out, repr(r))

    def test_repeat_table_lists_recurring_findings(self):
        """회차 간 유일한 기억 — 같은 kind@location 이 몇 회차째인지."""
        self.setup_loop()
        one = ('{"iteration":%d,"verdict":"RETRY","findings":'
               '[{"kind":"n-plus-1","location":"src/Main.kt:8"}]}')
        (self.loop_dir / "history.jsonl").write_text((one % 1) + "\n" + (one % 2) + "\n")
        r = self.run_block("lr-makerinput")
        self.assertIn("2회차째", r.out, repr(r))
        self.assertIn("n-plus-1@src/Main.kt:8", r.out)

    def test_repeat_table_quiet_on_first_cycle(self):
        self.setup_loop()
        r = self.run_block("lr-makerinput")
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
                r = self.run_block("lr-tree")
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

    def test_loop_run_cleanup(self):
        self.check_cleanup("lr-cleanup", "loop-run Step 5-1")

    def test_loop_build_cleanup(self):
        self.check_cleanup("lb-cleanup", "loop-build Step 3-1")

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


# ── 10. loop-review ────────────────────────────────────────────────────────

class TestLoopReview(BlockCase):
    def review_findings_path(self) -> Path:
        r = self.sh('echo "${TMPDIR:-/tmp}/loop-review-findings-$(basename "$PWD")-'
                    '$(git rev-parse --abbrev-ref HEAD | cksum | tr \' \' \'-\').json"')
        return Path(r.out.strip())

    def test_detect_prints_prompt_values(self):
        # 0.9.7 의 빈 diff 가드가 여기서도 돈다 — 점검 대상이 없으면 멈춘다. 감지 값 출력을 보려면
        # 실제로 볼 변경이 있어야 한다(리뷰는 회차가 없어 이 한 번이 전부라 더 치명적이다).
        (self.work / "Changed.kt").write_text("class Changed\n")
        r = self.run_block("lv-detect")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertIn("review 값: base=origin/main", r.out, repr(r))
        self.assertIn("docs/CONVENTIONS.md", r.out)
        self.assertIn("docs/ANTIPATTERNS.md", r.out)
        self.assertIn(str(ENGINE / "rubric.base.md"), r.out)

    def test_no_change_stops_review_instead_of_reporting_clean(self):
        """베이스가 어긋나 diff 가 통째로 비면 checker 는 깨끗하다고 답한다 — 그게 통과가 되면 안 된다.

        loop-run 에는 이 가드가 있었고 loop-review 에는 통째로 없었다.
        """
        r = self.run_block("lv-detect")
        self.assertNotEqual(r.rc, 0, repr(r))
        self.assertIn("점검 대상 변경 0건", r.err)

    def test_findings_path_is_deterministic_and_emptied(self):
        expected = self.review_findings_path()
        expected.write_text('{"findings":[{"id":"stale"}]}')
        r = self.run_block("lv-findings")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertTrue(expected.is_file(), f"결정적 경로에 파일이 안 생겼다: {expected}")
        self.assertEqual(expected.read_text(), "")

    def test_scoring_stops_on_empty_findings_file(self):
        self.run_block("lv-findings")
        r = self.run_block("lv-score")
        self.assertEqual(r.rc, 65, repr(r))
        self.assertIn("checker 가 findings 를", r.err)

    def test_scoring_consumes_and_removes_findings(self):
        f = self.review_findings_path()
        shutil.copy(ENGINE / "fixtures" / "findings.example.json", f)
        r = self.run_block("lv-score")
        self.assertEqual(r.rc, 0, repr(r))
        self.assertFalse(f.exists(), "채점 후 findings 파일이 남았다")


if __name__ == "__main__":
    unittest.main(verbosity=2)
