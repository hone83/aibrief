"""
렌더러 — 선별된 항목을 JSON / 웹페이지 / 메일 HTML 세 가지로 내보낸다.

템플릿 엔진(Jinja2 등)을 안 쓰는 이유는 의존성을 하나라도 줄이기 위해서다.
페이지가 한 종류뿐이고 구조가 고정이라, 문자열 조립으로 충분하다.
대신 사용자 입력이 들어가는 자리마다 html.escape를 반드시 통과시킨다.
피드 제목에 <script>가 들어 있어도 그대로 실행되지 않도록.

메일 HTML은 웹 HTML과 완전히 따로 만든다.
메일 클라이언트는 CSS를 거의 지원하지 않아서 인라인 스타일과 표 레이아웃만 쓴다.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from .models import Brief, Item
from .score import importance_stars

CATEGORY_LABELS = {
    "model_release": "모델 출시",
    "major_update": "업데이트",
    "benchmark": "리뷰·벤치마크",
    "workflow": "워크플로우",
    "opensource": "오픈소스·툴",
    "industry": "산업·규제",
    "minor": "기타",
}

CATEGORY_ORDER = ["model_release", "major_update", "benchmark",
                  "workflow", "opensource", "industry", "minor"]

TIER_LABELS = {"T0": "공식", "T1": "연구", "T2": "커뮤니티", "T3": "미디어", "T4": "영상"}


def e(text: str) -> str:
    """HTML 이스케이프. 모든 외부 문자열은 이걸 통과해야 한다."""
    return html.escape(str(text), quote=True)


# ==========================================================================
#  웹페이지
# ==========================================================================

PAGE_CSS = """
:root{--paper:#F4F6F2;--surface:#fff;--surface2:#EAEEE8;--line:#D3DACF;--ink:#141917;
--ink2:#3B4642;--muted:#6A7A73;--accent:#1F6F5C;--accent-ink:#17564A;--wash:#E3EFEA;--clay:#A8512F}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--paper:#101413;--surface:#171D1B;
--surface2:#1E2624;--line:#2C3634;--ink:#E7ECE8;--ink2:#C2CCC7;--muted:#8B9A94;--accent:#4BA88E;
--accent-ink:#6FC4AB;--wash:#16302A;--clay:#D08663}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);line-height:1.7;
font-family:"IBM Plex Sans KR","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif;
-webkit-font-smoothing:antialiased}
.wrap{max-width:760px;margin:0 auto;padding:0 20px 80px}
header{padding:44px 0 24px;border-bottom:1px solid var(--line);display:flex;flex-direction:column;gap:10px}
.date{font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);
font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
h1{font-size:clamp(26px,5vw,36px);margin:0;letter-spacing:-.02em;line-height:1.2}
.sub{color:var(--muted);font-size:14px;font-variant-numeric:tabular-nums}
nav.jump{display:flex;flex-wrap:wrap;gap:6px;padding-top:8px}
nav.jump a{font-size:12px;padding:3px 9px;border:1px solid var(--line);border-radius:2px;
color:var(--muted);text-decoration:none}
nav.jump a:hover{border-color:var(--accent);color:var(--accent)}
section{padding-top:36px;display:flex;flex-direction:column;gap:14px}
h2{font-size:13px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin:0;
font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-weight:500}
.tldr{background:var(--wash);border-left:2px solid var(--accent);padding:18px 20px;
display:flex;flex-direction:column;gap:8px}
.tldr p{margin:0;font-size:16.5px;line-height:1.65;color:var(--ink)}
ol.heads{margin:0;padding:0;list-style:none;counter-reset:h;display:flex;flex-direction:column;gap:2px}
ol.heads li{counter-increment:h;display:grid;grid-template-columns:26px 1fr;gap:10px;
padding:11px 0;border-bottom:1px solid var(--line)}
ol.heads li::before{content:counter(h);font-family:ui-monospace,monospace;font-size:12px;
color:var(--muted);padding-top:4px}
ol.heads a{color:var(--ink);text-decoration:none;font-weight:500;line-height:1.45}
ol.heads a:hover{color:var(--accent-ink)}
.hmeta{font-size:12px;color:var(--muted);display:flex;gap:8px;flex-wrap:wrap;margin-top:3px}
.card{background:var(--surface);border:1px solid var(--line);padding:18px 20px;
display:flex;flex-direction:column;gap:9px}
.card h3{margin:0;font-size:17px;line-height:1.45;letter-spacing:-.01em}
.card h3 a{color:var(--ink);text-decoration:none}
.card h3 a:hover{color:var(--accent-ink)}
.orig{font-size:13px;color:var(--muted);line-height:1.5}
.meta{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:11px}
.badge{font-family:ui-monospace,monospace;font-size:10.5px;letter-spacing:.06em;padding:2px 6px;
border:1px solid var(--line);color:var(--muted);border-radius:2px;white-space:nowrap}
.badge.t0{color:var(--accent);border-color:var(--accent);background:var(--wash)}
.badge.cat{color:var(--ink2)}
.stars{color:var(--accent);letter-spacing:.1em}
.summary{font-size:14.5px;color:var(--ink2);margin:0;line-height:1.65}
ul.bullets{margin:2px 0 0;padding:0;list-style:none;display:flex;flex-direction:column;gap:5px}
ul.bullets li{position:relative;padding-left:15px;font-size:13.5px;color:var(--ink2);line-height:1.6}
ul.bullets li::before{content:"";position:absolute;left:1px;top:10px;width:5px;height:1px;
background:var(--accent)}
details.rel{font-size:13px}
details.rel summary{cursor:pointer;color:var(--muted);list-style:none}
details.rel summary::-webkit-details-marker{display:none}
details.rel summary::before{content:"+ ";color:var(--accent)}
details.rel[open] summary::before{content:"− "}
details.rel ul{margin:8px 0 0;padding-left:16px;display:flex;flex-direction:column;gap:5px}
details.rel a{color:var(--muted)}
.report{margin-top:44px;padding-top:20px;border-top:1px solid var(--line);font-size:12.5px;
color:var(--muted)}
.report table{border-collapse:collapse;width:100%;margin-top:10px;font-variant-numeric:tabular-nums}
.report td{padding:3px 8px 3px 0;border-bottom:1px solid var(--line)}
.report .fail{color:var(--clay)}
.empty{padding:40px 0;color:var(--muted);text-align:center}
a:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
"""


def _card_html(item: Item, top_score: float) -> str:
    stars = "★" * importance_stars(item, top_score) + "☆" * (3 - importance_stars(item, top_score))
    tier_cls = " t0" if item.tier == "T0" else ""
    parts = [
        '<article class="card" id="i-%s">' % e(item.uid),
        '<div class="meta">',
        '<span class="badge%s">%s · %s</span>' % (tier_cls, e(item.tier), e(TIER_LABELS.get(item.tier, ""))),
        '<span class="badge cat">%s</span>' % e(CATEGORY_LABELS.get(item.category, item.category)),
        '<span class="badge">%s</span>' % e(item.source_name),
        '<span class="badge">%s KST</span>' % item.published_kst.strftime("%m/%d %H:%M"),
        '<span class="stars" title="중요도">%s</span>' % stars,
        "</div>",
        # 큰 제목은 한국어. 번역이 없으면 원제가 그대로 온다 (display_title이 처리).
        '<h3><a href="%s" target="_blank" rel="noopener">%s</a></h3>'
        % (e(item.url), e(item.display_title)),
    ]
    # 원제 병기 — 모델명·버전을 원문으로 확인하고 검색할 수 있어야 한다
    if item.translated:
        parts.append('<p class="orig">%s</p>' % e(item.title))

    summary = item.summary_ko or item.summary_raw
    if summary:
        parts.append('<p class="summary">%s</p>' % e(summary[:320]))

    if item.bullets:
        parts.append('<ul class="bullets">')
        parts.extend("<li>%s</li>" % e(b) for b in item.bullets)
        parts.append("</ul>")

    if item.related:
        parts.append('<details class="rel"><summary>관련 %d건</summary><ul>' % len(item.related))
        for r in item.related[:8]:
            parts.append('<li><a href="%s" target="_blank" rel="noopener">%s</a> · %s</li>'
                         % (e(r["url"]), e(r["title"][:90]), e(r["source"])))
        parts.append("</ul></details>")
    parts.append("</article>")
    return "".join(parts)


def render_page(brief: Brief, *, archive_links: list[str] | None = None) -> str:
    top = brief.cards[0].score if brief.cards else 1.0
    by_cat: dict[str, list[Item]] = {}
    for it in brief.cards:
        by_cat.setdefault(it.category, []).append(it)

    out: list[str] = [
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">",
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta name="robots" content="noindex,nofollow">',
        "<title>비주얼 AI 브리핑 · %s</title>" % e(brief.date_kst),
        '<link rel="manifest" href="manifest.json">',
        "<style>%s</style></head><body><div class=\"wrap\">" % PAGE_CSS,
        "<header>",
        '<span class="date">%s</span>' % e(brief.date_kst),
        "<h1>비주얼 AI 브리핑</h1>",
        '<span class="sub">수집 %d건 → 선별 %d건 · 소스 %d개 중 %d개 정상</span>' % (
            brief.stats.get("collected", 0), len(brief.cards),
            brief.stats.get("sources_total", 0), brief.stats.get("sources_ok", 0)),
        '<nav class="jump">',
    ]
    for cat in CATEGORY_ORDER:
        if cat in by_cat:
            out.append('<a href="#c-%s">%s %d</a>' % (cat, e(CATEGORY_LABELS[cat]), len(by_cat[cat])))
    out.append("</nav></header>")

    if not brief.cards:
        out.append('<p class="empty">오늘은 창(窓)에 걸린 항목이 없습니다. 하단 수집 리포트를 확인하세요.</p>')

    if brief.tldr:
        out.append('<section><h2>오늘 한눈에</h2><div class="tldr">')
        out.extend("<p>%s</p>" % e(line) for line in brief.tldr)
        out.append("</div></section>")

    if brief.headlines:
        out.append('<section><h2>헤드라인</h2><ol class="heads">')
        for it in brief.headlines:
            out.append(
                '<li><div><a href="#i-%s">%s</a>'
                '<div class="hmeta"><span>%s</span><span>%s</span><span>%s</span></div></div></li>'
                % (e(it.uid), e(it.display_title), e(it.source_name),
                   e(CATEGORY_LABELS.get(it.category, "")),
                   it.published_kst.strftime("%m/%d %H:%M"))
            )
        out.append("</ol></section>")

    for cat in CATEGORY_ORDER:
        items = by_cat.get(cat)
        if not items:
            continue
        out.append('<section id="c-%s"><h2>%s</h2>' % (cat, e(CATEGORY_LABELS[cat])))
        out.extend(_card_html(it, top) for it in items)
        out.append("</section>")

    # 수집 리포트 — 조용한 실패를 막는 장치
    out.append('<div class="report"><strong>수집 리포트</strong><table>')
    for r in brief.reports:
        cls = ' class="fail"' if not r.ok else ""
        detail = e(r.error) if not r.ok else ("%d건 → %d건" % (r.collected, r.kept))
        out.append("<tr%s><td>%s</td><td>%s</td><td>%s</td><td>%dms</td></tr>"
                   % (cls, e(r.tier), e(r.source_name), detail, r.elapsed_ms))
    out.append("</table>")

    if brief.dropped:
        by_reason: dict[str, list[dict]] = {}
        for row in brief.dropped:
            by_reason.setdefault(row["reason"].split("(")[0].strip(), []).append(row)
        out.append('<details class="rel"><summary>필터에 걸린 %d건 보기</summary>' % len(brief.dropped))
        for reason, rows in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
            out.append('<p style="margin:10px 0 4px"><strong>%s</strong> %d건</p><ul>'
                       % (e(reason), len(rows)))
            for row in rows[:25]:
                out.append('<li><a href="%s" target="_blank" rel="noopener">%s</a> · %s</li>'
                           % (e(row["url"]), e(row["title"][:90]), e(row["source"])))
            if len(rows) > 25:
                out.append("<li>… %d건 더</li>" % (len(rows) - 25))
            out.append("</ul>")
        out.append("</details>")

    if archive_links:
        out.append("<p>지난 브리핑: " + " · ".join(
            '<a href="archive/%s.html">%s</a>' % (e(d), e(d)) for d in archive_links[:14]
        ) + "</p>")
    out.append("</div></div></body></html>")
    return "".join(out)


# ==========================================================================
#  메일
# ==========================================================================

def render_email(brief: Brief) -> str:
    """
    메일 클라이언트는 <style> 블록도, flex도, 대부분의 최신 CSS도 무시한다.
    그래서 여기서는 표와 인라인 스타일만 쓴다. 20년 전 HTML처럼 보이는 게 정상이다.
    """
    S = {
        "body": "margin:0;padding:0;background:#f4f6f2;",
        "wrap": "max-width:600px;margin:0 auto;padding:24px 16px;"
                "font-family:-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;"
                "color:#141917;line-height:1.65;",
        "date": "font-size:12px;letter-spacing:.1em;color:#1F6F5C;text-transform:uppercase;",
        "h1": "font-size:24px;margin:6px 0 4px;letter-spacing:-.02em;",
        "sub": "font-size:13px;color:#6A7A73;margin:0 0 20px;",
        "h2": "font-size:12px;letter-spacing:.12em;color:#1F6F5C;text-transform:uppercase;"
              "margin:26px 0 10px;",
        "item": "padding:12px 0;border-bottom:1px solid #D3DACF;",
        "title": "font-size:16px;font-weight:600;color:#141917;text-decoration:none;",
        "meta": "font-size:11px;color:#6A7A73;margin-top:4px;",
        "sum": "font-size:13.5px;color:#3B4642;margin:6px 0 0;",
        "foot": "font-size:11px;color:#6A7A73;margin-top:28px;padding-top:14px;"
                "border-top:1px solid #D3DACF;",
    }
    out = ['<html><body style="%s"><div style="%s">' % (S["body"], S["wrap"]),
           '<div style="%s">%s</div>' % (S["date"], e(brief.date_kst)),
           '<h1 style="%s">비주얼 AI 브리핑</h1>' % S["h1"],
           '<p style="%s">수집 %d건 → 선별 %d건</p>' % (
               S["sub"], brief.stats.get("collected", 0), len(brief.cards))]

    if brief.tldr:
        out.append('<div style="%s">오늘 한눈에</div>' % S["h2"])
        out.append('<div style="background:#E3EFEA;border-left:2px solid #1F6F5C;'
                   'padding:14px 16px;margin-bottom:6px">')
        for line in brief.tldr:
            out.append('<p style="margin:0 0 6px;font-size:15px;line-height:1.6;color:#141917">'
                       '%s</p>' % e(line))
        out.append("</div>")

    if brief.headlines:
        out.append('<div style="%s">헤드라인</div>' % S["h2"])
        for n, it in enumerate(brief.headlines, 1):
            out.append('<div style="%s"><a href="%s" style="%s">%d. %s</a>'
                       '<div style="%s">%s · %s</div></div>'
                       % (S["item"], e(it.url), S["title"], n, e(it.display_title), S["meta"],
                          e(it.source_name), e(CATEGORY_LABELS.get(it.category, ""))))

    rest = brief.cards[len(brief.headlines):]
    if rest:
        out.append('<div style="%s">그 밖에</div>' % S["h2"])
        for it in rest:
            out.append('<div style="%s"><a href="%s" style="%s">%s</a>'
                       '<div style="%s">%s · %s</div>'
                       % (S["item"], e(it.url), S["title"], e(it.display_title), S["meta"],
                          e(it.source_name), e(CATEGORY_LABELS.get(it.category, ""))))
            body = it.summary_ko or it.summary_raw
            if body:
                out.append('<p style="%s">%s</p>' % (S["sum"], e(body[:180])))
            out.append("</div>")

    failed = [r for r in brief.reports if not r.ok]
    out.append('<div style="%s">소스 %d개 중 %d개 정상.%s</div>' % (
        S["foot"], brief.stats.get("sources_total", 0), brief.stats.get("sources_ok", 0),
        (" 실패: " + ", ".join(e(r.source_name) for r in failed[:6])) if failed else ""))
    out.append("</div></body></html>")
    return "".join(out)


# ==========================================================================
#  파일 쓰기
# ==========================================================================

MANIFEST = {
    "name": "비주얼 AI 브리핑",
    "short_name": "AI 브리핑",
    "start_url": "./index.html",
    "display": "standalone",
    "background_color": "#F4F6F2",
    "theme_color": "#1F6F5C",
    "icons": [],
}


def write_outputs(brief: Brief, root: Path) -> dict[str, Path]:
    """data/(원본 JSON) + docs/(공개 사이트) 두 곳에 나눠 쓴다."""
    data_dir = root / "data"
    docs_dir = root / "docs"
    archive_dir = docs_dir / "archive"
    for d in (data_dir, docs_dir, archive_dir):
        d.mkdir(parents=True, exist_ok=True)

    json_path = data_dir / f"{brief.date_kst}.json"
    json_path.write_text(json.dumps(brief.to_dict(), ensure_ascii=False, indent=2),
                         encoding="utf-8")

    past = sorted((p.stem for p in data_dir.glob("*.json")), reverse=True)
    page = render_page(brief, archive_links=[d for d in past if d != brief.date_kst])

    index_path = docs_dir / "index.html"
    index_path.write_text(page, encoding="utf-8")
    (archive_dir / f"{brief.date_kst}.html").write_text(page, encoding="utf-8")
    (docs_dir / "manifest.json").write_text(json.dumps(MANIFEST, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    (docs_dir / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    # 깃허브 Pages는 기본적으로 Jekyll이라는 옛 블로그 엔진을 한 번 거쳐서 사이트를
    # 만든다. 이 빈 파일이 있으면 그 단계를 통째로 건너뛴다.
    # 우리 docs/는 이미 완성된 HTML이라 거칠 이유가 없고, 건너뛰면 배포가 더 빠르고
    # 밑줄(_)로 시작하는 파일이 사라지는 사고도 원천적으로 막힌다.
    (docs_dir / ".nojekyll").write_text("", encoding="utf-8")

    return {"json": json_path, "index": index_path}
