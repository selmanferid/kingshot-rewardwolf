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
- Rewardwolf logo added as favicon + dashboard/login logo
- UI rebranded: WLF GİFT PANEL (sidebar title), Daemon → Rewardwolf (labels)
- TWA (Telegram Web App) removed completely — twa.html, /twa route, Dockerfile entry all gone
- Logo sizes: login page → logo-1024.png, sidebar/navbar → logo-128.png

## Public API Endpoints (X-API-Key header required)
- `GET /api/public/dashboard` — overall stats
- `GET /api/public/codes` — all codes with delivered/success/failed counts
- `GET /api/public/codes/{code}` — single code detail
- `GET /api/public/player/{player_id}` — player redemption history

## Known Active Issues
- None at time of writing
