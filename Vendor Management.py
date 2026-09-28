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

# HPE Corporate Enterprise Design System (CSS)
HPE_ENTERPRISE_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        color: #0B2341;
        background-color: #F4F7F9;
    }
    
    /* Remove default Streamlit header, footer, and excessive spacing */
    #MainMenu, header, footer { visibility: hidden !important; }
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 2rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
    }
    
    /* Application Cards */
    .hpe-card {
        background: #FFFFFF;
        border-radius: 8px;
        padding: 1.25rem;
        border: 1px solid #E0E6ED;
        box-shadow: 0 2px 6px rgba(11, 35, 65, 0.04);
        margin-bottom: 1rem;
    }
    
    /* Top Metric KPI Cards */
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
    .badge-adminwork { background-color: #E5F3F8; color: #00739D; border: 1px solid #00739D; }
    .badge-notreadyonline { background-color: #FCEBE8; color: #DE3618; border: 1px solid #DE3618; }
    .badge-coaching { background-color: #F5EBF7; color: #763082; border: 1px solid #763082; }
    .badge-meeting { background-color: #FFF6E6; color: #FFAA15; border: 1px solid #FFAA15; }
    .badge-lunch { background-color: #FFFDE6; color: #B38600; border: 1px solid #B38600; }
    .badge-break { background-color: #EFF1F3; color: #616D75; border: 1px solid #616D75; }
    .badge-unscheduledbreak { background-color: #E9ECEF; color: #495057; border: 1px solid #6C757D; }
    
    .badge-critical { background-color: #FCEBE8; color: #DE3618; font-weight: 700; border: 1px solid #DE3618; }
    .badge-high { background-color: #FFF0E6; color: #E26815; font-weight: 600; border: 1px solid #E26815; }
    .badge-medium { background-color: #FFFBE6; color: #B38600; border: 1px solid #B38600; }
    .badge-low { background-color: #EBF8F2; color: #01A982; border: 1px solid #01A982; }
    
    .badge-open { background-color: #E5F3F8; color: #00739D; }
    .badge-inprogress { background-color: #E6F6F2; color: #01A982; }
    .badge-onhold { background-color: #FFF6E6; color: #FFAA15; }
    .badge-pendingvendor { background-color: #FFFBE6; color: #B38600; }
    .badge-pendinginternal { background-color: #F5EBF7; color: #763082; }
    .badge-resolved { background-color: #D1E7DD; color: #0F5132; }
    .badge-closed { background-color: #E9ECEF; color: #495057; }
    
    /* Navigation button styling */
    .stButton>button {
        border-radius: 5px;
        font-weight: 500;
        transition: all 0.2s ease-in-out;
    }
</style>
"""
st.markdown(HPE_ENTERPRISE_CSS, unsafe_allow_html=True)

# ==============================================================================
# 2. DATABASE & PERSISTENCE LAYER (PyMongo with Session State Fail-Safe)
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
        "aux_since": "08:00 AM",
        "active_cases": 2,
        "today_assigned": 4,
        "department": "Global Mission Critical Support",
        "date_created": "2026-01-10",
        "last_login": datetime.now().strftime("%Y-%m-%d %H:%M")
    },
    {
        "employee_id": "HPE-1002",
        "first_name": "John",
        "last_name": "Dela Cruz",
        "email": "john.delacruz@hpe.com",
        "password_hash": hashlib.sha256("Admin@123".encode()).hexdigest(),
        "role": "ADMIN/AGENT",
        "status": "Active",
        "current_aux": "Available",
        "aux_since": "08:15 AM",
        "active_cases": 3,
        "today_assigned": 5,
        "department": "Compute Platform Group",
        "date_created": "2026-02-01",
        "last_login": datetime.now().strftime("%Y-%m-%d %H:%M")
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
        "aux_since": "08:30 AM",
        "active_cases": 4,
        "today_assigned": 6,
        "department": "Storage Ops & Alletra",
        "date_created": "2026-02-15",
        "last_login": datetime.now().strftime("%Y-%m-%d %H:%M")
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
        "aux_since": "09:00 AM",
        "active_cases": 1,
        "today_assigned": 2,
        "department": "HPE GreenLake Cloud Ops",
        "date_created": "2026-03-01",
        "last_login": datetime.now().strftime("%Y-%m-%d %H:%M")
    },
    {
        "employee_id": "HPE-1005",
        "first_name": "Liza",
        "last_name": "Garcia",
        "email": "liza.garcia@hpe.com",
        "password_hash": hashlib.sha256("Agent@123".encode()).hexdigest(),
        "role": "AGENT",
        "status": "Active",
        "current_aux": "Admin Work",
        "aux_since": "08:45 AM",
        "active_cases": 2,
        "today_assigned": 3,
        "department": "Aruba Edge Operations",
        "date_created": "2026-03-15",
        "last_login": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
]

DEFAULT_CASES = [
    {
        "case_id": "HC-2026-1044",
        "subject": "License Renewal Delay",
        "priority": "Critical",
        "assigned_to": "john.delacruz@hpe.com",
        "status": "On Hold",
        "case_type": "License Renewal",
        "account": "ABC Enterprise",
        "client": "ABC Enterprise Global",
        "related_system": "HPE Licensing Portal",
        "vendor": "Intel Xeon Platform Support",
        "created_date": (datetime.now() - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M"),
        "due_date": (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
        "last_update": "Waiting for Vendor Response. Authorization token pending.",
        "description": "Enterprise customer license renewal request stuck at authorization gate."
    },
    {
        "case_id": "CAS-98214",
        "subject": "GreenLake Flex Capacity Ingestion Latency Breach",
        "priority": "Critical",
        "assigned_to": "maria.santos@hpe.com",
        "status": "In Progress",
        "case_type": "Capacity Breach",
        "account": "Financial Corp Global",
        "client": "Financial Corp Global",
        "related_system": "ProLiant Gen11 / GreenLake Core",
        "vendor": "Intel Xeon Platform Support",
        "created_date": (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"),
        "due_date": (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
        "last_update": "Telemetry verified, pending vendor diagnostic dump.",
        "description": "High latency in metering telemetry causing billing pipeline lag."
    },
    {
        "case_id": "CAS-98215",
        "subject": "Synergy Interconnect Module Firmware Desync",
        "priority": "High",
        "assigned_to": "john.delacruz@hpe.com",
        "status": "Pending Vendor",
        "case_type": "Hardware Defect",
        "account": "AeroSpace Dynamics Ltd",
        "client": "AeroSpace Dynamics Ltd",
        "related_system": "HPE Synergy 12000 Frame",
        "vendor": "Brocade SAN Networking",
        "created_date": (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M"),
        "due_date": (datetime.now() + timedelta(hours=4)).strftime("%Y-%m-%d %H:%M"),
        "last_update": "Awaiting engineer response on ticket BR-8820.",
        "description": "Module 3 dropped redundant link after scheduled microcode patch."
    },
    {
        "case_id": "CAS-98216",
        "subject": "StoreOnce 5660 Replication Target Offline",
        "priority": "Critical",
        "assigned_to": "arianne.escabillas@hpe.com",
        "status": "Open",
        "case_type": "Service Outage",
        "account": "HealthAlliance National",
        "client": "HealthAlliance National",
        "related_system": "HPE StoreOnce Catalyst",
        "vendor": "Veeam Core Integration",
        "created_date": (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
        "due_date": (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
        "last_update": "Heartbeat failure detected on Catalyst interface.",
        "description": "Secondary backup target unreachable. Replication queue accumulating."
    },
    {
        "case_id": "CAS-98217",
        "subject": "Alletra 9000 Node Controller NVMe Degraded",
        "priority": "Medium",
        "assigned_to": "maria.santos@hpe.com",
        "status": "Pending Internal",
        "case_type": "Hardware Replacement",
        "account": "Nordic Telecommunications",
        "client": "Nordic Telecommunications",
        "related_system": "Alletra MP Block Storage",
        "vendor": "Samsung Semiconductor",
        "created_date": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
        "due_date": (datetime.now() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"),
        "last_update": "Part dispatched. Tracking: 8492049281.",
        "description": "Predictive sparing triggered for controller 0 NVMe SSD drive."
    },
    {
        "case_id": "CAS-98218",
        "subject": "Aruba Central Switch Stack Uplink Flapping",
        "priority": "Low",
        "assigned_to": "mark.tan@hpe.com",
        "status": "Resolved",
        "case_type": "Network Event",
        "account": "Retail Supermarkets Group",
        "client": "Retail Supermarkets Group",
        "related_system": "CX 6300M Series",
        "vendor": "Aruba Edge Services",
        "created_date": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M"),
        "due_date": (datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M"),
        "last_update": "Replaced SFP+ 10G transceiver. Link stabilized.",
        "description": "Port 1/1/48 intermittent state changes logged."
    }
]

class DatabaseManager:
    """Manages MongoDB cluster connection with safe fallback to session-state repository."""
    def __init__(self):
        self.is_connected = False
        self.db = None
        self.collection = None
        try:
            from pymongo import MongoClient
            mongo_uri = os.environ.get("MONGO_URI") or st.secrets.get("mongo_uri", None)
            if mongo_uri:
                client = MongoClient(mongo_uri, serverSelectionTimeoutMS=1500)
                client.server_info()
                self.db = client["TeamRoster"]
                self.collection = self.db["Team Roster Collection"]
                self.is_connected = True
        except Exception:
            self.is_connected = False
            
        self._init_memory_store()

    def _init_memory_store(self):
        if "roster_list" not in st.session_state:
            st.session_state["roster_list"] = DEFAULT_USERS.copy()
        if "case_list" not in st.session_state:
            st.session_state["case_list"] = DEFAULT_CASES.copy()
        if "case_history" not in st.session_state:
            st.session_state["case_history"] = {
                "HC-2026-1044": [
                    {"timestamp": "2026-09-28 08:45 AM", "user": "John Dela Cruz", "action": "Status changed to On Hold", "description": "Waiting for Vendor Response"},
                    {"timestamp": "2026-09-28 07:30 AM", "user": "SYSTEM", "action": "Case Intake", "description": "Inward telemetry ticket logged from HPE Licensing Portal"}
                ]
            }
        if "pto_requests" not in st.session_state:
            st.session_state["pto_requests"] = [
                {"req_id": "PTO-101", "name": "Maria Santos", "email": "maria.santos@hpe.com", "type": "PTO", "dates": "2026-10-12 to 2026-10-14", "status": "Approved", "reason": "Family gathering"},
                {"req_id": "PTO-102", "name": "Mark Tan", "email": "mark.tan@hpe.com", "type": "Sick Leave", "dates": "2026-10-01", "status": "Pending", "reason": "Medical follow-up"}
            ]
        if "notifications" not in st.session_state:
            st.session_state["notifications"] = [
                {"id": "notif-1", "user_email": "maria.santos@hpe.com", "title": "New Case Assigned", "text": "Case CAS-98214 assigned to you.", "time": "10 mins ago", "read": False, "case_id": "CAS-98214"},
                {"id": "notif-2", "user_email": "arianne.escabillas@hpe.com", "title": "Critical Case Alert", "text": "CAS-98216 approaching breach window.", "time": "25 mins ago", "read": False, "case_id": "CAS-98216"},
                {"id": "notif-3", "user_email": "john.delacruz@hpe.com", "title": "Transfer Request", "text": "Transfer request pending for HC-2026-1044.", "time": "1 hour ago", "read": False, "case_id": "HC-2026-1044"}
            ]
        if "vendors" not in st.session_state:
            st.session_state["vendors"] = [
                {"name": "Intel Xeon Platform Support", "contact": "David Vance", "email": "d.vance@intel.com", "phone": "+1-800-456-7890", "category": "Compute / Silicon", "status": "Active"},
                {"name": "Samsung Semiconductor", "contact": "Elena Rostova", "email": "e.rostova@samsung.com", "phone": "+1-888-234-5678", "category": "Storage / NVMe", "status": "Active"},
                {"name": "Brocade SAN Networking", "contact": "Arthur Dent", "email": "support@brocade.com", "phone": "+1-877-990-1234", "category": "Fibre Channel", "status": "Active"},
                {"name": "Veeam Core Integration", "contact": "Sarah Connor", "email": "s.connor@veeam.com", "phone": "+1-800-112-9876", "category": "Software / Backup", "status": "Active"}
            ]
        if "audit_logs" not in st.session_state:
            st.session_state["audit_logs"] = [
                {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "user": "SYSTEM", "activity": "System Initialization", "details": "HPE CaseFlow engine online."}
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
        self.log_audit(user_dict["email"], "Account Created", f"Registered new user {user_dict['email']} as {user_dict['role']}.")

    def update_user_aux(self, email, new_aux):
        for u in st.session_state["roster_list"]:
            if u["email"].lower() == email.lower():
                old_aux = u.get("current_aux", "Available")
                u["current_aux"] = new_aux
                u["aux_since"] = datetime.now().strftime("%I:%M %p")
                self.log_audit(email, "Aux Changed", f"Changed Aux state from {old_aux} to {new_aux}")
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
                self.log_audit(actor, "Case Update", f"Case {case_id} modified.")
                break

    def log_case_history(self, case_id, user, action, desc):
        if case_id not in st.session_state["case_history"]:
            st.session_state["case_history"][case_id] = []
        st.session_state["case_history"][case_id].insert(0, {
            "timestamp": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
            "user": user,
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

    def add_notification(self, user_email, title, text, case_id=None):
        st.session_state["notifications"].insert(0, {
            "id": f"notif-{uuid.uuid4().hex[:6]}",
            "user_email": user_email,
            "title": title,
            "text": text,
            "time": "Just now",
            "read": False,
            "case_id": case_id
        })

db_mgr = DatabaseManager()

# ==============================================================================
# 3. AUTOMATIC CASE ASSIGNMENT ENGINE
# ==============================================================================
def auto_assign_case(case_data):
    """
    Distributes case to eligible agent based on Aux state, role, and current active load.
    Ensures fair end-of-day assignment balance.
    """
    users = db_mgr.get_users()
    
    # 1. Strictly consider active, logged-in agents currently in Available Aux
    eligible_agents = [
        u for u in users
        if u["status"] == "Active"
        and u.get("current_aux") == "Available"
        and u["role"] in ["AGENT", "ADMIN/AGENT"]
    ]
    
    # Fallback to any active agent if none in Available Aux
    if not eligible_agents:
        eligible_agents = [
            u for u in users
            if u["status"] == "Active" and u["role"] in ["AGENT", "ADMIN/AGENT"]
        ]

    if not eligible_agents:
        return None

    # Sort primarily by least active cases, secondarily by least assigned today
    eligible_agents.sort(key=lambda x: (x.get("active_cases", 0), x.get("today_assigned", 0)))
    assigned_agent = eligible_agents[0]
    
    # Update assignee workloads
    assigned_agent["active_cases"] = assigned_agent.get("active_cases", 0) + 1
    assigned_agent["today_assigned"] = assigned_agent.get("today_assigned", 0) + 1
    
    case_data["assigned_to"] = assigned_agent["email"]
    db_mgr.get_cases().insert(0, case_data)
    
    db_mgr.log_case_history(case_data["case_id"], "AUTO-DISPATCH", "Automatic Assignment", f"Dispatched to {assigned_agent['email']}")
    db_mgr.add_notification(
        assigned_agent["email"], 
        "New Case Assigned", 
        f"Case {case_data['case_id']} ({case_data['priority']}) auto-assigned to your queue.",
        case_id=case_data["case_id"]
    )
    return assigned_agent

# ==============================================================================
# 4. MODAL DIALOGS (9 SPECIFIED OPERATIONAL ALERTS)
# ==============================================================================
@st.dialog("🔔 1. New Case Assigned to You")
def dlg_new_case(case):
    st.markdown("A new case has been automatically assigned to your queue.")
    st.markdown(f"**Case #:** `{case['case_id']}`")
    st.markdown(f"**Subject:** {case['subject']}")
    st.markdown(f"**Priority:** <span class='badge badge-{case['priority'].lower()}'>{case['priority']}</span>", unsafe_allow_html=True)
    st.markdown(f"**Due Date:** {case['due_date']}")
    c1, c2 = st.columns(2)
    if c1.button("View Case", type="primary", use_container_width=True, key="dlg_view_case_btn"):
        st.session_state["selected_case_id"] = case['case_id']
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c2.button("OK", use_container_width=True, key="dlg_ok_case_btn"):
        st.rerun()

@st.dialog("🔄 2. Case Reassigned to You")
def dlg_case_reassigned(case, from_user):
    st.markdown("An existing case was reassigned to your queue.")
    st.markdown(f"**Case #:** `{case['case_id']}`")
    st.markdown(f"**Subject:** {case['subject']}")
    st.markdown(f"**From:** `{from_user}`")
    st.markdown(f"**Priority:** <span class='badge badge-{case['priority'].lower()}'>{case['priority']}</span>", unsafe_allow_html=True)
    st.markdown(f"**Due Date:** {case['due_date']}")
    c1, c2 = st.columns(2)
    if c1.button("View Case", type="primary", use_container_width=True, key="dlg_reas_view"):
        st.session_state["selected_case_id"] = case['case_id']
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c2.button("OK", use_container_width=True, key="dlg_reas_ok"):
        st.rerun()

@st.dialog("📬 3. Case Transfer Request Received")
def dlg_transfer_request(case, from_user):
    st.markdown(f"**Agent `{from_user}`** requested to transfer Case **`{case['case_id']}`** to you.")
    st.markdown(f"**Subject:** {case['subject']}")
    st.markdown(f"**Priority:** <span class='badge badge-{case['priority'].lower()}'>{case['priority']}</span>", unsafe_allow_html=True)
    st.caption("Reason: High queue complexity / Tier-2 escalation required.")
    c1, c2, c3 = st.columns(3)
    if c1.button("Approve", type="primary", use_container_width=True, key="dlg_appr_tr"):
        case["assigned_to"] = st.session_state["auth_user"]["email"]
        db_mgr.log_case_history(case["case_id"], st.session_state["auth_user"]["email"], "Transfer Approved", f"Accepted from {from_user}")
        st.success("Case successfully transferred.")
        st.rerun()
    if c2.button("View Case", use_container_width=True, key="dlg_vw_tr"):
        st.session_state["selected_case_id"] = case['case_id']
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c3.button("Decline", use_container_width=True, key="dlg_dec_tr"):
        st.warning("Transfer request declined.")
        st.rerun()

@st.dialog("🗓️ 4. Schedule Swap Request")
def dlg_schedule_swap_request(requester, shift_date, proposed_shift):
    st.markdown(f"**Requester:** {requester}")
    st.markdown(f"**Shift Date:** `{shift_date}`")
    st.markdown(f"**Current Schedule:** `08:00 - 17:00 (Morning Shift)`")
    st.markdown(f"**Requested Schedule:** `{proposed_shift}`")
    c1, c2, c3 = st.columns(3)
    if c1.button("Approve", type="primary", use_container_width=True, key="dlg_swap_appr"):
        st.success("Schedule swap confirmed. Team roster updated.")
        st.rerun()
    if c2.button("View Details", use_container_width=True, key="dlg_swap_vw"):
        st.session_state["active_nav"] = "Schedule"
        st.rerun()
    if c3.button("Decline", use_container_width=True, key="dlg_swap_dec"):
        st.warning("Schedule swap declined.")
        st.rerun()

@st.dialog("✅ 5. Schedule Swap Approved")
def dlg_schedule_swap_approved(shift_date, new_schedule):
    st.markdown("Your shift swap request has been approved by Operations.")
    st.markdown(f"**Date:** `{shift_date}`")
    st.markdown(f"**New Schedule:** `{new_schedule}`")
    if st.button("OK", type="primary", use_container_width=True):
        st.rerun()

@st.dialog("❌ 6. Schedule Swap Declined")
def dlg_schedule_swap_declined(shift_date, reason):
    st.error("Schedule Swap Request Declined")
    st.markdown(f"**Date:** `{shift_date}`")
    st.markdown(f"**Reason:** {reason}")
    if st.button("OK", use_container_width=True):
        st.rerun()

@st.dialog("⚠️ 7. Critical Case Alert")
def dlg_critical_case_alert(case, due_in):
    st.warning("Approaching SLA Breach Window!")
    st.markdown(f"**Case #:** `{case['case_id']}`")
    st.markdown(f"**Subject:** {case['subject']}")
    st.markdown(f"**Priority:** <span class='badge badge-critical'>Critical</span>", unsafe_allow_html=True)
    st.markdown(f"**Due In:** <strong style='color:#DE3618;'>{due_in}</strong>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if c1.button("View Case", type="primary", use_container_width=True):
        st.session_state["selected_case_id"] = case['case_id']
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c2.button("OK", use_container_width=True):
        st.rerun()

@st.dialog("🚨 8. Critical Case Past Due")
def dlg_critical_case_past_due(case):
    st.error("SLA CONTRACT BREACH OCCURRED")
    st.markdown(f"**Case #:** `{case['case_id']}`")
    st.markdown(f"**Subject:** {case['subject']}")
    st.markdown(f"**Priority:** <span class='badge badge-critical'>Critical</span>", unsafe_allow_html=True)
    st.markdown(f"**Due Date:** `{case['due_date']}`")
    st.markdown(f"**Current Status:** `{case.get('status', 'Open')}`")
    st.caption("Automated notification dispatched to Enterprise SLA Governance.")
    c1, c2 = st.columns(2)
    if c1.button("Open Incident Workspace", type="primary", use_container_width=True):
        st.session_state["selected_case_id"] = case['case_id']
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c2.button("Acknowledge", use_container_width=True):
        st.rerun()

@st.dialog("📢 9. Message from Admin")
def dlg_admin_message(sender, msg_text, timestamp):
    st.subheader(f"Broadcast from {sender}")
    st.caption(f"Dispatched: {timestamp}")
    st.info(msg_text)
    if st.button("OK", type="primary", use_container_width=True):
        st.rerun()

# ==============================================================================
# 5. AUTHENTICATION MODULE (Sign-In, Sign-Up, Forgot Password)
# ==============================================================================
def render_auth():
    col_brand, col_form = st.columns([1.15, 1], gap="large")
    
    with col_brand:
        st.markdown(
            """
            <div style="background: linear-gradient(135deg, #0B2341 0%, #001A2C 100%); padding: 3.5rem 2.5rem; border-radius: 12px; color: white; height: 100%; box-shadow: 0 4px 15px rgba(0,0,0,0.15);">
                <div style="font-size: 1.8rem; font-weight: 800; letter-spacing: -0.5px; margin-bottom: 0.25rem;">
                    <span style="color: #01A982;">Hewlett Packard</span> Enterprise
                </div>
                <h1 style="color: white; font-size: 2.8rem; margin: 0 0 1rem 0; font-weight: 800;">HPE CaseFlow</h1>
                <p style="font-size: 1.15rem; color: #A0B2C6; margin-bottom: 2.5rem;">Team Task & Case Management System</p>
                <div style="margin-bottom: 1.8rem; display: flex; align-items: flex-start; gap: 14px;">
                    <div style="background: #01A982; min-width: 38px; height: 38px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 1.1rem;">✓</div>
                    <div>
                        <div style="font-size: 1.05rem; font-weight: 700;">Manage Cases</div>
                        <div style="font-size: 0.88rem; color: #B0C4DE;">Track and resolve mission-critical tasks with real-time SLA telemetry.</div>
                    </div>
                </div>
                <div style="margin-bottom: 1.8rem; display: flex; align-items: flex-start; gap: 14px;">
                    <div style="background: #00739D; min-width: 38px; height: 38px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 1.1rem;">✓</div>
                    <div>
                        <div style="font-size: 1.05rem; font-weight: 700;">Work Together</div>
                        <div style="font-size: 0.88rem; color: #B0C4DE;">Stay aligned with live team Aux states, automated dispatch, and shift scheduling.</div>
                    </div>
                </div>
                <div style="margin-bottom: 1.8rem; display: flex; align-items: flex-start; gap: 14px;">
                    <div style="background: #763082; min-width: 38px; height: 38px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 1.1rem;">✓</div>
                    <div>
                        <div style="font-size: 1.05rem; font-weight: 700;">Drive Results</div>
                        <div style="font-size: 0.88rem; color: #B0C4DE;">Real-time insights, vendor breach analysis, and adherence reporting.</div>
                    </div>
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
                email = st.text_input("HPE Email Address", placeholder="firstname.lastname@hpe.com")
                pwd = st.text_input("Password", type="password")
                remember = st.checkbox("Remember me", value=True)
                submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)
                
                if submitted:
                    if not email or not pwd:
                        st.error("Please enter your HPE email and password.")
                    else:
                        user = db_mgr.find_user_by_email(email)
                        pwd_hash = hashlib.sha256(pwd.encode()).hexdigest()
                        if user and user.get("password_hash") == pwd_hash:
                            if user.get("status") != "Active":
                                st.error("This account is deactivated. Please contact Operations Administration.")
                            else:
                                st.session_state["authenticated"] = True
                                st.session_state["auth_user"] = user
                                st.session_state["active_nav"] = "Dashboard"
                                db_mgr.log_audit(user["email"], "Sign In", "Successful session authentication.")
                                st.rerun()
                        else:
                            st.error("Invalid credentials. Please verify your HPE email or password.")
            
            c1, c2 = st.columns(2)
            if c1.button("Create Account", use_container_width=True):
                st.session_state["auth_mode"] = "Sign Up"
                st.rerun()
            if c2.button("Forgot Password?", use_container_width=True):
                st.session_state["auth_mode"] = "Forgot Password"
                st.rerun()

            st.divider()
            st.caption("Demo Quick Login (Pre-configured Roster):")
            cq1, cq2 = st.columns(2)
            if cq1.button("👑 Admin (Arianne)", use_container_width=True):
                st.session_state["authenticated"] = True
                st.session_state["auth_user"] = db_mgr.find_user_by_email("arianne.escabillas@hpe.com")
                st.session_state["active_nav"] = "Dashboard"
                st.rerun()
            if cq2.button("👤 Agent (Maria)", use_container_width=True):
                st.session_state["authenticated"] = True
                st.session_state["auth_user"] = db_mgr.find_user_by_email("maria.santos@hpe.com")
                st.session_state["active_nav"] = "Dashboard"
                st.rerun()

        elif auth_mode == "Sign Up":
            st.markdown("## Create Your Account")
            st.caption("Sign up to access the HPE CaseFlow Roster")
            
            with st.form("signup_form"):
                fn = st.text_input("First Name")
                ln = st.text_input("Last Name")
                emp_id = st.text_input("Employee ID", placeholder="HPE-XXXX")
                email = st.text_input("HPE Email Address", placeholder="firstname.lastname@hpe.com")
                role = st.selectbox("Role", ["AGENT", "ADMIN/AGENT", "ADMIN"])
                dept = st.text_input("Department", value="Compute & GreenLake Global Ops")
                pwd = st.text_input("Password", type="password", help="Must be at least 8 characters and include letters, numbers, and a special character.")
                
                submitted = st.form_submit_button("Sign Up", type="primary", use_container_width=True)
                if submitted:
                    if not all([fn, ln, emp_id, email, pwd]):
                        st.error("All registration fields are required.")
                    elif not email.endswith("@hpe.com"):
                        st.error("Registration requires an authorized @hpe.com enterprise address.")
                    elif len(pwd) < 8 or not re.search(r"\d", pwd) or not re.search(r"[!@#$%^&*(),.?\":{}|<>]", pwd):
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
                            "aux_since": datetime.now().strftime("%I:%M %p"),
                            "active_cases": 0,
                            "today_assigned": 0,
                            "department": dept,
                            "date_created": datetime.now().strftime("%Y-%m-%d"),
                            "last_login": datetime.now().strftime("%Y-%m-%d %H:%M")
                        }
                        db_mgr.add_user(new_u)
                        st.success("Account created successfully! You can now sign in.")
                        st.session_state["auth_mode"] = "Sign In"
                        st.rerun()

            if st.button("← Back to Sign In"):
                st.session_state["auth_mode"] = "Sign In"
                st.rerun()

        elif auth_mode == "Forgot Password":
            st.markdown("## Reset Your Password")
            st.caption("Enter your registered HPE enterprise email to generate a secure reset link.")
            reset_email = st.text_input("Registered HPE Email")
            if st.button("Send Reset Link", type="primary", use_container_width=True):
                if reset_email and db_mgr.find_user_by_email(reset_email):
                    st.success(f"A password reset token has been dispatched to {reset_email}.")
                else:
                    st.error("Email address not found in Team Roster.")
            if st.button("← Back to Sign In"):
                st.session_state["auth_mode"] = "Sign In"
                st.rerun()

# ==============================================================================
# 6. GLOBAL HEADER COMPONENT
# ==============================================================================
def render_header(user):
    user_notifs = [n for n in st.session_state["notifications"] if n.get("user_email") == user["email"] or user["role"] == "ADMIN"]
    unread_count = len([n for n in user_notifs if not n.get("read", False)])
    
    col_brand, col_search, col_aux, col_profile = st.columns([1.6, 2.8, 1.8, 1.8], gap="medium")
    
    with col_brand:
        st.markdown(
            f"""
            <div style="display: flex; align-items: center; gap: 10px; padding-top: 4px;">
                <div style="background-color: #01A982; width: 14px; height: 34px; border-radius: 2px;"></div>
                <div>
                    <div style="font-weight: 800; font-size: 1.25rem; color: #0B2341; line-height: 1;">HPE CaseFlow</div>
                    <div style="font-size: 0.72rem; color: #616D75;">Team Task & Case Management</div>
                </div>
            </div>
            """, 
            unsafe_allow_html=True
        )

    with col_search:
        search_query = st.text_input(
            "Global Search",
            placeholder="🔍 Search cases, agents, vendors, issues, serials...",
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
            key="header_aux_selector"
        )
        if new_aux != current_aux:
            db_mgr.update_user_aux(user["email"], new_aux)
            user["current_aux"] = new_aux
            st.rerun()

    with col_profile:
        bell_icon = f"🔔 ({unread_count})" if unread_count > 0 else "🔔"
        btn_label = f"{bell_icon} {user['first_name']} ({user['role']}) ▾"
        popover = st.popover(btn_label, use_container_width=True)
        with popover:
            st.markdown(f"### {user['first_name']} {user['last_name']}")
            st.caption(f"ID: {user['employee_id']} | {user['email']}")
            st.markdown(f"**Department:** {user.get('department', 'Global Services')}")
            st.markdown(f"**Current State:** `{user.get('current_aux', 'Available')}` (Since: {user.get('aux_since', '08:00 AM')})")
            
            st.divider()
            st.markdown(f"**Notifications ({unread_count} unread)**")
            if user_notifs:
                for notif in user_notifs[:4]:
                    st.markdown(f"• **{notif['title']}**: {notif['text']} *({notif['time']})*")
                if st.button("Mark All Notifications Read", key="popover_mark_read"):
                    for n in user_notifs:
                        n["read"] = True
                    st.rerun()
            else:
                st.caption("No new notifications.")
            
            st.divider()
            st.caption("Shift Schedule: Today 08:00 - 17:00")
            if st.button("Sign Out", type="primary", use_container_width=True):
                st.session_state.clear()
                st.rerun()

# ==============================================================================
# 7. SIDEBAR NAVIGATION COMPONENT
# ==============================================================================
def render_sidebar(user):
    with st.sidebar:
        st.markdown(
            """
            <div style="padding: 0.5rem 0 1rem 0; border-bottom: 1px solid #E0E6ED; margin-bottom: 1rem;">
                <span style="background: #01A982; color: white; padding: 3px 8px; border-radius: 4px; font-weight: 800; font-size: 0.85rem;">HPE</span>
                <strong style="color: #0B2341; font-size: 1.1rem; margin-left: 8px;">CASEFLOW</strong>
                <div style="font-size: 0.72rem; color: #616D75; margin-top: 3px;">Operational Command System</div>
            </div>
            """, 
            unsafe_allow_html=True
        )

        role = user.get("role", "AGENT")
        nav_options = []
        
        if role == "ADMIN":
            nav_options = ["Dashboard", "Monitoring", "Schedule", "Reports", "Settings"]
        elif role == "ADMIN/AGENT":
            view_toggle = st.radio("Active View", ["Admin View", "Agent View"], horizontal=True, key="admin_agent_view_toggle")
            st.session_state["view_mode"] = view_toggle
            if view_toggle == "Admin View":
                nav_options = ["Dashboard", "Monitoring", "Schedule", "Reports", "Settings"]
            else:
                nav_options = ["Dashboard", "Schedule", "Reports"]
        else: # AGENT
            nav_options = ["Dashboard", "Schedule", "Reports"]

        # Keep Case Details reachable when actively viewing a ticket
        if st.session_state.get("active_nav") == "Case Details":
            nav_options.append("Case Details")

        current_nav = st.session_state.get("active_nav", "Dashboard")
        if current_nav not in nav_options:
            current_nav = nav_options[0]

        for item in nav_options:
            is_active = (item == current_nav)
            icon_map = {
                "Dashboard": "📊", 
                "Monitoring": "🖥️", 
                "Schedule": "🗓️", 
                "Reports": "📈", 
                "Settings": "⚙️", 
                "Case Details": "🔍"
            }
            icon = icon_map.get(item, "▸")
            label = f"{icon}  {item}"
            btn_type = "primary" if is_active else "secondary"
            if st.button(label, key=f"nav_btn_{item}", use_container_width=True, type=btn_type):
                st.session_state["active_nav"] = item
                st.rerun()

        st.markdown("---")
        st.caption("System Environment")
        if db_mgr.is_connected:
            st.markdown("<span style='color: #01A982;'>●</span> **MongoDB:** Connected", unsafe_allow_html=True)
        else:
            st.markdown("<span style='color: #00739D;'>●</span> **Roster:** Local Enterprise Store", unsafe_allow_html=True)
        st.caption(f"HPE CaseFlow v1.0.0 • 2026")

# ==============================================================================
# 8. DASHBOARD VIEWS (Admin, Admin/Agent, & Agent)
# ==============================================================================
def render_dashboard(user):
    is_admin = (user["role"] == "ADMIN") or (user["role"] == "ADMIN/AGENT" and st.session_state.get("view_mode") != "Agent View")
    
    # Top Greetings
    if is_admin:
        st.markdown(f"## Dashboard")
        st.caption(f"Welcome back, {user['first_name']}! Here's what's happening with your team today.")
    else:
        st.markdown(f"## My Dashboard")
        st.caption(f"Good day, {user['first_name']}! 👋 Here are your active assigned cases and SLA deadlines.")
    
    # Metrics Computation
    all_cases = db_mgr.get_cases()
    user_cases = [c for c in all_cases if c.get("assigned_to", "").lower() == user["email"].lower()]
    target_cases = all_cases if is_admin else user_cases
    
    active_count = len([c for c in target_cases if c.get("status") not in ["Resolved", "Closed"]])
    critical_count = len([c for c in target_cases if c.get("priority") == "Critical" and c.get("status") != "Closed"])
    due_soon_count = len([c for c in target_cases if c.get("status") in ["Open", "In Progress", "Pending Vendor", "On Hold"]])
    on_track_count = max(0, active_count - critical_count)

    # 4 Enterprise KPI Cards
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(
            f"""
            <div class="metric-card info">
                <div style="font-size: 0.8rem; color: #616D75; font-weight: 700;">ACTIVE CASES</div>
                <div style="font-size: 2.2rem; font-weight: 800; color: #0B2341;">{active_count}</div>
                <div style="font-size: 0.75rem; color: #01A982;">↑ 4% from last shift</div>
            </div>
            """, 
            unsafe_allow_html=True
        )
    with m2:
        st.markdown(
            f"""
            <div class="metric-card critical">
                <div style="font-size: 0.8rem; color: #616D75; font-weight: 700;">CRITICAL PRIORITY</div>
                <div style="font-size: 2.2rem; font-weight: 800; color: #DE3618;">{critical_count}</div>
                <div style="font-size: 0.75rem; color: #DE3618;">Requires Immediate Action</div>
            </div>
            """, 
            unsafe_allow_html=True
        )
    with m3:
        st.markdown(
            f"""
            <div class="metric-card warning">
                <div style="font-size: 0.8rem; color: #616D75; font-weight: 700;">DUE IN < 2 HOURS</div>
                <div style="font-size: 2.2rem; font-weight: 800; color: #FFAA15;">{due_soon_count}</div>
                <div style="font-size: 0.75rem; color: #FFAA15;">SLA Breach Risk Window</div>
            </div>
            """, 
            unsafe_allow_html=True
        )
    with m4:
        st.markdown(
            f"""
            <div class="metric-card">
                <div style="font-size: 0.8rem; color: #616D75; font-weight: 700;">ON TRACK / HEALTHY</div>
                <div style="font-size: 2.2rem; font-weight: 800; color: #01A982;">{on_track_count}</div>
                <div style="font-size: 0.75rem; color: #01A982;">SLA Compliance: 96.8%</div>
            </div>
            """, 
            unsafe_allow_html=True
        )

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
    
    col_main, col_rail = st.columns([2.7, 1.1], gap="medium")
    
    with col_main:
        table_title = "Active Cases" if is_admin else "My Active Assigned Queue"
        st.subheader(table_title)
        
        # Filter Bar
        f1, f2, f3, f4 = st.columns([1.5, 1, 1, 0.5])
        with f1:
            q_search = st.text_input("Filter cases", placeholder="Search by subject, account, or case #...", label_visibility="collapsed")
        with f2:
            prio_filter = st.selectbox("Priority", ["All Priorities", "Critical", "High", "Medium", "Low"], label_visibility="collapsed")
        with f3:
            status_filter = st.selectbox("Status", ["All Statuses", "Open", "In Progress", "Pending Vendor", "Pending Internal", "On Hold", "Resolved"], label_visibility="collapsed")
        with f4:
            if st.button("Reset", use_container_width=True):
                st.rerun()

        # Filtering Logic
        filtered = target_cases
        if q_search:
            filtered = [c for c in filtered if q_search.lower() in c["subject"].lower() or q_search.lower() in c.get("account", "").lower() or q_search.lower() in c["case_id"].lower()]
        if prio_filter != "All Priorities":
            filtered = [c for c in filtered if c["priority"] == prio_filter]
        if status_filter != "All Statuses":
            filtered = [c for c in filtered if c["status"] == status_filter]

        if not filtered:
            st.info("No cases matching the selected filter criteria.")
        else:
            for case in filtered:
                with st.container():
                    status_slug = case.get('status', 'Open').lower().replace(' ', '')
                    st.markdown(
                        f"""
                        <div class="hpe-card" style="margin-bottom: 0.75rem;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                                <div>
                                    <strong style="color: #00739D; font-size: 1.05rem;">{case['case_id']}</strong>
                                    <span style="margin-left: 10px; font-weight: 700; color: #0B2341;">{case['subject']}</span>
                                </div>
                                <div>
                                    <span class="badge badge-{case['priority'].lower()}">{case['priority']}</span>
                                    <span class="badge badge-{status_slug}" style="margin-left: 5px;">{case.get('status')}</span>
                                </div>
                            </div>
                            <div style="font-size: 0.85rem; color: #616D75; display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 8px;">
                                <span>🏢 Account: <strong>{case.get('account', case.get('client', 'Global Partner'))}</strong></span>
                                <span>👤 Assigned: <strong>{case.get('assigned_to', 'Unassigned')}</strong></span>
                                <span>⏱ Due: <strong>{case.get('due_date')}</strong></span>
                                <span>⚙️ System: <strong>{case.get('related_system', 'HPE Infrastructure')}</strong></span>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                    c_btn, c_assign, _ = st.columns([1, 1.3, 2.5])
                    if c_btn.button(f"Manage Case", key=f"btn_manage_{case['case_id']}"):
                        st.session_state["selected_case_id"] = case['case_id']
                        st.session_state["active_nav"] = "Case Details"
                        st.rerun()
                    if is_admin:
                        user_emails = [u["email"] for u in db_mgr.get_users()]
                        curr_idx = user_emails.index(case["assigned_to"]) if case.get("assigned_to") in user_emails else 0
                        new_owner = c_assign.selectbox("Reassign", user_emails, index=curr_idx, key=f"reassign_{case['case_id']}", label_visibility="collapsed")
                        if new_owner != case.get("assigned_to"):
                            if c_assign.button("Confirm", key=f"conf_reas_{case['case_id']}"):
                                old_owner = case.get("assigned_to")
                                case["assigned_to"] = new_owner
                                db_mgr.log_case_history(case["case_id"], user["email"], "Reassigned", f"Reassigned from {old_owner} to {new_owner}")
                                db_mgr.add_notification(new_owner, "Case Reassigned", f"Case {case['case_id']} reassigned to you.", case_id=case['case_id'])
                                st.rerun()

    with col_rail:
        if is_admin:
            st.subheader("Agents Online")
            for ag in db_mgr.get_users():
                aux = ag.get("current_aux", "Available")
                aux_class = f"badge-{aux.lower().replace(' ', '').replace('-', '')}"
                st.markdown(
                    f"""
                    <div style="background: white; border: 1px solid #E0E6ED; border-radius: 6px; padding: 10px; margin-bottom: 8px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <strong style="color: #0B2341;">{ag['first_name']} {ag['last_name']}</strong>
                                <div style="font-size: 0.72rem; color: #616D75;">{ag['role']} • Active Cases: {ag.get('active_cases', 0)}</div>
                            </div>
                            <span class="badge {aux_class}">{aux}</span>
                        </div>
                    </div>
                    """, 
                    unsafe_allow_html=True
                )
            
            st.divider()
            st.subheader("Dispatch New Case")
            with st.form("admin_dispatch_case_form"):
                n_subj = st.text_input("Subject", placeholder="E.g., License Renewal Delay")
                n_prio = st.selectbox("Priority SLA", ["Critical", "High", "Medium", "Low"])
                n_acc = st.text_input("Account", value="Global Enterprise Core")
                
                # Fetch vendor options strictly from vendors list
                vendor_options = [v["name"] for v in st.session_state.get("vendors", [])] + ["Intel Xeon Platform Support"]
                n_vendor = st.selectbox("Vendor Component", list(dict.fromkeys(vendor_options)))
                
                n_sys = st.selectbox("Related System", ["HPE Licensing Portal", "ProLiant Gen11 Compute Core", "Alletra MP Storage", "Synergy Frame 12000", "Aruba CX Switch"])
                if st.form_submit_button("Auto-Assign & Dispatch", type="primary", use_container_width=True):
                    new_case_obj = {
                        "case_id": f"HC-2026-{uuid.uuid4().hex[:4].upper()}",
                        "subject": n_subj or "Mission Critical System Issue",
                        "priority": n_prio,
                        "status": "Open",
                        "case_type": "Hardware / Software Fault",
                        "account": n_acc,
                        "client": n_acc,
                        "related_system": n_sys,
                        "vendor": n_vendor,
                        "created_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "due_date": (datetime.now() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"),
                        "last_update": "Initial ticket intake via Operational Command.",
                        "description": "Ticket ingested and automatically routed."
                    }
                    assigned_agent = auto_assign_case(new_case_obj)
                    if assigned_agent:
                        st.success(f"Case successfully dispatched to {assigned_agent['first_name']} {assigned_agent['last_name']} ({assigned_agent['email']})!")
                    else:
                        st.warning("Case created but placed in unassigned queue (no agents currently in Available state).")
                    st.rerun()

        else: # Agent Right Rail: My Shift Overview & Alert Triggers
            st.subheader("My Shift Overview")
            st.markdown(
                """
                <div class="hpe-card">
                    <div style="font-weight: 700; color: #0B2341; margin-bottom: 6px;">Today's Shift: 08:00 - 17:00</div>
                    <div style="font-size: 0.85rem; color: #616D75; line-height: 1.7;">
                        • <strong>08:00 - 10:00</strong>: Case Work<br/>
                        • <strong>10:00 - 10:15</strong>: Morning Break<br/>
                        • <strong>10:15 - 12:00</strong>: Critical Case Work<br/>
                        • <strong>12:00 - 13:00</strong>: Lunch<br/>
                        • <strong>13:00 - 14:00</strong>: 1:1 Coaching<br/>
                        • <strong>14:00 - 17:00</strong>: Dispatch & Queue Resolution
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
            
            st.subheader("Operational Actions & Alerts")
            if st.button("Simulate Incoming Case Alert", use_container_width=True):
                sample_c = target_cases[0] if target_cases else DEFAULT_CASES[0]
                dlg_new_case(sample_c)
            if st.button("Simulate Schedule Swap Request", use_container_width=True):
                dlg_schedule_swap_request("John Dela Cruz", "2026-10-02", "10:00 - 19:00 (Mid Shift)")
            if st.button("Simulate Critical Breach Warning", use_container_width=True):
                sample_c = target_cases[0] if target_cases else DEFAULT_CASES[0]
                dlg_critical_case_past_due(sample_c)

# ==============================================================================
# 9. CASE DETAILS & WORKFLOW ENGINE
# ==============================================================================
def render_case_details(user):
    case_id = st.session_state.get("selected_case_id", "HC-2026-1044")
    case = db_mgr.get_case_by_id(case_id)
    
    if not case:
        st.error(f"Case {case_id} not found.")
        if st.button("← Return to Dashboard"):
            st.session_state["active_nav"] = "Dashboard"
            st.rerun()
        return

    # Header Bar
    c_back, c_title, c_badges = st.columns([0.6, 2.5, 1.4])
    with c_back:
        if st.button("← Back"):
            st.session_state["active_nav"] = "Dashboard"
            st.rerun()
    with c_title:
        st.markdown(f"### {case['case_id']} — {case['subject']}")
        st.caption(f"Account: {case.get('account', 'Enterprise Partner')} | Created: {case.get('created_date')}")
    with c_badges:
        st.markdown(
            f"""
            <div style="text-align: right; padding-top: 5px;">
                <span class="badge badge-{case['priority'].lower()}">{case['priority']}</span>
                <span class="badge badge-open" style="margin-left: 6px;">{case.get('status')}</span>
            </div>
            """, 
            unsafe_allow_html=True
        )

    t1, t2, t3, t4 = st.tabs(["Case Information", "Vendor Information", "Communication & Breach", "Case History"])
    
    with t1:
        c1, c2 = st.columns(2)
        with c1:
            st.text_input("Case Number", value=case["case_id"], disabled=True)
            st.text_input("Case Subject", value=case["subject"])
            st.text_input("Account / Client", value=case.get("account", case.get("client", "HPE Global Partner")))
            
            prio_opts = ["Critical", "High", "Medium", "Low"]
            prio_idx = prio_opts.index(case["priority"]) if case["priority"] in prio_opts else 0
            new_prio = st.selectbox("Priority SLA", prio_opts, index=prio_idx)
            
            stat_opts = ["Open", "In Progress", "Pending Vendor", "Pending Internal", "On Hold", "Resolved", "Closed"]
            stat_idx = stat_opts.index(case.get("status", "Open")) if case.get("status") in stat_opts else 0
            new_status = st.selectbox("Case Status", stat_opts, index=stat_idx)

        with c2:
            st.text_input("Assigned Engineer", value=case.get("assigned_to", "Unassigned"), disabled=True)
            st.text_input("SLA Target Due Date", value=case.get("due_date", "Pending"))
            st.text_input("Related System Platform", value=case.get("related_system", "HPE Infrastructure"))
            new_desc = st.text_area("Case Description & Telemetry", value=case.get("description", ""), height=100)
            
        update_remarks = st.text_input("Remarks / Activity Update Note", placeholder="Enter specific updates for case history...")
        if st.button("Save & Update Case", type="primary"):
            updates = {
                "priority": new_prio,
                "status": new_status,
                "description": new_desc
            }
            if update_remarks:
                updates["last_update"] = update_remarks
            db_mgr.update_case(case_id, updates, user["email"])
            st.success("Case details and SLA telemetry updated.")
            st.rerun()

        st.divider()
        st.markdown("#### Case Transfer & Reassignment Workflow")
        t_col1, t_col2 = st.columns([2, 1])
        target_agent = t_col1.selectbox("Transfer Case to Agent", [u["email"] for u in db_mgr.get_users() if u["email"] != user["email"]])
        if t_col2.button("Request Case Transfer", use_container_width=True):
            dlg_transfer_request(case, user["email"])

    with t2:
        st.markdown("#### Vendor Integration & Escalation Details")
        st.markdown(f"**Assigned Partner:** `{case.get('vendor', 'Intel Xeon Platform Support')}`")
        v_col1, v_col2 = st.columns(2)
        with v_col1:
            st.text_input("Vendor Contact Engineer", value="David Vance - Escalation Lead")
            st.text_input("Vendor Direct Email", value="tier3-intel-hpe-escalation@intel.com")
            if st.button("📋 Copy Vendor Email"):
                st.toast("Vendor email copied to clipboard.")
        with v_col2:
            st.text_input("Vendor Ticket Reference", value="VND-884920")
            st.text_input("Direct Phone Hotline", value="+1-800-456-7890 (Ext: 9)")
            if st.button("📋 Copy Phone Hotline"):
                st.toast("Vendor phone copied to clipboard.")

    with t3:
        st.markdown("#### Automated Breach Notification Generator")
        st.caption("Standardized SLA mitigation and contract adherence communication.")
        with st.form("breach_email_form"):
            b_to = st.text_input("Recipient", value=f"{case.get('account', 'partner').lower().replace(' ', '')}@enterprise-domain.com")
            b_subj = st.text_input("Subject", value=f"[CRITICAL SLA ADVISORY] Case {case['case_id']} — {case['subject']}")
            b_msg = st.text_area(
                "Message Body",
                value=f"Dear Partner Team,\n\nWe are actively managing Case {case['case_id']} regarding {case['subject']}. Our mission-critical engineering team is engaged directly with {case.get('vendor', 'hardware operations')} to ensure rapid resolution.\n\nNext scheduled telemetry update: 30 minutes.\n\nBest regards,\nHPE Global Operations",
                height=150
            )
            if st.form_submit_button("Transmit Breach Notice", type="primary"):
                db_mgr.log_case_history(case_id, user["email"], "Breach Notice Dispatched", f"Email transmitted to {b_to}")
                st.success(f"Breach mitigation advisory officially dispatched to {b_to}.")

    with t4:
        st.markdown("#### Case Event History Timeline")
        hist = st.session_state["case_history"].get(case_id, [
            {"timestamp": case.get("created_date", "Today"), "user": "SYSTEM", "action": "Case Intake", "description": "Ticket ingested via telemetry pipeline."}
        ])
        for event in hist:
            st.markdown(
                f"""
                <div style="border-left: 3px solid #01A982; padding-left: 14px; margin-bottom: 12px;">
                    <div style="font-weight: 700; color: #0B2341;">{event['action']} — <span style="font-weight: 400; color: #616D75;">{event['timestamp']}</span></div>
                    <div style="font-size: 0.85rem; color: #00739D;">Actor: {event['user']}</div>
                    <div style="font-size: 0.85rem; color: #333333;">{event['description']}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

# ==============================================================================
# 10. MONITORING (Admin Real-Time Agent Matrix)
# ==============================================================================
def render_monitoring(user):
    st.markdown("## Monitoring")
    st.caption("View all logged-in agents, their real-time status and activities.")
    
    users = db_mgr.get_users()
    total_logged = len(users)
    avail_count = len([u for u in users if u.get("current_aux") == "Available"])
    aux_count = len([u for u in users if u.get("current_aux") in ["Break", "Lunch", "Unscheduled Break"]])
    coaching_count = len([u for u in users if u.get("current_aux") in ["Coaching", "Meeting"]])
    notready_count = len([u for u in users if u.get("current_aux") == "Not Ready - Online"])

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Logged In", f"{total_logged} / {total_logged}")
    c2.metric("Available", f"{avail_count} ({int((avail_count/total_logged)*100)}%)")
    c3.metric("On Aux", f"{aux_count} ({int((aux_count/total_logged)*100)}%)")
    c4.metric("In Meeting/Coaching", f"{coaching_count} ({int((coaching_count/total_logged)*100)}%)")
    c5.metric("Not Ready", f"{notready_count} ({int((notready_count/total_logged)*100)}%)")
    
    st.divider()
    st.subheader("Team Roster Monitoring Grid")
    
    roster_rows = []
    for u in users:
        roster_rows.append({
            "Employee ID": u["employee_id"],
            "Agent Name": f"{u['first_name']} {u['last_name']}",
            "Role": u["role"],
            "Status": u.get("status", "Active"),
            "Current Aux": u.get("current_aux", "Available"),
            "Active Cases": u.get("active_cases", 0),
            "Assigned Today": u.get("today_assigned", 0),
            "Last Aux Change": u.get("aux_since", "08:00 AM")
        })
    st.dataframe(pd.DataFrame(roster_rows), use_container_width=True, hide_index=True)

    st.markdown("#### Agent State Inspection & Drawer")
    sel_agent_email = st.selectbox("Select Agent to Inspect", [u["email"] for u in users])
    target = db_mgr.find_user_by_email(sel_agent_email)
    if target:
        with st.container():
            st.markdown(
                f"""
                <div class="hpe-card">
                    <h4>{target['first_name']} {target['last_name']} ({target['employee_id']})</h4>
                    <div>Email: <strong>{target['email']}</strong> | Role: <strong>{target['role']}</strong></div>
                    <div>Department: {target.get('department', 'Global Services')}</div>
                    <div>Current Aux: <strong>{target.get('current_aux', 'Available')}</strong> (Since: {target.get('aux_since')})</div>
                </div>
                """,
                unsafe_allow_html=True
            )
            b1, b2 = st.columns(2)
            if b1.button("Dispatched OCC Broadcast to Agent"):
                dlg_admin_message("Operations Command", "Please prioritize all Critical priority tickets immediately.", "Just now")
            if b2.button("Force Aux State to Available"):
                db_mgr.update_user_aux(target["email"], "Available")
                st.success(f"{target['first_name']} set to Available state.")
                st.rerun()

# ==============================================================================
# 11. SCHEDULE MANAGEMENT (Admin & Agent)
# ==============================================================================
def render_schedule(user):
    is_admin = (user["role"] == "ADMIN") or (user["role"] == "ADMIN/AGENT" and st.session_state.get("view_mode") != "Agent View")
    
    st.markdown("## Schedule")
    st.caption("Manage PTO allocation, leaves, and daily shift schedules.")
    
    if is_admin:
        tab_grid, tab_pto = st.tabs(["Team Weekly Schedule Grid", "PTO & Leave Approvals"])
        
        with tab_grid:
            st.subheader("Shift Assignment Grid — Current Work Week")
            time_slots = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00"]
            grid_data = []
            for u in db_mgr.get_users():
                row = {"Agent": f"{u['first_name']} {u['last_name']}", "Role": u["role"]}
                for t in time_slots:
                    if t == "12:00":
                        row[t] = "Lunch"
                    elif t == "10:00":
                        row[t] = "Break"
                    elif t == "14:00" and u["first_name"] == "Mark":
                        row[t] = "Coaching"
                    else:
                        row[t] = "Case Work"
                grid_data.append(row)
            st.dataframe(pd.DataFrame(grid_data), use_container_width=True, hide_index=True)

            col1, col2 = st.columns(2)
            if col1.button("Auto-Plot Next Week Schedule", type="primary"):
                st.success("Fair-distribution scheduling algorithm executed successfully.")
            if col2.button("Export Schedule to CSV"):
                st.toast("Schedule exported successfully.")

        with tab_pto:
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
                if c_app.button("Approve", key=f"app_{r['req_id']}"):
                    r["status"] = "Approved"
                    db_mgr.log_audit(user["email"], "Leave Approval", f"Approved {r['type']} for {r['name']}")
                    st.rerun()
                if c_dec.button("Decline", key=f"dec_{r['req_id']}"):
                    r["status"] = "Declined"
                    st.rerun()

    else: # Agent Personal Schedule
        st.subheader("My Weekly Shift Schedule")
        my_schedule = {
            "Monday": "08:00 - 17:00 (Case Work & Dispatch)",
            "Tuesday": "08:00 - 17:00 (1:1 Coaching at 14:00)",
            "Wednesday": "08:00 - 17:00 (Case Work)",
            "Thursday": "08:00 - 17:00 (Storage Guild Meeting at 11:00)",
            "Friday": "08:00 - 17:00 (Queue Wrap-up)"
        }
        for day, shift in my_schedule.items():
            st.markdown(f"**{day}:** `{shift}`")
            
        st.divider()
        st.markdown("#### Leave Balances")
        b1, b2, b3 = st.columns(3)
        b1.metric("PTO Balance", "4 / 10 days")
        b2.metric("Sick Leave", "5 / 10 days")
        b3.metric("Emergency Leave", "5 / 10 days")
        
        st.divider()
        st.subheader("Submit Time-Off / Shift Swap Request")
        with st.form("pto_submit_form"):
            l_type = st.selectbox("Request Type", ["PTO", "Sick Leave", "Emergency Leave", "Schedule Swap"])
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
                st.success("Your request has been submitted to Operations Administration.")
                st.rerun()

# ==============================================================================
# 12. REPORTS & ANALYTICS (Admin & Agent)
# ==============================================================================
def render_reports(user):
    is_admin = (user["role"] == "ADMIN") or (user["role"] == "ADMIN/AGENT" and st.session_state.get("view_mode") != "Agent View")
    st.markdown("## Reports")
    st.caption("Visualize team performance, case resolution, attendance, and adherence.")
    
    p1, p2 = st.columns([1, 4])
    period = p1.selectbox("Period Filter", ["Daily", "Week-over-Week (WOW)", "Month-to-Date (MTD)", "Year-to-Date (YTD)"])
    
    cases = db_mgr.get_cases()
    df_cases = pd.DataFrame(cases)
    
    # KPI Metrics
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Total Cases Handled", len(df_cases))
    r2.metric("Resolved Cases", len(df_cases[df_cases["status"] == "Resolved"]))
    r3.metric("Breached Cases", 1)
    r4.metric("On-Time Resolution Rate", "94.2%")
    
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
        fig_prio.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=260)
        st.plotly_chart(fig_prio, use_container_width=True)

    with col_c2:
        st.subheader("Case Volume by Status")
        fig_status = px.bar(
            df_cases,
            x="status",
            color="status",
            color_discrete_sequence=["#01A982", "#00739D", "#FFAA15", "#DE3618", "#763082"]
        )
        fig_status.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=260, showlegend=False)
        st.plotly_chart(fig_status, use_container_width=True)

    if is_admin:
        st.divider()
        st.subheader("Team Resolution & Adherence Leaderboard")
        adherence_df = pd.DataFrame([
            {"Agent": "Arianne Escabillas", "Scheduled Hours": 40, "In Adherence": 38.8, "Adherence %": "97.0%", "Resolved": 14},
            {"Agent": "John Dela Cruz", "Scheduled Hours": 40, "In Adherence": 39.1, "Adherence %": "97.7%", "Resolved": 18},
            {"Agent": "Maria Santos", "Scheduled Hours": 40, "In Adherence": 38.0, "Adherence %": "95.0%", "Resolved": 22},
            {"Agent": "Mark Tan", "Scheduled Hours": 40, "In Adherence": 37.2, "Adherence %": "93.0%", "Resolved": 12},
        ])
        st.dataframe(adherence_df, use_container_width=True, hide_index=True)
    else:
        st.divider()
        st.subheader("My Individual Performance Factor")
        m1, m2, m3 = st.columns(3)
        m1.metric("Schedule Adherence", "96.4%", "+1.2%")
        m2.metric("Mean Time to Resolution (MTTR)", "3.2 Hours", "-0.4h")
        m3.metric("First-Contact Resolution", "88.5%", "+3.0%")

# ==============================================================================
# 13. SETTINGS & SYSTEM CONFIGURATION (Admin Only)
# ==============================================================================
def render_settings(user):
    st.markdown("## Settings")
    st.caption("Manage users, roles, external data synchronization, and system configuration.")
    
    t_roster, t_sources, t_audit = st.tabs(["Team Roster Management", "External Sources & Sync", "Audit Activity Trail"])
    
    with t_roster:
        st.subheader("Team Roster Administration")
        users = db_mgr.get_users()
        for idx, u in enumerate(users):
            with st.container():
                st.markdown(
                    f"""
                    <div class="hpe-card">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <strong>{u['first_name']} {u['last_name']}</strong> ({u['email']})
                                <div style="font-size: 0.8rem; color: #616D75;">ID: {u['employee_id']} | Role: <strong>{u['role']}</strong> | Status: <strong>{u['status']}</strong></div>
                            </div>
                        </div>
                    </div>
                    """, 
                    unsafe_allow_html=True
                )
                r1, r2, r3, _ = st.columns([1.2, 1, 1, 2.5])
                new_role = r1.selectbox("Role", ["AGENT", "ADMIN/AGENT", "ADMIN"], index=["AGENT", "ADMIN/AGENT", "ADMIN"].index(u["role"]), key=f"set_role_{idx}", label_visibility="collapsed")
                if new_role != u["role"]:
                    u["role"] = new_role
                    db_mgr.log_audit(user["email"], "Role Modified", f"Changed role of {u['email']} to {new_role}")
                    st.rerun()
                
                status_action = "Deactivate" if u["status"] == "Active" else "Activate"
                if r2.button(status_action, key=f"btn_stat_{idx}"):
                    u["status"] = "Deactivated" if u["status"] == "Active" else "Active"
                    db_mgr.log_audit(user["email"], "Account Status Modified", f"Toggled status of {u['email']} to {u['status']}")
                    st.rerun()

                if r3.button("Reset Pwd", key=f"btn_reset_pwd_{idx}"):
                    st.toast(f"Password reset link sent to {u['email']}")

    with t_sources:
        st.subheader("External Vendor Data Sources")
        for v in st.session_state["vendors"]:
            st.markdown(f"• **{v['name']}** — Contact: `{v['contact']}` | `{v['email']}` | Category: *{v['category']}*")
        
        st.divider()
        st.markdown("#### Automated Synchronization Schedule")
        c1, c2 = st.columns(2)
        c1.toggle("Auto-Sync Vendor Telemetry", value=True)
        c2.selectbox("Sync Frequency", ["Every 15 minutes", "Hourly", "Twice Daily (08:00 & 20:00)"])
        if st.button("Trigger Immediate Synchronous Pull", type="primary"):
            st.success("Telemetry synchronized with hardware partner databases.")

    with t_audit:
        st.subheader("Security & System Event Audit Trail")
        st.dataframe(pd.DataFrame(st.session_state["audit_logs"]), use_container_width=True, hide_index=True)

# ==============================================================================
# 14. APPLICATION ROUTER & EXECUTION
# ==============================================================================
def main():
    # Authentication Gate
    if not st.session_state.get("authenticated", False):
        render_auth()
        return

    # Authenticated Session
    current_user = st.session_state.get("auth_user")
    
    # 1. Global Enterprise Header
    render_header(current_user)
    
    # 2. Left Persistent Navigation Sidebar
    render_sidebar(current_user)
    
    # 3. Role-Based Navigation Routing
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
