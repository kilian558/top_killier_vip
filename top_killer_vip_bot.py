#!/usr/bin/env python3
"""
Top Killer VIP Bot für Hell Let Loose CRCON mit Discord Bot Integration
Trackt Kills während eines Matches mit Live-Updates in Discord
"""

import os
import sys
import signal
import logging
import asyncio
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
        "current_match_id": None,
        "match_kills": defaultdict(lambda: {"name": "", "kills": 0}),
        "match_start": None,
        "match_rewarded": False,
        "live_message": None,  # Discord Message für Live-Updates
        "last_update": None    # Timestamp des letzten Updates
    }
    for server in servers
}

# Discord Bot Setup
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

# Graceful Shutdown Handler
shutdown_requested = False

def signal_handler(sig, frame):
    global shutdown_requested
    logger.info(f"\n[SHUTDOWN] Signal {sig} empfangen - Bot wird beendet...")
    shutdown_requested = True

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def get_live_game_stats(server) -> Dict:
    """Hole Live-Game-Stats für das aktuelle Match"""
    try:
        response = server["session"].get(
            f"{server['base_url']}/api/get_live_game_stats",
            timeout=15
        )
        response.raise_for_status()
        return response.json().get("result", {})
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Live-Stats von {server['name']}: {e}")
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


def add_vip_hours(server, steam_id: str, player_name: str, hours: int) -> bool:
    """Füge VIP mit angegebenen Stunden hinzu"""
    try:
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


def create_live_embed(server, state: Dict, current_map: str) -> discord.Embed:
    """Erstelle Live-Update Embed"""
    match_kills = state["match_kills"]
    
    # Sortiere nach Kills
    sorted_killers = sorted(
        match_kills.items(),
        key=lambda x: x[1]["kills"],
        reverse=True
    )[:10]
    
    # Embed erstellen
    embed = discord.Embed(
        title=f"🎯 Live Match Stats - {server['name']}",
        description=f"**Map:** {current_map}\n**Match Start:** <t:{int(state['match_start'].timestamp())}:R>" if state['match_start'] else f"**Map:** {current_map}",
        color=0x00ff00,
        timestamp=datetime.now(timezone.utc)
    )
    
    if sorted_killers:
        top_text = ""
        for rank, (steam_id, data) in enumerate(sorted_killers, 1):
            emoji = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "▫️")
            top_text += f"{emoji} **{data['name'][:25]}** - {data['kills']} Kills\n"
        
        embed.add_field(name="Top 10 Killer", value=top_text or "Noch keine Kills", inline=False)
    else:
        embed.add_field(name="Top 10 Killer", value="Noch keine Kills aufgezeichnet", inline=False)
    
    embed.set_footer(text="🔄 Auto-Update alle 30 Sekunden")
    
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
        title=f"🏆 Match beendet - {server['name']}",
        description=f"**Map:** {current_map}",
        color=0xffd700,
        timestamp=datetime.now(timezone.utc)
    )
    
    if top_winners:
        winner_text = "🥇 Platz 1: +72 Stunden | 🥈 Platz 2: +48 Stunden | 🥉 Platz 3-5: +24 Stunden\n\n"
        for rank, (steam_id, data, hours, success) in top_winners:
            emoji = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣"}.get(rank, f"#{rank}")
            status = "✓" if success else "✗"
            winner_text += f"{status} {emoji} **{data['name'][:25]}** - {data['kills']} Kills → +{hours}h VIP\n"
        
        embed.add_field(name="🎁 VIP Belohnungen vergeben", value=winner_text, inline=False)
    
    if sorted_killers:
        top_text = ""
        vip_ids = get_vip_ids(server)
        for rank, (steam_id, data) in enumerate(sorted_killers, 1):
            has_vip = "👑" if steam_id in vip_ids else ""
            top_text += f"{rank}. **{data['name'][:25]}** - {data['kills']} Kills {has_vip}\n"
        
        embed.add_field(name="📊 Top 10 Gesamt", value=top_text, inline=False)
    
    embed.set_footer(text="Match abgeschlossen")
    
    return embed


async def process_match_end(server, state: Dict, channel):
    """Verarbeite Match-Ende und vergebe VIP an Top 5"""
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
    
    # VIP-Zeiten je nach Platzierung
    vip_hours = {1: 72, 2: 48, 3: 24, 4: 24, 5: 24}
    
    # Vergebe VIP an Top 5 ohne VIP
    top_winners = []
    for rank, (steam_id, data) in enumerate(top_killers_no_vip, 1):
        player_name = data["name"]
        kills = data["kills"]
        hours = vip_hours[rank]
        
        # Vergebe VIP
        success = add_vip_hours(server, steam_id, player_name, hours)
        top_winners.append((rank, steam_id, data, hours, success))
        
        rank_emoji = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣"}
        status = "✓" if success else "✗"
        logger.info(f"[{server['name']}] {status} Platz {rank}: {player_name} ({steam_id}) - {kills} Kills - +{hours}h VIP")
    
    # "Freeze" die Live-Message mit finalem Embed
    current_map, _ = get_current_map(server)
    final_embed = create_final_embed(server, state, current_map, top_winners)
    
    if state["live_message"]:
        try:
            await state["live_message"].edit(embed=final_embed)
            logger.info(f"[{server['name']}] ✓ Live-Message eingefroren mit finalen Ergebnissen")
        except Exception as e:
            logger.error(f"Fehler beim Einfrieren der Live-Message: {e}")
    
    state["match_rewarded"] = True
    logger.info(f"[{server['name']}] ✓ VIP an Top 5 Killer vergeben (72h/48h/24h/24h/24h)")


async def process_server(server, channel):
    """Verarbeite Stats für einen Server"""
    state = server_states[server["base_url"]]
    
    # Hole aktuelle Map/Match
    current_map, match_id = get_current_map(server)
    
    if match_id and match_id != state["current_match_id"]:
        # Neues Match erkannt
        if state["current_match_id"]:
            logger.info(f"[{server['name']}] Match-Ende erkannt: {state['current_match_id']}")
            # Verarbeite vorheriges Match
            await process_match_end(server, state, channel)
        
        # Reset für neues Match
        logger.info(f"[{server['name']}] Neues Match gestartet: {match_id}")
        state["current_match_id"] = match_id
        state["match_kills"] = defaultdict(lambda: {"name": "", "kills": 0})
        state["match_start"] = datetime.now(timezone.utc)
        state["match_rewarded"] = False
        state["live_message"] = None
        state["last_update"] = None
    
    # Hole Live Game Stats
    live_stats = get_live_game_stats(server)
    
    if not live_stats or "player_stats" not in live_stats:
        return
    
    # Verarbeite Spieler-Stats
    player_stats = live_stats.get("player_stats", {})
    
    for steam_id, stats in player_stats.items():
        if not steam_id or steam_id == "None":
            continue
            
        player_name = stats.get("player", "Unknown")
        kills = stats.get("kills", 0)
        
        # Update nur wenn Spieler Kills hat
        if kills > 0:
            state["match_kills"][steam_id]["name"] = player_name
            state["match_kills"][steam_id]["kills"] = kills


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
            logger.warning(f"⚠️ Channel nicht gefunden! Channel-ID: {DISCORD_CHANNEL_ID}, Bot Ready: {bot.is_ready()}")
            return
        
        for server in servers:
            state = server_states[server["base_url"]]
            
            # Verarbeite Server (Logs abrufen)
            await process_server(server, channel)
            
            # Debug-Info
            logger.info(f"[{server['name']}] Match-Status: ID={state['current_match_id']}, Rewarded={state['match_rewarded']}, Kills={len(state['match_kills'])}")
            
            # Nur Live-Update wenn Match läuft und nicht belohnt
            if state["current_match_id"] and not state["match_rewarded"]:
                current_map, _ = get_current_map(server)
                embed = create_live_embed(server, state, current_map)
                
                logger.info(f"[{server['name']}] Versuche Discord-Message zu senden...")
                
                if state["live_message"]:
                    # Update existierende Message
                    try:
                        await state["live_message"].edit(embed=embed)
                        logger.info(f"[{server['name']}] ✓ Live-Message aktualisiert")
                    except discord.NotFound:
                        # Message wurde gelöscht, erstelle neue
                        state["live_message"] = await channel.send(embed=embed)
                        logger.info(f"[{server['name']}] ✓ Live-Message neu erstellt (alte gelöscht)")
                    except Exception as e:
                        logger.error(f"[{server['name']}] ✗ Fehler beim Update der Live-Message: {e}", exc_info=True)
                else:
                    # Erstelle neue Live-Message
                    try:
                        state["live_message"] = await channel.send(embed=embed)
                        logger.info(f"[{server['name']}] ✓ Live-Message erstellt")
                    except Exception as e:
                        logger.error(f"[{server['name']}] ✗ Fehler beim Erstellen der Live-Message: {e}", exc_info=True)
    
    except Exception as e:
        logger.error(f"Fehler in update_live_stats: {e}", exc_info=True)


@bot.event
async def on_ready():
    logger.info(f"\n{'='*60}")
    logger.info(f"🎯 TOP KILLER VIP BOT GESTARTET")
    logger.info(f"{'='*60}")
    logger.info(f"Bot User: {bot.user} (ID: {bot.user.id})")
    logger.info(f"Discord Channel ID: {DISCORD_CHANNEL_ID}")
    logger.info(f"Guilds: {len(bot.guilds)}")
    for guild in bot.guilds:
        logger.info(f"  - Guild: {guild.name} (ID: {guild.id})")
    logger.info(f"Überwachte Server: {len(servers)}")
    for server in servers:
        logger.info(f"  - {server['name']}")
    logger.info(f"{'='*60}\n")
    
    # Test Channel-Zugriff
    test_channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if test_channel:
        logger.info(f"✓ Channel gefunden: {test_channel.name} (ID: {test_channel.id}) in {test_channel.guild.name}")
    else:
        logger.error(f"✗ Channel nicht gefunden! Channel-ID: {DISCORD_CHANNEL_ID}")
        logger.error(f"Verfügbare Channels:")
        for guild in bot.guilds:
            for channel in guild.text_channels:
                logger.error(f"  - {channel.name} (ID: {channel.id})")
    
    # Starte Live-Update Task
    if not update_live_stats.is_running():
        update_live_stats.start()
        logger.info("✓ Live-Update Task gestartet")
    else:
        logger.warning("Live-Update Task läuft bereits")


async def main():
    """Hauptfunktion"""
    try:
        await bot.start(DISCORD_BOT_TOKEN)
    except KeyboardInterrupt:
        logger.info("\n[SHUTDOWN] Bot wird beendet...")
    except Exception as e:
        logger.error(f"Fataler Fehler: {e}", exc_info=True)
    finally:
        if not bot.is_closed():
            await bot.close()
        logger.info("[SHUTDOWN] Bot beendet")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot gestoppt")
    except Exception as e:
        logger.error(f"Fataler Fehler: {e}", exc_info=True)
        sys.exit(1)
