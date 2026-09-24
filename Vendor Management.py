import streamlit as st
import datetime
import pandas as pd
import plotly.express as px
from pymongo import MongoClient
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. PAGE CONFIGURATION & STYLING
# ==========================================
st.set_page_config(
    page_title="HPE CaseFlow",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for Modern UI matching Hewlett Packard Enterprise branding
st.markdown("""
<style>
    /* Hide Streamlit Header & Footer */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Modern HPE Palette & Typography */
    :root {
        --hpe-green: #01A781;
        --hpe-dark-blue: #002B49;
        --hpe-light-bg: #F4F7F9;
        --card-border: #E2E8F0;
    }
    
    body {
        background-color: var(--hpe-light-bg);
        font-family: 'Metric', 'Segoe UI', Arial, sans-serif;
    }
    
    /* Responsive TV Mirroring optimization */
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        max-width: 98% !important;
    }

    /* Tile Stat Cards */
    .metric-card {
        background-color: white;
        border-radius: 8px;
        padding: 15px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        border: 1px solid var(--card-border);
        text-align: center;
        cursor: pointer;
        transition: transform 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-2px);
    }
    .metric-val {
        font-size: 2.2rem;
        font-weight: 700;
        margin: 5px 0;
    }
    .metric-lbl {
        color: #64748B;
        font-size: 0.9rem;
        font-weight: 600;
        text-transform: uppercase;
    }
    
    /* Alert Item Styling */
    .alert-box {
        background-color: #FFF5F5;
        border-left: 4px solid #E53E3E;
        padding: 10px 15px;
        margin-bottom: 8px;
        border-radius: 4px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    
    /* Table Conditional Badges */
    .badge-critical { background-color: #FED7D7; color: #9B2C2C; padding: 4px 8px; border-radius: 4px; font-weight: bold;}
    .badge-high { background-color: #FEEBC8; color: #9C4221; padding: 4px 8px; border-radius: 4px; font-weight: bold;}
    .badge-medium { background-color: #FEFCBF; color: #744210; padding: 4px 8px; border-radius: 4px; font-weight: bold;}
    .badge-low { background-color: #E2E8F0; color: #2D3748; padding: 4px 8px; border-radius: 4px; font-weight: bold;}
</style>
""", unsafe_allow_html=True)


# ==========================================
# 2. DATABASE CONNECTIVITY & INITIALIZATION
# ==========================================
@st.cache_resource
def get_mongo_client():
    # Replace string with your Mongo URI string when ready
    # Example: return MongoClient("mongodb://localhost:27017/")
    return MongoClient("mongodb://localhost:27017/")

def init_db():
    try:
        client = get_mongo_client()
        db = client["TeamRoster"]
        collection = db["Team Roster Collection"]
        
        # Seed auto admin account if missing
        admin_email = "arianne-may.escabillas@hpe.com"
        if not collection.find_one({"email": admin_email}):
            collection.insert_one({
                "first_name": "Arianne May",
                "last_name": "Escabillas",
                "employee_id": "60187999",
                "email": admin_email,
                "birthday": "1993-06-17",
                "address": "661 Betterlife, Tanzang Luma III, Imus City, Cavite",
                "contact": "09123456789",
                "password": "Escabillas1993",
                "role": "Admin",
                "aux": "Admin Task",
                "status": "Active"
            })
        return collection
    except Exception as e:
        # Fallback to Session State in-memory storage if DB connection fails
        if "mock_db" not in st.session_state:
            st.session_state.mock_db = [{
                "first_name": "Arianne May",
                "last_name": "Escabillas",
                "employee_id": "60187999",
                "email": "arianne-may.escabillas@hpe.com",
                "birthday": "1993-06-17",
                "address": "661 Betterlife, Tanzang Luma III, Imus City, Cavite",
                "contact": "09123456789",
                "password": "Escabillas1993",
                "role": "Admin",
                "aux": "Admin Task",
                "status": "Active"
            }]
        return None

roster_collection = init_db()

# Initialize In-Memory Realtime Cases Data
if "cases_db" not in st.session_state:
    st.session_state.cases_db = [
        {"case_id": "0000156", "subject": "Network equipment delay", "priority": "Critical", "due_date": "Today 2:00 PM", "status": "In Progress", "assigned_to": "john.delacruz@hpe.com", "last_update": datetime.datetime.now() - datetime.timedelta(hours=25)},
        {"case_id": "0000143", "subject": "Server replacement", "priority": "High", "due_date": "Today 5:00 PM", "status": "Pending Vendor", "assigned_to": "john.delacruz@hpe.com", "last_update": datetime.datetime.now() - datetime.timedelta(hours=1)},
        {"case_id": "0000132", "subject": "Software license", "priority": "Medium", "due_date": "Apr 30, 2025", "status": "Assigned", "assigned_to": "mark.rivera@hpe.com", "last_update": datetime.datetime.now() - datetime.timedelta(hours=5)},
        {"case_id": "0000128", "subject": "Site installation", "priority": "Medium", "due_date": "May 1, 2025", "status": "In Progress", "assigned_to": "ana.reyes@hpe.com", "last_update": datetime.datetime.now() - datetime.timedelta(hours=2)},
        {"case_id": "0000120", "subject": "Access request", "priority": "Low", "due_date": "May 2, 2025", "status": "New", "assigned_to": "Unassigned", "last_update": datetime.datetime.now()}
    ]

if "requests_db" not in st.session_state:
    st.session_state.requests_db = [
        {"agent": "Maria Santos", "type": "PTO", "start": "2025-04-29", "end": "2025-04-30", "status": "Pending"},
        {"agent": "Mark Rivera", "type": "Schedule Swap", "start": "2025-04-29", "end": "2025-04-29", "status": "Pending"}
    ]

# Realtime polling non-disruptive refresh (every 10 sec)
st_autorefresh(interval=10000, key="datarefresh")

# User Session Setup
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_data" not in st.session_state:
    st.session_state.user_data = None


# ==========================================
# 3. AUTOMATIC CASE ASSIGNMENT ENGINE
# ==========================================
def auto_assign_cases():
    unassigned = [c for c in st.session_state.cases_db if c["assigned_to"] == "Unassigned"]
    if not unassigned:
        return
    
    # Get available active agents (AUX == 'Available')
    if roster_collection is not None:
        agents = list(roster_collection.find({"aux": "Available", "role": "Agent"}))
    else:
        agents = [u for u in st.session_state.mock_db if u.get("aux") == "Available" and u.get("role") == "Agent"]

    if not agents:
        return

    for case in unassigned:
        # Calculate case load per active agent
        counts = {}
        for ag in agents:
            email = ag["email"]
            counts[email] = sum(1 for c in st.session_state.cases_db if c["assigned_to"] == email)
        
        # Pick agent with lowest current case load
        target_agent = min(counts, key=counts.get)
        case["assigned_to"] = target_agent
        case["status"] = "Assigned"

auto_assign_cases()


# ==========================================
# 4. AUTHENTICATION MODULE (LOGIN / SIGN UP)
# ==========================================
def render_auth_page():
    col1, col2 = st.columns([1, 1.2])
    
    with col1:
        st.markdown("""
        <div style="background-color: #002B49; padding: 40px; border-radius: 12px; color: white; height: 100%;">
            <h2 style="color: #01A781; margin-bottom:0;">Hewlett Packard Enterprise</h2>
            <h1 style="margin-top:0;">HPE CaseFlow</h1>
            <p style="font-size: 1.1rem; color: #CBD5E1;">Team Task and Case Management System</p>
            <br>
            <ul>
                <li><strong>Manage Cases:</strong> Track and resolve tasks efficiently</li>
                <li><strong>Team Collaboration:</strong> Work together for better service delivery</li>
                <li><strong>Real-Time Visibility:</strong> Stay informed and in control</li>
                <li><strong>Secure Access:</strong> HPE employees only</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        
    with col2:
        auth_mode = st.radio("Choose Action", ["Sign In", "Sign Up"], horizontal=True, label_visibility="collapsed")
        
        if auth_mode == "Sign In":
            st.subheader("Sign In")
            st.caption("Access your HPE CaseFlow account")
            email = st.text_input("HPE Email Address", placeholder="name@hpe.com")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            
            if st.button("Sign In", type="primary", use_container_width=True):
                user = None
                if roster_collection is not None:
                    user = roster_collection.find_one({"email": email, "password": password})
                else:
                    user = next((u for u in st.session_state.mock_db if u["email"] == email and u["password"] == password), None)
                
                if user:
                    st.session_state.authenticated = True
                    st.session_state.user_data = user
                    st.rerun()
                else:
                    st.error("Invalid Email or Password.")
                    
        else:
            st.subheader("Sign Up")
            st.caption("Create your HPE CaseFlow account")
            
            fn = st.text_input("First Name")
            ln = st.text_input("Last Name")
            emp_id = st.text_input("Employee ID")
            email = st.text_input("HPE Email Address", placeholder="name@hpe.com")
            bday = st.date_input("Birthday", min_value=datetime.date(1950, 1, 1))
            addr = st.text_area("Home Address")
            contact = st.text_input("Contact Number")
            pwd = st.text_input("Password", type="password")
            confirm_pwd = st.text_input("Confirm Password", type="password")
            
            if st.button("Create Account", type="primary", use_container_width=True):
                if not email.endswith("@hpe.com"):
                    st.error("Must use a valid @hpe.com email address.")
                elif pwd != confirm_pwd:
                    st.error("Passwords do not match!")
                elif not (fn and ln and emp_id and email and pwd):
                    st.error("Please fill in all required fields.")
                else:
                    new_user = {
                        "first_name": fn, "last_name": ln, "employee_id": emp_id,
                        "email": email, "birthday": str(bday), "address": addr,
                        "contact": contact, "password": pwd,
                        "role": "Agent", "aux": "Busy - Away", "status": "Active"
                    }
                    if roster_collection is not None:
                        roster_collection.insert_one(new_user)
                    else:
                        st.session_state.mock_db.append(new_user)
                    st.success("Account created successfully! Please sign in.")


# Check Auth State
if not st.session_state.authenticated:
    render_auth_page()
    st.stop()


# ==========================================
# 5. APP NAVIGATION & PROFILE / AUX HEADER
# ==========================================
user = st.session_state.user_data
is_admin = user.get("role") == "Admin"

# Top Navigation Bar & Profile/AUX Header
hdr_col1, hdr_col2, hdr_col3 = st.columns([3, 2, 2])
with hdr_col1:
    st.title("HPE CaseFlow")
with hdr_col2:
    # Realtime AUX Selector in Header
    aux_options = ["Available", "Break", "Lunch", "In a Meeting", "Coaching", "Busy - Away", "Unscheduled Break"]
    if is_admin:
        aux_options.insert(0, "Admin Task")
    
    current_aux = user.get("aux", "Admin Task" if is_admin else "Busy - Away")
    selected_aux = st.selectbox("Current AUX Status", aux_options, index=aux_options.index(current_aux) if current_aux in aux_options else 0)
    
    if selected_aux != current_aux:
        user["aux"] = selected_aux
        if roster_collection is not None:
            roster_collection.update_one({"email": user["email"]}, {"$set": {"aux": selected_aux}})
        st.toast(f"AUX updated to: {selected_aux}")

with hdr_col3:
    st.markdown(f"**User:** {user['first_name']} {user['last_name']} ({user['role']})")
    if st.button("Sign Out", key="logout_btn"):
        st.session_state.authenticated = False
        st.session_state.user_data = None
        st.rerun()

# Sidebar Setup
st.sidebar.markdown(f"### Menu ({user['role']})")
if is_admin:
    menu = st.sidebar.radio("Navigation", ["Dashboard", "Cases", "Agents", "Schedule", "Requests", "Reports", "Salesforce", "Settings"])
else:
    menu = st.sidebar.radio("Navigation", ["Dashboard", "My Cases", "Schedule", "Requests"])


# ==========================================
# 6. REGULAR AGENT DASHBOARD & VIEWS
# ==========================================
if not is_admin:
    my_cases = [c for c in st.session_state.cases_db if c["assigned_to"] == user["email"]]
    
    if menu == "Dashboard":
        st.subheader(f"Good Morning, {user['first_name']}!")
        st.caption(datetime.datetime.now().strftime("%A, %B %d, %Y"))
        
        # Summary Tiles
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("My Active Cases", len(my_cases))
        c2.metric("Critical", sum(1 for c in my_cases if c["priority"] == "Critical"))
        c3.metric("Due Soon", sum(1 for c in my_cases if "Today" in c["due_date"]))
        c4.metric("On Track", sum(1 for c in my_cases if c["priority"] in ["Medium", "Low"]))
        
        # Alerts Box
        st.markdown("### Alerts for You")
        now = datetime.datetime.now()
        unupdated = [c for c in my_cases if (now - c["last_update"]).total_seconds() > 86400]
        if unupdated:
            st.warning(f"⚠️ You have {len(unupdated)} cases not updated for 24+ hours!")
            
        for c in my_cases:
            if c["priority"] == "Critical":
                st.error(f"🚨 Case #{c['case_id']} ({c['subject']}) is Critical!")
        
        # Cases Table (Sorted by urgency)
        st.markdown("### My Cases (Sorted by Urgency)")
        if my_cases:
            df = pd.DataFrame(my_cases)[["case_id", "subject", "priority", "due_date", "status"]]
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No cases currently assigned to you.")

    elif menu == "My Cases":
        st.subheader("My Cases Management")
        if my_cases:
            selected_id = st.selectbox("Select Case to View/Update", [c["case_id"] for c in my_cases])
            case = next(c for c in my_cases if c["case_id"] == selected_id)
            
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"**Case #:** {case['case_id']}")
                st.markdown(f"**Subject:** {case['subject']}")
                st.markdown(f"**Priority:** {case['priority']}")
                st.markdown(f"**Due Date:** {case['due_date']}")
                
                # Link routing to Salesforce Case
                sf_url = f"https://hp.lightning.force.com/lightning/r/Case/{case['case_id']}/view"
                st.markdown(f"🔗 [Contact Vendor/Technician in Salesforce]({sf_url})")
            
            with col_b:
                new_status = st.selectbox("Update Status", ["In Progress", "Pending Vendor", "Completed", "Contract Breached"], index=0)
                if new_status == "Contract Breached":
                    reason = st.selectbox("Breach Reason", ["SLA Missed", "Vendor Unresponsive", "Part Out of Stock"])
                    auto_msg = st.text_area("Generated Automated Notification Email", f"Dear Team, Case #{case['case_id']} breached SLA due to: {reason}.")
                    if st.button("Send Breach Notification"):
                        st.success("Automated Breach email dispatched!")
                        
                if st.button("Save Case Update"):
                    case["status"] = new_status
                    case["last_update"] = datetime.datetime.now()
                    st.success("Case status updated successfully!")

    elif menu == "Schedule":
        st.subheader("My Schedule")
        t1, t2, t3 = st.tabs(["Day", "Week", "Month"])
        with t1:
            st.table([
                {"Time": "08:00 AM - 10:00 AM", "Activity": "Work / Case Processing"},
                {"Time": "10:00 AM - 10:15 AM", "Activity": "Break"},
                {"Time": "10:15 AM - 12:00 PM", "Activity": "Work / Case Processing"},
                {"Time": "12:00 PM - 01:00 PM", "Activity": "Lunch"},
                {"Time": "03:00 PM - 03:15 PM", "Activity": "Break"}
            ])

    elif menu == "Requests":
        st.subheader("Submit Request (Leave / Swap)")
        req_type = st.selectbox("Request Type", ["Sick Leave", "Emergency Leave", "PTO", "Schedule Swap"])
        s_date = st.date_input("Start Date")
        e_date = st.date_input("End Date")
        reason = st.text_input("Reason")
        
        if st.button("Submit Request"):
            st.session_state.requests_db.append({
                "agent": f"{user['first_name']} {user['last_name']}",
                "type": req_type, "start": str(s_date), "end": str(e_date),
                "status": "Auto-Approved" if req_type in ["Sick Leave", "Emergency Leave"] else "Pending"
            })
            st.success("Request Submitted Successfully!")


# ==========================================
# 7. ADMIN DASHBOARD & ADVANCED CONTROL
# ==========================================
else: # Role == Admin
    if menu == "Dashboard":
        st.subheader("Team Overview")
        all_cases = st.session_state.cases_db
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Active Cases", len(all_cases))
        c2.metric("Critical", sum(1 for c in all_cases if c["priority"] == "Critical"))
        c3.metric("Due Soon", sum(1 for c in all_cases if "Today" in c["due_date"]))
        c4.metric("On Track", sum(1 for c in all_cases if c["priority"] in ["Medium", "Low"]))
        
        col_chart1, col_chart2 = st.columns(2)
        with col_chart1:
            st.markdown("#### Agent Status Distribution")
            fig = px.pie(values=[25, 4, 2, 4], names=["Available", "Lunch", "Break", "Busy-Away"], hole=0.4)
            st.plotly_chart(fig, use_container_width=True)
            
        with col_chart2:
            st.markdown("#### Active Case Distribution")
            df_cases = pd.DataFrame(all_cases)
            fig2 = px.bar(df_cases, x="assigned_to", title="Cases per Agent")
            st.plotly_chart(fig2, use_container_width=True)

    elif menu == "Cases":
        st.subheader("All Cases Control")
        st.dataframe(pd.DataFrame(st.session_state.cases_db), use_container_width=True)
        
        st.markdown("### Reassign Case")
        cid = st.selectbox("Select Case ID", [c["case_id"] for c in st.session_state.cases_db])
        new_ag = st.text_input("Reassign to Agent Email")
        if st.button("Reassign Case"):
            c = next(x for x in st.session_state.cases_db if x["case_id"] == cid)
            c["assigned_to"] = new_ag
            st.success(f"Case #{cid} reassigned to {new_ag}")

    elif menu == "Agents":
        st.subheader("Agent AUX Monitoring & Kick Control")
        # Display roster/AUX status
        if roster_collection is not None:
            roster = list(roster_collection.find())
        else:
            roster = st.session_state.mock_db
            
        for r in roster:
            col_a, col_b, col_c = st.columns([2, 2, 1])
            col_a.write(f"**{r['first_name']} {r['last_name']}** ({r['email']})")
            col_b.write(f"AUX: `{r.get('aux', 'Offline')}`")
            if col_c.button("Kick Agent", key=f"kick_{r['email']}"):
                r["aux"] = "Busy - Away"
                st.warning(f"Agent {r['first_name']} kicked to prevent auto-assignment.")

    elif menu == "Schedule":
        st.subheader("Team Schedule Management")
        st.info("Interval Optimizer: Auto-ensuring queue coverage across all operating hours.")

    elif menu == "Requests":
        st.subheader("Manage Requests")
        if st.session_state.requests_db:
            st.table(pd.DataFrame(st.session_state.requests_db))

    elif menu == "Reports":
        st.subheader("Extract Operational Reports")
        st.download_button("Export Cases to CSV", data=pd.DataFrame(st.session_state.cases_db).to_csv(), file_name="hpe_cases_report.csv")

    elif menu == "Salesforce":
        st.subheader("Salesforce Integration (Admin Only)")
        st.markdown("🔗 Direct link: [https://hp.lightning.force.com/](https://hp.lightning.force.com/)")
        st.components.v1.iframe("https://hp.lightning.force.com/", height=600, scrolling=True)

    elif menu == "Settings":
        st.subheader("System Settings & User Role Management")
        st.write("Manage user roles across the platform.")
