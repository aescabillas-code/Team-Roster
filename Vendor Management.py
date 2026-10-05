"""
TASKS MONITORING TRACKER
Single-file Streamlit application.


UI is designed to closely match the supplied dashboard reference:
- White/light gray background
- Dark navy typography
- CSS-recreated HPE Caseflow header interface
- Integrated live search bar
- Five pastel station tiles
- Borderless active-case table
- Right-side case-detail dialog
- Settings control only (no alert bell / no profile)
- Admin Settings supports Excel case import and vendor synchronization
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
from pymongo import MongoClient, ASCENDING, DESCENDING, ReplaceOne
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
KB_COLLECTION = "Knowledge_Base_Collection"
SOP_COLLECTION = "SOP_Collection"


# Performance tuning: short cache keeps station switches responsive while preserving near-real-time data.
TASK_CACHE_TTL = 0.5
KB_CACHE_TTL = 5.0
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
        col(KB_COLLECTION).create_index([("title", ASCENDING)])
        col(KB_COLLECTION).create_index([("category", ASCENDING)])
        col(SOP_COLLECTION).create_index([("title", ASCENDING)])
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


    /* HEADER — CSS recreation of the supplied HPE Caseflow reference.
       No uploaded image is used. The logo, teal field, diagonal wave,
       search field and settings control are rendered as HTML/CSS. */
    .caseflow-header-shell,
    [class*="st-key-caseflow_header_shell"] {
        position:relative !important;
        height:62px !important;
        min-height:62px !important;
        width:100% !important;
        padding:0 !important;
        margin:0 0 18px 0 !important;
        overflow:hidden !important;
        border:1px solid #8aa4a3 !important;
        border-radius:1px !important;
        box-sizing:border-box !important;
        background:
            linear-gradient(101deg,
                #003f42 0%,
                #004b4c 48%,
                #00625f 72%,
                #00736a 100%) !important;
    }


    .caseflow-header-shell::before,
    [class*="st-key-caseflow_header_shell"]::before {
        content:"" !important;
        position:absolute !important;
        z-index:0 !important;
        top:-18px !important;
        right:-3% !important;
        width:49% !important;
        height:95px !important;
        background:
            linear-gradient(132deg,
                transparent 0%,
                rgba(0,150,137,.18) 27%,
                rgba(0,199,161,.30) 45%,
                rgba(0,103,101,.55) 65%,
                rgba(0,57,63,.15) 100%) !important;
        clip-path:polygon(28% 0,100% 0,100% 100%,0 100%) !important;
        pointer-events:none !important;
    }


    .caseflow-header-shell::after,
    [class*="st-key-caseflow_header_shell"]::after {
        content:"" !important;
        position:absolute !important;
        z-index:0 !important;
        right:2% !important;
        top:-7px !important;
        width:40% !important;
        height:82px !important;
        background:
            repeating-linear-gradient(
                154deg,
                transparent 0 10px,
                rgba(103,240,202,.16) 11px 12px,
                transparent 13px 20px
            ) !important;
        transform:skewX(-17deg) !important;
        opacity:.65 !important;
        pointer-events:none !important;
    }


    [class*="st-key-caseflow_header_shell"] > div {
        position:relative !important;
        z-index:2 !important;
    }


    /* HEADER HIT-AREA FIX
       Decorative/header layers must never sit above the native controls.
       The search field and Settings gear receive their own full-size,
       high-z-index hit areas so the entire visible control is clickable,
       not just its lower portion. */
    [class*="st-key-caseflow_header_shell"] {
        isolation:isolate !important;
    }


    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] {
        z-index:100 !important;
        pointer-events:none !important;
    }


    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] > div {
        pointer-events:none !important;
    }


    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] > div:nth-child(2),
    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] > div:nth-child(3) {
        pointer-events:auto !important;
        z-index:200 !important;
    }


    [class*="st-key-caseflow_header_shell"] [data-testid="stTextInput"],
    [class*="st-key-caseflow_header_shell"] [data-testid="stTextInput"] > div,
    [class*="st-key-caseflow_header_shell"] [data-testid="stTextInput"] input {
        position:relative !important;
        z-index:201 !important;
        pointer-events:auto !important;
    }


    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] > div:nth-child(3),
    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] > div:nth-child(3) > div,
    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] > div:nth-child(3) button {
        pointer-events:auto !important;
    }


    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] {
        position:absolute !important;
        inset:0 !important;
        width:100% !important;
        height:62px !important;
        min-height:62px !important;
        margin:0 !important;
        padding:0 !important;
        display:block !important;
    }


    /* Left HPE lockup */
    [class*="st-key-caseflow_header_shell"] .caseflow-brand {
        position:absolute !important;
        left:12px !important;
        top:7px !important;
        height:48px !important;
        display:flex !important;
        align-items:center !important;
        gap:6px !important;
        color:#fff !important;
        pointer-events:none !important;
        white-space:nowrap !important;
    }


    .caseflow-hpe-symbol {
        width:23px !important;
        height:23px !important;
        position:relative !important;
        flex:0 0 23px !important;
    }


    .caseflow-hpe-symbol::before,
    .caseflow-hpe-symbol::after {
        content:"" !important;
        position:absolute !important;
        left:1px !important;
        width:21px !important;
        height:7px !important;
        border:2px solid #fff !important;
        transform:skewY(-25deg) rotate(-25deg) !important;
        border-radius:1px !important;
    }


    .caseflow-hpe-symbol::before { top:3px !important; }
    .caseflow-hpe-symbol::after { top:12px !important; }


    .caseflow-hpe-copy {
        display:flex !important;
        flex-direction:column !important;
        justify-content:center !important;
        line-height:1 !important;
    }


    .caseflow-hpe-word {
        font-size:18px !important;
        line-height:16px !important;
        font-weight:800 !important;
        letter-spacing:-.3px !important;
        color:#fff !important;
    }


    .caseflow-hpe-tagline {
        margin-top:4px !important;
        font-size:6px !important;
        line-height:5px !important;
        font-weight:500 !important;
        color:rgba(255,255,255,.84) !important;
        letter-spacing:-.05px !important;
    }


    .caseflow-divider {
        width:1px !important;
        height:36px !important;
        margin-left:8px !important;
        background:rgba(255,255,255,.72) !important;
    }


    .caseflow-title {
        font-size:18px !important;
        line-height:21px !important;
        font-weight:750 !important;
        color:#fff !important;
        letter-spacing:-.2px !important;
    }


    /* The Streamlit columns are used only as functional control hosts. */
    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] > div:nth-child(1) {
        position:absolute !important;
        left:0 !important;
        top:0 !important;
        width:31% !important;
        height:62px !important;
        padding:0 !important;
        margin:0 !important;
        min-width:0 !important;
    }


    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] > div:nth-child(2) {
        position:absolute !important;
        left:34.2% !important;
        top:13px !important;
        width:44% !important;
        height:36px !important;
        min-height:36px !important;
        z-index:200 !important;
        max-width:360px !important;
        min-width:220px !important;
        padding:0 !important;
        margin:0 !important;
    }


    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] > div:nth-child(3) {
        position:absolute !important;
        right:1.1% !important;
        top:7px !important;
        width:48px !important;
        max-width:48px !important;
        min-width:48px !important;
        height:48px !important;
        min-height:48px !important;
        padding:0 !important;
        margin:0 !important;
    }


    [class*="st-key-caseflow_header_shell"] div[data-testid="stTextInput"] {
        width:100% !important;
        margin:0 !important;
        padding:0 !important;
    }


    [class*="st-key-caseflow_header_shell"] div[data-testid="stTextInput"] > div {
        width:100% !important;
        min-height:0 !important;
        margin:0 !important;
        padding:0 !important;
    }


    [class*="st-key-caseflow_header_shell"] div[data-testid="stTextInput"] input {
        width:100% !important;
        height:36px !important;
        min-height:36px !important;
        box-sizing:border-box !important;
        border:0 !important;
        outline:none !important;
        border-radius:8px !important;
        background:#fff !important;
        color:#244a55 !important;
        font-size:11px !important;
        font-weight:500 !important;
        line-height:36px !important;
        padding:0 12px 0 30px !important;
        box-shadow:0 1px 4px rgba(0,0,0,.12) !important;
        background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='13' height='13' viewBox='0 0 24 24' fill='none' stroke='%23728a98' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='7'/%3E%3Cpath d='m20 20-4-4'/%3E%3C/svg%3E") !important;
        background-position:10px center !important;
        background-repeat:no-repeat !important;
        background-size:15px 15px !important;
    }


    [class*="st-key-caseflow_header_shell"] div[data-testid="stTextInput"] input::placeholder {
        color:#748a98 !important;
        opacity:1 !important;
        font-size:11px !important;
    }


    [class*="st-key-caseflow_header_shell"] div[data-testid="stTextInput"] input:focus {
        box-shadow:0 0 0 1px rgba(112,235,207,.75), 0 1px 4px rgba(0,0,0,.12) !important;
    }


    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] > div:nth-child(3) button {
        width:48px !important;
        height:48px !important;
        min-width:48px !important;
        min-height:48px !important;
        max-width:48px !important;
        padding:0 !important;
        margin:0 !important;
        border:1px solid rgba(255,255,255,.60) !important;
        border-radius:9px !important;
        background:rgba(0,53,57,.28) !important;
        box-shadow:none !important;
        color:transparent !important;
        font-size:0 !important;
        cursor:pointer !important;
        position:relative !important;
    }


    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] > div:nth-child(3) button::before {
        content:"⚙" !important;
        position:absolute !important;
        inset:0 !important;
        display:flex !important;
        align-items:center !important;
        justify-content:center !important;
        color:#fff !important;
        font-size:21px !important;
        line-height:1 !important;
    }


    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] > div:nth-child(3) button:hover {
        background:rgba(255,255,255,.12) !important;
        border-color:rgba(255,255,255,.85) !important;
    }


    [class*="st-key-caseflow_header_shell"] [data-testid="stTextInput"] label {
        display:none !important;
    }


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
        border-radius:9px !important;
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




    /* MOBILE LAYOUT — header, station cards and case table remain usable on phones. */
    /* INTEGRATED KNOWLEDGE BASE */
    .kb-panel{background:#f7f9fc;border:1px solid #e3e9f1;border-radius:17px;padding:18px;margin:8px 0 12px}
    .kb-panel-header{display:flex;align-items:center;justify-content:space-between;gap:10px}
    .kb-title{color:#122442;font-size:18px;font-weight:850}
    .kb-subtitle{color:#718099;font-size:12px;line-height:1.45;margin-top:5px}
    .kb-auto-badge{display:inline-flex;padding:5px 9px;border-radius:12px;background:#e1f7f2;color:#007765;font-size:10px;font-weight:800}
    .kb-answer-card{background:#fff;border:1px solid #dce5ef;border-radius:13px;padding:14px;margin-top:12px}
    .kb-answer-card.best{border:2px solid #6d5ce7;box-shadow:0 5px 18px rgba(70,57,160,.08)}
    .kb-answer-label{color:#6756dc;font-size:10px;font-weight:850;text-transform:uppercase;letter-spacing:.4px;margin-bottom:5px}
    .kb-result-title{color:#182b4c;font-size:14px;font-weight:800;margin-bottom:5px}
    .kb-result-text{color:#5d6c82;font-size:12px;line-height:1.5}
    .kb-meta{color:#8491a4;font-size:10px;margin-top:8px}
    .kb-source-pill{display:inline-block;background:#edf2f8;color:#5d6c82;border-radius:10px;padding:3px 7px;font-size:9px;font-weight:750;margin-right:4px}
    .kb-empty{color:#718099;font-size:12px;padding:10px 0}


    @media(max-width:700px) {
        .block-container {
            padding:10px 10px 24px !important;
        }


        .caseflow-header-shell,
        [class*="st-key-caseflow_header_shell"] {
            height:94px !important;
            min-height:94px !important;
            margin-bottom:12px !important;
        }


        [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] {
            height:94px !important;
            min-height:94px !important;
        }


        [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] > div:nth-child(1) {
            left:0 !important;
            top:0 !important;
            width:72% !important;
            height:48px !important;
        }


        [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] > div:nth-child(2) {
            left:10px !important;
            top:52px !important;
            width:calc(100% - 70px) !important;
            max-width:none !important;
            min-width:0 !important;
        }


        [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"] > div:nth-child(3) {
            right:8px !important;
            top:6px !important;
            width:48px !important;
            max-width:48px !important;
            min-width:48px !important;
            height:48px !important;
        }


        [class*="st-key-caseflow_header_shell"] .caseflow-brand {
            left:10px !important;
            top:5px !important;
            height:42px !important;
        }


        .caseflow-hpe-symbol {
            width:27px !important;
            height:27px !important;
            flex-basis:27px !important;
        }


        .caseflow-hpe-symbol::before,
        .caseflow-hpe-symbol::after {
            width:25px !important;
        }


        .caseflow-hpe-word { font-size:16px !important; line-height:15px !important; }
        .caseflow-hpe-tagline { font-size:5px !important; line-height:6px !important; }
        .caseflow-divider { height:30px !important; margin-left:5px !important; }
        .caseflow-title { font-size:17px !important; line-height:20px !important; }


        [class*="st-key-caseflow_header_shell"] div[data-testid="stTextInput"] input {
            height:34px !important;
            min-height:34px !important;
            font-size:11px !important;
            line-height:34px !important;
        }


        /* Turn the five station columns into a compact two-column mobile grid. */
        [data-testid="stHorizontalBlock"]:has([class*="st-key-station_wrap_care"]) {
            display:grid !important;
            grid-template-columns:repeat(2,minmax(0,1fr)) !important;
            gap:9px !important;
        }


        [data-testid="stHorizontalBlock"]:has([class*="st-key-station_wrap_care"]) > div {
            width:auto !important;
            flex:unset !important;
            min-width:0 !important;
        }


        [class*="st-key-station_wrap_care"],
        [class*="st-key-station_wrap_arch"],
        [class*="st-key-station_wrap_pet"],
        [class*="st-key-station_wrap_supply"],
        [class*="st-key-station_wrap_onsite"] {
            min-height:145px !important;
        }


        .station-card-visual {
            height:145px !important;
            min-height:145px !important;
            padding:12px !important;
            border-radius:12px !important;
        }


        .station-icon-circle {
            width:46px !important;
            height:46px !important;
            left:12px !important;
            top:12px !important;
            font-size:22px !important;
        }


        .station-copy {
            left:70px !important;
            top:18px !important;
        }


        .station-card-title { font-size:14px !important; }
        .station-count { font-size:25px !important; }
        .station-active { font-size:10px !important; }
        .station-arrow { right:10px !important; top:17px !important; font-size:20px !important; }
        .station-warning { left:12px !important; bottom:32px !important; font-size:9px !important; }
        .station-sla-ref { left:12px !important; bottom:13px !important; font-size:9px !important; }
        .station-alert-icon { right:10px !important; top:64px !important; width:27px !important; height:27px !important; font-size:17px !important; }


        .cases-title { font-size:18px !important; }
        .station-pill { font-size:11px !important; padding:5px 10px !important; }


        /* Keep the essential case fields visible and prevent the table from
           becoming unusably narrow. Secondary fields are hidden on phones. */
        [data-testid="stHorizontalBlock"]:has([class*="st-key-case_cell_"]) > div:nth-child(4),
        [data-testid="stHorizontalBlock"]:has([class*="st-key-case_cell_"]) > div:nth-child(5) {
            display:none !important;
        }


        [data-testid="stHorizontalBlock"]:has([class*="st-key-case_cell_"]) {
            display:grid !important;
            grid-template-columns:1.2fr 2.1fr 1.15fr 1.05fr !important;
            gap:4px !important;
        }


        [data-testid="stHorizontalBlock"]:has([class*="st-key-case_cell_"]) > div {
            min-width:0 !important;
            width:auto !important;
            flex:unset !important;
        }


        .case-head, .case-row { font-size:9px !important; }
        [class*="st-key-case_cell_"] button { font-size:9px !important; padding:3px 5px !important; }
        .priority-pill { font-size:8px !important; padding:4px 5px !important; }
        .duration-warning-wrap { font-size:9px !important; }


        div[data-testid="stDialog"] > div {
            top:8px !important;
            right:8px !important;
            left:8px !important;
            width:calc(100vw - 16px) !important;
            max-width:calc(100vw - 16px) !important;
            height:calc(100vh - 16px) !important;
            max-height:calc(100vh - 16px) !important;
            border-radius:14px !important;
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
        "_id": 1, "case_number": 1, "subject": 1, "priority": 1,
        "account_priority": 1, "assigned_to": 1, "due_date": 1,
        "created_at": 1, "station_started_at": 1, "department": 1,
        "status": 1, "last_update": 1, "account_name": 1, "vendor": 1,
        "issue": 1, "description": 1, "notes": 1, "history": 1,
        "active": 1, "is_mock": 1, "source_type": 1, "case_type": 1,
        "category": 1, "contact_name": 1, "contact_number": 1,
        "email": 1, "site_location": 1, "product": 1, "serial_number": 1,
        "reference_number": 1, "resolution": 1, "next_action": 1,
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
        "Fulfillment technician request",
        "Hardware replacement",
        "Network equipment issue",
        "Site access request",
        "Installation support",
    ],
}

MOCK_NAMES = ["John Dela Cruz", "Maria Santos", "Anna Reyes", "Carlo Banaag", "Liza Tan"]
MOCK_ACCOUNTS = ["Marriott Hotel", "Hilton Group", "Accenture", "Microsoft", "Acme Corporation"]
MOCK_DATA_VERSION = 14

# Rich demonstration information shown inside Case Details.
MOCK_CASE_DETAILS = {
    "CARE": [
        {"case_type":"Guest Services / Maintenance","category":"Facilities","contact_name":"Daniel Wong","contact_number":"+63 917 555 0141","email":"daniel.wong@example.com","site_location":"Manila Bay Hotel • Room 1214","product":"Room HVAC / Thermostat","serial_number":"CARE-HVAC-1214","reference_number":"CARE-REQ-1214","issue":"Guest reports that the room air-conditioning is running but the room is not cooling.","description":"Guest confirmed the thermostat is set to 20°C. Airflow is present but remains warm. The room is occupied and the guest requested priority handling.","resolution":"Pending initial troubleshooting and maintenance validation.","next_action":"Verify thermostat mode, power cycle the unit, document the result, then route to the maintenance vendor if unresolved.","notes":"Guest requested an update before 9:00 PM."},
        {"case_type":"Facilities / Plumbing","category":"Maintenance","contact_name":"Maria Santos","contact_number":"+63 917 555 0142","email":"maria.santos@example.com","site_location":"Hilton Manila • Room 807","product":"Bathroom Plumbing","serial_number":"PLB-807-22","reference_number":"CARE-PLB-0807","issue":"Water is slowly leaking from the bathroom sink connection.","description":"A small continuous leak was reported under the sink. Guest placed a towel below the pipe while waiting for assistance.","resolution":"Pending fulfillment inspection.","next_action":"Confirm leak location and dispatch the appropriate maintenance resource.","notes":"No reported electrical hazard."},
        {"case_type":"Housekeeping Request","category":"Guest Services","contact_name":"Anna Reyes","contact_number":"+63 917 555 0143","email":"anna.reyes@example.com","site_location":"Accenture Guest Suite • Room 510","product":"Housekeeping Service","serial_number":"N/A","reference_number":"CARE-HK-0510","issue":"Guest requested additional towels and two bottles of water.","description":"Routine guest-service request for additional room supplies.","resolution":"Pending housekeeping fulfillment.","next_action":"Coordinate with housekeeping and confirm completion with the guest.","notes":"Standard request; no escalation required."},
        {"case_type":"Access / Door Hardware","category":"Security & Facilities","contact_name":"Carlo Banaag","contact_number":"+63 917 555 0144","email":"carlo.banaag@example.com","site_location":"Microsoft Executive Floor • Room 1502","product":"Electronic Door Lock","serial_number":"LOCK-1502-88","reference_number":"CARE-LOCK-1502","issue":"Electronic room lock intermittently rejects the access card.","description":"Guest reports two failed card attempts followed by one successful entry. Battery status is unknown.","resolution":"Pending lock inspection.","next_action":"Check lock battery and access-card reader, then test with a validated credential.","notes":"Guest is currently inside the room."},
        {"case_type":"In-Room Entertainment","category":"Guest Services","contact_name":"Liza Tan","contact_number":"+63 917 555 0145","email":"liza.tan@example.com","site_location":"Acme Corporation Hotel Block • Room 903","product":"IPTV / Room TV","serial_number":"TV-903-441","reference_number":"CARE-TV-0903","issue":"Television displays a no-signal message on all channels.","description":"Power and HDMI connections were checked by the guest. The issue remains after restarting the TV.","resolution":"Pending remote/basic troubleshooting.","next_action":"Validate room network/TV input configuration and escalate to the entertainment support vendor if needed.","notes":"Guest requested a callback after troubleshooting."}],
    "ARCH": [
        {"case_type":"Archive Retrieval","category":"Records Management","contact_name":"John Dela Cruz","contact_number":"+63 917 555 0241","email":"john.delacruz@example.com","site_location":"Manila Records Center","product":"Archive Repository","serial_number":"N/A","reference_number":"ARCH-RET-001","issue":"Historical contract record requested for retrieval.","description":"Requester needs a copy of a historical contract and provided the account name and approximate document year.","resolution":"Pending archive index search.","next_action":"Search by record identifier, account and date range, then document the retrieval result.","notes":"Requester indicated the document is needed for an audit review."},
        {"case_type":"Document Indexing","category":"Records Management","contact_name":"Maria Santos","contact_number":"+63 917 555 0242","email":"maria.santos@example.com","site_location":"Cavite Archive Hub","product":"Document Index","serial_number":"N/A","reference_number":"ARCH-IDX-002","issue":"A recently uploaded document is not appearing in the archive search results.","description":"Document metadata appears complete, but the record cannot be located using the expected title and reference number.","resolution":"Pending index validation.","next_action":"Validate metadata and indexing status, then reprocess the record if required.","notes":"Check for duplicate document identifiers before reprocessing."},
        {"case_type":"Historical Record Access","category":"Access Control","contact_name":"Anna Reyes","contact_number":"+63 917 555 0243","email":"anna.reyes@example.com","site_location":"Quezon City Records Office","product":"Archive Portal","serial_number":"N/A","reference_number":"ARCH-ACC-003","issue":"Requester cannot open a restricted historical record.","description":"The record is visible in search results but access is denied when the requester attempts to open it.","resolution":"Pending permission validation.","next_action":"Confirm requester authorization and the record's access classification before escalation.","notes":"Do not bypass archive permissions."},
        {"case_type":"Metadata Correction","category":"Records Management","contact_name":"Carlo Banaag","contact_number":"+63 917 555 0244","email":"carlo.banaag@example.com","site_location":"Pasig Archive Hub","product":"Archive Metadata","serial_number":"N/A","reference_number":"ARCH-META-004","issue":"Archive record contains an incorrect date in its metadata.","description":"Requester supplied supporting documentation showing the correct record date.","resolution":"Pending validation of source documentation.","next_action":"Validate the supporting document and update metadata according to the approved process.","notes":"Retain an audit trail for the metadata change."},
        {"case_type":"Retention Request","category":"Records Management","contact_name":"Liza Tan","contact_number":"+63 917 555 0245","email":"liza.tan@example.com","site_location":"Makati Records Office","product":"Retention Schedule","serial_number":"N/A","reference_number":"ARCH-RET-005","issue":"Business user is asking whether a record is eligible for retention review.","description":"The requester supplied the record type and approximate creation date and is asking for the applicable retention treatment.","resolution":"Pending policy validation.","next_action":"Check the applicable retention schedule and document the approved disposition path.","notes":"Final disposition must follow the approved records policy."}],
    "PET": [
        {"case_type":"Pet Registration","category":"Pet Services","contact_name":"John Dela Cruz","contact_number":"+63 917 555 0341","email":"john.delacruz@example.com","site_location":"Marriott Hotel • Guest Services","product":"Pet Registration","serial_number":"N/A","reference_number":"PET-REG-001","issue":"Guest needs to register a pet before check-in.","description":"Guest provided the pet type and requested confirmation of registration requirements and applicable policy documentation.","resolution":"Pending registration validation.","next_action":"Confirm account details, required documentation and current pet registration procedure.","notes":"Customer requested written confirmation of requirements."},
        {"case_type":"Policy Clarification","category":"Pet Services","contact_name":"Maria Santos","contact_number":"+63 917 555 0342","email":"maria.santos@example.com","site_location":"Hilton Group • Front Desk","product":"Pet Policy","serial_number":"N/A","reference_number":"PET-POL-002","issue":"Customer is asking whether a specific pet type is allowed under the current policy.","description":"Customer provided the animal type and requested a policy confirmation before arrival.","resolution":"Pending policy confirmation.","next_action":"Check the current pet policy and communicate the applicable restriction or approval requirement.","notes":"Do not promise an exception without approval."},
        {"case_type":"Pet Service Request","category":"Pet Services","contact_name":"Anna Reyes","contact_number":"+63 917 555 0343","email":"anna.reyes@example.com","site_location":"Accenture Executive Stay • Room 404","product":"Pet Service","serial_number":"N/A","reference_number":"PET-SVC-003","issue":"Guest requested information about available pet-related services.","description":"Customer wants to know which approved services can be arranged during the stay.","resolution":"Pending service availability check.","next_action":"Confirm available services and coordinate with the appropriate provider.","notes":"Provide only currently approved services."},
        {"case_type":"Animal Facility Issue","category":"Facilities / Pet Services","contact_name":"Carlo Banaag","contact_number":"+63 917 555 0344","email":"carlo.banaag@example.com","site_location":"Microsoft Guest Facility","product":"Pet Facility","serial_number":"PET-FAC-004","reference_number":"PET-FAC-004","issue":"Pet facility area requires inspection after a reported cleanliness concern.","description":"Guest reported an issue with the condition of a designated pet area.","resolution":"Pending facility inspection.","next_action":"Inspect the area, document the condition and coordinate corrective action.","notes":"Keep the area safe for guests and animals during inspection."},
        {"case_type":"Pet Account Update","category":"Account Maintenance","contact_name":"Liza Tan","contact_number":"+63 917 555 0345","email":"liza.tan@example.com","site_location":"Acme Corporation • Guest Services","product":"Pet Account","serial_number":"N/A","reference_number":"PET-ACC-005","issue":"Customer requested an update to pet information on the account.","description":"The customer wants to correct the pet name and update the recorded pet information.","resolution":"Pending account validation.","next_action":"Verify requester identity and update the account using the approved workflow.","notes":"Document the requested and final values."}],
    "SUPPLY CHAIN": [
        {"case_type":"Shipment Exception","category":"Logistics","contact_name":"John Dela Cruz","contact_number":"+63 917 555 0441","email":"john.delacruz@example.com","site_location":"Manila Distribution Center","product":"Enterprise Hardware Shipment","serial_number":"SHIP-001","reference_number":"SC-SHP-001","issue":"Expected shipment has not arrived at the receiving location.","description":"The purchase order and shipment reference are available. Receiving team confirmed that the expected delivery has not been logged.","resolution":"Pending supplier and carrier validation.","next_action":"Validate shipment reference, expected delivery date and carrier status, then document the exception.","notes":"Customer requested a delivery update."},
        {"case_type":"Purchase Order Exception","category":"Procurement","contact_name":"Maria Santos","contact_number":"+63 917 555 0442","email":"maria.santos@example.com","site_location":"Cavite Procurement Office","product":"Purchase Order","serial_number":"N/A","reference_number":"SC-PO-002","issue":"Invoice and purchase order quantities do not match.","description":"The received invoice shows a quantity different from the approved purchase order.","resolution":"Pending PO and invoice reconciliation.","next_action":"Compare PO, receipt and invoice details and route the discrepancy to procurement if confirmed.","notes":"Do not approve the invoice until reconciliation is complete."},
        {"case_type":"Supplier Delivery Delay","category":"Supplier Management","contact_name":"Anna Reyes","contact_number":"+63 917 555 0443","email":"anna.reyes@example.com","site_location":"Pasig Fulfillment Center","product":"Replacement Parts","serial_number":"N/A","reference_number":"SC-DLY-003","issue":"Supplier advised that the delivery will miss the committed date.","description":"The supplier has reported a delay and the business is asking for an updated ETA.","resolution":"Pending supplier confirmation.","next_action":"Obtain revised ETA and document impact to the requested delivery schedule.","notes":"Escalate if the revised ETA affects a committed customer date."},
        {"case_type":"Inventory Discrepancy","category":"Inventory","contact_name":"Carlo Banaag","contact_number":"+63 917 555 0444","email":"carlo.banaag@example.com","site_location":"Makati Warehouse","product":"Warehouse Inventory","serial_number":"INV-004","reference_number":"SC-INV-004","issue":"Physical inventory count does not match the recorded quantity.","description":"Warehouse reported a discrepancy during a routine count.","resolution":"Pending inventory validation.","next_action":"Recount the affected item and reconcile system quantity against the physical result.","notes":"Record the final count and supporting transaction references."},
        {"case_type":"Replacement Request","category":"Logistics / Replacement","contact_name":"Liza Tan","contact_number":"+63 917 555 0445","email":"liza.tan@example.com","site_location":"Quezon City Customer Site","product":"Replacement Equipment","serial_number":"RPL-005","reference_number":"SC-RPL-005","issue":"Customer requested replacement equipment after a confirmed delivery exception.","description":"Replacement requirement has been raised and needs validation against the original order and shipment record.","resolution":"Pending replacement authorization.","next_action":"Validate the original order, reason for replacement and approved fulfillment route.","notes":"Keep the original shipment reference attached to the case."}],
    "ONSITE": [
        {"case_type":"Fulfillment Technician","category":"Field Services","contact_name":"John Dela Cruz","contact_number":"+63 917 555 0541","email":"john.delacruz@example.com","site_location":"BGC Enterprise Site","product":"HPE Server Infrastructure","serial_number":"SGH-ON-001","reference_number":"ONS-TECH-001","issue":"Customer requested fulfillment technical assistance for a hardware issue.","description":"Remote checks identified a suspected hardware fault. Customer has confirmed site access requirements and a local contact.","resolution":"Pending dispatch validation.","next_action":"Confirm technician availability, site access window, equipment details and dispatch requirements.","notes":"Site contact must be called before arrival."},
        {"case_type":"Hardware Replacement","category":"Field Services","contact_name":"Maria Santos","contact_number":"+63 917 555 0542","email":"maria.santos@example.com","site_location":"Makati Data Center","product":"HPE Storage Hardware","serial_number":"SGH-RPL-002","reference_number":"ONS-RPL-002","issue":"A hardware component requires replacement at the customer site.","description":"Customer provided the affected device information and requested an fulfillment replacement schedule.","resolution":"Pending replacement scheduling.","next_action":"Validate entitlement, replacement part availability and technician dispatch window.","notes":"Record serial number before and after replacement."},
        {"case_type":"Network Equipment","category":"Network / Field Services","contact_name":"Anna Reyes","contact_number":"+63 917 555 0543","email":"anna.reyes@example.com","site_location":"Cavite Manufacturing Site","product":"Network Switch","serial_number":"SW-ONS-003","reference_number":"ONS-NET-003","issue":"Network equipment is reporting intermittent connectivity at the site.","description":"Customer reports intermittent connectivity affecting a local segment. Initial remote checks are inconclusive.","resolution":"Pending fulfillment diagnostics.","next_action":"Confirm topology, affected ports and fulfillment access before dispatch.","notes":"Capture current configuration before hardware changes."},
        {"case_type":"Site Access","category":"Field Services","contact_name":"Carlo Banaag","contact_number":"+63 917 555 0544","email":"carlo.banaag@example.com","site_location":"Quezon City Corporate Office","product":"Fulfillment Support Visit","serial_number":"N/A","reference_number":"ONS-ACC-004","issue":"Scheduled fulfillment support requires updated visitor access information.","description":"Customer changed the site access window and needs the technician visit details updated.","resolution":"Pending access confirmation.","next_action":"Confirm the new access window, site contact and visitor requirements.","notes":"Do not dispatch without confirmed site access."},
        {"case_type":"Installation Support","category":"Deployment / Field Services","contact_name":"Liza Tan","contact_number":"+63 917 555 0545","email":"liza.tan@example.com","site_location":"Pasig Technology Center","product":"HPE Compute System","serial_number":"CMP-ONS-005","reference_number":"ONS-INS-005","issue":"Customer needs fulfillment assistance during a new equipment installation.","description":"Equipment is scheduled for installation and the customer requested support for physical setup and validation.","resolution":"Pending installation scheduling.","next_action":"Confirm equipment availability, site readiness, installation window and required technician skills.","notes":"Coordinate with the customer before confirming the appointment."}],
}


def reset_mock_case_durations():
    now = utc_now()

    result = col(TASKS_COLLECTION).update_many(
        {"is_mock": True, "case_number": {"$not": {"$regex": "^SIM-"}}},
        {"$set": {
            "created_at": now,
            "station_started_at": now,
            "last_update": now,
            "mock_data_version": MOCK_DATA_VERSION,
        }},
    )

    for station, cfg in STATIONS.items():
        col(TASKS_COLLECTION).update_many(
            {
                "is_mock": True,
                "case_number": {"$not": {"$regex": "^SIM-"}},
                "department": station,
            },
            {"$set": {
                "due_date": now + timedelta(minutes=cfg["sla_minutes"])
            }},
        )

    clear_task_cache()
    return result.modified_count


@st.cache_resource(show_spinner=False)
def seed_mock_cases():
    # Remove old mock distributions so the app always ends with 5 per station.
    existing = list(
        col(TASKS_COLLECTION).find(
            {"is_mock": True},
            {"_id": 1, "department": 1, "mock_data_version": 1}
        )
    )

    expected = len(STATIONS) * 5
    valid = (
        len(existing) == expected
        and all(
            x.get("mock_data_version") == MOCK_DATA_VERSION
            for x in existing
        )
        and all(
            sum(
                1 for x in existing
                if station_name(x.get("department")) == station
            ) == 5
            for station in STATIONS
        )
    )

    if valid:
        return len(existing)

    col(TASKS_COLLECTION).delete_many({"is_mock": True})

    now = utc_now()
    docs = []
    number = 1

    for station, cfg in STATIONS.items():
        for i in range(5):
            priority = i == 0
            detail = MOCK_CASE_DETAILS[station][i]
            account = MOCK_ACCOUNTS[i % len(MOCK_ACCOUNTS)]
            vendor = "CoolTech Solutions" if i % 2 == 0 else "HPE Partner Services"

            docs.append({
                "case_number": f"{station[:3].upper()}-2026-{number:04d}",
                "subject": MOCK_SUBJECTS[station][i],
                "priority": "Critical" if priority else ("Medium" if i == 1 else "Low"),
                "account_priority": "Yes" if priority else "No",
                "assigned_to": MOCK_NAMES[i],
                "department": station,
                "account_name": account,
                "vendor": vendor,
                "issue": detail["issue"],
                "description": detail["description"],
                "status": "In Progress" if i % 2 == 0 else "Open",
                "created_at": now,
                "station_started_at": now,
                "due_date": now + timedelta(minutes=cfg["sla_minutes"]),
                "last_update": now,
                "notes": detail["notes"],
                "active": True,
                "is_mock": True,
                "mock_data_version": MOCK_DATA_VERSION,
                "source_type": "mock",
                "case_type": detail["case_type"],
                "category": detail["category"],
                "contact_name": detail["contact_name"],
                "contact_number": detail["contact_number"],
                "email": detail["email"],
                "site_location": detail["site_location"],
                "product": detail["product"],
                "serial_number": detail["serial_number"],
                "reference_number": detail["reference_number"],
                "resolution": detail["resolution"],
                "next_action": detail["next_action"],
                "history": [
                    {"action": f"Case entered {station}", "timestamp": now},
                    {"action": f"Assigned to {MOCK_NAMES[i]}", "timestamp": now},
                    {"action": f"Initial triage completed — {detail['category']}", "timestamp": now},
                ],
            })
            number += 1

    col(TASKS_COLLECTION).insert_many(docs)
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




def import_cases_excel(uploaded_file, replace_existing_excel=False):
    try:
        df = pd.read_excel(uploaded_file)
        if df.empty:
            return False, "The Excel file is empty.", 0

        def norm(c):
            return (
                text(c).lower().strip()
                .replace("#", "number")
                .replace("/", "_")
                .replace("-", "_")
                .replace(" ", "_")
            )

        df.columns = [norm(c) for c in df.columns]
        df = df.rename(columns={
            "case": "case_number",
            "case_no": "case_number",
            "caseid": "case_number",
            "case_id": "case_number",
            "account": "account_name",
            "accountname": "account_name",
            "station": "department",
            "assigned": "assigned_to",
            "assignedto": "assigned_to",
            "accountpriority": "account_priority",
            "created": "created_at",
            "created_date": "created_at",
            "station_started": "station_started_at",
            "station_start": "station_started_at",
            "due": "due_date",
            "due_datetime": "due_date",
            "last_update_date": "last_update",
        })

        required = {"case_number", "subject", "department"}
        missing = sorted(required - set(df.columns))
        if missing:
            return False, "Missing required column(s): " + ", ".join(missing), 0

        def parse_dt(value, fallback):
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return fallback
            parsed = pd.to_datetime(value, errors="coerce", utc=True)
            return fallback if pd.isna(parsed) else parsed.to_pydatetime()

        now = utc_now()
        operations = []
        skipped = 0

        if replace_existing_excel:
            col(TASKS_COLLECTION).delete_many({"source_type": "excel"})

        for _, row in df.iterrows():
            case_number = text(row.get("case_number"))
            subject = text(row.get("subject"))
            station = station_name(row.get("department"))

            if not case_number or not subject or station not in STATIONS:
                skipped += 1
                continue

            created = parse_dt(row.get("created_at"), now)
            started = parse_dt(row.get("station_started_at"), created)
            due = parse_dt(
                row.get("due_date"),
                started + timedelta(minutes=STATIONS[station]["sla_minutes"]),
            )

            doc = {
                "case_number": case_number,
                "subject": subject,
                "priority": text(row.get("priority")) or "Low",
                "account_priority": "Yes" if is_priority(row.get("account_priority")) else "No",
                "assigned_to": text(row.get("assigned_to")) or "Unassigned",
                "department": station,
                "account_name": text(row.get("account_name")),
                "vendor": text(row.get("vendor")),
                "issue": text(row.get("issue")) or subject,
                "description": text(row.get("description")),
                "status": text(row.get("status")) or "Open",
                "created_at": created,
                "station_started_at": started,
                "due_date": due,
                "last_update": parse_dt(row.get("last_update"), now),
                "notes": text(row.get("notes")),
                "active": True,
                "is_mock": False,
                "source_type": "excel",
                "history": [{"action": f"Case imported into {station}", "timestamp": now}],
            }

            operations.append(
                ReplaceOne({"case_number": case_number}, doc, upsert=True)
            )

        if operations:
            col(TASKS_COLLECTION).bulk_write(operations, ordered=False)
            clear_task_cache()

        return True, f"{len(operations)} case record(s) imported; {skipped} skipped.", len(operations)
    except Exception as exc:
        return False, f"Unable to import cases: {exc}", 0





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
# KNOWLEDGE BASE
# ============================================================

def kb_text(doc):
    fields = [
        doc.get("title"), doc.get("subject"), doc.get("question"),
        doc.get("keywords"), doc.get("category"), doc.get("answer"),
        doc.get("content"), doc.get("body"), doc.get("summary"),
        doc.get("resolution"), doc.get("sop"),
    ]

    parts = []
    for value in fields:
        if isinstance(value, list):
            parts.extend(text(x) for x in value)
        elif isinstance(value, dict):
            parts.extend(text(x) for x in value.values())
        else:
            parts.append(text(value))

    return " ".join(x for x in parts if x).lower()


def kb_content(doc):
    for key in ["answer", "content", "body", "resolution", "summary", "description", "sop"]:
        if doc.get(key):
            return text(doc.get(key))
    return "No detailed answer was provided in this article."


def kb_score(query, doc):
    words = {
        x.strip(".,:;!?()[]{}").lower()
        for x in text(query).split()
        if len(x.strip(".,:;!?()[]{}")) >= 3
    }

    if not words:
        return 0

    haystack = kb_text(doc)
    title = text(doc.get("title")).lower()
    category = text(doc.get("category")).lower()

    score = sum(1 for word in words if word in haystack)
    score += 4 if any(word in title for word in words) else 0
    score += 2 if any(word in category for word in words) else 0

    keywords = doc.get("keywords", [])
    if isinstance(keywords, list):
        score += sum(
            3 for keyword in keywords
            if any(word in text(keyword).lower() for word in words)
        )

    return score


def load_kb_documents():
    docs = []

    for collection_name in [KB_COLLECTION, SOP_COLLECTION]:
        try:
            docs.extend(
                list(
                    col(collection_name).find(
                        {},
                        {
                            "_id": 1, "title": 1, "subject": 1, "question": 1,
                            "keywords": 1, "category": 1, "answer": 1,
                            "content": 1, "body": 1, "summary": 1,
                            "description": 1, "resolution": 1, "sop": 1,
                            "source": 1, "source_type": 1, "url": 1,
                        },
                    ).limit(1000)
                )
            )
        except Exception:
            pass

    return docs


def search_kb(query, limit=5):
    results = [
        (kb_score(query, doc), doc)
        for doc in load_kb_documents()
        if kb_score(query, doc) > 0
    ]
    results.sort(key=lambda x: -x[0])
    return [doc for _, doc in results[:limit]]


def case_kb_query(task):
    return " ".join(
        x for x in [
            text(task.get("subject")),
            text(task.get("issue")),
            station_name(task.get("department")),
            text(task.get("account_name")),
        ]
        if x
    )


def seed_demo_kb():
    try:
        if col(KB_COLLECTION).count_documents({}) or col(SOP_COLLECTION).count_documents({}):
            return

        docs = [
            {
                "title": "CARE - Guest Room AC Not Working",
                "category": "CARE / Maintenance",
                "keywords": ["AC", "air conditioning", "room", "HVAC", "not working"],
                "answer": "Verify the room number, thermostat setting, power and airflow. Document the symptoms and route the case through the applicable maintenance/vendor process if basic checks do not resolve the issue.",
                "source": "Caseflow Demo Knowledge Base",
                "source_type": "demo",
            },
            {
                "title": "HPE Licensing - Portal Access Troubleshooting",
                "category": "Licensing",
                "keywords": ["licensing", "portal", "access", "HPE", "login"],
                "answer": "Confirm the customer's account and entitlement context, verify the portal account and capture the exact access error. If entitlement is valid but portal access fails, follow the approved account-access escalation process.",
                "source": "Caseflow Demo Knowledge Base",
                "source_type": "demo",
            },
            {
                "title": "FULFILLMENT - Hardware Replacement",
                "category": "FULFILLMENT",
                "keywords": ["fulfillment", "hardware", "replacement", "device", "technician"],
                "answer": "Capture the device, serial number, site/location, symptoms, contact details and access requirements. Confirm whether fulfillment dispatch or remote troubleshooting is appropriate before escalation.",
                "source": "Caseflow Demo Knowledge Base",
                "source_type": "demo",
            },
            {
                "title": "SUPPLY CHAIN - Missing Shipment",
                "category": "SUPPLY CHAIN",
                "keywords": ["shipment", "missing", "delivery", "supplier", "order"],
                "answer": "Validate the purchase order or shipment reference, delivery destination and expected delivery date. Document supplier confirmation and escalate the delivery exception through the approved process.",
                "source": "Caseflow Demo Knowledge Base",
                "source_type": "demo",
            },
            {
                "title": "ARCH - Document Retrieval",
                "category": "ARCH",
                "keywords": ["archive", "document", "retrieval", "record", "index"],
                "answer": "Confirm the record identifier, date range and retention context. Search the applicable archive index and document the retrieval result or reason the record cannot be located.",
                "source": "Caseflow Demo Knowledge Base",
                "source_type": "demo",
            },
            {
                "title": "PET - Pet Registration Inquiry",
                "category": "PET",
                "keywords": ["pet", "registration", "policy", "animal"],
                "answer": "Confirm the account and pet information, then follow the current pet registration and policy procedure. Record required approval or documentation in the case.",
                "source": "Caseflow Demo Knowledge Base",
                "source_type": "demo",
            },
        ]

        col(KB_COLLECTION).insert_many(docs)
        load_kb_documents.clear()
    except Exception:
        pass


def local_kb_ai_answer(question, task, documents):
    """Create a deterministic, KB-grounded answer without an external AI API."""
    question = text(question).strip()

    if not question:
        return {
            "answer": "Please enter a question first.",
            "sources": [],
            "confidence": "No question",
        }

    if not documents:
        return {
            "answer": (
                "No matching Knowledge Base or SOP article was found. "
                "Try a product name, issue keyword, station name, or "
                "troubleshooting term."
            ),
            "sources": [],
            "confidence": "No matching source",
        }

    selected = []
    seen = set()

    for doc in documents:
        title = text(doc.get("title")) or "Knowledge Base Article"
        identity = text(doc.get("_id")) or title.lower()
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(doc)
        if len(selected) >= 4:
            break

    retrieval_query = f"{question} {case_kb_query(task)}"
    scores = [kb_score(retrieval_query, doc) for doc in selected]
    best_score = max(scores) if scores else 0

    if best_score >= 8:
        confidence = "High match"
    elif best_score >= 4:
        confidence = "Good match"
    else:
        confidence = "Related match"

    best = selected[0]
    best_title = text(best.get("title")) or "Knowledge Base Article"
    best_content = kb_content(best).strip()

    answer_parts = [
        "### Recommended guidance",
        f"**{best_title}**",
        "",
        best_content,
    ]

    if len(selected) > 1:
        answer_parts.extend(["", "### Additional relevant guidance"])
        for doc in selected[1:3]:
            title = text(doc.get("title")) or "Related Article"
            content = kb_content(doc).strip()
            if len(content) > 450:
                content = content[:450].rstrip() + "…"
            answer_parts.append(f"- **{title}:** {content}")

    answer_parts.extend([
        "",
        "### Verify before action",
        (
            "Confirm the current case details, applicable policy or "
            "entitlement, required identifiers, and the latest approved "
            "SOP before escalating or taking an external action."
        ),
    ])

    return {
        "answer": "\n".join(answer_parts),
        "sources": selected,
        "confidence": confidence,
    }


seed_demo_kb()


# ============================================================
# HEADER
# ============================================================


# CSS/HTML recreation of the supplied HPE Caseflow reference.
# The uploaded image itself is NOT used. Search and Settings remain native
# Streamlit controls so all existing functionality is preserved.
with st.container(key="caseflow_header_shell"):


    header_cols = st.columns([31, 44, 5], gap="small")


    with header_cols[0]:
        st.markdown(
            """
            <div class="caseflow-brand" aria-label="HPE Caseflow">
                <div class="caseflow-hpe-symbol" aria-hidden="true"></div>
                <div class="caseflow-hpe-copy">
                    <div class="caseflow-hpe-word">HPE</div>
                    <div class="caseflow-hpe-tagline">Accelerating what's next together</div>
                </div>
                <div class="caseflow-divider" aria-hidden="true"></div>
                <div class="caseflow-title">Caseflow</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


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
                "Cases",
                "External Sync",
                "Access Control",
                "Simulation",
            ])


            # -----------------------------------------------
            # CASE EXCEL IMPORT
            # -----------------------------------------------


            with tabs[0]:
                st.markdown("### Case Data")
                st.caption(
                    "Upload the Excel case file using the same columns as the "
                    "dashboard case records. Case #, Subject and Department are required."
                )


                case_file = st.file_uploader(
                    "Cases Excel",
                    type=["xlsx", "xls"],
                    key="case_excel_upload",
                    help="Import active cases into Tasks_Collection.",
                )


                replace_excel = st.checkbox(
                    "Replace previously imported Excel cases",
                    value=False,
                    help="Removes only records previously tagged as source_type='excel' before importing this workbook.",
                )


                if case_file is not None:
                    try:
                        preview_df = pd.read_excel(case_file)
                        st.dataframe(
                            preview_df.head(8),
                            use_container_width=True,
                            hide_index=True,
                        )
                    except Exception as exc:
                        st.error(f"Unable to preview the Excel file: {exc}")


                    if st.button(
                        "Import Cases",
                        type="primary",
                        use_container_width=True,
                        key="import_cases_excel",
                    ):
                        with st.spinner("Importing case data..."):
                            ok, msg, imported_count = import_cases_excel(
                                case_file,
                                replace_existing_excel=replace_excel,
                            )


                        if ok:
                            st.success(msg)
                            st.session_state["selected_station"] = "CARE"
                            st.rerun()
                        else:
                            st.error(msg)


                st.info(
                    "Recommended columns: Case #, Subject, Priority, Account Priority, "
                    "Assigned To, Department, Account Name, Vendor, Issue, Description, "
                    "Status, Created At, Station Started At, Due Date, Last Update, Notes, Active, Is Mock."
                )


            # -----------------------------------------------
            # EXTERNAL SYNC
            # -----------------------------------------------


            with tabs[1]:


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
                    "↻ Reset Mock Case Durations to 00:00:00",
                    type="secondary",
                    use_container_width=True,
                    key="reset_mock_case_durations",
                    help="Reset all seeded mock cases to zero elapsed duration and restart their station SLA timers.",
                ):
                    reset_count = reset_mock_case_durations()
                    st.session_state["simulation_until"] = 0.0
                    st.session_state["simulation_case_id"] = None
                    st.success(
                        f"{reset_count} mock case(s) reset to 00:00:00."
                    )


                st.markdown("---")


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
        task = col(TASKS_COLLECTION).find_one({"_id": ObjectId(task_id)})
    except Exception:
        task = None

    if not task:
        st.error("Case not found.")
        return

    state = calculate_state(task)
    station = station_name(task.get("department"))
    status = text(task.get("status")) or "In Progress"

    critical = (
        state["priority_account"]
        or state["status"] in {"CRITICAL", "BREACHED"}
    )

    description = (
        text(task.get("description"))
        or text(task.get("issue"))
        or "No description available."
    )

    # -------------------------
    # Reference header
    # -------------------------

    st.markdown(
        f"""
        <div class="detail-header">
            <div class="detail-header-title">Case Details</div>
            {
                '<span class="detail-critical"><span class="detail-critical-dot">!</span>Critical</span>'
                if critical else
                f'<span class="detail-pill blue">{html.escape(state["status"].title())}</span>'
            }
        </div>

        <div class="detail-case-title">
            {html.escape(text(task.get("case_number")))}
            <span class="detail-status">{html.escape(status)}</span>
        </div>

        <div class="detail-subject">
            {html.escape(text(task.get("subject")))}
        </div>

        <div class="detail-description">
            {html.escape(description)}
        </div>
        """,
        unsafe_allow_html=True,
    )

    priority_html = (
        '<span class="detail-pill red">! Critical</span>'
        if critical
        else f'<span class="detail-pill blue">{html.escape(text(task.get("priority","Low")).title())}</span>'
    )

    account_html = (
        '<span class="detail-pill purple">⌖ Priority Account</span>'
        if state["priority_account"]
        else ""
    )

    st.markdown(
        f"""
        <div class="detail-grid">

            <div class="detail-grid-col">

                <div class="detail-field">
                    <div class="detail-label">Priority</div>
                    <div class="detail-value">{priority_html}</div>
                </div>

                <div class="detail-field">
                    <div class="detail-label">Current Department</div>
                    <div class="detail-value">
                        <span class="detail-pill"
                              style="background:{STATIONS.get(station,STATIONS["CARE"])["soft"]};
                                     color:{STATIONS.get(station,STATIONS["CARE"])["accent"]}">
                            {html.escape(station)}
                        </span>
                    </div>
                </div>

                <div class="detail-field">
                    <div class="detail-label">Assigned To</div>
                    <div class="detail-value">
                        {html.escape(text(task.get("assigned_to")) or "Unassigned")}
                    </div>
                </div>

                <div class="detail-field">
                    <div class="detail-label">Due Date</div>
                    <div class="detail-value red">
                        {html.escape(dt_display(task.get("due_date")))}
                    </div>
                </div>

                <div class="detail-field">
                    <div class="detail-label">Duration</div>
                    <div class="detail-value red">
                        {duration_string(state["elapsed"])}
                    </div>
                </div>

            </div>

            <div class="detail-grid-col right">

                <div class="detail-field">
                    <div class="detail-label">Account Name</div>
                    <div class="detail-value">
                        {html.escape(text(task.get("account_name")) or "—")}
                        {account_html}
                    </div>
                </div>

                <div class="detail-field">
                    <div class="detail-label">Case Type</div>
                    <div class="detail-value">
                        {html.escape(
                            text(task.get("case_type"))
                            or text(task.get("category"))
                            or station
                            or "—"
                        )}
                    </div>
                </div>

                <div class="detail-field">
                    <div class="detail-label">Case Status</div>
                    <div class="detail-value">
                        {html.escape(status)}
                    </div>
                </div>

                <div class="detail-field">
                    <div class="detail-label">Created By</div>
                    <div class="detail-value">
                        {html.escape(text(task.get("created_by")) or "System")}
                    </div>
                </div>

                <div class="detail-field">
                    <div class="detail-label">Date Created</div>
                    <div class="detail-value">
                        {html.escape(dt_display(task.get("created_at")))}
                    </div>
                </div>

            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # -------------------------
    # Detailed case information
    # -------------------------

    detail_items = [
        ("Contact Person", text(task.get("contact_name"))),
        ("Contact Number", text(task.get("contact_number"))),
        ("Email", text(task.get("email"))),
        ("Site / Location", text(task.get("site_location"))),
        ("Product / Service", text(task.get("product"))),
        ("Serial Number", text(task.get("serial_number"))),
        ("Reference Number", text(task.get("reference_number"))),
        ("Category", text(task.get("category"))),
    ]

    detail_items = [item for item in detail_items if item[1]]

    if detail_items:
        st.markdown("### Case Information")
        cols = st.columns(2)
        for index, (label, value) in enumerate(detail_items):
            with cols[index % 2]:
                st.markdown(
                    f"""
                    <div class=\"detail-field\">
                        <div class=\"detail-label\">{html.escape(label)}</div>
                        <div class=\"detail-value\">{html.escape(value)}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        resolution = text(task.get("resolution"))
        next_action = text(task.get("next_action"))
        notes = text(task.get("notes"))

        if resolution:
            st.markdown("**Current Resolution / Assessment**")
            st.info(resolution)

        if next_action:
            st.markdown("**Recommended Next Action**")
            st.success(next_action)

        if notes:
            st.markdown("**Case Notes**")
            st.caption(notes)

    # -------------------------
    # Vendor reference card
    # -------------------------

    vendor = find_vendor(task)

    st.markdown(
        '<div class="vendor-card"><div class="vendor-heading">'
        '<span class="vendor-icon">⌂</span>Vendor Information'
        '</div>',
        unsafe_allow_html=True,
    )

    if vendor:

        items = {
            k: v for k, v in vendor.items()
            if k not in {"_id", "vendor_key", "synced_at"} and text(v)
        }

        if items:
            markup = ""
            for key, value in items.items():
                markup += (
                    f'<div class="vendor-key">{html.escape(key.replace("_"," ").title())}</div>'
                    f'<div class="vendor-value">{html.escape(text(value))}</div>'
                )

            st.markdown(
                f'<div class="vendor-grid">{markup}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="kb-empty">Vendor record is empty.</div>',
                unsafe_allow_html=True,
            )

    else:

        st.markdown(
            """
            <div class="vendor-grid">
                <div class="vendor-key">Vendor Name</div>
                <div class="vendor-value">No synchronized vendor record</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)

    # -------------------------
    # INTEGRATED KNOWLEDGE BASE
    # -------------------------

    auto_query = case_kb_query(task)

    st.markdown(
        f"""
        <div class="kb-panel">
            <div class="kb-panel-header">
                <div class="kb-title">Knowledge Base</div>
                <span class="kb-auto-badge">CASE-MATCHED</span>
            </div>
            <div class="kb-subtitle">
                Recommended SOPs, troubleshooting guidance and knowledge
                articles based on this case.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    kb_query = st.text_area(
        "Ask Knowledge Base",
        value=auto_query,
        placeholder="Ask a question about this case, troubleshooting, licensing, devices or SOPs...",
        key=f"kb_query_{task_id}",
        height=82,
        label_visibility="collapsed",
    )

    kb1, kb2 = st.columns([2, 1])

    with kb1:
        search_clicked = st.button(
            "✨ Ask Knowledge Base",
            type="primary",
            use_container_width=True,
            key=f"kb_search_{task_id}",
        )

    with kb2:
        case_match_clicked = st.button(
            "↻ Case Match",
            use_container_width=True,
            key=f"kb_case_match_{task_id}",
        )

    if search_clicked:
        active_query = text(kb_query).strip() or auto_query
        results = search_kb(f"{active_query} {auto_query}", limit=5)
    elif case_match_clicked:
        results = search_kb(auto_query, limit=5)
    else:
        results = search_kb(auto_query, limit=5)

    if results:

        best = results[0]

        st.markdown(
            f"""
            <div class="kb-answer-card best">
                <div class="kb-answer-label">Best Match</div>
                <div class="kb-result-title">
                    {html.escape(text(best.get("title")) or "Knowledge Base Article")}
                </div>
                <div class="kb-result-text">
                    {html.escape(kb_content(best))}
                </div>
                <div class="kb-meta">
                    <span class="kb-source-pill">
                        {html.escape(text(best.get("category")) or "Knowledge Base")}
                    </span>
                    <span class="kb-source-pill">
                        {html.escape(text(best.get("source_type")) or "KB")}
                    </span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        for index, result in enumerate(results[1:], start=2):

            content = kb_content(result)
            if len(content) > 450:
                content = content[:450].rstrip() + "…"

            st.markdown(
                f"""
                <div class="kb-answer-card">
                    <div class="kb-result-title">
                        {index}. {html.escape(text(result.get("title")) or "Knowledge Base Article")}
                    </div>
                    <div class="kb-result-text">
                        {html.escape(content)}
                    </div>
                    <div class="kb-meta">
                        <span class="kb-source-pill">
                            {html.escape(text(result.get("category")) or "Knowledge Base")}
                        </span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    else:

        st.markdown(
            f"""
            <div class="kb-answer-card">
                <div class="kb-result-title">No matching article found</div>
                <div class="kb-empty">
                    Try a shorter issue description or a product/SOP keyword.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


    # -------------------------
    # ASK KNOWLEDGE BASE
    # -------------------------

    ai_question_key = f"local_ai_question_{task_id}"
    ai_result_key = f"local_ai_result_{task_id}"

    if ai_question_key not in st.session_state:
        st.session_state[ai_question_key] = "What are the recommended next steps for this case?"

    st.markdown(
        """
        <div class="kb-panel">
            <div class="kb-panel-header">
                <div>
                    <div class="kb-title">✨ Ask Knowledge Base</div>
                    <div class="kb-subtitle">
                        Ask a question about this case. Caseflow searches the local Knowledge Base and SOPs;
                        no OpenAI API key is required.
                    </div>
                </div>
                <span class="kb-auto-badge">CASE-AWARE</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    ai_question = st.text_area(
        "Ask the Knowledge Base",
        key=ai_question_key,
        height=90,
        placeholder="Example: What should I verify before escalating this case?",
        label_visibility="collapsed",
    )

    ask_col, clear_col = st.columns([3, 1])

    with ask_col:
        ask_ai_clicked = st.button(
            "✨ Ask Knowledge Base",
            type="primary",
            use_container_width=True,
            key=f"ask_local_kb_{task_id}",
        )

    with clear_col:
        clear_ai_clicked = st.button(
            "Clear",
            use_container_width=True,
            key=f"clear_local_kb_{task_id}",
        )

    if clear_ai_clicked:
        st.session_state.pop(ai_result_key, None)
        st.session_state[ai_question_key] = ""
        st.rerun()

    if ask_ai_clicked:
        question = text(ai_question).strip()
        retrieval_query = " ".join(x for x in [question, case_kb_query(task)] if x)
        retrieved = search_kb(retrieval_query, limit=6)
        st.session_state[ai_result_key] = local_kb_ai_answer(question, task, retrieved)

    ai_result = st.session_state.get(ai_result_key)

    if ai_result:
        answer_html = html.escape(text(ai_result.get("answer"))).replace("\n", "<br>")
        st.markdown(
            f"""
            <div class="kb-answer-card best">
                <div class="kb-answer-label">Knowledge Base Answer · {html.escape(text(ai_result.get("confidence")))}</div>
                <div class="kb-result-text">{answer_html}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        sources = ai_result.get("sources", [])
        if sources:
            pills = "".join(
                f'<span class="kb-source-pill">{html.escape(text(doc.get("title")) or "KB Article")}</span>'
                for doc in sources[:6]
            )
            st.markdown(
                f'<div class="kb-meta" style="margin-top:8px"><strong>Sources used:</strong> {pills}</div>',
                unsafe_allow_html=True,
            )


    # -------------------------
    # Transfer
    # -------------------------

    st.markdown("### Transfer Case")

    stations = list(STATIONS.keys())
    current = station

    destination = st.selectbox(
        "Destination",
        stations,
        index=stations.index(current) if current in stations else 0,
        key=f"destination_{task_id}",
    )

    st.caption("Duration resets when the case enters the destination station.")

    if st.button(
        f"Transfer to {destination}",
        type="primary",
        use_container_width=True,
        key=f"transfer_{task_id}",
    ):

        if destination == current:
            st.warning("Choose a different station.")
        elif transfer_case(task, destination):
            st.success(f"Case transferred to {destination}.")
            st.rerun()
        else:
            st.error("Unable to transfer case.")

    # -------------------------
    # History
    # -------------------------

    history = task.get("history", [])

    if history:

        st.markdown("### Activity History")

        for event in reversed(history[-15:]):
            st.write(f"• {text(event.get('action'))}")
            st.caption(dt_display(event.get("timestamp")))

    if st.button("Close", use_container_width=True, key=f"close_case_{task_id}"):
        st.rerun()









# ============================================================
# DASHBOARD
# ============================================================
# REAL-TIME DASHBOARD
# The dashboard fragment refreshes once per second so MongoDB changes are
# reflected on the visible tiles/table without refreshing the entire app.
# Duration still updates browser-side every second for smooth per-second timing.


@st.fragment(run_every="1s")
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


    # Alerts are evaluated during the same lightweight 1-second fragment
    # refresh, keeping the visible dashboard and Alert_Collection synchronized.
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
                    f'<div class="station-card-title">{html.escape("FULFILLMENT" if station == "ONSITE" else station)}</div>'
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
                {html.escape("FULFILLMENT" if selected == "ONSITE" else selected)}
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
# INITIAL MOCK DATA
# ============================================================


# Seed before the first dashboard render so the first view already
# contains the mock cases. This check runs once per normal app render
# and does not create a background refresh loop.
# Seed/mock migration is cached as a resource so normal fragment reruns
# do not repeatedly query MongoDB for the mock-data count.
seed_mock_cases()




# Render the live dashboard. The fragment itself refreshes every second,
# while the rest of the application remains untouched.
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
