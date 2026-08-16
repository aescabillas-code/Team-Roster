import calendar
from datetime import date, datetime, time, timedelta
import re
import altair as alt
import holidays
import pandas as pd
from pymongo import MongoClient
import pytz
import streamlit as st
import smtplib

st.set_page_config(layout="wide")


# --- DATABASE HELPERS & CONNECTION ---
@st.cache_resource
def get_mongo_client():
    uri = st.secrets["mongo"]["uri"]
    return MongoClient(uri)


client = get_mongo_client()
db = client["my_database"]
collection = db["my_collection"]


# --- CACHED DATA FETCHERS (Optimized TTL & Projections) ---
@st.cache_data(ttl=120)
def fetch_roster_doc():
    try:
        return collection.find_one({"type": "roster_list"}) or {}
    except Exception:
        return {}


@st.cache_data(ttl=120)
def fetch_calendar_doc():
    try:
        return collection.find_one({"type": "calendar_data"}) or {}
    except Exception:
        return {}


@st.cache_data(ttl=120)
def fetch_masterfile_doc():
    try:
        return collection.find_one({"type": "masterfile"}) or {}
    except Exception:
        return {}


@st.cache_data(ttl=60)
def get_cases_from_db():
    try:
        return list(collection.find({"type": "case"}))
    except Exception:
        return []


@st.cache_data(ttl=60)
def fetch_deviations_from_db():
    try:
        return list(collection.find({"type": "deviation"}))
    except Exception:
        return []


@st.cache_data(ttl=60)
def fetch_approved_requests_from_db():
    try:
        return list(
            collection.find({
                "type": {"$in": ["PTO", "Wellness", "SL/EL"]},
                "status": {"$in": ["RTM_Pending", "RTM_Approved"]},
            })
        )
    except Exception:
        return []


@st.cache_data(ttl=60)
def fetch_rejected_requests_from_db():
    try:
        return list(collection.find({"status": "Rejected"}))
    except Exception:
        return []


global_rejected_requests = fetch_rejected_requests_from_db()


@st.cache_data(ttl=60)
def fetch_pending_requests_from_db():
    try:
        return list(
            collection.find({
                "type": {"$in": ["PTO", "Wellness", "SL/EL"]},
                "status": "Pending",
            })
        )
    except Exception:
        return []


@st.cache_data(ttl=60)
def fetch_rtm_processed_requests_from_db():
    try:
        return list(
            collection.find({
                "type": {"$in": ["PTO", "Wellness", "SL/EL"]},
                "status": "RTM_Approved",
            })
        )
    except Exception:
        return []


# --- DB MUTATION HELPERS ---
def clear_requests_cache():
    fetch_approved_requests_from_db.clear()
    fetch_pending_requests_from_db.clear()
    fetch_rejected_requests_from_db.clear()
    fetch_rtm_processed_requests_from_db.clear()


def bulk_update_requests(request_ids, status):
    collection.update_many(
        {"_id": {"$in": request_ids}}, {"$set": {"status": status}}
    )
    clear_requests_cache()


def bulk_delete_requests(request_ids):
    collection.delete_many({"_id": {"$in": request_ids}})
    clear_requests_cache()


def update_request_fields(request_id, update_dict):
    collection.update_one({"_id": request_id}, {"$set": update_dict})
    clear_requests_cache()


def bulk_update_rtm_status(request_ids, status):
    collection.update_many(
        {"_id": {"$in": request_ids}}, {"$set": {"status": status}}
    )
    clear_requests_cache()


def save_staff(name, data):
    st.session_state.staff_roster[name] = data
    collection.update_one(
        {"type": "roster_list"},
        {"$set": {"data": st.session_state.staff_roster}},
        upsert=True,
    )
    fetch_roster_doc.clear()


def delete_staff(name):
    if name in st.session_state.staff_roster:
        del st.session_state.staff_roster[name]
    collection.update_one(
        {"type": "roster_list"},
        {"$set": {"data": st.session_state.staff_roster}},
        upsert=True,
    )
    fetch_roster_doc.clear()


def update_staff_in_db(name, update_dict):
    if name in st.session_state.staff_roster:
        st.session_state.staff_roster[name].update(update_dict)
    collection.update_one(
        {"type": "roster_list"},
        {"$set": {"data": st.session_state.staff_roster}},
        upsert=True,
    )
    fetch_roster_doc.clear()


def save_case_to_db(case_data):
    case_data["type"] = "case"
    collection.insert_one(case_data)
    get_cases_from_db.clear()


def save_deviation_to_db(data):
    data["type"] = "deviation"
    collection.insert_one(data)
    fetch_deviations_from_db.clear()


def update_deviation_in_db(id_val, update_dict):
    collection.update_one({"_id": id_val}, {"$set": update_dict})
    fetch_deviations_from_db.clear()


def delete_deviation_from_db(id_val):
    collection.delete_one({"_id": id_val})
    fetch_deviations_from_db.clear()


def delete_request_from_db(req):
    collection.delete_one({"_id": req["_id"]})
    clear_requests_cache()


def update_request_status_in_db(req, status):
    update_data = {"status": status}
    collection.update_one({"_id": req["_id"]}, {"$set": update_data})
    clear_requests_cache()


def save_request_to_db(req, request_type):
    req["type"] = request_type
    if request_type == "SL/EL":
        req["status"] = "RTM_Approved"
    else:
        req["status"] = "Pending"
    collection.insert_one(req)
    clear_requests_cache()


def save_masterfile_to_db(df):
    collection.update_one(
        {"type": "masterfile"},
        {"$set": {"data": df.to_dict(orient="records")}},
        upsert=True,
    )
    fetch_masterfile_doc.clear()


def get_request_limits(req_date):
    cal_doc = fetch_calendar_doc()
    selected_config = cal_doc.get("data", {}).get(str(req_date), {})

    st.session_state.limits["PTO_per_day"] = selected_config.get(
        "PTO_per_day", 1
    )
    st.session_state.limits["Wellness_per_day"] = selected_config.get(
        "Wellness_per_day", 1
    )
    return st.session_state.limits


def calculate_duration_mins(start_str, end_str):
    """Calculates non-zero positive duration minutes between HH:MM strings accurately."""
    try:
        time_fmt = "%H:%M"
        start_dt = datetime.strptime(start_str.strip(), time_fmt)
        end_dt = datetime.strptime(end_str.strip(), time_fmt)

        if end_dt < start_dt:
            end_dt += timedelta(days=1)  # Overlap across midnight

        diff_mins = int((end_dt - start_dt).total_seconds() // 60)
        return max(0, diff_mins)
    except Exception:
        return 0


# --- INITIAL CONFIG & STATE ---
st.title("📊 Team Operations Management System (TOMS)")

local_tz = pytz.timezone("Asia/Manila")
current_date = datetime.now(local_tz).date()

if "admin_password" not in st.session_state:
    st.session_state.admin_password = "Password1234"
if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False
if "limits" not in st.session_state:
    st.session_state.limits = {"PTO_per_day": 1, "Wellness_per_day": 1}
if "notifications" not in st.session_state:
    st.session_state.notifications = []
if "master_data" not in st.session_state:
    st.session_state.master_data = pd.DataFrame({
        "Category": ["Contact Type", "Issue", "Product Group"],
        "Values": ["Call,Chat,Email", "Tech,Billing", "Hardware,Soft"],
    })

# Fetch heavy datasets exactly ONCE per runner cycle globally
roster_doc = fetch_roster_doc()
st.session_state.staff_roster = roster_doc.get("data", {}) if roster_doc else {}

# Data migration normalization
if "staff_roster" in st.session_state:
    for name, value in st.session_state.staff_roster.items():
        if (
            isinstance(value, dict)
            and isinstance(value.get("bday"), date)
            and not isinstance(value.get("bday"), datetime)
        ):
            d = value["bday"]
            value["bday"] = datetime(d.year, d.month, d.day)

calendar_doc = fetch_calendar_doc()
raw_cal_data = calendar_doc.get("data", {}) if calendar_doc else {}
st.session_state.calendar_data = {
    (
        datetime.strptime(k, "%Y-%m-%d").date()
        if isinstance(k, str) and len(k) == 10
        else k
    ): v
    for k, v in raw_cal_data.items()
}

global_approved_requests = fetch_approved_requests_from_db()
global_pending_requests = fetch_pending_requests_from_db()
global_rejected_requests = fetch_rejected_requests_from_db()

# Filter for approved display on Tab 1 calendar and sidebar (RTM_Approved or auto-approved SL/EL)
global_approved_calendar_requests = [
    r
    for r in global_approved_requests
    if r.get("status") == "RTM_Approved" or r.get("type") == "SL/EL"
]

# Fetch RTM requests from DB
global_rtm_processed_requests = fetch_rtm_processed_requests_from_db()

# --- GLOBAL CSS STYLING ---
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;700&display=swap');
    html, body, [class*="css"] { font-family: 'Montserrat', sans-serif !important; }
    h1, h2, h3, .header-cell { font-family: 'Montserrat', sans-serif !important; font-weight: 700; color: #008080 !important; }
    .side-block { font-family: 'Montserrat', sans-serif !important; font-size: 10px !important; line-height: 1.2; }
    
    .day-block { 
        border-radius: 0px; 
        padding: 10px; 
        height: 100%; 
        min-height: 280px; 
        font-size: 11px; 
        background-color: rgba(0, 128, 128, 0.75); 
        color: #ffffff !important;
        border: 1px solid #ffffff !important;
        margin: 0px; 
        display: flex; 
        flex-direction: column; 
        box-sizing: border-box;
    }

    .day-block-outside, .day-block:empty {
        background-color: rgba(230, 242, 242, 0.85) !important;
        border: 1px solid #008080 !important;
        color: #008080 !important;
    }

    .day-block-outside *, .day-block:empty * { color: #008080 !important; }
    div[data-testid="stHorizontalBlock"] { gap: 0px !important; }
    div[data-testid="stHorizontalBlock"]:has(.day-block) { margin: 0px !important; padding: 0px !important; }
    div[data-testid="stColumn"]:has(.day-block), div[data-testid="stColumn"]:has(.day-block-outside) { padding-right: 4px !important; }
    div[data-testid="stHorizontalBlock"]:has(.day-block), div[data-testid="stHorizontalBlock"]:has(.day-block-outside) { margin-bottom: 25px !important; }
    .day-block > b:first-of-type { font-size: 16px !important; display: block; margin-bottom: 2px; }
    .day-block u, .day-block center, .day-block b { color: #ffffff !important; }
    .calendar-divider { border-top: 1px solid rgba(255, 255, 255, 0.4); margin: 5px 0; width: 100%; }
    div.stButton > button { background: linear-gradient(90deg, #7b61ff 0%, #3b82f6 100%); color: white; border-radius: 12px; font-weight: 600; }
    .header-cell { font-weight: bold; text-align: center; padding-bottom: 10px; }
    .alert-container { border-radius: 20px; border: 2px solid #ff4d4d; padding: 15px; background-color: #fff5f5; margin-bottom: 20px; }
    .flash-red { color: #ff4d4d; font-weight: bold; text-align: center; }
    
    div[data-baseweb="select"] > div {
        background-color: rgba(0, 128, 128, 0.75) !important;
        color: #ffffff !important;
        border-radius: 8px;
        border: 1px solid #00aaaa !important;
    }
    div[data-baseweb="select"] * { color: #ffffff !important; }
    div[data-baseweb="menu"] { background-color: rgba(0, 128, 128, 0.95) !important; border: 1px solid #00aaaa !important; }
    div[data-baseweb="menu"] li { color: #ffffff !important; background-color: transparent !important; }
    div[data-baseweb="menu"] li:hover { background-color: rgba(0, 170, 170, 0.4) !important; }

    div[data-testid="stTabs"] button {
        background: linear-gradient(90deg, #004d4d 0%, #008080 100%) !important;
        color: #ffffff !important;
        font-size: 18px !important;
        font-weight: 600 !important;
        padding: 12px 24px !important;
        border-radius: 8px 8px 0px 0px !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        margin-right: 4px !important;
    }
    div[data-testid="stTabs"] button[aria-selected="true"] {
        background: linear-gradient(90deg, #008080 0%, #00bcbc 100%) !important;
        color: #ffffff !important;
        border-bottom: 3px solid #ffffff !important;
    }

    div[data-testid="stForm"] input, 
    div[data-testid="stForm"] textarea,
    div[data-testid="stForm"] .stTextInput div div,
    div[data-testid="stForm"] .stNumberInput div div,
    div[data-testid="stForm"] .stDateInput div div,
    div[data-testid="stForm"] div[role="textarea"] {
        background-color: rgba(0, 128, 128, 0.75) !important;
        color: #ffffff !important;
        border: 1px solid #00aaaa !important;
    }
    div[data-testid="stForm"] input { -webkit-text-fill-color: #ffffff !important; color: #ffffff !important; }
    div[data-testid="stForm"] label, div[data-testid="stForm"] p { color: #008080 !important; font-weight: 600; }

    div[data-testid="stTable"] tr:nth-child(even) { background-color: rgba(0, 128, 128, 0.85) !important; }
    div[data-testid="stTable"] tr:nth-child(even) td { color: #ffffff !important; }
    div[data-testid="stTable"] tr:nth-child(odd) { background-color: #ffffff !important; }
    div[data-testid="stTable"] tr:nth-child(odd) td { color: #008080 !important; font-weight: 600; }
    div[data-testid="stTable"] th { background-color: #004d4d !important; color: #ffffff !important; }

    .qa-box-passed {
        background-color: #e6f4ea !important;
        border: 1px solid #34a853 !important;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 10px;
    }
    .qa-box-failed {
        background-color: #fce8e6 !important;
        border: 2px solid #ea4335 !important;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 10px;
    }
    .qa-box-passed * { color: #1e4620 !important; }
    .qa-box-failed * { color: #5c1d1d !important; }
    </style>
""",
    unsafe_allow_html=True,
)


# --- REQUEST RENDER HANDLER ---
def render_request(req, key_prefix):
    unique_id = str(req.get("_id", "fallback"))
    denial_key = f"denying_{key_prefix}_{unique_id}"

    st.info(
        f"Name: {req.get('name')}\nType: {req.get('type')}\nDate:"
        f" {req.get('date')}\nStatus: {req.get('status')}"
    )

    if not st.session_state.get(denial_key):
        c1, c2 = st.columns(2)
        if c1.button("Approve", key=f"app_{key_prefix}_{unique_id}"):
            update_request_status_in_db(req, "RTM_Pending")
            st.success("Approved!")
            st.rerun()
        if c2.button("Deny", key=f"den_{key_prefix}_{unique_id}"):
            st.session_state[denial_key] = True
            st.rerun()

    if st.session_state.get(denial_key):
        reason = st.text_input(
            "Reason for denial", key=f"reason_{key_prefix}_{unique_id}"
        )
        col1, col2 = st.columns(2)
        if col1.button(
            "Proceed Denial", key=f"confirm_{key_prefix}_{unique_id}"
        ):
            update_request_status_in_db(req, "Rejected")
            st.session_state[denial_key] = False
            st.success("Request denied.")
            st.rerun()
        if col2.button("Cancel", key=f"cancel_{key_prefix}_{unique_id}"):
            st.session_state[denial_key] = False
            st.rerun()


# --- TABS WORKSPACE ---
tab_names = [
    "📅 Calendar",
    "📝 Request",
    "🔑 Admin",
]

tab_cal, tab_req, tab_adm = st.tabs(tab_names)

# --- TAB 1: CALENDAR ---
with tab_cal:
    col_main, space_gap, col_side = st.columns([4, 0.2, 1])

    with col_main:
        c1, c2 = st.columns([1, 1])
        year = c1.selectbox("Year", [2026, 2027, 2028], key="cal_y")
        month = c2.selectbox(
            "Month",
            range(1, 13),
            format_func=lambda x: calendar.month_name[x],
            index=current_date.month - 1,
            key="cal_m",
        )

    roster = st.session_state.staff_roster

    with col_side:
        st.markdown('<div class="side-block">', unsafe_allow_html=True)
        st.subheader("Monthly Summary")

        st.markdown("**Birthdays:**")
        for name, info in roster.items():
            bday = info.get("bday") if isinstance(info, dict) else info
            if isinstance(bday, (date, datetime)) and bday.month == month:
                st.write(f"- {name}: {bday.strftime('%B %d')}")

        st.markdown("**Holidays:**")
        us_hols, ph_hols, found_holiday = (
            holidays.US(years=year),
            holidays.PH(years=year),
            False,
        )
        for d_obj, h_name in sorted(us_hols.items()):
            if d_obj.month == month:
                st.write(f"- [US] {h_name}: {d_obj.strftime('%B %d')}")
                found_holiday = True
        for d_obj, h_name in sorted(ph_hols.items()):
            if d_obj.month == month:
                st.write(f"- [PH] {h_name}: {d_obj.strftime('%B %d')}")
                found_holiday = True
        if not found_holiday:
            st.write("No holidays this month.")
        st.divider()

        st.subheader("Daily View")
        view_date = current_date

        d_data = (
            st.session_state.calendar_data.get(view_date)
            or st.session_state.calendar_data.get(str(view_date))
            or {}
        )

        st.markdown(f"### Date: {view_date.strftime('%B %d, %Y')}")

        if view_date.weekday() in [5, 6]:
            day_status, day_shift = "REST DAY", "--"
        else:
            day_status = d_data.get("status", "Not Set")
            day_shift = d_data.get("shift", "--")

        st.markdown(f"**Work Setup:** `{day_status}`")
        st.markdown(f"**Shift:** `{day_shift}`")

        tm_list = d_data.get("team_manager", [])
        tm_name = tm_list[0] if (isinstance(tm_list, list) and tm_list) else ""
        if tm_name:
            st.write(f"**Team Manager:** {tm_name}")

        st.write("**Today's Schedule:**")
        if view_date.weekday() in [5, 6]:
            st.info("📊 **Rest Day** — Weekend Schedule")
            sched_rows = [
                {"Name": name, "Role": "REST DAY"} for name in roster.keys()
            ]
            if sched_rows:
                sched_df = pd.DataFrame(sched_rows).sort_values(
                    by=["Role", "Name"], ascending=True
                )
                st.dataframe(
                    sched_df,
                    hide_index=True,
                    use_container_width=True,
                    height=min(1000, max(100, len(sched_df) * 35 + 38)),
                )
            else:
                st.write("*No staff configured in the system.*")
        else:
            roles = ["team_manager", "call", "chat", "mfq", "sme"]
            sched_rows = []
            for name in roster.keys():
                p_status = [
                    r["type"]
                    for r in global_approved_calendar_requests
                    if str(r["date"]) == str(view_date) and r["name"] == name
                ]
                if p_status:
                    role_display = p_status[0].upper()
                else:
                    assigned_roles = []
                    for r in roles:
                        assigned_list = d_data.get(r, [])
                        if (
                            isinstance(assigned_list, list)
                            and name in assigned_list
                        ):
                            assigned_roles.append(r.upper().replace("_", " "))
                        elif (
                            isinstance(assigned_list, dict)
                            and name in assigned_list.keys()
                        ):
                            assigned_roles.append(r.upper().replace("_", " "))
                    role_display = (
                        ", ".join(assigned_roles)
                        if assigned_roles
                        else "UNASSIGNED"
                    )

                if "TEAM MANAGER" in role_display or name == tm_name:
                    continue
                sched_rows.append({"Name": name, "Role": role_display})

            if sched_rows:
                sched_df = pd.DataFrame(sched_rows).sort_values(
                    by=["Role", "Name"], ascending=True
                )
                st.dataframe(
                    sched_df,
                    hide_index=True,
                    use_container_width=True,
                    height=min(1000, max(100, len(sched_df) * 35 + 38)),
                )
            else:
                st.write("*No staff configured in the system.*")
        st.markdown("</div>", unsafe_allow_html=True)

    with col_main:
        cols = st.columns(7)
        for i, d_name in enumerate(
            ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        ):
            cols[i].markdown(
                f'<div class="header-cell">{d_name}</div>',
                unsafe_allow_html=True,
            )

        for week in calendar.Calendar(firstweekday=6).monthdayscalendar(
            year, month
        ):
            cols = st.columns(7)
            for i, day in enumerate(week):
                if day != 0:
                    d = date(year, month, day)
                    approved = [
                        r
                        for r in global_approved_calendar_requests
                        if str(r["date"]) == str(d)
                    ]
                    away_names = [r["name"] for r in approved]

                    def get_filtered_nicks(full_names):
                        active = [n for n in full_names if n not in away_names]
                        return ", ".join(
                            [roster.get(x, {}).get("nick", x) for x in active]
                        )

                    req_display = "<br>".join([
                        f"{roster.get(r['name'], {}).get('nick', r['name'])}({r['type']})"
                        for r in approved
                    ])

                    grid_data = (
                        st.session_state.calendar_data.get(d)
                        or st.session_state.calendar_data.get(str(d))
                        or {}
                    )

                    if d.weekday() in [5, 6]:
                        content = (
                            f"<b>{day}</b><div"
                            " class='calendar-divider'></div><br><center><b>REST"
                            " DAY</b></center>"
                        )
                    else:
                        content = (
                            f"<b>{day}</b><div class='calendar-divider'></div>"
                            f"<u>{grid_data.get('status', '-')}</u><div"
                            " class='calendar-divider'></div>"
                            f"{grid_data.get('shift', '-')}<div"
                            " class='calendar-divider'></div>"
                            f"PTO/Wellness/SL: {req_display}<div"
                            " class='calendar-divider'></div>"
                            "Call:"
                            f" {get_filtered_nicks(grid_data.get('call', []))}<div"
                            " class='calendar-divider'></div>"
                            "Chat:"
                            f" {get_filtered_nicks(grid_data.get('chat', []))}<div"
                            " class='calendar-divider'></div>"
                            "MFQ:"
                            f" {get_filtered_nicks(grid_data.get('mfq', []))}<div"
                            " class='calendar-divider'></div>"
                            "SME:"
                            f" {get_filtered_nicks(grid_data.get('sme', []))}"
                        )

                    cols[i].markdown(
                        f'<div class="day-block">{content}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    cols[i].markdown(
                        '<div class="day-block day-block-outside"></div>',
                        unsafe_allow_html=True,
                    )

    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader("📆 Weekly Roster")

    month_start_date = date(year, month, 1)
    base_sunday = month_start_date - timedelta(
        days=(
            (month_start_date.weekday() + 1)
            if month_start_date.weekday() != 6
            else 0
        )
    )

    sunday_options = [base_sunday + timedelta(weeks=i) for i in range(0, 6)]
    today_sunday = current_date - timedelta(
        days=(current_date.weekday() + 1) if current_date.weekday() != 6 else 0
    )

    default_week_index = (
        sunday_options.index(today_sunday)
        if today_sunday in sunday_options
        else 0
    )

    selected_week_start = st.selectbox(
        "Select Week Beginning (Sunday):",
        options=sunday_options,
        index=default_week_index,
        format_func=lambda d: d.strftime("%B %d, %Y"),
        key="weekly_view_lookup_start_select",
    )

    week_start_sunday = pd.to_datetime(selected_week_start).date()
    week_days = [
        week_start_sunday + timedelta(days=idx) for idx in range(1, 6)
    ]

    roles = ["team_manager", "call", "chat", "mfq", "sme"]

    setup_row = {"Staff Name": "🛠️ WORK SETUP"}
    shift_row = {"Staff Name": "⏰ SHIFT"}
    weekly_tms = []

    for day in week_days:
        col_name = day.strftime("%A (%m/%d)")
        day_config = (
            st.session_state.calendar_data.get(day)
            or st.session_state.calendar_data.get(str(day))
            or {}
        )

        setup_row[col_name] = str(day_config.get("status", "Not Set")).upper()
        shift_row[col_name] = str(day_config.get("shift", "--")).upper()

        tm_found = day_config.get("team_manager", [])
        if tm_found and tm_found[0] not in weekly_tms:
            weekly_tms.append(tm_found[0])

    weekly_rows = []
    for name in roster.keys():
        staff_row = {"Staff Name": name}
        is_tm_somewhere = False

        for day in week_days:
            col_name = day.strftime("%A (%m/%d)")

            p_status = [
                r["type"]
                for r in global_approved_calendar_requests
                if str(r["date"]) == str(day) and r["name"] == name
            ]
            if p_status:
                staff_row[col_name] = p_status[0].upper()
            else:
                day_config = (
                    st.session_state.calendar_data.get(day)
                    or st.session_state.calendar_data.get(str(day))
                    or {}
                )

                assigned_roles = []
                for r in roles:
                    assigned_list = day_config.get(r, [])
                    if isinstance(assigned_list, list) and name in assigned_list:
                        assigned_roles.append(r.upper().replace("_", " "))
                    elif (
                        isinstance(assigned_list, dict)
                        and name in assigned_list.keys()
                    ):
                        assigned_roles.append(r.upper().replace("_", " "))

                role_display = (
                    ", ".join(assigned_roles) if assigned_roles else "UNASSIGNED"
                )

                if "TEAM MANAGER" in role_display:
                    is_tm_somewhere = True
                    break

                staff_row[col_name] = role_display

        if not is_tm_somewhere:
            weekly_rows.append(staff_row)

    tm_display_string = (
        ", ".join(set(weekly_tms)).upper() if weekly_tms else "NONE ASSIGNED"
    )
    st.markdown(f"## TEAM MANAGER: {tm_display_string}")
    st.write("")

    if weekly_rows:
        first_day_col = week_days[0].strftime("%A (%m/%d)")
        staff_df = pd.DataFrame(weekly_rows).sort_values(
            by=[first_day_col, "Staff Name"], ascending=True
        )
        meta_df = pd.DataFrame([setup_row, shift_row])
        weekly_df = pd.concat([meta_df, staff_df], ignore_index=True)

        column_configurations = {
            "Staff Name": st.column_config.TextColumn(label="Staff Name")
        }
        for day in week_days:
            c_name = day.strftime("%A (%m/%d)")
            column_configurations[c_name] = st.column_config.TextColumn(
                label=c_name
            )

        st.dataframe(
            weekly_df,
            column_config=column_configurations,
            hide_index=True,
            use_container_width=True,
            height=min(1000, max(100, len(weekly_df) * 35 + 38)),
        )
    else:
        st.write("*No scheduled staff found for this week.*")

# --- TAB 2: REQUEST FORM ---
with tab_req:
    from email.mime.text import MIMEText

    def send_request_email_notification(employee_name, req_date, req_type):
        try:
          sender_email = st.secrets["email"]["sender"]
          sender_password = st.secrets["email"]["password"]
          recipient_emails = [
              "arianne-may.escabillas@hpe.com",
              "jeff.bote@hpe.com",
              "jane-paula.manlangit@hpe.com",
          ]
    
          msg_body = f"A new leave request has been submitted by {employee_name}.\n\nType: {req_type}\nDate: {req_date}"
          msg = MIMEText(msg_body)
          msg["Subject"] = (
              f"New Leave Request Submitted: {req_type} - {employee_name}"
          )
          msg["From"] = "Leave Request Notification"
          msg["To"] = ", ".join(recipient_emails)
    
          with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient_emails, msg.as_string())
    
          st.success("Email sent successfully! 📧", icon="✅")
        except Exception as e:
          st.error(f"Failed to send email: {e}", icon="❌")
            
    st.subheader("PTO / Wellness / SL Request Form")

    if "request_count" not in st.session_state:
        st.session_state.request_count = 1

    available_names = ["Select Name..."] + list(st.session_state.staff_roster.keys())

    selected_name = st.selectbox(
        "Select Employee Name:", available_names, key="bulk_request_global_name"
    )

    with st.form("bulk_request_form"):
        st.markdown("### 📊 Request Entry Table")

        header_cols = st.columns([1, 1])
        header_cols[0].markdown("**Date**")
        header_cols[1].markdown("**Request Type**")

        for i in range(st.session_state.request_count):
            row_cols = st.columns([1, 1])
            with row_cols[0]:
                st.date_input(
                    "Date", label_visibility="collapsed", key=f"date_{i}"
                )
            with row_cols[1]:
                st.selectbox(
                    "Type",
                    ["PTO", "Wellness", "SL/EL"],
                    label_visibility="collapsed",
                    key=f"type_{i}",
                )

        st.markdown("<br>", unsafe_allow_html=True)
        
        action_cols = st.columns([1, 1, 2])
        with action_cols[0]:
            add_row_triggered = st.form_submit_button("➕ Add New Row")
        with action_cols[1]:
            submit_triggered = st.form_submit_button(
                "✅ Submit Entries", type="primary"
            )
            
        if add_row_triggered:
            if selected_name == "Select Name...":
                st.warning("⚠️ Please select a valid employee name to proceed.")
            else:
                st.session_state.request_count += 1
                st.rerun()

        if submit_triggered:
            if selected_name == "Select Name...":
                st.warning("⚠️ Please select a valid employee name to proceed.")
            else:
                running_caps = {}
                existing_requests = (
                    global_pending_requests + global_approved_requests
                )

                for i in range(st.session_state.request_count):
                    req_date = st.session_state[f"date_{i}"]
                    req_type = st.session_state[f"type_{i}"]
                    date_str = str(req_date)
                    cap_key = f"{req_type}_{date_str}"

                    is_already_requested = any(
                        r.get("name") == selected_name
                        and str(r.get("date")) == date_str
                        and r.get("status") in ["Pending", "RTM_Pending", "RTM_Approved"]
                        for r in existing_requests
                    )

                    if is_already_requested:
                        st.warning(
                            f"⚠️ A request for {selected_name} on {req_date} already"
                            " exists."
                        )
                        continue

                    if req_type == "SL/EL":
                        initial_status = "RTM_Approved"
                        new_req = {
                            "name": selected_name,
                            "date": date_str,
                            "type": req_type,
                            "status": initial_status,
                        }
                        save_request_to_db(new_req, req_type)
                        send_request_email_notification(selected_name, date_str, req_type)
                    else:
                        limits = get_request_limits(req_date)
                        limit_value = (
                            limits["PTO_per_day"]
                            if req_type == "PTO"
                            else limits["Wellness_per_day"]
                        )

                        if cap_key not in running_caps:
                            db_count = sum(
                                1
                                for r in existing_requests
                                if r.get("type") == req_type
                                and str(r.get("date")) == date_str
                                and r.get("status") in ["Pending", "RTM_Pending", "RTM_Approved"]
                            )
                            running_caps[cap_key] = db_count

                        if running_caps[cap_key] >= limit_value:
                            st.error(f"❌ Limit reached for {req_type} on {req_date}.")
                        else:
                            initial_status = "Pending"
                            new_req = {
                                "name": selected_name,
                                "date": date_str,
                                "type": req_type,
                                "status": initial_status,
                            }
                            save_request_to_db(new_req, req_type)
                            send_request_email_notification(selected_name, date_str, req_type)
                            running_caps[cap_key] += 1

                st.success(
                    "All operational entries successfully verified and processed!"
                )

                st.session_state.request_count = 1
                st.rerun()
                    
    # 1. Render date filters first so all sections can access f_m and f_y
    f_c1, f_c2 = st.columns(2)
    
    month_names = list(calendar.month_name)[1:]
    selected_month_name = f_c1.selectbox(
        "Month",
        month_names,
        index=current_date.month - 1,
        key="history_month_select",
    )
    f_m = month_names.index(selected_month_name) + 1
    f_y = f_c2.number_input(
        "Year", value=current_date.year, key="history_year_select"
    )
    
    # 2. Fetch roster_list from database to map full name -> emp_id
    roster_doc = collection.find_one({"type": "roster_list"})
    roster_data = roster_doc.get("data", {}) if roster_doc else {}
    roster_lookup = {
        name: details.get("emp_id", "N/A") 
        for name, details in roster_data.items()
    }

    # Helper function to format full names as "Last Name, First Name"
    def format_last_first(full_name):
        if not full_name or not isinstance(full_name, str):
            return ""
        parts = full_name.strip().split()
        if len(parts) > 1:
            return f"{parts[-1]}, {' '.join(parts[:-1])}"
        return full_name
    
    # Helper function to format dates as M/D/YYYY
    def format_m_d_yyyy(date_val):
        try:
            dt = pd.to_datetime(date_val)
            return f"{dt.month}/{dt.day}/{dt.year}"
        except Exception:
            return str(date_val)
    
    # Helper function to get emp_id from roster lookup or request data
    def get_emp_id(req):
        name = req.get("name", "")
        if name in roster_lookup and roster_lookup[name]:
            return roster_lookup[name]
        return req.get("emp_id", "N/A")

    # --- Section: Approved by RTM & Auto-Approved SL/EL ---
    st.subheader("RTM Approved")
    
    rtm_requests = global_rtm_processed_requests
    auto_sl_requests = [
        r for r in global_approved_requests
        if r.get("type") == "SL/EL"
    ]

    filtered_rtm = []
    for r in rtm_requests + auto_sl_requests:
        try:
            if r.get("type") != "SL/EL" and r.get("rtm_status") != "RTM_Approved":
                continue

            if isinstance(r.get("date"), str):
                parts = r["date"].split("-")
                r_month, r_year = int(parts[1]), int(parts[0])
            else:
                dt = pd.to_datetime(r.get("date"))
                r_month, r_year = dt.month, dt.year

            if r_month == f_m and r_year == f_y:
                r_copy = dict(r)
                r_copy["emp_id"] = get_emp_id(r_copy)
                r_copy["rtm_status"] = r.get("rtm_status", r.get("status", "N/A"))
                filtered_rtm.append(r_copy)
        except Exception:
            continue

    if filtered_rtm:
        df_rtm_display = pd.DataFrame(filtered_rtm)

        for col in ["date", "name", "rtm_status", "emp_id", "type", "status"]:
            if col not in df_rtm_display.columns:
                df_rtm_display[col] = "N/A"

        df_rtm_display["sort_date"] = pd.to_datetime(df_rtm_display["date"], errors="coerce")
        df_rtm_display = df_rtm_display.sort_values(by="sort_date", ascending=True)

        df_rtm_display["formatted_date"] = df_rtm_display["date"].apply(format_m_d_yyyy)
        df_rtm_display["formatted_name"] = df_rtm_display["name"].apply(format_last_first)

        df_rtm_display = df_rtm_display[["formatted_name", "emp_id", "formatted_date", "rtm_status"]]
        df_rtm_display.columns = ["Name", "Employee ID", "Date", "RTM Status"]

        st.dataframe(df_rtm_display, hide_index=True, use_container_width=True)
    else:
        st.write("No records found.")

    # --- Section: RTM Verification & Approval Level (Pending RTM Approval) ---
    st.subheader("Pending RTM Approval")
    
    filtered_rtm_pending = []
    for r in global_approved_requests:
        try:
            if r.get("type") == "SL/EL":
                continue
            if r.get("status") != "RTM_Pending":
                continue

            date_val = r.get("date")
            if isinstance(date_val, str):
                parts = date_val.split("-")
                r_year, r_month = int(parts[0]), int(parts[1])
            else:
                dt = pd.to_datetime(date_val)
                r_year, r_month = dt.year, dt.month

            if r_month == f_m and r_year == f_y:
                r_copy = dict(r)
                r_copy["emp_id"] = get_emp_id(r_copy)
                filtered_rtm_pending.append(r_copy)
        except Exception:
            continue

    if filtered_rtm_pending:
        df_rtm_pending_display = pd.DataFrame(filtered_rtm_pending)
        df_rtm_pending_display["sort_date"] = pd.to_datetime(df_rtm_pending_display["date"], errors="coerce")
        df_rtm_pending_display = df_rtm_pending_display.sort_values(by="sort_date", ascending=True)

        df_rtm_pending_display["formatted_date"] = df_rtm_pending_display["date"].apply(format_m_d_yyyy)
        df_rtm_pending_display["formatted_name"] = df_rtm_pending_display["name"].apply(format_last_first)

        df_rtm_pending_display = df_rtm_pending_display[["formatted_name", "emp_id", "formatted_date", "type"]]
        df_rtm_pending_display.columns = ["Name", "Employee ID", "Date", "Type"]

        st.dataframe(df_rtm_pending_display, hide_index=True, use_container_width=True)
    else:
        st.write("No records found.")

    # --- Section: Manager Level Approval (Pending Manager Approval) ---
    st.subheader("Manager Level Approval")
    if global_pending_requests:
        filtered_pending = []
        for r in global_pending_requests:
            if r.get("type") not in ["Wellness", "PTO"]:
                continue
            try:
                req_date = pd.to_datetime(r["date"])
            except Exception:
                continue
            if req_date.month == f_m and req_date.year == f_y:
                r_copy = dict(r)
                r_copy["emp_id"] = get_emp_id(r_copy)
                r_copy["status"] = r.get("status", "Pending")
                filtered_pending.append(r_copy)
    
        if filtered_pending:
            df_pending = pd.DataFrame(filtered_pending)
            df_pending["sort_date"] = pd.to_datetime(df_pending["date"])
            df_pending = df_pending.sort_values(by="sort_date", ascending=True)
    
            df_pending["formatted_date"] = df_pending["date"].apply(format_m_d_yyyy)
            df_pending["formatted_name"] = df_pending["name"].apply(format_last_first)
    
            df_pending_display = df_pending[["formatted_name", "emp_id", "formatted_date", "status"]].copy()
            df_pending_display.columns = ["Name", "Employee ID", "Date", "Status"]
    
            calculated_height = (len(df_pending_display) * 35) + 45
            st.dataframe(
                df_pending_display,
                hide_index=True,
                use_container_width=True,
                height=calculated_height,
            )
        else:
            st.info(
                f"ℹ️ No pending Wellness or PTO requests found for"
                f" {selected_month_name} {int(f_y)}."
            )
    else:
        st.write(
            "*No pending requests await administrator review authorization"
            " logs.*"
        )
    
    # --- Section: Rejected History ---
    st.subheader("Rejected Requests")

    all_rej_source = global_rejected_requests
    filtered_rej = []

    for r in all_rej_source:
        date_str = str(r.get("date", ""))
        try:
            parts = date_str.split("-")
            r_year = int(parts[0])
            r_month = int(parts[1])
            if r_month == f_m and r_year == f_y:
                filtered_rej.append(r)
        except (ValueError, IndexError):
            continue

    if filtered_rej:
        for req in filtered_rej:
            req["emp_id"] = get_emp_id(req)

        df_rej_display = pd.DataFrame(filtered_rej)
        df_rej_display["sort_date"] = pd.to_datetime(df_rej_display["date"])
        df_rej_display = df_rej_display.sort_values(by="sort_date", ascending=True)

        df_rej_display["formatted_date"] = df_rej_display["date"].apply(format_m_d_yyyy)
        df_rej_display["formatted_name"] = df_rej_display["name"].apply(format_last_first)

        df_rej_display = df_rej_display[["formatted_name", "emp_id", "formatted_date", "type"]]
        df_rej_display.columns = ["Name", "Employee ID", "Date", "Type"]
        st.dataframe(df_rej_display, hide_index=True, use_container_width=True)
    else:
        st.write("No records found.")
        
# --- TAB 3: ADMIN PANEL ---
with tab_adm:
    st.markdown(
        """
        <style>
        .small-font-container input, .small-font-container button, .small-font-container label, 
        .small-font-container div, .small-font-container span, .small-font-container p {
            font-size: 0.85rem !important;
        }
        .small-font-container h3 { font-size: 1.2rem !important; }
        .small-font-container h4 { font-size: 1.05rem !important; }
        .small-font-container h5 { font-size: 0.95rem !important; }
        </style>
    """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="small-font-container">', unsafe_allow_html=True)

    if not st.session_state.admin_authenticated:
        if (
            st.text_input(
                "Admin Password", type="password", key="a_pass_admin_tab"
            )
            == "Password1234"
        ):
            st.session_state.admin_authenticated = True
            st.rerun()
    else:
        st.subheader("🔑 System Administrator Workspace")
        pending_count = len(global_pending_requests)

        if pending_count > 0:
            st.info(
                f"⚠️ You have {pending_count} pending request(s) waiting in the"
                " queue below."
            )

        st.divider()

        col_left, space_gap, col_right = st.columns([2, 0.2, 3])

        with col_left:
            st.subheader("👥 Roster Management")
            roster = st.session_state.staff_roster
        
            grid_cols = st.columns([1.5, 2, 2, 2, 0.8, 0.8])
            grid_cols[0].write("**Emp ID**")
            grid_cols[1].write("**Name**")
            grid_cols[2].write("**Nickname**")
            grid_cols[3].write("**Birthday**")
            grid_cols[4].write("**Edit**")
            grid_cols[5].write("**Delete**")
        
            if roster:
                for name, data in roster.items():
                    r_cols = st.columns([1.5, 2, 2, 2, 0.8, 0.8])
                    r_cols[0].write(data.get("emp_id", "N/A"))
                    r_cols[1].write(name)
                    r_cols[2].write(data.get("nick", ""))
        
                    bday_val = data.get("bday")
                    if isinstance(bday_val, str):
                        try:
                            bday_val = datetime.strptime(
                                bday_val.split("T")[0], "%Y-%m-%d"
                            ).date()
                        except ValueError:
                            bday_val = date.today()
        
                    r_cols[3].write(
                        bday_val.strftime("%B %d")
                        if hasattr(bday_val, "strftime")
                        else str(bday_val)
                    )
        
                    if r_cols[4].button("✏️", key=f"edit_staff_{name}", help="Edit"):
                        st.session_state.new_staff_entries = [{
                            "emp_id": data.get("emp_id", ""),
                            "name": name,
                            "nick": data.get("nick", ""),
                            "bday": (
                                bday_val
                                if isinstance(bday_val, date)
                                else date.today()
                            ),
                            "rest_days": data.get("rest_days", []),
                        }]
                        st.rerun()
        
                    if r_cols[5].button("🗑️", key=f"del_staff_{name}", help="Remove"):
                        delete_staff(name)
                        st.rerun()
            else:
                st.write("*No staff members configured in the roster database.*")
        
            st.markdown("### ➕ Add / Edit Staff")
            if "new_staff_entries" not in st.session_state:
                st.session_state.new_staff_entries = [{
                    "emp_id": "",
                    "name": "",
                    "nick": "",
                    "bday": date.today(),
                    "rest_days": [],
                }]
        
            for idx, staff in enumerate(st.session_state.new_staff_entries):
                st.markdown(f"#### Staff Member #{idx + 1}")
                inner_c1, inner_c2 = st.columns(2)
                with inner_c1:
                    staff["emp_id"] = st.text_input(
                        "Employee ID",
                        value=staff.get("emp_id", ""),
                        key=f"multi_staff_empid_{idx}",
                    )
                    staff["name"] = st.text_input(
                        "Staff Name",
                        value=staff["name"],
                        key=f"multi_staff_name_{idx}",
                    )
                    staff["nick"] = st.text_input(
                        "Nickname",
                        value=staff["nick"],
                        key=f"multi_staff_nick_{idx}",
                    )
                with inner_c2:
                    staff["bday"] = st.date_input(
                        "Birthday",
                        value=staff["bday"],
                        min_value=date(1950, 1, 1),
                        key=f"multi_staff_bday_{idx}",
                    )
                    staff["rest_days"] = st.multiselect(
                        "Select Rest Days",
                        [
                            "Monday",
                            "Tuesday",
                            "Wednesday",
                            "Thursday",
                            "Friday",
                            "Saturday",
                            "Sunday",
                        ],
                        default=staff["rest_days"],
                        key=f"multi_staff_rest_{idx}",
                    )
        
            col_add, col_save = st.columns(2)
            with col_add:
                if st.button("➕ Add Row", key="btn_add_staff_row"):
                    st.session_state.new_staff_entries.append({
                        "emp_id": "",
                        "name": "",
                        "nick": "",
                        "bday": date.today(),
                        "rest_days": [],
                    })
                    st.rerun()
            with col_save:
                if st.button("💾 Save All Entries", key="btn_save_multi_staff"):
                    added_count = 0
                    for staff in st.session_state.new_staff_entries:
                        if not staff["name"]:
                            continue
                        bday_datetime = datetime(
                            staff["bday"].year,
                            staff["bday"].month,
                            staff["bday"].day,
                        )
                        save_staff(staff["name"], {
                            "emp_id": staff.get("emp_id", ""),
                            "bday": bday_datetime,
                            "nick": (
                                staff["nick"]
                                if staff["nick"]
                                else staff["name"]
                            ),
                            "rest_days": staff["rest_days"],
                        })
                        added_count += 1
        
                    st.success(
                        f"{added_count} staff record(s) saved successfully!"
                    )
                    st.session_state.new_staff_entries = [{
                        "emp_id": "",
                        "name": "",
                        "nick": "",
                        "bday": date.today(),
                        "rest_days": [],
                    }]
                    st.rerun()
        
            st.markdown("---")

            st.subheader("🗓️ Calendar Block Updates")
            config_mode = st.radio(
                "Target Scope Selection:",
                ["Single Date", "Date Range", "Full Month"],
                key="radio_cfg_mode",
            )

            if config_mode == "Single Date":
                target_date = st.date_input(
                    "Target Date Scope", value=date.today(), key="cfg_d"
                )
                target_dates = [target_date]
                lookup_date_str = str(target_date)
            elif config_mode == "Date Range":
                dr = st.date_input("Target Date Range", [], key="cfg_dr")
                target_dates = (
                    pd.date_range(dr[0], dr[1]).date if len(dr) == 2 else []
                )
                lookup_date_str = str(dr[0]) if len(dr) == 2 else str(date.today())
            else:
                sm = st.date_input(
                    "Target Operational Month Selector",
                    value=date.today(),
                    key="cfg_m",
                )
                target_dates = pd.date_range(
                    f"{sm.year}-{sm.month}-01", periods=31
                ).date
                target_dates = [d for d in target_dates if d.month == sm.month]
                lookup_date_str = str(date.today())

            if "limits" not in st.session_state:
                st.session_state.limits = {}

            target_key = str(
                st.session_state.get("selected_admin_date", lookup_date_str)
            )
            selected_config = st.session_state.calendar_data.get(target_key, {})

            st.session_state.limits["PTO_per_day"] = selected_config.get(
                "PTO_per_day", 1
            )
            st.session_state.limits["Wellness_per_day"] = selected_config.get(
                "Wellness_per_day", 1
            )

            st.session_state.limits["PTO_per_day"] = st.number_input(
                "Max Allowable PTO Allocations Per Day",
                min_value=1,
                value=st.session_state.limits.get("PTO_per_day", 1),
                key="num_max_pto_per_day",
            )
            st.session_state.limits["Wellness_per_day"] = st.number_input(
                "Max Allowable Wellness Allocations Per Day",
                min_value=1,
                value=st.session_state.limits.get("Wellness_per_day", 1),
                key="num_max_well_per_day",
            )

            start_t = st.time_input(
                "Shift Operational Start Window",
                value=time(9, 0),
                key="time_shift_start",
            )
            end_t = st.time_input(
                "Shift Operational End Window",
                value=time(18, 0),
                key="time_shift_end",
            )
            timezone = "PHT"

            shift_display = (
                f"{start_t.strftime('%I:%M %p')} -"
                f" {end_t.strftime('%I:%M %p')} {timezone}"
            )
            st.write(
                "Configured Shift String Representation:"
                f" **{shift_display}**"
            )
            setup = st.selectbox(
                "Site Production Status Profile",
                ["PROD - ONSITE", "PROD - WAH", "HOLIDAY"],
                key="sb_daily_status_setup",
            )

            safe_target_dates = (
                target_dates if isinstance(target_dates, (list, tuple)) else []
            )
            base_date = (
                safe_target_dates[0]
                if len(safe_target_dates) > 0
                else date.today()
            )
            unavailable = [
                r["name"]
                for r in global_approved_requests
                if str(r.get("date")) == str(base_date)
                and r.get("status") == "RTM_Approved"
            ]
            available = (
                [n for n in roster.keys() if n not in unavailable]
                if roster
                else []
            )

            team_manager = st.selectbox(
                "Team Manager", [":"] + available, key="sb_assign_team_manager"
            )
            call = st.multiselect("Call", available, key="ms_assign_call")
            chat = st.multiselect("Chat", available, key="ms_assign_chat")
            mfq = st.multiselect("MFQ", available, key="ms_assign_mfq")
            sme = st.multiselect("SME", available, key="ms_assign_sme")

            if st.button(
                "💾 Apply Configuration Profile To Dates",
                key="btn_save_daily_config",
            ):
                for d in target_dates:
                    st.session_state.calendar_data[d] = {
                        "shift": shift_display,
                        "status": setup,
                        "team_manager": [team_manager] if team_manager else [],
                        "call": call,
                        "chat": chat,
                        "mfq": mfq,
                        "sme": sme,
                        "PTO_per_day": st.session_state.limits["PTO_per_day"],
                        "Wellness_per_day": st.session_state.limits[
                            "Wellness_per_day"
                        ],
                    }
                serializable_data = {
                    str(k): v for k, v in st.session_state.calendar_data.items()
                }
                collection.update_one(
                    {"type": "calendar_data"},
                    {"$set": {"data": serializable_data}},
                    upsert=True,
                )
                fetch_calendar_doc.clear()
                st.success(
                    "Calendar timeline database parameters successfully"
                    " updated!"
                )
                st.rerun()

        with col_right:
            st.subheader("📥 Approval Center")
        
            def get_all_requests_dataframe(requests_list, select_all_values=False):
                filtered = [
                    r for r in requests_list if r.get("type") in ["Wellness", "PTO"]
                ]
                if not filtered:
                    return pd.DataFrame()
        
                data = {
                    "Select": [select_all_values] * len(filtered),
                    "Name": [r.get("name", "") for r in filtered],
                    "Employee ID": [get_emp_id(r) for r in filtered],
                    "Date": [r.get("date", "") for r in filtered],
                    "Type": [r.get("type", "") for r in filtered],
                    "Status": [r.get("status", "") for r in filtered],
                    "_id": [r.get("_id") for r in filtered],
                }
                df = pd.DataFrame(data)
                df.sort_values(by="Date", inplace=True)
                df.reset_index(drop=True, inplace=True)
                return df
        
            if "admin_msg" not in st.session_state:
                st.session_state.admin_msg = None
            if st.session_state.admin_msg:
                msg_type, msg_text = st.session_state.admin_msg
                if msg_type == "success":
                    st.success(msg_text)
                else:
                    st.warning(msg_text)
                if st.button(
                    "Clear Processing Session Prompt", key="clear_admin_notif"
                ):
                    st.session_state.admin_msg = None
                    st.rerun()
        
            select_all = st.checkbox(
                "Select All Pending Requests", key="global_select_all"
            )
        
            all_requests_df = get_all_requests_dataframe(
                global_pending_requests, select_all_values=select_all
            )
        
            if not all_requests_df.empty:
                calculated_height = max(150, min(800, (len(all_requests_df) * 35) + 40))
        
                edited_df = st.data_editor(
                    all_requests_df,
                    hide_index=True,
                    column_config={
                        "Select": st.column_config.CheckboxColumn(default=False),
                        "Name": st.column_config.TextColumn(disabled=False),
                        "Employee ID": st.column_config.TextColumn(disabled=True),
                        "Date": st.column_config.TextColumn(disabled=False),
                        "Type": st.column_config.SelectboxColumn(
                            options=["Wellness", "PTO", "SL/EL"], disabled=False
                        ),
                        "Status": st.column_config.SelectboxColumn(
                            options=["Pending", "RTM_Pending", "RTM_Approved", "Rejected"], disabled=False
                        ),
                        "_id": None,
                    },
                    use_container_width=True,
                    height=calculated_height,
                    key="editor_all_requests",
                )
            else:
                st.write("*No pending Wellness or PTO requests.*")
        
            if not all_requests_df.empty:
                btn_col1, btn_col2, btn_col3, btn_col4 = st.columns(4)
        
                def get_selected_ids(base_df, session_key):
                    selected_ids = []
                    current_select_states = base_df["Select"].tolist()
        
                    if (
                        session_key in st.session_state
                        and "edited_rows" in st.session_state[session_key]
                    ):
                        edits = st.session_state[session_key]["edited_rows"]
                        for row_idx, edit_dict in edits.items():
                            if "Select" in edit_dict:
                                current_select_states[int(row_idx)] = edit_dict["Select"]
        
                    for idx, is_selected in enumerate(current_select_states):
                        if is_selected:
                            selected_ids.append(base_df.iloc[idx]["_id"])
                    return selected_ids
        
                def process_df_edits(base_df, session_key):
                    if (
                        session_key in st.session_state
                        and "edited_rows" in st.session_state[session_key]
                    ):
                        edits = st.session_state[session_key]["edited_rows"]
                        for row_idx, edit_dict in edits.items():
                            target_id = base_df.iloc[int(row_idx)]["_id"]
                            update_fields = {
                                k.lower().replace(" ", "_"): v
                                for k, v in edit_dict.items()
                                if k != "Select"
                            }
                            if update_fields:
                                update_request_fields(target_id, update_fields)
        
                with btn_col1:
                    if st.button(
                        "✅ Approve Selected",
                        type="primary",
                        use_container_width=True,
                        key="btn_approve_pending_selected",
                    ):
                        process_df_edits(all_requests_df, "editor_all_requests")
                        target_ids = get_selected_ids(
                            all_requests_df, "editor_all_requests"
                        )
                        if target_ids:
                            bulk_update_requests(target_ids, "RTM_Pending")
                            st.session_state.admin_msg = (
                                "success",
                                f"Successfully approved {len(target_ids)} requests!",
                            )
                            st.rerun()
                        else:
                            st.warning("Please select at least one request to approve.")
            
                with btn_col2:
                    if st.button(
                        "❌ Deny Selected",
                        type="secondary",
                        use_container_width=True,
                        key="btn_deny_pending_selected",
                    ):
                        process_df_edits(all_requests_df, "editor_all_requests")
                        target_ids = get_selected_ids(
                            all_requests_df, "editor_all_requests"
                        )
                        if target_ids:
                            bulk_update_requests(target_ids, "Rejected")
                            st.session_state.admin_msg = (
                                "success",
                                f"Successfully denied {len(target_ids)} requests!",
                            )
                            st.rerun()
                        else:
                            st.warning("Please select at least one request to deny.")
            
                with btn_col3:
                    if st.button(
                        "💾 Save Edits",
                        use_container_width=True,
                        key="btn_save_pending_edits",
                    ):
                        process_df_edits(all_requests_df, "editor_all_requests")
                        st.session_state.admin_msg = (
                            "success",
                            "Pending request edits saved successfully!",
                        )
                        st.rerun()
            
                with btn_col4:
                    if st.button(
                        "🗑️ Delete Selected Pending",
                        use_container_width=True,
                        key="btn_delete_pending_selected",
                    ):
                        target_ids = get_selected_ids(
                            all_requests_df, "editor_all_requests"
                        )
                        if target_ids:
                            bulk_delete_requests(target_ids)
                            st.session_state.admin_msg = (
                                "success",
                                f"Successfully deleted {len(target_ids)} pending requests!",
                            )
                            st.rerun()
                        else:
                            st.warning(
                                "Please select at least one pending request to delete."
                            )
            st.markdown("---")
            
            filter_col1, filter_col2 = st.columns(2)
            with filter_col1:
                month_options = {
                    1: "January",
                    2: "February",
                    3: "March",
                    4: "April",
                    5: "May",
                    6: "June",
                    7: "July",
                    8: "August",
                    9: "September",
                    10: "October",
                    11: "November",
                    12: "December",
                }
                default_month = st.session_state.get("cal_m", date.today().month)
                selected_month = st.selectbox(
                    "Archive Filter Month",
                    options=list(month_options.keys()),
                    format_func=lambda x: month_options[x],
                    index=list(month_options.keys()).index(default_month),
                    key="history_filter_month",
                )
            with filter_col2:
                current_year = date.today().year
                year_options = list(range(current_year - 5, current_year + 6))
                selected_year = st.selectbox(
                    "Archive Filter Year",
                    options=year_options,
                    index=year_options.index(current_year),
                    key="history_filter_year",
                )
        
            roster_doc = collection.find_one({"type": "roster_list"})
            roster_data = roster_doc.get("data", {}) if roster_doc else {}
            roster_lookup = {
                name: details.get("emp_id", "N/A")
                for name, details in roster_data.items()
            }
        
            def get_emp_id(req):
                name = req.get("name", "")
                if name in roster_lookup and roster_lookup[name]:
                    return roster_lookup[name]
                return req.get("emp_id", "N/A")
        
            def format_last_first(full_name):
                if not full_name or not isinstance(full_name, str):
                    return ""
                parts = full_name.strip().split()
                if len(parts) > 1:
                    return f"{parts[-1]}, {' '.join(parts[:-1])}"
                return full_name
        
            # --- Section: RTM_Approved & Auto-Approved SL/EL ---
            st.subheader("RTM Approved")
            rtm_approved_list = []
            auto_sl_list = [r for r in global_approved_requests if r.get("type") == "SL/EL"]
            
            for r in global_rtm_processed_requests + auto_sl_list:
                if r.get("type") != "SL/EL" and r.get("rtm_status") != "RTM_Approved":
                    continue
                date_val = r.get("date")
                if isinstance(date_val, str):
                    try:
                        date_val = datetime.strptime(date_val.split("T")[0], "%Y-%m-%d").date()
                    except ValueError:
                        continue
                if date_val.month == selected_month and date_val.year == selected_year:
                    r_copy = r.copy()
                    r_copy["emp_id"] = get_emp_id(r_copy)
                    r_copy["rtm_status"] = r.get("rtm_status", r.get("status", "N/A"))
                    r_copy["formatted_date"] = format_m_d_yyyy(date_val) if 'format_m_d_yyyy' in globals() else date_val.strftime("%m/%d/%Y")
                    r_copy["formatted_name"] = format_last_first(r_copy["name"])
                    rtm_approved_list.append(r_copy)
            
            if rtm_approved_list:
                df_rtm_adm = pd.DataFrame(rtm_approved_list)
                df_rtm_adm = df_rtm_adm[["formatted_name", "emp_id", "formatted_date", "rtm_status"]]
                df_rtm_adm.columns = ["Name", "Employee ID", "Date", "RTM Status"]
                df_rtm_adm = df_rtm_adm.sort_values(by="Date", key=pd.to_datetime)
                st.dataframe(df_rtm_adm, hide_index=True, use_container_width=True)
            else:
                st.write("No records found.")
        
            # --- Section: RTM Verification & Approval Level ---
            st.subheader("🛡️ Pending RTM Approval")
        
            filtered_history_requests = []
            for r in global_approved_requests:
                date_val = r.get("date")
                if isinstance(date_val, str):
                    try:
                        date_val = datetime.strptime(
                            date_val.split("T")[0], "%Y-%m-%d"
                        ).date()
                    except ValueError:
                        continue
        
                if (
                    date_val.month == selected_month
                    and date_val.year == selected_year
                ):
                    if r.get("type") in ["Wellness", "PTO", "SL/EL"]:
                        r_copy = r.copy()
                        r_copy["parsed_date"] = date_val
                        r_copy["emp_id"] = get_emp_id(r_copy)
                        try:
                            r_copy["date"] = date_val.strftime("%-m/%-d/%Y")
                        except ValueError:
                            r_copy["date"] = date_val.strftime("%#m/%#d/%Y")
        
                        filtered_history_requests.append(r_copy)
        
            rtm_pending_adm = []
            for r in filtered_history_requests:
                if r.get("type") == "SL/EL" or r.get("status") != "RTM_Pending":
                    continue
                date_val = r.get("parsed_date")
                if not date_val:
                    continue
                r_copy = r.copy()
                r_copy["formatted_date"] = r.get("date")
                r_copy["formatted_name"] = format_last_first(r_copy["name"])
                rtm_pending_adm.append(r_copy)
        
            if rtm_pending_adm:
                df_rtm_adm_pending = pd.DataFrame(rtm_pending_adm)
                if "Select" not in df_rtm_adm_pending.columns:
                    df_rtm_adm_pending.insert(0, "Select", False)
        
                df_rtm_adm_pending = df_rtm_adm_pending[["Select", "formatted_name", "emp_id", "formatted_date", "type", "_id"]]
                df_rtm_adm_pending.columns = ["Select", "Name", "Employee ID", "Date", "Type", "_id"]
                
                edited_rtm_adm = st.data_editor(
                    df_rtm_adm_pending,
                    hide_index=True,
                    column_config={
                        "Select": st.column_config.CheckboxColumn(default=False),
                        "Name": st.column_config.TextColumn(disabled=True),
                        "Employee ID": st.column_config.TextColumn(disabled=True),
                        "Date": st.column_config.TextColumn(disabled=True),
                        "Type": st.column_config.TextColumn(disabled=True),
                        "_id": None,
                    },
                    use_container_width=True,
                    key="editor_rtm_adm_pending"
                )
        
                rtm_col1, rtm_col2, rtm_col3 = st.columns(3)
                
                def get_rtm_selected_ids(base_df, session_key):
                    selected = []
                    current_states = base_df["Select"].tolist()
                    if session_key in st.session_state and "edited_rows" in st.session_state[session_key]:
                        for r_idx, ed in st.session_state[session_key]["edited_rows"].items():
                            if "Select" in ed:
                                current_states[int(r_idx)] = ed["Select"]
                    for idx, sel in enumerate(current_states):
                        if sel:
                            selected.append(base_df.iloc[idx]["_id"])
                    return selected
        
                with rtm_col1:
                    if st.button("✅ Approve Selected RTM", key="btn_approve_rtm_selected"):
                        t_ids = get_rtm_selected_ids(df_rtm_adm_pending, "editor_rtm_adm_pending")
                        if t_ids:
                            bulk_update_rtm_status(t_ids, "RTM_Approved")
                            st.success("Successfully approved selected RTM requests!")
                            st.rerun()
                        else:
                            st.warning("Select at least one request.")
                with rtm_col2:
                    if st.button("❌ Reject Selected RTM", key="btn_reject_rtm_selected"):
                        t_ids = get_rtm_selected_ids(df_rtm_adm_pending, "editor_rtm_adm_pending")
                        if t_ids:
                            bulk_update_rtm_status(t_ids, "Rejected")
                            st.success("Successfully rejected selected RTM requests!")
                            st.rerun()
                        else:
                            st.warning("Select at least one request.")
                with rtm_col3:
                    if st.button("🗑️ Delete Selected RTM", key="btn_delete_rtm_selected"):
                        t_ids = get_rtm_selected_ids(df_rtm_adm_pending, "editor_rtm_adm_pending")
                        if t_ids:
                            bulk_delete_requests(t_ids)
                            st.success("Successfully deleted selected RTM requests!")
                            st.rerun()
                        else:
                            st.warning("Select at least one request.")
            else:
                st.write("No records found.")
        
            # --- 3. MANAGER LEVEL APPROVAL VIEW ---
            st.subheader("Manager Level Approval")
            
            current_pending_requests = fetch_pending_requests_from_db()
            filtered_manager_pending = [
                r for r in current_pending_requests if r.get("type") in ["Wellness", "PTO"]
            ]
            
            if filtered_manager_pending:
                manager_pending_data = []
                for r in filtered_manager_pending:
                    date_val = r.get("date")
                    try:
                        if isinstance(date_val, str):
                            parsed_dt = datetime.strptime(date_val.split("T")[0], "%Y-%m-%d").date()
                        else:
                            parsed_dt = pd.to_datetime(date_val).date()
                        formatted_date = format_m_d_yyyy(parsed_dt)
                    except Exception:
                        parsed_dt = date.today()
                        formatted_date = str(date_val)
                    
                    r_copy = r.copy()
                    r_copy["parsed_date"] = parsed_dt
                    r_copy["Employee ID"] = get_emp_id(r_copy)
                    r_copy["Date"] = formatted_date
                    r_copy["Name"] = format_last_first(r_copy.get("name", ""))
                    r_copy["Request Type"] = r_copy.get("type", "")
                    r_copy["Status"] = r_copy.get("status", "Pending")
                    manager_pending_data.append(r_copy)
            
                manager_df = pd.DataFrame(manager_pending_data)
                manager_df.sort_values(by="parsed_date", ascending=True, inplace=True)
                
                if "Select" not in manager_df.columns:
                    manager_df.insert(0, "Select", False)
            
                desired_order = ["Select", "Employee ID", "Date", "Name", "Request Type", "Status"]
                existing_cols = [c for c in desired_order if c in manager_df.columns]
                extra_cols = [c for c in manager_df.columns if c not in desired_order and c != "_id" and c != "parsed_date"]
                
                manager_display_df = manager_df[existing_cols + extra_cols + ["_id"]].copy()
                manager_height = (len(manager_display_df) * 35) + 45
            
                edited_manager_df = st.data_editor(
                    manager_display_df.drop(columns=["_id"]),
                    hide_index=True,
                    column_config={
                        "Select": st.column_config.CheckboxColumn(default=False),
                        "Employee ID": st.column_config.TextColumn(disabled=True),
                        "Date": st.column_config.TextColumn(disabled=False),
                        "Name": st.column_config.TextColumn(disabled=False),
                        "Request Type": st.column_config.SelectboxColumn(
                            options=["Wellness", "PTO"], disabled=False
                        ),
                        "Status": st.column_config.SelectboxColumn(
                            options=["Pending", "RTM_Pending", "Rejected"], disabled=False
                        ),
                    },
                    use_container_width=True,
                    height=manager_height,
                    key="editor_manager_level_approval",
                )
            
                mgr_col1, mgr_col2, mgr_col3 = st.columns(3)
                
                def get_manager_selected_ids(base_df, session_key):
                    selected = []
                    current_states = base_df["Select"].tolist()
                    if session_key in st.session_state and "edited_rows" in st.session_state[session_key]:
                        for r_idx, ed in st.session_state[session_key]["edited_rows"].items():
                            if "Select" in ed:
                                current_states[int(r_idx)] = ed["Select"]
                    for idx, sel in enumerate(current_states):
                        if sel:
                            selected.append(base_df.iloc[idx]["_id"])
                    return selected
            
                with mgr_col1:
                    if st.button("✅ Approve Selected", key="btn_approve_manager_selected", use_container_width=True):
                        target_ids = get_manager_selected_ids(manager_display_df, "editor_manager_level_approval")
                        if target_ids:
                            bulk_update_requests(target_ids, "RTM_Pending")
                            st.session_state.admin_msg = (
                                "success",
                                f"Successfully approved {len(target_ids)} requests! Sent to RTM Pending list.",
                            )
                            st.rerun()
                        else:
                            st.warning("Please select at least one request to approve.")
            
                with mgr_col2:
                    if st.button("❌ Reject Selected", key="btn_reject_manager_selected", use_container_width=True):
                        target_ids = get_manager_selected_ids(manager_display_df, "editor_manager_level_approval")
                        if target_ids:
                            bulk_update_requests(target_ids, "Rejected")
                            st.session_state.admin_msg = (
                                "success",
                                f"Successfully rejected {len(target_ids)} requests!",
                            )
                            st.rerun()
                        else:
                            st.warning("Please select at least one request to reject.")
            
                with mgr_col3:
                    if st.button("🗑️ Delete Selected", key="btn_delete_manager_selected", use_container_width=True):
                        target_ids = get_manager_selected_ids(manager_display_df, "editor_manager_level_approval")
                        if target_ids:
                            bulk_delete_requests(target_ids)
                            st.session_state.admin_msg = (
                                "success",
                                f"Successfully deleted {len(target_ids)} requests!",
                            )
                            st.rerun()
                        else:
                            st.warning("Please select at least one request to delete.")
            else:
                st.write("*No pending Wellness or PTO requests awaiting manager level approval.*")
        
            # --- 4. REJECTED HISTORY VIEW ---
            st.subheader("Rejected History")
        
            global_rejected_requests = fetch_rejected_requests_from_db()
            all_rejected_source = global_rejected_requests
            filtered_rejected_requests = []
        
            for r in all_rejected_source:
                date_val = r.get("date")
                if isinstance(date_val, str):
                    try:
                        date_val = datetime.strptime(
                            date_val.split("T")[0], "%Y-%m-%d"
                        ).date()
                    except ValueError:
                        continue
        
                if (
                    date_val.month == selected_month
                    and date_val.year == selected_year
                ):
                    if r.get("type") in ["Wellness", "PTO", "SL/EL"]:
                        r_copy = r.copy()
                        r_copy["parsed_date"] = date_val
                        r_copy["emp_id"] = get_emp_id(r_copy)
                        try:
                            r_copy["date"] = date_val.strftime("%-m/%-d/%Y")
                        except ValueError:
                            r_copy["date"] = date_val.strftime("%#m/%#d/%Y")
                        filtered_rejected_requests.append(r_copy)
        
            if filtered_rejected_requests:
                st.markdown("#### Rejected Requests Summary")
                rejected_df = pd.DataFrame(filtered_rejected_requests)
                rejected_df.sort_values(by="parsed_date", ascending=True, inplace=True)
        
                if "name" in rejected_df.columns:
                    rejected_df["name"] = rejected_df["name"].apply(format_last_first)
        
                if "type" in rejected_df.columns:
                    rejected_df.rename(columns={"type": "Request Type"}, inplace=True)
        
                rejected_df.rename(
                    columns={
                        "emp_id": "Employee ID",
                        "date": "Date",
                        "name": "Name",
                        "status": "Status",
                    },
                    inplace=True,
                )
        
                columns_to_drop = ["parsed_date", "email", "viewed"]
                rejected_display_df = rejected_df.drop(
                    columns=columns_to_drop, errors="ignore"
                )
        
                if "Select" not in rejected_display_df.columns:
                    rejected_display_df.insert(0, "Select", False)
        
                desired_order = [
                    "Select",
                    "Employee ID",
                    "Date",
                    "Name",
                    "Request Type",
                    "Status",
                ]
                existing_cols = [
                    c for c in desired_order if c in rejected_display_df.columns
                ]
                extra_cols = [
                    c for c in rejected_display_df.columns if c not in desired_order
                ]
        
                rejected_display_df = rejected_display_df[existing_cols + extra_cols]
                rejected_height = (len(rejected_display_df) * 35) + 45
        
                edited_rejected_df = st.data_editor(
                    rejected_display_df,
                    hide_index=True,
                    column_config={
                        "Select": st.column_config.CheckboxColumn(default=False),
                        "Employee ID": st.column_config.TextColumn(disabled=True),
                        "Date": st.column_config.TextColumn(disabled=False),
                        "Name": st.column_config.TextColumn(disabled=False),
                        "Request Type": st.column_config.SelectboxColumn(
                            options=["Wellness", "PTO", "SL/EL"], disabled=False
                        ),
                        "Status": st.column_config.SelectboxColumn(
                            options=["Approved", "Pending", "RTM_Pending", "RTM_Approved", "Rejected"], disabled=False
                        ),
                        "_id": None,
                    },
                    use_container_width=True,
                    height=rejected_height,
                    key="editor_rejected_requests",
                )
        
                rej_col1, rej_col2 = st.columns(2)
                with rej_col1:
                    if st.button("💾 Save Edit", key="btn_save_rejected_edits", use_container_width=True):
                        process_df_edits(rejected_display_df, "editor_rejected_requests")
                        st.session_state.admin_msg = (
                            "success",
                            "Rejected request edits saved successfully!",
                        )
                        st.rerun()
        
                with rej_col2:
                    if st.button("🗑️ Delete Selected", key="btn_delete_rejected", use_container_width=True):
                        selected_rejected_ids = []
                        if (
                            "editor_rejected_requests" in st.session_state
                            and "edited_rows"
                            in st.session_state["editor_rejected_requests"]
                        ):
                            edits = st.session_state["editor_rejected_requests"][
                                "edited_rows"
                            ]
                            current_states = rejected_display_df["Select"].tolist()
                            for r_idx, edit_dict in edits.items():
                                if "Select" in edit_dict:
                                    current_states[int(r_idx)] = edit_dict["Select"]
                            for idx, is_sel in enumerate(current_states):
                                if is_sel:
                                    selected_rejected_ids.append(
                                        rejected_display_df.iloc[idx]["_id"]
                                    )
                        else:
                            selected_rejected_ids = rejected_display_df[
                                rejected_display_df["Select"]
                            ]["_id"].tolist()
        
                        if selected_rejected_ids:
                            bulk_delete_requests(selected_rejected_ids)
                            st.session_state.admin_msg = (
                                "success",
                                f"Successfully deleted {len(selected_rejected_ids)} rejected requests!",
                            )
                            st.rerun()
                        else:
                            st.warning("Please tick at least one rejected entry to delete.")
            else:
                st.write("*No rejected requests found matching the selected month and year.*")
        
            st.markdown("</div>", unsafe_allow_html=True)
