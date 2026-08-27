#!/usr/bin/env python3
"""
파이프라인 오케스트레이터 — 하루치 브리핑을 만든다.

    python run.py                  # 전체 실행 (수집 → 발행 → 메일)
    python run.py --dry-run        # 파일만 쓰고 메일은 보내지 않음
    python run.py --no-mail        # 위와 동일
    python run.py --fixture tests/fixtures/sample.json
                                   # 네트워크 없이 저장된 데이터로 실행 (개발·검증용)
    python run.py --engine deepl   # 이번 실행만 다른 번역 엔진으로

각 단계 사이에 건수를 출력한다. 어느 단계에서 몇 건이 사라졌는지 보이지 않으면
필터를 조일지 풀지 판단할 수 없다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import yaml

from src import collect, dedupe, mail, normalize, render, score, translate
from src.models import Brief, Item, SourceReport, KST

ROOT = Path(__file__).resolve().parent


def load_dotenv(path: Path) -> None:
    """
    .env 파일이 있으면 그 안의 값을 환경변수로 읽어들인다.

    맥에서 직접 돌릴 때 매번 터미널에 비밀번호를 치지 않으려고 두는 파일이다.
    setdefault를 쓰는 게 중요하다 — 깃허브 액션에서는 Secrets가 이미 환경변수로
    들어와 있으므로, .env가 그걸 덮어쓰면 안 된다.

    .env는 .gitignore에 들어 있어 저장소에 올라가지 않는다. 절대 커밋하지 말 것.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config() -> tuple[list[dict], dict, dict]:
    sources_doc = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    scoring_doc = yaml.safe_load((ROOT / "config" / "scoring.yaml").read_text(encoding="utf-8"))
    scoring_doc["_tiers"] = sources_doc["tiers"]
    return sources_doc["sources"], sources_doc.get("blocklist", {}), scoring_doc


def load_fixture(path: Path) -> tuple[list[Item], list[SourceReport]]:
    """저장된 수집 결과로 파이프라인을 돌린다. 네트워크 없이 로직만 검증할 때."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = [
        Item(
            title=r["title"], url=r["url"], source_id=r["source_id"],
            source_name=r["source_name"], tier=r["tier"], topics=r["topics"],
            published=dt.datetime.fromisoformat(r["published"]),
            summary_raw=r.get("summary_raw", ""), signal=r.get("signal", "normal"),
            ad_filter=r.get("ad_filter", "normal"), extra=r.get("extra", {}),
        )
        for r in raw["items"]
    ]
    reports = [SourceReport(**r) for r in raw.get("reports", [])]
    return items, reports


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="메일 발송 생략")
    ap.add_argument("--no-mail", action="store_true", help="메일 발송 생략")
    ap.add_argument("--fixture", type=Path, help="네트워크 대신 저장된 데이터 사용")
    ap.add_argument("--now", help="기준 시각 고정 (예: 2026-08-25T08:00+09:00). 테스트용")
    ap.add_argument("--engine", choices=["gemini", "claude", "deepl", "none"],
                    help="이번 실행에만 번역 엔진을 바꾼다 (설정 파일은 그대로)")
    ap.add_argument("--show-dropped", nargs="?", const=40, type=int, metavar="N",
                    help="필터에 걸린 항목을 제목까지 출력한다 (기본 40건). 필터 튜닝용")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    sources, blocklist, cfg = load_config()

    now_kst = dt.datetime.fromisoformat(args.now).astimezone(KST) if args.now \
        else dt.datetime.now(KST)
    start, end = normalize.window_bounds(
        now_kst,
        end_local=cfg["schedule"]["window_end_local"],
        hours=cfg["schedule"]["window_hours"],
    )
    print(f"\n창(窓): {start:%Y-%m-%d %H:%M} ~ {end:%Y-%m-%d %H:%M} KST")

    # --- 1) 수집 ---------------------------------------------------------
    if args.fixture:
        raw_items, reports = load_fixture(args.fixture)
        print(f"[1] 수집(픽스처)  {len(raw_items):>4}건")
    else:
        raw_items, reports = collect.collect_all(sources)
        ok = sum(1 for r in reports if r.ok)
        print(f"[1] 수집          {len(raw_items):>4}건  (소스 {ok}/{len(reports)} 정상)")

    # --- 2) 정규화 + 시간창 ----------------------------------------------
    items = normalize.normalize(raw_items, start, end)
    print(f"[2] 정규화·시간창  {len(items):>4}건")

    # --- 3) 스크리닝 -----------------------------------------------------
    kept, dropped = screen_items(items, blocklist, cfg)
    print(f"[3] 필터 통과      {len(kept):>4}건  (탈락 {len(dropped)}건)")

    # --- 4) 중복 묶기 ----------------------------------------------------
    # 회사·브랜드 이름은 사건 식별에서 빼준다 (용어 사전의 protect 목록 재사용)
    brands = dedupe.brand_tokens(
        translate.load_glossary(ROOT / cfg.get("translate", {})
                                .get("glossary", "config/glossary.json"))["protect"])
    unique = dedupe.dedupe(kept, threshold=0.5, exclude=brands)
    merged = len(kept) - len(unique)
    print(f"[4] 중복 묶기      {len(unique):>4}건  ({merged}건 병합)")

    # --- 5) 점수 + 선별 --------------------------------------------------
    scored = score.compute_scores(unique, cfg)
    headlines, cards = score.select(scored, cfg)
    print(f"[5] 선별          헤드라인 {len(headlines)} · 카드 {len(cards)}")

    # --- 6) 번역 ---------------------------------------------------------
    # 선별 뒤에 번역한다. 화면에 나올 12건만 번역하면 되기 때문이다.
    tcfg = dict(cfg.get("translate", {}))
    if args.engine:
        tcfg["engine"] = args.engine
    engine, tmsg = translate.translate(cards, tcfg, ROOT)
    print(f"[6] 번역({engine})   {tmsg}")

    tldr, tldr_msg = translate.make_tldr(cards, tcfg)
    print(f"[7] TL;DR         {tldr_msg}")

    # 소스별 최종 채택 수를 리포트에 반영
    kept_by_source: dict[str, int] = {}
    for it in cards:
        kept_by_source[it.source_id] = kept_by_source.get(it.source_id, 0) + 1
    for r in reports:
        r.kept = kept_by_source.get(r.source_id, 0)

    # 탈락 항목을 기록해둔다. 필터를 조일지 풀지 판단하려면 무엇이 버려졌는지 봐야 한다.
    dropped_rows = [
        {"title": it.title, "url": it.url, "source": it.source_name,
         "tier": it.tier, "reason": it.drop_reason}
        for it in dropped
    ]

    brief = Brief(
        date_kst=end.date().isoformat(),
        generated_at=now_kst.isoformat(),
        window_start=start.isoformat(),
        window_end=end.isoformat(),
        headlines=headlines,
        cards=cards,
        tldr=tldr,
        dropped=dropped_rows,
        reports=reports,
        stats={
            "collected": len(raw_items),
            "in_window": len(items),
            "screened": len(kept),
            "clustered": len(unique),
            "merged": merged,
            "sources_total": len(reports),
            "sources_ok": sum(1 for r in reports if r.ok),
            "translate_engine": engine,
            "translate_status": tmsg,
            "tldr_status": tldr_msg,
            "translated": sum(1 for c in cards if c.translated),
            "dropped_reasons": _count_reasons(dropped),
        },
    )

    # --- 8) 렌더 + 저장 --------------------------------------------------
    paths = render.write_outputs(brief, ROOT)
    print(f"[8] 저장          {paths['json'].relative_to(ROOT)} · {paths['index'].relative_to(ROOT)}")

    # --- 9) 발송 ---------------------------------------------------------
    if args.dry_run or args.no_mail:
        print("[9] 메일          생략 (--dry-run)")
    else:
        try:
            mail.send(
                subject=f"[AI 브리핑] {brief.date_kst} · {len(cards)}건",
                html_body=render.render_email(brief),
            )
            print("[9] 메일          발송 완료")
        except mail.MailNotConfigured as exc:
            print(f"[9] 메일          건너뜀 ({exc})")

    if args.show_dropped:
        _print_dropped(dropped_rows, args.show_dropped)

    _print_health(brief)
    return 0


def _print_dropped(rows: list[dict], limit: int) -> None:
    """
    탈락 항목을 사유별로 묶어서 보여준다.

    이걸 보는 법:
      - "주제 무관"에 진짜 관련 있는 글이 섞여 있다 → screen.py의 TOPIC_TERMS에 단어 추가
      - "광고성 판정"에 멀쩡한 글이 있다 → scoring.yaml의 ad_filter 임계값을 올린다
      - 대부분이 정말 무관한 글이다 → 필터가 제 몫을 하는 것이니 그대로 둔다
    """
    if not rows:
        print("\n  탈락 항목 없음")
        return

    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["reason"].split("(")[0].strip(), []).append(r)

    print(f"\n  ── 탈락 항목 {len(rows)}건 " + "─" * 46)
    shown = 0
    for reason, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"\n  [{reason}] {len(items)}건")
        for r in items:
            if shown >= limit:
                print(f"       … 나머지 {len(rows) - shown}건 생략 (--show-dropped 200 으로 더 보기)")
                return
            print(f"       {r['tier']} {r['source'][:18]:<18} {r['title'][:70]}")
            shown += 1
    print()


def screen_items(items: list[Item], blocklist: dict, cfg: dict):
    from src import screen as screen_mod
    return screen_mod.screen(
        items,
        blocklist,
        ad_threshold=cfg["ad_filter"]["llm_threshold"],
        strict_threshold=cfg["ad_filter"]["strict_sources_threshold"],
    )


def _count_reasons(dropped: list[Item]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for it in dropped:
        key = it.drop_reason.split("(")[0].strip()
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def _print_health(brief: Brief) -> None:
    failed = [r for r in brief.reports if not r.ok]
    empty = [r for r in brief.reports if r.ok and r.collected == 0]

    print("\n  탈락 사유:", ", ".join(f"{k} {v}" for k, v in brief.stats["dropped_reasons"].items()) or "없음")
    if failed:
        print("  실패 소스:", ", ".join(f"{r.source_id}({r.error.split(':')[0]})" for r in failed))
    if empty:
        print("  0건 소스:", ", ".join(r.source_id for r in empty))

    if len(brief.cards) < 5:
        msg = f"⚠ 카드가 {len(brief.cards)}건뿐입니다. 필터가 과한지, 소스가 죽었는지 확인하세요."
        print("\n " + msg)
        mail.send_telegram(msg)
    print()


if __name__ == "__main__":
    sys.exit(main())
