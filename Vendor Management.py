import os
import re
import io
import base64
import time
import hashlib
import hmac
from datetime import datetime, date, time as dtime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st
import extra_streamlit_components as stx
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import PyMongoError, DuplicateKeyError

try:
    import bcrypt
except ImportError:
    bcrypt = None

# ============================================================
# CASEFLOW — HPE TEAM TASK / CASE MANAGEMENT
# MongoDB: TeamRoster / Team Roster Collection
# Salesforce: https://hp.lightning.force.com/
#
# Recommended:
#   pip install streamlit pymongo bcrypt pandas openpyxl
#
# MongoDB URI:
#   .streamlit/secrets.toml
#       MONGO_URI="mongodb+srv://..."
#
# The app intentionally stores password hashes, never plaintext
# passwords. All operational changes are persisted to MongoDB.
# ============================================================

APP_TZ = ZoneInfo("Asia/Manila")
DEFAULT_SF_URL = "https://hp.lightning.force.com/"
AUTO_ADMIN_EMAIL = "admin"
AUTO_ADMIN_PASSWORD = "Admin1234"

DB_NAME = "TeamRoster"
USER_COLLECTION = "Team Roster Collection"

SESSION_COOKIE_NAME = "hpe_caseflow_session"
SESSION_COOKIE_DAYS = 7

def get_session_secret():
    """Stable signing secret without putting credentials in the browser."""
    configured = None
    try:
        configured = st.secrets.get("SESSION_SECRET")
    except Exception:
        pass
    configured = configured or os.getenv("SESSION_SECRET")
    if configured:
        return str(configured)

    # Fallback keeps tokens stable for the current deployment while still
    # avoiding plaintext credentials in the cookie. For production, set
    # SESSION_SECRET in Streamlit secrets.
    uri = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI") or ""
    return hashlib.sha256(
        f"HPE-CASEFLOW-SESSION::{uri}::{AUTO_ADMIN_PASSWORD}".encode()
    ).hexdigest()

POLL_SECONDS = 15
DUE_SOON_HOURS = 4
STALE_HOURS = 24

AUX_OPTIONS = [
    "Available",
    "Admin Task",
    "Break",
    "Lunch",
    "In a Meeting",
    "Coaching",
    "Busy - Away",
    "Unscheduled Break",
]

CASE_STATUSES = [
    "New",
    "Assigned",
    "In Progress",
    "Pending Vendor",
    "Pending Technician",
    "Waiting for Customer",
    "Completed",
    "Contract Breached",
    "Cancelled",
]

PRIORITIES = ["Critical", "High", "Medium", "Low"]

BREACH_REASONS = {
    "Vendor missed committed delivery": "The vendor did not deliver within the committed timeframe.",
    "Vendor failed to respond": "The vendor failed to provide the required response or update within the expected timeframe.",
    "Vendor missed scheduled appointment": "The vendor failed to attend or complete the scheduled appointment.",
    "Repeated vendor delay": "The vendor has repeatedly delayed delivery despite follow-up.",
    "Other contractual violation": "The vendor did not meet the applicable contractual service requirement.",
}

REQUEST_TYPES = ["Sick Leave", "Emergency Leave", "PTO", "Schedule Swap", "Schedule Change"]

st.set_page_config(
    page_title="HPE CaseFlow",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------- Styling ---------------------------

st.markdown(
    """
<style>
:root {
  --navy:#062b49;
  --navy2:#0a3d61;
  --blue:#0879bd;
  --blue2:#145b86;
  --teal:#0d6d68;
  --green:#16855b;
  --yellow:#d5a20a;
  --red:#d33b3b;
  --purple:#7754a5;
  --bg:#eef3f6;
  --card:#ffffff;
  --line:#d7e0e7;
  --muted:#657485;
  --text:#183047;
}

/* Overall canvas */
html, body, [class*="css"] {
  font-family: Inter, Arial, sans-serif;
}
[data-testid="stAppViewContainer"] {
  background:var(--bg);
}
[data-testid="stHeader"] {
  background:transparent;
}
.block-container {
  padding-top:.35rem;
  padding-left:.45rem;
  padding-right:.45rem;
  padding-bottom:.5rem;
  max-width:1550px;
}

/* Sidebar — compact navy navigation like the reference */
[data-testid="stSidebar"] {
  background:linear-gradient(180deg,#062b49 0%,#073652 100%) !important;
  border-right:1px solid #0d5277 !important;
  min-width:230px !important;
  max-width:230px !important;
  width:230px !important;
  display:block !important;
  visibility:visible !important;
  z-index:100 !important;
}
[data-testid="stSidebar"][aria-expanded="false"] {
  min-width:0 !important;
  max-width:0 !important;
  width:0 !important;
}
[data-testid="stSidebar"] > div:first-child {
  width:230px !important;
}
[data-testid="stSidebarCollapsedControl"] {
  display:flex !important;
  visibility:visible !important;
  z-index:999 !important;
  top:8px !important;
}

[data-testid="stSidebar"] > div:first-child {
  padding:8px 8px 12px 8px;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
  color:#fff;
}
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] small {
  color:#d7e8f2 !important;
}
[data-testid="stSidebar"] button {
  border:0 !important;
  border-radius:3px !important;
  background:transparent !important;
  color:#eaf5fb !important;
  text-align:left !important;
  justify-content:flex-start !important;
  min-height:31px !important;
  padding:4px 8px !important;
  font-size:12px !important;
  box-shadow:none !important;
}
[data-testid="stSidebar"] button:hover {
  background:#0b5279 !important;
}
[data-testid="stSidebar"] hr {
  border-color:rgba(255,255,255,.15);
}

/* Reference-style top/page bars */
.reference-topbar {
  background:#082f4d;
  color:#fff;
  border-radius:5px;
  padding:7px 11px;
  margin-bottom:5px;
  display:flex;
  align-items:center;
  justify-content:space-between;
}
.reference-topbar h1 {
  margin:0;
  font-size:22px;
  letter-spacing:.2px;
  font-weight:800;
}
.reference-topbar p {
  margin:0;
  font-size:11px;
  opacity:.9;
}
.page-title-bar {
  background:#0c466b;
  color:#fff;
  border-radius:5px;
  padding:7px 10px;
  margin:2px 0 6px 0;
}
.page-title-bar .title {
  font-size:15px;
  font-weight:800;
  margin:0;
}
.page-title-bar .subtitle {
  font-size:10px;
  margin-top:1px;
  opacity:.92;
}

/* White content cards */
[data-testid="stVerticalBlockBorderWrapper"] {
  border-radius:6px !important;
}
.case-card,
.metric-card,
.panel-card {
  background:#fff;
  border:1px solid var(--line);
  border-radius:5px;
  box-shadow:0 1px 3px rgba(20,40,60,.08);
}
.metric-card {
  padding:8px 10px;
  min-height:72px;
}
.metric-title {
  color:#627385;
  font-size:10px;
  font-weight:600;
}
.metric-value {
  font-size:24px;
  line-height:1.05;
  font-weight:800;
  color:#12314a;
}
.metric-sub {
  color:#7a8896;
  font-size:9px;
}
.case-card {
  padding:7px 9px;
  margin-bottom:5px;
}
.case-id {
  color:#0879bd;
  font-weight:800;
  font-size:11px;
}
.muted {
  color:#667789;
  font-size:10px;
}
.small-note {
  font-size:9px;
  color:#6c7c8b;
}
.badge {
  display:inline-block;
  border-radius:4px;
  padding:2px 5px;
  font-size:9px;
  background:#edf2f7;
  margin-right:3px;
  color:#405366;
}
.badge-red {
  background:#ffdfe0;
  color:#a32222;
}
.badge-yellow {
  background:#fff0bf;
  color:#7e6000;
}
.badge-green {
  background:#d9f3e6;
  color:#086c46;
}
.case-red {
  border-left:4px solid var(--red) !important;
}
.case-yellow {
  border-left:4px solid var(--yellow) !important;
}
.case-green {
  border-left:4px solid var(--green) !important;
}
.alert-box {
  background:#fff5d8;
  border:1px solid #eed17a;
  padding:6px 8px;
  border-radius:4px;
  margin-bottom:5px;
  font-size:10px;
}

/* Compact controls / tables */
.stButton > button,
.stDownloadButton > button,
.stFormSubmitButton > button {
  border-radius:4px !important;
  min-height:30px !important;
  padding:4px 10px !important;
  font-size:11px !important;
}
.stTextInput input,
.stTextArea textarea,
.stSelectbox div[data-baseweb="select"],
.stDateInput input,
.stTimeInput input {
  border-radius:4px !important;
  font-size:11px !important;
}
[data-testid="stDataFrame"] {
  border:1px solid var(--line);
  border-radius:5px;
}
[data-testid="stMetric"] {
  background:#fff;
  border:1px solid var(--line);
  border-radius:5px;
  padding:6px;
}

/* Make Streamlit headings compact like the reference */
h1 { font-size:21px !important; color:#14344d; }
h2 { font-size:16px !important; color:#14344d; margin-top:8px !important; }
h3 { font-size:13px !important; color:#173b56; margin-top:7px !important; }
p, label, .stCaption { font-size:11px; }


/* Hide Streamlit application chrome while preserving the sidebar
   collapse/expand control. */
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
[data-testid="stAppDeployButton"],
#MainMenu,
footer {
  display:none !important;
}

/* Do NOT collapse the Streamlit header itself. The sidebar toggle lives
   in the header; hiding the whole header makes the navigation disappear. */
header[data-testid="stHeader"] {
  background:transparent !important;
  height:2rem !important;
  min-height:2rem !important;
  box-shadow:none !important;
}

/* Keep the CaseFlow sidebar visible and TV-friendly. */
[data-testid="stSidebar"] {
  display:block !important;
  visibility:visible !important;
  width:235px !important;
  min-width:235px !important;
  max-width:235px !important;
  z-index:999 !important;
}

[data-testid="stSidebar"] > div:first-child {
  width:235px !important;
  min-width:235px !important;
}

/* Preserve the native collapse/expand affordance. */
[data-testid="stSidebarCollapsedControl"] {
  display:flex !important;
  visibility:visible !important;
}

/* Profile popover */
.profile-anchor {
  text-align:right;
}

/* Reference-style profile button */
[data-testid="stPopover"] button {
  font-size:10px !important;
  min-height:28px !important;
}

/* Compact tab-like segmented controls */
.stTabs [data-baseweb="tab-list"] {
  gap:2px;
  background:#eef3f6;
  padding:2px;
  border-radius:4px;
}
.stTabs [data-baseweb="tab"] {
  font-size:10px !important;
  padding:5px 9px !important;
}


/* ===== Uploaded-reference visual system ===== */
[data-testid="stAppViewContainer"] {
  background:#eef2f5 !important;
}
.block-container {
  max-width:1536px !important;
  padding-top:4px !important;
  padding-bottom:8px !important;
  padding-left:8px !important;
  padding-right:8px !important;
}
.reference-topbar {
  min-height:42px;
  border-radius:4px;
  background:#082f4d !important;
  padding:5px 10px !important;
}
.reference-topbar h1 {
  font-size:20px !important;
  line-height:1.05 !important;
}
.reference-topbar p {
  font-size:10px !important;
}
.page-title-bar {
  background:#0b4568 !important;
  border-radius:4px !important;
  padding:6px 9px !important;
  margin:2px 0 5px 0 !important;
}
.page-title-bar .title {
  font-size:14px !important;
}
.page-title-bar .subtitle {
  font-size:10px !important;
}

/* Metric tiles exactly follow the screenshot's compact proportions. */
.metric-card {
  background:#fff !important;
  border:1px solid #d5dfe6 !important;
  border-radius:4px !important;
  min-height:58px !important;
  padding:7px 8px !important;
  box-shadow:none !important;
}
.metric-title {
  font-size:9px !important;
  color:#526474 !important;
  font-weight:700 !important;
  text-transform:none !important;
}
.metric-value {
  font-size:21px !important;
  font-weight:800 !important;
  line-height:1.05 !important;
}
.metric-sub {
  font-size:8px !important;
}

/* Streamlit widgets: compact enterprise controls. */
.stButton > button {
  border-radius:3px !important;
  min-height:29px !important;
  padding:3px 8px !important;
  font-size:10px !important;
}
.stTextInput input,
.stTextArea textarea,
.stSelectbox [data-baseweb="select"] > div,
.stDateInput input {
  min-height:29px !important;
  font-size:10px !important;
  border-radius:3px !important;
}
.stDataFrame {
  border-radius:3px !important;
}
[data-testid="stExpander"] {
  border-radius:4px !important;
  border:1px solid #d7e0e7 !important;
}
h1,h2,h3,h4 {
  color:#183047 !important;
}
.stCaption {
  font-size:9px !important;
}

/* Reference screenshot uses dense panel layouts rather than large gaps. */
[data-testid="stVerticalBlockBorderWrapper"] {
  border-radius:4px !important;
  border:1px solid #d6e0e7 !important;
}
[data-testid="stHorizontalBlock"] {
  gap:6px !important;
}

/* Keep profile at the upper-right without exposing Streamlit chrome. */
.profile-button {
  font-size:10px;
}

/* Sidebar visual language from screenshot. */
[data-testid="stSidebar"] {
  box-shadow:2px 0 5px rgba(0,0,0,.08) !important;
}
[data-testid="stSidebar"] button {
  margin:1px 0 !important;
  border-radius:2px !important;
  font-weight:600 !important;
}
[data-testid="stSidebar"] button p {
  font-size:11px !important;
}
[data-testid="stSidebar"] button[kind="secondary"] {
  background:transparent !important;
}

/* Hide Streamlit product chrome but retain sidebar collapse control. */
#MainMenu { visibility:hidden !important; }
footer { visibility:hidden !important; }
[data-testid="stToolbar"] { visibility:hidden !important; height:0 !important; }
[data-testid="stDecoration"] { display:none !important; }

/* ===== Authentication — matches uploaded Sign In / Sign Up reference ===== */
.auth-page {
  min-height:calc(100vh - 8px);
  padding:0;
  background:
    radial-gradient(circle at 18% 8%, rgba(68,142,204,.72), transparent 35%),
    linear-gradient(135deg,#5e98c5 0%,#326b9b 55%,#285c88 100%);
  border-radius:0;
}
body:has(.auth-page) [data-testid="stHorizontalBlock"] {
  max-width:1000px !important;
  min-height:680px;
  margin:0 auto !important;
  padding-top:0 !important;
  background:#f8fafc;
  border-radius:17px;
  overflow:hidden;
  box-shadow:0 18px 45px rgba(7,34,62,.25);
  gap:0 !important;
}
body:has(.auth-page) [data-testid="column"] {
  padding:0 !important;
}
.auth-brand-panel {
  position:relative;
  height:680px;
  overflow:hidden;
  background:
    linear-gradient(180deg,rgba(4,44,83,.96) 0%,rgba(4,48,88,.91) 58%,rgba(5,43,76,.97) 100%);
  color:#fff;
}
.auth-brand-content {
  position:relative;
  z-index:2;
  padding:35px 34px 0 35px;
}
.hpe-mark {
  width:72px;
  height:25px;
  border:5px solid #00a98f;
  border-bottom-width:5px;
  margin-bottom:15px;
  box-sizing:border-box;
}
.hpe-mark span {
  display:block;
  width:42px;
  height:3px;
  margin:5px auto 0;
  background:#00a98f;
}
.hpe-name {
  font-size:21px;
  line-height:.98;
  font-weight:800;
  letter-spacing:-.4px;
}
.hpe-rule {
  width:92px;
  height:2px;
  background:#00a98f;
  margin:25px 0 22px;
}
.caseflow-name {
  font-size:28px;
  line-height:1.05;
  font-weight:800;
  letter-spacing:-.8px;
}
.caseflow-subtitle {
  margin-top:17px;
  font-size:17px;
  line-height:1.4;
  color:#e4eef7;
}
.auth-feature {
  display:flex;
  align-items:flex-start;
  gap:14px;
  margin-top:30px;
  color:#fff;
}
.auth-feature + .auth-feature {
  margin-top:24px;
}
.feature-icon {
  font-family: Arial, "Segoe UI Symbol", sans-serif;
  width:36px;
  flex:0 0 36px;
  color:#7fc0ff;
  font-size:30px;
  line-height:30px;
  text-align:center;
}
.auth-feature b {
  display:block;
  font-size:14px;
  line-height:1.2;
}
.auth-feature small {
  display:block;
  margin-top:4px;
  font-size:11px;
  line-height:1.35;
  color:#cbd9e8;
}
.auth-building {
  position:absolute;
  z-index:1;
  left:0;
  right:0;
  bottom:0;
  height:315px;
  background-size:cover;
  background-position:center bottom;
  opacity:.95;
  -webkit-mask-image:linear-gradient(to bottom,transparent 0%,rgba(0,0,0,.72) 17%,#000 40%);
  mask-image:linear-gradient(to bottom,transparent 0%,rgba(0,0,0,.72) 17%,#000 40%);
}
.auth-form-heading {
  padding:38px 42px 14px;
}
.auth-form-heading h1 {
  margin:0 !important;
  font-size:31px !important;
  line-height:1.05 !important;
  color:#10243e !important;
  font-weight:800 !important;
  letter-spacing:-.8px;
}
.auth-form-heading p {
  margin:8px 0 0 !important;
  color:#627286 !important;
  font-size:14px !important;
}
body:has(.auth-page) [data-testid="stForm"] {
  border:0 !important;
  padding:0 42px !important;
}
body:has(.auth-page) [data-testid="stTextInput"] label,
body:has(.auth-page) [data-testid="stDateInput"] label {
  color:#17283e !important;
  font-size:12px !important;
  font-weight:750 !important;
}
body:has(.auth-page) [data-testid="stTextInput"] input,
body:has(.auth-page) [data-testid="stDateInput"] input {
  height:43px !important;
  border:1px solid #d4dce5 !important;
  border-radius:7px !important;
  background:#fbfcfd !important;
  color:#26384c !important;
  font-size:13px !important;
  padding-left:13px !important;
  box-shadow:inset 0 1px 2px rgba(15,38,61,.03) !important;
}
body:has(.auth-page) [data-testid="stTextInput"] input:focus,
body:has(.auth-page) [data-testid="stDateInput"] input:focus {
  border-color:#1876c5 !important;
  box-shadow:0 0 0 2px rgba(24,118,197,.10) !important;
}
body:has(.auth-page) [data-testid="stTextInput"] {
  margin-bottom:7px !important;
}
body:has(.auth-page) [data-testid="stCheckbox"] {
  margin-top:2px !important;
}
body:has(.auth-page) [data-testid="stCheckbox"] label p {
  font-size:12px !important;
  color:#22354a !important;
}
body:has(.auth-page) [data-testid="stFormSubmitButton"] button,
body:has(.auth-page) .stButton > button {
  height:44px !important;
  border-radius:7px !important;
  border:1px solid #0b72c7 !important;
  background:#0876c9 !important;
  color:#fff !important;
  font-size:14px !important;
  font-weight:750 !important;
  box-shadow:none !important;
}
body:has(.auth-page) [data-testid="stFormSubmitButton"] button:hover,
body:has(.auth-page) .stButton > button:hover {
  background:#096bb3 !important;
  border-color:#096bb3 !important;
}
body:has(.auth-page) .auth-forgot {
  text-align:right;
  margin:-38px 43px 24px 0;
  color:#0b67ac;
  font-size:12px;
  font-weight:700;
}
.auth-divider {
  display:flex;
  align-items:center;
  gap:12px;
  padding:0 42px;
  color:#687789;
  font-size:13px;
}
.auth-divider span {
  height:1px;
  flex:1;
  background:#d6dde5;
}
.auth-switch-card {
  margin:25px 42px 8px;
  padding:25px 18px 20px;
  background:#edf3f8;
  border:1px solid #e0e7ee;
  border-radius:10px;
  text-align:center;
  color:#1a2b41;
}
.auth-switch-card strong {
  display:block;
  font-size:16px;
}
.auth-switch-card span {
  display:block;
  margin-top:7px;
  font-size:12px;
  color:#52657a;
}
body:has(.auth-page) button[key="go_signup"] {
  margin:0 42px !important;
  width:calc(100% - 84px) !important;
  background:#f8fbfe !important;
  color:#1268ad !important;
  border-color:#1774bb !important;
}
.signup-heading {
  padding-top:20px;
}
body:has(.auth-page) .signup-heading + [data-testid="stForm"] {
  padding-bottom:0 !important;
}
body:has(.auth-page) [data-testid="stForm"] [data-testid="stTextArea"] {
  margin-bottom:0 !important;
}
.auth-bottom-login {
  text-align:center;
  margin-top:15px;
  color:#69798b;
  font-size:12px;
}
body:has(.auth-page) button[key="go_signin"] {
  height:auto !important;
  min-height:24px !important;
  width:auto !important;
  margin:0 auto !important;
  display:block !important;
  padding:0 8px !important;
  background:transparent !important;
  border:0 !important;
  color:#0b67ac !important;
  font-size:12px !important;
}
@media (max-width: 900px) {
  body:has(.auth-page) [data-testid="stHorizontalBlock"] {
    margin:10px !important;
  }
  .auth-brand-panel {
    height:520px;
  }
  .auth-feature {
    margin-top:17px;
  }
  .auth-form-heading {
    padding-top:24px;
  }
}

/* Authentication: eliminate Streamlit's default top whitespace. */
body:has(.auth-brand-panel) .block-container {
  padding-top: 0 !important;
  margin-top: 0 !important;
}
body:has(.auth-brand-panel) [data-testid="stAppViewContainer"] {
  padding-top: 0 !important;
}
body:has(.auth-brand-panel) [data-testid="stVerticalBlock"] {
  gap: 0 !important;
}
body:has(.auth-brand-panel) [data-testid="stHorizontalBlock"] {
  margin-top: 0 !important;
  padding-top: 0 !important;
  align-items: stretch !important;
}
body:has(.auth-brand-panel) [data-testid="column"] {
  margin-top: 0 !important;
  padding-top: 0 !important;
}
body:has(.auth-brand-panel) .auth-brand-panel {
  margin-top: 0 !important;
}

/* Authentication feature rows — intentionally simple HTML so they cannot
   fall back to literal source-code rendering. */
body:has(.auth-brand-panel) .auth-feature {
  display:flex !important;
  align-items:flex-start !important;
  gap:14px !important;
  margin-top:24px !important;
  color:#fff !important;
}
body:has(.auth-brand-panel) .auth-feature + .auth-feature {
  margin-top:20px !important;
}
body:has(.auth-brand-panel) .feature-icon {
  display:flex !important;
  align-items:center !important;
  justify-content:center !important;
  width:36px !important;
  min-width:36px !important;
  height:36px !important;
  color:#82c2ff !important;
  font-family:Arial,"Segoe UI Symbol",sans-serif !important;
  font-size:27px !important;
  line-height:1 !important;
}
body:has(.auth-brand-panel) .feature-copy {
  display:block !important;
}
body:has(.auth-brand-panel) .feature-copy b {
  display:block !important;
  color:#fff !important;
  font-size:14px !important;
  line-height:1.2 !important;
}
body:has(.auth-brand-panel) .feature-copy small {
  display:block !important;
  color:#cbd9e8 !important;
  font-size:11px !important;
  line-height:1.35 !important;
  margin-top:4px !important;
}


/* Authentication page: remove Streamlit's default top whitespace. */
body:has(.auth-page) .block-container {
  padding-top:0 !important;
  margin-top:0 !important;
}
body:has(.auth-page) [data-testid="stAppViewContainer"] {
  padding-top:0 !important;
}
body:has(.auth-page) [data-testid="stVerticalBlock"] {
  gap:0 !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# ------------------------- Utilities -------------------------

def now():
    return datetime.now(APP_TZ).replace(tzinfo=None)

def oid_str(value):
    return str(value) if value is not None else ""

def normalize_email(email):
    return (email or "").strip().lower()

def safe_text(value):
    return "" if value is None else str(value)

def parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None

def fmt_dt(value):
    dt = parse_dt(value)
    return dt.strftime("%b %d, %Y %I:%M %p") if dt else "—"

def hours_since(value):
    dt = parse_dt(value)
    if not dt:
        return None
    return (now() - dt).total_seconds() / 3600

def hash_password(password):
    if bcrypt:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    # Fallback so the app can start, but bcrypt is strongly recommended.
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 200_000
    ).hex()
    return f"pbkdf2${salt}${digest}"

def verify_password(password, stored):
    if not stored:
        return False
    try:
        if stored.startswith("$2"):
            return bool(bcrypt and bcrypt.checkpw(password.encode(), stored.encode()))
        if stored.startswith("pbkdf2$"):
            _, salt, digest = stored.split("$", 2)
            check = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), salt.encode(), 200_000
            ).hex()
            return hmac.compare_digest(check, digest)
    except Exception:
        return False
    return False

def priority_rank(priority):
    return {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}.get(priority, 4)

def case_bucket(case):
    status = case.get("status", "")
    if status in ("Completed", "Cancelled"):
        return "Closed"
    priority = case.get("priority", "Medium")
    due = parse_dt(case.get("due_at"))
    if priority == "Critical":
        return "Critical"
    if due and due <= now():
        return "Critical"
    if due and due <= now() + timedelta(hours=DUE_SOON_HOURS):
        return "Due Soon"
    return "On Track"

def urgency_score(case):
    bucket = case_bucket(case)
    bucket_rank = {"Critical": 0, "Due Soon": 1, "On Track": 2, "Closed": 3}.get(bucket, 3)
    return (
        bucket_rank,
        priority_rank(case.get("priority")),
        parse_dt(case.get("due_at")) or datetime.max,
        parse_dt(case.get("created_at")) or datetime.max,
    )

def is_active_case(case):
    return case.get("status") not in ("Completed", "Cancelled")

def case_row_class(case):
    bucket = case_bucket(case)
    return {"Critical": "case-red", "Due Soon": "case-yellow", "On Track": "case-green"}.get(bucket, "")

# ------------------------- MongoDB ---------------------------

@st.cache_resource(show_spinner=False)
def get_mongo_client():
    uri = None
    try:
        uri = st.secrets.get("MONGO_URI")
    except Exception:
        pass
    uri = uri or os.getenv("MONGO_URI") or os.getenv("MONGODB_URI")
    if not uri:
        raise RuntimeError(
            "MongoDB connection is not configured. Add MONGO_URI to "
            ".streamlit/secrets.toml or as an environment variable."
        )
    client = MongoClient(
        uri,
        maxPoolSize=30,
        minPoolSize=2,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        retryWrites=True,
    )
    client.admin.command("ping")
    return client

def get_db():
    return get_mongo_client()[DB_NAME]

def init_db():
    """Initialize indexes safely for an existing Team Roster Collection."""
    db = get_db()
    user_collection = db[USER_COLLECTION]

    # Legacy roster records may have missing/null/empty emails.
    # Empty strings are not useful account emails, so remove only those.
    user_collection.update_many({"email": ""}, {"$unset": {"email": ""}})
    user_collection.update_many({"employee_id": ""}, {"$unset": {"employee_id": ""}})

    # Replace an old non-partial email index. A normal unique index treats
    # multiple missing/null email values as duplicates.
    try:
        indexes = list(user_collection.list_indexes())
        old_email = next((i for i in indexes if i.get("name") == "email_1"), None)
        if old_email and not old_email.get("partialFilterExpression"):
            user_collection.drop_index("email_1")

        user_collection.create_index(
            [("email", ASCENDING)],
            name="email_1",
            unique=True,
            partialFilterExpression={"email": {"$type": "string"}},
        )
    except PyMongoError as exc:
        st.warning(f"Email index warning: {exc}")

    # Employee IDs follow the same safe pattern.
    try:
        indexes = list(user_collection.list_indexes())
        old_emp = next((i for i in indexes if i.get("name") == "employee_id_1"), None)
        if old_emp and not old_emp.get("partialFilterExpression"):
            user_collection.drop_index("employee_id_1")

        user_collection.create_index(
            [("employee_id", ASCENDING)],
            name="employee_id_1",
            unique=True,
            partialFilterExpression={"employee_id": {"$type": "string"}},
        )
    except PyMongoError as exc:
        st.warning(f"Employee ID index warning: {exc}")

    # Operational indexes.
    db["cases"].create_index([ ("status", ASCENDING), ("due_at", ASCENDING) ], name="case_status_due")
    db["cases"].create_index([ ("assigned_to", ASCENDING), ("status", ASCENDING) ], name="case_assignment_status")
    db["cases"].create_index([ ("created_at", DESCENDING) ], name="case_created")
    db["alerts"].create_index([ ("user_email", ASCENDING), ("read", ASCENDING), ("created_at", DESCENDING) ], name="alert_user_read_created")
    db["schedules"].create_index([ ("email", ASCENDING), ("schedule_date", ASCENDING) ], name="schedule_user_date")
    db["requests"].create_index([ ("status", ASCENDING), ("created_at", DESCENDING) ], name="request_status_created")
    db["audit_logs"].create_index([ ("created_at", DESCENDING) ], name="audit_created")

    # Guarantee the requested owner remains an admin.
    # The password is stored only as a secure hash.
    admin_email = normalize_email(AUTO_ADMIN_EMAIL)
    admin_hash = hash_password(AUTO_ADMIN_PASSWORD)

    admin = user_collection.find_one({"email": admin_email})
    if admin:
        user_collection.update_one(
            {"_id": admin["_id"]},
            {"$set": {
                "email": admin_email,
                "type": "roster_list",
                "password_hash": admin_hash,
                "role": "admin",
                "aux": "Admin Task",
                "active": True,
                "kicked": False,
                "updated_at": now(),
            }}
        )
    else:
        try:
            user_collection.insert_one({
                "first_name": "Admin",
                "last_name": "",
                "employee_id": "AUTO-ADMIN",
                "email": admin_email,
                "type": "roster_list",
                "password_hash": admin_hash,
                "role": "admin",
                "aux": "Admin Task",
                "active": True,
                "kicked": False,
                "created_at": now(),
                "updated_at": now(),
                "daily_case_count": 0,
                "mtd_case_count": 0,
                "pto_allocation": {
                    "PTO": 0,
                    "Sick Leave": 0,
                    "Emergency Leave": 0,
                },
            })
        except DuplicateKeyError:
            admin = user_collection.find_one({"email": admin_email})
            if admin:
                user_collection.update_one(
                    {"_id": admin["_id"]},
                    {"$set": {
                        "password_hash": admin_hash,
                        "role": "admin",
                        "aux": "Admin Task",
                        "active": True,
                        "kicked": False,
                        "updated_at": now(),
                    }}
                )
            else:
                raise


def audit(action, actor, target=None, details=None):
    get_db()["audit_logs"].insert_one({
        "created_at": now(),
        "actor": normalize_email(actor),
        "action": action,
        "target": target,
        "details": details or {},
    })

def create_alert(email, title, message, severity="info"):
    get_db()["alerts"].insert_one({
        "user_email": normalize_email(email),
        "title": title,
        "message": message,
        "severity": severity,
        "read": False,
        "created_at": now(),
    })


# ------------------------- Persistent session ----------------

def get_cookie_manager():
    # CookieManager is a Streamlit custom component. It MUST NOT be wrapped
    # in st.cache_data/st.cache_resource because Streamlit will treat its
    # widget/component calls as cached widget commands.
    #
    # The stable component key preserves the browser-side cookie state across
    # reruns without caching the component itself.
    return stx.CookieManager(key="hpe_caseflow_cookie_manager")

def _session_token(email, expires_at):
    payload = f"{normalize_email(email)}|{int(expires_at)}"
    sig = hmac.new(
        get_session_secret().encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    raw = f"{payload}|{sig}"
    return raw

def _verify_session_token(token):
    if not token:
        return None

    try:
        parts = str(token).split("|")
        if len(parts) != 3:
            return None

        email, expires_raw, signature = parts
        expires_at = int(expires_raw)

        if expires_at <= int(time.time()):
            return None

        payload = f"{normalize_email(email)}|{expires_at}"
        expected = hmac.new(
            get_session_secret().encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            return None

        return normalize_email(email)
    except Exception:
        return None

def persist_login(email):
    expires_at = int(time.time() + SESSION_COOKIE_DAYS * 86400)
    token = _session_token(email, expires_at)

    try:
        get_cookie_manager().set(
            SESSION_COOKIE_NAME,
            token,
            expires_at=expires_at,
            key="set_hpe_caseflow_session",
        )
    except Exception:
        # The application can still function for the current session if
        # cookies are unavailable in the deployment.
        pass

def restore_login():
    if "user" in st.session_state:
        return st.session_state.user

    try:
        token = get_cookie_manager().get(SESSION_COOKIE_NAME)
        email = _verify_session_token(token)
        if not email:
            return None

        user = get_user(email)
        if not user or not user.get("active", True) or user.get("kicked"):
            return None

        st.session_state.user = user
        return user
    except Exception:
        return None

def clear_login_cookie():
    try:
        get_cookie_manager().delete(
            SESSION_COOKIE_NAME,
            key="delete_hpe_caseflow_session",
        )
    except Exception:
        pass

# ------------------------- Auth -------------------------------

@st.cache_data(ttl=2, show_spinner=False)
def get_user(email):
    normalized = normalize_email(email)
    db = get_db()

    # Super-admin login is case-insensitive: Admin / admin both resolve
    # to the bootstrap account.
    if normalized == "admin":
        user = db[USER_COLLECTION].find_one({"email": "admin"})
        if user:
            return user
        user = db[USER_COLLECTION].find_one({"email": "Admin"})
        if user:
            return user

    return db[USER_COLLECTION].find_one({"email": normalized})

def sign_up(data):
    db = get_db()
    email = normalize_email(data["email"])
    if not re.match(r"^[A-Za-z0-9._%+-]+@hpe\.com$", email):
        return False, "Use a valid HPE email address ending in @hpe.com."
    if len(data["password"]) < 8:
        return False, "Password must be at least 8 characters."
    if db[USER_COLLECTION].find_one({"email": email}):
        return False, "An account with that email already exists."
    if db[USER_COLLECTION].find_one({"employee_id": data["employee_id"]}):
        return False, "That employee ID is already registered."

    doc = {
        "first_name": data["first_name"].strip(),
        "last_name": data["last_name"].strip(),
        "employee_id": data["employee_id"].strip(),
        "email": email,
        "type": "roster_list",
        "birthday": str(data["birthday"]),
        "home_address": data["home_address"].strip(),
        "contact_number": data["contact_number"].strip(),
        "password_hash": hash_password(data["password"]),
        "role": "regular",
        "aux": "Busy - Away",
        "active": True,
        "kicked": False,
        "created_at": now(),
        "updated_at": now(),
        "daily_case_count": 0,
        "mtd_case_count": 0,
        "pto_allocation": {"PTO": 0, "Sick Leave": 0, "Emergency Leave": 0},
    }
    try:
        db[USER_COLLECTION].insert_one(doc)
        audit("user_signup", email)
        return True, "Account created. You can now sign in."
    except DuplicateKeyError:
        return False, "Email or employee ID is already registered."
    except Exception as exc:
        return False, f"Could not create account: {exc}"

def authenticate(email, password):
    user = get_user(email)
    if not user or not verify_password(password, user.get("password_hash", "")):
        return None
    if not user.get("active", True):
        return None
    if user.get("kicked"):
        return None
    return user

def logout():
    clear_login_cookie()
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# ------------------------- Case assignment -------------------

def eligible_agents():
    db = get_db()
    excluded = {"Break", "Lunch", "In a Meeting", "Coaching", "Busy - Away", "Unscheduled Break", "Admin Task"}
    return list(db[USER_COLLECTION].find(
        {
            "role": "regular",
            "active": True,
            "kicked": {"$ne": True},
            "aux": {"$nin": list(excluded)},
        },
        {
            "email": 1, "first_name": 1, "last_name": 1,
            "aux": 1, "daily_case_count": 1, "mtd_case_count": 1,
        }
    ))

def active_load(email):
    return get_db()["cases"].count_documents({
        "assigned_to": normalize_email(email),
        "status": {"$nin": ["Completed", "Cancelled"]},
    })

def fair_agent():
    agents = eligible_agents()
    if not agents:
        return None

    # Fairness uses today's assigned count first, then active load,
    # then MTD count, then the oldest last-assignment timestamp.
    db = get_db()
    scored = []
    for a in agents:
        email = a["email"]
        recent = db["cases"].find_one(
            {"assigned_to": email},
            sort=[("assigned_at", DESCENDING)],
            projection={"assigned_at": 1},
        )
        last_assigned = parse_dt(recent.get("assigned_at")) if recent else datetime.min
        scored.append((
            int(a.get("daily_case_count", 0)),
            active_load(email),
            int(a.get("mtd_case_count", 0)),
            last_assigned,
            email,
            a,
        ))
    scored.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4]))
    return scored[0][5]

def assign_case(case_id, actor="system"):
    db = get_db()
    case = db["cases"].find_one({"_id": case_id})
    if not case or case.get("assigned_to"):
        return False, "Case is already assigned or does not exist."

    agent = fair_agent()
    if not agent:
        return False, "No eligible agent is currently available."

    email = agent["email"]
    ts = now()

    result = db["cases"].update_one(
        {"_id": case_id, "assigned_to": {"$in": [None, ""]}},
        {"$set": {
            "assigned_to": email,
            "assigned_at": ts,
            "status": "Assigned",
            "updated_at": ts,
            "last_updated_by": actor,
        }},
    )
    if result.modified_count:
        db[USER_COLLECTION].update_one(
            {"email": email},
            {"$inc": {"daily_case_count": 1, "mtd_case_count": 1},
             "$set": {"updated_at": ts}},
        )
        create_alert(
            email,
            "New case assigned",
            f"Case {case.get('case_number', oid_str(case_id))} was automatically assigned to you.",
            "info",
        )
        audit("case_auto_assigned", actor, oid_str(case_id), {"agent": email})
        return True, email
    return False, "Case assignment changed before it could be completed."

def auto_assign_new_cases():
    db = get_db()
    for case in db["cases"].find({
        "status": {"$in": ["New", "Assigned"]},
        "$or": [{"assigned_to": {"$exists": False}}, {"assigned_to": None}, {"assigned_to": ""}],
    }).sort("created_at", ASCENDING).limit(25):
        assign_case(case["_id"])

# ------------------------- Alerts -----------------------------

def generate_case_alerts(user_email=None):
    db = get_db()
    query = {"status": {"$nin": ["Completed", "Cancelled"]}}
    if user_email:
        query["assigned_to"] = normalize_email(user_email)

    cases = list(db["cases"].find(query).limit(300))
    existing_recent = {
        (a.get("user_email"), a.get("title"), a.get("case_id"))
        for a in db["alerts"].find({
            "created_at": {"$gte": now() - timedelta(hours=24)},
            "case_id": {"$exists": True},
        }, {"user_email": 1, "title": 1, "case_id": 1})
    }

    for c in cases:
        email = c.get("assigned_to")
        if not email:
            continue
        cid = oid_str(c["_id"])
        due = parse_dt(c.get("due_at"))
        title = None
        message = None
        severity = "info"

        if c.get("priority") == "Critical" or (due and due <= now()):
            title = "Critical case"
            message = f"{c.get('case_number', cid)} requires immediate attention."
            severity = "critical"
        elif due and due <= now() + timedelta(hours=DUE_SOON_HOURS):
            title = "Case due soon"
            message = f"{c.get('case_number', cid)} is due within {DUE_SOON_HOURS} hours."
            severity = "warning"
        elif hours_since(c.get("last_updated_at")) and hours_since(c.get("last_updated_at")) >= STALE_HOURS:
            title = "Case needs an update"
            message = f"{c.get('case_number', cid)} has not been updated for 24 hours."
            severity = "warning"

        key = (normalize_email(email), title, cid)
        if title and key not in existing_recent:
            db["alerts"].insert_one({
                "user_email": normalize_email(email),
                "title": title,
                "message": message,
                "severity": severity,
                "case_id": c["_id"],
                "read": False,
                "created_at": now(),
            })

def unread_alerts(email):
    return list(get_db()["alerts"].find(
        {"user_email": normalize_email(email), "read": False},
        sort=[("created_at", DESCENDING)],
        limit=20,
    ))

# ------------------------- Schedule / Requests ---------------

def get_schedule(email, start_date, days=1):
    end_date = start_date + timedelta(days=days)
    return list(get_db()["schedules"].find({
        "email": normalize_email(email),
        "schedule_date": {"$gte": start_date.isoformat(), "$lt": end_date.isoformat()},
    }).sort([("schedule_date", ASCENDING), ("start_time", ASCENDING)]))

def create_default_schedule(email, target_date):
    db = get_db()
    day = target_date.weekday()
    if day >= 5:
        return

    existing = db["schedules"].count_documents({
        "email": normalize_email(email),
        "schedule_date": target_date.isoformat(),
    })
    if existing:
        return

    # Default 8-hour day. Break/lunch positions are subsequently
    # recalculated by admin using queue coverage.
    blocks = [
        ("Work", "08:00", "10:00"),
        ("Break", "10:00", "10:15"),
        ("Work", "10:15", "12:15"),
        ("Lunch", "12:15", "13:15"),
        ("Work", "13:15", "15:15"),
        ("Break", "15:15", "15:30"),
        ("Work", "15:30", "17:00"),
    ]
    docs = [{
        "email": normalize_email(email),
        "schedule_date": target_date.isoformat(),
        "activity": activity,
        "start_time": start,
        "end_time": end,
        "status": "Approved",
        "created_at": now(),
        "updated_at": now(),
    } for activity, start, end in blocks]
    db["schedules"].insert_many(docs)

def auto_schedule_all_agents(target_date=None):
    target_date = target_date or date.today()
    db = get_db()
    agents = list(db[USER_COLLECTION].find({"role": "regular", "active": True}, {"email": 1}))
    for a in agents:
        create_default_schedule(a["email"], target_date)

def submit_request(user, request_type, payload):
    db = get_db()
    doc = {
        "request_type": request_type,
        "email": user["email"],
        "created_at": now(),
        "status": "Pending",
        "payload": payload,
    }

    if request_type in ("Sick Leave", "Emergency Leave"):
        doc["status"] = "Approved"
    elif request_type == "PTO":
        selected = date.fromisoformat(payload["date"])
        allocation = float(user.get("pto_allocation", {}).get("PTO", 0))
        used = db["requests"].count_documents({
            "email": user["email"],
            "request_type": "PTO",
            "status": "Approved",
            "payload.date": payload["date"],
        })
        if allocation - used <= 0:
            return False, "No allocation for the selected date."
        doc["status"] = "Approved"

    db["requests"].insert_one(doc)
    audit("request_submitted", user["email"], details={"type": request_type})
    if user["email"] != AUTO_ADMIN_EMAIL:
        create_alert(AUTO_ADMIN_EMAIL, "New request submitted", f"{user['email']} submitted {request_type}.")
    return True, f"{request_type} submitted successfully."

def approve_request(request_id, admin_email):
    db = get_db()
    req = db["requests"].find_one({"_id": request_id})
    if not req:
        return False
    db["requests"].update_one(
        {"_id": request_id},
        {"$set": {"status": "Approved", "approved_by": admin_email, "approved_at": now()}}
    )
    create_alert(req["email"], "Request approved", f"Your {req['request_type']} request was approved.")
    audit("request_approved", admin_email, oid_str(request_id))
    return True

def deny_request(request_id, admin_email):
    db = get_db()
    req = db["requests"].find_one({"_id": request_id})
    if not req:
        return False
    db["requests"].update_one(
        {"_id": request_id},
        {"$set": {"status": "Denied", "approved_by": admin_email, "approved_at": now()}}
    )
    create_alert(req["email"], "Request denied", f"Your {req['request_type']} request was denied.")
    audit("request_denied", admin_email, oid_str(request_id))
    return True

# ------------------------- Data helpers -----------------------

@st.cache_data(ttl=2, show_spinner=False)
def get_cases_for_user(email, role):
    """Cached case query using only hashable primitive arguments.

    Do not pass the full MongoDB user document into st.cache_data: MongoDB
    documents can contain ObjectId/other unhashable values and Streamlit will
    attempt to pickle/hash the argument before executing the function.
    """
    db = get_db()
    q = {"status": {"$nin": ["Completed", "Cancelled"]}}
    if role != "admin":
        q["assigned_to"] = normalize_email(email)
    return list(db["cases"].find(q).sort([("priority", ASCENDING), ("due_at", ASCENDING)]).limit(1000))

@st.cache_data(ttl=2, show_spinner=False)
def get_case(case_id):
    try:
        from bson import ObjectId
        return get_db()["cases"].find_one({"_id": ObjectId(case_id)})
    except Exception:
        return None

def save_case_update(case_id, user, fields):
    db = get_db()
    fields["updated_at"] = now()
    fields["last_updated_at"] = now()
    fields["last_updated_by"] = user["email"]
    result = db["cases"].update_one({"_id": case_id}, {"$set": fields})
    if result.modified_count:
        get_case.clear()
        get_cases_for_user.clear()
        audit("case_updated", user["email"], oid_str(case_id), fields)
        return True
    return False

def contract_breach_message(case, reason):
    return (
        f"Subject: Contract Breach – Case {case.get('case_number', '')}\n\n"
        f"Hello Vendor,\n\n"
        f"This is to formally document a contract breach related to case "
        f"{case.get('case_number', '')}. The identified violation is: {reason}\n\n"
        f"Please provide the required corrective action and an updated delivery "
        f"commitment at the earliest opportunity.\n\n"
        f"Regards,\nHPE Support"
    )

# ------------------------- Login UI ---------------------------

def login_screen():
    """Reference-matched HPE CaseFlow authentication screen.

    The two authentication states intentionally share the same branded left
    panel and switch between Sign In / Sign Up without a radio-button control.
    """
    if "auth_action" not in st.session_state:
        st.session_state.auth_action = "Sign in"

    # The auth card is formed directly by the Streamlit columns. Do not open
    # an HTML <div> in one st.markdown call and close it in another: Streamlit
    # renders each markdown block independently, which can cause nested HTML
    # to be displayed literally.
    left, right = st.columns([0.92, 1.18], gap="small")

    with left:
        # Keep the complete branded panel in ONE markdown block. This prevents
        # Streamlit from escaping the feature HTML as literal text.
        st.html(
            f"""
            <div class="auth-brand-panel">
              <div class="auth-brand-content">
                <div class="hpe-mark"><span></span></div>
                <div class="hpe-name">Hewlett Packard<br>Enterprise</div>
                <div class="hpe-rule"></div>
                <div class="caseflow-name">HPE CaseFlow</div>
                <div class="caseflow-subtitle">Team Task and Case<br>Management</div>

                <div class="auth-feature">
                  <div class="feature-icon">▤</div>
                  <div class="feature-copy"><b>Manage Cases</b><small>Track and resolve tasks<br>efficiently</small></div>
                </div>
                <div class="auth-feature">
                  <div class="feature-icon">♧</div>
                  <div class="feature-copy"><b>Team Collaboration</b><small>Work together for better<br>service delivery</small></div>
                </div>
                <div class="auth-feature">
                  <div class="feature-icon">▥</div>
                  <div class="feature-copy"><b>Real-Time Visibility</b><small>Stay informed and in control</small></div>
                </div>
                <div class="auth-feature">
                  <div class="feature-icon">◇</div>
                  <div class="feature-copy"><b>Secure Access</b><small>HPE employees only</small></div>
                </div>
              </div>
              <div class="auth-building" style="background-image:url('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAATAAAAFJCAIAAACTtOatAAABCGlDQ1BJQ0MgUHJvZmlsZQAAeJxjYGA8wQAELAYMDLl5JUVB7k4KEZFRCuwPGBiBEAwSk4sLGHADoKpv1yBqL+viUYcLcKakFicD6Q9ArFIEtBxopAiQLZIOYWuA2EkQtg2IXV5SUAJkB4DYRSFBzkB2CpCtkY7ETkJiJxcUgdT3ANk2uTmlyQh3M/Ck5oUGA2kOIJZhKGYIYnBncAL5H6IkfxEDg8VXBgbmCQixpJkMDNtbGRgkbiHEVBYwMPC3MDBsO48QQ4RJQWJRIliIBYiZ0tIYGD4tZ2DgjWRgEL7AwMAVDQsIHG5TALvNnSEfCNMZchhSgSKeDHkMyQx6QJYRgwGDIYMZAKbWPz9HbOBQAAEAAElEQVR4nLz9abhtyVUYCK4hYg9nusMbclIOypSUEpIQUmEjMMJCsoQsW2IoA8aGtqmyKdvVdhWuz+Uuu7qrP9vV7Wq+cuGqrq/dBmOEcSEQEpMLjBCDGAQIIQRKKZUaMpWZb77jGfcQEWv1j9jn3H2m++4Trg493Txnn9ixY0esFWteCy+//e8X02nKrEFQBQAUAQCA4n8AAAgQAFQ1/oR49tMFG4IsPjsvxpjKBUXs7+wNh8NXvOKVf/E7/vJ4MhORX/j5f/fZZ57Ok1SCy2zinCOiEEIdvDGG2AZFRQgqAcLLX/7yb/2Wbz05Ot0d7PzKhz7467/8i/uX9oOvfCgNk6gSMQApkCoS6Nbpzd9Idd4HJU8T51xdyatf/eq/9B3f/H3f933BAyFOJpMH7rv8vd/7t9///vf//sc++RWve+13ftdf/Lt/93sBTVn7Rx579B/+3/677//+73/xxRf/wX/zDz/wU+//2O9+NO3kZVEpUqfbpySbFlVquWNCNR1JIEQVrYMKaZZm2Xh8gEyZHTjvEUJZF4nJyXDpajamm/fH4yEbqGZFr7tHBGU5QlTDnTxJ/+bf+uu/+Zu//uEP/8bOzs7MFV7D3t7+bFpPp8Wgv0doAMB7sWnifU1ENuGimqXWTqajftZzzoGoSaxl44KvisqLJyAgCM7v7u+JD+PpKE8zFwTImsQa4qoqEDFJkrqu67IwxqgG55xlw8wKYTAY3Lp+Y2dnZ2enD0Cnp8cA9NKXPvrd3/2fft8/+x/LsrRJdnx83Ov1ptPCGGOMUSQvCkorG/QltLM9Xd112Xx90+NUzyZzwYa0+bk6n1J8iqoiIhMU4/F3ftNbjbYejYgCTVdtXYyQLKAIG9Zl22JtWwhrLQCkaUpEs8koy7Knn/7Uhz70wTd//ducyDd+07f80gf//cc/9vu9TlbW3jKFEMiazBoF8gKKoEB1VX/lV33lO97xjsloevny/q//2od/6zd+/ep99wdfEaplY4wpy5KMASUvyswa/OaFQ9zwCohFUVhricj5ChGdq44OTjudjisr56q6KiX4shiH4I4PD3d2dkRpxyTXrl174YUXHn744WeeeSZLrK/qoijImizLytqZJAuqadZh8MXk1IB821/41le88uUK/umnn/6J9/7MdDL+uq/9U0++6lVS86te8+rnvvi5D3zgJ9/+tnc++uijSZb++I//+Gee/tyg133LW77OGvPQg4/1O52sg+9973s/+Uef8WWxM+gZJgatytnrvvzLvvUvfrsEUIV/+6Pv+8Tvf/x7/sZ/XlXu/T/1gSRPmc1rXvNlr3vD637y/e8riulf/ct/+U985VdWVfWrH/rlX/v13yymY5umr//yL3/Hn3tHwsmdozvv/bfvPTg+6HU63/D2P/PWN781qH7uued/4id+oq5LImLm4OpiOnnrW7/+LW/+elF/48aN9733xw4ODq5cufId3/oXXnjhhVe96lX9fl9U/8W/+BdHR0cAACChrh599NFv+ZZv+f5//r+UZYmIb3jDG974xjf+4A/8q7AFgO4V3rYi870gOSJuHP7ck2IrATinESIDgDQfKTYgXDSYgyxz83P8SvO2dehWQzJn/5ABSERCCMYY1NDN09/76Ed/5Vd+pdvteu+/4Ru+4Z3vfOfJyUmn0/ECQMaa1DupqirLstlsVlXVO9/5zne8453D4fjS5b3f+Z3f+Y3f+I3dvUFdl3G2RCQiSZIAgKoSkaoC4eIfMrX/xYuKcNYHIMvTIN75igg6neytf+brv/mbv/Gtb/36P/O2t/yJP/EfMSOAMFGaJIh4enJ0cnSrmJy84bWvemB/cPuFZzMMWk//9Nd85X/87nd80zve+m3f+Gff9MY3uOK0Y5WkYHXg3Xf+5b/0mle/6t/+6I/86I+851VPvuIb3/3np6PTV7/qlW/6U1/9sd/73ff8638Fwf8//8l/bxl/6Af/5c/+zE/9nb/9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env48edz7/TRR89imlJKaoW5vjxbX9/tr6+v50CR9Xp92PfDMMyyleWiQqauG8CsbWrv/dnZyeMnl4f9w5dffr4+WX3nO9+5u77ZbR7M7OHh4Uc/+vPb+wdVvn/YDP1ILCfrddIxChRzd9vek4/T66dPz7748tXm9vrLz7769DcvytA/efqutCvvfTdMQBwLdEUeXz2pz89sv73dbfp9uTo9PXE4dbvVunnn2dXUyzimqqrqtqqW1euHzfWrV1fuvOicOITkiYjq5Wq9apv16erR+/El2MFSmiz4t441AHoTpQzOOedcjH0au5hkfxhTFkBnZg/3u5QmRKuYSop5it6fLJb102eP+li2+/tpHF49f/7qtQcBR0aohFAFF8yDGqorBRSgaptvfuPjyzph3h12m+X63W/94sXJD56rCxeXV//R3/6DJyfqoXhfjWMkh+M0jSm/vt999mL3k58/By1THJnhu9/59io86w8PEqldnmTA3Tg5z/NxegyP/npB/tVz76+3bv7qbwJA5Hnp2uzSetvUGYbBldGUV8vTg7HhFrku4s0QEIvmoe9rwdWqXq/WTVGmZuhLxU4KiYAKAjhEVgVT8K5CYCIHAKu2enZ1OQ1bzesP3n+/m5BdXxFnKUyKBiIZIPhZPmdiUhCACRwBghIUBGFUSbFIKuIIEE3JoKoa76vlcunYELGUDCKg0FSevb968ngcewXq+n65Oq1rx4zsMOeYC4S6fefZe4Ht7Pxif9dxaN798ON9jrobP/zom5eXlw8HJdY6EBGxw1A35DCnPDeyQ+03u51ql7Pb7O++973vrU/PV6vV9fX148cffeMb38hqcUr9p589e/bs6tHjf/2HfzSO477rZoliu1x0Q++rWsFW67aug6mURG272G43r17uAdL56TI4fnx58R/9ze/94Pvf/+r5FzlGRoypZDEEUoUsGhwpuCnq6dkqVKXYwOSUuF6cT3l7t4cpDa+vf3xa4396+f6TiyeLenF724ez9uT8apDuj374sz7+aNMfdtu7P/gb33n24UdndRunIZdxHEf2zTo0y+XaVwEcTuZ+8/w3j4iRXRYV1JqdDxVDvN9sVxeXi8VC7ICIdVUPmt++XnPSByIplFkDp2jO++X6HKl2vgH0kvPtwxZuJyI8X50zGcgkCsvT9vT0PUH/8uVX3eHm0dl5fygM0His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')"></div>
            </div>
            """,
        )

    with right:
        if st.session_state.auth_action == "Sign in":
            st.markdown(
                """
                <div class="auth-form-heading">
                  <h1>Sign In</h1>
                  <p>Access your HPE CaseFlow account</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.form("login_form", clear_on_submit=False):
                email = st.text_input(
                    "HPE Email Address",
                    placeholder="Admin or name@hpe.com",
                    key="login_email",
                )
                password = st.text_input(
                    "Password",
                    type="password",
                    placeholder="Enter your password",
                    key="login_password",
                )
                keep = st.checkbox("Keep me signed in", value=True, key="keep_signed_in")
                submitted = st.form_submit_button("Sign In", use_container_width=True)

            st.markdown(
                """
                <div class="auth-forgot">Forgot password?</div>
                <div class="auth-divider"><span></span><b>or</b><span></span></div>
                <div class="auth-switch-card">
                  <strong>Don't have an account?</strong>
                  <span>Sign up to access HPE CaseFlow.</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("Create an Account", key="go_signup", use_container_width=True):
                st.session_state.auth_action = "Sign up"
                st.rerun()

            if submitted:
                try:
                    user = authenticate(email, password)
                    if user:
                        if normalize_email(user["email"]) == AUTO_ADMIN_EMAIL:
                            user["role"] = "admin"
                            user["aux"] = "Admin Task"
                            get_db()[USER_COLLECTION].update_one(
                                {"email": AUTO_ADMIN_EMAIL},
                                {"$set": {
                                    "role": "admin",
                                    "aux": "Admin Task",
                                    "password_hash": hash_password(AUTO_ADMIN_PASSWORD),
                                    "type": "roster_list",
                                    "updated_at": now(),
                                }}
                            )
                        elif user.get("role") != "admin" and not user.get("aux"):
                            user["aux"] = "Busy - Away"
                        st.session_state.user = user
                        persist_login(user["email"])
                        st.rerun()
                    else:
                        st.error("Invalid account, password, or inactive/kicked account.")
                except Exception as exc:
                    st.error(str(exc))

        else:
            st.markdown(
                """
                <div class="auth-form-heading signup-heading">
                  <h1>Sign Up</h1>
                  <p>Create your HPE CaseFlow account</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.form("signup_form", clear_on_submit=False):
                first = st.text_input("First Name", placeholder="Enter your first name")
                last = st.text_input("Last Name", placeholder="Enter your last name")
                employee_id = st.text_input("Employee ID", placeholder="Enter your employee ID")
                email = st.text_input("HPE Email Address", placeholder="name@hpe.com")
                birthday = st.date_input(
                    "Birthday",
                    min_value=date(1940,1,1),
                    max_value=date.today(),
                )
                address = st.text_input("Home Address", placeholder="Enter your home address")
                phone = st.text_input("Contact Number", placeholder="Enter your contact number")
                password = st.text_input("Password", type="password", placeholder="Create a password")
                confirm = st.text_input("Confirm Password", type="password", placeholder="Confirm your password")
                submit = st.form_submit_button("Create Account", use_container_width=True)

            st.markdown(
                '<div class="auth-bottom-login">Already have an account?</div>',
                unsafe_allow_html=True,
            )
            if st.button("Sign In", key="go_signin", use_container_width=False):
                st.session_state.auth_action = "Sign in"
                st.rerun()

            if submit:
                if password != confirm:
                    st.error("Passwords do not match.")
                elif not all([first, last, employee_id, email, address, phone, password]):
                    st.error("Complete all required fields.")
                else:
                    try:
                        ok, msg = sign_up({
                            "first_name": first,
                            "last_name": last,
                            "employee_id": employee_id,
                            "email": email,
                            "birthday": birthday,
                            "home_address": address,
                            "contact_number": phone,
                            "password": password,
                        })
                        (st.success if ok else st.error)(msg)
                    except Exception as exc:
                        st.error(str(exc))

    st.markdown('</div>', unsafe_allow_html=True)


def render_reference_header(title, subtitle="", admin=False):
    """Compact header matching the uploaded CaseFlow reference image."""
    st.markdown(
        f"""
        <div class="page-title-bar">
          <div class="title">{title}</div>
          <div class="subtitle">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_reference_topbar(title, subtitle, user):
    """Top strip used consistently across every CaseFlow tab."""
    role_label = "Admin" if user.get("role") == "admin" else "Agent"
    st.markdown(
        f"""
        <div class="reference-topbar">
          <div>
            <h1>{title}</h1>
            <p>{subtitle}</p>
          </div>
          <div style="text-align:right;font-size:10px;opacity:.92;">
            <b>{user.get('first_name','')} {user.get('last_name','')}</b><br>
            {role_label}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ------------------------- Sidebar ----------------------------

def render_profile_menu(user):
    """Profile and AUX control in the upper-right corner."""
    name = f"{user.get('first_name','')} {user.get('last_name','')}".strip() or user["email"]

    with st.popover(f"👤 {name} ▾", use_container_width=True):
        st.markdown(f"**{name}**")
        st.caption(user["email"])
        st.caption(f"Role: {user.get('role','regular').title()}")

        aux_options = AUX_OPTIONS if user.get("role") == "admin" else [
            "Available", "Break", "Lunch", "In a Meeting", "Coaching",
            "Busy - Away", "Unscheduled Break"
        ]
        default_aux = user.get("aux") or (
            "Admin Task" if user.get("role") == "admin" else "Busy - Away"
        )
        if default_aux not in aux_options:
            default_aux = aux_options[0]

        aux = st.selectbox(
            "AUX",
            aux_options,
            index=aux_options.index(default_aux),
            key="profile_aux",
        )

        if st.button("Save AUX", key="profile_save_aux", use_container_width=True):
            get_db()[USER_COLLECTION].update_one(
                {"email": user["email"]},
                {"$set": {"aux": aux, "updated_at": now()}}
            )
            st.session_state.user["aux"] = aux
            audit("aux_changed", user["email"], details={"aux": aux})
            st.success("AUX updated.")
            st.rerun()

        st.divider()
        st.write(f"**Employee ID:** {user.get('employee_id','—')}")
        if st.button("Sign out", key="profile_signout", use_container_width=True):
            logout()


def render_sidebar(user):
    """Compact reference-style text navigation; no radio buttons."""
    if user["role"] == "admin":
        options = ["Dashboard", "Cases", "Agents", "Schedule", "Requests", "Reports", "Salesforce", "Settings"]
    else:
        options = ["Dashboard", "My Cases", "Schedule", "Requests"]

    if "nav_page" not in st.session_state or st.session_state.nav_page not in options:
        st.session_state.nav_page = "Dashboard"

    with st.sidebar:
        st.markdown("### HPE CaseFlow")
        st.caption(f"{user.get('first_name','')} {user.get('last_name','')}")
        st.caption(user["email"])
        st.divider()

        for option in options:
            active = st.session_state.nav_page == option
            if st.button(
                f"▸ {option}" if active else option,
                key=f"nav_word_{option}",
                use_container_width=True,
                type="secondary",
            ):
                if st.session_state.nav_page != option:
                    st.session_state.nav_page = option
                    st.session_state.pop("selected_case", None)
                    st.rerun()

        st.divider()
        unread = unread_alerts(user["email"])
        if unread:
            st.warning(f"🔔 {len(unread)} unread alert(s)")

    return st.session_state.nav_page


# ------------------------- Dashboard --------------------------

def metric_button(label, value, key, selected):
    cls = "metric-card"
    if selected == key:
        cls += " case-green"
    st.markdown(
        f'<div class="{cls}"><div class="metric-title">{label}</div>'
        f'<div class="metric-value">{value}</div></div>',
        unsafe_allow_html=True,
    )
    return st.button(f"View {label}", key=f"metric_{key}", use_container_width=True)

def render_alerts(user):
    alerts = unread_alerts(user["email"])
    if not alerts:
        return
    with st.expander(f"🔔 Alerts ({len(alerts)})", expanded=True):
        for a in alerts:
            st.markdown(
                f'<div class="alert-box"><b>{a.get("title")}</b><br>{a.get("message")}'
                f'<div class="small-note">{fmt_dt(a.get("created_at"))}</div></div>',
                unsafe_allow_html=True,
            )
            if st.button("Mark read", key=f"read_{a['_id']}"):
                get_db()["alerts"].update_one({"_id": a["_id"]}, {"$set": {"read": True}})
                st.rerun()

def render_case_card(case, user):
    bucket = case_bucket(case)
    css = case_row_class(case)
    due = parse_dt(case.get("due_at"))
    assigned = case.get("assigned_to") or "Unassigned"
    st.markdown(
        f"""
        <div class="case-card {css}">
          <span class="case-id">{case.get('case_number', oid_str(case['_id']))}</span>
          <span class="badge">{case.get('priority','Medium')}</span>
          <span class="badge">{case.get('status','New')}</span>
          <span class="badge">{bucket}</span>
          <br>
          <b>{case.get('title','Untitled case')}</b>
          <div class="muted">{case.get('description','')[:180]}</div>
          <div class="small-note">
            Assigned: {assigned} · Due: {fmt_dt(due)} · Last update: {fmt_dt(case.get('last_updated_at'))}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Open case", key=f"open_{case['_id']}"):
        st.session_state.selected_case = oid_str(case["_id"])
        st.rerun()

def render_case_list(cases, user, title="Active Cases"):
    st.subheader(title)
    search = st.text_input(
        "Search cases",
        placeholder="Case number, title, vendor, technician, status...",
        key=f"search_{title}",
    )
    filtered = cases
    if search:
        s = search.lower()
        filtered = [
            c for c in cases
            if s in safe_text(c.get("case_number")).lower()
            or s in safe_text(c.get("title")).lower()
            or s in safe_text(c.get("description")).lower()
            or s in safe_text(c.get("vendor_name")).lower()
            or s in safe_text(c.get("technician_name")).lower()
            or s in safe_text(c.get("status")).lower()
        ]

    filtered.sort(key=urgency_score)
    if not filtered:
        st.info("No cases match the current view.")
    else:
        for c in filtered:
            render_case_card(c, user)

def render_dashboard(user):
    db = get_db()
    render_reference_topbar(
        "TEAM OVERVIEW" if user.get("role") == "admin" else "MY CASE DASHBOARD",
        "Overall queue status, agent stats and alerts" if user.get("role") == "admin"
        else "Overview of assigned cases, quick stats and alerts",
        user,
    )
    render_alerts(user)

    cases = get_cases_for_user(user["email"], user["role"])
    active = [c for c in cases if is_active_case(c)]

    critical = [c for c in active if case_bucket(c) == "Critical"]
    due_soon = [c for c in active if case_bucket(c) == "Due Soon"]
    on_track = [c for c in active if case_bucket(c) == "On Track"]

    if user["role"] == "admin":
        all_active = list(db["cases"].find({"status": {"$nin": ["Completed", "Cancelled"]}}))
        active = all_active
        critical = [c for c in active if case_bucket(c) == "Critical"]
        due_soon = [c for c in active if case_bucket(c) == "Due Soon"]
        on_track = [c for c in active if case_bucket(c) == "On Track"]

    render_reference_header(
        "Dashboard (Admin)" if user["role"] == "admin" else "Dashboard (Agent)",
        f"{now().strftime('%A, %B %d, %Y · %I:%M %p')} · Live queue monitoring"
    )

    cols = st.columns(4)
    labels = [
        ("Active Cases", len(active), "all"),
        ("Critical", len(critical), "critical"),
        ("Due Soon", len(due_soon), "due"),
        ("On Track", len(on_track), "track"),
    ]
    for col, (label, value, key) in zip(cols, labels):
        with col:
            st.markdown(
                f'<div class="metric-card"><div class="metric-title">{label}</div>'
                f'<div class="metric-value">{value}</div>'
                f'<div class="metric-sub">Click below to filter</div></div>',
                unsafe_allow_html=True,
            )
            if st.button(f"View {label}", key=f"tile_{key}", use_container_width=True):
                st.session_state.selected_tile = key

    selected = st.session_state.get("selected_tile", "all")
    if selected == "critical":
        shown = critical
        heading = "Critical Cases"
    elif selected == "due":
        shown = due_soon
        heading = "Cases Due Soon"
    elif selected == "track":
        shown = on_track
        heading = "On-Track Cases"
    else:
        shown = active
        heading = "All Active Cases"

    if user["role"] == "admin":
        st.subheader("Queue & Agent Coverage")
        render_agent_status_strip()

    render_case_list(shown, user, heading)

def render_agent_status_strip():
    agents = list(get_db()[USER_COLLECTION].find(
        {"role": "regular", "active": True},
        {"first_name":1,"last_name":1,"email":1,"aux":1,"daily_case_count":1}
    ).sort("first_name", ASCENDING))
    if not agents:
        st.info("No regular agents are registered.")
        return

    rows = []
    for a in agents:
        rows.append({
            "Agent": f"{a.get('first_name','')} {a.get('last_name','')}",
            "AUX": a.get("aux","Busy - Away"),
            "Active": active_load(a["email"]),
            "Assigned Today": a.get("daily_case_count", 0),
            "Email": a["email"],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ------------------------- Case detail ------------------------

def render_case_detail(user):
    render_reference_header(
        "Case Details",
        "View, update and manage the selected case",
    )
    case_id = st.session_state.get("selected_case")
    case = get_case(case_id)
    if not case:
        st.warning("Case not found.")
        st.session_state.pop("selected_case", None)
        return

    if user["role"] != "admin" and case.get("assigned_to") != user["email"]:
        st.error("This case is not assigned to your profile.")
        return

    if st.button("← Back to dashboard"):
        st.session_state.pop("selected_case", None)
        st.rerun()

    st.markdown(
        f"""
        <div class="hero">
          <h1>{case.get('case_number', oid_str(case['_id']))}</h1>
          <p>{case.get('title','Untitled case')} · {case.get('priority','Medium')} · {case.get('status','New')}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Priority", case.get("priority", "Medium"))
    c2.metric("Status", case.get("status", "New"))
    c3.metric("Assigned", case.get("assigned_to") or "Unassigned")
    c4.metric("Due", fmt_dt(case.get("due_at")))

    with st.expander("Case information", expanded=True):
        st.write(case.get("description", "No description."))
        st.write(f"**Vendor:** {case.get('vendor_name','—')}")
        st.write(f"**Technician:** {case.get('technician_name','—')}")
        st.write(f"**Vendor phone:** {case.get('vendor_phone','—')}")
        st.write(f"**Last update:** {fmt_dt(case.get('last_updated_at'))}")

    if user["role"] == "admin" or case.get("assigned_to") == user["email"]:
        st.subheader("Case actions")
        status = st.selectbox("Status", CASE_STATUSES, index=CASE_STATUSES.index(case.get("status"))
                              if case.get("status") in CASE_STATUSES else 0)
        note = st.text_area("Update / work note", value=case.get("latest_note",""))

        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Save case update", use_container_width=True):
                save_case_update(case["_id"], user, {
                    "status": status,
                    "latest_note": note,
                })
                st.success("Case updated and saved.")
                st.rerun()

        with c2:
            sf = case.get("salesforce_url") or DEFAULT_SF_URL
            st.link_button("Contact Vendor / Technician", sf, use_container_width=True)

        with c3:
            phone = safe_text(case.get("vendor_phone"))
            if phone:
                st.markdown(
                    f'<a href="tel:{quote_plus(phone)}" style="text-decoration:none">'
                    f'<button style="width:100%;height:38px">📞 Call Vendor</button></a>',
                    unsafe_allow_html=True,
                )
                st.code(phone, language=None)
            else:
                st.caption("No vendor number is stored for this case.")

        st.subheader("Contract breach")
        reason = st.selectbox("Contract breached reason", [""] + list(BREACH_REASONS.keys()))
        if reason:
            generated = contract_breach_message(case, BREACH_REASONS[reason])
            edited = st.text_area("Generated message — editable before sending", generated, height=230)
            if st.button("Mark Contract Breached & Save", use_container_width=True):
                save_case_update(case["_id"], user, {
                    "status": "Contract Breached",
                    "contract_breached": True,
                    "contract_breach_reason": reason,
                    "contract_breach_message": edited,
                })
                st.success("Contract breach saved.")
                st.rerun()
            st.info("The Email button can be connected to your approved email connector later. "
                    "The generated message is already persisted with the case when saved.")

# ------------------------- Regular pages ---------------------

def render_my_schedule(user):
    render_reference_topbar("3. SCHEDULE (AGENT)", "View your schedule for the day, week or month", user)
    render_reference_header("My Schedule", "Day · Week · Month")
    view = st.radio("View", ["Day", "Week", "Month"], horizontal=True)
    days = {"Day": 1, "Week": 7, "Month": 31}[view]
    start = date.today()
    create_default_schedule(user["email"], start)
    rows = get_schedule(user["email"], start, days)

    if not rows:
        st.info("No schedule has been published.")
        return
    df = pd.DataFrame([{
        "Date": r.get("schedule_date"),
        "Activity": r.get("activity"),
        "Start": r.get("start_time"),
        "End": r.get("end_time"),
        "Status": r.get("status"),
    } for r in rows])
    st.dataframe(df, use_container_width=True, hide_index=True)

def render_requests(user):
    render_reference_topbar("4. REQUESTS (AGENT)", "Submit leave, PTO or schedule swap requests", user)
    render_reference_header("Requests", "New request · My requests")
    st.caption("Sick Leave and Emergency Leave are auto-approved. PTO is auto-approved only when allocation is available.")

    request_type = st.selectbox("Request type", REQUEST_TYPES)
    if request_type in ("Sick Leave", "Emergency Leave", "PTO"):
        selected = st.date_input("Date", value=date.today(), min_value=date.today())
        reason = st.text_area("Reason")
        if st.button("Submit request"):
            ok, msg = submit_request(user, request_type, {
                "date": selected.isoformat(),
                "reason": reason,
            })
            (st.success if ok else st.error)(msg)

    elif request_type == "Schedule Swap":
        agents = list(get_db()[USER_COLLECTION].find(
            {"role":"regular","active":True,"email":{"$ne":user["email"]}},
            {"email":1,"first_name":1,"last_name":1}
        ))
        target = st.selectbox(
            "Swap with",
            agents,
            format_func=lambda a: f"{a.get('first_name','')} {a.get('last_name','')} — {a['email']}",
        )
        swap_date = st.date_input("Swap date", value=date.today(), min_value=date.today())
        if st.button("Submit mutual swap request"):
            ok, msg = submit_request(user, request_type, {
                "date": swap_date.isoformat(),
                "with_agent": target["email"] if target else "",
                "mutual_consent": True,
            })
            (st.success if ok else st.error)(msg)

    else:
        st.info("Select a request type to continue.")

    st.subheader("My submitted requests")
    reqs = list(get_db()["requests"].find({"email": user["email"]}).sort("created_at", DESCENDING).limit(50))
    if reqs:
        st.dataframe(pd.DataFrame([{
            "Type": r["request_type"],
            "Status": r["status"],
            "Submitted": fmt_dt(r.get("created_at")),
            "Payload": str(r.get("payload", {})),
        } for r in reqs]), use_container_width=True, hide_index=True)

def render_profile(user):
    render_reference_header("Profile (Agent)", "Personal details, role and PTO information")
    st.write(f"**Name:** {user.get('first_name')} {user.get('last_name')}")
    st.write(f"**Employee ID:** {user.get('employee_id','—')}")
    st.write(f"**Email:** {user.get('email')}")
    st.write(f"**Birthday:** {user.get('birthday','—')}")
    st.write(f"**Home address:** {user.get('home_address','—')}")
    st.write(f"**Contact number:** {user.get('contact_number','—')}")
    st.write(f"**Role:** {user.get('role')}")
    st.write(f"**AUX:** {user.get('aux')}")
    st.subheader("PTO Allocation")
    st.json(user.get("pto_allocation", {}))

# ------------------------- Admin pages ------------------------

def render_admin_schedule(user):
    render_reference_header("Schedule (Admin)", "Manage and approve agent schedules")
    st.caption("Approve schedule changes/requests and publish queue coverage schedules.")

    c1, c2 = st.columns(2)
    target_date = c1.date_input("Schedule date", value=date.today())
    if c2.button("Auto-schedule all agents"):
        auto_schedule_all_agents(target_date)
        st.success("Default schedules generated. Admin can adjust activities below.")
        st.rerun()

    st.subheader("Pending requests")
    pending = list(get_db()["requests"].find({"status":"Pending"}).sort("created_at", DESCENDING).limit(100))
    for r in pending:
        with st.container(border=True):
            st.write(f"**{r['request_type']}** — {r['email']} — {fmt_dt(r['created_at'])}")
            st.json(r.get("payload", {}))
            a, d = st.columns(2)
            if a.button("Approve", key=f"approve_{r['_id']}"):
                approve_request(r["_id"], user["email"])
                st.rerun()
            if d.button("Deny", key=f"deny_{r['_id']}"):
                deny_request(r["_id"], user["email"])
                st.rerun()

    st.subheader("Add activity")
    agents = list(get_db()[USER_COLLECTION].find({"role":"regular","active":True},
                                                   {"email":1,"first_name":1,"last_name":1}))
    if agents:
        with st.form("activity_form"):
            agent = st.selectbox("Agent", agents,
                                 format_func=lambda a: f"{a.get('first_name')} {a.get('last_name')}")
            activity = st.selectbox("Activity", ["Meeting", "Coaching", "Admin Task", "Break", "Lunch", "Work"])
            start = st.time_input("Start", value=dtime(10,0))
            end = st.time_input("End", value=dtime(10,30))
            if st.form_submit_button("Add activity"):
                get_db()["schedules"].insert_one({
                    "email": agent["email"],
                    "schedule_date": target_date.isoformat(),
                    "activity": activity,
                    "start_time": start.strftime("%H:%M"),
                    "end_time": end.strftime("%H:%M"),
                    "status": "Approved",
                    "created_at": now(),
                    "updated_at": now(),
                })
                create_alert(agent["email"], "Schedule updated",
                             f"{activity} was added to your schedule for {target_date}.")
                audit("schedule_activity_added", user["email"], details={"agent":agent["email"],"activity":activity})
                st.success("Activity added.")

    st.subheader("Coverage view")
    coverage = []
    for a in agents:
        rows = get_schedule(a["email"], target_date, 1)
        for r in rows:
            coverage.append({
                "Agent": f"{a.get('first_name')} {a.get('last_name')}",
                "Activity": r["activity"],
                "Start": r["start_time"],
                "End": r["end_time"],
                "Status": r["status"],
            })
    if coverage:
        st.dataframe(pd.DataFrame(coverage), use_container_width=True, hide_index=True)

def render_admin_cases(user):
    render_reference_topbar("2. CASES (ADMIN)", "View, reassign and manage all cases", user)
    render_reference_header("All Active Cases", "View, reassign and manage the queue")
    cases = list(get_db()["cases"].find().sort("created_at", DESCENDING).limit(2000))
    render_case_list(cases, user, "Case Management")

    st.subheader("Manual assignment")
    unassigned = [c for c in cases if is_active_case(c) and not c.get("assigned_to")]
    if unassigned:
        options = st.selectbox("Unassigned case", unassigned,
                               format_func=lambda c: c.get("case_number", oid_str(c["_id"])))
        if st.button("Auto-assign selected case"):
            ok, result = assign_case(options["_id"], user["email"])
            (st.success if ok else st.error)(f"Assigned to {result}" if ok else result)

def render_agents(user):
    render_reference_topbar("3. AGENTS (ADMIN)", "View agent status, AUX and case distribution", user)
    render_reference_header("Agent Status", "AUX · Active cases · Assigned today · MTD")
    agents = list(get_db()[USER_COLLECTION].find().sort([("role", ASCENDING), ("first_name", ASCENDING)]))
    rows = []
    for a in agents:
        rows.append({
            "Name": f"{a.get('first_name','')} {a.get('last_name','')}",
            "Email": a.get("email"),
            "Role": a.get("role"),
            "AUX": a.get("aux"),
            "Active Cases": active_load(a["email"]) if a.get("role") == "regular" else 0,
            "Assigned Today": a.get("daily_case_count", 0),
            "Active": a.get("active", True),
            "Kicked": a.get("kicked", False),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.subheader("Agent actions")
    if agents:
        selected = st.selectbox("Agent", agents,
                                format_func=lambda a: f"{a.get('first_name')} {a.get('last_name')} — {a.get('email')}")
        st.write(f"Current AUX: **{selected.get('aux','Busy - Away')}**")
        c1, c2, c3 = st.columns(3)
        if c1.button("Kick / remove from auto-assignment"):
            get_db()[USER_COLLECTION].update_one(
                {"_id": selected["_id"]},
                {"$set":{"kicked":True,"aux":"Busy - Away","updated_at":now()}}
            )
            create_alert(selected["email"], "Removed from queue", "An administrator temporarily removed you from auto-assignment.", "warning")
            audit("agent_kicked", user["email"], selected["email"])
            st.success("Agent removed from auto-assignment.")
        if c2.button("Restore to queue"):
            get_db()[USER_COLLECTION].update_one(
                {"_id": selected["_id"]},
                {"$set":{"kicked":False,"aux":"Available","updated_at":now()}}
            )
            create_alert(selected["email"], "Returned to queue", "You are available for auto-assignment.")
            audit("agent_restored", user["email"], selected["email"])
            st.success("Agent restored.")
        if c3.button("View bucket"):
            st.session_state["admin_bucket_agent"] = selected["email"]
            st.rerun()

    if st.session_state.get("admin_bucket_agent"):
        email = st.session_state["admin_bucket_agent"]
        st.subheader(f"Bucket: {email}")
        bucket = list(get_db()["cases"].find({
            "assigned_to": email,
            "status":{"$nin":["Completed","Cancelled"]},
        }).sort("due_at", ASCENDING))
        render_case_list(bucket, user, f"{email} Bucket")

    st.subheader("Role management")
    st.caption("The automatic admin owner is always protected: " + AUTO_ADMIN_EMAIL)
    if normalize_email(user["email"]) == AUTO_ADMIN_EMAIL:
        target = st.selectbox("User to update", agents,
                              format_func=lambda a: f"{a.get('first_name')} {a.get('last_name')} — {a.get('email')}")
        role = st.selectbox("Role", ["regular", "admin"], index=0 if target.get("role")=="regular" else 1)
        if st.button("Save role"):
            get_db()[USER_COLLECTION].update_one(
                {"_id":target["_id"]},
                {"$set":{"role":role,"updated_at":now()}}
            )
            audit("role_changed", user["email"], target["email"], {"role":role})
            st.success("Role updated.")
            st.rerun()

def render_requests_admin(user):
    render_reference_header("Requests (Admin)", "View and process agent requests")
    reqs = list(get_db()["requests"].find().sort("created_at", DESCENDING).limit(200))
    if not reqs:
        st.info("No requests.")
        return
    st.dataframe(pd.DataFrame([{
        "Type": r["request_type"],
        "Agent": r["email"],
        "Status": r["status"],
        "Submitted": fmt_dt(r.get("created_at")),
        "Payload": str(r.get("payload", {})),
    } for r in reqs]), use_container_width=True, hide_index=True)

def render_reports(user):
    render_reference_topbar("6. REPORTS (ADMIN)", "Extract reports and view adherence", user)
    render_reference_header("Reports", "Case report · Agent adherence · Attendance · Leave")
    db = get_db()
    users = list(db[USER_COLLECTION].find({"role":"regular"}))
    rows = []
    for u in users:
        cases = list(db["cases"].find({"assigned_to":u["email"]}))
        completed = [c for c in cases if c.get("status")=="Completed"]
        active = [c for c in cases if is_active_case(c)]
        rows.append({
            "Agent": f"{u.get('first_name')} {u.get('last_name')}",
            "Email": u["email"],
            "AUX": u.get("aux"),
            "Active Cases": len(active),
            "Completed": len(completed),
            "Assigned Today": u.get("daily_case_count", 0),
            "MTD Assigned": u.get("mtd_case_count", 0),
        })
    df = pd.DataFrame(rows)
    st.subheader("Agent performance")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if not df.empty:
        csv = df.to_csv(index=False).encode()
        st.download_button("Export CSV", csv, "caseflow_agent_report.csv", "text/csv")

    # Daily/MTD attendance/adherence from schedule vs recorded AUX.
    st.subheader("Daily / MTD adherence & attendance")
    st.caption("The framework records schedule/AUX data in MongoDB. You can extend the calculation rules to match your team's official adherence policy.")
    today = date.today().isoformat()
    schedule_count = db["schedules"].count_documents({"schedule_date": today})
    st.metric("Published schedules today", schedule_count)


def render_salesforce(user):
    render_reference_header(
        "Salesforce (Admin)",
        "Access Salesforce cases and external case data — Admin only",
    )
    st.markdown(
        """
        <div class="panel-card" style="padding:14px;">
          <div style="font-size:16px;font-weight:800;color:#12314a;">
            Salesforce Integration
          </div>
          <div style="font-size:11px;color:#657485;margin-top:4px;">
            External case access is restricted to administrators.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown(
            '<div style="font-size:42px;text-align:center;padding:18px;">☁️</div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown("**Open Salesforce**")
        st.caption(DEFAULT_SF_URL)
        st.link_button(
            "Open Salesforce",
            DEFAULT_SF_URL,
            use_container_width=True,
        )
        st.info(
            "Salesforce API credentials can be added later. "
            "The external integration remains Admin-only."
        )


def render_settings(user):
    render_reference_header("Settings (Admin)", "Manage system settings, PTO allocation, roles and integrations")
    st.subheader("External Salesforce")
    st.write("Admin-only Salesforce access:")
    st.link_button("Open Salesforce", DEFAULT_SF_URL)
    st.caption("Salesforce API integration is intentionally isolated so the API/token can be added later without changing the dashboard UI.")

    st.subheader("MongoDB diagnostics")
    try:
        get_mongo_client().admin.command("ping")
        st.success(f"MongoDB connected · database: {DB_NAME} · user collection: {USER_COLLECTION}")
    except Exception as exc:
        st.error(str(exc))

    st.subheader("System configuration")
    st.write({
        "Polling interval (seconds)": POLL_SECONDS,
        "Due soon window (hours)": DUE_SOON_HOURS,
        "Stale case window (hours)": STALE_HOURS,
        "Auto admin": AUTO_ADMIN_EMAIL,
        "Timezone": str(APP_TZ),
    })

# ------------------------- Realtime loop ---------------------

@st.fragment(run_every=f"{POLL_SECONDS}s")
def realtime_tick(user):
    # Only this fragment reruns. Queue work is performed only when
    # there is something to process, avoiding needless database churn.
    try:
        db = get_db()

        has_new_cases = db["cases"].find_one(
            {
                "status": {"$in": ["New", "Assigned"]},
                "$or": [
                    {"assigned_to": {"$exists": False}},
                    {"assigned_to": None},
                    {"assigned_to": ""},
                ],
            },
            {"_id": 1},
        )

        if has_new_cases:
            auto_assign_new_cases()

        # Alert generation is limited to the current user's active cases.
        has_user_cases = db["cases"].find_one(
            {
                "assigned_to": normalize_email(user["email"]),
                "status": {"$nin": ["Completed", "Cancelled"]},
            },
            {"_id": 1},
        )
        if has_user_cases:
            generate_case_alerts(user["email"])

        active = db["cases"].count_documents({
            "status":{"$nin":["Completed","Cancelled"]}
        })
        unread = db["alerts"].count_documents({
            "user_email":user["email"], "read":False
        })
        st.caption(
            f"🟢 Live · {now().strftime('%I:%M:%S %p')} · "
            f"{active} active queue cases · {unread} unread alerts"
        )
    except Exception as exc:
        st.caption(f"Live polling paused: {exc}")


@st.cache_resource(show_spinner=False)
def initialize_application():
    """
    Run expensive MongoDB setup only once per Streamlit process.
    This prevents index inspection/creation and admin upsert on every
    widget click, tab change, or fragment rerun.
    """
    init_db()
    return True

# ------------------------- Main -------------------------------

def main():
    # MongoDB indexes/admin bootstrap happen once per process.
    try:
        initialize_application()
    except Exception as exc:
        st.error("MongoDB is not available.")
        st.code(str(exc))
        st.info(
            "Set MONGO_URI in .streamlit/secrets.toml, then restart Streamlit. "
            "The app will create the required collections and indexes automatically."
        )
        return

    # Restore authentication from the signed browser cookie after a
    # browser refresh. A logout explicitly removes the cookie.
    user = restore_login()

    if not user:
        login_screen()
        return

    # Refresh the user record so AUX/role changes from another session
    # are reflected without requiring logout.
    current = get_user(st.session_state.user["email"])
    if not current:
        logout()
    st.session_state.user = current
    user = current

    if normalize_email(user["email"]) == normalize_email(AUTO_ADMIN_EMAIL):
        if user.get("role") != "admin" or user.get("aux") != "Admin Task":
            get_db()[USER_COLLECTION].update_one(
                {"email": AUTO_ADMIN_EMAIL},
                {"$set":{
                    "role":"admin",
                    "aux":"Admin Task",
                    "password_hash":hash_password(AUTO_ADMIN_PASSWORD),
                    "updated_at":now(),
                }}
            )
            get_user.clear()
            user = get_user(AUTO_ADMIN_EMAIL)
            st.session_state.user = user

    page = render_sidebar(user)

    # Reference image places the user profile at the upper-right of the content area.
    _title_col, _profile_col = st.columns([8.5, 1.5])
    with _profile_col:
        render_profile_menu(user)

    if st.session_state.get("selected_case"):
        render_case_detail(user)
    elif page == "Dashboard":
        render_dashboard(user)
    elif page == "Schedule":
        if user["role"] == "admin":
            render_admin_schedule(user)
        else:
            render_my_schedule(user)
    elif page == "My Cases":
        render_reference_topbar("2. MY CASES (AGENT)", "View and update assigned cases", user)
        render_reference_header("My Cases", "Assigned queue · urgency · updates")
        render_case_list(get_cases_for_user(user["email"], user["role"]), user, "My Active Cases")
    elif page == "Requests":
        if user["role"] == "admin":
            render_requests_admin(user)
        else:
            render_requests(user)
    elif page == "Cases":
        render_admin_cases(user)
    elif page == "Agents":
        render_agents(user)
    elif page == "Reports":
        render_reports(user)
    elif page == "Salesforce":
        render_salesforce(user)
    elif page == "Settings":
        render_settings(user)

    # Keep this last so it never takes over the active form/page.
    realtime_tick(user)

if __name__ == "__main__":
    main()
