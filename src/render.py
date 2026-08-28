"""
렌더러 — 선별된 항목을 JSON / 웹페이지 / 메일 HTML 세 가지로 내보낸다.

템플릿 엔진(Jinja2 등)을 안 쓰는 이유는 의존성을 하나라도 줄이기 위해서다.
페이지가 한 종류뿐이고 구조가 고정이라, 문자열 조립으로 충분하다.
대신 사용자 입력이 들어가는 자리마다 html.escape를 반드시 통과시킨다.
피드 제목에 <script>가 들어 있어도 그대로 실행되지 않도록.

화면 구조 (v12에서 바뀐 부분):
  - 첫 화면은 '오늘' 탭 하나. 위에 오늘의 흐름 + 헤드라인 5건이 한 덩어리로 있고
    (예전에는 요약과 헤드라인이 따로 있어서 같은 말을 두 번 읽어야 했다),
    그 아래에 나머지 카드가 타일로 깔린다. 목표는 스크롤 없이 하루치가 보이는 것.
  - 항목을 누르면 세부 화면이 덮는다. 페이지를 새로 부르지 않고 주소의 #만 바꾼다.
    그래서 폰의 뒤로가기가 그대로 '목록으로'가 된다.
  - 세부 화면은 요약 + 원문 열기 버튼. 번역이 없으면 원문 요약이 그 자리에 들어간다.
  - '순위' 탭은 모델 순위표, '모델' 탭은 이름별 지난 기사. 뉴스와 갱신 주기가 달라서 나눴다.
  - 검색창은 늘 헤더에 있고, 결과는 헤더 아래로 펼쳐진다. 달력은 날짜 버튼 아래 팝오버.
    둘 다 다른 화면으로 넘어가지 않아서 보던 자리를 잃지 않는다.

메일 HTML은 웹 HTML과 완전히 따로 만든다.
메일 클라이언트는 CSS를 거의 지원하지 않아서 인라인 스타일과 표 레이아웃만 쓴다.
그래서 메일은 밝은 배경이다 — 다크 메일을 지원하지 않는 클라이언트가 아직 많다.
"""

from __future__ import annotations

import datetime as dt
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

# 카테고리마다 점 색을 다르게 준다. 강조색(호박색)은 '누를 수 있는 것'에만 쓰고,
# 분류는 채도를 낮춘 색점으로만 구분한다 — 화면 전체가 알록달록해지지 않도록.
CATEGORY_DOT = {
    "model_release": "#FFCE4A",
    "major_update": "#8AB4F8",
    "benchmark": "#C4A0F0",
    "workflow": "#6FD3B8",
    "opensource": "#7FD16C",
    "industry": "#E89B72",
    "minor": "#7C8A95",
}

TIER_LABELS = {"T0": "공식", "T1": "연구", "T2": "커뮤니티", "T3": "미디어", "T4": "영상"}


def e(text: str) -> str:
    """HTML 이스케이프. 모든 외부 문자열은 이걸 통과해야 한다."""
    return html.escape(str(text), quote=True)


def _when(iso: str) -> str:
    """'08.27 14:20' 형태로. 날짜가 깨져 있어도 화면을 망가뜨리지 않는다."""
    try:
        return dt.datetime.fromisoformat(iso).strftime("%m.%d %H:%M")
    except (ValueError, TypeError):
        return ""


def _stars(n: int) -> str:
    return "●" * n + "○" * (3 - n)


# ==========================================================================
#  스타일 — 어두운 바탕에 한 가지 강조색
# ==========================================================================

PAGE_CSS = """
:root{
  --ground:#0B0E10; --surface:#14181C; --surface-2:#1B2127; --surface-3:#232B32;
  --line:#262E35; --line-soft:#1E252B;
  --ink:#F2F5F7; --ink-2:#B7C2CB; --muted:#7C8A95;
  --accent:#FFCE4A; --accent-ink:#0B0E10; --accent-soft:#3A2F12;
  --up:#4ADE80; --down:#F87171;
  --f-body:"IBM Plex Sans KR","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif;
  --f-mono:"IBM Plex Mono",SFMono-Regular,Consolas,monospace;
}
*{box-sizing:border-box;}
/* display를 지정한 요소에는 hidden 속성이 먹지 않는다(작성자 스타일이 이긴다).
   달력 팝오버가 닫히지 않던 원인이라 전역으로 못박아 둔다. */
[hidden]{display:none !important;}
html{-webkit-text-size-adjust:100%;}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:var(--f-body); font-size:16px; line-height:1.65;
  -webkit-font-smoothing:antialiased;
}
body[data-detail]{overflow:hidden;}
a{color:inherit;}
.wrap{max-width:1080px; margin:0 auto; padding:0 18px 72px;}

/* ---------- 상단 바 ---------- */
.top{
  position:sticky; top:0; z-index:30; background:rgba(11,14,16,.92);
  backdrop-filter:blur(8px); border-bottom:1px solid var(--line);
}
.top-in{
  max-width:1080px; margin:0 auto; padding:12px 18px;
  display:flex; align-items:center; gap:14px; flex-wrap:wrap;
}
.brand{display:flex; flex-direction:column; line-height:1.2; margin-right:auto;}
.brand .d{font-family:var(--f-mono); font-size:19px; font-weight:600; letter-spacing:.02em;}
.brand .s{font-family:var(--f-mono); font-size:10.5px; letter-spacing:.14em;
          text-transform:uppercase; color:var(--muted);}
.tabs{display:flex; gap:4px; background:var(--surface-2); padding:3px; border-radius:999px;}
.tabs button{
  font:inherit; font-size:13.5px; font-weight:500; color:var(--ink-2);
  background:none; border:0; padding:6px 16px; border-radius:999px; cursor:pointer;
}
.tabs button[aria-selected="true"]{background:var(--accent); color:var(--accent-ink); font-weight:600;}
/* 검색은 늘 보이게 둔다. 버튼 뒤에 숨기면 "찾아볼 수 있다"는 사실 자체를 잊는다. */
.find{display:flex; gap:6px; align-items:center; position:relative;}
#q{
  width:210px; font:inherit; font-size:14px; color:var(--ink);
  background:var(--surface-2); border:1px solid var(--line); border-radius:8px;
  padding:8px 12px;
}
#q::placeholder{color:var(--muted);}
#q:focus{border-color:var(--accent); outline:none; background:var(--surface);}
.calbtn{
  font:inherit; font-size:12.5px; font-family:var(--f-mono); letter-spacing:.04em;
  background:var(--surface-2); color:var(--ink-2);
  border:1px solid var(--line); border-radius:8px; padding:8px 12px; cursor:pointer;
  white-space:nowrap;
}
.calbtn:hover, .calbtn[aria-expanded="true"]{border-color:var(--accent); color:var(--ink);}

/* 검색 결과는 헤더 바로 아래로 펼친다. 다른 화면으로 넘어가지 않으므로
   지금 보던 자리를 잃지 않는다. */
#results{
  position:absolute; left:0; right:0; top:100%;
  background:var(--ground); border-bottom:1px solid var(--line);
  max-height:min(70vh,560px); overflow-y:auto; box-shadow:0 18px 40px rgba(0,0,0,.5);
}
#results .res-in{max-width:1080px; margin:0 auto; padding:12px 18px 20px;}

/* 미니 달력은 날짜 버튼 아래에 붙는다 */
#calpop{
  position:absolute; right:0; top:calc(100% + 8px); width:296px; z-index:40;
  background:var(--surface); border:1px solid var(--line); border-radius:12px;
  padding:14px; box-shadow:0 18px 40px rgba(0,0,0,.55);
  display:flex; flex-direction:column; gap:10px;
}

/* ---------- 덮어쓰는 화면들(세부·검색·달력) 공통 ---------- */
.sheet{
  position:fixed; inset:0; z-index:60; background:var(--ground);
  overflow-y:auto; display:none; overscroll-behavior:contain;
}
.sheet[data-open]{display:block;}
.s-body{max-width:760px; margin:0 auto; padding:22px 18px 80px;
        display:flex; flex-direction:column; gap:16px;}

/* ---------- 검색 ---------- */
.q-note{font-family:var(--f-mono); font-size:11.5px; color:var(--muted);}
.hits{display:flex; flex-direction:column;}
.hit{
  display:block; text-decoration:none; color:inherit;
  padding:13px 2px; border-bottom:1px solid var(--line-soft);
}
.hit:hover{background:var(--surface);}
.hit .hm{font-family:var(--f-mono); font-size:10.5px; color:var(--muted);
         display:flex; gap:8px; align-items:center;}
.hit .ht{font-size:16px; font-weight:600; line-height:1.5; margin:3px 0 2px;
         word-break:keep-all; overflow-wrap:break-word;}
.hit .hs{font-size:13.5px; color:var(--ink-2); line-height:1.55;
         display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;
         overflow:hidden;}
mark{background:var(--accent-soft); color:var(--accent); padding:0 2px; border-radius:2px;}

/* ---------- 달력 ---------- */
.cal-head{display:flex; align-items:center; gap:14px;}
.cal-head .mo{font-size:15px; font-weight:600; font-variant-numeric:tabular-nums;
              margin-right:auto;}
.cal-head button{
  font:inherit; font-size:15px; background:var(--surface-2); color:var(--ink);
  border:1px solid var(--line); border-radius:8px; width:32px; height:28px; cursor:pointer;
}
.cal-head button:disabled{opacity:.3; cursor:default;}
.cal{display:grid; grid-template-columns:repeat(7,1fr); gap:3px;}
.cal .dow{font-family:var(--f-mono); font-size:10.5px; color:var(--muted);
          text-align:center; padding:4px 0;}
.cal a, .cal span{
  display:flex; align-items:center; justify-content:center;
  aspect-ratio:1/1; border-radius:6px; font-family:var(--f-mono); font-size:12.5px;
  font-variant-numeric:tabular-nums;
}
.cal span{color:#3D474F;}
.cal span.pad{visibility:hidden;}
.cal a{background:var(--surface); border:1px solid var(--line);
       color:var(--ink); text-decoration:none;}
.cal a:hover{border-color:var(--accent); color:var(--accent);}
.cal a.now{background:var(--accent); border-color:var(--accent); color:var(--accent-ink);
           font-weight:600;}

/* ---------- 모델 히스토리 ---------- */
.mgrid{display:grid; grid-template-columns:repeat(auto-fill,minmax(252px,1fr)); gap:9px;
       padding-top:22px;}
.mcard{
  display:flex; flex-direction:column; gap:7px; text-align:left; cursor:pointer;
  background:var(--surface); border:1px solid var(--line); border-radius:10px;
  padding:14px 15px; font:inherit; color:inherit;
}
.mcard:hover{border-color:var(--accent);}
.mcard .top-row{display:flex; align-items:baseline; gap:8px;}
.mcard b{font-size:16px; font-weight:600; word-break:break-word;}
.mcard .ver{
  font-family:var(--f-mono); font-size:10.5px; letter-spacing:.04em;
  color:var(--accent); border:1px solid var(--accent); border-radius:4px;
  padding:1px 6px; white-space:nowrap;
}
.mcard .hd{
  font-size:13.5px; line-height:1.55; color:var(--ink-2);
  word-break:keep-all; overflow-wrap:break-word;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;
}
.mcard .meta{font-family:var(--f-mono); font-size:10.5px; color:var(--muted); margin-top:auto;}
.mhead{display:flex; align-items:center; gap:12px; padding:22px 0 6px;}
.mhead h2{margin:0; font-size:22px; font-weight:700;}
.mhead .n{font-family:var(--f-mono); font-size:12px; color:var(--muted); margin-right:auto;}
.timeline{display:flex; flex-direction:column;}
.tl{display:grid; grid-template-columns:78px 1fr; gap:14px; padding:13px 2px;
    border-bottom:1px solid var(--line-soft); text-decoration:none; color:inherit;}
.tl:hover{background:var(--surface);}
.tl .dt{font-family:var(--f-mono); font-size:11.5px; color:var(--accent);
        font-variant-numeric:tabular-nums;}
.tl .tt{font-size:15.5px; font-weight:500; line-height:1.5;
        word-break:keep-all; overflow-wrap:break-word;}
.tl .tt, .tl .ts{display:block;}
.tl .ts{font-family:var(--f-mono); font-size:10.5px; color:var(--muted); margin-top:4px;}

/* ---------- 오늘: 핵심 덩어리 ---------- */
.lede{
  padding:28px 0 22px; border-bottom:1px solid var(--line);
  display:flex; flex-direction:column; gap:22px;
}
.flow{
  font-weight:700; font-size:clamp(21px,3vw,30px);
  line-height:1.5; letter-spacing:-.025em;
  margin:0; max-width:30ch; text-wrap:balance;
}
/* 한국어는 기본값이 글자 단위 줄바꿈이라 '몰렸고'가 '몰/렸고'로 끊긴다.
   keep-all로 어절을 지키고, 긴 영문 모델명만 예외로 쪼갠다. */
.flow, .head .t, .tile .t, .d-title, .body-text, .bul li, td.nm{
  word-break:keep-all; overflow-wrap:break-word;
}
.flow span{display:block;}
.flow span+span{color:var(--ink-2); font-size:.82em; margin-top:.35em;}
.flow.empty{color:var(--muted); font-size:20px;}

.heads{display:flex; flex-direction:column; border-top:1px solid var(--line-soft);}
.head{
  display:grid; grid-template-columns:32px 1fr auto; align-items:baseline; gap:12px;
  padding:13px 6px 13px 0; border-bottom:1px solid var(--line-soft);
  background:none; border-left:0; border-right:0; border-top:0;
  width:100%; text-align:left; font:inherit; color:inherit; cursor:pointer;
}
.head:last-child{border-bottom:none;}
.head:hover, .head:focus-visible{background:var(--surface);}
.head .n{
  font-family:var(--f-mono); font-size:12px; color:var(--accent);
  font-variant-numeric:tabular-nums;
}
.head .t{font-size:clamp(16px,2vw,19px); font-weight:600; line-height:1.45;}
.head .m{font-family:var(--f-mono); font-size:11px; color:var(--muted); white-space:nowrap;}

/* ---------- 오늘: 카드 타일 ---------- */
.sec-h{
  display:flex; align-items:baseline; gap:10px; padding:24px 0 11px;
}
.sec-h h2{
  font-family:var(--f-mono); font-size:11px; letter-spacing:.16em; text-transform:uppercase;
  color:var(--muted); font-weight:500; margin:0;
}
.sec-h .c{font-family:var(--f-mono); font-size:11px; color:var(--accent);}
.grid{display:grid; grid-template-columns:repeat(auto-fill,minmax(268px,1fr)); gap:10px;}
.tile{
  display:flex; flex-direction:column; gap:9px; text-align:left;
  background:var(--surface); border:1px solid var(--line); border-radius:10px;
  padding:15px 16px 13px; cursor:pointer; font:inherit; color:inherit;
  transition:border-color .12s, background .12s;
}
.tile:hover, .tile:focus-visible{border-color:var(--accent); background:var(--surface-2);}
.tile .cat{
  display:flex; align-items:center; gap:7px;
  font-family:var(--f-mono); font-size:10px; letter-spacing:.1em;
  text-transform:uppercase; color:var(--muted);
}
.dot{width:7px; height:7px; border-radius:50%; flex:none;}
.tile .t{font-size:16px; font-weight:600; line-height:1.5; letter-spacing:-.01em;}
.tile .m{
  margin-top:auto; font-family:var(--f-mono); font-size:10.5px; color:var(--muted);
  display:flex; gap:8px; align-items:center;
}
.tile .m .st{color:var(--accent); letter-spacing:.1em;}

/* ---------- 세부 화면 ---------- */
.detail{
  position:fixed; inset:0; z-index:60; background:var(--ground);
  overflow-y:auto; display:none; overscroll-behavior:contain;
}
.detail[data-open]{display:block;}
.sheet .d-bar{padding:11px 18px;}
.d-bar{
  position:sticky; top:0; background:rgba(11,14,16,.94); backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line); padding:11px 18px;
  display:flex; align-items:center; gap:12px;
}
.d-bar .back{
  font:inherit; font-size:13.5px; font-weight:500; color:var(--ink);
  background:var(--surface-2); border:1px solid var(--line); border-radius:8px;
  padding:6px 13px; cursor:pointer;
}
.d-bar .back:hover{border-color:var(--accent);}
.d-bar .pos{font-family:var(--f-mono); font-size:11px; color:var(--muted); margin-left:auto;}
.d-body{max-width:720px; margin:0 auto; padding:26px 18px 80px;
        display:flex; flex-direction:column; gap:18px;}
.d-meta{display:flex; align-items:center; gap:10px; flex-wrap:wrap;
        font-family:var(--f-mono); font-size:11px; color:var(--muted);}
.d-meta .st{color:var(--accent); letter-spacing:.1em;}
.d-title{
  font-weight:700; margin:0;
  font-size:clamp(23px,4vw,33px); line-height:1.38; letter-spacing:-.03em;
  text-wrap:balance;
}
.d-orig{font-size:13.5px; color:var(--muted); line-height:1.55; margin:0;}

.raw-text{font-size:15.5px; color:var(--ink-2);}
.body-text{font-size:17.5px; line-height:1.78; color:var(--ink); margin:0;}
.raw .body-text{font-size:15.5px; color:var(--ink-2); line-height:1.7;}
.bul{margin:0; padding:0; list-style:none; display:flex; flex-direction:column; gap:9px;
     border-left:2px solid var(--accent); padding-left:16px;}
.bul li{font-size:15.5px; color:var(--ink-2); line-height:1.6;}
.none{color:var(--muted); font-size:14.5px;}

.go{
  display:inline-flex; align-items:center; gap:8px; align-self:flex-start;
  background:var(--accent); color:var(--accent-ink); text-decoration:none;
  font-weight:600; font-size:15px; padding:12px 20px; border-radius:10px;
}
.go:hover{filter:brightness(1.08);}
.rel{border-top:1px solid var(--line); padding-top:16px;
     display:flex; flex-direction:column; gap:9px;}
.rel h3{font-family:var(--f-mono); font-size:10.5px; letter-spacing:.14em;
        text-transform:uppercase; color:var(--muted); margin:0; font-weight:500;}
.rel a{display:flex; flex-direction:column; gap:3px; font-size:14.5px; color:var(--ink-2);
       text-decoration:none; line-height:1.5; padding:8px 0;
       border-bottom:1px solid var(--line-soft);}
.rel a:hover{color:var(--accent);}
.rel a .src{font-family:var(--f-mono); font-size:11px; color:var(--muted);}

/* ---------- 순위 ---------- */
.boards{display:flex; gap:6px; flex-wrap:wrap; padding:26px 0 16px;}
.boards button{
  font:inherit; font-size:13px; background:var(--surface); color:var(--ink-2);
  border:1px solid var(--line); border-radius:999px; padding:7px 15px; cursor:pointer;
}
.boards button[aria-selected="true"]{
  background:var(--accent); color:var(--accent-ink); border-color:var(--accent); font-weight:600;
}
.board{display:none;}
.board[data-open]{display:block;}
.tblwrap{overflow-x:auto; border:1px solid var(--line); border-radius:10px; background:var(--surface);}
table{border-collapse:collapse; width:100%; min-width:520px; font-size:14px;}
th,td{padding:11px 14px; text-align:left; border-bottom:1px solid var(--line-soft);}
thead th{
  font-family:var(--f-mono); font-size:10px; letter-spacing:.13em; text-transform:uppercase;
  color:var(--muted); font-weight:500; background:var(--surface-2); white-space:nowrap;
}
tbody tr:last-child td{border-bottom:none;}
td.r{font-family:var(--f-mono); color:var(--muted); font-variant-numeric:tabular-nums; width:38px;}
td.nm{font-weight:600;}
td.nm small{display:block; font-weight:400; font-size:12px; color:var(--muted);}
td.num{font-family:var(--f-mono); font-variant-numeric:tabular-nums; text-align:right; white-space:nowrap;}
td.sc{width:132px;}
.scwrap{display:flex; align-items:center; gap:9px; justify-content:flex-end;}
.bar{height:4px; border-radius:2px; background:var(--accent); opacity:.75; flex:none;}
.barbg{flex:1; height:4px; border-radius:2px; background:var(--surface-3); position:relative;}
.barbg i{position:absolute; inset:0 auto 0 0; border-radius:2px; background:var(--accent); opacity:.8;}
td.d{font-family:var(--f-mono); font-size:12px; white-space:nowrap; width:56px;}
.up{color:var(--up);} .down{color:var(--down);}
.new{color:var(--accent-ink); background:var(--accent); font-family:var(--f-mono);
     font-size:9.5px; letter-spacing:.1em; padding:2px 5px; border-radius:3px;}
.note{color:var(--muted); font-size:14px; padding:18px 0;}
.credit{font-size:12px; color:var(--muted); padding:14px 2px 0;}
.credit a{color:var(--ink-2);}

/* 홈 화면 앱에서 어제 것을 보고 있을 때 띄우는 띠.
   앱은 한 번 연 화면을 그대로 들고 있어서, 새 브리핑이 나온 걸 스스로 알기 어렵다. */
#fresh{
  position:fixed; left:12px; right:12px; bottom:calc(12px + env(safe-area-inset-bottom));
  z-index:80; display:none; align-items:center; gap:12px;
  background:var(--accent); color:var(--accent-ink);
  border-radius:12px; padding:12px 14px; box-shadow:0 12px 30px rgba(0,0,0,.5);
  font-size:14px; font-weight:600;
}
#fresh[data-show]{display:flex;}
#fresh span{flex:1;}
#fresh button{
  font:inherit; font-weight:700; font-size:13.5px; cursor:pointer;
  background:var(--accent-ink); color:var(--accent);
  border:0; border-radius:8px; padding:8px 14px; white-space:nowrap;
}

/* ---------- 꼬리말 ---------- */
.foot{
  margin-top:44px; padding-top:18px; border-top:1px solid var(--line);
  display:flex; gap:14px; flex-wrap:wrap; align-items:center;
  font-family:var(--f-mono); font-size:11px; color:var(--muted);
}
.foot button{
  font:inherit; background:none; border:0; color:var(--muted);
  text-decoration:underline; text-underline-offset:3px; cursor:pointer; padding:0;
}
.foot button:hover{color:var(--accent);}
#report{display:none; padding-top:18px;}
#report[data-open]{display:block;}
#report table{min-width:560px; font-size:12.5px;}
.bad{color:var(--down);}
.drop{margin-top:14px;}
.drop summary{cursor:pointer; font-family:var(--f-mono); font-size:11px; color:var(--muted);}
.drop ul{margin:10px 0 0; padding-left:18px; color:var(--muted); font-size:12.5px;
         line-height:1.7; max-height:320px; overflow-y:auto;}

:focus-visible{outline:2px solid var(--accent); outline-offset:2px;}
@media (prefers-reduced-motion:reduce){*{transition:none !important;}}
@media (max-width:560px){
  /* 폰에서 표가 옆으로 밀려 점수·변동이 안 보이던 것을 고친다.
     막대는 접고 숫자만 남긴다 — 좁은 화면에서는 숫자가 먼저다. */
  table{min-width:0; font-size:13px;}
  th,td{padding:9px 7px;}
  thead th{font-size:9px; letter-spacing:.06em;}
  td.r{width:26px;}
  td.sc{width:auto;}
  td.d{width:44px;}
  td.nm small{font-size:11px;}
  .barbg{display:none;}
  .find{width:100%;}
  #q{flex:1; width:auto;}
  #calpop{right:0; width:min(296px, calc(100vw - 28px));}
  .boards{flex-wrap:nowrap; overflow-x:auto; scrollbar-width:none;
          margin:0 -14px; padding:22px 14px 14px;}
  .boards::-webkit-scrollbar{display:none;}
  .boards button{flex:none; white-space:nowrap;}
  .top-in{gap:10px; padding:10px 14px;}
  .brand{width:100%; margin-right:0;}
  .wrap{padding:0 14px 60px;}
  .lede{padding:24px 0 20px;}
  .head{grid-template-columns:26px 1fr; gap:10px;}
  .head .m{grid-column:2; margin-top:2px;}
}
"""

PAGE_JS = r"""
(function(){
  var body = document.body;
  var BASE = body.dataset.base || '';       // 지난 브리핑 폴더 안에서는 '../'
  var TODAY = body.dataset.date || '';

  // 색인 파일은 필요할 때 한 번만 받아서 들고 있는다.
  // 첫 화면을 여는 속도에 영향을 주지 않으려고 미리 받지 않는다.
  var cache = {};
  function load(name){
    // 시안이나 오프라인 미리보기에서는 색인을 페이지 안에 직접 넣어 쓴다.
    // 실제 사이트에는 이 값이 없고 아래 fetch로 간다.
    if(window.__IDX__ && window.__IDX__[name]){ return Promise.resolve(window.__IDX__[name]); }
    if(cache[name]){ return cache[name]; }
    cache[name] = fetch(BASE + name + '.json')
      .then(function(r){ return r.ok ? r.json() : []; })
      .catch(function(){ return []; });
    return cache[name];
  }

  function esc(t){
    return String(t).replace(/[&<>"]/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];
    });
  }
  function linkTo(date, uid){
    var page = (date === TODAY && !BASE) ? '' : BASE + 'archive/' + date + '.html';
    return page + '#i-' + uid;
  }

  /* ---------------- 화면 전환 ---------------- */
  function setView(v){
    document.querySelectorAll('[data-view]').forEach(function(sec){
      sec.hidden = (sec.dataset.view !== v);
    });
    document.querySelectorAll('.tabs button').forEach(function(b){
      b.setAttribute('aria-selected', String(b.dataset.go === v));
    });
    if(v === 'models'){ renderModels(); }
  }
  function closeSheets(){
    document.querySelectorAll('.sheet[data-open]').forEach(function(x){
      x.removeAttribute('data-open');
    });
    body.removeAttribute('data-detail');
  }
  function openSheet(el){
    closeSheets();
    if(!el){ return; }
    el.setAttribute('data-open','');
    body.setAttribute('data-detail','');
    el.scrollTop = 0;
  }
  function goBack(){
    if(history.length > 1){ history.back(); } else { location.hash = ''; }
  }

  /* ---------------- 검색 ---------------- */
  var hits = null, qInput = null, qNote = null, results = null, timer = null;

  function tokens(q){
    return q.toLowerCase().split(/\s+/).filter(function(t){ return t.length > 0; });
  }
  // 검색어를 정규식으로 만들지 않는다. 모델 이름에는 .+-() 같은 기호가 흔해서
  // (FLUX.2, Gen-5, fal.ai) 이스케이프를 한 번만 틀려도 검색 전체가 죽는다.
  // 그냥 소문자로 위치를 찾아가며 잘라 붙인다.
  function hl(text, toks){
    var src = String(text), low = src.toLowerCase(), out = '', i = 0;
    while(i < src.length){
      var at = -1, len = 0;
      for(var k = 0; k < toks.length; k++){
        var j = low.indexOf(toks[k], i);
        if(j !== -1 && (at === -1 || j < at)){ at = j; len = toks[k].length; }
      }
      if(at === -1){ out += esc(src.slice(i)); break; }
      out += esc(src.slice(i, at)) + '<mark>' + esc(src.slice(at, at + len)) + '</mark>';
      i = at + len;
    }
    return out;
  }

  function hideResults(){ results.hidden = true; }

  function runSearch(){
    var q = qInput.value.trim();
    if(q.length < 2){
      hits.innerHTML = '';
      if(q.length === 0){ hideResults(); return; }
      results.hidden = false;
      qNote.textContent = '두 글자 이상 입력하세요.';
      return;
    }
    results.hidden = false;
    load('search-index').then(function(rows){
      if(rows === null){ qNote.textContent = OFFLINE; hits.innerHTML = ''; return; }
      var toks = tokens(q);
      var found = rows.filter(function(r){
        var hay = (r.t + ' ' + r.o + ' ' + r.s + ' ' + r.src).toLowerCase();
        return toks.every(function(t){ return hay.indexOf(t) !== -1; });
      });
      qNote.textContent = found.length
        ? found.length + '건 (' + rows.length + '건 중)'
        : '찾은 것이 없습니다. 영문 모델명으로도 찾아보세요.';
      hits.innerHTML = found.slice(0, 80).map(function(r){
        return '<a class="hit" href="' + linkTo(r.d, r.u) + '">'
          + '<span class="hm"><span>' + r.d + '</span><span>' + esc(r.src) + '</span></span>'
          + '<span class="ht">' + hl(r.t, toks) + '</span>'
          + '<span class="hs">' + hl(r.s, toks) + '</span></a>';
      }).join('');
    });
  }

  /* ---------------- 달력 ---------------- */
  var calMonth = null, calPop = null, calBtn = null;
  function ym(d){ return d.slice(0,7); }
  function toggleCal(force){
    var show = (force === undefined) ? calPop.hidden : force;
    calPop.hidden = !show;
    calBtn.setAttribute('aria-expanded', String(show));
    if(show){ load('dates').then(renderCal); }
  }
  function renderCal(dates){
    if(dates === null){
      calPop.querySelector('.cal-note').textContent = OFFLINE;
      return [];
    }
    var have = {};
    dates.forEach(function(d){ have[d] = true; });
    if(!calMonth){ calMonth = dates.length ? ym(dates[0]) : TODAY.slice(0,7); }
    var y = parseInt(calMonth.slice(0,4), 10), m = parseInt(calMonth.slice(5,7), 10);
    var first = new Date(Date.UTC(y, m - 1, 1));
    var days = new Date(Date.UTC(y, m, 0)).getUTCDate();
    var lead = first.getUTCDay();

    var cells = ['일','월','화','수','목','금','토'].map(function(d){
      return '<span class="dow">' + d + '</span>';
    });
    for(var i = 0; i < lead; i++){ cells.push('<span class="pad">.</span>'); }
    for(var day = 1; day <= days; day++){
      var iso = calMonth + '-' + String(day).padStart(2,'0');
      if(have[iso]){
        var href = (iso === TODAY && !BASE) ? '' : BASE + 'archive/' + iso + '.html';
        cells.push('<a href="' + (href || '#') + '" class="' + (iso === TODAY ? 'now' : '')
                   + '">' + day + '</a>');
      } else {
        cells.push('<span>' + day + '</span>');
      }
    }
    calPop.querySelector('.cal').innerHTML = cells.join('');
    calPop.querySelector('.mo').textContent = y + '년 ' + m + '월';

    var months = {};
    dates.forEach(function(d){ months[ym(d)] = true; });
    var keys = Object.keys(months).sort();
    calPop.querySelector('.prev').disabled = (keys.indexOf(calMonth) <= 0);
    calPop.querySelector('.next').disabled =
      (keys.indexOf(calMonth) === keys.length - 1 || keys.length === 0);
    calPop.querySelector('.cal-note').textContent =
      '브리핑이 있는 날만 누를 수 있습니다 · 전체 ' + dates.length + '일';
    return keys;
  }
  function moveMonth(step){
    load('dates').then(function(dates){
      if(dates === null){ return; }
      var months = {};
      dates.forEach(function(d){ months[ym(d)] = true; });
      var keys = Object.keys(months).sort();
      var i = keys.indexOf(calMonth);
      if(i + step >= 0 && i + step < keys.length){
        calMonth = keys[i + step];
        renderCal(dates);
      }
    });
  }

  /* ---------------- 모델별 히스토리 ---------------- */
  var modelsDrawn = false;
  function renderModels(){
    if(modelsDrawn){ return; }
    modelsDrawn = true;
    load('models').then(function(list){
      var box = document.querySelector('#mlist');
      if(list === null){
        modelsDrawn = false;
        box.innerHTML = '<p class="note">' + OFFLINE + '</p>';
        return;
      }
      if(!list.length){
        box.innerHTML = '<p class="note">아직 쌓인 기록이 없습니다. '
          + '며칠 지나면 모델·회사별로 묶여 나타납니다.</p>';
        return;
      }
      box.innerHTML = '<div class="mgrid">' + list.map(function(m){
        return '<button class="mcard" data-model="' + esc(m.name) + '">'
          + '<span class="top-row"><b>' + esc(m.name) + '</b>'
          + (m.ver ? '<span class="ver">' + esc(m.ver) + '</span>' : '') + '</span>'
          + '<span class="hd">' + esc(m.head || '') + '</span>'
          + '<span class="meta">' + m.n + '건 · 최근 ' + m.last + '</span></button>';
      }).join('') + '</div>';
    });
  }
  function showModel(name){
    load('models').then(function(list){
      var m = (list || []).filter(function(x){ return x.name === name; })[0];
      var box = document.querySelector('#mone');
      if(!m){ location.hash = 'models'; return; }
      box.innerHTML = '<div class="mhead"><button class="back" type="button">← 목록</button>'
        + '<h2>' + esc(m.name) + '</h2><span class="n">' + m.n + '건</span></div>'
        + '<div class="timeline">' + m.items.map(function(it){
            return '<a class="tl" href="' + linkTo(it.d, it.u) + '">'
              + '<span class="dt">' + it.d + '</span>'
              + '<span><span class="tt">' + esc(it.t) + '</span>'
              + '<span class="ts">' + esc(it.src) + '</span></span></a>';
          }).join('') + '</div>';
      document.querySelector('#mlist').hidden = true;
      box.hidden = false;
    });
  }

  /* ---------------- 주소 ↔ 화면 ---------------- */
  function route(){
    var h = decodeURIComponent(location.hash.replace(/^#/, ''));

    if(h.indexOf('i-') === 0){ openSheet(document.getElementById('d-' + h.slice(2))); return; }
    closeSheets();
    if(h.indexOf('m-') === 0){ setView('models'); showModel(h.slice(2)); return; }
    document.querySelector('#mone').hidden = true;
    document.querySelector('#mlist').hidden = false;
    setView(h === 'rank' ? 'rank' : (h === 'models' ? 'models' : 'today'));
  }

  /* ---------------- 클릭 한 곳에서 처리 ---------------- */
  document.addEventListener('click', function(ev){
    var t = ev.target;

    var mc = t.closest('.mcard');
    if(mc){ location.hash = 'm-' + encodeURIComponent(mc.dataset.model); return; }

    if(t.closest('.hit')){ hideResults(); return; }   // 링크는 그대로 따라간다

    var el = t.closest('[data-uid]');
    if(el){ location.hash = 'i-' + el.dataset.uid; return; }

    var tab = t.closest('.tabs button');
    if(tab){ location.hash = tab.dataset.go === 'today' ? '' : tab.dataset.go; return; }

    if(t.closest('.calbtn')){ toggleCal(); return; }
    if(t.closest('#calpop .prev')){ moveMonth(-1); return; }
    if(t.closest('#calpop .next')){ moveMonth(1); return; }

    if(t.closest('.back')){ goBack(); return; }

    // 팝오버·결과 패널 바깥을 누르면 닫는다
    if(!t.closest('#calpop') && !t.closest('.calbtn')){ toggleCal(false); }
    if(!t.closest('#results') && !t.closest('#q')){ hideResults(); }

    var bd = t.closest('.boards button');
    if(bd){
      document.querySelectorAll('.boards button').forEach(function(b){
        b.setAttribute('aria-selected', String(b === bd));
      });
      document.querySelectorAll('.board').forEach(function(sec){
        sec.toggleAttribute('data-open', sec.dataset.board === bd.dataset.board);
      });
      return;
    }

    if(t.closest('#report-toggle')){
      document.getElementById('report').toggleAttribute('data-open');
    }
  });

  document.addEventListener('keydown', function(ev){
    if(ev.key === 'Escape'){
      if(!calPop.hidden){ toggleCal(false); return; }
      if(!results.hidden){ hideResults(); qInput.blur(); return; }
      if(body.hasAttribute('data-detail')){ goBack(); }
      return;
    }
    // 어느 화면에서든 / 를 누르면 검색창으로 간다
    if(ev.key === '/' && !/^(INPUT|TEXTAREA)$/.test(ev.target.tagName)){
      ev.preventDefault();
      qInput.focus();
      qInput.select();
    }
  });

  qInput = document.getElementById('q');
  qNote = document.querySelector('#results .q-note');
  hits = document.querySelector('#results .hits');
  results = document.getElementById('results');
  calPop = document.getElementById('calpop');
  calBtn = document.querySelector('.calbtn');
  qInput.addEventListener('input', function(){
    clearTimeout(timer);
    timer = setTimeout(runSearch, 140);
  });
  qInput.addEventListener('focus', function(){
    if(qInput.value.trim().length >= 2){ runSearch(); }
  });

  window.addEventListener('hashchange', route);
  route();

  // 홈 화면에 추가했을 때 오프라인에서도 열리게 한다.
  // file://로 열었을 때는 등록이 안 되므로 조용히 건너뛴다.
  if('serviceWorker' in navigator && location.protocol.indexOf('http') === 0){
    navigator.serviceWorker.register(BASE + 'sw.js').catch(function(){});
  }

  // 홈 화면 앱은 한 번 연 화면을 그대로 들고 있는다. 그래서 아침에 열면
  // 어제 것이 그대로 보인다. 열 때마다 "가장 최근 브리핑 날짜"만 캐시를 무시하고
  // 확인해서, 지금 보는 것보다 새 것이 있으면 띠를 띄운다.
  function checkFresh(){
    if(!TODAY || BASE){ return; }              // 지난 브리핑 페이지에서는 띄우지 않는다
    fetch(BASE + 'dates.json', {cache: 'no-store'})
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(dates){
        if(!dates || !dates.length || dates[0] <= TODAY){ return; }
        var bar = document.getElementById('fresh');
        bar.querySelector('span').textContent = dates[0] + ' 브리핑이 나왔습니다';
        bar.setAttribute('data-show', '');
      })
      .catch(function(){});
  }

  document.getElementById('fresh').querySelector('button')
    .addEventListener('click', function(){
      // 캐시를 비우고 주소에 시각을 붙여 다시 부른다.
      // 둘 다 해야 확실하다 — 서비스 워커 캐시와 브라우저 캐시는 서로 다른 것이다.
      var done = function(){ location.replace(BASE + 'index.html?v=' + Date.now()); };
      if(!('caches' in window)){ done(); return; }
      caches.keys().then(function(keys){
        return Promise.all(keys.map(function(k){ return caches.delete(k); }));
      }).then(done, done);
    });

  checkFresh();
  // 앱을 다시 앞으로 가져왔을 때도 확인한다 (폰에서는 이쪽이 훨씬 흔하다)
  document.addEventListener('visibilitychange', function(){
    if(document.visibilityState === 'visible'){ checkFresh(); }
  });
})();
"""


# ==========================================================================
#  조각들
# ==========================================================================

def _cat(item: Item) -> tuple[str, str]:
    return (CATEGORY_LABELS.get(item.category, item.category),
            CATEGORY_DOT.get(item.category, CATEGORY_DOT["minor"]))


def _headline_row(n: int, item: Item, stars: int) -> str:
    label, _ = _cat(item)
    return (
        f'<button class="head" data-uid="{e(item.uid)}">'
        f'<span class="n">{n:02d}</span>'
        f'<span class="t">{e(item.display_title)}</span>'
        f'<span class="m">{e(label)} · {e(item.source_name)}</span>'
        f'</button>'
    )


def _tile(item: Item, stars: int) -> str:
    label, color = _cat(item)
    return (
        f'<button class="tile" data-uid="{e(item.uid)}">'
        f'<span class="cat"><i class="dot" style="background:{color}"></i>{e(label)}</span>'
        f'<span class="t">{e(item.display_title)}</span>'
        f'<span class="m"><span class="st">{_stars(stars)}</span>'
        f'<span>{e(item.source_name)}</span><span>{_when(item.published_kst.isoformat())}</span>'
        f'</span></button>'
    )


def _detail(item: Item, stars: int, pos: str) -> str:
    label, color = _cat(item)
    tier = TIER_LABELS.get(item.tier, item.tier)

    # 번역이 있으면 한국어 요약을, 없으면 원문 요약을 그대로 본문으로 쓴다.
    # 예전에는 [요약|원문] 전환 탭을 뒀는데, 바로 아래 '원문 열기' 버튼이
    # 같은 일을 더 확실히 한다. 눌러야 보이는 탭은 대개 눌리지 않는다.
    body_parts = []
    if item.summary_ko:
        body_parts.append(f'<p class="body-text">{e(item.summary_ko)}</p>')
        if item.bullets:
            bullets = "".join(f"<li>{e(b)}</li>" for b in item.bullets)
            body_parts.append(f'<ul class="bul">{bullets}</ul>')
    elif item.summary_raw.strip():
        body_parts.append('<p class="q-note">번역이 없어 원문을 그대로 싣습니다.</p>')
        body_parts.append(f'<p class="body-text raw-text">{e(item.summary_raw.strip()[:2000])}</p>')
    else:
        body_parts.append('<p class="none">이 소스는 본문 요약을 제공하지 않습니다. '
                          '아래 버튼으로 원문을 여세요.</p>')

    orig = ""
    if item.title_ko and item.title_ko != item.title:
        orig = f'<p class="d-orig">원제 · {e(item.title)}</p>'

    related = ""
    if item.related:
        rows = "".join(
            f'<a href="{e(r["url"])}" target="_blank" rel="noopener">{e(r["title"])}'
            f'<span class="src">{e(r.get("source", ""))}</span></a>'
            for r in item.related[:8]
        )
        related = (f'<div class="rel"><h3>같은 사건을 다룬 다른 기사 {len(item.related)}건</h3>'
                   f'{rows}</div>')

    return f"""<div class="detail" id="d-{e(item.uid)}">
  <div class="d-bar">
    <button class="back" type="button">← 목록</button>
    <span class="pos">{e(pos)}</span>
  </div>
  <div class="d-body">
    <div class="d-meta">
      <i class="dot" style="background:{color}"></i>{e(label)}
      <span class="st" title="중요도">{_stars(stars)}</span>
      <span>{e(item.source_name)} · {e(tier)}</span>
      <span>{_when(item.published_kst.isoformat())}</span>
    </div>
    <h1 class="d-title">{e(item.display_title)}</h1>
    {orig}
    {''.join(body_parts)}
    <a class="go" href="{e(item.url)}" target="_blank" rel="noopener">원문 열기 · {e(item.domain)} ↗</a>
    {related}
  </div>
</div>"""


def _delta_cell(row: dict) -> str:
    if row.get("is_new"):
        return '<span class="new">NEW</span>'
    d = row.get("delta")
    if not d:
        return '<span style="color:var(--muted)">–</span>'
    if d > 0:
        return f'<span class="up">▲{d}</span>'
    return f'<span class="down">▼{abs(d)}</span>'


def _board_table(board: dict) -> str:
    if not board["rows"]:
        return f'<p class="note">표를 받지 못했습니다 — {e(board["note"] or "이유 불명")}</p>'

    is_lang = board.get("kind") == "language"
    score_head = "지능 지수" if is_lang else "Elo"
    has_price = any(r.get("price") is not None for r in board["rows"])
    unit = next((r["price_unit"] for r in board["rows"] if r.get("price") is not None), "")

    head = f"<tr><th></th><th>모델</th><th style='text-align:right'>{score_head}</th><th>변동</th>"
    if has_price:
        head += f"<th style='text-align:right'>{e(unit)}</th>"
    head += "</tr>"

    # 숫자만 늘어놓으면 1위와 8위의 간격이 얼마나 되는지 읽히지 않는다.
    # 막대를 함께 그려서 "박빙인지 압도적인지"가 한눈에 보이게 한다.
    values = [r["score"] for r in board["rows"] if r["score"] is not None]
    lo = min(values) * 0.985 if values else 0
    span = (max(values) - lo) if values and max(values) > lo else 1

    rows = ""
    for r in board["rows"]:
        price = ""
        if has_price:
            v = r.get("price")
            price = f'<td class="num">{v if v is not None else "–"}</td>'
        if r["score"] is None:
            score_cell = '<td class="num sc">–</td>'
        else:
            pct = max(6, min(100, round((r["score"] - lo) / span * 100)))
            score_cell = (f'<td class="num sc"><span class="scwrap">'
                          f'<span class="barbg"><i style="width:{pct}%"></i></span>'
                          f'{r["score"]}</span></td>')
        rows += (
            f'<tr><td class="r">{r.get("rank", "")}</td>'
            f'<td class="nm">{e(r["name"])}<small>{e(r["creator"])}</small></td>'
            f'{score_cell}'
            f'<td class="d">{_delta_cell(r)}</td>{price}</tr>'
        )
    return f'<div class="tblwrap"><table><thead>{head}</thead><tbody>{rows}</tbody></table></div>'


def _rankings_view(rk: dict) -> str:
    if not rk or rk.get("error"):
        why = e(rk.get("error", "설정되지 않음")) if rk else "설정되지 않음"
        return (f'<p class="note">순위표가 아직 없습니다 — {why}.<br>'
                f'키를 넣으면 다음 실행부터 채워집니다 '
                f'(<code>AA_API_KEY</code>, artificialanalysis.ai/data-api).</p>')

    boards = [b for b in rk.get("boards", [])]
    if not boards:
        return '<p class="note">표시할 순위판이 없습니다.</p>'

    chips = "".join(
        f'<button type="button" data-board="{e(b["id"])}" '
        f'aria-selected="{"true" if i == 0 else "false"}">{e(b["label"])}</button>'
        for i, b in enumerate(boards)
    )
    panels = "".join(
        f'<section class="board" data-board="{e(b["id"])}"{" data-open" if i == 0 else ""}>'
        f'{_board_table(b)}</section>'
        for i, b in enumerate(boards)
    )
    # 무료 등급에서는 영상·이미지 판에 가격이 오지 않는다. 언어모델 판은 무료에도 가격이 있다.
    tier_note = ""
    media_missing_price = any(
        b.get("kind") != "language" and b["rows"]
        and all(r.get("price") is None for r in b["rows"])
        for b in boards
    )
    if rk.get("tier") == "free" and media_missing_price:
        tier_note = " · 영상·이미지 가격은 유료 등급에서만 제공됩니다"
    fetched = _when(rk.get("fetched_at", "").replace("Z", "+00:00"))

    return (
        f'<div class="boards">{chips}</div>{panels}'
        f'<p class="credit">순위·점수 출처 '
        f'<a href="{e(rk.get("source_url", "https://artificialanalysis.ai/"))}" '
        f'target="_blank" rel="noopener">{e(rk.get("attribution", "Artificial Analysis"))}</a>'
        f' · 블라인드 선호도 투표 기반 · 받아온 시각 {fetched} UTC{tier_note}</p>'
    )


def _report_view(brief: Brief) -> str:
    rows = ""
    for r in sorted(brief.reports, key=lambda x: (x.ok, -x.kept, x.source_id)):
        state = "정상" if r.ok else f'<span class="bad">{e(r.error.split(":")[0])}</span>'
        rows += (f'<tr><td>{e(r.source_name)}</td><td>{e(r.tier)}</td>'
                 f'<td class="num">{r.collected}</td><td class="num">{r.kept}</td>'
                 f'<td>{state}</td></tr>')
    table = (f'<div class="tblwrap"><table><thead><tr><th>소스</th><th>등급</th>'
             f'<th style="text-align:right">수집</th><th style="text-align:right">채택</th>'
             f'<th>상태</th></tr></thead><tbody>{rows}</tbody></table></div>')

    drop = ""
    if brief.dropped:
        items = "".join(f"<li>[{e(d['reason'])}] {e(d['title'][:110])}</li>"
                        for d in brief.dropped[:60])
        drop = (f'<details class="drop"><summary>필터에 걸린 {len(brief.dropped)}건 보기'
                f'</summary><ul>{items}</ul></details>')

    s = brief.stats
    line = (f"수집 {s.get('collected', 0)} → 시간창 {s.get('in_window', 0)} → "
            f"필터 {s.get('screened', 0)} → 병합 후 {s.get('clustered', 0)} → 카드 {len(brief.cards)}")
    return (f'<p class="note">{e(line)} · 번역 {s.get("translated", 0)}건'
            f'({e(str(s.get("translate_engine", "")))})</p>{table}{drop}')


# ==========================================================================
#  페이지
# ==========================================================================

def render_page(brief: Brief, in_archive: bool = False) -> str:
    cards = brief.cards
    top = max((c.score for c in cards), default=0.0)
    stars = {c.uid: importance_stars(c, top) for c in cards}

    heads = brief.headlines or cards[:5]
    rest = [c for c in cards if c.uid not in {h.uid for h in heads}]

    if brief.tldr:
        flow = f'<p class="flow">{"".join(f"<span>{e(t)}</span>" for t in brief.tldr)}</p>'
    else:
        flow = '<p class="flow empty">오늘의 흐름을 만들지 못했습니다.</p>'

    head_rows = "".join(_headline_row(n, h, stars.get(h.uid, 1))
                        for n, h in enumerate(heads, 1))
    tiles = "".join(_tile(c, stars.get(c.uid, 1)) for c in rest)

    details = "".join(
        _detail(c, stars.get(c.uid, 1), f"{i}/{len(cards)}")
        for i, c in enumerate(cards, 1)
    )

    # 지난 브리핑은 docs/archive/ 안에 있다. 그 안에서 열렸을 때는 경로가 한 단계 다르다.
    # 달력·검색·모델 목록은 docs/*.json을 받아서 쓰므로 이 값만 맞으면 어디서든 동작한다.
    base = "../" if in_archive else ""
    manifest_href = base + "manifest.json"

    grid = (f'<div class="sec-h"><h2>나머지</h2><span class="c">{len(rest)}건</span></div>'
            f'<div class="grid">{tiles}</div>') if rest else ""

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="#0B0E10">
<meta name="robots" content="noindex, nofollow">
<title>{e(brief.date_kst)} · 비주얼 AI 브리핑</title>
<link rel="manifest" href="{manifest_href}">
<link rel="icon" href="{base}icon-192.png" type="image/png">
<link rel="apple-touch-icon" href="{base}apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="AI 브리핑">
<link rel="alternate" type="application/rss+xml" title="비주얼 AI 브리핑" href="{base}feed.xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>{PAGE_CSS}</style>
</head>
<body data-base="{base}" data-date="{e(brief.date_kst)}">

<header class="top"><div class="top-in">
  <div class="brand">
    <span class="d">{e(brief.date_kst)}</span>
    <span class="s">Visual AI Brief</span>
  </div>
  <div class="tabs">
    <button type="button" data-go="today" aria-selected="true">오늘</button>
    <button type="button" data-go="rank" aria-selected="false">순위</button>
    <button type="button" data-go="models" aria-selected="false">모델</button>
  </div>
  <div class="find">
    <input id="q" type="search" placeholder="검색 (지난 브리핑 포함)"
           autocomplete="off" autocapitalize="off" spellcheck="false">
    <button class="calbtn" type="button" aria-expanded="false">날짜</button>
  </div>
</div>

<div id="results" hidden><div class="res-in">
  <p class="q-note"></p>
  <div class="hits"></div>
</div></div>

<div id="calpop" hidden>
  <div class="cal-head">
    <span class="mo"></span>
    <button class="prev" type="button" aria-label="이전 달">‹</button>
    <button class="next" type="button" aria-label="다음 달">›</button>
  </div>
  <div class="cal"></div>
  <p class="q-note cal-note"></p>
</div>
</header>

<main class="wrap">

  <section data-view="today">
    <div class="lede">
      {flow}
      <div class="heads">{head_rows}</div>
    </div>
    {grid}
    <div class="foot">
      <span>{len(cards)}건 · {e(brief.window_start[5:16].replace("T", " "))} ~ {e(brief.window_end[5:16].replace("T", " "))} KST</span>
      <button type="button" id="report-toggle">실행 정보</button>
    </div>
    <div id="report">{_report_view(brief)}</div>
  </section>

  <section data-view="rank" hidden>
    {_rankings_view(brief.rankings)}
  </section>

  <section data-view="models" hidden>
    <div id="mlist"></div>
    <div id="mone" hidden></div>
  </section>

</main>

{details}


<div id="fresh"><span></span><button type="button">열기</button></div>

<script>{PAGE_JS}</script>
</body>
</html>"""


# ==========================================================================
#  메일 — 표 레이아웃 + 인라인 스타일만
# ==========================================================================

def render_email(brief: Brief, site_url: str = "") -> str:
    """
    메일 본문 — 웹 화면과 같은 어두운 배경으로 맞춘다.

    메일에서 지켜야 하는 제약이 웹과 다르다.
      · CSS 파일도 <style>도 못 믿는다 → 모든 스타일을 태그에 직접 쓴다
      · flex/grid 없다 → 표(table)로만 배치한다
      · 웹폰트 안 온다 → 시스템 글꼴만 쓴다
      · 배경색은 style과 bgcolor를 함께 준다 (구버전 아웃룩은 style을 버린다)
    자바스크립트가 없으므로 접기·탭 같은 건 없다. 대신 헤드라인 5건은 크게,
    나머지는 한 줄로 줄이고, 자세한 건 웹에서 보게 한다.
    """
    GROUND, SURF, LINE = "#0B0E10", "#14181C", "#262E35"
    INK, INK2, MUTED, AMBER = "#F2F5F7", "#B7C2CB", "#7C8A95", "#FFCE4A"
    FONT = ("-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',"
            "'Malgun Gothic',Roboto,sans-serif")
    MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

    site = (site_url or "").rstrip("/")
    web = ""
    if site:
        web = (f'<a href="{e(site)}" style="color:{AMBER};text-decoration:none;'
               f'font-size:12.5px;font-weight:600">웹에서 보기 →</a>')

    flow = "".join(
        f'<div style="color:{INK};font-size:18px;line-height:1.55;font-weight:700;'
        f'margin:0 0 10px;word-break:keep-all">{e(t)}</div>'
        for t in brief.tldr
    ) or f'<div style="color:{MUTED};font-size:14px">오늘의 흐름 없음</div>'

    heads = brief.headlines or brief.cards[:5]
    rest = [c for c in brief.cards if c.uid not in {h.uid for h in heads}]

    head_rows = ""
    for n, it in enumerate(heads, 1):
        label = CATEGORY_LABELS.get(it.category, it.category)
        summary = it.summary_ko or it.summary_raw[:180]
        head_rows += f"""
<tr><td style="padding:18px 0;border-bottom:1px solid {LINE}">
  <div style="font-family:{MONO};font-size:11px;color:{MUTED};letter-spacing:.08em">
    <span style="color:{AMBER}">{n:02d}</span> · {e(label)} · {e(it.source_name)}
  </div>
  <a href="{e(it.url)}" style="display:block;margin:6px 0 7px;font-size:19px;line-height:1.45;
     font-weight:700;color:{INK};text-decoration:none;word-break:keep-all">{e(it.display_title)}</a>
  <div style="font-size:14px;line-height:1.65;color:{INK2};word-break:keep-all">{e(summary)}</div>
</td></tr>"""

    rest_rows = ""
    if rest:
        lines = ""
        for it in rest:
            label = CATEGORY_LABELS.get(it.category, it.category)
            lines += (
                f'<a href="{e(it.url)}" style="display:block;padding:9px 0;'
                f'border-bottom:1px solid {LINE};color:{INK2};text-decoration:none;'
                f'font-size:15px;line-height:1.5;word-break:keep-all">{e(it.display_title)}'
                f'<span style="font-family:{MONO};font-size:10.5px;color:{MUTED};'
                f'display:block;margin-top:3px">{e(label)} · {e(it.source_name)}</span></a>'
            )
        rest_rows = f"""
<tr><td style="padding:22px 0 0">
  <div style="font-family:{MONO};font-size:10.5px;color:{MUTED};letter-spacing:.14em;
       text-transform:uppercase;margin-bottom:4px">나머지 {len(rest)}건</div>
  {lines}
</td></tr>"""

    rank_block = ""
    boards = [b for b in (brief.rankings or {}).get("boards", []) if b.get("rows")]
    if boards:
        b = boards[0]
        rows = "".join(
            f'<tr><td style="font-family:{MONO};font-size:12px;color:{MUTED};'
            f'padding:5px 10px 5px 0;width:18px">{r.get("rank","")}</td>'
            f'<td style="font-size:14px;color:{INK};font-weight:600;padding:5px 0">{e(r["name"])}'
            f'<span style="color:{MUTED};font-weight:400"> · {e(r["creator"])}</span></td>'
            f'<td style="font-family:{MONO};font-size:12.5px;color:{INK2};'
            f'text-align:right;padding:5px 0">{r["score"] if r["score"] is not None else ""}</td></tr>'
            for r in b["rows"][:5]
        )
        rank_block = f"""
<tr><td style="padding:26px 0 0;border-top:1px solid {LINE}">
  <div style="font-family:{MONO};font-size:10.5px;color:{MUTED};letter-spacing:.14em;
       text-transform:uppercase;margin:14px 0 8px">{e(b["label"])} 순위</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table>
  <div style="font-size:11px;color:{MUTED};margin-top:8px">
    출처 {e((brief.rankings or {}).get("attribution", "Artificial Analysis"))}
  </div>
</td></tr>"""

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="supported-color-schemes" content="dark">
</head>
<body style="margin:0;padding:0;background:{GROUND};" bgcolor="{GROUND}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       bgcolor="{GROUND}" style="background:{GROUND};padding:22px 10px">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
       bgcolor="{SURF}"
       style="max-width:600px;width:100%;background:{SURF};border:1px solid {LINE};
              border-radius:14px;padding:26px 24px;font-family:{FONT}">

  <tr><td style="padding-bottom:16px;border-bottom:1px solid {LINE}">
    <div style="font-family:{MONO};font-size:10.5px;letter-spacing:.16em;
         text-transform:uppercase;color:{MUTED}">Visual AI Brief</div>
    <div style="font-family:{MONO};font-size:23px;font-weight:700;color:{INK};
         margin:3px 0 7px;letter-spacing:.02em">{e(brief.date_kst)}</div>
    {web}
  </td></tr>

  <tr><td style="padding:22px 0 4px">{flow}</td></tr>
  {head_rows}
  {rest_rows}
  {rank_block}

  <tr><td style="padding-top:24px;font-size:11.5px;color:{MUTED};line-height:1.65">
    수집 {brief.stats.get('collected', 0)}건에서 {len(brief.cards)}건 선별 ·
    소스 {brief.stats.get('sources_ok', 0)}/{brief.stats.get('sources_total', 0)} 정상<br>
    각 항목의 저작권은 원 저작자에게 있습니다. 개인 열람용 요약입니다.
  </td></tr>

</table>
</td></tr></table>
</body></html>"""


# ==========================================================================
#  저장
# ==========================================================================

MANIFEST = {
    "name": "비주얼 AI 브리핑",
    "short_name": "AI 브리핑",
    "description": "생성형 비주얼 AI 뉴스 데일리 브리핑",
    "start_url": "./index.html",
    "scope": "./",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#0B0E10",
    "theme_color": "#0B0E10",
    "lang": "ko",
    "icons": [
        {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
        # maskable은 안드로이드가 아이콘을 원형·사각형 등으로 잘라낼 때 쓴다.
        # 여백을 넉넉히 둔 그림이라 어떻게 잘려도 안쪽 도형이 살아남는다.
        {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png",
         "purpose": "maskable"},
    ],
}

# 서비스 워커 — 홈 화면에 추가한 뒤 지하철에서 열어도 어제 것이 보이게 한다.
# 전략은 "네트워크 먼저, 실패하면 캐시". 브리핑은 매일 바뀌므로 캐시를 우선하면
# 새 브리핑이 나온 날 옛것을 보게 된다. 반대로 두면 평소엔 항상 최신이고
# 비행기 모드에서만 마지막으로 본 것이 뜬다.
SERVICE_WORKER = """
const CACHE = 'brief-v2';
const CORE = ['./', './index.html', './manifest.json',
              './dates.json', './models.json', './search-index.json'];

self.addEventListener('install', function(ev){
  self.skipWaiting();
  ev.waitUntil(caches.open(CACHE).then(function(c){
    return Promise.all(CORE.map(function(u){
      return c.add(u).catch(function(){ /* 아직 없는 파일은 넘어간다 */ });
    }));
  }));
});

self.addEventListener('activate', function(ev){
  ev.waitUntil(caches.keys().then(function(keys){
    return Promise.all(keys.filter(function(k){ return k !== CACHE; })
                           .map(function(k){ return caches.delete(k); }));
  }).then(function(){ return self.clients.claim(); }));
});

// 브리핑 본문과 색인은 매일 바뀐다. 그런데 그냥 fetch를 하면 브라우저의 HTTP 캐시가
// 먼저 답해버려서, 서비스 워커가 "네트워크 먼저"를 해도 어제 것이 온다.
// (깃허브 Pages가 HTML에 10분짜리 캐시를 걸어 두기 때문이다.)
// 그래서 이 파일들만 cache:'reload'로 요청해 HTTP 캐시를 건너뛴다.
function isFresh(url){
  return /\.(html|json)$/.test(url) || url.endsWith('/') ||
         url.indexOf('/index') !== -1;
}

self.addEventListener('fetch', function(ev){
  if(ev.request.method !== 'GET'){ return; }
  var req = ev.request;
  if(req.mode === 'navigate' || isFresh(req.url)){
    try { req = new Request(req.url, {cache: 'reload', credentials: 'same-origin'}); }
    catch(e){ req = ev.request; }
  }
  ev.respondWith(
    fetch(req).then(function(res){
      var copy = res.clone();
      caches.open(CACHE).then(function(c){ c.put(ev.request, copy); });
      return res;
    }).catch(function(){
      return caches.match(ev.request).then(function(hit){
        return hit || caches.match('./index.html');
      });
    })
  );
});
"""


def _write_if_changed(path: Path, text: str) -> bool:
    """
    내용이 같으면 쓰지 않는다.

    지난 브리핑 페이지를 매일 다시 그리는데, 매번 파일을 새로 쓰면 내용이 똑같아도
    깃이 "바뀐 파일"로 잡는 날이 생긴다. 그러면 매일 수십 개 파일이 커밋에 딸려 들어와
    "무엇이 실제로 달라졌나"를 볼 수 없게 된다.
    """
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def rebuild_archive(root: Path, limit: int = 120) -> int:
    """
    지난 브리핑 페이지를 지금 디자인으로 다시 그린다.

    화면을 고칠 때마다 어제까지의 페이지만 옛 모습으로 남으면, 달력이나 검색으로
    거슬러 올라갔을 때 갑자기 다른 앱이 된다. 저장된 JSON이 원본이므로 언제든
    다시 그릴 수 있다 — 그게 JSON을 원본으로 삼은 이유이기도 하다.
    """
    from .models import Brief as _Brief

    data_dir, archive_dir = root / "data", root / "docs" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    paths = sorted(data_dir.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].json"),
                   reverse=True)[:limit]
    changed = 0
    for path in paths:
        try:
            past = _Brief.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError):
            continue          # 예전 버전이 쓴 파일이 깨져 있어도 나머지는 계속 그린다
        if _write_if_changed(archive_dir / f"{past.date_kst}.html",
                             render_page(past, in_archive=True)):
            changed += 1
    return changed


def render_feed(root: Path, site_url: str, days: int = 14) -> str:
    """
    RSS 피드 — 알림 앱을 따로 깔지 않아도 되는 가장 가벼운 구독 방법.

    링크는 원문이 아니라 우리 페이지의 그 항목으로 건다. 요약과 원문 링크가
    거기 함께 있어서, 읽고 나서 원문으로 갈지 말지를 고를 수 있기 때문이다.
    """
    from . import archive as _archive

    site = (site_url or "").rstrip("/")
    briefs = _archive.load_all(root / "data")[-days:]
    items = []
    for brief in reversed(briefs):
        date = brief.get("date_kst", "")
        for n, card in enumerate(brief.get("cards", [])):
            title = card.get("title_ko") or card.get("title", "")
            summary = card.get("summary_ko") or card.get("summary_raw", "")[:400]
            link = f"{site}/archive/{date}.html#i-{card.get('uid','')}" if site else card.get("url", "")
            # RFC 822 형식. 날짜만 있으므로 발행 시각은 07:00 KST로 고정한다.
            pub = f"{date} 07:00:00 +0900"
            try:
                pub = dt.datetime.fromisoformat(f"{date}T07:00:00+09:00") \
                        .strftime("%a, %d %b %Y %H:%M:%S %z")
            except ValueError:
                pass
            items.append(
                "<item>"
                f"<title>{e(title)}</title>"
                f"<link>{e(link)}</link>"
                f"<guid isPermaLink=\"false\">{e(card.get('uid',''))}</guid>"
                f"<pubDate>{pub}</pubDate>"
                f"<category>{e(CATEGORY_LABELS.get(card.get('category','minor'), ''))}</category>"
                f"<description>{e(summary)}</description>"
                "</item>"
            )

    now = dt.datetime.now(dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        "<title>비주얼 AI 브리핑</title>"
        f"<link>{e(site)}/</link>"
        "<description>생성형 비주얼 AI 뉴스 데일리 브리핑</description>"
        "<language>ko</language>"
        f"<lastBuildDate>{now}</lastBuildDate>"
        + "".join(items) +
        "</channel></rss>"
    )


def write_outputs(brief: Brief, root: Path, site_url: str = "") -> dict[str, Path]:
    """data/(원본 JSON) + docs/(공개 사이트) 두 곳에 나눠 쓴다."""
    data_dir = root / "data"
    docs_dir = root / "docs"
    archive_dir = docs_dir / "archive"
    for d in (data_dir, docs_dir, archive_dir):
        d.mkdir(parents=True, exist_ok=True)

    json_path = data_dir / f"{brief.date_kst}.json"
    json_path.write_text(json.dumps(brief.to_dict(), ensure_ascii=False, indent=2),
                         encoding="utf-8")

    index_path = docs_dir / "index.html"
    index_path.write_text(render_page(brief), encoding="utf-8")
    _write_if_changed(archive_dir / f"{brief.date_kst}.html",
                      render_page(brief, in_archive=True))
    (docs_dir / "manifest.json").write_text(json.dumps(MANIFEST, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    (docs_dir / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (docs_dir / "sw.js").write_text(SERVICE_WORKER, encoding="utf-8")
    _write_if_changed(docs_dir / "feed.xml", render_feed(root, site_url))

    # 홈 화면 아이콘. assets/에 있는 원본을 docs/로 복사한다.
    for name in ("icon-192.png", "icon-512.png", "icon-maskable-512.png",
                 "apple-touch-icon.png"):
        src_icon = root / "assets" / name
        if src_icon.exists():
            dst = docs_dir / name
            if not dst.exists() or dst.read_bytes() != src_icon.read_bytes():
                dst.write_bytes(src_icon.read_bytes())
    # 깃허브 Pages는 기본적으로 Jekyll이라는 옛 블로그 엔진을 한 번 거쳐서 사이트를
    # 만든다. 이 빈 파일이 있으면 그 단계를 통째로 건너뛴다.
    (docs_dir / ".nojekyll").write_text("", encoding="utf-8")

    return {"json": json_path, "index": index_path}
