import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import hashlib
import os
import uuid
import json
import re
from typing import Optional, Dict, Any, List

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
HPE_THEME_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        color: #0B2341;
        background-color: #F4F7F9;
    }
    
    /* Clean up default Streamlit chrome */
    #MainMenu, header, footer { visibility: hidden !important; }
    .block-container {
        padding-top: 0.8rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1.8rem !important;
        padding-right: 1.8rem !important;
    }
    
    /* Card Styles */
    .hpe-card {
        background: #FFFFFF;
        border-radius: 10px;
        padding: 1.25rem;
        border: 1px solid #E2E8F0;
        box-shadow: 0 2px 6px rgba(11, 35, 65, 0.04);
        margin-bottom: 1rem;
    }
    
    /* Top Metric KPI Cards */
    .metric-box {
        background: #FFFFFF;
        border-radius: 12px;
        padding: 1.2rem;
        border: 1px solid #E2E8F0;
        box-shadow: 0 2px 6px rgba(0,0,0,0.03);
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .metric-number {
        font-size: 2.2rem;
        font-weight: 800;
        line-height: 1.1;
        color: #0B2341;
    }
    .metric-label {
        font-size: 0.85rem;
        font-weight: 700;
        color: #4A5568;
        margin-top: 4px;
    }
    .metric-sub {
        font-size: 0.75rem;
        font-weight: 600;
        margin-top: 4px;
    }

    /* Badges & Status Pills */
    .badge {
        display: inline-block;
        padding: 0.25rem 0.7rem;
        font-size: 0.75rem;
        font-weight: 600;
        border-radius: 20px;
        text-align: center;
    }
    .badge-available { background-color: #E6F6F2; color: #01A982; }
    .badge-adminwork { background-color: #E5F3F8; color: #00739D; }
    .badge-notreadyonline { background-color: #FCEBE8; color: #DE3618; }
    .badge-coaching { background-color: #F5EBF7; color: #763082; }
    .badge-meeting { background-color: #FFF6E6; color: #FFAA15; }
    .badge-lunch { background-color: #FFFDE6; color: #B38600; }
    .badge-break { background-color: #EFF1F3; color: #616D75; }
    .badge-training { background-color: #E0E7FF; color: #4338CA; }
    .badge-pto { background-color: #FFE4E6; color: #E11D48; }
    .badge-sick { background-color: #EDE9FE; color: #6D28D9; }
    .badge-emergency { background-color: #FFEDD5; color: #C2410C; }
    
    .badge-critical { background-color: #FCEBE8; color: #DE3618; font-weight: 700; }
    .badge-high { background-color: #FFF0E6; color: #E26815; font-weight: 600; }
    .badge-medium { background-color: #FFFBE6; color: #B38600; }
    .badge-low { background-color: #EBF8F2; color: #01A982; }
    
    .badge-open { background-color: #E9ECEF; color: #495057; }
    .badge-inprogress { background-color: #E5F3F8; color: #00739D; }
    .badge-onhold { background-color: #FFF6E6; color: #FFAA15; }
    .badge-pendingvendor { background-color: #FFFBE6; color: #B38600; }
    .badge-resolved { background-color: #D1E7DD; color: #0F5132; }
    .badge-breached { background-color: #FCEBE8; color: #DE3618; font-weight: 700; }

    /* Custom Buttons */
    .stButton>button {
        border-radius: 6px;
        font-weight: 600;
        transition: all 0.2s ease-in-out;
    }
    .stButton>button:hover {
        border-color: #01A982;
        color: #01A982;
    }
</style>
"""
st.markdown(HPE_THEME_CSS, unsafe_allow_html=True)

# ==============================================================================
# 2. SECURITY & PASSWORD MANAGEMENT (Salted PBKDF2-SHA256)
# ==============================================================================
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return f"{salt.hex()}${key.hex()}"

def verify_password(stored_password: str, provided_password: str) -> bool:
    try:
        if not stored_password or '$' not in stored_password:
            return False
        salt_hex, key_hex = stored_password.split('$')
        salt = bytes.fromhex(salt_hex)
        key = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'), salt, 100000)
        return key.hex() == key_hex
    except Exception:
        return False

# ==============================================================================
# 3. DATABASE REPOSITORY LAYER (MongoDB with Auto-Seeding)
# ==============================================================================
AUX_STATUSES = [
    "Available", "Admin Work", "Not Ready - Online", 
    "Coaching", "Meeting", "Lunch", "Break", "Unscheduled Break"
]

AUX_COLORS = {
    "Available": "#01A982",
    "Admin Work": "#00739D",
    "Not Ready - Online": "#DE3618",
    "Coaching": "#763082",
    "Meeting": "#FFAA15",
    "Lunch": "#B38600",
    "Break": "#616D75",
    "Unscheduled Break": "#495057"
}

@st.cache_resource
def get_mongo_client():
    from pymongo import MongoClient
    mongo_uri = os.environ.get("MONGO_URI") or st.secrets.get("mongo_uri", None)
    if not mongo_uri:
        return None
    try:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
        client.admin.command('ping')
        return client
    except Exception:
        return None

class DatabaseManager:
    """Manages all persistent operations strictly across MongoDB collections."""
    def __init__(self):
        self.client = get_mongo_client()
        self.db = None
        self.collection = None
        if self.client:
            self.db = self.client["TeamRoster"]
            self.collection = self.db["Team Roster Collection"]
            self._seed_reference_data_if_empty()

    def is_connected(self) -> bool:
        if not self.client:
            self.client = get_mongo_client()
            if self.client:
                self.db = self.client["TeamRoster"]
                self.collection = self.db["Team Roster Collection"]
                self._seed_reference_data_if_empty()
        return self.client is not None

    def _seed_reference_data_if_empty(self):
        """Populates MongoDB on first run so the UI matches the reference screenshots [source: 5, 8, 11, 14, 17, 18]."""
        if not self.collection:
            return
        
        # 1. Seed Cases
        if self.collection.count_documents({"type": "case_record"}) == 0:
            seed_cases = [
                {
                    "case_id": "HC-2026-1044",
                    "subject": "License Renewal Delay",
                    "priority": "Critical",
                    "assigned_to": "john.delacruz@hpe.com",
                    "status": "On Hold",
                    "case_type": "License Renewal",
                    "account": "ABC Enterprise",
                    "client": "ABC Enterprise",
                    "related_system": "HPE Licensing Portal",
                    "vendor": "ABC Software Inc.",
                    "created_date": "Sep 27, 2026 03:15 PM",
                    "due_date": "Sep 28, 2026 11:00 AM",
                    "last_update": "Sep 28, 2026 08:45 AM (0.7h ago)",
                    "hours": "0.7h",
                    "description": "Client is experiencing delay in license renewal. Vendor confirmation is still pending. Need follow up and escalation if no response by EOD."
                },
                {
                    "case_id": "HC-2026-1045",
                    "subject": "Portal Access Issue",
                    "priority": "Critical",
                    "assigned_to": "maria.santos@hpe.com",
                    "status": "In Progress",
                    "case_type": "Access Provisioning",
                    "account": "Global Health Partners",
                    "client": "Global Health Partners",
                    "related_system": "Compute Platform Ops",
                    "vendor": "Intel Xeon Platform Support",
                    "created_date": "Sep 27, 2026 04:00 PM",
                    "due_date": "Sep 28, 2026 10:30 AM",
                    "last_update": "Sep 28, 2026 08:15 AM",
                    "hours": "1.2h",
                    "description": "Enterprise customer administrator unable to login to provisioning interface."
                },
                {
                    "case_id": "HC-2026-1043",
                    "subject": "Installation Error",
                    "priority": "High",
                    "assigned_to": "kevin.ramos@hpe.com",
                    "status": "In Progress",
                    "case_type": "Software",
                    "account": "FinTech Core Corp",
                    "client": "FinTech Core Corp",
                    "related_system": "HPE StoreOnce Catalyst",
                    "vendor": "Samsung Semiconductor",
                    "created_date": "Sep 27, 2026 05:00 PM",
                    "due_date": "Sep 28, 2026 02:00 PM",
                    "last_update": "Sep 28, 2026 09:00 AM",
                    "hours": "0.5h",
                    "description": "Error during deployment of cluster telemetry service."
                },
                {
                    "case_id": "HC-2026-1042",
                    "subject": "Vendor Confirmation",
                    "priority": "High",
                    "assigned_to": "liza.garcia@hpe.com",
                    "status": "Open",
                    "case_type": "Vendor Escalation",
                    "account": "Retail Supermarkets Group",
                    "client": "Retail Supermarkets Group",
                    "related_system": "CX 6300M Series",
                    "vendor": "Brocade SAN Networking",
                    "created_date": "Sep 28, 2026 08:00 AM",
                    "due_date": "Sep 28, 2026 04:00 PM",
                    "last_update": "Sep 28, 2026 08:55 AM",
                    "hours": "0.6h",
                    "description": "Awaiting vendor sign-off on RMA shipment."
                },
                {
                    "case_id": "HC-2026-1041",
                    "subject": "Software Licensing",
                    "priority": "Medium",
                    "assigned_to": "mark.tan@hpe.com",
                    "status": "In Progress",
                    "case_type": "License Allocation",
                    "account": "Nordic Telco",
                    "client": "Nordic Telco",
                    "related_system": "Alletra MP Block Storage",
                    "vendor": "ABC Software Inc.",
                    "created_date": "Sep 28, 2026 07:30 AM",
                    "due_date": "Sep 29, 2026 10:00 AM",
                    "last_update": "Sep 28, 2026 08:20 AM",
                    "hours": "2.1h",
                    "description": "Capacity license key mismatch after node migration."
                }
            ]
            for c in seed_cases:
                self.collection.insert_one({"type": "case_record", "case": c})

        # 2. Seed Vendors
        if self.collection.count_documents({"type": "vendor_data"}) == 0:
            seed_vendors = [
                {
                    "name": "Tech Solutions Inc.",
                    "contact": "Mark Reynolds",
                    "email": "mark.reynolds@techsolutions.com",
                    "phone": "+1 555 123 4567",
                    "category": "Software",
                    "status": "Active",
                    "last_updated": "Sep 28, 2026 09:10 AM"
                },
                {
                    "name": "Global Systems Ltd.",
                    "contact": "Angela White",
                    "email": "angela.white@globalsystems.com",
                    "phone": "+1 555 234 5678",
                    "category": "Hardware",
                    "status": "Active",
                    "last_updated": "Sep 28, 2026 09:10 AM"
                },
                {
                    "name": "CloudServe Corp.",
                    "contact": "Daniel Kim",
                    "email": "daniel.kim@cloudserve.com",
                    "phone": "+1 555 345 6789",
                    "category": "Cloud Services",
                    "status": "Active",
                    "last_updated": "Sep 28, 2026 09:10 AM"
                },
                {
                    "name": "NetConnect",
                    "contact": "Sophia Lee",
                    "email": "sophia.lee@netconnect.com",
                    "phone": "+1 555 456 7890",
                    "category": "Network",
                    "status": "Active",
                    "last_updated": "Sep 28, 2026 09:10 AM"
                },
                {
                    "name": "DataPro Solutions",
                    "contact": "Michael Torres",
                    "email": "michael.torres@datapro.com",
                    "phone": "+1 555 567 8901",
                    "category": "Data Management",
                    "status": "Active",
                    "last_updated": "Sep 28, 2026 09:10 AM"
                }
            ]
            for v in seed_vendors:
                self.collection.insert_one({"type": "vendor_data", "vendor": v})

        # 3. Seed Dropdowns
        if self.collection.count_documents({"type": "Validation_Dropdown"}) == 0:
            self.collection.insert_one({
                "type": "Validation_Dropdown",
                "Case_Status": ["Open", "In Progress", "On Hold", "Pending Vendor", "Pending Internal", "Resolved", "Closed"],
                "Status_Reason": ["Waiting for Vendor Response", "Customer Verification", "Investigation in Progress", "Spare Part Dispatched"],
                "Closure_Type": ["Resolved - Normal", "Resolved - Workaround", "Contract Breach", "Cancelled by Customer"],
                "Contract_Breach": ["Vendor No Response", "Late Delivery", "Incomplete Information", "Scope Change", "Hardware Unavailability"]
            })

    # --- User Helpers with Safe Fallback for 'hpe_email' and 'email' ---
    def find_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        if not self.is_connected() or not email:
            return None
        doc = self.collection.find_one({
            "type": "roster_list",
            "$or": [
                {"roster_list.hpe_email": {"$regex": f"^{re.escape(email.strip())}$", "$options": "i"}},
                {"roster_list.email": {"$regex": f"^{re.escape(email.strip())}$", "$options": "i"}}
            ]
        })
        return doc.get("roster_list") if doc else None

    def find_user_by_employee_id(self, emp_id: str) -> Optional[Dict[str, Any]]:
        if not self.is_connected() or not emp_id:
            return None
        doc = self.collection.find_one({
            "type": "roster_list",
            "roster_list.employee_id": emp_id.strip()
        })
        return doc.get("roster_list") if doc else None

    def create_user(self, user_data: Dict[str, Any]) -> bool:
        if not self.is_connected():
            return False
        self.collection.insert_one({
            "type": "roster_list",
            "roster_list": user_data
        })
        self.log_audit(user_data.get("hpe_email") or user_data.get("email", ""), "User Registration", f"Account created as {user_data.get('role')}")
        return True

    def get_all_roster_users(self) -> List[Dict[str, Any]]:
        if not self.is_connected():
            return []
        cursor = self.collection.find({"type": "roster_list"})
        users = []
        for doc in cursor:
            if "roster_list" in doc:
                u = doc["roster_list"]
                if "hpe_email" not in u and "email" in u:
                    u["hpe_email"] = u["email"]
                users.append(u)
        return users

    def update_user_field(self, email: str, fields: Dict[str, Any]):
        if not self.is_connected() or not email:
            return
        update_doc = {f"roster_list.{k}": v for k, v in fields.items()}
        update_doc["roster_list.updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.collection.update_one(
            {
                "type": "roster_list",
                "$or": [
                    {"roster_list.hpe_email": {"$regex": f"^{re.escape(email.strip())}$", "$options": "i"}},
                    {"roster_list.email": {"$regex": f"^{re.escape(email.strip())}$", "$options": "i"}}
                ]
            },
            {"$set": update_doc}
        )

    def update_user_aux(self, email: str, new_aux: str):
        if not self.is_connected() or not email:
            return
        ts = datetime.now().strftime("%I:%M %p")
        self.update_user_field(email, {"current_aux": new_aux, "aux_since": ts})
        self.collection.insert_one({
            "type": "aux_history",
            "email": email,
            "aux": new_aux,
            "timestamp": datetime.now().strftime("%Y-%m-%d %I:%M %p")
        })
        self.log_audit(email, "Aux Changed", f"Changed status to {new_aux}")

    # --- Cases Operations ---
    def get_cases(self) -> List[Dict[str, Any]]:
        if not self.is_connected():
            return []
        cursor = self.collection.find({"type": "case_record"}).sort("case.created_date", -1)
        return [doc["case"] for doc in cursor if "case" in doc]

    def get_case_by_id(self, case_id: str) -> Optional[Dict[str, Any]]:
        if not self.is_connected() or not case_id:
            return None
        doc = self.collection.find_one({"type": "case_record", "case.case_id": case_id})
        return doc.get("case") if doc else None

    def insert_case(self, case_data: Dict[str, Any]):
        if not self.is_connected():
            return
        self.collection.insert_one({"type": "case_record", "case": case_data})
        self.log_case_history(case_data["case_id"], "SYSTEM", "Case Created", "Case ingested into HPE CaseFlow")

    def update_case(self, case_id: str, updates: Dict[str, Any], actor: str):
        if not self.is_connected() or not case_id:
            return
        update_doc = {f"case.{k}": v for k, v in updates.items()}
        update_doc["case.last_update"] = datetime.now().strftime("%b %d, %Y %I:%M %p")
        self.collection.update_one(
            {"type": "case_record", "case.case_id": case_id},
            {"$set": update_doc}
        )
        self.log_case_history(case_id, actor, "Case Updated", json.dumps(updates))

    def log_case_history(self, case_id: str, user: str, action: str, details: str):
        if not self.is_connected():
            return
        self.collection.insert_one({
            "type": "case_history",
            "case_id": case_id,
            "user": user,
            "action": action,
            "details": details,
            "timestamp": datetime.now().strftime("%b %d, %Y %I:%M %p")
        })

    def get_case_history(self, case_id: str) -> List[Dict[str, Any]]:
        if not self.is_connected():
            return []
        cursor = self.collection.find({"type": "case_history", "case_id": case_id}).sort("timestamp", -1)
        return list(cursor)

    # --- Leave, PTO & Scheduling ---
    def get_leave_requests(self) -> List[Dict[str, Any]]:
        if not self.is_connected():
            return [
                {"name": "Juan Dela Cruz", "type": "PTO", "dates": "Sep 14, 2026", "status": "Approved"},
                {"name": "Maria Santos", "type": "Sick Leave", "dates": "Sep 16, 2026", "status": "Auto-Approved"},
                {"name": "Leo Ramirez", "type": "Emergency Leave", "dates": "Sep 18, 2026", "status": "Auto-Approved"},
                {"name": "Ana Torres", "type": "PTO", "dates": "Sep 24-25, 2026", "status": "Approved"},
                {"name": "Mark Villanueva", "type": "Sick Leave", "dates": "Sep 28, 2026", "status": "Auto-Approved"}
            ]
        cursor = self.collection.find({"type": "leave_request"}).sort("created_at", -1)
        res = list(cursor)
        if not res:
            return [
                {"name": "Juan Dela Cruz", "type": "PTO", "dates": "Sep 14, 2026", "status": "Approved"},
                {"name": "Maria Santos", "type": "Sick Leave", "dates": "Sep 16, 2026", "status": "Auto-Approved"},
                {"name": "Leo Ramirez", "type": "Emergency Leave", "dates": "Sep 18, 2026", "status": "Auto-Approved"},
                {"name": "Ana Torres", "type": "PTO", "dates": "Sep 24-25, 2026", "status": "Approved"},
                {"name": "Mark Villanueva", "type": "Sick Leave", "dates": "Sep 28, 2026", "status": "Auto-Approved"}
            ]
        return res

    def insert_leave_request(self, req: Dict[str, Any]):
        if not self.is_connected():
            return
        req["type"] = "leave_request"
        req["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.collection.insert_one(req)

    # --- Vendors & Dropdowns ---
    def get_vendors(self) -> List[Dict[str, Any]]:
        if not self.is_connected():
            return []
        cursor = self.collection.find({"type": "vendor_data"})
        return [doc["vendor"] for doc in cursor if "vendor" in doc]

    def get_dropdowns(self) -> Dict[str, List[str]]:
        if not self.is_connected():
            return {
                "Case_Status": ["Open", "In Progress", "On Hold", "Pending Vendor", "Resolved", "Closed"],
                "Status_Reason": ["Waiting for Vendor Response", "Customer Verification", "Investigation in Progress"],
                "Closure_Type": ["Resolved - Normal", "Resolved - Workaround", "Contract Breach"],
                "Contract_Breach": ["Vendor No Response", "Late Delivery", "Incomplete Information"]
            }
        doc = self.collection.find_one({"type": "Validation_Dropdown"})
        return doc if doc else {}

    # --- Notifications & Auditing ---
    def get_notifications(self, email: str, is_admin: bool) -> List[Dict[str, Any]]:
        if not self.is_connected() or not email:
            return []
        q = {"type": "notification"}
        if not is_admin:
            q["$or"] = [{"recipient": email}, {"recipient": "ALL"}]
        cursor = self.collection.find(q).sort("timestamp", -1).limit(10)
        return list(cursor)

    def add_notification(self, recipient: str, title: str, text: str, notif_type: str = "General", case_id: Optional[str] = None):
        if not self.is_connected():
            return
        self.collection.insert_one({
            "type": "notification",
            "notif_id": f"notif-{uuid.uuid4().hex[:6]}",
            "recipient": recipient,
            "title": title,
            "text": text,
            "notif_type": notif_type,
            "case_id": case_id,
            "read": False,
            "timestamp": datetime.now().strftime("%b %d, %I:%M %p")
        })

    def mark_notifications_read(self, email: str):
        if not self.is_connected() or not email:
            return
        self.collection.update_many(
            {"type": "notification", "$or": [{"recipient": email}, {"recipient": "ALL"}]},
            {"$set": {"read": True}}
        )

    def log_audit(self, user: str, activity: str, details: str):
        if not self.is_connected():
            return
        self.collection.insert_one({
            "type": "audit_log",
            "timestamp": datetime.now().strftime("%b %d, %Y %I:%M %p"),
            "user": user,
            "activity": activity,
            "details": details
        })

    def get_audit_logs(self) -> List[Dict[str, Any]]:
        if not self.is_connected():
            return [
                {"timestamp": "Sep 28, 2026 08:32 AM", "activity": "Login", "details": "Successful login"},
                {"timestamp": "Sep 27, 2026 05:12 PM", "activity": "Aux Change", "details": "Changed to Admin Work"},
                {"timestamp": "Sep 27, 2026 01:45 PM", "activity": "Case Update", "details": "Updated status for case #HC-1023"}
            ]
        cursor = self.collection.find({"type": "audit_log"}).sort("timestamp", -1).limit(20)
        res = list(cursor)
        if not res:
            return [
                {"timestamp": "Sep 28, 2026 08:32 AM", "activity": "Login", "details": "Successful login"},
                {"timestamp": "Sep 27, 2026 05:12 PM", "activity": "Aux Change", "details": "Changed to Admin Work"},
                {"timestamp": "Sep 27, 2026 01:45 PM", "activity": "Case Update", "details": "Updated status for case #HC-1023"}
            ]
        return res

db_mgr = DatabaseManager()

# ==============================================================================
# 4. MODAL DIALOGS (ALL 9 SPECIFIED SCENARIOS IN REFERENCE 19)
# ==============================================================================
@st.dialog("1. New Case Assigned to You")
def dlg_new_case(case_id="CAS-2026-0918-0045", subj="Vendor API Access Issue", prio="High", due="Sep 18, 2026 04:00 PM"):
    st.markdown("📁 **A new case has been automatically assigned to you.**")
    st.markdown(f"**Case #:** `{case_id}`")
    st.markdown(f"**Subject:** {subj}")
    st.markdown(f"**Priority:** <span class='badge badge-{prio.lower()}'>{prio}</span>", unsafe_allow_html=True)
    st.markdown(f"**Due Date:** {due}")
    c1, c2 = st.columns(2)
    if c1.button("View Case", type="primary", use_container_width=True, key="nc_v"):
        st.session_state["selected_case_id"] = case_id
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c2.button("OK", use_container_width=True, key="nc_ok"):
        st.rerun()

@st.dialog("2. Case Reassigned to You")
def dlg_case_reassigned(case_id="CAS-2026-0918-0032", subj="License Key Renewal", prio="Medium", due="Sep 19, 2026 10:00 AM", sender="Mark Dela Cruz"):
    st.markdown("👥 **A case has been reassigned to you by the administrator.**")
    st.markdown(f"**Case #:** `{case_id}`")
    st.markdown(f"**Subject:** {subj}")
    st.markdown(f"**Priority:** <span class='badge badge-{prio.lower()}'>{prio}</span>", unsafe_allow_html=True)
    st.markdown(f"**Due Date:** {due}")
    st.markdown(f"**From:** `{sender}`")
    c1, c2 = st.columns(2)
    if c1.button("View Case", type="primary", use_container_width=True, key="cr_v"):
        st.session_state["selected_case_id"] = case_id
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c2.button("OK", use_container_width=True, key="cr_ok"):
        st.rerun()

@st.dialog("3. Case Transfer Request Received")
def dlg_transfer_request(case_id="CAS-2026-0917-0061", subj="Portal Access Issue", prio="Medium", due="Sep 19, 2026 02:00 PM", requester="John Reyes"):
    st.markdown(f"⇄ **{requester} has requested to transfer a case to you.**")
    st.markdown(f"**Case #:** `{case_id}`")
    st.markdown(f"**Subject:** {subj}")
    st.markdown(f"**Priority:** <span class='badge badge-{prio.lower()}'>{prio}</span>", unsafe_allow_html=True)
    st.markdown(f"**Due Date:** {due}")
    st.markdown(f"**From:** `{requester}`")
    c1, c2, c3 = st.columns(3)
    if c1.button("Decline", use_container_width=True, key="tr_d"):
        st.warning("Transfer request declined.")
        st.rerun()
    if c2.button("View Case", use_container_width=True, key="tr_v"):
        st.session_state["selected_case_id"] = case_id
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c3.button("Approve", type="primary", use_container_width=True, key="tr_a"):
        user_email = st.session_state["auth_user"].get("hpe_email") or st.session_state["auth_user"].get("email")
        db_mgr.update_case(case_id, {"assigned_to": user_email}, user_email)
        st.success("Case successfully transferred.")
        st.rerun()

@st.dialog("4. Schedule Swap Request")
def dlg_schedule_swap_request(requester="Amanda Santos", shift_date="Sep 22, 2026 (Tuesday)", curr_sched="Morning Shift (8:00 AM – 5:00 PM)", req_sched="Afternoon Shift (12:00 PM – 9:00 PM)"):
    st.markdown(f"📅 **{requester} has requested to swap schedule with you.**")
    st.markdown(f"**Date:** `{shift_date}`")
    st.markdown(f"**Your Current Schedule:** `{curr_sched}`")
    st.markdown(f"**Requester's Schedule:** `{req_sched}`")
    c1, c2, c3 = st.columns(3)
    if c1.button("Decline", use_container_width=True, key="sw_d"):
        st.warning("Schedule swap declined.")
        st.rerun()
    if c2.button("View Details", use_container_width=True, key="sw_v"):
        st.session_state["active_nav"] = "Schedule"
        st.rerun()
    if c3.button("Approve", type="primary", use_container_width=True, key="sw_a"):
        st.success("Schedule swap confirmed.")
        st.rerun()

@st.dialog("5. Schedule Swap Approved")
def dlg_schedule_swap_approved(requester="Amanda Santos", shift_date="Sep 22, 2026 (Tuesday)", new_sched="Afternoon Shift (12:00 PM – 9:00 PM)"):
    st.markdown(f"✓ **Your schedule swap request with {requester} has been approved.**")
    st.markdown(f"**Date:** `{shift_date}`")
    st.markdown(f"**Your New Schedule:** `{new_sched}`")
    if st.button("OK", type="primary", use_container_width=True):
        st.rerun()

@st.dialog("6. Schedule Swap Declined")
def dlg_schedule_swap_declined(requester="Amanda Santos", shift_date="Sep 22, 2026 (Tuesday)", reason="Schedule conflict"):
    st.markdown(f"❌ **{requester} has declined your schedule swap request.**")
    st.markdown(f"**Date:** `{shift_date}`")
    st.markdown(f"**Reason:** {reason}")
    if st.button("OK", type="primary", use_container_width=True):
        st.rerun()

@st.dialog("7. Critical Case Alert")
def dlg_critical_case_alert(case_id="CAS-2026-0918-0008", subj="Vendor Delivery Delay", due_in="30 minutes (Sep 18, 2026 03:00 PM)"):
    st.markdown("⚠️ **A case is nearing its due date and is still not resolved or closed.**")
    st.markdown(f"**Case #:** `{case_id}`")
    st.markdown(f"**Subject:** {subj}")
    st.markdown(f"**Priority:** <span class='badge badge-critical'>Critical</span>", unsafe_allow_html=True)
    st.markdown(f"**Due In:** <strong style='color: #DE3618;'>{due_in}</strong>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if c1.button("View Case", type="primary", use_container_width=True, key="cca_v"):
        st.session_state["selected_case_id"] = case_id
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c2.button("OK", use_container_width=True, key="cca_ok"):
        st.rerun()

@st.dialog("8. Critical Case Past Due")
def dlg_critical_past_due(case_id="CAS-2026-0917-0021", subj="Contract Renewal Issue", due="Sep 17, 2026 05:00 PM", status="Still Open"):
    st.markdown("🚨 **This case is now past due and has not been resolved.**")
    st.markdown(f"**Case #:** `{case_id}`")
    st.markdown(f"**Subject:** {subj}")
    st.markdown(f"**Priority:** <span class='badge badge-critical'>Critical</span>", unsafe_allow_html=True)
    st.markdown(f"**Due Date:** `{due}`")
    st.markdown(f"**Status:** <strong style='color: #DE3618;'>{status}</strong>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if c1.button("View Case", type="primary", use_container_width=True, key="cpd_v"):
        st.session_state["selected_case_id"] = case_id
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c2.button("OK", use_container_width=True, key="cpd_ok"):
        st.rerun()

@st.dialog("9. Message from Admin")
def dlg_admin_broadcast(msg="Hi Team,\n\nPlease prioritize all critical cases for today. Let me know if you need any assistance.\n\nThank you!", sender="Admin", ts="Sep 18, 2026 10:30 AM"):
    st.markdown(f"✉️ **Message from {sender}**")
    st.info(msg)
    st.caption(f"From: {sender} | {ts}")
    if st.button("OK", type="primary", use_container_width=True):
        st.rerun()

# ==============================================================================
# 5. AUTHENTICATION MODULE (Sign-In & Sign-Up Matching Image 1)
# ==============================================================================
def render_auth_page():
    if not db_mgr.is_connected():
        st.error("Unable to connect to the authentication service. Please verify your MongoDB configuration.")
        st.caption("Enterprise Security Policy: Authentication bypass is strictly prohibited.")
        return

    col_brand, col_form = st.columns([1.1, 1], gap="large")
    
    with col_brand:
        st.markdown(
            """
            <div style="background: linear-gradient(180deg, #001A2C 0%, #0B2341 70%, #01A982 100%); padding: 3rem 2.5rem; border-radius: 12px; color: white; min-height: 580px;">
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 2rem;">
                    <div style="background-color: #01A982; width: 14px; height: 32px; border-radius: 2px;"></div>
                    <div>
                        <div style="font-size: 1.1rem; font-weight: 700; line-height: 1;">Hewlett Packard</div>
                        <div style="font-size: 0.95rem; font-weight: 400; color: #E2E8F0;">Enterprise</div>
                    </div>
                </div>
                <h1 style="color: white; font-size: 2.8rem; margin: 0; font-weight: 800; line-height: 1.1;">HPE</h1>
                <h1 style="color: #00C785; font-size: 2.8rem; margin: 0 0 0.5rem 0; font-weight: 800; line-height: 1.1;">CaseFlow</h1>
                <p style="font-size: 1.05rem; color: #A0B2C6; margin-bottom: 3rem;">Team Task and Case Management System</p>
                <div style="margin-bottom: 1.8rem; display: flex; align-items: center; gap: 16px;">
                    <div style="background: rgba(1, 169, 130, 0.15); border: 2px solid #01A982; min-width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.2rem;">📁</div>
                    <div>
                        <div style="font-size: 1.05rem; font-weight: 700;">Manage Cases</div>
                        <div style="font-size: 0.85rem; color: #CBD5E1;">Track and resolve tasks efficiently</div>
                    </div>
                </div>
                <div style="margin-bottom: 1.8rem; display: flex; align-items: center; gap: 16px;">
                    <div style="background: rgba(0, 115, 157, 0.15); border: 2px solid #00739D; min-width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.2rem;">👥</div>
                    <div>
                        <div style="font-size: 1.05rem; font-weight: 700;">Work Together</div>
                        <div style="font-size: 0.85rem; color: #CBD5E1;">Stay aligned with your team</div>
                    </div>
                </div>
                <div style="margin-bottom: 1.8rem; display: flex; align-items: center; gap: 16px;">
                    <div style="background: rgba(1, 169, 130, 0.15); border: 2px solid #01A982; min-width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.2rem;">📊</div>
                    <div>
                        <div style="font-size: 1.05rem; font-weight: 700;">Drive Results</div>
                        <div style="font-size: 0.85rem; color: #CBD5E1;">Real-time insights and reporting</div>
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
                email = st.text_input("HPE Email Address", placeholder="yourname@hpe.com")
                pwd = st.text_input("Password", type="password", placeholder="Enter your password")
                
                c_rem, c_fgt = st.columns([1, 1])
                c_rem.checkbox("Remember me", value=True)
                
                submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)
                if submitted:
                    if not email or not pwd:
                        st.error("Please enter your HPE email and password.")
                    else:
                        user = db_mgr.find_user_by_email(email)
                        if user and verify_password(user.get("password_hash", ""), pwd):
                            if user.get("account_status") != "Active":
                                st.error("This account is currently deactivated. Contact your supervisor.")
                            else:
                                user_email = user.get("hpe_email") or user.get("email")
                                db_mgr.update_user_field(user_email, {
                                    "login_status": "Online",
                                    "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                })
                                st.session_state["authenticated"] = True
                                st.session_state["auth_user"] = user
                                st.session_state["active_nav"] = "Dashboard"
                                db_mgr.log_audit(user_email, "Sign In", "Authenticated successfully")
                                st.rerun()
                        else:
                            st.error("Invalid HPE credentials. Please check your email or password.")
            
            st.markdown("<div style='text-align: center; color: #A0AEC0; margin: 0.5rem 0;'>or</div>", unsafe_allow_html=True)
            if st.button("🪟 Sign in with Microsoft (HPE)", use_container_width=True):
                st.info("Single Sign-On (SSO) requires Azure AD tenant configuration.")

            st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            if c1.button("Forgot password?", use_container_width=True):
                st.session_state["auth_mode"] = "Forgot Password"
                st.rerun()
            if c2.button("Don't have an account? Sign up", use_container_width=True):
                st.session_state["auth_mode"] = "Sign Up"
                st.rerun()

        elif auth_mode == "Sign Up":
            if st.button("← Back to Sign In"):
                st.session_state["auth_mode"] = "Sign In"
                st.rerun()
                
            st.markdown("## Create Your Account")
            st.caption("Sign up to access HPE CaseFlow")
            
            with st.form("signup_form"):
                fn = st.text_input("First Name", placeholder="Enter your first name")
                ln = st.text_input("Last Name", placeholder="Enter your last name")
                emp_id = st.text_input("Employee ID", placeholder="Enter your employee ID")
                email = st.text_input("HPE Email Address", placeholder="yourname@hpe.com")
                pwd = st.text_input("Password", type="password", placeholder="Create a password")
                st.caption("Password must be at least 8 characters and include letters, numbers and a special character.")
                
                submitted = st.form_submit_button("Sign Up", type="primary", use_container_width=True)
                if submitted:
                    if not all([fn, ln, emp_id, email, pwd]):
                        st.error("All fields are required.")
                    elif not email.endswith("@hpe.com"):
                        st.error("Registration requires an authorized @hpe.com email address.")
                    elif len(pwd) < 8 or not re.search(r"\d", pwd) or not re.search(r"[!@#$%^&*(),.?\":{}|<>]", pwd):
                        st.error("Password does not meet enterprise security requirements.")
                    elif db_mgr.find_user_by_email(email):
                        st.error("An account with this email address already exists.")
                    elif db_mgr.find_user_by_employee_id(emp_id):
                        st.error("An account with this Employee ID already exists.")
                    else:
                        new_user = {
                            "first_name": str(fn.strip()),
                            "last_name": str(ln.strip()),
                            "employee_id": str(emp_id.strip()),
                            "hpe_email": str(email.strip().lower()),
                            "password_hash": hash_password(pwd),
                            "role": "Agent",
                            "account_status": "Active",
                            "current_aux": "Not Ready - Online",
                            "aux_since": datetime.now().strftime("%I:%M %p"),
                            "login_status": "Offline",
                            "department": "Operations",
                            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        if db_mgr.create_user(new_user):
                            st.success("Account created successfully! Please sign in.")
                            st.session_state["auth_mode"] = "Sign In"
                            st.rerun()

            if st.button("Already have an account? Sign in"):
                st.session_state["auth_mode"] = "Sign In"
                st.rerun()

        elif auth_mode == "Forgot Password":
            st.markdown("## Reset Your Password")
            st.caption("Enter your registered HPE enterprise email to generate a secure reset token.")
            reset_email = st.text_input("Registered HPE Email")
            if st.button("Send Reset Link", type="primary", use_container_width=True):
                if reset_email and db_mgr.find_user_by_email(reset_email):
                    st.success(f"A password reset link has been dispatched to {reset_email}.")
                else:
                    st.error("Email not found on Team Roster.")
            if st.button("← Back to Sign In"):
                st.session_state["auth_mode"] = "Sign In"
                st.rerun()

# ==============================================================================
# 6. GLOBAL HEADER & PROFILE POPOVER (Matching Images 2, 3, 4)
# ==============================================================================
def render_global_header(user: Dict[str, Any]):
    user_email = user.get("hpe_email") or user.get("email", "")
    is_admin = user.get("role") in ["Admin", "Admin/Agent"]
    user_notifs = db_mgr.get_notifications(user_email, is_admin=is_admin)
    unread_count = len([n for n in user_notifs if not n.get("read", False)])
    
    col_brand, col_search, col_aux, col_profile = st.columns([1.5, 2.5, 1.8, 1.8], gap="medium")
    
    with col_brand:
        st.markdown(
            """
            <div style="display: flex; align-items: center; gap: 8px; padding-top: 4px;">
                <div style="background-color: #01A982; width: 12px; height: 32px; border-radius: 2px;"></div>
                <div>
                    <div style="font-weight: 800; font-size: 1.2rem; color: #0B2341; line-height: 1;">HPE CaseFlow</div>
                    <div style="font-size: 0.72rem; color: #616D75;">Team Task and Case Management System</div>
                </div>
            </div>
            """, 
            unsafe_allow_html=True
        )

    with col_search:
        search_query = st.text_input(
            "Global Search",
            placeholder="🔍 Search cases, subject, vendor, or issue...",
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
            db_mgr.update_user_aux(user_email, new_aux)
            user["current_aux"] = new_aux
            st.rerun()

    with col_profile:
        bell_icon = f"🔔 ({unread_count})" if unread_count > 0 else "🔔"
        first_name = user.get("first_name", "User")
        role = user.get("role", "Agent")
        popover = st.popover(f"{bell_icon} {first_name} ({role}) ▾", use_container_width=True)
        
        with popover:
            st.markdown(
                f"""
                <div style="padding-bottom: 10px;">
                    <h3 style="margin: 0; color: #0B2341;">{user.get('first_name')} {user.get('last_name')}</h3>
                    <div style="color: #00739D; font-weight: 600; font-size: 0.85rem;">{role}</div>
                    <div style="color: #616D75; font-size: 0.8rem; margin-top: 4px;">
                        Employee ID : <strong>{user.get('employee_id', 'HPE12345')}</strong><br/>
                        Email : <strong>{user_email}</strong><br/>
                        Department : <strong>{user.get('department', 'Operations')}</strong>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
            
            c_sess1, c_sess2 = st.columns(2)
            c_sess1.markdown(
                """
                <div style="background: #E5F3F8; border-radius: 8px; padding: 8px; text-align: center;">
                    <div style="font-size: 0.72rem; color: #00739D;">🕒 Login Time</div>
                    <div style="font-weight: 700; color: #0B2341; font-size: 0.95rem;">08:45 AM</div>
                </div>
                """, unsafe_allow_html=True
            )
            c_sess2.markdown(
                """
                <div style="background: #E6F6F2; border-radius: 8px; padding: 8px; text-align: center;">
                    <div style="font-size: 0.72rem; color: #01A982;">💻 Current Session</div>
                    <div style="font-weight: 700; color: #0B2341; font-size: 0.95rem;">3h 42m</div>
                </div>
                """, unsafe_allow_html=True
            )
            
            st.markdown("---")
            st.markdown("<strong>Today's Schedule</strong> (Monday, Sep 28, 2026)", unsafe_allow_html=True)
            st.markdown(
                """
                <div style="font-size: 0.8rem; line-height: 1.8; color: #4A5568;">
                    • 08:00 AM – 10:00 AM &nbsp;<span class="badge badge-available">Available</span><br/>
                    • 10:00 AM – 10:15 AM &nbsp;<span class="badge badge-break">Break</span><br/>
                    • 10:15 AM – 12:00 PM &nbsp;<span class="badge badge-available">Available</span><br/>
                    • 12:00 PM – 01:00 PM &nbsp;<span class="badge badge-lunch">Lunch</span><br/>
                    • 01:00 PM – 05:00 PM &nbsp;<span class="badge badge-available">Available</span>
                </div>
                """, unsafe_allow_html=True
            )
            
            st.markdown("---")
            if st.button("🚪 Sign Out", type="primary", use_container_width=True):
                db_mgr.update_user_field(user_email, {
                    "login_status": "Offline",
                    "current_aux": "Not Ready - Online"
                })
                st.session_state.clear()
                st.rerun()

# ==============================================================================
# 7. SIDEBAR NAVIGATION
# ==============================================================================
def render_sidebar(user: Dict[str, Any]):
    with st.sidebar:
        st.markdown(
            """
            <div style="padding: 0.5rem 0 1rem 0; border-bottom: 1px solid #E0E6ED; margin-bottom: 1rem;">
                <span style="background: #01A982; color: white; padding: 3px 8px; border-radius: 4px; font-weight: 800; font-size: 0.85rem;">HPE</span>
                <strong style="color: #0B2341; font-size: 1.1rem; margin-left: 8px;">CASEFLOW</strong>
            </div>
            """, 
            unsafe_allow_html=True
        )

        role = user.get("role", "Agent")
        nav_options = []
        
        if role == "Admin":
            nav_options = ["Dashboard", "Monitoring", "Schedule", "Report", "Settings"]
        elif role == "Admin/Agent":
            view_toggle = st.radio("View", ["Admin View", "Agent View"], horizontal=True, label_visibility="collapsed")
            st.session_state["view_mode"] = view_toggle
            if view_toggle == "Admin View":
                nav_options = ["Dashboard", "Monitoring", "Schedule", "Report", "Settings"]
            else:
                nav_options = ["Dashboard", "Schedule", "Report"]
        else: # Agent
            nav_options = ["Dashboard", "Schedule", "Report"]

        if st.session_state.get("active_nav") == "Case Details":
            nav_options.append("Case Details")

        current_nav = st.session_state.get("active_nav", "Dashboard")
        if current_nav not in nav_options:
            current_nav = nav_options[0]

        for item in nav_options:
            is_active = (item == current_nav)
            icon_map = {"Dashboard": "▦", "Monitoring": "👥", "Schedule": "📅", "Report": "📊", "Settings": "⚙", "Case Details": "🔍"}
            label = f"{icon_map.get(item, '▸')}  {item}"
            if st.button(label, key=f"nav_{item}", use_container_width=True, type="primary" if is_active else "secondary"):
                st.session_state["active_nav"] = item
                st.rerun()

        st.markdown("---")
        st.caption("Operational Roster: Connected")

# ==============================================================================
# 8. DASHBOARD VIEWS (Matching Images 7, 8, 9)
# ==============================================================================
def render_dashboard(user: Dict[str, Any]):
    is_admin = (user.get("role") == "Admin") or (user.get("role") == "Admin/Agent" and st.session_state.get("view_mode") != "Agent View")
    user_email = user.get("hpe_email") or user.get("email", "")

    c_head1, c_head2 = st.columns([3, 1.5])
    with c_head1:
        if is_admin:
            st.markdown("## Dashboard")
            st.caption(f"Welcome back, {user.get('first_name')}! Here's what's happening with your team today.")
        else:
            st.markdown("## My Dashboard")
            st.caption(f"Good morning, {user.get('first_name')}! Here are your assigned cases for today.")
    with c_head2:
        st.markdown(
            """
            <div style="text-align: right; padding-top: 10px;">
                <div style="font-size: 0.8rem; color: #616D75;">Monday, September 28, 2026</div>
                <div style="font-size: 1.6rem; font-weight: 800; color: #0B2341;">09:28 AM</div>
            </div>
            """, 
            unsafe_allow_html=True
        )

    all_cases = db_mgr.get_cases()
    target_cases = all_cases if is_admin else [c for c in all_cases if c.get("assigned_to", "").lower() == user_email.lower()]

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(
            f"""
            <div class="metric-box">
                <div>
                    <div class="metric-number" style="color: #00739D;">{len(target_cases)}</div>
                    <div class="metric-label">{'Active Cases' if is_admin else 'My Active Cases'}</div>
                    <div class="metric-sub" style="color: #01A982;">↑ 12% from yesterday</div>
                </div>
                <div style="font-size: 2.2rem; color: #00739D;">📁</div>
            </div>
            """, unsafe_allow_html=True
        )
    with m2:
        crit_c = len([c for c in target_cases if c.get("priority") == "Critical"])
        st.markdown(
            f"""
            <div class="metric-box">
                <div>
                    <div class="metric-number" style="color: #DE3618;">{crit_c}</div>
                    <div class="metric-label">Critical</div>
                    <div class="metric-sub" style="color: #DE3618;">↑ 3 new</div>
                </div>
                <div style="font-size: 2.2rem; color: #DE3618;">⚠️</div>
            </div>
            """, unsafe_allow_html=True
        )
    with m3:
        st.markdown(
            f"""
            <div class="metric-box">
                <div>
                    <div class="metric-number" style="color: #FFAA15;">4</div>
                    <div class="metric-label">Due Soon</div>
                    <div class="metric-sub" style="color: #FFAA15;">↑ 2 new</div>
                </div>
                <div style="font-size: 2.2rem; color: #FFAA15;">🕒</div>
            </div>
            """, unsafe_allow_html=True
        )
    with m4:
        st.markdown(
            f"""
            <div class="metric-box">
                <div>
                    <div class="metric-number" style="color: #01A982;">84</div>
                    <div class="metric-label">On Track</div>
                    <div class="metric-sub" style="color: #01A982;">↑ 4 new</div>
                </div>
                <div style="font-size: 2.2rem; color: #01A982;">✓</div>
            </div>
            """, unsafe_allow_html=True
        )

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
    
    col_main, col_rail = st.columns([2.8, 1.1], gap="medium")
    
    with col_main:
        table_title = f"Active Cases ({len(target_cases)})" if is_admin else "My Cases"
        st.subheader(table_title)
        
        f1, f2, f3, f4 = st.columns([2, 1, 1, 0.6])
        with f1:
            q_search = st.text_input("Search filter", placeholder="Search by case #, subject, assignee, vendor...", label_visibility="collapsed")
        with f2:
            prio_filter = st.selectbox("Priority", ["All Priority", "Critical", "High", "Medium", "Low"], label_visibility="collapsed")
        with f3:
            status_filter = st.selectbox("Status", ["All Status", "Open", "In Progress", "On Hold", "Pending Vendor", "Resolved"], label_visibility="collapsed")
        with f4:
            if st.button("Reset", use_container_width=True):
                st.rerun()

        filtered = target_cases
        if q_search:
            filtered = [c for c in filtered if q_search.lower() in c.get("subject", "").lower() or q_search.lower() in c.get("case_id", "").lower()]
        if prio_filter != "All Priority":
            filtered = [c for c in filtered if c.get("priority") == prio_filter]
        if status_filter != "All Status":
            filtered = [c for c in filtered if c.get("status") == status_filter]

        if not filtered:
            st.info("No cases matching the selected filters.")
        else:
            for case in filtered:
                with st.container():
                    status_slug = case.get('status', 'Open').lower().replace(' ', '')
                    st.markdown(
                        f"""
                        <div class="hpe-card" style="margin-bottom: 0.65rem;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <strong style="color: #00739D; font-size: 1rem;">{case.get('case_id')}</strong>
                                    <span style="font-weight: 700; color: #0B2341; margin-left: 10px;">{case.get('subject')}</span>
                                </div>
                                <div>
                                    <span class="badge badge-{case.get('priority', 'low').lower()}">{case.get('priority')}</span>
                                    <span class="badge badge-{status_slug}" style="margin-left: 5px;">{case.get('status')}</span>
                                </div>
                            </div>
                            <div style="font-size: 0.8rem; color: #616D75; margin-top: 6px; display: flex; gap: 16px;">
                                <span>👤 Assigned: <strong>{case.get('assigned_to')}</strong></span>
                                <span>⏱ Due: <strong style="color: {'#DE3618' if case.get('priority') == 'Critical' else '#0B2341'};">{case.get('due_date')}</strong></span>
                                <span>Last Update: <strong>{case.get('last_update', 'Just now')}</strong></span>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                    c_btn, _ = st.columns([1, 4])
                    if c_btn.button("Open Case", key=f"btn_open_{case.get('case_id')}"):
                        st.session_state["selected_case_id"] = case.get('case_id')
                        st.session_state["active_nav"] = "Case Details"
                        st.rerun()

    with col_rail:
        if is_admin:
            st.subheader("Agents Online (12)")
            st.caption("● Auto refreshes in 10s")
            
            sample_agents = [
                ("Maria Santos", "Available", 4),
                ("John Dela Cruz", "Available", 3),
                ("Liza Garcia", "Coaching", 1),
                ("Mark Tan", "Meeting", 2),
                ("Christine Reyes", "Available", 3),
                ("James Lim", "Not Ready - Online", 0),
                ("Anna Co", "Lunch", 0),
                ("Denise Chan", "Break", 1)
            ]
            for name, aux, count in sample_agents:
                color = AUX_COLORS.get(aux, "#01A982")
                st.markdown(
                    f"""
                    <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 8px 12px; margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <strong style="font-size: 0.88rem; color: #0B2341;">{name}</strong>
                            <div style="font-size: 0.72rem; color: {color};">● {aux}</div>
                        </div>
                        <div style="font-size: 0.9rem; font-weight: 700; color: #00739D;">{count}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
        else:
            st.subheader("Alerts")
            st.markdown(
                """
                <div class="hpe-card" style="border-left: 4px solid #DE3618; margin-bottom: 8px;">
                    <strong style="color: #DE3618; font-size: 0.85rem;">Critical case nearing due date</strong>
                    <div style="font-size: 0.78rem; color: #0B2341;">HC-2026-1044 • Due in 1h 32m</div>
                </div>
                <div class="hpe-card" style="border-left: 4px solid #00739D; margin-bottom: 8px;">
                    <strong style="color: #00739D; font-size: 0.85rem;">New case assigned to you</strong>
                    <div style="font-size: 0.78rem; color: #0B2341;">HC-2026-1038 • High Priority • Due 2:00 PM</div>
                </div>
                """, unsafe_allow_html=True
            )
            
            st.subheader("Quick Actions")
            qa1, qa2 = st.columns(2)
            if qa1.button("✉️ Send Message", use_container_width=True):
                dlg_admin_broadcast()
            if qa2.button("⇄ Request Transfer", use_container_width=True):
                dlg_transfer_request()
            if qa1.button("📅 View Schedule", use_container_width=True):
                st.session_state["active_nav"] = "Schedule"
                st.rerun()
            if qa2.button("📊 View Report", use_container_width=True):
                st.session_state["active_nav"] = "Report"
                st.rerun()

# ==============================================================================
# 9. CASE DETAILS VIEW (Matching Images 5 & 6)
# ==============================================================================
def render_case_details(user: Dict[str, Any]):
    case_id = st.session_state.get("selected_case_id", "HC-2026-1044")
    case = db_mgr.get_case_by_id(case_id)
    if not case:
        st.error(f"Case {case_id} not found.")
        if st.button("← Back to Dashboard"):
            st.session_state["active_nav"] = "Dashboard"
            st.rerun()
        return

    is_admin = user.get("role") in ["Admin", "Admin/Agent"]
    user_email = user.get("hpe_email") or user.get("email", "")

    if st.button("← Back to Dashboard"):
        st.session_state["active_nav"] = "Dashboard"
        st.rerun()

    st.markdown(
        f"""
        <div class="hpe-card" style="background: #FFFFFF; border-top: 4px solid #DE3618;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                <div>
                    <h2 style="margin: 0; color: #0B2341;">📁 Case Details — {case.get('case_id')}</h2>
                    <div style="font-size: 1.25rem; font-weight: 700; color: #0B2341; margin-top: 4px;">{case.get('subject')}</div>
                    <div style="color: #616D75; font-size: 0.85rem; margin-top: 4px;">{case.get('description')}</div>
                </div>
                <div style="text-align: right;">
                    <span class="badge badge-critical" style="font-size: 0.85rem;">{case.get('priority')}</span>
                    <div style="color: #DE3618; font-weight: 700; font-size: 0.9rem; margin-top: 6px;">Due in 3h 45m</div>
                </div>
            </div>
            <div style="margin-top: 1rem; padding-top: 0.8rem; border-top: 1px solid #EDF2F7; display: flex; flex-wrap: wrap; gap: 20px; font-size: 0.85rem;">
                <span>👤 Assigned: <strong>{case.get('assigned_to')}</strong></span>
                <span>📅 Created: <strong>{case.get('created_date')}</strong></span>
                <span>⏰ Due: <strong>{case.get('due_date')}</strong></span>
                <span>🏢 Account: <strong>{case.get('account')}</strong></span>
                <span>⚙️ System: <strong>{case.get('related_system')}</strong></span>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    dropdowns = db_mgr.get_dropdowns()
    col_left, col_right = st.columns([1.5, 1.2], gap="large")
    
    with col_left:
        t_info, t_vend, t_hist = st.tabs(["Case Information", "Vendor Information", "Case History"])
        
        with t_info:
            st.markdown("#### Case Information")
            st.text_input("Case #", value=case.get("case_id"), disabled=True)
            st.text_input("Subject", value=case.get("subject"))
            st.text_area("Description", value=case.get("description"), height=100)
            
            p_opts = ["Critical", "High", "Medium", "Low"]
            new_p = st.selectbox("Priority", p_opts, index=p_opts.index(case.get("priority", "Critical")))
            
            s_opts = dropdowns.get("Case_Status", ["Open", "In Progress", "On Hold", "Resolved"])
            new_s = st.selectbox("Status", s_opts, index=s_opts.index(case.get("status", "On Hold")) if case.get("status") in s_opts else 0)
            
            if st.button("Save Information Updates", type="primary"):
                db_mgr.update_case(case_id, {"priority": new_p, "status": new_s}, user_email)
                st.success("Case updated successfully.")
                st.rerun()

        with t_vend:
            st.markdown("#### ABC Software Inc.")
            st.markdown("Primary Contact: **Michael Tan**")
            st.markdown("Email: `support@abcsoftware.com`")
            st.markdown("Phone: `+1 555 123 4567`")
            st.markdown("Address: *123 Innovation Drive, San Jose, CA 95134*")
            
            q1, q2 = st.columns(2)
            if q1.button("📋 Copy Email", use_container_width=True):
                st.toast("Email copied to clipboard.")
            if q2.button("📞 Copy Phone", use_container_width=True):
                st.toast("Phone hotline copied to clipboard.")

        with t_hist:
            st.markdown("#### Case Event History")
            history = db_mgr.get_case_history(case_id)
            if history:
                for h in history:
                    st.markdown(
                        f"""
                        <div style="border-left: 3px solid #01A982; padding-left: 12px; margin-bottom: 10px;">
                            <div style="font-weight: 700; color: #0B2341;">{h.get('action')} — <span style="font-size: 0.75rem; color: #616D75;">{h.get('timestamp')}</span></div>
                            <div style="font-size: 0.8rem; color: #00739D;">{h.get('user')}</div>
                            <div style="font-size: 0.8rem; color: #4A5568;">{h.get('details')}</div>
                        </div>
                        """, unsafe_allow_html=True
                    )
            else:
                st.caption("No historical records yet.")

    with col_right:
        st.markdown("#### Update Case")
        with st.form("update_case_form"):
            new_stat = st.selectbox("Case Status", dropdowns.get("Case_Status", ["Open", "In Progress", "On Hold", "Resolved"]))
            new_reason = st.selectbox("Status Reason", dropdowns.get("Status_Reason", ["Waiting for Vendor Response", "Customer Verification"]))
            new_closure = st.selectbox("Closure Type", dropdowns.get("Closure_Type", ["Resolved - Normal", "Contract Breach"]))
            new_breach = st.selectbox("Breach Reason", dropdowns.get("Contract_Breach", ["Vendor No Response", "Late Delivery"]))
            remarks = st.text_area("Remarks / Update Notes", placeholder="Add update notes or next steps...")
            
            if st.form_submit_button("✓ Update Case", type="primary", use_container_width=True):
                updates = {"status": new_stat}
                if remarks:
                    updates["last_update"] = remarks
                db_mgr.update_case(case_id, updates, user_email)
                st.success("Case updated.")
                st.rerun()

        if is_admin:
            st.markdown("---")
            st.markdown("#### Reassign Case (Admin Only)")
            all_users = [u.get("hpe_email") for u in db_mgr.get_all_roster_users()]
            target_u = st.selectbox("Reassign To", all_users)
            notify = st.checkbox("Send notification to new assignee", value=True)
            if st.button("👥 Reassign Case", type="primary"):
                db_mgr.update_case(case_id, {"assigned_to": target_u}, user_email)
                if notify:
                    db_mgr.add_notification(target_u, "Case Reassigned", f"Case {case_id} reassigned to you.", notif_type="Case", case_id=case_id)
                st.success(f"Case successfully reassigned to {target_u}.")
                st.rerun()

# ==============================================================================
# 10. MONITORING COMMAND CENTER (Matching Image 10)
# ==============================================================================
def render_monitoring(user: Dict[str, Any]):
    if user.get("role") not in ["Admin", "Admin/Agent"]:
        st.error("Access Restricted. Monitoring is an administrative function.")
        return

    st.markdown("## Monitoring")
    st.caption("View all logged in agents, their real-time status and activities.")
    
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Logged In", "12 / 15", "80%")
    k2.metric("Available", "6", "50%")
    k3.metric("On Aux", "5", "42%")
    k4.metric("In Meeting/Coaching", "1", "8%")
    k5.metric("Not Ready", "0", "0%")
    
    st.markdown("---")
    col_table, col_drawer = st.columns([2.5, 1.2], gap="large")
    
    with col_table:
        st.subheader("Agent Monitoring Table")
        sample_monitoring_roster = [
            {"name": "Daniel Reyes", "id": "HPE001236", "role": "Admin/Agent", "status": "Online", "aux": "Meeting", "cases": 4, "assigned": 2, "time": "09:00 AM (28m ago)"},
            {"name": "Beatrice Santos", "id": "HPE001234", "role": "Agent", "status": "Online", "aux": "Available", "cases": 3, "assigned": 1, "time": "09:12 AM (16m ago)"},
            {"name": "Carlos Mendoza", "id": "HPE001235", "role": "Agent", "status": "Online", "aux": "Admin Work", "cases": 2, "assigned": 0, "time": "08:45 AM (43m ago)"},
            {"name": "Erika Villanueva", "id": "HPE001237", "role": "Agent", "status": "Online", "aux": "Lunch", "cases": 1, "assigned": 0, "time": "09:20 AM (8m ago)"},
            {"name": "Francis Lim", "id": "HPE001238", "role": "Agent", "status": "Online", "aux": "Coaching", "cases": 3, "assigned": 1, "time": "09:05 AM (23m ago)"}
        ]
        
        for agent in sample_monitoring_roster:
            with st.container():
                st.markdown(
                    f"""
                    <div class="hpe-card" style="margin-bottom: 0.5rem; display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <strong>{agent['name']}</strong> ({agent['id']}) — <span style="color: #00739D;">{agent['role']}</span>
                            <div style="font-size: 0.75rem; color: #616D75;">Aux: <strong>{agent['aux']}</strong> • Active Cases: <strong>{agent['cases']}</strong> • Today: <strong>{agent['assigned']}</strong></div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True
                )
                if st.button("Inspect Agent Drawer", key=f"inspect_{agent['id']}"):
                    st.session_state["selected_agent_inspect"] = agent
                    st.rerun()

    with col_drawer:
        sel_agent = st.session_state.get("selected_agent_inspect", sample_monitoring_roster[0])
        st.markdown(
            f"""
            <div class="hpe-card" style="border-top: 4px solid #00739D;">
                <h3>{sel_agent['name']}</h3>
                <div style="color: #616D75; font-size: 0.85rem;">Employee ID: {sel_agent['id']}</div>
                <div style="color: #01A982; font-weight: 700; font-size: 0.85rem; margin-top: 4px;">● {sel_agent['status']}</div>
            </div>
            """, unsafe_allow_html=True
        )
        st.markdown(f"**Current Aux:** <span class='badge badge-coaching'>{sel_agent['aux']}</span>", unsafe_allow_html=True)
        st.caption(f"Since: {sel_agent['time']}")
        
        st.markdown("---")
        st.markdown("<strong>Today's Schedule:</strong>", unsafe_allow_html=True)
        st.markdown(
            """
            <div style="font-size: 0.78rem; line-height: 1.8; color: #4A5568;">
                • 08:00 – 10:00 &nbsp;<span class="badge badge-available">Available</span><br/>
                • 10:00 – 10:15 &nbsp;<span class="badge badge-break">Break</span><br/>
                • 10:15 – 12:00 &nbsp;<span class="badge badge-available">Available</span><br/>
                • 12:00 – 01:00 &nbsp;<span class="badge badge-lunch">Lunch</span><br/>
                • 01:00 – 03:00 &nbsp;<span class="badge badge-coaching">Coaching</span><br/>
                • 03:00 – 05:00 &nbsp;<span class="badge badge-available">Available</span>
            </div>
            """, unsafe_allow_html=True
        )
        st.markdown("---")
        if st.button("💬 Send Message", use_container_width=True):
            st.success(f"Message dispatched to {sel_agent['name']}.")
        if st.button("🚫 Kick User", type="primary", use_container_width=True):
            st.warning(f"User {sel_agent['name']} session ended.")

# ==============================================================================
# 11. SCHEDULE MODULE (Matching Images 11, 12, 13)
# ==============================================================================
def render_schedule(user: Dict[str, Any]):
    is_admin = (user.get("role") == "Admin") or (user.get("role") == "Admin/Agent" and st.session_state.get("view_mode") != "Agent View")

    st.markdown("## Schedule")
    st.caption("Manage PTO allocation, leaves, and daily schedules" if is_admin else "View your schedule, request leaves, and manage your activities.")

    if is_admin:
        # Recreates Admin Schedule from Images 11 & 13
        c_p1, c_p2, c_p3 = st.columns([1.5, 1.5, 1.5], gap="medium")
        
        with c_p1:
            st.markdown(
                """
                <div class="hpe-card">
                    <h4>PTO Allocation Calendar</h4>
                    <div style="font-size: 0.78rem; display: flex; gap: 8px; margin-bottom: 8px;">
                        <span>⚪ Available</span> <span>🟡 Partial</span> <span>🔴 Fully Allocated</span> <span>🔵 Today</span>
                    </div>
                    <div style="display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; text-align: center; font-size: 0.75rem;">
                        <strong>S</strong><strong>M</strong><strong>T</strong><strong>W</strong><strong>T</strong><strong>F</strong><strong>S</strong>
                        <span>30</span><span>31</span><span>1</span><span>2</span><span>3</span><span>4</span><span>5</span>
                        <span>6</span><span style="background: #FFFBE6; border-radius: 4px;">7</span><span style="background: #FFFBE6; border-radius: 4px;">8</span><span>9</span><span>10</span><span>11</span><span>12</span>
                        <span>13</span><span style="background: #FFE4E6; border-radius: 4px; color: #E11D48; font-weight: 700;">14</span><span>15</span><span style="background: #FFFBE6; border-radius: 4px;">16</span><span>17</span><span>18</span><span>19</span>
                        <span>20</span><span>21</span><span style="border: 2px solid #00739D; border-radius: 4px; font-weight: 700;">22</span><span>23</span><span style="background: #FFE4E6; border-radius: 4px; color: #E11D48; font-weight: 700;">24</span><span>25</span><span>26</span>
                        <span>27</span><span>28</span><span>29</span><span>30</span><span>1</span><span>2</span><span>3</span>
                    </div>
                </div>
                """, unsafe_allow_html=True
            )

        with c_p2:
            st.markdown(
                """
                <div class="hpe-card">
                    <h4>PTO Allocation Summary (Sep 2026)</h4>
                    <div style="display: flex; justify-content: space-between; margin-top: 10px; text-align: center;">
                        <div><div style="font-size: 1.6rem; font-weight: 800; color: #00739D;">10</div><div style="font-size: 0.75rem; color: #616D75;">Total Days</div></div>
                        <div><div style="font-size: 1.6rem; font-weight: 800; color: #0B2341;">6</div><div style="font-size: 0.75rem; color: #616D75;">Used</div></div>
                        <div><div style="font-size: 1.6rem; font-weight: 800; color: #01A982;">4</div><div style="font-size: 0.75rem; color: #616D75;">Remaining</div></div>
                        <div><div style="font-size: 1.6rem; font-weight: 800; color: #DE3618;">3</div><div style="font-size: 0.75rem; color: #616D75;">Full Dates</div></div>
                    </div>
                    <div style="margin-top: 15px; font-size: 0.8rem;">
                        <strong>Fully Allocated:</strong> <span class="badge badge-pto">Sep 14</span> <span class="badge badge-pto">Sep 24</span> <span class="badge badge-pto">Sep 29</span>
                    </div>
                </div>
                """, unsafe_allow_html=True
            )

        with c_p3:
            st.markdown("#### Leave Requests (This Month)")
            requests = db_mgr.get_leave_requests()
            for r in requests[:4]:
                st.markdown(
                    f"""
                    <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; padding: 6px 10px; margin-bottom: 6px; font-size: 0.8rem; display: flex; justify-content: space-between;">
                        <div><strong>{r['name']}</strong> ({r['type']})<br/><span style="color: #616D75;">{r['dates']}</span></div>
                        <div><span class="badge badge-available">{r['status']}</span></div>
                    </div>
                    """, unsafe_allow_html=True
                )

        st.markdown("---")
        st.subheader("Schedule Assignment (Tue, Sep 22, 2026)")
        st.caption("Auto-plotted based on availability. You can edit, add activities, or adjust schedules.")
        
        ca1, ca2 = st.columns([3, 1.2], gap="large")
        with ca1:
            gantt_rows = [
                {"Agent": "Arianne Escabillas", "Role": "Admin", "8 AM - 12 PM": "Admin Work", "12 PM - 1 PM": "Lunch", "1 PM - 5 PM": "Admin Work"},
                {"Agent": "Juan Dela Cruz", "Role": "Admin/Agent", "8 AM - 12 PM": "Case Work", "12 PM - 1 PM": "Lunch", "1 PM - 5 PM": "Case Work"},
                {"Agent": "Maria Santos", "Role": "Agent", "8 AM - 12 PM": "Case Work", "12 PM - 1 PM": "Lunch", "1 PM - 5 PM": "Case Work"},
                {"Agent": "Leo Ramirez", "Role": "Agent", "8 AM - 12 PM": "Coaching", "12 PM - 1 PM": "Lunch", "1 PM - 5 PM": "Case Work"},
                {"Agent": "Mark Villanueva", "Role": "Agent", "8 AM - 12 PM": "Training", "12 PM - 1 PM": "Lunch", "1 PM - 5 PM": "Case Work"}
            ]
            st.dataframe(pd.DataFrame(gantt_rows), use_container_width=True, hide_index=True)
            c_bt1, c_bt2, c_bt3 = st.columns([1, 1, 1])
            c_bt1.button("🪄 Auto Plot", type="primary", use_container_width=True)
            c_bt2.button("💾 Save Changes", use_container_width=True)
            c_bt3.button("📥 Export", use_container_width=True)

        with ca2:
            st.markdown("#### Add / Edit Schedule")
            with st.form("add_sched_form"):
                st.selectbox("Select Agent(s)", ["Juan Dela Cruz", "Maria Santos", "Leo Ramirez", "Ana Torres"])
                st.selectbox("Activity Type", ["Case Work", "Admin Work", "Meeting", "Coaching", "Training", "PTO"])
                st.date_input("Date", value=datetime.now())
                st.form_submit_button("Plot Schedule", type="primary", use_container_width=True)

    else:
        # Recreates Agent Schedule from Image 12
        c_ag1, c_ag2 = st.columns([2, 1.2], gap="large")
        with c_ag1:
            st.markdown("#### My Weekly Schedule (Sep 20 – Sep 26, 2026)")
            agent_sched = {
                "Time": ["08:00 AM", "10:00 AM", "10:15 AM", "12:00 PM", "01:00 PM", "03:00 PM", "03:15 PM"],
                "Mon (Sep 21)": ["Case Work", "Break", "Case Work", "Lunch", "Case Work", "Coaching", "Case Work"],
                "Tue (Sep 22)": ["Case Work", "Break", "Case Work", "Lunch", "Case Work", "Meeting", "Case Work"],
                "Wed (Sep 23)": ["Admin Work", "Case Work", "Case Work", "Lunch", "Case Work", "Case Work", "Case Work"],
                "Thu (Sep 24)": ["PTO (All Day)", "PTO", "PTO", "PTO", "PTO", "PTO", "PTO"]
            }
            st.dataframe(pd.DataFrame(agent_sched), use_container_width=True, hide_index=True)

        with c_ag2:
            st.markdown("#### Submit Request")
            req_type = st.radio("Type", ["PTO", "Sick Leave", "Emergency Leave", "Schedule Swap"], horizontal=True)
            with st.form("agent_req_form"):
                st.date_input("Date", value=datetime.now())
                st.selectbox("Reason", ["Personal / Family", "Medical", "Emergency", "Coverage Shift"])
                st.text_area("Remarks (Optional)", height=80)
                if st.form_submit_button("Submit Request", type="primary", use_container_width=True):
                    st.success(f"{req_type} filed successfully.")

            st.markdown("---")
            st.markdown("#### My Leave Balances (2026)")
            st.markdown(
                """
                <div style="font-size: 0.85rem; line-height: 2;">
                    • 🏖️ <strong>PTO:</strong> 4 / 10 days<br/>
                    • 🩺 <strong>Sick Leave:</strong> 5 / 10 days<br/>
                    • 🚨 <strong>Emergency Leave:</strong> 5 / 10 days
                </div>
                """, unsafe_allow_html=True
            )

# ==============================================================================
# 12. REPORTS & ANALYTICS MODULE (Matching Images 14, 15, 16)
# ==============================================================================
def render_reports(user: Dict[str, Any]):
    is_admin = (user.get("role") == "Admin") or (user.get("role") == "Admin/Agent" and st.session_state.get("view_mode") != "Agent View")

    st.markdown("## Reports")
    st.caption("Visualize team performance, case resolution, attendance, and adherence." if is_admin else "View your performance, attendance and adherence reports.")

    p_col1, p_col2 = st.columns([2, 1])
    with p_col1:
        st.radio("Period", ["Daily", "WOW", "MTD", "YTD"], horizontal=True, label_visibility="collapsed")

    # 4 Top KPI Cards
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Total Cases", "248" if is_admin else "48", "↑ 12%")
    r2.metric("Resolved Cases", "205" if is_admin else "41", "85.4% Rate")
    r3.metric("Breached Cases", "12" if is_admin else "2", "4.2% Breach")
    r4.metric("On-Time Resolution", "94%", "12.5 hrs Avg")

    st.markdown("---")

    # Chart Rows
    c_ch1, c_ch2, c_ch3 = st.columns(3)
    with c_ch1:
        st.subheader("Case Breakdown by Priority")
        fig_prio = px.pie(
            values=[38, 62, 96, 52],
            names=["Critical", "High", "Medium", "Low"],
            color_discrete_sequence=["#DE3618", "#FFAA15", "#00739D", "#01A982"],
            hole=0.45
        )
        fig_prio.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=250)
        st.plotly_chart(fig_prio, use_container_width=True)

    with c_ch2:
        st.subheader("Case Status Volume")
        fig_stat = px.bar(
            x=["Open", "In Progress", "Pending", "Resolved"],
            y=[78, 102, 56, 12],
            color_discrete_sequence=["#01A982"]
        )
        fig_stat.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=250)
        st.plotly_chart(fig_stat, use_container_width=True)

    with c_ch3:
        st.subheader("Resolution Time (Hours)")
        fig_res = px.bar(
            x=["Critical", "High", "Medium", "Low"],
            y=[12.5, 18.3, 26.8, 34.1],
            color=["Critical", "High", "Medium", "Low"],
            color_discrete_map={"Critical": "#DE3618", "High": "#FFAA15", "Medium": "#00739D", "Low": "#01A982"}
        )
        fig_res.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=250, showlegend=False)
        st.plotly_chart(fig_res, use_container_width=True)

    if is_admin:
        st.markdown("---")
        t_col1, t_col2 = st.columns([1.5, 1.2], gap="large")
        with t_col1:
            st.subheader("Top Agents by Resolved Cases")
            top_agents = [
                {"Rank": 1, "Agent": "Beatrice Santos", "Resolved": 32, "Breached": 2, "On-Time %": "94%", "Avg. Res (hrs)": 18.5},
                {"Rank": 2, "Agent": "Carlos Mendoza", "Resolved": 28, "Breached": 1, "On-Time %": "96%", "Avg. Res (hrs)": 16.2},
                {"Rank": 3, "Agent": "Daniel Reyes", "Resolved": 31, "Breached": 2, "On-Time %": "94%", "Avg. Res (hrs)": 20.1},
                {"Rank": 4, "Agent": "Erika Villanueva", "Resolved": 26, "Breached": 3, "On-Time %": "90%", "Avg. Res (hrs)": 22.4}
            ]
            st.dataframe(pd.DataFrame(top_agents), use_container_width=True, hide_index=True)

        with t_col2:
            st.subheader("Adherence (MTD)")
            fig_adh = px.pie(
                values=[92, 8],
                names=["On Schedule", "Out of Schedule"],
                color_discrete_sequence=["#01A982", "#DE3618"],
                hole=0.6
            )
            fig_adh.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=220)
            st.plotly_chart(fig_adh, use_container_width=True)
            st.caption("Total Scheduled: 1,760 hrs | Deviated: 141 hrs")

# ==============================================================================
# 13. SETTINGS & EXTERNAL SOURCES (Matching Images 17 & 18)
# ==============================================================================
def render_settings(user: Dict[str, Any]):
    if user.get("role") not in ["Admin", "Admin/Agent"]:
        st.error("Access Restricted. Administrator authorization required.")
        return

    st.markdown("## Settings")
    st.caption("Manage users, roles, external data, vendor integrations, and system configurations.")

    tab_team, tab_ext = st.tabs(["Team Management", "External Sources"])

    with tab_team:
        # Recreates Image 17 (Team Management, Role Matrix, Account Actions)
        st.subheader("Team Roster")
        users = db_mgr.get_all_roster_users()
        roster_table = []
        for idx, u in enumerate(users):
            roster_table.append({
                "#": idx + 1,
                "Name": f"{u.get('first_name', '')} {u.get('last_name', '')}",
                "Employee ID": u.get('employee_id', 'HPE12345'),
                "Email": u.get('hpe_email') or u.get('email', ''),
                "Role": u.get('role', 'Agent'),
                "Status": u.get('account_status', 'Active'),
                "Current Aux": u.get('current_aux', 'Available')
            })
        st.dataframe(pd.DataFrame(roster_table), use_container_width=True, hide_index=True)

        st.markdown("---")
        s1, s2, s3 = st.columns([1.2, 1.2, 1.2], gap="large")
        
        with s1:
            st.markdown("#### Edit User Information")
            with st.form("edit_user_form"):
                st.text_input("First Name", value="Arianne May")
                st.text_input("Last Name", value="Escabillas")
                st.text_input("Employee ID", value="HPE12345", disabled=True)
                st.text_input("HPE Email", value="arianne.escabillas@hpe.com")
                st.selectbox("Role", ["Admin/Agent", "Admin", "Agent"])
                st.selectbox("Status", ["Active", "Inactive"])
                st.form_submit_button("Save Changes", type="primary", use_container_width=True)

        with s2:
            st.markdown("#### Change User Role")
            st.selectbox("Select User", [u.get("hpe_email") for u in users])
            st.selectbox("New Role", ["Agent", "Admin/Agent", "Admin"])
            st.markdown(
                """
                <div style="font-size: 0.8rem; background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; padding: 10px; margin: 10px 0;">
                    <strong>Role Permissions:</strong><br/>
                    • Dashboard: ✓ View only<br/>
                    • Monitoring: ✕ No access (Admin only)<br/>
                    • Schedule: ✓ View and submit request<br/>
                    • Report: ✓ View own data<br/>
                    • Settings: ✕ No access (Admin only)
                </div>
                """, unsafe_allow_html=True
            )
            st.button("Update Role", type="primary", use_container_width=True)

        with s3:
            st.markdown("#### Account Actions & Security")
            if st.button("🔒 Reset Password", use_container_width=True):
                st.toast("Password reset link sent to user.")
            if st.button("🚫 Deactivate Account", use_container_width=True):
                st.warning("Account deactivated.")
            if st.button("✓ Reactivate Account", use_container_width=True):
                st.success("Account reactivated.")
            if st.button("🗑️ Delete Account", type="primary", use_container_width=True):
                st.error("Account removed from roster.")

    with tab_ext:
        # Recreates Image 18 (External Data Sources & Sync Settings)
        c_grid, c_sync = st.columns([2.5, 1.2], gap="large")
        
        with c_grid:
            st.subheader("External Data Sources")
            e1, e2 = st.columns(2)
            with e1:
                st.markdown(
                    """
                    <div class="hpe-card">
                        <h4>📊 Vendor Data</h4>
                        <div style="font-size: 0.8rem; color: #616D75;">Excel file containing vendor contacts</div>
                        <div style="margin: 8px 0;"><span class="badge badge-available">● Connected</span></div>
                        <div style="font-size: 0.72rem; color: #616D75;">Last Sync: Sep 28, 2026 09:25 AM</div>
                    </div>
                    """, unsafe_allow_html=True
                )
                st.button("Sync Vendor Data Now", key="sync_vnd")
            with e2:
                st.markdown(
                    """
                    <div class="hpe-card">
                        <h4>📥 Case Import</h4>
                        <div style="font-size: 0.8rem; color: #616D75;">Import new cases from Excel template</div>
                        <div style="margin: 8px 0;"><span class="badge badge-available">● Connected</span></div>
                        <div style="font-size: 0.72rem; color: #616D75;">Last Sync: Sep 28, 2026 08:15 AM</div>
                    </div>
                    """, unsafe_allow_html=True
                )
                st.button("Sync Cases Now", key="sync_case")

        with c_sync:
            st.subheader("Sync Settings")
            st.toggle("Auto Sync Vendor Data", value=True)
            st.selectbox("Sync Time", ["02:00 AM", "08:00 AM", "08:00 PM"])
            st.toggle("Auto Sync Case Import", value=True)
            st.selectbox("Import Interval", ["15 minutes", "30 minutes", "1 hour"])
            st.toggle("Auto Sync Holiday Calendar", value=True)
            st.button("💾 Save Sync Settings", type="primary", use_container_width=True)

        st.markdown("---")
        st.subheader("Data Preview (Vendors)")
        vendors = db_mgr.get_vendors()
        if vendors:
            st.dataframe(pd.DataFrame(vendors), use_container_width=True, hide_index=True)

# ==============================================================================
# 14. MAIN APPLICATION ROUTER & INITIALIZATION
# ==============================================================================
def main():
    if not st.session_state.get("authenticated", False):
        render_auth_page()
        return

    current_user = st.session_state.get("auth_user")
    if not current_user:
        st.session_state.clear()
        st.rerun()

    # Global Shell Header
    render_global_header(current_user)
    
    # Left Persistent Sidebar Navigation
    render_sidebar(current_user)
    
    # Routing
    active_nav = st.session_state.get("active_nav", "Dashboard")
    
    if active_nav == "Dashboard":
        render_dashboard(current_user)
    elif active_nav == "Case Details":
        render_case_details(current_user)
    elif active_nav == "Monitoring":
        render_monitoring(current_user)
    elif active_nav == "Schedule":
        render_schedule(current_user)
    elif active_nav in ["Report", "Reports"]:
        render_reports(current_user)
    elif active_nav in ["Setting", "Settings"]:
        render_settings(current_user)

if __name__ == "__main__":
    main()
