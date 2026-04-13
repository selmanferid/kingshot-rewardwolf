# Decisions

## Architecture
- memory/*.md files are AI working memory; do not duplicate large architecture text, keep concise.
- Source of truth for architecture: MIMARI.md, GELISTIRICI_REHBERI.md, KURULUM_VE_BAKIM.md
- Browser automation: Playwright (not Selenium). Host Chromium binary mounted into container.
- Player management: Dashboard only (Google Sheets sync permanently disabled).

## Redemption Status Logic
- `ALREADY_USED` = player already has the reward → counts as **delivered** (not failed)
- `FAILED` = shown separately for bot success rate tracking
- `delivered` = `success + already_used` everywhere (daemon messages, API responses, UI)

## Performance Decisions
- 3 per-player DB queries replaced with in-memory `_dist_state` counters
- `wait_until="domcontentloaded"` instead of `networkidle` (saves 3-5s per player)
- Code expiry cached once before distribution loop (not re-queried per player)
- Exchange button uses `wait_for_function` instead of `time.sleep` polling loop
- SERVER_BUSY: no mid-retry Telegram message (reduces noise and rate limit risk)
- Blocked resource types: image, media, font (stylesheet must stay — Vue SPA breaks without it)
- Browser args: --disable-software-rasterizer, --disable-extensions, --disable-background-networking,
  --disable-sync, --no-first-run, --js-flags=--max-old-space-size=64
- shm_size: 256mb → 64mb (--disable-dev-shm-usage already set, /dev/shm unused by Chromium)

## API Design
- Public endpoints use `X-API-Key` header, keys stored in `api_keys` table with description
- `delivered` field always = success + already_used in all API responses
- New endpoints added: /api/public/codes/{code} and /api/public/player/{player_id}

## Notification Channels
- `notification_channels` table stores multi-platform channels (Telegram chat_id or Discord webhook URL)
- Per-event flags: ev_new_code, ev_dist_complete, ev_expiry_warning, ev_daily_summary
- Custom templates per event per channel; null = use DEFAULT_CHANNEL_TEMPLATES
- Template variables (Telegram only): {code_fmt}, {delivered}, {failed}, {total}, {hours}, {players}, {success}, {already_used}
- {code_fmt}: Telegram → `<pre>CODE</pre>` (code block, one-tap copy)
- Discord: uses `_build_discord_embed(event, **kwargs)` — structured embed per event type, NO string templates
  - new_code: gold embed, Code / Expires / Status fields + @everyone
  - dist_complete: green embed, Code / Delivered / Failed / Total fields
  - expiry_warning: red embed, Code / Remaining / Delivered fields + @everyone
  - daily_summary: blue embed, Players / Delivered / Failed fields
- `DISCORD_EVERYONE_EVENTS = {"new_code", "expiry_warning"}` — these add content: "@everyone"
- `send_to_channels(event, **kwargs)` routes Discord → embed, Telegram → string template
- Main new-code send_telegram() uses `<pre>CODE</pre>` block for one-tap copy

## New Code Spam Prevention
- `notified` column on `active_codes` (INTEGER DEFAULT 0)
- Migration sets notified=1 for all pre-existing codes on first run
- Telegram alert + send_to_channels("new_code") fires ONLY when notified=0, then sets notified=1
- Queue insertion guarded: only if code not already in queue AND not currently being distributed

## Chat ID Discovery
- Every incoming Telegram message logs: chat_type, chat name, chat_id, username, text
- `/chatid` command: bot replies with chat ID, type and name in that chat

## Pitfalls
- Do NOT block stylesheets on ks-giftcode.centurygame.com — Vue SPA hides input fields without CSS (tested 2026-04-13)
- Font blocking IS safe (tested same date)
- Do not rely on chat history as permanent memory — read these files first
- Modal open/close: all modals use `.open` class (not `.active`) — `closeModal()` removes 'open'
