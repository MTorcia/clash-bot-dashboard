import datetime
import html
from telegram import Update
from telegram.ext import ContextTypes
from database import get_connection, make_api_request, CLAN_TAG

# --- LOGICA DI SCAN (Aggiorna DB per storico) ---
async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 **Analisi e Salvataggio Dati War...**")
    
    # 1. Recupero dati War Corrente
    war_data = make_api_request("currentriverrace")
    # 2. Recupero tutti i membri (anche quelli che non hanno fatto war)
    members_data = make_api_request("") 
    
    if not war_data or not members_data:
        await update.message.reply_text("❌ Errore API: Impossibile scaricare i dati.")
        return

    all_members = members_data.get('memberList', [])

    # Usiamo la data di creazione della war come ID univoco della settimana (es. 20240215)
    # Se la war è in 'training' o simile, createdDate potrebbe mancare, usiamo data odierna.
    raw_date = war_data.get('createdDate')
    if not raw_date:
        # Fallback: usiamo la data ISO della settimana corrente
        today = datetime.date.today()
        # Lunedì della settimana corrente
        monday = today - datetime.timedelta(days=today.weekday())
        week_id = f"Week-{monday.strftime('%Y%m%d')}"
    else:
        week_id = f"Week-{raw_date[:8]}"

    # Mappiamo i partecipanti attivi alla war
    participants = {p['tag']: p for p in war_data.get('clan', {}).get('participants', [])}
    
    # Determiniamo il giorno corrente anche per il DB
    period_logs = war_data.get('clan', {}).get('periodLogs', [])
    
    # FIX: Calcolo robusto del giorno. Se periodLogs è vuoto (es. errore API) usiamo i mazzi usati.
    max_decks = max([p.get('decksUsed', 0) for p in participants.values()]) if participants else 0
    implied_day = (max_decks + 3) // 4
    if implied_day < 1: implied_day = 1
    
    days_completed = len(period_logs)
    current_day = max(days_completed + 1, implied_day)
    
    if current_day > 4: current_day = 4
    
    decks_possible = current_day * 4
        
    conn = get_connection()
    c = conn.cursor()
    
    count_updated = 0
    count_new = 0
    
    for m in all_members:
        tag = m['tag']
        name = m['name']
        
        # Aggiorniamo anagrafica giocatori (Status e Note rimangono invariati se esistono)
        c.execute("INSERT OR IGNORE INTO players (tag, name, status, admin_notes) VALUES (?, ?, 0, '')", (tag, name))
        
        # Recuperiamo i dati della war per questo giocatore (se ha partecipato)
        p_data = participants.get(tag)
        
        if p_data:
            decks_used = p_data.get('decksUsed', 0)
            fame = p_data.get('fame', 0)
        else:
            decks_used = 0
            fame = 0
            
        decks_possible = 16 # VECCHIO
        decks_possible = current_day * 4 # NUOVO: Target dinamico "fino ad ora"
        
        # CERCHIAMO SE ESISTE GIÀ UN RECORD PER QUESTA SETTIMANA E QUESTO GIOCATORE
        c.execute("SELECT id FROM war_history WHERE date = ? AND player_tag = ?", (week_id, tag))
        row = c.fetchone()
        
        if row:
            # RECORD ESISTENTE: Aggiorniamo con i dati più recenti (es. ha fatto un altro mazzo oggi)
            c.execute('''UPDATE war_history 
                         SET decks_used=?, fame=?, decks_possible=? 
                         WHERE id=?''', (decks_used, fame, decks_possible, row[0]))
            count_updated += 1
        else:
            # NUOVO RECORD: Inseriamo la riga
            c.execute('''INSERT INTO war_history (date, player_tag, decks_used, decks_possible, fame) 
                         VALUES (?, ?, ?, ?, ?)''', (week_id, tag, decks_used, decks_possible, fame))
            count_new += 1
            
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ **Database Aggiornato!**\nSettimana: `{week_id}`\nNuovi record: {count_new}\nAggiornati: {count_updated}", parse_mode='Markdown')


# --- COMANDO /WAROGGI (Attacchi del Giorno) ---
async def waroggi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    war_data = make_api_request("currentriverrace")
    if not war_data:
        await update.message.reply_text("❌ Errore API.")
        return

    state = war_data.get('state', '')
    if state == 'matchmaking':
        await update.message.reply_text("🛡 **Siamo nei giorni di Training.**\nNessun attacco fiume disponibile oggi.")
        return

    # calcolo del giorno
    period_logs = war_data.get('clan', {}).get('periodLogs', [])
    days_completed = len(period_logs)
    current_day = days_completed + 1
    
    if current_day > 4: 
        # Potrebbe essere colosseum week o fine data
        await update.message.reply_text("🏁 **Giorni di battaglia conclusi.**")
        # Ma mostriamo comunque i dati se serve
        
    clan = war_data.get('clan', {})
    participants = {p['tag']: p for p in clan.get('participants', [])}
    
    # Mappa dei mazzi usati nei giorni PRECEDENTI per ogni giocatore
    past_decks_map = {}
    
    for log in period_logs:
        log_participants = log.get('participants', [])
        for p in log_participants:
            tag = p['tag']
            decks = p['decksUsed']
            past_decks_map[tag] = past_decks_map.get(tag, 0) + decks
            
    # Recuperiamo anche lo status e i nomi dal DB per visualizzazione carina
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT tag, name, status FROM players")
    db_players = {r[0]: {'name': r[1], 'status': r[2]} for r in c.fetchall()}
    conn.close()
    
    status_icon = {0: "⚪️", 1: "🟢", 2: "🔴", 3: "⚫️"}
    
    # Costruzione Lista Risultati
    report_list = []
    
    # Fetch membri attuali
    clan_info = make_api_request("")
    all_current_members = clan_info.get('memberList', []) if clan_info else []
    
    for m in all_current_members:
        tag = m['tag']
        name = m['name']
        
        # Dati totali ad ora
        p_total = participants.get(tag)
        total_used = p_total.get('decksUsed', 0) if p_total else 0
        
        # Dati passati
        past_used = past_decks_map.get(tag, 0)
        
        # Dati OGGI = Totale Attuale - Totale Passato
        today_used = total_used - past_used
        
        if today_used < 0: today_used = 0
        if today_used > 4: today_used = 4 # Cap a 4 visivo
        
        # Status
        db_p = db_players.get(tag, {})
        status = db_p.get('status', 0) # Default neutro
        icon = status_icon.get(status, "⚪️")
        
        report_list.append({
            'name': name,
            'today': today_used,
            'icon': icon
        })
        
    # Ordiniamo: Prima chi ha fatto MENO attacchi oggi
    report_list.sort(key=lambda x: x['today'])
    
    msg = f"⚔️ <b>WAR: GIORNO {current_day}</b> (Oggi)\n"
    msg += "<code>St| Nome      | Oggi </code>\n"
    msg += "<code>--|-----------|------</code>\n"
    
    for r in report_list:
        safe_name = html.escape(r['name'][:9])
        
        line = f"{r['icon']}| <code>{safe_name:<9} | {r['today']}/4 </code>\n"
        
        if len(msg) + len(line) > 4000:
            await update.message.reply_text(msg, parse_mode='HTML')
            msg = "⚔️ <b>GIORNO CORRENTE (Cont.)</b>\n"
            msg += "<code>St| Nome      | Oggi </code>\n"
            
        msg += line
        
    await update.message.reply_text(msg, parse_mode='HTML')


# --- COMANDO /WAR (Andamento Globale Settimana) ---
async def war_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    war_data = make_api_request("currentriverrace")
    if not war_data:
        await update.message.reply_text("❌ Errore API.")
        return
        
    # Calcolo target dinamico
    period_logs = war_data.get('clan', {}).get('periodLogs', [])
    
    # FIX: Logica per individuare il giorno corretto se periodLogs è incompleto
    # Prendiamo il MAX mazzi usati da un singolo player per capire a che punto siamo
    participants_check = {p['tag']: p for p in war_data.get('clan', {}).get('participants', [])}
    max_decks = max([p.get('decksUsed', 0) for p in participants_check.values()]) if participants_check else 0
    
    implied_day = (max_decks + 3) // 4
    if implied_day < 1: implied_day = 1
    
    days_completed = len(period_logs)
    
    # Il giorno attuale è il massimo tra quello calcolato dai logs e quello dedotto dai mazzi
    current_day = max(days_completed + 1, implied_day)
    
    if current_day > 4: current_day = 4
    week_target = current_day * 4
    
    # Recuperiamo anche lo status e i nomi dal DB
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT tag, name, status FROM players")
    db_players = {r[0]: {'name': r[1], 'status': r[2]} for r in c.fetchall()}
    conn.close()
    
    status_icon = {0: "⚪️", 1: "🟢", 2: "🔴", 3: "⚫️"}
    
    clan = war_data.get('clan', {})
    participants = {p['tag']: p for p in clan.get('participants', [])}
    
    # Fetch membri attuali
    clan_info = make_api_request("")
    all_current_members = clan_info.get('memberList', []) if clan_info else []
    
    report_list = []
    
    for m in all_current_members:
        tag = m['tag']
        
        # Filtro: Se il giocatore non è più nel clan (caso strano, ma possibile per cache API) passiamo oltre
        # Ma qui stiamo iterando SUGLI ATTUALI, quindi sono sicuramente dentro.
        
        name = m['name']
        
        p = participants.get(tag)
        if p:
            decks = p.get('decksUsed', 0)
            fame = p.get('fame', 0)
        else:
            decks = 0
            fame = 0
            
        db_p = db_players.get(tag, {})
        status = db_p.get('status', 0)
        icon = status_icon.get(status, "⚪️")
        
        report_list.append({
            'name': name,
            'decks': decks,
            'fame': fame,
            'icon': icon
        })
        
    # Ordiniamo per mazzi totali usati decrescente
    report_list.sort(key=lambda x: x['decks'], reverse=True)
    
    msg = f"🏆 <b>ANDAMENTO SETTIMANALE</b>\n"
    msg += "<code>St| Nome      | Tot  | Punti </code>\n"
    msg += "<code>--|-----------|------|-------</code>\n"
    
    for r in report_list:
        safe_name = html.escape(r['name'][:9])
        fame_k = f"{r['fame']/1000:.1f}k" if r['fame'] >= 1000 else str(r['fame'])
        
        # Mostriamo il totale su TARGET DINAMICO (es. 4/4 se G1, 8/8 se G2)
        line = f"{r['icon']}| <code>{safe_name:<9} | {r['decks']:>2}/{week_target:<2} | {fame_k:>5} </code>\n"
        
        if len(msg) + len(line) > 4000:
            await update.message.reply_text(msg, parse_mode='HTML')
            msg = "🏆 <b>ANDAMENTO (Cont.)</b>\n"
            msg += "<code>St| Nome      | Tot  | Punti </code>\n"
            
        msg += line
        
    await update.message.reply_text(msg, parse_mode='HTML')


# --- UTILITIES ---
async def set_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /status #TAG [0-3]\n0=⚪️, 1=🟢, 2=🔴, 3=⚫️")
        return
    tag_input = context.args[0].upper()
    if not tag_input.startswith("#"):
        tag_input = "#" + tag_input
        
    try:
        new_status = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Lo status deve essere un numero (0-3).")
        return

    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("UPDATE players SET status = ? WHERE tag = ?", (new_status, tag_input))
        rows = c.rowcount
        conn.commit()
        conn.close()
        
        if rows > 0:
            await update.message.reply_text(f"✅ Status aggiornato per {tag_input} a {new_status}")
        else:
            await update.message.reply_text(f"⚠️ Tag {tag_input} non trovato nel database.\nAssicurati che il giocatore sia stato scansionato.")
    except Exception as e:
        await update.message.reply_text(f"❌ Errore DB: {e}")

async def set_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /nota #TAG testo")
        return
    
    tag_input = context.args[0].upper()
    if not tag_input.startswith("#"):
        tag_input = "#" + tag_input
        
    note = " ".join(context.args[1:])
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("UPDATE players SET admin_notes = ? WHERE tag = ?", (note, tag_input))
        rows = c.rowcount
        conn.commit()
        conn.close()
        
        if rows > 0:
            await update.message.reply_text(f"✅ Nota salvata per {tag_input}")
        else:
            await update.message.reply_text(f"⚠️ Tag {tag_input} non trovato nel database.")
    except Exception as e:
        await update.message.reply_text(f"❌ Errore DB: {e}")