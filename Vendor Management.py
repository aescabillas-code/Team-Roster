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
- Centered compact case-detail dialog
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
    APP_NAME = "OVR-VW"


Install:
    pip install streamlit pymongo pandas openpyxl itsdangerous streamlit-js-eval
"""


import hashlib
import hmac
import html
import os
import time
from datetime import datetime, timezone, timedelta


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
    page_title="OVR-VW",
    page_icon="⏱️",
    layout="wide",
    initial_sidebar_state="collapsed",
)




# ============================================================
# CONFIG
# ============================================================




DB_NAME = "TeamRoster"


TASKS_COLLECTION = "Tasks_Collection"
VENDOR_COLLECTION = "Vendor_Collection"
ACCESS_COLLECTION = "Access_Collection"
ALERT_COLLECTION = "Alert_Collection"
KB_COLLECTION = "Knowledge_Base_Collection"
SOP_COLLECTION = "SOP_Collection"
ACCOUNT_PRIORITY_COLLECTION = "Account_Priority_Collection"


# Performance tuning: retain a short cache so the 1-second UI fragment does not
# force a MongoDB read on every tick. This reduces database/network churn while
# keeping the dashboard visually current.
TASK_CACHE_TTL = 1.5
# Alert scans are lightweight and run in the same 1-second fragment.
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


# Required completion checklist for every station.
# A case cannot be reassigned or transferred until every checked-in item
# for its CURRENT station is completed. Custom items may be added per case.
STATION_CHECKLISTS = {
    "CARE": [
        "Confirm the HPE/Aruba product, model and serial number.",
        "Capture the exact alert, error message or customer symptom.",
        "Complete the applicable remote/basic troubleshooting checks.",
        "Verify support, entitlement or contract context when applicable.",
        "Record customer contact, site and required reference information.",
        "Document the assessment and recommended next action.",
    ],
    "ARCH": [
        "Confirm the case/reference number and customer record.",
        "Identify the required HPE/Aruba document, entitlement or record.",
        "Locate and validate the source record against the request.",
        "Attach or record the retrieved reference/document details.",
        "Confirm the information is complete and appropriate for release.",
        "Document the retrieval result and next action.",
    ],
    "PET": [
        "Confirm the HPE/Aruba device, platform and management system.",
        "Capture model, serial number, hostname or endpoint identifier.",
        "Verify the requested configuration, policy or access requirement.",
        "Review the relevant HPE/Aruba management or event details.",
        "Validate the proposed change before applying or escalating it.",
        "Document the result, evidence and next action.",
    ],
    "SUPPLY CHAIN": [
        "Validate the purchase order, sales order or shipment reference.",
        "Confirm the HPE/Aruba product, part number and quantity.",
        "Verify shipment status, tracking and expected delivery date.",
        "Confirm destination site and receiving contact.",
        "Document any delivery, inventory or fulfillment exception.",
        "Record the supplier/partner action and next step.",
    ],
    "ONSITE": [
        "Confirm the HPE/Aruba device model and serial number.",
        "Verify site address, onsite contact and access requirements.",
        "Confirm remote troubleshooting and onsite scope of work.",
        "Verify replacement part, equipment or technician requirement.",
        "Document onsite findings, work completed and evidence.",
        "Confirm the case is ready for closure or the next station.",
    ],
}

CASEFLOW_ASSIGNEES = [
    "June John Cruz",
    "Arianne May Escabillas",
    "Jonathan Gaspar",
    "Kenjie Locsin",
    "Lucille Layug",
    "Karen Sabile",
]


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
        col(ALERT_COLLECTION).create_index(
            [("task_id", ASCENDING), ("trigger_key", ASCENDING), ("alert_type", ASCENDING)]
        )
        col(ACCOUNT_PRIORITY_COLLECTION).create_index(
            [("account_name", ASCENDING)]
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


def station_display_name(value):
    """UI label for a station; keep ONSITE as the internal key but show FULFILLMENT."""
    canonical = station_name(value)
    return "FULFILLMENT" if canonical == "ONSITE" else canonical




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
            <div class="access-title">OVR-VW</div>
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
    "station_warning_latched": set(),
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
    [class*="st-key-station_wrap_onsite"] { position:relative !important; min-height:150px !important; overflow:visible !important; }
    .station-card-visual {
        position:relative; z-index:1; height:150px; min-height:150px; box-sizing:border-box;
        border-radius:11px; padding:13px 17px; overflow:hidden;
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
        width:48px; height:48px; border-radius:50%; display:flex; align-items:center; justify-content:center;
        font-size:23px; font-weight:900; position:absolute; left:17px; top:13px;
        background:rgba(255,255,255,.48);
    }
    .care .station-icon-circle { color:#e51c3a; background:#ffd7df; }
    .arch .station-icon-circle { color:#0879c9; background:#bce8ff; }
    .pet .station-icon-circle { color:#087b58; background:#bff1df; }
    .supply .station-icon-circle { color:#5d2ac9; background:#dfceff; }
    .onsite .station-icon-circle { color:#c98700; background:#ffe5a8; }
    .station-copy { position:absolute; left:78px; top:21px; }
    .station-card-title { font-size:14px; font-weight:850; line-height:1.1; letter-spacing:-.15px; }
    .station-count-line { display:flex; align-items:baseline; gap:4px; margin-top:5px; }
    .station-count { font-size:25px; line-height:1; font-weight:900; }
    .station-active { font-size:9px; color:#53637f; }
    .care .station-count { color:#e51c3a; }
    .arch .station-count { color:#0879c9; }
    .pet .station-count { color:#087b58; }
    .supply .station-count { color:#5d2ac9; }
    .onsite .station-count { color:#c98700; }
    .station-arrow { position:absolute; right:14px; top:21px; font-size:21px; font-weight:300; color:#30466b; }
    .station-warning { position:absolute; left:17px; bottom:27px; font-size:9px; font-weight:750; color:#53637f; }
    .station-warning.active { color:#d33a4e; }
    .arch .station-warning.active, .pet .station-warning.active, .supply .station-warning.active, .onsite .station-warning.active { color:#53637f; }
    .station-sla-ref { position:absolute; left:17px; bottom:10px; font-size:9px; color:#53637f; }
    .station-sla-ref strong { color:#102041; }
    /* Make the real button transparent and stretch it over the card. */
    [class*="st-key-station_wrap_care"] [class*="st-key-station_CARE"],
    [class*="st-key-station_wrap_arch"] [class*="st-key-station_ARCH"],
    [class*="st-key-station_wrap_pet"] [class*="st-key-station_PET"],
    [class*="st-key-station_wrap_supply"] [class*="st-key-station_SUPPLY"],
    [class*="st-key-station_wrap_onsite"] [class*="st-key-station_ONSITE"] {
        position:absolute !important; inset:0 !important; z-index:50 !important;
        width:100% !important; height:150px !important;
    }
    [class*="st-key-station_wrap_care"] [class*="st-key-station_CARE"] button,
    [class*="st-key-station_wrap_arch"] [class*="st-key-station_ARCH"] button,
    [class*="st-key-station_wrap_pet"] [class*="st-key-station_PET"] button,
    [class*="st-key-station_wrap_supply"] [class*="st-key-station_SUPPLY"] button,
    [class*="st-key-station_wrap_onsite"] [class*="st-key-station_ONSITE"] button {
        position:absolute !important; inset:0 !important; width:100% !important; height:150px !important;
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

        div[data-testid="stDialog"] [data-testid="stDialogContent"] {
            overflow:hidden !important;
            scrollbar-width:none !important;
        }

        div[data-testid="stDialog"] [data-testid="stDialogContent"] > div {
            zoom:.68 !important;
            width:147.06% !important;
            max-width:147.06% !important;
        }
    }


    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# CENTERED CASE DETAILS — visual override based on supplied reference image.
# This changes only the dialog presentation; the underlying Caseflow logic
# remains unchanged.
# ============================================================
st.markdown(r"""
<style>
/* Center the Streamlit dialog instead of rendering it as the old right drawer. */
/* CASE DETAILS — compact fit-to-modal layout.
   The complete workspace is scaled down slightly so the Case Information,
   Case Actions and Knowledge Base columns fit inside the modal without
   creating a vertical scrollbar. */
div[data-testid="stDialog"] > div {
    position: fixed !important;
    top: 50% !important;
    left: 50% !important;
    right: auto !important;
    bottom: auto !important;
    transform: translate(-50%, -50%) !important;
    width: min(1400px, calc(100vw - 28px)) !important;
    max-width: min(1400px, calc(100vw - 28px)) !important;
    height: min(94vh, 900px) !important;
    max-height: calc(100vh - 28px) !important;
    margin: 0 !important;
    border-radius: 12px !important;
    overflow: hidden !important;
    box-shadow: 0 18px 60px rgba(15,23,42,.28) !important;
    border: 1px solid #dbe4ef !important;
}

div[data-testid="stDialog"] [data-testid="stDialogContent"] {
    padding: 0 8px 6px 8px !important;
    height: calc(100% - 54px) !important;
    max-height: calc(100% - 54px) !important;
    overflow: hidden !important;
    overflow-y: hidden !important;
    overflow-x: hidden !important;
    scrollbar-width: none !important;
}

div[data-testid="stDialog"] [data-testid="stDialogContent"]::-webkit-scrollbar,
div[data-testid="stDialog"] > div > div::-webkit-scrollbar {
    display: none !important;
    width: 0 !important;
    height: 0 !important;
}

div[data-testid="stDialog"] header {
    min-height: 50px !important;
    height: 50px !important;
    padding: 5px 14px !important;
    background: linear-gradient(180deg,#f7fbff 0%,#edf4fb 100%) !important;
    border-bottom: 1px solid #dce5ef !important;
}

div[data-testid="stDialog"] header p {
    font-size: 20px !important;
    font-weight: 800 !important;
    color: #102041 !important;
}

div[data-testid="stDialog"] > div > div {
    overflow: hidden !important;
    overflow-y: hidden !important;
    overflow-x: hidden !important;
    scrollbar-width: none !important;
}

/* Scale the actual Case Details workspace, not the modal shell/header. */
div[data-testid="stDialog"] [data-testid="stDialogContent"] > div {
    zoom: .78 !important;
    width: 128.205% !important;
    max-width: 128.205% !important;
    box-sizing: border-box !important;
}

/* Compact the top summary so the three-column workspace gets more vertical room. */
div[data-testid="stDialog"] .case-detail-hero {
    margin: 0 0 5px 0 !important;
    padding: 4px 6px 3px 6px !important;
}
div[data-testid="stDialog"] .case-folder-icon { font-size: 25px !important; }
div[data-testid="stDialog"] .case-detail-case-number { font-size: 17px !important; }
div[data-testid="stDialog"] .case-detail-subject { font-size: 15px !important; margin-top: 3px !important; }
div[data-testid="stDialog"] .case-detail-description { font-size: 10px !important; line-height: 1.25 !important; }
div[data-testid="stDialog"] .case-detail-timing { min-width: 520px !important; }
div[data-testid="stDialog"] .case-timing-item { padding: 1px 14px !important; }
div[data-testid="stDialog"] .case-timing-item span { font-size: 9px !important; }
div[data-testid="stDialog"] .case-timing-item strong { font-size: 11px !important; }
div[data-testid="stDialog"] .case-timing-icon { font-size: 16px !important; }

div[data-testid="stDialog"] .case-summary-strip {
    padding: 4px 5px !important;
    margin: 2px 0 4px !important;
}
div[data-testid="stDialog"] .case-summary-cell { padding: 1px 9px !important; }
div[data-testid="stDialog"] .case-summary-cell > span { font-size: 8px !important; margin-bottom: 2px !important; }
div[data-testid="stDialog"] .case-summary-cell > strong { font-size: 10px !important; }
div[data-testid="stDialog"] .case-avatar { width: 28px !important; height: 28px !important; font-size: 10px !important; }
div[data-testid="stDialog"] .case-status-chip { padding: 3px 7px !important; font-size: 9px !important; }

div[data-testid="stDialog"] [data-baseweb="tab"] {
    padding: 6px 11px !important;
    font-size: 10px !important;
}


/* Compact the three workspace columns so their full contents fit in the modal. */
div[data-testid="stDialog"] .case-card {
    padding: 7px 9px !important;
    border-radius: 6px !important;
}
div[data-testid="stDialog"] .case-card-heading {
    font-size: 11px !important;
    padding-bottom: 5px !important;
    margin-bottom: 4px !important;
    gap: 5px !important;
}
div[data-testid="stDialog"] .case-heading-icon {
    font-size: 15px !important;
}
div[data-testid="stDialog"] .case-info-row {
    grid-template-columns: 95px minmax(0,1fr) !important;
    gap: 5px !important;
    padding: 3px 0 !important;
    line-height: 1.15 !important;
}
div[data-testid="stDialog"] .case-info-row span { font-size: 8.5px !important; }
div[data-testid="stDialog"] .case-info-row strong { font-size: 9px !important; }

div[data-testid="stDialog"] .action-readonly-label {
    font-size: 8px !important;
    margin-top: 3px !important;
}
div[data-testid="stDialog"] .action-readonly-value {
    font-size: 9px !important;
    padding: 5px 7px !important;
    margin-top: 2px !important;
}
div[data-testid="stDialog"] .case-checklist-wrap {
    margin-top: 5px !important;
    padding: 6px !important;
}
div[data-testid="stDialog"] .case-checklist-title {
    font-size: 9px !important;
}
div[data-testid="stDialog"] .case-checklist-sub {
    font-size: 7.5px !important;
    line-height: 1.2 !important;
}
div[data-testid="stDialog"] .case-checklist-status {
    font-size: 7.5px !important;
    padding: 2px 5px !important;
}
div[data-testid="stDialog"] [data-testid="stCheckbox"] {
    min-height: 22px !important;
}
div[data-testid="stDialog"] [data-testid="stCheckbox"] label {
    font-size: 8px !important;
    line-height: 1.1 !important;
}
div[data-testid="stDialog"] [data-testid="stTextInput"] input {
    height: 28px !important;
    min-height: 28px !important;
    font-size: 9px !important;
}
div[data-testid="stDialog"] [data-testid="stSelectbox"] {
    font-size: 9px !important;
}
div[data-testid="stDialog"] [data-testid="stSelectbox"] input,
div[data-testid="stDialog"] [data-testid="stSelectbox"] button {
    min-height: 28px !important;
    height: 28px !important;
    font-size: 9px !important;
}
div[data-testid="stDialog"] button {
    min-height: 28px !important;
    height: auto !important;
    padding: 4px 8px !important;
    font-size: 9px !important;
}
div[data-testid="stDialog"] .kb-inline-card {
    padding: 7px 8px !important;
}
div[data-testid="stDialog"] .kb-inline-card .stCaption,
div[data-testid="stDialog"] .kb-inline-card [data-testid="stCaptionContainer"] {
    font-size: 8px !important;
    line-height: 1.2 !important;
}
div[data-testid="stDialog"] .kb-result-title {
    font-size: 9px !important;
}
div[data-testid="stDialog"] .kb-answer-card {
    padding: 7px !important;
    margin-bottom: 5px !important;
}

/* Streamlit renders raw HTML wrappers around separate widgets as empty
   elements. Hide those empty shells so no stray blank boxes appear above
   Case Information, Case Actions, or Knowledge Base. */
div[data-testid="stDialog"] .case-card:empty {
    display: none !important;
}

.case-detail-hero {
    margin: 0 0 8px 0;
    padding: 7px 8px 5px 8px;
    background: #fff;
}
.case-detail-title-row { display:flex; justify-content:space-between; gap:20px; align-items:flex-start; }
.case-detail-title-left { display:flex; gap:12px; min-width:0; flex:1; }
.case-folder-icon { color:#0879c9; font-size:30px; line-height:1; margin-top:2px; }
.case-detail-case-number { color:#0d1937; font-size:20px; font-weight:850; line-height:1.15; }
.case-copy-icon { color:#0879c9; font-size:18px; margin-left:7px; }
.case-priority-badge { margin-left:12px; vertical-align:middle; font-size:12px !important; padding:6px 15px !important; }
.case-detail-subject { color:#0d1937; font-size:18px; font-weight:800; margin-top:5px; }
.case-detail-description { color:#334155; font-size:11.5px; line-height:1.35; margin-top:3px; max-width:850px; }
.case-detail-timing { display:flex; align-items:stretch; gap:0; min-width:600px; }
.case-timing-item { display:flex; align-items:flex-start; gap:7px; padding:2px 22px; border-left:1px solid #dfe6ee; position:relative; }
.case-timing-item:first-child { border-left:0; }
.case-timing-item > div { display:flex; flex-direction:column; }
.case-timing-item span { font-size:10px; color:#526078; }
.case-timing-item strong { color:#102041; font-size:12.5px; white-space:nowrap; margin-top:2px; }
.case-timing-icon { color:#0879c9 !important; font-size:20px !important; line-height:1 !important; }
.case-timing-item.due .case-timing-icon { color:#e51c3a !important; }
.case-timing-item.due strong { color:#d9213d; }
.case-due-badge { display:inline-block; align-self:center; background:#ffdfe4; color:#dc1938 !important; border-radius:6px; padding:5px 8px; font-size:10px !important; font-weight:800; margin-left:6px; white-space:nowrap; }
.case-due-badge.overdue { background:#ffe3e3; color:#b91c1c !important; }

.case-summary-strip {
    display:grid;
    grid-template-columns:1.25fr 1fr 1.05fr 1.3fr 1.05fr 1.2fr 1.2fr;
    background:#f4f8fc;
    border:1px solid #e2eaf2;
    border-radius:8px;
    padding:7px 6px;
    margin:3px 0 6px;
}
.case-summary-cell { padding:2px 13px; border-left:1px solid #cbd6e2; min-width:0; }
.case-summary-cell:first-child { border-left:0; }
.case-summary-cell > span { display:block; color:#334155; font-size:10px; margin-bottom:3px; }
.case-summary-cell > strong { display:block; color:#0d1937; font-size:12px; line-height:1.25; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.case-assignee { display:flex; align-items:center; gap:8px; }
.case-assignee > div:last-child { min-width:0; }
.case-avatar { width:34px; height:34px; border-radius:50%; background:#94a8bf; color:#fff; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:800; flex:none; }
.priority-text { color:#e51c3a !important; }
.case-status-chip { display:inline-block; background:#ffe8b0; color:#8a5a00; border-radius:5px; padding:4px 10px; font-size:11px; }

/* Make Streamlit tabs resemble the reference's compact navigation strip. */
div[data-testid="stDialog"] [data-baseweb="tab-list"] { gap:0 !important; border-bottom:1px solid #dbe4ee !important; }
div[data-testid="stDialog"] [data-baseweb="tab"] { padding:9px 15px !important; color:#334155 !important; font-size:12px !important; }
div[data-testid="stDialog"] [aria-selected="true"] { color:#0879c9 !important; font-weight:800 !important; }

.case-card { background:#fff; border:1px solid #e1e8f0; border-radius:7px; padding:10px 13px; box-shadow:0 1px 3px rgba(15,23,42,.025); min-height:100%; width:100%; box-sizing:border-box; }
.case-workspace-col { min-width:0; }
div[data-testid="stDialog"] [data-testid="stHorizontalBlock"] { align-items:flex-start !important; }
div[data-testid="stDialog"] [data-testid="stHorizontalBlock"] > div { min-width:0 !important; }
.case-card-heading { display:flex; align-items:center; gap:8px; color:#102041; font-size:14px; font-weight:800; border-bottom:1px solid #e6edf4; padding-bottom:8px; margin-bottom:7px; }
.case-heading-icon { color:#0879c9; font-size:20px; }
.case-info-row { display:grid; grid-template-columns:125px minmax(0,1fr); gap:8px; padding:5px 0; border-bottom:1px solid #edf1f5; line-height:1.3; }
.case-info-row:last-child { border-bottom:0; }
.case-info-row span { color:#526078; font-size:11.5px; }
.case-info-row strong { color:#172b52; font-size:11.8px; font-weight:600; word-break:break-word; }
.vendor-brand { color:#172b52; font-size:19px; font-weight:850; padding:4px 0 8px; }
.quick-actions { margin-top:11px; background:#e7f7f5; border-radius:7px; padding:9px; }
.quick-actions-title { color:#0b766e; font-size:12px; font-weight:800; margin-bottom:8px; }
.quick-actions-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:5px; }
.quick-actions-grid div { background:#fff; border:1px solid #d8e6e9; border-radius:5px; padding:7px 4px; text-align:center; color:#0879c9; font-size:10px; font-weight:700; }
.action-readonly-label { color:#526078; font-size:10px; margin-top:6px; }
.action-readonly-value { border:1px solid #d8e1ea; border-radius:5px; background:#f8fafc; color:#172b52; font-size:12px; padding:7px 9px; margin-top:3px; }
.case-actions-card [data-testid="stSelectbox"] { margin-top:5px; }
.case-history-card { margin-top:9px; }
.history-row { display:flex; gap:10px; position:relative; padding:7px 0; }
.history-dot { width:13px; height:13px; border-radius:50%; background:#0879c9; flex:none; margin-top:4px; box-shadow:0 0 0 3px #e7f2fb; }
.history-main { border-bottom:1px solid #edf1f5; padding-bottom:7px; flex:1; }
.history-meta { color:#64748b; font-size:10px; }
.history-meta span { margin-left:12px; color:#334155; font-weight:600; }
.history-action { color:#172b52; font-size:12px; margin-top:3px; }
.case-resolution-card { margin-top:9px; }
.resolution-label { color:#526078; font-size:10px; font-weight:800; margin-top:6px; }
.resolution-value { color:#172b52; font-size:12px; line-height:1.45; background:#f8fafc; border:1px solid #e3eaf1; border-radius:5px; padding:8px; margin-top:3px; }
.communication-card { border:1px solid #e2e8f0; border-radius:8px; padding:10px 12px; margin-bottom:8px; background:#fafcfe; color:#334155; font-size:12px; line-height:1.45; }
.communication-head { display:flex; justify-content:space-between; gap:12px; margin-bottom:5px; color:#172b52; }
.communication-head span { color:#64748b; font-size:10px; }
.attachment-row { display:flex; justify-content:space-between; gap:12px; padding:10px 12px; border:1px solid #e2e8f0; border-radius:7px; margin-bottom:7px; color:#172b52; font-size:12px; }
.attachment-row > span:last-child { color:#64748b; font-size:10px; }
.case-detail-footer { height:3px; }
.case-checklist-wrap { margin-top:9px; background:#f7fbff; border:1px solid #dce8f3; border-radius:7px; padding:9px; }
.case-checklist-title { color:#102041; font-size:12px; font-weight:850; margin-bottom:3px; }
.case-checklist-sub { color:#64748b; font-size:9.5px; line-height:1.35; margin-bottom:7px; }
.case-checklist-status { display:inline-flex; align-items:center; gap:5px; border-radius:999px; padding:4px 8px; font-size:9px; font-weight:800; margin-bottom:7px; }
.case-checklist-status.complete { background:#dcf8df; color:#218137; }
.case-checklist-status.pending { background:#fff1d6; color:#a56a00; }
.case-actions-note { color:#64748b; font-size:9.5px; line-height:1.35; margin:5px 0 8px; }
.case-action-divider { height:1px; background:#e8eef4; margin:9px 0; }
.kb-inline-card { overflow:hidden; }
.kb-mini-best { background:#f3f8ff; border:1px solid #bcd8f2; border-left:4px solid #0879c9; border-radius:7px; padding:9px; margin:5px 0 7px; }
.kb-mini-label { color:#0879c9; font-size:9px; font-weight:850; letter-spacing:.5px; }
.kb-mini-title { color:#102041; font-size:12px; font-weight:800; margin-top:3px; line-height:1.25; }
.kb-mini-text { color:#334155; font-size:10.5px; line-height:1.35; margin-top:4px; }
.kb-mini-meta { color:#64748b; font-size:9px; margin-top:6px; }
.kb-mini-result { display:flex; flex-direction:column; gap:3px; padding:7px 8px; border:1px solid #e2e8f0; border-radius:6px; margin-top:5px; background:#fff; }
.kb-mini-result strong { color:#172b52; font-size:10.5px; }
.kb-mini-result span { color:#64748b; font-size:9.5px; line-height:1.3; }
.kb-panel{background:#f7f9fc;border:1px solid #e3e9f1;border-radius:10px;padding:12px;margin:6px 0 9px}
.kb-panel-header{display:flex;align-items:center;justify-content:space-between;gap:10px}
.kb-title{color:#122442;font-size:16px;font-weight:850}
.kb-subtitle{color:#64748b;font-size:10.5px;line-height:1.4;margin-top:3px}
.kb-auto-badge{background:#e9f5ff;color:#0879c9;border-radius:999px;padding:4px 7px;font-size:9px;font-weight:800}
.kb-answer-card{background:#fff;border:1px solid #dce5ef;border-radius:8px;padding:10px;margin-top:8px}
.kb-answer-card.best{border:1.5px solid #0879c9;box-shadow:0 3px 12px rgba(8,121,201,.07)}
.kb-answer-label{color:#0879c9;font-size:9px;font-weight:850;letter-spacing:.35px}
.kb-result-title{color:#102041;font-size:12px;font-weight:800;margin-top:3px}
.kb-result-text{color:#334155;font-size:10.5px;line-height:1.4;margin-top:4px}
.kb-meta{margin-top:6px;color:#64748b;font-size:9px}
.kb-source-pill{display:inline-block;background:#edf2f8;color:#5d6c82;border-radius:10px;padding:3px 7px;font-size:9px;font-weight:750;margin-right:4px}


@media (max-width: 1100px) {
    div[data-testid="stDialog"] > div { width:calc(100vw - 24px) !important; max-width:calc(100vw - 24px) !important; height:calc(100vh - 24px) !important; max-height:calc(100vh - 24px) !important; }
    .case-detail-title-row { flex-direction:column; }
    .case-detail-timing { min-width:0; width:100%; }
    .case-summary-strip { grid-template-columns:repeat(3,1fr); }
    .case-summary-cell:nth-child(4) { border-left:0; }
}
@media (max-width: 760px) {
    .case-detail-case-number { font-size:19px; }
    .case-detail-subject { font-size:17px; }
    .case-detail-timing { display:grid; grid-template-columns:1fr; }
    .case-timing-item { border-left:0; border-top:1px solid #e5eaf0; padding:7px 4px; }
    .case-summary-strip { grid-template-columns:repeat(2,1fr); }
    .case-summary-cell { border-left:0; border-top:1px solid #d7e0e9; }
    .case-summary-cell:nth-child(-n+2) { border-top:0; }
}
</style>
""", unsafe_allow_html=True)


# ============================================================
# ============================================================
# CASE DETAILS — COMPACT DESKTOP MODAL / RESPONSIVE SCROLL
# ============================================================
st.markdown(r"""
<style>
/*
   CASE DETAILS SIZING
   The dashboard reference is approximately 1366px wide.  Keep the case
   dialog clearly smaller than the dashboard instead of allowing it to span
   almost the entire viewport.
*/
div[data-testid="stDialog"] > div {
    position: fixed !important;
    top: 50% !important;
    left: 50% !important;
    right: auto !important;
    bottom: auto !important;
    transform: translate(-50%, -50%) !important;

    /* Desktop target: compact, centered, approximately 3/4 of the viewport. */
    width: min(1080px, calc(100vw - 72px)) !important;
    max-width: min(1080px, calc(100vw - 72px)) !important;

    height: min(76vh, 540px) !important;
    max-height: calc(100vh - 48px) !important;

    margin: 0 !important;
    overflow: hidden !important;
    border-radius: 12px !important;
}

/* The modal itself does not scroll horizontally.
   Its content is the ONE vertical scroll surface. */
div[data-testid="stDialog"] [data-testid="stDialogContent"] {
    height: calc(100% - 48px) !important;
    max-height: calc(100% - 48px) !important;
    min-height: 0 !important;
    overflow-y: auto !important;
    overflow-x: hidden !important;
    padding: 0 12px 12px 12px !important;
    scrollbar-width: auto !important;
    scrollbar-color: #8fa3b9 #edf2f7 !important;
}

div[data-testid="stDialog"] [data-testid="stDialogContent"]::-webkit-scrollbar {
    width: 9px !important;
    display: block !important;
}
div[data-testid="stDialog"] [data-testid="stDialogContent"]::-webkit-scrollbar-track {
    background: #edf2f7 !important;
    border-radius: 8px !important;
}
div[data-testid="stDialog"] [data-testid="stDialogContent"]::-webkit-scrollbar-thumb {
    background: #8fa3b9 !important;
    border-radius: 8px !important;
    border: 2px solid #edf2f7 !important;
}

div[data-testid="stDialog"] [data-testid="stDialogContent"] > div {
    width: 100% !important;
    max-width: 100% !important;
    min-width: 0 !important;
    zoom: 1 !important;
    box-sizing: border-box !important;
}

div[data-testid="stDialog"] > div > div {
    overflow: hidden !important;
}

/* Compact header — still readable at the smaller modal size. */
div[data-testid="stDialog"] header {
    min-height: 48px !important;
    height: 48px !important;
    padding: 5px 14px !important;
}
div[data-testid="stDialog"] header p {
    font-size: 17px !important;
    font-weight: 800 !important;
}

/* Case hero */
div[data-testid="stDialog"] .case-detail-hero {
    margin: 0 0 5px 0 !important;
    padding: 5px 6px 4px 6px !important;
}
div[data-testid="stDialog"] .case-detail-case-number {
    font-size: 15px !important;
}
div[data-testid="stDialog"] .case-detail-subject {
    font-size: 13px !important;
    margin-top: 3px !important;
}
div[data-testid="stDialog"] .case-detail-description {
    font-size: 9.5px !important;
    line-height: 1.3 !important;
}
div[data-testid="stDialog"] .case-detail-timing {
    min-width: 0 !important;
}
div[data-testid="stDialog"] .case-timing-item {
    padding: 1px 9px !important;
}
div[data-testid="stDialog"] .case-timing-item span {
    font-size: 8px !important;
}
div[data-testid="stDialog"] .case-timing-item strong {
    font-size: 9.5px !important;
}
div[data-testid="stDialog"] .case-timing-icon {
    font-size: 14px !important;
}
div[data-testid="stDialog"] .case-due-badge {
    font-size: 8px !important;
    padding: 3px 5px !important;
}

/* Case summary: seven compact fields without forcing horizontal overflow. */
div[data-testid="stDialog"] .case-summary-strip {
    grid-template-columns: 1.15fr 1fr 1fr 1.25fr 1fr 1.05fr 1.05fr !important;
    padding: 4px 4px !important;
    margin: 2px 0 5px !important;
}
div[data-testid="stDialog"] .case-summary-cell {
    padding: 2px 6px !important;
}
div[data-testid="stDialog"] .case-summary-cell > strong {
    font-size: 9px !important;
}
div[data-testid="stDialog"] .case-assignee {
    gap: 5px !important;
}
div[data-testid="stDialog"] .case-assignee-copy > span {
    font-size: 8px !important;
}
div[data-testid="stDialog"] .case-assignee-copy > strong {
    font-size: 9px !important;
    font-weight: 600 !important;
    line-height: 1.15 !important;
    white-space: normal !important;
}
div[data-testid="stDialog"] .case-avatar {
    width: 25px !important;
    height: 25px !important;
    font-size: 8.5px !important;
}
div[data-testid="stDialog"] .case-status-chip {
    padding: 2px 6px !important;
    font-size: 8px !important;
}

/* Tabs */
div[data-testid="stDialog"] [data-baseweb="tab-list"] {
    gap: 0 !important;
}
div[data-testid="stDialog"] [data-baseweb="tab"] {
    padding: 7px 11px !important;
    font-size: 9.5px !important;
}

/* Cards and information rows */
div[data-testid="stDialog"] .case-card {
    padding: 7px 9px !important;
    border-radius: 6px !important;
}
div[data-testid="stDialog"] .case-card-heading {
    font-size: 10px !important;
    padding-bottom: 5px !important;
    margin-bottom: 4px !important;
    gap: 5px !important;
}
div[data-testid="stDialog"] .case-heading-icon {
    font-size: 13px !important;
}
div[data-testid="stDialog"] .case-info-row {
    grid-template-columns: 94px minmax(0,1fr) !important;
    gap: 5px !important;
    padding: 3px 0 !important;
    line-height: 1.2 !important;
}
div[data-testid="stDialog"] .case-info-row span {
    font-size: 8px !important;
}
div[data-testid="stDialog"] .case-info-row strong {
    font-size: 8.7px !important;
}
div[data-testid="stDialog"] .action-readonly-value {
    font-size: 9px !important;
    padding: 5px 7px !important;
}
div[data-testid="stDialog"] [data-testid="stCheckbox"] label {
    font-size: 8px !important;
    line-height: 1.15 !important;
}
div[data-testid="stDialog"] input {
    font-size: 9px !important;
}
div[data-testid="stDialog"] button {
    font-size: 9px !important;
}

/* Two-column Knowledge Base */
div[data-testid="stDialog"] .kb-full-sop,
div[data-testid="stDialog"] .kb-recommendation {
    margin-top: 7px !important;
    padding: 8px !important;
    background: #f7fbff !important;
    border: 1px solid #d7e6f4 !important;
    border-radius: 7px !important;
}
div[data-testid="stDialog"] .kb-full-sop-label {
    color:#0879c9 !important;
    font-size:8px !important;
    font-weight:850 !important;
    letter-spacing:.3px !important;
    margin-bottom:4px !important;
}
div[data-testid="stDialog"] .kb-full-sop-text {
    color:#334155 !important;
    font-size:8.5px !important;
    line-height:1.35 !important;
    word-break:break-word !important;
}
div[data-testid="stDialog"] [class*="st-key-kb_tile_"] {
    margin: 3px 0 !important;
}
div[data-testid="stDialog"] [class*="st-key-kb_tile_"] button {
    width:100% !important;
    min-height:32px !important;
    height:auto !important;
    padding:5px 7px !important;
    text-align:left !important;
    justify-content:flex-start !important;
    white-space:normal !important;
    line-height:1.2 !important;
    font-size:8.5px !important;
}

/* Prevent inner columns from creating a second horizontal scroll. */
div[data-testid="stDialog"] [data-testid="stHorizontalBlock"] {
    align-items:flex-start !important;
    max-width:100% !important;
}
div[data-testid="stDialog"] [data-testid="stHorizontalBlock"] > div {
    min-width:0 !important;
    max-width:100% !important;
}

/*
   The modal should remain compact on the same 1366px desktop shown in the
   reference image, but expand naturally on smaller screens.
*/
@media (max-width: 1120px) {
    div[data-testid="stDialog"] > div {
        width:calc(100vw - 40px) !important;
        max-width:calc(100vw - 40px) !important;
        height:min(80vh, 600px) !important;
        max-height:calc(100vh - 32px) !important;
    }

    div[data-testid="stDialog"] .case-summary-strip {
        grid-template-columns:repeat(4,minmax(0,1fr)) !important;
    }
}

@media (max-width: 760px) {
    div[data-testid="stDialog"] > div {
        width:calc(100vw - 20px) !important;
        max-width:calc(100vw - 20px) !important;
        height:calc(100vh - 20px) !important;
        max-height:calc(100vh - 20px) !important;
    }

    div[data-testid="stDialog"] .case-detail-title-row {
        flex-direction:column !important;
    }
    div[data-testid="stDialog"] .case-detail-timing {
        width:100% !important;
    }
    div[data-testid="stDialog"] .case-summary-strip {
        grid-template-columns:repeat(2,minmax(0,1fr)) !important;
    }
    div[data-testid="stDialog"] .case-summary-cell {
        border-left:0 !important;
        border-top:1px solid #d7e0e9 !important;
    }
    div[data-testid="stDialog"] .case-summary-cell:nth-child(-n+2) {
        border-top:0 !important;
    }
}

/* FINAL CASE DETAILS SCROLL FIX
   The previous compact overrides explicitly hid the scroll surface.
   Keep the modal compact, but make the dialog content itself the scroll area. */
div[data-testid="stDialog"] > div {
    overflow:hidden !important;
}

div[data-testid="stDialog"] > div > div {
    height:calc(100% - 48px) !important;
    max-height:calc(100% - 48px) !important;
    min-height:0 !important;
    overflow-y:auto !important;
    overflow-x:hidden !important;
    scrollbar-width:thin !important;
    scrollbar-color:#7f94aa #edf2f7 !important;
}

div[data-testid="stDialog"] > div > div::-webkit-scrollbar {
    width:10px !important;
    display:block !important;
}

div[data-testid="stDialog"] > div > div::-webkit-scrollbar-track {
    background:#edf2f7 !important;
    border-radius:8px !important;
}

div[data-testid="stDialog"] > div > div::-webkit-scrollbar-thumb {
    background:#7f94aa !important;
    border-radius:8px !important;
    border:2px solid #edf2f7 !important;
}

/* Do not hide the scrollbar on the nested Streamlit content element. */
div[data-testid="stDialog"] [data-testid="stDialogContent"] {
    height:auto !important;
    max-height:none !important;
    min-height:0 !important;
    overflow:visible !important;
    overflow-y:visible !important;
    overflow-x:visible !important;
    scrollbar-width:auto !important;
}

/* Preserve the compact 1366x768 desktop proportion while leaving enough
   height for the user to scroll through complete case information. */
@media (min-width:1121px) {
    div[data-testid="stDialog"] > div {
        width:min(1080px,calc(100vw - 72px)) !important;
        max-width:min(1080px,calc(100vw - 72px)) !important;
        height:min(680px,calc(100vh - 48px)) !important;
        max-height:calc(100vh - 48px) !important;
    }
}
</style>
""", unsafe_allow_html=True)





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
        "station_warning_ack_trigger": 1,
        "station_warning_acknowledged_at": 1,
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




@st.cache_data(ttl=15, show_spinner=False)
def _account_priority_lookup(account_name):
    account_name = text(account_name)
    if not account_name:
        return False
    try:
        record = col(ACCOUNT_PRIORITY_COLLECTION).find_one({
            "account_name": account_name,
            "account_priority": {"$in": ["High", "HIGH", "Yes", "YES", "Critical", "CRITICAL", True, 1]},
        }, {"_id": 1})
        if record:
            return True
    except Exception:
        pass
    try:
        record = col(TASKS_COLLECTION).find_one({
            "account_name": account_name,
            "source_type": "excel",
            "account_priority": {"$in": ["Yes", "YES", "High", "HIGH", "Critical", "CRITICAL", True, 1]},
        }, {"_id": 1})
        return bool(record)
    except Exception:
        return False


def account_priority_status(task):
    """Resolve account priority from the case record or Excel-backed account mapping."""
    if is_priority(task.get("account_priority")):
        return True
    return _account_priority_lookup(task.get("account_name"))



def station_warning_trigger_key(task, station=None):
    """Stable identifier for one SLA-warning cycle of one case/station."""
    station = station_name(station or task.get("department"))
    started = iso_z(task.get("station_started_at") or task.get("created_at"))
    task_id = text(task.get("_id")) or text(task.get("case_number"))
    return sha256(f"{station}|{task_id}|{started}|{STATIONS.get(station, STATIONS['CARE']).get('sla_minutes', 0)}")[:32]


def acknowledge_station_warning_cycle(task_list):
    """Persist the currently flashing station-warning cycles as acknowledged."""
    try:
        now = utc_now()
        for task in task_list:
            col(TASKS_COLLECTION).update_one(
                {"_id": task.get("_id")},
                {"$set": {
                    "station_warning_ack_trigger": station_warning_trigger_key(task),
                    "station_warning_acknowledged_at": now,
                }},
            )
    except Exception:
        pass
    clear_task_cache()
    try:
        _account_priority_lookup.clear()
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


    priority_account = account_priority_status(task)


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
    # These are deliberately aligned with the HPE/Aruba KB/SOP subjects so
    # opening a mock case immediately demonstrates a meaningful KB match.
    "CARE": [
        "HPE ProLiant / iLO Alert Troubleshooting",
        "Aruba Central Device Offline",
        "HPE Alletra Storage Capacity Warning",
        "Aruba ClearPass Endpoint Profiling",
        "HPE Licensing Portal Access",
    ],
    "ARCH": [
        "HPE IMC Licensing",
        "AirWave Licensing",
        "ArubaOS / AOS Licensing",
        "HPE iLO 6 User Guide - Configuration Reference",
        "HPE Gen11 Server Setup and Configuration Guide",
    ],
    "PET": [
        "Aruba ClearPass Endpoint Profiling",
        "Aruba Central Device Offline",
        "Aruba Switch Configuration Guide",
        "ArubaOS / AOS Licensing",
        "HPE Intelligent Management Center (IMC) Licensing",
    ],
    "SUPPLY CHAIN": [
        "HPE ProLiant Hardware Replacement",
        "Aruba CX Switch Onsite Support",
        "HPE Alletra Storage Hardware Support",
        "Aruba AP Hardware / Replacement Support",
        "HPE Licensing Entitlement Verification",
    ],
    "ONSITE": [
        "HPE ProLiant / iLO Alert Troubleshooting",
        "Aruba CX Switch Onsite Support",
        "HPE Gen11 Server Setup and Configuration Guide",
        "HPE iLO 6 User Guide - Configuration Reference",
        "Aruba Switch Configuration Guide",
    ],
}


MOCK_CASE_CONTEXT = {
    "CARE": [
        {"product": "HPE ProLiant DL380 Gen11", "category": "HPE Compute", "issue": "iLO hardware alert requires triage.", "next_action": "Capture iLO event details, serial number and hardware health before escalation."},
        {"product": "Aruba AP-515", "category": "Aruba Networking", "issue": "Device is showing offline in Aruba Central.", "next_action": "Verify last-seen time, uplink, power and device connectivity path."},
        {"product": "HPE Alletra", "category": "HPE Storage", "issue": "Storage capacity warning reported by the array.", "next_action": "Capture array/site, current capacity and recent capacity trend."},
        {"product": "Aruba ClearPass", "category": "Aruba Security", "issue": "Endpoint profiling does not match the expected policy.", "next_action": "Capture endpoint identifier, authentication method and enforcement profile."},
        {"product": "HPE Licensing Portal", "category": "HPE Licensing", "issue": "Customer cannot access licensing entitlement information.", "next_action": "Validate account, entitlement and exact portal error."},
    ],
    "ARCH": [
        {"product": "HPE IMC", "category": "HPE Networking", "issue": "Customer requested IMC license capacity documentation.", "next_action": "Verify edition, current managed-device count and target node count."},
        {"product": "Aruba AirWave", "category": "Aruba Networking", "issue": "License record needs validation for an AirWave environment.", "next_action": "Review the AirWave License page and record current license/device counts."},
        {"product": "ArubaOS / AOS", "category": "Aruba Licensing", "issue": "Customer needs the correct licensing model for managed devices.", "next_action": "Identify deployment model and device class before validating Foundation/Advanced licensing."},
        {"product": "HPE iLO 6", "category": "HPE Compute", "issue": "Customer requested iLO configuration reference material.", "next_action": "Retrieve the applicable iLO 6 guide and confirm server generation."},
        {"product": "HPE ProLiant Gen11", "category": "HPE Compute", "issue": "Customer requested Gen11 setup/configuration documentation.", "next_action": "Validate server model and retrieve the applicable setup guide."},
    ],
    "PET": [
        {"product": "Aruba ClearPass", "category": "Aruba Security", "issue": "Endpoint authentication/profiling request requires review.", "next_action": "Review request/event details and confirm classification before policy changes."},
        {"product": "Aruba Central", "category": "Aruba Networking", "issue": "Managed device appears offline.", "next_action": "Confirm serial number, site, last-seen time and connectivity path."},
        {"product": "Aruba CX Switch", "category": "Aruba Networking", "issue": "Switch configuration guidance is required.", "next_action": "Confirm switch model and applicable AOS-CX configuration requirement."},
        {"product": "ArubaOS / AOS", "category": "Aruba Licensing", "issue": "License tier needs validation for an Aruba deployment.", "next_action": "Identify AP, switch, gateway or controller model and deployment architecture."},
        {"product": "HPE IMC", "category": "HPE Networking", "issue": "Managed-device license capacity requires verification.", "next_action": "Verify the included 50-device capacity and required additional nodes."},
    ],
    "SUPPLY CHAIN": [
        {"product": "HPE ProLiant", "category": "HPE Compute", "issue": "Replacement hardware shipment is pending.", "next_action": "Validate part number, shipment reference, destination and expected delivery."},
        {"product": "Aruba CX Switch", "category": "Aruba Networking", "issue": "Switch replacement shipment requires fulfillment validation.", "next_action": "Confirm model, quantity, PO/shipment reference and destination site."},
        {"product": "HPE Alletra", "category": "HPE Storage", "issue": "Storage hardware delivery is delayed.", "next_action": "Verify tracking, receiving contact and supplier exception details."},
        {"product": "Aruba AP", "category": "Aruba Networking", "issue": "AP inventory or replacement quantity needs reconciliation.", "next_action": "Validate part numbers, quantities and receiving records."},
        {"product": "HPE Licensing", "category": "HPE Licensing", "issue": "Entitlement fulfillment requires validation.", "next_action": "Confirm customer account, entitlement and licensing reference."},
    ],
    "ONSITE": [
        {"product": "HPE ProLiant DL380 Gen11", "category": "HPE Compute", "issue": "Onsite support is required for an iLO/hardware alert.", "next_action": "Confirm model, serial, site access and remote troubleshooting before dispatch."},
        {"product": "Aruba CX Switch", "category": "Aruba Networking", "issue": "Onsite technician support is required for the switch.", "next_action": "Confirm switch model, serial, site contact and replacement/technician scope."},
        {"product": "HPE ProLiant Gen11", "category": "HPE Compute", "issue": "Server setup/configuration support is required onsite.", "next_action": "Confirm server generation, installation scope and site access requirements."},
        {"product": "HPE iLO 6", "category": "HPE Compute", "issue": "Onsite configuration assistance is requested for iLO 6.", "next_action": "Validate server model and capture the required iLO configuration scope."},
        {"product": "Aruba CX Switch", "category": "Aruba Networking", "issue": "Switch configuration support is required onsite.", "next_action": "Confirm AOS-CX version, model, site details and configuration objective."},
    ],
}


MOCK_NAMES = CASEFLOW_ASSIGNEES


MOCK_ACCOUNTS = [
    "HPE Aruba Networking Demo Lab",
    "Enterprise Customer - BGC",
    "Enterprise Customer - Makati",
    "Enterprise Customer - Cavite",
    "Enterprise Customer - Quezon City",
]


# Increment this whenever mock content/checklists change so the old demo
# records are rebuilt with the new HPE/Aruba content.
MOCK_DATA_VERSION = 16


def mock_original_state(case_number):
    """Return the original seeded state for one of the 25 deterministic mock cases."""
    match = re.search(r"-(\d{4})$", text(case_number))
    if not match:
        return None

    case_index = int(match.group(1))
    if case_index < 1 or case_index > 25:
        return None

    station_order = list(STATIONS.keys())
    station = station_order[(case_index - 1) // 5]
    item_index = (case_index - 1) % 5
    context = MOCK_CASE_CONTEXT[station][item_index]
    account = MOCK_ACCOUNTS[item_index % len(MOCK_ACCOUNTS)]
    priority_account = item_index == 0
    started = utc_now()
    checklist = {
        station: [
            {"item": item, "checked": False}
            for item in STATION_CHECKLISTS[station]
        ]
    }

    return {
        "subject": MOCK_SUBJECTS[station][item_index],
        "priority": "Critical" if priority_account else ("Medium" if item_index == 1 else "Low"),
        "account_priority": "Yes" if priority_account else "No",
        "assigned_to": MOCK_NAMES[item_index % len(MOCK_NAMES)],
        "department": station,
        "account_name": account,
        "vendor": "HPE Services" if item_index % 2 == 0 else "Aruba Networking Services",
        "issue": context["issue"],
        "description": (
            f"HPE/Aruba demonstration case for {station_name(station)}. "
            f"Device: {context['product']}. {context['issue']} "
            "The case is intentionally aligned with a Knowledge Base/SOP topic "
            "so the integrated guidance panel can demonstrate retrieval."
        ),
        "product": context["product"],
        "category": context["category"],
        "related_system": context["product"],
        "resolution": "Pending current-station checklist completion and SOP-guided assessment.",
        "next_action": context["next_action"],
        "notes": "HPE/Aruba mock case for Caseflow + Knowledge Base demonstration.",
        "status": "In Progress" if item_index % 2 == 0 else "Open",
        "active": True,
        "is_mock": True,
        "mock_data_version": MOCK_DATA_VERSION,
        "station_checklists": checklist,
        "history": [{"action": f"Case entered {station_name(station)}", "timestamp": started}],
    }


def reset_mock_case_durations():
    """Reset all 25 mock cases to their original seeded state and SLA demo timing.

    The reset intentionally restores the original station, assignee, status,
    checklist and seeded case fields first. This means mock cases may be moved
    and updated during a demonstration, but Reset always returns them to the
    state in which they were originally seeded.
    """
    reset_now = utc_now()
    elapsed_ratios = [0.00, 0.50, 0.80, 0.95, 1.00]
    total_reset = 0
    reset_task_ids = []

    mock_cases = list(
        col(TASKS_COLLECTION).find(
            {
                "is_mock": True,
                "case_number": {"$not": {"$regex": "^SIM-"}},
            },
            {"_id": 1, "case_number": 1},
        ).sort("case_number", ASCENDING)
    )

    for case in mock_cases:
        original = mock_original_state(case.get("case_number"))
        if not original:
            continue

        station = original["department"]
        station_index = (int(text(case["case_number"])[-4:]) - 1) % 5
        sla_seconds = int(STATIONS[station]["sla_minutes"] * 60)
        ratio = elapsed_ratios[station_index]
        elapsed_seconds = int(sla_seconds * ratio)
        started_at = reset_now - timedelta(seconds=elapsed_seconds)
        due_date = started_at + timedelta(seconds=sla_seconds)

        restore = dict(original)
        restore.update({
            "created_at": started_at,
            "station_started_at": started_at,
            "last_update": reset_now,
            "due_date": due_date,
            "mock_data_version": MOCK_DATA_VERSION,
        })

        try:
            from bson import ObjectId
            result = col(TASKS_COLLECTION).update_one(
                {"_id": ObjectId(str(case["_id"]))},
                {
                    "$set": restore,
                    "$unset": {
                        "case_action_log": "",
                        "meetings": "",
                        "communications": "",
                        "communication_history": "",
                        "attachments": "",
                        "files": "",
                        "war_room": "",
                        "station_warning_ack_trigger": "",
                        "station_warning_acknowledged_at": "",
                    },
                },
            )
            if result.matched_count:
                total_reset += 1
                reset_task_ids.append(str(case["_id"]))
        except Exception:
            continue

    # Remove stale alerts from the demonstration state. A reset starts a
    # completely new mock-case/SLA cycle and must not inherit prior alerts.
    if reset_task_ids:
        try:
            col(ALERT_COLLECTION).delete_many({"task_id": {"$in": reset_task_ids}})
        except Exception:
            pass

    clear_task_cache()
    return total_reset


@st.cache_resource(show_spinner=False)
def seed_mock_cases(force=False):
    existing = col(TASKS_COLLECTION).count_documents({"is_mock": True})

    # Rebuild old demonstration data whenever the content version changes so
    # new HPE/Aruba subjects, assignees and checklists actually appear.
    if existing and not force:
        old_version = col(TASKS_COLLECTION).count_documents({
            "is_mock": True,
            "mock_data_version": {"$ne": MOCK_DATA_VERSION},
            "case_number": {"$not": {"$regex": "^SIM-"}},
        })
        if old_version:
            col(TASKS_COLLECTION).delete_many({"is_mock": True})
            existing = 0
        else:
            return existing

    if force:
        col(TASKS_COLLECTION).delete_many({"is_mock": True})

    now = utc_now()
    docs = []
    case_index = 1

    for station, config in STATIONS.items():
        subjects = MOCK_SUBJECTS[station]
        contexts = MOCK_CASE_CONTEXT[station]
        for i in range(5):
            subject = subjects[i]
            context = contexts[i]
            account = MOCK_ACCOUNTS[i % len(MOCK_ACCOUNTS)]
            priority_account = i == 0
            started = now
            due = now + timedelta(minutes=config["sla_minutes"])
            checklist = {
                station: [
                    {"item": item, "checked": False}
                    for item in STATION_CHECKLISTS[station]
                ]
            }
            docs.append({
                "case_number": f"{station[:3].upper()}-2026-{case_index:04d}",
                "subject": subject,
                "priority": "Critical" if priority_account else ("Medium" if i == 1 else "Low"),
                "account_priority": "Yes" if priority_account else "No",
                "assigned_to": MOCK_NAMES[i % len(MOCK_NAMES)],
                "department": station,
                "account_name": account,
                "vendor": "HPE Services" if i % 2 == 0 else "Aruba Networking Services",
                "issue": context["issue"],
                "description": (
                    f"HPE/Aruba demonstration case for {station_name(station)}. "
                    f"Device: {context['product']}. {context['issue']} "
                    "The case is intentionally aligned with a Knowledge Base/SOP topic "
                    "so the integrated guidance panel can demonstrate retrieval."
                ),
                "product": context["product"],
                "category": context["category"],
                "related_system": context["product"],
                "resolution": "Pending current-station checklist completion and SOP-guided assessment.",
                "next_action": context["next_action"],
                "notes": "HPE/Aruba mock case for Caseflow + Knowledge Base demonstration.",
                "status": "In Progress" if i % 2 == 0 else "Open",
                "created_at": started,
                "station_started_at": started,
                "due_date": due,
                "last_update": now,
                "active": True,
                "is_mock": True,
                "mock_data_version": MOCK_DATA_VERSION,
                "station_checklists": checklist,
                "history": [{"action": f"Case entered {station_name(station)}", "timestamp": started}],
            })
            case_index += 1

    if docs:
        col(TASKS_COLLECTION).insert_many(docs)
    clear_task_cache()
    return len(docs)


# ============================================================
# ALERT ENGINE
# ============================================================






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




def acknowledge_station_alerts(station, trigger_keys=None):
    """Acknowledge only the active warning triggers represented by the clicked tile."""
    query = {
        "station": station,
        "acknowledged": False,
    }
    if trigger_keys:
        query["trigger_key"] = {"$in": list(trigger_keys)}

    col(ALERT_COLLECTION).update_many(
        query,
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
    candidate_trigger_keys = {
        station_warning_trigger_key(task, station_name(task.get("department")))
        for task, _, _ in candidates
    }
    try:
        existing = {
            (
                str(doc.get("task_id")),
                doc.get("alert_type"),
                text(doc.get("trigger_key")),
            )
            for doc in col(ALERT_COLLECTION).find(
                {
                    "task_id": {"$in": task_ids},
                    "trigger_key": {"$in": list(candidate_trigger_keys)},
                },
                {"task_id": 1, "alert_type": 1, "trigger_key": 1},
            )
        }
    except Exception:
        existing = set()

    docs = []
    created_at = utc_now()

    for task, alert_type, message in candidates:
        trigger_key = station_warning_trigger_key(task, station_name(task.get("department")))
        key = (str(task["_id"]), alert_type, trigger_key)
        if key in existing:
            continue
        docs.append({
            "task_id": str(task["_id"]),
            "case_number": task.get("case_number"),
            "station": station_name(task.get("department")),
            "account_name": task.get("account_name"),
            "alert_type": alert_type,
            "trigger_key": trigger_key,
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




def sync_account_priority_excel(uploaded_file):
    """Synchronize account priority mapping from an Excel workbook."""
    try:
        df = pd.read_excel(uploaded_file)
        if df.empty:
            return False, "The Account Priority Excel file is empty.", 0

        def normalize(value):
            return text(value).lower().strip().replace("#", "number").replace("/", "_").replace("-", "_").replace(" ", "_")

        df.columns = [normalize(c) for c in df.columns]
        aliases = {
            "account": "account_name",
            "accountname": "account_name",
            "customer": "account_name",
            "customer_name": "account_name",
            "accountpriority": "account_priority",
            "priority": "account_priority",
            "account_priority": "account_priority",
        }
        df = df.rename(columns=aliases)
        if "account_name" not in df.columns or "account_priority" not in df.columns:
            return False, "Required columns: Account Name and Account Priority.", 0

        docs = []
        for _, row in df.iterrows():
            account = text(row.get("account_name"))
            if not account:
                continue
            raw = text(row.get("account_priority"))
            high = is_priority(raw) or raw.lower() in {"high", "critical", "p1", "p0"}
            docs.append({
                "account_name": account,
                "account_priority": "High" if high else "Normal",
                "source_type": "account_priority_excel",
                "synced_at": utc_now(),
            })

        collection = col(ACCOUNT_PRIORITY_COLLECTION)
        collection.delete_many({})
        if docs:
            collection.insert_many(docs)
        try:
            _account_priority_lookup.clear()
        except Exception:
            pass
        return True, f"{len(docs)} account-priority records synchronized.", len(docs)
    except Exception as exc:
        return False, str(exc), 0


def import_cases_excel(uploaded_file, replace_existing_excel=False):
    """Import case records from an Excel workbook into Tasks_Collection.


    The workbook mirrors the case fields used by the dashboard. Existing records
    with the same Case # are updated, while new Case # values are inserted.
    Imported rows are tagged source_type='excel' so they can be replaced safely.
    """
    try:
        df = pd.read_excel(uploaded_file)


        if df.empty:
            return False, "The Excel file is empty.", 0


        def normalize_column(value):
            return (
                text(value).lower().strip()
                .replace("#", "number")
                .replace("/", "_")
                .replace("-", "_")
                .replace(" ", "_")
            )


        df.columns = [normalize_column(c) for c in df.columns]


        aliases = {
            "case": "case_number",
            "case_no": "case_number",
            "case_no.": "case_number",
            "case_number": "case_number",
            "case_number_": "case_number",
            "caseid": "case_number",
            "case_id": "case_number",
            "account": "account_name",
            "accountname": "account_name",
            "department": "department",
            "station": "department",
            "assigned": "assigned_to",
            "assignedto": "assigned_to",
            "accountpriority": "account_priority",
            "account_priority": "account_priority",
            "created": "created_at",
            "created_date": "created_at",
            "created_datetime": "created_at",
            "station_started": "station_started_at",
            "station_start": "station_started_at",
            "due": "due_date",
            "due_datetime": "due_date",
            "last_update_date": "last_update",
            "isactive": "active",
        }
        df = df.rename(columns=aliases)


        required = {"case_number", "subject", "department"}
        missing = sorted(required - set(df.columns))
        if missing:
            return (
                False,
                "Missing required column(s): " + ", ".join(missing),
                0,
            )


        def parse_datetime(value, fallback=None):
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return fallback
            parsed = pd.to_datetime(value, errors="coerce", utc=True)
            if pd.isna(parsed):
                return fallback
            return parsed.to_pydatetime()


        def parse_bool(value, default=True):
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return default
            return text(value).lower() in {
                "true", "yes", "y", "1", "active", "open"
            }


        now = utc_now()
        operations = []
        skipped = 0


        if replace_existing_excel:
            col(TASKS_COLLECTION).delete_many({"source_type": "excel"})


        for _, row in df.iterrows():
            case_number = text(row.get("case_number"))
            subject = text(row.get("subject"))


            if not case_number or not subject:
                skipped += 1
                continue


            station = station_name(row.get("department"))
            if station not in STATIONS:
                skipped += 1
                continue


            created_at = parse_datetime(row.get("created_at"), now)
            started_at = parse_datetime(row.get("station_started_at"), created_at)
            due_default = started_at + timedelta(
                minutes=STATIONS[station]["sla_minutes"]
            )
            due_date = parse_datetime(row.get("due_date"), due_default)
            last_update = parse_datetime(row.get("last_update"), now)


            priority = text(row.get("priority")) or "Low"
            account_priority = (
                "Yes" if is_priority(row.get("account_priority")) else "No"
            )


            active = parse_bool(row.get("active"), True)
            raw_is_mock = parse_bool(row.get("is_mock"), False)


            doc = {
                "case_number": case_number,
                "subject": subject,
                "priority": priority,
                "account_priority": account_priority,
                "assigned_to": text(row.get("assigned_to")) or "Unassigned",
                "department": station,
                "account_name": text(row.get("account_name")),
                "vendor": text(row.get("vendor")),
                "issue": text(row.get("issue")) or subject,
                "description": text(row.get("description")),
                "status": text(row.get("status")) or "Open",
                "created_at": created_at,
                "station_started_at": started_at,
                "due_date": due_date,
                "last_update": last_update,
                "notes": text(row.get("notes")),
                "active": active,
                "is_mock": raw_is_mock,
                "source_type": "excel",
                "history": [{
                    "action": f"Case imported into {station}",
                    "timestamp": now,
                }],
            }


            operations.append(
                ReplaceOne(
                    {"case_number": case_number},
                    doc,
                    upsert=True,
                )
            )


        if operations:
            col(TASKS_COLLECTION).bulk_write(operations, ordered=False)
            clear_task_cache()


        imported = len(operations)
        return True, (
            f"{imported} case record(s) imported successfully"
            + (f"; {skipped} row(s) skipped." if skipped else ".")
        ), imported


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
# CASE CHECKLIST / ASSIGNMENT
# ============================================================


def _default_station_checklist(station):
    station = station_name(station)
    return [
        {"item": item, "checked": False}
        for item in STATION_CHECKLISTS.get(station, [])
    ]


def get_case_station_checklist(task, station=None):
    """Return the persisted checklist for a station, falling back to defaults."""
    station = station_name(station or task.get("department"))
    stored = task.get("station_checklists") or {}
    items = stored.get(station) if isinstance(stored, dict) else None
    if not isinstance(items, list) or not items:
        return _default_station_checklist(station)

    normalized = []
    for item in items:
        if isinstance(item, dict):
            label = text(item.get("item") or item.get("label"))
            if label:
                normalized.append({"item": label, "checked": bool(item.get("checked"))})
        else:
            label = text(item)
            if label:
                normalized.append({"item": label, "checked": False})
    return normalized or _default_station_checklist(station)




def checklist_missing(task, station=None):
    return [
        text(item.get("item"))
        for item in get_case_station_checklist(task, station)
        if not bool(item.get("checked"))
    ]


def save_case_station_checklist(task_id, station, items):
    station = station_name(station)
    clean_items = []
    for item in items:
        label = text(item.get("item") or item.get("label")) if isinstance(item, dict) else text(item)
        if label:
            clean_items.append({
                "item": label,
                "checked": bool(item.get("checked")) if isinstance(item, dict) else False,
            })

    try:
        from bson import ObjectId
        now = utc_now()
        task = col(TASKS_COLLECTION).find_one({"_id": ObjectId(str(task_id))}) or {}
        previous_items = get_case_station_checklist(task, station)
        was_complete = bool(previous_items) and all(bool(x.get("checked")) for x in previous_items)
        is_complete = bool(clean_items) and all(bool(x.get("checked")) for x in clean_items)

        update = {
            "$set": {
                f"station_checklists.{station}": clean_items,
                "last_update": now,
            }
        }

        # When the current station checklist becomes complete, create one
        # readable bullet-form history/current-note entry. The transition guard
        # prevents duplicate entries on subsequent rerenders.
        if is_complete and not was_complete:
            bullets = "\n".join(f"• {text(x.get('item'))}" for x in clean_items if text(x.get("item")))
            history = list(task.get("history") or [])
            history.append({
                "action": f"{station_display_name(station)} checklist completed:\n{bullets}",
                "timestamp": now,
                "actor": "Caseflow",
            })
            update["$set"]["history"] = history
            update["$set"]["notes"] = f"{station_display_name(station)} checklist completed:\n{bullets}"

        col(TASKS_COLLECTION).update_one(
            {"_id": ObjectId(str(task_id))},
            update,
        )
        clear_task_cache()
        return True
    except Exception:
        return False


def set_case_checklist_item(task_id, station, index, checked):
    # Streamlit callbacks pass the widget key so the current checkbox value
    # can be read from session_state at callback time.
    if isinstance(checked, str) and checked in st.session_state:
        checked = st.session_state.get(checked, False)
    station = station_name(station)
    try:
        from bson import ObjectId
        task = col(TASKS_COLLECTION).find_one({"_id": ObjectId(str(task_id))})
        if not task:
            return False
        items = get_case_station_checklist(task, station)
        if index < 0 or index >= len(items):
            return False
        items[index]["checked"] = bool(checked)
        return save_case_station_checklist(task_id, station, items)
    except Exception:
        return False




def remove_case_checklist_item(task_id, station, index):
    """Remove one checklist item from the selected station without changing other stations."""
    station = station_name(station)
    try:
        from bson import ObjectId
        task = col(TASKS_COLLECTION).find_one({"_id": ObjectId(str(task_id))})
        if not task:
            return False
        items = get_case_station_checklist(task, station)
        if index < 0 or index >= len(items):
            return False
        items.pop(index)
        return save_case_station_checklist(task_id, station, items)
    except Exception:
        return False


def save_case_action_log(task_id, action_plan, note, logged_by="Caseflow User"):
    """Persist an action-plan/note entry and mirror the latest values to the case."""
    action_plan = text(action_plan)
    note = text(note)
    if not action_plan and not note:
        return False, "Enter an action plan or note before saving."
    try:
        from bson import ObjectId
        now = utc_now()
        task = col(TASKS_COLLECTION).find_one({"_id": ObjectId(str(task_id))}) or {}
        station = station_name(task.get("department"))
        actor = text(logged_by) or "Caseflow User"
        record = {
            "timestamp": now,
            "action_plan": action_plan,
            "note": note,
            "logged_by": actor,
            "station": station,
        }
        history = list(task.get("history") or [])
        history.append({
            "action": (
                f"{station_display_name(station)} action plan/note logged."
                + (f"\n• Action Plan: {action_plan}" if action_plan else "")
                + (f"\n• Case Note: {note}" if note else "")
            ),
            "timestamp": now,
            "actor": actor,
            "station": station,
        })
        result = col(TASKS_COLLECTION).update_one(
            {"_id": ObjectId(str(task_id))},
            {
                "$push": {"case_action_log": {"$each": [record]}},
                "$set": {
                    "next_action": action_plan,
                    "notes": note,
                    "last_update": now,
                    "history": history,
                },
            },
        )
        clear_task_cache()
        try:
            _account_priority_lookup.clear()
        except Exception:
            pass
        return result.modified_count > 0, ""
    except Exception as exc:
        return False, f"Unable to save the action plan and note: {exc}"


def reassign_case(task, assignee):
    assignee = text(assignee)
    current = station_name(task.get("department"))
    if not assignee or assignee == text(task.get("assigned_to")):
        return False, "Choose a different assignee."
    missing = checklist_missing(task, current)
    if missing:
        return False, "Complete the current-station checklist before reassigning this case."
    try:
        from bson import ObjectId
        now = utc_now()
        history = list(task.get("history") or [])
        history.append({
            "action": f"Reassigned within {current} from {text(task.get('assigned_to')) or 'Unassigned'} to {assignee}",
            "timestamp": now,
            "assigned_to": assignee,
        })
        result = col(TASKS_COLLECTION).update_one(
            {"_id": ObjectId(str(task["_id"]))},
            {"$set": {
                "assigned_to": assignee,
                "last_update": now,
                "history": history,
            }},
        )
        clear_task_cache()
        return result.modified_count > 0, ""
    except Exception as exc:
        return False, f"Unable to reassign case: {exc}"


def close_case(task):
    """Close a case only from the final FULFILLMENT/ONSITE station after its checklist is complete."""
    current_station = station_name(task.get("department"))
    if current_station != "ONSITE":
        return False, "Case can only be closed from FULFILLMENT."

    missing = checklist_missing(task, current_station)
    if missing:
        return False, "Complete every FULFILLMENT checklist item before closing the case."

    try:
        from bson import ObjectId
        now = utc_now()
        history = list(task.get("history") or [])
        history.append({
            "action": (
                "Case closed from FULFILLMENT after completing the final station checklist."
            ),
            "timestamp": now,
            "actor": text(task.get("assigned_to")) or "Caseflow",
            "station": current_station,
        })

        result = col(TASKS_COLLECTION).update_one(
            {"_id": ObjectId(str(task["_id"]))},
            {
                "$set": {
                    "status": "Closed",
                    "active": False,
                    "last_update": now,
                    "resolution": "Case closed after completing the FULFILLMENT checklist.",
                    "next_action": "No further station transfer required.",
                    "history": history,
                }
            },
        )
        clear_task_cache()
        return result.modified_count > 0, ""
    except Exception as exc:
        return False, f"Unable to close case: {exc}"


# ============================================================
# CASE TRANSFER
# ============================================================


def transfer_case(task, destination):
    current_station = station_name(task.get("department"))
    missing = checklist_missing(task, current_station)
    if missing:
        return False

    now = utc_now()


    history = task.get(
        "history",
        []
    )


    source_station = station_name(task.get("department"))
    destination_station = station_name(destination)

    history.append({
        "action": (
            f"Transferred from {station_display_name(source_station)} "
            f"to {station_display_name(destination_station)}"
        ),
        "timestamp": now,
        "actor": text(task.get("assigned_to")) or "Caseflow",
    })
    history.append({
        "action": (
            f"Entered {station_display_name(destination_station)} station. "
            f"SLA clock reset to {STATIONS.get(destination_station, STATIONS['CARE'])['sla_minutes']} minutes."
        ),
        "timestamp": now,
        "actor": text(task.get("assigned_to")) or "Caseflow",
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
                    "history": history,
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


# CSS/HTML recreation of the supplied HPE Caseflow reference.
# The uploaded image itself is NOT used. Search and Settings remain native
# Streamlit controls so all existing functionality is preserved.
with st.container(key="caseflow_header_shell"):


    header_cols = st.columns([31, 44, 5], gap="small")


    with header_cols[0]:
        st.markdown(
            """
            <div class="caseflow-brand" aria-label="OVR-VW">
                <div class="caseflow-hpe-symbol" aria-hidden="true"></div>
                <div class="caseflow-hpe-copy">
                    <div class="caseflow-hpe-word">HPE</div>
                    <div class="caseflow-hpe-tagline">Accelerating what's next together</div>
                </div>
                <div class="caseflow-divider" aria-hidden="true"></div>
                <div class="caseflow-title">OVR-VW</div>
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

            st.markdown(
                """
                <style>
                /* Replace the password-field's Material 'visibility' text with an eye icon. */
                div[data-testid="stDialog"] [data-testid="stTextInput"] button {
                    font-size:0 !important;
                    width:34px !important;
                    min-width:34px !important;
                    height:34px !important;
                }
                div[data-testid="stDialog"] [data-testid="stTextInput"] button::after {
                    content:"👁" !important;
                    font-size:18px !important;
                    line-height:1 !important;
                    color:#102041 !important;
                }
                </style>
                """,
                unsafe_allow_html=True,
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
                "Account Priority",
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
            # ACCOUNT PRIORITY EXCEL
            # -----------------------------------------------
            with tabs[1]:
                st.markdown("### Account Priority")
                st.caption(
                    "Upload an Excel mapping of Account Name to Account Priority. "
                    "High/Critical accounts automatically make their active cases CRITICAL."
                )
                priority_file = st.file_uploader(
                    "Account Priority Excel",
                    type=["xlsx", "xls"],
                    key="account_priority_excel_upload",
                )
                if priority_file is not None:
                    try:
                        preview_priority = pd.read_excel(priority_file)
                        st.dataframe(preview_priority.head(8), use_container_width=True, hide_index=True)
                    except Exception as exc:
                        st.error(f"Unable to preview the Account Priority file: {exc}")
                    if st.button(
                        "Import Account Priorities",
                        type="primary",
                        use_container_width=True,
                        key="import_account_priority_excel",
                    ):
                        with st.spinner("Importing account priorities..."):
                            ok, msg, _count = sync_account_priority_excel(priority_file)
                        if ok:
                            st.success(msg)
                            clear_task_cache()
                            st.rerun()
                        else:
                            st.error(msg)
                st.info("Recommended columns: Account Name, Account Priority. Example: H&M | High")


            # -----------------------------------------------
            # EXTERNAL SYNC
            # -----------------------------------------------


            with tabs[2]:


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


            with tabs[3]:


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


            with tabs[4]:


                st.markdown(
                    "### Alert Simulation"
                )


                st.caption(
                    "Creates a temporary CARE case with approximately 5 seconds remaining. "
                    "Use this to demonstrate flashing, critical status and the central alert."
                )


                if st.button(
                    "↻ Reset Mock Due Dates & Durations",
                    type="secondary",
                    use_container_width=True,
                    key="reset_mock_case_durations",
                    help="Reset all 25 seeded HPE/Aruba mock cases with five different elapsed-duration states per station so green, yellow, red, critical and breached alerts can be demonstrated.",
                ):
                    reset_count = reset_mock_case_durations()
                    st.session_state["simulation_until"] = 0.0
                    st.session_state["simulation_case_id"] = None
                    st.session_state["station_warning_ack_until"] = {}
                    st.session_state["station_warning_silenced"] = set()
                    st.session_state["station_warning_latched"] = set()
                    st.success(
                        f"{reset_count} mock case(s) reset with staggered durations and due dates."
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




# ============================================================
# INTEGRATED KNOWLEDGE BASE — local MongoDB retrieval, no API key required
# ============================================================
def kb_text(doc):
    fields = [doc.get("title"), doc.get("subject"), doc.get("question"),
              doc.get("keywords"), doc.get("category"), doc.get("answer"),
              doc.get("content"), doc.get("body"), doc.get("summary"),
              doc.get("resolution"), doc.get("sop")]
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
    words = {x.strip(".,:;!?()[]{}").lower() for x in text(query).split()
             if len(x.strip(".,:;!?()[]{}")) >= 3}
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
        score += sum(3 for keyword in keywords if any(word in text(keyword).lower() for word in words))
    return score


@st.cache_data(ttl=30, show_spinner=False)
def load_kb_documents():
    """Load Caseflow KB/SOP records plus the shared HPE Knowledge Base.

    The standalone HPE Knowledge Base stores AI-ready records in the HPE
    database using `Knowledge base` and `Knowledge base Documents`.  Caseflow
    consumes those records read-only so the Case Details panel can surface the
    same SOP content without requiring a second API or a duplicate KB.
    """
    docs = []

    # Caseflow-local KB/SOP collections.
    for collection_name in [KB_COLLECTION, SOP_COLLECTION]:
        try:
            docs.extend(list(col(collection_name).find({}, {
                "_id": 1, "title": 1, "subject": 1, "question": 1,
                "keywords": 1, "category": 1, "answer": 1, "content": 1,
                "body": 1, "summary": 1, "description": 1, "resolution": 1,
                "sop": 1, "steps": 1, "source": 1, "source_type": 1, "url": 1,
            }).limit(1000)))
        except Exception:
            pass

    # Shared standalone HPE Knowledge Base.  It is optional: if the same
    # MongoDB cluster/secret is not available, Caseflow simply keeps using its
    # local KB without breaking the dashboard.
    try:
        uri = text(st.secrets.get("MONGODB_URI", ""))
        if not uri:
            uri = text(os.getenv("MONGO_URI", ""))
        if not uri:
            try:
                uri = text(st.secrets.get("mongo", {}).get("uri", ""))
            except Exception:
                uri = ""

        if uri:
            shared_client = MongoClient(
                uri,
                serverSelectionTimeoutMS=2500,
                connectTimeoutMS=2500,
                socketTimeoutMS=5000,
            )
            shared_db = shared_client["HPE"]

            for record in shared_db["Knowledge base"].find({}, {
                "_id": 1, "kb_id": 1, "family": 1, "topic": 1,
                "question": 1, "answer": 1, "steps": 1,
                "keywords": 1, "source": 1, "source_url": 1,
            }).sort("created_at", -1).limit(1500):
                docs.append({
                    "_id": f"hpe-kb:{text(record.get('kb_id')) or text(record.get('_id'))}",
                    "title": text(record.get("topic")) or text(record.get("question")) or text(record.get("kb_id")) or "HPE Knowledge Base Article",
                    "subject": text(record.get("question")),
                    "question": text(record.get("question")),
                    "keywords": record.get("keywords") or [],
                    "category": text(record.get("family")) or "HPE Knowledge Base",
                    "answer": text(record.get("answer")),
                    "content": text(record.get("steps")),
                    "steps": text(record.get("steps")),
                    "source": text(record.get("source")) or "HPE Knowledge Base",
                    "source_type": "shared_hpe_kb",
                    "url": text(record.get("source_url")),
                })

            for record in shared_db["Knowledge base Documents"].find({}, {
                "_id": 1, "doc_id": 1, "title": 1, "filename": 1,
                "family": 1, "topic": 1, "source_url": 1,
                "content": 1, "doc_type": 1,
            }).sort("created_at", -1).limit(1000):
                docs.append({
                    "_id": f"hpe-doc:{text(record.get('doc_id')) or text(record.get('_id'))}",
                    "title": text(record.get("title")) or text(record.get("filename")) or "HPE Knowledge Document",
                    "subject": text(record.get("topic")),
                    "question": text(record.get("topic")),
                    "keywords": [text(record.get("family")), text(record.get("topic"))],
                    "category": text(record.get("family")) or "HPE Knowledge Base",
                    "content": text(record.get("content")),
                    "answer": text(record.get("content")),
                    "source": text(record.get("filename")) or "HPE Knowledge Base Document",
                    "source_type": "shared_hpe_document",
                    "url": text(record.get("source_url")),
                })

            try:
                shared_client.close()
            except Exception:
                pass
    except Exception:
        pass

    # De-duplicate shared/local records by title + source while preserving the
    # first (usually richer) record.
    unique = []
    seen = set()
    for doc in docs:
        key = (
            text(doc.get("title")).strip().lower(),
            text(doc.get("source")).strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(doc)
    return unique


def search_kb(query, limit=5):
    ranked = [(kb_score(query, doc), doc) for doc in load_kb_documents() if kb_score(query, doc) > 0]
    ranked.sort(key=lambda x: -x[0])
    return [doc for _, doc in ranked[:limit]]


def case_kb_query(task):
    return " ".join(x for x in [
        text(task.get("subject")), text(task.get("issue")),
        station_name(task.get("department")), text(task.get("account_name")),
        text(task.get("product")), text(task.get("category")),
    ] if x)


def seed_demo_kb():
    try:
        if col(KB_COLLECTION).count_documents({}) or col(SOP_COLLECTION).count_documents({}):
            return
        docs = [
            {"title":"HPE ProLiant / iLO Alert Troubleshooting","category":"HPE Compute","keywords":["HPE","ProLiant","iLO","server","alert","hardware"],"answer":"Verify the server model and serial number, capture the iLO alert code, review hardware health and recent events, and confirm whether the issue is recoverable remotely before escalation or onsite dispatch.","source":"HPE Caseflow Knowledge Base","source_type":"demo"},
            {"title":"Aruba Central Device Offline","category":"Aruba Networking","keywords":["Aruba","Central","offline","AP","switch","network"],"answer":"Confirm the device serial number, site, last-seen time and connectivity path. Check Aruba Central status and the local uplink/power state. Document the exact error and last successful contact before escalation.","source":"HPE Caseflow Knowledge Base","source_type":"demo"},
            {"title":"HPE Licensing Portal Access","category":"HPE Licensing","keywords":["HPE","licensing","portal","access","entitlement","login"],"answer":"Validate the customer account, entitlement and exact portal error. Capture the affected user/email and licensing reference. If entitlement is valid but access remains blocked, follow the approved licensing/account-access escalation path.","source":"HPE Caseflow Knowledge Base","source_type":"demo"},
            {"title":"Aruba ClearPass Endpoint Profiling","category":"Aruba ClearPass","keywords":["Aruba","ClearPass","endpoint","profiling","policy","authentication"],"answer":"Capture the endpoint identifier, authentication method, enforcement profile and timestamp. Review the ClearPass request/event details and confirm whether the endpoint is being classified correctly before changing policy.","source":"HPE Caseflow Knowledge Base","source_type":"demo"},
            {"title":"HPE Alletra Storage Capacity Warning","category":"HPE Storage","keywords":["HPE","Alletra","storage","capacity","warning","array"],"answer":"Confirm the array/site, affected system and current capacity threshold. Capture the alert details and recent capacity trend. Follow the applicable storage monitoring and escalation SOP before making configuration changes.","source":"HPE Caseflow Knowledge Base","source_type":"demo"},
            {"title":"Aruba CX Switch Onsite Support","category":"Aruba CX","keywords":["Aruba","CX","switch","onsite","replacement","technician"],"answer":"Confirm the switch model, serial number, site address, onsite contact, access requirements and symptoms. Verify whether remote troubleshooting has been completed and document the replacement/dispatch requirement.","source":"HPE Caseflow Knowledge Base","source_type":"demo"},
        ]
        col(KB_COLLECTION).insert_many(docs)
    except Exception:
        pass


def _kb_inline_format(value):
    """Small, dependency-free markdown-like formatter for KB text."""
    value = html.escape(text(value))
    parts = value.split("**")
    if len(parts) == 1:
        return value
    out = []
    for idx, part in enumerate(parts):
        if idx % 2:
            out.append(f"<strong>{part}</strong>")
        else:
            out.append(part)
    return "".join(out)


def kb_rich_html(content):
    """Render KB/SOP content as readable HTML with real headings and lists."""
    lines = text(content).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    html_lines = []
    in_ul = False
    in_ol = False

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            html_lines.append("</ul>")
            in_ul = False
        if in_ol:
            html_lines.append("</ol>")
            in_ol = False

    for raw in lines:
        line = text(raw).strip()
        if not line:
            close_lists()
            continue
        if line in {"---", "___", "***"}:
            close_lists()
            continue
        if line.startswith("### "):
            close_lists()
            html_lines.append(f"<div class='kb-content-heading'>{_kb_inline_format(line[4:])}</div>")
            continue
        if line.startswith("## "):
            close_lists()
            html_lines.append(f"<div class='kb-content-heading'>{_kb_inline_format(line[3:])}</div>")
            continue
        if line.startswith("# "):
            close_lists()
            html_lines.append(f"<div class='kb-content-heading'>{_kb_inline_format(line[2:])}</div>")
            continue
        if line.startswith("**") and line.endswith("**") and len(line) > 4:
            close_lists()
            html_lines.append(f"<div class='kb-content-heading'>{_kb_inline_format(line[2:-2])}</div>")
            continue
        if line.startswith("- ") or line.startswith("• "):
            if in_ol:
                html_lines.append("</ol>")
                in_ol = False
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            html_lines.append(f"<li>{_kb_inline_format(line[2:])}</li>")
            continue
        numbered = line.split(". ", 1)
        if len(numbered) == 2 and numbered[0].isdigit():
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            if not in_ol:
                html_lines.append("<ol>")
                in_ol = True
            html_lines.append(f"<li>{_kb_inline_format(numbered[1])}</li>")
            continue
        close_lists()
        html_lines.append(f"<p>{_kb_inline_format(line)}</p>")

    close_lists()
    return "".join(html_lines)


def _case_update_events(task):
    """Return timestamped human-readable updates from the case record."""
    events = []
    history = task.get("history") or []
    if isinstance(history, list):
        for item in history:
            if isinstance(item, dict):
                stamp = as_utc(item.get("timestamp") or item.get("created_at") or item.get("updated_at"))
                detail = text(item.get("action") or item.get("event") or item.get("details"))
                actor = text(item.get("user") or item.get("actor") or item.get("assigned_to"))
                if detail:
                    events.append((stamp or datetime.min.replace(tzinfo=timezone.utc), detail, actor))

    action_log = task.get("case_action_log") or []
    if isinstance(action_log, list):
        for item in action_log:
            if isinstance(item, dict):
                stamp = as_utc(item.get("timestamp") or item.get("created_at"))
                plan = text(item.get("action_plan"))
                note = text(item.get("note"))
                detail = " · ".join(x for x in [plan, note] if x)
                actor = text(item.get("logged_by"))
                if detail:
                    events.append((stamp or datetime.min.replace(tzinfo=timezone.utc), detail, actor))

    communications = task.get("communications") or task.get("communication_history") or []
    if isinstance(communications, list):
        for item in communications:
            if isinstance(item, dict):
                stamp = as_utc(item.get("timestamp") or item.get("created_at"))
                detail = text(item.get("message") or item.get("body") or item.get("details"))
                actor = text(item.get("sender") or item.get("user") or item.get("from"))
            else:
                stamp = None
                detail = text(item)
                actor = ""
            if detail:
                events.append((stamp or datetime.min.replace(tzinfo=timezone.utc), detail, actor))

    meetings = task.get("meetings") or []
    if isinstance(meetings, list):
        for item in meetings:
            if isinstance(item, dict):
                stamp = as_utc(item.get("timestamp") or item.get("created_at"))
                detail = text(item.get("actions") or item.get("details"))
                actor = text(item.get("recorded_by"))
                if detail:
                    events.append((stamp or datetime.min.replace(tzinfo=timezone.utc), detail, actor))

    fallback = as_utc(task.get("last_update") or task.get("updated_at") or task.get("created_at"))
    if fallback:
        events.append((fallback, "Case record updated.", "Caseflow"))
    return events


def automated_case_assessment(task, state):
    """Build a read-only assessment from the most recent case update and SLA state."""
    events = _case_update_events(task)
    latest = max(events, key=lambda x: x[0]) if events else None
    station = station_display_name(task.get("department")) or "Current station"
    status = text(state.get("status") or task.get("status") or "OPEN").upper()
    if state.get("past_due"):
        lead = f"SLA breached in {station}."
    elif state.get("nearing_due"):
        lead = f"SLA nearing due in {station}."
    elif status in {"RESOLVED", "CLOSED", "COMPLETED"}:
        lead = f"Case is {status.lower()} in {station}."
    else:
        lead = f"Case remains {status.lower()} in {station}."
    if latest:
        detail = latest[1].replace("\n", " ").strip()
        if len(detail) > 320:
            detail = detail[:317].rstrip() + "…"
        actor = f" · {latest[2]}" if latest[2] else ""
        return f"{lead} Most recent update: {detail}{actor}."
    return f"{lead} No detailed update has been recorded yet."






seed_demo_kb()


@st.dialog("Case Details", width="large")
def case_details(task_id):
    """Compact, centered Case Details modal using the original Caseflow data/actions.

    Tabs are deliberately separated:
      1. Case Information
      2. Case Actions
      3. Knowledge Base
      4. Collaboration
      5. Attachments

    The original MongoDB task model, SLA engine, checklist gate, transfer logic,
    reassignment logic, and local/shared KB retrieval remain the source of truth.
    """
    try:
        from bson import ObjectId
        task = col(TASKS_COLLECTION).find_one({"_id": ObjectId(str(task_id))})
    except Exception:
        task = None

    if not task:
        st.error("Case not found.")
        if st.button("Close", use_container_width=True, key=f"case_missing_close_{task_id}"):
            st.session_state["show_case"] = False
            st.session_state["selected_case_id"] = None
            st.rerun()
        return

    state = calculate_state(task)
    status = text(task.get("status", "Open")) or "Open"
    department = station_name(task.get("department")) or "CARE"
    case_number = text(task.get("case_number")) or "—"
    subject = text(task.get("subject")) or text(task.get("issue")) or "No subject available."
    description = text(task.get("description")) or text(task.get("issue")) or "No description available."
    assigned_to = text(task.get("assigned_to")) or "Unassigned"
    account_name = text(task.get("account_name")) or "—"
    account_priority_label = "HIGH" if state.get("priority_account") else "NORMAL"
    case_type = text(task.get("case_type")) or text(task.get("category")) or "—"
    related_system = text(task.get("related_system")) or text(task.get("product")) or "—"
    last_update = dt_display(task.get("last_update")) or "—"
    created = dt_display(task.get("created_at")) or "—"
    due = dt_display(task.get("due_date")) or "—"
    elapsed = duration_string(state.get("elapsed", 0))

    priority_label = "CRITICAL" if state.get("priority_account") else str(state.get("status") or "LOW").upper()
    priority_class = {
        "BREACHED": "badge-critical",
        "CRITICAL": "badge-critical",
        "MEDIUM": "badge-medium",
        "LOW": "badge-low",
    }.get(priority_label, "badge-low")

    remaining = state.get("remaining", 0)
    if remaining <= 0:
        due_badge = f"Overdue by {duration_string(abs(remaining))}"
        due_class = "case-due-badge overdue"
    else:
        due_badge = f"Due in {duration_string(remaining)}"
        due_class = "case-due-badge"

    vendor = find_vendor(task)
    vendor_name = text((vendor or {}).get("vendor_name")) or text(task.get("vendor")) or "No synchronized vendor record"
    vendor_contact = text((vendor or {}).get("contact_name")) or text((vendor or {}).get("primary_contact")) or text(task.get("vendor_contact"))
    vendor_email = text((vendor or {}).get("email")) or text(task.get("vendor_email"))

    # ---------------------------------------------------------------
    # COMPACT TOP SUMMARY
    # ---------------------------------------------------------------
    st.markdown(
        f"""
        <div class="case-detail-hero">
            <div class="case-detail-title-row">
                <div class="case-detail-title-left">
                    <div class="case-folder-icon">▣</div>
                    <div class="case-detail-copy">
                        <div class="case-detail-case-number">
                            {html.escape(case_number)}
                            <span class="case-copy-icon">▢</span>
                            <span class="badge {priority_class} case-priority-badge">{html.escape(priority_label.title())}</span>
                        </div>
                        <div class="case-detail-subject">{html.escape(subject)}</div>
                        <div class="case-detail-account-line">
                            <span><b>Account:</b> {html.escape(account_name)}</span>
                            <span class="case-account-priority {'high' if account_priority_label == 'HIGH' else 'normal'}">{html.escape(account_priority_label)} PRIORITY ACCOUNT</span>
                        </div>
                    </div>
                </div>
                <div class="case-detail-timing">
                    <div class="case-timing-item">
                        <span class="case-timing-icon">▣</span>
                        <div><span>Created</span><strong>{html.escape(created)}</strong></div>
                    </div>
                    <div class="case-timing-item due">
                        <span class="case-timing-icon">▣</span>
                        <div><span>Due Date</span><strong>{html.escape(due)}</strong></div>
                        <span class="{due_class}">{html.escape(due_badge)}</span>
                    </div>
                    <div class="case-timing-item">
                        <span class="case-timing-icon">◷</span>
                        <div><span>Total Elapsed</span><strong data-total-elapsed-live="1" data-total-elapsed-start="{html.escape(iso_z(task.get("station_started_at") or task.get("created_at")))}">{html.escape(elapsed)}</strong></div>
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    initials = "".join(p[:1] for p in assigned_to.split()[:2]) or "—"
    st.markdown(
        f"""
        <div class="case-summary-strip">
            <div class="case-summary-cell"><span>Assigned To</span><strong>{html.escape(assigned_to)}</strong></div>
            <div class="case-summary-cell"><span>Priority</span><strong class="priority-text">{html.escape(priority_label.title())}</strong></div>
            <div class="case-summary-cell"><span>Current Status</span><strong><span class="case-status-chip">{html.escape(status)}</span></strong></div>
            <div class="case-summary-cell"><span>Last Update</span><strong>{html.escape(last_update)}</strong></div>
            <div class="case-summary-cell"><span>Case Type</span><strong>{html.escape(case_type)}</strong></div>
            <div class="case-summary-cell"><span>Related System</span><strong>{html.escape(related_system)}</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Native Streamlit scroll container: this is the actual reliable scrollbar.
    # Use the dialog's native scroll surface. A fixed-height nested container
    # created the double/offset scrollbar seen in the reference screenshot.
    with st.container(border=False, key=f"case_detail_scroll_{task_id}"):
        tab_info, tab_actions, tab_kb, tab_comm, tab_attach = st.tabs([
            "ⓘ  Case Information",
            "◷  Case Actions",
            "✦  Knowledge Base",
            "✉  Collaboration",
            "♧  Attachments",
        ])

        # ---------------------------------------------------------------
        # CASE INFORMATION TAB
        # ---------------------------------------------------------------
        with tab_info:
            info_col, meta_col = st.columns([1.35, 1], gap="small")
            with info_col:
                st.markdown("<div class='case-card'>", unsafe_allow_html=True)
                st.markdown("<div class='case-card-heading'><span class='case-heading-icon'>♙</span>Case Information</div>", unsafe_allow_html=True)
                rows = [
                    ("Case #", case_number),
                    ("Subject", subject),
                    ("Account", account_name),
                    ("Account Priority", account_priority_label.title()),
                    ("Priority", priority_label.title()),
                    ("Assigned To", assigned_to),
                    ("Due Date", due),
                    ("Created Date", created),
                    ("Last Update", last_update),
                    ("Current Status", status),
                    ("Case Category", text(task.get("category")) or "—"),
                    ("Product / Device", text(task.get("product")) or related_system),
                    ("Related System", related_system),
                    ("Site / Location", text(task.get("site_location")) or "—"),
                    ("Reference Number", text(task.get("reference_number")) or "—"),
                    ("Vendor", vendor_name),
                ]
                for label, value in rows:
                    st.markdown(
                        f"<div class='case-info-row'><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>",
                        unsafe_allow_html=True,
                    )
                if vendor_contact or vendor_email:
                    vendor_line = html.escape(vendor_contact or "—")
                    if vendor_email:
                        vendor_line += " · " + html.escape(vendor_email)
                    st.markdown(
                        f"<div class='case-info-row'><span>Vendor Contact</span><strong>{vendor_line}</strong></div>",
                        unsafe_allow_html=True,
                    )
                st.markdown("</div>", unsafe_allow_html=True)

            with meta_col:
                st.markdown("<div class='case-card'>", unsafe_allow_html=True)
                st.markdown("<div class='case-card-heading'><span class='case-heading-icon'>✓</span>Resolution & Next Action</div>", unsafe_allow_html=True)
                resolution = automated_case_assessment(task, state)
                action_log = task.get("case_action_log") or []
                latest_action_log = action_log[-1] if isinstance(action_log, list) and action_log and isinstance(action_log[-1], dict) else {}
                # The bottom Case Actions log is the source of truth for the
                # action plan and note shown here. Fall back to legacy fields
                # for older cases that have not yet used the log.
                next_action = text(latest_action_log.get("action_plan")) or text(task.get("next_action"))
                notes = text(latest_action_log.get("note")) or text(task.get("notes"))
                if resolution:
                    st.markdown(f"<div class='resolution-label'>Current Resolution / Assessment</div><div class='resolution-value'>{html.escape(resolution)}</div>", unsafe_allow_html=True)
                if next_action:
                    st.markdown(f"<div class='resolution-label'>Logged Action Plan</div><div class='resolution-value'>{html.escape(next_action)}</div>", unsafe_allow_html=True)
                if notes:
                    notes_html = html.escape(notes).replace("\n", "<br>")
                    st.markdown(
                        f"<div class='resolution-label'>Logged Case Note</div>"
                        f"<div class='resolution-value'>{notes_html}</div>",
                        unsafe_allow_html=True,
                    )
                if latest_action_log.get("timestamp"):
                    logged_stamp = dt_display(latest_action_log.get("timestamp"))
                    logged_by = text(latest_action_log.get("logged_by")) or "Caseflow User"
                    st.markdown(f"<div class='resolution-log-meta'>Latest action log · {html.escape(logged_stamp)} · {html.escape(logged_by)}</div>", unsafe_allow_html=True)
                if not any([resolution, next_action, notes]):
                    st.caption("No resolution, action plan, or notes are recorded for this case.")
                st.markdown("</div>", unsafe_allow_html=True)

            history = task.get("history") or []
            st.markdown("<div class='case-card case-history-card'>", unsafe_allow_html=True)
            st.markdown("<div class='case-card-heading'><span class='case-heading-icon'>◷</span>Case History</div>", unsafe_allow_html=True)
            if history:
                for event in reversed(history):
                    if isinstance(event, dict):
                        action = text(event.get("action") or event.get("event") or event.get("details")) or "Case updated"
                        stamp = dt_display(event.get("timestamp")) or ""
                        actor = text(event.get("user") or event.get("actor") or event.get("assigned_to")) or "System"
                    else:
                        action, stamp, actor = text(event), "", "System"
                    action_html = html.escape(action).replace("\n", "<br>")
                    st.markdown(
                        f"<div class='history-row'><div class='history-dot'></div>"
                        f"<div class='history-main'><div class='history-meta'>{html.escape(stamp)} "
                        f"<span>{html.escape(actor)}</span></div>"
                        f"<div class='history-action'>{action_html}</div></div></div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No activity history is stored on this case.")
            st.markdown("</div>", unsafe_allow_html=True)

        # ---------------------------------------------------------------
        # CASE ACTIONS TAB — two-column operational workspace
        # ---------------------------------------------------------------
        with tab_actions:
            action_col, checklist_col = st.columns([1, 1.35], gap="small")
            stations = list(STATIONS.keys())
            current = department if department in stations else "CARE"

            with action_col:
                st.markdown("<div class='case-card case-actions-card'>", unsafe_allow_html=True)
                st.markdown("<div class='case-card-heading'><span class='case-heading-icon'>◷</span>Case Action</div>", unsafe_allow_html=True)
                st.markdown("<div class='action-readonly-label'>Current Status</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='action-readonly-value'>{html.escape(status)}</div>", unsafe_allow_html=True)
                st.markdown("<div class='action-readonly-label'>Current Station</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='action-readonly-value'>{html.escape(station_display_name(current))}</div>", unsafe_allow_html=True)
                st.markdown("<div class='action-readonly-label'>Current Assignee</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='action-readonly-value'>{html.escape(assigned_to)}</div>", unsafe_allow_html=True)

                assignee_options = list(dict.fromkeys(CASEFLOW_ASSIGNEES + ([assigned_to] if assigned_to else [])))
                new_assignee = st.selectbox(
                    "Reassign case to",
                    assignee_options,
                    index=assignee_options.index(assigned_to) if assigned_to in assignee_options else 0,
                    key=f"case_reassign_assignee_{task_id}",
                )
                current_missing = checklist_missing(task, current)
                if st.button("Reassign Case", use_container_width=True, key=f"case_reassign_{task_id}"):
                    if new_assignee == assigned_to:
                        st.warning("Choose a different assignee.")
                    elif current_missing:
                        st.error("Complete every item in the current-station checklist before reassigning this case.")
                    else:
                        ok, message = reassign_case(task, new_assignee)
                        if ok:
                            st.success(f"Case reassigned to {new_assignee}.")
                            st.rerun()
                        else:
                            st.error(message or "Unable to reassign case.")

                if current == "ONSITE":
                    st.markdown(
                        "<div class='action-readonly-label'>Final Station</div>"
                        "<div class='action-readonly-value'>FULFILLMENT</div>",
                        unsafe_allow_html=True,
                    )
                    if st.button(
                        "Close Case",
                        type="primary",
                        use_container_width=True,
                        key=f"case_close_{task_id}",
                        disabled=bool(current_missing),
                        help=(
                            "Complete every FULFILLMENT checklist item to enable case closure."
                            if current_missing
                            else "Close the case after the final FULFILLMENT checklist is complete."
                        ),
                    ):
                        if current_missing:
                            missing_html = "<br>• ".join(html.escape(x) for x in current_missing[:8])
                            st.error(
                                f"Complete the FULFILLMENT checklist before closing the case:<br>• {missing_html}",
                                unsafe_allow_html=True,
                            )
                        else:
                            ok, message = close_case(task)
                            if ok:
                                st.success("Case closed.")
                                st.session_state["show_case"] = False
                                st.session_state["selected_case_id"] = None
                                st.rerun()
                            else:
                                st.error(message or "Unable to close case.")

                    st.markdown(
                        "<div class='case-actions-note'>FULFILLMENT is the final station. Completing every checklist item enables case closure instead of station transfer.</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    destination = st.selectbox(
                        "Transfer to station",
                        stations,
                        index=stations.index(current),
                        format_func=station_display_name,
                        key=f"case_transfer_destination_{task_id}",
                    )
                    if st.button(
                        "Transfer Case",
                        type="primary",
                        use_container_width=True,
                        key=f"case_transfer_{task_id}",
                        disabled=bool(current_missing),
                        help="Complete every checklist item for the current station to enable transfer." if current_missing else "Transfer the case to the selected station.",
                    ):
                        if destination == current:
                            st.warning("Choose a different station.")
                        elif current_missing:
                            missing_html = "<br>• ".join(html.escape(x) for x in current_missing[:8])
                            st.error(f"Complete the current-station checklist before transfer:<br>• {missing_html}", unsafe_allow_html=True)
                        elif transfer_case(task, destination):
                            st.success(f"Case transferred to {station_name(destination)}.")
                            st.session_state["show_case"] = False
                            st.session_state["selected_case_id"] = None
                            st.rerun()
                        else:
                            st.error("Unable to transfer case.")

                    st.markdown(
                        "<div class='case-actions-note'>Reassignment and station transfer are locked until every required item for the current station is checked.</div>",
                        unsafe_allow_html=True,
                    )
                st.markdown("</div>", unsafe_allow_html=True)

            with checklist_col:
                st.markdown("<div class='case-card'>", unsafe_allow_html=True)
                st.markdown("<div class='case-card-heading'><span class='case-heading-icon'>☑</span>Station Task Checklists</div>", unsafe_allow_html=True)
                st.caption(f"Required tasks for the current station: {station_display_name(current)}. Completed items are logged automatically when the station checklist is finished.")

                selected_check_station = current
                selected_items = get_case_station_checklist(task, selected_check_station)
                selected_missing = [x.get("item") for x in selected_items if not bool(x.get("checked"))]
                complete_class = "complete" if not selected_missing else "pending"
                complete_text = "✓ Complete" if not selected_missing else f"{len(selected_missing)} item(s) remaining"
                st.markdown(
                    f"<div class='case-checklist-wrap'><div class='case-checklist-title'>{html.escape(station_display_name(selected_check_station))} Required Tasks</div>"
                    f"<div class='case-checklist-sub'>Every task below must be completed before this case can leave the current station.</div>"
                    f"<span class='case-checklist-status {complete_class}'>{html.escape(complete_text)}</span></div>",
                    unsafe_allow_html=True,
                )

                for idx, item in enumerate(selected_items):
                    check_key = f"case_checklist_{task_id}_{selected_check_station}_{idx}"
                    if check_key not in st.session_state:
                        st.session_state[check_key] = bool(item.get("checked"))

                    item_col, remove_col = st.columns([1, 0.08], gap="small")
                    with item_col:
                        st.checkbox(
                            item.get("item") or f"Checklist item {idx + 1}",
                            key=check_key,
                            on_change=set_case_checklist_item,
                            args=(task_id, selected_check_station, idx, check_key),
                        )
                    with remove_col:
                        if st.button(
                            "×",
                            key=f"case_checklist_remove_{task_id}_{selected_check_station}_{idx}",
                            help="Remove this checklist item",
                        ):
                            if remove_case_checklist_item(task_id, selected_check_station, idx):
                                st.session_state.pop(check_key, None)
                                st.rerun()
                            else:
                                st.error("Unable to remove this checklist item.")

                st.markdown("</div>", unsafe_allow_html=True)

            # -----------------------------------------------------------
            # LOGGED ACTION PLAN / NOTE — feeds the Resolution section
            # -----------------------------------------------------------
            action_log = task.get("case_action_log") or []
            latest_action_log = action_log[-1] if isinstance(action_log, list) and action_log and isinstance(action_log[-1], dict) else {}
            action_plan_default = text(latest_action_log.get("action_plan")) or text(task.get("next_action"))
            note_default = text(latest_action_log.get("note")) or text(task.get("notes"))
            st.markdown("<div class='case-card case-action-log-card'>", unsafe_allow_html=True)
            st.markdown("<div class='case-card-heading'><span class='case-heading-icon'>✎</span>Log Action Plan & Note</div>", unsafe_allow_html=True)
            st.caption("Log the action plan and case note here. The latest saved entry is automatically shown in Resolution & Next Action.")
            log_col1, log_col2 = st.columns([1.35, 1], gap="small")
            with log_col1:
                action_plan_value = st.text_area(
                    "Action Plan",
                    value=action_plan_default,
                    placeholder="Describe the next action, owner, escalation or commitment...",
                    height=72,
                    key=f"case_action_plan_{task_id}",
                )
            with log_col2:
                note_value = st.text_area(
                    "Case Note",
                    value=note_default,
                    placeholder="Record the important case note, finding or customer update...",
                    height=72,
                    key=f"case_action_note_{task_id}",
                )
            if st.button("＋ Save Action Plan & Note", type="primary", use_container_width=True, key=f"save_case_action_log_{task_id}"):
                ok, message = save_case_action_log(task_id, action_plan_value, note_value, assigned_to)
                if ok:
                    st.success("Action plan and note logged.")
                    st.rerun()
                else:
                    st.error(message or "Unable to save the action log.")
            if isinstance(action_log, list) and action_log:
                st.markdown("<div class='action-log-history-title'>Recent logged actions</div>", unsafe_allow_html=True)
                for entry in reversed(action_log[-3:]):
                    if not isinstance(entry, dict):
                        continue
                    stamp = dt_display(entry.get("timestamp")) or "—"
                    actor = text(entry.get("logged_by")) or "Caseflow User"
                    plan = text(entry.get("action_plan")) or "No action plan"
                    note = text(entry.get("note")) or "No note"
                    st.markdown(
                        f"<div class='action-log-entry'><div class='action-log-meta'>{html.escape(stamp)} · {html.escape(actor)}</div><div><b>Action Plan:</b> {html.escape(plan)}</div><div><b>Note:</b> {html.escape(note)}</div></div>",
                        unsafe_allow_html=True,
                    )
            st.markdown("</div>", unsafe_allow_html=True)

        # ---------------------------------------------------------------
        # KNOWLEDGE BASE TAB — CASE-MATCHED READER
        # ---------------------------------------------------------------
        with tab_kb:
            auto_query = case_kb_query(task)
            query_key = f"kb_reference_query_{task_id}"
            selected_kb_key = f"selected_kb_doc_{task_id}"

            st.markdown(
                "<div class='kb-panel-intro'><div class='kb-panel-title'>Knowledge Base</div>"
                "<div class='kb-panel-sub'>Case-matched HPE and Aruba guidance. Results are ranked from the current case issue, product, station and category.</div></div>",
                unsafe_allow_html=True,
            )

            query = st.text_input(
                "Knowledge Base Search",
                value=auto_query,
                placeholder="Search the current case issue, product or SOP...",
                key=query_key,
                label_visibility="collapsed",
            )
            search_col, clear_col = st.columns([8, 1], gap="small")
            with search_col:
                search_clicked = st.button(
                    "Search Knowledge Base  →",
                    type="primary",
                    use_container_width=True,
                    key=f"kb_reference_search_{task_id}",
                )
            with clear_col:
                clear_clicked = st.button(
                    "×",
                    use_container_width=True,
                    key=f"kb_reference_clear_{task_id}",
                    help="Clear the Knowledge Base search",
                )

            if clear_clicked:
                st.session_state.pop(query_key, None)
                active_query = auto_query
            else:
                active_query = text(query).strip() or auto_query

            # The suggested-question strip was intentionally removed to keep
            # the Case Details Knowledge Base focused on the matched SOP list
            # and the Exact Answer.
            if search_clicked:
                active_query = text(query).strip() or auto_query
            else:
                active_query = text(query).strip() or auto_query

            results = search_kb(active_query, limit=8)

            if not results:
                st.info("No matching Knowledge Base/SOP article was found for this case. Try the product, model, acronym or exact issue.")
            else:
                # Submit or a suggested question always selects the highest match.
                available_ids = {text(x.get("_id")) or text(x.get("title")) for x in results}
                stored_selected = st.session_state.get(selected_kb_key)
                if stored_selected not in available_ids or search_clicked:
                    stored_selected = text(results[0].get("_id")) or text(results[0].get("title"))
                    st.session_state[selected_kb_key] = stored_selected

                selected_doc = next(
                    (doc for doc in results if (text(doc.get("_id")) or text(doc.get("title"))) == stored_selected),
                    results[0],
                )

                # Keep the matching-SOP list inside the same dialog. Clicking a
                # result changes the selected document without closing the modal.
                st.markdown("<div class='kb-sop-list-title'>Matching SOPs for this case</div>", unsafe_allow_html=True)
                for idx, result in enumerate(results[:6]):
                    rid = text(result.get("_id")) or text(result.get("title")) or str(idx)
                    title = text(result.get("title")) or "Knowledge Base Article"
                    category = text(result.get("category")) or "Knowledge Base"
                    selected = rid == st.session_state[selected_kb_key]
                    if st.button(
                        f"{'★ BEST · ' if idx == 0 else f'{idx + 1}. '}{title} · {category}",
                        use_container_width=True,
                        key=f"kb_sop_list_{task_id}_{idx}_{sha256(rid)[:10]}",
                        type="primary" if selected else "secondary",
                    ):
                        st.session_state[selected_kb_key] = rid
                        selected_doc = result

                # Resolve the final selection after button interaction so the
                # clicked SOP is rendered immediately and only once.
                selected_id = st.session_state.get(selected_kb_key)
                selected_doc = next(
                    (doc for doc in results if (text(doc.get("_id")) or text(doc.get("title"))) == selected_id),
                    results[0],
                )

                st.markdown(
                    f"<div class='kb-selected-sop'>"
                    f"<div class='kb-selected-label'>{'BEST MATCH FOR THIS CASE' if selected_doc is results[0] else 'SELECTED SOP'}</div>"
                    f"<div class='kb-selected-sop-title'>{html.escape(text(selected_doc.get('title')) or 'Knowledge Base Article')}</div>"
                    f"<div class='kb-selected-sop-meta'>{html.escape(text(selected_doc.get('category')) or 'HPE Knowledge Base')} · {html.escape(text(selected_doc.get('source')) or text(selected_doc.get('source_type')) or 'Caseflow')}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                st.markdown(
                    f"<div class='kb-full-sop'><div class='kb-full-sop-label'>EXACT ANSWER</div>"
                    f"<div class='kb-rich-content'>{kb_rich_html(kb_content(selected_doc))}</div></div>",
                    unsafe_allow_html=True,
                )

        # ---------------------------------------------------------------
        # COMMUNICATION TAB
        # ---------------------------------------------------------------
        with tab_comm:
            st.markdown("<div class='case-card communication-workspace-card'>", unsafe_allow_html=True)
            st.markdown("<div class='case-card-heading'><span class='case-heading-icon'>✦</span>Collaboration</div>", unsafe_allow_html=True)

            # -----------------------------------------------------------
            # WAR ROOM / MEETING RECORD
            # -----------------------------------------------------------
            st.markdown(
                "<div class='meeting-panel'>"
                "<div class='meeting-panel-title'>War Room / Meeting</div>"
                "<div class='meeting-panel-sub'>Create a meeting record, add the war-room link, tag participants, record attendance and capture agreed actions.</div>"
                "</div>",
                unsafe_allow_html=True,
            )
            latest_events = _case_update_events(task)
            latest_event = max(latest_events, key=lambda x: x[0]) if latest_events else None
            latest_text = text(latest_event[1]) if latest_event else "No live update has been recorded yet."
            latest_actor = text(latest_event[2]) if latest_event and latest_event[2] else "Caseflow"
            participants_preview = list(dict.fromkeys(CASEFLOW_ASSIGNEES + ([assigned_to] if assigned_to else [])))
            participant_preview = participants_preview[:5] or [assigned_to]
            participant_html = "".join(f"<span class='war-room-avatar'>{html.escape((text(name) or '?')[:1].upper())}</span>" for name in participant_preview if text(name))
            war_open_key = f"war_room_open_{task_id}"
            war_room_open = bool(st.session_state.get(war_open_key, False))
            mock_link = f"https://meet.example.com/hpe-caseflow-{html.escape(case_number, quote=True)}"
            with st.container(key=f"war_room_tile_{task_id}"):
                st.markdown(
                    f"<div class='war-room-mock {'war-room-open' if war_room_open else ''}' role='button' aria-label='Open war room'>"
                    f"<div class='war-room-top'><div><span class='war-room-live-dot'></span><b>LIVE WAR ROOM</b><span class='war-room-case'>{html.escape(case_number)}</span></div><span class='war-room-status'>{'OPEN' if war_room_open else 'ACTIVE'}</span></div>"
                    f"<div class='war-room-grid'>"
                    f"<div><div class='war-room-label'>CURRENT FOCUS</div><div class='war-room-focus'>{html.escape(subject)}</div><div class='war-room-muted'>{html.escape(station_display_name(department))} · {html.escape(priority_label.title())}</div></div>"
                    f"<div><div class='war-room-label'>PARTICIPANTS</div><div class='war-room-avatars'>{participant_html}</div><div class='war-room-muted'>{len(participant_preview)} people in collaboration</div></div>"
                    f"<div><div class='war-room-label'>MOST RECENT UPDATE</div><div class='war-room-update'>{html.escape(latest_text[:190])}</div><div class='war-room-muted'>by {html.escape(latest_actor)}</div></div>"
                    f"</div></div>",
                    unsafe_allow_html=True,
                )
                if st.button(
                    "Open War Room",
                    use_container_width=True,
                    key=f"war_room_open_button_{task_id}",
                ):
                    st.session_state[war_open_key] = True
                    war_room_open = True

            if war_room_open:
                meetings = task.get("meetings") or []
                latest_meeting = meetings[-1] if isinstance(meetings, list) and meetings and isinstance(meetings[-1], dict) else {}
                current_attendees = latest_meeting.get("attendance") or participant_preview
                attendee_html = "".join(f"<li>{html.escape(text(name))}</li>" for name in current_attendees if text(name)) or "<li>No attendees recorded yet.</li>"
                st.markdown(
                    f"<div class='war-room-expanded'><div class='war-room-expanded-head'><div><b>War Room Details</b><span> · {html.escape(case_number)}</span></div><span class='war-room-expanded-live'>LIVE</span></div>"
                    f"<div class='war-room-expanded-grid'><div><div class='war-room-label'>CURRENT ATTENDEES</div><ul>{attendee_html}</ul></div>"
                    f"<div><div class='war-room-label'>MOCK WAR ROOM LINK</div><a class='war-room-link' href='{mock_link}' target='_blank' rel='noopener noreferrer'>Open mock war room ↗</a><div class='war-room-muted'>Opens without closing Case Details.</div></div></div></div>",
                    unsafe_allow_html=True,
                )
                if st.button("Close War Room", use_container_width=True, key=f"war_room_close_{task_id}"):
                    try:
                        from bson import ObjectId
                        now = utc_now()
                        history = list(task.get("history") or [])
                        attendee_names = ", ".join(text(x) for x in current_attendees if text(x)) or "None recorded"
                        history.append({
                            "action": f"War Room closed.\n• Attendees: {attendee_names}\n• Link: {mock_link}",
                            "timestamp": now,
                            "actor": assigned_to or "Caseflow",
                        })
                        col(TASKS_COLLECTION).update_one(
                            {"_id": ObjectId(str(task_id))},
                            {"$set": {"history": history, "last_update": now}},
                        )
                        clear_task_cache()
                    except Exception:
                        pass
                    st.session_state[war_open_key] = False
                    st.rerun()

            meeting_link_key = f"meeting_link_{task_id}"
            meeting_tags_key = f"meeting_tags_{task_id}"
            meeting_attendance_key = f"meeting_attendance_{task_id}"
            meeting_actions_key = f"meeting_actions_{task_id}"

            participant_options = list(dict.fromkeys(
                CASEFLOW_ASSIGNEES
                + ([assigned_to] if assigned_to and assigned_to not in CASEFLOW_ASSIGNEES else [])
            ))

            meeting_link = st.text_input(
                "War Room / Meeting Link",
                value="",
                placeholder="Paste Teams, Meet, Zoom or other meeting link...",
                key=meeting_link_key,
            )
            meeting_tagged = st.multiselect(
                "Tag people",
                participant_options,
                default=[],
                placeholder="Select people to tag in this meeting...",
                key=meeting_tags_key,
            )
            meeting_attendance = st.multiselect(
                "Attendance",
                participant_options,
                default=[],
                placeholder="Select attendees who joined...",
                key=meeting_attendance_key,
            )
            meeting_actions = st.text_area(
                "Meeting actions / decisions",
                placeholder="Record decisions, owners, next steps or commitments...",
                height=90,
                key=meeting_actions_key,
            )

            if st.button(
                "＋ Record Meeting",
                type="primary",
                use_container_width=True,
                key=f"record_meeting_{task_id}",
            ):
                if not text(meeting_link) and not meeting_tagged and not meeting_attendance and not text(meeting_actions):
                    st.warning("Add at least a meeting link, tagged participant, attendee, or meeting action.")
                else:
                    try:
                        from bson import ObjectId
                        now = utc_now()
                        meeting_record = {
                            "timestamp": now,
                            "meeting_link": text(meeting_link),
                            "tagged_people": list(meeting_tagged),
                            "attendance": list(meeting_attendance),
                            "actions": text(meeting_actions),
                            "recorded_by": assigned_to,
                        }
                        history = list(task.get("history") or [])
                        meeting_history = (
                            f"{station_display_name(department)} meeting recorded."
                            + (f"\n• War Room: {text(meeting_link)}" if text(meeting_link) else "")
                            + (f"\n• Tagged: {', '.join(text(x) for x in meeting_tagged)}" if meeting_tagged else "")
                            + (f"\n• Attendees: {', '.join(text(x) for x in meeting_attendance)}" if meeting_attendance else "")
                            + (f"\n• Actions / Decisions: {text(meeting_actions)}" if text(meeting_actions) else "")
                        )
                        history.append({
                            "action": meeting_history,
                            "timestamp": now,
                            "actor": assigned_to or "Caseflow",
                            "station": department,
                        })
                        col(TASKS_COLLECTION).update_one(
                            {"_id": ObjectId(str(task_id))},
                            {
                                "$push": {
                                    "meetings": {
                                        "$each": [meeting_record],
                                        "$slice": -50,
                                    }
                                },
                                "$set": {
                                    "last_update": now,
                                    "history": history,
                                },
                            },
                        )
                        clear_task_cache()
                        st.success("Meeting record saved.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Unable to save the meeting record: {exc}")

            meetings = task.get("meetings") or []
            if isinstance(meetings, list) and meetings:
                st.markdown("<div class='communication-section-label'>Recorded Meetings</div>", unsafe_allow_html=True)
                for meeting in reversed(meetings[-10:]):
                    if not isinstance(meeting, dict):
                        continue
                    meeting_stamp = dt_display(meeting.get("timestamp")) or "—"
                    tagged = meeting.get("tagged_people") or []
                    attendance = meeting.get("attendance") or []
                    actions = text(meeting.get("actions")) or "No actions recorded."
                    link = text(meeting.get("meeting_link"))
                    tagged_html = ", ".join(html.escape(text(x)) for x in tagged) or "None"
                    attendance_html = ", ".join(html.escape(text(x)) for x in attendance) or "No attendance recorded."
                    link_html = (
                        f"<a href='{html.escape(link, quote=True)}' target='_blank' rel='noopener noreferrer'>Open war room</a>"
                        if link else "No meeting link"
                    )
                    st.markdown(
                        f"<div class='meeting-record'>"
                        f"<div class='communication-head'><strong>Meeting</strong><span>{html.escape(meeting_stamp)}</span></div>"
                        f"<div class='meeting-record-row'><b>War Room:</b> {link_html}</div>"
                        f"<div class='meeting-record-row'><b>Tagged:</b> {tagged_html}</div>"
                        f"<div class='meeting-record-row'><b>Attendance:</b> {attendance_html}</div>"
                        f"<div class='meeting-record-row'><b>Actions / Decisions:</b> {html.escape(actions).replace(chr(10), '<br>')}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

            st.markdown("<div class='communication-section-label'>Communication History</div>", unsafe_allow_html=True)
            communications = task.get("communications") or task.get("communication_history") or []
            if isinstance(communications, list) and communications:
                for item in reversed(communications[-20:]):
                    if isinstance(item, dict):
                        sender = text(item.get("sender") or item.get("user") or item.get("from")) or "Caseflow User"
                        body = text(item.get("message") or item.get("body") or item.get("details")) or "—"
                        stamp = dt_display(item.get("timestamp") or item.get("created_at"))
                    else:
                        sender, body, stamp = "Caseflow User", text(item), ""
                    st.markdown(
                        f"<div class='communication-card'><div class='communication-head'><strong>{html.escape(sender)}</strong><span>{html.escape(stamp)}</span></div><div>{html.escape(body)}</div></div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No communication history is stored on this case.")
            st.markdown("</div>", unsafe_allow_html=True)

        # ---------------------------------------------------------------
        # ATTACHMENTS TAB
        # ---------------------------------------------------------------
        with tab_attach:
            st.markdown("<div class='case-card'>", unsafe_allow_html=True)
            st.markdown("<div class='case-card-heading'><span class='case-heading-icon'>♧</span>Attachments</div>", unsafe_allow_html=True)
            attachments = task.get("attachments") or task.get("files") or []
            if isinstance(attachments, list) and attachments:
                for item in attachments:
                    if isinstance(item, dict):
                        name = text(item.get("name") or item.get("filename") or item.get("file_name")) or "Attachment"
                        detail = text(item.get("description") or item.get("type") or item.get("size"))
                    else:
                        name, detail = text(item), ""
                    st.markdown(
                        f"<div class='attachment-row'><span>▧ <strong>{html.escape(name)}</strong></span><span>{html.escape(detail)}</span></div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No attachments are recorded for this case.")
            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='case-detail-footer'></div>", unsafe_allow_html=True)


    # ============================================================
    # DASHBOARD
    # ============================================================
    # REAL-TIME DASHBOARD
    # The dashboard fragment refreshes once per second so MongoDB changes are
    # reflected on the visible tiles/table without refreshing the entire app.


# ============================================================
# FINAL CASE DETAILS MODAL SHELL — NATIVE SCROLL CONTAINER
# ============================================================
st.markdown(r"""
<style>
/* Compact modal shell sized to the actual Caseflow desktop workspace. */
div[data-testid="stDialog"] > div {
    position: fixed !important;
    top: 50% !important;
    left: 50% !important;
    right: auto !important;
    bottom: auto !important;
    transform: translate(-50%, -50%) !important;
    width: min(1080px, calc(100vw - 48px)) !important;
    max-width: min(1080px, calc(100vw - 48px)) !important;
    height: min(660px, calc(100vh - 32px)) !important;
    max-height: calc(100vh - 32px) !important;
    min-height: 0 !important;
    overflow: hidden !important;
}

/* Never hide the native scrollbar of the Streamlit container. */
div[data-testid="stDialog"] [data-testid="stVerticalBlock"] {
    scrollbar-width: thin !important;
}

/* Remove the old zoom/oversizing behavior from the case-detail workspace. */
div[data-testid="stDialog"] .case-detail-hero,
div[data-testid="stDialog"] .case-summary-strip {
    zoom: 1 !important;
}

/* Compact typography without shrinking the browser layout. */
div[data-testid="stDialog"] .case-summary-cell span { font-size: 8px !important; }
div[data-testid="stDialog"] .case-summary-cell strong { font-size: 9px !important; }
div[data-testid="stDialog"] .case-assignee-copy span { font-size: 8px !important; }
div[data-testid="stDialog"] .case-assignee-copy strong { font-size: 9px !important; }

/* Sleek, thin, semi-transparent scrollbar for the ACTUAL native Streamlit scroll container. */
div[data-testid="stDialog"] [data-testid="stVerticalBlock"] {
    scrollbar-width: thin !important;
    scrollbar-color: rgba(71, 85, 105, .42) transparent !important;
}
div[data-testid="stDialog"] [data-testid="stVerticalBlock"]::-webkit-scrollbar {
    width: 5px !important;
    height: 5px !important;
}
div[data-testid="stDialog"] [data-testid="stVerticalBlock"]::-webkit-scrollbar-track {
    background: transparent !important;
    border: 0 !important;
}
div[data-testid="stDialog"] [data-testid="stVerticalBlock"]::-webkit-scrollbar-thumb {
    background: rgba(71, 85, 105, .42) !important;
    border-radius: 999px !important;
    border: 0 !important;
}
div[data-testid="stDialog"] [data-testid="stVerticalBlock"]::-webkit-scrollbar-thumb:hover {
    background: rgba(30, 41, 59, .62) !important;
}

@media (max-width: 900px) {
    div[data-testid="stDialog"] > div {
        width: calc(100vw - 12px) !important;
        max-width: calc(100vw - 12px) !important;
        height: calc(100vh - 12px) !important;
        max-height: calc(100vh - 12px) !important;
    }
}

/* ============================================================
   CASE DETAILS VISUAL REFINEMENT — INTER / UNIFORM BODY TYPE
   ============================================================ */
div[data-testid="stDialog"],
div[data-testid="stDialog"] * {
    font-family:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif !important;
}

/* Keep ordinary Case Details text on one consistent readable scale.
   Headings, selected SOP title and status chips retain deliberate hierarchy. */
div[data-testid="stDialog"] .case-card,
div[data-testid="stDialog"] .case-card p,
div[data-testid="stDialog"] .case-card label,
div[data-testid="stDialog"] .case-card input,
div[data-testid="stDialog"] .case-card textarea,
div[data-testid="stDialog"] .case-card button,
div[data-testid="stDialog"] .case-card [data-baseweb="select"] {
    font-size:11px !important;
}

div[data-testid="stDialog"] .case-card-heading {
    font-size:12px !important;
    font-weight:800 !important;
}

div[data-testid="stDialog"] .action-readonly-label,
div[data-testid="stDialog"] .case-checklist-sub,
div[data-testid="stDialog"] .case-actions-note,
div[data-testid="stDialog"] .communication-section-label {
    font-size:10px !important;
}

div[data-testid="stDialog"] .action-readonly-value,
div[data-testid="stDialog"] .case-checklist-title,
div[data-testid="stDialog"] [data-testid="stCheckbox"] label,
div[data-testid="stDialog"] .communication-card,
div[data-testid="stDialog"] .meeting-record {
    font-size:11px !important;
    line-height:1.35 !important;
}

/* Station buttons: compact checklist station switcher. */
div[data-testid="stDialog"] [class*="st-key-select_action_station_"] button {
    font-size:9.5px !important;
    font-weight:700 !important;
    min-height:28px !important;
    height:28px !important;
    padding:3px 7px !important;
    border-radius:6px !important;
    line-height:1 !important;
    white-space:nowrap !important;
}

/* Tight checklist rows so the required-task list stays compact. */
div[data-testid="stDialog"] .case-card [data-testid="stCheckbox"] {
    margin-top:-5px !important;
    margin-bottom:-8px !important;
}
div[data-testid="stDialog"] .case-card [data-testid="stCheckbox"] label {
    font-size:10px !important;
    line-height:1.2 !important;
}
div[data-testid="stDialog"] .case-card [class*="st-key-case_checklist_remove_"] {
    margin-top:-6px !important;
    margin-bottom:-8px !important;
}

/* Checklist delete control. */
div[data-testid="stDialog"] [class*="st-key-case_checklist_remove_"] button {
    width:28px !important;
    min-width:28px !important;
    height:28px !important;
    min-height:28px !important;
    padding:0 !important;
    border:0 !important;
    background:transparent !important;
    color:#94a3b8 !important;
    font-size:18px !important;
    font-weight:400 !important;
}
div[data-testid="stDialog"] [class*="st-key-case_checklist_remove_"] button:hover {
    color:#dc3545 !important;
    background:#fff1f2 !important;
}

/* Transfer stays visibly disabled until the CURRENT station is complete. */
div[data-testid="stDialog"] [class*="st-key-case_transfer_"] button:disabled {
    opacity:.42 !important;
    cursor:not-allowed !important;
}

/* ============================================================
   KNOWLEDGE BASE — CLEAN TWO-PANE READER
   ============================================================ */
div[data-testid="stDialog"] .kb-inline-card {
    overflow:hidden !important;
}

div[data-testid="stDialog"] .kb-inline-card [class*="st-key-kb_tile_"] button {
    font-size:10px !important;
    line-height:1.25 !important;
    min-height:34px !important;
    padding:7px 9px !important;
    border-radius:7px !important;
    text-align:left !important;
    white-space:normal !important;
    overflow:hidden !important;
}

div[data-testid="stDialog"] .kb-selected-sop {
    padding:12px 14px !important;
    border-left:4px solid #0879c9 !important;
    background:#f7fbff !important;
}

div[data-testid="stDialog"] .kb-selected-sop-title {
    color:#102041 !important;
    font-size:15px !important;
    line-height:1.3 !important;
    font-weight:800 !important;
    margin-top:4px !important;
}

div[data-testid="stDialog"] .kb-selected-sop-meta {
    color:#5f7189 !important;
    font-size:10px !important;
    line-height:1.3 !important;
    margin-top:5px !important;
}

div[data-testid="stDialog"] .kb-full-sop {
    padding:13px 15px !important;
    background:#fff !important;
    border:1px solid #dbe5ef !important;
    border-radius:8px !important;
}

div[data-testid="stDialog"] .kb-full-sop-label {
    font-size:9px !important;
    font-weight:800 !important;
    letter-spacing:.35px !important;
    color:#0879c9 !important;
    margin-bottom:7px !important;
}

div[data-testid="stDialog"] .kb-full-sop-text {
    font-size:12px !important;
    line-height:1.55 !important;
    color:#263957 !important;
}

div[data-testid="stDialog"] .kb-recommendation .kb-full-sop-text {
    font-size:11.5px !important;
    line-height:1.5 !important;
}

/* ============================================================
   COMMUNICATION / WAR ROOM
   ============================================================ */
div[data-testid="stDialog"] .meeting-panel {
    background:#f5fbfa !important;
    border:1px solid #cde8e3 !important;
    border-left:4px solid #00a98f !important;
    border-radius:8px !important;
    padding:10px 12px !important;
    margin-bottom:10px !important;
}

div[data-testid="stDialog"] .meeting-panel-title {
    color:#0b625b !important;
    font-size:12px !important;
    font-weight:800 !important;
}

div[data-testid="stDialog"] .meeting-panel-sub {
    color:#5d7180 !important;
    font-size:10px !important;
    line-height:1.4 !important;
    margin-top:3px !important;
}

div[data-testid="stDialog"] .communication-section-label {
    color:#102041 !important;
    font-weight:800 !important;
    margin:12px 0 6px !important;
}

div[data-testid="stDialog"] .meeting-record {
    border:1px solid #dbe5ed !important;
    border-radius:8px !important;
    background:#fbfdff !important;
    padding:10px 12px !important;
    margin-bottom:8px !important;
    color:#334155 !important;
}

div[data-testid="stDialog"] .meeting-record-row {
    margin-top:5px !important;
}

div[data-testid="stDialog"] .meeting-record-row b {
    color:#172b52 !important;
}

div[data-testid="stDialog"] .meeting-record a {
    color:#0879c9 !important;
    font-weight:700 !important;
    text-decoration:none !important;
}

div[data-testid="stDialog"] .meeting-record a:hover {
    text-decoration:underline !important;
}

/* Keep the single actual Case Details scroll surface sleek and transparent. */
div[data-testid="stDialog"] [data-testid="stVerticalBlock"] {
    scrollbar-width:thin !important;
    scrollbar-color:rgba(71,85,105,.42) transparent !important;
}
div[data-testid="stDialog"] [data-testid="stVerticalBlock"]::-webkit-scrollbar {
    width:5px !important;
}
div[data-testid="stDialog"] [data-testid="stVerticalBlock"]::-webkit-scrollbar-track {
    background:transparent !important;
}
div[data-testid="stDialog"] [data-testid="stVerticalBlock"]::-webkit-scrollbar-thumb {
    background:rgba(71,85,105,.42) !important;
    border-radius:999px !important;
}
div[data-testid="stDialog"] [data-testid="stVerticalBlock"]::-webkit-scrollbar-thumb:hover {
    background:rgba(30,41,59,.62) !important;
}

</style>
""", unsafe_allow_html=True)

    # Duration and Total Elapsed are browser-clock driven; dashboard refresh cadence is independent.


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
        warning_latched = st.session_state.setdefault(
            "station_warning_latched",
            set(),
        )


        warning_condition = (nearing > 0 or past_due > 0)
        warning_pairs = [
            (task, state)
            for task, state in zip(station_tasks, station_states)
            if state.get("nearing_due", False) or state.get("past_due", False)
        ]
        unacknowledged_warning_tasks = [
            task for task, _state in warning_pairs
            if text(task.get("station_warning_ack_trigger")) != station_warning_trigger_key(task, station)
        ]
        if unacknowledged_warning_tasks:
            warning_latched.add(station)
        elif not warning_condition:
            warning_latched.discard(station)
            warning_silenced.discard(station)

        ack_until = 0.0
        now_epoch = time.time()

        # Persisted per-case warning-cycle acknowledgement means a refresh
        # cannot resurrect an alert that the user already clicked. A new case
        # entering warning, or the same case entering a new station cycle, gets
        # a new trigger key and can alert again.
        flash_tile = bool(unacknowledged_warning_tasks)


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
                    f'<div class="station-warning{" active" if warning_condition else ""}">◷ &nbsp; {nearing} nearing due{("  •  " + str(past_due) + " past due") if past_due else ""}</div>'
                    f'<div class="station-sla-ref">◷ &nbsp; Max Timeframe: <strong>{html.escape(sla_text)}</strong></div>'
                    f'</div>'
                )
                st.markdown(station_html, unsafe_allow_html=True)
                if st.button(
                    f"Select {station}",
                    key=f"station_{station}",
                    use_container_width=True,
                ):
                    if warning_condition:
                        # Acknowledge exactly the currently-warning case cycles
                        # in MongoDB so the clicked state survives refresh.
                        warning_ack_until[station] = 0.0
                        warning_silenced.add(station)
                        warning_latched.discard(station)
                        acknowledge_station_warning_cycle(unacknowledged_warning_tasks)
                        acknowledge_station_alerts(
                            station,
                            trigger_keys={
                                station_warning_trigger_key(task, station)
                                for task in unacknowledged_warning_tasks
                            },
                        )


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
                    # Persist the selected case so controls inside the dialog
                    # can rerun the app without losing the Case Details modal.
                    st.session_state["selected_case_id"] = str(task_id)
                    st.session_state["show_case"] = True
                    # Open the dialog directly from this sequential fragment
                    # widget interaction. Streamlit supports opening a dialog
                    # from a fragment rerun; forcing an app rerun here caused
                    # the layout-context error in this application.
                    case_details(str(task_id))


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


                // Flashing is latched server-side and may only be stopped by
                // clicking the station tile. Do not time it out in the browser.
            }
            function updateTotalElapsed() {
                const nodes = document.querySelectorAll('[data-total-elapsed-live="1"]');
                const nowMs = Date.now();

                nodes.forEach(function (node) {
                    const raw = node.getAttribute("data-total-elapsed-start");
                    if (!raw) return;

                    const startedMs = Date.parse(raw);
                    if (!Number.isFinite(startedMs)) return;

                    const elapsed = Math.max(0, Math.floor((nowMs - startedMs) / 1000));
                    const h = Math.floor(elapsed / 3600);
                    const m = Math.floor((elapsed % 3600) / 60);
                    const sec = elapsed % 60;

                    node.textContent =
                        String(h).padStart(2, "0") + ":" +
                        String(m).padStart(2, "0") + ":" +
                        String(sec).padStart(2, "0");
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
            updateTotalElapsed();
            updateWarningAnimations();


            /*
             * Keep Duration and Total Elapsed completely browser-side.
             * Do not depend on the Streamlit fragment cadence.  The dashboard
             * may refresh independently for alerts/data, but these clocks are
             * driven from the browser clock and repaint on the exact second.
             */
            if (!window.__taskTrackerDurationLoop) {
                window.__taskTrackerDurationLoop = true;
                let lastSecond = -1;

                function durationClockLoop() {
                    const now = Date.now();
                    const second = Math.floor(now / 1000);
                    if (second !== lastSecond) {
                        lastSecond = second;
                        updateDurations();
                        updateTotalElapsed();
                        updateWarningAnimations();
                    }
                    /* Wake close to the next wall-clock second instead of
                       running requestAnimationFrame ~60 times per second.
                       This preserves 1-second timer accuracy while materially
                       reducing browser CPU work and visual contention. */
                    const delay = Math.max(50, 1000 - (now % 1000) + 10);
                    window.setTimeout(durationClockLoop, delay);
                }

                /*
                 * Streamlit may replace the fragment DOM on its normal
                 * 1-second data refresh. Repaint any newly inserted
                 * Duration / Total Elapsed nodes immediately from the browser
                 * clock so those data refreshes never become the visible timer.
                 */
                if (!window.__taskTrackerDurationObserver) {
                    window.__taskTrackerDurationObserver = new MutationObserver(function () {
                        updateDurations();
                        updateTotalElapsed();
                    });
                    window.__taskTrackerDurationObserver.observe(document.body, {
                        childList: true,
                        subtree: true
                    });
                }

                durationClockLoop();
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




# Render the live dashboard. Case Details is opened directly by the
# case button during the fragment's sequential widget interaction.
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



st.markdown(r'''
<style>
/* ============================================================
   CASEFLOW FINAL UI PATCH — 2026-10-06
   ============================================================ */
/* Use one real scroll surface for Case Details. Do not apply scrollbar
   styling to every nested Streamlit vertical block. */
div[data-testid="stDialog"] [class*="st-key-case_detail_scroll_"] {
    height:auto !important;
    max-height:none !important;
    min-height:0 !important;
    overflow:visible !important;
    overflow-x:visible !important;
    overscroll-behavior:auto !important;
    padding-bottom:18px !important;
    box-sizing:border-box !important;
}
div[data-testid="stDialog"] [class*="st-key-case_detail_scroll_"]::-webkit-scrollbar { width:5px !important; height:5px !important; }
div[data-testid="stDialog"] [class*="st-key-case_detail_scroll_"]::-webkit-scrollbar-track { background:transparent !important; }
div[data-testid="stDialog"] [class*="st-key-case_detail_scroll_"]::-webkit-scrollbar-thumb { background:rgba(71,85,105,.42) !important; border-radius:999px !important; }
div[data-testid="stDialog"] [class*="st-key-case_detail_scroll_"]::-webkit-scrollbar-thumb:hover { background:rgba(30,41,59,.62) !important; }

/* Uniform Case Details body typography. Only the dialog header, hero case
   number/subject and card headings receive a larger type scale. */
div[data-testid="stDialog"] .case-detail-description,
div[data-testid="stDialog"] .case-timing-item,
div[data-testid="stDialog"] .case-summary-cell,
div[data-testid="stDialog"] .case-info-row,
div[data-testid="stDialog"] .action-readonly-value,
div[data-testid="stDialog"] .resolution-value,
div[data-testid="stDialog"] .resolution-log-meta,
div[data-testid="stDialog"] .case-checklist-sub,
div[data-testid="stDialog"] .case-actions-note,
div[data-testid="stDialog"] .case-action-log-card,
div[data-testid="stDialog"] .communication-card,
div[data-testid="stDialog"] .meeting-record,
div[data-testid="stDialog"] .attachment-row,
div[data-testid="stDialog"] .kb-reference-answer,
div[data-testid="stDialog"] .kb-step {
    font-size:11px !important;
    line-height:1.4 !important;
}
div[data-testid="stDialog"] .case-detail-case-number { font-size:16px !important; }
div[data-testid="stDialog"] .case-detail-subject { font-size:13px !important; }
div[data-testid="stDialog"] .case-info-row span,
div[data-testid="stDialog"] .action-readonly-label,
div[data-testid="stDialog"] .resolution-label { font-size:10px !important; }
div[data-testid="stDialog"] .case-info-row strong,
div[data-testid="stDialog"] .action-readonly-value,
div[data-testid="stDialog"] .resolution-value { font-size:11px !important; }

/* Compact select/dropdown controls so they do not consume large vertical space. */
div[data-testid="stDialog"] [data-testid="stSelectbox"] { margin:1px 0 2px !important; }
div[data-testid="stDialog"] [data-testid="stSelectbox"] label { font-size:9px !important; margin-bottom:1px !important; line-height:1.1 !important; }
div[data-testid="stDialog"] [data-testid="stSelectbox"] [data-baseweb="select"] > div { min-height:28px !important; height:28px !important; padding-top:0 !important; padding-bottom:0 !important; border-radius:5px !important; }
div[data-testid="stDialog"] [data-testid="stSelectbox"] [data-baseweb="select"] span { font-size:9.5px !important; line-height:26px !important; }
div[data-testid="stDialog"] [data-testid="stSelectbox"] svg { width:12px !important; height:12px !important; }

/* Logged action plan / note card. */
div[data-testid="stDialog"] .case-action-log-card { margin-top:9px !important; padding:9px 11px !important; }
div[data-testid="stDialog"] .action-log-history-title { font-size:10px !important; font-weight:800 !important; color:#102041 !important; margin:8px 0 5px !important; }
div[data-testid="stDialog"] .action-log-entry { border:1px solid #e1e8f0 !important; background:#fbfdff !important; border-radius:6px !important; padding:7px 8px !important; margin-bottom:5px !important; font-size:10px !important; line-height:1.35 !important; color:#334155 !important; }
div[data-testid="stDialog"] .action-log-meta { color:#64748b !important; font-size:9px !important; margin-bottom:3px !important; }
div[data-testid="stDialog"] .resolution-log-meta { color:#64748b !important; font-size:9px !important; margin-top:5px !important; }

/* ============================================================
   KNOWLEDGE BASE — CLEAN WHITE CASE-MATCHED READER
   ============================================================ */
div[data-testid="stDialog"] .kb-panel-intro {
    background:#fff !important;
    border:1px solid #e3eaf1 !important;
    border-radius:7px !important;
    padding:8px 10px !important;
    margin-bottom:7px !important;
}
div[data-testid="stDialog"] .kb-panel-title {
    color:#102041 !important;
    font-size:12px !important;
    font-weight:850 !important;
}
div[data-testid="stDialog"] .kb-panel-sub {
    color:#64748b !important;
    font-size:9.5px !important;
    line-height:1.35 !important;
    margin-top:2px !important;
}
div[data-testid="stDialog"] .kb-suggested-title {
    color:#008f80 !important;
    font-size:8px !important;
    font-weight:850 !important;
    letter-spacing:.45px !important;
    text-transform:uppercase !important;
    margin:6px 0 3px !important;
}
div[data-testid="stDialog"] [class*="st-key-kb_suggested_"] button {
    border:1px solid #dce8e7 !important;
    background:#fff !important;
    color:#176b67 !important;
    font-size:9px !important;
    line-height:1.2 !important;
    padding:5px 7px !important;
    min-height:27px !important;
    height:auto !important;
    white-space:normal !important;
    text-align:left !important;
    border-radius:6px !important;
}
div[data-testid="stDialog"] [class*="st-key-kb_suggested_"] button:hover {
    background:#f2fbf9 !important;
    border-color:#00a98f !important;
}
div[data-testid="stDialog"] .kb-selected-sop {
    padding:8px 10px !important;
    border-left:3px solid #00a98f !important;
    border-top:1px solid #e1e8ee !important;
    border-right:1px solid #e1e8ee !important;
    border-bottom:1px solid #e1e8ee !important;
    background:#fff !important;
    border-radius:6px !important;
    margin-top:7px !important;
}
div[data-testid="stDialog"] .kb-selected-label {
    color:#008f80 !important;
    font-size:8px !important;
    font-weight:900 !important;
    letter-spacing:.45px !important;
}
div[data-testid="stDialog"] .kb-selected-sop-title {
    color:#102041 !important;
    font-size:12px !important;
    line-height:1.25 !important;
    font-weight:800 !important;
    margin-top:2px !important;
}
div[data-testid="stDialog"] .kb-selected-sop-meta {
    color:#64748b !important;
    font-size:8.5px !important;
    line-height:1.3 !important;
    margin-top:3px !important;
}
div[data-testid="stDialog"] .kb-full-sop,
div[data-testid="stDialog"] .kb-recommendation {
    padding:9px 11px !important;
    background:#fff !important;
    border:1px solid #e0e7ee !important;
    border-radius:6px !important;
    margin-top:6px !important;
    color:#263957 !important;
}
div[data-testid="stDialog"] .kb-recommendation {
    background:#fbfefd !important;
    border-left:3px solid #00a98f !important;
}
div[data-testid="stDialog"] .kb-full-sop-label {
    font-size:8px !important;
    font-weight:850 !important;
    letter-spacing:.45px !important;
    color:#087b71 !important;
    margin-bottom:5px !important;
}
div[data-testid="stDialog"] .kb-rich-content {
    color:#263957 !important;
    font-size:10px !important;
    line-height:1.45 !important;
}
div[data-testid="stDialog"] .kb-rich-content p {
    margin:0 0 6px !important;
}
div[data-testid="stDialog"] .kb-rich-content p:last-child {
    margin-bottom:0 !important;
}
div[data-testid="stDialog"] .kb-rich-content ul,
div[data-testid="stDialog"] .kb-rich-content ol {
    margin:2px 0 7px 17px !important;
    padding:0 !important;
}
div[data-testid="stDialog"] .kb-rich-content li {
    margin:0 0 3px !important;
    padding-left:2px !important;
}
div[data-testid="stDialog"] .kb-content-heading {
    color:#008f80 !important;
    font-size:9px !important;
    font-weight:850 !important;
    letter-spacing:.25px !important;
    margin:7px 0 3px !important;
}
div[data-testid="stDialog"] .kb-content-heading:first-child {
    margin-top:0 !important;
}
div[data-testid="stDialog"] .kb-sop-list-title {
    color:#102041 !important;
    font-size:9px !important;
    font-weight:850 !important;
    margin:8px 0 4px !important;
}
div[data-testid="stDialog"] [class*="st-key-kb_sop_list_"] button {
    min-height:28px !important;
    height:28px !important;
    padding:4px 7px !important;
    border-radius:5px !important;
    font-size:9px !important;
    line-height:1.15 !important;
    text-align:left !important;
}

/* Collaboration / war room mockup. */
div[data-testid="stDialog"] .war-room-mock {
    background:#fff !important;
    border:1px solid #dbe5ed !important;
    border-radius:8px !important;
    padding:8px 10px !important;
    margin:0 0 9px !important;
}
div[data-testid="stDialog"] .war-room-top {
    display:flex !important;
    justify-content:space-between !important;
    align-items:center !important;
    gap:8px !important;
    color:#102041 !important;
    font-size:9px !important;
}
div[data-testid="stDialog"] .war-room-live-dot {
    display:inline-block !important;
    width:7px !important;
    height:7px !important;
    border-radius:50% !important;
    background:#00a98f !important;
    margin-right:5px !important;
}
div[data-testid="stDialog"] .war-room-case {
    color:#64748b !important;
    margin-left:7px !important;
    font-weight:600 !important;
}
div[data-testid="stDialog"] .war-room-status {
    color:#087b71 !important;
    background:#e7faf5 !important;
    border-radius:999px !important;
    padding:3px 6px !important;
    font-size:7.5px !important;
    font-weight:850 !important;
}
div[data-testid="stDialog"] .war-room-grid {
    display:grid !important;
    grid-template-columns:1.3fr .8fr 1.4fr !important;
    gap:8px !important;
    margin-top:7px !important;
}
div[data-testid="stDialog"] .war-room-label {
    color:#64748b !important;
    font-size:7px !important;
    font-weight:850 !important;
    letter-spacing:.35px !important;
}
div[data-testid="stDialog"] .war-room-focus,
div[data-testid="stDialog"] .war-room-update {
    color:#243858 !important;
    font-size:9px !important;
    line-height:1.25 !important;
    margin-top:2px !important;
}
div[data-testid="stDialog"] .war-room-muted {
    color:#7a8798 !important;
    font-size:7.5px !important;
    margin-top:2px !important;
}
div[data-testid="stDialog"] .war-room-avatars {
    display:flex !important;
    align-items:center !important;
    margin-top:3px !important;
}
div[data-testid="stDialog"] .war-room-avatar {
    width:22px !important;
    height:22px !important;
    border-radius:50% !important;
    display:inline-flex !important;
    align-items:center !important;
    justify-content:center !important;
    margin-right:-3px !important;
    background:#dff5ef !important;
    color:#087b71 !important;
    border:2px solid #fff !important;
    font-size:8px !important;
    font-weight:850 !important;
}

/* Compact station buttons and checklist controls. */
div[data-testid="stDialog"] [class*="st-key-select_action_station_"] button { min-height:32px !important; height:32px !important; padding:4px 7px !important; font-size:10px !important; }
div[data-testid="stDialog"] [class*="st-key-case_checklist_remove_"] button { width:24px !important; min-width:24px !important; height:24px !important; min-height:24px !important; font-size:15px !important; }

</style>
''', unsafe_allow_html=True)

st.markdown(r'''<style>
/* CASE DETAILS — compact header, tighter vertical rhythm */
div[data-testid="stDialog"] header {
    min-height:40px !important; height:40px !important; padding:2px 12px !important;
}
div[data-testid="stDialog"] header p {
    font-size:15px !important; font-weight:750 !important; margin:0 !important; line-height:1.1 !important;
}
div[data-testid="stDialog"] .case-detail-hero { margin:0 0 2px !important; padding:2px 5px 2px !important; }
div[data-testid="stDialog"] .case-detail-case-number { font-size:14px !important; line-height:1.1 !important; }
div[data-testid="stDialog"] .case-detail-subject { font-size:11.5px !important; line-height:1.2 !important; margin-top:1px !important; }
div[data-testid="stDialog"] .case-detail-copy { min-width:0 !important; }
div[data-testid="stDialog"] .case-detail-title-row { gap:8px !important; }
div[data-testid="stDialog"] .case-folder-icon { font-size:20px !important; }
div[data-testid="stDialog"] .case-detail-account-line {
    display:flex !important; align-items:center !important; flex-wrap:wrap !important; gap:6px !important;
    color:#526078 !important; font-size:8.5px !important; line-height:1.15 !important; margin-top:2px !important;
}
div[data-testid="stDialog"] .case-account-priority {
    display:inline-flex !important; padding:2px 5px !important; border-radius:999px !important;
    font-size:7px !important; font-weight:850 !important; letter-spacing:.2px !important;
}
div[data-testid="stDialog"] .case-account-priority.high { background:#ffe5e9 !important; color:#d33a4e !important; }
div[data-testid="stDialog"] .case-account-priority.normal { background:#eef2f6 !important; color:#66758d !important; }
div[data-testid="stDialog"] .case-detail-timing { min-width:460px !important; }
div[data-testid="stDialog"] .case-timing-item { padding:0 9px !important; }
div[data-testid="stDialog"] .case-timing-item span { font-size:7.5px !important; }
div[data-testid="stDialog"] .case-timing-item strong { font-size:9px !important; }
div[data-testid="stDialog"] .case-timing-icon { font-size:12px !important; }
div[data-testid="stDialog"] .case-summary-strip { padding:3px 3px !important; margin:1px 0 2px !important; }
div[data-testid="stDialog"] .case-summary-cell { padding:1px 7px !important; min-width:0 !important; }
div[data-testid="stDialog"] .case-summary-cell > span { font-size:7px !important; margin:0 0 1px !important; line-height:1 !important; }
div[data-testid="stDialog"] .case-summary-cell > strong { font-size:8.5px !important; line-height:1.05 !important; }

/* Compact dropdowns: remove the whitespace around labels and selected values. */
div[data-testid="stDialog"] [data-testid="stSelectbox"] { margin:0 !important; padding:0 !important; }
div[data-testid="stDialog"] [data-testid="stSelectbox"] > div { margin:0 !important; padding:0 !important; }
div[data-testid="stDialog"] [data-testid="stSelectbox"] label { margin:0 0 1px !important; padding:0 !important; font-size:8.5px !important; line-height:1 !important; }
div[data-testid="stDialog"] [data-testid="stSelectbox"] [data-baseweb="select"] { margin:0 !important; padding:0 !important; }
div[data-testid="stDialog"] [data-testid="stSelectbox"] [data-baseweb="select"] > div { min-height:25px !important; height:25px !important; padding:0 7px !important; margin:0 !important; border-radius:5px !important; }
div[data-testid="stDialog"] [data-testid="stSelectbox"] [data-baseweb="select"] span { font-size:8.5px !important; line-height:23px !important; }

/* Only the CURRENT station checklist is shown. */
div[data-testid="stDialog"] .case-checklist-wrap { margin:4px 0 4px !important; padding:6px 8px !important; }
div[data-testid="stDialog"] .case-checklist-title { font-size:10px !important; margin:0 0 1px !important; }
div[data-testid="stDialog"] .case-checklist-sub { font-size:8px !important; line-height:1.2 !important; margin:0 0 4px !important; }
div[data-testid="stDialog"] .case-checklist-status { padding:2px 6px !important; font-size:7.5px !important; margin:0 !important; }
div[data-testid="stDialog"] [data-testid="stCheckbox"] { margin:0 !important; padding:0 !important; min-height:22px !important; }
div[data-testid="stDialog"] [data-testid="stCheckbox"] label { font-size:9px !important; line-height:1.15 !important; padding:0 !important; margin:0 !important; }
div[data-testid="stDialog"] [data-testid="stCheckbox"] > div { padding:0 !important; margin:0 !important; }

/* Knowledge Base: readable white article, smaller questions and tighter SOP list. */
div[data-testid="stDialog"] .kb-panel-intro { padding:5px 7px !important; margin:0 0 4px !important; background:#fff !important; }
div[data-testid="stDialog"] .kb-panel-title { font-size:10px !important; }
div[data-testid="stDialog"] .kb-panel-sub { font-size:8px !important; line-height:1.2 !important; }
div[data-testid="stDialog"] .kb-suggested-title { font-size:7px !important; margin:3px 0 2px !important; }
div[data-testid="stDialog"] [class*="st-key-kb_suggested_"] { margin:0 !important; padding:0 !important; }
div[data-testid="stDialog"] [class*="st-key-kb_suggested_"] button {
    font-size:7.5px !important; line-height:1.12 !important; padding:3px 5px !important;
    min-height:22px !important; border-radius:4px !important; margin:0 0 2px !important;
}
div[data-testid="stDialog"] .kb-sop-list-title { font-size:7.5px !important; margin:4px 0 2px !important; }
div[data-testid="stDialog"] [class*="st-key-kb_sop_list_"] { margin:0 !important; padding:0 !important; }
div[data-testid="stDialog"] [class*="st-key-kb_sop_list_"] button {
    min-height:23px !important; height:23px !important; padding:2px 5px !important;
    font-size:7.5px !important; line-height:1 !important; border-radius:4px !important; margin:0 0 2px !important;
}
div[data-testid="stDialog"] .kb-selected-sop { padding:5px 7px !important; margin-top:3px !important; }
div[data-testid="stDialog"] .kb-selected-label { font-size:6.5px !important; }
div[data-testid="stDialog"] .kb-selected-sop-title { font-size:9px !important; line-height:1.15 !important; }
div[data-testid="stDialog"] .kb-selected-sop-meta { font-size:7px !important; margin-top:2px !important; }
div[data-testid="stDialog"] .kb-full-sop { padding:7px 9px !important; margin-top:4px !important; }
div[data-testid="stDialog"] .kb-full-sop-label { font-size:7px !important; margin-bottom:3px !important; }
div[data-testid="stDialog"] .kb-rich-content { font-size:8.5px !important; line-height:1.35 !important; color:#243858 !important; }
div[data-testid="stDialog"] .kb-rich-content p { margin:0 0 4px !important; }
div[data-testid="stDialog"] .kb-rich-content ul,
div[data-testid="stDialog"] .kb-rich-content ol { margin:1px 0 5px 15px !important; padding:0 !important; }
div[data-testid="stDialog"] .kb-rich-content li { margin:0 0 2px !important; padding-left:1px !important; }
div[data-testid="stDialog"] .kb-content-heading { font-size:8px !important; margin:5px 0 2px !important; }

/* Exact clickable War Room tile. */
div[data-testid="stDialog"] [class*="st-key-war_room_tile_"] { position:relative !important; min-height:88px !important; margin:0 !important; padding:0 !important; }
div[data-testid="stDialog"] [class*="st-key-war_room_tile_"] .war-room-mock { margin:0 !important; min-height:82px !important; box-sizing:border-box !important; cursor:pointer !important; transition:border-color .12s ease, box-shadow .12s ease !important; }
div[data-testid="stDialog"] [class*="st-key-war_room_tile_"] .war-room-mock:hover { border-color:#00a98f !important; box-shadow:0 0 0 2px rgba(0,169,143,.08) !important; }
div[data-testid="stDialog"] [class*="st-key-war_room_tile_"] [class*="st-key-war_room_open_button_"] { position:absolute !important; inset:0 !important; z-index:30 !important; margin:0 !important; padding:0 !important; }
div[data-testid="stDialog"] [class*="st-key-war_room_tile_"] [class*="st-key-war_room_open_button_"] button { position:absolute !important; inset:0 !important; width:100% !important; height:100% !important; background:transparent !important; border:0 !important; color:transparent !important; box-shadow:none !important; opacity:.001 !important; cursor:pointer !important; }
div[data-testid="stDialog"] .war-room-expanded {
    background:#f8fcfb !important; border:1px solid #cfe3e1 !important; border-radius:7px !important;
    padding:7px 9px !important; margin:4px 0 5px !important;
}
div[data-testid="stDialog"] .war-room-expanded-head { display:flex !important; justify-content:space-between !important; font-size:9px !important; color:#102041 !important; }
div[data-testid="stDialog"] .war-room-expanded-head span { color:#64748b !important; }
div[data-testid="stDialog"] .war-room-expanded-live { color:#087b71 !important; background:#e7faf5 !important; border-radius:999px !important; padding:2px 5px !important; font-size:6.5px !important; font-weight:850 !important; }
div[data-testid="stDialog"] .war-room-expanded-grid { display:grid !important; grid-template-columns:1fr 1fr !important; gap:10px !important; margin-top:5px !important; }
div[data-testid="stDialog"] .war-room-expanded-grid ul { margin:2px 0 0 14px !important; padding:0 !important; font-size:8px !important; line-height:1.3 !important; }
div[data-testid="stDialog"] .war-room-link { font-size:8.5px !important; color:#0879c9 !important; font-weight:750 !important; text-decoration:none !important; }

/* Preserve a single scroll surface and make it tall enough to reach the bottom. */

/* Remove old product-family/navigation tiles if any legacy markup remains. */
div[data-testid="stDialog"] .kb-product-family,
div[data-testid="stDialog"] .product-family-tiles,
div[data-testid="stDialog"] [class*="product-family"] { display:none !important; }

/* KNOWLEDGE BASE FINAL SPACING / READABILITY FIX */
div[data-testid="stDialog"] [class*="st-key-kb_sop_list_"] {
    margin:0 !important;
    padding:0 !important;
    min-height:0 !important;
}
div[data-testid="stDialog"] [class*="st-key-kb_sop_list_"] + div {
    margin-top:0 !important;
}
div[data-testid="stDialog"] [class*="st-key-kb_sop_list_"] button {
    min-height:26px !important;
    height:26px !important;
    padding:3px 6px !important;
    margin:0 0 2px 0 !important;
    font-size:8.5px !important;
    line-height:1.05 !important;
}
div[data-testid="stDialog"] .kb-full-sop-label {
    font-size:9px !important;
    margin-bottom:5px !important;
}
</style>''', unsafe_allow_html=True)


st.markdown(r'''
<style>
/* ============================================================
   CASE DETAILS FINAL FIX — requested compact reference spacing
   ============================================================ */
div[data-testid="stDialog"] header {
    min-height:40px !important;
    height:40px !important;
    padding:2px 12px !important;
    margin:0 !important;
}
div[data-testid="stDialog"] header p {
    font-size:16px !important;
    line-height:1.1 !important;
    font-weight:750 !important;
    margin:0 !important;
}
div[data-testid="stDialog"] header button {
    width:30px !important;
    height:30px !important;
    min-height:30px !important;
    padding:0 !important;
    margin:0 !important;
}
div[data-testid="stDialog"] [data-testid="stDialogContent"] {
    padding-top:0 !important;
    margin-top:0 !important;
}
div[data-testid="stDialog"] [data-testid="stDialogContent"] > div {
    margin-top:0 !important;
    padding-top:0 !important;
}
div[data-testid="stDialog"] .case-detail-hero {
    margin:0 0 3px 0 !important;
    padding:2px 4px 2px 4px !important;
}
div[data-testid="stDialog"] .case-detail-title-row {
    gap:10px !important;
}
div[data-testid="stDialog"] .case-folder-icon {
    font-size:20px !important;
    margin-top:1px !important;
}
div[data-testid="stDialog"] .case-detail-case-number {
    font-size:14px !important;
    line-height:1.05 !important;
}
div[data-testid="stDialog"] .case-copy-icon {
    font-size:12px !important;
    margin-left:4px !important;
}
div[data-testid="stDialog"] .case-priority-badge {
    font-size:8px !important;
    padding:3px 8px !important;
    margin-left:6px !important;
}
div[data-testid="stDialog"] .case-detail-subject {
    font-size:11px !important;
    line-height:1.15 !important;
    margin-top:2px !important;
}
div[data-testid="stDialog"] .case-detail-account-line {
    font-size:8px !important;
    line-height:1.1 !important;
    margin-top:2px !important;
}
div[data-testid="stDialog"] .case-detail-account-line span {
    margin-right:7px !important;
}
div[data-testid="stDialog"] .case-detail-timing {
    min-width:430px !important;
}
div[data-testid="stDialog"] .case-timing-item {
    padding:0 8px !important;
    gap:4px !important;
}
div[data-testid="stDialog"] .case-timing-item span {
    font-size:7px !important;
}
div[data-testid="stDialog"] .case-timing-item strong {
    font-size:8px !important;
    margin-top:1px !important;
}
div[data-testid="stDialog"] .case-timing-icon {
    font-size:11px !important;
}
div[data-testid="stDialog"] .case-due-badge {
    font-size:7px !important;
    padding:2px 4px !important;
    margin-left:3px !important;
}
div[data-testid="stDialog"] .case-summary-strip {
    margin:1px 0 3px !important;
    padding:2px 2px !important;
}
div[data-testid="stDialog"] .case-summary-cell {
    padding:1px 6px !important;
}
div[data-testid="stDialog"] .case-summary-cell > span {
    font-size:7px !important;
    margin:0 0 1px !important;
}
div[data-testid="stDialog"] .case-summary-cell > strong {
    font-size:8px !important;
    line-height:1.05 !important;
}
div[data-testid="stDialog"] .case-summary-cell .case-status-chip {
    font-size:7px !important;
    padding:2px 5px !important;
}
/* Assigned To is intentionally label-over-value like the other summary cells. */
div[data-testid="stDialog"] .case-summary-cell:first-child .case-avatar {
    display:none !important;
}
/* Dropdowns: compact label/value with no extra top/bottom whitespace. */
div[data-testid="stDialog"] [data-testid="stSelectbox"],
div[data-testid="stDialog"] [data-testid="stSelectbox"] > div,
div[data-testid="stDialog"] [data-testid="stSelectbox"] label {
    margin:0 !important;
    padding:0 !important;
}
div[data-testid="stDialog"] [data-testid="stSelectbox"] label {
    font-size:8px !important;
    line-height:1 !important;
    margin-bottom:1px !important;
}
div[data-testid="stDialog"] [data-testid="stSelectbox"] [data-baseweb="select"] > div {
    min-height:24px !important;
    height:24px !important;
    padding:0 6px !important;
    margin:0 !important;
}
div[data-testid="stDialog"] [data-testid="stSelectbox"] [data-baseweb="select"] span {
    font-size:8px !important;
    line-height:22px !important;
}
/* Current-station checklist only; no station selector row is rendered. */
div[data-testid="stDialog"] .case-checklist-wrap {
    margin:3px 0 3px !important;
    padding:5px 7px !important;
}
div[data-testid="stDialog"] .case-checklist-title {
    font-size:9px !important;
    margin:0 0 1px !important;
}
div[data-testid="stDialog"] .case-checklist-sub {
    font-size:7.5px !important;
    margin:0 0 3px !important;
}
div[data-testid="stDialog"] .case-checklist-status {
    font-size:7px !important;
    padding:2px 5px !important;
    margin:0 !important;
}
div[data-testid="stDialog"] [data-testid="stCheckbox"] {
    min-height:20px !important;
    margin:0 !important;
    padding:0 !important;
}
div[data-testid="stDialog"] [data-testid="stCheckbox"] label {
    font-size:8px !important;
    line-height:1.1 !important;
    margin:0 !important;
    padding:0 !important;
}
/* Knowledge Base: smaller text and tighter suggested/SOP tiles. */
div[data-testid="stDialog"] .kb-suggested-title {
    font-size:6.5px !important;
    margin:2px 0 1px !important;
}
div[data-testid="stDialog"] [class*="st-key-kb_suggested_"] button {
    font-size:7px !important;
    line-height:1.05 !important;
    min-height:20px !important;
    padding:2px 4px !important;
    margin:0 0 1px !important;
}
div[data-testid="stDialog"] .kb-sop-list-title {
    font-size:7px !important;
    margin:2px 0 1px !important;
}
div[data-testid="stDialog"] .kb-selected-sop {
    padding:4px 6px !important;
    margin-top:2px !important;
}
div[data-testid="stDialog"] .kb-selected-sop-title {
    font-size:8.5px !important;
}
div[data-testid="stDialog"] .kb-selected-sop-meta {
    font-size:6.5px !important;
}
div[data-testid="stDialog"] .kb-full-sop {
    padding:5px 7px !important;
    margin-top:2px !important;
}
div[data-testid="stDialog"] .kb-full-sop-label {
    font-size:6.5px !important;
    margin-bottom:2px !important;
}
div[data-testid="stDialog"] .kb-rich-content {
    font-size:8px !important;
    line-height:1.28 !important;
}
div[data-testid="stDialog"] .kb-rich-content p {
    margin:0 0 3px !important;
}
div[data-testid="stDialog"] .kb-rich-content ul,
div[data-testid="stDialog"] .kb-rich-content ol {
    margin:1px 0 4px 14px !important;
    padding:0 !important;
}
div[data-testid="stDialog"] .kb-rich-content li {
    margin:0 0 1px !important;
}
/* Remove the old recommendation presentation completely if legacy content exists. */
div[data-testid="stDialog"] .kb-recommendation,
div[data-testid="stDialog"] .kb-recommendation-label,
div[data-testid="stDialog"] [class*="recommended-guidance"] {
    display:none !important;
}
/* War Room: the exact visible tile is the click target. */
div[data-testid="stDialog"] [class*="st-key-war_room_tile_"] {
    position:relative !important;
    margin:0 !important;
    padding:0 !important;
}
div[data-testid="stDialog"] [class*="st-key-war_room_tile_"] .war-room-mock {
    cursor:pointer !important;
}
div[data-testid="stDialog"] [class*="st-key-war_room_tile_"] [class*="st-key-war_room_open_button_"] {
    position:absolute !important;
    inset:0 !important;
    z-index:100 !important;
}
div[data-testid="stDialog"] [class*="st-key-war_room_tile_"] [class*="st-key-war_room_open_button_"] button {
    position:absolute !important;
    inset:0 !important;
    width:100% !important;
    height:100% !important;
    min-height:100% !important;
    background:transparent !important;
    border:0 !important;
    opacity:.001 !important;
    color:transparent !important;
    cursor:pointer !important;
}
/* CASE DETAILS — RESTORE THE NATIVE SCROLLBAR.
   This is the single scroll surface inside the dialog. */
div[data-testid="stDialog"] [class*="st-key-case_detail_scroll_"] {
    height:calc(100vh - 185px) !important;
    max-height:calc(100vh - 185px) !important;
    min-height:220px !important;
    overflow-y:auto !important;
    overflow-x:hidden !important;
    overscroll-behavior:contain !important;
    scrollbar-width:thin !important;
    scrollbar-color:rgba(71,85,105,.48) transparent !important;
    padding-bottom:18px !important;
    box-sizing:border-box !important;
}
div[data-testid="stDialog"] [class*="st-key-case_detail_scroll_"]::-webkit-scrollbar {
    width:7px !important;
}
div[data-testid="stDialog"] [class*="st-key-case_detail_scroll_"]::-webkit-scrollbar-thumb {
    background:rgba(71,85,105,.48) !important;
    border-radius:999px !important;
}
div[data-testid="stDialog"] [class*="st-key-case_detail_scroll_"]::-webkit-scrollbar-thumb:hover {
    background:rgba(30,41,59,.68) !important;
}
</style>

''', unsafe_allow_html=True)

st.markdown(r"""
<style>
/* CASE DETAILS — ONLY tighten the vertical space between Matching SOP tiles.
   Do NOT change the parent dialog/vertical-block gap, because that affects
   unrelated Case Details content. */
div[data-testid="stDialog"] [class*="st-key-kb_sop_list_"] {
    margin-top:-5px !important;
    margin-bottom:-5px !important;
    padding-top:0 !important;
    padding-bottom:0 !important;
    min-height:0 !important;
}
div[data-testid="stDialog"] [class*="st-key-kb_sop_list_"] > div {
    margin:0 !important;
    padding:0 !important;
}
div[data-testid="stDialog"] [class*="st-key-kb_sop_list_"] button {
    min-height:24px !important;
    height:24px !important;
    padding:2px 6px !important;
    margin:0 !important;
    font-size:8.5px !important;
    line-height:1 !important;
}
/* Equal bottom breathing room, matching the compact top spacing. */
div[data-testid="stDialog"] [class*="st-key-case_detail_scroll_"] {
    padding-bottom:18px !important;
}
div[data-testid="stDialog"] [data-testid="stDialogContent"] {
    padding-bottom:18px !important;
}
</style>
""", unsafe_allow_html=True)

st.markdown(r"""
<style>
/* USER REQUEST — ONLY these two typography changes.
   1) Matching SOP tiles: one smaller, uniform font size.
   2) Case Details tabs: smaller, uniform tab-label font size.
   No spacing, layout, scrollbar, content, or functionality changes. */

/* 1. MATCHING SOP TILES — smaller + same font size everywhere */
div[data-testid="stDialog"] [class*="st-key-kb_sop_list_"] button,
div[data-testid="stDialog"] [class*="st-key-kb_sop_list_"] button *,
div[data-testid="stDialog"] [class*="st-key-kb_sop_list_"] button p,
div[data-testid="stDialog"] [class*="st-key-kb_sop_list_"] button div,
div[data-testid="stDialog"] [class*="st-key-kb_sop_list_"] button span {
    font-size:7px !important;
    line-height:1 !important;
}

/* 2. CASE DETAILS TABS — smaller + same font size */
div[data-testid="stDialog"] [data-testid="stTabs"] [role="tab"],
div[data-testid="stDialog"] [data-testid="stTabs"] [role="tab"] *,
div[data-testid="stDialog"] [data-testid="stTabs"] [role="tab"] p,
div[data-testid="stDialog"] [data-testid="stTabs"] [role="tab"] span {
    font-size:10px !important;
    line-height:1.1 !important;
}

/* ============================================================
   FONT-SIZE-ONLY PATCH — 2026-10-06
   User requested ONLY:
   1) Knowledge Base search section: one smaller uniform font size.
   2) Case Actions + Collaboration sections: one smaller uniform font size.
   No spacing, layout, color, functionality, or control-size changes.
   ============================================================ */

/* 1. KNOWLEDGE BASE SEARCH SECTION */
div[data-testid="stDialog"] [role="tabpanel"]:has(.kb-panel-intro) * {
    font-size:9px !important;
}

/* 2. CASE ACTIONS + COLLABORATION SECTIONS */
div[data-testid="stDialog"] [role="tabpanel"]:has(.case-checklist-wrap) *,
div[data-testid="stDialog"] [role="tabpanel"]:has(.meeting-panel) * {
    font-size:9px !important;
}

</style>
""", unsafe_allow_html=True)
