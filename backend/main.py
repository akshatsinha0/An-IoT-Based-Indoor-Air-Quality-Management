from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict
from fastapi import FastAPI, Query
from pydantic import BaseModel, Field
import sqlite3
import os
import random

DB_PATH = os.environ.get("IAQ_DB", os.path.join(os.path.dirname(__file__), "iaq.db"))

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

conn = get_conn()
cur = conn.cursor()
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS readings (
        ts TEXT PRIMARY KEY,
        pm25 REAL,
        co2 REAL,
        temp REAL,
        rh REAL,
        pm25_index INTEGER,
        pm25_category TEXT,
        site TEXT DEFAULT 'Lab',
        source TEXT
    )
    """
)
# lightweight events table for alerts/logging
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT,
        site TEXT,
        type TEXT,
        severity TEXT,
        message TEXT,
        acknowledged INTEGER DEFAULT 0
    )
    """
)
conn.commit()

# Schema migration for missing columns on existing DBs
def ensure_column(table: str, name: str, type_sql: str):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {type_sql}")
        conn.commit()

ensure_column("readings", "site", "TEXT DEFAULT 'Lab'")
ensure_column("readings", "source", "TEXT")

# CPCB NAQI mapping for PM2.5
PM25_BP = [
    (0, 30, 0, 50, "Good", "#009865"),
    (31, 60, 51, 100, "Satisfactory", "#98CE00"),
    (61, 90, 101, 200, "Moderately Polluted", "#FFFF00"),
    (91, 120, 201, 300, "Poor", "#FF7E00"),
    (121, 250, 301, 400, "Very Poor", "#FF0000"),
    (251, 350, 401, 500, "Severe", "#7E0023"),
]

def sub_index_pm25(v: float):
    if v is None:
        return None, None
    for Blo, Bhi, Ilo, Ihi, cat, _ in PM25_BP:
        if Blo <= v <= Bhi:
            I = (Ihi - Ilo) / (Bhi - Blo) * (v - Blo) + Ilo
            return int(round(I)), cat
    last = PM25_BP[-1]
    Blo, Bhi, Ilo, Ihi, cat, _ = last
    I = (Ihi - Ilo) / (Bhi - Blo) * (v - Blo) + Ihi
    return int(round(max(I, Ihi))), cat

class ReadingIn(BaseModel):
    ts: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))
    pm25: Optional[float] = None
    co2: Optional[float] = None
    temp: Optional[float] = None
    rh: Optional[float] = None
    site: Optional[str] = Field(default="Lab")
    source: Optional[str] = Field(default=None)

class ExposureOut(BaseModel):
    window: str
    good: int
    satisfactory: int
    moderate: int
    poor: int
    very_poor: int
    severe: int

class SeedIn(BaseModel):
    hours: int = 24
    site: str = "Lab"
    period_seconds: int = 60

app = FastAPI(title="IAQ Backend", version="0.2.0")

@app.get("/")
def root():
    last = conn.execute("SELECT MAX(ts) FROM readings").fetchone()[0]
    count = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    return {"ok": True, "db": os.path.abspath(DB_PATH), "last": last, "count": count}

@app.get("/sites")
def sites() -> List[str]:
    rows = conn.execute("SELECT DISTINCT site FROM readings ORDER BY site").fetchall()
    return [r[0] for r in rows] or ["Lab"]

def insert_reading(r: ReadingIn):
    ts = r.ts.astimezone(timezone.utc).isoformat()
    idx, cat = sub_index_pm25(r.pm25) if r.pm25 is not None else (None, None)
    conn.execute(
        "INSERT OR REPLACE INTO readings(ts, pm25, co2, temp, rh, pm25_index, pm25_category, site, source) VALUES (?,?,?,?,?,?,?,?,?)",
        (ts, r.pm25, r.co2, r.temp, r.rh, idx, cat, r.site or "Lab", r.source),
    )
    # simple alert log when category Poor or worse
    if cat in ("Poor", "Very Poor", "Severe"):
        conn.execute(
            "INSERT INTO events(ts, site, type, severity, message) VALUES (?,?,?,?,?)",
            (ts, r.site or "Lab", "pm25_alert", "warning" if cat=="Poor" else "critical", f"PM2.5 is {cat} ({r.pm25:.1f} µg/m³)"),
        )
    conn.commit()
    return ts, idx, cat

@app.post("/ingest")
def ingest(r: ReadingIn):
    ts, idx, cat = insert_reading(r)
    return {"inserted": ts, "pm25_index": idx, "pm25_category": cat}

@app.get("/readings")
def readings(limit: int = 500, site: Optional[str] = None, window: Optional[str] = Query(default=None, description="e.g. 24h, 7d")):
    base = "SELECT ts, pm25, co2, temp, rh, pm25_index, pm25_category, site, source FROM readings"
    where = []
    params: List = []
    if site:
        where.append("site = ?")
        params.append(site)
    if window:
        # window like 24h or 7d
        import pandas as pd
        max_ts = conn.execute("SELECT MAX(ts) FROM readings").fetchone()[0]
        if max_ts:
            now = pd.to_datetime(max_ts)
            delta = pd.Timedelta(window)
            start = (now - delta).isoformat()
            where.append("ts >= ?")
            params.append(start)
    if where:
        base += " WHERE " + " AND ".join(where)
    base += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(base, tuple(params)).fetchall()
    cols = ["ts", "pm25", "co2", "temp", "rh", "pm25_index", "pm25_category", "site", "source"]
    return [dict(zip(cols, r)) for r in rows][::-1]

@app.get("/exposure", response_model=ExposureOut)
def exposure(window: str = "24h", site: Optional[str] = None):
    import pandas as pd
    q = "SELECT ts, pm25_category FROM readings"
    params: List = []
    if site:
        q += " WHERE site = ?"
        params.append(site)
    rows = conn.execute(q, tuple(params)).fetchall()
    if not rows:
        return ExposureOut(window=window, good=0, satisfactory=0, moderate=0, poor=0, very_poor=0, severe=0)
    df = pd.DataFrame(rows, columns=["ts", "cat"])
    df["ts"] = pd.to_datetime(df["ts"])
    now = df["ts"].max()
    delta = pd.Timedelta(window)
    df = df[df["ts"] >= now - delta]
    df = df.sort_values("ts")
    if df.empty:
        return ExposureOut(window=window, good=0, satisfactory=0, moderate=0, poor=0, very_poor=0, severe=0)
    df["dt"] = df["ts"].diff().dt.total_seconds().fillna(60)
    minutes = df.groupby("cat")["dt"].sum() / 60.0
    def m(cat):
        return int(round(minutes.get(cat, 0)))
    return ExposureOut(
        window=window,
        good=m("Good"),
        satisfactory=m("Satisfactory"),
        moderate=m("Moderately Polluted"),
        poor=m("Poor"),
        very_poor=m("Very Poor"),
        severe=m("Severe"),
    )

@app.get("/stats")
def stats(window: str = "24h", site: Optional[str] = None) -> Dict:
    import pandas as pd
    rows = readings(limit=1000000, site=site, window=window)  # reuse
    if not rows:
        return {"window": window, "count": 0}
    df = pd.DataFrame(rows)
    out = {"window": window, "count": len(df), "last": df["ts"].iloc[-1]}
    for col in ["pm25", "co2", "temp", "rh"]:
        if col in df:
            s = df[col].astype(float)
            out[col] = {
                "min": float(s.min()),
                "mean": float(s.mean()),
                "max": float(s.max()),
            }
    return out

@app.post("/seed")
def seed(payload: SeedIn):
    hours = payload.hours
    site = payload.site
    period_seconds = payload.period_seconds
    now = datetime.now(timezone.utc)
    n = int(hours * 3600 / period_seconds)
    # generate backwards in time so ts unique and sorted
    for i in range(n):
        ts = now - timedelta(seconds=(n - i) * period_seconds)
        # cycle through CPCB bands roughly
        band = (i // max(1, n // 6)) % 6
        ranges = [
            (5, 25), (35, 55), (65, 85), (95, 115), (140, 220), (260, 320)
        ]
        lo, hi = ranges[band]
        pm25 = random.uniform(lo, hi)
        co2 = random.uniform(450, 1200)
        temp = random.uniform(22, 33)
        rh = random.uniform(35, 70)
        insert_reading(ReadingIn(ts=ts, pm25=pm25, co2=co2, temp=temp, rh=rh, site=site, source="seed"))
    return {"seeded": n, "site": site, "period_seconds": period_seconds}

@app.get("/events")
def get_events(limit: int = 100, site: Optional[str] = None):
    q = "SELECT id, ts, site, type, severity, message, acknowledged FROM events"
    params: List = []
    if site:
        q += " WHERE site = ?"
        params.append(site)
    q += " ORDER BY ts DESC, id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(q, tuple(params)).fetchall()
    cols = ["id","ts","site","type","severity","message","acknowledged"]
    return [dict(zip(cols, r)) for r in rows]

@app.post("/events/ack")
def ack_event(event_id: int):
    conn.execute("UPDATE events SET acknowledged=1 WHERE id=?", (event_id,))
    conn.commit()
    return {"acknowledged": event_id}

@app.post("/reset")
def reset(site: Optional[str] = None):
    if site:
        conn.execute("DELETE FROM readings WHERE site=?", (site,))
        conn.execute("DELETE FROM events WHERE site=?", (site,))
    else:
        conn.execute("DELETE FROM readings")
        conn.execute("DELETE FROM events")
    conn.commit()
    return {"ok": True}
