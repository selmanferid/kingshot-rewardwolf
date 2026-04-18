"""
WLF Rewardwolf — Gift Code Daemon v2.1.0
============================================
- Monitors Kingshot API for new gift codes
- Redeems codes for all players via Playwright/Chromium (randomized intervals)
- Players managed via web dashboard (no Google Sheets dependency)
- VIP player priority processing
- Optimized SQLite database with WAL mode and bulk lookups
- Telegram bot with instant command responses (separate thread)
- RAM/CPU/temperature monitoring with alerts
- Browser fingerprint randomization (user-agent, viewport, language)
- Retry mechanism for failed redemptions
- Browser crash recovery with auto-restart
- 72-hour expiry warnings
- Daily summary report
"""

import os
import re
import sys
import time
import json
import random
import logging
import sqlite3
import threading
import queue
import requests
import subprocess
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

# ============================================================
#  CONFIG
# ============================================================
CONFIG = {
    "KINGSHOT_API":          os.getenv("KINGSHOT_API", "https://kingshot.net/api"),
    "REBUILD_SERVER_URL":    os.getenv("REBUILD_SERVER_URL", "http://192.168.1.36:9999"),
    "DASHBOARD_URL":         os.getenv("DASHBOARD_URL", "https://gift.ks-wolfpack.com"),
    "SHEETS_WEB_APP_URL":    os.getenv("SHEETS_WEB_APP_URL", ""),
    "CHECK_INTERVAL_MIN":    int(os.getenv("CHECK_INTERVAL_MIN", "5")),
    "HEADLESS":              os.getenv("HEADLESS", "true").lower() == "true",
    "LOG_FILE":              "/app/data/kingshot_daemon.log",
    "DB_FILE":               "/app/data/kingshot.db",
    "TELEGRAM_TOKEN":        os.getenv("TELEGRAM_TOKEN", ""),
    "TELEGRAM_CHAT_ID":      os.getenv("TELEGRAM_CHAT_ID", ""),
    "RETRY_DELAY_HOURS":     2,
    "EXPIRY_WARNING_HOURS":  72,
    "CPU_ALERT_THRESHOLD":   80,
    "RAM_ALERT_THRESHOLD":   85,
    "TEMP_ALERT_THRESHOLD":  75,
}

# ============================================================
#  LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(CONFIG["LOG_FILE"], encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ============================================================
#  GLOBAL STATE
# ============================================================
_daemon_start_time = datetime.now(timezone.utc)
_is_first_run = True
_cached_players = []
_telegram_offset = 0
_code_queue = queue.Queue()  # Yeni kodlar için kuyruk
_last_summary_date = None
_last_health_alert = {}
_last_name_sync        = None
_last_player_check_ts  = None  # Yeni oyuncu tespiti için

# Active distribution state (for web UI and /status command)
_dist_state = {
    "active": False,
    "paused": False,
    "cancelled": False,
    "code": None,
    "current_player": None,
    "current_index": 0,
    "total": 0,
    "success": 0,
    "already_used": 0,
    "failed": 0,
    "skipped": 0,
    "started_at": None,
}

# ============================================================
#  USER AGENTS & FINGERPRINTS
# ============================================================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]
SCREEN_SIZES = ["1280,800", "1920,1080", "1366,768", "1440,900", "1600,900"]
LANGUAGES = ["en-US,en;q=0.9", "en-GB,en;q=0.9", "tr-TR,tr;q=0.9,en;q=0.8"]

# ============================================================
#  TELEGRAM
# ============================================================
def send_telegram(message, chat_id=None):
    if not CONFIG["TELEGRAM_TOKEN"]:
        return
    target = chat_id or CONFIG["TELEGRAM_CHAT_ID"]
    if not target:
        return
    try:
        url = f"https://api.telegram.org/bot{CONFIG['TELEGRAM_TOKEN']}/sendMessage"
        requests.post(url, json={
            "chat_id": target,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        log.warning(f"Telegram send error: {e}")

# ── Notification Channels ────────────────────────────────────
# {code_fmt} → platform'a göre kopyalanabilir kod formatı
# Telegram: <pre>WEEKENDPLAN</pre>  |  Discord: `WEEKENDPLAN`
DEFAULT_CHANNEL_TEMPLATES = {
    "new_code":       "🎉 New Gift Code Found!\n{code_fmt}\n🔄 Queued for distribution...",
    "dist_complete":  "✅ Distribution Complete!\n🎁 Code: {code_fmt}\n\n✅ Delivered: {delivered}\n❌ Failed: {failed}\n👥 Total: {total}",
    "expiry_warning": "⏰ Gift Code Expiring!\n🎁 Code: {code_fmt}\n⏱ {hours}h remaining\n📊 {delivered}/{total} delivered",
    "daily_summary":  "📅 Daily Summary\n👥 Players: {players}\n✅ Delivered: {delivered}\n❌ Failed: {failed}",
}

# Discord events that should ping @everyone
DISCORD_EVERYONE_EVENTS = {"new_code", "expiry_warning"}

def _build_discord_embed(event: str, **kwargs) -> dict:
    """Event türüne göre Discord embed payload'u oluşturur."""
    code     = kwargs.get("code", "")
    code_fmt = f"```\n{code}\n```" if code else ""

    if event == "new_code":
        expires_val = kwargs.get("expires", "No expiry")
        return {
            "embeds": [{
                "title": "🎁 New Gift Code Available!",
                "color": 16766720,  # gold
                "fields": [
                    {"name": "Code",    "value": code_fmt,                        "inline": False},
                    {"name": "Expires", "value": str(expires_val),                "inline": True},
                    {"name": "Status",  "value": "🔄 Distribution in progress...", "inline": True},
                ],
                "footer": {"text": "WLF Bot • Powered by Rewardwolf"},
            }]
        }

    if event == "dist_complete":
        return {
            "embeds": [{
                "title": "✅ Distribution Complete!",
                "color": 5763719,  # green
                "fields": [
                    {"name": "Code",      "value": code_fmt,                      "inline": False},
                    {"name": "✅ Delivered", "value": str(kwargs.get("delivered", 0)), "inline": True},
                    {"name": "❌ Failed",    "value": str(kwargs.get("failed", 0)),    "inline": True},
                    {"name": "👥 Total",     "value": str(kwargs.get("total", 0)),     "inline": True},
                ],
                "footer": {"text": "WLF Bot • Powered by Rewardwolf"},
            }]
        }

    if event == "expiry_warning":
        return {
            "embeds": [{
                "title": "⏰ Gift Code Expiring Soon!",
                "color": 15548997,  # red
                "fields": [
                    {"name": "Code",        "value": code_fmt,                                              "inline": False},
                    {"name": "⏱ Remaining", "value": f"{kwargs.get('hours', '?')}h",                       "inline": True},
                    {"name": "📊 Delivered", "value": f"{kwargs.get('delivered', 0)}/{kwargs.get('total', 0)}", "inline": True},
                ],
                "footer": {"text": "WLF Bot • Powered by Rewardwolf"},
            }]
        }

    if event == "daily_summary":
        return {
            "embeds": [{
                "title": "📅 Daily Summary",
                "color": 5793266,  # blue
                "fields": [
                    {"name": "👥 Players",    "value": str(kwargs.get("players", 0)),   "inline": True},
                    {"name": "✅ Delivered",  "value": str(kwargs.get("delivered", 0)), "inline": True},
                    {"name": "❌ Failed",     "value": str(kwargs.get("failed", 0)),    "inline": True},
                ],
                "footer": {"text": "WLF Bot • Powered by Rewardwolf"},
            }]
        }

    # Bilinmeyen event — fallback plain text
    return {"content": f"[{event}] " + " ".join(f"{k}={v}" for k, v in kwargs.items())}

def _send_discord(webhook_url: str, payload: dict):
    """Discord webhook'a embed payload gönderir."""
    try:
        requests.post(webhook_url, json=payload, timeout=10)
    except Exception as e:
        log.warning(f"Discord send error: {e}")

def send_to_channels(event: str, **kwargs):
    """Tüm aktif notification channel'larına event mesajı gönder."""
    ev_col  = f"ev_{event}"
    tpl_col = f"tpl_{event}"
    try:
        conn = db_connect()
        rows = conn.execute(f"""
            SELECT platform, target, {tpl_col} as template
            FROM notification_channels
            WHERE enabled=1 AND {ev_col}=1
        """).fetchall()
        conn.close()
    except Exception as e:
        log.warning(f"send_to_channels DB error: {e}")
        return

    default_tpl = DEFAULT_CHANNEL_TEMPLATES.get(event, "")
    for row in rows:
        platform = row["platform"]

        if platform == "discord":
            payload = _build_discord_embed(event, **kwargs)
            if event in DISCORD_EVERYONE_EVENTS:
                payload["content"] = "@everyone"
            _send_discord(row["target"], payload)

        elif platform == "telegram":
            tpl = row["template"] or default_tpl
            platform_kwargs = dict(kwargs)
            platform_kwargs["code_fmt"] = f"<pre>{kwargs.get('code', '')}</pre>"
            try:
                message = tpl.format(**platform_kwargs)
            except (KeyError, ValueError) as e:
                log.warning(f"Channel template error [{event}]: {e} — using default")
                try:
                    message = default_tpl.format(**platform_kwargs)
                except Exception:
                    continue
            send_telegram(message, row["target"])

def get_telegram_updates():
    global _telegram_offset
    if not CONFIG["TELEGRAM_TOKEN"]:
        return []
    try:
        url = f"https://api.telegram.org/bot{CONFIG['TELEGRAM_TOKEN']}/getUpdates"
        resp = requests.get(url, params={"offset": _telegram_offset, "timeout": 2}, timeout=5)
        data = resp.json()
        updates = data.get("result", [])
        if updates:
            _telegram_offset = updates[-1]["update_id"] + 1
        return updates
    except Exception:
        return []

def init_telegram_offset():
    """Başlangıçta eski mesajları atla — sadece yeni komutları dinle."""
    global _telegram_offset
    if not CONFIG["TELEGRAM_TOKEN"]:
        return
    try:
        url = f"https://api.telegram.org/bot{CONFIG['TELEGRAM_TOKEN']}/getUpdates"
        resp = requests.get(url, params={"offset": -1, "timeout": 1}, timeout=5)
        data = resp.json()
        updates = data.get("result", [])
        if updates:
            _telegram_offset = updates[-1]["update_id"] + 1
    except Exception:
        pass

# ============================================================
#  DATABASE
# ============================================================
def init_db():
    conn = sqlite3.connect(CONFIG["DB_FILE"])
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Players table — single source of truth for all players
    c.execute("""
        CREATE TABLE IF NOT EXISTS players (
            player_id    TEXT PRIMARY KEY,
            username     TEXT,
            is_vip       INTEGER DEFAULT 0,
            role         TEXT DEFAULT 'R1',
            active_since TEXT NOT NULL,
            removed_at   TEXT
        )
    """)
    # Mevcut DB'ye role kolonu ekle (zaten varsa hata vermez)
    try:
        c.execute("ALTER TABLE players ADD COLUMN role TEXT DEFAULT 'R1'")
        conn.commit()
        log.info("✅ 'role' column added to players table.")
    except sqlite3.OperationalError:
        pass  # Kolon zaten var

    # Redemptions — optimized with index
    c.execute("""
        CREATE TABLE IF NOT EXISTS redemptions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT NOT NULL,
            player_id   TEXT NOT NULL,
            username    TEXT,
            status      TEXT NOT NULL,
            message     TEXT,
            retry_count INTEGER DEFAULT 0,
            created_at  TEXT NOT NULL,
            UNIQUE(code, player_id)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_redemptions_code ON redemptions(code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_redemptions_player ON redemptions(player_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_redemptions_status ON redemptions(code, status)")

    # Active codes cache
    c.execute("""
        CREATE TABLE IF NOT EXISTS active_codes (
            code             TEXT PRIMARY KEY,
            created_at       TEXT,
            expires_at       TEXT,
            is_currently_active INTEGER DEFAULT 1,
            is_completed     INTEGER DEFAULT 0,
            total            INTEGER DEFAULT 0,
            success          INTEGER DEFAULT 0,
            already_used     INTEGER DEFAULT 0,
            failed           INTEGER DEFAULT 0,
            last_updated     TEXT,
            player_count     INTEGER DEFAULT 0
        )
    """)
    # Migration: mevcut DB'ye player_count ve notified kolonlarını ekle
    for col, definition in [
        ("player_count", "INTEGER DEFAULT 0"),
        ("notified",     "INTEGER DEFAULT 0"),
    ]:
        try:
            c.execute(f"ALTER TABLE active_codes ADD COLUMN {col} {definition}")
            conn.commit()
            log.info(f"✅ '{col}' column added to active_codes table.")
            if col == "notified":
                # Mevcut (migration öncesi) tüm kodları bildirilmiş say — spam önleme
                c.execute("UPDATE active_codes SET notified=1")
                conn.commit()
                log.info("✅ Existing codes marked as notified (spam prevention).")
        except sqlite3.OperationalError:
            pass  # Kolon zaten var

    # Notification channels tablosu
    c.execute("""
        CREATE TABLE IF NOT EXISTS notification_channels (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            name                TEXT NOT NULL,
            platform            TEXT NOT NULL DEFAULT 'telegram',
            target              TEXT NOT NULL,
            enabled             INTEGER DEFAULT 1,
            ev_new_code         INTEGER DEFAULT 1,
            ev_dist_complete    INTEGER DEFAULT 1,
            ev_expiry_warning   INTEGER DEFAULT 1,
            ev_daily_summary    INTEGER DEFAULT 0,
            tpl_new_code        TEXT,
            tpl_dist_complete   TEXT,
            tpl_expiry_warning  TEXT,
            tpl_daily_summary   TEXT,
            created_at          TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS expiry_warnings (
            code      TEXT PRIMARY KEY,
            warned_at TEXT NOT NULL
        )
    """)

    # Player name history — eski isimleri kaydeder
    c.execute("""
        CREATE TABLE IF NOT EXISTS player_name_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id   TEXT NOT NULL,
            username    TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_name_history_player ON player_name_history(player_id)")

    # Daemon control — web ↔ daemon iletişimi (pause/resume/cancel)
    c.execute("""
        CREATE TABLE IF NOT EXISTS daemon_control (
            key        TEXT PRIMARY KEY,
            value      TEXT,
            updated_at TEXT
        )
    """)
    # Varsayılan kontrol kayıtları
    c.execute("INSERT OR IGNORE INTO daemon_control (key, value, updated_at) VALUES ('dist_cmd', '', '')")
    c.execute("INSERT OR IGNORE INTO daemon_control (key, value, updated_at) VALUES ('dist_paused', '0', '')")

    conn.commit()
    conn.close()
    log.info("✅ Database initialized.")

def db_connect():
    conn = sqlite3.connect(CONFIG["DB_FILE"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def ctrl_get(key: str) -> str:
    """daemon_control tablosundan değer oku."""
    conn = db_connect()
    row = conn.execute("SELECT value FROM daemon_control WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else ""

def ctrl_set(key: str, value: str):
    """daemon_control tablosuna değer yaz."""
    conn = db_connect()
    conn.execute(
        "INSERT OR REPLACE INTO daemon_control (key, value, updated_at) VALUES (?, ?, ?)",
        (key, value, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()

# ============================================================
#  PLAYER SYNC
# ============================================================
def sync_players(sheet_players):
    """
    Sync player list from Sheets to DB.
    - New players: insert
    - Removed players: soft-delete (set removed_at)
    - Returned players: clear removed_at
    """
    conn = db_connect()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()

    # Get current DB state
    c.execute("SELECT player_id, username, is_vip, removed_at FROM players")
    db_players = {row["player_id"]: dict(row) for row in c.fetchall()}

    sheet_ids = {p["playerId"] for p in sheet_players}
    db_ids = set(db_players.keys())

    added = []
    removed = []
    restored = []

    vip_promoted = []
    vip_demoted = []

    # New players
    for p in sheet_players:
        pid = p["playerId"]
        uname = p.get("username", "")
        is_vip = 1 if p.get("is_vip") else 0
        if pid not in db_ids:
            c.execute("""
                INSERT OR IGNORE INTO players (player_id, username, is_vip, active_since)
                VALUES (?, ?, ?, ?)
            """, (pid, uname, is_vip, now))
            added.append(p)
        else:
            # Update username, restore if previously removed
            if db_players[pid]["removed_at"] is not None:
                c.execute("UPDATE players SET removed_at=NULL, username=?, is_vip=? WHERE player_id=?", (uname, is_vip, pid))
                restored.append(p)
            else:
                # Check VIP status change
                old_vip = db_players[pid].get("is_vip", 0)
                if old_vip != is_vip:
                    if is_vip:
                        vip_promoted.append(uname or pid)
                    else:
                        vip_demoted.append(uname or pid)
                c.execute("UPDATE players SET username=?, is_vip=? WHERE player_id=?", (uname, is_vip, pid))

    # Removed players (soft delete)
    for pid in db_ids - sheet_ids:
        if db_players[pid]["removed_at"] is None:
            c.execute("UPDATE players SET removed_at=? WHERE player_id=?", (now, pid))
            c.execute("SELECT username FROM players WHERE player_id=?", (pid,))
            row = c.fetchone()
            removed.append({"playerId": pid, "username": row["username"] if row else pid})

    conn.commit()
    conn.close()

    if added:
        log.info(f"🆕 {len(added)} new player(s) added: {[p.get('username') or p['playerId'] for p in added]}")
    if removed:
        log.info(f"🗑️ {len(removed)} player(s) removed: {[p.get('username') or p['playerId'] for p in removed]}")
        send_telegram(
            f"🗑️ <b>{len(removed)} player(s) removed from list:</b>\n"
            + "\n".join(f"• {p.get('username') or p['playerId']}" for p in removed)
        )
    if restored:
        log.info(f"♻️ {len(restored)} player(s) restored: {[p.get('username') or p['playerId'] for p in restored]}")
    if vip_promoted:
        log.info(f"⭐ VIP promoted: {vip_promoted}")
        send_telegram(f"⭐ <b>VIP promoted:</b>\n" + "\n".join(f"• {n}" for n in vip_promoted))
    if vip_demoted:
        log.info(f"🔽 VIP demoted: {vip_demoted}")
        send_telegram(f"🔽 <b>VIP removed:</b>\n" + "\n".join(f"• {n}" for n in vip_demoted))

    return added, removed, restored, vip_promoted, vip_demoted

def get_active_players():
    """Get all active (non-removed) players from DB — VIP > R5..R1 > alphabetical."""
    conn = db_connect()
    c = conn.cursor()
    c.execute("""
        SELECT player_id, username, is_vip, role
        FROM players
        WHERE removed_at IS NULL
        ORDER BY is_vip DESC, role DESC, username ASC
    """)
    rows = c.fetchall()
    conn.close()
    return [
        {"playerId": r["player_id"], "username": r["username"],
         "is_vip": r["is_vip"], "role": r["role"] or "R1"}
        for r in rows
    ]

def get_vip_player_ids():
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT player_id FROM players WHERE is_vip=1 AND removed_at IS NULL")
    ids = {r["player_id"] for r in c.fetchall()}
    conn.close()
    return ids

# ============================================================
#  BULK REDEMPTION STATUS (single query per code)
# ============================================================
def get_code_status_map(code):
    """
    Returns a dict {player_id: status} for a given code.
    Single DB query instead of one per player.
    """
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT player_id, status FROM redemptions WHERE code=?", (code,))
    result = {row["player_id"]: row["status"] for row in c.fetchall()}
    conn.close()
    return result

def save_redemption(code, player_id, username, status, message, retry_count=0):
    conn = db_connect()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO redemptions (code, player_id, username, status, message, retry_count, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (code, player_id, username, status, message, retry_count,
          datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()

def get_failed_players(code, ignore_delay=False):
    """
    SUCCESS ve ALREADY_USED dışındaki tüm statüleri retry kuyruğuna alır.
    INVALID_CODE hariç — kodun kendisi geçersiz, retry işe yaramaz.
    ignore_delay=True → manuel /retry için zaman kısıtlaması yok.
    """
    conn = db_connect()
    c = conn.cursor()
    if ignore_delay:
        c.execute("""
            SELECT player_id, username, retry_count FROM redemptions
            WHERE code=?
              AND status NOT IN ('SUCCESS', 'ALREADY_USED', 'INVALID_CODE', 'SERVER_BUSY')
              AND retry_count < 3
        """, (code,))
    else:
        retry_after = (datetime.now(timezone.utc) - timedelta(hours=CONFIG["RETRY_DELAY_HOURS"])).isoformat()
        c.execute("""
            SELECT player_id, username, retry_count FROM redemptions
            WHERE code=?
              AND status NOT IN ('SUCCESS', 'ALREADY_USED', 'INVALID_CODE', 'SERVER_BUSY')
              AND created_at <= ?
              AND retry_count < 3
        """, (code, retry_after))
    rows = c.fetchall()
    conn.close()
    return [(r["player_id"], r["username"], r["retry_count"]) for r in rows]

# ============================================================
#  ACTIVE CODES CACHE
# ============================================================
def sync_active_codes(api_codes_data):
    """
    Sync active codes from API to DB.
    - New codes: insert
    - Codes present in API: mark is_currently_active=1
    - Codes missing from API: mark is_currently_active=0 (may reactivate later)
    - Reactivated codes: restore is_currently_active=1, reset is_completed=0
      so missing players get the code again
    """
    conn = db_connect()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    api_codes = {d["code"]: d for d in api_codes_data}

    # Get current DB state
    c.execute("SELECT code, is_currently_active, is_completed FROM active_codes")
    db_codes = {row["code"]: row for row in c.fetchall()}

    for code, code_data in api_codes.items():
        if code not in db_codes:
            # Brand new code
            c.execute("""
                INSERT OR IGNORE INTO active_codes (code, created_at, expires_at, is_currently_active, last_updated)
                VALUES (?, ?, ?, 1, ?)
            """, (code, code_data.get("createdAt"), code_data.get("expiresAt"), now))
            log.info(f"🆕 New code added to DB: {code}")
        else:
            existing = db_codes[code]
            new_expiry = code_data.get("expiresAt")
            if existing["is_currently_active"] == 0:
                # Reactivated — reset completed so missing players get it
                log.info(f"♻️ Code reactivated: {code} — resetting completed status")
                c.execute("""
                    UPDATE active_codes
                    SET is_currently_active=1, is_completed=0,
                        expires_at = CASE WHEN ? IS NOT NULL THEN ? ELSE expires_at END,
                        last_updated=?
                    WHERE code=?
                """, (new_expiry, new_expiry, now, code))
            else:
                # Update expiry only if API provides a non-null value (never overwrite with null)
                if new_expiry:
                    c.execute("""
                        UPDATE active_codes SET expires_at=?, last_updated=? WHERE code=?
                    """, (new_expiry, now, code))
                else:
                    c.execute("UPDATE active_codes SET last_updated=? WHERE code=?", (now, code))

    # Mark codes not in API as inactive
    # expires_at IS NULL olanlar için şu anki zamanı expiry olarak kaydet
    for code in db_codes:
        if code not in api_codes:
            c.execute("""
                UPDATE active_codes
                SET is_currently_active=0,
                    expires_at = CASE WHEN expires_at IS NULL THEN ? ELSE expires_at END,
                    last_updated=?
                WHERE code=?
            """, (now, now, code))

    conn.commit()
    conn.close()

def is_code_completed(code):
    """A code is 'done' only if it's currently active AND fully completed."""
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT is_completed, is_currently_active FROM active_codes WHERE code=?", (code,))
    row = c.fetchone()
    conn.close()
    if not row:
        return False
    # If reactivated (is_currently_active=1 but is_completed was reset), treat as not done
    return row["is_completed"] == 1 and row["is_currently_active"] == 1

def mark_code_completed(code, results):
    success      = sum(1 for r in results if r["status"] == "SUCCESS")
    already_used = sum(1 for r in results if r["status"] == "ALREADY_USED")
    failed       = sum(1 for r in results if r["status"] in ("FAILED", "INVALID_CODE", "UNKNOWN", "SERVER_BUSY"))
    conn = db_connect()
    c = conn.cursor()
    c.execute("""
        UPDATE active_codes SET is_completed=1, total=?, success=?, already_used=?, failed=?, last_updated=?
        WHERE code=?
    """, (len(results), success, already_used, failed,
          datetime.now(timezone.utc).isoformat(), code))
    conn.commit()
    conn.close()

def update_code_progress(code, results):
    """Update progress stats without marking as completed."""
    success      = sum(1 for r in results if r["status"] == "SUCCESS")
    already_used = sum(1 for r in results if r["status"] == "ALREADY_USED")
    failed       = sum(1 for r in results if r["status"] in ("FAILED", "INVALID_CODE", "UNKNOWN"))
    conn = db_connect()
    c = conn.cursor()
    c.execute("""
        UPDATE active_codes SET total=?, success=?, already_used=?, failed=?, last_updated=?
        WHERE code=?
    """, (len(results), success, already_used, failed,
          datetime.now(timezone.utc).isoformat(), code))
    conn.commit()
    conn.close()

def get_active_codes_details():
    """Get all codes with full details for status display."""
    conn = db_connect()
    c = conn.cursor()
    c.execute("""
        SELECT code, created_at, expires_at, is_currently_active, is_completed,
               total, success, already_used, failed
        FROM active_codes
        ORDER BY is_currently_active DESC,
                 CASE WHEN expires_at IS NULL THEN '9999' ELSE expires_at END ASC
    """)
    rows = c.fetchall()
    conn.close()
    return rows

def get_db_stats():
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM active_codes WHERE is_completed=1")
    total_codes = c.fetchone()["cnt"]
    c.execute("SELECT SUM(success) as s, SUM(already_used) as a, SUM(failed) as f FROM active_codes")
    row = c.fetchone()
    success, already_used, failed = (row["s"] or 0), (row["a"] or 0), (row["f"] or 0)
    c.execute("SELECT COUNT(*) as cnt FROM players WHERE removed_at IS NULL")
    total_players = c.fetchone()["cnt"]
    c.execute("SELECT COUNT(*) as cnt FROM players WHERE is_vip=1 AND removed_at IS NULL")
    total_vip = c.fetchone()["cnt"]
    conn.close()
    return total_codes, success, already_used, failed, total_players, total_vip

def get_player_stats(player_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT code, status, message, created_at FROM redemptions WHERE player_id=? ORDER BY created_at DESC", (player_id,))
    rows = c.fetchall()
    c.execute("SELECT username, is_vip FROM players WHERE player_id=?", (player_id,))
    p_row = c.fetchone()
    conn.close()
    username = p_row["username"] if p_row else "Unknown"
    is_vip = bool(p_row["is_vip"]) if p_row else False
    return [(r["code"], r["status"], r["message"], r["created_at"]) for r in rows], username, is_vip

# ============================================================
#  SYSTEM HEALTH
# ============================================================
def get_system_health():
    health = {}
    try:
        result = subprocess.run(["cat", "/proc/loadavg"], capture_output=True, text=True)
        load = float(result.stdout.split()[0])
        health["cpu_load"] = round(load * 100 / os.cpu_count(), 1)
    except Exception as e:
        log.debug(f"CPU load read error: {e}")
        health["cpu_load"] = 0

    try:
        result = subprocess.run(["cat", "/proc/meminfo"], capture_output=True, text=True)
        mem = {}
        for line in result.stdout.splitlines():
            parts = line.split()
            if parts[0] in ("MemTotal:", "MemAvailable:"):
                mem[parts[0]] = int(parts[1])
        total = mem.get("MemTotal:", 1)
        available = mem.get("MemAvailable:", 0)
        health["ram_percent"] = round((total - available) / total * 100, 1)
        health["ram_used_mb"] = round((total - available) / 1024)
        health["ram_total_mb"] = round(total / 1024)
    except Exception as e:
        log.debug(f"RAM read error: {e}")
        health["ram_percent"] = 0
        health["ram_used_mb"] = 0
        health["ram_total_mb"] = 0

    try:
        result = subprocess.run(["cat", "/sys/class/thermal/thermal_zone0/temp"], capture_output=True, text=True)
        health["temp_c"] = round(int(result.stdout.strip()) / 1000, 1)
    except Exception:
        try:
            result = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True, text=True)
            match = re.search(r"[\d.]+", result.stdout)
            health["temp_c"] = float(match.group()) if match else 0
        except Exception as e:
            log.debug(f"Temperature read error: {e}")
            health["temp_c"] = 0

    return health

def check_health_alerts():
    global _last_health_alert
    health = get_system_health()
    now = datetime.now(timezone.utc)
    alerts = []
    if health["cpu_load"] > CONFIG["CPU_ALERT_THRESHOLD"]:
        alerts.append(f"🔥 CPU: {health['cpu_load']}% (threshold: {CONFIG['CPU_ALERT_THRESHOLD']}%)")
    if health["ram_percent"] > CONFIG["RAM_ALERT_THRESHOLD"]:
        alerts.append(f"💾 RAM: {health['ram_percent']}% ({health['ram_used_mb']}MB / {health['ram_total_mb']}MB)")
    if health["temp_c"] > CONFIG["TEMP_ALERT_THRESHOLD"]:
        alerts.append(f"🌡️ Temperature: {health['temp_c']}°C (threshold: {CONFIG['TEMP_ALERT_THRESHOLD']}°C)")
    for alert in alerts:
        key = alert[:20]
        last = _last_health_alert.get(key)
        if not last or (now - last).total_seconds() > 3600:
            send_telegram(f"⚠️ <b>System Alert!</b>\n{alert}")
            _last_health_alert[key] = now
    return health

# ============================================================
#  EXPIRY WARNINGS
# ============================================================
def already_warned(code):
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT warned_at FROM expiry_warnings WHERE code=?", (code,))
    row = c.fetchone()
    conn.close()
    if not row:
        return False
    return row["warned_at"][:10] == datetime.now(timezone.utc).isoformat()[:10]

def save_warning(code):
    conn = db_connect()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO expiry_warnings (code, warned_at) VALUES (?, ?)",
              (code, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()

def check_expiry_warnings(codes_data, all_players):
    now = datetime.now(timezone.utc)
    threshold = now + timedelta(hours=CONFIG["EXPIRY_WARNING_HOURS"])

    for code_data in codes_data:
        code = code_data["code"]
        expires_at = code_data.get("expiresAt")
        if not expires_at:
            continue
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expires <= threshold and not already_warned(code):
            hours_left = int((expires - now).total_seconds() / 3600)
            log.warning(f"⚠️ Code expiring soon: {code} — {hours_left}h left")

            status_map = get_code_status_map(code)
            delivered_ids = {pid for pid, status in status_map.items() if status == "SUCCESS"}
            undelivered = [p for p in all_players if p["playerId"] not in delivered_ids]

            msg = (
                f"⏰ <b>Gift Code Expiry Warning!</b>\n"
                f"Code: <code>{code}</code>\n"
                f"Expires: {expires.strftime('%Y-%m-%d %H:%M')} UTC\n"
                f"Time left: <b>{hours_left} hours</b>\n\n"
                f"👥 Total players: {len(all_players)}\n"
                f"✅ Delivered: {len(delivered_ids)}\n"
                f"❌ Not delivered: {len(undelivered)}\n"
            )
            if undelivered:
                player_list = "\n".join(
                    f"• {p.get('username') or p['playerId']} ({p['playerId']})"
                    for p in undelivered[:30]
                )
                if len(undelivered) > 30:
                    player_list += f"\n... and {len(undelivered) - 30} more"
                msg += f"\n<b>Not delivered:</b>\n{player_list}"

            send_telegram(msg)
            send_to_channels("expiry_warning",
                code=code,
                hours=hours_left,
                delivered=len(delivered_ids),
                total=len(all_players),
            )
            save_warning(code)

# ============================================================
#  KINGSHOT API
# ============================================================
def refresh_null_expiries():
    """
    expires_at IS NULL olan aktif kodlar için API'yi tek tek sorgular.
    Eğer artık bir expiry tarihi döndürülüyorsa DB'yi günceller.
    """
    conn = db_connect()
    null_codes = conn.execute(
        "SELECT code FROM active_codes WHERE is_currently_active=1 AND expires_at IS NULL"
    ).fetchall()
    conn.close()

    if not null_codes:
        return

    updated = 0
    for row in null_codes:
        code = row["code"]
        expiry = None

        # Yöntem 1: bireysel kod endpoint'i
        try:
            resp = requests.get(
                f"{CONFIG['KINGSHOT_API']}/gift-codes/{code}",
                timeout=8,
                headers={"Accept": "application/json"}
            )
            if resp.status_code == 200:
                d = resp.json()
                expiry = (d.get("data") or d).get("expiresAt")
        except Exception:
            pass

        # Yöntem 2: liste endpoint'ine parametre ile sor
        if not expiry:
            try:
                resp = requests.get(
                    f"{CONFIG['KINGSHOT_API']}/gift-codes",
                    params={"code": code},
                    timeout=8,
                    headers={"Accept": "application/json"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = (data.get("data") or {}).get("giftCodes") or []
                    for item in items:
                        if item.get("code") == code:
                            expiry = item.get("expiresAt")
                            break
            except Exception:
                pass

        if expiry:
            conn = db_connect()
            conn.execute(
                "UPDATE active_codes SET expires_at=?, last_updated=? WHERE code=?",
                (expiry, datetime.now(timezone.utc).isoformat(), code)
            )
            conn.commit()
            conn.close()
            log.info(f"📅 Expiry updated for {code}: {expiry}")
            updated += 1

    if updated:
        log.info(f"✅ Expiry refresh: {updated}/{len(null_codes)} code(s) updated")
    else:
        log.debug(f"🔍 Expiry refresh: no updates for {len(null_codes)} null-expiry code(s)")


def fetch_active_gift_codes(run_expiry_check=False, all_players=None):
    try:
        resp = requests.get(
            f"{CONFIG['KINGSHOT_API']}/gift-codes",
            timeout=10,
            headers={"Accept": "application/json"}
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "success":
            codes = data["data"]["giftCodes"]
            now = datetime.now(timezone.utc)

            # Sort by expiry: soonest first
            def sort_key(c):
                exp = c.get("expiresAt")
                if not exp:
                    return datetime(9999, 12, 31, tzinfo=timezone.utc)
                return datetime.fromisoformat(exp.replace("Z", "+00:00"))
            codes.sort(key=sort_key)

            # Sync to DB
            sync_active_codes(codes)

            active = []
            for c in codes:
                expires_at = c.get("expiresAt")
                if not expires_at:
                    active.append(c["code"])
                else:
                    expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    if expires > now:
                        active.append(c["code"])

            if run_expiry_check and all_players:
                check_expiry_warnings(codes, all_players)

            return active, codes
    except Exception as e:
        log.error(f"Gift code fetch error: {e}")
        send_telegram(f"❌ <b>Error:</b> Failed to fetch gift codes\n<code>{e}</code>")
    return [], []

# ============================================================
#  GOOGLE SHEETS
# ============================================================
def fetch_player_list():
    global _cached_players
    try:
        resp = requests.get(
            CONFIG["SHEETS_WEB_APP_URL"],
            timeout=60,
            allow_redirects=True
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("success"):
            log.info(f"✅ {data['total']} players fetched from Sheets.")
            _cached_players = data["players"]
            return _cached_players
    except Exception as e:
        log.error(f"Player list fetch error: {e}")
        send_telegram(f"❌ <b>Error:</b> Failed to fetch player list\n<code>{e}</code>")
    if _cached_players:
        log.warning(f"⚠️ Using cached player list ({len(_cached_players)} players).")
        return _cached_players
    return []

def send_results_to_sheets(code, results):
    try:
        payload = {"code": code, "results": results}
        resp = requests.post(CONFIG["SHEETS_WEB_APP_URL"], json=payload, timeout=30)
        resp.raise_for_status()
        if resp.json().get("success"):
            log.info("✅ Results sent to Sheets.")
    except Exception as e:
        log.error(f"Sheets write error: {e}")
        send_telegram(f"❌ <b>Error:</b> Failed to write to Sheets\n<code>{e}</code>")

# ============================================================
#  PLAYWRIGHT
# ============================================================
def launch_browser(pw):
    """
    Host Chromium binary'sini kullanarak tarayıcı başlatır (ARM64/Raspberry Pi uyumlu).
    Playwright'ın kendi tarayıcısını indirmez; Docker volume ile map edilmiş
    /usr/bin/chromium'u kullanır. Browser dağıtım süreci boyunca TEK kez açılır.
    """
    return pw.chromium.launch(
        executable_path='/usr/bin/chromium',
        headless=CONFIG["HEADLESS"],
        args=[
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-software-rasterizer',
            '--disable-setuid-sandbox',
            '--no-zygote',
            '--disable-extensions',
            '--disable-background-networking',
            '--disable-sync',
            '--no-first-run',
            '--disable-blink-features=AutomationControlled',
            '--disable-features=IsolateOrigins,site-per-process',
            '--js-flags=--max-old-space-size=64',
        ]
    )


def create_context(browser):
    """
    Her oyuncu için hafif bir BrowserContext oluşturur.
    Rastgele UA / viewport / dil ile parmak izi çeşitlendirilir (stealth).
    Context kapatıldığında tüm tab hafızası serbest bırakılır.
    """
    ua     = random.choice(USER_AGENTS)
    screen = random.choice(SCREEN_SIZES)
    w, h   = map(int, screen.split(','))
    lang   = random.choice(LANGUAGES)

    context = browser.new_context(
        user_agent=ua,
        viewport={'width': w, 'height': h},
        locale=lang.split(';')[0].split(',')[0],
        extra_http_headers={'Accept-Language': lang},
    )
    # Stealth: navigator.webdriver ve diğer otomasyon izlerini gizle
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins',   {get: () => [1, 2, 3, 4, 5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        window.chrome = {runtime: {}};
    """)
    return context

def kill_zombie_chromium():
    """Browser kapatıldıktan sonra kalan zombie Chromium process'leri temizle — host üzerinden."""
    try:
        import urllib.request
        req = urllib.request.Request(
            CONFIG["REBUILD_SERVER_URL"] + "/kill-zombies",
            method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

def parse_message(msg_text):
    if not msg_text:
        return "UNKNOWN", msg_text
    msg_lower = msg_text.lower()
    if any(x in msg_lower for x in ["redeemed", "success", "reward", "please claim"]):
        return "SUCCESS", msg_text
    if any(x in msg_lower for x in ["already claimed", "already used", "cannot claim again", "unable to claim again"]):
        return "ALREADY_USED", msg_text
    if any(x in msg_lower for x in ["not found", "invalid", "expired", "wrong", "case-sensitive"]):
        return "INVALID_CODE", msg_text
    if any(x in msg_lower for x in ["claim limit", "unable to claim", "cannot claim", "limit reached"]):
        return "FAILED", msg_text
    if any(x in msg_lower for x in ["server busy", "please try again later", "try again later", "too many", "service unavailable", "please log in", "log in to relevant", "character before redemption"]):
        return "SERVER_BUSY", msg_text
    return "UNKNOWN", msg_text

def _attempt_redeem(page, player_id, gift_code):
    """
    Tek bir redemption denemesi yapar. Playwright page nesnesi alır.
    Returns (status, message).
    """
    for page_try in range(3):
        try:
            page.goto(
                "https://ks-giftcode.centurygame.com/",
                wait_until="domcontentloaded",
                timeout=45000,
            )
        except Exception as e:
            log.warning(f"Page load attempt {page_try+1}/3 goto error: {e}")
            time.sleep(5)
            continue
        try:
            # domcontentloaded sonrası Vue DOM'u render eder; 15s yeterli
            page.wait_for_selector('input[placeholder="Player ID"]', timeout=15000)
            log.info(f"Page loaded OK on attempt {page_try+1}")
            break
        except Exception as e:
            log.warning(f"Page load attempt {page_try+1}/3 input not found: {e}")
            time.sleep(5)
    else:
        raise Exception("Page failed to load after 3 attempts — browser crash")

    # Player ID gir ve doğrula
    pid_input = page.locator('input[placeholder="Player ID"]')
    pid_input.fill(str(player_id))
    time.sleep(0.3)
    entered = pid_input.input_value()
    if entered.strip() != str(player_id).strip():
        log.warning(f"Player ID input mismatch: expected {player_id}, got {entered} — retrying")
        pid_input.fill("")
        time.sleep(0.5)
        pid_input.fill(str(player_id))

    # Gift code gir ve doğrula
    code_input = page.locator('input[placeholder="Enter Gift Code"]')
    code_input.fill(str(gift_code))
    time.sleep(0.3)
    entered_code = code_input.input_value()
    if entered_code.strip() != str(gift_code).strip():
        log.warning(f"Gift code input mismatch — retrying")
        code_input.fill("")
        time.sleep(0.5)
        code_input.fill(str(gift_code))

    # Login butonuna tıkla
    login_btn = page.locator('div.login_btn.btn')
    login_btn.wait_for(state="visible", timeout=15000)
    login_btn.click()

    # Loading spinner kaybolana dek bekle
    try:
        page.wait_for_selector('div.loading', state='hidden', timeout=10000)
    except Exception:
        pass
    time.sleep(1)

    # Erken "please enter your player id" kontrolü
    try:
        early_text = (page.locator('p.msg').text_content(timeout=2000) or "").strip().lower()
        if "please enter your player id" in early_text:
            log.warning(f"Player ID not entered properly for {player_id}, retrying page")
            return "RETRY_PAGE", "Player ID not entered"
    except Exception:
        pass

    # Exchange butonunun disabled class'ının kalkmasını bekle (max 15s)
    try:
        page.wait_for_function(
            "!document.querySelector('div.exchange_btn')?.className.includes('disabled')",
            timeout=15000,
        )
    except Exception as e:
        log.debug(f"Exchange button wait error: {e}")

    # Confirm butonuna tıkla
    try:
        confirm_btn = page.locator('div.exchange_btn:has-text("Confirm")')
        confirm_btn.wait_for(state="visible", timeout=15000)
        confirm_btn.click()
        time.sleep(1.5)
    except Exception as e:
        log.debug(f"Confirm button not found: {e}")

    # Sonuç mesajını bekle (max 60s)
    KNOWN_PHRASES = [
        "please claim", "already claimed", "unable to claim again",
        "not found", "case-sensitive", "server busy", "please try again",
        "please log in", "log in to relevant", "redeemed", "gift code",
        "expired", "invalid", "too many", "service unavailable",
    ]
    msg_text = ""
    try:
        for _ in range(120):
            try:
                txt = (page.locator('p.msg').text_content(timeout=1000) or "").strip()
                if txt and any(p in txt.lower() for p in KNOWN_PHRASES):
                    msg_text = txt
                    break
                # txt var ama tanınmıyor — devam et
            except Exception:
                pass
            time.sleep(0.5)
        else:
            # 60 saniye doldu
            try:
                msg_text = (page.locator('p.msg').text_content(timeout=2000) or "").strip()
                if msg_text:
                    log.warning(f"Unknown modal text after 60s: '{msg_text}'")
            except Exception:
                pass
    except Exception:
        msg_text = ""

    return parse_message(msg_text)


def redeem_code_for_player(browser, player_id, username, gift_code, retry_count=0):
    """
    Her oyuncu için ayrı bir BrowserContext açar, işlemi yapar ve context'i kapatır.
    Browser instance dağıtım boyunca tek kez açılmış halde kalır (RAM optimizasyonu).
    Gereksiz kaynaklar (image, stylesheet, font, media) network seviyesinde engellenir.
    """
    result = {
        "playerId":   player_id,
        "username":   username,
        "status":     "FAILED",
        "message":    "No response from site",
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "retryCount": retry_count,
    }

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        ctx = None
        try:
            ctx = create_context(browser)
            page = ctx.new_page()

            # image/media/font engelle; stylesheet SPA render için gerekli (kaldırılırsa input görünmez)
            page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ("image", "media", "font")
                else route.continue_(),
            )

            status, message = _attempt_redeem(page, player_id, gift_code)

            if status == "SERVER_BUSY":
                wait_sec = 120 * attempt  # 2dk, 4dk, 6dk
                log.warning(f"  ⏳ Server busy for {player_id} ({username}) — waiting {wait_sec}s before retry ({attempt}/{max_attempts})")
                ctx.close()
                ctx = None
                time.sleep(wait_sec)
                continue

            if status == "RETRY_PAGE":
                log.warning(f"  ↩️ Page issue for {player_id} ({username}), retrying ({attempt}/{max_attempts})")
                ctx.close()
                ctx = None
                time.sleep(2)
                continue

            result["status"]  = status
            result["message"] = message
            return result

        except Exception as e:
            err_lines = str(e).splitlines()
            clean_err = err_lines[0] if err_lines else str(e)
            log.warning(f"  ⚠️ Attempt {attempt}/{max_attempts} failed for {player_id} ({username}): {clean_err}")
            # Browser crash — dışarıya fırlat ki ana loop yeniden başlatsın
            raise
        finally:
            if ctx:
                try:
                    ctx.close()
                except Exception:
                    pass

    return result

# ============================================================
#  REDEMPTION
# ============================================================
def get_code_expiry(code):
    """Get expiry datetime for a code from DB. Returns None if no expiry."""
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT expires_at FROM active_codes WHERE code=?", (code,))
    row = c.fetchone()
    conn.close()
    if not row or not row["expires_at"]:
        return None
    return datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))

def is_code_expired(code):
    """Check if code has passed its expiry time (UTC)."""
    expires = get_code_expiry(code)
    if not expires:
        return False
    return datetime.now(timezone.utc) >= expires

def redeem_code_for_all(gift_code):
    """Dynamic SQL queue: each iteration queries the DB for the next unprocessed player."""
    log.info(f"\n{'='*50}")
    log.info(f"🎁 Redeeming (dynamic queue): {gift_code}")

    # Count players that still need processing
    conn = db_connect()
    total = conn.execute("""
        SELECT COUNT(*) FROM players p
        LEFT JOIN redemptions r ON r.player_id = p.player_id AND r.code = ?
        WHERE p.removed_at IS NULL AND (r.status IS NULL OR r.status = 'SERVER_BUSY')
    """, (gift_code,)).fetchone()[0]
    total_players = conn.execute(
        "SELECT COUNT(*) FROM players WHERE removed_at IS NULL"
    ).fetchone()[0]
    conn.execute(
        "UPDATE active_codes SET player_count=? WHERE code=?",
        (total_players, gift_code)
    )
    conn.commit()
    conn.close()
    log.info(f"👥 Players to process: {total}")

    _dist_state.update({
        "active": True,
        "code": gift_code,
        "current_player": None,
        "current_index": 0,
        "total": total,
        "success": 0,
        "already_used": 0,
        "failed": 0,
        "skipped": 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
    })

    results = []
    processed = 0
    pw = None
    browser = None
    code_expires_at = get_code_expiry(gift_code)  # cached once — avoid per-player DB hit

    # Browser is started once for the entire distribution run
    try:
        pw      = sync_playwright().start()
        browser = launch_browser(pw)
        log.info("🌐 Browser started.")
    except Exception as e:
        log.error(f"Failed to start browser: {e}")
        send_telegram(f"❌ <b>Browser Error:</b>\n<code>{e}</code>")
        if pw:
            try:
                pw.stop()
            except Exception:
                pass
        _dist_state["active"] = False
        return []

    while True:
        # Fetch the next player that hasn't been processed (or was SERVER_BUSY / RETRY_PENDING)
        try:
            conn = db_connect()
            row = conn.execute("""
                SELECT p.*, COALESCE(r.retry_count, 0) AS r_retry_count FROM players p
                LEFT JOIN redemptions r ON r.player_id = p.player_id AND r.code = ?
                WHERE p.removed_at IS NULL
                  AND (r.status IS NULL OR r.status IN ('SERVER_BUSY', 'RETRY_PENDING'))
                ORDER BY p.is_vip DESC, p.role DESC, p.username ASC
                LIMIT 1
            """, (gift_code,)).fetchone()
            conn.close()
        except Exception as e:
            log.error(f"DB error fetching next player: {e}")
            break

        if row is None:
            log.info("✅ No more players to process. Distribution complete.")
            break

        player_id    = row["player_id"]
        username     = row["username"] or player_id
        is_vip       = bool(row["is_vip"])
        role         = row["role"] or "R1"
        vip_tag      = " ⭐" if is_vip else ""
        role_tag     = f" [{role}]" if role != "R1" else ""
        r_retry_count = row["r_retry_count"]  # 0 for first-timers, N for retry players

        if code_expires_at and datetime.now(timezone.utc) >= code_expires_at:
            log.warning(f"⏰ Code {gift_code} has expired (UTC). Stopping distribution.")
            send_telegram(
                f"⏰ <b>Code Expired!</b>\n"
                f"Code: <code>{gift_code}</code>\n"
                f"Stopped after {processed} players."
            )
            break

        log.info(f"🔄 [{processed + 1}] {player_id} ({username}){vip_tag}{role_tag}")
        _dist_state["current_player"] = username
        _dist_state["current_index"]  = processed + 1

        try:
            result = redeem_code_for_player(browser, player_id, username, gift_code)
            results.append(result)
            save_redemption(gift_code, player_id, username, result["status"], result["message"],
                            r_retry_count + 1 if r_retry_count > 0 else 0)
            processed += 1
            _dist_state["current_index"] = processed

            status = result["status"]
            status_icon = {"SUCCESS": "✅", "ALREADY_USED": "⚠️", "INVALID_CODE": "❌",
                           "FAILED": "❌", "UNKNOWN": "❓", "SERVER_BUSY": "🔄"}.get(status, "❓")
            if status == "SUCCESS":
                _dist_state["success"] += 1
            elif status == "ALREADY_USED":
                _dist_state["already_used"] += 1
            elif status in ("FAILED", "INVALID_CODE", "UNKNOWN", "SERVER_BUSY"):
                _dist_state["failed"] += 1
            log.info(f"  {status_icon} {status}: {result['message']}")

            tg_extra = f"\n🔄 Will retry in {CONFIG['RETRY_DELAY_HOURS']} hours" if status == "FAILED" else ""
            delivered = _dist_state["success"] + _dist_state["already_used"]
            live_total = _dist_state["total"]  # updated dynamically if /retry injects players
            send_telegram(
                f"{status_icon} <b>[{processed}/{live_total}] {username or player_id}{vip_tag}</b>\n"
                f"Code: <code>{gift_code}</code>\n"
                f"Status: {status}\n"
                f"Message: {result['message']}\n"
                f"✅ {delivered} | ❌ {_dist_state['failed']}"
                f"{tg_extra}"
            )

            avg_delay = (24 * 60 * 60) / 100
            delay = random.randint(int(avg_delay * 0.7), int(avg_delay * 1.3))
            log.info(f"  ⏳ Next player in {delay}s (~{delay//60}min)...")
            time.sleep(delay)

            # ── Kontrol: pause / resume / cancel / retry ──────
            cmd = ctrl_get("dist_cmd")
            if cmd == "retry":
                ctrl_set("dist_cmd", "")
                rows = get_failed_players(gift_code, ignore_delay=True)
                if rows:
                    for pid, uname, retry_cnt in rows:
                        save_redemption(gift_code, pid, uname, "RETRY_PENDING", "Injected by UI retry", retry_cnt)
                    _dist_state["total"] += len(rows)
                    log.info(f"↩️ UI retry: {len(rows)} player(s) injected (new total: {_dist_state['total']})")
                    send_telegram(f"↩️ <b>Retry:</b> {len(rows)} player(s) injected into active distribution.")
                else:
                    log.info("↩️ UI retry: no players to retry.")
            elif cmd == "cancel":
                ctrl_set("dist_cmd", "")
                ctrl_set("dist_paused", "0")
                _dist_state["paused"] = False
                log.info("⏹ Distribution cancelled via control panel.")
                send_telegram(f"⏹ <b>Distribution cancelled.</b>\nCode: <code>{gift_code}</code>\n{processed} player(s) processed.")
                break
            elif cmd == "pause":
                ctrl_set("dist_cmd", "")
                ctrl_set("dist_paused", "1")
                _dist_state["paused"] = True
                log.info("⏸ Distribution paused. Waiting for resume or cancel...")
                send_telegram(f"⏸ <b>Distribution paused.</b>\nCode: <code>{gift_code}</code>\n{processed}/{_dist_state['total']} processed.")
                while True:
                    time.sleep(10)
                    resume_cmd = ctrl_get("dist_cmd")
                    if resume_cmd == "resume":
                        ctrl_set("dist_cmd", "")
                        ctrl_set("dist_paused", "0")
                        _dist_state["paused"] = False
                        log.info("▶ Distribution resumed.")
                        send_telegram(f"▶ <b>Distribution resumed.</b>\nCode: <code>{gift_code}</code>")
                        break
                    elif resume_cmd == "cancel":
                        ctrl_set("dist_cmd", "")
                        ctrl_set("dist_paused", "0")
                        _dist_state["paused"] = False
                        log.info("⏹ Distribution cancelled while paused.")
                        send_telegram(f"⏹ <b>Distribution cancelled (was paused).</b>\nCode: <code>{gift_code}</code>")
                        # Dış döngüyü kırmak için flag kullan
                        _dist_state["cancelled"] = True
                        break
                if _dist_state.get("cancelled"):
                    _dist_state["cancelled"] = False
                    break

        except Exception as e:
            log.error(f"  💥 Browser crashed for {player_id}: {e}")
            try:
                browser.close()
            except Exception:
                pass
            kill_zombie_chromium()
            browser = None
            log.info("  🔄 Restarting browser in 10s...")
            time.sleep(10)
            restarted = False
            for restart_try in range(5):
                try:
                    browser = launch_browser(pw)
                    log.info("  🌐 Browser restarted successfully.")
                    restarted = True
                    break
                except Exception as ce:
                    log.warning(f"  ⚠️ Browser restart attempt {restart_try+1}/5 failed: {ce} — waiting 30s")
                    time.sleep(30)
            if not restarted:
                log.error("  ❌ Browser could not restart after 5 attempts. Skipping player.")
                send_telegram(f"❌ <b>Browser restart failed!</b>\nPlayer: {username} (<code>{player_id}</code>) skipped.")
                save_redemption(gift_code, player_id, username, "FAILED", "Browser could not restart")
                processed += 1
            # If restarted: same player re-picked next iteration (no record saved).
            # If not restarted: player saved as FAILED, next player picked next iteration.
            continue

    if browser:
        try:
            browser.close()
        except Exception as e:
            log.debug(f"Browser close error: {e}")
    if pw:
        try:
            pw.stop()
        except Exception:
            pass
    kill_zombie_chromium()

    success      = sum(1 for r in results if r["status"] == "SUCCESS")
    already_used = sum(1 for r in results if r["status"] == "ALREADY_USED")
    failed       = sum(1 for r in results if r["status"] in ("FAILED", "INVALID_CODE", "UNKNOWN"))

    log.info(f"\n📊 Summary — {gift_code}: ✅{success} ⚠️{already_used} ❌{failed}")
    send_telegram(
        f"📊 <b>Redemption Complete!</b>\n"
        f"Code: <code>{gift_code}</code>\n\n"
        f"✅ Success: {success}\n"
        f"⚠️ Already used: {already_used}\n"
        f"❌ Failed: {failed}\n"
        f"👥 Total processed: {processed}"
    )
    send_to_channels("dist_complete",
        code=gift_code,
        delivered=success + already_used,
        success=success,
        already_used=already_used,
        failed=failed,
        total=processed,
    )

    _dist_state["active"] = False
    _dist_state["paused"] = False
    ctrl_set("dist_paused", "0")
    ctrl_set("dist_cmd", "")
    return results

# ============================================================
#  BACKGROUND NAME SYNC
# ============================================================
NAME_SYNC_INTERVAL = 15 * 60  # seconds

def sync_player_names():
    """Query KingShot API for each active player and update username in DB if changed."""
    conn = db_connect()
    rows = conn.execute(
        "SELECT player_id, username FROM players WHERE removed_at IS NULL"
    ).fetchall()
    conn.close()

    updated = 0
    for row in rows:
        pid      = row["player_id"]
        old_name = row["username"]
        try:
            resp = requests.get(
                f"{CONFIG['KINGSHOT_API']}/player-info",
                params={"playerId": pid},
                timeout=10,
                headers={"Accept": "application/json"}
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            name = (data.get("data", {}).get("name") or "").strip()
            if not name or name == old_name:
                continue
            conn = db_connect()
            # Eski ismi geçmişe kaydet
            if old_name:
                conn.execute(
                    "INSERT INTO player_name_history (player_id, username, recorded_at) VALUES (?, ?, ?)",
                    (pid, old_name, datetime.now(timezone.utc).isoformat())
                )
            conn.execute("UPDATE players SET username=? WHERE player_id=?", (name, pid))
            conn.commit()
            conn.close()
            log.info(f"  📝 Name updated: {pid} → {name} (was: {old_name})")
            updated += 1
        except Exception as e:
            log.debug(f"Name sync error for {pid}: {e}")

    if updated:
        log.info(f"✅ Name sync complete: {updated} player(s) updated.")
    return updated

# ============================================================
#  RETRY
# ============================================================
def retry_failed_players(active_codes, all_players):
    player_map = {p["playerId"]: p for p in all_players}
    for code in active_codes:
        failed_rows = get_failed_players(code)
        if not failed_rows:
            continue
        log.info(f"🔁 Retrying {len(failed_rows)} failed players for {code}...")
        send_telegram(f"🔁 <b>Retrying {len(failed_rows)} failed players</b> for <code>{code}</code>")

        pw      = None
        browser = None
        i = 0

        # Retry için browser bir kez başlatılır
        for restart_try in range(5):
            try:
                pw      = sync_playwright().start()
                browser = launch_browser(pw)
                log.info("  🌐 Browser started for retry.")
                break
            except Exception as ce:
                log.warning(f"  ⚠️ Browser start attempt {restart_try+1}/5 failed: {ce} — waiting 30s")
                if pw:
                    try:
                        pw.stop()
                    except Exception:
                        pass
                pw = None
                time.sleep(30)
        else:
            log.error("  ❌ Browser could not be started for retry. Aborting retry for this code.")
            send_telegram(f"❌ <b>Retry aborted!</b> Browser could not start for <code>{code}</code>")
            continue

        while i < len(failed_rows):
            player_id, username, retry_count = failed_rows[i]
            try:
                log.info(f"  🔁 Retry #{retry_count+1}: {player_id} ({username})")
                result = redeem_code_for_player(browser, player_id, username, code, retry_count + 1)
                save_redemption(code, player_id, username, result["status"], result["message"], retry_count + 1)
                icon = {"SUCCESS": "✅", "ALREADY_USED": "⚠️"}.get(result["status"], "❌")
                log.info(f"    {icon} {result['status']}: {result['message']}")
                i += 1
                if i < len(failed_rows):
                    time.sleep(random.randint(30, 60))
            except Exception as e:
                log.error(f"  💥 Browser crashed during retry for {player_id}: {e}")
                try:
                    browser.close()
                except Exception:
                    pass
                kill_zombie_chromium()
                browser = None
                log.info("  🔄 Restarting browser in 10s...")
                time.sleep(10)
                save_redemption(code, player_id, username, "FAILED", "Browser crashed during retry", retry_count + 1)
                send_telegram(f"❌ <b>Retry crash!</b> Player {username} (<code>{player_id}</code>) skipped.")
                i += 1
                # Browser'ı yeniden başlatmayı dene
                for restart_try in range(5):
                    try:
                        browser = launch_browser(pw)
                        log.info("  🌐 Browser restarted for retry.")
                        break
                    except Exception as ce:
                        log.warning(f"  ⚠️ Retry browser restart {restart_try+1}/5 failed: {ce} — waiting 30s")
                        time.sleep(30)
                else:
                    log.error("  ❌ Browser could not restart during retry. Stopping retry for this code.")
                    send_telegram(f"❌ <b>Retry browser restart failed!</b> Stopping retry for <code>{code}</code>")
                    break

        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if pw:
            try:
                pw.stop()
            except Exception:
                pass
        kill_zombie_chromium()

# ============================================================
#  STARTUP MESSAGE
# ============================================================
def build_startup_message(active_codes_data):
    total_codes, success, already_used, failed, total_players, total_vip = get_db_stats()
    health = get_system_health()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    msg = (
        f"🚀 <b>WLF Rewardwolf v2.1.0</b> — {now_str}\n\n"
        f"👥 Players: {total_players} ({total_vip} VIP)\n"
        f"🎁 Codes processed: {total_codes}\n"
        f"💻 CPU {health['cpu_load']}% | RAM {health['ram_percent']}% | Temp {health['temp_c']}°C\n"
    )

    now = datetime.now(timezone.utc)
    db_codes = get_active_codes_details()
    active_db = [r for r in db_codes if r["is_currently_active"]]

    if active_db:
        msg += f"\n🟢 <b>Active Codes ({len(active_db)}):</b>\n"
        for r in active_db:
            code = r["code"]
            created = r["created_at"][:10] if r["created_at"] else "?"
            if r["expires_at"]:
                exp_dt = datetime.fromisoformat(r["expires_at"].replace("Z", "+00:00"))
                hours_left = int((exp_dt - now).total_seconds() / 3600)
                exp_str = f"{r['expires_at'][:10]} ({hours_left}h left)"
            else:
                exp_str = "No expiry"

            status_map = get_code_status_map(code)
            success_cnt = sum(1 for s in status_map.values() if s == "SUCCESS")
            already_cnt = sum(1 for s in status_map.values() if s == "ALREADY_USED")
            failed_cnt  = sum(1 for s in status_map.values() if s in ("FAILED", "INVALID_CODE", "UNKNOWN", "SERVER_BUSY"))
            delivered   = success_cnt + already_cnt
            pending     = total_players - delivered - failed_cnt

            if r["is_completed"]:
                fail_str = f" | ❌ {failed_cnt} failed" if failed_cnt else ""
                progress = f"✅ Complete — {delivered}/{total_players} delivered{fail_str}"
            elif delivered > 0:
                progress = f"🔄 In progress — {delivered}/{total_players}, {pending} pending"
            else:
                progress = "⏳ Not started"

            msg += (
                f"\n• <code>{code}</code>\n"
                f"  📅 Created: {created} | ⏰ Expires: {exp_str}\n"
                f"  {progress}\n"
            )
    else:
        msg += "\nℹ️ No active codes.\n"

    msg += "\nType /help for commands."
    return msg

# ============================================================
#  DAILY SUMMARY
# ============================================================
def send_daily_summary():
    global _last_summary_date
    today = datetime.now(timezone.utc).date()
    if _last_summary_date == today:
        return
    _last_summary_date = today
    total_codes, success, already_used, failed, total_players, total_vip = get_db_stats()
    health = get_system_health()
    send_telegram(
        f"📅 <b>Daily Summary</b> — {today}\n\n"
        f"🎁 Codes processed: {total_codes}\n"
        f"👥 Players: {total_players} ({total_vip} VIP)\n"
        f"✅ Successful: {success}\n"
        f"⚠️ Already used: {already_used}\n"
        f"❌ Failed: {failed}\n"
        f"📊 Success rate: {round(success/(success+failed)*100) if (success+failed) > 0 else 0}%\n\n"
        f"💻 CPU {health['cpu_load']}% | RAM {health['ram_percent']}% | Temp {health['temp_c']}°C"
    )
    send_to_channels("daily_summary",
        players=total_players,
        delivered=success + already_used,
        success=success,
        already_used=already_used,
        failed=failed,
        codes=total_codes,
    )

# ============================================================
#  TELEGRAM COMMAND HANDLER
# ============================================================
def telegram_command_loop():
    log.info("🤖 Telegram command listener started.")
    while True:
        try:
            updates = get_telegram_updates()
            for update in updates:
                msg = update.get("message", {})
                text = msg.get("text", "").strip()
                chat = msg.get("chat", {})
                chat_id   = str(chat.get("id", ""))
                chat_type = chat.get("type", "unknown")
                chat_name = chat.get("title") or chat.get("username") or chat.get("first_name") or "?"
                from_user = msg.get("from", {})
                from_name = from_user.get("username") or from_user.get("first_name") or "?"

                # Her mesajda chat info'yu logla (Chat ID almayı kolaylaştırır)
                log.info(f"💬 Message from [{chat_type}] '{chat_name}' | chat_id={chat_id} | user=@{from_name} | text={text[:60]!r}")

                if not text.startswith("/"):
                    continue

                parts = text.split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ""
                log.info(f"📩 Command: {cmd} {arg}")

                if cmd == "/status":
                    total_codes, success, already_used, failed, total_players, total_vip = get_db_stats()
                    uptime = datetime.now(timezone.utc) - _daemon_start_time
                    uptime_str = f"{uptime.days}d {uptime.seconds//3600}h {(uptime.seconds%3600)//60}m"
                    health = get_system_health()
                    send_telegram(
                        f"📊 <b>System Status</b>\n\n"
                        f"⏱️ Uptime: {uptime_str}\n"
                        f"💻 CPU {health['cpu_load']}% | RAM {health['ram_percent']}% | Temp {health['temp_c']}°C\n\n"
                        f"🎁 Codes processed: {total_codes}\n"
                        f"👥 Players: {total_players} ({total_vip} VIP)\n"
                        f"✅ Successful: {success}\n"
                        f"⚠️ Already used: {already_used}\n"
                        f"❌ Failed: {failed}\n"
                        f"📡 Check interval: {CONFIG['CHECK_INTERVAL_MIN']} min",
                        chat_id
                    )

                elif cmd == "/health":
                    health = get_system_health()
                    uptime = datetime.now(timezone.utc) - _daemon_start_time
                    uptime_str = f"{uptime.days}d {uptime.seconds//3600}h {(uptime.seconds%3600)//60}m"
                    cpu_icon = "🔥" if health["cpu_load"] > CONFIG["CPU_ALERT_THRESHOLD"] else "✅"
                    ram_icon = "🔥" if health["ram_percent"] > CONFIG["RAM_ALERT_THRESHOLD"] else "✅"
                    temp_icon = "🔥" if health["temp_c"] > CONFIG["TEMP_ALERT_THRESHOLD"] else "✅"
                    send_telegram(
                        f"💻 <b>System Health</b>\n\n"
                        f"{cpu_icon} CPU: {health['cpu_load']}%\n"
                        f"{ram_icon} RAM: {health['ram_percent']}% ({health['ram_used_mb']}MB / {health['ram_total_mb']}MB)\n"
                        f"{temp_icon} Temp: {health['temp_c']}°C\n\n"
                        f"⏱️ Uptime: {uptime_str}",
                        chat_id
                    )

                elif cmd == "/players":
                    conn = db_connect()
                    c = conn.cursor()
                    c.execute("SELECT player_id, username, is_vip FROM players WHERE removed_at IS NULL ORDER BY is_vip DESC, username ASC")
                    rows = c.fetchall()
                    conn.close()
                    if not rows:
                        send_telegram("ℹ️ No players tracked yet.", chat_id)
                    else:
                        player_list = "\n".join(
                            f"{'⭐ ' if r['is_vip'] else ''}{r['username'] or r['player_id']} ({r['player_id']})"
                            for r in rows
                        )
                        send_telegram(f"👥 <b>Players ({len(rows)}):</b>\n\n{player_list}", chat_id)

                elif cmd == "/codes":
                    rows = get_active_codes_details()
                    if not rows:
                        send_telegram("ℹ️ No codes in database.", chat_id)
                    else:
                        lines = []
                        for r in rows:
                            code = r["code"]
                            created = r["created_at"][:10] if r["created_at"] else "?"
                            expires = r["expires_at"][:10] if r["expires_at"] else "∞"
                            if not r["is_currently_active"]:
                                status = "⚫ Inactive"
                            elif r["is_completed"]:
                                status = "✅ Complete"
                            else:
                                status = "🔄 Active"
                            lines.append(
                                f"{status} <code>{code}</code>\n"
                                f"   📅 {created} → ⏰ {expires}\n"
                                f"   ✅{r['success']} ⚠️{r['already_used']} ❌{r['failed']}"
                            )
                        send_telegram(f"🎁 <b>Codes ({len(rows)}):</b>\n\n" + "\n\n".join(lines), chat_id)

                elif cmd == "/player":
                    if not arg:
                        send_telegram("Usage: /player PLAYER_ID", chat_id)
                    else:
                        rows, username, is_vip = get_player_stats(arg)
                        if not rows:
                            send_telegram(f"ℹ️ No data for <code>{arg}</code>", chat_id)
                        else:
                            vip_tag = " ⭐" if is_vip else ""
                            lines = [f"👤 <b>{username}{vip_tag}</b> (<code>{arg}</code>)\n"]
                            for code, status, message, created_at in rows[:10]:
                                icon = {"SUCCESS": "✅", "ALREADY_USED": "⚠️"}.get(status, "❌")
                                date = created_at[:10] if created_at else "?"
                                lines.append(f"{icon} <code>{code}</code> — {status} ({date})")
                            send_telegram("\n".join(lines), chat_id)

                elif cmd == "/logs":
                    try:
                        result = subprocess.run(
                            ["tail", "-n", "20", CONFIG["LOG_FILE"]],
                            capture_output=True, text=True
                        )
                        last_lines = result.stdout or "No logs found."
                        send_telegram(f"📋 <b>Last 20 log lines:</b>\n\n<code>{last_lines[-3000:]}</code>", chat_id)
                    except Exception as e:
                        send_telegram(f"❌ Failed to read logs: {e}", chat_id)

                elif cmd == "/retry":
                    send_telegram("🔁 <b>Manual retry started...</b>", chat_id)
                    active_codes_now, _ = fetch_active_gift_codes()
                    retried_total  = 0
                    injected_total = 0
                    queued_total   = 0
                    for rc in active_codes_now:
                        rows = get_failed_players(rc, ignore_delay=True)
                        if not rows:
                            continue
                        log.info(f"🔁 Manual retry: {len(rows)} player(s) for {rc}")
                        currently_distributing = (
                            _dist_state.get("active") and _dist_state.get("code") == rc
                        )
                        if currently_distributing:
                            # Inject directly into the running distribution loop
                            for pid, uname, retry_cnt in rows:
                                save_redemption(rc, pid, uname, "RETRY_PENDING",
                                                "Injected by /retry", retry_cnt)
                            _dist_state["total"] += len(rows)
                            injected_total += len(rows)
                            log.info(f"  ↩️ Injected {len(rows)} player(s) into active distribution (new total: {_dist_state['total']})")
                        else:
                            # Not currently distributing — mark FAILED and queue the code
                            for pid, uname, retry_cnt in rows:
                                save_redemption(rc, pid, uname, "FAILED", "Manual retry queued", retry_cnt)
                            if rc not in list(_code_queue.queue):
                                _code_queue.put(rc)
                            queued_total += len(rows)
                        retried_total += len(rows)

                    if retried_total:
                        parts = []
                        if injected_total:
                            parts.append(f"↩️ <b>{injected_total}</b> injected into active distribution")
                        if queued_total:
                            parts.append(f"🔁 <b>{queued_total}</b> queued for next run")
                        send_telegram(
                            f"🔁 <b>Retrying {retried_total} player(s)</b>\n" + "\n".join(parts),
                            chat_id
                        )
                    else:
                        send_telegram("✅ No players to retry — all are SUCCESS or ALREADY_USED.", chat_id)

                elif cmd == "/pause":
                    if not _dist_state.get("active"):
                        send_telegram("ℹ️ No active distribution.", chat_id)
                    elif _dist_state.get("paused"):
                        send_telegram("⏸ Distribution is already paused.\nUse /resume to continue.", chat_id)
                    else:
                        ctrl_set("dist_cmd", "pause")
                        log.info("⏸ Pause requested via Telegram.")
                        send_telegram(
                            f"⏸ <b>Pause command sent.</b>\n"
                            f"Takes effect after the current player (~10 min).\n"
                            f"Use /resume to continue.", chat_id
                        )

                elif cmd == "/resume":
                    if not _dist_state.get("active"):
                        send_telegram("ℹ️ No active distribution.", chat_id)
                    elif not _dist_state.get("paused"):
                        send_telegram("▶️ Distribution is already running.", chat_id)
                    else:
                        ctrl_set("dist_cmd", "resume")
                        ctrl_set("dist_paused", "0")
                        log.info("▶ Resume requested via Telegram.")
                        send_telegram("▶️ <b>Resume command sent.</b>", chat_id)

                elif cmd == "/cancel":
                    if not _dist_state.get("active"):
                        send_telegram("ℹ️ No active distribution.", chat_id)
                    else:
                        ctrl_set("dist_cmd", "cancel")
                        log.info("⏹ Cancel requested via Telegram.")
                        send_telegram(
                            f"⏹ <b>Cancel command sent.</b>\n"
                            f"Distribution stops after the current player (~10 min).\n"
                            f"Remaining players will be retried automatically.", chat_id
                        )

                elif cmd == "/restart":
                    send_telegram("🔄 <b>Restarting daemon...</b>", chat_id)
                    log.info("🔄 Restart requested via Telegram.")
                    time.sleep(1)
                    os._exit(0)

                elif cmd == "/rebuild":
                    send_telegram("🔨 <b>Rebuilding daemon...</b>\nThis may take a few minutes.", chat_id)
                    log.info("🔨 Rebuild requested via Telegram.")
                    try:
                        import urllib.request
                        req = urllib.request.Request(
                            CONFIG["REBUILD_SERVER_URL"] + "/rebuild",
                            method="POST"
                        )
                        urllib.request.urlopen(req, timeout=10)
                        send_telegram("✅ <b>Rebuild started!</b>", chat_id)
                    except Exception as e:
                        send_telegram(f"❌ <b>Rebuild error:</b> {e}", chat_id)

                elif cmd == "/dist":
                    if _dist_state["active"]:
                        elapsed = ""
                        if _dist_state["started_at"]:
                            start = datetime.fromisoformat(_dist_state["started_at"])
                            mins = int((datetime.now(timezone.utc) - start).total_seconds() / 60)
                            elapsed = f"\n⏱️ Running: {mins} min"
                        paused  = _dist_state.get("paused", False)
                        pending = ctrl_get("dist_cmd")
                        if paused:
                            state_line = "⏸ <b>PAUSED</b>"
                            hint = "\nSend /resume to continue or /cancel to stop."
                        elif pending == "pause":
                            state_line = "⏸ <b>Pause pending...</b> (waits for current player)"
                            hint = ""
                        elif pending == "cancel":
                            state_line = "⏹ <b>Cancel pending...</b> (waits for current player)"
                            hint = ""
                        else:
                            state_line = "🔄 <b>Active Distribution</b>"
                            hint = ""
                        send_telegram(
                            f"{state_line}\n"
                            f"Code: <code>{_dist_state['code']}</code>\n"
                            f"Player: {_dist_state['current_player']} [{_dist_state['current_index']}/{_dist_state['total']}]\n"
                            f"✅ {_dist_state['success']} ⚠️ {_dist_state['already_used']} ❌ {_dist_state['failed']} ⏭️ {_dist_state['skipped']}"
                            f"{elapsed}{hint}",
                            chat_id
                        )
                    else:
                        send_telegram("ℹ️ No active distribution.", chat_id)


                elif cmd == "/chatid":
                    send_telegram(
                        f"🆔 <b>Chat Info</b>\n\n"
                        f"Chat ID: <code>{chat_id}</code>\n"
                        f"Type: {chat_type}\n"
                        f"Name: {chat_name}",
                        chat_id
                    )

                elif cmd == "/help":
                    send_telegram(
                        "🤖 <b>Available Commands:</b>\n\n"
                        "<b>📊 Info</b>\n"
                        "/status — system status &amp; stats\n"
                        "/health — CPU, RAM, temperature\n"
                        "/dist — active distribution status\n"
                        "/players — list all players\n"
                        "/codes — list all codes\n"
                        "/player ID — player details\n"
                        "/logs — last 20 log lines\n\n"
                        "<b>🎁 Distribution</b>\n"
                        "/retry — retry failed players\n"
                        "/pause — pause distribution\n"
                        "/resume — resume distribution\n"
                        "/cancel — cancel distribution\n\n"
                        "<b>⚙️ System</b>\n"
                        "/restart — restart the daemon\n"
                        "/rebuild — rebuild docker image\n"
                        "/chatid — show this chat's ID\n"
                        "/help — show this message",
                        chat_id
                    )

        except Exception as e:
            log.warning(f"Telegram loop error: {e}")

        time.sleep(2)

# ============================================================
#  MAIN LOOP
# ============================================================
def main():
    global _is_first_run

    init_db()

    log.info("🚀 WLF Rewardwolf Daemon v2.1.0 started.")
    log.info(f"   Check interval: {CONFIG['CHECK_INTERVAL_MIN']} minutes")
    log.info(f"   Retry delay: {CONFIG['RETRY_DELAY_HOURS']} hours")
    log.info(f"   Expiry warning: {CONFIG['EXPIRY_WARNING_HOURS']} hours before")
    log.info(f"   Database: {CONFIG['DB_FILE']}")

    # Start Telegram command listener — eski mesajları atla
    init_telegram_offset()
    tg_thread = threading.Thread(target=telegram_command_loop, daemon=True)
    tg_thread.start()

    # Fetch initial data for startup message
    # --- Google Sheets senkronizasyonu DEVRE DIŞI ---
    # players = fetch_player_list()
    # if players:
    #     sync_players(players)
    players = []  # Sheets sync kapalı; oyuncular yalnızca Dashboard üzerinden yönetilir
    active_codes, codes_data = fetch_active_gift_codes(run_expiry_check=False)

    send_telegram(build_startup_message(codes_data))

    # active_codes always initialized before loop references it
    active_codes = active_codes or []
    active_codes = active_codes  # used by code_check_loop via closure

    def code_check_loop():
        """Arka planda her 5 dakikada bir yeni kod ve oyuncu kontrolü yapar."""
        global _is_first_run, active_codes
        while True:
            try:
                log.info("\n🔍 Checking for new gift codes...")
                # --- Google Sheets senkronizasyonu DEVRE DIŞI ---
                # players = fetch_player_list()
                # if players:
                #     added, removed, restored, vip_promoted, vip_demoted = sync_players(players)
                #
                #     # Yeni oyuncular — aktif kodları gönder
                #     if added:
                #         added_names = ', '.join(p.get('username') or p['playerId'] for p in added)
                #         send_telegram(
                #             f"🆕 <b>{len(added)} new player(s)!</b>\n"
                #             f"{added_names}\n"
                #             f"Queuing active codes..."
                #         )
                #         log.info(f"🆕 New player(s): {added_names}")
                #         for code in active_codes:
                #             status_map = get_code_status_map(code)
                #             missing = [p for p in added if status_map.get(p["playerId"]) not in ("SUCCESS", "ALREADY_USED")]
                #             if missing:
                #                 updated = False
                #                 with _code_queue.mutex:
                #                     for i, (qcode, qplayers) in enumerate(_code_queue.queue):
                #                         if qcode == code:
                #                             existing_ids = {p["playerId"] for p in qplayers}
                #                             new_ones = [p for p in missing if p["playerId"] not in existing_ids]
                #                             qplayers.extend(new_ones)
                #                             updated = True
                #                             break
                #                 if not updated:
                #                     _code_queue.put((code, missing))
                #
                #     # Çıkarılan oyuncular — kuyruktan sil
                #     if removed:
                #         removed_ids = {p["playerId"] for p in removed}
                #         removed_names = ', '.join(p.get('username') or p['playerId'] for p in removed)
                #         send_telegram(f"🗑️ <b>{len(removed)} player(s) removed!</b>\n{removed_names}")
                #         log.info(f"🗑️ Removed player(s): {removed_names}")
                #         with _code_queue.mutex:
                #             for i, (qcode, qplayers) in enumerate(_code_queue.queue):
                #                 _code_queue.queue[i] = (qcode, [p for p in qplayers if p["playerId"] not in removed_ids])
                #
                #     # VIP değişiklikleri — kuyruktaki oyuncu sıralamasını güncelle
                #     if vip_promoted or vip_demoted:
                #         fresh_players = get_active_players()
                #         fresh_map = {p["playerId"]: p for p in fresh_players}
                #         with _code_queue.mutex:
                #             for i, (qcode, qplayers) in enumerate(_code_queue.queue):
                #                 updated = [dict(p, is_vip=fresh_map.get(p["playerId"], p).get("is_vip", 0)) for p in qplayers]
                #                 updated.sort(key=lambda p: 0 if p.get("is_vip") else 1)
                #                 _code_queue.queue[i] = (qcode, updated)
                #         log.info(f"⭐ Queue reordered for VIP changes")
                players = []  # Sheets sync kapalı

                active_codes, codes_data = fetch_active_gift_codes(
                    run_expiry_check=not _is_first_run,
                    all_players=players
                )

                # expires_at IS NULL olan aktif kodların expiry'sini ayrıca kontrol et
                refresh_null_expiries()

                # Dağıtım bekleyen (tamamlanmamış) kodlar
                incomplete = [c for c in active_codes if not is_code_completed(c)]
                if not incomplete:
                    log.info("  ℹ️ No pending codes.")

                newly_queued = []
                for code in incomplete:
                    queued         = list(_code_queue.queue)
                    currently_dist = (_dist_state.get("active") and _dist_state.get("code") == code)

                    # Telegram bildirimi — sadece daha önce hiç bildirilmemiş kodlar için
                    conn = db_connect()
                    row_notified = conn.execute(
                        "SELECT notified FROM active_codes WHERE code=?", (code,)
                    ).fetchone()
                    if row_notified and not row_notified["notified"]:
                        send_telegram(
                            f"🎉 <b>New Gift Code Found!</b>\n"
                            f"<pre>{code}</pre>"
                            f"🔄 Queued for distribution..."
                        )
                        send_to_channels("new_code", code=code)
                        conn.execute("UPDATE active_codes SET notified=1 WHERE code=?", (code,))
                        conn.commit()
                    conn.close()

                    # Kuyruğa ekleme — kuyrukta yoksa VE şu an dağıtılmıyorsa
                    if code not in queued and not currently_dist:
                        _code_queue.put(code)
                        newly_queued.append(code)

                if newly_queued:
                    log.info(f"  ➕ Queued for distribution: {newly_queued}")
                elif incomplete:
                    in_progress = [c for c in incomplete if _dist_state.get("active") and _dist_state.get("code") == c]
                    waiting     = [c for c in incomplete if c in list(_code_queue.queue)]
                    log.info(f"  ⏳ In progress: {in_progress or waiting} — already queued/distributing")

                check_health_alerts()
                now = datetime.now(timezone.utc)
                if now.hour == 0 and now.minute < CONFIG["CHECK_INTERVAL_MIN"]:
                    send_daily_summary()

                # Background name sync every 15 minutes
                global _last_name_sync, _last_player_check_ts
                now_ts = time.time()
                if _last_name_sync is None or now_ts - _last_name_sync >= NAME_SYNC_INTERVAL:
                    log.info("🔄 Running background player name sync...")
                    sync_player_names()
                    _last_name_sync = now_ts

                # Yeni oyuncu tespiti — ilk çalışmada sadece timestamp'i kaydet, sıfırlama yapma
                now_iso = datetime.now(timezone.utc).isoformat()
                if _last_player_check_ts is None:
                    # İlk çalışma: mevcut tüm oyuncular "eski", sadece zamanı kaydet
                    _last_player_check_ts = now_iso
                else:
                    try:
                        conn = db_connect()
                        new_players = conn.execute(
                            "SELECT player_id FROM players WHERE removed_at IS NULL AND active_since > ?",
                            (_last_player_check_ts,)
                        ).fetchall()
                        if new_players:
                            pids = [r["player_id"] for r in new_players]
                            log.info(f"🆕 {len(pids)} new player(s) detected: {pids}")
                            conn.execute("""
                                UPDATE active_codes
                                SET is_completed=0
                                WHERE is_currently_active=1
                                  AND is_completed=1
                                  AND (expires_at IS NULL OR expires_at > ?)
                            """, (now_iso,))
                            conn.commit()
                            log.info("♻️ Completed codes reset for new player distribution")
                        conn.close()
                    except Exception as e:
                        log.warning(f"New player check error: {e}")
                    _last_player_check_ts = now_iso

                _is_first_run = False

            except Exception as e:
                log.error(f"Code check loop error: {e}")

            log.info(f"💤 Next check in {CONFIG['CHECK_INTERVAL_MIN']} minutes...")
            time.sleep(CONFIG["CHECK_INTERVAL_MIN"] * 60)

    # Kod kontrol thread'ini başlat
    check_thread = threading.Thread(target=code_check_loop, daemon=True)
    check_thread.start()

    # Ana dağıtım döngüsü — kuyruktan kod alıp dağıtır
    while True:
        try:
            code = _code_queue.get(timeout=30)
            log.info(f"📦 Distributing queued code: {code}")
            results = redeem_code_for_all(code)
            if results:
                send_results_to_sheets(code, results)
                update_code_progress(code, results)
            status_map = get_code_status_map(code)
            pending = [p for p in get_active_players() if status_map.get(p["playerId"]) not in ("SUCCESS", "ALREADY_USED")]
            if not pending:
                mark_code_completed(code, results)
                log.info(f"✅ Code {code} fully completed.")
            else:
                log.info(f"⏳ Code {code} pending for {len(pending)} player(s).")
            retry_failed_players([code], get_active_players())

        except queue.Empty:
            pass  # Kuyruk boş, bekle
        except KeyboardInterrupt:
            log.info("\n⛔ Daemon stopped.")
            send_telegram("⛔ <b>WLF Rewardwolf stopped.</b>")
            break
        except Exception as e:
            log.error(f"Main loop error: {e}")
            send_telegram(f"❌ <b>Critical Error!</b>\n<code>{e}</code>")

if __name__ == "__main__":
    main()
