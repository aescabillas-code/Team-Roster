import streamlit as st
import pandas as pd
from datetime import date, time, datetime
import calendar
import holidays

# --- 1. PERSISTENCE LAYER & INITIALIZATION ---
def initialize_state():
    defaults = {
        "staff_roster": {"Agent A": {"bday": date(2000, 1, 1), "nick": "Agent A", "rest_days": []}},
        "calendar_data": {},
        "pending_requests": [],
        "approved_requests": [],
        "deviation_requests": [],
        "notifications": [],
        "admin_authenticated": False,
        "cases": [],
        "master_data": pd.DataFrame({
            "Category": ["Contact Type", "Issue", "Product Group"], 
            "Values": ["Call,Chat,Email", "Tech,Billing", "Hardware,Soft"]
        })
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

initialize_state()

# --- 2. GLOBAL HANDLERS ---
def handle_approval(req, original_idx):
    req["status"] = "Approved"
    st.session_state.approved_requests.append(req)
    st.session_state.pending_requests.pop(original_idx)
    st.session_state.admin_msg = ("success", f"Approved {req['name']}")
    st.rerun()

def render_request(req, idx, prefix):
    unique_id = f"{prefix}_{idx}_{req.get('name', '').replace(' ', '_')}"
    with st.expander(f"{req['name']} - {req['date']} ({req['type']})"):
        if st.button("Approve", key=f"app_{unique_id}"):
            handle_approval(req, idx)
        if st.button("Deny", key=f"den_{unique_id}"):
            st.session_state.pending_requests.pop(idx)
            st.rerun()

# --- 3. UI LAYOUT ---
st.set_page_config(layout="wide", page_title="Team Roster System")

# CSS Styling
st.markdown("""<style>
    .day-block { border-radius: 15px; padding: 10px; background-color: #ffffff; border: 1px solid #eef0f5; margin: 4px; }
    .knowledge-card { border: none; padding: 20px; margin-bottom: 15px; border-radius: 20px; background-color: #ffffff; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
</style>""", unsafe_allow_html=True)

tabs = st.tabs(["📅 Calendar", "📝 Request", "🔍 Case Tracker", "🔀 Deviation", "📂 Masterfile", "🔑 Admin"])

# --- TAB 1: CALENDAR ---
with tabs[0]:
    st.subheader("Team Calendar")
    c1, c2 = st.columns(2)
    y = c1.selectbox("Year", [2026, 2027], key="cal_y")
    m = c2.selectbox("Month", range(1, 13), index=date.today().month-1, key="cal_m")
    
    # Rendering grid logic...
    cols = st.columns(7)
    for i, d_name in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
        cols[i].markdown(f"**{d_name}**")
    # ... loop through calendar.monthdayscalendar(y, m)

# --- TAB 2: REQUEST ---
with tabs[1]:
    st.subheader("PTO/Wellness Request")
    with st.form("req_form"):
        name = st.selectbox("Name", list(st.session_state.staff_roster.keys()))
        req_date = st.date_input("Date")
        req_type = st.selectbox("Type", ["PTO", "Wellness"])
        if st.form_submit_button("Submit"):
            st.session_state.pending_requests.append({"name": name, "date": req_date, "type": req_type})
            st.success("Submitted!")

# --- TAB 3: CASE TRACKER ---
with tabs[2]:
    st.subheader("Case Tracker")
    desc = st.text_area("Issue Description")
    if st.button("Log Case"):
        st.session_state.cases.append({"Desc": desc, "Date": date.today()})
    for case in reversed(st.session_state.cases):
        st.write(f"Logged: {case['Desc']}")

# --- TAB 4: DEVIATION ---
with tabs[3]:
    st.subheader("Deviation Request")
    # ... logic for deviation form and report ...

# --- TAB 5: MASTERFILE ---
with tabs[4]:
    st.session_state.master_data = st.data_editor(st.session_state.master_data, num_rows="dynamic")

# --- TAB 6: ADMIN ---
with tabs[5]:
    if not st.session_state.admin_authenticated:
        if st.text_input("Password", type="password") == "Password1234":
            st.session_state.admin_authenticated = True
            st.rerun()
    else:
        st.subheader("Admin Configuration")
        # --- APPROVAL SECTION ---
        for i, req in enumerate(st.session_state.pending_requests):
            render_request(req, i, "req")
        
        # --- DAILY CONFIG ---
        st.date_input("Target Date", key="cfg_target_date")
        if st.button("Save Config"):
            st.success("Saved!")
