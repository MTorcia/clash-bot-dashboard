import sqlite3
import html
from telegram import Update
from telegram.ext import ContextTypes
from database import get_connection, make_api_request, CLAN_TAG

# --- LOGICA PURA (Funziona senza utente) ---
def sync_history_logic():
    """Scarica lo storico e popola il DB. Ritorna un messaggio di stato."""
    log_data = make_api_request("riverracelog?limit=10")
    if not log_data or 'items' not in log_data:
        return "❌ Errore API: Impossibile scaricare lo storico."

    conn = get_connection()
    c = conn.cursor()
    imported_weeks = 0
    
    for race in log_data['items']:
        season_id = race.get('sectionIndex', 'S')
        raw_date = race.get('createdDate', '00000000')
        week_label = f"W{season_id}-{raw_date[:8]}"
        
        my_clan = None
        for standing in race.get('standings', []):
            if standing['clan']['tag'] == f"#{CLAN_TAG}":
                my_clan = standing['clan']
                break
        
        if not my_clan: continue
        imported_weeks += 1
        
        for p in my_clan.get('participants', []):
            tag, name = p['tag'], p['name']
            used, fame = p['decksUsed'], p['fame']
            
            c.execute("INSERT OR IGNORE INTO players (tag, name, status, admin_notes) VALUES (?, ?, 0, '')", (tag, name))
            c.execute("""INSERT OR REPLACE INTO war_history 
                         (date, player_tag, decks_used, decks_possible, fame) 
                         VALUES (?, ?, ?, ?, ?)""", (week_label, tag, used, 16, fame))

    conn.commit()
    conn.close()
    return f"✅ Storico ripristinato: {imported_weeks} settimane caricate."

# --- COMANDI TELEGRAM ---
async def import_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Scarico dati...")
    # Chiama la logica pura
    result = sync_history_logic()
    await update.message.reply_text(result)

async def storia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clan_data = make_api_request("")
    if not clan_data:
        await update.message.reply_text("❌ Errore membri attuali.")
        return
    current_tags = [m['tag'] for m in clan_data.get('memberList', [])]
    
    conn = get_connection()
    c = conn.cursor()
    query = """
        SELECT p.tag, p.name, p.status, 
               SUM(w.decks_used), SUM(w.decks_possible), SUM(w.fame), COUNT(w.id)
        FROM players p
        JOIN war_history w ON p.tag = w.player_tag
        WHERE w.date LIKE 'W%'
        GROUP BY p.tag
        ORDER BY SUM(w.decks_used) DESC
    """
    c.execute(query)
    rows = c.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("⚠️ Database vuoto. Attendi il ripristino automatico o usa /importa.")
        return

    msg = "📊 <b>STORICO ULTIME 10 SETTIMANE</b>\n"
    msg += "<code>St| Nome      | Att    | Punti </code>\n"
    msg += "<code>--|-----------|--------|-------</code>\n"

    for row in rows:
        tag, name, status, used, possible, fame, weeks = row
        if tag not in current_tags: continue

        icon = {0: "⚪️", 1: "🟢", 2: "🔴", 3: "⚫️"}.get(status, "⚪️")
        fame_str = f"{fame/1000:.1f}k" if fame >= 1000 else str(fame)
        new_mark = "*" if weeks < 10 else " "
        safe_name = html.escape(name[:9])
        
        line = f"{icon}| <code>{safe_name:<9}{new_mark}|{used:>3}/{possible:<3}|{fame_str:>6}</code>\n"
        
        if len(msg) + len(line) > 3900:
            await update.message.reply_text(msg, parse_mode='HTML'); msg = "📊 <b>STORICO (Cont.)</b>\n"
        msg += line

    await update.message.reply_text(msg, parse_mode='HTML')