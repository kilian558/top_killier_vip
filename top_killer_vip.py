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

# VIP-Blacklist (keine VIP-Vergabe)
VIP_EXCLUDE_IDS = {"76561198859268589"}
VIP_EXCLUDE_NAMES = {"lexman"}

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
        "match_rewarded": False,
        "match_end_pending_at": None
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


def get_live_scoreboard(server) -> List[Dict]:
    """Hole Live-Scoreboard für aktuell verbundene Spieler"""
    try:
        response = server["session"].get(
            f"{server['base_url']}/api/get_live_scoreboard",
            timeout=15
        )
        response.raise_for_status()
        return response.json().get("result", [])
    except Exception as e:
        logger.error(f"Fehler beim Abrufen des Scoreboards von {server['name']}: {e}")
        return []


def get_map_scoreboard(server) -> List[Dict]:
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
        return []


def get_gamestate(server) -> Dict:
    """Hole aktuellen Gamestate"""
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


def get_round_time_remaining(server) -> float | None:
    """Hole verbleibende Rundzeit in Sekunden"""
    try:
        response = server["session"].get(
            f"{server['base_url']}/api/get_round_time_remaining",
            timeout=10
        )
        response.raise_for_status()
        return float(response.json().get("result"))
    except Exception:
        return None


def extract_scoreboard_players(scoreboard) -> List[Dict]:
    """Extrahiere Spieler-Liste aus unterschiedlichen Scoreboard-Formaten"""
    players: List[Dict] = []

    if isinstance(scoreboard, dict):
        for team_key in ("allied", "axis", "team1", "team2"):
            team_players = scoreboard.get(team_key)
            if isinstance(team_players, list):
                players.extend([p for p in team_players if isinstance(p, dict)])

        if not players and isinstance(scoreboard.get("stats"), list):
            players = [p for p in scoreboard.get("stats", []) if isinstance(p, dict)]

        if not players and isinstance(scoreboard.get("players"), list):
            players = [p for p in scoreboard.get("players", []) if isinstance(p, dict)]

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


def get_player_support_points(server, player_id: str = None, player_name: str = None, players: List[Dict] | None = None) -> int | None:
    """Lese Support-Punkte eines einzelnen Spielers aus dem Scoreboard"""
    if players is None:
        scoreboard = get_live_scoreboard(server)
        players = extract_scoreboard_players(scoreboard)

    def normalize_name(name: str) -> str:
        return (name or "").strip().casefold()

    target_name = normalize_name(player_name) if player_name else None

    for player in players:
        pid = player.get("player_id") or player.get("steam_id") or player.get("playerid")
        pname = player.get("name") or player.get("player_name") or player.get("player")

        if player_id and pid and str(pid) == str(player_id):
            return _extract_support_points(player)
        if target_name and pname and normalize_name(pname) == target_name:
            return _extract_support_points(player)

    return None


def _extract_support_points(player: Dict) -> int | None:
    """Support-Punkte aus Spieler-Objekt extrahieren (verschiedene mögliche Keys)."""
    for key in (
        "support", "support_points", "support_score", "score_support",
        "supportScore", "supportPoints", "supp"
    ):
        if key in player and player[key] is not None:
            try:
                return int(player[key])
            except (ValueError, TypeError):
                return None
    return None


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


def get_vip_expiration(server, steam_id: str) -> str | None:
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


def is_lifetime_vip(expiration) -> bool:
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


def _compute_award_expiration(server, steam_id: str, hours: int) -> str | None:
    current_exp = get_vip_expiration(server, steam_id)
    if is_lifetime_vip(current_exp):
        return None
    if current_exp:
        base_time = parse_vip_expiration(current_exp)
    else:
        base_time = datetime.now(timezone.utc)
    return (base_time + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def add_vip_hours(server, steam_id: str, player_name: str, hours: int, expiration: str | None = None) -> bool:
    """Fuege VIP mit angegebenen Stunden hinzu"""
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

        expiration = expiration or _compute_award_expiration(server, steam_id, hours)
        if not expiration:
            return False

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
            logger.error(f"✗ VIP-Fehler fuer {player_name}: {response.status_code} - {response.text[:200]}")
            return False

    except Exception as e:
        logger.error(f"Fehler beim Vergeben von VIP fuer {player_name}: {e}")
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
    """Verarbeite Match-Ende und vergebe VIP an Top 3"""
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

    # Erstelle Discord-Log
    current_map, _ = get_current_map(server)
    discord_msg = f"**🏆 Match beendet - {server['name']}**\n"
    discord_msg += f"Map: {current_map}\n\n"

    # Versuche Map-Scoreboard, dann Live-Scoreboard als Fallback
    map_scoreboard = get_map_scoreboard(server)
    if map_scoreboard:
        logger.info(f"[{server['name']}] ✓ Map-Scoreboard verfügbar")
        scoreboard_players = extract_scoreboard_players(map_scoreboard)
    else:
        logger.warning(f"[{server['name']}] ⚠️ Map-Scoreboard nicht verfügbar - verwende Live-Scoreboard")
        scoreboard_players = extract_scoreboard_players(get_live_scoreboard(server))
    
    # Prüfe ob Support-Punkte verfügbar sind
    support_available = any(_extract_support_points(p) is not None and _extract_support_points(p) > 0 for p in scoreboard_players)
    if not support_available:
        logger.warning(f"[{server['name']}] ⚠️ Keine Support-Punkte im Scoreboard gefunden (möglicherweise API-Permission fehlt).")

    awarded_ids: set[str] = set()

    # Top Killer Benachrichtigungen (bis 3 VIP vergeben)
    discord_msg += "**📊 VIP Belohnungen vergeben:**\n"
    discord_msg += "**🔪 Platz 1-3: +24 Stunden**\n\n"

    killer_results = []
    vip_awarded_count = 0
    last_rank_awarded = 0

    for rank, (steam_id, data) in enumerate(sorted_killers, 1):
        if vip_awarded_count >= 3:
            break

        player_name = data["name"]
        kills = data["kills"]
        has_vip = steam_id in vip_ids
        is_excluded = str(steam_id) in VIP_EXCLUDE_IDS or (player_name or "").strip().casefold() in VIP_EXCLUDE_NAMES

        support_points = get_player_support_points(
            server,
            player_id=steam_id,
            player_name=player_name,
            players=scoreboard_players
        )

        award_success = False
        expiration = None

        if (not has_vip) and (not is_excluded) and vip_awarded_count < 3:
            hours = 24
            expiration = _compute_award_expiration(server, steam_id, hours)
            if expiration:
                award_success = add_vip_hours(server, steam_id, player_name, hours, expiration=expiration)
            if award_success:
                awarded_ids.add(steam_id)
                vip_awarded_count += 1
                last_rank_awarded = rank

        killer_results.append({
            "rank": rank,
            "steam_id": steam_id,
            "name": player_name,
            "kills": kills,
            "support_points": support_points,
            "has_vip": has_vip,
            "is_excluded": is_excluded,
            "award_success": award_success,
            "expiration": expiration
        })

    for result in killer_results:
        if result["rank"] > last_rank_awarded:
            continue

        rank = result["rank"]
        steam_id = result["steam_id"]
        player_name = result["name"]
        kills = result["kills"]
        support_points = result["support_points"]
        has_vip = result["has_vip"]
        is_excluded = result["is_excluded"]
        award_success = result["award_success"]
        expiration = result["expiration"]

        support_text = f" | Support: {support_points}" if support_points is not None else ""
        rank_emoji = {1: "🥇", 2: "🥈", 3: "🥉"}

        if award_success:
            pm_message = (
                "🏆 CONGRATULATIONS! 🏆\n"
                f"You placed Top Killer #{rank} with {kills} kills and had no VIP. "
                f"Your VIP has been extended until {expiration}."
            )
            send_private_message(server, steam_id, player_name, pm_message)

            logger.info(
                f"[{server['name']}] ✓ Platz {rank}: {player_name} ({steam_id}) - {kills} Kills{support_text} - +24h VIP"
            )
            discord_msg += (
                f"✓ {rank_emoji.get(rank, f'#{rank}')} **{player_name}** - {kills} Kills"
                f"{support_text} → +24h VIP\n"
            )
        else:
            if has_vip:
                reason = "No VIP was granted because you already have VIP."
            elif is_excluded:
                reason = "No VIP was granted."
            else:
                reason = "No VIP was granted."

            pm_message = (
                "🏆 MATCH RESULT 🏆\n"
                f"You placed Top Killer #{rank} with {kills} kills. {reason}"
            )
            send_private_message(server, steam_id, player_name, pm_message)

            discord_msg += (
                f"• {rank_emoji.get(rank, f'#{rank}')} **{player_name}** - {kills} Kills"
                f"{support_text} → keine VIP (bereits VIP/ausgenommen)\n"
            )

    # Top Support Benachrichtigungen (bis 2 VIP vergeben)
    support_candidates = []
    for player in scoreboard_players:
        pid = player.get("player_id") or player.get("steam_id") or player.get("playerid")
        pname = player.get("name") or player.get("player_name") or player.get("player") or "Unknown"
        points = _extract_support_points(player)
        if pid and points is not None:
            if str(pid) in VIP_EXCLUDE_IDS or (pname or "").strip().casefold() in VIP_EXCLUDE_NAMES:
                continue
            support_candidates.append((pid, pname, points))

    support_candidates.sort(key=lambda x: x[2], reverse=True)
    
    if support_available:
        discord_msg += "\n**🛠️ Platz 1-2 Support: +24 Stunden**\n\n"
    else:
        discord_msg += "\n**⚠️ Support-Punkte nicht verfügbar (API-Permission fehlt möglicherweise)**\n\n"

    support_results = []
    support_awarded_count = 0
    last_support_rank_awarded = 0

    for rank, (pid, pname, points) in enumerate(support_candidates, 1):
        if support_awarded_count >= 2:
            break

        has_vip = pid in vip_ids
        is_excluded = str(pid) in VIP_EXCLUDE_IDS or (pname or "").strip().casefold() in VIP_EXCLUDE_NAMES

        award_success = False
        expiration = None

        if (not has_vip) and (pid not in awarded_ids) and (not is_excluded) and support_awarded_count < 2:
            hours = 24
            expiration = _compute_award_expiration(server, pid, hours)
            if expiration:
                award_success = add_vip_hours(server, pid, pname, hours, expiration=expiration)
            if award_success:
                awarded_ids.add(pid)
                support_awarded_count += 1
                last_support_rank_awarded = rank

        support_results.append({
            "rank": rank,
            "steam_id": pid,
            "name": pname,
            "points": points,
            "has_vip": has_vip,
            "is_excluded": is_excluded,
            "award_success": award_success,
            "expiration": expiration
        })

    for result in support_results:
        if result["rank"] > last_support_rank_awarded:
            continue

        rank = result["rank"]
        pid = result["steam_id"]
        pname = result["name"]
        points = result["points"]
        has_vip = result["has_vip"]
        is_excluded = result["is_excluded"]
        award_success = result["award_success"]
        expiration = result["expiration"]

        rank_emoji = {1: "🥇", 2: "🥈"}

        if award_success:
            pm_message = (
                "🛠️ CONGRATULATIONS! 🛠️\n"
                f"You placed Top Support #{rank} with {points} support points and had no VIP. "
                f"Your VIP has been extended until {expiration}."
            )
            send_private_message(server, pid, pname, pm_message)

            logger.info(
                f"[{server['name']}] ✓ Support Platz {rank}: {pname} ({pid}) - Support: {points} - +24h VIP"
            )
            discord_msg += f"✓ {rank_emoji.get(rank, f'#{rank}')} **{pname}** - Support: {points} → +24h VIP\n"
        else:
            if has_vip:
                reason = "No VIP was granted because you already have VIP."
            elif pid in awarded_ids:
                reason = "No VIP was granted because you already received a VIP as Top Killer."
            elif is_excluded:
                reason = "No VIP was granted."
            else:
                reason = "No VIP was granted."

            pm_message = (
                "🛠️ MATCH RESULT 🛠️\n"
                f"You placed Top Support #{rank} with {points} support points. {reason}"
            )
            send_private_message(server, pid, pname, pm_message)

            discord_msg += f"• {rank_emoji.get(rank, f'#{rank}')} **{pname}** - Support: {points} → keine VIP (bereits VIP/ausgenommen)\n"
    
    # Zeige alle Top 10 zur Info
    discord_msg += "\n**📊 Top 10 Gesamt:**\n"
    for rank, (steam_id, data) in enumerate(sorted_killers[:10], 1):
        player_support = get_player_support_points(
            server,
            player_id=steam_id,
            player_name=data['name'],
            players=scoreboard_players
        )
        support_text = f", Support: {player_support}" if player_support is not None and player_support > 0 else ""
        discord_msg += f"{data['name']} - {data['kills']} Kills{support_text}\n"
    
    discord_msg += f"\n✅ **Match abgeschlossen** • {datetime.now(timezone.utc).strftime('%H:%M Uhr')}"
    
    send_discord_log(discord_msg)
    logger.info(f"[{server['name']}] ✓ Match abgeschlossen – Belohnungen vergeben & Discord-Benachrichtigung gesendet")
    
    state["match_rewarded"] = True


def process_server(server):
    """Verarbeite Logs für einen Server"""
    state = server_states[server["base_url"]]

    # Hole aktuelle Map/Match ZUERST
    current_map, match_id = get_current_map(server)
    
    # Frühes Match-Ende erkennen (Scoreboard-Phase) - VOR Map-Wechsel-Check
    remaining = None
    gamestate = get_gamestate(server)
    
    # Extrahiere Timer aus Gamestate
    if isinstance(gamestate, dict):
        for key in ("remaining_time", "remaining_time_seconds", "remaining_time_sec", "remaining_time_s"):
            if key in gamestate:
                try:
                    remaining = float(gamestate[key])
                    break
                except (TypeError, ValueError):
                    pass

    if remaining is None:
        remaining = get_round_time_remaining(server)

    # Extrahiere Score aus Gamestate (Allied vs Axis)
    allied_score = 0
    axis_score = 0
    if isinstance(gamestate, dict):
        # Verschiedene mögliche Score-Felder
        for allied_key in ("allied_score", "team1_score", "allied", "team1"):
            if allied_key in gamestate:
                try:
                    allied_score = int(gamestate[allied_key])
                    break
                except (ValueError, TypeError):
                    pass
        
        for axis_key in ("axis_score", "team2_score", "axis", "team2"):
            if axis_key in gamestate:
                try:
                    axis_score = int(gamestate[axis_key])
                    break
                except (ValueError, TypeError):
                    pass

    # Match-Ende Bedingungen:
    # 1. Timer bei 0 (Zeit abgelaufen) → 90s Scoreboard startet
    # 2. Score 5:0 (ein Team gewinnt) → 90s Scoreboard startet
    match_ended = False
    end_reason = ""
    
    if remaining is not None and remaining <= 0:
        match_ended = True
        end_reason = "Zeit abgelaufen (Timer ≤ 0)"
    elif allied_score >= 5 or axis_score >= 5:
        match_ended = True
        end_reason = f"Score erreicht ({allied_score}:{axis_score})"
    
    if match_ended and not state["match_rewarded"] and state["current_match_id"]:
        logger.info(f"[{server['name']}] 🏁 Match-Ende erkannt: {end_reason} - Scoreboard-Phase (90s)!")
        process_match_end(server, state)
        # WICHTIG: match_id bleibt gleich bis zum Map-Wechsel
        return
    
    # Logging für Scoreboard-Phase (noch nicht bei 0/5:0)
    if remaining is not None and 0 < remaining <= 90 and not state["match_rewarded"] and state.get("match_end_pending_at") is None:
        state["match_end_pending_at"] = datetime.now(timezone.utc)
        logger.info(f"[{server['name']}] ⏱️ Bald Scoreboard-Phase ({remaining:.0f}s verbleibend, Score {allied_score}:{axis_score}).")
    
    # Neues Match erkannt (Map-Wechsel)
    if match_id and match_id != state["current_match_id"]:
        # Vorheriges Match abschließen (falls noch nicht rewarded)
        if state["current_match_id"] and not state["match_rewarded"]:
            logger.warning(f"[{server['name']}] ⚠️ Map-Wechsel ohne Match-Abschluss erkannt! Verarbeite nachträglich.")
            process_match_end(server, state)
        
        # Reset für neues Match
        logger.info(f"[{server['name']}] 🗺️ Neues Match gestartet: {match_id}")
        state["current_match_id"] = match_id
        state["match_kills"] = defaultdict(lambda: {"name": "", "kills": 0})
        state["match_start"] = datetime.now()
        state["match_rewarded"] = False
        state["match_end_pending_at"] = None
        
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





