"""
EVCharge — Streamlit frontend.

Run (from streamlit-app/):  uv run streamlit run app.py
Backend URL:                EVCHARGE_API_URL (default http://127.0.0.1:8080)
"""
import streamlit as st

st.set_page_config(page_title="EVCharge", page_icon=":material/ev_station:", layout="wide")

pages = [
    st.Page("views/home.py", title="Home", icon=":material/home:", default=True),
    st.Page("views/stations.py", title="Stations", icon=":material/ev_station:"),
    st.Page("views/book.py", title="Book", icon=":material/event_available:"),
    st.Page("views/bookings.py", title="My bookings", icon=":material/receipt_long:"),
    st.Page("views/nerd_stats.py", title="Model insights", icon=":material/insights:"),
]

st.navigation(pages, position="top").run()

st.divider()
st.caption("Demonstration project. Stations and bookings are sample data. Prices are based on forecasts from "
           "historical charging data, not live traffic.")
