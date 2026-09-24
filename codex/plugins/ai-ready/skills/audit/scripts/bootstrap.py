#!/usr/bin/env python3
"""대상 저장소에 에이전트 작업용 문서·검증 장치의 첫 초안을 만든다.

만들 수 있는 것(--only 로 고른다, 기본은 전부):

  root          루트 CLAUDE.md (확인 명령 · 문서 지도 · 강제할 수 없는 규칙 자리) + AGENTS.md 심링크
  design        docs/design/README.md + .gitattributes 의 union merge 한 줄
                (--design-domain 을 주면 docs/design/{domain}.md 와 {domain}.decisions.md 도)
  antipatterns  docs/ANTIPATTERNS.md — 빈 원장과 항목 형식
  verification  docs/VERIFICATION.md + scripts/verify.sh
  doc-check     scripts/check_docs.py (문서 정합 검사)

모든 파일은 managed_doc 규칙을 따른다. 없으면 만들고, ai-ready 서명이 있으면 다시 쓰고, 서명이 없는
(사람이 관리하는) 파일이 하나라도 있으면 아무것도 쓰지 않고 exit 3 이다. --force 로만 덮는다.
서명이 있는 scripts/verify.sh 라도 CHECKS 가 이번에 만들 값과 다르면 사람이 고친 것으로 보고 같은 식으로 멈춘다.
.gitattributes 는 덮어쓰지 않고 빠진 줄만 더한다.

  python3 bootstrap.py --target <repo> --dry-run               # 무엇을 쓸지만 본다
  python3 bootstrap.py --target <repo> --only root,verification
  python3 bootstrap.py --target <repo> --only verification --check "npm run lint" --check "npm test"
"""
from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import audit  # noqa: E402
import managed_doc  # noqa: E402
import stacks  # noqa: E402

PROJECT_FILES = _SCRIPT_DIR / "project"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3       # managed_doc: 사람이 관리하는 파일이 있어 아무것도 쓰지 않았다
EXIT_NO_COMMANDS = 4   # verification 을 골랐는데 확인 명령을 하나도 정하지 못했다

KINDS = ("root", "design", "antipatterns", "verification", "doc-check")

SIGNATURE_MD = ("<!-- ai-ready:apply 자동 생성 초안 — 다듬은 뒤 이 줄을 지우면 사람이 관리하는 문서가 되고, "
                "ai-ready 는 이후 이 파일을 덮어쓰지 않는다 -->")
UNION_LINE = "docs/design/*.decisions.md merge=union"
_DOMAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CHECKS_BLOCK = re.compile(r"^CHECKS=\($\n(.*?)^\)$", re.M | re.S)

ROLE_LABEL = {"typecheck": "타입 검사", "lint": "lint", "test": "테스트"}


@dataclass
class Planned:
    rel: str
    content: str
    executable: bool = False


# --- 내용 ------------------------------------------------------------------

def _checks(target: Path, extra: list[str]) -> list[tuple[str, str]]:
    """(역할, 명령). --check 를 주면 그것만 쓴다 — 추론한 명령과 섞으면 무엇이 도는지 헷갈린다."""
    if extra:
        return [("check", c) for c in extra]
    return stacks.detect_commands(target).checks()


def render_root(target: Path, checks: list[tuple[str, str]], planned: set[str]) -> str:
    def exists(rel: str) -> bool:
        return rel in planned or (target / rel).exists()

    lines = [SIGNATURE_MD, f"# {target.name}", "",
             "TODO: 이 저장소가 무엇인지 한두 문장으로 적는다.", "", "## 확인 명령", ""]
    if exists("scripts/verify.sh"):
        lines.append("- 한 번에: `scripts/verify.sh` (아래 명령을 차례로 돌린다)")
    if checks:
        lines += [f"- {ROLE_LABEL.get(role, '확인')}: `{cmd}`" for role, cmd in checks]
    else:
        lines.append("- TODO: 빌드·lint·테스트 명령을 적는다. 매니페스트에서 추론하지 못했다.")
    lines += ["", "## 문서 지도", "", "| 이럴 때 | 읽을 문서 |", "|---|---|",
              "| 모듈 하나를 고칠 때 | 그 모듈 폴더의 `CLAUDE.md` |"]
    rows = [
        ("docs/design/README.md", "설계 결정의 배경이 궁금할 때"),
        ("docs/ANTIPATTERNS.md", "하면 안 되는 것과 그 이유를 볼 때"),
        ("docs/VERIFICATION.md", "무엇을 어떻게 검증하는지 볼 때"),
    ]
    for rel, when in rows:
        if exists(rel):
            lines.append(f"| {when} | [`{rel}`]({rel}) |")
    known = {rel for rel, _ in rows}
    docs = target / "docs"
    if docs.is_dir():
        for p in sorted(docs.glob("*.md")):
            rel = f"docs/{p.name}"
            if rel not in known:
                lines.append(f"| TODO: 언제 읽나 | [`{rel}`]({rel}) |")
    lines += ["", "## 강제할 수 없는 규칙", "",
              "<!-- lint·타입·테스트·CI 로 잡을 수 있는 규칙은 여기 두지 않는다. 항목마다 왜를 붙인다. -->",
              "- TODO: <규칙> — 왜: <이유>", ""]
    return "\n".join(lines)


DESIGN_README = f"""{SIGNATURE_MD}
# docs/design — 설계 문서와 결정 기록

도메인마다 파일 두 개를 둔다.

| 파일 | 담는 것 | 고치는 방법 |
|---|---|---|
| `{{domain}}.md` | 지금 시스템이 어떻게 동작하나 | 동작이 바뀌면 그 자리에서 고쳐 쓴다 |
| `{{domain}}.decisions.md` | 왜 그렇게 정했나 (결정 카드) | 새 카드를 맨 위에 더한다. 옛 카드 본문은 고치지 않는다 |

## 결정 카드

카드 제목 줄은 이 형식 하나만 쓴다. 티켓이 없으면 `(-)` 로 둔다.

```
## 제목 · (TICKET-123) · [accepted|proposed|rejected|superseded]
```

- 최신 카드가 맨 위에 온다.
- 결정이 바뀌면 새 카드를 위에 쓰고, 옛 카드는 제목 줄의 라벨만 `[superseded]` 로 바꾼다. 옛 카드 본문은
  그대로 둔다 — 그때 왜 그렇게 정했는지가 남아 있어야 같은 논의를 되풀이하지 않는다.
- 본문에는 날짜, 맥락, 결정, 버린 대안, 결과를 적는다.

## 읽는 법

카드를 전부 읽지 않는다. 제목만 훑고 필요한 카드만 연다.

```
grep -n '^## ' docs/design/<domain>.decisions.md
```

## 병합

`.gitattributes` 의 `{UNION_LINE}` 설정으로 두 브랜치가 같은 자리에 카드를 더해도 충돌 없이 양쪽이 남는다.
같은 카드가 두 번 남거나 라벨만 다른 줄이 둘 남으면 `scripts/check_docs.py` 가 오류로 알린다.
"""


def render_design_domain(domain: str) -> tuple[str, str]:
    doc = f"""{SIGNATURE_MD}
# {domain} — 현재 동작

결정의 배경은 [{domain}.decisions.md]({domain}.decisions.md) 에 있다.

## 무엇을 하나
- TODO

## 주요 흐름
- TODO

## 규칙과 제약
- TODO: 코드로 강제되는 규칙은 "→ <테스트·lint 규칙>" 으로 위치만 적는다.
"""
    decisions = f"""{SIGNATURE_MD}
# {domain} — 결정 기록

형식과 읽는 법은 [README.md](README.md) 에 있다. 새 카드는 이 줄 바로 아래, 맨 위에 더한다.

## TODO 첫 결정 제목 · (-) · [proposed]

- 날짜: TODO
- 맥락: TODO
- 결정: TODO
- 버린 대안: TODO
- 결과: TODO
"""
    return doc, decisions


ANTIPATTERNS = f"""{SIGNATURE_MD}
# 안티패턴 원장

하지 말아야 할 것을 이유와 함께 모은다. 강제할 수 있는 항목은 먼저 lint·타입·테스트로 옮기고, 여기에는 그
위치만 적는다. 도구로 잡을 수 없는 항목은 왜 못 잡는지 적는다.

## 항목 형식

```
### <짧은 제목>
- DO NOT: <하지 말 것>
- 이유: <왜 — 어떤 사고가 났거나 날 수 있나>
- 대신: <이렇게 한다>
- 강제 수단: <lint 규칙 이름 또는 테스트 경로>      (또는)  강제 불가: <왜 도구로 못 잡나>
- 출처: <PR·이슈 링크, 날짜>
```

## 항목

아직 없다.
"""


def render_verification(target: Path, checks: list[tuple[str, str]]) -> str:
    enf = audit.enforcement_facts(target)
    ci_by_cmd = {row["command"]: row for row in enf["commands"]}
    lines = [SIGNATURE_MD, "# 검증", "", "무엇을 어떻게 돌려 확인하는지 한 곳에 적는다.", "",
             "## 로컬에서", "", "한 번에 돌린다. 마지막 통과 이후 바뀐 것이 없으면 바로 끝난다.", "",
             "```", "scripts/verify.sh", "```", "", "`scripts/verify.sh` 가 차례로 돌리는 명령:", ""]
    lines += [f"- {ROLE_LABEL.get(role, '확인')}: `{cmd}`" for role, cmd in checks]
    lines += ["", "명령을 바꾸려면 `scripts/verify.sh` 의 `CHECKS` 를 고치고 이 목록도 같이 고친다. 고친 뒤 ai-ready apply 를",
              "다시 돌려도, `CHECKS` 가 새로 만들 값과 다르면 `scripts/verify.sh` 를 덮어쓰지 않고 멈춘다(exit 3).",
              "새 값으로 덮어쓰려면 `--force` 를 준다.", "",
              "마지막 통과를 기억하는 지문에는 커밋·커밋 안 한 변경·추적 안 하는 파일·`CHECKS` 만 들어간다. gitignore 된 파일(`.env` 등),",
              "환경변수, 도구 버전만 바꿨다면 지문을 지우고 다시 돌린다.", "",
              "```", 'rm "$(git rev-parse --git-path verify-pass)"', "```", "",
              "## CI 에서", ""]
    if enf["ci_files"]:
        lines.append("CI 설정: " + ", ".join(f"`{p}`" for p in enf["ci_files"]))
        lines.append("")
        for role, cmd in checks:
            row = ci_by_cmd.get(cmd)
            if row and row["ci"] == "예":
                lines.append(f"- `{cmd}`: CI 가 돌린다 ({', '.join(row['ci_evidence'][:3])})")
            elif row and row["ci"] == audit.CI_EXCLUDED:
                lines.append(f"- `{cmd}`: CI 가 이 명령을 부르는 줄에서 `-x`·`-DskipTests` 같은 옵션으로 이 검사를 뺀다 "
                             f"({', '.join(row['ci_evidence'][:3])}) — TODO: 왜 빼는지, 대신 어디서 도는지 적는다")
            else:
                lines.append(f"- `{cmd}`: CI 설정에서 이 명령을 찾지 못했다 — TODO: CI 에 넣거나 이유를 적는다")
    else:
        lines.append("- 저장소 안에서 CI 설정을 찾지 못했다. TODO: CI 가 저장소 밖에 있으면 어디서 무엇을 돌리는지 적는다.")
    if enf["exclusions"]:
        lines += ["", "테스트를 빼거나 실패를 무시하는 줄:"]
        lines += [f"- `{x['where']}` — {x['label']}. TODO: 왜 빼는지, 대신 어디서 도는지 적는다" for x in enf["exclusions"]]
    lines += ["", "## 에이전트 작업 중", "",
              "Claude Code 를 쓰면 `.claude/settings.json` 의 Stop hook 이 `scripts/verify.sh --stop-hook` 을 돌린다.",
              "실패하면 턴을 끝내지 못하고 실패 출력의 마지막 20줄을 에이전트가 받는다. 연속 3번 막히면 다음 실패는",
              "경고만 남기고 통과시킨다.", "",
              "실패 출력 마지막 20줄이 가공 없이 모델에 전달되므로, 테스트가 환경변수·설정 값을 출력하지 않게 한다.", ""]
    if enf["precommit"]:
        lines += ["pre-commit: " + ", ".join(f"`{p}`" for p in enf["precommit"]), ""]
    lines += ["## 테스트 작성 규칙", "", "- TODO: 테스트를 어디에 두고 어떻게 이름 짓는지, 무엇을 가짜로 바꾸는지 적는다."]
    for legacy in ("docs/TESTING.md", "TESTING.md"):
        if (target / legacy).is_file():
            lines.append(f"- TODO: `{legacy}` 의 내용을 이 절로 옮기고 그 파일은 지운다.")
    lines.append("")
    return "\n".join(lines)


def checks_block(verify_sh: str) -> list[str] | None:
    """verify.sh 의 `CHECKS=( … )` 배열 원소. 따옴표만 바꾼 것은 같은 값으로 본다. 블록을 못 찾거나 셸 문법으로
    읽지 못하면 None."""
    m = _CHECKS_BLOCK.search(verify_sh)
    if not m:
        return None
    try:
        return shlex.split(m.group(1), comments=True)
    except ValueError:
        return None


def render_verify_sh(checks: list[tuple[str, str]]) -> str:
    template = (PROJECT_FILES / "verify.sh").read_text(encoding="utf-8")
    body = "\n".join(f"  {shlex.quote(cmd)}" for _, cmd in checks)
    return template.replace("__CHECKS__", body)


# --- 계획·쓰기 ----------------------------------------------------------------

def plan(target: Path, kinds: list[str], checks: list[tuple[str, str]], domain: str | None) -> list[Planned]:
    out: list[Planned] = []
    if "design" in kinds:
        out.append(Planned("docs/design/README.md", DESIGN_README))
        if domain:
            doc, decisions = render_design_domain(domain)
            out += [Planned(f"docs/design/{domain}.md", doc), Planned(f"docs/design/{domain}.decisions.md", decisions)]
    if "antipatterns" in kinds:
        out.append(Planned("docs/ANTIPATTERNS.md", ANTIPATTERNS))
    if "verification" in kinds:
        out.append(Planned("docs/VERIFICATION.md", render_verification(target, checks)))
        out.append(Planned("scripts/verify.sh", render_verify_sh(checks), executable=True))
    if "doc-check" in kinds:
        out.append(Planned("scripts/check_docs.py",
                           (PROJECT_FILES / "check_docs.py").read_text(encoding="utf-8"), executable=True))
    if "root" in kinds:
        names = {p.rel for p in out}
        out.insert(0, Planned("CLAUDE.md", render_root(target, checks, names)))
    return out


def _needs_union_line(target: Path) -> bool:
    ga = target / ".gitattributes"
    text = ga.read_text(encoding="utf-8") if ga.is_file() else ""
    return not any(line.split() and line.split()[0] == "docs/design/*.decisions.md" and "merge=union" in line
                   for line in text.splitlines())


def _edited_checks(target: Path, items: list[Planned]) -> Planned | None:
    """서명이 남은 기존 verify.sh 인데 CHECKS 가 이번에 만들 값과 다르면 그 항목."""
    for p in items:
        path = target / p.rel
        if p.rel == "scripts/verify.sh" and path.is_file() and managed_doc.is_ai_ready_generated(path):
            if checks_block(path.read_text(encoding="utf-8")) != checks_block(p.content):
                return p
    return None


def run(target: Path, kinds: list[str], extra_checks: list[str], domain: str | None,
        force: bool = False, dry_run: bool = False) -> int:
    checks = _checks(target, extra_checks)
    if "verification" in kinds and not checks:
        print("중단: 확인 명령을 하나도 정하지 못했다. 매니페스트에서 추론이 안 되면 --check 로 준다.",
              file=sys.stderr)
        return EXIT_NO_COMMANDS
    items = plan(target, kinds, checks, domain)
    refused = [p for p in items if (target / p.rel).exists() and not managed_doc.is_ai_ready_generated(target / p.rel)]
    if refused and not force:
        for p in refused:
            managed_doc.guard_overwrite(target / p.rel, force=False)
        print(f"아무것도 쓰지 않았다 — 사람이 관리하는 파일 {len(refused)}개. 그 파일은 apply 스킬에서 diff 로 고친다.",
              file=sys.stderr)
        return EXIT_REFUSED
    edited = _edited_checks(target, items)
    if edited and not force:
        now = checks_block((target / edited.rel).read_text(encoding="utf-8"))
        keep = " ".join(f"--check {shlex.quote(c)}" for c in now) if now else "(CHECKS 를 읽지 못했다)"
        print(f"중단: {edited.rel} 의 CHECKS 가 이번에 만들 값과 다르다 — 사람이 고친 것으로 보고 덮어쓰지 않는다.\n"
              f"  지금 값: {now}\n"
              f"  만들 값: {checks_block(edited.content)}\n"
              f"  지금 값을 두려면 --only 에서 verification 을 빼거나 이 인자로 다시 돌린다: {keep}\n"
              f"  새 값으로 덮으려면 --force.\n"
              f"아무것도 쓰지 않았다.", file=sys.stderr)
        return EXIT_REFUSED
    union = "design" in kinds and _needs_union_line(target)
    agents_link = "root" in kinds and not (target / "AGENTS.md").exists() and not (target / "AGENTS.md").is_symlink()

    if dry_run:
        for p in items:
            state = "새로 만듦" if not (target / p.rel).exists() else (
                "덮어씀(사람 문서 — --force)" if p in refused else "덮어씀(자동 생성 초안)")
            print(f"{state}: {p.rel}")
        if union:
            print(f"줄 추가: .gitattributes ← {UNION_LINE}")
        if agents_link:
            print("심링크: AGENTS.md → CLAUDE.md")
        return EXIT_OK

    for p in items:
        path = target / p.rel
        managed_doc.guard_overwrite(path, force=force)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(p.content, encoding="utf-8")
        if p.executable:
            os.chmod(path, 0o755)
        print(f"썼다: {p.rel}")
    if union:
        ga = target / ".gitattributes"
        text = ga.read_text(encoding="utf-8") if ga.is_file() else ""
        if text and not text.endswith("\n"):
            text += "\n"
        ga.write_text(text + UNION_LINE + "\n", encoding="utf-8")
        print(f"줄 추가: .gitattributes ← {UNION_LINE}")
    if agents_link:
        (target / "AGENTS.md").symlink_to("CLAUDE.md")
        print("심링크: AGENTS.md → CLAUDE.md")
    return EXIT_OK


def main() -> int:
    ap = argparse.ArgumentParser(description="에이전트 작업용 문서·검증 장치 초안")
    ap.add_argument("--target", required=True)
    ap.add_argument("--only", default=",".join(KINDS), help=f"쉼표로 구분: {', '.join(KINDS)}")
    ap.add_argument("--design-domain", help="docs/design/{domain}.md 와 .decisions.md 도 만든다")
    ap.add_argument("--check", action="append", default=[], metavar="CMD",
                    help="verify.sh 에 넣을 확인 명령. 주면 추론한 명령 대신 이것만 쓴다(여러 번)")
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 무엇을 쓸지만 보여 준다")
    managed_doc.add_force_arg(ap)
    args = ap.parse_args()

    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"오류: 대상이 디렉토리가 아니다: {target}", file=sys.stderr)
        return EXIT_USAGE
    kinds = [k.strip() for k in args.only.split(",") if k.strip()]
    unknown = [k for k in kinds if k not in KINDS]
    if unknown:
        print(f"오류: 모르는 종류 {unknown}. 가능한 것: {', '.join(KINDS)}", file=sys.stderr)
        return EXIT_USAGE
    if args.design_domain and not _DOMAIN.match(args.design_domain):
        print(f"오류: 도메인 이름은 영문·숫자·._- 만 쓴다: {args.design_domain}", file=sys.stderr)
        return EXIT_USAGE
    return run(target, kinds, args.check, args.design_domain, force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
