# 🎯 Top Killer VIP Bot für Hell Let Loose

Automatischer Bot, der während eines Matches die Kills trackt und den **Top 3 Killern ohne VIP** automatisch **+24 Stunden VIP** vergibt.

## ✨ Features

- ✅ **Match-basierte Kill-Tracking**: Zählt Kills während eines laufenden Matches
- ✅ **Top 3 Belohnung**: Die besten 3 Killer **ohne VIP** bekommen automatisch +24h VIP
- ✅ **Multi-Server Support**: Überwacht bis zu 3 Server gleichzeitig
- ✅ **Discord Logs**: Sendet Benachrichtigungen über Match-Starts und VIP-Vergabe
- ✅ **Ingame-Nachrichten**: Belohnte Spieler erhalten eine PM im Spiel
- ✅ **PM2-Ready**: Einfaches Deployment und automatischer Restart
- ✅ **Graceful Shutdown**: Sauberes Beenden bei Systemsignalen

## 📋 Voraussetzungen

- **Python 3.8+** (empfohlen: Python 3.10+)
- **PM2** (Node.js Process Manager)
- **CRCON API Token** mit Admin-Rechten
- **Discord Webhook** (optional, aber empfohlen)

## 🚀 Installation

### 1. Repository klonen / Dateien herunterladen

```bash
cd "e:\Discord Bot\Top Killer VIP"
```

### 2. Python Dependencies installieren

```bash
pip install -r requirements.txt
```

### 3. Environment-Variablen konfigurieren

Kopiere `.env.example` zu `.env` und trage deine Werte ein:

```bash
copy .env.example .env
```

Bearbeite `.env`:

```env
CRCON_API_TOKEN=dein_api_token_hier
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/deine_webhook_url
SERVER1_URL=https://server1.example.com
SERVER2_URL=https://server2.example.com
SERVER3_URL=https://server3.example.com
```

**Wichtig:**
- Mindestens `SERVER1_URL` muss gesetzt sein
- Server ohne URL werden automatisch ignoriert
- Alle Server verwenden denselben API Token

### 4. PM2 installieren (falls nicht vorhanden)

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
python top_killer_vip.py
```

**Beenden:** `Strg + C`

## 📊 Funktionsweise

### 1. Match-Erkennung
Der Bot erkennt automatisch, wenn ein neues Match startet (Map-Wechsel).

### 2. Kill-Tracking
Während des Matches werden alle regulären Kills gezählt:
- ✅ Normale Kills zählen
- ❌ Teamkills werden **ignoriert**

### 3. Match-Ende
Beim Wechsel zur nächsten Map:
1. Bot ermittelt die Top 3 Killer
2. Prüft, welche davon **kein VIP** haben
3. Vergibt diesen Spielern **+24h VIP**
4. Sendet ihnen eine **Ingame-Nachricht**
5. Postet **Discord-Log** mit Ergebnissen

### 4. Discord-Benachrichtigungen

**Match-Start:**
```
🎮 Neues Match gestartet auf Server 1
Map: Carentan
```

**Match-Ende:**
```
🏆 Match beendet auf Server 1
Map: Carentan

Top 3 Killer ohne VIP erhalten +24h VIP:
✓ #1 SpielerName1 - 45 Kills
✓ #2 SpielerName2 - 38 Kills
✓ #3 SpielerName3 - 34 Kills

Top 10 Gesamt:
1. SpielerName1 - 45 Kills
2. SpielerName2 - 38 Kills
3. SpielerName3 - 34 Kills
4. SpielerMitVIP - 32 Kills 👑
...
```

## 📁 Verzeichnisstruktur

```
Top Killer VIP/
├── top_killer_vip.py       # Hauptscript
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

**Q: Bekommen Spieler mit VIP auch +24h?**  
A: Nein, nur Spieler **ohne VIP** bekommen die Belohnung.

**Q: Was passiert, wenn ein Top-Killer Lifetime-VIP hat?**  
A: Er wird übersprungen, der nächste Killer ohne VIP rückt nach.

**Q: Werden Teamkills gezählt?**  
A: Nein, nur reguläre Kills zählen für das Ranking.

**Q: Wie oft prüft der Bot auf neue Kills?**  
A: Alle 5 Sekunden werden die Logs abgefragt.

**Q: Was passiert bei Bot-Neustart während eines Matches?**  
A: Die Kills des aktuellen Matches gehen verloren. Der Bot startet die Zählung beim nächsten Match neu.

**Q: Kann ich die Top 3 auf Top 5 ändern?**  
A: Ja, in `top_killer_vip.py` Zeile 227 ändere `[:3]` zu `[:5]`.

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

- Prüfe, ob `DISCORD_WEBHOOK_URL` korrekt ist
- Teste den Webhook in Discord (Server Settings -> Integrations -> Webhooks)

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
