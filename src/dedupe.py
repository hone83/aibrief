"""
중복 묶기 — 같은 사건을 다룬 항목들을 하나로 묶는다.

이 앱에서 가장 중요한 단계다.
Runway가 새 모델을 내면 공식 블로그 1건 + 미디어 4건 + 유튜브 3건 + HN 1건이
따로 들어온다. 안 묶으면 카드 12장 중 9장이 같은 뉴스가 된다.

방법: 제목을 토큰(단어) 집합으로 바꾸고 자카드 유사도로 비교한다.
  자카드 유사도 = 교집합 크기 / 합집합 크기
  "Runway launches Gen-5"  → {runway, launches, gen5}
  "Runway Gen-5 is here"   → {runway, gen5, here}
  교집합 2 / 합집합 4 = 0.5

임베딩(문장을 벡터로 바꿔 의미를 비교하는 방법)이 더 정확하지만,
모델 이름과 버전 숫자가 핵심인 이 도메인에서는 단어 겹침만으로도 충분히 잡힌다.
무료이고 즉시 계산되며 결과를 눈으로 설명할 수 있다는 게 더 큰 장점이다.
정확도가 부족해지면 2주차에 임베딩으로 교체한다.
"""

from __future__ import annotations

import re
import unicodedata

from .models import Item

# 어느 제목에나 나오는 단어들. 이게 겹쳤다고 같은 사건은 아니다.
STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on", "for",
    "with", "and", "or", "it", "its", "this", "that", "you", "your", "we", "our",
    "new", "now", "how", "what", "why", "ai", "model", "models", "video", "image",
    "generation", "generative", "using", "use", "best", "top",
}

TOKEN = re.compile(r"[a-z0-9]+")

# "gen5", "wan22", "veo35" 처럼 이름+버전이 붙은 토큰.
# 이 도메인에서는 이게 사실상 사건의 고유 키다.
KEY_TOKEN = re.compile(r"^[a-z]+\d+$")


def tokenize(title: str) -> set[str]:
    """
    제목을 비교용 단어 집합으로 바꾼다.

    핵심은 버전 표기 정규화다. 같은 모델이 매체마다 다르게 적힌다.
      "Gen-5" / "Gen 5" / "gen5"      → gen5
      "Kling 2.8" / "Kling2.8"        → kling28
    이걸 안 맞추면 같은 사건이 절대 안 묶인다.
    """
    # 악센트를 떼어 ASCII로 맞춘다.
    # "Jalapeño"가 그냥 소문자화만 되면 토큰 정규식이 "jalape"와 "o"로 쪼개서
    # 같은 사건을 다룬 세 기사가 서로 다른 클러스터로 갈라졌다(실제로 그랬다).
    lowered = unicodedata.normalize("NFKD", title.lower())
    lowered = "".join(c for c in lowered if not unicodedata.combining(c))
    # 이름과 숫자를 붙이고, 버전의 소수점은 없앤다 (2.8 → 28)
    lowered = re.sub(
        r"\b([a-z]{2,})[\s\-]?v?(\d+(?:\.\d+)?)",
        lambda m: m.group(1) + m.group(2).replace(".", ""),
        lowered,
    )
    return {t for t in TOKEN.findall(lowered) if len(t) > 1 and t not in STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


TITLE_CASE_RATIO = 0.5


def proper_tokens(titles: list[str]) -> set[str]:
    """
    고유명사로 보이는 단어를 모은다. 제목 중간에서 대문자로 시작한 단어들이다.

    드문 단어만으로는 부족했다. 하루치가 40건쯤이면 built·local·world 같은
    평범한 영어 단어도 '드물게' 나오고, 그것만 겹쳐도 같은 사건으로 묶여버렸다.
    고유명사인지까지 확인해야 Jalapeño는 잡고 built는 거른다.

    단, 제목 전체가 Title Case인 경우(단어 대부분이 대문자로 시작)는
    대문자가 아무 정보도 주지 못하므로 그 제목의 대소문자는 무시한다.
    """
    import unicodedata as _ud
    found: set[str] = set()
    for title in titles:
        words = title.split()
        if len(words) < 3:
            continue
        capitalized = sum(1 for w in words if w[:1].isupper())
        if capitalized / len(words) > TITLE_CASE_RATIO:
            continue                      # Title Case 제목 — 대문자에 정보 없음
        for w in words[1:]:               # 첫 단어는 문장 시작이라 제외
            if not w[:1].isupper():
                continue
            plain = _ud.normalize("NFKD", w.lower())
            plain = "".join(c for c in plain if not _ud.combining(c))
            for tok in TOKEN.findall(plain):
                if len(tok) >= 4:
                    found.add(tok)
    return found


def rare_tokens(token_sets: list[set[str]], max_share: float = 0.12) -> set[str]:
    """
    오늘 들어온 항목 전체에서 '드물게 나오는 단어'를 골라낸다.

    왜 하루치 안에서 세는가: 무엇이 드문 단어인지는 그날 뉴스에 달려 있다.
    OpenAI가 하루에 네 건을 발표한 날 "openai"는 흔한 단어라 사건을 구별하지 못한다.
    반면 "jalapeno"는 그 칩 소식에만 나오므로 그것만으로 같은 사건임을 알 수 있다.
    검색에서 쓰는 IDF와 같은 발상이다.
    """
    if not token_sets:
        return set()
    # 상한이 너무 빡빡하면 여러 매체가 함께 보도한 큰 사건을 놓친다.
    # 55건 기준 상한 6 — 여섯 곳이 같은 단어를 쓰면 그건 오늘의 사건이라는 뜻이다.
    limit = max(3, int(len(token_sets) * max_share))
    counts: dict[str, int] = {}
    for ts in token_sets:
        for t in ts:
            counts[t] = counts.get(t, 0) + 1
    return {t for t, n in counts.items() if 2 <= n <= limit and len(t) >= 5}


def similarity(a: set[str], b: set[str], rare: set[str] | None = None) -> float:
    """
    자카드만으로는 이 도메인에서 부족하다.
      "Introducing Runway Gen-5: a new frontier for video generation"
      "Runway Gen-5 released"
    는 같은 사건인데 자카드가 0.4밖에 안 나온다. 문장 스타일이 너무 달라서다.

    그래서 조건을 하나 더 둔다 — 두 제목의 '모델+버전 키'가 완전히 같고
    그 밖의 단어도 최소 하나 겹치면 같은 사건으로 본다.

    '완전히 같을 것'을 요구하는 게 중요하다.
      릴리스 기사        키 = {kling28}
      비교 영상          키 = {kling28, veo35, seedance2}
    이 둘은 초점이 다르므로 묶으면 안 된다. 부분 일치를 허용하면 묶여버린다.
    """
    keys_a = {t for t in a if KEY_TOKEN.match(t)}
    keys_b = {t for t in b if KEY_TOKEN.match(t)}
    shared_other = (a & b) - keys_a

    if keys_a and keys_a == keys_b and shared_other:
        return 0.95

    # 버전 번호가 없는 사건도 있다. 칩·제품·회사 이름만 있는 경우가 그렇다.
    #   "OpenAI Jalapeño chip first results show industry-leading speed"
    #   "OpenAI's Jalapeño chip is built for fast inference at scale"
    # 위 둘은 같은 사건인데 자카드가 0.27이고 버전 키도 없어서 안 묶였다.
    #
    # 버전 번호가 없는 사건도 있다. 제품·칩 이름만 있는 경우가 그렇다.
    # 그럴 때는 '오늘 드물게 나온 단어'를 공유하는지 본다.
    # "jalapeno"는 그날 세 기사에만 나왔으므로 그 자체가 같은 사건이라는 신호다.
    if rare and (a & b & rare):
        return 0.9

    return jaccard(a, b)


class _UnionFind:
    """
    서로 비슷한 항목들을 같은 그룹으로 합치는 자료구조.
    A~B가 같고 B~C가 같으면 A~C도 같은 그룹이어야 하는데,
    이걸 직접 관리하면 코드가 금방 지저분해진다.
    """

    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]   # 경로 압축
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def brand_tokens(names: list[str]) -> set[str]:
    """
    회사·브랜드 이름을 토큰으로 편다. 이건 사건 식별에 쓰지 않는다.

    "openai"는 어느 날 다섯 건에 나오면 '드문 단어'로 분류되지만, 회사 이름이라
    서로 다른 사건에도 계속 나온다. 실제로 칩 소식과 소송 소식이 openai 하나로
    묶여버렸다. 반면 "jalapeno" 같은 제품 이름은 그 사건에만 나온다.
    구분 기준은 용어 사전의 protect 목록이다 — 거기 있는 건 회사·제품 고정 표기다.
    """
    out: set[str] = set()
    for name in names:
        out.update(t for t in TOKEN.findall(name.lower()) if len(t) >= 4)
    return out


def cluster(items: list[Item], threshold: float = 0.5,
            exclude: set[str] | None = None) -> list[list[Item]]:
    """
    비슷한 제목끼리 묶는다. 항목이 수백 개 수준이라 전수 비교(N²)로 충분하다.
    250건이면 약 3만 번 비교 — 1초도 안 걸린다.
    """
    tokens = [tokenize(it.title) for it in items]
    # '드물게 나오고' + '고유명사처럼 보이는' 단어만 사건 식별에 쓴다
    rare = rare_tokens(tokens) & proper_tokens([it.title for it in items])
    rare -= (exclude or set())          # 회사·브랜드 이름은 사건 식별에 쓰지 않는다
    uf = _UnionFind(len(items))

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if similarity(tokens[i], tokens[j], rare) >= threshold:
                uf.union(i, j)

    groups: dict[int, list[Item]] = {}
    for idx, it in enumerate(items):
        groups.setdefault(uf.find(idx), []).append(it)

    return list(groups.values())


def pick_representative(group: list[Item]) -> Item:
    """
    클러스터에서 대표 1건을 고른다.
    우선순위: 낮은 티어 번호(T0가 최우선) → 이른 발행 시각(원출처일 가능성)
    """
    return sorted(group, key=lambda x: (x.tier, x.published))[0]


def dedupe(items: list[Item], threshold: float = 0.5,
           exclude: set[str] | None = None) -> list[Item]:
    """대표만 남기고, 나머지는 대표의 related에 붙인다."""
    result: list[Item] = []

    for cid, group in enumerate(cluster(items, threshold, exclude)):
        rep = pick_representative(group)
        rep.cluster_id = cid
        rep.related = [
            {"title": o.title, "url": o.url, "source": o.source_name, "tier": o.tier}
            for o in group if o is not rep
        ]
        result.append(rep)

    return result
