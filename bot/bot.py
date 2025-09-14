# bot/bot.py
import os
import sys
import logging
import django
from dotenv import load_dotenv

# --- Proje kökünü sys.path'e ekle (…/crypto-alert) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# --- Django'yu ayağa kaldır (importlardan ÖNCE) ---
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "crypto_alert.settings")
django.setup()

# --- PTB ve job importları (Django setup'tan SONRA) ---
from telegram.ext import (  # type: ignore
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
)
from watcher.tasks import check_thresholds_and_notify

# --- .env ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# --- Log ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# --- Handler'ları relative import et (Django setup SONRASI) ---
from .handlers import (  # noqa: E402
    # Komut tabanlı
    start, help_cmd, close_menu, addtoken, mytokens, setthreshold,
    # Inline callback + wizard
    help_inline, close_inline,
    addtoken_inline_start, addtoken_inline_capture,
    setthreshold_inline_start, setthreshold_inline_low, setthreshold_inline_mid,
    setthreshold_inline_high, setthreshold_inline_apply,
    # Sabitler
    CB_ADD, CB_LIST, CB_SET, CB_HELP, CB_CLOSE,
    ST_ADD_CONTRACT, ST_SET_LO, ST_SET_MI, ST_SET_HI, ST_SET_CONTRACT,
)


def main() -> None:
    if not BOT_TOKEN:
        print("HATA: BOT_TOKEN bulunamadı. Lütfen .env dosyasını kontrol edin (BOT_TOKEN=...).")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # ---------- WIZARDLAR (ÖNCE bunları ekle) ----------
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(addtoken_inline_start, pattern=f"^{CB_ADD}$")],
        states={
            ST_ADD_CONTRACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, addtoken_inline_capture)],
        },
        fallbacks=[],
        name="addtoken_wizard",
        persistent=False,
    )
    app.add_handler(add_conv)

    set_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(setthreshold_inline_start, pattern=f"^{CB_SET}$")],
        states={
            ST_SET_LO: [MessageHandler(filters.TEXT & ~filters.COMMAND, setthreshold_inline_low)],
            ST_SET_MI: [MessageHandler(filters.TEXT & ~filters.COMMAND, setthreshold_inline_mid)],
            ST_SET_HI: [MessageHandler(filters.TEXT & ~filters.COMMAND, setthreshold_inline_high)],
            ST_SET_CONTRACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, setthreshold_inline_apply)],
        },
        fallbacks=[],
        name="setthreshold_wizard",
        persistent=False,
    )
    app.add_handler(set_conv)

    # ---------- Basit inline callback'ler ----------
    app.add_handler(CallbackQueryHandler(lambda u, c: mytokens(u, c), pattern=f"^{CB_LIST}$"))
    app.add_handler(CallbackQueryHandler(help_inline, pattern=f"^{CB_HELP}$"))
    app.add_handler(CallbackQueryHandler(close_inline, pattern=f"^{CB_CLOSE}$"))

    # ---------- Klasik komutlar ----------
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("addtoken", addtoken))
    app.add_handler(CommandHandler("mytokens", mytokens))
    app.add_handler(CommandHandler("setthreshold", setthreshold))

    # ReplyKeyboard'taki "Close" metnini yakalayıp menüyü kapatma (opsiyonel)
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^Close$"), close_menu))

    # ---------- Periyodik eşik kontrolü (DexScreener) ----------
    # 30 sn’de bir kontrol et (5 sn sonra başlasın)
    app.job_queue.run_repeating(check_thresholds_and_notify, interval=30, first=5)

    print("🚀 Bot çalışıyor… Komutlar:")
    print("  /start")
    print("  /help")
    print("  /addtoken <contract>")
    print("  /mytokens")
    print("  /setthreshold <low> <mid> <high> [contract]")

    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
