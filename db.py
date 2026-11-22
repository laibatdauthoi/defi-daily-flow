"""SQLite storage: one snapshot per UTC day. Re-running the same day replaces it."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    day          TEXT PRIMARY KEY,   -- YYYY-MM-DD (UTC)
    fetched_at   TEXT NOT NULL,      -- ISO timestamp UTC
    n_protocols  INTEGER,
    n_fee_protocols INTEGER
);
CREATE TABLE IF NOT EXISTS prices (
    day TEXT, coin TEXT, price REAL, price_7d_ago REAL, price_ts INTEGER,
    PRIMARY KEY (day, coin)
);
-- Aggregated over ALL protocols (excludes chain-level fee entries)
CREATE TABLE IF NOT EXISTS category_snap (
    day TEXT, category TEXT,
    n_protocols INTEGER,
    tvl REAL, tvl_7d_ago REAL,
    fees_7d REAL, fees_prev_7d REAL, n_fee_protocols INTEGER,
    PRIMARY KEY (day, category)
);
CREATE TABLE IF NOT EXISTS chain_snap (
    day TEXT, chain TEXT,
    tvl REAL, tvl_7d_ago REAL,
    stables REAL, stables_7d_ago REAL,
    fees_7d REAL, fees_prev_7d REAL,
    PRIMARY KEY (day, chain)
);
-- Only protocols that matter (TVL or fees above thresholds), to keep the DB small
CREATE TABLE IF NOT EXISTS protocol_snap (
    day TEXT, slug TEXT, name TEXT, category TEXT, parent TEXT,
    source TEXT,                       -- 'protocols' or 'fees_only' (token info unknown)
    symbol TEXT, gecko_id TEXT, listed_at INTEGER,
    tvl REAL, tvl_change_7d REAL,
    fees_7d REAL, fees_prev_7d REAL,
    PRIMARY KEY (day, slug)
);
"""

TABLES = ["runs", "prices", "category_snap", "chain_snap", "protocol_snap"]
PROTOCOL_KEEP_DAYS = 90  # detailed rows pruned after this; aggregates kept forever


def connect(path):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def _insert(con, table, rows):
    if not rows:
        return
    cols = list(rows[0].keys())
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
    con.executemany(sql, [tuple(r[c] for c in cols) for r in rows])


def save_snapshot(con, snap):
    """snap: dict from fetch.build_snapshot(). Atomic: all or nothing."""
    day = snap["day"]
    with con:
        for t in TABLES:
            con.execute(f"DELETE FROM {t} WHERE day = ?", (day,))
        _insert(con, "runs", [{
            "day": day, "fetched_at": snap["fetched_at"],
            "n_protocols": snap["n_protocols"], "n_fee_protocols": snap["n_fee_protocols"],
        }])
        for t in ["prices", "category_snap", "chain_snap", "protocol_snap"]:
            _insert(con, t, [dict(r, day=day) for r in snap[t]])
        con.execute(
            "DELETE FROM protocol_snap WHERE day < date(?, ?)",
            (day, f"-{PROTOCOL_KEEP_DAYS} days"),
        )
