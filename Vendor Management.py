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
# HPE CASEFLOW — PERFORMANCE + UI VERSION
# ============================================================

st.set_page_config(
    page_title="HPE CaseFlow",
    page_icon="▣",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# DESIGN SYSTEM
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
        padding: .55rem 1.05rem 1.4rem;
    }}

    header[data-testid="stHeader"] {{
        background: transparent;
    }}

    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, #003B49 0%, #002F3A 100%);
        min-width: 180px;
        max-width: 180px;
    }}

    [data-testid="stSidebar"] > div:first-child {{
        padding: .45rem .45rem 1rem;
    }}

    [data-testid="stSidebar"] * {{
        color: #fff !important;
    }}

    [data-testid="stSidebar"] button {{
        width: 100%;
        min-height: 34px;
        border: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
        border-radius: 7px !important;
        text-align: left !important;
        font-size: 12px !important;
        padding: 5px 9px !important;
        margin: 1px 0 !important;
    }}

    [data-testid="stSidebar"] button:hover {{
        background: rgba(0,168,143,.24) !important;
    }}

    .side-brand {{
        padding: 8px 7px 13px;
        border-bottom: 1px solid rgba(255,255,255,.16);
        margin-bottom: 8px;
    }}

    .brand-mark {{
        width: 21px;
        height: 12px;
        border: 2px solid var(--teal);
        border-radius: 1px;
        display: inline-block;
        margin-bottom: 5px;
    }}

    .brand-name {{
        color: #fff;
        font-size: 11px;
        font-weight: 800;
        line-height: 1.08;
    }}

    .side-section {{
        font-size: 10px;
        opacity: .8;
        padding: 7px 8px 3px;
    }}

    .topbar {{
        height: 47px;
        background: #fff;
        border: 1px solid var(--border);
        border-radius: 7px;
        display: flex;
        align-items: center;
        padding: 0 10px;
        gap: 14px;
        box-shadow: 0 1px 4px rgba(0,0,0,.04);
        margin-bottom: 12px;
    }}

    .top-logo {{
        color: var(--navy);
        font-weight: 800;
        font-size: 13px;
        white-space: nowrap;
    }}

    .top-logo .mini-mark {{
        display: inline-block;
        width: 13px;
        height: 8px;
        border: 2px solid var(--teal);
        margin-right: 5px;
        vertical-align: middle;
    }}

    .top-spacer {{
        flex: 1;
    }}

    .user-chip {{
        font-size: 11px;
        color: var(--text);
        white-space: nowrap;
    }}

    .avatar {{
        display: inline-flex;
        width: 23px;
        height: 23px;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        background: var(--navy);
        color: #fff;
        font-size: 9px;
        font-weight: 800;
        margin-right: 5px;
    }}

    .page-title {{
        font-size: 23px;
        font-weight: 800;
        color: var(--text);
        margin: 4px 0 2px;
    }}

    .page-subtitle {{
        color: var(--muted);
        font-size: 11px;
        margin-bottom: 13px;
    }}

    .section-title {{
        color: var(--text);
        font-size: 15px;
        font-weight: 800;
        margin: 10px 0 7px;
    }}

    .metric-card {{
        background: #fff;
        border: 1px solid var(--border);
        border-radius: 7px;
        padding: 10px 11px;
        min-height: 68px;
        box-shadow: 0 1px 3px rgba(0,0,0,.035);
    }}

    .metric-label {{
        color: var(--muted);
        font-size: 10px;
        font-weight: 700;
        margin-bottom: 4px;
    }}

    .metric-value {{
        color: var(--text);
        font-size: 21px;
        line-height: 1;
        font-weight: 800;
    }}

    .metric-icon {{
        float: left;
        margin-right: 9px;
        width: 28px;
        height: 28px;
        border-radius: 7px;
        background: #edf7f5;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 14px;
    }}

    .alert-card {{
        background: #fff1f1;
        border: 1px solid #ffd0d0;
        border-left: 3px solid {RED};
        border-radius: 5px;
        padding: 8px 10px;
        margin: 9px 0 13px;
        font-size: 10px;
    }}

    .alert-title {{
        font-size: 12px;
        font-weight: 800;
        margin-bottom: 3px;
    }}

    .card {{
        background: #fff;
        border: 1px solid var(--border);
        border-radius: 7px;
        padding: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,.035);
    }}

    [data-testid="stHorizontalBlock"] {{
        align-items: flex-start !important;
    }}

    .auth-brand {{
        min-height: 560px;
        height: 100%;
        background: linear-gradient(150deg, #003B49 0%, #002C38 100%);
        color: #fff;
        border-radius: 9px 0 0 9px;
        padding: 30px 27px;
    }}

    .auth-brand h1 {{
        font-size: 29px;
        margin: 14px 0 4px;
        color: #fff;
    }}

    .auth-brand-subtitle {{
        color: #e5f1f3 !important;
        font-size: 11px !important;
        line-height: 1.45;
        max-width: 250px;
        margin: 0 0 24px;
    }}

    .auth-feature {{
        display: flex;
        gap: 10px;
        margin-top: 18px;
        align-items: center;
    }}

    .auth-feature-icon {{
        width: 25px;
        height: 25px;
        border-radius: 5px;
        background: rgba(0,168,143,.18);
        color: #16d4b5;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 13px;
    }}

    .auth-feature b {{
        font-size: 11px;
        display: block;
    }}

    .auth-feature small {{
        color: #c8dcdf;
        font-size: 9px;
    }}

    div[data-testid="stVerticalBlockBorderWrapper"]:has(.auth-panel-marker) {{
        min-height: 560px;
        background: #fff;
        border: 1px solid var(--border);
        border-radius: 0 9px 9px 0;
        padding: 0 !important;
        box-sizing: border-box;
        box-shadow: 0 5px 20px rgba(0,0,0,.06);
    }}

    div[data-testid="stVerticalBlockBorderWrapper"]:has(.auth-panel-marker) > div {{
        padding: 24px 28px 22px !important;
    }}

    .auth-panel-title {{
        margin: 6px 0 2px;
        font-size: 19px;
        font-weight: 800;
        color: var(--text);
    }}

    .auth-panel-subtitle {{
        margin: 0 0 14px;
        color: var(--muted);
        font-size: 10px;
    }}

    .auth-panel-marker {{
        display: none;
    }}

    .pill {{
        display: inline-block;
        padding: 3px 8px;
        border-radius: 10px;
        font-size: 9px;
        font-weight: 800;
        white-space: nowrap;
    }}

    .pill-critical {{ background:#ffe3e3; color:#c92d2d; }}
    .pill-high {{ background:#fff0dd; color:#b65e00; }}
    .pill-medium {{ background:#fff6ce; color:#866900; }}
    .pill-low {{ background:#e9f0f2; color:#4c6871; }}
    .pill-green {{ background:#dcf7ef; color:#08795e; }}
    .pill-purple {{ background:#eee8ff; color:#6240bf; }}

    .info-grid {{
        display: grid;
        grid-template-columns: 110px 1fr;
        gap: 8px 10px;
        font-size: 11px;
    }}

    .info-grid .label {{
        color: var(--muted);
        font-weight: 700;
    }}

    .empty {{
        text-align: center;
        padding: 30px 10px;
        color: var(--muted);
        font-size: 12px;
    }}

    div[data-testid="stDataFrame"] {{
        border: 1px solid var(--border);
        border-radius: 7px;
        overflow: hidden;
    }}

    .stButton > button,
    .stDownloadButton > button {{
        border-radius: 5px;
        min-height: 31px;
        font-size: 11px;
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
        font-size: 11px !important;
    }}

    label {{
        font-size: 10px !important;
        font-weight: 700 !important;
    }}

    @media (max-width: 900px) {{
        [data-testid="stSidebar"] {{
            min-width: 150px;
            max-width: 150px;
        }}
        .auth-brand {{
            border-radius: 7px;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.auth-panel-marker) {{
            border-radius: 7px;
            min-height: 0;
        }}
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
    "Break",
    "Lunch",
    "Meeting",
    "Training",
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
            [("type", 1), ("email", 1)],
            name="roster_type_email_lookup",
        )
        roster.create_index(
            [("session_token", 1)],
            name="session_token_lookup",
        )
        roster.create_index(
            [("role", 1), ("status", 1), ("aux", 1)],
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

    # Check for persistent login via query parameter
    if not st.session_state.authenticated:
        token = st.query_params.get("session")
        if token:
            collections = get_collections()
            if collections:
                roster = collections[0]
                user = roster.find_one({"session_token": token, "type": "roster_list", "status": "Active"}, {"_id": 0})
                if user:
                    st.session_state.authenticated = True
                    st.session_state.user_data = user

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
            return list(
                roster.find(
                    {"type": "roster_list"},
                    {
                        "_id": 0,
                        "type": 1,
                        "first_name": 1,
                        "last_name": 1,
                        "name": 1,
                        "email": 1,
                        "employee_id": 1,
                        "role": 1,
                        "status": 1,
                        "aux": 1,
                    },
                )
            )
        except PyMongoError:
            pass
    return []


@st.cache_data(ttl=5, show_spinner=False)
def load_cases():
    collections = get_collections()
    if collections:
        _, cases, _ = collections
        try:
            return list(
                cases.find(
                    {},
                    {"_id": 0},
                )
            )
        except PyMongoError:
            pass
    return []


@st.cache_data(ttl=5, show_spinner=False)
def load_requests():
    collections = get_collections()
    if collections:
        _, _, requests = collections
        try:
            return list(
                requests.find(
                    {},
                    {"_id": 0},
                ).sort("created_at", -1)
            )
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
                {
                    "type": "roster_list",
                    "email": data["email"],
                },
                {"_id": 1},
            ):
                return False, "An account with this email already exists."

            record = dict(data)
            # Ensuring type is saved strictly as "roster_list" string
            record["type"] = "roster_list"
            record["password_hash"] = hash_password(
                record.pop("password")
            )
            record.pop("confirm_password", None)
            record["created_at"] = dt.datetime.now()

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
            user = roster.find_one(
                {
                    "type": "roster_list",
                    "email": email,
                    "status": "Active",
                },
                {"_id": 0},
            )

            if not user:
                return None

            stored = user.get("password_hash")

            if stored:
                valid = verify_password(password, stored)
            else:
                valid = verify_password(
                    password,
                    user.get("password", ""),
                )

                if valid:
                    roster.update_one(
                        {"email": email},
                        {
                            "$set": {
                                "password_hash": hash_password(password)
                            },
                            "$unset": {"password": ""},
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
            result = cases.update_one(
                {"case_id": case_id},
                {"$set": updates},
            )
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
                {"email": email},
                {"$set": {"aux": aux}},
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
    return case.get("status") not in (
        "Completed",
        "Closed",
        "Cancelled",
    )

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
    value = (
        f"{user.get('first_name', '')} "
        f"{user.get('last_name', '')}"
    ).strip()
    return value or user.get("name") or user.get("email", "User")

def initials(user):
    name = display_name(user)
    pieces = name.split()
    return "".join(x[0] for x in pieces[:2]).upper() or "U"

def agent_label(agent):
    return (
        agent.get("name")
        or f"{agent.get('first_name', '')} "
           f"{agent.get('last_name', '')}".strip()
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
        if x.get("role") == "Agent"
        and x.get("status", "Active") == "Active"
        and x.get("aux") == "Available"
    ]

def assign_unassigned_cases():
    cases = load_cases()
    unassigned = [
        x for x in cases
        if x.get("assigned_to") in ("", None, "Unassigned")
        and is_active(x)
    ]
    if not unassigned:
        return 0
    agents = available_agents()
    if not agents:
        return 0

    loads = Counter(
        x.get("assigned_to")
        for x in cases
        if x.get("assigned_to")
        not in ("", None, "Unassigned")
        and is_active(x)
    )

    collections = get_collections()
    changed = 0
    unassigned.sort(key=case_sort)

    for case in unassigned:
        agent = min(
            agents,
            key=lambda x: (
                loads[x.get("email", agent_label(x))],
                x.get("email", agent_label(x)),
            ),
        )

        email = agent.get("email", agent_label(agent))
        updates = {
            "assigned_to": email,
            "status": "Assigned",
            "last_update": dt.datetime.now(),
        }

        if collections:
            _, cases_collection, _ = collections
            try:
                result = cases_collection.update_one(
                    {
                        "case_id": case.get("case_id"),
                        "assigned_to": {
                            "$in": ["", None, "Unassigned"]
                        },
                    },
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
    """Forces the user to configure MongoDB to avoid local failover behaviors."""
    if not MONGO_ENABLED:
        st.error("### 🛑 MongoDB Not Configured")
        st.markdown(
            "To use this application, you must connect it to a MongoDB database. "
            "Please create a folder named `.streamlit` in your project directory, "
            "and inside it, create a file named `secrets.toml` with your connection string:\n\n"
            "```toml\n"
            "# .streamlit/secrets.toml\n"
            'MONGO_URI = "mongodb+srv://<username>:<password>@cluster.mongodb.net/?retryWrites=true&w=majority"\n'
            "
