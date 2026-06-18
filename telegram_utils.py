import asyncio
import os
import re
from pathlib import Path
from typing import Optional, Dict, Any
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().with_name(".env"))

def _env(name):
    value = os.getenv(name)
    return value.strip() if value else None

def _redact_secret(text: str) -> str:
    token = _env("TELEGRAM_TOKEN") or _env("telegram_token")
    if token:
        text = text.replace(token, "<redacted-token>")
    return re.sub(r"/bot[^/\s]+", "/bot<redacted-token>", text)

class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    async def send(self, text: str, parse_mode: str = "HTML") -> Optional[Dict[str, Any]]:
        if not self.token or not self.chat_id:
            return {"ok": False, "error": "Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID"}

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        def _post():
            try:
                resp = requests.post(url, data=payload, timeout=10)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                return {"ok": False, "error": _redact_secret(str(e))}

        # ✅ IMPORTANT: actually execute the request and return the result
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()

        return await loop.run_in_executor(None, _post)

def send_telegram_alert(text):
    token = _env("TELEGRAM_TOKEN") or _env("telegram_token")
    chat_id = (
        _env("TELEGRAM_CHAT_ID")
        or _env("telegram_chat_id")
        or _env("TELTGRAM_CHAT_ID")
        or _env("teltgram_chat_id")
    )
    if not token or not chat_id:
        print("Telegram alert skipped: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID is missing.")
        return None

    notifier = TelegramNotifier(token, chat_id)
    try:
        result = asyncio.run(notifier.send(text))
    except RuntimeError:
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(notifier.send(text))

    if isinstance(result, dict) and not result.get("ok", False):
        print(f"Telegram alert failed: {result}")
    return result
