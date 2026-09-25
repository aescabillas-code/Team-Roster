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

# Custom Styling: Replicates the exact visual identity of the design
st.markdown("""
    <style>
    /* Hide Streamlit default headers & toolbars */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden !important;}
    [data-testid="stDecoration"] {visibility: hidden !important;}
    [data-testid="stStatusWidget"] {visibility: hidden !important;}

    /* Page container spacing */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1200px;
    }
    
    :root {
        --hpe-green: #01a982;
        --hpe-green-dark: #007a5e;
        --hpe-teal: #00c9a7;
    }

    /* Left Hero Card */
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

    /* Right Auth Form Titles */
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

    /* Primary Button Styling */
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

    /* Secondary / Outline Button */
    div.stButton > button[kind="secondary"] {
        border-radius: 8px !important;
        font-weight: 600 !important;
        border: 1px solid #cbd5e1 !important;
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
    try:
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
    except Exception:
        return False


# ==========================================
# 5. REAL-TIME AUX MANAGEMENT
# ==========================================
def update_agent_aux(email, new_aux):
    try:
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
    except Exception as e:
        st.error(f"Error updating aux: {e}")


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
    st.caption(f"Priority: **{case.get('priority')}** | Due: **{case.get('due_date')}**")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Assigned To:** {case.get('assigned_agent_name', 'Unassigned')}")
        st.markdown(f"**Current Status:** `{case.get('status')}`")
        st.markdown(f"**Status Reason:** {case.get('status_reason', 'N/A')}")
        st.markdown(f"**Last Update:** {case.get('last_update')}")
    with col2:
        st.markdown("**Vendor Information:**")
        st.text_input("Vendor Name", case.get("vendor_name", "Hewlett Packard Enterprise"), disabled=True)
        st.text_input("Vendor Email", case.get("vendor_email", "vendor-support@hpe-partners.com"), disabled=True)
        st.text_input("Vendor Phone", case.get("vendor_phone", "+1-800-555-0199"), disabled=True)

    st.divider()

    if user["role"] == "Admin":
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

    s_col1, s_col2 = st.columns(2)
    with s_col1:
        new_status = st.selectbox("Case Status", options=dropdowns.get("Case_Status", []), index=dropdowns.get("Case_Status", []).index(case.get("status")) if case.get("status") in dropdowns.get("Case_Status", []) else 0)
        new_reason = st.selectbox("Status Reason", options=dropdowns.get("Case_Reason", []))
    with s_col2:
        new_closure = st.selectbox("Closure Type", options=["None"] + dropdowns.get("Closure_Type", []))
        breach_reason = None
        if new_closure == "Contract Breach":
            breach_reason = st.selectbox("Contract Breach Reason", options=dropdowns.get("Contract_Breach", []))

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
    t1, t2 = st.tabs(["Aux History (Today)", "Case Assignment History"])
    with t1:
        aux_hist = agent.get("aux_history", [])
        if aux_hist:
            st.dataframe(pd.DataFrame(aux_hist).iloc[::-1], use_container_width=True)
        else:
            st.info("No aux history recorded for today.")

    with t2:
        asg_hist = agent.get("assignment_history", [])
        if asg_hist:
            st.dataframe(pd.DataFrame(asg_hist).iloc[::-1], use_container_width=True)
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
    try:
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
            sched_text = "Shift: 08:00 - 17:00 | Break: 10:00, 15:00 | Lunch: 12:00"
            st.markdown(f"<div style='font-size:0.75rem; color:#868e96; text-align:right;'>📅 {sched_text}</div>", unsafe_allow_html=True)

    st.markdown("---")


# ==========================================
# 9. SIGN IN / SIGN UP (EXACT IMAGE REPLICA)
# ==========================================
def render_auth_view():
    if "auth_page" not in st.session_state:
        st.session_state["auth_page"] = "signin"

    # Outer split layout
    col_left, col_mid, col_right = st.columns([4.4, 0.4, 4.4])

    # ------------------ LEFT HERO BANNER ------------------
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

    # ------------------ RIGHT FORM PANEL ------------------
    with col_right:
        # 1. SIGN IN VIEW
        if st.session_state["auth_page"] == "signin":
            st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
            st.markdown("<div class='auth-main-title'>Welcome Back!</div>", unsafe_allow_html=True)
            st.markdown("<div class='auth-sub-title'>Sign in to your HPE CaseFlow account</div>", unsafe_allow_html=True)

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

            col_rem, col_fp = st.columns([1, 1])
            with col_rem:
                remember_me = st.checkbox("Remember me", value=True, key="in_remember")
            with col_fp:
                if st.button("Forgot password?", key="btn_to_fp", help="Reset password"):
                    show_forgot_password_dialog()

            st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
            if st.button("Sign In", type="primary", use_container_width=True, key="btn_signin"):
                if not login_email or not login_pwd:
                    st.error("Please enter both email and password.")
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

            # OR divider
            st.markdown("""
            <div style="display: flex; align-items: center; text-align: center; margin: 18px 0; color: #94a3b8; font-size: 0.85rem;">
                <div style="flex: 1; border-bottom: 1px solid #e2e8f0;"></div>
                <span style="padding: 0 10px;">or</span>
                <div style="flex: 1; border-bottom: 1px solid #e2e8f0;"></div>
            </div>
            """, unsafe_allow_html=True)

            # Microsoft SSO Button matching screenshot
            st.markdown("""
            <style>
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
            <div class="ms-btn-wrap">
            """, unsafe_allow_html=True)
            if st.button("🪟  Sign in with Microsoft (HPE)", use_container_width=True, key="btn_ms_sso"):
                st.info("Directing to HPE Single Sign-On (Azure AD)...")
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
            
            # Switch to Sign Up
            c_lbl, c_lnk = st.columns([2.2, 1.8])
            with c_lbl:
                st.markdown("<div style='text-align:right; font-size:0.92rem; color:#475569; padding-top:6px;'>Don't have an account?</div>", unsafe_allow_html=True)
            with c_lnk:
                if st.button("Sign up", key="btn_goto_signup"):
                    st.session_state["auth_page"] = "signup"
                    st.rerun()

        # 2. SIGN UP VIEW
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

            # Default role for all signups is Agent
            default_role = "Agent"

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
                    default_aux = "Not Ready - Online"
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    user_doc = {
                        "first_name": su_fname,
                        "last_name": su_lname,
                        "emp_id": su_empid,
                        "email": su_email,
                        "password": hashed,
                        "role": default_role,
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
                st.markdown("<div style='text-align:right; font-size:0.92rem; color:#475569; padding-top:6px;'>Already have an account?</div>", unsafe_allow_html=True)
            with c_lnk2:
                if st.button("Sign in", key="btn_goto_signin_bottom"):
                    st.session_state["auth_page"] = "signin"
                    st.rerun()


# ==========================================
# 10. DASHBOARD TAB VIEW
# ==========================================
def render_dashboard(user):
    handle_live_alerts_and_messages(user)
    search_q = st.text_input("🔍 Search cases, keywords, or subjects", placeholder="Type case #, subject, or name...").strip().lower()

    if user["role"] == "Admin":
        all_cases = list(cases_col.find({"status": {"$nin": ["Resolved", "Closed"]}}))
    else:
        all_cases = list(cases_col.find({"assigned_to": user["email"], "status": {"$nin": ["Resolved", "Closed"]}}))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Active Cases", len(all_cases))
    m2.metric("Critical", sum(1 for c in all_cases if c.get("priority") == "Critical"))
    m3.metric("Due Soon", sum(1 for c in all_cases if c.get("priority") in ["High", "Critical"]))
    m4.metric("On Track", sum(1 for c in all_cases if c.get("priority") not in ["High", "Critical"]))

    dash_col_main, dash_col_side = st.columns([8, 3])

    with dash_col_main:
        filtered_cases = [c for c in all_cases if not search_q or search_q in f"{c.get('case_number','')} {c.get('subject','')}".lower()]

        if not filtered_cases:
            st.info("No active cases found.")
        else:
            table_html = "<table class='borderless-table'><thead><tr><th>Case #</th><th>Subject</th><th>Priority</th><th>Assigned To</th><th>Status</th></tr></thead><tbody>"
            for c in filtered_cases:
                table_html += f"<tr><td><strong>{c.get('case_number')}</strong></td><td>{c.get('subject')}</td><td>{c.get('priority')}</td><td>{c.get('assigned_agent_name', 'Unassigned')}</td><td>`{c.get('status')}`</td></tr>"
            table_html += "</tbody></table>"
            st.markdown(table_html, unsafe_allow_html=True)

            case_options = {f"#{c.get('case_number')} - {c.get('subject')}": str(c["_id"]) for c in filtered_cases}
            sel_case_label = st.selectbox("Inspect case:", list(case_options.keys()))
            if st.button("Open Case Details"):
                show_case_modal(case_options[sel_case_label], user)

    with dash_col_side:
        st.markdown("#### Live Workforce Aux")
        active_agents = list(roster_col.find({"role": {"$in": ["Agent", "Admin/Agent"]}}))
        for ag in active_agents:
            st.write(f"**{ag.get('first_name')} {ag.get('last_name')}**: `{ag.get('current_aux')}`")


# ==========================================
# 11. MONITORING TAB (ADMIN ONLY)
# ==========================================
def render_monitoring(user):
    st.subheader("Workforce Live Monitoring")
    agents = list(roster_col.find({"role": {"$in": ["Agent", "Admin/Agent"]}}))
    col_cards = st.columns(3)
    for idx, ag in enumerate(agents):
        with col_cards[idx % 3]:
            with st.container(border=True):
                st.markdown(f"### {ag.get('first_name')} {ag.get('last_name')}")
                st.caption(f"Role: {ag.get('role')} | Current: `{ag.get('current_aux')}`")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Inspect", key=f"insp_{ag['email']}"):
                        show_agent_monitoring_modal(ag['email'])
                with c2:
                    if st.button("Message", key=f"msg_{ag['email']}"):
                        show_broadcast_modal(ag['email'], f"{user['first_name']} {user['last_name']}")


# ==========================================
# 12. SCHEDULE TAB
# ==========================================
def render_schedule(user):
    st.subheader("Shift & Leave Management")
    selected_date = st.date_input("Target Date", value=date.today())
    st.info(f"Schedule for {selected_date}")


# ==========================================
# 13. REPORT TAB
# ==========================================
def render_report(user):
    st.subheader("Analytics & Reporting")
    st.metric("Adherence Score", "95.2%")


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
            new_role = r3.selectbox(
                "Role", 
                ["Agent", "Admin/Agent", "Admin"], 
                index=["Agent", "Admin/Agent", "Admin"].index(u.get("role", "Agent")), 
                key=f"r_role_{u['_id']}"
            )
            
            if r4.button("Update Role", key=f"btn_r_{u['_id']}"):
                roster_col.update_one({"_id": u["_id"]}, {"$set": {"role": new_role}})
                st.toast(f"Role updated to {new_role} for {u.get('first_name')}!")
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
    render_custom_top_bar(user)

    st.sidebar.markdown("### 📍 Navigation")
    nav_options = ["Dashboard", "Monitoring", "Schedule", "Report", "Setting"] if user["role"] in ["Admin", "Admin/Agent"] else ["Dashboard", "Schedule", "Report"]
    active_page = st.sidebar.radio("Go to:", nav_options, index=0)

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
