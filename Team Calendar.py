from datetime import date, time, datetime
import streamlit as st
from pymongo.mongo_client import MongoClient
import calendar
import pandas as pd
import holidays

# --- INITIAL CONFIG & STATE ---
st.set_page_config(layout="wide", page_title="Team Roster & Staffing System")

# --- DATABASE ---
uri = st.secrets["mongo"]["uri"]
@st.cache_resource
def get_db_collection():
    client = MongoClient(uri)
    return client["my_database"]["my_collection"]
collection = get_db_collection()

# --- INITIALIZE STATE ---
if "staff_roster" not in st.session_state: 
    st.session_state.staff_roster = {"Agent A": {"bday": date(2000, 1, 1), "nick": "A"}, "Agent B": {"bday": date(1995, 5, 20), "nick": "B"}}
if "deviation_requests" not in st.session_state: st.session_state.deviation_requests = []
if "pending_requests" not in st.session_state: st.session_state.pending_requests = []
if "approved_requests" not in st.session_state: st.session_state.approved_requests = []
if "limits" not in st.session_state: st.session_state.limits = {"PTO": 1, "Wellness": 1}
if "admin_authenticated" not in st.session_state: st.session_state.admin_authenticated = False
if "cases" not in st.session_state: st.session_state.cases = []
if "notifications" not in st.session_state: st.session_state.notifications = []
if "calendar_data" not in st.session_state: st.session_state.calendar_data = {}
if "master_data" not in st.session_state: 
    st.session_state.master_data = pd.DataFrame({"Category": ["Contact Type", "Issue", "Product Group"], "Values": ["Call,Chat,Email", "Tech,Billing", "Hardware,Soft"]})

# --- SHARED DATE SELECTION ---
# Defining these here makes them accessible to both Calendar and Admin tabs
col_top1, col_top2 = st.sidebar.columns(2)
current_date = date.today()
year = col_top1.selectbox("Year", [2026, 2027, 2028], key="g_year")
month = col_top2.selectbox("Month", range(1, 13), format_func=lambda x: calendar.month_name[x], index=current_date.month - 1, key="g_month")

# --- HANDLER FUNCTIONS ---
def handle_approval(req, original_idx):
    req["status"] = "Approved"
    st.session_state.approved_requests.append(req)
    st.session_state.pending_requests.pop(original_idx)
    st.session_state.admin_msg = ("success", f"Approved {req['name']}")
    st.rerun()

def render_request(req, idx, prefix):
    safe_name = req.get('name', '').replace(' ', '_')
    unique_id = f"{prefix}_{idx}_{safe_name}"
    with st.expander(f"{req['name']} - {req['date']} ({req['type']})"):
        if st.button("Approve", key=f"app_{unique_id}"):
            handle_approval(req, idx)
        if st.button("Deny", key=f"den_{unique_id}"):
            st.session_state.pending_requests.pop(idx)
            st.rerun()

# --- APP LAYOUT ---
tab_names = ["📅 Calendar", "📝 Request", "🔍 Case Tracker", "🔀 Deviation", "📂 Masterfile", "🔑 Admin"]
tabs = st.tabs(tab_names)
    
    # Close the div
    st.markdown('</div>', unsafe_allow_html=True)

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

# --- INITIALIZE STATE ---
if "deviation_requests" not in st.session_state:
    st.session_state.deviation_requests = []
if "active_tab" not in st.session_state:
    st.session_state.active_tab = 0
if "calendar_data" not in st.session_state: st.session_state.calendar_data = {}
if "pending_requests" not in st.session_state: st.session_state.pending_requests = []
if "approved_requests" not in st.session_state: st.session_state.approved_requests = []
if "staff_roster" not in st.session_state: st.session_state.staff_roster = {"Agent A": date(2000, 1, 1), "Agent B": date(1995, 5, 20)}
if "limits" not in st.session_state: st.session_state.limits = {"PTO": 1, "Wellness": 1}
if "admin_authenticated" not in st.session_state: st.session_state.admin_authenticated = False
if "cases" not in st.session_state: st.session_state.cases = []
if "master_data" not in st.session_state: 
    st.session_state.master_data = pd.DataFrame({"Category": ["Contact Type", "Issue", "Product Group"], "Values": ["Call,Chat,Email", "Tech,Billing", "Hardware,Soft"]})
if "notifications" not in st.session_state: st.session_state.notifications = []

st.set_page_config(layout="wide", page_title="Team Roster & Staffing System")

# --- CSS STYLES ---
st.markdown("""
    <style>
    /* Import Google Font */
    @import url('https://fonts.googleapis.com/css2?family=Quicksand:wght@400;600&display=swap');
    
    /* Apply Font */
    html, body, [class*="css"] {
        font-family: 'Quicksand', sans-serif !important;
    }
    
    h1, h2, h3 {
        font-family: 'Quicksand', sans-serif !important;
        font-weight: 600;
    }

    /* Component Styling */
    .side-block {font-family: 'Quicksand', sans-serif !important; font-size: 10px !important; line-height: 1.2; }
    .day-block { border-radius: 15px; padding: 10px; height: auto; min-height: 140px; font-size: 11px; background-color: #ffffff; border: 1px solid #eef0f5; margin: 4px; display: flex; flex-direction: column; }
    .calendar-divider { border-top: 1px solid #e0e0e0; margin: 5px 0; width: 100%; }
    
    div.stButton > button { background: linear-gradient(90deg, #7b61ff 0%, #3b82f6 100%); color: white; border-radius: 12px; font-weight: 600; }
    
    .header-cell { font-weight: bold; text-align: center; color: #7b61ff; padding-bottom: 10px; }
    
    .alert-container { border-radius: 20px; border: 2px solid #ff4d4d; padding: 15px; background-color: #fff5f5; margin-bottom: 20px; }
    .flash-red { color: #ff4d4d; font-weight: bold; text-align: center; }
    
    .knowledge-card { border: none; padding: 20px; margin-bottom: 15px; border-radius: 20px; background-color: #ffffff; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
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
    # 1. Define your layout columns first
    col_main, col_side = st.columns([4, 1])
    
    # 2. Use col_main for the top filters
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
    
    # Instruction added here
    st.info("💡 **Tip:** Providing your work email is optional. If you provide it, you will receive an automatic notification once your request status is updated.")
    
    with st.form("request_form", clear_on_submit=True):
        name = st.selectbox("Name", list(st.session_state.staff_roster.keys()))
        email = st.text_input("Work Email (Optional)")
        req_date = st.date_input("Request Date")
        req_type = st.selectbox("Type", ["PTO", "Wellness"])
        
        submitted = st.form_submit_button("Submit Request")
        if submitted:
            # --- DUPLICATE CHECK ---
            # Check both pending and approved lists to ensure no conflicts
            is_already_requested = any(
                r["name"] == name and r["date"] == req_date 
                for r in (st.session_state.pending_requests + st.session_state.approved_requests)
            )
            
            if is_already_requested:
                st.warning(f"⚠️ A request for {name} on {req_date} already exists.")
            else:
                st.session_state.pending_requests.append({
                    "name": name, 
                    "date": req_date, 
                    "type": req_type, 
                    "status": "Pending", 
                    "email": email,
                    "viewed": False # Ensure this is added for your rendering logic
                })
                st.success("Request submitted successfully.")

# --- TAB 3: CASE TRACKER ---
with tab_case:
    # 1. Define the columns first
    col_h1, col_h2 = st.columns([4, 1])
    with col_h1:
        st.subheader("Log New Case")
    with col_h2:
        if st.button("Save Case Tracker"):
            st.success("Case tracker data saved!")
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
    
    if st.button("Log Case"):
        st.session_state.cases.append({"Date": date.today(), "Type": c_type, "Issue": issue, "Product Group": prod, "Desc": desc, "Steps": steps, "Status": status, "Extra": extra, "Image": uploaded_file})
        st.success("Case logged successfully!")
        st.rerun()

    st.divider()
    st.subheader("Knowledge Base")
    f1, f2 = st.columns(2)
    f_issue = f1.multiselect("Filter by Issue", issues)
    f_prod = f2.multiselect("Filter by Product Group", prods)
    for case in reversed(st.session_state.cases):
        if (not f_issue or case['Issue'] in f_issue) and (not f_prod or case['Product Group'] in f_prod):
            with st.container():
                st.markdown(f"""
                <div class="knowledge-card">
                    <b>Date:</b> {case['Date']} | <b>Status:</b> {case['Status']}<br>
                    <b>Contact:</b> {case['Type']} | <b>Issue:</b> {case['Issue']} | <b>Group:</b> {case['Product Group']}<br>
                    <b>Description:</b> {case['Desc']}<br>
                    <b>Steps Taken:</b> {case['Steps']}<br>
                    {"<b>Extra Info:</b> " + case['Extra'] if case['Extra'] else ""}
                </div>
                """, unsafe_allow_html=True)
                if case['Image']: st.image(case['Image'], caption="Case Screenshot", width=300)

# --- TAB: DEVIATION ---
    with tab_dev:  # Ensure this tab is defined in your main st.tabs list
        st.subheader("Submit Deviation Request")
        
        with st.form("deviation_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                target_date = st.date_input("Target Date", value=date.today())
                manager = st.text_input("Manager", value="Jeff Bote")
                name = st.selectbox("Name", list(st.session_state.staff_roster.keys()))
                # Retrieve shift from Admin configuration
                shift_time = st.session_state.calendar_data.get(target_date, {}).get("shift", "Not Set")
                st.write(f"**Shift Time:** {shift_time}")
                
            with col2:
                start_time = st.time_input("Start Time")
                end_time = st.time_input("End Time")
                total_mins = st.number_input("Total Mins", min_value=0)
                aux = st.text_input("Aux")
                reason = st.text_area("Reason of Deviation")
                
            submitted = st.form_submit_button("Submit Deviation Request")
            if submitted:
                st.session_state.deviation_requests.append({
                    "Date": target_date,
                    "Manager": manager,
                    "Name": name,
                    "Shift Time": shift_time,
                    "Start Time": str(start_time),
                    "End Time": str(end_time),
                    "Total Mins": total_mins,
                    "Aux": aux,
                    "Reason": reason
                })
                st.success("Deviation request submitted!")

    # --- DEVIATION REPORT SECTION ---
        st.divider()
        c_head1, c_head2 = st.columns([3, 1])
        c_head1.subheader("Deviation Request Report")
        
        # 1. Filter UI
        with st.expander("Filter Report"):
            f_col1, f_col2, f_col3 = st.columns(3)
            # Using keys to ensure these widgets don't conflict with others in the app
            filter_month = f_col1.selectbox("Month", range(1, 13), index=date.today().month-1, key="dev_f_month")
            filter_year = f_col2.number_input("Year", value=date.today().year, key="dev_f_year")
            filter_date = f_col3.date_input("Specific Date (Optional)", value=None, key="dev_f_date")
            
            apply_filter = st.button("Apply Filter")

        # 2. Filtering Logic
        if st.session_state.deviation_requests:
            df = pd.DataFrame(st.session_state.deviation_requests)
            
            # Ensure the 'Date' column is in datetime format for accurate filtering
            df['Date'] = pd.to_datetime(df['Date']).dt.date
            
            filtered_df = df.copy()
            
            if apply_filter:
                if filter_date:
                    filtered_df = df[df['Date'] == filter_date]
                else:
                    filtered_df = df[(df['Date'].apply(lambda x: x.month) == filter_month) & 
                                    (df['Date'].apply(lambda x: x.year) == filter_year)]
            
            # 3. Display Result
            st.table(filtered_df)
            
            # 4. Extract/Download button
            csv = filtered_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Extract Report as CSV", 
                data=csv, 
                file_name="deviation_report.csv", 
                mime="text/csv"
            )
        else:
            st.write("No deviation requests submitted yet.")

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
                st.success("Masterfile updated.")
                st.rerun()
        
        # Display the editor below the header/button row
        st.session_state.master_data = st.data_editor(st.session_state.master_data, num_rows="dynamic")

# --- TAB 5: ADMIN ---
with tab_adm:
    if not st.session_state.admin_authenticated:
        if st.text_input("Admin Password", type="password") == "Password1234": 
            st.session_state.admin_authenticated = True
            st.rerun()
    else:
        # --- TOP LEVEL ADMIN UI ---
        if st.session_state.pending_requests:
            st.info(f"⚠️ You have {len(st.session_state.pending_requests)} pending request(s).")
        
        if st.button("Save Admin Changes", key="btn_top_admin_save"):
            st.success("Admin configuration saved.")
        st.divider()

        col1, col2 = st.columns(2)

        with col1:

            # Roster Management
            st.subheader("Roster Management")

            # Initialize edit state if not exists
            if "edit_staff" not in st.session_state: st.session_state.edit_staff = None

            # Header row
            c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
            c1.write("**Name**")
            c2.write("**Nickname**")
            c3.write("**Birthday**")
            c4.write("**Actions**")
            st.divider()

            # Loop through roster
            for name in list(st.session_state.staff_roster.keys()):
                data = st.session_state.staff_roster[name]
                
                if st.session_state.edit_staff == name:
                    # EDIT MODE
                    with st.container():
                        new_name = st.text_input("Edit Name", value=name, key=f"edit_name_{name}")
                        new_nick = st.text_input("Edit Nickname", value=data.get("nick", ""), key=f"edit_nick_{name}")
                        new_bday = st.date_input("Edit Birthday", value=data["bday"], key=f"edit_bday_{name}")
                        if st.button("Save Changes", key=f"save_{name}"):
                            st.session_state.staff_roster[name] = {"bday": new_bday, "nick": new_nick}
                            st.session_state.edit_staff = None
                            st.rerun()
                else:
                    # DISPLAY MODE (Table-like rows)
                    c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
                    c1.write(name)
                    c2.write(data.get("nick", ""))
                    c3.write(data['bday'].strftime('%B %d'))
                    
                    # Actions in the 4th column
                    sub_c1, sub_c2 = c4.columns(2)
                    if sub_c1.button("Edit", key=f"edit_{name}"):
                        st.session_state.edit_staff = name
                        st.rerun()
                    if sub_c2.button("Remove", key=f"del_{name}"):
                        del st.session_state.staff_roster[name]
                        st.rerun()

            # Entry Form
            st.markdown("---")
            new_name = st.text_input("Staff Name")
            new_nick = st.text_input("Nickname") # This captures the input
            new_bday = st.date_input("Birthday", min_value=date(1950, 1, 1))
            rest_days = st.multiselect("Select Rest Days", 
                           ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
            
            if st.button("Add Staff"): 
                if new_name: 
                    # This saves the nickname (new_nick) into the dictionary
                    st.session_state.staff_roster[new_name] = {
                        "bday": new_bday, 
                        "rest_days": rest_days,
                        "nick": new_nick if new_nick else ""}
                        
                    st.success(f"Added {new_name} to roster!")
                    st.rerun()

            st.divider()

            # --- DAILY CONFIG---
            chosen_date = st.date_input("Select Date to View/Edit", date.today())
            st.session_state.selected_admin_date = chosen_date
            st.subheader("Important Notifications")
            target_d = st.date_input("Target Date", key="config_target_date")
            admin_sender_email = st.text_input("Your Work Email (Sender Address)")
            
            new_notif = st.text_input("Add New System Notification")
            if st.button("Post Notification"): 
                if new_notif:
                    st.session_state.notifications.append(new_notif)
                    st.success("Notification posted!")
                    st.rerun()
            
            st.subheader("Daily Config")
            # 1. Choose the scope: Single Date vs. Range
            config_mode = st.radio("Apply settings to:", ["Single Date", "Date Range", "Full Month"])

            target_d = None
            start_date = None
            end_date = None
            timezone = "PHT" # Added Timezone

            # 1. Ensure target_d is defined based on the mode
            if config_mode == "Single Date":
                target_d = st.date_input("Target Date", key="cfg_target_d")
            elif config_mode == "Date Range":
                date_range = st.date_input("Select Date Range", [], key="cfg_date_range")
                # Default to today if range is empty, otherwise use the start of the range
                target_d = date_range[0] if date_range else date.today()
                if len(date_range) == 2:
                    start_date, end_date = date_range
            elif config_mode == "Full Month":
                selected_month = st.date_input("Select Month", value=date.today(), key="cfg_month")
                target_d = selected_month # Default to the month start

            # 2. Add a safety check before using strftime
            if target_d:
                day_name = target_d.strftime("%A")
                # ... (rest of your logic using day_name)
            else:
                day_name = date.today().strftime("%A") # Fallback

            st.session_state.limits["PTO"] = st.number_input("Max PTO", value=st.session_state.limits["PTO"])
            st.session_state.limits["Wellness"] = st.number_input("Max Wellness", value=st.session_state.limits["Wellness"])
            
            start_t = st.time_input("Shift Start", value=time(9, 0))
            end_t = st.time_input("Shift End", value=time(18, 0))

            # 2. Create the 12-hour string representation with Timezone
            start_12hr = start_t.strftime("%I:%M %p")
            end_12hr = end_t.strftime("%I:%M %p")
            shift_display = f"{start_12hr} - {end_12hr} {timezone}"

            # 3. Use these variables for your display
            st.write(f"Selected Shift: **{shift_display}**")
            
            setup = st.selectbox("Status", ["PROD - ONSITE", "PROD - WAH", "HOLIDAY"])
            
            import calendar

            # 1. Determine the day of the week for the selected date
            day_name = target_d.strftime("%A") 

            # 2. Get list of staff who have approved requests for this date
            unavailable = [r['name'] for r in st.session_state.approved_requests if r['date'] == target_d]

            # 3. Filter staff:
            # - Must not be in the 'unavailable' list
            # - Must not have the current day_name in their 'rest_days' list
            available_staff = [
                name for name, info in st.session_state.staff_roster.items() 
                if name not in unavailable and day_name not in info.get("rest_days", [])
            ]
            call = st.multiselect("Assign Call", available_staff)
            chat = st.multiselect("Assign Chat", available_staff)
            mfq = st.multiselect("Assign MFQ", available_staff)
            sme = st.multiselect("Assign SME", available_staff)
            
            if st.button("Save Config"):
                dates_to_update = []
                if config_mode == "Single Date":
                    dates_to_update = [target_d]
                elif config_mode == "Date Range" and start_date and end_date:
                    dates_to_update = pd.date_range(start_date, end_date).date
                elif config_mode == "Full Month":
                    dates_to_update = pd.date_range(
                        start=f"{selected_month.year}-{selected_month.month}-01", 
                        end=pd.Period(f"{selected_month.year}-{selected_month.month}", freq='M').end_time
                    ).date

                for d in dates_to_update:
                    # Corrected: Use 'd' instead of 'target_d' so every date in the range gets saved
                    st.session_state.calendar_data[d] = {
                        "shift": shift_display,
                        "status": setup, 
                        "call": call, 
                        "chat": chat, 
                        "mfq": mfq, 
                        "sme": sme
                    }
                st.success(f"Configuration saved for {len(dates_to_update)} day(s).")
        
        with col2:
            st.subheader("Approval Center")

            # --- DISPLAY ADMIN MESSAGES ---
            # This block handles messages at the top
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
            # Properly un-indented so it always renders
            st.markdown("### 🌿 Wellness Requests")
            wellness_pending = [r for r in st.session_state.pending_requests if r['type'] == 'Wellness']
            if wellness_pending:
                for req in wellness_pending:
                    master_idx = st.session_state.pending_requests.index(req)
                    render_request(req, master_idx, "wellness")
            else:
                st.write("No pending Wellness requests.")

            # --- PTO SECTION ---
            # Properly un-indented so it always renders
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
            # Displaying approved requests based on the current month
            app_wellness = [r for r in st.session_state.approved_requests if r['type'] == "Wellness" and r['date'].month == month]
            app_pto = [r for r in st.session_state.approved_requests if r['type'] == "PTO" and r['date'].month == month]

            if app_wellness:
                st.markdown("#### Approved Wellness")
                st.table(pd.DataFrame(app_wellness))
            if app_pto:
                st.markdown("#### Approved PTO")
                st.table(pd.DataFrame(app_pto))
            if not app_wellness and not app_pto:
                st.write("No approved requests for this month.")
