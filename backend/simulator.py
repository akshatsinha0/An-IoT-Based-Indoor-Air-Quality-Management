import random
import time
from datetime import datetime, timezone
import requests
import argparse

parser = argparse.ArgumentParser(description="Simulate IAQ readings and post to API")
parser.add_argument("--api", default="http://127.0.0.1:8000", help="FastAPI base URL")
parser.add_argument("--period", type=float, default=5.0, help="Seconds between posts")
parser.add_argument("--jitter", type=float, default=0.2, help="Random jitter fraction")
args = parser.parse_args()

API = args.api.rstrip("/")

# Simple PM2.5 profile that drifts between CPCB bands
bands = [
    (5, 25),     # Good
    (35, 55),    # Satisfactory
    (65, 85),    # Moderate
    (95, 115),   # Poor
    (140, 220),  # Very Poor
    (260, 320),  # Severe
]
state = 0

while True:
    # random walk between bands
    if random.random() < 0.1:
        state = (state + random.choice([-1, 1])) % len(bands)
    lo, hi = bands[state]
    pm25 = random.uniform(lo, hi)
    co2 = random.uniform(400, 1200)
    temp = random.uniform(20, 34)
    rh = random.uniform(30, 75)
    ts = datetime.now(timezone.utc).isoformat()
    try:
        requests.post(f"{API}/ingest", json={"ts": ts, "pm25": pm25, "co2": co2, "temp": temp, "rh": rh}, timeout=5)
    except Exception:
        pass
    t = args.period * (1 + random.uniform(-args.jitter, args.jitter))
    time.sleep(max(0.5, t))
