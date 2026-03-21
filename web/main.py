"""
WLF Rewardwolf — Web Dashboard v2.0.2
"""
import os
import json
import sqlite3
import subprocess
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import jwt
from passlib.context import CryptContext

# ── Config ────────────────────────────────────────────────
DB_PATH     = os.getenv("DB_PATH",     "/app/data/kingshot.db")
LOG_PATH    = os.getenv("LOG_PATH",    "/app/data/kingshot_daemon.log")
CONFIG_PATH = os.getenv("CONFIG_PATH", "/app/data/web_config.json")
SECRET_KEY  = os.getenv("JWT_SECRET",  "changeme")
ADMIN_USER  = os.getenv("ADMIN_USER",  "admin")
ADMIN_PASS  = os.getenv("ADMIN_PASS",  "kingshot123")
COMPOSE_DIR = os.getenv("COMPOSE_DIR", "/home/selman/kingshot")
REBUILD_SERVER_URL = os.getenv("REBUILD_SERVER_URL", "http://192.168.1.36:9999")
DOCKER_TCP_URL = os.getenv("DOCKER_TCP_URL", "http://192.168.1.36:2375")
ALGORITHM   = "HS256"
TOKEN_EXPIRE = 60 * 24

app = FastAPI(title="WLF Rewardwolf", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# ── Auth ──────────────────────────────────────────────────
def create_token(username):
    exp = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRE)
    return jwt.encode({"sub": username, "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload["sub"]
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

@app.post("/api/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    if form.username != ADMIN_USER or form.password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"access_token": create_token(form.username), "token_type": "bearer"}

# ── DB ────────────────────────────────────────────────────
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ── Dashboard ─────────────────────────────────────────────
@app.get("/api/dashboard")
def dashboard(_=Depends(verify_token)):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM players WHERE removed_at IS NULL")
    total_players = c.fetchone()["cnt"]
    c.execute("SELECT COUNT(*) as cnt FROM players WHERE is_vip=1 AND removed_at IS NULL")
    total_vip = c.fetchone()["cnt"]
    c.execute("""
        SELECT code, created_at, expires_at, is_currently_active, is_completed,
               total, success, already_used, failed
        FROM active_codes
        ORDER BY is_currently_active DESC,
                 CASE WHEN expires_at IS NULL THEN '9999' ELSE expires_at END ASC
    """)
    codes = [dict(r) for r in c.fetchall()]
    # Gerçek zamanlı istatistikler redemptions tablosundan
    c.execute("SELECT COUNT(*) as cnt FROM redemptions WHERE status='SUCCESS'")
    total_success = c.fetchone()["cnt"]
    c.execute("SELECT COUNT(*) as cnt FROM redemptions WHERE status='ALREADY_USED'")
    total_already_used = c.fetchone()["cnt"]
    c.execute("SELECT COUNT(*) as cnt FROM redemptions WHERE status='FAILED'")
    total_failed = c.fetchone()["cnt"]
    c.execute("SELECT COUNT(DISTINCT code) as cnt FROM active_codes")
    total_codes = c.fetchone()["cnt"]
    codes_raw = conn.execute("""
        SELECT ac.code, ac.is_currently_active, ac.is_completed, ac.expires_at, ac.created_at,
               ac.player_count,
               COALESCE(SUM(CASE WHEN r.status='SUCCESS' THEN 1 ELSE 0 END), 0) as success,
               COALESCE(SUM(CASE WHEN r.status='ALREADY_USED' THEN 1 ELSE 0 END), 0) as already_used,
               COALESCE(SUM(CASE WHEN r.status='FAILED' THEN 1 ELSE 0 END), 0) as failed
        FROM active_codes ac
        LEFT JOIN redemptions r ON r.code = ac.code
        GROUP BY ac.code
        ORDER BY ac.is_currently_active DESC, ac.created_at DESC
    """).fetchall()
    conn.close()
    health = get_health_data()
    return {
        # Yeni format
        "total_players": total_players,
        "vip_count": total_vip,
        "total_codes": total_codes,
        "success": total_success,
        "already_used": total_already_used,
        "failed": total_failed,
        "health": health,
        # Eski frontend uyumluluğu
        "players": {"total": total_players, "vip": total_vip},
        "stats": {
            "total_redemptions": total_success + total_already_used + total_failed,
            "total_success_all": total_success,
            "success": total_success,
            "already_used": total_already_used,
            "failed": total_failed,
        },
        "codes": [dict(r) for r in codes_raw],
    }

# ── Players ───────────────────────────────────────────────
@app.get("/api/players")
def list_players(_=Depends(verify_token)):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT player_id, username, is_vip, active_since, removed_at FROM players ORDER BY is_vip DESC, username ASC")
    players = [dict(r) for r in c.fetchall()]
    conn.close()
    return players

class PlayerAdd(BaseModel):
    player_id: str
    username: str
    is_vip: bool = False

class PlayerUpdate(BaseModel):
    username: Optional[str] = None
    is_vip: Optional[bool] = None

@app.post("/api/players")
def add_player(p: PlayerAdd, _=Depends(verify_token)):
    conn = db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO players (player_id, username, is_vip, active_since) VALUES (?, ?, ?, ?)",
              (p.player_id, p.username, int(p.is_vip), datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.patch("/api/players/{player_id}")
def update_player(player_id: str, update: PlayerUpdate, _=Depends(verify_token)):
    conn = db()
    c = conn.cursor()
    if update.username is not None:
        c.execute("UPDATE players SET username=? WHERE player_id=?", (update.username, player_id))
    if update.is_vip is not None:
        c.execute("UPDATE players SET is_vip=? WHERE player_id=?", (int(update.is_vip), player_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/api/players/{player_id}")
def remove_player(player_id: str, _=Depends(verify_token)):
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE players SET removed_at=? WHERE player_id=?",
              (datetime.now(timezone.utc).isoformat(), player_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/players/{player_id}/restore")
def restore_player(player_id: str, _=Depends(verify_token)):
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE players SET removed_at=NULL WHERE player_id=?", (player_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/players/{player_id}/history")
def player_history(player_id: str, _=Depends(verify_token)):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT player_id, username, is_vip, active_since, removed_at FROM players WHERE player_id=?", (player_id,))
    player = dict(c.fetchone() or {})
    c.execute("""
        SELECT r.code, r.status, r.message, r.created_at, r.retry_count,
               ac.expires_at
        FROM redemptions r
        LEFT JOIN active_codes ac ON ac.code = r.code
        WHERE r.player_id=? ORDER BY r.created_at DESC
    """, (player_id,))
    history = [dict(r) for r in c.fetchall()]
    conn.close()
    return {"player": player, "history": history}

# ── Codes ─────────────────────────────────────────────────
@app.get("/api/codes")
def list_codes(_=Depends(verify_token)):
    conn = db()
    c = conn.cursor()
    c.execute("""
        SELECT ac.code, ac.created_at, ac.expires_at, ac.is_currently_active, ac.is_completed, ac.last_updated,
               COALESCE(ac.player_count, 0) as player_count,
               COALESCE(SUM(CASE WHEN r.status='SUCCESS' THEN 1 ELSE 0 END), 0) as success,
               COALESCE(SUM(CASE WHEN r.status='ALREADY_USED' THEN 1 ELSE 0 END), 0) as already_used,
               COALESCE(SUM(CASE WHEN r.status='FAILED' THEN 1 ELSE 0 END), 0) as failed,
               COUNT(r.player_id) as total
        FROM active_codes ac
        LEFT JOIN redemptions r ON r.code = ac.code
        GROUP BY ac.code
        ORDER BY ac.is_currently_active DESC, ac.created_at DESC
    """)
    codes = [dict(r) for r in c.fetchall()]
    conn.close()
    return codes

@app.get("/api/codes/{code}/players")
def code_players(code: str, _=Depends(verify_token)):
    conn = db()
    c = conn.cursor()
    c.execute("""
        SELECT p.player_id, p.username, p.is_vip,
               r.status, r.message, r.created_at, r.retry_count
        FROM players p
        LEFT JOIN redemptions r ON r.player_id=p.player_id AND r.code=?
        WHERE p.removed_at IS NULL
        ORDER BY p.is_vip DESC, p.username ASC
    """, (code,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

# ── Logs ──────────────────────────────────────────────────
@app.get("/api/logs")
def get_logs(lines: int = 100, search: str = "", level: str = "ALL", _=Depends(verify_token)):
    try:
        result = subprocess.run(["tail", "-n", str(lines * 3), LOG_PATH], capture_output=True, text=True)
        all_lines = result.stdout.splitlines()
        filtered = []
        for line in all_lines:
            if level != "ALL":
                if f"[{level}]" not in line:
                    if level == "SUCCESS" and "✅ SUCCESS" not in line:
                        continue
                    elif level not in ("SUCCESS",) and f"[{level}]" not in line:
                        continue
            if search and search.lower() not in line.lower():
                continue
            filtered.append(line)
        return {"logs": "\n".join(filtered[-lines:])}
    except Exception as e:
        return {"logs": f"Error: {e}"}

# ── Docker Control ────────────────────────────────────────
def rebuild_server(path):
    """Rebuild server üzerinden Docker komutlarını çalıştır."""
    import urllib.request
    req = urllib.request.Request(f"{REBUILD_SERVER_URL}{path}", method="POST")
    resp = urllib.request.urlopen(req, timeout=10)
    return resp.read().decode()

@app.post("/api/daemon/start")
def daemon_start(_=Depends(verify_token)):
    try:
        out = rebuild_server("/start")
        return {"ok": True, "output": out}
    except Exception as e:
        return {"ok": False, "output": str(e)}

@app.post("/api/daemon/stop")
def daemon_stop(_=Depends(verify_token)):
    try:
        out = rebuild_server("/stop")
        return {"ok": True, "output": out}
    except Exception as e:
        return {"ok": False, "output": str(e)}

@app.post("/api/daemon/restart")
def daemon_restart(_=Depends(verify_token)):
    try:
        out = rebuild_server("/restart")
        return {"ok": True, "output": out}
    except Exception as e:
        return {"ok": False, "output": str(e)}

@app.post("/api/daemon/rebuild")
def daemon_rebuild(_=Depends(verify_token)):
    try:
        import urllib.request
        req = urllib.request.Request(REBUILD_SERVER_URL + "/rebuild", method="POST")
        urllib.request.urlopen(req, timeout=10)
        return {"ok": True, "output": "Rebuild started"}
    except Exception as e:
        return {"ok": False, "output": str(e)}

@app.get("/api/daemon/status")
def daemon_status(_=Depends(verify_token)):
    try:
        import urllib.request
        # Docker TCP API üzerinden container durumunu kontrol et
        req = urllib.request.Request(DOCKER_TCP_URL + "/containers/kingshot-daemon/json")
        resp = urllib.request.urlopen(req, timeout=3)
        data = json.loads(resp.read())
        status = data.get("State", {}).get("Status", "unknown")
        running = data.get("State", {}).get("Running", False)
        return {"status": status, "running": running}
    except Exception:
        # Fallback: DB'ye bağlanabiliyorsa running say
        try:
            conn = db()
            conn.execute("SELECT 1")
            conn.close()
            return {"status": "running", "running": True}
        except Exception:
            return {"status": "unknown", "running": False}

# ── Telegram ──────────────────────────────────────────────
class TelegramMsg(BaseModel):
    message: str

@app.post("/api/telegram/send")
def telegram_send(msg: TelegramMsg, _=Depends(verify_token)):
    token = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise HTTPException(status_code=400, detail="Telegram not configured")
    import requests as req
    r = req.post(f"https://api.telegram.org/bot{token}/sendMessage",
                 json={"chat_id": chat_id, "text": msg.message, "parse_mode": "HTML"}, timeout=10)
    return {"ok": r.ok}

# ── Settings ──────────────────────────────────────────────
def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {
        "CHECK_INTERVAL_MIN": 5,
        "RETRY_DELAY_HOURS": 2,
        "EXPIRY_WARNING_HOURS": 72,
        "CPU_ALERT_THRESHOLD": 80,
        "RAM_ALERT_THRESHOLD": 85,
        "TEMP_ALERT_THRESHOLD": 75,
        "TELEGRAM_TOKEN": os.getenv("TELEGRAM_TOKEN", ""),
        "TELEGRAM_CHAT_ID": os.getenv("TELEGRAM_CHAT_ID", ""),
    }

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

@app.get("/api/settings")
def get_settings(_=Depends(verify_token)):
    return load_config()

@app.post("/api/settings")
def update_settings(settings: dict, _=Depends(verify_token)):
    cfg = load_config()
    cfg.update(settings)
    save_config(cfg)
    return {"ok": True}

# ── Daemon file edit ──────────────────────────────────────
DAEMON_FILE = "/app/data/../kingshot_giftcode_daemon.py"

@app.get("/api/daemon/file")
def get_daemon_file(_=Depends(verify_token)):
    path = os.path.join(COMPOSE_DIR, "kingshot_giftcode_daemon.py")
    try:
        with open(path, "r") as f:
            return {"content": f.read()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/daemon/file")
def save_daemon_file(body: dict, _=Depends(verify_token)):
    path = os.path.join(COMPOSE_DIR, "kingshot_giftcode_daemon.py")
    try:
        with open(path, "w") as f:
            f.write(body["content"])
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Sheets sync ───────────────────────────────────────────
@app.post("/api/sync/sheets")
def sync_sheets(_=Depends(verify_token)):
    sheets_url = os.getenv("SHEETS_WEB_APP_URL", "")
    if not sheets_url:
        raise HTTPException(status_code=400, detail="Sheets URL not configured")
    import requests as req
    r = req.get(sheets_url, timeout=60)
    data = r.json()
    if not data.get("success"):
        raise HTTPException(status_code=500, detail="Sheets sync failed")
    players = data["players"]
    conn = db()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    added = 0
    for p in players:
        result = c.execute("INSERT OR IGNORE INTO players (player_id, username, is_vip, active_since) VALUES (?, ?, 0, ?)",
                          (p["playerId"], p.get("username", ""), now))
        if result.rowcount > 0:
            added += 1
    conn.commit()
    conn.close()
    return {"ok": True, "total": len(players), "added": added}

# ── Health ────────────────────────────────────────────────
def get_health_data():
    health = {}
    try:
        result = subprocess.run(["cat", "/proc/loadavg"], capture_output=True, text=True)
        load = float(result.stdout.split()[0])
        health["cpu"] = round(load * 100 / (os.cpu_count() or 1), 1)
    except Exception:
        health["cpu"] = 0
    try:
        result = subprocess.run(["cat", "/proc/meminfo"], capture_output=True, text=True)
        mem = {}
        for line in result.stdout.splitlines():
            parts = line.split()
            if parts[0] in ("MemTotal:", "MemAvailable:"):
                mem[parts[0]] = int(parts[1])
        total = mem.get("MemTotal:", 1)
        avail = mem.get("MemAvailable:", 0)
        health["ram"] = round((total - avail) / total * 100, 1)
        health["ram_used_mb"] = round((total - avail) / 1024)
        health["ram_total_mb"] = round(total / 1024)
    except Exception:
        health["ram"] = 0
        health["ram_used_mb"] = 0
        health["ram_total_mb"] = 0
    try:
        result = subprocess.run(["cat", "/sys/class/thermal/thermal_zone0/temp"], capture_output=True, text=True)
        health["temp"] = round(int(result.stdout.strip()) / 1000, 1)
    except Exception:
        health["temp"] = 0
    return health

@app.get("/api/health")
def health(_=Depends(verify_token)):
    return get_health_data()

# ── Serve frontend ────────────────────────────────────────
INDEX_HTML = "/app/web/dist/index.html"

@app.get("/twa")
def twa():
    return FileResponse(os.path.join(os.path.dirname(INDEX_HTML), "twa.html"))

@app.get("/")
@app.get("/{full_path:path}")
def serve_spa(full_path: str = ""):
    return FileResponse(INDEX_HTML)
