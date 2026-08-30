"""
파이프라인 회귀 테스트 — 네트워크 없이 돈다.

    python tests/test_pipeline.py

여기서 검증하는 건 "코드가 죽지 않는다"가 아니라
"규칙이 의도대로 동작한다"이다. 필터 규칙과 유사도 임계값은
손으로 계속 만지게 되는데, 만질 때마다 여기가 빨개지는지 보면 된다.
"""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import (archive, dedupe, normalize, notify, rankings, render,   # noqa: E402
                 screen, translate)
from src.models import Brief                                    # noqa: E402
from src.models import Item, KST                               # noqa: E402

PASSED, FAILED = 0, 0


def check(label: str, actual, expected) -> None:
    global PASSED, FAILED
    if actual == expected:
        PASSED += 1
        print(f"  ok   {label}")
    else:
        FAILED += 1
        print(f"  FAIL {label}\n         기대 {expected!r}\n         실제 {actual!r}")


def item(title: str, *, url="https://example.com/a", tier="T3",
         topics=("video",), summary="", ad_filter="normal", hours_ago=2) -> Item:
    return Item(
        title=title, url=url, source_id="s", source_name="테스트", tier=tier,
        topics=list(topics),
        published=dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago),
        summary_raw=summary, ad_filter=ad_filter,
    )


print("\nURL 정규화")
check("추적 파라미터 제거",
      normalize.canonical_url("https://runwayml.com/news/gen-5?utm_source=x&fbclid=1"),
      "https://runwayml.com/news/gen-5")
check("유튜브는 v만 남긴다",
      normalize.canonical_url("https://www.youtube.com/watch?v=abc&t=30s&list=PL1"),
      "https://youtube.com/watch?v=abc")
check("끝 슬래시 통일",
      normalize.canonical_url("https://Example.com/Path/"),
      "https://example.com/Path")

print("\n시간창")
now = dt.datetime(2026, 8, 25, 8, 0, tzinfo=KST)
start, end = normalize.window_bounds(now, "07:00", 24)
check("창 끝은 당일 07:00", end.isoformat(), "2026-08-25T07:00:00+09:00")
check("창 시작은 전일 07:00", start.isoformat(), "2026-08-24T07:00:00+09:00")
early = dt.datetime(2026, 8, 25, 3, 0, tzinfo=KST)   # 아직 07시 전
_, end2 = normalize.window_bounds(early, "07:00", 24)
check("07시 전 실행이면 창 끝은 어제", end2.isoformat(), "2026-08-24T07:00:00+09:00")

print("\n토큰화·유사도")
check("버전 표기 통일", "gen5" in dedupe.tokenize("Runway Gen-5 is here"), True)
check("소수점 버전 통일", "kling28" in dedupe.tokenize("Kling 2.8 arrives"), True)
check("같은 사건은 묶인다",
      dedupe.similarity(dedupe.tokenize("Introducing Runway Gen-5: a new frontier"),
                        dedupe.tokenize("Runway Gen-5 released")) >= 0.5, True)
check("비교글은 릴리스와 안 묶인다",
      dedupe.similarity(dedupe.tokenize("Kling 2.8 released today"),
                        dedupe.tokenize("Kling 2.8 vs Veo 3.5 vs Seedance 2")) >= 0.5, False)
check("무관한 제목은 안 묶인다",
      dedupe.similarity(dedupe.tokenize("Runway Gen-5 released"),
                        dedupe.tokenize("ComfyUI v0.9.0 subgraph nodes")) >= 0.5, False)

print("\n카테고리 분류")
cases = [
    ("Introducing Runway Gen-5: a new video model", "model_release"),
    ("Kling 2.8 vs Veo 3.5: head-to-head", "benchmark"),
    ("Consistent characters: a full ComfyUI workflow", "workflow"),
    ("Wan 2.2 weights are now available on Hugging Face", "opensource"),
    ("Midjourney release notes: style references improved", "major_update"),
    ("Getty and Stability settlement reshapes licensing", "industry"),
]
for title, expected in cases:
    check(f"{title[:38]}…", screen.categorize(item(title)), expected)

print("\n주제 추론")
check("소스 topics가 industry여도 비디오로 잡힌다",
      "video" in screen.infer_topics(item("Runway launches Gen-5", topics=("industry",))), True)
check("무관한 제목은 빈 리스트",
      screen.infer_topics(item("Quarterly earnings at a logistics firm", topics=("industry",))), [])

print("\n이미 걸러온 소스는 두 번 거르지 않는다")
_papers = ["EchoWM: Open and Enterable Omnimodal World Models",
           "MIVIFI: Bridging Perspective and Fisheye Domains for Training Multi-View",
           "Multiple View Neural Regression of a Facial Shape Model"]
def _paper(title, pre):
    # 실제 arXiv 항목처럼 kind와 초록을 갖춰준다.
    # (초록이 없으면 "내용 없음" 규칙에 먼저 걸려서 이 테스트의 의미가 사라진다)
    it = item(title, tier="T1",
              summary="We present a method for generating consistent outputs. "
                      "Code is available at https://github.com/example/repo")
    it.extra = {"kind": "paper", "has_code": True}
    if pre:
        it.extra["pre_filtered"] = True
    return it

_k, _d = screen.screen([_paper(t, True) for t in _papers], {}, 0.6, 0.4)
check("skip_topic_filter면 제목만으로 떨어뜨리지 않는다", len(_k), 3)
# 표시가 없으면 제목에 용어가 있는 것만 통과한다.
# EchoWM은 "World Models"가 사전에 있어 통과하고, 나머지 둘은 떨어진다 —
# 즉 사전을 넓혀도 이름만 있는 논문은 못 잡는다. 그래서 skip_topic_filter가 필요하다.
_k2, _d2 = screen.screen([_paper(t, False) for t in _papers], {}, 0.6, 0.4)
check("표시가 없으면 제목에 용어가 있는 것만 통과", (len(_k2), len(_d2)), (1, 2))

_general = screen.screen([item("The full stack behind abundant intelligence", tier="T0")], {}, 0.6, 0.4)
check("범용 T0 소스도 주제 필터를 받는다 (표시가 없으면)", len(_general[1]), 1)

print("\n사건 식별 (드문 고유명사)")
_titles = ["Jalapeño's first results show industry-leading speed and efficiency in AI inference",
           "OpenAI's Jalapeño chip is built for fast inference at scale, benchmarks show",
           "OpenAI says its Jalapeño chip can power faster AI responses than the competition",
           "Granite 4.2 LLMs: How They're Built",
           "Wan 3.0 in ComfyUI: Native 30-Second Video with Omni-Reference Control"]
_tk = [dedupe.tokenize(t) for t in _titles]
_rare = dedupe.rare_tokens(_tk) & dedupe.proper_tokens(_titles)
check("악센트가 붙은 이름이 한 토큰으로 잡힌다", "jalapeno" in _tk[0], True)
check("드문 고유명사만 사건 식별에 쓰인다", _rare, {"jalapeno"})
check("같은 칩 기사 3건이 묶인다",
      all(dedupe.similarity(_tk[0], _tk[k], _rare) >= 0.5 for k in (1, 2)), True)
check("흔한 단어(built)로는 안 묶인다", dedupe.similarity(_tk[1], _tk[3], _rare) >= 0.5, False)

_noise = ["What's new in Emacs 31.1", "Ask HN: Why do corporate failures punish the wrong people",
          "Trump bought SpaceX shares two weeks after blockbuster IPO"]
_k3, _ = screen.screen([item(t, tier="T2") for t in _noise], {}, 0.6, 0.4)
check("무관한 글은 여전히 걸러진다", len(_k3), 0)

check("world model이 비디오로 잡힌다",
      "video" in screen.infer_topics(item("A world model for long video generation")), True)
check("inpainting이 이미지로 잡힌다",
      "image" in screen.infer_topics(item("A guide to inpainting with FLUX")), True)

print("\n내용 없는 글")
from src import collect as _c                                # noqa: E402
_bp = _c._strip_html("&#32; submitted by &#32; /u/someone [link] &#32; [comments]")
check("레딧 꼬리말이 제거된다", _bp, "")
def _rd(title, raw):
    it = item(title, tier="T2")
    it.summary_raw = _c._strip_html(raw)
    it.extra = {"pre_filtered": True}
    return it
_k, _d = screen.screen([
    _rd("That Good Stuff", "&#32; submitted by &#32; /u/x [link] &#32; [comments]"),
    _rd("Face Detailer With PerRowMasking",
        "First Video with Face Detailer, second without. You need "
        "https://github.com/Carasibana/ComfyUI-H3-FaceRefine to run this workflow."),
], {}, 0.6, 0.4)
check("제목뿐인 작품 공유 글은 빠진다", [i.drop_reason for i in _d], ["내용 없음"])
check("본문이 있는 글은 남는다", len(_k), 1)

# 규칙이 너무 넓으면 볼 만한 것까지 걸린다 — 세 가지 면제를 확인한다
_exempt = [_rd("Gaussian Splatting test with MiniMax H3", ""),      # 제목에 용어가 있음
           _rd("If dean ran into Harry Potter", "")]                # 아무 신호 없음
_k2, _d2 = screen.screen(_exempt, {}, 0.6, 0.4)
check("제목에 주제 용어가 있으면 본문이 없어도 남는다", len(_k2), 1)
check("아무 신호가 없으면 빠진다", [i.drop_reason for i in _d2], ["내용 없음"])

_official = _rd("Quantization-Aware Healing: a 4-bit model that outperforms", "")
_official.tier = "T1"
check("T0·T1 공식 소스는 면제된다", len(screen.screen([_official], {}, 0.6, 0.4)[0]), 1)

print("\n논문 초록 길이")
check("소스가 요약 길이를 정할 수 있다",
      len(_c._strip_html("x" * 3000, 2000)), 2000)
check("기본값은 600자", len(_c._strip_html("x" * 3000)), 600)
check("코드 공개 문구가 초록 끝에 있어도 잡힌다",
      bool(_c.CODE_HINT.search("..." * 300 + " Code is available at https://github.com/a/b")), True)

print("\n광고 필터")
blocklist = {"domains": ["toolify.ai"], "title_patterns": [r"(?i)^top\s*\d+"]}
check("차단 도메인",
      bool(screen.is_blocked(item("Some post", url="https://toolify.ai/x"), blocklist)), True)
check("차단 제목패턴",
      bool(screen.is_blocked(item("Top 10 AI tools"), blocklist)), True)
check("낚시 제목은 점수가 높다", screen.ad_score(item("You won't believe this INSANE tool!!")) >= 0.6, True)
check("정상 제목은 점수가 낮다", screen.ad_score(item("Runway launches Gen-5 video model")) < 0.3, True)
check("strict 소스는 가산점", screen.ad_score(item("Free trial now", ad_filter="strict"))
      > screen.ad_score(item("Free trial now")), True)

print("\n번역")
gl = translate.load_glossary(Path(__file__).resolve().parent.parent / "config" / "glossary.json")
check("용어 사전이 읽힌다", len(gl["protect"]) > 20 and len(gl["terms"]) > 10, True)

prot = translate._protect("Stable Diffusion and ComfyUI updates", gl["protect"])
check("고유명사가 태그로 보호된다", "<x>Stable Diffusion</x>" in prot, True)
check("긴 이름이 먼저 잡힌다 (Stable만 잡히면 안 됨)", "<x>Stable</x>" in prot, False)
check("태그 제거", translate._unprotect("<x>FLUX</x> 공개"), "FLUX 공개")

check("용어 통일", translate.enforce_terms("새 diffusion model 공개", gl["terms"]),
      "새 확산 모델 공개")

check("코드 펜스가 붙어도 파싱된다",
      translate._parse_json_array('```json\n[{"i":0,"title_ko":"제목"}]\n```')[0]["title_ko"],
      "제목")
check("앞뒤 설명이 붙어도 파싱된다",
      translate._parse_json_array('다음과 같습니다: [{"i":1}] 끝')[0]["i"], 1)

it_a = item("Runway launches Gen-5")
cache = {it_a.uid: {"engine": "claude", "title_ko": "Runway, Gen-5 공개",
                    "summary_ko": "요약", "bullets": ["a"]}}
todo = translate.apply_cache([it_a], cache, "claude")
check("캐시가 적중하면 호출 대상에서 빠진다", len(todo), 0)
check("캐시 값이 채워진다", it_a.title_ko, "Runway, Gen-5 공개")
check("엔진이 다르면 캐시를 안 쓴다",
      len(translate.apply_cache([item("Runway launches Gen-5")], cache, "deepl")), 1)

engine, msg = translate.translate([item("X")], {"engine": "none"}, Path("."))
check("engine none이면 건너뛴다", msg, "번역 안 함")

import os
ROOT = Path(__file__).resolve().parent.parent
for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "DEEPL_API_KEY"):
    os.environ.pop(key, None)
for eng in ("claude", "gemini", "deepl"):
    _, msg = translate.translate([item(f"Runway launches Gen-{eng}")], {"engine": eng}, ROOT)
    check(f"{eng}: 키가 없어도 예외 없이 메시지만 남는다", "건너뜀" in msg, True)

check("등록된 엔진 3개", sorted(translate.ENGINES), ["claude", "deepl", "gemini"])
check("알 수 없는 엔진은 메시지로 처리",
      "알 수 없는" in translate.translate([item("X")], {"engine": "gpt9"}, ROOT)[1], True)
_tl, _tlmsg = translate.make_tldr([item("X")], {"engine": "deepl"})
check("deepl은 TL;DR을 만들지 않는다", _tl, [])
check("이유가 함께 돌아온다", "TL;DR을 만들지 않음" in _tlmsg, True)

prompt = translate._build_user_prompt([item("Runway launches Gen-5", summary="A new model.")], gl)
check("프롬프트에 고유명사 목록이 들어간다", "ComfyUI" in prompt, True)
check("프롬프트에 항목이 들어간다", "Runway launches Gen-5" in prompt, True)

rows = [{"i": 0, "title_ko": "가", "summary_ko": "나", "bullets": ["1", "2", "3", "4"]},
        {"i": 99, "title_ko": "버려야 함"}]
targets = [item("A")]
translate._apply_rows(rows, targets)
check("범위 밖 인덱스는 무시된다", targets[0].title_ko, "가")
check("불릿은 3개로 자른다", len(targets[0].bullets), 3)

print("\n묶음 분할·부분 실패")
import httpx as _httpx, json as _json
translate.time.sleep = lambda _s: None          # 테스트에서 대기 생략
_calls = {"n": 0}
def _second_chunk_fails(user):
    _calls["n"] += 1
    if "T6" in user:
        raise _httpx.ReadTimeout("timed out")
    return _json.dumps([{"i": i, "title_ko": f"번역{i}"} for i in range(6)])

_items = [item(f"T{i}", url=f"https://e.com/{i}") for i in range(12)]
_fails = translate._run_llm(_items, {"chunk_size": 6, "retries": 1}, gl, _second_chunk_fails)
check("한 묶음이 죽어도 나머지는 번역된다", sum(1 for i in _items if i.title_ko), 6)
check("실패 사유가 기록된다", _fails, ["ReadTimeout"])
check("실패한 묶음은 원문 유지", all(not i.title_ko for i in _items[6:]), True)
_cache = {}
translate.store_cache(_items, _cache, "gemini")
check("캐시에는 성공분만 저장된다", len(_cache), 6)

print("\n오류 진단")
class _R:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._p = status, payload
        self.text = text or _json.dumps(payload or {})
    def json(self):
        if self._p is None:
            raise ValueError("no json")
        return self._p

_seen = []
def _post_400_then_ok(url, **kw):
    _seen.append(kw["json"]["generationConfig"])
    if "thinkingConfig" in kw["json"]["generationConfig"]:
        return _R(400, {"error": {"message": 'Unknown name "thinkingLevel"'}})
    return _R(200, {"candidates": [{"content": {"parts": [{"text": "[]"}]}}]})

translate.httpx.post = _post_400_then_ok
translate._gemini_call("K", "m", "sys", "user", 4000, thinking="low")
check("thinkingConfig는 generationConfig 안에 중첩된다",
      _seen[0]["thinkingConfig"], {"thinkingLevel": "low"})
check("거부당하면 그 항목만 빼고 재시도한다", "thinkingConfig" in _seen[1], False)

translate.httpx.post = lambda url, **kw: _R(
    400, {"error": {"message": "API key not valid."}})
_f = translate._run_llm([item("X")], {"chunk_size": 6, "retries": 0}, gl,
                        lambda u: translate._gemini_call("K", "m", "s", u, 4000, thinking=""))
check("실패 사유에 API가 준 설명이 남는다", "API key not valid" in _f[0], True)

from src import collect as _collect                          # noqa: E402
class _ErrResp:
    status_code = 400
    text = "<feed><entry><summary>sortBy must be one of...</summary></entry></feed>"
check("수집 오류에도 응답 본문이 붙는다",
      "sortBy must be one of" in _collect._http_detail(_ErrResp()), True)

print("\n혼잡 대응")
_tried = []
def _busy_first_two(url, **kw):
    _m = url.split("/models/")[1].split(":")[0]
    _tried.append(_m)
    if _m in ("m1", "m2"):
        return _R(503, {"error": {"message": "This model is currently experiencing high demand."}})
    return _R(200, {"candidates": [{"content": {"parts": [{"text": "[]"}]}}]})

translate.httpx.post = _busy_first_two
translate._gemini_with_fallback("K", ["m1", "m2", "m3"], "sys", "user", 3000, "low")
check("503이면 다음 모델로 넘어간다", _tried, ["m1", "m2", "m3"])

_tried.clear()
translate.httpx.post = lambda url, **kw: (
    _tried.append(url), _R(401, {"error": {"message": "API key not valid."}}))[1]
try:
    translate._gemini_with_fallback("K", ["m1", "m2", "m3"], "s", "u", 3000, "low")
except translate.ApiError as _e:
    check("401은 모델을 바꿔봐야 소용없으므로 한 번만 시도", len(_tried), 1)

_waits = []
translate.time.sleep = lambda _s: _waits.append(_s)
translate.httpx.post = lambda url, **kw: _R(503, {"error": {"message": "high demand"}})
_f = translate._run_llm([item("X")], {"chunk_size": 4, "retries": 3, "retry_base_seconds": 4},
                        gl, lambda u: translate._gemini_with_fallback("K", ["m"], "s", u, 3000, "low"))
check("재시도 간격이 4→8→16초로 늘어난다", _waits, [4.0, 8.0, 16.0])
check("503은 재시도 대상", "503" in _f[0], True)

_waits.clear()
translate.httpx.post = lambda url, **kw: _R(401, {"error": {"message": "API key not valid."}})
translate._run_llm([item("Y")], {"chunk_size": 4, "retries": 3, "retry_base_seconds": 4},
                   gl, lambda u: translate._gemini_with_fallback("K", ["m"], "s", u, 3000, "low"))
check("키 오류는 기다리지 않고 바로 포기", len(_waits), 0)

print("\n목록 페이지 긁기")
import re as _re                                             # noqa: E402
_LIST_HTML = """<html><body>
<nav><a href="/blog">Blog</a><a href="/news/customers">Customers</a></nav>
<a href="/blog/flux-video-upscale"><h3>FLUX Upscale: 2K and 4K for Video</h3></a>
<a href="/blog/martin-scorsese-bfl-advisor"></a>
<a href="/blog/flux-video-upscale">같은 글 다른 자리</a>
<footer><a href="/about">About</a></footer></body></html>"""
_got = _collect.extract_links(_LIST_HTML, "https://bfl.ai/blog", _re.compile(r"/blog/", _re.I))
check("글 링크만 뽑는다 (메뉴·꼬리말 제외)", len(_got), 2)
check("앵커 텍스트를 제목으로 쓴다",
      any(t == "FLUX Upscale: 2K and 4K for Video" for _, t in _got), True)
check("앵커가 비었으면 슬러그로 제목을 만든다",
      any(t == "Martin scorsese bfl advisor" for _, t in _got), True)

_JS_HTML = ('<script id="__NEXT_DATA__">{"posts":[{"slug":"/news/introducing-gen-5-video"}],'
            '"nav":"/news/research"}</script>')
_got2 = _collect.extract_links(_JS_HTML, "https://runway.com/news", _re.compile(r"/news/", _re.I))
check("앵커가 없으면 박힌 JSON에서 찾는다", len(_got2), 1)
check("한 단어 메뉴 경로는 제외된다", "research" in _got2[0][0], False)

_NUM = '<a href="/papers/2608.24885">Some Paper Title Here</a>'
check("슬러그 규칙을 끄면 숫자 주소도 잡힌다",
      len(_collect.extract_links(_NUM, "https://huggingface.co/papers",
                                 _re.compile(r"/papers/\d"), heuristic=False)), 1)
check("규칙을 켜면 숫자 주소는 빠진다",
      len(_collect.extract_links(_NUM, "https://huggingface.co/papers",
                                 _re.compile(r"/papers/\d"))), 0)

print("\n새 글 판별 (발행일 없는 사이트)")
import json as _j2                                            # noqa: E402
_collect.SEEN_PATH = Path("/tmp/_seen_pipeline_test.json")
if _collect.SEEN_PATH.exists():
    _collect.SEEN_PATH.unlink()

_P1 = '<a href="/blog/flux-3-video">FLUX 3 Video</a><a href="/blog/flux-erase">FLUX Erase Anything</a>'
_P2 = _P1 + '<a href="/blog/flux-4-announcement">Introducing FLUX 4</a>'
class _Page:
    def __init__(self, html): self.html = html
    def get(self, url, **kw):
        return type("R", (), {"status_code": 200, "text": self.html, "url": url,
                              "raise_for_status": lambda s: None})()
_src = {"id": "t-bfl", "name": "BFL", "tier": "T0", "topics": ["image"],
        "url": "https://bfl.ai/blog", "link_pattern": "/blog/"}

_first = ""
try:
    _collect.fetch_list(_Page(_P1), _src)
except RuntimeError as _e:
    _first = str(_e)
check("첫 실행은 기록만 하고 내보내지 않는다", "첫 실행" in _first, True)
check("변화가 없으면 새 글도 없다", len(_collect.fetch_list(_Page(_P1), _src)), 0)
_new = _collect.fetch_list(_Page(_P2), _src)
check("새 주소만 새 글로 잡힌다", [i.title for i in _new], ["Introducing FLUX 4"])
check("같은 글이 두 번 나오지 않는다", len(_collect.fetch_list(_Page(_P2), _src)), 0)

print("\n피드 자동 탐지")
from src import collect                                    # noqa: E402
class _Resp:
    def __init__(self, text, status=200, url="https://blog.example.com/"):
        self.text, self.status_code, self.url = text, status, url
        self.content = text.encode()
    def raise_for_status(self):
        if self.status_code >= 400:
            raise _httpx.HTTPStatusError("x", request=None, response=self)
class _Client:
    def __init__(self, pages): self.pages = pages
    def get(self, url, **kw):
        return _Resp(self.pages[url], url=url) if url in self.pages else _Resp("", 404, url=url)

_HOME = "https://blog.example.com/"
_HTML = '<html><head><link rel="alternate" type="application/rss+xml" href="/feed/posts.xml"></head></html>'
_RSS = ('<?xml version="1.0"?><rss version="2.0"><channel><title>t</title><item>'
        '<title>a</title><link>u</link><pubDate>Mon, 25 Aug 2026 00:00:00 GMT</pubDate>'
        '</item></channel></rss>')
check("head의 link 태그에서 피드를 찾는다",
      collect.discover_feed(_Client({_HOME: _HTML}), _HOME), _HOME + "feed/posts.xml")
check("link이 없으면 흔한 경로를 두드린다",
      collect.discover_feed(_Client({_HOME: "<html><head></head></html>", _HOME + "feed": _RSS}), _HOME),
      _HOME + "feed")
check("피드가 없으면 None", collect.discover_feed(_Client({_HOME: "<html></html>"}), _HOME), None)

print("\narXiv 질의 인코딩")
# arXiv 문서 예시 형태: 콜론·괄호는 그대로, 공백은 +, 따옴표는 %22
_captured = {}
class _ArxivClient:
    def get(self, url, **kw):
        _captured["url"] = url
        return _R(200, text='<?xml version="1.0"?><feed></feed>')
try:
    _collect.fetch_arxiv(_ArxivClient(), {"id": "a", "name": "arXiv", "tier": "T1",
                                          "topics": ["video"], "max_items": 5,
                                          "query": 'cat:cs.CV AND (abs:"video generation")'})
except Exception:
    pass                      # 빈 피드라 예외가 나도 URL은 잡혔다
_u = _captured.get("url", "")
check("공백은 +로 바뀐다", "+AND+" in _u, True)
check("따옴표는 %22로 인코딩된다", "%22video+generation%22" in _u, True)
check("콜론은 그대로 남는다 (%3A면 arXiv가 400을 낸다)", "cat:cs.CV" in _u, True)
check("괄호는 그대로 남는다", "(abs:" in _u, True)
check("https를 쓴다", _u.startswith("https://"), True)

it_b = item("Runway launches Gen-5")
check("번역 전에는 원제가 표시된다", it_b.display_title, "Runway launches Gen-5")
it_b.title_ko = "Runway, Gen-5 공개"
check("번역 후에는 한국어가 표시된다", it_b.display_title, "Runway, Gen-5 공개")


print("\n순위표 정규화")
_raw = [
    {"name": "Seedance 2.0", "model_creator": {"name": "ByteDance Seed"},
     "elo": 1269, "ci_95": 8, "rank": 1, "price_per_minute": 0.45},
    {"name": "Veo 4", "model_creator": {"name": "Google DeepMind"}, "elo": 1261, "rank": 2},
    {"name": "빈 줄", "elo": None},
]
_n = rankings._normalize(_raw, "media", 8)
check("점수 순으로 순위를 다시 매긴다", [r["rank"] for r in _n[:2]], [1, 2])
check("제작사는 중첩된 객체에서 꺼낸다", _n[0]["creator"], "ByteDance Seed")
check("분당 가격을 초당으로 바꾼다", _n[0]["price"], 0.0075)
check("가격이 없으면 None", _n[1]["price"], None)
check("점수 없는 줄은 뒤로 밀린다", _n[-1]["name"], "빈 줄")

_lang = rankings._normalize(
    [{"name": "M", "evaluations": {"artificial_analysis_intelligence_index": 71.2},
      "pricing": {"price_1m_blended_3_to_1": 22.5}}], "language", 5)
check("언어모델은 지능 지수를 점수로 쓴다", _lang[0]["score"], 71.2)
check("언어모델 가격은 100만 토큰 기준", (_lang[0]["price"], _lang[0]["price_unit"]), (22.5, "$/1M"))

_boards = [{"id": "b", "label": "L", "kind": "media", "note": "", "rows": [
    {"name": "A", "rank": 1}, {"name": "B", "rank": 2}, {"name": "C", "rank": 3}]}]
rankings._apply_deltas(_boards, {"ranks": {"b": {"A": 3, "B": 2}}})
_rows = {r["name"]: r for r in _boards[0]["rows"]}
check("두 계단 오르면 +2", _rows["A"]["delta"], 2)
check("그대로면 0", _rows["B"]["delta"], 0)
check("어제 없던 모델은 NEW", _rows["C"]["is_new"], True)

_empty = rankings.fetch({"rankings": {"enabled": False}}, Path("."))
check("꺼져 있으면 이유를 남기고 끝낸다", bool(_empty["error"]), True)


print("\n화면 만들기")
_c = item("Runway launches Gen-5", summary="Gen-5 produces up to 40 seconds.")
_c.title_ko, _c.summary_ko, _c.bullets = "Runway, Gen-5 공개", "40초까지 생성된다.", ["최대 40초"]
_c.category, _c.score = "model_release", 9.0
_brief = Brief(date_kst="2026-08-28", generated_at="", window_start="2026-08-27T07:00:00+09:00",
               window_end="2026-08-28T07:00:00+09:00", headlines=[_c], cards=[_c],
               tldr=["흐름 한 줄."], rankings={})
_page = render.render_page(_brief)
check("세부 화면이 항목마다 만들어진다", f'id="d-{_c.uid}"' in _page, True)
check("목록 항목이 세부와 연결된다", f'data-uid="{_c.uid}"' in _page, True)
check("항목마다 원문 링크가 붙는다", 'class="go"' in _page, True)
check("검색창이 첫 화면에 있다", 'id="q"' in _page, True)
check("달력이 팝오버로 붙는다", 'id="calpop"' in _page, True)

_notrans = item("Only English here", summary="Raw body text only.")
_notrans.category, _notrans.score = "minor", 1.0
_nb = Brief(date_kst="2026-08-28", generated_at="", window_start="", window_end="",
            headlines=[_notrans], cards=[_notrans], tldr=[], rankings={})
check("번역이 없으면 원문 요약을 그대로 싣는다",
      "Raw body text only." in render.render_page(_nb), True)
check("순위 탭 자리는 항상 있다", 'data-view="rank"' in _page, True)
check("키가 없으면 안내가 뜬다", "AA_API_KEY" in _page, True)
check("메일에는 스크립트가 없다", "<script" in render.render_email(_brief), False)

_evil = item("<script>alert(1)</script>", summary="x")
_evil.category, _evil.score = "minor", 1.0
_bad = Brief(date_kst="2026-08-28", generated_at="", window_start="", window_end="",
             headlines=[_evil], cards=[_evil], tldr=[], rankings={})
check("제목의 태그는 이스케이프된다", "<script>alert(1)</script>" in render.render_page(_bad), False)



print("\n지난 브리핑 색인")
_b1 = {"date_kst": "2026-08-27", "cards": [
    {"uid": "aaa", "title": "Runway launches Gen-5", "title_ko": "Runway, Gen-5 공개",
     "summary_ko": "40초까지 생성된다.", "summary_raw": "Gen-5 does 40 seconds.",
     "source_name": "Runway", "category": "model_release", "url": "https://x/1"}]}
_b2 = {"date_kst": "2026-08-28", "cards": [
    {"uid": "bbb", "title": "Kling 2.8 cuts price", "title_ko": "Kling 2.8 가격 인하",
     "summary_ko": "40% 인하.", "summary_raw": "Kling cuts price.",
     "source_name": "Kling", "category": "major_update", "url": "https://x/2"}]}
_names = ["Runway", "Gen-5", "Kling", "GitHub"]
_m = archive.build_models([_b1, _b2, _b1], _names, {"min_mentions": 2, "exclude": ["GitHub"]})
_by = {x["name"]: x for x in _m}
check("두 번 나온 이름만 세운다", sorted(_by), ["Gen-5", "Runway"])
check("최근 날짜가 기록된다", _by["Runway"]["last"], "2026-08-27")
check("제외 목록의 이름은 빠진다", "GitHub" in _by, False)
check("한 번만 나온 이름은 빠진다", "Kling" in _by, False)

_one = archive.build_models([{"date_kst": "2026-08-28", "cards": [
    {"uid": "c", "title": "Sorare raises funding", "summary_raw": "", "url": "u",
     "source_name": "s", "category": "industry"}]}] * 2, ["Sora"], {"min_mentions": 1})
check("이름이 다른 단어에 묻혀 있으면 잡지 않는다 (Sora ≠ Sorare)", _one, [])

_e = archive._entry({"uid": "u1", "title": "T", "title_ko": "제목",
                     "summary_ko": "요\n약  입니다", "source_name": "S",
                     "category": "workflow", "url": "https://x"}, "2026-08-28")
check("색인은 한국어 제목을 우선한다", _e["t"], "제목")
check("색인은 원제도 함께 남긴다", _e["o"], "T")
check("줄바꿈은 한 칸으로 눌린다", _e["s"], "요 약 입니다")


print("\n알림·피드")
import os as _os                                                    # noqa: E402
for _k in ("NTFY_TOPIC", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"):
    _os.environ.pop(_k, None)
check("설정이 없으면 조용히 건너뛴다", notify.send_all(_brief), "설정된 알림 없음")
_os.environ["NTFY_TOPIC"] = "한글주제어"
_ok, _msg = notify.send_ntfy(_brief)
check("한글 주제어는 보내기 전에 막는다", (_ok, "영문" in _msg), (False, True))
_os.environ.pop("NTFY_TOPIC")
check("알림 본문은 제목 세 줄까지", len(notify._lines(_brief)) <= 3, True)

# 깃허브 액션은 등록하지 않은 Secret도 빈 문자열로 넣어준다.
# 그래서 기본값이 무시되고 주소가 "/주제어"가 되어 발송이 통째로 실패했다.
_os.environ["NTFY_SERVER"] = ""
check("빈 서버 주소는 기본값으로 되돌린다", notify._server(), "https://ntfy.sh")
_os.environ["NTFY_SERVER"] = "  "
check("공백만 있어도 기본값", notify._server(), "https://ntfy.sh")
_os.environ["NTFY_SERVER"] = "my.ntfy.example/"
check("http가 빠져 있으면 붙여준다", notify._server(), "https://my.ntfy.example")
_os.environ.pop("NTFY_SERVER")

import tempfile, json as _json                                      # noqa: E402
with tempfile.TemporaryDirectory() as _tmp:
    _root = Path(_tmp)
    (_root / "data").mkdir()
    (_root / "data" / "2026-08-28.json").write_text(
        _json.dumps({"date_kst": "2026-08-28", "cards": [
            {"uid": "z9", "title": "T", "title_ko": "제목", "summary_ko": "요약",
             "category": "workflow", "url": "https://x/1", "source_name": "S"}]}),
        encoding="utf-8")
    _xml = render.render_feed(_root, "https://example.github.io/aibrief")
    check("피드에 항목이 들어간다", "<item>" in _xml, True)
    check("피드 링크는 그 항목으로 바로 간다",
          "https://example.github.io/aibrief/archive/2026-08-28.html#i-z9" in _xml, True)
    import xml.etree.ElementTree as _ET                              # noqa: E402
    check("피드가 XML로 파싱된다", _ET.fromstring(_xml).tag, "rss")

print(f"\n  통과 {PASSED} · 실패 {FAILED}\n")
sys.exit(1 if FAILED else 0)
