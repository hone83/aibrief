"""
알림 — 메일 말고 폰으로 바로 받는 길.

왜 메일과 따로 두는가:
메일은 "나중에 읽을 것"이 쌓이는 곳이라 아침에 열지 않으면 그날 안 보게 된다.
알림은 잠금화면에 뜨고, 눌러서 웹으로 바로 넘어간다. 읽는 자리는 결국 웹이므로
알림 본문은 "볼 만한지"만 판단할 수 있으면 충분하다 — 제목 세 줄과 링크.

두 가지를 지원한다. 둘 다 서버가 필요 없고 무료다.

  ntfy      가장 단순하다. 앱을 깔고 주제어(topic)를 정하면 끝. 가입도 토큰도 없다.
            대신 주제어를 아는 사람은 누구나 같은 알림을 구독할 수 있으므로,
            남이 추측할 수 없는 긴 문자열을 써야 한다.
  telegram  이미 텔레그램을 쓴다면 이쪽이 낫다. 봇을 만들어 토큰을 받는다.
            대화 기록이 남아서 며칠 전 알림을 거슬러 볼 수 있다.

둘 다 설정이 없으면 조용히 건너뛴다. 알림이 없어도 브리핑은 나간다.
"""

from __future__ import annotations

import os

import httpx

TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _lines(brief) -> list[str]:
    """알림에 넣을 제목 세 줄. 폰 잠금화면에 보이는 분량이 대략 그 정도다."""
    heads = brief.headlines or brief.cards[:3]
    return [it.display_title for it in heads[:3]]


def send_ntfy(brief, site_url: str = "") -> tuple[bool, str]:
    """
    ntfy.sh로 보낸다. 필요한 환경변수는 NTFY_TOPIC 하나뿐이다.
    자체 서버를 쓴다면 NTFY_SERVER로 주소를 바꾼다.

    헤더 값은 ASCII만 담을 수 있어서 제목은 본문에 넣고,
    Title 헤더에는 날짜만 넣는다(한글 제목을 헤더에 넣으면 요청이 깨진다).
    """
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return False, "NTFY_TOPIC 없음"
    if not topic.isascii():
        return False, "NTFY_TOPIC은 영문·숫자여야 합니다"

    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    body = "\n".join(f"· {t}" for t in _lines(brief))
    body = f"{brief.date_kst} · {len(brief.cards)}건\n{body}"

    headers = {"Title": f"AI Brief {brief.date_kst}", "Tags": "clapper"}
    if site_url:
        headers["Click"] = site_url

    try:
        r = httpx.post(f"{server}/{topic}", data=body.encode("utf-8"),
                       headers=headers, timeout=TIMEOUT)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        return True, "발송 완료"
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}"


def send_telegram(brief, site_url: str = "") -> tuple[bool, str]:
    """
    텔레그램 봇으로 보낸다. 봇 만들기: 텔레그램에서 @BotFather → /newbot.
    받은 토큰을 TELEGRAM_TOKEN에, 봇에게 아무 말이나 건 뒤
    api.telegram.org/bot<토큰>/getUpdates 에서 확인한 chat id를 TELEGRAM_CHAT_ID에 넣는다.
    """
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return False, "TELEGRAM_TOKEN / CHAT_ID 없음"

    lines = "\n".join(f"· {t}" for t in _lines(brief))
    text = f"*AI 브리핑 {brief.date_kst}* · {len(brief.cards)}건\n{lines}"
    if site_url:
        text += f"\n\n[웹에서 보기]({site_url})"

    try:
        r = httpx.post(TELEGRAM_URL.format(token=token),
                       json={"chat_id": chat, "text": text,
                             "parse_mode": "Markdown",
                             "disable_web_page_preview": True},
                       timeout=TIMEOUT)
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        return True, "발송 완료"
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}"


def send_all(brief, site_url: str = "") -> str:
    """
    설정된 통로로 모두 보내고, 화면에 찍을 한 줄을 돌려준다.
    하나가 실패해도 나머지는 보낸다 — 알림은 여러 개일수록 안전한 쪽이다.
    """
    results = []
    for name, fn in (("ntfy", send_ntfy), ("telegram", send_telegram)):
        ok, msg = fn(brief, site_url)
        if ok:
            results.append(name)
        elif "없음" not in msg:          # 설정을 안 한 통로는 조용히 넘어간다
            results.append(f"{name} 실패({msg})")
    return " · ".join(results) if results else "설정된 알림 없음"


def alert(text: str) -> bool:
    """장애 알림용. 브리핑이 아니라 '뭔가 잘못됐다'를 알릴 때."""
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if topic and topic.isascii():
        server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
        try:
            httpx.post(f"{server}/{topic}", data=text.encode("utf-8"),
                       headers={"Title": "AI Brief warning", "Priority": "high",
                                "Tags": "warning"}, timeout=TIMEOUT)
            return True
        except httpx.HTTPError:
            pass
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and chat:
        try:
            httpx.post(TELEGRAM_URL.format(token=token),
                       json={"chat_id": chat, "text": text}, timeout=TIMEOUT)
            return True
        except httpx.HTTPError:
            pass
    return False
