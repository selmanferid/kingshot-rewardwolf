# Current State

**Last updated:** 2026-04-19

## System Status
- Production running on Raspberry Pi 4 via Docker Compose
- Two containers: `kingshot-daemon` and `kingshot-web`

## Recent Changes
- v2.0.2 → v2.1.0 bump
- Selenium removed, Playwright is the browser automation layer
- Google Sheets player sync disabled — players managed via Dashboard only
- Delivered count fixed: ALREADY_USED now counts as delivered (SUCCESS + ALREADY_USED = delivered)
- Notification Channels system: multi-platform (Telegram + Discord), per-event toggles, custom templates
- Gift codes copyable in Telegram (`<pre>` block); Discord uses structured embeds + @everyone
- player_name_history table added; player modal shows name change history
- Code active status based solely on expires_at (future → active, past/null+inactive → expired)
- New player auto-distribution: newly added players trigger reset of completed active codes
- "Claim limit reached" → FAILED in parse_message()
- Automatic null-expiry refresh: refresh_null_expiries() runs every 5-min cycle
- Rewardwolf Control page overhauled: distribution status, trigger, manual add, uptime, message sender, system check, test-all-channels
- get_failed_players() retry logic: excludes SUCCESS, ALREADY_USED, INVALID_CODE, SERVER_BUSY
- /retry mid-distribution: saves as RETRY_PENDING, injected into running while loop; _dist_state["total"] bumped
- First-run new player detection bug fixed: _last_player_check_ts=None skips first cycle
- Log spam fixed: only log codes actually added to queue
- Distribution status + trigger dropdown: only shows is_currently_active=1 codes
- Distribution pause/resume/cancel/retry via daemon_control table (web↔daemon IPC)
  - Checked after each player sleep (~10min delay by design)
  - Pause: daemon enters 10s polling loop until resume/cancel
  - Cancel: loop breaks, remaining players stay FAILED for auto-retry
  - Retry: injects RETRY_PENDING players into running distribution loop
- Telegram commands: /pause, /resume, /cancel — context-aware replies, all English
- /dist command: shows PAUSED / Pause pending / Cancel pending states with hints
- /help reorganized: Info / Distribution / System sections, all English
- Distribution Status UI: Retry button (always visible) + Pause/Resume + Cancel (active dist only)

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
