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
    return f"✅ Storico ripristinato: {imported_weeks} settimane (passate) caricate."

# --- COMANDI TELEGRAM ---
async def import_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Svuoto e ricarico lo storico...")
    # Eseguiamo un reset pulito per evitare duplicati
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM war_history WHERE date LIKE 'W%' AND date NOT LIKE 'Week-%'")
    conn.commit()
    conn.close()
    
    # Chiama la logica pura
    result = sync_history_logic()
    await update.message.reply_text(result)

async def storia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clan_data = make_api_request("") # Chiede la lista membri attuale
    if not clan_data:
        await update.message.reply_text("❌ Errore API: impossibile recuperare i membri attuali.")
        return
    
    # Crea un set di tag dei membri attuali per un lookup veloce O(1)
    current_members_tags = {m['tag'] for m in clan_data.get('memberList', [])}
    
    conn = get_connection()
    c = conn.cursor()
    # QUERY CORRETTA: Somma solo le settimane storiche (W...) ESCLUDENDO la corrente (Week...)
    query = """
        SELECT p.tag, p.name, p.status, 
               SUM(w.decks_used), SUM(w.decks_possible), SUM(w.fame), COUNT(w.id)
        FROM players p
        JOIN war_history w ON p.tag = w.player_tag
        WHERE w.date LIKE 'W%' AND w.date NOT LIKE 'Week-%'
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
        
        # FILTRO FONDAMENTALE: Salta chi non è attualmente nel clan
        if tag not in current_members_tags: continue

        icon = {0: "⚪️", 1: "🟢", 2: "🔴", 3: "⚫️"}.get(status, "⚪️")
        
        # Calcolo % Partecipazione (opzionale ma utile)
        percent = (used / possible * 100) if possible > 0 else 0
        
        fame_str = f"{fame/1000:.1f}k" if fame >= 1000 else str(fame)
        new_mark = "🆕" if weeks < 2 else "" # Se ha meno di 2 settimane registrate è nuovo
        
        safe_name = html.escape(name[:8])
        
        # Formattazione allineata: Icona | Nome | Mazzi | Fama
        line = f"{icon}| <code>{safe_name:<8} {new_mark}|{used:>3}/{possible:<3}|{fame_str:>5}</code>\n"
        
        if len(msg) + len(line) > 3900:
            await update.message.reply_text(msg, parse_mode='HTML')
            msg = "📊 <b>STORICO (Cont.)</b>\n"
            msg += "<code>St| Nome     | Tot    | Fama </code>\n"
            
        msg += line

    await update.message.reply_text(msg, parse_mode='HTML')

    await update.message.reply_text(msg, parse_mode='HTML')