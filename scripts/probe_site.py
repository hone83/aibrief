#!/usr/bin/env python3
"""
사이트 하나를 열어 글 링크를 어떻게 뽑는지 보여준다.

피드가 없는 사이트는 목록 페이지를 긁어야 하는데, 주소 패턴이 사이트마다 다르다.
이 스크립트로 먼저 확인한 뒤 sources.yaml의 link_pattern을 정하면 된다.

    python scripts/probe_site.py https://bfl.ai/blog
    python scripts/probe_site.py https://runway.com/news '/news/'
    python scripts/probe_site.py https://huggingface.co/papers '/papers/' --all

결과가 이상하면 그 출력을 그대로 알려주세요. 패턴을 맞춰 드립니다.
"""

import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.collect import UA, extract_links                       # noqa: E402

DEFAULT_PATTERN = r"/(news|blog|posts?|updates?|articles?)/"


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    heuristic = "--all" not in sys.argv

    if not args:
        print(__doc__)
        return 2

    url = args[0]
    pattern = args[1] if len(args) > 1 else DEFAULT_PATTERN

    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as c:
        r = c.get(url)

    print(f"\n  {url}")
    print(f"  HTTP {r.status_code} · {len(r.text) // 1024}KB · 최종 주소 {r.url}")
    print(f"  패턴 {pattern}" + ("" if heuristic else " · 슬러그 규칙 끔(--all)"))

    links = extract_links(r.text, str(r.url), re.compile(pattern, re.I), heuristic)
    if not links:
        print("\n  글 링크를 찾지 못했습니다.")
        print("  이 페이지에 실제로 있는 경로들을 몇 개 보여드리면:")
        paths = sorted({m for m in re.findall(r'"(/[a-z0-9][\w/.-]{4,60})"', r.text, re.I)})
        for path in paths[:25]:
            print(f"      {path}")
        if not paths:
            print("      (경로가 전혀 없습니다 — 로그인이 필요하거나 완전히 동적인 페이지)")
        return 1

    print(f"\n  글 링크 {len(links)}건:\n")
    for u, t in links[:25]:
        print(f"    {t[:58]:<60} {u}")
    if len(links) > 25:
        print(f"    … 외 {len(links) - 25}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
