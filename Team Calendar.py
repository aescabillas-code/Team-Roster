from datetime import datetime, time
from datetime import datetime
from datetime import date, time, datetime
import streamlit as st
from pymongo import MongoClient
import calendar
import pandas as pd
import holidays

# --- DATABASE HELPERS ---
# 1. ESTABLISH CONNECTION FIRST
# Use st.secrets to keep your credentials safe
uri = st.secrets["mongo"]["uri"] 
client = MongoClient(uri)
db = client["team_calendar_db"] # Replace with your actual DB name
collection = db["team_data"]    # Replace with your actual collection name

def fetch_cases_from_db():
    # Add your database connection and query logic here
    # Example for MongoDB:
    # return list(db.cases_collection.find({}))
    return [] # Placeholder

def fetch_masterfile_from_db():
    # Replace this with your actual database logic
    # Example:
    # return list(db.master_collection.find({}))
    
    # Placeholder for testing:
    return [
        {"Category": "Contact Type", "Values": "Email,Phone,Chat"},
        {"Category": "Issue", "Values": "Login,Billing,Technical"},
        {"Category": "Product Group", "Values": "Software,Hardware,Services"}
    ]
    
# 2. NOW DEFINE THE FUNCTION (it can now see 'collection')
def load_data_from_db():
    if "staff_roster" not in st.session_state:
        roster_doc = collection.find_one({"type": "roster_list"})
        st.session_state.staff_roster = roster_doc.get("data", {}) if roster_doc else {}
    
    cal_doc = collection.find_one({"type": "calendar_data"})
    if cal_doc and "data" in cal_doc:
        # Convert string keys (from DB) back into date objects (for logic/display)
        st.session_state.calendar_data = {
            datetime.strptime(k, "%Y-%m-%d").date(): v 
            for k, v in cal_doc["data"].items()
        }
    else:
        st.session_state.calendar_data = {}
        
@st.cache_data(ttl=600)
def get_staff_list():
    try:
        # Fetching documents from MongoDB
        cursor = collection.find({"type": "roster"})
        # Building the dictionary
        return {doc["name"]: {
            "bday": doc["bday"], 
            "nick": doc["nick"], 
            "rest_days": doc.get("rest_days", [])
        } for doc in cursor}
    except Exception as e:
        # If there's a connection error or query issue, show error and return empty dict
        st.error("Could not load staff data from the database.")
        return {}

def save_staff(name, data):
    # 1. Update Session State (for immediate UI response)
    st.session_state.staff_roster[name] = data
    
    # 2. Update Database (for persistence)
    collection.update_one(
        {"type": "roster_list"},
        {"$set": {"data": st.session_state.staff_roster}},
        upsert=True
    )

def delete_staff(name):
    # 1. Remove from MongoDB
    collection.delete_one({"type": "roster", "name": name})
    
    # 2. Update session state immediately so the UI reflects the change
    if name in st.session_state.staff_roster:
        del st.session_state.staff_roster[name]
        
    st.success(f"{name} has been removed.")

def update_staff_in_db(name, update_dict):
    # 1. Update in MongoDB
    collection.update_one({"type": "roster", "name": name}, {"$set": update_dict})
    
    # 2. Update session state so the UI reflects the change
    if name in st.session_state.staff_roster:
        st.session_state.staff_roster[name].update(update_dict)
        
    st.success(f"{name} has been updated.")
    
# --- INITIAL CONFIG & STATE ---
st.set_page_config(layout="wide", page_title="Team Roster & Staffing System")

# --- DATABASE ---
uri = st.secrets["mongo"]["uri"]

@st.cache_resource
def get_db_client():
    return MongoClient(uri)

def get_collection():
    client = get_db_client()
    return client["my_database"]["my_collection"]

# Initialize the collection once
collection = get_collection()

# --- INITIALIZE STATE ---
if "admin_password" not in st.session_state:
    st.session_state.admin_password = "Password1234"
if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False
if "staff_roster" not in st.session_state: 
    st.session_state.staff_roster = {
        "Agent A": {"bday": date(2000, 1, 1), "nick": "A"}, 
        "Agent B": {"bday": date(1995, 5, 20), "nick": "B"}
    }
if "pending_requests" not in st.session_state: st.session_state.pending_requests = []
if "deviation_requests" not in st.session_state: st.session_state.deviation_requests = []
if "active_tab" not in st.session_state: st.session_state.active_tab = 0
if "calendar_data" not in st.session_state: st.session_state.calendar_data = {}
if "approved_requests" not in st.session_state: st.session_state.approved_requests = []
if "limits" not in st.session_state: st.session_state.limits = {"PTO": 1, "Wellness": 1}
if "admin_authenticated" not in st.session_state: st.session_state.admin_authenticated = False
if "cases" not in st.session_state: st.session_state.cases = []
if "notifications" not in st.session_state: st.session_state.notifications = []
if "master_data" not in st.session_state: 
    st.session_state.master_data = pd.DataFrame({"Category": ["Contact Type", "Issue", "Product Group"], "Values": ["Call,Chat,Email", "Tech,Billing", "Hardware,Soft"]})

# --- HANDLER FUNCTIONS ---
def handle_approval(req, original_idx):
    # 1. Add to approved list
    st.session_state.approved_requests.append(req)
    
    # 2. Remove from pending list
    st.session_state.pending_requests.pop(original_idx)
    
    # 3. Send Email
    if req.get("email"):
        send_request_notification(req['email'], "Approved", req['type'], req['date'])
        
    # 4. Set Success Message
    st.session_state.admin_msg = ("success", f"Approved {req['name']}'s {req['type']} request.")
    
    # 5. Rerun to refresh UI
    st.rerun()
    
def render_request(req, idx, key_prefix):
    # Unique keys for this specific request
    denial_key = f"denying_{key_prefix}_{idx}"
    
    # 1. Standard Display Row
    c1, c2, c3 = st.columns([3, 1, 1])
    c1.write(f"**{req['name']}** - {req['date']} ({req['type']})")
    
    # 2. Approve Action
    if c2.button("Approve", key=f"app_{key_prefix}_{idx}"):
        # Update Database
        update_request_status_in_db(req, "Approved")
        # Sync Session State
        req['status'] = "Approved"
        st.session_state.approved_requests.append(req)
        st.session_state.pending_requests.pop(idx)
        st.success("Request Approved and saved!")
        st.rerun()

    # 3. Deny Action (Triggers Popup)
    if c3.button("Deny", key=f"den_{key_prefix}_{idx}"):
        st.session_state[denial_key] = True
        st.rerun()

    # 4. Denial Popup Logic
    if st.session_state.get(denial_key):
        st.write(f"--- Reason for denying {req['name']}'s {req['type']} request ---")
        reason = st.text_input("Reason", key=f"reason_{key_prefix}_{idx}")
        
        col1, col2 = st.columns(2)
        if col1.button("Proceed Denial", key=f"confirm_{key_prefix}_{idx}"):
            # 1. Database Deletion
            delete_request_from_db(req)
            # 2. Notification (Optional)
            if req.get("email"):
                send_request_notification(req['email'], "Denied", req['type'], req['date'])
            # 3. State sync
            st.session_state.pending_requests.pop(idx)
            st.session_state[denial_key] = False
            st.session_state.admin_msg = ("warning", f"Denied {req['name']}'s request: {reason}")
            st.rerun()
            
        if col2.button("Cancel", key=f"cancel_{key_prefix}_{idx}"):
            st.session_state[denial_key] = False
            st.rerun()
            
    else:
        # --- STANDARD VIEW ---
        st.write(f"**{req['name']}** | {req['type']} | {req['date']}")
        
        c1, c2 = st.columns(2)
        # Call the handle_approval function here
        if c1.button("Approve", key=f"app_{key_prefix}_{idx}"):
            handle_approval(req, idx) 
            
        if c2.button("Deny", key=f"den_{key_prefix}_{idx}"):
            st.session_state[denial_key] = True
            st.rerun()
            
def send_request_notification(recipient_email, status, request_type, date):
    # Everything below MUST be indented with 4 spaces (or one tab)
    subject = f"Your {request_type} Request has been {status.upper()}"
    body = f"Hello,\n\nYour {request_type} request for {date} has been {status}.\n\nBest regards,\nAdmin Team"
    
    # Use gmail_bard to send
    gmail_bard.send_message(
        to=[recipient_email],
        subject=subject,
        body=body
    )

# --- ADD THIS MIGRATION BLOCK ---
if "staff_roster" in st.session_state:
    for name, value in st.session_state.staff_roster.items():
        # Check if the value is just a date object (the old format)
        if not isinstance(value, dict):
            # Convert the old format to the new format
            st.session_state.staff_roster[name] = {
                "bday": value, 
                "nick": name  # Default nickname to the full name
            }

# --- CSS STYLES ---
st.markdown("""
    <style>
    /* Import Google Font */
    @import url('https://fonts.googleapis.com/css2?family=Quicksand:wght@400;600&display=swap');
    
    /* 1. Global App Background */
    [data-testid="stAppViewContainer"] {
        background-color: #000000;
    }
    
    /* 2. Set all Labels and Text to Teal */
    label, p, div, span, h1, h2, h3, .stMarkdown {
        color: #008080 !important; 
        font-family: 'Quicksand', sans-serif !important;
    }

    /* 3. Calendar Grid Styling (The "Normal Calendar" Look) */
    .day-block { 
        border: 1px solid #333333; 
        border-radius: 8px; 
        padding: 10px; 
        height: 150px; 
        width: 100%;
        background-color: #121212; 
        margin: 2px; 
        display: flex; 
        flex-direction: column;
        overflow-y: auto;
        font-size: 11px;
    }
    
    .header-cell { 
        font-weight: bold; 
        text-align: center; 
        color: #008080 !important; 
        padding-bottom: 10px; 
        border-bottom: 2px solid #008080;
    }

    .rest-day {
        background-color: #0a0a0a !important;
        border: 1px dashed #333 !important;
        color: #555 !important;
    }

    .calendar-divider { border-top: 1px solid #333; margin: 5px 0; width: 100%; }
    
    /* Buttons */
    div.stButton > button { 
        background: linear-gradient(90deg, #008080 0%, #005f5f 100%); 
        color: white; 
        border-radius: 12px; 
        font-weight: 600; 
    }
    
    /* Alert & Knowledge Styling */
    .alert-container { 
        border-radius: 20px; 
        border: 2px solid #ff4d4d; 
        padding: 15px; 
        background-color: #1a1a1a; 
        margin-bottom: 20px; 
    }
    
    .flash-red { 
        color: #ff4d4d !important; 
        font-weight: bold; 
        text-align: center; 
    }
    
    .knowledge-card { 
        border: none; 
        padding: 20px; 
        margin-bottom: 15px; 
        border-radius: 20px; 
        background-color: #121212; 
        box-shadow: 0 4px 6px rgba(255,255,255,0.05); 
    }
    </style>
""", unsafe_allow_html=True)

# --- TOP FLASHING NOTIFICATION BAR ---
# Now strictly for system-wide notices
if st.session_state.notifications:
    html_content = '<div class="alert-container">'
    html_content += '<div class="flash-red" style="margin-bottom: 10px;">⚠️ ATTENTION: New System Notifications Detected!</div>'
    for n in st.session_state.notifications:
        html_content += f'''
            <div style="background-color: #fff3cd; padding: 10px; border-radius: 5px; margin: 5px 0; border-left: 5px solid #ffecb5; color: #856404;">
                <b>System Notice:</b> {n}
            </div>'''
    html_content += '</div>'
    st.markdown(html_content, unsafe_allow_html=True)

st.title("Team Roster & Staffing System")
# --- TOP OF SCRIPT (After your title) ---
tab_names = ["📅 Calendar", "📝 Request", "🔍 Case Tracker", "🔀 Deviation", "📂 Masterfile", "🔑 Admin"]

# Use the state to control the index
if "active_tab" not in st.session_state:
    st.session_state.active_tab = 0

# Set index=st.session_state.active_tab
tabs = st.tabs(tab_names)
tab_cal, tab_req, tab_case, tab_dev, tab_master, tab_adm = tabs

# --- TAB 1: CALENDAR ---
with tab_cal:
    # 1. ADD THIS LINE: Ensure we fetch the latest data from MongoDB
    load_data_from_db()
    
    # 2. Define your layout columns
    col_main, col_side = st.columns([4, 1])
    
    # 3. Use col_main for the top filters
    with col_main:
        c1, c2 = st.columns([1, 1])
        
        # Get current date
        current_date = date.today()
        
        year = c1.selectbox("Year", [2026, 2027, 2028], key="cal_y")
        
        # Set index to current_date.month - 1 to default to the current month
        month = c2.selectbox(
            "Month", 
            range(1, 13), 
            format_func=lambda x: calendar.month_name[x], 
            index=current_date.month - 1, 
            key="cal_m"
        )

    # 3. Use col_side for the summary/sidebar
    with col_side:
        st.markdown('<div class="side-block">', unsafe_allow_html=True)
        
        st.subheader("Monthly Summary")
        
        st.markdown("**Birthdays:**")
        for name, bday in st.session_state.staff_roster.items():
            if isinstance(bday, date) and bday.month == month:
                st.write(f"- {name}: {bday.strftime('%B %d')}")

        st.markdown("**Holidays:**")
        us_hols = holidays.US(years=year)
        ph_hols = holidays.PH(years=year)
        found_holiday = False
        
        for date_obj, name in sorted(us_hols.items()):
            if date_obj.month == month:
                st.write(f"- [US] {name}: {date_obj.strftime('%B %d')}")
                found_holiday = True
        for date_obj, name in sorted(ph_hols.items()):
            if date_obj.month == month:
                st.write(f"- [PH] {name}: {date_obj.strftime('%B %d')}")
                found_holiday = True
        if not found_holiday: 
            st.write("No holidays this month.")

        st.subheader("Daily View")
        today = date.today()
            # 1. Get the date chosen in your Admin/Config UI
            # Ensure your Admin date picker saves to this key: st.session_state.selected_admin_date
        view_date = st.session_state.get('selected_admin_date', date.today())
            
            # 2. Retrieve data for that specific date
        d_data = st.session_state.calendar_data.get(view_date, {}) 
            
            # 3. Retrieve shift and setup info
            # Note: Updated to match the key 'shift' (which includes PHT/PST) and 'status'
        shift_info = d_data.get('shift', '--') 
        w_setup = d_data.get('status', 'Not Set')
        
        # 4. Display for the selected date
        st.markdown(f"### Date: {view_date.strftime('%B %d, %Y')}")
        st.markdown(f"**Setup:** {w_setup} | **Shift:** {shift_info}")
        st.divider()
        
        # 2. DISPLAY ROLES
        st.write("**Today's Schedule:**")
        
        # 1. Define the roles you are tracking
        roles = ["call", "chat", "mfq", "sme"]
        
        for name in st.session_state.staff_roster:
            # 2. Determine the role for this staff member today
            # We look through the lists in d_data to see where the name is found
            assigned_roles = []
            for r in roles:
                if name in d_data.get(r, []):
                    assigned_roles.append(r.upper())
            
            shift_role = ", ".join(assigned_roles) if assigned_roles else "Unassigned"
            
            # 3. Check for approved requests (Leave/PTO)
            p_status = [r['type'] for r in st.session_state.approved_requests 
                        if r['date'] == today and r['name'] == name]
            p_display = f" ({p_status[0]})" if p_status else ""
            
            st.write(f"- **{name}**: {shift_role}{p_display}")
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    # 4. Render main calendar content
        with col_main:
            cols = st.columns(7)
            for i, d_name in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
                cols[i].markdown(f'<div class="header-cell">{d_name}</div>', unsafe_allow_html=True)
                
            for week in calendar.Calendar(firstweekday=6).monthdayscalendar(year, month):
                cols = st.columns(7)
                for i, day in enumerate(week):
                    if day != 0:
                        d = date(year, month, day)
                        
                        # --- CHECK FOR WEEKEND (Sat=5, Sun=6) ---
                        is_weekend = d.weekday() in [5, 6]
                        
                        if is_weekend:
                            # Block as Rest Day
                            cols[i].markdown(f'<div class="day-block rest-day"><b>{day}</b><br>REST DAY</div>', unsafe_allow_html=True)
                        else:
                            approved = [r for r in st.session_state.approved_requests if r['date'] == d]
                            
                            # --- NICKNAME LOOKUP LOGIC ---
                            display_list = []
                            for r in approved:
                                # Get staff data from roster (assuming structure {'bday': ..., 'nick': ...})
                                staff_info = st.session_state.staff_roster.get(r['name'], {})
                                # Use nickname if available, else fallback to name
                                nick = staff_info.get("nick", r['name'])
                                display_list.append(f"{nick}({r['type']})")
                            
                            req_display = "<br>".join(display_list)
                            
                           # --- 1. Identify who is away today ---
                            away_names = [r['name'] for r in approved]
    
                            # --- 2. Updated lookup helper ---
                            def get_filtered_nicks(full_names):
                                # Filter out anyone who is in the away_names list
                                active_staff = [name for name in full_names if name not in away_names]
                                # Return nicknames for those remaining
                                return ", ".join([st.session_state.staff_roster.get(name, {}).get("nick", name) for name in active_staff])
    
                            data = st.session_state.calendar_data.get(d, {})
                            
                            content = (f"<b>{day}</b><div class='calendar-divider'></div>"
                                       f"<u>{data.get('status', '-')}</u><div class='calendar-divider'></div>"
                                       f"{data.get('shift', '-')}<div class='calendar-divider'></div>"
                                       f"PTO/Wellness: {req_display}<div class='calendar-divider'></div>"
                                       f"Call: {get_filtered_nicks(data.get('call', []))}<div class='calendar-divider'></div>"
                                       f"Chat: {get_filtered_nicks(data.get('chat', []))}<div class='calendar-divider'></div>"
                                       f"MFQ: {get_filtered_nicks(data.get('mfq', []))}<div class='calendar-divider'></div>"
                                       f"SME: {get_filtered_nicks(data.get('sme', []))}")
                            
                            cols[i].markdown(f'<div class="day-block">{content}</div>', unsafe_allow_html=True)

# --- TAB 2: REQUEST ---
with tab_req:
    st.subheader("PTO/Wellness Request")
    
    st.info("💡 **Tip:** Providing your work email is optional.")
    
    with st.form("request_form", clear_on_submit=True):
        # 1. Fetch staff roster from DB
        staff_data = get_staff_list() # Ensure this returns a dict or list of names
        name = st.selectbox("Name", list(staff_data.keys()))
        
        email = st.text_input("Work Email (Optional)")
        req_date = st.date_input("Request Date")
        req_type = st.selectbox("Type", ["PTO", "Wellness"])
        
        submitted = st.form_submit_button("Submit Request")
        
        if submitted:
            # 2. Fetch limits from DB
            limits = get_request_limits() # Returns e.g., {"PTO": 5, "Wellness": 2}
            
            # Count existing requests for this specific date and type
            count_on_date = len([
                r for r in (st.session_state.pending_requests + st.session_state.approved_requests)
                if r["date"] == req_date and r["type"] == req_type
            ])
            
            # Check Duplicates
            is_already_requested = any(
                r["name"] == name and r["date"] == req_date 
                for r in (st.session_state.pending_requests + st.session_state.approved_requests)
            )
            
            # 3. Validation Logic
            if is_already_requested:
                st.warning(f"⚠️ A request for {name} on {req_date} already exists.")
            elif count_on_date >= limits.get(req_type, 0):
                st.error(f"❌ Limit reached for {req_type} on {req_date}. Please choose another date.")
            else:
                st.session_state.pending_requests.append({
                    "name": name, 
                    "date": req_date, 
                    "type": req_type, 
                    "status": "Pending", 
                    "email": email,
                    "viewed": False
                })
                # Trigger a database write here to persist this new request
                save_request_to_db(st.session_state.pending_requests[-1])
                st.success("Request submitted successfully.")

# --- TAB 3: CASE TRACKER ---
with tab_case:
    st.subheader("Log New Case")
    
    # 1. Fetch dropdown data directly from DB
    master_file = fetch_masterfile_from_db() 
    def get_master_values(category):
        row = next((item for item in master_file if item.get('Category') == category), None)
        return row['Values'].split(',') if row else []

    c_types = get_master_values('Contact Type')
    issues = get_master_values('Issue')
    prods = get_master_values('Product Group')
    
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
    
    # 2. Log Case to DB
    if st.button("Log Case"):
        new_case = {"Date": str(date.today()), "Type": c_type, "Issue": issue, "Product Group": prod, "Desc": desc, "Steps": steps, "Status": status, "Extra": extra}
        save_case_to_db(new_case) # Ensure this function is defined
        st.success("Case logged to database successfully!")
        st.rerun()

    st.divider()
    st.subheader("Knowledge Base")
    
    # 3. Filtering
    f1, f2 = st.columns(2)
    f_issue = f1.multiselect("Filter by Issue", issues)
    f_prod = f2.multiselect("Filter by Product Group", prods)

    # 4. Knowledge Base Loop
    cases_list = fetch_cases_from_db() 

    for case in reversed(cases_list):
        if (not f_issue or case['Issue'] in f_issue) and (not f_prod or case['Product Group'] in f_prod):
            with st.container():
                # Layout: Three-dot menu + Content
                col_menu, col_content = st.columns([1, 10])
                
                with col_menu.popover("⋮"):
                    if st.button("Edit", key=f"edit_trigger_{case['_id']}"):
                        st.session_state[f"edit_mode_{case['_id']}"] = True
                    if st.button("Delete", key=f"del_trigger_{case['_id']}"):
                        st.session_state[f"del_mode_{case['_id']}"] = True

                col_content.markdown(f"**Date:** {case['Date']} | **Status:** {case['Status']} | **Issue:** {case['Issue']}")

                # --- EDIT LOGIC (Accessible to all) ---
                if st.session_state.get(f"edit_mode_{case['_id']}"):
                    with st.form(key=f"edit_form_{case['_id']}"):
                        new_desc = st.text_area("Update Description", value=case.get('Desc', ''))
                        if st.form_submit_button("Save Changes"):
                            update_case_in_db(case['_id'], {"Desc": new_desc})
                            st.session_state[f"edit_mode_{case['_id']}"] = False
                            st.rerun()
                        if st.form_submit_button("Cancel"):
                            st.session_state[f"edit_mode_{case['_id']}"] = False
                            st.rerun()

                # --- DELETE LOGIC (Password Protected) ---
                if st.session_state.get(f"del_mode_{case['_id']}"):
                    check_pass = st.text_input("Enter Admin Password to Confirm", type="password", key=f"pass_{case['_id']}")
                    if check_pass == "Password1234":
                        if st.button("Confirm Delete", key=f"confirm_del_{case['_id']}"):
                            delete_case_from_db(case['_id'])
                            st.rerun()
                    elif check_pass:
                        st.error("Incorrect Password")
                        
# --- TAB: DEVIATION ---
with tab_dev:
    st.subheader("Submit Deviation Request")
    
    with st.form("deviation_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            target_date = st.date_input("Target Date", value=date.today())
            manager = st.text_input("Manager", value="Jeff Bote")
            name = st.selectbox("Name", list(st.session_state.staff_roster.keys()))
            shift_time = st.session_state.calendar_data.get(target_date, {}).get("shift", "Not Set")
            st.write(f"**Shift Time:** {shift_time}")
        with col2:
            start_time = st.time_input("Start Time")
            end_time = st.time_input("End Time")
            total_mins = st.number_input("Total Mins", min_value=0)
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
    
    # 1. Filter UI
    with st.expander("Filter Report"):
        f_col1, f_col2, f_col3 = st.columns(3)
        filter_month = f_col1.selectbox("Month", range(1, 13), index=date.today().month-1, key="dev_f_month")
        filter_year = f_col2.number_input("Year", value=date.today().year, key="dev_f_year")
        filter_date = f_col3.date_input("Specific Date (Optional)", value=None, key="dev_f_date")
        apply_filter = st.button("Apply Filter")

    # 2. Fetch and Filter Data
    dev_data = fetch_deviations_from_db()
    if dev_data:
        # Loop through data to display each entry with a menu
        for entry in reversed(dev_data):
            # Apply your filter logic
            e_date = pd.to_datetime(entry['Date']).date()
            if apply_filter:
                if filter_date and e_date != filter_date: continue
                if not filter_date and (e_date.month != filter_month or e_date.year != filter_year): continue
            
            with st.container():
                # Menu + Content
                col_menu, col_content = st.columns([1, 10])
                with col_menu.popover("⋮"):
                    if st.button("Edit", key=f"edit_trig_{entry['_id']}"):
                        st.session_state[f"edit_dev_{entry['_id']}"] = True
                    if st.button("Delete", key=f"del_trig_{entry['_id']}"):
                        st.session_state[f"del_dev_{entry['_id']}"] = True
                
                col_content.markdown(f"**{e_date}** | {entry['Name']} | {entry['Reason']}")

                # --- EDIT LOGIC ---
                if st.session_state.get(f"edit_dev_{entry['_id']}"):
                    with st.form(key=f"edit_f_{entry['_id']}"):
                        new_r = st.text_area("Edit Reason", value=entry.get('Reason', ''))
                        new_m = st.number_input("Edit Mins", value=entry.get('Total Mins', 0))
                        if st.form_submit_button("Update"):
                            update_deviation_in_db(entry['_id'], {"Reason": new_r, "Total Mins": new_m})
                            st.session_state[f"edit_dev_{entry['_id']}"] = False
                            st.rerun()

                # --- DELETE LOGIC (Password Protected) ---
                if st.session_state.get(f"del_dev_{entry['_id']}"):
                    check_pass = st.text_input("Enter Admin Password", type="password", key=f"p_{entry['_id']}")
                    if check_pass == "Password1234":
                        if st.button("Confirm Delete", key=f"conf_del_{entry['_id']}"):
                            delete_deviation_from_db(entry['_id'])
                            st.session_state[f"del_dev_{entry['_id']}"] = False
                            st.rerun()
                    elif check_pass:
                        st.error("Invalid Password")

        # 4. CSV Download
        df = pd.DataFrame(dev_data)
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("Extract Report as CSV", csv, "deviation_report.csv", "text/csv")
    else:
        st.write("No deviation requests found.")

# --- TAB 4: MASTERFILE ---
with tab_master:
    if not st.session_state.admin_authenticated:
        if st.text_input("Enter Password", type="password") == "Password1234": 
            st.session_state.admin_authenticated = True
            st.rerun()
    else:
        # Create columns to align the header and the button
        col_m1, col_m2 = st.columns([4, 1])
        
        with col_m1:
            st.subheader("System Masterfile")
        with col_m2:
            if st.button("Save Masterfile Changes"):
                # 1. Update the session state with the editor's current content
                # 2. Call your database function to persist the data
                # Assuming your database function takes the dataframe or dict
                save_masterfile_to_db(st.session_state.master_data) 
                
                st.success("Masterfile updated in database.")
                st.rerun()
        
        # Display the editor below the header/button row
        # We assign the result of data_editor back to session_state
        st.session_state.master_data = st.data_editor(st.session_state.master_data, num_rows="dynamic")

# --- TAB 5: ADMIN ---
with tab_adm:
    if not st.session_state.admin_authenticated:
        if st.text_input("Admin Password", type="password") == "Password1234": 
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
                
            # 1. Fetch current list from DB
            roster = get_staff_list() 
                
            # 2. Header
            c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
            c1.write("**Name**")
            c2.write("**Nickname**")
            c3.write("**Birthday**")
            c4.write("**Actions**")
            st.divider()
    
            # 3. Loop through DB data
            for name, data in roster.items():
                c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
                c1.write(name)
                c2.write(data.get("nick", ""))
                c3.write(data['bday'].strftime('%B %d'))
                
                # Actions
                if c4.button("Remove", key=f"del_{name}"):
                    delete_staff(name)
                    st.rerun()
    
            # 4. Entry Form (Using MongoDB Helper)
            st.markdown("---")
            new_name = st.text_input("Staff Name")
            new_nick = st.text_input("Nickname")
            new_bday = st.date_input("Birthday", min_value=date(1950, 1, 1), key="new_bday")
            rest_days = st.multiselect("Select Rest Days", 
                           ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
            
            if st.button("Add Staff"):
                if new_name:
                    # Convert date to datetime before passing to save_staff
                    bday_datetime = datetime.combine(new_bday, time.min)
                    
                    save_staff(new_name, {
                        "bday": bday_datetime, # Use the converted datetime
                        "nick": new_nick if new_nick else new_name,
                        "rest_days": rest_days
                    })
                    st.success(f"Added {new_name}!")
                    st.rerun()
            st.divider()
    
            # --- DAILY CONFIG---
            st.subheader("Configuration")
            
            # Selected Date View
            st.session_state.selected_admin_date = st.date_input("Select Date to View/Edit", date.today())
            
            st.markdown("---")
            st.subheader("Important Notifications")
            target_d = st.date_input("Target Date", key="config_target_date")
            admin_sender_email = st.text_input("Your Work Email (Sender Address)")
            
            new_notif = st.text_input("Add New System Notification")
            if st.button("Post Notification"): 
                if new_notif:
                    st.session_state.notifications.append(new_notif)
                    st.success("Notification posted!")
                    st.rerun()
            
            # --- Daily Config ---
            st.subheader("Daily Config")
            config_mode = st.radio("Apply to:", ["Single Date", "Date Range", "Full Month"])
            
            # Date selection logic
            if config_mode == "Single Date": 
                target_dates = [st.date_input("Date", key="cfg_d")]
            elif config_mode == "Date Range": 
                dr = st.date_input("Range", [], key="cfg_dr")
                target_dates = pd.date_range(dr[0], dr[1]).date if len(dr)==2 else []
            else:
                sm = st.date_input("Month", value=date.today(), key="cfg_m")
                target_dates = pd.date_range(f"{sm.year}-{sm.month}-01", periods=31).date
                target_dates = [d for d in target_dates if d.month == sm.month]
    
            # --- Limits, Shifts, and Status ---
            st.session_state.limits["PTO"] = st.number_input("Max PTO", value=st.session_state.limits.get("PTO", 1))
            st.session_state.limits["Wellness"] = st.number_input("Max Wellness", value=st.session_state.limits.get("Wellness", 1))
            
            start_t = st.time_input("Shift Start", value=time(9, 0))
            end_t = st.time_input("Shift End", value=time(18, 0))
            timezone = "PHT"
            
            # Format display
            shift_display = f"{start_t.strftime('%I:%M %p')} - {end_t.strftime('%I:%M %p')} {timezone}"
            st.write(f"Selected Shift: **{shift_display}**")
            
            setup = st.selectbox("Status", ["PROD - ONSITE", "PROD - WAH", "HOLIDAY"])
            
            # --- Assignment logic ---
            # Ensure target_dates is a list to avoid ValueError
            safe_target_dates = target_dates if isinstance(target_dates, (list, tuple)) else []
            # Safely select the first date or default to today
            base_date = safe_target_dates[0] if len(safe_target_dates) > 0 else date.today()
            unavailable = [r['name'] for r in st.session_state.approved_requests if r['date'] == base_date]
            available = [n for n in roster.keys() if n not in unavailable]
            
            call = st.multiselect("Assign Call", available)
            chat = st.multiselect("Assign Chat", available)
            mfq = st.multiselect("Assign MFQ", available)
            sme = st.multiselect("Assign SME", available)
            
            # --- Locate this block in your tab_adm ---
            if st.button("Save Config"):
                # 1. Update session state (for the UI to reflect changes immediately)
                for d in target_dates:
                    st.session_state.calendar_data[d] = {
                        "shift": shift_display, 
                        "status": setup, 
                        "call": call, 
                        "chat": chat,
                        "mfq": mfq,
                        "sme": sme
                    }
                
                # 2. SAVE TO MONGODB: Convert date keys to strings for database compatibility
                # MongoDB keys cannot be date objects; they must be strings
                serializable_data = {str(k): v for k, v in st.session_state.calendar_data.items()}
                
                # Push to your existing MongoDB collection
                collection.update_one(
                    {"type": "calendar_data"},
                    {"$set": {"data": serializable_data}},
                    upsert=True
                )
                
                st.success("Configuration saved to database!")
                st.rerun() # Refresh so the main calendar view picks up the new data
        
        with col2:
            st.subheader("Approval Center")
            if st.session_state.pending_requests:
                for idx, req in enumerate(st.session_state.pending_requests):
                    render_request(req, idx, "req")
            
            # --- DISPLAY ADMIN MESSAGES ---
            if "admin_msg" not in st.session_state: st.session_state.admin_msg = None
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
            wellness_pending = [r for r in st.session_state.pending_requests if r['type'] == 'Wellness']
            if wellness_pending:
                for req in wellness_pending:
                    master_idx = st.session_state.pending_requests.index(req)
                    render_request(req, master_idx, "wellness")
            else:
                st.write("No pending Wellness requests.")

            # --- PTO SECTION ---
            st.markdown("### ✈️ PTO Requests")
            pto_pending = [r for r in st.session_state.pending_requests if r['type'] == 'PTO']
            if pto_pending:
                for req in pto_pending:
                    master_idx = st.session_state.pending_requests.index(req)
                    render_request(req, master_idx, "pto")
            else:
                st.write("No pending PTO requests.")

            st.divider()

            # --- APPROVED HISTORY ---
            st.subheader("✅ Approved History")
            
            # 1. Fetch from DB instead of session state
            # Assume fetch_approved_requests_from_db() returns a list of approved dicts
            all_approved_from_db = fetch_approved_requests_from_db()
            
            # 2. Filter logic using the fetched data
            month_to_filter = st.session_state.get("cal_m", date.today().month)
            
            app_wellness = [r for r in all_approved_from_db 
                            if r['type'] == "Wellness" and r['date'].month == month_to_filter]
            app_pto = [r for r in all_approved_from_db 
                       if r['type'] == "PTO" and r['date'].month == month_to_filter]
            
            if app_wellness:
                st.markdown("#### Approved Wellness")
                st.table(pd.DataFrame(app_wellness))
            if app_pto:
                st.markdown("#### Approved PTO")
                st.table(pd.DataFrame(app_pto))
            if not app_wellness and not app_pto:
                st.write("No approved requests for this month.")
   
