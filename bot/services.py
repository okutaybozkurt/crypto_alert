# bot/services.py
import os
from typing import Optional

import aiohttp  # type: ignore
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


async def send_telegram_message(chat_id: str, text: str, parse_mode: Optional[str] = "Markdown") -> Optional[dict]:
    """
    Telegram'a asenkron mesaj gönderir. (watcher/tasks.py içinden await ile çağrılır)
    """
    if not BOT_TOKEN:
        return None

    url = f"{BASE_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
    except Exception:
        return None
