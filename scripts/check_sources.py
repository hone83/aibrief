#!/usr/bin/env python3
"""
소스 헬스체크 · 비주얼 AI 데일리 브리핑

config/sources.yaml에 등록된 모든 소스를 실제로 한 번씩 호출해서
  - 살아 있는지 (HTTP 응답)
  - 파싱되는지 (항목이 뽑히는지)
  - 신선한지 (최신 항목 날짜)
를 확인하고 표로 출력한다. 유튜브 handle은 channel_id로 자동 해석해
sources.yaml의 해당 줄만 고쳐 써넣는다 (주석은 보존된다).

    pip install pyyaml httpx feedparser
    python scripts/check_sources.py            # 검사만
    python scripts/check_sources.py --write    # 유튜브 channel_id를 파일에 채워 넣음

소스를 추가한 다음에는 항상 이걸 먼저 돌린다. 파이프라인에 넣기 전에
죽은 소스를 걸러내는 게 목적이다.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import feedparser
import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.collect import discover_feed          # noqa: E402  수집기와 같은 로직을 쓴다

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "config" / "sources.yaml"

UA = "visual-ai-brief/0.1 (personal daily digest; contact: you@example.com)"
TIMEOUT = 20.0
NOW = dt.datetime.now(dt.timezone.utc)

GITHUB_RELEASES = "https://github.com/{repo}/releases.atom"
YOUTUBE_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
ARXIV_API = "http://export.arxiv.org/api/query?search_query={q}&sortBy=submittedDate&sortOrder=descending&max_results={n}"
from urllib.parse import quote_plus            # noqa: E402
HN_API = "https://hn.algolia.com/api/v1/search_by_date?query={q}&tags=story&numericFilters=points>{p}"
REDDIT_RSS = "https://www.reddit.com/r/{sub}/{listing}/.rss?t={period}"


@dataclass
class Result:
    sid: str
    name: str
    tier: str
    ok: bool
    items: int = 0
    latest: dt.datetime | None = None
    detail: str = ""
    resolved_channel_id: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def stale_days(self) -> int | None:
        if not self.latest:
            return None
        return (NOW - self.latest).days


def parse_feed(client: httpx.Client, url: str) -> tuple[int, dt.datetime | None, str]:
    """RSS/Atom 하나를 가져와 (항목수, 최신시각, 메시지)를 돌려준다."""
    r = client.get(url, follow_redirects=True)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    if feed.bozo and not feed.entries:
        return 0, None, f"파싱 실패: {type(feed.bozo_exception).__name__}"
    latest = None
    for e in feed.entries:
        struct = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
        if struct:
            ts = dt.datetime(*struct[:6], tzinfo=dt.timezone.utc)
            latest = ts if latest is None or ts > latest else latest
    return len(feed.entries), latest, ""


def resolve_youtube(client: httpx.Client, handle: str) -> str:
    """@handle → UC... channel_id. 유튜브 채널 페이지 HTML에서 뽑는다."""
    r = client.get(f"https://www.youtube.com/{handle}", follow_redirects=True)
    r.raise_for_status()
    for pattern in (r'"channelId":"(UC[\w-]{22})"', r'channel/(UC[\w-]{22})'):
        m = re.search(pattern, r.text)
        if m:
            return m.group(1)
    raise ValueError("channel_id를 찾지 못함 (핸들 오타이거나 페이지 구조 변경)")


def check(client: httpx.Client, src: dict) -> Result:
    sid, name = src["id"], src["name"]
    res = Result(sid=sid, name=name, tier=src.get("tier", "?"), ok=False)
    stype = src.get("type")

    try:
        if stype == "rss":
            n, latest, msg = parse_feed(client, src["url"])
            res.items, res.latest, res.detail = n, latest, msg

        elif stype == "github_releases":
            n, latest, msg = parse_feed(client, GITHUB_RELEASES.format(repo=src["repo"]))
            res.items, res.latest, res.detail = n, latest, msg

        elif stype == "youtube":
            cid = src.get("channel_id") or ""
            if not cid:
                cid = resolve_youtube(client, src["handle"])
                res.resolved_channel_id = cid
                res.notes.append(f"channel_id 해석됨 → {cid}")
            n, latest, msg = parse_feed(client, YOUTUBE_FEED.format(cid=cid))
            res.items, res.latest, res.detail = n, latest, msg

        elif stype == "arxiv":
            url = ARXIV_API.format(q=quote_plus(src["query"]), n=src.get("max_items", 15))
            n, latest, msg = parse_feed(client, url)
            res.items, res.latest, res.detail = n, latest, msg

        elif stype == "hn":
            total = 0
            for q in src.get("queries", []):
                r = client.get(HN_API.format(q=q, p=src.get("min_points", 30)))
                r.raise_for_status()
                total += len(r.json().get("hits", []))
            res.items = total
            res.latest = NOW
            res.notes.append(f"{len(src.get('queries', []))}개 쿼리 합산")

        elif stype == "reddit":
            url = REDDIT_RSS.format(sub=src["subreddit"],
                                    listing=src.get("listing", "top"),
                                    period=src.get("period", "day"))
            try:
                n, latest, msg = parse_feed(client, url)
                res.items, res.latest, res.detail = n, latest, msg
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (403, 429):
                    res.detail = "차단됨 (데이터센터 IP). OAuth 앱 등록 또는 로컬 수집 필요"
                    res.notes.append("fallback: skip")
                    return res
                raise

        elif stype == "html":
            # 페이지에 숨어 있는 피드를 찾아본다. 찾으면 그대로 수집 가능한 소스다.
            found = discover_feed(client, src["url"])
            if not found:
                res.detail = "피드 없음 · 개별 스크래퍼 필요"
                return res
            n, latest, msg = parse_feed(client, found)
            res.items, res.latest, res.detail = n, latest, msg
            res.notes.append(f"피드 발견 → {found}")

        elif stype == "api":
            r = client.get(src["url"], follow_redirects=True)
            r.raise_for_status()
            data = r.json()
            res.items = len(data.get("items", data if isinstance(data, list) else []))

        elif stype == "imap":
            res.detail = "수동 설정 (전용 Gmail + 앱 비밀번호)"
            res.notes.append("검사 대상 아님")
            res.ok = True
            return res

        else:
            res.detail = f"알 수 없는 type: {stype}"
            return res

        res.ok = res.items > 0
        if not res.ok and not res.detail:
            res.detail = "응답은 정상이나 항목 0건"

    except httpx.HTTPStatusError as e:
        res.detail = f"HTTP {e.response.status_code}"
    except httpx.RequestError as e:
        res.detail = f"연결 실패: {type(e).__name__}"
    except Exception as e:  # noqa: BLE001 - 헬스체크는 어떤 실패든 리포트로만 남긴다
        res.detail = f"{type(e).__name__}: {e}"

    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="해석된 유튜브 channel_id를 sources.yaml에 채워 넣는다 (주석 보존)")
    ap.add_argument("--all", action="store_true",
                    help="enabled: false인 소스도 검사")
    args = ap.parse_args()

    doc = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))
    sources = [s for s in doc["sources"] if args.all or s.get("enabled", True)]

    print(f"\n  소스 {len(sources)}개 검사 · {NOW.astimezone().strftime('%Y-%m-%d %H:%M')}\n")

    with httpx.Client(headers={"User-Agent": UA}, timeout=TIMEOUT) as client:
        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda s: check(client, s), sources))

    stale_limit = 21
    width = max(len(r.name) for r in results) + 2

    for r in sorted(results, key=lambda x: (x.tier, x.sid)):
        if r.ok and (r.stale_days is None or r.stale_days <= stale_limit):
            mark, state = "OK  ", ""
        elif r.ok:
            mark, state = "STALE", f"최신 항목 {r.stale_days}일 전"
        else:
            mark, state = "FAIL", r.detail
        latest = r.latest.astimezone().strftime("%Y-%m-%d") if r.latest else "—"
        print(f"  {mark:6} {r.tier:3} {r.name:<{width}} {r.items:>4}건  {latest:>10}  {state}")
        for n in r.notes:
            print(f"         {'':3} {'':<{width}}       ↳ {n}")

    ok = sum(1 for r in results if r.ok)
    fail = [r for r in results if not r.ok]
    stale = [r for r in results if r.ok and r.stale_days and r.stale_days > stale_limit]

    print(f"\n  정상 {ok} / 실패 {len(fail)} / 정체 {len(stale)}")
    if fail:
        print("  실패:", ", ".join(r.sid for r in fail))
    if stale:
        print("  정체:", ", ".join(r.sid for r in stale))

    if args.write:
        # yaml.safe_dump로 통째로 다시 쓰면 주석이 전부 사라진다.
        # sources.yaml의 주석은 이 프로젝트에서 문서 역할을 하므로,
        # 필요한 줄만 문자열로 찾아 바꾼다.
        text = SOURCES.read_text(encoding="utf-8")
        lines = text.split("\n")
        changed = 0

        for r in results:
            if not r.resolved_channel_id:
                continue
            # "- id: <sid>" 줄을 찾고, 그 아래 15줄 안의 빈 channel_id를 채운다
            for i, line in enumerate(lines):
                if line.strip() != f"- id: {r.sid}":
                    continue
                for j in range(i, min(i + 15, len(lines))):
                    if re.match(r'\s*channel_id:\s*""\s*$', lines[j]):
                        indent = len(lines[j]) - len(lines[j].lstrip())
                        lines[j] = " " * indent + f'channel_id: "{r.resolved_channel_id}"'
                        changed += 1
                        break
                break

        if changed:
            SOURCES.write_text("\n".join(lines), encoding="utf-8")
            print(f"\n  sources.yaml에 channel_id {changed}건을 채웠습니다 (주석은 그대로).")
        else:
            print("\n  채울 channel_id가 없습니다 (이미 전부 있거나, 해석에 실패했습니다).")

    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
