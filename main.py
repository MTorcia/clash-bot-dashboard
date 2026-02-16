import logging
import sqlite3
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
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

    # IMPOSTA I SUGGERIMENTI DEI COMANDI
    commands = [
        BotCommand("scan", "🔄 Aggiorna i dati della War corrente"),
        BotCommand("waroggi", "⚔️ Report attacchi di oggi"),
        BotCommand("war", "🏆 Andamento generale della settimana"),
        BotCommand("storia", "📜 Storico ultime 10 settimane"),
        BotCommand("dashboard", "📱 Apri il gestionale web"),
        BotCommand("status", "🚦 Imposta status (0-3)"),
        BotCommand("nota", "📝 Aggiungi nota giocatore"),
        BotCommand("importa", "📥 Riscarica lo storico dall'API")
    ]
    await bot_app.bot.set_my_commands(commands)

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
    # RECUPERIAMO SOLO I GIOCATORI CHE SONO ATTUALMENTE NEL CLAN?
    # No, il DB potrebbe avere ex membri. 
    # Dobbiamo fare una verifica live o assumere che nel DB ci siano tutti ma filtrare chi non ha stats recenti?
    # L'utente ha chiesto "SOLO i player attivi adesso nel clan".
    # Quindi dobbiamo scaricare la lista membri dal API e filtrare.
    
    from database import make_api_request
    clan_data = make_api_request("")
    active_tags = set()
    if clan_data and 'memberList' in clan_data:
        for m in clan_data['memberList']:
            active_tags.add(m['tag'])
            
    c.execute("SELECT tag, name, status, admin_notes FROM players")
    # Creiamo un dizionario per accesso rapido
    players = {}
    for r in c.fetchall():
        tag = r[0]
        # FILTRO ATTVI: Se non è nella lista API, lo ignoriamo dalla dashboard
        if tag not in active_tags: continue
        
        players[tag] = {
            "tag": tag,
            "name": r[1],
            "status": r[2],
            "note": r[3] or "", # Se None, diventa stringa vuota
            "cur_decks": 0,
            "cur_fame": 0,
            "hist_decks": 0,
            "hist_possible": 0,
            "hist_fame": 0
        }
    
    # 2. Dati War Attuale (Week- e SOLO per i player attivi)
    # Calcolo ID Settimana Corrente
    import datetime
    today = datetime.date.today()
    current_monday = today - datetime.timedelta(days=today.weekday())
    current_week_id = f"Week-{current_monday.strftime('%Y%m%d')}"
    
    # Seleziona SOLO la settimana corrente, ignorando eventuali vecchie "Week-..." rimaste appese
    c.execute("SELECT player_tag, SUM(decks_used), SUM(fame) FROM war_history WHERE date = ? GROUP BY player_tag", (current_week_id,))
    for r in c.fetchall():
        tag, decks, fame = r
        if tag in players: # players contiene già solo gli attivi grazie al filtro sopra
            players[tag]["cur_decks"] = decks or 0
            players[tag]["cur_fame"] = fame or 0

    # 3. Dati Storico (W- e SOLO per i player attivi, NON Week-)
    c.execute("SELECT player_tag, SUM(decks_used), SUM(decks_possible), SUM(fame) FROM war_history WHERE date LIKE 'W%' AND date NOT LIKE 'Week-%' GROUP BY player_tag")
    for r in c.fetchall():
        tag, decks, possible, fame = r
        if tag in players: # players contiene già solo gli attivi
            players[tag]["hist_decks"] = decks or 0
            players[tag]["hist_possible"] = possible or 0
            players[tag]["hist_fame"] = fame or 0

    conn.close()
    # Ordina: Prima lo status (dal più alto), poi il nome
    return sorted(list(players.values()), key=lambda x: (x['status'], x['name']), reverse=True)

@app.post("/api/update")
async def update_player(data: PlayerUpdate):
    try:
        conn = get_connection()
        c = conn.cursor()
        
        # FIX: Assicura che il tag abbia il prefisso #
        tag_clean = data.tag.upper()
        if not tag_clean.startswith("#"):
            tag_clean = "#" + tag_clean
            
        # Usa una stringa vuota se la nota è None, per sicurezza
        safe_note = data.note if data.note is not None else ""
        c.execute("UPDATE players SET status = ?, admin_notes = ? WHERE tag = ?", (data.status, safe_note, tag_clean))
        conn.commit()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        print(f"❌ Errore aggiornamento: {e}")
        return {"status": "error", "message": str(e)}
