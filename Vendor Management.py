"""
HPE CASEFLOW - UPDATED SINGLE-FILE STREAMLIT APP

Changes requested:
1. Case Details now follows the supplied visual reference and contains an
   integrated, functional Knowledge Base section.
2. The temporary "Simulate Critical Alert" case/functionality is removed.
3. Exactly 5 mock cases are maintained per station (25 total).
4. The Settings > Simulation tab keeps only:
      Reset Mock Case Durations to 00:00:00
5. Existing dashboard, MongoDB, Excel import, vendor sync, persistent access,
   station filtering, browser-side duration timer, alerts, transfer and admin
   settings functionality are retained.

Required Streamlit Secrets:
MONGODB_URI = "mongodb+srv://..."
ACCESS_CODE = "..."
TOKEN_SECRET = "..."
ADMIN_PIN = "..."

Optional:
APP_NAME = "HPE Caseflow"

Install:
pip install streamlit pymongo pandas openpyxl itsdangerous streamlit-js-eval
"""

import hashlib
import hmac
import html
import os
import time
from datetime import datetime, timezone, timedelta

import pandas as pd
import streamlit as st
from pymongo import MongoClient, ASCENDING, DESCENDING, ReplaceOne
from pymongo.errors import PyMongoError

try:
    from itsdangerous import URLSafeTimedSerializer
except Exception:
    URLSafeTimedSerializer = None

try:
    from streamlit_js_eval import streamlit_js_eval
except Exception:
    streamlit_js_eval = None


# ============================================================
# PAGE / CONFIG
# ============================================================

st.set_page_config(
    page_title="HPE Caseflow",
    page_icon="⏱️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

APP_NAME = st.secrets.get("APP_NAME", "HPE Caseflow")
DB_NAME = "TeamRoster"

ROSTER_COLLECTION = "Team Roster Collection"
TASKS_COLLECTION = "Tasks_Collection"
VENDOR_COLLECTION = "Vendor_Collection"
ACCESS_COLLECTION = "Access_Collection"
ALERT_COLLECTION = "Alert_Collection"

# These collections are used by the integrated Case Details Knowledge Base.
KB_COLLECTION = "Knowledge_Base_Collection"
SOP_COLLECTION = "SOP_Collection"

TASK_CACHE_TTL = 0.5
KB_CACHE_TTL = 5.0
ALERT_SCAN_MIN_INTERVAL = 1.0

STATIONS = {
    "CARE": {"sla_minutes": 15, "icon": "♥", "accent": "#e51c3a", "soft": "#fff0f2"},
    "ARCH": {"sla_minutes": 30, "icon": "▣", "accent": "#0879c9", "soft": "#eaf7ff"},
    "PET": {"sla_minutes": 45, "icon": "●", "accent": "#087b58", "soft": "#ecfbf4"},
    "SUPPLY CHAIN": {"sla_minutes": 30, "icon": "◆", "accent": "#5d2ac9", "soft": "#f2edff"},
    "ONSITE": {"sla_minutes": 120, "icon": "▥", "accent": "#c98700", "soft": "#fff8df"},
}

STATUS_ORDER = {"BREACHED": 0, "CRITICAL": 1, "MEDIUM": 2, "LOW": 3}


# ============================================================
# DATABASE
# ============================================================

@st.cache_resource(show_spinner=False)
def get_mongo_client():
    uri = st.secrets.get("MONGODB_URI", "")
    if not uri:
        raise RuntimeError("MONGODB_URI is missing from Streamlit Secrets.")

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
    return get_mongo_client()[DB_NAME]


def col(name):
    return get_database()[name]


@st.cache_resource(show_spinner=False)
def initialize_indexes():
    try:
        col(TASKS_COLLECTION).create_index(
            [("active", ASCENDING), ("department", ASCENDING)]
        )
        col(TASKS_COLLECTION).create_index([("case_number", ASCENDING)])
        col(TASKS_COLLECTION).create_index([("assigned_to", ASCENDING)])
        col(VENDOR_COLLECTION).create_index([("vendor_key", ASCENDING)])
        col(ACCESS_COLLECTION).create_index([("token_hash", ASCENDING)])
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
# HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def as_utc(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
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
    return value.astimezone().strftime("%b %d, %Y %I:%M %p") if value else "—"


def iso_z(value):
    value = as_utc(value)
    return value.isoformat() if value else ""


def is_priority(value):
    return text(value).lower() in {
        "true", "yes", "y", "1", "priority", "high", "critical"
    }


def station_name(value):
    value = text(value).upper()
    return {
        "SUPPLYCHAIN": "SUPPLY CHAIN",
        "SUPPLY_CHAIN": "SUPPLY CHAIN",
        "SUPPLY": "SUPPLY CHAIN",
        "ON SITE": "ONSITE",
        "ON-SITE": "ONSITE",
    }.get(value, value)


def duration_string(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


# ============================================================
# PERSISTENT ACCESS
# ============================================================

ACCESS_STORAGE_KEY = "hpe_caseflow_authorized_v1"
AUTH_COOKIE_KEY = "hpe_caseflow_authorized_cookie_v1"


def _access_secrets():
    try:
        code = str(st.secrets.get("ACCESS_CODE", os.getenv("ACCESS_CODE", ""))).strip()
        secret = str(st.secrets.get("TOKEN_SECRET", os.getenv("TOKEN_SECRET", ""))).strip()
    except Exception:
        code = os.getenv("ACCESS_CODE", "").strip()
        secret = os.getenv("TOKEN_SECRET", "").strip()
    return code, secret


def _fingerprint(code):
    return hashlib.sha256(code.encode()).hexdigest()[:32]


def _serializer():
    if URLSafeTimedSerializer is None:
        return None
    code, secret = _access_secrets()
    if not code or not secret:
        return None
    return URLSafeTimedSerializer(
        secret,
        salt="hpe-caseflow-" + _fingerprint(code),
    )


def _make_token():
    serializer = _serializer()
    code, _ = _access_secrets()
    if not serializer or not code:
        return ""
    return serializer.dumps({"authorized": True, "fp": _fingerprint(code)})


def _valid_token(token):
    serializer = _serializer()
    code, _ = _access_secrets()
    if not serializer or not code or not token:
        return False
    try:
        payload = serializer.loads(str(token))
        return (
            payload.get("authorized") is True
            and hmac.compare_digest(
                str(payload.get("fp", "")),
                _fingerprint(code),
            )
        )
    except Exception:
        return False


def _js(expression, key):
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


def _read_token():
    try:
        cookies = getattr(getattr(st, "context", None), "cookies", None)
        if cookies and cookies.get(AUTH_COOKIE_KEY):
            return str(cookies.get(AUTH_COOKIE_KEY))
    except Exception:
        pass

    key = repr(ACCESS_STORAGE_KEY)
    return_value = _js(
        f"""
        (() => {{
            try {{
                const k={key};
                for (const s of [
                    window.top.localStorage,
                    window.parent.localStorage,
                    window.localStorage
                ]) {{
                    try {{
                        const v=s.getItem(k);
                        if(v) return v;
                    }} catch(e) {{}}
                }}
                try {{
                    const v=window.sessionStorage.getItem(k);
                    if(v) return v;
                }} catch(e) {{}}
                return "";
            }} catch(e) {{ return ""; }}
        }})()
        """,
        "caseflow_auth_read",
    )
    return None if return_value is None else str(return_value or "")


def _save_token(token):
    k = repr(ACCESS_STORAGE_KEY)
    ck = repr(AUTH_COOKIE_KEY)
    value = repr(token)
    result = _js(
        f"""
        (() => {{
            try {{
                const k={k}, ck={ck}, v={value};
                let saved=false;
                try {{
                    document.cookie=ck+"="+encodeURIComponent(v)+
                        "; Max-Age=31536000; Path=/; SameSite=Lax";
                    saved=true;
                }} catch(e) {{}}
                for (const s of [
                    window.top.localStorage,
                    window.parent.localStorage,
                    window.localStorage
                ]) {{
                    try {{ s.setItem(k,v); saved=true; }} catch(e) {{}}
                }}
                if(!saved) {{
                    try {{ window.sessionStorage.setItem(k,v); saved=true; }}
                    catch(e) {{}}
                }}
                return saved ? "saved" : "error";
            }} catch(e) {{ return "error"; }}
        }})()
        """,
        "caseflow_auth_save",
    )
    return result == "saved"


def _clear_token():
    k = repr(ACCESS_STORAGE_KEY)
    ck = repr(AUTH_COOKIE_KEY)
    _js(
        f"""
        (() => {{
            try {{
                document.cookie={ck}+"=; Max-Age=0; Path=/; SameSite=Lax";
                for (const s of [
                    window.top.localStorage,
                    window.parent.localStorage,
                    window.localStorage
                ]) {{
                    try {{ s.removeItem({k}); }} catch(e) {{}}
                }}
                try {{ window.sessionStorage.removeItem({k}); }} catch(e) {{}}
                return "cleared";
            }} catch(e) {{ return "error"; }}
        }})()
        """,
        "caseflow_auth_clear",
    )


def browser_authorized():
    if st.session_state.get("access_authorized"):
        return True

    token = _read_token()
    if token is None:
        return None

    if _valid_token(token):
        st.session_state["access_authorized"] = True
        return True

    return False


def access_gate():
    if URLSafeTimedSerializer is None or streamlit_js_eval is None:
        st.error("Install itsdangerous and streamlit-js-eval.")
        st.stop()

    code, secret = _access_secrets()
    if not code or not secret:
        st.error("ACCESS_CODE and TOKEN_SECRET are required in Streamlit Secrets.")
        st.stop()

    authorized = browser_authorized()

    if authorized is True:
        return True

    if authorized is None:
        st.markdown(
            "<div style='text-align:center;padding:20vh;color:#718099'>"
            "Restoring secure browser access…</div>",
            unsafe_allow_html=True,
        )
        st.stop()

    st.markdown(
        """
        <div style="max-width:560px;margin:12vh auto 0;background:#fff;
                    border:1px solid #e8edf4;border-radius:26px;padding:42px;
                    box-shadow:0 24px 70px rgba(20,38,70,.10);text-align:center">
            <div style="font-size:30px;font-weight:850;color:#102041">HPE Caseflow</div>
            <div style="color:#73819a;margin:10px 0 25px">
                Enter the one-time access code to continue.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    entered = st.text_input(
        "Access code",
        type="password",
        label_visibility="collapsed",
        placeholder="Enter access code",
    )

    if st.button("Access Tracker", type="primary", use_container_width=True):
        if hmac.compare_digest(entered, code):
            token = _make_token()
            if _save_token(token):
                st.session_state["access_authorized"] = True
                st.rerun()
            else:
                st.error("Browser storage is unavailable.")
        else:
            st.error("Invalid access code.")

    return False


if not access_gate():
    st.stop()


# ============================================================
# SESSION
# ============================================================

for key, value in {
    "selected_station": "CARE",
    "selected_case_id": None,
    "show_settings": False,
    "show_alerts": False,
    "admin_unlocked": False,
    "search": "",
    "station_warning_silenced": set(),
}.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# CSS
# ============================================================

st.markdown(
    """
    <style>
    @import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap");
    html,body,[class*="css"],.stApp,.stApp *{
        font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif!important;
    }
    #MainMenu,footer,[data-testid="stToolbar"],[data-testid="stDecoration"]{display:none!important}
    header{background:transparent!important}
    .block-container{max-width:1500px;padding:18px 20px 30px}
    .stApp,[data-testid="stAppViewContainer"]{background:#fff!important}

    /* HEADER */
    .caseflow-header-shell,[class*="st-key-caseflow_header_shell"]{
        position:relative!important;height:62px!important;min-height:62px!important;
        margin:0 0 18px!important;overflow:hidden!important;
        border:1px solid #8aa4a3!important;border-radius:2px!important;
        background:linear-gradient(101deg,#003f42,#004b4c 48%,#00625f 72%,#00736a)!important;
        isolation:isolate!important;
    }
    .caseflow-header-shell:before,[class*="st-key-caseflow_header_shell"]:before{
        content:"";position:absolute;right:-3%;top:-18px;width:49%;height:95px;
        background:linear-gradient(132deg,transparent,rgba(0,199,161,.30),rgba(0,57,63,.15));
        clip-path:polygon(28% 0,100% 0,100% 100%,0 100%);pointer-events:none;
    }
    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"]{
        position:absolute!important;inset:0!important;height:62px!important;
        display:block!important;z-index:100!important;pointer-events:none!important;
    }
    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"]>div{
        pointer-events:none!important;
    }
    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"]>div:nth-child(1){
        position:absolute!important;left:0!important;top:0!important;width:31%!important;height:62px!important;
    }
    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"]>div:nth-child(2){
        position:absolute!important;left:34.2%!important;top:13px!important;width:44%!important;
        max-width:360px!important;min-width:220px!important;height:36px!important;
        pointer-events:auto!important;z-index:200!important;
    }
    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"]>div:nth-child(3){
        position:absolute!important;right:1.1%!important;top:7px!important;width:48px!important;
        height:48px!important;pointer-events:auto!important;z-index:200!important;
    }
    .caseflow-brand{
        position:absolute!important;left:12px!important;top:7px!important;height:48px!important;
        display:flex!important;align-items:center!important;gap:6px!important;color:#fff!important;
        white-space:nowrap!important;pointer-events:none!important;
    }
    .caseflow-hpe-symbol{width:23px;height:23px;position:relative}
    .caseflow-hpe-symbol:before,.caseflow-hpe-symbol:after{
        content:"";position:absolute;left:1px;width:21px;height:7px;
        border:2px solid #fff;transform:skewY(-25deg) rotate(-25deg);border-radius:1px;
    }
    .caseflow-hpe-symbol:before{top:3px}.caseflow-hpe-symbol:after{top:12px}
    .caseflow-hpe-copy{display:flex;flex-direction:column;justify-content:center}
    .caseflow-hpe-word{font-size:18px;line-height:16px;font-weight:800;color:#fff}
    .caseflow-hpe-tagline{margin-top:4px;font-size:6px;line-height:5px;color:#d9f7f2}
    .caseflow-divider{width:1px;height:36px;margin-left:8px;background:rgba(255,255,255,.72)}
    .caseflow-title{font-size:18px;font-weight:750;color:#fff}
    [class*="st-key-caseflow_header_shell"] div[data-testid="stTextInput"] input{
        width:100%!important;height:36px!important;border:0!important;border-radius:8px!important;
        padding:0 12px 0 30px!important;color:#244a55!important;font-size:11px!important;
        box-shadow:0 1px 4px rgba(0,0,0,.12)!important;
    }
    [class*="st-key-caseflow_header_shell"] div[data-testid="stTextInput"] label{display:none!important}
    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"]>div:nth-child(3) button{
        width:48px!important;height:48px!important;border-radius:9px!important;
        border:1px solid rgba(255,255,255,.6)!important;
        background:rgba(0,53,57,.28)!important;color:transparent!important;font-size:0!important;
    }
    [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"]>div:nth-child(3) button:before{
        content:"⚙";color:#fff;font-size:21px;display:flex;align-items:center;justify-content:center;
    }

    /* STATION CARDS */
    [class*="st-key-station_wrap_"]{position:relative!important;min-height:184px!important}
    .station-card-visual{position:relative;height:184px;box-sizing:border-box;border-radius:13px;
        padding:18px 24px;overflow:hidden;color:#102041}
    .station-card-visual.care{background:linear-gradient(135deg,#fff4f6,#ffe8ec);border:1.5px solid #f24a61}
    .station-card-visual.arch{background:linear-gradient(135deg,#eaf8ff,#d9f1fc);border:1.5px solid #69b7e5}
    .station-card-visual.pet{background:linear-gradient(135deg,#ecfff9,#dcf7ee);border:1.5px solid #70cda9}
    .station-card-visual.supply{background:linear-gradient(135deg,#f7f0ff,#eee5ff);border:1.5px solid #a07de2}
    .station-card-visual.onsite{background:linear-gradient(135deg,#fff9e8,#fff3cf);border:1.5px solid #e0b94f}
    .station-card-visual.selected{border-width:3px!important}
    .station-icon-circle{width:64px;height:64px;border-radius:50%;display:flex;align-items:center;
        justify-content:center;font-size:30px;font-weight:900;position:absolute;left:24px;top:18px}
    .care .station-icon-circle{color:#e51c3a;background:#ffd7df}.arch .station-icon-circle{color:#0879c9;background:#bce8ff}
    .pet .station-icon-circle{color:#087b58;background:#bff1df}.supply .station-icon-circle{color:#5d2ac9;background:#dfceff}
    .onsite .station-icon-circle{color:#c98700;background:#ffe5a8}
    .station-copy{position:absolute;left:112px;top:29px}.station-card-title{font-size:18px;font-weight:850}
    .station-count-line{display:flex;align-items:baseline;gap:6px;margin-top:8px}
    .station-count{font-size:32px;font-weight:900}.station-active{font-size:12px;color:#53637f}
    .care .station-count{color:#e51c3a}.arch .station-count{color:#0879c9}.pet .station-count{color:#087b58}
    .supply .station-count{color:#5d2ac9}.onsite .station-count{color:#c98700}
    .station-arrow{position:absolute;right:20px;top:31px;font-size:25px;color:#30466b}
    .station-warning{position:absolute;left:24px;bottom:39px;font-size:12px;font-weight:750;color:#53637f}
    .station-warning.active{color:#d33a4e}.station-sla-ref{position:absolute;left:24px;bottom:17px;font-size:12px;color:#53637f}
    .station-sla-ref strong{color:#102041}
    [class*="st-key-station_wrap_"] [class*="st-key-station_"]{
        position:absolute!important;inset:0!important;z-index:50!important;height:184px!important
    }
    [class*="st-key-station_wrap_"] [class*="st-key-station_"] button{
        position:absolute!important;inset:0!important;width:100%!important;height:184px!important;
        background:transparent!important;border:0!important;color:transparent!important;opacity:.001!important
    }
    .station-card-visual.critical{border:2px solid #ef334f!important;animation:flash .55s ease-in-out infinite alternate}
    .station-alert-icon{position:absolute;right:54px;top:22px;width:34px;height:34px;border-radius:50%;
        background:#ef1738;color:#fff;display:flex;align-items:center;justify-content:center;
        font-size:22px;font-weight:950;animation:iconflash .42s ease-in-out infinite alternate}
    @keyframes flash{to{box-shadow:0 0 0 5px rgba(239,23,56,.16),0 0 30px rgba(239,23,56,.48)}}
    @keyframes iconflash{to{transform:scale(1.14);opacity:1}}

    /* TABLE */
    .cases-title{color:#11213e;font-size:21px;font-weight:850}.station-pill{display:inline-block;padding:7px 14px;
        border-radius:18px;font-weight:800;font-size:13px;margin-left:10px}
    .case-head{color:#263957;font-size:10px;font-weight:700;padding:7px 6px;border-bottom:1px solid #edf0f5}
    .case-row{min-height:30px;border-bottom:1px solid #edf0f5;color:#31435f;font-size:10px;padding:4px 6px}
    [class*="st-key-case_cell_"]{min-width:0!important;width:100%!important;height:30px!important}
    [class*="st-key-case_cell_"] button{width:100%!important;height:30px!important;border:1px solid #d3dbe7!important;
        border-radius:9px!important;background:#fff!important;color:#31435f!important;font-size:10px!important}
    [class*="st-key-case_cell_care_"] button{background:#fff0f2!important;border-color:#f3a4b0!important}
    [class*="st-key-case_cell_arch_"] button{background:#eaf7ff!important;border-color:#9bd7f5!important}
    [class*="st-key-case_cell_pet_"] button{background:#ecfbf4!important;border-color:#9cdec6!important}
    [class*="st-key-case_cell_supply_"] button{background:#f2edff!important;border-color:#c8b5f3!important}
    [class*="st-key-case_cell_onsite_"] button{background:#fff8df!important;border-color:#ecd28c!important}
    .agent-cell{display:flex;align-items:center;gap:7px;min-height:30px;border-bottom:1px solid #edf0f5;font-size:10px}
    .agent-avatar{width:25px;height:25px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;color:#fff;font-size:9px;font-weight:850}
    .priority-pill{display:inline-flex;padding:5px 9px;border-radius:14px;font-size:9px;font-weight:850}
    .priority-pill.critical{background:#ffe5e9;color:#e51c3a}.priority-pill.high{background:#fff0dc;color:#e77700}
    .priority-pill.medium{background:#fff3d2;color:#b77a00}.priority-pill.low{background:#edf1f6;color:#65738a}
    .due-cell{min-height:30px;border-bottom:1px solid #edf0f5;font-size:9px;padding:3px 6px}
    .badge{display:inline-block;padding:4px 7px;border-radius:12px;font-size:9px;font-weight:800}
    .badge-open{background:#dcf8df;color:#218137}.badge-progress{background:#dff1ff;color:#0d72c6}
    .badge-hold{background:#fff0ce;color:#b77900}.badge-pending{background:#eef2f7;color:#526078}
    .duration-warning-wrap{display:inline-flex;align-items:center;min-height:24px;white-space:nowrap;font-weight:800}
    .duration-green{color:#218137}.duration-yellow{color:#c58a00}.duration-red{color:#e51c3a;font-weight:900}
    .duration-warning-active{animation:durationflash .65s ease-in-out infinite alternate}
    @keyframes durationflash{from{opacity:.55}to{opacity:1}}

    /* DETAIL DRAWER */
    div[data-testid="stDialog"]>div{position:fixed!important;top:8vh!important;right:14px!important;left:auto!important;
        width:min(620px,calc(100vw - 28px))!important;max-width:min(620px,calc(100vw - 28px))!important;
        height:84vh!important;max-height:84vh!important;border-radius:18px!important;
        box-shadow:0 12px 40px rgba(25,42,76,.18)!important;overflow:hidden!important;background:#fff!important}
    div[data-testid="stDialog"]>div>div{overflow-y:auto!important}
    .detail-header{display:flex;align-items:center;gap:14px;border-bottom:1px solid #e9edf3;padding:4px 0 18px;margin-bottom:20px}
    .detail-header-title{color:#102041;font-size:30px;font-weight:850}
    .detail-critical{display:inline-flex;align-items:center;gap:7px;padding:9px 18px;border-radius:13px;background:#ffe4e8;color:#e51c3a;font-weight:850;font-size:14px}
    .detail-critical-dot{width:18px;height:18px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;background:#ef1738;color:#fff}
    .detail-case-title{color:#102041;font-size:25px;font-weight:850;margin-bottom:8px}
    .detail-status{display:inline-flex;padding:8px 15px;border-radius:18px;background:#dff0ff;color:#1872c8;font-size:13px;font-weight:800;margin-left:10px}
    .detail-subject{color:#172b4d;font-size:19px;font-weight:750;margin-bottom:12px}
    .detail-description{color:#718099;font-size:14px;line-height:1.55;margin-bottom:22px}
    .detail-grid{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid #e7ebf1;border-bottom:1px solid #e7ebf1;margin-bottom:18px}
    .detail-grid-col{padding:12px 18px 16px 0}.detail-grid-col.right{padding-left:28px;border-left:1px solid #e7ebf1}
    .detail-field{margin-bottom:18px}.detail-label{color:#78869c;font-size:13px;margin-bottom:5px}
    .detail-value{color:#1b2d4c;font-size:15px;font-weight:650}.detail-value.red{color:#e51c3a}
    .detail-pill{display:inline-flex;padding:7px 13px;border-radius:18px;font-size:13px;font-weight:800}
    .detail-pill.red{background:#ffe4e8;color:#e51c3a}.detail-pill.blue{background:#dff0ff;color:#1872c8}
    .detail-pill.purple{background:#f3ddff;color:#a33bd0}
    .vendor-card{background:#f4f7fb;border-radius:16px;padding:18px 20px;margin:12px 0 20px}
    .vendor-heading{display:flex;align-items:center;gap:10px;color:#182b4c;font-size:16px;font-weight:850;margin-bottom:16px}
    .vendor-icon{width:28px;height:28px;display:inline-flex;align-items:center;justify-content:center;border:2px solid #263d60;border-radius:5px}
    .vendor-grid{display:grid;grid-template-columns:150px 1fr;gap:8px 12px;font-size:13px}
    .vendor-key{color:#718099}.vendor-value{color:#253754;font-weight:600}

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

    @media(max-width:700px){
        .block-container{padding:10px}
        .caseflow-header-shell,[class*="st-key-caseflow_header_shell"]{height:94px!important;min-height:94px!important}
        [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"]{height:94px!important}
        [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"]>div:nth-child(1){width:72%!important;height:48px!important}
        [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"]>div:nth-child(2){
            left:10px!important;top:52px!important;width:calc(100% - 70px)!important;max-width:none!important;min-width:0!important}
        [class*="st-key-caseflow_header_shell"] [data-testid="stHorizontalBlock"]>div:nth-child(3){right:8px!important;top:6px!important}
        [data-testid="stHorizontalBlock"]:has([class*="st-key-station_wrap_"]){
            display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:9px!important}
        .station-card-visual{height:145px!important;min-height:145px!important;padding:12px!important}
        .station-icon-circle{width:46px;height:46px;left:12px;top:12px;font-size:22px}
        .station-copy{left:70px;top:18px}.station-card-title{font-size:14px}.station-count{font-size:25px}
        .station-warning{left:12px;bottom:32px;font-size:9px}.station-sla-ref{left:12px;bottom:13px;font-size:9px}
        .detail-grid{grid-template-columns:1fr}.detail-grid-col.right{padding-left:0;border-left:0;border-top:1px solid #e7ebf1;padding-top:14px}
        .vendor-grid{grid-template-columns:1fr}.vendor-key{margin-top:6px}
        div[data-testid="stDialog"]>div{top:8px!important;right:8px!important;left:8px!important;
            width:calc(100vw - 16px)!important;max-width:calc(100vw - 16px)!important;height:calc(100vh - 16px)!important;max-height:calc(100vh - 16px)!important}
    }
    
    .kb-ai-panel{background:linear-gradient(135deg,#f8fbff 0%,#f4f7ff 100%);border:1px solid #d9e1ef;border-radius:17px;padding:18px;margin:18px 0 14px;box-shadow:0 5px 18px rgba(24,43,76,.04)}
    .kb-ai-header{display:flex;align-items:center;justify-content:space-between;gap:12px}
    .kb-ai-title{color:#122442;font-size:18px;font-weight:850}
    .kb-ai-subtitle{color:#718099;font-size:12px;line-height:1.5;margin-top:5px}
    .kb-ai-badge{display:inline-flex;align-items:center;padding:5px 9px;border-radius:12px;background:#e9e5ff;color:#5b49cf;font-size:10px;font-weight:850}
    .kb-ai-answer{background:#fff;border:1px solid #d9e1ef;border-left:4px solid #6d5ce7;border-radius:13px;padding:15px;margin-top:12px}
    .kb-ai-answer-label{color:#6756dc;font-size:10px;font-weight:850;text-transform:uppercase;letter-spacing:.45px;margin-bottom:7px}
    .kb-ai-answer-text{color:#394b65;font-size:13px;line-height:1.62}
    .kb-ai-source-title{color:#53657e;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.35px;margin-top:13px}
    .kb-ai-source{display:inline-block;background:#edf2f8;color:#5d6c82;border-radius:10px;padding:4px 8px;font-size:9px;font-weight:750;margin:5px 5px 0 0}
    .kb-ai-note{color:#8491a4;font-size:10px;line-height:1.45;margin-top:8px}
</style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# TASKS
# ============================================================

def task_projection():
    return {
        "_id": 1, "case_number": 1, "subject": 1, "priority": 1,
        "account_priority": 1, "assigned_to": 1, "due_date": 1,
        "created_at": 1, "station_started_at": 1, "department": 1,
        "status": 1, "last_update": 1, "account_name": 1, "vendor": 1,
        "issue": 1, "description": 1, "notes": 1, "history": 1,
        "active": 1, "is_mock": 1, "source_type": 1, "case_type": 1,
        "category": 1,
    }


@st.cache_data(ttl=TASK_CACHE_TTL, show_spinner=False)
def fetch_tasks(search="", station=None, limit=300):
    query = {"active": True}

    if station:
        query["department"] = station

    if search:
        rx = {"$regex": search, "$options": "i"}
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
            .sort([("station_started_at", ASCENDING)])
            .limit(limit)
        )
    except PyMongoError:
        return []


def clear_task_cache():
    try:
        fetch_tasks.clear()
    except Exception:
        pass


def calculate_state(task, now=None):
    now = now or utc_now()
    station = station_name(task.get("department"))
    sla = STATIONS.get(station, STATIONS["CARE"])["sla_minutes"] * 60
    started = as_utc(task.get("station_started_at") or task.get("created_at"))
    elapsed = 0 if not started else max(0, (now - started).total_seconds())
    remaining = sla - elapsed
    priority_account = is_priority(task.get("account_priority"))
    nearing = remaining > 0 and remaining <= sla * .20
    breached = remaining <= 0

    if priority_account:
        status = "CRITICAL"
    elif breached:
        status = "BREACHED"
    elif nearing:
        status = "CRITICAL"
    elif remaining <= sla * .50:
        status = "MEDIUM"
    else:
        status = "LOW"

    return {
        "status": status,
        "elapsed": elapsed,
        "remaining": remaining,
        "progress": min(100, max(0, elapsed / sla * 100)),
        "priority_account": priority_account,
        "nearing_due": nearing,
        "past_due": breached,
        "critical": status in {"CRITICAL", "BREACHED"},
        "breached": breached,
    }


# ============================================================
# EXACTLY 5 MOCK CASES PER STATION
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

MOCK_NAMES = ["John Dela Cruz", "Maria Santos", "Anna Reyes", "Carlo Banaag", "Liza Tan"]
MOCK_ACCOUNTS = ["Marriott Hotel", "Hilton Group", "Accenture", "Microsoft", "Acme Corporation"]
MOCK_DATA_VERSION = 12


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
            docs.append({
                "case_number": f"{station[:3].upper()}-2026-{number:04d}",
                "subject": MOCK_SUBJECTS[station][i],
                "priority": "Critical" if priority else ("Medium" if i == 1 else "Low"),
                "account_priority": "Yes" if priority else "No",
                "assigned_to": MOCK_NAMES[i],
                "department": station,
                "account_name": MOCK_ACCOUNTS[i % len(MOCK_ACCOUNTS)],
                "vendor": "CoolTech Solutions" if i % 2 == 0 else "HPE Partner Services",
                "issue": MOCK_SUBJECTS[station][i],
                "description": f"Mock task for {station}. This record was created for dashboard demonstration.",
                "status": "In Progress" if i % 2 == 0 else "Open",
                "created_at": now,
                "station_started_at": now,
                "due_date": now + timedelta(minutes=cfg["sla_minutes"]),
                "last_update": now,
                "notes": "Mock demonstration case.",
                "active": True,
                "is_mock": True,
                "mock_data_version": MOCK_DATA_VERSION,
                "source_type": "mock",
                "history": [{
                    "action": f"Case entered {station}",
                    "timestamp": now,
                }],
            })
            number += 1

    col(TASKS_COLLECTION).insert_many(docs)
    return len(docs)


# ============================================================
# ALERTS
# ============================================================

def active_alerts():
    try:
        return list(
            col(ALERT_COLLECTION)
            .find({"acknowledged": False})
            .sort("created_at", DESCENDING)
            .limit(50)
        )
    except Exception:
        return []


def acknowledge_alert(alert_id):
    try:
        from bson import ObjectId
        col(ALERT_COLLECTION).update_one(
            {"_id": ObjectId(alert_id)},
            {"$set": {"acknowledged": True, "acknowledged_at": utc_now()}},
        )
    except Exception:
        pass


def acknowledge_station_alerts(station):
    try:
        col(ALERT_COLLECTION).update_many(
            {"station": station, "acknowledged": False},
            {"$set": {"acknowledged": True, "acknowledged_at": utc_now()}},
        )
    except Exception:
        pass


def scan_alerts(tasks):
    if time.time() - float(st.session_state.get("_last_alert_scan", 0)) < 1:
        return

    st.session_state["_last_alert_scan"] = time.time()
    candidates = []

    for task in tasks:
        state = calculate_state(task)
        if not state["critical"]:
            continue

        if state["priority_account"]:
            kind = "PRIORITY_ACCOUNT"
            message = (
                f"High-priority account detected: {text(task.get('account_name'))} "
                f"— Case {text(task.get('case_number'))}"
            )
        elif state["breached"]:
            continue
        else:
            kind = "NEARING_DUE"
            message = (
                f"Case nearing SLA: {text(task.get('case_number'))} "
                f"— {text(task.get('account_name'))}"
            )

        candidates.append((task, kind, message))

    if not candidates:
        return

    ids = [str(x[0]["_id"]) for x in candidates]

    try:
        existing = {
            (str(x.get("task_id")), x.get("alert_type"))
            for x in col(ALERT_COLLECTION).find(
                {"acknowledged": False, "task_id": {"$in": ids}},
                {"task_id": 1, "alert_type": 1},
            )
        }
    except Exception:
        existing = set()

    docs = []

    for task, kind, message in candidates:
        key = (str(task["_id"]), kind)
        if key in existing:
            continue

        docs.append({
            "task_id": str(task["_id"]),
            "case_number": task.get("case_number"),
            "station": station_name(task.get("department")),
            "account_name": task.get("account_name"),
            "alert_type": kind,
            "message": message,
            "created_at": utc_now(),
            "acknowledged": False,
        })

    if docs:
        try:
            col(ALERT_COLLECTION).insert_many(docs, ordered=False)
        except Exception:
            pass


# ============================================================
# VENDOR / CASE EXCEL
# ============================================================

def find_vendor(task):
    keys = [
        text(task.get("vendor")).lower(),
        text(task.get("account_name")).lower(),
    ]
    keys = [x for x in keys if x]
    if not keys:
        return None

    try:
        return col(VENDOR_COLLECTION).find_one({"vendor_key": {"$in": keys}})
    except Exception:
        return None


def sync_vendor_excel(uploaded_file):
    try:
        df = pd.read_excel(uploaded_file)
        if df.empty:
            return False, "The Excel file is empty."

        df.columns = [
            text(c).lower().strip().replace(" ", "_")
            for c in df.columns
        ]

        df = df.rename(columns={
            "vendor_name": "vendor",
            "vendorname": "vendor",
            "account": "account_name",
            "accountname": "account_name",
            "vendorid": "vendor_id",
            "contact": "contact_name",
            "contactperson": "contact_name",
            "contact_number": "phone",
            "contactnumber": "phone",
        })

        docs = []

        for _, row in df.iterrows():
            item = {}
            for c in df.columns:
                value = row[c]
                if pd.isna(value):
                    value = ""
                if isinstance(value, pd.Timestamp):
                    value = value.isoformat()
                item[c] = text(value)

            key = item.get("vendor_id") or item.get("vendor") or item.get("account_name")
            if not key:
                continue

            item["vendor_key"] = text(key).lower()
            item["synced_at"] = utc_now()
            docs.append(item)

        col(VENDOR_COLLECTION).delete_many({})
        if docs:
            col(VENDOR_COLLECTION).insert_many(docs)

        return True, f"{len(docs)} vendor records synchronized."
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


# ============================================================
# TRANSFER
# ============================================================

def transfer_case(task, destination):
    try:
        from bson import ObjectId

        now = utc_now()
        history = list(task.get("history", []))
        history.append({
            "action": f"Transferred from {station_name(task.get('department'))} to {destination}",
            "timestamp": now,
        })

        col(TASKS_COLLECTION).update_one(
            {"_id": ObjectId(str(task["_id"]))},
            {"$set": {
                "department": destination,
                "station_started_at": now,
                "due_date": now + timedelta(minutes=STATIONS[destination]["sla_minutes"]),
                "last_update": now,
                "status": "Open",
                "history": history[-50:],
            }},
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


@st.cache_data(ttl=KB_CACHE_TTL, show_spinner=False)
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
                "title": "ONSITE - Hardware Replacement",
                "category": "ONSITE",
                "keywords": ["onsite", "hardware", "replacement", "device", "technician"],
                "answer": "Capture the device, serial number, site/location, symptoms, contact details and access requirements. Confirm whether onsite dispatch or remote troubleshooting is appropriate before escalation.",
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


seed_demo_kb()


# ============================================================
# HEADER
# ============================================================

with st.container(key="caseflow_header_shell"):

    c1, c2, c3 = st.columns([31, 44, 5], gap="small")

    with c1:
        st.markdown(
            """
            <div class="caseflow-brand">
                <div class="caseflow-hpe-symbol"></div>
                <div class="caseflow-hpe-copy">
                    <div class="caseflow-hpe-word">HPE</div>
                    <div class="caseflow-hpe-tagline">Accelerating what's next together</div>
                </div>
                <div class="caseflow-divider"></div>
                <div class="caseflow-title">Caseflow</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c2:
        st.session_state["search"] = st.text_input(
            "Search",
            value=st.session_state["search"],
            placeholder="Search case number, subject, name, or issue...",
            key="header_search",
            label_visibility="collapsed",
        )

    with c3:
        if st.button("⚙", key="open_settings", use_container_width=True):
            st.session_state["show_settings"] = True


# ============================================================
# SETTINGS
# ============================================================

if st.session_state["show_settings"]:

    @st.dialog("Settings", width="large")
    def settings_dialog():

        if not st.session_state["admin_unlocked"]:

            st.markdown("### Administrator Access")

            pin = st.text_input(
                "Admin PIN",
                type="password",
                placeholder="Enter admin PIN",
            )

            if st.button("Unlock Settings", type="primary", use_container_width=True):
                if hmac.compare_digest(pin, text(st.secrets.get("ADMIN_PIN", ""))):
                    st.session_state["admin_unlocked"] = True
                    st.rerun()
                else:
                    st.error("Invalid admin PIN.")

            if st.button("Close", use_container_width=True):
                st.session_state["show_settings"] = False
                st.rerun()

        else:

            tabs = st.tabs([
                "Cases",
                "External Sync",
                "Access Control",
                "Simulation",
            ])

            with tabs[0]:

                st.markdown("### Case Data")
                st.caption(
                    "Case #, Subject and Department are required."
                )

                uploaded = st.file_uploader(
                    "Cases Excel",
                    type=["xlsx", "xls"],
                    key="case_excel_upload",
                )

                replace_excel = st.checkbox(
                    "Replace previously imported Excel cases",
                    value=False,
                )

                if uploaded is not None:

                    try:
                        st.dataframe(
                            pd.read_excel(uploaded).head(8),
                            use_container_width=True,
                            hide_index=True,
                        )
                    except Exception as exc:
                        st.error(f"Unable to preview: {exc}")

                    if st.button(
                        "Import Cases",
                        type="primary",
                        use_container_width=True,
                    ):
                        ok, msg, _ = import_cases_excel(
                            uploaded,
                            replace_existing_excel=replace_excel,
                        )
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

            with tabs[1]:

                st.markdown("### Vendor Information")

                uploaded_vendor = st.file_uploader(
                    "Vendor Excel",
                    type=["xlsx", "xls"],
                    key="vendor_excel_upload",
                )

                if uploaded_vendor is not None and st.button(
                    "Synchronize Vendor Data",
                    type="primary",
                    use_container_width=True,
                ):
                    ok, msg = sync_vendor_excel(uploaded_vendor)
                    st.success(msg) if ok else st.error(msg)

            with tabs[2]:

                st.markdown("### One-Time Access")
                st.info(
                    "Changing ACCESS_CODE or TOKEN_SECRET invalidates stored browser authorization."
                )

                if st.button(
                    "Clear Token Access",
                    use_container_width=True,
                ):
                    _clear_token()
                    st.session_state["access_authorized"] = False
                    st.success("Browser authorization cleared.")

            # IMPORTANT: Simulate Critical Alert was removed.
            # The reset button remains exactly as requested.
            with tabs[3]:

                st.markdown("### Mock Case Controls")

                st.caption(
                    "There are exactly 5 mock cases per station (25 total). "
                    "This control resets all mock-case durations to 00:00:00."
                )

                if st.button(
                    "↻ Reset Mock Case Durations to 00:00:00",
                    type="secondary",
                    use_container_width=True,
                    key="reset_mock_case_durations",
                ):
                    count = reset_mock_case_durations()
                    st.success(
                        f"{count} mock case(s) reset to 00:00:00."
                    )
                    st.rerun()

            if st.button("Close Settings", use_container_width=True):
                st.session_state["show_settings"] = False
                st.rerun()

    settings_dialog()


# ============================================================
# ALERT CENTER
# ============================================================

if st.session_state["show_alerts"]:

    @st.dialog("Alert Center", width="large")
    def alert_dialog():

        alerts = active_alerts()

        if not alerts:
            st.success("No active alerts.")

        for alert in alerts:

            st.markdown(
                f"""
                <div style="border:2px solid #ef334f;background:#fff5f7;
                            border-radius:18px;padding:18px;margin-bottom:12px">
                    <div style="color:#c91935;font-size:18px;font-weight:900">
                        🚨 {html.escape(text(alert.get("alert_type")).replace("_"," "))}
                    </div>
                    <div style="color:#5d2730;margin-top:6px">
                        {html.escape(text(alert.get("message")))}
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
                acknowledge_alert(str(alert["_id"]))
                st.rerun()

        if st.button("Close", use_container_width=True):
            st.session_state["show_alerts"] = False
            st.rerun()

    alert_dialog()


# ============================================================
# CASE DETAIL
# ============================================================

@st.dialog("Case Details", width="large")
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

    kb_query = st.text_input(
        "Knowledge Base Search",
        value=auto_query,
        placeholder="Search SOPs, troubleshooting, licensing, devices...",
        key=f"kb_query_{task_id}",
        label_visibility="collapsed",
    )

    kb1, kb2 = st.columns(2)

    with kb1:
        search_clicked = st.button(
            "🔎 Search Knowledge Base",
            type="primary",
            use_container_width=True,
            key=f"kb_search_{task_id}",
        )

    with kb2:
        case_match_clicked = st.button(
            "↻ Use Case Match",
            use_container_width=True,
            key=f"kb_case_match_{task_id}",
        )

    active_query = (
        auto_query
        if case_match_clicked
        else text(kb_query)
        if search_clicked
        else text(kb_query) or auto_query
    )

    results = search_kb(active_query, limit=5)

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
        st.session_state[ai_question_key] = (
            "What are the recommended next steps for this case?"
        )

    st.markdown(
        """
        <div class="kb-ai-panel">
            <div class="kb-ai-header">
                <div>
                    <div class="kb-ai-title">✨ Ask Knowledge Base</div>
                    <div class="kb-ai-subtitle">
                        Ask a question about this case. Caseflow searches
                        the Knowledge Base and SOPs and builds a grounded
                        answer from the most relevant articles.
                    </div>
                </div>
                <span class="kb-ai-badge">CASE-AWARE</span>
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

        retrieval_query = " ".join(
            x for x in [question, case_kb_query(task)] if x
        )

        retrieved = search_kb(retrieval_query, limit=6)

        st.session_state[ai_result_key] = local_kb_ai_answer(
            question,
            task,
            retrieved,
        )

    ai_result = st.session_state.get(ai_result_key)

    if ai_result:
        answer_html = html.escape(
            text(ai_result.get("answer"))
        ).replace("\n", "<br>")

        st.markdown(
            f"""
            <div class="kb-ai-answer">
                <div class="kb-ai-answer-label">
                    Knowledge Base Answer ·
                    {html.escape(text(ai_result.get("confidence")))}
                </div>
                <div class="kb-ai-answer-text">
                    {answer_html}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        sources = ai_result.get("sources", [])

        if sources:
            pills = "".join(
                f'<span class="kb-ai-source">'
                f'{html.escape(text(doc.get("title")) or "KB Article")}'
                f'</span>'
                for doc in sources[:6]
            )

            st.markdown(
                f"""
                <div class="kb-ai-source-title">Sources used</div>
                <div>{pills}</div>
                <div class="kb-ai-note">
                    This assistant works entirely from the Caseflow
                    Knowledge Base/SOP data. No OpenAI API or API key
                    is required.
                </div>
                """,
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

@st.fragment(run_every="1s")
def dashboard_fragment():

    selected = st.session_state["selected_station"]

    tasks = fetch_tasks(
        search=st.session_state["search"],
        limit=300,
    )

    scan_alerts(tasks)

    now = utc_now()
    states = {}
    tasks_by_station = {s: [] for s in STATIONS}
    states_by_station = {s: [] for s in STATIONS}

    for task in tasks:
        task_id = str(task["_id"])
        state = calculate_state(task, now)
        states[task_id] = state

        station = station_name(task.get("department"))

        if station in tasks_by_station:
            tasks_by_station[station].append(task)
            states_by_station[station].append(state)

    # -------------------------
    # Station tiles
    # -------------------------

    cols = st.columns(5)

    for index, station in enumerate(STATIONS):

        station_tasks = tasks_by_station[station]
        station_states = states_by_station[station]

        nearing = sum(x["nearing_due"] for x in station_states)
        past_due = sum(x["past_due"] for x in station_states)

        silenced = st.session_state.setdefault(
            "station_warning_silenced", set()
        )

        if nearing == 0:
            silenced.discard(station)

        flashing = nearing > 0 and station not in silenced

        slug = {
            "CARE": "care",
            "ARCH": "arch",
            "PET": "pet",
            "SUPPLY CHAIN": "supply",
            "ONSITE": "onsite",
        }[station]

        cfg = STATIONS[station]
        sla = cfg["sla_minutes"]
        sla_text = f"{sla} mins" if sla < 60 else f"{sla // 60} hour"

        with cols[index]:

            with st.container(key=f"station_wrap_{slug}"):

                st.markdown(
                    f"""
                    <div class="station-card-visual {slug}
                        {"critical" if flashing else ""}
                        {"selected" if selected == station else ""}">
                        {"<div class='station-alert-icon'>!</div>" if flashing else ""}
                        <div class="station-icon-circle">{html.escape(cfg["icon"])}</div>
                        <div class="station-copy">
                            <div class="station-card-title">{html.escape(station)}</div>
                            <div class="station-count-line">
                                <span class="station-count">{len(station_tasks)}</span>
                                <span class="station-active">Active Cases</span>
                            </div>
                        </div>
                        <div class="station-arrow">›</div>
                        <div class="station-warning {"active" if nearing else ""}">
                            ◷ &nbsp; {nearing} nearing due
                            {" • " + str(past_due) + " past due" if past_due else ""}
                        </div>
                        <div class="station-sla-ref">
                            ◷ &nbsp; Max Timeframe: <strong>{sla_text}</strong>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if st.button(
                    f"Select {station}",
                    key=f"station_{station}",
                    use_container_width=True,
                ):

                    if nearing:
                        silenced.add(station)
                        acknowledge_station_alerts(station)

                    st.session_state["selected_station"] = station
                    st.rerun(scope="fragment")

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

    # -------------------------
    # Active cases
    # -------------------------

    selected_tasks = [
        task for task in tasks
        if station_name(task.get("department")) == selected
    ]

    selected_tasks.sort(
        key=lambda task: (
            STATUS_ORDER.get(states[str(task["_id"])]["status"], 9),
            states[str(task["_id"])]["remaining"],
        )
    )

    title_cols = st.columns([6.5, 2])

    with title_cols[0]:
        cfg = STATIONS.get(selected, STATIONS["CARE"])
        st.markdown(
            f"""
            <span class="cases-title">Active Cases</span>
            <span class="station-pill"
                  style="background:{cfg["soft"]};color:{cfg["accent"]};border:1px solid {cfg["accent"]}33">
                {html.escape(selected)}
            </span>
            """,
            unsafe_allow_html=True,
        )

    with title_cols[1]:
        sort = st.selectbox(
            "Sort",
            ["Urgency", "Duration", "Due Date"],
            label_visibility="collapsed",
            key="sort_choice",
        )

    if sort == "Duration":
        selected_tasks.sort(
            key=lambda task: -states[str(task["_id"])]["elapsed"]
        )
    elif sort == "Due Date":
        selected_tasks.sort(
            key=lambda task: as_utc(task.get("due_date"))
            or datetime.max.replace(tzinfo=timezone.utc)
        )

    header = st.columns([1.05,2.25,1.15,1.35,1.35,1.10,1.00])

    for cell, title in zip(
        header,
        ["Case #","Subject","Priority","Assigned To","Due Date","Status","Duration"]
    ):
        with cell:
            st.markdown(
                f'<div class="case-head">{title}</div>',
                unsafe_allow_html=True,
            )

    for task in selected_tasks:

        task_id = str(task["_id"])
        state = states[task_id]
        row = st.columns([1.05,2.25,1.15,1.35,1.35,1.10,1.00])

        with row[0]:

            slug = {
                "CARE": "care",
                "ARCH": "arch",
                "PET": "pet",
                "SUPPLY CHAIN": "supply",
                "ONSITE": "onsite",
            }.get(station_name(task.get("department")), "care")

            with st.container(key=f"case_cell_{slug}_{task_id}"):

                if st.button(
                    text(task.get("case_number")),
                    key=f"case_{task_id}",
                    use_container_width=True,
                ):
                    case_details(task_id)

        with row[1]:
            st.markdown(
                f'<div class="case-row">{html.escape(text(task.get("subject")))}</div>',
                unsafe_allow_html=True,
            )

        with row[2]:

            priority_text = (
                "Critical"
                if state["priority_account"] or state["status"] in {"CRITICAL","BREACHED"}
                else text(task.get("priority","Low")).title()
            )

            priority_class = {
                "Critical": "critical",
                "High": "high",
                "Medium": "medium",
                "Low": "low",
            }.get(priority_text, "low")

            st.markdown(
                f'<div class="case-row"><span class="priority-pill {priority_class}">● {html.escape(priority_text)}</span></div>',
                unsafe_allow_html=True,
            )

        with row[3]:

            assigned = text(task.get("assigned_to")) or "Unassigned"
            initials = "".join(x[0] for x in assigned.split() if x)[:2].upper()

            colors = ["#e94b68","#3d8fe5","#70b942","#25a7d8","#8a63df","#7083a2"]
            avatar = colors[sum(ord(c) for c in assigned) % len(colors)]

            st.markdown(
                f"""
                <div class="agent-cell">
                    <span class="agent-avatar" style="background:{avatar}">{html.escape(initials)}</span>
                    <span>{html.escape(assigned)}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with row[4]:

            due = dt_display(task.get("due_date"))
            st.markdown(
                f'<div class="due-cell" style="color:{"#e51c3a" if state["critical"] else "#31435f"}">{html.escape(due)}</div>',
                unsafe_allow_html=True,
            )

        with row[5]:

            raw = text(task.get("status","Open")).lower()
            status_class = (
                "badge-progress" if "progress" in raw
                else "badge-hold" if "hold" in raw
                else "badge-pending" if "pending" in raw
                else "badge-open"
            )

            st.markdown(
                f'<div class="case-row"><span class="badge {status_class}">{html.escape(text(task.get("status","Open")))}</span></div>',
                unsafe_allow_html=True,
            )

        with row[6]:

            started = iso_z(task.get("station_started_at") or task.get("created_at"))
            sla_seconds = STATIONS.get(
                station_name(task.get("department")),
                STATIONS["CARE"],
            )["sla_minutes"] * 60

            ratio = state["elapsed"] / sla_seconds if sla_seconds else 1

            duration_class = (
                "duration-green" if ratio < .50
                else "duration-yellow" if ratio < .80
                else "duration-red"
            )

            st.markdown(
                f"""
                <div class="case-row">
                    <div class="duration-warning-wrap {duration_class}"
                         data-duration-live="1"
                         data-duration-start="{html.escape(started)}"
                         data-sla-seconds="{sla_seconds}">
                        {duration_string(state["elapsed"])}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # -------------------------
    # Browser-side duration
    # -------------------------

    st.markdown(
        """
        <script>
        (() => {
            function tick() {
                const now = Date.now();
                document.querySelectorAll('[data-duration-live="1"]').forEach(n => {
                    const raw = n.getAttribute("data-duration-start");
                    const sla = Number(n.getAttribute("data-sla-seconds") || 0);
                    if (!raw || !sla) return;

                    const start = Date.parse(raw);
                    if (!Number.isFinite(start)) return;

                    const elapsed = Math.max(0, Math.floor((now-start)/1000));
                    const h = Math.floor(elapsed/3600);
                    const m = Math.floor((elapsed%3600)/60);
                    const s = elapsed%60;

                    n.textContent =
                        String(h).padStart(2,"0")+":"+
                        String(m).padStart(2,"0")+":"+
                        String(s).padStart(2,"0");

                    const ratio = elapsed/sla;
                    n.classList.toggle("duration-green", ratio < .50);
                    n.classList.toggle("duration-yellow", ratio >= .50 && ratio < .80);
                    n.classList.toggle("duration-red", ratio >= .80);
                    n.classList.toggle("duration-warning-active", ratio >= .80 && ratio < 1);
                });
            }

            tick();

            if (!window.__caseflowTimer) {
                window.__caseflowTimer = setInterval(tick,1000);
            }
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# START APP
# ============================================================

seed_mock_cases()
dashboard_fragment()

st.markdown(
    """
    <div style="text-align:center;color:#98a2b3;font-size:11px;padding-top:22px">
        Real-time monitoring enabled • Duration updates in the browser
        without refreshing the full dashboard
    </div>
    """,
    unsafe_allow_html=True,
)
