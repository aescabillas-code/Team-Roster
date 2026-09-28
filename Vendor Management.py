import streamlit as st
import pandas as pd
import datetime
import time
import random
import uuid
from typing import Dict, List

# -----------------------------------------------------------------------------
# 1. PAGE CONFIGURATION & CUSTOM CSS
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="HPE CaseFlow",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

HPE_TEAL = "#00B388"
NAVY = "#0A1C2E"
BG_LIGHT = "#F4F7F9"

css = f"""
<style>
    /* Global UI Overrides */
    [data-testid="stAppViewContainer"] {{ background-color: {BG_LIGHT}; }}
    [data-testid="stHeader"] {{ display: none; }}
    footer {{ display: none; }}
    #MainMenu {{ display: none; }}
    
    /* Sidebar Navigation */
    [data-testid="stSidebar"] {{ background-color: {NAVY}; color: white; }}
    [data-testid="stSidebar"] * {{ color: white !important; }}
    
    /* HPE Buttons */
    .stButton > button {{
        background-color: {HPE_TEAL} !important;
        color: white !important;
        border-radius: 4px;
        border: none;
        font-weight: 600;
        padding: 0.5rem 1rem;
        transition: all 0.2s;
    }}
    .stButton > button:hover {{ filter: brightness(1.1); box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
    
    /* Split Screen Auth Form */
    .auth-container {{ padding: 2rem; background: white; border-radius: 8px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); }}
    .brand-hero {{ 
        height: 80vh; 
        background: linear-gradient(rgba(10, 28, 46, 0.8), rgba(10, 28, 46, 0.8)), url('https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&q=80'); 
        background-size: cover; 
        border-radius: 12px; 
        display: flex; 
        align-items: center; 
        justify-content: center; 
        color: white; 
        text-align: center;
    }}

    /* KPI Tiles */
    .kpi-card {{
        background: white; padding: 1.5rem; border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04); border-top: 4px solid {HPE_TEAL};
        display: flex; flex-direction: column; gap: 0.5rem;
    }}
    .kpi-title {{ font-size: 0.9rem; color: #666; font-weight: 600; text-transform: uppercase; }}
    .kpi-value {{ font-size: 2rem; font-weight: 700; color: #222; }}
    .kpi-trend {{ font-size: 0.8rem; color: #28a745; font-weight: 500; }}

    /* Status & Priority Pills */
    .pill {{ padding: 0.2rem 0.6rem; border-radius: 50px; font-size: 0.75rem; font-weight: 600; display: inline-block; }}
    .pill.critical {{ background: #FFE5E5; color: #D32F2F; }}
    .pill.high {{ background: #FFF4E5; color: #ED6C02; }}
    .pill.low {{ background: #E8F5E9; color: #2E7D32; }}
    .pill.open {{ background: #E3F2FD; color: #1976D2; }}
    .pill.resolved {{ background: #E8F5E9; color: #28A745; }}
    
    /* Table Rows */
    .table-row {{
        background: white; padding: 1rem; margin-bottom: 0.5rem; border-radius: 6px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; align-items: center;
        transition: transform 0.1s;
    }}
    .table-row:hover {{ transform: translateY(-2px); box-shadow: 0 4px 6px rgba(0,0,0,0.08); }}
    
    /* Top Header */
    .custom-header {{
        background: white; padding: 1rem 2rem; border-bottom: 1px solid #eee;
        position: sticky; top: 0; z-index: 999; display: flex; justify-content: space-between; align-items: center;
        margin: -3rem -3rem 2rem -3rem; box-shadow: 0 2px 4px rgba(0,0,0,0.02);
    }}
</style>
"""
st.markdown(css, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. DATABASE MOCK & STATE MANAGEMENT
# -----------------------------------------------------------------------------
# In a real environment, pymongo would be imported and connected here.
# For guaranteed immediate execution, we wrap the MongoDB concepts in session_state.
def get_mongo_client():
    if "db" not in st.session_state:
        st.session_state.db = {
            "Team Roster Collection": [],
            "Cases": [],
            "Validation_Dropdown": {"statuses": ["Open", "Pending Vendor", "Resolved", "Contract Breach", "Closed"]},
            "Schedule_Monitoring": []
        }
    return st.session_state.db

db = get_mongo_client()

def init_mock_data():
    if not db["Team Roster Collection"]:
        db["Team Roster Collection"].extend([
            {"type": "roster_list", "first_name": "Admin", "last_name": "User", "emp_id": "EMP001", "email": "admin@hpe.com", "password": "password123", "role": "Admin", "aux": "Admin Work"},
            {"type": "roster_list", "first_name": "Agent", "last_name": "One", "emp_id": "EMP002", "email": "agent1@hpe.com", "password": "password123", "role": "Agent", "aux": "Not Ready - Online"},
        ])
    if not db["Cases"]:
        priorities = ["Low", "High", "Critical"]
        for i in range(25):
            db["Cases"].append({
                "case_id": f"CAS-{random.randint(10000, 99999)}",
                "subject": f"Network Latency Issue - Node {i}",
                "priority": random.choice(priorities),
                "assigned_to": random.choice(["agent1@hpe.com", "Unassigned"]),
                "due_date": (datetime.datetime.now() + datetime.timedelta(days=random.randint(-1, 5))).strftime("%Y-%m-%d"),
                "status": random.choice(["Open", "Pending Vendor", "Resolved"]),
                "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

init_mock_data()

if "authenticated" not in st.session_state:
    st.session_state.update({
        "authenticated": False, "user": None, "user_role": None, 
        "active_page": "Dashboard", "current_aux_status": None, "alerts": []
    })

# -----------------------------------------------------------------------------
# 3. UTILITY COMPONENTS & DIALOGS
# -----------------------------------------------------------------------------
@st.dialog("Case Information", width="large")
def case_details_modal(case):
    st.markdown(f"### {case['case_id']} : {case['subject']}")
    tab1, tab2, tab3 = st.tabs(["Case Information", "Vendor Information", "Communication"])
    
    with tab1:
        col1, col2 = st.columns(2)
        status_opts = db["Validation_Dropdown"]["statuses"]
        new_status = col1.selectbox("Status", status_opts, index=status_opts.index(case["status"]))
        new_priority = col2.selectbox("Priority", ["Low", "High", "Critical"], index=["Low", "High", "Critical"].index(case["priority"]))
        
        if new_status == "Contract Breach":
            st.error("⚠️ Contract Breach Triggered")
            breach_reason = st.selectbox("Breach Reason", ["SLA Missed", "Non-Responsive", "Quality Issue"])
            st.text_area("Breach Notice Template (Editable)", f"Dear Vendor,\n\nWe are formally notifying you of a breach regarding {case['case_id']} due to {breach_reason}...")
            
        if st.button("Update Case"):
            case["status"] = new_status
            case["priority"] = new_priority
            st.success("Case Updated!")
            st.rerun()

    with tab2:
        st.info("Vendor Excel Data Synced via @st.cache_data")
        v_col1, v_col2 = st.columns(2)
        v_col1.markdown("**Vendor:** Cisco Systems\n**SLA:** 4 Hours")
        v_col2.markdown("**Contact:** noc@cisco.com\n**Phone:** +1-800-553-2447")
        st.button("📋 Copy Vendor Details to Clipboard")

    with tab3:
        st.text_area("Add Note / Communication Log")
        st.button("Save Note")

@st.dialog("System Alert")
def alert_modal(msg):
    st.warning(msg)
    if st.button("Acknowledge"):
        st.session_state.alerts.remove(msg)
        st.rerun()

def route_cases():
    """Auto-assignment logic: Routes Open & Unassigned cases to Available agents."""
    available_agents = [u for u in db["Team Roster Collection"] if u["aux"] == "Available" and u["role"] in ["Agent", "Admin/Agent"]]
    if not available_agents: return
    
    unassigned = [c for c in db["Cases"] if c["assigned_to"] == "Unassigned" and c["status"] == "Open"]
    for case in unassigned:
        # Round robin basic logic
        target = min(available_agents, key=lambda a: len([c for c in db["Cases"] if c["assigned_to"] == a["email"]]))
        if case["priority"] == "Critical":
            # Check if agent already has a critical case
            if any(c["priority"] == "Critical" for c in db["Cases"] if c["assigned_to"] == target["email"]):
                continue # Skip assigning critical if they already have one
        case["assigned_to"] = target["email"]
        if target["email"] == st.session_state.user["email"]:
            st.session_state.alerts.append(f"Auto-assigned new case: {case['case_id']}")

# -----------------------------------------------------------------------------
# 4. AUTHENTICATION FLOW
# -----------------------------------------------------------------------------
def render_auth():
    col_img, col_form = st.columns([1.2, 1])
    
    with col_img:
        st.markdown(
            """<div class="brand-hero">
                <div>
                    <h1 style="font-size: 3.5rem; margin-bottom: 0;">HPE CaseFlow</h1>
                    <p style="font-size: 1.2rem; font-weight: 300;">Next-Gen Task & Resolution Management</p>
                </div>
            </div>""", unsafe_allow_html=True
        )
        
    with col_form:
        st.markdown("<div style='height: 10vh;'></div>", unsafe_allow_html=True) # Spacer
        st.markdown("<div class='auth-container'>", unsafe_allow_html=True)
        tab_login, tab_signup = st.tabs(["Sign In", "Sign Up"])
        
        with tab_login:
            st.subheader("Welcome Back")
            email = st.text_input("HPE Email")
            pwd = st.text_input("Password", type="password")
            cols = st.columns(2)
            cols[0].checkbox("Remember me")
            cols[1].markdown("<p style='text-align: right; color: #00B388; font-size: 0.9rem; cursor: pointer;'>Forgot password?</p>", unsafe_allow_html=True)
            
            if st.button("Sign In", use_container_width=True):
                user = next((u for u in db["Team Roster Collection"] if u["email"] == email and u["password"] == pwd), None)
                if user:
                    st.session_state.authenticated = True
                    st.session_state.user = user
                    st.session_state.user_role = user["role"]
                    st.session_state.current_aux = user["aux"]
                    st.rerun()
                else:
                    st.error("Invalid credentials.")
                    
        with tab_signup:
            st.subheader("Create Account")
            s_fname = st.text_input("First Name")
            s_lname = st.text_input("Last Name")
            s_emp = st.text_input("Employee ID")
            s_email = st.text_input("HPE Email (Signup)")
            s_pwd = st.text_input("Password (Signup)", type="password")
            
            if st.button("Register", use_container_width=True):
                db["Team Roster Collection"].append({
                    "type": "roster_list", "first_name": s_fname, "last_name": s_lname, 
                    "emp_id": s_emp, "email": s_email, "password": s_pwd, 
                    "role": "Agent", "aux": "Not Ready - Online"
                })
                st.success("Registered! Please sign in.")
        st.markdown("</div>", unsafe_allow_html=True)

if not st.session_state.authenticated:
    render_auth()
    st.stop()

# -----------------------------------------------------------------------------
# 5. MAIN APPLICATION SHELL
# -----------------------------------------------------------------------------
route_cases() # Run routing on user interactions

if st.session_state.alerts:
    alert_modal(st.session_state.alerts[0])

# --- TOP HEADER ---
header_html = """
<div class="custom-header">
    <div style="font-weight: 700; font-size: 1.2rem; color: #0A1C2E;">HPE CaseFlow Workspace</div>
</div>
"""
st.markdown(header_html, unsafe_allow_html=True)

# We use Streamlit columns floating over the injected header visually for functionality
h_col1, h_col2, h_col3 = st.columns([6, 1, 1])
with h_col1:
    st.text_input("🔍 Search cases, names, issues...", label_visibility="collapsed", placeholder="Search cases, names, issues...")
with h_col2:
    unread = len([c for c in db["Cases"] if c["priority"] == "Critical"])
    st.button(f"🔔 {unread}")
with h_col3:
    with st.popover("👤 Profile & Aux"):
        st.markdown(f"**{st.session_state.user['first_name']} {st.session_state.user['last_name']}**")
        st.caption(f"Role: {st.session_state.user_role}")
        
        aux_opts = ["Available", "Admin Work", "Not Ready - Online", "Coaching", "Meeting", "Lunch", "Break", "Unscheduled Break"]
        new_aux = st.selectbox("Current Status", aux_opts, index=aux_opts.index(st.session_state.current_aux))
        if new_aux != st.session_state.current_aux:
            st.session_state.current_aux = new_aux
            st.session_state.user["aux"] = new_aux
            st.rerun()
            
        st.divider()
        st.markdown("🗓️ **Today's Timeline**")
        st.caption("08:00 AM - Login\n12:00 PM - Lunch (Scheduled)\n05:00 PM - End Shift")
        
        if st.button("Sign Out"):
            st.session_state.authenticated = False
            st.rerun()

# --- SIDEBAR NAV ---
with st.sidebar:
    st.markdown("<h2 style='color: #00B388; text-align: center; margin-bottom: 2rem;'>CaseFlow</h2>", unsafe_allow_html=True)
    
    pages = ["Dashboard", "Schedule", "Reports"]
    if st.session_state.user_role in ["Admin", "Admin/Agent"]:
        pages.insert(1, "Monitoring")
        pages.append("Settings")
        
    for p in pages:
        icon = {"Dashboard": "📊", "Monitoring": "👀", "Schedule": "📅", "Reports": "📈", "Settings": "⚙️"}[p]
        if st.button(f"{icon} {p}", use_container_width=True, type="primary" if st.session_state.active_page == p else "secondary"):
            st.session_state.active_page = p
            st.rerun()

# -----------------------------------------------------------------------------
# 6. VIEWS
# -----------------------------------------------------------------------------
def get_pill(val, ptype="priority"):
    val_lower = val.lower().replace(" ", "-")
    return f"<span class='pill {val_lower}'>{val}</span>"

def render_dashboard():
    st.markdown("### Operational Dashboard")
    
    # KPI TTILES
    my_cases = [c for c in db["Cases"] if c["assigned_to"] == st.session_state.user["email"]]
    team_cases = db["Cases"]
    
    display_cases = team_cases if st.session_state.user_role == "Admin" else my_cases
    active = len([c for c in display_cases if c["status"] != "Resolved"])
    critical = len([c for c in display_cases if c["priority"] == "Critical" and c["status"] != "Resolved"])
    resolved_today = len([c for c in display_cases if c["status"] == "Resolved"])
    
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(f"<div class='kpi-card'><div class='kpi-title'>Active Cases</div><div class='kpi-value'>{active}</div><div class='kpi-trend'>↑ 2 from yesterday</div></div>", unsafe_allow_html=True)
    k2.markdown(f"<div class='kpi-card'><div class='kpi-title'>Critical Alert</div><div class='kpi-value' style='color:#D32F2F;'>{critical}</div><div class='kpi-trend' style='color:#D32F2F;'>Action Required</div></div>", unsafe_allow_html=True)
    k3.markdown(f"<div class='kpi-card'><div class='kpi-title'>Resolved Today</div><div class='kpi-value'>{resolved_today}</div><div class='kpi-trend'>+15% WoW</div></div>", unsafe_allow_html=True)
    k4.markdown(f"<div class='kpi-card'><div class='kpi-title'>SLA Adherence</div><div class='kpi-value'>98.2%</div><div class='kpi-trend'>On Track</div></div>", unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # MAIN WORKSPACE
    m_col1, m_col2 = st.columns([3, 1])
    
    with m_col1:
        st.markdown("#### Active Queue")
        
        # Table Header
        h_c1, h_c2, h_c3, h_c4, h_c5, h_c6 = st.columns([1, 3, 1, 1.5, 1, 1])
        h_c1.caption("CASE #"); h_c2.caption("SUBJECT"); h_c3.caption("PRIORITY")
        h_c4.caption("ASSIGNED TO"); h_c5.caption("STATUS"); h_c6.caption("ACTION")
        st.divider()
        
        for case in display_cases[:10]: # Paginate/limit for UI speed
            c1, c2, c3, c4, c5, c6 = st.columns([1, 3, 1, 1.5, 1, 1])
            c1.markdown(f"**{case['case_id']}**")
            c2.markdown(case["subject"])
            c3.markdown(get_pill(case["priority"], "priority"), unsafe_allow_html=True)
            c4.markdown(case["assigned_to"].split("@")[0])
            c5.markdown(get_pill(case["status"], "status"), unsafe_allow_html=True)
            if c6.button("View", key=f"view_{case['case_id']}"):
                case_details_modal(case)
                
    with m_col2:
        if st.session_state.user_role == "Admin":
            st.markdown("#### Live Roster")
            for agent in [u for u in db["Team Roster Collection"] if u["role"] != "Admin"]:
                st.markdown(f"<div style='padding:10px; background:white; border-radius:5px; margin-bottom:5px;'>"
                            f"<strong>{agent['first_name']}</strong><br>"
                            f"<small style='color:gray;'>{agent['aux']}</small></div>", unsafe_allow_html=True)
            if st.button("Bulk Reassign Engine"):
                st.info("Re-distributing queue load...")
        else:
            st.markdown("#### Quick Actions")
            st.button("Request Peer Transfer", use_container_width=True)
            st.button("Escalate to Tier 2", use_container_width=True)
            st.button("Contact Vendor SD", use_container_width=True)

def render_monitoring():
    st.markdown("### Real-Time Adherence & Monitoring")
    agents = [u for u in db["Team Roster Collection"] if u["role"] != "Admin"]
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Available Agents", len([a for a in agents if a["aux"] == "Available"]))
    c2.metric("On Break / Lunch", len([a for a in agents if a["aux"] in ["Break", "Lunch"]]))
    c3.metric("Unscheduled Break", len([a for a in agents if a["aux"] == "Unscheduled Break"]))
    
    st.dataframe(pd.DataFrame(agents)[["first_name", "last_name", "role", "aux"]], use_container_width=True)
    
    col1, col2 = st.columns(2)
    col1.button("Kick Selected User")
    col2.button("Force Aux Change")

def render_schedule():
    st.markdown("### Workforce Scheduling")
    tabs = st.tabs(["Daily Auto-Plotter", "PTO Requests (Month)", "Shift Swaps"])
    
    with tabs[0]:
        st.info("Auto-plotter ensures minimum 80% coverage during breaks based on current volume.")
        df = pd.DataFrame({
            "Agent": ["Agent One", "Agent Two", "Agent Three"],
            "Shift": ["08:00 - 17:00", "09:00 - 18:00", "08:00 - 17:00"],
            "Break 1": ["10:00", "11:00", "10:15"],
            "Lunch": ["12:00", "13:00", "12:30"],
            "Break 2": ["15:00", "16:00", "15:15"]
        })
        st.dataframe(df, use_container_width=True, hide_index=True)
        
    with tabs[1]:
        st.markdown("PTO Allocation Limit: **4 Slots Remaining Today**")
        date = st.date_input("Select Date for PTO")
        st.button("Submit PTO Request")

def render_reports():
    st.markdown("### Analytics & Reporting")
    st.selectbox("Timeframe", ["MTD", "YTD", "WOW", "Daily"])
    
    r_col1, r_col2 = st.columns(2)
    with r_col1:
        st.markdown("**Resolution Metrics**")
        st.bar_chart({"Handled": [45, 52, 49, 60], "Resolved": [40, 50, 48, 55], "Breached": [2, 1, 0, 1]})
    with r_col2:
        st.markdown("**Adherence vs Schedule**")
        st.line_chart({"Adherence %": [95, 96, 92, 98], "Attendance %": [100, 100, 95, 100]})

def render_settings():
    st.markdown("### System Settings")
    st.subheader("Team Management")
    st.dataframe(pd.DataFrame(db["Team Roster Collection"])[["first_name", "email", "role", "emp_id"]])
    st.button("Add New User")
    
    st.divider()
    st.subheader("External Syncing")
    st.file_uploader("Upload Vendor Matrix (Excel)")
    st.button("Sync Dropdowns to DB")

# -----------------------------------------------------------------------------
# 7. ROUTER
# -----------------------------------------------------------------------------
if st.session_state.active_page == "Dashboard":
    render_dashboard()
elif st.session_state.active_page == "Monitoring":
    render_monitoring()
elif st.session_state.active_page == "Schedule":
    render_schedule()
elif st.session_state.active_page == "Reports":
    render_reports()
elif st.session_state.active_page == "Settings":
    render_settings()
