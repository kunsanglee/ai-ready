# 강제 초안 만드는 법

audit 이 B(싸게 강제 가능)로 나눈 규칙을 도구로 옮길 때 참고한다. 모든 초안은 사람이 승인한 뒤에 적용한다.

## 순서

강한 수단부터 따져 보고, 가능한 것 중 가장 강한 것을 고른다.

1. **표현할 수 없게 만든다** — 잘못된 상태를 타입·구조로 만들 수 없게 한다. 봉인된 타입(sealed class·
   discriminated union), 값 객체(생성자를 막고 검증하는 팩토리만 연다), 브랜드 타입.
2. **CI 에서 실패하는 lint·금지 API** — 아래 도구별 예시.
3. **정석 헬퍼** — 옳은 길을 함수·모듈 하나로 만들고, 다른 길은 2번 규칙으로 막으면서 오류 메시지가 그 헬퍼를
   가리키게 한다.
4. **런타임 검사** — 경계에서 `require`·`assert`·스키마 검증.
5. **테스트** — 아키텍처 테스트, 계약 테스트.
6. 여기까지 모두 안 되면 C(강제 불가)로 돌려 문서에 이유와 함께 남긴다.

## 오류 메시지

규칙을 어겼을 때 에이전트가 보는 것은 오류 메시지뿐이다. 메시지에 **무엇이 금지인지와 대신 무엇을 쓰는지**를
함께 적는다.

- 나쁜 예: `Forbidden import`
- 좋은 예: `axios 를 직접 부르지 않는다. 대신 src/lib/http.ts 의 request() 를 써라 (재시도·인증 헤더가 거기 있다)`

## 도구별 예시

아래 설정 형식은 도구 버전에 따라 다를 수 있다. 초안을 내기 전에 대상 저장소의 도구 버전과 그 버전의 문서를
확인한다.

### JVM — ArchUnit (테스트)

```kotlin
@AnalyzeClasses(packages = ["com.example"])
class LayerRulesTest {
    @ArchTest
    val controllerDoesNotUseRepository: ArchRule =
        noClasses().that().resideInAPackage("..controller..")
            .should().dependOnClassesThat().resideInAPackage("..repository..")
            .because("컨트롤러는 저장소를 직접 부르지 않는다. 대신 ..service.. 의 서비스를 거쳐라")
}
```

### Kotlin — detekt (금지 import·호출)

```yaml
style:
  ForbiddenImport:
    active: true
    imports:
      - value: 'java.util.Date'
        reason: '대신 java.time.Instant 를 써라'
  ForbiddenMethodCall:
    active: true
    methods:
      - value: 'kotlin.io.println'
        reason: '대신 로거(LoggerFactory.getLogger)를 써라'
```

### TypeScript·JavaScript — eslint

```js
rules: {
  "no-restricted-imports": ["error", {
    paths: [{ name: "axios", message: "대신 src/lib/http.ts 의 request() 를 써라" }],
    patterns: [{ group: ["**/db/*"], message: "UI 에서 db 를 직접 부르지 않는다. 대신 src/services 를 거쳐라" }],
  }],
  "no-restricted-syntax": ["error", {
    selector: "CallExpression[callee.object.name='console'][callee.property.name='log']",
    message: "대신 src/lib/log.ts 의 log() 를 써라",
  }],
}
```

### TypeScript·JavaScript — dependency-cruiser (모듈 경계)

```js
forbidden: [{
  name: "ui-not-to-db",
  comment: "UI 는 db 를 직접 부르지 않는다. 대신 src/services 를 거쳐라",
  severity: "error",
  from: { path: "^src/ui" },
  to: { path: "^src/db" },
}]
```

### Python — ruff banned-api (TID251)

```toml
[tool.ruff.lint]
extend-select = ["TID251"]

[tool.ruff.lint.flake8-tidy-imports.banned-api]
"requests".msg = "대신 app.http.client 를 써라 (타임아웃·재시도가 거기 있다)"
```

### Python — import-linter (모듈 경계)

```toml
[tool.importlinter]
root_package = "app"

[[tool.importlinter.contracts]]
name = "도메인은 인프라를 모른다 — 인프라가 필요하면 app.domain.ports 의 인터페이스를 쓴다"
type = "forbidden"
source_modules = ["app.domain"]
forbidden_modules = ["app.infra"]
```

### Go — golangci-lint (forbidigo·depguard)

`forbidigo` 로 금지 호출을, `depguard` 로 금지 패키지를 막는다. 두 린터 모두 메시지 필드를 둘 수 있으니
"대신 X" 를 적는다. 설정 키 이름이 golangci-lint 버전(v1·v2)마다 달라 대상 저장소 버전에 맞춰 쓴다.

### Rust — clippy disallowed-methods

```toml
# clippy.toml
disallowed-methods = [
  { path = "std::env::var", reason = "대신 crate::config::get 을 써라" },
]
```

CI 에서 `cargo clippy -- -D warnings` 로 돌려야 경고가 실패가 된다.

## 이미 어긴 곳이 있을 때

규칙을 켜자마자 기존 코드가 수백 곳 실패하면 규칙을 끄게 된다. 기존 위반은 기록해 두고 새 위반만 막는다.

| 도구 | 방법 |
|---|---|
| ArchUnit | `FreezingArchRule.freeze(rule)` — 지금 위반을 저장해 두고 새 위반만 실패시킨다 |
| detekt | `detektBaseline` 태스크로 기준 파일을 만들고 설정의 `baseline` 에 연결한다 |
| eslint | 버전에 따라 일괄 억제 기능이 있다. 없으면 파일 단위 `overrides` 로 기존 파일만 규칙을 끈다 |
| dependency-cruiser | 알려진 위반을 기준 파일로 뽑아 두고 그 위반은 무시하는 옵션으로 돌린다 |
| ruff | `ruff check --add-noqa` 로 기존 위반 줄에 억제 주석을 단다 |
| import-linter | 계약의 `ignore_imports` 에 기존 위반을 적는다 |

기준 파일은 줄어들기만 해야 한다. 초안과 함께 "기준 파일에 새 항목이 생기면 리뷰에서 막는다" 는 권고를 낸다.

## 초안에 담을 것

규칙 하나당 다음을 사용자에게 보여 준다.

1. 원래 문서 줄(`파일:줄`)과 규칙 요약
2. 고른 수단과 그 이유(더 강한 수단을 못 쓴 이유 포함)
3. 추가·변경할 파일 내용(설정 조각 또는 테스트 파일)
4. 지금 위반이 몇 곳인지 — 승인을 받아 돌려 본 결과. 돌리지 않았으면 "돌려 보지 않았다" 고 적는다
5. 위반이 있으면 기준 파일 방식
6. 적용 뒤 문서 줄을 "→ <규칙 이름·테스트 경로>" 한 줄로 줄이는 diff
7. CI 가 이 검사를 돌리는지. 안 돌리면 CI 에 넣는 한 줄
