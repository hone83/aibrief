"""
점수 계산과 선별 — 무엇을 헤드라인으로 올리고 무엇을 버릴지 정한다.

점수 = 티어가중치 × 관심도배수 × 사건유형가중치
     × (1 + 커뮤니티반응) × (1 + 클러스터크기) × 신선도감쇠 × 채널신호

곱셈으로 쌓는 이유: 어느 한 축이 0에 가까우면 전체가 0에 가까워진다.
덧셈이면 "관심 없는 주제인데 반응만 많은 글"이 상위로 올라온다.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

from .models import Item, KST


def interest_multiplier(item: Item, interests: dict, baseline: int) -> float:
    """
    관심 비중을 배수로 바꾼다. baseline 25를 1.0으로 본다.
    비디오 50 → 2.0배, 이미지·툴 20 → 0.8배, 산업 10 → 0.4배.

    여러 topic을 가진 항목은 그중 '최댓값'을 쓴다.
    합산하면 topic을 많이 달아둔 소스가 무조건 유리해져서 잡탕 기사가 올라온다.
    """
    if not item.topics:
        return 1.0
    return max(interests.get(t, baseline) for t in item.topics) / baseline


def community_boost(item: Item, cap: float, medians: dict[str, float]) -> float:
    """
    반응량 보정. 소스마다 단위가 달라서(HN 점수 vs 유튜브 조회수)
    같은 소스 안에서의 중앙값 대비 비율로 정규화한 뒤 0~cap 범위로 누른다.
    """
    raw = item.extra.get("points") or item.extra.get("downloads") or 0
    if not raw:
        return 0.0
    median = medians.get(item.source_id) or 1.0
    ratio = raw / median
    return min(cap, cap * math.log1p(ratio) / math.log1p(4))   # 중앙값의 4배에서 상한


def freshness(item: Item, now: dt.datetime, half_life_hours: float) -> float:
    """
    지수 감쇠. half_life_hours가 지날 때마다 절반이 된다.
    24시간 창 안에서도 방금 나온 것이 유리해야 하기 때문에 넣는다.
    """
    age_h = max(0.0, (now - item.published).total_seconds() / 3600)
    return 0.5 ** (age_h / half_life_hours)


def compute_scores(items: list[Item], cfg: dict, now: dt.datetime | None = None) -> list[Item]:
    now = now or dt.datetime.now(dt.timezone.utc)
    sc = cfg["scoring"]
    tiers = cfg["_tiers"]
    interests = cfg["interests"]
    baseline = cfg.get("interest_baseline", 25)

    # 소스별 반응량 중앙값을 먼저 구해둔다 (정규화 기준)
    buckets: dict[str, list[float]] = defaultdict(list)
    for it in items:
        raw = it.extra.get("points") or it.extra.get("downloads") or 0
        if raw:
            buckets[it.source_id].append(float(raw))
    medians = {
        sid: sorted(vals)[len(vals) // 2]
        for sid, vals in buckets.items() if vals
    }

    for it in items:
        tier_w = tiers.get(it.tier, {}).get("weight", 0.5)
        topic_m = interest_multiplier(it, interests, baseline)
        event_w = sc["event_type_weight"].get(it.category, 0.3)
        signal_m = sc["signal_modifier"].get(it.signal, 1.0)
        boost = community_boost(it, sc["community_boost_max"], medians)
        cluster_bonus = min(
            sc["cluster_size_bonus"] * len(it.related),
            sc["cluster_size_bonus_max"],
        )
        decay = freshness(it, now, sc["freshness_half_life_hours"])

        it.score = round(
            tier_w * topic_m * event_w * signal_m
            * (1 + boost) * (1 + cluster_bonus) * decay,
            4,
        )

    return sorted(items, key=lambda x: x.score, reverse=True)


def select(items: list[Item], cfg: dict) -> tuple[list[Item], list[Item]]:
    """
    헤드라인과 카드를 뽑는다.

    카테고리 쿼터를 먼저 채우는 이유:
    비디오 관심도가 50이면 점수 상위가 비디오로만 덮인다.
    쿼터로 각 카테고리 최소 몇 장을 확보한 뒤, 남은 자리를 점수순으로 채운다.
    """
    out = cfg["output"]
    quota: dict[str, int] = dict(cfg.get("category_quota", {}))

    picked: list[Item] = []
    picked_ids: set[str] = set()

    # 1단계: 카테고리별 최소 배정
    for category, need in quota.items():
        for it in items:
            if need <= 0:
                break
            if it.uid in picked_ids or it.category != category:
                continue
            picked.append(it)
            picked_ids.add(it.uid)
            need -= 1

    # 2단계: 남은 자리를 점수순으로
    for it in items:
        if len(picked) >= out["cards"]:
            break
        if it.uid not in picked_ids:
            picked.append(it)
            picked_ids.add(it.uid)

    picked.sort(key=lambda x: x.score, reverse=True)
    cards = picked[: out["cards"]]
    headlines = cards[: out["headlines"]]
    return headlines, cards


def importance_stars(item: Item, top_score: float) -> int:
    """화면에 표시할 별 개수(1~3). 상대값이라 날마다 기준이 흔들리지 않는다."""
    if top_score <= 0:
        return 1
    ratio = item.score / top_score
    return 3 if ratio >= 0.7 else 2 if ratio >= 0.4 else 1


def kst_now() -> dt.datetime:
    return dt.datetime.now(KST)
