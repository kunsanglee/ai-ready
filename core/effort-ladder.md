# Effort ladder — provider-neutral reasoning-effort contract

loop 역할(maker·checker·lesson-synthesizer)은 구체 effort 토큰을 박지 않고 **중립 사다리 등급**을 의도로 선언한다. 각 호스트 어댑터가 그 등급을 자기 provider 의 토큰으로 푼다. effort 는 모델과 달리 작고 안정된 순서 enum 이라, 느슨한 이름 맵이 아니라 **정적 변환표**로 충분하다.

## 중립 사다리 (낮음 → 높음)

`minimal < low < medium < high < xhigh < max`

역할은 이 중 하나를 고른다. 예: maker=`high`, checker=`high`(균일 프로필에선 둘이 같은 세션 등급을 물려받는다).

## 호스트 변환표

| 중립 등급 | codex (`model_reasoning_effort`) | Claude (`--effort`) |
|---|---|---|
| minimal | `minimal` | `low` (강등 — Claude 에 minimal 없음, 경고) |
| low | `low` | `low` |
| medium | `medium` | `medium` |
| high | `high` | `high` |
| xhigh | `xhigh` (모델 의존 — 미지원이면 `high` 로 강등, 경고) | `xhigh` |
| max | `max` | `max` |

- codex 는 실측상 `none·minimal·low·medium·high·xhigh·max` 를 받는다(API 가 유효 집합을 명시). 사다리 밖의 `none` 은 쓰지 않는다(필요해지면 사다리에 추가).
- Claude 는 `low·medium·high·xhigh·max` 를 받는다. `minimal` 이 없어 강등한다.

## 강등 규칙

호스트가 요청 등급을 지원하지 않으면 **더 낮은 가장 가까운 지원 등급으로 내리고 경고를 남긴다**. 조용히 올리지 않는다. 봇 러너 추상화의 "대응 없는 값은 생략/강등 + 경고" 규율과 같은 결이다.

## 적용 지점

- **codex(균일 프로필)**: 세션 시작 시 `-c model_reasoning_effort=<토큰>` 로 준다. 세션 effort 는 위임된 maker/checker 하위 에이전트로 상속된다(2026-07-22 실측 — orchestrator `high` → 하위 `high`). 프로필은 `codex/plugins/ai-ready/loop-profile.env` 의 `LOOP_EFFORT`(중립 등급), 런처 `loop-launch.sh` 가 codex 토큰으로 넘긴다.
- **Claude(비대칭 프로필)**: 역할별 에이전트 frontmatter 의 `effort:` 키로 준다(값은 `low·medium·high·xhigh·max`, 세션 등급을 덮어쓰고 미기입이면 상속). codex 와 달리 **호출 시점 재정의가 없다** — Agent 도구는 `model` 파라미터는 받아도 `effort` 파라미터가 없으므로, 호출별 조정이 필요하면 Workflow 스크립트의 `agent(..., {effort})` 를 쓰거나 frontmatter 를 고친다. 그래서 Claude 트리는 균일 프로필이 아니라 **역할별 고정**으로 간다: `loop-maker=high`(모델이 이미 opus 로 세션 아래인 데 더해 한 등급 낮춤), `loop-checker=xhigh`(적발률이 곧 탐색량이라 세션 등급과 분리해 고정 — 세션을 내려도 판정부는 안 내려간다). `loop-lesson-synthesizer` 는 루프당 1회에 결과를 사람이 전량 승인하므로 상속을 유지한다. 2026-07-29 채택.
