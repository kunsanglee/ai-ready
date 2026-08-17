#!/usr/bin/env python3
"""
Extract anti-pattern seed from git history.

Analyzes commits matching fix/hotfix/revert patterns over the last N days,
groups them by file, and produces an ANTIPATTERNS.md draft. Also scans the
working tree for TODO/FIXME/HACK markers as a complementary signal.

The output is a *draft* — review and prune before adopting.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# 동일 디렉토리의 모듈 import — ai-ready 의 standard layout
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from managed_doc import guard_overwrite, add_force_arg  # noqa: E402

EXCLUDE_DIRS = {
    ".git", "node_modules", "build", "dist", "target", ".gradle", ".idea",
    "out", "bin", "vendor", ".venv", "venv", "__pycache__", ".next", ".turbo",
    ".pytest_cache", ".mypy_cache",
    "worktrees",  # git worktree(.claude/worktrees) = repo 전체 복사본 — 통째 중복 수집 방지
    ".ai-ready",  # 자기 산출물 자기참조 차단
}

CODE_EXTS = {
    ".kt", ".java", ".scala", ".groovy",
    ".ts", ".tsx", ".js", ".jsx", ".mjs",
    ".py", ".rs", ".go", ".rb", ".php", ".cs", ".swift",
    ".sql", ".kts", ".gradle",
}

# L-1 fix: 한국어 커밋 메시지 지원
FIX_PREFIX = re.compile(
    r"^(fix|hotfix|revert|chore\(fix\)|bugfix|버그|핫픽스|롤백|되돌림)[\(\s:]",
    re.IGNORECASE,
)
REVERT_PATTERN = re.compile(r"^(revert|롤백|되돌림)[\s:]", re.IGNORECASE)
MARKER_PATTERN = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b\s*:?\s*(.{0,160})", re.IGNORECASE)

MIN_OCCURRENCES = 3  # file must appear in this many fix commits to count

# T-11: 클러스터링 키워드 추출 — 반복되는 commit 메시지 키워드를 안티패턴 후보로
_KEYWORD_RE = re.compile(r"[A-Za-z][A-Za-z]{3,}|[가-힣]{2,}")
_STOPWORDS_EN = {
    "the", "this", "that", "with", "without", "from", "into", "for",
    "fix", "fixes", "fixed", "fixing", "bug", "bugs", "issue", "issues",
    "error", "errors", "feat", "feature", "chore", "refactor", "test", "tests",
    "wip", "merge", "merged", "branch", "main", "master", "rev", "revert",
    "update", "updates", "updated", "remove", "removed", "removes",
}
_STOPWORDS_KO = {
    "수정", "버그", "오류", "이슈", "에러", "추가", "삭제", "변경", "처리",
    "관련", "기능", "작업", "내용", "부분", "방식", "문제", "이전", "현재",
    "동작", "원인", "임시", "최근", "롤백", "되돌림", "핫픽스",
}
_MIN_KEYWORD_CLUSTER_SIZE = 3

# scaffold.py 와 같은 명명. 3 은 이 스크립트에서 이미 덮어쓰기 가드가 쓰고 있고
# SKILL.md 도 그 값으로 문서화해서, git 실패는 다음 번호를 쓴다.
EXIT_OK = 0
EXIT_NOT_A_DIR = 2         # --target 이 디렉토리가 아니다
EXIT_GUARD_REFUSED = 3     # 사람이 인수한 문서라 덮지 않는다
EXIT_GIT_UNAVAILABLE = 4   # 대상이 git 저장소가 아니거나 git 을 실행하지 못했다


def run_git(target: Path, args: list[str], timeout: int = 60) -> tuple[bool, str]:
    """(성공 여부, stdout). 실패를 빈 문자열로 삼키면 히스토리가 없는 것과 구분되지 않는다."""
    try:
        result = subprocess.run(
            ["git", "-C", str(target), *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        # OSError = FileNotFoundError(git 부재) + PermissionError 등, SubprocessError = TimeoutExpired 등.
        # gen_index 의 git 래퍼와 동일 폭으로 통일(PermissionError 미처리 크래시 차단).
        return False, ""
    if result.returncode != 0:
        return False, ""
    return True, result.stdout


SUBJECT_DELIM = "§§§"  # H-4 fix: subject에 들어갈 가능성이 거의 없는 unique delimiter


def parse_fix_commits(target: Path, days: int) -> list[dict] | None:
    """fix류 커밋의 subject와 변경 파일 목록을 반환. git log 를 못 읽으면 None.

    커밋이 하나도 없는 저장소에서 `git log` 는 exit 128 로 끝난다. 그건 오류가 아니라
    정당한 "히스토리 없음" 이라 빈 목록으로 계속 간다.

    H-4 fix: `|` 대신 unique delimiter(`§§§`)를 사용해 subject에 `|`가 있어도 안전.
    """
    ok, out = run_git(
        target,
        ["log", f"--since={days}.days.ago",
         f"--pretty=format:%H{SUBJECT_DELIM}%s", "--name-only"],
    )
    if not ok:
        listed, head = run_git(target, ["rev-list", "-n", "1", "--all"])
        if listed and not head.strip():
            return []
        return None
    commits = []
    current = None
    for line in out.splitlines():
        if not line.strip():
            if current and current["files"]:
                commits.append(current)
            current = None
            continue
        if SUBJECT_DELIM in line and current is None:
            sha, _, subject = line.partition(SUBJECT_DELIM)
            if FIX_PREFIX.match(subject) or REVERT_PATTERN.match(subject):
                current = {"sha": sha.strip(), "subject": subject.strip(), "files": []}
            else:
                current = None
        elif current is not None:
            current["files"].append(line.strip())
    if current and current["files"]:
        commits.append(current)
    return commits


def find_markers(target: Path, max_per_file: int = 3, max_total: int = 80) -> list[dict]:
    """Scan working tree for TODO/FIXME/HACK markers."""
    found = []
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        for f in sorted(filenames):  # 정렬 순회로 max_total 컷이 안정적 — 재실행 시 동일 출력(멱등)
            ext = Path(f).suffix
            if ext not in CODE_EXTS:
                continue
            full = Path(dirpath) / f
            try:
                with full.open("r", encoding="utf-8", errors="replace") as fh:
                    file_hits = []
                    for line_no, line in enumerate(fh, start=1):
                        m = MARKER_PATTERN.search(line)
                        if m and not _is_likely_function_name(line, m):
                            file_hits.append({
                                "path": str(full.relative_to(target)),
                                "line": line_no,
                                "marker": m.group(1).upper(),
                                "text": m.group(2).strip(),
                            })
                            if len(file_hits) >= max_per_file:
                                break
                    found.extend(file_hits)
            except OSError:
                continue
            if len(found) >= max_total:
                return found
    return found


def _is_likely_function_name(line: str, m: re.Match) -> bool:
    """Skip TODO/FIXME if it's part of a method/var name like `todoList` rather than a comment marker."""
    snippet = line[max(0, m.start() - 1):m.start()]
    return bool(snippet) and snippet[-1].isalnum()


def group_files_by_module(files: list[str], modules: set[str]) -> dict:
    """L-4 fix: 미사용 target 매개변수 제거. 가장 긴 일치 모듈에 파일을 귀속."""
    grouped = defaultdict(list)
    sorted_modules = sorted(modules, key=len, reverse=True)
    for f in files:
        match = "(root)"
        for m in sorted_modules:
            if f == m or f.startswith(m + "/"):
                match = m
                break
        grouped[match].append(f)
    return grouped


def cluster_keywords(commits: list[dict]) -> list[tuple[str, int, list[dict]]]:
    """T-11: commit subject 에서 키워드 빈도 집계.

    한국어/영어 단어를 추출, stopword 제거, N회 이상 반복되는 키워드를 (word, count, commits) 로.
    같은 commit 안에서 같은 키워드를 두 번 카운트하지 않음.
    """
    word_counts = Counter()
    word_to_commits = defaultdict(list)
    for c in commits:
        words = _KEYWORD_RE.findall(c["subject"])
        seen = set()
        for w in words:
            wl = w.lower()
            if wl in _STOPWORDS_EN or wl in _STOPWORDS_KO:
                continue
            if wl in seen:
                continue
            seen.add(wl)
            word_counts[wl] += 1
            word_to_commits[wl].append(c)
    clusters = [(w, n, word_to_commits[w]) for w, n in word_counts.items()
                if n >= _MIN_KEYWORD_CLUSTER_SIZE]
    clusters.sort(key=lambda x: x[1], reverse=True)
    return clusters


def detect_modules(target: Path) -> set[str]:
    """Lightweight module detection via build manifests."""
    out = set()
    BUILD_MANIFESTS = {
        "build.gradle.kts", "build.gradle", "pom.xml",
        "package.json", "Cargo.toml", "go.mod", "pyproject.toml", "setup.py",
    }
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        for f in filenames:
            if f in BUILD_MANIFESTS:
                rel = os.path.relpath(dirpath, target)
                if rel == ".":
                    continue
                out.add(rel.replace("\\", "/"))
                break
    return out


# --- Render ---------------------------------------------------------------

def render(commits: list[dict], markers: list[dict], modules: set[str], days: int) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    lines = []
    lines.append(f"# ANTIPATTERNS.md (초안 — {today} 생성)")
    lines.append("")
    # 자동 생성 서명. 덮어쓰기 가드가 이 줄을 보고 "ai-ready 산출물이라 다시 써도 된다" 를
    # 판정한다. 없으면 두 번째 감사가 자기가 만든 씨앗에 막혀 exit 3 으로 죽는다.
    lines.append(f"_자동 생성: {today} · `ai-ready:apply` (extract_antipatterns.py) — "
                 f"이 줄을 지우면 이후 실행이 이 파일을 덮지 않습니다._")
    lines.append("")
    lines.append(f"> 최근 {days}일 git 히스토리에서 추출한 시드입니다. **아래 각 항목은 후보**이며 확정된 안티패턴이 아닙니다. 검토·편집·정제한 뒤 채택하세요.")
    lines.append("")

    # 1. 키워드 클러스터 (T-11: 새 섹션) — 반복되는 commit 메시지 키워드를 안티패턴 후보로
    clusters = cluster_keywords(commits)
    lines.append("## 1. 반복 키워드 클러스터")
    lines.append("")
    if not clusters:
        lines.append(f"_{_MIN_KEYWORD_CLUSTER_SIZE}회 이상 반복되는 키워드 없음._")
    else:
        lines.append(f"커밋 메시지에 **{_MIN_KEYWORD_CLUSTER_SIZE}회 이상** 등장한 키워드 — 같은 종류의 실수가 반복될 가능성을 시사합니다.")
        lines.append("")
        for word, count, sample_commits in clusters[:10]:
            lines.append(f"### `{word}` — {count}회 반복")
            for c in sample_commits[:5]:
                lines.append(f"- `{c['sha'][:7]}` {c['subject']}")
            lines.append("")
            lines.append(f"  > **검토 포인트**: `{word}` 관련 변경이 {count}회 반복됐습니다. 같은 클래스의 결함이라면 "
                         f"안티패턴 1건으로 정리하세요 (`절대 금지 — X. 이유 — Y. 대신 — Z` 형식).")
            lines.append("")

    # 2. 반복 수정 위치 (파일 단위)
    file_counts = Counter()
    file_to_commits = defaultdict(list)
    for c in commits:
        for f in c["files"]:
            file_counts[f] += 1
            file_to_commits[f].append(c)
    recurring = [(f, n) for f, n in file_counts.items() if n >= MIN_OCCURRENCES]
    recurring.sort(key=lambda x: x[1], reverse=True)

    lines.append("## 2. 반복 수정 위치 (파일 단위)")
    lines.append("")
    if not recurring:
        lines.append("_3회 이상 fix류 커밋에 등장한 파일이 없습니다. 저장소가 건강하거나, 커밋 메시지가 모호하거나, 룩백 기간이 너무 짧습니다._")
    else:
        lines.append(f"**{MIN_OCCURRENCES}회 이상** fix/revert 커밋에 등장한 파일 — 안티패턴이나 숨은 복잡도를 품고 있을 가능성이 높습니다.")
        lines.append("")
        for f, n in recurring[:25]:
            lines.append(f"### `{f}` — fix 커밋 {n}회")
            sample = file_to_commits[f][:5]
            for c in sample:
                lines.append(f"- `{c['sha'][:7]}` {c['subject']}")
            lines.append("")
            lines.append(f"  > **검토 포인트**: 이 파일은 {days}일 동안 {n}번 수정됐습니다. 위 커밋 메시지에서 공통 패턴을 찾아 "
                         f"`절대 금지 — X. 이유 — Y. 대신 — Z` 형식의 안티패턴 1건으로 정리하세요.")
            lines.append("")

    # 3. Revert 커밋
    reverts = [c for c in commits if REVERT_PATTERN.match(c["subject"])]
    lines.append("## 3. 최근 Revert 커밋")
    lines.append("")
    if not reverts:
        lines.append("_룩백 기간 내 revert 커밋이 없습니다._")
    else:
        for c in reverts[:15]:
            lines.append(f"- `{c['sha'][:7]}` — {c['subject']}")
            for f in c["files"][:3]:
                lines.append(f"  - `{f}`")
    lines.append("")

    # 4. 모듈 핫스팟
    if modules:
        lines.append("## 4. 모듈 핫스팟")
        lines.append("")
        all_files = [f for c in commits for f in c["files"]]
        grouped = group_files_by_module(all_files, modules)
        ranked = sorted(grouped.items(), key=lambda kv: len(kv[1]), reverse=True)
        for mod, files in ranked[:10]:
            unique_files = len(set(files))
            total_changes = len(files)
            lines.append(f"- **{mod}** — fix 관련 변경 {total_changes}건, 고유 파일 {unique_files}개")
        lines.append("")

    # 5. 코드 마커
    lines.append("## 5. 소스 내 TODO / FIXME / HACK 마커")
    lines.append("")
    if not markers:
        lines.append("_마커 없음._")
    else:
        by_marker = defaultdict(list)
        for m in markers:
            by_marker[m["marker"]].append(m)
        for marker_type in ("FIXME", "HACK", "XXX", "TODO"):
            items = by_marker.get(marker_type, [])
            if not items:
                continue
            lines.append(f"### {marker_type} ({len(items)}건)")
            lines.append("")
            for m in items[:20]:
                snippet = m["text"][:120].replace("|", "│")
                lines.append(f"- `{m['path']}:{m['line']}` — {snippet}")
            if len(items) > 20:
                lines.append(f"- … 외 {len(items) - 20}건")
            lines.append("")

    # 6. 활용 가이드
    lines.append("## 6. 이 초안을 실제 ANTIPATTERNS.md로 정리하는 법")
    lines.append("")
    lines.append(textwrap_dedent("""\
        반복 수정 위치마다 다음 형식의 한 줄 항목을 작성하세요:

        > **절대 금지**: \\<잘못된 행동>. **이유**: \\<관찰된 실패 양상>. **대신**: \\<올바른 행동>.

        그런 다음 모듈이나 주제별로 그룹화합니다. 양보다 질 — 고품질 10~30개를 목표로 합니다.
        정제 후 이 파일을 저장소 루트로 옮기고 루트 CLAUDE.md에서 참조하도록 하세요.
    """).rstrip())
    return "\n".join(lines)


def textwrap_dedent(s: str) -> str:
    import textwrap
    return textwrap.dedent(s)


# --- Main -----------------------------------------------------------------

def run(target: Path, out_path: Path, days: int) -> int:
    # 산출물이 "최근 N일 git 히스토리에서 추출한 시드" 라고 말하므로, git 을 한 번도
    # 실행하지 못한 채로는 쓰지 않는다. 조용히 빈 문서를 내면 커밋이 없는 저장소와
    # 구분되지 않는다. scaffold.py 가 어댑터 미매칭을 비 0 으로 알리는 것과 같은 원칙.
    inside_work_tree, _ = run_git(target, ["rev-parse", "--is-inside-work-tree"])
    if not inside_work_tree:
        print(f"오류: git 히스토리를 읽을 수 없습니다: {target}\n"
              f"      `git -C <target> rev-parse --is-inside-work-tree` 가 실패했습니다 "
              f"(git 저장소가 아니거나 git 을 실행할 수 없음).",
              file=sys.stderr)
        return EXIT_GIT_UNAVAILABLE

    commits = parse_fix_commits(target, days)
    if commits is None:
        print(f"오류: git log 를 읽지 못했습니다: {target}\n"
              f"      대상은 git 저장소인데 `git log --since={days}.days.ago` 가 실패했습니다 "
              f"(타임아웃이거나 git 오류).",
              file=sys.stderr)
        return EXIT_GIT_UNAVAILABLE

    markers = find_markers(target)
    modules = detect_modules(target)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(commits, markers, modules, days), encoding="utf-8")
    print(f"분석 완료: fix류 커밋 {len(commits)}개, 코드 마커 {len(markers)}개, 모듈 {len(modules)}개")
    print(f"생성: {out_path}")
    return EXIT_OK


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--out", required=True, help="ANTIPATTERNS.md 출력 경로")
    ap.add_argument("--days", type=int, default=180)
    add_force_arg(ap)
    args = ap.parse_args()
    target = Path(args.target).resolve()
    out_path = Path(args.out).resolve()
    if not target.is_dir():
        print(f"오류: 대상이 디렉토리가 아님: {target}", file=sys.stderr)
        sys.exit(EXIT_NOT_A_DIR)
    # 사람이 인수한 문서는 덮지 않는다. 이 스크립트가 유독 이 가드가 필요한 이유는,
    # 산출물이 **초안이고 사람이 골라 옮기는 것**이 설계이기 때문이다. 관례상 `--out` 은
    # `.ai-ready/scaffolds/` 를 가리키지만 그것은 관례일 뿐이라, 누가 `docs/ANTIPATTERNS.md`
    # 를 넘기면 손으로 추린 항목이 git 히스토리 덤프로 조용히 덮인다.
    if not guard_overwrite(out_path, args.force):
        sys.exit(EXIT_GUARD_REFUSED)
    sys.exit(run(target, out_path, args.days))


if __name__ == "__main__":
    main()
