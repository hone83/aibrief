#!/usr/bin/env python3
"""
순위표 API 점검 — 키가 살아 있는지, 어떤 값이 오는지 확인한다.

    python scripts/probe_aa.py            # 설정에 있는 판 전부
    python scripts/probe_aa.py --raw      # 첫 줄의 원본 필드까지 보여준다

순위표가 비어 보일 때 원인을 가르는 용도다.
키 문제인지, 권한(무료/유료) 문제인지, 필드 이름이 바뀐 것인지가 여기서 갈린다.
--raw 출력은 필드 이름만 보여주고 값은 줄여서 찍는다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import rankings  # noqa: E402
from run import load_dotenv  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", action="store_true", help="원본 응답의 첫 항목을 그대로 출력")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    key = os.environ.get("AA_API_KEY", "").strip()
    if not key:
        print("AA_API_KEY가 없습니다. .env에 넣거나 환경변수로 지정하세요.")
        print("발급: https://artificialanalysis.ai/data-api")
        return 1
    if not key.isascii():
        print(f"'.env'의 AA_API_KEY가 실제 키가 아닙니다 — 지금 값: {key}")
        print("안내문의 자리표시자를 그대로 넣으신 것 같습니다.")
        print("artificialanalysis.ai/data-api 에서 받은 영문·숫자 문자열로 바꿔주세요.")
        return 1
    if len(key) < 12:
        print(f"AA_API_KEY가 너무 짧습니다 ({len(key)}자). 값을 다시 확인하세요.")
        return 1
    print(f"키 확인: {key[:6]}…{key[-4:]} ({len(key)}자)\n")

    cfg = yaml.safe_load((ROOT / "config" / "scoring.yaml").read_text(encoding="utf-8"))
    boards = (cfg.get("rankings") or {}).get("boards", [])

    with httpx.Client(timeout=rankings.TIMEOUT, follow_redirects=True) as client:
        for board in boards:
            print(f"── {board['label']}  ({board['endpoint']})")
            try:
                rows, tier = rankings._fetch_one(client, board["endpoint"], key)
            except Exception as exc:  # noqa: BLE001 — 진단용이므로 이유만 보이면 된다
                print(f"   실패: {type(exc).__name__}: {exc}\n")
                continue

            got = "유료 등급" if tier == "full" else "무료 등급"
            print(f"   {got} · {len(rows)}건")
            norm = rankings._normalize(rows, board.get("kind", "media"), board.get("top", 8))
            for r in norm[:3]:
                price = f" · {r['price']}{r['price_unit']}" if r["price"] is not None else ""
                print(f"   {r.get('rank','?'):>2}. {r['name'][:38]:<38} {r['score']}{price}")
            if norm and norm[0]["score"] is None:
                print("   ⚠ 점수를 못 읽었습니다. --raw로 필드 이름을 확인하세요.")
            if args.raw and rows:
                print("   원본 첫 항목:")
                print("   " + json.dumps(rows[0], ensure_ascii=False, indent=2)[:1200]
                      .replace("\n", "\n   "))
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
