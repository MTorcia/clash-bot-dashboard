import os
import sqlite3
import requests
from dotenv import load_dotenv

# Caricamento variabili d'ambiente dal file .env
load_dotenv()
TG_TOKEN = os.getenv('TELEGRAM_TOKEN')
CR_TOKEN = os.getenv('CR_API_TOKEN')
CLAN_TAG = os.getenv('CLAN_TAG')
DB_FILE = "clan_data.db"

def get_connection():
    """Ritorna una connessione attiva al database SQLite."""
    return sqlite3.connect(DB_FILE)

def init_db():
    """Inizializza il database e crea le tabelle se non esistono."""
    conn = get_connection()
    c = conn.cursor()
    
    # Tabella GIOCATORI: Gestisce anagrafica, bollini status e note admin
    c.execute('''CREATE TABLE IF NOT EXISTS players
                 (tag TEXT PRIMARY KEY, 
                  name TEXT, 
                  status INTEGER DEFAULT 0, 
                  admin_notes TEXT)''')
    
    # Tabella STORICO: Memorizza le performance giornaliere e delle war passate
    # Aggiunta la colonna 'fame' per il calcolo dei punti fama
    c.execute('''CREATE TABLE IF NOT EXISTS war_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  date TEXT, 
                  player_tag TEXT, 
                  decks_used INTEGER,
                  decks_possible INTEGER,
                  fame INTEGER)''')
    
    conn.commit()
    conn.close()
    print("✅ Database inizializzato correttamente (Supporto Fama attivo).")

def make_api_request(endpoint):
    """
    Helper universale per le chiamate all'API di Clash Royale.
    Gestisce il prefisso del tag clan e l'autenticazione.
    """
    # Se l'endpoint è vuoto, recupera le informazioni generali del clan
    url = f"https://proxy.royaleapi.dev/v1/clans/%23{CLAN_TAG}"
    if endpoint:
        url += f"/{endpoint}"
        
    headers = {
        "Authorization": f"Bearer {CR_TOKEN}",
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"⚠️ Errore API {response.status_code}: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Errore di connessione API: {e}")
        return None

# Esegue l'inizializzazione se il file viene lanciato direttamente
if __name__ == "__main__":
    init_db()