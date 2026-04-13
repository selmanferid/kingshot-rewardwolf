# Current State

**Last updated:** 2026-04-13

## System Status
- Production running on Raspberry Pi 4 via Docker Compose
- Two containers: `kingshot-daemon` and `kingshot-web`

## Recent Changes (this session)
- v2.0.2 → v2.1.0 bump
- Selenium removed, Playwright is the browser automation layer
- Google Sheets player sync disabled — players managed via Dashboard only
- Delivered count fixed: ALREADY_USED now counts as delivered (SUCCESS + ALREADY_USED = delivered)
- Startup Telegram message simplified (inactive codes list removed)
- Performance optimisations applied (see decisions.md)
- RAM optimisations: shm_size 256mb→64mb, new browser args, font blocking added
- API management improved: new endpoints, UI redesign, description field on keys
- Rewardwolf logo added as favicon + dashboard/login logo (logo-1024.png login, logo-128.png sidebar)
- UI rebranded: WLF GİFT PANEL (sidebar title), Daemon → Rewardwolf (labels)
- TWA (Telegram Web App) removed completely
- New-code spam fix: `notified` column on active_codes — Telegram alert sent only once per code
- Notification Channels system: multi-platform (Telegram + Discord), per-event toggles, custom templates
- `/chatid` bot command added; every incoming message logs chat_id to daemon log

## Public API Endpoints (X-API-Key header required)
- `GET /api/public/dashboard` — overall stats (delivered = success + already_used)
- `GET /api/public/codes` — all codes with delivered/success/failed counts
- `GET /api/public/codes/{code}` — single code detail
- `GET /api/public/player/{player_id}` — player redemption history

## Notification Channel Events
- `new_code` — fired once per code when first discovered
- `dist_complete` — fired when full distribution run finishes
- `expiry_warning` — fired 72h before code expiry
- `daily_summary` — fired at midnight UTC

## Known Active Issues
- None at time of writing
