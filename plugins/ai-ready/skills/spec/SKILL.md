---
name: spec
description: 무인 실행에 넘길 스펙을 사람과 함께 도출하는 도출층. 대화·초안·기존 코드에서 아직 안 정해진 결정을 loop-spec-checker 가 다섯 렌즈로 열거하면, 이 스킬이 셋으로 처분한다 — 코드에 답이 있으면 근거 경로와 함께 채우고, 나중에 감으로 맞출 조절값은 기본값으로 표시하고, 추측일 수밖에 없는 것만 사람에게 묻는다. 종료 조건은 rubric 통과가 아니라 미결이 0 이고, 그 판정은 결정 원장을 세는 셸이 한다 — 지적을 받았다고 에이전트가 답을 지어내면 다음 회차가 그것을 통과시켜 환각을 수렴시키기 때문이다. 산출은 /build 가 그대로 받는 설계 문서와 결정 원장. 호출 /spec [초안·설계문서 경로]. Use this skill when the user says "/spec", "스펙 뽑자", "요구사항 정리", "무인 루프 돌리기 전에 스펙부터", or whenever a task is about to go to /build but nobody has decided what "done" means. 도출은 사람에게 직접 물어야 해서 메인 세션이 돌린다.
---

# spec — 무인 실행에 넘길 스펙 도출층

`/build` 는 스펙이 **이미 있다고 가정하고** phase 로 쪼갠다. 이 스킬은 그 앞에 서서 **스펙 자체를 만든다.** 아직 아무도 안 정한 결정을 사람 앞에 놓고 하나씩 닫는다.

## 왜 이 층이 있나

**무인 완주를 가르는 것은 사람 게이트가 아니라 스펙의 질이다.** 같은 날 같은 저장소에서 돌린 두 phase 가 근거다. 목표를 "세웠다고 적은 장치가 실제로 잠기게 한다" 로 준 phase 는 여섯 사이클을 돌고 사람이 한 번 끼어들어야 닫혔고, 목표를 변이 여섯으로 미리 적어 준 phase 는 네 사이클에 사람 없이 닫혔다. `/build` 의 착수 전 검사는 빈 자리를 돌려보내기만 한다. 무엇을 채워야 하는지 함께 알아내는 자리가 이 스킬이다.

## 절대 원칙

1. **답을 지어내지 않는다. 이것이 이 스킬의 전부다.** 스펙의 구멍은 대부분 **사람 머릿속에만** 있어서, 작성하는 쪽에 "지적받았으니 보완해라" 를 시키면 그럴듯한 답이 채워지고 다음 회차의 점검이 그것을 통과시킨다. 그래서 모든 결정에는 **처분과 근거**가 함께 붙고, 근거 없는 채움은 아래 기계 검사가 거부한다.
2. **종료 조건은 통과가 아니라 미결 0 이다.** 결정 원장에 `open` 이 하나도 없고 `asked` 에 전부 사람 답이 붙어 있을 때만 끝나며, 그 판정은 셸이 센다.
3. **도출과 질문은 이 세션이 한다.** 서브에이전트는 사람에게 직접 못 물어 왕복이 성립하지 않는다. 열거(점검)만 `loop-spec-checker` 에 내리고, 처분과 질문과 반영은 이 본문이 메인에서 진행한다.
4. **조절값을 사람에게 묻지 않는다.** 이미 정해진 방식 안에서 나중에 감으로 맞출 수치(타임아웃 몇 초, 페이지 크기, 재시도 횟수)는 기본값을 두고 표시만 한다. **방식 자체가 안 정해진 것**만 사람 몫이다. 재시도를 몇 번 할지는 조절값이고, 재시도가 안전한 연산인지는 결정이다.
5. **미결을 남기고 끝낼 수는 있되 조용히는 안 된다.** 사람이 "그건 나중에" 라고 하면 그 항목은 `deferred` 로 남기고 산출 문서에 **미결 절**로 적는다. 넘긴다는 사실을 문서가 들고 가야 `/build` 로 간 뒤 maker 가 그 자리를 추측으로 메우지 않는다.

## 🔌 plugin / 프로젝트 구조

- 이 스킬은 `ai-ready` plugin 의 일부다. 의존(plugin 번들): `agents/loop-spec-checker.md`(결정 자리 열거, `ai-ready:` namespace), `_loop-engine/detect_build.py`(컨벤션 문서·지식층 경로 감지).
- 산출(프로젝트 델타): `.loop/spec/{slug}/decisions.json`(결정 원장)과 `.loop/spec/{slug}/spec.md`(사람이 읽고 `/build` 가 받는 설계 문서). 사용자가 정본 위치를 지정하면 `spec.md` 는 그리로 옮긴다(예: `docs/design/`).
- 환경변수 없음. 경로는 런타임 감지와 Step 0 이 파일로 남긴다.

## 호출 예시

```
/spec                                  # 대화에서 합의된 것을 출발점으로
/spec docs/design/x.md          # 초안 문서를 출발점으로
/spec --slug T-42                      # 원장 디렉터리 이름 지정(기본은 브랜치명)
```

## 작업 흐름

### Step 0. 셋업 — 원장 자리를 만들고 감지 값을 창에 낸다

```bash
# 엔진: plugin 번들. **$CLAUDE_PLUGIN_ROOT 는 Bash 도구의 셸에 없다** — 스킬 본문을 만들 때
# 치환되는 값이라 자식 셸로 안 내려간다(실측). 그대로 쓰면 ENG=/_loop-engine 이 되어 조용히 없는
# 경로를 가리킨다. 이 스킬 본문 맨 위의 "Base directory for this skill" 값을 그대로 넣는다.
SKILL_DIR="<이 스킬 본문 첫머리의 Base directory 를 그대로 넣는다>"
ENG="$(cd "$SKILL_DIR/../.." && pwd)/_loop-engine"
[ -f "$ENG/lib.sh" ] || { echo "spec: 엔진을 못 찾았다 ($ENG) — base directory 확인" >&2; exit 65; }

# 점검기 정의가 번들에 실재하나. 이 스킬은 열거를 loop-spec-checker 에 전적으로 기대고 대체
# 실행 경로를 두지 않으므로, 그것이 없으면 도출이 성립하지 않는다. 여기서 먼저 보는 이유는
# **설치가 깨진 것과 세션 목록이 낡은 것을 가르기 위해서다** — 파일이 없으면 재설치가 답이고,
# 파일이 있는데 Step 2 의 호출이 죽으면 세션 재시작이 답이다. 둘을 한 메시지로 뭉뚱그리면
# 사람이 엉뚱한 쪽을 고치느라 시간을 쓴다.
SPEC_CHECKER="$(cd "$SKILL_DIR/../.." && pwd)/agents/loop-spec-checker.md"
[ -f "$SPEC_CHECKER" ] || { echo "spec: 점검기 정의가 없다 ($SPEC_CHECKER) — 플러그인 설치가 깨졌다. 재설치하고 다시 온다." >&2; exit 65; }

PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"

# slug 는 원장 디렉터리 이름. 인자로 안 오면 브랜치명에서 만든다. 브랜치별로 갈라야 샤드·워크트리
# 둘이 같은 원장을 덮지 않는다(같은 실수를 loop 상태 포인터에서 한 번 했다).
SLUG="${SPEC_SLUG:-$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')}"
[ -n "$SLUG" ] || { echo "spec: slug 를 못 만들었다 — --slug 로 지정한다" >&2; exit 65; }
SPEC_DIR="$PROJECT_ROOT/.loop/spec/$SLUG"
mkdir -p "$SPEC_DIR"

# 컨벤션 문서·지식층 경로 감지(읽기 전용). loop-spec-checker 의 "이미 답이 있나" 확인에 쓴다 —
# 이 값을 안 넘기면 그 에이전트가 코드로만 확인해서, 잘 정착된 프로젝트일수록 출력이 길어지는
# 거꾸로 된 점검이 된다.
DET="$(python3 "$ENG/detect_build.py" --target "$PROJECT_ROOT")"
LOOP_CONVENTION_DOCS="$(printf '%s' "$DET" | jq -r '(.convention_docs // []) | join(" ")')"
LOOP_KNOWLEDGE_LAYER="$(printf '%s' "$DET" | jq -r '.knowledge_layer // ""')"

# 원장이 없으면 빈 원장으로 시작한다. 있으면 이어서 돈다 — 사람이 답하다 세션이 끊겨도
# 처음부터 다시 묻지 않기 위해서다.
[ -f "$SPEC_DIR/decisions.json" ] || printf '{"round":0,"decisions":[]}\n' > "$SPEC_DIR/decisions.json"

# 감지 값을 창에 낸다. 변수 대입만으로는 다음 Step 의 프롬프트에 넣을 값이 오케스트레이터에게
# 존재하지 않는다 — Bash 호출마다 새 셸이라 변수가 안 남는다.
echo "spec 값: dir=$SPEC_DIR / ledger=$SPEC_DIR/decisions.json / conventions=[${LOOP_CONVENTION_DOCS:-없음}] / knowledge=[${LOOP_KNOWLEDGE_LAYER:-없음}] / engine=$ENG"
```

### Step 1. 출발점을 모은다

세 곳에서 모아 한 문서로 적는다. 이것이 점검 대상이 된다.

- **대화에서 합의된 것** — 이 세션에서 사용자가 말한 목표·제약·거부한 대안. 사람이 이미 말한 것을 다시 묻는 것이 신뢰를 가장 빨리 깎는다.
- **초안 문서** — 인자로 온 경로. 없으면 없는 대로 간다.
- **기존 코드와 컨벤션 문서** — Step 0 이 감지한 경로. 여기에 답이 있는 결정은 애초에 질문이 아니다.

모은 것을 `$SPEC_DIR/spec.md` 초안으로 쓴다. 이 시점의 초안은 **비어 있어도 된다** — 뒤 라운드가 채운다. 형식은 아래 "산출물" 절과 같다.

### Step 2. 결정 자리를 열거한다 (loop-spec-checker)

`Agent` 로 `loop-spec-checker` 를 띄운다. 프롬프트에 담는 것: 점검 대상 경로(`$SPEC_DIR/spec.md` 와 초안 경로), 컨벤션 문서 경로·지식층 값(**환경변수는 서브에이전트에 전달되지 않으므로 Step 0 이 창에 낸 값 자체를 텍스트로**), 출력 경로 `$SPEC_DIR/gaps-round{N}.json`, 그리고 **이미 원장에 처분된 결정 목록**.

마지막 항목이 중요하다. 안 넘기면 매 라운드 같은 자리를 다시 물어 사람이 같은 답을 반복하고, 그 순간 이 스킬은 쓰이지 않게 된다. 넘기는 형태는 `subject` 와 `disposition` 한 줄씩이면 충분하다.

`/build` 를 이미 한 번 돌렸다면 `phases.json` 도 점검 대상에 넣는다 — 그때는 `exit_criteria` 가 되돌림을 말하는지까지 그 에이전트가 본다.

#### `loop-spec-checker` 를 못 부르면 멈춘다 (대체 실행 없음)

`ai-ready:loop-spec-checker` 호출이 "Agent type not found" 로 죽으면 **다른 에이전트로 대신 돌리지 않는다. 대체 실행 경로를 두지 않는다** — 열거가 이 스킬의 전부인데 그 열거를 누가 했는지가 실행마다 달라지면 같은 스펙이 회차마다 다른 개수의 결정을 낸다.

멈추고 사람에게 세 줄을 준다. 그 에이전트가 이 세션의 목록에 없다는 것, 목록은 세션 시작 시점에 고정되므로 설치는 정상일 수 있다는 것, 세션을 다시 시작해 `/spec` 을 다시 부르면 Step 0 이 만든 원장이 남아 있어 처음부터 다시 묻지 않는다는 것.

### Step 3. 셋으로 처분한다 (이 세션이 한다)

`gaps` 하나하나를 아래 넷 중 하나로 처분해 원장에 적는다. **처분마다 요구하는 근거가 다르고, 근거가 없으면 그 처분을 쓸 수 없다.**

| 처분 | 언제 | 반드시 함께 적는 것 |
|---|---|---|
| `resolved-from-code` | 기존 코드·컨벤션 문서·지식층에 답이 이미 있다 | `evidence` 에 **읽은 파일 경로**(가능하면 심볼명까지). 경로 없이 이 처분을 쓰지 않는다 |
| `default` | 방식은 정해졌고 수치만 남은 조절값 | `answer` 에 기본값, `note` 에 "나중에 감으로 맞출 값" 임을 명시 |
| `asked` | 추측일 수밖에 없다 | Step 4 에서 사람 답을 받아 `answer` 에 **사람이 말한 그대로** |
| `deferred` | 사람이 "그건 나중에" 라고 답했다 | `note` 에 왜 미루는지. 산출 문서의 미결 절로 따라간다 |

원장 형식:

```jsonc
{
  "round": 1,
  "decisions": [
    { "id": "g1", "lens": "contract", "subject": "요청 상태 값 집합",
      "question": "취소와 만료를 같은 상태로 볼 것인가 다른 값으로 나눌 것인가",
      "what_diverges": "같으면 재신청 분기가 하나고, 나누면 만료만 재신청을 허용하는 분기가 생긴다",
      "disposition": "resolved-from-code",
      "evidence": "src/main/kotlin/.../RequestStatus.kt — enum 에 CANCELED·EXPIRED 가 이미 따로 있다",
      "answer": "다른 값으로 나눈다" },
    { "id": "g2", "lens": "purpose", "subject": "무엇이 되면 실패인가",
      "question": "어느 지표가 얼마나 나빠지면 이 기능을 끄시겠습니까",
      "what_diverges": "하한이 없으면 무인 루프가 나빠지는 중에도 계속 돈다",
      "disposition": "open" }
  ]
}
```

**`open` 은 처분이 아니라 아직 안 한 상태다.** Step 2 가 낸 gap 은 전부 `open` 으로 들어오고, Step 3·4 가 하나씩 다른 값으로 바꾼다.

### Step 4. 추측만 사람에게 묻는다 (한 라운드에 모아서)

`asked` 로 갈 항목만 사용자에게 낸다. `resolved-from-code` 와 `default` 는 **묻지 않고 결과만 보고한다** — 그 둘까지 물으면 질문 수가 부풀어 사람이 다음부터 이 스킬을 안 부른다.

**한 화면에 모아서 낸다.** 한 번에 하나씩 묻는 방식은 답이 즉시 오는 대화에서는 낫지만, 이 스킬은 백그라운드 잡에서도 돌고 그때 답을 기다리는 자리를 여럿으로 나누면 오지 않을 답을 여러 번 기다리게 된다.

```
## 확인이 필요한 결정 {n}개 (라운드 {r})

### {i}. {subject}  [{lens}]
{question}
- 안 정하면: {what_diverges}
- 선택지: A) ... B) ... (모르겠으면 "나중에" 라고 하시면 미결로 남깁니다)

## 물어보지 않고 정한 것
- {subject} → {answer}  (근거: {evidence})            # resolved-from-code
- {subject} → {answer}  (기본값, 나중에 조정)          # default
```

질문에는 **선택지를 함께 낸다.** "X 를 어떻게 할 것인가" 보다 "X 를 A 로 할 것인가 B 로 할 것인가" 가 답하기 쉽고, 선택지를 못 쓰겠으면 그건 아직 열거가 덜 된 것이다.

답이 오면 `answer` 에 **사람이 말한 그대로** 적는다. 다듬어 적으면 다음 라운드의 점검이 다듬은 문장을 근거로 삼아, 사람이 말하지 않은 것이 스펙에 들어간다.

### Step 5. 반영하고 다시 돈다 — 미결 0 이면 끝

답을 `spec.md` 에 반영한 뒤 **Step 2 로 돌아간다.** 답 하나가 새 결정을 여는 것이 정상이다(상태를 나눴더니 전이표가 필요해지는 식).

종료 판정은 아래 블록이 한다. **모델이 "이만하면 됐다" 를 말하지 않는다.**

```bash
# 종료 조건 — 미결 0. `open` 이 남았거나 `asked` 인데 사람 답이 안 붙었으면 아직이다.
# 처분마다 요구 근거가 다르므로 그것도 함께 본다: 근거 없는 resolved-from-code 가 바로
# 이 스킬이 막으려는 환각이다(지어낸 답이 근거 없이 원장에 앉는 자리).
LEDGER="$SPEC_DIR/decisions.json"
[ -s "$LEDGER" ] || { echo "spec: 원장이 없다 ($LEDGER) — Step 0 미실행" >&2; exit 65; }

# (1) 아직 안 닫힌 것
OPEN="$(jq '[.decisions[] | select(.disposition=="open"
        or (.disposition=="asked" and ((.answer // "") | test("\\S") | not)))] | length' "$LEDGER")"
# (2) 근거 없이 닫힌 것 — 코드에서 나왔다면서 경로가 없거나, 기본값이라면서 값이 없는 것.
UNGROUNDED="$(jq '[.decisions[]
        | select((.disposition=="resolved-from-code" and ((.evidence // "") | test("\\S") | not))
              or (.disposition=="default"           and ((.answer   // "") | test("\\S") | not))
              or (.disposition=="deferred"          and ((.note     // "") | test("\\S") | not)))] | length' "$LEDGER")"
# (3) 처분 어휘 자체가 틀린 것 — 오타로 만든 새 값이 두 검사를 모두 지나가는 것을 막는다.
BADDISP="$(jq '[.decisions[] | select(.disposition
        | IN("open","resolved-from-code","default","asked","deferred") | not)] | length' "$LEDGER")"

TOTAL="$(jq '.decisions | length' "$LEDGER")"
DEFERRED="$(jq '[.decisions[] | select(.disposition=="deferred")] | length' "$LEDGER")"
# 중괄호는 장식이 아니다. 변수 바로 뒤에 한글이 붙으면 셸이 그 한글까지 변수 이름으로 읽어,
# zsh 는 빈 문자열을 내고 bash 는 깨진 바이트를 낸다(실측). 하필 아래 둘은 실패 경로의 메시지라
# 사람이 그 줄을 읽는 순간은 이미 뭔가 잘못됐을 때고, 그때 개수가 사라지면 한 번 더 헤맨다.
echo "spec: 결정 ${TOTAL}개 / 미결 ${OPEN} / 근거없음 ${UNGROUNDED} / 어휘오류 ${BADDISP} / 미룸 ${DEFERRED}"

[ "$BADDISP" -eq 0 ] || { echo "spec: 처분 값이 어휘 밖이다 — open|resolved-from-code|default|asked|deferred 중 하나여야 한다." >&2; exit 65; }
[ "$UNGROUNDED" -eq 0 ] || { echo "spec: 근거 없이 닫은 결정이 ${UNGROUNDED}개 있다 — 코드에서 나왔으면 경로를, 기본값이면 값을, 미룸이면 이유를 적는다. 근거 없는 채움이 이 스킬이 막으려는 것이다." >&2; exit 65; }
[ "$OPEN" -eq 0 ] || { echo "spec: 미결 ${OPEN}개 — Step 2 로 돌아간다(아직 끝이 아니다)." >&2; exit 3; }
echo "spec: 미결 0 — 산출 단계로 간다"
```

> 종료코드가 둘로 갈린다. **65 는 사람이 원장을 고쳐야 하는 것**(근거 없음·어휘 오류)이고, **3 은 그냥 아직 안 끝난 것**이라 다음 라운드로 돌아가라는 뜻이다. 같은 값으로 두면 "한 바퀴 더 돌아라" 와 "네가 뭔가 잘못 적었다" 가 구분되지 않는다.

**라운드 상한은 3이다.** 세 라운드를 돌고도 `open` 이 남으면 더 묻지 않고, 남은 것을 그대로 사용자에게 보여 주며 "이대로 미결로 넘길지" 를 한 번 묻는다. 넘기기로 하면 전부 `deferred` 로 처분한다. 상한이 없으면 답 하나가 새 결정을 여는 성질 때문에 끝나지 않을 수 있고, 그때 지치는 쪽은 사람이다.

### Step 6. 산출 — `/build` 가 받는 형태로

`spec.md` 를 최종 형태로 정리하고 경로를 사용자에게 알린다. 정본을 저장소 문서로 옮기고 싶다면 그때 옮긴다(`docs/design/` 등). 원장은 `.loop/spec/{slug}/decisions.json` 에 남는다 — 나중에 "왜 이렇게 정했나" 를 되짚는 유일한 근거다.

산출 문서 형식:

```markdown
# {제목}

## 목표
{한두 문단. 무엇을 만드는가}

## 안 만드는 것 (Non-Goals)
- {항목} — {왜 안 만드나}

## 결정
| 자리 | 정한 것 | 근거 |
|---|---|---|
| {subject} | {answer} | {evidence 또는 "사람 결정(라운드 N)"} |

## 완료 조건
- {되돌리면 무엇이 빨개지는지로 적는다. "~하게 만든다" 는 항목이 아니다}

## 실패 하한
- {어느 지표가 얼마나 나빠지면 되돌리나}

## 미결 (넘기는 것)
- {subject} — {왜 미뤘나}. `/build` 에서 이 자리에 닿으면 사람에게 올린다.
```

**완료 조건 절이 `/build` 의 `exit_criteria` 가 되고, 안 만드는 것 절이 `non_goals` 의 재료가 되고, 미결 절이 `irreversible`·`tiebreaks` 판단 재료가 된다.** 그래서 이 절들을 대충 적으면 `/build` 의 착수 전 검사가 바로 그 자리에서 막는다.

**다만 알갱이가 다르다. 이 문서의 두 절은 문서에 하나씩이고 `/build` 의 두 칸은 phase 마다 하나라, 옮길 때 나눠야 한다.** 나누는 규칙은 `/build` 스킬의 "착수 전 스펙 검사" 절이 정본이다.

이어서 `/build {산출 문서 경로}` 를 부르면 된다.

## 이 스킬이 하지 않는 것 (Non-Goals)

- **좋은 스펙인지 평가하는 것.** 등급도 점수도 없다. 무엇이 중요한지는 프로젝트마다 달라 기계가 판정하면 거짓 양성으로 사람이 우회법부터 배운다.
- **phase 분해.** 그건 `/build` Step 1 이다. 여기서 미리 쪼개면 두 곳이 서로 다른 분해를 들고 어긋난다.
- **코드 수정.** 도출층은 문서와 원장만 쓴다.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| 매 라운드 같은 것을 다시 묻는다 | Step 2 프롬프트에 처분된 결정 목록을 안 넘겼다 | 원장의 `subject`·`disposition` 을 프롬프트에 싣는다 |
| `gaps` 가 수십 개로 쏟아진다 | 컨벤션 문서 경로를 안 넘겨 점검기가 코드로만 확인했다 | Step 0 의 `conventions=` 값을 프롬프트에 넣는다 |
