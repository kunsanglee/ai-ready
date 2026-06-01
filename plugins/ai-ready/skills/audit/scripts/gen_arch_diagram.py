#!/usr/bin/env python3
"""
빌드 매니페스트에서 모듈 의존성을 추출해 ARCHITECTURE.md (+ Mermaid 다이어그램) 생성.

지원하는 빌드 시스템:
  - Gradle (build.gradle.kts / build.gradle): `project(":foo")` 참조 파싱
  - npm workspaces (package.json): `dependencies` 중 workspace 패키지 참조
  - Swift Package Manager (Package.swift): `.package(path: "...")` path-based 워크스페이스 의존성 파싱

ROI 액션 매핑: "ARCHITECTURE.md + Mermaid 다이어그램" (Rule 4.1, +5점).

실행:
  python3 gen_arch_diagram.py --target /path/to/repo --out /path/to/repo/docs/ARCHITECTURE.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

EXCLUDE_DIRS = {
    ".git", "node_modules", "build", "dist", "target", ".gradle", ".idea",
    "out", "bin", "vendor", ".venv", "venv", "__pycache__", ".next", ".turbo",
    ".pytest_cache", ".mypy_cache", ".ai-ready",
}

GRADLE_FILES = ("build.gradle.kts", "build.gradle")


def walk(target: Path):
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        yield Path(dirpath), dirnames, filenames


PROD_GRADLE_CONFIGS = {"implementation", "api", "compileOnly", "runtimeOnly", "kapt"}


def parse_gradle_deps(target: Path) -> list[tuple[str, str]]:
    """gradle build 파일에서 prod 의존성의 project(":foo:bar") 참조만 추출.

    test 전용 의존성 (testImplementation, testRuntimeOnly, testFixtures*) 은
    실행 시 prod 코드 경로가 아니므로 그래프에서 제외한다 — 헥사고날 경계 혼동 방지.
    """
    edges = []
    pattern = re.compile(
        r'(?:^|\b)(\w+)\s*\(\s*(?:testFixtures\s*\(\s*)?project\(["\']:([\w\-:]+)["\']\)',
        re.MULTILINE,
    )
    for dirpath, _, filenames in walk(target):
        for fname in filenames:
            if fname not in GRADLE_FILES:
                continue
            full = dirpath / fname
            rel_dir = str(full.parent.relative_to(target))
            if rel_dir == ".":
                # 루트 build.gradle은 보통 모듈 자체가 아님
                continue
            try:
                text = full.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in pattern.finditer(text):
                config = m.group(1)
                if config not in PROD_GRADLE_CONFIGS:
                    continue
                dep = m.group(2).replace(":", "/")
                edges.append((rel_dir, dep))
            break
    return edges


def parse_swift_deps(target: Path) -> list[tuple[str, str]]:
    """Swift Package Manager `Package.swift` 의 path-based 워크스페이스 의존성만 추출.

    SPM 의 외부 패키지 (`.package(url: ...)`) 는 prod-수준 모듈 그래프와 다르므로 제외.
    같은 저장소 내의 모듈 간 의존성을 표현하는 `.package(path: "...")` 만 추출한다.

    매칭 패턴 (느슨한 정규식, 한 줄짜리 / 멀티라인 모두 허용):
      .package(name: "...", path: "../core")
      .package(path: "../core")
    """
    edges = []
    pattern = re.compile(
        r'\.package\(\s*(?:name\s*:\s*[^,]+,\s*)?path\s*:\s*["\']([^"\']+)["\']'
    )
    target_resolved = target.resolve()
    for dirpath, _, filenames in walk(target):
        if "Package.swift" not in filenames:
            continue
        full = dirpath / "Package.swift"
        rel_dir = str(full.parent.relative_to(target))
        if rel_dir == ".":
            # 루트의 Package.swift 는 단일 모듈 저장소 — 그래프 의미 없음
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in pattern.finditer(text):
            dep_path = m.group(1)
            try:
                abs_dep = (full.parent / dep_path).resolve()
                rel_dep = str(abs_dep.relative_to(target_resolved))
            except (ValueError, OSError):
                continue
            edges.append((rel_dir, rel_dep))
    return edges


def parse_npm_deps(target: Path) -> list[tuple[str, str]]:
    """package.json workspaces의 패키지 이름 기반 의존성 추출."""
    edges = []
    # 먼저 workspace 패키지 이름 → 디렉토리 매핑 생성
    name_to_dir = {}
    for dirpath, _, filenames in walk(target):
        if "package.json" not in filenames:
            continue
        full = dirpath / "package.json"
        try:
            data = json.loads(full.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        name = data.get("name")
        if not name:
            continue
        rel_dir = str(full.parent.relative_to(target))
        if rel_dir == ".":
            continue
        name_to_dir[name] = rel_dir

    for dirpath, _, filenames in walk(target):
        if "package.json" not in filenames:
            continue
        full = dirpath / "package.json"
        rel_dir = str(full.parent.relative_to(target))
        if rel_dir == ".":
            continue
        try:
            data = json.loads(full.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            for dep_name in (data.get(key) or {}):
                if dep_name in name_to_dir:
                    edges.append((rel_dir, name_to_dir[dep_name]))
    return edges


def sanitize_id(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", s) or "root"


def render(target: Path, edges: list[tuple[str, str]]) -> str:
    lines = ["# 모듈 의존성", ""]
    # 휘발성 메타(생성일자 · 대상 워크트리명) 제거 — 브랜치마다 달라져 머지 충돌을 내던 줄.
    lines.append("_자동 생성 (`ai-ready:apply`) — 재생성 시 전체를 덮어씁니다._")
    lines.append("")

    if not edges:
        lines.append("의존성을 감지하지 못했습니다. 단일 모듈이거나 지원하지 않는 빌드 시스템입니다.")
        return "\n".join(lines) + "\n"

    unique_edges = sorted(set(edges))
    nodes = sorted({n for e in unique_edges for n in e})

    lines.append(f"감지된 모듈 {len(nodes)}개, 의존성 엣지 {len(unique_edges)}개.")
    lines.append("")
    lines.append("> **그래프 범위**: prod 의존성 (`implementation`, `api`, `compileOnly`, `runtimeOnly`, `kapt`) 만 포함. `testImplementation` / `testFixtures` 는 제외.")
    lines.append("")
    lines.append("```mermaid")
    lines.append("graph LR")
    # 노드 정의 (디스플레이 라벨 포함)
    for n in nodes:
        lines.append(f"  {sanitize_id(n)}[\"{n}\"]")
    # 엣지
    for src, dst in unique_edges:
        lines.append(f"  {sanitize_id(src)} --> {sanitize_id(dst)}")
    lines.append("```")
    lines.append("")
    lines.append("## 모듈 목록")
    lines.append("")
    for n in nodes:
        lines.append(f"- `{n}`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("_재생성: Claude Code 에서 `ai-ready:apply` 스킬을 호출하거나 \"ARCHITECTURE.md 재생성해줘\" 라고 말하세요._")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--out", required=True, help="ARCHITECTURE.md 출력 경로")
    args = ap.parse_args()
    target = Path(args.target).resolve()
    out_path = Path(args.out).resolve()
    if not target.is_dir():
        print(f"오류: 대상이 디렉토리가 아님: {target}", file=sys.stderr)
        sys.exit(2)
    edges = parse_gradle_deps(target) + parse_npm_deps(target) + parse_swift_deps(target)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(target, edges), encoding="utf-8")
    print(f"ARCHITECTURE.md 생성: {out_path}")
    print(f"  의존성 엣지: {len(set(edges))}개")


if __name__ == "__main__":
    main()
