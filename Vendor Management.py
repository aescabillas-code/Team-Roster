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
# Interface follows the uploaded 14-screen reference image.
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
ORANGE = "#F28C28"
YELLOW = "#F6C344"
PURPLE = "#7656D6"

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

    /* Authentication layout: keep both panels pinned to the top. */
    [data-testid="stHorizontalBlock"] {{
        align-items: flex-start !important;
    }}

    .auth-shell {{
        min-height: 0;
        display: block;
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

    .auth-brand p {{
        color: #e5f1f3;
        font-size: 11px;
        line-height: 1.45;
        max-width: 250px;
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

    /* Authentication card: style the real Streamlit container.
       No HTML wrapper is placed around Streamlit widgets. */
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

    .auth-card h2 {{
        font-size: 19px;
        margin: 7px 0 2px;
    }}

    .auth-card p {{
        font-size: 10px;
        color: var(--muted);
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

    .table-note {{
        color: var(--muted);
        font-size: 10px;
        margin-bottom: 5px;
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

    .profile-box {{
        background: #fff;
        border: 1px solid var(--border);
        border-radius: 7px;
        padding: 14px;
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

DEFAULT_CASES = [
    {
        "case_id": "0000156",
        "subject": "Network equipment delay",
        "customer": "Enterprise Client",
        "priority": "Critical",
        "status": "In Progress",
        "progress": 70,
        "last_update": dt.datetime.now(),
        "due_date": dt.datetime.now() + dt.timedelta(hours=3),
        "assigned_to": "Unassigned",
        "salesforce_url": "https://example.salesforce.com/",
        "breach_reason": "SLA Missed",
    },
    {
        "case_id": "0000143",
        "subject": "Server replacement",
        "customer": "Enterprise Client",
        "priority": "High",
        "status": "Pending Vendor",
        "progress": 55,
        "last_update": dt.datetime.now() - dt.timedelta(hours=2),
        "due_date": dt.datetime.now() + dt.timedelta(hours=8),
        "assigned_to": "Unassigned",
        "salesforce_url": "https://example.salesforce.com/",
        "breach_reason": "",
    },
    {
        "case_id": "0000132",
        "subject": "Software license",
        "customer": "Enterprise Client",
        "priority": "Medium",
        "status": "Assigned",
        "progress": 40,
        "last_update": dt.datetime.now() - dt.timedelta(hours=6),
        "due_date": dt.datetime.now() + dt.timedelta(days=1),
        "assigned_to": "Unassigned",
        "salesforce_url": "https://example.salesforce.com/",
        "breach_reason": "",
    },
    {
        "case_id": "0000128",
        "subject": "Site installation",
        "customer": "Enterprise Client",
        "priority": "Medium",
        "status": "In Progress",
        "progress": 25,
        "last_update": dt.datetime.now() - dt.timedelta(hours=26),
        "due_date": dt.datetime.now() + dt.timedelta(hours=5),
        "assigned_to": "Unassigned",
        "salesforce_url": "https://example.salesforce.com/",
        "breach_reason": "",
    },
    {
        "case_id": "0000120",
        "subject": "Access request",
        "customer": "Enterprise Client",
        "priority": "Low",
        "status": "Assigned",
        "progress": 15,
        "last_update": dt.datetime.now() - dt.timedelta(hours=4),
        "due_date": dt.datetime.now() + dt.timedelta(days=3),
        "assigned_to": "Unassigned",
        "salesforce_url": "https://example.salesforce.com/",
        "breach_reason": "",
    },
]


# ============================================================
# SESSION
# ============================================================

def init_session():
    defaults = {
        "authenticated": False,
        "user_data": None,
        "mock_db": [],
        "cases_db": [],
        "requests_db": [],
        "menu": "Dashboard",
        "auth_view": "Sign In",
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


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
# MONGODB — FAST / NON-BLOCKING WHEN NOT CONFIGURED
# ============================================================

@st.cache_resource(show_spinner=False)
def get_mongo_client():
    try:
        uri = str(st.secrets.get("MONGO_URI", "")).strip()
    except Exception:
        uri = ""

    # Important: do not try localhost when no URI is configured.
    if not uri:
        return None

    try:
        client = MongoClient(
            uri,
            serverSelectionTimeoutMS=1200,
            connectTimeoutMS=1200,
            socketTimeoutMS=2500,
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
            [("email", 1)],
            name="email_lookup",
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
# FALLBACK MODE
# ============================================================

def initialize_mock_data():
    if not st.session_state.cases_db:
        st.session_state.cases_db = [
            dict(x) for x in DEFAULT_CASES
        ]


if not MONGO_ENABLED:
    initialize_mock_data()


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
                    {},
                    {
                        "_id": 0,
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

    return [dict(x) for x in st.session_state.mock_db]


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

    return [dict(x) for x in st.session_state.cases_db]


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

    return [dict(x) for x in st.session_state.requests_db]


# ============================================================
# WRITES
# ============================================================

def create_user(data):
    collections = get_collections()

    if collections:
        roster, _, _ = collections

        try:
            if roster.find_one(
                {"email": data["email"]},
                {"_id": 1},
            ):
                return False, "An account with this email already exists."

            record = dict(data)
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

    if any(
        x.get("email", "").lower() == data["email"].lower()
        for x in st.session_state.mock_db
    ):
        return False, "An account with this email already exists."

    record = dict(data)
    record["password_hash"] = hash_password(
        record.pop("password")
    )
    record.pop("confirm_password", None)
    record["created_at"] = dt.datetime.now()
    st.session_state.mock_db.append(record)
    clear_data_caches()

    return True, "Account created successfully."


def find_user(email, password):
    email = email.strip().lower()
    collections = get_collections()

    if collections:
        roster, _, _ = collections

        try:
            user = roster.find_one(
                {
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

    for user in st.session_state.mock_db:
        if (
            user.get("email", "").lower() == email
            and user.get("status", "Active") == "Active"
            and verify_password(
                password,
                user.get(
                    "password_hash",
                    user.get("password", ""),
                ),
            )
        ):
            return dict(user)

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

    for case in st.session_state.cases_db:
        if case.get("case_id") == case_id:
            case.update(updates)
            clear_data_caches()
            return True

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

    for agent in st.session_state.mock_db:
        if agent.get("email") == email:
            agent["aux"] = aux
            clear_data_caches()
            return True

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

    st.session_state.requests_db.append(dict(data))
    clear_data_caches()
    return True


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
        else:
            for local_case in st.session_state.cases_db:
                if local_case.get("case_id") == case.get("case_id"):
                    local_case.update(updates)
                    loads[email] += 1
                    changed += 1
                    break

    if changed:
        clear_data_caches()

    return changed


# ============================================================
# AUTH SCREEN — EXACT 2-PANEL STYLE
# ============================================================

def auth_brand_panel():
    st.markdown(
        """
        <div class="auth-brand">
            <div class="brand-mark"></div>
            <div style="font-size:14px;font-weight:800;line-height:1.05">
                Hewlett Packard<br>Enterprise
            </div>

            <h1>HPE CaseFlow</h1>
            <p>
                Team Task and Case Management System
            </p>

            <div class="auth-feature">
                <div class="auth-feature-icon">▣</div>
                <div>
                    <b>Manage Cases</b>
                    <small>Track and resolve tasks efficiently</small>
                </div>
            </div>

            <div class="auth-feature">
                <div class="auth-feature-icon">▰</div>
                <div>
                    <b>Team Collaboration</b>
                    <small>Work together for better service delivery</small>
                </div>
            </div>

            <div class="auth-feature">
                <div class="auth-feature-icon">◷</div>
                <div>
                    <b>Real-Time Visibility</b>
                    <small>Stay informed and in control</small>
                </div>
            </div>

            <div class="auth-feature">
                <div class="auth-feature-icon">●</div>
                <div>
                    <b>Secure Access</b>
                    <small>HPE employees only</small>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def auth_screen():
    """Two-panel sign-in/sign-up screen matching the supplied reference."""
    left, right = st.columns(
        [1, 1.25],
        gap="small",
        vertical_alignment="top",
    )

    with left:
        auth_brand_panel()

    with right:
        # Streamlit's native container keeps all widgets in the same
        # component tree, avoiding malformed HTML and the large blank area.
        with st.container(border=True):
            st.markdown(
                '<div class="auth-panel-marker"></div>',
                unsafe_allow_html=True,
            )

            t1, t2 = st.tabs(["Sign In", "Sign Up"])

            with t1:
                st.markdown(
                    '<div class="auth-panel-title">Sign In</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    '<div class="auth-panel-subtitle">Access your HPE CaseFlow account</div>',
                    unsafe_allow_html=True,
                )

                with st.form("signin_form", clear_on_submit=False):
                    email = st.text_input(
                        "HPE Email Address",
                        placeholder="name@hpe.com",
                    )
                    password = st.text_input(
                        "Password",
                        type="password",
                        placeholder="••••••••",
                    )

                    submitted = st.form_submit_button(
                        "Sign In",
                        type="primary",
                        use_container_width=True,
                    )

                if submitted:
                    user = find_user(email, password)

                    if user:
                        st.session_state.authenticated = True
                        st.session_state.user_data = user
                        st.session_state.menu = "Dashboard"
                        st.rerun()
                    else:
                        st.error(
                            "Invalid email, password, or inactive account."
                        )

            with t2:
                st.markdown(
                    '<div class="auth-panel-title">Sign Up</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    '<div class="auth-panel-subtitle">Create your HPE CaseFlow account</div>',
                    unsafe_allow_html=True,
                )

                with st.form("signup_form", clear_on_submit=True):
                    c1, c2 = st.columns(2, gap="small")

                    with c1:
                        first = st.text_input("First Name")
                        employee_id = st.text_input("Employee ID")
                        birthday = st.date_input(
                            "Birthday",
                            value=dt.date(1990, 1, 1),
                        )
                        home = st.text_input("Home Address")
                        password = st.text_input(
                            "Password",
                            type="password",
                        )

                    with c2:
                        last = st.text_input("Last Name")
                        email = st.text_input("HPE Email Address")
                        contact = st.text_input("Contact Number")
                        confirm = st.text_input(
                            "Confirm Password",
                            type="password",
                        )

                    submitted = st.form_submit_button(
                        "Create Account",
                        type="primary",
                        use_container_width=True,
                    )

                if submitted:
                    email_clean = email.strip().lower()

                    if not all(
                        [
                            first.strip(),
                            last.strip(),
                            employee_id.strip(),
                            email_clean,
                            password,
                            confirm,
                        ]
                    ):
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

                        if success:
                            st.success(message)
                        else:
                            st.error(message)


# ============================================================
# AUTH GATE
# ============================================================

if not st.session_state.authenticated:
    auth_screen()
    st.stop()


user = st.session_state.user_data or {}
is_admin = user.get("role") == "Admin"
role_name = user.get("role", "Agent")
name = display_name(user)
initial = initials(user)


# ============================================================
# TOP HEADER — MATCH REFERENCE
# ============================================================

current_aux = (
    "Admin Task"
    if is_admin
    else user.get("aux", "Available")
)

top1, top2, top3, top4 = st.columns(
    [2.3, 2.6, 3.2, 1.1]
)

with top1:
    st.markdown(
        f"""
        <div class="topbar">
            <div class="top-logo">
                <span class="mini-mark"></span>
                HPE CaseFlow
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with top2:
    st.markdown(
        '<div style="height:1px"></div>',
        unsafe_allow_html=True,
    )
    aux_options = ["Admin Task"] if is_admin else AUX_OPTIONS
    selected_aux = st.selectbox(
        "Current AUX Status",
        aux_options,
        index=(
            aux_options.index(current_aux)
            if current_aux in aux_options
            else 0
        ),
        label_visibility="collapsed",
        key="header_aux",
    )

    if not is_admin and selected_aux != current_aux:
        if update_agent_aux(
            user.get("email"),
            selected_aux,
        ):
            st.session_state.user_data["aux"] = selected_aux
            st.toast("AUX status updated.")

with top3:
    st.markdown(
        f"""
        <div style="height:47px;display:flex;align-items:center;
                    justify-content:flex-end;font-size:10px">
            <span class="avatar">{initial}</span>
            <span class="user-chip">
                User: <b>{name}</b> ({role_name})
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

with top4:
    if st.button(
        "Sign Out",
        key="header_signout",
        use_container_width=True,
    ):
        st.session_state.authenticated = False
        st.session_state.user_data = None
        st.rerun()


# ============================================================
# SIDEBAR — CLICKABLE WORDS, NO RADIO/SELECTBOX
# ============================================================

if is_admin:
    NAV = [
        ("▣", "Dashboard"),
        ("▤", "Cases"),
        ("♙", "Agents"),
        ("◷", "Schedule"),
        ("▧", "Requests"),
        ("▥", "Reports"),
        ("☁", "Salesforce"),
        ("⚙", "Settings"),
    ]
else:
    NAV = [
        ("▣", "Dashboard"),
        ("▤", "My Cases"),
        ("◷", "Schedule"),
        ("▧", "Requests"),
    ]

st.sidebar.markdown(
    """
    <div class="side-brand">
        <span class="brand-mark"></span>
        <div class="brand-name">HPE CaseFlow</div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.sidebar.markdown(
    f'<div class="side-section">Menu ({role_name})</div>',
    unsafe_allow_html=True,
)

for icon, label in NAV:
    if st.sidebar.button(
        f"{icon}  {label}",
        key=f"nav_{label}",
    ):
        st.session_state.menu = label
        st.rerun()

menu = st.session_state.menu

# A small visual marker under the active page.
st.sidebar.markdown(
    f"""
    <div style="font-size:9px;color:#8be7da;
                padding:8px 9px;border-top:1px solid rgba(255,255,255,.10)">
        ● {menu}
    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# COMMON PAGE HEADER
# ============================================================

def page_header(title, subtitle=""):
    st.markdown(
        f'<div class="page-title">{title}</div>',
        unsafe_allow_html=True,
    )
    if subtitle:
        st.markdown(
            f'<div class="page-subtitle">{subtitle}</div>',
            unsafe_allow_html=True,
        )


def metric_card(icon, label, value):
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-icon">{icon}</div>
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# AGENT DASHBOARD — SCREEN 3
# ============================================================

def agent_dashboard():
    if st_autorefresh is not None:
        st_autorefresh(
            interval=60_000,
            key="agent_dashboard_refresh",
        )

    changed = assign_unassigned_cases()

    if changed:
        st.toast(f"{changed} case(s) auto-assigned.")

    cases = load_cases()
    active = [x for x in cases if is_active(x)]

    email = user.get("email", "")
    my_cases = [
        x for x in active
        if x.get("assigned_to") in (email, name)
    ]

    critical = [
        x for x in my_cases
        if x.get("priority") == "Critical"
    ]

    due = [
        x for x in my_cases
        if due_soon(x)
    ]

    on_track = [
        x for x in my_cases
        if x not in critical
        and not due_soon(x)
        and not stale(x)
    ]

    page_header(
        f"Good Morning, {first_name(user)}!",
        dt.datetime.now().strftime("%A, %B %-d, %Y"),
    )

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        metric_card("▣", "My Active Cases", len(my_cases))
    with c2:
        metric_card("▲", "Critical", len(critical))
    with c3:
        metric_card("◷", "Due Soon", len(due))
    with c4:
        metric_card("✓", "On Track", len(on_track))

    stale_cases = [x for x in my_cases if stale(x)]

    if stale_cases or critical:
        alert_lines = []

        if stale_cases:
            alert_lines.append(
                f"⚠ You have {len(stale_cases)} case(s) not updated for 24+ hours!"
            )

        if critical:
            alert_lines.append(
                f"♟ Case #{critical[0].get('case_id')} "
                f"({critical[0].get('subject')}) is Critical!"
            )

        st.markdown(
            f"""
            <div class="alert-card">
                <div class="alert-title">Alerts for You</div>
                {"<br>".join(alert_lines)}
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="section-title">My Cases (Sorted by Urgency)</div>',
        unsafe_allow_html=True,
    )

    if not my_cases:
        st.markdown(
            '<div class="card empty">No cases are currently assigned to you.</div>',
            unsafe_allow_html=True,
        )
        return

    my_cases.sort(key=case_sort)

    df = case_dataframe(my_cases)

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=260,
        column_config={
            "Priority": st.column_config.TextColumn(
                "Priority",
            ),
        },
    )


# ============================================================
# AGENT MY CASES — SCREEN 4
# ============================================================

def agent_cases():
    cases = [
        x for x in load_cases()
        if x.get("assigned_to")
        in (user.get("email"), name)
        and is_active(x)
    ]

    cases.sort(key=case_sort)

    page_header(
        "My Cases Management",
        "Select a case to view and update",
    )

    if not cases:
        st.markdown(
            '<div class="card empty">No cases are assigned to you.</div>',
            unsafe_allow_html=True,
        )
        return

    options = [
        f"{x.get('case_id')} - {x.get('subject')}"
        for x in cases
    ]

    selected = st.selectbox(
        "Select Case to View/Update",
        options,
    )

    case_id = selected.split(" - ", 1)[0]

    case = next(
        x for x in cases
        if x.get("case_id") == case_id
    )

    left, right = st.columns(
        [1.05, 1.15],
        gap="medium",
    )

    with left:
        st.markdown(
            '<div class="card">',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="section-title">Case Details</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            <div class="info-grid">
                <div class="label">Case #</div>
                <div><b>{case.get('case_id')}</b></div>

                <div class="label">Subject</div>
                <div>{case.get('subject')}</div>

                <div class="label">Priority</div>
                <div>{priority_html(case.get('priority'))}</div>

                <div class="label">Due Date</div>
                <div><b>{format_due(case)}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            <div style="margin-top:15px;font-size:10px">
                🔗 <a href="{case.get('salesforce_url', '#')}"
                target="_blank">Contact Vendor/Technician in Salesforce</a>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        with st.form(
            f"case_update_{case_id}"
        ):
            status_options = [
                "In Progress",
                "Pending Vendor",
                "Assigned",
                "Completed",
            ]

            current = case.get("status", "Assigned")

            status = st.selectbox(
                "Update Status",
                status_options,
                index=(
                    status_options.index(current)
                    if current in status_options
                    else 0
                ),
            )

            breach = st.checkbox(
                "Contract Breached",
                value=bool(case.get("breach_reason")),
            )

            reason_options = [
                "SLA Missed",
                "Vendor Delay",
                "Customer Delay",
                "Technical Issue",
                "Other",
            ]

            reason = st.selectbox(
                "Breach Reason",
                reason_options,
                index=(
                    reason_options.index(
                        case.get("breach_reason")
                    )
                    if case.get("breach_reason")
                    in reason_options
                    else 0
                ),
                disabled=not breach,
            )

            st.text_area(
                "Generated Automated Notification Email",
                value=(
                    f"Dear Team, Case {case_id} breached SLA "
                    f"due to: {reason}."
                ),
                disabled=True,
            )

            notify = st.form_submit_button(
                "Send Breach Notification",
                type="primary",
                use_container_width=True,
            )

            save = st.form_submit_button(
                "Save Case Update",
                use_container_width=True,
            )

        if notify:
            st.success(
                f"Breach notification prepared for Case #{case_id}."
            )

        if save:
            update_case(
                case_id,
                {
                    "status": status,
                    "breach_reason": reason if breach else "",
                    "last_update": dt.datetime.now(),
                },
            )
            st.success("Case update saved.")
            st.rerun()


# ============================================================
# SCHEDULE — SCREEN 5
# ============================================================

def schedule_page(admin=False):
    page_header(
        "Team Schedule Management" if admin else "My Schedule",
        "Auto-ensuring queue coverage across all operating hours."
        if admin
        else "Your scheduled activities",
    )

    if admin:
        st.info(
            "Interval Optimizer: Auto-ensuring queue coverage "
            "across all operating hours."
        )

    tab_day, tab_week, tab_month = st.tabs(
        ["Day", "Week", "Month"]
    )

    schedule = pd.DataFrame(
        [
            ["08:00 AM - 10:00 AM", "▣", "Work / Case Processing"],
            ["10:00 AM - 10:15 AM", "☕", "Break"],
            ["10:15 AM - 12:00 PM", "▣", "Work / Case Processing"],
            ["12:00 PM - 01:00 PM", "🍴", "Lunch"],
            ["03:00 PM - 03:15 PM", "☕", "Break"],
        ],
        columns=["Time", "", "Activity"],
    )

    with tab_day:
        left, right = st.columns([5, 2])

        with left:
            st.dataframe(
                schedule,
                use_container_width=True,
                hide_index=True,
                height=245,
            )

        with right:
            st.markdown(
                f"""
                <div class="card">
                    <div class="section-title">Coverage</div>
                    <div style="font-size:11px;line-height:2">
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
            pd.DataFrame(
                [
                    ["Monday", "09:00 AM - 06:00 PM", "Regular"],
                    ["Tuesday", "09:00 AM - 06:00 PM", "Regular"],
                    ["Wednesday", "09:00 AM - 06:00 PM", "Regular"],
                    ["Thursday", "09:00 AM - 06:00 PM", "Regular"],
                    ["Friday", "09:00 AM - 06:00 PM", "Regular"],
                ],
                columns=["Day", "Hours", "Coverage"],
            ),
            use_container_width=True,
            hide_index=True,
        )

    with tab_month:
        st.info("Monthly schedule view is ready for schedule data integration.")


# ============================================================
# REQUESTS — SCREEN 6 / 11
# ============================================================

def requests_page(admin=False):
    if admin:
        page_header(
            "Manage Requests",
            "Review team requests and approval status.",
        )

        requests = load_requests()

        if requests:
            df = pd.DataFrame(
                [
                    {
                        "Agent": x.get("requested_by", ""),
                        "Type": x.get("request_type", ""),
                        "Start Date": x.get("start_date", ""),
                        "End Date": x.get("end_date", ""),
                        "Status": x.get("status", "Pending"),
                    }
                    for x in requests
                ]
            )

            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.markdown(
                '<div class="card empty">No requests found.</div>',
                unsafe_allow_html=True,
            )

        return

    page_header(
        "Submit Request (Leave / Swap)",
        "Create a request for schedule or leave changes.",
    )

    with st.form("request_form"):
        c1, c2, c3 = st.columns(3)

        with c1:
            request_type = st.selectbox(
                "Request Type",
                ["PTO", "Sick Leave", "Schedule Swap", "Other"],
            )

        with c2:
            start_date = st.date_input(
                "Start Date",
                value=dt.date.today(),
            )

        with c3:
            end_date = st.date_input(
                "End Date",
                value=dt.date.today(),
            )

        reason = st.text_area(
            "Reason",
            placeholder="Family event",
        )

        submitted = st.form_submit_button(
            "Submit Request",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        if end_date < start_date:
            st.error("End Date cannot be before Start Date.")
        elif not reason.strip():
            st.error("Enter a reason.")
        else:
            if create_request(
                {
                    "requested_by": user.get(
                        "email",
                        name,
                    ),
                    "request_type": request_type,
                    "start_date": str(start_date),
                    "end_date": str(end_date),
                    "reason": reason.strip(),
                    "status": "Pending",
                    "created_at": dt.datetime.now(),
                }
            ):
                st.success("Request submitted.")
                st.rerun()

    st.markdown(
        '<div class="section-title">My Requests</div>',
        unsafe_allow_html=True,
    )

    mine = [
        x for x in load_requests()
        if x.get("requested_by")
        in (user.get("email"), name)
    ]

    if mine:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Date Filed": (
                            x.get("created_at").strftime("%b %-d, %Y")
                            if isinstance(
                                x.get("created_at"),
                                dt.datetime,
                            )
                            else ""
                        ),
                        "Type": x.get("request_type", ""),
                        "Start Date": x.get("start_date", ""),
                        "End Date": x.get("end_date", ""),
                        "Status": x.get("status", "Pending"),
                    }
                    for x in mine
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.markdown(
            '<div class="card empty">No requests submitted.</div>',
            unsafe_allow_html=True,
        )


# ============================================================
# ADMIN DASHBOARD — SCREEN 7
# ============================================================

def admin_dashboard():
    cases = [x for x in load_cases() if is_active(x)]
    roster = load_roster()

    critical = [
        x for x in cases
        if x.get("priority") == "Critical"
    ]

    due = [
        x for x in cases
        if due_soon(x)
    ]

    on_track = [
        x for x in cases
        if x not in critical
        and not due_soon(x)
        and not stale(x)
    ]

    page_header(
        "Team Overview",
        "Operational visibility across active cases and agents.",
    )

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        metric_card("▣", "Active Cases", len(cases))
    with c2:
        metric_card("▲", "Critical", len(critical))
    with c3:
        metric_card("◷", "Due Soon", len(due))
    with c4:
        metric_card("✓", "On Track", len(on_track))

    st.markdown(
        '<div class="section-title">Agent Status Distribution</div>',
        unsafe_allow_html=True,
    )

    left, right = st.columns(2)

    with left:
        agents = [
            x for x in roster
            if x.get("role") == "Agent"
        ]

        if agents:
            aux_df = pd.DataFrame(
                [
                    {
                        "AUX": x.get(
                            "aux",
                            "Available",
                        )
                    }
                    for x in agents
                ]
            )

            counts = (
                aux_df["AUX"]
                .value_counts()
                .reset_index()
            )
            counts.columns = ["AUX", "Count"]

            fig = px.pie(
                counts,
                names="AUX",
                values="Count",
                hole=.55,
            )

            fig.update_layout(
                height=270,
                margin=dict(l=10, r=10, t=20, b=10),
                showlegend=True,
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False},
            )

    with right:
        assigned = [
            x for x in cases
            if x.get("assigned_to")
            not in ("", None, "Unassigned")
        ]

        if assigned:
            counts = (
                pd.Series(
                    [
                        x.get("assigned_to")
                        for x in assigned
                    ]
                )
                .value_counts()
                .reset_index()
            )
            counts.columns = ["Agent", "Cases"]

            fig = px.bar(
                counts,
                x="Agent",
                y="Cases",
            )

            fig.update_layout(
                height=270,
                margin=dict(l=10, r=10, t=20, b=10),
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False},
            )


# ============================================================
# ADMIN CASES — SCREEN 8
# ============================================================

def admin_cases():
    page_header(
        "All Cases Control",
        "Search, review and reassign active case work.",
    )

    cases = load_cases()

    search = st.text_input(
        "Search",
        placeholder="Case ID, subject, priority, assignee...",
    )

    if search.strip():
        term = search.lower().strip()
        cases = [
            x for x in cases
            if term in str(x).lower()
        ]

    cases.sort(key=case_sort)

    if cases:
        st.dataframe(
            case_dataframe(cases),
            use_container_width=True,
            hide_index=True,
            height=300,
        )
    else:
        st.markdown(
            '<div class="card empty">No cases found.</div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        '<div class="section-title">Reassign Case</div>',
        unsafe_allow_html=True,
    )

    case_ids = [
        f"{x.get('case_id')} - {x.get('subject')}"
        for x in cases
    ]

    c1, c2, c3 = st.columns([1.2, 1.2, .8])

    with c1:
        selected = st.selectbox(
            "Select Case ID",
            case_ids,
        )

    selected_id = selected.split(" - ", 1)[0]

    with c2:
        agents = [
            x for x in load_roster()
            if x.get("role") == "Agent"
            and x.get("status", "Active") == "Active"
        ]

        agent_options = ["Unassigned"] + [
            x.get("email")
            for x in agents
            if x.get("email")
        ]

        assignee = st.selectbox(
            "Reassign to Agent Email",
            agent_options,
        )

    with c3:
        st.markdown("<div style='height:27px'></div>", unsafe_allow_html=True)

        if st.button(
            "Reassign Case",
            type="primary",
            use_container_width=True,
        ):
            if update_case(
                selected_id,
                {
                    "assigned_to": assignee,
                    "status": (
                        "Assigned"
                        if assignee != "Unassigned"
                        else "Pending"
                    ),
                    "last_update": dt.datetime.now(),
                },
            ):
                st.success("Case reassigned.")
                st.rerun()


# ============================================================
# ADMIN AGENTS — SCREEN 9
# ============================================================

def admin_agents():
    page_header(
        "Agent AUX Monitoring & Kick Control",
        "Monitor availability and remove agents from active queue coverage.",
    )

    agents = [
        x for x in load_roster()
        if x.get("role") == "Agent"
    ]

    if not agents:
        st.markdown(
            '<div class="card empty">No agents found.</div>',
            unsafe_allow_html=True,
        )
        return

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Name": agent_label(x),
                    "Email": x.get("email", ""),
                    "AUX Status": x.get(
                        "aux",
                        "Available",
                    ),
                    "Status": x.get(
                        "status",
                        "Active",
                    ),
                }
                for x in agents
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown(
        '<div class="section-title">Agent Controls</div>',
        unsafe_allow_html=True,
    )

    for index, agent in enumerate(agents):
        c1, c2, c3, c4 = st.columns([2.5, 3.2, 1.5, 1])

        c1.write(
            f"**{agent_label(agent)}**"
        )
        c2.write(
            agent.get("email", "")
        )

        aux = agent.get(
            "aux",
            "Available",
        )

        css = (
            "pill-green"
            if aux == "Available"
            else "pill-purple"
            if aux == "Admin Task"
            else "pill-high"
        )

        c3.markdown(
            f'<span class="pill {css}">{aux}</span>',
            unsafe_allow_html=True,
        )

        if c4.button(
            "Kick Agent",
            key=f"kick_{index}",
        ):
            if update_agent_aux(
                agent.get("email"),
                "Offline",
            ):
                st.success(
                    f"{agent_label(agent)} set to Offline."
                )
                st.rerun()


# ============================================================
# ADMIN REPORTS — SCREEN 12
# ============================================================

def admin_reports():
    page_header(
        "Extract Operational Reports",
        "Download operational data for analysis and reporting purposes.",
    )

    st.markdown(
        """
        <div class="card" style="text-align:center;padding:38px 20px">
            <div style="font-size:42px">▤</div>
            <div style="font-size:16px;font-weight:800;margin-top:8px">
                Export Cases to CSV
            </div>
            <div style="font-size:10px;color:#6B7C84;margin:5px 0 16px">
                Download all case data for analysis and reporting purposes.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    cases = load_cases()
    df = case_dataframe(cases)
    csv = df.to_csv(index=False).encode("utf-8")

    st.download_button(
        "Export Cases to CSV",
        csv,
        file_name="hpe_caseflow_cases.csv",
        mime="text/csv",
        type="primary",
        use_container_width=True,
    )


# ============================================================
# SALESFORCE — SCREEN 13
# ============================================================

def admin_salesforce():
    page_header(
        "Salesforce Integration (Admin Only)",
        "View Salesforce information without loading it during normal navigation.",
    )

    url = st.text_input(
        "Salesforce Link",
        value="https://example.salesforce.com/",
    )

    if st.button(
        "Open Salesforce",
        type="primary",
    ):
        st.link_button(
            "Open in Salesforce",
            url,
        )

    st.markdown(
        '<div class="section-title">Cases — Recently Viewed</div>',
        unsafe_allow_html=True,
    )

    recent = sorted(
        load_cases(),
        key=lambda x: x.get(
            "last_update",
            dt.datetime.min,
        ),
        reverse=True,
    )[:5]

    if recent:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Case Number": x.get("case_id"),
                        "Subject": x.get("subject"),
                        "Status": x.get("status"),
                    }
                    for x in recent
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# SETTINGS — SCREEN 14
# ============================================================

def admin_settings():
    page_header(
        "System Settings & User Role Management",
        "Manage user roles across the platform.",
    )

    st.markdown(
        '<div class="section-title">User Role Management</div>',
        unsafe_allow_html=True,
    )

    roster = load_roster()

    if roster:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Name": agent_label(x),
                        "Email": x.get("email", ""),
                        "Role": x.get("role", "Agent"),
                        "Status": x.get("status", "Active"),
                        "AUX": x.get("aux", "Available"),
                    }
                    for x in roster
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No users found.")

    st.markdown(
        '<div class="section-title">System Configuration</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "MongoDB",
        "Connected" if MONGO_ENABLED else "Fallback",
    )
    c2.metric("Database", DB_NAME)
    c3.metric("Roster Collection", ROSTER_COLLECTION)

    st.caption(
        "No personal administrator account or password is hard-coded "
        "in this application."
    )

    if st.button(
        "Clear Application Cache",
        use_container_width=True,
    ):
        clear_data_caches()
        st.success("Cache cleared.")


# ============================================================
# ROUTER
# ============================================================

if is_admin:
    if menu == "Dashboard":
        admin_dashboard()
    elif menu == "Cases":
        admin_cases()
    elif menu == "Agents":
        admin_agents()
    elif menu == "Schedule":
        schedule_page(admin=True)
    elif menu == "Requests":
        requests_page(admin=True)
    elif menu == "Reports":
        admin_reports()
    elif menu == "Salesforce":
        admin_salesforce()
    elif menu == "Settings":
        admin_settings()

else:
    if menu == "Dashboard":
        agent_dashboard()
    elif menu == "My Cases":
        agent_cases()
    elif menu == "Schedule":
        schedule_page(admin=False)
    elif menu == "Requests":
        requests_page(admin=False)
