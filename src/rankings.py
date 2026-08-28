"""
모델 순위표 — Artificial Analysis 데이터 API에서 받아온다.

왜 뉴스와 별도인가:
뉴스는 "어제 무슨 일이 있었나"이고 순위는 "지금 뭐가 제일 좋나"이다.
둘은 갱신 주기가 다르다. 순위는 며칠에 한 번 바뀌므로, 매일 받아오되
어제와 비교해서 바뀐 것만 눈에 띄게 표시한다 (▲▼).

키가 없거나 API가 죽어도 브리핑은 그대로 나간다. 순위 탭만 비어 있을 뿐이다.
이 원칙은 이 프로그램 전체에서 같다 — 한 부분의 실패가 발행을 막지 않는다.

무료 키와 유료 키의 차이:
무료 등급의 미디어 엔드포인트는 "모델 이름 + Elo + 오차범위"만 준다. 가격은 없다.
그래서 정식 주소를 먼저 찔러 보고, 권한이 없다고 하면 /free 주소로 물러선다.
나중에 유료로 올리면 코드를 고치지 않아도 가격 칸이 저절로 채워진다.

출처 표기는 API 이용 조건이다. 화면에 반드시 남긴다.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

import httpx

API_BASE = "https://artificialanalysis.ai/api/v2"
TIMEOUT = httpx.Timeout(connect=10.0, read=40.0, write=20.0, pool=10.0)

# 응답의 필드 이름이 바뀌어도 버티도록 후보를 여러 개 둔다.
# 이름 하나 바뀌었다고 순위표가 통째로 빈칸이 되는 것보다 낫다.
NAME_KEYS = ("name", "model_name", "slug", "id")
ELO_KEYS = ("elo", "elo_score", "quality_elo", "arena_elo")
CI_KEYS = ("ci_95", "ci95", "confidence_interval")
RANK_KEYS = ("rank", "position")
INDEX_KEYS = ("artificial_analysis_intelligence_index", "intelligence_index", "index")


def _pick(row: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def _creator(row: dict) -> str:
    c = row.get("model_creator") or row.get("creator") or row.get("organization")
    if isinstance(c, dict):
        return str(c.get("name") or c.get("id") or "")
    return str(c or "")


def _deep_get(row: dict, *paths: tuple[str, ...]) -> Any:
    """중첩된 값을 찾는다. price가 pricing 안에 들어 있는 식의 응답을 위해."""
    for path in paths:
        cur: Any = row
        for key in path:
            if not isinstance(cur, dict) or key not in cur:
                cur = None
                break
            cur = cur[key]
        if cur not in (None, ""):
            return cur
    return None


def _media_price(row: dict) -> tuple[float | None, str]:
    """영상은 분당, 이미지는 장당으로 값이 온다. 단위를 같이 돌려준다."""
    per_min = _pick(row, ("price_per_minute", "price_usd_per_minute"))
    if per_min is not None:
        try:
            return round(float(per_min) / 60, 4), "$/초"
        except (TypeError, ValueError):
            pass
    per_k = _pick(row, ("price_per_1000_images",))
    if per_k is not None:
        try:
            return round(float(per_k) / 1000, 4), "$/장"
        except (TypeError, ValueError):
            pass
    per_img = _pick(row, ("price_per_image", "price_usd_per_image"))
    if per_img is not None:
        try:
            return round(float(per_img), 4), "$/장"
        except (TypeError, ValueError):
            pass
    return None, ""


def _language_price(row: dict) -> tuple[float | None, str]:
    v = _deep_get(
        row,
        ("pricing", "price_1m_blended_3_to_1"),
        ("pricing", "price_1m_output_tokens"),
        ("price_1m_blended_3_to_1",),
        ("price_1m_output_tokens",),
    )
    try:
        return (round(float(v), 2), "$/1M") if v is not None else (None, "")
    except (TypeError, ValueError):
        return None, ""


def _rows_from(payload: Any) -> list[dict]:
    """{"status":200,"data":[...]} 형태와 그냥 배열 형태를 모두 받는다."""
    if isinstance(payload, dict):
        for key in ("data", "results", "models"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return []
    return payload if isinstance(payload, list) else []


def _fetch_one(client: httpx.Client, endpoint: str, api_key: str) -> tuple[list[dict], str]:
    """
    정식 주소 → 권한 없으면 /free 주소. 어느 쪽으로 받았는지도 같이 돌려준다.
    """
    headers = {"x-api-key": api_key}
    tried: list[str] = []
    for url, tier in ((f"{API_BASE}/{endpoint}", "full"),
                      (f"{API_BASE}/{endpoint}/free", "free")):
        tried.append(url)
        try:
            r = client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"연결 실패: {type(exc).__name__}") from exc
        if r.status_code in (401, 403, 404) and tier == "full":
            continue                      # 무료 키다. 아래 /free로 다시 시도
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}")
        return _rows_from(r.json()), tier
    raise RuntimeError("무료 주소에서도 권한이 없습니다 (키 확인 필요)")


def _normalize(rows: list[dict], kind: str, top: int) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _pick(row, NAME_KEYS)
        if not name:
            continue
        if kind == "language":
            score = _deep_get(row, *[("evaluations", k) for k in INDEX_KEYS],
                              *[(k,) for k in INDEX_KEYS])
            price, unit = _language_price(row)
        else:
            score = _pick(row, ELO_KEYS)
            price, unit = _media_price(row)
        try:
            score = round(float(score), 1) if score is not None else None
        except (TypeError, ValueError):
            score = None
        out.append({
            "name": str(name),
            "creator": _creator(row),
            "score": score,
            "ci": _pick(row, CI_KEYS),
            "price": price,
            "price_unit": unit,
            "released": _pick(row, ("release_date", "released", "first_seen")),
        })

    # rank가 없는 응답도 있으므로 점수 기준으로 직접 세운다.
    scored = [r for r in out if r["score"] is not None]
    unscored = [r for r in out if r["score"] is None]
    scored.sort(key=lambda r: r["score"], reverse=True)
    for i, r in enumerate(scored, 1):
        r["rank"] = i
    return (scored + unscored)[:top]


def _apply_deltas(boards: list[dict], previous: dict) -> None:
    """어제 순위와 비교해 ▲▼를 붙인다. 새로 등장한 모델은 NEW."""
    prev_ranks: dict[str, dict[str, int]] = previous.get("ranks", {})
    for board in boards:
        old = prev_ranks.get(board["id"], {})
        for row in board["rows"]:
            before = old.get(row["name"])
            if before is None:
                row["delta"] = None            # 처음 보는 모델
                row["is_new"] = bool(old)      # 비교할 어제가 있었는데 없던 이름이면 신규
            else:
                row["delta"] = before - row.get("rank", before)
                row["is_new"] = False


def fetch(cfg: dict, root: Path, api_key: str | None = None) -> dict:
    """
    설정에 적힌 순위판을 모두 받아 하나의 묶음으로 돌려준다.
    실패한 판은 note에 이유를 담고 rows를 비운다 — 조용히 사라지지 않게.
    """
    conf = cfg.get("rankings") or {}
    result: dict[str, Any] = {
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "attribution": conf.get("attribution", "Artificial Analysis"),
        "source_url": conf.get("source_url", "https://artificialanalysis.ai/"),
        "boards": [],
        "tier": "",
        "error": "",
    }
    if not conf.get("enabled", True):
        result["error"] = "설정에서 꺼져 있습니다"
        return result

    api_key = (api_key or os.environ.get("AA_API_KEY", "")).strip()
    if not api_key:
        result["error"] = "AA_API_KEY 없음"
        return result
    # HTTP 헤더에는 ASCII만 들어갈 수 있다. 한글이 섞여 있으면 httpx가 예외를 던지는데,
    # 그게 순위표 하나 때문에 브리핑 전체를 멈추게 두면 안 된다.
    # (안내문의 자리표시자를 그대로 복사해 넣는 실수가 실제로 있었다.)
    if not api_key.isascii():
        result["error"] = "AA_API_KEY가 실제 키가 아닙니다 (한글이 섞여 있음)"
        return result

    store = root / "data" / "rankings.json"
    previous = {}
    if store.exists():
        try:
            previous = json.loads(store.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}

    tiers: set[str] = set()
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        for board in conf.get("boards", []):
            entry = {"id": board["id"], "label": board["label"],
                     "kind": board.get("kind", "media"), "rows": [], "note": ""}
            try:
                rows, tier = _fetch_one(client, board["endpoint"], api_key)
                tiers.add(tier)
                entry["rows"] = _normalize(rows, entry["kind"], board.get("top", 8))
                if not entry["rows"]:
                    entry["note"] = "받은 데이터가 비어 있습니다"
            except Exception as exc:  # noqa: BLE001 — 순위표 실패가 발행을 막지 않는다
                entry["note"] = f"{type(exc).__name__}: {exc}"[:140]
            result["boards"].append(entry)

    result["tier"] = "full" if "full" in tiers else ("free" if tiers else "")
    _apply_deltas(result["boards"], previous)

    # 다음 실행에서 ▲▼를 계산하려고 이번 순위를 저장한다.
    # 전부 실패한 날에는 덮어쓰지 않는다 — 어제 기준을 잃으면 비교가 끊긴다.
    if any(b["rows"] for b in result["boards"]):
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps({
            "date": dt.datetime.now(dt.timezone.utc).date().isoformat(),
            "ranks": {b["id"]: {r["name"]: r["rank"] for r in b["rows"] if "rank" in r}
                      for b in result["boards"] if b["rows"]},
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    return result
