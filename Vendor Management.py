```python
import os
import datetime as dt
from collections import Counter

import pandas as pd
import plotly.express as px
import streamlit as st
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from streamlit_autorefresh import st_autorefresh


# ============================================================
# 1. PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="HPE CaseFlow",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# 2. GLOBAL CSS
# ============================================================

st.markdown(
    """
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}

        :root {
            --hpe-green: #01A781;
            --hpe-dark-blue: #002B49;
            --hpe-light-bg: #F4F7F9;
            --card-border: #E2E8F0;
            --text-dark: #1E293B;
            --muted: #64748B;
        }

        .stApp {
            background: var(--hpe-light-bg);
        }

        .block-container {
            padding-top: 1.0rem;
            padding-bottom: 2rem;
            max-width: 98% !important;
        }

        /* Reduce Streamlit default spacing */
        div[data-testid="stVerticalBlock"] {
            gap: 0.55rem;
        }

        /* Metric cards */
        .metric-card {
            background: white;
            border: 1px solid var(--card-border);
            border-radius: 10px;
            padding: 16px;
            min-height: 105px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.04);
        }

        .metric-value {
            font-size: 2rem;
            font-weight: 700;
            color: var(--text-dark);
        }

        .metric-label {
            color: var(--muted);
            font-size: 0.82rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }

        .critical {
            color: #C53030;
        }

        .due {
            color: #C05621;
        }

        .track {
            color: var(--hpe-green);
        }

        /* Auth panel */
        .auth-panel {
            background: #002B49;
            color: white;
            padding: 40px;
            border-radius: 14px;
            min-height: 560px;
        }

        .auth-panel h1 {
            color: white;
            margin-bottom: 5px;
        }

        .auth-panel h2 {
            color: #01A781;
        }

        .auth-feature {
            margin: 20px 0;
            font-size: 0.95rem;
        }

        /* Case status */
        .status-pill {
            padding: 4px 9px;
            border-radius: 5px;
            font-weight: 600;
            display: inline-block;
        }

        .status-critical {
            background: #FED7D7;
            color: #9B2C2C;
        }

        .status-high {
            background: #FEEBC8;
            color: #9C4221;
        }

        .status-medium {
            background: #FEFCBF;
            color: #744210;
        }

        .status-low {
            background: #E2E8F0;
            color: #2D3748;
        }

        /* Sidebar navigation */
        section[data-testid="stSidebar"] {
            background: #002B49;
        }

        section[data-testid="stSidebar"] * {
            color: white;
        }

        /* Remove unnecessary borders */
        .case-card {
            background: white;
            border: 1px solid var(--card-border);
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 8px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# 3. CONSTANTS
# ============================================================

ADMIN_EMAIL = "arianne-may.escabillas@hpe.com"

# For production, place these in .streamlit/secrets.toml
DEFAULT_MONGO_URI = "mongodb://localhost:27017/"

DB_NAME = "TeamRoster"
ROSTER_COLLECTION = "Team Roster Collection"

AUX_OPTIONS = [
    "Available",
    "Break",
    "Lunch",
    "In a Meeting",
    "Coaching",
    "Busy - Away",
    "Unscheduled Break",
]


# ============================================================
# 4. SESSION STATE
# ============================================================

def initialize_session():
    defaults = {
        "authenticated": False,
        "user_data": None,
        "mock_db": [],
        "cases_db": [],
        "requests_db": [],
        "selected_case": None,
        "mongo_available": False,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


initialize_session()


# ============================================================
# 5. MONGODB CONNECTION
# ============================================================

@st.cache_resource(ttl=60, show_spinner=False)
def get_mongo_client():
    """
    Cached MongoDB connection.

    TTL prevents a dead MongoDB connection from being permanently
    cached if MongoDB is restarted.
    """

    mongo_uri = st.secrets.get("MONGO_URI", DEFAULT_MONGO_URI)

    try:
        client = MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=1500,
            connectTimeoutMS=1500,
            socketTimeoutMS=3000,
            maxPoolSize=20,
            minPoolSize=1,
            retryWrites=True,
        )

        # Fast connectivity test
        client.admin.command("ping")

        return client

    except Exception:
        return None


@st.cache_resource(ttl=60, show_spinner=False)
def get_roster_collection():
    client = get_mongo_client()

    if client is None:
        return None

    try:
        return client[DB_NAME][ROSTER_COLLECTION]
    except Exception:
        return None


roster_collection = get_roster_collection()

st.session_state.mongo_available = roster_collection is not None


# ============================================================
# 6. INITIAL MOCK DATA
# ============================================================

def initialize_mock_data():

    if not st.session_state.mock_db:

        st.session_state.mock_db = [
            {
                "first_name": "Arianne May",
                "last_name": "Escabillas",
                "employee_id": "60187999",
                "email": ADMIN_EMAIL,
                "birthday": "1993-06-17",
                "address": "Imus City, Cavite",
                "contact": "",
                "password": "Escabillas1993",
                "role": "Admin",
                "aux": "Admin Task",
                "status": "Active",
            }
        ]

    if not st.session_state.cases_db:

        now = dt.datetime.now()

        st.session_state.cases_db = [
            {
                "case_id": "0000156",
                "subject": "Network equipment delay",
                "priority": "Critical",
                "due_date": "Today 2:00 PM",
                "status": "In Progress",
                "assigned_to": "john.delacruz@hpe.com",
                "last_update": now - dt.timedelta(hours=25),
            },
            {
                "case_id": "0000143",
                "subject": "Server replacement",
                "priority": "High",
                "due_date": "Today 5:00 PM",
                "status": "Pending Vendor",
                "assigned_to": "john.delacruz@hpe.com",
                "last_update": now - dt.timedelta(hours=1),
            },
            {
                "case_id": "0000132",
                "subject": "Software license",
                "priority": "Medium",
                "due_date": "Apr 30, 2026",
                "status": "Assigned",
                "assigned_to": "mark.rivera@hpe.com",
                "last_update": now - dt.timedelta(hours=5),
            },
            {
                "case_id": "0000128",
                "subject": "Site installation",
                "priority": "Medium",
                "due_date": "May 1, 2026",
                "status": "In Progress",
                "assigned_to": "ana.reyes@hpe.com",
                "last_update": now - dt.timedelta(hours=2),
            },
            {
                "case_id": "0000120",
                "subject": "Access request",
                "priority": "Low",
                "due_date": "May 2, 2026",
                "status": "New",
                "assigned_to": "Unassigned",
                "last_update": now,
            },
        ]

    if not st.session_state.requests_db:

        st.session_state.requests_db = [
            {
                "agent": "Maria Santos",
                "type": "PTO",
                "start": "2026-09-28",
                "end": "2026-09-30",
                "status": "Pending",
            },
            {
                "agent": "Mark Rivera",
                "type": "Schedule Swap",
                "start": "2026-09-29",
                "end": "2026-09-29",
                "status": "Pending",
            },
        ]


initialize_mock_data()


# ============================================================
# 7. SEED ADMIN
# ============================================================

def seed_admin():
    """
    Runs only when MongoDB is available.
    Does not run on every page interaction.
    """

    if roster_collection is None:
        return

    try:
        existing = roster_collection.find_one(
            {"email": ADMIN_EMAIL},
            {"_id": 1}
        )

        if existing:
            return

        roster_collection.insert_one(
            {
                "first_name": "Arianne May",
                "last_name": "Escabillas",
                "employee_id": "60187999",
                "email": ADMIN_EMAIL,
                "birthday": "1993-06-17",
                "address": "Imus City, Cavite",
                "contact": "",
                "password": "Escabillas1993",
                "role": "Admin",
                "aux": "Admin Task",
                "status": "Active",
            }
        )

    except PyMongoError:
        pass


seed_admin()


# ============================================================
# 8. USER LOOKUP
# ============================================================

def find_user(email, password):

    email = email.strip().lower()

    if roster_collection is not None:

        try:
            return roster_collection.find_one(
                {
                    "email": email,
                    "password": password,
                    "status": "Active",
                }
            )
        except PyMongoError:
            pass

    return next(
        (
            user
            for user in st.session_state.mock_db
            if user.get("email", "").lower() == email
            and user.get("password") == password
            and user.get("status") == "Active"
        ),
        None,
    )


# ============================================================
# 9. USER CREATION
# ============================================================

def create_user(user):

    if roster_collection is not None:

        try:
            roster_collection.insert_one(user)
            return True
        except PyMongoError:
            return False

    st.session_state.mock_db.append(user)
    return True


# ============================================================
# 10. AUTH PAGE
# ============================================================

def render_auth_page():

    left, right = st.columns([1, 1.15], gap="large")

    with left:

        st.markdown(
            """
            <div class="auth-panel">

                <h2>Hewlett Packard Enterprise</h2>

                <h1>HPE CaseFlow</h1>

                <p style="color:#CBD5E1;font-size:1.05rem;">
                    Team Task and Case Management System
                </p>

                <br>

                <div class="auth-feature">
                    <b>▤ Manage Cases</b><br>
                    <small>Track and resolve tasks efficiently</small>
                </div>

                <div class="auth-feature">
                    <b>◈ Team Collaboration</b><br>
                    <small>Work together for better service delivery</small>
                </div>

                <div class="auth-feature">
                    <b>◉ Real-Time Visibility</b><br>
                    <small>Stay informed and in control</small>
                </div>

                <div class="auth-feature">
                    <b>▣ Secure Access</b><br>
                    <small>HPE employees only</small>
                </div>

            </div>
            """,
            unsafe_allow_html=True,
        )

    with right:

        st.markdown("## Welcome to HPE CaseFlow")

        mode = st.segmented_control(
            "Authentication",
            ["Sign In", "Sign Up"],
            default="Sign In",
            label_visibility="collapsed",
        )

        # ----------------------------------------------------
        # SIGN IN
        # ----------------------------------------------------

        if mode == "Sign In":

            st.subheader("Sign In")
            st.caption("Access your HPE CaseFlow account.")

            email = st.text_input(
                "HPE Email Address",
                placeholder="name@hpe.com",
                key="login_email",
            )

            password = st.text_input(
                "Password",
                type="password",
                key="login_password",
            )

            if st.button(
                "Sign In",
                type="primary",
                use_container_width=True,
            ):

                if not email or not password:
                    st.warning("Enter your email and password.")

                else:

                    user = find_user(email, password)

                    if user:

                        st.session_state.authenticated = True
                        st.session_state.user_data = user

                        st.rerun()

                    else:
                        st.error("Invalid email or password.")

        # ----------------------------------------------------
        # SIGN UP
        # ----------------------------------------------------

        else:

            st.subheader("Create Account")
            st.caption("Create your HPE CaseFlow account.")

            c1, c2 = st.columns(2)

            with c1:
                fn = st.text_input("First Name")
                emp_id = st.text_input("Employee ID")

            with c2:
                ln = st.text_input("Last Name")
                email = st.text_input(
                    "HPE Email Address",
                    placeholder="name@hpe.com",
                )

            bday = st.date_input(
                "Birthday",
                min_value=dt.date(1950, 1, 1),
            )

            addr = st.text_area("Home Address")

            contact = st.text_input("Contact Number")

            c1, c2 = st.columns(2)

            with c1:
                pwd = st.text_input(
                    "Password",
                    type="password",
                )

            with c2:
                confirm_pwd = st.text_input(
                    "Confirm Password",
                    type="password",
                )

            if st.button(
                "Create Account",
                type="primary",
                use_container_width=True,
            ):

                email = email.strip().lower()

                if not email.endswith("@hpe.com"):
                    st.error(
                        "Please use a valid @hpe.com email address."
                    )

                elif not all(
                    [
                        fn,
                        ln,
                        emp_id,
                        email,
                        pwd,
                    ]
                ):
                    st.error(
                        "Please complete all required fields."
                    )

                elif pwd != confirm_pwd:
                    st.error("Passwords do not match.")

                else:

                    new_user = {
                        "first_name": fn.strip(),
                        "last_name": ln.strip(),
                        "employee_id": emp_id.strip(),
                        "email": email,
                        "birthday": str(bday),
                        "address": addr.strip(),
                        "contact": contact.strip(),
                        "password": pwd,
                        "role": "Agent",
                        "aux": "Busy - Away",
                        "status": "Active",
                    }

                    if create_user(new_user):

                        st.success(
                            "Account created successfully. "
                            "You can now sign in."
                        )

                    else:
                        st.error(
                            "Unable to create account. "
                            "The email may already exist."
                        )


# ============================================================
# 11. STOP BEFORE LOADING THE MAIN APPLICATION
# ============================================================

if not st.session_state.authenticated:

    render_auth_page()
    st.stop()


# ============================================================
# 12. REFRESH ONLY AFTER LOGIN
# ============================================================

# 30 seconds instead of 10 seconds.
# This avoids excessive complete Streamlit reruns.

st_autorefresh(
    interval=30000,
    key="caseflow_refresh",
)


# ============================================================
# 13. CURRENT USER
# ============================================================

user = st.session_state.user_data

is_admin = user.get("role") == "Admin"


# ============================================================
# 14. AUTOMATIC CASE ASSIGNMENT
# ============================================================

def get_available_agents():

    if roster_collection is not None:

        try:
            return list(
                roster_collection.find(
                    {
                        "role": "Agent",
                        "status": "Active",
                        "aux": "Available",
                    },
                    {
                        "_id": 0,
                        "email": 1,
                        "first_name": 1,
                        "last_name": 1,
                    },
                )
            )

        except PyMongoError:
            pass

    return [
        user
        for user in st.session_state.mock_db
        if user.get("role") == "Agent"
        and user.get("status") == "Active"
        and user.get("aux") == "Available"
    ]


def auto_assign_cases():

    cases = st.session_state.cases_db

    unassigned = [
        case
        for case in cases
        if case.get("assigned_to") == "Unassigned"
    ]

    if not unassigned:
        return

    agents = get_available_agents()

    if not agents:
        return

    load = Counter(
        case.get("assigned_to")
        for case in cases
        if case.get("assigned_to") != "Unassigned"
    )

    for case in unassigned:

        target = min(
            agents,
            key=lambda agent: load.get(agent["email"], 0),
        )

        case["assigned_to"] = target["email"]
        case["status"] = "Assigned"

        load[target["email"]] += 1


auto_assign_cases()


# ============================================================
# 15. UPDATE AUX
# ============================================================

def update_aux(new_aux):

    user["aux"] = new_aux

    if roster_collection is not None:

        try:
            roster_collection.update_one(
                {"email": user["email"]},
                {"$set": {"aux": new_aux}},
            )
        except PyMongoError:
            pass


# ============================================================
# 16. HEADER
# ============================================================

header_left, header_middle, header_right = st.columns(
    [3.5, 2.2, 2.2]
)

with header_left:

    st.markdown(
        """
        <h1 style="
            color:#002B49;
            margin-bottom:0;
            font-size:2rem;
        ">
            HPE CaseFlow
        </h1>
        """,
        unsafe_allow_html=True,
    )

with header_middle:

    current_aux = user.get(
        "aux",
        "Admin Task" if is_admin else "Busy - Away",
    )

    options = AUX_OPTIONS.copy()

    if is_admin and "Admin Task" not in options:
        options.insert(0, "Admin Task")

    selected_aux = st.selectbox(
        "AUX",
        options,
        index=(
            options.index(current_aux)
            if current_aux in options
            else 0
        ),
        label_visibility="collapsed",
    )

    if selected_aux != current_aux:

        update_aux(selected_aux)

        st.toast(
            f"AUX updated to {selected_aux}",
            icon="✓",
        )

with header_right:

    st.markdown(
        f"""
        <div style="
            text-align:right;
            padding-top:7px;
        ">
            <b>{user['first_name']} {user['last_name']}</b><br>
            <small>{user['role']}</small>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button(
        "Sign Out",
        use_container_width=True,
    ):

        st.session_state.authenticated = False
        st.session_state.user_data = None
        st.rerun()


# ============================================================
# 17. SIDEBAR NAVIGATION
# ============================================================

st.sidebar.markdown(
    f"""
    <div style="
        padding:10px 0 20px 0;
        border-bottom:1px solid rgba(255,255,255,0.2);
    ">
        <b>HPE CaseFlow</b><br>
        <small>{user['first_name']} {user['last_name']}</small>
    </div>
    """,
    unsafe_allow_html=True,
)

if is_admin:

    menu_items = [
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

    menu_items = [
        "Dashboard",
        "My Cases",
        "Schedule",
        "Requests",
    ]


menu = st.sidebar.selectbox(
    "Navigation",
    menu_items,
    label_visibility="collapsed",
)


# ============================================================
# 18. COMMON CASE HELPERS
# ============================================================

PRIORITY_ORDER = {
    "Critical": 0,
    "High": 1,
    "Medium": 2,
    "Low": 3,
}


def sort_cases(cases):

    return sorted(
        cases,
        key=lambda case: (
            PRIORITY_ORDER.get(
                case.get("priority"),
                99,
            ),
            case.get("due_date", ""),
        ),
    )


def cases_dataframe(cases):

    if not cases:
        return pd.DataFrame(
            columns=[
                "Case ID",
                "Subject",
                "Priority",
                "Due Date",
                "Status",
                "Assigned To",
            ]
        )

    rows = []

    for case in sort_cases(cases):

        rows.append(
            {
                "Case ID": case.get("case_id"),
                "Subject": case.get("subject"),
                "Priority": case.get("priority"),
                "Due Date": case.get("due_date"),
                "Status": case.get("status"),
                "Assigned To": case.get("assigned_to"),
            }
        )

    return pd.DataFrame(rows)


def show_metrics(cases, prefix=""):

    active = len(cases)

    critical = sum(
        1
        for case in cases
        if case.get("priority") == "Critical"
    )

    due_soon = sum(
        1
        for case in cases
        if "Today" in case.get("due_date", "")
    )

    on_track = sum(
        1
        for case in cases
        if case.get("priority") in ["Medium", "Low"]
    )

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">
                    {prefix} Active Cases
                </div>
                <div class="metric-value">
                    {active}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c2:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">
                    Critical
                </div>
                <div class="metric-value critical">
                    {critical}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c3:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">
                    Due Soon
                </div>
                <div class="metric-value due">
                    {due_soon}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c4:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">
                    On Track
                </div>
                <div class="metric-value track">
                    {on_track}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ============================================================
# 19. REGULAR AGENT APPLICATION
# ============================================================

if not is_admin:

    my_cases = [
        case
        for case in st.session_state.cases_db
        if case.get("assigned_to") == user.get("email")
    ]

    # --------------------------------------------------------
    # DASHBOARD
    # --------------------------------------------------------

    if menu == "Dashboard":

        st.subheader(
            f"Good Morning, {user['first_name']}!"
        )

        st.caption(
            dt.datetime.now().strftime(
                "%A, %B %d, %Y"
            )
        )

        show_metrics(
            my_cases,
            prefix="My",
        )

        st.markdown("### Alerts")

        now = dt.datetime.now()

        stale_cases = [
            case
            for case in my_cases
            if (
                now - case.get(
                    "last_update",
                    now,
                )
            ).total_seconds()
            > 86400
        ]

        critical_cases = [
            case
            for case in my_cases
            if case.get("priority") == "Critical"
        ]

        if stale_cases:

            st.warning(
                f"⚠️ {len(stale_cases)} case(s) "
                "have not been updated for more than 24 hours."
            )

        if critical_cases:

            for case in critical_cases:

                st.error(
                    f"🚨 Case #{case['case_id']} "
                    f"— {case['subject']} is Critical."
                )

        st.markdown("### My Cases")

        search = st.text_input(
            "Search my cases",
            placeholder="Case number, subject, status...",
            key="agent_case_search",
        )

        filtered = my_cases

        if search:

            q = search.lower()

            filtered = [
                case
                for case in my_cases
                if q in str(
                    case.get("case_id", "")
                ).lower()
                or q in str(
                    case.get("subject", "")
                ).lower()
                or q in str(
                    case.get("status", "")
                ).lower()
            ]

        df = cases_dataframe(filtered)

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )

    # --------------------------------------------------------
    # MY CASES
    # --------------------------------------------------------

    elif menu == "My Cases":

        st.subheader("My Cases Management")

        if not my_cases:

            st.info(
                "No cases are currently assigned to you."
            )

        else:

            case_ids = [
                case["case_id"]
                for case in my_cases
            ]

            selected_id = st.selectbox(
                "Select Case",
                case_ids,
            )

            case = next(
                case
                for case in my_cases
                if case["case_id"] == selected_id
            )

            left, right = st.columns(2)

            with left:

                st.markdown(
                    f"### Case #{case['case_id']}"
                )

                st.write(
                    f"**Subject:** {case['subject']}"
                )

                st.write(
                    f"**Priority:** {case['priority']}"
                )

                st.write(
                    f"**Due Date:** {case['due_date']}"
                )

                st.write(
                    f"**Current Status:** {case['status']}"
                )

                sf_url = (
                    "https://hp.lightning.force.com/"
                    f"lightning/r/Case/"
                    f"{case['case_id']}/view"
                )

                st.markdown(
                    f"[Open Case in Salesforce ↗]({sf_url})"
                )

            with right:

                statuses = [
                    "New",
                    "Assigned",
                    "In Progress",
                    "Pending Vendor",
                    "Completed",
                    "Contract Breached",
                ]

                current_status = case.get(
                    "status",
                    "Assigned",
                )

                status_index = (
                    statuses.index(current_status)
                    if current_status in statuses
                    else 0
                )

                new_status = st.selectbox(
                    "Update Status",
                    statuses,
                    index=status_index,
                )

                if new_status == "Contract Breached":

                    reason = st.selectbox(
                        "Breach Reason",
                        [
                            "SLA Missed",
                            "Vendor Unresponsive",
                            "Part Out of Stock",
                        ],
                    )

                    st.text_area(
                        "Generated Notification",
                        value=(
                            f"Dear Team,\n\n"
                            f"Case #{case['case_id']} "
                            f"breached SLA due to: {reason}."
                        ),
                        height=130,
                    )

                if st.button(
                    "Save Case Update",
                    type="primary",
                    use_container_width=True,
                ):

                    case["status"] = new_status
                    case["last_update"] = dt.datetime.now()

                    st.success(
                        "Case updated successfully."
                    )

    # --------------------------------------------------------
    # SCHEDULE
    # --------------------------------------------------------

    elif menu == "Schedule":

        st.subheader("My Schedule")

        tab_day, tab_week, tab_month = st.tabs(
            ["Day", "Week", "Month"]
        )

        with tab_day:

            st.table(
                [
                    {
                        "Time": "08:00 AM - 10:00 AM",
                        "Activity": "Work / Case Processing",
                    },
                    {
                        "Time": "10:00 AM - 10:15 AM",
                        "Activity": "Break",
                    },
                    {
                        "Time": "10:15 AM - 12:00 PM",
                        "Activity": "Work / Case Processing",
                    },
                    {
                        "Time": "12:00 PM - 01:00 PM",
                        "Activity": "Lunch",
                    },
                    {
                        "Time": "03:00 PM - 03:15 PM",
                        "Activity": "Break",
                    },
                ]
            )

        with tab_week:

            st.info(
                "Weekly schedule management will appear here."
            )

        with tab_month:

            st.info(
                "Monthly schedule management will appear here."
            )

    # --------------------------------------------------------
    # REQUESTS
    # --------------------------------------------------------

    elif menu == "Requests":

        st.subheader("Submit Request")

        req_type = st.selectbox(
            "Request Type",
            [
                "Sick Leave",
                "Emergency Leave",
                "PTO",
                "Schedule Swap",
            ],
        )

        c1, c2 = st.columns(2)

        with c1:
            s_date = st.date_input("Start Date")

        with c2:
            e_date = st.date_input("End Date")

        reason = st.text_input("Reason")

        if st.button(
            "Submit Request",
            type="primary",
        ):

            st.session_state.requests_db.append(
                {
                    "agent": (
                        f"{user['first_name']} "
                        f"{user['last_name']}"
                    ),
                    "type": req_type,
                    "start": str(s_date),
                    "end": str(e_date),
                    "reason": reason,
                    "status": (
                        "Auto-Approved"
                        if req_type
                        in [
                            "Sick Leave",
                            "Emergency Leave",
                        ]
                        else "Pending"
                    ),
                }
            )

            st.success(
                "Request submitted successfully."
            )


# ============================================================
# 20. ADMIN APPLICATION
# ============================================================

else:

    all_cases = st.session_state.cases_db

    # --------------------------------------------------------
    # ADMIN DASHBOARD
    # --------------------------------------------------------

    if menu == "Dashboard":

        st.subheader("Team Overview")

        show_metrics(all_cases)

        col1, col2 = st.columns(2)

        with col1:

            st.markdown(
                "### Agent Status Distribution"
            )

            if roster_collection is not None:

                try:

                    agents = list(
                        roster_collection.find(
                            {
                                "role": "Agent",
                                "status": "Active",
                            },
                            {
                                "_id": 0,
                                "aux": 1,
                            },
                        )
                    )

                except PyMongoError:

                    agents = []

            else:

                agents = [
                    user
                    for user
                    in st.session_state.mock_db
                    if user.get("role") == "Agent"
                ]

            status_counts = Counter(
                agent.get(
                    "aux",
                    "Offline",
                )
                for agent in agents
            )

            if status_counts:

                fig = px.pie(
                    values=list(
                        status_counts.values()
                    ),
                    names=list(
                        status_counts.keys()
                    ),
                    hole=0.45,
                )

                fig.update_layout(
                    margin=dict(
                        l=10,
                        r=10,
                        t=20,
                        b=10,
                    )
                )

                st.plotly_chart(
                    fig,
                    use_container_width=True,
                )

            else:

                st.info(
                    "No active agents found."
                )

        with col2:

            st.markdown(
                "### Active Cases by Agent"
            )

            if all_cases:

                case_counts = Counter(
                    case.get(
                        "assigned_to",
                        "Unassigned",
                    )
                    for case in all_cases
                )

                df_chart = pd.DataFrame(
                    {
                        "Agent": list(
                            case_counts.keys()
                        ),
                        "Cases": list(
                            case_counts.values()
                        ),
                    }
                )

                fig = px.bar(
                    df_chart,
                    x="Agent",
                    y="Cases",
                )

                fig.update_layout(
                    margin=dict(
                        l=10,
                        r=10,
                        t=20,
                        b=10,
                    )
                )

                st.plotly_chart(
                    fig,
                    use_container_width=True,
                )

    # --------------------------------------------------------
    # CASES
    # --------------------------------------------------------

    elif menu == "Cases":

        st.subheader("All Cases")

        search = st.text_input(
            "Search cases",
            placeholder=(
                "Case ID, subject, priority, "
                "status, assigned agent..."
            ),
        )

        filtered = all_cases

        if search:

            q = search.lower()

            filtered = [
                case
                for case in all_cases
                if q in str(
                    case.get("case_id", "")
                ).lower()
                or q in str(
                    case.get("subject", "")
                ).lower()
                or q in str(
                    case.get("priority", "")
                ).lower()
                or q in str(
                    case.get("status", "")
                ).lower()
                or q in str(
                    case.get("assigned_to", "")
                ).lower()
            ]

        st.dataframe(
            cases_dataframe(filtered),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("### Reassign Case")

        if all_cases:

            case_ids = [
                case["case_id"]
                for case in all_cases
            ]

            cid = st.selectbox(
                "Case ID",
                case_ids,
            )

            agent_email = st.text_input(
                "Agent Email",
                placeholder="agent@hpe.com",
            )

            if st.button(
                "Reassign Case",
                type="primary",
            ):

                target = next(
                    case
                    for case in all_cases
                    if case["case_id"] == cid
                )

                target["assigned_to"] = (
                    agent_email.strip().lower()
                )

                target["last_update"] = (
                    dt.datetime.now()
                )

                st.success(
                    f"Case #{cid} reassigned."
                )

    # --------------------------------------------------------
    # AGENTS
    # --------------------------------------------------------

    elif menu == "Agents":

        st.subheader(
            "Agent AUX Monitoring"
        )

        if roster_collection is not None:

            try:

                roster = list(
                    roster_collection.find(
                        {},
                        {
                            "_id": 0,
                            "first_name": 1,
                            "last_name": 1,
                            "email": 1,
                            "role": 1,
                            "aux": 1,
                            "status": 1,
                        },
                    )
                )

            except PyMongoError:

                roster = []

        else:

            roster = st.session_state.mock_db

        if not roster:

            st.info("No roster records found.")

        else:

            for agent in roster:

                a, b, c = st.columns(
                    [3, 2, 1]
                )

                with a:

                    st.markdown(
                        f"""
                        **{agent.get('first_name', '')}
                        {agent.get('last_name', '')}**

                        <small>
                        {agent.get('email', '')}
                        </small>
                        """,
                        unsafe_allow_html=True,
                    )

                with b:

                    st.write(
                        f"AUX: `{agent.get('aux', 'Offline')}`"
                    )

                with c:

                    if (
                        agent.get("role")
                        == "Agent"
                    ):

                        if st.button(
                            "Kick",
                            key=f"kick_{agent.get('email')}",
                        ):

                            update_data = {
                                "aux": "Busy - Away"
                            }

                            if roster_collection is not None:

                                try:

                                    roster_collection.update_one(
                                        {
                                            "email":
                                            agent.get(
                                                "email"
                                            )
                                        },
                                        {
                                            "$set":
                                            update_data
                                        },
                                    )

                                except PyMongoError:
                                    pass

                            agent["aux"] = (
                                "Busy - Away"
                            )

                            st.toast(
                                "Agent moved to Busy - Away."
                            )

    # --------------------------------------------------------
    # SCHEDULE
    # --------------------------------------------------------

    elif menu == "Schedule":

        st.subheader(
            "Team Schedule Management"
        )

        st.info(
            "Interval Optimizer is active. "
            "Queue coverage and agent availability "
            "can be managed here."
        )

    # --------------------------------------------------------
    # REQUESTS
    # --------------------------------------------------------

    elif menu == "Requests":

        st.subheader(
            "Manage Requests"
        )

        if st.session_state.requests_db:

            st.dataframe(
                pd.DataFrame(
                    st.session_state.requests_db
                ),
                use_container_width=True,
                hide_index=True,
            )

        else:

            st.info(
                "No requests available."
            )

    # --------------------------------------------------------
    # REPORTS
    # --------------------------------------------------------

    elif menu == "Reports":

        st.subheader(
            "Operational Reports"
        )

        cases_df = pd.DataFrame(
            st.session_state.cases_db
        )

        csv = cases_df.to_csv(
            index=False
        ).encode("utf-8")

        st.download_button(
            "Export Cases to CSV",
            data=csv,
            file_name="hpe_cases_report.csv",
            mime="text/csv",
            type="primary",
        )

    # --------------------------------------------------------
    # SALESFORCE
    # --------------------------------------------------------

    elif menu == "Salesforce":

        st.subheader(
            "Salesforce Integration"
        )

        st.markdown(
            "[Open Salesforce ↗]"
            "(https://hp.lightning.force.com/)"
        )

        st.info(
            "Salesforce is loaded only when this tab "
            "is selected, preventing it from slowing "
            "the rest of the application."
        )

        load_salesforce = st.toggle(
            "Load Salesforce inside CaseFlow",
            value=False,
        )

        if load_salesforce:

            st.components.v1.iframe(
                "https://hp.lightning.force.com/",
                height=700,
                scrolling=True,
            )

    # --------------------------------------------------------
    # SETTINGS
    # --------------------------------------------------------

    elif menu == "Settings":

        st.subheader(
            "System Settings"
        )

        st.write(
            "Manage user roles and system configuration."
        )

        st.markdown(
            f"""
            **Database:** `{DB_NAME}`

            **Roster Collection:** `{ROSTER_COLLECTION}`

            **MongoDB Status:**  
            {"🟢 Connected"
             if roster_collection is not None
             else "🟠 Offline / Using local session data"}
            """
        )

