import requests
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime
from pathlib import Path
import os

st.set_page_config(page_title="IAQ Dashboard", layout="wide")

# styles (resolve relative to this file so it works from any CWD)
_style_path = Path(__file__).resolve().parent / "styles.html"
try:
    with open(_style_path, "r", encoding="utf-8") as f:
        st.markdown(f.read(), unsafe_allow_html=True)
except FileNotFoundError:
    st.markdown("", unsafe_allow_html=True)

# Backend URL: prefer Streamlit secrets or env var, else fallback to localhost
try:
    API = st.secrets["api"].rstrip("/")
except Exception:
    API = os.environ.get("IAQ_API", "http://127.0.0.1:8000").rstrip("/")

st.title("An IoT-Based Indoor Air Quality Management")

# Auto-refresh every 5 seconds
st_autorefresh = st.empty()
with st_autorefresh:
    st.caption("🔄 Auto-refreshing every 5 seconds...")

# helpers
CPCB_COLORS = {
    "Good": "#009865",
    "Satisfactory": "#98CE00",
    "Moderately Polluted": "#FFFF00",
    "Poor": "#FF7E00",
    "Very Poor": "#FF0000",
    "Severe": "#7E0023",
}

@st.cache_data(ttl=5)
def api_get(path: str, params=None):
    r = requests.get(f"{API}{path}", params=params or {}, timeout=5)
    r.raise_for_status()
    return r.json()

def api_post(path: str, json=None):
    r = requests.post(f"{API}{path}", json=json or {}, timeout=15)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=5)
def get_sites():
    try:
        sites_from_db = api_get("/sites")
        # Always show all possible sites, even if no data yet
        all_sites = ["Lab", "Classroom", "Canteen"]
        # Merge: prioritize DB sites, then add missing defaults
        for s in all_sites:
            if s not in sites_from_db:
                sites_from_db.append(s)
        return sites_from_db
    except Exception:
        return ["Lab", "Classroom", "Canteen"]

@st.cache_data(ttl=5)
def get_readings(limit=5000, site=None, window=None):
    try:
        params = {"limit": limit}
        if site: params["site"] = site
        if window: params["window"] = window
        data = api_get("/readings", params)
        return pd.DataFrame(data)
    except Exception:
        return pd.DataFrame(columns=["ts","pm25","co2","temp","rh","pm25_index","pm25_category","site","source"])    

@st.cache_data(ttl=5)
def get_exposure(window="24h", site=None):
    try:
        params = {"window": window}
        if site: params["site"] = site
        return api_get("/exposure", params)
    except Exception:
        return {"window":window,"good":0,"satisfactory":0,"moderate":0,"poor":0,"very_poor":0,"severe":0}

# health + site controls
top_col1, top_col2, top_col3, top_col4 = st.columns([2,2,2,2])
api_ok = True
health = {"count": 0, "last": None}
try:
    health = api_get("/")
except Exception:
    api_ok = False
top_col1.markdown(f"**Data source:** {'API' if api_ok else 'Offline'} | `{API}`")
if api_ok:
    total_records = health.get('count', 0)
    top_col2.metric("Total Records", f"{total_records:,}", help="Total sensor readings stored in database")
    last = health.get("last")
    if last:
        try:
            last_dt = pd.to_datetime(last)
            time_ago = (pd.Timestamp.utcnow() - last_dt).total_seconds()
            if time_ago < 60:
                last_display = f"{time_ago:.0f}s ago"
            elif time_ago < 3600:
                last_display = f"{time_ago/60:.0f}m ago"
            else:
                last_display = f"{time_ago/3600:.1f}h ago"
            top_col3.metric("Last Update", last_display, help=f"Latest reading: {last}")
        except:
            top_col3.metric("Last Update", last if last else "—")
    else:
        top_col3.metric("Last Update", "—")
else:
    top_col2.warning("API offline — use Seed")

sites = get_sites() if api_ok else ["Lab","Classroom","Canteen"]
site = top_col4.selectbox("Site", sites, index=0)

# seeding / reset controls
with st.expander("Demo controls (seed/reset)", expanded=not api_ok):
    c1,c2,c3,c4,c5 = st.columns([1.5,1,1,1,1])
    hours = c1.slider("Seed hours", 1, 72, 6, step=1)
    seed_clicked = c2.button("Seed Current Site", disabled=not api_ok)
    seed_all_clicked = c3.button("Seed All Sites", disabled=not api_ok)
    seed_variety_clicked = c4.button("Seed Variety Pack", disabled=not api_ok)
    reset_clicked = c5.button("Reset", disabled=not api_ok)
    
    if seed_clicked and api_ok:
        try:
            res = api_post("/seed", {"hours": hours, "site": site, "period_seconds": 60})
            st.success(f"Seeded {res.get('seeded', 0)} points for {res.get('site', site)}")
            get_readings.clear(); get_exposure.clear(); get_sites.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Seeding failed: {e}")
    if seed_all_clicked and api_ok:
        try:
            for s in ["Lab", "Classroom", "Canteen"]:
                api_post("/seed", {"hours": hours, "site": s, "period_seconds": 60})
            st.success(f"Seeded {hours}h for all sites")
            get_readings.clear(); get_exposure.clear(); get_sites.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Seeding failed: {e}")
    if seed_variety_clicked and api_ok:
        try:
            # Seed different time periods and intervals for variety
            sites_config = [
                ("Lab", hours, 120),  # 2-min intervals
                ("Classroom", hours, 60),  # 1-min intervals
                ("Canteen", hours, 180),  # 3-min intervals
                ("Office", hours//2, 90),  # Half duration, 1.5-min intervals
                ("Library", hours//3, 150),  # Third duration, 2.5-min intervals
                ("Hospital", hours//2, 100),  # Medical facility
                ("Gym", hours//3, 80),  # High activity
                ("Auditorium", hours//2, 110),  # Large gathering
                ("Parking", hours//4, 200),  # Vehicle emissions
            ]
            for s, h, period in sites_config:
                api_post("/seed", {"hours": h, "site": s, "period_seconds": period})
            st.success(f"Seeded variety pack: 9 sites with different patterns")
            get_readings.clear(); get_exposure.clear(); get_sites.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Seeding failed: {e}")
    if reset_clicked and api_ok:
        try:
            api_post("/reset", {"site": site})
            st.success(f"Cleared {site}")
            get_readings.clear(); get_exposure.clear()
        except Exception:
            st.error("Reset failed")
    if not api_ok:
        st.caption("Backend API is offline — start it: uvicorn backend.main:app --reload --port 8000")

colA, colB, colC, colD, colE, colF = st.columns(6)

df = get_readings(site=site, window="24h") if api_ok else pd.DataFrame()
if not df.empty:
    df["ts"] = pd.to_datetime(df["ts"]) 
    latest = df.iloc[-1]
    
    # Get CPCB category and color
    pm25_val = latest.get('pm25', np.nan)
    pm25_cat = latest.get('pm25_category', 'Unknown')
    cat_colors = {
        "Good": "🟢", "Satisfactory": "🟡", "Moderately Polluted": "🟠",
        "Poor": "🔴", "Very Poor": "🟣", "Severe": "🟤"
    }
    pm25_icon = cat_colors.get(pm25_cat, "⚪")
    
    colA.metric("PM2.5 (µg/m³)", f"{pm25_val:.1f}", delta=f"{pm25_cat} {pm25_icon}")
    colB.metric("CO₂ (ppm)", f"{latest.get('co2',np.nan):.0f}")
    colC.metric("Temperature (°C)", f"{latest.get('temp',np.nan):.1f}")
    colD.metric("Humidity (%)", f"{latest.get('rh',np.nan):.0f}")
    
    # simple thermal comfort (humidex-like)
    try:
        T = float(latest.get('temp', np.nan))
        RH = float(latest.get('rh', np.nan))
        e = 6.112*np.exp((17.67*T)/(T+243.5))*RH/100.0
        humidex = T + (5/9)*(e-10)
        colE.metric("Comfort index", f"{humidex:.1f}")
    except Exception:
        pass
    
    # Data freshness indicator
    try:
        time_diff = (pd.Timestamp.utcnow() - df["ts"].iloc[-1]).total_seconds()
        if time_diff < 60:
            freshness = f"🟢 {time_diff:.0f}s ago"
        elif time_diff < 300:
            freshness = f"🟡 {time_diff/60:.0f}m ago"
        else:
            freshness = f"🔴 {time_diff/60:.0f}m ago"
        colF.metric("Data Age", freshness)
    except Exception:
        pass
else:
    st.info("No data yet. Start API then use Seed demo data or Manual Ingest.")

# ingestion/quality status
if not df.empty:
    st.subheader("Status")
    try:
        age = (pd.Timestamp.utcnow() - df["ts"].iloc[-1]).total_seconds()
        rate = max(0.0, len(df.tail(60)) / ((df["ts"].iloc[-1] - df["ts"].iloc[-60]).total_seconds()/60.0)) if len(df) > 60 else len(df) / max(1, (df["ts"].iloc[-1] - df["ts"].iloc[0]).total_seconds()/60.0)
        s1, s2 = st.columns(2)
        s1.metric("Ingestion delay", f"{age:.0f}s")
        s2.metric("Throughput", f"{rate:.1f} pts/min")
    except Exception:
        pass

st.subheader("Trends")
if not df.empty:
    # EWMA bands
    for col in ["pm25","co2"]:
        if col in df:
            df[f"{col}_ewma"] = df[col].ewm(span=30, adjust=False).mean()
    # control simulation toggles (visual only)
    with st.expander("Simulate actions (visual only)"):
        a1, a2 = st.columns(2)
        if a1.toggle("Air purifier active", key="purifier_toggle", value=False):
            if "purifier_started" not in st.session_state:
                st.session_state["purifier_started"] = df["ts"].iloc[-1]
        else:
            st.session_state.pop("purifier_started", None)
        if a2.toggle("Exhaust fan active", key="exhaust_toggle", value=False):
            if "exhaust_started" not in st.session_state:
                st.session_state["exhaust_started"] = df["ts"].iloc[-1]
        else:
            st.session_state.pop("exhaust_started", None)

    y_cols = [c for c in ["pm25","co2","temp","rh"] if c in df.columns]
    fig = px.line(df, x="ts", y=y_cols)
    # overlay EWMA lines
    for col in ["pm25","co2"]:
        if f"{col}_ewma" in df:
            fig.add_trace(go.Scatter(x=df["ts"], y=df[f"{col}_ewma"], name=f"{col.upper()} EWMA", line=dict(dash="dot")))
    # annotate active periods
    now_ts = df["ts"].iloc[-1]
    if "purifier_started" in st.session_state:
        fig.add_vrect(x0=st.session_state["purifier_started"], x1=now_ts, fillcolor="#cce5ff", opacity=0.25, line_width=0, annotation_text="Purifier", annotation_position="top left")
    if "exhaust_started" in st.session_state:
        fig.add_vrect(x0=st.session_state["exhaust_started"], x1=now_ts, fillcolor="#ffe6cc", opacity=0.25, line_width=0, annotation_text="Exhaust", annotation_position="top left")

    fig.update_layout(margin=dict(l=0,r=0,t=24,b=0))
    st.plotly_chart(fig, use_container_width=True)

    # lightweight analytics: ACH estimate & 30m forecast
    met1, met2 = st.columns(2)
    if "co2" in df and df["co2"].notna().any():
        try:
            sub = df.tail(180)  # about last 3 hours if 1-min cadence; safe if denser too
            x = (sub["ts"] - sub["ts"].iloc[0]).dt.total_seconds().values
            co2 = sub["co2"].astype(float).values
            baseline = 400.0
            y = np.log(np.clip(co2 - baseline, 1, None))
            slope, intercept = np.polyfit(x, y, 1)
            ach = max(0.0, -slope * 3600.0)
            met1.metric("Ventilation rate (ACH)", f"{ach:.2f}", help="Estimated from CO₂ decay")
        except Exception:
            pass
    if "pm25" in df and df["pm25"].notna().any():
        try:
            sub = df.tail(60)
            x = (sub["ts"] - sub["ts"].iloc[0]).dt.total_seconds().values
            y = sub["pm25"].astype(float).values
            slope, intercept = np.polyfit(x, y, 1)
            forecast = y[-1] + slope * 1800  # 30 minutes
            met2.metric("PM2.5 forecast (30m)", f"{forecast:.1f} µg/m³")
        except Exception:
            pass

st.subheader("CPCB Exposure (time in zone)")
win = st.selectbox("Window", ["24h","7d"], index=0)
exp = get_exposure(win, site=site)
exp_data = pd.DataFrame({
    "Category":["Good","Satisfactory","Moderately Polluted","Poor","Very Poor","Severe"],
    "Minutes":[exp.get("good",0),exp.get("satisfactory",0),exp.get("moderate",0),exp.get("poor",0),exp.get("very_poor",0),exp.get("severe",0)]
})
fig2 = px.bar(exp_data, x="Category", y="Minutes", color="Category", color_discrete_map=CPCB_COLORS)
fig2.update_layout(margin=dict(l=0,r=0,t=24,b=0))
st.plotly_chart(fig2, use_container_width=True)

st.subheader("Manual Ingest")
with st.form("ingest"):
    c1,c2,c3,c4= st.columns(4)
    pm25 = c1.number_input("PM2.5", min_value=0.0, max_value=1000.0, value=25.0, step=1.0)
    co2 = c2.number_input("CO₂", min_value=0.0, max_value=5000.0, value=600.0, step=10.0)
    temp = c3.number_input("Temp °C", min_value=-10.0, max_value=60.0, value=28.0, step=0.1)
    rh   = c4.number_input("RH %", min_value=0.0, max_value=100.0, value=45.0, step=1.0)
    submitted = st.form_submit_button("Add reading")
    if submitted:
        try:
            api_post("/ingest", {"pm25":pm25,"co2":co2,"temp":temp,"rh":rh, "site": site, "source": "manual"})
            st.success("Reading saved")
            get_readings.clear(); get_exposure.clear()
        except Exception:
            st.error("API not reachable")

st.subheader("Alert log")
if api_ok:
    try:
        events = api_get("/events", {"site": site, "limit": 50})
        if events:
            st.dataframe(pd.DataFrame(events))
        else:
            st.caption("No events yet")
    except Exception:
        st.caption("Events unavailable")

# Statistics Summary
if not df.empty:
    st.subheader("Statistical Summary")
    stat_cols = st.columns(4)
    
    for idx, param in enumerate(['pm25', 'co2', 'temp', 'rh']):
        if param in df.columns:
            with stat_cols[idx]:
                param_data = df[param].astype(float)
                st.markdown(f"**{param.upper()}**")
                st.write(f"Min: {param_data.min():.1f}")
                st.write(f"Mean: {param_data.mean():.1f}")
                st.write(f"Max: {param_data.max():.1f}")
                st.write(f"Std: {param_data.std():.1f}")

# Site Comparison
if api_ok:
    st.subheader("Multi-Site Comparison")
    try:
        all_sites = get_sites()
        if len(all_sites) > 1:
            comparison_data = []
            for s in all_sites:
                site_df = get_readings(site=s, window="24h")
                if not site_df.empty:
                    site_df["ts"] = pd.to_datetime(site_df["ts"])
                    latest_site = site_df.iloc[-1]
                    comparison_data.append({
                        "Site": s,
                        "PM2.5": latest_site.get('pm25', 0),
                        "CO2": latest_site.get('co2', 0),
                        "Temp": latest_site.get('temp', 0),
                        "Humidity": latest_site.get('rh', 0),
                        "Category": latest_site.get('pm25_category', 'Unknown')
                    })
            
            if comparison_data:
                comp_df = pd.DataFrame(comparison_data)
                st.dataframe(comp_df, use_container_width=True)
                
                # Comparison charts
                comp_col1, comp_col2 = st.columns(2)
                with comp_col1:
                    fig_pm25 = px.bar(comp_df, x="Site", y="PM2.5", color="Category",
                                      color_discrete_map=CPCB_COLORS,
                                      title="PM2.5 Comparison Across Sites")
                    st.plotly_chart(fig_pm25, use_container_width=True)
                
                with comp_col2:
                    fig_co2 = px.bar(comp_df, x="Site", y="CO2",
                                     title="CO₂ Comparison Across Sites")
                    st.plotly_chart(fig_co2, use_container_width=True)
    except Exception as e:
        st.caption(f"Comparison unavailable: {e}")

# export
if not df.empty:
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", data=csv, file_name=f"iaq_{site}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv")

# Auto-refresh trigger
import time
time.sleep(5)
st.rerun()
