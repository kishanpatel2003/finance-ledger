"""SQLite ledger. One file under MINT_HOME (default ~/.mint), never in the repo."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .normalize import account_kind, bucket_for, classify, norm_merchant

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  kind TEXT,
  institution TEXT,
  source TEXT,
  external_id TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  date TEXT NOT NULL,
  hour INTEGER,
  out REAL NOT NULL,
  merchant TEXT,
  merchant_key TEXT,
  category_src TEXT,
  type_src TEXT,
  bucket TEXT,
  kind TEXT,
  pending INTEGER DEFAULT 0,
  superseded INTEGER DEFAULT 0,
  source TEXT NOT NULL,
  external_id TEXT NOT NULL,
  raw TEXT,
  imported_at TEXT,
  UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_tx_account ON transactions(account_id);
CREATE TABLE IF NOT EXISTS balances (
  id INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  as_of TEXT NOT NULL,
  balance REAL NOT NULL,
  source TEXT NOT NULL,
  UNIQUE(account_id, as_of, source)
);
CREATE TABLE IF NOT EXISTS connectors (
  name TEXT PRIMARY KEY,
  status TEXT,
  config_json TEXT,
  last_sync TEXT,
  last_error TEXT
);
CREATE TABLE IF NOT EXISTS sync_log (
  id INTEGER PRIMARY KEY,
  connector TEXT,
  started_at TEXT,
  finished_at TEXT,
  rows_added INTEGER,
  note TEXT
);
CREATE TABLE IF NOT EXISTS characters (
  name TEXT PRIMARY KEY,
  built_at TEXT,
  since TEXT,
  until TEXT,
  sheet_json TEXT
);
"""


def mint_home() -> Path:
    return Path(os.environ.get("MINT_HOME", str(Path.home() / ".mint"))).expanduser()


def config_path() -> Path:
    return mint_home() / "config.json"


def load_config() -> dict:
    p = config_path()
    if p.exists():
        return json.loads(p.read_text())
    return {}


def save_config(cfg: dict):
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2))
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def init_home() -> dict:
    home = mint_home()
    home.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(home, 0o700)
    except OSError:
        pass
    cfg = load_config()
    changed = False
    if "ingest_token" not in cfg:
        cfg["ingest_token"] = secrets.token_urlsafe(24)
        changed = True
    cfg.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
    if changed or not config_path().exists():
        save_config(cfg)
    with connect() as con:
        con.executescript(SCHEMA)
    return cfg


def db_path() -> Path:
    return mint_home() / "ledger.sqlite"


def connect() -> sqlite3.Connection:
    mint_home().mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path()))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def _migrate(con):
    """Add columns introduced after a ledger was first created."""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(transactions)")}
    if "type_src" not in cols:
        con.execute("ALTER TABLE transactions ADD COLUMN type_src TEXT")
        con.commit()


# ----------------------------------------------------------------------------
# Accounts
# ----------------------------------------------------------------------------

def get_or_create_account(con, name: str, source: str, institution: str | None = None,
                          external_id: str | None = None, kind: str | None = None) -> int:
    row = con.execute("SELECT id FROM accounts WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = con.execute(
        "INSERT INTO accounts(name, kind, institution, source, external_id, created_at) VALUES (?,?,?,?,?,?)",
        (name, kind or account_kind(name), institution, source, external_id, datetime.now().isoformat(timespec="seconds")))
    return cur.lastrowid


def accounts(con):
    return [dict(r) for r in con.execute("SELECT * FROM accounts ORDER BY name")]


def peer_wallet_present(con) -> bool:
    return con.execute("SELECT 1 FROM accounts WHERE kind = 'peer_wallet' LIMIT 1").fetchone() is not None


# ----------------------------------------------------------------------------
# Transactions
# ----------------------------------------------------------------------------

def content_id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def upsert_transaction(con, *, account_id: int, d: date, hour, out: float, merchant: str, category_src: str,
                       source: str, external_id: str, raw=None, pending: int = 0, acct_kind: str | None = None,
                       peer_present: bool | None = None, type_src: str | None = None) -> bool:
    """Insert if (source, external_id) is new. Returns True when inserted."""
    if acct_kind is None:
        acct_kind = con.execute("SELECT kind FROM accounts WHERE id = ?", (account_id,)).fetchone()["kind"]
    if peer_present is None:
        peer_present = peer_wallet_present(con)
    bucket = bucket_for(category_src, merchant)
    kind = classify(out, acct_kind, category_src, merchant, bucket, peer_present, type_src)
    try:
        con.execute(
            "INSERT INTO transactions(account_id, date, hour, out, merchant, merchant_key, category_src, type_src, "
            "bucket, kind, pending, source, external_id, raw, imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (account_id, d.isoformat(), hour, float(out), merchant, norm_merchant(merchant), category_src, type_src,
             bucket, kind, int(pending), source, external_id, json.dumps(raw) if raw is not None else None,
             datetime.now().isoformat(timespec="seconds")))
        return True
    except sqlite3.IntegrityError:
        return False


def reclassify_all(con) -> int:
    peer = peer_wallet_present(con)
    kinds = {r["id"]: r["kind"] for r in con.execute("SELECT id, kind FROM accounts")}
    n = 0
    for r in con.execute("SELECT id, account_id, out, merchant, category_src, type_src FROM transactions").fetchall():
        bucket = bucket_for(r["category_src"], r["merchant"])
        kind = classify(r["out"], kinds[r["account_id"]], r["category_src"], r["merchant"], bucket, peer, r["type_src"])
        con.execute("UPDATE transactions SET bucket = ?, kind = ?, merchant_key = ? WHERE id = ?",
                    (bucket, kind, norm_merchant(r["merchant"]), r["id"]))
        n += 1
    return n


def fetch_rows(con, since: date | None = None, until: date | None = None, account_filters=None,
               include_superseded=False):
    """Rows as dicts shaped for profile(): date, hour, out, merchant, category, account, bucket, kind, mkey."""
    q = ("SELECT t.*, a.name AS account, a.kind AS acct_kind FROM transactions t JOIN accounts a ON a.id = t.account_id "
         "WHERE 1=1")
    params = []
    if since:
        q += " AND t.date >= ?"
        params.append(since.isoformat())
    if until:
        q += " AND t.date <= ?"
        params.append(until.isoformat())
    if not include_superseded:
        q += " AND t.superseded = 0"
    q += " ORDER BY t.date"
    out = []
    filters = [f.lower() for f in (account_filters or [])]
    for r in con.execute(q, params):
        if filters and not any(f in r["account"].lower() for f in filters):
            continue
        out.append({
            "id": r["id"], "date": date.fromisoformat(r["date"]), "hour": r["hour"], "out": r["out"],
            "merchant": r["merchant"] or "", "category": r["category_src"] or "", "account": r["account"],
            "acct_kind": r["acct_kind"], "bucket": r["bucket"], "kind": r["kind"], "mkey": r["merchant_key"] or "",
            "pending": r["pending"], "source": r["source"],
        })
    return out


def reconcile_shortcut_rows(con, window_days: int = 3) -> int:
    """Mark wallet_shortcut rows superseded when a non-shortcut row matches account, amount and date window."""
    n = 0
    rows = con.execute("SELECT id, account_id, date, out FROM transactions WHERE source = 'wallet_shortcut' AND superseded = 0").fetchall()
    for r in rows:
        d = date.fromisoformat(r["date"])
        match = con.execute(
            "SELECT id FROM transactions WHERE source != 'wallet_shortcut' AND account_id = ? AND ABS(out - ?) < 0.005 "
            "AND date BETWEEN ? AND ? AND superseded = 0 LIMIT 1",
            (r["account_id"], r["out"], (d - _td(window_days)).isoformat(), (d + _td(window_days)).isoformat())).fetchone()
        if match:
            con.execute("UPDATE transactions SET superseded = 1 WHERE id = ?", (r["id"],))
            n += 1
    return n


def _td(days):
    from datetime import timedelta
    return timedelta(days=days)


# ----------------------------------------------------------------------------
# Balances, connectors, characters
# ----------------------------------------------------------------------------

def set_balance(con, account_name: str, value: float, as_of: date, source: str = "manual"):
    aid = get_or_create_account(con, account_name, source)
    con.execute("INSERT OR REPLACE INTO balances(account_id, as_of, balance, source) VALUES (?,?,?,?)",
                (aid, as_of.isoformat(), float(value), source))


def latest_balances(con):
    q = ("SELECT a.name, a.kind, b.as_of, b.balance, b.source FROM balances b JOIN accounts a ON a.id = b.account_id "
         "WHERE b.id IN (SELECT MAX(id) FROM balances GROUP BY account_id) ORDER BY a.name")
    return [dict(r) for r in con.execute(q)]


def log_sync(con, connector: str, started: datetime, rows_added: int, note: str = ""):
    con.execute("INSERT INTO sync_log(connector, started_at, finished_at, rows_added, note) VALUES (?,?,?,?,?)",
                (connector, started.isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds"), rows_added, note))
    con.execute("INSERT INTO connectors(name, status, last_sync) VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET "
                "status = excluded.status, last_sync = excluded.last_sync", (connector, "ok", datetime.now().isoformat(timespec="seconds")))


def save_character(con, name: str, since, until, sheet: dict):
    con.execute("INSERT OR REPLACE INTO characters(name, built_at, since, until, sheet_json) VALUES (?,?,?,?,?)",
                (name, datetime.now().isoformat(timespec="seconds"), since.isoformat() if since else None,
                 until.isoformat() if until else None, json.dumps(sheet)))


def load_character(con, name: str | None = None):
    if name:
        r = con.execute("SELECT * FROM characters WHERE name = ?", (name,)).fetchone()
    else:
        r = con.execute("SELECT * FROM characters ORDER BY built_at DESC LIMIT 1").fetchone()
    if not r:
        return None
    d = dict(r)
    d["sheet"] = json.loads(d.pop("sheet_json"))
    return d


def status(con) -> dict:
    tx = con.execute("SELECT COUNT(*) AS n, MIN(date) AS first, MAX(date) AS last FROM transactions WHERE superseded = 0").fetchone()
    by_source = [dict(r) for r in con.execute("SELECT source, COUNT(*) AS n, MAX(imported_at) AS last_import FROM transactions GROUP BY source")]
    by_account = [dict(r) for r in con.execute(
        "SELECT a.name, a.kind, COUNT(t.id) AS n, MAX(t.date) AS last FROM accounts a LEFT JOIN transactions t ON t.account_id = a.id "
        "GROUP BY a.id ORDER BY a.name")]
    chars = [dict(r) for r in con.execute("SELECT name, built_at, since, until FROM characters ORDER BY built_at DESC")]
    conns = [dict(r) for r in con.execute("SELECT name, status, last_sync, last_error FROM connectors")]
    return {"home": str(mint_home()), "transactions": dict(tx), "by_source": by_source, "by_account": by_account,
            "characters": chars, "connectors": conns, "balances": latest_balances(con)}
