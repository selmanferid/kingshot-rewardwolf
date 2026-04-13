# CLAUDE.md — WLF Rewardwolf Project Guidelines

## Sensitive Data Policy

**Tokens, IP addresses, chat IDs, webhook URLs, API keys → always in `.env`, never in MD or memory files.**

Specifically, never write these into any `.md`, memory file, or code comment:
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`
- Discord webhook URLs
- `ADMIN_PASS`, `JWT_SECRET`
- Internal network IPs (e.g. Uptime Kuma address)
- Any `API_KEY` values

If a value is needed as an example in documentation, use a placeholder: `your_token_here`, `<CHAT_ID>`, etc.

## Environment Variables

All runtime secrets live in `/home/selman/kingshot/.env` (Docker Compose loads it automatically).
The `.env` file is git-ignored. Never commit it.

## Project Stack

- **Daemon:** Python 3.11 + Playwright (browser automation), SQLite (WAL mode)
- **Web:** FastAPI + Vue-style SPA, JWT auth
- **Runtime:** Docker Compose on Raspberry Pi 4 (ARM64)
- **Notifications:** Telegram Bot API (HTML parse_mode) + Discord webhooks (embeds)

## Code Conventions

- Discord notifications use `_build_discord_embed()` — structured embeds, NOT string templates
- Telegram notifications use HTML parse_mode; codes use `<pre>CODE</pre>` for one-tap copy
- `send_to_channels(event, **kwargs)` routes platform-specific formatting automatically
- `{code_fmt}` in Telegram templates → `<pre>CODE</pre>`; in Discord → handled by embed builder

## Container Names

- `kingshot-daemon` — main automation daemon
- `kingshot-web` — FastAPI dashboard (port 8000)
