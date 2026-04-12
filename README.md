# 🐺 WLF Rewardwolf

Automated gift code redemption daemon for KingShot mobile game. Monitors new codes via API, redeems them for all alliance members using Playwright/Chromium, with Telegram bot control and a web dashboard. Built for Raspberry Pi 4.

---

## Features

- **Automatic redemption** — Monitors KingShot API for new gift codes and redeems them for all players with randomized intervals
- **Telegram bot** — Real-time notifications and control commands (`/status`, `/restart`, `/rebuild`, etc.)
- **Web dashboard** — Full management interface at your domain
- **Telegram Web App** — Native mobile-feel mini app accessible directly from Telegram
- **Player management** — Players managed entirely via the web dashboard (add, remove, VIP toggle)
- **Browser crash recovery** — Automatically restarts Chromium on crash and retries the same player
- **Retry mechanism** — Failed redemptions are retried after 2 hours
- **VIP players** — Priority processing for designated VIP members
- **Health monitoring** — CPU, RAM, temperature alerts via Telegram
- **Daily summary** — Automatic daily report sent to Telegram group

---

## Stack

| Component | Technology |
|-----------|-----------|
| Daemon | Python 3.11, Playwright |
| Web backend | FastAPI, SQLite |
| Web frontend | HTML/CSS/JS |
| Containerization | Docker, Docker Compose |
| Hardware | Raspberry Pi 4 |
| Notifications | Telegram Bot API |

---

## Project Structure

```
kingshot-rewardwolf/
├── kingshot_giftcode_daemon.py  # Main daemon
├── Dockerfile                   # Daemon container
├── docker-compose.yml           # Services definition
├── requirements.txt             # Daemon dependencies
├── rebuild.sh                   # Host rebuild script
├── rebuild_server.py            # Local HTTP server for rebuild triggers
├── .env.example                 # Environment variables template
└── web/
    ├── main.py                  # FastAPI backend
    ├── index.html               # Web dashboard
    ├── twa.html                 # Telegram Web App
    ├── Dockerfile               # Web container
    └── requirements.txt         # Web dependencies
```

---

## Setup

### Requirements

- Raspberry Pi 4 (4GB+ RAM recommended)
- Docker + Docker Compose
- Chromium installed on host (`sudo apt install chromium-browser`)
- Telegram bot token (via [@BotFather](https://t.me/BotFather))

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/kingshot-rewardwolf.git
cd kingshot-rewardwolf
```

### 2. Configure environment

```bash
cp .env.example .env
nano .env
```

Fill in all required values in `.env`.

### 3. Start rebuild server (on host)

```bash
nohup python3 rebuild_server.py > /dev/null 2>&1 &
```

Add to crontab for auto-start on reboot:
```bash
(crontab -l 2>/dev/null; echo "@reboot python3 /home/YOUR_USER/kingshot-rewardwolf/rebuild_server.py > /dev/null 2>&1 &") | crontab -
```

### 4. Build and run

```bash
docker compose up -d --build
```

---

## Telegram Bot Commands

| Command | Description |
|---------|-------------|
| `/status` | Daemon status and statistics |
| `/health` | CPU, RAM, temperature |
| `/dist` | Active distribution progress |
| `/players` | Player list |
| `/codes` | Active gift codes |
| `/logs` | Recent log entries |
| `/retry` | Retry failed redemptions |
| `/restart` | Restart daemon |
| `/rebuild` | Rebuild Docker image |
| `/help` | Command list |

---

## Web Dashboard

Accessible at your configured domain. Features:

- Live distribution status
- Player management (add, remove, VIP toggle, history)
- Code registry with per-code statistics
- Real-time log viewer
- Daemon controls (start, stop, restart, rebuild)
- Telegram message sender

---

## Telegram Web App

A mobile-optimized mini app accessible from Telegram. Configure via BotFather:

1. `/mybots` → select your bot
2. **Bot Settings** → **Menu Button** → **Configure menu button**
3. URL: `https://your.domain.com/twa`

---

## Environment Variables

See `.env.example` for all available configuration options.

| Variable | Description |
|----------|-------------|
| `KINGSHOT_API` | KingShot API base URL |
| `TELEGRAM_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Telegram group chat ID |
| `JWT_SECRET` | Web dashboard JWT secret |
| `ADMIN_USER` | Dashboard username |
| `ADMIN_PASS` | Dashboard password |
| `REBUILD_SERVER_URL` | Local rebuild server URL |
| `DOCKER_TCP_URL` | Docker TCP API URL |
| `DASHBOARD_URL` | Public dashboard URL |

---

## License

Private — WLF Alliance use only.
