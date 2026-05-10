#!/usr/bin/env python3
"""
audit.json을 셀프 컨테인드 HTML 대시보드로 렌더링.

외부 CSS/JS/폰트 의존성 없음. 점수 게이지와 카테고리 바는 inline SVG.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path


GRADE_COLORS = {
    "에이전트 자율 (Agentic-ready)": "#16a34a",
    "AI 맥시멀리스트 (AI-maximalist)": "#65a30d",
    "AI 활용 (AI-enabled)": "#ca8a04",
    "AI 인지 (AI-aware)": "#ea580c",
    "AI 미인지 (AI-blind)": "#dc2626",
}


def gauge_svg(score: int, color: str) -> str:
    r = 80
    circumference = 2 * 3.14159 * r
    pct = max(0, min(100, score))
    dash = circumference * pct / 100
    return f'''<svg viewBox="0 0 200 200" width="200" height="200" role="img" aria-label="점수 게이지">
  <circle cx="100" cy="100" r="{r}" stroke="#e5e7eb" stroke-width="20" fill="none"/>
  <circle cx="100" cy="100" r="{r}" stroke="{color}" stroke-width="20" fill="none"
          stroke-dasharray="{dash:.2f} {circumference - dash:.2f}"
          stroke-dashoffset="{circumference / 4:.2f}" transform="rotate(-90 100 100)"
          stroke-linecap="round"/>
  <text x="100" y="100" text-anchor="middle" dominant-baseline="central"
        font-size="44" font-weight="700" fill="#111827">{score}</text>
  <text x="100" y="130" text-anchor="middle" dominant-baseline="central"
        font-size="14" fill="#6b7280">/ 100</text>
</svg>'''


def bar_svg(score: int, max_score: int, color: str) -> str:
    pct = (score / max_score * 100) if max_score else 0
    return f'''<svg viewBox="0 0 100 8" preserveAspectRatio="none" width="100%" height="8" aria-hidden="true">
  <rect x="0" y="0" width="100" height="8" rx="4" fill="#e5e7eb"/>
  <rect x="0" y="0" width="{pct:.2f}" height="8" rx="4" fill="{color}"/>
</svg>'''


def category_color(score: int, max_score: int) -> str:
    pct = (score / max_score * 100) if max_score else 0
    if pct >= 90:
        return "#16a34a"
    if pct >= 70:
        return "#65a30d"
    if pct >= 50:
        return "#ca8a04"
    if pct >= 25:
        return "#ea580c"
    return "#dc2626"


def read_history(audit_path: Path) -> list[dict]:
    """T-12: `.ai-ready/history/*.json` 시계열 데이터 적재."""
    hist_dir = audit_path.parent / "history"
    if not hist_dir.is_dir():
        return []
    points = []
    for p in sorted(hist_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        ts = data.get("timestamp_local") or data.get("timestamp")
        score = data.get("total_score")
        if ts is None or score is None:
            continue
        points.append({"timestamp": ts, "total_score": score})
    return points


def render_sparkline(history: list[dict], color: str) -> str:
    """T-12: 점수 추이 sparkline (>=2 개 데이터 포인트 필요)."""
    if len(history) < 2:
        if len(history) == 1:
            return ('<p class="hist-empty">_점수 추이는 다음 회차부터 표시됩니다 (현재 1회 기록)._</p>')
        return ""
    width, height = 280, 56
    pad = 6
    scores = [pt["total_score"] for pt in history]
    smin, smax = min(scores), max(scores)
    span = max(smax - smin, 5)
    n = len(scores)
    pts = []
    for i, s in enumerate(scores):
        x = pad + (width - 2 * pad) * (i / max(n - 1, 1))
        y = pad + (height - 2 * pad) * (1 - (s - smin) / span)
        pts.append((x, y))
    polyline = '<polyline points="{}" fill="none" stroke="{}" stroke-width="2" stroke-linejoin="round"/>'.format(
        " ".join(f"{x:.1f},{y:.1f}" for x, y in pts), color,
    )
    last_x, last_y = pts[-1]
    last_dot = f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3.5" fill="{color}"/>'
    delta = scores[-1] - scores[0]
    sign = "+" if delta >= 0 else ""
    delta_color = "#16a34a" if delta > 0 else ("#dc2626" if delta < 0 else "#6b7280")
    return f'''<div class="sparkline">
      <svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img"
           aria-label="점수 추이">
        <rect x="0" y="0" width="{width}" height="{height}" fill="#f9fafb" rx="6"/>
        {polyline}
        {last_dot}
      </svg>
      <p class="trend">최근 {n}회: <b>{scores[0]} → {scores[-1]}</b>
        <span style="color:{delta_color}">({sign}{delta})</span></p>
    </div>'''


def render_html(audit: dict, history: list[dict] | None = None) -> str:
    grade = audit.get("grade", "AI 미인지 (AI-blind)")
    color = GRADE_COLORS.get(grade, "#6b7280")
    target = html.escape(audit.get("target", ""))
    # T-5: 로컬 + UTC 둘 다 보여주기
    ts_local = html.escape(audit.get("timestamp_local", ""))
    ts_utc = html.escape(audit.get("timestamp", ""))
    timestamp = f"{ts_local} (로컬) · {ts_utc} (UTC)" if ts_local else ts_utc
    total = audit.get("total_score", 0)
    module_count = audit.get("module_count", 0)
    doc_count = audit.get("claude_doc_count", 0)
    sparkline_html = render_sparkline(history or [], color)

    cat_cards = []
    for cat in audit["categories"]:
        cat_score = cat["score"]
        cat_max = cat["max"]
        cat_color = category_color(cat_score, cat_max)
        rules_html = []
        for rule in cat["rules"]:
            mark = "✅" if rule["passed"] else ("🟡" if rule["points"] > 0 else "❌")
            evidence_str = ", ".join(html.escape(e) for e in rule["evidence"][:5])
            note_str = html.escape(rule.get("note", ""))
            rules_html.append(f'''
              <li>
                <div class="rule-head">
                  <span class="mark">{mark}</span>
                  <span class="rule-name">{html.escape(rule["name"])}</span>
                  <span class="rule-points">{rule["points"]} / {rule["max"]}</span>
                </div>
                {f'<div class="evidence">📁 {evidence_str}</div>' if evidence_str else ''}
                {f'<div class="note">📝 {note_str}</div>' if note_str else ''}
              </li>''')
        cat_cards.append(f'''
          <div class="cat-card">
            <div class="cat-head">
              <h3>{cat["id"]}. {html.escape(cat["name"])}</h3>
              <span class="cat-score" style="color:{cat_color}">{cat_score} / {cat_max}</span>
            </div>
            {bar_svg(cat_score, cat_max, cat_color)}
            <ul class="rules">{''.join(rules_html)}</ul>
          </div>''')

    actions = audit.get("actions", [])
    if actions:
        action_rows = []
        for i, a in enumerate(actions[:15], 1):
            action_rows.append(f'''
              <tr>
                <td class="rank">{i}</td>
                <td><b>{a["roi_score"]}</b></td>
                <td>{a["effort_minutes"]}분</td>
                <td>{html.escape(a["category"])}</td>
                <td>{html.escape(a["action"])}</td>
              </tr>''')
        actions_html = f'''
          <section>
            <h2>ROI 우선순위 액션</h2>
            <table class="actions">
              <thead><tr><th>#</th><th>ROI</th><th>소요</th><th>카테고리</th><th>액션</th></tr></thead>
              <tbody>{''.join(action_rows)}</tbody>
            </table>
          </section>'''
    else:
        actions_html = '<section><h2>ROI 우선순위 액션</h2><p class="empty">모든 카테고리 만점입니다.</p></section>'

    modules_html = ""
    if audit.get("modules"):
        docs = set(audit.get("claude_docs", []))
        rows = []
        for m in audit["modules"][:30]:
            if m == ".":
                continue
            covered = any(doc.startswith(m + "/CLAUDE.md") or doc.startswith(m + "/AGENTS.md")
                          for doc in docs)
            mark = "✅" if covered else "⚪"
            rows.append(f'<tr><td>{mark}</td><td><code>{html.escape(m)}</code></td></tr>')
        if rows:
            extra = ""
            if len(audit["modules"]) > 30:
                extra = f"<p>… 외 {len(audit['modules']) - 30}개 모듈</p>"
            modules_html = f'''
            <section>
              <h2>모듈 커버리지</h2>
              <table class="modules">
                <thead><tr><th></th><th>모듈</th></tr></thead>
                <tbody>{''.join(rows)}</tbody>
              </table>
              {extra}
            </section>'''

    return f'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<title>AI 준비도 감사 대시보드</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Apple SD Gothic Neo", "Pretendard", "Noto Sans KR", Roboto, "Helvetica Neue", Arial, sans-serif;
       background: #f9fafb; color: #111827; line-height: 1.5; }}
.container {{ max-width: 1100px; margin: 0 auto; padding: 32px 24px; }}
header {{ display: flex; align-items: center; gap: 32px; flex-wrap: wrap; padding-bottom: 24px;
         border-bottom: 1px solid #e5e7eb; margin-bottom: 32px; }}
header .summary {{ flex: 1; min-width: 280px; }}
header h1 {{ margin: 0 0 8px 0; font-size: 28px; }}
header p {{ margin: 4px 0; color: #6b7280; font-size: 14px; }}
header .grade {{ display: inline-block; padding: 4px 12px; border-radius: 999px; color: #fff;
                font-weight: 600; font-size: 13px; background: {color}; margin-top: 8px; }}
header .stats {{ margin-top: 12px; display: flex; gap: 24px; }}
header .stats div {{ font-size: 14px; }}
header .stats b {{ display: block; font-size: 22px; }}
section {{ margin: 32px 0; }}
section h2 {{ margin: 0 0 16px 0; font-size: 20px; }}
.cat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
.cat-card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px; }}
.cat-head {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }}
.cat-head h3 {{ margin: 0; font-size: 16px; }}
.cat-score {{ font-weight: 700; font-size: 16px; }}
ul.rules {{ list-style: none; padding: 0; margin: 12px 0 0 0; font-size: 13px; }}
ul.rules li {{ padding: 8px 0; border-top: 1px solid #f3f4f6; }}
ul.rules li:first-child {{ border-top: none; }}
.rule-head {{ display: flex; align-items: center; gap: 8px; }}
.rule-name {{ flex: 1; }}
.rule-points {{ color: #6b7280; font-variant-numeric: tabular-nums; }}
.evidence {{ font-size: 11px; color: #6b7280; margin-top: 4px; word-break: break-all; }}
.note {{ font-size: 11px; color: #92400e; margin-top: 4px; background: #fef3c7; padding: 4px 8px; border-radius: 4px; }}
table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden;
         border: 1px solid #e5e7eb; font-size: 14px; }}
table th, table td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #f3f4f6; }}
table th {{ background: #f9fafb; font-weight: 600; }}
table tr:last-child td {{ border-bottom: none; }}
table.actions td.rank {{ font-weight: 700; color: #6b7280; width: 32px; }}
.empty {{ color: #6b7280; font-style: italic; }}
.sparkline {{ margin-top: 16px; }}
.sparkline svg {{ display: block; }}
.sparkline .trend {{ font-size: 13px; color: #6b7280; margin: 6px 0 0 0; }}
.hist-empty {{ font-size: 12px; color: #9ca3af; margin-top: 12px; font-style: italic; }}
code {{ font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
        font-size: 13px; background: #f3f4f6; padding: 1px 6px; border-radius: 4px; }}
footer {{ margin-top: 48px; padding-top: 24px; border-top: 1px solid #e5e7eb;
          color: #6b7280; font-size: 13px; }}
</style>
</head>
<body>
  <div class="container">
    <header>
      <div>{gauge_svg(total, color)}</div>
      <div class="summary">
        <h1>AI 준비도 감사</h1>
        <p><code>{target}</code></p>
        <p>생성 시각: {timestamp}</p>
        <span class="grade">{html.escape(grade)}</span>
        <div class="stats">
          <div><b>{module_count}</b>모듈</div>
          <div><b>{doc_count}</b>CLAUDE.md 문서</div>
          <div><b>{len(actions)}</b>액션</div>
        </div>
        {sparkline_html}
      </div>
    </header>

    <section>
      <h2>카테고리별 점수</h2>
      <div class="cat-grid">
        {''.join(cat_cards)}
      </div>
    </section>

    {actions_html}

    {modules_html}

    <footer>
      주기적으로 재실행해 추이를 추적하세요. ±5점 노이즈는 정상입니다 — 절대 점수가 아닌 방향에 주목합니다.
    </footer>
  </div>
</body>
</html>
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", required=True, help="audit.json 경로")
    ap.add_argument("--out", required=True, help="dashboard.html 출력 경로")
    args = ap.parse_args()
    audit_path = Path(args.audit).resolve()
    out_path = Path(args.out).resolve()
    if not audit_path.is_file():
        print(f"오류: audit 파일이 없습니다: {audit_path}", file=sys.stderr)
        sys.exit(2)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    history = read_history(audit_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_html(audit, history), encoding="utf-8")
    print(f"생성: {out_path}")
    if history:
        print(f"  history 항목: {len(history)}개 (sparkline 표시됨)")


if __name__ == "__main__":
    main()
