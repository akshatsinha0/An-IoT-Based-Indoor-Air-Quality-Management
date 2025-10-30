import requests
import pandas as pd
import numpy as np
import plotly.express as px
import streamlit as st
from datetime import datetime
from pathlib import Path

st.set_page_config(page_title="IAQ Dashboard", layout="wide")

# styles (resolve relative to this file so it works from any CWD)
_style_path = Path(__file__).resolve().parent / "styles.html"
try:
    with open(_style_path, "r", encoding="utf-8") as f:
        st.markdown(f.read(), unsafe_allow_html=True)
except FileNotFoundError:
    st.markdown("", unsafe_allow_html=True)

API = st.secrets.get("api", "http://127.0.0.1:8000").rstrip("/")

st.title("An IoT-Based Indoor Air Quality Management")

colA, colB, colC, colD = st.columns(4)

@st.cache_data(ttl=5)
def get_readings(limit=1000):
    try:
        r = requests.get(f"{API}/readings", params={"limit": limit}, timeout=5)
        r.raise_for_status()
        return pd.DataFrame(r.json())
    except Exception:
        return pd.DataFrame(columns=["ts","pm25","co2","temp","rh","pm25_index","pm25_category"])    

@st.cache_data(ttl=5)
def get_exposure(window="24h"):
    try:
        r = requests.get(f"{API}/exposure", params={"window": window}, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {"window":window,"good":0,"satisfactory":0,"moderate":0,"poor":0,"very_poor":0,"severe":0}

# latest
df = get_readings()
if not df.empty:
    df["ts"] = pd.to_datetime(df["ts"]) 
    latest = df.iloc[-1]
    colA.metric("PM2.5 (µg/m³)", f"{latest.get('pm25',np.nan):.1f}", help="Particulate Matter 2.5")
    colB.metric("CO₂ (ppm)", f"{latest.get('co2',np.nan):.0f}")
    colC.metric("Temperature (°C)", f"{latest.get('temp',np.nan):.1f}")
    colD.metric("Humidity (%)", f"{latest.get('rh',np.nan):.0f}")
else:
    st.info("No data yet. Start the API and the simulator.")

st.subheader("Trends")
if not df.empty:
    fig = px.line(df, x="ts", y=[c for c in ["pm25","co2","temp","rh"] if c in df.columns])
    fig.update_layout(margin=dict(l=0,r=0,t=24,b=0))
    st.plotly_chart(fig, use_container_width=True)

st.subheader("CPCB Exposure (time in zone)")
win = st.selectbox("Window", ["24h","7d"], index=0)
exp = get_exposure(win)
exp_data = pd.DataFrame({
    "Category":["Good","Satisfactory","Moderately Polluted","Poor","Very Poor","Severe"],
    "Minutes":[exp.get("good",0),exp.get("satisfactory",0),exp.get("moderate",0),exp.get("poor",0),exp.get("very_poor",0),exp.get("severe",0)]
})
fig2 = px.bar(exp_data, x="Category", y="Minutes")
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
            r = requests.post(f"{API}/ingest", json={"pm25":pm25,"co2":co2,"temp":temp,"rh":rh}, timeout=5)
            if r.ok:
                st.success("Reading saved")
                get_readings.clear()
                get_exposure.clear()
            else:
                st.error(f"Error {r.status_code}")
        except Exception as e:
            st.error("API not reachable")
