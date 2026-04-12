# Project

**Name:** WLF Rewardwolf  
**Version:** v2.1.0  
**Repo:** https://github.com/selmanferid/kingshot-rewardwolf

## Purpose
- Monitor newly published KingShot gift codes via API
- Redeem them for all alliance members automatically
- Provide Telegram bot control and web dashboard management

## Main Components
- **Core daemon:** `kingshot_giftcode_daemon.py` — Playwright/Chromium, SQLite, Telegram
- **Web backend:** `web/main.py` — FastAPI, JWT auth, public API with API keys
- **Web frontend:** `web/index.html` — SPA dashboard (branded: WLF GİFT PANEL)
- **Rebuild server:** `rebuild_server.py` — host-side HTTP server for Docker ops
- **Database:** SQLite WAL mode at `/app/data/kingshot.db`

## Core Integrations
- KingShot API (gift code monitoring)
- Telegram Bot API (notifications + commands)
- Public REST API (external bots via API key)

## Deployment
- Raspberry Pi 4 (ARM64)
- Docker / Docker Compose
- Host Chromium binary mounted read-only into daemon container

## Key Tables (SQLite)
- `players` — player list with VIP, role, soft-delete
- `redemptions` — per-player-per-code results (SUCCESS, ALREADY_USED, FAILED, etc.)
- `active_codes` — tracked gift codes with stats
- `api_keys` — external API access keys with name/description/last_used
- `expiry_warnings` — tracks which expiry warnings have been sent
