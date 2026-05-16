#!/usr/bin/env python3
"""
Minimal YAML frontmatter parser — stdlib only.

본 ai-ready 플러그인은 third-party 의존성 (PyYAML 등) 을 쓰지 않는 정책.
대신 frontmatter 가 실제로 쓰는 *subset* 만 처리하는 가벼운 파서를 자체 구현.

지원 패턴:
  ---
  type: adr                              # scalar (string)
  status: active
  created: 2026-05-16                    # scalar (date — string 그대로 보존)
  count: 7                               # int
  enabled: true                          # bool
  related-adr: [0006, 0007]              # inline list
  superseded-by: []                      # empty list
  aliases:                               # block list
    - 커버 템플릿 통합
    - cover-template
  tags:
    - 한영혼용
    - mixed
  ---

미지원 (의도적):
  - 다중행 string (`>` / `|`)
  - nested object (`key:\n  sub: value`)
  - anchors / aliases
  - flow mapping (`{a: 1, b: 2}`)

위 미지원 패턴이 frontmatter 에 나타나면 *그 키만* 무시한다 (silent fallback).
파서 실패 시 빈 dict 반환 — 호출 측이 frontmatter 없음으로 취급.

사용:
  from frontmatter_parser import parse_frontmatter
  data = parse_frontmatter(Path("docs/adr/0001-x.md").read_text())
"""
from __future__ import annotations

import re
from pathlib import Path


__all__ = ["parse_frontmatter", "extract_frontmatter_and_body"]


_FM_DELIM = "---"


def _parse_scalar(s: str):
    """단일 값 파싱 — 문자열 / 정수 / 불리언."""
    s = s.strip()
    # 둘러싼 따옴표 제거
    if len(s) >= 2 and (
        (s.startswith('"') and s.endswith('"'))
        or (s.startswith("'") and s.endswith("'"))
    ):
        s = s[1:-1]
        return s
    # null
    if s in ("null", "Null", "NULL", "~", ""):
        return None
    # bool
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    # 정수 (leading zero 보존 위해 ADR 번호 같은 4자리 정수는 padded string 으로 본 적도 있음.
    #        그러나 frontmatter-schema 표준은 int[] 이므로 int 로 반환. 출력 측에서 f"{n:04d}" 재포맷.)
    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s)
        except ValueError:
            pass
    # default: string
    return s


def _parse_inline_list(s: str) -> list:
    """`[a, b, c]` 형식 inline list 파싱."""
    inner = s.strip()[1:-1].strip()
    if not inner:
        return []
    # 단순 split — 문자열 안 `,` 가 있는 경우는 미지원 (정수 / 단순 토큰 위주)
    return [_parse_scalar(item.strip()) for item in inner.split(",")]


def parse_frontmatter(text: str) -> dict:
    """텍스트의 frontmatter 블록을 dict 로 파싱."""
    if not text.startswith(_FM_DELIM):
        return {}
    # 첫 줄이 정확히 `---` 이어야 함 (혹시 trailing space 가 있으면 strip)
    first_newline = text.find("\n")
    if first_newline == -1:
        return {}
    if text[:first_newline].strip() != _FM_DELIM:
        return {}
    # 닫는 `---` 찾기
    body_start = first_newline + 1
    end_match = re.search(r"^---\s*$", text[body_start:], re.MULTILINE)
    if not end_match:
        return {}
    fm_block = text[body_start : body_start + end_match.start()]

    data: dict = {}
    current_list_key: str | None = None

    for raw_line in fm_block.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            # 빈 줄 — current_list_key 컨텍스트 유지
            continue
        # 주석
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        # block list item
        if current_list_key is not None and (
            stripped.startswith("- ") or stripped == "-"
        ):
            item_value = stripped[1:].strip()
            if item_value:
                data[current_list_key].append(_parse_scalar(item_value))
            continue
        # key: value 또는 key: (block list 시작)
        # ":" 가 *처음 등장하는* 위치 기준 split (값에 ":" 포함 가능)
        if ":" not in stripped:
            # 미지원 라인 — 무시
            current_list_key = None
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            current_list_key = None
            continue

        if not value:
            # block list 시작 (또는 nested — nested 는 미지원이라 list 로 가정)
            data[key] = []
            current_list_key = key
        elif value.startswith("[") and value.endswith("]"):
            data[key] = _parse_inline_list(value)
            current_list_key = None
        else:
            data[key] = _parse_scalar(value)
            current_list_key = None

    return data


def extract_frontmatter_and_body(text: str) -> tuple[dict, str]:
    """frontmatter dict 와 본문 (frontmatter 제거된 나머지) 을 분리해 반환."""
    if not text.startswith(_FM_DELIM):
        return {}, text
    first_newline = text.find("\n")
    if first_newline == -1:
        return {}, text
    if text[:first_newline].strip() != _FM_DELIM:
        return {}, text
    body_start = first_newline + 1
    end_match = re.search(r"^---\s*$", text[body_start:], re.MULTILINE)
    if not end_match:
        return {}, text
    fm = parse_frontmatter(text)
    # 닫는 ---\n 다음부터가 본문
    body_offset = body_start + end_match.end()
    # 닫는 줄 뒤 개행 1개 흡수
    if body_offset < len(text) and text[body_offset] == "\n":
        body_offset += 1
    return fm, text[body_offset:]


# CLI 진단 — 단일 파일 frontmatter 파싱 결과 출력
if __name__ == "__main__":
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="Markdown 파일 경로")
    args = ap.parse_args()
    p = Path(args.path)
    if not p.is_file():
        print(f"오류: 파일 아님: {p}", file=sys.stderr)
        sys.exit(2)
    fm = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
    print(json.dumps(fm, ensure_ascii=False, indent=2))
