"""gate_parse.py (게이트 실패 → 항목 큐 파서) 회귀 테스트.

아래 샘플의 **형식**은 실제 출력에서 뜬 것이다(2026-07-27: Kotlin 2.x 컴파일러, ktlint,
Gradle test 리포터 / 2026-08-22: eslint 10.9.0 stylish, radon cc 6.0.1, xenon 0.9.3).
경로·이름만 중립으로 바꿨다. 형식을 기억으로 쓰면 정규식과 테스트가
같은 착오를 공유해 둘 다 초록인 채 실전에서 0건이 된다 — 실제로 Kotlin 2.x 는 열 번호 뒤에
콜론이 없고 기억은 콜론이 있다고 알려줬으며, eslint 는 출력을 파일로 리다이렉트해도
ANSI 색 코드를 남기는데 기억은 TTY 가 아니면 색이 꺼진다고 알려줬다.

stdlib only. 실행:
    python3 _loop-engine/test_gate_parse.py
test.sh 가 마지막 섹션에서 이 파일을 호출한다.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import gate_parse  # noqa: E402


# 실측 형식 — Kotlin 2.x. 열 번호 뒤가 콜론이 아니라 공백이다.
KOTLIN_2X = """\
> Task :compileKotlin FAILED
w: file:///repo/src/main/kotlin/com/example/app/Legacy.kt:8:5 Parameter 'unused' is never used.
e: file:///repo/src/main/kotlin/com/example/app/Main.kt:17:31 Unresolved reference 'thisSymbolDoesNotExist'.
e: file:///repo/src/main/kotlin/com/example/app/Main.kt:18:34 Initializer type mismatch: expected 'String', actual 'Int'.

FAILURE: Build failed with an exception.

* What went wrong:
Execution failed for task ':compileKotlin'.
BUILD FAILED in 5s
"""

# 실측 형식 — ktlint. e: 접두어도 file:// 도 없고, 열 뒤가 공백이다.
KTLINT = """\
> Task :ktlintMainSourceSetCheck FAILED
/repo/src/main/kotlin/com/example/app/Main.kt:17:7 Unnecessary long whitespace
/repo/src/main/kotlin/com/example/app/Main.kt:18:1 Unexpected indentation (6) (should be 4)
BUILD FAILED in 3s
"""

# 실측 형식 — Gradle test 리포터. FAILED 줄 다음 들여쓴 줄에 예외·파일·줄이 온다.
GRADLE_TEST = """\
> Task :test FAILED

ReportWriterTest > parses quoted commas() PASSED

ReportWriterTest > emits CRLF between header and rows() FAILED
    org.opentest4j.AssertionFailedError at ReportWriterTest.kt:16

ReportWriterTest > stops at rowCap() PASSED

12 tests completed, 1 failed
BUILD FAILED in 6s
"""


# 실측 형식 — eslint 10.9.0 stylish, 출력을 파일로 리다이렉트한 원문. 색 코드가 그대로 남는다.
ESLINT_ANSI = (
    "\x1b[0m\n"
    "\x1b[4m/repo/web/src/route.js\x1b[24m\n"
    "  \x1b[2m1:1\x1b[22m  \x1b[31merror\x1b[39m  Function 'route' has a complexity of 13. "
    "Maximum allowed is 5  \x1b[2mcomplexity\x1b[22m\n"
    "\n"
    "\x1b[31m\x1b[1m✖ 1 problem (1 error, 0 warnings)\x1b[22m\x1b[39m\n"
    "\x1b[0m\n"
)

# 실측 형식 — eslint 여러 파일·여러 규칙. 파일 헤더가 반복되고 항목 줄엔 파일이 없다.
ESLINT_MULTI = """\

/repo/web/src/route.js
  1:1  error  Function 'route' has a complexity of 13. Maximum allowed is 3  complexity

/repo/web/src/pick.js
  1:1   error  Function 'pick' has a complexity of 8. Maximum allowed is 3  complexity
  4:12  error  Expected '===' and instead saw '=='                          eqeqeq

✖ 3 problems (3 errors, 0 warnings)
"""

# 실측 형식 — eslint 경고. 경고는 게이트를 깨지 않는다(exit 0) — 항목이 아니다.
ESLINT_WARNING = """\

/repo/web/src/tiny.js
  2:9  warning  'unused' is assigned a value but never used  no-unused-vars

✖ 1 problem (0 errors, 1 warning)
"""

# 실측 형식 — radon cc. 파일 헤더 + 들여쓴 항목, 점수 괄호는 -s 옵션일 때만 붙는다.
RADON_WITH_SCORE = """\
src/app/service.py
    F 1:0 route - C (13)
"""
RADON_NO_SCORE = """\
src/app/service.py
    F 1:0 route - C
"""

# 실측 형식 — xenon (radon 기반 게이트형). 한 줄에 파일·줄·이름·등급이 다 실린다.
XENON = 'ERROR:xenon:block "src/app/service.py:1 route" has a rank of C\n'


class TestKotlinCompiler(unittest.TestCase):
    def test_column_without_trailing_colon(self):
        items = gate_parse.parse(KOTLIN_2X)
        errors = [i for i in items if i["kind"] == "compile-error"]
        self.assertEqual(len(errors), 2, f"실측 Kotlin 2.x 형식을 못 잡았다: {items}")
        first = errors[0]
        self.assertEqual(first["file"], "/repo/src/main/kotlin/com/example/app/Main.kt")
        self.assertEqual(first["line_number"], 17)
        self.assertEqual(first["column"], 31)
        self.assertEqual(first["message"], "Unresolved reference 'thisSymbolDoesNotExist'.")

    def test_message_containing_colon_is_kept_whole(self):
        items = gate_parse.parse(KOTLIN_2X)
        messages = [i.get("message") for i in items]
        self.assertIn("Initializer type mismatch: expected 'String', actual 'Int'.", messages)

    def test_legacy_format_with_trailing_colon(self):
        # 구버전 Kotlin·다른 도구는 열 뒤에 콜론이 붙는다. 양쪽을 다 받아야 한다.
        items = gate_parse.parse(
            "e: file:///repo/src/Main.kt:4:9: Unresolved reference 'x'.\n"
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], "compile-error")
        self.assertEqual(items[0]["line_number"], 4)
        self.assertEqual(items[0]["column"], 9)
        self.assertEqual(items[0]["message"], "Unresolved reference 'x'.")

    def test_warnings_are_not_items(self):
        items = gate_parse.parse(KOTLIN_2X)
        self.assertFalse([i for i in items if "never used" in (i.get("message") or "")],
                         "w: 경고는 게이트를 깨지 않으므로 항목이 아니다")

    def test_build_noise_is_not_items(self):
        items = gate_parse.parse(KOTLIN_2X)
        raws = " ".join(i["raw"] for i in items)
        for noise in ("What went wrong", "BUILD FAILED", "> Task"):
            self.assertNotIn(noise, raws, f"빌드 잡음이 항목으로 새어 들어왔다: {noise}")


class TestKtlint(unittest.TestCase):
    def test_no_prefix_is_lint_violation(self):
        items = gate_parse.parse(KTLINT)
        self.assertEqual([i["kind"] for i in items], ["lint-violation", "lint-violation"])
        self.assertEqual(items[0]["column"], 7)
        self.assertEqual(items[0]["message"], "Unnecessary long whitespace")

    def test_parenthesised_message_is_kept(self):
        items = gate_parse.parse(KTLINT)
        self.assertEqual(items[1]["message"], "Unexpected indentation (6) (should be 4)")


class TestGradleTest(unittest.TestCase):
    def test_failed_line_with_cause(self):
        items = gate_parse.parse(GRADLE_TEST)
        self.assertEqual(len(items), 1, f"FAILED 한 건만 항목이어야 한다: {items}")
        item = items[0]
        self.assertEqual(item["kind"], "test-failure")
        self.assertEqual(item["test"], "ReportWriterTest > emits CRLF between header and rows()")
        self.assertEqual(item["file"], "ReportWriterTest.kt")
        self.assertEqual(item["line_number"], 16)
        self.assertEqual(item["exception"], "org.opentest4j.AssertionFailedError")

    def test_passed_lines_are_not_items(self):
        items = gate_parse.parse(GRADLE_TEST)
        raws = " ".join(i["raw"] for i in items)
        self.assertNotIn("PASSED", raws)

    def test_failed_without_cause_line_still_becomes_item(self):
        items = gate_parse.parse("SomeTest > it works() FAILED\n")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], "test-failure")
        self.assertNotIn("file", items[0])

    def test_cause_with_message_instead_of_location(self):
        items = gate_parse.parse(
            "SomeTest > compares values() FAILED\n"
            "    java.lang.AssertionError: expected <2> but was <3>\n"
        )
        self.assertEqual(items[0]["exception"], "java.lang.AssertionError")
        self.assertEqual(items[0]["message"], "expected <2> but was <3>")


class TestOtherStacks(unittest.TestCase):
    def test_javac(self):
        items = gate_parse.parse("src/main/java/App.java:12: error: cannot find symbol\n")
        self.assertEqual(items[0]["kind"], "compile-error")
        self.assertEqual(items[0]["file"], "src/main/java/App.java")
        self.assertEqual(items[0]["line_number"], 12)
        self.assertEqual(items[0]["message"], "cannot find symbol")

    def test_tsc(self):
        items = gate_parse.parse("src/app.ts(17,31): error TS2304: Cannot find name 'foo'.\n")
        self.assertEqual(items[0]["kind"], "compile-error")
        self.assertEqual(items[0]["file"], "src/app.ts")
        self.assertEqual(items[0]["line_number"], 17)
        self.assertEqual(items[0]["column"], 31)

    def test_ruff_style_lint(self):
        items = gate_parse.parse("src/app.py:3:1: F401 'os' imported but unused\n")
        self.assertEqual(items[0]["kind"], "lint-violation")
        self.assertEqual(items[0]["message"], "F401 'os' imported but unused")

    def test_pytest_summary(self):
        items = gate_parse.parse("FAILED tests/test_app.py::test_adds - assert 1 == 2\n")
        self.assertEqual(items[0]["kind"], "test-failure")
        self.assertEqual(items[0]["file"], "tests/test_app.py")
        self.assertEqual(items[0]["test"], "test_adds")
        self.assertEqual(items[0]["message"], "assert 1 == 2")


class TestComplexityTools(unittest.TestCase):
    """QUALITY 게이트로 태우는 복잡도·정적 분석 도구 형식 (2026-08-22 실측)."""

    def test_eslint_ansi_codes_are_stripped(self):
        items = gate_parse.parse(ESLINT_ANSI)
        self.assertEqual(len(items), 1, f"ANSI 색이 남으면 매칭이 통째로 빗나간다: {items}")
        item = items[0]
        self.assertEqual(item["kind"], "complexity-over-threshold")
        self.assertEqual(item["file"], "/repo/web/src/route.js")
        self.assertEqual(item["line_number"], 1)
        self.assertEqual(item["rule"], "complexity")
        self.assertNotIn("\x1b", item["raw"], "raw 에 색 코드가 남으면 maker 가 원문을 오독한다")

    def test_eslint_header_tracks_across_files(self):
        items = gate_parse.parse(ESLINT_MULTI)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["file"], "/repo/web/src/route.js")
        self.assertEqual(items[1]["file"], "/repo/web/src/pick.js")
        self.assertEqual(items[2]["file"], "/repo/web/src/pick.js")
        self.assertEqual(items[2]["line_number"], 4)
        self.assertEqual(items[2]["column"], 12)

    def test_eslint_complexity_rule_gets_its_own_kind(self):
        items = gate_parse.parse(ESLINT_MULTI)
        kinds = {i["rule"]: i["kind"] for i in items}
        self.assertEqual(kinds["complexity"], "complexity-over-threshold")
        self.assertEqual(kinds["eqeqeq"], "lint-violation")

    def test_eslint_warning_is_not_an_item(self):
        # 경고만 있으면 eslint 는 exit 0 이라 게이트가 안 깨진다 — 항목을 내면 안 된다.
        # 이 입력이 파서에 오는 경우는 오류·경고가 섞인 출력뿐이고, 그때도 경고 줄은 건너뛴다.
        items = gate_parse.parse(ESLINT_WARNING + ESLINT_ANSI)
        self.assertEqual(len(items), 1)
        self.assertNotIn("never used", items[0]["message"])

    def test_eslint_summary_line_is_not_an_item(self):
        items = gate_parse.parse(ESLINT_MULTI)
        raws = " ".join(i["raw"] for i in items)
        self.assertNotIn("problem", raws)

    def test_radon_with_and_without_score(self):
        with_score = gate_parse.parse(RADON_WITH_SCORE)
        self.assertEqual(len(with_score), 1)
        self.assertEqual(with_score[0]["kind"], "complexity-over-threshold")
        self.assertEqual(with_score[0]["file"], "src/app/service.py")
        self.assertEqual(with_score[0]["message"], "route cyclomatic complexity rank C (13)")
        no_score = gate_parse.parse(RADON_NO_SCORE)
        self.assertEqual(no_score[0]["message"], "route cyclomatic complexity rank C")

    def test_xenon_single_line(self):
        items = gate_parse.parse(XENON)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["kind"], "complexity-over-threshold")
        self.assertEqual(item["file"], "src/app/service.py")
        self.assertEqual(item["line_number"], 1)
        self.assertEqual(item["message"], "route cyclomatic complexity rank C")

    def test_indented_entry_without_header_is_not_claimed(self):
        # 헤더 없이 들여쓴 항목 줄만 오면 파일을 지어내지 않는다 — 꼬리 폴백으로 남긴다.
        items = gate_parse.parse("  1:1  error  Something is wrong here  some-rule\n")
        self.assertEqual([i["kind"] for i in items], ["gate-output-unparsed"])


class TestNeverSilentlyEmpty(unittest.TestCase):
    def test_unknown_format_keeps_tail(self):
        text = "\n".join(f"이상한 형식 {n}" for n in range(1, 60)) + "\n"
        items = gate_parse.parse(text)
        self.assertEqual(len(items), 1, "아는 형식 0건이면 꼬리 항목 하나가 나와야 한다")
        self.assertEqual(items[0]["kind"], "gate-output-unparsed")
        self.assertEqual(items[0]["tail_lines"], gate_parse.TAIL_LINES)
        self.assertIn("이상한 형식 59", items[0]["raw"])
        self.assertNotIn("이상한 형식 1\n", items[0]["raw"])

    def test_truly_empty_input_is_empty(self):
        self.assertEqual(gate_parse.parse(""), [])
        self.assertEqual(gate_parse.parse("\n  \n\t\n"), [])

    def test_known_format_suppresses_tail_fallback(self):
        items = gate_parse.parse(KOTLIN_2X)
        self.assertFalse([i for i in items if i["kind"] == "gate-output-unparsed"],
                         "아는 형식이 하나라도 있으면 꼬리 폴백을 내지 않는다")


class TestItemShape(unittest.TestCase):
    def test_raw_always_present(self):
        for sample in (KOTLIN_2X, KTLINT, GRADLE_TEST, "형식 모름\n"):
            for item in gate_parse.parse(sample):
                self.assertIn("raw", item, "파서가 잘못 쪼갰을 때 돌아갈 원문이 없다")
                self.assertTrue(item["raw"].strip())

    def test_no_empty_fields(self):
        for item in gate_parse.parse(GRADLE_TEST):
            for key, value in item.items():
                self.assertNotIn(value, ("", None), f"빈 필드가 실렸다: {key}")

    def test_duplicates_collapse(self):
        one = "e: file:///repo/src/Main.kt:4:9 Unresolved reference 'x'.\n"
        self.assertEqual(len(gate_parse.parse(one * 3)), 1)

    def test_same_file_different_line_kept_separate(self):
        two = ("e: file:///repo/src/Main.kt:4:9 Unresolved reference 'x'.\n"
               "e: file:///repo/src/Main.kt:5:9 Unresolved reference 'y'.\n")
        self.assertEqual(len(gate_parse.parse(two)), 2)


class TestCli(unittest.TestCase):
    def test_stage_label_is_attached(self):
        import io
        import json
        from contextlib import redirect_stdout

        buf = io.StringIO()
        stdin = sys.stdin
        sys.stdin = io.StringIO(KTLINT)
        try:
            with redirect_stdout(buf):
                rc = gate_parse.main(["--stage", "lint"])
        finally:
            sys.stdin = stdin
        self.assertEqual(rc, 0)
        rows = [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["stage"] == "lint" for r in rows))

    def test_one_json_object_per_line(self):
        import io
        import json
        from contextlib import redirect_stdout

        buf = io.StringIO()
        stdin = sys.stdin
        sys.stdin = io.StringIO(KOTLIN_2X)
        try:
            with redirect_stdout(buf):
                gate_parse.main([])
        finally:
            sys.stdin = stdin
        for line in buf.getvalue().splitlines():
            if line.strip():
                json.loads(line)   # 줄마다 단독 JSON — 큐 파일에 그대로 이어 붙인다


if __name__ == "__main__":
    unittest.main(verbosity=2)
