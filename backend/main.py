from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI
from pydantic import BaseModel, Field
import sqlite3
import os

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
        pm25_category TEXT
    )
    """
)
conn.commit()

# CPCB NAQI mapping for PM2.5
# Breakpoints (µg/m3) mapped to index ranges
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
    # above last band
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

class ExposureOut(BaseModel):
    window: str
    good: int
    satisfactory: int
    moderate: int
    poor: int
    very_poor: int
    severe: int

app = FastAPI(title="IAQ Backend", version="0.1.0")

@app.get("/")
def root():
    return {"ok": True}

@app.post("/ingest")
def ingest(r: ReadingIn):
    ts = r.ts.astimezone(timezone.utc).isoformat()
    idx, cat = sub_index_pm25(r.pm25) if r.pm25 is not None else (None, None)
    conn.execute(
        "INSERT OR REPLACE INTO readings(ts, pm25, co2, temp, rh, pm25_index, pm25_category) VALUES (?,?,?,?,?,?,?)",
        (ts, r.pm25, r.co2, r.temp, r.rh, idx, cat),
    )
    conn.commit()
    return {"inserted": ts, "pm25_index": idx, "pm25_category": cat}

@app.get("/readings")
def readings(limit: int = 500):
    rows = conn.execute(
        "SELECT ts, pm25, co2, temp, rh, pm25_index, pm25_category FROM readings ORDER BY ts DESC LIMIT ?",
        (limit,),
    ).fetchall()
    cols = ["ts", "pm25", "co2", "temp", "rh", "pm25_index", "pm25_category"]
    return [dict(zip(cols, r)) for r in rows][::-1]

@app.get("/exposure", response_model=ExposureOut)
def exposure(window: str = "24h"):
    import pandas as pd
    rows = conn.execute("SELECT ts, pm25_category FROM readings").fetchall()
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
    # assume 1-minute cadence if unknown
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

