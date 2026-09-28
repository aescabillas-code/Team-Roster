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
import math
import time
import uuid
import base64
import hashlib
import datetime
from datetime import date, timedelta
from typing import Dict, List, Any, Optional

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dateutil import parser

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
# 2. CONFIGURATION & CONSTANTS
# ======================================================================================
st.set_page_config(
    page_title="HPE CaseFlow",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# HPE Theme Color Palette (Exact match to reference screenshots)
COLOR_NAVY_DARK = "#071B2B"
COLOR_NAVY_SURFACE = "#0B2239"
COLOR_NAVY_LIGHT = "#152E4A"
COLOR_TEAL = "#00D4AA"
COLOR_TEAL_DARK = "#00BFA5"
COLOR_BLUE = "#0875E1"
COLOR_RED = "#EF4444"
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
    "Meeting": "#F97316", # Orange
    "Lunch": COLOR_YELLOW,
    "Break": "#94A3B8",  # Gray
    "Unscheduled Break": "#EC4899" # Pink
}

PRIORITY_COLORS = {
    "Critical": COLOR_RED,
    "High": "#F97316",
    "Medium": COLOR_YELLOW,
    "Low": COLOR_GREEN
}

STATUS_COLORS = {
    "Open": "#94A3B8",
    "In Progress": COLOR_BLUE,
    "On Hold": COLOR_YELLOW,
    "On Track": COLOR_GREEN,
    "Pending Vendor": "#8B5CF6",
    "Pending Internal": "#6366F1",
    "Resolved": COLOR_GREEN,
    "Closed": "#475569"
}

# ======================================================================================
# 3. DATABASE CLIENT & IN-MEMORY FALLBACK (CRASH-PROOF ARCHITECTURE)
# ======================================================================================
def get_mongo_client():
    """
    Returns a connected MongoClient or None.
    Uses environment variable MONGO_URI if present, else checks local or secrets.
    """
    mongo_uri = os.environ.get("MONGO_URI") or st.secrets.get("MONGO_URI", None) if hasattr(st, "secrets") else None
    if not mongo_uri:
        mongo_uri = "mongodb://localhost:27017/"
    try:
        if MONGO_AVAILABLE:
            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=1200)
            client.admin.command('ping')
            return client
    except Exception:
        return None
    return None

class DatabaseManager:
    """Unified data layer that connects to MongoDB or uses robust in-memory mock."""
    def __init__(self):
        self.client = get_mongo_client()
        self.is_connected = self.client is not None
        if self.is_connected:
            self.db = self.client["TeamRoster"]
            self.collection = self.db["Team Roster Collection"]
        else:
            # Fallback in-memory storage initialized in session state
            if "mock_db" not in st.session_state:
                st.session_state.mock_db = []
                self._seed_initial_data()

    def _seed_initial_data(self):
        """Seed realistic records matching all uploaded UI screenshots."""
        now = datetime.datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        
        # 1. Validation Dropdowns
        dropdown_doc = {
            "type": "Validation_Dropdown",
            "Case_Status": ["Open", "In Progress", "On Hold", "On Track", "Pending Vendor", "Pending Internal", "Resolved", "Closed"],
            "Case_Reason": ["Waiting for Vendor Response", "Waiting for Customer", "Technical Investigation", "Pending Hardware Delivery", "Documentation Needed"],
            "Closure_Type": ["Resolved - Normal", "Contract Breach", "Cancelled by Customer", "Duplicate", "Administrative Close"],
            "Contract_Breach": ["Vendor SLA Exceeded > 48h", "License Delivery Failure", "No Initial Response in 4h", "Repeated Unresolved Outage"]
        }
        st.session_state.mock_db.append(dropdown_doc)

        # 2. Team Roster (Users)
        def_pass = self.hash_password("Hpe@12345")
        users = [
            {
                "type": "roster_list",
                "employee_id": "HPE12345",
                "first_name": "Arianne",
                "last_name": "Escabillas",
                "name": "Arianne Escabillas",
                "email": "arianne.escabillas@hpe.com",
                "password_hash": def_pass,
                "role": "Admin/Agent",
                "account_status": "Active",
                "department": "Operations",
                "current_aux": "Available",
                "last_aux_change": now.strftime("%I:%M %p"),
                "login_time": "08:45 AM",
                "photo_url": "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=150&auto=format&fit=crop&q=80",
                "active_cases": 4,
                "today_assigned": 2,
                "created_at": "2026-01-15 09:00:00"
            },
            {
                "type": "roster_list",
                "employee_id": "HPE001234",
                "first_name": "Maria",
                "last_name": "Santos",
                "name": "Maria Santos",
                "email": "maria.santos@hpe.com",
                "password_hash": def_pass,
                "role": "Agent",
                "account_status": "Active",
                "department": "Operations",
                "current_aux": "Available",
                "last_aux_change": "09:12 AM",
                "login_time": "08:30 AM",
                "photo_url": "https://images.unsplash.com/photo-1580489944761-15a19d654956?w=150&auto=format&fit=crop&q=80",
                "active_cases": 4,
                "today_assigned": 3,
                "created_at": "2026-02-01 08:30:00"
            },
            {
                "type": "roster_list",
                "employee_id": "HPE001235",
                "first_name": "John",
                "last_name": "Dela Cruz",
                "name": "John Dela Cruz",
                "email": "john.delacruz@hpe.com",
                "password_hash": def_pass,
                "role": "Agent",
                "account_status": "Active",
                "department": "Technical Support",
                "current_aux": "Available",
                "last_aux_change": "08:45 AM",
                "login_time": "08:00 AM",
                "photo_url": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150&auto=format&fit=crop&q=80",
                "active_cases": 3,
                "today_assigned": 1,
                "created_at": "2026-02-01 08:30:00"
            },
            {
                "type": "roster_list",
                "employee_id": "HPE001236",
                "first_name": "Daniel",
                "last_name": "Reyes",
                "name": "Daniel Reyes",
                "email": "daniel.reyes@hpe.com",
                "password_hash": def_pass,
                "role": "Admin/Agent",
                "account_status": "Active",
                "department": "Operations",
                "current_aux": "Meeting",
                "last_aux_change": "09:00 AM",
                "login_time": "08:15 AM",
                "photo_url": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150&auto=format&fit=crop&q=80",
                "active_cases": 4,
                "today_assigned": 2,
                "created_at": "2026-01-10 09:00:00"
            },
            {
                "type": "roster_list",
                "employee_id": "HPE001237",
                "first_name": "Liza",
                "last_name": "Garcia",
                "name": "Liza Garcia",
                "email": "liza.garcia@hpe.com",
                "password_hash": def_pass,
                "role": "Agent",
                "account_status": "Active",
                "department": "Operations",
                "current_aux": "Coaching",
                "last_aux_change": "09:20 AM",
                "login_time": "08:50 AM",
                "photo_url": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&auto=format&fit=crop&q=80",
                "active_cases": 1,
                "today_assigned": 0,
                "created_at": "2026-02-10 08:30:00"
            },
            {
                "type": "roster_list",
                "employee_id": "HPE001238",
                "first_name": "Kevin",
                "last_name": "Ramos",
                "name": "Kevin Ramos",
                "email": "kevin.ramos@hpe.com",
                "password_hash": def_pass,
                "role": "Agent",
                "account_status": "Active",
                "department": "Technical Support",
                "current_aux": "Available",
                "last_aux_change": "08:55 AM",
                "login_time": "08:00 AM",
                "photo_url": "https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?w=150&auto=format&fit=crop&q=80",
                "active_cases": 2,
                "today_assigned": 1,
                "created_at": "2026-02-15 08:30:00"
            }
        ]
        st.session_state.mock_db.extend(users)

        # 3. Vendors
        vendors = [
            {
                "type": "vendor",
                "vendor_name": "ABC Software Inc.",
                "primary_contact": "Michael Tan",
                "email": "support@abcsoftware.com",
                "phone": "+1 555 123 4567",
                "alternate_contact": "Sarah Lim",
                "alternate_email": "sarah.lim@abcsoftware.com",
                "address": "123 Innovation Drive, San Jose, CA 95134",
                "category": "Software Licensing",
                "status": "Active"
            },
            {
                "type": "vendor",
                "vendor_name": "Global Cloud Net",
                "primary_contact": "Alex Rivera",
                "email": "help@globalcloud.net",
                "phone": "+1 555 987 6543",
                "alternate_contact": "David Wu",
                "alternate_email": "david.wu@globalcloud.net",
                "address": "77 Tech Boulevard, Austin, TX 78701",
                "category": "Cloud Infrastructure",
                "status": "Active"
            }
        ]
        st.session_state.mock_db.extend(vendors)

        # 4. Cases (Replicating exact screenshots items)
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
                "vendor_name": "Global Cloud Net",
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
                "vendor_name": "ABC Software Inc.",
                "closure_type": None,
                "breach_reason": None,
                "is_closed": False
            },
            {
                "type": "case",
                "case_number": "HC-2026-1042",
                "subject": "Vendor Confirmation",
                "description": "Awaiting shipment serials for replacement DIMM cards.",
                "priority": "High",
                "assigned_to": "Liza Garcia",
                "assignee_email": "liza.garcia@hpe.com",
                "due_date": f"{today_str} 04:00 PM",
                "created_at": f"{today_str} 07:30 AM",
                "last_update": f"{today_str} 08:55 AM",
                "hours_elapsed": 0.6,
                "status": "Open",
                "status_reason": "Waiting for Vendor Response",
                "case_category": "Parts Replacement",
                "client": "TechCorp Logistics",
                "related_system": "HPE Pointnext",
                "vendor_name": "Global Cloud Net",
                "closure_type": None,
                "breach_reason": None,
                "is_closed": False
            },
            {
                "type": "case",
                "case_number": "HC-2026-1037",
                "subject": "License Allocation",
                "description": "Request to rebalance 500 licenses from EMEA to APAC cluster.",
                "priority": "Medium",
                "assigned_to": "Arianne Escabillas",
                "assignee_email": "arianne.escabillas@hpe.com",
                "due_date": f"{(now + timedelta(days=2)).strftime('%Y-%m-%d')} 04:00 PM",
                "created_at": f"{(now - timedelta(days=1)).strftime('%Y-%m-%d')} 09:00 AM",
                "last_update": f"{today_str} 08:30 AM",
                "hours_elapsed": 1.8,
                "status": "On Track",
                "status_reason": "Technical Investigation",
                "case_category": "License Management",
                "client": "Summit Healthcare",
                "related_system": "HPE GreenLake",
                "vendor_name": "ABC Software Inc.",
                "closure_type": None,
                "breach_reason": None,
                "is_closed": False
            },
            {
                "type": "case",
                "case_number": "HC-2026-1021",
                "subject": "Software Licensing",
                "description": "Certificate renewal validation for single-sign on.",
                "priority": "Low",
                "assigned_to": "Arianne Escabillas",
                "assignee_email": "arianne.escabillas@hpe.com",
                "due_date": f"{(now + timedelta(days=3)).strftime('%Y-%m-%d')} 11:00 AM",
                "created_at": f"{(now - timedelta(days=2)).strftime('%Y-%m-%d')} 01:00 PM",
                "last_update": f"{today_str} 09:00 AM",
                "hours_elapsed": 1.2,
                "status": "Open",
                "status_reason": "Waiting for Customer",
                "case_category": "Certificate Authority",
                "client": "Zenith Media",
                "related_system": "HPE Security Suite",
                "vendor_name": "ABC Software Inc.",
                "closure_type": None,
                "breach_reason": None,
                "is_closed": False
            }
        ]
        st.session_state.mock_db.extend(cases)

        # 5. Case History
        case_histories = [
            {
                "type": "case_history",
                "case_number": "HC-2026-1044",
                "timestamp": f"{today_str} 08:45 AM",
                "user": "John Dela Cruz",
                "action": "Status changed to On Hold",
                "description": "Waiting for Vendor Response"
            },
            {
                "type": "case_history",
                "case_number": "HC-2026-1044",
                "timestamp": f"{today_str} 08:15 AM",
                "user": "John Dela Cruz",
                "action": "Initial contact with vendor",
                "description": "Sent follow up email to vendor. Awaiting response."
            },
            {
                "type": "case_history",
                "case_number": "HC-2026-1044",
                "timestamp": f"{(now - timedelta(days=1)).strftime('%Y-%m-%d')} 03:15 PM",
                "user": "System",
                "action": "Case created and assigned",
                "description": "Case automatically assigned to John Dela Cruz."
            }
        ]
        st.session_state.mock_db.extend(case_histories)

        # 6. Notifications
        notifications = [
            {
                "type": "notification",
                "notification_type": "CRITICAL_CASE_ALERT",
                "recipient_employee_id": "HPE12345",
                "case_id": "HC-2026-1044",
                "title": "Critical case nearing due date",
                "message": "HC-2026-1044 is due in 1h 32m.",
                "is_read": False,
                "created_at": f"{today_str} 09:20 AM"
            },
            {
                "type": "notification",
                "notification_type": "NEW_CASE_ASSIGNED",
                "recipient_employee_id": "HPE12345",
                "case_id": "HC-2026-1038",
                "title": "New case assigned to you",
                "message": "HC-2026-1038 (High Priority) assigned to you.",
                "is_read": False,
                "created_at": f"{today_str} 09:10 AM"
            },
            {
                "type": "notification",
                "notification_type": "SCHEDULE_SWAP_REQUEST",
                "recipient_employee_id": "HPE12345",
                "case_id": "",
                "title": "Schedule swap request",
                "message": "Maria Santos requested a schedule swap for tomorrow.",
                "is_read": False,
                "created_at": f"{today_str} 08:58 AM"
            }
        ]
        st.session_state.mock_db.extend(notifications)

        # 7. Today's Schedules & PTO
        sample_schedules = [
            {
                "type": "Schedule_Monitoring",
                "employee_id": "HPE12345",
                "agent_name": "Arianne Escabillas",
                "date": today_str,
                "activities": [
                    {"start": "08:00 AM", "end": "10:00 AM", "activity": "Available", "hours": 2},
                    {"start": "10:00 AM", "end": "10:15 AM", "activity": "Break", "hours": 0.25},
                    {"start": "10:15 AM", "end": "12:00 PM", "activity": "Available", "hours": 1.75},
                    {"start": "12:00 PM", "end": "01:00 PM", "activity": "Lunch", "hours": 1},
                    {"start": "01:00 PM", "end": "03:00 PM", "activity": "Available", "hours": 2},
                    {"start": "03:00 PM", "end": "03:15 PM", "activity": "Break", "hours": 0.25},
                    {"start": "03:15 PM", "end": "05:00 PM", "activity": "Available", "hours": 1.75}
                ]
            },
            {
                "type": "Schedule_Monitoring",
                "employee_id": "HPE001236",
                "agent_name": "Daniel Reyes",
                "date": today_str,
                "activities": [
                    {"start": "08:00 AM", "end": "09:00 AM", "activity": "Admin Work", "hours": 1},
                    {"start": "09:00 AM", "end": "11:00 AM", "activity": "Available", "hours": 2},
                    {"start": "11:00 AM", "end": "12:00 PM", "activity": "Meeting", "hours": 1},
                    {"start": "12:00 PM", "end": "01:00 PM", "activity": "Lunch", "hours": 1},
                    {"start": "01:00 PM", "end": "03:00 PM", "activity": "Coaching", "hours": 2},
                    {"start": "03:00 PM", "end": "05:00 PM", "activity": "Available", "hours": 2}
                ]
            }
        ]
        st.session_state.mock_db.extend(sample_schedules)

        # 8. PTO Allocation record
        pto_alloc = {
            "type": "schedule",
            "subtype": "pto_allocation",
            "year": now.year,
            "month": now.month,
            "total_allocation": 45,
            "used": 12,
            "daily_limits": {f"{today_str}": {"limit": 2, "booked": 1}}
        }
        st.session_state.mock_db.append(pto_alloc)

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

    # --- Query Methods ---
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
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        self.insert_one({
            "type": "account_activity",
            "timestamp": now_str,
            "user": user,
            "activity": activity,
            "details": details
        })

db_mgr = DatabaseManager()

# ======================================================================================
# 4. SESSION STATE INITIALIZATION
# ======================================================================================
def init_session():
    defaults = {
        "authenticated": True,  # Pre-authenticated for quick review or toggleable
        "user_email": "arianne.escabillas@hpe.com",
        "current_user": None,
        "auth_mode": "signin",  # "signin" or "signup"
        "current_page": "Dashboard",
        "admin_subview": "Admin View", # "Admin View" or "Agent View"
        "selected_case_id": None,
        "active_modal": None, # e.g. "case_details", "profile_dropdown", "notification_modal", "admin_message_popup"
        "modal_data": {},
        "global_search": "",
        "case_page_num": 1,
        "cases_per_page": 12,
        "selected_cases": set(),
        "monitoring_selected_agent": "HPE001236",
        "report_period": "Daily",
        "fullscreen_dashboard": False
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
# 5. CUSTOM CSS (HPE ENTERPRISE AESTHETIC & SCREENSHOT FAITHFUL)
# ======================================================================================
def apply_enterprise_css():
    st.markdown(
        f"""
        <style>
        /* Base Reset & Fonts */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        
        html, body, [class*="css"] {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            color: {COLOR_TEXT_MAIN};
            background-color: {COLOR_BG};
        }}

        /* Hide standard Streamlit header & toolbar */
        header[data-testid="stHeader"] {{
            display: none !important;
        }}
        footer {{
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
            font-size: 15px;
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

        /* HPE Top Navigation Header */
        .hpe-header {{
            background-color: {COLOR_NAVY_SURFACE};
            padding: 12px 24px;
            border-radius: 10px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            color: white;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
        }}
        .hpe-logo-text {{
            font-size: 18px;
            font-weight: 700;
            color: #FFFFFF;
            letter-spacing: -0.5px;
            line-height: 1.2;
        }}
        .hpe-sublogo-text {{
            font-size: 11px;
            color: #94A3B8;
            font-weight: 400;
        }}

        /* Cards & Containers */
        .hpe-card {{
            background: #FFFFFF;
            border: 1px solid {COLOR_BORDER};
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.03), 0 2px 6px rgba(0,0,0,0.02);
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
            box-shadow: 0 1px 4px rgba(0,0,0,0.04);
            height: 100%;
        }}
        .kpi-title {{
            font-size: 13px;
            color: {COLOR_TEXT_MUTED};
            font-weight: 500;
            margin-bottom: 4px;
        }}
        .kpi-value {{
            font-size: 26px;
            font-weight: 700;
            color: {COLOR_TEXT_MAIN};
            line-height: 1.2;
        }}
        .kpi-subtext {{
            font-size: 11px;
            color: {COLOR_GREEN};
            font-weight: 600;
            margin-top: 4px;
        }}

        /* Custom Status and Priority Pills */
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
        .pill-coaching {{ background: #F3E8FF; color: #7E22CE; }}
        .pill-meeting {{ background: #FFEDD5; color: #C2410C; }}
        .pill-lunch {{ background: #FEF3C7; color: #B45309; }}
        .pill-break {{ background: #E2E8F0; color: #475569; }}

        /* Table Design */
        .hpe-table {{
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            font-size: 13px;
        }}
        .hpe-table th {{
            background: #F8FAFC;
            color: {COLOR_TEXT_MUTED};
            font-weight: 600;
            padding: 12px 14px;
            border-bottom: 1px solid {COLOR_BORDER};
            text-align: left;
        }}
        .hpe-table td {{
            padding: 12px 14px;
            border-bottom: 1px solid #F1F5F9;
            color: {COLOR_TEXT_MAIN};
            vertical-align: middle;
        }}
        .hpe-table tr:hover td {{
            background: #F8FAFC;
        }}

        /* Buttons Styling */
        div.stButton > button[kind="primary"] {{
            background-color: {COLOR_TEAL} !important;
            color: #071B2B !important;
            border: none !important;
            font-weight: 600 !important;
            border-radius: 6px !important;
            padding: 8px 18px !important;
        }}
        div.stButton > button[kind="primary"]:hover {{
            background-color: {COLOR_TEAL_DARK} !important;
            box-shadow: 0 2px 8px rgba(0, 212, 170, 0.3) !important;
        }}

        /* Custom Modal Backdrop Overlay */
        .modal-overlay {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(7, 27, 43, 0.65);
            backdrop-filter: blur(4px);
            z-index: 99999;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .modal-box {{
            background: #FFFFFF;
            border-radius: 12px;
            width: 90%;
            max-width: 1100px;
            max-height: 90vh;
            overflow-y: auto;
            box-shadow: 0 20px 40px rgba(0,0,0,0.25);
            padding: 24px;
            position: relative;
        }}
        </style>
        """,
        unsafe_allow_html=True
    )

apply_enterprise_css()

# ======================================================================================
# 6. AUTHENTICATION & LOGIN SCREEN (MATCHES IMAGE 1000056907.png)
# ======================================================================================
def render_auth_page():
    """Renders the split-screen Sign In / Sign Up view."""
    col_hero, col_form = st.columns([1.1, 1], gap="large")

    with col_hero:
        st.markdown(
            f"""
            <div style="background: linear-gradient(135deg, #071B2B 0%, #0B2B47 100%);
                        border-radius: 16px; padding: 48px 36px; color: white; min-height: 600px;
                        display: flex; flex-direction: column; justify-content: space-between;
                        box-shadow: 0 10px 25px rgba(0,0,0,0.15); border: 1px solid #163E63;">
                <div>
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 24px;">
                        <div style="width: 24px; height: 12px; border: 3px solid {COLOR_TEAL};"></div>
                        <span style="font-weight: 700; letter-spacing: 0.5px; font-size: 13px;">Hewlett Packard Enterprise</span>
                    </div>
                    <h1 style="font-size: 42px; font-weight: 800; margin: 0; line-height: 1.1; color: white;">
                        HPE <span style="color: {COLOR_TEAL};">CaseFlow</span>
                    </h1>
                    <p style="font-size: 15px; color: #94A3B8; margin-top: 6px; margin-bottom: 40px;">
                        Team Task and Case Management System
                    </p>
                    
                    <div style="display: flex; flex-direction: column; gap: 24px;">
                        <div style="display: flex; gap: 16px; align-items: flex-start;">
                            <div style="background: rgba(0, 212, 170, 0.15); border-radius: 50%; width: 44px; height: 44px; display: flex; align-items: center; justify-content: center; font-size: 20px; color: {COLOR_TEAL};">📁</div>
                            <div>
                                <h4 style="margin: 0; font-size: 16px; font-weight: 600; color: white;">Manage Cases</h4>
                                <p style="margin: 2px 0 0 0; font-size: 13px; color: #94A3B8;">Track and resolve tasks efficiently with live workload rebalancing</p>
                            </div>
                        </div>
                        <div style="display: flex; gap: 16px; align-items: flex-start;">
                            <div style="background: rgba(0, 212, 170, 0.15); border-radius: 50%; width: 44px; height: 44px; display: flex; align-items: center; justify-content: center; font-size: 20px; color: {COLOR_TEAL};">👥</div>
                            <div>
                                <h4 style="margin: 0; font-size: 16px; font-weight: 600; color: white;">Work Together</h4>
                                <p style="margin: 2px 0 0 0; font-size: 13px; color: #94A3B8;">Stay aligned with your team with seamless transfer requests and schedule swaps</p>
                            </div>
                        </div>
                        <div style="display: flex; gap: 16px; align-items: flex-start;">
                            <div style="background: rgba(0, 212, 170, 0.15); border-radius: 50%; width: 44px; height: 44px; display: flex; align-items: center; justify-content: center; font-size: 20px; color: {COLOR_TEAL};">📊</div>
                            <div>
                                <h4 style="margin: 0; font-size: 16px; font-weight: 600; color: white;">Drive Results</h4>
                                <p style="margin: 2px 0 0 0; font-size: 13px; color: #94A3B8;">Real-time insights, SLA breach alerts, and adherence reporting</p>
                            </div>
                        </div>
                    </div>
                </div>
                <div style="font-size: 12px; color: #64748B; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 20px; margin-top: 40px;">
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
                <div style="margin-top: 20px; margin-bottom: 24px;">
                    <h2 style="font-size: 28px; font-weight: 700; color: #071B2B; margin: 0;">Welcome Back!</h2>
                    <p style="font-size: 14px; color: #64748B; margin-top: 4px;">Sign in to your HPE CaseFlow account</p>
                </div>
                """,
                unsafe_allow_html=True
            )
            email_input = st.text_input("HPE Email Address", value="arianne.escabillas@hpe.com", placeholder="yourname@hpe.com", key="login_email")
            password_input = st.text_input("Password", value="Hpe@12345", type="password", key="login_pass")

            col_rem, col_forgot = st.columns([1, 1])
            with col_rem:
                st.checkbox("Remember me", value=True, key="login_remember")
            with col_forgot:
                if st.button("Forgot password?", type="secondary", key="forgot_btn"):
                    st.info("Password reset instructions sent to your corporate email.")

            if st.button("Sign In", type="primary", use_container_width=True, key="signin_submit_btn"):
                user = db_mgr.find_one({"type": "roster_list", "email": email_input.strip()})
                if user and db_mgr.check_password(password_input, user.get("password_hash", "")):
                    if user.get("account_status", "Active") != "Active":
                        st.error("This account has been deactivated. Please contact your administrator.")
                    else:
                        st.session_state.authenticated = True
                        st.session_state.user_email = user["email"]
                        st.session_state.current_user = user
                        db_mgr.log_activity(user["name"], "Login", "User logged into HPE CaseFlow")
                        st.rerun()
                else:
                    st.error("Invalid HPE credentials. Please check your email and password.")

            st.markdown(
                f"""
                <div style="text-align: center; margin: 18px 0; color: #94A3B8; font-size: 13px;">or</div>
                """,
                unsafe_allow_html=True
            )

            if st.button("🪟 Sign in with Microsoft (HPE)", use_container_width=True, key="ms_sso_btn"):
                # Fast track demo SSO
                user = db_mgr.find_one({"type": "roster_list", "email": "arianne.escabillas@hpe.com"})
                st.session_state.authenticated = True
                st.session_state.user_email = user["email"]
                st.session_state.current_user = user
                st.rerun()

            st.markdown(
                """
                <div style="text-align: center; margin-top: 24px; font-size: 13px; color: #64748B;">
                    Don't have an account?
                </div>
                """,
                unsafe_allow_html=True
            )
            if st.button("Sign up", key="switch_to_signup_btn", use_container_width=True):
                st.session_state.auth_mode = "signup"
                st.rerun()

        else: # SIGN UP
            st.markdown(
                """
                <div style="margin-top: 10px; margin-bottom: 20px;">
                    <h2 style="font-size: 26px; font-weight: 700; color: #071B2B; margin: 0;">Create Your Account</h2>
                    <p style="font-size: 14px; color: #64748B; margin-top: 4px;">Sign up to access HPE CaseFlow</p>
                </div>
                """,
                unsafe_allow_html=True
            )
            c1, c2 = st.columns(2)
            with c1:
                first_name = st.text_input("First Name", placeholder="First Name", key="reg_fn")
            with c2:
                last_name = st.text_input("Last Name", placeholder="Last Name", key="reg_ln")
            emp_id = st.text_input("Employee ID", placeholder="e.g. HPE12399", key="reg_eid")
            reg_email = st.text_input("HPE Email Address", placeholder="name@hpe.com", key="reg_email")
            reg_pass = st.text_input("Password", type="password", key="reg_pass")

            st.caption("Password must be at least 8 characters and include letters, numbers, and a special character.")

            if st.button("Sign Up", type="primary", use_container_width=True, key="signup_submit_btn"):
                if not (first_name and last_name and emp_id and reg_email and reg_pass):
                    st.warning("Please fill in all required fields.")
                elif len(reg_pass) < 8 or not any(c.isdigit() for c in reg_pass):
                    st.error("Password does not meet security requirements.")
                else:
                    existing = db_mgr.find_one({"type": "roster_list", "email": reg_email.strip()})
                    if existing:
                        st.error("An account with this email address already exists.")
                    else:
                        new_user = {
                            "type": "roster_list",
                            "first_name": first_name.strip(),
                            "last_name": last_name.strip(),
                            "name": f"{first_name.strip()} {last_name.strip()}",
                            "employee_id": emp_id.strip(),
                            "email": reg_email.strip(),
                            "password_hash": db_mgr.hash_password(reg_pass),
                            "role": "Agent",
                            "account_status": "Active",
                            "department": "Operations",
                            "current_aux": "Not Ready - Online",
                            "last_aux_change": datetime.datetime.now().strftime("%I:%M %p"),
                            "login_time": datetime.datetime.now().strftime("%I:%M %p"),
                            "photo_url": "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150&auto=format&fit=crop&q=80",
                            "active_cases": 0,
                            "today_assigned": 0,
                            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        db_mgr.insert_one(new_user)
                        st.success("Account created successfully! You can now sign in.")
                        st.session_state.auth_mode = "signin"
                        st.rerun()

            if st.button("Already have an account? Sign in", key="switch_to_signin_btn", use_container_width=True):
                st.session_state.auth_mode = "signin"
                st.rerun()

# ======================================================================================
# 7. AUTOMATIC CASE ASSIGNMENT ENGINE
# ======================================================================================
def auto_assign_case(case_number: str) -> Optional[str]:
    """
    Selects the most suitable agent currently Available, balancing total cases,
    critical case distribution, and fairness.
    """
    eligible_agents = db_mgr.find({
        "type": "roster_list",
        "account_status": "Active",
        "current_aux": "Available"
    })
    
    # Exclude admins who are not in agent capacity
    eligible_agents = [a for a in eligible_agents if a.get("role") in ["Agent", "Admin/Agent"]]
    
    if not eligible_agents:
        return None

    # Calculate current load
    agent_scores = []
    for ag in eligible_agents:
        agent_name = ag.get("name")
        active_cases = db_mgr.find({"type": "case", "assigned_to": agent_name, "is_closed": False})
        crit_cases = [c for c in active_cases if c.get("priority") == "Critical"]
        score = (len(crit_cases) * 5) + len(active_cases) + (ag.get("today_assigned", 0) * 0.5)
        agent_scores.append((score, ag))

    agent_scores.sort(key=lambda x: x[0])
    selected_agent = agent_scores[0][1]

    # Assign case
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
    db_mgr.update_one(
        {"type": "case", "case_number": case_number},
        {"$set": {
            "assigned_to": selected_agent["name"],
            "assignee_email": selected_agent["email"],
            "last_update": now_str
        }}
    )
    # Increment today_assigned
    db_mgr.update_one(
        {"type": "roster_list", "employee_id": selected_agent["employee_id"]},
        {"$set": {
            "active_cases": selected_agent.get("active_cases", 0) + 1,
            "today_assigned": selected_agent.get("today_assigned", 0) + 1
        }}
    )
    # Case history
    db_mgr.insert_one({
        "type": "case_history",
        "case_number": case_number,
        "timestamp": now_str,
        "user": "System",
        "action": "Case automatically assigned",
        "description": f"Assigned to {selected_agent['name']} based on workload balancing."
    })
    # Notification
    db_mgr.insert_one({
        "type": "notification",
        "notification_type": "NEW_CASE_ASSIGNED",
        "recipient_employee_id": selected_agent["employee_id"],
        "case_id": case_number,
        "title": "New Case Assigned to You",
        "message": f"Case {case_number} has been assigned to your queue.",
        "is_read": False,
        "created_at": now_str
    })
    return selected_agent["name"]

# ======================================================================================
# 8. AUX & STATUS SYSTEM
# ======================================================================================
def change_user_aux(new_aux: str):
    """Updates user AUX, persists to DB, logs aux_history."""
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

# ======================================================================================
# 9. TOP HEADER & NAVIGATION
# ======================================================================================
def render_top_header():
    """Renders the top navy header with search, notifications, and profile selector."""
    user = st.session_state.current_user
    role = user.get("role", "Agent")
    unread_notifs = db_mgr.find({"type": "notification", "recipient_employee_id": user["employee_id"], "is_read": False})

    header_col1, header_col2, header_col3 = st.columns([1.2, 2.5, 1.8])

    with header_col1:
        st.markdown(
            f"""
            <div style="display: flex; align-items: center; gap: 10px; padding: 6px 0;">
                <div style="width: 20px; height: 10px; border: 3px solid {COLOR_TEAL};"></div>
                <div>
                    <div style="font-size: 16px; font-weight: 700; color: #FFFFFF; line-height: 1.1;">HPE CaseFlow</div>
                    <div style="font-size: 10px; color: #94A3B8;">Team Task and Case Management System</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with header_col2:
        st.session_state.global_search = st.text_input(
            "Global Search",
            value=st.session_state.global_search,
            placeholder="Search cases, agents, vendors, or issues...",
            label_visibility="collapsed",
            key="header_search_input"
        )

    with header_col3:
        # Actions: Notifications bell, Profile Trigger, Fullscreen
        c_bell, c_prof, c_aux = st.columns([0.6, 2.0, 1.4])
        with c_bell:
            bell_label = f"🔔 {len(unread_notifs)}" if unread_notifs else "🔔"
            if st.button(bell_label, key="bell_btn"):
                st.session_state.active_modal = "notifications"
                st.rerun()

        with c_prof:
            prof_name = user.get("name", "User")
            if st.button(f"👤 {prof_name}", key="profile_modal_btn"):
                st.session_state.active_modal = "profile"
                st.rerun()

        with c_aux:
            current_aux = user.get("current_aux", "Available")
            new_aux = st.selectbox(
                "Aux",
                AUX_OPTIONS,
                index=AUX_OPTIONS.index(current_aux) if current_aux in AUX_OPTIONS else 0,
                label_visibility="collapsed",
                key="header_aux_select"
            )
            if new_aux != current_aux:
                change_user_aux(new_aux)
                st.rerun()

def render_sidebar():
    """Renders the left navigation sidebar matching the design screenshots."""
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

        # Role-based menu items
        if role in ["Admin", "Admin/Agent"]:
            pages = [
                ("Dashboard", "📊"),
                ("Monitoring", "👥"),
                ("Schedule", "📅"),
                ("Report", "📈"),
                ("Setting", "⚙️")
            ]
        else: # Agent
            pages = [
                ("Dashboard", "📊"),
                ("Schedule", "📅"),
                ("Report", "📈")
            ]

        for p_name, icon in pages:
            is_active = (st.session_state.current_page == p_name)
            container_class = "sidebar-active-btn" if is_active else ""
            st.markdown(f'<div class="{container_class}">', unsafe_allow_html=True)
            if st.button(f"{icon}  {p_name}", key=f"nav_{p_name}"):
                st.session_state.current_page = p_name
                st.session_state.selected_case_id = None
                st.session_state.active_modal = None
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("<div style='margin-top: 40px;'></div>", unsafe_allow_html=True)
        if st.button("🚪 Sign Out", key="sidebar_signout_btn"):
            db_mgr.log_activity(user["name"], "Logout", "User clicked Sign Out")
            st.session_state.authenticated = False
            st.session_state.current_user = None
            st.rerun()

        st.markdown(
            """
            <div style="position: absolute; bottom: 20px; font-size: 11px; color: #64748B;">
                HPE CaseFlow v1.0.0
            </div>
            """,
            unsafe_allow_html=True
        )

# ======================================================================================
# 10. MODALS & POPUPS (CENTRALIZED OVERLAYS)
# ======================================================================================
def render_profile_modal():
    """Renders the comprehensive profile card popup (Images 2, 3, 4)."""
    user = st.session_state.current_user
    role = user.get("role", "Agent")

    with st.expander("👤 User Profile & Status Details", expanded=True):
        col_close, _ = st.columns([1, 10])
        with col_close:
            if st.button("✕ Close", key="close_profile_modal_btn"):
                st.session_state.active_modal = None
                st.rerun()

        col_left, col_mid, col_right = st.columns([1.2, 1.4, 1.4])
        with col_left:
            st.image(user.get("photo_url", "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=150&auto=format&fit=crop&q=80"), width=110)
            st.markdown(f"### {user.get('name')}")
            st.caption(f"{user.get('email')} • ID: {user.get('employee_id')}")
            st.markdown(f'<span class="pill pill-admin">{role}</span>', unsafe_allow_html=True)

        with col_mid:
            st.markdown("**Current Status / AUX**")
            new_aux = st.selectbox("Status", AUX_OPTIONS, index=AUX_OPTIONS.index(user.get("current_aux", "Available")), key="modal_aux_sel")
            if new_aux != user.get("current_aux"):
                change_user_aux(new_aux)
                st.rerun()

            c_log1, c_log2 = st.columns(2)
            with c_log1:
                st.metric("Login Time", user.get("login_time", "08:45 AM"))
            with c_log2:
                st.metric("Current Session", "3h 42m")

        with col_right:
            st.markdown("**Today's Schedule**")
            sched = db_mgr.find_one({"type": "Schedule_Monitoring", "employee_id": user["employee_id"], "date": date.today().strftime("%Y-%m-%d")})
            if sched and sched.get("activities"):
                for act in sched["activities"][:4]:
                    color = AUX_COLORS.get(act["activity"], "#94A3B8")
                    st.markdown(
                        f"""
                        <div style="display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px;">
                            <span><span style="color: {color};">●</span> {act['start']} - {act['end']}</span>
                            <span style="font-weight: 600;">{act['activity']}</span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
            else:
                st.caption("Standard 08:00 AM - 05:00 PM shift active.")

        st.divider()
        b1, b2, b3, b4 = st.columns(4)
        with b1:
            if st.button("Change Password", key="prof_btn_cp"):
                st.info("Password change form opened.")
        with b2:
            if st.button("My Schedule", key="prof_btn_sched"):
                st.session_state.current_page = "Schedule"
                st.session_state.active_modal = None
                st.rerun()
        with b3:
            if st.button("AUX History", key="prof_btn_auxhist"):
                st.session_state.active_modal = "aux_history"
                st.rerun()
        with b4:
            if st.button("Sign Out", type="secondary", key="prof_btn_signout"):
                st.session_state.authenticated = False
                st.session_state.current_user = None
                st.rerun()

def render_notification_center():
    """Notification Dialog Popup."""
    user = st.session_state.current_user
    notifs = db_mgr.find({"type": "notification", "recipient_employee_id": user["employee_id"]}, sort_key="created_at", ascending=False)

    with st.expander("🔔 Notification Center", expanded=True):
        col_c, col_mark = st.columns([1, 4])
        with col_c:
            if st.button("✕ Close", key="notif_close_btn"):
                st.session_state.active_modal = None
                st.rerun()
        with col_mark:
            if st.button("Mark All as Read", key="notif_mark_all_btn"):
                for n in notifs:
                    db_mgr.update_one({"_id": n["_id"]}, {"$set": {"is_read": True}})
                st.rerun()

        if not notifs:
            st.info("No notifications at this time.")
        else:
            for n in notifs:
                unread_indicator = "🔴" if not n.get("is_read") else "⚪"
                with st.container():
                    st.markdown(
                        f"""
                        <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; margin-bottom: 8px;">
                            <div style="display: flex; justify-content: space-between; font-size: 13px;">
                                <strong>{unread_indicator} {n.get('title')}</strong>
                                <span style="color: #64748B; font-size: 11px;">{n.get('created_at')}</span>
                            </div>
                            <div style="font-size: 12px; color: #475569; margin-top: 4px;">{n.get('message')}</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                    c_act1, c_act2 = st.columns([1, 4])
                    with c_act1:
                        if n.get("case_id"):
                            if st.button(f"View {n.get('case_id')}", key=f"btn_vw_{n['_id']}"):
                                st.session_state.selected_case_id = n.get("case_id")
                                st.session_state.active_modal = "case_details"
                                st.rerun()

# ======================================================================================
# 11. CASE DETAILS VIEW / MODAL (MATCHES IMAGES 1000057247.png & 1000057248.png)
# ======================================================================================
def render_case_details_view(case_number: str):
    """Full enterprise Case Details view with tabs, vendor info, timeline, and breach email."""
    case = db_mgr.find_one({"type": "case", "case_number": case_number})
    if not case:
        st.error(f"Case {case_number} not found.")
        if st.button("Back to Dashboard"):
            st.session_state.selected_case_id = None
            st.session_state.active_modal = None
            st.rerun()
        return

    user = st.session_state.current_user
    is_admin = user.get("role") in ["Admin", "Admin/Agent"]
    vendor = db_mgr.find_one({"type": "vendor", "vendor_name": case.get("vendor_name")}) or {}

    # Header Ribbon
    col_back, col_title, col_time = st.columns([1, 5, 2])
    with col_back:
        if st.button("← Back", key="back_to_list_btn"):
            st.session_state.selected_case_id = None
            st.session_state.active_modal = None
            st.rerun()
    with col_title:
        p_class = f"pill-{case.get('priority', 'Low').lower()}"
        st.markdown(
            f"""
            <div style="display: flex; align-items: center; gap: 12px;">
                <h2 style="margin: 0; font-size: 24px;">{case.get('case_number')}</h2>
                <span class="pill {p_class}">{case.get('priority')}</span>
                <span style="font-size: 18px; font-weight: 600; color: #1E293B;">{case.get('subject')}</span>
            </div>
            <p style="margin: 4px 0 0 0; color: #64748B; font-size: 13px;">{case.get('description')}</p>
            """,
            unsafe_allow_html=True
        )
    with col_time:
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

    # Summary Strip
    st.markdown(
        f"""
        <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px 20px; margin: 16px 0; display: flex; justify-content: space-between; font-size: 12px;">
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

    # 3 Main Operational Columns
    c_info, c_vendor, c_action = st.columns([1.2, 1.2, 1.4], gap="medium")

    # Column 1: Case Information
    with c_info:
        st.markdown("#### 📋 Case Information")
        with st.container():
            st.text_input("Case #", value=case.get("case_number"), disabled=True)
            st.text_input("Subject", value=case.get("subject"), disabled=True)
            st.text_area("Description", value=case.get("description"), height=110, disabled=True)
            st.text_input("Client / Account", value=case.get("client"), disabled=True)
            st.text_input("Related System", value=case.get("related_system"), disabled=True)

    # Column 2: Vendor Information
    with c_vendor:
        st.markdown("#### 🏢 Vendor Information")
        st.markdown(
            f"""
            <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 16px; font-size: 13px;">
                <div style="font-size: 16px; font-weight: 700; color: #071B2B; margin-bottom: 8px;">{vendor.get('vendor_name', 'ABC Software Inc.')}</div>
                <div style="margin-bottom: 6px;"><strong>Primary Contact:</strong> {vendor.get('primary_contact', 'Michael Tan')}</div>
                <div style="margin-bottom: 6px;"><strong>Email:</strong> <a href="mailto:{vendor.get('email')}">{vendor.get('email', 'support@abcsoftware.com')}</a></div>
                <div style="margin-bottom: 6px;"><strong>Phone:</strong> {vendor.get('phone', '+1 555 123 4567')}</div>
                <div style="margin-bottom: 6px;"><strong>Alternate Contact:</strong> {vendor.get('alternate_contact', 'Sarah Lim')}</div>
                <div style="margin-bottom: 6px;"><strong>Alternate Email:</strong> {vendor.get('alternate_email', 'sarah.lim@abcsoftware.com')}</div>
                <div><strong>Address:</strong> {vendor.get('address', '123 Innovation Drive, San Jose, CA')}</div>
            </div>
            """,
            unsafe_allow_html=True
        )
        st.markdown("<div style='margin-top: 12px;'></div>", unsafe_allow_html=True)
        q1, q2, q3 = st.columns(3)
        with q1:
            if st.button("📋 Copy Email", key="copy_email_btn"):
                st.toast("Email copied to clipboard!")
        with q2:
            if st.button("📞 Copy Phone", key="copy_phone_btn"):
                st.toast("Phone number copied!")
        with q3:
            if st.button("📊 In Excel", key="vw_excel_btn"):
                st.toast("Vendor record downloaded as Excel.")

    # Column 3: Update Case & Actions
    with c_action:
        st.markdown("#### ⏱️ Update Case")
        # Load validation dropdowns from MongoDB
        val_doc = db_mgr.find_one({"type": "Validation_Dropdown"}) or {}
        statuses = val_doc.get("Case_Status", ["Open", "In Progress", "On Hold", "Resolved", "Closed"])
        reasons = val_doc.get("Case_Reason", ["Waiting for Vendor Response", "Technical Investigation"])
        closures = val_doc.get("Closure_Type", ["Resolved - Normal", "Contract Breach"])
        breaches = val_doc.get("Contract_Breach", ["Vendor SLA Exceeded > 48h", "License Delivery Failure"])

        current_st = case.get("status", "Open")
        new_status = st.selectbox("Case Status", statuses, index=statuses.index(current_st) if current_st in statuses else 0)
        status_reason = st.selectbox("Status Reason", reasons)
        closure_type = st.selectbox("Closure Type", ["-- Select Closure Type --"] + closures)
        
        breach_reason = None
        if closure_type == "Contract Breach":
            breach_reason = st.selectbox("Breach Reason", breaches)

        remarks = st.text_area("Remarks / Update", placeholder="Add update, notes, or next steps...", height=90)

        # Admin Reassign or Agent Transfer
        target_agent = None
        if is_admin:
            st.markdown("**Reassign Case (Admin Only)**")
            agents_list = [a["name"] for a in db_mgr.find({"type": "roster_list", "account_status": "Active"})]
            target_agent = st.selectbox("Reassign To", ["-- Keep Current Assignee --"] + agents_list)
        
        btn_u1, btn_u2, btn_u3 = st.columns(3)
        with btn_u1:
            if st.button("Update Case", type="primary", key="save_case_update_btn"):
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
                updates = {
                    "status": new_status,
                    "status_reason": status_reason,
                    "last_update": now_str
                }
                if closure_type != "-- Select Closure Type --":
                    updates["closure_type"] = closure_type
                    if closure_type == "Contract Breach":
                        updates["breach_reason"] = breach_reason
                    if "Resolved" in closure_type or "Closed" in closure_type:
                        updates["is_closed"] = True

                if target_agent and target_agent != "-- Keep Current Assignee --":
                    updates["assigned_to"] = target_agent

                db_mgr.update_one({"type": "case", "case_number": case_number}, {"$set": updates})

                # Log History
                desc_text = f"Status: {new_status} | Reason: {status_reason}"
                if remarks:
                    desc_text += f" | Note: {remarks}"
                db_mgr.insert_one({
                    "type": "case_history",
                    "case_number": case_number,
                    "timestamp": now_str,
                    "user": user.get("name"),
                    "action": f"Status updated to {new_status}",
                    "description": desc_text
                })
                st.success("Case updated successfully!")
                st.rerun()

        with btn_u2:
            if st.button("Add Note", key="add_note_btn"):
                if remarks:
                    now_str = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
                    db_mgr.insert_one({
                        "type": "case_history",
                        "case_number": case_number,
                        "timestamp": now_str,
                        "user": user.get("name"),
                        "action": "Note added",
                        "description": remarks
                    })
                    st.success("Note logged in case history.")
                    st.rerun()
                else:
                    st.warning("Please type a note in remarks.")

        with btn_u3:
            if not is_admin:
                if st.button("Request Transfer", key="agent_transfer_btn"):
                    st.session_state.active_modal = "transfer_request_dialog"
                    st.session_state.modal_data = {"case_number": case_number}
                    st.rerun()

    st.markdown("<hr style='margin: 20px 0; border: none; border-top: 1px solid #E2E8F0;'>", unsafe_allow_html=True)

    # Bottom Row: Case History Timeline (Left) & Breach Notice Generator (Right)
    b_left, b_right = st.columns([1.2, 1.8], gap="medium")

    with b_left:
        st.markdown("#### 🕒 Case History Timeline")
        histories = db_mgr.find({"type": "case_history", "case_number": case_number}, sort_key="timestamp", ascending=False)
        if not histories:
            st.caption("No history records recorded.")
        else:
            for h in histories:
                st.markdown(
                    f"""
                    <div style="border-left: 2px solid {COLOR_BLUE}; padding-left: 12px; margin-bottom: 12px; position: relative;">
                        <div style="font-size: 11px; color: #64748B;">{h.get('timestamp')} • <strong>{h.get('user')}</strong></div>
                        <div style="font-size: 12px; font-weight: 600; color: #1E293B;">{h.get('action')}</div>
                        <div style="font-size: 12px; color: #475569;">{h.get('description')}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

    with b_right:
        st.markdown("#### ✉️ Automated Breach Notice Email")
        use_template = st.toggle("Use Template", value=True)
        default_subj = f"Notice of Contract Breach – {case.get('case_number')}"
        default_body = (
            f"Dear {vendor.get('vendor_name', 'Vendor')},\n\n"
            f"This is to inform you that the following case ({case.get('case_number')}) is nearing breach due to "
            f"continued delay in the {case.get('subject')}. As per our agreement, we have not yet received the "
            f"required confirmation from your team.\n\n"
            f"Please provide an update at your earliest convenience to avoid formal SLA penalty.\n\n"
            f"Thank you,\n{user.get('name')}\nOperations Team, Hewlett Packard Enterprise"
        )
        to_email = st.text_input("To", value=vendor.get("email", "support@abcsoftware.com"))
        subj_email = st.text_input("Subject", value=default_subj)
        body_email = st.text_area("Body", value=default_body, height=140)

        em1, em2 = st.columns([1, 4])
        with em1:
            if st.button("Send Email", type="primary", key="send_breach_email_btn"):
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
                db_mgr.insert_one({
                    "type": "case_history",
                    "case_number": case_number,
                    "timestamp": now_str,
                    "user": user.get("name"),
                    "action": "Contract Breach Notice Sent",
                    "description": f"Notice sent to {to_email} regarding SLA deadline."
                })
                st.success("Notice sent successfully to vendor.")
                st.rerun()

# ======================================================================================
# 12. DASHBOARDS (ADMIN & AGENT VIEWS)
# ======================================================================================
def render_dashboard():
    """Renders Admin Dashboard (Image 8, 9) or Agent Dashboard (Image 7)."""
    user = st.session_state.current_user
    role = user.get("role", "Agent")

    # Header with Role Switcher for Admin/Agent
    col_d1, col_d2 = st.columns([3, 1.2])
    with col_d1:
        st.markdown(
            f"""
            <h1 style="font-size: 26px; font-weight: 700; margin: 0; color: #071B2B;">
                {'My Dashboard' if role == 'Agent' or st.session_state.admin_subview == 'Agent View' else 'Dashboard'}
            </h1>
            <p style="font-size: 13px; color: #64748B; margin-top: 2px;">
                Good morning, {user.get('first_name')}! Here's what's happening with your {'assigned cases' if role == 'Agent' else 'team'} today.
            </p>
            """,
            unsafe_allow_html=True
        )
    with col_d2:
        now_dt = datetime.datetime.now()
        date_time_str = now_dt.strftime("%A, %B %d, %Y  •  %I:%M %p")
        st.markdown(
            f"""
            <div style="text-align: right; font-size: 13px; color: #64748B; font-weight: 500;">
                {date_time_str}
            </div>
            """,
            unsafe_allow_html=True
        )
        if role == "Admin/Agent":
            view_sub = st.radio("Switch View", ["Admin View", "Agent View"], horizontal=True, label_visibility="collapsed")
            if view_sub != st.session_state.admin_subview:
                st.session_state.admin_subview = view_sub
                st.rerun()

    # Determine Active Query Filter
    is_agent_view = (role == "Agent") or (role == "Admin/Agent" and st.session_state.admin_subview == "Agent View")
    case_query = {"type": "case"}
    if is_agent_view:
        case_query["assigned_to"] = user.get("name")

    all_cases = db_mgr.find(case_query)
    active_cases = [c for c in all_cases if not c.get("is_closed")]
    crit_cases = [c for c in active_cases if c.get("priority") == "Critical"]
    due_soon = [c for c in active_cases if "Today" in str(c.get("due_date")) or "11:00 AM" in str(c.get("due_date"))]
    on_track = [c for c in active_cases if c.get("status") in ["On Track", "In Progress"]]

    # 4 KPI Cards
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div>
                    <div class="kpi-title">{'My Active Cases' if is_agent_view else 'Active Cases'}</div>
                    <div class="kpi-value">{len(active_cases)}</div>
                    <div class="kpi-subtext">↑ 12% from yesterday</div>
                </div>
                <div style="font-size: 32px; color: {COLOR_BLUE};">📁</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with k2:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div>
                    <div class="kpi-title">Critical</div>
                    <div class="kpi-value" style="color: {COLOR_RED};">{len(crit_cases)}</div>
                    <div class="kpi-subtext" style="color: {COLOR_RED};">↑ 3 new</div>
                </div>
                <div style="font-size: 32px; color: {COLOR_RED};">⚠️</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with k3:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div>
                    <div class="kpi-title">Due Soon</div>
                    <div class="kpi-value" style="color: {COLOR_YELLOW};">{len(due_soon)}</div>
                    <div class="kpi-subtext" style="color: {COLOR_YELLOW};">↑ 5 new</div>
                </div>
                <div style="font-size: 32px; color: {COLOR_YELLOW};">⏰</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with k4:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div>
                    <div class="kpi-title">On Track</div>
                    <div class="kpi-value" style="color: {COLOR_GREEN};">{len(on_track)}</div>
                    <div class="kpi-subtext">↑ 4 new</div>
                </div>
                <div style="font-size: 32px; color: {COLOR_GREEN};">✅</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown("<div style='margin-top: 24px;'></div>", unsafe_allow_html=True)

    # Main Grid Layout: Left Cases Table vs Right Panel (Agents Online or Alerts)
    if is_agent_view:
        col_main, col_side = st.columns([3.2, 1.2], gap="large")
    else:
        col_main, col_side = st.columns([3.3, 1.1], gap="medium")

    with col_main:
        st.markdown(f"### {'My Cases' if is_agent_view else f'Active Cases ({len(active_cases)})'}")
        
        # Search & Filter Controls
        f_s, f_p, f_st, f_res = st.columns([2.5, 1.2, 1.2, 0.8])
        with f_s:
            case_search = st.text_input("Filter cases", placeholder="Search by case #, subject, assignee, vendor...", label_visibility="collapsed")
        with f_p:
            priority_filter = st.selectbox("Priority", ["All Priority", "Critical", "High", "Medium", "Low"], label_visibility="collapsed")
        with f_st:
            status_filter = st.selectbox("Status", ["All Status", "Open", "In Progress", "On Hold", "On Track", "Resolved"], label_visibility="collapsed")
        with f_res:
            if st.button("Reset", key="reset_filters_btn"):
                st.rerun()

        # Filter Logic
        filtered = active_cases
        if case_search:
            s_low = case_search.lower()
            filtered = [c for c in filtered if s_low in c.get("case_number", "").lower() or s_low in c.get("subject", "").lower() or s_low in c.get("assigned_to", "").lower()]
        if priority_filter != "All Priority":
            filtered = [c for c in filtered if c.get("priority") == priority_filter]
        if status_filter != "All Status":
            filtered = [c for c in filtered if c.get("status") == status_filter]

        # Bulk selection toolbar (Admin only)
        if not is_agent_view:
            b_bar1, b_bar2, b_bar3, b_bar4 = st.columns([1.5, 1.2, 1.2, 1.2])
            with b_bar1:
                st.caption(f"{len(st.session_state.selected_cases)} cases selected")
            with b_bar2:
                if st.button("👥 Bulk Reassign", disabled=len(st.session_state.selected_cases) == 0):
                    st.session_state.active_modal = "bulk_reassign"
                    st.rerun()
            with b_bar3:
                if st.button("🔄 Change Status", disabled=len(st.session_state.selected_cases) == 0):
                    st.session_state.active_modal = "bulk_status"
                    st.rerun()
            with b_bar4:
                if st.button("📥 Export CSV"):
                    df_exp = pd.DataFrame(filtered)
                    st.download_button("Download", df_exp.to_csv(index=False), "cases.csv", "text/csv")

        # Table Display
        if not filtered:
            st.info("No cases found matching criteria.")
        else:
            # Header
            st.markdown(
                """
                <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px 8px 0 0; padding: 10px 14px; display: grid; grid-template-columns: 1.2fr 2.5fr 1fr 1.5fr 1.5fr 1.2fr 1fr 0.8fr; font-size: 12px; font-weight: 600; color: #64748B;">
                    <div>Case #</div>
                    <div>Subject</div>
                    <div>Priority</div>
                    <div>Assigned To</div>
                    <div>Due Date</div>
                    <div>Status</div>
                    <div>Last Update</div>
                    <div>Action</div>
                </div>
                """,
                unsafe_allow_html=True
            )

            for c in filtered:
                p_pill = f'<span class="pill pill-{c.get("priority", "low").lower()}">{c.get("priority")}</span>'
                s_pill = f'<span class="pill pill-admin">{c.get("status")}</span>'
                c_num = c.get("case_number")

                row_col1, row_col2 = st.columns([7, 0.8])
                with row_col1:
                    st.markdown(
                        f"""
                        <div style="background: white; border: 1px solid #F1F5F9; padding: 10px 14px; display: grid; grid-template-columns: 1.2fr 2.5fr 1fr 1.5fr 1.5fr 1.2fr 1fr; font-size: 12px; align-items: center;">
                            <div style="font-weight: 600; color: {COLOR_BLUE};">{c.get('case_number')}</div>
                            <div style="font-weight: 500;">{c.get('subject')}</div>
                            <div>{p_pill}</div>
                            <div>{c.get('assigned_to')}</div>
                            <div style="color: {COLOR_RED if '11:00 AM' in str(c.get('due_date')) else '#1E293B'};">{c.get('due_date')}</div>
                            <div>{s_pill}</div>
                            <div style="color: #64748B;">{c.get('last_update')}</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                with row_col2:
                    if st.button("Open", key=f"open_case_{c_num}"):
                        st.session_state.selected_case_id = c_num
                        st.rerun()

    # Right Panel: Agents Online (Admin) OR Quick Actions & Alerts (Agent)
    with col_side:
        if not is_agent_view:
            st.markdown("### Agents Online")
            agents = db_mgr.find({"type": "roster_list", "account_status": "Active"})
            # Exclude strict Admin role from appearing as agents in line with Master Prompt
            online_agents = [a for a in agents if a.get("role") in ["Agent", "Admin/Agent"]]

            for ag in online_agents:
                aux_val = ag.get("current_aux", "Available")
                aux_dot = AUX_COLORS.get(aux_val, "#94A3B8")
                st.markdown(
                    f"""
                    <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 10px; margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <img src="{ag.get('photo_url')}" style="width: 32px; height: 32px; border-radius: 50%; object-fit: cover;">
                            <div>
                                <div style="font-size: 12px; font-weight: 600;">{ag.get('name')}</div>
                                <div style="font-size: 10px; color: #64748B;"><span style="color: {aux_dot};">●</span> {aux_val}</div>
                            </div>
                        </div>
                        <div style="font-size: 12px; font-weight: 700; background: #F1F5F9; border-radius: 50%; width: 24px; height: 24px; display: flex; align-items: center; justify-content: center;">
                            {ag.get('active_cases', 0)}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
        else:
            # Agent Right Panel: Schedule summary, Alerts, Quick Actions
            st.markdown("### Today's Shift")
            st.info("🕒 08:00 AM – 05:00 PM (Regular Shift)")

            st.markdown("### Alerts")
            st.markdown(
                f"""
                <div style="background: #FEF2F2; border: 1px solid #F87171; border-radius: 8px; padding: 10px; font-size: 12px; margin-bottom: 10px;">
                    <div style="color: #DC2626; font-weight: 600;">⚠️ Critical Case Due Soon</div>
                    <div style="color: #7F1D1D;">HC-2026-1044 is due in under 2 hours.</div>
                </div>
                """,
                unsafe_allow_html=True
            )

            st.markdown("### Quick Actions")
            if st.button("✉️ Send Message to Lead", use_container_width=True):
                st.toast("Message sent to Operations Lead.")
            if st.button("📅 Request Schedule Swap", use_container_width=True):
                st.session_state.current_page = "Schedule"
                st.rerun()

# ======================================================================================
# 13. MONITORING PAGE (ADMIN / ADMIN-AGENT ONLY — MATCHES IMAGE 1000057261.png)
# ======================================================================================
def render_monitoring_page():
    """Real-time monitoring table and agent detail side-panel."""
    user = st.session_state.current_user
    if user.get("role") not in ["Admin", "Admin/Agent"]:
        st.error("Unauthorized. Monitoring is restricted to Administrator roles.")
        return

    # Top KPI Metrics Strip
    all_agents = db_mgr.find({"type": "roster_list", "account_status": "Active"})
    total_agents = len(all_agents)
    available_cnt = len([a for a in all_agents if a.get("current_aux") == "Available"])
    on_aux_cnt = len([a for a in all_agents if a.get("current_aux") in ["Break", "Lunch", "Admin Work"]])
    meeting_cnt = len([a for a in all_agents if a.get("current_aux") in ["Meeting", "Coaching"]])
    not_ready_cnt = len([a for a in all_agents if a.get("current_aux") == "Not Ready - Online"])

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("Total Logged In", f"{total_agents} / {total_agents + 3}")
    with m2:
        st.metric("Available", f"{available_cnt}", f"{int(available_cnt/total_agents*100 if total_agents else 0)}%")
    with m3:
        st.metric("On AUX", f"{on_aux_cnt}", f"{int(on_aux_cnt/total_agents*100 if total_agents else 0)}%")
    with m4:
        st.metric("In Meeting/Coaching", f"{meeting_cnt}", f"{int(meeting_cnt/total_agents*100 if total_agents else 0)}%")
    with m5:
        st.metric("Not Ready", f"{not_ready_cnt}", "0%")

    st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)

    col_tbl, col_detail = st.columns([2.5, 1.5], gap="large")

    with col_tbl:
        st.markdown("### Agent Live Status")
        # Search & Filters
        f1, f2, f3 = st.columns(3)
        with f1:
            q_agent = st.text_input("Search agent", placeholder="Agent name or employee ID...", label_visibility="collapsed")
        with f2:
            q_role = st.selectbox("Role", ["All Roles", "Agent", "Admin/Agent", "Admin"], label_visibility="collapsed")
        with f3:
            q_aux = st.selectbox("AUX", ["All AUX"] + AUX_OPTIONS, label_visibility="collapsed")

        # Table rows
        filtered_roster = all_agents
        if q_agent:
            filtered_roster = [a for a in filtered_roster if q_agent.lower() in a.get("name", "").lower() or q_agent.lower() in a.get("employee_id", "").lower()]
        if q_role != "All Roles":
            filtered_roster = [a for a in filtered_roster if a.get("role") == q_role]
        if q_aux != "All AUX":
            filtered_roster = [a for a in filtered_roster if a.get("current_aux") == q_aux]

        for ag in filtered_roster:
            c_r1, c_r2 = st.columns([4, 1])
            with c_r1:
                aux_name = ag.get("current_aux", "Available")
                aux_clr = AUX_COLORS.get(aux_name, "#94A3B8")
                st.markdown(
                    f"""
                    <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between;">
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <img src="{ag.get('photo_url')}" style="width: 38px; height: 38px; border-radius: 50%; object-fit: cover;">
                            <div>
                                <div style="font-weight: 600; font-size: 13px;">{ag.get('name')} <span style="font-size: 11px; color: #64748B;">({ag.get('employee_id')})</span></div>
                                <div style="font-size: 11px; color: #64748B;">Role: {ag.get('role')}</div>
                            </div>
                        </div>
                        <div style="text-align: right;">
                            <div><span class="pill" style="background: {aux_clr}22; color: {aux_clr};">● {aux_name}</span></div>
                            <div style="font-size: 11px; color: #64748B; margin-top: 4px;">Since {ag.get('last_aux_change', '09:00 AM')}</div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            with c_r2:
                if st.button("Inspect", key=f"inspect_{ag.get('employee_id')}"):
                    st.session_state.monitoring_selected_agent = ag.get("employee_id")
                    st.rerun()

    # Detail Side-Panel (Matching Image 1000057261.png right side)
    with col_detail:
        sel_id = st.session_state.monitoring_selected_agent
        sel_ag = db_mgr.find_one({"type": "roster_list", "employee_id": sel_id}) or (all_agents[0] if all_agents else None)

        if sel_ag:
            st.markdown(
                f"""
                <div style="background: white; border: 1px solid #E2E8F0; border-radius: 12px; padding: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.04);">
                    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 16px;">
                        <img src="{sel_ag.get('photo_url')}" style="width: 56px; height: 56px; border-radius: 50%; object-fit: cover;">
                        <div>
                            <h3 style="margin: 0; font-size: 16px;">{sel_ag.get('name')}</h3>
                            <div style="font-size: 12px; color: #64748B;">ID: {sel_ag.get('employee_id')}</div>
                            <span class="pill pill-admin">{sel_ag.get('role')}</span>
                        </div>
                    </div>
                    <div style="font-size: 13px; margin-bottom: 12px;">
                        <strong>Current Status:</strong> <span style="color: {AUX_COLORS.get(sel_ag.get('current_aux', 'Available'))};">● {sel_ag.get('current_aux')}</span>
                        <div style="font-size: 11px; color: #64748B;">Since {sel_ag.get('last_aux_change', '09:00 AM')}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
            st.markdown("<div style='margin-top: 12px;'></div>", unsafe_allow_html=True)
            k_c1, k_c2 = st.columns(2)
            with k_c1:
                st.metric("Active Cases", sel_ag.get("active_cases", 0))
            with k_c2:
                st.metric("Today Assigned", sel_ag.get("today_assigned", 0))

            msg_text = st.text_input("Message to Agent", placeholder="Type immediate message...", key="admin_agent_msg_input")
            b_s1, b_s2 = st.columns(2)
            with b_s1:
                if st.button("Send Message", key="send_popmsg_btn"):
                    if msg_text:
                        db_mgr.insert_one({
                            "type": "notification",
                            "notification_type": "ADMIN_MESSAGE",
                            "recipient_employee_id": sel_ag.get("employee_id"),
                            "title": "Admin Broadcast Message",
                            "message": msg_text,
                            "is_read": False,
                            "created_at": datetime.datetime.now().strftime("%I:%M %p")
                        })
                        st.success(f"Message delivered to {sel_ag.get('name')}.")
            with b_s2:
                if st.button("🚨 Kick / Reset Session", type="secondary", key="kick_user_btn"):
                    db_mgr.update_one({"type": "roster_list", "employee_id": sel_ag.get("employee_id")}, {"$set": {"current_aux": "Not Ready - Online"}})
                    st.warning(f"{sel_ag.get('name')} kicked to Not Ready - Online.")
                    st.rerun()

# ======================================================================================
# 14. SCHEDULE & PTO ALLOCATION (ADMIN & AGENT)
# ======================================================================================
def render_schedule_page():
    """Interactive calendar, PTO allocation summary, leave approvals, and auto-plotting grid."""
    user = st.session_state.current_user
    is_admin = user.get("role") in ["Admin", "Admin/Agent"]
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")

    st.markdown(
        f"""
        <h1 style="font-size: 24px; font-weight: 700; margin: 0; color: #071B2B;">Schedule Management</h1>
        <p style="font-size: 13px; color: #64748B; margin-top: 2px;">
            {'Manage PTO allocation, leaves, and daily team schedule' if is_admin else 'View your weekly timetable, request PTO, or swap schedules'}
        </p>
        """,
        unsafe_allow_html=True
    )

    tab_cal, tab_grid, tab_leave = st.tabs(["📅 Daily Timetable Grid", "🏖️ PTO Allocation & Calendar", "📝 Leave Requests"])

    # TAB 1: 8 AM - 5 PM Hourly Assignment Grid
    with tab_grid:
        st.markdown("### Team Activity Plotter (8:00 AM – 5:00 PM)")
        grid_date = st.date_input("Select Date", value=today, key="grid_date_sel")
        grid_date_str = grid_date.strftime("%Y-%m-%d")

        col_act1, col_act2, col_act3 = st.columns([1.5, 1.5, 4])
        with col_act1:
            if is_admin and st.button("⚡ Auto-Plot Daily Shift", key="auto_plot_btn"):
                # Automatically plot realistic shift coverage
                active_roster = db_mgr.find({"type": "roster_list", "account_status": "Active"})
                for idx, ag in enumerate(active_roster):
                    lunch_start = "12:00 PM" if idx % 2 == 0 else "01:00 PM"
                    lunch_end = "01:00 PM" if idx % 2 == 0 else "02:00 PM"
                    acts = [
                        {"start": "08:00 AM", "end": "10:00 AM", "activity": "Available", "hours": 2},
                        {"start": "10:00 AM", "end": "10:15 AM", "activity": "Break", "hours": 0.25},
                        {"start": "10:15 AM", "end": lunch_start, "activity": "Available", "hours": 1.75},
                        {"start": lunch_start, "end": lunch_end, "activity": "Lunch", "hours": 1},
                        {"start": lunch_end, "end": "03:00 PM", "activity": "Available", "hours": 2},
                        {"start": "03:00 PM", "end": "03:15 PM", "activity": "Break", "hours": 0.25},
                        {"start": "03:15 PM", "end": "05:00 PM", "activity": "Available", "hours": 1.75}
                    ]
                    db_mgr.update_one(
                        {"type": "Schedule_Monitoring", "employee_id": ag["employee_id"], "date": grid_date_str},
                        {"$set": {"activities": acts, "agent_name": ag["name"]}}
                    )
                st.success("Automated staggered schedule successfully plotted!")
                st.rerun()

        # Visual 8 AM - 5 PM Grid
        hours = ["8 AM", "9 AM", "10 AM", "11 AM", "12 PM", "1 PM", "2 PM", "3 PM", "4 PM", "5 PM"]
        sched_records = db_mgr.find({"type": "Schedule_Monitoring", "date": grid_date_str})
        
        if not sched_records:
            st.info("No scheduled shifts plotted for this date. Click 'Auto-Plot Daily Shift' above.")
        else:
            header_cols = st.columns([1.5] + [1]*len(hours))
            header_cols[0].markdown("**Agent**")
            for i, h in enumerate(hours):
                header_cols[i+1].markdown(f"**{h}**")

            for rec in sched_records:
                r_cols = st.columns([1.5] + [1]*len(hours))
                r_cols[0].markdown(f"**{rec.get('agent_name')}**")
                # Fill hours
                for i in range(len(hours)):
                    # Staggered logic representation
                    block_color = COLOR_GREEN
                    block_label = "Avail"
                    if i == 2:
                        block_color = "#94A3B8"
                        block_label = "Brk"
                    elif i == 4:
                        block_color = COLOR_YELLOW
                        block_label = "Lunch"
                    elif i == 7:
                        block_color = "#94A3B8"
                        block_label = "Brk"

                    r_cols[i+1].markdown(
                        f"""
                        <div style="background: {block_color}; color: white; border-radius: 4px; padding: 6px 2px; text-align: center; font-size: 10px; font-weight: 600;">
                            {block_label}
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

    # TAB 2: PTO Calendar & Allocation
    with tab_cal:
        st.markdown("### Monthly PTO Pool Summary")
        pto_doc = db_mgr.find_one({"type": "schedule", "subtype": "pto_allocation"}) or {"total_allocation": 45, "used": 12}
        
        p1, p2, p3 = st.columns(3)
        with p1:
            st.metric("Total PTO Pool (Days)", pto_doc.get("total_allocation", 45))
        with p2:
            st.metric("Booked / Used", pto_doc.get("used", 12))
        with p3:
            remaining = pto_doc.get("total_allocation", 45) - pto_doc.get("used", 12)
            st.metric("Remaining Available", remaining)

        if is_admin:
            with st.expander("⚙️ Set Daily PTO Capacity Limits"):
                new_limit = st.number_input("Maximum simultaneous agents allowed on PTO per day", min_value=1, max_value=10, value=2)
                if st.button("Save Allocation Rules"):
                    st.success("Allocation capacity updated.")

    # TAB 3: Leave Requests & Swaps
    with tab_leave:
        st.markdown("### Submit / Review Leave Requests")
        if not is_admin:
            with st.form("leave_req_form"):
                req_type = st.selectbox("Leave Type", ["PTO", "Sick Leave (Auto-Approved)", "Emergency Leave (Auto-Approved)", "Schedule Swap"])
                req_date = st.date_input("Date", value=today + timedelta(days=2))
                reason = st.text_area("Reason / Target Agent (for Swaps)")
                submit_leave = st.form_submit_button("Submit Request")
                if submit_leave:
                    status = "Auto-Approved" if "Auto" in req_type else "Pending"
                    db_mgr.insert_one({
                        "type": "leave_request",
                        "employee_id": user["employee_id"],
                        "name": user["name"],
                        "leave_type": req_type,
                        "date": req_date.strftime("%Y-%m-%d"),
                        "reason": reason,
                        "status": status,
                        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                    })
                    st.success(f"Leave submitted with status: {status}")
                    st.rerun()

        # Leave List
        l_query = {"type": "leave_request"}
        if not is_admin:
            l_query["employee_id"] = user["employee_id"]
        reqs = db_mgr.find(l_query)
        if not reqs:
            st.info("No leave requests on file.")
        else:
            for r in reqs:
                st.markdown(
                    f"""
                    <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <strong>{r.get('name')}</strong> • {r.get('leave_type')} on <code>{r.get('date')}</code>
                            <div style="font-size: 11px; color: #64748B;">{r.get('reason')}</div>
                        </div>
                        <div>
                            <span class="pill pill-available">{r.get('status')}</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

# ======================================================================================
# 15. REPORTS & ANALYTICS (PLOTLY INTEGRATED)
# ======================================================================================
def render_reports_page():
    """Performance, Breach rate, attendance and schedule adherence analytics."""
    user = st.session_state.current_user
    is_admin = user.get("role") in ["Admin", "Admin/Agent"]

    st.markdown(
        f"""
        <h1 style="font-size: 24px; font-weight: 700; margin: 0; color: #071B2B;">Reports & Performance Analytics</h1>
        <p style="font-size: 13px; color: #64748B; margin-top: 2px;">
            Visualize team performance, case resolution rate, attendance, and schedule adherence
        </p>
        """,
        unsafe_allow_html=True
    )

    r_c1, r_c2 = st.columns([2, 1])
    with r_c1:
        period = st.radio("Reporting Horizon", ["Daily", "WOW", "MTD", "YTD"], horizontal=True)
    with r_c2:
        st.date_input("Date Range", value=(date.today() - timedelta(days=7), date.today()))

    # KPI Summary Row
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.metric("Total Cases Handled", "154", "↑ 8%")
    with k2:
        st.metric("Resolved Cases", "138", "↑ 12%")
    with k3:
        st.metric("Breached SLA", "3", "- 2%")
    with k4:
        st.metric("Adherence Rate", "94.8%", "↑ 1.2%")

    st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)

    # Plotly Charts
    ch1, ch2 = st.columns(2)
    with ch1:
        st.markdown("#### Case Resolution Trend")
        df_trend = pd.DataFrame({
            "Day": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "Resolved": [18, 24, 22, 29, 31, 8, 6],
            "Created": [20, 22, 25, 27, 28, 5, 4]
        })
        fig_trend = px.line(df_trend, x="Day", y=["Resolved", "Created"], color_discrete_sequence=[COLOR_TEAL, COLOR_BLUE])
        fig_trend.update_layout(height=280, margin=dict(l=20, r=20, t=20, b=20), plot_bgcolor="#FFFFFF")
        st.plotly_chart(fig_trend, use_container_width=True)

    with ch2:
        st.markdown("#### Cases by Priority")
        df_prio = pd.DataFrame({
            "Priority": ["Critical", "High", "Medium", "Low"],
            "Count": [12, 34, 58, 50]
        })
        fig_pie = px.pie(df_prio, names="Priority", values="Count", color="Priority",
                         color_discrete_map={"Critical": COLOR_RED, "High": "#F97316", "Medium": COLOR_YELLOW, "Low": COLOR_GREEN},
                         hole=0.45)
        fig_pie.update_layout(height=280, margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig_pie, use_container_width=True)

    # Performance & Adherence Table
    st.markdown("#### Agent Adherence & Attendance Summary")
    df_perf = pd.DataFrame({
        "Agent": ["Maria Santos", "John Dela Cruz", "Daniel Reyes", "Liza Garcia", "Kevin Ramos"],
        "Scheduled Hrs": [40.0, 40.0, 40.0, 40.0, 40.0],
        "Attended Hrs": [39.5, 40.0, 38.8, 39.0, 40.2],
        "Attendance %": ["98.7%", "100%", "97.0%", "97.5%", "100%"],
        "Adherence %": ["96.2%", "94.5%", "93.1%", "95.0%", "98.1%"],
        "Resolved Cases": [28, 31, 24, 19, 36]
    })
    st.dataframe(df_perf, use_container_width=True, hide_index=True)

# ======================================================================================
# 16. SETTINGS & EXTERNAL DATA SOURCES
# ======================================================================================
def render_settings_page():
    """Team management, Role configuration, and External Sources (Excel imports)."""
    user = st.session_state.current_user
    if user.get("role") not in ["Admin", "Admin/Agent"]:
        st.error("Access restricted to Administrators.")
        return

    st.markdown(
        f"""
        <h1 style="font-size: 24px; font-weight: 700; margin: 0; color: #071B2B;">Settings & Configuration</h1>
        <p style="font-size: 13px; color: #64748B; margin-top: 2px;">
            Manage team access, role assignments, audit logs, and external Excel data synchronization
        </p>
        """,
        unsafe_allow_html=True
    )

    t_team, t_ext, t_audit = st.tabs(["👥 Team Management", "📂 External Sources & Excel Sync", "📜 Audit Activity Logs"])

    # TAB 1: Team Roster Management
    with t_team:
        st.markdown("### Team Members")
        with st.expander("➕ Add New User", expanded=False):
            with st.form("new_user_form"):
                c_fn, c_ln, c_id = st.columns(3)
                with c_fn:
                    n_fn = st.text_input("First Name")
                with c_ln:
                    n_ln = st.text_input("Last Name")
                with c_id:
                    n_id = st.text_input("Employee ID")
                n_em = st.text_input("HPE Email")
                n_role = st.selectbox("Role", ["Agent", "Admin/Agent", "Admin"])
                if st.form_submit_button("Create User"):
                    if n_em and n_id and n_fn:
                        db_mgr.insert_one({
                            "type": "roster_list",
                            "first_name": n_fn,
                            "last_name": n_ln,
                            "name": f"{n_fn} {n_ln}",
                            "employee_id": n_id,
                            "email": n_em,
                            "password_hash": db_mgr.hash_password("Hpe@12345"),
                            "role": n_role,
                            "account_status": "Active",
                            "current_aux": "Available",
                            "photo_url": "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150&auto=format&fit=crop&q=80",
                            "active_cases": 0,
                            "today_assigned": 0
                        })
                        st.success(f"User {n_fn} created!")
                        st.rerun()

        # User List
        roster = db_mgr.find({"type": "roster_list"})
        for u in roster:
            col_u1, col_u2 = st.columns([4, 1.5])
            with col_u1:
                st.markdown(
                    f"""
                    <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between;">
                        <div>
                            <strong>{u.get('name')}</strong> ({u.get('employee_id')}) - <code>{u.get('email')}</code>
                            <div style="font-size: 11px; color: #64748B;">Role: <strong>{u.get('role')}</strong> • Status: {u.get('account_status')}</div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            with col_u2:
                new_r = st.selectbox("Edit Role", ["Agent", "Admin/Agent", "Admin"], index=["Agent", "Admin/Agent", "Admin"].index(u.get("role", "Agent")), key=f"role_sel_{u.get('employee_id')}")
                if new_r != u.get("role"):
                    db_mgr.update_one({"employee_id": u.get("employee_id")}, {"$set": {"role": new_r}})
                    st.rerun()

    # TAB 2: External Sources & Excel Import
    with t_ext:
        st.markdown("### External Data Synchronization")
        st.caption("Upload Excel files (.xlsx) to bulk synchronize vendor directories or case backlogs.")

        u_col1, u_col2 = st.columns(2)
        with u_col1:
            st.markdown("#### Vendor Database Sync")
            v_file = st.file_uploader("Upload Vendor Excel", type=["xlsx", "xls"], key="vendor_upload")
            if v_file:
                try:
                    df_v = pd.read_excel(v_file)
                    st.dataframe(df_v.head(3), use_container_width=True)
                    if st.button("Sync Vendor Data to MongoDB"):
                        for _, row in df_v.iterrows():
                            db_mgr.insert_one({
                                "type": "vendor",
                                "vendor_name": str(row.get("Vendor Name", "Unknown")),
                                "primary_contact": str(row.get("Primary Contact", "N/A")),
                                "email": str(row.get("Email", "support@vendor.com")),
                                "phone": str(row.get("Phone", "N/A")),
                                "status": "Active"
                            })
                        st.success("Vendor records successfully synced!")
                except Exception as e:
                    st.error(f"Error parsing Excel file: {e}")

        with u_col2:
            st.markdown("#### Case Batch Import")
            c_file = st.file_uploader("Upload Case Excel", type=["xlsx", "xls"], key="case_upload")
            if c_file:
                try:
                    df_c = pd.read_excel(c_file)
                    st.dataframe(df_c.head(3), use_container_width=True)
                    if st.button("Import & Auto-Assign Cases"):
                        for _, row in df_c.iterrows():
                            c_num = f"HC-2026-{1000 + int(time.time() % 9000)}"
                            db_mgr.insert_one({
                                "type": "case",
                                "case_number": c_num,
                                "subject": str(row.get("Subject", "Imported Issue")),
                                "description": str(row.get("Description", "Imported from batch file.")),
                                "priority": str(row.get("Priority", "Medium")),
                                "due_date": f"{date.today()} 05:00 PM",
                                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p"),
                                "last_update": datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p"),
                                "status": "Open",
                                "is_closed": False
                            })
                            auto_assign_case(c_num)
                        st.success("Cases imported and passed through assignment engine!")
                except Exception as e:
                    st.error(f"Error importing cases: {e}")

    # TAB 3: Audit Activity Logs
    with t_audit:
        st.markdown("### System Security & Activity Logs")
        logs = db_mgr.find({"type": "account_activity"}, sort_key="timestamp", ascending=False)
        if not logs:
            st.info("No security logs recorded.")
        else:
            df_logs = pd.DataFrame(logs)
            st.dataframe(df_logs[["timestamp", "user", "activity", "details"]], use_container_width=True, hide_index=True)

# ======================================================================================
# 17. MAIN APPLICATION DISPATCHER
# ======================================================================================
def main():
    if not st.session_state.authenticated or st.session_state.current_user is None:
        render_auth_page()
        return

    # Check connection health (non-blocking notification)
    if not db_mgr.is_connected:
        st.markdown(
            f"""
            <div style="background: #FEF3C7; border-left: 4px solid {COLOR_YELLOW}; padding: 6px 12px; font-size: 11px; margin-bottom: 8px; border-radius: 4px;">
                <strong>Demo Mode Active:</strong> Operating with in-memory persistence. To connect MongoDB, set <code>MONGO_URI</code> in environment or Streamlit secrets.
            </div>
            """,
            unsafe_allow_html=True
        )

    # Render Persistent Navigation & Shell
    render_top_header()
    render_sidebar()

    # Active Overlays / Modals
    if st.session_state.active_modal == "profile":
        render_profile_modal()
    elif st.session_state.active_modal == "notifications":
        render_notification_center()

    # Page Routing
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
