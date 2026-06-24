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
  },
  "rubric": {
    "decision_records": { "dir_hints": ["docs/design"] },
    "api_contracts":    { "build_deps": ["springdoc", "springfox"] }
  }
}

각 섹션은 *선택적* — 누락된 섹션은 빈 / 비활성으로 취급.

`rubric` 섹션 (v0.3.0+) — audit.py 채점 로직이 프로젝트 현실을 존중하도록 하는 선언:
  - decision_records.dir_hints: 의사결정 기록(ADR rule 3.2)으로 인정할 *추가* 디렉토리.
    하드코딩된 docs/adr·docs/decisions 외에, design 통합 문서 (PRD/ADR/api-doc 흡수) 를
    docs/design/ 에 두는 프로젝트가 그 디렉토리를 결정 기록 신호로 선언할 때 사용.
  - api_contracts.build_deps: API 계약(rule 4.3)으로 인정할 빌드 의존성 문자열.
    정적 openapi.yaml 대신 springdoc/springfox 처럼 *코드에서 OpenAPI 를 런타임 생성* 하는
    의존성을 빌드 매니페스트에서 감지하면 계약 문서화로 인정.

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


__all__ = [
    "load_config", "CONFIG_FILE_NAME", "CONFIG_VERSION",
    "rubric_section", "decision_record_hints", "api_contract_build_deps",
]


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
#
# 섹션 값이 잘못된 타입(예: dict 자리에 문자열, list 자리에 dict)으로 들어오면
# `... or {}` 는 truthy 비-dict 를 막지 못해 .get 호출 시 크래시한다. 아래 두
# 강제 헬퍼로 타입을 보장해 잘못된 값이 호출부로 새지 않고 빈 값 fallback 하도록 한다.

def _as_dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _as_list(v) -> list:
    return v if isinstance(v, list) else []


def frontmatter_section(cfg: dict | None) -> dict:
    if cfg is None:
        return {}
    return _as_dict(cfg.get("frontmatter"))


def index_section(cfg: dict | None) -> dict:
    if cfg is None:
        return {}
    return _as_dict(cfg.get("index"))


def lazy_load_triggers_section(cfg: dict | None) -> dict:
    if cfg is None:
        return {}
    return _as_dict(cfg.get("lazy_load_triggers"))


def index_groups(cfg: dict | None) -> list[dict]:
    return _as_list(index_section(cfg).get("groups"))


def cross_reference_config(cfg: dict | None) -> dict:
    return _as_dict(index_section(cfg).get("cross_reference"))


def evolution_graph_config(cfg: dict | None) -> dict:
    return _as_dict(index_section(cfg).get("evolution_graph"))


def lazy_load_detect_rules(cfg: dict | None) -> list[dict]:
    return _as_list(lazy_load_triggers_section(cfg).get("detect"))


def lazy_load_override_hardcoded(cfg: dict | None) -> list[str]:
    return _as_list(lazy_load_triggers_section(cfg).get("override_hardcoded"))


# ---- rubric 채점 조정 (v0.3.0+) ----

def rubric_section(cfg: dict | None) -> dict:
    if cfg is None:
        return {}
    return _as_dict(cfg.get("rubric"))


def decision_record_hints(cfg: dict | None) -> list[str]:
    """ADR rule(3.2) 에서 의사결정 기록으로 인정할 *추가* 디렉토리 (예: docs/design)."""
    dr = _as_dict(rubric_section(cfg).get("decision_records"))
    return [h.strip("/").lower().replace("\\", "/")
            for h in _as_list(dr.get("dir_hints")) if isinstance(h, str)]


def api_contract_build_deps(cfg: dict | None) -> list[str]:
    """API 계약 rule(4.3) 에서 인정할 빌드 의존성 문자열 (예: springdoc)."""
    ac = _as_dict(rubric_section(cfg).get("api_contracts"))
    return [d.lower() for d in _as_list(ac.get("build_deps")) if isinstance(d, str)]


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
