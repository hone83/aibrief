"""
메일 발송 — Gmail SMTP로 나에게 보낸다.

왜 Gmail SMTP인가:
Resend 같은 서비스는 도메인 인증이 필요하고 설정에 두어 시간이 든다.
혼자 보는 단계에서는 Gmail 앱 비밀번호 하나면 30분 안에 끝난다.
구독자가 생기면 그때 Resend로 갈아탄다 (render_email 결과를 그대로 보내면 된다).

앱 비밀번호 만드는 법:
  Google 계정 → 보안 → 2단계 인증 켜기 → 앱 비밀번호 → 16자리 생성
  일반 계정 비밀번호로는 SMTP 로그인이 안 된다.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


class MailNotConfigured(RuntimeError):
    pass


def send(subject: str, html_body: str, *, text_fallback: str = "") -> None:
    """
    필요한 환경변수 (GitHub Actions에서는 Secrets로 주입):
      GMAIL_USER      보내는 계정        예) me@gmail.com
      GMAIL_APP_PASS  앱 비밀번호 16자리
      MAIL_TO         받는 주소 (없으면 GMAIL_USER와 동일)
    """
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASS")
    to = os.environ.get("MAIL_TO") or user

    if not user or not password:
        raise MailNotConfigured("GMAIL_USER / GMAIL_APP_PASS 미설정")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("비주얼 AI 브리핑", user))
    msg["To"] = to
    # 텍스트 파트를 먼저 넣고 HTML을 add_alternative로 덮는다.
    # HTML을 못 읽는 클라이언트는 텍스트를, 나머지는 HTML을 본다.
    msg.set_content(text_fallback or "HTML 메일입니다. HTML 보기를 지원하는 앱에서 열어주세요.")
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.starttls()          # 평문 연결을 TLS로 승격. 이걸 빼면 비밀번호가 그대로 나간다
        smtp.login(user, password)
        smtp.send_message(msg)


def send_telegram(text: str) -> bool:
    """
    속보·장애 알림용. 봇 만들기: 텔레그램에서 @BotFather → /newbot → 토큰 발급.
    chat_id는 봇에게 아무 메시지나 보낸 뒤
    api.telegram.org/bot<토큰>/getUpdates 를 열면 보인다.
    설정이 없으면 조용히 False를 돌려준다 — 알림은 있으면 좋고 없어도 되는 기능이다.
    """
    import httpx

    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False

    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=15,
        )
        return r.status_code == 200
    except Exception:  # noqa: BLE001 — 알림 실패가 브리핑을 막으면 안 된다
        return False
