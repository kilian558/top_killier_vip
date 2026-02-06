# 🎯 Top Killer VIP Bot für Hell Let Loose

Automatischer Discord Bot, der während eines Matches die Kills trackt mit **Live-Updates** und den **Top 5 Killern ohne VIP** automatisch **gestaffelte VIP-Belohnungen** vergibt.

## ✨ Features

- ✅ **Live Match-Tracking**: Echtzeit-Updates alle 30 Sekunden in Discord
- ✅ **Bearbeitbare Messages**: Eine Message pro Server, wird während des Matches aktualisiert
- ✅ **Top 5 Belohnung**: Die besten 5 Killer **ohne VIP** bekommen gestaffelte VIP-Zeiten:
  - 🥇 **Platz 1**: +72 Stunden VIP
  - 🥈 **Platz 2**: +48 Stunden VIP
  - 🥉 **Platz 3-5**: +24 Stunden VIP
- ✅ **Match-Ende Freeze**: Am Match-Ende wird die Message eingefroren mit finalen Ergebnissen
- ✅ **Multi-Server Support**: Überwacht bis zu 3 Server gleichzeitig
- ✅ **PM2-Ready**: Einfaches Deployment und automatischer Restart
- ✅ **Graceful Shutdown**: Sauberes Beenden bei Systemsignalen

## 📋 Voraussetzungen

- **Python 3.8+** (empfohlen: Python 3.10+)
- **PM2** (Node.js Process Manager)
- **CRCON API Token** mit Admin-Rechten
- **Discord Bot** (nicht Webhook!) mit folgenden Berechtigungen:
  - Send Messages
  - Embed Links
  - Read Message History

## 🚀 Installation

### 1. Repository klonen / Dateien herunterladen

```bash
cd "e:\Discord Bot\Top Killer VIP"
```

### 2. Python Dependencies installieren

```bash
pip install -r requirements.txt
```

### 3. Discord Bot erstellen

1. Gehe zu [Discord Developer Portal](https://discord.com/developers/applications)
2. Klicke auf "New Application"
3. Gib einen Namen ein (z.B. "Top Killer VIP")
4. Gehe zu "Bot" im linken Menü
5. Klicke auf "Add Bot"
6. Unter "TOKEN" klicke "Copy" (das ist dein `DISCORD_BOT_TOKEN`)
7. Aktiviere unter "Privileged Gateway Intents":
   - ✅ Message Content Intent
8. Gehe zu "OAuth2" → "URL Generator"
9. Wähle folgende Scopes:
   - `bot`
10. Wähle folgende Bot Permissions:
    - Send Messages
    - Embed Links
    - Read Message History
11. Kopiere die generierte URL und öffne sie im Browser
12. Wähle deinen Discord-Server und autorisiere den Bot

### 4. Channel ID ermitteln

1. Aktiviere in Discord den Developer Mode:
   - User Settings → Advanced → Developer Mode (aktivieren)
2. Rechtsklick auf den gewünschten Channel → "Copy ID"
3. Das ist deine `DISCORD_CHANNEL_ID`

### 5. Environment-Variablen konfigurieren

Kopiere `.env.example` zu `.env` und trage deine Werte ein:

```bash
copy .env.example .env
```

Bearbeite `.env`:

```env
CRCON_API_TOKEN=dein_api_token_hier
DISCORD_BOT_TOKEN=dein_bot_token_hier
DISCORD_CHANNEL_ID=1234567890123456789
SERVER1_URL=https://server1.example.com
SERVER2_URL=https://server2.example.com
SERVER3_URL=https://server3.example.com
```

**Wichtig:**
- Mindestens `SERVER1_URL` muss gesetzt sein
- Server ohne URL werden automatisch ignoriert
- Alle Server verwenden denselben API Token
- Bot-Token niemals öffentlich teilen!

### 6. PM2 installieren (falls nicht vorhanden)

```bash
npm install -g pm2
```

## 🎮 Verwendung

### Mit PM2 starten (empfohlen)

```bash
pm2 start ecosystem.config.js
```

### Weitere PM2-Befehle

```bash
# Status anzeigen
pm2 status

# Logs anzeigen (live)
pm2 logs top-killer-vip

# Logs anzeigen (letzten 100 Zeilen)
pm2 logs top-killer-vip --lines 100

# Bot stoppen
pm2 stop top-killer-vip

# Bot neustarten
pm2 restart top-killer-vip

# Bot löschen
pm2 delete top-killer-vip

# PM2 beim Systemstart aktivieren
pm2 startup
pm2 save
```

### Manueller Start (ohne PM2)

```bash
python top_killer_vip_bot.py
```

**Beenden:** `Strg + C`

## 📊 Funktionsweise

### 1. Match-Erkennung
Der Bot erkennt automatisch, wenn ein neues Match startet (Map-Wechsel).

### 2. Live Kill-Tracking
- **Alle 30 Sekunden** wird die Discord-Message mit aktuellen Stats aktualisiert
- Eine Message pro Server wird **während des Matches bearbeitet**
- Zeigt **Top 10 Killer in Echtzeit**
- Teamkills werden **ignoriert**

### 3. Match-Ende
Beim Wechsel zur nächsten Map:
1. Bot ermittelt die Top 5 Killer
2. Prüft, welche davon **kein VIP** haben
3. Vergibt diesen Spielern **gestaffelte VIP-Zeiten**:
   - 🥇 Platz 1: +72 Stunden
   - 🥈 Platz 2: +48 Stunden
   - 🥉 Platz 3-5: +24 Stunden
4. **"Freezed" die Message** mit finalen Ergebnissen
5. Erstellt **neue Message** für das nächste Match

### 4. Discord Live-Updates

**Während des Matches (wird alle 30 Sek. bearbeitet):**
```
🎯 Live Match Stats - Server 1
Map: carentan_warfare
Match Start: vor 25 Minuten

Top 10 Killer:
🥇 SpielerName1 - 42 Kills
🥈 SpielerName2 - 35 Kills
🥉 SpielerName3 - 31 Kills
▫️ SpielerName4 - 28 Kills
...

🔄 Auto-Update alle 30 Sekunden
```

**Match-Ende (eingefrorene finale Message):**
```
🏆 Match beendet - Server 1
Map: carentan_warfare

🎁 VIP Belohnungen vergeben:
🥇 Platz 1: +72 Stunden | 🥈 Platz 2: +48 Stunden | 🥉 Platz 3-5: +24 Stunden

✓ 🥇 SpielerName1 - 45 Kills → +72h VIP
✓ 🥈 SpielerName2 - 38 Kills → +48h VIP
✓ 🥉 SpielerName3 - 34 Kills → +24h VIP
✓ 4️⃣ SpielerName4 - 30 Kills → +24h VIP
✓ 5️⃣ SpielerName5 - 28 Kills → +24h VIP

📊 Top 10 Gesamt:
1. SpielerName1 - 45 Kills
2. SpielerName2 - 38 Kills
3. SpielerName3 - 34 Kills
4. SpielerName4 - 30 Kills
5. SpielerName5 - 28 Kills
6. SpielerMitVIP - 26 Kills 👑
...

Match abgeschlossen
```

## 📁 Verzeichnisstruktur

```
Top Killer VIP/
├── top_killer_vip_bot.py  # Hauptscript (Discord Bot)
├── top_killer_vip.py       # Legacy Webhook-Version
├── ecosystem.config.js     # PM2-Konfiguration
├── requirements.txt        # Python-Dependencies
├── .env                    # Deine Konfiguration (NICHT committen!)
├── .env.example            # Template für .env
├── logs/                   # PM2-Logs (wird automatisch erstellt)
│   ├── error.log
│   └── output.log
└── README.md               # Diese Datei
```

## 🔧 Konfiguration

### Server hinzufügen/entfernen

In der `.env`:
- Server ohne URL werden automatisch übersprungen
- Du kannst 1-3 Server konfigurieren
- Alle verwenden denselben API Token

### Logging anpassen

Im Script `top_killer_vip.py`, Zeile 23-28:
```python
logging.basicConfig(
    level=logging.INFO,  # Ändere zu DEBUG für mehr Details
    ...
)
```

## ❓ FAQ

**Q: Wie oft werden die Live-Updates aktualisiert?**  
A: Alle 30 Sekunden wird die Message mit den aktuellen Stats bearbeitet.

**Q: Was passiert mit der Message am Match-Ende?**  
A: Sie wird "eingefroren" mit den finalen Ergebnissen und eine neue Message startet für das nächste Match.

**Q: Bekommen Spieler mit VIP auch VIP-Verlängerung?**  
A: Nein, nur Spieler **ohne VIP** bekommen die Belohnung.

**Q: Was passiert, wenn ein Top-Killer Lifetime-VIP hat?**  
A: Er wird übersprungen, der nächste Killer ohne VIP rückt nach.

**Q: Wie sind die VIP-Zeiten gestaffelt?**  
A: Platz 1 erhält 72h, Platz 2 erhält 48h, Plätze 3-5 erhalten jeweils 24h VIP.

**Q: Werden Teamkills gezählt?**  
A: Nein, nur reguläre Kills zählen für das Ranking.

**Q: Wie oft prüft der Bot auf neue Kills?**  
A: Alle 5 Sekunden werden die Logs abgefragt.

**Q: Was passiert bei Bot-Neustart während eines Matches?**  
A: Die Kills des aktuellen Matches gehen verloren. Der Bot startet die Zählung beim nächsten Match neu.

**Q: Kann ich die VIP-Zeiten anpassen?**  
A: Ja, in `top_killer_vip.py` in der Funktion `process_match_end()` kannst du das Dictionary `vip_hours` anpassen (z.B. `{1: 96, 2: 72, 3: 48, 4: 24, 5: 24}`).

## 🐛 Troubleshooting

### Bot startet nicht

```bash
# Prüfe Logs
pm2 logs top-killer-vip --lines 50

# Prüfe Python-Version
python --version  # Sollte 3.8+ sein

# Teste manuell
python top_killer_vip.py
```

### "CRCON_API_TOKEN nicht gesetzt"

- Stelle sicher, dass `.env` existiert (nicht `.env.example`!)
- Prüfe, dass der Token korrekt eingefügt wurde (keine Leerzeichen)

### "Keine Server-URLs konfiguriert"

- Mindestens `SERVER1_URL` muss in `.env` gesetzt sein

### Discord-Logs kommen nicht an

- Prüfe, ob `DISCORD_BOT_TOKEN` korrekt ist
- Stelle sicher, dass der Bot im Server ist und Berechtigungen hat
- Prüfe, ob die `DISCORD_CHANNEL_ID` korrekt ist
- Teste mit: Rechtsklick auf Channel → Copy ID

### Bot ist offline/antwortet nicht

- Prüfe `pm2 status` - Bot sollte "online" sein
- Schaue in die Logs: `pm2 logs top-killer-vip`
- Stelle sicher, dass der Bot den Channel sehen kann (Berechtigungen)

### VIP wird nicht vergeben

- Prüfe, ob der API Token Admin-Rechte hat
- Schaue in die Logs: `pm2 logs top-killer-vip`
- Teste manuell im CRCON-Interface

## 📝 Lizenz

Dieses Projekt ist frei verfügbar für private und kommerzielle Nutzung.

## 🤝 Support

Bei Problemen oder Fragen:
1. Prüfe die Logs: `pm2 logs top-killer-vip`
2. Schaue in die FAQ
3. Erstelle ein Issue im Repository

---

**Viel Erfolg mit deinem Top Killer VIP Bot! 🎯**
