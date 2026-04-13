# Todos

## Potential Future Work
- Rate limiting on public API endpoints (per key, per minute)
- API key expiry option (optional time-limited keys)
- Worker/multi-instance consideration if ever needed for multiple games/servers
- Consider tightening CORS from allow_origins=["*"] for admin endpoints

## Done (recent)
- [x] Selenium → Playwright migration
- [x] Google Sheets sync disabled, Dashboard-managed players
- [x] Delivered count fix (ALREADY_USED = delivered)
- [x] Startup message simplified
- [x] Performance optimisations (6 items)
- [x] RAM optimisations (shm, browser args, font blocking)
- [x] API management: new endpoints, UI redesign, description field
- [x] Docs updated (README, MIMARI, GELISTIRICI_REHBERI, KURULUM_VE_BAKIM)
- [x] Rewardwolf logo added — favicon + login + sidebar/navbar
- [x] UI rebranded: WLF GİFT PANEL, Daemon → Rewardwolf labels
- [x] TWA (Telegram Web App) removed completely
- [x] New-code spam fix: notified column, one-time Telegram alert per code
- [x] Notification Channels: Telegram + Discord, per-event, custom templates, UI page
- [x] /chatid command + chat_id logging on every message
