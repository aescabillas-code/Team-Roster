import streamlit as st
import calendar
from datetime import datetime, date
import pandas as pd

# --- INITIALIZE STATE ---
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
    /* Global Background */
    body { background-color: #f7f7f9; }
    .stApp { background-color: #f7f7f9; }
    
    /* Calendar Day Block Styling */
    .day-block { 
        border-radius: 15px; 
        padding: 10px; 
        height: auto; 
        min-height: 140px; 
        font-size: 11px; 
        background-color: #ffffff; 
        border: 1px solid #eef0f5; 
        margin: 4px;
        transition: transform 0.2s;
        word-wrap: break-word;
        display: flex;
        flex-direction: column;
    }
    
    /* Separator for items within calendar day */
    .calendar-divider {
        border-top: 1px solid #e0e0e0;
        margin: 5px 0;
        width: 100%;
    }
    
    /* Buttons */
    div.stButton > button {
        background: linear-gradient(90deg, #7b61ff 0%, #3b82f6 100%);
        color: white;
        border: none;
        border-radius: 12px;
        padding: 10px 20px;
        font-weight: 600;
        box-shadow: 0 4px 10px rgba(123, 97, 255, 0.3);
    }
    
    /* Headers and Text */
    .header-cell { font-weight: bold; text-align: center; color: #7b61ff; padding-bottom: 10px; }
    
    /* Alerts */
    .alert-container { border-radius: 20px; border: 2px solid #ff4d4d; padding: 15px; background-color: #fff5f5; margin-bottom: 20px; }
    .flash-red { color: #ff4d4d; font-weight: bold; text-align: center; }
    
    /* Input/Card */
    input, select, textarea { border-radius: 12px !important; border: 1px solid #e0e0e0 !important; }
    .knowledge-card { border: none; padding: 20px; margin-bottom: 15px; border-radius: 20px; background-color: #ffffff; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
    </style>
""", unsafe_allow_html=True)

# --- TOP FLASHING NOTIFICATION BAR ---
if st.session_state.notifications or st.session_state.pending_requests:
    st.markdown('<div class="alert-container"><div class="flash-red">⚠️ ATTENTION: Pending Requests or New System Notifications Detected!</div></div>', unsafe_allow_html=True)

st.title("Team Roster & Staffing System")
tab_cal, tab_req, tab_case, tab_master, tab_adm = st.tabs(["📅 Calendar", "📝 Request", "🔍 Case Tracker", "📂 Masterfile", "🔑 Admin"])

# --- TAB 1: CALENDAR ---
with tab_cal:
    c1, c2 = st.columns([1, 1])
    year = c1.selectbox("Year", [2026, 2027, 2028], key="cal_y")
    month = c2.selectbox("Month", range(1, 13), format_func=lambda x: calendar.month_name[x], key="cal_m")
    col_main, col_side = st.columns([4, 1])
import holidays  # Make sure to import this at the top of your script

with col_side:
    st.subheader("Monthly Summary")
    
    # --- Birthday Display ---
    st.markdown("**Birthdays:**")
    for name, bday in st.session_state.staff_roster.items():
        if isinstance(bday, date) and bday.month == month:
            st.write(f"- {name}: {bday.strftime('%B %d')}")

    # --- Holiday Display ---
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
    d_data = st.session_state.calendar_data.get(date.today(), {})
    st.table({"Role": ["Status", "Shift", "Call", "Chat", "MFQ", "SME", "PTO/W"], 
                  "Data": [d_data.get(r, '-') for r in ['status', 'shift', 'call', 'chat', 'mfq', 'sme', 'requests']]})
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
                    req_display = "<br>".join([f"{r['name']}({r['type']})" for r in approved])
                    data = st.session_state.calendar_data.get(d, {})
                    # Updated content with dividers
                    content = (f"<b>{day}</b><div class='calendar-divider'></div>"
                               f"<u>{data.get('status', '-')}</u><div class='calendar-divider'></div>"
                               f"{data.get('shift', '-')}<div class='calendar-divider'></div>"
                               f"PTO/W: {req_display}<div class='calendar-divider'></div>"
                               f"C: {', '.join(data.get('call', []))}<div class='calendar-divider'></div>"
                               f"Ch: {', '.join(data.get('chat', []))}<div class='calendar-divider'></div>"
                               f"M: {', '.join(data.get('mfq', []))}<div class='calendar-divider'></div>"
                               f"S: {', '.join(data.get('sme', []))}")
                    cols[i].markdown(f'<div class="day-block">{content}</div>', unsafe_allow_html=True)

# --- TAB 2: REQUESTS ---
with tab_req:
    st.subheader("Submit PTO/Wellness Request")
    st.info("Please provide your work email if you wish to receive a notification regarding your request status.")
    name = st.selectbox("Name", list(st.session_state.staff_roster.keys()), key="req_name")
    email = st.text_input("Work Email (Optional)")
    req_date = st.date_input("Request Date", key="req_date")
    req_type = st.selectbox("Type", ["PTO", "Wellness"], key="req_type")
    if st.button("Submit Request"):
        st.session_state.pending_requests.append({"name": name, "date": req_date, "type": req_type, "status": "Pending", "email": email})
        st.success("Request submitted.")

# --- TAB 3: CASE TRACKER ---
with tab_case:
    st.subheader("Log New Case")
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

# --- TAB 4: MASTERFILE ---
with tab_master:
    if not st.session_state.admin_authenticated:
        if st.text_input("Enter Password", type="password") == "Password1234": st.session_state.admin_authenticated = True; st.rerun()
    else:
        st.subheader("System Masterfile")
        st.session_state.master_data = st.data_editor(st.session_state.master_data, num_rows="dynamic")

# --- TAB 5: ADMIN ---
with tab_adm:
    if not st.session_state.admin_authenticated:
        if st.text_input("Admin Password", type="password") == "Password1234": st.session_state.admin_authenticated = True; st.rerun()
    else:
        target_d = st.date_input("Target Date")
        admin_sender_email = st.text_input("Your Work Email (Sender Address)")
        
        st.subheader("Important Notifications")
        new_notif = st.text_input("Add New System Notification")
        if st.button("Post Notification"): st.session_state.notifications.append(new_notif); st.rerun()
        for n in st.session_state.notifications: st.warning(n)

        unavailable = [r['name'] for r in st.session_state.approved_requests if r['date'] == target_d]
        available_staff = [s for s in st.session_state.staff_roster.keys() if s not in unavailable]
        
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Roster Management")
            st.write("### Current Roster")
            
            # Display roster with a delete button for each
            for name in list(st.session_state.staff_roster.keys()):
                c_roster1, c_roster2 = st.columns([3, 1])
                bday = st.session_state.staff_roster[name]
                c_roster1.write(f"**{name}** ({bday.strftime('%B %d')})")
                if c_roster2.button("Remove", key=f"del_{name}"):
                    del st.session_state.staff_roster[name]
                    st.rerun()

            st.divider()
            new_name = st.text_input("New Staff Name")
            new_bday = st.date_input("Birthday", min_value=date(1950, 1, 1))
            if st.button("Add Staff"): 
                if new_name:
                    st.session_state.staff_roster[new_name] = new_bday
                    st.rerun()
                else:
                    st.error("Please enter a staff name.")
            st.subheader("Daily Config")
            st.session_state.limits["PTO"] = st.number_input("Max PTO", value=st.session_state.limits["PTO"])
            st.session_state.limits["Wellness"] = st.number_input("Max Wellness", value=st.session_state.limits["Wellness"])
            start_t, end_t = st.time_input("Shift Start"), st.time_input("Shift End")
            setup = st.selectbox("Status", ["PROD - ONSITE", "PROD - WAH", "HOLIDAY"])
            call = st.multiselect("Assign Call", available_staff)
            chat = st.multiselect("Assign Chat", available_staff)
            mfq = st.multiselect("Assign MFQ", available_staff)
            sme = st.multiselect("Assign SME", available_staff)
            if st.button("Save Config"):
                st.session_state.calendar_data[target_d] = {"status": setup, "shift": f"{start_t}-{end_t}", "call": call, "chat": chat, "mfq": mfq, "sme": sme}
                st.success(f"Configuration saved for {target_d}")
        
        with col2:
            st.subheader("Approval Center")
            for i, req in enumerate(st.session_state.pending_requests):
                if req["status"] == "Pending":
                    denial_reason = st.text_area(f"Denial Reason (for {req['name']})", key=f"reason_{i}")
                    if st.button(f"Approve {req['name']} ({req['type']}) for {req['date']}", key=f"app_{i}"):
                        req["status"] = "Approved"
                        st.session_state.approved_requests.append(req)
                        st.session_state.pending_requests.pop(i)
                        if req.get("email") and admin_sender_email:
                            gmail_bard.send_message(sender=admin_sender_email, to=[req["email"]], body=f"Your {req['type']} request for {req['date']} has been approved.", subject="Request Approved")
                        st.rerun()
                    if st.button(f"Deny {req['name']} ({req['type']}) for {req['date']}", key=f"den_{i}"):
                        req["status"] = "Denied"
                        if req.get("email") and admin_sender_email:
                            gmail_bard.send_message(sender=admin_sender_email, to=[req["email"]], body=f"Your {req['type']} request for {req['date']} has been denied.\nReason: {denial_reason}", subject="Request Denied")
                        st.session_state.pending_requests.pop(i)
                        st.rerun()
            st.subheader("Approved Requests")
            st.table(pd.DataFrame(st.session_state.approved_requests))