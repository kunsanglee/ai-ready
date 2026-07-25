#!/usr/bin/env python3
"""
루트 CLAUDE.md 에 Lazy-load 트리거 테이블 주입.

대상 디렉토리에 존재하는 docs/ 가이드와 광역 문서를 자동 감지해
"트리거 (대화 맥락) → 문서" 매핑을 idempotent block 으로 추가한다.

매 세션 자동 로드되는 루트 CLAUDE.md 분량을 줄이고, AI 가 작업 맥락에
맞는 detail 문서를 lazy-load 하도록 유도하는 게 목적이다.

ROI 액션 매핑: "'사용 시점' 가이드 존재" + "lazy-load 인덱스" (Rule 2.4 + 1.5).

# 변경 이력
- v0.1.x: `<!-- lazy-load:begin -->` ~ `<!-- lazy-load:end -->` 단일 마커. 사용자 수동 추가 행이 다음 실행 시 *전부 덮어쓰임*. (시한폭탄)
- v0.2.0+: **사용자 영역 / 자동 영역 분리** —
    `<!-- lazy-load:user-begin -->` ~ `<!-- lazy-load:user-end -->` 는 *절대 건드리지 않음*,
    `<!-- lazy-load:auto-begin -->` ~ `<!-- lazy-load:auto-end -->` 만 자동 갱신.
  + (선택) `.ai-ready/config.json` 의 `lazy_load_triggers.detect` 추가 룰 적용,
    `override_hardcoded` 로 기본 룰 일부 제거 가능.
- v0.8.7+: **수동 영역과 중복되는 auto 행 자동 제거** — user-section 이 이미 가리키는 문서는
  auto 표에서 뺀다. 루트 CLAUDE.md 는 always-loaded 라 같은 문서를 두 표가 각각 가리키면
  그 중복분이 매 세션 컨텍스트를 먹는다 (c8c-api 에서 12행·약 1,558자 이중 등재).
  `override_hardcoded` 로 손수 지정해야 했던 일을 링크 대상 비교로 자동화한 것.

# 마이그레이션
기존 단일 마커 (`lazy-load:begin`/`lazy-load:end`) 또는 마커 없이 `## Lazy-load docs`
헤더만 있는 CLAUDE.md 에 대해서는 *기존 표 내용을 user-section 으로 안전하게 흡수* 후
auto-section 을 별도 생성. 사용자가 한 번 더 audit:apply 만 실행해도 수동 추가 행이
보존됨.

실행:
  python3 inject_lazy_load_index.py --target /path/to/repo

  # 미리 보기 (수정 안 함)
  python3 inject_lazy_load_index.py --target /path/to/repo --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 동일 디렉토리의 config_loader import
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from config_loader import (  # noqa: E402
    load_config,
    lazy_load_detect_rules,
    lazy_load_override_hardcoded,
)

CLAUDE_DOC_NAMES = ("CLAUDE.md", "AGENTS.md")

# v0.2.0 마커 (auto / user 분리)
AUTO_BEGIN = "<!-- lazy-load:auto-begin (auto-generated) -->"
AUTO_END = "<!-- lazy-load:auto-end -->"
USER_BEGIN = "<!-- lazy-load:user-begin -->"
USER_END = "<!-- lazy-load:user-end -->"

# v0.1.x legacy 단일 마커 (마이그레이션 대상)
LEGACY_BEGIN = "<!-- lazy-load:begin (auto-generated) -->"
LEGACY_END = "<!-- lazy-load:end -->"

SECTION_HEADING = "## Lazy-load docs"

# 감지 패턴: (파일/디렉토리 경로, 문서 표기, 트리거 설명)
DETECTION_RULES = [
    ("docs/COMMANDS.md", "[`docs/COMMANDS.md`](docs/COMMANDS.md)",
        "빌드·실행·lint 등 명령어 확인"),
    ("docs/CONVENTIONS.md", "[`docs/CONVENTIONS.md`](docs/CONVENTIONS.md)",
        "코드 작성 detail (repository 패턴·DTO 분리·검증 등)"),
    # NAMING.md: docs/ 우선, 루트는 fallback
    ("docs/NAMING.md", "[`docs/NAMING.md`](docs/NAMING.md)",
        "클래스/패키지/메서드/DTO 명명, 컬럼 네이밍"),
    ("NAMING.md", "[`NAMING.md`](NAMING.md)",
        "클래스/패키지/메서드/DTO 명명, 컬럼 네이밍"),
    ("docs/API_COMPATIBILITY.md", "[`docs/API_COMPATIBILITY.md`](docs/API_COMPATIBILITY.md)",
        "Response DTO 변경, 필드 추가/제거, 버전 호환성"),
    ("docs/ERROR_HANDLING.md", "[`docs/ERROR_HANDLING.md`](docs/ERROR_HANDLING.md)",
        "에러 코드 추가, 예외 처리, i18n 메시지"),
    # TESTING.md: docs/ 우선
    ("docs/TESTING.md", "[`docs/TESTING.md`](docs/TESTING.md)",
        "테스트 작성, 픽스처/Factory 추가, 베이스 클래스 사용"),
    ("TESTING.md", "[`TESTING.md`](TESTING.md)",
        "테스트 작성, 픽스처/Factory 추가, 베이스 클래스 사용"),
    ("docs/GIT_WORKFLOW.md", "[`docs/GIT_WORKFLOW.md`](docs/GIT_WORKFLOW.md)",
        "커밋 메시지·브랜치 네이밍·PR 본문 형식"),
    ("docs/DDL_DML.md", "[`docs/DDL_DML.md`](docs/DDL_DML.md)",
        "마이그레이션, CREATE TABLE, 인덱스 작성"),
    # ANTIPATTERNS.md: docs/ 우선
    ("docs/ANTIPATTERNS.md", "[`docs/ANTIPATTERNS.md`](docs/ANTIPATTERNS.md)",
        "신규 코드 작성·리뷰, 안티패턴 점검"),
    ("ANTIPATTERNS.md", "[`ANTIPATTERNS.md`](ANTIPATTERNS.md)",
        "신규 코드 작성·리뷰, 안티패턴 점검"),
    # ARCHITECTURE.md: docs/ 우선
    ("docs/ARCHITECTURE.md", "[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)",
        "모듈 의존성 / 영향 범위 분석, 새 모듈 결합 검토"),
    ("ARCHITECTURE.md", "[`ARCHITECTURE.md`](ARCHITECTURE.md)",
        "모듈 의존성 / 영향 범위 분석, 새 모듈 결합 검토"),
    ("docs/decisions", "[`docs/decisions/`](docs/decisions/) (ADR)",
        '"왜 이렇게 결정됐나?" — 아키텍처 의사결정 근거 확인'),
    ("docs/INDEX.md", "[`docs/INDEX.md`](docs/INDEX.md)",
        "처음 진입 / 모든 문서 카탈로그"),
    ("docs/pre-commit-setup.md", "[`docs/pre-commit-setup.md`](docs/pre-commit-setup.md)",
        "사전 커밋 훅 셋업·우회"),
    (".ai-ready/audit-report.md", "[`.ai-ready/audit-report.md`](.ai-ready/audit-report.md)",
        "AI 준비도 점수·추이 확인"),
]


def find_root_doc(target: Path) -> Path | None:
    for name in CLAUDE_DOC_NAMES:
        p = target / name
        if p.exists():
            return p
    return None


def detect_present(target: Path, cfg: dict | None = None) -> list[tuple[str, str]]:
    """존재하는 detail 문서만 (문서 표기, 트리거) 튜플 리스트로 반환.

    같은 트리거를 가진 docs/ 우선 / 루트 fallback 항목이 둘 다 있으면 docs/ 만 표시.
    config 의 override_hardcoded 가 있으면 그 경로를 hardcode 룰에서 제거.
    config 의 detect 추가 룰을 hardcode 다음에 append.
    """
    override = set(lazy_load_override_hardcoded(cfg))
    extra_rules = lazy_load_detect_rules(cfg)

    found: list[tuple[str, str]] = []
    seen_triggers: set[str] = set()

    # 1. hardcoded rules
    for path, label, trigger in DETECTION_RULES:
        if path in override:
            continue
        if trigger in seen_triggers:
            continue
        if (target / path).exists():
            found.append((label, trigger))
            seen_triggers.add(trigger)

    # 2. config 추가 rules
    for rule in extra_rules:
        path = rule.get("path")
        label = rule.get("label")
        trigger = rule.get("trigger")
        if not (path and label and trigger):
            continue
        if trigger in seen_triggers:
            continue
        if (target / path).exists():
            found.append((label, trigger))
            seen_triggers.add(trigger)

    return found


_LINK_TARGET_RE = re.compile(r"\]\(([^)\s]+)\)")


def _link_targets(s: str) -> set[str]:
    """마크다운 링크 대상 경로 집합. 후행 슬래시는 정규화해 `docs/design/` 과 `docs/design` 을 같게 본다."""
    return {m.group(1).strip().rstrip("/") for m in _LINK_TARGET_RE.finditer(s or "") if m.group(1).strip()}


def _user_section_text(text: str) -> str:
    """user-section 마커 사이 본문. 마커가 온전하지 않으면 빈 문자열."""
    i = text.find(USER_BEGIN)
    j = text.find(USER_END)
    if i < 0 or j < 0 or j < i:
        return ""
    return text[i + len(USER_BEGIN):j]


def _drop_rows_covered_by_user(
    rows: list[tuple[str, str]], user_text: str
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """user-section 이 이미 가리키는 문서를 auto 표에서 뺀다. 반환: (남길 행, 뺀 행)

    루트 CLAUDE.md 는 매 세션 always-loaded 라, 같은 문서를 수동 표와 자동 표가 각각
    가리키면 그 중복분이 세션마다 컨텍스트를 먹는다. c8c-api 에서 12행(약 1,558자)이
    이렇게 이중 등재돼 있었다. user 행은 사용자가 그 레포 맥락에 맞춰 손으로 쓴 것이라
    트리거 설명이 더 구체적이므로 그쪽을 정본으로 두고 자동 행을 뺀다.
    """
    covered = _link_targets(user_text)
    if not covered:
        return list(rows), []
    kept: list[tuple[str, str]] = []
    dropped: list[tuple[str, str]] = []
    for label, trigger in rows:
        paths = _link_targets(label)
        # label 의 링크 대상이 전부 user 쪽에 이미 있을 때만 뺀다 — 일부만 겹치면 남긴다.
        (dropped if paths and paths <= covered else kept).append((label, trigger))
    return kept, dropped


def _strip_marker_lines(s: str) -> str:
    """문자열에서 lazy-load 마커 라인을 제거.

    auto/user 마커가 한쪽만 손상돼 잔존하면, case C 가 그 잔존 마커를 user-section 으로
    흡수한다. 그러면 다음 실행에서 case A 정규식이 그 마커부터 user 내용까지 통째로 날린다.
    흡수 전에 마커 라인을 걷어내 그 사고를 막는다.
    """
    tokens = {AUTO_BEGIN, AUTO_END, USER_BEGIN, USER_END, LEGACY_BEGIN, LEGACY_END}
    return "\n".join(ln for ln in s.splitlines() if ln.strip() not in tokens)


def _render_auto_block(rows: list[tuple[str, str]]) -> str:
    """auto-section 블록 (마커 포함) 렌더링."""
    lines = []
    lines.append(AUTO_BEGIN)
    lines.append("")
    lines.append("> 자동 생성됩니다. 본 영역 (`lazy-load:auto-begin` ~ `lazy-load:auto-end`) 의 수동 편집은 다음 갱신 시 덮어쓰여집니다.")
    lines.append("> 갱신: Claude Code 에서 `ai-ready:apply` 스킬을 호출하거나 \"lazy-load 인덱스 갱신해줘\" 라고 말하세요.")
    lines.append(">")
    lines.append("> **읽기 강제 시점**: 작업 영역이 트리거에 해당하면 사용자 추가 지시 없이도 즉시 read.")
    lines.append("> **모듈 단위**: 모듈 CLAUDE.md 는 그 모듈 파일을 Read/Edit 할 때 Claude Code 가 자동 로드.")
    lines.append("")
    if rows:
        lines.append("| 트리거 (대화·작업 맥락) | 문서 |")
        lines.append("|---|---|")
        for label, trigger in rows:
            # 셀 안 '|' 는 테이블 컬럼 구분자로 오인돼 행이 깨진다 — 이스케이프하고 개행은 공백으로.
            safe_trigger = trigger.replace("|", "\\|").replace("\n", " ")
            safe_label = label.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {safe_trigger} | {safe_label} |")
    else:
        lines.append("자동 감지된 문서가 모두 위 수동 영역에 이미 등재돼 있어 자동 행이 없습니다.")
    lines.append("")
    lines.append(AUTO_END)
    return "\n".join(lines)


def _render_empty_user_block() -> str:
    """비어 있는 user-section 블록 (사용자가 추후 행 추가)."""
    lines = []
    lines.append(USER_BEGIN)
    lines.append("")
    lines.append("> 본 영역 (`lazy-load:user-begin` ~ `lazy-load:user-end`) 의 행은 사용자 수동 편집용 — `ai-ready:apply` 가 *절대 덮어쓰지 않음*.")
    lines.append("> 자동 감지에서 누락된 트리거를 여기에 추가하세요. 예:")
    lines.append("> ")
    lines.append("> ```")
    lines.append("> | 트리거 설명 | [`docs/custom.md`](docs/custom.md) |")
    lines.append("> ```")
    lines.append("")
    lines.append(USER_END)
    return "\n".join(lines)


def _render_user_block_with_rows(rows_content: str) -> str:
    """사용자 행이 이미 있는 user-section 을 마커로 감싸 반환."""
    lines = []
    lines.append(USER_BEGIN)
    lines.append("")
    lines.append("> 본 영역 (`lazy-load:user-begin` ~ `lazy-load:user-end`) 의 행은 사용자 수동 편집용 — `ai-ready:apply` 가 *절대 덮어쓰지 않음*.")
    lines.append("")
    content = rows_content.strip("\n")
    if content:
        lines.append(content)
        lines.append("")
    lines.append(USER_END)
    return "\n".join(lines)


def _build_full_section(user_block: str, auto_block: str) -> str:
    """`## Lazy-load docs` 헤더 + user + auto 통합 섹션.

    auto-block 마지막에 빈 줄 1개 보장 — 다음 `## ` 헤더와 시각적 분리.
    """
    lines = []
    lines.append(SECTION_HEADING + " (트리거 시 즉시 read)")
    lines.append("")
    lines.append(user_block)
    lines.append("")
    lines.append(auto_block)
    lines.append("")
    lines.append("")  # auto-block 뒤 빈 줄 1개(\n\n) 보장 — 다음 `## ` 헤더와 시각적 분리 (docstring 계약)
    return "\n".join(lines)


def update_root(text: str, rows: list[tuple[str, str]]) -> tuple[str, bool, str, int]:
    """루트 CLAUDE.md 의 lazy-load 섹션을 갱신.

    반환: (new_text, changed, mode, dropped_as_duplicate)
      mode ∈ {"updated-auto", "migrated-legacy", "migrated-unmarked", "inserted-new", "no-rows"}
      dropped_as_duplicate = user-section 에 이미 등재돼 auto 표에서 뺀 행 수

    동작 분기:
    - case A (정상 v0.2.0): user/auto 마커 둘 다 존재 — auto-block 만 교체
    - case B (legacy 단일 마커): lazy-load:begin/end 존재 — auto 로 격하, user 는 빈 마커 신설
    - case C (마커 없는 표): SECTION_HEADING 존재하지만 마커 없음 — 기존 표를 user-section 으로 흡수, auto 별도 생성
    - case D: 없음 — 신규 삽입 (## 모듈 맵 직전 또는 EOF)

    case A / C 는 user-section 이 이미 가리키는 문서를 auto 표에서 뺀다 (`_drop_rows_covered_by_user`).
    case B / D 는 user-section 이 비어 있어 뺄 대상이 없다.
    """
    if not rows:
        return text, False, "no-rows", 0

    # case A: user/auto 마커 둘 다 존재
    has_auto = AUTO_BEGIN in text and AUTO_END in text
    has_user = USER_BEGIN in text and USER_END in text
    if has_auto:
        kept, dropped = _drop_rows_covered_by_user(rows, _user_section_text(text))
        auto_block = _render_auto_block(kept)
        # auto 블록만 교체
        new_text = re.sub(
            re.escape(AUTO_BEGIN) + r".*?" + re.escape(AUTO_END),
            lambda _: auto_block,
            text,
            count=1,
            flags=re.DOTALL,
        )
        if not has_user:
            # auto 만 있고 user 가 없는 비정상 케이스 — user 마커도 신설
            user_block = _render_empty_user_block()
            new_text = new_text.replace(auto_block, user_block + "\n\n" + auto_block, 1)
            return new_text, new_text != text, "updated-auto+user-inserted", len(dropped)
        return new_text, new_text != text, "updated-auto", len(dropped)

    # case B: legacy 단일 마커
    if LEGACY_BEGIN in text and LEGACY_END in text:
        auto_block = _render_auto_block(rows)
        # 기존 LEGACY 블록의 표 내용은 *모두 자동 생성된 것* 이므로 사용자 행 흡수 불필요.
        # SECTION_HEADING 부터 LEGACY_END 까지 통째로 새 user(empty) + auto 로 교체.
        idx_heading = text.find(SECTION_HEADING)
        idx_begin = text.find(LEGACY_BEGIN)
        if 0 <= idx_heading < idx_begin:
            start = idx_heading
        else:
            start = idx_begin
        end = text.find(LEGACY_END) + len(LEGACY_END)
        user_block = _render_empty_user_block()
        full = _build_full_section(user_block, auto_block)
        new_text = text[:start] + full + text[end:]
        return new_text, True, "migrated-legacy", 0

    # case C: SECTION_HEADING 만 존재 (마커 없는 수동 표) — 사용자 수동 행 흡수
    if SECTION_HEADING in text:
        idx_heading = text.find(SECTION_HEADING)
        # 해당 섹션의 끝 = 다음 `## ` 헤더 직전 또는 EOF
        body_start = text.find("\n", idx_heading) + 1
        next_section = re.search(r"^## ", text[body_start:], re.MULTILINE)
        if next_section:
            body_end = body_start + next_section.start()
        else:
            body_end = len(text)
        existing_body = text[body_start:body_end]
        # 손상돼 잔존한 마커가 섞여 있으면, 흡수 후 다음 실행에서 case A 가 user 를 파괴한다 — 제거.
        existing_body = _strip_marker_lines(existing_body)
        # 흡수될 기존 표가 곧 user-section 이 되므로, 그것이 이미 가리키는 문서는 auto 에서 뺀다.
        kept, dropped = _drop_rows_covered_by_user(rows, existing_body)
        # 사용자 수동 표를 user-section 으로 흡수
        user_block = _render_user_block_with_rows(existing_body)
        full = _build_full_section(user_block, _render_auto_block(kept))
        new_text = text[:idx_heading] + full + text[body_end:]
        return new_text, True, "migrated-unmarked", len(dropped)

    # case D: 신규 삽입 — `## 모듈 맵` 직전, 또는 EOF
    user_block = _render_empty_user_block()
    full = _build_full_section(user_block, _render_auto_block(rows))
    target_heading = "## 모듈 맵"
    idx = text.find(target_heading)
    if idx >= 0:
        # full 은 이미 끝에 빈 줄 1개를 포함하므로 추가 "\n\n" 을 넣지 않는다.
        new_text = text[:idx] + full + text[idx:]
        return new_text, True, "inserted-new", 0
    # EOF append
    base = text if text.endswith("\n") else text + "\n"
    return base + "\n" + full + "\n", True, "inserted-new", 0


def collect_facts(target: Path, cfg: dict | None = None) -> dict:
    """문서를 쓰지 않고 lazy-load 트리거 사실(존재하는 detail 문서·트리거 라벨)만 반환.

    AI 가 이 사실 + 현재 루트 CLAUDE.md 의 lazy-load 표를 읽고, 새 트리거만 더하고
    사용자가 손본 행은 보존한다.
    """
    rows = detect_present(target, cfg)
    return {"target": str(target),
            "triggers": [{"label": label, "trigger": trigger} for label, trigger in rows]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="대상 코드베이스 경로")
    ap.add_argument("--dry-run", action="store_true",
                    help="실제 파일은 수정하지 않고 결과만 출력")
    ap.add_argument("--json", action="store_true", dest="json_mode",
                    help="문서를 쓰지 않고 트리거 사실만 JSON 으로 출력(읽기 전용). apply 의 AI 외과 유지보수용")
    args = ap.parse_args()
    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"오류: 대상이 디렉토리가 아님: {target}", file=sys.stderr)
        sys.exit(2)
    if args.json_mode:
        print(json.dumps(collect_facts(target, load_config(target)), ensure_ascii=False, indent=2))
        return
    root = find_root_doc(target)
    if not root:
        print("루트 CLAUDE.md / AGENTS.md 가 없어서 주입할 위치가 없습니다.", file=sys.stderr)
        sys.exit(1)

    cfg = load_config(target)
    rows = detect_present(target, cfg)
    if not rows:
        print("감지된 detail 문서가 없습니다 — lazy-load 인덱스를 만들 대상이 없습니다.")
        sys.exit(0)

    text = root.read_text(encoding="utf-8")
    new_text, changed, mode, dropped = update_root(text, rows)

    if args.dry_run:
        print("=== dry-run 결과 ===")
        print(f"_모드: {mode}_")
        print(f"_변경 여부: {'있음' if changed else '없음'}_")
        if dropped:
            print(f"_수동 영역 중복으로 auto 표에서 뺀 행: {dropped}개_")
        print()
        # 고정 placeholder 가 아니라 실제 갱신 결과(new_text)를 그대로 보여줘
        # 마이그레이션 결과를 미리보기로 검증할 수 있게 한다.
        print(new_text)
        return

    if not changed:
        print(f"변경 없음: {root}  (lazy-load 인덱스 최신, 모드={mode})")
        return
    root.write_text(new_text, encoding="utf-8")
    print(f"lazy-load 인덱스 갱신: {root}")
    print(f"  모드: {mode}")
    print(f"  자동 감지 detail 문서 {len(rows)}개")
    if dropped:
        print(f"  수동 영역에 이미 등재돼 auto 표에서 뺀 행 {dropped}개 (always-loaded 중복 제거)")
    if cfg is not None:
        print(f"  config 추가 룰 {len(lazy_load_detect_rules(cfg))}개, override {len(lazy_load_override_hardcoded(cfg))}개 적용")


if __name__ == "__main__":
    main()
