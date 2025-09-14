# bot/handlers.py
import re
from typing import Optional, Tuple, List

from asgiref.sync import sync_to_async
from telegram import (
    Update,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
)

from watcher.models import User, Token, UserToken

# -------------------- Utils --------------------
# EVM (Ethereum/EVM zincirleri): 0x + 40 hex
HEX_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
# Solana: base58, 32–44
SOL_ADDR_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

def _is_supported_contract(addr: str) -> bool:
    return bool(HEX_ADDR_RE.match(addr) or SOL_ADDR_RE.match(addr))

def _tg_ids(update: Update) -> Tuple[str, Optional[str]]:
    return str(update.effective_user.id), update.effective_user.username

def _inline_menu() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("➕ Add Token", callback_data=CB_ADD),
         InlineKeyboardButton("📄 My Tokens", callback_data=CB_LIST)],
        [InlineKeyboardButton("⚙️ Set Thresholds", callback_data=CB_SET),
         InlineKeyboardButton("🆘 Help", callback_data=CB_HELP)],
        [InlineKeyboardButton("❌ Close", callback_data=CB_CLOSE)],
    ]
    return InlineKeyboardMarkup(kb)

# -------------------- Callback Keys & States (export) --------------------
CB_ADD = "ADD"
CB_LIST = "LIST"
CB_SET = "SET"
CB_HELP = "HELP"
CB_CLOSE = "CLOSE"

(ST_SET_LO, ST_SET_MI, ST_SET_HI, ST_SET_CONTRACT, ST_ADD_CONTRACT) = range(5)

# -------------------- DB Helpers (async-safe) --------------------
@sync_to_async
def _get_or_create_user(tg_id: str, username: Optional[str]) -> Tuple[User, bool]:
    return User.objects.get_or_create(telegram_id=tg_id, defaults={"username": username})

@sync_to_async
def _get_or_create_token(contract: str) -> Tuple[Token, bool]:
    return Token.objects.get_or_create(contract_address=contract)

@sync_to_async
def _get_or_create_user_token(user: User, token: Token) -> Tuple[UserToken, bool]:
    return UserToken.objects.get_or_create(
        user=user,
        token=token,
        defaults={"threshold_low": 500, "threshold_mid": 1000, "threshold_high": 1500},
    )

@sync_to_async
def _user_tokens(user: User) -> List[UserToken]:
    return list(
        UserToken.objects.select_related("token")
        .filter(user=user)
        .order_by("token__contract_address")
    )

@sync_to_async
def _update_thresholds_for_contract(user: User, contract: str, low: float, mid: float, high: float) -> int:
    try:
        token = Token.objects.get(contract_address=contract)
    except Token.DoesNotExist:
        return -1  # token yok
    return UserToken.objects.filter(user=user, token=token).update(
        threshold_low=low, threshold_mid=mid, threshold_high=high
    )

@sync_to_async
def _update_thresholds_for_all(user: User, low: float, mid: float, high: float) -> int:
    qs = UserToken.objects.filter(user=user)
    count = qs.count()
    if count:
        qs.update(threshold_low=low, threshold_mid=mid, threshold_high=high)
    return count

# -------------------- Komut Handlers --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id, username = _tg_ids(update)
    await _get_or_create_user(tg_id, username)

    if update.message:
        await update.message.reply_text("👋 Hoş geldin! Bir seçim yap:", reply_markup=_inline_menu())
    else:
        q = update.callback_query
        await q.edit_message_text("👋 Hoş geldin! Bir seçim yap:", reply_markup=_inline_menu())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆘 *Yardım*\n"
        "• `/addtoken <contract_address>` – Takip etmek istediğin adresi ekler\n"
        "• `/mytokens` – Takip ettiklerini listeler\n"
        "• `/setthreshold <low> <mid> <high> [contract]` – Eşikleri günceller",
        parse_mode="Markdown",
    )

async def close_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧹 Menü kapatıldı.", reply_markup=ReplyKeyboardRemove())

async def addtoken(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id, username = _tg_ids(update)
    user, _ = await _get_or_create_user(tg_id, username)

    if not context.args:
        await update.message.reply_text("⚠️ Kullanım: `/addtoken <contract_address>`", parse_mode="Markdown")
        return

    contract = context.args[0].strip()
    if not _is_supported_contract(contract):
        await update.message.reply_text(
            "❌ Geçersiz adres.\n"
            "• EVM: `0x` + 40 hex\n"
            "• Solana: base58, 32–44 karakter",
            parse_mode="Markdown",
        )
        return

    token, _ = await _get_or_create_token(contract)
    _, created = await _get_or_create_user_token(user, token)

    if created:
        await update.message.reply_text(f"✅ Takibe alındı:\n`{contract}`", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"ℹ️ Bu adres zaten listende:\n`{contract}`", parse_mode="Markdown")

async def mytokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Hem komutla (/mytokens) hem de inline callback ile çalışır
    is_callback = update.callback_query is not None
    if is_callback:
        q = update.callback_query
        await q.answer()

    tg_id, username = _tg_ids(update)
    user, _ = await _get_or_create_user(tg_id, username)

    try:
        items = await _user_tokens(user)
    except Exception as e:
        text = f"❌ DB hatası: {e}"
        if is_callback:
            await q.edit_message_text(text, reply_markup=_inline_menu())
        else:
            await update.message.reply_text(text)
        return

    if not items:
        text = "🗒️ Henüz takip ettiğin CA yok. `/addtoken <contract>` ile ekleyebilirsin."
        if is_callback:
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=_inline_menu())
        else:
            await update.message.reply_text(text, parse_mode="Markdown")
        return

    lines = [
        f"• `{ut.token.contract_address}` — thresholds: {int(ut.threshold_low)}/{int(ut.threshold_mid)}/{int(ut.threshold_high)}"
        for ut in items
    ]
    text = "📄 *Takip Listem:*\n" + "\n".join(lines)

    if is_callback:
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=_inline_menu())
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

async def setthreshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id, username = _tg_ids(update)
    user, _ = await _get_or_create_user(tg_id, username)

    if len(context.args) < 3:
        await update.message.reply_text(
            "⚠️ Kullanım: `/setthreshold <low> <mid> <high> [contract]`", parse_mode="Markdown"
        )
        return

    try:
        low = float(context.args[0]); mid = float(context.args[1]); high = float(context.args[2])
    except ValueError:
        await update.message.reply_text("❌ low/mid/high sayısal olmalı. Örn: `/setthreshold 500 1000 1500`", parse_mode="Markdown")
        return

    if not (0 < low <= mid <= high):
        await update.message.reply_text("❌ Kural: 0 < low ≤ mid ≤ high olmalı.")
        return

    if len(context.args) >= 4:
        contract = context.args[3].strip()
        if not _is_supported_contract(contract):
            await update.message.reply_text(
                "❌ Geçersiz adres. EVM: `0x..` | Solana: base58 (32–44).",
                parse_mode="Markdown",
            )
            return
        updated = await _update_thresholds_for_contract(user, contract, low, mid, high)
        if updated == -1:
            await update.message.reply_text("❌ Bu contract adresi listende yok. Önce `/addtoken` ile ekle.")
        elif updated == 0:
            await update.message.reply_text("❌ Bu token için bir kaydın bulunamadı.")
        else:
            await update.message.reply_text(
                f"✅ Eşik güncellendi (sadece `{contract}`): {int(low)}/{int(mid)}/{int(high)}",
                parse_mode="Markdown",
            )
        return

    count = await _update_thresholds_for_all(user, low, mid, high)
    if count == 0:
        await update.message.reply_text("🗒️ Önce `/addtoken <contract>` ile en az bir coin ekle.")
    else:
        await update.message.reply_text(
            f"✅ Eşikler *tüm takiplerin* için güncellendi: {int(low)}/{int(mid)}/{int(high)}",
            parse_mode="Markdown",
        )

# -------------------- Inline Callback Handlers --------------------
async def help_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🆘 *Yardım*\n"
        "• `/addtoken <contract_address>` – Takip etmek istediğin adresi ekler\n"
        "• `/mytokens` – Takip ettiklerini listeler\n"
        "• `/setthreshold <low> <mid> <high> [contract]` – Eşikleri günceller",
        parse_mode="Markdown",
        reply_markup=_inline_menu()
    )

async def close_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("🧹 Menü kapatıldı.")

# ---- Add Token (Inline Wizard) ----
async def addtoken_inline_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["mode"] = "addtoken"
    await q.edit_message_text("➕ CA: (0x… | base58)\nAdresini gönder:", parse_mode="Markdown")
    return ST_ADD_CONTRACT

async def addtoken_inline_capture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id, username = _tg_ids(update)
    user, _ = await _get_or_create_user(tg_id, username)
    contract = (update.message.text or "").strip()

    if not _is_supported_contract(contract):
        await update.message.reply_text(
            "❌ Geçersiz CA formatı.\nEVM: `0x` + 40 hex | Solana: base58 (32–44)",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    token, _ = await _get_or_create_token(contract)
    _, created = await _get_or_create_user_token(user, token)
    if created:
        await update.message.reply_text(f"✅ Takibe alındı: `{contract}`", parse_mode="Markdown", reply_markup=_inline_menu())
    else:
        await update.message.reply_text(f"ℹ️ Bu adres zaten listende: `{contract}`", parse_mode="Markdown", reply_markup=_inline_menu())

    return ConversationHandler.END

# ---- Set Thresholds (Inline Wizard) ----
async def setthreshold_inline_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    await q.edit_message_text("⚙️ low değerini gönder (örn. 500):")
    return ST_SET_LO

async def setthreshold_inline_low(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["low"] = float((update.message.text or "").strip())
    except ValueError:
        await update.message.reply_text("❌ low sayısal olmalı. Tekrar deneyelim: (örn. 500)")
        return ST_SET_LO
    await update.message.reply_text("mid değerini gönder (örn. 1000):")
    return ST_SET_MI

async def setthreshold_inline_mid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["mid"] = float((update.message.text or "").strip())
    except ValueError:
        await update.message.reply_text("❌ mid sayısal olmalı. (örn. 1000)")
        return ST_SET_MI
    await update.message.reply_text("high değerini gönder (örn. 1500):")
    return ST_SET_HI

async def setthreshold_inline_high(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["high"] = float((update.message.text or "").strip())
    except ValueError:
        await update.message.reply_text("❌ high sayısal olmalı. (örn. 1500)")
        return ST_SET_HI

    low, mid, high = context.user_data["low"], context.user_data["mid"], context.user_data["high"]
    if not (0 < low <= mid <= high):
        await update.message.reply_text("❌ Kural: 0 < low ≤ mid ≤ high. Baştan deneyelim: /setthreshold")
        return ConversationHandler.END

    await update.message.reply_text(
        "İstersen sadece *bir contract* için uygula. Contract adresini (0x… | base58) gönder.\n"
        "Ya da `Tüm takipler` yaz → hepsi için uygularım.",
        parse_mode="Markdown",
    )
    return ST_SET_CONTRACT

async def setthreshold_inline_apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    tg_id, username = _tg_ids(update)
    user, _ = await _get_or_create_user(tg_id, username)
    low, mid, high = context.user_data["low"], context.user_data["mid"], context.user_data["high"]

    if text.lower() in {"tüm takipler", "tum takipler", "hepsi", "all"}:
        count = await _update_thresholds_for_all(user, low, mid, high)
        if count == 0:
            await update.message.reply_text("🗒️ Önce en az bir coin ekle: /addtoken <contract>")
        else:
            await update.message.reply_text(
                f"✅ Eşikler tüm takiplerin için güncellendi: {int(low)}/{int(mid)}/{int(high)}",
                reply_markup=_inline_menu(),
            )
        return ConversationHandler.END

    if not _is_supported_contract(text):
        await update.message.reply_text(
            "❌ Geçersiz adres. EVM: `0x..` | Solana: base58 (32–44) veya `Tüm takipler` yaz.",
            parse_mode="Markdown",
        )
        return ST_SET_CONTRACT

    updated = await _update_thresholds_for_contract(user, text, low, mid, high)
    if updated == -1:
        await update.message.reply_text("❌ Bu contract listende yok. Önce /addtoken ile ekle.")
    elif updated == 0:
        await update.message.reply_text("❌ Bu token için bir kaydın bulunamadı.")
    else:
        await update.message.reply_text(
            f"✅ Eşik güncellendi (sadece `{text}`): {int(low)}/{int(mid)}/{int(high)}",
            parse_mode="Markdown",
            reply_markup=_inline_menu(),
        )
    return ConversationHandler.END
