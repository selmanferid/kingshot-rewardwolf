"""
WLF Rewardwolf — Gift Code Daemon v2.0.2
============================================
- Monitors Kingshot API for new gift codes
- Fetches player list from Google Sheets
- Redeems codes for all players via Selenium (spread over 24h, random intervals)
- Optimized SQLite database with bulk lookups
- Player sync every 5 minutes (add new, soft-delete removed)
- VIP player list (processed first)
- Telegram bot with instant command responses (separate thread)
- RAM/CPU/temperature monitoring with alerts
- Chromium fingerprint randomization
- Retry mechanism for failed redemptions
- Chromium crash recovery
- 72-hour expiry warnings with undelivered player list
- Daily summary report
- New player auto-detection
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
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

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

# Active distribution state (for web UI and /status command)
_dist_state = {
    "active": False,
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
            active_since TEXT NOT NULL,
            removed_at   TEXT
        )
    """)

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
            last_updated     TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS expiry_warnings (
            code      TEXT PRIMARY KEY,
            warned_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    log.info("✅ Database initialized.")

def db_connect():
    conn = sqlite3.connect(CONFIG["DB_FILE"])
    conn.row_factory = sqlite3.Row
    return conn

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
    """Get all active (non-removed) players from DB."""
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT player_id, username, is_vip FROM players WHERE removed_at IS NULL ORDER BY is_vip DESC")
    rows = c.fetchall()
    conn.close()
    return [{"playerId": r["player_id"], "username": r["username"], "is_vip": r["is_vip"]} for r in rows]

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

def get_failed_players(code):
    conn = db_connect()
    c = conn.cursor()
    retry_after = (datetime.now(timezone.utc) - timedelta(hours=CONFIG["RETRY_DELAY_HOURS"])).isoformat()
    c.execute("""
        SELECT player_id, username, retry_count FROM redemptions
        WHERE code=? AND status='FAILED' AND created_at <= ? AND retry_count < 3
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
            if existing["is_currently_active"] == 0:
                # Reactivated — reset completed so missing players get it
                log.info(f"♻️ Code reactivated: {code} — resetting completed status")
                c.execute("""
                    UPDATE active_codes
                    SET is_currently_active=1, is_completed=0,
                        expires_at=?, last_updated=?
                    WHERE code=?
                """, (code_data.get("expiresAt"), now, code))
            else:
                # Update expiry in case it changed
                c.execute("""
                    UPDATE active_codes SET expires_at=?, last_updated=? WHERE code=?
                """, (code_data.get("expiresAt"), now, code))

    # Mark codes not in API as inactive
    for code in db_codes:
        if code not in api_codes:
            c.execute("""
                UPDATE active_codes SET is_currently_active=0, last_updated=? WHERE code=?
            """, (now, code))

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
            save_warning(code)

# ============================================================
#  KINGSHOT API
# ============================================================
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
#  SELENIUM
# ============================================================
def create_driver():
    options = Options()
    if CONFIG["HEADLESS"]:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--no-zygote")
    options.add_argument(f"--window-size={random.choice(SCREEN_SIZES)}")
    options.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")
    options.add_argument(f"--lang={random.choice(['en-US', 'en-GB', 'tr-TR'])}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.binary_location = "/usr/bin/chromium"
    service = Service("/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    driver.execute_cdp_cmd("Network.setUserAgentOverride", {
        "userAgent": random.choice(USER_AGENTS),
        "acceptLanguage": random.choice(LANGUAGES),
        "platform": random.choice(["Win32", "MacIntel", "Linux x86_64"])
    })
    return driver

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
    if any(x in msg_lower for x in ["server busy", "please try again later", "try again later", "too many", "service unavailable", "please log in", "log in to relevant", "character before redemption"]):
        return "SERVER_BUSY", msg_text
    return "UNKNOWN", msg_text

def _attempt_redeem(driver, player_id, gift_code):
    """Single redemption attempt. Returns (status, message)."""
    # Sayfayı yükle, max 3 deneme (sayfa yüklenemezse yenile)
    for page_try in range(3):
        try:
            # Önceki sayfayı temizle
            driver.execute_script("window.stop();")
        except Exception:
            pass
        try:
            driver.get("https://ks-giftcode.centurygame.com/")
        except Exception as e:
            log.warning(f"Page load attempt {page_try+1}/3 driver.get error: {e}")
            time.sleep(5)
            continue
        wait = WebDriverWait(driver, 30)
        try:
            player_input = wait.until(EC.presence_of_element_located(
                (By.XPATH, '//input[@placeholder="Player ID"]')
            ))
            log.info(f"Page loaded OK on attempt {page_try+1}")
            break
        except Exception as e:
            log.warning(f"Page load attempt {page_try+1}/3 input not found: {e}")
            time.sleep(5)
    else:
        raise Exception("Page failed to load after 3 attempts — browser crash")

    # Player ID gir ve doğrula
    player_input.clear()
    player_input.send_keys(player_id)
    time.sleep(0.3)
    # Girilen değeri doğrula
    entered = player_input.get_attribute("value") or ""
    if entered.strip() != str(player_id).strip():
        log.warning(f"Player ID input mismatch: expected {player_id}, got {entered} — retrying")
        player_input.clear()
        time.sleep(0.5)
        player_input.send_keys(player_id)

    code_input = driver.find_element(By.XPATH, '//input[@placeholder="Enter Gift Code"]')
    code_input.clear()
    code_input.send_keys(gift_code)
    time.sleep(0.3)
    # Kod girişini doğrula
    entered_code = code_input.get_attribute("value") or ""
    if entered_code.strip() != str(gift_code).strip():
        log.warning(f"Gift code input mismatch — retrying")
        code_input.clear()
        time.sleep(0.5)
        code_input.send_keys(gift_code)

    login_btn = wait.until(EC.element_to_be_clickable(
        (By.XPATH, '//div[contains(@class, "login_btn") and contains(@class, "btn")]')
    ))
    login_btn.click()

    wait.until(EC.invisibility_of_element_located(
        (By.XPATH, '//div[contains(@class, "loading")]')
    ))
    time.sleep(1)

    # msg'de "please enter your player id" varsa ID girilmemiş — hata
    try:
        msg_el = driver.find_element(By.XPATH, '//p[contains(@class, "msg")]')
        early_text = msg_el.text.strip().lower()
        if "please enter your player id" in early_text:
            log.warning(f"Player ID not entered properly for {player_id}, retrying page")
            return "RETRY_PAGE", "Player ID not entered"
    except Exception:
        pass

    # Exchange butonunun disabled class'ının kalkmasını bekle (max 15s)
    try:
        for _ in range(30):
            exchange_btn = driver.find_element(By.XPATH, '//div[contains(@class, "exchange_btn")]')
            btn_class = exchange_btn.get_attribute("class") or ""
            if "disabled" not in btn_class:
                break
            time.sleep(0.5)
        else:
            log.debug("Exchange button still disabled after 15s")
    except Exception as e:
        log.debug(f"Exchange button check error: {e}")

    try:
        confirm_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, '//div[contains(@class, "exchange_btn") and contains(text(), "Confirm")]')
        ))
        driver.execute_script("arguments[0].click();", confirm_btn)
        time.sleep(1.5)
    except Exception as e:
        log.debug(f"Confirm button not found: {e}")

    KNOWN_PHRASES = [
        "please claim", "already claimed", "unable to claim again",
        "not found", "case-sensitive", "server busy", "please try again",
        "please log in", "log in to relevant", "redeemed", "gift code",
        "expired", "invalid", "too many", "service unavailable",
    ]
    msg_text = ""
    try:
        # msg elementi metin içerene kadar max 60 saniye bekle
        for _ in range(120):
            try:
                msg_el = driver.find_element(By.XPATH, '//p[contains(@class, "msg")]')
                txt = msg_el.text.strip()
                if txt and any(p in txt.lower() for p in KNOWN_PHRASES):
                    msg_text = txt
                    break
                elif txt:
                    # Metin var ama tanınmıyor — devam et, belki doluyor
                    pass
            except Exception:
                pass
            time.sleep(0.5)
        else:
            # 60 saniye doldu
            try:
                msg_el = driver.find_element(By.XPATH, '//p[contains(@class, "msg")]')
                msg_text = msg_el.text.strip()
                if msg_text:
                    log.warning(f"Unknown modal text after 60s: '{msg_text}'")
            except Exception:
                pass
    except Exception:
        msg_text = ""

    return parse_message(msg_text)


def redeem_code_for_player(driver, player_id, username, gift_code, retry_count=0):
    result = {
        "playerId":   player_id,
        "username":   username,
        "status":     "FAILED",
        "message":    "No response from site",
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "retryCount": retry_count,
    }

    try:
        driver.execute_cdp_cmd("Network.setUserAgentOverride", {
            "userAgent": random.choice(USER_AGENTS),
            "acceptLanguage": random.choice(LANGUAGES),
            "platform": random.choice(["Win32", "MacIntel", "Linux x86_64"])
        })
    except Exception as e:
        log.debug(f"User-agent rotation skipped: {e}")

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            status, message = _attempt_redeem(driver, player_id, gift_code)

            if status == "SERVER_BUSY":
                wait_sec = 120 * attempt  # 2min, 4min, 6min
                log.warning(f"  ⏳ Server busy for {player_id} ({username}) — waiting {wait_sec}s before retry ({attempt}/{max_attempts})")
                send_telegram(
                    f"⏳ <b>Server Busy</b>\n"
                    f"Player: {username} (<code>{player_id}</code>)\n"
                    f"Retry {attempt}/{max_attempts} in {wait_sec}s"
                )
                time.sleep(wait_sec)
                continue

            if status == "RETRY_PAGE":
                log.warning(f"  ↩️ Page issue for {player_id} ({username}), retrying ({attempt}/{max_attempts})")
                time.sleep(2)
                continue

            result["status"]  = status
            result["message"] = message
            return result

        except Exception as e:
            # Clean up selenium stacktrace — only show first line
            err_lines = str(e).splitlines()
            clean_err = err_lines[0] if err_lines else str(e)
            log.warning(f"  ⚠️ Attempt {attempt}/{max_attempts} failed for {player_id} ({username}): {clean_err}")
            # Browser crash — dışarıya fırlat ki ana loop yeniden başlatsın
            try:
                driver.quit()
            except Exception:
                pass
            raise

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

def redeem_code_for_all(gift_code, players, is_retry=False):
    log.info(f"\n{'='*50}")
    log.info(f"🎁 Redeeming: {gift_code}{'  [RETRY]' if is_retry else ''}")
    log.info(f"👥 Total players: {len(players)}")

    vip_ids = get_vip_player_ids()

    # Single bulk query for all processed statuses
    status_map = get_code_status_map(gift_code)

    total_players = len(players)
    to_process = []
    skipped_success = 0
    skipped_already_used = 0

    for idx, p in enumerate(players, 1):
        pid = p["playerId"]
        uname = p.get("username") or pid
        vtag = " ⭐" if pid in vip_ids else ""
        existing = status_map.get(pid)
        if existing == "SUCCESS":
            log.info(f"  ⏭️  [{idx}/{total_players}] {uname}{vtag} — skipped (SUCCESS)")
            skipped_success += 1
        elif existing == "ALREADY_USED":
            log.info(f"  ⏭️  [{idx}/{total_players}] {uname}{vtag} — skipped (ALREADY_USED)")
            skipped_already_used += 1

        else:
            to_process.append((p, idx))

    total_skipped = skipped_success + skipped_already_used
    log.info(f"⏭️  Skipped: {total_skipped} | 🔄 To process: {len(to_process)}")
    log.info(f"{'='*50}")

    if not to_process:
        log.info("✅ All players already processed.")
        return []

    results = []
    driver = None
    i = 0

    # Update global distribution state
    _dist_state.update({
        "active": True,
        "code": gift_code,
        "current_player": None,
        "current_index": 0,
        "total": total_players,
        "success": 0,
        "already_used": 0,
        "failed": 0,
        "skipped": total_skipped,
        "started_at": datetime.now(timezone.utc).isoformat(),
    })

    while i < len(to_process):
        # Check if code expired before processing next player
        if is_code_expired(gift_code):
            log.warning(f"⏰ Code {gift_code} has expired (UTC). Stopping distribution.")
            delivered = sum(1 for r in results if r["status"] == "SUCCESS")
            send_telegram(
                f"⏰ <b>Code Expired!</b>\n"
                f"Code: <code>{gift_code}</code>\n"
                f"Stopped at [{to_process[i][1]}/{total_players}]\n"
                f"✅ Delivered before expiry: {delivered}"
            )
            break

        player, global_idx = to_process[i]
        pid      = player["playerId"]
        username = player.get("username", "")
        is_vip   = pid in vip_ids
        vip_tag  = " ⭐" if is_vip else ""

        if driver is None:
            try:
                driver = create_driver()
                log.info("🌐 Browser started.")
            except Exception as e:
                log.error(f"Failed to start browser: {e}")
                send_telegram(f"❌ <b>Browser Error:</b>\n<code>{e}</code>")
                break

        log.info(f"🔄 [{global_idx}/{total_players}] {pid} ({username}){vip_tag}")
        _dist_state["current_player"] = username or pid
        _dist_state["current_index"] = global_idx

        try:
            result = redeem_code_for_player(driver, pid, username, gift_code)
            results.append(result)
            save_redemption(gift_code, pid, username, result["status"], result["message"])

            status_icon = {"SUCCESS": "✅", "ALREADY_USED": "⚠️", "INVALID_CODE": "❌", "FAILED": "❌", "UNKNOWN": "❓", "SERVER_BUSY": "🔄"}.get(result["status"], "❓")
            if result["status"] == "SUCCESS": _dist_state["success"] += 1
            elif result["status"] == "ALREADY_USED": _dist_state["already_used"] += 1
            elif result["status"] in ("FAILED","INVALID_CODE","UNKNOWN","SERVER_BUSY"): _dist_state["failed"] += 1
            log.info(f"  {status_icon} {result['status']}: {result['message']}")

            tg_extra = ""
            if result["status"] == "FAILED":
                tg_extra = f"\n🔄 Will retry in {CONFIG['RETRY_DELAY_HOURS']} hours"
            process_idx = i + 1  # 1-based işlem sırası
            process_total = len(to_process)
            # DB'den güncel toplam sayıları çek
            conn = db_connect()
            db_success = conn.execute(
                "SELECT COUNT(*) FROM redemptions WHERE code=? AND status='SUCCESS'", (gift_code,)
            ).fetchone()[0]
            db_already_used = conn.execute(
                "SELECT COUNT(*) FROM redemptions WHERE code=? AND status='ALREADY_USED'", (gift_code,)
            ).fetchone()[0]
            db_failed = conn.execute(
                "SELECT COUNT(*) FROM redemptions WHERE code=? AND status='FAILED'", (gift_code,)
            ).fetchone()[0]
            conn.close()
            db_completed = db_success + db_already_used
            send_telegram(
                f"{status_icon} <b>[{process_idx}/{process_total}] {username or pid}{vip_tag}</b>\n"
                f"Code: <code>{gift_code}</code>\n"
                f"Status: {result['status']}\n"
                f"Message: {result['message']}\n"
                f"✅ {db_completed} | ❌ {db_failed} — {total_players} total"
                f"{tg_extra}"
            )

            i += 1

            # Her oyuncudan sonra browser'ı kapat — uzun bekleme süresinde memory şişmesini önler
            try:
                driver.quit()
            except Exception:
                pass
            kill_zombie_chromium()
            driver = None

            if i < len(to_process):
                avg_delay = (24 * 60 * 60) / 100
                delay = random.randint(int(avg_delay * 0.7), int(avg_delay * 1.3))
                log.info(f"  ⏳ Next player in {delay}s (~{delay//60}min)...")
                time.sleep(delay)

        except Exception as e:
            log.error(f"  💥 Browser crashed for {pid}: {e}")
            try:
                driver.quit()
            except Exception:
                pass
            kill_zombie_chromium()
            driver = None
            log.info(f"  🔄 Restarting browser in 10s...")
            time.sleep(10)
            # Browser yeniden açılamazsa 30 saniye bekle ve tekrar dene
            for restart_try in range(5):
                try:
                    driver = create_driver()
                    log.info("  🌐 Browser restarted successfully.")
                    break
                except Exception as ce:
                    log.warning(f"  ⚠️ Browser restart attempt {restart_try+1}/5 failed: {ce} — waiting 30s")
                    time.sleep(30)
            else:
                log.error("  ❌ Browser could not be restarted after 5 attempts. Skipping player.")
                send_telegram(f"❌ <b>Browser restart failed!</b>\nPlayer: {username} (<code>{pid}</code>) skipped.")
                result = {"playerId": pid, "username": username, "status": "FAILED",
                          "message": "Browser could not restart", "timestamp": datetime.now(timezone.utc).isoformat(), "retryCount": 0}
                results.append(result)
                save_redemption(gift_code, pid, username, "FAILED", "Browser could not restart")
                i += 1

    if driver:
        try:
            driver.quit()
        except Exception as e:
            log.debug(f"Driver quit error: {e}")
        kill_zombie_chromium()

    success      = sum(1 for r in results if r["status"] == "SUCCESS")
    already_used = sum(1 for r in results if r["status"] == "ALREADY_USED")
    failed       = sum(1 for r in results if r["status"] in ("FAILED", "INVALID_CODE", "UNKNOWN"))

    log.info(f"\n📊 Summary — {gift_code}: ✅{success} ⚠️{already_used} ❌{failed} ⏭️{total_skipped}")
    send_telegram(
        f"📊 <b>Redemption Complete!</b>\n"
        f"Code: <code>{gift_code}</code>\n\n"
        f"✅ Success: {success}\n"
        f"⚠️ Already used: {already_used}\n"
        f"❌ Failed: {failed}\n"
        f"⏭️ Skipped: {total_skipped}\n"
        f"👥 Total: {total_players}"
    )

    return results

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
        driver = None
        try:
            driver = create_driver()
            for player_id, username, retry_count in failed_rows:
                log.info(f"  🔁 Retry #{retry_count+1}: {player_id} ({username})")
                result = redeem_code_for_player(driver, player_id, username, code, retry_count + 1)
                save_redemption(code, player_id, username, result["status"], result["message"], retry_count + 1)
                icon = {"SUCCESS": "✅", "ALREADY_USED": "⚠️"}.get(result["status"], "❌")
                log.info(f"    {icon} {result['status']}: {result['message']}")
                time.sleep(random.randint(30, 60))
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception as e:
                    log.debug(f"Driver quit error: {e}")

# ============================================================
#  STARTUP MESSAGE
# ============================================================
def build_startup_message(active_codes_data):
    total_codes, success, already_used, failed, total_players, total_vip = get_db_stats()
    health = get_system_health()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    msg = (
        f"🚀 <b>WLF Rewardwolf v2.0.2</b> — {now_str}\n\n"
        f"👥 Players: {total_players} ({total_vip} VIP)\n"
        f"🎁 Codes processed: {total_codes}\n"
        f"💻 CPU {health['cpu_load']}% | RAM {health['ram_percent']}% | Temp {health['temp_c']}°C\n"
    )

    now = datetime.now(timezone.utc)
    db_codes = get_active_codes_details()
    active_db = [r for r in db_codes if r["is_currently_active"]]
    inactive_db = [r for r in db_codes if not r["is_currently_active"]]

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
            delivered = sum(1 for s in status_map.values() if s == "SUCCESS")
            already = sum(1 for s in status_map.values() if s == "ALREADY_USED")
            pending = total_players - delivered - already

            if r["is_completed"]:
                progress = f"✅ Complete — {delivered}/{total_players} delivered"
            elif delivered > 0 or already > 0:
                progress = f"🔄 In progress — {delivered+already}/{total_players}, {pending} pending"
            else:
                progress = "⏳ Not started"

            msg += (
                f"\n• <code>{code}</code>\n"
                f"  📅 Created: {created} | ⏰ Expires: {exp_str}\n"
                f"  {progress}\n"
            )
    else:
        msg += "\nℹ️ No active codes.\n"

    if inactive_db:
        msg += f"\n⚫ <b>Inactive Codes ({len(inactive_db)}):</b> "
        msg += ", ".join(f"<code>{r['code']}</code>" for r in inactive_db) + "\n"

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
                chat_id = str(msg.get("chat", {}).get("id", ""))
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
                    send_telegram("🔁 Retry will trigger on next check cycle.", chat_id)

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
                        send_telegram(
                            f"🔄 <b>Active Distribution</b>\n"
                            f"Code: <code>{_dist_state['code']}</code>\n"
                            f"Player: {_dist_state['current_player']} [{_dist_state['current_index']}/{_dist_state['total']}]\n"
                            f"✅ {_dist_state['success']} ⚠️ {_dist_state['already_used']} ❌ {_dist_state['failed']} ⏭️ {_dist_state['skipped']}"
                            f"{elapsed}",
                            chat_id
                        )
                    else:
                        send_telegram("ℹ️ No active distribution.", chat_id)

                elif cmd == "/help":
                    send_telegram(
                        "🤖 <b>Available Commands:</b>\n\n"
                        "/status — system status & stats\n"
                        "/health — CPU, RAM, temperature\n"
                        "/dist — active distribution status\n"
                        "/players — list all players\n"
                        "/codes — list all codes with details\n"
                        "/player ID — specific player stats\n"
                        "/logs — last 20 log lines\n"
                        "/retry — retry failed players\n"
                        "/restart — restart the daemon\n"
                        "/rebuild — rebuild docker image\n"
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

    log.info("🚀 WLF Rewardwolf Daemon v2.0.2 started.")
    log.info(f"   Check interval: {CONFIG['CHECK_INTERVAL_MIN']} minutes")
    log.info(f"   Retry delay: {CONFIG['RETRY_DELAY_HOURS']} hours")
    log.info(f"   Expiry warning: {CONFIG['EXPIRY_WARNING_HOURS']} hours before")
    log.info(f"   Database: {CONFIG['DB_FILE']}")

    # Start Telegram command listener — eski mesajları atla
    init_telegram_offset()
    tg_thread = threading.Thread(target=telegram_command_loop, daemon=True)
    tg_thread.start()

    # Fetch initial data for startup message
    players = fetch_player_list()
    if players:
        sync_players(players)
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
                players = fetch_player_list()
                if players:
                    added, removed, restored, vip_promoted, vip_demoted = sync_players(players)

                    # Yeni oyuncular — aktif kodları gönder
                    if added:
                        added_names = ', '.join(p.get('username') or p['playerId'] for p in added)
                        send_telegram(
                            f"🆕 <b>{len(added)} new player(s)!</b>\n"
                            f"{added_names}\n"
                            f"Queuing active codes..."
                        )
                        log.info(f"🆕 New player(s): {added_names}")
                        for code in active_codes:
                            status_map = get_code_status_map(code)
                            missing = [p for p in added if status_map.get(p["playerId"]) not in ("SUCCESS", "ALREADY_USED")]
                            if missing:
                                # Kuyrukta bu kod varsa oyuncuları ekle, yoksa yeni giriş oluştur
                                updated = False
                                with _code_queue.mutex:
                                    for i, (qcode, qplayers) in enumerate(_code_queue.queue):
                                        if qcode == code:
                                            existing_ids = {p["playerId"] for p in qplayers}
                                            new_ones = [p for p in missing if p["playerId"] not in existing_ids]
                                            qplayers.extend(new_ones)
                                            updated = True
                                            break
                                if not updated:
                                    _code_queue.put((code, missing))

                    # Çıkarılan oyuncular — kuyruktan sil
                    if removed:
                        removed_ids = {p["playerId"] for p in removed}
                        removed_names = ', '.join(p.get('username') or p['playerId'] for p in removed)
                        send_telegram(f"🗑️ <b>{len(removed)} player(s) removed!</b>\n{removed_names}")
                        log.info(f"🗑️ Removed player(s): {removed_names}")
                        with _code_queue.mutex:
                            for i, (qcode, qplayers) in enumerate(_code_queue.queue):
                                _code_queue.queue[i] = (qcode, [p for p in qplayers if p["playerId"] not in removed_ids])

                    # VIP değişiklikleri — kuyruktaki oyuncu sıralamasını güncelle
                    if vip_promoted or vip_demoted:
                        fresh_players = get_active_players()
                        fresh_map = {p["playerId"]: p for p in fresh_players}
                        with _code_queue.mutex:
                            for i, (qcode, qplayers) in enumerate(_code_queue.queue):
                                # is_vip bilgisini güncelle
                                updated = [dict(p, is_vip=fresh_map.get(p["playerId"], p).get("is_vip", 0)) for p in qplayers]
                                # VIP önce gelecek şekilde sırala
                                updated.sort(key=lambda p: 0 if p.get("is_vip") else 1)
                                _code_queue.queue[i] = (qcode, updated)
                        log.info(f"⭐ Queue reordered for VIP changes")

                active_codes, codes_data = fetch_active_gift_codes(
                    run_expiry_check=not _is_first_run,
                    all_players=players
                )
                new_codes = [c for c in active_codes if not is_code_completed(c)]

                if not new_codes:
                    log.info("  ℹ️ No new codes.")
                else:
                    log.info(f"  🎉 {len(new_codes)} new/incomplete code(s): {new_codes}")
                    for code in new_codes:
                        # Kuyruğa zaten ekli değilse ekle
                        queued = list(_code_queue.queue)
                        if not any(c == code for c, _ in queued):
                            all_players = get_active_players()
                            send_telegram(
                                f"🎉 <b>New Gift Code Found!</b>\n"
                                f"Code: <code>{code}</code>\n"
                                f"Queued for distribution..."
                            )
                            _code_queue.put((code, all_players))

                check_health_alerts()
                now = datetime.now(timezone.utc)
                if now.hour == 0 and now.minute < CONFIG["CHECK_INTERVAL_MIN"]:
                    send_daily_summary()
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
            code, players = _code_queue.get(timeout=30)
            log.info(f"📦 Distributing queued code: {code} for {len(players)} player(s)")
            results = redeem_code_for_all(code, players)
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
