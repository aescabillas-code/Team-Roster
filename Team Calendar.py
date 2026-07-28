import calendar
from datetime import datetime
from datetime import date, datetime, time, timedelta
import re
import altair as alt
import holidays
import pandas as pd
from pymongo import MongoClient
import pytz
import streamlit as st

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
                "status": "Approved",
            })
        )
    except Exception:
        return []


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


# --- DB MUTATION HELPERS ---
def calculate_duration_mins(start_str: str, end_str: str) -> int:
    """Calculates duration in minutes.

    If start time is greater than end time (e.g. Start 11:51, End 01:00), it
    subtracts 12 hours from the start time before calculating the difference.
    """
    if not start_str or not end_str:
        return 0

    fmt = "%H:%M"
    try:
        s_time = datetime.strptime(start_str.strip(), fmt)
        e_time = datetime.strptime(end_str.strip(), fmt)
    except ValueError:
        return 0

    s_mins = s_time.hour * 60 + s_time.minute
    e_mins = e_time.hour * 60 + e_time.minute

    # If start is bigger than end, subtract 12 hours (720 mins) from start time
    if s_mins > e_mins:
        s_mins -= 12 * 60

    duration = e_mins - s_mins
    return max(0, duration)
    
def clear_requests_cache():
    fetch_approved_requests_from_db.clear()
    fetch_pending_requests_from_db.clear()


def bulk_update_requests(request_ids, status):
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
    collection.update_one({"_id": req["_id"]}, {"$set": {"status": status}})
    clear_requests_cache()


def save_request_to_db(req, request_type):
    req["type"] = request_type
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

# --- NOTIFICATION BAR ---
if st.session_state.notifications:
    html_content = '<div class="alert-container"><div class="flash-red" style="margin-bottom: 10px;">⚠️ ATTENTION: New System Notifications Detected!</div>'
    for n in st.session_state.notifications:
        html_content += f'<div style="background-color: #fff3cd; padding: 10px; border-radius: 5px; margin: 5px 0; border-left: 5px solid #ffecb5; color: #856404;"><b>System Notice:</b> {n}</div>'
    html_content += "</div>"
    st.markdown(html_content, unsafe_allow_html=True)


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
            update_request_status_in_db(req, "Approved")
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
    "📈 Reports",
    "🔍 Case Tracker",
    "🔀 Deviation",
    "🔑 Admin",
]

tab_cal, tab_req, tab_prod, tab_case, tab_dev, tab_adm = st.tabs(tab_names)

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
                    for r in global_approved_requests
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
                        for r in global_approved_requests
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
                for r in global_approved_requests
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
    st.subheader("PTO / Wellness / SL Request Form")

    if "request_count" not in st.session_state:
        st.session_state.request_count = 1

    available_names = list(st.session_state.staff_roster.keys())

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
            st.session_state.request_count += 1
            st.rerun()

        if submit_triggered:
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
                    and r.get("status") in ["Pending", "Approved"]
                    for r in existing_requests
                )

                if is_already_requested:
                    st.warning(
                        f"⚠️ A request for {selected_name} on {req_date} already"
                        " exists."
                    )
                    continue

                if req_type == "SL/EL":
                    initial_status = "Approved"
                    new_req = {
                        "name": selected_name,
                        "date": date_str,
                        "type": req_type,
                        "status": initial_status,
                    }
                    save_request_to_db(new_req, req_type)
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
                            and r.get("status") in ["Pending", "Approved"]
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
                        running_caps[cap_key] += 1

            st.success(
                "All operational entries successfully verified and processed!"
            )
            st.session_state.request_count = 1
            st.rerun()

    st.subheader("Approved History")
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
    
    # 1. Fetch roster_list from database to map full name -> emp_id
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

    filtered_app = [
        r
        for r in global_approved_requests
        if int(r["date"].split("-")[1]) == f_m
        and int(r["date"].split("-")[0]) == f_y
    ]
    
    if filtered_app:
        # Populate emp_id directly from the database roster lookup
        for req in filtered_app:
            req["emp_id"] = get_emp_id(req)

        df_display = pd.DataFrame(filtered_app)
        # Sort by date
        df_display["sort_date"] = pd.to_datetime(df_display["date"])
        df_display = df_display.sort_values(by="sort_date", ascending=True)
    
        # Reformat date to M/D/YYYY
        df_display["formatted_date"] = df_display["date"].apply(format_m_d_yyyy)
    
        # Reformat name to "Last Name, First Name"
        df_display["formatted_name"] = df_display["name"].apply(format_last_first)
    
        df_display = df_display[["emp_id", "formatted_date", "formatted_name", "type"]]
        df_display.columns = ["Employee ID", "Date", "Name", "Type"]
        st.dataframe(df_display, hide_index=True, use_container_width=True)
    else:
        st.write("No records found.")
    
    st.subheader("📥 Pending Requests Overview")
    
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
                # Populate emp_id directly from database roster lookup
                r_copy = dict(r)
                r_copy["emp_id"] = get_emp_id(r_copy)
                filtered_pending.append(r_copy)
    
        if filtered_pending:
            df_pending = pd.DataFrame(filtered_pending)
            # Sort by date
            df_pending["sort_date"] = pd.to_datetime(df_pending["date"])
            df_pending = df_pending.sort_values(by="sort_date", ascending=True)
    
            # Reformat date to M/D/YYYY
            df_pending["formatted_date"] = df_pending["date"].apply(format_m_d_yyyy)
    
            # Reformat name to "Last Name, First Name"
            df_pending["formatted_name"] = df_pending["name"].apply(format_last_first)
    
            df_pending_display = df_pending[["emp_id", "formatted_date", "formatted_name", "type"]].copy()
            df_pending_display.columns = ["Employee ID", "Date", "Name", "Type"]
    
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
    
# --- TAB 3: PRODUCTIVITY MONITORING ---
with tab_prod:
    cases = get_cases_from_db()
    dev_data_all = fetch_deviations_from_db()

    if not cases:
        st.info("No case records found.")
    else:
        df = pd.DataFrame(cases)
        if "_id" in df.columns:
            df = df.drop(columns=["_id"])

        if "Date" not in df.columns and "Target Date" in df.columns:
            df["Date"] = df["Target Date"]
        elif "Date" in df.columns and "Target Date" in df.columns:
            df["Date"] = df["Date"].fillna(df["Target Date"])

        df["Date"] = pd.to_datetime(df["Date"].astype(str), errors="coerce")
        df = df.dropna(subset=["Date"])

        df["Month"] = df["Date"].dt.month
        df["Year"] = df["Date"].dt.year
        df["Day"] = df["Date"].dt.date
        df["Day_Str"] = df["Date"].dt.strftime("%Y-%m-%d")

        type_col = (
            "Type"
            if "Type" in df.columns
            else ("Contact Type" if "Contact Type" in df.columns else None)
        )

        st.markdown("## 🗓️ Monthly Breakdown")

        col_y, col_m = st.columns(2)
        years = sorted(df["Year"].dropna().unique())

        selected_year = col_y.selectbox(
            "Year",
            years if years else [date.today().year],
            key="prod_year",
        )
        selected_month = col_m.selectbox(
            "Month",
            range(1, 13),
            format_func=lambda x: calendar.month_name[x],
            index=date.today().month - 1,
            key="prod_monitor_month",
        )

        monthly_df = df[
            (df["Year"] == selected_year) & (df["Month"] == selected_month)
        ]

        dev_df_m = pd.DataFrame()
        if dev_data_all:
            dev_df_all = pd.DataFrame(dev_data_all)
            dev_df_all["ParsedDate"] = pd.to_datetime(
                dev_df_all["Date"], errors="coerce"
            )
            dev_df_all = dev_df_all.dropna(subset=["ParsedDate"])

            dev_df_m = dev_df_all[
                (dev_df_all["ParsedDate"].dt.year == selected_year)
                & (dev_df_all["ParsedDate"].dt.month == selected_month)
                & (dev_df_all["Name"] != "Jeff Bote")
            ]

        # Filter strictly for audited cases
        if "QA_Audited" in monthly_df.columns:
            audited_df = monthly_df[
                monthly_df["QA_Audited"].isin([True, "True", "true", 1])
            ].copy()
        else:
            audited_df = pd.DataFrame()

        st.markdown("## 📈 Quality Analysis")
        if not audited_df.empty:
            st.markdown(
                "### ⚠️ Most Common QA Error & Defect Analysis (Audited Cases"
                " Only)"
            )
            qa_criteria_map = {
                "QA_SLO_SLA": "SLO / SLA Adherence",
                "QA_Initial_Consecutive_Resp": (
                    "Initial & Consecutive Responses"
                ),
                "QA_Case_Status_Update": "Timely Case Status Update",
                "QA_Issue_Field_Updated": "Issue Field Documentation",
                "QA_Case_Comments_Probing": (
                    "Probing Questions & Case Comments (🚨)"
                ),
                "QA_Collaborations_Logging": (
                    "Collaborations / Communication Logging (🚨)"
                ),
                "QA_Entitlement_Validation": (
                    "Entitlement Validation Process (🚨)"
                ),
                "QA_Account_Validation": "Account Validation Process",
                "QA_Case_Routing": "Private Case Routing / Escalation (🚨)",
            }

            error_counts = {}
            total_audited = len(audited_df)
            for col, label in qa_criteria_map.items():
                if col in audited_df.columns:
                    not_met_count = (audited_df[col] == "Not Met").sum()
                    error_counts[label] = not_met_count

            error_df = pd.DataFrame(
                list(error_counts.items()), columns=["Criterion", "DefectCount"]
            )
            error_df["ErrorRate"] = (
                (error_df["DefectCount"] / total_audited) * 100
            ).round(1)
            error_df = error_df.sort_values(by="DefectCount", ascending=False)

            table_df = error_df.rename(
                columns={
                    "Criterion": "QA Requirement / Criterion",
                    "DefectCount": "Defect Count ('Not Met')",
                    "ErrorRate": "Error Rate (%)",
                }
            )

            err_col1, gap, err_col2 = st.columns([1, 0.2, 1])
            with err_col1:
                st.markdown(
                    "**Defect Breakdown Table** *(Total Audited:"
                    f" {total_audited})*"
                )
                st.dataframe(table_df, use_container_width=True, hide_index=True)

            with err_col2:
                st.markdown("**Defect Distribution Visual**")
                if error_df["DefectCount"].sum() > 0:
                    err_chart = (
                        alt.Chart(error_df)
                        .mark_bar(color="#ea4335")
                        .encode(
                            x=alt.X("DefectCount:Q", title="Total Defect Count"),
                            y=alt.Y(
                                "Criterion:N", sort="-x", title="QA Criterion"
                            ),
                            tooltip=["Criterion", "DefectCount", "ErrorRate"],
                        )
                    )
                    st.altair_chart(err_chart, use_container_width=True)
                else:
                    st.success(
                        "🎉 No QA defect errors recorded across audited cases"
                        " in this timeframe!"
                    )
        else:
            st.info(
                "No audited cases found for QA evaluation in the selected"
                " month."
            )

        st.divider()

        st.header("📈 Utilization Monitoring & Operational Analysis")
        st.markdown("### 📦 Cases Count")
        if not monthly_df.empty:
            if type_col:
                monthly_summary = (
                    monthly_df.groupby(["Owner", type_col])
                    .size()
                    .unstack(fill_value=0)
                )
            else:
                monthly_summary = (
                    monthly_df.groupby("Owner")
                    .size()
                    .to_frame(name="Total Cases")
                )

            monthly_summary["Total Cases"] = (
                monthly_summary.sum(axis=1) if type_col else monthly_summary["Total Cases"]
            )
            monthly_summary = monthly_summary.sort_values(
                by="Total Cases", ascending=False
            )

            m_height = min(1000, max(100, len(monthly_summary) * 35 + 38))
            st.dataframe(
                monthly_summary.reset_index(),
                use_container_width=True,
                height=m_height,
                hide_index=True,
            )
        else:
            st.info("No cases found for selected month.")

        st.markdown("### 🔀 Deviations Count")
        if not dev_df_m.empty:
            m_dev_summary = (
                dev_df_m.groupby(["Name"])
                .size()
                .reset_index(name="Total Deviations")
                .sort_values(by="Total Deviations", ascending=False)
            )
            st.dataframe(
                m_dev_summary, use_container_width=True, hide_index=True
            )
        else:
            st.info("No deviation entries found for selected month.")

        st.markdown("## 📈 Daily Utilization & Deviation Trends")

        daily_owner_prod = (
            monthly_df.groupby(["Day_Str", "Owner"])
            .size()
            .reset_index(name="Case Count")
        )

        daily_dev_trend = pd.DataFrame()
        if not dev_df_m.empty:
            dev_chart_df = dev_df_m.copy()
            dev_chart_df["Date_Str"] = dev_chart_df["ParsedDate"].dt.strftime(
                "%Y-%m-%d"
            )
            daily_dev_trend = (
                dev_chart_df.groupby(["Date_Str", "Name"])
                .size()
                .reset_index(name="Deviation Count")
            )

        all_owners = (
            sorted(daily_owner_prod["Owner"].unique().tolist())
            if not daily_owner_prod.empty
            else []
        )
        selected_chart_owner = st.selectbox(
            "Filter Daily Charts by Case Owner / Employee",
            ["All Owners"] + all_owners,
            key="tab3_owner_filter",
        )

        if selected_chart_owner != "All Owners":
            filtered_prod = (
                daily_owner_prod[daily_owner_prod["Owner"] == selected_chart_owner]
                if not daily_owner_prod.empty
                else daily_owner_prod
            )
            filtered_dev = (
                daily_dev_trend[daily_dev_trend["Name"] == selected_chart_owner]
                if not daily_dev_trend.empty
                else daily_dev_trend
            )
        else:
            filtered_prod = daily_owner_prod
            filtered_dev = daily_dev_trend

        st.markdown("### 📈 Daily Utilization")
        if not filtered_prod.empty:
            prod_line_chart = (
                alt.Chart(filtered_prod)
                .mark_line(point=True)
                .encode(
                    x=alt.X(
                        "Day_Str:N",
                        title="Date",
                        axis=alt.Axis(labelAngle=-45),
                    ),
                    y=alt.Y("Case Count:Q", title="Total Cases Handled"),
                    color=alt.Color("Owner:N", title="Case Owner"),
                    tooltip=[
                        alt.Tooltip("Day_Str:N", title="Date"),
                        alt.Tooltip("Owner:N", title="Owner"),
                        alt.Tooltip("Case Count:Q", title="Cases Handled"),
                    ],
                )
                .interactive()
            )
            st.altair_chart(prod_line_chart, use_container_width=True)
        else:
            st.info(
                "No utilization chart data available for current selection."
            )

        st.markdown("### 🔀 Daily Deviation")
        if not filtered_dev.empty:
            dev_line_chart = (
                alt.Chart(filtered_dev)
                .mark_line(point=True)
                .encode(
                    x=alt.X(
                        "Date_Str:N",
                        title="Date",
                        axis=alt.Axis(labelAngle=-45),
                    ),
                    y=alt.Y("Deviation Count:Q", title="Total Deviations"),
                    color=alt.Color("Name:N", title="Employee"),
                    tooltip=[
                        alt.Tooltip("Date_Str:N", title="Date"),
                        alt.Tooltip("Name:N", title="Employee"),
                        alt.Tooltip("Deviation Count:Q", title="Deviations"),
                    ],
                )
                .interactive()
            )
            st.altair_chart(dev_line_chart, use_container_width=True)
        else:
            st.info("No deviation trend data available for current selection.")

        st.markdown(
            "## 📊 Operational Analysis: Utilization vs. Deviations"
        )

        total_monthly_prod_count = (
            daily_owner_prod["Case Count"].sum()
            if not daily_owner_prod.empty
            else 0
        )

        total_monthly_dev_count = 0
        global_daily_dev = pd.DataFrame()
        if not dev_df_m.empty:
            dev_global_df = dev_df_m.copy()
            dev_global_df["Date_Str"] = dev_global_df["ParsedDate"].dt.strftime(
                "%Y-%m-%d"
            )
            global_daily_dev = (
                dev_global_df.groupby(["Date_Str", "Name"])
                .size()
                .reset_index(name="Deviation Count")
            )
            total_monthly_dev_count = global_daily_dev["Deviation Count"].sum()

        global_merged_metrics = pd.DataFrame()
        if not daily_owner_prod.empty and not global_daily_dev.empty:
            global_merged_metrics = pd.merge(
                daily_owner_prod,
                global_daily_dev,
                left_on=["Day_Str", "Owner"],
                right_on=["Date_Str", "Name"],
                how="inner",
            )

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric(
                label="Total Productivity Logs",
                value=f"{total_monthly_prod_count:,}",
            )
        with col2:
            st.metric(
                label="Total Deviations Logged",
                value=f"{total_monthly_dev_count:,}",
            )
        with col3:
            if len(global_merged_metrics) > 2:
                corr_val = global_merged_metrics["Case Count"].corr(
                    global_merged_metrics["Deviation Count"]
                )
                st.metric(
                    label="Correlation Coefficient",
                    value=f"{corr_val:.2f}",
                    help=(
                        "Values close to -1 indicate high deviations lower"
                        " output. Values close to +1 indicate parallel"
                        " increases."
                    ),
                )
            else:
                st.metric(label="Correlation Coefficient", value="N/A")

        st.markdown("### 📞 Contact / Case Type Operational Analysis")
        if type_col and type_col in monthly_df.columns and not monthly_df.empty:
            type_counts = monthly_df[type_col].value_counts().reset_index()
            type_counts.columns = ["Contact Type", "Total Volume"]

            total_monthly_cases = type_counts["Total Volume"].sum()
            type_counts["Volume Share (%)"] = (
                (type_counts["Total Volume"] / total_monthly_cases) * 100
            ).round(1).astype(str) + "%"

            col_t1, col_t2 = st.columns([1, 1])

            with col_t1:
                st.markdown("**Distribution Table**")
                st.dataframe(
                    type_counts, use_container_width=True, hide_index=True
                )

            with col_t2:
                st.markdown("**Volume Share Visual**")
                type_chart = (
                    alt.Chart(type_counts)
                    .mark_bar()
                    .encode(
                        x=alt.X("Total Volume:Q", title="Total Cases"),
                        y=alt.Y(
                            "Contact Type:N", sort="-x", title="Contact Type"
                        ),
                        color=alt.Color("Contact Type:N", legend=None),
                        tooltip=[
                            "Contact Type",
                            "Total Volume",
                            "Volume Share (%)",
                        ],
                    )
                )
                st.altair_chart(type_chart, use_container_width=True)
        else:
            st.info(
                "No specific contact/case type column found for deeper contact"
                " analysis."
            )

        st.markdown(
            "## 👤 Individual Performance Analysis & Profile Categories"
        )

        active_roster_names = sorted(
            list(
                set(
                    df["Owner"].dropna().tolist()
                    + list(st.session_state.staff_roster.keys())
                )
            )
        )

        person_cases = (
            monthly_df.groupby("Owner").size().to_dict()
            if not monthly_df.empty
            else {}
        )
        person_devs = (
            dev_df_m.groupby("Name").size().to_dict()
            if not dev_df_m.empty
            else {}
        )

        avg_cases = (
            (sum(person_cases.values()) / len(person_cases))
            if person_cases
            else 0
        )
        avg_devs = (
            (sum(person_devs.values()) / len(person_devs)) if person_devs else 0
        )

        profile_analysis_rows = []

        for emp_name in active_roster_names:
            c_count = person_cases.get(emp_name, 0)
            d_count = person_devs.get(emp_name, 0)

            if c_count == 0 and d_count == 0:
                continue

            if c_count >= avg_cases and d_count <= avg_devs:
                cat = "High Performers"
                diag = (
                    "High output with low off-queue deviations. Strong"
                    " adherence."
                )
                action = "Benchmark for operational best practices."
            elif c_count >= avg_cases and d_count > avg_devs:
                cat = "Complex Processors"
                diag = (
                    "High case effort with elevated deviation/consultation"
                    " time."
                )
                action = "Review AUX reason codes & SME consultation time."
            elif c_count < avg_cases and d_count > avg_devs:
                cat = "Adherence At-Risk"
                diag = (
                    "Frequent off-queue time directly lowering total output."
                )
                action = "Schedule targeted schedule adherence coaching."
            else:
                cat = "Under-Reporting"
                diag = (
                    "Low case output despite low logged offline/deviation time."
                )
                action = "Inspect active floor work habits & idle time."

            profile_analysis_rows.append({
                "Employee Name": emp_name,
                "Total Cases": c_count,
                "Total Deviations": d_count,
                "Profile Category": cat,
                "Operational Diagnosis": diag,
                "Recommended Action": action,
            })

        if profile_analysis_rows:
            profile_df = pd.DataFrame(profile_analysis_rows).sort_values(
                by="Total Cases", ascending=False
            )
            p_height = min(1000, max(120, len(profile_df) * 38 + 38))
            st.dataframe(
                profile_df,
                use_container_width=True,
                height=p_height,
                hide_index=True,
            )
        else:
            st.info(
                "No employee activity recorded for the selected month to"
                " generate individual performance profiles."
            )

        with st.expander(
            "🔍 Deep-Dive Operational Insights & Correlation Models",
            expanded=True,
        ):
            st.markdown("""
            ### 1. Operational Relationship Framework
            Understanding how work throughput (cases processed) intersects with queue deviations (AUX time, offline activity, unscheduled breaks):

            * **Inverse Correlation Curve (Unplanned System / Adherence Anomalies):**
              * **Pattern:** Days with spikes in total deviation counts show a proportional decline in total cases completed.
              * **Drivers:** System outages, unannounced tool slowness, or non-adherence to scheduled shifts.
            
            * **Direct Correlation Curve (Complex Escalations & Mentorship):**
              * **Pattern:** Days where complex cases spike lead to simultaneously high recorded case effort and increased off-queue deviation time.
              * **Drivers:** Required SME consultations, QA syncs, multi-system research, or coaching sessions required to complete difficult cases.

            ### 2. Employee Efficiency Profile Matrix Framework
            """)

            matrix_data = {
                "Profile Category": [
                    "High Performers",
                    "Complex Processors",
                    "Adherence At-Risk",
                    "Under-Reporting",
                ],
                "Output": ["High", "High/Medium", "Low", "Low"],
                "Deviation Frequency": ["Low", "High", "High", "Low"],
                "Operational Diagnosis": [
                    "Optimal floor engagement and adherence.",
                    "Handling difficult escalations requiring offline effort.",
                    "Frequent off-queue activity directly impacting output.",
                    "Low output despite no logged offline time.",
                ],
                "Recommended Action": [
                    "Benchmark for team best practices.",
                    "Review AUX reason codes & SME time.",
                    "Schedule adherence coaching.",
                    "Inspect active work queue habits and idle time.",
                ],
            }
            st.dataframe(
                pd.DataFrame(matrix_data),
                use_container_width=True,
                hide_index=True,
            )

            st.markdown("""
            > **Operational Takeaway:** Monitor cases with high deviation counts to distinguish between **healthy process deviations** (coaching, complex research) and **unplanned friction** (tool outages, adherence loss).
            """)

# --- TAB 4: CASE TRACKER ---
with tab_case:
    st.subheader("📝 Bulk Log New Cases")
    cases_list = get_cases_from_db()

    masterfile_doc = fetch_masterfile_doc()
    if masterfile_doc and "data" in masterfile_doc:
        master_df = pd.DataFrame(masterfile_doc["data"])
    else:
        master_df = pd.DataFrame(
            {"Category": ["Contact Type"], "Values": ["Call,Chat,Email"]}
        )

    c_types = (
        master_df.loc[master_df["Category"] == "Contact Type", "Values"]
        .iloc[0]
        .split(",")
    )

    owner_list = sorted(list(st.session_state.staff_roster.keys()))
    if not owner_list:
        owner_list = ["Unknown"]

    g_col1, g_col2, g_col3 = st.columns(3)
    with g_col1:
        global_target_date = st.date_input(
            "Global Target Date",
            value=date.today(),
            key="case_global_target_date",
        )
    with g_col2:
        global_c_type = st.selectbox(
            "Global Contact Type", c_types, key="case_global_type"
        )
    with g_col3:
        global_owner = st.selectbox(
            "Global Case Owner", owner_list, key="case_global_owner"
        )

    st.markdown("### 📊 Case Entry")

    if (
        "batch_case_entries" not in st.session_state
        or len(st.session_state.batch_case_entries) == 0
    ):
        st.session_state.batch_case_entries = [
            {"case_number": ""} for _ in range(5)
        ]

    total_slots = len(st.session_state.batch_case_entries)
    for row_idx in range(0, total_slots, 5):
        cols = st.columns(5)
        for col_idx in range(5):
            entry_idx = row_idx + col_idx
            if entry_idx < total_slots:
                with cols[col_idx]:
                    val = st.text_input(
                        f"Case #{entry_idx + 1}",
                        value=st.session_state.batch_case_entries[entry_idx][
                            "case_number"
                        ],
                        key=f"grid_case_num_{entry_idx}",
                    )
                    st.session_state.batch_case_entries[entry_idx][
                        "case_number"
                    ] = val

    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 2, 4])
    with ctrl_col1:
        if st.button("➕ Add Row (+1 Slot)", key="btn_add_matrix_row"):
            st.session_state.batch_case_entries.append({"case_number": ""})
            st.rerun()
    with ctrl_col2:
        if st.button("🗑️ Remove Last Slot", key="btn_remove_matrix_row"):
            if len(st.session_state.batch_case_entries) > 1:
                st.session_state.batch_case_entries.pop()
                st.rerun()
            else:
                st.warning(
                    "Cannot remove slot. Minimum of 1 entry slot required."
                )
    with ctrl_col3:
        if st.button("💾 Submit All Cases", key="btn_save_batch_cases"):
            cases_saved = 0
            for entry in st.session_state.batch_case_entries:
                c_num = entry.get("case_number", "").strip()
                if not c_num:
                    continue
                new_case = {
                    "Date": str(global_target_date),
                    "Target Date": str(global_target_date),
                    "Owner": global_owner,
                    "Type": global_c_type,
                    "Case Number": c_num,
                    "QA_SLO_SLA": "Met",
                    "QA_Initial_Consecutive_Resp": "Met",
                    "QA_Case_Status_Update": "Met",
                    "QA_Issue_Field_Updated": "Met",
                    "QA_Case_Comments_Probing": "Met",
                    "QA_Collaborations_Logging": "Met",
                    "QA_Entitlement_Validation": "Met",
                    "QA_Account_Validation": "Met",
                    "QA_Case_Routing": "Met",
                    "QA_Score": None,
                    "QA_Audited": False,
                    "QA_Feedback": "",
                }
                save_case_to_db(new_case)
                cases_saved += 1

            if cases_saved > 0:
                st.success(
                    f"Batch execution complete! {cases_saved} cases recorded."
                )
            else:
                st.warning(
                    "No cases recorded. Please enter at least one valid case"
                    " number."
                )
            st.session_state.batch_case_entries = [
                {"case_number": ""} for _ in range(5)
            ]
            st.rerun()

    st.divider()
    st.subheader("📚 Cases")

    if cases_list:
        df_cases = pd.DataFrame(cases_list)
        if "_id" in df_cases.columns:
            df_cases["_id"] = df_cases["_id"].astype(str)

        dl_col1, dl_col2 = st.columns(2)

        with dl_col1:
            kb_cols = [
                c
                for c in ["Case Number", "Owner", "Target Date", "Type"]
                if c in df_cases.columns
            ]
            df_kb = df_cases[kb_cols] if kb_cols else df_cases
            csv_kb = df_kb.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Download Cases CSV",
                csv_kb,
                "kb_export.csv",
                "text/csv",
                key="dl_kb_csv",
            )

        with dl_col2:
            qa_cols = [
                "Case Number",
                "Owner",
                "Target Date",
                "Type",
                "QA_Score",
                "QA_Audited",
                "QA_Feedback",
                "QA_SLO_SLA",
                "QA_Initial_Consecutive_Resp",
                "QA_Case_Status_Update",
                "QA_Issue_Field_Updated",
                "QA_Case_Comments_Probing",
                "QA_Collaborations_Logging",
                "QA_Entitlement_Validation",
                "QA_Account_Validation",
                "QA_Case_Routing",
            ]
            available_qa_cols = [
                col for col in qa_cols if col in df_cases.columns
            ]
            df_qa = df_cases[available_qa_cols] if available_qa_cols else df_cases
            
            # Filter to only include audited records
            if "QA_Audited" in df_qa.columns:
                df_qa = df_qa[df_qa["QA_Audited"] == True]

            csv_qa = df_qa.to_csv(index=False).encode("utf-8")
            st.download_button(
                "🎯 Download QA Audit Report CSV",
                csv_qa,
                "qa_audit_report.csv",
                "text/csv",
                key="dl_qa_csv",
            )

    with st.expander("🔍 Filter Options", expanded=True):
        f1, f2, f3 = st.columns(3)
        f_case = f1.text_input("Filter by Case #", key="case_filter_num")
        owners = sorted(
            list(
                set(
                    case.get("Owner", "")
                    for case in cases_list
                    if case.get("Owner")
                )
            )
        )
        f_owner = f2.selectbox(
            "Filter by Owner", ["All"] + owners, key="case_filter_owner"
        )
        # Defaulting "Filter by Audit Status" to "Audited" (index 1)
        f_audit_status = f3.selectbox(
            "Filter by Audit Status",
            ["All", "Audited", "Not Audited"],
            index=1,
            key="case_filter_audit_status",
        )
        
        d_col1, d_col2, d_col3 = st.columns([2, 2, 2])
        filter_date_mode = d_col1.selectbox(
            "Filter Date By",
            ["All Time", "Specific Date", "Month & Year"],
            key="case_filter_date_mode",
        )

        f_specific_date = None
        f_month = None
        f_year = None

        if filter_date_mode == "Specific Date":
            f_specific_date = d_col2.date_input(
                "Select Date", value=date.today(), key="case_filter_spec_date"
            )
        elif filter_date_mode == "Month & Year":
            f_month = d_col2.selectbox(
                "Month",
                options=range(1, 13),
                index=date.today().month - 1,
                format_func=lambda x: calendar.month_name[x],
                key="case_filter_month",
            )
            f_year = d_col3.number_input(
                "Year", value=date.today().year, step=1, key="case_filter_year"
            )

    filtered_cases = []
    for case in reversed(cases_list):
        matches_case = not f_case or f_case.lower() in str(
            case.get("Case Number", "")
        ).lower()
        matches_owner = f_owner == "All" or case.get("Owner", "") == f_owner

        is_case_audited = case.get("QA_Audited", False)
        if f_audit_status == "Audited":
            matches_audit = is_case_audited is True
        elif f_audit_status == "Not Audited":
            matches_audit = is_case_audited is False
        else:
            matches_audit = True

        matches_date = True
        raw_date_str = case.get("Target Date") or case.get("Date", "")

        if filter_date_mode != "All Time" and raw_date_str:
            try:
                c_date = pd.to_datetime(raw_date_str).date()
                if filter_date_mode == "Specific Date":
                    matches_date = c_date == f_specific_date
                elif filter_date_mode == "Month & Year":
                    matches_date = (
                        c_date.month == f_month and c_date.year == f_year
                    )
            except Exception:
                matches_date = False

        if matches_case and matches_owner and matches_audit and matches_date:
            filtered_cases.append(case)

    if filtered_cases:
        items_per_page = 10
        total_case_pages = max(
            1, (len(filtered_cases) + items_per_page - 1) // items_per_page
        )

        p_col1, p_col2 = st.columns([1, 4])
        with p_col1:
            case_page = st.number_input(
                "Page",
                min_value=1,
                max_value=total_case_pages,
                value=1,
                step=1,
                key="case_page_num",
            )
        with p_col2:
            st.write(
                f"Showing page **{case_page}** of **{total_case_pages}**"
                f" ({len(filtered_cases)} total matching cases)"
            )

        start_idx = (case_page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        paginated_cases = filtered_cases[start_idx:end_idx]

        for case in paginated_cases:
            entry_col, gap, action_col = st.columns([3.5, 0.1, 1.4])
            has_qa_fb = bool(str(case.get("QA_Feedback", "")).strip())
            is_audited = case.get("QA_Audited", False)

            qa_score = case.get("QA_Score", None)
            is_passed = (qa_score == 9) if qa_score is not None else False

            if is_audited:
                box_class = "qa-box-passed" if is_passed else "qa-box-failed"
            else:
                box_class = ""

            with entry_col:
                if is_audited:
                    if not is_passed:
                        expander_label = (
                            "🚨 RED ALERT | Case"
                            f" #{case.get('Case Number','')} (Failed Audit)"
                        )
                    else:
                        expander_label = (
                            f"✅ PASSED | Case #{case.get('Case Number','')}"
                        )
                else:
                    expander_label = f"Case #{case.get('Case Number','')}"

                st.markdown(
                    f'<div class="{box_class}">', unsafe_allow_html=True
                )

                with st.expander(
                    expander_label,
                    expanded=False,
                ):
                    score_display = (
                        f"`{qa_score} / 9` ({'PASSED' if is_passed else 'FAILED'})"
                        if (is_audited and qa_score is not None)
                        else "`Not Audited`"
                    )

                    st.markdown(f"""
                        **Owner:** {case.get('Owner','')}  
                        **Target Date:** {case.get('Target Date', str(date.today()))}  
                        **Contact Type:** {case.get('Type','')}  
                        **Case Number:** {case.get('Case Number','')}  
                        **QA Score:** {score_display}
                        """)

                    # TABLE VIEW FOR AUDITED QA SCORECARD RESULTS
                    if is_audited:
                        st.markdown("#### 📋 QA Audit Evaluation Summary")
                        scorecard_data = [
                            {"Category": "1️⃣ Timely Engagement", "Criterion": "SLO / SLA", "Type": "Standard", "Status": case.get("QA_SLO_SLA", "Met")},
                            {"Category": "1️⃣ Timely Engagement", "Criterion": "Initial & Consecutive Responses", "Type": "Standard", "Status": case.get("QA_Initial_Consecutive_Resp", "Met")},
                            {"Category": "1️⃣ Timely Engagement", "Criterion": "Case Status Update", "Type": "Standard", "Status": case.get("QA_Case_Status_Update", "Met")},
                            {"Category": "2️⃣ Documentations", "Criterion": "Issue Field Description/Freq/Start Date", "Type": "Standard", "Status": case.get("QA_Issue_Field_Updated", "Met")},
                            {"Category": "2️⃣ Documentations", "Criterion": "Comments with Probing Q&A", "Type": "🚨 Non-negotiable", "Status": case.get("QA_Case_Comments_Probing", "Met")},
                            {"Category": "2️⃣ Documentations", "Criterion": "Collaborations / Logging", "Type": "🚨 Non-negotiable", "Status": case.get("QA_Collaborations_Logging", "Met")},
                            {"Category": "3️⃣ Validation Process", "Criterion": "Entitlement Validation", "Type": "🚨 Non-negotiable", "Status": case.get("QA_Entitlement_Validation", "Met")},
                            {"Category": "3️⃣ Validation Process", "Criterion": "Account Validation Process", "Type": "Standard", "Status": case.get("QA_Account_Validation", "Met")},
                            {"Category": "4️⃣ Process and Policy", "Criterion": "UVA, SDI, Private Case Routing", "Type": "🚨 Non-negotiable", "Status": case.get("QA_Case_Routing", "Met")},
                        ]
                        df_scorecard = pd.DataFrame(scorecard_data)
                        st.dataframe(df_scorecard, use_container_width=True, hide_index=True)

                    if case.get("QA_Feedback"):
                        st.info(f"📝 **QA Feedback:** {case.get('QA_Feedback')}")

                st.markdown("</div>", unsafe_allow_html=True)

            with action_col:
                t_col1, t_col2, t_col3 = st.columns(3)
                with t_col1:
                    t_edit = st.toggle("✏️ Edit", key=f"t_edit_{case['_id']}")
                with t_col2:
                    t_del = st.toggle("🗑️ Del", key=f"t_del_{case['_id']}")
                with t_col3:
                    t_qa = st.toggle("🎯 QA", key=f"t_qa_{case['_id']}")

            if t_edit:
                with st.container(border=True):
                    st.markdown(f"#### Edit Case #{case.get('Case Number','')}")
                    edit_owner = st.selectbox(
                        "Record Assignment Owner",
                        owner_list,
                        index=(
                            owner_list.index(case.get("Owner"))
                            if case.get("Owner") in owner_list
                            else 0
                        ),
                        key=f"owner_{case['_id']}",
                    )

                    try:
                        default_target = date.fromisoformat(
                            case.get("Target Date", str(date.today()))
                        )
                    except ValueError:
                        default_target = date.today()
                    edit_target_date = st.date_input(
                        "Target Date",
                        value=default_target,
                        key=f"target_date_{case['_id']}",
                    )

                    edit_type = st.selectbox(
                        "Interaction Channel Profile",
                        c_types,
                        index=(
                            c_types.index(case.get("Type"))
                            if case.get("Type") in c_types
                            else 0
                        ),
                        key=f"type_{case['_id']}",
                    )
                    edit_case_number = st.text_input(
                        "Identified Case Identifier",
                        value=case.get("Case Number", ""),
                        key=f"case_num_{case['_id']}",
                    )

                    if st.button("Save Record", key=f"save_ed_{case['_id']}"):
                        collection.update_one(
                            {"_id": case["_id"]},
                            {
                                "$set": {
                                    "Target Date": str(edit_target_date),
                                    "Owner": edit_owner,
                                    "Type": edit_type,
                                    "Case Number": edit_case_number,
                                }
                            },
                        )
                        get_cases_from_db.clear()
                        st.success(
                            "Case profile properties modified successfully."
                        )
                        st.rerun()

            if t_del:
                with st.container(border=True):
                    st.warning(
                        "⚠️ Supervised Destruction Operations Requesting"
                        " Credentials"
                    )
                    del_password = st.text_input(
                        "Security Authorization Vector Password",
                        type="password",
                        key=f"pwd_del_{case['_id']}",
                    )
                    if st.button(
                        "Purge Permanent Record", key=f"conf_del_{case['_id']}"
                    ):
                        if del_password == "Password1234":
                            collection.delete_one({"_id": case["_id"]})
                            get_cases_from_db.clear()
                            st.success("Database entity stripped completely.")
                            st.rerun()
                        else:
                            st.error(
                                "Credential confirmation mismatch validation"
                                " failure."
                            )

            if t_qa:
                with st.container(border=True):
                    st.markdown(
                        "### 🎯 QA Scorecard | Case"
                        f" #{case.get('Case Number','')}"
                    )

                    # Password check required if the case has already been audited
                    is_already_audited = case.get("QA_Audited", False)
                    qa_pwd_valid = True

                    if is_already_audited:
                        st.warning("🔒 **Security Gate:** Editing an audited QA record requires authorization.")
                        qa_edit_password = st.text_input(
                            "Enter Admin Password to Modify QA Audit",
                            type="password",
                            key=f"pwd_qa_edit_{case['_id']}"
                        )
                        qa_pwd_valid = (qa_edit_password == "Password1234")

                    # Audited status toggle with dynamic AUDITED / NOT AUDITED label
                    is_audited_val = case.get("QA_Audited", False)

                    toggle_key = f"qa_audited_toggle_{case['_id']}"
                    current_toggle_state = st.session_state.get(
                        toggle_key, is_audited_val
                    )
                    toggle_label = (
                        "Audit Status:"
                        f" {'AUDITED' if current_toggle_state else 'NOT AUDITED'}"
                    )

                    audited_status = st.toggle(
                        toggle_label, value=is_audited_val, key=toggle_key
                    )

                    met_opts = ["Met", "Not Met"]

                    st.markdown("#### 1️⃣ Timely Engagement Standard")
                    q_slo = st.selectbox(
                        "SLO/SLA",
                        met_opts,
                        index=met_opts.index(
                            case.get("QA_SLO_SLA", "Met")
                        ),
                        key=f"qa_slo_{case['_id']}",
                    )
                    q_resp = st.selectbox(
                        "Initial and consecutive responses",
                        met_opts,
                        index=met_opts.index(
                            case.get("QA_Initial_Consecutive_Resp", "Met")
                        ),
                        key=f"qa_resp_{case['_id']}",
                    )
                    q_update = st.selectbox(
                        "Case status update",
                        met_opts,
                        index=met_opts.index(
                            case.get("QA_Case_Status_Update", "Met")
                        ),
                        key=f"qa_update_{case['_id']}",
                    )

                    st.markdown("#### 2️⃣ Documentations")
                    q_issue = st.selectbox(
                        "Issue field updated with description, frequency and"
                        " start date",
                        met_opts,
                        index=met_opts.index(
                            case.get("QA_Issue_Field_Updated", "Met")
                        ),
                        key=f"qa_issue_{case['_id']}",
                    )
                    q_probing = st.selectbox(
                        "Case comments with probing questions and answers (🚨"
                        " Non-negotiable)",
                        met_opts,
                        index=met_opts.index(
                            case.get("QA_Case_Comments_Probing", "Met")
                        ),
                        key=f"qa_probing_{case['_id']}",
                    )
                    q_collab = st.selectbox(
                        "Collaborations/Case communication logging (🚨"
                        " Non-negotiable)",
                        met_opts,
                        index=met_opts.index(
                            case.get("QA_Collaborations_Logging", "Met")
                        ),
                        key=f"qa_collab_{case['_id']}",
                    )

                    st.markdown("#### 3️⃣ Validation Process Guidelines")
                    q_entitle = st.selectbox(
                        "Entitlement Validation Process (🚨 Non-negotiable)",
                        met_opts,
                        index=met_opts.index(
                            case.get("QA_Entitlement_Validation", "Met")
                        ),
                        key=f"qa_entitle_{case['_id']}",
                    )
                    q_account = st.selectbox(
                        "Account Validation Process",
                        met_opts,
                        index=met_opts.index(
                            case.get("QA_Account_Validation", "Met")
                        ),
                        key=f"qa_account_{case['_id']}",
                    )

                    st.markdown("#### 4️⃣ Process and Policy")
                    q_routing = st.selectbox(
                        "UVA, SDI, Private Case Routing (🚨 Non-negotiable)",
                        met_opts,
                        index=met_opts.index(
                            case.get("QA_Case_Routing", "Met")
                        ),
                        key=f"qa_routing_{case['_id']}",
                    )

                    all_criteria = [
                        q_slo,
                        q_resp,
                        q_update,
                        q_issue,
                        q_probing,
                        q_collab,
                        q_entitle,
                        q_account,
                        q_routing,
                    ]
                    non_negotiables = [q_probing, q_collab, q_entitle, q_routing]

                    if audited_status:
                        if any(nn == "Not Met" for nn in non_negotiables):
                            computed_score = 0
                            st.error(
                                "🚨 **Score: 0 / 9** (Failed a Non-negotiable"
                                " criteria)"
                            )
                        else:
                            deductions = sum(
                                1 for item in all_criteria if item == "Not Met"
                            )
                            computed_score = max(0, 9 - deductions)
                            st.metric("Calculated QA Score", f"{computed_score} / 9")

                        qa_status_display = (
                            "PASSED" if computed_score == 9 else "FAILED"
                        )
                        if qa_status_display == "PASSED":
                            st.success(f"**STATUS: {qa_status_display}** ✅")
                        else:
                            st.error(f"**STATUS: {qa_status_display}** ❌")
                    else:
                        computed_score = None
                        st.info("ℹ️ **Status: NOT AUDITED**")

                    qa_feedback_str = st.text_area(
                        "QA Auditor Feedback",
                        value=case.get("QA_Feedback", ""),
                        key=f"qa_fb_{case['_id']}",
                    )

                    if st.button(
                        "💾 Save QA Scorecard", key=f"btn_save_qa_{case['_id']}"
                    ):
                        if is_already_audited and not qa_pwd_valid:
                            st.error("❌ Unauthorized: Incorrect password provided for editing audited record.")
                        else:
                            collection.update_one(
                                {"_id": case["_id"]},
                                {
                                    "$set": {
                                        "QA_SLO_SLA": q_slo,
                                        "QA_Initial_Consecutive_Resp": q_resp,
                                        "QA_Case_Status_Update": q_update,
                                        "QA_Issue_Field_Updated": q_issue,
                                        "QA_Case_Comments_Probing": q_probing,
                                        "QA_Collaborations_Logging": q_collab,
                                        "QA_Entitlement_Validation": q_entitle,
                                        "QA_Account_Validation": q_account,
                                        "QA_Case_Routing": q_routing,
                                        "QA_Score": computed_score,
                                        "QA_Audited": audited_status,
                                        "QA_Feedback": qa_feedback_str,
                                    }
                                },
                            )
                            get_cases_from_db.clear()
                            st.success("QA evaluation saved successfully!")
                            st.rerun()

    else:
        st.info("No active system case records match filter parameters.")

# --- TAB 5: DEVIATION ---
with tab_dev:
    st.subheader("Submit Deviation Request")

    with st.container(border=True):
        st.markdown("### 🌐 Information")
        g_col1, g_col2, g_col3 = st.columns(3)
        with g_col1:
            target_date = st.date_input("Target Date", value=date.today())
        with g_col2:
            manager = st.text_input("Manager", value="Jeff Bote")
        with g_col3:
            available_names = list(st.session_state.staff_roster.keys())
            name = st.selectbox("Name", available_names, key="dev_name_box")

        date_str = str(target_date)
        shift_time = (
            st.session_state.calendar_data.get(target_date, {}).get("shift")
            or st.session_state.calendar_data.get(date_str, {}).get(
                "shift", "Not Set"
            )
        )

        st.write(f"**Shift Time:** `{shift_time}`")

    st.markdown("### 📊 Bulk Entry Log")
    if "bulk_deviation_entries" not in st.session_state:
        st.session_state.bulk_deviation_entries = [{
            "start": "09:00",
            "end": "09:30",
            "duration": "30m",
            "aux": "",
            "reason": "",
        }]

    hdr_cols = st.columns([2, 2, 2, 2, 4])
    hdr_cols[0].markdown("**Start Time (HH:MM)**")
    hdr_cols[1].markdown("**End Time (HH:MM)**")
    hdr_cols[2].markdown("**Duration**")
    hdr_cols[3].markdown("**Aux**")
    hdr_cols[4].markdown("**Reason of Deviation**")

    for idx, entry in enumerate(st.session_state.bulk_deviation_entries):
        row_cols = st.columns([2, 2, 2, 2, 4])
        with row_cols[0]:
            start_val = st.text_input(
                "Start",
                value=entry["start"],
                label_visibility="collapsed",
                key=f"dev_matrix_start_{idx}",
            )
            entry["start"] = start_val
        with row_cols[1]:
            end_val = st.text_input(
                "End",
                value=entry["end"],
                label_visibility="collapsed",
                key=f"dev_matrix_end_{idx}",
            )
            entry["end"] = end_val

        calc_mins = calculate_duration_mins(entry["start"], entry["end"])
        if calc_mins > 0:
            entry["duration"] = f"{calc_mins}m"
        else:
            entry["duration"] = "0m"

        with row_cols[2]:
            st.text_input(
                "Duration",
                value=entry["duration"],
                label_visibility="collapsed",
                key=f"dev_matrix_dur_{idx}",
                disabled=True,
            )
        with row_cols[3]:
            entry["aux"] = st.text_input(
                "Aux",
                value=entry["aux"],
                label_visibility="collapsed",
                key=f"dev_matrix_aux_{idx}",
            )
        with row_cols[4]:
            entry["reason"] = st.text_area(
                "Reason",
                value=entry["reason"],
                label_visibility="collapsed",
                key=f"dev_matrix_reas_{idx}",
                height=68,
            )

    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 2, 4])
    with ctrl_col1:
        if st.button("➕ Add Row", key="btn_add_dev_matrix_row"):
            st.session_state.bulk_deviation_entries.append({
                "start": "09:00",
                "end": "09:30",
                "duration": "30m",
                "aux": "",
                "reason": "",
            })
            st.rerun()
    with ctrl_col2:
        if st.button("🗑️ Remove Last Row", key="btn_remove_dev_matrix_row"):
            if len(st.session_state.bulk_deviation_entries) > 1:
                st.session_state.bulk_deviation_entries.pop()
                st.rerun()
            else:
                st.warning("Minimum of 1 entry line required.")
    with ctrl_col3:
        if st.button("💾 Submit All", key="btn_save_batch_deviations"):
            records_saved = 0
            has_zero_error = False

            for entry in st.session_state.bulk_deviation_entries:
                total_mins = calculate_duration_mins(
                    entry["start"], entry["end"]
                )

                if total_mins <= 0:
                    has_zero_error = True
                    st.error(
                        f"❌ Invalid duration for time slot {entry['start']} -"
                        f" {entry['end']}. Duration cannot be 0 minutes."
                    )
                    continue

                save_deviation_to_db({
                    "Date": str(target_date),
                    "Manager": manager,
                    "Name": name,
                    "Shift Time": shift_time,
                    "Start Time": str(entry["start"].strip()),
                    "End Time": str(entry["end"].strip()),
                    "Total Mins": total_mins,
                    "Aux": entry["aux"],
                    "Reason": entry["reason"],
                })
                records_saved += 1

            if records_saved > 0:
                st.success(
                    f"Successfully processed and recorded {records_saved}"
                    " deviation entities!"
                )
                st.session_state.bulk_deviation_entries = [{
                    "start": "09:00",
                    "end": "09:30",
                    "duration": "30m",
                    "aux": "",
                    "reason": "",
                }]
                st.rerun()

    st.divider()
    st.subheader("Deviation Report")

    with st.expander("Filter Report"):
        d_col1, d_col2, d_col3 = st.columns([2, 2, 2])
        filter_date_mode = d_col1.selectbox(
            "Filter Date By",
            ["Specific Date", "Month & Year", "All Time"],
            index=0,  # Defaults to "Specific Date"
            key="dev_filter_date_mode",
        )

        f_specific_date = None
        f_month = None
        f_year = None

        if filter_date_mode == "Specific Date":
            f_specific_date = d_col2.date_input(
                "Select Date", value=date.today(), key="dev_filter_spec_date"
            )
        elif filter_date_mode == "Month & Year":
            f_month = d_col2.selectbox(
                "Month",
                options=range(1, 13),
                index=date.today().month - 1,
                format_func=lambda x: calendar.month_name[x],
                key="dev_filter_month",
            )
            f_year = d_col3.number_input(
                "Year", value=date.today().year, step=1, key="dev_filter_year"
            )

    dev_data = fetch_deviations_from_db()
    if dev_data:
        df = pd.DataFrame(dev_data)
        df["Date"] = pd.to_datetime(df["Date"]).dt.date
        df = df[df["Name"] != "Jeff Bote"]

        # Dynamic Date Filtering Logic
        if filter_date_mode == "Specific Date" and f_specific_date:
            df = df[df["Date"] == f_specific_date]
        elif filter_date_mode == "Month & Year" and f_month and f_year:
            df = df[
                (df["Date"].apply(lambda x: x.month) == f_month)
                & (df["Date"].apply(lambda x: x.year) == f_year)
            ]
        # "All Time" applies no filtering on df["Date"]

        filtered_records = df.to_dict(orient="records")

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Extract Report as CSV", csv, "deviation_report.csv", "text/csv"
        )
        st.write("## Deviation Records")

        if filtered_records:
            items_per_page = 10
            total_dev_pages = max(
                1, (len(filtered_records) + items_per_page - 1) // items_per_page
            )

            dp_col1, dp_col2 = st.columns([1, 4])
            with dp_col1:
                dev_page = st.number_input(
                    "Page",
                    min_value=1,
                    max_value=total_dev_pages,
                    value=1,
                    step=1,
                    key="dev_page_num",
                )
            with dp_col2:
                st.write(
                    f"Showing page **{dev_page}** of **{total_dev_pages}**"
                    f" ({len(filtered_records)} total records)"
                )

            col_widths = [0.6, 1.2, 1.2, 1.2, 1.2, 1.0, 1.0, 0.8, 0.8, 2.0, 2.4]
            h_cols = st.columns(col_widths)
            headers = [
                "#",
                "Date",
                "Manager",
                "Name",
                "Shift Time",
                "Start Time",
                "End Time",
                "Total Mins",
                "Aux",
                "Reason",
                "Actions",
            ]
            for idx, header_title in enumerate(headers):
                h_cols[idx].markdown(f"**{header_title}**")
            st.markdown("---")

            reversed_all_records = list(reversed(filtered_records))
            start_idx = (dev_page - 1) * items_per_page
            end_idx = start_idx + items_per_page
            paginated_records = reversed_all_records[start_idx:end_idx]

            total_records = len(filtered_records)

            for page_rel_idx, dev in enumerate(paginated_records):
                overall_reverse_idx = start_idx + page_rel_idx
                entry_number = total_records - overall_reverse_idx

                r_cols = st.columns(col_widths)
                r_cols[0].write(f"#{entry_number}")
                r_cols[1].write(str(dev.get("Date", "")))
                r_cols[2].write(str(dev.get("Manager", "")))
                r_cols[3].write(str(dev.get("Name", "")))
                r_cols[4].write(str(dev.get("Shift Time", "Not Set")))
                r_cols[5].write(str(dev.get("Start Time", "")))
                r_cols[6].write(str(dev.get("End Time", "")))
                r_cols[7].write(str(dev.get("Total Mins", 0)))
                r_cols[8].write(str(dev.get("Aux", "N/A")))
                r_cols[9].write(str(dev.get("Reason", "")))

                with r_cols[10]:
                    t_edit = st.toggle("✏️ Edit", key=f"t_edit_{dev['_id']}")
                    t_del = st.toggle("🗑️ Del", key=f"t_del_{dev['_id']}")

                if t_edit:
                    with st.container(border=True):
                        st.markdown(
                            "#### Edit Properties Frame For Record Line Item"
                            f" #{entry_number}"
                        )
                        edit_date = st.date_input(
                            "Update Target Date",
                            value=pd.to_datetime(dev.get("Date")).date(),
                            key=f"ed_date_{dev['_id']}",
                        )
                        edit_manager = st.text_input(
                            "Update Manager",
                            value=dev.get("Manager", ""),
                            key=f"ed_mgr_{dev['_id']}",
                        )

                        staff_names = (
                            list(st.session_state.staff_roster.keys())
                            if st.session_state.staff_roster
                            else [dev.get("Name", "")]
                        )
                        if dev.get("Name") not in staff_names:
                            staff_names.append(dev.get("Name"))

                        edit_name = st.selectbox(
                            "Update Name",
                            staff_names,
                            index=staff_names.index(dev.get("Name")),
                            key=f"ed_name_{dev['_id']}",
                        )
                        edit_shift = st.text_input(
                            "Update Shift Time",
                            value=dev.get("Shift Time", "Not Set"),
                            key=f"ed_shift_{dev['_id']}",
                        )

                        c1, c2, c3 = st.columns(3)
                        edit_start = c1.text_input(
                            "Update Start Time",
                            value=dev.get("Start Time", "00:00"),
                            key=f"ed_start_{dev['_id']}",
                        )
                        edit_end = c2.text_input(
                            "Update End Time",
                            value=dev.get("End Time", "00:00"),
                            key=f"ed_end_{dev['_id']}",
                        )

                        auto_mins = calculate_duration_mins(
                            edit_start, edit_end
                        )
                        edit_mins = c3.number_input(
                            "Update Total Mins",
                            value=max(1, auto_mins),
                            min_value=1,
                            key=f"ed_mins_{dev['_id']}",
                        )

                        edit_aux = st.text_input(
                            "Update Aux",
                            value=dev.get("Aux", ""),
                            key=f"ed_aux_{dev['_id']}",
                        )
                        edit_reason = st.text_area(
                            "Update Reason of Deviation",
                            value=dev.get("Reason", ""),
                            key=f"ed_reas_{dev['_id']}",
                        )

                        if st.button(
                            "Save Changes", key=f"save_ed_dev_{dev['_id']}"
                        ):
                            update_deviation_in_db(dev["_id"], {
                                "Date": str(edit_date),
                                "Manager": edit_manager,
                                "Name": edit_name,
                                "Shift Time": edit_shift,
                                "Start Time": str(edit_start),
                                "End Time": str(edit_end),
                                "Total Mins": edit_mins,
                                "Aux": edit_aux,
                                "Reason": edit_reason,
                            })
                            st.success("Deviation record updated completely!")
                            st.rerun()

                if t_del:
                    with st.container(border=True):
                        st.warning(
                            "⚠️ This action requires supervisor authorization"
                            " credentials verification validation."
                        )
                        del_password = st.text_input(
                            "Enter Admin Password to confirm delete",
                            type="password",
                            key=f"pwd_del_dev_{dev['_id']}",
                        )
                        if st.button(
                            "Confirm Purge Selection Action",
                            key=f"conf_del_dev_{dev['_id']}",
                        ):
                            if del_password == "Password1234":
                                delete_deviation_from_db(dev["_id"])
                                st.success("Deviation record removed.")
                                st.rerun()
                            else:
                                st.error("Incorrect Password. Action denied.")

                st.markdown("---")
        else:
            st.info("No deviation records match the selected filter criteria.")
    else:
        st.write("No deviation requests found.")
        
# --- TAB 6: ADMIN PANEL ---
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
        
            # Expand the columns list so Edit and Remove each get their own dedicated column
            # [Emp ID, Name, Nickname, Birthday, Edit Btn, Remove Btn]
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
        
                    # Placed directly into columns 4 and 5 (no nesting required)
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
                if str(r["date"]) == str(base_date)
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

            def get_all_requests_dataframe(
                requests_list, select_all_values=False
            ):
                filtered = [
                    r
                    for r in requests_list
                    if r.get("type") in ["Wellness", "PTO"]
                ]
                if not filtered:
                    return pd.DataFrame()

                data = {
                    "Select": [select_all_values] * len(filtered),
                    "Date": [r.get("date", "") for r in filtered],
                    "Name": [r.get("name", "") for r in filtered],
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
                calculated_height = max(
                    150, min(800, (len(all_requests_df) * 35) + 40)
                )

                edited_df = st.data_editor(
                    all_requests_df,
                    hide_index=True,
                    column_config={
                        "Select": st.column_config.CheckboxColumn(
                            default=False
                        ),
                        "Date": st.column_config.TextColumn(disabled=True),
                        "Name": st.column_config.TextColumn(disabled=True),
                        "Type": st.column_config.TextColumn(disabled=True),
                        "Status": st.column_config.TextColumn(disabled=True),
                        "_id": None,
                    },
                    use_container_width=True,
                    height=calculated_height,
                    key="editor_all_requests",
                )
            else:
                st.write("*No pending Wellness or PTO requests.*")

            if not all_requests_df.empty:
                st.markdown("---")
                btn_col1, btn_col2 = st.columns(2)

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
                                current_select_states[int(row_idx)] = edit_dict[
                                    "Select"
                                ]

                    for idx, is_selected in enumerate(current_select_states):
                        if is_selected:
                            selected_ids.append(base_df.iloc[idx]["_id"])
                    return selected_ids

                with btn_col1:
                    if st.button(
                        "✅ Approve Selected",
                        type="primary",
                        use_container_width=True,
                    ):
                        target_ids = get_selected_ids(
                            all_requests_df, "editor_all_requests"
                        )
                        if target_ids:
                            bulk_update_requests(target_ids, "Approved")
                            st.session_state.admin_msg = (
                                "success",
                                f"Successfully approved {len(target_ids)}"
                                " requests!",
                            )
                            st.rerun()
                        else:
                            st.warning(
                                "Please select at least one request to approve."
                            )

                with btn_col2:
                    if st.button(
                        "❌ Deny Selected",
                        type="secondary",
                        use_container_width=True,
                    ):
                        target_ids = get_selected_ids(
                            all_requests_df, "editor_all_requests"
                        )
                        if target_ids:
                            bulk_update_requests(target_ids, "Rejected")
                            st.session_state.admin_msg = (
                                "success",
                                f"Successfully denied {len(target_ids)}"
                                " requests!",
                            )
                            st.rerun()
                        else:
                            st.warning(
                                "Please select at least one request to deny."
                            )

            st.divider()
            st.subheader("Approved History")
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
            
            # 1. Fetch roster_list from database to map full name -> emp_id
            roster_doc = collection.find_one({"type": "roster_list"})
            roster_data = roster_doc.get("data", {}) if roster_doc else {}
            roster_lookup = {
                name: details.get("emp_id", "N/A")
                for name, details in roster_data.items()
            }

            # Helper function to get emp_id from roster lookup or request data
            def get_emp_id(req):
                name = req.get("name", "")
                if name in roster_lookup and roster_lookup[name]:
                    return roster_lookup[name]
                return req.get("emp_id", "N/A")

            # Helper function to format full names as "Last Name, First Name"
            def format_last_first(full_name):
                if not full_name or not isinstance(full_name, str):
                    return ""
                parts = full_name.strip().split()
                if len(parts) > 1:
                    return f"{parts[-1]}, {' '.join(parts[:-1])}"
                return full_name
            
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
                        
                        # Populate emp_id dynamically from database roster lookup
                        r_copy["emp_id"] = get_emp_id(r_copy)

                        # Format date string to M/D/YYYY (e.g., 7/28/2026)
                        try:
                            r_copy["date"] = date_val.strftime("%-m/%-d/%Y")
                        except ValueError:
                            # Windows fallback (using # instead of -)
                            r_copy["date"] = date_val.strftime("%#m/%#d/%Y")
                            
                        filtered_history_requests.append(r_copy)
            
            if filtered_history_requests:
                st.markdown("#### Approved Requests Summary")
                history_df = pd.DataFrame(filtered_history_requests)
                history_df.sort_values(
                    by="parsed_date", ascending=True, inplace=True
                )
            
                # Reformat name to "Last Name, First Name"
                if "name" in history_df.columns:
                    history_df["name"] = history_df["name"].apply(format_last_first)
            
                if "type" in history_df.columns:
                    history_df.rename(
                        columns={"type": "Request Type"}, inplace=True
                    )
            
                # Rename columns for presentation
                history_df.rename(
                    columns={
                        "emp_id": "Employee ID",
                        "date": "Date",
                        "name": "Name",
                        "status": "Status",
                    },
                    inplace=True,
                )
            
                columns_to_drop = ["_id", "parsed_date", "email", "viewed"]
                history_display_df = history_df.drop(
                    columns=columns_to_drop, errors="ignore"
                )
            
                desired_order = ["Employee ID", "Date", "Name", "Request Type", "Status"]
                existing_cols = [
                    c for c in desired_order if c in history_display_df.columns
                ]
                extra_cols = [
                    c for c in history_display_df.columns if c not in desired_order
                ]
            
                history_display_df = history_display_df[
                    existing_cols + extra_cols
                ]
                history_height = (len(history_display_df) * 35) + 45
            
                st.dataframe(
                    history_display_df,
                    hide_index=True,
                    use_container_width=True,
                    height=history_height,
                )
            else:
                st.write(
                    "*No verified history logs found matching calendar"
                    " dimensions.*"
                )
            
            st.markdown("</div>", unsafe_allow_html=True)
