"""Application database: users, saved zones, reference layers, access requests,
settings, background jobs and audit log.

Two backends with the same SQL (written with `?` placeholders):
  * SQLite (default) — a local file in config.APPDB;
  * Postgres — when FIRESYNC_DATABASE_URL / DATABASE_URL / POSTGRES_URL is set
    (needed on serverless hosting, whose disk is wiped at every cold start).

An administrator can be provisioned from the environment (FIRESYNC_ADMIN_EMAIL +
FIRESYNC_ADMIN_PASSWORD_HASH, or FIRESYNC_ADMIN_PASSWORD) so that a fresh
deployment is usable without a shell.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager

from .. import config

log = logging.getLogger(__name__)
DB_PATH = config.APPDB / "firesync.db"
PG = bool(config.DATABASE_URL)
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  org TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL CHECK (role IN ('admin','pro')),
  pw_hash TEXT NOT NULL,
  lang TEXT NOT NULL DEFAULT 'fr',
  active INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  last_login REAL
);
CREATE TABLE IF NOT EXISTS zones (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'drawn',
  category TEXT NOT NULL DEFAULT '',
  geometry TEXT NOT NULL,
  public INTEGER NOT NULL DEFAULT 0,
  alert_pct REAL,
  notes TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS access_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, email TEXT NOT NULL, org TEXT NOT NULL DEFAULT '',
  profile TEXT NOT NULL DEFAULT '', message TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending', created_at REAL NOT NULL, handled_by INTEGER
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, status TEXT NOT NULL,
  created_by INTEGER, started_at REAL, finished_at REAL, log TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, user_id INTEGER,
  action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
);
"""
_ID_TABLES = {"users", "zones", "access_requests", "jobs", "audit"}


# ---------------------------------------------------------------- Postgres adapter
class _PgCursor:
    def __init__(self, cur, lastrowid=None):
        self._cur, self.lastrowid = cur, lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    def fetchall(self):
        return self._cur.fetchall() if self._cur.description else []

    def fetchone(self):
        return self._cur.fetchone() if self._cur.description else None


class _PgConn:
    """Gives a psycopg connection the small sqlite3 surface the app uses
    (`?` placeholders, cursor.lastrowid, commit / rollback)."""

    def __init__(self, url: str):
        import psycopg
        from psycopg.rows import dict_row
        self._c = psycopg.connect(url, row_factory=dict_row, autocommit=False, connect_timeout=15)

    @property
    def closed(self) -> bool:
        return self._c.closed or self._c.broken

    def execute(self, sql: str, args=()):
        s = sql.replace("?", "%s")
        m = re.match(r"\s*INSERT\s+INTO\s+(\w+)", s, re.I)
        want_id = bool(m) and m.group(1).lower() in _ID_TABLES and "RETURNING" not in s.upper()
        if want_id:
            s += " RETURNING id"
        cur = self._c.cursor()
        cur.execute(s, tuple(args))
        return _PgCursor(cur, cur.fetchone()["id"] if want_id else None)

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()


def _pg_schema() -> list[str]:
    s = (SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
         .replace(" REAL", " DOUBLE PRECISION")  # time.time() needs more than float4
         .replace("INTEGER REFERENCES", "BIGINT REFERENCES"))
    return [x.strip() for x in s.split(";") if x.strip()]


# ---------------------------------------------------------------- connection
def _connect():
    if PG:
        c = _PgConn(config.DATABASE_URL)
        for stmt in _pg_schema():
            c.execute(stmt)
        c.commit()
        return c
    con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    if not config.SERVERLESS:
        con.execute("PRAGMA journal_mode = WAL")
    con.executescript(SCHEMA)
    return con


_con = None


def conn():
    global _con
    with _lock:
        if _con is None or (PG and _con.closed):
            _con = _connect()
            _bootstrap_admin(_con)
        return _con


@contextmanager
def tx():
    with _lock:
        c = conn()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise


def q(sql: str, args=()) -> list[dict]:
    with _lock:
        c = conn()
        try:
            rows = [dict(r) for r in c.execute(sql, args).fetchall()]
            if PG:
                c.commit()  # close the implicit read transaction
            return rows
        except Exception:
            if PG:
                c.rollback()
            raise


def q1(sql: str, args=()) -> dict | None:
    r = q(sql, args)
    return r[0] if r else None


def get_setting(key: str, default=None):
    r = q1("SELECT value FROM settings WHERE key=?", (key,))
    return json.loads(r["value"]) if r else default


def set_setting(key: str, value) -> None:
    with tx() as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, json.dumps(value)))


def audit(user_id: int | None, action: str, detail: str = "") -> None:
    with tx() as c:
        c.execute("INSERT INTO audit(ts,user_id,action,detail) VALUES(?,?,?,?)",
                  (time.time(), user_id, action, detail[:2000]))


# ---------------------------------------------------------------- environment admin
def _bootstrap_admin(c) -> None:
    """Create (or re-activate) the administrator described by the environment.
    Prefer FIRESYNC_ADMIN_PASSWORD_HASH (scrypt hash from `python -m firesync hash-password`)
    so that no clear-text password is stored in the hosting settings."""
    email = os.environ.get("FIRESYNC_ADMIN_EMAIL", "").strip().lower()
    pw_hash = os.environ.get("FIRESYNC_ADMIN_PASSWORD_HASH", "").strip()
    if not email:
        return
    if not pw_hash and os.environ.get("FIRESYNC_ADMIN_PASSWORD"):
        from .auth import hash_password
        pw_hash = hash_password(os.environ["FIRESYNC_ADMIN_PASSWORD"])
    if not pw_hash.startswith("scrypt$"):
        log.warning("FIRESYNC_ADMIN_EMAIL set without a valid password (hash): admin not created")
        return
    try:
        row = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if row is None:
            c.execute("INSERT INTO users(email,name,org,role,pw_hash,created_at) VALUES(?,?,?,?,?,?)",
                      (email, os.environ.get("FIRESYNC_ADMIN_NAME", "Administrateur"), "", "admin",
                       pw_hash, time.time()))
            log.info("admin %s created from the environment", email)
        else:
            # the environment is the source of truth for this account's password and role
            c.execute("UPDATE users SET pw_hash=?, role='admin', active=1 WHERE email=?", (pw_hash, email))
        c.commit()
    except Exception as e:  # never block the app because of the bootstrap
        c.rollback()
        log.warning("admin bootstrap failed: %s", e)
