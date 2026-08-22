#!/usr/bin/env python3
"""점검 파일 목록을 checker 샤드로 나누는 결정론 분할기 (ai-ready loop 엔진용).

렌즈 하나가 읽을 파일이 많으면 회차 벽시계가 그 렌즈 하나에 끌려간다. 이 스크립트가
목록을 샤드 몇 개로 나눠, 오케스트레이터가 같은 렌즈의 checker 를 샤드 수만큼 병렬로
띄우게 한다. 나누는 주체가 LLM 이면 회차마다 배정이 흔들리므로 여기서 결정론으로 나눈다.

  입력: 파일 경로 목록(stdin, 한 줄 하나. 빈 줄 무시)
  출력: 샤드 수 K 를 stdout 한 줄로. K >= 2 면 {--out-prefix}s1.txt ... sK.txt 에
        샤드별 목록을 쓴다. K == 1 이면 파일을 쓰지 않는다(샤딩 안 함 — 기존 경로 그대로).

규칙(전부 결정론):
  - K = ceil(파일 수 / size) 를 cap 으로 자른다. 파일 수 <= size 면 K=1.
  - 배정은 바이트 크기 균형 — 큰 파일부터(크기 내림차순, 같으면 이름 오름차순) 가장 가벼운
    샤드에 넣는다(같으면 낮은 번호). 읽는 시간이 파일 크기에 대체로 비례한다는 근사다.
  - 없는 파일(삭제된 경로 등)은 크기 0 으로 배정에 남긴다 — 목록에서 빼면 그 파일의 지적
    이력이 어느 샤드의 시야에도 안 들어간다.
  - 샤드 안 목록은 이름 정렬로 쓴다. 같은 입력이면 언제나 같은 파일이 같은 샤드에 간다.

stdlib-only — argparse / math / os / sys 만 사용.
"""
from __future__ import annotations

import argparse
import math
import os
import sys

__all__ = ["plan_shards"]


def plan_shards(files: list[str], size: int, cap: int, root: str = ".") -> list[list[str]]:
    """파일 목록 → 샤드별 목록. 길이 1 이면 샤딩 안 함."""
    names = sorted({f.strip() for f in files if f.strip()})
    if not names:
        return [[]]
    count = min(max(1, math.ceil(len(names) / max(1, size))), max(1, cap))
    if count == 1:
        return [names]

    def byte_size(name: str) -> int:
        try:
            return os.path.getsize(os.path.join(root, name))
        except OSError:
            return 0

    shards: list[list[str]] = [[] for _ in range(count)]
    weights = [0] * count
    # 크기 내림차순, 같으면 이름 — 가장 가벼운 샤드로. 무게 동률이면 파일 수 적은 쪽, 그래도
    # 같으면 낮은 번호(크기가 전부 0 인 목록이 한 샤드로 몰리지 않게). 전부 결정론.
    for name in sorted(names, key=lambda n: (-byte_size(n), n)):
        target = min(range(count), key=lambda i: (weights[i], len(shards[i]), i))
        shards[target].append(name)
        weights[target] += byte_size(name)
    return [sorted(s) for s in shards]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="점검 파일 목록 → checker 샤드 분할")
    ap.add_argument("--size", type=int, required=True, help="샤드당 목표 파일 수")
    ap.add_argument("--cap", type=int, required=True, help="샤드 수 상한")
    ap.add_argument("--out-prefix", required=True,
                    help="샤드 목록 파일 접두 경로 — {prefix}s1.txt 형태로 쓴다")
    ap.add_argument("--root", default=".", help="파일 크기를 잴 기준 디렉터리")
    args = ap.parse_args(argv)

    shards = plan_shards(sys.stdin.read().splitlines(), args.size, args.cap, args.root)
    if len(shards) >= 2:
        for index, shard in enumerate(shards, start=1):
            with open(f"{args.out_prefix}s{index}.txt", "w", encoding="utf-8") as fh:
                fh.write("\n".join(shard) + "\n")
    print(len(shards))
    return 0


if __name__ == "__main__":
    sys.exit(main())
