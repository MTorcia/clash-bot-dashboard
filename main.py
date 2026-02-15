import logging
import sqlite3
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from database import init_db, get_connection, TG_TOKEN

# Import Comandi
from war_attuale import scan_command, waroggi_command, war_command, set_status, set_note
from war_passate import storia_command, import_history_command, sync_history_logic

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- MODELLO PER RICEVERE AGGIORNAMENTI ---
class PlayerUpdate(BaseModel):
    tag: str
    status: int
    note: str

# --- CICLO VITA ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Tenta il ripristino ma non blocca l'avvio se fallisce
    try:
        sync_history_logic()
    except Exception as e:
        print(f"⚠️ Warning ripristino dati: {e}")

    bot_app = ApplicationBuilder().token(TG_TOKEN).build()
    
    # Registra comandi
    bot_app.add_handler(CommandHandler('scan', scan_command))
    bot_app.add_handler(CommandHandler('waroggi', waroggi_command))
    bot_app.add_handler(CommandHandler('war', war_command))
    bot_app.add_handler(CommandHandler('status', set_status))
    bot_app.add_handler(CommandHandler('nota', set_note))
    bot_app.add_handler(CommandHandler('storia', storia_command))
    bot_app.add_handler(CommandHandler('importa', import_history_command))
    
    async def dashboard_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
        # NOTA: Sostituisci con il tuo URL Render reale
        webapp_url = "https://clash-bot-dashboard.onrender.com" 
        await update.message.reply_text(
            "👇 <b>Clicca per aprire la Dashboard:</b>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📱 Apri Gestionale", web_app=WebAppInfo(url=webapp_url))]]),
            parse_mode='HTML'
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

# Abilita CORS per sicurezza
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ROTTE WEB ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/data")
async def get_dashboard_data():
    conn = get_connection()
    c = conn.cursor()
    
    # 1. Recupera Anagrafica Base
    c.execute("SELECT tag, name, status, admin_notes FROM players")
    # Creiamo un dizionario per accesso rapido
    players = {}
    for r in c.fetchall():
        players[r[0]] = {
            "tag": r[0],
            "name": r[1],
            "status": r[2],
            "note": r[3] or "", # Se None, diventa stringa vuota
            "cur_decks": 0,
            "cur_fame": 0,
            "hist_decks": 0,
            "hist_possible": 0,
            "hist_fame": 0
        }
    
    # 2. Dati War Attuale (Date che iniziano con Week-)
    c.execute("SELECT player_tag, SUM(decks_used), SUM(fame) FROM war_history WHERE date LIKE 'Week-%' GROUP BY player_tag")
    for r in c.fetchall():
        tag, decks, fame = r
        if tag in players:
            players[tag]["cur_decks"] = decks or 0
            players[tag]["cur_fame"] = fame or 0

    # 3. Dati Storico (Date che iniziano con W ma NON sono la war corrente Week-)
    c.execute("SELECT player_tag, SUM(decks_used), SUM(decks_possible), SUM(fame) FROM war_history WHERE date LIKE 'W%' AND date NOT LIKE 'Week-%' GROUP BY player_tag")
    for r in c.fetchall():
        tag, decks, possible, fame = r
        if tag in players:
            players[tag]["hist_decks"] = decks or 0
            players[tag]["hist_possible"] = possible or 0
            players[tag]["hist_fame"] = fame or 0

    conn.close()
    # Restituisce una lista pulita ordinata per status (i rossi prima)
    return sorted(list(players.values()), key=lambda x: x['status'], reverse=True)

@app.post("/api/update")
async def update_player(data: PlayerUpdate):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE players SET status = ?, admin_notes = ? WHERE tag = ?", (data.status, data.note, data.tag))
    conn.commit()
    conn.close()
    return {"status": "ok"}
