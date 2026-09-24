import datetime as dt
import hashlib
import hmac
import os
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
# PAGE / APP CONFIG
# ============================================================

st.set_page_config(
    page_title="HPE CaseFlow",
    page_icon="▣",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# CONSTANTS
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

DEFAULT_CASES = [
    {
        "case_id": "0000156",
        "subject": "Software licensing portal access",
        "customer": "Enterprise Client",
        "priority": "Critical",
        "status": "Assigned",
        "progress": 70,
        "last_update": dt.datetime.now(),
        "due_date": dt.datetime.now() + dt.timedelta(hours=3),
        "assigned_to": "Unassigned",
        "salesforce_url": "https://example.salesforce.com/",
        "breach_reason": "",
    },
    {
        "case_id": "0000143",
        "subject": "License entitlement validation",
        "customer": "Enterprise Client",
        "priority": "High",
        "status": "Assigned",
        "progress": 55,
        "last_update": dt.datetime.now() - dt.timedelta(hours=2),
        "due_date": dt.datetime.now() + dt.timedelta(hours=8),
        "assigned_to": "Unassigned",
        "salesforce_url": "https://example.salesforce.com/",
        "breach_reason": "",
    },
    {
        "case_id": "0000132",
        "subject": "Customer portal technical issue",
        "customer": "Enterprise Client",
        "priority": "Medium",
        "status": "In Progress",
        "progress": 40,
        "last_update": dt.datetime.now() - dt.timedelta(hours=6),
        "due_date": dt.datetime.now() + dt.timedelta(days=1),
        "assigned_to": "Unassigned",
        "salesforce_url": "https://example.salesforce.com/",
        "breach_reason": "",
    },
    {
        "case_id": "0000128",
        "subject": "Account escalation",
        "customer": "Enterprise Client",
        "priority": "High",
        "status": "Assigned",
        "progress": 25,
        "last_update": dt.datetime.now() - dt.timedelta(hours=26),
        "due_date": dt.datetime.now() + dt.timedelta(hours=5),
        "assigned_to": "Unassigned",
        "salesforce_url": "https://example.salesforce.com/",
        "breach_reason": "",
    },
    {
        "case_id": "0000120",
        "subject": "Licensing information request",
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
# SESSION STATE
# ============================================================

def init_session():
    defaults = {
        "authenticated": False,
        "user_data": None,
        "mock_db": [],
        "cases_db": [],
        "requests_db": [],
        "selected_case_id": None,
        "menu": "Dashboard",
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session()


# ============================================================
# CSS
# ============================================================

st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1.2rem;
            padding-bottom: 2rem;
            max-width: 1500px;
        }

        [data-testid="stSidebar"] {
            border-right: 1px solid rgba(128,128,128,.18);
        }

        .case-card {
            padding: 14px 16px;
            border: 1px solid rgba(128,128,128,.20);
            border-radius: 12px;
            margin-bottom: 10px;
        }

        .small-muted {
            color: #777;
            font-size: 0.82rem;
        }

        .status-critical {
            color: #b42318;
            font-weight: 700;
        }

        .status-warning {
            color: #b54708;
            font-weight: 700;
        }

        .status-good {
            color: #067647;
            font-weight: 700;
        }

        div[data-testid="stMetric"] {
            border: 1px solid rgba(128,128,128,.15);
            border-radius: 12px;
            padding: 10px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# PASSWORD HELPERS
# ============================================================

def hash_password(password: str) -> str:
    """Built-in PBKDF2 hashing; no extra dependency required."""
    salt = secrets.token_bytes(16)
    iterations = 210_000
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )

    return (
        f"pbkdf2_sha256${iterations}$"
        f"{salt.hex()}${digest.hex()}"
    )


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False

    if not stored.startswith("pbkdf2_sha256$"):
        # Backward compatibility for older records.
        return hmac.compare_digest(password, stored)

    try:
        _, iterations, salt_hex, digest_hex = stored.split("$")
        iterations = int(iterations)
        salt = bytes.fromhex(salt_hex)

        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )

        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


# ============================================================
# MONGODB
# ============================================================

@st.cache_resource(show_spinner=False)
def get_mongo_client():
    """
    Do not attempt localhost MongoDB when MONGO_URI is missing.
    This removes the connection timeout that made the original
    application feel slow on startup.
    """
    try:
        uri = st.secrets.get("MONGO_URI", "")
    except Exception:
        uri = ""

    uri = str(uri).strip()

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
    if client is None:
        return None
    return client[DB_NAME]


@st.cache_resource(show_spinner=False)
def get_collections():
    db = get_database()

    if db is None:
        return None, None, None

    return (
        db[ROSTER_COLLECTION],
        db[CASES_COLLECTION],
        db[REQUESTS_COLLECTION],
    )


@st.cache_resource(show_spinner=False)
def ensure_indexes():
    """
    Non-unique indexes are intentionally used here so existing
    duplicate records do not break application startup.
    """
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


# ============================================================
# CACHE INVALIDATION
# ============================================================

def clear_data_caches():
    load_roster.clear()
    load_cases.clear()
    load_requests.clear()


# ============================================================
# INITIAL FALLBACK DATA
# ============================================================

def initialize_mock_data():
    if not st.session_state.cases_db:
        st.session_state.cases_db = [
            dict(case) for case in DEFAULT_CASES
        ]

    if "mock_initialized" not in st.session_state:
        st.session_state.mock_initialized = True


if not MONGO_ENABLED:
    initialize_mock_data()


# ============================================================
# DATA READS
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
                ).sort(
                    [
                        ("priority", 1),
                        ("due_date", 1),
                    ]
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
# DATA WRITES
# ============================================================

def create_user(user_data: dict):
    collections = get_collections()

    if collections:
        roster, _, _ = collections

        try:
            existing = roster.find_one(
                {"email": user_data["email"]},
                {"_id": 1},
            )

            if existing:
                return False, "An account with this email already exists."

            record = dict(user_data)
            record["password_hash"] = hash_password(
                record.pop("password")
            )
            record.setdefault("status", "Active")
            record.setdefault("role", "Agent")
            record.setdefault("aux", "Available")
            record["created_at"] = dt.datetime.now()

            roster.insert_one(record)
            clear_data_caches()

            return True, "Account created successfully."

        except DuplicateKeyError:
            return False, "An account with this email already exists."
        except PyMongoError as exc:
            return False, f"Database error: {exc}"

    email_exists = any(
        x.get("email", "").lower() == user_data["email"].lower()
        for x in st.session_state.mock_db
    )

    if email_exists:
        return False, "An account with this email already exists."

    record = dict(user_data)
    record["password_hash"] = hash_password(record.pop("password"))
    record.setdefault("status", "Active")
    record.setdefault("role", "Agent")
    record.setdefault("aux", "Available")
    record["created_at"] = dt.datetime.now()

    st.session_state.mock_db.append(record)
    clear_data_caches()

    return True, "Account created successfully."


def find_user(email: str, password: str):
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
                {
                    "_id": 0,
                },
            )

            if not user:
                return None

            stored_password = user.get("password_hash")

            # Support old plaintext records and upgrade them after login.
            if stored_password:
                valid = verify_password(password, stored_password)
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
                            "$unset": {
                                "password": ""
                            },
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
                user.get("password_hash", user.get("password", "")),
            )
        ):
            return dict(user)

    return None


def update_case(case_id: str, updates: dict):
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


def create_request(request_data: dict):
    collections = get_collections()

    if collections:
        _, _, requests = collections

        try:
            requests.insert_one(dict(request_data))
            clear_data_caches()
            return True
        except PyMongoError:
            return False

    st.session_state.requests_db.append(dict(request_data))
    clear_data_caches()
    return True


def update_agent_aux(email: str, aux: str):
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


# ============================================================
# AUTO ASSIGNMENT
# ============================================================

PRIORITY_ORDER = {
    "Critical": 0,
    "High": 1,
    "Medium": 2,
    "Low": 3,
}


def available_agents():
    roster = load_roster()

    return [
        agent
        for agent in roster
        if agent.get("role") == "Agent"
        and agent.get("status", "Active") == "Active"
        and agent.get("aux") == "Available"
    ]


def assign_unassigned_cases():
    """
    Assign only when there are actually unassigned cases.
    The original code called this on every Streamlit rerun.
    """
    cases = load_cases()

    unassigned = [
        case
        for case in cases
        if case.get("assigned_to") in (None, "", "Unassigned")
        and case.get("status") != "Completed"
    ]

    if not unassigned:
        return 0

    agents = available_agents()

    if not agents:
        return 0

    loads = Counter(
        case.get("assigned_to")
        for case in cases
        if case.get("assigned_to")
        not in (None, "", "Unassigned")
        and case.get("status") != "Completed"
    )

    assigned_count = 0

    unassigned.sort(
        key=lambda c: (
            PRIORITY_ORDER.get(c.get("priority", "Low"), 9),
            c.get("due_date") or dt.datetime.max,
        )
    )

    collections = get_collections()

    for case in unassigned:
        agent = min(
            agents,
            key=lambda a: (
                loads[a.get("email", a.get("name", ""))],
                a.get("email", a.get("name", "")),
            ),
        )

        agent_key = agent.get("email", agent.get("name", "Unassigned"))

        updates = {
            "assigned_to": agent_key,
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
                            "$in": [None, "", "Unassigned"]
                        },
                    },
                    {"$set": updates},
                )

                if result.modified_count:
                    assigned_count += 1
                    loads[agent_key] += 1

            except PyMongoError:
                continue

        else:
            for local_case in st.session_state.cases_db:
                if local_case.get("case_id") == case.get("case_id"):
                    local_case.update(updates)
                    assigned_count += 1
                    loads[agent_key] += 1
                    break

    if assigned_count:
        clear_data_caches()

    return assigned_count


# ============================================================
# HELPERS
# ============================================================

def normalize_datetime(value):
    if isinstance(value, dt.datetime):
        return value
    return None


def case_is_active(case):
    return case.get("status") not in (
        "Completed",
        "Closed",
        "Cancelled",
    )


def case_is_due_soon(case):
    due = normalize_datetime(case.get("due_date"))

    if not due:
        return False

    remaining = due - dt.datetime.now()
    return dt.timedelta(0) <= remaining <= dt.timedelta(hours=24)


def case_is_stale(case):
    last_update = normalize_datetime(case.get("last_update"))

    if not last_update:
        return False

    return dt.datetime.now() - last_update > dt.timedelta(hours=24)


def case_sort_key(case):
    due = normalize_datetime(case.get("due_date"))

    return (
        PRIORITY_ORDER.get(case.get("priority", "Low"), 9),
        due or dt.datetime.max,
    )


def case_dataframe(cases):
    rows = []

    for case in cases:
        rows.append(
            {
                "Case ID": case.get("case_id", ""),
                "Subject": case.get("subject", ""),
                "Priority": case.get("priority", ""),
                "Status": case.get("status", ""),
                "Progress": f"{case.get('progress', 0)}%",
                "Assigned To": case.get("assigned_to", "Unassigned"),
                "Due": (
                    case.get("due_date").strftime("%Y-%m-%d %H:%M")
                    if isinstance(case.get("due_date"), dt.datetime)
                    else ""
                ),
                "Last Update": (
                    case.get("last_update").strftime("%Y-%m-%d %H:%M")
                    if isinstance(case.get("last_update"), dt.datetime)
                    else ""
                ),
            }
        )

    return pd.DataFrame(rows)


def show_case_table(cases):
    if not cases:
        st.info("No cases found.")
        return

    df = case_dataframe(cases)

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Progress": st.column_config.ProgressColumn(
                "Progress",
                min_value=0,
                max_value=100,
            )
        },
    )


# ============================================================
# AUTHENTICATION
# ============================================================

def authentication_screen():
    st.title("HPE CaseFlow")
    st.caption("Case management and team operations dashboard")

    login_tab, signup_tab = st.tabs(["Sign In", "Sign Up"])

    with login_tab:
        with st.form("login_form", clear_on_submit=False):
            email = st.text_input(
                "HPE Email",
                placeholder="name@hpe.com",
            )
            password = st.text_input(
                "Password",
                type="password",
            )

            submitted = st.form_submit_button(
                "Sign In",
                use_container_width=True,
            )

        if submitted:
            if not email or not password:
                st.error("Enter your email and password.")
            else:
                user = find_user(email, password)

                if user:
                    st.session_state.authenticated = True
                    st.session_state.user_data = user
                    st.rerun()
                else:
                    st.error("Invalid email, password, or inactive account.")

    with signup_tab:
        with st.form("signup_form", clear_on_submit=True):
            col1, col2 = st.columns(2)

            with col1:
                first_name = st.text_input("First Name")
                employee_id = st.text_input("Employee ID")
                birthday = st.date_input(
                    "Birthday",
                    value=dt.date(1990, 1, 1),
                    min_value=dt.date(1940, 1, 1),
                    max_value=dt.date.today(),
                )
                email = st.text_input(
                    "HPE Email",
                    placeholder="name@hpe.com",
                )

            with col2:
                last_name = st.text_input("Last Name")
                contact_number = st.text_input("Contact Number")
                home_address = st.text_area("Home Address")
                password = st.text_input(
                    "Password",
                    type="password",
                )

            submitted = st.form_submit_button(
                "Create Account",
                use_container_width=True,
            )

        if submitted:
            if not all(
                [
                    first_name.strip(),
                    last_name.strip(),
                    employee_id.strip(),
                    email.strip(),
                    password,
                ]
            ):
                st.error("Complete all required fields.")
            elif "@" not in email:
                st.error("Enter a valid email address.")
            else:
                success, message = create_user(
                    {
                        "first_name": first_name.strip(),
                        "last_name": last_name.strip(),
                        "employee_id": employee_id.strip(),
                        "birthday": str(birthday),
                        "email": email.strip().lower(),
                        "contact_number": contact_number.strip(),
                        "home_address": home_address.strip(),
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


if not st.session_state.authenticated:
    authentication_screen()
    st.stop()


# ============================================================
# USER / NAVIGATION
# ============================================================

user = st.session_state.user_data or {}
is_admin = user.get("role") == "Admin"

user_name = (
    f"{user.get('first_name', '')} {user.get('last_name', '')}"
).strip()

if not user_name:
    user_name = user.get("name", user.get("email", "User"))

role_name = user.get("role", "Agent")


# ============================================================
# HEADER
# ============================================================

header_left, header_right = st.columns([7, 3])

with header_left:
    st.title("HPE CaseFlow")

with header_right:
    st.markdown(
        f"""
        <div style="text-align:right;padding-top:10px">
            <b>{user_name}</b><br>
            <span class="small-muted">{role_name}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Sign Out", key="sign_out"):
        st.session_state.authenticated = False
        st.session_state.user_data = None
        st.rerun()


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.markdown("### Navigation")

if is_admin:
    menu_options = [
        "Dashboard",
        "Cases",
        "Agents",
        "Schedule",
        "Requests",
        "Reports",
        "Salesforce",
        "Settings",
    ]
else:
    menu_options = [
        "Dashboard",
        "My Cases",
        "Schedule",
        "Requests",
    ]

current_index = (
    menu_options.index(st.session_state.menu)
    if st.session_state.menu in menu_options
    else 0
)

menu = st.sidebar.selectbox(
    "Menu",
    menu_options,
    index=current_index,
    label_visibility="collapsed",
)

st.session_state.menu = menu


# ============================================================
# AUX STATUS
# ============================================================

if role_name != "Admin":
    current_aux = user.get("aux", "Available")

    new_aux = st.sidebar.selectbox(
        "AUX Status",
        AUX_OPTIONS,
        index=(
            AUX_OPTIONS.index(current_aux)
            if current_aux in AUX_OPTIONS
            else 0
        ),
    )

    if new_aux != current_aux:
        if update_agent_aux(user.get("email"), new_aux):
            st.session_state.user_data["aux"] = new_aux
            st.toast("AUX status updated.")
        else:
            st.error("Unable to update AUX status.")


# ============================================================
# DASHBOARD
# ============================================================

def dashboard_page():
    # Refresh only the dashboard, not every application page.
    if st_autorefresh is not None:
        st_autorefresh(
            interval=60_000,
            key="dashboard_refresh",
        )

    cases = load_cases()

    # Auto-assignment is only checked when the dashboard is open.
    assigned = assign_unassigned_cases()

    if assigned:
        cases = load_cases()
        st.toast(f"{assigned} case(s) auto-assigned.")

    active = [
        case for case in cases
        if case_is_active(case)
    ]

    critical = [
        case for case in active
        if case.get("priority") == "Critical"
    ]

    due_soon = [
        case for case in active
        if case_is_due_soon(case)
    ]

    on_track = [
        case for case in active
        if (
            case.get("priority") != "Critical"
            and not case_is_due_soon(case)
            and not case_is_stale(case)
        )
    ]

    st.markdown("## Dashboard")

    m1, m2, m3, m4 = st.columns(4)

    with m1:
        st.metric("Active Cases", len(active))

    with m2:
        st.metric("Critical", len(critical))

    with m3:
        st.metric("Due Soon", len(due_soon))

    with m4:
        st.metric("On Track", len(on_track))

    st.divider()

    search = st.text_input(
        "Search cases",
        placeholder="Search by case ID, subject, customer, or assignee...",
    )

    if search.strip():
        term = search.strip().lower()

        active = [
            case
            for case in active
            if term in str(case).lower()
        ]

    active.sort(key=case_sort_key)

    show_case_table(active)

    stale_cases = [
        case for case in active
        if case_is_stale(case)
    ]

    if stale_cases:
        st.warning(
            f"{len(stale_cases)} case(s) have not been updated "
            "for more than 24 hours."
        )


# ============================================================
# MY CASES
# ============================================================

def my_cases_page():
    cases = load_cases()

    email = user.get("email", "")

    my_cases = [
        case
        for case in cases
        if case.get("assigned_to") in (email, user_name)
    ]

    my_cases.sort(key=case_sort_key)

    st.markdown("## My Cases")

    if not my_cases:
        st.info("No cases are currently assigned to you.")
        return

    options = [
        case.get("case_id")
        for case in my_cases
    ]

    selected_id = st.selectbox(
        "Select Case",
        options,
    )

    case = next(
        (
            x for x in my_cases
            if x.get("case_id") == selected_id
        ),
        None,
    )

    if not case:
        return

    st.subheader(
        f"Case #{case.get('case_id')}"
    )

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Priority",
        case.get("priority", ""),
    )
    col2.metric(
        "Status",
        case.get("status", ""),
    )
    col3.metric(
        "Progress",
        f"{case.get('progress', 0)}%",
    )

    st.write(
        f"**Subject:** {case.get('subject', '')}"
    )
    st.write(
        f"**Customer:** {case.get('customer', '')}"
    )

    if case.get("salesforce_url"):
        st.link_button(
            "Open Salesforce",
            case.get("salesforce_url"),
        )

    with st.form(
        f"case_update_{case.get('case_id')}"
    ):
        status_options = [
            "Assigned",
            "In Progress",
            "Pending",
            "Completed",
        ]

        current_status = case.get(
            "status",
            "Assigned",
        )

        status = st.selectbox(
            "Status",
            status_options,
            index=(
                status_options.index(current_status)
                if current_status in status_options
                else 0
            ),
        )

        progress = st.slider(
            "Progress",
            0,
            100,
            int(case.get("progress", 0)),
        )

        breach_reason = st.text_area(
            "Breach Reason",
            value=case.get("breach_reason", ""),
        )

        submitted = st.form_submit_button(
            "Save Update",
            use_container_width=True,
        )

    if submitted:
        success = update_case(
            case.get("case_id"),
            {
                "status": status,
                "progress": progress,
                "breach_reason": breach_reason,
                "last_update": dt.datetime.now(),
            },
        )

        if success:
            st.success("Case updated.")
            st.rerun()
        else:
            st.error("Unable to update case.")


# ============================================================
# ADMIN DASHBOARD
# ============================================================

def admin_dashboard_page():
    cases = load_cases()
    roster = load_roster()

    active = [
        case for case in cases
        if case_is_active(case)
    ]

    critical = [
        case for case in active
        if case.get("priority") == "Critical"
    ]

    due_soon = [
        case for case in active
        if case_is_due_soon(case)
    ]

    st.markdown("## Admin Dashboard")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Active Cases", len(active))
    c2.metric("Critical", len(critical))
    c3.metric("Due Soon", len(due_soon))
    c4.metric(
        "Agents",
        sum(
            1 for x in roster
            if x.get("role") == "Agent"
        ),
    )

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Agent AUX")

        aux_rows = [
            {
                "Agent": (
                    x.get("name")
                    or f"{x.get('first_name', '')} "
                       f"{x.get('last_name', '')}".strip()
                    or x.get("email", "")
                ),
                "AUX": x.get("aux", "Available"),
            }
            for x in roster
            if x.get("role") == "Agent"
        ]

        if aux_rows:
            aux_df = pd.DataFrame(aux_rows)
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
            )

            fig.update_layout(
                margin=dict(l=10, r=10, t=20, b=10),
                showlegend=True,
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False},
            )
        else:
            st.info("No agents found.")

    with col2:
        st.subheader("Cases by Agent")

        assigned_cases = [
            case for case in active
            if case.get("assigned_to")
            not in (None, "", "Unassigned")
        ]

        if assigned_cases:
            counts = (
                pd.Series(
                    [
                        x.get("assigned_to")
                        for x in assigned_cases
                    ]
                )
                .value_counts()
                .reset_index()
            )

            counts.columns = [
                "Agent",
                "Cases",
            ]

            fig = px.bar(
                counts,
                x="Agent",
                y="Cases",
            )

            fig.update_layout(
                margin=dict(l=10, r=10, t=20, b=10),
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False},
            )
        else:
            st.info("No assigned cases.")


# ============================================================
# ADMIN CASES
# ============================================================

def admin_cases_page():
    cases = load_cases()

    st.markdown("## Cases")

    search = st.text_input(
        "Search cases",
        placeholder="Case ID, subject, customer, assignee...",
    )

    if search.strip():
        term = search.strip().lower()

        cases = [
            case
            for case in cases
            if term in str(case).lower()
        ]

    cases.sort(key=case_sort_key)

    show_case_table(cases)

    if not cases:
        return

    case_ids = [
        case.get("case_id")
        for case in cases
    ]

    selected = st.selectbox(
        "Select a case to manage",
        case_ids,
    )

    case = next(
        (
            x for x in cases
            if x.get("case_id") == selected
        ),
        None,
    )

    if not case:
        return

    roster = load_roster()

    agents = [
        x for x in roster
        if x.get("role") == "Agent"
        and x.get("status", "Active") == "Active"
    ]

    agent_options = ["Unassigned"] + [
        x.get("email")
        for x in agents
        if x.get("email")
    ]

    current_assignee = case.get(
        "assigned_to",
        "Unassigned",
    )

    if current_assignee not in agent_options:
        agent_options.append(current_assignee)

    with st.form(
        f"reassign_{selected}"
    ):
        new_assignee = st.selectbox(
            "Assign To",
            agent_options,
            index=agent_options.index(current_assignee),
        )

        submitted = st.form_submit_button(
            "Save Assignment",
            use_container_width=True,
        )

    if submitted:
        if update_case(
            selected,
            {
                "assigned_to": new_assignee,
                "last_update": dt.datetime.now(),
                "status": (
                    "Assigned"
                    if new_assignee != "Unassigned"
                    else "Pending"
                ),
            },
        ):
            st.success("Assignment updated.")
            st.rerun()
        else:
            st.error("Unable to update assignment.")


# ============================================================
# ADMIN AGENTS
# ============================================================

def admin_agents_page():
    roster = load_roster()

    st.markdown("## Agents")

    agents = [
        x for x in roster
        if x.get("role") == "Agent"
    ]

    if not agents:
        st.info("No agents found.")
        return

    for index, agent in enumerate(agents):
        name = (
            agent.get("name")
            or f"{agent.get('first_name', '')} "
               f"{agent.get('last_name', '')}".strip()
            or agent.get("email", "Agent")
        )

        col1, col2, col3, col4 = st.columns(
            [3, 3, 2, 1]
        )

        col1.write(f"**{name}**")
        col2.write(agent.get("email", ""))
        col3.write(agent.get("aux", "Available"))

        if col4.button(
            "Kick",
            key=f"kick_{index}",
        ):
            if update_agent_aux(
                agent.get("email"),
                "Offline",
            ):
                st.success(
                    f"{name} set to Offline."
                )
                st.rerun()


# ============================================================
# SCHEDULE
# ============================================================

def schedule_page():
    st.markdown("## Schedule")

    schedule = pd.DataFrame(
        [
            ["Monday", "09:00 - 18:00", "Regular"],
            ["Tuesday", "09:00 - 18:00", "Regular"],
            ["Wednesday", "09:00 - 18:00", "Regular"],
            ["Thursday", "09:00 - 18:00", "Regular"],
            ["Friday", "09:00 - 18:00", "Regular"],
        ],
        columns=["Day", "Hours", "Type"],
    )

    st.dataframe(
        schedule,
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# REQUESTS
# ============================================================

def requests_page():
    st.markdown("## Requests")

    with st.form("request_form"):
        request_type = st.selectbox(
            "Request Type",
            [
                "Schedule Change",
                "AUX Change",
                "Case Support",
                "Other",
            ],
        )

        description = st.text_area(
            "Description"
        )

        submitted = st.form_submit_button(
            "Submit Request",
            use_container_width=True,
        )

    if submitted:
        if not description.strip():
            st.error("Enter a request description.")
        else:
            success = create_request(
                {
                    "request_type": request_type,
                    "description": description.strip(),
                    "requested_by": user.get("email", user_name),
                    "status": "Open",
                    "created_at": dt.datetime.now(),
                }
            )

            if success:
                st.success("Request submitted.")
                st.rerun()
            else:
                st.error("Unable to submit request.")

    if is_admin:
        st.divider()
        st.subheader("Open Requests")

        requests = load_requests()

        open_requests = [
            x for x in requests
            if x.get("status", "Open") == "Open"
        ]

        if open_requests:
            request_df = pd.DataFrame(open_requests)

            st.dataframe(
                request_df,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No open requests.")


# ============================================================
# REPORTS
# ============================================================

def reports_page():
    st.markdown("## Reports")

    cases = load_cases()

    if not cases:
        st.info("No case data available.")
        return

    df = case_dataframe(cases)

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
    )

    csv = df.to_csv(index=False).encode("utf-8")

    st.download_button(
        "Download Case Report",
        data=csv,
        file_name="hpe_caseflow_cases.csv",
        mime="text/csv",
    )


# ============================================================
# SALESFORCE
# ============================================================

def salesforce_page():
    st.markdown("## Salesforce")

    st.write(
        "Salesforce is loaded only when requested so it does not "
        "slow down normal CaseFlow navigation."
    )

    url = st.text_input(
        "Salesforce URL",
        value="https://example.salesforce.com/",
    )

    load_salesforce = st.toggle(
        "Load Salesforce",
        value=False,
    )

    if load_salesforce:
        st.link_button(
            "Open Salesforce",
            url,
        )

        st.components.v1.iframe(
            url,
            height=700,
            scrolling=True,
        )


# ============================================================
# SETTINGS
# ============================================================

def settings_page():
    st.markdown("## Settings")

    mongo_status = (
        "Connected"
        if MONGO_ENABLED
        else "Not configured / local fallback"
    )

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "MongoDB",
        mongo_status,
    )

    c2.metric(
        "Database",
        DB_NAME,
    )

    c3.metric(
        "Roster Collection",
        ROSTER_COLLECTION,
    )

    st.divider()

    st.write(
        """
        **Performance configuration**

        - MongoDB connection is cached.
        - Database reads use short TTL caching.
        - Indexes are created once per application process.
        - Dashboard refresh is limited to the Dashboard page.
        - Salesforce is loaded only when requested.
        - Forms prevent unnecessary reruns while typing.
        - Auto-assignment runs only when unassigned cases exist.
        """
    )

    if st.button(
        "Clear Application Data Cache",
        use_container_width=True,
    ):
        clear_data_caches()
        st.success("Application data cache cleared.")


# ============================================================
# ROUTER
# ============================================================

if is_admin:
    if menu == "Dashboard":
        admin_dashboard_page()
    elif menu == "Cases":
        admin_cases_page()
    elif menu == "Agents":
        admin_agents_page()
    elif menu == "Schedule":
        schedule_page()
    elif menu == "Requests":
        requests_page()
    elif menu == "Reports":
        reports_page()
    elif menu == "Salesforce":
        salesforce_page()
    elif menu == "Settings":
        settings_page()

else:
    if menu == "Dashboard":
        dashboard_page()
    elif menu == "My Cases":
        my_cases_page()
    elif menu == "Schedule":
        schedule_page()
    elif menu == "Requests":
        requests_page()
