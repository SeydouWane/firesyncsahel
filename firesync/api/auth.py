"""Password hashing (scrypt), signed session tokens and role guards."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import defaultdict

from fastapi import Depends, HTTPException, Request

from .. import config
from . import db

COOKIE = "fs_session"
SESSION_TTL = 12 * 3600
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r),
                              p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(uid: int, role: str) -> str:
    payload = _b64(json.dumps({"uid": uid, "role": role, "exp": int(time.time()) + SESSION_TTL,
                               "n": secrets.token_hex(4)}).encode())
    sig = _b64(hmac.new(config.SECRET.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(tok: str) -> dict | None:
    try:
        payload, sig = tok.split(".")
        good = _b64(hmac.new(config.SECRET.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(_unb64(payload))
        return data if data["exp"] > time.time() else None
    except Exception:
        return None


def create_user(email: str, password: str, role: str = "pro", name: str = "", org: str = "") -> int:
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    with db.tx() as c:
        cur = c.execute("INSERT INTO users(email,name,org,role,pw_hash,created_at) VALUES(?,?,?,?,?,?)",
                        (email.strip().lower(), name, org, role, hash_password(password), time.time()))
        return cur.lastrowid


def public_user(u: dict) -> dict:
    return {k: u[k] for k in ("id", "email", "name", "org", "role", "lang", "active",
                              "created_at", "last_login")}


# --- brute-force protection: 5 failures per 10 minutes and per IP+email ---
_fails: dict[str, list[float]] = defaultdict(list)


def check_rate(key: str) -> None:
    now = time.time()
    _fails[key] = [t for t in _fails[key] if now - t < 600]
    if len(_fails[key]) >= 5:
        raise HTTPException(429, "too many attempts, retry in a few minutes")


def note_failure(key: str) -> None:
    _fails[key].append(time.time())


def current_user(request: Request) -> dict | None:
    tok = request.cookies.get(COOKIE)
    data = read_token(tok) if tok else None
    if not data:
        return None
    u = db.q1("SELECT * FROM users WHERE id=? AND active=1", (data["uid"],))
    return u


def require_csrf(request: Request) -> None:
    """Mutating requests must carry the custom header (blocks cross-site forms)."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and \
            request.headers.get("x-requested-with") != "firesync":
        raise HTTPException(403, "missing X-Requested-With header")


def require_pro(request: Request, _=Depends(require_csrf)) -> dict:
    u = current_user(request)
    if not u:
        raise HTTPException(401, "authentication required")
    return u


def require_admin(request: Request, _=Depends(require_csrf)) -> dict:
    u = current_user(request)
    if not u:
        raise HTTPException(401, "authentication required")
    if u["role"] != "admin":
        raise HTTPException(403, "admin only")
    return u
