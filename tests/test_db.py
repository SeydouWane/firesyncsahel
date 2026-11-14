"""Postgres adapter: SQL translation (no live database needed)."""
from firesync.api import db


class _FakeCursor:
    def __init__(self, log):
        self.log, self.description, self.rowcount = log, None, 1

    def execute(self, sql, args):
        self.log.append((sql, args))
        self.description = [("id",)] if "RETURNING id" in sql or sql.lstrip().upper().startswith("SELECT") else None

    def fetchone(self):
        return {"id": 42}

    def fetchall(self):
        return [{"id": 42}]


class _FakePg:
    def __init__(self):
        self.log = []

    def cursor(self):
        return _FakeCursor(self.log)


def _adapter():
    c = db._PgConn.__new__(db._PgConn)
    c._c = _FakePg()
    return c


def test_placeholders_and_returning_id():
    c = _adapter()
    cur = c.execute("INSERT INTO zones(owner_id,name) VALUES(?,?)", (1, "Kédougou"))
    sql, args = c._c.log[-1]
    assert sql == "INSERT INTO zones(owner_id,name) VALUES(%s,%s) RETURNING id" and args == (1, "Kédougou")
    assert cur.lastrowid == 42
    c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("a", "1"))
    assert "RETURNING" not in c._c.log[-1][0]  # settings has no id column
    c.execute("SELECT * FROM users WHERE email=?", ("x@y.z",))
    assert c._c.log[-1][0].endswith("email=%s")


def test_pg_schema_types():
    stmts = db._pg_schema()
    assert len(stmts) == 6
    s = " ".join(stmts)
    assert "AUTOINCREMENT" not in s and "BIGSERIAL PRIMARY KEY" in s
    assert " REAL" not in s and "DOUBLE PRECISION" in s  # epoch seconds need float8
