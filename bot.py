import os
import logging
from dotenv import load_dotenv
from telegram import Update # pyright: ignore[reportMissingImports]
from telegram.ext import Application, CommandHandler, ContextTypes # pyright: ignore[reportMissingImports]

# .env dosyasını yükle
load_dotenv()

# Token'ı .env'den al
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')  # Chat ID'yi .env'den al

# Log ayarları
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start komutuna yanıt verir ve Chat ID'yi gösterir"""
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # Terminale Chat ID'yi yazdır
    print(f"CHAT ID BULUNDU: {chat_id}")
    print(f"Kullanıcı: {user.first_name} {user.last_name or ''} (@{user.username or 'yok'})")
    
    await update.message.reply_html(
        f"Merhaba {user.mention_html()}!\n\nChat ID'n: <code>{chat_id}</code>\n\n"
        "Bu ID'yi .env dosyasına CHAT_ID olarak kaydet."
    )

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test mesajı gönderir"""
    if not CHAT_ID:
        await update.message.reply_text("❌ CHAT_ID bulunamadı. Lütfen .env dosyasını kontrol edin.")
        return
        
    try:
        # Kayıtlı CHAT_ID'ye test mesajı gönder
        await context.bot.send_message(
            chat_id=CHAT_ID, 
            text="✅ Bot test mesajı gönderiyor!\n\nBu mesaj başarıyla iletildi."
        )
        await update.message.reply_text("✅ Test mesajı başarıyla gönderildi!")
    except Exception as e:
        await update.message.reply_text(f"❌ Mesaj gönderilemedi: {e}")

def main():
    if not BOT_TOKEN:
        print("HATA: BOT_TOKEN bulunamadı. Lütfen .env dosyasını kontrol edin.")
        return

    application = Application.builder().token(BOT_TOKEN).build()
    
    # Komut handler'ları
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", test_command))
    
    print("Bot çalışıyor... Komutlar:")
    print("/start - Chat ID öğrenmek için")
    print("/test - Test mesajı göndermek için")
    
    application.run_polling()

if __name__ == '__main__':
    main()