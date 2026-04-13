# Pitfalls

## Browser Automation
- **Stylesheet blocking breaks the site:** ks-giftcode.centurygame.com Vue SPA uses CSS to control input visibility. Blocking stylesheets causes `input[placeholder="Player ID"]` to never become visible. Tested 2026-04-13.
- **Font blocking is safe:** Tested 2026-04-13, all selectors found normally.
- **networkidle is slow:** Use `domcontentloaded` + explicit `wait_for_selector` instead. networkidle waits 500ms of idle network which is wasteful on Vue SPAs.

## Memory / Development
- Do not rely on chat history as permanent memory — read memory/*.md files first at session start.
- Claude Code and Ollama chat are different environments.

## Docker
- `--disable-dev-shm-usage` is already set in browser args, so shm_size in docker-compose is irrelevant to Chromium. Set it to 64mb (Docker default).
- Host Chromium volumes must be mounted: /usr/bin/chromium, /usr/lib/chromium, /usr/lib/aarch64-linux-gnu

## API
- `ALREADY_USED` must count as delivered everywhere (daemon messages, API responses). Do not treat it as failure.

## Frontend (Web UI)
- All modals use `.open` CSS class. `closeModal(id)` removes 'open'. Never add 'active' to modal overlays.
- PAGES array and showPage() actions object must stay in sync when adding new pages.

## Notifications
- New code spam: `notified` flag in active_codes. Do NOT remove this guard — without it every 5-min check re-alerts.
- Discord channels: strip HTML before sending (no parse_mode support on webhooks).
- send_to_channels() silently skips rows with template format errors — check template variables match event kwargs.
