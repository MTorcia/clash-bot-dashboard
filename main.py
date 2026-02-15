import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from database import init_db, TG_TOKEN

# Importiamo i comandi corretti
from war_attuale import scan_command, waroggi_command, war_command, set_status, set_note
from war_passate import storia_command, import_history_command, sync_history_logic

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # App Render
    webapp_url = "https://clash-bot-dashboard.onrender.com" 
    
    keyboard = [
        [InlineKeyboardButton("📱 Apri Dashboard", web_app=WebAppInfo(url=webapp_url))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Clicca sotto per aprire la Dashboard:",
        reply_markup=reply_markup
    )

# Variabile globale per l'applicazione bot
bot_app = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot_app
    
    # 1. Avvio Database
    init_db()
    
    # 2. AUTO-RIPRISTINO DATI
    print("🔄 Avvio ripristino dati automatico...")
    try:
        report = sync_history_logic()
        print(f"REPORT AVVIO: {report}")
    except Exception as e:
        print(f"⚠️ Errore nel ripristino avvio: {e}")

    # 3. Configura Bot Telegram
    bot_app = ApplicationBuilder().token(TG_TOKEN).build()
    
    # Comandi War Attuale
    bot_app.add_handler(CommandHandler('scan', scan_command))
    bot_app.add_handler(CommandHandler('waroggi', waroggi_command))
    bot_app.add_handler(CommandHandler('war', war_command))
    bot_app.add_handler(CommandHandler('status', set_status))
    bot_app.add_handler(CommandHandler('nota', set_note))
    
    # Comandi War Passate
    bot_app.add_handler(CommandHandler('storia', storia_command))
    bot_app.add_handler(CommandHandler('importa', import_history_command))
    
    # Comandi Dashboard
    bot_app.add_handler(CommandHandler('dashboard', dashboard_command))
    
    # Avvio del bot
    await bot_app.initialize()
    await bot_app.start()
    
    # Per il polling in async context con FastAPI, usiamo updater.start_polling()
    # Attenzione: start_polling() è non-bloccante, avvia un task in background.
    await bot_app.updater.start_polling()
    
    print("🤖 Bot Modulare Avviato! Comandi: /scan, /waroggi, /war, /storia, /dashboard")
    
    yield
    
    # Shutdown
    if bot_app:
        print("🛑 Arresto bot...")
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()

# Creazione App FastAPI
app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serve la pagina HTML della dashboard"""
    return templates.TemplateResponse("index.html", {"request": request})

if __name__ == '__main__':
    import uvicorn
    # Se avviato direttamente, usa uvicorn per servire l'app (che avvierà il bot nel lifespan)
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)