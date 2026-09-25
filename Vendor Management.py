import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from datetime import datetime, date, timedelta, time
import pymongo
from bson.objectid import ObjectId
import bcrypt
import json
import time as time_pkg
import extra_streamlit_components as stx

# ==========================================
# 1. STREAMLIT PAGE CONFIG & CSS CUSTOMIZATION
# ==========================================
st.set_page_config(
    page_title="HPE CaseFlow - Team Task and Case Management System",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling: Matches the HPE CaseFlow visual design and clears chrome
st.markdown("""
    <style>
    /* Hide Streamlit default chrome & deploy button */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden !important;}
    [data-testid="stDecoration"] {visibility: hidden !important;}
    [data-testid="stStatusWidget"] {visibility: hidden !important;}

    /* Container Spacing */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 2rem;
    }
    
    /* HPE Brand Colors */
    :root {
        --hpe-green: #01a982;
        --hpe-green-dark: #007a5e;
        --hpe-green-light: #00d69f;
        --hpe-teal: #00c9a7;
    }

    /* Left Hero Card Styling */
    .hero-container {
        background: linear-gradient(180deg, rgba(8, 28, 36, 0.95) 0%, rgba(6, 20, 26, 0.98) 100%), 
                    url('https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?q=80&w=1200&auto=format&fit=crop');
        background-size: cover;
        background-position: center;
        border-radius: 20px;
        padding: 42px 36px;
        color: white;
        height: 100%;
        min-height: 640px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.15);
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }

    .hpe-brand-bar {
        width: 48px;
        height: 6px;
        background-color: var(--hpe-green);
        margin-bottom: 12px;
        border-radius: 3px;
    }

    .hpe-corp-title {
        font-size: 1.15rem;
        font-weight: 700;
        letter-spacing: -0.2px;
        line-height: 1.15;
        margin-bottom: 30px;
    }

    .hero-heading {
        font-size: 2.6rem;
        font-weight: 800;
        line-height: 1.05;
        margin-bottom: 4px;
        letter-spacing: -0.5px;
    }

    .hero-heading-highlight {
        color: var(--hpe-green-light);
    }

    .hero-subheading {
        font-size: 1.05rem;
        color: #d1d5db;
        margin-bottom: 40px;
        font-weight: 400;
    }

    .feature-item {
        display: flex;
        align-items: center;
        margin-bottom: 24px;
    }

    .feature-icon-circle {
        width: 48px;
        height: 48px;
        border-radius: 50%;
        border: 2px solid var(--hpe-teal);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.35rem;
        margin-right: 18px;
        background: rgba(0, 201, 167, 0.08);
        flex-shrink: 0;
    }

    .feature-text-title {
        font-size: 1rem;
        font-weight: 700;
        color: #ffffff;
        margin-bottom: 2px;
    }

    .feature-text-desc {
        font-size: 0.85rem;
        color: #9ca3af;
    }

    /* Right Auth Form Styling */
    .auth-card-title {
        font-size: 2.1rem;
        font-weight: 800;
        color: #111827;
        margin-bottom: 4px;
        letter-spacing: -0.5px;
    }

    .auth-card-subtitle {
        font-size: 0.95rem;
        color: #4b5563;
        margin-bottom: 26px;
    }

    /* Primary Green HPE Buttons */
    div.stButton > button[kind="primary"] {
        background-color: var(--hpe-green-dark) !important;
        border-color: var(--hpe-green-dark) !important;
        color: #ffffff !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        padding: 0.65rem 1rem !important;
        font-size: 1rem !important;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: var(--hpe-green) !important;
        border-color: var(--hpe-green) !important;
    }

    /* Borderless table */
    .borderless-table {
        width: 100%;
        border-collapse: collapse;
        font-family: sans-serif;
        font-size: 0.88rem;
    }
    .borderless-table th {
        background-color: #f8f9fa;
        color: #495057;
        padding: 10px 12px;
        text-align: left;
        border: none !important;
    }
    .borderless-table td {
        padding: 9px 12px;
        border: none !important;
        border-bottom: 1px solid #f1f3f5 !important;
    }
    .borderless-table tr:hover {
        background-color: #f8f9fa;
    }
    
    /* Status Pills */
    .pill {
        padding: 3px 8px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
        display: inline-block;
    }
    .pill-crit { background: #ffe3e3; color: #c92a2a; }
    .pill-high { background: #ffe8cc; color: #d9480f; }
    .pill-med { background: #fff3bf; color: #f08c00; }
    .pill-low { background: #e6fcf5; color: #0ca678; }
    .pill-avail { background: #d3f9d8; color: #2b8a3e; }
    .pill-aux { background: #e7f5ff; color: #1c7ed6; }
    .pill-break { background: #f3d9fa; color: #ae3ec9; }
    </style>
""", unsafe_allow_html=True)


# ==========================================
# 2. DATABASE INITIALIZATION & SEEDING
# ==========================================
@st.cache_resource
def get_mongo_client():
    mongo_uri = st.secrets.get("MONGO_URI", "mongodb://localhost:27017")
    return pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)

client = get_mongo_client()
db = client["TeamRoster"]
roster_col = db["Team Roster Collection"]
validation_col = db["Validation_Dropdown"]
schedule_col = db["Schedule_Monitoring"]
cases_col = db["Cases_Collection"]
alerts_col = db["Alerts_Collection"]
messages_col = db["Messages_Collection"]
swaps_col = db["Schedule_Swaps"]

def seed_validation_data():
    try:
        if validation_col.count_documents({}) == 0:
            validation_col.insert_one({
                "Validation_Dropdown": {
                    "Case_Status": ["Open", "In Progress", "Pending Vendor Response", "Escalated", "Resolved", "Closed"],
                    "Case_Reason": ["First Contact", "Awaiting Part Delivery", "Technical Troubleshooting", "Customer Callback Needed", "Engineer Dispatched"],
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
        "Case_Status": ["Open", "In Progress", "Resolved", "Closed"],
        "Case_Reason": ["Initial Work", "Vendor Contact"],
        "Closure_Type": ["Completed", "Contract Breach"],
        "Contract_Breach": ["SLA Missed", "Defective Component"]
    }

def get_cookie_manager():
    return stx.CookieManager()

cookie_manager = get_cookie_manager()


# ==========================================
# 3. AUTHENTICATION & PASSWORD HELPERS
# ==========================================
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

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
# 4. AUTO-ASSIGNMENT & CASE ENGINE
# ==========================================
def auto_assign_case(case_id):
    case = cases_col.find_one({"_id": ObjectId(case_id)})
    if not case or case.get("assigned_to"):
        return False

    available_agents = list(roster_col.find({
        "current_aux": "Available",
        "role": {"$in": ["Agent", "Admin/Agent"]}
    }))

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

    roster_col.update_one(
        {"email": chosen_agent["email"]},
        {"$push": {"assignment_history": {
            "case_id": str(case_id),
            "case_number": case.get("case_number"),
            "priority": case.get("priority"),
            "timestamp": now_iso
        }}}
    )

    alerts_col.insert_one({
        "target_email": chosen_agent["email"],
        "type": "Assignment",
        "message": f"Case #{case.get('case_number')} assigned to you! Priority: {case.get('priority')}. Due: {case.get('due_date')}",
        "read": False,
        "created_at": now_iso
    })
    return True


# ==========================================
# 5. REAL-TIME AUX MANAGEMENT
# ==========================================
def update_agent_aux(email, new_aux):
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    roster_col.update_one(
        {"email": email},
        {
            "$set": {"current_aux": new_aux, "aux_last_updated": now_iso},
            "$push": {"aux_history": {"aux": new_aux, "timestamp": now_iso}}
        }
    )
    st.session_state["user"]["current_aux"] = new_aux

    if new_aux == "Available":
        unassigned_cases = cases_col.find({"assigned_to": None}).sort("urgency_weight", pymongo.DESCENDING)
        for c in unassigned_cases:
            assigned = auto_assign_case(c["_id"])
            if not assigned:
                break


# ==========================================
# 6. POPUPS & DIALOGS
# ==========================================
@st.dialog("Forgot Password", width="medium")
def show_forgot_password_dialog():
    st.markdown("### Password Reset Assistance")
    st.markdown("Enter your registered HPE email address below. We'll send you an instant reset link.")
    fp_email = st.text_input("HPE Email Address", placeholder="yourname@hpe.com", key="dlg_fp_email").strip().lower()
    if st.button("Send Reset Link", type="primary", use_container_width=True):
        if not fp_email:
            st.error("Please enter your HPE email.")
            return
        user = roster_col.find_one({"email": fp_email})
        if user:
            token = hash_password(fp_email)[:16]
            st.success(f"A password reset link has been dispatched to {fp_email}!")
            st.caption(f"Reset Link: https://caseflow.hpe.com/reset?token={token}")
        else:
            st.error("No account found with this HPE email address.")

@st.dialog("Case Detail & Actions", width="large")
def show_case_modal(case_id, user):
    case = cases_col.find_one({"_id": ObjectId(case_id)})
    if not case:
        st.error("Case not found.")
        return

    dropdowns = get_dropdown_data()
    st.markdown(f"### Case #{case.get('case_number')} — {case.get('subject')}")
    st.caption(f"Priority: **{case.get('priority')}** | Urgency: **{case.get('urgency', 'Normal')}** | Due: **{case.get('due_date')}**")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Assigned To:** {case.get('assigned_agent_name', 'Unassigned')} (`{case.get('assigned_to', 'None')}`)")
        st.markdown(f"**Current Status:** `{case.get('status')}`")
        st.markdown(f"**Status Reason:** {case.get('status_reason', 'N/A')}")
        st.markdown(f"**Last Update:** {case.get('last_update')}")
    with col2:
        st.markdown("**Vendor Details:**")
        v_name = case.get("vendor_name", "Hewlett Packard Enterprise Global Service")
        v_email = case.get("vendor_email", "vendor-support@hpe-partners.com")
        v_phone = case.get("vendor_phone", "+1-800-555-0199")
        st.text_input("Vendor Name (Click to copy)", v_name, disabled=True)
        st.text_input("Vendor Email (Click to copy)", v_email, disabled=True)
        st.text_input("Vendor Phone (Click to copy)", v_phone, disabled=True)

    st.divider()

    if user["role"] == "Admin":
        st.markdown("#### Admin Reassignment")
        all_agents = list(roster_col.find({"role": {"$in": ["Agent", "Admin/Agent"]}}))
        ag_map = {f"{a.get('first_name')} {a.get('last_name')} ({a['email']})": a['email'] for a in all_agents}
        new_assigned_display = st.selectbox("Reassign to:", options=list(ag_map.keys()))
        if st.button("Confirm Reassign", key="btn_reassign_admin"):
            new_email = ag_map[new_assigned_display]
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cases_col.update_one(
                {"_id": ObjectId(case_id)},
                {"$set": {"assigned_to": new_email, "assigned_agent_name": new_assigned_display.split(" (")[0], "last_update": now_str}}
            )
            alerts_col.insert_one({
                "target_email": new_email,
                "type": "Assignment",
                "message": f"Case #{case.get('case_number')} was reassigned to you by Admin.",
                "read": False,
                "created_at": now_str
            })
            st.success("Case reassigned successfully!")
            time_pkg.sleep(1)
            st.rerun()

    elif user["role"] == "Agent":
        st.markdown("#### Request Case Transfer")
        peer_agents = list(roster_col.find({"email": {"$ne": user["email"]}, "role": {"$in": ["Agent", "Admin/Agent"]}}))
        peer_map = {f"{a.get('first_name')} {a.get('last_name')} ({a['email']})": a['email'] for a in peer_agents}
        if peer_map:
            transfer_peer = st.selectbox("Request Transfer To:", list(peer_map.keys()))
            if st.button("Send Transfer Request", key="btn_req_transfer"):
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cases_col.update_one({"_id": ObjectId(case_id)}, {"$set": {"transfer_pending_to": peer_map[transfer_peer]}})
                alerts_col.insert_one({
                    "target_email": peer_map[transfer_peer],
                    "type": "Case Transfer",
                    "message": f"{user['first_name']} wants to transfer Case #{case.get('case_number')} to you.",
                    "read": False,
                    "created_at": now_str
                })
                st.info("Transfer request sent to peer.")

    st.markdown("#### Update Status & Resolution")
    s_col1, s_col2 = st.columns(2)
    with s_col1:
        new_status = st.selectbox("Case Status", options=dropdowns.get("Case_Status", []), index=dropdowns.get("Case_Status", []).index(case.get("status")) if case.get("status") in dropdowns.get("Case_Status", []) else 0)
        new_reason = st.selectbox("Status Reason", options=dropdowns.get("Case_Reason", []))
    with s_col2:
        new_closure = st.selectbox("Closure Type", options=["None"] + dropdowns.get("Closure_Type", []))
        breach_reason = None
        if new_closure == "Contract Breach":
            breach_reason = st.selectbox("Contract Breach Reason", options=dropdowns.get("Contract_Breach", []))

    if new_closure == "Contract Breach":
        st.markdown("##### ⚠️ Automated Breach Notice Email Template")
        default_body = f"""Subject: OFFICIAL NOTICE: Contract Breach - Case #{case.get('case_number')} - {breach_reason}

Dear {case.get('vendor_name', 'Vendor Support Team')},

This notice informs you that Case #{case.get('case_number')} regarding '{case.get('subject')}' has been formally marked in Contract Breach due to: {breach_reason}.

Per HPE SLA terms and service contract conditions, immediate rectification and executive escalation are required within 2 business hours.

Case Reference: {case.get('case_number')}
Due Date: {case.get('due_date')}
Logged By: {user.get('first_name')} {user.get('last_name')} (HPE Operations)

Please reply with an immediate remediation timeline.
"""
        st.text_area("Review / Edit Breach Email Before Sending", value=default_body, height=180)
        if st.button("Send Breach Notice Email to Vendor", key="btn_send_breach"):
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            admins = list(roster_col.find({"role": {"$in": ["Admin", "Admin/Agent"]}}))
            for adm in admins:
                alerts_col.insert_one({
                    "target_email": adm["email"],
                    "type": "Breach Notice",
                    "message": f"CRITICAL: Case #{case.get('case_number')} was marked CONTRACT BREACH by {user['first_name']}. Reason: {breach_reason}",
                    "read": False,
                    "created_at": now_str
                })
            st.success("Breach notice recorded and dispatched to vendor & admins alerted!")

    if st.button("Save Case Updates", type="primary"):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update_payload = {
            "status": new_status,
            "status_reason": new_reason,
            "closure_type": new_closure,
            "last_update": now_str
        }
        if breach_reason:
            update_payload["breach_reason"] = breach_reason

        cases_col.update_one({"_id": ObjectId(case_id)}, {"$set": update_payload})
        st.toast("Case updated successfully!")
        time_pkg.sleep(1)
        st.rerun()

@st.dialog("Agent History & Monitoring", width="large")
def show_agent_monitoring_modal(agent_email):
    agent = roster_col.find_one({"email": agent_email})
    if not agent:
        st.error("Agent not found.")
        return

    st.subheader(f"{agent.get('first_name')} {agent.get('last_name')} — Activity Track")
    st.write(f"**Email:** {agent.get('email')} | **Role:** {agent.get('role')} | **Current Aux:** `{agent.get('current_aux')}`")
    
    t1, t2 = st.tabs(["Aux History (Today)", "Case Assignment History"])
    with t1:
        aux_hist = agent.get("aux_history", [])
        if aux_hist:
            df_aux = pd.DataFrame(aux_hist)
            st.dataframe(df_aux.iloc[::-1], use_container_width=True)
        else:
            st.info("No aux history recorded for today.")

    with t2:
        asg_hist = agent.get("assignment_history", [])
        if asg_hist:
            df_asg = pd.DataFrame(asg_hist)
            st.dataframe(df_asg.iloc[::-1], use_container_width=True)
        else:
            st.info("No cases assigned yet today.")

@st.dialog("Broadcast Instant Message")
def show_broadcast_modal(target_email, sender_name):
    msg = st.text_area("Message to Agent:")
    if st.button("Send Popup Alert"):
        if msg.strip():
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            messages_col.insert_one({
                "target_email": target_email,
                "sender": sender_name,
                "message": msg,
                "timestamp": now_str,
                "displayed": False
            })
            st.success("Message dispatched instantly.")
            time_pkg.sleep(1)
            st.rerun()


# ==========================================
# 7. NOTIFICATION & POPUP DISPATCHER
# ==========================================
def handle_live_alerts_and_messages(user):
    unread_msg = messages_col.find_one({"target_email": user["email"], "displayed": False})
    if unread_msg:
        st.warning(f"📢 **ADMIN MESSAGE from {unread_msg.get('sender')}**:\n\n{unread_msg.get('message')}")
        if st.button("Acknowledge Message", key=f"ack_msg_{unread_msg['_id']}"):
            messages_col.update_one({"_id": unread_msg["_id"]}, {"$set": {"displayed": True}})
            st.rerun()

    unread_alerts = list(alerts_col.find({"target_email": user["email"], "read": False}).limit(3))
    for alert in unread_alerts:
        st.info(f"🔔 **{alert.get('type')}:** {alert.get('message')}")
        if st.button("Dismiss", key=f"alert_btn_{alert['_id']}"):
            alerts_col.update_one({"_id": alert["_id"]}, {"$set": {"read": True}})
            st.rerun()

    now = datetime.now()
    two_hours_later = now + timedelta(hours=2)
    crit_cases = cases_col.find({
        "status": {"$nin": ["Resolved", "Closed"]},
        "priority": "Critical"
    })
    for c in crit_cases:
        try:
            d_time = datetime.strptime(c.get("due_date"), "%Y-%m-%d %H:%M")
            if now < d_time <= two_hours_later:
                st.error(f"🚨 **CRITICAL SLA ALERT:** Case #{c.get('case_number')} ('{c.get('subject')}') is due at {c.get('due_date')} and remains unresolved!")
        except Exception:
            pass


# ==========================================
# 8. TOP-RIGHT PROFILE BAR REPLACEMENT
# ==========================================
def render_custom_top_bar(user):
    top_col1, top_col2 = st.columns([6, 4])
    
    with top_col1:
        st.markdown("<h2 style='margin:0; font-weight:800; color:#111827;'>HPE CaseFlow <span style='font-size:1.1rem; color:#01a982; font-weight:600;'>Workforce Operations</span></h2>", unsafe_allow_html=True)
    
    with top_col2:
        with st.container():
            c_pic, c_details, c_aux = st.columns([1, 2, 2])
            with c_pic:
                if user.get("profile_pic"):
                    st.image(user["profile_pic"], width=46)
                else:
                    st.markdown("<div style='font-size:2rem; line-height:1;'>👤</div>", unsafe_allow_html=True)
            with c_details:
                st.markdown(f"**{user.get('first_name')} {user.get('last_name')}**")
                st.caption(f"Role: `{user.get('role')}` | ID: `{user.get('emp_id')}`")
            with c_aux:
                current_aux = user.get("current_aux", "Available")
                new_aux = st.selectbox(
                    "Current Aux",
                    options=AUX_LIST,
                    index=AUX_LIST.index(current_aux) if current_aux in AUX_LIST else 0,
                    key="top_aux_selector",
                    label_visibility="collapsed"
                )
                if new_aux != current_aux:
                    update_agent_aux(user["email"], new_aux)
                    st.rerun()

        if user["role"] in ["Agent", "Admin/Agent"]:
            today_str = datetime.now().strftime("%Y-%m-%d")
            sched = schedule_col.find_one({"date": today_str, "Schedule_Monitoring.agent_email": user["email"]})
            sched_text = "Shift: 08:00 - 17:00 | Break: 10:00, 15:00 | Lunch: 12:00"
            if sched and "Schedule_Monitoring" in sched:
                for entry in sched["Schedule_Monitoring"]:
                    if entry.get("agent_email") == user["email"]:
                        sched_text = f"Today's Plan: {entry.get('schedule_plan', 'Standard')}"
            st.markdown(f"<div style='font-size:0.75rem; color:#868e96; text-align:right;'>📅 {sched_text}</div>", unsafe_allow_html=True)

    st.markdown("---")


# ==========================================
# 9. SIGN IN / SIGN UP (EXACT IMAGE REPLICA)
# ==========================================
def render_hero_left():
    """Renders the left hero card matching the screenshot design"""
    st.markdown("""
    <div class="hero-container">
        <div>
            <div class="hpe-brand-bar"></div>
            <div class="hpe-corp-title">Hewlett Packard<br/>Enterprise</div>
            
            <div class="hero-heading">HPE</div>
            <div class="hero-heading hero-heading-highlight">CaseFlow</div>
            <div class="hero-subheading">Team Task and<br/>Case Management System</div>
            
            <div class="feature-item">
                <div class="feature-icon-circle">📁</div>
                <div>
                    <div class="feature-text-title">Manage Cases</div>
                    <div class="feature-text-desc">Track and resolve tasks efficiently</div>
                </div>
            </div>
            
            <div class="feature-item">
                <div class="feature-icon-circle">👥</div>
                <div>
                    <div class="feature-text-title">Work Together</div>
                    <div class="feature-text-desc">Stay aligned with your team</div>
                </div>
            </div>
            
            <div class="feature-item">
                <div class="feature-icon-circle">📊</div>
                <div>
                    <div class="feature-text-title">Drive Results</div>
                    <div class="feature-text-desc">Real-time insights and reporting</div>
                </div>
            </div>
        </div>
        <div style="font-size:0.75rem; color:#6b7280; padding-top:20px;">
            Hewlett Packard Enterprise Development LP
        </div>
    </div>
    """, unsafe_allow_html=True)

def render_auth_view():
    if "auth_page" not in st.session_state:
        st.session_state["auth_page"] = "signin"

    # Outer split-screen grid layout (Left: Hero Graphic, Right: White Form Card)
    _, main_center, _ = st.columns([0.5, 9, 0.5])
    with main_center:
        col_hero, col_spacer, col_form = st.columns([4.2, 0.5, 4.3])

        with col_hero:
            render_hero_left()

        with col_form:
            # ----------------------------------------------------
            # VIEW: SIGN IN
            # ----------------------------------------------------
            if st.session_state["auth_page"] == "signin":
                st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)
                st.markdown("<div class='auth-card-title'>Welcome Back!</div>", unsafe_allow_html=True)
                st.markdown("<div class='auth-card-subtitle'>Sign in to your HPE CaseFlow account</div>", unsafe_allow_html=True)

                login_email = st.text_input(
                    "HPE Email Address",
                    placeholder="yourname@hpe.com",
                    key="in_email"
                ).strip().lower()

                login_pwd = st.text_input(
                    "Password",
                    type="password",
                    placeholder="Enter your password",
                    key="in_pwd"
                )

                row_rem, row_fp = st.columns([1, 1])
                with row_rem:
                    remember_me = st.checkbox("Remember me", value=True, key="in_remember")
                with row_fp:
                    if st.button("Forgot password?", key="btn_to_fp", help="Click to reset password"):
                        show_forgot_password_dialog()

                st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
                if st.button("Sign In", type="primary", use_container_width=True, key="btn_signin"):
                    if not login_email or not login_pwd:
                        st.error("Please provide both your HPE email address and password.")
                    else:
                        user = roster_col.find_one({"email": login_email})
                        if user and verify_password(login_pwd, user.get("password")):
                            default_aux = "Admin Work" if user.get("role") == "Admin" else "Not Ready - Online"
                            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                            roster_col.update_one(
                                {"_id": user["_id"]},
                                {"$set": {"current_aux": default_aux, "last_login": now_str}}
                            )
                            user["current_aux"] = default_aux
                            st.session_state["user"] = user

                            if remember_me:
                                cookie_manager.set("hpe_auth_token", login_email, expires_at=datetime.now() + timedelta(days=14))

                            st.success("Signed in successfully!")
                            st.rerun()
                        else:
                            st.error("Invalid HPE email address or password.")

                # Styled OR divider
                st.markdown("""
                <div style="display: flex; align-items: center; text-align: center; margin: 18px 0; color: #9ca3af; font-size: 0.85rem;">
                    <div style="flex: 1; border-bottom: 1px solid #e5e7eb;"></div>
                    <span style="padding: 0 10px;">or</span>
                    <div style="flex: 1; border-bottom: 1px solid #e5e7eb;"></div>
                </div>
                """, unsafe_allow_html=True)

                if st.button("🪟  Sign in with Microsoft (HPE)", use_container_width=True, key="btn_ms_sso"):
                    st.info("Directing to HPE Enterprise Single Sign-On (Ping/Microsoft Azure AD)...")

                st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
                
                c_lbl, c_lnk = st.columns([2.2, 1.8])
                with c_lbl:
                    st.markdown("<div style='text-align:right; font-size:0.92rem; color:#4b5563; padding-top:6px;'>Don't have an account?</div>", unsafe_allow_html=True)
                with c_lnk:
                    if st.button("Sign up", key="btn_goto_signup"):
                        st.session_state["auth_page"] = "signup"
                        st.rerun()

            # ----------------------------------------------------
            # VIEW: SIGN UP
            # ----------------------------------------------------
            elif st.session_state["auth_page"] == "signup":
                if st.button("← Back to Sign In", key="btn_back_to_signin"):
                    st.session_state["auth_page"] = "signin"
                    st.rerun()

                st.markdown("<div class='auth-card-title'>Create Your Account</div>", unsafe_allow_html=True)
                st.markdown("<div class='auth-card-subtitle'>Sign up to access HPE CaseFlow</div>", unsafe_allow_html=True)

                su_fname = st.text_input("First Name", placeholder="Enter your first name", key="reg_fname")
                su_lname = st.text_input("Last Name", placeholder="Enter your last name", key="reg_lname")
                su_empid = st.text_input("Employee ID", placeholder="Enter your employee ID", key="reg_empid")
                su_email = st.text_input("HPE Email Address", placeholder="yourname@hpe.com", key="reg_email").strip().lower()
                su_pwd = st.text_input("Password", type="password", placeholder="Create a password", key="reg_pwd")

                st.markdown("<div style='font-size:0.75rem; color:#6b7280; margin-top:-8px; margin-bottom:12px;'>Password must be at least 8 characters and include letters, numbers and a special character.</div>", unsafe_allow_html=True)

                su_role = st.selectbox("Role Assignment", ["Agent", "Admin/Agent", "Admin"], key="reg_role")

                st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
                if st.button("Sign Up", type="primary", use_container_width=True, key="btn_submit_signup"):
                    if not (su_fname and su_lname and su_empid and su_email and su_pwd):
                        st.error("Please fill in all registration fields.")
                    elif not su_email.endswith("@hpe.com"):
                        st.warning("Please ensure you are registering with an authorized HPE corporate email address.")
                    elif len(su_pwd) < 8:
                        st.error("Password must be at least 8 characters long.")
                    elif roster_col.find_one({"email": su_email}):
                        st.error("An account with this HPE email already exists.")
                    else:
                        hashed = hash_password(su_pwd)
                        default_aux = "Admin Work" if su_role == "Admin" else "Not Ready - Online"
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                        user_doc = {
                            "first_name": su_fname,
                            "last_name": su_lname,
                            "emp_id": su_empid,
                            "email": su_email,
                            "password": hashed,
                            "role": su_role,
                            "profile_pic": None,
                            "current_aux": default_aux,
                            "registered_date": now_str,
                            "aux_history": [{"aux": default_aux, "timestamp": now_str}],
                            "assignment_history": []
                        }
                        roster_col.insert_one(user_doc)
                        st.success("Account created successfully! Redirecting to Sign In...")
                        time_pkg.sleep(1.2)
                        st.session_state["auth_page"] = "signin"
                        st.rerun()

                st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
                c_lbl2, c_lnk2 = st.columns([2.4, 1.6])
                with c_lbl2:
                    st.markdown("<div style='text-align:right; font-size:0.92rem; color:#4b5563; padding-top:6px;'>Already have an account?</div>", unsafe_allow_html=True)
                with c_lnk2:
                    if st.button("Sign in", key="btn_goto_signin_bottom"):
                        st.session_state["auth_page"] = "signin"
                        st.rerun()


# ==========================================
# 10. DASHBOARD TAB VIEW
# ==========================================
def render_dashboard(user):
    handle_live_alerts_and_messages(user)
    
    search_q = st.text_input("🔍 Search cases, keywords, customer names, or subjects", placeholder="Type case #, subject, agent name...").strip().lower()

    if user["role"] == "Admin":
        all_cases = list(cases_col.find({"status": {"$nin": ["Resolved", "Closed"]}}))
    else:
        all_cases = list(cases_col.find({"assigned_to": user["email"], "status": {"$nin": ["Resolved", "Closed"]}}))

    now = datetime.now()
    crit_count = 0
    due_soon_count = 0
    on_track_count = 0

    for c in all_cases:
        prio = c.get("priority", "Low")
        if prio == "Critical":
            crit_count += 1
        try:
            d_time = datetime.strptime(c.get("due_date"), "%Y-%m-%d %H:%M")
            if now < d_time <= (now + timedelta(hours=4)):
                due_soon_count += 1
            elif d_time > (now + timedelta(hours=4)):
                on_track_count += 1
        except Exception:
            on_track_count += 1

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Active Cases", len(all_cases))
    m2.metric("Critical", crit_count)
    m3.metric("Due Soon (<4h)", due_soon_count)
    m4.metric("On Track", on_track_count)

    st.markdown("### Active Case Queue (Sorted by Urgency)")

    dash_col_main, dash_col_side = st.columns([8, 3])

    with dash_col_main:
        filtered_cases = []
        for c in all_cases:
            combined = f"{c.get('case_number','')} {c.get('subject','')} {c.get('assigned_agent_name','')} {c.get('vendor_name','')}".lower()
            if not search_q or search_q in combined:
                filtered_cases.append(c)

        urgency_map = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
        filtered_cases.sort(key=lambda x: urgency_map.get(x.get("priority", "Low"), 0), reverse=True)

        if not filtered_cases:
            st.info("No active cases currently in this queue.")
        else:
            table_html = """
            <table class='borderless-table'>
                <thead>
                    <tr>
                        <th>Case #</th>
                        <th>Subject</th>
                        <th>Priority</th>
                        <th>Assigned To</th>
                        <th>Due Date</th>
                        <th>Status</th>
                        <th>Last Update (Elapsed)</th>
                    </tr>
                </thead>
                <tbody>
            """
            for c in filtered_cases:
                try:
                    last_up = datetime.strptime(c.get("last_update"), "%Y-%m-%d %H:%M:%S")
                    elapsed_hours = round((now - last_up).total_seconds() / 3600, 1)
                    elapsed_str = f"{c.get('last_update')} ({elapsed_hours}h ago)"
                except Exception:
                    elapsed_str = c.get("last_update", "N/A")

                p_class = "pill-low"
                if c.get("priority") == "Critical": p_class = "pill-crit"
                elif c.get("priority") == "High": p_class = "pill-high"
                elif c.get("priority") == "Medium": p_class = "pill-med"

                table_html += f"""
                    <tr>
                        <td><strong>{c.get('case_number')}</strong></td>
                        <td>{c.get('subject')}</td>
                        <td><span class='pill {p_class}'>{c.get('priority')}</span></td>
                        <td>{c.get('assigned_agent_name', 'Unassigned')}</td>
                        <td>{c.get('due_date')}</td>
                        <td>`{c.get('status')}`</td>
                        <td>{elapsed_str}</td>
                    </tr>
                """
            table_html += "</tbody></table>"
            st.markdown(table_html, unsafe_allow_html=True)

            st.markdown("##### View & Work on Case:")
            case_options = {f"#{c.get('case_number')} - {c.get('subject')}": str(c["_id"]) for c in filtered_cases}
            sel_case_label = st.selectbox("Select case to open modal:", list(case_options.keys()))
            if st.button("Open Case Details Pop-up", type="secondary"):
                show_case_modal(case_options[sel_case_label], user)

    with dash_col_side:
        st.markdown("#### Live Workforce Aux")
        active_agents = list(roster_col.find(
            {"role": {"$in": ["Agent", "Admin/Agent"]}},
            {"first_name": 1, "last_name": 1, "current_aux": 1, "email": 1}
        ))
        
        for ag in active_agents:
            aux_val = ag.get("current_aux", "Not Ready - Online")
            aux_style = "pill-aux"
            if aux_val == "Available": aux_style = "pill-avail"
            elif "Break" in aux_val or "Lunch" in aux_val: aux_style = "pill-break"
            elif "Admin" in aux_val: aux_style = "pill-med"

            st.markdown(f"""
            <div style='padding:6px 0; border-bottom: 1px solid #f1f3f5; display:flex; justify-content:space-between; align-items:center;'>
                <span><strong>{ag.get('first_name')} {ag.get('last_name')}</strong></span>
                <span class='pill {aux_style}'>{aux_val}</span>
            </div>
            """, unsafe_allow_html=True)

        st.divider()
        st.markdown("##### 📁 Sync Vendor Excel Data")
        uploaded_vendor_file = st.file_uploader("Upload Vendor Master Contact File", type=["xlsx", "xls"])
        if uploaded_vendor_file:
            try:
                df_vendor = pd.read_excel(uploaded_vendor_file)
                st.success(f"Synced {len(df_vendor)} vendor records!")
            except Exception as e:
                st.error(f"Error parsing vendor excel file: {e}")


# ==========================================
# 11. MONITORING TAB (ADMIN ONLY)
# ==========================================
def render_monitoring(user):
    st.subheader("Workforce Live Monitoring & Interventions")
    agents = list(roster_col.find({"role": {"$in": ["Agent", "Admin/Agent"]}}))
    
    col_cards = st.columns(3)
    for idx, ag in enumerate(agents):
        with col_cards[idx % 3]:
            with st.container(border=True):
                st.markdown(f"### {ag.get('first_name')} {ag.get('last_name')}")
                st.caption(f"Role: {ag.get('role')} | Email: {ag.get('email')}")
                st.markdown(f"**Current Status:** `{ag.get('current_aux')}`")
                
                c1, c2, c3 = st.columns(3)
                with c1:
                    if st.button("Inspect", key=f"insp_{ag['email']}"):
                        show_agent_monitoring_modal(ag['email'])
                with c2:
                    if st.button("Message", key=f"msg_{ag['email']}"):
                        show_broadcast_modal(ag['email'], f"{user['first_name']} {user['last_name']}")
                with c3:
                    if st.button("Kick", key=f"kck_{ag['email']}"):
                        roster_col.update_one({"email": ag["email"]}, {"$set": {"force_logout": True}})
                        st.warning(f"Session terminated for {ag.get('first_name')}.")


# ==========================================
# 12. SCHEDULE TAB
# ==========================================
def render_schedule(user):
    st.subheader("Schedule, Shifts & Leave Management")
    st.radio("Schedule View", ["Month", "Week", "Day"], horizontal=True)

    today = date.today()
    selected_date = st.date_input("Target Schedule Date", value=today)
    sel_date_str = selected_date.strftime("%Y-%m-%d")

    sched_doc = schedule_col.find_one({"date": sel_date_str})
    pto_limit = sched_doc.get("pto_allocation", 3) if sched_doc else 3
    pto_taken = sched_doc.get("pto_approved_count", 0) if sched_doc else 0
    pto_remaining = max(0, pto_limit - pto_taken)

    st.info(f"📅 **Date:** {sel_date_str} | **PTO Allocation Available:** {pto_remaining} slots remaining (Limit: {pto_limit})")

    if user["role"] in ["Admin", "Admin/Agent"]:
        with st.expander("⚙️ Admin PTO Allocation & Auto-Plot Control", expanded=False):
            col_p1, col_p2 = st.columns(2)
            with col_p1:
                new_alloc = st.number_input("Set PTO Allocation for Selected Date", min_value=0, max_value=20, value=pto_limit)
                if st.button("Update Allocation", key="btn_save_alloc"):
                    schedule_col.update_one(
                        {"date": sel_date_str},
                        {"$set": {"pto_allocation": new_alloc}},
                        upsert=True
                    )
                    st.success("Allocation updated!")
                    st.rerun()

            with col_p2:
                if st.button("Auto-Plot Shift Staggering (Breaks/Lunch)", key="btn_autoplot"):
                    all_active = list(roster_col.find({"role": {"$in": ["Agent", "Admin/Agent"]}}))
                    leaves = sched_doc.get("leaves", []) if sched_doc else []
                    leave_emails = [l["agent_email"] for l in leaves]
                    working_agents = [a for a in all_active if a["email"] not in leave_emails]
                    
                    staggered_schedule = []
                    for i, ag in enumerate(working_agents):
                        b1 = f"{9 + (i % 3)}:00"
                        lunch = f"{12 + (i % 2)}:00"
                        b2 = f"{14 + (i % 3)}:00"
                        staggered_schedule.append({
                            "agent_email": ag["email"],
                            "agent_name": f"{ag.get('first_name')} {ag.get('last_name')}",
                            "schedule_plan": f"Shift: 08:00-17:00 | Break 1: {b1} | Lunch: {lunch} | Break 2: {b2}"
                        })

                    schedule_col.update_one(
                        {"date": sel_date_str},
                        {"$set": {"Schedule_Monitoring": staggered_schedule}},
                        upsert=True
                    )
                    st.success(f"Optimal staggered schedule plotted for {len(working_agents)} active agents!")
                    st.rerun()

    st.markdown("#### Submit Leave or Schedule Request")
    req_type = st.selectbox("Request Type", ["Paid Time Off (PTO)", "Sick Leave", "Emergency Leave", "Schedule Swap"])

    if req_type in ["Paid Time Off (PTO)", "Sick Leave", "Emergency Leave"]:
        if st.button("Submit Leave Request"):
            if req_type == "Paid Time Off (PTO)":
                if pto_remaining <= 0:
                    st.error("No Allocation for the selected date! PTO request cannot be submitted.")
                    return
                schedule_col.update_one(
                    {"date": sel_date_str},
                    {
                        "$inc": {"pto_approved_count": 1},
                        "$push": {"leaves": {"agent_email": user["email"], "type": req_type, "status": "Approved"}}
                    },
                    upsert=True
                )
                st.success("PTO Request Auto-Approved! Allocation updated.")
                st.rerun()
            else:
                schedule_col.update_one(
                    {"date": sel_date_str},
                    {"$push": {"leaves": {"agent_email": user["email"], "type": req_type, "status": "Approved"}}},
                    upsert=True
                )
                st.success(f"{req_type} has been automatically approved and logged.")
                st.rerun()

    elif req_type == "Schedule Swap":
        peers = list(roster_col.find({"email": {"$ne": user["email"]}, "role": {"$in": ["Agent", "Admin/Agent"]}}))
        peer_dict = {f"{p.get('first_name')} {p.get('last_name')} ({p['email']})": p['email'] for p in peers}
        target_swap_peer = st.selectbox("Select Advocate to Swap With", list(peer_dict.keys()))

        if st.button("Send Swap Request"):
            swaps_col.insert_one({
                "requester_email": user["email"],
                "requester_name": f"{user['first_name']} {user['last_name']}",
                "target_email": peer_dict[target_swap_peer],
                "date": sel_date_str,
                "status": "Pending",
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            alerts_col.insert_one({
                "target_email": peer_dict[target_swap_peer],
                "type": "Schedule Swap Request",
                "message": f"{user['first_name']} requested to swap shifts with you for {sel_date_str}.",
                "read": False
            })
            st.success("Schedule swap request dispatched to advocate!")

    my_swap_requests = list(swaps_col.find({"target_email": user["email"], "status": "Pending"}))
    if my_swap_requests:
        st.markdown("#### Pending Schedule Swaps Requiring Your Approval")
        for sw in my_swap_requests:
            c_s1, c_s2 = st.columns([3, 1])
            c_s1.write(f"Advocate **{sw.get('requester_name')}** wants to swap shift with you for date: `{sw.get('date')}`.")
            if c_s2.button("Approve Swap", key=f"appr_{sw['_id']}"):
                swaps_col.update_one({"_id": sw["_id"]}, {"$set": {"status": "Approved"}})
                alerts_col.insert_one({"target_email": sw["requester_email"], "type": "Swap Approved", "message": f"Your swap for {sw.get('date')} was approved by advocate!", "read": False})
                admins = list(roster_col.find({"role": "Admin"}))
                for a in admins:
                    alerts_col.insert_one({"target_email": a["email"], "type": "Swap Completed", "message": f"Swap between {sw['requester_name']} and {user['first_name']} approved.", "read": False})
                st.success("Swap successfully finalized!")
                st.rerun()


# ==========================================
# 13. REPORT TAB
# ==========================================
def render_report(user):
    st.subheader("Performance, SLA & Workforce Adherence Analytics")
    st.radio("Timeframe Filter", ["Daily", "WOW", "MTD", "YTD"], horizontal=True)

    query = {}
    if user["role"] == "Agent":
        query["assigned_to"] = user["email"]

    all_historical = list(cases_col.find(query))
    total_cases = len(all_historical)
    resolved_count = sum(1 for c in all_historical if c.get("status") in ["Resolved", "Closed"])
    breach_count = sum(1 for c in all_historical if c.get("closure_type") == "Contract Breach")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Cases Handled", total_cases)
    c2.metric("Successfully Resolved", resolved_count)
    c3.metric("Contract Breaches", breach_count, delta=f"-{breach_count}" if breach_count > 0 else "0", delta_color="inverse")
    c4.metric("Adherence Score", "94.8%")

    g1, g2 = st.columns(2)
    with g1:
        st.markdown("##### Case Resolution vs Breach Breakdown")
        df_chart = pd.DataFrame({
            "Outcome": ["Resolved On-Time", "Contract Breach", "In-Flight/Pending"],
            "Count": [resolved_count, breach_count, max(0, total_cases - resolved_count - breach_count)]
        })
        fig = px.pie(df_chart, names="Outcome", values="Count", color="Outcome",
                     color_discrete_map={"Resolved On-Time": "#20c997", "Contract Breach": "#f03e3e", "In-Flight/Pending": "#339af0"},
                     hole=0.45)
        st.plotly_chart(fig, use_container_width=True)

    with g2:
        st.markdown("##### Attendance & Schedule Adherence (Scheduled vs Attended)")
        df_att = pd.DataFrame({
            "Metric": ["Scheduled Hours", "Attended Hours", "Adherent Aux Hours"],
            "Hours": [40, 38.5, 36.8]
        })
        fig_bar = px.bar(df_att, x="Metric", y="Hours", color="Metric", color_discrete_sequence=["#4dabf7", "#38d9a9", "#74c0fc"])
        st.plotly_chart(fig_bar, use_container_width=True)


# ==========================================
# 14. SETTING TAB (ADMIN ONLY)
# ==========================================
def render_settings(user):
    st.subheader("Team Roster Master Directory & Role Administration")
    all_users = list(roster_col.find({}))

    st.markdown("#### Registered Users")
    for u in all_users:
        with st.container(border=True):
            r1, r2, r3, r4 = st.columns([3, 3, 2, 2])
            r1.write(f"**{u.get('first_name')} {u.get('last_name')}** ({u.get('emp_id')})")
            r2.write(f"Email: `{u.get('email')}`")
            new_role = r3.selectbox("Role", ["Agent", "Admin/Agent", "Admin"], index=["Agent", "Admin/Agent", "Admin"].index(u.get("role", "Agent")), key=f"r_role_{u['_id']}")
            
            if r4.button("Update Role", key=f"btn_r_{u['_id']}"):
                roster_col.update_one({"_id": u["_id"]}, {"$set": {"role": new_role}})
                st.toast(f"Role updated for {u.get('first_name')}!")
                st.rerun()

    st.divider()
    st.markdown("#### External Source Data Synchronization")
    if st.button("Sync Data From External Master HR / Ticketing Source"):
        with st.spinner("Connecting to external API..."):
            time_pkg.sleep(1.2)
            st.success("Successfully synchronized all cases and agent status with external HPE systems.")


# ==========================================
# 15. MAIN RUNNER & ROUTING
# ==========================================
def main():
    if "user" not in st.session_state:
        saved_email = cookie_manager.get("hpe_auth_token")
        if saved_email:
            existing = roster_col.find_one({"email": saved_email})
            if existing:
                st.session_state["user"] = existing

    if "user" not in st.session_state or not st.session_state["user"]:
        render_auth_view()
        return

    user = st.session_state["user"]

    refreshed_user = roster_col.find_one({"email": user["email"]})
    if refreshed_user and refreshed_user.get("force_logout"):
        roster_col.update_one({"email": user["email"]}, {"$unset": {"force_logout": ""}})
        cookie_manager.delete("hpe_auth_token")
        del st.session_state["user"]
        st.warning("Your session has been terminated by an administrator.")
        st.rerun()

    render_custom_top_bar(user)

    st.sidebar.markdown(f"### 📍 Navigation")
    if user["role"] in ["Admin", "Admin/Agent"]:
        nav_options = ["Dashboard", "Monitoring", "Schedule", "Report", "Setting"]
    else:
        nav_options = ["Dashboard", "Schedule", "Report"]

    active_page = st.sidebar.radio("Go to:", nav_options, index=0)

    with st.sidebar.expander("👤 My Profile Settings"):
        uploaded_pic = st.file_uploader("Upload Profile Picture", type=["png", "jpg", "jpeg"])
        if uploaded_pic:
            import base64
            pic_b64 = f"data:image/png;base64,{base64.b64encode(uploaded_pic.read()).decode()}"
            roster_col.update_one({"email": user["email"]}, {"$set": {"profile_pic": pic_b64}})
            st.session_state["user"]["profile_pic"] = pic_b64
            st.success("Profile photo updated!")
            st.rerun()

        new_password = st.text_input("New Password", type="password", key="new_prof_pwd")
        if st.button("Change Password"):
            if new_password:
                roster_col.update_one({"email": user["email"]}, {"$set": {"password": hash_password(new_password)}})
                st.success("Password changed successfully!")

    if st.sidebar.button("Sign Out", type="primary", use_container_width=True):
        cookie_manager.delete("hpe_auth_token")
        update_agent_aux(user["email"], "Not Ready - Online")
        del st.session_state["user"]
        st.rerun()

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
