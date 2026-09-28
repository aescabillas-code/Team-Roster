import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import hashlib
import uuid
import json
import re
import os

# ==============================================================================
# 1. APPLICATION SETUP & PAGE CONFIGURATION
# ==============================================================================
st.set_page_config(
    page_title="HPE CaseFlow",
    page_icon="🟩",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom HPE Enterprise Design System CSS
HPE_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Metric:wght@300;400;500;600;700&family=Inter:wght@300;400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        color: #0B2341;
        background-color: #F4F7F9;
    }
    
    /* Clean up default Streamlit elements */
    #MainMenu, header, footer {visibility: hidden;}
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2rem;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    
    /* Card Styles */
    .hpe-card {
        background: #FFFFFF;
        border-radius: 8px;
        padding: 1.25rem;
        border: 1px solid #E0E6ED;
        box-shadow: 0 2px 6px rgba(11, 35, 65, 0.04);
        margin-bottom: 1rem;
    }
    
    .metric-card {
        background: #FFFFFF;
        border-radius: 8px;
        padding: 1.2rem;
        border-left: 5px solid #01A982;
        border-top: 1px solid #E0E6ED;
        border-right: 1px solid #E0E6ED;
        border-bottom: 1px solid #E0E6ED;
        box-shadow: 0 2px 5px rgba(0,0,0,0.03);
    }
    .metric-card.critical { border-left-color: #DE3618; }
    .metric-card.warning { border-left-color: #FFAA15; }
    .metric-card.info { border-left-color: #00739D; }
    
    /* Status Badges */
    .badge {
        display: inline-block;
        padding: 0.25rem 0.65rem;
        font-size: 0.75rem;
        font-weight: 600;
        border-radius: 20px;
        text-align: center;
    }
    .badge-available { background-color: #E6F6F2; color: #01A982; border: 1px solid #01A982; }
    .badge-admin { background-color: #E5F3F8; color: #00739D; border: 1px solid #00739D; }
    .badge-notready { background-color: #FCEBE8; color: #DE3618; border: 1px solid #DE3618; }
    .badge-coaching { background-color: #F5EBF7; color: #763082; border: 1px solid #763082; }
    .badge-meeting { background-color: #FFF6E6; color: #EAA023; border: 1px solid #EAA023; }
    .badge-lunch { background-color: #FFFDE6; color: #B38600; border: 1px solid #B38600; }
    .badge-break { background-color: #EFF1F3; color: #616D75; border: 1px solid #616D75; }
    .badge-critical { background-color: #FCEBE8; color: #DE3618; font-weight: 700; }
    .badge-high { background-color: #FFF0E6; color: #E26815; font-weight: 600; }
    .badge-medium { background-color: #FFFBE6; color: #B38600; }
    .badge-low { background-color: #EBF8F2; color: #01A982; }
    
    /* Nav Buttons */
    .stButton>button {
        border-radius: 4px;
        font-weight: 500;
        transition: all 0.2s ease;
    }
    .stButton>button:hover {
        border-color: #01A982;
        color: #01A982;
    }
    
    /* Global Header Container */
    .global-header {
        background: #0B2341;
        color: #FFFFFF;
        padding: 0.75rem 1.5rem;
        border-radius: 8px;
        margin-bottom: 1.5rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .global-header h2 { color: #FFFFFF !important; margin: 0; }
    .global-header span { color: #01A982; font-weight: 600; }
</style>
"""
st.markdown(HPE_CSS, unsafe_allow_html=True)

# ==============================================================================
# 2. PERSISTENCE & DATABASE LAYER (PyMongo with Fail-Safe Mock Fallback)
# ==============================================================================
AUX_STATUSES = [
    "Available", "Admin Work", "Not Ready - Online", 
    "Coaching", "Meeting", "Lunch", "Break", "Unscheduled Break"
]

DEFAULT_USERS = [
    {
        "employee_id": "HPE-1001",
        "first_name": "Arianne",
        "last_name": "Escabillas",
        "email": "arianne.escabillas@hpe.com",
        "password_hash": hashlib.sha256("Admin@123".encode()).hexdigest(),
        "role": "ADMIN",
        "status": "Active",
        "current_aux": "Available",
        "aux_since": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "active_cases": 2,
        "today_assigned": 4,
        "department": "Global Mission Critical Support",
        "created_at": "2026-01-10"
    },
    {
        "employee_id": "HPE-1002",
        "first_name": "John",
        "last_name": "Dela Cruz",
        "email": "john.delacruz@hpe.com",
        "password_hash": hashlib.sha256("Agent@123".encode()).hexdigest(),
        "role": "ADMIN/AGENT",
        "status": "Active",
        "current_aux": "Available",
        "aux_since": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "active_cases": 3,
        "today_assigned": 5,
        "department": "Compute Platform Group",
        "created_at": "2026-02-01"
    },
    {
        "employee_id": "HPE-1003",
        "first_name": "Maria",
        "last_name": "Santos",
        "email": "maria.santos@hpe.com",
        "password_hash": hashlib.sha256("Agent@123".encode()).hexdigest(),
        "role": "AGENT",
        "status": "Active",
        "current_aux": "Available",
        "aux_since": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "active_cases": 4,
        "today_assigned": 6,
        "department": "Storage Ops & Alletra",
        "created_at": "2026-02-15"
    },
    {
        "employee_id": "HPE-1004",
        "first_name": "Mark",
        "last_name": "Tan",
        "email": "mark.tan@hpe.com",
        "password_hash": hashlib.sha256("Agent@123".encode()).hexdigest(),
        "role": "AGENT",
        "status": "Active",
        "current_aux": "Meeting",
        "aux_since": (datetime.now() - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M:%S"),
        "active_cases": 1,
        "today_assigned": 2,
        "department": "HPE GreenLake Cloud Ops",
        "created_at": "2026-03-01"
    }
]

DEFAULT_CASES = [
    {
        "case_id": "CAS-98214",
        "subject": "GreenLake Flex Capacity Ingestion Latency Breach",
        "priority": "Critical",
        "assigned_to": "maria.santos@hpe.com",
        "status": "In Progress",
        "category": "Cloud Services",
        "client": "Financial Corp Global",
        "vendor": "Intel Xeon Platform Support",
        "created_at": (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"),
        "due_date": (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
        "last_update": "Telemetry verified, pending vendor diagnostic dump.",
        "related_system": "ProLiant Gen11 / GreenLake Core"
    },
    {
        "case_id": "CAS-98215",
        "subject": "Synergy Interconnect Module Firmware Desync",
        "priority": "High",
        "assigned_to": "john.delacruz@hpe.com",
        "status": "Pending Vendor",
        "category": "Converged Infrastructure",
        "client": "AeroSpace Dynamics Ltd",
        "vendor": "Brocade SAN Networking",
        "created_at": (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M"),
        "due_date": (datetime.now() + timedelta(hours=4)).strftime("%Y-%m-%d %H:%M"),
        "last_update": "Awaiting engineer response on ticket BR-8820.",
        "related_system": "HPE Synergy 12000 Frame"
    },
    {
        "case_id": "CAS-98216",
        "subject": "StoreOnce 5660 Replication Target Offline",
        "priority": "Critical",
        "assigned_to": "arianne.escabillas@hpe.com",
        "status": "Open",
        "category": "Storage Systems",
        "client": "HealthAlliance National",
        "vendor": "Veeam Core Integration",
        "created_at": (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
        "due_date": (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
        "last_update": "Heartbeat failure detected on Catalyst interface.",
        "related_system": "HPE StoreOnce Catalyst"
    },
    {
        "case_id": "CAS-98217",
        "subject": "Alletra 9000 Node Controller NVMe Degraded",
        "priority": "Medium",
        "assigned_to": "maria.santos@hpe.com",
        "status": "On Hold",
        "category": "Hardware Lifecycle",
        "client": "Nordic Telecommunications",
        "vendor": "Samsung Semiconductor",
        "created_at": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
        "due_date": (datetime.now() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"),
        "last_update": "Part dispatched. Tracking: 8492049281.",
        "related_system": "Alletra MP Block Storage"
    },
    {
        "case_id": "CAS-98218",
        "subject": "Aruba Central Switch Stack Uplink Flapping",
        "priority": "Low",
        "assigned_to": "mark.tan@hpe.com",
        "status": "Resolved",
        "category": "Networking",
        "client": "Retail Supermarkets Group",
        "vendor": "Aruba Edge Services",
        "created_at": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M"),
        "due_date": (datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M"),
        "last_update": "Replaced SFP+ 10G transceiver. Link stabilized.",
        "related_system": "CX 6300M Series"
    }
]

class DatabaseManager:
    """Provides resilient persistence using MongoDB, falling back seamlessly to Session State."""
    def __init__(self):
        self.is_connected = False
        self.db = None
        self.collection = None
        try:
            from pymongo import MongoClient
            mongo_uri = os.environ.get("MONGO_URI") or st.secrets.get("mongo_uri", None)
            if mongo_uri:
                client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
                client.server_info() # verify
                self.db = client["TeamRoster"]
                self.collection = self.db["Team Roster Collection"]
                self.is_connected = True
        except Exception:
            self.is_connected = False

        self._initialize_seed_data()

    def _initialize_seed_data(self):
        if "roster_list" not in st.session_state:
            st.session_state["roster_list"] = DEFAULT_USERS.copy()
        if "case_list" not in st.session_state:
            st.session_state["case_list"] = DEFAULT_CASES.copy()
        if "case_history" not in st.session_state:
            st.session_state["case_history"] = {}
        if "pto_requests" not in st.session_state:
            st.session_state["pto_requests"] = [
                {"req_id": "PTO-101", "name": "Maria Santos", "email": "maria.santos@hpe.com", "type": "PTO", "dates": "2026-10-12 to 2026-10-14", "status": "Approved", "reason": "Family gathering"},
                {"req_id": "PTO-102", "name": "Mark Tan", "email": "mark.tan@hpe.com", "type": "Sick Leave", "dates": "2026-10-01", "status": "Pending", "reason": "Medical follow-up"}
            ]
        if "notifications" not in st.session_state:
            st.session_state["notifications"] = [
                {"id": "notif-1", "user_email": "maria.santos@hpe.com", "title": "New Case Assigned", "text": "Case CAS-98214 assigned to you.", "time": "10 mins ago", "read": False},
                {"id": "notif-2", "user_email": "arianne.escabillas@hpe.com", "title": "SLA Alert", "text": "CAS-98216 approaching breach window.", "time": "25 mins ago", "read": False}
            ]
        if "audit_logs" not in st.session_state:
            st.session_state["audit_logs"] = [
                {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "user": "SYSTEM", "activity": "System Initialization", "details": "HPE CaseFlow Services online."}
            ]
        if "vendors" not in st.session_state:
            st.session_state["vendors"] = [
                {"name": "Intel Xeon Operations", "contact": "David Vance", "email": "d.vance@intel.com", "phone": "+1-800-456-7890", "category": "Silicon/Compute"},
                {"name": "Samsung NVMe Tier-1", "contact": "Elena Rostova", "email": "e.rostova@samsung.com", "phone": "+1-888-234-5678", "category": "Memory/Storage"},
                {"name": "Brocade SAN Division", "contact": "Arthur Dent", "email": "support@brocade.com", "phone": "+1-877-990-1234", "category": "Fibre Channel"}
            ]

    # User operations
    def get_users(self):
        return st.session_state["roster_list"]

    def find_user_by_email(self, email):
        for u in st.session_state["roster_list"]:
            if u["email"].lower() == email.lower():
                return u
        return None

    def add_user(self, user_dict):
        st.session_state["roster_list"].append(user_dict)
        self.log_audit(user_dict["email"], "Account Created", f"New user {user_dict['email']} registered as {user_dict['role']}.")

    def update_user_aux(self, email, new_aux):
        for u in st.session_state["roster_list"]:
            if u["email"].lower() == email.lower():
                old_aux = u.get("current_aux", "Available")
                u["current_aux"] = new_aux
                u["aux_since"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.log_audit(email, "Aux Changed", f"Changed from {old_aux} to {new_aux}")
                break

    # Case operations
    def get_cases(self):
        return st.session_state["case_list"]

    def get_case_by_id(self, case_id):
        for c in st.session_state["case_list"]:
            if c["case_id"] == case_id:
                return c
        return None

    def update_case(self, case_id, updates, actor):
        for c in st.session_state["case_list"]:
            if c["case_id"] == case_id:
                c.update(updates)
                self.log_case_history(case_id, actor, "Case Updated", json.dumps(updates))
                self.log_audit(actor, "Case Update", f"Case {case_id} updated.")
                break

    def log_case_history(self, case_id, actor, action, desc):
        if case_id not in st.session_state["case_history"]:
            st.session_state["case_history"][case_id] = []
        st.session_state["case_history"][case_id].append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "actor": actor,
            "action": action,
            "description": desc
        })

    def log_audit(self, user, activity, details):
        st.session_state["audit_logs"].insert(0, {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user": user,
            "activity": activity,
            "details": details
        })

    def add_notification(self, user_email, title, text):
        st.session_state["notifications"].insert(0, {
            "id": f"notif-{uuid.uuid4().hex[:6]}",
            "user_email": user_email,
            "title": title,
            "text": text,
            "time": "Just now",
            "read": False
        })

db_mgr = DatabaseManager()

# ==============================================================================
# 3. AUTOMATED CASE ASSIGNMENT ENGINE
# ==============================================================================
def auto_assign_case(case_data):
    """
    Distributes case to eligible agent based on Aux state, role, and current active load.
    """
    eligible_users = [
        u for u in db_mgr.get_users()
        if u["status"] == "Active"
        and u["current_aux"] == "Available"
        and u["role"] in ["AGENT", "ADMIN/AGENT"]
    ]
    
    if not eligible_users:
        # Fallback to any active agent if none in Available Aux
        eligible_users = [
            u for u in db_mgr.get_users()
            if u["status"] == "Active" and u["role"] in ["AGENT", "ADMIN/AGENT"]
        ]

    if not eligible_users:
        return None

    # Sort primarily by least active cases, secondarily by least assigned today
    eligible_users.sort(key=lambda x: (x.get("active_cases", 0), x.get("today_assigned", 0)))
    assigned_agent = eligible_users[0]
    
    # Update assignee workloads
    assigned_agent["active_cases"] = assigned_agent.get("active_cases", 0) + 1
    assigned_agent["today_assigned"] = assigned_agent.get("today_assigned", 0) + 1
    
    case_data["assigned_to"] = assigned_agent["email"]
    db_mgr.get_cases().insert(0, case_data)
    
    db_mgr.log_case_history(case_data["case_id"], "AUTO-DISPATCH", "Automatic Assignment", f"Assigned to {assigned_agent['email']}")
    db_mgr.add_notification(assigned_agent["email"], "New Case Assigned", f"Case {case_data['case_id']} ({case_data['priority']}) auto-assigned to you.")
    return assigned_agent

# ==============================================================================
# 4. MODAL DIALOGS (9 SPECIFIED OPERATIONAL ALERTS)
# ==============================================================================
@st.dialog("🔔 New Case Assigned")
def dlg_new_case(case):
    st.markdown(f"**Case #:** `{case['case_id']}`")
    st.markdown(f"**Subject:** {case['subject']}")
    st.markdown(f"**Priority:** <span class='badge badge-{case['priority'].lower()}'>{case['priority']}</span>", unsafe_allow_html=True)
    st.markdown(f"**Due Date:** {case['due_date']}")
    col1, col2 = st.columns(2)
    if col1.button("View Case", key="dlg_nc_view", use_container_width=True):
        st.session_state["selected_case_id"] = case['case_id']
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if col2.button("Acknowledge", key="dlg_nc_ack", use_container_width=True):
        st.rerun()

@st.dialog("🔄 Case Reassigned")
def dlg_case_reassigned(case_id, from_user):
    st.markdown(f"**Case #:** `{case_id}` has been transferred.")
    st.markdown(f"**Transferred From:** {from_user}")
    st.info("You are now the primary owner for this SLA contract.")
    if st.button("Acknowledge & Close", use_container_width=True):
        st.rerun()

@st.dialog("📬 Case Transfer Request Received")
def dlg_transfer_request(case_id, from_user):
    st.markdown(f"**Agent `{from_user}`** requested to transfer Case **`{case_id}`** to you.")
    st.write("Reason: High queue complexity / Subject matter escalation.")
    col1, col2 = st.columns(2)
    if col1.button("Approve Transfer", type="primary", use_container_width=True):
        c = db_mgr.get_case_by_id(case_id)
        if c:
            c["assigned_to"] = st.session_state["auth_user"]["email"]
            db_mgr.log_case_history(case_id, st.session_state["auth_user"]["email"], "Transfer Approved", f"Transferred from {from_user}")
        st.success("Case successfully accepted.")
        st.rerun()
    if col2.button("Decline", use_container_width=True):
        st.warning("Transfer request declined.")
        st.rerun()

@st.dialog("🗓️ Schedule Swap Request")
def dlg_schedule_swap(requester, date_str):
    st.markdown(f"**Requester:** {requester}")
    st.markdown(f"**Target Shift Date:** {date_str}")
    st.markdown("**Proposed:** Shift Swap: Morning Shift (08:00-17:00) ⇄ Mid Shift (11:00-20:00)")
    c1, c2 = st.columns(2)
    if c1.button("Approve Swap", type="primary", use_container_width=True):
        st.success("Schedule swap confirmed. Rostering updated.")
        st.rerun()
    if c2.button("Decline", use_container_width=True):
        st.info("Swap request rejected.")
        st.rerun()

@st.dialog("🚨 Critical Case Breach Notice")
def dlg_critical_past_due(case):
    st.error(f"SLA BREACH ALERT: Case {case['case_id']}")
    st.markdown(f"**Client:** {case.get('client', 'Global Account')}")
    st.markdown(f"**Deadline:** `{case['due_date']}`")
    st.markdown(f"**Vendor Dependency:** {case.get('vendor', 'Tier-3 Ops')}")
    st.markdown("Immediate escalation action required. Executive team notified.")
    if st.button("Open Incident Workspace", type="primary", use_container_width=True):
        st.session_state["selected_case_id"] = case['case_id']
        st.session_state["active_nav"] = "Case Details"
        st.rerun()

@st.dialog("📢 Admin Broadcast Message")
def dlg_admin_broadcast():
    st.subheader("Global Operations Announcement")
    st.markdown("**From:** Operational Command Center (OCC)")
    st.markdown("**Timestamp:** Today at 09:00 AM UTC")
    st.info("Please be advised: Scheduled firmware upgrades on GreenLake Core Network nodes will take place at 22:00 UTC. Hold all non-urgent firmware flushes.")
    if st.button("Understood", use_container_width=True):
        st.rerun()

# ==============================================================================
# 5. AUTHENTICATION PAGES (Sign-In, Sign-Up, Forgot Password)
# ==============================================================================
def render_auth():
    col_brand, col_form = st.columns([1.1, 1], gap="large")
    
    with col_brand:
        st.markdown(
            """
            <div style="background: linear-gradient(135deg, #0B2341 0%, #001A2C 100%); padding: 3.5rem 2.5rem; border-radius: 12px; color: white; height: 100%;">
                <div style="font-size: 2.2rem; font-weight: 800; letter-spacing: -1px; margin-bottom: 0.5rem;">
                    <span style="color: #01A982;">Hewlett Packard</span> Enterprise
                </div>
                <h1 style="color: white; font-size: 2.8rem; margin: 0 0 1rem 0; font-weight: 700;">HPE CaseFlow</h1>
                <p style="font-size: 1.15rem; color: #A0B2C6; margin-bottom: 2.5rem;">Next-Generation Mission Critical Team Task & Case Management</p>
                <div style="margin-bottom: 1.5rem; display: flex; align-items: center; gap: 12px;">
                    <div style="background: #01A982; width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 700;">✓</div>
                    <div style="font-size: 1.05rem;"><strong>Manage Cases:</strong> Real-time SLA Tracking & Fair Dispatch</div>
                </div>
                <div style="margin-bottom: 1.5rem; display: flex; align-items: center; gap: 12px;">
                    <div style="background: #00739D; width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 700;">✓</div>
                    <div style="font-size: 1.05rem;"><strong>Work Together:</strong> Real-time Aux Status & Live Scheduling</div>
                </div>
                <div style="margin-bottom: 1.5rem; display: flex; align-items: center; gap: 12px;">
                    <div style="background: #763082; width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 700;">✓</div>
                    <div style="font-size: 1.05rem;"><strong>Drive Results:</strong> Deep Adherence & Resolution Analytics</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col_form:
        auth_mode = st.session_state.get("auth_mode", "Sign In")
        
        if auth_mode == "Sign In":
            st.markdown("## Welcome Back!")
            st.caption("Sign in to your HPE CaseFlow account")
            
            with st.form("signin_form"):
                email = st.text_input("HPE Email Address", placeholder="name@hpe.com")
                pwd = st.text_input("Password", type="password")
                remember = st.checkbox("Remember me", value=True)
                submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)
                
                if submitted:
                    if not email or not pwd:
                        st.error("Please enter both email and password.")
                    else:
                        user = db_mgr.find_user_by_email(email)
                        pwd_hash = hashlib.sha256(pwd.encode()).hexdigest()
                        if user and user.get("password_hash") == pwd_hash:
                            if user.get("status") != "Active":
                                st.error("Account is deactivated. Contact Operations Administrator.")
                            else:
                                st.session_state["authenticated"] = True
                                st.session_state["auth_user"] = user
                                st.session_state["active_nav"] = "Dashboard"
                                db_mgr.log_audit(user["email"], "Sign In", "Successful session authentication.")
                                st.rerun()
                        else:
                            st.error("Invalid HPE credentials. Please check your email or password.")
            
            c1, c2 = st.columns(2)
            if c1.button("Create Account", use_container_width=True):
                st.session_state["auth_mode"] = "Sign Up"
                st.rerun()
            if c2.button("Forgot Password?", use_container_width=True):
                st.session_state["auth_mode"] = "Forgot Password"
                st.rerun()

            st.divider()
            if st.button("🔑 Quick Demo Login (Admin - Arianne Escabillas)", use_container_width=True):
                user = db_mgr.find_user_by_email("arianne.escabillas@hpe.com")
                st.session_state["authenticated"] = True
                st.session_state["auth_user"] = user
                st.session_state["active_nav"] = "Dashboard"
                st.rerun()
            if st.button("👤 Quick Demo Login (Agent - Maria Santos)", use_container_width=True):
                user = db_mgr.find_user_by_email("maria.santos@hpe.com")
                st.session_state["authenticated"] = True
                st.session_state["auth_user"] = user
                st.session_state["active_nav"] = "Dashboard"
                st.rerun()

        elif auth_mode == "Sign Up":
            st.markdown("## Create Your Account")
            st.caption("Sign up to access HPE CaseFlow Roster")
            
            with st.form("signup_form"):
                fn = st.text_input("First Name")
                ln = st.text_input("Last Name")
                emp_id = st.text_input("Employee ID", placeholder="HPE-XXXX")
                email = st.text_input("HPE Email Address", placeholder="firstname.lastname@hpe.com")
                role = st.selectbox("Role", ["AGENT", "ADMIN/AGENT", "ADMIN"])
                dept = st.text_input("Department", value="Compute & GreenLake Global Ops")
                pwd = st.text_input("Password", type="password", help="Must be 8+ chars, with letters, numbers, and special symbol.")
                
                submitted = st.form_submit_button("Sign Up", type="primary", use_container_width=True)
                if submitted:
                    if not all([fn, ln, emp_id, email, pwd]):
                        st.error("All fields are mandatory.")
                    elif not email.endswith("@hpe.com"):
                        st.error("Registration requires an authorized @hpe.com email address.")
                    elif len(pwd) < 8 or not re.search(r"\d", pwd) or not re.search(r"[!@#$%^&*]", pwd):
                        st.error("Password must be at least 8 characters and include numbers and special characters.")
                    elif db_mgr.find_user_by_email(email):
                        st.error("An account with this email address already exists.")
                    else:
                        new_u = {
                            "employee_id": emp_id,
                            "first_name": fn,
                            "last_name": ln,
                            "email": email,
                            "password_hash": hashlib.sha256(pwd.encode()).hexdigest(),
                            "role": role,
                            "status": "Active",
                            "current_aux": "Available",
                            "aux_since": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "active_cases": 0,
                            "today_assigned": 0,
                            "department": dept,
                            "created_at": datetime.now().strftime("%Y-%m-%d")
                        }
                        db_mgr.add_user(new_u)
                        st.success("Account successfully created! Please sign in.")
                        st.session_state["auth_mode"] = "Sign In"
                        st.rerun()

            if st.button("← Back to Sign In"):
                st.session_state["auth_mode"] = "Sign In"
                st.rerun()

        elif auth_mode == "Forgot Password":
            st.markdown("## Reset Your Password")
            st.caption("Provide your verified HPE enterprise email to generate a secure reset token.")
            reset_email = st.text_input("Registered HPE Email")
            if st.button("Send Reset Link", type="primary", use_container_width=True):
                if reset_email and db_mgr.find_user_by_email(reset_email):
                    st.success(f"A secure reset token has been dispatched to {reset_email}.")
                else:
                    st.error("Email not found on Team Roster.")
            if st.button("← Back to Sign In"):
                st.session_state["auth_mode"] = "Sign In"
                st.rerun()

# ==============================================================================
# 6. GLOBAL HEADER COMPONENT
# ==============================================================================
def render_header(user):
    unread_count = len([n for n in st.session_state["notifications"] if not n.get("read", False)])
    
    col_brand, col_search, col_aux, col_profile = st.columns([1.5, 2.5, 1.8, 1.8], gap="medium")
    
    with col_brand:
        st.markdown(
            f"""
            <div style="display: flex; align-items: center; gap: 8px;">
                <div style="background-color: #01A982; width: 12px; height: 32px; border-radius: 2px;"></div>
                <div>
                    <div style="font-weight: 800; font-size: 1.2rem; color: #0B2341; line-height: 1;">HPE CaseFlow</div>
                    <div style="font-size: 0.72rem; color: #616D75;">Team Task & Case Management</div>
                </div>
            </div>
            """, 
            unsafe_allow_html=True
        )

    with col_search:
        search_query = st.text_input(
            "Global Search",
            placeholder="🔍 Search cases, agents, vendors, serials...",
            label_visibility="collapsed",
            key="global_search_input"
        )
        if search_query:
            st.session_state["active_search"] = search_query

    with col_aux:
        current_aux = user.get("current_aux", "Available")
        idx = AUX_STATUSES.index(current_aux) if current_aux in AUX_STATUSES else 0
        new_aux = st.selectbox(
            "Aux Status",
            AUX_STATUSES,
            index=idx,
            label_visibility="collapsed",
            key="aux_status_selector"
        )
        if new_aux != current_aux:
            db_mgr.update_user_aux(user["email"], new_aux)
            user["current_aux"] = new_aux
            st.rerun()

    with col_profile:
        popover = st.popover(f"👤 {user['first_name']} ({user['role']})", use_container_width=True)
        with popover:
            st.markdown(f"### {user['first_name']} {user['last_name']}")
            st.caption(f"ID: {user['employee_id']} | {user['email']}")
            st.markdown(f"**Dept:** {user.get('department', 'Global Services')}")
            st.markdown(f"**Current State:** `{user.get('current_aux', 'Available')}`")
            st.divider()
            
            # Unread Notifications
            st.markdown(f"**Notifications ({unread_count} unread)**")
            for notif in st.session_state["notifications"][:3]:
                st.caption(f"• **{notif['title']}**: {notif['text']}")
            
            st.divider()
            if st.button("Trigger Admin Broadcast Dialog"):
                dlg_admin_broadcast()
            
            if st.button("Sign Out", type="primary", use_container_width=True):
                st.session_state.clear()
                st.rerun()

# ==============================================================================
# 7. SIDEBAR NAVIGATION
# ==============================================================================
def render_sidebar(user):
    with st.sidebar:
        st.markdown(
            """
            <div style="padding: 0.5rem 0 1rem 0; border-bottom: 1px solid #E0E6ED; margin-bottom: 1rem;">
                <span style="background: #01A982; color: white; padding: 2px 6px; border-radius: 4px; font-weight: 700; font-size: 0.8rem;">HPE</span>
                <strong style="color: #0B2341; font-size: 1.05rem; margin-left: 6px;">PORTAL MENU</strong>
            </div>
            """, 
            unsafe_allow_html=True
        )

        role = user.get("role", "AGENT")
        nav_options = []
        
        if role == "ADMIN":
            nav_options = ["Dashboard", "Monitoring", "Schedule", "Reports", "Settings"]
        elif role == "ADMIN/AGENT":
            view_toggle = st.radio("Active View", ["Admin View", "Agent View"], horizontal=True)
            st.session_state["view_mode"] = view_toggle
            if view_toggle == "Admin View":
                nav_options = ["Dashboard", "Monitoring", "Schedule", "Reports", "Settings"]
            else:
                nav_options = ["Dashboard", "Schedule", "Reports"]
        else: # AGENT
            nav_options = ["Dashboard", "Schedule", "Reports"]

        # Keep Case Details accessible if selected
        if st.session_state.get("active_nav") == "Case Details":
            nav_options.append("Case Details")

        current_nav = st.session_state.get("active_nav", "Dashboard")
        if current_nav not in nav_options:
            current_nav = nav_options[0]

        for item in nav_options:
            is_active = (item == current_nav)
            label = f"▸ {item}" if is_active else f"  {item}"
            btn_type = "primary" if is_active else "secondary"
            if st.button(label, key=f"nav_{item}", use_container_width=True, type=btn_type):
                st.session_state["active_nav"] = item
                st.rerun()

        st.markdown("---")
        # Quick System Diagnostics
        st.caption("Environment Health")
        if db_mgr.is_connected:
            st.markdown("<span style='color: #01A982;'>●</span> Mongo Cluster: Connected", unsafe_allow_html=True)
        else:
            st.markdown("<span style='color: #FFAA15;'>●</span> Engine: In-Memory / Local Roster", unsafe_allow_html=True)
        st.caption(f"Session: {datetime.now().strftime('%d %b %Y %H:%M')}")

# ==============================================================================
# 8. DASHBOARD VIEWS (Admin & Agent)
# ==============================================================================
def render_dashboard(user):
    is_admin = (user["role"] == "ADMIN") or (user["role"] == "ADMIN/AGENT" and st.session_state.get("view_mode") != "Agent View")
    
    # Header greeting
    greeting = f"Welcome back, {user['first_name']}!" if is_admin else f"Good day, {user['first_name']}!"
    subtext = "Here is what's happening across your team's case queues today." if is_admin else "Here are your active assigned cases and SLA deadlines."
    st.markdown(f"## {greeting}")
    st.caption(subtext)
    
    # Calculate Metrics
    all_cases = db_mgr.get_cases()
    user_cases = [c for c in all_cases if c.get("assigned_to", "").lower() == user["email"].lower()]
    target_cases = all_cases if is_admin else user_cases
    
    active_count = len([c for c in target_cases if c["status"] not in ["Resolved", "Closed"]])
    critical_count = len([c for c in target_cases if c["priority"] == "Critical" and c["status"] != "Closed"])
    due_soon_count = len([c for c in target_cases if c["status"] in ["Open", "In Progress", "Pending Vendor"]])
    on_track_count = max(0, active_count - critical_count)

    # Top Metric Cards
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(
            f"""
            <div class="metric-card info">
                <div style="font-size: 0.8rem; color: #616D75; font-weight: 600;">ACTIVE CASES</div>
                <div style="font-size: 2rem; font-weight: 700; color: #0B2341;">{active_count}</div>
                <div style="font-size: 0.75rem; color: #01A982;">↑ +4% from last shift</div>
            </div>
            """, 
            unsafe_allow_html=True
        )
    with m2:
        st.markdown(
            f"""
            <div class="metric-card critical">
                <div style="font-size: 0.8rem; color: #616D75; font-weight: 600;">CRITICAL PRIORITY</div>
                <div style="font-size: 2rem; font-weight: 700; color: #DE3618;">{critical_count}</div>
                <div style="font-size: 0.75rem; color: #DE3618;">Requires Immediate Action</div>
            </div>
            """, 
            unsafe_allow_html=True
        )
    with m3:
        st.markdown(
            f"""
            <div class="metric-card warning">
                <div style="font-size: 0.8rem; color: #616D75; font-weight: 600;">DUE IN < 2 HOURS</div>
                <div style="font-size: 2rem; font-weight: 700; color: #FFAA15;">{due_soon_count}</div>
                <div style="font-size: 0.75rem; color: #FFAA15;">SLA Breach Risk Window</div>
            </div>
            """, 
            unsafe_allow_html=True
        )
    with m4:
        st.markdown(
            f"""
            <div class="metric-card">
                <div style="font-size: 0.8rem; color: #616D75; font-weight: 600;">ON TRACK / HEALTHY</div>
                <div style="font-size: 2rem; font-weight: 700; color: #01A982;">{on_track_count}</div>
                <div style="font-size: 0.75rem; color: #01A982;">SLA Compliance: 96.8%</div>
            </div>
            """, 
            unsafe_allow_html=True
        )

    st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
    
    # Main Content Columns (Main Table + Right Rail)
    col_main, col_rail = st.columns([2.7, 1.1], gap="medium")
    
    with col_main:
        st.subheader("Team Task & Case Queue" if is_admin else "My Active Assigned Queue")
        
        # Filters Row
        f1, f2, f3, f4 = st.columns([1.5, 1, 1, 0.5])
        with f1:
            q_search = st.text_input("Filter", placeholder="Filter by subject/client...", label_visibility="collapsed")
        with f2:
            prio_filter = st.selectbox("Priority", ["All Priorities", "Critical", "High", "Medium", "Low"], label_visibility="collapsed")
        with f3:
            status_filter = st.selectbox("Status", ["All Statuses", "Open", "In Progress", "Pending Vendor", "On Hold", "Resolved"], label_visibility="collapsed")
        with f4:
            if st.button("Reset", use_container_width=True):
                st.rerun()

        # Filter Logic
        filtered = target_cases
        if q_search:
            filtered = [c for c in filtered if q_search.lower() in c["subject"].lower() or q_search.lower() in c["client"].lower() or q_search.lower() in c["case_id"].lower()]
        if prio_filter != "All Priorities":
            filtered = [c for c in filtered if c["priority"] == prio_filter]
        if status_filter != "All Statuses":
            filtered = [c for c in filtered if c["status"] == status_filter]

        if not filtered:
            st.info("No cases matching current filter parameters.")
        else:
            for case in filtered:
                with st.container():
                    st.markdown(
                        f"""
                        <div class="hpe-card" style="margin-bottom: 0.75rem;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                                <div>
                                    <strong style="color: #00739D; font-size: 1.05rem;">{case['case_id']}</strong>
                                    <span style="margin-left: 8px; font-weight: 600; color: #0B2341;">{case['subject']}</span>
                                </div>
                                <div>
                                    <span class="badge badge-{case['priority'].lower()}">{case['priority']}</span>
                                </div>
                            </div>
                            <div style="font-size: 0.85rem; color: #616D75; display: flex; gap: 18px; margin-bottom: 8px;">
                                <span>🏢 Client: <strong>{case.get('client', 'Global Account')}</strong></span>
                                <span>👤 Assigned: <strong>{case.get('assigned_to', 'Unassigned')}</strong></span>
                                <span>⏱ Due: <strong>{case.get('due_date')}</strong></span>
                                <span>Status: <strong>{case.get('status')}</strong></span>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                    c_btn, c_assign, _ = st.columns([1, 1.2, 3])
                    if c_btn.button(f"Manage Case", key=f"btn_manage_{case['case_id']}"):
                        st.session_state["selected_case_id"] = case['case_id']
                        st.session_state["active_nav"] = "Case Details"
                        st.rerun()
                    if is_admin:
                        new_owner = c_assign.selectbox("Quick Reassign", [u["email"] for u in db_mgr.get_users()], key=f"reassign_{case['case_id']}", label_visibility="collapsed")
                        if new_owner != case.get("assigned_to"):
                            if c_assign.button("Confirm", key=f"confirm_reas_{case['case_id']}"):
                                case["assigned_to"] = new_owner
                                db_mgr.log_case_history(case["case_id"], user["email"], "Quick Reassign", f"Reassigned to {new_owner}")
                                st.rerun()

    with col_rail:
        if is_admin:
            st.subheader("Agents Online")
            agents = db_mgr.get_users()
            for ag in agents:
                aux = ag.get("current_aux", "Available")
                badge_class = f"badge-{aux.lower().replace(' ', '').replace('-', '')}"
                st.markdown(
                    f"""
                    <div style="background: white; border: 1px solid #E0E6ED; border-radius: 6px; padding: 10px; margin-bottom: 8px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <strong>{ag['first_name']} {ag['last_name']}</strong>
                                <div style="font-size: 0.72rem; color: #616D75;">{ag['role']} • Cases: {ag.get('active_cases', 0)}</div>
                            </div>
                            <span class="badge {badge_class}">{aux}</span>
                        </div>
                    </div>
                    """, 
                    unsafe_allow_html=True
                )
            
            st.divider()
            st.subheader("Create Quick Case")
            with st.form("quick_case_form"):
                n_subj = st.text_input("Subject", placeholder="E.g., Storage SAN failure")
                n_prio = st.selectbox("Priority", ["Critical", "High", "Medium", "Low"])
                n_client = st.text_input("Client", value="Enterprise Partner")
                vendor_options = [v["name"] for v in st.session_state.get("vendors", [])] + ["Intel Platform Support"]
                n_vendor = st.selectbox("Vendor Component", list(dict.fromkeys(vendor_options)))
                n_due = (datetime.now() + timedelta(hours=4)).strftime("%Y-%m-%d %H:%M")
                if st.form_submit_button("Auto-Assign & Dispatch", type="primary", use_container_width=True):
                    new_c = {
                        "case_id": f"CAS-{uuid.uuid4().hex[:5].upper()}",
                        "subject": n_subj or "Mission Critical System Issue",
                        "priority": n_prio,
                        "status": "Open",
                        "category": "Enterprise Infrastructure",
                        "client": n_client,
                        "vendor": n_vendor,
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "due_date": n_due,
                        "last_update": "Initial ticket intake.",
                        "related_system": "ProLiant Gen11 Compute Core"
                    }
                    assigned_to = auto_assign_case(new_c)
                    if assigned_to:
                        st.success(f"Case dispatched automatically to {assigned_to['email']}!")
                    else:
                        st.warning("Case created but no agents were currently Available.")
                    st.rerun()

        else: # Agent Right Rail: Schedule Preview & Quick Actions
            st.subheader("My Shift Overview")
            st.markdown(
                """
                <div class="hpe-card">
                    <div style="font-weight: 700; color: #0B2341; margin-bottom: 6px;">Today's Shift: 08:00 - 17:00</div>
                    <div style="font-size: 0.85rem; color: #616D75;">
                        • 08:00 - 10:00: Case Work<br/>
                        • 10:00 - 10:15: Morning Break<br/>
                        • 10:15 - 12:00: Critical Case Work<br/>
                        • 12:00 - 13:00: Lunch<br/>
                        • 13:00 - 14:00: 1:1 Coaching<br/>
                        • 14:00 - 17:00: Dispatch & Queue Resolution
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
            st.subheader("Quick Actions")
            if st.button("Request Shift Swap", use_container_width=True):
                dlg_schedule_swap("John Dela Cruz", "Tomorrow (10:00-19:00)")
            if st.button("Simulate Incoming Case Alert", use_container_width=True):
                if target_cases:
                    dlg_new_case(target_cases[0])

# ==============================================================================
# 9. CASE DETAILS & WORKFLOW ENGINE
# ==============================================================================
def render_case_details(user):
    case_id = st.session_state.get("selected_case_id", "CAS-98214")
    case = db_mgr.get_case_by_id(case_id)
    
    if not case:
        st.error(f"Case {case_id} not found.")
        if st.button("← Return to Dashboard"):
            st.session_state["active_nav"] = "Dashboard"
            st.rerun()
        return

    # Header Bar
    c_back, c_title, c_actions = st.columns([0.6, 2.5, 1.2])
    with c_back:
        if st.button("← Back"):
            st.session_state["active_nav"] = "Dashboard"
            st.rerun()
    with c_title:
        st.markdown(f"### Case Details: `{case['case_id']}`")
        st.caption(f"{case['subject']} • Created on {case['created_at']}")
    with c_actions:
        st.markdown(f"**Current SLA State:** <span class='badge badge-{case['priority'].lower()}'>{case['priority']}</span>", unsafe_allow_html=True)

    t1, t2, t3, t4 = st.tabs(["Case Information", "Vendor Information", "Communication & Breach", "Case History"])
    
    with t1:
        c1, c2 = st.columns(2)
        with c1:
            st.text_input("Case Number", value=case["case_id"], disabled=True)
            st.text_input("Account / Client", value=case.get("client", "Global Client"))
            new_prio = st.selectbox("Priority SLA", ["Critical", "High", "Medium", "Low"], index=["Critical", "High", "Medium", "Low"].index(case["priority"]))
            new_status = st.selectbox("Status", ["Open", "In Progress", "Pending Vendor", "On Hold", "Resolved", "Closed"], index=["Open", "In Progress", "Pending Vendor", "On Hold", "Resolved", "Closed"].index(case.get("status", "Open")))
        with c2:
            st.text_input("Assigned Engineer", value=case.get("assigned_to", "Unassigned"), disabled=True)
            st.text_input("Due Date SLA", value=case.get("due_date", "Pending"))
            st.text_input("Impacted Component / System", value=case.get("related_system", "HPE Infrastructure Platform"))
            update_notes = st.text_area("Update Notes / Activity Log", placeholder="Add latest progress telemetry...")
            
        if st.button("Save & Update Case Record", type="primary"):
            updates = {"priority": new_prio, "status": new_status}
            if update_notes:
                updates["last_update"] = update_notes
            db_mgr.update_case(case_id, updates, user["email"])
            st.success("Case successfully updated.")
            st.rerun()

        st.divider()
        st.markdown("#### Operational Escalation & Transfer")
        t_col1, t_col2 = st.columns(2)
        target_agent = t_col1.selectbox("Transfer Case to Agent", [u["email"] for u in db_mgr.get_users() if u["email"] != user["email"]])
        if t_col2.button("Initiate Transfer Request", use_container_width=True):
            dlg_transfer_request(case_id, user["email"])

    with t2:
        st.markdown("#### Vendor Integration Details")
        st.markdown(f"**Active Partner / Supplier:** `{case.get('vendor', 'Intel Platform Engineering')}`")
        v_col1, v_col2 = st.columns(2)
        with v_col1:
            st.text_input("Vendor Escalation Contact", value="David Vance - Senior Lead")
            st.text_input("Vendor Direct Email", value="tier3-intel-hpe-escalation@intel.com")
            if st.button("📋 Copy Vendor Email"):
                st.toast("Vendor email copied to clipboard.")
        with v_col2:
            st.text_input("Vendor Case Reference", value="INTEL-ENG-772910")
            st.text_input("Support Hot-line", value="+1-800-456-7890 (Ext: 9)")
            if st.button("📞 Log Vendor Call"):
                st.toast("Call session recorded in case audit.")

    with t3:
        st.markdown("#### Automated Breach Notification Generator")
        st.caption("Standardized SLA mitigation and contract adherence communication.")
        with st.form("breach_email_form"):
            b_to = st.text_input("Recipient", value=f"{case.get('client', 'client')}@partner-corp.com")
            b_subj = st.text_input("Email Subject", value=f"[URGENT] SLA Advisory: HPE Case {case['case_id']} - {case['subject']}")
            b_body = st.text_area(
                "Email Body", 
                value=f"Dear Partner Team,\n\nWe are actively managing Case {case['case_id']}. Our Tier-3 engineering staff is engaged with {case.get('vendor', 'our hardware partners')} to ensure prompt resolution prior to critical operational windows.\n\nNext scheduled telemetry checkpoint: 30 minutes.\n\nBest regards,\nHPE Global Mission Critical Operations",
                height=150
            )
            if st.form_submit_button("Transmit Breach Mitigation Notice", type="primary"):
                db_mgr.log_case_history(case_id, user["email"], "Breach Notice Sent", f"Email dispatched to {b_to}")
                st.success(f"Notification officially dispatched to {b_to}.")

    with t4:
        st.markdown("#### Case Event Timeline")
        hist = st.session_state["case_history"].get(case_id, [
            {"timestamp": case["created_at"], "actor": "SYSTEM", "action": "Case Intake", "description": "Ticket received and ingested via telemetry pipeline."}
        ])
        for event in reversed(hist):
            st.markdown(
                f"""
                <div style="border-left: 3px solid #01A982; padding-left: 14px; margin-bottom: 12px;">
                    <div style="font-weight: 700; color: #0B2341;">{event['action']} - <span style="font-weight: 400; color: #616D75;">{event['timestamp']}</span></div>
                    <div style="font-size: 0.85rem; color: #00739D;">Actor: {event['actor']}</div>
                    <div style="font-size: 0.85rem; color: #333333;">{event['description']}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

# ==============================================================================
# 10. MONITORING (Admin Real-Time Agent Matrix)
# ==============================================================================
def render_monitoring(user):
    st.markdown("## Real-Time Operations Monitoring")
    st.caption("Supervise agent presence, current Aux, workload volume, and system readiness.")
    
    users = db_mgr.get_users()
    total_logged_in = len(users)
    available_c = len([u for u in users if u.get("current_aux") == "Available"])
    on_aux_c = len([u for u in users if u.get("current_aux") in ["Break", "Lunch", "Unscheduled Break"]])
    coaching_c = len([u for u in users if u.get("current_aux") in ["Coaching", "Meeting"]])
    not_ready_c = len([u for u in users if u.get("current_aux") == "Not Ready - Online"])

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Logged In", total_logged_in)
    c2.metric("Available for Dispatch", available_c)
    c3.metric("On Rest / Lunch", on_aux_c)
    c4.metric("In Meeting / Coaching", coaching_c)
    c5.metric("Not Ready", not_ready_c)
    
    st.divider()
    st.subheader("Active Agent Roster")
    
    # Render table
    df_data = []
    for u in users:
        df_data.append({
            "Employee ID": u["employee_id"],
            "Agent Name": f"{u['first_name']} {u['last_name']}",
            "Role": u["role"],
            "Current Aux": u.get("current_aux", "Available"),
            "Aux Since": u.get("aux_since", "08:00 AM"),
            "Active Cases": u.get("active_cases", 0),
            "Assigned Today": u.get("today_assigned", 0),
            "Status": u.get("status", "Active")
        })
    df_roster = pd.DataFrame(df_data)
    st.dataframe(df_roster, use_container_width=True, hide_index=True)

    st.markdown("#### Individual Agent Inspection & Drawer")
    sel_agent_email = st.selectbox("Inspect Agent State", [u["email"] for u in users])
    target = db_mgr.find_user_by_email(sel_agent_email)
    if target:
        with st.container():
            st.markdown(
                f"""
                <div class="hpe-card">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <h4>{target['first_name']} {target['last_name']} ({target['employee_id']})</h4>
                            <div>Department: {target.get('department', 'Global Services')} | Role: <strong>{target['role']}</strong></div>
                            <div>Current Aux: <strong>{target.get('current_aux', 'Available')}</strong> (Since: {target.get('aux_since')})</div>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
            b1, b2 = st.columns(2)
            if b1.button("Send Direct Admin Push Message", key="btn_push_msg"):
                dlg_admin_broadcast()
            if b2.button("Force Aux State Reset (Available)", key="btn_force_aux"):
                db_mgr.update_user_aux(target["email"], "Available")
                st.success("User forced into Available dispatch state.")
                st.rerun()

# ==============================================================================
# 11. SCHEDULE MANAGEMENT (Admin & Agent)
# ==============================================================================
def render_schedule(user):
    is_admin = (user["role"] == "ADMIN") or (user["role"] == "ADMIN/AGENT" and st.session_state.get("view_mode") != "Agent View")
    
    st.markdown("## Schedule & Rostering Operations")
    st.caption("Administer shift rotations, PTO allocation allowances, and emergency leave requests.")
    
    if is_admin:
        tab_admin_cal, tab_requests = st.tabs(["Team Weekly Schedule Grid", "PTO & Leave Approvals"])
        
        with tab_admin_cal:
            st.subheader("Shift Allocation - Current Work Week")
            time_slots = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00"]
            schedule_grid = []
            for u in db_mgr.get_users():
                row = {"Agent": f"{u['first_name']} {u['last_name']}"}
                for t in time_slots:
                    if t == "12:00":
                        row[t] = "Lunch"
                    elif t == "10:00":
                        row[t] = "Break"
                    elif t == "14:00" and u["first_name"] == "Mark":
                        row[t] = "Coaching"
                    else:
                        row[t] = "Case Work"
                schedule_grid.append(row)
            st.dataframe(pd.DataFrame(schedule_grid), use_container_width=True, hide_index=True)

            col1, col2 = st.columns(2)
            if col1.button("Auto-Plot Next Week Schedule", type="primary"):
                st.success("Fair-distribution scheduling algorithm plotted shifts for next 7 days.")
            if col2.button("Export Schedule (CSV)"):
                st.toast("Schedule exported.")

        with tab_requests:
            st.subheader("Pending Leave Requests")
            reqs = st.session_state.get("pto_requests", [])
            for r in reqs:
                st.markdown(
                    f"""
                    <div class="hpe-card">
                        <div style="display: flex; justify-content: space-between;">
                            <div>
                                <strong>{r['name']}</strong> — <span style="color: #00739D;">{r['type']}</span>
                                <div>Dates: <strong>{r['dates']}</strong> | Reason: {r['reason']}</div>
                            </div>
                            <div>
                                <strong>Status: {r['status']}</strong>
                            </div>
                        </div>
                    </div>
                    """, 
                    unsafe_allow_html=True
                )
                c_app, c_dec, _ = st.columns([1, 1, 3])
                if c_app.button(f"Approve", key=f"app_{r['req_id']}"):
                    r["status"] = "Approved"
                    db_mgr.log_audit(user["email"], "Leave Approval", f"Approved {r['type']} for {r['name']}")
                    st.rerun()
                if c_dec.button(f"Decline", key=f"dec_{r['req_id']}"):
                    r["status"] = "Declined"
                    st.rerun()

    else: # Agent Personal Schedule & Request Filing
        st.subheader("My Weekly Shift Schedule")
        my_schedule = {
            "Monday": "08:00 - 17:00 (Case Work & Dispatch)",
            "Tuesday": "08:00 - 17:00 (1:1 Coaching 14:00)",
            "Wednesday": "08:00 - 17:00 (Case Work)",
            "Thursday": "08:00 - 17:00 (Storage Guild Meeting 11:00)",
            "Friday": "08:00 - 17:00 (Queue Wrap-up)"
        }
        for day, shift in my_schedule.items():
            st.markdown(f"**{day}:** `{shift}`")
            
        st.divider()
        st.subheader("Submit Time-Off / Leave Request")
        with st.form("pto_submit_form"):
            l_type = st.selectbox("Leave Type", ["PTO", "Sick Leave", "Emergency Leave"])
            l_dates = st.text_input("Requested Date(s)", placeholder="YYYY-MM-DD to YYYY-MM-DD")
            l_reason = st.text_area("Reason / Coverage Plan")
            if st.form_submit_button("Submit Request", type="primary"):
                st.session_state["pto_requests"].append({
                    "req_id": f"PTO-{uuid.uuid4().hex[:4].upper()}",
                    "name": f"{user['first_name']} {user['last_name']}",
                    "email": user["email"],
                    "type": l_type,
                    "dates": l_dates,
                    "status": "Pending",
                    "reason": l_reason
                })
                st.success("Your request has been submitted to Operations Admin.")
                st.rerun()

# ==============================================================================
# 12. REPORTS & ANALYTICS (Admin & Agent)
# ==============================================================================
def render_reports(user):
    is_admin = (user["role"] == "ADMIN") or (user["role"] == "ADMIN/AGENT" and st.session_state.get("view_mode") != "Agent View")
    st.markdown("## Operational Performance & SLA Intelligence")
    st.caption("Resolution time curves, priority distribution, adherence tracking, and vendor breach analysis.")
    
    p1, p2 = st.columns([1, 4])
    period = p1.selectbox("Reporting Period", ["Daily", "Week-over-Week (WOW)", "Month-to-Date (MTD)", "Year-to-Date (YTD)"])
    
    # Chart 1: Priority Distribution
    cases = db_mgr.get_cases()
    df_cases = pd.DataFrame(cases)
    
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.subheader("Case Breakdown by Priority")
        fig_prio = px.pie(
            df_cases, 
            names="priority", 
            color="priority",
            color_discrete_map={"Critical": "#DE3618", "High": "#FFAA15", "Medium": "#00739D", "Low": "#01A982"},
            hole=0.45
        )
        fig_prio.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=280)
        st.plotly_chart(fig_prio, use_container_width=True)

    with col_c2:
        st.subheader("Case Volume by Status")
        fig_status = px.bar(
            df_cases,
            x="status",
            color="status",
            color_discrete_sequence=["#01A982", "#00739D", "#FFAA15", "#DE3618", "#763082"]
        )
        fig_status.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=280, showlegend=False)
        st.plotly_chart(fig_status, use_container_width=True)

    if is_admin:
        st.divider()
        st.subheader("Team Resolution SLA Adherence")
        adherence_df = pd.DataFrame([
            {"Agent": "Arianne Escabillas", "Scheduled Hours": 40, "In Adherence": 38.8, "Adherence %": "97.0%", "Resolved": 14},
            {"Agent": "John Dela Cruz", "Scheduled Hours": 40, "In Adherence": 39.1, "Adherence %": "97.7%", "Resolved": 18},
            {"Agent": "Maria Santos", "Scheduled Hours": 40, "In Adherence": 38.0, "Adherence %": "95.0%", "Resolved": 22},
            {"Agent": "Mark Tan", "Scheduled Hours": 40, "In Adherence": 37.2, "Adherence %": "93.0%", "Resolved": 12},
        ])
        st.dataframe(adherence_df, use_container_width=True, hide_index=True)
    else:
        st.divider()
        st.subheader("My Individual Adherence Factor")
        m1, m2, m3 = st.columns(3)
        m1.metric("Schedule Adherence", "96.4%", "+1.2%")
        m2.metric("Mean Time to Resolution (MTTR)", "3.2 Hours", "-0.4h")
        m3.metric("First-Contact Resolution", "88.5%", "+3.0%")

# ==============================================================================
# 13. SETTINGS & TEAM MANAGEMENT (Admin Only)
# ==============================================================================
def render_settings(user):
    st.markdown("## System Configuration & Administration")
    st.caption("Manage roster access, vendor integrations, data synchronizations, and system audit logs.")
    
    t_roster, t_vendors, t_audit = st.tabs(["Team Roster Management", "External Vendors & Sync", "Audit Activity Trail"])
    
    with t_roster:
        st.subheader("Team Roster")
        users = db_mgr.get_users()
        for idx, u in enumerate(users):
            with st.container():
                st.markdown(
                    f"""
                    <div class="hpe-card">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <strong>{u['first_name']} {u['last_name']}</strong> ({u['email']})
                                <div style="font-size: 0.8rem; color: #616D75;">Employee ID: {u['employee_id']} | Role: <strong>{u['role']}</strong> | Status: <strong>{u['status']}</strong></div>
                            </div>
                        </div>
                    </div>
                    """, 
                    unsafe_allow_html=True
                )
                r1, r2, r3, _ = st.columns([1, 1, 1, 3])
                new_role = r1.selectbox("Role", ["AGENT", "ADMIN/AGENT", "ADMIN"], index=["AGENT", "ADMIN/AGENT", "ADMIN"].index(u["role"]), key=f"r_role_{idx}", label_visibility="collapsed")
                if new_role != u["role"]:
                    u["role"] = new_role
                    db_mgr.log_audit(user["email"], "Role Modified", f"Changed role of {u['email']} to {new_role}")
                    st.rerun()
                
                status_action = "Deactivate" if u["status"] == "Active" else "Activate"
                if r2.button(status_action, key=f"tog_stat_{idx}"):
                    u["status"] = "Deactivated" if u["status"] == "Active" else "Active"
                    db_mgr.log_audit(user["email"], "Account Status Modified", f"Toggled status of {u['email']} to {u['status']}")
                    st.rerun()

                if r3.button("Reset Pwd", key=f"reset_pwd_{idx}"):
                    st.toast(f"Password reset email sent to {u['email']}")

    with t_vendors:
        st.subheader("Vendor Contacts & Integrations")
        for v in st.session_state["vendors"]:
            st.markdown(f"**{v['name']}** — Contact: `{v['contact']}` | `{v['email']}` | Category: *{v['category']}*")
        
        st.divider()
        st.markdown("#### Automated Synchronization Schedule")
        c1, c2 = st.columns(2)
        c1.toggle("Auto-Sync Vendor Telemetry", value=True)
        c2.selectbox("Sync Frequency", ["Every 15 minutes", "Hourly", "Twice Daily (08:00 & 20:00)"])
        if st.button("Trigger Immediate Synchronous Pull", type="primary"):
            st.success("Telemetry synchronized with hardware partner databases.")

    with t_audit:
        st.subheader("System Event & Security Audit Trail")
        st.dataframe(pd.DataFrame(st.session_state["audit_logs"]), use_container_width=True, hide_index=True)

# ==============================================================================
# 14. APPLICATION ROUTER & EXECUTION
# ==============================================================================
def main():
    # Authentication check
    if not st.session_state.get("authenticated", False):
        render_auth()
        return

    # User is authenticated: Render full enterprise interface
    current_user = st.session_state.get("auth_user")
    
    # 1. Global Application Header
    render_header(current_user)
    
    # 2. Side Navigation
    render_sidebar(current_user)
    
    # 3. View Routing
    active_nav = st.session_state.get("active_nav", "Dashboard")
    
    if active_nav == "Dashboard":
        render_dashboard(current_user)
    elif active_nav == "Case Details":
        render_case_details(current_user)
    elif active_nav == "Monitoring":
        if current_user["role"] in ["ADMIN", "ADMIN/AGENT"]:
            render_monitoring(current_user)
        else:
            st.error("Access Restricted. Monitoring is an administrative function.")
    elif active_nav == "Schedule":
        render_schedule(current_user)
    elif active_nav == "Reports":
        render_reports(current_user)
    elif active_nav == "Settings":
        if current_user["role"] == "ADMIN":
            render_settings(current_user)
        else:
            st.error("Access Restricted. Administrator role required.")

if __name__ == "__main__":
    main()
