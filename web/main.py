"""
WLF Rewardwolf — Web Dashboard v2.0.3
"""
import os
import json
import sqlite3
import subprocess
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect, Request
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
REBUILD_SERVER_URL = os.getenv("REBUILD_SERVER_URL", "")
DOCKER_TCP_URL     = os.getenv("DOCKER_TCP_URL",     "")
ALGORITHM    = "HS256"
TOKEN_EXPIRE = 60 * 24

# Brute force koruması
_login_attempts: dict = {}  # {ip: [timestamp, ...]}
LOGIN_MAX_ATTEMPTS   = 10
LOGIN_WINDOW_SECONDS = 300  # 5 dakika

app = FastAPI(title="WLF Rewardwolf", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
pwd_ctx       = CryptContext(schemes=["bcrypt"], deprecated="auto")
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

def _check_brute_force(ip: str):
    now      = datetime.now(timezone.utc).timestamp()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < LOGIN_WINDOW_SECONDS]
    _login_attempts[ip] = attempts
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in 5 minutes.")

def _record_failed(ip: str):
    now = datetime.now(timezone.utc).timestamp()
    _login_attempts.setdefault(ip, []).append(now)

def _clear_attempts(ip: str):
    _login_attempts.pop(ip, None)

def _verify_password(plain: str, stored: str) -> bool:
    """Stored değer bcrypt hash'i ise pwd_ctx ile, değilse düz karşılaştır."""
    if stored.startswith("$2"):
        return pwd_ctx.verify(plain, stored)
    return plain == stored

@app.post("/api/auth/login")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends()):
    ip = request.client.host
    _check_brute_force(ip)
    if form.username != ADMIN_USER or not _verify_password(form.password, ADMIN_PASS):
        _record_failed(ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _clear_attempts(ip)
    return {"access_token": create_token(form.username), "token_type": "bearer"}

# ── API Key Auth ──────────────────────────────────────────
import secrets

def init_api_keys_table():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            key         TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            description TEXT,
            created_at  TEXT NOT NULL,
            last_used   TEXT
        )
    """)
    # Migrate: add description column if missing
    cols = [r[1] for r in conn.execute("PRAGMA table_info(api_keys)").fetchall()]
    if "description" not in cols:
        conn.execute("ALTER TABLE api_keys ADD COLUMN description TEXT")
    conn.commit()
    conn.close()

def verify_api_key(key: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT key FROM api_keys WHERE key=?", (key,)).fetchone()
    if row:
        conn.execute("UPDATE api_keys SET last_used=? WHERE key=?",
                     (datetime.now(timezone.utc).isoformat(), key))
        conn.commit()
    conn.close()
    return row is not None

from fastapi.security import APIKeyHeader
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_api_key_header(api_key: str = Depends(api_key_header)):
    if not api_key or not verify_api_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key

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
        "total_players": total_players,
        "vip_count": total_vip,
        "total_codes": total_codes,
        "success": total_success,
        "already_used": total_already_used,
        "failed": total_failed,
        "health": health,
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
    c.execute("""
        SELECT player_id, username, is_vip, role, active_since, removed_at
        FROM players
        ORDER BY is_vip DESC, role DESC, username ASC
    """)
    players = [dict(r) for r in c.fetchall()]
    conn.close()
    return players

class PlayerAdd(BaseModel):
    player_id: str
    username: str
    is_vip: bool = False
    role: str = "R1"

class PlayerUpdate(BaseModel):
    username: Optional[str] = None
    is_vip: Optional[bool] = None
    role: Optional[str] = None

def _resolve_name_from_api(player_id: str) -> str:
    """Resolve player display name from KingShot API. Returns empty string on failure."""
    import urllib.request as _ur
    kingshot_api = os.getenv("KINGSHOT_API", "https://kingshot.net/api")
    try:
        req  = _ur.Request(
            f"{kingshot_api}/player-info?playerId={player_id}",
            headers={"Accept": "application/json"}
        )
        resp = _ur.urlopen(req, timeout=8)
        data = json.loads(resp.read())
        return (data.get("data", {}).get("name") or "").strip()
    except Exception:
        return ""

@app.post("/api/players")
def add_player(p: PlayerAdd, _=Depends(verify_token)):
    username = p.username.strip() if p.username else ""
    if not username:
        username = _resolve_name_from_api(p.player_id)
    conn = db()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO players (player_id, username, is_vip, role, active_since) VALUES (?, ?, ?, ?, ?)",
        (p.player_id, username, int(p.is_vip), p.role, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()
    return {"ok": True, "resolved_name": username or None}

@app.patch("/api/players/{player_id}")
def update_player(player_id: str, update: PlayerUpdate, _=Depends(verify_token)):
    conn = db()
    c = conn.cursor()
    if update.username is not None:
        c.execute("UPDATE players SET username=? WHERE player_id=?", (update.username, player_id))
    if update.is_vip is not None:
        c.execute("UPDATE players SET is_vip=? WHERE player_id=?", (int(update.is_vip), player_id))
    if update.role is not None:
        c.execute("UPDATE players SET role=? WHERE player_id=?", (update.role, player_id))
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

@app.get("/api/players/resolve/{player_id}")
def resolve_player_name(player_id: str, _=Depends(verify_token)):
    """Query KingShot API to resolve a player's display name by ID."""
    import urllib.request as _urllib_req
    kingshot_api = os.getenv("KINGSHOT_API", "https://kingshot.net/api")
    try:
        req  = _urllib_req.Request(
            f"{kingshot_api}/player-info?playerId={player_id}",
            headers={"Accept": "application/json"}
        )
        resp = _urllib_req.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        name = (data.get("data", {}).get("name") or "").strip()
        if name:
            return {"ok": True, "name": name}
        return {"ok": False, "name": None}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Name resolve failed: {e}")

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
    c.execute("SELECT player_id, username, is_vip, role, active_since, removed_at FROM players WHERE player_id=?", (player_id,))
    player = dict(c.fetchone() or {})
    c.execute("""
        SELECT r.code, r.status, r.message, r.created_at, r.retry_count,
               ac.expires_at
        FROM redemptions r
        LEFT JOIN active_codes ac ON ac.code = r.code
        WHERE r.player_id=? ORDER BY r.created_at DESC
    """, (player_id,))
    history = [dict(r) for r in c.fetchall()]
    # İsim geçmişi (tablo yoksa boş döner)
    try:
        c.execute(
            "SELECT username, recorded_at FROM player_name_history WHERE player_id=? ORDER BY recorded_at DESC",
            (player_id,)
        )
        name_history = [dict(r) for r in c.fetchall()]
    except Exception:
        name_history = []
    conn.close()
    return {"player": player, "history": history, "name_history": name_history}

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
        SELECT p.player_id, p.username, p.is_vip, p.role,
               r.status, r.message, r.created_at, r.retry_count
        FROM players p
        LEFT JOIN redemptions r ON r.player_id=p.player_id AND r.code=?
        WHERE p.removed_at IS NULL
        ORDER BY p.is_vip DESC, p.role DESC, p.username ASC
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
def _docker_unix_request(method: str, path: str, body=None) -> tuple:
    """Make an HTTP request to the Docker Unix socket. Returns (status_code, response_body_str)."""
    import socket as _socket
    DOCKER_SOCK = '/var/run/docker.sock'
    try:
        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(DOCKER_SOCK)
        body_bytes = json.dumps(body).encode() if body else b''
        request_lines = [
            f"{method} {path} HTTP/1.0",
            "Host: localhost",
            "Content-Type: application/json",
            f"Content-Length: {len(body_bytes)}",
            "",
            "",
        ]
        sock.sendall(("\r\n".join(request_lines)).encode() + body_bytes)
        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
        sock.close()
        header_end = response.find(b"\r\n\r\n")
        status_line = response[:response.find(b"\r\n")].decode(errors='replace')
        parts = status_line.split(" ", 2)
        status_code = int(parts[1]) if len(parts) > 1 else 0
        resp_body = response[header_end + 4:].decode(errors='replace') if header_end >= 0 else ""
        return status_code, resp_body
    except Exception as e:
        return 0, str(e)

def _rebuild_server(path):
    """Rebuild server üzerinden Docker komutlarını çalıştır."""
    if not REBUILD_SERVER_URL:
        raise HTTPException(status_code=503, detail="REBUILD_SERVER_URL not configured")
    import urllib.request as _ur
    req  = _ur.Request(f"{REBUILD_SERVER_URL}{path}", method="POST")
    resp = _ur.urlopen(req, timeout=10)
    return resp.read().decode()

@app.post("/api/daemon/start")
def daemon_start(_=Depends(verify_token)):
    try:
        if REBUILD_SERVER_URL:
            out = _rebuild_server("/start")
            return {"ok": True, "output": out}
        # Fallback: Docker socket
        code, body = _docker_unix_request("POST", "/containers/kingshot-daemon/start")
        ok = code in (204, 304)
        msg = "Container started" if ok else f"HTTP {code}: {body.strip()[:120]}"
        return {"ok": ok, "output": msg}
    except Exception as e:
        return {"ok": False, "output": str(e)}

@app.post("/api/daemon/stop")
def daemon_stop(_=Depends(verify_token)):
    try:
        if REBUILD_SERVER_URL:
            out = _rebuild_server("/stop")
            return {"ok": True, "output": out}
        # Fallback: Docker socket
        code, body = _docker_unix_request("POST", "/containers/kingshot-daemon/stop")
        ok = code in (204, 304)
        msg = "Container stopped" if ok else f"HTTP {code}: {body.strip()[:120]}"
        return {"ok": ok, "output": msg}
    except Exception as e:
        return {"ok": False, "output": str(e)}

@app.post("/api/daemon/restart")
def daemon_restart(_=Depends(verify_token)):
    try:
        if REBUILD_SERVER_URL:
            out = _rebuild_server("/restart")
            return {"ok": True, "output": out}
        # Fallback: Docker socket
        code, body = _docker_unix_request("POST", "/containers/kingshot-daemon/restart")
        ok = code in (204, 304)
        msg = "Container restarted" if ok else f"HTTP {code}: {body.strip()[:120]}"
        return {"ok": ok, "output": msg}
    except Exception as e:
        return {"ok": False, "output": str(e)}

@app.post("/api/daemon/rebuild")
def daemon_rebuild(_=Depends(verify_token)):
    try:
        if REBUILD_SERVER_URL:
            import urllib.request as _ur
            req = _ur.Request(REBUILD_SERVER_URL + "/rebuild", method="POST")
            _ur.urlopen(req, timeout=10)
            return {"ok": True, "output": "Rebuild started via rebuild server"}
        # Fallback: restart via Docker socket (can't do full compose rebuild without CLI)
        code, body = _docker_unix_request("POST", "/containers/kingshot-daemon/restart")
        ok = code in (204, 304)
        msg = "Container restarted (no rebuild server — restart only)" if ok else f"HTTP {code}: {body.strip()[:120]}"
        return {"ok": ok, "output": msg}
    except Exception as e:
        return {"ok": False, "output": str(e)}

@app.get("/api/daemon/status")
def daemon_status(_=Depends(verify_token)):
    # 1. Try DOCKER_TCP_URL (remote Docker daemon)
    if DOCKER_TCP_URL:
        try:
            import urllib.request as _ur
            req  = _ur.Request(DOCKER_TCP_URL + "/containers/kingshot-daemon/json")
            resp = _ur.urlopen(req, timeout=3)
            data = json.loads(resp.read())
            return {
                "status":  data.get("State", {}).get("Status",  "unknown"),
                "running": data.get("State", {}).get("Running", False),
            }
        except Exception:
            pass
    # 2. Fallback: Unix socket (docker.sock mounted in container)
    try:
        code, body = _docker_unix_request("GET", "/containers/kingshot-daemon/json")
        if code == 200:
            data = json.loads(body)
            return {
                "status":  data.get("State", {}).get("Status",  "unknown"),
                "running": data.get("State", {}).get("Running", False),
            }
    except Exception:
        pass
    # 3. Last resort: unknown
    return {"status": "unknown", "running": False}

# ── Telegram ──────────────────────────────────────────────
class TelegramMsg(BaseModel):
    message: str

@app.post("/api/telegram/send")
def telegram_send(msg: TelegramMsg, _=Depends(verify_token)):
    token   = os.getenv("TELEGRAM_TOKEN",  "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return {"ok": False, "error": "Telegram not configured (TELEGRAM_TOKEN or TELEGRAM_CHAT_ID missing)"}
    try:
        import requests as _req
        r = _req.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg.message, "parse_mode": "HTML"},
            timeout=10,
        )
        if r.ok:
            return {"ok": True}
        try:
            detail = r.json().get("description", r.text[:120])
        except Exception:
            detail = r.text[:120]
        return {"ok": False, "error": f"Telegram API: {detail}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ── Distribution Status ───────────────────────────────────
def _ctrl_get(key: str) -> str:
    conn = db()
    row = conn.execute("SELECT value FROM daemon_control WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else ""

def _ctrl_set(key: str, value: str):
    conn = db()
    conn.execute(
        "INSERT OR REPLACE INTO daemon_control (key, value, updated_at) VALUES (?, ?, datetime('now'))",
        (key, value)
    )
    conn.commit()
    conn.close()

@app.get("/api/distribution/status")
def distribution_status(_=Depends(verify_token)):
    conn = db()
    rows = conn.execute("""
        SELECT
            ac.code, ac.expires_at, ac.is_currently_active, ac.is_completed,
            ac.player_count,
            COALESCE(SUM(CASE WHEN r.status='SUCCESS'       THEN 1 ELSE 0 END), 0) as success,
            COALESCE(SUM(CASE WHEN r.status='ALREADY_USED'  THEN 1 ELSE 0 END), 0) as already_used,
            COALESCE(SUM(CASE WHEN r.status='FAILED'        THEN 1 ELSE 0 END), 0) as failed,
            COALESCE(SUM(CASE WHEN r.status='SERVER_BUSY'   THEN 1 ELSE 0 END), 0) as server_busy,
            COALESCE(SUM(CASE WHEN r.status='LIMIT_REACHED' THEN 1 ELSE 0 END), 0) as limit_reached,
            COUNT(r.player_id) as processed
        FROM active_codes ac
        LEFT JOIN redemptions r ON r.code = ac.code
        WHERE ac.is_currently_active = 1
        GROUP BY ac.code
        ORDER BY ac.is_completed ASC, ac.created_at DESC
    """).fetchall()
    conn.close()
    paused = _ctrl_get("dist_paused") == "1"
    return {"codes": [dict(r) for r in rows], "paused": paused}

@app.post("/api/distribution/pause")
def distribution_pause(_=Depends(verify_token)):
    _ctrl_set("dist_cmd", "pause")
    return {"ok": True, "message": "Duraklat komutu gönderildi"}

@app.post("/api/distribution/resume")
def distribution_resume(_=Depends(verify_token)):
    _ctrl_set("dist_cmd", "resume")
    _ctrl_set("dist_paused", "0")
    return {"ok": True, "message": "Devam et komutu gönderildi"}

@app.post("/api/distribution/cancel")
def distribution_cancel(_=Depends(verify_token)):
    _ctrl_set("dist_cmd", "cancel")
    return {"ok": True, "message": "Cancel command sent"}

@app.post("/api/distribution/retry")
def distribution_retry(_=Depends(verify_token)):
    _ctrl_set("dist_cmd", "retry")
    return {"ok": True, "message": "Retry command sent"}

class AddCodeBody(BaseModel):
    code: str
    expires_at: Optional[str] = None

@app.post("/api/codes/add")
def add_code_manual(body: AddCodeBody, _=Depends(verify_token)):
    code = body.code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Code is required")
    conn = db()
    existing = conn.execute("SELECT code, is_completed, is_currently_active FROM active_codes WHERE code=?", (code,)).fetchone()
    if existing:
        if existing["is_completed"] or not existing["is_currently_active"]:
            # Reset LIMIT_REACHED redemptions so the code can be fully redistributed
            conn.execute(
                "DELETE FROM redemptions WHERE code=? AND status='LIMIT_REACHED'",
                (code,)
            )
            conn.execute(
                "UPDATE active_codes SET is_completed=0, is_currently_active=1, notified=0, last_updated=? WHERE code=?",
                (datetime.now(timezone.utc).isoformat(), code)
            )
            conn.commit()
            conn.close()
            return {"ok": True, "message": "Code reactivated for redistribution"}
        conn.close()
        return {"ok": False, "message": "Code already active"}
    conn.execute(
        """INSERT INTO active_codes (code, created_at, expires_at, is_currently_active, is_completed, notified)
           VALUES (?, ?, ?, 1, 0, 0)""",
        (code, datetime.now(timezone.utc).isoformat(), body.expires_at)
    )
    conn.commit()
    conn.close()
    return {"ok": True, "message": "Code added"}

@app.get("/api/daemon/uptime")
def daemon_uptime_endpoint(_=Depends(verify_token)):
    if DOCKER_TCP_URL:
        try:
            import urllib.request as _ur
            req  = _ur.Request(DOCKER_TCP_URL + "/containers/kingshot-daemon/json")
            resp = _ur.urlopen(req, timeout=3)
            data = json.loads(resp.read())
            state = data.get("State", {})
            return {"started_at": state.get("StartedAt"), "running": state.get("Running", False), "status": state.get("Status", "unknown")}
        except Exception:
            pass
    try:
        code, body = _docker_unix_request("GET", "/containers/kingshot-daemon/json")
        if code == 200:
            data  = json.loads(body)
            state = data.get("State", {})
            return {"started_at": state.get("StartedAt"), "running": state.get("Running", False), "status": state.get("Status", "unknown")}
    except Exception:
        pass
    return {"started_at": None, "running": False, "status": "unknown"}

class SendMsgBody(BaseModel):
    channel_id: int
    message: str

@app.post("/api/message/send")
def send_to_channel(body: SendMsgBody, _=Depends(verify_token)):
    conn = db()
    row  = conn.execute("SELECT * FROM notification_channels WHERE id=?", (body.channel_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Channel not found")
    r = dict(row)
    try:
        import requests as _req
        if r["platform"] == "telegram":
            token = os.getenv("TELEGRAM_TOKEN", "")
            if not token:
                raise HTTPException(status_code=400, detail="TELEGRAM_TOKEN not configured")
            resp = _req.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": r["target"], "text": body.message, "parse_mode": "HTML"},
                timeout=10
            )
            if not resp.ok:
                raise HTTPException(status_code=400, detail=f"Telegram error: {resp.text[:120]}")
        elif r["platform"] == "discord":
            resp = _req.post(r["target"], json={"content": body.message}, timeout=10)
            if resp.status_code not in (200, 204):
                raise HTTPException(status_code=400, detail=f"Discord error: {resp.text[:120]}")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/channels/test-all")
def test_all_channels(_=Depends(verify_token)):
    import requests as _req
    conn = db()
    rows = conn.execute("SELECT * FROM notification_channels WHERE enabled=1 ORDER BY id").fetchall()
    conn.close()
    results = []
    for row in rows:
        r = dict(row)
        try:
            test_msg = f"🔔 Test — WLF Gift Panel\nChannel: {r['name']}"
            if r["platform"] == "telegram":
                token = os.getenv("TELEGRAM_TOKEN", "")
                resp  = _req.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": r["target"], "text": test_msg}, timeout=10
                )
                ok, err = resp.ok, ("" if resp.ok else resp.text[:80])
            elif r["platform"] == "discord":
                resp = _req.post(r["target"], json={"content": test_msg}, timeout=10)
                ok   = resp.status_code in (200, 204)
                err  = "" if ok else resp.text[:80]
            else:
                ok, err = False, "Unknown platform"
        except Exception as e:
            ok, err = False, str(e)[:80]
        results.append({"id": r["id"], "name": r["name"], "platform": r["platform"], "ok": ok, "error": err})
    return results

@app.get("/api/system/check")
def system_check(_=Depends(verify_token)):
    checks = []
    # Daemon container
    try:
        code, body = _docker_unix_request("GET", "/containers/kingshot-daemon/json")
        if code == 200:
            data    = json.loads(body)
            running = data.get("State", {}).get("Running", False)
            checks.append({"name": "Daemon Container", "ok": running, "detail": "Running" if running else "Stopped"})
        else:
            checks.append({"name": "Daemon Container", "ok": False, "detail": f"Docker HTTP {code}"})
    except Exception as e:
        checks.append({"name": "Daemon Container", "ok": False, "detail": str(e)[:60]})
    # Database
    try:
        conn   = db()
        p_cnt  = conn.execute("SELECT COUNT(*) FROM players WHERE removed_at IS NULL").fetchone()[0]
        c_cnt  = conn.execute("SELECT COUNT(*) FROM active_codes WHERE is_currently_active=1").fetchone()[0]
        conn.close()
        checks.append({"name": "Database", "ok": True, "detail": f"{p_cnt} players · {c_cnt} active codes"})
    except Exception as e:
        checks.append({"name": "Database", "ok": False, "detail": str(e)[:60]})
    # Telegram bot
    try:
        import requests as _req
        token = os.getenv("TELEGRAM_TOKEN", "")
        if token:
            r = _req.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
            if r.ok:
                uname = r.json().get("result", {}).get("username", "?")
                checks.append({"name": "Telegram Bot", "ok": True, "detail": f"@{uname}"})
            else:
                checks.append({"name": "Telegram Bot", "ok": False, "detail": "API error"})
        else:
            checks.append({"name": "Telegram Bot", "ok": False, "detail": "Token not configured"})
    except Exception as e:
        checks.append({"name": "Telegram Bot", "ok": False, "detail": str(e)[:60]})
    # Discord webhooks
    try:
        conn  = db()
        d_cnt = conn.execute(
            "SELECT COUNT(*) FROM notification_channels WHERE platform='discord' AND enabled=1"
        ).fetchone()[0]
        conn.close()
        checks.append({"name": "Discord Webhooks", "ok": True, "detail": f"{d_cnt} active"})
    except Exception as e:
        checks.append({"name": "Discord Webhooks", "ok": False, "detail": str(e)[:60]})
    # System health
    h = get_health_data()
    checks.append({"name": "CPU",         "ok": h.get("cpu",  0) < 90, "detail": f"{h.get('cpu', 0):.1f}%"})
    checks.append({"name": "RAM",         "ok": h.get("ram",  0) < 90, "detail": f"{h.get('ram', 0):.1f}% · {h.get('ram_used_mb',0)}/{h.get('ram_total_mb',0)} MB"})
    checks.append({"name": "Temperature", "ok": h.get("temp", 0) < 80, "detail": f"{h.get('temp', 0):.1f}°C"})
    return {"checks": checks, "all_ok": all(c["ok"] for c in checks)}

# ── Settings ──────────────────────────────────────────────
def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {
        "CHECK_INTERVAL_MIN":   5,
        "RETRY_DELAY_HOURS":    2,
        "EXPIRY_WARNING_HOURS": 72,
        "CPU_ALERT_THRESHOLD":  80,
        "RAM_ALERT_THRESHOLD":  85,
        "TEMP_ALERT_THRESHOLD": 75,
        "TELEGRAM_TOKEN":       os.getenv("TELEGRAM_TOKEN",  ""),
        "TELEGRAM_CHAT_ID":     os.getenv("TELEGRAM_CHAT_ID", ""),
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

# ── Player name sync (web-triggered) ─────────────────────
@app.post("/api/players/sync-names")
def sync_player_names_now(_=Depends(verify_token)):
    """Resolve and refresh usernames from KingShot API for all active players (including renamed ones)."""
    conn = db()
    rows = conn.execute(
        "SELECT player_id, username FROM players WHERE removed_at IS NULL"
    ).fetchall()
    conn.close()
    updated = []
    for row in rows:
        pid      = row["player_id"]
        old_name = (row["username"] or "").strip()
        name = _resolve_name_from_api(pid)
        if not name or name == old_name:
            continue  # API returned nothing or name unchanged
        conn = db()
        conn.execute("UPDATE players SET username=? WHERE player_id=?", (name, pid))
        conn.commit()
        conn.close()
        updated.append({"player_id": pid, "old_name": old_name, "name": name})
    return {"ok": True, "updated": updated, "count": len(updated)}

# ── Daemon file edit ──────────────────────────────────────
# Güvenlik: Dosya düzenleme için ek şifre onayı gerekli
class DaemonFileWrite(BaseModel):
    content:  str
    password: str  # Değişiklik onayı için şifre tekrar istenir

@app.get("/api/daemon/file")
def get_daemon_file(_=Depends(verify_token)):
    path = os.path.join(COMPOSE_DIR, "kingshot_giftcode_daemon.py")
    try:
        with open(path, "r") as f:
            return {"content": f.read()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/daemon/file")
def save_daemon_file(body: DaemonFileWrite, _=Depends(verify_token)):
    # Şifre tekrar doğrula
    if not _verify_password(body.password, ADMIN_PASS):
        raise HTTPException(status_code=403, detail="Invalid password confirmation")
    path = os.path.join(COMPOSE_DIR, "kingshot_giftcode_daemon.py")
    # Backup al
    backup_path = path + ".bak"
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                backup = f.read()
            with open(backup_path, "w") as f:
                f.write(backup)
    except Exception:
        pass
    try:
        with open(path, "w") as f:
            f.write(body.content)
        return {"ok": True, "backup": backup_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Sheets sync ───────────────────────────────────────────
@app.post("/api/sync/sheets")
def sync_sheets(_=Depends(verify_token)):
    sheets_url = os.getenv("SHEETS_WEB_APP_URL", "")
    if not sheets_url:
        raise HTTPException(status_code=400, detail="Sheets URL not configured")
    import requests as req
    r    = req.get(sheets_url, timeout=60)
    data = r.json()
    if not data.get("success"):
        raise HTTPException(status_code=500, detail="Sheets sync failed")
    players = data["players"]
    conn    = db()
    c       = conn.cursor()
    now     = datetime.now(timezone.utc).isoformat()
    added   = 0
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
        load   = float(result.stdout.split()[0])
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
        total  = mem.get("MemTotal:",     1)
        avail  = mem.get("MemAvailable:", 0)
        health["ram"]         = round((total - avail) / total * 100, 1)
        health["ram_used_mb"] = round((total - avail) / 1024)
        health["ram_total_mb"]= round(total / 1024)
    except Exception:
        health["ram"] = health["ram_used_mb"] = health["ram_total_mb"] = 0
    try:
        result = subprocess.run(["cat", "/sys/class/thermal/thermal_zone0/temp"], capture_output=True, text=True)
        health["temp"] = round(int(result.stdout.strip()) / 1000, 1)
    except Exception:
        health["temp"] = 0
    return health

@app.get("/api/health")
def health(_=Depends(verify_token)):
    return get_health_data()

# ── Notification Channels ────────────────────────────────
DEFAULT_CHANNEL_TEMPLATES = {
    "new_code":       "🎉 New Gift Code Found!\n{code_fmt}\n🔄 Queued for distribution...",
    "dist_complete":  "✅ Distribution Complete!\n🎁 Code: {code_fmt}\n\n✅ Delivered: {delivered}\n❌ Failed: {failed}\n👥 Total: {total}",
    "expiry_warning": "⏰ Gift Code Expiring!\n🎁 Code: {code_fmt}\n⏱ {hours}h remaining\n📊 {delivered}/{total} delivered",
    "daily_summary":  "📅 Daily Summary\n👥 Players: {players}\n✅ Delivered: {delivered}\n❌ Failed: {failed}",
}

class ChannelCreate(BaseModel):
    name:                str
    platform:            str = "telegram"   # "telegram" | "discord"
    target:              str                # chat_id veya webhook URL
    enabled:             bool = True
    ev_new_code:         bool = True
    ev_dist_complete:    bool = True
    ev_expiry_warning:   bool = True
    ev_daily_summary:    bool = False
    tpl_new_code:        Optional[str] = None
    tpl_dist_complete:   Optional[str] = None
    tpl_expiry_warning:  Optional[str] = None
    tpl_daily_summary:   Optional[str] = None
    tpl_dist_state:      Optional[str] = None
    mention_new_code:        str = "everyone"  # "none" | "everyone" | "here"
    mention_dist_complete:   str = "none"
    mention_expiry_warning:  str = "everyone"
    mention_daily_summary:   str = "none"
    mention_dist_state:      str = "none"
    ev_dist_state:           bool = True
    ev_dist_progress:        bool = False
    tpl_dist_progress:       Optional[str] = None
    mention_dist_progress:   str = "none"

class ChannelUpdate(BaseModel):
    name:                Optional[str]  = None
    platform:            Optional[str]  = None
    target:              Optional[str]  = None
    enabled:             Optional[bool] = None
    ev_new_code:         Optional[bool] = None
    ev_dist_complete:    Optional[bool] = None
    ev_expiry_warning:   Optional[bool] = None
    ev_daily_summary:    Optional[bool] = None
    ev_dist_state:       Optional[bool] = None
    tpl_new_code:        Optional[str]  = None
    tpl_dist_complete:   Optional[str]  = None
    tpl_expiry_warning:  Optional[str]  = None
    tpl_daily_summary:   Optional[str]  = None
    tpl_dist_state:      Optional[str]  = None
    mention_new_code:        Optional[str] = None
    mention_dist_complete:   Optional[str] = None
    mention_expiry_warning:  Optional[str] = None
    mention_daily_summary:   Optional[str] = None
    mention_dist_state:      Optional[str] = None
    ev_dist_progress:        Optional[bool] = None
    tpl_dist_progress:       Optional[str]  = None
    mention_dist_progress:   Optional[str]  = None

def init_channels_table():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
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
            mention_new_code        TEXT DEFAULT 'everyone',
            mention_dist_complete   TEXT DEFAULT 'none',
            mention_expiry_warning  TEXT DEFAULT 'everyone',
            mention_daily_summary   TEXT DEFAULT 'none',
            mention_dist_state      TEXT DEFAULT 'none',
            ev_dist_state           INTEGER DEFAULT 1,
            tpl_dist_state          TEXT,
            created_at          TEXT NOT NULL
        )
    """)
    for col, default in [
        ("mention_new_code",       "everyone"),
        ("mention_dist_complete",  "none"),
        ("mention_expiry_warning", "everyone"),
        ("mention_daily_summary",  "none"),
        ("mention_dist_state",     "none"),
        ("ev_dist_state",          "1"),
        ("tpl_dist_state",         ""),
        ("ev_dist_progress",       "0"),
        ("tpl_dist_progress",      ""),
        ("mention_dist_progress",  "none"),
    ]:
        try:
            if col.startswith("ev_"):
                conn.execute(f"ALTER TABLE notification_channels ADD COLUMN {col} INTEGER DEFAULT {default}")
            else:
                conn.execute(f"ALTER TABLE notification_channels ADD COLUMN {col} TEXT DEFAULT '{default}'")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()

@app.get("/api/channels")
def list_channels(_=Depends(verify_token)):
    conn = db()
    rows = conn.execute("SELECT * FROM notification_channels ORDER BY created_at DESC").fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        # Null template'leri default ile doldur (UI'da göstermek için)
        for ev in ("new_code", "dist_complete", "expiry_warning", "daily_summary"):
            if not d.get(f"tpl_{ev}"):
                d[f"tpl_{ev}_default"] = DEFAULT_CHANNEL_TEMPLATES.get(ev, "")
        result.append(d)
    return result

@app.post("/api/channels")
def create_channel(body: ChannelCreate, _=Depends(verify_token)):
    conn = db()
    cur = conn.execute("""
        INSERT INTO notification_channels
            (name, platform, target, enabled,
             ev_new_code, ev_dist_complete, ev_expiry_warning, ev_daily_summary, ev_dist_state, ev_dist_progress,
             tpl_new_code, tpl_dist_complete, tpl_expiry_warning, tpl_daily_summary, tpl_dist_state, tpl_dist_progress,
             mention_new_code, mention_dist_complete, mention_expiry_warning, mention_daily_summary, mention_dist_state, mention_dist_progress,
             created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (body.name, body.platform, body.target, int(body.enabled),
          int(body.ev_new_code), int(body.ev_dist_complete),
          int(body.ev_expiry_warning), int(body.ev_daily_summary), int(body.ev_dist_state), int(body.ev_dist_progress),
          body.tpl_new_code, body.tpl_dist_complete,
          body.tpl_expiry_warning, body.tpl_daily_summary, body.tpl_dist_state, body.tpl_dist_progress,
          body.mention_new_code, body.mention_dist_complete,
          body.mention_expiry_warning, body.mention_daily_summary, body.mention_dist_state, body.mention_dist_progress,
          datetime.now(timezone.utc).isoformat()))
    conn.commit()
    row = conn.execute("SELECT * FROM notification_channels WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)

@app.patch("/api/channels/{channel_id}")
def update_channel(channel_id: int, body: ChannelUpdate, _=Depends(verify_token)):
    conn = db()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    # bool → int dönüşümü
    for bfield in ("enabled","ev_new_code","ev_dist_complete","ev_expiry_warning","ev_daily_summary","ev_dist_state","ev_dist_progress"):
        if bfield in updates:
            updates[bfield] = int(updates[bfield])
    set_clause = ", ".join(f"{k}=?" for k in updates)
    conn.execute(f"UPDATE notification_channels SET {set_clause} WHERE id=?",
                 (*updates.values(), channel_id))
    conn.commit()
    row = conn.execute("SELECT * FROM notification_channels WHERE id=?", (channel_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Channel not found")
    return dict(row)

@app.delete("/api/channels/{channel_id}")
def delete_channel(channel_id: int, _=Depends(verify_token)):
    conn = db()
    conn.execute("DELETE FROM notification_channels WHERE id=?", (channel_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/channels/{channel_id}/test")
def test_channel(channel_id: int, _=Depends(verify_token)):
    conn = db()
    row = conn.execute("SELECT * FROM notification_channels WHERE id=?", (channel_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Channel not found")
    r = dict(row)
    test_msg = f"🔔 Test message from WLF Gift Panel\nChannel: {r['name']}\nPlatform: {r['platform'].capitalize()}"
    try:
        if r["platform"] == "telegram":
            import requests as req
            token = os.getenv("TELEGRAM_TOKEN","")
            if not token:
                raise HTTPException(status_code=400, detail="TELEGRAM_TOKEN not configured")
            resp = req.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": r["target"], "text": test_msg},
                timeout=10
            )
            if not resp.ok:
                raise HTTPException(status_code=400, detail=f"Telegram error: {resp.text}")
        elif r["platform"] == "discord":
            import requests as req, re
            resp = req.post(r["target"], json={"content": test_msg}, timeout=10)
            if not resp.ok:
                raise HTTPException(status_code=400, detail=f"Discord error: {resp.text}")
        return {"ok": True, "message": "Test message sent successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/channels/templates")
def get_default_templates(_=Depends(verify_token)):
    return DEFAULT_CHANNEL_TEMPLATES

# ── API Key Management ────────────────────────────────────
class ApiKeyCreate(BaseModel):
    name: str
    description: Optional[str] = None

@app.on_event("startup")
async def startup():
    init_api_keys_table()
    init_channels_table()

@app.get("/api/apikeys")
def list_api_keys(_=Depends(verify_token)):
    conn = db()
    rows = conn.execute(
        "SELECT key, name, description, created_at, last_used FROM api_keys ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/apikeys")
def create_api_key(body: ApiKeyCreate, _=Depends(verify_token)):
    key = "rwf_" + secrets.token_urlsafe(32)
    conn = db()
    conn.execute(
        "INSERT INTO api_keys (key, name, description, created_at) VALUES (?, ?, ?, ?)",
        (key, body.name, body.description, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()
    return {"key": key, "name": body.name, "description": body.description}

@app.delete("/api/apikeys/{key}")
def delete_api_key(key: str, _=Depends(verify_token)):
    conn = db()
    conn.execute("DELETE FROM api_keys WHERE key=?", (key,))
    conn.commit()
    conn.close()
    return {"ok": True}

# ── Public API (API Key ile) ───────────────────────────────
@app.get("/api/public/codes")
def public_codes(_=Depends(verify_api_key_header)):
    """Tüm gift code listesi ve istatistikleri."""
    conn = db()
    rows = conn.execute("""
        SELECT ac.code, ac.created_at, ac.expires_at, ac.is_currently_active, ac.is_completed,
               ac.player_count as total_players,
               COALESCE(SUM(CASE WHEN r.status='SUCCESS'      THEN 1 ELSE 0 END), 0) as success,
               COALESCE(SUM(CASE WHEN r.status='ALREADY_USED' THEN 1 ELSE 0 END), 0) as already_used,
               COALESCE(SUM(CASE WHEN r.status='FAILED'       THEN 1 ELSE 0 END), 0) as failed
        FROM active_codes ac
        LEFT JOIN redemptions r ON r.code = ac.code
        GROUP BY ac.code
        ORDER BY ac.is_currently_active DESC, ac.created_at DESC
    """).fetchall()
    conn.close()
    result = []
    for r in rows:
        row = dict(r)
        row["delivered"] = row["success"] + row["already_used"]
        result.append(row)
    return result

@app.get("/api/public/codes/{code}")
def public_code_detail(code: str, _=Depends(verify_api_key_header)):
    """Tek bir gift code'un detayı."""
    conn = db()
    row = conn.execute("""
        SELECT ac.code, ac.created_at, ac.expires_at, ac.is_currently_active, ac.is_completed,
               ac.player_count as total_players,
               COALESCE(SUM(CASE WHEN r.status='SUCCESS'      THEN 1 ELSE 0 END), 0) as success,
               COALESCE(SUM(CASE WHEN r.status='ALREADY_USED' THEN 1 ELSE 0 END), 0) as already_used,
               COALESCE(SUM(CASE WHEN r.status='FAILED'       THEN 1 ELSE 0 END), 0) as failed
        FROM active_codes ac
        LEFT JOIN redemptions r ON r.code = ac.code
        WHERE ac.code = ?
        GROUP BY ac.code
    """, (code,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Code not found")
    result = dict(row)
    result["delivered"] = result["success"] + result["already_used"]
    return result

@app.get("/api/public/player/{player_id}")
def public_player_status(player_id: str, _=Depends(verify_api_key_header)):
    """Bir oyuncunun tüm kodlardaki redemption durumu."""
    conn = db()
    player = conn.execute(
        "SELECT player_id, username, is_vip, role FROM players WHERE player_id=? AND removed_at IS NULL",
        (player_id,)
    ).fetchone()
    if not player:
        conn.close()
        raise HTTPException(status_code=404, detail="Player not found")
    redemptions = conn.execute("""
        SELECT r.code, r.status, r.message, r.timestamp
        FROM redemptions r
        WHERE r.player_id = ?
        ORDER BY r.timestamp DESC
    """, (player_id,)).fetchall()
    conn.close()
    return {
        "player_id": player["player_id"],
        "username":  player["username"],
        "is_vip":    bool(player["is_vip"]),
        "role":      player["role"],
        "redemptions": [dict(r) for r in redemptions],
    }

@app.get("/api/public/dashboard")
def public_dashboard(_=Depends(verify_api_key_header)):
    """Genel istatistikler."""
    conn = db()
    row = conn.execute("""
        SELECT
            (SELECT COUNT(*) FROM players WHERE removed_at IS NULL)        AS total_players,
            (SELECT COUNT(*) FROM players WHERE is_vip=1 AND removed_at IS NULL) AS vip_count,
            (SELECT COUNT(DISTINCT code) FROM active_codes)                AS total_codes,
            (SELECT COUNT(*) FROM active_codes WHERE is_currently_active=1) AS active_codes,
            COALESCE(SUM(CASE WHEN r.status='SUCCESS'      THEN 1 ELSE 0 END), 0) AS success,
            COALESCE(SUM(CASE WHEN r.status='ALREADY_USED' THEN 1 ELSE 0 END), 0) AS already_used,
            COALESCE(SUM(CASE WHEN r.status='FAILED'       THEN 1 ELSE 0 END), 0) AS failed
        FROM redemptions r
    """).fetchone()
    conn.close()
    d = dict(row)
    d["delivered"] = d["success"] + d["already_used"]
    return d

# ── Serve frontend ────────────────────────────────────────
DIST = "/app/web/dist"
INDEX_HTML = f"{DIST}/index.html"

@app.get("/favicon.ico")
def favicon():
    return FileResponse(f"{DIST}/favicon.ico", media_type="image/x-icon")

@app.get("/favicon-32.png")
def favicon32():
    return FileResponse(f"{DIST}/favicon-32.png", media_type="image/png")

@app.get("/apple-touch-icon.png")
def apple_touch():
    return FileResponse(f"{DIST}/apple-touch-icon.png", media_type="image/png")

@app.get("/logo.png")
def logo():
    return FileResponse(f"{DIST}/logo.png", media_type="image/png")

@app.get("/logo-128.png")
def logo128():
    return FileResponse(f"{DIST}/logo-128.png", media_type="image/png")

@app.get("/logo-1024.png")
def logo1024():
    return FileResponse(f"{DIST}/logo-1024.png", media_type="image/png")

@app.get("/")
@app.get("/{full_path:path}")
def serve_spa(full_path: str = ""):
    return FileResponse(INDEX_HTML)
