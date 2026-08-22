#!/usr/bin/env python3
"""게이트(빌드·테스트·품질) 실패 출력을 항목 큐로 바꾸는 파서 (ai-ready loop 엔진용).

게이트가 깨지면 무인 검증 loop 은 checker 를 부르지 않고 곧장 maker 로 돌아간다. 그때
빌드 출력 전문이 오케스트레이터 창에 그대로 쏟아지고, 다음 회차에 또 쏟아진다. 이 파서가
그 출력을 한 줄 하나의 JSON 항목으로 바꿔, maker 가 항목 단위로 꺼내 고치게 한다. 채점
경로의 `scored.json` 이 checker finding 을 담는 것과 같은 자리를 게이트 실패가 갖는다.

  입력: 게이트 명령의 합친 출력(stdout+stderr)을 stdin 또는 파일 인자로.
  출력: JSONL — 한 줄이 항목 하나. 큐 파일에 그대로 이어 붙일 수 있다.

**빈 큐를 내지 않는다.** 아는 형식이 하나도 안 맞으면 출력 꼬리를 항목 하나로 남긴다.
조용히 버리면 큐가 비어 게이트가 통과한 것처럼 보이고, 그게 이 파서가 막는 실패다.

형식은 추측이 아니라 실제 출력에서 떴다(2026-07-27, Kotlin 2.x + ktlint + Gradle test /
2026-08-22, eslint 10.9.0 stylish + radon cc 6.0.1 + xenon 0.9.3 — QUALITY 게이트용 복잡도 도구).
특히 Kotlin 2.x 는 **열 번호 뒤에 콜론이 없다** — `...:17:31 Unresolved reference` 다.
구버전은 콜론이 붙어(`...:17:31: message`) 양쪽을 다 받는다. 그리고 eslint 는 출력을 파일로
리다이렉트해도 ANSI 색 코드를 남긴다 — 매칭 전에 벗겨야 한다. 기억으로 쓰면 여기서 틀린다.

빌드 시스템으로 분기하지 않고 아는 패턴을 전부 시도한다. 형식이 서로 충분히 달라 교차
매칭이 나지 않고, 분기를 두면 `params.env` 에 빌드 시스템을 실어 나르는 단계가 늘어난다.
한 패턴이 과하게 잡히면 그때 분기를 넣는다.

stdlib-only — json / re / sys / argparse 만 사용.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

__all__ = ["parse", "parse_lines"]

# 꼬리 폴백에 남길 줄 수. 게이트 실패의 원인은 보통 출력 끝에 몰린다.
TAIL_LINES = 40

# 경로:줄:칸 뒤가 콜론일 수도, 공백일 수도 있다(Kotlin 2.x 는 공백).
# `e: file:///abs/File.kt:17:31 메시지`  — Kotlin 컴파일러
# `/abs/File.kt:17:7 메시지`             — ktlint
# `/abs/file.py:3:1: F401 메시지`        — ruff 등 콜론 형식
_FILE_LINE_COL = re.compile(
    r"^(?:(?P<sev>[ew]):\s+)?"           # 선택적 e:/w: 접두어 (Kotlin)
    r"(?:file://)?"                      # 선택적 file:// 스킴 (Kotlin)
    r"(?P<file>/?[^\s:][^\s:]*\.[A-Za-z0-9]+)"   # 확장자 있는 경로
    r":(?P<line>\d+):(?P<col>\d+)"
    r"[:\s]\s*"                          # 콜론 또는 공백 — 버전마다 다르다
    r"(?P<msg>\S.*)$"
)

# `File.java:17: error: 메시지` — javac (칸 없음)
_JAVAC = re.compile(
    r"^(?P<file>\S+\.java):(?P<line>\d+):\s+error:\s+(?P<msg>\S.*)$"
)

# `File.ts(17,31): error TS2304: 메시지` — tsc
_TSC = re.compile(
    r"^(?P<file>\S+?)\((?P<line>\d+),(?P<col>\d+)\):\s+error\s+TS\d+:\s+(?P<msg>\S.*)$"
)

# `SomeTest > 테스트 이름() FAILED` — Gradle test 리포터
_GRADLE_TEST_FAIL = re.compile(
    r"^(?P<suite>\S+)\s+>\s+(?P<test>.+?)\s+FAILED\s*$"
)

# 위 FAILED 줄 **다음** 들여쓴 줄: `org.opentest4j.AssertionFailedError at SomeTest.kt:16`
_GRADLE_TEST_CAUSE = re.compile(
    r"^\s+(?P<exc>[\w.$]+(?:Error|Exception|Throwable))"
    r"(?:\s+at\s+(?P<file>\S+?):(?P<line>\d+))?"
    r"(?:\s*:\s*(?P<detail>.*))?\s*$"
)

# `FAILED path/to/test_x.py::test_name - 메시지` — pytest 요약
_PYTEST_FAIL = re.compile(
    r"^FAILED\s+(?P<file>\S+?)::(?P<test>\S+)(?:\s+-\s+(?P<msg>.*))?$"
)

# 컴파일러 경고는 게이트를 깨지 않는다 — 항목으로 만들지 않는다.
_WARN_PREFIX = re.compile(r"^w:\s")

# ANSI 색 코드. eslint 는 파일로 리다이렉트해도 색을 남긴다(10.9.0 실측) — 매칭 전에 벗긴다.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# 파일 경로가 제 줄에 홀로 서는 헤더. eslint stylish 와 radon cc 가 이 모양으로 파일을 선언하고
# 아래 항목 줄을 들여쓴다 — 항목 줄에는 파일이 없어 헤더를 기억해야 한다.
_BARE_PATH_HEADER = re.compile(r"^(?:/|\.{1,2}/)?[^\s:]+\.[A-Za-z0-9]+$")

# `  1:1  error  Function 'route' has a complexity of 13. Maximum allowed is 5  complexity`
# — eslint stylish (10.9.0 실측). 열 사이가 공백 둘 이상, 마지막 열이 규칙 이름.
_ESLINT_ENTRY = re.compile(
    r"^\s+(?P<line>\d+):(?P<col>\d+)\s{2,}(?P<sev>error|warning)\s{2,}(?P<msg>.+?)\s{2,}(?P<rule>[\w./-]+)$"
)

# `    F 1:0 route - C (13)` — radon cc (6.0.1 실측). 점수 괄호는 -s 옵션일 때만 붙는다.
_RADON_ENTRY = re.compile(
    r"^\s+[FMC]\s+(?P<line>\d+):(?P<col>\d+)\s+(?P<name>\S+)\s+-\s+(?P<rank>[A-F])(?:\s+\((?P<score>\d+)\))?$"
)

# `ERROR:xenon:block "sample.py:1 route" has a rank of C` — xenon (0.9.3 실측)
_XENON = re.compile(
    r'^ERROR:xenon:block\s+"(?P<file>.+?):(?P<line>\d+)\s+(?P<name>\S+)"\s+has a rank of\s+(?P<rank>[A-F])$'
)


def _item(kind: str, raw: str, **fields: object) -> dict:
    """항목 하나. raw 는 항상 남긴다 — 파서가 잘못 쪼갰을 때 maker 가 원문으로 돌아갈 근거다."""
    item: dict = {"kind": kind}
    for key, value in fields.items():
        if value not in (None, ""):
            item[key] = value
    item["raw"] = raw.rstrip()
    return item


def parse_lines(lines: list[str]) -> list[dict]:
    """게이트 출력 줄 목록 → 항목 목록. 아는 형식이 0건이면 꼬리를 항목 하나로."""
    items: list[dict] = []
    seen: set[tuple] = set()

    def add(item: dict) -> None:
        # 같은 파일·줄·메시지가 여러 태스크에서 중복 보고되는 일이 흔하다.
        key = (item.get("kind"), item.get("file"), item.get("line"),
               item.get("column"), item.get("message"), item.get("test"))
        if key in seen:
            return
        seen.add(key)
        items.append(item)

    header_file = None   # 직전 헤더 줄의 파일 경로 — eslint·radon 항목 줄엔 파일이 없다
    for index, raw in enumerate(lines):
        line = _ANSI.sub("", raw.rstrip("\n"))
        if not line.strip() or _WARN_PREFIX.match(line):
            continue

        if _BARE_PATH_HEADER.match(line):
            header_file = line
            continue

        match = _ESLINT_ENTRY.match(line)
        if match and header_file:
            if match.group("sev") == "warning":
                continue   # 경고는 게이트를 깨지 않는다 — w: 접두어와 같은 취급
            kind = ("complexity-over-threshold" if match.group("rule") == "complexity"
                    else "lint-violation")
            add(_item(
                kind, line,
                file=header_file,
                line_number=int(match.group("line")),
                column=int(match.group("col")),
                message=match.group("msg").strip(),
                rule=match.group("rule"),
            ))
            continue

        match = _RADON_ENTRY.match(line)
        if match and header_file:
            score = match.group("score")
            add(_item(
                "complexity-over-threshold", line,
                file=header_file,
                line_number=int(match.group("line")),
                column=int(match.group("col")),
                message=f'{match.group("name")} cyclomatic complexity rank {match.group("rank")}'
                        + (f" ({score})" if score else ""),
            ))
            continue

        match = _XENON.match(line)
        if match:
            add(_item(
                "complexity-over-threshold", line,
                file=match.group("file"),
                line_number=int(match.group("line")),
                message=f'{match.group("name")} cyclomatic complexity rank {match.group("rank")}',
            ))
            continue

        match = _GRADLE_TEST_FAIL.match(line)
        if match:
            cause_file = cause_line = None
            detail = None
            exc = None
            # 원인은 바로 다음 들여쓴 줄에 온다. 없으면 테스트 이름만으로도 항목이 성립한다.
            if index + 1 < len(lines):
                cause = _GRADLE_TEST_CAUSE.match(lines[index + 1].rstrip("\n"))
                if cause:
                    exc = cause.group("exc")
                    cause_file = cause.group("file")
                    cause_line = cause.group("line")
                    detail = (cause.group("detail") or "").strip() or None
            add(_item(
                "test-failure", line,
                test=f'{match.group("suite")} > {match.group("test")}',
                file=cause_file,
                line_number=int(cause_line) if cause_line else None,
                exception=exc,
                message=detail,
            ))
            continue

        match = _PYTEST_FAIL.match(line)
        if match:
            add(_item(
                "test-failure", line,
                test=match.group("test"),
                file=match.group("file"),
                message=(match.group("msg") or "").strip() or None,
            ))
            continue

        match = _TSC.match(line)
        if match:
            add(_item(
                "compile-error", line,
                file=match.group("file"),
                line_number=int(match.group("line")),
                column=int(match.group("col")),
                message=match.group("msg").strip(),
            ))
            continue

        match = _JAVAC.match(line)
        if match:
            add(_item(
                "compile-error", line,
                file=match.group("file"),
                line_number=int(match.group("line")),
                message=match.group("msg").strip(),
            ))
            continue

        match = _FILE_LINE_COL.match(line)
        if match:
            # e: 접두어가 있으면 컴파일 에러, 없으면 린트 위반으로 본다.
            kind = "compile-error" if match.group("sev") == "e" else "lint-violation"
            add(_item(
                kind, line,
                file=match.group("file"),
                line_number=int(match.group("line")),
                column=int(match.group("col")),
                message=match.group("msg").strip(),
            ))
            continue

    if items:
        return items

    # 아는 형식 0건 — 빈 큐를 내지 않는다. 꼬리를 항목 하나로 남겨 maker 가 원문을 본다.
    tail = [ln.rstrip("\n") for ln in lines if ln.strip()][-TAIL_LINES:]
    if not tail:
        return []
    return [_item("gate-output-unparsed", "\n".join(tail),
                  message="게이트가 실패했으나 아는 오류 형식이 없다. 원문 꼬리를 그대로 남긴다.",
                  tail_lines=len(tail))]


def parse(text: str) -> list[dict]:
    return parse_lines(text.splitlines())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="게이트 실패 출력 → 항목 JSONL")
    ap.add_argument("path", nargs="?", help="게이트 출력 파일. 없으면 stdin")
    ap.add_argument("--stage", default="", help="게이트 단계 라벨(build/test/quality). 항목에 실린다")
    args = ap.parse_args(argv)

    if args.path:
        with open(args.path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    else:
        text = sys.stdin.read()

    for item in parse(text):
        if args.stage:
            item["stage"] = args.stage
        print(json.dumps(item, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
