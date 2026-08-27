"""
수집기 — sources.yaml에 적힌 소스를 실제로 호출해서 Item 리스트로 바꾼다.

설계 원칙 세 가지
  1) 소스 하나가 죽어도 전체가 죽지 않는다. 예외는 그 소스 안에서만 잡고 리포트에 남긴다.
  2) 소스 타입마다 함수 하나. 새 타입이 필요하면 함수를 추가하고 FETCHERS에 등록만 한다.
  3) 네트워크는 느리므로 소스들을 스레드로 동시에 호출한다.
     (파이썬의 GIL은 CPU 연산만 막고, 응답을 기다리는 동안에는 다른 스레드가 돈다.)
"""

from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import re
import time
from urllib.parse import quote_plus, urljoin, urlparse
from typing import Callable

import feedparser
import httpx

import json
from pathlib import Path

from .models import Item, SourceReport

SEEN_PATH = Path(__file__).resolve().parent.parent / "data" / "seen.json"
SEEN_MAX_PER_SOURCE = 400

UA = "visual-ai-brief/0.1 (+personal daily digest)"
TIMEOUT = 25.0

GITHUB_RELEASES = "https://github.com/{repo}/releases.atom"
YOUTUBE_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
ARXIV_API = (
    "https://export.arxiv.org/api/query"
    "?search_query={q}&sortBy=submittedDate&sortOrder=descending&max_results={n}"
)
HN_API = (
    "https://hn.algolia.com/api/v1/search_by_date"
    "?query={q}&tags=story&numericFilters=points>{p}&hitsPerPage=30"
)
REDDIT_RSS = "https://www.reddit.com/r/{sub}/{listing}/.rss?t={period}"


# --------------------------------------------------------------------------
# 이미 본 주소 기록 — 발행일이 없는 사이트의 '새 글' 판별에 쓴다
# --------------------------------------------------------------------------

def _load_all_seen() -> dict:
    try:
        return json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _load_seen(source_id: str) -> dict:
    return _load_all_seen().get(source_id, {})


def _save_seen(source_id: str, entries: dict) -> None:
    if len(entries) > SEEN_MAX_PER_SOURCE:
        newest = sorted(entries.items(), key=lambda kv: kv[1], reverse=True)
        entries = dict(newest[:SEEN_MAX_PER_SOURCE])
    store = _load_all_seen()
    store[source_id] = entries
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")


# --------------------------------------------------------------------------
# 공통 헬퍼
# --------------------------------------------------------------------------

def _http_detail(r: httpx.Response) -> str:
    """
    오류 응답의 본문 앞부분을 뽑는다.

    처음엔 상태 코드만 기록했는데, 실제로 arXiv가 400을 돌려줬을 때
    "왜"를 알 수가 없었다. 서버는 대개 본문에 이유를 적어 보낸다.
    """
    body = re.sub(r"<[^>]+>", " ", r.text[:600])
    body = re.sub(r"\s+", " ", body).strip()
    return f"HTTP {r.status_code} · {body[:180]}" if body else f"HTTP {r.status_code}"


def _raise_for_status(r: httpx.Response) -> None:
    if r.status_code >= 400:
        raise RuntimeError(_http_detail(r))


def _entry_time(entry) -> dt.datetime | None:
    """feedparser가 준 시각 구조체를 UTC datetime으로. 없으면 None."""
    struct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not struct:
        return None
    return dt.datetime(*struct[:6], tzinfo=dt.timezone.utc)


# 레딧 피드는 모든 글 끝에 같은 꼬리를 붙인다. 내용이 아니므로 떼어낸다.
REDDIT_BOILERPLATE = re.compile(
    r"(&#32;|\s)*(submitted by|/u/[\w-]+|\[link\]|\[comments\])(\s|&#32;)*", re.I)


def _strip_html(text: str, limit: int = 600) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = REDDIT_BOILERPLATE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _mk(src: dict, *, title: str, url: str, published: dt.datetime,
        summary: str = "", extra: dict | None = None) -> Item:
    """소스 설정 + 개별 항목 정보 → Item. 소스 공통 필드를 여기서 한 번에 붙인다."""
    return Item(
        title=(title or "").strip(),
        url=url,
        source_id=src["id"],
        source_name=src["name"],
        tier=src.get("tier", "T3"),
        topics=list(src.get("topics", [])),
        published=published,
        summary_raw=summary,
        signal=src.get("signal", "normal"),
        ad_filter=src.get("ad_filter", "normal"),
        extra={**(extra or {}),
               # 소스가 이미 주제 질의로 걸러 가져온 경우 표시해둔다.
               # 아래 screen.py가 이걸 보고 주제 필터를 건너뛴다.
               **({"pre_filtered": True} if src.get("skip_topic_filter") else {}),
               **({"require_code": True} if src.get("require_code") else {})},
    )


def _from_feed(client: httpx.Client, src: dict, url: str) -> list[Item]:
    """RSS/Atom 하나를 Item 리스트로. rss·github·youtube·arxiv가 전부 이걸 쓴다."""
    r = client.get(url, follow_redirects=True)
    _raise_for_status(r)
    feed = feedparser.parse(r.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"피드 파싱 실패: {type(feed.bozo_exception).__name__}")

    items: list[Item] = []
    for e in feed.entries:
        published = _entry_time(e)
        if not published:
            continue  # 시각을 모르면 24시간 창에 넣을 수 없다
        link = getattr(e, "link", "")
        if not link:
            continue
        # 요약을 얼마나 남길지는 소스가 정한다.
        # arXiv 초록은 1,500자쯤 되고 "code is available at ..."이 대개 맨 끝에 온다.
        # 600자로 자르면 그 문구가 잘려서 코드 공개 논문이 전부 미공개로 판정됐다.
        limit = int(src.get("summary_limit", 600))
        summary = _strip_html(
            getattr(e, "summary", "") or getattr(e, "description", ""), limit)
        items.append(_mk(src, title=getattr(e, "title", ""), url=link,
                         published=published, summary=summary))
    return items


# --------------------------------------------------------------------------
# 소스 타입별 수집기
# --------------------------------------------------------------------------

FEED_LINK = re.compile(
    r"""<link[^>]+type=["']application/(?:rss|atom)\+xml["'][^>]*>""", re.I)
HREF = re.compile(r"""href=["']([^"']+)["']""", re.I)

# 사이트가 <link>를 안 걸어둔 경우에 시도해볼 흔한 경로들
COMMON_FEED_PATHS = ("/feed", "/rss", "/rss.xml", "/feed.xml", "/index.xml",
                     "/atom.xml", "/blog/rss.xml", "/feed/")


def discover_feed(client: httpx.Client, page_url: str) -> str | None:
    """
    페이지 HTML에서 RSS/Atom 주소를 찾아낸다. RSS 리더가 하는 일과 같다.

    이게 필요한 이유: 피드 주소는 사이트마다 제각각이고 개편 때 자주 바뀐다.
    설정 파일에 손으로 적어둔 주소는 언젠가 404가 된다. 페이지에서 찾아내면
    주소가 바뀌어도 알아서 따라간다.
    """
    try:
        r = client.get(page_url, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return None

    for tag in FEED_LINK.findall(r.text[:200_000]):
        m = HREF.search(tag)
        if m:
            return urljoin(str(r.url), m.group(1))

    # <link>가 없으면 흔한 경로를 직접 두드려 본다
    for path in COMMON_FEED_PATHS:
        candidate = urljoin(str(r.url), path)
        try:
            probe = client.get(candidate, follow_redirects=True)
            if probe.status_code == 200 and feedparser.parse(probe.content).entries:
                return candidate
        except httpx.HTTPError:
            continue
    return None


def fetch_rss(client: httpx.Client, src: dict) -> list[Item]:
    try:
        return _from_feed(client, src, src["url"])
    except RuntimeError as e:
        # 적어둔 주소가 죽었으면 사이트에서 새 주소를 찾아본다
        if "HTTP 404" not in str(e) and "HTTP 410" not in str(e):
            raise
        found = discover_feed(client, src["url"].rsplit("/", 1)[0] or src["url"])
        if not found:
            raise RuntimeError(f"피드 주소 만료 · 자동 탐지 실패 ({e})") from e
        items = _from_feed(client, src, found)
        for it in items:
            it.extra["discovered_feed"] = found
        return items


def fetch_github_releases(client: httpx.Client, src: dict) -> list[Item]:
    """GitHub의 모든 저장소는 releases.atom을 제공한다. 오픈 모델 추적에 가장 안정적."""
    items = _from_feed(client, src, GITHUB_RELEASES.format(repo=src["repo"]))
    for it in items:
        it.title = f"{src['repo'].split('/')[-1]} {it.title}"
        it.extra["repo"] = src["repo"]
        it.extra["kind"] = "release"
    return items


def fetch_youtube(client: httpx.Client, src: dict) -> list[Item]:
    """채널 RSS는 API 키도 쿼터도 필요 없다. channel_id만 있으면 된다."""
    cid = src.get("channel_id")
    if not cid:
        raise ValueError("channel_id 비어 있음 — scripts/check_sources.py --write 먼저 실행")
    items = _from_feed(client, src, YOUTUBE_FEED.format(cid=cid))
    for it in items:
        it.extra["kind"] = "video"
    return items


CODE_HINT = re.compile(
    r"(github\.com|huggingface\.co|"
    r"code (is |will be )?(publicly )?(available|released)|"
    r"we (will )?releases? (our )?(code|models?|weights)|"
    r"project page)", re.I)


def fetch_arxiv(client: httpx.Client, src: dict) -> list[Item]:
    # 검색어에 공백·따옴표·괄호가 들어 있어서 반드시 URL 인코딩을 해야 한다.
    # (처음엔 httpx.QueryParams(...).get()을 썼는데 그건 '디코딩된' 값을 돌려줘서
    #  인코딩되지 않은 문자열이 그대로 URL에 들어갔고 arXiv가 400을 반환했다.)
    # arXiv 문서의 예시 형태에 맞춘다:
    #   콜론·괄호는 그대로, 공백은 +, 따옴표만 %22 로 인코딩.
    #   처음엔 quote_plus로 전부 인코딩했다가(콜론까지 %3A) 400을 받았다.
    url = ARXIV_API.format(q=quote_plus(src["query"], safe=":()"),
                           n=src.get("max_items", 15))
    # arXiv는 짧은 간격의 연속 요청에 429를 준다(3초 간격을 권장한다).
    # check_sources.py를 돌린 직후 run.py를 돌리면 바로 걸린다 — 실제로 그랬다.
    for attempt in range(3):
        try:
            items = _from_feed(client, src, url)
            break
        except RuntimeError as e:
            if "HTTP 429" not in str(e) or attempt == 2:
                raise
            time.sleep(4 * (attempt + 1))
    for it in items:
        it.extra["kind"] = "paper"
    return items


def fetch_hn(client: httpx.Client, src: dict) -> list[Item]:
    """
    Hacker News는 Algolia가 무료 검색 API를 제공한다. 키·쿼터·차단이 없다.
    같은 글이 여러 키워드에 걸릴 수 있으므로 objectID로 중복을 먼저 없앤다.
    """
    seen: dict[str, Item] = {}
    for q in src.get("queries", []):
        r = client.get(HN_API.format(q=q, p=src.get("min_points", 30)))
        _raise_for_status(r)
        for hit in r.json().get("hits", []):
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
            if hit["objectID"] in seen:
                continue
            seen[hit["objectID"]] = _mk(
                src,
                title=hit.get("title", ""),
                url=url,
                published=dt.datetime.fromtimestamp(hit["created_at_i"], dt.timezone.utc),
                summary=_strip_html(hit.get("story_text", "")),
                extra={"points": hit.get("points", 0),
                       "comments": hit.get("num_comments", 0),
                       "hn_id": hit["objectID"]},
            )
    return list(seen.values())


def fetch_reddit(client: httpx.Client, src: dict) -> list[Item]:
    """
    레딧은 데이터센터 IP를 차단한다. GitHub Actions는 Azure IP라 403이 잘 난다.
    그래서 여기서는 실패를 '예외'가 아니라 '건너뜀'으로 처리한다.
    fallback: skip 이면 브리핑은 그대로 나가고 리포트에만 표시된다.
    """
    url = REDDIT_RSS.format(sub=src["subreddit"],
                            listing=src.get("listing", "top"),
                            period=src.get("period", "day"))
    try:
        return _from_feed(client, src, url)
    except RuntimeError as e:
        if ("HTTP 403" in str(e) or "HTTP 429" in str(e)) and src.get("fallback") == "skip":
            raise RuntimeError("레딧 차단(데이터센터 IP) — 건너뜀") from e
        raise


def fetch_api(client: httpx.Client, src: dict) -> list[Item]:
    """Civitai처럼 JSON을 그대로 주는 소스."""
    r = client.get(src["url"], follow_redirects=True)
    _raise_for_status(r)
    data = r.json()
    rows = data.get("items", data if isinstance(data, list) else [])
    items: list[Item] = []
    for row in rows:
        # Civitai는 모델 객체에 날짜가 없고 modelVersions 안에 들어 있다.
        # 이걸 몰라서 전부 걸러지는 바람에 첫 실행에서 0건이 나왔다.
        versions = row.get("modelVersions") or []
        published = (row.get("publishedAt") or row.get("createdAt")
                     or (versions[0].get("publishedAt") if versions else None)
                     or (versions[0].get("createdAt") if versions else None))
        if not published:
            continue
        ts = dt.datetime.fromisoformat(published.replace("Z", "+00:00"))
        stats = row.get("stats", {})
        items.append(_mk(
            src,
            title=row.get("name", ""),
            url=f"https://civitai.com/models/{row.get('id')}",
            published=ts,
            summary=_strip_html(row.get("description", "")),
            extra={"downloads": stats.get("downloadCount", 0),
                   "rating": stats.get("rating", 0)},
        ))
    return items


# ---------------------------------------------------------------------------
#  피드가 없는 사이트 — 목록 페이지에서 글 링크를 긁는다
# ---------------------------------------------------------------------------

ANCHOR = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
# Next.js 같은 프레임워크는 링크를 HTML이 아니라 페이지에 박아둔 JSON에 담는다.
JSON_PATH = re.compile(r'["\'](/[a-z0-9][a-z0-9/_-]{6,120})["\']', re.I)


def _slug_to_title(path: str) -> str:
    """주소 끝의 슬러그를 제목처럼 되돌린다. 앵커 텍스트가 비어 있을 때 쓴다."""
    slug = path.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"[-_]+", " ", slug).strip()
    return slug[:1].upper() + slug[1:] if slug else ""


def _looks_like_article(path: str) -> bool:
    """
    목록 페이지에는 글 링크뿐 아니라 메뉴·꼬리말 링크도 섞여 있다.
    글 주소는 대개 여러 단어를 이어붙인 슬러그다 — /news/introducing-luma-scenes.
    반면 메뉴는 /news/customers 처럼 한 단어다.
    """
    slug = path.rstrip("/").rsplit("/", 1)[-1]
    return "-" in slug or len(slug) >= 14


def extract_links(html: str, base_url: str, pattern: re.Pattern,
                  heuristic: bool = True) -> list[tuple[str, str]]:
    """
    (주소, 제목) 목록을 뽑는다. 앵커를 먼저 보고, 없으면 박힌 JSON을 훑는다.

    heuristic=False로 두면 '여러 단어 슬러그' 규칙을 끈다.
    Hugging Face Papers처럼 주소가 /papers/2608.24885 로 숫자인 곳에 쓴다.
    """
    found: dict[str, str] = {}

    for href, inner in ANCHOR.findall(html):
        url = urljoin(base_url, href.split("#")[0])
        path = urlparse(url).path
        if not pattern.search(path) or (heuristic and not _looks_like_article(path)):
            continue
        title = re.sub(r"<[^>]+>", " ", inner)
        title = re.sub(r"\s+", " ", title).strip()
        if len(title) < 8:
            title = _slug_to_title(path)
        found.setdefault(url, title)

    if not found:
        # 앵커가 없으면 JavaScript로 그리는 페이지다. 박혀 있는 JSON에서 경로를 찾는다.
        for path in JSON_PATH.findall(html):
            if not pattern.search(path) or (heuristic and not _looks_like_article(path)):
                continue
            url = urljoin(base_url, path)
            found.setdefault(url, _slug_to_title(path))

    return list(found.items())


def fetch_list(client: httpx.Client, src: dict) -> list[Item]:
    """
    RSS가 없는 공식 사이트의 목록 페이지를 긁는다.

    날짜가 문제다. 목록 페이지에는 발행일이 없는 경우가 많고, 있어도 사이트마다
    형식이 다르다. 그래서 날짜를 파싱하는 대신 '처음 본 시각'을 발행일로 쓴다.
    한 번 본 주소는 data/seen.json에 적어두고, 다음부터는 새 주소만 새 글로 친다.

    이 방식의 대가: 처음 한 번은 전부 '이미 본 것'으로 기록만 하고 아무것도 내보내지
    않는다. 그러지 않으면 첫 실행에 지난 1년 치가 오늘 뉴스로 쏟아진다.
    """
    r = client.get(src["url"], follow_redirects=True)
    _raise_for_status(r)

    pattern = re.compile(src.get("link_pattern", r"/(news|blog|posts?|updates?)/"), re.I)
    links = extract_links(r.text, str(r.url), pattern,
                          heuristic=src.get("link_heuristic", True))
    if not links:
        raise RuntimeError("목록에서 글 링크를 찾지 못함 · link_pattern 확인 필요")

    seen = _load_seen(src["id"])
    now = dt.datetime.now(dt.timezone.utc)
    fresh = [(u, t) for u, t in links if u not in seen]

    if not seen:
        # 첫 실행 — 지금 있는 건 전부 '과거'로 간주하고 기록만 한다
        _save_seen(src["id"], {u: now.isoformat() for u, _ in links})
        raise RuntimeError(f"첫 실행 · 링크 {len(links)}건 기록 (다음 실행부터 새 글만)")

    for u, _ in fresh:
        seen[u] = now.isoformat()
    _save_seen(src["id"], seen)

    return [_mk(src, title=t, url=u, published=now,
                summary="", extra={"kind": "listing"})
            for u, t in fresh]


def fetch_html(client: httpx.Client, src: dict) -> list[Item]:
    """
    RSS 주소를 모르는 사이트. 먼저 피드가 숨어 있는지 찾아본다.

    처음에는 '개별 스크래퍼를 붙여야 한다'고 보고 그냥 건너뛰었는데,
    실제로 돌려보니 이런 소스가 13개나 됐다. 그중 상당수는 페이지에
    피드 링크를 걸어두고 있을 뿐 주소를 몰랐던 것이다.
    자동 탐지가 성공하면 스크래퍼 없이 그대로 수집된다.
    """
    found = discover_feed(client, src["url"])
    if not found:
        raise RuntimeError("피드 없음 · 개별 스크래퍼 필요")
    items = _from_feed(client, src, found)
    for it in items:
        it.extra["discovered_feed"] = found
    return items


def fetch_imap(client: httpx.Client, src: dict) -> list[Item]:
    raise RuntimeError("메일 수집 미구현 (4주차 예정)")


FETCHERS: dict[str, Callable[[httpx.Client, dict], list[Item]]] = {
    "rss": fetch_rss,
    "github_releases": fetch_github_releases,
    "youtube": fetch_youtube,
    "arxiv": fetch_arxiv,
    "hn": fetch_hn,
    "reddit": fetch_reddit,
    "api": fetch_api,
    "html": fetch_html,
    "list": fetch_list,
    "imap": fetch_imap,
}


# --------------------------------------------------------------------------
# 오케스트레이션
# --------------------------------------------------------------------------

def collect_one(client: httpx.Client, src: dict) -> tuple[list[Item], SourceReport]:
    rep = SourceReport(source_id=src["id"], source_name=src["name"], tier=src.get("tier", "?"))
    started = time.perf_counter()
    items: list[Item] = []
    try:
        fetcher = FETCHERS.get(src.get("type", ""))
        if fetcher is None:
            raise ValueError(f"알 수 없는 소스 타입: {src.get('type')}")
        items = fetcher(client, src)
        rep.collected = len(items)
    except Exception as e:  # noqa: BLE001 — 소스 하나의 실패가 전체를 멈추면 안 된다
        rep.ok = False
        # RuntimeError는 우리가 만든 설명이라 타입 이름을 붙이면 읽기만 나빠진다.
        rep.error = (str(e) if isinstance(e, RuntimeError) else f"{type(e).__name__}: {e}")[:200]
    rep.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return items, rep


def collect_all(sources: list[dict], max_workers: int = 8) -> tuple[list[Item], list[SourceReport]]:
    """활성 소스 전체를 동시에 호출한다. 순차 실행이면 몇 분, 동시 실행이면 20~40초."""
    enabled = [s for s in sources if s.get("enabled", True)]
    all_items: list[Item] = []
    reports: list[SourceReport] = []

    with httpx.Client(headers={"User-Agent": UA}, timeout=TIMEOUT) as client:
        with cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(collect_one, client, s): s for s in enabled}
            for fut in cf.as_completed(futures):
                items, rep = fut.result()
                all_items.extend(items)
                reports.append(rep)

    reports.sort(key=lambda r: (r.tier, r.source_id))
    return all_items, reports
