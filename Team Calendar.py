from datetime import datetime, time, date, timedelta
import streamlit as st
from pymongo import MongoClient
import calendar
import pandas as pd
import holidays
import pytz
import re
import altair as alt

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
@st.cache_data(ttl=60)
def fetch_roster_doc():
    try:
        return collection.find_one({"type": "roster_list"}) or {}
    except Exception:
        return {}

@st.cache_data(ttl=60)
def fetch_calendar_doc():
    try:
        return collection.find_one({"type": "calendar_data"}) or {}
    except Exception:
        return {}

@st.cache_data(ttl=60)
def fetch_masterfile_doc():
    try:
        return collection.find_one({"type": "masterfile"}) or {}
    except Exception:
        return {}

@st.cache_data(ttl=30)
def get_cases_from_db():
    try:
        return list(collection.find({"type": "case"}))
    except Exception:
        return []

@st.cache_data(ttl=30)
def fetch_deviations_from_db():
    try:
        return list(collection.find({"type": "deviation"}))
    except Exception:
        return []

@st.cache_data(ttl=30)
def fetch_approved_requests_from_db():
    try:
        return list(collection.find({
            "type": {"$in": ["PTO", "Wellness", "Sick Leave"]}, 
            "status": "Approved"
        }))
    except Exception:
        return []

@st.cache_data(ttl=30)
def fetch_pending_requests_from_db():
    try:
        return list(collection.find({
            "type": {"$in": ["PTO", "Wellness", "Sick Leave"]}, 
            "status": "Pending"
        }))
    except Exception:
        return []

# --- DB MUTATION HELPERS ---
def bulk_update_requests(request_ids, status):
    collection.update_many(
        {"_id": {"$in": request_ids}},
        {"$set": {"status": status}}
    )
    st.cache_data.clear()

def save_staff(name, data):
    st.session_state.staff_roster[name] = data
    collection.update_one({"type": "roster_list"}, {"$set": {"data": st.session_state.staff_roster}}, upsert=True)
    st.cache_data.clear()

def delete_staff(name):
    collection.delete_one({"type": "roster_list", "name": name})
    if name in st.session_state.staff_roster: 
        del st.session_state.staff_roster[name]
    st.cache_data.clear()

def update_staff_in_db(name, update_dict):
    collection.update_one({"type": "roster_list", "name": name}, {"$set": update_dict})
    if name in st.session_state.staff_roster:
        st.session_state.staff_roster[name].update(update_dict)
    st.cache_data.clear()

def save_case_to_db(case_data):
    case_data["type"] = "case"
    collection.insert_one(case_data)
    st.cache_data.clear()

def save_deviation_to_db(data):
    data["type"] = "deviation"
    collection.insert_one(data)
    st.cache_data.clear()

def update_deviation_in_db(id_val, update_dict):
    collection.update_one({"_id": id_val}, {"$set": update_dict})
    st.cache_data.clear()

def delete_deviation_from_db(id_val):
    collection.delete_one({"_id": id_val})
    st.cache_data.clear()

def delete_request_from_db(req):
    collection.delete_one({"_id": req["_id"]})
    st.cache_data.clear()

def update_request_status_in_db(req, status):
    collection.update_one({"_id": req["_id"]}, {"$set": {"status": status}})
    st.cache_data.clear()

def save_request_to_db(req, request_type):
    req["type"] = request_type
    collection.insert_one(req)
    st.cache_data.clear()

def save_masterfile_to_db(df):
    collection.update_one({"type": "masterfile"}, {"$set": {"data": df.to_dict(orient="records")}}, upsert=True)
    st.cache_data.clear()

def get_request_limits(req_date):
    cal_doc = fetch_calendar_doc()
    selected_config = cal_doc.get("data", {}).get(str(req_date), {})
    
    st.session_state.limits["PTO_per_day"] = selected_config.get("PTO_per_day", 1)
    st.session_state.limits["Wellness_per_day"] = selected_config.get("Wellness_per_day", 1)
    return st.session_state.limits

def send_request_notification(recipient_email, status, request_type, date_val):
    pass

# --- INITIAL CONFIG & STATE ---
st.title("📊 Team Operations Management System (TOMS)")

local_tz = pytz.timezone("Asia/Manila") 
current_date = datetime.now(local_tz).date()

if "admin_password" not in st.session_state: st.session_state.admin_password = "Password1234"
if "admin_authenticated" not in st.session_state: st.session_state.admin_authenticated = False
if "limits" not in st.session_state:
    st.session_state.limits = {"PTO_per_day": 1, "Wellness_per_day": 1}
if "notifications" not in st.session_state: st.session_state.notifications = []
if "master_data" not in st.session_state: 
    st.session_state.master_data = pd.DataFrame({
        "Category": ["Contact Type", "Issue", "Product Group"], 
        "Values": ["Call,Chat,Email", "Tech,Billing", "Hardware,Soft"]
    })

# Fetch heavy datasets exactly ONCE per runner cycle globally
roster_doc = fetch_roster_doc()
st.session_state.staff_roster = roster_doc.get("data", {}) if roster_doc else {}

# Data migration normalization
if "staff_roster" in st.session_state:
    for name, value in st.session_state.staff_roster.items():
        if isinstance(value, dict) and isinstance(value.get("bday"), date) and not isinstance(value.get("bday"), datetime):
            d = value["bday"]
            value["bday"] = datetime(d.year, d.month, d.day)

calendar_doc = fetch_calendar_doc()
raw_cal_data = calendar_doc.get("data", {}) if calendar_doc else {}
st.session_state.calendar_data = {
    (datetime.strptime(k, "%Y-%m-%d").date() if isinstance(k, str) and len(k) == 10 else k): v 
    for k, v in raw_cal_data.items()
}

global_approved_requests = fetch_approved_requests_from_db()
global_pending_requests = fetch_pending_requests_from_db()

# --- GLOBAL CSS STYLING ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Quicksand:wght=400;600&display=swap');
    html, body, [class*="css"] { font-family: 'Quicksand', sans-serif !important; }
    h1, h2, h3, .header-cell { font-family: 'Quicksand', sans-serif !important; font-weight: 600; color: #008080 !important; }
    .side-block { font-family: 'Quicksand', sans-serif !important; font-size: 10px !important; line-height: 1.2; }
    
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

    .card-passed {
        background-color: #e6f4ea !important;
        border: 1px solid #34a853 !important;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 10px;
    }
    .card-failed {
        background-color: #fce8e6 !important;
        border: 2px solid #ea4335 !important;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# --- NOTIFICATION BAR ---
if st.session_state.notifications:
    html_content = '<div class="alert-container"><div class="flash-red" style="margin-bottom: 10px;">⚠️ ATTENTION: New System Notifications Detected!</div>'
    for n in st.session_state.notifications:
        html_content += f'<div style="background-color: #fff3cd; padding: 10px; border-radius: 5px; margin: 5px 0; border-left: 5px solid #ffecb5; color: #856404;"><b>System Notice:</b> {n}</div>'
    html_content += '</div>'
    st.markdown(html_content, unsafe_allow_html=True)

# --- REQUEST RENDER HANDLER ---
def render_request(req, key_prefix):
    unique_id = str(req.get('_id', 'fallback'))
    denial_key = f"denying_{key_prefix}_{unique_id}"
    
    st.info(f"Name: {req.get('name')}\nType: {req.get('type')}\nDate: {req.get('date')}\nStatus: {req.get('status')}")
    
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
        reason = st.text_input("Reason for denial", key=f"reason_{key_prefix}_{unique_id}")
        col1, col2 = st.columns(2)
        if col1.button("Proceed Denial", key=f"confirm_{key_prefix}_{unique_id}"):
            update_request_status_in_db(req, "Rejected")
            st.session_state[denial_key] = False
            st.success("Request denied.")
            st.rerun()
        if col2.button("Cancel", key=f"cancel_{key_prefix}_{unique_id}"):
            st.session_state[denial_key] = False
            st.rerun()

# --- TABS WORKSPACE ---
tab_names = [
    "📅 Calendar", "📝 Request", "📈 Productivity Monitoring", 
    "🔍 Case Tracker", "🔀 Deviation", "🔑 Admin"
]

tab_cal, tab_req, tab_prod, tab_case, tab_dev, tab_adm = st.tabs(tab_names)

# --- TAB 1: CALENDAR ---
with tab_cal:
    col_main, space_gap, col_side = st.columns([4, 0.2, 1])
    
    with col_main:
        c1, c2 = st.columns([1, 1])
        year = c1.selectbox("Year", [2026, 2027, 2028], key="cal_y")
        month = c2.selectbox("Month", range(1, 13), format_func=lambda x: calendar.month_name[x], index=current_date.month - 1, key="cal_m")

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
        us_hols, ph_hols, found_holiday = holidays.US(years=year), holidays.PH(years=year), False
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

        d_data = st.session_state.calendar_data.get(view_date) or st.session_state.calendar_data.get(str(view_date)) or {}
        
        st.markdown(f"### Date: {view_date.strftime('%B %d, %Y')}")
        
        if view_date.weekday() in [5, 6]:
            day_status, day_shift = "REST DAY", "--"
        else:
            day_status = d_data.get('status', 'Not Set')
            day_shift = d_data.get('shift', '--')

        st.markdown(f"**Work Setup:** `{day_status}`")
        st.markdown(f"**Shift:** `{day_shift}`")

        tm_list = d_data.get('team_manager', [])
        tm_name = tm_list[0] if (isinstance(tm_list, list) and tm_list) else ""
        if tm_name:
            st.write(f"**Team Manager:** {tm_name}")
        
        st.write("**Today's Schedule:**")
        if view_date.weekday() in [5, 6]:
            st.info("📊 **Rest Day** — Weekend Schedule")
            sched_rows = [{"Name": name, "Role": "REST DAY"} for name in roster.keys()]
            if sched_rows:
                sched_df = pd.DataFrame(sched_rows).sort_values(by=["Role", "Name"], ascending=True)
                st.dataframe(sched_df, hide_index=True, use_container_width=True, height=min(1000, max(100, len(sched_df) * 35 + 38)))
            else:
                st.write("*No staff configured in the system.*")
        else:
            roles = ["team_manager", "call", "chat", "mfq", "sme"]
            sched_rows = []
            for name in roster.keys():
                p_status = [r["type"] for r in global_approved_requests if str(r["date"]) == str(view_date) and r["name"] == name]
                if p_status:
                    role_display = p_status[0].upper()
                else:
                    assigned_roles = []
                    for r in roles:
                        assigned_list = d_data.get(r, [])
                        if isinstance(assigned_list, list) and name in assigned_list:
                            assigned_roles.append(r.upper().replace("_", " "))
                        elif isinstance(assigned_list, dict) and name in assigned_list.keys():
                            assigned_roles.append(r.upper().replace("_", " "))
                    role_display = ", ".join(assigned_roles) if assigned_roles else "UNASSIGNED"
                
                if "TEAM MANAGER" in role_display or name == tm_name:
                    continue
                sched_rows.append({"Name": name, "Role": role_display})
                
            if sched_rows:
                sched_df = pd.DataFrame(sched_rows).sort_values(by=["Role", "Name"], ascending=True)
                st.dataframe(sched_df, hide_index=True, use_container_width=True, height=min(1000, max(100, len(sched_df) * 35 + 38)))
            else:
                st.write("*No staff configured in the system.*")
        st.markdown('</div>', unsafe_allow_html=True)

    with col_main:
        cols = st.columns(7)
        for i, d_name in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
            cols[i].markdown(f'<div class="header-cell">{d_name}</div>', unsafe_allow_html=True)
            
        for week in calendar.Calendar(firstweekday=6).monthdayscalendar(year, month):
            cols = st.columns(7)
            for i, day in enumerate(week):
                if day != 0:
                    d = date(year, month, day)
                    approved = [r for r in global_approved_requests if str(r["date"]) == str(d)]
                    away_names = [r['name'] for r in approved]
                    
                    def get_filtered_nicks(full_names):
                        active = [n for n in full_names if n not in away_names]
                        return ", ".join([roster.get(x, {}).get("nick", x) for x in active])
                    
                    req_display = "<br>".join([f"{roster.get(r['name'], {}).get('nick', r['name'])}({r['type']})" for r in approved])
                    
                    grid_data = st.session_state.calendar_data.get(d) or st.session_state.calendar_data.get(str(d)) or {}
                    
                    if d.weekday() in [5, 6]:
                        content = f"<b>{day}</b><div class='calendar-divider'></div><br><center><b>REST DAY</b></center>"
                    else:
                        content = (f"<b>{day}</b><div class='calendar-divider'></div>"
                                   f"<u>{grid_data.get('status', '-')}</u><div class='calendar-divider'></div>"
                                   f"{grid_data.get('shift', '-')}<div class='calendar-divider'></div>"
                                   f"PTO/Wellness/SL: {req_display}<div class='calendar-divider'></div>"
                                   f"Call: {get_filtered_nicks(grid_data.get('call', []))}<div class='calendar-divider'></div>"
                                   f"Chat: {get_filtered_nicks(grid_data.get('chat', []))}<div class='calendar-divider'></div>"
                                   f"MFQ: {get_filtered_nicks(grid_data.get('mfq', []))}<div class='calendar-divider'></div>"
                                   f"SME: {get_filtered_nicks(grid_data.get('sme', []))}")
                    
                    cols[i].markdown(f'<div class="day-block">{content}</div>', unsafe_allow_html=True)
                else:
                    cols[i].markdown('<div class="day-block day-block-outside"></div>', unsafe_allow_html=True)
                    
    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader("📆 Weekly Roster")
    
    month_start_date = date(year, month, 1)
    base_sunday = month_start_date - timedelta(days=(month_start_date.weekday() + 1) if month_start_date.weekday() != 6 else 0)
    
    sunday_options = [base_sunday + timedelta(weeks=i) for i in range(0, 6)]
    today_sunday = current_date - timedelta(days=(current_date.weekday() + 1) if current_date.weekday() != 6 else 0)
    
    default_week_index = sunday_options.index(today_sunday) if today_sunday in sunday_options else 0
    
    selected_week_start = st.selectbox(
        "Select Week Beginning (Sunday):", 
        options=sunday_options,
        index=default_week_index,
        format_func=lambda d: d.strftime("%B %d, %Y"),
        key="weekly_view_lookup_start_select"
    )
    
    week_start_sunday = pd.to_datetime(selected_week_start).date()
    week_days = [week_start_sunday + timedelta(days=idx) for idx in range(1, 6)]
    
    roles = ["team_manager", "call", "chat", "mfq", "sme"]
    
    setup_row = {"Staff Name": "🛠️ WORK SETUP"}
    shift_row = {"Staff Name": "⏰ SHIFT"}
    weekly_tms = []
    
    for day in week_days:
        col_name = day.strftime("%A (%m/%d)")
        day_config = st.session_state.calendar_data.get(day) or st.session_state.calendar_data.get(str(day)) or {}
        
        setup_row[col_name] = str(day_config.get('status', 'Not Set')).upper()
        shift_row[col_name] = str(day_config.get('shift', '--')).upper()
        
        tm_found = day_config.get('team_manager', [])
        if tm_found and tm_found[0] not in weekly_tms:
            weekly_tms.append(tm_found[0])

    weekly_rows = []
    for name in roster.keys():
        staff_row = {"Staff Name": name}
        is_tm_somewhere = False
        
        for day in week_days:
            col_name = day.strftime("%A (%m/%d)")
            
            p_status = [r["type"] for r in global_approved_requests if str(r["date"]) == str(day) and r["name"] == name]
            if p_status:
                staff_row[col_name] = p_status[0].upper()
            else:
                day_config = st.session_state.calendar_data.get(day) or st.session_state.calendar_data.get(str(day)) or {}
                    
                assigned_roles = []
                for r in roles:
                    assigned_list = day_config.get(r, [])
                    if isinstance(assigned_list, list) and name in assigned_list:
                        assigned_roles.append(r.upper().replace("_", " "))
                    elif isinstance(assigned_list, dict) and name in assigned_list.keys():
                        assigned_roles.append(r.upper().replace("_", " "))
                
                role_display = ", ".join(assigned_roles) if assigned_roles else "UNASSIGNED"
                
                if "TEAM MANAGER" in role_display:
                    is_tm_somewhere = True
                    break
                    
                staff_row[col_name] = role_display
        
        if not is_tm_somewhere:
            weekly_rows.append(staff_row)

    tm_display_string = ", ".join(set(weekly_tms)).upper() if weekly_tms else "NONE ASSIGNED"
    st.markdown(f"## TEAM MANAGER: {tm_display_string}")
    st.write("")

    if weekly_rows:
        first_day_col = week_days[0].strftime("%A (%m/%d)")
        staff_df = pd.DataFrame(weekly_rows).sort_values(by=[first_day_col, "Staff Name"], ascending=True)
        meta_df = pd.DataFrame([setup_row, shift_row])
        weekly_df = pd.concat([meta_df, staff_df], ignore_index=True)
        
        column_configurations = {
            "Staff Name": st.column_config.TextColumn(label="Staff Name")
        }
        for day in week_days:
            c_name = day.strftime("%A (%m/%d)")
            column_configurations[c_name] = st.column_config.TextColumn(label=c_name)

        st.dataframe(
            weekly_df, 
            column_config=column_configurations,
            hide_index=True, 
            use_container_width=True, 
            height=min(1000, max(100, len(weekly_df) * 35 + 38))
        )
    else:
        st.write("*No scheduled staff found for this week.*")

# --- TAB 2: REQUEST FORM ---
with tab_req:
    st.subheader("PTO / Wellness / SL Request Form")

    if "request_count" not in st.session_state:
        st.session_state.request_count = 1

    available_names = list(st.session_state.staff_roster.keys())

    selected_name = st.selectbox("Select Employee Name:", available_names, key="bulk_request_global_name")

    with st.form("bulk_request_form"):
        st.markdown("### 📊 Request Entry Table")
        
        header_cols = st.columns([1, 1])
        header_cols[0].markdown("**Date**")
        header_cols[1].markdown("**Request Type**")

        for i in range(st.session_state.request_count):
            row_cols = st.columns([1, 1])
            with row_cols[0]:
                st.date_input("Date", label_visibility="collapsed", key=f"date_{i}")
            with row_cols[1]:
                st.selectbox("Type", ["PTO", "Wellness", "Sick Leave"], label_visibility="collapsed", key=f"type_{i}")

        st.markdown("<br>", unsafe_allow_html=True)
        
        action_cols = st.columns([1, 1, 2])
        with action_cols[0]:
            add_row_triggered = st.form_submit_button("➕ Add New Row")
        with action_cols[1]:
            submit_triggered = st.form_submit_button("✅ Submit Entries", type="primary")

        if add_row_triggered:
            st.session_state.request_count += 1
            st.rerun()

        if submit_triggered:
            running_caps = {}
            # In-memory fast checks replacing DB count_documents queries inside loop
            existing_requests = global_pending_requests + global_approved_requests
            
            for i in range(st.session_state.request_count):
                req_date = st.session_state[f"date_{i}"]
                req_type = st.session_state[f"type_{i}"]
                date_str = str(req_date)
                cap_key = f"{req_type}_{date_str}"
                
                is_already_requested = any(
                    r.get("name") == selected_name and str(r.get("date")) == date_str and r.get("status") in ["Pending", "Approved"] 
                    for r in existing_requests
                )
                
                if is_already_requested:
                    st.warning(f"⚠️ A request for {selected_name} on {req_date} already exists.")
                    continue
                
                if req_type == "Sick Leave":
                    initial_status = "Approved"
                    new_req = {"name": selected_name, "date": date_str, "type": req_type, "status": initial_status}
                    save_request_to_db(new_req, req_type)
                else:
                    limits = get_request_limits(req_date)
                    limit_value = limits["PTO_per_day"] if req_type == "PTO" else limits["Wellness_per_day"]
                    
                    if cap_key not in running_caps:
                        db_count = sum(
                            1 for r in existing_requests 
                            if r.get("type") == req_type and str(r.get("date")) == date_str and r.get("status") in ["Pending", "Approved"]
                        )
                        running_caps[cap_key] = db_count
                        
                    if running_caps[cap_key] >= limit_value:
                        st.error(f"❌ Limit reached for {req_type} on {req_date}.")
                    else:
                        initial_status = "Pending"
                        new_req = {"name": selected_name, "date": date_str, "type": req_type, "status": initial_status}
                        save_request_to_db(new_req, req_type)
                        running_caps[cap_key] += 1
            
            st.success("All operational entries successfully verified and processed!")
            st.session_state.request_count = 1 
            st.rerun()
            
    st.subheader("Approved History")
    f_c1, f_c2 = st.columns(2)
    
    month_names = list(calendar.month_name)[1:]
    selected_month_name = f_c1.selectbox("Month", month_names, index=current_date.month-1, key="history_month_select")
    f_m = month_names.index(selected_month_name) + 1
    f_y = f_c2.number_input("Year", value=current_date.year, key="history_year_select")
    
    filtered_app = [r for r in global_approved_requests if int(r['date'].split('-')[1]) == f_m and int(r['date'].split('-')[0]) == f_y]
    
    if filtered_app: 
        df_display = pd.DataFrame(filtered_app)[['date', 'name', 'type']]
        df_display.columns = ["Date", "Name", "Type"]
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
            except:
                continue
            if req_date.month == f_m and req_date.year == f_y:
                filtered_pending.append(r)
    
        if filtered_pending:
            df_pending = pd.DataFrame(filtered_pending)
            df_pending["sort_date"] = pd.to_datetime(df_pending["date"])
            df_pending = df_pending.sort_values(by="sort_date", ascending=True)
            df_pending_display = df_pending[["date", "name", "type"]].copy()
            df_pending_display.columns = ["Date", "Name", "Type"]
    
            calculated_height = (len(df_pending_display) * 35) + 45
            st.dataframe(df_pending_display, hide_index=True, use_container_width=True, height=calculated_height)
        else:
            st.info(f"ℹ️ No pending Wellness or PTO requests found for {selected_month_name} {int(f_y)}.")
    else:
        st.write("*No pending requests await administrator review authorization logs.*")

# --- TAB 3: PRODUCTIVITY MONITORING ---
with tab_prod:
    cases = get_cases_from_db()
    dev_data = fetch_deviations_from_db()

    if not cases:
        st.info("No case records found.")
    else:
        df = pd.DataFrame(cases)
        if "_id" in df.columns:
            df = df.drop(columns=["_id"])
        
        # Coalesce Date and Target Date
        if "Date" not in df.columns and "Target Date" in df.columns:
            df["Date"] = df["Target Date"]
        elif "Date" in df.columns and "Target Date" in df.columns:
            df["Date"] = df["Date"].fillna(df["Target Date"])
        
        # Ensure string conversion before parsing to avoid type errors
        df["Date"] = pd.to_datetime(df["Date"].astype(str), errors="coerce")
        df = df.dropna(subset=["Date"])
        
        df["Month"] = df["Date"].dt.month
        df["Year"] = df["Date"].dt.year
        df["Day"] = df["Date"].dt.date
        

        st.markdown("## Monthly Productivity")
        col1, col2 = st.columns(2)
        years = sorted(df["Year"].dropna().unique())
        
        selected_year = col1.selectbox("Year", years if years else [date.today().year], key="prod_year")
        selected_month = col2.selectbox(
            "Month", 
            range(1, 13), 
            format_func=lambda x: calendar.month_name[x], 
            index=date.today().month - 1, 
            key="prod_monitor_month"
        )

        monthly_df = df[(df["Year"] == selected_year) & (df["Month"] == selected_month)]

        if not monthly_df.empty:
            monthly_summary = monthly_df.groupby(["Owner", "Type"]).size().unstack(fill_value=0)
            monthly_summary["Total Cases"] = monthly_summary.sum(axis=1)
            monthly_summary = monthly_summary.sort_values(by="Total Cases", ascending=False)
            
            m_height = min(1000, max(100, len(monthly_summary) * 35 + 38))
            st.dataframe(monthly_summary.reset_index(), use_container_width=True, height=m_height, hide_index=True)
        else:
            st.info("No cases found for selected month.")

        st.markdown("### 🔀 Monthly Deviation Summary")
        if dev_data:
            df_dev_m = pd.DataFrame(dev_data)
            df_dev_m['Date'] = pd.to_datetime(df_dev_m['Date'], errors="coerce")
            df_dev_m = df_dev_m.dropna(subset=['Date'])
            df_dev_m = df_dev_m[df_dev_m["Name"] != "Jeff Bote"]
            
            df_dev_filtered = df_dev_m[(df_dev_m['Date'].dt.year == selected_year) & (df_dev_m['Date'].dt.month == selected_month)]
            
            if not df_dev_filtered.empty:
                monthly_dev_summary = df_dev_filtered.groupby("Name").agg(
                    Total_Deviations=("Name", "count"),
                    Total_Minutes=("Total Mins", "sum")
                ).reset_index().rename(columns={"Name": "Employee", "Total_Deviations": "Total Deviations", "Total_Minutes": "Total Minutes Lost"})
                monthly_dev_summary = monthly_dev_summary.sort_values(by="Total Deviations", ascending=False)
                st.dataframe(monthly_dev_summary, use_container_width=True, hide_index=True)
            else:
                st.info("No deviation records found for selected month.")
        else:
            st.info("No deviation data available.")

        st.divider()

        st.markdown("## Daily Productivity")
        
        # Constrain date selector bounds to selected year and month
        num_days = calendar.monthrange(int(selected_year), int(selected_month))[1]
        min_date_val = date(int(selected_year), int(selected_month), 1)
        max_date_val = date(int(selected_year), int(selected_month), num_days)
        default_day_val = min(max(date.today(), min_date_val), max_date_val)
        
        selected_day = st.date_input(
            "Select Day", 
            value=default_day_val, 
            min_value=min_date_val, 
            max_value=max_date_val, 
            key="prod_day"
        )
        daily_df = df[df["Day"] == selected_day]

        if not daily_df.empty:
            daily_summary = daily_df.groupby(["Owner", "Type"]).size().unstack(fill_value=0)
            daily_summary["Total Cases"] = daily_summary.sum(axis=1)
            daily_summary = daily_summary.sort_values(by="Total Cases", ascending=False)
            
            d_height = min(1000, max(100, len(daily_summary) * 35 + 38))
            st.dataframe(daily_summary.reset_index(), use_container_width=True, height=d_height, hide_index=True)
        else:
            st.info("No cases found for selected day.")

        st.divider()

        st.markdown("## 📈 Daily Productivity & Deviation Trend per Owner")

        daily_owner_prod = df.groupby(["Day", "Owner"]).size().reset_index(name="Case Count")

        if not daily_owner_prod.empty:
            all_owners = sorted(daily_owner_prod["Owner"].unique().tolist())
            selected_chart_owner = st.selectbox(
                "Filter Chart by Case Owner", 
                ["All Owners"] + all_owners, 
                key="prod_chart_owner_filter"
            )

            if selected_chart_owner != "All Owners":
                chart_df = daily_owner_prod[daily_owner_prod["Owner"] == selected_chart_owner]
            else:
                chart_df = daily_owner_prod

            if not chart_df.empty:
                prod_line_chart = (
                    alt.Chart(chart_df)
                    .mark_line(point=True)
                    .encode(
                        x=alt.X("Day:T", title="Date", axis=alt.Axis(format="%Y-%m-%d", labelAngle=-45)),
                        y=alt.Y("Case Count:Q", title="Total Cases Handled"),
                        color=alt.Color("Owner:N", title="Case Owner"),
                        tooltip=["Day:T", "Owner:N", "Case Count:Q"]
                    )
                    .interactive()
                )
                st.altair_chart(prod_line_chart, use_container_width=True)
            else:
                st.info(f"No chart data available for {selected_chart_owner}.")

            # --- DAILY DEVIATION LINE CHART ---
            st.markdown("### 🔀 Daily Deviation Trend")
            if dev_data:
                df_dev_chart = pd.DataFrame(dev_data)
                df_dev_chart["Day"] = pd.to_datetime(df_dev_chart["Date"], errors="coerce").dt.date
                df_dev_chart = df_dev_chart.dropna(subset=["Day"])
                df_dev_chart = df_dev_chart[df_dev_chart["Name"] != "Jeff Bote"]

                daily_dev_counts = df_dev_chart.groupby(["Day", "Name"]).size().reset_index(name="Deviation Count")

                if selected_chart_owner != "All Owners":
                    dev_chart_df = daily_dev_counts[daily_dev_counts["Name"] == selected_chart_owner]
                else:
                    dev_chart_df = daily_dev_counts

                if not dev_chart_df.empty:
                    dev_line_chart = (
                        alt.Chart(dev_chart_df)
                        .mark_line(point=True)
                        .encode(
                            x=alt.X("Day:T", title="Date", axis=alt.Axis(format="%Y-%m-%d", labelAngle=-45)),
                            y=alt.Y("Deviation Count:Q", title="Total Deviations"),
                            color=alt.Color("Name:N", title="Employee"),
                            tooltip=["Day:T", "Name:N", "Deviation Count:Q"]
                        )
                        .interactive()
                    )
                    st.altair_chart(dev_line_chart, use_container_width=True)
                else:
                    st.info("No deviation trend data available for current selection.")
            else:
                st.info("No deviation records available.")

            st.markdown("### 🏆 Overall Leaderboard by Productivity")
            
            overall_leaderboard = (
                df.groupby("Owner")
                .agg(
                    Total_Cases=("Owner", "count"),
                    Days_Active=("Day", "nunique")
                )
                .reset_index()
            )
            
            overall_leaderboard["Avg Cases / Active Day"] = (
                overall_leaderboard["Total_Cases"] / overall_leaderboard["Days_Active"]
            ).round(2)

            overall_leaderboard = overall_leaderboard.rename(
                columns={"Total_Cases": "Total Cases Handled", "Days_Active": "Days Active"}
            ).sort_values(by="Total Cases Handled", ascending=False)

            l_height = min(1000, max(100, len(overall_leaderboard) * 35 + 38))
            st.dataframe(overall_leaderboard, use_container_width=True, height=l_height, hide_index=True)
        else:
            st.info("No daily productivity trend data available.")

# --- TAB 4: CASE TRACKER ---
with tab_case:
    st.subheader("📝 Bulk Log New Cases")
    cases_list = get_cases_from_db() 

    masterfile_doc = fetch_masterfile_doc()
    if masterfile_doc and "data" in masterfile_doc:
        master_df = pd.DataFrame(masterfile_doc["data"])
    else:
        master_df = pd.DataFrame({
            "Category": ["Contact Type"],
            "Values": ["Call,Chat,Email"]
        })

    c_types = master_df.loc[master_df["Category"] == "Contact Type", "Values"].iloc[0].split(",")

    owner_list = sorted(list(st.session_state.staff_roster.keys()))
    if not owner_list:
        owner_list = ["Unknown"]

    g_col1, g_col2, g_col3 = st.columns(3)
    with g_col1:
        global_target_date = st.date_input("Global Target Date", value=date.today(), key="case_global_target_date")
    with g_col2:
        global_c_type = st.selectbox("Global Contact Type", c_types, key="case_global_type")
    with g_col3:
        global_owner = st.selectbox("Global Case Owner", owner_list, key="case_global_owner")

    st.markdown("### 📊 Case Entry")

    if "batch_case_entries" not in st.session_state or len(st.session_state.batch_case_entries) == 0:
        st.session_state.batch_case_entries = [{"case_number": ""} for _ in range(5)]

    total_slots = len(st.session_state.batch_case_entries)
    for row_idx in range(0, total_slots, 5):
        cols = st.columns(5)
        for col_idx in range(5):
            entry_idx = row_idx + col_idx
            if entry_idx < total_slots:
                with cols[col_idx]:
                    st.session_state.batch_case_entries[entry_idx]["case_number"] = st.text_input(
                        f"Case #{entry_idx + 1}",
                        value=st.session_state.batch_case_entries[entry_idx]["case_number"],
                        key=f"grid_case_num_{entry_idx}"
                    )

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
                st.warning("Cannot remove slot. Minimum of 1 entry slot required.")
    with ctrl_col3:
        if st.button("💾 Submit All Cases", key="btn_save_batch_cases"):
            cases_saved = 0
            for entry in st.session_state.batch_case_entries:
                case_num_str = str(entry["case_number"]).strip()
                if not case_num_str:
                    continue
                new_case = {
                    "Date": str(global_target_date),
                    "Target Date": str(global_target_date),
                    "Owner": global_owner,
                    "Type": global_c_type,
                    "Case Number": case_num_str,
                    "Comment": "",
                    "QA_SLO_SLA": "Met",
                    "QA_Initial_Consecutive_Resp": "Met",
                    "QA_Case_Status_Update": "Met",
                    "QA_Issue_Field_Updated": "Met",
                    "QA_Case_Comments_Probing": "Met",
                    "QA_Collaborations_Logging": "Met",
                    "QA_Entitlement_Validation": "Met",
                    "QA_Account_Validation": "Met",
                    "QA_Case_Routing": "Met",
                    "QA_Score": 9,
                    "QA_Feedback": ""
                }
                save_case_to_db(new_case)
                cases_saved += 1
            
            if cases_saved > 0:
                st.success(f"Batch execution complete! {cases_saved} cases recorded.")
            else:
                st.warning("No valid case numbers entered. Blank slots were skipped.")
            st.session_state.batch_case_entries = [{"case_number": ""} for _ in range(5)]
            st.rerun()

    st.divider()
    st.subheader("📚 Knowledge Base & QA Reports")

    if cases_list:
        df_cases = pd.DataFrame(cases_list)
        if "_id" in df_cases.columns:
            df_cases["_id"] = df_cases["_id"].astype(str)

        dl_col1, dl_col2 = st.columns(2)

        with dl_col1:
            kb_cols = [c for c in ["Case Number", "Owner", "Target Date", "Type", "Comment"] if c in df_cases.columns]
            df_kb = df_cases[kb_cols] if kb_cols else df_cases
            csv_kb = df_kb.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Download Knowledge Base CSV", 
                csv_kb, 
                "kb_export.csv", 
                "text/csv", 
                key="dl_kb_csv"
            )

        with dl_col2:
            qa_cols = [
                "Case Number", "Owner", "Target Date", "Type",
                "QA_Score", "QA_Feedback",
                "QA_SLO_SLA", "QA_Initial_Consecutive_Resp", "QA_Case_Status_Update",
                "QA_Issue_Field_Updated", "QA_Case_Comments_Probing", "QA_Collaborations_Logging",
                "QA_Entitlement_Validation", "QA_Account_Validation", "QA_Case_Routing"
            ]
            available_qa_cols = [col for col in qa_cols if col in df_cases.columns]
            df_qa = df_cases[available_qa_cols] if available_qa_cols else df_cases
            csv_qa = df_qa.to_csv(index=False).encode('utf-8')
            st.download_button(
                "🎯 Download QA Audit Report CSV", 
                csv_qa, 
                "qa_audit_report.csv", 
                "text/csv", 
                key="dl_qa_csv"
            )

    f1, f2, f3 = st.columns(3)
    f_case = f1.text_input("Filter by Case #")
    owners = sorted(list(set(case.get("Owner", "") for case in cases_list if case.get("Owner"))))
    f_owner = f2.selectbox("Filter by Owner", ["All"] + owners)

    f_comment = f3.selectbox(
        "Filter by Comment", 
        ["All", "With Comments Only", "Without Comments Only"], 
        index=0
    )

    filtered_cases = []
    for case in reversed(cases_list):
        matches_case = not f_case or f_case.lower() in str(case.get("Case Number", "")).lower()
        matches_owner = f_owner == "All" or case.get("Owner", "") == f_owner
        
        has_comment = bool(case.get("Comment"))
        if f_comment == "With Comments Only":
            matches_comment = has_comment
        elif f_comment == "Without Comments Only":
            matches_comment = not has_comment
        else:
            matches_comment = True

        if matches_case and matches_owner and matches_comment:
            filtered_cases.append(case)

    if filtered_cases:
        for case in filtered_cases:
            entry_col, gap, action_col = st.columns([3.8, .2, 1.2])
            has_comment = bool(case.get("Comment"))
            has_qa_fb = bool(case.get("QA_Feedback"))
            score_val = case.get('QA_Score', 9)
            qa_status_str = "PASSED" if score_val == 9 else "FAILED"
            
            with entry_col:
                if has_qa_fb:
                    card_class = "card-passed" if qa_status_str == "PASSED" else "card-failed"
                    alert_prefix = "🚨 RED ALERT | " if qa_status_str == "FAILED" else ""
                    st.markdown(f'<div class="{card_class}"><b>{alert_prefix}Case #{case.get("Case Number","")} ({qa_status_str})</b></div>', unsafe_allow_html=True)

                expander_label = f"🚨 RED ALERT | Case #{case.get('Case Number','')} (Requires Attention)" if (has_comment and not has_qa_fb) else f"Case #{case.get('Case Number','')}"
                
                with st.expander(expander_label, expanded=has_comment):
                    st.markdown(f"""
                        **Owner:** {case.get('Owner','')}  
                        **Target Date:** {case.get('Target Date', str(date.today()))}  
                        **Contact Type:** {case.get('Type','')}  
                        **Case Number:** {case.get('Case Number','')}  
                        **QA Score:** `{score_val} / 9` (`{qa_status_str}`)
                        """)
                    
                    if has_comment:
                        st.error(f"💬 **Internal Work Note:** {case.get('Comment')}")
                    
                    if has_qa_fb:
                        st.info(f"📝 **QA Feedback:** {case.get('QA_Feedback')}")

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
                    edit_owner = st.selectbox("Record Assignment Owner", owner_list, index=owner_list.index(case.get("Owner")) if case.get("Owner") in owner_list else 0, key=f"owner_{case['_id']}")
                    
                    try:
                        default_target = date.fromisoformat(case.get("Target Date", str(date.today())))
                    except ValueError:
                        default_target = date.today()
                    edit_target_date = st.date_input("Target Date", value=default_target, key=f"target_date_{case['_id']}")
                    
                    edit_type = st.selectbox("Interaction Channel Profile", c_types, index=c_types.index(case.get("Type")) if case.get("Type") in c_types else 0, key=f"type_{case['_id']}")
                    edit_case_number = st.text_input("Identified Case Identifier", value=case.get("Case Number", ""), key=f"case_num_{case['_id']}")
                    
                    if st.button("Save Record", key=f"save_ed_{case['_id']}"):
                        collection.update_one(
                            {"_id": case["_id"]},
                            {"$set": {
                                "Target Date": str(edit_target_date),
                                "Owner": edit_owner, 
                                "Type": edit_type,
                                "Case Number": edit_case_number
                            }}
                        )
                        st.cache_data.clear()
                        st.success("Case profile properties modified successfully.")
                        st.rerun()

            if t_del:
                with st.container(border=True):
                    st.warning("⚠️ Supervised Destruction Operations Requesting Credentials")
                    del_password = st.text_input("Security Authorization Vector Password", type="password", key=f"pwd_del_{case['_id']}")
                    if st.button("Purge Permanent Record", key=f"conf_del_{case['_id']}"):
                        if del_password == "Password1234":
                            collection.delete_one({"_id": case["_id"]})
                            st.cache_data.clear()
                            st.success("Database entity stripped completely.")
                            st.rerun()
                        else:
                            st.error("Credential confirmation mismatch validation failure.")

            if t_qa:
                with st.container(border=True):
                    st.markdown(f"### 🎯 QA Scorecard | Case #{case.get('Case Number','')}")
                    
                    met_opts = ["Met", "Not Met"]
                    
                    st.markdown("#### 1️⃣ Timely Engagement Standard")
                    q_slo = st.selectbox("SLO/SLA", met_opts, index=met_opts.index(case.get("QA_SLO_SLA", "Met")), key=f"qa_slo_{case['_id']}")
                    q_resp = st.selectbox("Initial and consecutive responses", met_opts, index=met_opts.index(case.get("QA_Initial_Consecutive_Resp", "Met")), key=f"qa_resp_{case['_id']}")
                    q_update = st.selectbox("Case status update", met_opts, index=met_opts.index(case.get("QA_Case_Status_Update", "Met")), key=f"qa_update_{case['_id']}")
                    
                    st.markdown("#### 2️⃣ Documentations")
                    q_issue = st.selectbox("Issue field updated with description, frequency and start date", met_opts, index=met_opts.index(case.get("QA_Issue_Field_Updated", "Met")), key=f"qa_issue_{case['_id']}")
                    q_probing = st.selectbox("Case comments with probing questions and answers (🚨 Non-negotiable)", met_opts, index=met_opts.index(case.get("QA_Case_Comments_Probing", "Met")), key=f"qa_probing_{case['_id']}")
                    q_collab = st.selectbox("Collaborations/Case communication logging (🚨 Non-negotiable)", met_opts, index=met_opts.index(case.get("QA_Collaborations_Logging", "Met")), key=f"qa_collab_{case['_id']}")
                    
                    st.markdown("#### 3️⃣ Validation Process Guidelines")
                    q_entitle = st.selectbox("Entitlement Validation Process (🚨 Non-negotiable)", met_opts, index=met_opts.index(case.get("QA_Entitlement_Validation", "Met")), key=f"qa_entitle_{case['_id']}")
                    q_account = st.selectbox("Account Validation Process", met_opts, index=met_opts.index(case.get("QA_Account_Validation", "Met")), key=f"qa_account_{case['_id']}")
                    
                    st.markdown("#### 4️⃣ Process and Policy")
                    q_routing = st.selectbox("UVA, SDI, Private Case Routing (🚨 Non-negotiable)", met_opts, index=met_opts.index(case.get("QA_Case_Routing", "Met")), key=f"qa_routing_{case['_id']}")
                    
                    all_criteria = [q_slo, q_resp, q_update, q_issue, q_probing, q_collab, q_entitle, q_account, q_routing]
                    non_negotiables = [q_probing, q_collab, q_entitle, q_routing]
                    
                    if any(nn == "Not Met" for nn in non_negotiables):
                        computed_score = 0
                        st.error("🚨 **Score: 0 / 9** (Failed a Non-negotiable criteria)")
                    else:
                        deductions = sum(1 for item in all_criteria if item == "Not Met")
                        computed_score = max(0, 9 - deductions)
                        st.metric("Calculated QA Score", f"{computed_score} / 9")

                    computed_status = "PASSED" if computed_score == 9 else "FAILED"
                    if computed_status == "PASSED":
                        st.success(f"**STATUS:** `{computed_status}`")
                    else:
                        st.error(f"**STATUS:** `{computed_status}`")

                    qa_feedback_str = st.text_area("QA Auditor Feedback", value=case.get("QA_Feedback", ""), key=f"qa_fb_{case['_id']}")
                    
                    if st.button("💾 Save QA Scorecard", key=f"btn_save_qa_{case['_id']}"):
                        collection.update_one(
                            {"_id": case["_id"]},
                            {"$set": {
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
                                "QA_Feedback": qa_feedback_str
                            }}
                        )
                        st.cache_data.clear()
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
        shift_time = st.session_state.calendar_data.get(target_date, {}).get("shift") or \
                     st.session_state.calendar_data.get(date_str, {}).get("shift", "Not Set")
            
        st.write(f"**Shift Time:** `{shift_time}`")

    st.markdown("### 📊 Bulk Entry Log")
    if "bulk_deviation_entries" not in st.session_state:
        st.session_state.bulk_deviation_entries = [{"start": "00:00", "end": "00:00", "duration": "0m", "aux": "", "reason": ""}]

    hdr_cols = st.columns([2, 2, 2, 2, 4])
    hdr_cols[0].markdown("**Start Time (HH:MM)**")
    hdr_cols[1].markdown("**End Time (HH:MM)**")
    hdr_cols[2].markdown("**Duration**")
    hdr_cols[3].markdown("**Aux**")
    hdr_cols[4].markdown("**Reason of Deviation**")

    for idx, entry in enumerate(st.session_state.bulk_deviation_entries):
        row_cols = st.columns([2, 2, 2, 2, 4])
        with row_cols[0]:
            entry["start"] = st.text_input("Start", value=entry["start"], label_visibility="collapsed", key=f"dev_matrix_start_{idx}")
        with row_cols[1]:
            entry["end"] = st.text_input("End", value=entry["end"], label_visibility="collapsed", key=f"dev_matrix_end_{idx}")
        with row_cols[2]:
            entry["duration"] = st.text_input("Duration", value=entry["duration"], label_visibility="collapsed", key=f"dev_matrix_dur_{idx}")
        with row_cols[3]:
            entry["aux"] = st.text_input("Aux", value=entry["aux"], label_visibility="collapsed", key=f"dev_matrix_aux_{idx}")
        with row_cols[4]:
            entry["reason"] = st.text_area("Reason", value=entry["reason"], label_visibility="collapsed", key=f"dev_matrix_reas_{idx}", height=68)

    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 2, 4])
    with ctrl_col1:
        if st.button("➕ Add Row", key="btn_add_dev_matrix_row"):
            st.session_state.bulk_deviation_entries.append({"start": "00:00", "end": "00:00", "duration": "0m", "aux": "", "reason": ""})
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
            for entry in st.session_state.bulk_deviation_entries:
                duration_raw = entry["duration"].lower().strip()
                hrs_match = re.search(r'(\d+)\s*h', duration_raw)
                mins_match = re.search(r'(\d+)\s*m', duration_raw)
                parsed_hrs = int(hrs_match.group(1)) if hrs_match else 0
                parsed_mins = int(mins_match.group(1)) if mins_match else 0
                
                if not hrs_match and not mins_match and duration_raw.isdigit():
                    total_mins = int(duration_raw)
                else:
                    total_mins = (parsed_hrs * 60) + parsed_mins

                save_deviation_to_db({
                    "Date": str(target_date), "Manager": manager, "Name": name,
                    "Shift Time": shift_time, "Start Time": str(entry["start"].strip()),
                    "End Time": str(entry["end"].strip()), "Total Mins": total_mins,
                    "Aux": entry["aux"], "Reason": entry["reason"]
                })
                records_saved += 1
            
            st.success(f"Successfully processed and recorded {records_saved} deviation entities!")
            st.session_state.bulk_deviation_entries = [{"start": "00:00", "end": "00:00", "duration": "0m", "aux": "", "reason": ""}]
            st.rerun()

    st.divider()
    st.subheader("Deviation Report")

    dev_data = fetch_deviations_from_db()
    if dev_data:
        df = pd.DataFrame(dev_data)
        df['Date'] = pd.to_datetime(df['Date']).dt.date
        df = df[df["Name"] != "Jeff Bote"]
        
        # Filter entries for the current day only
        df_today = df[df['Date'] == date.today()]
        filtered_records = df_today.to_dict(orient="records")

        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("Extract Report as CSV", csv, "deviation_report.csv", "text/csv")
        st.write("## Today's Deviation Records")
        
        col_widths = [0.6, 1.2, 1.2, 1.2, 1.2, 1.0, 1.0, 0.8, 0.8, 2.0, 2.4]
        h_cols = st.columns(col_widths)
        headers = ["#", "Date", "Manager", "Name", "Shift Time", "Start Time", "End Time", "Total Mins", "Aux", "Reason", "Actions"]
        for idx, header_title in enumerate(headers):
            h_cols[idx].markdown(f"**{header_title}**")
        st.markdown("---")
        
        total_records = len(filtered_records)
        
        for reverse_idx, dev in enumerate(reversed(filtered_records)):
            entry_number = total_records - reverse_idx
            
            r_cols = st.columns(col_widths)
            r_cols[0].write(f"#{entry_number}")
            r_cols[1].write(str(dev.get('Date', '')))
            r_cols[2].write(str(dev.get('Manager', '')))
            r_cols[3].write(str(dev.get('Name', '')))
            r_cols[4].write(str(dev.get('Shift Time', 'Not Set')))
            r_cols[5].write(str(dev.get('Start Time', '')))
            r_cols[6].write(str(dev.get('End Time', '')))
            r_cols[7].write(str(dev.get('Total Mins', 0)))
            r_cols[8].write(str(dev.get('Aux', 'N/A')))
            r_cols[9].write(str(dev.get('Reason', '')))
            
            with r_cols[10]:
                t_edit = st.toggle("✏️ Edit", key=f"t_edit_{dev['_id']}")
                t_del = st.toggle("🗑️ Del", key=f"t_del_{dev['_id']}")
            
            if t_edit:
                with st.container(border=True):
                    st.markdown(f"#### Edit Properties Frame For Record Line Item #{entry_number}")
                    edit_date = st.date_input("Update Target Date", value=pd.to_datetime(dev.get('Date')).date(), key=f"ed_date_{dev['_id']}")
                    edit_manager = st.text_input("Update Manager", value=dev.get('Manager', ''), key=f"ed_mgr_{dev['_id']}")
                    
                    staff_names = list(st.session_state.staff_roster.keys()) if st.session_state.staff_roster else [dev.get('Name', '')]
                    if dev.get('Name') not in staff_names:
                        staff_names.append(dev.get('Name'))
                        
                    edit_name = st.selectbox("Update Name", staff_names, index=staff_names.index(dev.get('Name')), key=f"ed_name_{dev['_id']}")
                    edit_shift = st.text_input("Update Shift Time", value=dev.get('Shift Time', 'Not Set'), key=f"ed_shift_{dev['_id']}")
                    
                    c1, c2, c3 = st.columns(3)
                    edit_start = c1.text_input("Update Start Time", value=dev.get('Start Time', '00:00'), key=f"ed_start_{dev['_id']}")
                    edit_end = c2.text_input("Update End Time", value=dev.get('End Time', '00:00'), key=f"ed_end_{dev['_id']}")
                    edit_mins = c3.number_input("Update Total Mins", value=int(dev.get('Total Mins', 0)), min_value=0, key=f"ed_mins_{dev['_id']}")
                    
                    edit_aux = st.text_input("Update Aux", value=dev.get('Aux', ''), key=f"ed_aux_{dev['_id']}")
                    edit_reason = st.text_area("Update Reason of Deviation", value=dev.get('Reason', ''), key=f"ed_reas_{dev['_id']}")

                    if st.button("Save Changes", key=f"save_ed_dev_{dev['_id']}"):
                        update_deviation_in_db(dev["_id"], {
                            "Date": str(edit_date), "Manager": edit_manager, "Name": edit_name,
                            "Shift Time": edit_shift, "Start Time": str(edit_start),
                            "End Time": str(edit_end), "Total Mins": edit_mins,
                            "Aux": edit_aux, "Reason": edit_reason
                        })
                        st.success("Deviation record updated completely!")
                        st.rerun()
                        
            if t_del:
                with st.container(border=True):
                    st.warning("⚠️ This action requires supervisor authorization credentials verification validation.")
                    del_password = st.text_input("Enter Admin Password to confirm delete", type="password", key=f"pwd_del_dev_{dev['_id']}")
                    if st.button("Confirm Purge Selection Action", key=f"conf_del_dev_{dev['_id']}"):
                        if del_password == "Password1234":
                            delete_deviation_from_db(dev["_id"])
                            st.success("Deviation record removed.")
                            st.rerun()
                        else:
                            st.error("Incorrect Password. Action denied.")

            st.markdown("---")
    else:
        st.write("No deviation requests found.")

# --- TAB 6: ADMIN PANEL ---
with tab_adm:
    st.markdown("""
        <style>
        .small-font-container input, .small-font-container button, .small-font-container label, 
        .small-font-container div, .small-font-container span, .small-font-container p {
            font-size: 0.85rem !important;
        }
        .small-font-container h3 { font-size: 1.2rem !important; }
        .small-font-container h4 { font-size: 1.05rem !important; }
        .small-font-container h5 { font-size: 0.95rem !important; }
        </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="small-font-container">', unsafe_allow_html=True)

    if not st.session_state.admin_authenticated:
        if st.text_input("Admin Password", type="password", key="a_pass_admin_tab") == "Password1234": 
            st.session_state.admin_authenticated = True
            st.rerun()
    else:
        st.subheader("🔑 System Administrator Workspace")
        pending_count = len(global_pending_requests)

        if pending_count > 0:
            st.info(f"⚠️ You have {pending_count} pending request(s) waiting in the queue below.")
        
        st.divider()

        col_left, space_gap, col_right = st.columns([2, 0.2, 3])
        
        with col_left:
            st.subheader("👥 Roster Management")
            roster = st.session_state.staff_roster
                
            grid_cols = st.columns([2, 2, 2, 2])
            grid_cols[0].write("**Name**")
            grid_cols[1].write("**Nickname**")
            grid_cols[2].write("**Birthday**")
            grid_cols[3].write("**Actions**")

            if roster:
                for name, data in roster.items():
                    r_cols = st.columns([2, 2, 2, 2])
                    r_cols[0].write(name)
                    r_cols[1].write(data.get("nick", ""))
                    
                    bday_val = data.get("bday")
                    if isinstance(bday_val, str):
                        try:
                            bday_val = datetime.strptime(bday_val.split("T")[0], "%Y-%m-%d").date()
                        except ValueError:
                            bday_val = date.today()
                    
                    r_cols[2].write(bday_val.strftime('%B %d') if hasattr(bday_val, 'strftime') else str(bday_val))
                    
                    if r_cols[3].button("Remove", key=f"del_staff_{name}"):
                        delete_staff(name)
                        st.rerun()
            else:
                st.write("*No staff members configured in the roster database.*")
    
            st.markdown("### ➕ Add Multiple Staff")
            if "new_staff_entries" not in st.session_state:
                st.session_state.new_staff_entries = [{"name": "", "nick": "", "bday": date.today(), "rest_days": []}]
            
            for idx, staff in enumerate(st.session_state.new_staff_entries):
                st.markdown(f"#### Staff Member #{idx + 1}")
                inner_c1, inner_c2 = st.columns(2)
                with inner_c1:
                    staff["name"] = st.text_input("Staff Name", value=staff["name"], key=f"multi_staff_name_{idx}")
                    staff["nick"] = st.text_input("Nickname", value=staff["nick"], key=f"multi_staff_nick_{idx}")
                with inner_c2:
                    staff["bday"] = st.date_input("Birthday", value=staff["bday"], min_value=date(1950, 1, 1), key=f"multi_staff_bday_{idx}")
                    staff["rest_days"] = st.multiselect("Select Rest Days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"], default=staff["rest_days"], key=f"multi_staff_rest_{idx}")
            
            col_add, col_save = st.columns(2)
            with col_add:
                if st.button("➕ Add Row", key="btn_add_staff_row"):
                    st.session_state.new_staff_entries.append({"name": "", "nick": "", "bday": date.today(), "rest_days": []})
                    st.rerun()
            with col_save:
                if st.button("💾 Save All Entries", key="btn_save_multi_staff"):
                    added_count = 0
                    for staff in st.session_state.new_staff_entries:
                        if not staff["name"]:
                            continue
                        bday_datetime = datetime(staff["bday"].year, staff["bday"].month, staff["bday"].day)
                        save_staff(staff["name"], {
                            "bday": bday_datetime,
                            "nick": staff["nick"] if staff["nick"] else staff["name"],
                            "rest_days": staff["rest_days"]
                        })
                        added_count += 1
                
                    st.success(f"{added_count} staff record(s) saved successfully!")
                    st.session_state.new_staff_entries = [{"name": "", "nick": "", "bday": date.today(), "rest_days": []}]
                    st.rerun()
    
            st.markdown("---")
            st.subheader("🗓️ Calendar Block Updates")
            config_mode = st.radio("Target Scope Selection:", ["Single Date", "Date Range", "Full Month"], key="radio_cfg_mode")
            
            if config_mode == "Single Date": 
                target_date = st.date_input("Target Date Scope", value=date.today(), key="cfg_d")
                target_dates = [target_date]
                lookup_date_str = str(target_date)
            elif config_mode == "Date Range": 
                dr = st.date_input("Target Date Range", [], key="cfg_dr")
                target_dates = pd.date_range(dr[0], dr[1]).date if len(dr) == 2 else []
                lookup_date_str = str(dr[0]) if len(dr) == 2 else str(date.today())
            else:
                sm = st.date_input("Target Operational Month Selector", value=date.today(), key="cfg_m")
                target_dates = pd.date_range(f"{sm.year}-{sm.month}-01", periods=31).date
                target_dates = [d for d in target_dates if d.month == sm.month]
                lookup_date_str = str(date.today())
            
            if "limits" not in st.session_state:
                st.session_state.limits = {}
            
            target_key = str(st.session_state.get("selected_admin_date", lookup_date_str))
            selected_config = st.session_state.calendar_data.get(target_key, {})
            
            st.session_state.limits["PTO_per_day"] = selected_config.get("PTO_per_day", 1)
            st.session_state.limits["Wellness_per_day"] = selected_config.get("Wellness_per_day", 1)
            
            st.session_state.limits["PTO_per_day"] = st.number_input(
                "Max Allowable PTO Allocations Per Day", 
                min_value=1, 
                value=st.session_state.limits.get("PTO_per_day", 1), 
                key="num_max_pto_per_day"
            )
            st.session_state.limits["Wellness_per_day"] = st.number_input(
                "Max Allowable Wellness Allocations Per Day", 
                min_value=1, 
                value=st.session_state.limits.get("Wellness_per_day", 1), 
                key="num_max_well_per_day"
            )
            
            start_t = st.time_input("Shift Operational Start Window", value=time(9, 0), key="time_shift_start")
            end_t = st.time_input("Shift Operational End Window", value=time(18, 0), key="time_shift_end")
            timezone = "PHT"
            
            shift_display = f"{start_t.strftime('%I:%M %p')} - {end_t.strftime('%I:%M %p')} {timezone}"
            st.write(f"Configured Shift String Representation: **{shift_display}**")
            setup = st.selectbox("Site Production Status Profile", ["PROD - ONSITE", "PROD - WAH", "HOLIDAY"], key="sb_daily_status_setup")
            
            safe_target_dates = target_dates if isinstance(target_dates, (list, tuple)) else []
            base_date = safe_target_dates[0] if len(safe_target_dates) > 0 else date.today()
            unavailable = [r["name"] for r in global_approved_requests if str(r["date"]) == str(base_date)]
            available = [n for n in roster.keys() if n not in unavailable] if roster else []
            
            team_manager = st.selectbox("Team Manager", [""] + available, key="sb_assign_team_manager")
            call = st.multiselect("Call", available, key="ms_assign_call")
            chat = st.multiselect("Chat", available, key="ms_assign_chat")
            mfq = st.multiselect("MFQ", available, key="ms_assign_mfq")
            sme = st.multiselect("SME", available, key="ms_assign_sme")
            
            if st.button("💾 Apply Configuration Profile To Dates", key="btn_save_daily_config"):
                for d in target_dates:
                    st.session_state.calendar_data[d] = {
                        "shift": shift_display, "status": setup,
                        "team_manager": [team_manager] if team_manager else [],
                        "call": call, "chat": chat, "mfq": mfq, "sme": sme,
                        "PTO_per_day": st.session_state.limits["PTO_per_day"],
                        "Wellness_per_day": st.session_state.limits["Wellness_per_day"]
                    }
                serializable_data = {str(k): v for k, v in st.session_state.calendar_data.items()}
                collection.update_one({"type": "calendar_data"}, {"$set": {"data": serializable_data}}, upsert=True)
                st.cache_data.clear()
                st.success("Calendar timeline database parameters successfully updated!")
                st.rerun()
    
        with col_right:
            st.subheader("📥 Approval Center")
            
            def get_all_requests_dataframe(requests_list, select_all_values=False):
                filtered = [r for r in requests_list if r.get("type") in ["Wellness", "PTO"]]
                if not filtered:
                    return pd.DataFrame()
                
                data = {
                    "Select": [select_all_values] * len(filtered),
                    "Date": [r.get("date", "") for r in filtered],
                    "Name": [r.get("name", "") for r in filtered],
                    "Type": [r.get("type", "") for r in filtered],
                    "Status": [r.get("status", "") for r in filtered],
                    "_id": [r.get("_id") for r in filtered]
                }
                df = pd.DataFrame(data)
                df.sort_values(by="Date", inplace=True)
                df.reset_index(drop=True, inplace=True)
                return df

            if "admin_msg" not in st.session_state: 
                st.session_state.admin_msg = None
            if st.session_state.admin_msg:
                msg_type, msg_text = st.session_state.admin_msg
                if msg_type == "success": st.success(msg_text)
                else: st.warning(msg_text)
                if st.button("Clear Processing Session Prompt", key="clear_admin_notif"):
                    st.session_state.admin_msg = None
                    st.rerun()

            select_all = st.checkbox("Select All Pending Requests", key="global_select_all")

            all_requests_df = get_all_requests_dataframe(global_pending_requests, select_all_values=select_all)
            
            if not all_requests_df.empty:
                calculated_height = max(150, min(800, (len(all_requests_df) * 35) + 40))
                
                edited_df = st.data_editor(
                    all_requests_df,
                    hide_index=True,
                    column_config={
                        "Select": st.column_config.CheckboxColumn(default=False),
                        "Date": st.column_config.TextColumn(disabled=True),
                        "Name": st.column_config.TextColumn(disabled=True),
                        "Type": st.column_config.TextColumn(disabled=True),
                        "Status": st.column_config.TextColumn(disabled=True),
                        "_id": None
                    },
                    use_container_width=True,
                    height=calculated_height,
                    key="editor_all_requests"
                )
            else:
                st.write("*No pending Wellness or PTO requests.*")

            if not all_requests_df.empty:
                st.markdown("---")
                btn_col1, btn_col2 = st.columns(2)
                
                def get_selected_ids(base_df, session_key):
                    selected_ids = []
                    current_select_states = base_df["Select"].tolist()
                    
                    if session_key in st.session_state and "edited_rows" in st.session_state[session_key]:
                        edits = st.session_state[session_key]["edited_rows"]
                        for row_idx, edit_dict in edits.items():
                            if "Select" in edit_dict:
                                current_select_states[int(row_idx)] = edit_dict["Select"]
                    
                    for idx, is_selected in enumerate(current_select_states):
                        if is_selected:
                            selected_ids.append(base_df.iloc[idx]["_id"])
                    return selected_ids

                with btn_col1:
                    if st.button("✅ Approve Selected", type="primary", use_container_width=True):
                        target_ids = get_selected_ids(all_requests_df, "editor_all_requests")
                        if target_ids:
                            bulk_update_requests(target_ids, "Approved")
                            st.session_state.admin_msg = ("success", f"Successfully approved {len(target_ids)} requests!")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.warning("Please select at least one request to approve.")
                            
                with btn_col2:
                    if st.button("❌ Deny Selected", type="secondary", use_container_width=True):
                        target_ids = get_selected_ids(all_requests_df, "editor_all_requests")
                        if target_ids:
                            bulk_update_requests(target_ids, "Rejected")
                            st.session_state.admin_msg = ("success", f"Successfully denied {len(target_ids)} requests!")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.warning("Please select at least one request to deny.")
                            
            st.divider()
            st.subheader("Approved History")
            filter_col1, filter_col2 = st.columns(2)
            with filter_col1:
                month_options = {
                    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
                    7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December"
                }
                default_month = st.session_state.get("cal_m", date.today().month)
                selected_month = st.selectbox("Archive Filter Month", options=list(month_options.keys()), format_func=lambda x: month_options[x], index=list(month_options.keys()).index(default_month), key="history_filter_month")
            with filter_col2:
                current_year = date.today().year
                year_options = list(range(current_year - 5, current_year + 6))
                selected_year = st.selectbox("Archive Filter Year", options=year_options, index=year_options.index(current_year), key="history_filter_year")
    
            filtered_history_requests = []
            
            for r in global_approved_requests:
                date_val = r.get('date')
                if isinstance(date_val, str):
                    try:
                        date_val = datetime.strptime(date_val.split("T")[0], "%Y-%m-%d").date()
                    except ValueError:
                        continue
                
                if date_val.month == selected_month and date_val.year == selected_year:
                    if r.get('type') in ["Wellness", "PTO", "Sick Leave"]:
                        r_copy = r.copy()
                        r_copy['parsed_date'] = date_val
                        filtered_history_requests.append(r_copy)
            
            if filtered_history_requests:
                st.markdown("#### Approved Requests Summary")
                history_df = pd.DataFrame(filtered_history_requests)
                history_df.sort_values(by="parsed_date", ascending=True, inplace=True)
                
                if 'type' in history_df.columns:
                    history_df.rename(columns={'type': 'Request Type'}, inplace=True)
                
                for col in ['date', 'name', 'status']:
                    if col in history_df.columns:
                        history_df.rename(columns={col: col.capitalize()}, inplace=True)
                
                columns_to_drop = ['_id', 'parsed_date', 'email', 'viewed']
                history_display_df = history_df.drop(columns=columns_to_drop, errors='ignore')
                
                desired_order = ["Date", "Name", "Request Type", "Status"]
                existing_cols = [c for c in desired_order if c in history_display_df.columns]
                extra_cols = [c for c in history_display_df.columns if c not in desired_order]
                
                history_display_df = history_display_df[existing_cols + extra_cols]
                history_height = (len(history_display_df) * 35) + 45
                
                st.dataframe(
                    history_display_df, 
                    hide_index=True, 
                    use_container_width=True, 
                    height=history_height
                )
            else:
                st.write("*No verified history logs found matching calendar dimensions.*")
    
        st.markdown('</div>', unsafe_allow_html=True)
