"""gate_parse.py (게이트 실패 → 항목 큐 파서) 회귀 테스트.

아래 샘플의 **형식**은 2026-07-27 에 실제 출력에서 뜬 것이다(Kotlin 2.x 컴파일러, ktlint,
Gradle test 리포터). 경로·이름만 중립으로 바꿨다. 형식을 기억으로 쓰면 정규식과 테스트가
같은 착오를 공유해 둘 다 초록인 채 실전에서 0건이 된다 — 실제로 Kotlin 2.x 는 열 번호 뒤에
콜론이 없고, 기억은 콜론이 있다고 알려줬다.

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
