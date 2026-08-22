"""shard_scope.py (checker 샤드 분할기) 회귀 테스트.

분할이 결정론이어야 하는 이유가 이 파일의 주제다 — 같은 입력이 회차마다 다른 배정을 내면
"직전 회차에 이 파일을 본 샤드" 가 없어져 지적 이력이 시야 사이로 샌다.

stdlib only. 실행:
    python3 _loop-engine/test_shard_scope.py
test.sh 가 마지막 섹션에서 이 파일을 호출한다.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import shard_scope  # noqa: E402


class TestShardCount(unittest.TestCase):
    def test_at_or_under_size_is_single_shard(self):
        files = [f"f{i}.txt" for i in range(8)]
        self.assertEqual(len(shard_scope.plan_shards(files, 8, 3)), 1)

    def test_over_size_splits(self):
        files = [f"f{i}.txt" for i in range(9)]
        self.assertEqual(len(shard_scope.plan_shards(files, 8, 3)), 2)

    def test_cap_bounds_shard_count(self):
        files = [f"f{i}.txt" for i in range(100)]
        self.assertEqual(len(shard_scope.plan_shards(files, 8, 3)), 3)

    def test_empty_list_is_single_empty_shard(self):
        self.assertEqual(shard_scope.plan_shards([], 8, 3), [[]])

    def test_blank_lines_and_duplicates_are_dropped(self):
        shards = shard_scope.plan_shards(["a.txt", "", "  ", "a.txt", "b.txt"], 8, 3)
        self.assertEqual(shards, [["a.txt", "b.txt"]])


class TestDeterminism(unittest.TestCase):
    def test_same_input_same_assignment(self):
        files = [f"f{i:02d}.txt" for i in range(20)]
        first = shard_scope.plan_shards(files, 8, 3)
        for _ in range(5):
            self.assertEqual(shard_scope.plan_shards(list(reversed(files)), 8, 3), first,
                             "입력 순서가 달라도 배정은 같아야 한다")

    def test_every_file_lands_in_exactly_one_shard(self):
        files = [f"f{i:02d}.txt" for i in range(21)]
        shards = shard_scope.plan_shards(files, 8, 3)
        flat = [name for shard in shards for name in shard]
        self.assertEqual(sorted(flat), sorted(files), "빠지거나 중복된 파일이 있다")

    def test_missing_files_stay_in_the_plan(self):
        # 삭제된 경로를 목록에서 빼면 그 파일의 지적 이력이 어느 샤드 시야에도 안 들어간다.
        shards = shard_scope.plan_shards([f"gone{i}.txt" for i in range(10)], 4, 3)
        flat = [name for shard in shards for name in shard]
        self.assertEqual(len(flat), 10)


class TestSizeBalance(unittest.TestCase):
    def test_large_files_spread_across_shards(self):
        with tempfile.TemporaryDirectory() as root:
            names = []
            for i, size in enumerate([1000, 1000, 10, 10, 10, 10, 10, 10, 10, 10]):
                name = f"f{i}.txt"
                Path(root, name).write_bytes(b"x" * size)
                names.append(name)
            shards = shard_scope.plan_shards(names, 5, 2, root)
            weights = [sum(os.path.getsize(os.path.join(root, n)) for n in s) for s in shards]
            self.assertEqual(len(shards), 2)
            self.assertLess(abs(weights[0] - weights[1]), 1000,
                            f"큰 파일 둘이 한 샤드에 몰렸다: {weights}")


class TestCli(unittest.TestCase):
    def run_cli(self, stdin: str, prefix: str, size: int = 8, cap: int = 3, root: str = ".") -> str:
        proc = subprocess.run(
            [sys.executable, str(HERE / "shard_scope.py"), "--size", str(size),
             "--cap", str(cap), "--out-prefix", prefix, "--root", root],
            input=stdin, capture_output=True, text=True, check=True)
        return proc.stdout.strip()

    def test_single_shard_writes_no_files(self):
        with tempfile.TemporaryDirectory() as d:
            prefix = os.path.join(d, "shard-")
            out = self.run_cli("a.txt\nb.txt\n", prefix)
            self.assertEqual(out, "1")
            self.assertEqual(os.listdir(d), [], "K=1 인데 샤드 파일을 썼다")

    def test_multi_shard_writes_one_list_per_shard(self):
        with tempfile.TemporaryDirectory() as d:
            prefix = os.path.join(d, "shard-")
            stdin = "".join(f"f{i:02d}.txt\n" for i in range(10))
            out = self.run_cli(stdin, prefix, size=4, cap=3)
            self.assertEqual(out, "3")
            written = sorted(os.listdir(d))
            self.assertEqual(written, ["shard-s1.txt", "shard-s2.txt", "shard-s3.txt"])
            lines = []
            for name in written:
                content = Path(d, name).read_text().splitlines()
                self.assertTrue(content, f"{name} 이 비어 있다")
                lines.extend(content)
            self.assertEqual(sorted(lines), [f"f{i:02d}.txt" for i in range(10)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
