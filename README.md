# 비주얼 AI 데일리 브리핑

이미지·비디오 생성 AI 소식을 매일 아침 한 장으로 정리한다.
서버 없이 GitHub Actions에서 돌고, 결과는 GitHub Pages로 발행된다.

**현재 범위** — 수집·필터·중복제거·랭킹은 규칙 기반, 번역·요약은 선택형 엔진.
브리핑은 한국어로 발행되고 원제를 함께 표기한다.

---

## 30분 세팅

### 1. 저장소 만들기

```bash
gh repo create visual-ai-brief --public --source=. --push
```

public으로 만든다. Actions가 무제한 무료이고 Pages를 바로 쓸 수 있다.
공개 범위는 아래 "무엇이 공개되나"를 참고.

### 2. Gmail 앱 비밀번호

Google 계정 → 보안 → **2단계 인증을 먼저 켠다** → 앱 비밀번호 → 16자리 생성.
계정 비밀번호로는 SMTP 로그인이 안 된다.

### 3. Secrets 등록

저장소 → Settings → Secrets and variables → Actions → New repository secret

| 이름 | 값 | 필수 |
|---|---|---|
| `GMAIL_USER` | 보내는 Gmail 주소 | ✓ |
| `GMAIL_APP_PASS` | 위에서 만든 16자리 | ✓ |
| `MAIL_TO` | 받는 주소 (생략 시 자기 자신) | |
| `GEMINI_API_KEY` | 번역 엔진이 `gemini`일 때 (기본값) | |
| `ANTHROPIC_API_KEY` | 번역 엔진이 `claude`일 때 | |
| `DEEPL_API_KEY` | 번역 엔진이 `deepl`일 때 | |
| `AA_API_KEY` | 모델 순위표 (artificialanalysis.ai/data-api) | |
| `NTFY_TOPIC` | 폰 알림 (ntfy). 남이 추측 못 할 긴 문자열 | |
| `TELEGRAM_TOKEN` | 폰 알림 (텔레그램). @BotFather에서 발급 | |
| `TELEGRAM_CHAT_ID` | 봇에게 말 건 뒤 getUpdates로 확인 | |

### 4. Pages 켜기

Settings → Pages → Source: **Deploy from a branch** → Branch: `main`, 폴더: `/docs`

주소는 `https://<계정>.github.io/visual-ai-brief/` 가 된다.

### 5. 소스 검증

```bash
pip install -r requirements.txt
python scripts/check_sources.py --write
```

43개 소스를 실제로 호출해서 죽은 피드를 표시하고,
유튜브 채널의 `channel_id`를 자동으로 찾아 `sources.yaml`에 채운다.
**이걸 먼저 돌려야 유튜브 수집이 동작한다.**

### 6. 첫 실행

```bash
python run.py --dry-run          # 메일 없이 파일만
open docs/index.html
```

맥에서 메일까지 시험해보려면 `.env.example`을 복사해 `.env`로 만들고 값을 채운다.
`.env`는 `.gitignore`에 있어 저장소에 올라가지 않는다.

```bash
cp .env.example .env
```

Actions 탭 → "데일리 브리핑" → Run workflow 로 클라우드에서도 한 번 눌러본다.

---

## 새 버전으로 갈아끼우기

zip을 받으면 **한 줄이면 끝난다.** 새로 풀지 말고 기존 폴더에서 실행한다.

```bash
cd ~/Documents/aibrief
bash update.sh                       # 다운로드 폴더에서 최신 zip을 알아서 찾는다
bash update.sh ~/Downloads/x.zip     # 직접 지정할 수도 있다
```

이 한 줄이 하는 일 — 코드 교체, 가상환경 확인(없으면 생성), 의존성 설치, 테스트 실행.

| 지켜지는 것 | 바뀌는 것 |
|---|---|
| `.env` (API 키) | `src/` `scripts/` `tests/` `run.py` |
| `data/` (아카이브·번역 캐시) | `config/` — 이전 것은 `backups/config-날짜/`에 보관 |
| `.venv/` (가상환경) | `README.md` `.github/` |

유튜브 `channel_id`처럼 **실행으로 얻은 값**은 새 설정으로 자동으로 옮겨진다
(`scripts/carry_over.py`). 이게 없던 시절엔 업데이트할 때마다 유튜브 소스가 전부 죽었다.

설정을 직접 고쳐 쓰고 있었다면 `backups/`에서 꺼내 다시 반영하면 된다.

---

## 폰에서 앱처럼 쓰기

사파리(아이폰) 또는 크롬(안드로이드)으로 사이트를 열고 **공유 → 홈 화면에 추가**.
아이콘이 생기고 주소창 없이 전체화면으로 열린다. 앱스토어를 거치지 않는다.

`docs/sw.js`가 마지막으로 본 화면을 캐시해 두므로 지하철이나 비행기 모드에서도 열린다.
전략은 "네트워크 먼저, 실패하면 캐시"라서 평소에는 항상 최신을 본다.

## 알림 받기

메일 말고 잠금화면으로 바로 받는 길이 두 가지 있다. 둘 다 무료이고 서버가 필요 없다.
하나만 채우면 되고, 둘 다 비워두면 알림 단계만 건너뛴다.

**ntfy** — 가장 단순하다. [ntfy 앱](https://ntfy.sh/)을 깔고 주제어를 하나 정해
구독한 뒤, 같은 값을 `NTFY_TOPIC`에 넣는다. 가입도 토큰도 없다.
대신 **주제어를 아는 사람은 누구나 같은 알림을 받을 수 있으므로**
`aibrief-h7k2m9x4qp`처럼 추측할 수 없는 문자열을 써야 한다.

**텔레그램** — 이미 쓰고 있다면 이쪽이 낫다. @BotFather에서 `/newbot`으로 봇을 만들고
토큰을 `TELEGRAM_TOKEN`에, 봇에게 아무 말이나 건 뒤
`api.telegram.org/bot<토큰>/getUpdates`에서 확인한 chat id를 `TELEGRAM_CHAT_ID`에 넣는다.
대화 기록이 남아 며칠 전 알림을 거슬러 볼 수 있다.

**RSS** — `docs/feed.xml`이 매 실행마다 만들어진다. 쓰던 RSS 앱이 있으면
사이트 주소 뒤에 `/feed.xml`을 붙여 구독하면 된다. 설정이 필요 없다.

## 지난 브리핑 · 검색 · 모델 히스토리

헤더의 **검색창**, **날짜** 버튼(미니 달력), **모델** 탭이 읽는 색인은 매 실행마다 다시 만들어진다.

    docs/dates.json          브리핑이 있는 날짜 (달력)
    docs/search-index.json   모든 날의 모든 카드 (검색)
    docs/models.json         이름별 등장 기록 (모델 탭)

색인을 HTML에 박지 않고 따로 두는 이유는 커밋을 깨끗하게 유지하기 위해서다.
페이지 안에 넣으면 하루가 지날 때마다 지난 페이지 전부가 바뀌어 커밋에 딸려 들어온다.

모델 카드에는 최신 헤드라인과, 기사 제목에서 뽑아낸 최근 버전이 함께 붙는다.
("Wan 3.0", "Kling 2.8" 같은 표기를 찾는다. 이름에 이미 버전이 붙어 있으면 생략된다.)

모델 탭의 이름 사전은 `config/glossary.json`의 `protect` 목록을 그대로 쓴다.
새 모델이 나오면 거기에 추가하면 다음 실행부터 탭에 잡힌다.
라이선스·저장소처럼 뉴스마다 나오지만 추적할 의미가 없는 이름은
`config/scoring.yaml`의 `history.exclude`에서 뺀다.

지난 브리핑 페이지(`docs/archive/`)는 매 실행마다 지금 디자인으로 다시 그려진다.
저장된 JSON이 원본이므로 화면을 바꿔도 과거가 옛 모습으로 남지 않는다.
내용이 같으면 파일을 쓰지 않아서 커밋에는 실제로 달라진 것만 올라간다.

**로컬에서 볼 때 주의** — `open docs/index.html`로 직접 열면 브라우저 보안 정책 때문에
검색·달력·모델 탭이 동작하지 않는다(색인 파일을 못 읽는다). 이렇게 열어야 한다.

    cd docs && python -m http.server 8000
    # 브라우저에서 http://localhost:8000

## 모델 순위표

'순위' 탭은 [Artificial Analysis](https://artificialanalysis.ai/)의 데이터 API에서 받아온다.
키는 artificialanalysis.ai/data-api에서 무료로 발급되고 하루 100회까지 쓸 수 있다
(이 앱은 하루 5회 쓴다).

무료 등급은 **모델 이름·Elo·오차범위**까지만 준다. 영상·이미지의 가격은 유료 등급 전용이다.
언어모델 판은 무료 등급에도 가격이 들어 있다.
유료로 올리면 설정을 고치지 않아도 가격 칸이 저절로 채워진다 —
정식 주소를 먼저 찔러 보고 권한이 없을 때만 무료 주소로 물러서기 때문이다.

    python scripts/probe_aa.py          # 키가 사는지, 어떤 값이 오는지
    python scripts/probe_aa.py --raw    # 응답 원본 필드까지

보는 판과 순서는 `config/scoring.yaml`의 `rankings.boards`에서 바꾼다.
순위 변동(▲▼)은 `data/rankings.json`에 저장된 직전 순위와 비교해서 나온다.
전부 실패한 날에는 이 파일을 덮어쓰지 않는다 — 기준을 잃으면 비교가 끊기기 때문이다.

출처 표기는 API 이용 조건이다. 화면 아래 크레딧을 지우지 말 것.

## 필터 튜닝

무엇이 버려졌는지 봐야 필터를 조일지 풀지 알 수 있다.

```bash
python run.py --dry-run --show-dropped        # 40건까지
python run.py --dry-run --show-dropped 200    # 더 많이
```

사유별로 묶여서 나온다. 읽는 법:

- **"주제 무관"에 관련 있는 글이 섞였다** → `src/screen.py`의 `TOPIC_TERMS`에 단어를 추가한다.
  새 모델 이름이 나왔는데 사전에 없으면 그 소식이 통째로 걸러진다.
- **"광고성 판정"에 멀쩡한 글이 있다** → `config/scoring.yaml`의 `ad_filter.llm_threshold`를 올린다.
- **대부분 정말 무관한 글이다** → 필터가 제 몫을 하는 것이니 그대로 둔다.

**주제 필터를 적용할지는 소스별로 정한다** — `sources.yaml`의 `skip_topic_filter`.

처음엔 "T0 공식 발표는 무조건 통과"로 만들었는데 이게 틀렸다.
Runway·Midjourney는 무엇을 발표하든 비주얼 AI가 맞지만, OpenAI·Google은 종합 AI 회사라
칩·관리자 플러그인·여론조작 대응까지 발표한다. 실제로 OpenAI 카드 4장 중 3장이 무관한 소식이었다.

기준은 **"이 소스가 내놓는 게 전부 비주얼 AI인가"**다.

| `skip_topic_filter: true` | 필터 적용 |
|---|---|
| 비주얼 전용 개발사(Runway·BFL·Midjourney…) | OpenAI, Google DeepMind/Research, Qwen |
| r/StableDiffusion, ComfyUI, Civitai | Hugging Face 블로그, Hacker News |
| 비주얼 AI 유튜브 채널 | TechCrunch, The Verge, Ars Technica |
| arXiv (질의가 이미 주제 필터) | |

이 설정 덕분에 사전에 없는 신모델(H3, Krea 2 등)도 r/StableDiffusion에서는 그냥 통과한다.
사전을 아무리 넓혀도 어제 나온 모델 이름은 못 잡기 때문이다.

**본문이 없는 글은 카드가 되지 않는다.** r/aivideo 같은 작품 공유 게시판은
제목만 있고 본문이 없는 글이 많은데, 그런 게 실리면
"커뮤니티에 새 게시물이 등록되었습니다" 같은 빈 요약이 나온다.
`screen.py`의 `MIN_CONTENT_CHARS`(기본 40자)로 조절한다. 면제가 셋 있다 —
출시·오픈소스 등 제목만으로 사건이 성립하는 카테고리, T0·T1 공식 소스,
그리고 제목에서 주제 용어가 잡힌 글. "Gaussian Splatting test with MiniMax H3"는
본문이 없어도 제목만으로 무슨 실험인지 알 수 있으므로 남긴다.

**논문은 코드·가중치가 공개된 것만 싣는다** — arXiv 소스의 `require_code: true`.
초록에서 GitHub·Hugging Face 링크나 "code will be released" 표현을 찾는다.
개념만 있는 논문은 당장 해볼 게 없어서 실무 브리핑에는 안 맞는다.

탈락 목록은 브리핑 페이지 하단에도 접힌 채로 들어간다.
매일 눈에 띄는 자리에 있어야 실제로 손보게 된다.

---

## 매일 무슨 일이 일어나나

```
22:20 UTC (07:20 KST)  Actions 시작
  ↓  43개 소스 동시 호출          20~40초
  ↓  URL 정규화 · 24시간 창 필터
  ↓  주제·광고 규칙 필터
  ↓  같은 사건 묶기
  ↓  점수 계산 · 헤드라인 5 + 카드 12 선별
  ↓  JSON + HTML + 메일 HTML 생성
  ↓  커밋 → Pages 자동 배포
08:00 KST 전후          메일 도착
```

커버 구간은 **전일 07:00 ~ 당일 07:00 KST**로 고정이다.
미국 발표가 한국 새벽에 몰리기 때문에, 이렇게 잘라야 하루가 통째로 비거나
같은 뉴스가 이틀 연속 실리는 일이 없다.

---

## 구조

```
config/
  sources.yaml       소스 43개. 여기만 고치면 소스가 늘고 준다
  scoring.yaml       관심 비중, 출력 건수, 점수 공식, 발행 시각, 번역 엔진
  glossary.json      번역하지 않을 고유명사 + 통일할 용어
src/
  models.py          파이프라인이 주고받는 데이터 모양 (Item, Brief, SourceReport)
  collect.py         소스 타입별 수집기. 소스 하나가 죽어도 전체는 산다
  normalize.py       URL 정규화, 시간창 계산
  screen.py          주제·광고 필터, 카테고리 분류
  dedupe.py          같은 사건 묶기
  score.py           점수 계산, 헤드라인·카드 선별
  translate.py       번역 엔진 (claude / deepl / none), 캐시, 용어 사전
  render.py          웹페이지 / 메일 HTML / JSON 출력
  mail.py            Gmail SMTP, 텔레그램 알림
scripts/
  check_sources.py   소스 전수 검사
run.py               파이프라인 오케스트레이터
data/YYYY-MM-DD.json 원본. 이게 진짜 데이터고 HTML은 파생물이다
docs/                Pages가 서빙하는 폴더
```

---

## 자주 하는 조정

**소스 추가** — `config/sources.yaml`에 항목 하나 붙여넣고 `check_sources.py` 실행

```yaml
  - id: my-source
    name: 새 소스
    tier: T1
    topics: [video]
    type: rss
    url: https://example.com/feed.xml
    enabled: true
```

**소스 잠깐 빼기** — `enabled: false`

**피드가 아예 없는 사이트** — `type: list`로 목록 페이지를 긁는다.

```yaml
  - id: bfl-blog
    type: list
    url: https://bfl.ai/blog
    link_pattern: '/blog/'        # 글 주소가 이 패턴을 포함해야 한다
    link_heuristic: true          # 여러 단어 슬러그만 글로 본다 (메뉴 링크 제외)
```

**날짜를 파싱하지 않는다.** 목록 페이지에는 발행일이 없거나 형식이 제각각이라,
대신 **처음 본 시각**을 발행일로 쓴다. 한 번 본 주소는 `data/seen.json`에 적어두고
다음부터는 새 주소만 새 글로 친다.

그래서 **소스를 처음 추가한 날은 아무것도 나오지 않는다** — "첫 실행 · 링크 N건 기록"이
리포트에 뜨고, 그다음 실행부터 새 글이 올라온다. 이러지 않으면 첫날에
지난 1년 치가 오늘 뉴스로 쏟아진다.

패턴이 맞는지 미리 확인하려면:

```bash
python scripts/probe_site.py https://bfl.ai/blog
python scripts/probe_site.py https://runway.com/news '/news/'
python scripts/probe_site.py https://huggingface.co/papers '/papers/' --all
```

찾은 링크와 제목을 그대로 보여준다. 하나도 못 찾으면 그 페이지에 실제로 있는
경로들을 대신 출력하므로, 그걸 보고 `link_pattern`을 고치면 된다.

**피드 주소만 모를 때** — `type: html`로 두고 사이트 주소만 적는다.
수집기가 페이지에서 `<link rel="alternate">`를 찾고, 없으면 `/feed`, `/rss.xml` 같은
흔한 경로를 두드려 본다. 찾으면 그대로 수집되고, 못 찾으면 리포트에 남는다.
`type: rss`로 적어둔 주소가 404가 되어도 같은 방식으로 새 주소를 찾는다.

**브리핑이 너무 짧다** — `scoring.yaml`의 `ad_filter.llm_threshold`를 올리거나
`screen.py`의 `TOPIC_TERMS`에 단어를 추가한다. 실행 로그의 "탈락 사유"가 단서다.

**같은 뉴스가 두 번 나온다** — `run.py`의 `dedupe.dedupe(kept, threshold=0.5)`를 0.4로 낮춘다

**관심사가 바뀌었다** — `scoring.yaml`의 `interests` 숫자만 고친다

---

## 번역

`config/scoring.yaml`의 `translate.engine` 한 줄로 바뀐다.

| 엔진 | 하는 일 | 비용 | 필요한 키 |
|---|---|---|---|
| `gemini` | 한국어 제목 + 요약 + 3줄 불릿 + TL;DR **(기본값)** | 무료 (하루 1,500회) | `GEMINI_API_KEY` |
| `claude` | 위와 동일. 입력이 학습에 쓰이지 않는다 | 월 1천원 안팎 | `ANTHROPIC_API_KEY` |
| `deepl` | 제목·요약 문장 번역. 요약을 새로 만들지는 못한다 | 무료 (월 50만자) | `DEEPL_API_KEY` |
| `none` | 번역 안 함. 원문 그대로 | 0원 | 없음 |

`gemini`와 `claude`는 프롬프트·용어 사전·캐시를 그대로 공유한다.
HTTP 호출부만 다르므로, 키를 바꿔 끼우면 결과 형식은 동일하다.

**gemini 무료 등급의 유일한 대가**는 입력이 구글의 모델 개선에 쓰일 수 있다는 점이다.
여기서 보내는 건 이미 공개된 뉴스 제목과 요약문이라 실질적인 문제가 없다.
그게 걸리면 `claude`로 바꾸면 된다 — 설정 한 줄이다.

한 번만 시험해보려면 설정을 안 고치고 실행할 때만 바꿀 수 있다.

```bash
python run.py --engine claude --dry-run
python run.py --engine deepl --dry-run
python run.py --engine none --dry-run
```

**비용을 아끼는 장치 두 개**

- 번역은 **최종 선별된 12건에만** 적용한다. 수집한 200건을 다 번역하지 않는다.
- 결과를 `data/translation-cache.json`에 항목 ID로 캐시한다.
  같은 날 다시 돌려도 새로 번역되지 않는다. 이 파일은 저장소에 커밋되므로
  깃허브 액션에서도 캐시가 유지된다.

**번역이 실패하면** 원문 그대로 발행되고 실행 로그에 이유가 남는다.
키가 없거나 API가 죽어도 브리핑은 멈추지 않는다.

**"high demand" (HTTP 503)이 나면** 구글 서버가 혼잡한 것이지 설정 문제가 아니다.
`gemini_fallback_models`에 적힌 순서대로 덜 붐비는 모델로 자동으로 옮겨 타고,
그래도 안 되면 4초 → 8초 → 16초 간격으로 다시 시도한다.
계속 실패하면 그날은 원문으로 발행되고, 다음 실행에서 실패한 묶음만 다시 번역된다.

**키 오류(401)나 잘못된 요청(400)은 재시도하지 않는다.** 다시 보내도 결과가 같기 때문이다.
이 경우는 로그에 API가 준 설명이 그대로 찍히니 그걸 보고 고치면 된다.

**타임아웃이 나면** `scoring.yaml`의 `chunk_size`를 더 줄인다.
번역은 6건씩 나눠 보내고 실패한 묶음만 한 번 재시도하므로,
한 묶음이 죽어도 나머지는 정상 번역되어 나온다.
`thinking_level: low`는 Gemini가 답하기 전에 오래 '생각'하는 것을 막는 설정이다 —
기본값 medium으로 두면 12건 한 번에 3분을 넘긴다.

**용어가 매번 다르게 번역되면** `config/glossary.json`을 고친다.
`protect`에 넣은 이름은 번역하지 않고 원문으로 두고,
`terms`에 넣은 단어는 항상 지정한 한국어로 통일된다. 새 모델이 나오면 이름만 추가하면 된다.

---

## 무엇이 공개되나

public 저장소라 인터넷의 누구나 볼 수 있는 것:

- 소스 코드, 설정 파일, 커밋 이력
- **Actions 실행 로그** — 가장 놓치기 쉬운 곳
- `data/`의 수집 결과와 발행된 브리핑 페이지

가려지는 것:

- Secrets에 넣은 API 키·비밀번호 (로그에 찍혀도 자동 마스킹)

지킬 것 세 가지:

1. 키는 **반드시 Secrets에**. 코드나 설정 파일에 넣지 않는다.
2. 로그에 응답 원문을 출력하지 않는다. 건수와 소스명까지만.
3. 실수로 키를 커밋했다면 파일을 지워도 소용없다 — **키를 재발급**한다.

`docs/robots.txt`가 검색엔진 색인을 막지만, 주소를 아는 사람은 볼 수 있다.

---

## 로드맵

| 주차 | 범위 | 상태 |
|---|---|---|
| 1주차 | 수집 → 규칙 필터 → HTML → Actions → 메일 | ✅ |
| 2주차 | 한국어 번역·요약·TL;DR (엔진 전환형) | ✅ |
| 2주차 | HTML 파서, 아카이브 | |
| 3주차 | 검색 인덱스, 캘린더, PWA, 텔레그램 | |
| 4주차 | 소스 확장, 가중치 튜닝, 주간 회고 | |
| 이후 | 노션 동기화 (저장한 카드만) | |
