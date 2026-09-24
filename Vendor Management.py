```python
import datetime as dt
from collections import Counter

import pandas as pd
import plotly.express as px
import streamlit as st
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from streamlit_autorefresh import st_autorefresh


# ============================================================
# 1. PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="HPE CaseFlow",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# 2. CUSTOM STYLING
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
            background-color: var(--hpe-light-bg);
        }

        .block-container {
            padding-top: 1rem;
            padding-bottom: 2rem;
            max-width: 98% !important;
        }

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

        .auth-panel {
            background-color: #002B49;
            color: white;
            padding: 40px;
            border-radius: 14px;
            min-height: 560px;
        }

        .auth-panel h1 {
            color: white;
        }

        .auth-panel h2 {
            color: #01A781;
        }

        .auth-feature {
            margin: 20px 0;
        }

        section[data-testid="stSidebar"] {
            background-color: #002B49;
        }

        section[data-testid="stSidebar"] * {
            color: white;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# 3. APPLICATION CONSTANTS
# ============================================================

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
    }

    for key, value in defaults.items():

        if key not in st.session_state:
            st.session_state[key] = value


initialize_session()


# ============================================================
# 5. MONGODB CONNECTION
# ============================================================

@st.cache_resource(
    ttl=60,
    show_spinner=False,
)
def get_mongo_client():

    mongo_uri = st.secrets.get(
        "MONGO_URI",
        DEFAULT_MONGO_URI,
    )

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

        client.admin.command("ping")

        return client

    except Exception:

        return None


@st.cache_resource(
    ttl=60,
    show_spinner=False,
)
def get_roster_collection():

    client = get_mongo_client()

    if client is None:
        return None

    try:

        return client[
            DB_NAME
        ][ROSTER_COLLECTION]

    except Exception:

        return None


roster_collection = get_roster_collection()


# ============================================================
# 6. INITIALIZE FALLBACK DATA
# ============================================================

def initialize_mock_data():

    # --------------------------------------------------------
    # IMPORTANT:
    # No preconfigured personal/admin account is created here.
    # --------------------------------------------------------

    if not st.session_state.mock_db:

        st.session_state.mock_db = []

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
                "last_update": (
                    now - dt.timedelta(hours=25)
                ),
            },

            {
                "case_id": "0000143",
                "subject": "Server replacement",
                "priority": "High",
                "due_date": "Today 5:00 PM",
                "status": "Pending Vendor",
                "assigned_to": "john.delacruz@hpe.com",
                "last_update": (
                    now - dt.timedelta(hours=1)
                ),
            },

            {
                "case_id": "0000132",
                "subject": "Software license",
                "priority": "Medium",
                "due_date": "Apr 30, 2026",
                "status": "Assigned",
                "assigned_to": "mark.rivera@hpe.com",
                "last_update": (
                    now - dt.timedelta(hours=5)
                ),
            },

            {
                "case_id": "0000128",
                "subject": "Site installation",
                "priority": "Medium",
                "due_date": "May 1, 2026",
                "status": "In Progress",
                "assigned_to": "ana.reyes@hpe.com",
                "last_update": (
                    now - dt.timedelta(hours=2)
                ),
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

        st.session_state.requests_db = []


initialize_mock_data()


# ============================================================
# 7. AUTHENTICATION
# ============================================================

def find_user(email, password):

    email = email.strip().lower()

    # --------------------------------------------------------
    # MongoDB
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Fallback memory database
    # --------------------------------------------------------

    return next(
        (
            user
            for user
            in st.session_state.mock_db

            if user.get(
                "email",
                "",
            ).lower() == email

            and user.get(
                "password"
            ) == password

            and user.get(
                "status"
            ) == "Active"
        ),
        None,
    )


def create_user(user):

    if roster_collection is not None:

        try:

            # Prevent duplicate emails
            existing = roster_collection.find_one(
                {
                    "email": user["email"]
                },
                {
                    "_id": 1
                },
            )

            if existing:
                return False

            roster_collection.insert_one(
                user
            )

            return True

        except PyMongoError:

            return False

    # Fallback database

    if any(
        u.get("email", "").lower()
        == user["email"].lower()
        for u in st.session_state.mock_db
    ):
        return False

    st.session_state.mock_db.append(
        user
    )

    return True


# ============================================================
# 8. LOGIN / SIGN-UP PAGE
# ============================================================

def render_auth_page():

    left, right = st.columns(
        [1, 1.15],
        gap="large",
    )

    with left:

        st.markdown(
            """
            <div class="auth-panel">

                <h2>
                    Hewlett Packard Enterprise
                </h2>

                <h1>
                    HPE CaseFlow
                </h1>

                <p style="
                    color:#CBD5E1;
                    font-size:1.05rem;
                ">
                    Team Task and Case Management System
                </p>

                <br>

                <div class="auth-feature">
                    <b>▤ Manage Cases</b><br>
                    <small>
                        Track and resolve tasks efficiently
                    </small>
                </div>

                <div class="auth-feature">
                    <b>◈ Team Collaboration</b><br>
                    <small>
                        Work together for better service delivery
                    </small>
                </div>

                <div class="auth-feature">
                    <b>◉ Real-Time Visibility</b><br>
                    <small>
                        Stay informed and in control
                    </small>
                </div>

                <div class="auth-feature">
                    <b>▣ Secure Access</b><br>
                    <small>
                        HPE employees only
                    </small>
                </div>

            </div>
            """,
            unsafe_allow_html=True,
        )

    with right:

        st.markdown(
            "## Welcome to HPE CaseFlow"
        )

        auth_mode = st.radio(
            "Authentication",
            [
                "Sign In",
                "Sign Up",
            ],
            horizontal=True,
            label_visibility="collapsed",
        )

        # ====================================================
        # SIGN IN
        # ====================================================

        if auth_mode == "Sign In":

            st.subheader("Sign In")

            st.caption(
                "Access your HPE CaseFlow account."
            )

            email = st.text_input(
                "HPE Email Address",
                placeholder="name@hpe.com",
            )

            password = st.text_input(
                "Password",
                type="password",
            )

            if st.button(
                "Sign In",
                type="primary",
                use_container_width=True,
            ):

                if not email or not password:

                    st.warning(
                        "Enter your email and password."
                    )

                else:

                    user = find_user(
                        email,
                        password,
                    )

                    if user:

                        st.session_state.authenticated = True

                        st.session_state.user_data = user

                        st.rerun()

                    else:

                        st.error(
                            "Invalid email or password."
                        )

        # ====================================================
        # SIGN UP
        # ====================================================

        else:

            st.subheader(
                "Create Account"
            )

            st.caption(
                "Create your HPE CaseFlow account."
            )

            c1, c2 = st.columns(2)

            with c1:

                fn = st.text_input(
                    "First Name"
                )

                emp_id = st.text_input(
                    "Employee ID"
                )

            with c2:

                ln = st.text_input(
                    "Last Name"
                )

                email = st.text_input(
                    "HPE Email Address",
                    placeholder="name@hpe.com",
                )

            bday = st.date_input(
                "Birthday",
                min_value=dt.date(
                    1950,
                    1,
                    1,
                ),
            )

            addr = st.text_area(
                "Home Address"
            )

            contact = st.text_input(
                "Contact Number"
            )

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

                email = (
                    email.strip().lower()
                )

                if not email.endswith(
                    "@hpe.com"
                ):

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

                    st.error(
                        "Passwords do not match."
                    )

                else:

                    new_user = {

                        "first_name":
                            fn.strip(),

                        "last_name":
                            ln.strip(),

                        "employee_id":
                            emp_id.strip(),

                        "email":
                            email,

                        "birthday":
                            str(bday),

                        "address":
                            addr.strip(),

                        "contact":
                            contact.strip(),

                        "password":
                            pwd,

                        "role":
                            "Agent",

                        "aux":
                            "Busy - Away",

                        "status":
                            "Active",
                    }

                    if create_user(
                        new_user
                    ):

                        st.success(
                            "Account created successfully. "
                            "You can now sign in."
                        )

                    else:

                        st.error(
                            "An account with this email "
                            "already exists."
                        )


# ============================================================
# 9. AUTH CHECK
# ============================================================

if not st.session_state.authenticated:

    render_auth_page()

    st.stop()


# ============================================================
# 10. REFRESH ONLY AFTER LOGIN
# ============================================================

st_autorefresh(
    interval=30000,
    key="caseflow_refresh",
)


# ============================================================
# 11. CURRENT USER
# ============================================================

user = st.session_state.user_data

is_admin = (
    user.get("role") == "Admin"
)


# ============================================================
# 12. AUTOMATIC CASE ASSIGNMENT
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
        u
        for u
        in st.session_state.mock_db

        if u.get("role") == "Agent"

        and u.get("status") == "Active"

        and u.get("aux") == "Available"
    ]


def auto_assign_cases():

    cases = (
        st.session_state.cases_db
    )

    unassigned = [
        case
        for case in cases

        if case.get(
            "assigned_to"
        ) == "Unassigned"
    ]

    if not unassigned:
        return

    agents = get_available_agents()

    if not agents:
        return

    load = Counter(
        case.get("assigned_to")
        for case in cases

        if case.get(
            "assigned_to"
        ) != "Unassigned"
    )

    for case in unassigned:

        target = min(
            agents,
            key=lambda agent:
                load.get(
                    agent["email"],
                    0,
                ),
        )

        case["assigned_to"] = (
            target["email"]
        )

        case["status"] = "Assigned"

        load[
            target["email"]
        ] += 1


auto_assign_cases()


# ============================================================
# 13. AUX UPDATE
# ============================================================

def update_aux(new_aux):

    user["aux"] = new_aux

    if roster_collection is not None:

        try:

            roster_collection.update_one(
                {
                    "email":
                        user["email"]
                },
                {
                    "$set":
                    {
                        "aux":
                            new_aux
                    }
                },
            )

        except PyMongoError:

            pass


# ============================================================
# 14. HEADER
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
        "Busy - Away",
    )

    aux_options = (
        AUX_OPTIONS.copy()
    )

    if is_admin:

        aux_options.insert(
            0,
            "Admin Task",
        )

    selected_aux = st.selectbox(
        "AUX",
        aux_options,
        index=(
            aux_options.index(
                current_aux
            )
            if current_aux
            in aux_options
            else 0
        ),
        label_visibility="collapsed",
    )

    if selected_aux != current_aux:

        update_aux(
            selected_aux
        )

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
            <b>
                {user.get('first_name', '')}
                {user.get('last_name', '')}
            </b><br>
            <small>
                {user.get('role', 'Agent')}
            </small>
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
# 15. SIDEBAR
# ============================================================

st.sidebar.markdown(
    f"""
    <div style="
        padding:10px 0 20px 0;
        border-bottom:
        1px solid rgba(255,255,255,0.2);
    ">

        <b>HPE CaseFlow</b><br>

        <small>
            {user.get('role', 'Agent')}
        </small>

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
# 16. CASE HELPERS
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
                case.get(
                    "priority"
                ),
                99,
            ),
            case.get(
                "due_date",
                "",
            ),
        ),
    )


def cases_dataframe(cases):

    rows = []

    for case in sort_cases(
        cases
    ):

        rows.append(
            {
                "Case ID":
                    case.get(
                        "case_id"
                    ),

                "Subject":
                    case.get(
                        "subject"
                    ),

                "Priority":
                    case.get(
                        "priority"
                    ),

                "Due Date":
                    case.get(
                        "due_date"
                    ),

                "Status":
                    case.get(
                        "status"
                    ),

                "Assigned To":
                    case.get(
                        "assigned_to"
                    ),
            }
        )

    return pd.DataFrame(rows)


def show_metrics(
    cases,
    prefix="",
):

    active = len(cases)

    critical = sum(
        1
        for case in cases
        if case.get(
            "priority"
        ) == "Critical"
    )

    due_soon = sum(
        1
        for case in cases
        if "Today"
        in case.get(
            "due_date",
            "",
        )
    )

    on_track = sum(
        1
        for case in cases
        if case.get(
            "priority"
        )
        in [
            "Medium",
            "Low",
        ]
    )

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        f"{prefix} Active Cases",
        active,
    )

    c2.metric(
        "Critical",
        critical,
    )

    c3.metric(
        "Due Soon",
        due_soon,
    )

    c4.metric(
        "On Track",
        on_track,
    )


# ============================================================
# 17. REGULAR AGENT VIEW
# ============================================================

if not is_admin:

    my_cases = [
        case
        for case
        in st.session_state.cases_db

        if case.get(
            "assigned_to"
        )
        == user.get(
            "email"
        )
    ]

    # --------------------------------------------------------
    # DASHBOARD
    # --------------------------------------------------------

    if menu == "Dashboard":

        st.subheader(
            f"Good Morning, "
            f"{user.get('first_name', 'Agent')}!"
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

        st.markdown(
            "### Alerts"
        )

        now = dt.datetime.now()

        stale = [
            case
            for case in my_cases

            if (
                now
                - case.get(
                    "last_update",
                    now,
                )
            ).total_seconds()
            > 86400
        ]

        critical = [
            case
            for case in my_cases

            if case.get(
                "priority"
            )
            == "Critical"
        ]

        if stale:

            st.warning(
                f"⚠️ {len(stale)} case(s) "
                "have not been updated "
                "for more than 24 hours."
            )

        for case in critical:

            st.error(
                f"🚨 Case #{case['case_id']} "
                f"({case['subject']}) is Critical."
            )

        st.markdown(
            "### My Cases"
        )

        search = st.text_input(
            "Search",
            placeholder=(
                "Case number, subject, status..."
            ),
        )

        filtered = my_cases

        if search:

            q = search.lower()

            filtered = [
                case
                for case
                in my_cases

                if q
                in str(
                    case.get(
                        "case_id",
                        "",
                    )
                ).lower()

                or q
                in str(
                    case.get(
                        "subject",
                        "",
                    )
                ).lower()

                or q
                in str(
                    case.get(
                        "status",
                        "",
                    )
                ).lower()
            ]

        st.dataframe(
            cases_dataframe(
                filtered
            ),
            use_container_width=True,
            hide_index=True,
        )

    # --------------------------------------------------------
    # MY CASES
    # --------------------------------------------------------

    elif menu == "My Cases":

        st.subheader(
            "My Cases Management"
        )

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
                for case
                in my_cases

                if case[
                    "case_id"
                ]
                == selected_id
            )

            left, right = st.columns(2)

            with left:

                st.markdown(
                    f"### Case #{case['case_id']}"
                )

                st.write(
                    f"**Subject:** "
                    f"{case['subject']}"
                )

                st.write(
                    f"**Priority:** "
                    f"{case['priority']}"
                )

                st.write(
                    f"**Due Date:** "
                    f"{case['due_date']}"
                )

                st.write(
                    f"**Status:** "
                    f"{case['status']}"
                )

                sf_url = (
                    "https://hp.lightning.force.com/"
                    f"lightning/r/Case/"
                    f"{case['case_id']}/view"
                )

                st.markdown(
                    f"[Open Salesforce Case ↗]"
                    f"({sf_url})"
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

                current = case.get(
                    "status",
                    "Assigned",
                )

                status_index = (
                    statuses.index(
                        current
                    )
                    if current
                    in statuses
                    else 0
                )

                new_status = st.selectbox(
                    "Update Status",
                    statuses,
                    index=status_index,
                )

                if new_status == (
                    "Contract Breached"
                ):

                    reason = st.selectbox(
                        "Breach Reason",
                        [
                            "SLA Missed",
                            "Vendor Unresponsive",
                            "Part Out of Stock",
                        ],
                    )

                    st.text_area(
                        "Notification",
                        value=(
                            "Dear Team,\n\n"
                            f"Case #{case['case_id']} "
                            "breached SLA due to: "
                            f"{reason}."
                        ),
                    )

                if st.button(
                    "Save Case Update",
                    type="primary",
                    use_container_width=True,
                ):

                    case["status"] = (
                        new_status
                    )

                    case["last_update"] = (
                        dt.datetime.now()
                    )

                    st.success(
                        "Case updated successfully."
                    )

    # --------------------------------------------------------
    # SCHEDULE
    # --------------------------------------------------------

    elif menu == "Schedule":

        st.subheader(
            "My Schedule"
        )

        day, week, month = st.tabs(
            [
                "Day",
                "Week",
                "Month",
            ]
        )

        with day:

            st.table(
                [
                    {
                        "Time":
                            "08:00 AM - 10:00 AM",
                        "Activity":
                            "Work / Case Processing",
                    },
                    {
                        "Time":
                            "10:00 AM - 10:15 AM",
                        "Activity":
                            "Break",
                    },
                    {
                        "Time":
                            "10:15 AM - 12:00 PM",
                        "Activity":
                            "Work / Case Processing",
                    },
                    {
                        "Time":
                            "12:00 PM - 01:00 PM",
                        "Activity":
                            "Lunch",
                    },
                    {
                        "Time":
                            "03:00 PM - 03:15 PM",
                        "Activity":
                            "Break",
                    },
                ]
            )

        with week:

            st.info(
                "Weekly schedule."
            )

        with month:

            st.info(
                "Monthly schedule."
            )

    # --------------------------------------------------------
    # REQUESTS
    # --------------------------------------------------------

    elif menu == "Requests":

        st.subheader(
            "Submit Request"
        )

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

            start = st.date_input(
                "Start Date"
            )

        with c2:

            end = st.date_input(
                "End Date"
            )

        reason = st.text_input(
            "Reason"
        )

        if st.button(
            "Submit Request",
            type="primary",
        ):

            st.session_state.requests_db.append(
                {
                    "agent":
                        (
                            f"{user.get('first_name', '')} "
                            f"{user.get('last_name', '')}"
                        ),

                    "type":
                        req_type,

                    "start":
                        str(start),

                    "end":
                        str(end),

                    "reason":
                        reason,

                    "status":
                        (
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
# 18. ADMIN VIEW
# ============================================================

else:

    all_cases = (
        st.session_state.cases_db
    )

    # --------------------------------------------------------
    # DASHBOARD
    # --------------------------------------------------------

    if menu == "Dashboard":

        st.subheader(
            "Team Overview"
        )

        show_metrics(
            all_cases
        )

        left, right = st.columns(2)

        with left:

            st.markdown(
                "### Agent Status Distribution"
            )

            if roster_collection is not None:

                try:

                    agents = list(
                        roster_collection.find(
                            {
                                "role":
                                    "Agent",
                                "status":
                                    "Active",
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
                    u
                    for u
                    in st.session_state.mock_db

                    if u.get(
                        "role"
                    )
                    == "Agent"
                ]

            status_counts = Counter(
                agent.get(
                    "aux",
                    "Offline",
                )
                for agent
                in agents
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

                st.plotly_chart(
                    fig,
                    use_container_width=True,
                )

            else:

                st.info(
                    "No active agents found."
                )

        with right:

            st.markdown(
                "### Active Cases by Agent"
            )

            if all_cases:

                counts = Counter(
                    case.get(
                        "assigned_to",
                        "Unassigned",
                    )
                    for case
                    in all_cases
                )

                chart_df = pd.DataFrame(
                    {
                        "Agent":
                            list(
                                counts.keys()
                            ),

                        "Cases":
                            list(
                                counts.values()
                            ),
                    }
                )

                fig = px.bar(
                    chart_df,
                    x="Agent",
                    y="Cases",
                )

                st.plotly_chart(
                    fig,
                    use_container_width=True,
                )

    # --------------------------------------------------------
    # CASES
    # --------------------------------------------------------

    elif menu == "Cases":

        st.subheader(
            "All Cases Control"
        )

        search = st.text_input(
            "Search Cases",
            placeholder=(
                "Case ID, subject, "
                "priority, status..."
            ),
        )

        filtered = all_cases

        if search:

            q = search.lower()

            filtered = [
                case
                for case
                in all_cases

                if q
                in str(
                    case.get(
                        "case_id",
                        "",
                    )
                ).lower()

                or q
                in str(
                    case.get(
                        "subject",
                        "",
                    )
                ).lower()

                or q
                in str(
                    case.get(
                        "priority",
                        "",
                    )
                ).lower()

                or q
                in str(
                    case.get(
                        "status",
                        "",
                    )
                ).lower()

                or q
                in str(
                    case.get(
                        "assigned_to",
                        "",
                    )
                ).lower()
            ]

        st.dataframe(
            cases_dataframe(
                filtered
            ),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown(
            "### Reassign Case"
        )

        if all_cases:

            cid = st.selectbox(
                "Case ID",
                [
                    c["case_id"]
                    for c
                    in all_cases
                ],
            )

            new_agent = st.text_input(
                "Agent Email",
                placeholder="agent@hpe.com",
            )

            if st.button(
                "Reassign Case",
                type="primary",
            ):

                target = next(
                    c
                    for c
                    in all_cases

                    if c[
                        "case_id"
                    ]
                    == cid
                )

                target[
                    "assigned_to"
                ] = (
                    new_agent
                    .strip()
                    .lower()
                )

                target[
                    "last_update"
                ] = (
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

            roster = (
                st.session_state.mock_db
            )

        if not roster:

            st.info(
                "No roster records found."
            )

        else:

            for agent in roster:

                c1, c2, c3 = st.columns(
                    [3, 2, 1]
                )

                with c1:

                    st.write(
                        f"**{agent.get('first_name', '')} "
                        f"{agent.get('last_name', '')}**"
                    )

                    st.caption(
                        agent.get(
                            "email",
                            "",
                        )
                    )

                with c2:

                    st.write(
                        "AUX: "
                        f"`{agent.get('aux', 'Offline')}`"
                    )

                with c3:

                    if agent.get(
                        "role"
                    ) == "Agent":

                        if st.button(
                            "Kick",
                            key=(
                                "kick_"
                                + agent.get(
                                    "email",
                                    "",
                                )
                            ),
                        ):

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
                                            {
                                                "aux":
                                                    "Busy - Away"
                                            }
                                        },
                                    )

                                except PyMongoError:

                                    pass

                            agent[
                                "aux"
                            ] = "Busy - Away"

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
            "Interval Optimizer: "
            "Auto-ensuring queue coverage "
            "across operating hours."
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

        csv = (
            pd.DataFrame(
                st.session_state.cases_db
            )
            .to_csv(index=False)
            .encode("utf-8")
        )

        st.download_button(
            "Export Cases to CSV",
            data=csv,
            file_name=(
                "hpe_cases_report.csv"
            ),
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

        mongo_status = (
            "🟢 Connected"
            if roster_collection
            is not None
            else
            "🟠 Offline / Local Session Mode"
        )

        st.write(
            f"**Database:** `{DB_NAME}`"
        )

        st.write(
            f"**Collection:** "
            f"`{ROSTER_COLLECTION}`"
        )

        st.write(
            f"**MongoDB Status:** "
            f"{mongo_status}"
        )

        st.info(
            "Administrator accounts are managed "
            "through the Team Roster Collection. "
            "No administrator account is hard-coded "
            "in this application."
        )
```

**Important:** if the account already exists in your MongoDB database, removing it from the Python code **does not delete the existing database record**. The uploaded code only showed the application creating that record automatically; it did not contain a database-deletion operation.

So after deploying this version, `Team Roster Collection` will retain any existing records unless you explicitly remove them from MongoDB.
