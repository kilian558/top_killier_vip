#!/usr/bin/env python3
"""
Top Killer VIP Bot fÃ¼r Hell Let Loose CRCON mit Discord Bot Integration
Trackt Kills wÃ¤hrend eines Matches mit Live-Updates in Discord
"""

import os
import sys
import signal
import logging
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Dict, List, Tuple, Optional
import requests
from dotenv import load_dotenv
import urllib3
import discord
from discord.ext import tasks

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
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

if not API_TOKEN:
    logger.error("FEHLER: CRCON_API_TOKEN nicht gesetzt!")
    sys.exit(1)

if not DISCORD_BOT_TOKEN:
    logger.error("FEHLER: DISCORD_BOT_TOKEN nicht gesetzt!")
    sys.exit(1)

if not DISCORD_CHANNEL_ID:
    logger.error("FEHLER: DISCORD_CHANNEL_ID nicht gesetzt!")
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

# Initialisiere Sessions fÃ¼r jeden Server
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
        logger.info(f"âœ“ Verbunden mit: {server['name']}")
    except Exception as e:
        logger.error(f"âœ— Verbindung zu {server['name']} fehlgeschlagen: {e}")
        sys.exit(1)

# Server States
server_states = {
    server["base_url"]: {
        "current_match_id": None,
        "match_kills": defaultdict(lambda: {"name": "", "kills": 0}),
        "match_support": defaultdict(lambda: {"name": "", "support": 0}),
        "support_available": False,
        "baseline_kills": {},
        "kill_offsets": {},
        "match_start": None,
        "match_rewarded": False,
        "live_message": None,  # Discord Message fÃ¼r Live-Updates
        "live_message_id": None,
        "last_update": None,   # Timestamp des letzten Updates
        "inactive_since": None,
        "current_map": None,
        "support_debug_logged": False
    }
    for server in servers
}

# Discord Bot Setup
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

# Graceful Shutdown Handler
shutdown_requested = False
last_channel_warning = 0.0
last_state_write = 0.0
STATE_WRITE_MIN_SECONDS = 20
STATE_FILE = os.path.join("data", "state.json")
RESTART_HOUR = 4
RESTART_MINUTE = 30

last_restart_date = None

EMOJI_TARGET = "\U0001F3AF"
EMOJI_REFRESH = "\U0001F501"
EMOJI_TROPHY = "\U0001F3C6"
EMOJI_MEDAL_1 = "\U0001F947"
EMOJI_MEDAL_2 = "\U0001F948"
EMOJI_MEDAL_3 = "\U0001F949"
EMOJI_STAR = "\u25AB\ufe0f"
EMOJI_GIFT = "\U0001F381"
EMOJI_BAR_CHART = "\U0001F4CA"
EMOJI_VIP = "\U0001F451"
EMOJI_CHECK = "\u2713"
EMOJI_CROSS = "\u2717"

def signal_handler(sig, frame):
    global shutdown_requested
    logger.info(f"\n[SHUTDOWN] Signal {sig} empfangen - Bot wird beendet...")
    shutdown_requested = True

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def ensure_data_dir():
    data_dir = os.path.dirname(STATE_FILE)
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _serialize_datetime(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    return value.isoformat()


def load_state():
    global last_restart_date
    if not os.path.exists(STATE_FILE):
        return

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Fehler beim Laden von {STATE_FILE}: {e}")
        return

    last_restart_date = data.get("last_restart_date")

    server_data = data.get("servers", {})
    for server in servers:
        base_url = server["base_url"]
        saved = server_data.get(base_url)
        if not saved:
            continue

        state = server_states[base_url]
        state["current_match_id"] = saved.get("current_match_id")
        state["match_kills"] = defaultdict(lambda: {"name": "", "kills": 0}, saved.get("match_kills", {}))
        state["baseline_kills"] = saved.get("baseline_kills", {})
        state["kill_offsets"] = saved.get("kill_offsets", {})
        state["match_start"] = _parse_datetime(saved.get("match_start"))
        state["match_rewarded"] = saved.get("match_rewarded", False)
        state["live_message_id"] = saved.get("live_message_id")
        state["inactive_since"] = _parse_datetime(saved.get("inactive_since"))
        state["current_map"] = saved.get("current_map")

    logger.info("✓ State geladen")


def save_state(force: bool = False):
    global last_state_write
    now_ts = time.time()
    if not force and (now_ts - last_state_write) < STATE_WRITE_MIN_SECONDS:
        return

    ensure_data_dir()
    payload = {
        "last_restart_date": last_restart_date,
        "servers": {}
    }

    for server in servers:
        base_url = server["base_url"]
        state = server_states[base_url]
        payload["servers"][base_url] = {
            "current_match_id": state.get("current_match_id"),
            "match_kills": dict(state.get("match_kills", {})),
            "baseline_kills": state.get("baseline_kills", {}),
            "kill_offsets": state.get("kill_offsets", {}),
            "match_start": _serialize_datetime(state.get("match_start")),
            "match_rewarded": state.get("match_rewarded", False),
            "live_message_id": state.get("live_message_id"),
            "inactive_since": _serialize_datetime(state.get("inactive_since")),
            "current_map": state.get("current_map")
        }

    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=True, indent=2)
        last_state_write = now_ts
    except Exception as e:
        logger.error(f"Fehler beim Speichern von {STATE_FILE}: {e}")


def get_live_scoreboard(server):
    """Hole Live-Scoreboard fÃ¼r aktuell verbundene Spieler"""
    try:
        response = server["session"].get(
            f"{server['base_url']}/api/get_live_scoreboard",
            timeout=15
        )
        response.raise_for_status()
        result = response.json().get("result", [])
        # result kann Liste oder Dict sein
        return result
    except Exception as e:
        logger.error(f"Fehler beim Abrufen des Scoreboards von {server['name']}: {e}")
        return None


def get_players(server):
    """Hole Live-Players vom Server (enthÃ¤lt oft Support-Punkte)"""
    try:
        response = server["session"].get(
            f"{server['base_url']}/api/get_players",
            timeout=15
        )
        response.raise_for_status()
        return response.json().get("result", [])
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Players von {server['name']}: {e}")
        return None


def get_map_scoreboard(server):
    """Hole Match-Scoreboard (Map) vom Server"""
    try:
        response = server["session"].get(
            f"{server['base_url']}/api/get_map_scoreboard",
            timeout=15
        )
        response.raise_for_status()
        return response.json().get("result", [])
    except Exception as e:
        logger.error(f"Fehler beim Abrufen des Map-Scoreboards von {server['name']}: {e}")
        return None


def extract_scoreboard_players(scoreboard) -> List[Dict]:
    """Extrahiere Spieler-Liste aus unterschiedlichen Scoreboard-Formaten"""
    players: List[Dict] = []

    if isinstance(scoreboard, dict):
        # Team-Keys
        for team_key in ("allied", "axis", "team1", "team2"):
            team_players = scoreboard.get(team_key)
            if isinstance(team_players, list):
                players.extend([p for p in team_players if isinstance(p, dict)])

        # stats-Array
        if not players and isinstance(scoreboard.get("stats"), list):
            players = [p for p in scoreboard.get("stats", []) if isinstance(p, dict)]

        # players-Array
        if not players and isinstance(scoreboard.get("players"), list):
            players = [p for p in scoreboard.get("players", []) if isinstance(p, dict)]

        # Dict mit steam_id als Keys
        if not players:
            for steam_id, data in scoreboard.items():
                if isinstance(data, dict):
                    data["player_id"] = steam_id
                    players.append(data)
                elif isinstance(data, list):
                    players.extend([p for p in data if isinstance(p, dict)])

    elif isinstance(scoreboard, list):
        players = [p for p in scoreboard if isinstance(p, dict)]

    return players


def _extract_support_points(player: Dict) -> Optional[int]:
    """Support-Punkte aus Spieler-Objekt extrahieren (verschiedene mögliche Keys)."""
    for key in (
        "support", "support_points", "support_score", "score_support",
        "supportScore", "supportPoints", "supp"
    ):
        if key in player and player[key] is not None:
            try:
                if isinstance(player[key], dict):
                    for subkey in ("score", "value", "total", "points"):
                        if subkey in player[key] and player[key][subkey] is not None:
                            return int(player[key][subkey])
                    return None
                return int(player[key])
            except (ValueError, TypeError):
                return None

    score_block = player.get("score") or player.get("scores")
    if isinstance(score_block, dict):
        for key in ("support", "support_score", "support_points"):
            if key in score_block and score_block[key] is not None:
                try:
                    return int(score_block[key])
                except (ValueError, TypeError):
                    return None

    return None


def get_live_game_stats(server) -> Dict:
    """Hole Live-Game-Stats mit Timer und Score"""
    try:
        response = server["session"].get(
            f"{server['base_url']}/api/get_live_game_stats",
            timeout=10
        )
        response.raise_for_status()
        return response.json().get("result", {})
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Live-Stats von {server['name']}: {e}")
        return {}


def get_gamestate(server) -> Dict:
    """Hole aktuellen Gamestate (Fallback für Timer/Score)"""
    try:
        response = server["session"].get(
            f"{server['base_url']}/api/get_gamestate",
            timeout=10
        )
        response.raise_for_status()
        return response.json().get("result", {})
    except Exception as e:
        logger.error(f"Fehler beim Abrufen des Gamestates von {server['name']}: {e}")
        return {}


def get_current_map(server) -> Tuple[str, str]:
    """Hole aktuelle Map und Match-ID"""
    try:
        response = server["session"].get(
            f"{server['base_url']}/api/get_map",
            timeout=10
        )
        response.raise_for_status()
        result = response.json()
        
        data = result.get("result", result)
        
        current_map = None
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


def get_vip_expiration(server, steam_id: str) -> Optional[str]:
    """Hole VIP-Expiration fuer eine Spieler-ID."""
    try:
        response = server["session"].get(
            f"{server['base_url']}/api/get_vip_ids",
            timeout=10
        )
        response.raise_for_status()
        vips = response.json().get("result", [])
        for vip in vips:
            if vip.get("player_id") == steam_id:
                return vip.get("vip_expiration")
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der VIP-Daten von {server['name']}: {e}")
    return None


def is_lifetime_vip(expiration: Optional[str]) -> bool:
    if not expiration:
        return False
    exp = str(expiration).strip().lower()
    if exp.startswith(("permanent", "lifetime", "never")):
        return True
    if exp.startswith("3000-"):
        return True
    try:
        year = int(exp.split("-", 1)[0])
        return year >= 3000
    except (ValueError, IndexError):
        return False


def parse_vip_expiration(expiration: str) -> datetime:
    exp = expiration.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(exp)
    except ValueError:
        if "." in exp:
            exp = exp.split(".", 1)[0]
        try:
            return datetime.strptime(exp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.now(timezone.utc)


def add_vip_hours(server, steam_id: str, player_name: str, hours: int) -> bool:
    """FÃ¼ge VIP mit angegebenen Stunden hinzu"""
    try:
        current_exp = get_vip_expiration(server, steam_id)
        if is_lifetime_vip(current_exp):
            logger.info(
                f"[{server['name']}] Lifetime VIP erkannt fuer {player_name} ({steam_id}) - keine Aenderung."
            )
            return True

        if current_exp:
            remove_payload = {"player_id": steam_id}
            remove_response = server["session"].post(
                f"{server['base_url']}/api/remove_vip",
                json=remove_payload,
                timeout=10
            )
            if remove_response.status_code != 200:
                logger.warning(
                    f"[{server['name']}] Entfernen von VIP fehlgeschlagen fuer {player_name}: "
                    f"{remove_response.status_code} - {remove_response.text[:200]}"
                )

            base_time = parse_vip_expiration(current_exp)
        else:
            base_time = datetime.now(timezone.utc)

        expiration = (base_time + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
        
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
            logger.info(f"âœ“ VIP (+{hours}h) vergeben an {player_name} ({steam_id}) auf {server['name']}")
            return True
        else:
            logger.error(f"âœ— VIP-Fehler fÃ¼r {player_name}: {response.status_code} - {response.text[:200]}")
            return False
            
    except Exception as e:
        logger.error(f"Fehler beim Vergeben von VIP fÃ¼r {player_name}: {e}")
        return False


def send_private_message(server, player_id: str, player_name: str, message: str) -> bool:
    """Sende private Nachricht an Spieler"""
    try:
        payload = {
            "player_id": player_id,
            "message": message,
            "by": "Top Killer VIP Bot",
            "player_name": player_name
        }
        response = server["session"].post(
            f"{server['base_url']}/api/message_player",
            json=payload,
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info(f"✓ PM gesendet an {player_name} ({player_id}) auf {server['name']}")
            return True
        else:
            logger.warning(f"PM-Fehler für {player_name}: {response.status_code} - {response.text[:100]}")
            return False
            
    except Exception as e:
        logger.error(f"Fehler beim Senden der PM an {player_name}: {e}")
        return False


def create_live_embed(server, state: Dict, current_map: str) -> discord.Embed:
    """Erstelle Live-Update Embed"""
    match_kills = state["match_kills"]
    match_support = state.get("match_support", {})
    support_available = state.get("support_available", False)
    
    # Hole Live-Stats für Timer & Score
    live_stats = get_live_game_stats(server)
    timer_remaining = live_stats.get("time_remaining") or live_stats.get("remaining_time")
    allied_score = live_stats.get("allied_score", 0) or live_stats.get("allied", {}).get("score", 0)
    axis_score = live_stats.get("axis_score", 0) or live_stats.get("axis", {}).get("score", 0)
    
    # Fallback: gamestate (gibt andere Feldnamen zurück)
    if timer_remaining is None or (allied_score == 0 and axis_score == 0):
        gamestate = get_gamestate(server)
        if isinstance(gamestate, dict):
            # Debug: Zeige gamestate Struktur
            logger.info(f"[{server['name']}] Gamestate Keys: {list(gamestate.keys())}")
            
            # Timer aus gamestate
            if timer_remaining is None:
                # Versuche alle möglichen Timer-Felder
                timer_str = (
                    gamestate.get("remaining_time") or 
                    gamestate.get("time_remaining") or
                    gamestate.get("raw_time_remaining")
                )
                
                if timer_str:
                    logger.info(f"[{server['name']}] Timer String aus gamestate: '{timer_str}'")
                    try:
                        # Zuerst versuchen als Float (z.B. '4749.0' = Sekunden direkt)
                        timer_remaining = float(timer_str)
                        logger.info(f"[{server['name']}] Timer konvertiert: {timer_remaining}s")
                    except ValueError:
                        # Fallback: Format "0:11:51" oder "1:30:00" → Sekunden
                        try:
                            parts = str(timer_str).strip().split(":")
                            if len(parts) == 3:
                                timer_remaining = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                            elif len(parts) == 2:
                                timer_remaining = int(parts[0]) * 60 + int(parts[1])
                            logger.info(f"[{server['name']}] Timer konvertiert (HH:MM:SS): {timer_remaining}s")
                        except Exception as e:
                            logger.warning(f"[{server['name']}] Timer Parse Fehler: {e}")
            
            # Score aus gamestate
            if allied_score == 0 and axis_score == 0:
                allied_score = gamestate.get("allied_score", 0) or gamestate.get("score_allied", 0)
                axis_score = gamestate.get("axis_score", 0) or gamestate.get("score_axis", 0)
    
    # Debug: Zeige was wir bekommen haben
    logger.info(f"[{server['name']}] Live Stats für Embed: Timer={timer_remaining}, Score={allied_score}:{axis_score}, Live-Keys={list(live_stats.keys()) if live_stats else 'None'}")
    
    # Sortiere nach Kills
    sorted_killers = sorted(
        match_kills.items(),
        key=lambda x: x[1]["kills"],
        reverse=True
    )[:10]
    
    # Timer & Score formatieren
    timer_text = ""
    if timer_remaining is not None:
        minutes = int(timer_remaining // 60)
        seconds = int(timer_remaining % 60)
        timer_emoji = "🟢"
        if timer_remaining <= 80:
            timer_emoji = "🔴"  # Kritisch - Auswertung läuft!
        elif timer_remaining <= 90:
            timer_emoji = "🟡"  # Scoreboard-Phase
        timer_text = f"**{timer_emoji} Timer:** {minutes:02d}:{seconds:02d}\n"
    else:
        # Fallback: Zeige dass Timer nicht verfügbar ist
        timer_text = "**⏱️ Timer:** Lädt...\n"
    
    score_text = f"**📊 Score:** {allied_score}:{axis_score}\n" if allied_score > 0 or axis_score > 0 else "**📊 Score:** 0:0\n"
    
    # Embed erstellen
    match_info = f"**Map:** {current_map}\n{timer_text}{score_text}"
    if state['match_start']:
        match_info += f"**Match Start:** <t:{int(state['match_start'].timestamp())}:R>"
    
    # Farbe basierend auf Timer
    color = 0x00ff00  # Grün
    if timer_remaining is not None:
        if timer_remaining <= 80:
            color = 0xff0000  # Rot - Auswertung!
        elif timer_remaining <= 90:
            color = 0xffff00  # Gelb - Scoreboard
    
    embed = discord.Embed(
        title=f"{EMOJI_TARGET} Live Match Stats - {server['name']}",
        description=match_info,
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    
    if sorted_killers:
        top_text = ""
        for rank, (steam_id, data) in enumerate(sorted_killers, 1):
            emoji = {1: EMOJI_MEDAL_1, 2: EMOJI_MEDAL_2, 3: EMOJI_MEDAL_3}.get(rank, EMOJI_STAR)
            top_text += f"{emoji} **{data['name'][:25]}** - {data['kills']} Kills\n"
        
        embed.add_field(name="Top 10 Killer", value=top_text or "Noch keine Kills", inline=False)
    else:
        embed.add_field(name="Top 10 Killer", value="Noch keine Kills aufgezeichnet", inline=False)

    # Top Support (falls verfügbar)
    if match_support and support_available:
        sorted_support = sorted(
            match_support.items(),
            key=lambda x: x[1]["support"],
            reverse=True
        )[:10]
        support_text = ""
        for rank, (steam_id, data) in enumerate(sorted_support, 1):
            emoji = {1: EMOJI_MEDAL_1, 2: EMOJI_MEDAL_2, 3: EMOJI_MEDAL_3}.get(rank, EMOJI_STAR)
            support_text += f"{emoji} **{data['name'][:25]}** - {data['support']} Support\n"
        embed.add_field(name="Top 10 Support", value=support_text or "Keine Support-Daten", inline=False)
    else:
        embed.add_field(name="Top 10 Support", value="Support-Punkte sind erst nach Match-Ende verfÃ¼gbar.", inline=False)
    
    embed.set_footer(text=f"{EMOJI_REFRESH} Auto-Update alle 30 Sekunden")
    
    return embed


def create_final_embed(server, state: Dict, current_map: str, top_winners: List) -> discord.Embed:
    """Erstelle finales Match-Ende Embed"""
    match_kills = state["match_kills"]
    
    sorted_killers = sorted(
        match_kills.items(),
        key=lambda x: x[1]["kills"],
        reverse=True
    )[:10]
    
    embed = discord.Embed(
        title=f"{EMOJI_TROPHY} Match beendet - {server['name']}",
        description=f"**Map:** {current_map}",
        color=0xffd700,
        timestamp=datetime.now(timezone.utc)
    )
    
    if top_winners:
        winner_text = f"{EMOJI_MEDAL_1}{EMOJI_MEDAL_2}{EMOJI_MEDAL_3} Platz 1-3: +24 Stunden\n\n"
        for rank, steam_id, data, hours, success in top_winners:
            emoji = {1: EMOJI_MEDAL_1, 2: EMOJI_MEDAL_2, 3: EMOJI_MEDAL_3}.get(rank, f"#{rank}")
            status = EMOJI_CHECK if success else EMOJI_CROSS
            winner_text += f"{status} {emoji} **{data['name'][:25]}** - {data['kills']} Kills -> +{hours}h VIP\n"
        
        embed.add_field(name=f"{EMOJI_GIFT} VIP Belohnungen vergeben", value=winner_text, inline=False)
    
    if sorted_killers:
        top_text = ""
        vip_ids = get_vip_ids(server)
        for rank, (steam_id, data) in enumerate(sorted_killers, 1):
            has_vip = EMOJI_VIP if steam_id in vip_ids else ""
            top_text += f"{rank}. **{data['name'][:25]}** - {data['kills']} Kills {has_vip}\n"
        
        embed.add_field(name=f"{EMOJI_BAR_CHART} Top 10 Gesamt", value=top_text, inline=False)
    
    embed.set_footer(text="Match abgeschlossen")
    
    return embed


async def process_match_end(server, state: Dict, channel):
    """Verarbeite Match-Ende und vergebe VIP an Top 3"""
    if state["match_rewarded"]:
        return
    
    match_kills = state["match_kills"]
    
    if not match_kills:
        logger.info(f"[{server['name']}] Keine Kills im Match aufgezeichnet.")
        state["match_rewarded"] = True
        return
    
    # Sortiere nach Kills
    sorted_killers = sorted(
        match_kills.items(),
        key=lambda x: x[1]["kills"],
        reverse=True
    )
    
    # Hole VIP-Listen pro Server (fuer Cross-Server Vergabe)
    vip_ids_by_server = {s["base_url"]: get_vip_ids(s) for s in servers}
    
    # Filtere Top 3 ohne VIP
    top_killers_no_vip = [
        (steam_id, data) for steam_id, data in sorted_killers
        if steam_id not in vip_ids_by_server[server["base_url"]]
    ][:3]
    
    # Auch Top 3 MIT VIP für Benachrichtigungen sammeln
    top_killers_with_vip = [
        (steam_id, data) for steam_id, data in sorted_killers[:3]
        if steam_id in vip_ids_by_server[server["base_url"]]
    ]
    
    if not top_killers_no_vip:
        logger.info(f"[{server['name']}] Alle Top-Killer haben bereits VIP.")
    
    # VIP-Zeiten je nach Platzierung
    vip_hours = {1: 24, 2: 24, 3: 24}
    
    # Vergebe VIP an Top 3 ohne VIP
    top_winners = []
    for rank, (steam_id, data) in enumerate(top_killers_no_vip, 1):
        player_name = data["name"]
        kills = data["kills"]
        hours = vip_hours[rank]
        
        # Vergebe VIP auf allen Servern
        per_server_success = []
        for target_server in servers:
            target_vips = vip_ids_by_server.get(target_server["base_url"], set())
            if steam_id in target_vips:
                logger.info(
                    f"[{server['name']}] {player_name} ({steam_id}) hat bereits VIP auf {target_server['name']}, skip"
                )
                per_server_success.append(True)
                continue
            per_server_success.append(add_vip_hours(target_server, steam_id, player_name, hours))

        success = all(per_server_success)
        top_winners.append((rank, steam_id, data, hours, success))
        
        rank_emoji = {1: EMOJI_MEDAL_1, 2: EMOJI_MEDAL_2, 3: EMOJI_MEDAL_3}
        status = EMOJI_CHECK if success else EMOJI_CROSS
        logger.info(f"[{server['name']}] {status} Platz {rank}: {player_name} ({steam_id}) - {kills} Kills - +{hours}h VIP")
        
        # Sende Nachricht an Spieler
        if success:
            # Berechne Ablaufdatum für die Nachricht
            expiration_date = (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M UTC")
            pm_message = (
                "🏆 CONGRATULATIONS! 🏆\n"
                f"You placed Top Killer #{rank} with {kills} kills and had no VIP. "
                f"Your VIP has been extended until {expiration_date}."
            )
            logger.info(f"[{server['name']}] 📨 Sende PM an Top Killer #{rank}: {player_name} ({steam_id})")
            pm_success = send_private_message(server, steam_id, player_name, pm_message)
            if not pm_success:
                logger.warning(f"[{server['name']}] ⚠️ PM konnte nicht gesendet werden an {player_name} (möglicherweise disconnected)")
    
    # Benachrichtige auch Top-Killer die bereits VIP haben
    for idx, (steam_id, data) in enumerate(top_killers_with_vip):
        player_name = data["name"]
        kills = data["kills"]
        # Finde den echten Rang unter allen Killern
        try:
            rank = next(i for i, (sid, _) in enumerate(sorted_killers, 1) if sid == steam_id)
        except StopIteration:
            logger.warning(f"[{server['name']}] Konnte Rang für {player_name} ({steam_id}) nicht finden")
            continue
        
        pm_message = (
            "🏆 MATCH RESULT 🏆\n"
            f"You placed Top Killer #{rank} with {kills} kills. "
            "No VIP was granted because you already have VIP."
        )
        logger.info(f"[{server['name']}] 📨 Sende PM an Top Killer #{rank} (bereits VIP): {player_name} ({steam_id})")
        pm_success = send_private_message(server, steam_id, player_name, pm_message)
        if not pm_success:
            logger.warning(f"[{server['name']}] ⚠️ PM konnte nicht gesendet werden an {player_name} (möglicherweise disconnected)")
    
    # "Freeze" die Live-Message mit finalem Embed
    current_map, _ = get_current_map(server)
    final_embed = create_final_embed(server, state, current_map, top_winners)
    
    if state["live_message"]:
        try:
            await state["live_message"].edit(embed=final_embed)
            logger.info(f"[{server['name']}] âœ“ Live-Message eingefroren mit finalen Ergebnissen")
        except Exception as e:
            logger.error(f"Fehler beim Einfrieren der Live-Message: {e}")
    
    # Sende Benachrichtigung, sobald Match beendet und finale Punkteanzeige verfügbar ist
    try:
        if state["live_message"]:
            await channel.send(
                f"🏁 **Match beendet auf {server['name']}** – Die finale Punkteanzeige ist jetzt verfügbar."
            )
        else:
            await channel.send(
                f"🏁 **Match beendet auf {server['name']}** – Die finale Punkteanzeige ist jetzt verfügbar.",
                embed=final_embed
            )
    except Exception as e:
        logger.error(f"Fehler beim Senden der Match-Ende Nachricht: {e}")
    
    state["match_rewarded"] = True
    logger.info(f"[{server['name']}] ✓ Match abgeschlossen – Punkteanzeige gesendet")


async def process_server(server, channel):
    """Verarbeite Stats fÃ¼r einen Server"""
    state = server_states[server["base_url"]]

    scoreboard = get_live_scoreboard(server)
    if scoreboard is None:
        if not state.get("inactive_since"):
            state["inactive_since"] = datetime.now(timezone.utc)
            logger.warning(f"[{server['name']}] Server ist inaktiv seit {state['inactive_since'].isoformat()}")
        return

    if state.get("inactive_since"):
        inactive_for = datetime.now(timezone.utc) - state["inactive_since"]
        logger.info(f"[{server['name']}] Server wieder aktiv nach {inactive_for}")
        state["inactive_since"] = None

        # Restart counting from current stats while keeping previous totals
        state["kill_offsets"] = {}
        for steam_id, data in state["match_kills"].items():
            state["kill_offsets"][steam_id] = data.get("kills", 0)
        for player in extract_scoreboard_players(scoreboard):
            steam_id = player.get("player_id") or player.get("steam_id_64")
            kills = player.get("kills", 0)
            if steam_id and steam_id != "None":
                state["baseline_kills"][steam_id] = kills

    # Hole aktuelle Map/Match
    current_map, match_id = get_current_map(server)
    state["current_map"] = current_map
    
    if match_id and match_id != state["current_match_id"]:
        # Neues Match erkannt
        if state["current_match_id"]:
            logger.info(f"[{server['name']}] Match-Ende erkannt: {state['current_match_id']}")
            # Verarbeite vorheriges Match
            await process_match_end(server, state, channel)
        
        # Reset fÃ¼r neues Match
        logger.info(f"[{server['name']}] Neues Match gestartet: {match_id}")
        state["current_match_id"] = match_id
        state["match_kills"] = defaultdict(lambda: {"name": "", "kills": 0})
        state["match_support"] = defaultdict(lambda: {"name": "", "support": 0})
        state["baseline_kills"] = {}
        state["kill_offsets"] = {}
        state["match_start"] = datetime.now(timezone.utc)
        state["match_rewarded"] = False
        state["live_message"] = None
        state["last_update"] = None
        state["support_debug_logged"] = False

        # Baseline-Kills beim Matchstart setzen (damit Kills bei 0 starten)
        start_players = extract_scoreboard_players(scoreboard)
        for player in start_players:
            steam_id = player.get("player_id") or player.get("steam_id_64")
            kills = player.get("kills", 0)
            if steam_id and steam_id != "None":
                state["baseline_kills"][steam_id] = kills
    
    # WICHTIG: Reset match_kills VOR dem Update, um alte Daten zu lÃ¶schen
    state["match_kills"].clear()
    state["match_support"].clear()
    
    # Verarbeite Spieler-Stats
    player_count = 0
    players = extract_scoreboard_players(scoreboard)
    
    if isinstance(scoreboard, dict):
        logger.info(f"[{server['name']}] Scoreboard-Keys: {list(scoreboard.keys())}")

    logger.info(f"[{server['name']}] Anzahl Spieler im Scoreboard: {len(players)}")
    
    # Support-Daten bevorzugt aus Map-Scoreboard (falls verfÃ¼gbar)
    support_players = None
    map_players = None
    players_endpoint_players = None
    players_endpoint = get_players(server)
    if players_endpoint:
        players_endpoint_players = extract_scoreboard_players(players_endpoint)
        if any(_extract_support_points(p) is not None for p in players_endpoint_players):
            support_players = players_endpoint_players

    map_scoreboard = get_map_scoreboard(server)
    if map_scoreboard:
        map_players = extract_scoreboard_players(map_scoreboard)
        if support_players is None and any(_extract_support_points(p) is not None for p in map_players):
            support_players = map_players

    if support_players is None:
        support_players = players

    for player in players:
        if not isinstance(player, dict):
            continue
            
        steam_id = player.get("player_id") or player.get("steam_id_64")
        player_name = player.get("player") or player.get("name", "Unknown")
        kills = player.get("kills", 0)
        
        if not steam_id or steam_id == "None":
            continue
        
        # Baseline abziehen (Kills seit Matchstart)
        baseline = state["baseline_kills"].get(steam_id, 0)
        if kills < baseline:
            # Spieler hat sich evtl. reconnectet, baseline anpassen
            state["baseline_kills"][steam_id] = kills
            baseline = kills
        offset = state.get("kill_offsets", {}).get(steam_id, 0)
        match_kills = max(0, offset + (kills - baseline))

        # Update nur wenn Spieler Kills seit Matchstart hat
        if match_kills > 0:
            state["match_kills"][steam_id] = {"name": player_name, "kills": match_kills}
            player_count += 1

    support_nonzero_found = False
    for player in support_players:
        if not isinstance(player, dict):
            continue
        steam_id = player.get("player_id") or player.get("steam_id_64") or player.get("player_id")
        player_name = player.get("player") or player.get("name", "Unknown")
        if not steam_id or steam_id == "None":
            continue

        support_points = _extract_support_points(player)
        if support_points is not None:
            state["match_support"][steam_id] = {"name": player_name, "support": support_points}
            if support_points > 0:
                support_nonzero_found = True

    state["support_available"] = support_nonzero_found

    if not state["support_debug_logged"]:
        sample_source = support_players[0] if support_players else None
        if sample_source:
            sample_keys = list(sample_source.keys())
            sample_support = sample_source.get("support")
            logger.info(
                f"[{server['name']}] Support-Debug: Beispiel-Keys im Scoreboard: {sample_keys} | "
                f"support={sample_support} (type={type(sample_support).__name__}) | "
                f"Quelle={'players' if (players_endpoint_players is not None and support_players is players_endpoint_players) else ('map' if (map_players is not None and support_players is map_players) else 'live')}"
            )
        if players_endpoint is None:
            logger.info(f"[{server['name']}] Support-Debug: Players-Endpoint nicht verfÃ¼gbar (API/Permission?).")
        if map_scoreboard is None:
            logger.info(f"[{server['name']}] Support-Debug: Map-Scoreboard nicht verfÃ¼gbar (API/Permission?).")
        state["support_debug_logged"] = True
            
    logger.info(f"[{server['name']}] Verarbeitete Spieler mit Kills: {player_count}/{len(players)}")


@tasks.loop(seconds=30)
async def update_live_stats():
    """Update Live-Stats alle 30 Sekunden"""
    if shutdown_requested:
        update_live_stats.cancel()
        return
    
    try:
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        logger.info(f"[DEBUG] Channel-Lookup: {channel is not None}, Channel-ID: {DISCORD_CHANNEL_ID}, Bot Ready: {bot.is_ready()}")
        
        if not channel:
            logger.warning(f"âš ï¸ Channel nicht gefunden! Channel-ID: {DISCORD_CHANNEL_ID}, Bot Ready: {bot.is_ready()}")
            return
        
        for server in servers:
            state = server_states[server["base_url"]]
            
            # Verarbeite Server (Logs abrufen)
            await process_server(server, channel)
            
            # Debug-Info
            logger.info(f"[{server['name']}] Match-Status: ID={state['current_match_id']}, Rewarded={state['match_rewarded']}, Kills={len(state['match_kills'])}")
            
            # Nur Live-Update wenn Match lÃ¤uft und nicht belohnt
            if state["current_match_id"] and not state["match_rewarded"] and not state.get("inactive_since"):
                current_map = state.get("current_map") or "Unknown"
                embed = create_live_embed(server, state, current_map)
                
                logger.info(f"[{server['name']}] Versuche Discord-Message zu senden...")
                
                if state["live_message"]:
                    # Update existierende Message
                    try:
                        if not state.get("live_message_id"):
                            state["live_message_id"] = state["live_message"].id
                        await state["live_message"].edit(embed=embed)
                        logger.info(f"[{server['name']}] âœ“ Live-Message aktualisiert")
                    except discord.NotFound:
                        # Message wurde gelÃ¶scht, erstelle neue
                        state["live_message"] = await channel.send(embed=embed)
                        state["live_message_id"] = state["live_message"].id
                        logger.info(f"[{server['name']}] âœ“ Live-Message neu erstellt (alte gelÃ¶scht)")
                    except Exception as e:
                        logger.error(f"[{server['name']}] âœ— Fehler beim Update der Live-Message: {e}", exc_info=True)
                else:
                    # Erstelle neue Live-Message
                    try:
                        state["live_message"] = await channel.send(embed=embed)
                        state["live_message_id"] = state["live_message"].id
                        logger.info(f"[{server['name']}] âœ“ Live-Message erstellt")
                    except Exception as e:
                        logger.error(f"[{server['name']}] âœ— Fehler beim Erstellen der Live-Message: {e}", exc_info=True)

        save_state()
    
    except Exception as e:
        logger.error(f"Fehler in update_live_stats: {e}", exc_info=True)


@tasks.loop(minutes=1)
async def daily_restart_check():
    global last_restart_date
    if shutdown_requested:
        daily_restart_check.cancel()
        return

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    if last_restart_date == today_str:
        return

    if now.hour > RESTART_HOUR or (now.hour == RESTART_HOUR and now.minute >= RESTART_MINUTE):
        last_restart_date = today_str
        save_state(force=True)
        logger.info(f"[RESTART] TÃ¤glicher Neustart ausgelÃ¶st um {RESTART_HOUR:02d}:{RESTART_MINUTE:02d}")
        await bot.close()
        os.execv(sys.executable, [sys.executable] + sys.argv)


async def restore_live_messages(channel):
    for server in servers:
        state = server_states[server["base_url"]]
        message_id = state.get("live_message_id")
        if not message_id:
            continue
        try:
            state["live_message"] = await channel.fetch_message(message_id)
            state["live_message_id"] = state["live_message"].id
            logger.info(f"[{server['name']}] âœ“ Live-Message wiederhergestellt (ID: {message_id})")
        except discord.NotFound:
            state["live_message"] = None
            state["live_message_id"] = None
            logger.warning(f"[{server['name']}] Live-Message nicht gefunden (ID: {message_id})")
        except Exception as e:
            logger.error(f"[{server['name']}] Fehler beim Laden der Live-Message: {e}")


@bot.event
async def on_ready():
    logger.info(f"\n{'='*60}")
    logger.info(f"ðŸŽ¯ TOP KILLER VIP BOT GESTARTET")
    logger.info(f"{'='*60}")
    logger.info(f"Bot User: {bot.user} (ID: {bot.user.id})")
    logger.info(f"Discord Channel ID: {DISCORD_CHANNEL_ID}")
    logger.info(f"Guilds: {len(bot.guilds)}")
    for guild in bot.guilds:
        logger.info(f"  - Guild: {guild.name} (ID: {guild.id})")
    logger.info(f"Ãœberwachte Server: {len(servers)}")
    for server in servers:
        logger.info(f"  - {server['name']}")
    logger.info(f"{'='*60}\n")
    
    # Test Channel-Zugriff
    test_channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if test_channel:
        logger.info(f"âœ“ Channel gefunden: {test_channel.name} (ID: {test_channel.id}) in {test_channel.guild.name}")
        await restore_live_messages(test_channel)
    else:
        logger.error(f"âœ— Channel nicht gefunden! Channel-ID: {DISCORD_CHANNEL_ID}")
        logger.error(f"VerfÃ¼gbare Channels:")
        for guild in bot.guilds:
            for channel in guild.text_channels:
                logger.error(f"  - {channel.name} (ID: {channel.id})")
    
    # Starte Live-Update Task
    if not update_live_stats.is_running():
        update_live_stats.start()
        logger.info("âœ“ Live-Update Task gestartet")
    else:
        logger.warning("Live-Update Task lÃ¤uft bereits")

    if not daily_restart_check.is_running():
        daily_restart_check.start()
        logger.info("âœ“ Daily-Restart Task gestartet")

    save_state(force=True)


async def main():
    """Hauptfunktion"""
    try:
        await bot.start(DISCORD_BOT_TOKEN)
    except KeyboardInterrupt:
        logger.info("\n[SHUTDOWN] Bot wird beendet...")
    except Exception as e:
        logger.error(f"Fataler Fehler: {e}", exc_info=True)
    finally:
        save_state(force=True)
        if not bot.is_closed():
            await bot.close()
        logger.info("[SHUTDOWN] Bot beendet")


if __name__ == "__main__":
    try:
        ensure_data_dir()
        load_state()
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot gestoppt")
    except Exception as e:
        logger.error(f"Fataler Fehler: {e}", exc_info=True)
        sys.exit(1)
