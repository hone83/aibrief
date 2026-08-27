"""
스크리닝 — 규칙만으로 걸러내고 분류한다. 1주차에는 LLM을 쓰지 않는다.

의도적으로 순서가 있다.
  1) 주제 관련성  : 비주얼 AI와 무관하면 여기서 끝. 가장 많이 걸러진다.
  2) 광고성 판정  : 도메인 차단 → 제목 패턴 → 낚시 신호
  3) 카테고리 분류: 사건 유형을 정한다. 점수 계산의 입력이 된다.

각 단계는 왜 떨어졌는지를 drop_reason에 남긴다.
필터가 너무 세면 브리핑이 비고, 너무 약하면 광고가 실린다.
이 이유 문자열이 튜닝의 유일한 단서다.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch

from .models import Item

# --------------------------------------------------------------------------
# 1) 주제 관련성 — 이 단어들 중 하나라도 없으면 비주얼 AI 뉴스가 아니다
# --------------------------------------------------------------------------
TOPIC_TERMS = {
    "video": [
        "sora", "veo", "kling", "runway", "gen-3", "gen-4", "gen-5", "luma", "ray2", "ray3",
        "pika", "hailuo", "minimax", "seedance", "ltx", "wan2", "wan 2", "hunyuanvideo",
        "cogvideo", "video model", "video generation", "text-to-video", "image-to-video",
        "video diffusion", "video generative", "world model", "frame interpolation",
        "motion transfer", "camera control", "비디오 생성", "영상 생성",
    ],
    "image": [
        "midjourney", "flux", "stable diffusion", "sdxl", "imagen", "dall-e", "dalle",
        "nano banana", "seedream", "qwen-image", "z-image", "ideogram", "recraft", "krea",
        "firefly", "image model", "text-to-image", "image generation", "image editing",
        "inpainting", "outpainting", "novel view", "3d generation", "rendering refinement",
        "identity preservation", "이미지 생성", "이미지 편집",
    ],
    "tools": [
        "comfyui", "comfy", "lora", "controlnet", "ipadapter", "workflow", "checkpoint",
        "civitai", "replicate", "fal.ai", "diffusers", "node", "inference", "quantiz",
        "워크플로우", "파인튜닝", "finetune", "fine-tune",
    ],
    "industry": [
        "copyright", "lawsuit", "regulation", "licensing", "funding", "acquisition",
        "저작권", "규제", "소송", "투자",
    ],
}

# 주제 필터를 건너뛸지는 티어가 아니라 소스별로 정한다(sources.yaml의 skip_topic_filter).
#
# 처음에는 "T0 공식 발표는 무조건 통과"로 만들었는데 이게 틀렸다.
# Runway·Midjourney·BFL은 무엇을 발표하든 비주얼 AI가 맞다. 하지만
# OpenAI·Google은 종합 AI 회사라 칩·관리자 플러그인·여론조작 대응까지 발표한다.
# 실제 브리핑에서 OpenAI 카드 4장 중 3장이 비주얼과 무관한 소식이었다.
#
# 그래서 기준을 "그 소스가 내놓는 것이 전부 비주얼 AI인가"로 바꿨다.
#   확정된 소스 : 비주얼 전용 개발사, r/StableDiffusion, ComfyUI, Civitai,
#                 비주얼 AI 유튜브 채널, 그리고 이미 주제로 검색해 오는 arXiv
#   필터 적용   : OpenAI·Google·미디어·Hacker News 등 범용 소스

# --------------------------------------------------------------------------
# 2) 카테고리 규칙 — 위에서부터 먼저 맞는 것을 채택한다 (순서가 곧 우선순위)
# --------------------------------------------------------------------------
CATEGORY_RULES: list[tuple[str, re.Pattern]] = [
    # 비교·리뷰를 가장 먼저 본다.
    # "Kling 2.8 vs Veo 3.5"는 모델명과 버전이 들어 있어서 아래 model_release에도 걸린다.
    # 순서가 곧 우선순위이므로, 더 구체적인 규칙이 위에 있어야 한다.
    ("benchmark", re.compile(
        r"\b(benchmark|head[- ]to[- ]head|shootout|first look|hands[- ]on|"
        r"comparison|tested|leaderboard|arena)\b|\bvs\.?\b", re.I)),
    # 가중치를 공개한 릴리스는 그 자체가 사건이다.
    # "Wan 2.2 weights are now available"는 model_release 규칙에도 걸리므로
    # 더 구체적인 이쪽이 위에 있어야 한다.
    ("opensource", re.compile(
        r"\b(open[- ]?sourc\w+|weights? (are )?(now )?(available|released)|"
        r"apache 2|mit licen[sc]e|hugging ?face)\b|github\.com", re.I)),
    ("model_release", re.compile(
        r"\b(introduc\w+|announc\w+|releas\w+|launch\w+|unveil\w+|now available|"
        r"we'?re bringing|meet )\b.*\b(model|v\d|\d\.\d)\b"
        r"|\b(sora|veo|kling|flux|wan|ltx|seedance|hunyuanvideo|imagen|gen)[\s.-]?\d",
        re.I)),
    ("workflow", re.compile(
        r"\b(workflow|tutorial|how ?to|guide|walkthrough|pipeline|explain\w+|"
        r"deep dive|under the hood|actually works?|consistent character|prompting|tips?)\b",
        re.I)),
    ("major_update", re.compile(
        r"\b(update|upgrade|new feature|adds?|improv\w+|now supports?|"
        r"expand\w+|rolling out|release notes?)\b", re.I)),
    ("industry", re.compile(
        r"\b(lawsuit|copyright|regulation|polic\w+|funding|raises?|valuation|"
        r"acquisition|partnership|settlement|licensing)\b|저작권|규제|소송", re.I)),
]

# --------------------------------------------------------------------------
# 3) 낚시·광고 신호
# --------------------------------------------------------------------------
# 이보다 짧은 본문은 요약할 게 없다고 본다 (제목만 있는 작품 공유 글)
MIN_CONTENT_CHARS = 40

CLICKBAIT = re.compile(
    r"(?i)(you won'?t believe|shocking|insane|mind[- ]blow|game[- ]?chang|"
    r"this changes everything|nobody is talking about|\bomg\b|🤯|😱)")
EXCESS_PUNCT = re.compile(r"[!?]{2,}|[A-Z]{6,}")


def infer_topics(item: Item) -> list[str]:
    """
    항목의 실제 주제를 본문에서 추론한다.

    소스에 적어둔 topics는 '이 소스가 주로 다루는 분야'라는 힌트일 뿐이다.
    TechCrunch를 industry로 등록해뒀다고 해서 거기 실린 Runway 기사가
    비디오 뉴스가 아닌 게 아니다. 소스의 topics로 관련성을 판정하면
    바로 그런 기사가 '주제 무관'으로 탈락한다. (실제로 처음에 그렇게 됐다.)

    그래서 전체 용어 사전으로 검사하고, 맞은 주제를 항목의 topics로 덮어쓴다.
    이 값이 점수 계산의 관심도 배수로 그대로 들어가므로 정확도가 중요하다.
    """
    haystack = f"{item.title} {item.summary_raw}".lower()
    matched = [topic for topic, terms in TOPIC_TERMS.items()
               if any(t in haystack for t in terms)]
    return matched or []


def is_blocked(item: Item, blocklist: dict) -> str:
    """차단 목록에 걸리면 이유 문자열을, 아니면 빈 문자열을 돌려준다."""
    for pattern in blocklist.get("domains", []):
        target = f"{item.domain}{'' if pattern.count('/') == 0 else '/' + item.url.split('/', 3)[-1]}"
        if fnmatch(item.domain, pattern) or fnmatch(target, pattern):
            return f"차단 도메인({pattern})"

    for pattern in blocklist.get("title_patterns", []):
        if re.search(pattern, item.title):
            return f"차단 제목패턴({pattern[:24]}…)"

    return ""


def ad_score(item: Item) -> float:
    """
    0.0(정상) ~ 1.0(명백한 광고). 규칙 기반 근사치다.
    2주차에 LLM 판정이 붙으면 이 값은 1차 후보를 좁히는 용도로만 남는다.
    """
    score = 0.0
    if CLICKBAIT.search(item.title):
        score += 0.45
    if EXCESS_PUNCT.search(item.title):
        score += 0.20
    if item.title.count("|") >= 2 or item.title.count("-") >= 3:
        score += 0.10                       # SEO용 제목 조립 흔적
    if re.search(r"(?i)\b(free|download now|sign ?up|try (it )?now)\b", item.title):
        score += 0.20
    if item.ad_filter == "strict":
        score += 0.15
    return min(score, 1.0)


def categorize(item: Item) -> str:
    haystack = f"{item.title} {item.summary_raw[:300]}"
    for name, pattern in CATEGORY_RULES:
        if pattern.search(haystack):
            return name
    if item.extra.get("kind") == "paper":
        return "benchmark"
    if item.extra.get("kind") == "release":
        # GitHub 릴리스는 제목이 "ComfyUI v0.9.0"처럼 짧아서 어느 규칙에도 안 걸린다.
        # 하지만 릴리스라는 사실 자체가 이미 '오픈소스 업데이트'라는 정보다.
        return "opensource"
    if item.tier == "T0":
        return "major_update"               # 공식 발표는 최소 '업데이트'로 본다
    return "minor"


def screen(items: list[Item], blocklist: dict, ad_threshold: float,
           strict_threshold: float) -> tuple[list[Item], list[Item]]:
    """통과한 항목과 떨어진 항목을 나눠서 돌려준다. 떨어진 쪽도 리포트에 쓴다."""
    kept: list[Item] = []
    dropped: list[Item] = []

    for it in items:
        if len(it.title) < 8:
            it.drop_reason = "제목 너무 짧음"
            dropped.append(it)
            continue

        reason = is_blocked(it, blocklist)
        if reason:
            it.drop_reason = reason
            dropped.append(it)
            continue

        # 논문은 코드·가중치가 공개된 것만 싣는다 (sources.yaml의 require_code).
        # 개념만 있는 논문은 당장 해볼 수 있는 게 없어서 실무 브리핑에는 안 맞는다.
        if it.extra.get("kind") == "paper" and it.extra.get("require_code") \
                and not it.extra.get("has_code"):
            it.drop_reason = "논문 · 코드 미공개"
            dropped.append(it)
            continue

        matched = infer_topics(it)
        if matched:
            it.topics = matched          # 추론 결과로 덮어쓴다 (점수 계산의 입력)
        elif it.extra.get("pre_filtered"):
            # 주제가 확정된 소스. 다만 topics를 소스 선언값 그대로 두면
            # 관심도 배수를 과하게 받는다(OpenAI 칩 기사가 video 2.0배를 받았다).
            # 용어가 안 잡혔다는 건 확신이 낮다는 뜻이므로 tools로 낮춰 잡는다.
            it.topics = it.topics or ["tools"]
        else:
            it.drop_reason = "주제 무관"
            dropped.append(it)
            continue

        threshold = strict_threshold if it.ad_filter == "strict" else ad_threshold
        score = ad_score(it)
        if score >= threshold:
            it.drop_reason = f"광고성 판정({score:.2f} ≥ {threshold})"
            dropped.append(it)
            continue

        it.category = categorize(it)

        # 요약할 내용이 없는 글은 카드가 될 수 없다.
        # r/aivideo 같은 작품 공유 게시판은 제목만 있고 본문이 없는 글이 많은데,
        # 그런 게 카드로 올라오면 "커뮤니티에 새 게시물이 등록되었습니다" 같은
        # 아무 정보 없는 요약이 나온다(실제로 카드 12장 중 4장이 그랬다).
        #
        # 다만 처음 만들었을 때 너무 많이 걸렸다. 세 가지를 면제한다.
        #   - 출시·오픈소스 등 제목만으로 사건이 성립하는 카테고리
        #   - T0·T1 공식 블로그·연구 소스 (제목이 곧 발표다)
        #   - 제목에서 주제 용어가 잡힌 글
        #     "Gaussian Splatting test with MiniMax H3"는 본문이 없어도
        #     제목만으로 무슨 실험인지 알 수 있다. 이런 게 빠지면 안 된다.
        if (it.category == "minor"
                and len(it.summary_raw) < MIN_CONTENT_CHARS
                and it.tier not in ("T0", "T1")
                and not matched):
            it.drop_reason = "내용 없음"
            dropped.append(it)
            continue

        kept.append(it)

    return kept, dropped
