from datetime import datetime, time, date
import streamlit as st
from pymongo import MongoClient
import calendar
import pandas as pd
import holidays
import sys
from types import ModuleType
import pytz

# --- MOCK GMAIL BARD MODULE IF NOT LOCALLY INSTALLED ---
if "gmail_bard" not in sys.modules:
    mock_gmail = ModuleType("gmail_bard")
    def send_message(to, subject, body):
        # Console confirmation fallback log
        print(f"[Mock Mail] Sent to {to}: {subject}")
    mock_gmail.send_message = send_message
    sys.modules["gmail_bard"] = mock_gmail

# --- DATABASE HELPERS & CONNECTION ---
uri = st.secrets["mongo"]["uri"] 
client = MongoClient(uri)
db = client["my_database"] 
collection = db["my_collection"]

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

def delete_staff(name):
    collection.delete_one({"type": "roster_list", "name": name})
    if name in st.session_state.staff_roster: 
        del st.session_state.staff_roster[name]

def update_staff_in_db(name, update_dict):
    collection.update_one({"type": "roster_list", "name": name}, {"$set": update_dict})
    if name in st.session_state.staff_roster:
        st.session_state.staff_roster[name].update(update_dict)

def get_cases_from_db():
    try:
        return list(collection.find({"type": "case"}))
    except Exception:
        return []

def save_case_to_db(case_data):
    case_data["type"] = "case"
    collection.insert_one(case_data)

def fetch_deviations_from_db():
    try:
        return list(collection.find({"type": "deviation"}))
    except Exception:
        return []

def save_deviation_to_db(data):
    data["type"] = "deviation"
    collection.insert_one(data)

def update_deviation_in_db(id, update_dict):
    collection.update_one({"_id": id}, {"$set": update_dict})

def delete_deviation_from_db(id):
    collection.delete_one({"_id": id})

def delete_request_from_db(req):
    collection.delete_one({"_id": req["_id"]})

def update_request_status_in_db(req, status):
    collection.update_one({"_id": req["_id"]}, {"$set": {"status": status}})

def fetch_approved_requests_from_db():
    return list(collection.find({
        "type": {"$in": ["PTO", "Wellness"]}, 
        "status": "Approved"
    }))

def fetch_pending_requests_from_db():
    return list(collection.find({
        "type": {"$in": ["PTO", "Wellness"]}, 
        "status": "Pending"
    }))

def save_request_to_db(req, request_type):
    """
    Saves a request payload to the MongoDB collection with a dynamic type designation.
    
    Parameters:
        req (dict): The original request data payload.
        request_type (str): Expected to be either "PTO" or "Wellness".
    """
    req["type"] = request_type
    collection.insert_one(req)

def get_request_limits():
    return st.session_state.get("limits", {"PTO": 1, "Wellness": 1})

def save_masterfile_to_db(df):
    collection.update_one({"type": "masterfile"}, {"$set": {"data": df.to_dict(orient="records")}}, upsert=True)

def send_request_notification(recipient_email, status, request_type, date_val):
    subject = f"Your {request_type} Request has been {status.upper()}"
    body = f"Hello,\n\nYour {request_type} request for {date_val} has been {status}.\n\nBest regards,\nAdmin Team"
    try:
        import gmail_bard
        gmail_bard.send_message(to=[recipient_email], subject=subject, body=body)
    except Exception as e:
        st.error(f"Could not send notification email: {e}")

# --- INITIAL CONFIG & STATE ---
st.set_page_config(layout="wide")
st.title("📊 Operational Shift & Roster Management System")

# Define your country's local timezone (Philippines / PHT)
local_tz = pytz.timezone("Asia/Manila") 
current_date = datetime.now(local_tz).date()

if "pending_requests" not in st.session_state: 
    st.session_state.pending_requests = fetch_pending_requests_from_db()
if "approved_requests" not in st.session_state: 
    st.session_state.approved_requests = fetch_approved_requests_from_db()
if "admin_password" not in st.session_state: st.session_state.admin_password = "Password1234"
if "admin_authenticated" not in st.session_state: st.session_state.admin_authenticated = False
if "staff_roster" not in st.session_state: 
    st.session_state.staff_roster = {}
if "calendar_data" not in st.session_state: st.session_state.calendar_data = {}
if "limits" not in st.session_state: st.session_state.limits = {"PTO": 1, "Wellness": 1}
if "notifications" not in st.session_state: st.session_state.notifications = []
if "master_data" not in st.session_state: 
    st.session_state.master_data = pd.DataFrame({
        "Category": ["Contact Type", "Issue", "Product Group"], 
        "Values": ["Call,Chat,Email", "Tech,Billing", "Hardware,Soft"]
    })

# --- DATA MIGRATION ---
# Force type conversions during load transitions safely
if "staff_roster" in st.session_state:
    for name, value in st.session_state.staff_roster.items():
        if isinstance(value, dict) and isinstance(value.get("bday"), date) and not isinstance(value.get("bday"), datetime):
            d = value["bday"]
            value["bday"] = datetime(d.year, d.month, d.day)

# SAFE SYSTEM REFRESH IF THE DATE HAS SHIFTED TO A NEW DAY
if "last_tracked_date" not in st.session_state or st.session_state.last_tracked_date != current_date:
    st.session_state.last_tracked_date = current_date
    # Instead of deleting the object key entirely (which causes the segmentation fault),
    # we cleanly clear out the old records or let load_data_from_db safely overwrite it.
    st.session_state.calendar_data = {} 
    load_data_from_db()

# --- GLOBAL CSS STYLING ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Quicksand:wght=400;600&display=swap');
    html, body, [class*="css"] { font-family: 'Quicksand', sans-serif !important; }
    
    /* All headers forced to Teal color */
    h1, h2, h3, .header-cell { font-family: 'Quicksand', sans-serif !important; font-weight: 600; color: #008080 !important; }
    
    .side-block { font-family: 'Quicksand', sans-serif !important; font-size: 10px !important; line-height: 1.2; }
    
    /* Calendar Day Block: Combined together dynamically in a uniform strip layout with no margins */
    .day-block { 
        border-radius: 0px; 
        padding: 10px; 
        height: 100%; 
        min-height: 280px; 
        font-size: 11px; 
        background-color: rgba(0, 128, 128, 0.75); 
        color: #ffffff !important;
        border: 1px solid #ffffff !important; /* Solid white border for calendar days within the month */
        margin: 0px; 
        display: flex; 
        flex-direction: column; 
        box-sizing: border-box;
    }

    /* Target state for blocks that fall outside the current month's active days */
    .day-block-outside,
    .day-block:empty {
        background-color: rgba(230, 242, 242, 0.85) !important; /* Baby teal design background */
        border: 1px solid #008080 !important; /* Teal border profile */
        color: #008080 !important;
    }

    /* Force text elements inside outside-month/empty blocks to color match the teal theme */
    .day-block-outside *, .day-block:empty * {
        color: #008080 !important;
    }
    
    /* Strict layout equalization to combine calendar blocks side-by-side cleanly without separation gaps */
    div[data-testid="stHorizontalBlock"] {
        gap: 0px !important;
    }

    /* Adjust structural layouts containing the calendar elements to enforce a flawless square/rectangular block alignment */
    div[data-testid="stHorizontalBlock"]:has(.day-block) {
        margin: 0px !important;
        padding: 0px !important;
    }

    /* Target the column block layout structure containing the calendar grid to separate it from the summary panel on the right */
    div[data-testid="stColumn"]:has(.day-block),
    div[data-testid="stColumn"]:has(.day-block-outside) {
        padding-right: 4px !important; /* Generates a precise structural gap layout of at least 1.5px to the summary block */
    }

    /* Provide a structured spatial separation gap between the calendar container and the monthly/daily summaries below it */
    div[data-testid="stHorizontalBlock"]:has(.day-block),
    div[data-testid="stHorizontalBlock"]:has(.day-block-outside) {
        margin-bottom: 25px !important; /* Provides clear separation space layout above the summary modules */
    }
    
    /* Make the date inside the day block noticeably bigger than the rest of the content */
    .day-block > b:first-of-type {
        font-size: 16px !important;
        display: block;
        margin-bottom: 2px;
    }
    
    /* Force internal day text links and components to honor the white text profile */
    .day-block u, .day-block center, .day-block b {
        color: #ffffff !important;
    }
    
    .calendar-divider { border-top: 1px solid rgba(255, 255, 255, 0.4); margin: 5px 0; width: 100%; }
    div.stButton > button { background: linear-gradient(90deg, #7b61ff 0%, #3b82f6 100%); color: white; border-radius: 12px; font-weight: 600; }
    .header-cell { font-weight: bold; text-align: center; padding-bottom: 10px; }
    .alert-container { border-radius: 20px; border: 2px solid #ff4d4d; padding: 15px; background-color: #fff5f5; margin-bottom: 20px; }
    .flash-red { color: #ff4d4d; font-weight: bold; text-align: center; }
    
    /* Selectboxes / Dropdowns targeted to display as translucent teal with white font */
    div[data-baseweb="select"] > div {
        background-color: rgba(0, 128, 128, 0.75) !important;
        color: #ffffff !important;
        border-radius: 8px;
        border: 1px solid #00aaaa !important;
    }
    
    /* Ensures selection text strings inside dropdown elements render cleanly in white */
    div[data-baseweb="select"] * {
        color: #ffffff !important;
    }

    /* Target the dropdown popover list options to also be translucent teal with white font */
    div[data-baseweb="menu"] {
        background-color: rgba(0, 128, 128, 0.95) !important; 
        border: 1px solid #00aaaa !important;
    }
    
    div[data-baseweb="menu"] li {
        color: #ffffff !important;
        background-color: transparent !important;
    }

    /* Hover effect for items inside the dropdown menu */
    div[data-baseweb="menu"] li:hover {
        background-color: rgba(0, 170, 170, 0.4) !important;
    }

    /* Header Tab Bar Restyling: Ombre teal background, white text labels, and larger font sizing */
    div[data-testid="stTabs"] button {
        background: linear-gradient(90deg, #004d4d 0%, #008080 100%) !important;
        color: #ffffff !important;
        font-size: 18px !important; /* Noticeably bigger in size */
        font-weight: 600 !important;
        padding: 12px 24px !important;
        border-radius: 8px 8px 0px 0px !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        margin-right: 4px !important;
    }
    
    /* Active highlighted tab indicator color override */
    div[data-testid="stTabs"] button[aria-selected="true"] {
        background: linear-gradient(90deg, #008080 0%, #00bcbc 100%) !important;
        color: #ffffff !important;
        border-bottom: 3px solid #ffffff !important;
    }

    /* Translucent teal entry boxes and white font applied to all forms and their nested standard input tags */
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
    
    /* Ensure typed text and placeholders inside forms present cleanly in white */
    div[data-testid="stForm"] input {
        -webkit-text-fill-color: #ffffff !important;
        color: #ffffff !important;
    }
    
    /* General input label text color overrides inside interactive form view blocks */
    div[data-testid="stForm"] label, div[data-testid="stForm"] p {
        color: #008080 !important;
        font-weight: 600;
    }

    /* Table alternate grid styles (skipping the main calendar layout) */
    div[data-testid="stTable"] tr:nth-child(even) {
        background-color: rgba(0, 128, 128, 0.85) !important;
    }
    div[data-testid="stTable"] tr:nth-child(even) td {
        color: #ffffff !important;
    }
    div[data-testid="stTable"] tr:nth-child(odd) {
        background-color: #ffffff !important;
    }
    div[data-testid="stTable"] tr:nth-child(odd) td {
        color: #008080 !important;
        font-weight: 600;
    }
    div[data-testid="stTable"] th {
        background-color: #004d4d !important;
        color: #ffffff !important;
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
    
    st.write(f"**{req['name']}** | {req['type']} | {req['date']}")
    
    # Render primary action buttons only if the denial process has NOT been triggered
    if not st.session_state.get(denial_key):
        c1, c2 = st.columns(2)
        
        if c1.button("Approve", key=f"app_{key_prefix}_{unique_id}"):
            update_request_status_in_db(req, "Approved")
            if req in st.session_state.pending_requests: 
                st.session_state.pending_requests.remove(req)
            st.session_state.approved_requests.append(req)
            if req.get("email"):
                send_request_notification(req['email'], "Approved", req['type'], req['date'])
            st.success("Approved!")
            st.rerun()

        if c2.button("Deny", key=f"den_{key_prefix}_{unique_id}"):
            st.session_state[denial_key] = True
            st.rerun()

    # Render denial follow-up flow elements when triggered
    if st.session_state.get(denial_key):
        reason = st.text_input("Reason for denial", key=f"reason_{key_prefix}_{unique_id}")
        col1, col2 = st.columns(2)
        
        if col1.button("Proceed Denial", key=f"confirm_{key_prefix}_{unique_id}"):
            delete_request_from_db(req)
            if req in st.session_state.pending_requests: 
                st.session_state.pending_requests.remove(req)
            if req.get("email"):
                send_request_notification(req['email'], "Denied", req['type'], req['date'])
            st.session_state[denial_key] = False
            st.rerun()
            
        if col2.button("Cancel", key=f"cancel_{key_prefix}_{unique_id}"):
            st.session_state[denial_key] = False
            st.rerun()

# --- TABS WORKSPACE ---
tab_cal, tab_req, tab_case, tab_dev, tab_mas, tab_adm = st.tabs([
    "📅 Calendar", "📝 Request", "🔍 Case Tracker", "🔀 Deviation", "📂 Masterfile", "🔑 Admin"
])

# --- TAB 1: CALENDAR ---
with tab_cal:
    
    # 2. Define structural page layout allocation matrix columns
    col_main, col_side = st.columns([4, 1])
    
    # 3. Use col_main for the top filters
    with col_main:
        c1, c2 = st.columns([1, 1])
        year = c1.selectbox("Year", [2026, 2027, 2028], key="cal_y")
        month = c2.selectbox(
            "Month", 
            range(1, 13), 
            format_func=lambda x: calendar.month_name[x], 
            index=current_date.month - 1, 
            key="cal_m"
        )

    # 4. Use col_side for the summary/sidebar
    with col_side:
        st.markdown('<div class="side-block">', unsafe_allow_html=True)
        st.subheader("Monthly Summary")
        
        st.markdown("**Birthdays:**")
        for name, info in st.session_state.staff_roster.items():
            # Robust extraction matching nested dictionary properties
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
        # 1. Safely extract the date object and ensure it is a standard datetime.date object
        raw_view_date = st.session_state.get('selected_admin_date', current_date)
        view_date = raw_view_date.date() if hasattr(raw_view_date, 'date') else raw_view_date

        # 2. Look up the data matching either the date object or its string representation
        d_data = st.session_state.calendar_data.get(view_date)
        if not d_data:
            d_data = st.session_state.calendar_data.get(str(view_date), {})
        
        st.markdown(f"### Date: {view_date.strftime('%B %d, %Y')}")
        st.markdown(f"**Setup:** {d_data.get('status', 'Not Set')} | **Shift:** {d_data.get('shift', '--')}")
        st.divider()
        
        st.write("**Today's Schedule:**")
        roles = ["call", "chat", "mfq", "sme"]
        
        for name in st.session_state.staff_roster:
            # Check for approved requests matching the active daily view date using string matching
            p_status = [r['type'] for r in st.session_state.approved_requests 
                        if str(r['date']) == str(view_date) and r['name'] == name]
            
            # If they have approved time off today, keep them in view but explicitly tag with leave type
            if p_status:
                st.write(f"- **{name}**: {str(p_status[0]).upper()}")
            else:
                assigned_roles = [r.upper() for r in roles if name in d_data.get(r, [])]
                shift_role = ", ".join(assigned_roles) if assigned_roles else "Unassigned"
                st.write(f"- **{name}**: {shift_role}")
            
        st.markdown('</div>', unsafe_allow_html=True)

    # 5. Render interactive monthly calendar grid block
    with col_main:
        # Fetch current roster directly from the database document to align nickname matching
        roster_doc = collection.find_one({"type": "roster_list"})
        roster = roster_doc.get("data", {}) if roster_doc else {}

        cols = st.columns(7)
        for i, d_name in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
            cols[i].markdown(f'<div class="header-cell">{d_name}</div>', unsafe_allow_html=True)
            
        for week in calendar.Calendar(firstweekday=6).monthdayscalendar(year, month):
            cols = st.columns(7)
            for i, day in enumerate(week):
                if day != 0:
                    d = date(year, month, day)
                    approved = [r for r in st.session_state.approved_requests if str(r['date']) == str(d)]
                    away_names = [r['name'] for r in approved]
                    
                    # Look up nicknames from the active roster configuration list instead of full names
                    def get_filtered_nicks(full_names):
                        active = [n for n in full_names if n not in away_names]
                        return ", ".join([roster.get(x, {}).get("nick", x) for x in active])
                    
                    # Mapping nickname profile directly onto the requested leave items
                    req_display = "<br>".join([f"{roster.get(r['name'], {}).get('nick', r['name'])}({r['type']})" for r in approved])
                    data = st.session_state.calendar_data.get(d, {})
                    
                    # WEEKEND INSTRUCTION: Block out Saturday (5) and Sunday (6) explicitly as REST DAY
                    if d.weekday() in [5, 6]:
                        content = f"<b>{day}</b><div class='calendar-divider'></div><br><center><b>REST DAY</b></center>"
                    else:
                        content = (f"<b>{day}</b><div class='calendar-divider'></div>"
                                   f"<u>{data.get('status', '-')}</u><div class='calendar-divider'></div>"
                                   f"{data.get('shift', '-')}<div class='calendar-divider'></div>"
                                   f"PTO/Wellness: {req_display}<div class='calendar-divider'></div>"
                                   f"Call: {get_filtered_nicks(data.get('call', []))}<div class='calendar-divider'></div>"
                                   f"Chat: {get_filtered_nicks(data.get('chat', []))}<div class='calendar-divider'></div>"
                                   f"MFQ: {get_filtered_nicks(data.get('mfq', []))}<div class='calendar-divider'></div>"
                                   f"SME: {get_filtered_nicks(data.get('sme', []))}")
                    
                    cols[i].markdown(f'<div class="day-block">{content}</div>', unsafe_allow_html=True)

# --- TAB 2: REQUEST FORM ---
with tab_req:
    st.subheader("PTO/Wellness Request")
    st.info("💡 **Tip:** Providing your work email is optional.")
    
    with st.form("request_form", clear_on_submit=True):
        # 1. Fetch current roster directly from the database document
        roster_doc = collection.find_one({"type": "roster_list"})
        staff_data = roster_doc.get("data", {}) if roster_doc else {}
        
        # 2. Extract available names or fallback to session state
        available_names = list(staff_data.keys()) if staff_data else list(st.session_state.staff_roster.keys())
        name = st.selectbox("Name", available_names)
        
        email = st.text_input("Work Email (Optional)")
        req_date = st.date_input("Request Date")
        req_type = st.selectbox("Type", ["PTO", "Wellness"])
        
        if st.form_submit_button("Submit Request"):
            # 2. Fetch limit ceilings directly from DB configuration
            limits = get_request_limits()
            
            # Count records on specified target date using explicit string conversions
            count_on_date = len([
                r for r in (st.session_state.pending_requests + st.session_state.approved_requests) 
                if str(r["date"]) == str(req_date) and r["type"] == req_type
            ])
            
            # Double Booking Duplicate Verification Check
            is_already_requested = any(
                r["name"] == name and str(r["date"]) == str(req_date) 
                for r in (st.session_state.pending_requests + st.session_state.approved_requests)
            )
            
            # 3. Validation and Submission Logic Flow
            if is_already_requested:
                st.warning(f"⚠️ A request for {name} on {req_date} already exists.")
            elif count_on_date >= limits.get(req_type, 0):
                st.error(f"❌ Limit reached for {req_type} on {req_date}. Please choose another date.")
            else:
                # Construct combined document payload
                new_req = {
                    "name": name, 
                    "date": str(req_date), 
                    "type": req_type, 
                    "status": "Pending", 
                    "email": email,
                    "viewed": False
                }
                
                # --- UPDATED DB SAVE FUNCTION CALL ---
                # Pass both the dictionary payload and the selected type string ("PTO" or "Wellness")
                save_request_to_db(new_req, req_type)
                
                st.session_state.pending_requests.append(new_req)
                st.success("Request submitted successfully.")
                st.rerun()

# --- TAB 3: CASE TRACKER ---
with tab_case:
    st.subheader("Log New Case")
    
    # 1. Fetch dropdown data from DB (assuming your master_data logic holds)
    c_types = st.session_state.master_data.loc[st.session_state.master_data['Category'] == 'Contact Type', 'Values'].iloc[0].split(',')
    issues = st.session_state.master_data.loc[st.session_state.master_data['Category'] == 'Issue', 'Values'].iloc[0].split(',')
    prods = st.session_state.master_data.loc[st.session_state.master_data['Category'] == 'Product Group', 'Values'].iloc[0].split(',')
    
    c1, c2 = st.columns(2)
    c_type = c1.selectbox("Contact Type", c_types)
    issue = c1.selectbox("Issue", issues)
    prod = c2.selectbox("Product Group", prods)
    desc = st.text_area("Issue Description")
    steps = st.text_area("Steps Taken")
    uploaded_file = st.file_uploader("Upload Screenshot")
    status = st.selectbox("Status", ["Resolved", "Pending/Monitoring", "Routed"])
    extra = ""
    if status == "Pending/Monitoring": extra = st.text_input("Pending/Monitoring Reason")
    elif status == "Routed": extra = st.text_input("Queue Destination")
    
    # 2. Use 'Log Case' button to save directly to DB
    if st.button("Log Case"):
        new_case = {
            "Date": str(date.today()), 
            "Type": c_type, 
            "Issue": issue, 
            "Product Group": prod, 
            "Desc": desc, 
            "Steps": steps, 
            "Has_Screenshot": uploaded_file is not None, # Captures attachment state
            "Status": status, 
            "Extra": extra
        }
        save_case_to_db(new_case) # Linked directly back to your Mongo helper
        st.success("Case logged to database successfully!")
        st.rerun()

    st.divider()
    st.subheader("Knowledge Base")
    
    # 3. Restored Database Linkage
    cases_list = get_cases_from_db() 
    
    f1, f2 = st.columns(2)
    f_issue = f1.multiselect("Filter by Issue", issues)
    f_prod = f2.multiselect("Filter by Product Group", prods)
    
    for case in reversed(cases_list): # Safely uses active list
        if (not f_issue or case['Issue'] in f_issue) and (not f_prod or case['Product Group'] in f_prod):
            with st.container():
                # Split header row to place ellipses options menu on the upper right corner
                head_col, opt_col = st.columns([6, 1])
                
                with head_col:
                    st.markdown(f"**Date:** {case['Date']} | **Status:** {case['Status']} | **Issue:** {case['Issue']}")
                
                with opt_col:
                    # Ellipses simulation dropdown for managing individual case entry
                    options_menu = st.popover("⋮", help="Options")
                    with options_menu:
                        action = st.radio("Action", ["View", "Edit", "Delete"], key=f"act_{case['_id']}", horizontal=False)
                
                # Render content or Action menus depending on choice
                if action == "Edit":
                    st.markdown("#### Edit Case Details")
                    # Populates current data into editable fields
                    edit_desc = st.text_area("Update Issue Description", value=case.get('Desc', ''), key=f"ed_desc_{case['_id']}")
                    edit_steps = st.text_area("Update Steps Taken", value=case.get('Steps', ''), key=f"ed_step_{case['_id']}")
                    
                    if st.button("Save Changes", key=f"save_ed_{case['_id']}"):
                        # Updates the live collection document directly
                        collection.update_one(
                            {"_id": case["_id"]}, 
                            {"$set": {"Desc": edit_desc, "Steps": edit_steps}}
                        )
                        st.success("Case updated successfully!")
                        st.rerun()
                        
                elif action == "Delete":
                    st.warning("⚠️ This action requires supervisor authorization.")
                    del_password = st.text_input("Enter Admin Password to confirm delete", type="password", key=f"pwd_del_{case['_id']}")
                    if st.button("Confirm Delete", key=f"conf_del_{case['_id']}"):
                        if del_password == "Password1234":
                            # Calls active MongoDB removal command
                            collection.delete_one({"_id": case["_id"]})
                            st.success("Case deleted successfully.")
                            st.rerun()
                        else:
                            st.error("Incorrect Password. Action denied.")
                else:
                    # Default Display State (View Mode)
                    st.write(case.get('Desc', ''))
                    st.write(f"*Steps Taken:* {case.get('Steps', '')}")
                    if case.get("Has_Screenshot"):
                        st.caption("📎 Screenshot attached to this record.")
                
                st.markdown("---")
                
# --- TAB 4: DEVIATION ---
with tab_dev:
    st.subheader("Submit Deviation Request")
    
    with st.form("deviation_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            target_date = st.date_input("Target Date", value=date.today())
            manager = st.text_input("Manager", value="Jeff Bote")
            # 1. Fetch current roster directly from the database document
            roster_doc = collection.find_one({"type": "roster_list"})
            staff_data = roster_doc.get("data", {}) if roster_doc else {}
            # 2. Extract available names or fallback to session state
            available_names = list(staff_data.keys()) if staff_data else list(st.session_state.staff_roster.keys())
            name = st.selectbox("Name", available_names, key="dev_name_box")
            # Restored calendar shift time calculations
            shift_time = st.session_state.calendar_data.get(target_date, {}).get("shift", "Not Set")
            st.write(f"**Shift Time:** {shift_time}")
        with col2:
            start_time = st.time_input("Start Time")
            end_time = st.time_input("End Time")
            total_mins = st.number_input("Total Mins", min_value=0)
            aux = st.text_input("Aux") # Restored input field
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
    
    # 1. Restored Filter Block Controls
    with st.expander("Filter Report"):
        f_col1, f_col2, f_col3 = st.columns(3)
        filter_month = f_col1.selectbox("Month", range(1, 13), index=date.today().month-1, key="dev_f_month")
        filter_year = f_col2.number_input("Year", value=date.today().year, key="dev_f_year")
        filter_date = f_col3.date_input("Specific Date (Optional)", value=None, key="dev_f_date")
        apply_filter = st.button("Apply Filter")

    # 2. Fetch and Filter Data
    dev_data = fetch_deviations_from_db()
    if dev_data:
        df = pd.DataFrame(dev_data)
        df['Date'] = pd.to_datetime(df['Date']).dt.date
        
        if apply_filter:
            if filter_date:
                df = df[df['Date'] == filter_date]
            else:
                df = df[(df['Date'].apply(lambda x: x.month) == filter_month) & (df['Date'].apply(lambda x: x.year) == filter_year)]
        
        # Convert filtered dataframe back to list of dictionaries for container loop rendering
        filtered_records = df.to_dict(orient="records")
        
        # 3. CSV Download
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("Extract Report as CSV", csv, "deviation_report.csv", "text/csv")
        st.write("## Deviation Records")
        
        # Render each row inside individual interactive blocks with ellipses menu
        for dev in reversed(filtered_records):
            with st.container():
                # Split header row to place ellipses options menu on the upper right corner
                head_col, opt_col = st.columns([6, 1])
                
                with head_col:
                    st.markdown(f"**Date:** {dev.get('Date')} | **Staff Name:** {dev.get('Name')} | **Manager:** {dev.get('Manager')}")
                
                with opt_col:
                    # Ellipses simulation popover menu for individual entries
                    options_menu = st.popover("⋮", help="Options")
                    with options_menu:
                        action = st.radio("Action", ["View", "Edit", "Delete"], key=f"act_dev_{dev['_id']}", horizontal=False)
                
                # Render content or action menus depending on selector
                if action == "Edit":
                    st.markdown("#### Edit Deviation Request")
                    edit_manager = st.text_input("Update Manager", value=dev.get('Manager', ''), key=f"ed_mgr_{dev['_id']}")
                    edit_mins = st.number_input("Update Total Mins", value=int(dev.get('Total Mins', 0)), min_value=0, key=f"ed_mins_{dev['_id']}")
                    edit_aux = st.text_input("Update Aux", value=dev.get('Aux', ''), key=f"ed_aux_{dev['_id']}")
                    edit_reason = st.text_area("Update Reason of Deviation", value=dev.get('Reason', ''), key=f"ed_reas_{dev['_id']}")
                    
                    if st.button("Save Changes", key=f"save_ed_dev_{dev['_id']}"):
                        update_deviation_in_db(dev["_id"], {
                            "Manager": edit_manager,
                            "Total Mins": edit_mins,
                            "Aux": edit_aux,
                            "Reason": edit_reason
                        })
                        st.success("Deviation record updated successfully!")
                        st.rerun()
                        
                elif action == "Delete":
                    st.warning("⚠️ This action requires supervisor authorization.")
                    del_password = st.text_input("Enter Admin Password to confirm delete", type="password", key=f"pwd_del_dev_{dev['_id']}")
                    if st.button("Confirm Delete", key=f"conf_del_dev_{dev['_id']}"):
                        if del_password == "Password1234":
                            delete_deviation_from_db(dev["_id"])
                            st.success("Deviation record removed.")
                            st.rerun()
                        else:
                            st.error("Incorrect Password. Action denied.")
                else:
                    # Default Display State (View Mode)
                    st.write(f"**Shift:** {dev.get('Shift Time', 'Not Set')} | **Aux:** {dev.get('Aux', 'N/A')}")
                    st.write(f"**Time-frame:** {dev.get('Start Time')} - {dev.get('End Time')} ({dev.get('Total Mins')} Mins)")
                    st.write(f"*Reason:* {dev.get('Reason', '')}")
                
                st.markdown("---")
    else:
        st.write("No deviation requests found.")

# --- TAB 5: MASTERFILE ---
with tab_mas:
    if not st.session_state.admin_authenticated:
        if st.text_input("Enter Password", type="password", key="m_pass") == "Password1234":
            st.session_state.admin_authenticated = True
            st.rerun()
    else:
        # Create columns to align the header and the button side-by-side
        col_m1, col_m2 = st.columns([4, 1])
        
        with col_m1:
            st.subheader("System Masterfile")
        
        with col_m2:
            if st.button("Save Masterfile Changes", key="btn_save_masterfile"):
                # Persist the current data_editor state directly to MongoDB
                save_masterfile_to_db(st.session_state.master_data)
                st.success("Masterfile saved to DB.")
                st.rerun() # Restored to immediately refresh state and commit configuration
        
        # Display the interactive data editor grid below the action layout row
        st.session_state.master_data = st.data_editor(st.session_state.master_data, num_rows="dynamic")

# --- TAB 6: ADMIN Panel ---
with tab_adm:
    if not st.session_state.admin_authenticated:
        if st.text_input("Admin Password", type="password", key="a_pass_admin_tab") == "Password1234": 
            st.session_state.admin_authenticated = True
            st.rerun()
    else:
        st.subheader("Admin Panel")
        
        # --- Top Level Admin UI ---
        if st.session_state.pending_requests:
            st.info(f"⚠️ You have {len(st.session_state.pending_requests)} pending request(s).")
        
        if st.button("Save Admin Changes", key="btn_top_admin_save"):
            st.success("Admin configuration saved.")
        st.divider()

        col1, col2 = st.columns(2)
    
        with col1:
            st.subheader("Roster Management")
                
            # 1. Fetch current list directly from the roster_list document in DB
            roster_doc = collection.find_one({"type": "roster_list"})
            roster = roster_doc.get("data", {}) if roster_doc else {}
                
            # 2. Header Grid Layout
            c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
            c1.write("**Name**")
            c2.write("**Nickname**")
            c3.write("**Birthday**")
            c4.write("**Actions**")
            st.divider()
    
            # 3. Loop through DB data records
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
                    
                    # Actions Button Control
                    if c4.button("Remove", key=f"del_staff_{name}"):
                        delete_staff(name)
                        st.rerun()
            else:
                st.write("*No staff members configured in the roster database.*")
    
            # 4. Entry Form Configuration
            st.markdown("---")
            new_name = st.text_input("Staff Name", key="input_new_staff_name")
            new_nick = st.text_input("Nickname", key="input_new_staff_nick")
            new_bday = st.date_input("Birthday", min_value=date(1950, 1, 1), key="new_bday")
            rest_days = st.multiselect("Select Rest Days", 
                           ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"], key="ms_rest_days")
            
            if st.button("Add Staff", key="btn_submit_add_staff"):
                if new_name:
                    # Explicitly force a true datetime object that PyMongo natively serializes
                    bday_datetime = datetime(new_bday.year, new_bday.month, new_bday.day)
                    
                    save_staff(new_name, {
                        "bday": bday_datetime, 
                        "nick": new_nick if new_nick else new_name,
                        "rest_days": rest_days
                    })
                    st.success(f"Added {new_name} to database!")
                    st.rerun()
            st.divider()
    
            # --- DAILY CONFIG ---
            st.subheader("Configuration")
            st.session_state.selected_admin_date = st.date_input("Select Date to View/Edit", date.today(), key="cfg_view_edit_date")
            
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
            
            # Date selection logic configuration mapping
            if config_mode == "Single Date": 
                target_dates = [st.date_input("Date", key="cfg_d")]
            elif config_mode == "Date Range": 
                dr = st.date_input("Range", [], key="cfg_dr")
                target_dates = pd.date_range(dr[0], dr[1]).date if len(dr) == 2 else []
            else:
                sm = st.date_input("Month", value=date.today(), key="cfg_m")
                target_dates = pd.date_range(f"{sm.year}-{sm.month}-01", periods=31).date
                target_dates = [d for d in target_dates if d.month == sm.month]
    
            # Limits, Shifts, and Status mapping definitions
            st.session_state.limits["PTO"] = st.number_input("Max PTO", value=st.session_state.limits.get("PTO", 1), key="num_max_pto")
            st.session_state.limits["Wellness"] = st.number_input("Max Wellness", value=st.session_state.limits.get("Wellness", 1), key="num_max_well")
            
            start_t = st.time_input("Shift Start", value=time(9, 0), key="time_shift_start")
            end_t = st.time_input("Shift End", value=time(18, 0), key="time_shift_end")
            timezone = "PHT"
            
            shift_display = f"{start_t.strftime('%I:%M %p')} - {end_t.strftime('%I:%M %p')} {timezone}"
            st.write(f"Selected Shift: **{shift_display}**")
            
            setup = st.selectbox("Status", ["PROD - ONSITE", "PROD - WAH", "HOLIDAY"], key="sb_daily_status_setup")
            
            # Assignment Availability Filters
            safe_target_dates = target_dates if isinstance(target_dates, (list, tuple)) else []
            base_date = safe_target_dates[0] if len(safe_target_dates) > 0 else date.today()
            
            unavailable = [r['name'] for r in st.session_state.approved_requests if str(r['date']) == str(base_date)]
            available = [n for n in roster.keys() if n not in unavailable] if roster else []
            
            call = st.multiselect("Assign Call", available, key="ms_assign_call")
            chat = st.multiselect("Assign Chat", available, key="ms_assign_chat")
            mfq = st.multiselect("Assign MFQ", available, key="ms_assign_mfq")
            sme = st.multiselect("Assign SME", available, key="ms_assign_sme")
            
            if st.button("Save Config", key="btn_save_daily_config"):
                for d in target_dates:
                    st.session_state.calendar_data[d] = {
                        "shift": shift_display, 
                        "status": setup, 
                        "call": call, 
                        "chat": chat,
                        "mfq": mfq,
                        "sme": sme
                    }
                
                # Convert date keys to strings for MongoDB compatibility
                serializable_data = {str(k): v for k, v in st.session_state.calendar_data.items()}
                
                collection.update_one(
                    {"type": "calendar_data"},
                    {"$set": {"data": serializable_data}},
                    upsert=True
                )
                st.success("Configuration saved to database!")
                st.rerun()
        
        with col2:
            st.subheader("Approval Center")
            
            # --- DISPLAY ADMIN MESSAGES ---
            if "admin_msg" not in st.session_state: 
                st.session_state.admin_msg = None
            if st.session_state.admin_msg:
                msg_type, msg_text = st.session_state.admin_msg
                if msg_type == "success": 
                    st.success(msg_text)
                else: 
                    st.warning(msg_text)
                    
                if st.button("Clear Notification", key="clear_admin_notif"):
                    st.session_state.admin_msg = None
                    st.rerun()

            # --- WELLNESS SECTION ---
            st.markdown("### 🌿 Wellness Requests")
            wellness_pending = [r for r in st.session_state.pending_requests if r.get('type') == 'Wellness']
            if wellness_pending:
                for idx, req in enumerate(wellness_pending):
                    # Generate a truly unique deterministic key string profile
                    unique_key = f"wellness_{req.get('name')}_{req.get('date')}_{idx}"
                    render_request(req, unique_key)
            else:
                st.write("No pending Wellness requests.")

            # --- PTO SECTION ---
            st.markdown("### ✈️ PTO Requests")
            pto_pending = [r for r in st.session_state.pending_requests if r.get('type') == 'PTO']
            if pto_pending:
                for idx, req in enumerate(pto_pending):
                    # Generate a truly unique deterministic key string profile
                    unique_key = f"pto_{req.get('name')}_{req.get('date')}_{idx}"
                    render_request(req, unique_key)
            else:
                st.write("No pending PTO requests.")

            st.divider()

           # --- APPROVED HISTORY ---
            st.subheader("✅ Approved History")
            
            # --- ADDED: Month and Year Filters ---
            filter_col1, filter_col2 = st.columns(2)
            with filter_col1:
                month_options = {
                    1: "January", 2: "February", 3: "March", 4: "April", 
                    5: "May", 6: "June", 7: "July", 8: "August", 
                    9: "September", 10: "October", 11: "November", 12: "December"
                }
                # Default to the session state month 'cal_m' if available, otherwise current month
                default_month = st.session_state.get("cal_m", date.today().month)
                selected_month = st.selectbox("Filter by Month", options=list(month_options.keys()), format_func=lambda x: month_options[x], index=list(month_options.keys()).index(default_month), key="history_filter_month")
            
            with filter_col2:
                current_year = date.today().year
                year_options = list(range(current_year - 5, current_year + 6))
                selected_year = st.selectbox("Filter by Year", options=year_options, index=year_options.index(current_year), key="history_filter_year")
            # -------------------------------------

            all_approved_from_db = fetch_approved_requests_from_db()
            
            # Updated to use the selected dropdown choices for filtering
            month_to_filter = selected_month
            year_to_filter = selected_year
            
            app_wellness = []
            app_pto = []
            
            for r in all_approved_from_db:
                date_val = r.get('date')
                if isinstance(date_val, str):
                    try:
                        date_val = datetime.strptime(date_val.split("T")[0], "%Y-%m-%d").date()
                    except ValueError:
                        continue
                # Added explicit year validation alongside the existing month matching condition
                if date_val.month == month_to_filter and date_val.year == year_to_filter:
                    if r.get('type') == "Wellness":
                        app_wellness.append(r)
                    elif r.get('type') == "PTO":
                        app_pto.append(r)
            
            if app_wellness:
                st.markdown("#### Approved Wellness")
                st.table(pd.DataFrame(app_wellness).drop(columns=['_id', 'type'], errors='ignore'))
            if app_pto:
                st.markdown("#### Approved PTO")
                st.table(pd.DataFrame(app_pto).drop(columns=['_id', 'type'], errors='ignore'))
            if not app_wellness and not app_pto:
                st.write("No approved requests for this month.")
