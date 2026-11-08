"""Interface Streamlit qui appelle l'API FastAPI."""

import os

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="Financial Report Intelligence", page_icon="📊")
st.title("Financial Report Intelligence")

with st.sidebar:
    company = st.text_input("Société (optionnel)")
    year = st.number_input("Année (optionnel)", min_value=0, max_value=2100, value=0, step=1)

question = st.chat_input("Posez une question sur un rapport financier")
if question:
    st.chat_message("user").write(question)
    payload = {"question": question, "company": company or None, "year": int(year) or None}
    resp = requests.post(f"{API_URL}/ask", json=payload, timeout=120)
    data = resp.json()
    with st.chat_message("assistant"):
        st.write(data["answer"])
        for c in data.get("citations", []):
            st.caption(f"[{c['company']}, {c['year']}, p. {c['page']}]")
