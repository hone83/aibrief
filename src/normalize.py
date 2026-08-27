"""
정규화 — 수집 직후의 지저분한 데이터를 정돈한다.

여기서 하는 일은 눈에 안 보이지만, 안 하면 뒤에서 전부 깨진다.
같은 기사가 추적 파라미터(?utm_source=...) 때문에 다른 URL로 보이면
중복제거가 실패하고, 브리핑에 같은 뉴스가 두 번 실린다.
"""

from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from .models import Item, KST

# 광고 추적용 쿼리 파라미터. 내용에 아무 영향이 없으므로 제거한다.
TRACKING_PARAMS = re.compile(
    r"^(utm_\w+|fbclid|gclid|mc_cid|mc_eid|ref|ref_src|source|_hsenc|_hsmi|igshid)$",
    re.IGNORECASE,
)


def canonical_url(url: str) -> str:
    """
    같은 문서를 가리키는 URL을 하나의 표기로 통일한다.
      - 추적 파라미터 제거
      - 끝의 슬래시 제거
      - 호스트 소문자화, www. 제거
      - 유튜브는 v= 파라미터만 남긴다 (?t=30s 같은 게 붙어 오는 경우가 있다)
    """
    p = urlparse(url)
    netloc = p.netloc.lower().removeprefix("www.")

    query = [(k, v) for k, v in parse_qsl(p.query) if not TRACKING_PARAMS.match(k)]
    if "youtube.com" in netloc:
        query = [(k, v) for k, v in query if k == "v"]

    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme or "https", netloc, path, "", urlencode(query), ""))


def window_bounds(now_kst: dt.datetime, end_local: str = "07:00",
                  hours: int = 24) -> tuple[dt.datetime, dt.datetime]:
    """
    브리핑이 다루는 시간 구간을 계산한다.

    왜 필요한가: 미국 발표는 한국 시간 새벽 2~6시에 몰린다.
    "오늘 것만"이라고 자르면 그 시간대가 통째로 빠지거나,
    다음 날 다시 나와서 같은 뉴스가 이틀 연속 실린다.
    그래서 경계를 07:00으로 고정한다 → 전일 07:00 ~ 당일 07:00 KST.
    """
    hh, mm = (int(x) for x in end_local.split(":"))
    end = now_kst.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now_kst < end:                       # 아직 오늘 07:00 전이면 어제 07:00이 끝
        end -= dt.timedelta(days=1)
    return end - dt.timedelta(hours=hours), end


def normalize(items: list[Item], start: dt.datetime, end: dt.datetime) -> list[Item]:
    """URL 통일 → 시간창 필터 → URL 기준 중복 제거. 순서가 중요하다."""
    out: dict[str, Item] = {}

    for it in items:
        it.url = canonical_url(it.url)
        it.title = re.sub(r"\s+", " ", it.title).strip()

        published_kst = it.published.astimezone(KST)
        if not (start <= published_kst < end):
            continue

        # 같은 URL이 여러 소스에서 왔다면 티어가 높은(=숫자가 작은) 쪽을 남긴다.
        prev = out.get(it.url)
        if prev is None or it.tier < prev.tier:
            out[it.url] = it

    return sorted(out.values(), key=lambda x: x.published, reverse=True)
