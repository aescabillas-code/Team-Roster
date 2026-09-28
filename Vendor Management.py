"""
========================================================================================
HPE CaseFlow - Team Task and Case Management System
Enterprise Streamlit Single-Script Application
========================================================================================
"""

# ======================================================================================
# 1. IMPORTS
# ======================================================================================
import os
import io
import time
import uuid
import hashlib
import datetime
from datetime import date, timedelta
from typing import Dict, List, Any, Optional

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False

try:
    import pymongo
    from pymongo import MongoClient
    MONGO_AVAILABLE = True
except ImportError:
    MONGO_AVAILABLE = False

# ======================================================================================
# 2. CONFIGURATION & DESIGN CONSTANTS
# ======================================================================================
st.set_page_config(
    page_title="HPE CaseFlow",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# HPE Design Tokens
COLOR_NAVY_DARK = "#071B2B"
COLOR_NAVY_SURFACE = "#0B2239"
COLOR_NAVY_LIGHT = "#152E4A"
COLOR_TEAL = "#00D4AA"
COLOR_TEAL_DARK = "#00BFA5"
COLOR_BLUE = "#0875E1"
COLOR_RED = "#EF4444"
COLOR_ORANGE = "#F97316"
COLOR_YELLOW = "#F5B82E"
COLOR_GREEN = "#16B979"
COLOR_PURPLE = "#8B5CF6"
COLOR_BG = "#F4F7FB"
COLOR_BORDER = "#E2E8F0"
COLOR_TEXT_MAIN = "#1E293B"
COLOR_TEXT_MUTED = "#64748B"

AUX_OPTIONS = [
    "Available",
    "Admin Work",
    "Not Ready - Online",
    "Coaching",
    "Meeting",
    "Lunch",
    "Break",
    "Unscheduled Break"
]

AUX_COLORS = {
    "Available": COLOR_GREEN,
    "Admin Work": COLOR_BLUE,
    "Not Ready - Online": COLOR_RED,
    "Coaching": COLOR_PURPLE,
    "Meeting": COLOR_ORANGE,
    "Lunch": COLOR_YELLOW,
    "Break": "#94A3B8",
    "Unscheduled Break": "#EC4899"
}

PRIORITY_COLORS = {
    "Critical": COLOR_RED,
    "High": COLOR_ORANGE,
    "Medium": COLOR_YELLOW,
    "Low": COLOR_GREEN
}

STATUS_COLORS = {
    "Open": "#94A3B8",
    "In Progress": COLOR_BLUE,
    "On Hold": COLOR_YELLOW,
    "On Track": COLOR_GREEN,
    "Pending Vendor": COLOR_PURPLE,
    "Pending Internal": "#6366F1",
    "Resolved": COLOR_GREEN,
    "Closed": "#475569"
}

SCHEDULE_ACTIVITY_COLORS = {
    "Case Work": "#A7F3D0",       # Light mint
    "Admin Work": "#BAE6FD",      # Light sky blue
    "Meeting": "#DDD6FE",         # Lavender
    "Coaching": "#E9D5FF",        # Light purple
    "Lunch": "#FEF08A",           # Soft yellow
    "Break": "#FBCFE8",           # Soft pink
    "Training": "#BFDBFE",        # Soft blue
    "PTO": "#FECACA",             # Soft coral
    "Sick Leave": "#E0E7FF",      # Indigo tint
    "Emergency Leave": "#FFEDD5"  # Soft orange
}

# ======================================================================================
# 3. DATABASE CLIENT & CRASH-PROOF SEED STORE
# ======================================================================================
def get_mongo_client():
    mongo_uri = os.environ.get("MONGO_URI") or (st.secrets.get("MONGO_URI", None) if hasattr(st, "secrets") else None)
    if not mongo_uri:
        mongo_uri = "mongodb://localhost:27017/"
    try:
        if MONGO_AVAILABLE:
            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=800)
            client.admin.command('ping')
            return client
    except Exception:
        return None
    return None

class DatabaseManager:
    """Enterprise Data Layer with MongoDB fallback."""
    def __init__(self):
        self.client = get_mongo_client()
        self.is_connected = self.client is not None
        if self.is_connected:
            self.db = self.client["TeamRoster"]
            self.collection = self.db["Team Roster Collection"]
        else:
            if "mock_db" not in st.session_state:
                st.session_state.mock_db = []
                self._seed_reference_data()

    def _seed_reference_data(self):
        now = datetime.datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        def_pass = self.hash_password("Hpe@12345")

        # 1. Validation Dropdowns
        self.insert_one({
            "type": "Validation_Dropdown",
            "Case_Status": ["Open", "In Progress", "On Hold", "On Track", "Pending Vendor", "Pending Internal", "Resolved", "Closed"],
            "Case_Reason": ["Waiting for Vendor Response", "Waiting for Customer", "Technical Investigation", "Pending Hardware Delivery", "Documentation Needed"],
            "Closure_Type": ["Resolved - Normal", "Contract Breach", "Cancelled by Customer", "Duplicate", "Administrative Close"],
            "Contract_Breach": ["Vendor SLA Exceeded > 48h", "License Delivery Failure", "No Initial Response in 4h", "Repeated Unresolved Outage"]
        })

        # 2. Roster matching Screenshots (Images 8, 10, 11, 17)
        roster_users = [
            {
                "type": "roster_list",
                "employee_id": "HPE12345",
                "first_name": "Arianne May",
                "last_name": "Escabillas",
                "name": "Arianne Escabillas",
                "email": "arianne.escabillas@hpe.com",
                "password_hash": def_pass,
                "role": "Admin/Agent",
                "account_status": "Active",
                "department": "Operations",
                "contact_number": "0917 123 4567",
                "birthday": "1995-03-15",
                "address": "Imus City, Cavite",
                "current_aux": "Available",
                "last_aux_change": "09:28 AM",
                "login_time": "08:45 AM",
                "photo_url": "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=150&auto=format&fit=crop&q=80",
                "active_cases": 4,
                "today_assigned": 2,
                "created_at": "2025-01-15"
            },
            {
                "type": "roster_list",
                "employee_id": "HPE67890",
                "first_name": "John",
                "last_name": "Dela Cruz",
                "name": "John Dela Cruz",
                "email": "john.delacruz@hpe.com",
                "password_hash": def_pass,
                "role": "Agent",
                "account_status": "Active",
                "department": "Technical Support",
                "contact_number": "0918 234 5678",
                "birthday": "1994-06-20",
                "address": "Taguig City, Metro Manila",
                "current_aux": "Available",
                "last_aux_change": "08:45 AM",
                "login_time": "08:00 AM",
                "photo_url": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150&auto=format&fit=crop&q=80",
                "active_cases": 3,
                "today_assigned": 1,
                "created_at": "2025-01-20"
            },
            {
                "type": "roster_list",
                "employee_id": "HPE54321",
                "first_name": "Maria",
                "last_name": "Santos",
                "name": "Maria Santos",
                "email": "maria.santos@hpe.com",
                "password_hash": def_pass,
                "role": "Agent",
                "account_status": "Active",
                "department": "Operations",
                "contact_number": "0919 345 6789",
                "birthday": "1996-09-12",
                "address": "Makati City, Metro Manila",
                "current_aux": "Not Ready - Online",
                "last_aux_change": "09:12 AM",
                "login_time": "08:30 AM",
                "photo_url": "https://images.unsplash.com/photo-1580489944761-15a19d654956?w=150&auto=format&fit=crop&q=80",
                "active_cases": 4,
                "today_assigned": 3,
                "created_at": "2025-01-22"
            },
            {
                "type": "roster_list",
                "employee_id": "HPE98765",
                "first_name": "Rafael",
                "last_name": "Corpus",
                "name": "Rafael Corpus",
                "email": "rafael.corpus@hpe.com",
                "password_hash": def_pass,
                "role": "Admin",
                "account_status": "Active",
                "department": "IT Operations",
                "contact_number": "0920 456 7890",
                "birthday": "1990-11-05",
                "address": "Quezon City",
                "current_aux": "Admin Work",
                "last_aux_change": "08:00 AM",
                "login_time": "07:55 AM",
                "photo_url": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150&auto=format&fit=crop&q=80",
                "active_cases": 0,
                "today_assigned": 0,
                "created_at": "2025-01-10"
            },
            {
                "type": "roster_list",
                "employee_id": "HPE11223",
                "first_name": "Liza",
                "last_name": "Tan",
                "name": "Liza Tan",
                "email": "liza.tan@hpe.com",
                "password_hash": def_pass,
                "role": "Agent",
                "account_status": "Inactive",
                "department": "Operations",
                "contact_number": "0921 567 8901",
                "birthday": "1997-02-18",
                "address": "Pasig City",
                "current_aux": "-",
                "last_aux_change": "-",
                "login_time": "-",
                "photo_url": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&auto=format&fit=crop&q=80",
                "active_cases": 0,
                "today_assigned": 0,
                "created_at": "2025-01-18"
            }
        ]
        for u in roster_users:
            self.insert_one(u)

        # 3. Vendors matching Image 18
        vendors = [
            {"type": "vendor", "vendor_name": "Tech Solutions Inc.", "primary_contact": "Mark Reynolds", "email": "mark.reynolds@techsolutions.com", "phone": "+1 555 123 4567", "category": "Software", "status": "Active", "last_updated": f"{today_str} 09:10 AM"},
            {"type": "vendor", "vendor_name": "Global Systems Ltd.", "primary_contact": "Angela White", "email": "angela.white@globalsystems.com", "phone": "+1 555 234 5678", "category": "Hardware", "status": "Active", "last_updated": f"{today_str} 09:10 AM"},
            {"type": "vendor", "vendor_name": "CloudServe Corp.", "primary_contact": "Daniel Kim", "email": "daniel.kim@cloudserve.com", "phone": "+1 555 345 6789", "category": "Cloud Services", "status": "Active", "last_updated": f"{today_str} 09:10 AM"},
            {"type": "vendor", "vendor_name": "NetConnect", "primary_contact": "Sophia Lee", "email": "sophia.lee@netconnect.com", "phone": "+1 555 456 7890", "category": "Network", "status": "Active", "last_updated": f"{today_str} 09:10 AM"},
            {"type": "vendor", "vendor_name": "DataPro Solutions", "primary_contact": "Michael Torres", "email": "michael.torres@datapro.com", "phone": "+1 555 567 8901", "category": "Data Management", "status": "Active", "last_updated": f"{today_str} 09:10 AM"},
            {"type": "vendor", "vendor_name": "ABC Software Inc.", "primary_contact": "Michael Tan", "email": "support@abcsoftware.com", "phone": "+1 555 123 4567", "category": "Software Licensing", "status": "Active", "last_updated": f"{today_str} 08:30 AM"}
        ]
        for v in vendors:
            self.insert_one(v)

        # 4. Cases matching Image 5, 6, 8, 9
        cases = [
            {
                "type": "case",
                "case_number": "HC-2026-1044",
                "subject": "License Renewal Delay",
                "description": "Client is experiencing delay in license renewal. Vendor confirmation is still pending. Need follow up and escalation if no response by EOD.",
                "priority": "Critical",
                "assigned_to": "John Dela Cruz",
                "assignee_email": "john.delacruz@hpe.com",
                "due_date": f"{today_str} 11:00 AM",
                "created_at": f"{(now - timedelta(days=1)).strftime('%Y-%m-%d')} 03:15 PM",
                "last_update": f"{today_str} 08:45 AM",
                "hours_elapsed": 0.7,
                "status": "On Hold",
                "status_reason": "Waiting for Vendor Response",
                "case_category": "License Renewal",
                "client": "ABC Enterprise",
                "related_system": "HPE Licensing Portal",
                "vendor_name": "ABC Software Inc.",
                "closure_type": None,
                "breach_reason": None,
                "is_closed": False
            },
            {
                "type": "case",
                "case_number": "HC-2026-1045",
                "subject": "Portal Access Issue",
                "description": "Enterprise customer user cannot access the admin delegation portal.",
                "priority": "Critical",
                "assigned_to": "Maria Santos",
                "assignee_email": "maria.santos@hpe.com",
                "due_date": f"{today_str} 10:30 AM",
                "created_at": f"{today_str} 07:45 AM",
                "last_update": f"{today_str} 08:15 AM",
                "hours_elapsed": 1.2,
                "status": "In Progress",
                "status_reason": "Technical Investigation",
                "case_category": "Access Management",
                "client": "Delta Global",
                "related_system": "IAM Portal",
                "vendor_name": "Tech Solutions Inc.",
                "closure_type": None,
                "breach_reason": None,
                "is_closed": False
            },
            {
                "type": "case",
                "case_number": "HC-2026-1043",
                "subject": "Installation Error",
                "description": "Cluster node failed during microcode upgrade step 3.",
                "priority": "High",
                "assigned_to": "Kevin Ramos",
                "assignee_email": "kevin.ramos@hpe.com",
                "due_date": f"{today_str} 02:00 PM",
                "created_at": f"{today_str} 08:00 AM",
                "last_update": f"{today_str} 09:00 AM",
                "hours_elapsed": 0.5,
                "status": "In Progress",
                "status_reason": "Technical Investigation",
                "case_category": "Hardware Firmware",
                "client": "First Bank Group",
                "related_system": "Synergy OneView",
                "vendor_name": "Global Systems Ltd.",
                "closure_type": None,
                "breach_reason": None,
                "is_closed": False
            }
        ]
        for c in cases:
            self.insert_one(c)

        # 5. Case History
        self.insert_one({
            "type": "case_history",
            "case_number": "HC-2026-1044",
            "timestamp": f"{today_str} 08:45 AM",
            "user": "John Dela Cruz",
            "action": "Status changed to On Hold",
            "description": "Waiting for Vendor Response"
        })

        # 6. Schedule Data matching Image 11, 12, 13
        self.insert_one({
            "type": "schedule",
            "subtype": "pto_allocation",
            "month_year": "September 2026",
            "total_allocation": 10,
            "used": 6,
            "remaining": 4,
            "fully_allocated_dates": ["Sep 14", "Sep 24", "Sep 29"]
        })

        leave_reqs = [
            {"type": "leave_request", "name": "Juan Dela Cruz", "leave_type": "PTO", "dates": "Sep 14, 2026", "status": "Approved"},
            {"type": "leave_request", "name": "Maria Santos", "leave_type": "Sick Leave", "dates": "Sep 16, 2026", "status": "Auto-Approved"},
            {"type": "leave_request", "name": "Leo Ramirez", "leave_type": "Emergency Leave", "dates": "Sep 18, 2026", "status": "Auto-Approved"},
            {"type": "leave_request", "name": "Ana Torres", "leave_type": "PTO", "dates": "Sep 24-25, 2026", "status": "Approved"},
            {"type": "leave_request", "name": "Mark Villanueva", "leave_type": "Sick Leave", "dates": "Sep 28, 2026", "status": "Auto-Approved"}
        ]
        for lr in leave_reqs:
            self.insert_one(lr)

        # 7. Audit Activity Logs matching Image 17
        self.insert_one({"type": "account_activity", "timestamp": "Sep 28, 2026 08:32 AM", "user": "Arianne May Escabillas", "activity": "Login", "details": "Successful login"})
        self.insert_one({"type": "account_activity", "timestamp": "Sep 27, 2026 05:12 PM", "user": "Arianne May Escabillas", "activity": "Aux Change", "details": "Changed to Admin Work"})
        self.insert_one({"type": "account_activity", "timestamp": "Sep 27, 2026 01:45 PM", "user": "Arianne May Escabillas", "activity": "Case Update", "details": "Updated status for case #HC-1023"})

    def hash_password(self, password: str) -> str:
        if BCRYPT_AVAILABLE:
            return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        return hashlib.sha256(password.encode('utf-8')).hexdigest()

    def check_password(self, password: str, hashed: str) -> bool:
        if BCRYPT_AVAILABLE and hashed.startswith('$2'):
            try:
                return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
            except Exception:
                return False
        return hashlib.sha256(password.encode('utf-8')).hexdigest() == hashed

    def find_one(self, filter_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if self.is_connected:
            return self.collection.find_one(filter_dict)
        for doc in st.session_state.mock_db:
            if all(doc.get(k) == v for k, v in filter_dict.items()):
                return doc
        return None

    def find(self, filter_dict: Dict[str, Any], sort_key: Optional[str] = None, ascending: bool = True) -> List[Dict[str, Any]]:
        if self.is_connected:
            cursor = self.collection.find(filter_dict)
            if sort_key:
                cursor = cursor.sort(sort_key, pymongo.ASCENDING if ascending else pymongo.DESCENDING)
            return list(cursor)
        results = [doc for doc in st.session_state.mock_db if all(doc.get(k) == v for k, v in filter_dict.items())]
        if sort_key:
            results.sort(key=lambda x: str(x.get(sort_key, "")), reverse=not ascending)
        return results

    def insert_one(self, doc: Dict[str, Any]):
        if "_id" not in doc:
            doc["_id"] = str(uuid.uuid4())
        if self.is_connected:
            self.collection.insert_one(doc)
        else:
            st.session_state.mock_db.append(doc)
        return doc

    def update_one(self, filter_dict: Dict[str, Any], update_dict: Dict[str, Any]):
        if self.is_connected:
            self.collection.update_one(filter_dict, update_dict)
            return
        fields = update_dict.get("$set", update_dict)
        for doc in st.session_state.mock_db:
            if all(doc.get(k) == v for k, v in filter_dict.items()):
                doc.update(fields)
                break

    def log_activity(self, user: str, activity: str, details: str):
        now_str = datetime.datetime.now().strftime("%b %d, %Y %I:%M %p")
        self.insert_one({
            "type": "account_activity",
            "timestamp": now_str,
            "user": user,
            "activity": activity,
            "details": details
        })

db_mgr = DatabaseManager()

# ======================================================================================
# 4. SESSION MANAGEMENT
# ======================================================================================
def init_session():
    defaults = {
        "authenticated": True,
        "user_email": "arianne.escabillas@hpe.com",
        "current_user": None,
        "auth_mode": "signin",
        "current_page": "Dashboard",
        "admin_subview": "Admin View", # Admin View vs Agent View
        "selected_case_id": None,
        "active_modal": None,          # 'profile', 'notifications', 'demo_popups'
        "active_popup_type": None,     # Image 19 exact alert popups 1 to 9
        "popup_data": {},
        "global_search": "",
        "selected_cases": set(),
        "monitoring_selected_agent": "HPE67890",
        "report_period": "MTD",
        "settings_tab": "Team Management",
        "schedule_selected_date": "2026-09-22"
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    if st.session_state.authenticated and st.session_state.current_user is None:
        user = db_mgr.find_one({"type": "roster_list", "email": st.session_state.user_email})
        if user:
            st.session_state.current_user = user
        else:
            st.session_state.authenticated = False

init_session()

# ======================================================================================
# 5. ENTERPRISE CSS (STRICT TO UPLOADED SCREENSHOTS)
# ======================================================================================
def apply_enterprise_css():
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        
        html, body, [class*="css"] {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            color: {COLOR_TEXT_MAIN};
            background-color: {COLOR_BG};
        }}

        header[data-testid="stHeader"], footer {{
            display: none !important;
        }}
        .block-container {{
            padding-top: 1rem !important;
            padding-bottom: 2rem !important;
            padding-left: 2rem !important;
            padding-right: 2rem !important;
            max-width: 100% !important;
        }}

        /* Sidebar Styling */
        section[data-testid="stSidebar"] {{
            background-color: {COLOR_NAVY_DARK} !important;
            border-right: 1px solid #112A40;
            width: 250px !important;
        }}
        section[data-testid="stSidebar"] div.stButton > button {{
            width: 100%;
            text-align: left;
            background: transparent;
            color: #94A3B8;
            border: none;
            border-radius: 8px;
            padding: 10px 16px;
            font-size: 14px;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 12px;
            transition: all 0.15s ease-in-out;
        }}
        section[data-testid="stSidebar"] div.stButton > button:hover {{
            background: rgba(255, 255, 255, 0.06);
            color: #FFFFFF;
        }}
        .sidebar-active-btn button {{
            background: rgba(0, 212, 170, 0.12) !important;
            color: {COLOR_TEAL} !important;
            font-weight: 600 !important;
            border-left: 4px solid {COLOR_TEAL} !important;
            border-radius: 4px 8px 8px 4px !important;
        }}

        /* Cards & Metrics */
        .hpe-card {{
            background: #FFFFFF;
            border: 1px solid {COLOR_BORDER};
            border-radius: 12px;
            padding: 18px 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.03);
            margin-bottom: 16px;
        }}
        .kpi-card {{
            background: #FFFFFF;
            border: 1px solid {COLOR_BORDER};
            border-radius: 12px;
            padding: 16px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            box-shadow: 0 1px 4px rgba(0,0,0,0.03);
            height: 100%;
        }}
        .kpi-title {{
            font-size: 13px;
            color: {COLOR_TEXT_MUTED};
            font-weight: 500;
            margin-bottom: 2px;
        }}
        .kpi-val {{
            font-size: 26px;
            font-weight: 700;
            color: {COLOR_TEXT_MAIN};
            line-height: 1.1;
        }}
        .kpi-delta {{
            font-size: 11px;
            font-weight: 600;
            margin-top: 4px;
        }}

        /* Colored Badges / Pills */
        .pill {{
            display: inline-block;
            padding: 3px 10px;
            border-radius: 16px;
            font-size: 11px;
            font-weight: 600;
            text-align: center;
        }}
        .pill-critical {{ background: #FEE2E2; color: #DC2626; }}
        .pill-high {{ background: #FFEDD5; color: #EA580C; }}
        .pill-medium {{ background: #FEF3C7; color: #D97706; }}
        .pill-low {{ background: #DCFCE7; color: #16A34A; }}
        .pill-available {{ background: #DCFCE7; color: #15803D; }}
        .pill-admin {{ background: #DBEAFE; color: #1D4ED8; }}
        .pill-notready {{ background: #FEE2E2; color: #DC2626; }}
        .pill-meeting {{ background: #FFEDD5; color: #C2410C; }}
        .pill-coaching {{ background: #F3E8FF; color: #7E22CE; }}
        .pill-lunch {{ background: #FEF3C7; color: #B45309; }}
        .pill-break {{ background: #E2E8F0; color: #475569; }}
        .pill-active {{ background: #DCFCE7; color: #16A34A; }}
        .pill-inactive {{ background: #FEE2E2; color: #DC2626; }}

        /* Primary Button */
        div.stButton > button[kind="primary"] {{
            background-color: {COLOR_TEAL} !important;
            color: #071B2B !important;
            border: none !important;
            font-weight: 600 !important;
            border-radius: 6px !important;
            padding: 8px 18px !important;
        }}

        /* Center Modal Backdrop / Dialog */
        .modal-backdrop {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(7, 27, 43, 0.7);
            z-index: 999999;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .modal-box-center {{
            background: #FFFFFF;
            border-radius: 12px;
            width: 480px;
            max-width: 95%;
            padding: 24px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.3);
            border: 1px solid #CBD5E1;
            position: relative;
        }}
        </style>
        """,
        unsafe_allow_html=True
    )

apply_enterprise_css()

# ======================================================================================
# 6. AUTHENTICATION (SIGN IN & SIGN UP — IMAGE 1)
# ======================================================================================
def render_auth_page():
    col_hero, col_form = st.columns([1.1, 1], gap="large")

    with col_hero:
        st.markdown(
            f"""
            <div style="background: linear-gradient(135deg, #071B2B 0%, #0B2B47 100%);
                        border-radius: 16px; padding: 48px 36px; color: white; min-height: 580px;
                        display: flex; flex-direction: column; justify-content: space-between;
                        border: 1px solid #163E63;">
                <div>
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 24px;">
                        <div style="width: 24px; height: 12px; border: 3px solid {COLOR_TEAL};"></div>
                        <span style="font-weight: 700; font-size: 13px;">Hewlett Packard Enterprise</span>
                    </div>
                    <h1 style="font-size: 40px; font-weight: 800; margin: 0; color: white;">
                        HPE <span style="color: {COLOR_TEAL};">CaseFlow</span>
                    </h1>
                    <p style="font-size: 14px; color: #94A3B8; margin-top: 4px; margin-bottom: 36px;">
                        Team Task and Case Management System
                    </p>
                    
                    <div style="display: flex; flex-direction: column; gap: 20px;">
                        <div style="display: flex; gap: 16px; align-items: flex-start;">
                            <div style="background: rgba(0, 212, 170, 0.15); border-radius: 50%; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; font-size: 18px; color: {COLOR_TEAL};">📁</div>
                            <div>
                                <h4 style="margin: 0; font-size: 15px; font-weight: 600; color: white;">Manage Cases</h4>
                                <p style="margin: 2px 0 0 0; font-size: 12px; color: #94A3B8;">Track and resolve tasks efficiently</p>
                            </div>
                        </div>
                        <div style="display: flex; gap: 16px; align-items: flex-start;">
                            <div style="background: rgba(0, 212, 170, 0.15); border-radius: 50%; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; font-size: 18px; color: {COLOR_TEAL};">👥</div>
                            <div>
                                <h4 style="margin: 0; font-size: 15px; font-weight: 600; color: white;">Work Together</h4>
                                <p style="margin: 2px 0 0 0; font-size: 12px; color: #94A3B8;">Stay aligned with your team</p>
                            </div>
                        </div>
                        <div style="display: flex; gap: 16px; align-items: flex-start;">
                            <div style="background: rgba(0, 212, 170, 0.15); border-radius: 50%; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; font-size: 18px; color: {COLOR_TEAL};">📊</div>
                            <div>
                                <h4 style="margin: 0; font-size: 15px; font-weight: 600; color: white;">Drive Results</h4>
                                <p style="margin: 2px 0 0 0; font-size: 12px; color: #94A3B8;">Real-time insights and reporting</p>
                            </div>
                        </div>
                    </div>
                </div>
                <div style="font-size: 11px; color: #64748B; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 16px;">
                    © 2026 Hewlett Packard Enterprise Development LP
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col_form:
        if st.session_state.auth_mode == "signin":
            st.markdown(
                """
                <div style="margin-top: 20px; margin-bottom: 20px;">
                    <h2 style="font-size: 26px; font-weight: 700; color: #071B2B; margin: 0;">Welcome Back!</h2>
                    <p style="font-size: 13px; color: #64748B; margin-top: 4px;">Sign in to your HPE CaseFlow account</p>
                </div>
                """,
                unsafe_allow_html=True
            )
            email_in = st.text_input("HPE Email Address", value="arianne.escabillas@hpe.com", key="auth_email")
            pass_in = st.text_input("Password", value="Hpe@12345", type="password", key="auth_pass")

            c_rem, c_fgt = st.columns(2)
            with c_rem:
                st.checkbox("Remember me", value=True)
            with c_fgt:
                if st.button("Forgot password?", type="secondary"):
                    st.toast("Reset token dispatched to your corporate email.")

            if st.button("Sign In", type="primary", use_container_width=True):
                user = db_mgr.find_one({"type": "roster_list", "email": email_in.strip()})
                if user and db_mgr.check_password(pass_in, user.get("password_hash", "")):
                    if user.get("account_status") != "Active":
                        st.error("Account deactivated. Contact system admin.")
                    else:
                        st.session_state.authenticated = True
                        st.session_state.user_email = user["email"]
                        st.session_state.current_user = user
                        db_mgr.log_activity(user["name"], "Login", "Signed in via credentials")
                        st.rerun()
                else:
                    st.error("Invalid HPE credentials.")

            st.markdown("<div style='text-align: center; margin: 16px 0; color: #94A3B8; font-size: 12px;'>or</div>", unsafe_allow_html=True)
            if st.button("🪟 Sign in with Microsoft (HPE)", use_container_width=True):
                user = db_mgr.find_one({"type": "roster_list", "email": "arianne.escabillas@hpe.com"})
                st.session_state.authenticated = True
                st.session_state.user_email = user["email"]
                st.session_state.current_user = user
                st.rerun()

            st.markdown("<div style='text-align: center; margin-top: 20px; font-size: 13px; color: #64748B;'>Don't have an account?</div>", unsafe_allow_html=True)
            if st.button("Sign up", use_container_width=True):
                st.session_state.auth_mode = "signup"
                st.rerun()
        else:
            # SIGN UP
            st.markdown(
                """
                <div style="margin-top: 10px; margin-bottom: 16px;">
                    <h2 style="font-size: 24px; font-weight: 700; color: #071B2B; margin: 0;">Create Your Account</h2>
                    <p style="font-size: 13px; color: #64748B; margin-top: 4px;">Sign up to access HPE CaseFlow</p>
                </div>
                """,
                unsafe_allow_html=True
            )
            c1, c2 = st.columns(2)
            with c1:
                fn = st.text_input("First Name", key="su_fn")
            with c2:
                ln = st.text_input("Last Name", key="su_ln")
            eid = st.text_input("Employee ID", key="su_eid")
            em = st.text_input("HPE Email Address", key="su_em")
            pw = st.text_input("Password", type="password", key="su_pw")

            if st.button("Sign Up", type="primary", use_container_width=True):
                if not (fn and ln and eid and em and pw):
                    st.warning("All fields are mandatory.")
                else:
                    db_mgr.insert_one({
                        "type": "roster_list",
                        "first_name": fn,
                        "last_name": ln,
                        "name": f"{fn} {ln}",
                        "employee_id": eid,
                        "email": em,
                        "password_hash": db_mgr.hash_password(pw),
                        "role": "Agent",
                        "account_status": "Active",
                        "current_aux": "Not Ready - Online",
                        "photo_url": "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150&auto=format&fit=crop&q=80",
                        "active_cases": 0,
                        "today_assigned": 0,
                        "created_at": datetime.datetime.now().strftime("%Y-%m-%d")
                    })
                    st.success("Account registered! Please sign in.")
                    st.session_state.auth_mode = "signin"
                    st.rerun()

            if st.button("Already have an account? Sign in", use_container_width=True):
                st.session_state.auth_mode = "signin"
                st.rerun()

# ======================================================================================
# 7. AUX MANAGEMENT & AUTOMATIC ASSIGNMENT
# ======================================================================================
def change_user_aux(new_aux: str):
    user = st.session_state.current_user
    if not user or user.get("current_aux") == new_aux:
        return
    now_time = datetime.datetime.now().strftime("%I:%M %p")
    db_mgr.update_one(
        {"type": "roster_list", "employee_id": user["employee_id"]},
        {"$set": {"current_aux": new_aux, "last_aux_change": now_time}}
    )
    db_mgr.insert_one({
        "type": "aux_history",
        "employee_id": user["employee_id"],
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p"),
        "previous_aux": user.get("current_aux"),
        "new_aux": new_aux
    })
    user["current_aux"] = new_aux
    user["last_aux_change"] = now_time
    st.session_state.current_user = user

def auto_assign_case(case_number: str) -> Optional[str]:
    eligible = db_mgr.find({"type": "roster_list", "account_status": "Active", "current_aux": "Available"})
    eligible = [a for a in eligible if a.get("role") in ["Agent", "Admin/Agent"]]
    if not eligible:
        return None

    # Workload score
    scores = []
    for ag in eligible:
        active = db_mgr.find({"type": "case", "assigned_to": ag["name"], "is_closed": False})
        crits = [c for c in active if c.get("priority") == "Critical"]
        score = (len(crits) * 5) + len(active) + (ag.get("today_assigned", 0) * 0.5)
        scores.append((score, ag))

    scores.sort(key=lambda x: x[0])
    selected = scores[0][1]

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
    db_mgr.update_one(
        {"type": "case", "case_number": case_number},
        {"$set": {"assigned_to": selected["name"], "assignee_email": selected["email"], "last_update": now_str}}
    )
    db_mgr.update_one(
        {"type": "roster_list", "employee_id": selected["employee_id"]},
        {"$set": {"active_cases": selected.get("active_cases", 0) + 1, "today_assigned": selected.get("today_assigned", 0) + 1}}
    )
    db_mgr.insert_one({
        "type": "case_history",
        "case_number": case_number,
        "timestamp": now_str,
        "user": "System",
        "action": "Case automatically assigned",
        "description": f"Fair distribution engine assigned to {selected['name']}."
    })
    return selected["name"]

# ======================================================================================
# 8. ALL 9 POPUP ALERTS SYSTEM (IMAGE 1000057269.png)
# ======================================================================================
def trigger_alert_popup(popup_type: int, custom_data: Optional[Dict[str, Any]] = None):
    st.session_state.active_popup_type = popup_type
    st.session_state.popup_data = custom_data or {}
    st.rerun()

def render_alert_popups():
    """Renders the exact 9 popup modals from Image 19."""
    ptype = st.session_state.active_popup_type
    data = st.session_state.popup_data
    if not ptype:
        return

    with st.expander(f"⚠️ Active Alert Popup (#{ptype})", expanded=True):
        col_x, _ = st.columns([1, 10])
        with col_x:
            if st.button("✕", key="close_alert_popup_top"):
                st.session_state.active_popup_type = None
                st.rerun()

        # 1. NEW CASE ASSIGNED
        if ptype == 1:
            st.markdown(
                f"""
                <div style="text-align: center; margin-bottom: 12px;">
                    <div style="font-size: 36px; color: {COLOR_GREEN};">📄⁺</div>
                    <h3 style="margin: 0; color: #071B2B;">New Case Assigned to You</h3>
                    <p style="font-size: 12px; color: #64748B;">A new case has been automatically assigned to you.</p>
                </div>
                <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; font-size: 13px; margin-bottom: 16px;">
                    <div><strong>Case #:</strong> {data.get('case_number', 'CAS-2026-0918-0045')}</div>
                    <div><strong>Subject:</strong> {data.get('subject', 'Vendor API Access Issue')}</div>
                    <div><strong>Priority:</strong> <span class="pill pill-high">High</span></div>
                    <div><strong>Due Date:</strong> {data.get('due_date', 'Sep 18, 2026 04:00 PM')}</div>
                </div>
                """,
                unsafe_allow_html=True
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button("View Case", key="pop1_view"):
                    st.session_state.selected_case_id = data.get("case_number", "HC-2026-1044")
                    st.session_state.active_popup_type = None
                    st.rerun()
            with c2:
                if st.button("OK", type="primary", key="pop1_ok"):
                    st.session_state.active_popup_type = None
                    st.rerun()

        # 2. CASE REASSIGNED TO YOU
        elif ptype == 2:
            st.markdown(
                f"""
                <div style="text-align: center; margin-bottom: 12px;">
                    <div style="font-size: 36px; color: {COLOR_ORANGE};">👤➔</div>
                    <h3 style="margin: 0; color: #071B2B;">Case Reassigned to You</h3>
                    <p style="font-size: 12px; color: #64748B;">A case has been reassigned to you by the administrator.</p>
                </div>
                <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; font-size: 13px; margin-bottom: 16px;">
                    <div><strong>Case #:</strong> {data.get('case_number', 'CAS-2026-0918-0032')}</div>
                    <div><strong>Subject:</strong> {data.get('subject', 'License Key Renewal')}</div>
                    <div><strong>Priority:</strong> <span class="pill pill-medium">Medium</span></div>
                    <div><strong>Due Date:</strong> Sep 19, 2026 10:00 AM</div>
                    <div><strong>From:</strong> Mark Dela Cruz</div>
                </div>
                """,
                unsafe_allow_html=True
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button("View Case", key="pop2_view"):
                    st.session_state.selected_case_id = data.get("case_number", "HC-2026-1044")
                    st.session_state.active_popup_type = None
                    st.rerun()
            with c2:
                if st.button("OK", type="primary", key="pop2_ok"):
                    st.session_state.active_popup_type = None
                    st.rerun()

        # 3. TRANSFER REQUEST RECEIVED
        elif ptype == 3:
            st.markdown(
                f"""
                <div style="text-align: center; margin-bottom: 12px;">
                    <div style="font-size: 36px; color: {COLOR_PURPLE};">🔄</div>
                    <h3 style="margin: 0; color: #071B2B;">Case Transfer Request</h3>
                    <p style="font-size: 12px; color: #64748B;">John Reyes has requested to transfer a case to you.</p>
                </div>
                <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; font-size: 13px; margin-bottom: 16px;">
                    <div><strong>Case #:</strong> CAS-2026-0917-0061</div>
                    <div><strong>Subject:</strong> Portal Access Issue</div>
                    <div><strong>Priority:</strong> <span class="pill pill-medium">Medium</span></div>
                    <div><strong>Due Date:</strong> Sep 19, 2026 02:00 PM</div>
                    <div><strong>From:</strong> John Reyes</div>
                </div>
                """,
                unsafe_allow_html=True
            )
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("Decline", key="pop3_dec"):
                    st.toast("Transfer declined.")
                    st.session_state.active_popup_type = None
                    st.rerun()
            with c2:
                if st.button("View Case", key="pop3_vw"):
                    st.session_state.selected_case_id = "HC-2026-1044"
                    st.session_state.active_popup_type = None
                    st.rerun()
            with c3:
                if st.button("Approve", type="primary", key="pop3_app"):
                    st.toast("Transfer approved and case shifted to your queue.")
                    st.session_state.active_popup_type = None
                    st.rerun()

        # 4. SCHEDULE SWAP REQUEST RECEIVED
        elif ptype == 4:
            st.markdown(
                """
                <div style="text-align: center; margin-bottom: 12px;">
                    <div style="font-size: 36px; color: #0875E1;">📅</div>
                    <h3 style="margin: 0; color: #071B2B;">Schedule Swap Request</h3>
                    <p style="font-size: 12px; color: #64748B;">Amanda Santos has requested to swap schedule with you.</p>
                </div>
                <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; font-size: 13px; margin-bottom: 16px;">
                    <div><strong>Date:</strong> Sep 22, 2026 (Tuesday)</div>
                    <div><strong>Your Current Schedule:</strong> Morning Shift (8:00 AM – 5:00 PM)</div>
                    <div><strong>Requester's Schedule:</strong> Afternoon Shift (12:00 PM – 9:00 PM)</div>
                </div>
                """,
                unsafe_allow_html=True
            )
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("Decline", key="pop4_dec"):
                    trigger_alert_popup(6)
            with c2:
                if st.button("View Details", key="pop4_det"):
                    st.session_state.current_page = "Schedule"
                    st.session_state.active_popup_type = None
                    st.rerun()
            with c3:
                if st.button("Approve", type="primary", key="pop4_app"):
                    trigger_alert_popup(5)

        # 5. SCHEDULE SWAP APPROVED
        elif ptype == 5:
            st.markdown(
                f"""
                <div style="text-align: center; margin-bottom: 12px;">
                    <div style="font-size: 36px; color: {COLOR_GREEN};">✅</div>
                    <h3 style="margin: 0; color: #071B2B;">Schedule Swap Approved</h3>
                    <p style="font-size: 12px; color: #64748B;">Your schedule swap request with Amanda Santos has been approved.</p>
                </div>
                <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; font-size: 13px; margin-bottom: 16px;">
                    <div><strong>Date:</strong> Sep 22, 2026 (Tuesday)</div>
                    <div><strong>Your New Schedule:</strong> Afternoon Shift (12:00 PM – 9:00 PM)</div>
                </div>
                """,
                unsafe_allow_html=True
            )
            if st.button("OK", type="primary", use_container_width=True, key="pop5_ok"):
                st.session_state.active_popup_type = None
                st.rerun()

        # 6. SCHEDULE SWAP DECLINED
        elif ptype == 6:
            st.markdown(
                f"""
                <div style="text-align: center; margin-bottom: 12px;">
                    <div style="font-size: 36px; color: {COLOR_RED};">❌</div>
                    <h3 style="margin: 0; color: #071B2B;">Schedule Swap Declined</h3>
                    <p style="font-size: 12px; color: #64748B;">Amanda Santos has declined your schedule swap request.</p>
                </div>
                <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; font-size: 13px; margin-bottom: 16px;">
                    <div><strong>Date:</strong> Sep 22, 2026 (Tuesday)</div>
                    <div><strong>Reason:</strong> Schedule conflict</div>
                </div>
                """,
                unsafe_allow_html=True
            )
            if st.button("OK", type="primary", use_container_width=True, key="pop6_ok"):
                st.session_state.active_popup_type = None
                st.rerun()

        # 7. CRITICAL CASE ALERT (NEARING DUE DATE)
        elif ptype == 7:
            st.markdown(
                f"""
                <div style="text-align: center; margin-bottom: 12px;">
                    <div style="font-size: 36px; color: {COLOR_RED};">⚠️</div>
                    <h3 style="margin: 0; color: #071B2B;">Critical Case Alert</h3>
                    <p style="font-size: 12px; color: #64748B;">A case is nearing its due date and is still not resolved or closed.</p>
                </div>
                <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; font-size: 13px; margin-bottom: 16px;">
                    <div><strong>Case #:</strong> CAS-2026-0918-0008</div>
                    <div><strong>Subject:</strong> Vendor Delivery Delay</div>
                    <div><strong>Priority:</strong> <span class="pill pill-critical">Critical</span></div>
                    <div><strong>Due In:</strong> <strong style="color: {COLOR_RED};">30 minutes (Sep 18, 2026 03:00 PM)</strong></div>
                </div>
                """,
                unsafe_allow_html=True
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button("View Case", key="pop7_vw"):
                    st.session_state.selected_case_id = "HC-2026-1044"
                    st.session_state.active_popup_type = None
                    st.rerun()
            with c2:
                if st.button("OK", type="primary", key="pop7_ok"):
                    st.session_state.active_popup_type = None
                    st.rerun()

        # 8. CRITICAL CASE PAST DUE
        elif ptype == 8:
            st.markdown(
                f"""
                <div style="text-align: center; margin-bottom: 12px;">
                    <div style="font-size: 36px; color: {COLOR_RED};">🚨</div>
                    <h3 style="margin: 0; color: #071B2B;">Critical Case Past Due</h3>
                    <p style="font-size: 12px; color: #64748B;">This case is now past due and has not been resolved.</p>
                </div>
                <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; font-size: 13px; margin-bottom: 16px;">
                    <div><strong>Case #:</strong> CAS-2026-0917-0021</div>
                    <div><strong>Subject:</strong> Contract Renewal Issue</div>
                    <div><strong>Priority:</strong> <span class="pill pill-critical">Critical</span></div>
                    <div><strong>Due Date:</strong> Sep 17, 2026 05:00 PM</div>
                    <div><strong>Status:</strong> <span class="pill pill-notready">Still Open</span></div>
                </div>
                """,
                unsafe_allow_html=True
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button("View Case", key="pop8_vw"):
                    st.session_state.selected_case_id = "HC-2026-1044"
                    st.session_state.active_popup_type = None
                    st.rerun()
            with c2:
                if st.button("OK", type="primary", key="pop8_ok"):
                    st.session_state.active_popup_type = None
                    st.rerun()

        # 9. MESSAGE FROM ADMIN
        elif ptype == 9:
            st.markdown(
                """
                <div style="text-align: center; margin-bottom: 12px;">
                    <div style="font-size: 36px; color: #0875E1;">✉️</div>
                    <h3 style="margin: 0; color: #071B2B;">Message from Admin</h3>
                </div>
                <div style="background: #F1F5F9; border-radius: 8px; padding: 14px; font-size: 13px; line-height: 1.5; margin-bottom: 12px;">
                    Hi Team,<br><br>
                    Please prioritize all critical cases for today. Let me know if you need any assistance.<br><br>
                    Thank you!
                </div>
                <div style="font-size: 11px; color: #64748B; margin-bottom: 16px;">
                    From: Admin | Sep 18, 2026 10:30 AM
                </div>
                """,
                unsafe_allow_html=True
            )
            if st.button("OK", type="primary", use_container_width=True, key="pop9_ok"):
                st.session_state.active_popup_type = None
                st.rerun()

# ======================================================================================
# 9. TOP HEADER & SIDEBAR NAVIGATION
# ======================================================================================
def render_top_header():
    user = st.session_state.current_user
    h_col1, h_col2, h_col3 = st.columns([1.2, 2.5, 1.8])

    with h_col1:
        st.markdown(
            f"""
            <div style="display: flex; align-items: center; gap: 8px; padding: 6px 0;">
                <div style="width: 18px; height: 9px; border: 2.5px solid {COLOR_TEAL};"></div>
                <div>
                    <div style="font-size: 15px; font-weight: 700; color: #071B2B; line-height: 1.1;">HPE CaseFlow</div>
                    <div style="font-size: 10px; color: #64748B;">Team Task and Case Management System</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with h_col2:
        st.session_state.global_search = st.text_input(
            "Global Search",
            value=st.session_state.global_search,
            placeholder="Search cases, agents, vendors, or issues...",
            label_visibility="collapsed",
            key="g_search_box"
        )

    with h_col3:
        c_bell, c_prof, c_aux = st.columns([0.6, 2.0, 1.4])
        with c_bell:
            if st.button("🔔 3", key="hdr_bell_btn"):
                st.session_state.active_modal = "notifications" if st.session_state.active_modal != "notifications" else None
                st.rerun()
        with c_prof:
            if st.button(f"👤 {user.get('name')}", key="hdr_prof_btn"):
                st.session_state.active_modal = "profile" if st.session_state.active_modal != "profile" else None
                st.rerun()
        with c_aux:
            cur_aux = user.get("current_aux", "Available")
            new_aux = st.selectbox("AUX", AUX_OPTIONS, index=AUX_OPTIONS.index(cur_aux) if cur_aux in AUX_OPTIONS else 0, label_visibility="collapsed")
            if new_aux != cur_aux:
                change_user_aux(new_aux)
                st.rerun()

def render_sidebar():
    user = st.session_state.current_user
    role = user.get("role", "Agent")

    with st.sidebar:
        st.markdown(
            f"""
            <div style="padding: 10px 0 20px 0; border-bottom: 1px solid rgba(255,255,255,0.08); margin-bottom: 15px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <div style="width: 14px; height: 7px; border: 2.5px solid {COLOR_TEAL};"></div>
                    <span style="font-weight: 700; color: white; font-size: 14px;">HPE CaseFlow</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

        nav_items = [("Dashboard", "📊"), ("Monitoring", "👥"), ("Schedule", "📅"), ("Report", "📈"), ("Setting", "⚙️")]
        if role == "Agent":
            nav_items = [("Dashboard", "📊"), ("Schedule", "📅"), ("Report", "📈")]

        for p_name, icon in nav_items:
            is_active = (st.session_state.current_page == p_name)
            css_class = "sidebar-active-btn" if is_active else ""
            st.markdown(f'<div class="{css_class}">', unsafe_allow_html=True)
            if st.button(f"{icon}  {p_name}", key=f"btn_nav_{p_name}"):
                st.session_state.current_page = p_name
                st.session_state.selected_case_id = None
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("<div style='margin-top: 30px;'></div>", unsafe_allow_html=True)
        # Alert Showcase triggers to test all 9 screenshot modals
        with st.expander("🧪 Test Alert Modals (1-9)"):
            c_a1, c_a2 = st.columns(2)
            with c_a1:
                if st.button("Alert 1", key="t_a1"): trigger_alert_popup(1)
                if st.button("Alert 2", key="t_a2"): trigger_alert_popup(2)
                if st.button("Alert 3", key="t_a3"): trigger_alert_popup(3)
                if st.button("Alert 4", key="t_a4"): trigger_alert_popup(4)
                if st.button("Alert 5", key="t_a5"): trigger_alert_popup(5)
            with c_a2:
                if st.button("Alert 6", key="t_a6"): trigger_alert_popup(6)
                if st.button("Alert 7", key="t_a7"): trigger_alert_popup(7)
                if st.button("Alert 8", key="t_a8"): trigger_alert_popup(8)
                if st.button("Alert 9", key="t_a9"): trigger_alert_popup(9)

        if st.button("🚪 Sign Out", key="sb_signout"):
            db_mgr.log_activity(user["name"], "Logout", "Logged out")
            st.session_state.authenticated = False
            st.session_state.current_user = None
            st.rerun()

# ======================================================================================
# 10. CASE DETAILS & BREACH GENERATOR (IMAGES 5 & 6)
# ======================================================================================
def render_case_details_view(case_number: str):
    case = db_mgr.find_one({"type": "case", "case_number": case_number})
    if not case:
        st.error(f"Case {case_number} not found.")
        if st.button("Back"):
            st.session_state.selected_case_id = None
            st.rerun()
        return

    user = st.session_state.current_user
    is_admin = user.get("role") in ["Admin", "Admin/Agent"]
    vendor = db_mgr.find_one({"type": "vendor", "vendor_name": case.get("vendor_name", "ABC Software Inc.")}) or {}

    # Header ribbon
    c_b, c_h, c_t = st.columns([0.8, 5, 2])
    with c_b:
        if st.button("← Back", key="cd_back"):
            st.session_state.selected_case_id = None
            st.rerun()
    with c_h:
        st.markdown(
            f"""
            <div style="display: flex; align-items: center; gap: 12px;">
                <h2 style="margin: 0;">{case.get('case_number')}</h2>
                <span class="pill pill-{case.get('priority', 'low').lower()}">{case.get('priority')}</span>
                <span style="font-size: 18px; font-weight: 600;">{case.get('subject')}</span>
            </div>
            <p style="margin: 2px 0 0 0; color: #64748B; font-size: 13px;">{case.get('description')}</p>
            """,
            unsafe_allow_html=True
        )
    with c_t:
        st.markdown(
            f"""
            <div style="text-align: right; font-size: 12px; color: #64748B;">
                <div>Created: <strong>{case.get('created_at')}</strong></div>
                <div>Due Date: <strong style="color: {COLOR_RED};">{case.get('due_date')}</strong></div>
                <div>Total Elapsed: <strong>19h 45m</strong></div>
            </div>
            """,
            unsafe_allow_html=True
        )

    # Summary strip
    st.markdown(
        f"""
        <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 10px 16px; margin: 14px 0; display: flex; justify-content: space-between; font-size: 12px;">
            <div><span style="color: #64748B;">Assigned To:</span> <strong>{case.get('assigned_to')}</strong></div>
            <div><span style="color: #64748B;">Priority:</span> <strong style="color: {PRIORITY_COLORS.get(case.get('priority'))};">{case.get('priority')}</strong></div>
            <div><span style="color: #64748B;">Current Status:</span> <strong>{case.get('status')}</strong></div>
            <div><span style="color: #64748B;">Last Update:</span> <strong>{case.get('last_update')}</strong></div>
            <div><span style="color: #64748B;">Case Type:</span> <strong>{case.get('case_category', 'General')}</strong></div>
            <div><span style="color: #64748B;">Account:</span> <strong>{case.get('client', 'Enterprise')}</strong></div>
            <div><span style="color: #64748B;">Related System:</span> <strong>{case.get('related_system', 'HPE Portal')}</strong></div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # 3 Column Operations
    col1, col2, col3 = st.columns([1.2, 1.2, 1.4], gap="medium")
    with col1:
        st.markdown("#### 📋 Case Information")
        st.text_input("Case #", value=case.get("case_number"), disabled=True)
        st.text_input("Subject", value=case.get("subject"), disabled=True)
        st.text_area("Description", value=case.get("description"), height=100, disabled=True)
        st.text_input("Client", value=case.get("client", "ABC Enterprise"), disabled=True)

    with col2:
        st.markdown("#### 🏢 Vendor Information")
        st.markdown(
            f"""
            <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 14px; font-size: 13px;">
                <div style="font-size: 15px; font-weight: 700; margin-bottom: 6px;">{vendor.get('vendor_name', 'ABC Software Inc.')}</div>
                <div><strong>Primary Contact:</strong> {vendor.get('primary_contact', 'Michael Tan')}</div>
                <div><strong>Email:</strong> {vendor.get('email', 'support@abcsoftware.com')}</div>
                <div><strong>Phone:</strong> {vendor.get('phone', '+1 555 123 4567')}</div>
                <div><strong>Address:</strong> 123 Innovation Drive, San Jose, CA</div>
            </div>
            """,
            unsafe_allow_html=True
        )
        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
        c_v1, c_v2 = st.columns(2)
        with c_v1:
            if st.button("📋 Copy Email", key="cd_cpe"): st.toast("Email copied.")
        with c_v2:
            if st.button("📞 Copy Phone", key="cd_cpp"): st.toast("Phone copied.")

    with col3:
        st.markdown("#### ⏱️ Update Case")
        v_doc = db_mgr.find_one({"type": "Validation_Dropdown"}) or {}
        st_opts = v_doc.get("Case_Status", ["Open", "In Progress", "On Hold", "Resolved", "Closed"])
        new_status = st.selectbox("Case Status", st_opts, index=st_opts.index(case.get("status", "Open")) if case.get("status") in st_opts else 0)
        st_reason = st.selectbox("Status Reason", v_doc.get("Case_Reason", ["Waiting for Vendor Response"]))
        cl_type = st.selectbox("Closure Type", ["-- Select Closure Type --"] + v_doc.get("Closure_Type", ["Resolved - Normal", "Contract Breach"]))
        br_reason = None
        if cl_type == "Contract Breach":
            br_reason = st.selectbox("Breach Reason", v_doc.get("Contract_Breach", ["Vendor SLA Exceeded > 48h"]))

        rem = st.text_area("Remarks / Update", placeholder="Add notes...", height=70)
        if st.button("Update Case", type="primary", key="cd_save_btn"):
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
            upd = {"status": new_status, "status_reason": st_reason, "last_update": now_str}
            if cl_type != "-- Select Closure Type --":
                upd["closure_type"] = cl_type
                if cl_type == "Contract Breach": upd["breach_reason"] = br_reason
            db_mgr.update_one({"type": "case", "case_number": case_number}, {"$set": upd})
            db_mgr.insert_one({"type": "case_history", "case_number": case_number, "timestamp": now_str, "user": user["name"], "action": f"Status: {new_status}", "description": rem or st_reason})
            st.success("Case updated!")
            st.rerun()

    st.markdown("<hr style='margin: 18px 0; border: none; border-top: 1px solid #E2E8F0;'>", unsafe_allow_html=True)
    # Bottom Timeline & Breach notice email composer
    bt1, bt2 = st.columns([1.2, 1.8], gap="medium")
    with bt1:
        st.markdown("#### 🕒 Case History")
        hists = db_mgr.find({"type": "case_history", "case_number": case_number}, sort_key="timestamp", ascending=False)
        for h in hists:
            st.markdown(
                f"""
                <div style="border-left: 2px solid {COLOR_BLUE}; padding-left: 10px; margin-bottom: 10px;">
                    <div style="font-size: 11px; color: #64748B;">{h.get('timestamp')} • {h.get('user')}</div>
                    <div style="font-size: 12px; font-weight: 600;">{h.get('action')}</div>
                    <div style="font-size: 12px; color: #475569;">{h.get('description')}</div>
                </div>
                """,
                unsafe_allow_html=True
            )
    with bt2:
        st.markdown("#### ✉️ Automated Breach Notice Email")
        to_em = st.text_input("To", value=vendor.get("email", "support@abcsoftware.com"))
        subj_em = st.text_input("Subject", value=f"Notice of Contract Breach – {case.get('case_number')}")
        body_em = st.text_area("Body", value=f"Dear {vendor.get('vendor_name', 'Vendor')},\n\nCase {case.get('case_number')} is nearing breach due to delay. Please provide an immediate update.\n\nThank you,\n{user.get('name')}", height=100)
        if st.button("Send Email", type="primary"):
            st.success("Breach notice dispatched.")

# ======================================================================================
# 11. DASHBOARD (IMAGES 7, 8, 9)
# ======================================================================================
def render_dashboard():
    user = st.session_state.current_user
    role = user.get("role", "Agent")
    is_agent = (role == "Agent") or (role == "Admin/Agent" and st.session_state.admin_subview == "Agent View")

    col_h1, col_h2 = st.columns([3, 1.2])
    with col_h1:
        st.markdown(
            f"""
            <h1 style="font-size: 24px; font-weight: 700; margin: 0; color: #071B2B;">
                {'My Dashboard' if is_agent else 'Dashboard'}
            </h1>
            <p style="font-size: 13px; color: #64748B; margin-top: 2px;">
                Good morning, {user.get('first_name')}! Here's what's happening with your {'assigned cases' if is_agent else 'team'} today.
            </p>
            """,
            unsafe_allow_html=True
        )
    with col_h2:
        st.markdown(
            f"""
            <div style="text-align: right; font-size: 12px; color: #64748B; font-weight: 500;">
                Monday, September 28, 2026 &nbsp;•&nbsp; <strong>09:28 AM</strong>
            </div>
            """,
            unsafe_allow_html=True
        )
        if role == "Admin/Agent":
            sub = st.radio("View", ["Admin View", "Agent View"], horizontal=True, label_visibility="collapsed")
            if sub != st.session_state.admin_subview:
                st.session_state.admin_subview = sub
                st.rerun()

    # Query Cases
    q = {"type": "case"}
    if is_agent: q["assigned_to"] = user.get("name")
    active_cases = [c for c in db_mgr.find(q) if not c.get("is_closed")]
    crit_cases = [c for c in active_cases if c.get("priority") == "Critical"]

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(f'<div class="kpi-card"><div><div class="kpi-title">Active Cases</div><div class="kpi-val">{len(active_cases)}</div><div class="kpi-delta" style="color: {COLOR_GREEN};">↑ 12% from yesterday</div></div><div style="font-size: 28px; color: {COLOR_BLUE};">📁</div></div>', unsafe_allow_html=True)
    with k2:
        st.markdown(f'<div class="kpi-card"><div><div class="kpi-title">Critical</div><div class="kpi-val" style="color: {COLOR_RED};">{len(crit_cases)}</div><div class="kpi-delta" style="color: {COLOR_RED};">↑ 3 new</div></div><div style="font-size: 28px; color: {COLOR_RED};">⚠️</div></div>', unsafe_allow_html=True)
    with k3:
        st.markdown(f'<div class="kpi-card"><div><div class="kpi-title">Due Soon</div><div class="kpi-val" style="color: {COLOR_YELLOW};">28</div><div class="kpi-delta" style="color: {COLOR_YELLOW};">↑ 5 new</div></div><div style="font-size: 28px; color: {COLOR_YELLOW};">⏰</div></div>', unsafe_allow_html=True)
    with k4:
        st.markdown(f'<div class="kpi-card"><div><div class="kpi-title">On Track</div><div class="kpi-val" style="color: {COLOR_GREEN};">84</div><div class="kpi-delta" style="color: {COLOR_GREEN};">↑ 4 new</div></div><div style="font-size: 28px; color: {COLOR_GREEN};">✅</div></div>', unsafe_allow_html=True)

    st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)
    col_t, col_s = st.columns([3.3, 1.1] if not is_agent else [3.2, 1.2], gap="medium")

    with col_t:
        st.markdown(f"### {'My Cases' if is_agent else f'Active Cases ({len(active_cases)})'}")
        f_s, f_p, f_st = st.columns([2.5, 1.2, 1.2])
        with f_s: s_term = st.text_input("Search", placeholder="Search by case #, subject, assignee...", label_visibility="collapsed")
        with f_p: p_flt = st.selectbox("Priority", ["All Priority", "Critical", "High", "Medium", "Low"], label_visibility="collapsed")
        with f_st: st_flt = st.selectbox("Status", ["All Status", "Open", "In Progress", "On Hold", "Resolved"], label_visibility="collapsed")

        # Table rows
        filtered = active_cases
        if s_term:
            filtered = [c for c in filtered if s_term.lower() in c.get("case_number", "").lower() or s_term.lower() in c.get("subject", "").lower()]
        if p_flt != "All Priority": filtered = [c for c in filtered if c.get("priority") == p_flt]
        if st_flt != "All Status": filtered = [c for c in filtered if c.get("status") == st_flt]

        for c in filtered:
            c1, c2 = st.columns([7, 1])
            with c1:
                st.markdown(
                    f"""
                    <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 10px 14px; margin-bottom: 6px; display: grid; grid-template-columns: 1.2fr 2.5fr 1fr 1.5fr 1.5fr 1fr; font-size: 12px; align-items: center;">
                        <div style="font-weight: 600; color: {COLOR_BLUE};">{c.get('case_number')}</div>
                        <div style="font-weight: 500;">{c.get('subject')}</div>
                        <div><span class="pill pill-{c.get('priority', 'low').lower()}">{c.get('priority')}</span></div>
                        <div>{c.get('assigned_to')}</div>
                        <div style="color: {COLOR_RED if '11:00 AM' in str(c.get('due_date')) else '#1E293B'};">{c.get('due_date')}</div>
                        <div><span class="pill pill-admin">{c.get('status')}</span></div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            with c2:
                if st.button("Open", key=f"dash_op_{c.get('case_number')}"):
                    st.session_state.selected_case_id = c.get("case_number")
                    st.rerun()

    with col_s:
        if not is_agent:
            st.markdown("### Agents Online (12)")
            all_ag = db_mgr.find({"type": "roster_list", "account_status": "Active"})
            for a in all_ag:
                if a.get("role") in ["Agent", "Admin/Agent"]:
                    aux_dot = AUX_COLORS.get(a.get("current_aux", "Available"), "#94A3B8")
                    st.markdown(
                        f"""
                        <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 8px 12px; margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <div style="font-weight: 600; font-size: 12px;">{a.get('name')}</div>
                                <div style="font-size: 10px; color: #64748B;"><span style="color: {aux_dot};">●</span> {a.get('current_aux')}</div>
                            </div>
                            <span style="font-weight: 700; background: #F1F5F9; border-radius: 50%; width: 22px; height: 22px; display: flex; align-items: center; justify-content: center; font-size: 11px;">{a.get('active_cases', 0)}</span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
        else:
            st.markdown("### Today's Schedule")
            st.info("🕒 08:00 AM – 05:00 PM (Regular Shift)")
            st.markdown("### Alerts")
            st.markdown(
                f"""
                <div style="background: #FEF2F2; border: 1px solid #F87171; border-radius: 8px; padding: 10px; font-size: 12px;">
                    <strong style="color: {COLOR_RED};">Critical case nearing due date</strong>
                    <div style="color: #7F1D1D;">HC-2026-1044 is due in 1h 32m</div>
                </div>
                """,
                unsafe_allow_html=True
            )

# ======================================================================================
# 12. SCHEDULE & PTO MANAGEMENT (IMAGES 11, 12, 13)
# ======================================================================================
def render_schedule_page():
    user = st.session_state.current_user
    role = user.get("role", "Agent")
    is_agent = (role == "Agent") or (role == "Admin/Agent" and st.session_state.admin_subview == "Agent View")

    # Header Ribbon matching Image 11 & 13
    col_sh1, col_sh2 = st.columns([3, 2])
    with col_sh1:
        st.markdown(
            f"""
            <h1 style="font-size: 24px; font-weight: 700; margin: 0; color: #071B2B;">Schedule</h1>
            <p style="font-size: 13px; color: #64748B; margin-top: 2px;">
                {'Manage PTO allocation, leaves, and daily schedules' if not is_agent else 'View your schedule, request leaves, and manage your activities.'}
            </p>
            """,
            unsafe_allow_html=True
        )
    with col_sh2:
        c_nav1, c_nav2 = st.columns([2, 1])
        with c_nav1:
            st.radio("Range", ["Month", "Week", "Day"], horizontal=True, label_visibility="collapsed")
        with c_nav2:
            if role == "Admin/Agent":
                sub_v = st.radio("Mode", ["Admin View", "Agent View"], horizontal=True, label_visibility="collapsed", key="sched_mode_toggle")
                if sub_v != st.session_state.admin_subview:
                    st.session_state.admin_subview = sub_v
                    st.rerun()

    # Top 3 Panels (PTO Calendar, Summary, Leave Requests)
    c_p1, c_p2, c_p3 = st.columns([1.3, 1.2, 1.5], gap="medium")
    
    with c_p1:
        st.markdown("#### PTO Allocation Calendar")
        st.markdown(
            """
            <div style="display: flex; gap: 8px; font-size: 10px; color: #64748B; margin-bottom: 8px;">
                <span>◻ Available</span> <span>🟨 Partial</span> <span>🟥 Fully Allocated</span> <span>🟦 Today</span>
            </div>
            """,
            unsafe_allow_html=True
        )
        # 7-Column Mini Interactive Grid
        cal_cols = st.columns(7)
        days_header = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        for idx, d in enumerate(days_header):
            cal_cols[idx].markdown(f"<div style='text-align: center; font-size: 11px; font-weight: 600; color: #64748B;'>{d}</div>", unsafe_allow_html=True)

        # Dates representation
        dates_row = ["20", "21", "22", "23", "24", "25", "26"]
        r_cols = st.columns(7)
        for idx, day_n in enumerate(dates_row):
            bg = "#FFFFFF"
            border = "#E2E8F0"
            color = "#1E293B"
            if day_n == "22":  # Today
                bg = "#DBEAFE"
                border = COLOR_BLUE
            elif day_n in ["14", "24", "29"]: # Fully Allocated
                bg = "#FEE2E2"
                color = COLOR_RED
            elif day_n in ["7", "8", "16"]:    # Partial
                bg = "#FEF3C7"
                color = "#D97706"

            r_cols[idx].markdown(
                f"""
                <div style="background: {bg}; border: 1px solid {border}; color: {color}; border-radius: 6px; padding: 6px 0; text-align: center; font-size: 12px; font-weight: 600; margin-top: 4px;">
                    {day_n}
                </div>
                """,
                unsafe_allow_html=True
            )

    with c_p2:
        st.markdown("#### PTO Allocation Summary (Sep 2026)")
        pto_doc = db_mgr.find_one({"type": "schedule", "subtype": "pto_allocation"}) or {}
        st.markdown(
            f"""
            <div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
                <div style="text-align: center;">
                    <div style="font-size: 11px; color: #64748B;">Total Allocation</div>
                    <div style="font-size: 22px; font-weight: 700;">{pto_doc.get('total_allocation', 10)}</div>
                    <div style="font-size: 10px; color: #64748B;">days</div>
                </div>
                <div style="text-align: center;">
                    <div style="font-size: 11px; color: #64748B;">Used</div>
                    <div style="font-size: 22px; font-weight: 700; color: {COLOR_ORANGE};">{pto_doc.get('used', 6)}</div>
                    <div style="font-size: 10px; color: #64748B;">days</div>
                </div>
                <div style="text-align: center;">
                    <div style="font-size: 11px; color: #64748B;">Remaining</div>
                    <div style="font-size: 22px; font-weight: 700; color: {COLOR_GREEN};">{pto_doc.get('remaining', 4)}</div>
                    <div style="font-size: 10px; color: #64748B;">days</div>
                </div>
                <div style="text-align: center;">
                    <div style="font-size: 11px; color: #64748B;">Fully Allocated</div>
                    <div style="font-size: 22px; font-weight: 700; color: {COLOR_RED};">3</div>
                    <div style="font-size: 10px; color: #64748B;">dates</div>
                </div>
            </div>
            <div style="font-size: 12px; font-weight: 600; margin-bottom: 4px;">Fully Allocated Dates</div>
            <div style="display: flex; gap: 6px;">
                <span class="pill pill-critical">Sep 14</span>
                <span class="pill pill-critical">Sep 24</span>
                <span class="pill pill-critical">Sep 29</span>
            </div>
            """,
            unsafe_allow_html=True
        )

    with c_p3:
        st.markdown("#### Leave Requests (This Month)")
        st.markdown(
            """
            <div style="display: flex; gap: 4px; margin-bottom: 8px;">
                <span class="pill pill-admin">All (6)</span>
                <span class="pill">PTO (2)</span>
                <span class="pill">Sick Leave (2)</span>
                <span class="pill">Emergency Leave (1)</span>
            </div>
            """,
            unsafe_allow_html=True
        )
        l_reqs = db_mgr.find({"type": "leave_request"})
        for lr in l_reqs[:3]:
            st.markdown(
                f"""
                <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #F1F5F9; padding: 4px 0; font-size: 12px;">
                    <div>
                        <strong>{lr.get('name')}</strong> &nbsp; <span style="color: #64748B;">{lr.get('leave_type')}</span>
                        <div style="font-size: 10px; color: #94A3B8;">{lr.get('dates')}</div>
                    </div>
                    <span class="pill pill-available">{lr.get('status')}</span>
                </div>
                """,
                unsafe_allow_html=True
            )

    st.markdown("<hr style='margin: 16px 0; border: none; border-top: 1px solid #E2E8F0;'>", unsafe_allow_html=True)

    # Schedule Assignment Grid (8:00 AM - 5:00 PM) matching Image 11 & 13
    st.markdown("### Schedule Assignment")
    st.caption("Auto-plotted based on availability. You can edit, add activities, or adjust schedules.")

    c_gctl1, c_gctl2 = st.columns([2, 2])
    with c_gctl1:
        st.markdown("📅 **Sep 22, 2026 (Tue)**")
    with c_gctl2:
        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("⚡ Auto Plot", key="sch_auto_plot"): st.toast("Schedule automatically rebalanced.")
        with b2:
            if st.button("💾 Save Changes", key="sch_save_chg"): st.toast("Changes saved.")
        with b3:
            if st.button("📥 Export", key="sch_exp"): st.toast("Exported.")

    # 10 Hourly Slots (8 AM to 5 PM)
    hours = ["8:00 AM", "9:00 AM", "10:00 AM", "11:00 AM", "12:00 PM", "1:00 PM", "2:00 PM", "3:00 PM", "4:00 PM", "5:00 PM"]
    team_schedule = [
        {"agent": "Arianne Escabillas", "role": "Admin/Agent", "acts": ["Admin Work", "Admin Work", "Admin Work", "Admin Work", "Lunch", "Admin Work", "Admin Work", "Admin Work", "Admin Work", "Admin Work"]},
        {"agent": "Juan Dela Cruz", "role": "Agent", "acts": ["Case Work", "Case Work", "Break", "Case Work", "Case Work", "Lunch", "Case Work", "Case Work", "Case Work", "Case Work"]},
        {"agent": "Maria Santos", "role": "Agent", "acts": ["Training", "Training", "Case Work", "Case Work", "Lunch", "Lunch", "Case Work", "Case Work", "Meeting", "Meeting"]},
        {"agent": "Leo Ramirez", "role": "Agent", "acts": ["Case Work", "Case Work", "Coaching", "Coaching", "Case Work", "Lunch", "Lunch", "Case Work", "Case Work", "Case Work"]},
        {"agent": "Ana Torres", "role": "Agent", "acts": ["Case Work", "Case Work", "Case Work", "Lunch", "Lunch", "Case Work", "Case Work", "Meeting", "Case Work", "Case Work"]},
        {"agent": "Mark Villanueva", "role": "Agent", "acts": ["PTO", "PTO", "PTO", "PTO", "PTO", "PTO", "PTO", "PTO", "PTO", "PTO"]}
    ]

    h_cols = st.columns([1.5, 1.0] + [0.8]*len(hours))
    h_cols[0].markdown("**Agent**")
    h_cols[1].markdown("**Role**")
    for i, h in enumerate(hours):
        h_cols[i+2].markdown(f"<span style='font-size: 10px; font-weight: 600; color: #64748B;'>{h}</span>", unsafe_allow_html=True)

    for row in team_schedule:
        r_cols = st.columns([1.5, 1.0] + [0.8]*len(hours))
        r_cols[0].markdown(f"<div style='font-size: 12px; font-weight: 600;'>{row['agent']}</div>", unsafe_allow_html=True)
        r_cols[1].markdown(f"<div style='font-size: 11px; color: #64748B;'>{row['role']}</div>", unsafe_allow_html=True)
        for i, act in enumerate(row["acts"]):
            color = SCHEDULE_ACTIVITY_COLORS.get(act, "#E2E8F0")
            r_cols[i+2].markdown(
                f"""
                <div style="background: {color}; border-radius: 4px; padding: 4px 1px; font-size: 9px; font-weight: 600; text-align: center; color: #1E293B;">
                    {act}
                </div>
                """,
                unsafe_allow_html=True
            )

    # Activity legend
    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
    st.markdown(
        """
        <div style="display: flex; gap: 8px; flex-wrap: wrap; font-size: 11px;">
            <span style="background: #A7F3D0; padding: 2px 8px; border-radius: 4px;">● Case Work</span>
            <span style="background: #BAE6FD; padding: 2px 8px; border-radius: 4px;">● Admin Work</span>
            <span style="background: #DDD6FE; padding: 2px 8px; border-radius: 4px;">● Meeting</span>
            <span style="background: #E9D5FF; padding: 2px 8px; border-radius: 4px;">● Coaching</span>
            <span style="background: #FEF08A; padding: 2px 8px; border-radius: 4px;">● Lunch</span>
            <span style="background: #FBCFE8; padding: 2px 8px; border-radius: 4px;">● Break</span>
            <span style="background: #BFDBFE; padding: 2px 8px; border-radius: 4px;">● Training</span>
            <span style="background: #FECACA; padding: 2px 8px; border-radius: 4px;">● PTO</span>
            <span style="background: #E0E7FF; padding: 2px 8px; border-radius: 4px;">● Sick Leave</span>
            <span style="background: #FFEDD5; padding: 2px 8px; border-radius: 4px;">● Emergency Leave</span>
        </div>
        """,
        unsafe_allow_html=True
    )

# ======================================================================================
# 13. REPORTS & ADHERENCE (IMAGES 14, 15, 16)
# ======================================================================================
def render_reports_page():
    user = st.session_state.current_user
    role = user.get("role", "Agent")
    is_agent = (role == "Agent") or (role == "Admin/Agent" and st.session_state.admin_subview == "Agent View")

    col_rh1, col_rh2 = st.columns([3, 2])
    with col_rh1:
        st.markdown(
            f"""
            <h1 style="font-size: 24px; font-weight: 700; margin: 0; color: #071B2B;">Reports</h1>
            <p style="font-size: 13px; color: #64748B; margin-top: 2px;">
                {'Visualize team performance, case resolution, attendance, and adherence.' if not is_agent else 'View your performance, attendance, and adherence reports.'}
            </p>
            """,
            unsafe_allow_html=True
        )
    with col_rh2:
        c_rf1, c_rf2 = st.columns([2, 1])
        with c_rf1:
            st.radio("Range", ["Daily", "WOW", "MTD", "YTD"], horizontal=True, index=2, label_visibility="collapsed")
        with c_rf2:
            st.date_input("Filter", value=(date(2026, 9, 1), date(2026, 9, 28)), label_visibility="collapsed")

    # 4 KPI Cards matching Image 14 & 15
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(f'<div class="kpi-card"><div><div class="kpi-title">Total Cases</div><div class="kpi-val">248</div><div class="kpi-delta" style="color: {COLOR_GREEN};">↑ 12% vs previous month</div></div><div style="font-size: 28px; color: {COLOR_BLUE};">📁</div></div>', unsafe_allow_html=True)
    with k2:
        st.markdown(f'<div class="kpi-card"><div><div class="kpi-title">Resolved Cases</div><div class="kpi-val">205</div><div class="kpi-delta" style="color: {COLOR_GREEN};">↑ 15% vs previous month</div></div><div style="font-size: 28px; color: {COLOR_GREEN};">✅</div></div>', unsafe_allow_html=True)
    with k3:
        st.markdown(f'<div class="kpi-card"><div><div class="kpi-title">Breached Cases</div><div class="kpi-val" style="color: {COLOR_RED};">12</div><div class="kpi-delta" style="color: {COLOR_RED};">↓ 20% vs previous month</div></div><div style="font-size: 28px; color: {COLOR_RED};">⚠️</div></div>', unsafe_allow_html=True)
    with k4:
        st.markdown(f'<div class="kpi-card"><div><div class="kpi-title">On-Time Resolution</div><div class="kpi-val" style="color: {COLOR_BLUE};">94%</div><div class="kpi-delta" style="color: {COLOR_GREEN};">↑ 6% vs previous month</div></div><div style="font-size: 28px; color: {COLOR_BLUE};">⏱️</div></div>', unsafe_allow_html=True)

    st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)

    # Row 1 of Charts: Case Trend, Case Distribution by Priority, Case Status
    c_ch1, c_ch2, c_ch3 = st.columns([1.5, 1.2, 1.3], gap="medium")
    
    with c_ch1:
        st.markdown("#### Case Trend")
        df_trend = pd.DataFrame({
            "Day": [f"Sep {i}" for i in range(1, 29, 3)],
            "Total": [38, 48, 55, 62, 54, 58, 62, 59, 61, 58],
            "Resolved": [32, 40, 48, 52, 46, 50, 54, 51, 53, 50],
            "Breached": [2, 3, 2, 4, 1, 2, 3, 1, 2, 2]
        })
        fig1 = go.Figure()
        fig1.add_trace(go.Bar(x=df_trend["Day"], y=df_trend["Resolved"], name="Resolved", marker_color=COLOR_GREEN))
        fig1.add_trace(go.Bar(x=df_trend["Day"], y=df_trend["Breached"], name="Breached", marker_color=COLOR_RED))
        fig1.add_trace(go.Scatter(x=df_trend["Day"], y=df_trend["Total"], name="Total", mode="lines+markers", line=dict(color=COLOR_BLUE, width=2)))
        fig1.update_layout(barmode="stack", height=240, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig1, use_container_width=True)

    with c_ch2:
        st.markdown("#### Case Distribution by Priority")
        fig2 = px.pie(
            values=[38, 62, 96, 52],
            names=["Critical", "High", "Medium", "Low"],
            color=["Critical", "High", "Medium", "Low"],
            color_discrete_map={"Critical": COLOR_RED, "High": COLOR_ORANGE, "Medium": COLOR_YELLOW, "Low": COLOR_GREEN},
            hole=0.55
        )
        fig2.update_layout(height=240, margin=dict(l=10, r=10, t=10, b=10), showlegend=True)
        st.plotly_chart(fig2, use_container_width=True)

    with c_ch3:
        st.markdown("#### Case Status")
        st.markdown(
            """
            <div style="font-size: 12px; margin-bottom: 8px;">
                <div style="display: flex; justify-content: space-between;"><span>Open</span><span><strong>78</strong> (31%)</span></div>
                <div style="background: #E2E8F0; border-radius: 4px; height: 8px; margin-bottom: 8px;"><div style="background: #0875E1; width: 31%; height: 8px; border-radius: 4px;"></div></div>
                <div style="display: flex; justify-content: space-between;"><span>In Progress</span><span><strong>102</strong> (41%)</span></div>
                <div style="background: #E2E8F0; border-radius: 4px; height: 8px; margin-bottom: 8px;"><div style="background: #16B979; width: 41%; height: 8px; border-radius: 4px;"></div></div>
                <div style="display: flex; justify-content: space-between;"><span>Pending Vendor</span><span><strong>42</strong> (17%)</span></div>
                <div style="background: #E2E8F0; border-radius: 4px; height: 8px; margin-bottom: 8px;"><div style="background: #F5B82E; width: 17%; height: 8px; border-radius: 4px;"></div></div>
                <div style="display: flex; justify-content: space-between;"><span>Pending Internal</span><span><strong>14</strong> (6%)</span></div>
                <div style="background: #E2E8F0; border-radius: 4px; height: 8px;"><div style="background: #F97316; width: 6%; height: 8px; border-radius: 4px;"></div></div>
            </div>
            """,
            unsafe_allow_html=True
        )

    # Row 2 of Charts: Resolution Time, Case Resolution Rate, Breach Reason
    c_rc1, c_rc2, c_rc3 = st.columns([1.3, 1.2, 1.5], gap="medium")
    with c_rc1:
        st.markdown("#### Resolution Time (Avg - Hours)")
        fig3 = px.bar(
            x=["Critical", "High", "Medium", "Low"],
            y=[12.5, 18.3, 26.8, 34.1],
            color=["Critical", "High", "Medium", "Low"],
            color_discrete_map={"Critical": COLOR_RED, "High": COLOR_ORANGE, "Medium": COLOR_YELLOW, "Low": COLOR_GREEN}
        )
        fig3.update_layout(height=220, margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
        st.plotly_chart(fig3, use_container_width=True)

    with c_rc2:
        st.markdown("#### Case Resolution Rate")
        fig4 = px.pie(
            values=[94, 6],
            names=["On-Time", "Breached"],
            color=["On-Time", "Breached"],
            color_discrete_map={"On-Time": COLOR_GREEN, "Breached": COLOR_RED},
            hole=0.65
        )
        fig4.update_layout(height=220, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig4, use_container_width=True)

    with c_rc3:
        st.markdown("#### Breach Reason")
        st.markdown(
            """
            <div style="font-size: 12px;">
                <div style="display: flex; justify-content: space-between;"><span>Vendor No Response</span><span><strong>5</strong> (42%)</span></div>
                <div style="background: #E2E8F0; border-radius: 4px; height: 6px; margin-bottom: 8px;"><div style="background: #EF4444; width: 42%; height: 6px; border-radius: 4px;"></div></div>
                <div style="display: flex; justify-content: space-between;"><span>Late Delivery</span><span><strong>3</strong> (25%)</span></div>
                <div style="background: #E2E8F0; border-radius: 4px; height: 6px; margin-bottom: 8px;"><div style="background: #F97316; width: 25%; height: 6px; border-radius: 4px;"></div></div>
                <div style="display: flex; justify-content: space-between;"><span>Incomplete Information</span><span><strong>2</strong> (17%)</span></div>
                <div style="background: #E2E8F0; border-radius: 4px; height: 6px; margin-bottom: 8px;"><div style="background: #F5B82E; width: 17%; height: 6px; border-radius: 4px;"></div></div>
                <div style="display: flex; justify-content: space-between;"><span>Scope Change</span><span><strong>1</strong> (8%)</span></div>
                <div style="background: #E2E8F0; border-radius: 4px; height: 6px;"><div style="background: #0875E1; width: 8%; height: 6px; border-radius: 4px;"></div></div>
            </div>
            """,
            unsafe_allow_html=True
        )

# ======================================================================================
# 14. SETTINGS & EXTERNAL DATA (IMAGES 17 & 18)
# ======================================================================================
def render_settings_page():
    user = st.session_state.current_user
    if user.get("role") not in ["Admin", "Admin/Agent"]:
        st.error("Access restricted to Administrators.")
        return

    # Header matching Image 17 & 18
    col_sh1, col_sh2 = st.columns([3, 1.8])
    with col_sh1:
        st.markdown(
            """
            <h1 style="font-size: 24px; font-weight: 700; margin: 0; color: #071B2B;">Settings</h1>
            <p style="font-size: 13px; color: #64748B; margin-top: 2px;">
                Manage users, roles, external data, and system configurations
            </p>
            """,
            unsafe_allow_html=True
        )
    with col_sh2:
        c_sync1, c_sync2 = st.columns([1.5, 2])
        with c_sync1:
            if st.button("🔄 Sync All Data", type="primary"):
                st.toast("External synchronization completed.")
        with c_sync2:
            st.markdown(
                f"""
                <div style="font-size: 11px; color: #64748B; padding-top: 6px;">
                    <span style="color: {COLOR_GREEN};">●</span> Last Synced<br><strong>Sep 28, 2026 09:25 AM</strong>
                </div>
                """,
                unsafe_allow_html=True
            )

    tab_team, tab_ext, tab_sys = st.tabs(["👥 Team Management", "🗄️ External Sources", "⚙️ System Configuration"])

    # TAB 1: TEAM MANAGEMENT (IMAGE 17)
    with tab_team:
        st.markdown("### Team Roster")
        c_flt1, c_flt2, c_btn1, c_btn2 = st.columns([2.5, 1.5, 1.2, 1.0])
        with c_flt1:
            st.text_input("Search", placeholder="Search by name, employee ID or email...", label_visibility="collapsed")
        with c_flt2:
            st.selectbox("Filter Role", ["All Roles", "Admin", "Admin/Agent", "Agent"], label_visibility="collapsed")
        with c_btn1:
            if st.button("➕ Add User"): st.toast("Add User Modal opened.")
        with c_btn2:
            if st.button("📥 Export"): st.toast("Roster exported.")

        # Roster Table
        roster_data = db_mgr.find({"type": "roster_list"})
        st.markdown(
            """
            <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px 8px 0 0; padding: 10px 14px; display: grid; grid-template-columns: 0.5fr 2fr 1.2fr 2fr 1.2fr 1fr 1.2fr 1.2fr; font-size: 12px; font-weight: 600; color: #64748B;">
                <div>#</div><div>Name</div><div>Employee ID</div><div>Email</div><div>Role</div><div>Status</div><div>Current Aux</div><div>Date Created</div>
            </div>
            """,
            unsafe_allow_html=True
        )
        for idx, u in enumerate(roster_data):
            aux_cls = "pill-available" if u.get("current_aux") == "Available" else "pill-admin"
            st.markdown(
                f"""
                <div style="background: white; border: 1px solid #F1F5F9; padding: 10px 14px; display: grid; grid-template-columns: 0.5fr 2fr 1.2fr 2fr 1.2fr 1fr 1.2fr 1.2fr; font-size: 12px; align-items: center;">
                    <div>{idx + 1}</div>
                    <div style="font-weight: 600;">{u.get('name')}</div>
                    <div>{u.get('employee_id')}</div>
                    <div>{u.get('email')}</div>
                    <div><span class="pill pill-admin">{u.get('role')}</span></div>
                    <div><span class="pill pill-{'active' if u.get('account_status') == 'Active' else 'inactive'}">{u.get('account_status')}</span></div>
                    <div><span class="pill {aux_cls}">{u.get('current_aux')}</span></div>
                    <div>{u.get('created_at')}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        st.markdown("<div style='margin-top: 24px;'></div>", unsafe_allow_html=True)
        # Bottom 3 Cards: Edit User Information, Change User Role, Account Actions (Image 17)
        c_ed1, c_ed2, c_ed3 = st.columns([1.4, 1.3, 1.3], gap="medium")

        with c_ed1:
            st.markdown("#### Edit User Information")
            st.text_input("First Name", value="Arianne May")
            st.text_input("Last Name", value="Escabillas")
            st.text_input("Employee ID", value="HPE12345", disabled=True)
            st.text_input("HPE Email", value="arianne.escabillas@hpe.com")
            st.text_input("Contact Number", value="0917 123 4567")
            st.date_input("Birthday", value=date(1995, 3, 15))
            st.text_input("Address", value="Imus City, Cavite")
            if st.button("Save Changes", type="primary"):
                st.success("User record updated.")

        with c_ed2:
            st.markdown("#### Change User Role")
            st.selectbox("Select User", ["John Dela Cruz (HPE67890)", "Maria Santos (HPE54321)"])
            st.selectbox("New Role", ["Agent", "Admin/Agent", "Admin"])
            st.markdown(
                """
                <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; font-size: 12px; margin: 12px 0;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 6px;"><span>📊 Dashboard</span><span style="color: #16B979;">✓ View only</span></div>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 6px;"><span>👥 Monitoring</span><span style="color: #EF4444;">✕ No access</span></div>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 6px;"><span>📅 Schedule</span><span style="color: #16B979;">✓ View & Submit</span></div>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 6px;"><span>📈 Report</span><span style="color: #16B979;">✓ View own data</span></div>
                    <div style="display: flex; justify-content: space-between;"><span>⚙️ Settings</span><span style="color: #EF4444;">✕ No access</span></div>
                </div>
                """,
                unsafe_allow_html=True
            )
            if st.button("Update Role", type="primary"):
                st.success("Role updated.")

        with c_ed3:
            st.markdown("#### Account Actions")
            if st.button("🔒 Reset Password", use_container_width=True):
                st.toast("Reset link sent.")
            if st.button("⛔ Deactivate Account", use_container_width=True):
                st.warning("Account deactivated.")
            if st.button("🗑️ Delete Account", use_container_width=True):
                st.error("Account deleted.")

            st.markdown("#### Recent Activity")
            acts = db_mgr.find({"type": "account_activity"})
            for a in acts[:3]:
                st.markdown(
                    f"""
                    <div style="border-bottom: 1px solid #F1F5F9; padding: 4px 0; font-size: 11px;">
                        <strong>{a.get('activity')}</strong> • {a.get('details')}
                        <div style="color: #64748B;">{a.get('timestamp')}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

    # TAB 2: EXTERNAL SOURCES & EXCEL SYNC (IMAGE 18)
    with tab_ext:
        st.markdown("### External Data Sources")
        st.caption("Manage and synchronize external data used in the system")

        col_es1, col_es2 = st.columns([2.5, 1.5], gap="large")

        with col_es1:
            # 4 Cards Grid
            c_r1a, c_r1b = st.columns(2)
            with c_r1a:
                st.markdown(
                    """
                    <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 14px; margin-bottom: 12px;">
                        <div style="font-weight: 700; font-size: 14px;">📊 Vendor Data</div>
                        <div style="font-size: 11px; color: #64748B; margin-bottom: 8px;">Excel file containing vendor directory & contacts</div>
                        <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 10px;">
                            <span class="pill pill-available">● Connected</span>
                            <span style="color: #64748B;">Last Sync: 09:25 AM</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                if st.button("Sync Now", key="sync_vendor_btn"): st.toast("Vendor data refreshed.")

            with c_r1b:
                st.markdown(
                    """
                    <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 14px; margin-bottom: 12px;">
                        <div style="font-weight: 700; font-size: 14px;">📥 Case Import</div>
                        <div style="font-size: 11px; color: #64748B; margin-bottom: 8px;">Import new cases from external backlog Excel</div>
                        <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 10px;">
                            <span class="pill pill-available">● Connected</span>
                            <span style="color: #64748B;">Last Sync: 08:15 AM</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                if st.button("Sync Now", key="sync_case_btn"): st.toast("Case backlog parsed.")

            c_r2a, c_r2b = st.columns(2)
            with c_r2a:
                st.markdown(
                    """
                    <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 14px;">
                        <div style="font-weight: 700; font-size: 14px;">🗂️ Validation Dropdown</div>
                        <div style="font-size: 11px; color: #64748B; margin-bottom: 8px;">System dropdown values (Status, Reasons, Closures)</div>
                        <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 10px;">
                            <span class="pill pill-available">● Connected</span>
                            <span style="color: #64748B;">Last Sync: 07:40 AM</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                if st.button("Refresh Data", key="refresh_val_btn"): st.toast("Dropdowns reloaded.")

            with c_r2b:
                st.markdown(
                    """
                    <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 14px;">
                        <div style="font-weight: 700; font-size: 14px;">📅 Holiday Calendar</div>
                        <div style="font-size: 11px; color: #64748B; margin-bottom: 8px;">Public holidays for schedule and adherence</div>
                        <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 10px;">
                            <span class="pill pill-available">● Connected</span>
                            <span style="color: #64748B;">Last Sync: 06:30 AM</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                if st.button("Sync Now", key="sync_hol_btn"): st.toast("Holiday calendar synced.")

        with col_es2:
            st.markdown("#### Sync Settings")
            st.toggle("Auto Sync Vendor Data", value=True)
            st.time_input("Sync Time", value=datetime.time(2, 0))
            st.toggle("Auto Sync Case Import", value=True)
            st.selectbox("Check Interval", ["15 minutes", "30 minutes", "1 hour"])
            st.toggle("Auto Sync Holiday Calendar", value=True)
            if st.button("Save Sync Settings", type="primary"):
                st.success("Sync configuration updated.")

        st.markdown("<div style='margin-top: 24px;'></div>", unsafe_allow_html=True)
        # Data Preview Table matching Image 18
        st.markdown("#### Data Preview")
        v_list = db_mgr.find({"type": "vendor"})
        df_v = pd.DataFrame(v_list)[["vendor_name", "primary_contact", "email", "phone", "category", "status", "last_updated"]]
        st.dataframe(df_v, use_container_width=True, hide_index=True)

    with tab_sys:
        st.markdown("### System Configuration")
        st.text_input("MongoDB Connection URI", value="mongodb://localhost:27017/", type="password")
        st.text_input("Default SMTP Host", value="smtp.hpe.com")
        st.number_input("Session Timeout (Minutes)", value=60)
        if st.button("Save System Configuration", type="primary"):
            st.success("Configuration preserved.")

# ======================================================================================
# 15. MONITORING VIEW (IMAGE 10)
# ======================================================================================
def render_monitoring_page():
    user = st.session_state.current_user
    if user.get("role") not in ["Admin", "Admin/Agent"]:
        st.error("Access restricted.")
        return

    st.markdown(
        """
        <h1 style="font-size: 24px; font-weight: 700; margin: 0; color: #071B2B;">Monitoring</h1>
        <p style="font-size: 13px; color: #64748B; margin-top: 2px;">View all logged in agents, their real-time status and activities.</p>
        """,
        unsafe_allow_html=True
    )

    all_ag = db_mgr.find({"type": "roster_list", "account_status": "Active"})
    avail_cnt = len([a for a in all_ag if a.get("current_aux") == "Available"])

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1: st.metric("Total Logged In", f"{len(all_ag)} / 15")
    with m2: st.metric("Available", f"{avail_cnt}", "50%")
    with m3: st.metric("On Aux", "5", "42%")
    with m4: st.metric("In Meeting/Coaching", "1", "8%")
    with m5: st.metric("Not Ready", "0", "0%")

    st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)
    col_l, col_r = st.columns([2.5, 1.5], gap="large")

    with col_l:
        st.markdown("### Agent Live Status")
        for ag in all_ag:
            c1, c2 = st.columns([4, 1])
            with c1:
                aux_dot = AUX_COLORS.get(ag.get("current_aux", "Available"), "#94A3B8")
                st.markdown(
                    f"""
                    <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 10px 14px; margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center;">
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <img src="{ag.get('photo_url')}" style="width: 34px; height: 34px; border-radius: 50%;">
                            <div>
                                <div style="font-weight: 600; font-size: 13px;">{ag.get('name')} <span style="font-size: 11px; color: #64748B;">({ag.get('employee_id')})</span></div>
                                <div style="font-size: 11px; color: #64748B;">Role: {ag.get('role')}</div>
                            </div>
                        </div>
                        <div style="text-align: right;">
                            <span class="pill pill-available"><span style="color: {aux_dot};">●</span> {ag.get('current_aux')}</span>
                            <div style="font-size: 10px; color: #64748B; margin-top: 2px;">Since {ag.get('last_aux_change', '09:00 AM')}</div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            with c2:
                if st.button("Inspect", key=f"mon_insp_{ag.get('employee_id')}"):
                    st.session_state.monitoring_selected_agent = ag.get("employee_id")
                    st.rerun()

    with col_r:
        sel_ag = db_mgr.find_one({"type": "roster_list", "employee_id": st.session_state.monitoring_selected_agent}) or all_ag[0]
        st.markdown(
            f"""
            <div style="background: white; border: 1px solid #E2E8F0; border-radius: 12px; padding: 18px;">
                <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px;">
                    <img src="{sel_ag.get('photo_url')}" style="width: 48px; height: 48px; border-radius: 50%;">
                    <div>
                        <h3 style="margin: 0; font-size: 16px;">{sel_ag.get('name')}</h3>
                        <div style="font-size: 11px; color: #64748B;">ID: {sel_ag.get('employee_id')}</div>
                        <span class="pill pill-admin">{sel_ag.get('role')}</span>
                    </div>
                </div>
                <div style="font-size: 12px; margin-bottom: 8px;"><strong>Current AUX:</strong> {sel_ag.get('current_aux')}</div>
                <div style="font-size: 12px; margin-bottom: 12px;"><strong>Active Cases:</strong> {sel_ag.get('active_cases', 0)}</div>
            </div>
            """,
            unsafe_allow_html=True
        )
        msg_in = st.text_input("Send message to agent", placeholder="Type message...", key="mon_msg_box")
        if st.button("Dispatch Admin Message", type="primary"):
            if msg_in:
                trigger_alert_popup(9, {"msg": msg_in})

# ======================================================================================
# 16. MAIN DISPATCHER
# ======================================================================================
def main():
    if not st.session_state.authenticated or st.session_state.current_user is None:
        render_auth_page()
        return

    # Shell Top Header & Left Navigation
    render_top_header()
    render_sidebar()

    # Centered Alert Popups (Exact 9 Modals from Image 19)
    if st.session_state.active_popup_type is not None:
        render_alert_popups()

    # Route Page
    if st.session_state.selected_case_id:
        render_case_details_view(st.session_state.selected_case_id)
    else:
        page = st.session_state.current_page
        if page == "Dashboard":
            render_dashboard()
        elif page == "Monitoring":
            render_monitoring_page()
        elif page == "Schedule":
            render_schedule_page()
        elif page == "Report":
            render_reports_page()
        elif page == "Setting":
            render_settings_page()

if __name__ == "__main__":
    main()
