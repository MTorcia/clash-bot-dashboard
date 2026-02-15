import logging
import sqlite3
import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Body
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from database import init_db, get_connection, TG_TOKEN, make_api_request

# Import Comandi
from war_attuale import scan_command, waroggi_command, war_command, set_status, set_note
from war_passate import storia_command, import_history_command, sync_history_logic

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- MODELLI DATI ---
class PlayerUpdate(BaseModel):
    tag: str
    status: int
    note: str

# --- CICLO VITA ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print("🔄 Avvio ripristino dati automatico...")
    try:
        sync_history_logic()
    except Exception as e:
        print(f"⚠️ Errore ripristino: {e}")

    bot_app = ApplicationBuilder().token(TG_TOKEN).build()
    
    # Handler Comandi
    bot_app.add_handler(CommandHandler('scan', scan_command))
    bot_app.add_handler(CommandHandler('waroggi', waroggi_command))
    bot_app.add_handler(CommandHandler('war', war_command))
    bot_app.add_handler(CommandHandler('status', set_status))
    bot_app.add_handler(CommandHandler('nota', set_note))
    bot_app.add_handler(CommandHandler('storia', storia_command))
    bot_app.add_handler(CommandHandler('importa', import_history_command))
    
    async def dashboard_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
        # INSERISCI QUI IL TUO LINK RENDER REALE
        webapp_url = "https://clash-bot-dashboard.onrender.com" 
        await update.message.reply_text(
            "Clicca sotto per gestire il clan:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📱 Apri Dashboard", web_app=WebAppInfo(url=webapp_url))]])
        )
    bot_app.add_handler(CommandHandler('dashboard', dashboard_btn))

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()
    yield
    await bot_app.updater.stop()
    await bot_app.stop()
    await bot_app.shutdown()

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

# --- ROTTE WEB ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/data")
async def get_dashboard_data():
    """Restituisce TUTTI i dati per le due tab"""
    conn = get_connection()
    c = conn.cursor()
    
    # 1. Recupera anagrafica (Status e Note)
    c.execute("SELECT tag, name, status, admin_notes FROM players")
    players = {r[0]: {'tag': r[0], 'name': r[1], 'status': r[2], 'note': r[3], 'current': {}, 'history': {}} for r in c.fetchall()}
    
    # 2. Recupera dati WAR ATTUALE (Date che NON iniziano con 'W')
    # Nota: Assumiamo che i dati giornalieri siano salvati come Week-YYYYMMDD
    c.execute("""SELECT player_tag, SUM(decks_used), SUM(fame) 
                 FROM war_history WHERE date LIKE 'Week-%' GROUP BY player_tag""")
    for r in c.fetchall():
        if r[0] in players:
            players[r[0]]['current'] = {'decks': r[1], 'fame': r[2]}

    # 3. Recupera dati STORICO (Date che iniziano con 'W')
    c.execute("""SELECT player_tag, SUM(decks_used), SUM(decks_possible), SUM(fame) 
                 FROM war_history WHERE date LIKE 'W%' GROUP BY player_tag""")
    for r in c.fetchall():
        if r[0] in players:
            players[r[0]]['history'] = {'decks': r[1], 'possible': r[2], 'fame': r[3]}

    conn.close()
    
    # Filtra: Restituisci solo chi è nel clan ORA
    # (Per farlo bene servirebbe una chiamata API live, ma per velocità usiamo il DB)
    return list(players.values())

@app.post("/api/update")
async def update_player(data: PlayerUpdate):
    """Salva status e note"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE players SET status = ?, admin_notes = ? WHERE tag = ?", (data.status, data.note, data.tag))
    conn.commit()
    conn.close()
    return {"message": "Salvato"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)