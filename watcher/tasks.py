# watcher/tasks.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple, Optional

from asgiref.sync import sync_to_async
from telegram import Bot
from watcher.models import UserToken
from bot.service import fetch_many_stats            # DexScreener client (aiohttp, async)
from bot.services import send_telegram_message     # Telegram sender (aiohttp, async)

Level = str  # "none" | "low" | "mid" | "high"


# ---------------- DB helpers (sync → async) ----------------
@sync_to_async
def _load_user_tokens() -> List[Dict[str, Any]]:
    """
    UserToken'ları tek query ile gerekli alanlar halinde döndürür.
    """
    qs = (UserToken.objects
          .select_related("user", "token")
          .values(
              "id",
              "user__telegram_id",
              "token__contract_address",
              "threshold_low",
              "threshold_mid",
              "threshold_high",
              "last_alert_level",
              "last_seen_mcap",
          ))
    return list(qs)

@sync_to_async
def _update_level_and_seen(ut_id: int, new_level: Level, mcap: Optional[float]) -> int:
    return (UserToken.objects
            .filter(id=ut_id)
            .update(last_alert_level=new_level, last_seen_mcap=mcap))

@sync_to_async
def _update_seen_only(ut_id: int, mcap: Optional[float]) -> int:
    return (UserToken.objects
            .filter(id=ut_id)
            .update(last_seen_mcap=mcap))


# ---------------- Seviye hesaplama ----------------
def _level_for(mcap: float, low: float, mid: float, high: float) -> Level:
    if mcap >= high:
        return "high"
    if mcap >= mid:
        return "mid"
    if mcap >= low:
        return "low"
    return "none"


# ---------------- Ana job (PTB JobQueue ile çağrılır) ----------------
async def check_thresholds_and_notify(context) -> None:
    """
    - Tüm kullanıcıların takip ettiği kontratları çek
    - DexScreener'dan mcap verilerini topla
    - Eşik aşımı varsa kullanıcıya bildir, DB'yi güncelle
    Not: Sadece YUKARI yönlü yeni seviyeye geçişte bildirim atar.
    """
    # 1) DB: user-token kayıtlarını al
    uts = await _load_user_tokens()
    if not uts:
        return

    # 2) Unique kontrat listesi çıkar → tek seferde API çağır
    contracts = sorted({row["token__contract_address"] for row in uts})
    stats: Dict[str, Tuple[Optional[float], Dict[str, Any]]] = await fetch_many_stats(contracts)

    # 3) Her user-token için kontrol et
    for row in uts:
        ut_id = row["id"]
        chat_id = row["user__telegram_id"]
        contract = row["token__contract_address"]
        low, mid, high = row["threshold_low"], row["threshold_mid"], row["threshold_high"]
        prev_level: Level = row["last_alert_level"] or "none"

        mcap, detail = stats.get(contract, (None, {}))
        if mcap is None:
            # Veri alınamadı; sadece last_seen değiştir (isteğe bağlı)
            continue

        new_level = _level_for(mcap, low, mid, high)

        # Sadece YUKARI geçişte bildir (spam engeli)
        # none -> low/mid/high | low -> mid/high | mid -> high
        should_notify = (
            (prev_level == "none" and new_level in {"low", "mid", "high"}) or
            (prev_level == "low" and new_level in {"mid", "high"}) or
            (prev_level == "mid" and new_level == "high")
        )

        if should_notify:
            # Mesaj metni
            pair_url = detail.get("pair_url") or "https://dexscreener.com/"
            text = (
                "📈 *Market Cap Eşiği Aşıldı!*\n"
                f"`{contract}`\n"
                f"MCAP: *{int(mcap):,}* USD\n"
                f"Seviye: *{new_level.upper()}* "
                f"({int(low)}/{int(mid)}/{int(high)})\n"
                f"[Grafik / İşlem]({pair_url})"
            )
            try:
                if chat_id:
                    await send_telegram_message(str(chat_id), text, parse_mode="Markdown")
            except Exception:
                # Kullanıcı botu engellemiş olabilir, sessiz geç
                pass

            # DB güncelle
            await _update_level_and_seen(ut_id, new_level, mcap)
        else:
            # Seviye değişmediyse, sadece son görülen MCAP'i güncelle (opsiyonel)
            if row.get("last_seen_mcap") != mcap:
                await _update_seen_only(ut_id, mcap)
