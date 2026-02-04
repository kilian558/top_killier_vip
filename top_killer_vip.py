#!/usr/bin/env python3
"""
Top Killer VIP Bot für Hell Let Loose CRCON
Trackt Kills während eines Matches und vergibt den Top 3 Killern ohne VIP +24h VIP
"""

import os
import sys
import time
import signal
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Dict, List, Tuple
import requests
from dotenv import load_dotenv
import urllib3

# Lade Environment-Variablen
load_dotenv()

# Konfiguration Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger('TopKillerVIP')

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Environment-Variablen
API_TOKEN = os.getenv("CRCON_API_TOKEN")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

if not API_TOKEN:
    logger.error("FEHLER: CRCON_API_TOKEN nicht gesetzt!")
    sys.exit(1)

# Server-Konfiguration
servers = [
    {"name": "Server 1", "base_url": os.getenv("SERVER1_URL")},
    {"name": "Server 2", "base_url": os.getenv("SERVER2_URL")},
    {"name": "Server 3", "base_url": os.getenv("SERVER3_URL")},
]

# Entferne Server ohne URL
servers = [s for s in servers if s["base_url"]]

if not servers:
    logger.error("FEHLER: Keine Server-URLs konfiguriert!")
    sys.exit(1)

# Initialisiere Sessions für jeden Server
for server in servers:
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json"
    })
    session.verify = False
    server["session"] = session
    
    # Teste Verbindung
    try:
        response = session.get(f"{server['base_url']}/api/get_status", timeout=10)
        response.raise_for_status()
        data = response.json()
        server["name"] = data.get("result", {}).get("name") or server["name"]
        logger.info(f"✓ Verbunden mit: {server['name']}")
    except Exception as e:
        logger.error(f"✗ Verbindung zu {server['name']} fehlgeschlagen: {e}")
        sys.exit(1)

# Server States
server_states = {
    server["base_url"]: {
        "last_max_id": 0,
        "seen_log_ids": set(),
        "current_match_id": None,
        "match_kills": defaultdict(lambda: {"name": "", "kills": 0}),
        "match_start": None,
        "match_rewarded": False
    }
    for server in servers
}

# Graceful Shutdown Handler
shutdown_requested = False

def signal_handler(sig, frame):
    global shutdown_requested
    logger.info(f"\n[SHUTDOWN] Signal {sig} empfangen - Bot wird beendet...")
    shutdown_requested = True

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def get_historical_logs(server, limit=500) -> List[Dict]:
    """Hole historische Logs vom Server"""
    try:
        payload = {"limit": limit}
        response = server["session"].post(
            f"{server['base_url']}/api/get_historical_logs",
            json=payload,
            timeout=15
        )
        response.raise_for_status()
        return response.json().get("result", [])
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Logs von {server['name']}: {e}")
        return []


def get_current_map(server) -> Tuple[str, str]:
    """Hole aktuelle Map und Match-ID"""
    try:
        response = server["session"].get(
            f"{server['base_url']}/api/get_map",
            timeout=10
        )
        response.raise_for_status()
        result = response.json()
        
        # Versuche result zu extrahieren
        data = result.get("result", result)
        
        # Map-Name aus verschiedenen möglichen Feldern extrahieren
        current_map = None
        
        # Probiere verschiedene Felder
        if isinstance(data, dict):
            current_map = (
                data.get("id") or 
                data.get("map") or 
                data.get("name") or
                data.get("map_name") or
                data.get("layer") or
                data.get("layer_name")
            )
        elif isinstance(data, str):
            current_map = data
        
        if not current_map or current_map == "Unknown":
            logger.warning(f"[{server['name']}] Konnte Map nicht extrahieren.")
            current_map = "Unknown"
        
        # Verwende Map-Name als Match-ID
        match_id = current_map
        
        return current_map, match_id
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Map von {server['name']}: {e}")
        return "Unknown", None


def get_vip_ids(server) -> set:
    """Hole alle Spieler-IDs mit VIP"""
    try:
        response = server["session"].get(
            f"{server['base_url']}/api/get_vip_ids",
            timeout=10
        )
        response.raise_for_status()
        vips = response.json().get("result", [])
        return {vip.get("player_id") for vip in vips if vip.get("player_id")}
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der VIP-Liste von {server['name']}: {e}")
        return set()


def add_vip_hours(server, steam_id: str, player_name: str, hours: int) -> bool:
    """Füge VIP mit angegebenen Stunden hinzu"""
    try:
        # Setze VIP-Ablauf auf jetzt + X Stunden
        expiration = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
        
        payload = {
            "player_id": steam_id,
            "expiration": expiration,
            "description": f"Top Killer Belohnung (+{hours}h)"
        }
        
        response = server["session"].post(
            f"{server['base_url']}/api/add_vip",
            json=payload,
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info(f"✓ VIP (+{hours}h) vergeben an {player_name} ({steam_id}) auf {server['name']}")
            return True
        else:
            logger.error(f"✗ VIP-Fehler für {player_name}: {response.status_code} - {response.text[:200]}")
            return False
            
    except Exception as e:
        logger.error(f"Fehler beim Vergeben von VIP für {player_name}: {e}")
        return False


def add_vip_24h(server, steam_id: str, player_name: str) -> bool:
    """Füge 24h VIP hinzu (Legacy-Funktion)"""
    return add_vip_hours(server, steam_id, player_name, 24)


def send_private_message(server, player_id: str, player_name: str, message: str):
    """Sende private Nachricht an Spieler"""
    try:
        payload = {"player_id": player_id, "message": message}
        response = server["session"].post(
            f"{server['base_url']}/api/message_player",
            json=payload,
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info(f"✓ PM gesendet an {player_name} auf {server['name']}")
        else:
            logger.warning(f"PM-Fehler für {player_name}: {response.status_code}")
            
    except Exception as e:
        logger.error(f"Fehler beim Senden der PM an {player_name}: {e}")


def send_discord_log(message: str):
    """Sende Log-Nachricht an Discord Webhook"""
    if not DISCORD_WEBHOOK_URL:
        return
    
    try:
        payload = {
            "content": message,
            "username": "Top Killer VIP Bot"
        }
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        logger.warning(f"Discord-Webhook-Fehler: {e}")


def process_match_end(server, state: Dict):
    """Verarbeite Match-Ende und vergebe VIP an Top 5"""
    if state["match_rewarded"]:
        return
    
    match_kills = state["match_kills"]
    
    if not match_kills:
        logger.info(f"[{server['name']}] Keine Kills im Match aufgezeichnet.")
        return
    
    # Sortiere nach Kills (absteigend)
    sorted_killers = sorted(
        match_kills.items(),
        key=lambda x: x[1]["kills"],
        reverse=True
    )
    
    # Hole VIP-Liste
    vip_ids = get_vip_ids(server)
    
    # Filtere Top 5 ohne VIP
    top_killers_no_vip = [
        (steam_id, data) for steam_id, data in sorted_killers
        if steam_id not in vip_ids
    ][:5]
    
    if not top_killers_no_vip:
        logger.info(f"[{server['name']}] Alle Top-Killer haben bereits VIP.")
        state["match_rewarded"] = True
        return
    
    # Erstelle Discord-Log
    current_map, _ = get_current_map(server)
    discord_msg = f"**🏆 Match beendet auf {server['name']}**\n"
    discord_msg += f"Map: {current_map}\n\n"
    discord_msg += "**Top 5 Killer ohne VIP erhalten VIP-Belohnungen:**\n"
    discord_msg += "🥇 Platz 1: +72 Stunden | 🥈 Platz 2: +48 Stunden | 🥉 Platz 3-5: +24 Stunden\n\n"
    
    # VIP-Zeiten je nach Platzierung
    vip_hours = {1: 72, 2: 48, 3: 24, 4: 24, 5: 24}
    
    # Vergebe VIP an Top 5 ohne VIP
    for rank, (steam_id, data) in enumerate(top_killers_no_vip, 1):
        player_name = data["name"]
        kills = data["kills"]
        hours = vip_hours[rank]
        
        # Vergebe VIP mit entsprechender Stundenzahl
        success = add_vip_hours(server, steam_id, player_name, hours)
        
        # VORERST KEINE PM SENDEN
        # pm_message = (
        #     f"🏆 GLÜCKWUNSCH! 🏆\n"
        #     f"Du warst Platz {rank} der Top Killer ({kills} Kills) in diesem Match!\n"
        #     f"Als Belohnung erhältst du +{hours} Stunden VIP!"
        # )
        # send_private_message(server, steam_id, player_name, pm_message)
        
        # Detailliertes Logging
        rank_emoji = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣"}
        status = "✓" if success else "✗"
        
        logger.info(f"[{server['name']}] {status} Platz {rank}: {player_name} ({steam_id}) - {kills} Kills - +{hours}h VIP")
        
        # Füge zu Discord-Log hinzu
        discord_msg += f"{status} {rank_emoji.get(rank, f'#{rank}')} **{player_name}** - {kills} Kills → +{hours}h VIP\n"
    
    # Zeige alle Top 10 zur Info
    discord_msg += "\n**Top 10 Gesamt:**\n"
    for rank, (steam_id, data) in enumerate(sorted_killers[:10], 1):
        has_vip = "👑" if steam_id in vip_ids else ""
        discord_msg += f"{rank}. {data['name']} - {data['kills']} Kills {has_vip}\n"
    
    send_discord_log(discord_msg)
    logger.info(f"[{server['name']}] ✓ VIP an Top 5 Killer vergeben (72h/48h/24h/24h/24h)")
    
    state["match_rewarded"] = True


def process_server(server):
    """Verarbeite Logs für einen Server"""
    state = server_states[server["base_url"]]
    
    # Hole aktuelle Map/Match
    current_map, match_id = get_current_map(server)
    
    if match_id and match_id != state["current_match_id"]:
        # Neues Match erkannt
        if state["current_match_id"]:
            logger.info(f"[{server['name']}] Match-Ende erkannt: {state['current_match_id']}")
            # Verarbeite vorheriges Match
            process_match_end(server, state)
        
        # Reset für neues Match
        logger.info(f"[{server['name']}] Neues Match gestartet: {match_id}")
        state["current_match_id"] = match_id
        state["match_kills"] = defaultdict(lambda: {"name": "", "kills": 0})
        state["match_start"] = datetime.now()
        state["match_rewarded"] = False
        
        send_discord_log(f"🎮 **Neues Match gestartet auf {server['name']}**\nMap: {current_map}")
    
    # Hole Logs
    logs = get_historical_logs(server)
    if not logs:
        return
    
    # Filtere neue Logs
    new_logs = [log for log in logs if log.get("id", 0) > state["last_max_id"]]
    
    if new_logs:
        state["last_max_id"] = max(log.get("id", 0) for log in logs)
    
    # Verarbeite neue Logs
    for log in reversed(new_logs):
        log_id = log.get("id")
        if log_id in state["seen_log_ids"]:
            continue
        state["seen_log_ids"].add(log_id)
        
        log_type = log.get("type", "").upper()
        
        # Nur reguläre Kills zählen (keine Teamkills)
        if "KILL" in log_type and "TEAM KILL" not in log_type:
            killer_id = log.get("player1_id")
            killer_name = log.get("player1_name") or "Unknown"
            
            if killer_id:
                state["match_kills"][killer_id]["name"] = killer_name
                state["match_kills"][killer_id]["kills"] += 1
    
    # Cleanup alte IDs
    if len(state["seen_log_ids"]) > 3000:
        state["seen_log_ids"] = set(list(state["seen_log_ids"])[-1500:])


def main():
    """Hauptschleife"""
    logger.info("\n" + "="*60)
    logger.info("🎯 TOP KILLER VIP BOT GESTARTET")
    logger.info("="*60)
    logger.info(f"Überwachte Server: {len(servers)}")
    for server in servers:
        logger.info(f"  - {server['name']}")
    logger.info("="*60 + "\n")
    
    send_discord_log("🤖 **Top Killer VIP Bot gestartet**\n" + 
                     f"Überwacht {len(servers)} Server")
    
    loop_count = 0
    
    while not shutdown_requested:
        try:
            loop_count += 1
            
            # Verarbeite jeden Server
            for server in servers:
                process_server(server)
            
            # Status-Log alle 60 Loops (~5 Minuten)
            if loop_count % 60 == 0:
                logger.info(f"[STATUS] Bot läuft ({loop_count} Loops)")
            
            # Warte 5 Sekunden
            time.sleep(5)
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Fehler in Hauptschleife: {e}", exc_info=True)
            time.sleep(10)
    
    logger.info("\n[SHUTDOWN] Bot beendet")
    send_discord_log("🛑 **Top Killer VIP Bot gestoppt**")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Fataler Fehler: {e}", exc_info=True)
        send_discord_log(f"❌ **Bot Fehler:** {str(e)}")
        sys.exit(1)
