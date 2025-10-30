# Indoor Air Quality (IAQ) – Software-Only Demo

A local FastAPI + Streamlit app that demonstrates an Indoor Air Quality (IAQ) monitoring system without hardware. It simulates or manually ingests PM2.5, CO₂, temperature, and humidity; stores them in SQLite; computes India CPCB PM2.5 categories and exposure; and renders a demo‑ready dashboard.

## Why software‑only
- Easy to run on any machine, no sensors required
- Useful for class demos, prototyping, and UX/analytics work
- Deterministic seeding so graphs populate instantly for evaluation

## Features
- Live tiles: PM2.5, CO₂, Temp, RH with units
- CPCB PM2.5 categories: Good, Satisfactory, Moderately Polluted, Poor, Very Poor, Severe (color coded)
- Exposure counters: minutes in CPCB zones (24h/7d)
- Trends: time series for all parameters with EWMA overlays
- Status KPIs: ingestion delay and throughput (pts/min)
- Multi‑site: Lab, Classroom, Canteen (site selector)
- Alerts: event log when PM2.5 is Poor or worse; basic ack API
- Actions (visual): “air purifier”/“exhaust fan” toggles that annotate charts
- Manual Ingest: add a reading from the UI
- Seeding/Reset: generate demo data per site; clear site data
- CSV export of current window

## Repository layout
```
An-IoT-Based-Indoor-Air-Quality-Management/
  app/
    streamlit_app.py      # Streamlit UI
    styles.html           # UI tweaks
  backend/
    main.py               # FastAPI, SQLite, CPCB logic, seeding, events
    simulator.py          # optional live pusher to API
  data/
    AirQualityUCI.csv     # reference dataset (not required by app)
  .streamlit/config.toml  # theme
  report/final_report.tex # project report (LaTeX)
requirements.txt
```

## Prerequisites
- Python 3.9+
- pip install -r requirements.txt

## Run locally
1) Start the API (uses SQLite at backend/iaq.db)
```
uvicorn backend.main:app --reload --port 8000
```
2) Start the UI in another terminal
```
streamlit run app/streamlit_app.py
```
The UI targets http://127.0.0.1:8000 by default. To point to a different API, set `IAQ_API=http://host:port` (UI) or add `secrets.api` in Streamlit.

## Seeding data from the UI
- Open the dashboard → “Demo controls (seed/reset)” → choose Site and Hours → “Seed demo data from our downloaded dataset”
- “Stored points” and charts update; use “Seed all sites” to populate Lab, Classroom, Canteen
- Use “Reset data” to clear a site

## Manual ingest (UI)
Use the “Manual Ingest” form to add a single reading (parameter values + site). Charts update immediately.

## API quick reference
Base URL: http://127.0.0.1:8000

- GET `/` → `{ ok, db, last, count }`
- GET `/sites` → list of known sites
- POST `/ingest` → upsert reading `{ ts?, pm25?, co2?, temp?, rh?, site?, source? }`
- GET `/readings?limit=&site=&window=24h|7d` → time‑ordered readings
- GET `/exposure?window=&site=` → CPCB time‑in‑zone minutes
- GET `/stats?window=&site=` → min/mean/max per parameter
- POST `/seed` body `{ hours, site, period_seconds }` → synthesize data
- POST `/reset` body `{ site? }` → delete readings/events
- GET `/events?site=&limit=` → alert log
- POST `/events/ack?event_id=` → acknowledge event

Examples
```
# Seed 24h for Lab
curl -X POST http://127.0.0.1:8000/seed -H "Content-Type: application/json" -d '{"hours":24,"site":"Lab","period_seconds":60}'

# Insert one point
curl -X POST http://127.0.0.1:8000/ingest -H "Content-Type: application/json" -d '{"pm25":35,"co2":800,"temp":27,"rh":50,"site":"Lab"}'
```

## Data model (SQLite)
- `readings(ts TEXT PK, pm25 REAL, co2 REAL, temp REAL, rh REAL, pm25_index INT, pm25_category TEXT, site TEXT, source TEXT)`
- `events(id PK, ts TEXT, site TEXT, type TEXT, severity TEXT, message TEXT, acknowledged INT)`

## CPCB PM2.5 categories (µg/m³)
- 0–30 Good (index 0–50)
- 31–60 Satisfactory (51–100)
- 61–90 Moderately Polluted (101–200)
- 91–120 Poor (201–300)
- 121–250 Very Poor (301–400)
- 251–350 Severe (401–500; capped)

## Configuration
Environment variables:
- `IAQ_DB` (API): path to SQLite DB (default backend/iaq.db)
- `IAQ_API` (UI): base URL for API (default http://127.0.0.1:8000)

## Troubleshooting
- Charts empty → start API with uvicorn, then seed from UI
- “API not reachable” → check `IAQ_API`, port 8000, firewall
- Exposure bars zero → seed/ingest first; verify correct Site in selector

## Development notes
- Simulator can stream readings: `python backend/simulator.py --api http://127.0.0.1:8000 --period 5`
- UI caches API calls for 5s; after ingest/seed it clears caches
- Plotly hover tooltips are enabled
