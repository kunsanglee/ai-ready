#!/usr/bin/env python3
"""대상 저장소에 에이전트 작업용 문서·검증 장치의 첫 초안을 만든다.

만들 수 있는 것(--only 로 고른다, 기본은 전부):

  root          루트 AGENTS.md (확인 명령 · 문서 지도 · 강제할 수 없는 규칙 자리) + 그것을 가져오는
                한 줄짜리 CLAUDE.md(`@AGENTS.md`)
  design        docs/design/README.md + .gitattributes 의 union merge 한 줄
                (--design-domain 을 주면 docs/design/{domain}.md 와 {domain}.decisions.md 도)
  antipatterns  docs/ANTIPATTERNS.md — 빈 원장과 항목 형식
  verification  docs/VERIFICATION.md + scripts/verify.sh
  doc-check     scripts/check_docs.py (문서 정합 검사)

모든 파일은 managed_doc 규칙을 따른다. 쓰는 파일의 서명 줄에는 본문 해시가 들어간다. 없으면 만들고, ai-ready 가
쓴 그대로(해시가 맞는) 초안이면 다시 쓴다. 서명이 없는(사람이 관리하는) 파일이나, 서명은 있지만 본문이 고쳐진
초안(해시가 다르거나 해시가 없는 옛 초안)이 하나라도 있으면 아무것도 쓰지 않고 exit 3 이다. scripts/verify.sh 가
고쳐졌으면 지금 CHECKS 도 함께 알린다. 이미 `@AGENTS.md` 를 가져오는 CLAUDE.md 는 그대로 둔다. 만들 파일이 심볼릭
링크면(옛 구조: CLAUDE.md 원본 + AGENTS.md 링크) 따라 쓰지 않고 exit 3 이다. 막는 이유가 여럿이면 모두 적는다.

만들 파일이 git 에서 무시될 때: 무시되는 것이 `@AGENTS.md` 한 줄짜리 CLAUDE.md(다리 파일)뿐이면 그 파일만 건너뛰고
나머지는 쓴다(원본 AGENTS.md 는 커밋된다). AGENTS.md·docs/·scripts/ 같은 원본이 무시되면 아무것도 쓰지 않고
exit 6 이다. 막는 것은 모두 --force 로만 넘긴다(링크는 일반 파일로 바꿔 쓴다). .gitattributes 는 덮어쓰지 않고
빠진 줄만 더한다. 0 이 아닌 종료 코드로 끝나면 stderr 마지막 줄에 `종료 코드 N` 을 적는다.

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
EXIT_REFUSED = 3       # 사람이 관리하는 파일·고친 초안·심볼릭 링크(옛 구조)가 있어 아무것도 쓰지 않았다
EXIT_NO_COMMANDS = 4   # verification 을 골랐는데 확인 명령을 하나도 정하지 못했다
EXIT_IGNORED = 6       # 만들 원본 파일이 git 에서 무시된다 — 써도 커밋되지 않는다

KINDS = ("root", "design", "antipatterns", "verification", "doc-check")

SIGNATURE_MD = managed_doc.SIGNATURE_MD
UNION_LINE = "docs/design/*.decisions.md merge=union"
_DOMAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CHECKS_BLOCK = re.compile(r"^CHECKS=\($\n(.*?)^\)$", re.M | re.S)

ROLE_LABEL = {"typecheck": "타입 검사", "lint": "lint", "test": "테스트"}


@dataclass
class Planned:
    rel: str
    content: str
    executable: bool = False
    bridge: bool = False   # AGENTS.md 를 가져오는 CLAUDE.md — 이미 가져오고 있으면 그대로 둔다


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
              "| 모듈 하나를 고칠 때 | 그 모듈 폴더의 `AGENTS.md` |"]
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
    lines += ["", "명령을 바꾸려면 `scripts/verify.sh` 의 `CHECKS` 를 고치고 이 목록도 같이 고친다. 고친 파일은 첫머리 서명 줄을",
              "남겨 둬도 ai-ready apply 가 다시 덮어쓰지 않고 멈춘다(exit 3). 다시 만들려면 파일을 지우고 돌린다.", "",
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
              "실패하면 턴을 끝내지 못하고 실패 출력의 마지막 20줄을 에이전트가 받는다. 같은 작업 트리로 3번 막았으면",
              "그 뒤로는 확인 명령을 다시 돌리지 않고 통과시키고, 작업 트리가 바뀌면 다시 센다. `scripts/verify.sh` 를",
              "직접 부르면 늘 확인 명령을 돌린다.", "",
              "hook 은 `scripts/verify.sh` 가 한 번 통과한 뒤에 건다. 이번 작업과 무관한 기존 위반으로 막히면 에이전트는",
              "그 위반을 고치지 않고 멈춰서 사람에게 알린다.", "",
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
        out[:0] = [Planned("AGENTS.md", render_root(target, checks, names)),
                   Planned("CLAUDE.md", managed_doc.BRIDGE_TEXT, bridge=True)]
    for p in out:
        if not p.bridge:
            p.content = managed_doc.sign(p.content)
    return out


def _needs_union_line(target: Path) -> bool:
    ga = target / ".gitattributes"
    text = ga.read_text(encoding="utf-8") if ga.is_file() else ""
    return not any(line.split() and line.split()[0] == "docs/design/*.decisions.md" and "merge=union" in line
                   for line in text.splitlines())


def _already_imports(target: Path, p: Planned) -> bool:
    path = target / p.rel
    return p.bridge and path.is_file() and not path.is_symlink() and managed_doc.imports_agents(path)


def _checks_hint(target: Path, p: Planned) -> str:
    """고쳐진 verify.sh 의 지금 CHECKS 와 이번에 만들 CHECKS."""
    now = checks_block((target / p.rel).read_text(encoding="utf-8", errors="replace"))
    new = checks_block(p.content)
    keep = " ".join(f"--check {shlex.quote(c)}" for c in now) if now else "(CHECKS 를 읽지 못했다)"
    return (f"  지금 CHECKS: {now}\n"
            f"  만들 CHECKS: {new}\n"
            f"  지금 파일을 두려면 --only 에서 verification 을 뺀다. 새로 만들되 지금 명령을 이어 쓰려면 파일을 지우고\n"
            f"  이 인자로 돌린다: {keep}")


def _refusals(target: Path, items: list[Planned]) -> list[str]:
    """쓰지 못하게 막는 이유 전부(사람 파일·고친 초안·심볼릭 링크). 한 이유만 보고 멈추면 나머지를 모른다."""
    out: list[str] = []
    for p in items:
        path = target / p.rel
        if path.is_symlink():
            out.append(f"중단: {p.rel} 는 심볼릭 링크다 — 따라 쓰면 링크가 가리키는 파일이 바뀐다.\n"
                       f"  옛 구조(CLAUDE.md 원본 + AGENTS.md 링크)라면 audit 보고의 전환 제안을 보고 사람이 옮긴다.")
            continue
        state = managed_doc.draft_state(path)
        if state == "human":
            out.append(f"중단: {p.rel} 에 ai-ready 서명이 없다 — 사람이 관리하는 파일이라 덮어쓰지 않는다.\n"
                       f"  이 파일은 apply 스킬에서 diff 로 고친다.")
        elif state == "edited":
            msg = f"중단: {p.rel} — {managed_doc.edited_reason(path)}. 덮어쓰지 않는다."
            if p.rel == "scripts/verify.sh":
                msg += "\n" + _checks_hint(target, p)
            else:
                msg += "\n  고친 내용은 apply 스킬에서 diff 로 다룬다. 다시 만들려면 파일을 지우고 돌린다."
            out.append(msg)
    return out


def _checks_change(target: Path, p: Planned) -> str:
    """ai-ready 가 쓴 그대로의 verify.sh 를 다시 쓰면서 CHECKS 가 바뀌면 그 사실 한 줄."""
    path = target / p.rel
    if p.rel != "scripts/verify.sh" or not path.is_file():
        return ""
    now, new = checks_block(path.read_text(encoding="utf-8", errors="replace")), checks_block(p.content)
    return f" — CHECKS 가 바뀐다: {now} → {new}" if now != new else ""


def run(target: Path, kinds: list[str], extra_checks: list[str], domain: str | None,
        force: bool = False, dry_run: bool = False) -> int:
    checks = _checks(target, extra_checks)
    if "verification" in kinds and not checks:
        print("중단: 확인 명령을 하나도 정하지 못했다. 매니페스트에서 추론이 안 되면 --check 로 준다.",
              file=sys.stderr)
        return EXIT_NO_COMMANDS
    planned = plan(target, kinds, checks, domain)
    ignored = managed_doc.ignored_paths(target, [p.rel for p in planned]) or {}
    # 무시되는 다리 파일은 쓰지 않는다. 원본 AGENTS.md 는 커밋되니 멈출 이유가 없다.
    skipped = [] if force else [p for p in planned if p.bridge and p.rel in ignored]
    blocking_ignored = {rel: why for rel, why in ignored.items() if not managed_doc.is_bridge_path(rel)}
    kept = [p for p in planned if p not in skipped and _already_imports(target, p)]
    items = [p for p in planned if p not in kept and p not in skipped]

    refusals = _refusals(target, items)
    if refusals and not force:
        for msg in refusals:
            print(msg, file=sys.stderr)
        print(f"아무것도 쓰지 않았다 — 막는 파일 {len(refusals)}개. 그래도 덮으려면 --force.", file=sys.stderr)
        return EXIT_REFUSED
    if blocking_ignored and not force:
        print("중단: 만들 원본 파일이 git 에서 무시된다 — 써도 커밋되지 않아 다른 클론에는 없고, 커밋된 문서의 "
              "가져오기·링크가 깨진다.", file=sys.stderr)
        for rel, why in blocking_ignored.items():
            print(f"  {rel} ({why})", file=sys.stderr)
        print("  무시 규칙을 고칠지 사람에게 묻는다. 그래도 쓰려면 --force.\n"
              "아무것도 쓰지 않았다.", file=sys.stderr)
        return EXIT_IGNORED
    union = "design" in kinds and _needs_union_line(target)
    note = managed_doc.bridge_skip_note((target / "CLAUDE.md").exists() and "CLAUDE.md" not in ignored) if skipped else ""

    if dry_run:
        for p in kept:
            print(f"그대로 둠(이미 {managed_doc.AGENTS_IMPORT} 를 가져온다): {p.rel}")
        for p in skipped:
            print(f"건너뜀(git 이 무시한다 — {ignored[p.rel]}): {p.rel}")
        for p in items:
            path = target / p.rel
            if path.is_symlink():
                state = "심볼릭 링크를 일반 파일로 바꿔 씀(--force)"
            elif not path.exists():
                state = "새로 만듦"
            else:
                state = {"human": "덮어씀(사람 문서 — --force)", "edited": "덮어씀(고친 초안 — --force)"}.get(
                    managed_doc.draft_state(path), "덮어씀(자동 생성 초안)")
            print(f"{state}: {p.rel}{_checks_change(target, p)}")
        if union:
            print(f"줄 추가: .gitattributes ← {UNION_LINE}")
        if note:
            print(note)
        return EXIT_OK

    for p in items:
        path = target / p.rel
        change = _checks_change(target, p)
        if path.is_symlink():
            print(f"경고: {p.rel} 는 심볼릭 링크지만 --force 로 일반 파일로 바꿔 쓴다.", file=sys.stderr)
            path.unlink()
        managed_doc.guard_overwrite(path, force=force)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(p.content, encoding="utf-8")
        if p.executable:
            os.chmod(path, 0o755)
        print(f"썼다: {p.rel}{change}")
    for p in skipped:
        print(f"건너뜀(git 이 무시한다 — {ignored[p.rel]}): {p.rel}")
    if union:
        ga = target / ".gitattributes"
        text = ga.read_text(encoding="utf-8") if ga.is_file() else ""
        if text and not text.endswith("\n"):
            text += "\n"
        ga.write_text(text + UNION_LINE + "\n", encoding="utf-8")
        print(f"줄 추가: .gitattributes ← {UNION_LINE}")
    if note:
        print(note)
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


def _main_with_code() -> int:
    rc = main()
    if rc != EXIT_OK:
        print(f"종료 코드 {rc}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(_main_with_code())
