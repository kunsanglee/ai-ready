#!/usr/bin/env python3
"""모듈 문서 초안을 만든다 — 원본 `AGENTS.md` 와, 그것을 `@AGENTS.md` 한 줄로 가져오는 `CLAUDE.md`.

대상 모듈은 stacks.logical_modules 가 정한다(audit.py 와 같은 답). 모듈이 많으면 최근 변경이 잦은
모듈부터 --top 개만 고른다. 이미 사람이 관리하는 문서(자동 생성 서명이 없는 AGENTS.md, 또는 가져오는 줄
하나가 아닌 CLAUDE.md)가 있거나 둘 중 하나가 심볼릭 링크인(옛 구조) 모듈은 후보에서 뺀다. --modules 로 직접
고른 모듈이 그렇다면 exit 3 이다. 제자리에 쓸 때(--out 이 대상 저장소) 만들 파일이 git 에서 무시되면
아무것도 쓰지 않고 exit 6 이다. 셋 다 --force 로만 넘긴다.

초안의 절: 이 모듈이 하는 일 / 경계 / 변경 방법 / 강제할 수 없는 규칙 / 강제되는 규칙(포인터만).
파일 수·줄 수·변경 횟수 같은 숫자는 적지 않는다 — 문서에 박힌 숫자는 다음 커밋부터 틀린다.

  python3 scaffold.py --target <repo> --out <repo>                  # 제자리에 쓴다
  python3 scaffold.py --target <repo> --out <repo>/.ai-ready/drafts # 초안 폴더에 쓴다
  python3 scaffold.py --target <repo> --out <repo> --dry-run        # 쓸 파일만 보여 준다
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# 논리 모듈 기준점은 스택마다 다르다. 그 답을 여기 두지 않고 어댑터에 묻는다 — 종전에는
# 이 파일과 audit.py 가 각자 JVM 으로만 하드코딩해 두 벌로 갈라져 있었다.
import managed_doc
import stacks

# 모듈 목록·제외 디렉토리·코드 확장자는 audit.py 와 같은 답을 쓰도록 stacks.py 한 곳에 둔다.
EXCLUDE_DIRS = stacks.EXCLUDE_DIRS
CODE_EXTS = stacks.CODE_EXTS

# 종료코드. 0 이 아닌 값을 쓰는 이유는 "안 만들어졌다" 를 호출한 쪽이 셀 수 있게 하기
# 위해서다. 안내문은 사람만 읽고 스크립트는 못 읽는다.
EXIT_OK = 0
EXIT_REFUSED = 3       # managed_doc: 사람이 관리하는 문서라 덮어쓰지 않았다 (--force 로만)
EXIT_NO_PACKAGES = 4   # 기준점은 찾았는데 그 아래에 코드가 없다
EXIT_NO_ADAPTER = 5    # 등록된 스택 어댑터 중 맞는 것이 없다
EXIT_IGNORED = 6       # 만들 파일이 git 에서 무시된다 — 써도 커밋되지 않는다 (--force 로만)


def walk(target: Path):
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        yield Path(dirpath), dirnames, filenames


def git_changed_paths(target: Path, days: int = 90) -> list[str]:
    """최근 N일 커밋에서 바뀐 파일 경로 목록. 모듈을 고르는 순서에만 쓰고 문서에는 적지 않는다."""
    try:
        result = subprocess.run(
            ["git", "-C", str(target), "log", f"--since={days}.days.ago", "--name-only", "--pretty=format:"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        # OSError = git 부재·권한 오류, SubprocessError = 시간 초과. git 이 없으면 변경 이력 없이 고른다.
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def attribute_to_modules(paths: list[str], modules: list[Path]) -> dict[str, int]:
    """H-1 fix: 각 파일을 가장 긴 일치 prefix를 갖는 모듈에 정확히 1번 귀속.

    형제 모듈끼리 commit count를 나눠 갖지 않도록 longest-prefix 매칭.
    """
    counter: dict[str, int] = {}
    # 긴 경로 먼저 매칭하도록 정렬
    sorted_modules = sorted((str(m) for m in modules if m != Path(".")),
                            key=len, reverse=True)
    for p in paths:
        for m in sorted_modules:
            if p == m or p.startswith(m + "/"):
                counter[m] = counter.get(m, 0) + 1
                break
    return counter


def file_counts_attributed(target: Path, modules: list[Path]) -> dict[str, int]:
    """H-2 fix: 각 소스 파일을 가장 긴 일치 모듈 prefix에 누적.

    `foo` 모듈의 코드가 `foo/src/main/kotlin/...` 에 있어도 `foo`로 카운트되도록.
    """
    counter: dict[str, int] = {}
    sorted_modules = sorted((str(m) for m in modules if m != Path(".")),
                            key=len, reverse=True)
    if not sorted_modules:
        return counter
    for dirpath, _, filenames in walk(target):
        rel_dir = str(dirpath.relative_to(target))
        if rel_dir == ".":
            continue
        # 이 디렉토리가 속한 모듈 찾기
        owning_module = None
        for m in sorted_modules:
            if rel_dir == m or rel_dir.startswith(m + "/"):
                owning_module = m
                break
        if not owning_module:
            continue
        n = sum(1 for f in filenames if Path(f).suffix in CODE_EXTS)
        if n:
            counter[owning_module] = counter.get(owning_module, 0) + n
    return counter


def detect_layered_pattern(module_dir: Path) -> list[str]:
    """H-3 fix: 와일드카드 매칭으로 일반적인 아키텍처 패턴 마커 탐지.

    `Controller.kt`(정확 매칭)이 아닌 `*Controller.kt`(suffix 매칭) 사용.
    """
    hints = []
    # (rglob 패턴, 라벨)
    file_patterns = [
        ("*Controller.kt", "Controller (Kotlin)"),
        ("*Controller.java", "Controller (Java)"),
        ("*Service.kt", "Service (Kotlin)"),
        ("*Service.java", "Service (Java)"),
        ("*Repository.kt", "Repository (Kotlin)"),
        ("*UseCase.kt", "UseCase / Executor"),
        ("*Executor.kt", "Executor (오케스트레이션)"),
        ("*Entity.kt", "JPA Entity"),
    ]
    for pattern, label in file_patterns:
        try:
            if next(module_dir.rglob(pattern), None) is not None:
                if label not in hints:
                    hints.append(label)
        except OSError:
            continue

    # 디렉토리 마커 — `module_dir/api`, `module_dir/domain` 처럼 직속 자식만
    dir_markers = [
        ("api", "api/ 서브 모듈"),
        ("domain", "domain/ 서브 모듈"),
        ("infrastructure", "infrastructure/ 서브 모듈"),
        ("controller", "controller/ 디렉토리"),
    ]
    for marker, label in dir_markers:
        if (module_dir / marker).is_dir() or (module_dir / "src" / "main" / "kotlin" / marker).is_dir():
            if label not in hints:
                hints.append(label)
    return hints


def module_summary_from_root_claude_md(target: Path, module_path: str) -> str | None:
    """루트 AGENTS.md·CLAUDE.md 의 module map 줄에서 모듈 1줄 설명을 cherry-pick.

    매칭: `[`mod`](path)` 또는 `` `mod` `` 다음에 ' — ', ' - ', ': ' 로 이어지는 줄.
    """
    text = ""
    for name in ("AGENTS.md", "CLAUDE.md"):
        try:
            text += (target / name).read_text(encoding="utf-8", errors="replace") + "\n"
        except OSError:
            continue
    if not text:
        return None
    escaped = re.escape(module_path)
    # 형태: `[`module`](path)` — 설명  /  `[module](path)` — 설명  /  `module` — 설명
    patterns = [
        rf"\[`{escaped}`\]\([^)]*\)\s*[—\-:]\s*(.+?)(?:\n|$)",
        rf"\[{escaped}\]\([^)]*\)\s*[—\-:]\s*(.+?)(?:\n|$)",
        rf"`{escaped}`\s*[—\-:]\s*(.+?)(?:\n|$)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            summary = m.group(1).strip()
            # trailing 마크다운 강조/링크 제거
            summary = re.sub(r"\s*\(\[?[^\)]*\)\s*$", "", summary)
            return summary[:200]
    return None


# --- Template -------------------------------------------------------------

SIGNATURE = ("<!-- ai-ready:apply 자동 생성 초안 — 다듬은 뒤 이 줄을 지우면 사람이 관리하는 문서가 되고, "
             "ai-ready 는 이후 이 파일을 덮어쓰지 않는다 -->")

TEMPLATE = """{signature}
# `{module_path}`

## 이 모듈이 하는 일
{what_block}
{design_pointer_block}
## 경계
- 의존해도 되는 것: TODO{manifest_hint}
- 이 모듈에 의존하는 것: TODO
- 의존하면 안 되는 것: TODO — 도구로 막을 수 있으면 아키텍처 테스트로 옮기고 아래 "강제되는 규칙" 에 포인터만 남긴다.

## 변경 방법
{how_block}

## 강제할 수 없는 규칙
<!-- lint·타입·테스트로 잡을 수 없는 것만 적는다. 항목마다 왜를 붙인다. -->
- TODO: <규칙> — 왜: <이유>

## 강제되는 규칙
<!-- 규칙 본문은 도구에 있다. 여기에는 찾아갈 곳만 한 줄씩 적는다. -->
- TODO: <규칙 요약> → <lint 규칙 이름 또는 테스트 경로>
"""


def doc_state(directory: Path) -> str:
    """모듈 폴더 문서의 상태: none(없음) · ours(ai-ready 초안) · human(사람이 관리) · symlink(옛 구조)."""
    agents, claude = directory / "AGENTS.md", directory / "CLAUDE.md"
    if agents.is_symlink() or claude.is_symlink():
        return "symlink"
    if agents.exists() and not managed_doc.is_ai_ready_generated(agents):
        return "human"
    if claude.exists() and not managed_doc.is_ai_ready_generated(claude) and not managed_doc.is_bridge(claude):
        return "human"
    return "ours" if agents.exists() or claude.exists() else "none"


def write_module_docs(out_dir: Path, content: str) -> None:
    """AGENTS.md 에 초안을, CLAUDE.md 에 가져오는 한 줄을 쓴다. 심볼릭 링크는 일반 파일로 바꾼다(--force 로만 온다)."""
    agents, claude = out_dir / "AGENTS.md", out_dir / "CLAUDE.md"
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in (agents, claude):
        if p.is_symlink():
            p.unlink()
    agents.write_text(content, encoding="utf-8")
    if not managed_doc.is_bridge(claude):
        claude.write_text(managed_doc.BRIDGE_TEXT, encoding="utf-8")


def render_what_block(module_path: str, summary: str | None) -> str:
    """루트 AGENTS.md·CLAUDE.md 의 모듈 목록에 한 줄 설명이 있으면 가져온다."""
    return f"- {summary}" if summary else f"- TODO: `{module_path}` 의 책임을 한 문장으로 적는다."


_MANIFESTS_IN_ORDER = ("build.gradle.kts", "build.gradle", "pom.xml", "package.json",
                       "Cargo.toml", "go.mod", "pyproject.toml", "setup.py")


def render_manifest_hint(target: Path, module_path: str) -> str:
    """현재 의존의 정본(빌드 매니페스트)을 가리킨다. 목록을 문서에 복사하지 않는다 — 복사본은 낡는다."""
    for name in _MANIFESTS_IN_ORDER:
        if (target / module_path / name).is_file():
            return f" (지금 의존하는 것의 정본은 `{name}`)"
    return ""


def render_design_pointer_block(target: Path, module_path: str) -> str:
    """모듈이 속한 도메인의 living design 문서 (docs/design/{name}.md) 가 있으면 포인터 한 줄.

    도메인명은 모듈 경로의 최상위 세그먼트 (casting/casting-api → casting).
    파일명은 접두어 없는 `{name}.md` 다. 존재 검사가 실패하면 에러가 아니라 누락으로
    끝나 눈에 안 띄므로, 규약을 바꿀 때는 이 이름도 함께 본다.
    design 문서가 없으면 빈 문자열 — TODO 자리표시자를 만들지 않는다 (점진 확장 정책:
    design 문서가 생기는 도메인부터 포인터가 따라붙는다).
    """
    domain = Path(module_path).parts[0]
    rel = Path("docs/design") / f"{domain}.md"
    if not (target / rel).exists():
        return ""
    depth = len(Path(module_path).parts)
    href = "../" * depth + str(rel)
    return f"- **도메인 설계 문서**: 비즈니스 룰·결정 이력은 [{rel}]({href}) 참조.\n"


def render_how_block(layer_hints: list[str]) -> str:
    if not layer_hints:
        return ("- TODO: 이 모듈에 기능을 더할 때 보통 어느 파일부터 고치는지 적는다.\n"
                "- TODO: 요청이 어디로 들어와서 어디로 나가는지 적는다.")
    out = ["- 코드에서 본 레이어·패턴:"]
    for h in layer_hints:
        out.append(f"  - {h}")
    out.append("- TODO: 진입 → 처리 → 출구 순서로 기능 하나를 더할 때의 흐름을 적는다.")
    return "\n".join(out)


# --- Main -----------------------------------------------------------------

def select_top_modules(target: Path, modules: list[Path], top_n: int) -> list[Path]:
    """H-1/H-2 fix: longest-prefix 매칭으로 commit·file count를 정확히 모듈에 귀속."""
    paths = git_changed_paths(target)
    commit_counts = attribute_to_modules(paths, modules)
    file_counts = file_counts_attributed(target, modules)
    scored = []
    for m in modules:
        if m == Path("."):
            continue
        key = str(m)
        commit_score = commit_counts.get(key, 0)
        file_score = file_counts.get(key, 0)
        # composite: 핫 모듈을 보상하기 위해 commit 가중치 3배
        scored.append((commit_score * 3 + file_score, commit_score, file_score, m))
    scored.sort(reverse=True)
    return [m for _, _, _, m in scored[:top_n]]


def render_module(target: Path, module: Path) -> str:
    m = str(module)
    return TEMPLATE.format(
        signature=SIGNATURE,
        module_path=m,
        what_block=render_what_block(m, module_summary_from_root_claude_md(target, m)),
        design_pointer_block=render_design_pointer_block(target, m),
        manifest_hint=render_manifest_hint(target, m),
        how_block=render_how_block(detect_layered_pattern(target / module)),
    )


def run(target: Path, out_dir: Path, top_n: int, modules_arg: list[str] | None = None,
        force: bool = False, dry_run: bool = False) -> int:
    ml = stacks.logical_modules(target)
    if ml.mode == "no-adapter":
        # 안내문만 찍고 0으로 끝내지 않는다. 그러면 산출물 0개인 실행과 성공한 실행이
        # 호출한 쪽에서 똑같아 보인다.
        print(stacks.unsupported_message(target), file=sys.stderr)
        return EXIT_NO_ADAPTER
    if ml.mode == "no-code":
        layout = ml.layout
        print(f"단일 모듈({layout.stack}) — 기준점 {layout.source_root.relative_to(target)} 아래 "
              f"코드가 든 디렉토리가 없다. 근거: {layout.evidence}", file=sys.stderr)
        return EXIT_NO_PACKAGES

    if modules_arg:
        known = {str(m) for m in ml.modules}
        unknown = [m for m in modules_arg if m not in known]
        if unknown:
            print(f"오류: 모듈 목록에 없는 경로 {unknown}. 알려진 모듈: {sorted(known)}", file=sys.stderr)
            return 2
        selected = [Path(m) for m in modules_arg]
    else:
        # 사람이 이미 관리하는 문서가 있거나 옛 구조(심볼릭 링크)인 모듈은 후보가 아니다. 초안이 필요한 곳만 고른다.
        candidates = []
        for m in ml.modules:
            state = doc_state(out_dir / m)
            if state == "human":
                print(f"건너뜀: {m} (사람이 관리하는 AGENTS.md·CLAUDE.md 가 있다)", file=sys.stderr)
            elif state == "symlink":
                print(f"건너뜀: {m} (AGENTS.md·CLAUDE.md 가 심볼릭 링크다 — audit 보고의 전환 제안 참고)", file=sys.stderr)
            else:
                candidates.append(m)
        selected = select_top_modules(target, candidates, top_n)

    plans = [(m, out_dir / m) for m in selected]
    blocked = [(d, doc_state(d)) for _, d in plans if doc_state(d) in ("human", "symlink")]
    if blocked and not force:
        for d, state in blocked:
            if state == "human":
                for name in ("AGENTS.md", "CLAUDE.md"):
                    p = d / name
                    if p.exists() and not managed_doc.is_ai_ready_generated(p) and not managed_doc.is_bridge(p):
                        managed_doc.guard_overwrite(p, force=False)
            else:
                print(f"중단: {d} 의 AGENTS.md·CLAUDE.md 가 심볼릭 링크다 — 따라 쓰면 링크가 가리키는 파일이 바뀐다.\n"
                      f"  audit 보고의 전환 제안을 보고 사람이 옮긴다. 링크를 일반 파일로 바꿔 쓰려면 --force.",
                      file=sys.stderr)
        return EXIT_REFUSED
    if out_dir == target:
        rels = [f"{m}/{name}" for m in selected for name in ("AGENTS.md", "CLAUDE.md")]
        ignored = managed_doc.ignored_paths(target, rels) or {}
        if ignored and not force:
            print("중단: 만들 파일이 git 에서 무시된다 — 써도 커밋되지 않고, 커밋된 쪽의 가져오기가 깨진다.",
                  file=sys.stderr)
            for rel, why in ignored.items():
                print(f"  {rel} ({why})", file=sys.stderr)
            print("  무시 규칙을 고칠지 사람에게 묻는다. 그래도 쓰려면 --force. 아무것도 쓰지 않았다.", file=sys.stderr)
            return EXIT_IGNORED
    if dry_run:
        for m, d in plans:
            state = "덮어씀(자동 생성 초안)" if (d / "AGENTS.md").exists() else "새로 만듦"
            print(f"{state}: {d / 'AGENTS.md'} (+ CLAUDE.md 에 {managed_doc.AGENTS_IMPORT})")
        return EXIT_OK

    written = []
    for m, d in plans:
        for name in ("AGENTS.md", "CLAUDE.md"):
            p = d / name
            if p.exists() and not p.is_symlink() and not managed_doc.is_bridge(p):
                managed_doc.guard_overwrite(p, force=force)  # --force 로 사람 문서를 덮을 때 경고를 남긴다
        write_module_docs(d, render_module(target, m))
        written.append(d / "AGENTS.md")
    print(f"모듈 문서 초안 {len(written)}개 (AGENTS.md + 그것을 가져오는 CLAUDE.md): {out_dir}")
    for p in written:
        print(f"  - {p}")
    return EXIT_OK


def main():
    ap = argparse.ArgumentParser(description="모듈 문서 초안 생성 (AGENTS.md + 가져오는 CLAUDE.md)")
    ap.add_argument("--target", required=True)
    ap.add_argument("--out", required=True, help="쓸 루트. 대상 저장소 자체면 제자리에 쓴다")
    ap.add_argument("--top", type=int, default=5, help="--modules 가 없을 때 고를 모듈 수")
    ap.add_argument("--modules", help="쉼표로 구분한 모듈 경로. 주면 --top 대신 이 목록만")
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 쓸 파일만 보여 준다")
    managed_doc.add_force_arg(ap)
    args = ap.parse_args()
    target = Path(args.target).resolve()
    out_dir = Path(args.out).resolve()
    if not target.is_dir():
        print(f"오류: 대상이 디렉토리가 아님: {target}", file=sys.stderr)
        sys.exit(2)
    modules = [m.strip().strip("/") for m in args.modules.split(",") if m.strip()] if args.modules else None
    rc = run(target, out_dir, args.top, modules, force=args.force, dry_run=args.dry_run)
    if rc != EXIT_OK:
        print(f"종료 코드 {rc}", file=sys.stderr)
    sys.exit(rc)


if __name__ == "__main__":
    main()
