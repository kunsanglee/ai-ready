#!/usr/bin/env python3
"""
ai-ready 프로젝트별 config 로더.

대상 코드베이스의 `<target>/.ai-ready/config.json` 을 read 해 프로젝트별 설정을 dict 로 반환.
없으면 None 반환 — 호출 측이 None 일 때 *기존 동작* (backward compat) 으로 fallback.

stdlib-only 정책 — `json` 모듈만 사용.

config.json 표준 스키마 (v1):
{
  "version": 1,
  "frontmatter": {
    "required": ["type", "feature", "module", "status", "created", "updated"],
    "search":   ["aliases", "tags"],
    "evolution": ["supersedes", "superseded-by"]
  },
  "index": {
    "groups": [
      {
        "id": "adr",
        "title": "ADR (`docs/adr/`)",
        "match": { "path_prefix": "docs/adr/" },
        "sub_group_by": "feature",
        "sort": "filename"
      }
    ],
    "cross_reference": { "enabled": true, "title": "한영 검색 인덱스" },
    "evolution_graph": { "enabled": true, "title": "ADR 결정 진화", "scope": "adr" }
  },
  "lazy_load_triggers": {
    "detect": [
      { "path": "docs/adr/", "label": "[`docs/adr/`](docs/adr/)", "trigger": "ADR 조회" }
    ],
    "override_hardcoded": ["docs/decisions"]
  }
}

각 섹션은 *선택적* — 누락된 섹션은 빈 / 비활성으로 취급.

사용:
  from config_loader import load_config
  cfg = load_config(Path("/path/to/repo"))
  if cfg is None:
      # 기존 동작 (backward compat)
      ...
  else:
      groups = cfg.get("index", {}).get("groups", [])
      ...
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


__all__ = ["load_config", "CONFIG_FILE_NAME", "CONFIG_VERSION"]


CONFIG_FILE_NAME = ".ai-ready/config.json"
CONFIG_VERSION = 1


def load_config(target: Path) -> dict[str, Any] | None:
    """대상 디렉토리의 ai-ready config 를 로드.

    Returns:
        dict — config 가 존재하고 정상 파싱됨
        None — config 가 없거나 (backward compat) 형식이 잘못되어 *안전하게 fallback* 필요
    """
    cfg_path = target / CONFIG_FILE_NAME
    if not cfg_path.is_file():
        return None
    try:
        raw = cfg_path.read_text(encoding="utf-8")
        cfg = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        # JSON 깨짐 — stderr 로 경고만 출력하고 None 반환 (기존 동작 유지).
        # config 가 *부분적으로 잘못된* 경우에도 ai-ready 자체가 멈추면 안 됨.
        print(f"경고: {cfg_path} 파싱 실패 ({e}) — config 없는 것으로 처리.", file=sys.stderr)
        return None
    if not isinstance(cfg, dict):
        print(f"경고: {cfg_path} 가 object 가 아님 — config 없는 것으로 처리.", file=sys.stderr)
        return None
    # 버전 호환성
    version = cfg.get("version", 1)
    if version != CONFIG_VERSION:
        print(
            f"경고: {cfg_path} version={version} 이 지원 버전 {CONFIG_VERSION} 과 다름 — "
            "현재 버전 시맨틱으로 시도 진행.",
            file=sys.stderr,
        )
    return cfg


# ---- 편의 헬퍼: 섹션별 안전한 추출 ----

def frontmatter_section(cfg: dict | None) -> dict:
    if cfg is None:
        return {}
    return cfg.get("frontmatter", {}) or {}


def index_section(cfg: dict | None) -> dict:
    if cfg is None:
        return {}
    return cfg.get("index", {}) or {}


def lazy_load_triggers_section(cfg: dict | None) -> dict:
    if cfg is None:
        return {}
    return cfg.get("lazy_load_triggers", {}) or {}


def index_groups(cfg: dict | None) -> list[dict]:
    return index_section(cfg).get("groups", []) or []


def cross_reference_config(cfg: dict | None) -> dict:
    return index_section(cfg).get("cross_reference", {}) or {}


def evolution_graph_config(cfg: dict | None) -> dict:
    return index_section(cfg).get("evolution_graph", {}) or {}


def lazy_load_detect_rules(cfg: dict | None) -> list[dict]:
    return lazy_load_triggers_section(cfg).get("detect", []) or []


def lazy_load_override_hardcoded(cfg: dict | None) -> list[str]:
    return lazy_load_triggers_section(cfg).get("override_hardcoded", []) or []


# CLI 진단 — config 가 정상 로드되는지 확인
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="대상 코드베이스 경로")
    args = ap.parse_args()
    target = Path(args.target).resolve()
    cfg = load_config(target)
    if cfg is None:
        print(f"config 없음 또는 파싱 실패 — {target / CONFIG_FILE_NAME}")
        sys.exit(0)
    print(json.dumps(cfg, ensure_ascii=False, indent=2))
