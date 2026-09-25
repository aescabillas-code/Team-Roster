import datetime as dt
import hashlib
import hmac
import secrets
from collections import Counter

import pandas as pd
import plotly.express as px
import streamlit as st
from pymongo import MongoClient
from pymongo.errors import PyMongoError, DuplicateKeyError

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None


# ============================================================
# HPE CASEFLOW — EXACT UI MATCH VERSION
# ============================================================

st.set_page_config(
    page_title="HPE CaseFlow",
    page_icon="▣",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# DESIGN SYSTEM & CSS
# ============================================================

HPE_NAVY = "#003B49"
HPE_DARK = "#002F3A"
HPE_TEAL = "#00A88F"
HPE_GREEN = "#00A88F"
HPE_LIGHT = "#F5F8FA"
HPE_BORDER = "#DDE5E9"
TEXT = "#17313A"
MUTED = "#6B7C84"
RED = "#E94B4B"

st.markdown(
    f"""
    <style>
    :root {{
        --navy: {HPE_NAVY};
        --dark: {HPE_DARK};
        --teal: {HPE_TEAL};
        --light: {HPE_LIGHT};
        --border: {HPE_BORDER};
        --text: {TEXT};
        --muted: {MUTED};
    }}

    .stApp {{
        background: #f7f9fa;
        color: var(--text);
    }}

    .block-container {{
        max-width: 1480px;
        padding: 1rem 1.5rem 2rem;
    }}

    /* =========================================
       HIDE STREAMLIT BRANDING & UI ELEMENTS
       ========================================= */
    header[data-testid="stHeader"] {{
        display: none !important;
    }}
    
    [data-testid="stAppDeployButton"] {{
        display: none !important;
    }}
    
    #MainMenu {{
        display: none !important;
    }}
    
    footer {{
        display: none !important;
    }}

    /* =========================================
       SIDEBAR STYLING
       ========================================= */
    /* Removed rigid min-width/max-width so the native collapse toggle works properly */
    [data-testid="stSidebar"] {{
        background: #002B36 !important;
    }}

    [data-testid="stSidebar"] > div:first-child {{
        padding: 2rem 1.5rem;
    }}

    [data-testid="stSidebar"] * {{
        color: #fff !important;
    }}

    /* Fix white-on-white by making inactive buttons transparent */
    [data-testid="stSidebar"] button {{
        width: 100%;
        min-height: 44px;
        border: 0 !important;
        background: transparent !important; 
        box-shadow: none !important;
        border-radius: 8px !important;
        text-align: left !important;
        font-size: 14px !important;
        font-weight: 600 !important;
        padding: 10px 15px !important;
        margin: 0 0 12px 0 !important;
        color: #ffffff !important;
        transition: background 0.2s ease;
    }}

    [data-testid="stSidebar"] button:hover {{
        background: rgba(255, 255, 255, 0.08) !important;
    }}

    /* Top Bar Styling */
    .topbar {{
        height: 50px;
        background: #fff;
        border: 1px solid var(--border);
        border-radius: 8px;
        display: flex;
        align-items: center;
        padding: 0 15px;
        box-shadow: 0 1px 4px rgba(0,0,0,.03);
        margin-bottom: 20px;
    }}

    .top-logo {{
        color: var(--navy);
        font-weight: 800;
        font-size: 14px;
        display: flex;
        align-items: center;
    }}

    .top-logo .mini-mark {{
        display: inline-block;
        width: 16px;
        height: 10px;
        border: 2px solid var(--teal);
        margin-right: 8px;
        border-radius: 1px;
    }}

    .user-chip {{
        font-size: 12px;
        color: var(--text);
        white-space: nowrap;
    }}

    .avatar {{
        display: inline-flex;
        width: 26px;
        height: 26px;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        background: var(--navy);
        color: #fff;
        font-size: 10px;
        font-weight: 800;
        margin-right: 8px;
    }}

    /* Typography & Layout */
    .page-title {{
        font-size: 24px;
        font-weight: 800;
        color: var(--text);
        margin: 5px 0 2px;
    }}

    .page-subtitle {{
        color: var(--muted);
        font-size: 12px;
        margin-bottom: 20px;
    }}

    .section-title {{
        color: var(--text);
        font-size: 16px;
        font-weight: 800;
        margin: 15px 0 10px;
    }}

    /* Metrics Cards */
    .metric-card {{
        background: #fff;
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 15px;
        display: flex;
        align-items: center;
        box-shadow: 0 2px 5px rgba(0,0,0,.02);
    }}

    .metric-icon-wrap {{
        display: flex;
        align-items: center;
        justify-content: center;
        width: 40px;
        height: 40px;
        border-radius: 8px;
        margin-right: 15px;
        font-size: 18px;
    }}

    .metric-blue {{ background: #eef5ff; color: #2e7d32; }}
    .metric-red {{ background: #ffebeb; color: #d32f2f; }}
    .metric-orange {{ background: #fff4e5; color: #ed6c02; }}
    .metric-green {{ background: #edf7ed; color: #2e7d32; }}

    .metric-content {{
        display: flex;
        flex-direction: column;
    }}

    .metric-label {{
        color: var(--muted);
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 4px;
    }}

    .metric-value {{
        color: var(--text);
        font-size: 24px;
        line-height: 1;
        font-weight: 800;
    }}

    /* Alerts */
    .alert-card {{
        background: #fffafa;
        border: 1px solid #ffcdcd;
        border-left: 4px solid {RED};
        border-radius: 6px;
        padding: 12px 15px;
        margin: 15px 0;
        font-size: 12px;
        color: #b71c1c;
    }}

    .alert-title {{
        font-size: 13px;
        font-weight: 800;
        margin-bottom: 5px;
        display: flex;
        align-items: center;
        gap: 6px;
    }}

    /* Standard Cards */
    .card {{
        background: #fff;
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 15px;
        box-shadow: 0 2px 5px rgba(0,0,0,.02);
        margin-bottom: 15px;
    }}

    /* Auth Screens */
    .auth-brand {{
        min-height: 560px;
        height: 100%;
        background: linear-gradient(150deg, #003B49 0%, #002C38 100%);
        color: #fff;
        border-radius: 10px 0 0 10px;
        padding: 40px 35px;
    }}

    .auth-brand h1 {{
        font-size: 32px;
        margin: 20px 0 5px;
        color: #fff;
        font-weight: 800;
    }}

    .auth-brand-subtitle {{
        color: #d6e7ea !important;
        font-size: 13px !important;
        line-height: 1.5;
        margin: 0 0 35px 0;
    }}

    .auth-feature {{
        display: flex;
        gap: 15px;
        margin-top: 25px;
        align-items: flex-start;
    }}

    .auth-feature-icon {{
        width: 32px;
        height: 32px;
        border-radius: 6px;
        background: rgba(0,168,143,.15);
        color: #16d4b5;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 16px;
        flex-shrink: 0;
    }}

    .auth-feature b {{
        font-size: 13px;
        display: block;
        margin-bottom: 3px;
    }}

    .auth-feature small {{
        color: #c8dcdf;
        font-size: 11px;
        line-height: 1.4;
    }}

    div[data-testid="stVerticalBlockBorderWrapper"]:has(.auth-panel-marker) {{
        min-height: 560px;
        background: #fff;
        border: 1px solid var(--border);
        border-radius: 0 10px 10px 0;
        padding: 0 !important;
        box-shadow: 0 5px 20px rgba(0,0,0,.05);
    }}

    div[data-testid="stVerticalBlockBorderWrapper"]:has(.auth-panel-marker) > div {{
        padding: 35px 40px !important;
    }}

    .auth-panel-title {{
        margin: 10px 0 5px;
        font-size: 22px;
        font-weight: 800;
        color: var(--text);
    }}

    .auth-panel-subtitle {{
        margin: 0 0 20px;
        color: var(--muted);
        font-size: 12px;
    }}

    .auth-panel-marker {{ display: none; }}

    /* Pills */
    .pill {{
        display: inline-block;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 10px;
        font-weight: 800;
        white-space: nowrap;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    .pill-critical {{ background:#ffebee; color:#c62828; }}
    .pill-high {{ background:#fff3e0; color:#ef6c00; }}
    .pill-medium {{ background:#fff9c4; color:#f57f17; }}
    .pill-low {{ background:#f5f5f5; color:#616161; }}
    .pill-green {{ background:#e8f5e9; color:#2e7d32; }}
    .pill-purple {{ background:#f3e5f5; color:#6a1b9a; }}

    /* Grids & Tables */
    .info-grid {{
        display: grid;
        grid-template-columns: 120px 1fr;
        gap: 12px 15px;
        font-size: 13px;
    }}
    .info-grid .label {{ color: var(--muted); font-weight: 700; }}
    
    .empty {{
        text-align: center;
        padding: 40px 20px;
        color: var(--muted);
        font-size: 14px;
        background: #fff;
        border: 1px dashed var(--border);
        border-radius: 8px;
    }}

    div[data-testid="stDataFrame"] {{
        border: 1px solid var(--border);
        border-radius: 8px;
        overflow: hidden;
    }}

    /* Inputs & Buttons */
    .stButton > button,
    .stDownloadButton > button {{
        border-radius: 6px;
        min-height: 36px;
        font-size: 13px;
        font-weight: 600;
    }}

    .stButton > button[kind="primary"],
    .stDownloadButton > button[kind="primary"] {{
        background: var(--teal);
        border-color: var(--teal);
        color: #fff;
    }}

    .stTextInput input,
    .stTextArea textarea,
    .stSelectbox [data-baseweb="select"] > div,
    .stDateInput input {{
        font-size: 13px !important;
        border-radius: 6px !important;
    }}

    label {{
        font-size: 12px !important;
        font-weight: 700 !important;
        color: var(--text) !important;
    }}

    /* Remove Streamlit Top Padding */
    [data-testid="stAppViewContainer"] > .main {{
        padding-top: 0 !important;
    }}
    [data-testid="stMainBlockContainer"] {{
        padding-top: 1rem !important;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# CONSTANTS / DATA
# ============================================================

DB_NAME = "TeamRoster"
ROSTER_COLLECTION = "Team Roster Collection"
CASES_COLLECTION = "Cases"
REQUESTS_COLLECTION = "Requests"

AUX_OPTIONS = [
    "Available",
    "Busy - Away",
    "Break",
    "Unscheduled Break",
    "Lunch",
    "Meeting",
    "Coaching",
    "Admin Task",
    "Offline",
]

PRIORITY_ORDER = {
    "Critical": 0,
    "High": 1,
    "Medium": 2,
    "Low": 3,
}

# ============================================================
# MONGODB — SETUP & CONNECTION
# ============================================================

@st.cache_resource(show_spinner=False)
def get_mongo_client():
    try:
        uri = str(st.secrets.get("MONGO_URI", "")).strip()
    except FileNotFoundError:
        uri = ""

    if not uri:
        return None

    try:
        client = MongoClient(
            uri,
            serverSelectionTimeoutMS=2500,
            connectTimeoutMS=2500,
            socketTimeoutMS=5000,
            maxPoolSize=20,
            minPoolSize=1,
            retryWrites=True,
        )
        client.admin.command("ping")
        return client
    except PyMongoError:
        return None


@st.cache_resource(show_spinner=False)
def get_database():
    client = get_mongo_client()
    return client[DB_NAME] if client else None


@st.cache_resource(show_spinner=False)
def get_collections():
    db = get_database()

    if db is None:
        return None

    return (
        db[ROSTER_COLLECTION],
        db[CASES_COLLECTION],
        db[REQUESTS_COLLECTION],
    )


@st.cache_resource(show_spinner=False)
def ensure_indexes():
    collections = get_collections()

    if not collections:
        return False

    roster, cases, requests = collections

    try:
        roster.create_index(
            [("type", 1), ("data.email", 1)],
            name="roster_type_email_lookup",
        )
        roster.create_index(
            [("data.session_token", 1)],
            name="session_token_lookup",
        )
        roster.create_index(
            [("data.role", 1), ("data.status", 1), ("data.aux", 1)],
            name="agent_availability",
        )

        cases.create_index(
            [("case_id", 1)],
            name="case_id_lookup",
        )
        cases.create_index(
            [("assigned_to", 1), ("status", 1)],
            name="case_assignment",
        )
        cases.create_index(
            [("priority", 1), ("due_date", 1)],
            name="case_priority_due",
        )

        requests.create_index(
            [("created_at", -1)],
            name="request_created",
        )
        return True

    except PyMongoError:
        return False


MONGO_ENABLED = get_database() is not None
if MONGO_ENABLED:
    ensure_indexes()


def clear_data_caches():
    load_roster.clear()
    load_cases.clear()
    load_requests.clear()


# ============================================================
# SESSION & PERSISTENT LOGIN (VIA URL QUERY PARAMS)
# ============================================================

def init_session():
    defaults = {
        "authenticated": False,
        "user_data": None,
        "menu": "Dashboard",
        "auth_view": "Sign In",
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if not st.session_state.authenticated:
        token = st.query_params.get("session")
        if token:
            collections = get_collections()
            if collections:
                roster = collections[0]
                user_doc = roster.find_one(
                    {"data.session_token": token, "type": "roster_list", "data.status": "Active"}, 
                    {"_id": 0}
                )
                if user_doc and "data" in user_doc:
                    st.session_state.authenticated = True
                    st.session_state.user_data = user_doc["data"]

init_session()

# ============================================================
# PASSWORDS
# ============================================================

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 210_000
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False

    if not stored.startswith("pbkdf2_sha256$"):
        return hmac.compare_digest(password, stored)

    try:
        _, iterations, salt_hex, digest_hex = stored.split("$")
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


# ============================================================
# CACHED DATA READS
# ============================================================

@st.cache_data(ttl=5, show_spinner=False)
def load_roster():
    collections = get_collections()
    if collections:
        roster, _, _ = collections
        try:
            raw = list(roster.find({"type": "roster_list"}, {"_id": 0}))
            return [x.get("data", {}) for x in raw if "data" in x]
        except PyMongoError:
            pass
    return []


@st.cache_data(ttl=5, show_spinner=False)
def load_cases():
    collections = get_collections()
    if collections:
        _, cases, _ = collections
        try:
            return list(cases.find({}, {"_id": 0}))
        except PyMongoError:
            pass
    return []


@st.cache_data(ttl=5, show_spinner=False)
def load_requests():
    collections = get_collections()
    if collections:
        _, _, requests = collections
        try:
            return list(requests.find({}, {"_id": 0}).sort("created_at", -1))
        except PyMongoError:
            pass
    return []


# ============================================================
# WRITES
# ============================================================

def create_user(data):
    collections = get_collections()
    if collections:
        roster, _, _ = collections

        try:
            if roster.find_one(
                {"type": "roster_list", "data.email": data["email"]},
                {"_id": 1},
            ):
                return False, "An account with this email already exists."

            user_data = dict(data)
            password = user_data.pop("password")
            user_data.pop("confirm_password", None)
            user_data["password_hash"] = hash_password(password)
            user_data["created_at"] = dt.datetime.now()

            record = {
                "type": "roster_list",
                "data": user_data
            }

            roster.insert_one(record)
            clear_data_caches()
            return True, "Account created successfully."

        except DuplicateKeyError:
            return False, "An account with this email already exists."
        except PyMongoError as exc:
            return False, f"Database error: {exc}"

    return False, "Database not connected. Please ensure MongoDB is configured."


def find_user(email, password):
    email = email.strip().lower()
    collections = get_collections()

    if collections:
        roster, _, _ = collections

        try:
            user_doc = roster.find_one(
                {"type": "roster_list", "data.email": email, "data.status": "Active"},
                {"_id": 0},
            )

            if not user_doc or "data" not in user_doc:
                return None

            user = user_doc["data"]
            stored = user.get("password_hash")

            if stored:
                valid = verify_password(password, stored)
            else:
                valid = verify_password(password, user.get("password", ""))
                if valid:
                    roster.update_one(
                        {"type": "roster_list", "data.email": email},
                        {
                            "$set": {"data.password_hash": hash_password(password)},
                            "$unset": {"data.password": ""},
                        },
                    )

            return user if valid else None

        except PyMongoError:
            return None

    return None


def update_case(case_id, updates):
    collections = get_collections()
    if collections:
        _, cases, _ = collections
        try:
            result = cases.update_one({"case_id": case_id}, {"$set": updates})
            clear_data_caches()
            return result.modified_count > 0
        except PyMongoError:
            return False
    return False


def update_agent_aux(email, aux):
    collections = get_collections()
    if collections:
        roster, _, _ = collections
        try:
            roster.update_one(
                {"type": "roster_list", "data.email": email},
                {"$set": {"data.aux": aux}},
            )
            clear_data_caches()
            return True
        except PyMongoError:
            return False
    return False


def create_request(data):
    collections = get_collections()
    if collections:
        _, _, requests = collections
        try:
            requests.insert_one(data)
            clear_data_caches()
            return True
        except PyMongoError:
            return False
    return False


# ============================================================
# CASE HELPERS
# ============================================================

def is_active(case):
    return case.get("status") not in ("Completed", "Closed", "Cancelled")

def due_soon(case):
    due = case.get("due_date")
    if not isinstance(due, dt.datetime):
        return False
    remaining = due - dt.datetime.now()
    return dt.timedelta(0) <= remaining <= dt.timedelta(hours=24)

def stale(case):
    updated = case.get("last_update")
    return (
        isinstance(updated, dt.datetime)
        and dt.datetime.now() - updated > dt.timedelta(hours=24)
    )

def case_sort(case):
    return (
        PRIORITY_ORDER.get(case.get("priority", "Low"), 9),
        case.get("due_date") or dt.datetime.max,
    )

def first_name(user):
    value = user.get("first_name", "")
    if value:
        return value
    name = user.get("name", "")
    return name.split()[0] if name else "User"

def display_name(user):
    value = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    return value or user.get("name") or user.get("email", "User")

def initials(user):
    name = display_name(user)
    pieces = name.split()
    return "".join(x[0] for x in pieces[:2]).upper() or "U"

def agent_label(agent):
    return (
        agent.get("name")
        or f"{agent.get('first_name', '')} {agent.get('last_name', '')}".strip()
        or agent.get("email", "")
    )

def priority_html(priority):
    css = {
        "Critical": "pill-critical",
        "High": "pill-high",
        "Medium": "pill-medium",
        "Low": "pill-low",
    }.get(priority, "pill-low")
    return f'<span class="pill {css}">{priority}</span>'

def status_html(status):
    if status in ("Completed", "Auto-Approved"):
        css = "pill-green"
    elif status in ("Critical", "Breached"):
        css = "pill-critical"
    elif status in ("Pending", "Pending Vendor"):
        css = "pill-high"
    else:
        css = "pill-low"
    return f'<span class="pill {css}">{status}</span>'

def format_due(case):
    due = case.get("due_date")
    if not isinstance(due, dt.datetime):
        return "—"
    today = dt.datetime.now().date()
    if due.date() == today:
        return "Today " + due.strftime("%-I:%M %p")
    return due.strftime("%b %-d, %Y")

def case_dataframe(cases):
    rows = []
    for case in cases:
        rows.append(
            {
                "Case ID": case.get("case_id", ""),
                "Subject": case.get("subject", ""),
                "Priority": case.get("priority", ""),
                "Due Date": format_due(case),
                "Status": case.get("status", ""),
                "Assigned To": case.get("assigned_to", "Unassigned"),
                "Last Update": (
                    case.get("last_update").strftime("%b %-d, %Y")
                    if isinstance(case.get("last_update"), dt.datetime)
                    else "—"
                ),
            }
        )
    return pd.DataFrame(rows)

def available_agents():
    return [
        x for x in load_roster()
        if x.get("role") == "Agent" and x.get("status", "Active") == "Active" and x.get("aux") == "Available"
    ]

def assign_unassigned_cases():
    cases = load_cases()
    unassigned = [x for x in cases if x.get("assigned_to") in ("", None, "Unassigned") and is_active(x)]
    if not unassigned: return 0
    agents = available_agents()
    if not agents: return 0

    loads = Counter(x.get("assigned_to") for x in cases if x.get("assigned_to") not in ("", None, "Unassigned") and is_active(x))
    collections = get_collections()
    changed = 0
    unassigned.sort(key=case_sort)

    for case in unassigned:
        agent = min(agents, key=lambda x: (loads[x.get("email", agent_label(x))], x.get("email", agent_label(x))))
        email = agent.get("email", agent_label(agent))
        updates = {"assigned_to": email, "status": "Assigned", "last_update": dt.datetime.now()}

        if collections:
            _, cases_collection, _ = collections
            try:
                result = cases_collection.update_one(
                    {"case_id": case.get("case_id"), "assigned_to": {"$in": ["", None, "Unassigned"]}},
                    {"$set": updates},
                )
                if result.modified_count:
                    loads[email] += 1
                    changed += 1
            except PyMongoError:
                pass

    if changed:
        clear_data_caches()
    return changed


# ============================================================
# DB CONFIGURATION WARNING & AUTH SCREEN
# ============================================================

def check_db_setup():
    if not MONGO_ENABLED:
        st.error("### 🛑 MongoDB Not Configured")
        st.markdown(
            """
            To use this application, you must connect it to a MongoDB database.
            Please create a folder named `.streamlit` in your project directory,
            and inside it, create a file named `secrets.toml` with your connection string:

            ```toml
            # .streamlit/secrets.toml
            MONGO_URI = "mongodb+srv://<username>:<password>@cluster.mongodb.net/?retryWrites=true&w=majority"
            ```
            """
        )
        st.stop()


def auth_brand_panel():
    st.markdown(
        """
        <section class="auth-brand">
            <div class="brand-mark"></div>
            <div class="brand-name">Hewlett Packard<br>Enterprise</div>
            <h1>HPE CaseFlow</h1>
            <p class="auth-brand-subtitle">Team Task and Case Management System</p>
            <div class="auth-feature">
                <div class="auth-feature-icon">▣</div>
                <div class="auth-feature-copy">
                    <b>Manage Cases</b>
                    <small>Track and resolve tasks efficiently</small>
                </div>
            </div>
            <div class="auth-feature">
                <div class="auth-feature-icon">▰</div>
                <div class="auth-feature-copy">
                    <b>Team Collaboration</b>
                    <small>Work together for better service delivery</small>
                </div>
            </div>
            <div class="auth-feature">
                <div class="auth-feature-icon">◷</div>
                <div class="auth-feature-copy">
                    <b>Real-Time Visibility</b>
                    <small>Stay informed and in control</small>
                </div>
            </div>
            <div class="auth-feature">
                <div class="auth-feature-icon">●</div>
                <div class="auth-feature-copy">
                    <b>Secure Access</b>
                    <small>HPE employees only</small>
                </div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def auth_screen():
    left, right = st.columns([1, 1.25], gap="small", vertical_alignment="top")

    with left:
        auth_brand_panel()

    with right:
        with st.container(border=True):
            st.markdown('<div class="auth-panel-marker"></div>', unsafe_allow_html=True)
            t1, t2 = st.tabs(["Sign In", "Sign Up"])

            with t1:
                st.markdown('<div class="auth-panel-title">Sign In</div>', unsafe_allow_html=True)
                st.markdown('<div class="auth-panel-subtitle">Access your HPE CaseFlow account</div>', unsafe_allow_html=True)

                with st.form("signin_form", clear_on_submit=False):
                    email = st.text_input("HPE Email Address", placeholder="name@hpe.com")
                    password = st.text_input("Password", type="password", placeholder="••••••••")
                    submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)

                if submitted:
                    user = find_user(email, password)
                    if user:
                        session_token = secrets.token_hex(16)
                        collections = get_collections()
                        if collections:
                            collections[0].update_one(
                                {"type": "roster_list", "data.email": user["email"]},
                                {"$set": {"data.session_token": session_token}}
                            )
                            user["session_token"] = session_token
                            
                        st.query_params["session"] = session_token
                        st.session_state.authenticated = True
                        st.session_state.user_data = user
                        st.session_state.menu = "Dashboard"
                        st.rerun()
                    else:
                        st.error("Invalid email, password, or inactive account.")

            with t2:
                st.markdown('<div class="auth-panel-title">Sign Up</div>', unsafe_allow_html=True)
                st.markdown('<div class="auth-panel-subtitle">Create your HPE CaseFlow account</div>', unsafe_allow_html=True)

                with st.form("signup_form", clear_on_submit=True):
                    c1, c2 = st.columns(2, gap="small")
                    with c1:
                        first = st.text_input("First Name")
                        employee_id = st.text_input("Employee ID")
                        birthday = st.date_input("Birthday", value=dt.date(1990, 1, 1))
                        home = st.text_input("Home Address")
                        password = st.text_input("Password", type="password")
                    with c2:
                        last = st.text_input("Last Name")
                        email = st.text_input("HPE Email Address")
                        contact = st.text_input("Contact Number")
                        confirm = st.text_input("Confirm Password", type="password")

                    submitted = st.form_submit_button("Create Account", type="primary", use_container_width=True)

                if submitted:
                    email_clean = email.strip().lower()
                    if not all([first.strip(), last.strip(), employee_id.strip(), email_clean, password, confirm]):
                        st.error("Complete all required fields.")
                    elif not email_clean.endswith("@hpe.com"):
                        st.error("Use your HPE email address.")
                    elif password != confirm:
                        st.error("Passwords do not match.")
                    elif len(password) < 8:
                        st.error("Password must contain at least 8 characters.")
                    else:
                        success, message = create_user(
                            {
                                "first_name": first.strip(),
                                "last_name": last.strip(),
                                "employee_id": employee_id.strip(),
                                "birthday": str(birthday),
                                "email": email_clean,
                                "contact_number": contact.strip(),
                                "home_address": home.strip(),
                                "password": password,
                                "role": "Agent",
                                "status": "Active",
                                "aux": "Available",
                            }
                        )
                        if success: st.success(message)
                        else: st.error(message)


# ============================================================
# AUTH GATE
# ============================================================

check_db_setup()

if not st.session_state.authenticated:
    auth_screen()
    st.stop()


user = st.session_state.user_data or {}
is_admin = user.get("role") == "Admin"
role_name = user.get("role", "Agent")
name = display_name(user)
initial = initials(user)


# ============================================================
# TOP HEADER & PROFILE SECTION
# ============================================================

current_aux = user.get("aux", "Available")

# Restructured layout to place the AUX selector inside a unified Profile box
top1, top2, top_prof = st.columns([3, 4, 4.5])

with top1:
    st.markdown(
        """
        <div class="topbar" style="border:none; box-shadow:none; padding:0; background:transparent;">
            <div class="top-logo">
                <span class="mini-mark"></span>
                HPE CaseFlow
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with top_prof:
    with st.container(border=True):
        c_avatar, c_aux, c_btn = st.columns([2.5, 2, 1])
        
        with c_avatar:
            st.markdown(
                f"""
                <div style="display:flex; align-items:center; height:36px;">
                    <span class="avatar" style="margin-right:10px;">{initial}</span>
                    <div style="line-height:1.2;">
                        <strong style="font-size:12px; color:var(--text);">{name}</strong><br>
                        <span style="font-size:10px; color:var(--muted);">{role_name}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            
        with c_aux:
            selected_aux = st.selectbox(
                "AUX",
                AUX_OPTIONS,
                index=(AUX_OPTIONS.index(current_aux) if current_aux in AUX_OPTIONS else 0),
                label_visibility="collapsed",
                key="profile_aux",
            )
            if selected_aux != current_aux:
                if update_agent_aux(user.get("email"), selected_aux):
                    st.session_state.user_data["aux"] = selected_aux
                    st.toast("AUX status updated.")
                    st.rerun()
                    
        with c_btn:
            if st.button("Sign Out", key="header_signout", use_container_width=True):
                user_email = user.get("email")
                collections = get_collections()
                if collections and user_email:
                    collections[0].update_one(
                        {"type": "roster_list", "data.email": user_email}, 
                        {"$unset": {"data.session_token": ""}}
                    )
                st.query_params.clear()
                st.session_state.authenticated = False
                st.session_state.user_data = None
                st.rerun()

st.markdown("<hr style='margin-top:0; margin-bottom:20px; border-color:var(--border);'>", unsafe_allow_html=True)


# ============================================================
# SIDEBAR
# ============================================================

if is_admin:
    NAV = [
        ("▣", "Dashboard"), ("▤", "Cases"), ("♙", "Agents"), ("◷", "Schedule"),
        ("▧", "Requests"), ("▥", "Reports"), ("☁", "Salesforce"), ("⚙", "Settings"),
    ]
else:
    NAV = [("▣", "Dashboard"), ("▤", "My Cases"), ("◷", "Schedule"), ("▧", "Requests")]

st.sidebar.markdown(
    """
    <div style="display:flex; align-items:center; gap:12px; margin-bottom: 25px;">
        <span style="width:24px; height:14px; border: 2px solid #00A88F; border-radius:1px; display:inline-block;"></span>
        <span style="color:#fff; font-size:16px; font-weight:800; letter-spacing: 0.2px;">HPE CaseFlow</span>
    </div>
    <hr style="border-color: rgba(255,255,255,0.1); margin-bottom: 25px; margin-top: 0;">
    """,
    unsafe_allow_html=True,
)

st.sidebar.markdown(
    '<div style="font-size:11px; color:#8baaa9 !important; font-weight:700; margin-bottom: 20px; letter-spacing: 0.5px;">MENU</div>', 
    unsafe_allow_html=True
)

menu = st.session_state.menu

# Dynamically inject styles for the active button based on the user's selection
st.sidebar.markdown(
    f"""
    <style>
    div[data-testid="stSidebar"] button:has(div:contains(" {menu} ")) {{
        background: #1B4B5A !important;
        border-left: 3px solid var(--teal) !important;
    }}
    </style>
    """,
    unsafe_allow_html=True
)

for icon, label in NAV:
    if st.sidebar.button(f"{icon}  {label}", key=f"nav_{label}"):
        st.session_state.menu = label
        st.rerun()


# ============================================================
# COMMON PAGE HEADER & METRICS
# ============================================================

def page_header(title, subtitle=""):
    st.markdown(f'<div class="page-title">{title}</div>', unsafe_allow_html=True)
    if subtitle: st.markdown(f'<div class="page-subtitle">{subtitle}</div>', unsafe_allow_html=True)

def colored_metric_card(icon, label, value, color_class):
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-icon-wrap {color_class}">{icon}</div>
            <div class="metric-content">
                <div class="metric-label">{label}</div>
                <div class="metric-value">{value}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# AGENT DASHBOARD — SCREEN 3
# ============================================================

def agent_dashboard():
    if st_autorefresh is not None:
        st_autorefresh(interval=60_000, key="agent_dashboard_refresh")

    changed = assign_unassigned_cases()
    if changed: st.toast(f"{changed} case(s) auto-assigned.")

    cases = load_cases()
    active = [x for x in cases if is_active(x)]
    email = user.get("email", "")
    my_cases = [x for x in active if x.get("assigned_to") in (email, name)]

    critical = [x for x in my_cases if x.get("priority") == "Critical"]
    due = [x for x in my_cases if due_soon(x)]
    on_track = [x for x in my_cases if x not in critical and not due_soon(x) and not stale(x)]

    page_header(f"Good Morning, {first_name(user)}!", dt.datetime.now().strftime("%A, %B %-d, %Y"))

    c1, c2, c3, c4 = st.columns(4)
    with c1: colored_metric_card("🟦", "My Active Cases", len(my_cases), "metric-blue")
    with c2: colored_metric_card("🔺", "Critical", len(critical), "metric-red")
    with c3: colored_metric_card("⏱", "Due Soon", len(due), "metric-orange")
    with c4: colored_metric_card("✅", "On Track", len(on_track), "metric-green")

    stale_cases = [x for x in my_cases if stale(x)]
    if stale_cases or critical:
        alert_lines = []
        if stale_cases: alert_lines.append(f"⚠ You have {len(stale_cases)} case(s) not updated for 24+ hours!")
        if critical: alert_lines.append(f"♟ Case #{critical[0].get('case_id')} ({critical[0].get('subject')}) is Critical!")

        st.markdown(
            f"""
            <div class="alert-card">
                <div class="alert-title">⚠ Alerts for You</div>
                {"<br>".join(alert_lines)}
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown('<div class="section-title">My Cases (Sorted by Urgency)</div>', unsafe_allow_html=True)
    if not my_cases:
        st.markdown('<div class="empty">No cases are currently assigned to you.</div>', unsafe_allow_html=True)
        return

    my_cases.sort(key=case_sort)
    df = case_dataframe(my_cases)
    st.dataframe(df, use_container_width=True, hide_index=True, height=260)


# ============================================================
# AGENT MY CASES — SCREEN 4
# ============================================================

def agent_cases():
    cases = [x for x in load_cases() if x.get("assigned_to") in (user.get("email"), name) and is_active(x)]
    cases.sort(key=case_sort)

    page_header("My Cases Management", "Select a case to view and update")

    if not cases:
        st.markdown('<div class="empty">No cases are assigned to you.</div>', unsafe_allow_html=True)
        return

    options = [f"{x.get('case_id')} - {x.get('subject')}" for x in cases]
    selected = st.selectbox("Select Case to View/Update", options)
    case_id = selected.split(" - ", 1)[0]
    case = next(x for x in cases if x.get("case_id") == case_id)

    left, right = st.columns([1, 1], gap="large")

    with left:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Case Details</div>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class="info-grid" style="margin-bottom:20px;">
                <div class="label">Case #</div><div><b>{case.get('case_id')}</b></div>
                <div class="label">Subject</div><div>{case.get('subject')}</div>
                <div class="label">Priority</div><div>{priority_html(case.get('priority'))}</div>
                <div class="label">Due Date</div><div><b>{format_due(case)}</b></div>
            </div>
            <div style="font-size:12px">
                🔗 <a href="{case.get('salesforce_url', '#')}" target="_blank" style="color:var(--teal); font-weight:600;">Contact Vendor/Technician in Salesforce</a>
            </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with right:
        with st.container(border=True):
            with st.form(f"case_update_{case_id}"):
                status_options = ["In Progress", "Pending Vendor", "Assigned", "Completed"]
                current = case.get("status", "Assigned")

                status = st.selectbox("Update Status", status_options, index=(status_options.index(current) if current in status_options else 0))
                breach = st.checkbox("Contract Breached", value=bool(case.get("breach_reason")))

                reason_options = ["SLA Missed", "Vendor Delay", "Customer Delay", "Technical Issue", "Other"]
                reason = st.selectbox(
                    "Breach Reason", reason_options,
                    index=(reason_options.index(case.get("breach_reason")) if case.get("breach_reason") in reason_options else 0),
                    disabled=not breach,
                )

                st.text_area("Generated Automated Notification Email", value=f"Dear Team, Case {case_id} breached SLA due to: {reason}.", disabled=True)

                st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)
                col_a, col_b = st.columns(2)
                with col_a: notify = st.form_submit_button("Send Breach Notification", use_container_width=True)
                with col_b: save = st.form_submit_button("Save Case Update", type="primary", use_container_width=True)

            if notify: st.success(f"Breach notification prepared for Case #{case_id}.")
            if save:
                update_case(case_id, {"status": status, "breach_reason": reason if breach else "", "last_update": dt.datetime.now()})
                st.success("Case update saved.")
                st.rerun()


# ============================================================
# SCHEDULE — SCREEN 5
# ============================================================

def schedule_page(admin=False):
    page_header("My Schedule" if not admin else "Team Schedule Management", "Your scheduled activities" if not admin else "Auto-ensuring queue coverage across all operating hours.")

    if admin: st.info("Interval Optimizer: Auto-ensuring queue coverage across all operating hours.")

    tab_day, tab_week, tab_month = st.tabs(["Day", "Week", "Month"])

    schedule = pd.DataFrame([
        ["08:00 AM - 10:00 AM", "▣", "Work / Case Processing"],
        ["10:00 AM - 10:15 AM", "☕", "Break"],
        ["10:15 AM - 12:00 PM", "▣", "Work / Case Processing"],
        ["12:00 PM - 01:00 PM", "🍴", "Lunch"],
        ["03:00 PM - 03:15 PM", "☕", "Break"],
    ], columns=["Time", "", "Activity"])

    with tab_day:
        left, right = st.columns([5, 2])
        with left:
            st.dataframe(schedule, use_container_width=True, hide_index=True, height=245)
        with right:
            st.markdown(
                f"""
                <div class="card">
                    <div class="section-title" style="margin-top:0;">Coverage</div>
                    <div style="font-size:12px;line-height:2">
                        <b>Tuesday</b><br>
                        {dt.datetime.now().strftime("%B %-d, %Y")}<br><br>
                        <span class="pill pill-green">Available</span>
                        &nbsp; Queue coverage active
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with tab_week:
        st.dataframe(
            pd.DataFrame([
                ["Monday", "09:00 AM - 06:00 PM", "Regular"],
                ["Tuesday", "09:00 AM - 06:00 PM", "Regular"],
                ["Wednesday", "09:00 AM - 06:00 PM", "Regular"],
                ["Thursday", "09:00 AM - 06:00 PM", "Regular"],
                ["Friday", "09:00 AM - 06:00 PM", "Regular"],
            ], columns=["Day", "Hours", "Coverage"]),
            use_container_width=True, hide_index=True,
        )

    with tab_month:
        st.info("Monthly schedule view is ready for schedule data integration.")


# ============================================================
# REQUESTS — SCREEN 6 / 11
# ============================================================

def requests_page(admin=False):
    if admin:
        page_header("Manage Requests", "Review team requests and approval status.")
        requests = load_requests()
        if requests:
            df = pd.DataFrame([{
                "Agent": x.get("requested_by", ""), "Type": x.get("request_type", ""),
                "Start Date": x.get("start_date", ""), "End Date": x.get("end_date", ""),
                "Status": x.get("status", "Pending"),
            } for x in requests])
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.markdown('<div class="empty">No requests found.</div>', unsafe_allow_html=True)
        return

    page_header("Submit Request (Leave / Swap)", "Create a request for schedule or leave changes.")

    with st.form("request_form", border=False):
        st.markdown('<div class="card">', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1: request_type = st.selectbox("Request Type", ["PTO", "Sick Leave", "Schedule Swap", "Other"])
        with c2: start_date = st.date_input("Start Date", value=dt.date.today())
        with c3: end_date = st.date_input("End Date", value=dt.date.today())

        reason = st.text_area("Reason", placeholder="Family event")
        
        col1, col2, col3 = st.columns([1,1,1])
        with col3:
            submitted = st.form_submit_button("Submit Request", type="primary", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    if submitted:
        if end_date < start_date: st.error("End Date cannot be before Start Date.")
        elif not reason.strip(): st.error("Enter a reason.")
        else:
            if create_request({
                "requested_by": user.get("email", name), "request_type": request_type,
                "start_date": str(start_date), "end_date": str(end_date),
                "reason": reason.strip(), "status": "Pending", "created_at": dt.datetime.now(),
            }):
                st.success("Request submitted.")
                st.rerun()

    st.markdown('<div class="section-title">My Requests</div>', unsafe_allow_html=True)
    mine = [x for x in load_requests() if x.get("requested_by") in (user.get("email"), name)]

    if mine:
        st.dataframe(pd.DataFrame([{
            "Date Filed": (x.get("created_at").strftime("%b %-d, %Y") if isinstance(x.get("created_at"), dt.datetime) else ""),
            "Type": x.get("request_type", ""), "Start Date": x.get("start_date", ""),
            "End Date": x.get("end_date", ""), "Status": x.get("status", "Pending"),
        } for x in mine]), use_container_width=True, hide_index=True)
    else:
        st.markdown('<div class="empty">No requests submitted.</div>', unsafe_allow_html=True)


# ============================================================
# ADMIN DASHBOARD — SCREEN 7
# ============================================================

def admin_dashboard():
    cases = [x for x in load_cases() if is_active(x)]
    roster = load_roster()

    critical = [x for x in cases if x.get("priority") == "Critical"]
    due = [x for x in cases if due_soon(x)]
    on_track = [x for x in cases if x not in critical and not due_soon(x) and not stale(x)]

    page_header("Team Overview", "Operational visibility across active cases and agents.")
    c1, c2, c3, c4 = st.columns(4)

    with c1: colored_metric_card("🟦", "Active Cases", len(cases), "metric-blue")
    with c2: colored_metric_card("🔺", "Critical", len(critical), "metric-red")
    with c3: colored_metric_card("⏱", "Due Soon", len(due), "metric-orange")
    with c4: colored_metric_card("✅", "On Track", len(on_track), "metric-green")

    left, right = st.columns(2, gap="large")

    with left:
        st.markdown('<div class="section-title">Agent Status Distribution</div>', unsafe_allow_html=True)
        agents = [x for x in roster if x.get("role") == "Agent"]
        if agents:
            aux_df = pd.DataFrame([{"AUX": x.get("aux", "Available")} for x in agents])
            counts = aux_df["AUX"].value_counts().reset_index()
            counts.columns = ["AUX", "Count"]

            fig = px.pie(counts, names="AUX", values="Count", hole=.55, color_discrete_sequence=px.colors.qualitative.Pastel)
            fig.update_layout(height=280, margin=dict(l=0, r=0, t=20, b=0), showlegend=True)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    with right:
        st.markdown('<div class="section-title">Active Case Distribution</div>', unsafe_allow_html=True)
        assigned = [x for x in cases if x.get("assigned_to") not in ("", None, "Unassigned")]
        if assigned:
            counts = pd.Series([x.get("assigned_to") for x in assigned]).value_counts().reset_index()
            counts.columns = ["Agent", "Cases"]

            fig = px.bar(counts, x="Agent", y="Cases", color_discrete_sequence=["#4285F4"])
            fig.update_layout(height=280, margin=dict(l=0, r=0, t=20, b=0), xaxis_title="", yaxis_title="")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ============================================================
# ADMIN CASES — SCREEN 8
# ============================================================

def admin_cases():
    page_header("All Cases Control", "Search, review and reassign active case work.")
    cases = load_cases()

    search = st.text_input("Search", placeholder="Case ID, subject, priority, assignee...")
    if search.strip():
        term = search.lower().strip()
        cases = [x for x in cases if term in str(x).lower()]

    cases.sort(key=case_sort)

    if cases:
        st.dataframe(case_dataframe(cases), use_container_width=True, hide_index=True, height=300)
    else:
        st.markdown('<div class="empty">No cases found.</div>', unsafe_allow_html=True)
        return

    st.markdown('<div class="section-title">Reassign Case</div>', unsafe_allow_html=True)
    case_ids = [f"{x.get('case_id')} - {x.get('subject')}" for x in cases]
    
    with st.container(border=True):
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1: selected = st.selectbox("Select Case ID", case_ids)
        selected_id = selected.split(" - ", 1)[0]
        with c2:
            agents = [x for x in load_roster() if x.get("role") == "Agent" and x.get("status", "Active") == "Active"]
            agent_options = ["Unassigned"] + [x.get("email") for x in agents if x.get("email")]
            assignee = st.selectbox("Reassign to Agent Email", agent_options)
        with c3:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("Reassign Case", type="primary", use_container_width=True):
                if update_case(selected_id, {"assigned_to": assignee, "status": ("Assigned" if assignee != "Unassigned" else "Pending"), "last_update": dt.datetime.now()}):
                    st.success("Case reassigned.")
                    st.rerun()


# ============================================================
# ADMIN AGENTS — SCREEN 9
# ============================================================

def admin_agents():
    page_header("Agent AUX Monitoring & Kick Control", "Monitor availability and remove agents from active queue coverage.")
    agents = [x for x in load_roster() if x.get("role") == "Agent"]

    if not agents:
        st.markdown('<div class="empty">No agents found.</div>', unsafe_allow_html=True)
        return

    st.markdown(
        """
        <div style="display:grid; grid-template-columns: 2fr 2.5fr 1.5fr 1fr; padding: 10px 15px; border-bottom: 2px solid var(--border); font-weight: 700; font-size: 12px; color: var(--muted);">
            <div>Name</div><div>Email</div><div>AUX Status</div><div>Action</div>
        </div>
        """, unsafe_allow_html=True
    )

    for index, agent in enumerate(agents):
        c1, c2, c3, c4 = st.columns([2, 2.5, 1.5, 1])
        with c1: st.markdown(f"<div style='padding-top:8px; font-size:13px;'>{agent_label(agent)}</div>", unsafe_allow_html=True)
        with c2: st.markdown(f"<div style='padding-top:8px; font-size:13px; color:var(--muted);'>{agent.get('email', '')}</div>", unsafe_allow_html=True)
        
        aux = agent.get("aux", "Available")
        css = ("pill-green" if aux == "Available" else "pill-purple" if aux == "Admin Task" else "pill-high")
        with c3: st.markdown(f"<div style='padding-top:8px;'><span class='pill {css}'>{aux}</span></div>", unsafe_allow_html=True)
        
        with c4:
            if st.button("Kick Agent", key=f"kick_{index}", type="primary"):
                if update_agent_aux(agent.get("email"), "Offline"):
                    st.toast(f"{agent_label(agent)} set to Offline.")
                    st.rerun()
        st.markdown("<hr style='margin:0; border-color:var(--border);'>", unsafe_allow_html=True)


# ============================================================
# ADMIN REPORTS — SCREEN 12
# ============================================================

def admin_reports():
    page_header("Extract Operational Reports", "Download operational data for analysis and reporting purposes.")
    st.markdown(
        """
        <div class="card" style="text-align:center;padding:50px 20px; border: 1px dashed var(--teal);">
            <div style="font-size:48px; color:var(--teal);">▤</div>
            <div style="font-size:18px;font-weight:800;margin-top:10px;">Export Cases to CSV</div>
            <div style="font-size:12px;color:var(--muted);margin:5px 0 20px;">Download all case data for analysis and reporting purposes.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    cases = load_cases()
    df = case_dataframe(cases)
    csv = df.to_csv(index=False).encode("utf-8")

    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.download_button("Export Cases to CSV", csv, file_name="hpe_caseflow_cases.csv", mime="text/csv", type="primary", use_container_width=True)


# ============================================================
# SALESFORCE — SCREEN 13
# ============================================================

def admin_salesforce():
    page_header("Salesforce Integration (Admin Only)", "View Salesforce information without loading it during normal navigation.")
    
    with st.container(border=True):
        url = st.text_input("Direct link:", value="https://example.salesforce.com/")
        st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns([1,2,1])
        with c2: st.link_button("Open in Salesforce", url, use_container_width=True)

    st.markdown('<div class="section-title">Cases — Recently Viewed</div>', unsafe_allow_html=True)
    recent = sorted(load_cases(), key=lambda x: x.get("last_update", dt.datetime.min), reverse=True)[:5]

    if recent:
        st.dataframe(
            pd.DataFrame([{"Case Number": x.get("case_id"), "Subject": x.get("subject"), "Status": x.get("status")} for x in recent]),
            use_container_width=True, hide_index=True,
        )


# ============================================================
# SETTINGS — SCREEN 14
# ============================================================

def admin_settings():
    page_header("System Settings & User Role Management", "Manage user roles across the platform.")
    st.markdown('<div class="section-title">User Role Management</div>', unsafe_allow_html=True)

    roster = load_roster()
    if roster:
        st.dataframe(
            pd.DataFrame([{
                "Name": agent_label(x), "Email": x.get("email", ""),
                "Role": x.get("role", "Agent"), "Status": x.get("status", "Active"), "AUX": x.get("aux", "Available"),
            } for x in roster]),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("No users found.")

    st.markdown('<div class="section-title">System Configuration</div>', unsafe_allow_html=True)
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        c1.metric("MongoDB", "Connected" if MONGO_ENABLED else "Disconnected")
        c2.metric("Database", DB_NAME)
        c3.metric("Roster Collection", ROSTER_COLLECTION)

    st.caption("No personal administrator account or password is hard-coded in this application.")
    if st.button("Clear Application Cache", use_container_width=True):
        clear_data_caches()
        st.success("Cache cleared.")


# ============================================================
# ROUTER
# ============================================================

if is_admin:
    if menu == "Dashboard": admin_dashboard()
    elif menu == "Cases": admin_cases()
    elif menu == "Agents": admin_agents()
    elif menu == "Schedule": schedule_page(admin=True)
    elif menu == "Requests": requests_page(admin=True)
    elif menu == "Reports": admin_reports()
    elif menu == "Salesforce": admin_salesforce()
    elif menu == "Settings": admin_settings()
else:
    if menu == "Dashboard": agent_dashboard()
    elif menu == "My Cases": agent_cases()
    elif menu == "Schedule": schedule_page(admin=False)
    elif menu == "Requests": requests_page(admin=False)
