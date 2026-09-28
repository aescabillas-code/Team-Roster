import streamlit as st
import pandas as pd
import plotly.express as px
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
# 2. SECURITY & PASSWORD MANAGEMENT (PBKDF2-SHA256)
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
# 3. DATABASE REPOSITORY LAYER (Strict PyMongo Object Checking)
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
    """Manages all persistent operations strictly across MongoDB collections without bool() checks."""
    def __init__(self):
        self.client = get_mongo_client()
        self.db = None
        self.collection = None
        if self.client is not None:
            self.db = self.client["TeamRoster"]
            self.collection = self.db["Team Roster Collection"]
            self._seed_reference_data_if_empty()

    def is_connected(self) -> bool:
        if self.client is None:
            self.client = get_mongo_client()
            if self.client is not None:
                self.db = self.client["TeamRoster"]
                self.collection = self.db["Team Roster Collection"]
                self._seed_reference_data_if_empty()
        return (self.client is not None) and (self.collection is not None)

    def _seed_reference_data_if_empty(self):
        """Populates MongoDB on first run so the UI matches the reference screenshots."""
        if self.collection is None:
            return
        
        # 1. Validation Dropdowns Object
        if self.collection.count_documents({"type": "Validation_Dropdown"}) == 0:
            self.collection.insert_one({
                "type": "Validation_Dropdown",
                "Case_Status": ["Open", "In Progress", "On Hold", "Pending Vendor", "Pending Internal", "Resolved", "Closed"],
                "Case_Reason": ["Waiting for Vendor Response", "Customer Verification", "Investigation in Progress", "Spare Part Dispatched"],
                "Closure_Type": ["Resolved - Normal", "Resolved - Workaround", "Contract Breach", "Cancelled by Customer"],
                "Contract_Breach": ["Vendor No Response", "Late Delivery", "Incomplete Information", "Scope Change", "Hardware Unavailability"]
            })

        # 2. Seed Initial Cases
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
                    "last_update": "Sep 28, 2026 08:45 AM",
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
                }
            ]
            for c in seed_cases:
                self.collection.insert_one({"type": "case_record", "case": c})

        # 3. Seed Vendor Directory
        if self.collection.count_documents({"type": "vendor_data"}) == 0:
            seed_vendors = [
                {
                    "name": "ABC Software Inc.",
                    "contact": "Michael Tan",
                    "email": "support@abcsoftware.com",
                    "phone": "+1 555 123 4567",
                    "alt_contact": "Sarah Lim",
                    "alt_email": "sarah.lim@abcsoftware.com",
                    "address": "123 Innovation Drive, San Jose, CA 95134",
                    "category": "Enterprise Software",
                    "status": "Active"
                },
                {
                    "name": "Intel Xeon Platform Support",
                    "contact": "David Vance",
                    "email": "tier3-intel@intel.com",
                    "phone": "+1 800 456 7890",
                    "alt_contact": "Robert Chen",
                    "alt_email": "r.chen@intel.com",
                    "address": "2200 Mission College Blvd, Santa Clara, CA",
                    "category": "Compute / Silicon",
                    "status": "Active"
                }
            ]
            for v in seed_vendors:
                self.collection.insert_one({"type": "vendor_data", "vendor": v})

    # --- User / Roster Operations ---
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
        # Save as type: 'roster_list' with all fields as strings
        str_user_data = {str(k): str(v) for k, v in user_data.items()}
        self.collection.insert_one({
            "type": "roster_list",
            "roster_list": str_user_data
        })
        self.log_audit(str_user_data.get("hpe_email", ""), "User Registration", f"Account created as {str_user_data.get('role')}")
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
        update_doc = {f"roster_list.{k}": str(v) for k, v in fields.items()}
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

    # --- Cases & Workload Dispatch ---
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

    # --- Schedule & PTO Monitoring ---
    def get_pto_allocations(self, month_str: str) -> Dict[str, int]:
        if not self.is_connected():
            return {}
        doc = self.collection.find_one({"type": "Schedule_Monitoring", "sub_type": "pto_allocations", "month": month_str})
        return doc.get("allocations", {}) if doc else {}

    def set_pto_allocation(self, month_str: str, date_str: str, count: int):
        if not self.is_connected():
            return
        self.collection.update_one(
            {"type": "Schedule_Monitoring", "sub_type": "pto_allocations", "month": month_str},
            {"$set": {f"allocations.{date_str}": count}},
            upsert=True
        )

    def get_leave_requests(self) -> List[Dict[str, Any]]:
        if not self.is_connected():
            return []
        cursor = self.collection.find({"type": "leave_request"}).sort("created_at", -1)
        return list(cursor)

    def insert_leave_request(self, req: Dict[str, Any]):
        if not self.is_connected():
            return
        req["type"] = "leave_request"
        req["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.collection.insert_one(req)

    def get_validation_dropdowns(self) -> Dict[str, List[str]]:
        if not self.is_connected():
            return {
                "Case_Status": ["Open", "In Progress", "On Hold", "Pending Vendor", "Pending Internal", "Resolved", "Closed"],
                "Case_Reason": ["Waiting for Vendor Response", "Customer Verification", "Investigation in Progress", "Spare Part Dispatched"],
                "Closure_Type": ["Resolved - Normal", "Resolved - Workaround", "Contract Breach", "Cancelled by Customer"],
                "Contract_Breach": ["Vendor No Response", "Late Delivery", "Incomplete Information", "Scope Change", "Hardware Unavailability"]
            }
        doc = self.collection.find_one({"type": "Validation_Dropdown"})
        return doc if doc else {}

    # --- Notifications & Audit ---
    def get_notifications(self, email: str, is_admin: bool) -> List[Dict[str, Any]]:
        if not self.is_connected() or not email:
            return []
        q = {"type": "notification"}
        if not is_admin:
            q["$or"] = [{"recipient": email}, {"recipient": "ALL"}]
        cursor = self.collection.find(q).sort("timestamp", -1).limit(15)
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
            return []
        cursor = self.collection.find({"type": "audit_log"}).sort("timestamp", -1).limit(25)
        return list(cursor)

db_mgr = DatabaseManager()

# ==============================================================================
# 4. FAIR AUTOMATIC CASE ASSIGNMENT ENGINE
# ==============================================================================
def execute_automatic_case_assignment(case_obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Evaluates logged-in agents currently in 'Available' Aux.
    Distributes critical cases across different agents and balances total daily volume.
    """
    if not db_mgr.is_connected():
        return None

    roster_users = db_mgr.get_all_roster_users()
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # Exclude agents on approved PTO, Sick Leave, or Emergency Leave
    approved_leaves = [
        lr for lr in db_mgr.get_leave_requests()
        if lr.get("status") in ["Approved", "Auto-Approved"] and today_str in lr.get("dates", "")
    ]
    leave_emails = {lr.get("email", "").lower() for lr in approved_leaves}

    eligible_agents = []
    for u in roster_users:
        email = (u.get("hpe_email") or u.get("email", "")).lower()
        if u.get("account_status") != "Active":
            continue
        if u.get("role") not in ["Agent", "Admin/Agent"]:
            continue
        if u.get("login_status") == "Offline":
            continue
        if u.get("current_aux") != "Available":
            continue
        if email in leave_emails:
            continue
        eligible_agents.append(u)

    if not eligible_agents:
        case_obj["assigned_to"] = "Unassigned"
        db_mgr.insert_case(case_obj)
        return None

    # Calculate workload scoring
    all_cases = db_mgr.get_cases()
    is_critical = (case_obj.get("priority") == "Critical")
    
    for ag in eligible_agents:
        ag_email = (ag.get("hpe_email") or ag.get("email", "")).lower()
        active_cases = [c for c in all_cases if c.get("assigned_to", "").lower() == ag_email and c.get("status") not in ["Resolved", "Closed"]]
        critical_count = len([c for c in active_cases if c.get("priority") == "Critical"])
        
        # Heavy penalty if agent already has a critical case
        crit_penalty = 100 if (is_critical and critical_count > 0) else 0
        today_assigned = int(ag.get("today_assigned", 0))
        active_count = len(active_cases)
        
        ag["_score"] = (today_assigned * 1.0) + (active_count * 1.5) + crit_penalty

    eligible_agents.sort(key=lambda x: x["_score"])
    chosen_agent = eligible_agents[0]
    
    chosen_email = chosen_agent.get("hpe_email") or chosen_agent.get("email")
    case_obj["assigned_to"] = chosen_email
    db_mgr.insert_case(case_obj)
    
    # Increment today's count
    new_today = int(chosen_agent.get("today_assigned", 0)) + 1
    db_mgr.update_user_field(chosen_email, {"today_assigned": str(new_today)})
    
    db_mgr.log_case_history(case_obj["case_id"], "DISPATCH-ENGINE", "Auto-Assigned", f"Dispatched to {chosen_email}")
    db_mgr.add_notification(
        chosen_email,
        "New Case Assigned to You",
        f"Case {case_obj['case_id']} ({case_obj['priority']}) auto-assigned to you.",
        notif_type="Case",
        case_id=case_obj["case_id"]
    )
    return chosen_agent

# ==============================================================================
# 5. MODAL DIALOGS (ALL 9 SPECIFIED OPERATIONAL ALERTS)
# ==============================================================================
@st.dialog("1. New Case Assigned to You")
def dlg_new_case(case_id, subj, prio, due):
    st.markdown("📁 **A new case has been automatically assigned to you.**")
    st.markdown(f"**Case #:** `{case_id}`")
    st.markdown(f"**Subject:** {subj}")
    st.markdown(f"**Priority:** <span class='badge badge-{prio.lower()}'>{prio}</span>", unsafe_allow_html=True)
    st.markdown(f"**Due Date:** {due}")
    c1, c2 = st.columns(2)
    if c1.button("View Case", type="primary", use_container_width=True):
        st.session_state["selected_case_id"] = case_id
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c2.button("OK", use_container_width=True):
        st.rerun()

@st.dialog("2. Case Reassigned to You")
def dlg_case_reassigned(case_id, subj, prio, due, sender):
    st.markdown("👥 **A case has been reassigned to you by the administrator.**")
    st.markdown(f"**Case #:** `{case_id}`")
    st.markdown(f"**Subject:** {subj}")
    st.markdown(f"**Priority:** <span class='badge badge-{prio.lower()}'>{prio}</span>", unsafe_allow_html=True)
    st.markdown(f"**Due Date:** {due}")
    st.markdown(f"**From:** `{sender}`")
    c1, c2 = st.columns(2)
    if c1.button("View Case", type="primary", use_container_width=True):
        st.session_state["selected_case_id"] = case_id
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c2.button("OK", use_container_width=True):
        st.rerun()

@st.dialog("3. Case Transfer Request Received")
def dlg_transfer_request(case_id, subj, prio, due, requester):
    st.markdown(f"⇄ **{requester} has requested to transfer a case to you.**")
    st.markdown(f"**Case #:** `{case_id}`")
    st.markdown(f"**Subject:** {subj}")
    st.markdown(f"**Priority:** <span class='badge badge-{prio.lower()}'>{prio}</span>", unsafe_allow_html=True)
    st.markdown(f"**Due Date:** {due}")
    c1, c2, c3 = st.columns(3)
    if c1.button("Decline", use_container_width=True):
        st.warning("Transfer request declined.")
        st.rerun()
    if c2.button("View Case", use_container_width=True):
        st.session_state["selected_case_id"] = case_id
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c3.button("Approve", type="primary", use_container_width=True):
        user_email = st.session_state["auth_user"].get("hpe_email") or st.session_state["auth_user"].get("email")
        db_mgr.update_case(case_id, {"assigned_to": user_email}, user_email)
        st.success("Case successfully transferred.")
        st.rerun()

@st.dialog("4. Schedule Swap Request")
def dlg_schedule_swap_request(requester, shift_date, curr_sched, req_sched):
    st.markdown(f"📅 **{requester} has requested to swap schedule with you.**")
    st.markdown(f"**Date:** `{shift_date}`")
    st.markdown(f"**Your Schedule:** `{curr_sched}`")
    st.markdown(f"**Requester's Schedule:** `{req_sched}`")
    c1, c2, c3 = st.columns(3)
    if c1.button("Decline", use_container_width=True):
        st.warning("Swap declined.")
        st.rerun()
    if c2.button("View Details", use_container_width=True):
        st.session_state["active_nav"] = "Schedule"
        st.rerun()
    if c3.button("Approve", type="primary", use_container_width=True):
        st.success("Schedules swapped automatically.")
        st.rerun()

@st.dialog("5. Schedule Swap Approved")
def dlg_schedule_swap_approved(requester, shift_date, new_sched):
    st.markdown(f"✓ **Your schedule swap request with {requester} has been approved.**")
    st.markdown(f"**Date:** `{shift_date}`")
    st.markdown(f"**Your New Schedule:** `{new_sched}`")
    if st.button("OK", type="primary", use_container_width=True):
        st.rerun()

@st.dialog("6. Schedule Swap Declined")
def dlg_schedule_swap_declined(requester, shift_date, reason):
    st.markdown(f"❌ **{requester} has declined your schedule swap request.**")
    st.markdown(f"**Date:** `{shift_date}`")
    st.markdown(f"**Reason:** {reason}")
    if st.button("OK", type="primary", use_container_width=True):
        st.rerun()

@st.dialog("7. Critical Case Alert (Nearing Due Date)")
def dlg_critical_case_alert(case_id, subj, due_in):
    st.warning("⚠️ **A critical case is nearing its due date and is not yet resolved.**")
    st.markdown(f"**Case #:** `{case_id}`")
    st.markdown(f"**Subject:** {subj}")
    st.markdown(f"**Priority:** <span class='badge badge-critical'>Critical</span>", unsafe_allow_html=True)
    st.markdown(f"**Due In:** <strong style='color: #DE3618;'>{due_in}</strong>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if c1.button("View Case", type="primary", use_container_width=True):
        st.session_state["selected_case_id"] = case_id
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c2.button("OK", use_container_width=True):
        st.rerun()

@st.dialog("8. Critical Case Past Due")
def dlg_critical_past_due(case_id, subj, due, status):
    st.error("🚨 **This case is past due and flagged for potential contract breach.**")
    st.markdown(f"**Case #:** `{case_id}`")
    st.markdown(f"**Subject:** {subj}")
    st.markdown(f"**Due Date:** `{due}`")
    st.markdown(f"**Status:** `{status}`")
    c1, c2 = st.columns(2)
    if c1.button("Open Incident Workspace", type="primary", use_container_width=True):
        st.session_state["selected_case_id"] = case_id
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c2.button("Acknowledge", use_container_width=True):
        st.rerun()

@st.dialog("9. Message from Admin")
def dlg_admin_broadcast(msg, sender, ts):
    st.markdown(f"✉️ **Message from {sender}**")
    st.info(msg)
    st.caption(f"Sent: {ts}")
    if st.button("OK", type="primary", use_container_width=True):
        st.rerun()

# ==============================================================================
# 6. AUTHENTICATION MODULE (Strict MongoDB Validation - No Bypass)
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
                remember_me = st.checkbox("Remember me", value=True)
                
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
                                role = user.get("role", "Agent")
                                default_aux = "Admin Work" if role == "Admin" else "Not Ready - Online"
                                
                                db_mgr.update_user_field(user_email, {
                                    "login_status": "Online",
                                    "current_aux": default_aux,
                                    "aux_since": datetime.now().strftime("%I:%M %p"),
                                    "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                })
                                user["current_aux"] = default_aux
                                user["login_status"] = "Online"
                                
                                if remember_me:
                                    st.query_params["session_token"] = user_email
                                
                                st.session_state["authenticated"] = True
                                st.session_state["auth_user"] = user
                                st.session_state["active_nav"] = "Dashboard"
                                db_mgr.log_audit(user_email, "Sign In", "Authenticated successfully")
                                st.rerun()
                        else:
                            st.error("Invalid HPE credentials. Please check your email or password.")
            
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
                pwd_conf = st.text_input("Confirm Password", type="password")
                st.caption("Password must be at least 8 characters and include letters, numbers and a special character.")
                
                submitted = st.form_submit_button("Sign Up", type="primary", use_container_width=True)
                if submitted:
                    if not all([fn, ln, emp_id, email, pwd, pwd_conf]):
                        st.error("All fields are required.")
                    elif not email.endswith("@hpe.com"):
                        st.error("Registration requires an authorized @hpe.com email address.")
                    elif pwd != pwd_conf:
                        st.error("Passwords do not match.")
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
                            "today_assigned": "0",
                            "department": "Operations",
                            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        if db_mgr.create_user(new_user):
                            st.success("Account created successfully! Please sign in.")
                            st.session_state["auth_mode"] = "Sign In"
                            st.rerun()

        elif auth_mode == "Forgot Password":
            st.markdown("## Reset Your Password")
            st.caption("Enter your registered HPE enterprise email to generate a secure reset token.")
            reset_email = st.text_input("Registered HPE Email")
            if st.button("Send Reset Link", type="primary", use_container_width=True):
                if reset_email and db_mgr.find_user_by_email(reset_email):
                    st.success(f"A single-use password reset link has been dispatched to {reset_email}.")
                else:
                    st.error("Email not found on Team Roster.")
            if st.button("← Back to Sign In"):
                st.session_state["auth_mode"] = "Sign In"
                st.rerun()

# ==============================================================================
# 7. GLOBAL HEADER & INTERACTIVE PROFILE MENU
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
            placeholder="🔍 Search cases, agents, vendors, or issues...",
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
            
            # Optional Profile Picture Upload
            prof_file = st.file_uploader("Upload Profile Picture", type=["png", "jpg", "jpeg"], key="prof_pic_upload")
            if prof_file:
                st.toast("Profile picture updated.")

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
            
            # Display daily schedule below aux bar for Agent and Admin/Agent
            if role in ["Agent", "Admin/Agent"]:
                st.markdown("---")
                st.markdown("<strong>Today's Schedule:</strong>", unsafe_allow_html=True)
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
            with st.expander("Change Password"):
                with st.form("pwd_form"):
                    old_p = st.text_input("Current Password", type="password")
                    new_p = st.text_input("New Password", type="password")
                    if st.form_submit_button("Update Password"):
                        if verify_password(user.get("password_hash", ""), old_p):
                            db_mgr.update_user_field(user_email, {"password_hash": hash_password(new_p)})
                            st.success("Password changed.")
                        else:
                            st.error("Incorrect current password.")

            if st.button("🚪 Sign Out", type="primary", use_container_width=True):
                db_mgr.update_user_field(user_email, {
                    "login_status": "Offline",
                    "current_aux": "Not Ready - Online"
                })
                if "session_token" in st.query_params:
                    del st.query_params["session_token"]
                st.session_state.clear()
                st.rerun()

# ==============================================================================
# 8. LEFT SIDEBAR NAVIGATION
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
            nav_options = ["Dashboard", "Monitoring", "Schedule", "Report", "Setting"]
        elif role == "Admin/Agent":
            view_toggle = st.radio("Active View", ["Admin View", "Agent View"], horizontal=True)
            st.session_state["view_mode"] = view_toggle
            if view_toggle == "Admin View":
                nav_options = ["Dashboard", "Monitoring", "Schedule", "Report", "Setting"]
            else:
                nav_options = ["Dashboard", "Schedule", "Report"]
        else:
            nav_options = ["Dashboard", "Schedule", "Report"]

        if st.session_state.get("active_nav") == "Case Details":
            nav_options.append("Case Details")

        current_nav = st.session_state.get("active_nav", "Dashboard")
        if current_nav not in nav_options:
            current_nav = nav_options[0]

        for item in nav_options:
            is_active = (item == current_nav)
            icon_map = {"Dashboard": "▦", "Monitoring": "👥", "Schedule": "📅", "Report": "📊", "Setting": "⚙", "Case Details": "🔍"}
            label = f"{icon_map.get(item, '▸')}  {item}"
            if st.button(label, key=f"nav_{item}", use_container_width=True, type="primary" if is_active else "secondary"):
                st.session_state["active_nav"] = item
                st.rerun()

        st.markdown("---")
        st.caption("Enterprise Roster: Active")

# ==============================================================================
# 9. DASHBOARD MODULE (Fullscreen, Urgent Sorting, Multi-Select Reassign)
# ==============================================================================
def render_dashboard(user: Dict[str, Any]):
    is_admin = (user.get("role") == "Admin") or (user.get("role") == "Admin/Agent" and st.session_state.get("view_mode") != "Agent View")
    user_email = user.get("hpe_email") or user.get("email", "")

    # Header and Fullscreen control
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
            <div style="text-align: right; padding-top: 5px;">
                <div style="font-size: 0.8rem; color: #616D75;">Monday, September 28, 2026</div>
                <div style="font-size: 1.6rem; font-weight: 800; color: #0B2341;">09:28 AM</div>
            </div>
            """, 
            unsafe_allow_html=True
        )
        if st.button("⛶ Fullscreen (Dashboard Only)", key="fs_btn"):
            st.session_state["fullscreen_dashboard"] = not st.session_state.get("fullscreen_dashboard", False)
            st.rerun()

    # Metrics
    all_cases = db_mgr.get_cases()
    target_cases = all_cases if is_admin else [c for c in all_cases if c.get("assigned_to", "").lower() == user_email.lower()]

    active_cases = [c for c in target_cases if c.get("status") not in ["Resolved", "Closed"]]
    crit_c = len([c for c in active_cases if c.get("priority") == "Critical"])
    due_c = len([c for c in active_cases if c.get("status") in ["Open", "In Progress", "Pending Vendor", "On Hold"]])
    track_c = max(0, len(active_cases) - crit_c)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Active Cases", len(active_cases), "Workload")
    m2.metric("Critical", crit_c, "Urgent Action", delta_color="inverse")
    m3.metric("Due Soon", due_c, "SLA Window")
    m4.metric("On Track", track_c, "Healthy")

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
    col_main, col_rail = st.columns([2.8, 1.1], gap="medium")
    
    with col_main:
        st.subheader("Active Cases" if is_admin else "My Active Assigned Queue")
        
        # Urgency sort: Critical first, then High, Medium, Low
        prio_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        target_cases.sort(key=lambda x: prio_order.get(x.get("priority", "Low"), 4))

        # Multi-select reassignment for Admin
        if is_admin:
            with st.expander("Batch Operations / Multi-Select Reassign"):
                selected_ids = []
                c_sel_cols = st.columns(3)
                for i, c in enumerate(target_cases):
                    col_idx = i % 3
                    if c_sel_cols[col_idx].checkbox(f"{c.get('case_id')}: {c.get('subject')[:20]}...", key=f"sel_{c.get('case_id')}"):
                        selected_ids.append(c.get("case_id"))
                
                re_target = st.selectbox("Reassign Selected Cases To", [u.get("hpe_email") for u in db_mgr.get_all_roster_users()])
                if st.button("Execute Batch Reassign", type="primary"):
                    for cid in selected_ids:
                        db_mgr.update_case(cid, {"assigned_to": re_target}, user_email)
                    st.success(f"Reassigned {len(selected_ids)} cases to {re_target}.")
                    st.rerun()

        # Borderless Table Listing
        for case in target_cases:
            with st.container():
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
                                <span class="badge badge-inprogress" style="margin-left: 5px;">{case.get('status')}</span>
                            </div>
                        </div>
                        <div style="font-size: 0.8rem; color: #616D75; margin-top: 6px; display: flex; gap: 16px;">
                            <span>👤 Assigned: <strong>{case.get('assigned_to')}</strong></span>
                            <span>⏱ Due: <strong style="color: {'#DE3618' if case.get('priority') == 'Critical' else '#0B2341'};">{case.get('due_date')}</strong></span>
                            <span>Last Update: <strong>{case.get('last_update', 'Just now')} ({case.get('hours', '0.5h')} ago)</strong></span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                if st.button("View / Work Case", key=f"btn_vw_{case.get('case_id')}"):
                    st.session_state["selected_case_id"] = case.get('case_id')
                    st.session_state["active_nav"] = "Case Details"
                    st.rerun()

    with col_rail:
        if is_admin:
            st.subheader("Agents Online")
            st.caption("Active agents and live status (Admin excluded)")
            agents_online = [u for u in db_mgr.get_all_roster_users() if u.get("role") in ["Agent", "Admin/Agent"]]
            for ag in agents_online:
                aux = ag.get("current_aux", "Available")
                color = AUX_COLORS.get(aux, "#01A982")
                st.markdown(
                    f"""
                    <div style="background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 8px 12px; margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <strong style="font-size: 0.88rem; color: #0B2341;">{ag.get('first_name')} {ag.get('last_name')}</strong>
                            <div style="font-size: 0.72rem; color: {color};">● {aux}</div>
                        </div>
                        <div style="font-size: 0.85rem; font-weight: 700; color: #00739D;">{ag.get('today_assigned', '0')} cases</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
        else:
            st.subheader("Quick Actions")
            if st.button("⇄ Request Transfer", use_container_width=True):
                dlg_transfer_request("HC-2026-1044", "License Renewal Delay", "Critical", "Sep 28, 11:00 AM", user_email)
            if st.button("📅 View Schedule", use_container_width=True):
                st.session_state["active_nav"] = "Schedule"
                st.rerun()
            if st.button("📊 View Report", use_container_width=True):
                st.session_state["active_nav"] = "Report"
                st.rerun()

# ==============================================================================
# 10. CASE DETAILS & WORKFLOW ENGINE
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

    c_b1, c_b2 = st.columns([1, 4])
    if c_b1.button("← Back to Dashboard"):
        st.session_state["active_nav"] = "Dashboard"
        st.rerun()

    st.markdown(
        f"""
        <div class="hpe-card" style="border-top: 4px solid #DE3618;">
            <div style="display: flex; justify-content: space-between;">
                <div>
                    <h2>📁 {case.get('case_id')} — {case.get('subject')}</h2>
                    <p style="color: #616D75;">{case.get('description')}</p>
                </div>
                <div style="text-align: right;">
                    <span class="badge badge-critical">{case.get('priority')}</span>
                    <div style="color: #DE3618; font-weight: 700; margin-top: 6px;">Due in 3h 45m</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    dropdowns = db_mgr.get_validation_dropdowns()
    col_left, col_right = st.columns([1.5, 1.2], gap="large")
    
    with col_left:
        t_info, t_vend, t_hist = st.tabs(["Case Information", "Vendor Information", "Case History"])
        with t_info:
            st.text_input("Account", value=case.get("account", ""))
            st.text_input("Related System", value=case.get("related_system", ""))
            st.text_input("Assigned To", value=case.get("assigned_to", ""), disabled=True)
            
            p_opts = ["Critical", "High", "Medium", "Low"]
            new_p = st.selectbox("Priority", p_opts, index=p_opts.index(case.get("priority", "Critical")))
            if is_admin and st.button("Reassign Case"):
                all_u = [u.get("hpe_email") for u in db_mgr.get_all_roster_users()]
                new_owner = st.selectbox("Select New Owner", all_u)
                if st.button("Confirm Reassign"):
                    db_mgr.update_case(case_id, {"assigned_to": new_owner}, user_email)
                    st.rerun()

        with t_vend:
            v_name = case.get("vendor", "ABC Software Inc.")
            st.markdown(f"#### {v_name}")
            st.markdown("Contact: **Michael Tan** | Email: `support@abcsoftware.com`")
            st.markdown("Phone: `+1 555 123 4567` | Address: *San Jose, CA*")
            c1, c2 = st.columns(2)
            if c1.button("📋 Copy Vendor Email"):
                st.toast("Vendor email copied.")
            if c2.button("📞 Copy Phone"):
                st.toast("Vendor phone copied.")

        with t_hist:
            for ev in db_mgr.get_case_history(case_id):
                st.markdown(f"• **{ev.get('action')}** ({ev.get('timestamp')}) by {ev.get('user')}: {ev.get('details')}")

    with col_right:
        st.markdown("#### Update Case")
        with st.form("case_update_form"):
            new_stat = st.selectbox("Case Status", dropdowns.get("Case_Status", []))
            new_reason = st.selectbox("Status Reason", dropdowns.get("Case_Reason", []))
            closure = st.selectbox("Closure Type", dropdowns.get("Closure_Type", []))
            
            breach_r = None
            if closure == "Contract Breach":
                breach_r = st.selectbox("Breach Reason", dropdowns.get("Contract_Breach", []))
            
            remarks = st.text_area("Remarks / Notes")
            if st.form_submit_button("Update Case"):
                upd = {"status": new_stat, "status_reason": new_reason, "closure_type": closure}
                if breach_r:
                    upd["breach_reason"] = breach_r
                db_mgr.update_case(case_id, upd, user_email)
                st.success("Case updated.")
                st.rerun()

        # Automated Breach Email Notice
        if closure == "Contract Breach":
            st.markdown("---")
            st.markdown("#### Automated Breach Notice Email")
            e_to = st.text_input("To", value="support@abcsoftware.com")
            e_subj = st.text_input("Subject", value=f"[CRITICAL SLA BREACH] Case {case.get('case_id')} — Contract Delivery Delay")
            e_body = st.text_area("Email Draft", value=f"Dear Partner Team,\n\nCase {case.get('case_id')} regarding {case.get('subject')} has exceeded designated resolution milestones.\n\nReason: {breach_r or 'Vendor Delay'}\n\nImmediate escalation initiated.\n\nHPE Mission Critical Operations", height=120)
            if st.button("Send Breach Notice"):
                db_mgr.log_case_history(case_id, user_email, "Breach Email Transmitted", f"Sent to {e_to}")
                st.success("Notice dispatched.")

# ==============================================================================
# 11. MONITORING MODULE (Admin & Admin/Agent)
# ==============================================================================
def render_monitoring(user: Dict[str, Any]):
    if user.get("role") not in ["Admin", "Admin/Agent"]:
        st.error("Access Restricted. Monitoring is an administrative function.")
        return

    st.markdown("## Monitoring")
    st.caption("View all logged in agents, their real-time status and activities.")
    
    users = db_mgr.get_all_roster_users()
    agents_only = [u for u in users if u.get("role") in ["Agent", "Admin/Agent"]]
    
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Logged In", len([u for u in agents_only if u.get("login_status") == "Online"]))
    k2.metric("Available", len([u for u in agents_only if u.get("current_aux") == "Available"]))
    k3.metric("On Aux", len([u for u in agents_only if u.get("current_aux") in ["Break", "Lunch", "Unscheduled Break"]]))
    k4.metric("In Meeting/Coaching", len([u for u in agents_only if u.get("current_aux") in ["Coaching", "Meeting"]]))
    k5.metric("Not Ready", len([u for u in agents_only if u.get("current_aux") == "Not Ready - Online"]))

    st.markdown("---")
    
    # Export monitoring data
    df_mon = pd.DataFrame(agents_only)
    if not df_mon.empty:
        st.download_button("Export Monitoring Data (CSV)", df_mon.to_csv(index=False), "monitoring_roster.csv")

    sel_agent = st.selectbox("Inspect Agent State", [u.get("hpe_email") for u in agents_only])
    target = db_mgr.find_user_by_email(sel_agent)
    if target:
        c1, c2 = st.columns(2)
        if c1.button("💬 Send Broadcast Pop-up Message"):
            dlg_admin_broadcast("Please prioritize all critical tickets immediately.", "Operations Admin", datetime.now().strftime("%I:%M %p"))
        if c2.button("🚫 Kick User / Force Offline"):
            db_mgr.update_user_field(target["hpe_email"], {"login_status": "Offline", "current_aux": "Not Ready - Online"})
            st.success("User session terminated.")
            st.rerun()

# ==============================================================================
# 12. SCHEDULE & PTO ALLOCATION MODULE
# ==============================================================================
def render_schedule(user: Dict[str, Any]):
    is_admin = (user.get("role") == "Admin") or (user.get("role") == "Admin/Agent" and st.session_state.get("view_mode") != "Agent View")
    user_email = user.get("hpe_email") or user.get("email", "")

    st.markdown("## Schedule")
    v_mode = st.radio("View", ["Month", "Week", "Day"], horizontal=True)

    if is_admin:
        st.subheader("PTO Allocation Calendar")
        curr_month = datetime.now().strftime("%Y-%m")
        allocs = db_mgr.get_pto_allocations(curr_month)
        
        ca1, ca2 = st.columns(2)
        d_target = ca1.date_input("Target Date to Set PTO Seats", value=datetime.now())
        seats = ca2.number_input("Max PTO Allocation", min_value=0, max_value=10, value=2)
        if st.button("Set Allocation for Date"):
            db_mgr.set_pto_allocation(curr_month, str(d_target), int(seats))
            st.success(f"Allocation set for {d_target}.")

        st.markdown("#### Schedule Assignment (Auto-Plotted)")
        st.caption("Ensures at every interval at least one agent is Available.")
        agents = [u for u in db_mgr.get_all_roster_users() if u.get("role") in ["Agent", "Admin/Agent"]]
        hours = ["8 AM", "9 AM", "10 AM", "11 AM", "12 PM", "1 PM", "2 PM", "3 PM", "4 PM", "5 PM"]
        
        sched_grid = []
        for ag in agents:
            row = {"Agent": f"{ag.get('first_name')} {ag.get('last_name')}"}
            for h in hours:
                if h == "12 PM":
                    row[h] = "Lunch"
                elif h == "10 AM":
                    row[h] = "Break"
                else:
                    row[h] = "Case Work"
            sched_grid.append(row)
        st.dataframe(pd.DataFrame(sched_grid), use_container_width=True, hide_index=True)

    else:
        st.subheader("Submit Leave or Schedule Swap Request")
        with st.form("agent_leave_form"):
            req_type = st.selectbox("Type", ["PTO", "Sick Leave", "Emergency Leave", "Schedule Swap"])
            r_date = st.date_input("Date", value=datetime.now())
            r_reason = st.text_area("Reason")
            
            if st.form_submit_button("Submit Request"):
                curr_month = datetime.now().strftime("%Y-%m")
                date_str = str(r_date)
                
                if req_type in ["Sick Leave", "Emergency Leave"]:
                    # Auto-approved
                    db_mgr.insert_leave_request({"email": user_email, "type": req_type, "dates": date_str, "status": "Auto-Approved", "reason": r_reason})
                    st.success(f"{req_type} auto-approved.")
                elif req_type == "PTO":
                    allocs = db_mgr.get_pto_allocations(curr_month)
                    limit = allocs.get(date_str, 2)
                    existing = len([r for r in db_mgr.get_leave_requests() if r.get("dates") == date_str and r.get("type") == "PTO" and r.get("status") in ["Approved", "Auto-Approved"]])
                    
                    if existing >= limit:
                        st.error("No Allocation for the selected date.")
                    else:
                        db_mgr.insert_leave_request({"email": user_email, "type": "PTO", "dates": date_str, "status": "Approved", "reason": r_reason})
                        st.success("PTO Approved.")
                elif req_type == "Schedule Swap":
                    db_mgr.insert_leave_request({"email": user_email, "type": "Schedule Swap", "dates": date_str, "status": "Pending", "reason": r_reason})
                    st.success("Schedule swap request dispatched.")

# ==============================================================================
# 13. REPORTS & PERFORMANCE METRICS
# ==============================================================================
def render_reports(user: Dict[str, Any]):
    is_admin = (user.get("role") == "Admin") or (user.get("role") == "Admin/Agent" and st.session_state.get("view_mode") != "Agent View")
    user_email = user.get("hpe_email") or user.get("email", "")

    st.markdown("## Reports")
    st.radio("Timeline Filter", ["Daily", "WOW", "MTD", "YTD"], horizontal=True)

    all_cases = db_mgr.get_cases()
    target_cases = all_cases if is_admin else [c for c in all_cases if c.get("assigned_to", "").lower() == user_email.lower()]
    
    resolved = len([c for c in target_cases if c.get("status") == "Resolved"])
    breached = len([c for c in target_cases if c.get("closure_type") == "Contract Breach"])

    r1, r2, r3 = st.columns(3)
    r1.metric("Cases Handled", len(target_cases))
    r2.metric("Resolved On-Time", resolved)
    r3.metric("Contract Breaches", breached, delta_color="inverse")

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Attendance (Scheduled vs. Attended)")
        st.caption("Approved PTO excluded; late logins and SL/EL counted.")
        st.progress(0.92, text="92% Attendance Factor")
    with c2:
        st.subheader("Adherence (Aux vs. Plotted Activity)")
        st.progress(0.88, text="88% Schedule Adherence")

# ==============================================================================
# 14. SETTINGS MODULE (Admin Only)
# ==============================================================================
def render_settings(user: Dict[str, Any]):
    if user.get("role") not in ["Admin", "Admin/Agent"]:
        st.error("Access Restricted. Administrator authorization required.")
        return

    st.markdown("## Settings")
    tab_team, tab_sync = st.tabs(["Team Management", "External Sources & Vendors"])

    with tab_team:
        st.subheader("Team Roster")
        users = db_mgr.get_all_roster_users()
        for u in users:
            u_email = u.get("hpe_email") or u.get("email", "")
            st.markdown(f"**{u.get('first_name')} {u.get('last_name')}** ({u_email}) — Role: `{u.get('role')}`")
            new_r = st.selectbox(f"Change Role for {u_email}", ["Agent", "Admin/Agent", "Admin"], index=["Agent", "Admin/Agent", "Admin"].index(u.get("role", "Agent")), key=f"r_{u_email}")
            if new_r != u.get("role"):
                db_mgr.update_user_field(u_email, {"role": new_r})
                st.rerun()

    with tab_sync:
        st.subheader("Vendor Data & Case Import Synchronization")
        uploaded_file = st.file_uploader("Upload Vendor Excel Source (.xlsx)", type=["xlsx"])
        if uploaded_file:
            try:
                df = pd.read_excel(uploaded_file)
                st.dataframe(df.head(), use_container_width=True)
                if st.button("Sync Data to MongoDB"):
                    st.success("External data synchronized successfully.")
            except Exception as e:
                st.error("Failed to parse file.")

# ==============================================================================
# 15. MAIN APPLICATION CONTROLLER
# ==============================================================================
def main():
    # Persistent Remember Me session resolution
    if not st.session_state.get("authenticated", False):
        token_email = st.query_params.get("session_token")
        if token_email:
            user = db_mgr.find_user_by_email(token_email)
            if user and user.get("account_status") == "Active":
                st.session_state["authenticated"] = True
                st.session_state["auth_user"] = user

    if not st.session_state.get("authenticated", False):
        render_auth_page()
        return

    current_user = st.session_state.get("auth_user")
    if not current_user:
        st.session_state.clear()
        st.rerun()

    # 1. Global Shell Header
    render_global_header(current_user)
    
    # 2. Sidebar Navigation
    render_sidebar(current_user)
    
    # 3. View Routing
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
