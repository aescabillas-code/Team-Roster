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


import base64
import hashlib
import hmac
import html
import os
import re
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
ALERT_DEFINITION_COLLECTION = "Alert_Definition_Collection"
KB_COLLECTION = "Knowledge_Base_Collection"
SOP_COLLECTION = "SOP_Collection"
ACCOUNT_PRIORITY_COLLECTION = "Account_Priority_Collection"


# Performance tuning: retain a short cache so the 1-second UI fragment does not
# force a MongoDB read on every tick. This reduces database/network churn while
# keeping the dashboard visually current.
TASK_CACHE_TTL = 1.0
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

CASE_STATUS_OPTIONS = [
    "Open",
    "In Progress",
    "Pending Customer",
    "Pending Internal",
    "On Hold",
    "Escalated",
    "Resolved",
    "Completed",
    "Closed",
]




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
        # Dashboard query is active=True and sorted by station_started_at.
        # This compound index avoids an unnecessary MongoDB sort on every
        # short-lived dashboard data refresh.
        col(TASKS_COLLECTION).create_index(
            [("active", ASCENDING), ("station_started_at", ASCENDING)]
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
        col(ACCESS_COLLECTION).create_index(
            [("browser_fingerprint", ASCENDING), ("code_fingerprint", ASCENDING), ("authorized", ASCENDING)]
        )
        col(ACCESS_COLLECTION).create_index(
            [("request_fingerprint", ASCENDING), ("code_fingerprint", ASCENDING), ("authorized", ASCENDING)]
        )
        col(ACCESS_COLLECTION).create_index(
            [("simulation_profile_key", ASCENDING), ("simulation_event_id", ASCENDING), ("authorized", ASCENDING)]
        )
        col(ALERT_COLLECTION).create_index(
            [("acknowledged", ASCENDING), ("created_at", DESCENDING)]
        )
        col(ALERT_COLLECTION).create_index(
            [("task_id", ASCENDING), ("trigger_key", ASCENDING), ("alert_type", ASCENDING)]
        )
        col(ALERT_COLLECTION).create_index(
            [("alert_type", ASCENDING), ("trigger_key", ASCENDING), ("active", ASCENDING)]
        )
        col(ALERT_DEFINITION_COLLECTION).create_index(
            [("alert_key", ASCENDING)],
            unique=True,
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




def format_elapsed_duration(seconds):
    """Format a station duration as HH:MM:SS without changing the live clock logic."""
    try:
        total = max(0, int(round(float(seconds or 0))))
    except Exception:
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def case_station_durations(task, now=None):
    """Return the elapsed duration for each station in the case journey."""
    now = as_utc(now) or utc_now()
    history = [x for x in (task.get("history") or []) if isinstance(x, dict)]
    history = sorted(
        history,
        key=lambda x: as_utc(x.get("timestamp"))
        or datetime.min.replace(tzinfo=timezone.utc),
    )
    durations = {}
    current_station = None
    station_started = None

    for event in history:
        stamp = as_utc(event.get("timestamp"))
        if not stamp:
            continue
        action = text(event.get("action"))
        match = re.search(
            r"Transferred from (.+?) to (.+?)(?:$|\\.)",
            action,
            flags=re.IGNORECASE,
        )
        if match:
            source = station_name(match.group(1))
            destination = station_name(match.group(2))
            if current_station is None:
                current_station = source
                station_started = stamp
            if current_station == source and station_started:
                durations[source] = durations.get(source, 0) + max(
                    0, (stamp - station_started).total_seconds()
                )
            current_station = destination
            station_started = stamp
            continue

        entered = re.search(
            r"(?:Case entered|Entered) (.+?)(?: station)?(?:\\.|$)",
            action,
            flags=re.IGNORECASE,
        )
        if entered:
            entered_station = station_name(entered.group(1))
            if current_station is None:
                current_station = entered_station
                station_started = stamp

    live_station = station_name(task.get("department"))
    live_started = as_utc(task.get("station_started_at"))
    if live_station and live_started:
        current_duration = max(
            0, (now - live_started).total_seconds()
        )
        durations[live_station] = current_duration

    return durations


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
    # to Streamlit on the next request. This is the primary persistence path
    # for both desktop and mobile browsers, so mobile cannot bypass the
    # one-time access-code gate.
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


            const sessionStores = [];
            const addSessionStore = (store) => {{
                if (store && !sessionStores.includes(store)) sessionStores.push(store);
            }};
            try {{ addSessionStore(window.top.sessionStorage); }} catch (e) {{}}
            try {{ addSessionStore(window.parent.sessionStorage); }} catch (e) {{}}
            try {{ addSessionStore(window.sessionStorage); }} catch (e) {{}}

            for (const store of sessionStores) {{
                try {{
                    const value = store.getItem(key);
                    if (value) return value;
                }} catch (e) {{}}
            }}


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
                const sessionStores = [];
                const addSessionStore = (store) => {{
                    if (store && !sessionStores.includes(store)) sessionStores.push(store);
                }};
                try {{ addSessionStore(window.top.sessionStorage); }} catch (e) {{}}
                try {{ addSessionStore(window.parent.sessionStorage); }} catch (e) {{}}
                try {{ addSessionStore(window.sessionStorage); }} catch (e) {{}}

                for (const store of sessionStores) {{
                    try {{
                        store.setItem(key, value);
                        saved = true;
                    }} catch (e) {{}}
                }}
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


            const sessionStores = [];
            const addSessionStore = (store) => {{
                if (store && !sessionStores.includes(store)) sessionStores.push(store);
            }};
            try {{ addSessionStore(window.top.sessionStorage); }} catch (e) {{}}
            try {{ addSessionStore(window.parent.sessionStorage); }} catch (e) {{}}
            try {{ addSessionStore(window.sessionStorage); }} catch (e) {{}}

            for (const store of sessionStores) {{
                try {{
                    store.removeItem(key);
                    cleared = true;
                }} catch (e) {{}}
            }}
            return cleared ? 'cleared' : 'error';
        }} catch (e) {{
            return 'error';
        }}
    }})()
    """


    result = _js_parent_storage(expression, JS_CLEAR_KEY)
    return result == "cleared"




def _browser_fingerprint():
    """Return a stable browser-profile fingerprint without exposing raw browser data."""
    expression = """
    (() => {
        try {
            return [
                navigator.userAgent || '',
                navigator.platform || '',
                navigator.language || '',
                Intl.DateTimeFormat().resolvedOptions().timeZone || '',
                String(navigator.hardwareConcurrency || ''),
                String(navigator.maxTouchPoints || ''),
                String(navigator.vendor || '')
            ].join('|');
        } catch (e) {
            return '';
        }
    })()
    """
    value = _js_parent_storage(expression, "hpe_caseflow_browser_fingerprint_v1")
    if value is None:
        return None
    raw = str(value or "").strip()
    return sha256(raw) if raw else ""



def _server_request_fingerprint():
    """Stable server-side fallback for mobile browsers that do not retain JS storage."""
    try:
        context = getattr(st, "context", None)
        headers = getattr(context, "headers", None)
        if not headers:
            return ""
        values = []
        for key in (
            "user-agent",
            "accept-language",
            "sec-ch-ua",
            "sec-ch-ua-mobile",
            "sec-ch-ua-platform",
            "x-forwarded-for",
        ):
            value = headers.get(key, "")
            if key == "x-forwarded-for" and value:
                value = str(value).split(",")[0].strip()
            values.append(str(value or "").strip())
        raw = "|".join(values)
        return sha256(raw) if raw else ""
    except Exception:
        return ""


def _server_browser_authorized(fingerprint):
    """Fallback authorization for mobile/browser profiles where storage is unavailable."""
    if not fingerprint:
        return False
    access_code_value, _ = _get_access_secrets()
    code_fp = _get_code_fingerprint(access_code_value) if access_code_value else ""
    if not code_fp:
        return False
    try:
        query = {
            "code_fingerprint": code_fp,
            "authorized": True,
            "$or": [
                {"browser_fingerprint": fingerprint},
                {"request_fingerprint": fingerprint},
            ],
        }
        return bool(col(ACCESS_COLLECTION).find_one(query, {"_id": 1}))
    except Exception:
        return False


def browser_is_authorized():
    """
    Check session state first, then signed browser storage, then the
    server-side browser-profile fallback used when mobile storage is blocked.
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

    fingerprint = _browser_fingerprint()
    if fingerprint is None:
        return None
    if _server_browser_authorized(fingerprint):
        st.session_state["access_authorized"] = True
        st.session_state["access_granted"] = True
        return True

    request_fp = _server_request_fingerprint()
    if request_fp and _server_browser_authorized(request_fp):
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

    fingerprint = _browser_fingerprint()
    request_fp = _server_request_fingerprint()
    if fingerprint or request_fp:
        access_code_value, _ = _get_access_secrets()
        try:
            identity = {
                "code_fingerprint": _get_code_fingerprint(access_code_value),
            }
            if fingerprint:
                identity["browser_fingerprint"] = fingerprint
            if request_fp:
                identity["request_fingerprint"] = request_fp
            col(ACCESS_COLLECTION).update_one(
                identity,
                {"$set": {"authorized": True, "authorized_at": utc_now()}},
                upsert=True,
            )
        except Exception:
            pass


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

    fingerprint = _browser_fingerprint()
    request_fp = _server_request_fingerprint()
    if fingerprint or request_fp:
        access_code_value, _ = _get_access_secrets()
        try:
            code_fp = _get_code_fingerprint(access_code_value)
            filters = [{"browser_fingerprint": fingerprint}] if fingerprint else []
            if request_fp:
                filters.append({"request_fingerprint": request_fp})
            col(ACCESS_COLLECTION).delete_many({
                "code_fingerprint": code_fp,
                "$or": filters,
            })
        except Exception:
            pass


def access_gate():
    """
    One-time access-code gate with the same authorization requirement on
    desktop and mobile browsers. A valid signed browser token is the only
    bypass after the code has been entered successfully.
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
    "show_alerts": False,
    "show_settings": False,
    "admin_unlocked": False,
    "simulation_case_id": None,
    "simulation_alert_active": False,
    "simulation_alert_case_id": None,
    "simulation_alert_event_id": None,
    "simulation_alert_delay_until": 0.0,
    "simulation_alert_dismissed": False,
    "open_case_after_alert": False,
    "pending_case_dialog_id": None,
    "simulation_active": False,
    "search": "",
    # Marks the start of this browser session so a stale global simulation
    # event from an earlier run is never shown simply because the app was reopened.
    "app_session_started_at": utc_now(),
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


    /* Keep native controls responsive during the dashboard's background
       fragment refreshes. These are interaction-only hints and do not alter
       the existing control dimensions or functionality. */
    button, [role="button"], [data-baseweb="tab"], input, select {
        -webkit-tap-highlight-color:transparent !important;
    }
    button, [role="button"], [data-baseweb="tab"] {
        touch-action:manipulation !important;
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
    /* Fragment refresh is intentionally invisible: no spinner/status flash,
       no progress indicator, and no pointer interception during the 1-second
       monitoring rerun. */
    [data-testid="stStatusWidget"],
    [data-testid="stSpinner"],
    [data-testid="stProgress"],
    [data-testid="stAppRunningIndicator"],
    .stSpinner,
    .stProgress {
        display:none !important;
        opacity:0 !important;
        visibility:hidden !important;
        pointer-events:none !important;
    }

    /* Monitoring reruns must never steal focus or create a visible loading flash. */
    [data-testid="stAppViewContainer"] {
        scroll-behavior:auto !important;
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
        touch-action:manipulation !important; -webkit-tap-highlight-color:transparent !important;
    }
    /* ACTIVE SLA WARNING: intentionally strong and unmistakable. */
    .station-card-visual.critical-red {
        border:2px solid #ef334f !important;
        animation:stationCardFlash .55s ease-in-out infinite alternate;
    }
    .station-card-visual.critical-red.selected {
        border-width:3px !important;
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
    .station-alert-icon.red {
        background:#ef1738 !important;
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


    .station-card-visual.warning-muted,
    .station-card-visual.warning-muted.critical-red {
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
    /* Duration color follows each station's own SLA:
       green = more than 40% of the station timeframe remains,
       amber = 40% or less remains,
       red = final 20% / breach. */
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


    .duration-alert-icon {
        display:inline-flex;
        align-items:center;
        justify-content:center;
        width:15px;
        height:15px;
        margin-left:5px;
        border-radius:50%;
        font-size:10px;
        line-height:1;
        font-weight:950;
        vertical-align:middle;
        animation:durationAlertIconFlash .48s ease-in-out infinite alternate;
    }
    .duration-alert-icon.amber {
        background:#d9a400;
        color:#fff;
        box-shadow:0 0 0 2px rgba(217,164,0,.15);
    }
    .duration-alert-icon.red {
        background:#ef1738;
        color:#fff;
        box-shadow:0 0 0 2px rgba(239,23,56,.15);
    }
    .duration-alert-icon.hidden {
        display:none !important;
        animation:none !important;
    }
    @keyframes durationAlertIconFlash {
        from { opacity:.45; transform:scale(.82); }
        to { opacity:1; transform:scale(1.12); }
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


        /* Mobile case table: keep the useful operational fields on one
           readable row. Assigned To and Due Date remain available in Case
           Details; on phones they are intentionally collapsed to preserve
           a clear table rather than stacking every column vertically. */
        [data-testid="stHorizontalBlock"]:has(.case-head) > div:nth-child(4),
        [data-testid="stHorizontalBlock"]:has(.case-head) > div:nth-child(5),
        [data-testid="stHorizontalBlock"]:has([class*="st-key-case_cell_"]) > div:nth-child(4),
        [data-testid="stHorizontalBlock"]:has([class*="st-key-case_cell_"]) > div:nth-child(5) {
            display:none !important;
        }

        [data-testid="stHorizontalBlock"]:has(.case-head),
        [data-testid="stHorizontalBlock"]:has([class*="st-key-case_cell_"]) {
            display:grid !important;
            grid-template-columns:1.15fr 2.15fr .95fr 1.00fr .90fr !important;
            grid-auto-flow:row !important;
            gap:4px !important;
            width:100% !important;
            align-items:center !important;
        }

        [data-testid="stHorizontalBlock"]:has(.case-head) > div,
        [data-testid="stHorizontalBlock"]:has([class*="st-key-case_cell_"]) > div {
            min-width:0 !important;
            width:auto !important;
            max-width:none !important;
            flex:0 0 auto !important;
            margin:0 !important;
            padding:0 !important;
            align-self:stretch !important;
            grid-column:auto !important;
        }

        [data-testid="stHorizontalBlock"]:has(.case-head) .case-head {
            min-height:27px !important;
            padding:6px 5px !important;
            white-space:nowrap !important;
            overflow:hidden !important;
            text-overflow:ellipsis !important;
        }

        [data-testid="stHorizontalBlock"]:has([class*="st-key-case_cell_"]) .case-row,
        [data-testid="stHorizontalBlock"]:has([class*="st-key-case_cell_"]) .agent-cell,
        [data-testid="stHorizontalBlock"]:has([class*="st-key-case_cell_"]) .due-cell {
            min-height:32px !important;
            padding:4px 5px !important;
            box-sizing:border-box !important;
        }

        [class*="st-key-case_cell_"] button {
            font-size:9px !important;
            padding:3px 5px !important;
            min-height:30px !important;
            height:30px !important;
        }
        .priority-pill { font-size:8px !important; padding:4px 5px !important; }
        .duration-warning-wrap { font-size:9px !important; }
        [data-testid="stHorizontalBlock"]:has([class*="st-key-case_cell_"]) .badge {
            white-space:nowrap !important;
            font-size:8px !important;
            padding:5px 6px !important;
        }


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

/* Case Details typography follows the supplied reference: Inter with the
   same compact sizing used throughout the reference workspace. */
div[data-testid="stDialog"],
div[data-testid="stDialog"] [data-testid="stDialogContent"],
div[data-testid="stDialog"] [data-testid="stDialogContent"] * {
    font-family:"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
}
div[data-testid="stDialog"] [data-testid="stDialogContent"] {
    font-size:9px !important;
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
div[data-testid="stDialog"] [data-baseweb="tab-list"] {
    gap:0 !important;
    border-bottom:1px solid #dbe4ee !important;
    overflow-x:auto !important;
    scrollbar-width:none !important;
    -webkit-overflow-scrolling:touch !important;
}
div[data-testid="stDialog"] [data-baseweb="tab-list"]::-webkit-scrollbar { display:none !important; }
div[data-testid="stDialog"] [data-baseweb="tab"] {
    padding:8px 15px !important;
    min-height:32px !important;
    color:#334155 !important;
    font-size:12px !important;
    line-height:16px !important;
    white-space:nowrap !important;
    cursor:pointer !important;
    touch-action:manipulation !important;
    -webkit-tap-highlight-color:transparent !important;
}
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
.history-station-duration {
    margin:0 0 10px 0;
    padding:9px 11px;
    border:1px solid #dbe4ee;
    border-radius:8px;
    background:#f8fafc;
}
.history-station-duration-title {
    font-size:10px;
    font-weight:800;
    color:#334155;
    margin-bottom:7px;
}
.history-duration-grid {
    display:grid;
    grid-template-columns:repeat(auto-fit,minmax(125px,1fr));
    gap:6px;
}
.history-duration-item {
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:8px;
    padding:6px 8px;
    border-radius:6px;
    background:#fff;
    color:#52637b;
    font-size:9px;
}
.history-duration-item strong {
    color:#102041;
    font-size:9px;
    font-variant-numeric:tabular-nums;
}

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
        "issue": 1,
        "station_warning_ack_trigger": 1,
        "station_warning_acknowledged_at": 1,
        "active": 1,
        "is_mock": 1,
        "simulation_hold": 1,
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


    # Early SLA warning begins when 40% of the station timeframe remains.
    # The case stays AMBER/MEDIUM at this point; CRITICAL remains the final
    # 20% of the SLA. Once elapsed time reaches the SLA, the case is past due.
    nearing_due = (remaining > 0) and (remaining <= sla * 0.40)
    past_due = remaining <= 0


    if priority_account:
        status = "CRITICAL"
    elif remaining <= 0:
        status = "BREACHED"
    elif remaining <= sla * 0.20:
        status = "CRITICAL"
    elif remaining <= sla * 0.40:
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


def display_priority_label(state):
    """Single display rule for both the case table and Case Details."""
    if state.get("priority_account"):
        return "Critical"
    if state.get("status") in {"CRITICAL", "BREACHED"}:
        return "Critical"
    if state.get("status") == "MEDIUM":
        return "Medium"
    return "Low"



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
        "history": [{"action": f"Case entered {station_name(station)}", "timestamp": started, "station": station}],
    }


GLOBAL_SIMULATION_ALERT_KEY = "OVR_VW_GLOBAL_SIMULATION_PRIORITY_ACCOUNT"


def _simulation_profile_key():
    """Return a stable per-browser key for one-time simulation-alert display."""
    token = _read_browser_token()
    if token and validate_browser_token(token):
        return "token:" + sha256(token)
    fingerprint = _browser_fingerprint()
    if fingerprint:
        return "browser:" + fingerprint
    request_fp = _server_request_fingerprint()
    return "request:" + request_fp if request_fp else ""


def _simulation_event_seen(event_id):
    profile_key = _simulation_profile_key()
    if not profile_key or not event_id:
        return False
    try:
        return bool(col(ACCESS_COLLECTION).find_one({
            "simulation_profile_key": profile_key,
            "simulation_event_id": event_id,
            "authorized": True,
        }, {"_id": 1}))
    except Exception:
        return False


def _mark_simulation_event_seen(event_id):
    profile_key = _simulation_profile_key()
    if not profile_key or not event_id:
        return
    try:
        col(ACCESS_COLLECTION).update_one(
            {
                "simulation_profile_key": profile_key,
                "simulation_event_id": event_id,
            },
            {
                "$set": {
                    "authorized": True,
                    "simulation_seen_at": utc_now(),
                }
            },
            upsert=True,
        )
    except Exception:
        pass




def _get_global_simulation_event():
    try:
        return col(ALERT_COLLECTION).find_one({
            "alert_type": "SIMULATION_PRIORITY_ACCOUNT",
            "trigger_key": GLOBAL_SIMULATION_ALERT_KEY,
            "active": True,
        })
    except Exception:
        return None


def _set_global_simulation_event(task_id, triggered_at):
    try:
        col(ALERT_COLLECTION).update_one(
            {
                "alert_type": "SIMULATION_PRIORITY_ACCOUNT",
                "trigger_key": GLOBAL_SIMULATION_ALERT_KEY,
            },
            {"$set": {
                "task_id": str(task_id),
                "triggered_at": as_utc(triggered_at) or utc_now(),
                "active": True,
                "acknowledged": False,
                "updated_at": utc_now(),
            }},
            upsert=True,
        )
    except Exception:
        pass


def _clear_global_simulation_event():
    try:
        col(ALERT_COLLECTION).delete_many({
            "alert_type": "SIMULATION_PRIORITY_ACCOUNT",
            "trigger_key": GLOBAL_SIMULATION_ALERT_KEY,
        })
    except Exception:
        pass


def reset_mock_case_durations():
    """Reset all 25 mock cases to their original seeded state and SLA demo timing.

    The reset intentionally restores the original station, assignee, status,
    checklist and seeded case fields first. This means mock cases may be moved
    and updated during a demonstration, but Reset always returns them to the
    state in which they were originally seeded.
    """
    reset_now = utc_now()
    _clear_global_simulation_event()
    # Five cases per station are restored in staggered, non-breached states.
    # The latest mock case is only 50% elapsed, so no seeded case reaches the
    # 40%-remaining early-warning threshold during reset. Simulation then
    # promotes exactly one CARE case to the H&M critical-account alert.
    elapsed_ratios = [0.00, 0.15, 0.30, 0.40, 0.50]
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
        # Reset all seeded account-priority flags so the simulation starts
        # with exactly one alerting case across all five stations.
        restore.update({
            "created_at": started_at,
            "station_started_at": started_at,
            "last_update": reset_now,
            "due_date": due_date,
            "priority": "Medium" if station_index == 1 else "Low",
            "account_priority": "No",
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
                        "collaboration_history": "",
                        "attachments": "",
                        "files": "",
                        "war_room": "",
                        "active_war_rooms": "",
                        "simulation_collaboration": "",
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
                "history": [{"action": f"Case entered {station_name(station)}", "timestamp": started, "station": station}],
            })
            case_index += 1

    if docs:
        col(TASKS_COLLECTION).insert_many(docs)
    clear_task_cache()
    return len(docs)


# ============================================================
# ALERT ENGINE
# ============================================================






SIMULATION_ALERT_SOUND_B64 = "SUQzBAAAAAABCVRYWFgAAAASAAADbWFqb3JfYnJhbmQAaXNvbQBUWFhYAAAAEwAAA21pbm9yX3ZlcnNpb24ANTEyAFRYWFgAAAAkAAADY29tcGF0aWJsZV9icmFuZHMAaXNvbWlzbzJhdmMxbXA0MQBUU1NFAAAADgAAA0xhdmY2My4xLjEwMQAAAAAAAAAAAAAA//tQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAASW5mbwAAAA8AAAIrAAOK7wACBQgLDQ8SFRcaHB8iJCYpLC4xMzY4Oz1AQ0VISk1PUlVXWVxfYWRmaWxucHN2eHp9gIOFh4qNkJGUl5qbnqGkp6irrrGztbi7vb/CxcjKzM/S1NbZ3N7h4+bp6+7w8/X4+v0AAAAATGF2YzYzLjEuAAAAAAAAAAAAAAAAJALVAAAAAAADiu+nW7BNAAAAAAAAAAAAAAAAAAAAAP/7kGQAD/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABExBTUUzLjEwMFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUxBTUUzLjEwMFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVX/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAARVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUxBTUUzLjEwMFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVX/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAARVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUxBTUUzLjEwMFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVX/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAARVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUxBTUUzLjEwMFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVU7Ymz/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAAT/SnAQHmVQVmr9h97DQKBc85akzcVX/WwrAbfpUd5Ohg3AFzAG+4qAGhFB/KpEBXwMMYWgMCQPAMUhArYcuAoBAuEEAyXCKAx5CcAw8BwAKEp8UQiZOFwogZHBTAYSgXAMAwAoBIAAHf5Ex3mieBhZA6BjtCmBg2CECgEQHgSAwTAA/sgt3wMCICQt2EAFAMFQDgMMQGAMDIFwwJ/+7Jm+HxhjwBQEAWBICwBgMCwCgMDwDhHgep///4GBkAIbILAAEA8MTjvAaAeGXBsCCQZF/////AOAeBgbACJsKox4Whh74DAEwy4PAjgLnBoAsAALh/////////8rDjGKAAAAggQBAYDAgFICoBMGhVQ8EANWxjYQGzOQ2CCGYEa4cPDUHgMCj8yGFTrgiEYYMOGMKAY5kgUIAhWCzFGBrDNNM8ltWGo62qxYPL1jQRlGIWHGGbriELxnCAbGLH5Te/wEmruimm6BYCHsa0ygPsXy6cXz+IKHDR09Tez6Gx4K//uSZMCAABgAgAV0AAgAAA0goAABH44M5hnbAAgAADSDAAAAQZVVHEBj/oCwwN+HYnHl48LZMOUMOapELZXhcawxCQNIXRVYg/GbZ7NWs0vHKb4/Hd6dzP4NzXY7kULptgdRXFX8JXv9TFHVpe///+5JFq8n7//IzJDLNp92KSktPGwdak32BNRx5Ls9//urGJbze/zm5rn//6j2nAAAAAu19V6JyK3DoJCQXGLobBwZGD4xGX9aG7qJnqcOGbAgmFYHFAZlry7ada4F+N2ZM5zCWJSepSR2PoYmDApyyAm87bDBHmGAAyQzKrtXHG1lGtdmp1uNM3ExAJDh6BrVx3YUYyhioFF6eQwLZ//3M0954RCECwK5M7hQWeUDKhIKGhG9lKtfvn27a0kq4pKa2X/+dPUhoVCFaaSpn+rW6rBI1h///////6TugbO93PCQtCyz///////8ce6U/TZQFIZ3//////////XMoCfmJ7i1QAAEqvxFeMJIAIQKAeYF4HhgAAFmBgBSYWY2RtoiNmpctGGCJGAoAiYBADK/hoBeFf/7kmT/gAfKZFFWcyAEAAANIMAAABqFfzad3YAIAAA0g4AABAAw5nTJqN0XNlr+4TL6rlHQMbNYJhkNJMmAg2aFrZhQL3WIu1jldtblPNU05ZfpwhEjHKm6l90kMzKQ9Eii06Oxml/f/9C12EPUQioWGkufOVRqezweMLlFHGasS7Lm/zsYw+PELchq8/esJDWwUCKwlN9w5NECJkrhaebldv3nS6RoJQHAblZyZNQvwKM3/5gTrEwFFmxiJATbv//y+kJYLCITOifEIAyvu4pWwBO4wDgFzBiAwMAEAcwJgLjDLM/NwMdI1f3pjCCAOCACkjUJzX5+GGrvLI4rT0ErgbepkqAAZCJkiHGBBKmMAgscYSAGTUtgaW2ub//39WDFZn9WKZDEo8VWLS2tBY4AgswDAIBgqW0zP8gRBiaCTQETwiy0kjI3Lgs8DJJwGH5OFwdZmhpFUiIRAgBGB2jLN0jhJKIaAlOCI6WF9RkbAoVIml/edNy6CEwDgCRgtA2CQgiC//ywQ9ZFgYJVFYDS03//6BfDWEXC6krqPiAAQAD/+5Jk14f2umDLq9yc9AAADSAAAAEadYMsj3KNwAAANIAAAAT+yFj7yGASAmUBOFYhBgfgUGBqFIOvAmRSLsaoGdZieg0lAQxZJVsvhy3M83nKqOmq6rxxPUQCo1liTCxGQXf48TUDMAMQ3byL2LeGH/+dI7bC3VSnMjOMBFdskbjEPsENEnExqEi7L/UuWOX/+5iLQUSFwaSEp5zKpTSleRhZIGHQJM5OzKb/M6kXJ4LXAN0FFkERPeo6YC/AhhC58pLVdBzQDKjCImbfU9F0wF0AFnBIGqyMNwbrA4Afb/7j5XBZkmiVgoSPpf/+wNQAFg4ZsZJkAUtyKs6ZySgGGBUBAYZwJZgogQGC2FYYki75yWF0GMPoIYH4TBgXgDmCYGGAQDs4VzGqCXxmktX6XWdSVp6AUOzZVJjDEGxIEDAwDzMaWyAG0JD7yivUzz//xrNxTtXUDQIMTC8Aw7MRiUfaQFwHMXjnJitoqPj/5QCUwCYUttmRwi4zAGn3ASqC4yLiuFBPMSSGaCwQGzFjaIik3ugRcDDIQUpkgbodAjwM//uSZMED9rRgScPcpHAAAA0gAAABGpF9Jq92jdAAADSAAAAEcfLyvepS7kyBUAC006yykUAIjwWCmzf/kfNwc7ohuwtKf//8XwKHg5RAAAY1I+2BbYhAcGQLjAhBjIQEA4KcxjBWDvoFhMTfMMwJwMTAsAaMBQFLMPuXfdtdblu+/7/xen5hbXxI0YDgAlzB4BQwIjBsJjMiahIUllulEaarrnf3hXZglNL0qDGEhgwaGbzlqIjIBGJCAAQEUvndlxdSR+ssAnGALGJqUssIk0GNQND3AlVHo6McUkXYzHYPISHgascQdBfrSRHKAwCgHViq7alk2BgTyS/apBdI1AqJAtAJ6ozLgNDI01L//JU4kCz5mCQMjl///QHPChsMHpEAAJlYlbDGViwAJgbgIGGGBCHAiGA+CSYVS/hs9DMmmhW0YPoEwAAcMWhAAgAIAS0W1h2rzLsqtY9vQO6okBj447MJjhQkwYETrctHnQlc02LTtrmv/+8l0BNNRlMLsssi7UliDtoBDPYuMcgIaCMqxSX+twKtgLjTRssF8wD9wP/7kmSqg/alX8mr3aNwAAANIAAAARmZfykPco3AAAA0gAAABMV7AUXjMEwOWZtWZF0c0L+gDfBwmyL9ajo1gaTAxsUUl+TYROp/eptSIFTYMHFeopmIZdBwc8//5KnCYCjI8oMdDQF///QDRwRBhHT1tYy6KsGCwDhgigNmJyBkYMQHZg1BqmHDEMau5+5xQ5RmGUAOYCYEwXC0IBZsal8tkkOWZfPY5ZWb7kt1BAXnAijGDwsoJjBMLTfREzIUDx4BWPwdR2M89b1ugY2SAK+yviI8BItmKw9HWYCEETBBazDIChYAX6lpsi/5EAaxge9FzszlA2FdEEgNpeAmCJkoChSGpM5oNsaYTKAZI+LmM1L9RmMYBgZQKYBbjZN2dEjQAEhe+2eZ0kQQuwWKkSWooj7AcOBQMapf/kq5MAtKRMiRCihn//9QTFgoCBQiSD1qWVPS3IEAqmA6BqYPoNxgVAomC4DGY7KCh6BhhnQRY4YhIFRgSA1JKMDZLLIJgX5dfovwq1pS+zPQuGho624EDAt0IQMNWaiMGgkR/diN0lf/+5JkmI/2/WBJA92jcAAADSAAAAEbIX8kD3aRwAAANIAAAATDDvO4W4cgBkxVBAwRQYBAY6cQlbsIEDJ4wjEYIVVnJjVLlj///3XWHREBRkPt/4UFA2UkAAwNLIFAwqONu5SX+au1iSD1gC3YnIqpM+7GxIgY0aBcKLmprUs4SwGFSl37567k2DWCHTkwt0BywhQFBf/8lTp0KQmTDdAiOpf/+tQSFiYAsTLSIABAALlWAFprAAkBowIgNzCGBcGAHzBKBOMUtGE6cxTDr5eBMMYFIwRQBjAoCRUCEFR4CR4A0kF1vpBsWkM/lVrR1jAADcKswLAazUwQD8xXpExEClLx8Y9V1n3nf1Vbsh2a6iaYukCECqwaIxxrZCBBjiZwQTSrcM/86WgSXAu8IigqRzFYTADYnQY+E/kPF0SiNkx4FhCQsBckM6cWrpIlImQCboDRkiyPxlgMoSL32rPNWRYBysHEyQrKBuBEAF2O3/5KojrBzqdDPBwpf//UGegSCA2cJF+ZzkLYoAQTysFAoJhMFMBAwEwvjAwh/M68448///uSZHsD9s5gScPdo3AAAA0gAAABG21/JA92kcAAADSAAAAEkUjC3CoMGQDkwBQAAcAayqcadJpfzGvKrtm5NwAyMQBUabN2YoBmUAOYKhYbWSAGHUPBKxJ/ZdZ7vX6zqMzSnkCCMxYM0HD+2k/VuDAAmI6jmBwIBAIuNLabHLn//+/o6GREdrQ/1uDJt8CABQoZJcOApZC797u7lcuDQCsE8VmfqWUBCcBGUBRmXjNBB2TGdA04UYj/rRzEnQKIQYlJF2KRGAJGgsJSb/8f0RdgxCpYW2BQGl//9xPIElIN1y1VQAAFLTQy1p/QaCcYFwDhhqAdmCCAsYJITRhsMgnC4P4dp4PZQTIYDACZg0JCIErCMcdaM3o1VnKbGxXlENrsMHh89fIDAYwQAhAMPrhQSmI8C2gwqiv4Yf/8yhlfLEguADFzcMHgJrMSj8OKTNLAYykEVNozTIpL+ouAkaBeSUmyMPk4LEBsAILgxkCYFPJVV2IUTsERgBJMWUYpL9zxFwAiIIt42TdBWs+FHBJN+tarGQgKCkcqOxuRQJmRl//7kmRfD/aaX8mr3KN0AAANIAAAARpBfyYPcpcQAAA0gAAABFf/yVRGdCjpmFeBxs///+UAWOA28urcg1bC2yoBCVANhgHELgOGCqAYYygKB3ZBencgjuYyIJ4OAoTDCAFHzLbwFGHIsU8Pxe3jyjdRPsHAaGQICOYBwEb8mAOA2dq+JlkXl0HfllPYzz/96rtEJQBEWKmaxkTIlqUtkjMxEEjGcUCDu06K2se8////kQ4CB5kxXnMqCtVUaBigBQGkt+K2bW9V5QoVuAeWFvPO3RSMR1AESALOidNvOkiBmQBd/rT2JoChAKTlugR5oA4CFx2//kqiLWFG6KAnsHDjf//6YagDBADQFNUwAAAA7UcthjXwAB0YF4AxhegQkQJBgBgzmFgrsbig7Jx6tOGEIBEDguzBQCjA0BHHUyWM16Zd1/cJVLse2V3KCGBIGG1JRgEAwwBzAIMDCuTDAUClU4Iobm9c//7hP22mkAAiIzSz8BUOF8RAGYsliYPgYmrD1KbIpfjkhrAegN+UkD5EANG0AtgGTJsWgoL0iWHCCQX/+5JkSwf2oV/KQ92jcgAADSAAAAEW0YEsr3KN0AAANIAAAAQDKDCCmyP1HRnATmBqgvoJ9AxAxhEem/W71lgEBwER4rvLJmBAAGaRf/8soD+FFdQbsWJP//6w1gYJBwIlxaHeRuTQeKAMhAH5hTgDGA8AuYEANZgkp8GWOPubJjPJg7gagwAoChdnSx3/pYvN0/cMLGWOTstiGAWb0ZQMAgoBRQCmxbeYmAKl0O01nL///3qCVHX+YkY+Hg0PorTTb6MDMmF8SLsLx1/4tQLeTfWWESkJaBhboDQ0vIkWMmrQL58RgAdJGg/9MuAGhgRLCug/nwBRSv9+UggMBxz7F8JCiwv/+WUBdhQvUJaMh//+sMkL4ggfWhQAAABrbWlswUuQwAwDTA1AiMAYBEwFAFTCnH8Na0Gk0D17DBsBMEgAw4Qa+1CCJfzPGrjcxxyu0DwioUaDhiMNjSrj3EYScmgwfZv87///5yiDJ5uhiq0HAEv5q6qkBI4FA61pbki/+sHVT/MEzAV8DCJwUNk4YEPM+s+Vg/wBxcro/0iiBEaF//uSZESD9YBfzCPbo3IAAA0gAAABFyV/LI16icAAADSAAAAECJ/6iiBQKv/fwmKII1ZxMRkMR//51EZ0LjJqICIEb//8S4Q8Z82mEAAAJFbOAFpugFyZjiZxmCU4OmGHGUmbuITxl7Q7koBYqAwFQAy5jBUADRWhtIfly4hNU+G6krgwlAZMGUQpGaLoBDEBD+CAiHLdS3Yzw+iTQpwzIW5A1P0A4qOcYnC+K1A7K0DajBlSaRSR/mBMBTylziRiMcBipwFkxVUQ0xSqTJwnQx8AZsfQ/WofwhbjVLy/lICg5X+/MAiQBgJdZxQW7Exf/+WURnwYHMFEABwFv//xagoDFJPVFYAABHOuwydljniQCJMGgDgIgKBYQGpmM+L8YZK8RgSAhIBwMDGYtUhyBqXlN2kt65rOw65ACDUiJdlpIjBZj6NgoHuxN4b1/1EeLtAnwNAdBx8tJHSYDHwMpnBEgu3/jrBzxupAzHQBg2AWYL6ZMIPqRJkV0CxwnUv6imBQaDgZo/1hYNH/84H+BwB9NANeZ//51h9hddcfQ0f////7kmROg/UJX0yj3KNQAAANIAAAARNlfzSPbm3AAAA0gAAABKQecUqKAABkP1OuFSqBAoAwwRABwMAcYB4FRgpE7mYsFcYdqo4gATIgGmbujQLIYO/C95Zlev487hNRVf52Zgre4whBDSOgBBVmVY5f////29jLmfECou67r9wEYwrIYyKlyR/2EhB7W5xkiZAFiCzT6ykrzc+JUDdqv9kwyIDCov9QWuf/1G4UD1oDkjbb/+th8h4nWPxX///j7FTFvdUxgAAkY6mXwbC2hKAQVQlHEhg+AcmgYCoZCSJhgIgMBACAsAlFMPqUN/Onv3MO/3CLMtMKABYUAAhlVUwiwXyICWHqW1zv/WWB9F0ioGVAhQaVkVGYygGfHANGmS/9Qd0GEPUtRTAglFLlxBNPrUkQ4Fh5Wb+ssA0GDuf+Gq1v/+L8PC+uMYN///WxKia5QHv//+P5PEQYUAABAfqG2ASskAEDAAjBFADFgBREA6YGBMxnCB+mX2jiYHgCpCAAxhQJnqvnBcWPWsd4Y/lutAbDjp18wEDeBHs55bHk9tL/+5JkbwP0tl/Nox6icAAADSAAAAETsX80j25twAAANIAAAARZe7z////CvNzrZTBEVNek/dRhY4xqQjNrF/9Qa8Ht9ViBAYiAw5ogWTvmhqKaGXl/6ygCGAe4i31BwJh/t2CYQ+rtZMNwXv/9bD+HnzYSb//+L81IepU4AABEd5B7TbZfUiJj5IFCQAtMAaWNFS/PNtEHiWAAAKV5v/SP5UqXMNYc/et9RBMVhwVw5SUxiOYAYDDt0W9f/5iSpeGOAxCoLSi6ktieAzyABQKLEil/4bsKHPUpY/AmoHMM0zS+paJqDiBaf/YaQXEPt9Qg49/tzoXiO1JqnGOHj//WxKiZVkeO5///x8jwQ5lQAAFR3GadGaYQgLPqiyJqeYsqceWjmeow+YlASYEgI7O6WPbrd3Zypf/96kqbhKOKl0AlQATBcu0EsBVct//1mBKJkwBhzAXYfZRmKQAxq4GBSX/+mGThQr6mc8GlhQAfTOK8+bC1Cnof6kQTCiSpfw+V//zobkd9qo6x5f/+tiVFTyNMv//5RGwRFjQAAEhrOIRO//uSZJOD9JZfzaNdonAAAA0gAAABEYl/OIx2icAAADSAAAAEUEqy+puUz8u4YwpGfxjsfoKoYigKjq0ZpMkghyJBK5fhYl+u/rOUEIAmJI2DoBsiQlGNxADQHNrax7z/0jInR0gJfiPTiM4N0DB0RNxdNkX/0QkBBgpupZgOsJqR0mjH3bWgozChI+39RmEA0cav1Bf5v/1h1RJ/YRVH//Ww/iZY+Rsf//4ko2nOAAAMP33EV3LBkAIOARCAqAgAYQgOGBCWeY/IlhpOgSGBwAYYA4AaIi63ihNeVWpTDsti+PeZ4w+rYdYqggQZCzk6kYIgx86K/zv///+qF8a0WKDQoF5DlvB3wcohhTTY5f9IIZCuN1ThBwChBklRApnfPF0UKGIEVf2MwviDjZ/nQvy3/6YjENP60RQo22//rYXYgbMBMf//5DBMBcgUAACMY5MtYlDIXAPMBYAowgAHzAhASMCUEowkD4zREFANsov8DDhGAIAQYRAS0XKTiSQR/Zw+L7Usnvf3CCNP2cxDhg0HrVBIFNaS8DEuVS+xnhn////7kGTDA/SKX82jHaJwAAANIAAAARPVfTSPbk3AAAA0gAAABP50kxFltAE+J0SvWETRkMHp4HBt+p3Jv86CZ8KRG6lFEfQBk4LKjFy6i+o3TGcAUekI7fomwCxYFjSL/LAQCkP6/MyGAsabOnRNggZv/501ERC49YuhDVf//WIoINGPcABirTQS9T4kFxAsaWJknHLMYdgepv9A9G1uqQYTwGRgHgFkQHT5wc0yG62FHY1dwyxyiUDJkmKcDYJAapNDACAIG2CwBzW49Vub16lj6EuIKIKgbmiCJ6OI1ScUiBzfIGVDCPSLF1JH+dCFWClR+ZIF8cwDJtgLPCDl8dBg+iWyDBbYDHgSLIpfUdLAQuBWDNX1gPJmv3rT6gKAAWJI7OEhRNI//zpqHlCgOsP4QFX//2DJjUQmPxAAAChnpracjKxgAkwGQFjCTArDgGRCB2YaSMBuBEDm5w8uYPYG5gcARNSBoAHAKKgFJBZzkxJv3dlVPzKrNMJBIWOPuswuJgcBTAQdN95MIIKOTuxqly///91IDY3RKHmMj2Ch3P/7kmTpg/WoX0uj3KNwAAANIAAAARb9fy0M+onAAAA0gAAABAna7gCoBMpIcSPNzPX/OhFuCKy2spGpNB7IGNwgMMSeRIEZM6BmThqImBpwA40H/THIAJQAWWEkaJ+WAACH7b6zIIDAOFLUsoF4EwQeB//508GPhQkpYd4Oe///zcMeD7hiV3AAAy+FPbIjAAAOBwNZhjgDGBUAiCAczAhW2MWsd81m48DC4BMMDUAdrasb7uRKaeX0mcTm6mt1pnILBc0BKDBQ5LJDoCOuEoSRyrXmkNq93f//5RlurvKVGIFMCg8/tqxTKoGFG0AQStaHaZFJvyiCb0FrHWYLJgY8DJXQGm5BC4QMzbSKpBQ1oGoBEibI/ZIugEjQdBNz3qOgYsOQj/31qCZ4dyallgyFnhdZ2//LJ4JAQoTsOUFA7///MRKgcLC65bYwAAAArXYCYa0oqgOmAeBGYSIJBgXAOmDED+YjqNxx7kLme5ZeVAZwACYAA6wmnbCnzdaxD0vpZ6U3tXaBqpAMDMlPMBDp3h0KHW78YoASFdmL2M8MP/f/+5Jk8gP2SF/Ko9yjcAAADSAAAAEYgYErD3KNwAAANIAAAASrrYEppSv0yuHh4+tXnaj/pqGew6ZJByuY1SpI/qMQlJB2VS1qOKLoZCA0FIBiMPJwZ0opM6BEyJAkCA0A8cCavUsyI0CM8GxJeX83AUYFdv5/nATTBghPSRCEeMyl//LJaCEKDjzIDXBYU///2LwKEg2A0EQAABH7bA0tVQYALEAB5gUAWIhmBEAMYZ43ZtniDGKC9oYCgKCl5e5DFVR32vww/85LJRnOc3hXgAVB5staGBwCiQFguZAubA06IRc3rf///y31+VsiBBq3yrGnliH5hpLiw0itrj/8JKQch9SBmKYADSAsMIuXyYQfWkVhPQDDskkX/QKYFEYLC0E/WiBIcVH/v1BCKCgR8zNQ3Iqf/+dPB1QoDZQp47l///j7DTxSaCpgAAYU8sa+ioNAjmCUAKYegCAKBSEYQBhPuNmtiRkZpuj4oDaYCoCuYEAxz7zSZqpKZ2hvXL+FPJVdmAQQG9xbmFgIgoGgSJBoNMhiKAhgMAbJ4zTY6/v6//uSZOqD9lZfykPco3AAAA0gAAABFi1/Lo9yjcAAADSAAAAE3caKSAC15IYxsFAIIJmsivVU0jGw5jBoG0Bzuy4upI/rCdkHSS3UiZFUnhAUDXwwLhRP5TFDEci7JjsGZCEOBlygzaC1e54rAiEA7ESx9D0AMoLFzn/1JcwAiGBiYtsosmIfACw4qv/+WS0EhYUVJqC8QvYv//5gEwIXuC6RVEAAABGObsuM/qwZgLACGE4A+YFoDRgWg7GEolCaSRCBoFQeGDyEABAIR0HCoBV0w9rzew3LpZH5fSd7ypxEY6yCTB4sDgSDgScXW48eUNrcus959Mhg1CSDBgGd/AMGCfmBAwugB0bgB3InVL/6IQQQcdfWcWUBIwDM4N3kcXCfTbUiTIxoDVQkUm+pEfQCzACw4upfJQDBiCqf/UrmIguDkB9nRTBoIJJH/+dNQ1oUDY6Q0hv//qDdkGEenvppmSNhEYFQAAeMCAEUwDQEjBDAaMSAXE5AAfjXHh9MEYD0wAQAGPMybu+8Cyp3LOqCls2scnwdYCAU6oqjAwxTXP/7kmTrA/a2X8mr3aN0AAANIAAAARepfyyPco1AAAA0gAAABAwPOfO8yqDQgMOfRX+Z///+MSZ87rDTFqTBwtfqdp4gSgUGuEwIClIxayki/6ARlgsZS6p4kgM4AB1oYBgN0oquxJjuDOgHCS8tX1HR8APfAiCGaCfUTYAhMlzb3qbUUQhHgoZSZygbg1CB9E//5ZKoTAhQfcdAUAnv//wx0PAHOYwAGP1QtYeMLATJjDvnwcAMWjMJwzI1lBIzXWWCKBOigA1S1iTsrta9CaJ3X2swJn+WNNGRUAowswxwIAQrWWAFDCDFeMAAARY8or4Z4etQ+xWThLgahWCJmSB9ZcHGBznQGcBjnE6ki/84ELMMKNqoHRfAgrCbDNMtM+tSRPhScPTP+54G5QOSFtn9AGowy/250Go8PCrOKFBh4X//nTwd0NOdYlgyLf//i7DQBBA9FAAACHeNeZJIhEAsEAZgYS4wHgETAYBrMA1I4wKxtTZxPfMF4BEIA6HgK80NyuZgyes17VTHWNaZaMMBcwk5IwxUABMyndwMSVkQzWz/+5Jk4AP2Gl/Kg9yjcAAADSAAAAEV9X8vDXqJwAAANIAAAAR1////29Mw8sEDEIsqZtUkNjgAMUooaKV+93/uCbUUQiHc8bkiBkwgLPCJmY+Di9y0REMlAQCIil+tIjQKmwRDTZvUdBCNX/tzEISZF1aRgEwY7Vf/zpqG7C67LFOIP///LoaSMvUYAAFq61prrhBYEUwHQGzCdA+MC4DEwSgYzEjSqONUac6ADJjDPAsMCIA4wAwIxYBFSpdLwMGkr8ySGqWds3KGOPuFBobcrZhQUhgWMGhw7ZVjOYALMuNFZdZ7//+rrZEXn9U1Mvh0iPLQpDfmEGTI7hMBg5K1+pbaxy////myEupww3//lSx5O0wGjQUGa1iHqaz+7kvTDLgCnUVE+3qWcGqDSiIBnFq6zgGCNG32z2ozCKUFBaloFM8CQsPuh//LJaCEaChOiJ6Bw9L//8XgKFQtUnMVGAAAJGtt0T3gBDsIjTMgTJIsDCfEDNS8Fg1awZDCUAICAK0jIsuiIQ3U5ykwpMPzwp30LrmFmDkBQDmCJyGGCCIR//uSZOWD9Zlfy6Pco3AAAA0gAAABGq2DKQ9ykcAAADSAAAAEAuKfor/O8+gXymVRdgYK2G3lymgIzA1xUBpiQ5FX/OhJGyHrQIGBhCYLDyIIFM758ng/IGz5WR/oJgQEg4GaP9YWFnv9usMOGl86sZQVbf/1ng6oePKYmT///WLwaIpUwAAOZw4u9+AKB2CgZTDQAOMCUAAwAQZjCXYVNdcng56EizDJAIMBIC9CILAFClryxn+dp/qaal3e4W4o440AD2xdMBA1IUwOIzhHfMfgN4n/pKfDPf/+6zwqoteROMkI4MLTqyKWL7IAQF4AAiGpzAtpF2/OgnbEA2rUs4URPQGG/ANKlGxATFJajMnC0F6wNmCGGef6SJPAYAwDoxIu3pAFKBvt+tfTD9Qc+NNEmwSJDNI//yyToSEhQvQD/hoS///rCQIcIUBFtpEwAAAAxtSFtnlC5oZYDHtFJoJMZfKGF8xuasBVBx7tkGFUCAGAdEQGimzQXlSvtOw/FWellbO1ZnnVMAEAQxtQhS56Dw6A8YIRJAFAibnAUzW3rv/7kmTgA/UOX0yjPqJwAAANIAAAARlhgSkPco3IAAA0gAAABLUZjOB5CuHoAcf4AVYGmaS+IAgfX+BpywYxIMXUkUvymE64cGf6ZoTYjgDM3AGJAuci4xhQTrSJEcIIA4GoDDRNkX61HRuAgnBq4xUvygFE5Iv+tPW4XwCj81rKBuBUYHYT//lkkQiJBxJ0w3JDF///WEwAeMLqHjs612abChPAADhgVAcmAOBEYHIDxhyDjm+IDkbFjdYCHOMB4BYwaBwwCMJb+aiM7qtTazrTlaUukFAecEaBIFFegwIm6aOY8AbEoZl1nL////lNAT8pkmDUqXFjVmnhhEMyEiRIq0Xef86EnoeI/3NTIY0DGyQLLSsshxkjWgT5bDUAMwBIgn/TIwBKYFDBug/uAUNJf+t9ZwJDAUHI1lg4MmGUdv/zpVCAGDgVYoUOw3//4lgXeHJpLTAAQADeobZQ6YMAaMBcA4wZQKVBDATAzMLg0w20BHTRRgSMDYDYDAaBATVGyxlDd4ak0/GJugpbMWqx54RGFDP8BHQqroeAxyoAEy3/+5Jk6If2Xl9KQ36icgAADSAAAAEXIX8sD3KNwAAANIAAAASTYoJ2/zu//93HxUdlT5iSBJic+VHYmyUAGHlkVAGwaK2kUm/OhF+Dg6XrMBXwMJZAYNkULhFzNtZsTwdEAdLIki/2c1C0cHLS2z+gBgwht/vzIIDAc5tIwBqJGRS//nSqEwYZW5UC8m//+gXgoDFbPq887NG3EQAJQD2JERGCYBCYFwXZgNvRGIEaqaMGSZg4hWg4EB3VMEN1dtcoe0V23RZYuzEILW0QDszLnAQHmBGAAod38hnQICwCdWX2LeGHf/lt/Ig04hAhgt4GDgJBdaw/6KARGjKYUUtjVKkj/MQQawRR61uYqJ0UEBqpgDWYhCgLSRqS1JjsHkIRIGfJEHQX6SJkM6ATXAkhJ5H1GYGKOkTb3z71kYELwdCeUycBIqHPQ//nSRCREHE0kw3ALAUP//xQ4ORA2JUqMABgAMsZU6MNIqmAmAaYMoERgNAImBUCGYVJoBrNhymJS/MYJQBg6ASPAlJFVZjT3vzAUNyaLR2pS5T1I9YgBBrR//uSZOUL9eVfy0Pco3AAAA0gAAABGVF/Jg9yjcAAADSAAAAEiv0xEZCJizDmDQW+FDW3rf//63BTGodXKYxI4kOYGoqeGEyzBihGhhAtrF/9QTYg42/OoGYtABNILTCfNy4g+pE1HNBSATqTfWojwQLQuWXE/WcBCIMP9+cCEcGgJ51EcAi7f/1loM7DxVisEX///UKeIcIGQBWxmILfBMcwAAGTAKA8MAABEwMgDzDrEfN+8EcypYrzAsA3FQEBoUsghLoQdcq52+4Vu53p9uABBZzc8BcIo9AUJGrL8YtBS6X+ltNj///7wgNqtEsGYwPIcM4ct6xXMZGQRg4Erqh2mRSb+ELkKL36Z42IKBlwoUeEmZj8WF7FciQTBALAyaWr7sfBuEFmZUdvOgmRO/ep+wIQwOKO1EvgkGHcv/+dKgTChveKcH3f//6g75Bg5QlnQAAGF/Br7iCoDZgVAEmGcAsBgYiUHIwiV+zYjK+NOSmYwQwqBUFkwiABQGpMtwed1aWxKo1PY2uWp17i2p8oEGEBkmiYMCp4NVg5eojMdv/7kmTgA/W4X0vD3KNwAAANIAAAARdBgSyvco3AAAA0gAAABC07f5r//mUMsJZchOMUL4HDJ3ZFLHLLcGb0gClNLdb/6wQE0HEK9azElBFQII8O+TBoSZ9nUdOF4UsDkONo87daRiQIAAcAiHRdS9ZYAEDSX2qVzEQmBYYH2TKBPgmEBBj//zpLAkDQzTsRYKBc+3//qCAAjBDZzV92rMuogqAcEAeGEQASYDYAxgMgqGCsh2Zngpxpis4mEMADBo0EEM1N10Ri9Q143Ty/v5Y00MpfHGUKYJB8OpVm6mWEINyIfsW8M///1uCFOqsIMbhYeHj32KeOKzgFToCGSy6yk3+EkoLK1dc0JMCx0KLyIGA+zqty0REMGg0AFlX6lkYE1wggZq9SwAQJa//RD8wcRfOJDJiGv//WWghAiL41w5z///UJWG8COjQwAAAApa0Es+YyWACwQBIYIwJZgOgSGC6CsYkxQpxOC7G/Y2QYaYBBgLAGgoXNIVqj77S6HpdlqrS6q3Jl0goJzfUQDBonmFg4aD8hhwCJJu1dqbw///v/+5Jk5o/2PmBKK9yrdAAADSAAAAEVyX8uD3KN0AAANIAAAATJ+26qHoWW6M8eq34cauZsEhjAFsmlNMil/YIHYOvpaiyYFkS4AzwGKiifKqLsswL50ZgFMpIH2/THQASYCjQroP5NgY4ASf9TajEEJcHDTbSLgJjRRTb/+dIgExIcGmoO6NJf//0zEHCQ21dXTpq2MDEQKhgPgOGE6CWLAMGA+CuYlybR1HEDnYGxyYZQD4NAyMCwdEgGchvlqPvF5i9K7VJjcoY4xsKBsYos6YDhEWlMAg/MwaBEAOhcDEi3+pct/z9buM9JABcpOoxeFwMI5isLhxyxQDjEtCggj2xTtpn/koBSSCp7sUzQnxBQDYwALiBcZAxQhGJ3YhRkgQjgMmRIEYpL6SKRFQMGjBSqSR5+5DQFGZg/881IshFmFvJstRTKgFDIo6v/50iANCoUFOcDHQvYj//9YpAKIQRCiu0QAAAE5bi7TIuFgFw4D4eEnAQGoMBRMApHwxShoTb4IaMH0DMwIgEnwXoyuG4ct34YktPds9zqSt4B0PN5//uSZOqP9hdfysPco3AAAA0gAAABGqGBJg92jcAAADSAAAAE1BwfbEYCGH7ZACXletepbXO///+coeieeAxtuDBiN1N0Cj5l8KAQJdNNZSR/mQQHQdD9aJkMaATTAkJLyJNJNrNEBSYDTort+tRKhNaLhOL+mBISX/9udCRctqqOmJCCB2//rLQXiJrlkPA3//1iWBvAnRxQAAER3jtNdiQwAIYA4ApgogMGAgAaYEAHpg5lYGf+HOasofgGD9AwEQYCtAbZMJTVg0EcwpqS1394U5fQ6x1Agc+7UDu14iNWhya/zvP///c1BUZZSYajiQLLr1uUNLMyJRIxpsdf+EEQqr1rQIuBi+CjycMCmd6jxVE8gKAKqX9RmBR4XeaP9ALDkP9uwQFE/trTDcDu//1ngyUYdZQExb//8VgmRm0lQAAEulLdF9qOCMGUCAamAEDkYAQEZguADmMmIWP2lHh4yqYh4GQXAFMA4AlMRrr8Qy1+ih5drnSzve2Je6gkC5yaRxiGD5WCxCD5qRVJimC6NjhxCV1M88P1nMMLKoA0if/7kmTdg/WGX8uj26NwAAANIAAAARUZfzKPbm3AAAA0gAAABBZjgPYcTa/H7fxpY4DRgErxhWBqOT8y6zlz////pCIJEY1je8o7WlLKjCYkgcK0VuOjKbXM6j9kkCAMBwiI0DdvZzUcoDGDAd2Hk+yuUwMglJ1vetFVQ5wEDIKVzSsoE+EJ4OMT//nR2gmjCgZR0EgQb6l//9YTECygvUbiAAAEDm30Xe7AyAQYCQA5g9AIDwERVBGMIk9M0exsDYfTaMIAC4iBSJQEXDTMZpH45Py2mnd7/nbM8tU5MMgEQSyQjChjzAGCQI3GJVa2////+2Zl+lFgAhl9TOXLb2mSR2Ahs4suxSR/rBqVClNuZoGZAAMHAAsQIOXyGGD6z5PCEQCi8iSL/UiPoElAbEir6gIiip/X5kPIOLHs447hFn//rLQTCjCxKhpv//+KwHbEEXUwAEAAxykLrQ6CQDTAoAAMKQBEwHwFDApBeMGJOMzChujYKclMH8B1NBnit6schoJm3P27/beOWNM/oXAxxtdmCxApaYAAZwOZhBZGgE//+5Jk74P261/JK92kdAAADSAAAAEWZX8uj3KNwAAANIAAAATMus5f//+rr4KzSlzDI4RKxE2ecl7sI3mPEuPFi93n/WBQqDtx7YzRNhcoGRago1Jc6PoybTJwqhrQAlRfQ/UmPgCrICwQvoL6joTKv9636QJAgoWKr0jAEIMUVL/+sqBESJljPBeb///UNYKAw85tjWfVmTokAEQEAeMFoEMwIQIjBRBCMRAtc4mBcjTjkUMFAFowBQATC4GUCLTJesNZa5LsxmxyXZbrTLdhEJTVEeEQ7cJPI68JxpViwAhUhv3s9//9wht64FW2YWVYOBcMV6klR2MWMICAlXUO0yKTfqCAmC49HnTpQE9gYDiAwPIoXCLptWoukVE2gKZB2mzP7OOQDbIFohbZ/SAWJFtvbfWkCRgHDiq7GZcBoLFjV//WSARFh48Y8GA3///Fng4cGFDyNAAAAOYRNuDS4CAIBxgkgSl2DAHARMLwoA2WhaTKmeRMCMFUiAYMFgthj9rrjGrHbedTf63cgsqg4xE3REElChwAGxZMBiIueKW8//uSZOYL9e9fy0Pco3AAAA0gAAABGFl/Kg9yjcAAADSAAAAEM8P///UdaLDzKjERUDhVAtHYjbEDJYWBRSfmtir/WEw4LWvMXNRzgMgQBZcSBgP53oFcrBwgCAJcX+tIxAXPgoNNm+UQCQpr/v1BIoPSOdRGZEXb/+sqBIGMJ4rIoz///inhvYfuxgF+9A7aOuNAEBwQQcN2YFABYABlMCpmgzBB1zAjugMAQCYwFwEC96u3cW/LaXKg7N0Oet1I+3AZB80TSgODMaAkABeYNSaYLBaXEgOau3M+//6rvArJPp6GIpCBgwOPGIbaQQgWYGIWAhEYLFrOXO////3SqBpMU3N71JakfUaC5IF3InTxSxf/V24VhZwDIcW41dvWcH2BCaGWzBND3AyQg2b+f5gDVYIAJ5iZgkMD7Iv/+skQgJipVBg0XAn//9AJhRSwfseqFYAABGVlnSPKEp7DAXARMKMC4wMgJTBIBvMNNLg2VSETM/ndMDwGUwEwKBQDoEEK2BuBAL9RWUyC3a/CvKIbCgKOzK0wwExYBGCwwbwzBv/7kmTkh/WLX8vD3KNwAAANIAAAARj9fykPdpHAAAA0gAAABEMGLFcqM02P///3GNPE4qDJhVVgIGv9S2qJZxmJBGJASrqHaZFJv1hakFTbbFNj47ARPwpYHeTY1CwvclhmQgAgmGLql/oF8AQmCzsqJt6IDSMln/vzgJlgWCLZMwNwhFCwL//rJEJjRM6hehmG///CQEZgMSlowAAMtyRscEDACoyAiKAVIYiwHphmgXm3WCYZxDlhgcgVOsW2Rjawxyvlleq0uNXneW38TnOVggwOGlimAgGb9I5EcVEYrPWe89ah/EtMh3AbQCDnw8FcnBywbyAbncCKUaof+mOkGNfOrLAuwI1Q1aYIFZJtSZiRQFoI8u36JNALEAULGr/TAsJP//sGjBQgnWcSIMIFf/+sqhEGN/IoHmb//6hIRFhJqjAAAADDN2FM1bDADAQMD4B0w1AOBYDcwFgZDDzZRODcgg47awTDkA9BoCYhDAYDy7CnEnuw5LrdyRbws2pCu4wMFT8TIMHDuPmDQmeSzpl8HsMb+QW7Gef//LcOQw3/+5Jk5oP2Ll/Ko9yjcAAADSAAAAEVEX0vD3KNQAAANIAAAASxCCAC7gEAHTjkfggkBJjmQjoMRxfqWmyKX41xNgPtIbkabk4MmBtkoFxYsBABQ5Hquw9jJA1IAYMuOcYpL61HRfA0vBqo6pfsBmQw4P6lbsKXBSSW2mRgA8mG8pN/+seQTOiNjdwwYFyUP//xaQUOBYoLEAAABH9kL3ToyJCEh/g5nRhpahgjHsmOIMQanSLRgvgXEwFK9l5w0+7z16S9R3c88csa1KIwBDCpClUMW8MgDGCOKIgIZ3MXdb/6yOFOIqLlA0bcFko7jxuTguMBrwAc1IMXUkf8xFmA6n51RiM8A6MGMjrl1F9aDEXBEyJdn/TMAKkgUAG6H1gEAU2/tzELVg4Kf00A0Uif/+sqBeJLpRTjP//+gHAi53pAAAWcoi8Tog0FAwGgJjCGBXMCcDYwVwajFCQROxIXg6m2NTDuAdGgAQERhgKAwKAptWlS2xOQVMzsqyqzTwplBYNTGplDAUDC6JgYHpnXMJiQEIOAprMNUuW/5/51HTVn//uSZO4D9ohfScPco3IAAA0gAAABFTF/MI16icAAADSAAAAEkyq5icXJh2ArXH/hhpYgAwwxRYFEezadtIv/MgKCgZpXyPQIuIKAamsAp0FLkDFcIxPSIQXCCASBoCw+y8i/djYiAGLHhTSS55/SAwaAkE/ao81IuhAtChAyWolTENUg4Mef/9Y8BIyMk6IdYEQc2//+4YMChQLdJmAb1E24N3FACTAFAWMDkC0hAIBwIZhgEZGzYF2bhA0AKFzMBgA4wcDZIy9rcxC6ampsrmO9XZh6RkeN03QYHqxFpj9qo0UEaDFrNrn///+UpeF+k9jFnIFB0ZpsaZ3TNXMwcCZbLrKSP84EwAUxvzqzIZ0DCxQJETZEmjJq0Dc3EgAUak4/61FkEKsMKpL+UQaDTX/bwmTIihrMwtQNpH//KgRAlbNg05///rDyDREovSAAQADK9A7aNnMAAEQaCKDCBzA6APMCYJMwQnTjSAKzO40uYDEimDOA0AAHB6mq9pmTxm9OSmgsYV5RDaHhgMRnnZcYTFj/mBAIevgxnIHKxvZI5//7kmTvh/bPX8mr3aNwAAANIAAAARYZfy8Pbo3AAAA0gAAABC3hhv96rs8LAAoVhDNY+Jkw0OBH/ZwWzNCJsMXMPVdL/3BM4C8p9ZRL5MBkMDSeQGK4zBFBjymhUiRIcQFQwGxFkONUm9ZgKHAhVAaVk4mgrWcAMRFz7Z5qiyEWoYXQzAi4NSwjRP//IQIDZXZAOuDhRv//+EQgy4OHjfYQAABEdxh53ZcKAPmAmACYP4ChgOAImBECWYP57hpTi4mygbaYKID4cBoRDsFARKtaqgbhL8id+WRqrzDOxF1KDkBJLWs4HQqaGrJiEBuBK6meGf///y/k/KdpKhVgY9dqR9DoYCVBbtp0ttIv/WDQUFLb86kYjlAYZgCI8WlENMUtMnCdDJQDjxPof2L4bCDk55/mIBIc1/25mDQWDhbZxxZwhj//5aCIU/UJWTR///8UMIHEaOoUAAAEa23ZbcGJuCNECzAgkHimF+DcbEYCBq0ouBwkAcA2go0N0H0i9n7XKusrPeWodSCMP8CFp7SgSAgYHQoRgDgAPjKquW/+olT/+5Jk6QP2gGBJw9yjcAAADSAAAAEWzX8uj3KNwAAANIAAAARTSaGaA1RgFlRInzQrigAOKbAGXDml5FL/hAIB0Z+dUZjOAGvgswX0y4g+o1IqKFAYWFVJv1lIChgEQJH9IGwYbf/rD2QcLbUoNTEl//5aCIE5jOi2P//+RwceKTSIABDCVuQoGoAYBoKpgpASmIgCUEAvmAoEgYtr3J3altHUtvOYRYIZgaAQmDgJBUA0HEFGpssyeyLxHOJ1KWNP6sYwYDs40YQwYEItyYOB6cHxeZZBSBgGVy/Uttc1vW8KdpCdjfEAFGJqHGGQFLvdhw1KAKC5jIqYYcDyyK87P+PgEpgP9Ju7EeiTwZdA5dcA8SKOQ8SIfSKky4LeMIGhYDZIRzDNS+tRZEsAX9AMDCbME09yYA1IcnX/WtS0SaC1wFPxq6BfJwGqMXOgv/+LaDRei6Q5oUWI///QHWCzYCICQAAG/nZFIRUAgSA8MK4AEwKQEDAbBqMDBRkx5iIDRbgMMIwFwwDgD2LIB1ofFocjGFeft1Mcqs0z0RiI07BQ//uSZOSD9UJfzCM+onAAAA0gAAABHDF9Iw92jcAAADSAAAAEuE3PBwGOUEkMU6hMH0V/nf///GJNGd1NExWeQwMw9S1pSvIxcoDAAHYNDtMil/KQNDgUzvrOplARMAzGHTkwaF9NqlpE8HtASnjaNX/TLgCRAKKCuz+ZBQiW/636QQCAoSZ5mwhKHbb//JYIRKWNQNN///iMwuMGqTQUADHTwtKiLTjEIP6MxyDfsMKYlE1bgcDJAbHMCMBMBAOIVohK/ZdLozPzWWHe5buTccGQETAJDKEQADhI2GFCIQEAsROWZ4Z69aiPF2gOeBploIk47DcuEXFkAb1MApCIikv/qCRQFnz8xdisAUYBxskDAlTqtMqFUO+Fkxmr+kagPGg4abN8wAkCNH/v1A0GCL9aYYsFub//LQQAT1YrBFf//4iotwqTVUAABu5AbcF9ggQZVMcuaIxRvwJijFqHPQA4YclwhgmgiGBUAKYEYACWLz2Y5RWpy5Gb8Rs4U8MLBmAEBIYgglqISeIgA5BJH4FAdL/OzKqut+zk6OkUsBUBAf/7kmTeh/XIX8sr3KN0AAANIAAAARUlfzCM+onAAAA0gAAABIGaQAQCGdI4jxnAagMB0FAGHAgCRI1SRf+DUaA5BdRZMiVESCKODiCbNyQY+yzh0ujBBREDyfZ+pZwpghKYp5gtXlIDCARJdv596zIGgqFxJqWgVwmFC4v//IiEQiTk6HkDe0v//qCQDHQFmB5cgDvHbToccYAGBQJQCGLMCwAkGAymC4tMaAhR5mFzfmCEDiMATEINGgglKzeGIVMZam56Y52xL4oWrOrqwKiUu0YJChvjGGPwYDgC/Utpse///q6+Cf0MslMpgkeKrUpNPzipjMRuMSA1XUO0yKTfpggYAta8zY3HYBmxQUqDvJsahYXsS44gTAAmLJpFX3QIGAQnBEvKiaHWRgGFJIfbfWYA1OBoCallA+HRB2D//+SISGkhjcBYG///1B1Q2kPTPCAAAAC1uLO7LgQAmYEYAZhKgOGA8AyYDwLZhNo/GnSLaaJUDRgggYBQAAHCMHABpK1YPp3ZpoYnOV+49sxcIAB1wEmEhAssAAM5eHyJIpn/+5Jk7Af2PmBKK16qdAAADSAAAAEYJX8rD3KN0AAANIAAAATSaevd5///4SuC4FUfMHI8OCcQlcofcRAIx6khotX+d/7hAuBak3WmUhQoC+MMSmTE8k1SzA4K+Dqw9s/3RPgIDA5cWn+mBQin96n5gCYYHFDfOGAWXiSpf/5aCIMhHUQ8NKf//6hdg4AIyRwlM1BqyhkAIqgdmBaDcYDgGZg2AVmMiNwd04cpyG0emHMC+YLYBg8XAwRLajSgzAmJxGK2KeWbypY0zkAhY/WxzFI5L8AUOnhNqZjAaCj/yynsZ5//7rN1SdYkW6MtKAINTTY1KYKKgFMhxsRhRCl3pabIpN8wAjiBGCJbcxNycDL4GskgNgxcBFBPZHoWSIQXCBQSBkiBMmSKutRiRwELwDBIxV6yUAgoKy/apXJgLpAtIfMyABI2Oer/+odgQmRwOoNHDjk///uWgYSC2JrVMAAQAObjDpwwOgPmAYACYNQCg0A+AAQDB3NfNYkV41xExjA3AWGgOzAgCTHZw+j6zVaX0m872WOVWJEAHNkL4eCK//uQZOaH9dRfy0Pco3QAAA0gAAABGfV/Jg9yjcAAADSAAAAE/h0LGPb0YIAC0Zi7rev//1nEGqX2sGKycJByL0lPGGHmSgKBibD1Lkj/nAmsBRGvnUjEZ4ACQA0SMUiZMX0DdMWgBhySD/0yGARRAiAG6HqRAXDo//qE3gsVfOoCkRM2//qKgSBkJUKaOxf//4vAuSIONyAAA/sIdeTBUBYiA8EhJQMB0YA4LAAR/MO4Yo2fzawMI4UAFgoEI6xJ/JXrCUU9jLP9boGykIaMkuUwaEFVQQETSNVMEANGqM02OX////KaPPyoqYJPZdGJVZiJpuGB1AHCt+rOTf6ghWAoafnVGZAAMa2AkkIOXyGGD6JWJ4NSAGLlZH+54OcDkh9vlIGyFf7dEGoUGBEs6ZhkASZv/6ioEIUkcfIbQ3//1iKCqEGOIAAAAMcmUpVMBEIDpgNAUGEoCqYF4FRgzg1GJUjycbg5x04EHGJKBMAgmSgxwkDAtK9WF0ofilqX50Hc6k23AVEZp2pAUerDCoUO9N4DLYoDDNorPXu71+t3//uSZN+D9ahfy8Pco3AAAA0gAAABFf1/Lw9yjdAAADSAAAAEGxoFxJvjLAFGju2aT0U8jaZnUZiMHKaw9SmyKX6wjUBh09smsmgyCBm84DU0rHRjiki6BmRAqhbcDWgBbzR/dEyHSAmCBJKXkfmIGVCkt/ntJEE1IFgqmdAmwiUHMX//UOwIkRRXTKgOGnn//9YQAh1hkcrMYBvUFtwdMYAwAIBxgVgZigAwsB+Yeg8xvuBpm8iQsYOwABgAgLAAAOTSzkUwu18r9Stf/OkfcQA438wQAHgqA0KDj7QFjIjXCJ+xnh///M5ZUgZO4CpZDCG5iVvokeZEOpEYabev/CB4FCzdkygM+BhqoDBcghcIGZtqNSIhqIGgAERSb61FMEmIdOXE/wLFE2/t0gmdIOrKCYckIEf/+oqBMSN51ihA91X//4eQVMWo/SAAAADuDX06GdhYCMwLwCjDbATFgUQaDyYSzKBqNE/nNgqWYe4JZYAAAoJkwKIfrreyZncoMudmddwjdKWXNtSIMLwZKANC4QmWUSmE4Dosu3MV8M+8///7kmTsB/Z3YEpD3KN0AAANIAAAARY5fy0Pco3AAAA0gAAABNVXiSed1L0xTGcOGFp0ZmpSQAQYOH8AQNU2fmmNUm/MwSuBQ+2kYmxdFlAZ58CLEQhgM6UUroEmRILUAZ4aXE1fdAi4ABcCUsqJodzQBpcQj/z2pgSSgsHVmRgBEGGgmzf/qJYICYqDnQz4XGbf//WGpA4eDdqRgHeS6HY0FghlQJ8yhlCZoHZg3nNGaCKCalqSQGDgFgEgUAwrYwSXWIhGIxu9vPnO2brQDECASCAGVYgSAsYJwoRgAgCQ/D1Llv/oE2N08LWBmqYFi5OF8uE8KAA3oMAZkQ0yRS/zoQrhF/WozHQA+EF1BfTLiD60jYZYCTMiTP+iZALDgUHIv9wbOn/9ukGchebaZgF4pq//qLQZ+S1Y1hM3///MwyomrkAABNTMebq0YRgoiEDcwWQdDAwA3MHYFUxvSqj19GFOQK/0wowiTAsBABgFl1mDJEpWu/DtNEZdLotZtUr7I2mAYTHAKTmG4oGAgBmDAUm7bYmNgBgYAnBfqW2uf///+5Jk6of2bV/KQ92jdAAADSAAAAEVKX8xDXqJwAAANIAAAATjk4KiqmwVAwxCPAwnAZdsBPWwgVBsxCT0FE4lzCrLs/5iDT4CwI12TlYWEDfmQLjRbyHiXD8i7G40BiBCRAyZYZcwWrrUWRKgn2C6BZOJu1ZKAZNIeT9q1qsQ8MWg6+VE0CPLgDgIOHnn//ODYCR0LrG6BPg5Ufb//2DRwRIgcILTiMAazfRYdGxI4wDAETByAsDgEzAAA2MNE6E2kxtjR/gYMFYEYwHQEwUGDBIDUAqqB24vMXLXy/DHLF0hEGzWTuAAnyLTnHjiNH9UD3UV/nf//1dghRq66hkETExAhdFfpWRGSEkYKAaupbTIpf1BKELf1qMywImEGsOTKBoV3atRieFygpYJZ2/TIYAaYBZQboP1HQFhr/etfTDIAMIns6ZhgQQ5v/6i0ExIqDqETDen//+oRUPuGX2qQAAGPb0jkxdseBYBwqJgPgDGAqCsYFChZgbjIGRtGqVAIzAJAOQuZ45LMm3i1Ld3MS7lnKrEn9LASAkLMABRTcdB//uSZO4H9wFgSSvdo3AAAA0gAAABFyV/LI9yjcAAADSAAAAEBr26GCAAsekp8M8P///l/r8qKlVOoJ5JNyiG0qDKZQDjFS5b/6QRgGD7sfPFsA5yDE5EDAfZZVsSZEgiABIGUlq/SLoAosKKTZvlAGpQ0+2/MgSGAsGR0CbCAYTS//6ioEg4mNQiZDl///UGvKQphaMA5WjLlPqn4YBQCBg7AYmBCBIYHYKRhjHUm0IM0YlEYgFBoMBoBcABBH9SlrLKm1m5uXT9u5+9NjaMOh01q8isGjQBAAfMS8EwUEX6gWaq63//+9QStl/lzGOhYJD5+aarHCqARVhmAgE02XWUm/lkJvBJH1LSLIf4EsAXBFNMnUXqOmCREgYvIU8/1qHyELUNtMl+pECJE1++/OBAYD7LrMHC+QeB//6ioEw4mmJaHmPf//UHVE+CCJVqIAAQAK9SC2QM/GQHhCBEYGYKIjAMMD0A0xPCCDpKEBMxuzMlBrMBgApCkEARAfE4Ec9pjvS6GuWO4U8gUXCgUPCN0xcHQcDjAoeOjbQzCCExYv/7kmTgB/WUX8sr3KNwAAANIAAAARdZfy0Pco3AAAA0gAAABNDtNj3//8M30aJAybRjNXAocP/GKeHF/GeC4Y8Ba6odpkUkfyZBKwDhJv3UXxmANOuAY2DJk2LQUF7kIMiEhYBA4gqS/rMCPAdBAkrLiaHWRwGGLGv2z71lIJMBSCKllIsAVChoJs3/5wkAmTECs5FQYEPf//UImDBAEgTKOugD7kvdx/y8JgTgCGEuAeHAQgkEcwfEoDRaGFNJqAQwPwLhgAwFDMurMNJlD/25bRS6V1f7Yn5CrGdXHBgcPNNLoBpXGk4q6Ez17vP///GJNGd1G0xScwwUv9MzD7oIDFqgIinfvd/5mELoNMP61LKQnkDA3wGCJkxFjJqzhfjKAKURsO33YthsALNi07ewGFAlp/79AISgUCJ7mgTEmKv/6i0EhYmDRnA3lv//yGgsIDfDWZUwAAAAdsv86sWHAACPn3IGcImkmmDCdQZdYzJpNqMmDIBuLAdrTHgC1eOPQz8vp5ixdtfztmfTpMPQE4CAG4F9zCqDpAwH78S+xnj/+5Jk6AP2g2FKQ9yjcAAADSAAAAEWiYMsr3KN0AAANIAAAARn9RHi7QGXA0i8FkZIH2SF2Bof4WXClSeNUm/rCBQGgP0EzAcsDEJQRGycMCHmfnyeD/AHBy8j+pEyAocDejX8yBEA/79AM6BwR8zYPxFHb/+otBhxUKxdFX//+Rgc0UG66kdmnrUaCgNpgLgjmD2EAYGAHZgxAjmNGdMfdYpJ5kVDGLGCMBACwMDUYDQDY8AKu6BnScamiUWjVLS1oy4SdJgKHhvm1ZACQQBQhEYxl2AAiMimwCS0FfDned5fgVuqlwqBRhIowBAZkMGPuwwLgOZjDWY/A2rqGabHLf///+xkiCYbP5jlhLoZS2MLC6AxBPzWaTEbW9TbuEsBEOB2wQsZom3WoplAAn4BZIQcuJptkwCK8Wn/UpdzwcsFOBcZIjToCBgIjRql/+WBsBFKDkiiyCYIEQND//6wgEBRADUIX1IUAAAAZbdheb6CMAIwBgCzBEAeU3MBAA4woSdTVLDONfMtMrCiHgGy8IcC34p4fuRixXn9Yaxyuu0S//uSZOSH9WJfzCNeonAAAA0gAAABHE2BIg92kcAAADSAAAAEBMycyEZk2BACzRMlCCK4UO02OX///rckaNKYSDiuRCWFWbk2nYFUUGBN1rOTf6wgSBQq/UozGMAwLYCRAny+TBx9RqTofiAocKqX9zUMBA4gfb7gNAT7f/RDHwoFZrJhAALyP/9RoGfiSuspB4///1iWFEVqfMABjHsVg+TBcCUmBIDhWTAlAIMBMFgkURMSUeg30hCjDHAOMBAAowWBGivzRyt1cIPq01LRb1dmHjKoYMqQsGB9TYwGADlB6GlE5kDTtrnf///CNx+KqJmDEmEA+IV8LbumVzGYRBDLY1SpI/0Ai0BZgW9ZksvDmgZNqAwxJc6OoyRrQJ8thuAMoDIgn+tIhoCUIFjpWb5QAwIZv9udCRMGBHzA3C9Qiz//zhUCAOHhPxrhpX//8MkFjDtFahAAAGBjk0l2nZGQLDASAIMHoCkwIQGDA7BQMLo9k2OBsjd/HuMG4ARnqO6uk8AwQBwLS8W3ciUuv4/upK3YEIXN4t4RgpTIwECjiP/7kmTcA/V+X8wj3KNwAAANIAAAAReZfy0Pco3AAAA0gAAABLsGlQu+KW7GeH//7ygFjLvJpGODIHD53ZVNvoKgEyIiR4q4Z//zgNWADTxuYJlAT2ABfAkPJguEXTbWbE8H7AMTx3Gr/WcLIQORzzi/UoAwiT/+3RCEyLalnFB+4gV//5wtBIGGUqEvGkv//8P8HBCGC/KAW6Pii+MgIGAGBWFwCB4DIwuAvjX+BrNco00FDBmBkAANCJKBe7/1KX61NnYy7zOw/6GBuwquG1EhB5lahmBwGz6V1N6////zjjZL7wGJSEJBiX8yuqPGEkIk+40ttIv/hNADlJ7qdEngMQKByYqGBGnemVCqImDZpNX9A3AcNBYWaP8pBCIMP9vCI0aat0Azsu//6jULxE0qFZHB///Mg08QnP1AgAZYyt2GVmAMCYYJIBxiEgXhAMIXB9MNZ544Vinzrpp+MJgBUDAkmAgAYDgKS3CFiAJRVxH6cmDJG/tm1RQpdJgaAByiE5gGD4BAYwPEAzctIw/B5CS1qGZVV1///bL/MKVyFgP/+5Jk5Iv14V9LI9yjcAAADSAAAAEU0X8wr3KNwAAANIAAAATMMUHMEgLblBMQctAAZWgAYxggsWGqXLHL////EgFooKHfP1cmpKh4DS+AABO3bgSxf5u5VIiGWQD2AjUrIu2ikajnAYxYCmYkT7eUQEsS6r3rNdRuAsvBys0TQIeTgICYLAzT/+WB2hE6FDLJhuQWOHn//9APzBZEF+D4gAAAI1jIn4k4wAeCgLzCRAGMCQAswHAWTBhRMMvUe00zGTzBnAvMBYAxBPjHZHDlac3Xp6tvDHKllxc04EggAElhQIBTeLBCDSv6Kz1nvP//3qC1O60LMaAMiJcJtXYgm+YQToYKIraxf/OA0QAw8f5kxsPIKJwWYm5mPxxexbIkGuCwJgv9SyUBAuFzIq+ZAGCFf/rC/ILD2zqxCggZv/6iqF4h4GWXA8Lf//UJeIcKBQUwAAAAwmYCaK2RXhgFgRmCOCEYCQC5giAbmIaUkcXYOZp2y3GDoA8UAZGEAQAQAnysp7pNDMhkEqpIpZyqxJmJKKjcMdMCiW4WfOnK0HMN//uSZPID9w1fySvdpHAAAA0gAAABFl1/Lo9yjcAAADSAAAAEikLor+Ge//+ZyykdZJYCrJHSJ1M7K7jKCWMMAtXUO0yKTfnAKsgY2K+ssGZkIQgV8hiEfkCsk1R04XiFCmcejz/UmM4ASyBEgL6CflkDEiyr/X7lQHMj2xNgkOIMj//OFoIQoUA1iQB9Vf//UGdjiDBTCAAAAj+vA1uIBcEyBz6cSrM4owoyPzV9CUMVprUwDQGU9gMA6hnF4xTxuNz9LWtW9buTb0DoBYEDKQCNsOAJGECJIAgSHLpK+G9fWRwpxFRWoGpYgolIkYnCHigANrKAs+Lqv/WEygOeJcwc8T4GKGgsnJAwI873KhOh1QbyGKv7mgYnChU+31gNAD//7hfgHBj2cMw9oWz//UaBk4gSsXxPv//+JaOwT4eV3bikDr8QTiQRJMTiYLYGBgEhnGCjFCZeJ7Bi4dkGBmFMYDYFKZQVALKAAFtJnPFLnAfd/J+5upNvoquIAwNKGxEIKGAQBhYQTJW/QAEaSTI4alNbfedwzqNLSne0ZAMxaP/7kmTmg/YJX8rD3KNwAAANIAAAARVFfzCM+onAAAA0gAAABNcDC20yfqvQVQZMJ1XMCgQL0uNLbWOXP//+8VBQJjYx5zKYpoJUWMCC0AQNQzad2W3+Z1I2ZhyABb0UQ+z9JEyGdANygKKSLI7s5FAdPGw/6z+icBJsCyo1SWShGBZOCgVTf/lgdgRLg465iHFA4mbN//6QW1BxQL7sQBzKGWtSkKhjKBj3HTMjDWvjCSOBNS4QgyjXrzAYAXHgFQMBWyppkAQiG6DGn5Yz/uFuHBCASYeYSQXAbU2AoARhqCEGBOAIxFtqW1z/pEyNUcQdEBluQDAYipkZlwZsDjEAM8DFxF1JH/MAmQClnziBfGUAxqQFFhEy+Qw4+xbIkGDgAg5eR/qIeCSkMLoJ/SAkFZv79wSKDJI7mAQgSI//5w8GtDgHphpz///mILABKjU0AAAA3celTpVFFUEgSCoJIFAcMD0AgxJATDkGB2NbqPAwqQSAUDgOg4WBLzwXBkzZlsuppyj5y/RPeLAQ8EPzDAmZWHCE66Gg5KIlQijvX8P/+5Jk74f211/JA92kcAAADSAAAAEWZX8vDXqJ0AAANIAAAARf/6uvQm1QuoZPGg8aHzs0ETFAIYzYw8X4tZ63+oISwLhX1lhZSE8gZHKAwdJ5EgRkzqMycNRPYCloaZo/3YmwsNBzsqO3mAGNGEs/9+agmgDjF5mYAkFD7of/zhVCAKDATKETDjl///THQCwUQqh25G3Id8YAoMB8AYwpQFQcB6IwXTCMToNgQgU2t3qzCSBrMAICotygNViWGay8UBxCX2I5RWcsbTIQqADwZvMSh1Tw4DzgmBASPTUh+kt4Z5//95R2nVHAGVFqhxkl3U0juZJW5gcEK5h6lSRf86DUYDIz6ygmTAhGBjq4Fm5BC4OszbSKo5oWpAzgYnUkfqRHUAQuBEqNX9SYGCKlf778vBMoCxB8srDLgZpn//OFUJgwcJWoO6XF///huAu0LlFdIABAAMsaN7YUYAXg53PdDDNBczSJMFdmAzzSWTjscmKBlzAeAGRaQwgmo3rj2rm5vCxrdaU1goBOYrAigkCADgCgqBcYDJJhgJAGLCwF//uSZOeH9ftfSsPco3AAAA0gAAABGC1/Kq9yjdAAADSAAAAEM3N6Z9ZwXoa0c4PWA7EAC3IWEmimMoDcsD6XQFTJAjFJf+iEiwLqH3KCRdEdAaDABJ8PJwZ0opMmYETK4QAANQBIgm31HRuAVoBkQzQT6yUAecOfapLWaghEAs4TZ0S+CRYgyP/8sFoJBQWIVCIgoAX//9YTBDyF2FsUAABIZVXCXzARIEDUT1oM5E6sTC7H0NaUOM2CyezCwAfMA8AYFAIJ5r1gBhsEP9uGblbUs4N0GoEAy2vQDQIGqQDAeBpeIgBBUfRES8il+mTBKFYUIBg0yASAhPsoph3AaI4Gz44iqki/+JcFCi/OKMx0AGkIEQAJ8zJhT6zYrCMgGBGVkX/TNAHgQHBA3b1QhA6f/6Iy4UArtMDcMeGA//84eDyhlMxDgG///FYGbE7n1SAAAADub4LzgAVYmIGnQUJzmcIGGKWWbtYlBvUBKAYQMBABmAAAGW3a+sRyHYpKSx/5Zb1NwQQANmCWH4IQK1pFtjEmBKGgbkuWpztrnfokOP/7kmTmA/ZAX8pDfqJwAAANIAAAARZJfzCM+qkAAAA0gAAABEiGZDIIGx5gSWkGLpw3E6gdeCBpwgj0ixdSR/nQ4oHgC3rKTGw4QMyfB0EkzMfRSR0yoToYPAxoQn0P2SJkA0eCiU2b5SAIKEl9qm6IIRIUMPnEhQYby//84Wgw4XlWLQGwt//+JcHnF4VoaFm3LIfcgEgVAYGkw5gCDAxAMAIPhgstRmX+UQdC5aBh2ANIRgoCkIATSoagzF3YdjMMxmMy39V5Q0sLBw5hIzDA2RTBAMOp2YFHSVsQl9jPDD/1uo3dNukTTMrGcSKbmWpt0BCCzLDRJkpCb/O//////GqCyoo/1uSV44ssRI8tvDFJD9u93dylIqF8QBvA0TZn6lnBugnPEYl5fuwGLLlR/fPM6jEGqkEQk41I0BMmOFL/+WC0EwoMGOsMkIKr//8coHFwtBRWbBQAAABvrXVMoZEIBZgKAGGDwBGYEIDhgWgoGFQd6aaQsRtAH7jwe40AqYLByVkMO/AEI5Xt6qc/uFuMJznGzYHCMoBgiA5lK8j/+5Jk54f141/LQ16idgAADSAAAAEZMYMor3KRwAAANIAAAASMCs8f2pvW////tmZfpYIGIJW6U5cuqPGJEkFACuqW2kUv6iBgxsf5g54kgFFAMPkgYD+WegVysGGAQBMF/0CmA42ChM0T+kAcEN/9tRNhEqUziajM8FtRht//OHg6oXlWL4T+///46w08UZRgFm42NRJuowCAIQIgQCaYBYEBghgNGJkBqdQgGxwYwOGFEAsYCIFY0BQOCmvKaSxPUe6W7/eX6KD0AIK6gwoBMMB4wLCYzGhYwtA4LAHAEZpsdf//q62RKZ/V0mMIGkw4t9LZhw00DHsKDEUBFS02KS/8OJBytP6iwcJUOEA9JA3SJU3JE8fqOnC8KCBEgxhHnb3RJ4AABA4nEI7eiBIbmz/zzZmERSFpZgW1FkxFKBcY8//5YKoZ6DAZYhwOBT///UHlBYFA4AFqDAAAEGPIm4D7pkmAaAQYOoCpWAcBQOTCKOoNOwaM07GhzBZAjKgChhcKjQJL9p9roa3Hl2qST4lved5ajJe44afTBIUTFLYm//uSZOOH9adfy6Pco3AAAA0gAAABGT1/KQ92rcAAADSAAAAE+VSHGFez8z1nvP///CnksVUdMFH1AHKN5yhKUGKcHCR1Z7F2/sH5hTA/MmNyqBjwgUWE+Zj4OdyoSIZKGcGav1LI4ECoMLGqvmYIiJbb+3LIQCQcHVomYNAQ7kf/5w8ImDAFQ1w8///6g742xZaAssXmb2LGAAAAEAxmGCAYYFgCJgXAzmB6s8ZSI9Jo7y/GCYAcYEYAiwQsBn5opTnLa165KrWWNalfYUDZuqIAQWveIQOdMaYYh1aZHOX8M9//7ygFR13lTGQDQJFJ+aa7SMSMxHwxEC11Q7TIpN+oEgoMiPrLBiUg/EA3iDeEyYnkmrOGZ0ZAEWkhD7fUmSgFXQFhhfQT88BkQX+tedJsLXQczbMC+DUQJJ//lg8EgIUK1B/xzl///UGciwB+BIvVQIAGqWJNxZkSgKmASBWYQYKBgUAXmCQDSYn55hylj8mQtZqYDQKJgHAEA4HAgBkwVbWWLje2gm+S6d3lVjzGRwIDDFWQQCjEx0MjMuCjBP/7kmTjC/W1X8uj3KNwAAANIAAAARfxgSqvco3AAAA0gAAABICC98MTdTPDDv/qu6CskvSoMQSKAwmQPjKHbEADGL5YCxFVcM/+gEyIVUPygmTgzYGgegNYxkCYFrKaGxLjiAqIAwo8gyKl+yZVBu4KVCTPJ9RDwMMRK/3rTrLhkFkgOdHqywkJ3CgF2//LBVCAGDBjKDch9Ef//qDhhcQLnTVxQAAABrbdEj3QIAAwoAeYHAEyR5gJAIGGCRGbTonBhQPQGCMBgYAYEYWAyAuSQ478bo687cy7rdyhjgjB5oNuBweYKDAeZTu4GDLpROtjr////lNBUOr5MFn8vDKrPZhWUwmoUEDTZdZSb+cCQkKVX5xRiQIACQBYkikTJi9SzRAdYIoRCs/1pENAXQgoNNm+wC4wqf78pBAEBYUjpGAJgRopf/zhqImFxGkaGmN//+NULih9lRCAAAR/Yo478FvhIDEFB2BACwhA6MC87syYxLjKzahMCgBctKTAKhCtzLYrNRqJU1XPf6zqRMUCD0IswgLUuBwEd9mCzUxWIUv/+5Jk5oP2dGBKK92jdAAADSAAAAEWmX0uj3KNwAAANIAAAASXP///eoNarWkRlgGRG0HZbwdcmgAMau9S5I/8IB4OkepAzJwAFcBYoT5mTBg/NSdEYgDCC6l+tRZAolHGgv50JC1/79IJChGyemgGejTb/+cNRKwuJlAPD///JgOAEaMYAAFm0/LEmcjIA5gSALGGcBuYH4FRgshGGHIuSbVhSRteTzGEyDwYCYHICAQQFV8NLb6htSqawsWOZ2JetAIA58E5GFRk6IODJ3s0BzETDSxnqK/hr//mcspG2IQEYLawwAH1ypF9kAIMTvQHGtPKK2kX/ohNKFTjbFI1LwdCBm8IDU0kjo5RNIqWYETK4ZwAFdHYm33QJ4DAGQJUyQTQVUtwDDxC/bP61BNUMwfyyiJgFAR5//ywahooOQqWHUD3Vf//cOECISFwZbgqQAAH3JK9DYxUDALAPGAMCCAQDgMEcYjgcpyTAcm2C8aYOAKaEQKBqULdX7pKGW0NW9jlly/OuMYAAZ4AlDATSQBInN5ZUBGNXDt0meGff/9X//uSZOOD9UlfzCPbo3AAAA0gAAABGYl/KQ9yjcgAADSAAAAEXqVmd1TEyeVR4qwNO5YJKmVU6YbAyasPUqSL/rCKsGQG5YOkwHFgYjKAwrIIXCBmbaJWIMF6gBo5EjVL6SJAgEHgJMjV/l0DBj2/35wITQWsdEzBoIHEj//LBqHdChSsMmGmr//6wzwQ0PYN1HzAAU/CG2GNLBgCJgRgLGEmBiCgFDAPBLMMpHo22hczhYX+MPUC8vwDgsJA0DBcRgNgyuHRdarKe8xypaZwQaHDlrfZYnUDRAYE/BCEm6vtM1t6///PB92qyFJcxckQcO4c7XfQvOZcM4YdZVvX/hApB3FuYJF0c4DNNgLSiWMBqlFKpMnCWBqBAzYQi6H6jo+AghC0GKvlIDGBC236n5gCYwKIFsmYG4QihJE//5YPCRgwZihg0t///rCIAaYZFSowAAAAy5CmrOsDALgEDeYdIBxgjAUmCYEqYJbVBjslJnPie6YZgEpgtgFFAAIGAKbDGnJoKaXU0W+paqzUdZ8QCE1tTB0RJUgAVnJ9uZSB6//7kmTng/X2YMqr3KN0AAANIAAAARf5fysPco3AAAA0gAAABLnxjVLlz//+ZPqtllwjABjRZAYnOLPWH3IAMAH0YDBaaz801nLn///9ISj8iQP/+q1SPqKGBUMAghE6eHLHf3cpSChiEAbgLabIv6kx0ALrgo0J9BP4BStF/1K5gHRAxA7LKDixhQI7f/koXBEQclsQcHCz///0Q0YLlhcol2FAAARGsXSVVhoYTmFEnTTGUImocmFWWQbIIhptTBOGD2AKLAEDQArnQmBYtCJFVppmaq71doHxGAEjAmDpEACMqLpGIMBAJBDKRaFZv876lj4EqOkgBt1AInBJnlG4yAHLUgZ0AIKk8ik38sBFKDDjcyY2IqBkw4KPSuZj6OL0CuVg0YAICXF/3NQb+DBxbb6YLDSt/V5gHFg4r0kAagRkUv/5xASMKCMX4jZ///rH0GhB2DAAAADDcAMzboOgGAAB8wNAPBkAswKgAjDnIXN4sPg34SqjC8A0EgFxIYBAPa4/m2WY0+V6hpMs6krdAKhE2m8guBIgFAIb7kAOTDv/+5Jk5wP2dGBKQ9ykcAAADSAAAAEWcX0ujXqJwAAANIAAAARxi3hnh///8o6z8oykKbSpmrNPDCN5ixQjxFqUfH/ykDVWC0VtZwxLAZOEtYfuTBoW3bWZF4WcCKmNo1f61EaBVmFpJkv5cAOFFT/bVBMeDhqWZmgQBRU//8sICeQoMqEhIov//8zBYOGW0sc5ZD7aGAGCGEBCmHwAQYHICRgIhIGES5iaxJbx1dOrmIWAAGAiGFgFiQCA4DoBXnBrkyh/rtFcn7FPDi7zAgJjc442KoOkAbmNlNmHIRsIeOgu3N58/W7jRSoALtJhGNQcDxHMVkVihFQAMWj6MBgTL9O7Li6ki/ygErYU4tuUHKghcDaBQd7FgJgU8jVWTHYMiEA8BckUzi1eswHWAtTAYVlxNBuUgMcVM29881IohC1C7TBaiVRFQCgs8//5KF0O6CzicDiQWEI///QDHwLGg2Qq1SAAAADHruttFRUCAwGAAjCaAdMCkBQwJQYjCYSbNKYe42S2RDCUBKMBQCVBxuLaLmeezvXLlf+9vUcIQWDV//uSZOUH9bhfy0Pco3AAAA0gAAABGoV/Jg92jcAAADSAAAAEcDQWgKMAho1BhDCoOL4u9S1sf///85RBEWWwYXRAYDI3rCNqkMqjQDGqM1sVf6QJswo9bUpAsinAIwBcEWXKqL1qOojgB1kqu33YrBfUFnRadus4AKKb/brCA2LjQ0TMEAQUZH/+WERTwYIpQuI3//1Bk4kwfKaCEAb1BLRGyq3hQA4wCgKQCAIYEYBRhYBshmBpoXL4mCqAqYBAAA0RpsNzgeSZ6rz/bHe45UsaVtPkZgIGQyDgE9tzDH1NadtY9////3NNih1lJj6mLDMWvW5QoeKSIcEPzaxf/WE0oLEW6SCZBAMSMBZQRMzIw52LZPB1gt2Xkf1Il4CBoLWjV/rBIKf/28IhQ4PoJhoxEP/84xHhQDWNwPd///UIqUBOR5UwAAAA5g6a8GVmAAA8YFYDBhNgbjQBhgPgXmH0mMcJw1Jo41dGAwAgYBQFRgWAFJIlm0zHjXfPyaAq8N57rVYkvkLhg5PMTCona4BQGdykZm0JiQMi85bwzz1+s//7kmTeB/WrX8tD3KN0AAANIAAAARU9fzCPbo3AAAA0gAAABKjd0/aRc5k45jRTeS386sYzUdjGANU2h2mxyx////xGCqLEXv/utSzTMTBaBBwhjWMNVud1XpDAXOAyCGGef1qOjOAhoBY4ZoJvrKQFERgv2rR6YIBoUVoOssGQnILin2//LCAkIMJKOhwh8pf//LAYcLWA0AquSB/KOKPOmiRAdg4V4wKgCTAYBtMBFSYwqSSTGwiXMDEC8wGABi+ohACv4PgiFVaXC139VblC2QgD5jqKAoIInAwJGh9AYaAiYcMV6meH///2zEX6TKMDJZL6M2qSG0TDHqQJi/f53/uDRyFDD8wWXBlwMhBBReQQuDrM23LREQSBgYIIXUl/uXAAQwOYFdB+oxAFHlX+v1Dkgwiz0igCYUW1L/+WERnQYGrF0Ie///zIWkLiic0wAAAAymYCYa4QAANMCUB8wkQRDAoAjMFIF0xEUZDijEDMSi4YOAdDANgwJRYG0UGAQHlVkf//71XiDcwsFBlkppACRcUEBqZRxOYCAuspyY3/+5Jk7Qf2l2BKQ9ykcAAADSAAAAEWvX0tD3KNwAAANIAAAARS5f//vV1siL0Ms1DC/Ih9c6ip4ISnMPTrGQSStfqWmyKX5ZAjXAslS9RMiEQGQ0ASjEicHSTLsswJ8vhsgA3EkD7epFIdIBKsC0EnkfmQGMGFb7VpqsQ4CgYKOjV2MyYCAmLGr/+WDwnsFlDSsDA7///kwDBwYYqiEAAEjVd4GitgZOCADTASAmCgApQCKYWYmpr7gMmXCzmYGQE5QC0XBSbhyNclEopMP1h/cKeGBCCnkyANEWfFujxLYx0CVhi1nLn///+FPNxVjIAa1B6m86R+zPAUFHsPY5f8xCBaNF/QMxnAAWgFhBPmZMIPonysIRAHDyJI/rUUQapSPUv50BQGWn/v0wgDBwTZ1AgogZv/5xiNC4rR9iZf//xaBAorVUAAB9+KNfbQZAjAQLJhtAHAIFoCg6GDWyOaw5Zxs4TfGEeBoYDIB4MDSmiOSJyy3tikhl8hyq95blj9lrD4R3MJD5bacB4VNCzJSzfKT3reGH/+6zwp+uUkMZSP//uQZOeD9ktfykPdo3AAAA0gAAABFSV9MI9ujcAAADSAAAAEgYUm1k8sdsUCBgd9Aopr2itpF2/OA0vhphvrSNS8I5A0M0C1EhTMZ4pI0DMiBIhMCBrww2zR/rQIuAItBR+TiaHmYImAwm/n9aISVCap5imBAYIci//5YYaoOUuoS8aSf//1heAbCFpRLtVrSZpzTTAFA4MEIAgw9ALzBBAeMFEIww7m+zZ8JQOPGc8wsgATApAdKAQBoAiBHIjEHR+Xd1TUm8rMuaqAQEODRrMNwZKwEIQtNKpDMTwJQ0duUU9TPPn7wrtwT8k6VBiyVAOGht5ZumSNMgy9MNQYTBd6W02OX////RUc1+2v/eqsQTfMEilBwXuRGH/p73d1p0ZkEgYG8FC4TZF+ySJAgMAcBS0SJ9utEApsVf8/rLATbB6hugmXCfCEwKUT//koiaAo0qDJQuQv//1HQkETBEAdQAAG60y3ZupAAOIgHjAsA9MAsCAwRQMDD+G1N8IOI3bk3DC/A4MEoDcmGwcAWjxuVRnGi/VrmWOVLHRACzjy//uSZOyP9jNgSivco3QAAA0gAAABGm1/Jg92kdAAADSAAAAE4BRBL9CEPGINoh8XNcaZrb1///4yp4ndT1MIo8MBsasy+GEE5ko9jxtqZ//1g0gjfS+ajuAzBQGISQMB/KKWgVysGoAY4CRRP9SyOAgwDpi6r5mBiAZb/36gakgWCLUsoJiEwcCf//lhaIOI5DQ0hv//w7gfcPnNhAAAAR3UTZRExwBwwBQADBNATRECoDZhJFSGpUIKa25LZgkASzCdDuO2/jkQ5FLsxyjs/rdaDSUKN1vQaGLtEQWdj2gIlXdS2se///+9SVqtaFgZZJi+DreE23QwKKL7utLbSL/1BJSNr1oHR0ARjCuF9M0Z9aRsMsBZmVmf9ZQAiYDQE0PoAJBFT/9g4oGBH1MF+xsv//OTcLyyMENb//8dQecdDjAAAACj497JHHAAHYcEUNENGCAAiYDQSpgEO/GCQX2dywVRiKgQmB4BgXSGQgJBpO1vIedqT42qWatXbkfYwQC8xfnCUjphAYbD+oDlktxvoTPXs9//8tw5KGnEICMCu//7kmTeg/W6X8sr3KN0AAANIAAAARS1fzCPbo3AAAA0gAAABIwMBINrTj9o4GgRCY/DixYepUkVfpg0zgSHn9jctFsYAFr4O+Cxk2KYSi7JjsGyERoGLKC5zi/dj5UChMKZCXPJrUtRHgCKSCq96lLpHhxgtFPsozJwITI56v/5KKOhRxWGeB7qH//1k8FF4WEoIVqWGnBbkDAHjAhApMKEEowOgMTBWBpMSNMI4Tx0TpLP2MPoBsoCPMMBciE6YDGIFn565vOtjnqvKG5kAgOHTEwUMkcwsDjnusAxYR/dSX0meGH/+qrdkpnJSFMpmMOPrfSaLuAIQKYwd4cdHlnrLt/OhCXQWERtrmJKCWgLpELISwaEkbNWcOl0QVBREDwfZ+pEyFpAJIoDQlLyPrLANA8c+1SGkwNQWFBifRUU0A1aDgOz//koosBQU1hrhOaX//0BEwWCwWtH6kAABq7HHjbAIwOQIA+YDAHwWALJgYDENF1OQEEA35FvTCHAtZFBCoHYiEme+WRCvX+3+eFO7AyBJraUwKEcaAUQBGYSQCT/+5Jk7wf2cV/Jw9yjcAAADSAAAAEZJX8or3Kt0AAANIAAAASAS1SS0F3W+8/88H3aPJmfmFhMgoM4cp9VU9jEgrDBADVdQ7TIpN+sJyQYRQ6Ky4OMDMGwRVxwEwM+WVbEmO4GoQExJYRV9ZwboEIYWnmCaHlkAUqY/fbog1Mg4SlmJmCAIHvI//ywowBg6iM8F3n///qDrhxwaQWnJzOkjbkDIAxgNACmE0AgGAXBUFYwfUmzSpH6NoNmQwlgWCsCUKgEQhVqL9wJk/1i7GpZSd52xIi/gDYJhoHl+gKHDX2KMTgZXL/UtNj////lEWeu8lUYgQAQIodnpx/1hDKpWDDNLct/6kASfhRGhqOqMRPQAF4BgUYuRUxepaCiBgitEmz/sbgIAg5eVE260wMEKJ7/bnQhNidegbhMQOBf/8sUAoQaOsLjn///qDXmwfOhMABAALtp+WnO6YAYBpgdACGGwBGYHYFBgkhBGFkyCabhBBtVUUmC6BmHAFjAUSYZbVfiml7qxrOHsfysz0JBIAPTpsxCOC1JgoEnh1WPNAeA//uSZOIL9fhgSqvdo3QAAA0gAAABFn1/LK9yjcAAADSAAAAEbqxadv81v96rt0SkusEMtk4WOjQ4pG30LAPAMHMGAhS2HqU2Rf8mgKUQLQi1oGZoTYrQDQzgGrAuMi4xhQT3JAZEGgUDCDiKmSKutJEdQBDIETonUvk6BkQpOv/PNUUQgVh76soF4MvA4Afb/8sJkMCimoO+GFjf//6gkBC0gL8FUQADmTwr6fUcASEADBgdAdmA2A8YH4HBh7EGm9EI8ZicKQIA8MBoBNJhACy2O0UQhc3S9/uscqV0hABTcDUGA22ACgs4Q9THIJL0SOct4Z////KOs/KOpCo1DY9VvzjnGVBkYmAbXpbaRS/rBo1As3PdNEyE8gYuqBZKXlkOMka1F9xyAFKJIO31LI4E3Q6DqvVAkUS/27ggIgoPbMjAG9xGqX/8sJlIKDJwP6OBf//4tIXFEFTyMAAAAN4RNlDhqyGAOAgYMoE4KAIMBECswxDQjb8GLMa6I8wDwGxCAEPAMHBB21A5fqW5Sqdt17OVWaiIqGDIsNEQCXsFw//7kmTnh/aUX8pD3KNwAAANIAAAARbFfyyPco3AAAA0gAAABIZp1BKBC/cOV6meHP/93HpUdhppxkIOExOc2fljtogGMVAPFeevdb/QBozBSE/WsuCkwMVHAkrIIXCBmbaJbIMGDgMeBKSKX6ZoAk0CiAroJ9RkCxYtP+v3BvUKI7smaBAHImr/+WHGoFCFIboaQ3//6gcEDpl5Xrc5A6Fo0CsUCngoDkwAAUzAcUCMUQaExso0jABAuS+QbTeV05MVh6fnqC7law3coWyBcQmf4QChMgqAAyaTzZh4DvFDMqq5f///5yiCIstgwmjggERupdoFgTGKlBIGWrD1Kkj+owCLEFI3nVFocoDHOgRLiqcIaYpVJk4ahuwDoRPoP9kidAJGgspKzfTAGIn2/X6QrgORHnUZsK1EXb/+WHH0FCOgDgLf//WM4FxA3hoQgAAAZYuEsKw5fBgJgMmE2BwYFgEpgnA7mH2jgbcJDJo1y/mDgB+YD4EwXD6PzuN/AskorEpmKlXHCvEGRgALHNn6YIEaOZhELHPH0Blkki60ttf/+5Jk4gf141/LQ9yjcAAADSAAAAEWbX8sD3KNwAAANIAAAAQ7//+sYCW05KmJjs/hBBdaQy9/ExzNQ5MbAN3qXJH+oi4QOQW1q1FMwIuJsAxOwBggQcvkAMH0iqQULUgaQMO02R9Szg/ghhiCJkv5gBhRho/636YNBwORFrOmYIAghyL//lhxrA44yxQgbSr//6w3AYVDlyTYgABNYwQzOCBwBkqgImAIBMKAHhwIJhkhcm4CEQaNzURglgVCwAsGLDvJLLs5ai0InY5zncKd/GRnIywYFDDgpoG/0cLIRj8mo73ef//vCC2j4O2YwIY0L4Ep6SJpKCFSBwjfqdyRf9ZkDQ6FIfmbHRlQMeZBZaVzMjji9ArlsOoAEZIgn/QKYCyEFh5on8pgLC0/99bgkQDT16BuEIQuL//nHHQFANYlxml//+IoeFoLdRAAACBrNrigbWAKAcYFACJhUAQCQDYEBSMLtPU1kxyjeLdpMKwBEwNQCjEgORAXaoKq9mjE4xSyaMUF/l+igYWAB4gWAAHsNHRSbE55h8HuBG6lfDP///uSZOkD9k5gSqPco3AAAA0gAAABFjV/Lw9yjdAAADSAAAAE/+dlsEuMMgQwMtAcCoZprNGraZhN5iEDK5h6lSRf8sgmzB3JDnVlgOuAR9Bs+TBcJ9NqlmxPCAwCl8njV/uxPANAApDLTt1wamFr9s/rg1RC4iupZQNg6IN4f/+WExdBQrWKGC70v//rDDB9wy6bGAABZvwcwZxQuBOYFwBxhwATmB6BQYI4QBhUM1mf8WYcsS+Rh+gTGAEAmChzFghUyd5RaWZ3akumrk/TUsad0Cg8a+nKYCgKEAUDQ0MVo6MGQiXi+0prb1//+rrZEXoi00OM8eGRq8Uh9rAhAsxiLceJHDPn/MQQNQLmz3KLloegNMAB14iBMC7I1S1JkgPIRDgZEQU1L9aRiM8BCEBI8XUvkqAudJx/fP6ygDVQA0AN1LLCgKgw3lJv/ywXw6gLIGZIKEz///4f4FA4XuNlMAAAAOdoW5QSMgTAQAwwNgKzAPAEMCMCgwwCBTaoC4Nn0mEOD9QkhgKYWiox1968hppXeuz9rGtMukKBE0Y1if/7kmTqA/YpX8qj3KNwAAANIAAAARnNfykPdo3AAAA0gAAABAFKWgQDm14GDkS5UO01nv///+FPNxVVEwAgUF5RXqTadxhhLIc2nS20il/UEJUGLfOqOi6CdYT0X0zzPqRNRlQWgF1JvqWPgEKoL2GaH1AECF/7+CYQHCOmwRCkXV//OOKcDAjKGfDan//+xeDghAjGAAZ3ImoozMYAPMA0BowVQMy/hgUgHmG8XEbhAjZwKAimHWAiRAeGGwu/7bLzaJlGH8js/LscdXZI0cZDxgSLjIbgYoARywThynT5e6iv8z///eoBUdf5dxjYtCQ6eWenIfXQZhAAOMTi02KX+mEiIO3vzNjclgMqABSIRMvj4LC9iTIkEwQCwUiy1fuXAbKCjErs/UYgYUKaP+rzMRIKGXqLJqHQh52//lg2FOChBlCKkWX//6lD5BgENVuqFAAABGuMHUg84IAqKAXygYYwJgCzAMBxMBBbAyfiDziNPGMLgAsqAHTSgYkCF3M2fqO2Zj5fjhupE3YFRGbVjxAFHiEAWN93wyMCmDQ5T2P/+5Jk3wf1g1/Lw9yjcAAADSAAAAEXmX8sj3KNwAAANIAAAAQ8Of/6rwAxifZQY7QAkPHXjEbdAVAphZshhAdWespN/OhAVBGC6zpiUhPICeoCgUsMTyTVHTA2JMEXYkjzt6JkRUAlWDCheR+mAcgLbfqVrQEJwcldpidAgAEORf/8sGwiAUKnlB3w2Bv//UkGLw2IQgPGAZYv0w2mHCIGFnVHGQEmUamDGWEZ84m5pMG1mDWAiQALGAGADDzut/RQ/br1qlXfOZ2IbQSGGIDGzhlo4AaYAAj5buepbm9f9i8RxBRSIGDrhgknkUjUc4DTTgbCi4i6ki/9YZ6Czv1poE+BgiYKFycMCmd7nidERC1wuq/qKYSOi50F/YM0e/26IYPDSX0Ewwxc//zjjcDgcmRFm//+oSskhjT1IAAAAMttUUXbAloSgOiAEALAJkwPpiEg1m/+DYbPbSxhFAZGBeAiuBBOgMas5N63KbNJLtY9vUcIULOsgwLhlHYwCFjZ1qMThCGYeltrH///3cetRuVPmZAC5QQnsn5Y/6gBlc4A//uSZOcH9hNfyqPco3AAAA0gAAABFKl/Mw16idAAADSAAAAE43Vdb/5mDQKDwR/llRiJ6AxVIBosXUiZMXrMC+mMoAxVHh2/QIeAYVBys0Tb0wCiJs39udBqbDspZgmHpB5n//nD4vAoNxnA3lv//qDDiSB6zIfnGGXs4MAcDEwPgFzDWAqCAThQHYwz2WTf3ICNyS9EBBpGA8AURF8wECFmFvHDedrEth+SRl1rWNNGWdGAgef2YRhAVOSRDE+SdQVBSgBN7Ip2/zX/3luKUjTiEEAV8GAgI9Mkj7dCEKmFZaYCCyFLrS02RS/JUGgkHzn1EeXCbDAgGj4AKUBmyLjGFBNnRIUZICowDOkSDF1JuikiRYDBJAGqxIn26ygBlSw8r9s9qRCbUfKWUigBESF2mzf/kofDOgYUrDPBDUP//pBnIFiAOCFV1UAABetSGBnNFQDjA4ACMQgBswUwKjBFC0MIh4Mz7jaDS1ymMIQIAwBAXRCAAsAyQALsV9DL2WqeW2pTjWmYkvkQiw73PzDYnTkMDhk71lTMoDQodeWW7P/7kmTyB/W/X8tD3KN0AAANIAAAARqNgSavco3QAAA0gAAABGef/vVVnxKAGspEmaTaEI1m0Jkb8FnzTgsMnBNY0O0yKSP7BdEF7Z/RKZiTQjEDQ8wFKpJHRjiki6BmRAqBesDhghpmj+tR0awILwX2KKl9AfYGCQk2r3z2pMGrUFhaCaCZFAgNkel//JQvBMAFFpusLbB66X//3FdBY6GC3EAAARHMoBapEUvjAEAOMD4C0wDQEDAnAsMMokk2dgpDFgfJBQFYcAgEAJecARRv2syCQT0mrWcN3KGCiUFmWnALBVQIRBIyPdjDAAVjmLut6///8JW+M6z8w0bwwPxinlD7qqGG0sLDuXWet/pFYFMT86mYChwMBHAkXIoXCbTbSPE6HEgDICdSb9MmAIngRDDdB/UDUYl/tzMEg4KC2qM2D8RA7f/zhsKEBwV1jqDg3///HwGYFcTVIAAAAO6cNpD1piGAWAgYHYFayA4DIwwCPjZcBxMd58AwBwGjAQAGMCAhkmX2IBpZXYnLOeOtzDdxwMGTm+SgpE0EBE0LXwL/+5Jk6oP2pl/Jq9yjdAAADSAAAAEXEX8uj3KNwAAANIAAAAQA2HQ7TY5f///5SlusPKrGHDYHBKM02NMqqYxPJgMAMtl1lJH+sVgFtaHOuakWAxyIFmRaOEaYvoFctiQADITRP+5qFo4MJH29R0Exq/6/WK6DBrZ06H6CLo//zh8RAKAcjwyr///WJYHmGVPmAbxgdoDriIBIeBaDByzA2AdMAwI8wGmjDOCKxNLOp0wHAcQYBkXNC4BQyAGhcy1+Y5ulr00q/tSVv4BQ2dFiQBH6DRgsLHZnkZlAiYrbRWevd//3qu3RAqbYgZZKAkaGhxSH3IL/mfjWCkrD1XLf/////tKQaWf/+pLUj7CAKiAcAH/p4csX+fVnoeQnGMwC21nLn/+sa0AhUmiQZpsf/6igABw2+1aeyQJCBfxq9i+EFiGL//lgrhEAO7UG7DCyf//1hEAnEMFFthQAAABlt9mIxoKAImAyACYOoCxgLAFmBICeYO54BpgiTmjw0wYMYBQhAAEIFp43DkYpKS7ymvT/eZ2IbLgHHC2YKDjrl+De//uSZOKH9Ztfy8Pco3QAAA0gAAABGVWBKQ9yc8AAADSAAAAEasHjQnnILdjuH///y/WflRURoVVGPXbkfTIIFIDgG60ttIv/hjgUxNzrHx2gZEOFGpJmY/HOmVCqHVAGJE+h+tRHggVhcsuJ03nEQBQLf79wQCAYDRrMD4dEJI//84fESC4tQlZEG//+sRIbYgV0CtdepsKsgqKIEJhYBjDZwlJiHg5G/KEibXrFZhfAVmASA4hCu1QV6pPTTb7w9hS1t5RiJx9IoxYQJzAZALU1IQGTCQGbKwG05HrnpXfz8zOD5EYk0M0BwiwIpRBSsVCLjdA6McDQhBOpPGqSP1pphAGB3I062IYL8EG0UOYFwtqPG6ajxFRyQGLA0Um61uxuDdoLMy0mgdN7lcA4YW1/3oGZwGhwLlMgtJIOTDsv/6ssGQboGAHUNUN4b//6xLguWILlZTgAAABq8yBL+GCEiEBQGIJg5YOGCGTGZwIexoTFPAYKZOl3Ed59pkRkcQjd+9f/uErhM0h6YUQKRcVnSHIwKA9noeOZhGcj17GDHP/7kmTih/WoX0uj3KNwAAANIAAAARiRfy0NeonAAAA0gAAABExuAYOIHKGh9JhN4GQmhQ6ef/Us3DRAczZtaB4iYLBQYFLRcI8xPM82SFMC6JkzXW61OZAgEBcpF3UndYcEaJv+9VQNQhoqySg7pmr/1HqnF8JjlwVBF//+pkhJiAPE//njxAaL6K544aeOEBuSIGL//q43OMU9DTzP/0UmnKFgXjYsOi4AAADMCJJmTicZRkZnuXGdDObPJw0BSUIgwQBUiGSH+aaaByclGcgqNHM7AOqUeAr4GDM4iIqcbTFpyivnUicQaqKiSXX44yhxZcOq1eQQ/Dl/DPP/73l/CgYWs154clcqekVIqGL//rbQWI4LJauti6CnCKPVfqKhMjF2Tb6IcojoUlczJXb/Uph7J11sXVf/93MdJFv//0CWX//ioLyxiuvUag3kRY4K4pAUHskVz//yMTCdXiQIRFb/8Zl3qxAYBUJypOqUACAAAShFotIcdszzs1XUXVQyEIBn52GWOnpZaEOSzq6zFgsppEZ6ldzrF1FWhk8AMRT/+5Jk5IP1UF/NI16iciTMx7AAB55TfX1DzmGtwKszYcAAKngqKR8dGV137WbWz6sGsZK+ASlVDn4NqrapUBElFfhgIWUv+GMDYMBOX3BgJTX0UpUf99IYGCfg3Vv/8tWUv+ZW9WegEFFG//xBAVh6b9So+dFC6E4oIYF4Wf//Kg3C0PnNHDjjkOf/xVFl51AHgAQUw+cAAIERFxYed66mE7RblTEwoxMIzzE9U0yQtSgIFLpaaPEfreXPbMyyewWHJBEEPgKlgtX5czBWZnZ2glD0RiTFq11o6MaHT3mRSmMYKR7sVjHL/cs0pDaGM6lRymehlZWf/y6+FAobT9PT/1lBTAsr0P7m/7OWNyWXgU42DX+yt3tTq3oyE/yO1CshF+VM/U0letG73/fX/856NTR1V3VkFVsIAnncVVUwgcBBQABIhJkGZzppwkqAgYGmUImKEpmqDRR3u0i6RzEFBzbSRIomzazpIs2IQaqlyShem3NPUObEHED1NeU94+lEyWXkOiljslVmtUgqhlZGc+udFC3FOjm3Xadfwe8qtVpo//uSZNiC88hfzlMMFFAsDNhQAAqeDXUhHQ0wT4DVMuFAAIn4GzBlhjXE0fDyBGCzkx3XBqdeXO+8id//5MZGoZi2YO3RDFSgL+TI+UIyZbLg2oCyQeUuoZRNlPT4wAeYmKVs8WpBiyAU9qPfuUxuPqdFOm85bf/bw64kRqRGQ3Wxc7TAzkcrNzei+Ztti//NWVBy+ouXVAJT8COuTaxWgCNDglHtg9LIlNf19aRzLErn9fdGPtTZrDtq8p2TK8mhe7oGBuQptrvks3RbpRy2s7ERmp3ZpRRNWW5gubcmsOP33qFJyw3pMoZjxEeYquSRERfCweSUnEk0Oxka5AqZ1mhEZKhKq4MLnxkORAezk7GKQIeWKFOf9ylL8zMMytE0RytcMsZGOZSkSYJjDiAax2RTBQKQlSAAAIBW0imXStsNgoWp7k1TcxJJwQgmzc2bKio2Km/JazzptN/DT8ZXbthRqoBkZ/Ph93K05npnRdzH172FPWz/AbXDgRPSg9QKtozMHmYBO6RDpI2ktsfZFw+MC7uEoiQZDJPo1kfmJeefHv/7kmT0hPQCT0EDRhxyQYlYUAQjrku5iwrDDFkJdDJggACMaeL83Vwtw9lnLXHTbj+9QmZm7gijbKf7Eg5BVVaJLDe57LLFheTEKK7UgY2xE1JNoGVV1S1CZQYhjoKONB1qCqqoKlUKa/tViw0M4aw//mpVDoUq3uXilaxj7DpZK1Suq9VqAgxOthk3RjZglVOJFApX0wvTFlTDG+Lvpqu+XvRa9PbHUZt3IoJBUrEQgSJwwRI+kP2BjREauIyqUbJgWEtAxZ+cpkrZ1jIYENhMPTFxqym4YGwIOGBCLJ8S235kq+WQ5mM0oVOYqkaViSwmFodhEaqrkgKk0Cu4XHpCUX9NG/t6/KXVSR7ZWq+mqG1rVqe2l3DlQql/FDMjWanZqXlinwzmF5CiELD8XGZqwYI7hK46WPazodDUl4aI62AmDddUoKRLhL5GQcZOtDuNZ4dSlPukg5ZBMSEhJZQSE73tQ9TmqAoqxAVkfzSEmDHV/m0QUHrYcuiPqU2jHLhBE89odq70jV/E/pmQv/+t3oo4zLenOxjdvtbdU+L3XNz/+5Jk9QDzxmVAQMZFcFzMqAAAAwAOnYsJQyR4CPqmn0Agj9DKjIyi0PrUVpU1lndHdTF1FuYyV8lfpoViuUJLTG0fThdJE5oTlTf36k4Sd3oECugqP1PPIx2+rodyKevkIrozSEko3q/J7+TkYofORTySMrIyn66oS5OqCjHkF6jOIEEgEQ7bqNGpc43jrMiyyNUUeFZmPK4tuzOerLUZLmgvOYMommhQt2S9CCGpFct8rmXcOxIJu7LzoNEzM7CIWcaNHiCCJZtkmqc9bRJHqomw3GKa2jJQx5W9L1fiiuPv78Vibj3HxFkJj0STS4KIYHEzY3huSoEYQ6HjKMiQjacd4sdnRS3gsn0ZjsmxuDUrtlVWC75Qg2l3SrhlVx3KKZmQIRHLVk8aH05x2rrAQIUoFH3JM6MXT5NSUnBNl2KCRXYauFR1yWkgMqq2zYmkezIkT1P8ul577zEtrx8dpzBVuUZyTUkaLKtPCkfQRZ3ZT/24eaMkBFTPWFBAtC58mmbip0VnzPs+XfG7f+Xzu+9e8Gfnq9aE18C78lWtTVf///uSZO+Fc5BiQAjDNpJOq/fwBGV8DMVfAwMMukmAMOBUAIwhhT/V7GhbkE5MkoBPGnIOkqjqiksqrXzbimJTnRtiPkbMjcajrtxuvvkJtVFqwmTByHZwOMxCaqUr/USMty2j95R0Psc3Ti3VSLcicw5vu6RJ6muI6SGkioN9uaBAG/yakStIl+cNjrAjljjOz43LQR/ysT7ZKsamOOXfcDpytPnKP/BNHzxyP/EhIxhoRdHjkziAkjHFHxrOhrFaPZQ62Ncd/4xHh4QHiZhQO4hjMIrVtB/zkMIsigrkf/6tqKvGUqcal6OO8pFwyVZNNUvf/ze6lak67Pi6aVss491e+f5T6BJqnDc5rHl6nq0YjkQxDoFiTUCR///ox+xhhuxPV/RBFzq6av1GTSvRUf9H+F/cggZjqeayay9dSvL73rlN3S1f5XorFQwg4QE3cyjeKY2DA9S1ZgxsSGu1ZTUoezK3s5escSaeWGM9VaFGFPnK4Vv+5kVSvBicoY7lQ3WyKQFay1LzL/4YzqxjZEeXXtUsc3CToNAb8lEtMGFEGP/7kmTrBfLwR0CIwzaiVYo4EAAjHEx1jPqjCLwBnK+fQACYQFI1L9uNRLOKWCm+Of+BnQlPwqCmplRMNeE1E8FLCP+Garka3JuUYC9mL/BjBjyYwsaW4UTKqwSvrmt1govnhVCBScsi9VKAo/ksFX6WCHKIKpaqJAQAAIJU8JQwR4qJPSrJUTcIo0T4CkwKClcWnu/vvcvBCIfCRU3pxFS9/FeHYNz8smVv0Gc/BoaMZ/+mb2mfTjKiALXwVH3v5uGMuJN3vvecqGfsmTdkoNgrL7pM/sEQCRWUDlJn9jxBdDizyiOwAXXQnlfr6UDFiUafehISIV6/U/orufufYGF+GACd4I0iFES+hdcDF7onAAQVdP4hIkQnDufQBPf+acECXcOhPAAQkqJXP4kT0+FifEgQKNAHE/v72Y46DFviixSoFKfe/rr4i/r60vggxSaP04wudqxTnc47Wh0Evjib80MvrbDc46GEwx8OlCEZOGpaEcGhzGhr8Jbxo2kYK5fCsC4OHxmWzxCWCQcF6bULKEcxvk4dGjxRJJQR+F5ilmj/+5Jk6oBylVG/4GMTcFgrx6AAIxAO7ZbupCx+wYGy3lRRorimz4BCUOkdzwNzPEW/w0PXCJQqOYacPyG1OAhx3ogkydjZ121R4UUjM41RrtST4VGGjCr/wjmVCNrhSqNSdC3yiXbfey5JkLaLVqyFuTI0rpVtqaitMFgalWxquQ+m1SXOBNzMCfqvszi0qaCpHal2qVoQAARgZBFbP9IvJMPCkToxGBDlAXNwGBL+ICED2Kn5S6FGXwvGZtAThLMiSVSbp8YlUyMjQeU1zsqPH52vls8LAlHJXEhTqo+HQfE9e5IcEzVg1YqL5ZH1tCOyY6JdfPIT8zNGi3xdOjJSceeiWtHM6l0mnS08UpXPmZPz9LpIq4uovOzAknw8lw7EonriZ9i+mEs5LhZVnhLRnaUXoAn6HguFiTzRZJfTcV1SF1kcrLGCcSHRHK6NcXjUIQdARRtjSEKNSNPIUfV4bo9G1uXoXtxl5NpwU2I1j2cmUsVgoQg6eElo9kk0wxx9G742fTt1KUVvfYcg4pFdoN8/+3Or8c/GcXA2s+NEogZN//uSZOgEdiBluwHsfOC6zLd1FSwuD+GVASMk2AFgMSBgEIwBwpPymV/RPPXjplb2bH8x2fyxxNSJZ5CteESN4yJuDaMOKTCKQAlPrvi5hFFuTYIlK7ZSOrSOR8sqz+MCZv2TY5skd9SajFDOKQpU2qwmnqCkxL4XNm3YjpJWbmWql3gWcz8rDSoRxv8g7e7PsrNimcHNvjWGRkdGnKcmeGLt152JKSiKDZmEQEGkASLtrpIvFS6LMi+nV6aUdud6jhCGGFpCy6JwVWiljTwzJZM2hnK3N1I5IFm9nGvt1LVazdC5BhVJXcTBGrDDlnHoO3gqcynlLpeW55JY9bGJJ1iWWhO/xv8aunenNxG+arXtMh4TfeCw/A6fqQxA4tviiHa6iTPjmgIUlNWsa/DVL6ieZgR0YGVxODcurHL70b02y//ilV9PQpn7IVttHborKUjcurFr/7mVDFZRETV1ACNk5gPYlpXMtbuuvuWnUpvvWmEwwts5hbQYeSQj4hIQsInGt6ER2yotpnjXaVzgMQY+tlJDuz4X5xDO74YrDUC1R//7kmR8APN8ZEFIyB5gQuxoEAQCgg6JeQTDJNgA0AAgQBCI4GKHM2VOtTZtPmMbnpDQLUTuW7Cccoq31vvb96bWzz99fTntPcX9b7LlFBkmL6iZBYGAxQXnSfsp6M6k6jDRZJFB3Pa1CEFWiCsFTlKnVa3Pt1Yq4VCt7jCKlpptLxem/1A1SlNr5fkgh3bPIpkzE4nU/S7U+po2VWZ/7YYrUWdVcKka3K7f0vArCxxBVWKC4ro1DhYKaDTM6Bdw7kphHyINMQXxIIvKZupIjhDcfQIi2HjwUSO7p/UrFFPzuKTQIKJiM7axkcSkMQMbdVb44IzQAEABN0nu8O9Na77nxQQAGeQN8lfyGNgRJGwaN//nn/yjvP/zGfxKb9+h3mmi5Lv7zgLv0uXc6AZI6QsykyYgVkaAl2MEIqGWFdYIah2BETOZPpY3OrDQtG+FGNeBlsBOO+x8/tVoJPg68p42ETebCsJIiyeJKqDTaqYSZyn35IXrhDcyMSo6MJiptSHiGtKm12eEDZv7wMpA7UYUL+YDxALaxDARuUgHM6FEE2T/+5BkjY8zZmXAgMgdYEEpmCgII55MzWEEAZh8iSqp4NQRipFE5qLJ+jIEa1Q1b8kqTLNptW7spEdSuRU3+nZqKljnF+Vz65FnYw1n8gn3lzXYyzVsrdEeTqZ58ICmCtrj52R5tv7/rxkABFL2chUujNbu4cqX+Qy+12v3RyszChnzVnjIJZQUA1BsJg7OmVGUaljBhB11fkKpZtljReTYJOJfQoUHzHVpcWVCXjz1sp+JnTiyIoNcwiSce1upYjGmRFMMGUZHzPiUzNxsvJb1uca1tLgvaiLHGTNSSxzlrCosCgsVWPOuVWwUEyEPEInVFwEeLqF82JmMOrOtAIZdSmxbDoc81TuFlYwUUZPFrg0p0aXL2y5yywobFWbGmckRJSIoMQ0IrKdq7GpJIdgXBMrmRYyB90NNiioU/DCIHrmTSbewxMukZvmE5S45VW1uTMesUnm2vshRGys90+5HMc8zKHZDZzsXhFmDdlq2ZIQMa3O+ViEylztKKWyl6kC1uZBOS1qUKHsPvWOUUlCCCbLL0ISmLBpQDRpnCGOpn7X/+5JknIDznmLBEMgWYkBACEAEI14NEZMPQaR0yO0AYMAAiACLjFCUsUectYUO31MocYi+QGMU0BPQdGKc0KPCOs6lKQAEXV2kB8U4jhjiIaBgzhp3QL1KyvGJk/kOce0eOCgPIqJUcIEjCVogPRAml0i1+uOZkLcrNfIpq1HeEU/Mp4sUjAjx1BqeljxPCCj4x5pRYCKVcnLhopMcO9wEmRPBKy7Xxc3ITd/TabZTIjyNorwnJ0mbDs3piM2D542/9EAAs5BgAG5A5OLmLZviGF5mWo1hrH6IkNJol6ElPz5OWXCQ5n9cog1ZAQCv4e6KrL8a053Ky2GCvjfnS8Zhm7jaH/Xty8Q4jcO5EAnXoVUIUEImlyI/qi8PQVcIAJDsQc6m/TFeQXak5rBQcBEBFhgyWEMzNZMlSVCBBFNnZzvaVZ0ewipWIzGNKRb3oLETImQfXnTbPtpW6ZQ2WZHkRb3buvnS2DIYrK493W2ms/8qbEhBVyrs3qvZDUs+nn6Gq8aZMCuCb1OccybVirU88tb+OREV4h8ZJnU0Khv3x02e//uSZK+F8z1awRBpHZJA7AgwCCO+DQ1/AqMMuwlGLSCAAAwBBlec6iAG4ENQxUQN4wIQb6vJr7uEiJs7hczb5OlBp5JmJoHOqHttZ4+JdyB/Z02+zDU+p6AflsVcFhqy0MZ8GyjuzsW77CinRG1B174jLi9nt1tLdv8Cdy70s8kJ4Q/5k7WuVhsaLUlNejm1oREgABAF2CzBUySYBWvHmgOsVQtpRTSwiaEQy5oDDa3BYpljTaXHTj3HR+uPRc5rOqo6HEKXDAjuNMa8dctk2RImhqLZ3xLATGdRbZPS3ZXOCBqEZwZzwhJl7FZmZKpNFU2kao9fu33s3J3NKCpxmI2SsInPaFO2bkfl77G71xuuTPbimZV7FXeiiJ1rKG3RvgoQMeCHIhS2crkUFjyH0uZm/xJtvbktyS7kVc7x7RZ5laZ7uFYhSZzUcSIoY18eNGvWKkDYTOBxpZASTc4BGgjWNeBZTpMSZsiwItrRSl5ZxNXOR5tTGLWZIRexks1Smk3OUSKVAgAA2GBrhSQqqRg1zi0iM6Zl7GXVokBJSi/Gbf/7kmS9BVNLYkCIZh1yRcAISAQjXA4lkQTEmHyI9IBgwACMAEvVGDCoFFHOlrshrPIWUMC2wzVOSFj7Njz6NKOcNlu+m1rgnhT/8qS4MnxNfGfFQuZXMMnQS/zptc+eyfaYU2gAABcpLfXNZiX+y0WzpR7xzAhnNt8UcSqMkv9lTtujry1+pvjrStMhZKCaNR/Opy91G2t1H2dFRlMeZX8kA/q/wrxe/az9ScV0NhXsB0JP21nHf+Hqo3+pIVIiJ/iMdaAEkZyR0MIFPuvoVLMEcZ2sS1lMizOlb6ms3/o7vdCKLfHbMV1qpqirVADaMs+7O4Lq6jOi1z66p/wjeyoXTJL4il6wQCTSvEsPOJmdK5GSByLvpElaRXOu/L29JyuvfmvDpdRN/cM/0vMzP/k4U72a0odM/bdw+S1PLXBgZ+e3l4YILzVKbM+g1m4Qh7ulhGVL3NFReDAwN8ir5yYw4c1QJJDT9FMJ2rYKY8ZR/GIP5dSEEHPvz6l0636fC0Z3mTnDynJgtGPOM7rnSKUs6Vm3lD6eTf5a8EQKjyRQ42v/+5JkzQty0zdBKGM0ckqCmCgEYkRJUScCAYRVCToyIAAQDCBNYhzOV4dHd2ZEhl3sgQkqVaRoYUejuZhHiZ1DMfO0MTMgOZH7In1wiY6IOa03ii1OVHQrGDGaSPHKmCrJ3zcr2VTpO/XDN+SgKkNIYN1cQeRHlVNNTTcZpwz0BP5k9jLmizyUDrxcQtoh8OleTmL7H4QRYybfge1APQvHHECsZbv//2gMZu+vQCRNK2qzvX3nkaz46FwHrvnaO+vlZX/Yv9vzkU1SYoJYbhzNPSddRrhQDYFVVg1YEqPDMVnO6f+CJKgTElJTyPr6qzGleZZkWcUHtFIW9NbYQMw1mMeRuoQlPdqa7ykT0URgbEYrb/knVStlkqMLOx0K8hMUhdBjRE6qEeJTNJp1TGsNMn6kfhRzWy4zNlywJMZ9rgMccRCaQkvAbg1U0WuOpr6knksewgfhCR3ckdtEYZF265EvhfqNc299iJ09O1GAVzoc+kTHK3c+5WAo6lYt9Pff9xxqbGZsAYIuEUUzPUEo7j3M7LJTJS2MuNw5Iv+HPV3d//uSZO0PcrBlQIBlHxBeTKgABAMwDUWS/gMYVcl4riBUMZr5aRQ2pU4vGQXOeZzc02mY7myWsuZE6vrcoY2QQ4sPuY/3H92LBtSzx6WN7ECGYY+v3M35mpInDpJDImIn6dBw6f57nrMokBZi8grf8dRsuEu3nHJ5zFpK9Y8MRuLMQnoZQfjx9HjRcYgllchL0q3WzaMCNBUy1a3KRI5bYqD5JhgdWWexjdWMnjvb4gZDMZBj0tju4A+su3gsWLpJQ2I2EV52O3FwAJq54QeTJzQg2LAOkuHMtBw5yHXyFm8kd1LGcvd89QQmS0CKo6InPVjTNKH0v69hyR9khPuxJIsyKLf+GKNVeKbRKDPU4MySVyvl6UycqMfHw/N8iI7qKgPIyE07StaLzpVqdFELUEfUxGXfuqcgMtkzk/yXQo2MsVjdDClVIBX92bhepoMUnBqOmM9a7a0V9dNgVFxsK7M63iQqskEBRhmKJmoFH3Mw1rDJuUQX/tKAjyL91hoTNqJxP7Pcc+o5RluSxM0sn+2+Cqd4nPgTgdufXuvX+Z3xof/7kmTtj/LhYsAAZh2CW0y4EAzD4A31iwAEGHjJYLLgQBCMGFpIHRwtdOVph3WYsvwbmKr/ysjhYlvQAAFuTOSCnDAT1JCARxJFHo4+TDIomIogwONkiBDp5IpRJmRdTZAciEF/mX7IeVtamZLNL/Lt6JJzlmV9DsS/Pjl20QRsw/UhD+Z/cqsgJxerDhmOx4koS7OcnK1JSq4toJq6hm1Z4DUgDShBsUwNxUtw2bXOQ4eEpKDDjBQpG2pScxBkYaDpVVRFRkP0uRBVLUcu73WN+dTzoMoqE31ae2+AoSznxV/vf+CRDLljwzUsqwsTLi5y3cshmqYUDDT+Zn/8M77nk3il5KKlV4aYJjOansDD+TP1tPF47Ci49xWO3VXMKRqErLL/pYV4qsZORTw3/ARrSMVR65OWbtyR6OCIVcviJmI/I7G+vC++tS+UrzEoPI/PJ55+6m7nvp835yDnucdencxYUwdKTjDKbC7VUQaGnDgdxb8PEC7g4XSmsPFcPftmOQxFrWfgwvIYGSpP06XnV/tvSDM807H61Snv4PXfv+z/+5Jk7IFzimHAiMYV8E3q2DUEI45LoTcGoZh6CWCxIJQwjlHtVtcONmE0b7xpzIHZ5w5yjqwxkDwqMlS/rgtF9yLRSeOsc3+DRjO9Cr5EJZH1XzyI0qP8FGYxU1yxLkDJ5UwWR//LPJ6eJM5DDHYah3LuDKjccbTLm5ZLl9wJCLyz8QMQCjuAAgQSuGBkCMQZZWH09sMzX8LhqqhTULW0Mi1EOGdXPWfDBij86nNIrmZqq1jQmcr1f7hPrszRSRL+YuiQUS/O0vezTWuBI/K5v7TmBXlyt3UOiqGegtKUsY2XVDcodKkSZBZxWAxqGM+AresZfBGrSqFAQGEJ7P2Z+kaExhitVjQvDH9/OBfh+qhqFKFmAqGPplgQEdVFEqzX4R+zUp7ZMGP/1VemWeF+IeuoVGUtv78P2DH1RIrVmP4KZr8YcvDGdwbyVQAkIAA0scl8uuoY6hWbPR6lABCPb+wGHrz2hFRwel045UqkkMhpiMDY/8VZ+YyivhedBhTS/cq65RsV7pQX8rxdzcNKwprS3KonfLx5zv58L/t//+UW//uSZPED84div4DIN5BWixgADEPATVGK/QGYvMFmrx9AMo6Bk3/iwgBAAOaKRshNh8CQ7/VztYZbVdv6AVERaabAKHcHSbX/jAhBNcHB8rP/U8ur1aXxj2KMx8amsal/Gqxv2Or1e9UqpExa//1Gpa//s3D/4zrIex+v6wMl+bGxpQbqFMABBgmHrKsxw7CQYGcWpKiifwKiEaatJ5DRzkrZgismwtZ735dxz5Y60VCw2orGf2QzzIklxAE3if0ti+zLndwv00uhkC4QiFPiRArAHubCnkXpQtXU87q1J66GwQI7VslKGaUoTD80jADYIiEK47qAGGC0KZj3tNlU3GEEZVlALDEquVWPPWnYhUYuAGVzRI0oJHKCqJDIpkKIJmgrat2FTsqh6ljTtKqmV/H7fHzoJVihg+/oIZLEMOAfsDUElYwUHjNROMSEQECsymdTUKlM1lszciDjclNyqMxWMjNx4MtAwyGmzbLvNklkzc/D2/BPW0026ZTBxmNHJY0EXgMYASFzEYbAwwMNkczGeTM41MKIg3JMDs1uOZMAxv/7kkTqAZLQGzrBgkpCXWsHRSUDXst4fr0sZwAJhY5WIa5oCS8T4XOPeUo2APDI6LNLocOUZjg4GgDQLGUyMYjMA0MQCQxOFDA4nAgVDgeIAWHAgGgEvO6TGEwFNHcuu21x+KF22vv3bqSiN25iGIclnM6exyvG5fb/DDPVSkpMN55/nXp7fdYc/DCkDAnWD4PqOCAEDgfWD4fU4QAhD6wfP4IBjLg+/EDv5T3ggCEgH0bCKGpsYh5MS3/oeiGYnKusf5Tr80TpiRqK5rVL1dIVLFxv1+06fBJi+pw8i2sapfbmBCITCQVDAFAYAAAAAA/BCaFQGDCABmMHkeOxOGBsAgYIwAxmXkcm+BAFT4GA6BSNALnB42kaGQzR9AHA4GzAGy0ABvxdNUGqQoEAwUBY+gY6B4Gj4GsqJx2CDCBpAcvU4Hwp8BsAwAKED5HGpPitxZwLAcLCAxgBmUngY/If4uAiBfcuGoGTRGBnIjAYeAwW8BnwGFhF/TfTwMPAIGywMHh8AIditguYMf+g1b0MbwemMmFiYWbKgoAMACfP/tb/+5Jk7oAHOzgohXOAADajpcilvAFcnZUlueqAAAAANIMAAAA0a3kQJUQTQFAFUAoCByh5iz//2W//4uMBgEDPilycaw5ZJkEL7oAAAAAGs6UqWGUGXU0gqgmAgnMBApMSxoMlY6NBzTO5UhM/ClMTAlMFgdEQDAUBDFAS4qpWUsFgK9KotdmIe4l6YIOcykIRjHllHnjmoLois5itLD8WlkzGaG7Rym7DUEmKHBgJ1qOVy1wTIIEErkxmW8uZ49/trc1RkwWHZbhl+qWUgwUtaCp3e8su2tX5IiTY5j3HHHuu1CABIsO5c5navsqs3u8////q81eVknscf+y2CWds///////9Djmp1S3sXpudtfds8w///9bxxuzcySB0qkJGdUGiPTX4ABrrLGyPG5RIBCFQAzA5AeMAwAMwJgOTCdIYNasMs1whFTBHARAQECBJnCmrkMGcyGaZ0YrLrUpvYPFGhkSMxzyUPgpb5702RMc6zeEOVKJdYiU1FqbtZ9IBbkYymCQo28ptSppBmqYPJ0ndWAOfl+9fjhOMbJlC3alX//uSZKwG9uFgTr93QAAAAA0g4AABGQl/MQ9ukcAAADSAAAAEdYZPQBToaCJfK6Cz3XatsvBqQBQc4anz3XWQ4EKAN8XdanKhuA4GcSNG+klpBIgOY6R0pF4gQmJsl/+g4ZwbpqGqIZt//rNBLyEGNVUwAAAAprrYmbswEYCRgGATmCsB8iGYGABhh7lvnDCJocaaRhiFARJTjwdDCMgEWo1uHY1LJZBlPMa1KmVN2BolNLyYLgBMIhGBrnqGIg5GpTMxWXTF6vQdq6hpnzqiAAmK1CBhKzqU33qLADMJt0LAxtX6aSgj+YohCDAuVLpaMEykiRYWaBnYIIoonIio3B1PUZk4gIRgHUhpnHNfZMtAGhApALaT6pHAmWIitTbb6ygCZwHCFydMEAQhw+qSP/6ZEwkKPmTlAKDT3//zIOGFxAuaTx7IGJvIYAIGIkDqChuDA1AUBoNhgjsymfCRUcXD4ZhdgBGA8Ayv1xWZL5W88sFQTNzkxEfwp4YUzCwChilCDjoCBgEAAgwDEweyPQIAi3aGZVV1//+s6jY0CNA18//7kmSYj/aeX8rD3KNwAAANIAAAARmRfSgPbnkIAAA0gAAABFw3KHJzJ67LFrm+EhoAauqll2OX////bpUFyKw/Ws45dlCb5gkCDh+GJZDdfnfykMCjAKZUGRW1j3//LHJ9QSbiRbLuf/1FkA3471e9SXQBNgVgbsozNAgmLjQ//rJMJ0HplimBay3//3GdB0AzItUwAAAAqy59V1OSKgbGBYAwYdAIJgogWGCaFcYfDTZvfF9HBrU4YXgMgUBZa+AgcFQQntCl2M5lMBQRLZfO37EXXSYLAp/NMGDR2WqMHiY8VnDKoQLor2gWXWe7//5fkFlpwyBAa9gaAn1tSxwxACjIsUFkHDU7aZ/6ITUhWh3IxIqjSA1i4FOw2CgKaRqVMwHeSQIAAGuGjgTQ9Szg3QQYxAcsJq6ywBikw0l+1SuiJyCkw+yiPLoYhBw88//6x6CE4ONzoNAA4Vf//cWYCxkFA5WYkDGtAcEKpq/CgFRgCArmASAwYKIEBieBmnTQCebB1SJhhgUmAMAAk+VQECYBqGYacV12tT87Lb9jG1P/+5Jkhwf2lmBJw9yjcAAADSAAAAEZvX8pD3JzwAAANIAAAASu0iKfEJxhoZKViwEPEn4FLVyntk9Fbw1v/1dbEk85KQplkijR1b6d7WSlMrs0wOFC9LvS21jl////sdEZMrP/9UFSbTcEaQS8huniljvNVZ6HkJxjUBvNZy5///cJeAA+NEuWZ4f+XANryWf3qQ0iiBVYL5KzOYmYIDBtSL//rHoEpCrSRESC1tX//1hhgcALfFogAAAA3eSrQ0ZWYAQChgYgLGFWBmEAQGAaB6YbSkxvfCmmX/a4YFAChgQALp2F6I5TTVxr3yipKJylrVYlDJgMOHfXSYhCY0CRUQnCu2ZdBazXfpKfDPPn/ng+7R4FSXMXLEHEN/N07+JhmeDmZIAsNVcl/5RBNaCNCf2KR4tiyAdHBbQNMmxeEcuyZIEgEQYGXFDJoL+kiQYAA8BaUVXbok8AEkdv1NpIhAhBg42Z0C+EiRBF//1kuDUoKlQIEDh7///WDQAMqIxKxIGVJInVXEzUMBfMOkBIwQgGzAsCXMG1pwyTy8zCPtrM//uSZHWH9lNfykPco3QAAA0gAAABGTWBKQ92rcAAADSAAAAEAgJUCgiCoUkQCCIAV7QYzaLUdNa/uFWtHWfCALzNhRAMGqFRVCowOk4qg0+7tTNbeud/95PqtlryGRiEUAKE5ps9SQ2KAgIUOMCwJVih2mNUm/RCAZgwkPrJQxJQS8B6JC/pYNCSNmdZwxJ0SiAceBomzP1qOkYCAnBtxipfk4CgnLT/z2qDUUh7qqygfC+QaYfb/9ZJBIJDDoChwoBjf//6w0YSmFzx9hQAAAh266TAY8FhJjRpz0xkB5pGJhclKGxSFmZFDxCWxdRAUuiBViQiPw/BEvorVnHW6kFlQBYwBg4xUCBAKIAGTC7EhFgMV7Q7TWcv9SY+BWExcgGvbAsoHs9NhwgcN+BnQQpUnkUkf6gmdBFNP845oOeBjhoLNyIGA+zvYrkSDRgbol5f9MmAHnAUGG6D9RkBIKk39usJFRY0M4YBi8UV//6y2EwQ26hLx3P//9YlQZUPdIAADV1uCwbwMGMAgBkwNgNhQAUFAoGHyRKbyIOxpawJmP/7kmRqg/WeX0ujXqJwAAANIAAAARYRfy0Pco3QAAA0gAAABDUByGALpwojMKfiNQ9nH41nR4YbwrvoMgk2G7BUVq2F6jkgUDkEx17p2/zv///y1NPymSCU6pjKrNPDCJ5jxKkRVq3+f+EVYOsH+pRRGeAIvAMBjFyKovUdOHyLBSsNpn+zmgN1wowPt8wAwoQ1/28GhEFBaD0y4EhJfV//WWwmEG0yhLRYF///jqBwMQDNqjQAACR/YEeecIQAxoAkWCsCAEgaBQYFJc5j8ibGbAgcYIYBwIAZLeKncBrEN1rOcvuax//wtogHUJpgQI/7CDg64SHH7nM8O////6oXppoeCDQmFpDfwutkMOWFku9S5I/6wheFMv1IJlwAWAKEL6ZQV54uiWh7C1f1FEEMRBqv1hZKn/+kKFDS+dYckbbf/1nw8hJZRFQb//8viTEEY4AABgY5P6y6lFRAYMOYFBQYxq4xOp07kPg/108w2BMeAtXD7yqGKKilHe4WMP/naSFAZgkL3MHAFMDj7SrlV3W9f9zAoFYXQAMoN8M6BfH/+5JkdwP09F/NI9ubcAAADSAAAAES5X80jXaJwAAANIAAAATMA1IYCyYiqS/+sGpEKFX6kUiGgGpQtZSmSupNZDAWMlp/6iyCRMT+h+oLVIf/pkQC43WsRgNpv/6z4eQhWmAqLf//j+MUfLVdAACw8ybCvqDUXU/AodE42iMUhbPDAwPEFkDiKkEZbV30c1Quk77+w1lV/X9xrP6Y3A4ki8y8jDIikmrtNjl//mRKF0gIGDLhzTZkzAa4FHocoapN/4QBQ0z1UDMBYaH3NEDNfubDWELpf9MXKIu36xI//8XgmvpisIf/9xWCXyUKv//8lUiLMKAAAGP+VvpTjgCI/AIT2giEBzDJrDtIlT3MeTDYAVTrPlG6Sc/Ognec5n+7WKix4aYyCay+p9WpQMcadtc7/1GZKsQ8DR0LWzR7FsDpwBgJPIpf9QROFxfVRJoBDA0I8oxX1oMUwUMfb/SBvQSZv4hAr/+HUGF1OQIlv/9bisEnkoX///4/oEIyOAAAjHfnoTbR1SzH5i9IUXBL8GK5dniBZmGYDs4ZO8sAtvCX//uSZJsD9EVfzqMdonAAAA0gAAABESF/OI7qbUAAADSAAAAEde2ms03ZzRKQeUDJVgTAlwWeB3p4FhY4Tdn/0TE2HUAsqFLIugZjoAxKILjv/+EQohr/WUAKlBkE00FexqNUNsX/rUEwhFP5mIXb/+HeNn1R1kj//rcXRL5kQv//8lSEJMYAAAg626S8Y8jIAQATAzAUMAQAMwGgHzBnHoM/sJk0fylhoK0SAmEgh0GmSSzlnOa3jnZ1dqSUkBDPI0tw1IqgBoPckZT1t63////ugfCzGRY6KBGT3s8FsmAsaikO2sX/1BLIZh+pnKoGM4OSV1lg51G7joAk0uP/c8DeYKATb6IYkf/fwmQWxe6AcMn//9ZsHeGLmYk3//8oiYDmI0xBTUUzLjEwMFVVVVVVVVVVIAAAAObgBn76CMCEwAACzAgAoQ7mAQAEYaIy5tdgrGs0qKYS4FYGBMYI1p2n9ltJGJ/C3q1zeFd9BGETcK0MLgBLkKBUzTZzDQBWNGabHX////KevLVFQIh1T0GOcsZ2HJgBE1/qXJH/UELMKP/7kmTRA/QqX06jPaJAAAANIAAAARPVfzSPbm3AAAA0gAAABDW6llAWsClkNVlA0J9NtZsTwhEAUzMkX/SLoCSIOOltvUXQUFlp/79EEIgKAHzp4TaIu3/9ZWDPBNahWRPy///yYDSR8uh9uWQ+7gqAMBgNTCeACMCEAIQgsGDOmKZ6ZAxrcuZGEUCIAQGSzxgUAlwH2lEOwc/16V5XuczpIfLYHRjaYUDqIwFBRxZ5DR6SRh6W2uf//+9QSo7GlNjHBIEh88tHLH3S0MKrIMG7zTuTP/WE34UCN0J4kwCmgKOiQMB/KKtMqEsGdgZEATaH6zg/g1ejGmS/UbAMFSv/V6IfkCyB2nTMMICHN//WWwmGDgqhFSIL///EsDMh8yZMQU1FMAAQAMcpa16HS5ZgSAEGEwA6YEYDBgWguGEUk2aNAwxoeQumC6BGYHQA6T7OYjBNFVpo1l93+dvW5AjkdPDJgUPNFL4HJTgRIVKODqO93DX/+s4g2CeZAYlOwcII3husqqZHQ5gkEMFjVKkj/WEL8Lk9VAsimBBmFAFNMtP/+5Jk9Yf1k1/Lw9yjdAAADSAAAAEW8X8sr3KN0AAANIAAAAQ+o1J0QqAxUJ02b9AjwFkYLIzRNDrKAGHBGH9XmIhcKHXaxfCIgyX//OlsIQQZVlC9DTP//1hkgnEQ10ExrPCz5sIiASIAIDAwBHMB8CAwRQRjEiHPORATQyK58jA0BiGgIUb15MbWSyJusxN0krqX+42pa/QIAZ05hAwMwGSBU2ltzEIFWpD9Jnhn3n/+MaZ84ooATEqbBw5h6dl7+F5zMR7CDrKt6/5ZCGSF2Ns5obkQAz4wEVAd5NjULC9Akx3BMEBgBJMLV90SeAwQIKQi07emBgh51veptJEEIsHHUmcoODewdh//50rBIMDgbOTgUEt//9YaMLnC5ZWUTEEUAAAAbwZWl4+5UAAMA0A4wdQJSsAowCwOzCmOWNogbkwS4uzAJBxMAYAxzEACmc3O0cosW+1O45VZU3ELhg1y82WI/A0NGMNoYJB0BxKZrb1//+7kFqP3HfMgCUaKbyT9JEyoADAjAAQDadLbSKX8xCUMXC3SRKQf0A2+Fipx//uSZP2L9cVfy0Pco3AAAA0gAAABGC1/Kq9yjcgAADSAAAAEieSapaReFJAtbHo8/1HR9AkwCzRir1mACSRh9ttSwhKhoKs4cDCYhqX/86VgmEDg2WKYHZ///WJUHBiClJAAKfeg9aj9goAUmBqGhgjAmAHMBAH8GrbGCGOqZqk9BgRgGCMBUBAwIEKzAYAUREvm+a7SOFF+6u3JK2QqCcEzwAhgWAJggLnI7eZeA6lz+y6zlz//+dnKrrEIAKi4T+jta9L2rGaxuYrBS6Y1SpI/4QzSSPdllwQnAyzMCU8cBMDPlNCzkgOEJBQIjiKqX9SY+AF2wIhhfQT6oSNmv321LCaEm0NMuBCPLKv/50kgaBgu+sOETKv//xrBQmIiqkAABljDTgsCRcMBkC8wvQUjBGA1MHIJ0xO1XDmNKtNz+5Uw0gIzA5AkMBgD0wBABVqJXv+0ONxvut0WNSbgBMsGC44pfQAPWtCwWPmAcMixcVcUmo72e//errRiUAOyr0ziSx5GsehEPsoCoNMpQ8rKUCz17vP////rlgyo/4fvV//7kmT+g/XhX8sj3KNwAAANIAAAARftfysPco3QAAA0gAAABGpEWRGFkgDiNGcnZlN/m7lcmRmQLnRND7P7Hy0AoOBa4SZ5/I4Aw8gv2z2pYQNQUHoLQI8tAOChcc8//5ZIUISgMFqRDdAoDNv//oEPCiINuPkAAh+5h44AJAJwsAiYEAGBKAGBgRDDtFnN+cJA1xm3DBDBEDAGF6Qlg1BCqCVSqmprXfzqRuMBcGnIVUAQQygcARuWhGMgIyeap8M8P///CJvXFWFmFkWEAuMV7kyvIxspAIB1rQ7TIpN+dBo7DgvWaF8ZQDHwAJMCDl8cgwfYrkGDBwCQ5gir60iZAXTgWGmzeoxAwIsq/7dwgFhQfzqwyAIGb/+dJ4IQgZpljqCgJ///qFrC7g5ppTAAAACzm+i52UAEBwwNgDzDKAeKwHzACB0MLVgM1iSCjlJctAQ1CsYgAUHCOosztTd9GcTr/xutGLV63JnbMAACNvgvIgASBHA9MHI7CoKppOXNXdb///eUAqoteL3GHxOBAlNrIoo75cAx3FgBEs/tNin/+5Jk/4P2lV/Jq9ykcAAADSAAAAEXIX8tD3KNwAAANIAAAAR/sCVcKC22c1JoTaBlcYDFUkjoxxSZ1GZcLgW7APBEmedvWcGfBKiGCziaHmQGUEFZv1o8pBfEFmfYvhASJpH/+WSJBEYDBLMLWCwZP//6gz8TIMFmgEY/LXWckLgPmBIAYYXgEJgWgNGByDoYSyu5ovEkHGYfUYc4JhgQAVmKwQkK0mH5lxbjhY3ZbzO1ZlzDQCADvJ9C4XRGMAhw3hrjHYKQCu1KabH///1XeBWSu8hkkpCxEeeWRt9BUDjDnMOARksWspM/7g1jgoTb1kwHtgYzOAwfHMLhAzNnpEiOECgUDKBhwpI/oE2AALBZ2VE0PYBRWX/66rF4RwCipdZgbghAB2H//nSsEQwOH1B/SDI///UGvFaBjQquIABQAKW5BLdm4jIKxgDAWGC0C6YFIDhgvgaGLYXKdwQfR2siVmHkCgDQLjCoDTsUYTgae1h6Yk+z90nZ6rKoZGQACBWd4ohgAZKIAIUnyVKHR0oC6iEinb+Gv/+8i0FLpEQH//uSZPiL9kNfykPdo3AAAA0gAAABGLGBKw9yjcAAADSAAAAEMAvEEAF9qWekzQzSiQMeB1H53ZcXUkfqLINNILL0FrUYqJ0QmA1EoCXIeCgLSRqTJmBEyuFtAN0FHYbt6KRiOUBgGQEpxEUvYh4MPD03609FICiIFGTJLKRwG6YLATZv/yyS4QjAUPFpQZKHYR///CIUNADulRAH6lbgNzEQB5gFgLGDKBegoYDIFphlGdG2AKab/BJphrgGgoCweC5dBc7Incpe14zew7vV2SMJGQ8Zrg5gsItNAIDOCQMBJ9bkbnLeGe//93HxUbjTXgMiCYnvlPyx/0BBj1JFBio+d/6YJOQWVmmo6gUxLAE5AbwEXL5OIPolYiQe0AM3Hci/1HR+Bo6GMMVfPAFEjz/35wGhgOOR3NAmJKKX/86fCQAFgZrLoaQ3//1CeQWAB8yNQAAGV6LOY+ZgCAdBASZiEgAGB8A2YCQS4684ZCRWJ1ZtZGG8AmWAUCIUC0RZhhLpM9fh3p534vRduzEBrIEIdmRbNLoRWLAeGU8/GFQML//7kmTwg/bKX8nD3KNwAAANIAAAARcNfyyvco3QAAA0gAAABJgibqV8Od/uFt/HobYhAYwfPAwKAR25ibgwdAcxLRMVBRK13pabIpflMErYO3ktsZlorCdQNqbCoEaZNisEojYzHYO0EIcDXjhY0F/QMxyAMS+BSgRM0TT0C+BkCpJt7596ykEDYXAnUUyqCQ0Ljnv/5ZJMGgwHHnTF4CxVn//9ywCxwFgpqIAAACMsXCcGGiAjMRCTgSgyITM2UzC1PeNlEZ82YmATBlBJMAUBoCgBp6SlnsCZYW8of1ruFeUO2FAEDDuDXEQAyQoIAVMI0akGAJuE/tNVy/1IjqEiHNDLoG1tgSejiKpXIgIDgdQWAFVGaLqSP+YhNmCj816zEsCsgU1iEZMGhXdtRqVQ9kBiYVTZvskaAGhQcxKzP5gAaOv/foBCYC1hPOoiEAeJv/503CYAKA6xQgpVL//6xQgXaJmfIAAQAMrscbuzxQwcApMBAEgGAGmB4AOYjYhZx4hWG0fCwYZAJBgcgBFUHCwTUgo01OQSmHb3Zr+9vT//+5Bk5oP2rV/Jq92jdAAADSAAAAEXjX8sjfqJwAAANIAAAAQCFlztp+MDi9QIwCHjnzsMugBIF1ora53f/+6kBqPzjKzIRxCCm6kbjD7jACMFtoIIbjS20i/9YQOwpXP8xc0GmAFBB1sdhMDXLKtAiZBgwwGMFkwtXqWcH8EL8CwEvL9SAIDJ/71JdgKiAcgTZ2NwQECaR//nS2EQgUFqOh1hP5t//9YbgQIGXDAAAABzN3Fzv4CQDzAkABMIwBAmAnEAJBgyoumoOL0Z7kMY6BWYBoAZgsFhAHV3DkTht/4bjd/lJa5lZiyOJ1IHGFhEpmgkOTqgmOKB8CT9jPD///ylMEuMjMYMSAOBz+01m010yadzD4EYLGqVJH+oIF4UjPqOqKIvgHYguaMXJ1F6lpF4coC1sejV/rQI8By0FBZcTQ8pAgIKb2q8xGWCiR2TMDcG9hAj//zpbDDAwHRH0Gnn///w4RDxLXU0AAAAxtPK3zaioAwGBEMMABkwOQJDA/B2MHhZEz1imDIbnGMAgEAwHAHwSDkOqzW5LW1axlP/+5Jk3AP2IF9Kw9yjcAAADSAAAAEXsX8sj3KNwAAANIAAAAQZs2c8saZ9QKEDrq9MKgtA0KhE15wzGYFUOfepXwz7//q69CfkpaYZPCw8TXPikbdgLgMyciRY+1M9f9wgXgpjfYzNDcZgDPrARTBxk2OgsL3JAgoQAQEjCypf3YnwuwGISWdvLIBI8iP3qbmIJgQUSn2lhQXTDeTZv/yyWwmACg5mGfBwY///9YboPGGrj5gGOoBZ83UKgEGAYA8YIwIpgHgTGByBkYfxOZxWBPGDzQ6YEYHIXASMKgtHiW0kIh+IWKe/KN5brTLCCQQm3o0YYBY0DiQSGUPYBQYjy1iU1t6///uEvp35Q6mAl2gHj1DMR9DoYebgBBa1odtIpN+dBq1B3J9Z1EpCMQMLtBsSTyJFjJGs4ZmJBAW0jePs/pGJNALNgULE6l61gYoMl/U2ooghLgwMbblwIRpOpf/zpbCQIHC2UHfDjn///EqBgELeVDAAIADeom0huavDATAYMFUDUYAEBQI5hsF4G4wFyZwETBgqggGBcA2VQAiy//uSZNoH9ilfysPco3AAAA0gAAABGFl/Kw9yjcAAADSAAAAE1OA4Km8K1Ndw7zV2gkZKFDB8LLAkRNBARN6yUOJq9mWy6zlz//96glR1/lhjHRMEh88tHORdvDLITMVgJyabFJH+dCKUFs6udWXBZ4GQfgWbkELg6zrbFsiQQgAFwJeRV9SyYBNsHKGaC/RAOHk5/tzEJGRBqqjM8Deoh7f/zpuG6BgNNQf0ZhH//8+FAYdObCAAAJjLCB2SQsUAMJgPigVswKAAzAcBXJFDDHKJzNMl6kwbgawCBcAgumquouUnKyJo6tjhwxD9j94TcACEMmqXoARmwpxzlA7HkkrTCqK/zPf/+s4g0SjZgYpPgYKIflkrfQZAJihahhIitrj/6QJHwUzdRRUYjHAYiQBJUaqIaYpVLMEBc4LViFZ/s5cAFCA5QV2f0goQIm39udCE2LjVUdOiOA7Tf/zp8OEFBTqFChwDf//ihwtKEoFSEAAAMGWMNOzDQWAZMBMAUwbQHjAUAHMCYDMwnTgjUhEDNShfAMC3YeLAZsVipO19Xv/7kmTVA/XnX8tD3KNwAAANIAAAARd9fyyPco3AAAA0gAAABLNq/z/zwjYUARvhKmEgoUAMGAA2HKjEQKXXGKfDPD///xlTxPyqqYTOYcEY1S5UqwRjJAGBgKy6W2kUv8ISILV25mgZjkAYGEBIgRcvkwYPuWiRDBoAQQupfrSI0BcyCxU2b7AMCi0/9usEh4aWrZMJAieX//OnxEgoGeXA0xv//xExMhdnjAAQ1dgho7YB0IKHRiEACZtAph+g8m+2AqbqKoYcLK5BegmALV7Kl50lNbpflXP7y3DhZ8xSwMA4DcMANCwCYqN6IgAVho7QXdb9Zwa4ipwd4G+TgiljQJ8nBzwxAB17ACmonUl/9QJEQW5NzNEvDKgZNmCjktnSHFJGtAvmwmwBSSVHb6zg+QaOxyzi/wMMFJP+tukEAUFj7ZgkFqg7D//zpsGSA4dWJAH1b//6gydQgMeqMAAAAPzhxx38EYFYGAxMI4AwMAuJQRDCDRhNV0b43fjEjCNAMMAACUSEYJAK61+OM7kOUljeud529Fi5J04qGDgivcz/+5Jk14P1ul/Lo9yjcAAADSAAAAEWYX8tDXqJwAAANIAAAAQOGDa1kMXghbr/S21j////2iqv0jsMJ5VKO0E3BCf4XX4GAjJZdZSR/mQSEhTm3OrKAocDAXQGiZBC4RdNtErEGDFwGZAk8il+gXwDDoLIyom3WWACRhp/WvuOEKJ2zhkI7DzP//OnxFAoPrDyHVf//hkojQRqWhQAMNPI0KcEYCw8BICg9TATAEMAsEYwMDxzI4FmNgkIsDBwhQBNtH3dCBX7h2U0tLS1c+ZY1paIQI8mPAIg0lACeyVhyi1eK2r3ef//rckaNKXdMtDR4xhVFbnHWM8IgESuNS5I/6YYcKSm510SJAYoYDkxUMCNOq0zQ1EvAUPE+39EvAIABQsav8zAoHb/9w3AUFdzALbk6r/+dcUwM1WNYUf//+OkPCKO1Z2gmXSTdC4FJgMAiGEkDyYHYIBhCg4GOYi6eNhBR7PJMiRZYCA4AQMwKA0e5t07nl+N2pilywqyqIqHBYbm1uAOk94QuGz2HxMng0mDqv4pL7GeeH8zpHDYW2pC//uSZOEH9dhfy0Pco3AAAA0gAAABFU1/MI9ujcAAADSAAAAECTH0HARHZQ+7sMDBgYMzyAoWTzUV/nf////koWCZE77371BsxBaSghYRbh95fAli/zdaKtdEQHMkBJvbWPed5jlMqdDBuLtSnW/4kisElhPfas30UgHNAJNkXQIeTgDjILA0P/5Kk+EgwUhMiTwUZu3//qIKCjQGwYYpCgAANDem5qqPuKASGAOAQYIYEK5DAJAbMLInI2eAozYtQcMGIAou8XxdXC9Znq01Zr5Yb1doIZKoSMeOswEAEsyQIGN70h5D8qu63r///yiLPYeYEYkMQQGn5pqtZhJitJiEBMll1lJH+sSsHXzfmbHyQByMFmhEzMfBxegVysHcAGEkQT/rIwCqAFBhuh6jEBcOv/fW4RJC3I506K0EDIv/+dTFOBgGofIh3//7jcDSR8uqQAAG7EjdRxwoA+YGIAAGHLMDgBcwDAjzBYaiMxItE4YIARITYRAjBcAweAdDgGwwA9BxpbZJNSPxQz2V2pH1DhGD5pilxg2CwOBUwKB0zf/7kmTtA/a5YEkD3KTwAAANIAAAARZhfy6Pco3AAAA0gAAABNgsxGAtIZ2Y1S5f+9b1Xbom1E2sGKo3Dw6OvFIfawXXMchBMUgHd6lyx1////+bgixZSLv7obskUTC5Hl7aCxFsr36u2ieDkgCvY0jV29nLQKAwdVJc8/mQGMJF5vbP6y4DVYHSL0SHgkSFiS//lk3DDAwimcETIMn//9YQAgWAhkY3EAAAJGsWvLlhos4YD4CJhFgVGBEAuYGwLJhNodGraKeaubwg8IiYJ4AgkPVYnNoozGrNNEqTuPcM6Ro4ECB0BFmGA+oMAgEceUgOQyvYGltrnf///kuiTiqGmBUyibEpmYp0EAXXwKEbjS20i/+PwO/G3MUzQiYGcMgo/IgXB9lNWmVCIhCBAFDHVfrSI0Cq0FBJeR+sAYGj/vzgQkgoETrMC+CYAT4j//LJ8S4GCahfiDP//1hwi6INP0BABWuxx8XwEa4ouBejEVPQcw8QODgxCzM06FcEAVhUBwSA5RSa7G5BIrNJNzOv52xPvwn0DivwCA1CQAAAYjr/+5Jk5oP2kF/KK92kdAAADSAAAAEXXX8sj3KNwAAANIAAAAQYQcEIxeQUd7uHrODdDukWGSALGAtKGyWy0RMPVA5t8DLhhOpFi6kj/MBGAO/IaiykURIgCMgDAoxcnUXrOHS6NEEVQbJ9vrUPsEDELSy4mrrMwUGFv+p+YAmCBYwb1lg4J3DeX//nXEQBge5MheTf//WIkIPD7lZhCAABBrb+LvawvMwDgCTB0ASFgHhACEYTJ2pp9jiGOe8oYGAJCN4GCxc9TKONflb2V4zBGP/zKy7QWAJwg+F9WaBcJmerKYTA7AJupnhn///50kciysxgtBBgAhuUSuKKHmODiPEnXf/5SDqBTG3OoF8gAGPVAosImXyGHH2K5JBowNQZxf9j4BgEKHy07eUQJCio/6vRHGDiqWkYBCFHar/+dTGoFAbrGcDgW///F8HOEoOqQAAGN+deZ5QgAoFA+GHEAaYGYCxgYhAGCMz6ZchGBjM27mBwBqHAOP+NAYwktqzW5EHvgyZ+5jWpYk4IXCg0TTEcANMYwBDgyYjIw3BpALBU//uSZN8D9cRgSys+onQAAA0gAAABFnV/Lo9yjcAAADSAAAAEprY6///VV4k7muoJTFEgQ4cWnRmVQSQgMYYHYMgSlc/MuNUm/MgaCAVV3eUzEmg/UDJ8wGlpEjEcommdR0uFgVMEY4hTzt0UjEgwBjQFGxOpfOgZIKV2/U2kwJkwWYoMozLQIBon9v/5ZNw7wORKOhnguVD//6yaBEbDynlisAAAjeTkrSUpjAMAKMEACUwDwDDArAmMLIjE1ihFjLGZ0MDsCowIgC0ESeKwU3FrNyUyzD/y3coWxEoWYVlCoYv0CBJ5eGGKK7oFtY9////wib43nTMgSxIXilPSS9nAOggcfPzTYq/4RCBSm/OpmA5YGAZgiJk4YE2ZtuWi0HVBuQYpfqWYBNIOYmr6gDQBp/t1g1EhtPOrIgKk3/8641guPWL4WN///x9hvQuZCjAAIADOo8awDSyEDAwBQIDBlA/AAAhgRgimI8Z8c5gzJsF0GmGUCCIwDjAAVQUgdibXK9FnO4d5u5NwAvsYFxsysmABfEB4DnmEaEN9Lnsmv//7kmTng/ZzYEor3aN0AAANIAAAARXlfzCPbo3AAAA0gAAABHs9//8yhlurEhCBDFTCMFgByY9H3QEYJMSPkOJjJZdZSb+wJHALokNIomxdFzAZqkBKsPJwZ0opVmBPl4OQAK8kQPt9kyAACogRTCTQTXqI8AQ6gae+eaoshCzFhNl0S+CQ4T8a//yyZB+QURMw1gYJP///UGfhaUFjpLOQACn8i7TH/CgA4OA+AQi4OAlBgKJgpImGU0LSaxi8xQH0VgKII1YUD2VLhXZDMWq0f/+eFO7AhBpvNQDoEdgkCBq+eGIgA1uWZ4Z4epY+BLjotgG1DA5iQp4+aizgN1sAxQUTsTpsil/OAkMClo9qOqMxXACZQEhBNl8mEH0S2QYNSAGLkSRS/SLoC4sFjpWb8JijRP+3KYSJiTqzA3CEAMD//OpD4CgdlDrDgn//+oO+WxG7VTAAEADLGNOC7QwAgYDICJhLgVGBMBGYGwMphbo6GoSO6bnabphRAShgPRCCQcDochDg5VpdrOvrvL85A6QB0wepMJciALg3ehYJsOj/+5Jk54P2aWBKQ9yjcAAADSAAAAEWoX8vD3KNUAAANIAAAASNarrf///yX5vyrKFkukPJJuUPuhMMkmYIOVLrf/KQJHApyR5mibEBAy6MFHpJmY+iw2mVDwamANGIm361EqDVuJxMl/KIESazb325KhAPBQWhnEhcYeF//5ZTGoDA7qEjEAv//1B3ROAasNU4gAGV1sibrYiAD0VAbMAsD4wBAFTA0ATMRUMw5PwIzhkOcMLsA4MAAKAmvZszTY1MzUprTN/ufbM8/JbY7qZwSGQuAgCJjhGEMmhxPl+pbax7//+7j0ptuUoEZIJgkXnVl0zJCwAzB7jMAARasPUqSL/lgIUwO/PrOmZQETAM8hcORQuE+mz0iqREMggaIANE2R+tAh4BjEERsnE0OsyAAJE99q0emCAGDlzOyRcBqLGRS//llMawUPOoO6Mgj//+IiFAIuzTBRQAAABrbgKBugIxhkCJ6jwkHMU0MJ8281LRZDb1B9MIgBoWBDVGWvZx8XjG6ftS5nrHKljSRph0BXBQBS8W9MQEAEiB5hUhnr3e//uSZOUH9cVfy0Pco3IAAA0gAAABGN1/Ko9yjcgAADSAAAAEfTIYNQrCMANPuAaQEHLhfJwaYHKIAFTRmi6kj/pBJACk7zFzxEgGDgUXEgYD+d6BXKwiAGOAkQT/sbhaIFE5af5iAEHb+v3GMBxNnmZoEAEW9v/51MjgoKx0hvDf//lEHABCZGzlZkTNTAHBFMFAA4xMgHzBbA0MFkMowkIkTIwNoPRZPMxcQajBaBTIgMxYCAwDQBIYLtOiy2IOtnDdLLa0y9STpVEAz9bswLCNTUhCc2qhkiSMWAhl8sp7GefP/KlcJN5TUKAOYknqYVAKw6AYIXmFgQMV08AxPttIbWPef///0I6KxMX1796ks1BqiwiMRDyJ24TZv8yqy4ZoMVAdEKLEVUm6KRiNYCGgCT4mUtnRSAGmEu3609EzAokBSUi6BHmofQGCTz//kqkIoFI9MVwHHTz//9SYzgOWgWEoqhAAACRjlEXCmSE0AAhyDpkRxp2BhNE1mrsIsar50xg8ADF8AwAhzXctv3u//a3efvU3BA6AWYD4ZCdLQv/7kmTkB/VyX8ujXqJwAAANIAAAARudfyQPdpHAAAA0gAAABBkBQwFxSgUAozOOXdb/1qI8Xpwd4GqPg5WPB9jIUiBp94NgQuEnkUm/wQGgcvbnZuSwGPCA44RMzIw50yoVQ6oNxGav6yMBNEGCE1fWCwY9/v1BAIEm60wwYO5v/51ywDANYvBPrf//i0CNRMz5AAAY3HTT0ZmVAAwCBIYI4IpAAMCgZzEeJ0OKYR83hHOTDRAVBQOBg0CmDAQnq/7YpFEqbcit034V5Q0sGBw3pAQsJi8JgQMm0+GYgAo8AmSxqly///+doqVxkdgItFEoJmJW7CCczIVQUbYeq5L/zgNXgUtntazpSEhAN5g2JLzE8k1ZxEmRZoDWQeTZvs5FABgwLPS2z9RTAKQldv761BNERZFSzA3BqKFsT//llyUBg9jod4i6v//rDXDRD1D9IAAAAPwZerA5ZgBARAIHYw1wBTAgAFGAYzBwZONKIgE2k6HAgJUwJAGAQAC06DK24+21FDkEv5L6TPOxL3ULvnmVwYVIqHIwSFjxCqMtgxD/+5Jk3QP1TV/MI16icAAADSAAAAEYAX8rD3KN0AAANIAAAAS17oTPXu7//1dbEh2f1XJlkYixpZtLZp6xwDFiBGFwKrFFbSKTfuDWUFMZ7cxNy4OMDPRQUvjgJgZ8pq2HsdwQhAFh5cWr1ImQ6QBW4KLSeR+YAY0YaJ/z+s4EKgFgC1LKCQtwMAH2//LLkMBZO5iIkCwNL//6wvAPfD2ySatZfpYsPDgBZgLgDmE6A8YFQD5gYAymE+lAaTI9Jm/QpkILKPRdNabzvrLIVEZ2i1l2/j2zIlwAdgGFA0ycuYcVeQseVJxSfsZ4f//+EreuQs/MOIkIC8Yp6SXuaZXJ5h8DMtl1Kkj/QCbgHOi/uYpGIkQGArASJE6kTJilUs4kQcHWxhM/1nB/Bo1FBmC/nQCBv+p+YA1FBQY+kYAmFFhS//llM4FBzsZgwC///4lQcGK2PkAABlVoJK2RDEwAQFzATA6AABpgYAImHeIob+YERj3xuGDMB4g+PAEiByCjNG5xi7R0VPMY7yxpn1BIAOjpUFENGkgCZnzRhgvfCV1L//uSZOcP9mpgSkPco3QAAA0gAAABFnV/LA9yjdAAADSAAAAEut///+URaK7yRxig4A4XP7NTb6IIzGSZJixRX+f84EXQMIm3OqL4rgGLhASWEHL46DB9yWHaGcgICGal/oF8AgqCysqJt1koCZJD7VeYCEQLJH0y4EAcW///LKzIGCcUOHOf//8mgcGDpUDAM67gLTaQCgBzAsAZMJ4DwHADmA0BcYfqbJwoitGVLdOYNAKJgYgXJ8JXvovuT1ZqxnWv2st1pmAhAF5pglBhACYCAYwFDIyoigKgMhSq6M02Ov7/6rt0Tap2AGKY5Bw0PPRWpkhAoxMOICAims/MuNUkf0ga1AWdktrWsmhZoGXwgNVSSOjlFJFSzAvpkIBcCNg+z9kkSLAAHgWjEi7eZgRQk396ldAG6YLPUmUWURBEM2z//kqovA5VUG5GaX//9Q1QoTC3ukAABjleo4OR3HgLAMJaYEoBRgKguGA8kCYTw+BmjOnGCWB8SgEwaxxgzvuHAkKjNBa33mt0DYyUUMt4RkeXaWRPpzQhRQel89Z7z//7kmTlh/W+X8sr3KNwAAANIAAAARj5fSkPdo3AAAA0gAAABP//5ajz8pkmDwaJsSoZiG1KDSxwHKUO1sVf6wmwCgJHsmYDlgYSSA0PIoXCbTbYtk8GpAYMCXkf1LI4Elwso6r6gECDb/bsCYUKAX0TMGgAWJv/52gFBTKGqJI3//1i1hxwggeMA5TLlW04JgBgcGBYBEYVQJ5gYgSGCuDYYkifp0BC/G7nbWNC2mAOBYgwEAiKMhZRFNV6e/jOfduRN0B0Vm0bsBSOVAAYPC57xtjS6HgYxaTT9jPet63caqSAOGl/BzkHkk0GXSVugyDQBLwcRFqxaybIv+YhPMCI+W7OYlYnRKQGqmAp2IQoC0kaktRmRAtB+YA4YbZo/1GZcABhASiETNE16kQMWVJF/fNNJECLUFCLs5ME+EJgRov/+SsY8HN2c1Bxg8///ohEGJmGDypVMAAQAN3ILZ42UQAAmACA4YEIHYjAKIgXjDkGUN64Fk2gGcjCRACDARA4dI0rZb6NSmMyDCPWs//Oo+4iBxwZemDAss8ZCxrfEGH/+5Jk5If1el/Lq9ujcAAADSAAAAEZ3X8nD3KNwAAANIAAAARAI+MYp8M8Of//nLI5AysxgtKF8IbqV7DTjJxqMLAda0ZpkUv5wIXwaEf6zhTFoATkBsQRcvk4g+kWiChjoASwiqSP2cmQbjCjEts/lIBQYW2/tzMInyZVnHGkHAv//LKBKhQvWLwOb///DvjYEBi0QB9iLtMfsLAcA4Fow1QCTAuALMA4HswYmJjWAKTOU9fMwvgIwwBYWFRfCw7gLUaw6ld+auXeZ4T78AkATbcdCIbggHQAEJhvJJgYDbCn1lVXLfef+qrxJ3NdQSmJo+hwwtOlMccMLAEYwlYLElP4Z/8yBrcDS+yctjIgakmC3EaZTF0Ry1LMCJkuEAADWByCJt6lmQvQF5YEhpeR9zgOXmr/zXlEIpwWJoZkXAQjQ+ps3/5KsJCDlU6GSDtV//+H4hawFvJIuhQAAABlyD0rYUFgHwcBuYQoBhgKAJmBICmYLaDRnvjEm1IVEPBzgEAB+UelLoBkEqrVqGm3n/O3p5WE48JjBgPSSAoQNpP4//uSZOQH9c9fy0Pco3AAAA0gAAABGNmBKQ92jcAAADSAAAAEBFpgsPUtrH///3hE2x3m5mJiqLCOKX8aBNswuoRgBNNl1lJv6AQthkm6kywKeENcVkwQLbtrNieD8gDmZJIv9ah9gUThe9BP6YDQk2b+3UEAMKB20zQIApE3//nWLIUFVinC3///yVDMiauhlMvE0VTogAaBIGJgfgtGA4BSYKQK5ivkNHPmEmdQoKwQUgYEYD4CPo8FgwEJ6Nq/9aHJuNTGdnKzTOyAQkdrb5hMfF+RYCnhwsPKkiATmyKiv8///mUZaKy4VAhiBhAIVOzNTb+JjgJ8GRgewaM0yKX84DW4ar3Y+VBZYA00KZhkCYF+SqlqTIgQUGoUDMjCBpL+7EXAUEg6mSB9utADHiB5/rWrPiFQc/QdApnhAUFg9//yVRF6FFdEWoFhb//+o3JgFigYoXUQAAAgfm+jA30EIF5gIAEmDUA8JAHmAYBIYVZuptWiXG7camYTIB4cAQYDAJVAb0QJLu4yuthYw1jlSvsFAeaceRIG3KEIXNzUkP/7kmTih/WRX8uj3KNwAAANIAAAARkJfyivco3QAAA0gAAABFFdWCL2M8M///1dehRqZa4ZDDREVIPs3ImmQYfXAYQ3ms5N/qCF4Is/pFkVgB2AR0YuVUX1IkVGVAaoDQNm+pEpALJgREjV/lMAQWZ/1+4bgFkTZimCAAI2b/+dRH8GC8dYaU///qcSANhGfcgDl+TN+4gXAoHgaSgdUwNwCjArCIMA9qkwXSqDknZ2MLIFQwOQOwKAA6B64JG9jvtAl8ESiMTu8qsebqVQ4MKlpMGgEQiAIVGC8oAECFlwZM3Luv//7hP23VIADCxrjAAwZdwtCgCmLJgmDYMJ0v1LTZFL84DWkDgifSUXxcgGlZApcGTJsWgoJ3QHsdwQCAMEPJxavqOjUBOkGMC+gn6ABp44/tWnomQJGgWVIqWYF8ICAoif/8lURPYORuoMnEAl///WEgQbCGAiuhAAACRjlALpRFDMxQg6SExpA06gwoCyTTqDuNPJSEFB7mBMAIpYgNcWlhyV5VqW3U1lvVeABCAeYS4WhZpRAGAHmE6I2ED/+5Jk5Af1sl/LI9yjcAAADSAAAAEZbX8pD3aNwAAANIAAAAQksqh2mxy/6iNFNIsK2A1CgFCxETI6TAXzA2z8CUkyWr/qBooBwD1LMhnQDYIKATZEvJNrUkOcDmZLs/6aADwQLEDdvUdCAKv/fpBIYMkvOJjiEkf/+dRHSFAWL0aDf//iXEHE4uYAAGNxsa+GfhYDAwCQJjAbBLBIDQOB/MTAY46LAEzXlngMHIDJCJBIm2gBbm4soca3KaDCbwwp4wreDAEeMaJiIYl2ksjxR+Encoa30Vnr3f//wzdBjEnTcMdqQHDh+71yCxQEGCoMYJA66n5pjVJv4QXAWavzA3JgZcDPXQFJ4uAigx5TQdnHgcIQCQSGFFJf0UiKgYNGFIpWZ/JQAgwl9s/rOBJULgXmRgBUWFyUv/5ZMRTwojuM6FBB7//8NGC7wRBys1U0AAAAz476wi709TApAOMM0BsIBNGQfTDEXyNc4uk0qKzzCPB3GQNgMBwsAGHpFx1l8N5RiWy+rO9sT7LSzZ78WAEVJIAAEHY7ABlwlnFJ+xnh//uSZOID9VtfzCNeonAAAA0gAAABGLmBKQ9yjcAAADSAAAAEr//8X2YUy0RAExerQUSXKlMxG1+meR6Y/BilsPUqSP9EE6wMOH2Z0DYmQ/YDMZgJOiqcHJKL1mBmsQEBGFGAfb1LOD+CdULhTBaupYGLHlX71JdQNUQLDF5mXAkRGTV//JUuh3QonrGMCg1v//xagcSC5hxAAAARljDzuxZUICA7MIUBAwGgBzAUBDMGFCQzLRSTFbfSMDoC4aAfEAAL1OFAsMztmmtb1a5j2zIyyJxAzFsVclUKmRrWCQC4Ezc3rf//71BbVdP+YuFpMM4OyuxBGcxEjSYgRW/x/+EKwFjD9SjMYwDDwAJDCLl8mDB9i2RIL9A2HOI/0CbAQZBQmaJ+twDghL/79gmACgx86wrUTJv/51hawcOZYpgn1D//9wvMU9IwAAAAwutiWBaMgjCoFZgsgoGBMA+YKwHZiblfHO6MOZa9xphGAthgG5goDoYBSPi/4cdCKxOH6aIUVmtSxpaIVBQ05SEdAUOCYwBCgzChwwrAxgsklNNj3//7kmToA/YuX8pD3KNwAAANIAAAARYpfy6Pco3AAAA0gAAABO//OzspcYZAIEGYpVANbdUdAAxeNgwEBVHJ3ZcapN/CCcDFidSzJZeGZAzssC10hTMZ4pI1GZOFwT2AN2GEzt7ok8BgBALTiRdusxAaZki/6ldhtA56fZzEzBAKDajX/+SpoHdByasNcJTV//9g/MKAg5JAYAAAEazcBTOIFgAMEAAmB0AkqMCALGESQuaUokRkaLFGByBczdIBYsJhEhpcsq929llvK7BQ4GmXVRKCMxTFO5gQxVl8VtY1KTv//7oGxUrsmRhpMKyLG5Tq2GZkQYdUsxVNzBRpp6gmYBxT1JmA6wFnIgGXFF9Nq3PFUWkBQATqqd+spAkYFLL6GmFpLq9+riVgwA6qCYcInLf9s6gP4ZXH4TV2//+KyNoWE0UwACAA/UgdeKAkAImA9HhHAMBcFQUDAJRpMUMVY0s2swUBoYDAA5QAO1dgiWj2SGLQDAD1QJvepXQPWOChtHGSBcAl1z8JcWgy+FqHKjcI7L8vw38Nw3IWFmLPoQH/+5Jk64P2Zl/KQ92jcAAADSAAAAEVmX8yj26NwAAANIAAAARvx+4IKoCSVoOGHFvvLIpLHZVY04ffuEpMTFuf77h284xiAgUGUglkG1dc5lbtM8CDGko/rXKvf/eAqSDQBbw/WKjApAHFNkUFqRTsknRBDIXaZorOGQsoTA2MGnGzFIxZcusKyFCnDMOCWZv//1B3yqIualAgAAAGGVdpSwvqyq2GDwAl0jAMHDDZVzhIljjqHAgVloorN6wWdpJQ6MAxp/7ue/q/WYWcdtHq1g1PxPBud2ejEMSqar/nY5NxGmlQEJL2otYUlMYwYjjKpRewqYZ4ZVs/0lIoxb1nr9V5IQjohjXw3nnrfTIewKs3NK1K9EbwjJvUqmiF1dNVlM9qFQYSipSGNZY69XVey7D6L63KyOpBv/r8ikAejA3//////////3f/oUpxkoqow9CDQJ4mAAWUr+YAABMACgIyID0ypAE8CXI8pkk6cmI7rocwqIAxFKUGAwMBcOEeZTACYxg8YlBeYMgobhgKQ0ESSnknAvdChQdcjS6CaqzV//uSZO2D5odfy8PblPAAAA0gAAABFQF/Pc7pscBoABkIAIm4DJFEzQNrj/veAHkSW/eyLxSjqcx/H//LUwxKbwr1LcMJDSy3htWW85jzAmAaUPVnKCsIAaAScNjzuroYIxfSjqinBCJP8wbHt/7OIrfHTP/+xhyoa3+31N46NUfB///AAAAIh///m8RETPc3NCcRRcQqf1z/4c92CJ///BcTQndyrxKBtFjP4BjAAAALhQzDUMw84qxhAMdMOuLrhABlBMMGHchBCyAVEpuwxxxgjPTopnx0W3Vhs03RI2iXD0vUw6/M/0zCt2v5h8zrteq0FYgpdSmKWWGehgomVjLrBwolvCj7gKl+arf/DDlRHSDchvr/nMhxO35f1R8oCUBJtKxv//q4lyOR3///XzCnZGTzeqSzcuG+g5fD2JiDGvf/+BjInJDJHjUGBpusZw371QwAgBYKCwWVOF4KbpMjCi4JZkYSWZNsENy0rKXis15TGQWjia6YaayqpsNkr1ZMm0s1DMvq2ULCxITBIWBpzyzWDXAVwdljxYCjXFcRdP/7kGTjAPUdXtJzuDtwLQu4MAAj5E7JgTMMMFFAwy6iQAEPkZJan8idHldYC1PYkNFRE8j+ssDWoAAOglCCAP/L3TnN9H6gi+xR5v/OrEruT/S6ti2imvuWHA0CsarkHJAQNMxEPcdXWoAIEtS0qNLBgqEMeEFCYQlMKyEopsYRr0hpTwOPFszPBZlKmP/TyABMVZLAUJNxmIoAIKLYibVFQmgUlKztLJavTfZsaar6PoiiAJhS6sxNSYiwyMzkwMW6n0diZhiUWDcgZCCQIqw3FWFsSwd1sOPszmFP6TpHOPWtIJcmxJy1eHAqgjYxIqZRjGj6uxpyYf9oWc/67n09Ec63nUlktn3XUzdJ1eel9zsjauFeTf56mQPDGeEXfjk4zVg8QjY9g59QM6be6G5J9VGfYtD+dSAGTh9dStJw4iETh6I6254dkdQWpu8yzbbN3c+PdY6KNDbyWL3ovQKMNr8S8m2GtaBROGYRJ1oPbaL71pddvt+mdlZSLuack+m0VBC0zH6JVQGKGMY2kdWgi1Pr0r493jmdclZuL7HWQ//7kmTlgoMUIEjA2EDgMMAIegAiXhFZgwatGHFJDhsggAGJ8b3XoV6YoTBwqhreJSJR1F+KDOZB5PjOunG+wwqF83lJPP8zh1yON3WqWveEx59IGjo3z6QMSatGpa+tJ1/b/m2J/RKbpgTSblr8RCX5NzFDuux/cupdIv+/JsAwLoLQ9Vs8eODUpk1o4XAWx/3esqyW1tdpK6ex6i9WiI1DfIz54lnlcPbk2pWEm5UfQzSMZpG45LMZ9ViNW2SLpRVgy9jMtDig6iitAnJ3PfYI01ETXnrQpAehDsRw3G8W9tvrNIwRwvwQyzmLRdN10e8ovnPNovFnNRxzOUppLNUpZVwavJ4UK404tX9+dBw4+Ig6AFqAoaDibCtbjvKhpZ0kRg0HUZWDT4KiJSzrEYKiURMniUGgaf5IOZYq8Nby0qdw0edqBpUlz3VmZukadu6IbKqzXRQJN2eupFasp+01SGptQyCx1TasbEj9nDY7NHnqtGxFm3KFEtWNOaxNRDGEH5K4qbY4YLqzKsNUCziq7Xg3DkVFGBQLxRKEr7mJqVr/+5Jk84nz8GTAiYYewkbH6BAAAwxRbZb+piTcQPCAHkABiXj9fMU1wdDxJK3XOurHWmM5H4uNefTzjEs78jRIksSZQSEHCkVBCfkwgSmChNBVGRnzy6RG9IxwgE46I4bYwwyPjUVi/PBeUX6jRkPPfQ///mUo7//+VPJqDs9BW+5hg5QdLHAACAASRGh2iWRlGOZRRIcPTY6TTTq2m/z/rLMbCmtKvjf8PRpq/yxJGSxJJO+O6r2R111VBLGEHvo60cpW6Uu7uqgylCiQqARl0///OMaxurGFH9jQMx4Zdm+5/S/YMsMmZgI4v/990Q+KLMSJ8XFEEOK4tSd33BL07bWUzUanNyJr/pIdQmDAsVKe79hP0+7LUTR+KepzNNImm9vg6q87+O4uPd//zjxZDCwWNVf//+ZBQNh+PjM+bA0XNRadmHJGyVb8F/eub4qiVvzIUrwik24n4WFNl/Lo1mKqZb/fzr/L5FJhJI9yTz8yU69fs013qyoXzfG8NjY8vE7MzF+crAuOv/+FgLCou41A0XOn//nHHUdSho7FlCMg//uSZOwA09NkvoEoNtJBh/dxAScujLGM90MIfMl2n5yA8q+IyQxXQAAH/y1p9Xp06j/N1eSRuNirOtzJw6ym1faitcVd2tU/9FExKM7lU6OaPWWIdROCDMs53j9hLlyjKCqMUcjPmNChOTlH//42OOrJf/88bA+OQSpgOnm0lqgKrwGzRwAwuSxakKglJsIIgkUmMKkgGOteUFBoUTHIQxAplscunEEdDXuAnHV0iZAZi3EeKCBI4FkrwjpDEy3rTAyM+mlBrkmiPT8iGLKsV5/nHhSNCLQuPpPtxoMisOdbeKRDDkHoQiHNeAoEWl1Y8ZFOPWzF8QiAyZsn58sZfzrV75DDLanr4vg9Cyq2w01ttVbAoGt2hh1s9Wfqc5y5sRc3ORWF8RiffuzrhMByKiHuI/UhkaL4QhUXYGSMrNaU6F6L+QsXBos2qPGbwjTUbUhismkORULDuEogQYe5yj7OoSqjJapFFHBtGijyQINCWdCb6xX//9uGGXVWMNN43Y+C4DeUZyJaL9VyMsd9jmN0+5pGyWBPMBQqLdQsBa1/4v/7kmTrh6LgPzkB508iWufnJTzj5NrNjNqmYeOBPBEb2AC8AFIkh7uFVTgwuUcFYIedQhigF4Oc1qI002K6FI8M87j5EULwrMGQKA6NxIJBwHgTnQjGIsVQ86+UEBydVVSTaWwuhzoQxuJzKkfcDl/XKHp/awuHp8HOjTrLnI4qYuLMhaZOIpQvFSowZZPkBK5Kk+C+mOkV6pvluhHc4yFmmtnIoFUuS/mONA8FWnEW2Ghoc7s0TjbTLS6EPnFuPpaNNpQ5ATqAgxLU2pEQkj/TxeSPiHIdyyeTOX9bXUAtiFEdpTMiNOJIHQqk0j+voUMAksc9aFgP9JLJ9/n4itFzOv9POsNQnvFYEQWpSlYgCjtzf+gDB0V/CQFb/AUFUAQBAroUDNKCzBpIi6M2TpSgqKzcCz3C2uscmqqNZtTCDj+a3qTs6qEKRLw14SlR6yJ5CCjF30kCZJIs1TFJayQwBSRcg7ys06lat8swrjZq0caWF13Y8kMtbEgYTKWRoz9kLdoMUQKyZPsl0ChJK06ONOcRelTy0L/Zxg0Tvbf06bX/+5JkvAsG3WO6Aex8kB8D1yABhRRRaYr6pJkzSJgAILwAiACp1ESzcYem1+q1PU2DNpDkSIIK7JqDBCnEFBlb5R9nE63uU7nP8T7uch/28d77/yf+nq/SIAicodyu5iONmdc/q+iubGSEKQIfsQkjAXAkCgAdPLKFPloazTHhEKFmYQPNNEbO2GBFthaFyE2fmwynMTAM7EBKGov5YKanNBQKG5ApNC6p99W17DI8jcphbaeQjj4oeJzD1DYyXHwh+2semdVKh6mkKH8pVIhV2JDMFHqLqgogykZc3I4rlmyw/LkMm2PMEQNplWxfqhMOS+bh0JllzZlpoakw7qjAtScRphkeoQEoygKpmQaNiMDtoipSgOH3dr0YHUKvCYdBUoBVxqkmBQdDjCuH9bIhcpPageQPrEUqoxPVJNrASZxIcaBTxO5rlsoELFhuKmyLkUjoi05cnSGYISc/LdJXpmpoiYcGYyBBIhHQZ5PMkFEd9hMKkQSFjwJYlc0L3kIk7qGLZKhC+KGAsHltzjnnvoexRuLw+1ryhgtMVIt3TfDn//uSRKUA0rZEwQhhHyJXKTgQDCOCSTxvCyCIdgFcKiCEMI9R5S7arHJAAANqQYIsIia16uZ3oqGRmK7IKgyqLQQTQ4TxdzrtC1I6uKoIr25JvZUmh/H3az7kw6VS1aqNosLqNE5gUrxEdbtZtO7OJUcZ9F65OPY1DEo5Y16Sj0X85mIwKjKNwxbMj0J3GbCiQDoqwEubTE2IqCOv31k/4i5uVp0uwiTNplSS66U8rsZEUn7lAmmkwoVe54GiArrQIw6TbOcyfIraHZoy205EfF2RDMwTuviIREgB+jgAsqp7GY2ZlRSO2sH6pl5JJZn70rw/OUrtETNEgo9EsZ1d/keUoiOEerzuKEzsSpfDg1Cd4u578EJKDluF5fstt9wscA1QgSvUyVmOpl9pzubyZdNE5KcNy3y2R276U66NpXOJLeYOlJS0kU1Yub6mSbRE4R9B0uYW6SRXwvvY+W2R41pKcC9HSeBaCieQp3+1vf/2PAlqIQAAZkAG6NWRVgxLUHXcV30kjduJH8z5CM3fFqRo7AqCGnwJp6/unBRP4YIXW//7kmS8hzLFQUCooy3CSkhYIAQjbgq5DwICjLHJRp7glBCMARuhxHtJ5+RFrmD5JbZAebNTkPz/HZcP63DGXX84tUyenGI8Xv1Dp8OX3b8/BDgm23LnzeBQ6URouJRGiIJrNOytdLdDVR4xBc31p4o9jNajFwjoV4eap59LOr/b6o3tSNGkanCjXtn3RJtFzPj1uXsfUZ8+wnjquvr82UzIr52GzHP/4wqABsAEBPYBFo7rgBuwUaC8NkxCPbmuGOJWVko9IMaAiTgcut/W9YOfjQQOtG3Lrig54U3FTzAmD+uMQiUfw/yr+gUNKHDCqAInggUN+rbA0QgEDZ0s5ARJ5McO2ioKlq3iAB7Wi/wl4cGzJyEeFGijIbNPmtbJ/iil/k5kSlpdSMcMnKmdrQuGHM7qfIgJrosjNYg1flays1iVbm+juKq2Vx3dlVsheZFw6CVaACIA0DqL+IaSsEGyFWNKbRHFnwL/Aa3p58Sh0cxwVQqifS81CCcifQ4vLwKii/FhzP6xEe0dsNJ6nAhiombWDnwMOQSmqGOien06bQH/+5Jk1gTzJWNAyGkcQE5pSBAEYq5MnYb8IYxVyRqwX8ARi8kY/oyk2Yp4li/0/3P8+Wnhin0JQaTJNCkuOdyMQp3+MPK9K/55sdEZ7vM90LiuZaYZOiAsgIvIZRx4BlBscKC2hP2IAg3g+u0/YdKCF0QT7bv8SuHA8eUjE33/xniDInLPzxmbqKXrOzNl7DL/Y7NTEAAx0UkLD8bbUmm2FlZY2kzkk5pJbZ+/uSk/f9ytiHNaGajE3S2zSpz2/z8t0wVtJoGvOHbht6fETFIah4ggpRZKVq8QmxGV5VnsWZFjjYZyhaoCYQkBuJip4H2vvXNkebAsSUag4a6lDJiA8NqL9bLvQiu7/QfyKjT6D3zF9BPHmrYMkiZR6Rs7+2vKk881JNyEwa3uSe5Gn9ND2gwuDL9tNYniamjO3tq35qORRk8KRyakmlOsxWV3lnPsl6anyt8/I/bFbjcDeoSdv/qNZaZ56nXnucDVajE7+JbnOA01oRBSWygpCFFAYRAGtZo0dOu5m7o5lT3M7IWRITnC4NXABlHgGO47wwXcJTqW//uSZOWB8vFivyhhHQJe7EfQCGauD1GQ+qSZE8GxsV9AARhJdc2OyWmh/6c3ImBVkN3PkTOVDpX7lC6c+FrUPh1vvud4WLKMmRhkRZCGUsXsKgyDkw1Z0f5CphEulDn7EQI14YvNyKk+5SGqMnpZMg7pDJieFM8zaU9rwFnxy5GqKRIDL0QSDV5n8/hYJ37TGWcYwya/o7ekIMkLWpFcEjnCM8HFKDpnRNROy6018/tte4kaG6aQSYbbMb2CFGeaXvavGoWQsNUZNo1UKbbcGiexA5jzjkL4nPLt1UGN5YTenTidHczy3iknsFWGIJGtdhjgxg6U06GF+cVX8OXX9Ou3ytc4Q5EeHLhuam+KMPlQY5ZwBOnJ/aOX/zj4IIMLoyKsjPSJnzuk1X5DFHyll8CF6aF1ASOdrEcvvLwpSaSllpwrD+L72/Eubwxvz8tinEwRz+5uUu6ln7+EcgZ32c3U2hmxJ7lxqeXAfje0PcTkEIQAZQRKjZoqIPDqLWDlGM9y6MZuUPEqbf7NNoKS8pE6hwLUMKHzypYP2zYJCPrH0//7kmTSgLK7T8FIYR6AVUuYAAAjGk7xlP4EmHzBP63glBCMMyPdPz82t8jGysW7WjESlkDfI7ywkem/Ttl29j/NfWqD9+gZF0/J5pt/5mdAeKJyWOxlZaHfw+hO79hvZF3Xf6q7FKINqrd5Ld9dk758St/GKDxOdhbDlMP4S7ZUyZpptBf7/tqjrjnt1m3jd1lpVo4X97fK0hMlVWIihlhAeO2S6KPTQkK8klqkiExYHGeKUiHNkVS2ReZrUlYt7o8zEsoyd6p3s1Ge7Mos6GvdsJryIxlY9zpT26wXL/zzK8v8GU043fXzSj1BawquTKq8DRhRIRG1EPEPwTCrSYN3Mo5niMFBKMVY8uOUKJv0zWyZdc2J0IyMgyV0U+m52EefmRdpExhHpC80MEZEC9P5CpBz+Qp+f9i0qhZcQ16X/LfMUxAwAAfBd1oSmwYnaTdMbLUJ1K/UI1iilwHJGigUtaEzLDgdJ8epTGxm+0hWL9p/O/3luy0zK5a49xsFdH401r0rWbYwoE593tEDFhbH5eaPj4tqrswaPjFzrnCMdGn/+5Jk14Dy9FJByGYdkkchCCAEIwBKeTMGwZhWCWIw4AAQjAALcVf8b96jiB71zDfpcHjGosVxoz7yA7i1oUadf+ExERPScGpGcIfN1spcblnHZmbhWEs+NnU8J4fEoX12gF9tnyMh5myps2DAfFmIAwus1LyBpIFguaFXIX6LQ+rYRSpLfBeRyQ9jCxxaRGYYaz3MlVQ53PeJ7nhTc0UJc3jJRggKLpbEVNLiTfasx1yVZkhfTgS5tfU0/oXRVAd4G3uvzjEY51g5FwvMtGocpCnHHIjsrgIYwp/NdRmRDO6SOroEFz311fRWaIARijPpDAchuo5UGPAjFDBJ2djsmQjDKI103mcxrGt2n5CW9BtEXc4kiFvcglSnD8jvZzpMcyPMsmybmVct/z/5/3+R0Bfwmakg7bH3OtzlOEeXKSRSxS04BsoqCRIrNibRCKMFtTRGFbKMni0whT+mRvpKVpMtUlcWYPs89SEp98457PDLLy/t6PPnb3/f9OlDgF/KascLIiO0wZ9Q8Gas9v7TufPzxH6ztblpzUMXJ2s7C2SA//uSZO2B88ZiwEEmRyJkTHgADMOMCoFDBqGYVgEvsWDAEI25yNmImO7O5jhoGjEX1jJR6ddFCYScEsRLRc1IjIoVKx9iY1QUCJlg7UG0Q+os9pEOkZoHlQKsapyHtFc9CChZEAyqjnSU6wJUYx8PRsyLIwTCzHCrtrYfO6GAIADN0VHo4fJSoLHBzbGlgKuZWjWSySlks6VSDaSThVZLM7e85kuGfJqLqSU1z2C0Uverzb20Mt36/uNNeCqmE1HiQbM5P9FY+GWxhJnDXSTbUg3GRYkH3uqDUjb6mp9eC+L8Zz5o7h3Q8uDdNVj5VaqqwwPH+BkM8ioWlVVyv9wpBnh5kZnH4pk1WUmImUjOpHoeuFg+Yk18CU43r0HU/aqFuFGvUIEc2XtPWGx04YVTUcwcUNaJKSoG6uYC9IlzIE2ckXIkOjSp4goQBAq8ltLxDYVjrym1i0E3bSKewHjNzUD6uSWtrdAmLpRVQ/PUmNTLxO6w4SFlsVIjKDq3rrqTAhGq/+SZ/Lpp9Kr9ISXsRq4aGGITG3U9/JFPuEpIeP+Xwv/7kmTuAPKqTMIwJh2CYeuIAAAjAE2deP6kGRLZebCgAACMCBe9CYIwxK+ucc5sg62002+HBZ7wch4jxF/FyHoPDZjrzHkUsrW+Sa/a51cqvg/+G4Dzn/lEYzK1jJn7VUtVNumTbeITlooTvDXgXPDgj816n8LqggdLiILohASLRKkjaaZfafIUmScD+Hh5M/Z3nSQMIVuZJOPRbDrFifxDSTB4VFJSc501B4qLJsLoYx9hxzlPtEpc0shLnx0eLkCicDoliTLxeBZh5INQGyiWkiRaEHRxII1IUI+UAzEoxtScOQIm8xeXU44IwZRLBZFPEXx4oMcnCCI4apaed9uOcOOx8LO7BTJEqPZAyoh8Qz9qyOgJV4PI1hBwaVUPWGgNFNjppV6gvHSXtEI9VeirIAIiwIGVXBxkQNaCdhBVxdJCc4JkU1TJpvGlyUShXwkWR0pe+zs6tadfMa359v+1Q7K/6R9Zf4txRMWnZbvVGoGHSjT2lRmUTHqSXbh87Cj7o5LkK53Zyk1o0vREZcx3iJSsiuwUJD1IAAAADnOMCg3/+5Jk64Dy92JAKMIeAFMrqAAAAwAKNLkRoYR8AX4wn8AADAFieQUyBmV6rtDJFGekSx1YxYOl1FYHhRrX5Y+hmgNBnfdyNiLz4Ozd3WzlJ8i5DaLsdGTTBuf7zxHv9NoJPQGNqFHtAMhAc/yeEYXEauvYLNdXmSLYIGAde0UdVyji1omipQrFaLeIr9KdZxiCxrdcRG1E2mb3DIktqA2gR903JmKac6bcnlX7IJTr0hWHW9uJEMjOHTIz1YTRvNZ8hCctmBswEzbrSlTLHG3BTlFU7YwtRwiH0SFq0VDRg4sUMehXp/ZPemqRrCGx1O9Sv2qCh0sUkdcuVGHEakzhvOtffKqzZqRmrXWK4pBJgYjVkpeNa2JI0MyvFlKlZPpXmtZO+bHpWWdNXvpDNi86aa/Cpgsqfl5+SjycP94LSXyhfM1R3Pl7C0CEVQgAArtDCcqnThLUkEECyzlek1yBa5Q94VVPQghw0a+YzwijfJKpQlRhxjSH0uL8wMnqKN4i2IqBkv3S8283QiRJ0SJhIgudbvwVBQS1EGjxPXIsTNVs//uSZPiAc1RiwTBmLcJdK6gIDCPQz9GPAKSZGwlQsiBUMI8JS6FMlhW4mxttF1dIvTyqz8U1PDHzbsyHvbVwbFZsD6UgACFAMlKTe7dI8Fm3q3OTKSPwPxnmMEBDu8mRkRCJr93Odc6XWCHHQ6p91warKCU9F4GkQUNhyxY5jpZhEo5RBgXFn1FLr8TPKvGsIAgo0iAEsjI8yKTimZmz4s8mjTQwKNE2F07ZD+Tbpm71ZyqkzsKa6iIJFcWdZwJDps53CMr6vIxMqkWpHf9WB9XdHyU9FwUqs/19FftO8+gWlar2UXVrfLlIACzIRgGIOEABgcc/UDtB17Nbd58kUVnOZTUwAtDUVoQ7sd0OXka00nzUdfddKM+tiVY8yXTa+VZvSkcK+Z1UBvNbfbUF3BX87qOqVAEdSRElFSczsbavIU2VMyToEDOlXNIFgVSLjEZKaVb4oFezr4eg2sm9HNdGhjUkqifaelazOT19y2J4HesUI90ebXiC1iD5o4IUjldLK50+YMu0zZXHxF7iSiEJwP/vgNpHWP0xl38OgBCAAP/7kmTqAEOoZcCow0YQTGWoSQwieAs5Zw9ApFZJLCrg1BEP0VYiAmBQRjkQMNCAhB0VgasjkZ6GCjDN1EJrGUPym0q+XSWGyIJqcuZVGHv0v6VN/pMfwp3N780LM7kEOwni/oWuV8X/lM9KoYkt6rYIscRllV/NVAQMAAK5dS2yQwkYfB6M2VkcklhgQ+1ivEwao0czZ6A8nnFw7URIm0tK+ON6xyM5thRRK7M5bMmrkXtKXpI1ybPLxDXaTloUnqUZ++U1Unk+Y2C4YHUaQGXWNoRWlQAMOoAKGP1NnlEj3E8E6EGbpNqufxBWQx58qo5fT9CL8EzHBITWQ3kf3pDSblOJ0CMYqzN7Ft6e1S/9PLN7mCU0UzUwXtT+FSK/aea+ZjmaCcY7TNJAydAsGKYmBZ9f4E1RpN+KdkOAhF622QT2VIwFT8sgBOtSwKQpZKlJW3jCgK7sNraBOWsvxLFB2xWHINQHC4sXAtxXYwp6pph4VTp+auZ9N5JqS1g0OTSaiSMZZ/tKOMqrEJlOht8+a5Ye1WnC6JSlAw71I6N8FVT/+5Jk9YCTSUxDUGkdsleqyCYEw8BPQX0Awyx1iViuoEAwjlGzaUQJn7GJ48weWEzJbx59ggACJQbrz64MitmaT9CuP2fDedEqq5scnVhI66lzeqELZu1She/9hmbYSVfh2dLr3pu1ynWqqdhnCYaXKcS4z/ctRIRIhO3ll6ZOWn59Pkm1DaYnQAMyecgLAaYbO7qGBc061FVKhhcyUspUQqo7Gfu6K5dmMjkKzazKkr1s7WHnUrWWp2unYySqxSSvU+NsVWbJRDkkVaNKioxkUtM7qQ9bULtV2IqTnZb2Oo/vRVKQgHWnL2gx11csKTVDbxM3E+eDKIZLyUqTL0qP0iGqFRE9dXVYTQz9D1fCd+ntELdH7npqSx6bvaYtj9UL+3hHJEXUjl6+nZCI/MlLB/T45N1p9/P6b0Y9WhdLBoLRtdBaLRYHAIA/8RACgYBYwcA7DDGIV/hgSAGGAUAUY4YnJkmHpf5gNACN6aVhzhjNAIYGGgEH5gfGMQGh0rxDwMMgUAEGgZtHwBq8A4NBnTwFBGBYPhcIRoGVCIBvyCAb//uSZOwFY1FfQAhoHPZT7EgVBAMwC4WJALQygAliMeAihjAAQOgFib8A4CDhHGQccsFjyDYOAyQNgNem0DBYE/HGHHh6AnwXAXAMMBwBShgY0FAAolBEcQMck/+ThOD7HGG3ldMDDoFIoBgYSAY2EAChfBsIOv/tfvcDCAIDeCKA0AQGFAwAcHAuUDYQLqP///GEKQE4EKMaS58PTKx0h3////44BB4yg7E0VLGcEEA5cygAAAAAbBzPmE0TK9KTDemqKRxy02dRIR3OW8nk94cEAyVtZaW4ESM4HpOuTN5ac9ZSnTpfXnSAetVrWCZjcYcvuJ3vNC4ch/s81jyX7bvuL/w/iJZXTQHJeV7LO1mZrecmt2M7YY3lFKnRymhKwiz2TMzOY99V/501npnXHArFI9LrDqT0NpuZqORiztZm0Oos7/+f//vuHAAIAu5MQAAaSS8laxOsBpMYmhmFg4wkS0wkRHhAxr8TtNZTigOMF6TR1EYCjqQcSBzpxBV6Whp/GYYoiglHBNUiVWXFg7Wk2yZcZLs6SCBhF/FiwBFx1f/7kmTxgAecZNHueqAElsxIFcMwABxVkVH5vIAAd4AbKwAgACUL0F+bePZ1L6Mc5DyOtkqAMnsU2L4qLIE7f7gumSy1+3pKw25DpRsitmpIXIpyNixU1jRQPYg1JC7ymW3cw2jfS/G5DBWv62n7g29Dv/8Pc+Zt3sri+2OTbf2t/r/+hs61////9Deyvf/+9TXIKoP//05dq3//2GYne///OzIMv/6rzUvf//+CNgAAAAQAAAMBgMCAf/+pn///bS3+wk3//nv/XrtURlQAAABKrTIm5uCFgVMEAJMVAjMJADMIBnMmJ/NuSkPQFUNCSYKw1L4CQAwcLQQYvkyszMSqggXiyMyGygHAkA6EBZaPwYNA0EUAMTgIUsQYZU0OlVA2RMlol0fyiWwMBCwPmIMRIvyLAYTFoBIAFxMUS6gtTrZJMgIJAsLuJI2ROl2cOgGg8NtIi5xJaKZ5KXwWA6jh9kdaaLAhAozJdZa0EkzEOgLzpL/RUpYZOmyLsgLohE//qugJWTyVhvm3//0h9EFHPrIA5k5L/zghAmBwIBhRALn/+5Jkawf2NF9OJ3agAgAADSDgAAEZmYEtD2p5EAAANIAAAASBOAAYFoKRg4Jmmc4Owb5owAkLSNAeigADbrAKIX3arSjVm1SW6sQXmvFHoxMQhzADAgkYwAYYjoVQGCMEgCntn72eGv/9UMAKPUsHG/PFaiejD5tMQTnQsgrbF53K3////MRmOlRaRR63JNnuhijtmOjiS+KTEBy3GpzGch0qASANQ63Z//3vCIhZiJC5NZxuZLKpDQMZzR1v9tSYNNiZmlzheGbDQUv/1SQCFJXqFPDtJ//9bmoZIVxSRPqqQAAFmaeFuyjojAdMBAD4wYgaTAnAwMGkFAxbDMzssEMO1BgMxPwYwgGVWNP0eAdYrdGIKzzD+zz6wPflsvg6KAQNTUxWAqC6EkChWaBSyYKgrYf+Yr4Z587zt6X32CjAEkCCkgAwBBMYdMgA4wSS4wFAlezqy5FJvdiABKqBcMWjIwNiisc0R0BpMgEsw7SkM6UUy7OF9MQoAqVFQPoG3RniuAwFBFyJA3YyeiXgNAKJJlv6zXrAolBZOSybJFwC//uSZGAH9uBgSavdo3AAAA0gAAABGtGBJg9umMAAADSAAAAEpcPqkj//HYEjZE1nAzsVsv//rZYTAAiFg3aSS8akriDIwACYYFIDhhLgnmAQAMYDoF5iiJIHUIPOc0cWBhUAXKIA4HAqAKFskiUwaWpbpI3KJbjWlMehQqBYYLIzpMAqDgIjADA8MJQoIwKwJlXPFEa1XXO/rdxopIBuUkMbcsDUEt2D5A/aPhyqiaKIJ0w9S5Y5f//9SSjieLQdF+9TdJE1VDD5QDGDlxt2KS3zuMHi4gTFAZMiUjFL0UjEhwAEwCTYiKX1gifkI/60VZ8Cg8EUskE0CbJwEBUSdD/+seAibNZwM5BQAa///YV4Fj4UDFZqyop9+GThYCkHBHCRN5gqAUmBcFmYD0WRkjHinPNeSYT4Q5gFA7GFQ+zRpKk0iK0Pv/alUVr1LskeNWwRlM4P0jEY2UNMMCM+X/TUAFaUpa70ttc/f/hTuArI9xCBjJ7yMTAJnbsO2rYCQqZYlYspHlnrzt+cNglVBdsWndimVSeE6gbOeA2ZGGUxIv/7kmRFg/afX8kD3KNwAAANIAAAARmNfyivcnPQAAA0gAAABCORdAzIIVA5MDpgBYzR261HReA14AMCCmgm7OxTA1AMcf9a1UT4YABbMSLoEeaiiAwSef/+NgIEJPUhPIOOnn//9iDgouBEMLSAq1V9nBaUWgMCsB0wrQQDAsArMFAG8w/1HDfdHTNdmpAwngBgwI8hATAwBzOIRAMepnpl8zWvY4U8YZ2YIDx2yCmFg7IxIHnkjqAoGTAVzpNR3s8//9YvstpppeUx2oTDwBadGaaUp7GTmwYICKlz8y6zlj////slGosk+f+7t2OKLgBEl44YpIvbvd5lJn5FACYkA0Vyx7///M4wAQ0TEiR2M//MAOaiCP+t9FIIIA+Rq8xL4IGCDkf/8lglVF3FoByf//2DRwooL5qqIABQAMtzD1tgEJ4EZBGwIRPAMw9wnTfhB9MiKKkYAXMAkCBCOXLDrneh0XmfKlnKlzPtiffgSALMT8EYGgDOEOAGGGyLMYFwATE5RT4Z4eswH2JWYCtwNw/B0sdhPk4OeHwAdN4AVWL/+5JkNAP1xF/LQz6icAAADSAAAAEXEX8sj3KNwAAANIAAAAQKZIq/zoNEYIsTcxc8QYA5YDpZEDAa5ZVoFcthogGeAjsT/RSJkAk2DkpWb1FMDADS//v0gSLBQEjoG4QhBof/8qhIW1YlgyKv//qDDjJCemNAAAAHPaQmG5Ce5gKABmEkAkLAXCgKBhGo9moeQUYK8XxgGAUDIBowCBIHrEZw+9Td2W2aKmtcvzrngIEnSB81Fio4JxnamBhCsBHa13W////s7KX6VWAicTmiNBNwASgMRMUDCBpsuspN/gkfBFnLVaiyosiXBDsC54pm5aZ9E2IkHFAHPyeRf6zg+Qk7FanF+swASSOfbfWWAgOESTUs440hNH//yqERJOusSoT+///1B5SKB6paGAAAZHOvyyadTGEgJAEGSYB4ABgHgXGBgaWZBQexjSruo3CAA1ZDFnZXjAjXpTMU05Y53LG07IjBDsXUhAVnCEEOG4Aw+ZbTWcuf///7kjYqV3QMhjxDCr1+8/RlxcChl+qXJH/UExg//nWTLQAygW4T5mRh//uSZDqD9RxfzKPbm3AAAA0gAAABFQF/MIz6icAAADSAAAAEzrNDUUOAoZND+ozAo0LvNH/CEP/fqBqYT4+pANTHn//ngyU9lITJ///xWRUBRmFQAABGOnRWCaK0kLHHtOZqB0zGFcPSa2whhnJMVGEGBUCgDVxM9gZ94H3hdpLt7eW61VuRVALMGwMAUACclTUw2wGSIHlV0hv87z6BfI8nRLwMNpAsDJgzLhDw6ADT6gc2Ps//hEGDEr9aJwZ0B8cMYnGLyTakTUZUBhQRFJv2LwN1AcaPP84BAIf/38IQAZjpoBopE//9RaDOx2MomxF///4+Q7AnQ1oQAAAkfplaelcsAAj0YLgGwRCeYqKIejE6c/5SYQA6jY3dpUKoZRD0us1a17fNbuTaTgA2rLvK3ne5iROBLeHf////+rJaZ9jEIEzrOWOoBMG/YdFbWP/iWhVvXQL4BihoZogZr83NhdB8Kv9ZkEDDJI/wy+//8awgTrmpCt//sJWVcjyS///oDBIuMAAACP5F3ktpojww32maMMmB0eGdRkniFIBxFP/7kGRTg/RXX04jupN0AAANIAAAARFRfziM9mnAAAA0gAAABCwAJrvpSQ/bzwy3dsX+frOUI7mJYtYOsh4YEl0hpDtzev/6zAlEyGAa+BdhXQTLhBwFagWSXkf/UKaFL+uspAOwIORmK+tSReCizZv6zAGpBRE/1Bqw///IuHm60xaCs3/+eErPZKmn//8jBskc9XyAAGzrGVODWWwscHuRRAiTClPDaceTk9DQUKLbO52drRmzSnknoboJjkAcwqLwnRIQNHpD6k8il/0jhqQ0CJscKS1GY+AQphG5s3/zoXH9dZgBEAKImmgr2RHyNZf/QLYmj/xpt//GuNn41jT//sN09nSW///koVS6eAABIdbgxo9xF9jKHZlKQIKIIXYI6WGQaFZnD6wJK3lZfDUsl9q9jz/53kWJ6aR8qcI6iQiJSG1zv/+dJVRbCiRAx52cugabhdUTqTf9RiDB+uoxAiUSV6SvWtANNPf9YX7Gi/6xg//4kZI9U+S3//Yap7MCE///j8sknUxBTUUzLjEwMFVVVVVVVVVVXIAAMX7jDv/7kmSHA/PPX0+jHaIwAAANIAAAAQ99fzyO6m1AAAA0gAAABB1FlLpCAobOhwMI0zNpR0OYx8JghhYXHSxY/1MvDW9JFIgIHQKCAjkEA4qwFgBPs//QUkWAQmiYTUmgQ8DBEQ3n/9SIMA+uozBAFFjQQT+7kcMul/zoa0n/8XF//iXt6h9mv//Ybp7LBI///ywVicXAAATGOb2uNSoziQATyChjBgMFo/M+i4PaHhCB+HgIXnAXvK8ziWIZl0M1v/96qp3GLIsq/ZqrOYVFWgDilfW//6zIlC6QEDFlQWAlZFR0XQBkQQnIkapf9RYBxr12NgDAQZplHV9aDEPBQMfb/TEchwbfrEFX//hrR39aAppv//zwppax9O///5SG2QNMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVGAAAeHMnRQylJUSCwB5MmKIa7hhFDumnsGoaLJ/BgiALCAA1Op+naruMyWH4akEhh/v71dfAcAHMCYKQtKpsIwCjBIEUQ5SmVVct/9Apj+eHWBlI4FiZcN0C+OYANnAOXEFLyKv9QvD/+5JkwoPztF9Po6yjIAAADSAAAAERsX04jPaJwAAANIAAAAQUf+dUZj4Aq8D1CfTNEH54nQ/oNnC6l/RKQIBALAjV/sDdI0/26QaKG9qzrEBFW3/9R4MOSKbj8Km///5fEDD6qNABjHUBsgXmgRMAEBowSwN0AhgUgQmG8UwbpwpprtOdmFaB2YBwBQUAoiASB6ooCeGQuFF3doL+9ZzErIAsZ+foVEiRoCCJwl6jRlVifmXWe8///8pS8LvJHGGkMDg1DM1NwAMgExAsRIkRW1i//C8Ap+8zY+QUDMiQc9LZmPxSXWgT5sHUAOgk4n+pZHBA2H46r1FMGhMz+9fpCMQojPZ0zAoCEmR//qLQTEioG5o4Xm///4poLBg209MVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVEAAARH8ygSXl7CICYODLCAEQsBeYCxqRj+CLmVmtAYGABzmBAQziWRf6Stdv36Sp38M4gKgJ1b0YKI2VXHcJpQhLck97vO/WRgujpLAaEUDkBJnnRIEBqKgN//uSZPMD9UZfzKM+onAAAA0gAAABF3mDLQ9yjcAAADSAAAAEqi4i6kj/wwYFIbdazg3Qk9GuaIG7trNieE9ANEy8j/TQAiMBwA3b6gKAj//6AmwKA20DMNcTn/+o8HDGJYfYwv//1C1i3DabJAGXJc/rtEAAZgJgDmEuBIYFgDZgbA4mFejYapY8ZkWRPgQGF5wsH04UMV1Psy5/qavjS0veZ2J5IQ6oWzDgSQ3JA4bDtw0LILdyvhnh///8n+vykqOqVReSTcofdHgyeVgMbqXW/+4RJAt+bmLmg7wJLQdHHYYD7LKqkyoVQ1oAS4vofskToAosHKSs3qQAFFn3/vy8EiAKCmrLCQhMHhf/+otBIGIEqEVLC///qDDmQe4WlUxBTUUzLjEwMFVVVXAAAACmuzTRYMGAARCAmFwLgAAGYDwB5hog3G32BcYD74xghAKDQFYFA0hfhdlmhjdqUWMafneWowj0clHIkLhIElUNmGcWIAKzKGa29b///eoJYTGnGMYCIaHUC01WOJ3g1Sl/Gmy6yk39YTEBTE2osqOi+P/7kmTsA/UUX8yj26NSAAANIAAAARZ5fyyvco3QAAA0gAAABAhUDVRi5VRfUakVFIgSaEik31qJUIVonUyX8pAYAAbf79IICQgZHOGAWrFFS//qLQQgRUKheifG//+oREbwoM8IAAAQOZvwu99FCzAeANMHoCAeADMAQB4wnT9TXbFAM1eK0wNgMQCAOBgGqJozuSqBr8zYqWu8xyjrOgYATjSyMMBcvkAQQbqpwGLzav1LbWP///+cQeieWwYbQAcFIfpKeWPeZYGhiIDsultpFL+wTKBTc3KaBuQQDMpgUeETL46CgvQK5JBMABhgJcX/QH2BBWCI2XE29AAoma/784Ezg5i9M0CAWT6v/6i0EAURaonQuK3//1C9BwAT0io0AAAAxtu6x9kohAdMDAAAw6gEzBBAoMD8KAwdmoTIaLANhaiIwpQehABaYvCxg0CgAAImMroITA8VzvZY5YtgekEiw2/QwCPkiRIOkcnHloPBJqMKor+Gv/9YwErM10RAMx6owcOXKiMcdMQA4ya2hpHwq91v9IIRUBZLFp7HTpT/+5Jk+YP1qV/Lw9yjcAAADSAAAAEXiX8sj3KNwAAANIAAAASDUQMBoEAoOl5EgReao6XiLCggJH8aRq7e7FcLSAWKxLH26JeBgYJdv1Jc4CYiBwEXUUzUQFDNnn//OEiEweFADi0BQAnv//uiCwRDlSAAQxyfVuUREYDRgFAEGCcBKYCICBgTgcGFUU6bJweBp6sHmDQAyYAoBCalfCko5ThnVrapu71agoqBUwe7DA4XXQk6bIiIQL1uy+xnhn//+8ILarhDZjIejQzhF/GstkxajwqBGCy6ykj/UCA4C1Mtc6mYDlgYpeBZWThcIeZtuVCRDJQEgDFX6kSkBREDgxqr6ADBJv9+wTAAsMTzEzBvQW5v/6i0EgIgTFYHC3//4zgaSH2P1SQAQADdyA14JbmAEBKYDIHhgtgvgkBIWCTMWAyI7IAyzqwgMMRkDgwSAAwoAZagwJAEHAOuFuz3yZ9puQz9u5NxBeYWCg0sXMwgAIWBowHDwxDpwAg4tt8I7cu4c7z+disAsGEYFGBh5AYHnxjkTawW7MlhJMXgPZdK//uSZP+D9nBfSkPcq3AAAA0gAAABFsV/Lw9yjdAAADSAAAAEayKv5GAnOCpZGyRGl4mQwkBnPABVoiJkMaUUmWcOl0YAE0Akp9nbqOi8AjYAYGE2gm7OgR4GSIjv/qVzERsDpB9ky4QMJnBzE//5wkQhKhQayIYYN/S//+sJBAoFAYCJigAAAj8HXVgi4iAeGgMgcI2BgNQQCqYEiHBmJDem1CYGYTwD4FAMlqciFcYdTVeH7dud13eFPDCIZwNGGEQMlyYCBpqWggYytajNNjl///63BjGpS8pjUAkQwealuR9DoVVMNBd1p3Jn/mQQIAWfn+dUZjoAw8ICxgi5fJgwfYtkSDRgKgzi/7ngDQQOSFdn9ABIgnH/tzERMKFXzBMTcJg//9RaDPw82TQb2///1h3CGi5z6jAAAADLbvMRbYCAmmByAiYdYGhgiAUmCUE+YY7aBuhlLnb4PcYl4BYOAFBQZHhCYJAa62utZcXCGpPNyvWFuWPOBAEf6IpiofiwGMIhg+EyiZvEwRbaKz17u9f+eD/t3dVAsxE5TC4Dff/7kmT8A/bRX8nD3aNwAAANIAAAARaJfy6Pco3AAAA0gAAABCVyx/1+miU2Y3BCPrvS02RS+twlSBT8V9Z1Eng5EDT1wJZRvlMWojkXUZlxQrcC5oYp523SRMhjQMDBAtBIkj1qLIBik796kF0jUCqcFFJWaUjABcaDgJs3/5YJYIlQoRN2E3hQkV2//+Eggc8OiP5XWxKPsIJAGgqBeYE4MBgKAOmCYBuYqouh0lggnTSZIYeQFRgcgLBBoRuLAAcDr6Q5KKSrdq2e3p57QcBj1aRMBjYlAJg4IHb6UZUCAkB3kn7FvDD//dZ4U7WvF7jIyKCCk7sqj8OF7zLS5KEDlnz/lkJkgKFpWtEvkYGPgYIQYCgfHMLg55fPOyRCDMgkBQMJBIgKSP1nBug0KIarMFq6yUAcIC59s9qWEItDmmy1Jk4EgqQ9X/84SwTBYOBB9QYcOON///xGQLBMLmVVQAAH5ww1twAaCCYEwCJhRAXBwERgGAgGHKnWcJYxhyeL6mEWCWsCtKBlzOrDc7UwrVpHPYY00ZZUDAfNMkeC4Ej/+5Jk84/2xV/Jw9yjcAAADSAAAAEZmX8oD3KtwAAANIAAAARwGCoUmVEYmBIWpyQHMV8M+//6rt0Vkn1KDEsiAgRG3osnpGAEMNjqJANSufmXGqTfnQSoA6f3MTY1HeBpEAKbh4KAvSilWYE+T4cgBugI7DdvugOWAYnBR2SBuh50AE2h989qOhApFvUtRTLgYFBgE9//OEsEAsFhjKDJRABf//5WBxMHBnMAATXZA38HCEB4iBVCBlTAzAUMBkHgwFF4TFMKMN3dsgwjAKDAMAGIg4YTBIUASezvQy/b6RWH6CxjlVjzdSqHjMMtIgKWyMGiI013DFoKTLf6U1sf///uMaepxUQTCqvBQNf6ZmIbYIZxAQGNTXZdikv+sGkQHP31HTIph/AH9g1AmzcqHnaiWyJA3SAzoUcRql90SaAAJBRsVXbrcDCCDdv7dYIDIKC0KjrhegQ41f/84WghDhQC0dIZhv//sKyCwYLkHiAAQACrTQCyJeIBAHMCwDIwqAYTAzA0MG8IAxVlBTnoEwOJ6w0MG2FgSQUJlaVb2vM2//uSZN+D9jxfyivdo3QAAA0gAAABGLF/Kw9yjcAAADSAAAAEf63Z7P0GWV2YgtOwsDs1DkjCokLkmBA6eloZn4BgYBOLD0ttc//1u40cqAOGl/GcAuTItoMukrcBGGTHUnAR8f2LWUmf84EGIHTjfmbFsbIKYgqEGTJsUwlF0DMiA7AagwN6GFjNH9ajEUMCDAFixRUvyiBmRbP+tHpAQJgpDQ0DcGhwcxf/8sEQCJEFCibjkBQief//zgNQIMDg3LKiAt3I+8C+wYBMYB4EBgcglgECAoB/MSgjQ6KgPzTLroMFYC4wAwDy968GjvGyKP0kN1LtJ+8JuINLAgiOpRkKC9k5cc744zPYBSgg+iv4Z7//5nLIg6xCAjCLMCwAgOYzsqrGZlkYoBqVzu01nLH///+gLBYKBdf/9/XoE7RVIoIaCxIrV7u8p0doIAoGyCDtNkX9RmOgAl4CigiaCb7G4DSw2b9a9kiKA6EzrKBsF8goAdv/ywRAIiwoNUmGsDSTT//6ghBivB3iq6owAAAA+w19ljX3MMC0AIw2QEQMDf/7kmTYA/aFX8nD3KNwAAANIAAAARlRgSivcpHAAAA0gAAABCYAgPZhRMiGnsVWZglqpgJhLiMDZd4CBBbOnkzzyqWSOGpRU12xF2uGBw2e7SxgsNKSIBQbl/BkYOInv5K6meGH/+qrdk/nJR5MnmsOMLjSmOOGIAMZjSQcipm5tX+cCNoFkT7om5OCywNEpB2scBMC/LKtAiZJAkCAzwsuJq+zlUBgOC1QhTz+agWXEg/609EyAoOBzI87GRgCYUN5Nm//LBIBMeDA06GsGXQ///CACJIFzpacgDLcDM5h4uyYEoA5hLgNGA8AqYFQKZg/pOGi6KqYR0bBgbARAYEIFDNASsxYWDoHwisjkN+l1y/RP0NAU6gIEACgooEzHvDMFA9HKO1qut///+ETbLOLzMTHcOD8Uv7oE/TBbBMFAZksuspI/1A1hBcZ+tIojPAYC4FlRdcipi9S0ieDogGpY7kX+tIhoC68Cw0yX8pgYYCV2/vrMgkUBgNemXAgDk2r/+cKoQAwoArFDBob///iWhQCHvNVJAAAAK25qC2fLvH/+5JkyQf2TmBKQ9yjcAAADSAAAAEXjX8tD3KN0AAANIAAAATQGzApA8MBgB8wQAKzDvGGN+UREzc4azA6BRMBUA5QRdTNJFE78zP5d7jZys00RBIMOQqsVDKpgaEjgEoMigJer9S21zv///lKW6u8ocYcQgcDoZrV6Rpxl4QGLAS5UtyRS/wnCDgn6ai+LkAybQCzAg5fHQYPpk4REM/ABAGKv1nCmBBqBYGYJq60QARjP/fpBE0KWfM0AyCHnb/+cKoQgQcAolcHAn///KIUCB0haIAwzcBW9rA6BCYCQCZhEAWBwGZgCAnGHChubxpAhqXRuGDmCoYA4H4YFBYDr4dSR4S+moO9taq1o7JBEJzZEeMACBzECR1kXEzBTjkNHe7hr//V16E2qruGTxMNFB7qWgfcUAxj9kAovvNO9Z/7BDKDputSyaFIgY3CA0tJ5ZAjJGs4YkyIVBF0Hk+33YrgABQpDLTt50BBk3+++uEkAfRedOhbgOCNX//OFQIQoUEzASMOcn//9YngFhIarL4QAAAEb7AjbxQGgFDwIIsJ//uSZMSH9dZfy0Pco3AAAA0gAAABF8V/Kw9yjdAAADSAAAAECYDIAAFBUC6Q5gJC9GqCv+YJwACAYIAAOBcANfdekhqxQUOOHNXaB4yAJCjvBIDg4VBpr6RgYvssi9jPDv///y32KpukCHUToLusl8mL0GCQMyWXWUkf5wEmE90EzAcsDDQQLHyKFwh5m2xbKwYOCYMuL/UiTQEDQKDjV/WkDUUXv9+sGogLyT2NwiEMl//zhoGtDTXUKyZL///EsDzChj5AAAY6dlkUAjoUxBA8ysz5g2c4wrjJzWqGKNlRJIwnwOg4BUSAWQ1cGL4tJpKanw7j+6krfQVAVMJUNZiKdRKAoFxfjAAAMfeVXdb161D5EtIsIWA2yQCTodpeOkMDZwOJDAOslJFX/MgaNh5bskYivAYZoBZEWlENMUqloHCJgtCJNn+pZYCFULIOq+YgVDmf/7BqQOIPWYOHFCqf/+cPBkoaY6hqiSf//rEULoj16iAAAADenrZhBZIBMFwDjATAlQ5CQH5hYCZG3IGWbPJd5gbAHBACgjALIILjNv/7kmTHA/WHX8uj3KNwAAANIAAAARXtfy8NeonQAAA0gAAABJ/KtjH7Of8zpIfBgCN9I8cCyCUwAFTV89BRBZdDtNjl////nKIMizGDDJwDgxT4am07BRVAYDutLbSL/zgTaB7iPqMxQgAswCQgmy+TCD7lokQ0UAwAYpf0y4AkYCxw3Z/LAAgY2/q9iLhQy+cUHFiov//OHg7oaTmgZRv//xFB3iTFsUADPj9rshsRCwMiPeHJiohemCobsZrwmpsGBiAILsOAQCAE3cYO/8otY51KfuG+8v0Sa5iCgJGACAuzxH4w3gJg4GZPCRWb/O/RJoaxBRHIGbpgNFSLGKi+OwDbrwBlQzJeRS/1BCqDwN1UidAxI8FkJbTI44vUbuLMAsxJZ/6RdAXEg4ibN+DbM9/tzELbgwA+6AQgzv/+cPCJhdZ4+BMW///GsIeJI9UwAAAA/GBmStaAgFRgagJmGuBYYHwEpgpBLmFixoaf5SZ0Zm+GJgA2psUDACgUtwqBkzcXEca3SRKetY2pa7wABp7pNGKBMr8s4dZvAQsGkvz/+5Jk1Yf1hF/Lw9yjdAAADSAAAAEVFX8wjXqJwAAANIAAAARL7GeHP/91G7p/yhTMygZxI1vZam3AEIBMjNsaSF6/x/9YQFoFhQa6zhmUA/4AiPAKAZAC4RM3bRJccQFQQBhsFjiRS9Szg1QKlMPlOLV5SAUFif+2oxCETgiCJstRTNAIAENLb/+WCoEQKDAYpYdwXCr//8mgUDYXDjBQAACRlt4mEx4qviMk4YjEFNaEwpxbjYBCNNYI5EwdQKQMAgxNdXIvVrXq1eztdJEyIaCEAAbBT4KA8Lkg0BoGSKCBhECjoLJxav3NSiQYSIAg5Bl4mUqxNwGHEEDfRcROmyL/1BAKAoBG6DniLAMBQHCoqGBKnVaZoeFrAYExXb+pMBwXBQDmif4OAxUf+3WEwaTKWdOikBRm//nDwlocBWNwaf//8h4b0PzKMAAAANV3AUrWgOgHGAoBKYSAHwcA+YEgIxiIomnGCQMcdcERiEAlGB6BqQgLAYCtAIsAv+5Xls5Vo9ZXbklY0SBuZKKYYFA+GAkCQsMyISMFwQSJcqM0//uSZOeD9l5fSkPcq3IAAA0gAAABFXV/MIz6qQAAADSAAAAE2Ov//1dbIi9DKgpi6BokOLfS2YdtSwx5DQxLARptNjlv////8h0UCgPef+tVpKn8MEgnpH7cms3//KdHCCAGBsBRBTZF/dEgQAQAKUiRPt5mBlBIybfz2o6ElIb2rYmwSLF5f/8sFUM/CiF2JoHDz///4aOCgoG5pohj2ci8UAoB5ECgJCmmBCAMYA4MAJULMQkbA1VnmzBRAXEYAYKAiQrF8Io+7/yO7WnsO63MPGOBgzFAxwWKqhQBnHV+EGlM5+ZdZ7z///wjcfgVWUwklQcA6DecQIQCYGYIODjay6yk386E3AMKeko3GYAzooFpg7y+NQsLrQK5WDBgAS0iif6kR9AUZBaUYq9agMCIMv9umCAaDhaGYHwKgBJH//lg1DyhQY6haw0p///qDhj0HOZAAAWcqWNQySkjGED/LzTmjg4DC0PhNiIdoznYKDAkBqBICMMoc20fmYiU9cm5Zur+8Kd9BGAaYdoZxgAgUpyJJmJAF2LA9r9e+ct4Zv/7kmTqh/aDX8pD3aRwAAANIAAAARb1fyyvco3QAAA0gAAABL9IdIlozQckBtLwIoxBS8s0FxAcrQBlhYnIjTZFL+wQNAUaHtZwzKQoUAnOAwBMmJ5JtZsRYQGAUlj0i/1LHwA9cFpBfQ+dAIFl/+v0wx0KHjzzhYDkw7Jt//OGocMGBqhLxYk///qDyjMB2C05AGNZbaOi+xGAAQgXGBGDKIQICsFMxWBkDu2E9M3jRswUQNyIIEwoAsAAApnEbMjlGMul1/LeFuWO+BAIN7irMMgkDAaIQsM9ZyMJgIJgGfSV1K+GHebwrtwTak4oABiyUQKFx17MocMKAUY4mQJE1TtMz/5YCGwCn013KBuRQMvgbKaBLuLgIAK+R6CaCY7BsgkNAzJAcal/Y+VAMOCBa4SZon5GAVSFBP2rXskFjALRy07HyGBM6RqS//yULQTAhRayggAiDF///UEgIUEhZG0QAAAgZ8f9xIfTUMB0AAweQDSIAwAgcmDUfcaGQjZidPtCECgEAGFwGgPfL49T9p5vuU/zvL9E1I5iDQ4RI4j/+5Jk5Yf11WBLK16icAAADSAAAAEaKX8nD3aN0AAANIAAAATAZMj30BBF4n5pquX////KaCodUNMHnkMAMas9mFZzDKZRebWT2Um/qBqkBhx+gkYi1AYScBIUapEyYvqRLo5oFpA3nb60iZAXPgsNNm9R0EI0u/78yBoGBwZszQDFombf/zjB1QcBaPkN4b//8dIXkL5YxAAEY7xpykX6WABQD5g+gEGA4ASYDAJ5ggnhGUOM+ZWLNJgfAihgBxcdlrlGCggWBUqlg5yLRCc7znbMuRtPkbjChdH4EhR4GMGJSKMus5c///96krVa0WAS6TE8htbpHLFoAHGMPVckf+EJgGGn6lGY5AGFZAWKE+ZkwcfYrlYMMDepgv9aiVBonIGgv8BAI2/35wIBQhy86sUgJk3/84aishpmYB4W///JgPCMyqaZj0Ar6AgIpgOgamDuDYYFgFZgyAxmNie4eZ4epvdaEGCyAsFwBTAvAKKAA0iIxYnafGYpJPXltNSw0wEKhsaytGYHjAv8ICk4NKgePhCtqEH0VvDDf95bhyIM//uSZN6D9Y1fy6Pco3AAAA0gAAABFeF9MI9ujcAAADSAAAAEmFQKMGUaMAAIgvKMNLEQKGHKfAIl17RW1Z7z////yoKhQXlvWsY9VjSIJhaQoYPMKoWZRKz3U3KDYQcDMIi5adn7mhFwMExAlvHYboIPchoGVLkh98+7IlIJvhKCak2IuCSIWJFX/5KFUIAoKOJmFtA40qf//cM8AsdAaLETIA1tuiwbdAuAAYCQCpgqAYDIAJgQAAGGiX+bfobhsotnmFkBOTBJBgML9M1fpr87hfp5zlHhutMtUIA2YKhwXB7NCoCzYVjMJgNdEbpM8M+//63BSjz+qAmPSSLEl1rOWTATIaBMJgxasapUkf8IoAphP6ywmUBPYGCsgNEyCFwi5m25IEFBoDAQEMUl/dEngCCwOTGr/OAHEE2/v4NTQbQnWYHwb2FEf/+WDUVkKDGWIkM3//+sOENgOY8QAAAEc+BGTyYRgLjwGA8JKYD4AhgGgtCNHkxuxvjYKR6MJ0DYwJAFRoBJCtuxRgz8SyUS6CKtrHW5iVjgSNINMSBi1v/7kmTtB/bQX8kD3aRwAAANIAAAARd9fy0Pco3QAAA0gAAABASFjCmEMDgR65qrrevoEPG6VRPYGiygSRk46ZFA5MDeVQDqKC//hCUClA/zBzUiQGMRAsmLRgRpj1JnRlAJRR4dvqWWASYCtjqvqBwstf79gaggWEPnDgpMTF//5xhTwoFdY+g8b///WIgM2IXKxgAAVcoi5T6hcDQwIACDCYAxMCkBowMwZDDKSZNu4bA4gz1zCeATMAkCMBCBINhjLVXvzGZDQ0szl3OpK2kAEInSWkYXByXBhALnC8SAkSpk7supcuf//+UMs9cZI4xUmgcLndnrETIAEYQbBd9a0VtIpN+gCZ4KgD/OHCmJ4AJ7BYoRcvkUQdnRJIdwN7AY8SZIpfUmOgAlYCJQT6CfnAFDJLt+r2D2gYW7kwBUaO1L/+WDwloLGHYh4MBn///w6wcGJY5AAAbqTL0M/JDRWAL/g1IDvGHcEcb7ADJwTBMGG2A4DgUR4AseAcfGebpM09rKkxn+8t0jvo4GKgBmYCQDqry+RiVASEQT6asWnb//+5Jk4QP1k1/Lo9yjUAAADSAAAAEYkX8rD3KNwAAANIAAAATO+o6NQRQ6LIA3a4Fog9nlF8SgB2VIGpBClSeRSR/whJAtsfmTGxIAZcSFIBJmY/FhemaHhGYCkIiaD/ZI8Da4OWltn8sAYUEWn/UrsIRgodeozLgFAIq2//lhhWQYGqEvEbJ///WPoKAw+VCnsOOwxnYABOMDcAow3QKwEC6AQcTDkZcOAYj87L0OjDkAlMD8D4VANYkybOai2pXOy/K9j29J3NBIEP+ocGixXRgANHb98ZOCwKBavJfYt4Yf/9vSeVNNGAGQvcYAr7WZe1gKg0yVBRJINBnr3ef////UFBETLn/1uSV5IqmQKcZAccsSO/e7zKTDMgQBgbAYQUvIv0kTIZ0BNkCRUyR9RDwMQfRV71IaRiCaEHKSsiosrDEAOBmr//koeDJwoxqCIEZhf//2HWDkYODPEAAAIHeQM5knFAGQ4DMwkQAjAgAJMBIFUwQ0WjJ/HRNkJBswkQFRgAiuIAAsIhuppF43Iq9Jjb1jlSvsFgObgUisrLRg//uSZOSP9bhfyys+onQAAA0gAAABGZ1/Jg9ykdAAADSAAAAEGmKr+VAK+klqb1v//96gljMaZ0YyDQ0OoTa5dYUYwQhgIDtOltpFL+gDewUum+5g5oS4AR0GGyIGA+zvQK5bDuAFKTRP9aBHgUUhb2aJ+tQFRSH+3Og1Jh4UtkwgBEGX//OMM6DAmKaJI3//4tYcEIYeNAAABHbseXzBiRhgnnjIZB51RmFiPQa2ISJqIp1AIOgoALDgAWhv84MNX6luvL7meOsa0AjIBhgrhiogq+CoCBhACWAYD5yY1S5Y/9MmB8FYUwDH4gGghfoE2I4A3agBiEXUl/+IoC1R+cUdFqAhEDljrmqL6zYrCegGE5EkX/YviDQoXPP8sg1Do/7c6EA8i6swcMeGA//84xKheWeDwN//9Qlo2hZbKjAAAAC5ddBW9kAFA5MCICswfgUhGASYGADRieoBnXOI4bo1sphWgkmAkASBiKEBJAatNpzaw85780dDNXLsxBqqA6OTN+iMAjAIBpgIFnwX+HQ1CJmsDTt/DW//Kq6SdzEQsP/7kmThg/W4X8uj3KNwAAANIAAAARUFfzCM+onAAAA0gAAABAzJq5ARVadIZe4A6DRiTmIgMrl+pabIv+dEQB819ikgRcUABqXQCnAXGRcVwjE9Mdg7QKiwNOOJtBfrSMTYAyIBJsXUvW4GCRIfbPNUWQaMQobNKyUKQZHBwg2b/8lDQaoMLVh+AOCmn//1BCHE6B1iq4oAAAI517Fdw4vISAtEhJDAfACMAEE4wF0bTIhIKMylzowNAUiAA0eLFjlsG7MhiNNKoYkGdneq9WGwsGHgY4oItDUHPuwQdBtAkdjPmf//7wgtquD/mXIY0dwi/9hxjSEQDFrLpbkil/WNYHYH1nFmQxoGFlgNCTJEmjJtSJVEJQGnhEUm+pZKBNYIIGavmIAoM9/t0wSCg4W2kYA1AjRV//OMNcHBGWJURX//+KaKgKBPVSAAAADHJrqpmshwAxgXAMGFwB2YGYFRgng0GHUsKbmg1RkpXVmD+BCYDwBgVAgSA0dAVVzEI4w5r0xKaS1+dJBbSDAMDzaEuEGlYiwHBljERhIDTI4hN1P/+5Jk8IP2qWBJw9yjcAAADSAAAAEWYX8uj26NwAAANIAAAAQ8Od/+dlsAsuEYAGBxpAIAnZnpY4YWAIxVMAoIqjvdb/RGmCqjrIxMmBAcDRXQUli4CKDHlNDQJMcQQhgMMPHMWr7Jk4BgzALSCTNE/SAygQtt+tfTEJQo/d0DMuAkNEnQ//lhg/oOU1h3guWbf//UIiFCgWPHhY6krdILVUFQDAsBSBQEDApAOML4Bs2GAlDFgbKMAsB4wDAHRYLDQAoIekE5SY1bktz1zuEDNBCQAoYzkUCZlGdmAgO5UprY6////3JGjUruixfJhjCr2dRbJhlAkAAabLrKTf1i9ClBucSMSBAYBoCxIqqKJi+tRkRYFm5bZ/0iGgLjQcNNm+gCwc8//3EIAcK51Y7BNW//nGOheWZB4n///QDTBGhqMAAAAN0jvrCMPGAJDArAUMNsC8mBZAAOZiAMnHEgW+abeLZg6BBjgHAJAFLUSvy9EIk0OxOM1ZudrUsaYaYHCR8t4mCxiXWMEh489bDOYcQAr2isus9/X/nYf942mkgF//uQZOsL9nJfykPdo3QAAA0gAAABFPV/MK9yjdAAADSAAAAEMTOkwmA4Axp3cLhmmBGZWC7OozWxy/////AkAZQ0L3/qaqStVQw2igUQHLjbgTGf/2EC4QQDwKlCVMl+pZwSsEr4hCWFq84AoxKzfrN9FIEkgIkyOiTYNDQnJFL/8lEBrhRg0WsHEn//+mG4AaKhc2fIA7yFN5IgYASNAhmEeAAYCwApgNAlmCCjEZAYvZo3NvGC+AYYBAAKBrWpKzZutJZvcn5bU1jWmXiEAeddmAQSm0fD/WoolWDSC/e7z///1HWiw8pUZgpBxdAtHYhtHQwGmDBd1p3Jn/qDB4LXfMkTYgIGJVgiQls6RxkjWpMxJwHQSWdv0HAoVBQmaJ/LABQYtf784DQoH2RzA+Fqhgf/5xjEHBWUL8aS///rEsFRFYP1QAAFbGGm4ryLACRgGgbmEqDMYHwH5gzA/mLOi4dRpGJzkzImFsB2YKoFgcECFwBAUAagY/rDoYjsM3/vbuUMEMLGAOjBHGfMA8A9HEKgWmI4SGYKoB6kIDlF//uSZO6H9opfycPcpHAAAA0gAAABFiV/Lw9ujdAAADSAAAAEfDPPn7wrtwSkkaWhrdQCnB16TdpYU323MrGEfXeltNjl////46QjV5z/3HLsQUPMQmQcTv5GH/p+f/IPGSBCGAw5McRil7OajLAAEApjLR9vL4GOOkDV7596yUCFsHKHVLJQyEEwoFPt/+SimBhplBg0NgX//6lhIMM2DdUrYa3KHTfQhAtMAAA8wQgLExzAaASMMsms3lw8DcCTgMG0A4wEgETCYGQHl/GSu1QxSliN6is63UlbMBUMmk34X1SKFQ4Yi3BYBy7YlS1t6///8ZU9Tup6mEUqDgjD1mfhhG8yIdxo03N//ymDUmC3FuYOajLAZI0FIZIGA/llVSy4wocBqcPbP9RiPoCjQLTjqvWUAFxxef+/QBMoCwR9IwBqHGRS//liwUI46QuI3//1h1hDw+xLoSAAAADl9+GXu4DQGAMCSYUgAwcB0VQWDBdTrMvUc43rTATCwAcRQUtQJu7jD+o1f7asd/DOki5dQ4kuwQHkqQQFzd89MXA9Pv/7kmTsD/bHX8mr26YyAAANIAAAARbdfywPco3QAAA0gAAABKHZdZy///93HrUdrOsZABZMQ3sn6SJpTGEF4MgFg0ttIpfyiEJMKafOIFMO4BXMHIEXNyoz6RaIKGDQMYCLqSP1JkYBFYBYgX0F9SwaEV/1P4NQQLFE8zNAaAxb2//lhSQLEHj4C6zf//WNYLjBlEkmAWeuyuZlINAlMCoBowyAPTA/AqMFcJAw5lyzaUIsOlIIcw5QNjAuAVCwcFAaNAJxkemIu9K4pRY83leo34LRnwSgYbHayDAYCCYyPNNRBzpDR3s9//8zllRth0CCNrFsI/WsQ+rAaBBpkEDLpjVKkj/Og1UgulfYpHjcdgKVgdgGmTYvCUWpZgT5XDFgAWEnDdvs5IAsOClElzz+SgBhw0+1SuiOcDER9lFlEToF5nn//JQ4oKLKw3Acah//9i+ChsLnzZkwAAAA3cj7wQaQAUDgCBgCAVmACAQYEoCxhmBNm4QCwbS5VRg6AEN8XVU0c5ocVldmlp6KdrZY5WY0oCcgIxg4GMfHAEbJjAP/+5Jk4wf1w1/LQ9yjdAAADSAAAAEYrYEpD3KNwAAANIAAAASLDL5ZT4Z4f//rcFMajLimNRqNDF5qKnhhVcwkmxYYRW1x/86EJsHTH5xZwXoD6YhU4xsk2s2Kwe0AcrIki/1pGIEUoKATZvrABEv/U3YL9gwQ+imDQAO5H/+cUYBQQ6xThx///xTw2oXhAH6ctLxlYoA2YEYEBhXgag4DAwAQVzDiUgN8Ykc5mGYzDhANME4BxK0wWAgBA2wdSxzrLnuv2ISy3lVlTSQuDBrSg4sIQkCIiDEw2j8lBlTaDZq7rPvP/Oo+6ncHJpmHBVhAlu5T6pUqjFYwjA4E0rndlxqkj+wRbgqJ7lBMnBcYGkUgivjIEwLWR6C1JkQJEJgwNKGIOgv6zhZAdRAaDmCavOAZAUVm/U2o6CFCCJCkzmBuCEcH0T//lh0gYWdYnoFA5///6gvEN6C0E0wVEAAABHcYPbyLBQA4MBDMJEAAwHADzASBVMDFGQxNxdzWZXgBQjoCAOAwEBwKZO2O0/0qjmMppc8t6qwUOBMzs3DAANWG//uSZOMH9Y1fS8Pco3AAAA0gAAABGdV/KQ92jdgAADSAAAAECoKNPUIwiAodh6lyx////ylL0u8sow4ag4LPzPWI2pgZBJgQVpblv/qCaEFpr9SjEWoBE4CQIxcuovqNSdFIgNOCRSb9j4CA4MHnnb0AGh5Vf+3LIQlRkUs4kO4QK//84olAYEymHBP//9QiZkIOryxbkpS/xUAlMAcBkweQPDAoAfMEQFsxATqjf7HZNWCLswHwUQCBcCAagYgDjLWX7fzK9DkxL+auzDxjAiMbS8YHCCUwEBzqKXDECzZ5ZFZv81//qu9CiU3CDJo6Fio88sp4AHQKAXSYMAi1YtZSRf9waMwptP8yNC+I4AzcABiYQcmxjCgndAkySCIADECScWr6SJFgCEgLJjV/uDkKH+e1FEIEIh6WkUAQiRPqX/8sOQwHHahEw3o3///DJQ9wLkHmlRGAAABlm9CwaMjghYBMwLAKC+4GAsMMcec2rRFjNLdYMEgDoQgLiQKgLUqU9F45GLWNLhe5+q8QEYOdzfGCjrEAaBn0bYYnrMkdi//7kmThj/WmX8uj3KNwAAANIAAAARhRfyoPco3IAAA0gAAABHhn///8v1n5UVHYFP2VY37EHmnFRkAG41Lkil/WECUGHkucRMh0gYGOA0ZNlk0ZNrSNhlgRQySZ/qWWAiuGeWr7AKCi1/t1g0FhpatMuAkBGn//nI+goJqERIB///GqHAiP3MA5m8ix3cMAcAMBA6mGoAYCgPhwG4wdWTzTNHyMZK3swGANzAAAeMFwqHAOaQ2UiAFyIffiW197vazpHbBAKGzRbmFQFCwFDgVGRcaGCwHLTgCbqZ4c7/7uNhSlf5fxjAHQYOzmyOHGtiADDEs3BIb3uvdb/OgnJBFVfWWDpMCbwMprAUhjMEwOWU0HZMeBwg0DgJIFlS/oJkUABXAicE+gn1FMDFEx3t71o9wgFhRkgmosoi4QoCZ//yUcgAOWMkJCCwQ1//+swBxwL0LVPAAAAMcpTDzEXKAxQ+REzow08YwbjhTOGGeMVJqowMQMhIAkFAGFtWtN1hunklmRz2ub79ucU3KCBgMBMnyDADTBnE9BQDrpRGmx76f/+5Jk5If1bl/Lo9ujcAAADSAAAAEZsX8pD3aNwAAANIAAAASnWTBKFsUIBjcAEghF1GZwRiBofoWXC4SeRU3T3OhCjBxz1KRHKAwiYFDR5RGnX1GZ0qBRwSLt+kagLgQcVPtT6gEhkv/1EQCgptaYX4G03/845HAwA01Dwt//+OgQ0XKKABzbY09oJFQEAQAgYBwFYNAGMCUAQw0BEQNuoZdrrIUA1aEDgA4XOvm2/Inqnq3rlSbuUUAJEmIsDsYAQDrzA0AI+6+DGYoAY5LbXMpRWuy6MSyRM+f1Q0yFhEiV1ozD0YUzNGIwhVgKKajdb/+ktXZ6hKpaUDN27LP1hXbgCUwOBK+UYlHf/GXSJJYLgM1rPD9c/dyIjJSrDMc1rap0EGk/T/fWTQJEDuNdAvhCBEH//u41AotQtAizf//TEQENDpjdFAAAAG83wcW+piAgDjA1ARjRdMwfCKjO+CNM0RIAwJQAjAoAYUybmBQAUzGaMsoZXev4/nTQwvBYgWDDbW0sCj8lnDl1IwgHMXB1h2Ju/TMoV3L7b7sPYm47//uSZOWH9WlfTENeonAAAA0gAAABGHV/Lo9uV0AAADSAAAAEY4xA5ig+RA8IvySPyQLsgkBtIffKIxqMY0+EUoMaclGUzbldaBgeTJYDFQeJsXyMX1FpAiYI2J9y+9F0EXNwKWHHn1plwmC4yQWoKiKlINpp2WdCYCjHlLUZE8N7//MFEcHmx1FP//9QpiI2VLMCAABmCQxc0x1EMgZzEWwUawqNBhGDAQwgSNnmDnXIKsZvxeYmPDAmhMUTEIoEECoJchIdYRKtHyNxOIRd6HXbwwShIZPUvucWIRrDchldFTRKWSKK0MO7vUdJJi6yopblalMkZmilE5Rb1ZtVdfZ7S2mQt73G6k2JMElEgUjb6U0JE0SNX+tSJgOY6pFbH2MisopI/+w4iEi6Lok09//pLOkrWZG3//8yPpAcAANa5okpHf/Y9OrotroP/b+k03/rYb/8uQ7fJupFf/+7pTQAAAC5jEnRwguSNhpmUO8Y8DVkGDDZTOUrDQLPRGgf619Uqv2Zd6A+EIyBqtABBqtTf17ahI53UR86WrVWytgDlP/7kmTsAwY3X80j25PwAAANIAAAARV5fUHN5a/AjIBfNACMABgjyUJVP7P1iWtEmtrW9k8Oyy7P70zrTWM96WKZmCOvln2THphFbqVhJv+ZQFZcRM6f/xIJjysyD///1FVD0vx8l8HNngfH8l/G8xuyAQPVFkvr/UEDJECBUY/z/CCOqnchDk7eRRfKSm6QsUAAA1aVSqHuyl/YFZimMyNaoUDAxJCgdMQktVEQmIjU5IiZXWbQ0iajSyILCYQhlhFsvLctlFOSrKz1Wa2SKW9bY5VbFLWaVdspFEm9DHYMJ0lKVEUKMGdjOpWQylo2rewlBSt6lVv/VHUsMKVte+tH8qQrD8h/6hK6lX26iJU80RPwVOrFMRFga1ALiY8CoCDp5dQhc0kJWQdGJrCRZvtdDrCp2WDra+sAhoi8qeLKIAXIAc1drY3cTvGtAqHiBCiRLNfquz55Pk+lMyM5xETdsokmGIxNWTiXewqiksyuyVvBxQoCjVxIJx3U6pBQQfycSxqXpNnSmOiiUU41oR4fkxiJHdVnBJirCPQ5lelpWPD/+5Jk4AP0CV9LQwws8i1K+JAAIrwOuX8ZDKRPwOUAIgAQjbjAgqmKaov2ALKeIubwyoF9WyeM1F9eSTACZjGLU8Zlg31TGA0UbUisy8BuPmnVIqbCOlCbMM2RtSMm72MjANLeUY5FjbLIrn/u704nkUGV3ktIP4Q+ORu91g8D2qmnDzezIJgEJUgmbzXmUe76npi+8JNbxZ5cvU3y/4y2WYrepk4GtAitHIiJ0RlpIRoZmGUcEKFExlHWMCYHWtfUqEOTSBxC4IJQCNikhxkLm9bXDG99IDb/Rwpt3q79VKnv2fX5Ihh6cBuwMm/kPHu6sSgmjmUm5HqRBVzVYS3BQ9EtIgb8ONTv6iPBvmRnkt6m7G6q87rSTlgNmY9V9CQiTKa5mjSG8kJ6huaSqmwI5DckYfFOboDueTIdPBRszIqbhmSGFpIEAAJkBqKJtRmMzME6DOdTa2IlAH0McT07hGViNja12O5HLR3W5w9Y8yhPmQ4EbajdBHg3HriWQSDosWvIGEQsGZ+lDoQ1pcoZAvx+HOOhoJ5mTU6bO0FsybKb//uSZPAF87FjwbGJG3BHilgwBCOuTZ1zBAMM3MlpMOCAMA3BkuwIkXuMjjlVekI4YVBG0cDYUvlhWGZkP052I1MoOeCHXLsz4vqWd6cflyI+ZEZqtczSm1BulaR39SIeZkTW01I7bEMi0p/pCLInesvPZtipEVpG3CJCMX93RbLKwwACgJBljJkpuuMM9AhSnVBG4MmcLsSfTDJFY2HUYSBAIRBM1NjRICJ5DQtHzCIRlSqVj1VVb8KXQsNVcnj9VQ+fQRG8B6xUJxIWkpLKEMRQhp3Nk9Ezi4uERITjI1BxDU4aXBol8Q1XSyT3K75hENjMaEfshG7uTlmbjwEWLewwDIXGIiNlkZl40PIEYY+0sps6Bskac2lmm4bXNywodIaWl6XU0i/eD55mM8MbNYQxiQ4wPjnxlWiaRn4PlgiO1lH/NNNVAgUgADZOcdn1g2P0LxGUGnpru+lUUxJZgO7uYhJ5CnSogjqZZ5Wpl9JONvhdz9UNS1KpGG+i5dbXWl1ixK36mrUtCUw4J2lPOvTZY1hsQ7inK54on3pmy8imYf/7kmTshfMnYkEoIRhGVGu4IAAjHk0FfweBhGwJby1gQACMAV92hwORnWJ4SkpFWmLmtv15cE54xyInyZsfQkTbldq2anDJeIeZ3qF/Nz7fGkYnQgdiwv+5fuc6JxXYfDy4e7EW7PTh4nThEfV+gnJtmQlEsCRiIEha3I19YaqgaoaL34EsCiEAAGouKt0HIAWqbsWFAVQ1VycSzvLAXyavjA1rHdVgwtzBBTsV+WCpzWacWOkh8Hg9hHMGMVTBIAg5g1/VCFwGgNkFsZGax1FOea0xMFoNh1V/QREc2CT7GOmLeglGWuokNqRzhwo+JIAnqt2OyxKwBnVDgkxPgxmbCeFZMgipoTSNk1/Uzrp8SKcTxo6lJ8e/Yd6XpqWZZUvaAyzRYsXm3Ts43yCeZk4fGdN6XyXocNp0CachV9omSggEAMsKNAsUqxRFxSHnWJFV8x9bLQQnpUIRJS6F6RdQZXo3hLsICmLBVzdFBkGUkJEBOVbxMgm7eEJKx4toqJbsZJODbUTDp8pidAGhkhhBUY1N6cDYu/VwYNVbexwVYjj/+5Jk7IFzQmVBMGYdMFaMmBAAIwJNEZcCoQxgQUCoIGAgjbnMdU5ZjqUsMZAAQAB/RgmjsTLKRzBP/ovC2RkVZDcaLhyZxEzP/+pmtZedpeypaxlGPsarnSyIgawrW/pfxNfUjMoRdJuOp+mFKnpKUKwQZrsymUAQWikM02IB8yELU9PeOIaCCUU2XB2Ys07T0z6s5zGMbT4lHdQg9bVp6FrZWudJ2UXuIuSOI/DPjzCSatjDdqM0wozucm5mWV/sXbdJ9enacXjaxklZuv9Ts4rwjcDkWrV3cRiZRRqUPZIt6Q6RG0YTKgtMm1lG06YR/e66XFR3ugNhZDENkBHUtikTTMOSjpgHX5j3c4fC/lNefaCK/CNSXOqfCYmnS848hRqX/f9D2tM4xmkJuGh82vlseURWmRo0Nav6y5QirhPumQWCC8gANFJUBpCM8MJoPYqZX4RoxHhU9TQLuaYLJWakfBIo7RxJK7MS0o6sbpxGJ4RMYk8Kk19XK6kzwElhZ0G5fMNwlit8U5auUi7nXL9OR0mZdTlspIT1YcnkDPME//uSZO+F00plwKhmHgBVy4gGDCO0TpWLAgME0Ak0L6BAEI156NNnGMMk22W9EZZsBmxjSEiGsWQbGd3x6DYqaDhlkXpPHemjXm4dKKhXJzk/z6azQ7/bu0wnn99zv83ZURb5Mveuc/mnRzSc0ydzPyvlD1w2dOu8RWMXuz6WOaGsZNghKQ7VPrgESFLHrEEOlEUqeBOhEpegaKg48Nj85mQRUxHkY9/gMzUXqBEyTFkGoCkycWuCM4F6pGoNLHVhWNG5HS0y0zZc6vsa6LO6F4bDPeNiaTEl4o9fQlkfRcgqMO9z8qmnGeELpssdypPtiTZjaxW3UztaEpES1K5nUdSUmugPpbr1oaMcPCaPoimUN34RO+Ruxp5NBXS+D3Ghjbvk+hZ0tK4+zw/KEcjntCy8j2OSbFWULDzKUuAzkFWMwY1W5dZa2faOSOR7IiZjR25JrI21dd/OWJLfXlaLamxU7VTNFaWmjmg8DOKBBOO0wXvFcXu5kFIQWEbjcECExWSGQXJgxeOqrO3knIGaVPxsts0+qSbZanfWzaz/fjsiUP/7kmTuAfMyYEIwZh2wU0voEATDoE1RlQIBjNPBYzJgQAAMAOFWW5+PWb8TZq2VL1a1PzH8+9JJk8J1tP0t3bia1FK5Riya0wp09v6WC0hMUC8ncRBfyPth1ENOhis/eZbqv4nU3LZ6kyfI8si1WR1V17MHaRJX4gMceQT6FXKP/ucMU1JE4IkDkkzD22pNor2q2Qv/SrwQrGSusLwxtptXGfbq33VHGnNqBQpmEDAyZEQIAxTyNVqcuOZEYzkjlojWDAQZdUAxrJSz2+d0os2KayMo07ONZy8JGmXBX7Yfer+SvILmjj0DrliOvyBRe4kDtIoPo4YhCL7OZ1H9HX/ak7dqz+f0sxs7KRuXO2I9FPJxF+8mdkjFE6ynuVmj1pZzpNsGOFAspRZCpMoISg9gotTLn3epGLmFtzZxDOTDGrvpWRURgaO6btVAAwAAmlHCG6IuwnNB8VidfU+VnUmmlxiApSdy5xqDiC3B1Smk1uf/hSsfBEKLjLKxBB2bw0Bs3Mgq9/bSrTdZqTpO8znTMSpLPVt06INCUSiVmayZ3zP/+5Jk7o1ze2HAAMM3IlTMmBAMI+ANqW0AIwzayU+woGAwj4kgyS0NKvpUQIGddx4TKGZNRz1MPNjbgvT49n94d3e2MG26u6I1ZgaOz9ZHtdjf/U+VSOVqIOyLo7I/4kT7yMSMyfk30ljXp4yn91et6E0MteFS6UM0LrLTM/9qRlDXJo3mqW6zC2Wh3eJvo6VjA0FI7prKrkjj4Wlv9Nu8hXKk2rLRkBg5OlQgYVBzJEk0hzzu9M7moV8cGgk2puU9QnvLbU5I5pNBDDeRuLMlrg7UYrux15pc5evSqvWzl5POdEwslqdIPGhT60e9aE3k3X7IuWhhmWiftTEHtR8sQhK0aLdz+6D/3QrWCtK+3T1Yzf21v1b6St6t/y3UeJ/iChQEheMhCYWEJBjM2MnxjzXzyGm3DqqopU//bzdHVvdX7BVMqJSU6ClFkz9eBwWLEp6MSuZktKexRMp+YtRnJHai8E7Nuvb+9TQ00K/cu2YtHlylr126aLWO25Y3MxHo2WcDFnjcJYSI6qEoGyZKgKztJdKMa03WZBM9ymNt6Vt3//uSZOqF871jwLAjMNJLa2gQCCPiTw2VAiEEwEEFsp/AIIvQMn1Ny7IwWhMUVsGHJw0m34edsDK3yaUkLOSw7anzOycDDtRYgAAIGAB3nZnEJ0o6Pa9g7LjXESMo/Ppxkrkf/0P6E9D6i1VcGdvo8h3JeTyN7e6ThBiu1mCM9Gq/T/V7c/0O/nZ3OdkY7EIEEsxA3RXKO5v0+sywnKhwAg5yhlUMKMsDblJwgmlSRSWew5HG/L9rbBcmI46dJ7Xd9ejbjvsBNkIw8emTKyEKQeKLwqgnMiJAEzQl2OBjYYzjBNDnFdkILDHBr/uFJUcp0GNzV9yVpREJCd6Uzf3tO20uL9KGVI3eGifFzaD8pDAxI1NAT0Ccy0RMb43w3OFhczctLUry/ZCtm0+yFc/KkRbU+VmYj+PmcL4WZ2XN5xqflbNxKM2peCH4qggAAGAAJPWpBlHOVpijEE0/bQnNlT4blCoikoY1CxC8HjlOxQUgQHpXBOeDDwDv97QetLN7FFMtkpG4x5TuWiy2yI2WIvvjSq3IA/4cGqrlDU75HcQktv/7kmTrDxPUZcAAwzGQSYyoLAwifgz9lQIBmHwBSTGglDCPUVnzDdVSebbZ8sXJdud3Lgai2sqt0/4jJmuzO05zlzhmJFw0pAAQAAKXt62Fp5sISCLfovFxN3l/E8/Kuyn1mNvtX7kkuuBDP6YiiOMGeZ3+mjf+53w7FRX//u+TGsd3yf9dvM3gVx+Lous8cnhM2QCEIxe1g+LsgKR0ww4pZ92mQMIVshQh7O6CwSzCI41hfweeFu69SFDAkhBZPMd2qN/SJyTbUIqWw1PLo9A0UEQm557gfktW2pkdibEaB35tkyeBaeJbpwNOpsUVGxNueZln+v4hkMZZ4MEYi58kIIlII4jsvptRJ7n/llk05TSQQXOuh7PEqkZDCF/Sn7F/JfhHMEV5SCNVvclJldHlW7BpVQGjxlNKye7QT///GLyv//i8gI83q6//qv9TdXsMkHogEMjFatk1XhU1dVpdnuWzVrlzNs6pxFE1chQ9OtSKeTk6ve8TbOBzM0ctAjhbmUFQ6OxuYjlkqJlXOrTrXNvs7IXiRodNOtfmgaKdarH/+5Jk6oHz1WFASMM2gkuBKBQEIwBQOZT+oyDaAPuwn8ARiRgZeags2t9GyWZBkNuwbuO/UnXw22/0lczoWUm2mKNPgrJDE9rbC0NkAggABq0EjnjaPm5cySGdTOBH2N82ZLLIEunc8WIAE9220WCwRNT9+T9FyZzVdP/udBlRa5hN5cT7y4W6yYnPsNpgRRkWeTH15JFHlZb5VHomDJPWqj4YdDawhUvCcTcHqjDmRRtJjEy8hIiQmKhDE8PfNpSFLs4vFOUZWQhZx5H76umr5JQXcp2dU6nrYsuOrb8YcfV9Z6kksOZBcbh1sVIvGwhXJAhS2Ot9lgc6sYvHxiL4HHkGKsdLCJUBBaQVKnU2dmMiUxufmZTKAwjHAbNntmMIyUDgJEAAq0c3F9haeYazUWlq9tm6yOlFzXWyG9La5yb9EsrMzTUSo63txi5krS9BWgGNqIBUZax2uBMYIkqOCNloKkaTRGXvUIEU0MmCcfUFaZ+ZRMLfKzauUOXqFtRPK3BbNwXorqx9XeFAn7kDJy2PIyDM9WpFbFwX5jsQJ80v//uSZOYNA7hiwIghMCJCKUg1BCKODv2DAiME1AkqKuGkEIo49QCBsHE17MmKlaNWUiMg2FMgRVRZi2oPSMqhEjtQTgnZC5pVGrwVTaEo1iMlGONfdfI3RZ96L073nZCRn46xiQPqNZUMIAbNDnNu1Q4wF224CunedsH6thjDcI0y8cPxovMcw+03rIWUa8QTLAwFeBNOz7ROp5MpGizIP3IajvsnPHU55edsneZ7CUD50mZ1orblDJzlM5uHZadCqQKeYhZTnu3aEwf7FClbpaaarhOxd3pRTmcydipW+xCR1lVsaXdHq7mPe9D3ke3+LjX6ytpPcar2B+vBt2c5Qs4gfAuEzTYXOqcQxggMzMoC02T7jlNSSQmdRbyCNiJrZrLwUxP1P6XLMltjnpxG/yzNHB3yzXcgTRv4px5GygsriNJKkLtD0SZsrh3XSkp5n2xAxNUYpWy8N2bqZLqycNPS2u0M9CtMRP2NxncuC8OdfiE1n/PdQipi5PZeleECu0OnTAe88u9cqaeZW26VFU298ApsfzD8gxXma2mPP5WiB//7kmTnCHOKYsGwaR2yS2XYMARDbk65hwKgjMBJNyCg1BEPgVX9gzVbkgzak84+tpmHlEGdXeVtzIrGjCX3OmNOq3Of7UphaE2/tqjp9JS5qve9iXkW0mu6YJycd0exmCT0CaIBQSkkeUZVm2e4DfFtOEVBInUKUNonSDRvq+b5jkZNO5zKWhahi0kUmCCDA7DoM5VsmN71hvTZm64Lk1y2nuhK12yzRj5phBM0n3tNom4fuXu9U7Gq35RV88FprsDilhnRcm/qu9t+xZjH3bPM9F3wh5ecmpdC8zJiCs83bUxyFO+puSKQqobkMh0mk+GXq0oQIKYGW7/d6h4KQ/8j0zIrlB6OLQp1lQifpeZWQyrZopiA/RqQ1jjqdkj1U8sPMGJot5FkqaJkPe6MKpog4LFSulDMG1qGanykoPK0MqDHwWCJwaHWQycnDuZ0g+pmS53RGI2VG+zWqMceijUQBgFWkWGr1XNBmmeIZm93ZEzIiZru9AQI05Avk46mhPAvHIQT1alQe0bDlZuXHImyscudNXIw7zA9SV8xYNzHzDn/+5Jk5YXzlGPAgGEwgkOLmEAII9oOOYkCoYTKCYMyoEAyj8iNXpQI68iBKZXablf7umMY7UzAMLckLEFFfHxdgHDN5nSdmhMTQbyixjPlIyYDZTpRuOQIl0RdIsThzOM85kNHEBR/kbVrgqzRqPL2M1vZO3IiSO1izsjIjgiylPNt8jKbuxUnzy7heqfDsPY25VtPKMRZlG21SeR1QXl9GkWGoFHBvacExosIErP1CQxIDFN9LIsYSMCvxRxQNd1FTRrPYsdpwbIjirIWdQ1r4VWSOKhO5BsmWVZiIgQM4WjB1LwphBHWkcWSZVOmltyRZJE+c5YvrBRpPyZI5frw6qSGOLxqa8Vk2xDFaBpJFLnu0hnq2MdsTBnmj6qvW8Tn9Lj+ZfIVkLhoRxfKERVbXPPzXkD2ZNM/vnbMqrChm4ql+6Qwj8rdFmEkFNYS4ZRTdOnZUM7JjGdkpdzBX6ITt0e9m+lVvBdvK7LY6pHEXmGyCNcmYslLEYiebxLPZeGp5M1qfKgvbQJTeZmUn9QN6S5b3O1vqMJujprr182P3rpN//uSZOANc0JlQShmHiBGqWgwBCKOUPmRACMhOokwrSDUMI/RM8UjaKkdt6yKqzl8kaee1q1tSfCtQW8vEsvrkoiRl152dvSWBMzkW9DT4PMfXaGppLYO2Q5gAAAASXQ4gyHggkAWJNMzTHGVFANRnnkKnkVjB7XUl1LQiTYjD/QV7NNjiIrNX6TCVylBaFnFCFRgPPxUaJSRAIGOf0OM9u9rHIOLUDV0RCBJa6kpC3Q9Aq9gfEWPhx7bg5BMglBatU4ZJvQExzIkEViLNs2Z1VDLIKGDGTwcGrudt1EnAJWrFEGTezqNTKNq4C8xUV0MqzYuYVXYmrFtyebLo4apo9SVdEzSlZk204t7giUznigNzvTfSvf+OAm7cV8rho792rVdfpK+DGonxhn/y/8tr+uU9Df2fs96kOU5UT1HAbw3ved7KeoqQY/3SWFTmFK2YXB2ArUaah0EubgtJiGYxxakNmIwnkquz0UI0htWc034IBBN7Kv6NKoUsTJPOqNzUFRp2rNzT+7Exi1RjGK/j72lVY3U46dubkN+NsURLpuS6//7kmTdj/OQY8EAwzOyPaAIWAQiXg1diwIBjRXBEoigwACMmTcrRNWqGj0cjPo6p2OTQyypSQJoXQREPhKcWUoGZQvlRCwkJksJ1FxzBx5BjcRj/lgIIpQgeq9qiAUOmujjZOtIy62oQldcVXRgeFnTyUi8ninmgIGGh8Vzbuep1SOhjWqaD0EgU1pA1ICVCkgUNGhIZddCeeymVWNm7n6ASnYIYGGQwxZK94xGMRj5EAsneUzJUIK+RxvfODBSkPHNc0gQIiTQjSsujiJk4O8GOpG2Ud4OmX386hxM+eszKRIUHQgTW7Fcs3kOFbqRQzPr3yPL/DSy1u9c49e5jBW+rT/mGdWhql6a6m/14UNTWA+RpY/k+QO7nqL2fZx0TI+7wq2zObwiN5F8zhoWgZH24TSf2s7szxvUu5HmOa9yf954KmqIelylI68JpwToVJ1My+91h1BrVEmkggLiU6oEAQAAIcjhk4p1NslRB42nsYpPLmZlOZKKfX8mkyQOehBIWTjPBpeCntufmZuSDHSUjFxGJkyErEU4Ei8KXz3QmXr/+5Jk7ID0CWO/gMZMUmHr2AAAAwBLyScJIZh2iVUvYEAAjBl07JE32euhiYAAHGt6r+GjBzMyVIUTQFWQMHdAJkY0IkCfGeGotQgIeEQGAAQC4WLpUHUyshe54UpYbhPgN4Zf0CMkx9Ti9BhI5KqbyQDaK6JtVTkRd56QAIq4XbSdGjGYtuipmoVDATMkdeTlvZhh2UINfjaNqLVixRI1JKole/TRBNqUYRkUtlBBjF11A3nTd3KLLKPS/BkUjD0iyEH7wdAnTqlN6xMybJXlIs8lWDY0pQ6hK6IamUzsR3EOYHTg/ivScmvaRaZvWaWeeYSIochd7CSFEUm7ME1toG26zJH6mPrkNEihhqck0Kvptr8rPJCq4I/kprsdPsvnS/Y7p9hkcVeOVIj9qXI5RnXPIhlRjW/zv7/JTh87sTwy6cydv+2ZPSrT/ZafJRVZvbPiJ8vR6B/f3GBLCA4AmrWJIeJyZirO2rMGs5R7TGp9kNKnSujRIsgSJMcUQKWXDxayyr5O2ZFuhVeISObqjWdKUY9X5TVp0KkgbmHOlUTC//uQZOAFU15kQTBmHEI/oBhIACMAEL2VACSZO0EmrqCAMYq5RA3TjSat3O0nfzu68m+FR3ZFk/TfW02sRTRQbu9H/+u8+tjYm0ysh1vzZnH1X4lq+N6GpdJ9+pimuBYFTS9QuNjSMklTW6gqCqFA0+mWRroXUIn2eWWZFILJ2p2nVulploVhqwtRNhIJNGRGU3KmstEGStdzZfOxBMtJ8K/09BzRUDJBI9NthUnIEbYi0sfE8iIiWX7cNknM9LPkbj42jTnlQiP+TM7FkDrNTaJYt2pj5QnKCI52JVNiCybnNMPWgtMPiOjtI2VopKMyWhiRel9CUxjpnAeC9XWhZb40KLiyAoq4RCzjUz4TRLb6sTZ8CbXoK/C0uSB7C/JoYwwCEILGSTQgFOciIC//h5AWw0e//////9v///2/8vfob///X5f///jIcQSHmFhynHlUGGHBKJpHT33aWkks1NUiDKT2UkklrWvLVpEtS85lSVREqSrESJZaWQoqFRTqM6QxRGYZkk0LNRWJpvnfwmBonOvfdLMsssikwoeKIZPT//uSZOEF86RlQShhMKA6QdggACMUEQWJAEMk14jnMd6AUxVoIYzIWJmnlQyeKgFcSDS2IWffZFKG3m22yr1cl45J9eOePkiIUPaPnSHWnQcYIDiTksRPVQswWRR8YxIWfcpImvDCl9QEuFGNZTBGEp46NhGB8TB6OA+EoRhqx3+iiKOA6Jsaj//////////////////////oPHOppEwFw1QAQAAQCAcCAggIggEgD/SqCgEmOAXGRpd54GEoFmAoAmXiEHaZMf6NwOBA800g18DVkwBhoLjA3sWQAnU7w+QWQRoIiaBhISgRRxfJ8wNB3h745B4DdiUAzaGgMjBoBIL7RSic2PAYeCYGCQEBhwCAYeEQGEgx+T5upi0fAxEDgMtiMG9BfkaAQAP5ODIFM3TNi4DdMGwoWtABAwFAOFzgW//8iDTRk3aA0DCRGXEYgYFBIXLLYZDC6v/5onLjfl0iAzYuwbri3haeZS8XP//be76d05AwsULpcIsYnCePEwSRicOViIAAAAAiAAi9TBr7qveXgJgkSOMEghMSGdMUU//7kmTngASIZT2FGSAAPQyHYKEcAByNly+52oAAAAAAAwAAACOnYNMjh/MLgjMAgDQ8MBQKBvCJELmGSGbMTUih4uol01FnAGiANDLBvKMyNIAD2FsxmSCnCkOIvFVmoKSIcdMQBTolEnZSMh9ASPgHBhcx8wRMKWXJkWwxwPsXjMtJrZi6BUaOaTplTWuykyHBt6aKFOuYnSZDoRPx90VJqY8LgSWYMnXvTTYZwbStbFwklJoL/6lmI1idMWUSCK2/+td3Oi3DyR8AA6KxmeqYRFJcGAAYTAmWyMHQOMZmfPhCmP6IQAw5GBAKrgawiks+md2idaA2yPfH8p2mmZxF8xl6VVVuKgMZxiLGl8H4vVDueX2tXfuvvW6YkAlAW/FNZjDGTAEsoDHdmamFe/Z/VWvYl5UCEWqallNNdral4ICR4DjE5nvmW8caVu6ALuqXmf7y3ramCJWHda7OLBZrT0qlqdRjUBGBxLUowTB4a1lotRR1Knw0GjLJgtEDVX/7ciiLHOkUAAAAVcWXtEhscAyBICRgXgYrwDARzDgH0N7/+5JkzQb2DF9PX3aAAgAADSDgAAEXsX03Du2zwAAANIAAAAS4Jk3lR3wEHSAgMpKhxR9L8wiaa1Fp9/IllP0HaB/xEDDcTVBAeXqEAU42zQcZVnfLph3r//+su2JNIk7hGnlUHjosXdR2MgJAwYCVrQJDUJtfllvHHORig2KBfhTXLUzWzWCMGFgWC1FyI1bX/qlf1eIYRJDTU/f/963BQwNkIqXW8vqPgSSUiUfpOt0nqBpg0N6ywVwtUI0dJbf6NRbCBAwWWHkGRb//SSdQf8TkISHjJDGkcNIhgYMAzMD8BAw9wGzAuALMA0HcwoHADWGKxO84hUxAQhSYEUOJYWAwYE05UAiwL9ztHPym5IIJsS9xDAYPPxqwxCRUnAgBntoeBmcRAVOOQT9jPP//V1ow6AnFBgBMxmEMPK4odgh1wsCDPqYMugCZi0tR/kaXAnmBFabUUzhNhhADR/AGKguMi4swoJoJoDvHoIiAMcXIoZkCX6jMWgAWkBJwQdBNPrAy4guJt+f1pAm0BEIdSyUhb+FBLt/+ocYNDgfQ8iGj//uSZMyH9mxgSyPcnPAAAA0gAAABGvGDJq9yjdAAADSAAAAEB06X//1BMTDZSQM2QAAGXI02rOgIBIYGYC5hmgcGBoBGYKgRJhmr5GteQuc/qnBQPaLAVGAgIojJDL1dRZzEItDkvnIPy+/RQoMAE3OBAwyBImAYlCgzXhQwmAZO9r0rqZ4f//nUfdqsJSfMMCtDA/hzPcEEIEmBKDmCQGKwxaWmyL/WcBrWBz416ay8LNAzN8CU0kjozxSRqOmReEpAXBjCNVt7OWgcCB1Qlzz9Q+wMURN1e9SWsxAqYBZQtqRcBMyJ9S//qImEJIYjIjqBw8///9QSBhewL7GpAFzFuy23qJQNxGA2YFIIBgIAKmBoBWYg4yRyCh6m7UzaYP4CICArR3V2ow97euvLoE+irWbOWNM/pd47WrTEoAEgKCBCZf9pAB3KlMqq63///5RFjLjJfGNkoGC5/ZVdjDbmaiMYuBLEozTIpf1BDKBY0e7F8mBXwMZrAUNkELhAzNnZyQHaEAECoYzUv6JkPkB7UCRUvI/LgApQnH9qvQD9gv/7kmS5B/Z1X8or3aN0AAANIAAAARgxgSsPco3QAAA0gAAABIteozPAgDh90P/6iTCYweGQHWCwJ///xIQWEBvBq6pAAAauxh22ADoAxgNARmE8B0TATmAkC8Yg6aJwlkwG+nIIYdgCBgLgOgIqEAJIQIly7EUfbOdl8ZqaxrSluQUD5xadGEhmWiMBhQ6ZhDIIGQpcaHZdZ7//vVduiBVdlhlstBxgc+lmHTEQGMiuAiQ89e63+sJ2gcXbSRNi6I6A0D4FLxCGAzpRSrOGbEVBGNHk+z+s4L8CkkCQ8uJodSwSRmaver0BN4UcJMosnQ9AFgyL//qJIISBIrUGvEbJ///lUFDoXvPkActOaq57TAFARDgeDDiAFMDMBYwJQejAiaXMGYkQ1vKpTB7AlLABZgMAHMkDgA2itjXpKpRAcjjEmzyqx5sIyHjF9fGR0m6gNPCk4rKiBNzZPRX8Nf/95PSppqCEGtlBDAVXVZI0yW3zA4MStfqW2scv///9kBeRK//1drR9RwAoYFAh/6eHML/O8g8XEEhAGBGkCMVfdAj/+5Jkr4f2M1/KK9yjcAAADSAAAAEZoX8pD3KR0AAANIAAAAS4GCHgtPJA3QVUsjgEHDL7VIaTARLgolNmdEmwQEhkkf/8lwaEh5dQd0QYv//7iMAoQDICdUAABjTRF4nBKgCBgFANGEUB6YE4EhgggvGHQgqbxw+BlYzbGAaCkBQRQuEoBQJJrLSf12ZNfmalq/u5Nt0JRSbBjRgcNpmDoRN9ZEw2A1LIfpLeGe//93HpT9f5L4ycFh4vNrTTcMKDmZB6Y4ALjUuS/+EE4TVu82GZA0YUKXB7MxuFheZlwwELgNZiTPP9JEngBEwLMiq/rMwMCRLX321MEKMLrJZgXwTECNH//yXCY4quoV0HBG//+sMMIAibT5gG9OmshsYyAMMgPGBeCKWABDAtAJMR4eg5AhNTCuoRAANYKAEMBh0wMCCEDtCwtutMv1D/bXdZ0jtiIJHTGqPEQaAwNEgg/wXBDRYKmbm9f3/5nDD0QMVAAYhUwKEEb1UiZABAa4gUL2TS20i/9YQzis2tRmWA74IPYeUmDQlz7OyRIjyFqQMg//uSZKSH9gFfyqvco3QAAA0gAAABF4V/Kw9yjcAAADSAAAAEGJlJH6jo+AjEFoM1eiYAYgMbt/PakwihIGhlhxZYaS7f/ySCY5VxqBQSe//+sM8NQ5Yl1RAAAATlg/7DH/SZMCcAAwmQDRoC0YBLMHJK40ThgTLai2MCMCpZiCKA081mORIozYu3ruP9sS+KFwzq5GMNg4vyYCDJuGxmMACsZ/ZdZy////xgJjTurlMZmkIHr9Uty28plMumGQMwWNUqSP9gawid9j54g4BzUKSyIGA+yz0CfLwewAdBJx2/TIYAk4CiQroJ9RqA0PNX/t1gkXBYG2kwJiRopf/5bCQhbLEuEGof//WG6EPDsuIQAAAMuO86rrDAAYqBnGixkwuZYrmDKhsZu46pn9t9mC8B+YCIAwyAmk4n27LawuMyHlLS//O3pEiiYkgHRgFANsuHgCzECA+Hgilmxadtc760CHismgs8DXTQLLyQczIAGBwNp1BSKaO3/UEDATh9I6KwBCoHzGLl1F9E2IMG6AORkSRf9I8AuDByUrN6jIHDTf/7kmSlA/W7X8sj3KNwAAANIAAAARYxfy6N+onAAAA0gAAABL/bphADCg9DMzwJARh//8thCETrEqIn///F8GhiPz4wAAAAy2tJWeSDACoNAJMBsCQAAEmBAAyYWYphsBgCmh8rsYFIBRCAWCgSHGTMjd57YnlLa2dHzLG1GRGAHjyYqITAWADucoHKi95Zbwz5///9pY7DzIjAG5BaU5crqNGKQiUrTpbaRf+oIFAfQ19SZFAMWUBQ4T5mRhzpmh4RmAUaTQ/WosgmlE4pL+YASDHv/4yoUJtnURzBNW//ysEQBtj6Enf//8mg7QyjkAYZwAwN9BCCMYPOomQnmUEGFqXqa94ZxscqGgoPUDAbFs0YoacJ42WRuUcv558xyqvEKAKmDcG8mm00kAPMDwXksAEvRN3N636lj8JcTI3gJbgpAHo1OE2IUAPNADThzS8il/nAmwCgFfUsyFCgAzQLBTJiaSbUak6IVAYeE6k36BHgQSgoLNE/uBgAJX/r8yD+A4t0UwgBDiR//ysEwg783C67///i/C44pFAUAAAIc7T/+5Jkr4f1YV/MQ9ujdAAADSAAAAEVnX8vDXqJ0AAANIAAAARPdOjoA5EAoLBamAaAIYAoGBgAGBmECJQaMxIhgvgOIGjwsrbLo5I4dziNm9Ta3rdyhJAYxSXUFZMIQY1LkBRM/tNjlv////luvLWyhZPZXU/OYYWCGUWCJba5/1BLAaY/UmgQ8AC4KHJxApr83PisBZCYL/s4nAGDPP84F8kP9+kGiB4upIP8PH//Ph5HqHWNr//+L8bQyTDAAAEj8oBa9SjqAKAPw0xwjNcMGQi8zxgyDSBENDAhWksMa+78FwPNx7POex7req8QHQATB3B8EIATql7TClBZEgRXWnbWPf+oojVLw5wGUSAsWJ1KxAgM8+AOAjiLqSP/CZQKAX9JEhwAiILWkVGKPWpIgQKGys39ZkCAcIOR/WFqU/9+oJBBhc4cJ8Yj//58PIb4vzL//+KafFtPVRQAAABjp02EQWh1GTDBhQRB1RhNBdGp4B+atwmIYKGLAQl135VjftnE/QXqueNXmGdJG0EBhmAsgQAnpecwtgfRIFdzJ+93//uSZMID9PVfzSPbm3AAAA0gAAABE7F/NIz6icAAADSAAAAEnfpkwPx8dAGTiAWGE+yBNiEgGrgAiXIq/9YTOA4I/qMx0ACrALBCfTJhT80KoiIckYq/rQBqaECJq+oGgJ/9+oIRBh1GAX7Ii//+fDDFvFpFsf//6hWSWGTIA7g5biRcKATAoEYwlQBwUBiIARzBsR2NMwZU3QURBYQUwLQIS9i3kmnZa47tmPzFPy/e7eo4QmuHroBAJrwiCRo3KGGgZBcor4Z4f//+Mqbs7qeph9Fg4Uw9ZtygqgEwWvzAgCXrFrKTP+sIWwLNE+cWbDkgZVeBZ6S50dRkjWo6YjKg6gPLt9nKgNrAiYFdn6kQBR7v/foAhJBQBzMmAQBRU0P/6y2ERRLs5MgwEWv//qEtC1gP0NUwAAAA18ieWDxQfAx2dGHGUCZlDOYLqbxnNkDm1AtyYMoKY4BAOgElxGrvNBEalU9ent1O42pa/wUANMTYJgvokSIgGzBtGrMBIBFuEM01XW/WcGuIqcFxgcJKDp48H1lwUuB2iwGkCiyidf/7kmTih/UCX0yjPqJwAAANIAAAARcxfy0Pco3QAAA0gAAABCRS/ohAuB0h9ZxMoCVgEXwsXJguEXTbYrkSDPgKgzi1fWkTIC6MERkmn+ZAYIISTfqfmAQgAcUK9RZOEgG9Hn//WS4REEKyxaA2lv//yZBEFF6aAAlNSt2T9SeAgCBgKgYmC+DMYEAFZgxArmL6YUdrYVpyC1iGIcBcYIYBYGAJVBaBS4Z53HTmp+LSSR51pTAS8QqLjo9pKovLZGDw4eUwhocECQFcaHZdZ7///L8gssmHQQOvodAj62pY4YUBxlOJA5LutO2mf+gEqALiH3KB8qilgNcsBb8NAmBTSVUtRmTBgILg8sKmedn1LODdAphDV4+DdV2c0AzINF/1K5MDCBaYTzOYoAUMCBkUv/1j0DU0I2PHQmAFkpf//i8CiAGzRXUwAAAA1XiDS3QBoC5gKAHmC0BUjOYDgBxhlmVm4iF4Z/UHZgTgOlUABuSI6x27v41h+JBK5XdtZVa0lbEQB0xZEiUNRQMABysvDygZfJqO93DX/+twUo9DLOT/+5Jk9IP16V9LQ36icAAADSAAAAEaLX8nD3KNwAAANIAAAATH4vGiLA1ntxZJj1NmBwUrmHqVJF/zgTWAxM/UopimAPzB+hTNyoz7loiIQAwMEIMUl/oE2AsXBEnKjt5kDiBs36m6AW7BQzZzA2CEMLA//9ZWCQYhaw8gdtL//6w6gbyIa54ACY5SBv0mAaAULAmlAyhgXgEGAuDwFF0zGxKWMtOdQwOgajAJBDMEAwgALSlqPu7T755y6N446rxBmYiFRrCXiMCr9EYdNyZ8yKB1MIfpM8M8//88IbbHIVUzFCXBQnjH07+JfmZCyAj7D1XS/9QJsgRcH5kx8eQc+B0QiZNjULC1LMCfNg5AA7KPB9vuiXgBCgKNiq7egAceLX+2oxBMuDiqWWEhthprt/+slwiKGG7DqBYW///1hEAOEMLltjAAEACrk+rSnBLLGBIAoYSQGZgTgNGBaDAYciPZtkCKClH5gAgZrCmHQAyNkLPWmOfPyh85BWs8zpI21gChM524hgAorEgiMUfYZASmsSma29f3//KIsZcZCcYw//uSZOwD9eFfy0Pco3AAAA0gAAABF/2BKw9yjcAAADSAAAAERgYPodnqSJkgICzkMHgFa0VtIpN+WQhVAx11lgzLAd0B/0LfSgaFZJtErDiBCAAzYUgyKX1HR9AlEEEjqvpgYoOV/9tSIRPiAKGkYAhEiSpf/zpJBMYJq7CkwoGf//6wz4SYQofQBjcg1ujVVBAaBAFwRzAJAYMEcAwxIAuDkOB0M7CcowXwOAEAyr8EANSTK5+UQTXp5fQ6/l+cfsuweAKoMEiE0EA84DezGgRZc7sus5f//+q7wKJV3IMkk4MKD33tW21M0lcxSDmIxqlSR/og0UAp87lA3LgzYGiQgixjgJgZ8soLUmThVDdgBTiug/1JlwB64BpAX0E/MAMCQLj/21LBqjFvQWozLgNBInND/+skgaDg89QZKJ2X//9YiQODh0JsEAAABHbDX1SOWMANGA+AMYVoCoKBFCgNJhMKLGvYS6ae8g5ghAggQCAGhFcojA675XA1WHZi3TfvKzLnZLtHgyqYJFbCgUDjqgUFmUq17p2/zu//+8no8//7kmTtA/YKX8rD3KNwAAANIAAAARgVfyqvco3QAAA0gAAABIowAQCry8sNWad2BCBTIC3HjRB1/j/6gQnAeF6jhkURGQGC5AHDi65FS6+kVSChfkAKQMibI/ZydAODgpFLbP1GABhU+3vo+BQuCg80Wosoi2hQEe//rJMIjg7bHA6onxH//7D6Bw8NVJIA1jIoTCgAA6CgYzDBAOMCoBkwIAbTBPWcM5Ues2jIHDBxAcAwEggAIYIi/SV7aOtSxTKU1aa1jWlMaBgXOhNwwwFlvAQGHF60ZWACscOU9jPDD//dx8U/YaaEZOBgsXnNo7FCsoxwxAoDV1Q7TIpN+sJGgeI8yQL4rQDOwARSBxk2OgoJ1oETJINEAzQcnE/qWZDVAi/BEBLyPyOBMw/2rbpA0BgweezEzBAKE/I//1kmExQeJkhqg4I3//4x4LDguSWqQAAFqzHm4s+JACjABAnMFsEowJgJzBEBPMQ0vA4hxWTglY9MMwEMDAjOCWnYBJHTcyG4/KLk1+erseaKSBQ1fHyITF8SQQmOvyYfB7CoNoL/+5Jk6wP2DV/Ko9yjcAAADSAAAAEYfX8qr3KN0AAANIAAAATus///5nGIAgZPwwmqgwESvVh/1cGbxYAj07tNil/oA1KAqMLWssLJoY0DF4QGkpPIkOMm1mxFg2YAa+Ks1dvWYC1gUfgWFlxNDzoC5VP71r6Y7AoyPZgbgmMGgv/+dLYTFB42SFcBgJv//qDJwzQX3UaABWuugtOGB0B8AABmB0A0wcwAADjCbIvNaEPA1pi1jBlAEEAAqApcr6w7Df2IlnSZY63qvBAyDzCLCBgLWGBoKNDSgwWAGWxqlyx////3HmxQ6ykw+SxYMxa9blCb4gRoQGHVtYv/nAzwHTV84mYDlgYBqBYmThgTZm2mVC0IiDYEbq/sXwxKDBZ5/WZAGAjb/+G4CgZs4kQYTR//6y2GeCraNYWH//9QiZeFaHoUAAAEY33UV3DAXAUDAOQgSADAZA0E4wG0bzHZGmNt8UUwkAAB4EMwwCS0irWIvc3FYb53eOs6kBkAYdpehQgZCBAE/t3DmVk0Cz1nvP//3hAbVbDSzLFEaJ4pb/j9//uSZOcH9gtfyqvco3QAAA0gAAABFc1/MI9yjcAAADSAAAAEGgKxigK16W2kUv6gxcFMj8wSRHKAxy4ESokVEaYvqWYjmgpEIi7fUiUgFjwOHGr/RAKBlr/fpAkMDSkdIwBMCLal//WVwiAEXrFYHtX//4eUkBXT3LS7UxnREICZgNAJGEQBaYE4DxgbgrGGAhKazguBwDEijw1ZghAAA4PFlWnMtXgzXceh65Wl3/hbhwKgk5mjDAodXYFwCcWeo8hx4CRect4Z7///stgl3k9jBiWBwGjNqkhsvoZBQg8Xs8P/50RIHffOIFMSAAG4A0IIuXyKGDtYkySBqACQcmlq+pY+AheCFDNXzIBgo/+/OBI4MJeZlwIBI41f/zpXCYYPHi1Bvb///UJCGgBqpdUwAAAAs3ILbI9Y4BwIwHCQEUwAwFjA/AaMRABo5HADDgRTQMJgDwwBQFgUD0k0KElFevDFYDdCQ0+HeX70jRZI5KCiQRAIqiQ0z5DCACWBjk3Uzw5//q6+CbUpaaBlMTGxs85TxBF8xS1RABlcw9SpIv/7kmTuC/WTX8uj26NwAAANIAAAARb5fywPco3AAAA0gAAABP+wfgC5F+UkTYZkDPpwdRJMzGsUkajpgZDvCmob55/smaAElgRNCugn6wRIi4/99ZwJoA9ReWWFwhpzP/+dJcIig3p2JsKAn//+5MhQYGZVIA7g5axGtigBpgNgJGFGBKRASGAKCaYVibRslELm981mYYYH4QEAYCoBbQU63bdhw5BLJ2L6vZ9xpodCoGO6pMxCDgwCggQmj+6YUBKmT6yqrl/8/+4S+VvykqYIW5cuOY24cU3GmwY8ArXpTljl////9SNFCVv/+6CvMKLgQ7lr4xSS/PnedkA4QSKAAgmUl/RSICAT0FelZvlMDgErt+p+wIbAxieYpggMIcj//OkuEDAuu6hLw+z///jUBZIbWfUwAAAA1jPPLFgQAUBgUzCnAKMCABMwKgYTBNT4Mk0bc1m3ZjBmAADgJgcEFdo1rvir001Pbna17LeVV9hQJm4moYEEaRRgMBHEnQGHJNV+pba53//96glR1/k0jGxMFh88tHLH3RkMIroSH7//+5Jk94f2CF9Kw9yjcgAADSAAAAEYMX8rD3Jx0AAANIAAAARTuTP/UOsFvD8wc1ImAcsCj8iBgP5Z6i+mK4ApRJB2+s4SoTciUTi/sBgQxaf9XsFqgocPs6BuERBBF//1lcIhAytQl5FF///WH8C8hARPVWAm6vsSgLgEBMwVwNjAcAZMDQD8w2SzDdbFpM+yDUwJwPQQBcCg6OAaDlY2aO9DlulvU28dVZp6R0JGRYOKCZu6ZhytJDSEULg6jvdw///WcQaJRt0MVnQOFkP4brMBMjocwWCFqw9SpI/zAQjBT6/OKLIvAS0B0R1MtM+iWyJBugMaFIMil+gQ8BZGCI2aJoeUwCB6/6ldhSYOQH2WYHxWweZ//50thCCDK1C9DgG//+sNYLhEhLY0ADAA7uIMzZAskCAMmCQBkXDMBIBgw2SlTdLFIMnuKIwNgRkewMTBCAV1tAZWxSR0FypR28N3KF6CEOmf30YPC6BhIFzX2BMKgFiEbpM8M+///jKm7O6ghMMokIEL9TsvfxAWZOM4QZabev+cBqFB3w/zJjci//uSZPUP9dZfy0Pco3AAAA0gAAABFyV/LA9yjcAAADSAAAAEAGVBA6KRMvj4LHTKh4MhgFRh3oP90T4WEA5UWn9ZwGpJX2qbUiDUOCx184gCYET6l//OlYJgA0/PBmG//+sPISYaqLYgAAAI/sCMnhxC8OBRBQoAKAmCoIxgaptmW2LkYWsbpgSAYhYAQiBaVTDWURZtZ/GF3L/MdV5h9wYEjhTFDByuIEhYxhvjC4AbHEpmtvX//7uQWo3QQsx8ISYjvZP0kTQ6GCF8WTZNLbSKX9QNA4U+vrLCJSERANvhcyXmJ5JtIqkRDCIGcAE6kj9SJSBAyDCxir50B5NH77c6EioLAUtM0CASSav/50thIEF5tGoGgt//9Yf4NLDeXiQAAAD8n9cJYViZgKAGGEoBKYFIDRgbgvGFkjKapRCxmZQ6GCiCAYDACpf5PlN5yWXPLfxpsqlzvcKeHCzZ1UwGEQoiKYIB5vGahxpUufmXWcv///nZzF+k3ionk9Ijlel7mGWRGYnAziy7FJH+sCosFtptywmaDHgZJiCjcghcHf/7kmT6A/XPX8tD3KNwAAANIAAAARcdfyyPco3AAAA0gAAABGZ9ArlsMkAzAEiCf6kyGARYAiAF9B/cAgYbf7cxCZsnUlqKaIpEO23/86WwhCBcd1iWEyr//8Z4FgYb+VjAKtyDWiNlFQIhAA8BAPzABAOMDEAQxDAnzkoBtNQeQkwIAPzADAKVK8CZ7Tm6vXIKXN/q+Vrl+cg8HAU8UOjCArZMNA46wBxJXp4vdO373f//1depO52VqmUReNF1zpBL3YFQOYyZIYZHltcf/MQmbCng/ziiiK8BiMgDSYnUiAmKVSJsRIMhAFXx3GqX2c0BsaBaAW2fqKIGHEo/7cphAfDe0KjEzAoEDnI//zpbCAMFAzrEuDnpf//QHWCg4NWVEAAABH4O2wxwwYAGYD4Bxg+gShgAhgDgZmFkfoa9Ql5sTN2GFCBsJAOJkrsLpuy1iJz1mgpaWh5ljaioVAxx9WhcKQsUBxtmjGJgIteKU+GeH///hE3rh1ZZhpChgThyvcmVgjGicMEAll0ZpkUv50EJsGMj/MkC+MoBi4gEmBD/+5Jk/4f17l/LQ9yjdAAADSAAAAEYFX0rD3KNwAAANIAAAARy+QwwfTKhIho4GJAGaH6KRMgLqQRETZH7gKEC3/tzoJCQcLNNA3CYgqL//nS2EwQXHeXgvN///qEvDSg/E0MAADXHzZq8wWAoMDMAEw6QEDA+ApMDQJcwXWnDIjLjOR1tkwugZTBNAMT1CgFA4A1rqp27teUUs3+FWmiLShgKTN5RkK0aQQE5gVJIMBlhEG0F3W+///k+qqLjF7jEApg4RnFkUsd9FQx3FQxFAB/a2Kv8ohAzBU4f0Skal4QlAzd8BqaSR0Y4pIqWcLpOh6IB4QW02Z+pZwjwnRC4MwTQvcuhReaP+tfSAoDBZ+erKBeDEQZg+3/5ZLYRFBQe6AkYLDk///qDOxBwYyPKFAAABHcX2XjEhgB0wAQBzBDAcMAgAkwIAJTCZJSNXcL01mCygMGcsgiBKooJtOJGYduy3vbG9XaB8SAIGAmOWRV8CQQaUiwKLTkyqlyx///9bjjZM38MTiwaFED2KeUJvjCRBQMdW1i7f1BCTCjzzizA//uSZP8D9fRfyyPco3AAAA0gAAABGZ1/KQ92jcAAADSAAAAEdYBD8Llk4XCbTbYtk8HkBuiXF/2L4CwMKFzR/qAaAlv/9IUgFBR7UYBxYqL//1nw6geKoU8nv//4lY5gkp5AFy7ADM14CMBowDgLTBQBUGAFzBIACMUct851RDjp9FJMPABoBAvAwHkwmUAXQuuB8JNj8QpLV2Yia8AqJzhM8AoqQ1MIAU8akQc5RIDNrFp2/zX//eS6JNNFAGYPaICAr7UtqiZsZ8ORjgJq6h2mRSR/UCbsGQm3MEi6MkBoHgUtjYKA1SiktR04XhpAuHIU87daSJWAEUAtGKrt1lgDHjio/tWnomQJGgoqKrsmQwGhUgav/5ZK4REBQmioNyJwX//9Qa0MyCwM9RAAAARzr8MnhAVAnEgRQcKQAgQjABBSMDtNUzcxuDeyKJJhdh4AQICS11jTL8xym7cuX8e4Z0jthQFHKFKAAq9YFBZwiChCHYg89i3hn//+7kGqyyplxkAAFYpfKfljtiIAGQUsTF+1zv/g0UgxY2pSBTFoAP/7kmT4A/WAX8wj3KNwAAANIAAAARlVfyivco3QAAA0gAAABNwBigmy+TiD7ksSISAgUDF1Jf1HSwDR0K8dV9gBBp9v76zIIDQbUjmbCAoedv/503CYALjMockMw3//41QWAB6BVQBjlSxp+RGBcYEAARhYAOmBaBAYG4NxhPKQms4RwcI6chhPAhGASCOUDRwgsAGEOFALkxiNUshouZ2J95A4Bngw4gGYkKh4zr7jAQWeuSTdzeHO//M4xAD9IEDCKqAwQicxXkiLpi9nioIUth6lSRf9gQuwWutsZHjYdoGfGg6aO8zG4WFqWcL6hzAJaRgH2+pMgABKoESQroJ+PoBcx+2f1nAaoiYRzEzBACDtIv/+dLYRBA4ezjOAsBb//6ZUBYaLSeUwAAAAxrQS1RsoyCFIDO/MlQ+SDD6EBN8YBg2ymKTCTATMDQA4aAXGgBGyq/iUNzWNqjy7rG1Ov0CAAzE8B2UMWFAgD5hJjMmBIAW6UM02OX/RHUJcOaHIgbfOAw5HcVSuQQQXA7AkAbCM0XUkf9YSahR42s4iWBT/+5Bk+YP1tl/LI9yjcAAADSAAAAEYeX8qr3KNwAAANIAAAATwKZw6MoGhXdti2OcGdAYUKXkVfZIqgCgwotLbeo6BUmn99+oGpQLWF6BfCEUUF//zp8JgAoGdYlgpVX//4fwLih8xvrCG2UOmCAJjAjAOMIkCUSAUMAsDUwvkSDc2FNNdmIAwTADjACAATTVgZPhEKrhZWLVDFbOVWVOCIQocNgIjD6ORgEIHRnMJKpPl+pba53//91HjUbnGRmRjiGEN1I3GH3GAUYDbQCI7TpbaRf+UwTfhSQe5hNB3gDNQpeHYTA1yypajMnDQPbAOvD2ef6zIjQKwwtNMl/JQAQkl9qn6ANRgMJJoLKBsGQg0x//50thIAFCTrDvDvS//+sLwEwDST6pAAAZWZFCXnFAByYEsFDLGBkAaYEAOZgDrqGJWUWaNEn5gqg4iEBowCEWAIVr042B56LXNZaq3JK0YsCkzRMgQHEixIAHVWEBl4t+ET9juGv//yjL0uMX2MJKoFBqGaazPM5MwoMxCDF0w9SpI/yiEYoEoKGpRgUT/+5Jk+o/13V/LQz6icAAADSAAAAEYEX8qD3KNwAAANIAAAARQwCPQWVFlydRfSLQ7QSAgZoMOE2R+swHWAs5AkfLiaHrAw400/qV2D2gYYPtOHAKgQ7KTf/lkrhCABgV4tQLA3//+sM4GXC3sl2MAyxeplLci3pgRgRmEaCYYEQDZgrA1mJaikcaYq5mP24GD0AskeHCIkkEAIwB7JbIYP7j3fLk3ACwYgDIyYWEdAVSkRBSZtQaYggyqSG5RXwz7//q62BAhKWCmL4ADw4NTikPtYC4CmMRShxA1M8P/BrVCjTskaE+PAGlaASuDJk2LQSialmBEysFqANcJIgm33YiYIhoMVlo+ytZkBkAVv1K3RC24LPS21MuBCVJtX/8slYIhAoediLgwO7f//CEAGVDLB+owAEAA1jBDM3gLnmAIAyYEwHAiANDgXDDrHNBXuZitxvmBsBeqRJVDKFtdq08/RW63d8zwlb+BcFm/WkVAGj0Khwytsh0FMphqlrb1///cJfNvyk6YATaEuITdSPqpGFl0DQGwaK2kUm/WE3oL//uSZPsH9hRgSqvco3QAAA0gAAABGLl/KQ92jcAAADSAAAAEFW5xEyE8gYO6A0JLyJFjJtZsRIOKAOhkSRf6kTIBywERI1S+iBYuWn/UhqRBMaDBCVRmwciIu3/8snwyQKBzdQl4fZP//8UMCwcS1QgAAAI+27iu3cGQDQMCKYXwBBgVgBA0G4wZ1hTSNKUM46aIwZQZEvSUEEoRTxijjwLypOUm9fy/OQOYAAh3o9gQVIJTBAXOR0syEB0knVl1nLn//7uPSrK7ygRkYrCRab2RTkPslM5gUx2CGWxqlSR/rCUsHGW5gsuCtwMpLBFDHATA6ymhQTIgREM/AyoQi6C/qOlAGsQLqDNBfYzAUOkm39tSwgRhoKC1HVg3oIcav/+WT4TBA40fUHDIIv//7F8FhwfM1RAAAARjagV3p0GgGAYDgwggDzAXAOMBkFAwZkETPsFGNC1wswMAG1NwIA0qkLmTTsYfyU4VrNTuWNqdLxHKRGYJCrKESjfgzKEUxyT0V/nf///OIPRRswMRmQSDEP0krhgZAZhxNiw4gW1i///7kmT1g/XJX8tD3KNwAAANIAAAARipfyqPco3AAAA0gAAABPCBqGwv6jEcoDBOgUNFVRDTF9SJdFmgMQCRSb9zQA0MDjhuz+iAECPP/bnQiVGbVoG4QBi4v/+dNg/wUBYtIhjf//i/DQg+p4QgAAAY5N1W0wkYAHFAHjAoA/MBEB4wPwMDECGPN8AKg2cGmjCrAwMBgBMwSAE4UundaO/tNL9UWeNrGtSvsKAU5IqDDQOb4RAY2vZjGQEa/GKfDPD///xlTdndS1MPoUHBmHqWmpWRGQEcYEBLBozTIpf0waOxMT/c0MxSAGJpAMGCLl8gBg+gSZJBhgAA5cWr6KRdASfBRCbN6jEAQa/+3MwaFwu/mBuGQg7D//zpsGSBQXlQKAW//+oO+KOHvoIwAAAA/CG2cO2MGRiYYcKTkQwYOemGUgobyw4pvkrimEgB2DAFgwBdjKVcBQ22WCJ6crVq2eqs03ULgNGGuI6GAVBgAIEAtHSARGAWphAM1V1v1nBrhwywNsDmKwdbGgRMigy4WIAd/MAd6IqZLV/mIJSxsvv/+5Jk9QP1ol/Lo9yjcAAADSAAAAEYDX8sj3KNwAAANIAAAAQkal4ZUDKvwLSSXOjqKSOdUXhcQKbxtHnb1nCyEYonk4v5KAGljD7Vo86BQWCydDOIBesNJS//lk+GuChJ4iAc1D//6giBG4GKCRe/yLOpA4IAnFgYh4Y4wJABTAKBxMAZcQwAyBTiiQUIhTjAqAMBICDh4LAdt0THXfyB6WT0Vq1u5NtgIBSCJkABKgGMDhg39kDFIIL4u9GabH///52cxdYdAQyukQINoJuCCUAgVwmBAEwWLWUkX/YJ0yHvrUYlAUOBguYBxMghcIumzs5IDtCAGEIoxUv9AnwFlIIl5omh50ITZn9618yIKCy487JlwGo0iqv/5ZNw4QMFqWHCI9D//6g0UPMIxPVAAAVsYadl0hAAwYC4D5hFggGBQBKYIgNJiEoOG6uNCcnYKIKIRMEUAYwwGwgLogMlgmLt0iFzdfXcM5h0xAIjaUXCw0UVMCAE62SyZCJNPbIr1/mv/9XXqTuf1YUyWNRYut9Jp+KM2MyDwxQC11RmmRS///uSZPmP9gBgSsN+onAAAA0gAAABF/V/Kg9yjcAAADSAAAAEqBpTIkl0ZqK2AzxYHViQMBqlFVZwzWOAEXUbJ9vuiTwAAYFHRadussAIJG32rfmQNAgUVHnQKZcC1IaG3/8snwyYKFsRILlv//9QoUKDAy0vl2pH4AGQPwIAyYEQHQUAJGgYDENGPOPkFY4jDFzB5AlEQBwNA6YkJbyvS0sxUtynP/wp3YBIPOnrowyJU+AuATklLARnS4geWW8M9//54Q22OEp/mIk6Che7krjDhigCMcsAoN09e63+kEZobGlqOmBZFYAr4DZCbNyoaOzsS44gaggMCHJpFXrUYkcBCEF9i6r50DBkSQ/rfmQNCwLFjXOwboBvSP/8smwdYHF3YvBQGf//+5OA4aG8nhAAAADhbchQNrAjAWMCQAkwtAGB4DoKArGFGqiaf5FhwxqVGGwBQYDIFYWBANAcSm3Ogi1Zu2JBa7y3OSdSB4wXhA4HgMKhwyz9DAwEZnAFDc3hz//8oBYS7yVRjZGBhGd2XUsqT1Mer8AgZS2HqVJF///7kmT4h/YeX8qr3KN0AAANIAAAARdpfyoPco3AAAA0gAAABDAJSwoSfZM8bjZBR0FLA7ybGoWF5mXEBN4DGItnn+pMuAJbAiKF9BPzIDGBLf31mQNEgc5HQL4QDCMX//LJ8NQBxqgM+DgT///isAsFDnnxQAAARvJxU6ndBIeZIDHQDZkIoZexGD4mOZ5A2BtHM0mEeAETAmIHqavu/1qXxidl3xzPeWNqdRWMU0F0wHQDi9IAAVMKUZMwHABVKnZlVXL/UmOgRQzFyAbWEBZwNMnCfHMDV4HWZgFWSDGKS/8yCb0GB+uiWBWQI5Q1aWECskz0i0QUL8gYoIQVJH7OToc8GFC2z+wDRsqv/fWYBM0J0RUswNwyEHmf/+WTcRQGB2UIqM0v//6w6geAQobqcAAAALNaOs+eEcAgEAChgbAcmAiA8YGYFRh1D6m+QIQahLuxgcAnDgCZcYBBlEZ9nGityhoJ7lzLHKlfYQAc34xjAwlSGAwKOOKoOPSQLfS21zv///y1Hn5R1AKbR5iVDMQGOAARsADB9p0ttIv/cIv/+5Jk+AP2DF/Ko9yjcAAADSAAAAEXnX8sjfqJwAAANIAAAASwcbS61mgy4GYJgs/IgXB1lnoE+bh+ABUEdjt9aRDQF1YIhpsj8zBYqVm/vywEJIHBUazig5MQK//86mKcDBLKEREkb//6w1w+RaSsaB+obZQwOImJIHpUhwwzbkwxDXDbQGNNASDswcQLzAAAMIgL2WKxvqsjLOW5S6rrPLGtAIjAeMGkQEcAmi4iAAMQsNIOBoKAB5ZP2M8PWcG6IiTQsQB3wFpw2S2eLYyIHbtgZ0UI9J4upI/zoTcg5N1HVGIpwAl4BoEXXJ1F9ErESDFwATcnkUvrUPsCDUMFmCf2AGHFr+pLmAFQgOOJ7lwJiSKq//llMagMDnpDQvJv//rDvCTiCR9AAAd5I3yhYKAIJghyYcYwLgETAMCLMAJoIxZiEzIjuoMDYD4LADmBADqxjwAM1ZvD67ZPUw5T6xuSVugqE5kKrRgmEaQAqDZl1DJgeCaQj7yivhn3//mcYgB5k7jBkzDAoAH3iENuAFwJMWi9HiRhFvj/50Gk8EU///uSZPeH9edfy0Pco3AAAA0gAAABFyV/LQ16icAAADSAAAAEsZmhfFmAZ+cBaoLjJsYwoJ6ZECRBqBA04QcaC/ugTYAA8Fp5UN0PKYGMJmf3qVuw9hR4fZRTNAKBQu9v/5ZNw7wOR3FIAsJQ//+sP8FBwWZEIA1jATKXCWyYBIBpg2gSGA8AqYGAJphYm0Gr+MuYub2oAAvAIDxhYKo1rcU3fhz43KKl3lWzqvMQGFgUbQXI0EVCwqGDKl0MMgBpMSq1t////7jzRn9XKYrJocJYepa1ClMYeURKBWnS20il/hArBZV60TIV0DBwQUKmyyaMm1GpOikQFHhVSb9EmgFjAKGjV/WcASILn+3WCYEHDXzqxCQSZv/51xagoHdYlg7UP//zYLvEHm0wAAAA7XbostogoBGQATmBACcSAIiQOBiZi6nSuJcaAlhBgYg2AgBUUFBeJlSwC13IcaGJbHNT17OkjbkBAHPZrAw2GBIMmDAWdrr4CZKA5xYepbXP//zqPGonRMDMmIcMK7qQ/GH/RMBz6MngprsaqpI/1BKSCv/7kmT7h/ZKX0or3aN0AAANIAAAARbVfy6Pco3AAAA0gAAABGc0506TAe2BmNYBTsXARQZcptoD2O4IBAGQGlBavWo6LoJ1A9A6pfUWQQIy6r3qPaRRBCjBQqkzsTYNChFkf/5ZNhLgoqdYZMHvof//YSMERIOUPEAb7DjB3YLvGA0ACYPQCBQAuYAAGxg/n3mhWKEaSrbJgzAKhgFxa4RAFZr8TMQpMqe3O5fztiLr1OTAQwAG36TXN/FESP6nEnor/O////aWCX6T2MHHxFKIzU3EEdzBidDhhAtrF/84EkoOfNzFSI5QGMYAouKqiGmKVS0i8MsBaOSTP+mTABpIFjBug/nAKDEv9tSwkVFhSzA3DHhUH//nUhuAwLjqDnv//+JeIGE8oEwwAAAAxyirzPyMhpjgEdMLmVihnLYYMyd5mpETGzAzQYR4LwYDaYCIALGlgfWM3r/yaG7lN3HKzaf0vcYloTojAQe4YAYMMMXIwHgCGDxinwzw9R0agd4ojZA4IQKVBvlo+aiAwHM6AY4SI+IqXkUv5SBopBSme1H/+5Jk+of2V1/KQ9yjcAAADSAAAAEWIX8vD3KN0AAANIAAAASaBTFCAA3AGChBy+RQwfTJAiIZ6AuGKal/ZImQCRYLLSs3qWAKNLr/26waGxG6s4oQHENf/+WUheAwXYphdz///UGtIcHzNjWjrdoNEYFxgBAKGB8BmYBIChgTgPGG4RibzwQBtzqYmEkAyAgIl5DgMWzLoPlNDGbE3KeZY1pS6QgC5r51MnUtCwdMP70woCWwR2td1v//+8l9d+UnQAmUM5JNyh90BBlE5Bxau63/1BFGFLzczY2IKBkzoKQSXMx9FJdZw6YjtB1wlj7fWcHyDVqHymS/nAMIEL3+3cICIMDobmgQiSdS//llyMBw5lCKifl///UHDE4Bxp56MAAAAL2DpsgZ+FgFTAVAeMGsD0u4YEoFpiFG6HAQKmchx2hh3gEjwHBfl7GpRBcjrP1fjFLTWca1WSNFIRIYZn4MB6FRgcPHDLwBkspq70ttY///+7j0qyu8u4yQSggvOrLpmDCUBmDW6YAAS1YepUkX/UEloO9nudOlAUOAZ1Bu//uSZPsP9fVfy0N+onAAAA0gAAABFr2BLA9yjcAAADSAAAAE8mC4T6bbEmO4EwgDxZQRV9aA6wFloIk5cTQ9AApGVX/Wj0waAQWXnnQKZ4EAEQ9v/5ZTI4KHmUHlIgv//8SsKBQ08WFiRNBc8EAbEwN4YOUYHgDpgSBGgxpYybCcTotBIMQ4A0IAKEYFFgMXTwir7vTeeWTS2XWrsxE14Akam3aUYREisIQETx4VImyiU3sior/Nb/8K76MYkSihkFUBBEd+MRuHFrmfhMZCBquodpkUm/ghXgufPblFy0NIA6QDHI7CYF2SqlqMy4cGbAbBDbPO3uxPgMBAUrEsfbsfBy02b9a+4foDEJ51Fk6F0AoCRf/8lXI4FlR5IRiDhC///uO0FigWgGsgAAAA7dcJiMPCICswFQBzCFAmMCABswLgXzCjQENfUY03jCuzCLAhMAQAImBSbSWzM2mU8SprVLVy7hXlDtgADHGleFAXBIjBJvKZgI/tMl9jPDP///xlTYndSNMQoMICr/TMxAYwADFawEinA1nrf5mEzIU1tv/7kmT/i/YcX0rD3KNwAAANIAAAARiNfyivco3AAAA0gAAABKLKiyJUEtQf4pplVn3LREQ0UDCAC6kv6jE2AguBQUXUvoAKFj39b9IGgYFCzbF8Ggoiy//5ZTHQFC9zQLiN//+LQFrIz7mAVtvUz9sBIAISAPgwD4CAImBgAaYeIQZvrgvG6ymwYYABgCBDVlBQDdxf7/SSMQirbww72xPvwiOdRGjbLWGRAYp3gMCSt8ku3N6///dx61G7j9mQBaPEeEUdmmUNMdpcwOBmCw9SpIv+sJEwW5tzNjciAGZDAs8ImXx8FhdaBfNhNgDUUhHb6lkwBFoGMC+gvzMDDATdv76zgNCwaUipZgbghACYP//LJmcChd1iQB2W///EQDKBq4tqMAAAAFy+5C738BIEICA9MIoBIWAiMAIFAwd0UTVnFoNjBpUoDyMAoAYmAqHFw31jbu24tKpTVq6xtTsDAwBnRC0IgUl6Fgma5wJjIErDQzTY5f///9osX6R2ESeUSj8xK4YUzMsEkILsPVdf84EhoO7+dRKQkICcIWKnGJ7/+5Jk+of15V/LQ9yjdAAADSAAAAEXWX8tD3KNwAAANIAAAARJtZWIkGpAZcGRJFL9zwWFA5YV2f2ABGGn++tIJnCBLrOHA9MOAS//lk6kFCdYlRPq//+sMkJkPddDlqKue8oXAmBQOBiFANmCqBUYHoVxg8PCmiobAbvdkBg+BTGAeBaYqBBg8Iw0LAhFdlLU4el2UQoqWtKYaT1AImPE0MwKMUqjCIMPcMgSjQ8AW2gWevd//3q60YlATspqmayCLI1e0Ox5sZUCAWlBh8CprPzLjVJvyaBIyD46XKKZODNgaqWApvFwEUFfI9BNAzIgREEIUDbihpmifpImQroAsEC0EnketRKgCJy+h75/WYhCwAsAR0iYBqXFyoL//JVEvAs+ZEMmBEHf//6wmED7goHHphQAAARy49KynpaEYiR+WmWcc9BhjEdm0ED8ZoDuZg0gUiwEgBAPdVZ0Hx6XUup3d7LLdyhjwwAqYNQcxgAAFT6KBh3hrA4Hhk8Ut4Z8+gTY+yqLWBkvIDQ8ihfLhfGiBy3oGZAClSeRSR/xEQdr//uSZP2H9bBfyyPco3AAAA0gAAABGuGBJq9yjdAAADSAAAAEfllRiK8ABEAkKNVEyYvqNSdDoQCmhOpN9aiVBJeMucX64JDFf79YNQwUCczQC/Io7f/ztEKC2QUF1z///4lgdoWQYAAGNx92YNzBgBxgLgOGCuB6MACGBCAyYhhghwnBWmKDQ0YEYGhgQAOiROMBAcmAy7lqvhFIrKZ3ljdyvHFtiIQGRpuhWiiOiE0h4TFIXapH5i7rP//95QCtlryNxjRFA4fOLKo+6AjA5j5akxxor/H/4bkFyz8soE2ISAZGsBZwQcvjoME6aBEySCIQDKByYTV90CLgEHQUblRNDyiASVNfvV5iF+gYSdpZMQ+ALjHn//LMlQobWcE9htR///8coFiYiqoUgAAAdwaepY46IAsB0HCtmBMAWYCQOJgEJ8GUASyYtsWJgQAihUAoKgFJZcMDqwU1qpuN2/yzqStwBCHTcbUGQWisFxAaGzhgcCMNhqlrY///+s4AU6ttYMck4eHED3splRYxYrAoB1rQ7TIpN+5VBb2/M0S8Of/7kmT2A/V/X0ujPqJwAAANIAAAARidfysPco3AAAA0gAAABKBj4YIlpJHSHGTa0ieDogLVxtGr/dEvAEEgUVFV/W4GAFFb+pXREdg5CfZ2L4NAw4kf/5ZYphQlUJWRyf//1DXBwIUEogDLF3l2u8BAEzAnANMJ0CowJgITA4BfMMVMg2YRdzP2m4DgbggAwWDN1WN/WLTVWBq1BnzvLc4/ZZQ7gkzAQsTRBAZOcwEyoCUgnVl1nvP//7yXRJxUGTA6vLgvtQyh/0TDNYwMggJ3abFL/MyLguWfWYmZMCEYGIzgNIyCFwgZmzsmSBIhCFABGEXUv1qOjcBBCD1jFXzEDFgSr/UhpFEEx4UOmzOYF8Ewghn/+WWJUKH6hIQ5jf//UHXBYEFvJUc3ppmOQWrIgmBgHJgBg0GA0ByYLQG5i8gsHd6GqcDNmZhoA3mBmBMYYACTB8WuQocFu1NWdOX93jlZnnlCACOCwVMIw5TEAIHm3hylBzJAN/IJ+xnnr9buNVKgAu0tYxwAQaIpmsakrdBkDzAZKTCYBFYYtZNkX/P/+5Jk+of13F9LI9yjcAAADSAAAAEYUYMrD3KN0AAANIAAAAQQ/AF56VbkabE6LmA10YFNw8FAXpGpVnDpdD1QG0gxDZnbqMxnAMDGAk8J9BN2dj4DDw+3881IjQhZgiEpZKJB84OEmzf/kqgR4ObOkRUHED3//1BMOKWBEDKk4QAAnKdyGJrsEIKJgbANmH0B0CgZhCEAYi7jpzNl/HTlU0Yc4SxgIAjkoGRMBCzkMABbswFuDK5fEZXaypaaGWVAAEziJCDDoEhYDiqFxp3TBi8DSEt2JXSV8MO87hbfxujNiUCjCtCjBYCHDlErkCdRksYBhwEaCzixqlyx7///1hUCh4/u/vUG1ILQ6AkvjAgAHLjbuUl/nbz3ixAhKA1OjnGKlqXdj5BQMWHBb6Qp5Ne5MgFUhvP/PM6iVCMEcZgtkiYBCfD3Ukf/yVYX4UjUxGALHTz//+oJiw3wG2g7XL8wABAA52de6QA0B4WBMMKYAEwHQDjALBUMDxP8yQB2jcxTjIhMAqAyPB1UjeQ7B8a3ucmc8cdVZqARkHG2XKYT//uSZPqD9pVgyYPdo3AAAA0gAAABHEmDJQ92kcAAADSAAAAEACFIMD5kXbjoLYFEZqrr///1jATGn9UpMal8OHMPSmYfdSgyOiBoxbw//rCQIHdm5mx8cIGZCgxASZmPxSXnTBQy4EqxCs/1pEaA9iFmS8v1GYGGAm/+3WCRcNDQqMzQGgMUdv/5ZRHyDh9YiAyKv//xEQ4AWthAAN5PqzJupCASYAAChgmAXmAiAwYF4GhhmFHmxoHsbeBKxhVgDGBgAGPAthkXi7lUsh5LKWtSfvVC+BIEzEzgMBBtQYLgY2hCgERlqw9S2sf///eETaPYdMxQVxITxS/jNJumE0+hMabLrKSP9YSCBTE3OrLAuwjZEdmCBbdty0REMdAEAHUv1qKYEE4XvQT/AJBFT/bpBAHBYm2dYcAi7f/zsfwYDrEqGTf//8jQYAELLTAAAADmDprkdMRAjGAaA0YLoIYgACMDMBkxLjMDnuELOd0FYwwgLiUAoDCMwUAERXGdh24U+udunx/V2IMzFBobKpZgYgJOpwHiQ4TKlPJzZFRX8P/7kmTfB/W2X8tD3KNwAAANIAAAARZhfy6Pco3AAAA0gAAABMP/+ZQy3VlxeYw4xgUJnZmpt/FfkUAMiAtXUZpkUv6gQGgeiPblE3KgsYGqBgtjGQJgX5KqrMCfPhhABTyNA+33YrA2CQdSJA+3lkAw+boe9aPcPRBh3ol8EBAWJH/+WWG6DldhXgYHP///TGcBxUOaeIAATPCTupD4iANCAKgcHuHAMiADkwMjxjJEF3NdwkcBCHgYCRg9Raam8hl1vVPOw9/7wrxhI89OKMJD2gEIGdV+mIgK9JfYzw7///7jjVKsJMrBigkhVm5E0OBhMUREcWs9b/cJCAdKbUdUdGsAtGEEjFzVF9E+TwakAULMkf6JSAcUC1o1f5wIQx//9xNgODNoJhg4bH/+dQH2FxspiLv//+LwPqJq6jAAAAC1LWdLFYEYAgFxgkgYmIWCoYKAH5g7BUmJm7kcUpPZ4nxlGMEAgYHIFJgoDAiAJWeHWtM4V4xSSS2N19ctzjnmAQIHKw/iRECwTGBodGHOIAUHkp2ySWgu4c7/9sQ/TrX/+5Jk6QP2Ll/KQ9yjcAAADSAAAAEU9X8xD26N0AAANIAAAARIAJCyOgkBXom6k800yNPMwtCIMAFxoyXkUm+ZhF8D6ZV0CPQIuGXANvQAuQFLkDEYEYnUZkEJYB4kDmihP5o/rUWRIAa8AbHCycT6jEAViRFXvWbqZE+A5MFIZqkslC8JMDiJ9v/x/LgioMS0AzsLSjf//1HQkMDmhYYbkAa22RZL1Ds5AuZPBiJngiYeoaBwFg9mvM0mYIIHIsAWYBABrL3fgtgLU5JSz1JljzvLUVLbGKSCaYCoCwkACYAADZhii5goElYz+y6ly/1qHyIiOcIWA4UACT4ZEvFMgAWvgczOAphOLV/4SQAtibnVmQtIGDsgSMl5EmjJtIqkRDAoATQnUm/TIYAaUCiwroP5kBgBRL/76zgNDQb8jpGANQotqX/8soDdBxKoP6LAv//8NEE7iRm1FIAAAHc3AUDawlsYBQBZg2ANFYA4AAyMIs3M1KRljSHaqMHwDpvi0icbgL0d10K0Wzr8w/mVmNBQBm4k8YGD6xkfjgROKC8s//uSZPEH9wFfyUPdo3AAAA0gAAABFzF/LQz6idAAADSAAAAE2Bp2/zv///nEHwnmEGHzUJBiX4aoVZDASoLLtOltpF/6ggLAtPbrTMBywMU3AkfJwuEPM20CuWw7gAxkqJ/0iZASNBYyVm+gDZs9/vzgQliII6aAQAxp//51hdg4NUOkOY3//4kQk4oJyAPts1We8pgCgCgoHww4ACTA1AiMCkH4wRmfzHqIMNGCxswVQMwEA0TDIeEAQGguAVA3gZ5FX6q1reOVWVNxBoqNd0sgGjOwQGDqtmMlA5M95J+xbw1//3F9mFNdQxMerUHDlypTMRtTxnkWmQQYumNUqSP8pAgbAp+fSKJsTIdEBmMwDD4qnBySiktR02IkDewAWsWI1SbqWcHSDWmIKmS1eXgDkg9t/P9wQpgWIJ1FlEZEKBjz//lk1DvhRGzkMBQief//41gWLhYqpRQAAAhvKAVpSlJwCCjkIzJkDQtDCmJ5NWwTIwgWogABEW5DgQmLJjSF95VGZLMX7Ov3q7BhVATMB8MItmx0gANMD4UMKgBuxP/7kmTjB/WKX8uj3KNwAAANIAAAARmJfykPco3QAAA0gAAABK7m9b+ojxWTg7wNQfBEnJZI6TAcWBlvILKDU+3/OA0OAsqPajqjMdAALoCwgnzMmEH0yoVQ/4Ng5ND+gbgOKgsLNE/ogsCKr/36IX6BgB9FMLUDaX//OsKeFxmWLwW3//+Xw4IT+l9JH4AWDHQHDADAwMGMFsCADGByAyYsRkB2rDsmQjoeYD4KpgBADA0ADA4CEDldjQANPl81KopyV2bk3EG5gQKDU5YzCYAwwEjAkMDOacDEsHEkWQQzTY6/vO8vyaUsGFQEEB6CEAnxmtzIqARjMdxgICaGzuy41SR/H0EagEx5I3YzWTwhUDT3QRbSFKYtRHIqWcMSdDLoBZQSU2Z+zmpWAxQ4HZiEPt7gZoOVv6lLugITAtELbJkwT4ISwe4n//JUqBICDmbHQgADLpf//QDHwLCgtMWqIAAQAMsIfdyH0UQcB8YQ4AIkAyVQQTBEQwMyAV8zaHZjBfAIQnl/XWUHbDGJPRyCzTUneZ4ZuAFQWcRPRg0KI0j/+5Jk4wP1c1/MI16icAAADSAAAAEauX8mD3aNwAAANIAAAAQoAm81iHH1azsz1nv///rcGMajLLTGoZJhzA1LclamBk0bDRWma2/+kECgKO/WmYDPgGUQvuRQuE+m2xXIkGiAgBkUX+pZHAUVBcoxV8wABCHn/+wYTBgp84kNIQ1//500FPBgWsZ4Oe///4dcZIUOxgGWLrNdcoYAIMCEBEwtwKjA4AlMD4HcwrVOjVHJlNjGF0wrANTApASAw1BwOX+3R1Iaf2pF8+Zfy2+jrpMHjAKYGE7+BgDOlNEyqBVIvNRX+Z7//zwht64FUXMQJ0HB+MZ14AHQGQOMwkAnFi1lJn/WEMAFp3cxPmo4gM4WB1IeDAapRUtR0wSGGFNxJnn+ozHQAl0BIgX0E+pYAhU3+9TamCZcFiKtIoAmLFtNv/5ZNAyUGDaJuCw4///+GcilAxs1MABAALl2DGyvgMUhdU1dgQadxJhxifG/2ACbFDIRg1gWDID4iAAV8203OSeLS+mtY/vtmGoiXOMTcH8KgDSogAaMJ0ZgwEgClzvx//uSZN+H9Ytfy8Pco3QAAA0gAAABGEl/Kw9yjcAAADSAAAAEXwzw+kQ0U0ZoPSA1nIA5EOEvHS4N8DpTANAFEfEVLyKX9YQOgon6jpkUxTAnmDFBTNyoz7lQiINAIEARZSX9nLgX2CjEts/kYBUgl9tugEJkTirMy4DQOLer/+dPCKhQdUKaHBP//9Qf0QwPqWtV5Q7aaBgAgUGB0BuYaALRgKgFmBkDIYqrHJ1IkBHk7AaDjDTBPAoMMgYStAAFMcZzRym5NPs709PVZVGVbjAIPTYRjBgAAcEpgMIJlPdphwG6izKYlM1t95+8K6+CwAFOsQxxJ4aJBodmIMrBgIGN6JExhSK91v+CXQHYz+xmxXFKAKkgelFjIeJYPpalmBFzMUoAy5FsPs+pJEyFpAwNcBiaRJHrUWADWKavfPajMIIocupaiPRD6g4sef/8lSoEIUKOpwJgxnl///SErBZSCxZFQAAHO0UniohAZBwHAGEpMCMAgwHQYDAgRzMDoa42zCCjCFAUMCIA8FAQQIL3b13oMpJ/CczuW8qs09JVEP/7kmTkg/XGX8tDPqJwAAANIAAAARphfyQPdo3AAAA0gAAABDM+kQB7TjAQQ9r0BTstWHqW1j////y1En5WBAMCXxjWPbiBZj8uIQRksuspI/1BJgFCT66ZYFNAXqiApxisk2xbJ4NSAGFk8j+tRKhJWIBmC/lIBAg5/tzoQDQ0tDWZhagW5H/+dNBEwoHdQtIfRv//y4GYEoImAY5NZUqiIycMICOcbMeINC0MJAp81Pg/jXpCGBQWAkACXcTnWw9DDovK8MMqmeW7k3BAjAPMGEMgLgGW0RTDfA0KAhGzya/zvPWolRWSaHEBKwDC5Imx0uCE4HCEgFRSLGKX/OBFQGafsmgRcDEDQWTk4YEed6zQ8MeA0qK7f0C+A4GDi5o/0QBQJr//DHQcHbQTDOic//zrCIhcbNQ8zf//i8D3RruqIAAAAN3GFo6LLIAGQCBcYHoKo6A4NBBmKERwdBAh50cIjjQ45gYADBADpEBqBgKy0a5aeAI1PyKvS/hTwwnuFAkdehoACK7QuHzjXfMrhFYkP0lPhnn//zOMQA6yLxj/+5Bk3Yf1m1/Lq9ujdAAADSAAAAEU+X8xDXqJ0AAANIAAAARtnAIKQ3qkdMYBBhN+AYtsmitrHvP///8iUuJR9/8qtNMqLGCEAEBaU5QzS9/8pCOEEAMDSCBkTZF/SRHUBglwKQiRf2SAyQAkv619IbwUds6yw4nYLydv/yyVQkBBhFkxTAcBPf//WEgAbyF/jdDPj/u464AA0AQNxhogFmBIAGYAANphLMPGrIRScd7iBhiAVmBmAUMAIkcwuWLAO9P4XKCvjev2Je6oBAM21HJIcvEFQwMApKFAcXzAUzW3r+/+qrxJ3NdQEmJ5BhgwtOlta+sKY0lCYRgolbD1KbIpflkJXA0I/01E2I4Azc4BqoMmTYxhQTUmYETJIEAIDWCyIJt61HRuA1oCmHVL8xBEnGw/609EyAoMBZ0auxkgBUWHZSb/8slUJAwoWnQ4QslD//6wkCJcL6n6EAAABGWMWa7FhgTBROcOJGOB5jCWYO6ChndjimpguqYOoGJgIgLFk2UQfALw8lUuu/hl3mVmLoamJQBkAADkeTACAPP/+5Jk7gf2al/KQ9ykdAAADSAAAAEZSX8or3aN0AAANIAAAAQL8SkDAqsuh2mxy/1oEPF2aC1gaC6BZORBzMgAN5wNtnAamnF/+wJNief1mRAQMHDBERNlk0ZNrNieD9gGG5EkX/TKAESwLGDdD6YDQW39+kEA4LjI6Z4JAyfV//OmobsKA6xWBP///8P8JOJOViQAArXYKZ6qkW0MAcCswNQVDAOApMFIC8xOSCjoRApNq2iwwuAUDArABHhAAgWsE0BpEnm4Ym5dSzVutSw0ykGh47q+TAonRuCAceCIA84koXukNHez3//zKGWesuEYEMUMQFCp3ZdYiafxix+AkCqXPzLjVJvzgFbxEH1oF8mBCcDKawFG4zBMDllNB0EyIDtCYkDNiiLoL+yRMgYEaFKJJM/rAxoghH/n9agmqDpkaimYhq0HAzz//lkqBIKFCVhfA4mf//+sSIFhwWwQIAAAAPzfRc8MBUAkwEABzBWAaRTMAwB4wnS/TXLDMMoB3EwDAAwAAiQBLoMwZPOOJFonZqa3axrUL1DAicJwAgCe//uSZOED9ZBfy6N+onAAAA0gAAABGcF/KQ9yjcAAADSAAAAEYGAx6f0Dmxt5Zbwzw///W4IU6qwIZ2GFYxB9nVO0wFTYCUnFpsUv9YRaCweySI5QGMXAiRFpRGmL6kS6KRAagEi7fWojQTVhvpkv5ZAIDv/v1BCUFsR0SmF+BYkf/508HdC47qIeHaf//8zC7xT1Y2qKTtAa8NA4AoiEwSwJDA1C8BrzZhZnAGKfmgOA0AYA8HAQPIgMai9cHNHoa0qmaLO5NwAtskDYwiaMMCYLAKVAvMcKLMLQXVUg2gu3M+87ztiL12SjgEmAB8lu4KsxtpAXBMwyRUMHBksWs5c7////gQDQRAZz/19aJqKGB5LAoLH/jbsUlvmeELGSBqOAwhMih1X1mA6wMBVAszJxNBCpZGAGpCQX7VH+YA1RAskTQTMCBgmaFgX//LJLBMeFD7qDOw95f//0AvWChIMRNTAAEADHKUulDIVBGQGHiSmTKGrZGFQZya1AaxjGvimASASqRqTF2dx2YgOTYzncM/3hTvoIQEzCxDMFADUZhP/7kmTgB/WJX8vD26N0AAANIAAAARnxfyYPdpHAAAA0gAAABCAsYRwrhgHgCLpjVLlj/rUPkS0iwhYDaMgRKh2mzIjHAbj0BhAInYnTZFL+cCbIOAX1TYioGLLgsxK5mRxl1qLxFgRQySZ/2Ng8wURlp286DUea//oBjwUIc44s4QI//86eDXhcfFNFgb//8REUYQaes1qF6FE1GDAJA2MCEGUwBwJDBdAOMYIdg7xASjZIxQMMcF4wJgI0XAwBBIt3Yw/LnSulq475hbljXzAAQPoOMAD4RgMwEFz2cHM2BEaBTNYGnb/Nb/8K7oKNQpDoZDZAKKD98lDWy3BoNGGWwI4tbev////+sOmgSIH/+6lPHE/woowMA38pIvbvd52EDIhIaEzBMnFq6KRiLUAtMAsyJ1L1k0BgEhl9qlbsJ3CkU+0pFABcaGgpN/+WSIBMeDCLuJtBgg9//6zgSCkQBwMtKhQAAAhlxr7DIfHADAcA0Bg5wcAyIgPTBIOGM5YZ00G1kTA6BLEYAjInnZLalMFQLFsJ6lud7y/OJfiYCMH/+5Jk3oP1gF/Lw16icAAADSAAAAEZ5X8mD3KRwAAANIAAAAQhd/F3mylCRFdtJ+x3DP///xlT1Q6tEwqWxYEy6znMKzhdGhAAdWXYpN/OhNMFBPqc8TwDRAKHyoYEqd6k1kUBRySzt+slAQoBOCavlkA0C3+3RDB4MAPpmARAkT//zp4MlDKtKAeBv//qFZE+CyDVAFazLm1fMwAALzA5ABMNUBwwOgIzAwCLMJdkI08yCThygwMMMB8KAMI6wM60OMlopbe5clmNrG1LWtAAETa4rjCQAh4BiQJjLeJDDABk04Am6meHP/W6jd0C6jTzFoVQgc3Mo9yxjxjwIBh8Cauodpscuf///zJVFIeEjn/rVaSqPDhHLKlduixv87yDxkgTDAYkaQ5FJfsmVAASgOmEmaJ+dAxwQhW/tqMQQpQREUlqKZ4LXQuO3/8sk6ERYUJssNEDmof//h1QUEiWtRAAAARljBSwLxFQAIKgMmBiBoYBwC5gcAXmGCOEbU4WptSnpgYVUeBrKBoiswxlLexT5/Ozhh3LGtERUFGz1+YP//uSZN2D9WZfzCPco3AAAA0gAAABGZ1/KK92kdAAADSAAAAEAiSIoFTKt7Luq3Rmmx1////2zVfpYIRIZIaZysQ2iAYjRQ8Qp691v+DRcFEjdKbkEAyYYFGBEzMfBzrNGGPAlCK7P+kXQFyoLETZvnQUHmn+3OhMmQFWdOhiwUZv/501DXhdesVgg6v//zwZgQstAFTcofdrAhA7MBQBEwcgLgwAswFANDDROvOAcXQ4kijDC/AHMBoBEIFAcB1/sTYer6OxafuRCzljcoXwKgbM0S4wAKUJQqEjl0sMZgIvi/UVtWe///q6+Cf0MqlMnhsiLrnTtugXiZBXZgUDJqw9SpIv9agQvgpENallgzKQpoAvMBgKZMTyTOyRIjhBABAyQQiqSP1nB9hDDG6YLV50Cyk+39uUQaow8aGgXwmMHYj//OloIhQcCrFDAsD///cUwHAQ41MUAAAAYZvIt9+BCAsJAciQlAGA6BoJxgLo7mI2Lwbc4WQCEQDgUzCgQvu9KwjX4frTm5+znzW6kFigYbFvhQiYOtQ/tkImFKKDqP/7kmTfg/V+X8uj3KNwAAANIAAAARipfyqvco3QAAA0gAAABO93D///wlcFxVR8xB3DAuUbzjDLzTisHJMaxy/6ANUQOa+YJmg54GQRgorIgXCHmfQL5uIwAUYlx/6BDwFiYKGzRNvQAOFFp/7eDQSCwds44hMIs//86aBeIafmYXXf//6xKhYRFy2hjalLtMBBoD5gUAPGFYCWYHYFhgthBGJEo+b9g/B0IJphBE5gzATkRXEhKrSr59G5yJ2X9kVFW/OpK3AC4fOnwwxeISIChcLm/PqJGNHx/5RXwzz//3k8KqLXkMjISWCCs4s9LH3GAUAX8YdAa1oraRSb8jgawgpo6RgXiiGpAZL0AcyJ1IgJdSZRiVhxAVBAbMKMkapN6SJPAYQoCk4kT7eUwMUXdXvWj3BADBz9nmRQAqHDmmzf/lkkAmNCg9NQf8NCT//+sJAEQvofMAAEAMa0Fs8gsUsC6hg6gkwFvGG4Gsb/ACxtaq9GFsAAPADoNOqhfDi0MHYdTV6k/uGcsh9CQYpgL48BqLABBUBYwJBsi1zAYlP/+5Jk5Af1iV/Lo9ujcAAADSAAAAEZnX8or3KN0AAANIAAAAQ1t69SY6BLDcWYBuagEngt5pPiEoHRvgZ0MJ1IsXUkf6gTVAxYvnFF8VwDIwgJMCDl8hhg+mVC0H/AyIAd6H6jo+gSbCARir5gAkYXPtWvuJsBQ8zsmXAkHImr/+dJwJgw3qoRMjEf//rDvB9xGZs3cH/WEZWIgETAnASMMsCUIBJIQaTC2XUNn4ns3+o0TCtB/MEICARBMOFCgJe+ZhuAZBLrsZ3jleo4OQiPgjExaJggEmChKc31YOQqPziw9S5c///vJc8TLRQBmEWmAgC06dl7sCMDmYF2UIi9b5/zoIWwLhXqWUll4P1AzN0BqaVjo5RSRUs4XSIhi0AbYPJsi/qTHQATCAskJ9BNepMECM63vW/MgSKAwmzoFM8GEQoDZ//zpEAiLBwu4iIaQa///REiBwYNmPogAAAA7jAzyxouABgQzCLAMMBoA8wHgSzBZRGMsMW00FXBDByAYAwAVlKt1Xfr0WdFd7Od/HKzGgsATfSSMBCFayTYeBB4//uSZOQL9c1gS0M+onAAAA0gAAABGQF/KA9yjcAAADSAAAAE1qthU7f53//96g1jMqd4WNhMOpNfsTaTxh5NDgBadLbSL/1hIoDpj84mYDPgYCSA0PIoXCbTbQK5PBgwGyTi/7l0MZhRAW2fywCAYl/v0gaDg53OrDCAqTf/1lQJgxNWlUMo3//6guOHqoGAVpS6S8W5DIDoFAnMGcFQwMAKTBQBZMT0xw52xszNEszMCUHcwEgPjAQPBICo1z3olZrZSy5zHKrKm4iMVG56CMixWsUBhzvSGMAUiO/EvsZ4Yf/8zjEAOsSgIwmzgEFIbysP+kQaBBRksCNdlVVJH+ZgmqCpl7OUDYuiygNA8BFmJYwGdKKS1HTInhHQCoMW41dukiZDkgPjgWSl5H1IAYEyVfvn3rOBAwGMRUtAvhIoTC//50lggHhcZlh/AWCq//+gKHCg4FAaVSAAEADW4AYHACdoAAPMEwCRLswCAEjCpKZNksUww1XogABcYAoDK0gaA2kO6479yiU0lPj3LdaheosBcEuIt+6oWC5hi9jADf/7kmTiB/WFX8vD3KN0AAANIAAAARlZfykPco3AAAA0gAAABNChub1v///3HmjQ6uUxWSRYcwNRU8MI7mClGGCB+bWL/5iEhgKXTfnFFMZwAmoBIARc3JxB9yoREOGBUAXVfrUZgktD3y4n8pABAD/+/UCZIOwuswcP2E0f/+sqhMGIvWJUaq//+oRMRsJQa9fijbtoEALBATICIEMD0BAGhFGB67aZcZKxnD6SmCEBaJAXsqLZtJWFYSzeH9xfVWxu5NwAssUCw0oXkwgBsHA8YGhUaVRsYvgUkK5UZpsf//1nUbmn/JkGzFAsQcM7TKfVKj0Y9GAYWAuhs7suLqSP6AIUgKzCTqRI5isKVA2ZUHgRpk2KwRy1LOGZMiyQVSion2f3NCJgYYeBbWSBug3RAz4EhH/U/NAIoAc0N0Flg4BUOGZNm//OjyEBcKC50N0FraX//1BESQoXTQUVAAAAbydlhzWVFzDBjyHTMjjUxDCIMtNF4W4zVGKjBJAeSNEQAyCq8KVxqtyRxnt7/3hTwwIwATDnB6MAEBBaqOJhugv/+5Jk4w/1nF/Lw9yjdAAADSAAAAEZoX8mD3aNwAAANIAAAATlYGDNoras9/7l0fJBhCIDGZAsWJ02NCLhyAGxnAWdIq/9QQAgdMfnFnB9hGWKHMED7tsWyeDrA3nOL/olICBAFhRq/0wYCLf/6ArYGBn3QDPzv/+stBeIq3WRwh7///UIiLYKSZC7WfFhC+xUEIcAsAoMINAcBQTxiyBXHfcFOb+daZg4AegoAgUBceBpWFGxnMNOIx5qzW7Of8txRtxYEDggSTCANZeYChKbOLuYvgihY38gn7Gef/vVdohYACOq4MbwsKxEYvFI2+gyBZgulJgUCCVr9S02Rf84BUkDMRpuRh8qC3gbAKFQ4yBMCnkqpajMuFASmA2SFvPO3Wo6LwE8AjgpoJ+TAGfCEg/6kNzoIQoMUFZFRTNAIBQcHZ//zo8BEuFAToCJgoSN2//9w14UMgsFKroQAAAEb5DbXH3CgApgLgEGDmAuTAImAKBWYRR3RpXCnmvsqsYPYBxgEALaWanVSOY98ultSmt/j29aipfI4yVxUBP8WAoZ//uSZOGH9VJfzCNeonAAAA0gAAABGk2BJq92jdAAADSAAAAEbtgAAztzFfW9f///LecOrJFESrfNY9nGvmTAcBiS71Lkj/qEUB11ucUdF0BSoF1R1y6i+5aJEMWgYQEYpf0yYAXGAoYN2+mAABJ//bmIJiwoJSzqw4gSZH/+sqBMCKuoU8iX//81DSQ+zkAZXpE8r9CACAwKQAzDHAaMDYB0wNgfTBxW0MtMnc4d0ozDEBRMDkAxn7l0DQl4v9E36lPyCmtY00pcICCE4k9kXi1oEGJp3rmLAmwqGZVVy///93HpVRf5dRkghCxab2Ryx2xQAGLWMEFOBp3rP/UHcB5DykgXxlAMuqAtMHGTYzhYTUswJ8+IQAFWR4Tb7JEyAaTBRqVm+UAAShMP7Z7UYg1QhpqtAvg0HE4v/+sqBEaHjqDvifG///FCBQSF1CNAAAVMYKbi6QoCSYBoDpg4glGBIBKYIgJpiWm4HN2KWc3hZgsMUIAKAgAsSL4smWJCX3kvKa5hnWmY8z0dFBoOxjArbAYHBR3aYGaQAX5daK2rPf/7kmTiB/V/X8uj3KNwAAANIAAAARghfysPco3AAAA0gAAABP//wrvoxiRI6GMVUCho79JdmhQAmV2SYPCidMPS02RS/jOAu0TqWShiUg1EDG+QGFJeRIEZNokkO4GoQDShRxGqTdSzIWkEM0MYnF+opgkdM1e+e1HQkxFnoVlAvgVBBoB//+dJYJEwuPTHyFArf//TCQALkiMzb84g+7cB0gwlT+qHQzcMMMkk82Zw0jcTEQMKICYSBKMBAAZJKJtcdd0JDL6s5S4Wt3Jt6BkBcwTw6CUAyFoGGH6EAHBIKcya/e7h9EmhfEFEcgZ3WBIiQY1NyKBl8DiQQGKpPIq/6Is8KaPLCZgOWBjG4EkZEC4Q8zbTJwqh7YByon0P6BTAWQgiBmif1AgHJf7dYSJhvbZyGQxAr//1loIQYqVZFA8zf//WIkO0UkfVIABAAN37DzvIAQNxYHUaG8MDEAwwGwgDAdZtM3El45tlJTD3AaEgIUNVnKaPY4zxtKlr1T9in7hTwwtMEA8agJGSAOniCQjM6oDMQwRXJK5RXwz7//v/+5Jk6I/2VF/KK9yjdAAADSAAAAEV+X8uDPqJ0AAANIAAAASo3dP2owcxUFESG9vIvGHTJAEBCDGDICqxQ7TGqTfrDOwewQ1FAyJkP2AzWQBSESJwckopaROkFAgDA3AIgpsi/uxWAKABSsWnbyyBgTJ771o9MBxUFmZo7JmgQlSZV//WSwQEw8TLDcB7qH//1hnAg8LKTYUAAAEVcmutapR0oAiB6CJlxhoXBg0GlmhIK0ak6HRgvAaCgCIIAAbq2jNHajkop5u1Xr87hbiiVZh6gnI9sCGQDjAwFMLdPrA1XLf/c8YkGEiAW3CREykxuLhA4K0AZMLhLyKX+sRMGKG5xAzHIAwboEQgn0yYQfQK5WEQAGAmC/1LKQFDgbEj/BsIf//SIKFAzZmwjEVNv/6y0EIEbTLF8T///8Xwh4qbqqs1deBRMKgFggEYwAAfzAFA4MG8BIxxAuz1gBdOnS9ExKQLTBGAuJh/FgEBQp0D+uVyUv3FYxW+zPRVgwcCJygLhgYIBcEwWEE23gkxyBsHBMxx+pba5ret6oWNFUBn//uSZOoD9lJfykPdo3AAAA0gAAABFT1/MI16icAAADSAAAAEJUtMjQ9BxSrieR31yAkHzGpJRoxIFo7zt/RCJ0Cek3UpEfRqRYPRA2+UBsCN8pieiHI1HS8OcA8AA2zEmKqTdajMUIALgAYGEXME16iiBoRI8v+tNVEmgKEAWtFp1EqdAWEAsONX//OjYBJCFAx46H7A4ufb//2IsBZcA0AcUAAAEb1F1bIbCwBQGAiMF0A8mABBoD5g8GLGj0HeZpLGw8EwJABKLorL4Z27Eak78RyhkWt5Y1oZEIEe29gkRfBNY+AHGnZVs/ev87///4SuSzrPTCmsOA5RXuXWNGOPhdVxpbaRf+oJAQWmPzizAWsBEMLey4gX023KhVDJwsSM1f3NAxUDih9vpg4If/35wGgQLro7Jhnhe//1loLxHfWmHaf//8lQ3sV+MAAAANckTUXzFAAQgEcwyQDjA2AZMCAH8wUV1DJLKRMxqbMwGQYwaAEYdCYsA0JbQk1GTvbDNytr7VW5HW7CgfNuRgwYDFLgQDDgeGMjAJY8OU+GeP/7kmTug/bmX8kD3aNwAAANIAAAARVhfTCPbo3AAAA0gAAABHP/95QCo64yCYx8eAwpOrIpY/5ewzaMDHoEZLTYpf8EJsKhW5Qc1IMBoDQKTiQMBqlFVZw6ajRBTYPJ9n6kUh0gArwUSmzfYBhMaP/fWUgigD3lqWUDcG9g7D//1ksEx5C1CIhsS///qDrhsQZePEgVqsqbqwowQ8zqc/840iE40UxGz0DlJD1MSm5gwRAEjAfANAQMEaQzeZy40/8WjcmpLO7lDHGjigFQjFlBQExdkcAtMAwkkwDwF1goBmrut+gZjOBkhPhkQDKp+AOLAyZBCLjGAmAQMFQMBQiB0pEjVJF/yyEItBydbUcMCPDJAHowLDCBl8iCB9nYexpBIGARCZNLV9ZwX4FCqITlxNXjrAwgDSJt/P6ywEAsE6LUssHAsvC7TZv/1jwEwqMJag4ZFF///UEQCMILKSWeMAAAAPxlDM26KDmAUAuYGwGxAAKCgRDDpIpN40Ewy74rTBeAbBIBTgDgEYLVe5y6efqxvOT/vCVugIQuateA4GT/+5Jk6Yf2H1/Kw9yjcAAADSAAAAEZvYEpDXqpwAAANIAAAAS9wJDRsqzGHwMpq80ttY////8l0BO6oaYHTJcWJUtqiSqMqGgw8CV1RmmRS/ohJGC2XzI8bkQBEuB0QiZmPgsc6YLHeDrRCnn/QTAQVBErKibdZqACKS/35wGpQNAT3NAhEl1X/+VAiJLbKFZDsP//9QeUaAcEeFAA7nBzB4oMhRY6G9AEmMG6MDc8kygRpjNEYcMEMEQsyhKSnR+ZK61ydor3bOv5nYjZeQw2geQQAszMu6YcIHYYCax6EWr3efUSoppeImDrAUZkIVy4QMOgA1+IFoybf+cBoRBh7zizg+QIyxCpxjZ23LROh1QbILqX9EmgFggOLGr/WBAKV/9+wakDgD51g1EVNv/8tBICW2WYCGf//xdh7gjw1kAABepoq5TkmAKBoYHwChhzAcmBqBcYI4Pxh2NJm7gQ8cK9ZIGFNMB8AwDBKQgAwp5Y4y92qeNQ7Tzn5XqN1EojgUQjDkR1IGAYImyTQgY2y/DlxSX2M8//8LcOQA2xCAhg//uSZN+H9b5fy0Pco3AAAA0gAAABFKF/MI16icAAADSAAAAEqdQCABw45NvQQAeYVpOMAkla70tNkUv4BsMC50/uUEycEpgaxiBbuKUIAKHJVVZgT5sHsAFjRoG7Psio6KcEsAXDFlS7VkoEVB9ftUpdzwrYHRS2yiyUQskBwI1f/9Y8hE2Pc6H4A4Kh//9xSILGQwmeMAATdyhep6UOJIsZmZiqHisYcQaptwBBGxkoIYVYCg0CaGAXJyqTaO+EtmuUF2h3rHKzGmumI0CkBgIEWiQA4wQRfAIAE+Mxd1vX1kcKcQUQqBr44IlI7i0bk4J3AucAUmjNF1JH/RBojBh5+pRiOoAigFjxdcuovolsiQf4AouXkf6ZDAHmgUKG6HqWAkW/+h1hasKDD7WTCAETy//8tBEKW6xFC6h//+UAoAEdLiAAAAD6jppeOGIAQDAhASMKkC0MAxMAUE8w5lFDgcJDOYFR8wrAIU1HfAQBAIB0woBkzxUlLSXbtnKllTSQuCxq2g5g2EQGBkEBOZlwyYSAWrc5Mapcv/n/nUdNRv/7kmTwA/agX8mr3aN0AAANIAAAARXZfy8M+onAAAA0gAAABOTJ7mIhKhwnuJG4YcMQAUYVngBhfbadtIv/LAThgtxP8yNC+K0AzMgCVgZsmxjCgnUZk4VQxeBswQ70H+yROAYMGDqpbZ/MgMYYHc3tU3I0IowUImzJlA+BUMG8P//kIESpEnWHWC0tL//6YYMBwELqTcwABNcn4OkYWAbKANw4SYwHABTAQBRMBlHAxExrTbaG2MIUCMmAEtKsbmyuNyOXxi3jXy5jq7BQwJmvbQEH1TFrj8J4HLSQMDTtrnf///KUvS/ShxijwJA0ZpsaZpJm7iYWCNNl1lJH+4QpwcxfnETIWkDBxQGhpWWTRk2o1J0QhAOWE6k31qKIJqwt5SX9EAoOWv9uYg1KjIpZxQhOIFf//LQQBWy8GnP//+IkNEO0WzAAAADKZbktFeQWAmMCEDUwqQYDA8A7MHQIMxY02DohHxO+st4xMADTBlAcMDABYBAdIqpQssZZD8SpOQdXvYXY40cgGRojCmDiMoeJAg9XIjLgCTPbyRzlvDX/+5Jk7YP2el/KQ92jdAAADSAAAAEWGX8vD26NwAAANIAAAAS/3quzwqgChWIZrHgkeGLwJD7WAqAzQihBSpjV3W/////+ZJCyPGm1/7mLsoS3MNIEMLbuRh05vn7qQOPQSEAaYeRBNX1mAr4FK4FkZFE0PSAagW/nmdQ/g0cha2pbJEUBCdFypf/48hI2YuwfmFBxu3//rCAII3Cxw+h3GYibwCMDEwAAEzAuAwJAASYEAw1R6TfbCaNypBEDBpkoDhgMC1nHpXejsts00mu3ubwrwAIQqbvZxg8Go0CobNNZEwSAWWRupnhn3//+T99+VklhOqLxyhmI+VAIYCXxgEBsmltpFL/CTkKMD/QUXSBAZB4CJkWjg6TFKpZsTwfsApLGki/3Y3C5kFGZadvQBESLX+3MwQEQcLQqMy4CQERv//yqERZ11CIi4k///w/wbGIDm1UQAAAEY7fhl7+CoBACAxMIoAYHAVCME4wWUOzNDHCNglOgwmgJgUCGmIrKyBsjX5BDVPLM//+Z0jtoYHGDWGClA4EhYyNdjBIAdGJV//uSZOyH9qtfycPcpHAAAA0gAAABFtl/LK9yjcAAADSAAAAEct///+9QSxmNM6MaC4iGUC0diXvIZNDYCJTu02KX/CbEKIX6kDMWgAmgBIIRcvkwg+mVCqGtACBF9X9EmgHIAUFIv9IA4KT/+3WGDQYJbOrEKCHN//loJhTSoVkT4v//8vBoQzzsAABVh6HWtM5MAMBkwQAGjDuA/MEUDYwTwmDDwbjNqglQ4vKtx4YYwPACzAkGEjRoCxIA1Nl+xNy4akdv+dvT7XQ4BjhMBTDcNgECpgMEZsC0JjQAYYATLYeltrn7/eFd0FHHmQ8MPTOMKgAZfDENsoEIGmIiDhA+PLPWXb+sIdIUin9EyKpWFKgbVqC3kbZTFOI5FSzhRIqLCAqkFtNmdtajo+AgwA2cKaCfnAMeaMH9q17JCwA6GeeiTYQFhxIq//jwEi5cPOK6DjLP//8Z8KJgFAJUIAAAAMcoJY1Bo4AkVAEDAeAtMAsBAwMQHjDIE7NvINAzjXAjAEAkR5aYn7DC+MYNrTF6p3/x7Zny9pwY8AAOu0gucP/7kmTlA/WLX8uj3KNwAAANIAAAARq1fycPdo3AAAA0gAAABAH48a1wwfRX+d///8ZU3aHVbTEJpDAzD1LlVZEYsQAMAbLpbaRS/wmzBwxDqWUBrgQriFyYNCum2xbIkGdBADLC/6ZMAGiAogK7P5mAgOW/9+4W0BYU2YOFqhgP//loJg0WWPweH//9Qp4bUIeyF2pG3AXOzAwHwKDC9BFBQGhgNgomJUrwc0RNJoBZgmDKEqYCgIgjApbBgOCIkAaKjUpHL6CGpidxtUsNKUiEIjTVWxAGCnwAExpfDxiAByA93I3SZ4Yf+t1GfoEZQscxgGkWIdmj9w41stgZEjcYsgM4tNikv9UJ6QREUN0HLQnYBjIC4MWwmBTyNUtR0wKQsYPPDFLTs+kiXiqACzBaqRI1frQAqoMF+1ZvonAIKgYNRUssFILfwoFNm//UPAQnR4nQ0QPdV//9QQhQ9YCQAkXVIAAAAO8gdqMLRYIgWwgVIwHgBTAWBVMA1QgwORtTA2jsIgQgSAMIAPNJXs1rw9GYhL4R25lutMvEMCMwdED/+5Jk4If1hV/Lw9yjdAAADSAAAAEaNYEmr3aNwAAANIAAAARIDpIiILmD92YGArYo7Wu63///9nZS/SOxgBPJbRGgm4AIQCSsEFBhksuspN/WDSCI1P9aBZEUBBmEqLJuWmfcliIg0AgICFlJf1nDoQuxSJxfqMQHkTH776ywEjgzS9y4EIcgqX/+VAiLJZ1iKDTV//9QZKSwhOwzAAAIyxa0nKwKCwSDOKaMcLNIpMIcmA0cxCzH/W/MCoB0wDwCi1LB5qavQu9Sa7Sb3rdSJjgBhgwBTgYAVewNACMJAOIHAfOLLrOXP+slBfF0kQAo4LJSSPHzQiQGyVADGRxF1JH/WE0pOfZyKABBgYOK5mRhzqTTIABZKVH/oF8CA0M2aP9ILAG3+/OBEQNjrQD+jb//54NaSGRwh7///i7EaCzlMAAAAMrrdFtuAOAViACUwOASiwAWYEwCBibkVnQ+J0aslNRgwg3GAEAuFQwYXBKszLUF5Sy6epnenqbudJDbAACEzvL8MJiJPkWDp40jlDlUk8sinb/Nf/54Q28cCovm//uSZN4D9a9fy0Pco3QAAA0gAAABFLV9Mo16icAAADSAAAAEIGCBge+kThhwwsCjK7KIkFJ73W/zoJl8qHnrSLpSDygYFRINzSkxFi82iSQ4gQgoDDYHHEil90S8BgIDAwSlp28xAwaCR5f9SXJQEw0CIOG7SysToFxmf/9RLBMJiY2HLBYJH2//9xXQcEAtieIA/NtFA2cGACAgYHABJhnANBAIRADAYT7CJrFkGG9zKSYVgC48CO3ycyYSuHf46c3FYd3TX8LcsccwEAD5BdMAB3MwOEzpGHMuhtXjzyy3hnvX/us8KdrXhCADJCSCCk4sapY8QAUyC7RQIKWv1LTZF/yPBO6KOadllwP3A0kMCV8ZAmBnyygtRmThaC9YAWod6D+tRiL4CkYBoUYq9jIA5Qb/1JdAEwAKOHZ0S+CRAUsj//USARJiaVB3w2pP//8mAWMgiBFdIAAQAMcoy5UZGQ5jgB9iJnSBo4xg1HVmY0MAasiHxgygXGA0ASiUgBa8zeAph77fbd3n95akKdRh8gZsSZ0QAJGBWKUOACZzF//7kGTvB/ZsX8pD3KtwAAANIAAAARjpfykPco3QAAA0gAAABHW/+mRgujcdAGlfAWOETLhfIoITgboSAxBIsYpL/zEJKxhN1qMR1ACOARBkVEyi+o8VQ/EAowRFL+swBCaC5CaH2BwJX/7DlhQS+g4boaD//1HgvEhKhTyCf//xaBFhOGNZmKhzYxGCMYAAEhggAomAiBMYJoEBidEanSIFQcr6foKF9MCUA5X6JCG7sKNuTGeu7Hvr5Y00Za0FBCdagRUByAEwAKTdP1MhBNVzkxqly/+f/cY08TTREBzDrNAQddKOxx4xgDGC3sBiu06K2kX/wa2wUFntRmXCbFmAZm0ApEGbIuOQUE0EzAiZEgQAgNQPHYm32ctBZoKTSXPP1OBkgJJt+ptIxBMqDlCmWWDIR+FAJ9v/1EsESoqmcUKCwBv//rCIIPVDG5WZQAAH1Im/i0wYBKYFIGRhTgqmAQAYYEYHJibKLHPUPCeARPAKJbAQSgOTcGjQTriIBWXoY47luMY0taZgpRUdGhtfAkotRSMHgw9s7giXJAs2iv/7kmTjC/VJX0xDXqJ0AAANIAAAARlVgSgPco3QAAA0gAAABM9e7vX63caOVAHEmhAZylCKU9J6KRImmg1eYvDCA13paXkUvqWE9YORbopmpNB6IGh2gNXR6OjHFJGoxKw4gIgAOGDGSNUmfSRMiGgAywLLSeR+gBkyRon7VHtIxBNaCIahpEwBUuINSR//UQgTLh5qZoCx08///rCQYvBsxJmAARlyRt7IgoBALAlgoVowJgDzAYBlMA9SQw9h7TfFIoMNADEFAtIUKrOe3jKKexD9uml1bLdyPtEKoZMgwoEBLAEAQ4q3ghIL/kFuxnh///5yyYfpJ4wKli7ETmJW+iE8yUeQws63//ggfg4k3rKAx4GEsgSJkULhFzNtMqERDWgYsAX1frOFkEDkNvME/nQCBZ7/bphE6RVVRmXAaBRb2//qLQRDiYVi8Eaof//WGTBx4babKhQAACR+3KYbGhwBkwBQATBbAaMBIA0wJAPzCJLeNO8VM1djHTBLAPDgAFV2rS2BpVRyie7l3XdZ0kNigONOK1eLXR0JmZJmAhv/+5Jk6AP2hV/Jq9yjcAAADSAAAAEWsX8tD3KNwAAANIAAAATAE3U3r////ceaNGWGmJx2LCGLUtahUSMFIguG06W2kX/qCFODg/rok8BhiwLHi0YEad6kS6QECzgqu37G4CwMHEzR/qBMMh/tzEIBYk6s7HAKk3/9R4M5GDWLoz///j6DexRzZAFavBjc03CABAEAdmBUDQAAHwMEiYt43Z3SiKHRnGoYigHhg3gXmAQBcYDIA4UAAftcSmDWc5dLq13Vukh9lhgaCJuiZxgGCYOAIVDoyynIwfB5OVwoZpsdf/6zqNzT/kyq5i8W4YMbTIfjDvoOGSoGmLYKMRjVLljr////MhGEeFe/+9TdJH0dDAMpAgBH/l8OUl/ncIWMkCY4AAuTB1XopGJAgAGwDVokTZvJUCqszV71ooZPgQPhRmg9EmwIGBByKX/5wdoSMhQCfWHWBYObf//Ytg5MCIAaVRQAAAB+buLHhgKgJgoDkwfABg4BoYA8MGE/c0KxQDS6ZnBQSSXAEB6qrWXFgaSuzQ2Klylw529IkmQOXAQF//uSZOOD9WxfzCPco3AAAA0gAAABG1V/Jq92kcAAADSAAAAEk9QIAzcrPBxlZNDs9Z7z///ylMEv0jMYSPQYAoZmpuAEZzBibDhpFbXH/zME1IOXemePkiBjwIUaEmZj8c61GRWCkYemf6lkoEVhDjFX0gFgxe/r86KRBxtswNwtULZ//qKoSBiBcmguu///4vw0oT2gYBj2KvM/IyAUBgNDCmATMCcBYwKwajBsTfM54iY0D4BDBIBWBABaOIhCrAWUL/hl4bkQu59s5Y00Mg0CHOUuYHELRkizlB7Fku5sxRX+Z///q69Cj1WKmPxEPEh86K/Za0ZCRBgoEsGjNMil/LIQMQWbt1olgXYFM4iZMGhXdnuWiIhnoIAxdUv9MoAPRAiMG6CfmIGDCmP9a+kGyA5E1ZYODiDgH//qLQTDh5sUOHaf//6g7onITcWlNAAAAMaz6qPLJLTGAgBUYJwKJgNgQGCSCAYmhWZzzACmbha+YKII5gRATDwmL+Q8k+xVS+LPC/strZdu0ERbkIg6conBhwKDQCEAeN8/gyQBk//7kmTeB/V/X8uj3KNwAAANIAAAARc1fy0Pco3AAAA0gAAABI4bl9J/KTmfe8nqjNRgDlRriEAvBH4g7YUARnE/AZNP7L5eqtP5KglHBF7SpuYpnhkgNMBBTeOwmBfllVZwvxCQC30Yh9q3qRPkVAwo0FppLtT5SAyQBS029b6ZkDQwDCaLrMigCEmHSpf/zhIg0HhoDGAcMdyf//1hnpKBbElnIA1hK24RNYQwAwAjAxARYAYBIAZhFECGmMDWYSi9xED0zVWRfrM6sG0kvoJncvyxv51IJKgMMNqkvcoKIgWYPkaR8YzrSypCcL12m5rFR2LO8YiDhEIoTldmltg08o+MttT+W6ft/V7CrwgCpMJsPqaq/i9QwNl1Y093fd9sVostov/a3qrh/P3cmSEOsl1vPD7LC7zVI833qc2CDCNqkFIBkpJ//6jwdcVFahdjQ//69YuxVCjMlWmAAAACAAAALxoBygCjAAEDBwPjEoTkyggClAQECBgsoxiEQJkTCZgcEJg+CalcHuwoG879w3L8cpyvKH8ilJOICzXwd3b/+5Jk6Af2kGBKQ9yjcAAADSAAAAEW8X8zD3Iz0AAANIAAAATsHFgLHwigjFnCpQ63NWP+/2uCSoYuUnKSKBgCLE1Ul5fN1pn1LW6wrQzU2oIF8kwQoJRlpPUgxoxfDeWmmt3fZwkpDWmzaoyU1J/+gLI+nWms0P1f/0BrIDTMo//9Ws6UDSiKAAAABiS5lhkhjBwRJNsDFzAA8wkeNJkj1eg8NgLxioUYWCF3iySKMC1Haf6jqymlpuylyXBBgCYIAq9vS0JMAGhYn716raQo0HWayRm45ScurfFlMHES1WssWut4t/izEzXrX5rV6nTpZXtrb/9s4USyo6PmDAT5vQMKMZv/QCNqpkf//QKJKCrv5JZ0OqaYAARmAiIlZr+ICZwPQJPvJhEchLP9BMg7+QCOUACwITDBwPkGkSBMQEz7f/7mN5cDkO6XIOF1JLs5IpUjewwvMv46LESjiwCYDHCAIWSrM0IdoC2iuYuWrzLTa3POXbLg5IpKKZ6mfmc9q8UdHDK+XrLdUp70tQrWYncXPPTNIQwFHhhnGozCqpKr//uSZOICBUhf0HO5a3AAAA0gAAABEfFLQW28VwDSABwwEIkwOUaNisjsFYKrDY+o51v23FfqCNrSPX///WAQJOlfkng1ArCMEx8Dc7an1PyKd7N2//+qnq3/IRGnnYlTyMdrTujHq/0FqcO9BEi6Mf/sf/+RtPO7YgImsLOPyVqdjzXqOWGBBNXFBIYDM5XPtFM/UOjENOMMqEAAOkRAVYZQuZgid8k5aCJNGyib8sYCzUWc+Axb5KK9olelLnEiYZzuVUuaRUkahXxEvCi6S+b5bPMlvxRKb3a5s9qzKNc0lC367ls/iOhVT3lbLZ0cmjdzuyqd/j50vT211OW1drl9KZ6tvzXTT1J//SoRgYNFbjNCEhIcSCdArSC2//+qDlVv/3b5LQWRLTZz0oQhC1Iesov6XV3FYuTknIBT1CbmbH//55NZRn/R5iMSfyOMCKOoUP1MU7VDYSVVIBeWBVMqKpEYIDMwyIlw60mkXpbXbimSlquwI1y6hKXKqwuKrMczJ6UpqJI2zFsio0nHZCiE2R5ZrzP1Mo1jOxFe/PBqaf/7kmTqgPPVUUerDBvwN4rH0AQCKhEhkQYNJM8JTK9fgCML0HlTI9UjQN4XShRspFvU+1jpYVwuqyuPUv0QjoyACEuW0US9SUJNFZn01rdFEzIXI97nVEciAjqNWlN93YEXt0mkBr271+MmMkyns5dICPjy5cx8IwArK8uh3xWrKwzGtE/koco5VY1KnLAQRxETI0DkgtdEI4pSBK6l4ZkPOTrWUaWqHrDMxzK20oQ8Z6nEZlWzHQVeleFTFnFTe1xacTKX1yr5FtMUVsJazm2ViOxRt0ZyimtJ2fSm9MlMay+GB1ErBBmVWHsf6ANP4a/qgW9ceQUcGc4ZmYycL846GKOcoo/pjgebUslWV8c4hNfSdLHPkOEREI8H9NRrkJCsWTEgwZyxFQbDN/+D3PYv/EI7tyCRYuCl8mBW1WAG0sAAlNV66oMpusIG4g66CCyeJ6MIFIcZa9bCLkDKubeMr3EbJSbRTbNNmlvnOzGiEbliB0xbLy7iCdtlb3J2irHStcVPPiyazK3F1D7t6szx9IFdksYMDlHRFLEhUGFvI47/+5Jk4gUS8V1BiGkZsjPgCFkEIl4OOZT+owzYgW4v38AQDEkglvkwSGIiUbLWgzMAAAALToY0JEspsyZkZHfh/vInDky0KkXfBst4zr+TWZGRtkz/VthJqpu0zGTjwsusWD9uF3Y4N9/U0nuTHULIrx1+11cr+T80Rae/MXCszvGOFSg5KZM681ZmPm5MdKl60hvFK8V67Jt/iaRFcnvdQNpjU9TOdX0zxsoII6I8dRIt/JxedH5a5kK3CSQVFR9y2jiHplBgYVTNQxVTdPNCFv3yGOP4gwARAZ5Q6ops+NRl3MI2orOscUg9XGdDvKdlavC0ybzBkSm8StSKbha2xU2dr9DkeXkYRDju80Kiv/PfP996fpDKXRzKGO5P58U8fh03/6fmyF9k81N0aVMgSzdjplJStJp8dRvktqLGlKZQGqpcGMM1GRK0U22HZ+KYSKQ7kKoKM+LSsQyqNQESsUGZQHSYVpuOFHYkzWsoIZUHPoZhCipU6lFMbNtRbkHxw1ZHxMexVzIeqgkEmRkfGUEb6gl2zDCxJOuabK4JXmgJ//uSZPEN83xlwIhmHeBWDIgYACMETTl1BkMM3QlPsqCAAAwACggbME4QRipNmaYclliHTysHDctmOqG4yKUzM2nz4mWN+Y2byvCMipNke0krtAWZXaEMve9sRSMz+l875n7tfUafK5JOFLxDHqS5Gnjl1C6EkZVVmn+CUXgaluwhVfAtPbO5Zjxha+wjSvik+3hF5r/eSNNKTP10nb3px8lAVuRljy2TEYRHIhrNsUNBqhkoLgxyRcTQhSKVyJL5I0Y1MkBCk2KLWFV9BZuMVOHRHkIc11TMkRTBtmEU0zdEMjMTBkcK6xiYUDY5HG4Ytq5ALmpS8Woc7KQx9ooLnFKZx/XQjcp5sy8nU5Tho8UIbGtm5eVaN6EzNnvxTqN2U86WcM+yiopy0iNOwnPz8pUPM+XPZjhUipkuJ9/MKwUgHsuZUpzgM1bgiKC2IyIRzChIklpr3cF0ZNfml7hI18+Uz6yewVr1I9LnavNrtl2/Sqlyc6cHyDT7q0Yjrx3z3Gd3OK14K5hfJ59vZrDY8PO40ViOkydszEiroo4x92Wv8//7kmTuDXNeY8EAYhuCUus4IAAjFE2ljQQjGG3BWK2goBCMCRHH9WcW3uCaftBmTn5qFyJZ3dqe1XtaGhRHh22/ENyOnllC9KDNcy+sSwgQ3LVlujz3j1XhtyeVkqgiP5CY5tS32z30iEp8R/Rf+w4UtjnFqVTkyxRS6VFyMF3YHmu9oCxvA0hQY/dHO29EkOIdlYGxvDdZadEHQfiA6ArLmjQiBNCDZT8JLa1GgpnPoyAiuh0Wu4QUplqZEDJGiVjQQhlRCuHcs/iEEClXYyJkKLYR9omHTGBiAb2S0M+zFGRGDUUTFebh2Uio42PT15KfFU4kXOi6SG1IX9mdllP6PXQtAdqEaObI+bN8kFFF8RnDYGEYLurVzNqY9GaIDpbS5mvDOn41KeULzQj7KjGnYZZDh7EcoxeK8QwyoERZTb8+oEnVEo1AAKV67KoPZhwwR9QgdrUedcHmLG0Rgl+QQQbijtRddZBaJbIj9TVieWeOFihGKuoeC27tbQ4ojcu5QyHEKLCUixths6wkWwWGTu0MrsjC0SZgDk62Kh2AYnD/+5Jk7A3zVGFAgCMxclLrOCAEIwBMvYsGIYRmSWAsoIAADAGUGctgMi3hFkWDq5b57g8WAEiChe21GabBow6Ih0kirvkXflWhXKrlDOxmbNm4q2EwZ8yOkxHCMHnw4cLGN55/G72kSatfynodPsMHnmS3+l0r9+Un/y81nBek2P5fLXncvWlUxVmxkGvZBnzUt1eYspagp+dLH1ubSdaxR1sVpqgvzQQWIIFHh6fQKThCXCVBULrZmzP0F47aJ13RTvDWINfXUtt9ofXW8XSspXtf12q/Vu3Aos7bvEMeJXd6zE93YlcvfXAPdl4cvYQxAvSFunTtsdnP6A/CQGEeG+x5DDoyMyESR3dGGVBheTj8msoEsMgDb3IiBCFP0Duhndo9WVe6/MIOeDe4V1qXcuPdG2fE1O+aByufl70bH8gYlfOkXYALAABGOGo9JTdqg2imlQXPFsjTrY5iUcf2VdeZPWVhxFckilWlUqlgg0M3YMG58blJyCBuoZyUBvnTJ+nLjUpTDoJoWeUxHKGgUOAmOxDqpIavDkJ5SrymPB0W//uSZO0B85JhwbBpHTJQTFggACMKTp2JBEEEwAkZmqCAEIo5dWKUNhykHph+jli+YSoKHmbR7DPEOSRNEMfFv083qAE/OvneJAlIWznEgzcIjvznryQorks9kuT/y5wqxwrr9KAnPhlSIqiGRpLfn/LE/++Jpni5E37ubvnX6efHTR28qOs61IbssUCq0q2Ot3t7anPIKJR2I1IZJWK0owvXbMhOEMz1rgnqIdUiN1deZuwREMZZIYUi6wmIbIJVG0YQD1InEBhIkSdRpxZdWJVLLatGZyYsZaGBqzjDFAJJvfObiyLJswp1oOdPLKVZVq5PrqaYUfLmsh8bGBtW2gkBVTQ5NKmu1z0LptbpSCCtPeHCPZqRS0/ZAXrnfQwVi87F/qgs0Ns8jybPimuO8p2uUh1yiPTB6CJyGEZgNkak4xtqGJ2JWXx80z0jaUruDHgOrGnHlFFPj1jHXUe5vdvM2SqmXRklbIUczU9NlNoYO7yRKcgcdEFlMe3wljmzWpmHlnqfV7PyDUC/RtvUVKJjkpKmjFMYQRqsnaoLdaK8tP/7kmTtBXNeZUGwaR0gUuyIIAAjBkxZlQQBhHYBVi3goDCOyDXwhWEkDrKOf7lkbObGC9ToLNO6ZQAAU6UfM3QgXgmR0bQG0BkAh+GnwtNC1Ejue82xxIMjey3SE0ZwbE21kfk8vv5ka0p6OUVuGimZhaVZoe0VSWGmu9+QnMyklO5G27ne9NO2KQXxQCwQkAISx1hmKlKqgLY46zP9InSKju4MzLQ5ljuaZlEPBHZdyjKg3oNq6SohfHXsWftppujRk12ipEZDIiGStSf1NkOoezK3G44dvMjogv7rtdiNBkLtWUjMTmwbDEAABAAJ1EjYzGOYSJV1wWi07SyPK1okiH5SQwUd7CVWIszP0OSTjKs7meSSZQllzSVciW99C1a+Uh/DPbsH12YsplJubHhaa045JOdSGo/DrkXRiJf1aspOHVEBrZhKK1lB41pQW53lNqsKAmSKTUczWa14yrZzl3iM5V5DX7QIlGxB1vuFlntW0VyT8vrIjgWGOPA/usc/RZvJx2NJ9qtrfr9kT2NPyu6BJ9h7pOBgjwWtTEuSUEv/+5Jk8IEzvGRAAMI1AlVMWCUMI4xLjYsFAYRsAVit4JAQjLkCnc0cKqTTreegstrTQ4nNPhDIsaqWLDRG+UtKtGYusKFXLlI0rkaTSbGqhbP95I72XTly9FX9SkVpTVrD0B+CG7ylIdM7BjlIs0i31g6HJ2pHNoWR+VEMhMWex1TL0zUm4RGxh0/33CUmB8w8aUT6Bw48KgLCcpHH2FBou1LMnIGKQlciaihxKHRhGRlGH7ZDqCiyzjVnplv75ISYMjgaD8zar1aRnXUrYumU3yIqOYWnH6y8dkq+W8602h9XidLyX1JNn7+8s1Fytm3dNAOWU5Sb9lUoDwRc/isRORmRdpLpuvYPlU2QUynYTTwt83lccJBajMrR0dUVTkK24+iHajFZPNWr6p/BS4Ata+G0cPaFiKux5TNv1ezSLY55GyJ/PDTBtVIMggA0NKWmJ2UXXzJowuW1zzaJ5E6RJORFJgxMSJhJCH24p7uXvE9dGCnmM3KzYLk2MRSWrnNCrdzyXq8Z4pjHReFXmnevbHlH/rTvf0Ye8whN+8Ld80xj//uSZO+PM81kv4DGRXJUK3gQDCN0TUGVAgGM08E2oOCUMIqh5ukcyZkpMt3Pyas01V4fb5uXkj40501OkZnX0MQpgrQQABVzqIDDZ1yu5sqlp/f02+51W4XnYhmdUc69++3OCS2Kntezhnt3WX51evhNQkX+jf8LnCInKF3Rqle8CkBe1GGvJnxnkz9Rs7o2RRluBmhAAAq+dX96dh1P9yrtBmjlEL3crL0Zr9TRNtkJbKCmQO7SEDyOzRTI2Zz+QMU5+wr2zThiaDeoyqVRT7jFYuCDAeFkXrWfq5TOnr3W+lPOEigi2Erp5SCMAkTzD/5UzHy5VPURleVucjEo4SagTerbFotlt2XEzzAFSgxZ/AZmmVshGMwLRvZmJnjvGCh0xTcGA8vjpB2zaWvpVLj16ehvdOduf5rnCM6vgiK1iOI/i0/mj+/hRr0hx4hApw41tRgAAoihE0cVTTpHZHZ5uM9ppWybIxMiHpiRAgfU2tClKzS4udSchrdodmMzdrdM/Z1U7JNF+SGa8VNfO8pdEzHeVFNtx/e5exmf9yjhjP/7kmTrgHPGZcAwQzAgUQmIFQRDUM5lkQCjDNpJLqzggBCOOUlFInpRrns156tJxvSKmI5mFQ9dQh5z7QHSUmZSbRVy2MXvRlrORF8TEKtElJE8J8i47LHXcQT0k6iEg/5aWZ22kc/5W8+U34pI3Shkz/efDqsRnMOfkP4zzzM5ciIjeF8mCLuJ16WNkhUGaHJm8N5gYN4IJhfjL8W/Hz3bzayff7jK6hvyPV69UmheROOIUQwhjMkWQdQ/mJKcnQZXdTV6r+KVMJwwPotSi515Wanc4NZ+sMvpF0b36/fC52lVaeIcq2P15hvb+beY/Nibd11wPecRSjSUthYFJH/Hb4t9E80bb94YfCLlJH4ZEZIARoxxW/jCQ+A+zYmNSmELwNmw7QNwU3y+wjEpJYjL3hIXrRzqj73alEdIOyGOT5MFn61F5n2+SpAn4AAhBIgcIOyO6RREfDVaNkQcgRHTYP1ImOjJgzQTokr2GFTBxdwPlglllorIC6bMHBCOkwiKFYIHYUKJSMii0CHDH1BBYgS8IUWRuCY3QaMJD94DAgH/+5Jk5gnThWVBEGEyMFJLKDAII4RNaW0IxIzciRUqoUQQirkGccmPCkJuiB1HMssfBjsaNBQgMdU10ZlFepo1KgSLqRl1/IKRzLnCJYkPquk2Zzc1Ll4ZGaLM3m3UmVpkfGlLAqYnMTw5Z++3up0kk4bl+1YmONSzyT8iUpMzoPY4SQ8z8nRJkxzd3O5xpbs6a1Vqt5vCZhmB6nNieCyAAGDBQ0RiykOum934lo9zY4xSPTVigPEsdsZIDQBAyfgMi7GCUtAlBA9UPrO1tOLxypwx/IZ3TYzIyp2u+y5rLhsvCULKnD+YvSMW6E6p29DJLzllthVpRsuk1HsbC0sFkmIBDIGirl5+UDJj/jZdaohxRJGzyytBQHnMUzE9MJEc5RsK0EUQA6rePMsgRqOqLNWu1EV7M91vTyP6mayKiS3PYWux1csgpH+r/TbD/ZYfNqoIAyAApnPx1vhmE0rS19Wn1Y9XHznUR7VJJnaePGhQjRqooxaQrGKHFkxCCFYV0kNyi88iIp+mj6CTmcJFnPrFmlM6BScIy5/wdDFfodio//uSZOsB8+5jQTBsHaJVDKggACMKDaWRBKGYftkZqCDAEIo5LSMwxq+uvqPQjITIN6acVbIADNLcyCkZZ6q9k8gBvK7Ink610zv9ohj3WK6MDFisggAADChTARoIglwozstmxgNLCfMqbIl4Lwz/L8UM0AjVnutyoaInw11Pyl6IjsP2coasYe/DrhwkaJUilqGeIhKJUJJO7uPp28/J3lxfb8q42UpDaT8OdmVTTp9DYhJjs1Ay02YIopJlHw1bWUanrtmIYo/S2sr8pC/qU6khSRTWYSfCKOTKCk9mfOf/o4STNZzn5UlWXjZh0sh0EUop0dpRM9G1vaGW0/TkJPcjodt5l9tdeTq1OmqDEcRoAAycQKkQoG6aQ7O3vnRZISMPTatoxmlblhqLLMFWA7VFrhvoLfuxgBpDX+WapDXuQ4b6zSK6gAwBGF287TGFiTdAU7QdI9FBAo8Of5IbuIW2V6OKIZPoUMEpgKYaUOGt+LIkpt3yj4vNJPqa04oF18Yc2ZhCNUsk6LE2LQeONMKDy85LrWjedbupJ7bIHkUjK//7kmTmhWPtYcCwyTYCROi4OwQing8VkwQjJNgQ2YAgoDGJcGRdrk3AEQlhoLQYwoj6O5gWsoopmy3KKGBjLVfT7umRgY/xN0RMQJYkAjBpNEgQO3VX38PSKKg3QpggURoZ31a4NTAoYZJBpPsKUBJiGDqz//9HqYgj/2DMuZv////GfDLSgro3/6/hCMCXMT/2g6QEmK3HWF0tPq5GNaWCS6LheIn4bgxNqOHXk0V2O0GELIChaBFG507PFtBFTzdnZ0tZpDOTScdB7vRoEBQEPeuW5S9n7OlGWfxoFKC04eClJ4zvpYHp6Dkiihw4wgdCLkSk1F70JBIIoe9nucUioEJzZkBCIPgelagkWcgSTUBnhpSyo0vMSanNGYSkZkkaMkwCwBMuOwECSr2KZpxILP3Sl/by7NO3//+qE/eqpT/Qy1STqhF+M1s7vPAP4R3Ke7mplAe+hEYFGwRKDqEpMCtvAUGjDRVkjBQgOghvWkZLJQ8yQ0cgnI0NhiGD0Jhd5fMHoNSYqaKsg5BVcHogG4o6jarpieepZAmufuJ0Usz/+5Jk7IX0Y2XAKMk1YD9sV+AAYgoQeZcCIyTWAO2roEAQC4EtBBScEnQoMY8mM2qsMGI6VXYnJgysRl04yGpiw54NKU0PPMqs4HmllyYuOB8mAwCBQoXC45IocEJIaxpkebPA4TAoVHPrd9JAXyE+8sMHf9hoF32NxxqcFXCofGKUzAJYIBEXYp8AAIQvNlE4CXlLpSfrMpvRySOtaEOjmuztAnGt1VWw3WaRyLe7Q+PlLq83Gy+8OaRGpbX7FFW9qvC0ZRMKjWdEjZm+jJJmVEXZ+zuwXcTs38xC6oyvr5JE11NJ79ofJDGZtSOg/TyG8vXr9nwuhKrrHfzLEIP5qzdUC0mhkcT94lIF1GSQ+sOZw0RYYbY6pgi3MwMXs/jQJu+8rmZEK/svjnIIBThU2yg+DhQulgzy4DtMKh8a0Zj4LmbIrmazJ+BmCkRWQR3E7UvW3GFMFJURn6xhzcYlBgARgEdtOhSSZOjtC+HbDDEcZDEgwoI6AkSHFYXAmbwEpHZVMnY6jMVM0pCziRtrJGyzsz1SGRdz5zqFOmrnkSG6//uSZOYA86pjwshoHVJEgAggDGJuDhWVAACMwIF8suAAAIwA5w86GkilHaDyZhzZgupV9CNN14ju5Sd0pnQUnoORidu5dDlMMuqOjkZkM9H3VaUtblsWrT0Or9DXDvMld6jNmNnXka+KzsoYVSFhhXxMn3KOYjKnKR1UQtFJPMjPnc7kdjjUmrnu7kLGDNvOojiW5NApHHmGfTy4Q2FKdztrtGm/NVTztbVOfFLOOitQPjECoub03WstmMUbFIILmsclGhZBRC2drsu1U3mPz9XcXeHGmmOnvIIve656KCZ5fV6Kx8GA1GfCa6eUWPbWQ09A2oWVdbOoVsKts88rq94jGwh0vmKmDK/O5fFqqxn4ynmbOD69kHhZ6qEhq2Imz26NJMn1f0S8PtXwZmkp/CRjP5834lnG5/Wpvkc4tOGdzLz0+lPmZpya7sVIjpahuuCIFjYCFUANIoCucp2mV+odQ9T1tY5sUDDahzHCq4jMcOAiwxRhWOywvasdWruVONkXk2kfNJeCqwOkQfrToPrwEwg2EYJutQYcwt+8fzI+k//7kmTgAXMIZUFAIRgQSgyoIAgj9g6dkP4DIN4BUbDgUDCPSRboqaQHKr8lrWyLoI8rlaxu4F5fuuECAAAamVFlx97K6pgQ2i2aIlkHxiRABxskSemG2IepISe6UsK25aaSidxcuDlLnpYRKpedSfKKeWNB1qGOOuETRDAbgDSxWo1CAIDEnfSUhjXZaZU5CSJiEapM1BB8eHVqlJi06qsXn58V1pdhOUMbllgsouObLnmzKJh878XmJbBFGEF6dGBaToiZcusfJaRMaQNXqG0vQ4KsIVSA1BpWGudbaaUuw3qZKtucjbOIKkJiV7Emp6gxgKIkzcCOUoNIj7mewsaXRIiHGsNurDSkY/y9PuR+S4gnlmCqP+jgbDgKmsNGTR5UWQOGAGWzIxI6vBLkM5DSLBhocQrlxS3Z9XnFH/9Udod80YjKcH+yUp/vFOkaqGtYzPzJUZaG/vhBLgzHFfyVFgAC0tjDOT5hwxMyEsQSb01ciMY7aTk5RSVtvUMZHaUTMuRLiNVxA00zOIHa5HTWhSlYq7JUDnqhGKZoxkrmal7/+5Jk5IRzA1hBsGMdgkNACDgEIm4SVYz8IzE2iUQv38ARDykl9SCHE7uRM1Bki03B1ND1KtFI4PtqNVSmcKUdTFFSt5FLpKIy/TgJ1+iECAC1KOMAAqbbUd0UpGpMwWS8ZYtYqTg8oJlcu8oJjJLFCbhOYJuF0RZOtpcoqMQHVYxDNc4YNDgpLi4wIh57ydiweUwRF/RAGVlfJUWMIAhwcxyDVadyFofMuR2+JjijcPTBAYsUEQkkIiZOoVD8PTROIwjCMODq3Mmqiipv2n7UczjtrS6mjqiD5qn7hbhqgmB8RWMyaXiyryqntoVoWranhJW4VUy6pr5+YmYVU3i0lqV1obWrFONX1sOzbJ0TslX+12prsldmutk0qdJEfZHI60mfddFfK3VDKyI3mUn0Q9EW8uNY+/NdCv/PR6PPX04s1gyzRdzuyVbfrsz11QAgAAAIOj9a0YUoCpLtu/KZk3qE8pJ4H0jNk9R44a+kkcqnj/cae6cXiN27GV0GUqGzQJTK4JjNNflIOQDoCMIkOPv0y2/Rbpb2+CW0wIbh/KW8//uSZN+AM09jwZBpHaBE4Ag4BCNeDv2LCTQ0AAkSn+DCgiABizyRrKtMv7DusuNMicXh+YvxV5nZsu9Q/l2rlllLLErn5FOw/m8MYp36bFMxyNVYZcnLeqtLi68ovXreH9+mh6i3UjdSA3qm2Vb5NVaWGZVa+ZjP95qrL8/+pQym7DMhhuHXQmJRFvh6b9xrP6rSmW4apqbeOO6sXi/M8cpZIO2OZWHO//nf/4AQAAAAQMB4RILx3A4AdGvgGkBTvoSqDF/OguJEH891/ziP6MuP1MK9/+hgzVOlRzp2aVFHV//1MjiEGsYpb1cwwJ0UdX//6fGMahyQDpJG+P06YrchzN///2koHM5D9HeooaiewE83GkooLCcv////UyvU6jPCAqI65ZkAplFeDAT0JXPunv////+zHQp0LUJem3dlFk7S6SnCzKZRNsKVW+r3hot/T//LKQEoE7OOSW3W2aSu5egQwSV1AgsF+GDOhQGTXgFhFtJM/Dg5r1uMqJj8+a8yisYcoENlzQ0aoQDjAwAhmhWhvb1GqHH6XGVYhy92QP/7kGTogAbiZTuuawAAqOuXRcW8ABx1kXG5rTAQSRVAAwFwACBjkjTODhlHo4Ze2j+PRjPFIlnDCnUHY7k6T+KepAHEj4GEITxGKli/LX4vAh0f2m58EA4gZAMgyDiYYPbulfRfQ0eW9N5PQSRAK+ESTXfSceyXOIzSH8LXP+UXsanIF5/u3jvd7msLV6nl/556//wr6t///3P4IkVSUc//5zff//w5Y//+uxO5LP//7Xp///w1N////zF///////////wZragZZkl0gxLpwAAEYY5NKlesRAGLAiYcA6CglMIg1MloLPNiKO1vuM2S+MgQoHgnT1AQMCECd9zaSbtyqBpdKIakUScYgDzX14QhSsSCI4UeM2AUuWzdfKBXueKdlG+VZbAPIZMUIAwCkc1KIssEOpQ0Fu5Umq/44/jzC06Q6FJQv7GJdYt4yiaMBBRoBiMWlVb6+vz1KhIDz33//7WGMpFAFM6mvWeYY0FAobnzff/eP3/ytWkOkn3+VbF/4Tj++//5/j3DW8LlZcNLuCY1W7z/////////3aeqK//7kmRph/arX82vd2ACAAANIOAAARrxgS4PankAAAA0gAAABBTskEy1lLuQ2SgNBYAAGgapKCQL5hpBhG3oFSaoazZgGAUmBOBsPAGIliQBK+7zA4w+rWbMtpc5NPTjMy2hiJAwluW0JACzCkFBMCMBFdkPRl236kMtp9fqVPQzyG2MGppDSCFaooeXab/CZEU3GJOjHMf//+jm3ZFFBMpsU0qpo12abuBJokDikCQPnyIzmcRcVVMtFH53//7lit2JFzB42/OV6U2TYmSoE2FU1S9RslMTcigQSIIiXZkwQlKJ+l6LpImqnOOoGEPJCmiwIl1v/8yPB5CyKDPuFAAAAHdP+uiGxAHMqAPSLKBINbmC8bUZ3QjpreHwGEWA0BABFgkY4kxJ+Kj7U1NrvP7evyFi5iCgDqBsMEIChgECmDIAi5aSrjGcG9NEhgzIgKBgdoWUl4qmZFA2cDWWQJPVPLrfOvBqeCiQqolmgkxFgMUCCiYghoR51Vai6XRnQRMCq7dSNEpAUQB7yKkkOmBUOj/vrYIRQcAvTYOJFv//zlT/+5JkUgf1m1/MI16icgAADSAAAAEYFX8sj3JTyAAANIAAAAQUAsojQ7Df/+iiJcMUfTymAAWpS8zNYeEADRgRgCmFOAwYGQDZgVA5mDym0Zpo65vdlvmGkBaGAxFsEvnaVdK3ubhIaedu3LWOVK7QIBpy5PCAJMRAAJN5z8x8C17R2XWcv///d58VHY004BHkiKcIn6SVp+GFGACQGwaK2scuf//dvYEgsKCpvkzhq5QtUGTQsiN25znedwkcWReEAHqb1///6zlAhGA0CKfDPPmgARSX9T9AGqA+Hzp0RwIGb/+WKQVFpGA4W///F8DjD4XlEAAABGW25LAvUMAemAKA6YJoHhgMAKmBwB+YdJUBxlh6nFgBKYRYBLagoyFm3GWHiUql0ehuN38d5VY83EKh43HFQKI3aL9BLJFmsrCt6dv8z///nZZUfpJYArBBBJcrEbYIZpBpjsFMtjVKkj+soBNcCmx9E4xuPIOfA6gOMmxqFhdR0wLw9g7eNo87ezlQL3BSIW2X1LAxIkkf6ldEZoHLHZ2L4JECDI//ywog//uSZFcD9exfyqPco3AAAA0gAAABFrF/Lo9yjcAAADSAAAAEAUO1iQB9Vf//YvhQUHBFYUAAAIfmzxLdpA6AQYAwCZgmAVFqzASAOMNEqU2MxNDbnKkMK4CYBAZswdNgCzGDwFGp5/Xinr2W7lC9BUC5g52CABN8KAg2XHgUZGJxi3hnh///7jzRoy10xiNxocyKip4YTLMMJ8aHEVtcf/UCZgFqnnFnBTQQ2Q1aYIGyTbloiIaKCAAXVfrSI0CKMFBJsj8yAUEEn/tzENHChV2mBuF+hJP/84kRwUCMsSon///4vw5whh5AAAY24Ec9zDAHA7JgkA4hEwQQHDATCSHHjzLdK4OpR5kw+wNAUC4HAQOgOCgDUGQjdOOyyUQ7yru5NvotMEBwaAL6IQALYiIMzDiqTBMG0vnhj125vvP/Oo6aqcIEYAmIBcmFoBuJT3JSIwCMbDgMEgXQ2d2XF1JF/lkGjYKwU9yMNycGTA2i8Br+LgIAJ7I9CswJtxCgEzImh9n6lnBdgLYQGg5MJoM7OYgijkUf9Ro1IhoIVYUQqf/7kmRcj/a2X8mr3aN0AAANIAAAARqNgSYPbpjQAAA0gAAABKShkGXwWGpN/+ShkJcDDVg6wIhb///UEwYaUDbM0naZ/WtO6MgfGBMAwYagJJghgcGDGEQYiDBJx1FeHILMgYawLw6BOOAAKihqCIGiLgL9l+Muy5nSQ+wwwBQJTG1EOIQKQKAEYBYGRiVEWGCKBAoK16HabH/7/8yfVbLEhkCM01jJQByZFFHLBgAcPRBmU7tbev////+qQlxRe0fOZUFaOqHGFTgCLpTk/tLa53GDxcQNRgGbKkOMUvuaFYDBHQWvjwboK5ZACakTb+eaoshJuGMVaRMARNjhSX/+ShsM4FHLoETBxo+3//qCYcWgNYSL1UAAB9ySvQ3dlZIA8CQOQuAYCgajDoCKN+IJ01XnszCDApDgdCEAlkUz24upEJvKZzq2MudopGpE6sPTAwgYSAgKclO4cjVRQLPWe8///V2CFGrrsGPRQNEx75yniCHcKscAABlsuspI/1gmOCnA/zJAvjKAZF0BZ4QcvjoMH0y4eEIwGJw72f6SJND/+5JkRYf1ul/LK9yjdAAADSAAAAEW2X0sj3KNwAAANIAAAAQGHAWPFV/qACHGj/250Imx7UtRmaAgBiTt//LCY/BQg6hfiHJ///hwxNBKJ4UADmDE1iP+BADDAjACMIkBUaAYBoIJhOIhGqoJuZnMNRgWAXAgAEwMBkgKtRxOw/nI5bX3+WNM/qAo6SXzB4XZoWTOGQEiPakIHnLeGf//95R1n5R1JU6m3Hqt+cc8ysMjFAFYNLbSKX86ExALdOssLMhPIGPngSSlZZDjJtIqkFDCIASwupI/UdIwIWw5Bmr1FMAwWf/26YJEQWDoVHURAQOCb/+WHGsFCFQlZDF///ieQcADfjiAABDlx1m9kTcRYWC2xigJiF5gRl1GNSJ6YXSjIyBSBACkfYdvQ8/Mr3PUcjlef7yqypW0wkgaELG2Q6GBmHsJAGSW5vW/+osjVLxBgM8IBYsSJ80JsQgAxtYGCysz/+HUCixucTQGfAIRha2XEC+vqNz4vAGhpc/5gBUIGYN2/C23/+J5DK+mHcJ7//OOPweZlEaNhv//1CYD//uSZE2D9OJfzSNeonAAAA0gAAABFI1/Moz6icAAADSAAAAEQYQAAAsa3EnhjyRoBHOdowATYNMJMa408wYTDaXyIQCkATRSIAdfs1TxSGIVQT1B3et3I6MgGGCeE+YAIASxRQAkwVRDS2rXozTY6/6ZcIwrC8AxdICQAvoLOCugZ/KFrwyJeRS/1CMgc5bqSRJoDAHgUJHlFEx6zYvCbgGj5WR/uwN5woNPt86EIP//PBebanDvDY//ziQ/BdZrCaN//9ZGCSjNuhkAAAj+4AZG8DVy1JgMAGMbBQCBgziqmeCCgZBaKokCyX7Zugu5tBQxzKxyk1r96rzCHcxt6IAd2lbjgl4aGnlnrPef+ZEcTo5IGJYhe02PJlwXOBoBoFipeR/+SgOOv1KTIwB6IOkM0y4h5oeGuFsjf/UdBqPGRV+oMgJf/xQgeJtUi43n//qclBArSMGj///GoSJGOcAAAgOdhDb2E3ygASgmAgDgCFQrSZqeiR1B6hhGDgUAdVZu8ZYi7VeUZ4Wfx//wrp6GzL4WBIbZQcSmDRA99F3nf//7kmRsA/StX82j26NQAAANIAAAARIZfTaO7m3AAAA0gAAABP//9TcG4U5iA2RA85nhXZ4OrSFcus9/8oBUnquXQbAwck+ssK6mRIaCJh5/6jMEliN0PzoavR/36g1gmXsJGXf/9TkoItj6Nf//43C+ObUoAAACQxAAAMcnJYdZTKRwA5KAIwUjCxozjIijmmfwMGNx2JuOuzTxmd7e1Y13/zwcMxvBxDeDmNmFxHq7jGeG//9E6bDqBJYLiRSZy6BjyoXVE6kj/6wYI9S1EqDQuOegyb+5sPwoFD/uQgeNv4nR//4cInuthqlf//U5KDEykSf//8lCJkk4Ch/TZU/KF6VtDhVMg4wCIE64A46SZYFC8XZae9svh+VU9XC12mx7/87JiYzVmwMvIwEIZr0zlv//84SiJqCiwyh9kzAdYGL4OC3/5TChfVY+I0DznlHV/c+Gln/+kGDBpf4sbf/xECp1zQl//9UlBiah6///lIeiWUxBTUUzLjEwMFUcAAAxf7/sMzSUViDdsVJSmEi0G/RDnT5oiQUpVOHFou98Yv//+5Jkl4v0PV/O8z2icAAADSAAAAEPJX08jHZpwAAANIAAAAQp8u3t/3mWL7GLYOpDQ6sKBxaobCRI1Sb/TWakqBBCONBalkYAQsGqTyL/9ZHhQL6qywEBIml2+xqPkbi/+oIQBEE/4wX//inDY+Lx//9TnBvZmSX//+Nsi4oAAAI/kDObRigB4sBGDg0gEBCYAgG5gRmuGM+KSamAFJg2gEoCFA1CIPdeGZfhbp7Nbv45VZUMApwEcIBF/l7HfCZMdtWk97vO///+pl6Y01oxw2GhKK37EvhgWbgwqh3LH/rEVCkE/zjOQAAYUDjBEzMjDnUmsqAslLT/3YMRAsQPt8wBu49/+wfkDAHQcN0ND//OONYOBdQ3Sef//8dYgYfmTEFNRTMuMTAwVVVVVVVVVVVVVRQAAAhrFuTPYKFBACmfsxlInNaYRpIhq+hUmwST4CgnBoAdRRT8Oui0GCoHFsMl9SzIfINQIBhNjgLA4aYQAIDTsEAwUACLk4boJt9MjBuHxjAMPkgEQgImXC+TAX7AwIiQJCAdpsz/50IQGChM//uSZNED8+lfTyMdomAAAA0gAAABFH1/Mo9ujcAAADSAAAAEfnFkcOkB5DDBJeYvJNsWysGpA384j/SJkBcIgsETZvuAYAS3/+gOsHA184kS4qL//ziQrAabUKaLZ///FNFGFAnhAAAARzN4GluwIwLTAIARMDwDBG8wHgGjDhJpN6EKY2xlGTCVApCABgUFVL2Fw60mu+8PwjnP1u5NvAOhs0q+gcK0WQYFRBvQQD10R+5d1v///xlT1OKlqYXSIQEYapbVK3IyUejCALYNGaZFL+iEJMEW1+WEygOeBkmIIo5BC4OspoVGZcLgy4DU4ibP9ZwphA5G6YL9ZgAuQV9qm7AmHChlLSQBqJGil//OHwyQKDajENMb//6gw5oGMkxBTUUUAAAA/1xGbxQdACCAJQUHoCgJhGCEYF545kdjMGm6n4YJAGBUARCAIhJVUfSU2a0/Y5/7wryiJjAENnI0wQA0owKCjTUKAxKfmNUuWP+tRHismQ7wNcFBhkeCuXCLhgQDczgRPlq/9YQiQWkP0FGIzwAjwCQo1UTKL88VQ//7kmT2A/V8X8wjPqowAAANIAAAARdxfSyPco3AAAA0gAAABIkAYQapf2L4Cw0HCzR/rCIlH/brBqLDmpaZoGtGn//nDYRQNMaTAgVv//xLRSgjRjAAAx6/qxn9MAMAMwMgHDDCA1MDUCYwRQcjDYWtNqYbI2kKMzC9AzDgXACFxICJ0N1dp1GBro3b/+Z2Je4gFAZ70wGFRciaDgyePN4Q0UI21i07f5r//mcslDrIcga1gYAnxmJuCCUAmG4CYABSlr9S02Rf9YNFoKofKRcJsQgAzeYBSQM2TYxhQTQTMCJlsLUABaR4N29kkSHACFgWnki7dZSAEOEv9s81RKhCxGRUtRZRGCFAbP/+WCsEQAUQssMMHSof//h/QoMDp0lAAAbuQa0ZnogAgFQJjAaBTMBUBowUQKjE6EhOlYOgzybBDAUCwCoCZgcUEIDXwhjDz+svlMjv7/vL9E8xgADnvCwYOF90LhU6ldTKoFEgA685bwzz//1dbsk85KCUymZQw0s2kMjfhjxoAPGPAWuqM0yKX+EmYVKH6llI1LwfqBn/+5Jk/YP1aF/MI9yjUAAADSAAAAEZmX8pD3KNwAAANIAAAATb4DU0kjoxxSR0SeHcDUIBrwoySKXrUYjPBBQCyo6pfnQMKZQ++e1FkEloWloZiZgkQEAkf/5YLYNAAOOusMmFLq//+5DQcYDqGpAG8HbWEctZBgIgDGEGA+LASgED8wqD/jYIHRMUiMcwQwWQaBUGC98km0c2QQS/Man8e/jljTP6FwgcJX6ymHDIUMl7AGA503Yr3N6///eETbHOs/MUH0MF78SuUPuhwMRrIaJ8Ws9b/g1Sgxg+ssLKAtYGErgNFyCFwi5m2mThOhxYGRAFdD+mXAHqARDDdB/OAYQI7frbuCQ0FBfMD4NQwti//5w3DyBQI8awXXf//6xaAu0PlUAABavSJvYUAgGRIJsxAwCjBCAlMC4JEwUXcjJxJ1MqjRIwIwOjAFA3MAQWaUPAy2BhNE5ctn5F3LKrNQCvoYDMzSYYwDBAHASYHBqaAy6YoAelIwGGqWtv//8cn1VRXUFQGMQjQAwpMtjVLGhEApjKdZg6CiGrvS0vIpfm//uSZP+H9llfyivco3QAAA0gAAABFtV9LQ9yjdAAADSAAAAEANY4I0CHKCROiPgNREBF2GwUBaSNSrOE6OaFkoAYwUU2Rfux8lgFAYLYCXPOvUiAM/Hl/1oqy+F6QdCPOslDIRuCw0+3/5YK4QhgYUdAjwYNdv//hnAKBQJAiTYQgAAEaxdJeLSoMMGZPO2NAdN1VMN8y422RdTQRg3MHADEwCwFDAcADctcrWIak9NXiNW/+9XZI0cYAaMDoQsLALqXGACAUYkgWQYFUrl1pba531HR8CKGYsgDfsgUiDTJwnxzAv+B2KICmEgyKv+cBNeC01tSjApjOAL5gbHCbNycQdnQK5JBnQGEBmi/1pFEB68CwFJf3BYyW2/X6YfoFDbPSMATCjRS//nD4YYGBHUJGJMn//9YcIiodg+qIAAQANTb0LTVUIASTACA1MHAGIKgHmCQBYYw52Z6Jj7HExkkYQIOAcCcDg0NANdC1FTwM2lPf5LJzKvKHTTQBo5O/5wKjilMGBQ/3bDTQEKwe0CRzlvDDf87ek8SWqMAkAxcqP/7kmT9g/bIYEmr3aN0AAANIAAAARelfyyNeonAAAA0gAAABAluUGwQz8YCgEqxicIoVOrLjVJF/wlrB5xrsUi0VhOIHDHgqZFjIeJUPy6jpkOcGRgFW4uIqpM7azAdYAmkBhOTCaDOyZDANGMJ0/+s30XAgmAtCNXQJsgAID4bGr/+ShLhCKCjVM4EgYhRP//6wmIAsDBsFj0iKAB+b8LrhwLhAUtAegiNCjgwRzrzLDFMNRVN0wXAESsAkhAIddLiQT81WgSte/f8zpIfQEGHQDKqq7IyAWYNQmYGAXfybqb1v6iVFNIsOIDVDgRKh5PnjceAN2lAyoAXCXkUv+EKMGDm5xE4KeEZYrpggfdtyoVQ6oYGMVf2Phb6DjZ5/pA2qW/9+oIBQmTZ1iREyb/+cNg8gXWqHyJg3//4vhNRaHowAAAAszzBVNl2hcDUwPgKDEaBTMF0EgwaQtDESfjN9Y3o8oHcDFxCgMFoAUwtCYAASn4tZN5dcVnqKrG5TO2qKD2rEwNjZZmCIIgEBjAEQjLy3DB0Hk5V8QzKquud53D/+5Jk8Qf212BJQ9yjcAAADSAAAAEU1X8wjXqJwAAANIAAAASncBbDzEAFGIp/GEABNbfR22AA0FTGBHysYHNo7zt/Mwh6guBbcoJlQSmBxBoFyYpQgAkY/qrOFMoiDArAFUW2dnZFIxGOAw0oEV4nUupY1AMasIAv2z71kcEnwrBmpzEmwIGg941S//JQlwgHA5JcxCik8///rIkDm4BAE2FAAACHNN1Ueg0hAoEQBhgIAWgEAYwKwADDEETNwoE42hSHwMIa44kD3fWFfmWwTAUxLaTGp3HKlh4KAE4geAQEFgQQDTbrpBR1V9AM9Z7////jEmxQ6qqYfMIcIYepa0yvoxMkhQBtOltpFL+dCFaDkKvUYjPAQoBkYxcuovsWyJBbYBIMvL/UsfgaqhZhmr1LBIeY/79QQkA5i9A3DOh2f/5w+GuDTWWNQQKh//+PsLjiDj8UAAAAdqLTLcNLEAC5gOgNGESBmGAQGAyCSYbCHxuRDOnJQHOYdYE40EQNAdTADCdp8ji7iP7bltXmdarEm4iMQHAYeYDELpBwDOqG//uSZO8D9uxfyUPdo3AAAA0gAAABFo1/Lo9yjcAAADSAAAAE8aY6zICor/M9//7qPGo3SMrMgF8OKbqS+MP+rgzaKgccndpsUv9EEo4LHG2SNC+OEDLrgdIHGTYzhQ1HS4gLnAYzEuef9M0ASaBRwV0H8sAUMP9qkuwFRgOQJssoJCyg0x2//OFsIAAMCOsOoPtD//6gycEQINMLTmAZckb2QMDAHggEswqwAjAoARMBwGswH1CjB5HDN5c6YOGAFgWwEBUJTRWDtzgydltBKbPct3JK0QdEpjSFAgEMGFAYbNtBjACOPZr4Z4f///aWIv0mUYCSiAaI0E3ABCAQIwwcLHVl1lJv5wGr8FhJ7nETIRiBhbYFhpeRJoybSLRBQtSBigQ4UkfskRUBJEFlJs3qYBI1P+rzEUkFEB/MjACocSVL/+cNwvAGAKxTg+7///UGHHsQTPIgAAAAyxfZgL7ECkxY0+K4zxc1U8wvzfjbFFnNrpUUwlwFwQA8LAGrQQ0YS/TzyKT085r/wryh9woAoYQQf6GSRIWAfMA8bsLgFv/7kmTlB/YnYEqj3KNwAAANIAAAARdZfy0Pco3AAAA0gAAABLKidNV1v1HR+ESJkcIEwYLSRtFo+WhBYDnbAMkLEAiKl5FL+kEL0FBLdBZcFJgZB6BZmOAuDrM20C+fD+AFSR2O31nCVBq3FAnF/MgMAEJ5v1eiGLwccfMyYCASNNX/84fC8AoBzILzf//6gyUT4JYVTANXYAWWwggAACwEZgYAjDAB4KBoMRcfE4zxBDc9eeMKwEABAdjAADhEqRPhyWOvLFJPDdnP86lO0gAgs5u3iQQo3GBQocGvhjUFKhX9LbWP///3CNx9+UOpgpXgoLwBK4g4YWAhlFNA5DZ4d/6wlLBwn2UXRZwGUsASbEicHSYpaJWHEF+gNCHJ5FL60CHgIWgWVk4mh50AYuY/1NqRBMqCIyfqLKAnULrs//5wrhIEDAjoCngsCf//6g/oOACAp6oUAAAAa65CgcOAUBMHAmmEwAQEAXDoJxg5pWmhCMgaVj9pgfgAjoCQjAY0FRwAPQ77sSyXymapMP5bvQeiodSKphAQM9AwBOTh8ST/+5Jk5Af12l/LQ16idAAADSAAAAEYIX8rD3KNwAAANIAAAATKcUmo73ef//+oBUdd5OYx0WAwjOrTVZIomYfXZYAi1YtZSRf+EEEPdfugTYrgGFqAWIEHL5ADB9MqFoOuAU2Imh+7G4XMA5kWn9Z0ERQr/7alg1MiLG2YpgkCFuR//nC2EwAZhlCKjnL///I0KBQ5YgCraflWJxSEA4wKACjDYAvMEMCowRwlDDKYrNZQtIzoa2DBOBoMBAEEBAxDdMR1k9pyHp77cjy3asy53QCBj5ZfMTiNXohCJ0LLhizQofuWU+Gef/+Fd0FZJGqoZPTAQWHHjEbdxIsrPxkIGsujNZFL+4Rtiin9kjUvCEoGhlgiokKZjWKSKlmRVHNBvKBtgQ7TZF+tIxH0AtIAaFF1L5cAUVFx/57UdCBWMulmBPhMoLYv/+WC2ERgOGoqEREkR//+4tAOKBawjRCAAARjk9LxNjC4AQIAUMBoC8wAQEDArASMMAVM2yADDEafHMEECEWAJFgM/CfcP5Smgk2c7S02WOVWJCIGm9E4UCBU//uSZOSH9dxfSyPco3AAAA0gAAABGSV/KQ9yjdAAADSAAAAERYCxi++AIAN1mrut6///8ZVBTup6mDz+EAmGpmYiaHAwanBoTwNZyb/OhC1N0upZgKHAIohaeTBoX020CuWw1gGKAlxf9ZGAhUBdiaH3Bsyn/t1hAPDNqzjjLCBH//nD4Z4HAZMhvDf//imB7oj8toA3cibkMzLeGBSA4YR4IIAAGMC8DUxCkejiwEfMzC3IwXwOgMComqOgEv2lCmo+71xuNzM1Lc9XY82EZDBtGmmDxIDgCYIFJvX6mHgals12NUuX//63cbGi7Km+MwB0WObZpPRTymJmVZmGQkla/UtNkUv0QQWRR/RmozQGmQA68PBQF2UVLUdLxEhBYBsGLEapN7JlwG4gUmEmaJ+UAMKUKj+1aPcGhEHLzR2MjACI0NhNm//OEmEhQMDMmLQDgp5///WEAAYIbISaQEAHb0/CIPFABBYD8IFiMCoBMwJgcTAdUuMJgkc0B4DTAmBrFAFhYNg0ELxkNFF7cNV6ezjrdyheghDphuBBYUqrAv/7kmThA/WfX8uj3KNwAAANIAAAARlZfyivco3QAAA0gAAABIDHGkECj8LAmBp21zv//87OVH6TKBqaRsicxK30SrMnGcMNtNvX/OBF6HvpdZgWRLAnkDGhNm5UZ9yQIiEQIAoQxUv60iGgEpQUQmzepYDiKf9a+44QoiPOyZoEAck1f/zhbCYILrViKClf//1hrhS4gKbCAAZbiTSYkIAFzARAHMGMCIwEgDTAgA7MJ0zg1sQ7TSWaCME8CJIdiSQDbvNFJPWldBX1S81upAYiDDrMUwIYWumAfHmCSIs+KW7GeH//63BTGoyu0zEzHj2BqWtJU/gBTFy2nS20i/9YJsw2I9smx8qgWTAw8RMzH44utR1EgoLSB5dvrUSoNF4lMwX8sAkKQ//SC1AULHszYZUQO3/9RWCIAPM6xLBppf//inCBhGx+1SwQ8adgNAUMBAEcwLgfjAKAxMFYAMxvSEz03BQO5mlsxbgezCZAADAcGfgYBlNxYNYZ0H1p37llNezpI2wwwDCE4hQgxBBsmCgUD8zQt0whBlKh04hN1M//+5Jk4If1s1/LK9yjdAAADSAAAAEWLX8uj26NwAAANIAAAAQ+dwzpGlp3vKg2YoHWYZgKxB/4cd9GgyrFMxdBhDV3pbTY5f//+sREPoYJ8g/LHspgpD0Rl2BABj1h+rV7/494pYJlAEoR9GKl+5oOeBiloFvZIG6CHJUDBqSEV71m7siRwEGAKNirlEzAWLBmjVL/8sDuCZwFhp9EOiByc2b//1ibgoqBYyWxAAAAR+boM7hwVAfCAKTCCACDAIjABBOMEVAU0GRjDZkO+MIUC4UAHaQzdLqG2Lxq9EYnW5r+dvT61TlwBMHAFM4EgwzlbjB4CZzGqXLH////KUthfpPYw8cAgJP7NTcAJbmHkmRDiQ2uP/nAkxBxb0VmhEwMcVBy8iBgR51VS0FEHBSMSbP+iTQCCAKGjV/WoAAJ/31nAmUFuR0C+EwRBF//1FsNcIY8shlX///JUM2JTNowABAAx7LYtIRCA8GAaGEQAOYDYBxgSgrGCwhqZpQxhtYkEmEkAA0NaojAMcgyNUUcj0st/nzvLUtTCOMl8wmGk6QA//uSZOuD9wRfyQPdpHAAAA0gAAABFml/Lo9yjcAAADSAAAAEBTc7PAxZXtAsus9///9bghTqu1gxqKigcQu92lWUY0QgAALJpbaRS/uE1oONq51RiLUAJKAsCLqRdRfctERC/INhCil+pY/BAwFzGKvogFAzV/79QQkiCNWccQmEWf/+o+F4CaMoUOJ+T//+oWsQMKQPEAY5OCvpspCAaBAHjA4BBMBcBwwMwNjD0IFN5IMA4EhSysMsWBFBxqU0Llv0ySvGm1tUdqkyxypX2BALN1NgACd0kNzkSNIjurRB9Ff53///5R1n5TbCqfRViVDKIbQEGWR4DjVGa21f50ItQo28zNC+LMAybwCzAg5fHQYJ1oF9MTwApVJB2/THQAlICJAboJ+kBIoVv9+YBCOCgVHOGAN7iNUv/6i2EQweZlCIjML//+oPKKkICnrGpK4YZWBAUjAnAeMJsEcDASGA+CaYlCaB0/DOnWCtEYaQAwgAKFgfyIBUYAQEgFn9fxucJlUgmpbjWqxJnojD4xxZECBUlGQBYaPyEYQAYXbhif/7kmTgh/WpX8vD3KNwAAANIAAAARcVfy0Pco3QAAA0gAAABF0meHO/rdxopIAbhLWMcAyFh2ZrGo68A6BYqlpg4BSfL9S21j3///+6SCuPDv/9xr0sqWBMISBBQmxaq6Uqx/8YUMkBUIBpRoyRdSR7sbFUDFiQWykkefuYASdFR/1JcjAhHApEfMy4EBsZNX/84SQTLBQStINRChQ8///WcCIcRoBIESxgACXb0jeSHxEAqHAhCwrYCBFMAgGUwElFjEiI7NuBWcwdQLTAKAMBwnk7D0+6fccqyino7/7uULYCULme4QTBJGkKCExzuTBQNUektarrf///nKIIiyshhdHBAYjdJTyxnRlQoGHAOy6M2kUv8IF4LRm61mAr4GIlgSRkELhDzNqkyoWg4sAp8SbfrSHyBVqFvJkv6YAw0tt+pXQJcHIXqOoibQyrf/1FYIhA4B5cC8m///ErDmB9CRoUAAAAZYu0uV9i5hkRp6Uhliprn5hUmzGqGI6asrDxg9ADEQB5MACPALqgfeVvtVsSvtbn6zmIbCwChhxBbmD/+5Jk6IP2v1/Jg92kcAAADSAAAAEXNX8tD3KNwAAANIAAAAQcAWn0BQBDDSEQAwPUOw9S5Y/9EhwpxBQ5EDV3wGkJBjEoEPBAAA1PwFox9n/6waowWdtzqkRygMUuBZEWlEaYvqNSdE2gDLCIpN9aimBROFpaCf1AChDV/7dEGoEFiL50zDCAozf/1FsJABJKxaBJW///IaGmiAdSGV2OPW9AhAdBgC4MA2BABYCBdMO8L038QbzRSfzMBMD0MBKJhQmm8UblEUleUovXbne2Je7hgEAnTzEYTDjQU4DlIGGk4q6Ez17vP//3hAbGbDSzHBZFiPAl/GaWSYtV6HZlsWspI/1hFWFLzajqBTFoAFuANCCDl8iiD6BXJ4NYBkgpOJ/uxXC6kGGy07eUwED0P9uiEI8HBTZqBfCIowX//UWwiGElrEqJtX//5gDggjBcxigAAADDrWFMyyCFRgPADmFcAwEAhCIFAwqVDTXDJoM4Wb4wfAZDAZAjZABgGwiBGoU7rRSYp6Wn7y/OPOWtPDDQwEGaQdCpwK9mOwGrBD8s//uQZN6H9b1fy6NeonAAAA0gAAABFqWDLK9yjdAAADSAAAAEt4Z7//52WwC4yCIwYrC2z60E3DCY5moJgo8supckVf0waLwd3PbGZ42GRA0KcFqI9mY1ikvOmxBg/YBTGNI1dutJEmgDGQIkRdS9aATMIfbbUwSSifUsoHw2YNIf/+okghFCqrEQDa3//+mH4BayHIvkKgBj2KrqcUaFBDA+gMyYAzcgwQDtzKAEsMGBuERAJgYAQFANMFajN1pbIMq+628csaaMohGGyD+1xpwyAgBgurAVAA/lg6pf1LJQU4ujtBxXBYWj0anCPC/AC6MAaEY4jVJv9YNAmDA+3WswGfBIkiC5cQN020yoVQ74Ng4vq/Us4CYkE6Jq+iBUDnv9vCYPFvQ1KD9xRX//qNgvAbObB53///EqGRFLFupgAAUseglmQ4ACIgBjAEBEMIwHkwRQPDBvCCMapCM8riXjSI6OMM8AgwPgJzCUCwKALTg4AC3y8YZdeUwy/cDZVZU+qZQMDE0waoVCADAiYHB2au0GY4BGXGYi/0Ztc/ne//uSZOaH9g9fysPco3YAAA0gAAABFS1/MI16qYAAADSAAAAEZ2H/eNkpYAkweQ0DA28ErpJ9fplGapiOEhdFxoyXkUm+dBBHB9cqLWkRrksJ/AC8AuaE+EMErH9VZwmSAhikBuALaVkXbsbjgAw6gHbCTNE0+OoDIJC83tWa8zBAtBE/KiaBuRQEkZD1L//ODaCZ4PAyAZ2BYkn//6joSHDTChQtmAAb1AbAH3LBAAjDko0DDGkzCwKcNk4UEzc3DzAEAvU2ZMpw5067sDRqGqvL9/HV2gfEqgMCgdY4Amy4ukYhAKQGCSVDFp21zv1EaKaQYQmA1kgESYgpkUyGBfMDeaQLTTRP/1hCRB1ttR1R0bgSuCkjqZ5n2K5JBnQFAZxf9I1AeTBw02b8AIGa//wx0HE2zNhGIk7f/1FcJAhs1Csl7//+JcI3EEy2ikAABq9Rvw08wBgHQcE0YgoAJgXAImAIESYFjsxmME2nDJXcChPxoBkwABBEAUMlLlqL/ZZhLpyNzXa8xAa0ACOzj94BoqkhggNHm8kGPhg7qS+xb//7kmTvh/cRX8kr3aNwAAANIAAAARUNfy6NeonAAAA0gAAABAw3+8K7cE2pOloZNWAKKjb0VaDSwBjFEiMDhVK5+ZcapI/mYNEoVjNsR5oT42QNaeBF0FLkPFCEouo6YF4WIKoxVnnZ+s4NcIcoZBOLV5sAE4IVv1rVZIZQGJzzqLKYEAgWtGr//qHeEzQhlQaKF7Ef//sIyBg8MQG0MgDLGNOzDQwEMeNPuiNIdNdNMJs6Q1BRhzYRUJMIAC8wIQGgEAiyazp0ZFQ0+cxcuX8M6R/y0hiABIr1XaOgMmC4LmYBoA8AUNzet/RJoaw4Q6EDK9wGApFjEwJsbwHLAgaEAMyXkUv+EQ4UttzqJkJCATNAkFMmLyTblQiIZyFlhipf6BTAobBYuaJt6ILDip/v0ggABQf0HCIYuL//qLYRDDeyiGmN//+dDNCOUMpAAAVrsEM/aIQAjlQCUQAmAQA0wMgAzE1BTOnMJQ5alUjDRA0BoBZgYBIwAbNlKnIfR94u8cpqXe37E+4hEARuWExCC5cIEg8ZhQgYag0mC7UZpsf/+5Jk6Qf2dF/Jq9yjcgAADSAAAAEV6X8vDXqJ2AAANIAAAARf/63cbGgXHlrmLgZjw1ubLqF0BUDTC49wwcG1nrLt/SCZEHq0OUUyYFbgaCKA1fFwEwMeU0KzhNpiAgCo0bJ9n92IsBhBQOnFo+3k2AElM2/vrSBAkAsOWpZQLwN5guIfb/9Q9BMkMCmKEBgQ0//+gIzBYcF7mFAAwzawnO+ghAOMBQAkwdAGCYA4CAZGEedqaXItxt/jRmFIAwYDIBgGCAjB8UijO7EOQ5QVcvyxypYeR5OPFwGBhTUsyb3V4GMrNorPWe8///+2OQ8woQoZaE3c3iyIx0fDBQDZdLbSKX9xQoOz9RZUYjHAARgLDjVRMmL6JbIkGDgAh5FkVfUsjgQKgwUir7AAgDR/79QSJE0jnDgcWJi//9RbCQIbLrEsHC3//4l4sQgU9UAABy1FXzd0EgWmBsAUYcQDpgegTGB+EcYPzOpmmFNHSARaYjIEgWAvRnDAzPMIlrLYpFYGnsd7rUsSXiIRIdJkZg8Su2DgGd0co0104HvkFuxn//uSZOkH9lZfyivdo3QAAA0gAAABFn1/Lo9yjcAAADSAAAAEn//q62JJ5yUhTLJTFjS06MzDhl7DPp+Byih2ttX+ZieQezfkeYE2I4AzeYBqILjIuMYUHqMycNRGYG3AEmaP9RmPgAWEBJAX0E+pYABkl0PfP6zgRTBwC9MuAmVHWl//USYSKCin1h3hANL//6gkBNA29jAOaXiqtESUBwEAEGBwA+YBYBBgOgTGFAQSa1QcBrIlzGD4BMBQAwEAC8tMxC1FLE7fjNnLLeqF8CAImRmIXIcocBhneXAYiPvUr4b////wlcGzrCzChdEgnLO7mEnwukUAjqy7FJv6yiFKb86iZEBAwq0FCpWWUjJtR4nRQoBRQnUv7mojYHFT7fOAhDP/v0ATBBpD51ARiKk3/+WwiALTyODxv//9QrIogtCKMAAgALumlp6LBkAB5gFgUGDaCaFACDA5AdMT44Q5mhsTkIdjMOUFUwXAEh4G1iDwBJDvFF4bpqWSXLHcK8QZmOBkY+K2DQGLwhQLTGWNRED6czsyqrlv//+ZPqtll//7kmToh/YwX8or3KN0AAANIAAAARWVfzEPco3QAAA0gAAABCE4xEK4DCU5Mqm4wl+Y7CQYbAmrqHaZFJvymSIVbH9ZRMyYEIwMd9AUXjmEUGXM2rMCJkuF+ANMHHAm3qRMiGgGwQLISeR9RRAidP/epLmAWqBho+yiimA4EGlGr//yFCZIdlhfgoOP///cWkFBgY1PGAAAAjvI26kXBgBwsB8PCPgYCUwBgRTAQRUMkwW0082TDB+AYUOJhlHv4dlE5GZitX3Z/PCnhgRhJ6toFR1gQFDj2vwycAV7D0ttc///9ZwQp1m5BmJcNHEjxqRNNAyOQIkuevd/50QgB15+YuakGAxh4FGRaMCNMUtZsTwfsAo7JJF/rUR4IFYcegv1mQCBCX9SuwjsKET7OxuEQxkv//LYSDLZQp40l///lwKARHydMAAQAMrzXmcv8QAQmBCAmYYoGhgcAXmCUDyYa61BuAlRmrZS+YF4JYqBIYAYB6o2yiQAb2RJ97cmlU3a7y3OP2WwPXI8wYPFgxICnhSgHLVGNs0nor+Gv/+8npX/+5Jk7gP2eV/KQ92jcAAADSAAAAEWEX8uj26NwAAANIAAAAQ01GUwC0zAgBgKrqsOAEyS3zAISStfqW2scv///8SQBFCv//1H7kfUUAKGLQQ3Tw5Y7/5xQeQiFAzIocaC/ugTYABMEU8qG6Hl0DJkyp96m0kQhLhRQbMmUD4FQQbw//+PYRKHmUGHFET//+mHUCggLWHEIAAAGVC4CibPEeRCA6IQOgoAqTA0GH+B0b84JxmAxIGDcA0YG4DcMrnhMVWHfyRSapLqn87jaiqjJ1kMmGwipwSg025ZQUZ10Rukzwz///dyDVHY0y4yAGCgpQLTXYYTnMrDcFGV/quS/84EggPBeZsfJEDLhwpBJMzH4sLrUiVRPIDFgeTZvpIkOAQeBEiNX+4Awwtt/bnQTMhpKs4cDIYgV//8rhIUzRaQ3j//+GSCNQ982ZUwAAAA1t3FztYMAEAEwMgFTCuAyAwE5gCAgGG+qOb1oxBhl3OkoDZgsgKEwmmBoEtBT5ZfLmWUj84WcdY1pS7QIBM2MNgFCiHAsYAhMFZWAgMJGwFM//uSZO0D9nJfykPcpHAAAA0gAAABFsGBLI9yjcAAADSAAAAE1t653/wzhhsDrEgAGEZfAIJH/wqQGMAQDUKMIQFWtFbSKTfkcBQMBRTvrOmZGBrwQo8MXkANCTdtAexmggBAAgTHMWr6jo/BCUhajql+XQUF4xH/nmqMQgFozql0yYBqFyGq//x7CQSRpkUBgGb//6wmACNEQWQBjqQvdJmlhiA/wEzogzMowMj6zFyG2MiJo4wFwSDACATL+KruRZmrtNcynKmG9Y1oJGQBjCHCtMAcA5QEGACmE2IWGAerWjNNjl/1lIXxBRNoGfmgWOkWRUmQgG7egFKhmS8ik38sBAGBaN5i54i4ChkHIyQMCPOq1qSJ8KNy2z/plwCIwFBhu3zgEgJv/t4NBYh6GZsHsipt//nwmAN6xuCw///xKhUxZrowAAAAq5NxYUzECgZGBIBMYSAKpgVgTGC2C4YqCM51lCOGxPguYIAKJgGgImAsAMJAOwMPAFK5f5sD3u9T6nqbdySqdDg3MDZAGElAECQEe8LgYtx4EtChM9ez3v/7kmTph/ZbX8pD3atwAAANIAAAARVpfzENeonQAAA0gAAABL9bqNzQLlhfcy8iQwzt5am2kBUEmZnCPKTC3zv/////BRKLBZZc/epLWjq2gYoi0VDfitm//9hDLSAIjgWidbev/+42odMChsWNMivd/8fQHWRIP7Vo9MEug+5omosnQsQBYxq//8eglo3nQzwd6X//2DHgWuFmkPwj7wN3QxMAkBowOwOyoAcBgUzD0I+N3QHs2AHIDCvAiBwLIJArA3BeFcMYf69aqUu/1upExwKGqHiYEFCl5aQ3zHgUYEz4pP2M8P///tLBLvIzGCEsXajNbk2qkYiWwyCVrRW0ik36QSLBTG3M0DccAGVQAo8ImXx0FhdZwzWOQDrJLO3qWcI0CrsLqS8v6wBBaf9fpiEIMGnti+DQQXkf/8rBMQlWL4Oe///5eBYUG8tVQAAHbEvgR+wsYCzEG35mAmZNBmB0z4aPRXpxjulmGACiDQJgEA2k8vZeSxX+l9PMzcsq3t1JW0gwAQFTF7DmMCEAMmAJKgE5guEhgkAlbEFzF3X/+5Jk7Qf2ml9Jw9yc8AAADSAAAAEWXX8sr3KN0AAANIAAAASbtqOi6DXEyI1APbAtxGETpQIGGJAP6OA5oYWSRYxSR/mYQsgVJFp3nTpSE8gY36AcdJ5EgRkjsQouIIRQGJGjiRS+swIGBgH4Fk5cTQ6zgBpgqfatPZMCAAKOzWsoHwIiA3h//8hQkSGmzE8Dh5///6hIwcPC09AUAAAEZYu8wWNCAB8FAVmECAoYDACpgLAjmD+fUaQIq5s4HFBAhYoAAjgo+1Z/W81D1nKOVcOczsRtlBygUmGAGiMFQYaSqwOGzSYapcsf///8KebirRTAB9SLoMc4gjuYMUoQLIdtYv/wicClM91plwWeBiHIIlZFC4Q8zQqWXEBZ4DD4hWf9j4gwKJjz/KYQjU/9+oGgYFgyOcOCE4mL//1lsIQxs0WsQ4///9Ql4pYYw1VAAAaqxx61GiwAwMgamA6C4YCADpgmAXmK2KkdC4U50+kEmIYAqEBBGOgMiGJAlJGI0kM5yyRSvnO8nn5LRHwziYhGQYATAgDPCu8eZosAm1i0//uSZOiD9lhfyit+onAAAA0gAAABFnF/Lo9yjcAAADSAAAAE7f5//+6zwpSteLzGUjwDjE4suxvK3GXlQYiCqVz+y41SR/OBA+B4M10iibEyJ6AzmQBiUSJwY0opaRLDhBAFAzwoiKSPrSMR1ALQgRHi6l6ygAQeJ77Z/WZAgVA4Mi7OQwEyZAUv/8egmUGK0LxGWT///CIEgwY1KhAGG4YZ3DAjSgJCegsJBgIqMIc101bxSjawGxFg/kj0Uk5bE3FYTlO5Zd3rHKlhoLAEmGsFECAG5Ij2YeQWIKBvYpI7FvDP6ZDBdFsRgBqbwEkBPsYEDDkAN7iAlOMVf+oIEQLOm51RmLQBhYwEiBFy+TBg+gbnxPACjEln/UssAmqEaJofTABCo/79QTLFxPMzAL8iZt//WVgiEHpooURo3//4ioogj5kwAAAAq34S1N7AqBgPA0GHQACYHoCxgThOGBY1aY6RVRzZqPGG8BYYHIDZhQA0EiIAnYc9zZVlRU1DhZyqxJwRUJjJ1VzAIFE4hCEBl/EBgIDCg8MSupnhh//3GP/7kmToB/ZZX8or3KNwAAANIAAAARUVfy8NeonQAAA0gAAABGmfMtEQBmFphgYIXeltuIFQBzBc/QoBSlr9S02Rf9MEM4Kaj2xmsvCOQM/HAtZJczGeKSOiVh3AhCAa0GMkapN7Jk4ACOBSQSZon2TAyAYe/8/rg1TAoUN8snQvgDgaL//rJIIkhMmcckKDD3//4fiChALsKrigAAAjnXJUOeERgzFEDqLzKkDcxjC8LDNhAN42HlNTCXADBwBpMAkEACrekbhUNPDdikvZZY3KFshVAVMEcOoWAOZqCAFzBVF3MBIAN0pTWx1/rUPsS04O8DaFQc7IQ2WXBpgcoUAFBGaLqSP+dCBcDC7daZgL8AiiFi5FDQn020yoToamAEaL6H9ImQFyoLGTZvmIFh5Uf+/RCEECxB9i+DQIRJf/9ZbCQIbbLGcDgW///KIZkT+6MAAAAM9PWvhmYMA2MBECYwQQSRkAwHA3mI8UEdAwKJt1yxGCUBggDVrLdrIR/ce9MS6nrSmBccK8QaWKB451KTCwjQuMFho7FWgU2kkXKh3/+5Jk7QP2jWBKQ92jcAAADSAAAAEXAX8ujXqJwAAANIAAAASms93//u3FJxxh0BDrORAiOV5lYoBjGrmCDO807aZ/qQMQSqA6m25ibGouIDVGAW1DwUBelFLOHhwh8IAXgcJsi503dSzg1QlTEIzJaupgLLSuz/Uroidgc9J+mYEXAqIDmO3Uh/RJcISQkxodDDC5UP//uJ4ChANkL4oAAAI/jvssh9eIOAiAwd4QBCCANTBQOyMuoZEzSGKTA9A3MAQAIiBAsCSFT7oP3nXyzpMf7hTxhAWfeuGAhjmIoHypQc0NClt/nec3/3c4KaJEXJMpISgti1mbtt1MrawKANNl2KTfl+ECQHEm51R0XgIZAfAZpmjPoFcd4d4GwacXnVdAvgLDQoTNH+4Nijyf/0RIwoJVqUKTFRSb1/5kGfDvZYpg0///4lgooxqVJAAQANctUUPJIBACZgngCGAMAKYBAEJgqlRGViGSYw6kwCAQMBEAt1naV2xCQyK1bop/Df7t0lpoA+6KUq4CoKbRohwmwSH9w/Wqzm85XL9U8llj//uSZOcD9lFfykPco3AAAA0gAAABFfF/MI9ujcAAADSAAAAExmFIaiMYlklhprZlBSHEtqk3T9r36/K9ukfcqDitf5miCCCZcBRgZR9MjEKBwnEDQiwM0trMmND1OtMMIBmkXQoLWbhgErGNrfTZg3YgUya5oGPlVJvd/8O8QuXhM31fT9+sXROjJLAC/LRTBvDTBpi5jq3v8xzHMLkv/X+z7f///7l5oCC3JmQTrQaNmTOh6cAAAMwS7CwMM3I41czDLhqMzGpAYxiCQYAAQhDqo0MNa0qicxaGzFhTHhUE5oBQOEIKMsgt82Vw/3POVxuLtiNCDlk/XIYS7pJOSCnpKK/d7+WF2vnQF9HPtWMLF4dHWe38+yDVHC4EQMGX6101rA+kFkFUFNWxPH49SSrdTKQD4U73rpifW/ZVmWNJ7rWSL//9yIU3Ws2///UcPmv/w70ZyX53V3J/QkQuu6JoiEEEZ/nEchKE/tlzRwoCFKSAfggCCvoAAAAAALhUgZs8Y8UJAl8mAIggCYQKYgyZ9scuodWUbUgODQUZnHSSGf/7kmTpA+XdX01D25P2KCP00QQHLpPFfUXOaa3AliIewAEPyAkqAqCrta7DtnlarS2dQEzqR8jymLNXCdaVT28ef3f2SzSERCpqk4kLKpLHP/EgMLe6B44dKnobKVvq+VA8bXlLf/mxEOl5Tf//MLGMn//R+JB5sf/qL0OIN8hBpjN/Rp56mEgwXYPocKHK7fo36GZxAdF0b/a1VRmdgMIHCRonOhwjOtjEpO8UAWkUU52IoeA5YbDMMpU5grBA0eaytWYkR4BjSpDNRE3BtkiANABGkQawUAx/mN0TgrN+yxLQWjkjkqrzyRJLKdnNyuyW0BQsVYFQlDuJXFlD1A06JcKySg0//WZrlqx908b9f/KYwYCFGKY3nE1Vv6FKAlKVmUSrEDGFOGFOq+jqVu3KFIaJ2/2/UKIYyhAtmBtLlbVxIVAqGFAH1gK2h6DhoECoqCIGBCplYBwQxiURm5hm2wHBAwSBiKXMIdJ3ps8ycRLvxR6yNkqQpgiUNIUTS0jpKZg+RE2S+reqGFKRMYXCjZKqBqA1qVY4aAOHGAqYKgr/+5Jk1Abz8F9R40kuEi+LqIAAovRNHLEoDKTQgNWyoYABD9mCQ4qoeFFYIpQbSpNoUYGp3CR46F3nyLp1EufDVUrJZI7///tqeyMCJ/5GhqCvQ+bjPjlyACN/127Y1lnImNZo2m8Z5Gd0EA46NDcRrSD0dFOHRid23pTV7tQF+ixGOeOYVp5bKsYCi1I7zrhUJX5d0QmHPcdJSRTOoaaMAkRD8w4jM3gYRToVGrjTKiARi1BHmLPchb9Q0UKnn9t4kpcJO2qrHbZYT3nNrSQ813+O6m27Z6iZ3fS++kX32nr3jKb2yDlN7y8bvW+mxboIT/tLLz/f8xtJMUWd1DLLcUkSX2/69LKbtz6WTB+l3MRjcKcO977Ev09rn8MjJuaL/w8zcNTG/oF3kTj5Seg2UsWGRZ/ZjDl3ysin0rI5/i0UpYj7lt21wKlK0kUiskixE8WFpJzNWz2SHqBbhY0Inmnn8MCEU418tLnJ785m+LoHdYYxy1FpgH399YC1r1ttHafRVknsfNRv+/bAV83mGfT+ufE/zezU42s2bcLgRoZZ//uSZO0M8+kvRJNJHEBAq3hACCKuTxWFBAyMz8khLuEAAI3J5/F/NTpbZpfr0izYUbqx2kcN4lM2ZZCL3pebZNCRF2OHnz0Z2PiEPrmWh0w1skszQUsM3lLuIC01WCc/4b36RQFqSE38PqkWYOAmVGBMyqmdfVG/Gdm1eohdcooopJISgcrCLuSOjM9nllYya7ta4Yg5lsc2Tqb9R17cvhx4UxbuT6CBecG5PWUUUB0duu+00gyMzWpRiEJGo6nzOegmTLOgqkqtqVS0SZz5vr9qwabr2G0gXzwvcQiGNL3eaHavTt+hcH3rohL9GtOSOqbpvw2IbxKpixyrW3u8easysa1oY1h7wnFn3czYkb+qGbha6q3T2PBK6Eap00Ns15oEavHdDDCBqFVnpRcQIeM83XcXUk/71YrzoyPBCja9iTAzfkUk5bEXTwu7xNkN5597HWc4vXm1JT5sqLW5CRacNEwQNg8/SI4WpsLJRgtUbW75kygmN191Eg6zmHBpqdyGyDpUrCo5EQWOZBSJVdjDKamUCCNXO0mWLKIKUMUDiv/7kmTsgPKFHETQIzUSViyYIAAjDE8hjwABhMIBZSpgQAAMARqR2ma8xCuzZCFtt2xdsEJUYh1vwm7KDGJGupcq/3KkqqZVrc533fPVpyMSNr5eu5FaoqDyfePG6Vdb9h56tmbbe3hWMowChw/NUZZg9tjn+kPm5MRn1m4pmZMy6DnDwYnzEo8qsdB/NUBEZdZJJ3RL2N5WayDMjk5hzT6hkcnqqga5NUnKjUkStyZZ7sgoCdJUTch43GNHgIoLdga6qoJ7YaIaMy8PpPX1D7b4CrN25RReNJPiJHN3u8oqzJQtjTdr6xzHRnMKvq/om2uRU5ctWamSkQBIHz15ZSYsWe0hxHH9qxK8Myx67Ilr9Wv7yvPy5amlss82DNgxUU17/M/X/nu+hl6bV8+U6erf2W1JKihf+7Fv9VbHY5d2CdUIBAEinB5H8SEsAFHw46TBBjMoCLNCESQbQ0NA01rTLsbDP2Q2sxkbpmuG1kDNeM3MjP52qyKLRkEpZXURP340JWudK133Jo/dO+fU3x0a/owunN3JkvlpU2Tk2vDrxkT/+5Jk7w1zm2XBCMM3sFHr2CAEAwJOJY8EAwzciRuLoJQwjdmzLa8qqrfQ3HUQ5rG79xID6FETNpUZ4cJkqO5nk2TvPQ499NFkNDo7mUzc5Szr95jGaPJvlL/w0h6KHF13thoZ1hdB5F5EhzPQjPmZERVUJC41fL7oovuOe5T1jVzXbJEGRc2PgUBchDCm4AgoUVD0hJxAwYm9VdbqzOd37vp2lCnHHtwUMChuoNyIod7V29LzEDKKO5CjJSwzr0kZlwx2OxHMMrEYrM/WHQmLnUAjtGMEZDknVU1KuOyhwrXg9aSSUvIgRoEHFhShnuuBPzAaiEpEKBma9jscoCLjGKxKKeTGzHnTGObmabJhrSbzyDuRaFLeqZ89r9RhKN2Mdt2/W65nS/UnI/JSyI0CunFlU8l8Gc0uCJW8rsjIQMLoekXxyB25iqWuVvXle/HLg1izuqzrY5m2UeIgjfqJbiZsVzBHUehgZkBykhmjFNe7sX5mXv55jJ+IFE8xKELuGqTE4fZt2C8vvmZDLCzk1bEq2731qds0YoiYR09v5Txp//uSZO8B841iQShhNYJVKjgQACMETN2NBKGYdgFEMeCAEQ/Bi4d6hxEJlRQ86Kxy/molLwCEAAAtEI3JIh6JmbvT6sqE80UF/VjwzhmTGrNWLU1HB6aaiYeRFGy7bD+lM15aWXR8oX5Sfp/TvaD27DMIXg83xsfsE+Ird6Wwx5LhGv833YU41F6UShUnYQ9FUEZs6ttzYjY55B+xOVWii58Es9VX2Z+ZL0WdYXtZnpRD0zJqtQ18n8OuNSZL8lhbHuKUyXLOSwZDMspqdyyjFElByaGZNCSsxOb2XPIh3b0UwQYuZpp/HdAAAhz+1zz6+wstLcj8jee0MzhVkInIhVkdnkY0DOTcC2QSdgosGPyIU2E4wLBGjMuDmNkCNoAD5Eko0IxTSbnpMrUpzI6ZnGWHm81sP8Tn2C3J66LIC0tVGhrqp2CGY4chGtdbSNJmEVXTFrPRIMUpuilJLHNZU4SRm79rbOeNJHfaN29iGjc08+9C0aOImUX/JAJtkLI0tBu+79WeTw/bibtOsjC9hsLSX7YrF45Tm2xfRnVC3qD00f/7kmTuhRN6Y8AAwzaQVOioGARDEMvtdQbBmHaJXqyg4DCP0apD3OERSTbRPTrUdLYecxfekJoxNyd0AIBNKwu7NEMzIxmP5TvdUfpGRnCyQnyBHlvRt/zt4c82kLmu+I2LKU1ch17g2+lON/Sybio7U77ZwCj5CTd2I0PqL9Q7yYkz/l7fKMR5YrKPgpH8roWIJAt8kY3XhYNzctaT7y0njKnTUyBhJEHByDrklszL04BNIezRmILbUs14KdoeVLglSPJvUoYxKaOGOF1zC5m9L2lNLou8zvUiIVMrlHH5PKFsecRC3PTOWz6nIKf5IJrHKzECahEQgd36dsnc08jMp5Pfl3kcef7MfGKibVUQY8jxTGBq7MxZ6GJxBbRGl7fCZolc+eRU3UPzLNt+FeZH3pNPtz/pvksLhw5FO2OeCYcsu4PVoAsAACZa7kpgauVklM4b0nHNc9VKXc1T/CkylAoLo6UoI0lS1Mk5+40wniv77MnfxRFCr9Sb7qazTaDbmc2PrRDeESpcrMzcRicLMdUvMXiLaih3ZuIk+dUZXYP/+5Jk74FTu2VAgGYzcFbMCDUEIwZMtZMJIZhzATowIOAwjyGJhMJqUQpZK2MGstCGIWrlUsBDOCSgAAdKH5y1Uixgfnc7I6lkXDJVpPFVjsDaMDrwVORo5k3x4CDEEEhEihA0cfMlyCzR1YxEqSLkimUIgc6iZfVp+ZZWJac2ppzNihE8Q86WYjUEyEg0Fpi3oWBQVQzhbprGYqvRGogz7uMnuG+9mT08oDnEGIigt0KM0N4LN0b8ERQhTjsY5DEhYA6Zg8JhkZRuFRiVN94YZS2INFanQ5NQpcSgzWIHEhAVJaYAdd0n0EjOJNVYyVSISMOKCTYzIhZw4AO94/eufJkDXyTL0hCPCm31lnzNiOGfTVb2UtjY9mpxIi+MexDnDjlNwEaosi0OefmRFWpgiszM0fyyKm9BaTdH+LizZSo/JX9jOAYAzoVJdiAUI1ZutGQXB5PbAdHoY4RDpRF3dVhyNhsMw6Oe4meHMQBwAgRyCGHSlCJizbYw7IIBBlhZUoe9fc8p+LhLm4dUWlcUqSo7pxZZFvtpU7vuKltTnmH2//uSZO0Fc4hlQLBmHXBTTIglDCPKzcGRACGYb0lGpmBgMI/LQILJH4Ts6kbKpizzHaI6bKbY7HxvrDTTEi6opfx4NIYdTGHkTCCwEAhykEDI4ybgdRO4TN0QxraJIiLYWk7Cy3OjlGN36u8nZ6SsjNZU0kh35wRp5y/6y/YtfSLFX0z4Gf2sQ87VYQsWuXLvC87WyK/eZKMrK8VZGlrot73TPOakzmXBlmgXfPrnPt6ai3eURzl3ReOVmPu7mYa2vS1KI+Hqn7mJloiDjVZ5Naab9pa/Ums7UK3IsqTsyGfW1bIH87JCWPWnDs/y4Yssv001NXOzbftm5jmP5VDwagaM0Co6LEgsAABWSKmHqS5y2RVBUiNLsdiHbFomZ12PoVpWWJOpWwigA1tMtt73N1NrcqsUuJEXCj9Gm2vhugoMAg62SK1CikVIQajCLJHop7R55GRrGlL4i0RI5EhMwFl84lYd2qAoIA7haNXzOmhyjIbGOojzXZUxbo0hS0LNOs7aQ1uXdGpno8jjH9jJ1ppmo7LXKH6huY7+1O8Ibz6HRv/7kmTqDSPkZUAIwjWATAaoNQRi0E4JjQQBhMgI3wAhYBCJeKNlyyPKIXMJ0hKbxjCS7SvTztRySyJCiSLqvtM7zc0yBGM2DWdoGgMBHnCkFsEcxWjvxDmpG87kWHEqxEPJhoks6QLRGweR36uaVfV1pcUc3m8tM5s5cYtcKTixPIDwfaZIm5DV/gdCiEGg5dIBVFkQNXhN4p3Q6KWxu9Apy5p5bSbWt1ISVoKwsyukBCWLuWQYXmJI0Uu0N9fMfqdj6pEtm0zBqR7bLlM6btTK3S9RbCWU7o58l9iG3nS7955ev+XutOa29eoRhubd7spsabr+Xx/6jrEri08aizIbmSBH4B8tHF4hp2ORH8+7A8nZ31nyYNxCHe7XXyHKXfOx8zN/C8Mi6T2Uu9VH1T3Psc4DPRiJCOllEMrTey03nxpMcvy/2Mj4r06aTTVYKGPpwwRBJgAiACDE1d5kis1Nja5GMbEGMsu6yFTy4XL5zDiCNBQ4VE8ERjizKFHFnwc5EuS9V/OEWSnKUIGWSTsEcmeqIhl1BNEubiN1Kw+g7Wf/+5Jk8IHz4GI/qMM2glNMGAAII5hOnXkDIyDYCUOxYEAAjGnF2gqdCgaI52GYd2xjNNnDrGyCqzEGKjpBR4IAABa94fS5g061ISOj3pelD1rltTJxI0K3OMmJgRyKajTtF55bEPeubfahZGYYgqssbKrWxpxAPmCFQXc+dMLqWVUmjxhyIOPeqPKFnJizk2UEkHFkLAaUL0IMJx+o5GSArkGKousPvLNTLJRaJck1oQBpImJmJmYhSZVDEGTJg6vApsooqZ1e4VAYUnqFR6vbqWc8/KLsEyLGWFVmbVXyttpXsLMqSijhZVurkHz5laM7J5TaTSInUubMfwRwbcT6/aNLlcLtFCNDHsIPEZsDM6ZhHIJbWALDGeAzMzBI8R9dG+SEUIxjNt0ryxELdMQp2ZGReN0/lbyrm0IqsnSxerKpGufe+ydtF0r7uxHSscr0rkBUPeSjCkUwFZcwTJurA8S8GnQ4zoqmmaeRzX25eSpArGRBYI7R6WpjCZMIIv/g+7wUaZ0mF94S6stgFiPJapaTWkGOM5rNJl7BTaIssQ7s//uQZOUJcytkwSgmGNBDIBhIACMAEWGS/gMZMck0seDgEYvIJdmrPvXaspoLPrDGZQMhlSZLcmsFGqVKImmlN5kPYZq0Zc6UzBrDJsksU3Pm7F4MyvmuVicMjh/+ULadpZ+U/i8ldlQzLJS4KvYUhVvpFDB2XKkxo++0NAf+tn4Zbj6ndeltBF2ycgqpIIrXU5UWpNKy6Ud7rNhZBiszUj15al45uNVSBVvZUKwVOiE08NlEkpVlVm6BFtBW+wUkUbL+nW1ZT47cD+bmrzuaUTqkba0BmRh7UUKxnXyibKSIVSaBjSijacECqzG+k0VEnlGytUUhOp2SjDZSVuSVtmXY8pIkcj0EC4MwwCZaY4zr9bux5WoVuVm5kqm8yx1lKr/kGWVC/L/SrxmhIWpKaF9u4Y8sl+lw7yDX7K/Rm4bIi7e3frJXXuQ/5Uk72pJ9573UtW2agprED8VT8wvHlFvVrhfMSPrLvLmEypSQdqXREekjlNLIgcGZiTL0RWChwxWBigyOVHwgMHTgUKeCF0W6UGDkJxzyo5JxoIAI2zxF//uSZOMFcyJiwYhmHhZNycgwBANST7mXAKMk2AFAMCCgEA2BEnQL0+WGpngnp7bRG1VDamnvL1PNttpjehLxLlGH5/0x6S6dp2LX0kFPJ/CYkOXlREMamhnY1UdkmopH9GKPY3+a+Zqy+hlbrYyd+yMj7VV61b/T/7OqpyDt2RjcVOJ/6PKjJVHUMeHYoQIGQVp3NAnL0mpaOroI8h+glyibZZrqkR6BALjBGJTxUwqRgMGMeEAaxQs/pHvRaGlGnSYW1hjlLPY1MoQTRogjbma7uRJS5TYyqyoSg++uyeIEORKvE5lazSq4zSLGDngJJo0btpBfURsvVrqQo0gEnYfveoDOF4VkGkN2rikxJI/EjTzVl4xZId/dCif/lNbkYQzcUjuwhCYZoT8hG7Mv4QlMLyL6a5GRxPTvYxqPa9akb//+YxVL39KMz66f9HQUdfg3zezDVSADSAGWjDOWhk5up5031omrySpTt9KrFoFaOMI1tDk0jVUYbmH0BWLCdRGyMkEZpBHphSTBzZYGTt3pjbruz5j7Ug2pF6ViGNJRE//7kmTiBfOFZMCAwzZSP2wYEAQCRlFNkwEjJNRI964fACCKOYe91b4VWO2N7trSjXQROxkfjnwUFaV3ZDxWwuXgM0MS00IAzTN3NkPtW/ciuO74ZuQ92evPLkM59CWr5CJW0jKHeJHAQEPYJBA78z1ggGGid4gcUODz7k/9JCIAQP5DUAx3Pgn/iQAhCI5Uoyaj00yVJFQPNbYbtAdJ1a2szt69XNGKKqokZSDaGMrVRrkHioiVyYgxCen6BPaFnroYix6aVnNVS2RR+LpzpbXA8hEtNganrmHPlO9N5EM62svtlw5FdGkTOaHY7/Z1jNR7nOTF7JqKcDNE8YVh52GTOvpWJafHSMQLLlE99PU4NzITP3ZDzxj4RUGfOtTuw4h/0ZaL//kf/DmPVzmOxpaGKjnSdFcQ+CIlHO1CeiM8js77aN5T7nktkuCfPid3JX2KQBVFWVtuLThlWcgSLRxM5GUqONIyTbgjDVERZiXPJ3j3coEcD2iPLLOT5BAcXaecxoujiIE/c5REtGVikbEoHWWC6+aol8J2gkW+lm3TZdj/+5Jk5IHz/GXBMMk2EDHCp5AEAkIQUZUCwyTPgRKrH8AAiEC8rhApOZnXZU6W5r/QmCyDd9QvVIBY0qsdIjGbWGGqLnGiHKUTGwgREHnyitxhag76cg+S6/epnE0cyxuZ25dhxCyiR95z9zK6L//OvC7fT8vl6+oc09PL3ZHO6LpV5nBF4Z/moQYlrn88RkrLR2pnSv4rqf/9/o/cCEsyDObODUqglNKw+lROJUMsLmDKk4NiY4YkbHCkZlVS8jGxUYlAWSiV3RARw2XIsqRNECb5JS7foeP+BlTOjBCg5/SjNIapSDKZjtckiCrAqZJo9ZyWnSNxOGJSPlk4wZBQoJmgWetJhy0rgYfrnbxR8NT44I4wQh9xwQtCg1oWMMdWULoPGCZ4C1Qm1HYKMtFGq9Q0LgYqcEhoVAyShsBbu9+JKmEmAq0j7tGU0FeIrnGkoNufprP7d8LsyCsknwJnlX1JHoomwkkjmx3rCbokn6wT8k4Vb2+xJ66QBXcxtXy1P7woDrvFN3E+Zk4wg8JJZbE80u0zzDDfEfCKIeOdkE6h//uSZOcJdBJkwAjDNgBGZ/gQACMWTH2PBKGEbAkHACDgEI1wyotcl2WaaaWjVlhI47FuaQTuFgSLET0xYMgGGRHpXQCuiM3EnQuh71qKCbZAVWPizjG2a6M6wrw8kyUn/WvSr6a02XKkt72IR0G35pkDNjbQcelkC8zzMvP/vCzPkfSw7vT1SvO7T4Ka3B4efPDVI2ye+Fs8Kt7P5gW96V7M0Qhts4MkmQUMxZ3m/3u2d10MY4Mghd/oFc+iytgsz7uWz+ycF2yCLuqHKzlvMP0c2i77GIE709cLkB1OznfdnGyCZfnVfIHl3t+mLWZrX6x+fDa8aUxc9h/Xsp4xhA/rdy3+XLp/EisYOLLfMzYmqK5pDbQ3Q5EPdChuZf/wk9KVN+hdxzmy4JLDBAkUat5zEkY93zsdbYfd+rrOd0ZLakpu6pe3BoxCc69sfHXpQCUKdJZhTrtRM0oqlxPrKQNh8p2FvRqAJKCBwcsA2tOITCVOZJZ2xyZrZhzw6rRdnQ2mOfIA0JfgQFGFwjE3NPcvBvRR5qT3DylaAmWeDHe28f/7kmTugfP8Y7+oyTaCTguIAAgjXg4tjwIjDNCJMKzggDCLydSrQo5K5KV+LoFhI7aKyDyf1IC+vuWSmvPXHJvXkkgySJq08mjsNKEaA1gxP12Gw0PUzqEy25XaJlE6UhMSz7ItRJ/kZEebaEbsUGP/LIzV2KD/BmL83uiNu31z/pL1yRtXo7tOe93x2luWuu/O4NL9vCOe6wQloMbtEvbs/2DZ+XbxBjQ+M7IrS+ZyCSac7QIzubQnoE9GMmhllPIkKZnOv0yI8nzkh8XP6TQvHWTinaqaKTF8WGctWqzm77lY2z/nZxWYzfxPczYO7OanSj092uXWuUnMbtv/ympIYG4+3rwbuxCleal302nwP9J1vZWU6iyuFiH3yU833Xdk+N7+8r+v+1cX3oL31V73FO/33t2767XOXw78I4te8zHwl0oApnjTtJvdHqPrta0Ezmm7ef4YmSc4DMHCgKyzhgUbK3MTYOc8joHlkxkMRBWRYWkxMt1cy874dO90V0cgbSgylD0ZlhrAsQpmWTzN+axzVwWSBK70kzEHKPVPPMT/+5Jk6Anz6GJAiMZN8ksmeDAAIwpMXYEIwwzbCROAIQARjXEuhEJrvFi+VrTYEeYOIZ6bvBKAAA/rcZc0bLycjxi9LVhdiq1CxmZk5OPI02UGjGUopC4gbW5GWIxm7RxqSo5FHbaLmsMmSvtM9BRG3Ci3OVIZvFfhHkT40OFdLfqIW0Ki3mEhpABJoLJ1OQoJeVVNM2Nx1FR9qQkDiGWU0SyEzmORNKc43VqRNiV9UtnjVU+bRdec3PCM05ikTDnEJ4rU9GpZgOes+I/i0Niz7+IWMnDhYZJ+qmPuijLOgs+82XOLQqluDSZzPkvBS9Kay82G9Hwv5rXu6UUiypwoal05FRWHKWOV2ZmmDHND+FVXhe34jHurkUkg7qOD7V4caknmyqRRF63/22uc1c4TEXUaHmpmRfnhlyWZ3MfOxs2cnLg7Ht5BjKHL6HwzapU3txciJTjKEoQJ1GBp8wQgiGpC8Qxo2tDfUcZ03K0qjIbqZ/mhKvTMWhIwtIqvTcGBmDxyJjS8Bj3WHiQatQwM0Dctsc2XCcvM+2U/+tpbMzPC//uSZO8AE49eQbDGHcJSrCg1DCO6DsGJAiGk1glgr6DUMI4BGZk3UG7uNmQXO1y8hfOpPuxXzN9sdjb1S1SlcrjswEAAAAQNe1pR/fhOqf7nZud/sFUWr65N/z98Ddo3fsoDv90klOTxPxaSpkv165wtt+rM6xdV+0obzV0/8q35Opa+m3apw838Jrtis+lBWm0QOChxcjR0KwTJxQSMr+TLM12114qK7fySixFlztJ6HJwc51pza24a3JSC1zb3wYtGRkBhVcstBZ+RpaSdxUT/WS2VqvkgintRjmRy08rK+y2XuUunLINb1UMUOSTVY3xnKJz1Fm8jleqW85VAhjiWq6+9WjsaeahAkpTBpAAORnVPEA68m+RpN4UP/U//ufCsv/6+wpmpR8/DGVY78PI/jFTi5kVslKr/y1Mz1u2Y5FeTPpBuvUb90sRP/YpvKLJbRPdsx7PXbvfUag7vrovLZbbbZqNzXlwA6AT014BVyDgQME7SuDkOp0ZGC4w6bMAswECURzM2Dgg68gKESIZiBR4XFgocKBAYNAri1isgIP/7kmTkj1NJY0EAYzTySCAISwQjblCFkwAUlIAJLaOgYoIwAyByRNdQQeEGhSkRKEvk7HfdhrDqDwddsHTz8FrLNjKbXvecdX8sl7z0igiUdmGLkbVmULw1745yumikCSu25EujKANvbUohPJttqnOz9jfeZ5WM2QRW3AKg9Nk4dqZ/9ybu6G33////+9+HrOoUuyKNnkGWVz/+vRavf////////////eSseOjrXa1NK7cvwz/6eA4hl//u7EbHqYCAICgABAQQIQIAEcX1aNnVb1jSX53+3/1WL/+r//sYAAAAGG2mawKypAUW/MJQADAeMFQ6MT3eO7E3OVOiMeSYMYQuMDwKLftdDIog0eCsmZOXS4Wi6RUzD9gMKOA89UTgREGoID96QM4HFKFwdQ2khySNMS87E4Zm5qMqBgioODMqK2FDA5kAEWG2Q5aSFJ0XQRJkJBQ8xZJ04ZMbkVGVAWHhvRFjxRK5iXEnMiZH2GaJJJVd5eMiaCYglmW+eRMQ5AyTsuzWzFhGY3l1JLIcNlJaTv/sdoDFSSI4vstv/+b/+5Jk4wAHH2Tc7mtIhh9gB/zAiAAY9X05HdoAGAAANIOAAASlkaQ8qTQAAEBNTL/s5n0PBIBcFBtGAkAeYBAKZgCm0GECMOZrqjZgjAZq0DyKmhtNVWFqM/R4VO1sc5qYiRIGmXUAWC3+Wud0jg4zVC98ZpHVp57OW46npmlhTPjBlhHKxTTcYUfADqNCF6Szq2S84kYg16Dkk0yNUxI4DB4FJEsohpMons8aiMQCkE6k1q3SSJQCpgWIXzyaaJtOhZ9Tt+1aSwhOQVSqmE9je//zshwXXSRI4TNZ7//UuKeNoWNUxgAAaxpmkxIQHTGiTsojLFzPOTCpLuNg8M81SFzhYMcmAwHgCEUExHEcCJSiLSyds75LqswskgASMFYN8wBADF7jgCRhWifAoBiC4pMy3LNKXrSMEQKZOADcgc8J8nSNIgLmA4GwDHBRxEFNkUv7hAxBxU6avoFkcgAGcBIQRc3Jg47UCfLYngApSTj/opGIBocHJS9fRsAoIOf7VmRuEiYn/plwIQ5PpG3/51IfAUFWKYcEl//2qDuk0LIP//uSZLyD9eNfzKPbm3IAAA0gAAABF7F/Lw16icgAADSAAAAENiAAAADXwAqmzwRgDGAAA2YEwHgiAJBwOBh9jjm9uDobs6fphcARmA+BKlwTAZnanml0szLtajWWt1Kd4BGFTfrKHh2UAARBswvuzAQLdqI1qut/z/7yX135UVCyhLZxyVyh90JhkU5CRyq63/4SegwY+yR42GVAypkFoJJmY+jnWbE8HFAMSyJGqX1qGqELcOVOL+dAsbKr/21QgJgwGaVFM0DoRA7f/yymPgGC2UJeI2f//6gyUTAWk9OfnAjE34EIE4YB6BhPAMB8YAoMhgrpmmf2P4bzBcxhCgWFUBcZAY8AGEJovNTxykzl13H8M6R/wYBjqBrMGBNA4AhA3BSjG4IYi70ttY///+9QStl/l3GOiEGEZ+aarJEpTCLDEAAYLLrKSP9YQvQcUfWcRKAuwKYxAcmDQrps7JlQiIZ2BkQB1D9aBTAcrAsTLiaHrAsVSb9bdIGgEFj57OrDCAhyP/8spkcFCbKETHAv//6hQoXED4kV1TAAAADHJ//7kmS+j/XbYMtD3KN0AAANIAAAARdZfywPco3QAAA0gAAABOXWioXAyMCQAAwtAGzApAYMC8HAwhlWTUYH+OM8MEIFwQyWGWiub3Wf53o3hELmHO3qOEiwCPJiUwuLlcjQFCVOHK1Jp5ZFZv81//hnADRJEzwxiiBYYO/LJfDi1zMwcMbAVl0ZpkUv6INZoFhJ/qnhxASeA6WOwmBrllWcNSIh7IB2QaJsz+7FYEQAFoRLO3lADGhBvP+tfSE6AsyLWgXwgGGC//5ZcbgMIsoSELsb//7moMDBwIvG5AK2mEjICYMAmMCwEkwEwHDBLAyMSwbk43AsDkUNXMQ8BgSBFCCEt0u2y+s+8Xzmqav+WNqld4CB86ovAoIYEEIVOHW8DHtWCH6S3hn3//8Yk0ZxS8pitLhAlcqZjjpiIBGJ2YJFeBrPWf/CCaFyDbzAsh5AKehGRTNy0i7OgSZBgaBAMMLJhavpGJHAQcAoWLqX3AwQ87/W+syBoKCiIq1lA3Cy4N4P//yy6YOR54GBG///FCAiEhcstkAAB2pDbAGtgAH/+5Jkwg/18F9Kw9yjcgAADSAAAAEXfX8qD3KNwAAANIAAAAQwwLwHDCvA9HgJTAdA/MRRUw54hnTpPeEEhjUNzBoEiYASEAXGgqXZRemh+5LN1pTEl4gUJjRVbx0AAcAQFEYwhpgwHBJbb4SW5dw539bqM/KoA0C/zG4VRYi2gSeilyIJjadZguDCA13pabIpfpgltDeVbOVCuGXANmkBUILGQ8UISi6jpkQIPmBGjE1NXbrUZj4ATWAYGEXQTfWSgAKAmPtWb6JkCBQCyI1UspHAHhQcFNm//JWgDnx8zEUBQSg///rCQIFhINwG/ZyRPI0MEAajwTwYTsYKAEJgQBjmAJFoYHJ5Z1hVkmF+EmYHQFxgPgIllQMAusKudrzJJS/M1LrEuqzT0p/CATR14DA8GiYFTBoMTWWlzGoGy4zOX+ltr//+8vyaWq6GQMIEgEIFN1gh92GAUCzJolTGICXepct6////+hISFvYdyxypYKTtBpagIGYlef6mvd5beQWEEBcCpwgZktXsbkQAxZQFPBJmia1LUSoSallD3z7s//uSZMQP9qNfyavdo3QAAA0gAAABG0GBJA92kcAAADSAAAAEiSgQRhBIuqY+RQIUYzKS//x/WR4LSkjoSCDGq//9R0JDBSIaOPTVMABAAKbFwmAtyAgABgSgSmE6CUYGAEZgsA1mIqlMcQYqpuDz+GFYBkHBBIwpxBwIW0+9LMP9Zgak3ncm4gvMKCg31UTBQrLtGBwYeMWQQ6kgW2is9e7v//V1sSTzsqAmXRyJG1tpbNQWSAQEP4wuB1YorTGqTfnQlbD31dllwVuBnooEqY4CYGfKaFZwzKIskFQIwD7P1ImQ6QAWYFmpPI/KQBh4ize2f5wEKgLWF5TNAKAw3tv/5KsQ8KL3WIkCwNL//6wmAEPC5ol8rr0MLXwDQJTAKApMCQFACAKhwRpiVjgnRuAeaE1f5gRgeqAqoJbIQLBMjdCG5yrKrHcM6SG2GGAwmeHdwVFGjBQWO10YBLRSbyT9jPDX/+eD7tHgVF8xgtQEM38ldJD66TPZVMbhJXMPUqSL/rBpZDakNSJwmRCIDJdgGlxdSICYpM7EuO4GogDBj//7kmSrj/ZcX8pD3KNwAAANIAAAARhxfygPco3AAAA0gAAABCaRV6lnBdggpiA5gtXkqBiS5EfvU/QCEwCiBPLJZBugFxkX//JViNBhd2J4GBz///1hkwUJgoBSJAAAAMNuwpuoAlWAgNTCeAMBwIQFBOMHNLM0YyIjG9jAMCgFQZAvQ4MGWGhxt6OtQWp69O85bnIHSBOqC0FA1YUQh0zhoTDYJdCbqb1n///5RForvJpGLDoGCp/ZqbgAZAZjJNjRNk1/j/6whghd7dM0L4ygGNjANKCDl8hhg+suMI7BFOJNn/QJsAguCicqJt1qAwwBL+p+wWqCh1NnYzCQgiy//5ZYzBgmoX4b0///5NA4WGF0iAL3w6206g8CgODCEARMBUA4wHQTDBcQtM3IUoxKX4TAGAhMBUA8QABLZS9x5BAeFLllYxs5ctRVBMcbK6CNUwXCBmy0GDwM1mJUuWP///rcENUzdgxeOhoYQu92qvIxIkBAA2vS20il/hFiDAbd0TIc0DCswRISsshxk25aIiGDQAiBdS/ol4AwQCx41f7/+5Jkowf1ul/LQ9yjdAAADSAAAAEWPX8vD3KN0AAANIAAAATASHks/6vRFzhQofaYOHRCYP//OqOgwHUJWQZf//4+wu4XAyoVgAAEY6dFjCiq1BQA4wJAJzANAMMCkCAwrhbzXeD4MwhmgwZQRjAMAHAws2Vnbj08p3cnfvZfjlVfYYBTtpgRBTOQIAno1IObV3QLax7////y1NQ6vkGt6xZq7UlbODPRYMPn5rYq/4RSg4O3rMB1gEPwLAycQJtNtRubjGASUnn/UssA0RC5lq+4LBT/+3RDOwoFfOKFfFFf/+dUWQoDqG6J8b//6hTxAwuxQAO6fdWyGyoAgYAIARgkgLlAAJgDgSmEkUYarQo5nmromCYCCMgEIcUkFh4szmMVZXPbx3jq7QPSQhxqeCFQ2kSvPabRp3g7t7vO///+pK0WmfoFLBMTQm1dmFlgCPDhh+bWL/50JJQoXbrokWAxRQFkRaMCNO9ZsWxPQByMdyP9ZQAiWBYAbofMAFAR7/brCEaH1S3QCYE1//zqA+QoCzURZv//qErKwrYYAAAE//uSZK0H9VxfTCPbo3AAAA0gAAABFVF9MI9ujcAAADSAAAAEfx528py+o8DRMWYcBoUCkKXwYyISfce0UEuXxRLazMPa9Eb3R3r1zn71XjhKCmUyi+H+JAI2HcBRJDdJnhv/uYHCsNwAWUHKGaCbDnAaJgAcJHEXUkf9YSMg4O3WgdHwBVkJ0M0zRn1mhqLWA0CN2/uiKXBgI+31hgF/9usIhVq1sJ5Htv/62Mw8WRgqP//8XZUGixwAHcXaXLKklACCf6RkCmtaYOZIRnMhymi2VyYKwApgNgECQAqQcYgyCYfrUlLO29d/PCVoIDB+B1YEqUkADMBUPlHmJVct6/6ykPonRZoGXVgWEk8YnCbE2AZuIDky//pg0KgwO3WzlQBoWFChumWDnUiajGgSKGr/1FEEJEPqr9QYGPf7dYQAxY21rHIGE3/86ojQ8dY1iIof//jVFRGLOAAABGWMEL7oCw1JUGMWSPBMGsHc0IwEjPQFaBQLSRKQ0Mw1EZFftTFPnY3/8zsLDmE2BYX3cJBEYNwRwkAk/Muxy5/1GZKsQ//7kmTBB/TBX80ju6NQAAANIAAAARQZfTSM+onAAAA0gAAABMDGKQWBmjzgvQMDVD8CCmyL/6waCwWD/WojwgUjdUx9/Nz43A1aaf6imDQaJzQ/WGDV//rDqiB/TD+GX/+uWRA9Y3CT///mImA5jIA1Xfxc60AKBYYHQD5hyAaFAKZgHBBGHS1Gbk5Sx3khBGKUDMYFYHJhgCBguAZdxwh4A2fQPD12DsLOuWpC65dk4YEQwoDxMsSBA29DwFHiUAU1GFUV/DD//mT+sxYMFwAMLDgMEwEcGPRN2FNwMmpisBrEozTIpL/RBrTB4st7lFMqDbA2AcFPY4CYFDkqpajpkTwZeAVRi3Grt7niDgBBQWzFQ3QUtSyaAgkIp9q0ekDQCC1NnWUCLgREBxi//5Kngx8FnTsJuBgk///9MO4DjIe2ysb9meloFAjMCwAgwvgHTAtAcMDsHIwgFlTOsIEOMg7MOHHMAgAFOkWAqKcadmS3YIh6lq1N5VZUvkCgY7CwTEYTXCFQWcAxIke1cQ/SZ4Z9//1dehNqUtRMmgYoLLn/+5Jk44P0n1/Nox6icAAADSAAAAEakX8mr3aN0AAANIAAAATUtBAY4CDDLYBxTdadtM/+EW4O1JaiycKIf4AjcAUCLLk6i+mSA7QiFANDE2pf1Ik0AswBRcapfH8Akma/etfSDZAoqZ5wwDI4aS//8snhEQYNaOsKB3//+sOoDgIauNyAOZQC3aIlgCIGAGGBsBWYBoCBgXgSGGcP2bWwgRr2ovGCgBk3AiBThvs5Dt083LZfU+ktbuVawiCJqZmDQNSuGQsAcEYOADWZqrrev///lPXiqjoIQ6p5RXwvtZMenEwSBGWy6ykj/TCZ8Fo/maBuTgGNOAs4ImXyMMF1qOokQB0gkXb6lkoDVcK0M1fQACCH/9+ZA0DA4U25QCEGXVf/zrC7CgdlCsi3P//9YdwcIkp+NAAAAN1IDWgsGQAFmAWA4YNoG5ZAwIwGzDmN2OBobE3VngzDHArHgWDEoJGgSXTftLaN8jUp3uh/V2gaqVBEYbmJgMQFyTAQRNz58xYE0fndjVLl///7uPSqi7yXxkYsDRScWVTb6F7zLiBA//uSZO4H9e5fyoPco3AAAA0gAAABFkF/Lw9yjdAAADSAAAAEyJl29f9YIFIKbus6iUhNoGD3gSQl5EgRebYlxxA1DAEiyaRV+mQAAUsCjwroJ9RDABjZa/31mQTQBmkcpmgFAYc9v/5ZNBIwofnBERwL//+sLwE7hcsrMQB9h52SPmYAACRMDWUDBGBIAKYAgOZgDLbGRQPCa18hhghARCQBQNBRflpiPDosspYfpN2eYbqSt0BGKTY8YBI1T2MEgA6kaDJICJgC80htXu///rN9GqSdMgxujgcQH7saj6LhgpwA0BqxQ7TIpN+cCSUFt/nUyYFbgZKWAxDHATA5ZTQqMy4cFbgW1EKef6KRqASXBRqVm+Q4KHCTb++uE0Rknlk6GXAzTf/yyaB1QoaZQ1Q0hv//w6wXXDlF1UAABrGNOy4Q4AyYD4DZhdgeGBwBKYKgQphzqwG9iTOZ9FbIBBfMAMEIwACXRgJEprkpZfQRSW3bt7DOkcsCBQ8A3zEgyTXAgIOo24FJBOt+JfYzw1//3F9mFMtQmmMVmBia5UpmI//7kmT1B/YdYErD3KNwAAANIAAAARfxfysPco3QAAA0gAAABGvw0COTGISVzD1Kkj/cIVYMmpVqLKRMikgM9kAYpERODklFLSJYcIJBwMgMGRSR9Szg+QK0RAUyX7lAApUWn/n+cBqiBEITZ0SbBoSFxI//yyaBk4UTXIADAjf//j6BY2GtNjQNbghn7RBAAOQgNgQDgQAFkwMBh3hGnACGEY1caBgdAUDoDY8OVeMRXowtyI0/1edr4c7y3IEfzq4uBQ3RJKodMoasCgFukfuXdb///dyC1G7jlmPBmPD+DrV2ABUAmLFePEiE2uP/nQhKg7u/KaBTEYAYmkA0YIuXyKGD1mBfNxNgBUkbDt+gQ8BZOCI+aJoe4GGClv+p+gCYgGCE2WYHwQgBRH//lk0ETBgfEsDmt//9RDwWBCCR9UAAB+csa2wAOAPMEIB0w2ALhoEchBqMOFlk3xR+DND0lMFACswAwCDBMFzAUCVRKdFxIFWg+kOSaZlmWNqddYFAScCEkYcA2CgWMAwqM6JkMHQSQCtahmmx1/efzsmlLLj/+5Jk8gf2SF/KK9yjdAAADSAAAAEXMX8tD3KNwAAANIAAAARkChAewwAkEzW6UZAIxeO4waBdDZ3ZcXUkf0QIJQVlPsUzUnhYQNjRAltIUpi1EcjokkMkBEUBsSJBjVJuzmpJgYQQC2Ylj7KWpY+AMSeS+1SuUA1IFKB9lkoUgv+Dgps3/5Kk4EwYObusLbCt0v//qDRwRDgJBSQcQAAAgbykMKlqwYYA4YPQBJgPgEGBGCUYJR5pkXDaGYgyYYIYFBa1OpCSxG27VrDOvXs5/+OUpFQo8WPMDFF0hQFPPjxZhXtFbVnv///rckaNKWsmVh48QxaluStwDPTASOqXLf/UEAEHSm61mA6wHQwurLiBfTbTNDwkYCh4rt+pZkBRAG/I/rBIKW//2D8wcN8wDOyI//51hTQuM6x9CTv//+JeNoT+ykAABjWgFmTSQSB4YDQFhg7AsmBGBUYKIMRioHXnYEJYbxdlJhKAWmAUAcBgIuV72sxKMw5flm4Yv5Y1oizIcEpsC/CpHWAQlntJuAmOPAxv5BP2M89f+dR92fvK//uSZO+D9s5gSavdo3AAAA0gAAABFRV/MI9ujcAAADSAAAAESAExw2QML38zrvAWAyCZiYeBClr9S02Rf9wajwfLQWtRGuVRZQGyMA8GNgmBWSNVmROjhAgBA3ggZE2RduozGcABrANIC+gm7VkoCBQgv2qNNJEGqcKKFLUUycBIiG1of/yVKoNQoLL7EPBg0tt//6ggChygN4CRcgABP1AbMIDRtMMw840dAFmYUxARrGBDmpcnAYNYAhgQABsNRJgaPuhbp5DP2sb+9buQaWADDA0C/MAAARj5KAYYNomRcB25RXw3r6RRGqQYP2Az1QCxIipksuEKBvGAAyUZoupI/8UKDqzajqjopgRjCOC+maM+gVysIgAUBMF/3NA1UFCh9vUdAXCo/7dYQjxPqs7GYFW3/86eEvC6+LWJM///4uxMR1tVMAAAAO2H7Xo2cGAfEQPQsQmYJQC5gNBXmBY7YZ+RpZ1utmmJ4ESPBngIQU4UrF1LCpRQl/6CTwie/cxE14CENTWNUhoUgcEJgUGpk/R5h4DoyADWYlVy3/P3hf/7kmTtA/akYEmr3KN0AAANIAAAARU1fzEM+onQAAA0gAAABHZ4gQl6gBjSPwcPjQ6WYaWFgIMZTyKCro73W/3FCgvPPbEeeK4oAHVwd8GTJsUwlF1HS8QYMhAKlxbjVJn0kTImQAZIFnJPI/J8DIGiDfbPNUdBo3GbUuiXwQGBmkUv/yVKgSCg5WygkDGeX//+JaDkoN+XljGoZjQiAjAQFZg7gMGA0ASYEwJ5hCncGnSK2bVxKhhBgVslGgy0hd7vvZapZH3OtrPmdI/6GBxY3mDgyxYBAo288gg1MFlVLa5////y1NPyskEoVImVY9uKomI0yVQIwWXWUkf5mQQHYm51ZwfwQ0xBEwQNkm3KhOhrwDQBmr9aiyDReJ3MF/LoBwcwf+3TBIaFx0MwPhaoVD//OnhEQcLqEtEkb//80C6wkrJAAAVptsisqshVAoLAJYBB+MBQDkweAJzG/BSB9Ux7oi2GKgBMYMoBwsJgkL7pPgvt2m+fO/F41a7fnJG0AaA45RA0wpExBkWBA4DIgHIwjGt2FUV/DD/1ugUbKgD/+5Bk7I/2d1/Jw92jcAAADSAAAAEVmX8uD3KNwAAANIAAAATu0n0EIINFUs2Ho+7AFAMyoEkxmBtXUZpkUv4+QaCAr/NNyNNycE7gbR+AqLFKEAEZkehWWDEgIYpAu4GCVmf3NBzwMItBTmRA3QUvJ4A6gNJn+tHlMCB8FLZadZKFIQDBxE2b/8lSWCQ0FnTuLNByA8///phbQFDoOJjvYQAAAk6zdxibuBcC0wGgAzCGAWJgKiQD4wfUGzXJFqN3Y4EaEyDgdQSAJasuELvjuLxax5R5WbUth4KAk5gkhgGs1HQSbOsJiMGsEjdJnhn///5xiIRZP4welkFJXrCJjAAMDsIMEbNpbaRf+sMWBT02ospGIkQBFgBQUXUiKmL7EmSQZ0ERJktX3RNgDDAKHiq/ygBIse/rX3HCFDx52SKAJhxkUv/501DRQYFxjAzLf//WGSCqD5D9EAAABHOvy30gFRYaMAOSmOhxj64YEiNZj2DqGwyjkYQAFhgNgEgQA4gABcBekbnYnQy+3dr45VaZ9RUBIwqwyYknUIwEgsL/+5Jk7QP2zGBJK92jdAAADSAAAAEXJX8sj3KNwAAANIAAAATwYAIBz4zV3W/+sjhTiCh6IGtpgWUjiLqnHNA4d8DHhhSpPGqSP+G4CmdudQMxyAMWuBEgJ8vkMMH1oKJMFIxCs/1LOA0WDlLV9IGzJv/v0g3AMEs8zQBICKP//nTUO+Fx3iVEF///h5ByxazZAFWtBLMl8hUAkwGAKDB4BVMCMDIwVQWDEuOzOV4PI4KowTELAzMDAAgFAcSGjRU42JLod6XWIlWnsKs1HWNFQQmJLIAQ4JA0wUJTlPLMtBdMJbsapcuf//nUdNROcWDMmJUOL8CZTbgCEBmZlOLJ2WZ4f84CQoGWTXlNEmg9kDL8QGppWOjlFJF2clh2ggBgYYYTqSP0DMigArQCzQn0E/KAGJKEQf2rfWZAkcBY0uosmIgoGaPP/+WS0EIcHGklhnwfc2//+sMHBmwy0iAAAADeTS1oQGFAHjALAUMD0DElAGMB0AUw1iXjeCBzNIF9gwNgFjAPAFS6LXuhSQ1ceTsxKZdY3qvHG7igcNJP0KBV//uSZOKD9Z5fy6N+onAAAA0gAAABGZ19KK9yjdAAADSAAAAE1kNjmAiGl8t2cnb/O///+UpeF3ktjCCMCAVGbWE2i8YUXwXA7BoraRS/nAmOBjduYpkwK+BjKIDB8ghcIGZtqNz4oQBSSSzt9ki6ASFBzUtt6joCxEv/760gkYFzL0SbBAGG0v/+dPBICDALIEcGnJf//j6CgYOVYQgAAEdvP2yRp6NoYB0ChUwECKYBgN5gcJ0GYQSSZmkMpgegsmAMBAwcvgX7ddOizdrWdVN6zqStwAaFTh68C4UoBgFG+5UBj4teDreGeHqOjUEUKI2QN+IB0gbRqcJsUoAW7A2YIWSXkUkf6QQFgprblFIuizgMo4BE2LRwdJilolsgwaMBjwZBkUvrURoFW4YJMl/LAQEDn238IDQgxGswJsEwQtj//zpVDOQoCZRAwzX//8mwoHDtvSAAAADLGHmcxpS0wGwBTB7AaMBgBMwJgTzCLPQNIcSEw8X4jAQAOBQGRg0ALHSRkr+wJRU8ZllXv8t2JGjgckIq6XlHQuY2vZgMDv/7kmThA/XkX8tD3KN0AAANIAAAARdFfyyPco1AAAA0gAAABPFQ3N6////5T14qtkGIVpcxjnEEtzDCfHhhFbXH/zMICQOp+dUZi0AYGkBIIRcvkUQfTNDwjMBR0Sbf1FMCCcFAZon86BEW3+/g1GBpqdZyPYiz//zpqGvC67KEvGl///FPDYhOB7V1oyqLPkqxgCMwEwSDAOAbMEwDMxHw9jkJDlMsGeswfASTBBAACCSJA4SCrL2JPVTSeWdr8xysy6EA4DHfy+BQej0YBDRsTdGOwwpq/0Zpsf///dx6VZXeUCMlFQeKTaz2OK5jJSkMJAtNaHaZFJvyyECYKevM0TYZkDPpwWqj2ZjWKSOkTpBQtyBogRFUkfuxWC0kKQyo7dcDADj7e1T9EEwgIlB/SMAQixPqX/86VQmDBwJlB1RkEf//qDDiTh/z2CrleUP+sIOgUmBMA2YZgGxECeAAbjDvXnOQkq41dsIjAjBAMB0EmFAkBssAGF8C/bLLFFA0Wl1jKlpoZYEFBSeamhgwbKamGAeezd4GfKSTNYtO3+b/+5Jk5I/1il/Lw9yjdAAADSAAAAEYXX8qD3KN2AAANIAAAAS3/4V3QUShQ4ADJLCARgd/koa2WcNCpoymAozW3r/////2OEIaUdv/3drxxN8CKss3DEsfu3e/dSLkkEwwGqCjMJoeikYjlAESAGoROpfKIGZJjy/6lbmg4wWmqqKZcAgVD7of/yySASJg42yQjEHDG//9agiFGQC0I1hoc7eo5MDQCB4EAOEdMBkAYwBQUjAWRhMWYWo0p2mzBiAXQyHgxSRQAyBp8CUsttUk/e3lVoHpKocb3whcPqIrn6YI1DpwT9i3zP///xlT1Q6qqYy3hwrD1m3KEnzBaktA02XWUm/rCaAHRn5i54lwJJAo2JAwH86rWbE8K8Ao7JJF/qWRgJrA9Q6r6YFhBb/26wtWCw186iQQRdv/508F4hp+YBlG///EtEaCfT1AAAUs1HXSVVHQEzAUA0MKQF8wQwMjBvB0MVJLM6OiWDowkCMRcEgwbAHwKBUAgJYbZM1OKtwbLD3KGpauzEBqKEAHpgjjLAYBAukQAXGHCTsYHQDS//uSZOkH9ntfyYPcpHIAAA0gAAABFbF/Lq9ujcAAADSAAAAEe8ATdSvhzv63UZ+gRoFTm0KYk1tQnrsYY+corGiCqdT+02OWP////CRQIpe/+9SWtJUpByoRCj9uQ2b/6zgQcITGgZcoONBf2NyAAYE0FMJJmia9I1AUfFR/1HmpEaCFaCx1JnMSbBAWDjkX//LJLBARBg91huALAUP//w6oUQA4MQBvUBtwfckAmBoBhgWgSsAMAkAcwuB0jbKC9NjE9cHBatlUirRFmvQTPSCfpJ6tR91nSQ2IAga0Yo4BExREFTLNzMFAVnUZpscv///+2Kr9KLCiEX1M5WIbRkMTpIaJc9e63+cCFQDnT87NyKAZEMCzAiZmPg4utSJqOaBKISLt+kTICSoKETZvuAoNT/250IS4uHoG4QgBoP//Omoa8NKdYrBPq///NAcAEFDVIAAAAPsNfXQ5YIAfMC0AYwuwDw4D0YBlMGxX4z6h/zkKLIMO0AkOB1SZQCO25bEJ95J6erX8u9sS93DAIHO1pYAi1EIwGFDnkkMlgBGl1v/7kmTph/a1X0mr26YwAAANIAAAARWlfy8Pco3QAAA0gAAABJba53//9XXqT+hldplMUkRpb6dt3EOJkVhmAwgpbD1Kki/6QSgBSsb61nSkHVAwPcBgKZMRZJtAkxxBMEA4SWFq+s4RoTiigTJfrMAMSKIh/tqMQSSh06WWDIXEGYf/+dLQQhwcHxTg0N///xLARARN7igAAAjLF3l2w0FhIxcJODHjIBUzJXMIU/o0BRhTcBEUMLICcBALAoDGnUjEHehqa1Xjdb8se2ZEqwaJoMAwBpw0rTEFBoKAaFvyCjvd59Amx9kiJWBkuYDAMilMigfGByFoBV0ixir/qBoqBQ8/RTLg5YGMTgiVkQLhDzqFS1JFcHRiXZ/0C+A4uChc0TbzMAwaYt/buDQSFAbaRgFqxYUv/50tBMCHBVOHBP//9YlQmAoI+t3bkEt2JQSQqBGYFYKRgJARmB8BqYn4zB01hZnM0leYToCJdEwIBQwXuOXlVTd6DYVG5Y/28cqWVOSCQkenXpisJkwVEItOBfEySB1SQ3KK+Gef/+8oBVT/+5Jk5oP2B1/Kw9yjdAAADSAAAAEWeX8ujfqJwAAANIAAAARa8XmMfJgHEppsilj7jgEGYMYhAasUVtIpN+cCNIKOn1GJeJkUkBjtwDD4nUhyS6luSwuEIBICxQppIq90SBAYQcC04kXbUtQD0Bb+1aPcCgEFGZ50DM0BIiKOh//OkgEyIMB1CRhmk///rCAARcLMn0MM3IYGtAZFDHCE6I8Ii8xhOMO1Oc4OyKDlrb0MQoIIBBHmAsBYhKMAYAZCZDzFXes0tBbv5brR1mQgAjMSwSgFAchwAQjAsMDQj4cAUTlfaU1t6vqMxaAyQ3E2Ac3cBbYLeaKK4jUD4+wNmUDbSDF1JFL84E6gLOn5mcJsQkAyuIBqILjJscgoJqWYF9YpABTyOw+z9FIxHUEFABoMXVeolQIoT6XvWvpCCgObM6imXROoXmef/86SASHhQMxwMlI5P//6wmCC5YOBkk0gAAAA52QN/IQaAaLAgAYSEwGwDDAXBaMAxHEwkhlDVCYhCAvjAMAIFg+4NiOL2kEao57O5+9Xbj4joSMVuUCh//uSZOsH9khfygPco3AAAA0gAAABGZ2BKK36idAAADSAAAAEZQULA02XEQURWXQ7LrOX////LUeflGUCodBWNWbcMJVmMj2PEG93n/hCwBQc3WsyIqBiWIKHSssjjJti2QYMmAwYE4j/TLgEUgKAE0PuAYGJL/fphACBwptZmFtBpI//1loM5Dz1C9Ekb//8awaUJwcwCzWdllTslgB4wCgGDCEA/MCsCgwRwZDDmPvN8AgQ1D48DBSBcMAUCMwyHEwU6puGoFiFPNWZfWv7qTbwDojNOxwQjVuQKAQesBI/EwJe6Q372e9f+7jZU/Yk04IUBWMWzUdiPofGLmgSglS6HaZFJv0AnKChY92L5MDHgYbaAwXIIXCBmaDqMycPCbwCqw70H+zlQLWwpBLbP1GoGHDmv++tQJGgWFI1mBuEIwaC//50qhESGVd0QoAb//82Cg8PzUoUgAAAc9ua+G7uEIwDDAbAhQ8AwF5hTCwGv4HCZPTRJgTgTiwCBgoCjSj+0OxTztLZuW/7+8JWX0PGizCA5iYwAHX+QcYLXllvDP/7kmTfB/WIX8vD3KN0AAANIAAAARhNfysPco3AAAA0gAAABPD///zpJiLMaALcmJX1hTuICoIFH0O1sVf5wIVAmqPRdEc4DFFgWPFQwI0x6jxVEhAOMGqX9RRBM6CgFL8pANAD/+/UERxWXWcSGaE0f/+s1DDirx8CBW///H2HaFzMhjjfbRl5gEAAGCOAUYeYDZgXABlUIMwum/DYGINMG/UAGgXGAqAUPAahgAaAdhg8AE5am3ZmBdxX+2Je7hgOCZwGRAOFcIBkUDExAqcRAqk8+Mkobmfef+qrdkOzXS6pjKR4QPrNpND7gCoEmESRmGgAL1i1nLnf///8ioNisX/+rtaPqKAEngMBD/y+HKS/zOpA5BgKCANsJIgmh6lmAvwjbAUHkwmgz3UDoZaf+ba4QsAUAJqWZFAEJMPqkj/+dHkISoUDpLCAAI9Q//+oIQYKBgGgpacZgAAEaxZcrllzsAoeeUUZYSZ52YLpmBlqi3mNauOYBwHaEpPFPSHYflkWnJixO19//eUamJhvAQGAUAGrEFQDDB2D4DAImuz/+5Jk5Af1R1/MI9ujcAAADSAAAAEa5YEmr3aR0AAANIAAAARqlyx/6BTG6eHWBlnoEh5OJ0RZwGojAFCRmi6kj/wmiJJvuToCgsGDiumShzrSNhjgJHySR/sZg3VCg80f6YWZK/+/hhg4B9bBkpE//9Z4OGMXG4NP//9QpqQo6AJdMuEwlRICAfmAeB2YJoNxgPAVmCwByYw5Wh6ZgPm0pvsYR4NhECyYHABidrWi1q76z+44QZTVscrMaZyDQWN61DMLxUBwAmCwAnAJsjyEiwFL9gaQ38Nf/8tP6slXQNAgw2QIwdAhyZFDjDwQBRkyag8Z0pqb1/////1BggNTv63clcGIuihhkgBvpLIPv3u4U7yC4QTIgacoOMwWqpaKRdGOAwUgBrcRE2bUs8BoTBFDdu1SS80CyYEWQtsolS6GNQoSPP/+dIQIToUHMgKSCic+3//WcCYsBgIFhg8pVRAAAADh74KVugicYCABpgrARF7zAQASMLkvc1zQxDUXZvMHYAMBANF1YwsptYdlMcmLN6U3csa0pgIcEzjNocGY//uSZOMD9RtfTKNeonAAAA0gAAABHBmBJK92kdAAADSAAAAEwIQk+zdASOvyR2LeGf//63BCnVV5TNQgoOXvnKeYVlMNoS8jTZdZSb+oJNhiN2PmhJgBIQWdkQMB9nepEuizQGnhIu31LI4JrhjDFXymAQHQb9XoCEYOKvopg3oMJH/+sqBMGKm6h9hwT///imhdYWtjAAA52WPfIBUBMWAwCBLTAhAKMBMF4wAkezCDHkNdpRQwcwQDAaABLtMhfR/2nw3lSXP+tvW6B8SqFDBznMCABT5CEjLNyKgAa3KK+G8P///lPm/K2Qsh1A6DHtI2cycCDEABcalyR/4NXAi30jopwCKAYqMXJ1F9iuTwcIBYCXF/0zQA0kFDBug/oAVFGv+3UEIUKCX0DcIQREF//1loIhRMnUJeLEv//8uhdgjpajAAAACrWd1lTsgkEAwIgGDCgBDMC8B4wRQbjEUTDOIgao5W1pTB4AGMAUCMrDQsyr1nT9VI4/MMRutVyuzETZgIw1NGU+MKwAHgdAATmYMSmFgHqZOzKqXLf//7rP/7kmTfg/WUX8uj26NwAAANIAAAARXdfy8Pco3AAAA0gAAABNhSdcpQIxeF4WH5oMjhxwxACBhecg8N7bTtpn/ohDYChFHuovh+gGjbAtQHGTYtBQTqOnCaGkC38YZ527opEVABLgpBJJn1qMQTQpffPakATTgiAqrKDiCwXkfb/86RAJkRAxukGtD6I///TD+A4aGguhvU29DYyAkKsGfmISDpCMNASA2zgNzcMG8MKkAswEgAlLh4AlGuB3cl2NjcUw1+GdJDYWACMRAIkwBAE2vFyjDwC6GgfmCw9LbXP+mQwbhWD+AZ/QAwUIugsyFdA2f0DBgBSpPGqSP84DRoFADdSzIWkDBzQJBTZEvGTblQiIYNBoAM1frUSoJrRAFJf0gIDH/26wkXKatRgF+xUUv/6yoEgIwnkNDTG///EQDmiBj9+9Tw4y8wAgXDBHAIMRMB0wPgAQoE6YYD7RwFF0noaYsYqgIZgxgDA4GAKBRIABdtpzSmh0krgmlr435yLs0BQTnK4YGGIlCQCmBgKHAKJGSwHEwLtQg+ct4Yb///+5Jk7Yf2dV/KQ92jcAAADSAAAAEWAX8urPqJ0AAANIAAAAQsXCTeXSFgJMSTrMNAFZdCYuzgCgWZQE2AjNf6rktX6ywBX0A1VN9MoE+QANnA2n0BUGLIIAJvI9CswJssifAG3IqBbZ/WYC1gYC2BaWRQ3QZ2SHyBlUZRS96zXUUwQOQRI1JoF8nAaIxZal//nR4CR8MrTFIBQ6aP//1LCIwTEA4IbigAAAjLj9NrPDACocBGYPIAxgMAAmAwB+YHp2Rl4jJmtwW+YPYEoUAYCwDQ4JBp9vxWnZPGae5a/nb0iLcm8ioIAG/JVBpnyUmCwC5ErqZ63//+9R9qtx2zEwjGhfFLdJK07AsjgUB36pckX/whTA4Yf6CRiOUBgmAIiRqomTF9i2Vg1IG/l5H+xsHuBQsef1pgKACt/t4ZyDAbZ1hjRNW//rNQz0b9YvBbW///EqFLivmyIAAAAMrsFNxepBABQFzAtAyMAYBEwNgFzDXHANqsHE2SVBjCQAUMAsAliIYG0KGAurCaKXT//exyxpn1EYQNkr1/UwgSFjG1//uSZO0D9vdfyQPdo3AAAA0gAAABFll/MI9yjcAAADSAAAAE8MMgxlMqq5b////7eqw8soUQyVUpy5beQyOMTDoCcWmxSR/wisBRR6lGYxgGDjASIEXL5MGD6y4wr4EnRXZ/qRI4CCILWjVL5dBEPPf1+4pEKF2zqwvQKkj//WVQmDGHWKwOP//+LUHnFbPyvKHTZQYAoJZgaAVmFkC0YB4BpgaAjGL+qqd84xBzEX7mHKB2EAgiIBEoNQDUSCF2WWxCIwdh3KrHnpSeEA9NMeAwOKDBALMMDk939zTQdL5MtfqW2uax1vVCxolAzWUApo0jhilXE8jvrkBoPMyRsiWj20d52/lME9QIyr6JSRJ4MugbW+BcaN8pihiORSRSHkWEEiYG0KC4S8ik2tRmKYA/cA0UJtBN2dAjgDpo22/WmpaJNALCALXiWrLhFwkkGYWr/9Y2QmjD7UQ/IFjZ9v//lgKNwFAppedsT7qCMAgaBNIhlTAvAOMBsIAVXdMW0o41CZCjB6BQMAUCMwcDkn2eLUpYhKHxp6Sdt7uV44zMgP/7kmTjB/WZX8vD3KN0AAANIAAAARsxfyQPco3AAAA0gAAABGBpKZiIOsGGgGdSGY81laYVRX+d3//nhDb1wKi+YiUYODb+V6lCjsZAYggBquodpkUm/MQk6B1E31lgzKAkYBncBQORQuEXTatAnyeC9AAVUiCbfZMigAIYFnhJoJ+WAAjR5/1vopBEsDjRqpZQPhl4NIf/+slgkPG3k2FAz///QFfBYOHvpCEAAJDHKGXafVURgHADGCwA2YCIBhgQgbGEMXuaVgaRkaNZmA+BSYAQAKlKGL1tagKKYwFjfqa/eFPDAqBndyyLkSFAY6P+CFhx6TPDPn///qZbDDzKjHlAWForfsRtchno0EIUZy3/4Q6B8D/Qc8VgNBAXMSBgSpirWbE8HtAMjNkX/SNQF4gs02b6YBAS3/v4SUJyXqQD2xbX//yqGekvUL8UZ///xLxRhSh5IAAQAMdPGzx6y+gNASCoF4NAEMC0Agw3AqDb8BCMHR8IwGwJCYCEIA6gC94lKnfjDowJD0R53mdiH0JByAsuIu0RBcCXsRgV0pn/+5Jk24P1/1/Kg9yjcAAADSAAAAEVnX8wj25twAAANIAAAAStvX///rOONUtuAYrIw8LIHpKeII7iJRhAYdWexdv8JoAUeH+pR0XgJ1g+Qpm5UZ9MqFoOuAMeJ9D9aiPBovGXOL9ZwBIw0/35wJFiAdM0CAKX1f/5aCYUkqhFSwv//6g8pCie2QBnYhthjWxQBYwLwFDDrAnBQNpIESYbTYBuzGEmcXlmCQYQoBQluXMSum0RXWlVNGYpWlmeU7Fm1AQLHBIwgEIy2xgaDxp9DhjGERelr0O02Pf//7jDzdmCiIBzBs6zAQAXajM9IWJGQRQGGQOpXO7LjVJH9AGkIHsDfYpMWxYAYzBUQMmTYphKLUsyJ0doWWgcYILabIv7oEXAwzEEVMnDdBtQ/hCpKqveo25QAqsByBGojzwWWgsHZ//1jsCZseqQbkFhi///qCQcMKBYkaogAAAAyxizqyIGA4OQzjQgxgHMYSTBVRIMs0WUzlHKg4HIqAAg4AqA2iMppYPpM53KW8yxypYaGABzD6CWAgDDYw4AExAwOwwI//uSZOQD9XZfy8Pco3QAAA0gAAABGf1/Jq92jdAAADSAAAAEFoUhnr3eetQ/iVk0O4HbAYfG8VycIGFuAN30B1JNv/UEJgFpnWcWcFZArXDLpxisk2gVyeDhAYICXF/uiXgIBgUPFV/WkA4Uh/vzgTABQZzqw4gSZv/8qBIKV88GUb//8XodgUU8hPVYaXyosMgGGAOCKYR4PRgfAjmEUD+Y3KEB5ejqnRngCYfQRZgigjGQgOBQUVghQdoUSltA3Clqy3GtMvEh6FR4c525hUUrZMDiE+R5zRYFQotxSX2M8//uFt/HgZMSgow/FDBwGdOOR96CoETJNNEYeL0uNLS8ik30ghiBWY25GG5OCA4G4hgNoxShABGY+0FqOlIZYPiAu7FGKqTdFIxF8BDcFpxMqX1DVAyqUdv3qVuiGJgdgPs5oVwiiHQir/9Y2AgTkLTDUAWIof//cckFFoOHFWowACAA/OMQG+hChMAJOYeS7MYeMLEo82SRNjW+UAMHMBoCgAgYAFusKbO4coqwO7d7H9buUL0EIDIqHQlCoMMgJP/7kmTjh/V3X8vDfqJ0AAANIAAAARrNfySvco3AAAA0gAAABGCWLwYCAADxw5d1vXqWRwlxBRAUDXywJJR3FU3JwWWCM6ANJHOLqSP+sIkgYqfnEjEWoAygBIUYuTKL7lQiIa0EIAxV/TKADzwKCDdB/cDBAF/1eYho4LEXaYJCehNH//yqEwZsyxTB2q//+sfAOAB8iP35A678A0BoIBJCBTDAfAAMAEFgwK0+THjHgN31EMwhgADApAGMEApFWINmaLG35pJJU5v8K8odMLBY1w8RCFi/oMDppvHmDgKsZ3aarl///7wgNqtEzMxkbxIfvxL5Q+6HAwytgwfv1O5M/9AJjAW4PzJAvjmAZN0BZYQcvjoME6zh1ElgYsJE+32cmQtmDDRbZ/RAUJks/9uUQakQcFfOHAwOIFS//y0ExJnWJcH3///WH8DpRSZ+MAAAAMazsrmayFwITAkAkMLYEkwOwLjBJCCMQZWU3VCLjpSI4MSkEIMABTZmmVtFbRqTjbo6Wlq87Yl7kAkFnjWgCR2iEYLCB4J8By6RpbaKz17/+5Jk34v1mV/Lw16icAAADSAAAAEXFX8sD3KNwAAANIAAAATu//+ZQyzFlwhABiZkGCQA5MapZchiZjV5hUMI4v1LTZFL8oBCUBGoPayURJoP1AyPEBpyRI6OUUkdh7GSCEQASVHORUvqRMhnQHzQGjpPI/NwUUltv55qRiECsLkpLUmXAkZLKv/8lggKkUdiaCg9///rCIAUqHJEmhu5QvRAZBkKpEOYFKPEow1ATCMDk3jR0CIUUwBAGEV0c0mJa1qKyLGV63a/nbMiSEMV4BMwHAImXoKGJGF0NA+JxwJP2M8FdR0agd4ojRA4YgGKhtlQnxzAv+B0NICmUwWr/nAQhAW8tywmXBSYGGngSTkELhAzNCo6XFDLgMVh7PP9aBDwIMwtbLiaHmIBxYtf7aoQGxY1LUUzwdCHbb//LQTEnqhrhvT///WGSCphqk2qMAAAAOYP+wxrYgAXMCMBQwpQJRoCwAgtmFom0bCBCZxXI3mFeCeYCACBEDhoEu3LWJVYAeatIsbOOWNM7JZI8CfzDoJQhKonNYc8HEtkETmK//uSZOiH9mVfykPco3AAAA0gAAABFlV/LKz6idAAADSAAAAE+Gfef/eS+u6o4AwsuS4cGTcxBZIBDBjaCoFWtFbSKTfmAW2BcY25QSLoywGaiAWhEscHSUUtIlhwgkDAxwggqSP3YmwsNB0MqO3lkDFCyJ/7eDQ2Cw9qjqYN0A3o1f/+SARGlp1CIixJ///h/gu8NDKzaxacr2XBYQCl5+wxlhZmpJgVnrGPaKKamaPRg9AKkwERgCAAq+gCG5DyNyK9c/DLHKrEhEAWYWgTACARUuC4CRgdCiIzNZlVW5j/1EaKaRYVsBqFQFlQ8nzxXHABuy4ATIcJeRS/zg6gpQbnFGYtABsACwAvplxB9A3NxjAGFI8P/RKQCxQFBRr+cASEMP/3DHQYDbYvhIEcX//loJATSoXoyH//8pBwQnwgAAAAyqsqTRbkSgbmASBCYO4KRgWAUmCgCmYmZyRzgjpm31JyYPoP5gDgZGHgMNC2KpzvzIsmn3one39Slkj6lgSGia2YPHBcUwQCTrNvMhAVCpzGcLTUDk///4ZyhjUDMf/7kmTnj/YZYErD3KNwAAANIAAAARU9fTANeonQAAA0gAAABIMerIFDx24xDbgBcHmOHOHIRvZ687fOEQJ8gQF2PYpImwyoGlUgWwj2UxfFhOmiRMaQFQgGpElg1S9ajovglSDlFsvyHggRm7e9a62TFmAw+zrUVwKhA3g0Q/Sb0yRCRUaJ5IXoKDD3//4x4ORhj5OYHIAa3ACabwQQIAATAaAMWHLQGC+KiZ4ITBk0oVGBMAIYD4Ab0OjKFhHHdemuSzD+X+3JuLCoCZG/EITBjbHDDpQPtQTrru5FNyy7lzPfZJSt1MDM0Ia1W/diRiSIjzD1LkXGTVZaSzQ3CiT1LMB/BAnGbMJu7U0zRh1hY8tD+5gF6g0hJ6arkwGDKf/WifEgDxcwUM+PKTfr+phFS1mAwWf//4+xkiHHkWmQAAAQAAAAMJAkMJgqMgiKMgB6Mag+MDxRHAZMAARMGQNMFASMGGHMGGiN2LzMXAACwMGeNEBAOCIruJAC8F2O4/kYqQ+1t32vq0CEwdSu7yykKzt8C5Cy2ajQp93aZzGb0ar/+5Jk8Af2mV/KQ9yjdgAADSAAAAEVGX82j26NwAAANIAAAASyzViAZ5ohjAKJd3GV23TMuIHjeeUoLY7TIvrRWbkXJ8VuFW6dJSBMBxgXLPnC+YldNCouDPiaJ031tYph+4bQapGBso8cLAtbFxmt+kkKcMM3puw1SocamprfoON0iB5ywXU0Fo//1IlEyHNTSkgAW///FiYJs////7/+7N/1GD+l9ZA3/2d3N+gAIEXzT7KZM6SqWssLGzFMFHTUAPW4ZZNoFdL2v8+r+v7GZb+WX/uUv65MOKBO+4rdUiX0YlGrVXHWf05azS6hKR9m4hgRVmLtVZ1L1EQ6Q1S1KQBhYRNNUrSlY39zOHRXTVDHFS//QSHqEp07+sJhqe/xEJQasAIAAgAU/x3egYv6lf4WgvwghwfDwfIB9QEl/zn5Ofl+nDHxPnL8/yhcct/Lu5d63zgn/KIIAKAImZDGqzEmxONE2uNcMeoInLnhwgIFAwSt0jqRKZrqI6jVOcaKJoP9RJcKlp7KlbZWMpSMobFmuuQkOhUqysJPOvwqRcdS//uSZPECBpJfzvO6g3AaoBaSACIBDuUXQyywuEDSip/kEAxg4qRqUOArk9RURBq4f4spJ1zP/BZyUJqFaxzUN0ykj2YmQwOCpsE2KIFFXdn6TmoWkRitHrQ/AZwCC4c4hWKrYxU+7qfH2g53UGBL4q5TkzUATa0k3i5IrAdbQApHtDdIBiosqwaCFMn6mRmgbiQZNiJpoSAgChQMFLLbwitLQMOpI8sugnJMjgoIHUXkLg6CwlteQ8gZRsLTJIbX4LGjkkUQRB3DIFmJwdZXNdicnoVCAWkBMDMZsELjRwxpTQJFQUGGxNHpucJPIKDOA7ffo8gYMA/rl8McztIz1O1VkYG2EAhaUGSUKuRpa++C9zK0jZ71dr02dWY6POdwlT/yA1eK6Pi9Bq+f//O0N6KduWBbAR+n/h8k0/yv+XWFGQACiNCsl0SILRtaiy6Ta/O8Jc1pYq7K2wPEl1ZA2QJ5JABKFoysTLtLz8KdjDMxZJFHj7oGO1FCrM0DO+ehs7BhVTmqpGYq1dYSGhzZAmNHNOSumd3IZIr6u+LUmM1aEP/7kmTjgPLyJMhDJhwwM6LIUABmdhEdfQQsmHFJK52fwBGJ6aMCQ2XhkoxH0a/aZ5eW2bDuprfPL3ErWKZo7cKLwPs7lyZwGiRMvPpIRuyF8QJKfP0NuhNBHbNyBsHLP+c//Q6XTv+85lpI44j8n69PtnqnPYj+fSOkeyGCxSvm8ThAEGtQrYzpIzGEJy2rVoWjmzWbQ2i0KoCNsAkpxYZoQxCSLOxmd0idosKY4QTijYlauamIrmxIDNEGY2DvYhMlZwxtMhTBOqY1DGjM0Omb0vNHBsokjraqDD5CjKkOCTsB0PgfXEq0eg7JhCHkCB+Nk3WUkoNaMcquThThbHH604RGF7UPL3Nhjb9Q7HS/7YDPpNoFyKO1JYb+fl/TM9e8P+Q83w/uS04PHgPbYZSi7ivscRw/dbRXRdO0EdMGfjSgFd5rY8rfLbrtNsakmnO0qxoo2s+xjRFMTAs6tQtFHKz9oCdw3Dhj0OjI6+I1tjVXWihW/oNkOxXkD9xM60X83LbC/tzbSppvMQm3GaVRdkSujOlbptbnd+ZsWlWT2jf/+5Bk74Xzbl3AkSYbclDsCAAEQ0ZNMYUDAYRoCVuyoAAAjDgvonxbF4GLN17gjhihIAAABKxncaCb8r+x2xfeXkhLbBjdkiPoWxo1rmeXv1KexZa1A9Oocb9qv8vsgzrkVPy/xDtclv0NFb55Fn00kZvysKlHhyneo/Pm9NTotiGSGARAnFCcSlDWFhLjFUViHUzHVBBkvaOpKRY0y3ZC9z7sMeliGZ8MUzHuaZs5loHK97VfGna1emloamWlFZzu/7KOI8MlLUj23FZefZe7amu0pxLMJwnsoreNTJwm+HPzcY+U/iZn+dFh0FjNWoWIJOuBQkvPQahUKnzqZHo2M5xksZTZotJHaDc2YrRa/bn5rnMstCSZ6WvxBiNIS6Ia5Lwj2esRL1DlKmbEZTI+9znlLETUrvtDvmtQhsOaHtoCIG3pNjp8vVxKFRAIwscShgY8Um1axFzBOtOw5FyMbUyNvKWO5EKIeAlglycQhOEeXpvvUV0hLT+UkjGaEkuntV6a6/LaX8vGOJKXuRPTYlLYOYMwzruVZnYU8l6qclH/+5Jk7o1zZWPAiMM2olYseBgAIw7N7Y0CAZh3yVSyYIAAjEiDVDXu7gjiDsWQUQGbsJUNTCbNAqs+VZxalKmV+eYN1ocoXD/zn7T36RiJ8ncQ2kWMyrCYiMtel06CMt2sNaTZ5kXbtYZkxf+ZBjpL9jmt1LDwknJWbg/92aze5qSCYg6i2JjOvY7keKirXeoquhhIVNczIaXDhUGMWEnEhAxCNxtCI8ZBqR5h91RRwCWMHQqZS8wZPQEc+wNAwQtXZSEN93fQFy6LTjMvW3O3xoLFTGdsQYxzE6On6+RbOz4YfcmbbRJwJNJqxU5vwq1MnwTnK6vm3ZkZdfhPTMx2yUUok1q1WfoojpZrC9eohOCYuQqYMeuS0kdwZ/pkyfJTcNQeTC+13QnaICBtrsHDFCQuM7UgYQhSmJW09DGwm2j09tMx+g3QZi9KUK4odA/RCtRVJYoaVKxdTjAzqrJuFBxQSEwKsVU5QiMirwXk7FVjMRsHuCOKQVzZ+RVY3bCLthOs4pQACRnYmwpfArDeFfga1NFpnBAUtxIpMqxj9J3M//uSZOmNEvJjQYhhHIJUKrg1BCMeTVmNBAGM08F5MOBAAIwRUwxkR1ECkOfHEjuKIcqi/VhEDAAD+o+aEdgkzPLqPPp0tilsKt2kqRjSyqRZOmjvqlqQXLS3apc3YeKAlMyEhSm5oy0JDSnBYAGG3TAKZg5FmrUZlrbOEfX5xrbwBlxfApFcElOEFQ5G5GKGCJOiK++OZ9sQwWDOhCNMQhA2MVP16TFbOlSi274esgzYrVnavYId3Zr1e5uLxjp+3iV7EzaS4YluftFzXy/2pUSmjueLO81ByoiszVFwhY5fm6l8eEUVzI6aroDDG1iEDXRXVTzsNxxRZIS7HWf0uSHTv+0a7SsRHMzQspr67FvbmbKtZyzfR/sQ6Z/d6Eh57mX+Ehhe+h9zh1PXiQyhM2+TND4DWo/zf6e6JAR4tsto87D0lVSZKZx4xNLE8LazSZPJIW392zmlu7p5hbG5jy+kCtnKyQEAf3pHRp1sc4NqNXp7appnzV++dUaNxlYYxpKdud18MEq9aiejFs6VSxZJH6UTbU5ZtOfOk/ZuWz1Pzv/7kmTqhzM+YUEAYRgCVKpoOAwi9E0peQKhmHtJRy2gQAAMAUu7Mhag9RM0hnRP2U5xaSlkoa0uRsIF/0K7AX90VXrXdAbUSZ1St3vsHN/ax9yUKUJjnnaw91PT08y8lR5DZZkU7V2OlOtlI8GRbHOzFYrHJvc++5WjihzOn8i0fOptaSmoGuztdau6u0ZoMVc1D++7bGK5SCek42Ly59wa86Yfp6O4gees7Nj/oCxVBWPg7itXMnu85Nv2KyCcK+ELMhAtJmeKqKnJhajrvdSjPNw1TjFEGQ/t0o2HCMMw56us+IMUkq+ZdpyY3jbSR3d6bAdoCEY9NVRzLNs2QFhHGWjOtlkI+AGISWJAEo+U8hM6erV7O63L6fI6H7StfNz02e+dymaUogiTr5/lDIPXu5SFCL2V/XrkX2F6VMWf1kOcUpD1MBSkmJnS2SSnYNaowsiu3SZGnUUi5lXBLET2WoKIlHpXu8tZpnTwa7sYhq0xDv6tD9J5N1Iqjqk8xqMkigWbTcdjmYyNMklL+ilsWxuSQ3/KxBNtFFTlnFm+UC3/+5Jk7Ymzw2I/gMZNck8smBAIYsYNYWkCowzaSTAuoJQRD1HuDJiCLkUlDGeE4T714B1WErGqinGWhTFC2RDOZP0mZmSR6xAqOQOMLjPs/VACWiibNmgVJogW2eZWHXTlZCBD//+0hf575n94LM7mmiF37TMz3cjk57mp90yNGe+5F3WPW02/NfHSFK0KH4et0SysnGyQSARG00yFDejGzaWwzq6o0BEYXD07lGGjyiteUO/Is2zh02U7omYWbjYiUXa4Fd3wCtmeYDKRntcy5fz781Zza10EdWZ8yi//7PPuQEq9jpZtOVYIAyHJlZiFZQOUcp5uFJGFNnoiTMwTUa6yDO6FXjRShPL6C60QxnGoEAEijIyDzZVuXImXxnJsmcM0R/zia/xd/03XGlWN2AJ3DmUABR/MwbFsErJdRFSazqRzUzVm06ckC2KtuFBsYOpjhYdQYpBBsF2SdAiURLv5ts+LkTq8bTtOFHIgcMom0Emj26ICRRYK2qxpe6bUn3vaC+W9u400Mg6b0ois5+hm1BJJA927A5SBhbGbvgrS//uSZO0Ac8thwIjGRmJPzHgwCCOKSySjEUCMzUknJ2EgEI67MG0pI3mOanVFGHnH4hUPbTZsLGlIsgnEkAAALK6uxE3EaWRcjVGYiT/O/Hc6pETF9YzB3zQ3vfNyoUtRJGe03I+82f9ozOau/ya7IXLcR06TpsCNIgidDm5kSfmaX8utYJkIJmt8y2zaUit8VzlooQBIEhRGtJQYaGoNicR5HQwpSSuCtpoUhHNrCAp0UnZkrBVVDPj45iaX2OlvMfnI35PJY7TOqXeeUYOuCq52er+ETfuG4ZzP8kvlobS1Jwdd7yzYmi0UqKPRwi7loc7up67b16/py/GO11NiYN5qQUV2iZJ9a+Su6Q1yKFLMGnImH0Y+bIBEwNlZP4CLmKpeKnmaUBMyptlP4R014X5FmZftbJqDUr11WqLmd41FBoRHCvOpnDbcZ89sa+PdvCi8J4d1TJG6JlrRAgDivVbTni2nMrDJDBo5ox0zBToq2oblVUQhiGZlo7IHV+AoVMgbC2kYjjRA5V7Y2gNCOpDeKFPfdZYIig+D4U3BRaIbMP/7kmT2BXQqY8AQyTUyWCwoKAAjBk6tjQMhpNYJNCsggCCN+bXdaXouJQ/FqOJcXAVKZEDXpQ/ITIbWvK7sjEhH+SHWr/+hKa/iMzSJV86wT3P32a4/bIqIiehHfMiN0/Knd4f+CMxef5/30Y/hP6Mf811+NmpWEkLZUtJUa2TuhoPE/EJp7O8SFMKZCWplT6pPaOCc5FjkZda9884pjyuqha1MoIVlRBq1F2cZi2Rk2yjmdzKtHpUxa6AkIk6VU62giSRYQCulhBrHIhB+S1D0usVPQ98s82X5MG0PHBHdoYNgYvYSZ1KPLKOJF0ys+bROdOv5N++zcqlFRHcM2r2iChHfqjm81siIHEZqYVxMJNlkgmZicZKI0NRUaxrsZblVTa5mK+zqikQkGVsqrq6qLod/z668U/iM3s5+95fwj6dtKOXeJ5K9qWkxsEaFDTjxzMlD6BUaN7qyaiN6jvSH3hZmRGOGwbMzDqgaWD1WUqQqrHMgTICyuEPMj3Dzb+x9mpyGsp03d8hvIbk9ITEdBspU42ILVDXxy7DXBBnZZeP/+5Jk5QXzCGNAgCMbcE+LqBAAIxRPYYz/AyDeiUsyYAASj1mDGSTrHHg5ERD1XKx01qgzJqKPAyXME0LKZFgmULmT67VZH/RK8hLMvlZ3BCffZ/FftZ9n/R7dwT5Py2eADRCWBxbVb4n4bd499Gr01UUuGViu1yeqwlw5aVQQg2mQvTtsggalmcLTMISB2i7EDMmhij3qiJM5CynqBxp9ASe0ZZDk6L01O03EIkEOiggaW7CVlFmOmSc8e4B4tbWPuEnFsxZ+W0EUTySi1EZsuIfbXyE57pIYjY90oIpw8IJKIIGFITVWlScGTd+7eHkCiOoqsLo4vRpMOryZlJCzpCLoEUqWm72L4JFT33VzEgjOu46nPQnVDheCjCC/d0o/leMb6AhR7wKetL3KHPJPt/uaeFGp9ODs4lnQijKxk2p0a7ktiPoejYbo5G7x81qrehCLQuikiGOCxeYYw7uJQQbaVDVVenhO02e04PvUm4dqJ0HIKvMjYQV0RHhM7pCIWeLRpEhLkpEhqDChUJzEPCZjtVmFtRQRQY6JIp7Sue4Y//uSZOSF8wJkwIBhHAJExHggACIuURmQ/KMZM8lvsmAAAAwJT+2dm4nsy8dptl6yKJG5aayD0zTLkj8aNJ2ii8TF6hmnOZVVt6I+YOLmCgZj90/gxEGbq5ggD/IgUMZGUhdM2cIhDI5TIybo7Zv/KlZkzMKKZpz/PVl4m47ANX/nVKpVas3dhonTqdIXG/5HcrwiNF3QqEAMqcaIABXE0HBt4Q/0eMP2vWpi7ehwlWcZJYZPU0EAMgWCHgQlOgCBkUyZS6Rh8SqQMwftEgbR0KOR6g8iSsrmc8xRwd+zJrSstNe7RpYxUqZ+bkChiiiDizLNJ7V0zXLBgmBeBAtrV1jp6+wTEFTltso9LSqFjzD3kXGg6oWsXjw8lb9c2aScUJnJqKV4jEIu0yZc7StS3pkx0RDDzDLpgVQTaZfFHWKqFgAFFhzDKo+AxNZMNJRGtNQPckSiIR3Am1lyMJQNDcBadIR8v0Cg1RWAiNGeGZogRXKApNeoWhqDCs2UyOyqK0oLNvkhSurm9NHzvWxbHIYSYRMiobmkfags2tFWfYtFOv/7kmTegPNtYECAwzXSRAo4IAQirk2NaQtBmHaI9QAgwACIAHJKc3reDx6qXnhrxPP0rqCU2dbDxQmQ2hVFMI+FLeBCKNlsFcSGRVMNNpydNuVI4W3izAY8RM8I1Km0JGh021kY+EDNeZUn62xMsp767U5D1IF//y6E0e0/IpD+Hf8oalrK16hq1I53yqlcnMI/Xf4XrS/0cso7+9M8WU6Y/OSHZIELIhBsSXVTaJlT+Kqky4hZoRGoRmBMvS2YeMlU2kxjpQS1IyKmxAnSCSUIPmlwgmyyigjB8wZ07JVwpi2ix1ZhXOlsRsEyHXOBmI2fKxIL4rjKVU2hHhkZbx2CiVYEFCEHxZAEAU+gNHVwwTeqkWiZIYlVCBzxE8sFCzhOo846SF2MVOFnDH1S0q5bK3IgPJCzWGtUvNqEgqsVUOItDg8UlDbgDFmtropSeedaLKvIcLKMMSX0qWkyEW73cZgM+ZprehDf2+rlOhJVdDFtoDwaZ2KdqR6IIWNErkIJXsZNy7xH0W2zbHS5Nk2dReMT13ZDbtdHlBV55PJ3+6X/+5Jk7400iWQ/kMZKclDL+BAII0pMZYcCAIBgCRYAIOAgibgEF4e2xrIc79+d9xPGDw86yTk06Me3x1k+ZDrnPP/WDZd+ZxM4+saqEWl1G9wseNEDsxzDSgq+bg2K6xyqyVsjfZgbX83/kV1bFj/PIcJZaTksjyrxgmQUFWKtnghUV/1npWz9WWSqdWGq5wHhzRgwCADAyBKbU1Ebj7qZ0Yw+eEoIVDUTyjEWLVzV0d5Fpm6s2GVlIG7rop7PzlWqmIIW6RSl9s5OqfEp27d7pt+5kRxDzqP6nYqcw/UozJSzMJ1NSs54bScFSlD9chCqN3Xw7oVNNqZga3CjlgdB9CAEaUACAVptJV3twTu3fyKa86AjAAiOWNtWpuCyE8hAQJRI413MdpouwJqY0c6QP3A2yrnY4h+Z3NaCyUnlsOHTEFTQ/Lp/WZlUyl9g6ieTQBSGI4SpZWP2Kt3smv1hOhYvDFlEbnXcYFDiqac1/13uPFn9vhfZbeTLOiGT13xe7p1oYnqBPdayenezCSFxbFuzNOedg+tvEFsXEARskA51//uSZOkDM4JjP4DDNqBSrGgADEP0TjWNAQGYe0kyMSCgII64IXrGY0KbPJNMw/tL2Hj2e5PYwndxLGYEQQirKfQRBKUGCycM4pyZzI8W9WoVLQWU7mcrr90SZPldRTgJmhMF5kaJgJrMmabuesZzWzZZiQyOK8SEeYStOCXOLEqS5VYC+Q6pvL3Afy/vr1TLZUBFNm3gsfs7+VUPMoopp2N9x21do5hSMaXlbsFpo29ZQTfm2hFRdOFUquJJ2o3+jJob/J2zLa8o7Obz+ZPi5z5Kg/t0kUkLsTRf55t7NbjqTlkcqoy9Y3Eq+mVS8Tmy05uokQpAhqjsxLCpLMvFLgzCHRNaAN8wCEsomczt+JUuqvpsQ9ndbg3kI59mSjrb7qZVst5+s5v/+vrMydZdGYhETsifrm91Qex6IVMUqeUeWK0gBSAAxuyTlNNDqUysoJiskajJ1IGJxkvqp52XqAKTE6AE7JGDaZtfhhBFVIeTAZ+8sRAKtPu0WkA1le5dGOp4Vesh8h0q4/baKEdM8hFIMapBi9xdD2hb1LWVoVaBBP/7kmTnjfPXZMAIyTWCSIloIAgjrk4FjwIDDNpI8KoggBAKwGwTNbW3MObghcgbj0orzuRVRqarfmLtCLCCEy87k2m0W0/IgRkLTEyA8XIWEaTtqspfVC7bIwYM/MpSeX/4p1HymI7qY1tHBheZl5pvlKVnVlCpd9Sy//9fYxUN5noYCWVl4E4n8tRPmN6FJmuUplC5aPWaomUaVHCIZa8kjbGOfsG3F7WkY5p2JAzTQ5zOfCZ7mvVnpoApBethrI5CTEZKW1FPnHqSfJk2PKJ5JtCttI0NuUdYEVDEb8PEPi3t3NGaWtGaZpQC/avEH5tlmcmQuTi0+TNQTCHRKpVvIEcVoIZcIU5USQ2aaux5EiknWTEogYWuFmgGF8RK0XMNMsvqx1I/NzDQkzf5v2fUiUdfCzv0aJfV/xT+L+/SQNJagiBWVzChxGhacmlFnXKykkVJDSRZ/KEH4migbmFwapKqd90pdAtJ2I6OHJAZ22xrWJNhNL0TSzCyE1MYagSHFrPhlDTmpnsxNyEuukJG9Vu0hripVVM8jUXxgswlLlX/+5Jk7oUEcGW/sSZOwEcMR9AAYhxPhZUAAYzAQKcL33AQjTgL0KoYk4tV0wVmD2SVkoKplAaRIDFrKIEiVNdNmOIY9CyZWsjFLasDTMVmvlR/yQHw/QEWTTfDm7iIoUWWZQgQjpoj9n/+1PqUiHh9g1y3LhHuQoMW6ERqNckzEI0rSuKHchjCaNfp/ViGbRGnfV7yPv9/Iw1z55BQUZRRkUAolBOlbomHSP3zTNziuxym5eTcIgQJE8sGglA1jamsiSHHf68odFOxo6ZMaexpvyhe0qplXI5aXTmqW+a9bFC8fzYzbWmwu4mzXRUG/JZbCUfSM+TCD+0w5v7MRVblUEQEdRPR7UyVvCF/+THm94WfWzM+8JPKFV7LC78MkCZK79rGwKKPBzXwWX+tlBaoDe/ZS01DQR1OKHDiVuoqGeIjIjVIx9TKzA9HlpiXtNiyabBGVKOoVATOS+E9G074selzayyFB2U0fKQ106c7VsyBT13dKXwowCZ95rysLPUWSeCmq88RpWv2gmjrJWnaFofnEIdOwzopk22OnuFJvO5y//uSZPAA9GplPoDGTPBNjGfgBGW4CwEvByGEekkmLOBAEYtg0FSoyy4ZW0QlRCRFLVR8Nr6n/anEEAACrKPaaEmgjrtr301cnO0QiVjW1/J7ZB37fP72+YMb0S9vDNlMZFQT8Qv+JY8CNX6Hiv2M0z74RpYV9SOKfXOfxyhTgfbR6cHyK095Rf/1XyhVTjBVHJUR89KLibwqHs88Ve6i5ab6vNPc8INf2meg7et5xUlNsk9WXWYRp0IHVLTrB0G9GjtJHXZPEmvdnsTP5DnYcd0oLt12zGE3xjT26DWesGskjJxC4Sh6VC33WlZz4cLSOw6FF6m9nw74QM15QZe0YgUy2TL5Dfub1Y55IAIf1yt6XXfqOv/rMvB7mJzDqOsC6S+p/uYfPJzfd7mv1BUKn/12fb22yQ8zivOfTkb4u33V+aST8veol8tK8JK//71NjyUEAgSgAKZbvuRqN3uvu6o7fGlW0EYzw8xJybUaqDsShAMeibkyBHED5tG0zXIDJyVXThoIoLn4tyPzBKLSrGFBRRHown7koTKDccFysFZIIP/7kmTwjzPBZD8AZjIyWCy4BQBDBo8tkwADJNoBIYAg4BCJuXesYuE4DWYKRCwUaEduoUIayA3LnQPKKMMZ7QK7zmGw4/C+lUBkvLvITU0N0p4kzVlk9llJJIUmaF5VjTuZnwspyx3K5w29pmmscvM6pfxYYxBiMHT9s0IsYn+Cxd3zmZWkXPJe6vWOMVW5aGVLl3dsdAtSWIQAADILKJqi1IYd0oKSmR3C8yTKKZh58TgSaARraWlSyTiCmOZVUInnisKCUqvDp6kGdTCm+S44RuPIQJmDL6mdBE99YcR+OysOrMef+jhig5LUEcglopDKw4xQh44EF5RzoFPd5WeK8d+/4plP6t5lHInm2BVY+ZRbAIKzKU8ysJsioYcAFzQP5ne7dLI4mUNv+N5Jnlt8rdKZqRIdhRZq1E5FtwiW5US9ENDhLrpABAILYokLJoVKNQ+LmTiOItwsG0hNTu8tOjzjnydepkAIUOrbBtwg+oQS+vZhurPw+UL8RRGiH3FOZnRK28KrrUgUPhpP0jbw6e5uIO8/dme7Oc+2aU57KMP/+5Jk5oHzmF/BMMM3QlFr6CAAIyRNIWEFIZhwyRStIMAQjjhbK2i9RXOITZ2v01mSfZUcoDUe2PiBzZnuU3/+a5fnMAAH/kdU3jcUwTL/kZE/BUp1kU49JQ3wjkKImTSlzfLJDal2yUVbHZzwT/mWSfbP9J7tPjorcdCn7mf5GdVRchaIfweIpZ6k5FZU6Fp8IHbCxXw7QCgklxkgFZOs9x/kvWOYY+XkNaNRez9iIh8qpEPr4k6IqD0xw8rBznRZaBryOijjKEYEK0yAQ2NGSazonQF9TMyc5nIwOG1vMbKwi0go22z0sOnl9TEUzkGMncxezcSHhcf+12pM/e51KQj6k/HG9wo52L9VLZ/ba/f30w62pvfF3CdR//9nRqdP2bbeaTn//qYunmdzW3s7a8qZ/Fqs2HKV34zVPeEm0MjC7b0aqUmYoRETRqUZLQaYalzmJsmbctJ8E2z59Q0kR3iJSgbEK7mDymykWSfJZCAqKDUqHnkXWBo0eu0Rw9foIZfUCMhdWnmNyqNEFpzRbRDEzEdSIaGtkCQWYlKgCWds//uSZOwAc8hiv6jJNgJUa8gVDCPSTC2JDUMEfMkJgGDAAYgBgVHpGq6yJvLtWIrRdPyrfLBySL4dpTl4QUjjU0aaFpPFTdOaS6+65xaair0mDNH9bNOJLHIrIyu98nFtNnRiOGpmuu6tcuJ7e3X6X/4+usik5ZoU/J3buf/m69bv/XlOZ+Wq/xM/+HkgTMkM2XYFQ7ByCDQ3mTQlJGY3JTa8KssIOYtTwdSVB2o5GnatWVX2RBRmyDERsZT3GdECGSZOT5BNjB0yCVVspEeR4RWoEMDs17sYDpVM+RRqLcYw8JjkgHmR1JtDtOdpmdPcd5UJyZDjMYW9SMgBggiOHuGz2QaX/TXaf26Jrv0T0qmXnxt3+UNG6v7hz5hsPn9/QN+vh8FL0f4gIdaap73/ai2/E/82nck58jzP1s1lIK/2FTKqHYTRQPtkB9Y1BtRddb6w25pW4pjCMaXhKq1ZK7+Ik0QVGtp/VQxhTbsfqqyTdaus2SbcFVUuQpPSRyyJCyjJJpI2V0C1ItgutUnDyU2cQ+co2WlU2JEOELGvYXOUyv/7kmTyCQQ5Yr8BJkeyUOy4EAAjEgxlaQUBjNfJIIAhLBCNuRRUsfUnIhkkhleIcPkhrrNJchgwPJJ0is00GMSeD45U3FFsGVsRvYukadWuViiNIWcPjx24jYak1zLJ+G2qlo/6gh4ev/lSimQr5mTId2uirO5+Ubveit1JHqQvuTcMM7VD9jUyvPhnyl/mS9/heaF0EDyh92DoZgvrZBSBnsxk1h0S3qLCmvGq6z1zVYaqzbLGb9V6oY2aozBh1BiW9jXY+GFEwUGcmzwoy9XMKRhnEqsY/OgJTja8NQQolgqxgYxwUFJqq1qCNVWNSAgYnUm6Aw9jJYBOTGQZlE8aDXGyi4Ap7VuKuiV8s0QztaFHi2JQFkTqqzpVxZ8OlXYaWAgasWWLFQalgKAXLAUOkYilQCNOyIakJVPBoqyRDRERSRUArOh1TEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVX/+5Jk7w80W2W+gSk18FJMeAAAIwoMOXr2AYRqyRWAH2AQiOBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVaxyZZQoKgey2GrLDLWGTBQT2eaxlsDjAQVHIv2pBrSPWGWscmpMoWPKTL99rLJZS9Q0OUmWGxq3KWrVGIxIYELGFLHVmBoKWWO1IUssB0tukGChxm2ssz/NWCg0fqyGUkAtU/4e//zEQ0wk///5mhGB/+wwtJlz/sNYa/kxrDsKdzJrUNeGoaGX0mzJllQy45Nf9YdJr//SYLXWd/klvaSlURKUkTEFNRTMuMTAwqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uSZJMP8wVfsYBhGoJESjZiBCNuQAABpAAAACAAADSAAAAEqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqkxBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqv/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpMQU1FMy4xMDCqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqr/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAASqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqTEFNRTMuMTAwqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqTEFNRTMuMTAwqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqv/7kGRBD/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqkxBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqv/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpMQU1FMy4xMDCqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqr/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAASqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqTEFNRTMuMTAwqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqkxBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqv/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpMQU1FMy4xMDCqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqr/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAASqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqTEFNRTMuMTAwqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqkxBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqv/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpMQU1FMy4xMDCqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqr/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAASqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqTEFNRTMuMTAwqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqkxBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqv/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpMQU1FMy4xMDCqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqr/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAASqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqTEFNRTMuMTAwqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqkxBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqv/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpMQU1FMy4xMDCqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqr/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAASqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqTEFNRTMuMTAwqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqkxBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqv/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpMQU1FMy4xMDCqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqr/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAASqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqTEFNRTMuMTAwqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqkxBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqv/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpMQU1FMy4xMDCqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqr/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAASqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqTEFNRTMuMTAwqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqkxBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqv/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpMQU1FMy4xMDCqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqr/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAASqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqTEFNRTMuMTAwqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqTEFNRTMuMTAwqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqv/7kGRBD/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqkxBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqv/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpMQU1FMy4xMDCqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqr/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAASqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqTEFNRTMuMTAwqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqkxBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqv/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqpMQU1FMy4xMDCqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqr/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAASqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqTEFNRTMuMTAwqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqkxBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq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TWCgolo6w1QVT//Zb0m///4ymTAxmjBR0LGBVRFoFABRA7OxlKVrG6erf5Udq7f2RyyiIgPb3mWX1QzUmjUmUo3YZClIGeLpcoT3bJ/liilVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUxBTUUzLjEwMFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVX/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAARVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUxBTUUzLjEwMFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUxBTUUzLjEwMFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVX/+5BkQQ/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAARVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVX/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAARVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUxBTUUzLjEwMFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVX/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAARVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUxBTUUzLjEwMFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVX/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAARVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUxBTUUzLjEwMFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVX/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAARVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUxBTUUzLjEwMFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVX/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAARVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUxBTUUzLjEwMFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVU="

DEFAULT_ALERT_DEFINITION = {
    "alert_key": "SIMULATION_CRITICAL",
    "name": "Simulated Critical Account",
    "title": "Critical Case Alert",
    "subtitle": "The following high priority account requires immediate attention and is still not resolved.",
    "message": "Critical account alert: H&M is a high priority account and requires immediate attention.",
    "severity": "Critical",
    "popup_enabled": True,
    "sound_enabled": True,
    "flashing_enabled": True,
    "blinking_enabled": True,
    "icon": "!",
    "sound_filename": "77e629ebd4a1b51110736bdd69348450.mp3",
    "sound_mime": "audio/mpeg",
    "delay_seconds": 5,
}


def get_alert_definition(alert_key="SIMULATION_CRITICAL"):
    """Return the editable alert template without changing existing alert behavior."""
    try:
        doc = col(ALERT_DEFINITION_COLLECTION).find_one({"alert_key": text(alert_key)})
        if doc:
            return doc
    except Exception:
        pass
    definition = dict(DEFAULT_ALERT_DEFINITION)
    definition["alert_key"] = text(alert_key) or DEFAULT_ALERT_DEFINITION["alert_key"]
    try:
        col(ALERT_DEFINITION_COLLECTION).update_one(
            {"alert_key": definition["alert_key"]},
            {"$setOnInsert": definition},
            upsert=True,
        )
        return col(ALERT_DEFINITION_COLLECTION).find_one({"alert_key": definition["alert_key"]}) or definition
    except Exception:
        return definition


def save_alert_definition(definition):
    """Create or update an alert template used by popup notifications."""
    key = text(definition.get("alert_key"))
    if not key:
        return False, "Alert key is required."

    sound_upload = definition.get("sound_upload")
    sound_data_b64 = text(definition.get("sound_data_b64"))
    sound_filename = text(definition.get("sound_filename"))
    sound_mime = text(definition.get("sound_mime")) or "audio/mpeg"

    if sound_upload is not None:
        try:
            raw_sound = sound_upload.getvalue()
            if raw_sound:
                # Keep the alert sound inside the alert definition so an
                # administrator can replace it without changing application code.
                sound_data_b64 = base64.b64encode(raw_sound).decode("ascii")
                sound_filename = text(getattr(sound_upload, "name", "")) or "custom-alert-sound"
                sound_mime = text(getattr(sound_upload, "type", "")) or "audio/mpeg"
        except Exception as exc:
            return False, f"Unable to read the uploaded alert sound: {exc}"

    doc = {
        "alert_key": key,
        "name": text(definition.get("name")) or key,
        "title": text(definition.get("title")) or "Critical Case Alert",
        "subtitle": text(definition.get("subtitle")),
        "message": text(definition.get("message")),
        "severity": text(definition.get("severity")) or "Critical",
        "popup_enabled": bool(definition.get("popup_enabled", True)),
        "sound_enabled": bool(definition.get("sound_enabled", True)),
        "flashing_enabled": bool(definition.get("flashing_enabled", True)),
        "blinking_enabled": bool(definition.get("blinking_enabled", True)),
        "icon": text(definition.get("icon")) or "!",
        "sound_filename": sound_filename,
        "sound_mime": sound_mime,
        "delay_seconds": max(0, min(60, int(definition.get("delay_seconds", 5) or 0))),
        "updated_at": utc_now(),
    }
    if sound_data_b64:
        doc["sound_data_b64"] = sound_data_b64
    try:
        col(ALERT_DEFINITION_COLLECTION).update_one(
            {"alert_key": key},
            {"$set": doc, "$setOnInsert": {"created_at": utc_now()}},
            upsert=True,
        )
        return True, "Alert definition saved."
    except Exception as exc:
        return False, str(exc)


def list_alert_definitions():
    try:
        return list(col(ALERT_DEFINITION_COLLECTION).find({}).sort("name", ASCENDING))
    except Exception:
        return []


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




def scan_alerts(tasks, states=None, now=None):
    """Create missing alerts with minimal MongoDB round trips.

    Alert evaluation is intentionally throttled because Duration is updated
    entirely in the browser. When dashboard state has already been calculated,
    reuse it instead of calculating every case a second time on each refresh.
    """
    now_epoch = time.time()
    last_scan = float(st.session_state.get("_last_alert_scan", 0.0) or 0.0)
    if now_epoch - last_scan < ALERT_SCAN_MIN_INTERVAL:
        return
    st.session_state["_last_alert_scan"] = now_epoch


    now = now or utc_now()
    candidates = []


    for task in tasks:
        task_id = str(task["_id"])
        state = states.get(task_id) if states else calculate_state(task, now)
        if not state or not (state["critical"] or state["nearing_due"]):
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
                f"Case nearing SLA warning threshold: {text(task.get('case_number'))} "
                f"— {text(task.get('account_name'))} — 40% timeframe remaining"
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
            state_snapshot = calculate_state(task)
            resolution_snapshot = automated_case_assessment(task, state_snapshot)
            action_logs = task.get("case_action_log") or []
            latest_action_log = action_logs[-1] if isinstance(action_logs, list) and action_logs and isinstance(action_logs[-1], dict) else {}
            history.append({
                "action": f"{station_display_name(station)} checklist completed:\n{bullets}",
                "timestamp": now,
                "actor": "Caseflow",
                "station": station,
                "resolution_assessment": resolution_snapshot,
                "action_plan": text(latest_action_log.get("action_plan")),
                "case_note": text(latest_action_log.get("note")),
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



def refresh_case_checklist_state(task_id, station):
    """Refresh checklist widget values from the latest persisted MongoDB state."""
    station = station_name(station)
    try:
        from bson import ObjectId
        task = col(TASKS_COLLECTION).find_one(
            {"_id": ObjectId(str(task_id))}
        )
        if not task:
            return False

        items = get_case_station_checklist(task, station)
        prefix = f"case_checklist_{task_id}_{station}_"
        valid_keys = set()

        for idx, item in enumerate(items):
            key = f"{prefix}{idx}"
            valid_keys.add(key)
            st.session_state[key] = bool(item.get("checked"))

        # Remove stale checkbox keys if checklist items were removed.
        for key in list(st.session_state.keys()):
            if key.startswith(prefix) and key not in valid_keys:
                st.session_state.pop(key, None)

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
        # Persist the checkbox immediately. Streamlit automatically reruns
        # the current dialog after an on_change callback, so do NOT call
        # st.rerun() here; an explicit app rerun can close the Case Details
        # dialog. The next dialog render reads the saved checklist state and
        # updates Transfer Case availability immediately.
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
            "resolution_assessment": automated_case_assessment(task, calculate_state(task)),
            "action_plan": action_plan,
            "case_note": note,
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


def update_case_status(task_id, new_status, logged_by="Caseflow User"):
    """Update the editable case status and record the change in Case History."""
    new_status = text(new_status)
    if not new_status:
        return False, "Choose a case status."
    try:
        from bson import ObjectId
        now = utc_now()
        task = col(TASKS_COLLECTION).find_one({"_id": ObjectId(str(task_id))}) or {}
        old_status = text(task.get("status")) or "Open"
        actor = text(logged_by) or "Caseflow User"
        if old_status == new_status:
            return False, "No status change was made."
        station = station_name(task.get("department"))
        history = list(task.get("history") or [])
        history.append({
            "action": f"Case status changed from {old_status} to {new_status}.",
            "timestamp": now,
            "actor": actor,
            "station": station,
            "resolution_assessment": automated_case_assessment(task, calculate_state(task)),
            "action_plan": text(task.get("next_action")),
            "case_note": text(task.get("notes")),
        })
        result = col(TASKS_COLLECTION).update_one(
            {"_id": ObjectId(str(task_id))},
            {"$set": {
                "status": new_status,
                "last_update": now,
                "history": history,
            }},
        )
        clear_task_cache()
        try:
            _account_priority_lookup.clear()
        except Exception:
            pass
        return result.modified_count > 0, ""
    except Exception as exc:
        return False, f"Unable to update case status: {exc}"


def _append_collaboration_history(task_id, action, actor="Caseflow", station=None):
    """Persist a collaboration-tab action and mirror it into the main case history."""
    action = text(action)
    if not action:
        return False
    try:
        from bson import ObjectId
        now = utc_now()
        task = col(TASKS_COLLECTION).find_one({"_id": ObjectId(str(task_id))}) or {}
        station = station_name(station or task.get("department"))
        actor = text(actor) or "Caseflow"
        collaboration_entry = {
            "action": action,
            "timestamp": now,
            "actor": actor,
            "station": station,
        }
        history = list(task.get("history") or [])
        history.append({
            "action": f"Collaboration · {action}",
            "timestamp": now,
            "actor": actor,
            "station": station,
            "history_type": "collaboration",
        })
        result = col(TASKS_COLLECTION).update_one(
            {"_id": ObjectId(str(task_id))},
            {
                "$push": {
                    "collaboration_history": {"$each": [collaboration_entry], "$slice": -100}
                },
                "$set": {
                    "history": history,
                    "last_update": now,
                },
            },
        )
        clear_task_cache()
        return result.modified_count > 0
    except Exception:
        return False


def create_active_war_room(task_id, meeting_link, tagged_people=None, attendance=None, actor="Caseflow User"):
    """Create an active War Room from a pasted meeting link."""
    meeting_link = text(meeting_link)
    if not meeting_link:
        return False, "Paste a valid War Room / meeting link."
    try:
        from bson import ObjectId
        now = utc_now()
        task = col(TASKS_COLLECTION).find_one({"_id": ObjectId(str(task_id))}) or {}
        station = station_name(task.get("department"))
        room_id = sha256(f"{task_id}|{meeting_link}|{now.isoformat()}")[:16]
        tagged_people = list(dict.fromkeys(text(x) for x in (tagged_people or []) if text(x)))
        attendance = list(dict.fromkeys(text(x) for x in (attendance or []) if text(x)))
        assigned = text(task.get("assigned_to"))
        if assigned and assigned not in attendance:
            attendance.insert(0, assigned)

        room = {
            "room_id": room_id,
            "meeting_link": meeting_link,
            "tagged_people": tagged_people,
            "attendance": attendance,
            "discussed": "",
            "action_plan": "",
            "acknowledged_by": [],
            "created_at": now,
            "created_by": text(actor) or "Caseflow User",
            "status": "ACTIVE",
        }
        existing = list(task.get("active_war_rooms") or [])
        existing.append(room)
        action = (
            f"Active War Room created for {text(task.get('case_number')) or 'case'}."
            f"\n• Link: {meeting_link}"
            + (f"\n• Tagged: {', '.join(tagged_people)}" if tagged_people else "")
            + (f"\n• Attendees: {', '.join(attendance)}" if attendance else "")
        )
        history = list(task.get("history") or [])
        history.append({
            "action": f"Collaboration · {action}",
            "timestamp": now,
            "actor": text(actor) or "Caseflow User",
            "station": station,
            "history_type": "collaboration",
        })
        col(TASKS_COLLECTION).update_one(
            {"_id": ObjectId(str(task_id))},
            {"$set": {
                "active_war_rooms": existing[-10:],
                "history": history,
                "last_update": now,
            },
             "$push": {
                 "collaboration_history": {
                     "$each": [{
                         "action": action,
                         "timestamp": now,
                         "actor": text(actor) or "Caseflow User",
                         "station": station,
                         "type": "war_room_created",
                         "room_id": room_id,
                         "meeting_link": meeting_link,
                         "tagged_people": tagged_people,
                         "attendance": attendance,
                     }],
                     "$slice": -100,
                 }
             }},
        )
        clear_task_cache()
        return True, room_id
    except Exception as exc:
        return False, f"Unable to create the active War Room: {exc}"


def record_war_room_update(task_id, room_id, discussed, action_plan, actor="Caseflow User"):
    """Record discussion/action plan for an active War Room."""
    discussed = text(discussed)
    action_plan = text(action_plan)
    if not discussed and not action_plan:
        return False, "Add discussion or an action plan first."
    try:
        from bson import ObjectId
        now = utc_now()
        task = col(TASKS_COLLECTION).find_one({"_id": ObjectId(str(task_id))}) or {}
        rooms = list(task.get("active_war_rooms") or [])
        room = next((x for x in rooms if isinstance(x, dict) and text(x.get("room_id")) == text(room_id)), None)
        if not room:
            return False, "Active War Room not found."
        room["discussed"] = discussed
        room["action_plan"] = action_plan
        room["last_updated_at"] = now
        room["last_updated_by"] = text(actor) or "Caseflow User"
        station = station_name(task.get("department"))
        detail = (
            f"War Room update recorded for {text(task.get('case_number')) or 'case'}."
            + (f"\n• Discussed: {discussed}" if discussed else "")
            + (f"\n• Action Plan: {action_plan}" if action_plan else "")
        )
        history = list(task.get("history") or [])
        history.append({
            "action": f"Collaboration · {detail}",
            "timestamp": now,
            "actor": text(actor) or "Caseflow User",
            "station": station,
            "history_type": "collaboration",
            "room_id": room_id,
        })
        col(TASKS_COLLECTION).update_one(
            {"_id": ObjectId(str(task_id))},
            {"$set": {"active_war_rooms": rooms, "history": history, "last_update": now},
             "$push": {"collaboration_history": {
                 "$each": [{
                     "action": detail,
                     "timestamp": now,
                     "actor": text(actor) or "Caseflow User",
                     "station": station,
                     "type": "war_room_update",
                     "room_id": room_id,
                     "discussed": discussed,
                     "action_plan": action_plan,
                 }],
                 "$slice": -100,
             }}},
        )
        clear_task_cache()
        return True, ""
    except Exception as exc:
        return False, f"Unable to record the War Room update: {exc}"


def acknowledge_war_room(task_id, room_id, people, actor="Caseflow User"):
    people = list(dict.fromkeys(text(x) for x in (people or []) if text(x)))
    if not people:
        return False, "Select at least one attendant or tagged person."
    try:
        from bson import ObjectId
        now = utc_now()
        task = col(TASKS_COLLECTION).find_one({"_id": ObjectId(str(task_id))}) or {}
        rooms = list(task.get("active_war_rooms") or [])
        room = next((x for x in rooms if isinstance(x, dict) and text(x.get("room_id")) == text(room_id)), None)
        if not room:
            return False, "Active War Room not found."
        acknowledged = list(dict.fromkeys(
            text(x) for x in (room.get("acknowledged_by") or []) if text(x)
        ))
        acknowledged.extend(x for x in people if x not in acknowledged)
        room["acknowledged_by"] = acknowledged
        room["acknowledged_at"] = now
        station = station_name(task.get("department"))
        detail = (
            f"War Room acknowledgement recorded for {text(task.get('case_number')) or 'case'}."
            f"\n• Acknowledged by: {', '.join(people)}"
        )
        history = list(task.get("history") or [])
        history.append({
            "action": f"Collaboration · {detail}",
            "timestamp": now,
            "actor": text(actor) or "Caseflow User",
            "station": station,
            "history_type": "collaboration",
            "room_id": room_id,
        })
        col(TASKS_COLLECTION).update_one(
            {"_id": ObjectId(str(task_id))},
            {"$set": {"active_war_rooms": rooms, "history": history, "last_update": now},
             "$push": {"collaboration_history": {
                 "$each": [{
                     "action": detail,
                     "timestamp": now,
                     "actor": text(actor) or "Caseflow User",
                     "station": station,
                     "type": "war_room_acknowledgement",
                     "room_id": room_id,
                     "acknowledged_by": people,
                 }],
                 "$slice": -100,
             }}},
        )
        clear_task_cache()
        return True, ""
    except Exception as exc:
        return False, f"Unable to record the acknowledgement: {exc}"


def close_active_war_room(task_id, room_id, actor="Caseflow User"):
    """Remove an active War Room while preserving its complete record in collaboration history."""
    try:
        from bson import ObjectId
        now = utc_now()
        task = col(TASKS_COLLECTION).find_one({"_id": ObjectId(str(task_id))}) or {}
        rooms = list(task.get("active_war_rooms") or [])
        room = next((x for x in rooms if isinstance(x, dict) and text(x.get("room_id")) == text(room_id)), None)
        if not room:
            return False, "Active War Room not found."
        remaining = [
            x for x in rooms
            if not (isinstance(x, dict) and text(x.get("room_id")) == text(room_id))
        ]
        station = station_name(task.get("department"))
        detail = (
            f"War Room closed for {text(task.get('case_number')) or 'case'}."
            f"\n• Link: {text(room.get('meeting_link')) or 'None'}"
            + (f"\n• Tagged: {', '.join(text(x) for x in room.get('tagged_people') or [])}" if room.get("tagged_people") else "")
            + (f"\n• Attendees: {', '.join(text(x) for x in room.get('attendance') or [])}" if room.get("attendance") else "")
            + (f"\n• Discussed: {text(room.get('discussed'))}" if text(room.get("discussed")) else "")
            + (f"\n• Action Plan: {text(room.get('action_plan'))}" if text(room.get("action_plan")) else "")
            + (f"\n• Acknowledged by: {', '.join(text(x) for x in room.get('acknowledged_by') or [])}" if room.get("acknowledged_by") else "")
        )
        history = list(task.get("history") or [])
        history.append({
            "action": f"Collaboration · {detail}",
            "timestamp": now,
            "actor": text(actor) or "Caseflow User",
            "station": station,
            "history_type": "collaboration",
            "room_id": room_id,
        })
        col(TASKS_COLLECTION).update_one(
            {"_id": ObjectId(str(task_id))},
            {"$set": {"active_war_rooms": remaining, "history": history, "last_update": now},
             "$push": {"collaboration_history": {
                 "$each": [{
                     "action": detail,
                     "timestamp": now,
                     "actor": text(actor) or "Caseflow User",
                     "station": station,
                     "type": "war_room_closed",
                     "room_id": room_id,
                     "meeting_link": text(room.get("meeting_link")),
                     "tagged_people": list(room.get("tagged_people") or []),
                     "attendance": list(room.get("attendance") or []),
                     "discussed": text(room.get("discussed")),
                     "action_plan": text(room.get("action_plan")),
                     "acknowledged_by": list(room.get("acknowledged_by") or []),
                 }],
                 "$slice": -100,
             }}},
        )
        clear_task_cache()
        return True, ""
    except Exception as exc:
        return False, f"Unable to close the War Room: {exc}"


def reassign_case(task, assignee):
    assignee = text(assignee)
    current = station_name(task.get("department"))
    if not assignee or assignee == text(task.get("assigned_to")):
        return False, "Choose a different assignee."
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

    actor = text(task.get("assigned_to")) or "Caseflow"
    state_snapshot = calculate_state(task)
    resolution_snapshot = automated_case_assessment(task, state_snapshot)
    action_logs = task.get("case_action_log") or []
    latest_action_log = action_logs[-1] if isinstance(action_logs, list) and action_logs and isinstance(action_logs[-1], dict) else {}
    history.append({
        "action": (
            f"Transferred from {station_display_name(source_station)} "
            f"to {station_display_name(destination_station)}"
        ),
        "timestamp": now,
        "actor": actor,
        "station": source_station,
        "station_duration_seconds": max(0, float(state_snapshot.get("elapsed", 0))),
        "resolution_assessment": resolution_snapshot,
        "action_plan": text(latest_action_log.get("action_plan")),
        "case_note": text(latest_action_log.get("note")),
    })
    history.append({
        "action": (
            f"Entered {station_display_name(destination_station)} station. "
            f"SLA clock reset to {STATIONS.get(destination_station, STATIONS['CARE'])['sla_minutes']} minutes."
        ),
        "timestamp": now,
        "actor": text(task.get("assigned_to")) or "Caseflow",
        "station": destination_station,
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


        # Keep Streamlit's native uploader layout untouched. Earlier custom
        # positioning of the uploader drop-zone caused duplicate/overlapping
        # "Upload" text. The native label is already collapsed on each uploader
        # below, so no uploader geometry override is required here.
        if not st.session_state[
            "admin_unlocked"
        ]:


            st.markdown(
                "### Administrator Access"
            )

            st.markdown(
                """
                <style>
                /* Admin PIN is intentionally password-only: hide the native
                   visibility/reveal control. The surrounding st.form() keeps
                   Enter-key submission enabled. */
                div[data-testid="stDialog"] [data-testid="stTextInput"] button {
                    display:none !important;
                }
                </style>
                """,
                unsafe_allow_html=True,
            )


            with st.form("admin_pin_form", clear_on_submit=False):
                pin = st.text_input(
                    "Admin PIN",
                    type="password",
                    placeholder="Enter admin PIN",
                )

                unlock_submitted = st.form_submit_button(
                    "Unlock Settings",
                    type="primary",
                    use_container_width=True,
                )


            if unlock_submitted:
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

            # Settings uses the same reliable single-scroll-surface behavior as
            # the H&M Case Details workspace. The marker scopes this CSS to the
            # Settings dialog only, so other dialogs and dashboard behavior are
            # not changed.
            st.markdown(
                """
                <style>
                div[data-testid="stDialog"]:has(.settings-dialog-marker) > div {
                    overflow:hidden !important;
                    height:min(88vh,760px) !important;
                    max-height:calc(100vh - 24px) !important;
                }
                div[data-testid="stDialog"]:has(.settings-dialog-marker) > div > div {
                    height:calc(100% - 48px) !important;
                    max-height:calc(100% - 48px) !important;
                    min-height:0 !important;
                    overflow-y:auto !important;
                    overflow-x:hidden !important;
                    scrollbar-width:thin !important;
                    scrollbar-color:#7f94aa #edf2f7 !important;
                    overscroll-behavior:contain !important;
                }
                div[data-testid="stDialog"]:has(.settings-dialog-marker) > div > div::-webkit-scrollbar {
                    width:10px !important;
                    display:block !important;
                }
                div[data-testid="stDialog"]:has(.settings-dialog-marker) > div > div::-webkit-scrollbar-track {
                    background:#edf2f7 !important;
                    border-radius:8px !important;
                }
                div[data-testid="stDialog"]:has(.settings-dialog-marker) > div > div::-webkit-scrollbar-thumb {
                    background:#7f94aa !important;
                    border-radius:8px !important;
                    border:2px solid #edf2f7 !important;
                }
                div[data-testid="stDialog"]:has(.settings-dialog-marker) [data-testid="stDialogContent"] {
                    height:auto !important;
                    max-height:none !important;
                    min-height:0 !important;
                    overflow:visible !important;
                    overflow-y:visible !important;
                    overflow-x:visible !important;
                }
                @media (max-width:760px) {
                    div[data-testid="stDialog"]:has(.settings-dialog-marker) > div {
                        height:calc(100vh - 20px) !important;
                        max-height:calc(100vh - 20px) !important;
                    }
                }
                </style>
                <div class="settings-dialog-marker" aria-hidden="true"></div>
                """,
                unsafe_allow_html=True,
            )

            tabs = st.tabs([
                "Cases",
                "Account Priority",
                "External Sync",
                "Access Control",
                "Alerts",
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
                     label_visibility="collapsed",
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
                     label_visibility="collapsed",
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
                     label_visibility="collapsed",
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
            # ALERT DEFINITIONS — additive admin functionality
            # -----------------------------------------------
            with tabs[4]:
                st.markdown("### Alert Management")
                st.caption(
                    "Create and edit popup alert definitions. Existing dashboard alerts and simulation behavior remain unchanged unless an alert definition is explicitly edited."
                )

                definitions = list_alert_definitions()
                existing_keys = [text(d.get("alert_key")) for d in definitions if text(d.get("alert_key"))]
                default_key = "SIMULATION_CRITICAL"
                if default_key not in existing_keys:
                    get_alert_definition(default_key)
                    definitions = list_alert_definitions()
                    existing_keys = [text(d.get("alert_key")) for d in definitions if text(d.get("alert_key"))]

                edit_options = ["+ Create New Alert"] + existing_keys
                selected_alert_key = st.selectbox(
                    "Alert to create/edit",
                    edit_options,
                    key="alert_definition_selector",
                )

                selected_definition = DEFAULT_ALERT_DEFINITION.copy()
                if selected_alert_key != "+ Create New Alert":
                    selected_definition.update(get_alert_definition(selected_alert_key))
                else:
                    selected_definition["alert_key"] = "NEW_ALERT"
                    selected_definition["name"] = "New Alert"
                    selected_definition["title"] = "Critical Case Alert"
                    selected_definition["subtitle"] = ""
                    selected_definition["message"] = ""
                    selected_definition["delay_seconds"] = 0

                with st.form("alert_definition_form", clear_on_submit=False):
                    alert_key = st.text_input("Alert Key", value=text(selected_definition.get("alert_key")))
                    alert_name = st.text_input("Alert Name", value=text(selected_definition.get("name")))
                    alert_title = st.text_input("Popup Title", value=text(selected_definition.get("title")))
                    alert_subtitle = st.text_area("Popup Subtitle", value=text(selected_definition.get("subtitle")), height=70)
                    alert_message = st.text_area("Alert Message", value=text(selected_definition.get("message")), height=80)
                    alert_severity = st.selectbox(
                        "Severity",
                        ["Critical", "High", "Medium", "Low"],
                        index=["Critical", "High", "Medium", "Low"].index(text(selected_definition.get("severity")) or "Critical") if text(selected_definition.get("severity")) in {"Critical", "High", "Medium", "Low"} else 0,
                    )

                    st.markdown("**Alert Appearance & Sound**")
                    alert_popup = st.checkbox("Show as popup alert", value=bool(selected_definition.get("popup_enabled", True)))
                    alert_flashing = st.checkbox(
                        "Flash the alert popup",
                        value=bool(selected_definition.get("flashing_enabled", True)),
                        help="Makes the alert card pulse/flash while it is displayed.",
                    )
                    alert_blinking = st.checkbox(
                        "Blink the alert icon",
                        value=bool(selected_definition.get("blinking_enabled", True)),
                        help="Makes the default alert icon blink while the popup is displayed.",
                    )
                    alert_sound = st.checkbox(
                        "Play alert sound",
                        value=bool(selected_definition.get("sound_enabled", True)),
                    )
                    current_sound_name = text(selected_definition.get("sound_filename")) or "Built-in uploaded alert sound"
                    st.caption(f"Current alert sound: {current_sound_name}")
                    alert_sound_upload = st.file_uploader(
                        "Add / change alert sound",
                        type=["mp3", "wav", "ogg", "m4a"],
                        key=f"alert_sound_upload_{sha256(text(selected_alert_key))[:12]}",
                        help="Upload a new MP3, WAV, OGG or M4A file to replace the current alert sound for this alert.",
                        label_visibility="collapsed",
                    )
                    if alert_sound_upload is not None:
                        st.caption(f"New sound selected: {text(getattr(alert_sound_upload, 'name', '')) or 'Uploaded audio'}")

                    alert_delay = st.number_input(
                        "Delay before popup (seconds)",
                        min_value=0,
                        max_value=60,
                        value=int(selected_definition.get("delay_seconds", 5) or 0),
                        step=1,
                    )
                    save_alert = st.form_submit_button("Save Alert Definition", type="primary", use_container_width=True)

                if save_alert:
                    ok, msg = save_alert_definition({
                        "alert_key": alert_key,
                        "name": alert_name,
                        "title": alert_title,
                        "subtitle": alert_subtitle,
                        "message": alert_message,
                        "severity": alert_severity,
                        "popup_enabled": alert_popup,
                        "sound_enabled": alert_sound,
                        "flashing_enabled": alert_flashing,
                        "blinking_enabled": alert_blinking,
                        "icon": text(selected_definition.get("icon")) or "!",
                        "sound_upload": alert_sound_upload,
                        "sound_data_b64": selected_definition.get("sound_data_b64"),
                        "sound_filename": selected_definition.get("sound_filename"),
                        "sound_mime": selected_definition.get("sound_mime"),
                        "delay_seconds": alert_delay,
                    })
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

                st.info("The uploaded sound is used by the simulated critical popup when 'Play the uploaded alert sound' is enabled. It is embedded in this application, so the alert does not depend on a separate local file.")

            # -----------------------------------------------
            # SIMULATION
            # -----------------------------------------------

            with tabs[5]:

                st.markdown(
                    "### Simulation"
                )

                st.caption(
                    "Resets all 25 mock cases into five staggered, non-breached SLA states per station. "
                    "Only one case across all stations is promoted to the H&M critical-account alert when simulation starts."
                )

                if st.button(
                    "▶ Simulation",
                    type="primary",
                    use_container_width=True,
                    key="run_caseflow_simulation",
                    help="Reset all 25 mock cases below the 40%-remaining warning threshold, then show one H&M critical-account alert exactly 5 seconds after simulation starts.",
                ):
                    reset_count = reset_mock_case_durations()
                    now = utc_now()

                    # Use the first CARE mock case as the simulated critical account.
                    simulation_case = col(TASKS_COLLECTION).find_one(
                        {
                            "is_mock": True,
                            "case_number": "CAR-2026-0001",
                        }
                    )

                    simulation_case_id = ""
                    if simulation_case:
                        from bson import ObjectId
                        simulation_id = simulation_case.get("_id")
                        # The H&M case is only an alert placeholder at simulation start.
                        # Its CARE timer must NOT begin until the user clicks View Case.
                        simulation_due = now + timedelta(seconds=45)
                        
                        # Keep the alert visually urgent without making the actual CARE timer
                        # start before the case enters CARE.
                        simulation_started = now

                        col(TASKS_COLLECTION).update_one(
                            {"_id": simulation_id},
                            {
                                "$set": {
                                    "account_priority": "Yes",
                                    "priority": "Critical",
                                    "account_name": "H&M",
                                    "status": "In Progress",
                                    "active": False,
                                    "simulation_hold": True,
                                    "simulation_collaboration": {
                                        "title": "H&M Critical Account Collaboration Session",
                                        "status": "LIVE",
                                        "meeting_link": "https://meet.example.com/ovr-vw-hm-critical",
                                        "participants": ["Arianne May Escabillas", "June John Cruz", "Jonathan Gaspar", "Kenjie Locsin"],
                                        "discussion": "H&M is a high priority account requiring immediate coordination. The team is validating entitlement, impact and the fastest safe resolution path.",
                                        "action_plan": "Confirm account priority and entitlement, validate the affected service, assign an owner for each next step, and provide the customer with the next confirmed update.",
                                        "acknowledged_by": [],
                                        "started_at": now,
                                    },
                                    "station_started_at": simulation_started,
                                    "due_date": simulation_due,
                                    "last_update": now,
                                },
                                "$push": {
                                    "history": {
                                        "action": "Simulation activated a critical-account alert.",
                                        "timestamp": now,
                                        "actor": "Caseflow Simulation",
                                        "station": "CARE",
                                    }
                                },
                            },
                        )
                        simulation_case_id = str(simulation_id)
                        _set_global_simulation_event(simulation_id, now)

                        # Seed the alert center with the same simulated critical-account event.
                        try:
                            col(ALERT_COLLECTION).delete_many({
                                "task_id": simulation_case_id,
                                "alert_type": "PRIORITY_ACCOUNT",
                                "acknowledged": False,
                            })
                            col(ALERT_COLLECTION).insert_one({
                                "task_id": simulation_case_id,
                                "station": "CARE",
                                "alert_type": "PRIORITY_ACCOUNT",
                                "trigger_key": station_warning_trigger_key({
                                    **simulation_case,
                                    "station_started_at": simulation_started,
                                    "department": "CARE",
                                }),
                                "message": text(get_alert_definition("SIMULATION_CRITICAL").get("message")) or "Critical account alert: H&M is a high priority account and requires immediate attention.",
                                "created_at": now,
                                "acknowledged": False,
                            })
                        except Exception:
                            pass

                    clear_task_cache()
                    st.session_state["simulation_case_id"] = simulation_case_id or None
                    # The simulation alert is intentionally delayed by 5 seconds.
                    # The browser reveals the already-rendered alert at this
                    # timestamp without refreshing the dashboard.
                    st.session_state["simulation_alert_active"] = False
                    st.session_state["simulation_alert_case_id"] = simulation_case_id
                    st.session_state["simulation_alert_dismissed"] = False
                    st.session_state["open_case_after_alert"] = False
                    simulation_alert_definition = get_alert_definition("SIMULATION_CRITICAL")
                    simulation_delay_seconds = max(0, min(60, int(simulation_alert_definition.get("delay_seconds", 5) or 0)))
                    st.session_state["simulation_alert_delay_until"] = (
                        time.time() + simulation_delay_seconds if simulation_case_id else 0.0
                    )
                    st.session_state["simulation_active"] = bool(simulation_case_id)
                    st.session_state["show_settings"] = False

                    if simulation_case_id:
                        st.success(
                            f"Simulation started. {reset_count} mock case(s) reset; the H&M critical-account alert will appear in 5 seconds."
                        )
                    else:
                        st.error("Simulation could not find the CARE mock case CAR-2026-0001.")


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


def _case_details_dismissed():
    """Finish the simulated-alert transition and immediately return to CARE."""
    if not (
        st.session_state.get("open_case_after_alert")
        and st.session_state.get("simulation_alert_case_id")
        and st.session_state.get("simulation_alert_dismissed")
    ):
        return

    held_case_id = st.session_state.get("simulation_alert_case_id")
    try:
        from bson import ObjectId
        # The simulated case is already activated when View Case is clicked.
        # Keep this write idempotent so closing the dialog can never leave the
        # case in a hidden/simulation-hold state.
        col(TASKS_COLLECTION).update_one(
            {"_id": ObjectId(str(held_case_id))},
            {
                "$set": {
                    "active": True,
                },
                "$unset": {"simulation_hold": ""},
            },
        )
        clear_task_cache()
        st.session_state["selected_station"] = "CARE"
        st.session_state["open_case_after_alert"] = False
        # The alert has served its purpose. The H&M record is now a normal
        # active CARE case, so the simulation alert must never be rendered again.
        st.session_state["simulation_alert_active"] = False
        st.session_state["simulation_alert_dismissed"] = True
        st.session_state["simulation_alert_delay_until"] = 0.0

        # The dialog is opened from the dashboard fragment. Explicitly return
        # to the full application render after dismissal so the user never
        # lands on a blank fragment state; CARE is rendered immediately with
        # the newly activated case.
        st.rerun(scope="app")
    except Exception:
        # If MongoDB is temporarily unavailable, still return to the normal
        # dashboard rather than leaving the user on an empty page.
        st.session_state["selected_station"] = "CARE"
        st.session_state["open_case_after_alert"] = False
        st.session_state["simulation_alert_active"] = False
        st.session_state["simulation_alert_dismissed"] = True
        st.session_state["simulation_alert_delay_until"] = 0.0
        try:
            st.rerun(scope="app")
        except Exception:
            pass


@st.dialog("Case Details", width="large", on_dismiss=_case_details_dismissed)
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

    priority_label = display_priority_label(state).upper()
    priority_class = {
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

            history = list(task.get("history") or [])
            # Legacy collaboration/communication records are folded into Case History
            # so the complete journey remains visible even for cases created before
            # Collaboration History was introduced.
            history_actions = {
                text(event.get("action"))
                for event in history
                if isinstance(event, dict)
            }
            for collab_event in list(task.get("collaboration_history") or []):
                if not isinstance(collab_event, dict):
                    continue
                collab_action = text(collab_event.get("action"))
                if collab_action and f"Collaboration · {collab_action}" not in history_actions:
                    history.append({
                        "action": f"Collaboration · {collab_action}",
                        "timestamp": collab_event.get("timestamp"),
                        "actor": collab_event.get("actor") or collab_event.get("user"),
                        "station": collab_event.get("station") or department,
                        "history_type": "collaboration",
                    })
            legacy_communications = task.get("communications") or task.get("communication_history") or []
            for comm in legacy_communications if isinstance(legacy_communications, list) else []:
                if isinstance(comm, dict):
                    comm_body = text(comm.get("message") or comm.get("body") or comm.get("details"))
                    comm_stamp = comm.get("timestamp") or comm.get("created_at")
                    comm_actor = text(comm.get("sender") or comm.get("user") or comm.get("from"))
                else:
                    comm_body = text(comm)
                    comm_stamp = None
                    comm_actor = ""
                if comm_body:
                    history.append({
                        "action": f"Collaboration · {comm_body}",
                        "timestamp": comm_stamp,
                        "actor": comm_actor or "Caseflow User",
                        "station": department,
                        "history_type": "collaboration",
                    })
            station_durations = case_station_durations(task)
            visited_stations = [
                station for station in STATIONS
                if station in station_durations
            ]
            if visited_stations:
                duration_items = "".join(
                    f"<div class='history-duration-item'><span>{html.escape(station_display_name(station))}</span>"
                    f"<strong>{html.escape(format_elapsed_duration(station_durations[station]))}</strong></div>"
                    for station in visited_stations
                )
                st.markdown(
                    "<div class='history-station-duration'>"
                    "<div class='history-station-duration-title'>Total Duration by Station</div>"
                    f"<div class='history-duration-grid'>{duration_items}</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )

            st.markdown("<div class='case-card case-history-card'>", unsafe_allow_html=True)
            st.markdown("<div class='case-card-heading'><span class='case-heading-icon'>◷</span>Case History</div>", unsafe_allow_html=True)
            if history:
                # Chronological order intentionally starts at CARE and follows the
                # case through ARCH, PET, SUPPLY CHAIN and FULFILLMENT.
                for event in sorted(
                    history,
                    key=lambda x: as_utc(x.get("timestamp")) if isinstance(x, dict) and as_utc(x.get("timestamp")) else datetime.min.replace(tzinfo=timezone.utc),
                ):
                    if isinstance(event, dict):
                        action = text(event.get("action") or event.get("event") or event.get("details")) or "Case updated"
                        stamp = dt_display(event.get("timestamp")) or ""
                        actor = text(event.get("user") or event.get("actor") or event.get("assigned_to")) or "System"
                        station_label = station_display_name(event.get("station"))
                        resolution_snapshot = text(event.get("resolution_assessment"))
                        action_plan_snapshot = text(event.get("action_plan"))
                        note_snapshot = text(event.get("case_note"))
                    else:
                        action, stamp, actor = text(event), "", "System"
                        station_label = resolution_snapshot = action_plan_snapshot = note_snapshot = ""
                    action_html = html.escape(action).replace("\n", "<br>")
                    if station_label:
                        action_html = f"<b>{html.escape(station_label)}</b><br>{action_html}"
                    if resolution_snapshot:
                        action_html += f"<br><span class='history-snapshot'><b>Resolution / Assessment:</b> {html.escape(resolution_snapshot)}</span>"
                    if action_plan_snapshot:
                        action_html += f"<br><span class='history-snapshot'><b>Action Plan:</b> {html.escape(action_plan_snapshot)}</span>"
                    if note_snapshot:
                        action_html += f"<br><span class='history-snapshot'><b>Case Note:</b> {html.escape(note_snapshot)}</span>"
                    event_duration = event.get("station_duration_seconds") if isinstance(event, dict) else None
                    if event_duration is not None and station_label:
                        action_html += (
                            f"<br><span class='history-snapshot'><b>Total time in station:</b> "
                            f"{html.escape(format_elapsed_duration(event_duration))}</span>"
                        )
                    st.markdown(
                        f"<div class='history-row'><div class='history-dot'></div>"
                        f"<div class='history-main'><div class='history-meta'>{html.escape(stamp)} "
                        f"<span>{html.escape(actor)}</span></div>"
                        f"<div class='history-action'>{action_html}</div></div></div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No activity history is stored on this case yet.")
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
                status_options = list(dict.fromkeys(
                    CASE_STATUS_OPTIONS + ([status] if status else [])
                ))
                status_index = status_options.index(status) if status in status_options else 0
                editable_status = st.selectbox(
                    "Case Status",
                    status_options,
                    index=status_index,
                    key=f"case_status_{task_id}",
                )
                if editable_status != status:
                    if st.button(
                        "Update Status",
                        use_container_width=True,
                        key=f"case_update_status_{task_id}",
                    ):
                        ok, message = update_case_status(task_id, editable_status, assigned_to)
                        if ok:
                            st.success(f"Case status updated to {editable_status}.")
                            st.rerun()
                        else:
                            st.error(message or "Unable to update case status.")
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

                    # The checklist callback persists the checkbox immediately and
                    # Streamlit reruns the dialog after the widget change. Re-read
                    # the case here so the Transfer Case control reflects the
                    # persisted checklist state without a manual refresh button.
                    try:
                        from bson import ObjectId
                        live_task = col(TASKS_COLLECTION).find_one(
                            {"_id": ObjectId(str(task_id))}
                        )
                    except Exception:
                        live_task = None

                    if live_task:
                        task = live_task
                        current_missing = checklist_missing(task, current)

                    if st.button(
                        "Transfer Case",
                        type="primary",
                        use_container_width=True,
                        key=f"case_transfer_{task_id}",
                        disabled=bool(current_missing),
                        help=(
                            "Complete every current-station checklist item to enable transfer."
                            if current_missing
                            else "Transfer is ready. Choose the destination station."
                        ),
                    ):
                        if destination == current:
                            st.warning("Choose a different station.")
                        elif current_missing:
                            missing_html = "<br>• ".join(html.escape(x) for x in current_missing[:8])
                            st.error(f"Complete the current-station checklist before transfer:<br>• {missing_html}", unsafe_allow_html=True)
                        elif transfer_case(task, destination):
                            st.success(f"Case transferred to {station_name(destination)}.")
                            st.rerun()
                        else:
                            st.error("Unable to transfer case.")

                    st.markdown(
                        "<div class='case-actions-note'>Station transfer is available immediately after the final checklist item is checked. Reassignment does not require checklist completion.</div>",
                        unsafe_allow_html=True,
                    )
                st.markdown("</div>", unsafe_allow_html=True)

            with checklist_col:
                st.markdown("<div class='case-card'>", unsafe_allow_html=True)
                checklist_head_col, checklist_refresh_col = st.columns([1, 0.10], gap="small")
                with checklist_head_col:
                    st.markdown(
                        "<div class='case-card-heading'><span class='case-heading-icon'>☑</span>Station Task Checklists</div>",
                        unsafe_allow_html=True,
                    )
                with checklist_refresh_col:
                    st.button(
                        "↻",
                        key=f"case_checklist_refresh_{task_id}_{current}",
                        help="Refresh the checklist from the latest saved case state.",
                        use_container_width=True,
                        on_click=refresh_case_checklist_state,
                        args=(task_id, current),
                    )
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
                st.markdown("<div class='kb-sop-list-title'>Matching SOPs for this case</div><div class='kb-sop-list-spacer'></div>", unsafe_allow_html=True)
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
            # ACTIVE / MOCK WAR ROOM + COLLABORATION SESSION
            # -----------------------------------------------------------
            st.markdown(
                "<div class='meeting-panel'>"
                "<div class='meeting-panel-title'>War Room / Meeting</div>"
                "<div class='meeting-panel-sub'>Paste a meeting link to create an active War Room. Record discussion, action plans, attendance and acknowledgements without leaving Case Details.</div>"
                "</div>",
                unsafe_allow_html=True,
            )

            latest_events = _case_update_events(task)
            latest_event = max(latest_events, key=lambda x: x[0]) if latest_events else None
            latest_text = text(latest_event[1]) if latest_event else "No live update has been recorded yet."
            latest_actor = text(latest_event[2]) if latest_event and latest_event[2] else "Caseflow"
            participants_preview = list(dict.fromkeys(CASEFLOW_ASSIGNEES + ([assigned_to] if assigned_to else [])))
            participant_preview = participants_preview[:5] or [assigned_to]
            participant_html = "".join(
                f"<span class='war-room-avatar'>{html.escape((text(name) or '?')[:1].upper())}</span>"
                for name in participant_preview if text(name)
            )

            participant_options = list(dict.fromkeys(
                CASEFLOW_ASSIGNEES
                + ([assigned_to] if assigned_to and assigned_to not in CASEFLOW_ASSIGNEES else [])
            ))

            # -----------------------------------------------------------
            # MOCK COLLABORATION SESSION — visible only after Simulation.
            # -----------------------------------------------------------
            if (
                st.session_state.get("simulation_active")
                and str(st.session_state.get("simulation_case_id") or "") == str(task_id)
            ):
                simulation_session = task.get("simulation_collaboration") or {}
                sim_people = simulation_session.get("participants") or participant_preview
                sim_discussion = text(simulation_session.get("discussion")) or (
                    "H&M is a high priority account requiring immediate coordination."
                )
                sim_action_plan = text(simulation_session.get("action_plan")) or (
                    "Validate entitlement, confirm impact, assign owners and provide the next customer update."
                )
                sim_link = text(simulation_session.get("meeting_link"))
                video_tiles = "".join(
                    f"<div class='simulation-video-tile'><div class='simulation-video-avatar'>{html.escape((text(person) or '?')[:1].upper())}</div>"
                    f"<div class='simulation-video-name'>{html.escape(text(person))}</div><div class='simulation-video-status'>● Connected</div></div>"
                    for person in sim_people[:6] if text(person)
                )
                st.markdown(
                    f"<div class='simulation-collab-card'>"
                    f"<div class='simulation-collab-head'><div><span class='simulation-live-dot'></span><b>LIVE COLLABORATION · SIMULATION</b>"
                    f"<div class='simulation-collab-title'>H&amp;M Critical Account Session</div></div><span class='simulation-session-badge'>LIVE</span></div>"
                    f"<div class='simulation-video-grid'>{video_tiles}</div>"
                    f"<div class='simulation-collab-grid'><div><div class='war-room-label'>DISCUSSION</div><div class='simulation-collab-copy'>{html.escape(sim_discussion)}</div></div>"
                    f"<div><div class='war-room-label'>ACTION PLAN</div><div class='simulation-collab-copy'>{html.escape(sim_action_plan)}</div></div></div>"
                    f"<div class='simulation-collab-footer'><span>Mock collaboration session for demonstration only.</span>"
                    f"{f'<a href=\"{html.escape(sim_link, quote=True)}\" target=\"_blank\" rel=\"noopener noreferrer\">Open mock session ↗</a>' if sim_link else ''}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            # -----------------------------------------------------------
            # USER-CREATED ACTIVE WAR ROOMS
            # -----------------------------------------------------------
            active_rooms = task.get("active_war_rooms") or []
            if isinstance(active_rooms, list) and active_rooms:
                st.markdown(
                    "<div class='communication-section-label'>Active War Rooms</div>",
                    unsafe_allow_html=True,
                )

                for room in reversed(active_rooms[-10:]):
                    if not isinstance(room, dict):
                        continue
                    room_id = text(room.get("room_id"))
                    if not room_id:
                        continue
                    room_open_key = f"active_war_room_open_{task_id}_{room_id}"
                    room_open = bool(st.session_state.get(room_open_key, False))
                    room_link = text(room.get("meeting_link"))
                    room_tagged = list(room.get("tagged_people") or [])
                    room_attendance = list(room.get("attendance") or [])
                    room_ack = list(room.get("acknowledged_by") or [])
                    room_focus = subject
                    room_update = text(room.get("discussed")) or "No discussion has been recorded yet."
                    room_actor = text(room.get("last_updated_by") or room.get("created_by")) or "Caseflow"
                    room_participants = list(dict.fromkeys(room_attendance + room_tagged))
                    room_participant_html = "".join(
                        f"<span class='war-room-avatar'>{html.escape((text(name) or '?')[:1].upper())}</span>"
                        for name in room_participants[:6] if text(name)
                    )
                    with st.container(key=f"active_war_room_tile_{task_id}_{room_id}"):
                        st.markdown(
                            f"<div class='war-room-mock active-war-room'>"
                            f"<div class='war-room-top'><div><span class='war-room-live-dot'></span><b>ACTIVE WAR ROOM</b><span class='war-room-case'>{html.escape(case_number)}</span></div><span class='war-room-status'>LIVE</span></div>"
                            f"<div class='war-room-grid'>"
                            f"<div><div class='war-room-label'>CURRENT FOCUS</div><div class='war-room-focus'>{html.escape(room_focus)}</div><div class='war-room-muted'>{html.escape(station_display_name(department))} · {html.escape(priority_label.title())}</div></div>"
                            f"<div><div class='war-room-label'>PARTICIPANTS</div><div class='war-room-avatars'>{room_participant_html}</div><div class='war-room-muted'>{len(room_participants)} people tagged / attending</div></div>"
                            f"<div><div class='war-room-label'>MOST RECENT UPDATE</div><div class='war-room-update'>{html.escape(room_update[:190])}</div><div class='war-room-muted'>by {html.escape(room_actor)}</div></div>"
                            f"</div></div>",
                            unsafe_allow_html=True,
                        )
                        if st.button(
                            "Hide War Room Details" if room_open else "Open War Room",
                            use_container_width=True,
                            key=f"active_war_room_toggle_{task_id}_{room_id}",
                        ):
                            st.session_state[room_open_key] = not room_open
                            st.rerun()

                    if room_open:
                        st.markdown(
                            f"<div class='war-room-expanded active-war-room-expanded'>"
                            f"<div class='war-room-expanded-head'><div><b>War Room Details</b><span> · {html.escape(case_number)}</span></div><span class='war-room-expanded-live'>LIVE</span></div>"
                            f"<div class='war-room-expanded-grid'>"
                            f"<div><div class='war-room-label'>WAR ROOM LINK</div><a class='war-room-link' href='{html.escape(room_link, quote=True)}' target='_blank' rel='noopener noreferrer'>{html.escape(room_link) if room_link else 'No link recorded'} ↗</a></div>"
                            f"<div><div class='war-room-label'>CURRENT ATTENDANTS</div><div class='war-room-muted'>{html.escape(', '.join(text(x) for x in room_attendance) or 'None recorded')}</div></div>"
                            f"<div><div class='war-room-label'>TAGGED PEOPLE</div><div class='war-room-muted'>{html.escape(', '.join(text(x) for x in room_tagged) or 'None recorded')}</div></div>"
                            f"<div><div class='war-room-label'>ACKNOWLEDGED BY</div><div class='war-room-muted'>{html.escape(', '.join(text(x) for x in room_ack) or 'No acknowledgement recorded')}</div></div>"
                            f"</div></div>",
                            unsafe_allow_html=True,
                        )

                        discussed_key = f"war_room_discussed_{task_id}_{room_id}"
                        action_plan_key = f"war_room_action_plan_{task_id}_{room_id}"
                        ack_key = f"war_room_ack_{task_id}_{room_id}"

                        discussed = st.text_area(
                            "Discussed",
                            value=text(room.get("discussed")),
                            placeholder="Record what was discussed, decisions, findings or blockers...",
                            height=85,
                            key=discussed_key,
                        )
                        action_plan = st.text_area(
                            "Action Plan",
                            value=text(room.get("action_plan")),
                            placeholder="Record owners, next steps, due actions or commitments...",
                            height=85,
                            key=action_plan_key,
                        )

                        action_cols = st.columns(2)
                        with action_cols[0]:
                            if st.button(
                                "＋ Record Discussion & Action Plan",
                                type="primary",
                                use_container_width=True,
                                key=f"record_war_room_update_{task_id}_{room_id}",
                            ):
                                ok, msg = record_war_room_update(
                                    task_id,
                                    room_id,
                                    discussed,
                                    action_plan,
                                    assigned_to or "Caseflow User",
                                )
                                if ok:
                                    st.success("War Room documentation saved to Collaboration History.")
                                    st.rerun()
                                else:
                                    st.error(msg)

                        acknowledgement_options = list(dict.fromkeys(
                            [text(x) for x in room_attendance + room_tagged if text(x)]
                        ))
                        with action_cols[1]:
                            acknowledged_people = st.multiselect(
                                "Acknowledge by attendants / tagged people",
                                acknowledgement_options,
                                default=[x for x in room_ack if x in acknowledgement_options],
                                key=ack_key,
                            )
                            if st.button(
                                "✓ Record Acknowledgement",
                                use_container_width=True,
                                key=f"ack_war_room_{task_id}_{room_id}",
                            ):
                                ok, msg = acknowledge_war_room(
                                    task_id,
                                    room_id,
                                    acknowledged_people,
                                    assigned_to or "Caseflow User",
                                )
                                if ok:
                                    st.success("Acknowledgement saved to Collaboration History.")
                                    st.rerun()
                                else:
                                    st.error(msg)

                        if st.button(
                            "Close Active War Room",
                            type="secondary",
                            use_container_width=True,
                            key=f"close_active_war_room_{task_id}_{room_id}",
                        ):
                            ok, msg = close_active_war_room(
                                task_id,
                                room_id,
                                assigned_to or "Caseflow User",
                            )
                            if ok:
                                st.session_state.pop(room_open_key, None)
                                st.success("War Room closed. Its complete details remain in Collaboration History.")
                                st.rerun()
                            else:
                                st.error(msg)

            # -----------------------------------------------------------
            # MOCK WAR ROOM — retained until real collaboration data exists.
            # -----------------------------------------------------------
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
                    "Hide War Room Details" if war_room_open else "Open War Room",
                    use_container_width=True,
                    key=f"war_room_open_button_{task_id}",
                ):
                    st.session_state[war_open_key] = not war_room_open
                    _append_collaboration_history(
                        task_id,
                        (
                            f"War Room opened for {case_number}."
                            if not war_room_open
                            else f"War Room details hidden for {case_number}."
                        ),
                        assigned_to or "Caseflow",
                        department,
                    )

            if war_room_open:
                meetings = task.get("meetings") or []
                latest_meeting = meetings[-1] if isinstance(meetings, list) and meetings and isinstance(meetings[-1], dict) else {}
                current_attendees = latest_meeting.get("attendance") or participant_preview
                attendee_html = "".join(
                    f"<li>{html.escape(text(name))}</li>"
                    for name in current_attendees if text(name)
                ) or "<li>No attendees recorded yet.</li>"
                st.markdown(
                    f"<div class='war-room-expanded'><div class='war-room-expanded-head'><div><b>Mock War Room Details</b><span> · {html.escape(case_number)}</span></div><span class='war-room-expanded-live'>MOCK LIVE</span></div>"
                    f"<div class='war-room-expanded-grid'><div><div class='war-room-label'>CURRENT ATTENDEES</div><ul>{attendee_html}</ul></div>"
                    f"<div><div class='war-room-label'>MOCK WAR ROOM LINK</div><a class='war-room-link' href='{mock_link}' target='_blank' rel='noopener noreferrer'>Open mock war room ↗</a><div class='war-room-muted'>Demonstration placeholder while no real collaboration data is available.</div></div></div></div>",
                    unsafe_allow_html=True,
                )

            # -----------------------------------------------------------
            # PASTE LINK → ACTIVE WAR ROOM
            # -----------------------------------------------------------
            meeting_link_key = f"meeting_link_{task_id}"
            meeting_tags_key = f"meeting_tags_{task_id}"
            meeting_attendance_key = f"meeting_attendance_{task_id}"

            def _create_from_pasted_war_room():
                pasted_link = text(st.session_state.get(meeting_link_key))
                if not pasted_link:
                    return
                tags = st.session_state.get(meeting_tags_key, []) or []
                attendance = st.session_state.get(meeting_attendance_key, []) or []
                ok, _ = create_active_war_room(
                    task_id,
                    pasted_link,
                    tags,
                    attendance,
                    assigned_to or "Caseflow User",
                )
                if ok:
                    st.session_state[meeting_link_key] = ""

            st.markdown(
                "<div class='communication-section-label'>Create Active War Room</div>",
                unsafe_allow_html=True,
            )
            meeting_link = st.text_input(
                "War Room / Meeting Link",
                value="",
                placeholder="Paste Teams, Meet, Zoom or other meeting link — it will create an active War Room...",
                key=meeting_link_key,
                on_change=_create_from_pasted_war_room,
            )
            meeting_tagged = st.multiselect(
                "Tag people",
                participant_options,
                default=[],
                placeholder="Select people to tag...",
                key=meeting_tags_key,
            )
            meeting_attendance = st.multiselect(
                "Attendance",
                participant_options,
                default=[],
                placeholder="Select attendants who joined...",
                key=meeting_attendance_key,
            )

            # -----------------------------------------------------------
            # MEETING RECORD — retained for normal meeting documentation.
            # -----------------------------------------------------------
            meeting_actions_key = f"meeting_actions_{task_id}"
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
                                    },
                                    "collaboration_history": {
                                        "$each": [{
                                            "action": meeting_history,
                                            "timestamp": now,
                                            "actor": assigned_to or "Caseflow",
                                            "station": department,
                                            "type": "meeting",
                                        }],
                                        "$slice": -100,
                                    },
                                },
                                "$set": {
                                    "last_update": now,
                                    "history": history,
                                },
                            },
                        )
                        clear_task_cache()
                        st.success("Meeting record saved to Collaboration History.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Unable to save the meeting record: {exc}")

            meetings = task.get("meetings") or []
            if isinstance(meetings, list) and meetings:
                st.markdown("<div class='communication-section-label'>Recorded Collaboration Meetings</div>", unsafe_allow_html=True)
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

            st.markdown("<div class='communication-section-label'>Collaboration History</div>", unsafe_allow_html=True)
            collaboration_history = task.get("collaboration_history") or []
            communications = task.get("communications") or task.get("communication_history") or []
            combined_collaboration = []
            if isinstance(collaboration_history, list):
                combined_collaboration.extend(collaboration_history)
            if isinstance(communications, list):
                combined_collaboration.extend(communications)
            if isinstance(combined_collaboration, list) and combined_collaboration:
                for item in reversed(combined_collaboration[-50:]):
                    if isinstance(item, dict):
                        sender = text(item.get("sender") or item.get("user") or item.get("from") or item.get("actor")) or "Caseflow User"
                        body = text(item.get("message") or item.get("body") or item.get("details") or item.get("action")) or "—"
                        stamp = dt_display(item.get("timestamp") or item.get("created_at"))
                    else:
                        sender, body, stamp = "Caseflow User", text(item), ""
                    st.markdown(
                        f"<div class='communication-card'><div class='communication-head'><strong>{html.escape(sender)}</strong><span>{html.escape(stamp)}</span></div><div>{html.escape(body).replace(chr(10), '<br>')}</div></div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No collaboration history is stored on this case.")
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


    # Duration/data monitoring remains in the 1-second fragment.
    # Simulation state is shared through MongoDB so every connected user
    # receives the same H&M critical-account alert after the 5-second delay.
    global_simulation = _get_global_simulation_event()
    session_started_at = as_utc(
        st.session_state.get("app_session_started_at")
    ) or utc_now()

    if global_simulation:
        global_task_id = str(global_simulation.get("task_id") or "")
        global_triggered_at = as_utc(global_simulation.get("triggered_at"))
        global_event_id = f"{global_task_id}:{iso_z(global_triggered_at)}"

        # Alert_Collection is shared across users, so the event intentionally
        # remains available to sessions that were already open when Simulation
        # was triggered.  A newly opened/reopened browser session must NOT
        # resurrect an old simulation alert just because the global event is
        # still stored in MongoDB.
        event_belongs_to_session = bool(
            global_triggered_at
            and global_triggered_at >= session_started_at
        )

        if event_belongs_to_session:
            if st.session_state.get("simulation_alert_event_id") != global_event_id:
                already_seen = _simulation_event_seen(global_event_id)
                st.session_state["simulation_alert_event_id"] = global_event_id
                st.session_state["simulation_alert_case_id"] = global_task_id or None
                st.session_state["simulation_alert_dismissed"] = bool(already_seen)
                st.session_state["simulation_alert_active"] = False
                st.session_state["simulation_alert_delay_until"] = (
                    0.0
                    if already_seen
                    else (
                        global_triggered_at.timestamp() + 5.0
                        if global_triggered_at
                        else 0.0
                    )
                )

    simulation_delay_until = float(
        st.session_state.get("simulation_alert_delay_until", 0.0) or 0.0
    )
    if (
        simulation_delay_until
        and time.time() >= simulation_delay_until
        and st.session_state.get("simulation_alert_case_id")
        and not st.session_state.get("simulation_alert_active")
        and not st.session_state.get("simulation_alert_dismissed")
    ):
        st.session_state["simulation_alert_active"] = True
        st.session_state["simulation_alert_delay_until"] = 0.0
        st.rerun(scope="app")


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


    # Alerts reuse the state map above so the 1-second monitoring fragment
    # performs only one calculate_state pass per active case.
    scan_alerts(tasks, states=states, now=now)


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
        # Nearing due = 40%-remaining SLA warning, strictly BEFORE breach.
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
        # A tile flashes RED as soon as at least one case reaches the
        # 40%-remaining threshold for this station. There is no amber tile
        # animation; the amber warning is represented only beside Duration.
        warning_condition = (nearing > 0 or past_due > 0)
        red_warning = any(
            state.get("elapsed", 0) >= (
                STATIONS[station]["sla_minutes"] * 60 * 0.60
            )
            for state in station_states
        )
        # Station tiles only flash when a case reaches the red/critical window.
        # The 40%-remaining amber warning is shown in the Duration column only.
        warning_tone_class = " red" if red_warning else ""
        warning_pairs = [
            (task, state)
            for task, state in zip(station_tasks, station_states)
            if state.get("nearing_due", False) or state.get("past_due", False)
        ]
        unacknowledged_warning_tasks = [
            task for task, _state in warning_pairs
            if text(task.get("station_warning_ack_trigger")) != station_warning_trigger_key(task, station)
        ]
        # Persisted per-case acknowledgement is authoritative; no local
        # station-level latch is needed.

        # Persisted per-case warning-cycle acknowledgement means a refresh
        # cannot resurrect an alert that the user already clicked. A new case
        # entering warning, or the same case entering a new station cycle, gets
        # a new trigger key and can alert again.
        flash_tile = bool(unacknowledged_warning_tasks and red_warning)


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
            critical_class = " critical-red" if (flash_tile and red_warning) else ""
            selected_class = " selected" if selected == station else ""
            alert_icon = (
                '<div class="station-alert-icon red" aria-label="Critical SLA warning">!</div>'
                if flash_tile and red_warning else ""
            )


            # The visual card remains the reference design. A transparent
            # Streamlit button is layered over the entire card so ONE click
            # anywhere on the tile changes the station filter.
            with st.container(key=f"station_wrap_{slug}"):
                # Keep this HTML as one physical markdown line. Streamlit's
                # Markdown parser can otherwise interpret indented multiline
                # HTML as a code block and expose the raw tags.
                station_html = (
                    f'<div class="station-card-visual {slug}{critical_class}{warning_tone_class}{selected_class}" '
                    f'data-station="{html.escape(station)}" '
                    f'data-warning-stop="0">'
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
                        acknowledge_station_warning_cycle(unacknowledged_warning_tasks)
                        acknowledge_station_alerts(
                            station,
                            trigger_keys={
                                station_warning_trigger_key(task, station)
                                for task in unacknowledged_warning_tasks
                            },
                        )


                    # The station button itself already triggers the fragment
                    # rerun. Do not force a second fragment rerun here; that
                    # duplicate render makes tile switching feel less smooth.
                    st.session_state["selected_station"] = station


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
            # H&M is the simulated critical-account case and must remain
            # pinned above every other CARE case, including cases that are
            # nearing breach or already breached.
            0 if text(task.get("account_name")).strip().upper() == "H&M" else 1,
            0 if is_priority(task.get("account_priority")) else 1,
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
            key=lambda task: (
                0 if states[str(task["_id"])]["priority_account"] else 1,
                -states[str(task["_id"])]["elapsed"],
                text(task.get("case_number")),
            )
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


        priority_text = display_priority_label(state)


        priority_class = {
            "Critical": "priority-critical",
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


            st.markdown(
                f"""
                <div class="case-row">
                    <span class="priority-pill {priority_slug}">
                        {html.escape(priority_text)}
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
            # green = safely on time, amber = warning window (40% remaining),
            # red = final 20% / breach.
            warning_threshold_seconds = sla_for_case * 0.60
            elapsed_ratio = (state["elapsed"] / sla_for_case) if sla_for_case else 1.0
            if elapsed_ratio < 0.60:
                duration_color_class = "duration-green"
            elif elapsed_ratio < 0.80:
                duration_color_class = "duration-yellow"
            else:
                duration_color_class = "duration-red"


            case_ack_until = 0.0


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
                        <span
                            class="duration-alert-icon {'red' if elapsed_ratio >= 0.80 else 'amber' if elapsed_ratio >= 0.60 else 'hidden'}"
                            data-duration-alert-icon="1"
                            aria-label="SLA warning">!</span>
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
                    // Each row carries its station-specific SLA, so 40% remaining
                    // is always evaluated against the correct station timeframe.
                    wrap.classList.toggle("duration-green", ratio < 0.60);
                    wrap.classList.toggle("duration-yellow", ratio >= 0.60 && ratio < 0.80);
                    wrap.classList.toggle("duration-red", ratio >= 0.80);
                    wrap.classList.toggle("duration-warning-active", ratio >= 0.80 && ratio < 1.0);

                    const alertIcon = wrap.querySelector('[data-duration-alert-icon="1"]');
                    if (alertIcon) {
                        const amberWarning = ratio >= 0.60 && ratio < 0.80;
                        const redWarning = ratio >= 0.80;
                        alertIcon.classList.toggle("amber", amberWarning);
                        alertIcon.classList.toggle("red", redWarning);
                        alertIcon.classList.toggle("hidden", !amberWarning && !redWarning);
                    }
                });
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
                                card.classList.remove("critical", "critical-red", "critical-amber", "warning-amber", "warning-red");
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


            /*
             * Keep Duration and Total Elapsed completely browser-side.
             * Do not depend on the Streamlit fragment cadence.  The dashboard
             * may refresh independently for alerts/data, but these clocks are
             * driven from the browser clock and repaint on the exact second.
             */
            if (!window.__taskTrackerDurationLoop) {
                window.__taskTrackerDurationLoop = true;

                /*
                 * Duration and Total Elapsed are true 1-second browser clocks.
                 * They do NOT wait for the Streamlit fragment/data refresh.
                 * A dedicated 1000 ms interval keeps the counters independent
                 * from MongoDB/cache timing.
                 */
                const refreshDurationClocks = function () {
                    updateDurations();
                    updateTotalElapsed();
                };

                window.__taskTrackerDurationInterval = window.setInterval(
                    refreshDurationClocks,
                    1000
                );

                /*
                 * Streamlit may replace the fragment DOM on its normal
                 * 1-second data refresh. Repaint any newly inserted
                 * Duration / Total Elapsed nodes immediately from the browser
                 * clock so those data refreshes never become the visible timer.
                 */
                if (!window.__taskTrackerDurationObserver) {
                    let durationDomRefreshQueued = false;
                    window.__taskTrackerDurationObserver = new MutationObserver(function (mutations) {
                        /* Streamlit can replace many nodes during a fragment refresh.
                           Coalesce that burst into one browser paint instead of
                           recalculating every mutation. The 1000 ms interval remains
                           the authoritative Duration/Total Elapsed refresh. */
                        if (durationDomRefreshQueued) return;
                        const relevant = mutations.some(function (mutation) {
                            return Array.from(mutation.addedNodes || []).some(function (node) {
                                return node.nodeType === 1 && (
                                    node.matches?.('[data-duration-live="1"], [data-total-elapsed-live="1"]') ||
                                    node.querySelector?.('[data-duration-live="1"], [data-total-elapsed-live="1"]')
                                );
                            });
                        });
                        if (!relevant) return;
                        durationDomRefreshQueued = true;
                        window.requestAnimationFrame(function () {
                            durationDomRefreshQueued = false;
                            updateDurations();
                            updateTotalElapsed();
                        });
                    });
                    window.__taskTrackerDurationObserver.observe(document.body, {
                        childList: true,
                        subtree: true
                    });
                }

                refreshDurationClocks();
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
# SIMULATION ALERT OVERLAY — visual reference inspired by the supplied image
# ============================================================
st.markdown(
    """
    <style>
    [class*="st-key-simulation_alert_overlay"] {
        position:fixed !important;
        inset:0 !important;
        z-index:999999 !important;
        width:100vw !important;
        height:100vh !important;
        max-width:none !important;
        margin:0 !important;
        padding:0 !important;
        display:flex !important;
        align-items:center !important;
        justify-content:center !important;
        background:rgba(15,27,39,.58) !important;
        backdrop-filter:blur(2px) !important;
        pointer-events:auto !important;
    }
    [class*="st-key-simulation_alert_overlay"] > div {
        width:100% !important;
        height:100% !important;
        display:flex !important;
        align-items:center !important;
        justify-content:center !important;
    }
    [class*="st-key-simulation_alert_overlay"] .simulation-alert-card {
        width:min(490px, calc(100vw - 34px));
        box-sizing:border-box;
        background:#fff;
        border:1px solid #e5e9ef;
        border-radius:14px;
        padding:24px 24px 18px;
        box-shadow:0 28px 90px rgba(0,0,0,.30);
    }
    [class*="st-key-simulation_alert_overlay"] .simulation-alert-card.simulation-alert-flashing {
        animation:simulationAlertPulse .72s ease-in-out infinite alternate;
    }
    .simulation-alert-header {
        display:flex;
        align-items:flex-start;
        gap:14px;
    }
    .simulation-alert-icon {
        width:54px;
        height:54px;
        min-width:54px;
        border-radius:50%;
        background:#ef1738;
        color:#fff;
        display:flex;
        align-items:center;
        justify-content:center;
        font-size:34px;
        font-weight:900;
        line-height:1;
        box-shadow:0 0 0 6px rgba(239,23,56,.12);
    }
    .simulation-alert-icon.simulation-alert-blinking {
        animation:simulationAlertIconBlink .42s ease-in-out infinite alternate;
    }
    .simulation-alert-title {
        color:#e51c3a;
        font-size:21px;
        font-weight:900;
        line-height:1.15;
        margin-top:2px;
    }
    .simulation-alert-subtitle {
        color:#526078;
        font-size:12px;
        line-height:1.4;
        margin-top:6px;
    }
    .simulation-alert-details {
        margin-top:16px;
        padding:13px 15px;
        background:#fff0f2;
        border-radius:8px;
        border:1px solid #ffd9df;
    }
    .simulation-alert-row {
        display:grid;
        grid-template-columns:105px 1fr;
        gap:8px;
        padding:4px 0;
        color:#334155;
        font-size:11px;
    }
    .simulation-alert-row strong { color:#102041; font-weight:800; }
    .simulation-alert-critical {
        display:inline-block;
        color:#fff;
        background:#ef1738;
        border-radius:5px;
        padding:3px 8px;
        font-weight:850;
    }
    [class*="st-key-simulation_alert_overlay"] [data-testid="stButton"] {
        width:min(490px, calc(100vw - 34px)) !important;
        margin-top:12px !important;
    }
    [class*="st-key-simulation_alert_overlay"] [data-testid="stButton"] button {
        width:100% !important;
        height:42px !important;
        border-radius:8px !important;
        background:#ef1738 !important;
        border:1px solid #ef1738 !important;
        color:#fff !important;
        font-weight:850 !important;
        font-size:12px !important;
        box-shadow:0 7px 18px rgba(239,23,56,.22) !important;
    }
    [class*="st-key-simulation_alert_overlay"] [data-testid="stButton"] button:hover {
        background:#d91531 !important;
        border-color:#d91531 !important;
    }
    @keyframes simulationAlertPulse {
        from { transform:scale(1); box-shadow:0 28px 90px rgba(0,0,0,.30); }
        to { transform:scale(1.012); box-shadow:0 28px 105px rgba(239,23,56,.16), 0 28px 90px rgba(0,0,0,.30); }
    }
    @keyframes simulationAlertIconBlink {
        from { opacity:.55; transform:scale(.88); }
        to { opacity:1; transform:scale(1.08); }
    }
    .kb-sop-list-spacer { height:8px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# The delayed simulation alert is triggered by the 1-second dashboard
# fragment above. No browser-injected script is required.


# ============================================================
# COLLABORATION / ACTIVE WAR ROOM ENHANCEMENTS
# ============================================================
st.markdown(r"""
<style>
div[data-testid="stDialog"] .active-war-room {
    border-color:#00a98f !important;
    background:linear-gradient(135deg,#f7fffc,#eefbf8) !important;
}
div[data-testid="stDialog"] .active-war-room:hover {
    border-color:#008f80 !important;
    box-shadow:0 0 0 2px rgba(0,169,143,.10), 0 7px 20px rgba(0,74,72,.08) !important;
}
div[data-testid="stDialog"] [class*="st-key-active_war_room_tile_"] {
    position:relative !important;
    min-height:88px !important;
    margin:0 0 4px !important;
    padding:0 !important;
}
div[data-testid="stDialog"] [class*="st-key-active_war_room_tile_"] [class*="st-key-active_war_room_toggle_"] {
    position:absolute !important;
    inset:0 !important;
    z-index:30 !important;
    margin:0 !important;
    padding:0 !important;
}
div[data-testid="stDialog"] [class*="st-key-active_war_room_tile_"] [class*="st-key-active_war_room_toggle_"] button {
    position:absolute !important;
    inset:0 !important;
    width:100% !important;
    height:100% !important;
    background:transparent !important;
    border:0 !important;
    color:transparent !important;
    box-shadow:none !important;
    opacity:.001 !important;
    cursor:pointer !important;
}
div[data-testid="stDialog"] .active-war-room-expanded {
    border-color:#9ed9d0 !important;
    background:#f4fcfa !important;
}
div[data-testid="stDialog"] .simulation-collab-card {
    border:1px solid #b9e3db !important;
    border-radius:9px !important;
    background:linear-gradient(145deg,#f4fffc,#ffffff) !important;
    padding:10px !important;
    margin:0 0 8px !important;
    box-shadow:0 5px 18px rgba(0,79,74,.07) !important;
}
div[data-testid="stDialog"] .simulation-collab-head {
    display:flex !important;
    align-items:flex-start !important;
    justify-content:space-between !important;
    gap:10px !important;
}
div[data-testid="stDialog"] .simulation-live-dot {
    display:inline-block !important;
    width:7px !important;
    height:7px !important;
    margin-right:5px !important;
    border-radius:50% !important;
    background:#ef334f !important;
    box-shadow:0 0 0 3px rgba(239,51,79,.12) !important;
    animation:simulationLivePulse .75s ease-in-out infinite alternate !important;
}
div[data-testid="stDialog"] .simulation-collab-title {
    margin-top:3px !important;
    color:#102041 !important;
    font-size:11px !important;
    font-weight:850 !important;
}
div[data-testid="stDialog"] .simulation-session-badge {
    background:#e7faf5 !important;
    color:#087b71 !important;
    border:1px solid #b8e8dc !important;
    border-radius:999px !important;
    padding:3px 7px !important;
    font-size:7px !important;
    font-weight:900 !important;
}
div[data-testid="stDialog"] .simulation-video-grid {
    display:grid !important;
    grid-template-columns:repeat(4,minmax(0,1fr)) !important;
    gap:5px !important;
    margin-top:8px !important;
}
div[data-testid="stDialog"] .simulation-video-tile {
    min-height:58px !important;
    border-radius:6px !important;
    background:linear-gradient(145deg,#152b40,#28465c) !important;
    color:#fff !important;
    padding:7px !important;
    position:relative !important;
    overflow:hidden !important;
}
div[data-testid="stDialog"] .simulation-video-avatar {
    width:23px !important;
    height:23px !important;
    border-radius:50% !important;
    display:flex !important;
    align-items:center !important;
    justify-content:center !important;
    background:#00a98f !important;
    color:#fff !important;
    font-size:9px !important;
    font-weight:900 !important;
}
div[data-testid="stDialog"] .simulation-video-name {
    margin-top:6px !important;
    font-size:7.5px !important;
    font-weight:750 !important;
    white-space:nowrap !important;
    overflow:hidden !important;
    text-overflow:ellipsis !important;
}
div[data-testid="stDialog"] .simulation-video-status {
    margin-top:2px !important;
    color:#8ff1d6 !important;
    font-size:6.5px !important;
}
div[data-testid="stDialog"] .simulation-collab-grid {
    display:grid !important;
    grid-template-columns:1fr 1fr !important;
    gap:8px !important;
    margin-top:8px !important;
}
div[data-testid="stDialog"] .simulation-collab-copy {
    color:#263957 !important;
    font-size:8.5px !important;
    line-height:1.4 !important;
    background:#fff !important;
    border:1px solid #e0ece9 !important;
    border-radius:5px !important;
    padding:6px 7px !important;
}
div[data-testid="stDialog"] .simulation-collab-footer {
    display:flex !important;
    justify-content:space-between !important;
    gap:8px !important;
    margin-top:7px !important;
    color:#73819a !important;
    font-size:7px !important;
}
div[data-testid="stDialog"] .simulation-collab-footer a {
    color:#0879c9 !important;
    font-weight:800 !important;
    text-decoration:none !important;
}
@keyframes simulationLivePulse {
    from { opacity:.45; transform:scale(.8); }
    to { opacity:1; transform:scale(1.15); }
}
@media (max-width:700px) {
    div[data-testid="stDialog"] .simulation-video-grid {
        grid-template-columns:repeat(2,minmax(0,1fr)) !important;
    }
    div[data-testid="stDialog"] .simulation-collab-grid {
        grid-template-columns:1fr !important;
    }
}
</style>
""", unsafe_allow_html=True)

# ============================================================
# SIMULATION CRITICAL ACCOUNT ALERT
# ============================================================
if (
    st.session_state.get("simulation_alert_case_id")
    and not st.session_state.get("simulation_alert_dismissed")
    and bool(get_alert_definition("SIMULATION_CRITICAL").get("popup_enabled", True))
):
    simulation_alert_case_id = st.session_state.get("simulation_alert_case_id")
    try:
        from bson import ObjectId
        simulation_alert_task = col(TASKS_COLLECTION).find_one(
            {"_id": ObjectId(str(simulation_alert_case_id))}
        ) or {}
    except Exception:
        simulation_alert_task = {}

    if simulation_alert_task:
        simulation_alert_definition = get_alert_definition("SIMULATION_CRITICAL")
        simulation_sound_b64 = text(simulation_alert_definition.get("sound_data_b64"))
        simulation_sound_mime = text(simulation_alert_definition.get("sound_mime")) or "audio/mpeg"
        simulation_sound_src = (
            f"data:{simulation_sound_mime};base64,{simulation_sound_b64}"
            if simulation_sound_b64
            else f"data:audio/mpeg;base64,{SIMULATION_ALERT_SOUND_B64}"
        )
        simulation_alert_flash_class = " simulation-alert-flashing" if bool(simulation_alert_definition.get("flashing_enabled", True)) else ""
        simulation_alert_blink_class = " simulation-alert-blinking" if bool(simulation_alert_definition.get("blinking_enabled", True)) else ""
        simulation_alert_icon = html.escape(text(simulation_alert_definition.get("icon")) or "!")
        simulation_case_number = text(simulation_alert_task.get("case_number")) or "—"
        simulation_subject = text(simulation_alert_task.get("subject")) or text(simulation_alert_task.get("issue")) or "Critical account simulation"
        simulation_assignee = text(simulation_alert_task.get("assigned_to")) or "Unassigned"
        simulation_account = text(simulation_alert_task.get("account_name")) or "H&M"
        simulation_due = dt_display(simulation_alert_task.get("due_date")) or "Today"
        with st.container(key="simulation_alert_overlay"):
            simulation_delay_until = float(
                st.session_state.get("simulation_alert_delay_until", 0.0) or 0.0
            )
            st.markdown(
                f"""
                <div class="simulation-alert-delay-marker"
                     data-alert-delay-until="{simulation_delay_until:.3f}"></div>
                {f'<audio id="simulation-critical-alert-sound" autoplay preload="auto" style="display:none"><source src="{simulation_sound_src}" type="{html.escape(simulation_sound_mime)}"></audio><script>(function(){{var a=document.getElementById("simulation-critical-alert-sound");if(a){{a.volume=1.0;a.currentTime=0;var p=a.play();if(p&&p.catch)p.catch(function(){{}});}}}})();</script>' if bool(simulation_alert_definition.get("sound_enabled", True)) else ''}
                <div class="simulation-alert-card{simulation_alert_flash_class}">
                    <div class="simulation-alert-header">
                        <div class="simulation-alert-icon{simulation_alert_blink_class}">{simulation_alert_icon}</div>
                        <div>
                            <div class="simulation-alert-title">{html.escape(text(simulation_alert_definition.get("title")) or "Critical Case Alert")}</div>
                            <div class="simulation-alert-subtitle">
                                {html.escape(text(simulation_alert_definition.get("subtitle")) or "The following high priority account requires immediate attention and is still not resolved.")}
                            </div>
                        </div>
                    </div>
                    <div class="simulation-alert-details">
                        <div class="simulation-alert-row"><span>Case #</span><strong>{html.escape(simulation_case_number)}</strong></div>
                        <div class="simulation-alert-row"><span>Subject</span><strong>{html.escape(simulation_subject)}</strong></div>
                        <div class="simulation-alert-row"><span>Account</span><strong>{html.escape(simulation_account)}</strong></div>
                        <div class="simulation-alert-row"><span>Assigned To</span><strong>{html.escape(simulation_assignee)}</strong></div>
                        <div class="simulation-alert-row"><span>Priority</span><strong><span class="simulation-alert-critical">Critical</span></strong></div>
                        <div class="simulation-alert-row"><span>Due Date</span><strong style="color:#e51c3a">{html.escape(simulation_due)}</strong></div>
                        <div class="simulation-alert-row"><span>Current Status</span><strong>{html.escape(text(simulation_alert_task.get("status")) or "In Progress")}</strong></div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(
                "View Case",
                type="primary",
                use_container_width=True,
                key="simulation_alert_view_case",
            ):
                st.session_state["simulation_alert_active"] = False
                st.session_state["simulation_alert_dismissed"] = True
                st.session_state["simulation_alert_delay_until"] = 0.0
                current_event_id = st.session_state.get("simulation_alert_event_id")
                if current_event_id:
                    _mark_simulation_event_seen(current_event_id)
                st.session_state["selected_station"] = "CARE"
                st.session_state["open_case_after_alert"] = True

                # The alert represents a NEW case entering CARE. Reset both
                # the station timer and SLA due date at the exact moment the
                # user opens it, so Total Elapsed and Duration begin at 00:00.
                # The account remains a high-priority account independently of
                # the newly reset timer.
                transition_now = utc_now()
                care_sla = timedelta(minutes=STATIONS["CARE"]["sla_minutes"])
                try:
                    # Only the first View Case converts the hidden simulation
                    # placeholder into a new CARE case and starts its timer.
                    first_view = bool(simulation_alert_task.get("simulation_hold"))
                    update_set = {
                        "active": True,
                        "simulation_hold": False,
                        "account_name": "H&M",
                        "account_priority": "Yes",
                        "priority": "Critical",
                        "department": "CARE",
                        "status": "In Progress",
                        "last_update": transition_now,
                    }
                    if first_view:
                        update_set["station_started_at"] = transition_now
                        update_set["due_date"] = transition_now + care_sla

                    col(TASKS_COLLECTION).update_one(
                        {
                            "_id": simulation_alert_task.get("_id"),
                            **({"simulation_hold": True} if first_view else {}),
                        },
                        {
                            "$set": update_set,
                            "$unset": {"simulation_hold": ""},
                        },
                    )

                    clear_task_cache()

                except Exception:
                    pass
                try:
                    col(ALERT_COLLECTION).update_many(
                        {
                            "task_id": str(simulation_alert_case_id),
                            "alert_type": "PRIORITY_ACCOUNT",
                            "acknowledged": False,
                        },
                        {"$set": {"acknowledged": True, "acknowledged_at": utc_now()}},
                    )
                except Exception:
                    pass

                # Open Case Details on a clean application render. Calling the
                # native dialog directly from the alert button interaction can
                # race the alert's own rerender and cause the dialog to require
                # a second click or briefly reopen/close. A one-shot pending id
                # avoids that race while keeping the transition immediate.
                st.session_state["pending_case_dialog_id"] = str(simulation_alert_case_id)
                st.rerun(scope="app")

# Open the simulated H&M case exactly once on the clean render following
# View Case. The alert was already dismissed in the previous interaction,
# so there is no second alert/dialog invocation competing with this call.
pending_case_dialog_id = st.session_state.pop("pending_case_dialog_id", None)
if pending_case_dialog_id:
    case_details(str(pending_case_dialog_id))
    st.stop()

# ============================================================
# SIMULATION CLEANUP
# ============================================================
# Simulation state is persisted globally in Alert_Collection.


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


st.markdown(r"""
<style>
/* ============================================================
   MOBILE-FRIENDLY EXCEL UPLOAD TILE
   The entire visible tile is the native file-picker hit area.
   Do not display a second "Upload" label/button over the tile.
   ============================================================ */
div[data-testid="stDialog"] [data-testid="stFileUploader"] {
    width:100% !important;
    margin:8px 0 12px !important;
}
div[data-testid="stDialog"] [data-testid="stFileUploader"] > label {
    display:none !important;
}
div[data-testid="stDialog"] [data-testid="stFileUploader"] section {
    position:relative !important;
    width:100% !important;
    min-height:74px !important;
    height:74px !important;
    box-sizing:border-box !important;
    margin:0 !important;
    padding:0 !important;
    border:1.5px dashed #b8c9d7 !important;
    border-radius:12px !important;
    background:linear-gradient(180deg,#fbfdff,#f5f9fc) !important;
    display:flex !important;
    align-items:center !important;
    justify-content:center !important;
    overflow:hidden !important;
    cursor:pointer !important;
    transition:border-color .15s ease, background .15s ease, box-shadow .15s ease !important;
}
div[data-testid="stDialog"] [data-testid="stFileUploader"] section:hover {
    border-color:#0879c9 !important;
    background:#f3f9fd !important;
    box-shadow:0 2px 10px rgba(8,121,201,.08) !important;
}
/* One visual label only. The native file button is made invisible but
   remains the full-size touch/click target, so tapping anywhere on the tile
   opens the device/browser file picker. */
div[data-testid="stDialog"] [data-testid="stFileUploader"] section::before {
    content:"Upload Excel file" !important;
    position:absolute !important;
    inset:0 !important;
    z-index:1 !important;
    display:flex !important;
    align-items:center !important;
    justify-content:center !important;
    color:#486173 !important;
    font-size:12px !important;
    font-weight:700 !important;
    letter-spacing:.1px !important;
    pointer-events:none !important;
}
div[data-testid="stDialog"] [data-testid="stFileUploader"] section button {
    position:absolute !important;
    inset:0 !important;
    z-index:5 !important;
    width:100% !important;
    height:100% !important;
    min-width:100% !important;
    min-height:100% !important;
    margin:0 !important;
    padding:0 !important;
    border:0 !important;
    border-radius:12px !important;
    background:transparent !important;
    box-shadow:none !important;
    opacity:.001 !important;
    color:transparent !important;
    font-size:1px !important;
    cursor:pointer !important;
}
div[data-testid="stDialog"] [data-testid="stFileUploader"] section button *,
div[data-testid="stDialog"] [data-testid="stFileUploader"] section [data-testid="stFileUploaderDropzoneInstructions"] {
    opacity:0 !important;
    pointer-events:none !important;
}
/* Keep selected-file text readable below/around the native tile without
   bringing back the duplicate Upload text. */
div[data-testid="stDialog"] [data-testid="stFileUploader"] small {
    font-size:10px !important;
}
@media (max-width: 900px) {
    div[data-testid="stDialog"] [data-testid="stFileUploader"] section {
        min-height:64px !important;
        height:64px !important;
        border-radius:11px !important;
    }
    div[data-testid="stDialog"] [data-testid="stFileUploader"] section::before {
        font-size:12px !important;
    }
}
</style>
""", unsafe_allow_html=True)


st.markdown(r"""
<style>
/* ============================================================
   CHECKLIST REFRESH — restored manual synchronization control
   ============================================================ */
div[data-testid="stDialog"] [class*="st-key-case_checklist_refresh_"] {
    display:flex !important;
    justify-content:flex-end !important;
    align-items:flex-start !important;
    margin:0 !important;
    padding:0 !important;
}
div[data-testid="stDialog"] [class*="st-key-case_checklist_refresh_"] button {
    width:30px !important;
    min-width:30px !important;
    height:30px !important;
    min-height:30px !important;
    padding:0 !important;
    margin:0 !important;
    border:1px solid #dce5ef !important;
    border-radius:6px !important;
    background:#fff !important;
    color:#0879c9 !important;
    font-size:17px !important;
    line-height:1 !important;
    box-shadow:none !important;
}
div[data-testid="stDialog"] [class*="st-key-case_checklist_refresh_"] button:hover {
    background:#eef8ff !important;
    border-color:#0879c9 !important;
}
</style>
""", unsafe_allow_html=True)



st.markdown(r"""
<style>
/* ============================================================
   CASE DETAILS — UNIFORM BODY TYPOGRAPHY
   Keep only the modal title, case number and subject as headers.
   All other Case Details text uses one consistent Inter size.
   ============================================================ */
div[data-testid="stDialog"] [data-testid="stDialogContent"] * {
    font-family:"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
    font-size:10px !important;
}

/* Dialog header and Case Details hero remain intentionally larger. */
div[data-testid="stDialog"] header p {
    font-size:16px !important;
    line-height:1.1 !important;
}
div[data-testid="stDialog"] .case-detail-case-number {
    font-size:14px !important;
    line-height:1.1 !important;
}
div[data-testid="stDialog"] .case-detail-subject {
    font-size:11px !important;
    line-height:1.2 !important;
}

/* Preserve icon sizing so typography normalization does not shrink visual icons. */
div[data-testid="stDialog"] .case-folder-icon,
div[data-testid="stDialog"] .case-copy-icon,
div[data-testid="stDialog"] .case-timing-icon,
div[data-testid="stDialog"] .case-heading-icon {
    line-height:1 !important;
}
</style>
""", unsafe_allow_html=True)


st.markdown(r"""
<style>
/* ============================================================
   CASE DETAILS — FINAL TYPOGRAPHY + COMPACT DROPDOWN PATCH
   Keep Case Information / Attachments aligned with the same
   Inter 10px body typography used by the rest of the dialog.
   Header and case-detail hero remain larger.
   ============================================================ */

/* Case Information rows */
div[data-testid="stDialog"] [role="tabpanel"] .case-info-row,
div[data-testid="stDialog"] [role="tabpanel"] .case-info-row * {
    font-family:"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
    font-size:10px !important;
    line-height:1.3 !important;
}

/* Attachments rows */
div[data-testid="stDialog"] [role="tabpanel"] .attachment-row,
div[data-testid="stDialog"] [role="tabpanel"] .attachment-row * {
    font-family:"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
    font-size:10px !important;
    line-height:1.3 !important;
}

/* Keep the card headings as headings, rather than flattening them into body text. */
div[data-testid="stDialog"] [role="tabpanel"] .case-card-heading,
div[data-testid="stDialog"] [role="tabpanel"] .case-card-heading * {
    font-family:"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
}

/* Remove Streamlit/BaseWeb selectbox whitespace above and below the label/value. */
div[data-testid="stDialog"] [data-testid="stSelectbox"],
div[data-testid="stDialog"] [data-testid="stSelectbox"] > div,
div[data-testid="stDialog"] [data-testid="stSelectbox"] label,
div[data-testid="stDialog"] [data-testid="stSelectbox"] [data-baseweb="select"] {
    margin:0 !important;
    padding:0 !important;
}

div[data-testid="stDialog"] [data-testid="stSelectbox"] label {
    display:block !important;
    height:auto !important;
    min-height:0 !important;
    margin:0 0 1px !important;
    line-height:1 !important;
    font-size:8px !important;
}

div[data-testid="stDialog"] [data-testid="stSelectbox"] [data-baseweb="select"],
div[data-testid="stDialog"] [data-testid="stSelectbox"] [data-baseweb="select"] > div,
div[data-testid="stDialog"] [data-testid="stSelectbox"] [data-baseweb="select"] [role="combobox"] {
    min-height:24px !important;
    height:24px !important;
    box-sizing:border-box !important;
}

div[data-testid="stDialog"] [data-testid="stSelectbox"] [data-baseweb="select"] > div {
    padding:0 6px !important;
}

div[data-testid="stDialog"] [data-testid="stSelectbox"] [data-baseweb="select"] span {
    font-family:"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
    font-size:8px !important;
    line-height:22px !important;
}
</style>
""", unsafe_allow_html=True)
