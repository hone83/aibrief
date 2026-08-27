"""
번역 — 영어로 들어온 항목을 한국어로 바꾼다.

엔진을 세 개 넣고 설정에서 고를 수 있게 했다.

  gemini : 무료. LLM이라 번역 + 요약 + 3줄 불릿 + TL;DR을 한 번에 만든다.
           하루 1,500회까지 무료이고 카드 등록도 필요 없다. 이 앱은 하루 2회만 쓴다.
           단, 무료 등급의 입력은 구글이 모델 개선에 쓸 수 있다(공개 뉴스라 문제되지 않는다).
  claude : 유료(월 1천원 안팎). 하는 일은 gemini와 같다.
           입력이 학습에 쓰이지 않고, 한국어 문체가 조금 더 안정적이다.
  deepl  : 문장 단위 기계번역. 무료(월 50만자)지만 요약을 만들지는 못한다.
           피드가 요약문을 안 준 항목은 제목만 번역된 채로 남는다.
  none   : 번역하지 않음. 원문 그대로.

gemini와 claude는 프롬프트·파싱·캐시를 그대로 공유한다. HTTP 호출 부분만 다르다.

두 엔진 모두 실패해도 브리핑은 나간다. 번역은 '있으면 좋은 것'이지
'없으면 발행을 멈출 것'이 아니다. 실패하면 원문이 그대로 실리고 리포트에 이유가 남는다.

비용을 아끼는 장치가 두 개 있다.
  1) 번역은 최종 선별된 12건에만 적용한다. 수집한 200건을 다 번역하지 않는다.
  2) 결과를 uid로 캐시한다. 같은 날 두 번 돌려도 두 번 과금되지 않는다.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from pathlib import Path

import httpx

from .models import Item

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEEPL_FREE_URL = "https://api-free.deepl.com/v2/translate"
DEEPL_PRO_URL = "https://api.deepl.com/v2/translate"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

CACHE_MAX = 2000

# 번역은 느리다. 특히 Gemini 3.x는 기본적으로 '생각'을 하고 답하기 때문에
# 12건을 한 번에 넣으면 90초를 넘긴다(실제로 ReadTimeout이 났다).
# 연결은 빨리 포기하고, 응답은 길게 기다린다.
TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0)


class TranslationSkipped(RuntimeError):
    """번역을 건너뛴 이유. 브리핑을 멈추지 않고 리포트에만 남는다."""


# ==========================================================================
#  캐시
# ==========================================================================

def load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}          # 깨졌으면 그냥 새로 시작한다. 캐시는 없어도 되는 것이다.


def save_cache(path: Path, cache: dict) -> None:
    if len(cache) > CACHE_MAX:
        # 오래된 것부터 버린다
        ordered = sorted(cache.items(), key=lambda kv: kv[1].get("ts", ""), reverse=True)
        cache = dict(ordered[:CACHE_MAX])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def apply_cache(items: list[Item], cache: dict, engine: str) -> list[Item]:
    """캐시에 있는 건 채우고, 없는 것만 돌려준다."""
    todo: list[Item] = []
    for it in items:
        hit = cache.get(it.uid)
        if hit and hit.get("engine") == engine:
            it.title_ko = hit.get("title_ko", "")
            it.summary_ko = hit.get("summary_ko", "")
            it.bullets = hit.get("bullets", [])
        else:
            todo.append(it)
    return todo


def store_cache(items: list[Item], cache: dict, engine: str) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for it in items:
        if it.title_ko:
            cache[it.uid] = {
                "engine": engine, "ts": now,
                "title_ko": it.title_ko,
                "summary_ko": it.summary_ko,
                "bullets": it.bullets,
            }


# ==========================================================================
#  용어 사전
# ==========================================================================

def load_glossary(path: Path) -> dict:
    if not path.exists():
        return {"protect": [], "terms": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"protect": data.get("protect", []), "terms": data.get("terms", {})}


def enforce_terms(text: str, terms: dict[str, str]) -> str:
    """번역 결과에 영어 용어가 남아 있으면 지정된 한국어로 바꾼다 (DeepL 보정용)."""
    for en, ko in terms.items():
        text = re.sub(rf"\b{re.escape(en)}\b", ko, text, flags=re.I)
    return text


# ==========================================================================
#  엔진 1 · Claude
# ==========================================================================

def _claude_call(api_key: str, model: str, system: str, user: str, max_tokens: int) -> str:
    r = httpx.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        raise ApiError(f"HTTP {r.status_code} · {_api_detail(r)}", r.status_code)
    blocks = r.json().get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def _parse_json_array(text: str) -> list:
    """
    모델이 앞뒤에 설명을 붙이거나 ```json 펜스를 두르는 경우가 있다.
    첫 '['부터 마지막 ']'까지만 잘라내서 파싱한다.
    """
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"JSON 배열을 찾지 못함: {text[:120]}")
    return json.loads(text[start:end + 1])


CLAUDE_SYSTEM = """당신은 생성형 AI(이미지·비디오) 뉴스를 한국어로 옮기는 편집자입니다.

규칙:
1. 원문에 있는 내용만 씁니다. 배경지식이나 추측을 덧붙이지 않습니다.
2. 모델명·제품명·회사명·버전 숫자는 원문 표기를 그대로 둡니다. 예: Sora 2, FLUX.2, ComfyUI
3. 확인되지 않은 수치는 쓰지 않습니다.
4. 제목은 25자 내외의 자연스러운 한국어 뉴스 제목으로 만듭니다. 원문을 직역하지 말고,
   무엇이 일어났는지가 한눈에 보이게 씁니다.
5. 요약은 2~3문장. 불릿은 각 30자 내외로 3개. 정보가 부족하면 불릿을 줄입니다.
6. 번역투("~에 대해", "~하는 것을 통해")를 피하고 신문 기사체로 씁니다.

반드시 JSON 배열만 출력합니다. 설명이나 코드 펜스를 붙이지 마세요."""


def _build_user_prompt(items: list[Item], glossary: dict) -> str:
    """claude·gemini가 공유하는 요청 본문. 엔진이 달라도 지시는 같아야 결과가 비슷하다."""
    payload = [
        {
            "i": n,
            "title": it.title[:300],
            "summary": it.summary_raw[:900],
            "source": it.source_name,
            "category": it.category,
        }
        for n, it in enumerate(items)
    ]
    return (
        f"고유명사(그대로 둘 것): {', '.join(glossary['protect'][:60])}\n"
        f"용어 통일: {json.dumps(glossary['terms'], ensure_ascii=False)}\n\n"
        f"아래 {len(items)}건을 각각 번역·요약하세요.\n"
        f"출력 형식: [{{\"i\":0,\"title_ko\":\"...\",\"summary_ko\":\"...\",\"bullets\":[\"...\"]}}]\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def _apply_rows(rows: list, items: list[Item]) -> None:
    """모델이 돌려준 JSON 배열을 Item에 반영한다. i가 이상하면 그 줄만 버린다."""
    for row in rows:
        idx = row.get("i")
        if not isinstance(idx, int) or not (0 <= idx < len(items)):
            continue
        it = items[idx]
        it.title_ko = str(row.get("title_ko", "")).strip()
        it.summary_ko = str(row.get("summary_ko", "")).strip()
        it.bullets = [str(b).strip() for b in row.get("bullets", []) if str(b).strip()][:3]


def _run_llm(items: list[Item], cfg: dict, glossary: dict, call) -> list[str]:
    """
    LLM 번역의 공통 실행부. claude·gemini가 함께 쓴다.

    한 번에 다 보내지 않고 묶음으로 쪼개는 이유:
    12건을 한 요청에 넣으면 응답이 길어져 타임아웃이 난다. 그리고 그렇게 되면
    12건이 통째로 날아간다. 6건씩 나누면 한 묶음이 실패해도 나머지는 살아남는다.

    실패는 예외로 올리지 않고 사유 목록으로 돌려준다. 부분 성공이 정상 결과다.
    """
    size = max(1, int(cfg.get("chunk_size", 4)))
    retries = max(0, int(cfg.get("retries", 3)))
    base = float(cfg.get("retry_base_seconds", 4))
    failures: list[str] = []

    for start in range(0, len(items), size):
        group = items[start:start + size]
        for attempt in range(retries + 1):
            try:
                _apply_rows(_parse_json_array(call(_build_user_prompt(group, glossary))), group)
                break
            except (httpx.TimeoutException, httpx.HTTPStatusError, ApiError,
                    TranslationSkipped, ValueError, json.JSONDecodeError) as exc:
                # 키가 틀렸거나 요청이 잘못된 거라면 다시 보내도 똑같다. 바로 포기한다.
                hopeless = isinstance(exc, (ApiError, TranslationSkipped)) and \
                    not getattr(exc, "retryable", False)
                if attempt < retries and not hopeless:
                    # 지수 백오프: 4초 → 8초 → 16초.
                    # 503(혼잡)은 2초 만에 다시 보내봐야 또 밀린다.
                    time.sleep(base * (2 ** attempt))
                    continue
                # 이유를 그대로 남긴다. 종류만 적으면 무엇이 잘못됐는지 알 수 없다.
                reason = str(exc) if isinstance(exc, ApiError) else type(exc).__name__
                failures.append(reason)
                break
    return failures


def translate_claude(items: list[Item], cfg: dict, glossary: dict) -> list[str]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise TranslationSkipped("ANTHROPIC_API_KEY 미설정")

    model = cfg.get("claude_model", cfg.get("model", "claude-haiku-4-5"))
    return _run_llm(items, cfg, glossary, lambda user: _claude_call(
        api_key, model, CLAUDE_SYSTEM, user, max_tokens=cfg.get("max_tokens", 4000)))


# 다시 시도하면 될 오류 vs 시도해봐야 소용없는 오류.
# 503(혼잡)은 기다리면 풀리지만 401(키 오류)은 백 번 해도 같다.
RETRYABLE = {429, 500, 502, 503, 504}


class ApiError(RuntimeError):
    """API가 돌려준 오류. 본문을 그대로 담아서 무엇이 잘못됐는지 보이게 한다."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status

    @property
    def retryable(self) -> bool:
        return self.status in RETRYABLE


def _api_detail(r: httpx.Response) -> str:
    """오류 응답에서 사람이 읽을 메시지만 뽑아낸다."""
    try:
        payload = r.json()
    except ValueError:
        return r.text[:200].replace("\n", " ")
    err = payload.get("error", payload)
    if isinstance(err, dict):
        return str(err.get("message") or err.get("type") or err)[:220]
    return str(err)[:220]


def _gemini_call(api_key: str, model: str, system: str, user: str,
                 max_tokens: int, thinking: str = "low") -> str:
    """
    Gemini는 시스템 지시를 별도 필드로 받고, 응답은 parts 배열로 온다.
    responseMimeType을 application/json으로 두면 코드 펜스 없이 순수 JSON이 온다.
    (그래도 _parse_json_array를 통과시킨다 — 모델이 규칙을 어길 때가 있다.)
    """
    r = httpx.post(
        GEMINI_URL.format(model=model),
        headers={"x-goog-api-key": api_key, "content-type": "application/json"},
        json={
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
                "temperature": 0.3,
                # Gemini 3.x는 답하기 전에 오래 '생각'한다. 번역·요약은 추론이
                # 거의 필요 없는 일이라 낮춘다. 속도가 크게 빨라진다.
                #
                # 중첩 위치를 주의할 것 — generationConfig.thinkingConfig.thinkingLevel 이다.
                # 처음에 generationConfig.thinkingLevel 로 평평하게 넣었다가
                # "Unknown name" 400을 받았다.
                **({"thinkingConfig": {"thinkingLevel": thinking}} if thinking else {}),
            },
        },
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        detail = _api_detail(r)
        # 선택 항목 때문에 거부당한 거라면 그것만 빼고 한 번 더 시도한다.
        # API 스펙이 바뀌어도 번역이 통째로 멈추지 않게 하는 안전장치다.
        if r.status_code == 400 and thinking and "thinking" in detail.lower():
            return _gemini_call(api_key, model, system, user, max_tokens, thinking="")
        raise ApiError(f"HTTP {r.status_code} · {detail}", r.status_code)
    data = r.json()
    candidates = data.get("candidates") or []
    if not candidates:
        # 안전 필터에 걸리면 candidates가 비어 온다. 이유를 그대로 올려보낸다.
        raise TranslationSkipped(f"응답 없음: {json.dumps(data)[:160]}")
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts if "text" in p)


def _gemini_with_fallback(api_key: str, models: list[str], system: str, user: str,
                          max_tokens: int, thinking: str) -> str:
    """
    모델이 혼잡하면(503) 다음 모델로 넘어간다.

    무료 등급에서는 인기 모델이 자주 밀린다. 실제로 최신 flash가 503을 뱉는 동안
    같은 계정의 작은 요청은 통과했다. 한 모델만 붙잡고 있을 이유가 없으므로
    덜 붐비는 모델로 옮겨서라도 번역을 마치는 편이 낫다.
    """
    last: ApiError | None = None
    for model in models:
        try:
            return _gemini_call(api_key, model, system, user, max_tokens, thinking)
        except ApiError as exc:
            if not exc.retryable:
                raise                    # 키 오류 등은 모델을 바꿔도 똑같다
            last = ApiError(f"{model}: {exc}", exc.status)
    raise last or ApiError("모델을 모두 시도했으나 실패", 503)


def translate_gemini(items: list[Item], cfg: dict, glossary: dict) -> list[str]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise TranslationSkipped("GEMINI_API_KEY 미설정")

    models = [cfg.get("gemini_model", "gemini-3.7-flash")]
    models += [m for m in cfg.get("gemini_fallback_models", []) if m not in models]
    thinking = cfg.get("thinking_level", "low")
    return _run_llm(items, cfg, glossary, lambda user: _gemini_with_fallback(
        api_key, models, CLAUDE_SYSTEM,     # 지시는 엔진과 무관하게 동일하다
        user, max_tokens=cfg.get("max_tokens", 3000), thinking=thinking))


TLDR_SYSTEM = """당신은 생성형 AI 뉴스 브리핑의 편집장입니다.
오늘의 항목들을 보고 전체를 3문장으로 요약합니다.

규칙:
1. 각 문장은 40자 내외. 한 문장에 하나의 사건만.
2. 목록은 이미 중요도 순으로 정렬돼 있습니다. 1번을 첫 문장에 씁니다. 순서를 바꾸지 마세요.
3. 모델명·버전은 원문 표기 그대로.
4. "오늘은 ~한 하루였습니다" 같은 총평은 쓰지 않습니다. 사실만 씁니다.

반드시 JSON 배열만 출력합니다: ["문장1","문장2","문장3"]"""


def _tldr_llm(items: list[Item], cfg: dict, engine: str) -> list[str]:
    if not items:
        return []
    # 번호를 붙여 순위를 명시한다. 그냥 나열하면 모델이 제 판단으로 재배열해서,
    # 점수 1위인 비디오 모델 출시가 세 번째 줄로 밀린 적이 있다.
    prompt = "오늘의 항목 (중요도 순):\n" + "\n".join(
        f"{n}. [{it.category}] {it.display_title}" for n, it in enumerate(items[:12], 1)
    )

    if engine == "gemini":
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            return []
        models = [cfg.get("gemini_model", "gemini-3.7-flash")]
        models += [m for m in cfg.get("gemini_fallback_models", []) if m not in models]
        raw = _gemini_with_fallback(key, models, TLDR_SYSTEM, prompt, 800,
                                    cfg.get("thinking_level", "low"))
    else:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return []
        raw = _claude_call(key, cfg.get("claude_model", cfg.get("model", "claude-haiku-4-5")),
                           TLDR_SYSTEM, prompt, max_tokens=600)

    try:
        return [str(x).strip() for x in _parse_json_array(raw)][:3]
    except (ValueError, json.JSONDecodeError):
        return []


# ==========================================================================
#  엔진 2 · DeepL
# ==========================================================================

def _protect(text: str, protect: list[str]) -> str:
    """
    고유명사를 <x>태그로 감싸 DeepL이 건드리지 않게 한다.
    긴 이름부터 치환해야 'Stable Diffusion'이 'Stable'+'Diffusion'으로 쪼개지지 않는다.
    """
    for term in sorted(protect, key=len, reverse=True):
        text = re.sub(rf"(?<!<x>)\b{re.escape(term)}\b(?!</x>)",
                      f"<x>{term}</x>", text, flags=re.I)
    return text


def _unprotect(text: str) -> str:
    return text.replace("<x>", "").replace("</x>", "")


def translate_deepl(items: list[Item], cfg: dict, glossary: dict) -> list[str]:
    api_key = os.environ.get("DEEPL_API_KEY")
    if not api_key:
        raise TranslationSkipped("DEEPL_API_KEY 미설정")

    url = DEEPL_PRO_URL if cfg.get("pro") else DEEPL_FREE_URL
    protect = glossary["protect"]

    # 제목과 요약을 한 번에 보낸다. 순서가 그대로 돌아오므로 짝을 맞춰 되돌린다.
    texts: list[str] = []
    slots: list[tuple[Item, str]] = []
    for it in items:
        texts.append(_protect(it.title, protect))
        slots.append((it, "title"))
        if it.summary_raw:
            texts.append(_protect(it.summary_raw[:900], protect))
            slots.append((it, "summary"))

    if not texts:
        return []

    r = httpx.post(
        url,
        headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
        json={
            "text": texts,
            "target_lang": "KO",
            "source_lang": "EN",
            "tag_handling": "xml",
            "ignore_tags": ["x"],
        },
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        raise ApiError(f"HTTP {r.status_code} · {_api_detail(r)}", r.status_code)
    results = r.json().get("translations", [])
    if len(results) != len(texts):
        raise TranslationSkipped(f"DeepL 응답 개수 불일치 ({len(results)}/{len(texts)})")

    terms = glossary["terms"]
    for (it, kind), res in zip(slots, results):
        out = enforce_terms(_unprotect(res.get("text", "")), terms)
        if kind == "title":
            it.title_ko = out.strip()
        else:
            it.summary_ko = out.strip()
    return []


# ==========================================================================
#  진입점
# ==========================================================================

ENGINES = {
    "gemini": translate_gemini,
    "claude": translate_claude,
    "deepl": translate_deepl,
}


def translate(items: list[Item], cfg: dict, root: Path) -> tuple[str, str]:
    """
    선별된 항목을 번역한다. (엔진이름, 상태메시지)를 돌려준다.
    실패해도 예외를 밖으로 던지지 않는다 — 원문 그대로 발행되고 메시지만 남는다.
    """
    engine = cfg.get("engine", "none")
    if engine == "none" or not items:
        return engine, "번역 안 함"

    fn = ENGINES.get(engine)
    if fn is None:
        return engine, f"알 수 없는 엔진: {engine}"

    glossary = load_glossary(root / cfg.get("glossary", "config/glossary.json"))
    cache_path = root / "data" / "translation-cache.json"
    cache = load_cache(cache_path)

    todo = apply_cache(items, cache, engine)
    cached = len(items) - len(todo)

    if not todo:
        return engine, f"캐시 적중 {cached}건 · 호출 0회"

    try:
        failures = fn(todo, cfg, glossary) or []
    except TranslationSkipped as exc:
        return engine, f"건너뜀 ({exc})"
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:120].replace("\n", " ")
        return engine, f"실패 (HTTP {exc.response.status_code}: {body})"
    except Exception as exc:  # noqa: BLE001 — 번역 실패가 발행을 막으면 안 된다
        return engine, f"실패 ({type(exc).__name__}: {exc})"

    done = sum(1 for it in todo if it.title_ko)
    store_cache(todo, cache, engine)     # 성공한 것만 저장된다 (title_ko가 있는 것만)
    save_cache(cache_path, cache)

    msg = f"번역 {done}/{len(todo)}건 · 캐시 {cached}건"
    if failures:
        # 일부만 실패해도 나머지는 살아 있다. 실패한 묶음은 다음 실행에서 다시 시도된다.
        msg += f"\n                  실패 {len(failures)}묶음 · " + " / ".join(sorted(set(failures)))
    return engine, msg


def make_tldr(items: list[Item], cfg: dict) -> tuple[list[str], str]:
    """
    TL;DR은 여러 항목을 읽고 무엇이 중요한지 판단해야 하므로 LLM 엔진에서만 만든다.
    deepl은 문장 번역기라 이걸 못 한다.

    (3줄, 상태메시지)를 돌려준다. 예전에는 실패를 그냥 삼켰는데, 그러면
    어느 날 TL;DR이 조용히 사라져도 이유를 알 수 없다(실제로 그런 날이 있었다).
    """
    engine = cfg.get("engine")
    if engine not in ("claude", "gemini"):
        return [], f"{engine} 엔진은 TL;DR을 만들지 않음"
    try:
        lines = _tldr_llm(items, cfg, engine)
        return lines, f"{len(lines)}줄" if lines else "빈 응답"
    except ApiError as exc:
        return [], str(exc)
    except Exception as exc:  # noqa: BLE001 — TL;DR이 없어도 브리핑은 나간다
        return [], f"{type(exc).__name__}: {exc}"[:120]
