"""
지난 브리핑을 가로지르는 색인 — 달력·검색·모델별 히스토리가 이걸 읽는다.

왜 페이지 안에 넣지 않고 따로 파일로 빼는가:
색인을 HTML 안에 박아 넣으면, 하루가 지날 때마다 **지난 브리핑 페이지 전부**가
바뀌어야 한다(어제 페이지도 오늘 날짜를 알아야 하므로). 그러면 매일 수십 개
파일이 통째로 다시 커밋되고, 저장소가 금세 지저분해진다.

색인을 docs/*.json으로 빼두면 페이지는 그대로 있고 이 세 파일만 바뀐다.
페이지는 필요할 때(검색창을 처음 열 때) 받아서 쓴다.

만드는 파일:
  docs/dates.json         브리핑이 있는 날짜 목록 — 달력이 읽는다
  docs/search-index.json  모든 날의 모든 카드 — 검색이 읽는다
  docs/models.json        모델·회사 이름별 등장 기록 — '모델' 탭이 읽는다
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# 검색 결과에 보여줄 미리보기 길이. 색인 파일 크기를 좌우한다.
# 12건 × 365일 × 약 250바이트 ≈ 1년에 1MB. 이 정도면 한 번에 받아도 된다.
SNIPPET = 110

# 모델 탭에 세울 이름의 최소 등장 횟수. 한 번 스친 이름까지 세우면 목록이 못 쓰게 된다.
MIN_MENTIONS = 2
MAX_MODELS = 60


def load_all(data_dir: Path) -> list[dict]:
    """data/의 날짜 JSON을 오래된 것부터 읽는다. 깨진 파일은 건너뛴다."""
    out: list[dict] = []
    for path in sorted(data_dir.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _entry(card: dict, date: str) -> dict:
    """검색 색인 한 줄. 키를 짧게 쓰는 건 파일 크기 때문이다."""
    summary = (card.get("summary_ko") or card.get("summary_raw") or "")[:SNIPPET]
    return {
        "d": date,
        "u": card.get("uid", ""),
        "t": card.get("title_ko") or card.get("title", ""),
        "o": card.get("title", ""),
        "s": re.sub(r"\s+", " ", summary).strip(),
        "c": card.get("category", "minor"),
        "src": card.get("source_name", ""),
        "l": card.get("url", ""),
    }


# 이름 뒤에 붙은 버전 숫자를 찾는다. "Wan 3.0", "Kling 2.8", "LTX-Video 3" 모두 잡되
# "Kling cuts price by 40%"처럼 숫자가 멀리 떨어진 문장은 잡지 않는다.
# 사이에 낱말 하나까지만 허용하고(LTX-Video), 연도가 걸리지 않게 두 자리까지만 센다.
def _version_after(name: str, text: str) -> str:
    m = re.search(
        rf"(?<![0-9A-Za-z]){re.escape(name)}"
        rf"(?:[\s\-–]?[A-Za-z]{{2,12}})?[\s\-–]?"
        rf"(v?\d{{1,2}}(?:\.\d{{1,2}})*)"
        rf"(?:\s(pro|turbo|max|mini|flash|lite|ultra|preview))?",
        text, re.I)
    if not m:
        return ""
    ver = m.group(1)
    if m.group(2):
        ver += " " + m.group(2).capitalize()
    return ver


def _name_pattern(name: str) -> re.Pattern:
    """
    'Gen-5'나 'FLUX.2'처럼 기호가 섞인 이름도 정확히 잡아야 한다.
    앞뒤가 글자/숫자면 다른 단어의 일부이므로 제외한다 (예: 'Sora'가 'Sorare'에 걸리지 않게).
    """
    return re.compile(rf"(?<![0-9A-Za-z]){re.escape(name)}(?![0-9A-Za-z])", re.I)


def build_models(briefs: list[dict], names: list[str], conf: dict | None = None) -> list[dict]:
    """
    모델·회사 이름별로 지난 기사를 모은다.

    이름 목록은 용어 사전(config/glossary.json)의 protect를 그대로 쓴다.
    거기 이미 "번역하면 안 되는 고유명사"가 모여 있고, 새 모델이 나오면
    어차피 그 파일에 추가하게 되므로 목록을 두 벌 관리할 이유가 없다.

    제목에서 먼저 찾고, 제목에 없으면 요약에서 찾는다.
    요약까지 뒤지는 이유는 "Runway가 새 모델을 냈다"처럼 제목엔 회사만,
    본문엔 모델명이 있는 경우가 흔하기 때문이다.
    """
    conf = conf or {}
    exclude = {n.lower() for n in conf.get("exclude", [])}
    min_mentions = int(conf.get("min_mentions", MIN_MENTIONS))
    max_models = int(conf.get("max_models", MAX_MODELS))
    max_items = int(conf.get("max_items", 80))

    patterns = [(n, _name_pattern(n)) for n in names
                if len(n) >= 3 and n.lower() not in exclude]
    buckets: dict[str, list[dict]] = {}

    for brief in briefs:
        date = brief.get("date_kst", "")
        for card in brief.get("cards", []):
            title = f"{card.get('title', '')} {card.get('title_ko', '')}"
            body = f"{card.get('summary_raw', '')} {card.get('summary_ko', '')}"[:1200]
            for name, pat in patterns:
                if pat.search(title) or pat.search(body):
                    buckets.setdefault(name, []).append(_entry(card, date))

    models = []
    for name, items in buckets.items():
        if len(items) < min_mentions:
            continue
        items.sort(key=lambda x: (x["d"], x["t"]), reverse=True)

        # 카드에 최신 헤드라인을 얹는다. 이름만 있는 카드는 "그래서 뭐가 있었나"를
        # 알려주지 못해서, 목록을 훑는 동안 아무 정보도 주지 못한다.
        # 버전은 최근 기사부터 거슬러 올라가며 처음 찾은 것을 쓴다.
        version = ""
        for it in items[:12]:
            version = _version_after(name, it["o"]) or _version_after(name, it["t"])
            if version:
                break

        models.append({"name": name, "n": len(items), "last": items[0]["d"],
                       "head": items[0]["t"], "ver": version,
                       "items": items[:max_items]})

    # 최근에 움직인 이름을 위로. 같은 날이면 많이 나온 쪽이 위로.
    models.sort(key=lambda m: (m["last"], m["n"]), reverse=True)
    return models[:max_models]


def build(root: Path, protect_names: list[str],
          history_conf: dict | None = None) -> dict[str, int]:
    """세 색인 파일을 만든다. 돌려주는 값은 화면에 찍을 건수."""
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    briefs = load_all(root / "data")

    dates = [b.get("date_kst", "") for b in briefs if b.get("date_kst")]
    dates.sort(reverse=True)
    (docs / "dates.json").write_text(json.dumps(dates, ensure_ascii=False),
                                     encoding="utf-8")

    index: list[dict] = []
    for brief in briefs:
        date = brief.get("date_kst", "")
        for card in brief.get("cards", []):
            index.append(_entry(card, date))
    index.sort(key=lambda x: x["d"], reverse=True)
    (docs / "search-index.json").write_text(json.dumps(index, ensure_ascii=False),
                                            encoding="utf-8")

    models = build_models(briefs, protect_names, history_conf)
    (docs / "models.json").write_text(json.dumps(models, ensure_ascii=False),
                                      encoding="utf-8")

    return {"days": len(dates), "items": len(index), "models": len(models)}
