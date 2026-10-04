"""
TASKS MONITORING TRACKER
Single-file Streamlit application.

UI is designed to closely match the supplied dashboard reference:
- White/light gray background
- Dark navy typography
- Purple app mark
- Large search bar
- Five pastel station tiles
- Borderless active-case table
- Right-side case-detail dialog
- Bell + settings controls only (no profile)
- Real-time duration using the user's browser clock
- Fragment-only monitoring refreshes so the entire page does not refresh

MongoDB:
    client = get_mongo_client()
    db = client["TeamRoster"]
    roster collection = db["Team Roster Collection"]

Additional collections:
    Tasks_Collection
    Vendor_Collection
    Access_Collection
    Alert_Collection

Required secrets:
    MONGODB_URI = "mongodb+srv://..."
    ACCESS_CODE = "..."
    ADMIN_PIN = "..."

Optional:
    APP_NAME = "HPE Caseflow"

Install:
    pip install streamlit pymongo pandas openpyxl
"""

import hashlib
import hmac
import html
import secrets
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd
import streamlit as st
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import PyMongoError


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="HPE Caseflow",
    page_icon="⏱️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# CONFIG
# ============================================================

APP_NAME = st.secrets.get(
    "APP_NAME",
    "HPE Caseflow",
)

DB_NAME = "TeamRoster"

ROSTER_COLLECTION = "Team Roster Collection"
TASKS_COLLECTION = "Tasks_Collection"
VENDOR_COLLECTION = "Vendor_Collection"
ACCESS_COLLECTION = "Access_Collection"
ALERT_COLLECTION = "Alert_Collection"

STATIONS = {
    "CARE": {
        "sla_minutes": 15,
        "icon": "♥",
        "accent": "#e51c3a",
        "soft": "#fff0f2",
    },
    "ARCH": {
        "sla_minutes": 30,
        "icon": "▣",
        "accent": "#0879c9",
        "soft": "#eaf7ff",
    },
    "PET": {
        "sla_minutes": 45,
        "icon": "●",
        "accent": "#087b58",
        "soft": "#ecfbf4",
    },
    "SUPPLY CHAIN": {
        "sla_minutes": 30,
        "icon": "◆",
        "accent": "#5d2ac9",
        "soft": "#f2edff",
    },
    "ONSITE": {
        "sla_minutes": 120,
        "icon": "▥",
        "accent": "#c98700",
        "soft": "#fff8df",
    },
}

STATUS_ORDER = {
    "BREACHED": 0,
    "CRITICAL": 1,
    "MEDIUM": 2,
    "LOW": 3,
}


# ============================================================
# DATABASE
# ============================================================

@st.cache_resource(show_spinner=False)
def get_mongo_client():
    uri = st.secrets.get("MONGODB_URI", "")

    if not uri:
        raise RuntimeError(
            "MONGODB_URI is missing from Streamlit Secrets."
        )

    client = MongoClient(
        uri,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=8000,
        maxPoolSize=20,
        minPoolSize=1,
        retryWrites=True,
    )

    client.admin.command("ping")
    return client


@st.cache_resource(show_spinner=False)
def get_database():
    client = get_mongo_client()
    return client[DB_NAME]


def col(name):
    return get_database()[name]


@st.cache_resource(show_spinner=False)
def initialize_indexes():
    try:
        col(TASKS_COLLECTION).create_index(
            [("active", ASCENDING), ("department", ASCENDING)]
        )
        col(TASKS_COLLECTION).create_index(
            [("case_number", ASCENDING)]
        )
        col(TASKS_COLLECTION).create_index(
            [("account_name", ASCENDING)]
        )
        col(TASKS_COLLECTION).create_index(
            [("assigned_to", ASCENDING)]
        )
        col(VENDOR_COLLECTION).create_index(
            [("vendor_key", ASCENDING)]
        )
        col(ACCESS_COLLECTION).create_index(
            [("token_hash", ASCENDING)]
        )
        col(ALERT_COLLECTION).create_index(
            [("acknowledged", ASCENDING), ("created_at", DESCENDING)]
        )
    except Exception:
        pass


initialize_indexes()


# ============================================================
# TIME / DATA HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def as_utc(value):
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    try:
        return pd.to_datetime(value, utc=True).to_pydatetime()
    except Exception:
        return None


def text(value):
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def dt_display(value):
    value = as_utc(value)
    if not value:
        return "—"
    return value.astimezone().strftime("%b %d, %Y\n%I:%M %p")


def iso_z(value):
    value = as_utc(value)
    return value.isoformat() if value else ""


def sha256(value):
    return hashlib.sha256(
        text(value).encode("utf-8")
    ).hexdigest()


def is_priority(value):
    return text(value).lower() in {
        "true",
        "yes",
        "y",
        "1",
        "priority",
        "high",
        "critical",
    }


def station_name(value):
    value = text(value).upper()
    aliases = {
        "SUPPLYCHAIN": "SUPPLY CHAIN",
        "SUPPLY_CHAIN": "SUPPLY CHAIN",
        "SUPPLY": "SUPPLY CHAIN",
        "ON SITE": "ONSITE",
        "ON-SITE": "ONSITE",
    }
    return aliases.get(value, value)


# ============================================================
# ACCESS CONTROL
# ============================================================

def access_code():
    return text(st.secrets.get("ACCESS_CODE", ""))


def admin_pin():
    return text(st.secrets.get("ADMIN_PIN", ""))


def current_access_secret_hash():
    return sha256(access_code())


def issue_access_token():
    raw_token = secrets.token_urlsafe(32)

    col(ACCESS_COLLECTION).insert_one({
        "token_hash": sha256(raw_token),
        "access_code_hash": current_access_secret_hash(),
        "created_at": utc_now(),
        "active": True,
    })

    st.session_state["access_token"] = raw_token
    st.session_state["access_code_hash"] = current_access_secret_hash()


def access_is_valid():
    raw_token = st.session_state.get("access_token")

    if not raw_token:
        return False

    if st.session_state.get(
        "access_code_hash"
    ) != current_access_secret_hash():
        return False

    return col(ACCESS_COLLECTION).find_one({
        "token_hash": sha256(raw_token),
        "access_code_hash": current_access_secret_hash(),
        "active": True,
    }) is not None


def clear_token_access():
    col(ACCESS_COLLECTION).update_many(
        {},
        {
            "$set": {
                "active": False,
                "cleared_at": utc_now(),
            }
        },
    )

    st.session_state.pop("access_token", None)
    st.session_state.pop("access_code_hash", None)


def access_gate():
    if access_is_valid():
        return True

    st.markdown(
        """
        <style>
        .access-wrap {
            max-width: 560px;
            margin: 12vh auto 0 auto;
            background:#ffffff;
            border:1px solid #e8edf4;
            border-radius:26px;
            padding:42px;
            box-shadow:0 24px 70px rgba(20,38,70,.10);
        }
        .access-mark {
            width:62px;
            height:62px;
            border-radius:15px;
            background:linear-gradient(145deg,#6947ff,#3921c9);
            color:white;
            display:flex;
            align-items:center;
            justify-content:center;
            font-size:34px;
            font-weight:900;
            margin:auto;
        }
        .access-title {
            text-align:center;
            color:#102041;
            font-size:30px;
            font-weight:850;
            margin-top:18px;
        }
        .access-sub {
            text-align:center;
            color:#73819a;
            margin-bottom:25px;
        }
        </style>

        <div class="access-wrap">
            <div class="access-mark">▣</div>
            <div class="access-title">HPE Caseflow</div>
            <div class="access-sub">
                Enter the one-time access code to continue.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    code = st.text_input(
        "Access code",
        type="password",
        placeholder="Enter access code",
        label_visibility="collapsed",
    )

    if st.button(
        "Access Tracker",
        type="primary",
        use_container_width=True,
    ):
        secret = access_code()

        if not secret:
            st.error(
                "ACCESS_CODE is not configured in Streamlit Secrets."
            )
        elif hmac.compare_digest(code, secret):
            issue_access_token()
            st.rerun()
        else:
            st.error("Invalid access code.")

    return False


if not access_gate():
    st.stop()


# ============================================================
# SESSION STATE
# ============================================================

defaults = {
    "selected_station": "CARE",
    "selected_case_id": None,
    "show_case": False,
    "show_alerts": False,
    "show_settings": False,
    "admin_unlocked": False,
    "simulation_until": 0.0,
    "simulation_case_id": None,
    "search": "",
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ============================================================
# CSS — REFERENCE IMAGE
# ============================================================

st.markdown(
    """
    <style>

    #MainMenu,
    footer,
    [data-testid="stToolbar"],
    [data-testid="stDecoration"] {
        display:none !important;
    }

    header {
        background:transparent !important;
    }

    .block-container {
        max-width:1500px;
        padding-top:18px;
        padding-left:20px;
        padding-right:20px;
        padding-bottom:30px;
    }

    body {
        background:#f7f9fc;
    }

    /* HEADER */

    .brand-row {
        display:flex;
        align-items:center;
        gap:14px;
        height:64px;
    }

    .brand-mark {
        width:48px;
        height:48px;
        border-radius:11px;
        background:linear-gradient(145deg,#7051ff,#3723c6);
        color:#fff;
        display:flex;
        align-items:center;
        justify-content:center;
        font-size:27px;
        font-weight:900;
        box-shadow:0 7px 16px rgba(68,42,202,.20);
    }

    .brand-name {
        color:#102041;
        font-size:25px;
        font-weight:850;
        letter-spacing:-.7px;
    }

    .brand-divider {
        height:28px;
        width:1px;
        background:#dce2eb;
        margin-left:2px;
    }

    .top-nav {
        color:#53637f;
        font-size:14px;
    }

    .top-nav span {
        margin-right:15px;
    }

    .brand-mark { background:transparent !important; box-shadow:none !important; border-radius:0 !important; width:48px;height:48px; }
    .brand-mark svg { display:block; }

    /* SEARCH */

    div[data-testid="stTextInput"] input {
        height:50px !important;
        border:1px solid #dce3ed !important;
        border-radius:12px !important;
        background:#fff !important;
        color:#263957 !important;
        font-size:14px !important;
        box-shadow:0 5px 18px rgba(29,55,96,.06);
    }

    div[data-testid="stTextInput"] label {
        display:none;
    }

    /* TOP ICON BUTTONS */

    .top-icon button {
        height:50px !important;
        min-height:50px !important;
        border:1px solid #dce3ed !important;
        background:#fff !important;
        border-radius:12px !important;
        color:#152645 !important;
        font-size:22px !important;
    }

    /* STATIONS */

    .station-title {
        font-size:21px;
        font-weight:850;
        color:#11213e;
        margin-top:5px;
    }

    .station-sub {
        color:#63718a;
        font-size:12px;
    }

    .station-sla {
        color:#4f5e76;
        font-size:12px;
        margin-top:12px;
    }

    .station-sla strong {
        color:#132541;
    }

    .station-card {
        border-radius:13px;
        min-height:145px;
        padding:18px;
        border:1px solid transparent;
    }

    /* Click layer: the visual HTML card remains the tile.
       The Streamlit button is absolutely positioned over it so
       there is NO extra button box underneath the tile. */
    [class*="st-key-station_wrap_"] {
        position:relative !important;
        min-height:145px !important;
    }

    [class*="st-key-station_wrap_"] .stButton {
        position:absolute !important;
        inset:0 !important;
        z-index:20 !important;
        margin:0 !important;
        padding:0 !important;
        height:145px !important;
    }

    [class*="st-key-station_wrap_"] .stButton > button {
        width:100% !important;
        height:145px !important;
        min-height:145px !important;
        margin:0 !important;
        padding:0 !important;
        border:0 !important;
        border-radius:13px !important;
        background:transparent !important;
        color:transparent !important;
        box-shadow:none !important;
        opacity:0 !important;
        cursor:pointer !important;
    }

    [class*="st-key-station_wrap_"] .stButton > button:hover,
    [class*="st-key-station_wrap_"] .stButton > button:focus {
        border:0 !important;
        box-shadow:none !important;
        background:transparent !important;
        color:transparent !important;
        outline:none !important;
    }

    @keyframes stationFlash {
        from {
            box-shadow:0 0 0 0 rgba(239,51,79,.08);
        }
        to {
            box-shadow:0 0 28px 5px rgba(239,51,79,.30);
        }
    }

    /* TABLE */

    .cases-title {
        color:#11213e;
        font-size:26px;
        font-weight:850;
        letter-spacing:-.5px;
    }

    .station-pill {
        display:inline-block;
        padding:7px 14px;
        border-radius:18px;
        background:#ffecef;
        color:#e51c3a;
        font-weight:800;
        font-size:14px;
        margin-left:10px;
    }

    .case-head {
        color:#263957;
        font-size:12px;
        font-weight:700;
        padding:11px 8px;
        border-bottom:1px solid #edf0f5;
    }

    .case-row {
        min-height:60px;
        border-bottom:1px solid #edf0f5;
        color:#31435f;
        font-size:13px;
    }

    .case-row:hover { background:#fbfcfe; }
    .case-selected { background:#fff0f3 !important; }

    .case-button button {
        border:none !important;
        background:transparent !important;
        box-shadow:none !important;
        color:#315174 !important;
        padding:4px 0 !important;
        min-height:30px !important;
        text-align:left !important;
        font-size:13px !important;
    }

    .case-button button:hover {
        color:#6c4cff !important;
        text-decoration:underline;
    }

    .priority-critical {
        color:#e11d35;
        font-weight:850;
    }

    .priority-high {
        color:#ef7d1a;
        font-weight:800;
    }

    .priority-medium {
        color:#d69500;
        font-weight:750;
    }

    .priority-low {
        color:#59687f;
        font-weight:700;
    }

    .badge {
        display:inline-block;
        padding:7px 12px;
        border-radius:18px;
        font-size:11px;
        font-weight:800;
    }

    .badge-critical {
        background:#ffe8ec;
        color:#e51c3a;
    }

    .badge-medium {
        background:#fff3d4;
        color:#a46e00;
    }

    .badge-low {
        background:#eef2f7;
        color:#526078;
    }

    .badge-open {
        background:#dcf8df;
        color:#218137;
    }

    .badge-progress {
        background:#dff1ff;
        color:#0d72c6;
    }

    .badge-hold {
        background:#fff0ce;
        color:#b77900;
    }

    .badge-pending {
        background:#eef2f7;
        color:#526078;
    }

    .duration-critical {
        color:#e51c3a;
        font-weight:850;
    }

    /* REFERENCE-IMAGE STATION CARDS */
    .station-card-visual {
        position:relative; height:145px; border-radius:13px;
        padding:18px; box-sizing:border-box; overflow:hidden;
        border:1px solid transparent;
    }
    .station-card-visual.care { background:linear-gradient(135deg,#fff4f6,#ffe8ec); border-color:#f24a61; }
    .station-card-visual.arch { background:linear-gradient(135deg,#eaf8ff,#d9f1fc); }
    .station-card-visual.pet { background:linear-gradient(135deg,#ecfff9,#dcf7ee); }
    .station-card-visual.supply { background:linear-gradient(135deg,#f7f0ff,#eee5ff); }
    .station-card-visual.onsite { background:linear-gradient(135deg,#fff9e8,#fff3cf); }
    .station-card-visual.critical { animation:stationFlash .85s infinite alternate; }
    .station-card-visual { cursor:pointer; transition:transform .12s ease, box-shadow .12s ease; }
    .station-card-visual:hover { transform:translateY(-1px); box-shadow:0 7px 18px rgba(29,55,96,.08); }
    .station-icon-circle { width:68px;height:68px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:31px;position:absolute;left:22px;top:18px; }
    .care .station-icon-circle { background:#ffd9df;color:#df1737; }
    .arch .station-icon-circle { background:#bfeaff;color:#0877bf; }
    .pet .station-icon-circle { background:#bdeedc;color:#0a8a5a; }
    .supply .station-icon-circle { background:#ddc9ff;color:#5a2dc9; }
    .onsite .station-icon-circle { background:#ffe0a2;color:#c78300; }
    .station-copy { margin-left:90px; }
    .station-card-title { font-size:20px;font-weight:850;color:#102041;line-height:1.1;padding-top:12px; }
    .station-count-line { margin-top:7px;display:flex;align-items:baseline;gap:8px; }
    .station-count { font-size:40px;font-weight:850;line-height:1;color:#102041; }
    .care .station-count { color:#e11d35; }.arch .station-count { color:#0877bf; }.pet .station-count { color:#0a8a5a; }.supply .station-count { color:#5a2dc9; }.onsite .station-count { color:#c78300; }
    .station-active { font-size:12px;color:#50617c; }
    .station-arrow { position:absolute;right:18px;top:37px;font-size:25px;color:#273b5e; }
    .station-sla-ref { position:absolute;left:18px;bottom:15px;font-size:12px;color:#52627c; }
    .station-sla-ref strong { color:#152645;font-size:13px; }
    .station-warning { position:absolute;left:18px;bottom:17px;color:#df1737;font-weight:800;font-size:12px; }
    .station-warning + .station-sla-ref { bottom:0; }
    /* Invisible click target layered over each visual station card.
       The visual card itself remains pure HTML/CSS, so Streamlit does not
       replace it with a text button. */
    [class*="st-key-station_wrap_"] {
        position:relative !important;
        min-height:145px !important;
    }
    [class*="st-key-station_wrap_"] .stButton,
    [class*="st-key-station_wrap_"] [data-testid="stButton"] {
        position:absolute !important;
        inset:0 !important;
        height:145px !important;
        min-height:145px !important;
        z-index:20 !important;
        margin:0 !important;
        padding:0 !important;
    }
    [class*="st-key-station_wrap_"] .stButton > button,
    [class*="st-key-station_wrap_"] [data-testid="stButton"] button {
        width:100% !important;
        height:145px !important;
        min-height:145px !important;
        margin:0 !important;
        padding:0 !important;
        opacity:0 !important;
        border:0 !important;
        background:transparent !important;
        box-shadow:none !important;
        color:transparent !important;
        cursor:pointer !important;
    }
    [class*="st-key-station_wrap_"] .stButton > button:hover,
    [class*="st-key-station_wrap_"] .stButton > button:focus,
    [class*="st-key-station_wrap_"] .stButton > button:active,
    [class*="st-key-station_wrap_"] [data-testid="stButton"] button:hover,
    [class*="st-key-station_wrap_"] [data-testid="stButton"] button:focus,
    [class*="st-key-station_wrap_"] [data-testid="stButton"] button:active {
        border:0 !important;
        background:transparent !important;
        box-shadow:none !important;
    }

    /* REFERENCE TABLE PANEL */
    .cases-panel { background:#fff;border-radius:18px;padding:16px 12px 18px;box-shadow:0 3px 18px rgba(29,55,96,.05); }

    /* RIGHT-SIDE CASE DRAWER, matching the uploaded reference */
    div[data-testid="stDialog"] > div { position:fixed !important;top:278px !important;right:14px !important;left:auto !important;transform:none !important;width:min(494px,calc(100vw - 28px)) !important;max-width:min(494px,calc(100vw - 28px)) !important;height:calc(100vh - 294px) !important;max-height:calc(100vh - 294px) !important;margin:0 !important;border-radius:18px !important;box-shadow:0 12px 36px rgba(25,42,76,.16) !important;overflow:hidden !important; }
    div[data-testid="stDialog"] [data-testid="stDialogContent"] { padding-top:0 !important; }
    div[data-testid="stDialog"] header { border-bottom:1px solid #edf0f5 !important; }
    div[data-testid="stDialog"] > div > div { overflow-y:auto !important; }

    /* DIALOG */

    div[data-testid="stDialog"] > div {
        border-radius:18px !important;
    }

    /* ALERT */

    .alert-card {
        border:2px solid #ef334f;
        background:#fff5f7;
        border-radius:18px;
        padding:22px;
        animation:alertPulse 1s infinite alternate;
    }

    @keyframes alertPulse {
        from {
            box-shadow:0 0 0 rgba(239,51,79,0);
        }
        to {
            box-shadow:0 0 30px rgba(239,51,79,.28);
        }
    }

    .alert-title {
        color:#c91935;
        font-size:21px;
        font-weight:900;
    }

    .alert-message {
        color:#5d2730;
        margin-top:7px;
    }

    /* RESPONSIVE */

    @media(max-width:900px) {
        .brand-name {
            font-size:19px;
        }

        .top-nav {
            display:none;
        }
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# TASK ENGINE
# ============================================================

def task_projection():
    return {
        "_id": 1,
        "case_number": 1,
        "subject": 1,
        "priority": 1,
        "account_priority": 1,
        "assigned_to": 1,
        "due_date": 1,
        "created_at": 1,
        "station_started_at": 1,
        "department": 1,
        "status": 1,
        "last_update": 1,
        "account_name": 1,
        "vendor": 1,
        "issue": 1,
        "description": 1,
        "notes": 1,
        "history": 1,
        "active": 1,
        "is_mock": 1,
    }


def fetch_tasks(
    search="",
    station=None,
    limit=300,
):
    query = {"active": True}

    if station:
        query["department"] = station

    if search:
        rx = {
            "$regex": search,
            "$options": "i",
        }

        query["$or"] = [
            {"case_number": rx},
            {"subject": rx},
            {"assigned_to": rx},
            {"account_name": rx},
            {"issue": rx},
        ]

    try:
        return list(
            col(TASKS_COLLECTION)
            .find(query, task_projection())
            .sort([
                ("station_started_at", ASCENDING),
            ])
            .limit(limit)
        )
    except PyMongoError:
        return []


def calculate_state(task, now=None):
    """
    SLA is based on station_started_at.

    Priority accounts are automatically critical.
    Normal cases become critical at 20% remaining.
    Medium begins at 50% remaining.
    """

    now = now or utc_now()

    station = station_name(
        task.get("department")
    )

    config = STATIONS.get(
        station,
        STATIONS["CARE"],
    )

    sla = config["sla_minutes"] * 60

    started = as_utc(
        task.get("station_started_at")
        or task.get("created_at")
    )

    if not started:
        elapsed = 0
    else:
        elapsed = max(
            0,
            (now - started).total_seconds(),
        )

    remaining = sla - elapsed
    progress = min(
        100,
        max(0, elapsed / sla * 100),
    )

    priority_account = is_priority(
        task.get("account_priority")
    )

    if priority_account:
        status = "CRITICAL"
    elif remaining <= 0:
        status = "BREACHED"
    elif remaining <= sla * 0.20:
        status = "CRITICAL"
    elif remaining <= sla * 0.50:
        status = "MEDIUM"
    else:
        status = "LOW"

    return {
        "status": status,
        "elapsed": elapsed,
        "remaining": remaining,
        "progress": progress,
        "priority_account": priority_account,
        "critical": status in {"CRITICAL", "BREACHED"},
        "breached": status == "BREACHED",
    }


def duration_string(seconds):
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60

    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"

    return f"{m:02d}:{s:02d}"


# ============================================================
# MOCK DATA
# ============================================================

MOCK_SUBJECTS = {
    "CARE": [
        "Guest room AC not working",
        "Water leak in restroom",
        "Housekeeping request – extra towels",
        "Door lock not functioning",
        "TV no signal",
    ],
    "ARCH": [
        "Archive retrieval request",
        "Document indexing issue",
        "Historical record access",
        "Archive metadata correction",
        "Retention request",
    ],
    "PET": [
        "Pet registration inquiry",
        "Pet policy clarification",
        "Pet service request",
        "Animal facility issue",
        "Pet account update",
    ],
    "SUPPLY CHAIN": [
        "Missing shipment",
        "Purchase order mismatch",
        "Supplier delivery delay",
        "Inventory discrepancy",
        "Replacement request",
    ],
    "ONSITE": [
        "Onsite technician request",
        "Hardware replacement",
        "Network equipment issue",
        "Site access request",
        "Installation support",
    ],
}

MOCK_NAMES = [
    "John Dela Cruz",
    "Maria Santos",
    "Anna Reyes",
    "Carlo Banaag",
    "Liza Tan",
]

MOCK_ACCOUNTS = [
    "Marriott Hotel",
    "Hilton Group",
    "Accenture",
    "Microsoft",
    "Acme Corporation",
]

# Increment this when the structure/timing of demonstration cases changes.
MOCK_DATA_VERSION = 2


def seed_mock_cases(force=False):
    existing = col(TASKS_COLLECTION).count_documents(
        {"is_mock": True}
    )

    # One-time migration for mock data created by an earlier version.
    # This resets demonstration durations to 00:00:00 without doing so
    # again on every normal Streamlit rerun.
    if existing and not force:
        needs_reset = col(TASKS_COLLECTION).count_documents({
            "is_mock": True,
            "mock_data_version": {"$ne": MOCK_DATA_VERSION},
            "case_number": {"$not": {"$regex": "^SIM-"}},
        })

        if needs_reset:
            reset_now = utc_now()
            reset_docs = col(TASKS_COLLECTION).find({
                "is_mock": True,
                "mock_data_version": {"$ne": MOCK_DATA_VERSION},
                "case_number": {"$not": {"$regex": "^SIM-"}},
            })

            for old_task in reset_docs:
                department = station_name(
                    old_task.get("department")
                )
                sla_minutes = STATIONS.get(
                    department,
                    STATIONS["CARE"],
                )["sla_minutes"]

                col(TASKS_COLLECTION).update_one(
                    {"_id": old_task["_id"]},
                    {"$set": {
                        "created_at": reset_now,
                        "station_started_at": reset_now,
                        "due_date": reset_now + timedelta(
                            minutes=sla_minutes
                        ),
                        "last_update": reset_now,
                        "mock_data_version": MOCK_DATA_VERSION,
                    }},
                )

        return existing

    if force:
        col(TASKS_COLLECTION).delete_many(
            {"is_mock": True}
        )

    now = utc_now()
    docs = []

    case_index = 1

    for station, config in STATIONS.items():

        subjects = MOCK_SUBJECTS[station]
        target_count = {
            "CARE": 12,
            "ARCH": 8,
            "PET": 6,
            "SUPPLY CHAIN": 5,
            "ONSITE": 4,
        }[station]

        for i in range(target_count):

            subject = subjects[i % len(subjects)]
            account = MOCK_ACCOUNTS[i % len(MOCK_ACCOUNTS)]

            # Mock cases intentionally start at zero duration.
            # The browser timer then increments from 00:00:00.
            # Priority-account behavior is still preserved for alert/status testing.
            priority_account = (
                i == 0
            )

            started = now

            due = (
                started +
                timedelta(
                    minutes=config["sla_minutes"]
                )
            )

            docs.append({
                "case_number": (
                    f"{station[:3].upper()}"
                    f"-2026-{case_index:04d}"
                ),
                "subject": subject,
                "priority": (
                    "Critical"
                    if priority_account
                    else "Medium"
                    if i == 1
                    else "Low"
                ),
                "account_priority": (
                    "Yes"
                    if priority_account
                    else "No"
                ),
                "assigned_to": MOCK_NAMES[
                    i % len(MOCK_NAMES)
                ],
                "department": station,
                "account_name": account,
                "vendor": (
                    "CoolTech Solutions"
                    if i % 2 == 0
                    else "HPE Partner Services"
                ),
                "issue": subject,
                "description": (
                    f"Mock task for {station}. "
                    "This record was created for dashboard demonstration."
                ),
                "status": (
                    "In Progress"
                    if i % 2 == 0
                    else "Open"
                ),
                "created_at": started,
                "station_started_at": started,
                "due_date": due,
                "last_update": now,
                "notes": "Mock demonstration case.",
                "active": True,
                "is_mock": True,
                "mock_data_version": MOCK_DATA_VERSION,
                "history": [
                    {
                        "action": (
                            f"Case entered {station}"
                        ),
                        "timestamp": started,
                    }
                ],
            })

            case_index += 1

    if docs:
        col(TASKS_COLLECTION).insert_many(
            docs
        )

    return len(docs)


# ============================================================
# ALERT ENGINE
# ============================================================

def create_alert(
    task,
    alert_type,
    message,
):
    task_id = str(task["_id"])

    exists = col(
        ALERT_COLLECTION
    ).find_one({
        "task_id": task_id,
        "alert_type": alert_type,
        "acknowledged": False,
    })

    if exists:
        return

    col(ALERT_COLLECTION).insert_one({
        "task_id": task_id,
        "case_number": task.get("case_number"),
        "station": station_name(
            task.get("department")
        ),
        "account_name": task.get(
            "account_name"
        ),
        "alert_type": alert_type,
        "message": message,
        "created_at": utc_now(),
        "acknowledged": False,
    })


def active_alerts():
    try:
        return list(
            col(ALERT_COLLECTION)
            .find({
                "acknowledged": False
            })
            .sort(
                "created_at",
                DESCENDING,
            )
            .limit(50)
        )
    except Exception:
        return []


def acknowledge_alert(alert_id):
    try:
        from bson import ObjectId

        col(ALERT_COLLECTION).update_one(
            {"_id": ObjectId(alert_id)},
            {
                "$set": {
                    "acknowledged": True,
                    "acknowledged_at": utc_now(),
                }
            },
        )
    except Exception:
        pass


def acknowledge_station_alerts(station):
    col(ALERT_COLLECTION).update_many(
        {
            "station": station,
            "acknowledged": False,
        },
        {
            "$set": {
                "acknowledged": True,
                "acknowledged_at": utc_now(),
            }
        },
    )


def scan_alerts(tasks):
    now = utc_now()

    for task in tasks:
        state = calculate_state(
            task,
            now,
        )

        if not state["critical"]:
            continue

        if state["priority_account"]:

            create_alert(
                task,
                "PRIORITY_ACCOUNT",
                (
                    f"High-priority account detected: "
                    f"{text(task.get('account_name'))} "
                    f"— Case {text(task.get('case_number'))}"
                ),
            )

        elif state["breached"]:

            create_alert(
                task,
                "BREACHED",
                (
                    f"Case {text(task.get('case_number'))} "
                    f"has exceeded the "
                    f"{station_name(task.get('department'))} "
                    "timeframe."
                ),
            )

        else:

            create_alert(
                task,
                "NEARING_DUE",
                (
                    f"Case {text(task.get('case_number'))} "
                    f"is nearing its due time."
                ),
            )


# ============================================================
# VENDOR SYNC
# ============================================================

def sync_vendor_excel(uploaded_file):
    try:
        df = pd.read_excel(
            uploaded_file
        )

        if df.empty:
            return False, "The Excel file is empty."

        df.columns = [
            text(c).lower().strip()
            .replace(" ", "_")
            for c in df.columns
        ]

        aliases = {
            "vendor_name": "vendor",
            "vendorname": "vendor",
            "account": "account_name",
            "accountname": "account_name",
            "vendorid": "vendor_id",
            "vendor_id": "vendor_id",
            "contact": "contact_name",
            "contactperson": "contact_name",
            "contact_number": "phone",
            "contactnumber": "phone",
        }

        df = df.rename(
            columns=aliases
        )

        docs = []

        for _, row in df.iterrows():

            item = {}

            for c in df.columns:

                value = row[c]

                if pd.isna(value):
                    value = ""

                if isinstance(
                    value,
                    pd.Timestamp
                ):
                    value = value.isoformat()

                item[c] = text(value)

            key = (
                item.get("vendor_id")
                or item.get("vendor")
                or item.get("account_name")
            )

            if not key:
                continue

            item["vendor_key"] = (
                text(key).lower()
            )

            item["synced_at"] = utc_now()

            docs.append(item)

        collection = col(
            VENDOR_COLLECTION
        )

        collection.delete_many({})

        if docs:
            collection.insert_many(
                docs
            )

        return True, (
            f"{len(docs)} vendor records synchronized."
        )

    except Exception as exc:
        return False, str(exc)


def find_vendor(task):
    keys = [
        text(task.get("vendor")).lower(),
        text(task.get("account_name")).lower(),
    ]

    keys = [
        k for k in keys if k
    ]

    if not keys:
        return None

    try:
        return col(
            VENDOR_COLLECTION
        ).find_one({
            "vendor_key": {
                "$in": keys
            }
        })
    except Exception:
        return None


# ============================================================
# CASE TRANSFER
# ============================================================

def transfer_case(task, destination):
    now = utc_now()

    history = task.get(
        "history",
        []
    )

    history.append({
        "action": (
            f"Transferred from "
            f"{station_name(task.get('department'))} "
            f"to {destination}"
        ),
        "timestamp": now,
    })

    try:
        from bson import ObjectId

        col(TASKS_COLLECTION).update_one(
            {"_id": ObjectId(str(task["_id"]))},
            {
                "$set": {
                    "department": destination,
                    "station_started_at": now,
                    "due_date": (
                        now +
                        timedelta(
                            minutes=STATIONS[
                                destination
                            ]["sla_minutes"]
                        )
                    ),
                    "last_update": now,
                    "status": "Open",
                    "history": history[-50:],
                }
            },
        )

        return True

    except Exception:
        return False


# ============================================================
# HEADER
# ============================================================

header_cols = st.columns(
    [4.3, 5.4, 0.6, 0.6]
)

with header_cols[0]:

    st.markdown(
        """
        <div class="brand-row">
            <div class="brand-mark" aria-hidden="true">
                <svg viewBox="0 0 48 48" width="48" height="48">
                    <path d="M24 4 42 14 24 24 6 14 24 4Z" fill="#8068ff"/>
                    <path d="M6 14v9l18 10 18-10v-9L24 24 6 14Z" fill="#5d42e8"/>
                    <path d="M6 25v9l18 10 18-10v-9L24 35 6 25Z" fill="#4a30cf"/>
                </svg>
            </div>
            <div class="brand-name">HPE Caseflow</div>
            <div class="brand-divider"></div>
            <div class="top-nav">
                <span>Track</span><span>•</span><span>Manage</span><span>•</span><span>Resolve</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with header_cols[1]:

    search = st.text_input(
        "Search",
        value=st.session_state["search"],
        placeholder=(
            "Search case number, subject, name, or issue..."
        ),
        key="header_search",
        label_visibility="collapsed",
    )

    st.session_state["search"] = search

with header_cols[2]:

    alert_count = len(
        active_alerts()
    )

    if st.button(
        f"🔔 {alert_count}" if alert_count else "🔔",
        key="open_alerts",
        use_container_width=True,
    ):
        st.session_state[
            "show_alerts"
        ] = True

with header_cols[3]:

    if st.button(
        "⚙",
        key="open_settings",
        use_container_width=True,
    ):
        st.session_state[
            "show_settings"
        ] = True


# ============================================================
# SETTINGS DIALOG
# ============================================================

if st.session_state["show_settings"]:

    @st.dialog(
        "Settings",
        width="large",
    )
    def show_settings():

        if not st.session_state[
            "admin_unlocked"
        ]:

            st.markdown(
                "### Administrator Access"
            )

            pin = st.text_input(
                "Admin PIN",
                type="password",
                placeholder="Enter admin PIN",
            )

            if st.button(
                "Unlock Settings",
                type="primary",
                use_container_width=True,
            ):

                if hmac.compare_digest(
                    pin,
                    admin_pin(),
                ):

                    st.session_state[
                        "admin_unlocked"
                    ] = True

                    st.rerun()

                else:
                    st.error(
                        "Invalid admin PIN."
                    )

            if st.button(
                "Close",
                use_container_width=True,
            ):
                st.session_state[
                    "show_settings"
                ] = False
                st.rerun()

        else:

            tabs = st.tabs([
                "External Sync",
                "Alerts",
                "Access Control",
                "Simulation",
            ])

            # -----------------------------------------------
            # EXTERNAL SYNC
            # -----------------------------------------------

            with tabs[0]:

                st.markdown(
                    "### Vendor Information"
                )

                st.caption(
                    "Upload an Excel file to synchronize vendor information used by case details."
                )

                file = st.file_uploader(
                    "Vendor Excel",
                    type=["xlsx", "xls"],
                )

                if file:

                    if st.button(
                        "Synchronize Vendor Data",
                        type="primary",
                        use_container_width=True,
                    ):

                        with st.spinner(
                            "Synchronizing..."
                        ):

                            ok, msg = (
                                sync_vendor_excel(
                                    file
                                )
                            )

                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)

            # -----------------------------------------------
            # ALERTS
            # -----------------------------------------------

            with tabs[1]:

                st.markdown(
                    "### Alert Management"
                )

                alerts = active_alerts()

                st.write(
                    f"Active alerts: **{len(alerts)}**"
                )

                if st.button(
                    "Acknowledge All Alerts",
                    use_container_width=True,
                ):

                    col(
                        ALERT_COLLECTION
                    ).update_many(
                        {"acknowledged": False},
                        {
                            "$set": {
                                "acknowledged": True,
                                "acknowledged_at": utc_now(),
                            }
                        },
                    )

                    st.success(
                        "All alerts acknowledged."
                    )

            # -----------------------------------------------
            # ACCESS CONTROL
            # -----------------------------------------------

            with tabs[2]:

                st.markdown(
                    "### One-Time Access"
                )

                st.info(
                    "Changing ACCESS_CODE in Streamlit Secrets invalidates existing sessions."
                )

                if st.button(
                    "Clear Token Access",
                    type="secondary",
                    use_container_width=True,
                ):

                    clear_token_access()

                    st.success(
                        "All access tokens cleared. "
                        "Users must enter the access code again."
                    )

            # -----------------------------------------------
            # SIMULATION
            # -----------------------------------------------

            with tabs[3]:

                st.markdown(
                    "### Alert Simulation"
                )

                st.caption(
                    "Creates a temporary CARE case with approximately 5 seconds remaining. "
                    "Use this to demonstrate flashing, critical status and the central alert."
                )

                if st.button(
                    "▶ Simulate Critical Alert",
                    type="primary",
                    use_container_width=True,
                ):

                    now = utc_now()

                    demo = {
                        "case_number": (
                            "SIM-CARE-001"
                        ),
                        "subject": (
                            "Simulation – Critical Case Alert"
                        ),
                        "priority": "Low",
                        "account_priority": "No",
                        "assigned_to": "Simulation User",
                        "department": "CARE",
                        "account_name": "Simulation Account",
                        "vendor": "Simulation Vendor",
                        "issue": (
                            "Demonstration of the critical alert."
                        ),
                        "description": (
                            "Temporary simulation case."
                        ),
                        "status": "In Progress",
                        "created_at": now,
                        "station_started_at": (
                            now -
                            timedelta(
                                minutes=14,
                                seconds=55,
                            )
                        ),
                        "due_date": (
                            now +
                            timedelta(seconds=5)
                        ),
                        "last_update": now,
                        "notes": "Temporary simulation.",
                        "active": True,
                        "is_mock": True,
                    }

                    result = col(
                        TASKS_COLLECTION
                    ).insert_one(demo)

                    st.session_state[
                        "simulation_case_id"
                    ] = str(
                        result.inserted_id
                    )

                    st.session_state[
                        "simulation_until"
                    ] = time.time() + 35

                    st.success(
                        "Critical alert simulation started."
                    )

            if st.button(
                "Close Settings",
                use_container_width=True,
            ):

                st.session_state[
                    "show_settings"
                ] = False

                st.rerun()

    show_settings()


# ============================================================
# ALERT CENTER DIALOG
# ============================================================

if st.session_state["show_alerts"]:

    @st.dialog(
        "Alert Center",
        width="large",
    )
    def show_alert_center():

        alerts = active_alerts()

        if not alerts:
            st.success(
                "No active alerts."
            )
        else:

            for alert in alerts:

                with st.container(
                    border=True
                ):

                    st.markdown(
                        f"""
                        <div class="alert-card">
                            <div class="alert-title">
                                🚨 {html.escape(
                                    text(alert.get("alert_type"))
                                    .replace("_", " ")
                                )}
                            </div>
                            <div class="alert-message">
                                {html.escape(
                                    text(alert.get("message"))
                                )}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    if st.button(
                        "Acknowledge",
                        key=f"ack_{alert['_id']}",
                        use_container_width=True,
                    ):

                        acknowledge_alert(
                            str(alert["_id"])
                        )

                        st.rerun()

        if st.button(
            "Close",
            use_container_width=True,
        ):

            st.session_state[
                "show_alerts"
            ] = False

            st.rerun()

    show_alert_center()


@st.dialog(
    "Case Details",
    width="large",
)
def case_details(task_id):

    try:
        from bson import ObjectId

        task = col(
            TASKS_COLLECTION
        ).find_one({
            "_id": ObjectId(task_id)
        })

    except Exception:
        task = None

    if not task:

        st.error(
            "Case not found."
        )

        if st.button(
            "Close",
            use_container_width=True,
        ):

            st.session_state[
                "show_case"
            ] = False

            st.rerun()

        return

    state = calculate_state(
        task
    )

    status = text(
        task.get(
            "status",
            "Open"
        )
    )

    st.markdown(
        f"""
        <div style="
            display:flex;
            justify-content:space-between;
            align-items:center;
        ">
            <div style="
                font-size:25px;
                font-weight:850;
                color:#102041;
            ">
                Case Details
                <span class="badge badge-critical"
                      style="margin-left:12px;">
                    {html.escape(state["status"])}
                </span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        "---"
    )

    c1, c2 = st.columns(
        [7, 2]
    )

    with c1:

        st.markdown(
            f"### {text(task.get('case_number'))}"
        )

        st.markdown(
            f"**{text(task.get('subject'))}**"
        )

        st.write(
            text(
                task.get(
                    "description"
                )
            )
            or
            text(
                task.get(
                    "issue"
                )
            )
            or "No description available."
        )

    with c2:

        if st.button(
            "✕ Close",
            use_container_width=True,
        ):

            st.session_state[
                "show_case"
            ] = False

            st.session_state[
                "selected_case_id"
            ] = None

            st.rerun()

    st.markdown(
        "---"
    )

    a, b = st.columns(2)

    with a:

        st.markdown("**Priority**")

        if state["priority_account"]:
            st.markdown(
                '<span class="badge badge-critical">'
                '⚠ Critical'
                '</span>',
                unsafe_allow_html=True,
            )
        else:
            st.write(
                text(
                    task.get(
                        "priority",
                        "Low"
                    )
                )
            )

        st.markdown("**Current Department**")
        st.write(
            station_name(
                task.get(
                    "department"
                )
            )
        )

        st.markdown("**Assigned To**")
        st.write(
            text(
                task.get(
                    "assigned_to",
                    "Unassigned"
                )
            )
        )

        st.markdown("**Due Date**")
        st.write(
            dt_display(
                task.get(
                    "due_date"
                )
            )
        )

        st.markdown("**Duration**")
        st.markdown(
            f"### {duration_string(state['elapsed'])}"
        )

    with b:

        st.markdown("**Account Name**")
        st.write(
            text(
                task.get(
                    "account_name"
                )
            ) or "—"
        )

        st.markdown("**Case Status**")
        st.write(status)

        st.markdown("**Created**")
        st.write(
            dt_display(
                task.get(
                    "created_at"
                )
            )
        )

        st.markdown("**Last Update**")
        st.write(
            dt_display(
                task.get(
                    "last_update"
                )
            )
        )

    # ----------------------------------------------------
    # VENDOR
    # ----------------------------------------------------

    st.markdown(
        "### Vendor Information"
    )

    vendor = find_vendor(
        task
    )

    if vendor:

        items = {
            k: v
            for k, v in vendor.items()
            if k not in {
                "_id",
                "vendor_key",
                "synced_at",
            }
            and text(v)
        }

        if items:

            vendor_cols = st.columns(
                min(
                    3,
                    len(items),
                )
            )

            for i, (
                key,
                value,
            ) in enumerate(
                items.items()
            ):

                with vendor_cols[
                    i % len(vendor_cols)
                ]:

                    st.caption(
                        key.replace(
                            "_",
                            " "
                        ).title()
                    )

                    st.write(
                        text(value)
                    )

    else:

        st.info(
            "No matching vendor information found. "
            "Upload the vendor Excel file from Settings."
        )

    # ----------------------------------------------------
    # TRANSFER
    # ----------------------------------------------------

    st.markdown(
        "### Transfer Case"
    )

    stations = list(
        STATIONS.keys()
    )

    current = station_name(
        task.get(
            "department"
        )
    )

    destination = st.selectbox(
        "Destination",
        stations,
        index=(
            stations.index(current)
            if current in stations
            else 0
        ),
    )

    st.caption(
        "Duration resets when the case enters the destination station."
    )

    if st.button(
        f"Transfer to {destination}",
        type="primary",
        use_container_width=True,
    ):

        if destination == current:

            st.warning(
                "Choose a different station."
            )

        elif transfer_case(
            task,
            destination,
        ):

            st.success(
                f"Case transferred to {destination}."
            )

            st.session_state[
                "show_case"
            ] = False

            st.session_state[
                "selected_case_id"
            ] = None

            st.rerun()

        else:

            st.error(
                "Unable to transfer case."
            )

    # ----------------------------------------------------
    # HISTORY
    # ----------------------------------------------------

    history = task.get(
        "history",
        []
    )

    if history:

        st.markdown(
            "### Activity History"
        )

        for event in reversed(
            history[-15:]
        ):

            st.write(
                f"• {text(event.get('action'))}"
            )

            st.caption(
                dt_display(
                    event.get(
                        "timestamp"
                    )
                )
            )




# ============================================================
# DASHBOARD
# ============================================================
# IMPORTANT: This dashboard intentionally has NO periodic Streamlit
# rerun. The only continuously updating value is Duration, which is
# handled entirely by browser-side JavaScript below.

def dashboard_fragment():

    selected = st.session_state[
        "selected_station"
    ]

    tasks = fetch_tasks(
        search=st.session_state[
            "search"
        ],
        station=None,
        limit=300,
    )

    # Alerts are evaluated only when the dashboard itself renders
    # (initial load or a user action). There is deliberately no
    # background polling/rerun.
    scan_alerts(tasks)

    now = utc_now()

    states = {}

    for task in tasks:
        states[
            str(task["_id"])
        ] = calculate_state(
            task,
            now,
        )

    # --------------------------------------------------------
    # STATION TILES
    # --------------------------------------------------------

    station_cols = st.columns(5)

    for index, station in enumerate(
        STATIONS
    ):

        station_tasks = [
            task
            for task in tasks
            if station_name(
                task.get("department")
            ) == station
        ]

        station_states = [
            states[str(t["_id"])]
            for t in station_tasks
        ]

        critical = any(
            state["critical"]
            for state in station_states
        )

        nearing = sum(
            state["critical"]
            for state in station_states
        )

        config = STATIONS[
            station
        ]

        with station_cols[index]:
            slug = {"CARE":"care","ARCH":"arch","PET":"pet","SUPPLY CHAIN":"supply","ONSITE":"onsite"}[station]
            icon = config.get("icon", "•")
            sla = config["sla_minutes"]
            sla_text = f"{sla} mins" if sla < 60 else f"{sla // 60} hour" + ("s" if sla != 60 else "")
            warning_html = f'<div class="station-warning">◷ &nbsp; {nearing} nearing due</div>' if nearing else ""
            sla_bottom = "bottom:0px;" if nearing else "bottom:15px;"
            critical_class = "critical" if critical else ""

            # Keep the visual card and its invisible Streamlit click target
            # inside the same keyed container. This prevents Streamlit from
            # rendering a plain text button in place of the card.
            with st.container(key=f"station_wrap_{slug}"):
                st.markdown(
                    f"""
                    <div class="station-card-visual {slug} {critical_class}">
                        <div class="station-icon-circle">{html.escape(icon)}</div>
                        <div class="station-copy">
                            <div class="station-card-title">{html.escape(station)}</div>
                            <div class="station-count-line"><span class="station-count">{len(station_tasks)}</span><span class="station-active">Active Cases</span></div>
                        </div>
                        <div class="station-arrow">›</div>
                        {warning_html}
                        <div class="station-sla-ref" style="{sla_bottom}">◷ &nbsp; Max Timeframe: <strong>{sla_text}</strong></div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button("", key=f"station_{station}", use_container_width=True):
                    if critical:
                        acknowledge_station_alerts(station)
                    st.session_state["selected_station"] = station
                    st.rerun()

    st.markdown(
        "<div style='height:10px'></div>",
        unsafe_allow_html=True,
    )

    # --------------------------------------------------------
    # TABLE HEADER
    # --------------------------------------------------------

    selected_tasks = [
        task
        for task in tasks
        if station_name(
            task.get("department")
        ) == selected
    ]

    selected_tasks.sort(
        key=lambda task: (
            STATUS_ORDER.get(
                states[
                    str(task["_id"])
                ]["status"],
                9,
            ),
            states[
                str(task["_id"])
            ]["remaining"],
        )
    )

    title_cols = st.columns(
        [6.5, 2]
    )

    with title_cols[0]:

        st.markdown(
            f"""
            <span class="cases-title">
                Active Cases
            </span>
            <span class="station-pill">
                {html.escape(selected)}
            </span>
            """,
            unsafe_allow_html=True,
        )

    with title_cols[1]:

        sort_label = st.selectbox(
            "Sort",
            [
                "Urgency",
                "Duration",
                "Due Date",
            ],
            label_visibility="collapsed",
            key="sort_choice",
        )

    if sort_label == "Duration":

        selected_tasks.sort(
            key=lambda task:
            -states[
                str(task["_id"])
            ]["elapsed"]
        )

    elif sort_label == "Due Date":

        selected_tasks.sort(
            key=lambda task:
            as_utc(
                task.get(
                    "due_date"
                )
            ) or datetime.max.replace(
                tzinfo=timezone.utc
            )
        )

    # --------------------------------------------------------
    # BORDERLESS TABLE
    # --------------------------------------------------------

    header = st.columns(
        [1.05, 2.25, 1.25, 1.45, 1.45, 1.20, 1.15]
    )

    headers = [
        "Case #",
        "Subject",
        "Priority",
        "Assigned To",
        "Due Date",
        "Status",
        "Duration",
    ]

    for c, h in zip(
        header,
        headers,
    ):
        with c:
            st.markdown(
                f'<div class="case-head">{h}</div>',
                unsafe_allow_html=True,
            )

    for task in selected_tasks:

        task_id = str(
            task["_id"]
        )

        state = states[
            task_id
        ]

        status = state["status"]

        if status in {
            "CRITICAL",
            "BREACHED",
        }:
            status_class = "badge-critical"
        elif status == "MEDIUM":
            status_class = "badge-medium"
        else:
            status_class = "badge-low"

        priority_account = (
            state["priority_account"]
        )

        priority_text = (
            "Critical"
            if priority_account
            or status in {
                "CRITICAL",
                "BREACHED",
            }
            else text(
                task.get(
                    "priority",
                    "Low"
                )
            ).title()
        )

        priority_class = {
            "Critical": "priority-critical",
            "High": "priority-high",
            "Medium": "priority-medium",
            "Low": "priority-low",
        }.get(
            priority_text,
            "priority-low",
        )

        raw_status = text(
            task.get(
                "status",
                "Open"
            )
        ).lower()

        if "progress" in raw_status:
            status_class2 = "badge-progress"
        elif "hold" in raw_status:
            status_class2 = "badge-hold"
        elif "pending" in raw_status:
            status_class2 = "badge-pending"
        else:
            status_class2 = "badge-open"

        row = st.columns(
            [1.05, 2.25, 1.25, 1.45, 1.45, 1.20, 1.15]
        )

        with row[0]:

            st.markdown(
                '<div class="case-button">',
                unsafe_allow_html=True,
            )

            if st.button(
                text(task.get("case_number")),
                key=f"case_{task_id}",
                use_container_width=True,
            ):
                # Open the dialog directly from the user's click.
                # There is no periodic dashboard rerun.
                case_details(task_id)

            st.markdown(
                "</div>",
                unsafe_allow_html=True,
            )

        with row[1]:

            st.markdown(
                f"""
                <div class="case-row">
                    {html.escape(
                        text(task.get("subject"))
                    )}
                </div>
                """,
                unsafe_allow_html=True,
            )

        with row[2]:

            st.markdown(
                f"""
                <div class="case-row {priority_class}">
                    {html.escape(priority_text)}
                </div>
                """,
                unsafe_allow_html=True,
            )

        with row[3]:

            st.markdown(
                f"""
                <div class="case-row">
                    {html.escape(
                        text(
                            task.get(
                                "assigned_to",
                                "Unassigned"
                            )
                        )
                    )}
                </div>
                """,
                unsafe_allow_html=True,
            )

        with row[4]:

            due = dt_display(
                task.get(
                    "due_date"
                )
            ).replace(
                "\n",
                "<br>"
            )

            due_color = (
                "#e51c3a"
                if state["critical"]
                else "#31435f"
            )

            st.markdown(
                f"""
                <div class="case-row"
                     style="color:{due_color}">
                    {due}
                </div>
                """,
                unsafe_allow_html=True,
            )

        with row[5]:

            # For the reference UI, the operational status
            # remains separate from SLA priority.
            st.markdown(
                f"""
                <div class="case-row">
                    <span class="badge {status_class2}">
                        {html.escape(
                            text(
                                task.get(
                                    "status",
                                    "Open"
                                )
                            )
                        )}
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with row[6]:

            started = iso_z(
                task.get(
                    "station_started_at"
                )
                or task.get(
                    "created_at"
                )
            )

            # Browser-side timer:
            # duration changes every second according to
            # the user's own PC/browser clock and does not
            # require a Streamlit rerun.
            st.markdown(
                f"""
                <div class="case-row"
                     style="font-weight:700;
                            color:{'#e51c3a' if state['critical'] else '#53637f'}">
                    <span
                        data-duration-start="{html.escape(started)}"
                        data-duration-live="1">
                        {duration_string(state['elapsed'])}
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # --------------------------------------------------------
    # CLIENT-SIDE REAL-TIME DURATION
    # --------------------------------------------------------

    st.markdown(
        """
        <script>
        (function () {

            function updateDurations() {

                const nodes =
                    document.querySelectorAll(
                        '[data-duration-live="1"]'
                    );

                const now = new Date();

                nodes.forEach(function (node) {

                    const raw =
                        node.getAttribute(
                            "data-duration-start"
                        );

                    if (!raw) return;

                    const started =
                        new Date(raw);

                    if (isNaN(started.getTime())) {
                        return;
                    }

                    let seconds =
                        Math.max(
                            0,
                            Math.floor(
                                (now - started) / 1000
                            )
                        );

                    const h =
                        Math.floor(
                            seconds / 3600
                        );

                    seconds %= 3600;

                    const m =
                        Math.floor(
                            seconds / 60
                        );

                    const s =
                        seconds % 60;

                    node.textContent =
                        String(h).padStart(2, "0")
                        + ":"
                        + String(m).padStart(2, "0")
                        + ":"
                        + String(s).padStart(2, "0");
                });
            }

            updateDurations();

            if (!window.__taskTrackerDurationTimer) {
                window.__taskTrackerDurationTimer =
                    setInterval(
                        updateDurations,
                        1000
                    );
            }

        })();
        </script>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# INITIAL MOCK DATA
# ============================================================

# Seed before the first dashboard render so the first view already
# contains the mock cases. This check runs once per normal app render
# and does not create a background refresh loop.
if (
    col(TASKS_COLLECTION).count_documents(
        {"is_mock": True}
    ) == 0
):
    seed_mock_cases()


# Render the dashboard once. No run_every / autorefresh is used.
dashboard_fragment()


# ============================================================
# SIMULATION CLEANUP
# ============================================================

if (
    st.session_state.get(
        "simulation_until",
        0
    )
    and time.time()
    > st.session_state[
        "simulation_until"
    ]
):

    simulation_id = st.session_state.get(
        "simulation_case_id"
    )

    if simulation_id:

        try:
            from bson import ObjectId

            col(
                TASKS_COLLECTION
            ).update_one(
                {
                    "_id": ObjectId(
                        simulation_id
                    )
                },
                {
                    "$set": {
                        "active": False
                    }
                },
            )
        except Exception:
            pass

    st.session_state[
        "simulation_until"
    ] = 0

    st.session_state[
        "simulation_case_id"
    ] = None


# ============================================================
# FOOTER
# ============================================================

st.markdown(
    """
    <div style="
        text-align:center;
        color:#98a2b3;
        font-size:11px;
        padding-top:22px;
    ">
        Real-time monitoring enabled •
        Duration updates in the browser without refreshing the full dashboard
    </div>
    """,
    unsafe_allow_html=True,
)
