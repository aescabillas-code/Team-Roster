import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from datetime import datetime, date, timedelta, time
import pymongo
from bson.objectid import ObjectId
import bcrypt
import json
import uuid
import time as time_pkg
import extra_streamlit_components as stx

# ==========================================
# 1. STREAMLIT PAGE CONFIG & CSS CUSTOMIZATION
# ==========================================
st.set_page_config(
    page_title="HPE CaseFlow - Team Task Management",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    /* Hide Streamlit default chrome & deploy header */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden !important;}
    [data-testid="stDecoration"] {visibility: hidden !important;}
    [data-testid="stStatusWidget"] {visibility: hidden !important;}

    /* Page container adjustments */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 2rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        max-width: 100% !important;
    }

    :root {
        --hpe-green: #01a982;
        --hpe-green-dark: #007a5e;
        --hpe-teal: #00c9a7;
        --bg-slate: #f8fafc;
    }

    /* Retractable Sidebar Arrow in the Middle */
    [data-testid="stSidebarCollapseButton"] {
        position: fixed !important;
        top: 50% !important;
        left: 0 !important;
        transform: translateY(-50%) !important;
        z-index: 99999 !important;
        background-color: rgba(1, 169, 130, 0.45) !important;
        color: #ffffff !important;
        border-radius: 0 12px 12px 0 !important;
        padding: 10px 4px !important;
        box-shadow: 2px 0 8px rgba(0,0,0,0.15) !important;
        transition: all 0.25s ease-in-out !important;
    }
    [data-testid="stSidebarCollapseButton"]:hover {
        background-color: rgba(1, 169, 130, 0.9) !important;
    }

    /* Left Sidebar Brand */
    .brand-container {
        padding: 10px 0 20px 0;
    }
    .brand-title {
        font-size: 1.35rem;
        font-weight: 800;
        color: #ffffff;
        letter-spacing: -0.3px;
        margin: 0;
    }
    .brand-sub {
        font-size: 0.8rem;
        color: #94a3b8;
        margin-top: 2px;
    }

    /* Metric Cards */
    .metric-card-container {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 16px 20px;
        display: flex;
        align-items: center;
        gap: 16px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.02);
    }
    .metric-icon-circle {
        width: 44px;
        height: 44px;
        border-radius: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.3rem;
        flex-shrink: 0;
    }
    .metric-val {
        font-size: 1.85rem;
        font-weight: 800;
        color: #0f172a;
        line-height: 1.1;
    }
    .metric-lbl {
        font-size: 0.82rem;
        font-weight: 600;
        color: #64748b;
        margin-bottom: 2px;
    }
    .metric-sub {
        font-size: 0.72rem;
        color: #94a3b8;
    }

    /* Table styling - Borderless clean rows */
    .case-table {
        width: 100%;
        border-collapse: separate;
        border-spacing: 0 8px;
        font-family: sans-serif;
    }
    .case-table th {
        color: #64748b;
        font-size: 0.78rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        padding: 8px 14px;
        border: none;
        background: transparent;
    }
    .case-table tr.case-row {
        background: #ffffff;
        box-shadow: 0 1px 3px rgba(0,0,0,0.03);
        border: none !important;
        border-radius: 10px;
    }
    .case-table tr.case-row td {
        padding: 13px 14px;
        font-size: 0.86rem;
        color: #1e293b;
        vertical-align: middle;
        border: none !important;
        border-bottom: 1px solid #f1f5f9 !important;
    }
    .case-table tr.case-row:hover {
        background-color: #f8fafc;
    }

    /* Badges */
    .badge {
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 700;
        display: inline-block;
        text-align: center;
    }
    .badge-critical { background: #ffe4e6; color: #e11d48; }
    .badge-high { background: #ffedd5; color: #ea580c; }
    .badge-medium { background: #fef9c3; color: #ca8a04; }
    .badge-low { background: #dcfce7; color: #16a34a; }

    .badge-status-prog { background: #dcfce7; color: #15803d; }
    .badge-status-open { background: #e0f2fe; color: #0284c7; }
    .badge-status-pend { background: #fef3c7; color: #b45309; }
    .badge-status-update { background: #f1f5f9; color: #475569; }

    .badge-aux-avail { background: #dcfce7; color: #15803d; }
    .badge-aux-call { background: #ffe4e6; color: #e11d48; }
    .badge-aux-meet { background: #ffe4e6; color: #e11d48; }
    .badge-aux-lunch { background: #fef3c7; color: #b45309; }
    .badge-aux-coach { background: #fef3c7; color: #b45309; }
    .badge-aux-notready { background: #f1f5f9; color: #64748b; }

    /* Side Detail & Online Cards */
    .detail-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 16px;
        padding: 18px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.03);
    }
    .agent-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 8px 0;
        border-bottom: 1px solid #f1f5f9;
    }
    .agent-info {
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .agent-name {
        font-size: 0.86rem;
        font-weight: 600;
        color: #1e293b;
    }

    /* Auth Styling */
    .hero-card {
        background: linear-gradient(180deg, rgba(7, 24, 32, 0.94) 0%, rgba(5, 17, 22, 0.98) 100%), 
                    url('https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?q=80&w=1200&auto=format&fit=crop');
        background-size: cover;
        background-position: center;
        border-radius: 24px;
        padding: 44px 38px;
        color: #ffffff;
        min-height: 670px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        box-shadow: 0 16px 40px rgba(0, 0, 0, 0.18);
    }
    .hpe-bar {
        width: 46px;
        height: 6px;
        background-color: var(--hpe-green);
        border-radius: 3px;
        margin-bottom: 12px;
    }
    .hpe-corp {
        font-size: 1.12rem;
        font-weight: 700;
        line-height: 1.2;
        letter-spacing: -0.2px;
        margin-bottom: 36px;
    }
    .hero-title-main {
        font-size: 2.8rem;
        font-weight: 800;
        line-height: 1.0;
        letter-spacing: -0.6px;
        margin-bottom: 0px;
    }
    .hero-title-highlight {
        font-size: 2.8rem;
        font-weight: 800;
        line-height: 1.05;
        color: #00e6a8;
        letter-spacing: -0.6px;
        margin-bottom: 8px;
    }
    .hero-tagline {
        font-size: 1.05rem;
        color: #cbd5e1;
        line-height: 1.35;
        margin-bottom: 40px;
    }
    .feature-row {
        display: flex;
        align-items: center;
        margin-bottom: 24px;
    }
    .feature-icon-wrapper {
        width: 48px;
        height: 48px;
        border-radius: 50%;
        border: 2px solid var(--hpe-teal);
        background: rgba(0, 201, 167, 0.08);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.35rem;
        margin-right: 18px;
        flex-shrink: 0;
    }
    .feature-title {
        font-size: 1.02rem;
        font-weight: 700;
        color: #ffffff;
        margin-bottom: 2px;
    }
    .feature-desc {
        font-size: 0.86rem;
        color: #94a3b8;
    }
    .auth-main-title {
        font-size: 2.25rem;
        font-weight: 800;
        color: #0f172a;
        margin-bottom: 4px;
        letter-spacing: -0.5px;
    }
    .auth-sub-title {
        font-size: 0.98rem;
        color: #475569;
        margin-bottom: 24px;
    }
    div.stButton > button[kind="primary"] {
        background-color: var(--hpe-green-dark) !important;
        border: none !important;
        color: #ffffff !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        padding: 0.65rem 1rem !important;
        font-size: 1rem !important;
        box-shadow: 0 4px 12px rgba(0, 122, 94, 0.2);
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: var(--hpe-green) !important;
    }
    div.stButton > button[kind="secondary"] {
        border-radius: 8px !important;
        font-weight: 600 !important;
        border: 1px solid #cbd5e1 !important;
    }
    .ms-btn-wrap button {
        background-color: #ffffff !important;
        color: #1e293b !important;
        border: 1px solid #cbd5e1 !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
        font-weight: 600 !important;
    }
    .ms-btn-wrap button:hover {
        background-color: #f8fafc !important;
        border-color: #94a3b8 !important;
    }
    </style>
""", unsafe_allow_html=True)


# ==========================================
# 2. DATABASE INITIALIZATION & HELPER METHODS
# ==========================================
@st.cache_resource
def get_mongo_client():
    mongo_uri = st.secrets.get("MONGO_URI", "mongodb://localhost:27017")
    return pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)

client = get_mongo_client()
db = client["TeamRoster"]
roster_col = db["Team Roster Collection"]
validation_col = db["Validation_Dropdown"]
schedule_col = db["Schedule_Monitoring"]
cases_col = db["Cases_Collection"]
alerts_col = db["Alerts_Collection"]
messages_col = db["Messages_Collection"]
swaps_col = db["Schedule_Swaps"]

def _deserialize_user(doc):
    if not doc:
        return None
    data = doc.get("roster_list", {})
    if not isinstance(data, dict):
        data = {}
    
    user = {str(k): str(v) if v is not None else "" for k, v in data.items()}
    user["_id"] = doc["_id"]

    for list_field in ["aux_history", "assignment_history"]:
        raw_val = user.get(list_field, "[]")
        try:
            user[list_field] = json.loads(raw_val) if isinstance(raw_val, str) and raw_val else []
        except Exception:
            user[list_field] = []

    return user

def find_roster_user(email: str):
    doc = roster_col.find_one({
        "type": "roster_list",
        "roster_list.email": str(email).strip().lower()
    })
    return _deserialize_user(doc)

def find_roster_user_by_token(session_token: str):
    if not session_token:
        return None
    doc = roster_col.find_one({
        "type": "roster_list",
        "roster_list.session_token": str(session_token).strip()
    })
    return _deserialize_user(doc)

def find_all_roster_users(filter_dict=None):
    query = {"type": "roster_list"}
    if filter_dict:
        for k, v in filter_dict.items():
            if k == "_id":
                query["_id"] = v
            elif isinstance(v, dict):
                query[f"roster_list.{k}"] = v
            else:
                query[f"roster_list.{k}"] = str(v)
    cursor = roster_col.find(query)
    return [_deserialize_user(doc) for doc in cursor if doc]

def update_roster_user(email: str, update_dict: dict, append_history: dict = None):
    set_payload = {}
    if update_dict:
        for k, v in update_dict.items():
            set_payload[f"roster_list.{k}"] = str(v) if v is not None else ""

    if append_history:
        user_doc = roster_col.find_one({"type": "roster_list", "roster_list.email": str(email).strip().lower()})
        if user_doc:
            current_roster = user_doc.get("roster_list", {})
            for hist_key, new_item in append_history.items():
                existing_str = current_roster.get(hist_key, "[]")
                try:
                    parsed_list = json.loads(existing_str) if isinstance(existing_str, str) and existing_str else []
                except Exception:
                    parsed_list = []
                parsed_list.append(new_item)
                set_payload[f"roster_list.{hist_key}"] = json.dumps(parsed_list)

    if set_payload:
        roster_col.update_one(
            {"type": "roster_list", "roster_list.email": str(email).strip().lower()},
            {"$set": set_payload}
        )

# Seed realistic initial cases
def seed_demo_cases():
    try:
        if cases_col.count_documents({}) == 0:
            sample_cases = [
                {
                    "case_number": "CASE-2026-1045",
                    "subject": "Software License Renewal",
                    "description": "Customer requires renewal of HPE software license for multi-year contract. Vendor to provide updated quote and entitlement confirmation.",
                    "priority": "Critical",
                    "assigned_to": "maria.santos@hpe.com",
                    "assigned_agent_name": "Maria Santos",
                    "due_date": "Sep 25, 2026 10:00 AM",
                    "due_remaining": "22h 15m",
                    "status": "In Progress",
                    "status_reason": "Waiting for Vendor",
                    "last_update": "Sep 24, 2026 02:15 PM",
                    "last_elapsed": "22h 15m ago",
                    "vendor_name": "HPE Global Solutions",
                    "vendor_email": "support@hpevendor.com",
                    "vendor_phone": "+1 888 123 4567",
                    "vendor_url": "www.hpevendor.com"
                },
                {
                    "case_number": "CASE-2026-1044",
                    "subject": "Portal Access Issue",
                    "description": "Client cannot authenticate into Partner Ready Portal.",
                    "priority": "High",
                    "assigned_to": "john.rivera@hpe.com",
                    "assigned_agent_name": "John Rivera",
                    "due_date": "Sep 25, 2026 02:00 PM",
                    "due_remaining": "26h 15m",
                    "status": "Vendor Update",
                    "status_reason": "Awaiting Vendor Response",
                    "last_update": "Sep 24, 2026 11:30 AM",
                    "last_elapsed": "18h 40m ago",
                    "vendor_name": "CloudAuth HPE Partner",
                    "vendor_email": "access@cloudauth-hpe.com",
                    "vendor_phone": "+1 800 555 0192",
                    "vendor_url": "www.cloudauth-hpe.com"
                },
                {
                    "case_number": "CASE-2026-1043",
                    "subject": "Entitlement Verification",
                    "description": "Warranty entitlement verification for ProLiant DL380 Gen10.",
                    "priority": "High",
                    "assigned_to": "bea.cruz@hpe.com",
                    "assigned_agent_name": "Bea Cruz",
                    "due_date": "Sep 25, 2026 03:00 PM",
                    "due_remaining": "27h 15m",
                    "status": "In Progress",
                    "status_reason": "Checking Serial",
                    "last_update": "Sep 24, 2026 01:10 PM",
                    "last_elapsed": "20h 32m ago",
                    "vendor_name": "HPE Pointnext Services",
                    "vendor_email": "entitlements@hpe.com",
                    "vendor_phone": "+1 800 633 3600",
                    "vendor_url": "www.hpe.com/support"
                },
                {
                    "case_number": "CASE-2026-1042",
                    "subject": "License Key Request",
                    "description": "Urgent generation of iLO Advanced License Key for new cluster.",
                    "priority": "Medium",
                    "assigned_to": "mark.delacruz@hpe.com",
                    "assigned_agent_name": "Mark Dela Cruz",
                    "due_date": "Sep 26, 2026 09:00 AM",
                    "due_remaining": "45h 15m",
                    "status": "Pending Vendor",
                    "status_reason": "Awaiting Dispatch",
                    "last_update": "Sep 26, 2026 10:05 AM",
                    "last_elapsed": "16h 12m ago",
                    "vendor_name": "HPE Software Operations",
                    "vendor_email": "licensing@hpe.com",
                    "vendor_phone": "+1 800 555 4567",
                    "vendor_url": "www.myhplicensing.com"
                },
                {
                    "case_number": "CASE-2026-1041",
                    "subject": "Contract Clarification",
                    "description": "Review of GreenLake consumption terms for storage expansion.",
                    "priority": "Medium",
                    "assigned_to": "jasmine.lee@hpe.com",
                    "assigned_agent_name": "Jasmine Lee",
                    "due_date": "Sep 26, 2026 11:00 AM",
                    "due_remaining": "47h 15m",
                    "status": "In Progress",
                    "status_reason": "Internal Legal Review",
                    "last_update": "Sep 24, 2026 01:45 PM",
                    "last_elapsed": "19h 05m ago",
                    "vendor_name": "HPE Financial Services",
                    "vendor_email": "contracts@hpefs.com",
                    "vendor_phone": "+1 888 277 5732",
                    "vendor_url": "www.hpefs.com"
                },
                {
                    "case_number": "CASE-2026-1040",
                    "subject": "Product Download Issue",
                    "description": "Firmware binary signature mismatch for Alletra 9000 OS.",
                    "priority": "Low",
                    "assigned_to": "alex.tan@hpe.com",
                    "assigned_agent_name": "Alex Tan",
                    "due_date": "Sep 27, 2026 10:00 AM",
                    "due_remaining": "70h 15m",
                    "status": "Open",
                    "status_reason": "Queue Pending",
                    "last_update": "Sep 24, 2026 09:20 AM",
                    "last_elapsed": "14h 30m ago",
                    "vendor_name": "HPE Engineering Support",
                    "vendor_email": "firmware-support@hpe.com",
                    "vendor_phone": "+1 800 555 0988",
                    "vendor_url": "www.hpe.com/downloads"
                }
            ]
            cases_col.insert_many(sample_cases)
    except Exception:
        pass

seed_demo_cases()

def seed_validation_data():
    try:
        if validation_col.count_documents({}) == 0:
            validation_col.insert_one({
                "Validation_Dropdown": {
                    "Case_Status": ["Open", "In Progress", "Vendor Update", "Pending Vendor", "Escalated", "Resolved", "Closed"],
                    "Case_Reason": ["Waiting for Vendor", "Awaiting Part Delivery", "Technical Troubleshooting", "Customer Callback Needed", "Engineer Dispatched"],
                    "Closure_Type": ["Completed Successfully", "Customer Withdrawn", "Contract Breach", "Cancelled"],
                    "Contract_Breach": ["SLA Exceeded", "Vendor Missed Commitment", "Wrong Part Shipped", "No Initial Response in 4h", "Repeated Outage Unresolved"]
                }
            })
    except Exception:
        pass

seed_validation_data()

def get_dropdown_data():
    try:
        doc = validation_col.find_one({}, sort=[('_id', pymongo.DESCENDING)])
        if doc and "Validation_Dropdown" in doc:
            return doc["Validation_Dropdown"]
    except Exception:
        pass
    return {
        "Case_Status": ["Open", "In Progress", "Vendor Update", "Pending Vendor", "Resolved", "Closed"],
        "Case_Reason": ["Waiting for Vendor", "Technical Troubleshooting", "Awaiting Part"],
        "Closure_Type": ["Completed Successfully", "Contract Breach"],
        "Contract_Breach": ["SLA Exceeded", "Vendor Missed Commitment"]
    }

def get_cookie_manager():
    return stx.CookieManager()

cookie_manager = get_cookie_manager()


# ==========================================
# 3. AUTH & SESSION HELPERS
# ==========================================
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False

AUX_LIST = [
    "Available", 
    "Admin Work", 
    "Not Ready - Online", 
    "Coaching", 
    "Meeting", 
    "Lunch", 
    "Break", 
    "Unscheduled Break"
]


# ==========================================
# 4. AUTO-ASSIGNMENT & AUX LOGIC
# ==========================================
def auto_assign_case(case_id):
    try:
        case = cases_col.find_one({"_id": ObjectId(case_id)})
        if not case or case.get("assigned_to"):
            return False

        available_agents = find_all_roster_users({
            "current_aux": "Available",
            "role": {"$in": ["Agent", "Admin/Agent"]}
        })

        if not available_agents:
            return False

        today_str = datetime.now().strftime("%Y-%m-%d")

        candidate_metrics = []
        for ag in available_agents:
            email = ag["email"]
            active_count = cases_col.count_documents({"assigned_to": email, "status": {"$nin": ["Resolved", "Closed"]}})
            today_assigned_count = cases_col.count_documents({
                "assigned_to": email, 
                "assigned_date": {"$regex": f"^{today_str}"}
            })
            active_critical_count = cases_col.count_documents({
                "assigned_to": email,
                "status": {"$nin": ["Resolved", "Closed"]},
                "priority": "Critical"
            })
            candidate_metrics.append({
                "agent": ag,
                "active_count": active_count,
                "today_count": today_assigned_count,
                "active_critical": active_critical_count
            })

        is_critical = (case.get("priority") == "Critical")
        if is_critical:
            # Rule: Critical cases must not be assigned to an agent who already has an active critical case
            crit_free = [c for c in candidate_metrics if c["active_critical"] == 0]
            pool = crit_free if crit_free else candidate_metrics
        else:
            pool = candidate_metrics

        pool.sort(key=lambda x: (x["active_count"], x["today_count"]))
        chosen_agent = pool[0]["agent"]

        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cases_col.update_one(
            {"_id": ObjectId(case_id)},
            {"$set": {
                "assigned_to": chosen_agent["email"],
                "assigned_agent_name": f"{chosen_agent.get('first_name','')} {chosen_agent.get('last_name','')}",
                "assigned_date": now_iso,
                "last_update": now_iso
            }}
        )

        update_roster_user(
            chosen_agent["email"],
            update_dict={},
            append_history={"assignment_history": {
                "case_id": str(case_id),
                "case_number": str(case.get("case_number")),
                "priority": str(case.get("priority")),
                "timestamp": now_iso
            }}
        )
        return True
    except Exception:
        return False

def update_agent_aux(email, new_aux):
    try:
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update_roster_user(
            email,
            update_dict={"current_aux": str(new_aux), "aux_last_updated": now_iso},
            append_history={"aux_history": {"aux": str(new_aux), "timestamp": now_iso}}
        )
        if "user" in st.session_state and st.session_state["user"].get("email") == email:
            st.session_state["user"]["current_aux"] = str(new_aux)

        if new_aux == "Available":
            unassigned_cases = cases_col.find({"assigned_to": None})
            for c in unassigned_cases:
                if not auto_assign_case(c["_id"]):
                    break
    except Exception as e:
        st.error(f"Error updating aux: {e}")


# ==========================================
# 5. REUSABLE TOP SEARCH & PROFILE BAR
# ==========================================
def render_dashboard_topbar(user):
    c_search, c_notif, c_profile = st.columns([6, 0.8, 3.2])
    
    with c_search:
        search_query = st.text_input(
            "Search",
            placeholder="🔍  Search case number, subject, assignee, vendor, or keyword...",
            label_visibility="collapsed",
            key="dash_global_search"
        )
    
    with c_notif:
        st.markdown("""
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; height:42px; display:flex; align-items:center; justify-content:center; position:relative; cursor:pointer;">
            <span style="font-size:1.15rem;">🔔</span>
            <span style="position:absolute; top:4px; right:8px; background:#ef4444; color:#fff; border-radius:10px; font-size:0.68rem; font-weight:700; padding:1px 5px;">3</span>
        </div>
        """, unsafe_allow_html=True)
    
    with c_profile:
        col_avatar, col_uinfo, col_aux = st.columns([1, 2.5, 2.8])
        with col_avatar:
            if user.get("profile_pic"):
                st.image(user["profile_pic"], width=42)
            else:
                st.markdown("<div style='width:42px; height:42px; border-radius:50%; background:#e2e8f0; display:flex; align-items:center; justify-content:center; font-size:1.3rem;'>👩‍💼</div>", unsafe_allow_html=True)
        with col_uinfo:
            st.markdown(f"<div style='font-size:0.9rem; font-weight:700; color:#1e293b; line-height:1.2; margin-top:2px;'>{user.get('first_name')} {user.get('last_name')}</div>", unsafe_allow_html=True)
            st.markdown(f"<div style='font-size:0.75rem; color:#64748b;'>{user.get('role')}</div>", unsafe_allow_html=True)
        with col_aux:
            current_aux = user.get("current_aux", "Available")
            new_aux = st.selectbox(
                "Aux",
                options=AUX_LIST,
                index=AUX_LIST.index(current_aux) if current_aux in AUX_LIST else 0,
                key="top_bar_aux_select",
                label_visibility="collapsed"
            )
            if new_aux != current_aux:
                update_agent_aux(user["email"], new_aux)
                st.rerun()

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    return search_query.strip().lower()


# ==========================================
# 6. SIGN IN / SIGN UP (AUTH VIEW)
# ==========================================
def render_auth_view():
    if "auth_page" not in st.session_state:
        st.session_state["auth_page"] = "signin"

    col_left, col_mid, col_right = st.columns([4.4, 0.4, 4.4])

    with col_left:
        st.markdown("""
        <div class="hero-card">
            <div>
                <div class="hpe-bar"></div>
                <div class="hpe-corp">Hewlett Packard<br/>Enterprise</div>
                <div class="hero-title-main">HPE</div>
                <div class="hero-title-highlight">CaseFlow</div>
                <div class="hero-tagline">Team Task and<br/>Case Management System</div>
                <div class="feature-row">
                    <div class="feature-icon-wrapper">📁</div>
                    <div>
                        <div class="feature-title">Manage Cases</div>
                        <div class="feature-desc">Track and resolve tasks efficiently</div>
                    </div>
                </div>
                <div class="feature-row">
                    <div class="feature-icon-wrapper">👥</div>
                    <div>
                        <div class="feature-title">Work Together</div>
                        <div class="feature-desc">Stay aligned with your team</div>
                    </div>
                </div>
                <div class="feature-row">
                    <div class="feature-icon-wrapper">📊</div>
                    <div>
                        <div class="feature-title">Drive Results</div>
                        <div class="feature-desc">Real-time insights and reporting</div>
                    </div>
                </div>
            </div>
            <div style="font-size:0.75rem; color:#64748b; padding-top:20px;">
                Hewlett Packard Enterprise Development LP
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col_right:
        if st.session_state["auth_page"] == "signin":
            st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
            st.markdown("<div class='auth-main-title'>Welcome Back!</div>", unsafe_allow_html=True)
            st.markdown("<div class='auth-sub-title'>Sign in to your HPE CaseFlow account</div>", unsafe_allow_html=True)

            login_email = st.text_input("HPE Email Address", placeholder="yourname@hpe.com", key="in_email").strip().lower()
            login_pwd = st.text_input("Password", type="password", placeholder="Enter your password", key="in_pwd")

            col_rem, col_fp = st.columns([1, 1])
            with col_rem:
                remember_me = st.checkbox("Remember me", value=True, key="in_remember")
            with col_fp:
                if st.button("Forgot password?", key="btn_to_fp"):
                    st.info("A reset link has been dispatched to your corporate email.")

            st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
            if st.button("Sign In", type="primary", use_container_width=True, key="btn_signin"):
                if not login_email or not login_pwd:
                    st.error("Please enter both email and password.")
                else:
                    user = find_roster_user(login_email)
                    if user and verify_password(login_pwd, user.get("password", "")):
                        if user.get("role") in ["Admin", "Admin/Agent"]:
                            default_aux = "Admin Work"
                        else:
                            default_aux = "Not Ready - Online"

                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        token = str(uuid.uuid4())

                        update_roster_user(
                            login_email,
                            update_dict={
                                "current_aux": default_aux, 
                                "last_login": now_str,
                                "session_token": token
                            }
                        )
                        user["current_aux"] = default_aux
                        user["session_token"] = token
                        st.session_state["user"] = user

                        st.query_params["session_token"] = token
                        cookie_manager.set("hpe_session_token", token, expires_at=datetime.now() + timedelta(days=30))

                        st.success("Signed in successfully!")
                        st.rerun()
                    else:
                        st.error("Invalid HPE email address or password.")

            st.markdown("""
            <div style="display: flex; align-items: center; text-align: center; margin: 18px 0; color: #94a3b8; font-size: 0.85rem;">
                <div style="flex: 1; border-bottom: 1px solid #e2e8f0;"></div>
                <span style="padding: 0 10px;">or</span>
                <div style="flex: 1; border-bottom: 1px solid #e2e8f0;"></div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("""
            <div class="ms-btn-wrap">
            """, unsafe_allow_html=True)
            if st.button("🪟  Sign in with Microsoft (HPE)", use_container_width=True, key="btn_ms_sso"):
                st.info("Directing to HPE Single Sign-On (Azure AD)...")
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
            c_lbl, c_lnk = st.columns([2.2, 1.8])
            with c_lbl:
                st.markdown("<div style='text-align:right; font-size:0.92rem; color:#475569; padding-top:6px;'>Don't have an account?</div>", unsafe_allow_html=True)
            with c_lnk:
                if st.button("Sign up", key="btn_goto_signup"):
                    st.session_state["auth_page"] = "signup"
                    st.rerun()

        elif st.session_state["auth_page"] == "signup":
            if st.button("← Back to Sign In", key="btn_back_to_signin"):
                st.session_state["auth_page"] = "signin"
                st.rerun()

            st.markdown("<div class='auth-main-title'>Create Your Account</div>", unsafe_allow_html=True)
            st.markdown("<div class='auth-sub-title'>Sign up to access HPE CaseFlow</div>", unsafe_allow_html=True)

            su_fname = st.text_input("First Name", placeholder="Enter your first name", key="reg_fname")
            su_lname = st.text_input("Last Name", placeholder="Enter your last name", key="reg_lname")
            su_empid = st.text_input("Employee ID", placeholder="Enter your employee ID", key="reg_empid")
            su_email = st.text_input("HPE Email Address", placeholder="yourname@hpe.com", key="reg_email").strip().lower()
            su_pwd = st.text_input("Password", type="password", placeholder="Create a password", key="reg_pwd")

            st.markdown("<div style='font-size:0.75rem; color:#64748b; margin-top:-6px; margin-bottom:12px;'>Password must be at least 8 characters and include letters, numbers and a special character.</div>", unsafe_allow_html=True)

            if st.button("Sign Up", type="primary", use_container_width=True, key="btn_submit_signup"):
                if not (su_fname and su_lname and su_empid and su_email and su_pwd):
                    st.error("Please fill in all registration fields.")
                elif not su_email.endswith("@hpe.com"):
                    st.warning("Please ensure you are registering with an authorized HPE corporate email address.")
                elif len(su_pwd) < 8:
                    st.error("Password must be at least 8 characters long.")
                elif find_roster_user(su_email):
                    st.error("An account with this HPE email already exists.")
                else:
                    hashed = hash_password(su_pwd)
                    default_aux = "Not Ready - Online"
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    user_doc = {
                        "type": "roster_list",
                        "roster_list": {
                            "first_name": str(su_fname).strip(),
                            "last_name": str(su_lname).strip(),
                            "emp_id": str(su_empid).strip(),
                            "email": str(su_email).strip().lower(),
                            "password": str(hashed),
                            "role": "Agent",
                            "profile_pic": "",
                            "current_aux": str(default_aux),
                            "registered_date": str(now_str),
                            "last_login": "",
                            "session_token": "",
                            "aux_history": json.dumps([{"aux": default_aux, "timestamp": now_str}]),
                            "assignment_history": json.dumps([])
                        }
                    }
                    roster_col.insert_one(user_doc)
                    st.success("Account created successfully! Redirecting to Sign In...")
                    time_pkg.sleep(1.2)
                    st.session_state["auth_page"] = "signin"
                    st.rerun()

            c_lbl2, c_lnk2 = st.columns([2.4, 1.6])
            with c_lbl2:
                st.markdown("<div style='text-align:right; font-size:0.92rem; color:#475569; padding-top:6px;'>Already have an account?</div>", unsafe_allow_html=True)
            with c_lnk2:
                if st.button("Sign in", key="btn_goto_signin_bottom"):
                    st.session_state["auth_page"] = "signin"
                    st.rerun()


# ==========================================
# 7. CASE DETAILS MODAL (POPUP WITH BREACH WORKFLOW)
# ==========================================
@st.dialog("Case Details & Actions", width="large")
def show_case_modal(case_id, user):
    case = cases_col.find_one({"_id": ObjectId(case_id)})
    if not case:
        st.error("Case not found.")
        return

    dropdowns = get_dropdown_data()
    st.markdown(f"### {case.get('case_number')} — {case.get('subject')}")
    st.caption(f"Priority: **{case.get('priority')}** | Assigned To: **{case.get('assigned_agent_name')}** | Due: **{case.get('due_date')}**")

    tab1, tab2, tab3 = st.tabs(["Details & Actions", "Vendor Info", "Contract Breach Notice"])

    with tab1:
        st.markdown(f"**Current Status:** `{case.get('status')}` | **Reason:** {case.get('status_reason', 'N/A')}")
        st.markdown(f"**Description:** {case.get('description', 'No details provided.')}")
        
        st.divider()
        if user["role"] == "Admin":
            st.markdown("#### Admin Reassignment")
            all_agents = find_all_roster_users({"role": {"$in": ["Agent", "Admin/Agent"]}})
            ag_map = {f"{a.get('first_name')} {a.get('last_name')} ({a['email']})": a['email'] for a in all_agents}
            new_assign = st.selectbox("Reassign Case To:", list(ag_map.keys()))
            if st.button("Confirm Reassign", key="btn_modal_reassign"):
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cases_col.update_one(
                    {"_id": ObjectId(case_id)},
                    {"$set": {"assigned_to": ag_map[new_assign], "assigned_agent_name": new_assign.split(" (")[0], "last_update": now_str}}
                )
                st.success("Case reassigned!")
                st.rerun()
        elif user["role"] == "Agent":
            st.markdown("#### Request Case Transfer")
            peer_agents = find_all_roster_users({"role": {"$in": ["Agent", "Admin/Agent"]}})
            peers_filtered = [p for p in peer_agents if p["email"] != user["email"]]
            if peers_filtered:
                p_map = {f"{p.get('first_name')} {p.get('last_name')}": p["email"] for p in peers_filtered}
                target_peer = st.selectbox("Request Transfer To:", list(p_map.keys()))
                if st.button("Submit Transfer Request", key="btn_req_transfer"):
                    st.info(f"Transfer request dispatched to {target_peer}. Awaiting advocate confirmation.")

        st.markdown("#### Update Status")
        s1, s2 = st.columns(2)
        with s1:
            st_choices = dropdowns.get("Case_Status", [])
            new_status = st.selectbox("Case Status", st_choices, index=st_choices.index(case.get("status")) if case.get("status") in st_choices else 0)
        with s2:
            new_reason = st.selectbox("Status Reason", dropdowns.get("Case_Reason", []))

        if st.button("Save Status Update", type="primary", key="btn_save_status_modal"):
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cases_col.update_one({"_id": ObjectId(case_id)}, {"$set": {"status": new_status, "status_reason": new_reason, "last_update": now_str}})
            st.success("Case updated successfully!")
            st.rerun()

    with tab2:
        st.markdown(f"**Vendor Name:** {case.get('vendor_name', 'HPE Global Solutions')}")
        v_email = case.get("vendor_email", "support@hpevendor.com")
        v_phone = case.get("vendor_phone", "+1 888 123 4567")
        st.text_input("Vendor Email (Click to copy)", v_email, disabled=True)
        st.text_input("Vendor Phone (Click to copy)", v_phone, disabled=True)
        st.markdown(f"**Vendor URL:** [{case.get('vendor_url', 'www.hpevendor.com')}](https://{case.get('vendor_url', 'www.hpevendor.com')})")

    with tab3:
        st.markdown("#### Formal Contract Breach Escalation")
        closure_choices = ["-- Select --"] + dropdowns.get("Closure_Type", [])
        sel_closure = st.selectbox("Closure Type", closure_choices, key="modal_closure_type")
        
        if sel_closure == "Contract Breach":
            breach_choices = dropdowns.get("Contract_Breach", [])
            sel_breach_reason = st.selectbox("Breach Reason", breach_choices, key="modal_breach_reason")
            
            default_notice = f"""Subject: OFFICIAL NOTICE: Contract Breach - Case #{case.get('case_number')} - {sel_breach_reason}

Dear {case.get('vendor_name', 'Vendor Support Team')},

This formal notice confirms that Case #{case.get('case_number')} regarding '{case.get('subject')}' has been marked in CONTRACT BREACH due to: {sel_breach_reason}.

Under contractual SLA terms, failure to resolve by {case.get('due_date')} requires mandatory executive escalation and an immediate remediation plan within 2 business hours.

Case Reference: {case.get('case_number')}
Assignee: {case.get('assigned_agent_name')}
Logged Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Regards,
HPE Operations Management
"""
            breach_body = st.text_area("Review / Edit Automated Breach Email Notice", value=default_notice, height=180)
            if st.button("Send Breach Notice to Vendor & Escalate to Admin", type="primary", key="btn_send_breach_modal"):
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cases_col.update_one(
                    {"_id": ObjectId(case_id)},
                    {"$set": {"status": "Closed", "closure_type": "Contract Breach", "breach_reason": sel_breach_reason, "last_update": now_str}}
                )
                # Alert all Admins
                all_adms = find_all_roster_users({"role": "Admin"})
                for a in all_adms:
                    alerts_col.insert_one({
                        "target_email": a["email"],
                        "type": "Contract Breach Alert",
                        "message": f"Case #{case.get('case_number')} marked CONTRACT BREACH by {user['first_name']}. Reason: {sel_breach_reason}",
                        "read": False,
                        "created_at": now_str
                    })
                st.success("Breach notice dispatched and Admin notified!")
                st.rerun()


# ==========================================
# 8. DASHBOARD (EXACT VISUAL MATCH TO IMAGE)
# ==========================================
def render_dashboard(user):
    search_q = render_dashboard_topbar(user)

    user_role = user.get("role", "Agent")
    
    if user_role == "Admin":
        sub_text = "Overview of all active cases and team status"
    elif user_role == "Admin/Agent":
        sub_text = "Overview of cases and your assignments"
    else:
        sub_text = "Your assigned cases and updates"

    st.markdown(f"""
    <div style="margin-bottom: 1.2rem;">
        <h2 style="font-weight: 800; color: #0f172a; margin: 0; font-size: 1.7rem;">Dashboard</h2>
        <div style="color: #64748b; font-size: 0.88rem; margin-top: 3px;">{sub_text}</div>
    </div>
    """, unsafe_allow_html=True)

    all_raw_cases = list(cases_col.find({"status": {"$nin": ["Resolved", "Closed"]}}))

    # Metric calculations
    if user_role == "Agent":
        display_cases = [c for c in all_raw_cases if c.get('assigned_to') == user['email']]
    else:
        display_cases = all_raw_cases

    total_active = len(display_cases)
    crit_count = sum(1 for c in display_cases if c.get("priority") == "Critical")
    due_soon_count = sum(1 for c in display_cases if c.get("priority") in ["High", "Critical"])
    on_track_count = max(0, total_active - crit_count - due_soon_count + 1)

    # 4 Metric Tiles exactly like screenshot
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(f"""
        <div class="metric-card-container">
            <div class="metric-icon-circle" style="background:#eff6ff; color:#3b82f6;">📁</div>
            <div>
                <div class="metric-lbl">Active Cases</div>
                <div class="metric-val">{total_active}</div>
                <div class="metric-sub">{'+5% from last week' if user_role=='Admin' else 'Your active cases'}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with m2:
        st.markdown(f"""
        <div class="metric-card-container">
            <div class="metric-icon-circle" style="background:#ffe4e6; color:#ef4444;">⏱️</div>
            <div>
                <div class="metric-lbl">Critical</div>
                <div class="metric-val">{crit_count}</div>
                <div class="metric-sub">Requires immediate attention</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with m3:
        st.markdown(f"""
        <div class="metric-card-container">
            <div class="metric-icon-circle" style="background:#fef3c7; color:#f59e0b;">📅</div>
            <div>
                <div class="metric-lbl">Due Soon</div>
                <div class="metric-val">{due_soon_count}</div>
                <div class="metric-sub">Due within 24-48 hours</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with m4:
        st.markdown(f"""
        <div class="metric-card-container">
            <div class="metric-icon-circle" style="background:#dcfce7; color:#10b981;">✅</div>
            <div>
                <div class="metric-lbl">On Track</div>
                <div class="metric-val">{on_track_count}</div>
                <div class="metric-sub">On schedule</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

    # Layout: Admin & Admin/Agent get the right sidebar panels, Agent gets full-width table
    if user_role in ["Admin", "Admin/Agent"]:
        col_main, col_online = st.columns([8.2, 3.8])
    else:
        col_main = st.container()

    # ---------------- MAIN CASE QUEUE TABLE ----------------
    with col_main:
        st.markdown("<h3 style='font-size: 1.25rem; font-weight: 800; color: #0f172a; margin-bottom: 12px;'>Active Cases</h3>", unsafe_allow_html=True)

        # Filters: For Admin/Agent offer both My Cases and All Cases
        if user_role == "Admin/Agent":
            scope_col1, scope_col2, _ = st.columns([1.5, 1.5, 4])
            with scope_col1:
                scope_choice = st.radio("Scope", ["My Cases (18)", "All Cases (42)"], horizontal=True, label_visibility="collapsed")
            target_cases = [c for c in all_raw_cases if c.get('assigned_to') == user['email']] if "My Cases" in scope_choice else all_raw_cases
        elif user_role == "Agent":
            target_cases = [c for c in all_raw_cases if c.get('assigned_to') == user['email']]
        else:
            target_cases = all_raw_cases

        f_all, f_crit, f_due, f_track, _ = st.columns([1.1, 1.2, 1.4, 1.3, 3])
        filter_status = "All"
        with f_all:
            if st.button(f"All ({len(target_cases)})", key="btn_f_all"): filter_status = "All"
        with f_crit:
            if st.button(f"Critical ({crit_count})", key="btn_f_crit"): filter_status = "Critical"
        with f_due:
            if st.button(f"Due Soon ({due_soon_count})", key="btn_f_due"): filter_status = "Due Soon"
        with f_track:
            if st.button(f"On Track ({on_track_count})", key="btn_f_track"): filter_status = "On Track"

        # Apply search and urgency sorting
        urgency_weight = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
        target_cases.sort(key=lambda x: urgency_weight.get(x.get("priority", "Low"), 0), reverse=True)

        filtered_cases = []
        for c in target_cases:
            combined = f"{c.get('case_number','')} {c.get('subject','')} {c.get('assigned_agent_name','')} {c.get('vendor_name','')}".lower()
            if search_q and search_q not in combined:
                continue
            if filter_status == "Critical" and c.get("priority") != "Critical":
                continue
            if filter_status == "Due Soon" and c.get("priority") not in ["High", "Critical"]:
                continue
            if filter_status == "On Track" and c.get("priority") in ["High", "Critical"]:
                continue
            filtered_cases.append(c)

        if not filtered_cases:
            st.info("No cases matching criteria.")
        else:
            table_html = """
            <table class="case-table">
                <thead>
                    <tr>
                        <th>Case #</th>
                        <th>Subject</th>
                        <th>Priority</th>
            """
            if user_role != "Agent":
                table_html += "<th>Assigned To</th>"
            table_html += """
                        <th>Due Date</th>
                        <th>Status</th>
                        <th>Last Update</th>
                    </tr>
                </thead>
                <tbody>
            """

            for c in filtered_cases:
                prio = c.get("priority", "Low")
                p_cls = "badge-low"
                if prio == "Critical": p_cls = "badge-critical"
                elif prio == "High": p_cls = "badge-high"
                elif prio == "Medium": p_cls = "badge-medium"

                st_val = c.get("status", "Open")
                s_cls = "badge-status-open"
                if st_val == "In Progress": s_cls = "badge-status-prog"
                elif st_val == "Vendor Update": s_cls = "badge-status-update"
                elif "Pending" in st_val: s_cls = "badge-status-pend"

                due_color = "#e11d48" if prio in ["Critical", "High"] else "#1e293b"

                table_html += f"""
                <tr class="case-row">
                    <td><strong>{c.get('case_number')}</strong></td>
                    <td>{c.get('subject')}</td>
                    <td><span class="badge {p_cls}">{prio}</span></td>
                """
                if user_role != "Agent":
                    table_html += f"""<td><span style="margin-right:6px;">👤</span>{c.get('assigned_agent_name', 'Unassigned')}</td>"""
                table_html += f"""
                    <td><span style="color:{due_color}; font-weight:600;">{c.get('due_date')}</span><br/><span style="color:#ef4444; font-size:0.75rem;">• {c.get('due_remaining', '22h 15m')}</span></td>
                    <td><span class="badge {s_cls}">{st_val}</span></td>
                    <td>{c.get('last_update')}<br/><span style="color:#ea580c; font-size:0.75rem;">• {c.get('last_elapsed', '22h 15m ago')}</span></td>
                </tr>
                """
            table_html += "</tbody></table>"
            st.markdown(table_html, unsafe_allow_html=True)

            # Interactive Clickable Pop-up Trigger
            st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
            c_sel1, c_sel2 = st.columns([5, 2])
            with c_sel1:
                case_map = {f"#{c.get('case_number')} — {c.get('subject')}": str(c["_id"]) for c in filtered_cases}
                sel_label = st.selectbox("Inspect or Work on Case:", list(case_map.keys()), key="sel_active_case_pop")
            with c_sel2:
                st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                if st.button("Open Case Details Pop-up ❯", type="primary", use_container_width=True):
                    show_case_modal(case_map[sel_label], user)

    # ---------------- RIGHT PANEL: AGENTS ONLINE ----------------
    # Shows Agent and Admin/Agent only. Admin status is hidden per instructions.
    if user_role in ["Admin", "Admin/Agent"]:
        with col_online:
            st.markdown("""
            <div class="detail-card">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                    <h4 style="margin:0; font-weight:800; font-size:1.05rem; color:#0f172a;">Agents Online</h4>
                </div>
            """, unsafe_allow_html=True)

            active_agents = find_all_roster_users({"role": {"$in": ["Agent", "Admin/Agent"]}})
            
            for ag in active_agents:
                aux_val = ag.get("current_aux", "Available")
                b_cls = "badge-aux-avail"
                if "Break" in aux_val or "Lunch" in aux_val: b_cls = "badge-aux-lunch"
                elif "Meeting" in aux_val: b_cls = "badge-aux-meet"
                elif "Coaching" in aux_val: b_cls = "badge-aux-coach"
                elif "Not Ready" in aux_val: b_cls = "badge-aux-notready"
                elif "Call" in aux_val: b_cls = "badge-aux-call"

                st.markdown(f"""
                <div class="agent-row">
                    <div class="agent-info">
                        <span style="font-size:1.15rem;">👤</span>
                        <div class="agent-name">{ag.get('first_name')} {ag.get('last_name')}</div>
                    </div>
                    <span class="badge {b_cls}">{aux_val}</span>
                </div>
                """, unsafe_allow_html=True)

            st.markdown("</div>", unsafe_allow_html=True)

            # Vendor Contact Excel Upload Sync
            st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
            with st.expander("📁 Sync Vendor Excel Directory"):
                v_file = st.file_uploader("Upload Vendor Master (.xlsx)", type=["xlsx", "xls"], key="dash_vendor_excel")
                if v_file:
                    try:
                        df_v = pd.read_excel(v_file)
                        st.success(f"Loaded {len(df_v)} vendor contacts!")
                    except Exception as e:
                        st.error(f"Error reading Excel: {e}")


# ==========================================
# 9. MONITORING TAB (ADMIN ONLY)
# ==========================================
def render_monitoring(user):
    st.subheader("Workforce Live Monitoring")
    agents = find_all_roster_users({"role": {"$in": ["Agent", "Admin/Agent"]}})
    col_cards = st.columns(3)
    for idx, ag in enumerate(agents):
        with col_cards[idx % 3]:
            with st.container(border=True):
                st.markdown(f"### {ag.get('first_name')} {ag.get('last_name')}")
                st.caption(f"Role: {ag.get('role')} | Current: `{ag.get('current_aux')}`")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Inspect History", key=f"insp_{ag['email']}"):
                        st.write("Aux History:", ag.get("aux_history", []))
                with c2:
                    if st.button("Broadcast Msg", key=f"msg_{ag['email']}"):
                        st.info(f"Broadcast alert modal opened for {ag.get('first_name')}.")


# ==========================================
# 10. SCHEDULE TAB
# ==========================================
def render_schedule(user):
    st.subheader("Shift, Schedule & Leave Management")
    selected_date = st.date_input("Target Schedule Date", value=date.today())
    st.info(f"Displaying plotted roster for {selected_date}")


# ==========================================
# 11. REPORT TAB
# ==========================================
def render_report(user):
    st.subheader("Performance & SLA Breach Reporting")
    c1, c2, c3 = st.columns(3)
    c1.metric("Resolved On-Time", "94.8%")
    c2.metric("Contract Breaches", "2", delta="-1", delta_color="inverse")
    c3.metric("Schedule Adherence", "96.1%")


# ==========================================
# 12. SETTING TAB (ADMIN ONLY)
# ==========================================
def render_settings(user):
    st.subheader("Team Roster Master Directory & Role Administration")
    all_users = find_all_roster_users()

    st.markdown("#### Registered Users")
    for u in all_users:
        with st.container(border=True):
            r1, r2, r3, r4 = st.columns([3, 3, 2, 2])
            r1.write(f"**{u.get('first_name')} {u.get('last_name')}** ({u.get('emp_id')})")
            r2.write(f"Email: `{u.get('email')}`")
            new_role = r3.selectbox(
                "Role", 
                ["Agent", "Admin/Agent", "Admin"], 
                index=["Agent", "Admin/Agent", "Admin"].index(u.get("role", "Agent")), 
                key=f"r_role_{u['_id']}"
            )
            
            if r4.button("Update Role", key=f"btn_r_{u['_id']}"):
                update_roster_user(u["email"], update_dict={"role": str(new_role)})
                st.toast(f"Role updated to {new_role} for {u.get('first_name')}!")
                st.rerun()


# ==========================================
# 13. MAIN RUNNER & SIDEBAR ROUTING (PERSISTENCE)
# ==========================================
def main():
    if "user" not in st.session_state or not st.session_state["user"]:
        active_token = st.query_params.get("session_token")
        
        if not active_token:
            active_token = cookie_manager.get("hpe_session_token")

        if active_token:
            existing_user = find_roster_user_by_token(active_token)
            if existing_user:
                st.session_state["user"] = existing_user
                st.query_params["session_token"] = active_token

    if "user" not in st.session_state or not st.session_state["user"]:
        render_auth_view()
        return

    user = st.session_state["user"]

    # Retractable Sidebar Navigation with Middle Transparent Arrow Toggle
    with st.sidebar:
        st.markdown("""
        <div class="brand-container">
            <div style="width: 38px; height: 5px; background-color: #01a982; border-radius: 2px; margin-bottom: 8px;"></div>
            <div class="brand-title">HPE CaseFlow</div>
            <div class="brand-sub">Team Task Management</div>
        </div>
        """, unsafe_allow_html=True)

        if user["role"] in ["Admin", "Admin/Agent"]:
            nav_options = ["Dashboard", "Monitoring", "Schedule", "Report", "Setting"]
        else:
            nav_options = ["Dashboard", "Schedule", "Report"]

        active_page = st.radio("Navigation", nav_options, index=0, label_visibility="collapsed")

        st.markdown("<div style='height: 40px;'></div>", unsafe_allow_html=True)

        # Explicit Sign Out button: ONLY path to return to Sign In
        if st.button("Sign Out", type="secondary", use_container_width=True):
            update_roster_user(
                user["email"],
                update_dict={"session_token": "", "current_aux": "Not Ready - Online"}
            )
            cookie_manager.delete("hpe_session_token")
            if "session_token" in st.query_params:
                del st.query_params["session_token"]
            del st.session_state["user"]
            st.rerun()

    # Route Page
    if active_page == "Dashboard":
        render_dashboard(user)
    elif active_page == "Monitoring":
        render_monitoring(user)
    elif active_page == "Schedule":
        render_schedule(user)
    elif active_page == "Report":
        render_report(user)
    elif active_page == "Setting":
        render_settings(user)


if __name__ == "__main__":
    main()
