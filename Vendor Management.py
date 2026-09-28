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
    page_icon="🟩",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* Main background */
    .stApp {
        background-color: #F4F6F9;
    }

    /* Hide Streamlit default chrome & deploy header */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden !important;}
    [data-testid="stDecoration"] {visibility: hidden !important;}
    [data-testid="stStatusWidget"] {visibility: hidden !important;}

    /* Disable/Hide the collapse button to make sidebar NON-RETRACTABLE */
    [data-testid="stSidebarCollapseButton"] {
        display: none !important;
    }
    button[kind="header"] {
        display: none !important;
    }

    /* Fixed Dark Sidebar Styling Matching Image */
    section[data-testid="stSidebar"] {
        background-color: #0B252C !important;
        min-width: 250px !important;
        max-width: 250px !important;
        border-right: none !important;
    }
    section[data-testid="stSidebar"] .stMarkdown,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span {
        color: #94A3B8 !important;
    }

    /* Clickable Tile Navigation Buttons in Sidebar */
    .stSidebar [data-testid="stVerticalBlock"] div.stButton > button {
        width: 100% !important;
        text-align: left !important;
        justify-content: flex-start !important;
        background-color: transparent !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 10px 14px !important;
        font-size: 14px !important;
        font-weight: 500 !important;
        color: #94A3B8 !important;
        box-shadow: none !important;
        margin-bottom: 4px !important;
        transition: all 0.2s ease !important;
    }
    .stSidebar [data-testid="stVerticalBlock"] div.stButton > button:hover {
        background: rgba(255, 255, 255, 0.05) !important;
        color: #FFFFFF !important;
    }
    .stSidebar [data-testid="stVerticalBlock"] div.stButton > button[kind="primary"] {
        background-color: #01A982 !important;
        color: #FFFFFF !important;
        font-weight: 600 !important;
    }

    /* Sign Out Button in Sidebar */
    .stSidebar div.stButton > button[key="btn_sidebar_signout"],
    .stSidebar div.stButton > button:has(div:contains("Sign Out")) {
        background-color: #1e293b !important;
        color: #ef4444 !important;
        border: 1px solid #334155 !important;
        text-align: center !important;
        justify-content: center !important;
        font-weight: 700 !important;
        margin-top: 20px !important;
    }
    .stSidebar div.stButton > button:has(div:contains("Sign Out")):hover {
        background-color: #ef4444 !important;
        color: #ffffff !important;
        border-color: #ef4444 !important;
    }

    /* Full-screen dashboard container */
    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 2rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        max-width: 100% !important;
        width: 100% !important;
    }

    :root {
        --hpe-green: #01A982;
        --hpe-green-dark: #007A5E;
    }

    /* Top Alert Banner */
    .alert-banner {
        background: #FEE2E2;
        border: 1px solid #FCA5A5;
        color: #B91C1C;
        padding: 10px 16px;
        border-radius: 10px;
        font-size: 13.5px;
        font-weight: 500;
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 18px;
    }

    /* Metric Cards */
    .metric-card {
        background: #FFFFFF;
        border-radius: 12px;
        padding: 16px 20px;
        display: flex;
        align-items: center;
        gap: 14px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
        border: 1px solid #E2E8F0;
        height: 100%;
    }
    .metric-icon {
        width: 44px;
        height: 44px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 18px;
        flex-shrink: 0;
    }
    .metric-val {
        font-size: 22px;
        font-weight: 700;
        color: #0F172A;
        line-height: 1.1;
    }
    .metric-label {
        font-size: 13px;
        color: #475569;
        font-weight: 600;
    }
    .metric-sub {
        font-size: 11px;
        color: #94A3B8;
        margin-top: 2px;
    }

    /* Custom Data Table */
    .custom-table {
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        background: #FFFFFF;
        border-radius: 12px;
        overflow: hidden;
        border: 1px solid #E2E8F0;
        font-size: 13.5px;
        margin-bottom: 15px;
    }
    .custom-table th {
        background: #F8FAFC;
        color: #64748B;
        font-weight: 600;
        text-align: left;
        padding: 14px 16px;
        border-bottom: 1px solid #E2E8F0;
        text-transform: capitalize;
    }
    .custom-table td {
        padding: 12px 16px;
        border-bottom: 1px solid #F1F5F9;
        color: #1E293B;
        vertical-align: middle;
    }
    .custom-table tr:last-child td {
        border-bottom: none;
    }
    .custom-table tr:hover td {
        background-color: #F8FAFC;
    }

    /* Badges */
    .badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
    }
    .badge-available { background-color: #DCFCE7; color: #15803D; }
    .badge-meeting   { background-color: #FEF3C7; color: #B45309; }
    .badge-lunch     { background-color: #DBEAFE; color: #1D4ED8; }
    .badge-notready  { background-color: #FEE2E2; color: #B91C1C; }
    .badge-admin     { background-color: #F1F5F9; color: #475569; }
    .badge-role      { background-color: #E0F2FE; color: #0284C7; border-radius: 6px; }

    /* Urgency & Status Badges */
    .badge-critical { background: #FEE2E2; color: #B91C1C; }
    .badge-high { background: #FEF3C7; color: #D97706; }
    .badge-medium { background: #FEF9C3; color: #CA8A04; }
    .badge-low { background: #DCFCE7; color: #16A34A; }

    .badge-status-prog { background: #DCFCE7; color: #15803D; }
    .badge-status-open { background: #E0F2FE; color: #0284C7; }
    .badge-status-pend { background: #FEF3C7; color: #B45309; }
    .badge-status-update { background: #F1F5F9; color: #475569; }

    /* Right Side Panel / Card */
    .panel-card {
        background: #FFFFFF;
        border-radius: 14px;
        padding: 20px;
        border: 1px solid #E2E8F0;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
        margin-bottom: 15px;
    }
    .timeline-dot {
        width: 9px;
        height: 9px;
        border-radius: 50%;
        display: inline-block;
        margin-right: 8px;
    }
    
    .agent-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 0;
        border-bottom: 1px solid #f1f5f9;
    }
    .agent-row:last-child {
        border-bottom: none;
    }
    .agent-info {
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .agent-name {
        font-size: 13.5px;
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
        border: 2px solid var(--hpe-green);
        background: rgba(1, 169, 130, 0.08);
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
    .ms-btn-wrap button {
        background-color: #ffffff !important;
        color: #1e293b !important;
        border: 1px solid #cbd5e1 !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
        font-weight: 600 !important;
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
    if not doc: return None
    data = doc.get("roster_list", {})
    if not isinstance(data, dict): data = {}
    user = {str(k): str(v) if v is not None else "" for k, v in data.items()}
    user["_id"] = doc["_id"]
    for list_field in ["aux_history", "assignment_history"]:
        raw_val = user.get(list_field, "[]")
        try: user[list_field] = json.loads(raw_val) if isinstance(raw_val, str) and raw_val else []
        except Exception: user[list_field] = []
    return user

def find_roster_user(email: str):
    doc = roster_col.find_one({"type": "roster_list", "roster_list.email": str(email).strip().lower()})
    return _deserialize_user(doc)

def find_roster_user_by_token(session_token: str):
    if not session_token: return None
    doc = roster_col.find_one({"type": "roster_list", "roster_list.session_token": str(session_token).strip()})
    return _deserialize_user(doc)

def find_all_roster_users(filter_dict=None):
    query = {"type": "roster_list"}
    if filter_dict:
        for k, v in filter_dict.items():
            if k == "_id": query["_id"] = v
            elif isinstance(v, dict): query[f"roster_list.{k}"] = v
            else: query[f"roster_list.{k}"] = str(v)
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
                try: parsed_list = json.loads(existing_str) if isinstance(existing_str, str) and existing_str else []
                except Exception: parsed_list = []
                parsed_list.append(new_item)
                set_payload[f"roster_list.{hist_key}"] = json.dumps(parsed_list)

    if set_payload:
        roster_col.update_one(
            {"type": "roster_list", "roster_list.email": str(email).strip().lower()},
            {"$set": set_payload}
        )

# Database seeding functions logic kept exactly identical (hidden from brevity in summary)
def seed_demo_cases():
    try:
        if cases_col.count_documents({}) == 0:
            sample_cases = [
                {
                    "case_number": "CASE-2026-1045", "subject": "Software License Renewal", "description": "Customer requires renewal of HPE software license for multi-year contract. Vendor to provide updated quote and entitlement confirmation.",
                    "priority": "Critical", "assigned_to": "maria.santos@hpe.com", "assigned_agent_name": "Maria Santos",
                    "due_date": "Sep 25, 2026 10:00 AM", "due_remaining": "22h 15m", "status": "In Progress", "status_reason": "Waiting for Vendor",
                    "last_update": "Sep 24, 2026 02:15 PM", "last_elapsed": "22h 15m ago", "vendor_name": "HPE Global Solutions", "vendor_email": "support@hpevendor.com", "vendor_phone": "+1 888 123 4567", "vendor_url": "www.hpevendor.com"
                },
                {
                    "case_number": "CASE-2026-1044", "subject": "Portal Access Issue", "description": "Client cannot authenticate into Partner Ready Portal.",
                    "priority": "High", "assigned_to": "john.rivera@hpe.com", "assigned_agent_name": "John Rivera",
                    "due_date": "Sep 25, 2026 02:00 PM", "due_remaining": "26h 15m", "status": "Vendor Update", "status_reason": "Awaiting Vendor Response",
                    "last_update": "Sep 24, 2026 11:30 AM", "last_elapsed": "18h 40m ago", "vendor_name": "CloudAuth HPE Partner", "vendor_email": "access@cloudauth-hpe.com", "vendor_phone": "+1 800 555 0192", "vendor_url": "www.cloudauth-hpe.com"
                },
                {
                    "case_number": "CASE-2026-1042", "subject": "License Key Request", "description": "Urgent generation of iLO Advanced License Key for new cluster.",
                    "priority": "Medium", "assigned_to": "mark.delacruz@hpe.com", "assigned_agent_name": "Mark Dela Cruz",
                    "due_date": "Sep 26, 2026 09:00 AM", "due_remaining": "45h 15m", "status": "Pending Vendor", "status_reason": "Awaiting Dispatch",
                    "last_update": "Sep 26, 2026 10:05 AM", "last_elapsed": "16h 12m ago", "vendor_name": "HPE Software Operations", "vendor_email": "licensing@hpe.com", "vendor_phone": "+1 800 555 4567", "vendor_url": "www.myhplicensing.com"
                },
            ]
            cases_col.insert_many(sample_cases)
    except Exception: pass

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
    except Exception: pass

seed_validation_data()

def get_dropdown_data():
    try:
        doc = validation_col.find_one({}, sort=[('_id', pymongo.DESCENDING)])
        if doc and "Validation_Dropdown" in doc: return doc["Validation_Dropdown"]
    except Exception: pass
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
    try: return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except Exception: return False

AUX_LIST = [
    "Available", "Admin Work", "Not Ready - Online", "Coaching", "Meeting", "Lunch", "Break", "Unscheduled Break"
]


# ==========================================
# 4. TOPBAR COMPONENT (SHARED ACROSS VIEWS)
# ==========================================
@st.dialog("Change Account Password")
def show_change_password_dialog(user):
    p1 = st.text_input("New Password", type="password", key="chg_p1")
    p2 = st.text_input("Confirm New Password", type="password", key="chg_p2")
    if st.button("Update Password", type="primary"):
        if not p1 or len(p1) < 8: st.error("Password must be at least 8 characters long.")
        elif p1 != p2: st.error("Passwords do not match.")
        else:
            update_roster_user(user["email"], update_dict={"password": hash_password(p1)})
            st.success("Password updated successfully!")
            time_pkg.sleep(1)
            st.rerun()

def render_dashboard_topbar(user, show_alert=True):
    # Alert banner if requested
    if show_alert:
        crit_cases_cnt = cases_col.count_documents({"status": {"$nin": ["Resolved", "Closed"]}, "priority": "Critical"})
        high_cases_cnt = cases_col.count_documents({"status": {"$nin": ["Resolved", "Closed"]}, "priority": "High"})
        if crit_cases_cnt > 0 or high_cases_cnt > 0:
            st.markdown(
                f"""
                <div class="alert-banner">
                    <div>⚠️ <strong>{crit_cases_cnt} Critical case nearing due date</strong> &nbsp;|&nbsp; {high_cases_cnt} Cases due soon</div>
                    <span style="cursor: pointer; font-size: 18px;">›</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

    c_search, c_notif, c_profile = st.columns([6, 0.8, 3.2])
    with c_search:
        search_query = st.text_input("Search", placeholder="🔍 Search case number, subject, assignee, or keyword...", label_visibility="collapsed", key="dash_global_search")
    with c_notif:
        unread_count = alerts_col.count_documents({"target_email": user["email"], "read": False})
        st.markdown(f"""
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; height:42px; display:flex; align-items:center; justify-content:center; position:relative; cursor:pointer;">
            <span style="font-size:1.15rem;">🔔</span>
            <span style="position:absolute; top:4px; right:8px; background:#ef4444; color:#fff; border-radius:10px; font-size:0.68rem; font-weight:700; padding:1px 5px;">{unread_count}</span>
        </div>
        """, unsafe_allow_html=True)
    
    with c_profile:
        col_avatar, col_uinfo, col_aux = st.columns([1, 2.5, 2.8])
        with col_avatar:
            if user.get("profile_pic"): st.image(user["profile_pic"], width=42)
            else: st.markdown("<div style='width:42px; height:42px; border-radius:50%; background:#e2e8f0; display:flex; align-items:center; justify-content:center; font-size:1.3rem;'>👩‍💼</div>", unsafe_allow_html=True)
        with col_uinfo:
            st.markdown(f"<div style='font-size:13.5px; font-weight:600; color:#0F172A; line-height:1.2; margin-top:2px;'>{user.get('first_name')} {user.get('last_name')}</div>", unsafe_allow_html=True)
            st.markdown(f"<div style='font-size:11.5px; color:#64748B;'>{user.get('role')}</div>", unsafe_allow_html=True)
        with col_aux:
            current_aux = user.get("current_aux", "Available")
            new_aux = st.selectbox(
                "Aux", options=AUX_LIST, index=AUX_LIST.index(current_aux) if current_aux in AUX_LIST else 0,
                key="top_bar_aux_select", label_visibility="collapsed"
            )
            if new_aux != current_aux:
                now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                update_roster_user(user["email"], update_dict={"current_aux": str(new_aux), "aux_last_updated": now_iso}, append_history={"aux_history": {"aux": str(new_aux), "timestamp": now_iso}})
                st.session_state["user"]["current_aux"] = str(new_aux)
                st.rerun()

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    return search_query.strip().lower()


# ==========================================
# 5. SIGN IN / SIGN UP (AUTH VIEW)
# ==========================================
def render_auth_view():
    if "auth_page" not in st.session_state: st.session_state["auth_page"] = "signin"
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
                    <div><div class="feature-title">Manage Cases</div><div class="feature-desc">Track and resolve tasks efficiently</div></div>
                </div>
                <div class="feature-row">
                    <div class="feature-icon-wrapper">👥</div>
                    <div><div class="feature-title">Work Together</div><div class="feature-desc">Stay aligned with your team</div></div>
                </div>
                <div class="feature-row">
                    <div class="feature-icon-wrapper">📊</div>
                    <div><div class="feature-title">Drive Results</div><div class="feature-desc">Real-time insights and reporting</div></div>
                </div>
            </div>
            <div style="font-size:0.75rem; color:#64748b; padding-top:20px;">Hewlett Packard Enterprise Development LP</div>
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
            with col_rem: remember_me = st.checkbox("Remember me", value=True, key="in_remember")
            with col_fp:
                if st.button("Forgot password?", key="btn_to_fp"):
                    st.success(f"Password reset link dispatched to {login_email}!")

            st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
            if st.button("Sign In", type="primary", use_container_width=True, key="btn_signin"):
                if not login_email or not login_pwd: st.error("Please enter both email and password.")
                else:
                    user = find_roster_user(login_email)
                    if user and verify_password(login_pwd, user.get("password", "")):
                        default_aux = "Admin Work" if user.get("role") in ["Admin", "Admin/Agent"] else "Not Ready - Online"
                        token = str(uuid.uuid4())
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        update_roster_user(login_email, update_dict={"current_aux": default_aux, "last_login": now_str, "session_token": token})
                        user["current_aux"], user["session_token"] = default_aux, token
                        st.session_state["user"] = user
                        st.query_params["session_token"] = token
                        cookie_manager.set("hpe_session_token", token, expires_at=datetime.now() + timedelta(days=30))
                        st.rerun()
                    else: st.error("Invalid HPE email address or password.")

            st.markdown("""
            <div style="display: flex; align-items: center; text-align: center; margin: 18px 0; color: #94A3B8; font-size: 0.85rem;">
                <div style="flex: 1; border-bottom: 1px solid #E2E8F0;"></div>
                <span style="padding: 0 10px;">or</span>
                <div style="flex: 1; border-bottom: 1px solid #E2E8F0;"></div>
            </div>
            <div class="ms-btn-wrap">
            """, unsafe_allow_html=True)
            if st.button("🪟 Sign in with Microsoft (HPE)", use_container_width=True, key="btn_ms_sso"):
                st.info("Directing to HPE Single Sign-On (Azure AD)...")
            st.markdown("</div><div style='height: 24px;'></div>", unsafe_allow_html=True)

            c_lbl, c_lnk = st.columns([2.2, 1.8])
            with c_lbl: st.markdown("<div style='text-align:right; font-size:0.92rem; color:#475569; padding-top:6px;'>Don't have an account?</div>", unsafe_allow_html=True)
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
                if not (su_fname and su_lname and su_empid and su_email and su_pwd): st.error("Please fill in all registration fields.")
                elif not su_email.endswith("@hpe.com"): st.warning("Please ensure you are registering with an authorized HPE corporate email address.")
                elif find_roster_user(su_email): st.error("An account with this HPE email already exists.")
                else:
                    hashed = hash_password(su_pwd)
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    user_doc = {
                        "type": "roster_list",
                        "roster_list": {
                            "first_name": str(su_fname).strip(), "last_name": str(su_lname).strip(), "emp_id": str(su_empid).strip(),
                            "email": str(su_email).strip().lower(), "password": str(hashed), "role": "Agent", "profile_pic": "",
                            "current_aux": "Not Ready - Online", "registered_date": str(now_str), "last_login": "", "session_token": "",
                            "aux_history": json.dumps([{"aux": "Not Ready - Online", "timestamp": now_str}]), "assignment_history": json.dumps([])
                        }
                    }
                    roster_col.insert_one(user_doc)
                    st.success("Account created successfully! Redirecting to Sign In...")
                    time_pkg.sleep(1.2)
                    st.session_state["auth_page"] = "signin"
                    st.rerun()


# ==========================================
# 6. DASHBOARD TAB
# ==========================================
def render_dashboard(user):
    search_q = render_dashboard_topbar(user, show_alert=True)
    user_role = user.get("role", "Agent")
    
    st.markdown("""
        <h2 style="margin: 0; font-size: 26px; font-weight: 700; color: #0F172A;">Dashboard</h2>
        <p style="margin: 0; font-size: 13px; color: #64748B;">Overview of active cases and team status</p>
    """, unsafe_allow_html=True)
    st.write("")

    all_raw_cases = list(cases_col.find({"status": {"$nin": ["Resolved", "Closed"]}}))
    display_cases = [c for c in all_raw_cases if c.get('assigned_to') == user['email']] if user_role == "Agent" else all_raw_cases

    total_active = len(display_cases)
    crit_count = sum(1 for c in display_cases if c.get("priority") == "Critical")
    due_soon_count = sum(1 for c in display_cases if c.get("priority") in ["High", "Critical"])
    on_track_count = max(0, total_active - crit_count - due_soon_count + 1)

    m1, m2, m3, m4 = st.columns(4)
    metrics = [
        ("📁", "#EFF6FF", "#2563EB", str(total_active), "Active Cases", "+5% from last week"),
        ("⏱️", "#FEE2E2", "#DC2626", str(crit_count), "Critical", "Requires immediate attention"),
        ("📅", "#FEF3C7", "#D97706", str(due_soon_count), "Due Soon", "Due within 24-48 hours"),
        ("✅", "#DCFCE7", "#16A34A", str(on_track_count), "On Track", "On schedule")
    ]
    for col, (icon, bg, fg, val, title, sub) in zip([m1, m2, m3, m4], metrics):
        with col:
            st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-icon" style="background-color: {bg}; color: {fg};">{icon}</div>
                    <div>
                        <div class="metric-val">{val}</div>
                        <div class="metric-label">{title}</div>
                        <div class="metric-sub">{sub}</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
    
    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

    body_left, body_right = st.columns([7, 3]) if user_role in ["Admin", "Admin/Agent"] else (st.container(), None)
    
    with body_left:
        st.markdown("<h3 style='font-size: 1.25rem; font-weight: 700; color: #0f172a; margin-bottom: 12px;'>Active Cases</h3>", unsafe_allow_html=True)
        
        # Display filtering logic
        filtered_cases = []
        for c in display_cases:
            combined = f"{c.get('case_number','')} {c.get('subject','')} {c.get('assigned_agent_name','')} {c.get('vendor_name','')}".lower()
            if search_q and search_q not in combined: continue
            filtered_cases.append(c)
        filtered_cases.sort(key=lambda x: {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}.get(x.get("priority", "Low"), 0), reverse=True)

        if not filtered_cases:
            st.info("No active cases matching criteria.")
        else:
            table_html = """
            <table class="custom-table">
                <thead><tr>
                    <th>Case #</th><th>Subject</th><th>Priority</th>
            """
            if user_role != "Agent": table_html += "<th>Assigned To</th>"
            table_html += "<th>Due Date</th><th>Status</th><th>Last Update</th></tr></thead><tbody>"

            for c in filtered_cases:
                prio, st_val = c.get("priority", "Low"), c.get("status", "Open")
                p_cls = "badge-low" if prio=="Low" else "badge-medium" if prio=="Medium" else "badge-high" if prio=="High" else "badge-critical"
                s_cls = "badge-status-prog" if st_val=="In Progress" else "badge-status-update" if st_val=="Vendor Update" else "badge-status-pend" if "Pending" in st_val else "badge-status-open"
                due_color = "#e11d48" if prio in ["Critical", "High"] else "#1e293b"

                table_html += f"<tr><td><strong>{c.get('case_number')}</strong></td><td>{c.get('subject')}</td><td><span class='badge {p_cls}'>● {prio}</span></td>"
                if user_role != "Agent": table_html += f"<td>{c.get('assigned_agent_name', 'Unassigned')}</td>"
                table_html += f"<td><span style='color:{due_color}; font-weight:600;'>{c.get('due_date')}</span><br/><span style='color:#ef4444; font-size:11px;'>• {c.get('due_remaining', '')}</span></td>"
                table_html += f"<td><span class='badge {s_cls}'>{st_val}</span></td>"
                table_html += f"<td>{c.get('last_update')}<br/><span style='color:#ea580c; font-size:11px;'>• {c.get('last_elapsed', '')}</span></td></tr>"
            
            table_html += "</tbody></table>"
            st.markdown(table_html, unsafe_allow_html=True)
            
            with st.expander("🛠 Manage Selected Case"):
                case_map = {f"#{c.get('case_number')} — {c.get('subject')}": str(c["_id"]) for c in filtered_cases}
                sel_label = st.selectbox("Select Case:", list(case_map.keys()), key="sel_active_case")
                if st.button("Open Case Options"):
                    st.info(f"Opening details for {sel_label} (Action modal omitted for brevity in main view)")

    if body_right:
        with body_right:
            st.markdown("""
            <div class="panel-card">
                <h4 style="margin:0 0 15px 0; font-weight:700; font-size:16px; color:#0f172a;">Agents Online</h4>
            """, unsafe_allow_html=True)
            
            active_agents = find_all_roster_users({"role": {"$in": ["Agent", "Admin/Agent"]}})
            for ag in active_agents:
                aux_val = ag.get("current_aux", "Available")
                b_cls = "badge-available" if aux_val == "Available" else "badge-lunch" if "Break" in aux_val or "Lunch" in aux_val else "badge-meeting" if "Meeting" in aux_val else "badge-notready"
                
                st.markdown(f"""
                <div class="agent-row">
                    <div class="agent-info">
                        <span style="font-size:1.15rem; background:#E2E8F0; border-radius:50%; width:32px; height:32px; display:flex; align-items:center; justify-content:center;">👤</span>
                        <div class="agent-name">{ag.get('first_name')} {ag.get('last_name')}</div>
                    </div>
                    <span class="badge {b_cls}">● {aux_val}</span>
                </div>
                """, unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)


# ==========================================
# 7. MONITORING TAB (ADMIN/AGENT)
# ==========================================
def render_monitoring(user):
    search_q = render_dashboard_topbar(user, show_alert=False)
    
    st.markdown("""
        <h2 style="margin: 0; font-size: 26px; font-weight: 700; color: #0F172A;">Monitoring</h2>
        <p style="margin: 0; font-size: 13px; color: #64748B;">Real-time view of all logged in agents and their current status</p>
    """, unsafe_allow_html=True)
    st.write("")

    agents = find_all_roster_users({"role": {"$in": ["Agent", "Admin/Agent"]}})
    
    total_logged_in = len(agents)
    available_cnt = sum(1 for a in agents if a.get("current_aux") == "Available")
    meeting_cnt = sum(1 for a in agents if a.get("current_aux") == "Meeting")
    notready_cnt = sum(1 for a in agents if a.get("current_aux") == "Not Ready - Online")
    break_cnt = sum(1 for a in agents if a.get("current_aux") in ["Break", "Lunch"])
    admin_cnt = sum(1 for a in agents if a.get("current_aux") == "Admin Work")

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    metrics = [
        ("👥", "#EFF6FF", "#2563EB", str(total_logged_in), "Total Logged In", "Agents & Admins"),
        ("●", "#DCFCE7", "#16A34A", str(available_cnt), "Available", f"{int((available_cnt/total_logged_in)*100) if total_logged_in else 0}%"),
        ("●", "#FEF3C7", "#D97706", str(meeting_cnt), "In Meeting", f"{int((meeting_cnt/total_logged_in)*100) if total_logged_in else 0}%"),
        ("●", "#FEE2E2", "#DC2626", str(notready_cnt), "Not Ready", f"{int((notready_cnt/total_logged_in)*100) if total_logged_in else 0}%"),
        ("●", "#DBEAFE", "#2563EB", str(break_cnt), "On Break/Lunch", f"{int((break_cnt/total_logged_in)*100) if total_logged_in else 0}%"),
        ("●", "#F1F5F9", "#64748B", str(admin_cnt), "Admin Work", f"{int((admin_cnt/total_logged_in)*100) if total_logged_in else 0}%"),
    ]
    
    for col, (icon, bg, fg, val, title, sub) in zip([m1, m2, m3, m4, m5, m6], metrics):
        with col:
            st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-icon" style="background-color: {bg}; color: {fg};">{icon}</div>
                    <div><div class="metric-val">{val}</div><div class="metric-label">{title}</div><div class="metric-sub">{sub}</div></div>
                </div>
            """, unsafe_allow_html=True)

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

    body_left, body_right = st.columns([7, 3])

    # Left Side: Custom Table
    with body_left:
        table_html = """
        <table class="custom-table">
            <thead>
                <tr>
                    <th>Name</th><th>Emp ID</th><th>Role</th><th>Current Status</th>
                    <th>Active Cases</th><th>Actions</th>
                </tr>
            </thead>
            <tbody>
        """
        for ag in agents:
            aux_val = ag.get("current_aux", "Available")
            b_cls = "badge-available" if aux_val == "Available" else "badge-lunch" if "Break" in aux_val or "Lunch" in aux_val else "badge-meeting" if "Meeting" in aux_val else "badge-notready" if "Not Ready" in aux_val else "badge-admin"
            
            table_html += f"""
                <tr>
                    <td><strong>{ag.get('first_name')} {ag.get('last_name')}</strong><br><span style="color:#94A3B8; font-size:12px;">{ag.get('email')}</span></td>
                    <td>{ag.get('emp_id')}</td>
                    <td><span class="badge badge-role">{ag.get('role')}</span></td>
                    <td><span class="badge {b_cls}">● {aux_val}</span></td>
                    <td>{cases_col.count_documents({"assigned_to": ag.get('email'), "status": {"$nin": ["Resolved", "Closed"]}})}</td>
                    <td>💬 🕒 ⋯</td>
                </tr>
            """
        table_html += "</tbody></table>"
        st.markdown(table_html, unsafe_allow_html=True)
        
        # Interactive selection
        st.write("Select an agent below to view details and perform actions in the side panel:")
        agent_emails = [a["email"] for a in agents]
        selected_agent_email = st.selectbox("Select Agent", agent_emails, label_visibility="collapsed")

    # Right Side: Panel Card
    with body_right:
        if selected_agent_email:
            sel_ag = find_roster_user(selected_agent_email)
            a_val = sel_ag.get("current_aux", "Available")
            a_cls = "badge-available" if a_val == "Available" else "badge-lunch" if "Break" in a_val or "Lunch" in a_val else "badge-meeting" if "Meeting" in a_val else "badge-notready"
            
            st.markdown(f"""
            <div class="panel-card">
                <div style="display: flex; gap: 14px; align-items: center; margin-bottom: 14px;">
                    <div style="width: 48px; height: 48px; border-radius: 50%; background: #E2E8F0; display:flex; align-items:center; justify-content:center; font-weight:700;">
                        {sel_ag.get('first_name')[0]}{sel_ag.get('last_name')[0]}
                    </div>
                    <div>
                        <h3 style="margin: 0; font-size: 16px; color:#0F172A;">{sel_ag.get('first_name')} {sel_ag.get('last_name')}</h3>
                        <div class="badge {a_cls}" style="padding: 2px 8px; font-size:11px;">● {a_val}</div>
                        <div style="font-size: 12px; color: #64748B; margin-top:2px;">{sel_ag.get('emp_id')} &nbsp;|&nbsp; <span class="badge badge-role" style="padding:1px 6px;">{sel_ag.get('role')}</span></div>
                    </div>
                </div>

                <div style="display:flex; border-bottom:1px solid #E2E8F0; gap:20px; font-size:13px; font-weight:600; margin-bottom: 14px;">
                    <div style="border-bottom: 2px solid #0284C7; color:#0284C7; padding-bottom:6px;">Aux History</div>
                </div>
            """, unsafe_allow_html=True)
            
            hist = sel_ag.get("aux_history", [])[-5:]
            for h in reversed(hist):
                dot_c = "#16A34A" if h['aux'] == "Available" else "#DC2626" if "Not Ready" in h['aux'] else "#D97706"
                time_str = datetime.strptime(h['timestamp'], "%Y-%m-%d %H:%M:%S").strftime("%I:%M %p")
                st.markdown(f"<div><span class='timeline-dot' style='background:{dot_c};'></span><strong>{time_str}</strong> — {h['aux']}</div>", unsafe_allow_html=True)

            act_cases = list(cases_col.find({"assigned_to": sel_ag.get('email'), "status": {"$nin": ["Resolved", "Closed"]}}))
            st.markdown(f"""
                <div style="font-weight: 700; font-size: 13.5px; margin: 18px 0 8px 0; display:flex; justify-content:space-between;">
                    <span>Active Case Assignments</span><span class="badge badge-role">{len(act_cases)}</span>
                </div>
            """, unsafe_allow_html=True)
            
            for c in act_cases:
                st.markdown(f"""
                <div style="background:#F8FAFC; padding:8px 10px; border-radius:6px; font-size:12px; margin-bottom:6px; display:flex; justify-content:space-between; align-items:center; border: 1px solid #E2E8F0;">
                    <span>{c.get('case_number')}</span>
                    <span class="badge {'badge-critical' if c.get('priority')=='Critical' else 'badge-high'}" style="font-size:10px;">{c.get('priority')}</span>
                </div>
                """, unsafe_allow_html=True)
                
            st.markdown("</div>", unsafe_allow_html=True)

            btn_c1, btn_c2 = st.columns(2)
            with btn_c1: st.button("💬 Message", key="act_msg", use_container_width=True)
            with btn_c2:
                if st.button("🚪 Kick User", key="act_kick", use_container_width=True):
                    update_roster_user(sel_ag['email'], update_dict={"session_token": "", "current_aux": "Not Ready - Online"})
                    st.toast(f"Kicked {sel_ag.get('first_name')}!")
                    st.rerun()


# ==========================================
# 8. SCHEDULE, REPORT, SETTINGS (Stubs visually mapped)
# ==========================================
def render_schedule(user):
    render_dashboard_topbar(user, show_alert=False)
    st.markdown("<h2 style='font-size: 26px; font-weight: 700;'>Schedule</h2>", unsafe_allow_html=True)
    st.info("Schedule management logic loads here.")

def render_report(user):
    render_dashboard_topbar(user, show_alert=False)
    st.markdown("<h2 style='font-size: 26px; font-weight: 700;'>Reporting</h2>", unsafe_allow_html=True)
    st.info("Analytics and SLA reporting loads here.")

def render_settings(user):
    render_dashboard_topbar(user, show_alert=False)
    st.markdown("<h2 style='font-size: 26px; font-weight: 700;'>Settings</h2>", unsafe_allow_html=True)
    st.info("System administration settings load here.")


# ==========================================
# 9. MAIN RUNNER & SIDEBAR ROUTING 
# ==========================================
def main():
    if st.session_state.get("logout_requested"):
        st.session_state["logout_requested"] = False
        user_to_logout = st.session_state.get("user")
        if user_to_logout:
            update_roster_user(user_to_logout["email"], update_dict={"session_token": "", "current_aux": "Not Ready - Online"})
        cookie_manager.delete("hpe_session_token")
        if "session_token" in st.query_params: del st.query_params["session_token"]
        if "user" in st.session_state: del st.session_state["user"]
        st.rerun()

    if "user" not in st.session_state or not st.session_state["user"]:
        active_token = st.query_params.get("session_token") or cookie_manager.get("hpe_session_token")
        if active_token:
            existing_user = find_roster_user_by_token(active_token)
            if existing_user:
                st.session_state["user"] = existing_user
                st.query_params["session_token"] = active_token

    if "user" not in st.session_state or not st.session_state["user"]:
        render_auth_view()
        return

    user = st.session_state["user"]
    if "active_page" not in st.session_state: st.session_state["active_page"] = "Dashboard"

    with st.sidebar:
        st.markdown("""
        <div style="padding: 12px 0 24px 0;">
            <div style="font-size: 20px; font-weight: 700; color: #FFFFFF; letter-spacing: -0.5px;">
                <span style="color: #01A982;">HPE</span> CaseFlow
            </div>
            <div style="font-size: 11px; color: #64748B;">Team Task Management</div>
        </div>
        """, unsafe_allow_html=True)

        nav_tabs = [
            ("⊞ Dashboard", "Dashboard"),
            ("▦ Monitoring", "Monitoring"),
            ("📅 Schedule", "Schedule"),
            ("📈 Report", "Report"),
            ("⚙️ Setting", "Setting")
        ] if user["role"] in ["Admin", "Admin/Agent"] else [
            ("⊞ Dashboard", "Dashboard"), ("📅 Schedule", "Schedule"), ("📈 Report", "Report")
        ]

        for label, page_key in nav_tabs:
            if st.button(label, key=f"nav_tile_{page_key}", type="primary" if st.session_state["active_page"] == page_key else "secondary", use_container_width=True):
                st.session_state["active_page"] = page_key
                st.rerun()

        st.markdown("""
        <div style="margin-top: 260px; padding-top: 20px; border-top: 1px solid rgba(255,255,255,0.08);">
            <div style="font-weight: 700; color: #01A982; font-size: 14px;">Hewlett Packard</div>
            <div style="color: #E2E8F0; font-size: 12px;">Enterprise</div>
        </div>
        """, unsafe_allow_html=True)

        if st.button("🚪 Sign Out", key="btn_sidebar_signout", use_container_width=True):
            st.session_state["logout_requested"] = True
            st.rerun()

    current_page = st.session_state.get("active_page", "Dashboard")
    if current_page == "Dashboard": render_dashboard(user)
    elif current_page == "Monitoring": render_monitoring(user)
    elif current_page == "Schedule": render_schedule(user)
    elif current_page == "Report": render_report(user)
    elif current_page == "Setting": render_settings(user)

if __name__ == "__main__":
    main()
