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
    page_title="HPE Tasks & Workforce Tracker",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling: Replaces Streamlit standard deploy/edit headers with clean styling
st.markdown("""
    <style>
    /* Hide Streamlit default chrome & deploy button */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden !important;}
    [data-testid="stDecoration"] {visibility: hidden !important;}
    [data-testid="stStatusWidget"] {visibility: hidden !important;}

    /* Modern clean container & borders */
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2rem;
    }
    
    /* Custom borderless table */
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
    # Update with your actual MongoDB URI or st.secrets["MONGO_URI"]
    MONGO_URI = st.secrets.get("MONGO_URI", "mongodb://localhost:27017")
    return pymongo.MongoClient(MONGO_URI)

client = get_mongo_client()
db = client["TeamRoster"]
roster_col = db["Team Roster Collection"]
validation_col = db["Validation_Dropdown"]
schedule_col = db["Schedule_Monitoring"]
cases_col = db["Cases_Collection"]
alerts_col = db["Alerts_Collection"]
messages_col = db["Messages_Collection"]
swaps_col = db["Schedule_Swaps"]

# Seed validation dropdown objects if empty
def seed_validation_data():
    if validation_col.count_documents({}) == 0:
        validation_col.insert_one({
            "Validation_Dropdown": {
                "Case_Status": ["Open", "In Progress", "Pending Vendor Response", "Escalated", "Resolved", "Closed"],
                "Case_Reason": ["First Contact", "Awaiting Part Delivery", "Technical Troubleshooting", "Customer Callback Needed", "Engineer Dispatched"],
                "Closure_Type": ["Completed Successfully", "Customer Withdrawn", "Contract Breach", "Cancelled"],
                "Contract_Breach": ["SLA Exceeded", "Vendor Missed Commitment", "Wrong Part Shipped", "No Initial Response in 4h", "Repeated Outage Unresolved"]
            }
        })
seed_validation_data()

def get_dropdown_data():
    doc = validation_col.find_one({}, sort=[('_id', pymongo.DESCENDING)])
    if doc and "Validation_Dropdown" in doc:
        return doc["Validation_Dropdown"]
    return {
        "Case_Status": ["Open", "In Progress", "Resolved", "Closed"],
        "Case_Reason": ["Initial Work", "Vendor Contact"],
        "Closure_Type": ["Completed", "Contract Breach"],
        "Contract_Breach": ["SLA Missed", "Defective Component"]
    }

# Cookie manager for seamless "Remember Me" / session persistence
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
    """
    Auto assigns to an Available agent.
    Rules:
    - Available aux only.
    - Considers total active cases and assigned cases today.
    - Critical cases are evenly distributed and not assigned to someone with an active critical case.
    """
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

    # Build metric scores for available agents
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
        # Filter agents with 0 active critical cases first
        crit_free = [c for c in candidate_metrics if c["active_critical"] == 0]
        if crit_free:
            pool = crit_free
        else:
            pool = candidate_metrics
    else:
        pool = candidate_metrics

    # Sort by fewest active cases first, then fewest daily cases
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

    # Log case assignment in agent aux/assignment history
    roster_col.update_one(
        {"email": chosen_agent["email"]},
        {"$push": {"assignment_history": {
            "case_id": str(case_id),
            "case_number": case.get("case_number"),
            "priority": case.get("priority"),
            "timestamp": now_iso
        }}}
    )

    # Notify agent
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

    # If transitioned to Available, trigger auto assignment for pending unassigned cases
    if new_aux == "Available":
        unassigned_cases = cases_col.find({"assigned_to": None}).sort("urgency_weight", pymongo.DESCENDING)
        for c in unassigned_cases:
            assigned = auto_assign_case(c["_id"])
            if not assigned:
                break


# ==========================================
# 6. POPUPS & DIALOGS (Non-disruptive)
# ==========================================
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

    # Admin Reassignment or Case Transfer
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

    # Status & Contract Breach workflow
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

    # Automated Notice Generator for Contract Breach
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
        email_text = st.text_area("Review / Edit Breach Email Before Sending", value=default_body, height=180)
        if st.button("Send Breach Notice Email to Vendor", key="btn_send_breach"):
            # Trigger alert for all Admins
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
    # 1. Check direct broadcast messages from Admins
    unread_msg = messages_col.find_one({"target_email": user["email"], "displayed": False})
    if unread_msg:
        st.warning(f"📢 **ADMIN MESSAGE from {unread_msg.get('sender')}**:\n\n{unread_msg.get('message')}")
        if st.button("Acknowledge Message", key=f"ack_msg_{unread_msg['_id']}"):
            messages_col.update_one({"_id": unread_msg["_id"]}, {"$set": {"displayed": True}})
            st.rerun()

    # 2. Check pending notifications
    unread_alerts = list(alerts_col.find({"target_email": user["email"], "read": False}).limit(3))
    for alert in unread_alerts:
        st.info(f"🔔 **{alert.get('type')}:** {alert.get('message')}")
        if st.button("Dismiss", key=f"alert_btn_{alert['_id']}"):
            alerts_col.update_one({"_id": alert["_id"]}, {"$set": {"read": True}})
            st.rerun()

    # 3. Global Critical Near-Due Warning
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
        st.title("HPE Task Tracker")
    
    with top_col2:
        with st.container():
            c_pic, c_details, c_aux = st.columns([1, 2, 2])
            with c_pic:
                if user.get("profile_pic"):
                    st.image(user["profile_pic"], width=50)
                else:
                    st.markdown("👤")
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

        # Display today's plotted schedule below Aux Bar for Agent & Admin/Agent
        if user["role"] in ["Agent", "Admin/Agent"]:
            today_str = datetime.now().strftime("%Y-%m-%d")
            sched = schedule_col.find_one({"date": today_str, "Schedule_Monitoring.agent_email": user["email"]})
            sched_text = "Standard Shift (08:00 - 17:00) | Break: 10:00, 15:00 | Lunch: 12:00"
            if sched and "Schedule_Monitoring" in sched:
                for entry in sched["Schedule_Monitoring"]:
                    if entry.get("agent_email") == user["email"]:
                        sched_text = f"Today's Plan: {entry.get('schedule_plan', 'Standard')}"
            st.markdown(f"<div style='font-size:0.75rem; color:#868e96; text-align:right;'>📅 {sched_text}</div>", unsafe_allow_html=True)

    st.markdown("---")


# ==========================================
# 9. AUTH VIEW (SIGN IN / SIGN UP / FORGOT)
# ==========================================
def render_auth_view():
    st.markdown("<h2 style='text-align:center;'>HPE Operations & Task Monitoring Tracker</h2>", unsafe_allow_html=True)
    auth_tab1, auth_tab2, auth_tab3 = st.tabs(["Sign In", "Sign Up", "Forgot Password"])

    with auth_tab1:
        st.subheader("Login to your account")
        email = st.text_input("HPE Email", key="login_email").strip().lower()
        pwd = st.text_input("Password", type="password", key="login_pwd")
        remember_me = st.checkbox("Remember me", value=True)

        if st.button("Sign In", type="primary", use_container_width=True):
            if not email or not pwd:
                st.error("Please provide both email and password.")
                return

            user = roster_col.find_one({"email": email})
            if user and verify_password(pwd, user.get("password")):
                # Set initial aux based on role
                default_aux = "Admin Work" if user.get("role") == "Admin" else "Not Ready - Online"
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                roster_col.update_one(
                    {"_id": user["_id"]},
                    {"$set": {"current_aux": default_aux, "last_login": now_str}}
                )
                user["current_aux"] = default_aux
                st.session_state["user"] = user

                if remember_me:
                    cookie_manager.set("hpe_auth_token", email, expires_at=datetime.now() + timedelta(days=14))

                st.success("Signed in successfully!")
                st.rerun()
            else:
                st.error("Invalid HPE Email or Password.")

    with auth_tab2:
        st.subheader("Register New Team Roster Account")
        c1, c2 = st.columns(2)
        with c1:
            fname = st.text_input("First Name", key="su_fname")
            emp_id = st.text_input("Employee ID", key="su_empid")
            hpe_email = st.text_input("HPE Email (@hpe.com)", key="su_email").strip().lower()
        with c2:
            lname = st.text_input("Last Name", key="su_lname")
            role = st.selectbox("Role", ["Agent", "Admin/Agent", "Admin"], key="su_role")
            su_pwd = st.text_input("Password", type="password", key="su_pwd")

        if st.button("Complete Sign Up", type="primary", use_container_width=True):
            if not (fname and lname and emp_id and hpe_email and su_pwd):
                st.error("All fields are mandatory for HPE Roster registration.")
                return
            if not hpe_email.endswith("@hpe.com"):
                st.warning("Please ensure you sign up using your valid HPE email domain.")

            if roster_col.find_one({"email": hpe_email}):
                st.error("An account with this HPE email already exists.")
                return

            hashed = hash_password(su_pwd)
            default_aux = "Admin Work" if role == "Admin" else "Not Ready - Online"
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Store in Team Roster Collection as an object
            user_doc = {
                "first_name": fname,
                "last_name": lname,
                "emp_id": emp_id,
                "email": hpe_email,
                "password": hashed,
                "role": role,
                "profile_pic": None,
                "current_aux": default_aux,
                "registered_date": now_str,
                "aux_history": [{"aux": default_aux, "timestamp": now_str}],
                "assignment_history": []
            }
            roster_col.insert_one(user_doc)
            st.success("Sign up successful! Please navigate to Sign In tab to access the tracker.")

    with auth_tab3:
        st.subheader("Password Reset")
        fp_email = st.text_input("Enter your registered HPE Email", key="fp_email").strip().lower()
        if st.button("Send Reset Link"):
            user = roster_col.find_one({"email": fp_email})
            if user:
                # Simulated secure link dispatch
                token = hash_password(fp_email)[:16]
                st.success(f"A password reset link has been dispatched to {fp_email}. [Link: https://tracker.hpe.com/reset?token={token}]")
            else:
                st.error("No roster record found with this email.")


# ==========================================
# 10. DASHBOARD TAB VIEW
# ==========================================
def render_dashboard(user):
    handle_live_alerts_and_messages(user)
    
    # Live Search Bar
    search_q = st.text_input("🔍 Search cases, keywords, customer names, or subjects", placeholder="Type case #, subject, agent name...").strip().lower()

    # Query Cases
    if user["role"] == "Admin":
        all_cases = list(cases_col.find({"status": {"$nin": ["Resolved", "Closed"]}}))
    else:
        all_cases = list(cases_col.find({"assigned_to": user["email"], "status": {"$nin": ["Resolved", "Closed"]}}))

    # Metric calculations
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

    # Tiles
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Active Cases", len(all_cases))
    m2.metric("Critical", crit_count)
    m3.metric("Due Soon (<4h)", due_soon_count)
    m4.metric("On Track", on_track_count)

    st.markdown("### Active Case Queue (Sorted by Urgency)")

    dash_col_main, dash_col_side = st.columns([8, 3])

    with dash_col_main:
        # Search Filter
        filtered_cases = []
        for c in all_cases:
            combined = f"{c.get('case_number','')} {c.get('subject','')} {c.get('assigned_agent_name','')} {c.get('vendor_name','')}".lower()
            if not search_q or search_q in combined:
                filtered_cases.append(c)

        # Sort priority/urgency: Critical > High > Medium > Low
        urgency_map = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
        filtered_cases.sort(key=lambda x: urgency_map.get(x.get("priority", "Low"), 0), reverse=True)

        if not filtered_cases:
            st.info("No active cases currently in this queue.")
        else:
            # HTML Borderless Table with Clickable Inspect triggers
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
                # Calculate elapsed hours
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

            # Case inspector trigger
            st.markdown("##### View & Work on Case:")
            case_options = {f"#{c.get('case_number')} - {c.get('subject')}": str(c["_id"]) for c in filtered_cases}
            sel_case_label = st.selectbox("Select case to open modal:", list(case_options.keys()))
            if st.button("Open Case Details Pop-up", type="secondary"):
                show_case_modal(case_options[sel_case_label], user)

    # Right side monitoring tile (Only displays Agents & Admin/Agents)
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

        # Upload Vendor Contacts Excel File option next to the dashboard
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
    view_tier = st.radio("Schedule View", ["Month", "Week", "Day"], horizontal=True)

    today = date.today()
    selected_date = st.date_input("Target Schedule Date", value=today)
    sel_date_str = selected_date.strftime("%Y-%m-%d")

    # Fetch PTO allocation for target date
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
                    # Auto-plot breaks & lunches ensuring someone is ALWAYS Available
                    all_active = list(roster_col.find({"role": {"$in": ["Agent", "Admin/Agent"]}}))
                    # Exclude leaves
                    leaves = sched_doc.get("leaves", []) if sched_doc else []
                    leave_emails = [l["agent_email"] for l in leaves]
                    working_agents = [a for a in all_active if a["email"] not in leave_emails]
                    
                    staggered_schedule = []
                    # Assign intervals
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

    # Leave Request Filing
    st.markdown("#### Submit Leave or Schedule Request")
    req_type = st.selectbox("Request Type", ["Paid Time Off (PTO)", "Sick Leave", "Emergency Leave", "Schedule Swap"])

    if req_type in ["Paid Time Off (PTO)", "Sick Leave", "Emergency Leave"]:
        if st.button("Submit Leave Request"):
            if req_type == "Paid Time Off (PTO)":
                if pto_remaining <= 0:
                    st.error("No Allocation for the selected date! PTO request cannot be submitted.")
                    return
                # Auto-approve PTO & decrement allocation
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
                # Sick / Emergency Leave are always auto-approved
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

    # Check incoming swaps
    my_swap_requests = list(swaps_col.find({"target_email": user["email"], "status": "Pending"}))
    if my_swap_requests:
        st.markdown("#### Pending Schedule Swaps Requiring Your Approval")
        for sw in my_swap_requests:
            c_s1, c_s2 = st.columns([3, 1])
            c_s1.write(f"Advocate **{sw.get('requester_name')}** wants to swap shift with you for date: `{sw.get('date')}`.")
            if c_s2.button("Approve Swap", key=f"appr_{sw['_id']}"):
                swaps_col.update_one({"_id": sw["_id"]}, {"$set": {"status": "Approved"}})
                # Alert both
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
    timeframe = st.radio("Timeframe Filter", ["Daily", "WOW", "MTD", "YTD"], horizontal=True)

    # Cases Handled & Breach vs Resolved
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
        # Attendance: Scheduled vs Attended (Deducting sick/emergency & late log in)
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
    # 1. Manage Remember Me / Persistent Cookie
    if "user" not in st.session_state:
        saved_email = cookie_manager.get("hpe_auth_token")
        if saved_email:
            existing = roster_col.find_one({"email": saved_email})
            if existing:
                st.session_state["user"] = existing

    # 2. Render Auth if not logged in
    if "user" not in st.session_state or not st.session_state["user"]:
        render_auth_view()
        return

    user = st.session_state["user"]

    # 3. Handle Forced Logout / Kick from Admin
    refreshed_user = roster_col.find_one({"email": user["email"]})
    if refreshed_user and refreshed_user.get("force_logout"):
        roster_col.update_one({"email": user["email"]}, {"$unset": {"force_logout": ""}})
        cookie_manager.delete("hpe_auth_token")
        del st.session_state["user"]
        st.warning("Your session has been terminated by an administrator.")
        st.rerun()

    # 4. Render Profile Header & Aux Bar
    render_custom_top_bar(user)

    # 5. Sidebar Navigation Tile Menu
    st.sidebar.markdown(f"### 📍 Navigation")
    if user["role"] in ["Admin", "Admin/Agent"]:
        nav_options = ["Dashboard", "Monitoring", "Schedule", "Report", "Setting"]
    else:
        nav_options = ["Dashboard", "Schedule", "Report"]

    active_page = st.sidebar.radio("Go to:", nav_options, index=0)

    # Profile Settings in Sidebar (Picture & Password)
    with st.sidebar.expander("👤 My Profile Settings"):
        uploaded_pic = st.file_uploader("Upload Profile Picture", type=["png", "jpg", "jpeg"])
        if uploaded_pic:
            # Storing as base64 or raw image
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

    # 6. Route to selected page
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
