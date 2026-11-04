from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="OVR-VW Operations Workspace", page_icon="🛰️", layout="wide", initial_sidebar_state="collapsed")

# Remove Streamlit chrome/padding so the workspace fills the whole window, exactly like the original page.
st.markdown(
    """
    <style>
    #MainMenu, header, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] {display:none !important;}
    .block-container {padding:0 !important; max-width:100% !important;}
    [data-testid="stAppViewContainer"] > .main {padding:0 !important;}
    iframe[title*="components.v1.html"], [data-testid="stIFrame"] iframe, [data-testid="stCustomComponentV1"] iframe {
        height:100vh !important; width:100% !important; border:0 !important; display:block;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

html = (Path(__file__).parent / "workspace.html").read_text(encoding="utf-8")

# The full original app (UI, simulation, alarms, audio, shift schedule) runs unchanged inside this frame.
components.html(html, height=1000, scrolling=True)
