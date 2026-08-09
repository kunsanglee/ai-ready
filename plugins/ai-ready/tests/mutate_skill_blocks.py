"""test_skill_blocks.py 가 실제로 이를 가졌는지 확인하는 변이 시험.

통과한 시험이 충분한 시험은 아니다. 초록 50건은 "결함이 없다" 와 "결함을 볼 눈이 없다" 를
구별하지 못한다. 그래서 트리 사본의 SKILL.md 에 **0.9.5 에서 실제로 있었던 결함을 되넣고**
그 시험이 깨지는지 본다. 안 깨지면 그 시험은 장식이다.

변이마다 대조군을 함께 돈다 — 변이 없는 사본에서 같은 시험이 먼저 통과해야, 그 실패가 변이
때문이라고 말할 수 있다(늘 실패하는 시험은 아무것도 증명하지 않는다).

unittest 로 수집되지 않게 이름을 test_ 로 시작하지 않는다 — 이 스크립트는 문서를 일부러
깨뜨리므로 기본 시험 실행에 섞이면 안 된다. 직접 부른다:

    python3 tests/mutate_skill_blocks.py

exit 0 = 변이 전부 잡힘. 비0 = 살아남은 변이가 있다(하네스에 구멍).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TREE = Path(__file__).resolve().parents[1]
TEST = TREE / "tests" / "test_skill_blocks.py"

# 각 변이: (라벨, 대상 문서, 지울/바꿀 원문, 바꿀 내용, 깨져야 하는 시험, 왜 이 변이인가)
MUTATIONS = [
    (
        "근거 없이 닫은 결정을 통과",
        "skills/spec/SKILL.md",
        '[ "$UNGROUNDED" -eq 0 ] || { echo "spec: 근거 없이 닫은 결정이',
        '[ "$UNGROUNDED" -ge 0 ] || { echo "spec: 근거 없이 닫은 결정이',
        ["TestSpecLedger.test_exit_rejects_a_decision_closed_without_evidence"],
        "도출층의 존재 이유 — 지어낸 답이 근거 없이 원장에 앉는 것을 막는 유일한 자리다. "
        "이 가드가 죽으면 나머지 검사는 전부 통과해서 사람에게 아무 신호도 안 간다.",
    ),
    (
        "개수 출력에서 중괄호 제거",
        "skills/spec/SKILL.md",
        'echo "spec: 결정 ${TOTAL}개',
        'echo "spec: 결정 $TOTAL개',
        ["TestSpecLedger.test_exit_reports_counts_with_digits"],
        "변수 뒤에 한글이 붙으면 셸이 그 한글까지 이름으로 읽어 개수가 사라진다. "
        "실제로 그렇게 나갔던 자리이고, 하필 개수가 필요한 순간은 뭔가 잘못됐을 때다.",
    ),
    (
        "정리 블록의 재유도·가드 제거",
        "skills/build/SKILL.md",
        '''LOOP_DIR="$(cat "$PTR" 2>/dev/null)"
# 폐기는 lesson 종합(또는 사람이 생략 결정) 후에만. 지울 것이 없으면 그렇다고 말하고 끝낸다(재실행 안전).
[ -n "$LOOP_DIR" ] || { echo "build: 포인터 없음 — 지울 상태가 없다(이미 폐기됐거나 Step 0 미실행)" >&2; exit 0; }
''',
        "",
        ["TestCleanup.test_build_cleanup"],
        "0.9.4 결함 1 — 빈 LOOP_DIR 로 rm 이 아무것도 못 지우면서 종료코드 0 과 '폐기했다' 출력을 냈다.",
    ),
    (
        "순회 진입 블록의 재유도 제거",
        "skills/build/SKILL.md",
        '''  || { echo "build: params.env 없음 — Step 0 미실행/폐기됨" >&2; exit 65; }
set -a; . "$LOOP_DIR/params.env"; set +a

# (1a) 착수 전 스펙 검사 셋 재확인''',
        "\n# (1a) 착수 전 스펙 검사 셋 재확인",
        ["TestBlockInventory.test_state_blocks_rederive_or_are_prepended",
         "TestLoopBuildSetup.test_budget_block_without_pointer_fails_loud"],
        "0.9.4 결함 2 — Step 0 과 같은 셸이라 가정하면 PHASES·BUDGET_MIN 이 빈 값으로 돈다.",
    ),
    (
        "트리 확인을 상태 기반으로 회귀",
        "skills/build/SKILL.md",
        '''NOW="$(git rev-parse HEAD):$( { git diff HEAD; git ls-files --others --exclude-standard -z'''
        ''' | xargs -0 shasum 2>/dev/null; } | shasum | cut -d' ' -f1)"''',
        '''NOW="$(git rev-parse HEAD):$(git status --porcelain | shasum | cut -d' ' -f1)"''',
        ["TestTreeSnapshot.test_eight_mutations"],
        "0.9.4 결함 3 — porcelain 은 상태만 내므로 같은 파일 재수정을 놓치고 git add 를 오탐했다.",
    ),
    (
        "렌즈 병합을 건너뛰고 한 축만 채점",
        "skills/build/SKILL.md",
        '''bash "$ENG/merge_findings.sh" --expect 3 \\
  "contract=$LOOP_DIR/checker-$PHASE-contract.json" \\
  "safety=$LOOP_DIR/checker-$PHASE-safety.json" \\
  "quality=$LOOP_DIR/checker-$PHASE-quality.json" > "$F" || {
  echo "build: 렌즈 결과 병합 실패 — 위 메시지가 어느 축인지 말한다. 그 축만 다시 띄우거나 멈춰 사람 호출" >&2
  exit 65
}''',
        '''cp "$LOOP_DIR/checker-$PHASE-contract.json" "$F"''',
        ["TestCheckerAndScoring.test_scoring_stops_when_a_lens_is_missing"],
        "병렬화가 만든 구멍 — 개수를 안 세면 축 하나가 안 돌아도 남은 결과가 멀쩡해 보여 통과한다.",
    ),
    (
        "시험되지 않는 새 블록 추가",
        "skills/build/SKILL.md",
        "## Non-Goals",
        "## 새 절\n\n```bash\necho '아무도 시험하지 않는 블록'\n```\n\n## Non-Goals",
        ["TestBlockInventory.test_block_counts"],
        "블록이 늘면 하네스가 모르는 실행 경로가 생긴다 — 개수 고정이 그 신호다.",
    ),
]


def _run(tree: Path, tests: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TEST), *tests], cwd=str(tree),
        capture_output=True, text=True,
        env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"),
             "LANG": os.environ.get("LANG", "en_US.UTF-8"),
             "AI_READY_TREE": str(tree)})


def _copy(dest_parent: Path) -> Path:
    tree = dest_parent / "ai-ready"
    shutil.copytree(TREE, tree, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return tree


def main() -> int:
    survived = []
    for label, rel, old, new, tests, why in MUTATIONS:
        tmp = Path(tempfile.mkdtemp(prefix="ai-ready-mutate-"))
        try:
            # 대조군 — 변이 없는 사본에서 그 시험이 먼저 통과해야 한다.
            base = _copy(tmp / "base")
            (tmp / "base").mkdir(exist_ok=True)
            control = _run(base, tests)
            if control.returncode != 0:
                print(f"무효  {label}\n      대조군이 이미 실패한다 — 변이와 무관하게 깨지는 시험이다.")
                print((control.stdout + control.stderr)[-800:])
                survived.append(label)
                continue

            tree = _copy(tmp / "mut")
            target = tree / rel
            text = target.read_text(encoding="utf-8")
            if old not in text:
                print(f"무효  {label}\n      변이 대상 원문을 문서에서 못 찾았다 — 문서가 바뀠으면 이 변이를 고친다.")
                survived.append(label)
                continue
            target.write_text(text.replace(old, new, 1), encoding="utf-8")

            got = _run(tree, tests)
            if got.returncode == 0:
                print(f"놓침  {label}\n      {why}\n      변이해도 시험이 통과했다 — 하네스에 구멍이 있다.")
                survived.append(label)
            else:
                first = next((ln.strip() for ln in (got.stdout + got.stderr).splitlines()
                              if "AssertionError" in ln), "(비0 종료)")
                print(f"잡음  {label}\n      {first[:160]}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print("────────────────────────")
    if survived:
        print(f"살아남은 변이 {len(survived)}건: {', '.join(survived)}")
        return 1
    print(f"변이 {len(MUTATIONS)}건 전부 잡힘 — 하네스가 이를 가졌다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
