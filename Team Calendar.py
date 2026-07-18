from datetime import datetime, time, date, timedelta
import streamlit as st
from pymongo import MongoClient
import calendar
import pandas as pd
import holidays
import sys
from types import ModuleType
import pytz
import re
import io
import altair as alt

# --- DATABASE HELPERS & CONNECTION ---
uri = st.secrets["mongo"]["uri"] 
client = MongoClient(uri)
db = client["my_database"] 
collection = db["my_collection"]

# --- LEAVE LIMITS HELPERS ---

def bulk_update_requests(request_ids, status):
    collection.update_many(
        {"_id": {"$in": request_ids}},
        {"$set": {"status": status}}
    )
    st.cache_data.clear()

def load_data_from_db():
    if "staff_roster" not in st.session_state:
        roster_doc = collection.find_one({"type": "roster_list"})
        st.session_state.staff_roster = roster_doc.get("data", {}) if roster_doc else {}
    
    cal_doc = collection.find_one({"type": "calendar_data"})
    if cal_doc and "data" in cal_doc:
        st.session_state.calendar_data = {
            datetime.strptime(k, "%Y-%m-%d").date(): v 
            for k, v in cal_doc["data"].items()
        }
    else:
        st.session_state.calendar_data = {}

@st.cache_data(ttl=600)
def get_staff_list():
    try:
        cursor = collection.find({"type": "roster_list"})
        return {doc["name"]: {"bday": doc["bday"], "nick": doc["nick"], "rest_days": doc.get("rest_days", [])} for doc in cursor}
    except Exception:
        return {}

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

@st.cache_data(ttl=15)
def get_cases_from_db():
    try:
        return list(collection.find({"type": "case"}))
    except Exception:
        return []

def save_case_to_db(case_data):
    case_data["type"] = "case"
    collection.insert_one(case_data)
    st.cache_data.clear()

@st.cache_data(ttl=15)
def fetch_deviations_from_db():
    try:
        return list(collection.find({"type": "deviation"}))
    except Exception:
        return []

def save_deviation_to_db(data):
    data["type"] = "deviation"
    collection.insert_one(data)
    st.cache_data.clear()

def update_deviation_in_db(id, update_dict):
    collection.update_one({"_id": id}, {"$set": update_dict})
    st.cache_data.clear()

def delete_deviation_from_db(id):
    collection.delete_one({"_id": id})
    st.cache_data.clear()

def delete_request_from_db(req):
    collection.delete_one({"_id": req["_id"]})
    st.cache_data.clear()

def update_request_status_in_db(req, status):
    collection.update_one({"_id": req["_id"]}, {"$set": {"status": status}})
    st.cache_data.clear()

@st.cache_data(ttl=15)
def fetch_approved_requests_from_db():
    return list(collection.find({
        "type": {"$in": ["PTO", "Wellness"]}, 
        "status": "Approved"
    }))

@st.cache_data(ttl=15)
def fetch_pending_requests_from_db():
    return list(collection.find({
        "type": {"$in": ["PTO", "Wellness"]}, 
        "status": "Pending"
    }))

def save_request_to_db(req, request_type):
    req["type"] = request_type
    collection.insert_one(req)
    st.cache_data.clear()

def get_request_limits(req_date):
    calendar_doc = collection.find_one({"type": "calendar_data"})
    selected_config = {}
    
    if calendar_doc:
        selected_config = calendar_doc.get("data", {}).get(
            str(st.session_state.get("selected_admin_date", date.today())),
            {}
        )
    
    st.session_state.limits["PTO_per_day"] = selected_config.get("PTO_per_day", 1)
    st.session_state.limits["Wellness_per_day"] = selected_config.get("Wellness_per_day", 1)
    return st.session_state.limits

def save_masterfile_to_db(df):
    collection.update_one({"type": "masterfile"}, {"$set": {"data": df.to_dict(orient="records")}}, upsert=True)
    st.cache_data.clear()

def send_request_notification(recipient_email, status, request_type, date_val):
    pass

# --- INITIAL CONFIG & STATE ---
st.set_page_config(layout="wide")
st.title("📊 Team Operations Management System (TOMS)")

local_tz = pytz.timezone("Asia/Manila") 
current_date = datetime.now(local_tz).date()

if "pending_requests" not in st.session_state: 
    st.session_state.pending_requests = fetch_pending_requests_from_db()
if "approved_requests" not in st.session_state: 
    approved_requests = fetch_approved_requests_from_db()
if "admin_password" not in st.session_state: st.session_state.admin_password = "Password1234"
if "admin_authenticated" not in st.session_state: st.session_state.admin_authenticated = False
if "staff_roster" not in st.session_state: st.session_state.staff_roster = {}
if "calendar_data" not in st.session_state: st.session_state.calendar_data = {}
if "limits" not in st.session_state:
    st.session_state.limits = {
        "PTO_per_day": 1,
        "Wellness_per_day": 1
    }
if "notifications" not in st.session_state: st.session_state.notifications = []
if "master_data" not in st.session_state: 
    st.session_state.master_data = pd.DataFrame({
        "Category": ["Contact Type", "Issue", "Product Group"], 
        "Values": ["Call,Chat,Email", "Tech,Billing", "Hardware,Soft"]
    })

# --- DATA MIGRATION ---
if "staff_roster" in st.session_state:
    for name, value in st.session_state.staff_roster.items():
        if isinstance(value, dict) and isinstance(value.get("bday"), date) and not isinstance(value.get("bday"), datetime):
            d = value["bday"]
            value["bday"] = datetime(d.year, d.month, d.day)

if "last_tracked_date" not in st.session_state or st.session_state.last_tracked_date != current_date:
    st.session_state.last_tracked_date = current_date
    st.session_state.calendar_data = {} 
    load_data_from_db()

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
tab_cal, tab_req, tab_prod, tab_case, tab_dev, tab_adm = st.tabs([
    "📅 Calendar", "📝 Request", "📈 Productivity Monitoring", "🔍 Case Tracker", "🔀 Deviation", "🔑 Admin"
])

# --- TAB 1: CALENDAR ---
with tab_cal:
    col_main, col_side = st.columns([4, 1])
    
    with col_main:
        c1, c2 = st.columns([1, 1])
        year = c1.selectbox("Year", [2026, 2027, 2028], key="cal_y")
        month = c2.selectbox("Month", range(1, 13), format_func=lambda x: calendar.month_name[x], index=current_date.month - 1, key="cal_m")

    roster_doc = collection.find_one({"type": "roster_list"})
    roster = roster_doc.get("data", {}) if roster_doc else {}

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
        
        st.subheader("Daily View")
        # Automatically defaults to today's date context
        view_date = current_date.date() if hasattr(current_date, 'date') else current_date

        d_data = None
        if hasattr(st.session_state, 'calendar_data') and st.session_state.calendar_data:
            d_data = st.session_state.calendar_data.get(view_date) or st.session_state.calendar_data.get(str(view_date))
        if not d_data:
            # Fallback to direct singular collection query if session mapping state is unpopulated
            d_data = collection.find_one({"type": "calendar_day", "date": str(view_date)})
            if not d_data:
                calendar_doc = collection.find_one({"type": "calendar_data"})
                if calendar_doc:
                    d_data = calendar_doc.get("data", {}).get(str(view_date))
        d_data = d_data or {}
        
        st.markdown(f"### Date: {view_date.strftime('%B %d, %Y')}")
        
        if view_date.weekday() in [5, 6]:
            day_status, day_shift = "REST DAY", "--"
        else:
            day_status = d_data.get('status', 'Not Set')
            day_shift = d_data.get('shift', '--')

        st.markdown(f"**Work Setup:** `{day_status}`")
        st.markdown(f"**Shift:** `{day_shift}`")
        st.divider()

        tm_list = d_data.get('team_manager', [])
        tm_name = tm_list[0] if (isinstance(tm_list, list) and tm_list) else ""
        if tm_name:
            st.write(f"**Team Manager:** {tm_name}")
        
        st.write("**Today's Schedule:**")
        if view_date.weekday() in [5, 6]:
            st.info("📊 **Rest Day** — Weekend Schedule")
            sched_rows = [{"Name": name, "Role": "REST DAY"} for name in roster.keys()]
            if sched_rows:
                sched_df = pd.DataFrame(sched_rows)
                sched_df = sched_df.sort_values(by=["Role", "Name"], ascending=True)
                st.dataframe(sched_df, hide_index=True, use_container_width=True, height=min(1000, max(100, len(sched_df) * 35 + 38)))
            else:
                st.write("*No staff configured in the system.*")
        else:
            roles = ["team_manager", "call", "chat", "mfq", "sme"]
            approved_requests = fetch_approved_requests_from_db()
            sched_rows = []
            for name in roster.keys():
                p_status = [r["type"] for r in approved_requests if str(r["date"]) == str(view_date) and r["name"] == name]
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
                sched_df = pd.DataFrame(sched_rows)
                sched_df = sched_df.sort_values(by=["Role", "Name"], ascending=True)
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
                    approved_requests = fetch_approved_requests_from_db()
                    approved = [r for r in approved_requests if str(r["date"]) == str(d)]
                    away_names = [r['name'] for r in approved]
                    
                    def get_filtered_nicks(full_names):
                        active = [n for n in full_names if n not in away_names]
                        return ", ".join([roster.get(x, {}).get("nick", x) for x in active])
                    
                    req_display = "<br>".join([f"{roster.get(r['name'], {}).get('nick', r['name'])}({r['type']})" for r in approved])
                    
                    grid_data = None
                    if hasattr(st.session_state, 'calendar_data') and st.session_state.calendar_data:
                        grid_data = st.session_state.calendar_data.get(d) or st.session_state.calendar_data.get(str(d))
                    if not grid_data:
                        grid_data = collection.find_one({"type": "calendar_day", "date": str(d)}) or {}
                    
                    if d.weekday() in [5, 6]:
                        content = f"<b>{day}</b><div class='calendar-divider'></div><br><center><b>REST DAY</b></center>"
                    else:
                        content = (f"<b>{day}</b><div class='calendar-divider'></div>"
                                   f"<u>{grid_data.get('status', '-')}</u><div class='calendar-divider'></div>"
                                   f"{grid_data.get('shift', '-')}<div class='calendar-divider'></div>"
                                   f"PTO/Wellness: {req_display}<div class='calendar-divider'></div>"
                                   f"Call: {get_filtered_nicks(grid_data.get('call', []))}<div class='calendar-divider'></div>"
                                   f"Chat: {get_filtered_nicks(grid_data.get('chat', []))}<div class='calendar-divider'></div>"
                                   f"MFQ: {get_filtered_nicks(grid_data.get('mfq', []))}<div class='calendar-divider'></div>"
                                   f"SME: {get_filtered_nicks(grid_data.get('sme', []))}")
                    
                    cols[i].markdown(f'<div class="day-block">{content}</div>', unsafe_allow_html=True)
                else:
                    cols[i].markdown('<div class="day-block day-block-outside"></div>', unsafe_allow_html=True)
                    
    # =====================================================================
    # WEEKLY VIEW GRID AT THE BOTTOM OF THE ENTIRE TAB
    # =====================================================================
    st.markdown("<br>", unsafe_allow_html=True)
    st.divider()
    st.subheader("📆 Weekly Roster")
    
    # Dynamically anchors dropdown options starting from the first day of the top selected calendar month/year
    month_start_date = date(year, month, 1)
    base_sunday = month_start_date - timedelta(days=(month_start_date.weekday() + 1) if month_start_date.weekday() != 6 else 0)
    
    # Generates selection options encompassing all weeks touching the active chosen month view
    sunday_options = [base_sunday + timedelta(weeks=i) for i in range(0, 6)]
    
    # Calculate the Sunday of the current week (today)
    today_date = current_date.date() if hasattr(current_date, 'date') else current_date
    today_sunday = today_date - timedelta(days=(today_date.weekday() + 1) if today_date.weekday() != 6 else 0)
    
    # Determine the index for today's Sunday; fallback to 0 if it's outside the generated month scope
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
    
    approved_requests = fetch_approved_requests_from_db()
    roles = ["team_manager", "call", "chat", "mfq", "sme"]
    
    setup_row = {"Staff Name": "🛠️ WORK SETUP"}
    shift_row = {"Staff Name": "⏰ SHIFT"}
    weekly_tms = []
    
    for day in week_days:
        col_name = day.strftime("%A (%m/%d)")
        
        day_config = None
        if hasattr(st.session_state, 'calendar_data') and st.session_state.calendar_data:
            day_config = st.session_state.calendar_data.get(day) or st.session_state.calendar_data.get(str(day))
        if not day_config:
            day_config = collection.find_one({"type": "calendar_day", "date": str(day)}) or {}
        
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
            
            p_status = [r["type"] for r in approved_requests if str(r["date"]) == str(day) and r["name"] == name]
            if p_status:
                staff_row[col_name] = p_status[0].upper()
            else:
                day_config = None
                if hasattr(st.session_state, 'calendar_data') and st.session_state.calendar_data:
                    day_config = st.session_state.calendar_data.get(day) or st.session_state.calendar_data.get(str(day))
                if not day_config:
                    day_config = collection.find_one({"type": "calendar_day", "date": str(day)}) or {}
                    
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
    st.subheader("PTO/Wellness Request")

    # Initialize a counter in session state to track how many requests to show
    if "request_count" not in st.session_state:
        st.session_state.request_count = 1

    # Fetch roster for name selection
    roster_doc = collection.find_one({"type": "roster_list"})
    staff_data = roster_doc.get("data", {}) if roster_doc else {}
    available_names = list(staff_data.keys()) if staff_data else list(st.session_state.staff_roster.keys())

    with st.form("bulk_request_form"):
        for i in range(st.session_state.request_count):
            cols = st.columns([2, 2, 1])
            with cols[0]:
                st.selectbox("Name", available_names, key=f"name_{i}")
            with cols[1]:
                st.date_input("Date", key=f"date_{i}")
            with cols[2]:
                st.selectbox("Type", ["PTO", "Wellness"], key=f"type_{i}")

        # Button to add another row
        if st.form_submit_button("➕ Add Another Request"):
            st.session_state.request_count += 1
            st.rerun()

        # Final Submit Button
        if st.form_submit_button("✅ Submit All Requests"):
            for i in range(st.session_state.request_count):
                name = st.session_state[f"name_{i}"]
                req_date = st.session_state[f"date_{i}"]
                req_type = st.session_state[f"type_{i}"]
                
                limits = get_request_limits(req_date)
                count_on_date = collection.count_documents({"type": req_type, "date": str(req_date), "status": {"$in": ["Pending", "Approved"]}})
                is_already_requested = collection.count_documents({"name": name, "date": str(req_date), "status": {"$in": ["Pending", "Approved"]}}) > 0
                
                if is_already_requested:
                    st.warning(f"⚠️ A request for {name} on {req_date} already exists.")
                    continue
                
                limit_value = limits["PTO_per_day"] if req_type == "PTO" else limits["Wellness_per_day"]
                if count_on_date >= limit_value:
                    st.error(f"❌ Limit reached for {req_type} on {req_date}.")
                else:
                    new_req = {"name": name, "date": str(req_date), "type": req_type, "status": "Pending", "email": "", "viewed": False}
                    save_request_to_db(new_req, req_type)
                    st.session_state.pending_requests.append(new_req)
            
            st.success("All requests processed!")
            st.session_state.request_count = 1 
            st.rerun()

    # --- Pending Requests Overview ---
    st.subheader("Pending Requests Overview")    
    all_pending = fetch_pending_requests_from_db()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### 🌿 Wellness Pending")
        wellness_reqs = [r for r in all_pending if r['type'] == 'Wellness']
        if wellness_reqs:
            df_w = pd.DataFrame(wellness_reqs)[["name", "date"]]
            df_w.columns = ["Name", "Date"]
            st.dataframe(df_w, hide_index=True, use_container_width=True)
    with c2:
        st.markdown("### ✈️ PTO Pending")
        pto_reqs = [r for r in all_pending if r['type'] == 'PTO']
        if pto_reqs:
            df_p = pd.DataFrame(pto_reqs)[["name", "date"]]
            df_p.columns = ["Name", "Date"]
            st.dataframe(df_p, hide_index=True, use_container_width=True)
            
    st.divider()
    
    # --- Approved History ---
    st.subheader("Approved History")
    f_c1, f_c2 = st.columns(2)
    
    # Define month names using the calendar module
    import calendar
    month_names = list(calendar.month_name)[1:]
    
    # Selectbox displays month names; maps to 1-12 integer for logic
    selected_month_name = f_c1.selectbox("Month", month_names, index=current_date.month-1, key="history_month_select")
    f_m = month_names.index(selected_month_name) + 1
    
    f_y = f_c2.number_input("Year", value=current_date.year, key="history_year_select")
    
    app_reqs = fetch_approved_requests_from_db()
    
    # Filter logic: matches integer month and year
    filtered_app = [r for r in app_reqs if int(r['date'].split('-')[1]) == f_m and int(r['date'].split('-')[0]) == f_y]
    
    if filtered_app: 
        # Create display dataframe and rename columns
        df_display = pd.DataFrame(filtered_app)[['name', 'date', 'type']]
        df_display.columns = ["Name", "Date", "Type"]
        # Index hidden and container width applied
        st.dataframe(df_display, hide_index=True, use_container_width=True)
    else: 
        st.write("No records found.")
        
# --- TAB 3: PRODUCTIVITY MONITORING ---
with tab_prod:
    st.subheader("📈 Productivity Monitoring")
    cases = list(collection.find({"type": "case"}))

    if not cases:
        st.info("No case records found.")
    else:
        df = pd.DataFrame(cases)
        if "_id" in df.columns:
            df = df.drop(columns=["_id"])

        required_cols = ["Date", "Owner", "Type", "Issue", "Product Group"]
        for col in required_cols:
            if col not in df.columns:
                df[col] = "Unknown"

        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"])
        df["Month"] = df["Date"].dt.month
        df["Year"] = df["Date"].dt.year
        df["Day"] = df["Date"].dt.date

        st.markdown("## Monthly Productivity")
        col1, col2 = st.columns(2)
        years = sorted(df["Year"].dropna().unique())
        selected_year = col1.selectbox("Year", years, key="prod_year")
        selected_month = col2.selectbox("Month", range(1, 13), format_func=lambda x: calendar.month_name[x], index=current_date.month - 1, key="prod_monitor_month")

        monthly_df = df[(df["Year"] == selected_year) & (df["Month"] == selected_month)]

        if not monthly_df.empty:
            monthly_summary = monthly_df.groupby(["Owner", "Type"]).size().unstack(fill_value=0)
            monthly_summary["Total Cases"] = monthly_summary.sum(axis=1)
            m_height = min(1000, max(100, len(monthly_summary) * 35 + 38))
            
            # Reset index then hide for clean display
            st.dataframe(monthly_summary.reset_index().style.hide(axis="index"), use_container_width=True, height=m_height)
        else:
            st.info("No cases found for selected month.")

        st.divider()

        st.markdown("## Daily Productivity")
        selected_day = st.date_input("Select Day", value=date.today(), key="prod_day")
        daily_df = df[df["Day"] == selected_day]

        if not daily_df.empty:
            daily_summary = daily_df.groupby(["Owner", "Type"]).size().unstack(fill_value=0)
            daily_summary["Total Cases"] = daily_summary.sum(axis=1)
            d_height = min(1000, max(100, len(daily_summary) * 35 + 38))
            
            # Reset index then hide for clean display
            st.dataframe(daily_summary.reset_index().style.hide(axis="index"), use_container_width=True, height=d_height)
        else:
            st.info("No cases found for selected day.")

        st.divider()

        st.markdown("## Overall Issue Analysis")
        overall_issue = df["Issue"].value_counts().reset_index()
        overall_issue.columns = ["Issue", "Count"]

        issue_chart = alt.Chart(overall_issue).mark_bar().encode(
            x=alt.X("Issue", axis=alt.Axis(labelAngle=-45)),
            y="Count"
        )
        st.altair_chart(issue_chart, use_container_width=True)
        
        i_height = min(1000, max(100, len(overall_issue) * 35 + 38))
        # Hide index from Styler object
        st.dataframe(overall_issue.style.hide(axis="index"), use_container_width=True, height=i_height)

        st.divider()

        st.markdown("## Overall Product Analysis")
        overall_product = df["Product Group"].value_counts().reset_index()
        overall_product.columns = ["Product Group", "Count"]

        product_chart = alt.Chart(overall_product).mark_bar().encode(
            x=alt.X("Product Group", axis=alt.Axis(labelAngle=-45)),
            y="Count"
        )
        st.altair_chart(product_chart, use_container_width=True)

        p_height = min(1000, max(100, len(overall_product) * 35 + 38))
        # Hide index from Styler object
        st.dataframe(overall_product.style.hide(axis="index"), use_container_width=True, height=p_height)
        st.divider()

# --- TAB 4: CASE TRACKER ---
with tab_case:
    st.subheader("Log New Case")
    cases_list = get_cases_from_db() 

    masterfile_doc = collection.find_one({"type": "masterfile"})
    if masterfile_doc and "data" in masterfile_doc:
        master_df = pd.DataFrame(masterfile_doc["data"])
    else:
        master_df = pd.DataFrame({
            "Category": ["Contact Type", "Issue", "Product Group"],
            "Values": ["Call,Chat,Email", "Tech,Billing", "Hardware,Soft"]
        })

    c_types = master_df.loc[master_df["Category"] == "Contact Type", "Values"].iloc[0].split(",")
    issues = master_df.loc[master_df["Category"] == "Issue", "Values"].iloc[0].split(",")
    prods = master_df.loc[master_df["Category"] == "Product Group", "Values"].iloc[0].split(",")

    roster_doc = collection.find_one({"type": "roster_list"})
    staff_data = roster_doc.get("data", {}) if roster_doc else {}
    owner_list = sorted(list(staff_data.keys()))
    if not owner_list:
        owner_list = ["Unknown"]

    c1, c2 = st.columns(2)
    c_type = c1.selectbox("Contact Type", c_types, key="case_form_type")
    case_owner = c2.selectbox("Owner", owner_list, key="case_form_owner")
    case_number = c1.text_input("Case Number", key="case_form_case_number")
    issue = c1.selectbox("Issue", issues, key="case_form_issue")
    prod = c2.selectbox("Product Group", prods, key="case_form_product")
    desc = st.text_area("Issue Description", key="case_form_desc")
    steps = st.text_area("Steps Taken", key="case_form_steps")
    uploaded_file = st.file_uploader("Upload Screenshot", type=["png", "jpg", "jpeg"])
    status = st.selectbox("Status", ["Resolved", "Pending/Monitoring", "Routed"], key="case_form_status")

    extra = ""
    if status == "Pending/Monitoring":
        extra = st.text_input("Pending/Monitoring Reason", key="case_form_pending")
    elif status == "Routed":
        extra = st.text_input("Queue Destination", key="case_form_routed")

    if st.button("Log Case"):
        new_case = {
            "Date": str(date.today()),
            "Owner": case_owner,
            "Type": c_type,
            "Case Number": case_number,
            "Issue": issue,
            "Product Group": prod,
            "Desc": desc,
            "Steps": steps,
            "Has_Screenshot": uploaded_file is not None,
            "Screenshot": uploaded_file.getvalue() if uploaded_file else None,
            "Status": status,
            "Extra": extra
        }
        save_case_to_db(new_case)
        for key in list(st.session_state.keys()):
            if key.startswith("case_form_"):
                del st.session_state[key]
        st.success("Case logged to database successfully!")
        st.rerun()

    st.divider()
    st.subheader("Knowledge Base")

    if cases_list:
        df_cases = pd.DataFrame(cases_list)
        csv = df_cases.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Knowledge Base CSV", csv, "kb_export.csv", "text/csv")

    f1, f2, f3, f4 = st.columns(4)
    f_issue = f1.multiselect("Filter by Issue", issues)
    f_prod = f2.multiselect("Filter by Product Group", prods)
    f_case = f3.text_input("Filter by Case #")
    owners = sorted(list(set(case.get("Owner", "") for case in cases_list if case.get("Owner"))))
    f_owner = f4.selectbox("Filter by Owner", ["All"] + owners)

    filtered_cases = []
    for case in reversed(cases_list):
        matches_issue = not f_issue or case.get("Issue") in f_issue
        matches_prod = not f_prod or case.get("Product Group") in f_prod
        matches_case = not f_case or f_case.lower() in str(case.get("Case Number", "")).lower()
        matches_owner = f_owner == "All" or case.get("Owner", "") == f_owner

        if matches_issue and matches_prod and matches_case and matches_owner:
            filtered_cases.append(case)

    if filtered_cases:
        for case in filtered_cases:
            entry_col, action_col = st.columns([9, 1])
            with entry_col:
                with st.expander(f"Case #{case.get('Case Number','')} | {case.get('Desc','')[:80]}", expanded=False):
                    st.markdown(f"""
                        **Owner:** {case.get('Owner','')}
                        **Date:** {case.get('Date','')}
                        **Contact Type:** {case.get('Type','')}
                        **Case Number:** {case.get('Case Number','')}
                        **Status:** {case.get('Status','')}
                        **Issue:** {case.get('Issue','')}
                        **Product Group:** {case.get('Product Group','')}
                        """)
                    st.markdown("### Issue Description")
                    st.write(case.get("Desc", ""))
                    st.markdown("### Steps Taken")
                    st.write(case.get("Steps", ""))
                    if case.get("Extra"):
                        st.markdown("### Additional Information")
                        st.write(case.get("Extra", ""))
                    if case.get("Has_Screenshot") and case.get("Screenshot"):
                        st.image(case["Screenshot"], caption="Attached Screenshot", use_container_width=True)
                    elif case.get("Has_Screenshot"):
                        st.caption("📎 Screenshot attached to this record.")

            with action_col:
                pop = st.popover("⋮", help="Actions")
                with pop:
                    action = st.selectbox("Action", ["None", "Edit", "Delete"], key=f"action_{case['_id']}")

            if action == "Edit":
                with st.container():
                    st.markdown(f"### Editing Case #{case.get('Case Number','')}")
                    edit_date = st.text_input("Date", value=case.get("Date", ""), key=f"date_{case['_id']}")
                    edit_owner = st.selectbox("Owner", owner_list, index=owner_list.index(case.get("Owner")) if case.get("Owner") in owner_list else 0, key=f"owner_{case['_id']}")
                    edit_type = st.selectbox("Contact Type", c_types, index=c_types.index(case.get("Type")) if case.get("Type") in c_types else 0, key=f"type_{case['_id']}")
                    edit_case_number = st.text_input("Case Number", value=case.get("Case Number", ""), key=f"case_num_{case['_id']}")
                    edit_issue = st.selectbox("Issue", issues, index=issues.index(case.get("Issue")) if case.get("Issue") in issues else 0, key=f"issue_{case['_id']}")
                    edit_product = st.selectbox("Product Group", prods, index=prods.index(case.get("Product Group")) if case.get("Product Group") in prods else 0, key=f"prod_{case['_id']}")
                    
                    status_options = ["Resolved", "Pending/Monitoring", "Routed"]
                    current_status = case.get("Status", "Resolved")
                    edit_status = st.selectbox("Status", status_options, index=status_options.index(current_status) if current_status in status_options else 0, key=f"status_{case['_id']}")
                    edit_extra = st.text_input("Extra Information", value=case.get("Extra", ""), key=f"extra_{case['_id']}")
                    edit_desc = st.text_area("Issue Description", value=case.get("Desc", ""), key=f"ed_desc_{case['_id']}")
                    edit_steps = st.text_area("Steps Taken", value=case.get("Steps", ""), key=f"ed_step_{case['_id']}")

                    save_col, cancel_col = st.columns(2)
                    with save_col:
                        if st.button("Save Changes", key=f"save_ed_{case['_id']}"):
                            collection.update_one(
                                {"_id": case["_id"]},
                                {"$set": {
                                    "Date": edit_date, "Owner": edit_owner, "Type": edit_type,
                                    "Case Number": edit_case_number, "Issue": edit_issue,
                                    "Product Group": edit_product, "Status": edit_status,
                                    "Extra": edit_extra, "Desc": edit_desc, "Steps": edit_steps
                                }}
                            )
                            st.cache_data.clear()
                            st.success("Case updated successfully!")
                            st.rerun()
                    with cancel_col:
                        if st.button("Cancel", key=f"cancel_edit_{case['_id']}"):
                            if f"action_{case['_id']}" in st.session_state:
                                st.session_state[f"action_{case['_id']}"] = "None"
                            st.rerun()

            elif action == "Delete":
                st.warning("⚠️ Supervisor authorization required.")
                del_password = st.text_input("Enter Admin Password", type="password", key=f"pwd_del_{case['_id']}")
                del_col, cancel_col = st.columns(2)
                with del_col:
                    if st.button("Confirm Delete", key=f"conf_del_{case['_id']}"):
                        if del_password == "Password1234":
                            collection.delete_one({"_id": case["_id"]})
                            st.cache_data.clear()
                            st.success("Case deleted successfully.")
                            st.rerun()
                        else:
                            st.error("Incorrect Password.")
                with cancel_col:
                    if st.button("Cancel", key=f"cancel_del_w_{case['_id']}"):
                        if f"action_{case['_id']}" in st.session_state:
                            st.session_state[f"action_{case['_id']}"] = "None"
                        st.rerun()
            st.divider()
    else:
        st.info("No cases match the selected filters.")

# --- TAB 5: DEVIATION ---
with tab_dev:
    st.subheader("Submit Deviation Request")
    
    with st.form("deviation_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            target_date = st.date_input("Target Date", value=date.today())
            manager = st.text_input("Manager", value="Jeff Bote")
            
            roster_doc = collection.find_one({"type": "roster_list"})
            staff_data = roster_doc.get("data", {}) if roster_doc else {}
            available_names = list(staff_data.keys()) if staff_data else list(st.session_state.staff_roster.keys())
            name = st.selectbox("Name", available_names, key="dev_name_box")
            
            calendar_doc = collection.find_one({"type": "calendar_data"})
            if calendar_doc:
                date_str = str(target_date)
                shift_time = calendar_doc.get("data", {}).get(date_str, {}).get("shift") or \
                             st.session_state.calendar_data.get(target_date, {}).get("shift", "Not Set")
            else:
                shift_time = st.session_state.calendar_data.get(target_date, {}).get("shift", "Not Set")
                
            st.write(f"**Shift Time:** {shift_time}")
            
        with col2:
            start_time_input = st.text_input("Start Time (HH:MM)", value="00:00", key="manual_start_time")
            end_time_input = st.text_input("End Time (HH:MM)", value="00:00", key="manual_end_time")
            duration_input = st.text_input("Duration (e.g., 1h 15m or 45m)", value="0m", key="manual_duration")
            
            start_time = start_time_input.strip()
            end_time = end_time_input.strip()
            duration_raw = duration_input.lower().strip()
            
            hrs_match = re.search(r'(\d+)\s*h', duration_raw)
            mins_match = re.search(r'(\d+)\s*m', duration_raw)
            parsed_hrs = int(hrs_match.group(1)) if hrs_match else 0
            parsed_mins = int(mins_match.group(1)) if mins_match else 0
            
            if not hrs_match and not mins_match and duration_raw.isdigit():
                total_mins = int(duration_raw)
            else:
                total_mins = (parsed_hrs * 60) + parsed_mins
                
            aux = st.text_input("Aux")
            reason = st.text_area("Reason of Deviation")
            
        if st.form_submit_button("Submit Deviation Request"):
            save_deviation_to_db({
                "Date": str(target_date), "Manager": manager, "Name": name,
                "Shift Time": shift_time, "Start Time": str(start_time),
                "End Time": str(end_time), "Total Mins": total_mins,
                "Aux": aux, "Reason": reason
            })
            st.success("Deviation request saved to database!")
            st.rerun()

    st.divider()
    st.subheader("Deviation Request Report")
    
    with st.expander("Filter Report"):
        f_col1, f_col2, f_col3 = st.columns(3)
        filter_month = f_col1.selectbox("Month", range(1, 13), index=date.today().month-1, key="dev_f_month")
        filter_year = f_col2.number_input("Year", value=date.today().year, key="dev_f_year")
        filter_date = f_col3.date_input("Specific Date (Optional)", value=None, key="dev_f_date")
        apply_filter = st.button("Apply Filter")

    dev_data = fetch_deviations_from_db()
    if dev_data:
        df = pd.DataFrame(dev_data)
        df['Date'] = pd.to_datetime(df['Date']).dt.date
        
        if apply_filter:
            if filter_date:
                df = df[df['Date'] == filter_date]
            else:
                df = df[(df['Date'].apply(lambda x: x.month) == filter_month) & (df['Date'].apply(lambda x: x.year) == filter_year)]
        
        filtered_records = df.to_dict(orient="records")
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("Extract Report as CSV", csv, "deviation_report.csv", "text/csv")
        st.write("## Deviation Records")
        
        col_widths = [1.2, 1.2, 1.2, 1.2, 1.0, 1.0, 0.8, 0.8, 2.0, 1.0]
        h_cols = st.columns(col_widths)
        headers = ["Date", "Manager", "Name", "Shift Time", "Start Time", "End Time", "Total Mins", "Aux", "Reason of Deviation", "Action"]
        for idx, header_title in enumerate(headers):
            h_cols[idx].markdown(f"**{header_title}**")
        st.markdown("---")
        
        for dev in reversed(filtered_records):
            r_cols = st.columns(col_widths)
            r_cols[0].write(str(dev.get('Date', '')))
            r_cols[1].write(str(dev.get('Manager', '')))
            r_cols[2].write(str(dev.get('Name', '')))
            r_cols[3].write(str(dev.get('Shift Time', 'Not Set')))
            r_cols[4].write(str(dev.get('Start Time', '')))
            r_cols[5].write(str(dev.get('End Time', '')))
            r_cols[6].write(str(dev.get('Total Mins', 0)))
            r_cols[7].write(str(dev.get('Aux', 'N/A')))
            r_cols[8].write(str(dev.get('Reason', '')))
            
            with r_cols[9]:
                options_menu = st.popover("⋮", help="Options")
                with options_menu:
                    action = st.radio("Action", ["View", "Edit", "Delete"], key=f"act_dev_{dev['_id']}", horizontal=False)
            
            if action == "Edit":
                with st.container():
                    st.markdown(f"#### Edit Deviation Request for {dev.get('Name', '')}")
                    edit_date = st.date_input("Update Target Date", value=pd.to_datetime(dev.get('Date')).date(), key=f"ed_date_{dev['_id']}")
                    edit_manager = st.text_input("Update Manager", value=dev.get('Manager', ''), key=f"ed_mgr_{dev['_id']}")
                    
                    roster_doc = collection.find_one({"type": "roster_list"})
                    staff_names = list(roster_doc.get("data", {}).keys()) if roster_doc else [dev.get('Name', '')]
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

                    save_col, cancel_col = st.columns(2)
                    with save_col:
                        if st.button("Save Changes", key=f"save_ed_dev_{dev['_id']}"):
                            update_deviation_in_db(dev["_id"], {
                                "Date": str(edit_date), "Manager": edit_manager, "Name": edit_name,
                                "Shift Time": edit_shift, "Start Time": str(edit_start),
                                "End Time": str(edit_end), "Total Mins": edit_mins,
                                "Aux": edit_aux, "Reason": edit_reason
                            })
                            st.success("Deviation record updated completely!")
                            st.rerun()
                    with cancel_col:
                        if st.button("Cancel", key=f"cancel_ed_dev_{dev['_id']}"):
                            if f"act_dev_{dev['_id']}" in st.session_state:
                                st.session_state[f"act_dev_{dev['_id']}"] = "View"
                            st.rerun()
                      
            elif action == "Delete":
                with st.container():
                    st.warning("⚠️ This action requires supervisor authorization.")
                    del_password = st.text_input("Enter Admin Password to confirm delete", type="password", key=f"pwd_del_dev_{dev['_id']}")
                    del_col, cancel_del_col = st.columns(2)
                    with del_col:
                        if st.button("Confirm Delete", key=f"conf_del_dev_{dev['_id']}"):
                            if del_password == "Password1234":
                                delete_deviation_from_db(dev["_id"])
                                st.success("Deviation record removed.")
                                st.rerun()
                            else:
                                st.error("Incorrect Password. Action denied.")
                    with cancel_del_col:
                        if st.button("Cancel", key=f"cancel_del_dev_{dev['_id']}"):
                            if f"act_dev_{dev['_id']}" in st.session_state:
                                st.session_state[f"act_dev_{dev['_id']}"] = "View"
                            st.rerun()
            st.markdown("---")
    else:
        st.write("No deviation requests found.")

# --- TAB 6: ADMIN PANEL ---
with tab_adm:
    if not st.session_state.admin_authenticated:
        if st.text_input("Admin Password", type="password", key="a_pass_admin_tab") == "Password1234": 
            st.session_state.admin_authenticated = True
            st.rerun()
    else:
        st.subheader("Admin Panel")
        pending_count = len(fetch_pending_requests_from_db())

        if pending_count > 0:
            st.info(f"⚠️ You have {pending_count} pending request(s).")
        
        if st.button("Save Admin Changes", key="btn_top_admin_save"):
            st.success("Admin configuration saved.")
        st.divider()

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Roster Management")
            roster_doc = collection.find_one({"type": "roster_list"})
            roster = roster_doc.get("data", {}) if roster_doc else {}
                
            c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
            c1.write("**Name**")
            c2.write("**Nickname**")
            c3.write("**Birthday**")
            c4.write("**Actions**")
            st.divider()
    
            if roster:
                for name, data in roster.items():
                    c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
                    c1.write(name)
                    c2.write(data.get("nick", ""))
                    
                    bday_val = data.get("bday")
                    if isinstance(bday_val, str):
                        try:
                            bday_val = datetime.strptime(bday_val.split("T")[0], "%Y-%m-%d").date()
                        except ValueError:
                            bday_val = date.today()
                    
                    c3.write(bday_val.strftime('%B %d') if hasattr(bday_val, 'strftime') else str(bday_val))
                    
                    if c4.button("Remove", key=f"del_staff_{name}"):
                        delete_staff(name)
                        st.rerun()
            else:
                st.write("*No staff members configured in the roster database.*")
    
            st.markdown("### Add Multiple Staff")
            if "new_staff_entries" not in st.session_state:
                st.session_state.new_staff_entries = [{"name": "", "nick": "", "bday": date.today(), "rest_days": []}]
            
            for idx, staff in enumerate(st.session_state.new_staff_entries):
                st.markdown(f"#### Staff #{idx + 1}")
                c1, c2 = st.columns(2)
                with c1:
                    staff["name"] = st.text_input("Staff Name", value=staff["name"], key=f"multi_staff_name_{idx}")
                    staff["nick"] = st.text_input("Nickname", value=staff["nick"], key=f"multi_staff_nick_{idx}")
                with c2:
                    staff["bday"] = st.date_input("Birthday", value=staff["bday"], min_value=date(1950, 1, 1), key=f"multi_staff_bday_{idx}")
                    staff["rest_days"] = st.multiselect("Select Rest Days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"], default=staff["rest_days"], key=f"multi_staff_rest_{idx}")
                st.divider()
            
            col_add, col_save = st.columns(2)
            with col_add:
                if st.button("➕ Add Another Staff", key="btn_add_staff_row"):
                    st.session_state.new_staff_entries.append({"name": "", "nick": "", "bday": date.today(), "rest_days": []})
                    st.rerun()
            with col_save:
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
            st.divider()
    
            st.subheader("Configuration")
            st.session_state.selected_admin_date = st.date_input("Select Date to View/Edit", date.today(), key="cfg_view_edit_date")

            calendar_doc = collection.find_one({"type": "calendar_data"})
            if calendar_doc:
                selected_config = calendar_doc.get("data", {}).get(str(st.session_state.selected_admin_date), {})
                st.session_state.limits["PTO_per_day"] = selected_config.get("PTO_per_day", 1)
                st.session_state.limits["Wellness_per_day"] = selected_config.get("Wellness_per_day", 1)
    
            st.markdown("---")
            st.subheader("Important Notifications")
            target_d = st.date_input("Target Date", key="config_target_date")
            admin_sender_email = st.text_input("Your Work Email (Sender Address)", key="cfg_admin_sender_email")
            
            new_notif = st.text_input("Add New System Notification", key="input_new_sys_notif")
            if st.button("Post Notification", key="btn_post_sys_notif"): 
                if new_notif:
                    if "notifications" not in st.session_state:
                        st.session_state.notifications = []
                    st.session_state.notifications.append(new_notif)
                    st.success("Notification posted!")
                    st.rerun()
            
            st.subheader("Daily Config")
            config_mode = st.radio("Apply to:", ["Single Date", "Date Range", "Full Month"], key="radio_cfg_mode")
            
            if config_mode == "Single Date": 
                target_dates = [st.date_input("Date", key="cfg_d")]
            elif config_mode == "Date Range": 
                dr = st.date_input("Range", [], key="cfg_dr")
                target_dates = pd.date_range(dr[0], dr[1]).date if len(dr) == 2 else []
            else:
                sm = st.date_input("Month", value=date.today(), key="cfg_m")
                target_dates = pd.date_range(f"{sm.year}-{sm.month}-01", periods=31).date
                target_dates = [d for d in target_dates if d.month == sm.month]
    
            st.session_state.limits["PTO_per_day"] = st.number_input("Max PTO Per Day", min_value=1, value=st.session_state.limits.get("PTO_per_day", 1), key="num_max_pto_per_day")
            st.session_state.limits["Wellness_per_day"] = st.number_input("Max Wellness Per Day", min_value=1, value=st.session_state.limits.get("Wellness_per_day", 1), key="num_max_well_per_day")

            start_t = st.time_input("Shift Start", value=time(9, 0), key="time_shift_start")
            end_t = st.time_input("Shift End", value=time(18, 0), key="time_shift_end")
            timezone = "PHT"
            
            shift_display = f"{start_t.strftime('%I:%M %p')} - {end_t.strftime('%I:%M %p')} {timezone}"
            st.write(f"Selected Shift: **{shift_display}**")
            setup = st.selectbox("Status", ["PROD - ONSITE", "PROD - WAH", "HOLIDAY"], key="sb_daily_status_setup")
            
            safe_target_dates = target_dates if isinstance(target_dates, (list, tuple)) else []
            base_date = safe_target_dates[0] if len(safe_target_dates) > 0 else date.today()
            approved_requests = fetch_approved_requests_from_db()   
            unavailable = [r["name"] for r in approved_requests if str(r["date"]) == str(base_date)]
            available = [n for n in roster.keys() if n not in unavailable] if roster else []
            
            team_manager = st.selectbox("Assign Team Manager", [""] + available, key="sb_assign_team_manager")
            call = st.multiselect("Assign Call", available, key="ms_assign_call")
            chat = st.multiselect("Assign Chat", available, key="ms_assign_chat")
            mfq = st.multiselect("Assign MFQ", available, key="ms_assign_mfq")
            sme = st.multiselect("Assign SME", available, key="ms_assign_sme")
            
            if st.button("Save Config", key="btn_save_daily_config"):
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
                st.success("Configuration saved to database!")
                st.rerun()
                
        with col2:
            st.subheader("Approval Center")
            all_pending_requests = fetch_pending_requests_from_db()

            if "admin_msg" not in st.session_state: 
                st.session_state.admin_msg = None
            if st.session_state.admin_msg:
                msg_type, msg_text = st.session_state.admin_msg
                if msg_type == "success": st.success(msg_text)
                else: st.warning(msg_text)
                if st.button("Clear Notification", key="clear_admin_notif"):
                    st.session_state.admin_msg = None
                    st.rerun()

            st.markdown("### 🌿 Wellness Requests")
            wellness_pending = [r for r in all_pending_requests if r.get("type") == "Wellness"]
            wellness_selected = []
            
            if wellness_pending:
                select_all_wellness = st.checkbox("Select All Wellness", key="select_all_wellness")
                for req in wellness_pending:
                    req_id = str(req["_id"])
                    c1, c2 = st.columns([1, 8])
                    with c1:
                        checked = st.checkbox("", value=select_all_wellness, key=f"wellness_chk_{req_id}")
                    with c2:
                        st.write(f"{req['name']} | {req['date']} | {req['status']}")
                    if checked:
                        wellness_selected.append(req["_id"])
            
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Approve Selected Wellness", key="approve_wellness"):
                        if wellness_selected:
                            bulk_update_requests(wellness_selected, "Approved")
                            st.success("Selected wellness requests approved.")
                            st.rerun()
                with c2:
                    if st.button("❌ Deny Selected Wellness", key="deny_wellness"):
                        if wellness_selected:
                            bulk_update_requests(wellness_selected, "Rejected")
                            st.success("Selected wellness requests denied.")
                            st.rerun()
            else:
                st.write("No pending Wellness requests.")

            st.markdown("### ✈️ PTO Requests")
            pto_pending = [r for r in all_pending_requests if r.get("type") == "PTO"]
            pto_selected = []

            if pto_pending:
                select_all_pto = st.checkbox("Select All PTO", key="select_all_pto")
                for req in pto_pending:
                    req_id = str(req["_id"])
                    c1, c2 = st.columns([1, 8])
                    with c1:
                        checked = st.checkbox("", value=select_all_pto, key=f"pto_chk_{req_id}")
                    with c2:
                        st.write(f"{req['name']} | {req['date']} | {req['status']}")
                    if checked:
                        pto_selected.append(req["_id"])

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Approve Selected PTO", key="approve_pto"):
                        if pto_selected:
                            bulk_update_requests(pto_selected, "Approved")
                            st.success("Selected PTO requests approved.")
                            st.rerun()
                with c2:
                    if st.button("❌ Deny Selected PTO", key="deny_pto"):
                        if pto_selected:
                            bulk_update_requests(pto_selected, "Rejected")
                            st.success("Selected PTO requests denied.")
                            st.rerun()
            else:
                st.write("No pending PTO requests.")

            st.divider()
            st.subheader("✅ Approved History")
            
            filter_col1, filter_col2 = st.columns(2)
            with filter_col1:
                month_options = {
                    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
                    7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December"
                }
                default_month = st.session_state.get("cal_m", date.today().month)
                selected_month = st.selectbox("Filter by Month", options=list(month_options.keys()), format_func=lambda x: month_options[x], index=list(month_options.keys()).index(default_month), key="history_filter_month")
            with filter_col2:
                current_year = date.today().year
                year_options = list(range(current_year - 5, current_year + 6))
                selected_year = st.selectbox("Filter by Year", options=year_options, index=year_options.index(current_year), key="history_filter_year")

            all_approved_from_db = fetch_approved_requests_from_db()
            app_wellness = []
            app_pto = []
            
            for r in all_approved_from_db:
                date_val = r.get('date')
                if isinstance(date_val, str):
                    try:
                        date_val = datetime.strptime(date_val.split("T")[0], "%Y-%m-%d").date()
                    except ValueError:
                        continue
                if date_val.month == selected_month and date_val.year == selected_year:
                    if r.get('type') == "Wellness": app_wellness.append(r)
                    elif r.get('type') == "PTO": app_pto.append(r)
            
            if app_wellness:
                st.markdown("#### Approved Wellness")
                w_height = min(1000, max(100, len(app_wellness) * 35 + 38))
                st.dataframe(pd.DataFrame(app_wellness).drop(columns=['_id', 'type'], errors='ignore'), hide_index=True, use_container_width=True, height=w_height)
            if app_pto:
                st.markdown("#### Approved PTO")
                p_height = min(1000, max(100, len(app_pto) * 35 + 38))
                st.dataframe(pd.DataFrame(app_pto).drop(columns=['_id', 'type'], errors='ignore'), hide_index=True, use_container_width=True, height=p_height)
            if not app_wellness and not app_pto:
                st.write("No approved requests for this month.")
