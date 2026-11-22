"""Send messages to Telegram. Secrets come only from environment variables."""
import os

import requests

LIMIT = 4096


def load_dotenv(path=".env"):
    """Tiny .env loader for local runs (GitHub Actions uses real env vars)."""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def split(text, limit=LIMIT):
    """Split on line boundaries so HTML tags (one line each) are never cut."""
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit and cur:
            parts.append(cur)
            cur = ""
        cur += ("\n" if cur else "") + line
    return parts + ([cur] if cur else [])


def _creds():
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise RuntimeError("Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID")
    return token, chat


def send_photo(path, caption=""):
    token, chat = _creds()
    with open(path, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                          data={"chat_id": chat, "caption": caption[:1024], "parse_mode": "HTML"},
                          files={"photo": f}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram HTTP {r.status_code}: {r.text[:300]}")


def send(text):
    token, chat = _creds()
    for part in split(text):
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": part, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=30,
        )
        if r.status_code != 200:
            # never echo the URL (contains the token)
            raise RuntimeError(f"Telegram HTTP {r.status_code}: {r.text[:300]}")


if __name__ == "__main__":
    # Helper: after sending any message to your bot, print the chat ids it has seen.
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not tok:
        sys.exit("Đặt TELEGRAM_BOT_TOKEN trong .env trước")
    upd = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=30).json()
    seen = {(u.get("message") or u.get("channel_post") or {}).get("chat", {}).get("id"): 
            (u.get("message") or u.get("channel_post") or {}).get("chat", {}).get("title")
            or (u.get("message") or {}).get("chat", {}).get("first_name") for u in upd.get("result", [])}
    seen.pop(None, None)
    print(seen or "Chưa thấy tin nào. Nhắn /start cho bot rồi chạy lại.")
