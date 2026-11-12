"""Kenya Food Security Risk Index: public dashboard (DL-012, DL-026).

Two pages: the risk index (risk_page.py) and "Ask the data" (ask_page.py).

Run locally (from the repo root):
    streamlit run dashboard/app.py
"""
import streamlit as st

st.set_page_config(page_title="Kenya Food Security Risk Index", page_icon="🌾", layout="wide")

page = st.navigation([
    st.Page("risk_page.py", title="Risk index", icon="🌾", default=True),
    st.Page("ask_page.py", title="Ask the data", icon="💬", url_path="ask"),
])
page.run()
