"""
KingShot Web Dashboard — FastAPI Backend
"""
import os
import sqlite3
import subprocess
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import jwt
from passlib.context import CryptContext

# ── Config ────────────────────────────────────────────────
DB_PATH      = os.getenv("DB_PATH", "/app/data/kingshot.db")
LOG_PATH     = os.getenv("LOG_PATH", "/app/data/kingshot_daemon.log")
CONFIG_PATH  = os.getenv("CONFIG_PATH", "/app/data/web_config.json")
SECRET_KEY   = os.getenv("JWT_SECRET", "changeme-use-a-real-secret")
ADMIN_USER   = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS   = os.getenv("ADMIN_PASS", "kingshot123")
ALGORITHM    = "HS256"
TOKEN_EXPIRE = 60 * 24  # 24 hours

# ── App ───────────────────────────────────────────────────
app = FastAPI(title="KingShot Dashboard", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# ── Auth ──────────────────────────────────────────────────
def create_token(username: str) -> str:
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

# ── DB helper ─────────────────────────────────────────────
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

    c.execute("SELECT SUM(success) as s, SUM(already_used) as a, SUM(failed) as f FROM active_codes")
    row = c.fetchone()
    total_success    = row["s"] or 0
    total_already    = row["a"] or 0
    total_failed     = row["f"] or 0

    conn.close()

    # System health
    health = get_health_data()

    return {
        "players": {"total": total_players, "vip": total_vip},
        "codes": codes,
        "stats": {"success": total_success, "already_used": total_already, "failed": total_failed},
        "health": health,
    }

# ── Players ───────────────────────────────────────────────
@app.get("/api/players")
def list_players(_=Depends(verify_token)):
    conn = db()
    c = conn.cursor()
    c.execute("""
        SELECT player_id, username, is_vip, active_since, removed_at
        FROM players ORDER BY is_vip DESC, username ASC
    """)
    players = [dict(r) for r in c.fetchall()]
    conn.close()
    return players

class PlayerUpdate(BaseModel):
    username: Optional[str] = None
    is_vip: Optional[bool] = None

class PlayerAdd(BaseModel):
    player_id: str
    username: str
    is_vip: bool = False

@app.post("/api/players")
def add_player(p: PlayerAdd, _=Depends(verify_token)):
    conn = db()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT OR IGNORE INTO players (player_id, username, is_vip, active_since)
            VALUES (?, ?, ?, ?)
        """, (p.player_id, p.username, int(p.is_vip), datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
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

# ── Redemptions per player ────────────────────────────────
@app.get("/api/players/{player_id}/redemptions")
def player_redemptions(player_id: str, _=Depends(verify_token)):
    conn = db()
    c = conn.cursor()
    c.execute("""
        SELECT code, status, message, created_at, retry_count
        FROM redemptions WHERE player_id=? ORDER BY created_at DESC
    """, (player_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

# ── Codes ─────────────────────────────────────────────────
@app.get("/api/codes")
def list_codes(_=Depends(verify_token)):
    conn = db()
    c = conn.cursor()
    c.execute("""
        SELECT code, created_at, expires_at, is_currently_active, is_completed,
               total, success, already_used, failed, last_updated
        FROM active_codes ORDER BY is_currently_active DESC, created_at DESC
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
def get_logs(lines: int = 100, _=Depends(verify_token)):
    try:
        result = subprocess.run(["tail", "-n", str(lines), LOG_PATH],
                                capture_output=True, text=True)
        return {"logs": result.stdout}
    except Exception as e:
        return {"logs": f"Error reading logs: {e}"}

# ── Settings ──────────────────────────────────────────────
import json

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

# ── Health ────────────────────────────────────────────────
def get_health_data():
    health = {}
    try:
        result = subprocess.run(["cat", "/proc/loadavg"], capture_output=True, text=True)
        load = float(result.stdout.split()[0])
        import os as _os
        health["cpu"] = round(load * 100 / (_os.cpu_count() or 1), 1)
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
    try:
        result = subprocess.run(["cat", "/sys/class/thermal/thermal_zone0/temp"],
                                capture_output=True, text=True)
        health["temp"] = round(int(result.stdout.strip()) / 1000, 1)
    except Exception:
        health["temp"] = 0
    return health

@app.get("/api/health")
def health(_=Depends(verify_token)):
    return get_health_data()

# ── Serve React frontend ──────────────────────────────────
STATIC_DIR = "/app/web/dist"
if os.path.exists(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=f"{STATIC_DIR}/assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        return FileResponse(f"{STATIC_DIR}/index.html")
