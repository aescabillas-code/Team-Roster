from datetime import datetime, time, date
import streamlit as st
from pymongo import MongoClient
import calendar
import pandas as pd
import holidays

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
        cursor = collection.find({"type": "roster"})
        return {doc["name"]: {"bday": doc["bday"], "nick": doc["nick"], "rest_days": doc.get("rest_days", [])} for doc in cursor}
    except Exception:
        return {}

def save_staff(name, data):
    st.session_state.staff_roster[name] = data
    collection.update_one({"type": "roster_list"}, {"$set": {"data": st.session_state.staff_roster}}, upsert=True)

def delete_staff(name):
    collection.delete_one({"type": "roster", "name": name})
    if name in st.session_state.staff_roster: 
        del st.session_state.staff_roster[name]

def update_staff_in_db(name, update_dict):
    collection.update_one({"type": "roster", "name": name}, {"$set": update_dict})
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
    return list(collection.find({"type": "request", "status": "Approved"}))

def fetch_pending_requests_from_db():
    return list(collection.find({"type": "request", "status": "Pending"}))

def save_request_to_db(req):
    req["type"] = "request"
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
st.set_page_config(layout="wide", page_title="Team Roster & Staffing System")

if "pending_requests" not in st.session_state: 
    st.session_state.pending_requests = fetch_pending_requests_from_db()
if "approved_requests" not in st.session_state: 
    st.session_state.approved_requests = fetch_approved_requests_from_db()
if "admin_password" not in st.session_state: st.session_state.admin_password = "Password1234"
if "admin_authenticated" not in st.session_state: st.session_state.admin_authenticated = False
if "staff_roster" not in st.session_state: 
    st.session_state.staff_roster = {
        "Agent A": {"bday": date(2000, 1, 1), "nick": "A"}, 
        "Agent B": {"bday": date(1995, 5, 20), "nick": "B"}
    }
if "calendar_data" not in st.session_state: st.session_state.calendar_data = {}
if "limits" not in st.session_state: st.session_state.limits = {"PTO": 1, "Wellness": 1}
if "notifications" not in st.session_state: st.session_state.notifications = []
if "master_data" not in st.session_state: 
    st.session_state.master_data = pd.DataFrame({
        "Category": ["Contact Type", "Issue", "Product Group"], 
        "Values": ["Call,Chat,Email", "Tech,Billing", "Hardware,Soft"]
    })

# --- DATA MIGRATION ---
if "staff_roster" in st.session_state:
    for name, value in st.session_state.staff_roster.items():
        if not isinstance(value, dict):
            st.session_state.staff_roster[name] = {"bday": value, "nick": name}

# --- GLOBAL CSS STYLING ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Quicksand:wght@400;600&display=swap');
    html, body, [class*="css"] { font-family: 'Quicksand', sans-serif !important; }
    h1, h2, h3 { font-family: 'Quicksand', sans-serif !important; font-weight: 600; }
    .side-block { font-family: 'Quicksand', sans-serif !important; font-size: 10px !important; line-height: 1.2; }
    .day-block { border-radius: 15px; padding: 10px; height: auto; min-height: 140px; font-size: 11px; background-color: #ffffff; border: 1px solid #eef0f5; margin: 4px; display: flex; flex-direction: column; }
    .calendar-divider { border-top: 1px solid #e0e0e0; margin: 5px 0; width: 100%; }
    div.stButton > button { background: linear-gradient(90deg, #7b61ff 0%, #3b82f6 100%); color: white; border-radius: 12px; font-weight: 600; }
    .header-cell { font-weight: bold; text-align: center; color: #7b61ff; padding-bottom: 10px; }
    .alert-container { border-radius: 20px; border: 2px solid #ff4d4d; padding: 15px; background-color: #fff5f5; margin-bottom: 20px; }
    .flash-red { color: #ff4d4d; font-weight: bold; text-align: center; }
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
    c1, c2 = st.columns(2)
    
    if c1.button("Approve", key=f"app_{key_prefix}_{unique_id}"):
        update_request_status_in_db(req, "Approved")
        if req in st.session_state.pending_requests: st.session_state.pending_requests.remove(req)
        st.session_state.approved_requests.append(req)
        if req.get("email"):
            send_request_notification(req['email'], "Approved", req['type'], req['date'])
        st.success("Approved safely!")
        st.rerun()

    if c2.button("Deny", key=f"den_{key_prefix}_{unique_id}"):
        st.session_state[denial_key] = True
        st.rerun()

    if st.session_state.get(denial_key):
        reason = st.text_input("Reason for denial", key=f"reason_{key_prefix}_{unique_id}")
        col1, col2 = st.columns(2)
        if col1.button("Proceed Denial", key=f"confirm_{key_prefix}_{unique_id}"):
            delete_request_from_db(req)
            if req in st.session_state.pending_requests: st.session_state.pending_requests.remove(req)
            if req.get("email"):
                send_request_notification(req['email'], "Denied", req['type'], req['date'])
            st.session_state[denial_key] = False
            st.rerun()
        if col2.button("Cancel", key=f"cancel_{key_prefix}_{unique_id}"):
            st.session_state[denial_key] = False
            st.rerun()

# --- TABS WORKSPACE ---
tabs = st.tabs(["📅 Calendar", "📝 Request", "🔍 Case Tracker", "🔀 Deviation", "📂 Masterfile", "🔑 Admin"])

# --- TAB 1: CALENDAR ---
with tabs[0]:
    load_data_from_db()
    col_main, col_side = st.columns([4, 1])
    current_date = date.today()
    
    with col_main:
        c1, c2 = st.columns([1, 1])
        year = c1.selectbox("Year", [2026, 2027, 2028], key="cal_y")
        month = c2.selectbox("Month", range(1, 13), format_func=lambda x: calendar.month_name[x], index=current_date.month - 1, key="cal_m")

    with col_side:
        st.markdown('<div class="side-block">', unsafe_allow_html=True)
        st.subheader("Monthly Summary")
        st.markdown("**Birthdays:**")
        for name, info in st.session_state.staff_roster.items():
            bday = info.get("bday")
            if isinstance(bday, (date, datetime)) and bday.month == month:
                st.write(f"- {name}: {bday.strftime('%B %d')}")

        st.markdown("**Holidays:**")
        us_hols, ph_hols, found_holiday = holidays.US(years=year), holidays.PH(years=year), False
        for d_obj, h_name in sorted(us_hols.items()):
            if d_obj.month == month:
                st.write(f"- [US] {h_name}: {d_obj.strftime('%B %d')}"); found_holiday = True
        for d_obj, h_name in sorted(ph_hols.items()):
            if d_obj.month == month:
                st.write(f"- [PH] {h_name}: {d_obj.strftime('%B %d')}"); found_holiday = True
        if not found_holiday: st.write("No holidays this month.")
        
        st.subheader("Daily View")
        view_date = st.session_state.get('selected_admin_date', date.today())
        d_data = st.session_state.calendar_data.get(view_date, {})
        st.markdown(f"### Date: {view_date.strftime('%B %d, %Y')}")
        st.markdown(f"**Setup:** {d_data.get('status', 'Not Set')} | **Shift:** {d_data.get('shift', '--')}")
        st.divider()
        st.write("**Today's Schedule:**")
        for name in st.session_state.staff_roster:
            roles = [r.upper() for r in ["call", "chat", "mfq", "sme"] if name in d_data.get(r, [])]
            p_status = [r['type'] for r in st.session_state.approved_requests if str(r['date']) == str(view_date) and r['name'] == name]
            p_display = f" ({p_status[0]})" if p_status else ""
            st.write(f"- **{name}**: {', '.join(roles) if roles else 'Unassigned'}{p_display}")
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
                    approved = [r for r in st.session_state.approved_requests if str(r['date']) == str(d)]
                    away_names = [r['name'] for r in approved]
                    
                    def get_filtered_nicks(full_names):
                        active = [n for n in full_names if n not in away_names]
                        return ", ".join([st.session_state.staff_roster.get(x, {}).get("nick", x) for x in active])
                    
                    req_display = "<br>".join([f"{st.session_state.staff_roster.get(r['name'], {}).get('nick', r['name'])}({r['type']})" for r in approved])
                    data = st.session_state.calendar_data.get(d, {})
                    content = (f"<b>{day}</b><div class='calendar-divider'></div><u>{data.get('status', '-')}</u><div class='calendar-divider'></div>"
                               f"{data.get('shift', '-')}<div class='calendar-divider'></div>PTO: {req_display}<div class='calendar-divider'></div>"
                               f"Call: {get_filtered_nicks(data.get('call', []))}<div class='calendar-divider'></div>"
                               f"Chat: {get_filtered_nicks(data.get('chat', []))}<div class='calendar-divider'></div>"
                               f"MFQ: {get_filtered_nicks(data.get('mfq', []))}<div class='calendar-divider'></div>"
                               f"SME: {get_filtered_nicks(data.get('sme', []))}")
                    cols[i].markdown(f'<div class="day-block">{content}</div>', unsafe_allow_html=True)

# --- TAB 2: REQUEST FORM ---
with tabs[1]:
    st.subheader("PTO/Wellness Request")
    st.info("💡 **Tip:** Providing your work email is optional.")
    with st.form("request_form", clear_on_submit=True):
        staff_data = get_staff_list()
        name = st.selectbox("Name", list(staff_data.keys()) if staff_data else list(st.session_state.staff_roster.keys()))
        email = st.text_input("Work Email (Optional)")
        req_date = st.date_input("Request Date")
        req_type = st.selectbox("Type", ["PTO", "Wellness"])
        if st.form_submit_button("Submit Request"):
            limits = get_request_limits()
            count_on_date = len([r for r in (st.session_state.pending_requests + st.session_state.approved_requests) if str(r["date"]) == str(req_date) and r["type"] == req_type])
            is_already_requested = any(r["name"] == name and str(r["date"]) == str(req_date) for r in (st.session_state.pending_requests + st.session_state.approved_requests))
            
            if is_already_requested:
                st.warning(f"⚠️ A request for {name} on {req_date} already exists.")
            elif count_on_date >= limits.get(req_type, 0):
                st.error(f"❌ Limit reached for {req_type} on {req_date}.")
            else:
                new_req = {"name": name, "date": str(req_date), "type": req_type, "status": "Pending", "email": email}
                save_request_to_db(new_req)
                st.session_state.pending_requests.append(new_req)
                st.success("Request submitted successfully.")

# --- TAB 3: CASE TRACKER ---
with tabs[2]:
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
    status = st.selectbox("Status", ["Resolved", "Pending/Monitoring", "Routed"])
    extra = st.text_input("Reason / Destination") if status in ["Pending/Monitoring", "Routed"] else ""
    
    if st.button("Log Case"):
        save_case_to_db({"Date": str(date.today()), "Type": c_type, "Issue": issue, "Product Group": prod, "Desc": desc, "Steps": steps, "Status": status, "Extra": extra})
        st.success("Case logged successfully!")
        st.rerun()

    st.divider()
    st.subheader("Knowledge Base")
    cases_list = get_cases_from_db()
    f1, f2 = st.columns(2)
    f_issue = f1.multiselect("Filter by Issue", issues)
    f_prod = f2.multiselect("Filter by Product Group", prods)
    
    with st.expander("Admin Access (Edit/Delete)"):
        is_admin = (st.text_input("Enter Admin Password", type="password", key="case_adm_p") == st.session_state.admin_password)

    for case in reversed(cases_list):
        if (not f_issue or case.get('Issue') in f_issue) and (not f_prod or case.get('Product Group') in f_prod):
            st.markdown(f"**Date:** {case.get('Date')} | **Status:** {case.get('Status')} | **Issue:** {case.get('Issue')}")
            st.write(case.get('Desc'))
            if is_admin:
                st.button(f"Delete Row {case.get('_id')}", key=f"del_c_{case.get('_id')}", on_click=lambda: collection.delete_one({"_id": case["_id"]}))

# --- TAB 4: DEVIATION ---
with tabs[3]:
    st.subheader("Submit Deviation Request")
    with st.form("deviation_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        target_date = col1.date_input("Target Date", value=date.today())
        manager = col1.text_input("Manager", value="Jeff Bote")
        name = col1.selectbox("Name", list(st.session_state.staff_roster.keys()), key="dev_name_box")
        start_time = col2.time_input("Start Time")
        end_time = col2.time_input("End Time")
        total_mins = col2.number_input("Total Mins", min_value=0)
        reason = col2.text_area("Reason of Deviation")
        if st.form_submit_button("Submit Deviation Request"):
            save_deviation_to_db({"Date": str(target_date), "Manager": manager, "Name": name, "Start Time": str(start_time), "End Time": str(end_time), "Total Mins": total_mins, "Reason": reason})
            st.success("Deviation saved!")

    st.divider()
    dev_data = fetch_deviations_from_db()
    if dev_data:
        df = pd.DataFrame(dev_data)
        st.table(df.drop(columns=['_id', 'type'], errors='ignore'))
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("Extract Report as CSV", csv, "deviation_report.csv", "text/csv")

# --- TAB 5: MASTERFILE ---
with tabs[4]:
    if not st.session_state.admin_authenticated:
        if st.text_input("Enter Password", type="password", key="m_pass") == "Password1234":
            st.session_state.admin_authenticated = True
            st.rerun()
    else:
        col_m1, col_m2 = st.columns([4, 1])
        col_m1.subheader("System Masterfile")
        if col_m2.button("Save Masterfile Changes"):
            save_masterfile_to_db(st.session_state.master_data)
            st.success("Masterfile saved to DB.")
        st.session_state.master_data = st.data_editor(st.session_state.master_data, num_rows="dynamic")

# --- TAB 6: ADMIN ---
with tabs[5]:
    if not st.session_state.admin_authenticated:
        if st.text_input("Admin Password", type="password", key="a_pass") == "Password1234":
            st.session_state.admin_authenticated = True
            st.rerun()
    else:
        st.subheader("Admin Panel")
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Roster Management")
            roster = get_staff_list() if get_staff_list() else st.session_state.staff_roster
            for n, d in list(roster.items()):
                c1, c2, c3 = st.columns([3, 3, 2])
                c1.write(n)
                c2.write(d.get("nick", ""))
                if c3.button("Remove", key=f"rm_{n}"):
                    delete_staff(n)
                    st.rerun()

            st.markdown("---")
            new_name = st.text_input("Staff Name")
            new_nick = st.text_input("Nickname")
            new_bday = st.date_input("Birthday", min_value=date(1950, 1, 1))
            if st.button("Add Staff"):
                if new_name:
                    save_staff(new_name, {"bday": datetime.combine(new_bday, time.min), "nick": new_nick if new_nick else new_name, "rest_days": []})
                    st.success("Staff member created successfully.")
                    st.rerun()

            st.subheader("Daily Config")
            st.session_state.selected_admin_date = st.date_input("Select Date to View/Edit", date.today(), key="admin_date_pick")
            st.session_state.limits["PTO"] = st.number_input("Max PTO", value=st.session_state.limits.get("PTO", 1))
            st.session_state.limits["Wellness"] = st.number_input("Max Wellness", value=st.session_state.limits.get("Wellness", 1))
            
            config_mode = st.radio("Apply to:", ["Single Date", "Date Range", "Full Month"])
            if config_mode == "Single Date": 
                target_dates = [st.session_state.selected_admin_date]
            elif config_mode == "Date Range": 
                dr = st.date_input("Range", [], key="cfg_dr")
                target_dates = pd.date_range(dr[0], dr[1]).date if len(dr) == 2 else []
            else:
                sm = st.session_state.selected_admin_date
                target_dates = [d.date() for d in pd.date_range(f"{sm.year}-{sm.month}-01", periods=31) if d.month == sm.month]
            
            setup = st.selectbox("Status Setup", ["PROD - ONSITE", "PROD - WAH", "HOLIDAY"])
            available = list(roster.keys())
            call = st.multiselect("Assign Call", available)
            chat = st.multiselect("Assign Chat", available)
            mfq = st.multiselect("Assign MFQ", available)
            sme = st.multiselect("Assign SME", available)
            
            if st.button("Save Config"):
                for tgt in target_dates:
                    st.session_state.calendar_data[tgt] = {
                        "shift": "09:00 AM - 06:00 PM PHT", 
                        "status": setup, 
                        "call": call, 
                        "chat": chat, 
                        "mfq": mfq, 
                        "sme": sme
                    }
                serializable_data = {str(k): v for k, v in st.session_state.calendar_data.items()}
                collection.update_one({"type": "calendar_data"}, {"$set": {"data": serializable_data}}, upsert=True)
                st.success("Configuration synced successfully!")
                st.rerun()
        
        with col2:
            st.subheader("Approval Center")
            pto_pending = [r for r in st.session_state.pending_requests if r.get('type') == 'PTO']
            wellness_pending = [r for r in st.session_state.pending_requests if r.get('type') == 'Wellness']
            
            st.markdown("### ✈️ PTO Requests")
            for req in pto_pending: render_request(req, "pto")
            st.markdown("### 🌿 Wellness Requests")
            for req in wellness_pending: render_request(req, "wellness")
            
            st.subheader("✅ Approved History")
            all_approved = fetch_approved_requests_from_db()
            if all_approved:
                st.table(pd.DataFrame(all_approved).drop(columns=['_id', 'type'], errors='ignore'))
