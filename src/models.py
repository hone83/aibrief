"""
파이프라인 전체가 주고받는 데이터 모양을 한 곳에 정의한다.

여기서 dataclass를 쓰는 이유:
파이프라인은 수집 → 필터 → 중복제거 → 점수 → 렌더로 이어지는데,
각 단계가 dict를 주고받으면 어느 단계에서 어떤 키가 생기는지 아무도 모르게 된다.
Item이라는 고정된 모양을 정해두면, 오타(item["titel"])가 실행 즉시 잡히고
편집기가 자동완성을 해준다.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field, asdict
from typing import Any

KST = dt.timezone(dt.timedelta(hours=9))


@dataclass
class Item:
    """수집된 항목 하나. 뉴스 기사든 유튜브 영상이든 GitHub 릴리스든 전부 이 모양."""

    # --- 수집 단계에서 채워지는 값 ---
    title: str
    url: str
    source_id: str
    source_name: str
    tier: str                       # T0 ~ T4
    topics: list[str]               # video / image / tools / industry
    published: dt.datetime          # 항상 UTC(timezone-aware)로 보관한다
    summary_raw: str = ""           # 피드가 준 요약문. 본문 추출 전의 원본
    signal: str = "normal"          # 유튜브 채널 신호 등급
    ad_filter: str = "normal"       # "strict"이면 광고 판정을 더 엄격하게
    extra: dict[str, Any] = field(default_factory=dict)  # points, views 등 소스별 부가정보

    # --- 번역 단계에서 채워지는 값 (2주차) ---
    title_ko: str = ""              # 한국어 제목. 비어 있으면 화면은 원제를 그대로 쓴다
    summary_ko: str = ""            # 한국어 요약
    bullets: list[str] = field(default_factory=list)   # 핵심 3줄

    # --- 이후 단계에서 채워지는 값 ---
    category: str = "minor"         # 사건 유형 (model_release, workflow, ...)
    score: float = 0.0
    cluster_id: int = -1            # 같은 사건끼리 같은 번호를 갖는다
    related: list[dict] = field(default_factory=list)  # 클러스터 내 나머지 항목들
    drop_reason: str = ""           # 필터에 걸렸다면 그 이유 (리포트용)

    @property
    def uid(self) -> str:
        """URL 기준의 고유 ID. 어제 이미 나간 항목인지 판별할 때 쓴다."""
        return hashlib.sha1(self.url.encode("utf-8")).hexdigest()[:12]

    @property
    def published_kst(self) -> dt.datetime:
        return self.published.astimezone(KST)

    @property
    def display_title(self) -> str:
        """화면에 크게 보일 제목. 번역이 있으면 한국어, 없으면 원제."""
        return self.title_ko or self.title

    @property
    def translated(self) -> bool:
        return bool(self.title_ko)

    @property
    def domain(self) -> str:
        from urllib.parse import urlparse
        return urlparse(self.url).netloc.lower().removeprefix("www.")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published"] = self.published.isoformat()
        d["published_kst"] = self.published_kst.isoformat()
        d["uid"] = self.uid
        d["domain"] = self.domain
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Item":
        """저장된 JSON에서 되살린다. 지난 브리핑을 다시 그릴 때 쓴다.

        uid·domain·published_kst는 계산해서 나오는 값이라 넣지 않는다.
        모르는 키가 섞여 있어도 무시한다 — 예전 버전이 쓴 파일도 읽혀야 하기 때문이다.
        """
        known = {f for f in cls.__dataclass_fields__}
        kw = {k: v for k, v in d.items() if k in known}
        kw["published"] = dt.datetime.fromisoformat(d["published"])
        return cls(**kw)


@dataclass
class SourceReport:
    """소스 하나의 수집 결과. '조용한 실패'를 막는 장치."""

    source_id: str
    source_name: str
    tier: str
    collected: int = 0              # 가져온 원본 건수
    kept: int = 0                   # 필터를 통과한 건수
    ok: bool = True
    error: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Brief:
    """하루치 브리핑 전체. 이게 그대로 JSON 파일 하나가 된다."""

    date_kst: str                   # "2026-08-25"
    generated_at: str               # ISO 8601
    window_start: str
    window_end: str
    headlines: list[Item] = field(default_factory=list)
    cards: list[Item] = field(default_factory=list)
    tldr: list[str] = field(default_factory=list)      # 오늘 전체를 3줄로
    dropped: list[dict] = field(default_factory=list)  # 필터에 걸린 항목 (튜닝 근거)
    reports: list[SourceReport] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    rankings: dict[str, Any] = field(default_factory=dict)   # 모델 순위표 (별도 탭)

    def to_dict(self) -> dict:
        return {
            "date_kst": self.date_kst,
            "generated_at": self.generated_at,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "headlines": [i.to_dict() for i in self.headlines],
            "cards": [i.to_dict() for i in self.cards],
            "tldr": self.tldr,
            "dropped": self.dropped,
            "reports": [r.to_dict() for r in self.reports],
            "stats": self.stats,
            "rankings": self.rankings,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Brief":
        return cls(
            date_kst=d.get("date_kst", ""),
            generated_at=d.get("generated_at", ""),
            window_start=d.get("window_start", ""),
            window_end=d.get("window_end", ""),
            headlines=[Item.from_dict(x) for x in d.get("headlines", [])],
            cards=[Item.from_dict(x) for x in d.get("cards", [])],
            tldr=d.get("tldr", []),
            dropped=d.get("dropped", []),
            reports=[SourceReport(**{k: v for k, v in r.items()
                                     if k in SourceReport.__dataclass_fields__})
                     for r in d.get("reports", [])],
            stats=d.get("stats", {}),
            rankings=d.get("rankings", {}),
        )
