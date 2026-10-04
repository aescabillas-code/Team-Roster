"""
TASKS MONITORING TRACKER
Single-file Streamlit application.

UI is designed to closely match the supplied dashboard reference:
- White/light gray background
- Dark navy typography
- Exact uploaded HPE Caseflow header interface
- Integrated live search bar
- Five pastel station tiles
- Borderless active-case table
- Right-side case-detail dialog
- Settings control only (no alert bell / no profile)
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
    pip install streamlit pymongo pandas openpyxl itsdangerous streamlit-js-eval
"""

import hashlib
import hmac
import html
import secrets
import os
import time
import textwrap
from datetime import datetime, timezone, timedelta
from typing import Optional

try:
    from itsdangerous import URLSafeTimedSerializer
except Exception:
    URLSafeTimedSerializer = None

try:
    from streamlit_js_eval import streamlit_js_eval
except Exception:
    streamlit_js_eval = None

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

# Performance tuning: short cache keeps station switches responsive while preserving near-real-time data.
TASK_CACHE_TTL = 1.0
# Alert scans are lightweight and run in a dedicated 1-second fragment.
# Duration itself remains browser-side, while Alert_Collection is kept near real time.
ALERT_SCAN_MIN_INTERVAL = 1.0

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
# PERSISTENT ONE-TIME ACCESS — DESKTOP + MOBILE BROWSER STORAGE
# ============================================================
# The access code is requested only once per browser profile.
# A signed authorization token is stored in browser storage and is
# NEVER placed in the URL or query string.
#
# Behavior:
#   - ACCESS_CODE and TOKEN_SECRET are read only from Streamlit Secrets.
#   - Successful access creates a signed token.
#   - The browser stores that token in a durable first-party cookie and localStorage.
#   - sessionStorage is used only as a fallback when persistent storage is blocked.
#   - Refreshing/reopening the browser restores authorization automatically.
#   - Changing ACCESS_CODE invalidates previously issued tokens.
#   - Clearing browser access removes the stored authorization token.
#
# Required dependencies:
#   itsdangerous
#   streamlit-js-eval
#
# This intentionally follows the persistent authorization behavior used by
# the Knowledge Base implementation.

ACCESS_STORAGE_KEY = "hpe_caseflow_authorized_v1"
AUTH_COOKIE_KEY = "hpe_caseflow_authorized_cookie_v1"
JS_READ_KEY = "hpe_caseflow_auth_read_v1"
JS_SAVE_KEY = "hpe_caseflow_auth_save_v1"
JS_CLEAR_KEY = "hpe_caseflow_auth_clear_v1"


def _get_access_secrets():
    """Read ACCESS_CODE and TOKEN_SECRET only from Streamlit Secrets/environment."""
    access_code_value = ""
    token_secret = ""

    try:
        access_code_value = str(
            st.secrets.get(
                "ACCESS_CODE",
                os.getenv("ACCESS_CODE", ""),
            )
        ).strip()
        token_secret = str(
            st.secrets.get(
                "TOKEN_SECRET",
                os.getenv("TOKEN_SECRET", ""),
            )
        ).strip()
    except Exception:
        access_code_value = os.getenv("ACCESS_CODE", "").strip()
        token_secret = os.getenv("TOKEN_SECRET", "").strip()

    return access_code_value, token_secret


def access_code():
    return _get_access_secrets()[0]


def admin_pin():
    return text(st.secrets.get("ADMIN_PIN", ""))


def _get_code_fingerprint(code: str) -> str:
    return hashlib.sha256(
        code.encode("utf-8")
    ).hexdigest()[:32]


def get_token_serializer():
    if URLSafeTimedSerializer is None:
        return None

    access_code_value, token_secret = _get_access_secrets()

    if not access_code_value or not token_secret:
        return None

    salt = (
        "hpe-caseflow-browser-access-v1-"
        f"{_get_code_fingerprint(access_code_value)}"
    )

    return URLSafeTimedSerializer(
        token_secret,
        salt=salt,
    )


def create_browser_token():
    serializer = get_token_serializer()
    access_code_value, _ = _get_access_secrets()

    if serializer is None or not access_code_value:
        return ""

    return serializer.dumps({
        "authorized": True,
        "fp": _get_code_fingerprint(access_code_value),
    })


def validate_browser_token(token):
    if not token:
        return False

    serializer = get_token_serializer()
    access_code_value, _ = _get_access_secrets()

    if serializer is None or not access_code_value:
        return False

    try:
        payload = serializer.loads(str(token))

        if payload.get("authorized") is not True:
            return False

        return hmac.compare_digest(
            str(payload.get("fp", "")),
            _get_code_fingerprint(access_code_value),
        )
    except Exception:
        return False


def _js_parent_storage(expression: str, key: str):
    """Evaluate browser storage through streamlit-js-eval."""
    if streamlit_js_eval is None:
        return None

    try:
        return streamlit_js_eval(
            js_expressions=expression,
            want_output=True,
            key=key,
        )
    except Exception:
        return None


def _read_server_cookie_token():
    """Read the signed authorization token from the browser cookie on the current request."""
    try:
        context = getattr(st, "context", None)
        cookies = getattr(context, "cookies", None)
        if cookies:
            value = cookies.get(AUTH_COOKIE_KEY)
            if value:
                return str(value)
    except Exception:
        pass
    return ""


def _read_browser_token():
    """Read persistent authorization; prefer a server-visible cookie, then browser storage."""
    # Cookies survive refreshes and closing/reopening the tab and are available
    # to Streamlit on the next request. This avoids relying solely on the
    # streamlit-js-eval iframe's localStorage origin.
    cookie_token = _read_server_cookie_token()
    if cookie_token:
        return cookie_token

    key = repr(ACCESS_STORAGE_KEY)

    expression = f"""
    (() => {{
        try {{
            const key = {key};
            const stores = [];
            const addStore = (store) => {{
                if (store && !stores.includes(store)) stores.push(store);
            }};

            try {{ addStore(window.top.localStorage); }} catch (e) {{}}
            try {{ addStore(window.parent.localStorage); }} catch (e) {{}}
            try {{ addStore(window.localStorage); }} catch (e) {{}}

            for (const store of stores) {{
                try {{
                    const value = store.getItem(key);
                    if (value) return value;
                }} catch (e) {{}}
            }}

            try {{
                const value = window.sessionStorage.getItem(key);
                if (value) return value;
            }} catch (e) {{}}

            return '';
        }} catch (e) {{
            return '';
        }}
    }})()
    """

    value = _js_parent_storage(expression, JS_READ_KEY)
    if value is None:
        return None
    return str(value or "")


def _save_browser_token(token: str):
    """Persist authorization in a durable cookie plus browser storage fallback."""
    key = repr(ACCESS_STORAGE_KEY)
    cookie_key = repr(AUTH_COOKIE_KEY)
    value = repr(str(token))

    expression = f"""
    (() => {{
        try {{
            const key = {key};
            const cookieKey = {cookie_key};
            const value = {value};
            let saved = false;

            // Durable first-party cookie. Secure is enabled automatically on HTTPS.
            try {{
                const secure = window.location.protocol === 'https:' ? '; Secure' : '';
                const cookie = cookieKey + '=' + encodeURIComponent(value) +
                    '; Max-Age=31536000; Path=/; SameSite=Lax' + secure;
                const docs = [];
                const addDoc = (doc) => {{
                    if (doc && !docs.includes(doc)) docs.push(doc);
                }};
                try {{ addDoc(window.top.document); }} catch (e) {{}}
                try {{ addDoc(window.parent.document); }} catch (e) {{}}
                try {{ addDoc(document); }} catch (e) {{}}
                for (const doc of docs) {{
                    try {{ doc.cookie = cookie; }} catch (e) {{}}
                    try {{
                        if (doc.cookie.indexOf(cookieKey + '=') !== -1) saved = true;
                    }} catch (e) {{}}
                }}
            }} catch (e) {{}}

            const stores = [];
            const addStore = (store) => {{
                if (store && !stores.includes(store)) stores.push(store);
            }};
            try {{ addStore(window.top.localStorage); }} catch (e) {{}}
            try {{ addStore(window.parent.localStorage); }} catch (e) {{}}
            try {{ addStore(window.localStorage); }} catch (e) {{}}

            for (const store of stores) {{
                try {{ store.setItem(key, value); saved = true; }} catch (e) {{}}
            }}

            if (!saved) {{
                try {{ window.sessionStorage.setItem(key, value); saved = true; }} catch (e) {{}}
            }}

            return saved ? 'saved' : 'error';
        }} catch (e) {{
            return 'error';
        }}
    }})()
    """

    result = _js_parent_storage(expression, JS_SAVE_KEY)
    return result == "saved"


def _clear_browser_token():
    """Remove authorization from cookie, localStorage and sessionStorage."""
    key = repr(ACCESS_STORAGE_KEY)
    cookie_key = repr(AUTH_COOKIE_KEY)

    expression = f"""
    (() => {{
        try {{
            const key = {key};
            const cookieKey = {cookie_key};
            let cleared = false;

            try {{
                const expired = cookieKey + '=; Max-Age=0; Path=/; SameSite=Lax';
                const docs = [];
                const addDoc = (doc) => {{
                    if (doc && !docs.includes(doc)) docs.push(doc);
                }};
                try {{ addDoc(window.top.document); }} catch (e) {{}}
                try {{ addDoc(window.parent.document); }} catch (e) {{}}
                try {{ addDoc(document); }} catch (e) {{}}
                for (const doc of docs) {{
                    try {{ doc.cookie = expired; cleared = true; }} catch (e) {{}}
                }}
            }} catch (e) {{}}

            const stores = [];
            const addStore = (store) => {{
                if (store && !stores.includes(store)) stores.push(store);
            }};
            try {{ addStore(window.top.localStorage); }} catch (e) {{}}
            try {{ addStore(window.parent.localStorage); }} catch (e) {{}}
            try {{ addStore(window.localStorage); }} catch (e) {{}}

            for (const store of stores) {{
                try {{ store.removeItem(key); cleared = true; }} catch (e) {{}}
            }}

            try {{ window.sessionStorage.removeItem(key); cleared = true; }} catch (e) {{}}
            return cleared ? 'cleared' : 'error';
        }} catch (e) {{
            return 'error';
        }}
    }})()
    """

    result = _js_parent_storage(expression, JS_CLEAR_KEY)
    return result == "cleared"


def browser_is_authorized():
    """
    Check Streamlit session state first, then persistent browser storage.
    """
    if st.session_state.get(
        "access_authorized",
        False,
    ):
        return True

    token = _read_browser_token()

    if token is None:
        # The JS bridge has not returned yet. Do not incorrectly show
        # the access-code form while the stored authorization is restoring.
        return None

    if validate_browser_token(token):
        st.session_state["access_authorized"] = True
        st.session_state["access_granted"] = True
        return True

    return False


def authorize_browser():
    """Authorize immediately and persist the signed token in browser storage."""
    token = create_browser_token()

    if not token:
        return False

    # The current session becomes authorized immediately. The browser
    # component writes the signed token independently.
    _save_browser_token(token)

    st.session_state["access_authorized"] = True
    st.session_state["access_granted"] = True

    return True


def clear_token_access():
    """
    Clear authorization for this browser profile.

    The authorization token is removed from localStorage/sessionStorage and
    the current Streamlit session is reset. Existing authorization elsewhere
    is governed by that browser's own stored token.
    """
    st.session_state["access_authorized"] = False
    st.session_state["access_granted"] = False
    st.session_state.pop("access_token", None)
    st.session_state.pop("access_code_hash", None)

    _clear_browser_token()


def access_gate():
    """
    One-time access-code gate with persistent desktop/mobile authorization.
    """
    if URLSafeTimedSerializer is None or streamlit_js_eval is None:
        st.error(
            "Persistent browser authorization is not installed. "
            "Add `itsdangerous` and `streamlit-js-eval` to requirements.txt, "
            "then redeploy."
        )
        st.stop()

    access_code_value, token_secret = _get_access_secrets()

    if not access_code_value or not token_secret:
        st.error(
            "Access control is not configured. Add ACCESS_CODE and "
            "TOKEN_SECRET to Streamlit Secrets; do not place them in "
            "the source code."
        )
        st.stop()

    authorized = browser_is_authorized()

    if authorized is True:
        return True

    if authorized is None:
        st.markdown(
            """
            <div style="
                height:18vh;
                display:flex;
                align-items:center;
                justify-content:center;
                color:#5a7180;
                font-size:13px;
            ">
                Restoring secure browser access…
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.stop()

    st.markdown(
        """
        <style>
        .access-wrap {
            max-width:560px;
            margin:12vh auto 0 auto;
            background:#ffffff;
            border:1px solid #e8edf4;
            border-radius:26px;
            padding:42px;
            box-shadow:0 24px 70px rgba(20,38,70,.10);
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
        if hmac.compare_digest(
            code,
            access_code_value,
        ):
            if authorize_browser():
                st.rerun()
            else:
                st.error(
                    "Unable to save browser authorization. "
                    "Please check browser storage permissions."
                )
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
    # Kept for compatibility with existing session state; acknowledgement
    # now stops tile flashing immediately.
    "station_warning_ack_until": {},
    # Stations silenced after the user clicks their active warning tile.
    # The station stays silenced until the current warning condition clears.
    "station_warning_silenced": set(),
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
    @import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap");

    html, body, [class*="css"], .stApp, .stApp * {
        font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
    }

    button, input, textarea, select, [role="button"], [role="combobox"] {
        font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
    }

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

    body,
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stAppViewContainer"] > .main {
        background:#ffffff !important;
    }

    .block-container,
    .block-container p,
    .block-container div,
    .block-container span,
    .block-container label,
    .block-container button,
    .block-container input,
    .block-container textarea,
    .block-container select {
        font-family:"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
    }

    /* HEADER — exact uploaded Caseflow header reference */
    .caseflow-header-shell {
        position:relative !important;
        height:43px !important;
        min-height:43px !important;
        width:100% !important;
        padding:0 !important;
        margin:0 0 18px 0 !important;
        overflow:hidden !important;
        border:1px solid #d6e0df !important;
        border-radius:2px !important;
        box-sizing:border-box !important;
        background:#003c40 url("data:image/png;base64,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F91+6+Lbb1t8h+G6O2+/7s47jN51++I7b19wx23X3H4ruPaOWxfcedvCu25fcNft1955+zV33Hr1HbctwOGuOxbec+fCu++89u7br7kr4O7bF6C5566F99wBFt1zx2LDndfdd9d19929+L67Ft57Fw4LsN5758L7Miy4984F996x8N47cbj+/ruvv/8e6HX33YW48N47FtxzO/mvvfuOa/n8eNft195pxSy4y4oxeudt1wZ+Yahw4d13LDbcDr3u7jsADFh01+3Un2LR3beHwu40/Z23Lbjj1mtvv/Wq22+9+s5bGWjBPXcuvueu6+4F9yy2mikbWDGLKPieO6hnwd23X0tV1HZvNoXFVHv/XYvvv3vR/XctvO+OhffduWAEdy26DyXA+e6Fxt+NBiy47y5zu/fOa+6941pW4L67F91/z3UP3AsW3X83ymvuuePqe2676u7bfnaX0WsY3dKSKkWa7a7F97HCd193391UvvieOxfdc9eiGl18z12L773runsM19971/X33X3j/ffceP+94Of33/vzB+7/6R23f3TB1f9w2Q//8tor1XzO5yJ16VbBbSi+d9D3DfKSquxD3Jgp2DRS4MhNzF7CEyauCn/9Hd+uRx/kPvge/cfT5MMnyanHyHGHyOH7+f329HtM9hPG+K72pKMt6WhJ2lvilsa4IYobNGmNkvHtiUuSl16On3whfuJFeektXb5G121SPm6v2yyr18uaNbq12x4wjU3K18f+Ph4YWuoUH/ukIp0l4atkoZBUEt17T9l9oh8aSuIqO65jLx/fKRu6/aMvyLYBaS/5LdtlcFhykbQ28Qd137NDegdt895jilSqfsM2+9LA14I4Ee+VCbIBdnbYyzrfITzLwqNJMdAJjQ4l64P73Y9Hhx/gZkwWiTWualzRalV5s69U7dcAbmL5SJmCaLYL9Z6fGtGcd7kd/bqtj4mIc+aIL8nF2aoTwJOQLymmIX1CLHAcZjatHSZy1Fn2fyaBv8im7q0vr1iRSLJjaODZl19YtXbtHQ8+sGLNqq3bt9394IPsYeVK5dHnnrvr4Uc2dHc//vKr2weHbrr/L3c+8vjKDRtXrd8w3N//5NNP33rvvU+/9PKmLZsffOqplRvXv7J69csrV1dFN3Zv3TbQf/J7jn//B9/3x5v/bN8QKsNvrFq1fN367t7eh59+bnvP9jdX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") center center / 100% 100% no-repeat !important;
    }

    .caseflow-header-shell [data-testid="stHorizontalBlock"] {
        position:absolute !important;
        inset:0 !important;
        width:100% !important;
        height:43px !important;
        min-height:43px !important;
        margin:0 !important;
        padding:0 !important;
        display:block !important;
    }

    .caseflow-header-shell [data-testid="stHorizontalBlock"] > div:nth-child(1) {
        display:none !important;
    }

    .caseflow-header-shell [data-testid="stHorizontalBlock"] > div:nth-child(2) {
        position:absolute !important;
        left:34.2% !important;
        top:7px !important;
        width:44% !important;
        max-width:none !important;
        min-width:0 !important;
        padding:0 !important;
        margin:0 !important;
    }

    .caseflow-header-shell [data-testid="stHorizontalBlock"] > div:nth-child(3) {
        position:absolute !important;
        right:1.1% !important;
        top:3px !important;
        width:40px !important;
        max-width:40px !important;
        min-width:40px !important;
        padding:0 !important;
        margin:0 !important;
    }

    .caseflow-header-shell div[data-testid="stTextInput"] {
        width:100% !important;
        margin:0 !important;
        padding:0 !important;
    }

    .caseflow-header-shell div[data-testid="stTextInput"] > div {
        width:100% !important;
        min-height:0 !important;
        margin:0 !important;
        padding:0 !important;
    }

    .caseflow-header-shell div[data-testid="stTextInput"] input {
        width:100% !important;
        height:24px !important;
        min-height:24px !important;
        box-sizing:border-box !important;
        border:0 !important;
        outline:none !important;
        border-radius:6px !important;
        background:#ffffff url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23728a98' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='7'/%3E%3Cpath d='m20 20-4-4'/%3E%3C/svg%3E") 8px center / 11px 11px no-repeat !important;
        box-shadow:none !important;
        color:#244a55 !important;
        font-size:8px !important;
        font-weight:500 !important;
        line-height:24px !important;
        padding:0 10px 0 25px !important;
    }

    .caseflow-header-shell div[data-testid="stTextInput"] input::placeholder {
        color:#748a98 !important;
        opacity:1 !important;
        font-size:8px !important;
    }

    .caseflow-header-shell div[data-testid="stTextInput"] input:focus {
        border:0 !important;
        box-shadow:0 0 0 1px rgba(0,168,132,.35) !important;
    }

    .caseflow-header-shell [data-testid="stHorizontalBlock"] > div:nth-child(3) button {
        width:40px !important;
        height:37px !important;
        min-height:37px !important;
        padding:0 !important;
        margin:0 !important;
        border:0 !important;
        border-radius:7px !important;
        background:transparent !important;
        box-shadow:none !important;
        color:transparent !important;
        font-size:1px !important;
        opacity:1 !important;
        cursor:pointer !important;
    }

    .caseflow-header-shell [data-testid="stHorizontalBlock"] > div:nth-child(3) button:hover,
    .caseflow-header-shell [data-testid="stHorizontalBlock"] > div:nth-child(3) button:focus,
    .caseflow-header-shell [data-testid="stHorizontalBlock"] > div:nth-child(3) button:active {
        background:rgba(255,255,255,.08) !important;
        box-shadow:none !important;
        outline:none !important;
    }

    /* Keep the exact baked-in HPE / Caseflow artwork visible; only the
       live search field and settings click target sit above it. */

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

    /* Keep fragment station switching visually clean. The selected tile is
       updated on pointerdown before Streamlit performs its fragment rerun. */
    [data-testid="stStatusWidget"],
    [data-testid="stSpinner"],
    .stSpinner {
        opacity:0 !important;
        pointer-events:none !important;
    }

    /* STATION TILES — reference visual + reliable full-card click target */
    [class*="st-key-station_wrap_care"], [class*="st-key-station_wrap_arch"],
    [class*="st-key-station_wrap_pet"], [class*="st-key-station_wrap_supply"],
    [class*="st-key-station_wrap_onsite"] { position:relative !important; min-height:184px !important; overflow:visible !important; }
    .station-card-visual {
        position:relative; z-index:1; height:184px; min-height:184px; box-sizing:border-box;
        border-radius:13px; padding:18px 24px; overflow:hidden;
        color:#102041;
    }
    .station-card-visual {
        transition:border-color .12s ease, box-shadow .12s ease, transform .12s ease;
        will-change:border-color, box-shadow;
    }
    .station-card-visual.care {
        background:linear-gradient(135deg,#fff4f6,#ffe8ec);
        border:1.5px solid #f24a61;
    }
    .station-card-visual.arch {
        background:linear-gradient(135deg,#eaf8ff,#d9f1fc);
        border:1.5px solid #69b7e5;
    }
    .station-card-visual.pet {
        background:linear-gradient(135deg,#ecfff9,#dcf7ee);
        border:1.5px solid #70cda9;
    }
    .station-card-visual.supply {
        background:linear-gradient(135deg,#f7f0ff,#eee5ff);
        border:1.5px solid #a07de2;
    }
    .station-card-visual.onsite {
        background:linear-gradient(135deg,#fff9e8,#fff3cf);
        border:1.5px solid #e0b94f;
    }

    /* Selected station = visibly thicker border in its own station color. */
    .station-card-visual.care.selected { border:3px solid #f24a61 !important; }
    .station-card-visual.arch.selected { border:3px solid #69b7e5 !important; }
    .station-card-visual.pet.selected { border:3px solid #70cda9 !important; }
    .station-card-visual.supply.selected { border:3px solid #a07de2 !important; }
    .station-card-visual.onsite.selected { border:3px solid #e0b94f !important; }
    .station-icon-circle {
        width:64px; height:64px; border-radius:50%; display:flex; align-items:center; justify-content:center;
        font-size:30px; font-weight:900; position:absolute; left:24px; top:18px;
        background:rgba(255,255,255,.48);
    }
    .care .station-icon-circle { color:#e51c3a; background:#ffd7df; }
    .arch .station-icon-circle { color:#0879c9; background:#bce8ff; }
    .pet .station-icon-circle { color:#087b58; background:#bff1df; }
    .supply .station-icon-circle { color:#5d2ac9; background:#dfceff; }
    .onsite .station-icon-circle { color:#c98700; background:#ffe5a8; }
    .station-copy { position:absolute; left:112px; top:29px; }
    .station-card-title { font-size:18px; font-weight:850; line-height:1.1; letter-spacing:-.3px; }
    .station-count-line { display:flex; align-items:baseline; gap:6px; margin-top:8px; }
    .station-count { font-size:32px; line-height:1; font-weight:900; }
    .station-active { font-size:12px; color:#53637f; }
    .care .station-count { color:#e51c3a; }
    .arch .station-count { color:#0879c9; }
    .pet .station-count { color:#087b58; }
    .supply .station-count { color:#5d2ac9; }
    .onsite .station-count { color:#c98700; }
    .station-arrow { position:absolute; right:20px; top:31px; font-size:25px; font-weight:300; color:#30466b; }
    .station-warning { position:absolute; left:24px; bottom:39px; font-size:12px; font-weight:750; color:#53637f; }
    .station-warning.active { color:#d33a4e; }
    .arch .station-warning.active, .pet .station-warning.active, .supply .station-warning.active, .onsite .station-warning.active { color:#53637f; }
    .station-sla-ref { position:absolute; left:24px; bottom:17px; font-size:12px; color:#53637f; }
    .station-sla-ref strong { color:#102041; }
    /* Make the real button transparent and stretch it over the card. */
    [class*="st-key-station_wrap_care"] [class*="st-key-station_CARE"],
    [class*="st-key-station_wrap_arch"] [class*="st-key-station_ARCH"],
    [class*="st-key-station_wrap_pet"] [class*="st-key-station_PET"],
    [class*="st-key-station_wrap_supply"] [class*="st-key-station_SUPPLY"],
    [class*="st-key-station_wrap_onsite"] [class*="st-key-station_ONSITE"] {
        position:absolute !important; inset:0 !important; z-index:50 !important;
        width:100% !important; height:184px !important;
    }
    [class*="st-key-station_wrap_care"] [class*="st-key-station_CARE"] button,
    [class*="st-key-station_wrap_arch"] [class*="st-key-station_ARCH"] button,
    [class*="st-key-station_wrap_pet"] [class*="st-key-station_PET"] button,
    [class*="st-key-station_wrap_supply"] [class*="st-key-station_SUPPLY"] button,
    [class*="st-key-station_wrap_onsite"] [class*="st-key-station_ONSITE"] button {
        position:absolute !important; inset:0 !important; width:100% !important; height:184px !important;
        background:transparent !important; border:0 !important; box-shadow:none !important;
        color:transparent !important; font-size:1px !important; opacity:0.001 !important;
        cursor:pointer !important; z-index:30 !important; pointer-events:auto !important;
    }
    /* ACTIVE SLA WARNING: intentionally strong and unmistakable. */
    .station-card-visual.critical {
        border:2px solid #ef334f !important;
        animation:stationCardFlash .55s ease-in-out infinite alternate;
    }
    .station-card-visual.critical.selected {
        border-width:3px !important;
    }
    .station-alert-icon {
        position:absolute;
        right:54px;
        top:22px;
        width:34px;
        height:34px;
        border-radius:50%;
        background:#ef1738;
        color:#fff;
        display:flex;
        align-items:center;
        justify-content:center;
        font-size:22px;
        line-height:1;
        font-weight:950;
        box-shadow:0 0 0 3px rgba(239,23,56,.16), 0 5px 16px rgba(239,23,56,.28);
        z-index:4;
        animation:stationAlertIconFlash .42s ease-in-out infinite alternate;
    }
    @keyframes stationCardFlash {
        from {
            box-shadow:0 0 0 0 rgba(239,23,56,.12), 0 0 0 rgba(239,23,56,0);
            filter:saturate(1);
        }
        to {
            box-shadow:0 0 0 5px rgba(239,23,56,.16), 0 0 30px rgba(239,23,56,.48);
            filter:saturate(1.18);
        }
    }
    @keyframes stationAlertIconFlash {
        from {
            transform:scale(.86);
            opacity:.58;
            box-shadow:0 0 0 3px rgba(239,23,56,.12), 0 4px 10px rgba(239,23,56,.18);
        }
        to {
            transform:scale(1.14);
            opacity:1;
            box-shadow:0 0 0 7px rgba(239,23,56,.24), 0 0 24px rgba(239,23,56,.72);
        }
    }

    .station-card-visual.warning-muted {
        animation:none !important;
        box-shadow:none !important;
        filter:none !important;
    }
    .station-card-visual.warning-muted .station-alert-icon {
        animation:none !important;
        transform:none !important;
        opacity:1 !important;
    }
    .duration-warning-wrap {
        display:inline-flex;
        align-items:center;
        min-height:24px;
        white-space:nowrap;
        font-weight:800 !important;
        transition:color .25s ease, text-shadow .25s ease, opacity .25s ease;
    }
    /* Duration color follows elapsed time in the CURRENT station SLA:
       green = 0-50%, yellow = 50-80%, red = 80-100% and beyond. */
    .duration-warning-wrap.duration-green { color:#218137 !important; }
    .duration-warning-wrap.duration-yellow { color:#c58a00 !important; }
    .duration-warning-wrap.duration-red {
        color:#e51c3a !important;
        font-weight:900 !important;
    }
    /* Final 20% still pulses to make an approaching breach unmistakable. */
    .duration-warning-wrap.duration-warning-active {
        color:#ef1738 !important;
        font-weight:900 !important;
        animation:durationTextFlash .65s ease-in-out infinite alternate;
        text-shadow:0 0 8px rgba(239,23,56,.30);
    }
    @keyframes durationTextFlash {
        from { opacity:.55; }
        to { opacity:1; }
    }

    /* TABLE */

    .cases-title {
        color:#11213e;
        font-size:21px;
        font-weight:850;
        letter-spacing:-.5px;
    }

    .station-pill {
        display:inline-block;
        padding:7px 14px;
        border-radius:18px;
        font-weight:800;
        font-size:13px;
        margin-left:10px;
        vertical-align:middle;
    }

    .case-head {
        color:#263957;
        font-size:10px;
        font-weight:700;
        padding:7px 6px;
        border-bottom:1px solid #edf0f5;
        white-space:nowrap;
    }

    .case-row {
        min-height:30px;
        border-bottom:1px solid #edf0f5;
        color:#31435f;
        font-size:10px;
        line-height:1.2;
        padding:4px 6px;
        box-sizing:border-box;
    }

    .case-row:hover { background:#fbfcfe; }
    .case-selected { background:#fff0f3 !important; }

    .case-button button {
        border:none !important; background:transparent !important; border-radius:0 !important;
        box-shadow:none !important; color:#66758d !important;
        padding:0 !important; margin:0 !important; min-height:24px !important; height:24px !important;
        text-align:left !important; font-size:10px !important; line-height:1.2 !important; font-weight:500 !important;
    }
    .case-button button p, .case-button button div {
        font-size:10px !important; line-height:1.2 !important; margin:0 !important; padding:0 !important;
    }

    .case-button button:hover {
        color:#6c4cff !important;
        text-decoration:underline;
    }

    /* Case number is a compact cell button that stays inside its table row. */
    [class*="st-key-case_cell_"] {
        min-width:0 !important;
        width:100% !important;
        min-height:30px !important;
        height:30px !important;
        display:flex !important;
        align-items:center !important;
    }
    [class*="st-key-case_cell_"] > div {
        width:100% !important;
        min-width:0 !important;
    }
    [class*="st-key-case_cell_"] button,
    [class*="st-key-case_cell_"] button *,
    [class*="st-key-case_cell_"] button p,
    [class*="st-key-case_cell_"] button div,
    [class*="st-key-case_cell_"] button span {
        font-family:"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
        font-size:10px !important;
        line-height:1.1 !important;
        font-weight:500 !important;
    }
    [class*="st-key-case_cell_"] button {
        width:100% !important;
        min-width:0 !important;
        max-width:100% !important;
        height:30px !important;
        min-height:30px !important;
        padding:4px 8px !important;
        margin:0 !important;
        border:1px solid #d3dbe7 !important;
        border-radius:7px !important;
        background:#fff !important;
        box-shadow:none !important;
        color:#31435f !important;
        font-size:10px !important;
        font-weight:500 !important;
        line-height:1.1 !important;
        white-space:nowrap !important;
        overflow:hidden !important;
        text-overflow:ellipsis !important;
    }
    [class*="st-key-case_cell_"] button:hover {
        border-color:#b7c4d7 !important;
        color:#5d42e8 !important;
    }

    /* Case-number cells inherit the pastel color of their current station. */
    [class*="st-key-case_cell_care_"] button {
        background:#fff0f2 !important;
        border-color:#f3a4b0 !important;
    }
    [class*="st-key-case_cell_arch_"] button {
        background:#eaf7ff !important;
        border-color:#9bd7f5 !important;
    }
    [class*="st-key-case_cell_pet_"] button {
        background:#ecfbf4 !important;
        border-color:#9cdec6 !important;
    }
    [class*="st-key-case_cell_supply_"] button {
        background:#f2edff !important;
        border-color:#c8b5f3 !important;
    }
    [class*="st-key-case_cell_onsite_"] button {
        background:#fff8df !important;
        border-color:#ecd28c !important;
    }
    [class*="st-key-case_cell_"] button:hover {
        filter:brightness(.985);
    }

    .agent-cell {
        display:flex;
        align-items:center;
        gap:7px;
        min-height:30px;
        border-bottom:1px solid #edf0f5;
        color:#31435f;
        font-size:10px;
        white-space:nowrap;
    }

    .agent-avatar {
        width:25px;
        height:25px;
        min-width:25px;
        border-radius:50%;
        display:inline-flex;
        align-items:center;
        justify-content:center;
        color:#fff;
        font-size:9px;
        font-weight:850;
    }

    .priority-pill {
        display:inline-flex;
        align-items:center;
        gap:4px;
        padding:5px 9px;
        border-radius:14px;
        font-size:9px;
        font-weight:850;
        white-space:nowrap;
    }

    .priority-pill.critical { background:#ffe5e9; color:#e51c3a; }
    .priority-pill.high { background:#fff0dc; color:#e77700; }
    .priority-pill.medium { background:#fff3d2; color:#b77a00; }
    .priority-pill.low { background:#edf1f6; color:#65738a; }

    .due-cell {
        min-height:30px;
        border-bottom:1px solid #edf0f5;
        font-size:9px;
        line-height:1.25;
        padding:3px 6px;
        box-sizing:border-box;
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
        padding:4px 7px;
        border-radius:12px;
        font-size:9px;
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

    .case-row .badge {
        margin-top:1px;
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


@st.cache_data(ttl=TASK_CACHE_TTL, show_spinner=False)
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


def clear_task_cache():
    """Invalidate the short-lived task read cache after task mutations."""
    try:
        fetch_tasks.clear()
    except Exception:
        pass


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

    # SLA duration is measured from the moment the case entered its
    # current station. station_started_at is therefore authoritative.
    # created_at is only a legacy-data fallback when that field is missing.
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

    # SLA warning is strictly time-based: final 20% BEFORE the SLA ends.
    # Once elapsed time reaches the SLA, the case is past due instead.
    nearing_due = (remaining > 0) and (remaining <= sla * 0.20)
    past_due = remaining <= 0

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
        "nearing_due": nearing_due,
        "past_due": past_due,
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
# Version 10 resets existing demonstration cases to 00:00:00 on first load.
MOCK_DATA_VERSION = 10


@st.cache_resource(show_spinner=False)
def seed_mock_cases(force=False):
    existing = col(TASKS_COLLECTION).count_documents(
        {"is_mock": True}
    )

    # One-time migration for mock data created by an earlier version.
    # This resets demonstration durations to 00:00:00 without doing so
    # again on every normal Streamlit rerun.
    if existing and not force:
        reset_filter = {
            "is_mock": True,
            "mock_data_version": {"$ne": MOCK_DATA_VERSION},
            "case_number": {"$not": {"$regex": "^SIM-"}},
        }
        needs_reset = col(TASKS_COLLECTION).count_documents(reset_filter)

        if needs_reset:
            # Reset every demonstration case from one common timestamp.
            # update_many is substantially faster than one database write per case.
            reset_now = utc_now()
            col(TASKS_COLLECTION).update_many(
                reset_filter,
                {"$set": {
                    "created_at": reset_now,
                    "station_started_at": reset_now,
                    "due_date": reset_now + timedelta(days=2),
                    "last_update": reset_now,
                    "mock_data_version": MOCK_DATA_VERSION,
                }},
            )
            clear_task_cache()

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

            # All mock cases use a common demonstration due date:
            # exactly two days from the time the mock dataset is seeded.
            due = now + timedelta(days=2)

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
    """Create missing alerts with minimal MongoDB round trips.

    Alert evaluation is intentionally throttled because Duration is updated
    entirely in the browser. Rapid station clicks should not cause repeated
    MongoDB alert reads/writes while preserving alert creation on normal
    dashboard interactions.
    """
    now_epoch = time.time()
    last_scan = float(st.session_state.get("_last_alert_scan", 0.0) or 0.0)
    if now_epoch - last_scan < ALERT_SCAN_MIN_INTERVAL:
        return
    st.session_state["_last_alert_scan"] = now_epoch

    now = utc_now()
    candidates = []

    for task in tasks:
        state = calculate_state(task, now)
        if not state["critical"]:
            continue

        if state["priority_account"]:
            alert_type = "PRIORITY_ACCOUNT"
            message = (
                f"High-priority account detected: "
                f"{text(task.get('account_name'))} "
                f"— Case {text(task.get('case_number'))}"
            )
        elif state["breached"]:
            continue
        else:
            alert_type = "NEARING_DUE"
            message = (
                f"Case nearing SLA: {text(task.get('case_number'))} "
                f"— {text(task.get('account_name'))}"
            )

        candidates.append((task, alert_type, message))

    if not candidates:
        return

    task_ids = [str(task["_id"]) for task, _, _ in candidates]
    try:
        existing = {
            (str(doc.get("task_id")), doc.get("alert_type"))
            for doc in col(ALERT_COLLECTION).find(
                {
                    "acknowledged": False,
                    "task_id": {"$in": task_ids},
                },
                {"task_id": 1, "alert_type": 1},
            )
        }
    except Exception:
        existing = set()

    docs = []
    created_at = utc_now()

    for task, alert_type, message in candidates:
        key = (str(task["_id"]), alert_type)
        if key in existing:
            continue
        docs.append({
            "task_id": str(task["_id"]),
            "case_number": task.get("case_number"),
            "station": station_name(task.get("department")),
            "account_name": task.get("account_name"),
            "alert_type": alert_type,
            "message": message,
            "created_at": created_at,
            "acknowledged": False,
        })

    if docs:
        try:
            col(ALERT_COLLECTION).insert_many(docs, ordered=False)
        except Exception:
            pass

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

        clear_task_cache()
        return True

    except Exception:
        return False


# ============================================================
# HEADER
# ============================================================

# The uploaded 661x43 reference is used as the exact visual header artwork.
# Streamlit controls are transparent/overlaid so search and Settings remain fully functional.
with st.container(key="caseflow_header_shell"):

    header_cols = st.columns([1, 1, 1])

    with header_cols[0]:
        st.empty()

    with header_cols[1]:
        search = st.text_input(
            "Search",
            value=st.session_state["search"],
            placeholder="Search case number, subject, name, or issue...",
            key="header_search",
            label_visibility="collapsed",
        )
        st.session_state["search"] = search

    with header_cols[2]:
        if st.button(
            "⚙",
            key="open_settings",
            use_container_width=True,
            help="Settings",
        ):
            st.session_state["show_settings"] = True


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
                    "Changing ACCESS_CODE or TOKEN_SECRET in Streamlit Secrets invalidates previously stored browser authorization."
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

@st.fragment
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

    # Compute each case state once and group cases by station in the same pass.
    # This avoids repeated full-list scans every time a station is clicked.
    states = {}
    tasks_by_station = {station: [] for station in STATIONS}
    states_by_station = {station: [] for station in STATIONS}

    for task in tasks:
        task_state = calculate_state(task, now)
        task_id = str(task["_id"])
        states[task_id] = task_state
        task_station = station_name(task.get("department"))
        if task_station in tasks_by_station:
            tasks_by_station[task_station].append(task)
            states_by_station[task_station].append(task_state)

    # --------------------------------------------------------
    # STATION TILES
    # --------------------------------------------------------

    station_cols = st.columns(5)

    for index, station in enumerate(STATIONS):
        station_tasks = tasks_by_station[station]
        station_states = states_by_station[station]

        # Tile flashing is based ONLY on elapsed time in the CURRENT station.
        # A priority account is still marked CRITICAL and can generate alerts,
        # but it must NOT make a station tile blink by itself.
        #
        # "Nearing due" means the case has entered the final 20% of the
        # station SLA, while it has not yet breached the SLA.
        #
        # The duration clock itself starts at station_started_at. When a case
        # is transferred, transfer_case() resets station_started_at to the
        # transfer time, so the SLA clock starts over in the destination
        # station.
        sla_seconds = STATIONS[station]["sla_minutes"] * 60
        # A station warning is triggered by any case that has reached
        # the warning threshold OR has already breached the station SLA.
        # This keeps the visual warning tied to the same cases that receive
        # the red duration indicator in the table.
        # Nearing due = final 20% of the SLA, strictly BEFORE breach.
        # Past due = SLA has already elapsed.
        nearing = sum(
            1
            for state in station_states
            if state.get("nearing_due", False)
        )
        past_due = sum(
            1
            for state in station_states
            if state.get("past_due", False)
        )
        # A tile flashes ONLY while at least one case is in the final
        # 20% of this station's SLA. Priority-account status alone does not
        # trigger the tile animation.
        warning_ack_until = st.session_state.setdefault(
            "station_warning_ack_until",
            {},
        )

        warning_silenced = st.session_state.setdefault(
            "station_warning_silenced",
            set(),
        )

        if nearing == 0:
            warning_ack_until.pop(station, None)
            warning_silenced.discard(station)

        ack_until = float(
            warning_ack_until.get(station, 0.0) or 0.0
        )
        now_epoch = time.time()

        # A warning tile flashes only until the user clicks it.
        # Clicking the tile silences the flashing immediately and keeps it
        # silent until the current nearing-due condition clears.
        flash_tile = (
            nearing > 0
            and station not in warning_silenced
        )

        config = STATIONS[
            station
        ]

        with station_cols[index]:
            slug = {
                "CARE": "care",
                "ARCH": "arch",
                "PET": "pet",
                "SUPPLY CHAIN": "supply",
                "ONSITE": "onsite",
            }[station]
            icon = config.get("icon", "•")
            sla = config["sla_minutes"]
            sla_text = f"{sla} mins" if sla < 60 else f"{sla // 60} hour" + ("s" if sla != 60 else "")
            critical_class = " critical" if flash_tile else ""
            selected_class = " selected" if selected == station else ""
            alert_icon = (
                '<div class="station-alert-icon" aria-label="SLA warning">!</div>'
                if flash_tile else ""
            )

            # The visual card remains the reference design. A transparent
            # Streamlit button is layered over the entire card so ONE click
            # anywhere on the tile changes the station filter.
            with st.container(key=f"station_wrap_{slug}"):
                # Keep this HTML as one physical markdown line. Streamlit's
                # Markdown parser can otherwise interpret indented multiline
                # HTML as a code block and expose the raw tags.
                station_html = (
                    f'<div class="station-card-visual {slug}{critical_class}{selected_class}" '
                    f'data-station="{html.escape(station)}" '
                    f'data-warning-stop="{ack_until if ack_until > time.time() else 0:.3f}">'
                    f'{alert_icon}'
                    f'<div class="station-icon-circle">{html.escape(icon)}</div>'
                    f'<div class="station-copy">'
                    f'<div class="station-card-title">{html.escape(station)}</div>'
                    f'<div class="station-count-line">'
                    f'<span class="station-count">{len(station_tasks)}</span>'
                    f'<span class="station-active">Active Cases</span>'
                    f'</div></div>'
                    f'<div class="station-arrow">›</div>'
                    f'<div class="station-warning{" active" if nearing > 0 else ""}">◷ &nbsp; {nearing} nearing due{("  •  " + str(past_due) + " past due") if past_due else ""}</div>'
                    f'<div class="station-sla-ref">◷ &nbsp; Max Timeframe: <strong>{html.escape(sla_text)}</strong></div>'
                    f'</div>'
                )
                st.markdown(station_html, unsafe_allow_html=True)
                if st.button(
                    f"Select {station}",
                    key=f"station_{station}",
                    use_container_width=True,
                ):
                    if nearing > 0:
                        # Stop the tile warning immediately on click.
                        # Keep it silent until the current nearing-due condition
                        # clears and a new warning cycle begins.
                        warning_ack_until[station] = 0.0
                        warning_silenced.add(station)
                        acknowledge_station_alerts(station)

                    # A single click changes the filter and reruns ONLY
                    # the dashboard fragment. This keeps station switching
                    # fast without refreshing the rest of the application.
                    st.session_state["selected_station"] = station
                    st.rerun(scope="fragment")

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
            <span class="station-pill"
                  style="background:{STATIONS.get(selected, STATIONS["CARE"])["soft"]};
                         color:{STATIONS.get(selected, STATIONS["CARE"])["accent"]};
                         border:1px solid {STATIONS.get(selected, STATIONS["CARE"])["accent"]}33;">
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
        [1.05, 2.25, 1.15, 1.35, 1.35, 1.10, 1.00]
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
            [1.05, 2.25, 1.15, 1.35, 1.35, 1.10, 1.00]
        )

        with row[0]:

            case_station = station_name(task.get("department"))
            case_slug = {
                "CARE": "care",
                "ARCH": "arch",
                "PET": "pet",
                "SUPPLY CHAIN": "supply",
                "ONSITE": "onsite",
            }.get(case_station, "care")

            with st.container(key=f"case_cell_{case_slug}_{task_id}"):
                if st.button(
                    text(task.get("case_number")),
                    key=f"case_{task_id}",
                    use_container_width=True,
                ):
                    # Open the dialog directly from the user's click.
                    # There is no periodic dashboard rerun.
                    case_details(task_id)

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

            priority_slug = {
                "Critical": "critical",
                "High": "high",
                "Medium": "medium",
                "Low": "low",
            }.get(priority_text, "low")

            priority_icon = {
                "Critical": "●",
                "High": "●",
                "Medium": "●",
                "Low": "●",
            }.get(priority_text, "●")

            st.markdown(
                f"""
                <div class="case-row">
                    <span class="priority-pill {priority_slug}">
                        {priority_icon} {html.escape(priority_text)}
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with row[3]:

            assigned = text(
                task.get(
                    "assigned_to",
                    "Unassigned"
                )
            ) or "Unassigned"

            initials = "".join(
                part[0]
                for part in assigned.split()
                if part
            )[:2].upper()

            avatar_palette = [
                "#e94b68",
                "#3d8fe5",
                "#70b942",
                "#25a7d8",
                "#8a63df",
                "#7083a2",
            ]

            avatar_color = avatar_palette[
                sum(ord(ch) for ch in assigned)
                % len(avatar_palette)
            ]

            st.markdown(
                f"""
                <div class="agent-cell">
                    <span class="agent-avatar"
                          style="background:{avatar_color};">
                        {html.escape(initials)}
                    </span>
                    <span>{html.escape(assigned)}</span>
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
                <div class="due-cell"
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

            # Duration is the time spent in the CURRENT station.
            # station_started_at is reset whenever the case enters/transfers
            # into a station. Legacy records without it fall back to created_at.
            started = iso_z(
                task.get("station_started_at")
                or task.get("created_at")
            )

            # Browser-side timer:
            # duration changes every second according to the user's own
            # PC/browser clock and does not require a Streamlit rerun.
            sla_for_case = STATIONS.get(
                case_station,
                STATIONS["CARE"],
            )["sla_minutes"] * 60

            # Duration color follows elapsed SLA progress:
            # green 0-50%, yellow 50-80%, red 80-100% and past due.
            warning_threshold_seconds = sla_for_case * 0.80
            elapsed_ratio = (state["elapsed"] / sla_for_case) if sla_for_case else 1.0
            if elapsed_ratio < 0.50:
                duration_color_class = "duration-green"
            elif elapsed_ratio < 0.80:
                duration_color_class = "duration-yellow"
            else:
                duration_color_class = "duration-red"

            warning_ack_map = st.session_state.get(
                "station_warning_ack_until",
                {},
            )
            case_ack_until = float(
                warning_ack_map.get(case_station, 0.0) or 0.0
            )

            # The visual warning is handled entirely by browser-side JS so
            # the Duration can blink without rerunning the dashboard.
            st.markdown(
                f"""
                <div class="case-row"
                     style="font-weight:700;
                            color:{'#e51c3a' if state['critical'] else '#53637f'};
                            padding-top:4px;">
                    <div class="duration-warning-wrap {duration_color_class}"
                         data-warning-threshold="{warning_threshold_seconds:.3f}"
                         data-sla-seconds="{sla_for_case:.3f}"
                         data-warning-stop="{case_ack_until:.3f}"
                         data-duration-start="{html.escape(started)}">
                        <span
                            data-duration-start="{html.escape(started)}"
                            data-duration-live="1">
                            {duration_string(state['elapsed'])}
                        </span>
                    </div>
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
                const nodes = document.querySelectorAll('[data-duration-live="1"]');
                const nowMs = Date.now();

                nodes.forEach(function (node) {
                    const wrap = node.closest('.duration-warning-wrap');
                    const raw = node.getAttribute("data-duration-start");
                    if (!raw || !wrap) return;

                    const startedMs = Date.parse(raw);
                    if (!Number.isFinite(startedMs)) return;

                    const elapsed = Math.max(0, Math.floor((nowMs - startedMs) / 1000));
                    const sla = Number(wrap.getAttribute("data-sla-seconds") || "0");
                    if (!sla) return;

                    const h = Math.floor(elapsed / 3600);
                    const m = Math.floor((elapsed % 3600) / 60);
                    const sec = elapsed % 60;

                    node.textContent =
                        String(h).padStart(2, "0") + ":" +
                        String(m).padStart(2, "0") + ":" +
                        String(sec).padStart(2, "0");

                    const ratio = elapsed / sla;
                    wrap.classList.toggle("duration-green", ratio < 0.50);
                    wrap.classList.toggle("duration-yellow", ratio >= 0.50 && ratio < 0.80);
                    wrap.classList.toggle("duration-red", ratio >= 0.80);
                    wrap.classList.toggle("duration-warning-active", ratio >= 0.80 && ratio < 1.0);
                });
            }

            function updateWarningAnimations() {
                const nowMs = Date.now();

                document.querySelectorAll('.station-card-visual[data-warning-stop]').forEach(function (card) {
                    const stopAt = Number(card.getAttribute("data-warning-stop") || "0") * 1000;
                    if (stopAt > 0 && nowMs >= stopAt) {
                        card.classList.remove("critical");
                        const icon = card.querySelector(".station-alert-icon");
                        if (icon) icon.classList.add("warning-muted");
                    }
                });
            }

            /* Make the selected station respond visually BEFORE the
                   Streamlit fragment finishes rerendering. */
                document.querySelectorAll(
                    '[class*="st-key-station_"] button'
                ).forEach(function (button) {
                    if (button.__fastStationBound) return;
                    button.__fastStationBound = true;
                    button.addEventListener("pointerdown", function () {
                        const keyHost = button.closest('[class*="st-key-station_"]');
                        if (!keyHost) return;
                        const match = keyHost.className.match(/st-key-station_([^ ]+)/);
                        const stationMap = {
                            CARE:"CARE", ARCH:"ARCH", PET:"PET",
                            SUPPLY:"SUPPLY CHAIN", ONSITE:"ONSITE"
                        };
                        const station = match ? stationMap[match[1].toUpperCase()] : null;
                        if (!station) return;
                        document.querySelectorAll(
                            ".station-card-visual[data-station]"
                        ).forEach(function (card) {
                            const isSelected =
                                card.getAttribute("data-station") === station;

                            card.classList.toggle("selected", isSelected);

                            /* Stop flashing immediately — do not wait for the
                               fragment rerender. */
                            if (isSelected) {
                                card.classList.remove("critical");
                                card.classList.add("warning-muted");
                                const icon = card.querySelector(".station-alert-icon");
                                if (icon) {
                                    icon.style.animation = "none";
                                    icon.style.opacity = "1";
                                }
                                card.style.animation = "none";
                            }
                        });

                        /* Give the browser one paint before Streamlit starts
                           replacing the fragment. This makes the visual tile
                           switch feel immediate instead of waiting on Python. */
                        requestAnimationFrame(function () {
                            document.querySelectorAll(
                                '[data-testid="stStatusWidget"], ' +
                                '[data-testid="stSpinner"], ' +
                                '.stSpinner'
                            ).forEach(function (el) {
                                el.style.opacity = "0";
                                el.style.pointerEvents = "none";
                            });
                        });
                    }, {passive:true});
                });
            }

            updateDurations();
            updateWarningAnimations();

            if (!window.__taskTrackerDurationTimer) {
                window.__taskTrackerDurationTimer =
                    setInterval(
                        function () {
                            updateDurations();
                            updateWarningAnimations();
                        },
                        1000
                    );
            }

        })();
        </script>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# REAL-TIME ALERT MONITOR
# ============================================================
# Duration is calculated in the browser every second. This lightweight
# fragment independently evaluates the same SLA state on the server so
# MongoDB Alert_Collection is updated in near real time without rerunning
# the full dashboard or interrupting station switching.
@st.fragment(run_every="1s")
def realtime_alert_monitor():
    try:
        all_tasks = fetch_tasks(search="", station=None, limit=300)
        scan_alerts(all_tasks)
    except Exception:
        # Monitoring must never interfere with the main dashboard.
        pass


# ============================================================
# INITIAL MOCK DATA
# ============================================================

# Seed before the first dashboard render so the first view already
# contains the mock cases. This check runs once per normal app render
# and does not create a background refresh loop.
# Seed/mock migration is cached as a resource so normal fragment reruns
# do not repeatedly query MongoDB for the mock-data count.
seed_mock_cases()


# Render the dashboard once. No run_every / autorefresh is used on the main dashboard.
dashboard_fragment()

# Start the independent one-second alert monitor after mock data and the
# initial dashboard are ready. It does not rerender the main dashboard.
realtime_alert_monitor()


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
