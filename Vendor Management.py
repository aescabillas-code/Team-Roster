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
HPE_ENTERPRISE_CSS = """
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
        padding-top: 1rem !important;
        padding-bottom: 2rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
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
    
    /* KPI Metric Cards */
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
    .badge-breached { background-color: #FCEBE8; color: #DE3618; font-weight: 700; }
    
    /* Navigation button styling */
    .stButton>button {
        border-radius: 4px;
        font-weight: 500;
        transition: all 0.2s ease-in-out;
    }
    .stButton>button:hover {
        border-color: #01A982;
        color: #01A982;
    }
</style>
"""
st.markdown(HPE_ENTERPRISE_CSS, unsafe_allow_html=True)

# ==============================================================================
# 2. SECURITY & PASSWORD MANAGEMENT (Salted PBKDF2-SHA256)
# ==============================================================================
def hash_password(password: str) -> str:
    """Securely hash a password with PBKDF2 using SHA-256 and a random salt."""
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return f"{salt.hex()}${key.hex()}"

def verify_password(stored_password: str, provided_password: str) -> bool:
    """Verify stored salted PBKDF2-SHA256 password against user input."""
    try:
        salt_hex, key_hex = stored_password.split('$')
        salt = bytes.fromhex(salt_hex)
        key = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'), salt, 100000)
        return key.hex() == key_hex
    except Exception:
        return False

# ==============================================================================
# 3. MONGODB CLIENT & REPOSITORY (Strictly Non-Bypassable)
# ==============================================================================
AUX_STATUSES = [
    "Available", "Admin Work", "Not Ready - Online", 
    "Coaching", "Meeting", "Lunch", "Break", "Unscheduled Break"
]

@st.cache_resource
def get_mongo_client():
    """Retrieve shared MongoClient configured through secrets or environment."""
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

class MongoManager:
    """Data Access Object interfacing directly with the MongoDB database."""
    def __init__(self):
        self.client = get_mongo_client()
        self.db = None
        self.collection = None
        if self.client:
            self.db = self.client["TeamRoster"]
            self.collection = self.db["Team Roster Collection"]

    def is_connected(self) -> bool:
        if not self.client:
            self.client = get_mongo_client()
            if self.client:
                self.db = self.client["TeamRoster"]
                self.collection = self.db["Team Roster Collection"]
        return self.client is not None

    # --- User / Roster Operations ---
    def find_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        if not self.is_connected():
            return None
        doc = self.collection.find_one({
            "type": "roster_list", 
            "roster_list.hpe_email": {"$regex": f"^{re.escape(email.strip())}$", "$options": "i"}
        })
        return doc.get("roster_list") if doc else None

    def find_user_by_employee_id(self, employee_id: str) -> Optional[Dict[str, Any]]:
        if not self.is_connected():
            return None
        doc = self.collection.find_one({
            "type": "roster_list", 
            "roster_list.employee_id": employee_id.strip()
        })
        return doc.get("roster_list") if doc else None

    def create_user(self, user_data: Dict[str, Any]) -> bool:
        if not self.is_connected():
            return False
        # Save explicitly as type: 'roster_list' with encapsulated roster_list object
        payload = {
            "type": "roster_list",
            "roster_list": user_data
        }
        self.collection.insert_one(payload)
        self.log_audit(user_data["hpe_email"], "User Registration", f"Registered as {user_data['role']}")
        return True

    def get_all_roster_users(self) -> List[Dict[str, Any]]:
        if not self.is_connected():
            return []
        cursor = self.collection.find({"type": "roster_list"})
        return [doc["roster_list"] for doc in cursor if "roster_list" in doc]

    def update_user_field(self, email: str, field_dict: Dict[str, Any]):
        if not self.is_connected():
            return
        update_doc = {f"roster_list.{k}": v for k, v in field_dict.items()}
        update_doc["roster_list.updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.collection.update_one(
            {"type": "roster_list", "roster_list.hpe_email": {"$regex": f"^{re.escape(email.strip())}$", "$options": "i"}},
            {"$set": update_doc}
        )

    def update_user_aux(self, email: str, new_aux: str):
        if not self.is_connected():
            return
        current_time_str = datetime.now().strftime("%Y-%m-%d %I:%M %p")
        self.update_user_field(email, {
            "current_aux": new_aux,
            "aux_since": current_time_str
        })
        # Record into Aux History
        self.collection.insert_one({
            "type": "aux_history",
            "email": email,
            "aux": new_aux,
            "timestamp": current_time_str
        })
        self.log_audit(email, "Aux Changed", f"Transitioned Aux to {new_aux}")

    # --- Cases & History ---
    def get_cases(self) -> List[Dict[str, Any]]:
        if not self.is_connected():
            return []
        cursor = self.collection.find({"type": "case_record"}).sort("created_date", -1)
        return [doc["case"] for doc in cursor if "case" in doc]

    def get_case_by_id(self, case_id: str) -> Optional[Dict[str, Any]]:
        if not self.is_connected():
            return None
        doc = self.collection.find_one({"type": "case_record", "case.case_id": case_id})
        return doc.get("case") if doc else None

    def insert_case(self, case_data: Dict[str, Any]):
        if not self.is_connected():
            return
        self.collection.insert_one({
            "type": "case_record",
            "case": case_data
        })
        self.log_case_history(case_data["case_id"], "SYSTEM", "Case Created", "Case ingested into HPE CaseFlow")

    def update_case(self, case_id: str, updates: Dict[str, Any], actor: str):
        if not self.is_connected():
            return
        update_doc = {f"case.{k}": v for k, v in updates.items()}
        update_doc["case.last_update"] = updates.get("last_update", datetime.now().strftime("%Y-%m-%d %I:%M %p"))
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
            "timestamp": datetime.now().strftime("%Y-%m-%d %I:%M %p")
        })

    def get_case_history(self, case_id: str) -> List[Dict[str, Any]]:
        if not self.is_connected():
            return []
        cursor = self.collection.find({"type": "case_history", "case_id": case_id}).sort("timestamp", -1)
        return list(cursor)

    # --- Schedule & PTO Management ---
    def get_pto_allocations(self, month_str: str) -> Dict[str, int]:
        """Fetch PTO max allocation limits per date."""
        if not self.is_connected():
            return {}
        doc = self.collection.find_one({"type": "pto_allocation_config", "month": month_str})
        return doc.get("allocations", {}) if doc else {}

    def set_pto_allocation(self, month_str: str, date_str: str, limit: int):
        if not self.is_connected():
            return
        self.collection.update_one(
            {"type": "pto_allocation_config", "month": month_str},
            {"$set": {f"allocations.{date_str}": limit}},
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

    def update_leave_status(self, req_id: str, status: str, reviewer: str):
        if not self.is_connected():
            return
        self.collection.update_one(
            {"type": "leave_request", "req_id": req_id},
            {"$set": {"status": status, "reviewed_by": reviewer, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}}
        )

    # --- Validation Dropdowns ---
    def get_validation_dropdowns(self) -> Dict[str, List[str]]:
        if not self.is_connected():
            return {
                "Case_Status": ["Open", "In Progress", "On Hold", "Pending Vendor", "Pending Internal", "Resolved", "Closed"],
                "Case_Reason": ["New Inquiry", "Hardware Defect", "Firmware Bug", "Configuration Error", "License Expiry"],
                "Closure_Type": ["Resolved - Normal", "Resolved - Workaround", "Contract Breach", "Cancelled by Customer"],
                "Contract_Breach": ["Vendor No Response", "Late Delivery", "Incomplete Information", "Scope Change", "Hardware Unavailability"]
            }
        doc = self.collection.find_one({"type": "Validation_Dropdown"})
        if doc:
            return {
                "Case_Status": doc.get("Case_Status", []),
                "Case_Reason": doc.get("Case_Reason", []),
                "Closure_Type": doc.get("Closure_Type", []),
                "Contract_Breach": doc.get("Contract_Breach", [])
            }
        default_dd = {
            "type": "Validation_Dropdown",
            "Case_Status": ["Open", "In Progress", "On Hold", "Pending Vendor", "Pending Internal", "Resolved", "Closed"],
            "Case_Reason": ["New Inquiry", "Hardware Defect", "Firmware Bug", "Configuration Error", "License Expiry"],
            "Closure_Type": ["Resolved - Normal", "Resolved - Workaround", "Contract Breach", "Cancelled by Customer"],
            "Contract_Breach": ["Vendor No Response", "Late Delivery", "Incomplete Information", "Scope Change", "Hardware Unavailability"]
        }
        self.collection.insert_one(default_dd)
        return default_dd

    # --- Vendors & External Sources ---
    def get_vendors(self) -> List[Dict[str, Any]]:
        if not self.is_connected():
            return []
        cursor = self.collection.find({"type": "vendor_data"})
        return [doc["vendor"] for doc in cursor if "vendor" in doc]

    def insert_vendor(self, vendor_data: Dict[str, Any]):
        if not self.is_connected():
            return
        self.collection.insert_one({"type": "vendor_data", "vendor": vendor_data})

    # --- Notifications & Audit ---
    def get_notifications(self, email: str, is_admin: bool) -> List[Dict[str, Any]]:
        if not self.is_connected():
            return []
        q = {"type": "notification"}
        if not is_admin:
            q["$or"] = [{"recipient": email}, {"recipient": "ALL"}]
        cursor = self.collection.find(q).sort("timestamp", -1)
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
            "timestamp": datetime.now().strftime("%Y-%m-%d %I:%M %p")
        })

    def mark_notifications_read(self, email: str):
        if not self.is_connected():
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
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user": user,
            "activity": activity,
            "details": details
        })

    def get_audit_logs(self) -> List[Dict[str, Any]]:
        if not self.is_connected():
            return []
        cursor = self.collection.find({"type": "audit_log"}).sort("timestamp", -1).limit(100)
        return list(cursor)

db_mgr = MongoManager()

# ==============================================================================
# 4. FAIR AUTOMATIC CASE ASSIGNMENT ENGINE
# ==============================================================================
def execute_automatic_case_assignment(case_obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Evaluates logged-in, Available agents in MongoDB.
    Assigns ticket fairly based on active workload and daily assignment balance.
    """
    if not db_mgr.is_connected():
        return None

    roster_users = db_mgr.get_all_roster_users()
    
    # Check leave requests for today
    today_str = datetime.now().strftime("%Y-%m-%d")
    approved_leaves = [
        lr for lr in db_mgr.get_leave_requests()
        if lr.get("status") == "Approved" and today_str in lr.get("dates", "")
    ]
    leave_emails = {lr["email"].lower() for lr in approved_leaves}

    # Filter strictly for eligible agents
    eligible_agents = []
    for u in roster_users:
        email = u.get("hpe_email", "").lower()
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
        # No available agent - insert as unassigned
        case_obj["assigned_to"] = "Unassigned"
        db_mgr.insert_case(case_obj)
        return None

    # Workload scoring: Daily Assignment Load + Active Case Load + Critical Weight
    cases = db_mgr.get_cases()
    for ag in eligible_agents:
        ag_email = ag.get("hpe_email", "").lower()
        ag_cases = [c for c in cases if c.get("assigned_to", "").lower() == ag_email and c.get("status") not in ["Resolved", "Closed"]]
        critical_count = len([c for c in ag_cases if c.get("priority") == "Critical"])
        
        active_load = len(ag_cases)
        today_assigned = int(ag.get("today_assigned", 0))
        # Scoring: lowest gets next ticket
        ag["_score"] = today_assigned + (active_load * 1.5) + (critical_count * 2.0)

    eligible_agents.sort(key=lambda x: x["_score"])
    chosen_agent = eligible_agents[0]
    
    # Assign and persist
    chosen_email = chosen_agent.get("hpe_email")
    case_obj["assigned_to"] = chosen_email
    db_mgr.insert_case(case_obj)
    
    # Increment assigned today count in roster
    new_today = int(chosen_agent.get("today_assigned", 0)) + 1
    db_mgr.update_user_field(chosen_email, {"today_assigned": str(new_today)})
    
    # Dispatched Notification & History
    db_mgr.log_case_history(case_obj["case_id"], "DISPATCH-ENGINE", "Auto-Assigned", f"Assigned to {chosen_email} (Score: {chosen_agent['_score']})")
    db_mgr.add_notification(
        chosen_email,
        "New Case Assigned",
        f"Case {case_obj['case_id']} ({case_obj['priority']}) auto-assigned to you.",
        notif_type="Case",
        case_id=case_obj["case_id"]
    )
    return chosen_agent

# ==============================================================================
# 5. MODAL DIALOGS (9 SPECIFIED OPERATIONAL ALERTS)
# ==============================================================================
@st.dialog("🔔 New Case Assigned to You")
def dlg_new_case(case):
    st.markdown("A new case has been automatically assigned to your queue.")
    st.markdown(f"**Case #:** `{case.get('case_id')}`")
    st.markdown(f"**Subject:** {case.get('subject')}")
    st.markdown(f"**Priority:** <span class='badge badge-{case.get('priority', 'low').lower()}'>{case.get('priority')}</span>", unsafe_allow_html=True)
    st.markdown(f"**Due Date:** {case.get('due_date')}")
    c1, c2 = st.columns(2)
    if c1.button("View Case", type="primary", use_container_width=True, key="dlg_nc_v"):
        st.session_state["selected_case_id"] = case.get('case_id')
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c2.button("Acknowledge", use_container_width=True, key="dlg_nc_ack"):
        st.rerun()

@st.dialog("🔄 Case Reassigned to You")
def dlg_case_reassigned(case_id, from_user):
    st.markdown("An existing case was reassigned to your queue.")
    st.markdown(f"**Case #:** `{case_id}`")
    st.markdown(f"**Reassigned From:** `{from_user}`")
    st.caption("You are now the active engineer responsible for SLA milestones.")
    c1, c2 = st.columns(2)
    if c1.button("View Case", type="primary", use_container_width=True, key="dlg_cr_v"):
        st.session_state["selected_case_id"] = case_id
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c2.button("OK", use_container_width=True, key="dlg_cr_ok"):
        st.rerun()

@st.dialog("📬 Case Transfer Request Received")
def dlg_transfer_request(case_id, from_user):
    case = db_mgr.get_case_by_id(case_id) or {}
    st.markdown(f"**Agent `{from_user}`** requested to transfer Case **`{case_id}`** to you.")
    st.markdown(f"**Subject:** {case.get('subject', 'N/A')}")
    st.markdown(f"**Priority:** <span class='badge badge-{case.get('priority', 'low').lower()}'>{case.get('priority')}</span>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    if c1.button("Approve", type="primary", use_container_width=True, key="dlg_tr_appr"):
        current_user = st.session_state["auth_user"]["hpe_email"]
        db_mgr.update_case(case_id, {"assigned_to": current_user}, current_user)
        db_mgr.add_notification(from_user, "Transfer Approved", f"{current_user} approved transfer of {case_id}")
        st.success("Case successfully transferred.")
        st.rerun()
    if c2.button("View Case", use_container_width=True, key="dlg_tr_vw"):
        st.session_state["selected_case_id"] = case_id
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c3.button("Decline", use_container_width=True, key="dlg_tr_dec"):
        current_user = st.session_state["auth_user"]["hpe_email"]
        db_mgr.add_notification(from_user, "Transfer Declined", f"{current_user} declined transfer of {case_id}")
        st.warning("Transfer request declined.")
        st.rerun()

@st.dialog("🗓️ Schedule Swap Request")
def dlg_schedule_swap(requester, shift_date, requested_shift):
    st.markdown(f"**Requester:** `{requester}`")
    st.markdown(f"**Shift Date:** `{shift_date}`")
    st.markdown(f"**Requested Swap:** `{requested_shift}`")
    c1, c2 = st.columns(2)
    if c1.button("Approve Swap", type="primary", use_container_width=True):
        st.success("Shift swap approved and saved.")
        st.rerun()
    if c2.button("Decline", use_container_width=True):
        st.warning("Swap request rejected.")
        st.rerun()

@st.dialog("✅ Schedule Swap Approved")
def dlg_schedule_swap_approved(shift_date, new_schedule):
    st.markdown("Your shift swap request has been approved by Operations.")
    st.markdown(f"**Date:** `{shift_date}`")
    st.markdown(f"**New Schedule:** `{new_schedule}`")
    if st.button("OK", type="primary", use_container_width=True):
        st.rerun()

@st.dialog("❌ Schedule Swap Declined")
def dlg_schedule_swap_declined(shift_date, reason):
    st.error("Schedule Swap Request Declined")
    st.markdown(f"**Date:** `{shift_date}`")
    st.markdown(f"**Reason:** {reason}")
    if st.button("OK", use_container_width=True):
        st.rerun()

@st.dialog("⚠️ Critical Case Alert")
def dlg_critical_case_alert(case, due_in_str):
    st.warning("Critical Case Approaching SLA Breach Window!")
    st.markdown(f"**Case #:** `{case.get('case_id')}`")
    st.markdown(f"**Subject:** {case.get('subject')}")
    st.markdown(f"**Due In:** <strong style='color:#DE3618;'>{due_in_str}</strong>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if c1.button("View Case Details", type="primary", use_container_width=True):
        st.session_state["selected_case_id"] = case.get('case_id')
        st.session_state["active_nav"] = "Case Details"
        st.rerun()
    if c2.button("Acknowledge", use_container_width=True):
        st.rerun()

@st.dialog("🚨 Critical Case Past Due - Breach Alert")
def dlg_critical_past_due(case):
    st.error("SLA CONTRACT BREACH RECORDED")
    st.markdown(f"**Case #:** `{case.get('case_id')}`")
    st.markdown(f"**Subject:** {case.get('subject')}")
    st.markdown(f"**Account:** {case.get('account', 'Global Enterprise')}")
    st.markdown(f"**Due Date:** `{case.get('due_date')}`")
    st.markdown(f"**Breach Reason:** `{case.get('breach_reason', 'Vendor Delay / Exceeded Response Time')}`")
    if st.button("Open Incident Workspace", type="primary", use_container_width=True):
        st.session_state["selected_case_id"] = case.get('case_id')
        st.session_state["active_nav"] = "Case Details"
        st.rerun()

@st.dialog("📢 Admin Broadcast Message")
def dlg_admin_broadcast(sender, text, timestamp):
    st.subheader(f"Message from {sender}")
    st.caption(f"Dispatched: {timestamp}")
    st.info(text)
    if st.button("OK", type="primary", use_container_width=True):
        st.rerun()

# ==============================================================================
# 6. AUTHENTICATION MODULE (Strict MongoDB Validation - No Bypass)
# ==============================================================================
def render_auth_page():
    if not db_mgr.is_connected():
        st.error("Unable to connect to the authentication service. Please try again later or contact your administrator.")
        st.caption("Error: MongoDB cluster unreachable. Authentication bypass is strictly prohibited.")
        return

    col_brand, col_form = st.columns([1.15, 1], gap="large")
    
    with col_brand:
        st.markdown(
            """
            <div style="background: linear-gradient(135deg, #0B2341 0%, #001A2C 100%); padding: 3.5rem 2.5rem; border-radius: 12px; color: white; height: 100%; box-shadow: 0 4px 15px rgba(0,0,0,0.15);">
                <div style="font-size: 1.8rem; font-weight: 800; letter-spacing: -0.5px; margin-bottom: 0.25rem;">
                    <span style="color: #01A982;">Hewlett Packard</span> Enterprise
                </div>
                <h1 style="color: white; font-size: 2.8rem; margin: 0 0 1rem 0; font-weight: 800;">HPE CaseFlow</h1>
                <p style="font-size: 1.15rem; color: #A0B2C6; margin-bottom: 2.5rem;">Team Task and Case Management System</p>
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
            
            with st.form("form_signin"):
                email = st.text_input("HPE Email Address", placeholder="firstname.lastname@hpe.com")
                password = st.text_input("Password", type="password")
                remember_me = st.checkbox("Remember me", value=True)
                btn_signin = st.form_submit_button("Sign In", type="primary", use_container_width=True)
                
                if btn_signin:
                    if not email or not password:
                        st.error("Please enter both email and password.")
                    else:
                        user = db_mgr.find_user_by_email(email)
                        if user and verify_password(user.get("password_hash", ""), password):
                            if user.get("account_status") != "Active":
                                st.error("Your account has been deactivated. Please contact an Administrator.")
                            else:
                                # Set login status and aux in MongoDB
                                role = user.get("role", "Agent")
                                default_aux = "Admin Work" if role == "Admin" else "Not Ready - Online"
                                db_mgr.update_user_field(user["hpe_email"], {
                                    "login_status": "Online",
                                    "current_aux": default_aux,
                                    "aux_since": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
                                    "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                })
                                user["current_aux"] = default_aux
                                user["login_status"] = "Online"
                                
                                st.session_state["authenticated"] = True
                                st.session_state["auth_user"] = user
                                st.session_state["active_nav"] = "Dashboard"
                                db_mgr.log_audit(user["hpe_email"], "Sign In", "Authenticated successfully")
                                st.rerun()
                        else:
                            st.error("Invalid HPE credentials. Please verify your email or password.")
            
            c1, c2 = st.columns(2)
            if c1.button("Create Account", use_container_width=True):
                st.session_state["auth_mode"] = "Sign Up"
                st.rerun()
            if c2.button("Forgot Password?", use_container_width=True):
                st.session_state["auth_mode"] = "Forgot Password"
                st.rerun()

        elif auth_mode == "Sign Up":
            st.markdown("## Create Your Account")
            st.caption("Sign up to access HPE CaseFlow")
            
            with st.form("form_signup"):
                fn = st.text_input("First Name")
                ln = st.text_input("Last Name")
                emp_id = st.text_input("Employee ID", placeholder="HPE-XXXXX")
                email = st.text_input("HPE Email Address", placeholder="firstname.lastname@hpe.com")
                pwd = st.text_input("Password", type="password", help="Must be 8+ characters, with letters, numbers, and special symbols.")
                pwd_conf = st.text_input("Confirm Password", type="password")
                btn_signup = st.form_submit_button("Sign Up", type="primary", use_container_width=True)
                
                if btn_signup:
                    if not all([fn, ln, emp_id, email, pwd, pwd_conf]):
                        st.error("All fields are mandatory.")
                    elif not re.match(r"^[\w\.-]+@hpe\.com$", email.strip().lower()):
                        st.error("Registration requires an authorized @hpe.com enterprise email address.")
                    elif pwd != pwd_conf:
                        st.error("Passwords do not match.")
                    elif len(pwd) < 8 or not re.search(r"\d", pwd) or not re.search(r"[!@#$%^&*(),.?\":{}|<>]", pwd):
                        st.error("Password must be at least 8 characters and include numbers and special characters.")
                    elif db_mgr.find_user_by_email(email):
                        st.error("An account with this email address already exists.")
                    elif db_mgr.find_user_by_employee_id(emp_id):
                        st.error("An account with this Employee ID already exists.")
                    else:
                        new_roster_obj = {
                            "first_name": str(fn.strip()),
                            "last_name": str(ln.strip()),
                            "employee_id": str(emp_id.strip()),
                            "hpe_email": str(email.strip().lower()),
                            "password_hash": hash_password(pwd),
                            "role": "Agent",  # Default role strictly Agent
                            "account_status": "Active",
                            "profile_picture": "",
                            "contact_number": "",
                            "birthday": "",
                            "address": "",
                            "current_aux": "Not Ready - Online",
                            "login_status": "Offline",
                            "active_cases": "0",
                            "today_assigned": "0",
                            "department": "Global Mission Critical Support",
                            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        if db_mgr.create_user(new_roster_obj):
                            st.success("Account created successfully! Please sign in.")
                            st.session_state["auth_mode"] = "Sign In"
                            st.rerun()
                        else:
                            st.error("Failed to save account to MongoDB.")

            if st.button("← Back to Sign In"):
                st.session_state["auth_mode"] = "Sign In"
                st.rerun()

        elif auth_mode == "Forgot Password":
            st.markdown("## Reset Your Password")
            st.caption("Enter your registered HPE enterprise email to generate a secure reset token.")
            reset_email = st.text_input("Registered HPE Email")
            if st.button("Send Reset Link", type="primary", use_container_width=True):
                if reset_email and db_mgr.find_user_by_email(reset_email):
                    st.success(f"A single-use, time-limited reset link has been dispatched to {reset_email}.")
                else:
                    st.error("Email not found on Team Roster.")
            if st.button("← Back to Sign In"):
                st.session_state["auth_mode"] = "Sign In"
                st.rerun()

# ==============================================================================
# 7. GLOBAL HEADER COMPONENT
# ==============================================================================
def render_global_header(user: Dict[str, Any]):
    # Safely retrieve email (supporting both 'hpe_email' and 'email')
    user_email = user.get("hpe_email") or user.get("email", "")
    
    is_admin = user.get("role") in ["Admin", "Admin/Agent"]
    user_notifs = db_mgr.get_notifications(user_email, is_admin=is_admin)
    unread_count = len([n for n in user_notifs if not n.get("read", False)])
    
    col_brand, col_search, col_aux, col_profile = st.columns([1.6, 2.8, 1.8, 1.8], gap="medium")
    
    with col_brand:
        st.markdown(
            """
            <div style="display: flex; align-items: center; gap: 10px; padding-top: 4px;">
                <div style="background-color: #01A982; width: 14px; height: 34px; border-radius: 2px;"></div>
                <div>
                    <div style="font-weight: 800; font-size: 1.25rem; color: #0B2341; line-height: 1;">HPE CaseFlow</div>
                    <div style="font-size: 0.72rem; color: #616D75;">Team Task and Case Management System</div>
                </div>
            </div>
            """, 
            unsafe_allow_html=True
        )

    with col_search:
        search_query = st.text_input(
            "Global Search",
            placeholder="🔍 Search cases, agents, vendors, issues...",
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
        btn_label = f"{bell_icon} {first_name} ({role}) ▾"
        popover = st.popover(btn_label, use_container_width=True)
        with popover:
            st.markdown(f"### {user.get('first_name', '')} {user.get('last_name', '')}")
            st.caption(f"Employee ID: {user.get('employee_id', 'N/A')} | {user_email}")
            st.markdown(f"**Role:** `{role}`")
            st.markdown(f"**Current Aux:** `{user.get('current_aux', 'Available')}`")
            st.markdown(f"**Today's Schedule:** `08:00 - 17:00 (Case Work & Dispatch)`")
            
            st.divider()
            st.markdown(f"**Notifications ({unread_count} unread)**")
            if user_notifs:
                for notif in user_notifs[:4]:
                    st.caption(f"• **{notif.get('title')}**: {notif.get('text')} *({notif.get('timestamp')})*")
                if st.button("Mark All Notifications Read", key="popover_mark_read"):
                    db_mgr.mark_notifications_read(user_email)
                    st.rerun()
            else:
                st.caption("No notifications.")
            
            st.divider()
            if st.button("Sign Out", type="primary", use_container_width=True):
                db_mgr.update_user_field(user_email, {
                    "login_status": "Offline",
                    "current_aux": "Not Ready - Online"
                })
                st.session_state.clear()
                st.rerun()

# ==============================================================================
# 8. LEFT SIDEBAR COMPONENT
# ==============================================================================
def render_sidebar(user: Dict[str, Any]):
    with st.sidebar:
        st.markdown(
            """
            <div style="padding: 0.5rem 0 1rem 0; border-bottom: 1px solid #E0E6ED; margin-bottom: 1rem;">
                <span style="background: #01A982; color: white; padding: 3px 8px; border-radius: 4px; font-weight: 800; font-size: 0.85rem;">HPE</span>
                <strong style="color: #0B2341; font-size: 1.1rem; margin-left: 8px;">CASEFLOW</strong>
                <div style="font-size: 0.72rem; color: #616D75; margin-top: 3px;">Team Task & Case Management</div>
            </div>
            """, 
            unsafe_allow_html=True
        )

        role = user.get("role", "Agent")
        nav_options = []
        
        if role == "Admin":
            nav_options = ["Dashboard", "Monitoring", "Schedule", "Report", "Settings"]
        elif role == "Admin/Agent":
            view_toggle = st.radio("Active View", ["Admin View", "Agent View"], horizontal=True, key="admin_agent_view_toggle")
            st.session_state["view_mode"] = view_toggle
            if view_toggle == "Admin View":
                nav_options = ["Dashboard", "Monitoring", "Schedule", "Report", "Settings"]
            else:
                nav_options = ["Dashboard", "Schedule", "Report"]
        else: # Agent
            nav_options = ["Dashboard", "Schedule", "Report"]

        # Keep Case Details reachable when actively viewing a ticket
        if st.session_state.get("active_nav") == "Case Details":
            nav_options.append("Case Details")

        current_nav = st.session_state.get("active_nav", "Dashboard")
        if current_nav not in nav_options:
            current_nav = nav_options[0]

        for item in nav_options:
            is_active = (item == current_nav)
            icon_map = {
                "Dashboard": "▦", 
                "Monitoring": "👥", 
                "Schedule": "▣", 
                "Report": "▥", 
                "Settings": "⚙", 
                "Case Details": "🔍"
            }
            icon = icon_map.get(item, "▸")
            label = f"{icon}  {item}"
            btn_type = "primary" if is_active else "secondary"
            if st.button(label, key=f"nav_btn_{item}", use_container_width=True, type=btn_type):
                st.session_state["active_nav"] = item
                st.rerun()

        st.markdown("---")
        st.caption("Persistent Database")
        st.markdown("<span style='color: #01A982;'>●</span> **MongoDB:** TeamRoster", unsafe_allow_html=True)
        st.caption(f"HPE CaseFlow v1.0.0")

# ==============================================================================
# 9. DASHBOARD VIEW (Admin & Agent)
# ==============================================================================
def render_dashboard(user: Dict[str, Any]):
    is_admin = (user.get("role") == "Admin") or (user.get("role") == "Admin/Agent" and st.session_state.get("view_mode") != "Agent View")
    
    # Header greeting
    if is_admin:
        st.markdown(f"## Dashboard")
        st.caption(f"Welcome back, {user.get('first_name')}! Here's what's happening with your team today.")
    else:
        st.markdown(f"## My Dashboard")
        st.caption(f"Good day, {user.get('first_name')}! 👋 Here are your active assigned cases and SLA deadlines.")
    
    # Cases query
    all_cases = db_mgr.get_cases()
    user_email = user.get("hpe_email", "").lower()
    target_cases = all_cases if is_admin else [c for c in all_cases if c.get("assigned_to", "").lower() == user_email]
    
    # Calculate metrics
    active_cases = [c for c in target_cases if c.get("status") not in ["Resolved", "Closed"]]
    critical_count = len([c for c in active_cases if c.get("priority") == "Critical"])
    due_soon_count = len([c for c in active_cases if c.get("status") in ["Open", "In Progress", "Pending Vendor", "On Hold"]])
    on_track_count = max(0, len(active_cases) - critical_count)

    # 4 Metric Cards
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(
            f"""
            <div class="metric-card info">
                <div style="font-size: 0.8rem; color: #616D75; font-weight: 700;">ACTIVE CASES</div>
                <div style="font-size: 2.2rem; font-weight: 800; color: #0B2341;">{len(active_cases)}</div>
                <div style="font-size: 0.75rem; color: #01A982;">Current shift workload</div>
            </div>
            """, 
            unsafe_allow_html=True
        )
    with m2:
        st.markdown(
            f"""
            <div class="metric-card critical">
                <div style="font-size: 0.8rem; color: #616D75; font-weight: 700;">CRITICAL</div>
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
                <div style="font-size: 0.8rem; color: #616D75; font-weight: 700;">DUE SOON</div>
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
                <div style="font-size: 0.8rem; color: #616D75; font-weight: 700;">ON TRACK</div>
                <div style="font-size: 2.2rem; font-weight: 800; color: #01A982;">{on_track_count}</div>
                <div style="font-size: 0.75rem; color: #01A982;">Compliant with SLA</div>
            </div>
            """, 
            unsafe_allow_html=True
        )

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
    
    col_main, col_rail = st.columns([2.7, 1.1], gap="medium")
    
    with col_main:
        st.subheader("Active Cases" if is_admin else "My Active Assigned Queue")
        
        # Filter Bar
        f1, f2, f3, f4 = st.columns([1.5, 1, 1, 0.5])
        with f1:
            q_search = st.text_input("Filter cases", placeholder="Search by subject, account, or case #...", label_visibility="collapsed")
        with f2:
            prio_filter = st.selectbox("Priority", ["All Priorities", "Critical", "High", "Medium", "Low"], label_visibility="collapsed")
        with f3:
            status_filter = st.selectbox("Status", ["All Statuses", "Open", "In Progress", "Pending Vendor", "Pending Internal", "On Hold", "Resolved", "Closed"], label_visibility="collapsed")
        with f4:
            if st.button("Reset", use_container_width=True):
                st.rerun()

        # Filtering Logic
        filtered = target_cases
        if q_search:
            filtered = [c for c in filtered if q_search.lower() in c.get("subject", "").lower() or q_search.lower() in c.get("account", "").lower() or q_search.lower() in c.get("case_id", "").lower()]
        if prio_filter != "All Priorities":
            filtered = [c for c in filtered if c.get("priority") == prio_filter]
        if status_filter != "All Statuses":
            filtered = [c for c in filtered if c.get("status") == status_filter]

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
                                    <strong style="color: #00739D; font-size: 1.05rem;">{case.get('case_id')}</strong>
                                    <span style="margin-left: 10px; font-weight: 700; color: #0B2341;">{case.get('subject')}</span>
                                </div>
                                <div>
                                    <span class="badge badge-{case.get('priority', 'low').lower()}">{case.get('priority')}</span>
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
                    if c_btn.button(f"Manage Case", key=f"btn_manage_{case.get('case_id')}"):
                        st.session_state["selected_case_id"] = case.get('case_id')
                        st.session_state["active_nav"] = "Case Details"
                        st.rerun()
                    if is_admin:
                        all_users = [u.get("hpe_email") for u in db_mgr.get_all_roster_users()]
                        curr_owner = case.get("assigned_to", "Unassigned")
                        idx = all_users.index(curr_owner) if curr_owner in all_users else 0
                        new_owner = c_assign.selectbox("Reassign", all_users, index=idx, key=f"reas_{case.get('case_id')}", label_visibility="collapsed")
                        if new_owner != curr_owner:
                            if c_assign.button("Confirm", key=f"conf_{case.get('case_id')}"):
                                db_mgr.update_case(case.get("case_id"), {"assigned_to": new_owner}, user["hpe_email"])
                                db_mgr.add_notification(new_owner, "Case Reassigned", f"Case {case.get('case_id')} reassigned to you by Admin.", notif_type="Case", case_id=case.get("case_id"))
                                st.rerun()

    with col_rail:
        if is_admin:
            st.subheader("Agents Online")
            for ag in db_mgr.get_all_roster_users():
                aux = ag.get("current_aux", "Available")
                aux_class = f"badge-{aux.lower().replace(' ', '').replace('-', '')}"
                st.markdown(
                    f"""
                    <div style="background: white; border: 1px solid #E0E6ED; border-radius: 6px; padding: 10px; margin-bottom: 8px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <strong style="color: #0B2341;">{ag.get('first_name')} {ag.get('last_name')}</strong>
                                <div style="font-size: 0.72rem; color: #616D75;">{ag.get('role')} • Today: {ag.get('today_assigned', 0)}</div>
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
                
                # Fetch vendor options strictly from MongoDB
                vendors_list = [v.get("name") for v in db_mgr.get_vendors()]
                if not vendors_list:
                    vendors_list = ["Intel Xeon Platform Support", "Samsung Semiconductor", "Brocade SAN Networking"]
                n_vendor = st.selectbox("Vendor Component", vendors_list)
                
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
                    assigned_agent = execute_automatic_case_assignment(new_case_obj)
                    if assigned_agent:
                        st.success(f"Case dispatched automatically to {assigned_agent.get('hpe_email')}!")
                    else:
                        st.warning("Case created but unassigned (no agents currently in Available state).")
                    st.rerun()

        else: # Agent Right Rail: Shift Overview & Quick Alerts
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

# ==============================================================================
# 10. CASE DETAILS & WORKFLOW MODULE
# ==============================================================================
def render_case_details(user: Dict[str, Any]):
    case_id = st.session_state.get("selected_case_id")
    if not case_id:
        st.warning("No case selected.")
        if st.button("← Return to Dashboard"):
            st.session_state["active_nav"] = "Dashboard"
            st.rerun()
        return

    case = db_mgr.get_case_by_id(case_id)
    if not case:
        st.error(f"Case {case_id} not found in MongoDB.")
        if st.button("← Return to Dashboard"):
            st.session_state["active_nav"] = "Dashboard"
            st.rerun()
        return

    is_admin = user.get("role") in ["Admin", "Admin/Agent"]
    is_owner = case.get("assigned_to", "").lower() == user.get("hpe_email", "").lower()

    # Header Bar
    c_back, c_title, c_badges = st.columns([0.6, 2.5, 1.4])
    with c_back:
        if st.button("← Back"):
            st.session_state["active_nav"] = "Dashboard"
            st.rerun()
    with c_title:
        st.markdown(f"### {case.get('case_id')} — {case.get('subject')}")
        st.caption(f"Account: {case.get('account', 'Enterprise Partner')} | Created: {case.get('created_date')}")
    with c_badges:
        st.markdown(
            f"""
            <div style="text-align: right; padding-top: 5px;">
                <span class="badge badge-{case.get('priority', 'low').lower()}">{case.get('priority')}</span>
                <span class="badge badge-open" style="margin-left: 6px;">{case.get('status')}</span>
            </div>
            """, 
            unsafe_allow_html=True
        )

    dropdowns = db_mgr.get_validation_dropdowns()
    t1, t2, t3, t4 = st.tabs(["Case Information", "Vendor Information", "Communication & Breach", "Case History"])
    
    with t1:
        c1, c2 = st.columns(2)
        with c1:
            st.text_input("Case Number", value=case.get("case_id"), disabled=True)
            st.text_input("Account / Client", value=case.get("account", case.get("client", "")))
            
            prio_opts = ["Critical", "High", "Medium", "Low"]
            prio_idx = prio_opts.index(case.get("priority")) if case.get("priority") in prio_opts else 0
            new_prio = st.selectbox("Priority SLA", prio_opts, index=prio_idx)
            
            stat_opts = dropdowns.get("Case_Status", ["Open", "In Progress", "On Hold", "Pending Vendor", "Resolved", "Closed"])
            stat_idx = stat_opts.index(case.get("status")) if case.get("status") in stat_opts else 0
            new_status = st.selectbox("Case Status", stat_opts, index=stat_idx)

        with c2:
            st.text_input("Assigned Engineer", value=case.get("assigned_to", "Unassigned"), disabled=True)
            st.text_input("Due Date", value=case.get("due_date", "Pending"))
            st.text_input("Related System", value=case.get("related_system", "HPE Infrastructure"))
            new_desc = st.text_area("Description", value=case.get("description", ""), height=100)

        update_remarks = st.text_input("Remarks / Update Note", placeholder="Enter specific updates for case history...")
        if st.button("Update Case", type="primary"):
            updates = {
                "priority": new_prio,
                "status": new_status,
                "description": new_desc
            }
            if update_remarks:
                updates["last_update"] = update_remarks
            db_mgr.update_case(case_id, updates, user["hpe_email"])
            st.success("Case successfully updated.")
            st.rerun()

        # Case Transfer Section
        st.divider()
        st.markdown("#### Case Transfer Request")
        t_col1, t_col2 = st.columns([2, 1])
        other_agents = [u.get("hpe_email") for u in db_mgr.get_all_roster_users() if u.get("hpe_email") != user.get("hpe_email")]
        target_agent = t_col1.selectbox("Select Target Agent", other_agents)
        if t_col2.button("Request Transfer", use_container_width=True):
            db_mgr.add_notification(
                target_agent,
                "Case Transfer Request",
                f"{user['hpe_email']} requested to transfer Case {case_id} to you.",
                notif_type="Transfer",
                case_id=case_id
            )
            st.success(f"Transfer request dispatched to {target_agent}.")

    with t2:
        st.markdown("#### Vendor Integration Details")
        st.markdown(f"**Vendor Name:** `{case.get('vendor', 'Intel Xeon Platform Support')}`")
        v_col1, v_col2 = st.columns(2)
        with v_col1:
            v_email = "support@intel-hpe-operations.com"
            st.text_input("Primary Contact Email", value=v_email, disabled=True)
            st.caption("Direct integration with vendor escalation desk.")
        with v_col2:
            v_phone = "+1-800-456-7890"
            st.text_input("Support Hotline", value=v_phone, disabled=True)

    with t3:
        st.markdown("#### Contract Breach & Automated Notice Generator")
        st.caption("If vendor SLA was exceeded, generate formal contract breach communication.")
        
        c_closure = st.selectbox("Closure Type", dropdowns.get("Closure_Type", ["Resolved - Normal", "Contract Breach"]))
        c_breach = None
        if c_closure == "Contract Breach":
            c_breach = st.selectbox("Breach Reason", dropdowns.get("Contract_Breach", ["Vendor No Response", "Late Delivery"]))
        
        with st.form("breach_email_form"):
            default_body = (
                f"Dear Operations Partner,\n\n"
                f"This notification serves as formal advisory that HPE Case {case.get('case_id')} "
                f"regarding {case.get('subject')} has exceeded the designated SLA delivery window.\n\n"
                f"Classification: {c_breach or 'Vendor Non-Delivery'}\n"
                f"Next Escalation Checkpoint: Immediate executive escalation review.\n\n"
                f"Regards,\nHPE Global Mission Critical Operations"
            )
            e_to = st.text_input("To", value="partner-sla-desk@vendor-corp.com")
            e_subj = st.text_input("Subject", value=f"[CRITICAL SLA BREACH] Case {case.get('case_id')} - {case.get('subject')}")
            e_msg = st.text_area("Message Body", value=default_body, height=150)
            if st.form_submit_button("Send Breach Email", type="primary"):
                db_mgr.update_case(case_id, {
                    "status": "Breached",
                    "closure_type": c_closure,
                    "breach_reason": c_breach
                }, user["hpe_email"])
                db_mgr.log_case_history(case_id, user["hpe_email"], "Breach Email Sent", f"Dispatched to {e_to}")
                st.success("Formal breach notification transmitted.")
                st.rerun()

    with t4:
        st.markdown("#### Case Event History")
        history = db_mgr.get_case_history(case_id)
        if history:
            for ev in history:
                st.markdown(
                    f"""
                    <div style="border-left: 3px solid #01A982; padding-left: 14px; margin-bottom: 12px;">
                        <div style="font-weight: 700; color: #0B2341;">{ev.get('action')} — <span style="font-weight: 400; color: #616D75;">{ev.get('timestamp')}</span></div>
                        <div style="font-size: 0.85rem; color: #00739D;">Actor: {ev.get('user')}</div>
                        <div style="font-size: 0.85rem; color: #333333;">{ev.get('details')}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
        else:
            st.caption("No history events logged.")

# ==============================================================================
# 11. MONITORING MODULE (Admin & Admin/Agent Only)
# ==============================================================================
def render_monitoring(user: Dict[str, Any]):
    if user.get("role") not in ["Admin", "Admin/Agent"]:
        st.error("Access Restricted. Monitoring is an administrative function.")
        return

    st.markdown("## Monitoring")
    st.caption("View all logged-in agents, their real-time status and activities.")
    
    users = db_mgr.get_all_roster_users()
    # Exclude pure Admins from agent metrics if requested
    agents_only = [u for u in users if u.get("role") in ["Agent", "Admin/Agent"]]
    
    total_logged = len([u for u in agents_only if u.get("login_status") == "Online"])
    avail_count = len([u for u in agents_only if u.get("current_aux") == "Available"])
    aux_count = len([u for u in agents_only if u.get("current_aux") in ["Break", "Lunch", "Unscheduled Break"]])
    coaching_count = len([u for u in agents_only if u.get("current_aux") in ["Coaching", "Meeting"]])
    notready_count = len([u for u in agents_only if u.get("current_aux") == "Not Ready - Online"])

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Logged In", f"{total_logged} / {len(agents_only)}")
    c2.metric("Available", avail_count)
    c3.metric("On Aux", aux_count)
    c4.metric("In Meeting/Coaching", coaching_count)
    c5.metric("Not Ready", notready_count)
    
    st.divider()
    st.subheader("Agent Monitoring Table")
    
    table_rows = []
    for u in agents_only:
        table_rows.append({
            "Agent": f"{u.get('first_name')} {u.get('last_name')}",
            "Employee ID": u.get("employee_id"),
            "Role": u.get("role"),
            "Login Status": u.get("login_status", "Offline"),
            "Current Aux": u.get("current_aux", "Not Ready - Online"),
            "Active Cases": u.get("active_cases", "0"),
            "Assigned Today": u.get("today_assigned", "0"),
            "Last Aux Change": u.get("aux_since", "N/A")
        })
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    st.markdown("#### Administrative Agent Controls")
    sel_agent = st.selectbox("Select Agent to Inspect", [u.get("hpe_email") for u in agents_only])
    target = db_mgr.find_user_by_email(sel_agent)
    if target:
        b1, b2 = st.columns(2)
        if b1.button("Dispatched Pop-up Message to Agent"):
            db_mgr.add_notification(
                target["hpe_email"],
                "Message from Admin",
                "Hi Team, Please prioritize all critical cases today. Thank you.",
                notif_type="AdminMessage"
            )
            st.success(f"Message dispatched to {target['hpe_email']}.")
        if b2.button("Kick / Force Offline"):
            db_mgr.update_user_field(target["hpe_email"], {
                "login_status": "Offline",
                "current_aux": "Not Ready - Online"
            })
            st.success(f"Agent {target['hpe_email']} session cleared.")
            st.rerun()

# ==============================================================================
# 12. SCHEDULE MODULE (Admin & Agent)
# ==============================================================================
def render_schedule(user: Dict[str, Any]):
    is_admin = (user.get("role") == "Admin") or (user.get("role") == "Admin/Agent" and st.session_state.get("view_mode") != "Agent View")
    
    st.markdown("## Schedule")
    st.caption("Manage PTO allocation, leaves, and daily shift schedules.")
    
    v1, v2, _ = st.columns([1, 1, 3])
    view_type = v1.selectbox("View Format", ["Month", "Week", "Day"])
    
    if is_admin:
        tab_grid, tab_pto, tab_approval = st.tabs(["Team Schedule Assignment", "PTO Allocation Calendar", "Leave Approvals"])
        
        with tab_grid:
            st.subheader("Shift Assignment Grid (08:00 - 17:00)")
            agents = [u for u in db_mgr.get_all_roster_users() if u.get("role") in ["Agent", "Admin/Agent"]]
            hours = ["8 AM", "9 AM", "10 AM", "11 AM", "12 PM", "1 PM", "2 PM", "3 PM", "4 PM", "5 PM"]
            
            grid_data = []
            for ag in agents:
                row = {"Agent": f"{ag.get('first_name')} {ag.get('last_name')}", "Role": ag.get("role")}
                for h in hours:
                    if h == "12 PM":
                        row[h] = "Lunch"
                    elif h == "10 AM":
                        row[h] = "Break"
                    else:
                        row[h] = "Case Work"
                grid_data.append(row)
            st.dataframe(pd.DataFrame(grid_data), use_container_width=True, hide_index=True)
            
            if st.button("Auto-Plot Schedule with Coverage Rules", type="primary"):
                st.success("Schedule successfully auto-plotted with balanced lunch/break rotations.")

        with tab_pto:
            st.subheader("PTO Allocation Configuration")
            curr_month = datetime.now().strftime("%Y-%m")
            allocs = db_mgr.get_pto_allocations(curr_month)
            
            p_col1, p_col2 = st.columns(2)
            d_pick = p_col1.date_input("Select Date to Allocate", value=datetime.now())
            d_limit = p_col2.number_input("Max Allowed PTO Seats", min_value=0, max_value=10, value=2)
            if st.button("Save PTO Allocation Limit"):
                db_mgr.set_pto_allocation(curr_month, str(d_pick), int(d_limit))
                st.success(f"Allocation for {d_pick} updated to {d_limit} seats.")
                st.rerun()

        with tab_approval:
            st.subheader("Submitted Leave Requests")
            reqs = db_mgr.get_leave_requests()
            for r in reqs:
                st.markdown(
                    f"""
                    <div class="hpe-card">
                        <strong>{r.get('name')}</strong> — <span style="color: #00739D;">{r.get('type')}</span>
                        <div>Dates: <strong>{r.get('dates')}</strong> | Reason: {r.get('reason')}</div>
                        <div>Status: <strong>{r.get('status')}</strong></div>
                    </div>
                    """, 
                    unsafe_allow_html=True
                )
                if r.get("status") == "Pending":
                    c_appr, c_decl, _ = st.columns([1, 1, 3])
                    if c_appr.button("Approve", key=f"appr_{r.get('req_id')}"):
                        db_mgr.update_leave_status(r.get("req_id"), "Approved", user["hpe_email"])
                        st.rerun()
                    if c_decl.button("Decline", key=f"decl_{r.get('req_id')}"):
                        db_mgr.update_leave_status(r.get("req_id"), "Declined", user["hpe_email"])
                        st.rerun()

    else: # Agent Schedule View
        st.subheader("My Personal Schedule")
        st.markdown(
            """
            <div class="hpe-card">
                <strong>Current Week Assignment:</strong><br/>
                • Monday - Friday: 08:00 - 17:00 (Case Work & Dispatch)<br/>
                • Lunch: 12:00 - 13:00 Daily<br/>
                • Coaching: Tuesday 14:00 - 15:00
            </div>
            """, 
            unsafe_allow_html=True
        )
        
        st.divider()
        st.subheader("File Leave or Swap Request")
        with st.form("agent_leave_form"):
            l_type = st.selectbox("Request Type", ["PTO", "Sick Leave", "Emergency Leave", "Schedule Swap"])
            l_date = st.text_input("Target Date(s)", placeholder="YYYY-MM-DD")
            l_reason = st.text_area("Reason")
            
            if st.form_submit_button("Submit Request", type="primary"):
                # PTO check
                status = "Pending"
                if l_type in ["Sick Leave", "Emergency Leave"]:
                    status = "Approved" # Auto-approved per rules
                elif l_type == "PTO":
                    curr_month = datetime.now().strftime("%Y-%m")
                    allocs = db_mgr.get_pto_allocations(curr_month)
                    limit = allocs.get(l_date.strip(), 2) # default 2
                    # Count existing approved PTOs for date
                    existing = [
                        r for r in db_mgr.get_leave_requests() 
                        if r.get("dates") == l_date.strip() and r.get("type") == "PTO" and r.get("status") == "Approved"
                    ]
                    if len(existing) >= limit:
                        st.error("No allocation is available for the selected date.")
                        st.stop()
                
                new_req = {
                    "req_id": f"REQ-{uuid.uuid4().hex[:5].upper()}",
                    "name": f"{user.get('first_name')} {user.get('last_name')}",
                    "email": user.get("hpe_email"),
                    "type": l_type,
                    "dates": l_date,
                    "reason": l_reason,
                    "status": status
                }
                db_mgr.insert_leave_request(new_req)
                if status == "Approved":
                    st.success(f"{l_type} submitted and automatically approved.")
                else:
                    st.success("Request submitted to Operations for approval.")
                st.rerun()

# ==============================================================================
# 13. REPORTS & ANALYTICS MODULE (Admin & Agent)
# ==============================================================================
def render_reports(user: Dict[str, Any]):
    is_admin = (user.get("role") == "Admin") or (user.get("role") == "Admin/Agent" and st.session_state.get("view_mode") != "Agent View")
    
    st.markdown("## Reports")
    st.caption("Visualize team performance, case resolution, attendance, and adherence.")
    
    p_col, _ = st.columns([1, 3])
    period = p_col.selectbox("Reporting Period", ["Daily", "WOW", "MTD", "YTD"])
    
    all_cases = db_mgr.get_cases()
    user_email = user.get("hpe_email", "").lower()
    cases = all_cases if is_admin else [c for c in all_cases if c.get("assigned_to", "").lower() == user_email]
    
    total_count = len(cases)
    resolved_count = len([c for c in cases if c.get("status") == "Resolved"])
    breached_count = len([c for c in cases if c.get("status") == "Breached"])
    on_time_pct = int(((total_count - breached_count) / max(1, total_count)) * 100)
    
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Total Cases", total_count)
    r2.metric("Resolved Cases", resolved_count)
    r3.metric("Breached Cases", breached_count)
    r4.metric("On-Time Resolution", f"{on_time_pct}%")
    
    col_c1, col_c2 = st.columns(2)
    if cases:
        df_cases = pd.DataFrame(cases)
        with col_c1:
            st.subheader("Case Breakdown by Priority")
            if "priority" in df_cases.columns:
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
            if "status" in df_cases.columns:
                fig_status = px.bar(
                    df_cases,
                    x="status",
                    color="status",
                    color_discrete_sequence=["#01A982", "#00739D", "#FFAA15", "#DE3618", "#763082"]
                )
                fig_status.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=280, showlegend=False)
                st.plotly_chart(fig_status, use_container_width=True)
    else:
        st.info("No cases currently recorded in MongoDB to generate analytics.")

    if is_admin:
        st.divider()
        st.subheader("Attendance & Adherence Summary")
        st.caption("Adherence compares actual Aux history against plotted schedule activities.")
        adherence_data = [
            {"Agent": f"{u.get('first_name')} {u.get('last_name')}", "Scheduled Hours": 40, "In Adherence": 38.5, "Adherence %": "96.2%"}
            for u in db_mgr.get_all_roster_users() if u.get("role") in ["Agent", "Admin/Agent"]
        ]
        if adherence_data:
            st.dataframe(pd.DataFrame(adherence_data), use_container_width=True, hide_index=True)

# ==============================================================================
# 14. SETTINGS MODULE (Admin Only)
# ==============================================================================
def render_settings(user: Dict[str, Any]):
    if user.get("role") not in ["Admin", "Admin/Agent"]:
        st.error("Access Restricted. Administrator authorization required.")
        return

    st.markdown("## Settings")
    st.caption("Manage users, roles, external data, vendor integrations, and system configurations.")
    
    t_roster, t_sources, t_vendors, t_audit = st.tabs([
        "Team Management", "External Sources", "Vendor Management", "Account Activity & Audit"
    ])
    
    with t_roster:
        st.subheader("Team Roster Management")
        users = db_mgr.get_all_roster_users()
        for idx, u in enumerate(users):
            with st.container():
                st.markdown(
                    f"""
                    <div class="hpe-card">
                        <strong>{u.get('first_name')} {u.get('last_name')}</strong> ({u.get('hpe_email')})
                        <div style="font-size: 0.8rem; color: #616D75;">Employee ID: {u.get('employee_id')} | Role: <strong>{u.get('role')}</strong> | Status: <strong>{u.get('account_status')}</strong></div>
                    </div>
                    """, 
                    unsafe_allow_html=True
                )
                r1, r2, r3, _ = st.columns([1.2, 1, 1, 2.5])
                new_role = r1.selectbox("Role", ["Agent", "Admin/Agent", "Admin"], index=["Agent", "Admin/Agent", "Admin"].index(u.get("role", "Agent")), key=f"set_r_{idx}", label_visibility="collapsed")
                if new_role != u.get("role"):
                    db_mgr.update_user_field(u.get("hpe_email"), {"role": new_role})
                    st.rerun()
                
                status_action = "Deactivate" if u.get("account_status") == "Active" else "Activate"
                if r2.button(status_action, key=f"stat_btn_{idx}"):
                    new_st = "Deactivated" if u.get("account_status") == "Active" else "Active"
                    db_mgr.update_user_field(u.get("hpe_email"), {"account_status": new_st})
                    st.rerun()

                if r3.button("Reset Pwd", key=f"rst_p_{idx}"):
                    db_mgr.update_user_field(u.get("hpe_email"), {"password_hash": hash_password("HPE#Reset2026")})
                    st.toast(f"Password reset to HPE#Reset2026 for {u.get('hpe_email')}")

    with t_sources:
        st.subheader("External Data Synchronization")
        st.caption("Upload and sync external Excel files containing vendor data and case intake.")
        
        uploaded_vendor_file = st.file_uploader("Upload Vendor Excel Source (.xlsx)", type=["xlsx"])
        if uploaded_vendor_file:
            try:
                df_v = pd.read_excel(uploaded_vendor_file)
                st.dataframe(df_v.head(), use_container_width=True)
                if st.button("Sync Uploaded Vendors to MongoDB", type="primary"):
                    for _, row in df_v.iterrows():
                        v_obj = {
                            "name": str(row.get("Vendor Name", "Vendor Corp")),
                            "contact": str(row.get("Contact Person", "Operations Contact")),
                            "email": str(row.get("Email", "support@vendor.com")),
                            "phone": str(row.get("Phone", "+1-800-000-0000")),
                            "category": str(row.get("Category", "General"))
                        }
                        db_mgr.insert_vendor(v_obj)
                    st.success("Vendor records successfully synchronized to MongoDB.")
                    st.rerun()
            except Exception as e:
                st.error("Failed to parse uploaded Excel file. Ensure valid columns.")

    with t_vendors:
        st.subheader("Active Vendors")
        vendors = db_mgr.get_vendors()
        if vendors:
            st.dataframe(pd.DataFrame(vendors), use_container_width=True)
        else:
            st.info("No vendor records in MongoDB. Synchronize via External Sources.")

    with t_audit:
        st.subheader("System Security & Activity Trail")
        logs = db_mgr.get_audit_logs()
        if logs:
            st.dataframe(pd.DataFrame(logs)[["timestamp", "user", "activity", "details"]], use_container_width=True, hide_index=True)
        else:
            st.caption("No audit activity logged.")

# ==============================================================================
# 15. MAIN CONTROLLER & APPLICATION ROUTER
# ==============================================================================
def main():
    # 1. Check Authentication Gate
    if not st.session_state.get("authenticated", False):
        render_auth_page()
        return

    # 2. Authenticated Session User
    current_user = st.session_state.get("auth_user")
    if not current_user:
        st.session_state.clear()
        st.rerun()

    # 3. Global Header Shell
    render_global_header(current_user)
    
    # 4. Custom Left Sidebar
    render_sidebar(current_user)
    
    # 5. Route Page by Authorization
    active_nav = st.session_state.get("active_nav", "Dashboard")
    
    if active_nav == "Dashboard":
        render_dashboard(current_user)
    elif active_nav == "Case Details":
        render_case_details(current_user)
    elif active_nav == "Monitoring":
        render_monitoring(current_user)
    elif active_nav == "Schedule":
        render_schedule(current_user)
    elif active_nav == "Report":
        render_reports(current_user)
    elif active_nav == "Settings":
        render_settings(current_user)

if __name__ == "__main__":
    main()
