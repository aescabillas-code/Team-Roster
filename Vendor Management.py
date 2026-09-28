import streamlit as st
import pandas as pd
from datetime import datetime

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="HPE CaseFlow",
    page_icon="🟩",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# CUSTOM CSS
# ==========================================
st.markdown("""
<style>
    /* Main container padding */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 0rem;
    }
    
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Customizing the Sidebar */
    [data-testid="stSidebar"] {
        background-color: #1a2b3c;
    }
    [data-testid="stSidebar"] * {
        color: white !important;
    }
    
    /* Metric Card Styling */
    [data-testid="metric-container"] {
        background-color: #ffffff;
        border: 1px solid #e0e6ed;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# SESSION STATE MANAGEMENT
# ==========================================
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'current_page' not in st.session_state:
    st.session_state['current_page'] = "Dashboard"

# ==========================================
# MOCK DATA
# ==========================================
def get_case_data():
    data = {
        'Case #': ['HC-2026-1045', 'HC-2026-1044', 'HC-2026-1043', 'HC-2026-1042', 'HC-2026-1041', 'HC-2026-1040', 'HC-2026-1039'],
        'Subject': ['Portal Access Issue', 'License Renewal Delay', 'Installation Error', 'Vendor Confirmation', 'Software Licensing', 'Portal Access Request', 'Account Escalation'],
        'Priority': ['Critical', 'Critical', 'High', 'High', 'Medium', 'Medium', 'Low'],
        'Assignee': ['Maria Santos', 'John Dela Cruz', 'Kevin Ramos', 'Liza Garcia', 'Mark Tan', 'Christine Reyes', 'James Lim'],
        'Due Date': ['Sep 28, 2026 10:30 AM', 'Sep 28, 2026 11:00 AM', 'Sep 28, 2026 02:00 PM', 'Sep 28, 2026 04:00 PM', 'Sep 29, 2026 10:00 PM', 'Sep 29, 2026 03:00 PM', 'Sep 30, 2026 11:00 AM'],
        'Status': ['In Progress', 'On Hold', 'In Progress', 'Open', 'In Progress', 'Open', 'In Progress'],
        'Last Update': ['Sep 28, 08:15 AM', 'Sep 28, 08:45 AM', 'Sep 28, 09:00 AM', 'Sep 28, 08:55 AM', 'Sep 28, 08:20 AM', 'Sep 28, 09:10 AM', 'Sep 28, 08:40 AM'],
        'Hours': ['1.2h', '0.7h', '0.5h', '0.6h', '2.1h', '0.3h', '1.0h']
    }
    return pd.DataFrame(data)

def get_report_data():
    data = {
        'Date Resolved': ['Sep 28, 2026 10:15 AM', 'Sep 27, 2026 03:42 PM', 'Sep 26, 2026 11:03 AM', 'Sep 25, 2026 04:27 PM', 'Sep 24, 2026 02:10 PM'],
        'Case #': ['CAS-20260928-001', 'CAS-20260927-017', 'CAS-20260926-009', 'CAS-20260925-021', 'CAS-20260924-006'],
        'Subject': ['License Activation Issue', 'Portal Access Request', 'Software Renewal Inquiry', 'Entitlement Verification', 'Contract Delivery Delay'],
        'Priority': ['Critical', 'High', 'Medium', 'High', 'Critical'],
        'Status': ['Resolved', 'Resolved', 'Resolved', 'Resolved', 'Breached'],
        'Resolution Time': ['8.2 hrs', '14.5 hrs', '10.1 hrs', '16.3 hrs', '28.4 hrs'],
        'Breach': ['No', 'No', 'No', 'No', 'Yes']
    }
    return pd.DataFrame(data)

def get_vendor_data():
    data = {
        'Vendor Name': ['Tech Solutions Inc.', 'Global Systems Ltd.', 'CloudServe Corp.', 'NetConnect', 'DataPro Solutions'],
        'Contact Person': ['Mark Reynolds', 'Angela White', 'Daniel Kim', 'Sophia Lee', 'Michael Torres'],
        'Email': ['mark.reynolds@techsolutions.com', 'angela.white@globalsystems.com', 'daniel.kim@cloudserve.com', 'sophia.lee@netconnect.com', 'michael.torres@datapro.com'],
        'Phone': ['+1 555 123 4567', '+1 555 234 5678', '+1 555 345 6789', '+1 555 456 7890', '+1 555 567 8901'],
        'Category': ['Software', 'Hardware', 'Cloud Services', 'Network', 'Data Management'],
        'Status': ['🟢 Active', '🟢 Active', '🟢 Active', '🟢 Active', '🟢 Active'],
        'Last Updated': ['Sep 28, 2026 09:10 AM', 'Sep 28, 2026 09:10 AM', 'Sep 28, 2026 09:10 AM', 'Sep 28, 2026 09:10 AM', 'Sep 28, 2026 09:10 AM']
    }
    return pd.DataFrame(data)

# ==========================================
# VIEWS
# ==========================================

def login_view():
    st.markdown("<h1 style='text-align: center; color: #01a982;'>HPE CaseFlow</h1>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.markdown("### Welcome Back!")
        st.write("Sign in to your HPE CaseFlow account")
        
        with st.form("login_form"):
            st.text_input("HPE Email Address", placeholder="yourname@hpe.com")
            st.text_input("Password", type="password", placeholder="Enter your password")
            st.checkbox("Remember me")
            
            submitted = st.form_submit_button("Sign In", use_container_width=True)
            if submitted:
                st.session_state['logged_in'] = True
                st.rerun()
                
        st.write("--- or ---")
        st.button("Sign in with Microsoft (HPE)", use_container_width=True)

def dashboard_view():
    st.title("Dashboard")
    st.write("Welcome back, Arianne! Here's what's happening with your team today.")

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.metric(label="📁 Active Cases", value="124", delta="12% from yesterday")
    with kpi2:
        st.metric(label="⚠️ Critical", value="12", delta="-3 new", delta_color="inverse")
    with kpi3:
        st.metric(label="⏱️ Due Soon", value="28", delta="-5 new", delta_color="inverse")
    with kpi4:
        st.metric(label="✅ On Track", value="84", delta="4 new")

    st.write("---")

    main_col1, main_col2 = st.columns([3, 1])
    
    with main_col1:
        st.markdown("#### Active Cases (124)")
        
        f_col1, f_col2, f_col3, f_col4 = st.columns([2, 1, 1, 1])
        with f_col1:
             st.text_input("Filter", placeholder="Search by case #, subject...", label_visibility="collapsed")
        with f_col2:
             st.selectbox("Priority", ["All Priority", "Critical", "High", "Medium", "Low"], label_visibility="collapsed")
        with f_col3:
             st.selectbox("Status", ["All Status", "Open", "In Progress", "On Hold"], label_visibility="collapsed")
        with f_col4:
             st.selectbox("Assignee", ["All Assignees", "Maria", "John", "Kevin"], label_visibility="collapsed")
        
        df = get_case_data()
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Priority": st.column_config.TextColumn("Priority"),
                "Status": st.column_config.TextColumn("Status"),
            }
        )

    with main_col2:
        st.markdown("#### Agents Online (12)")
        st.text_input("Agent search", placeholder="🔍 Search agent...", label_visibility="collapsed")
        
        agents = [
            ("Maria Santos", "🟢 Available", "4"),
            ("John Dela Cruz", "🟢 Available", "3"),
            ("Liza Garcia", "🟡 Coaching", "1"),
            ("Mark Tan", "🟣 Meeting", "2"),
            ("Christine Reyes", "🟢 Available", "3"),
            ("James Lim", "🔴 Not Ready", "0")
        ]
        
        for name, status, cases in agents:
            st.markdown(f"**{name}**  \n{status} &nbsp;&nbsp;&nbsp;&nbsp; *(Cases: {cases})*")
            st.write("---")

def schedule_view():
    st.title("Schedule")
    st.write("Manage PTO allocation, leaves, and daily schedules")

    # Placeholder for the complex calendar and schedule components
    st.info("Calendar and Detailed Schedule Assignment View")
    st.image("1000057257.png") # Optional: Display the image to show what it should look like[cite: 11]

def report_view():
    st.title("Report")
    st.write("View your performance, attendance and adherence reports.")

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.metric(label="Total Cases Handled", value="48", delta="12% vs last month (43)")
    with kpi2:
        st.metric(label="Resolved Cases", value="41", delta="85.4% Resolution Rate")
    with kpi3:
        st.metric(label="Contract Breach", value="2", delta="-4.2% of total cases", delta_color="inverse")
    with kpi4:
        st.metric(label="Average Resolution Time", value="12.5 hrs", delta="-18% vs last month (15.2 hrs)", delta_color="inverse")
    
    st.write("---")
    
    st.markdown("#### Case Details")
    df = get_report_data()
    st.dataframe(df, use_container_width=True, hide_index=True)

def settings_view():
    st.title("Settings")
    st.write("Manage users, roles, external data and system configurations")

    tab1, tab2, tab3, tab4 = st.tabs(["Team Management", "External Sources", "Vendor Management", "System Configuration"])

    with tab2:
        st.markdown("### External Data Sources")
        st.write("Manage and synchronize external data used in the system")

        col1, col2 = st.columns(2)
        with col1:
            st.info("Vendor Data\n\n🟢 Connected - Last Sync: Sep 28, 2026 09:25 AM")
            st.info("Validation Dropdown\n\n🟢 Connected - Last Sync: Sep 28, 2026 07:40 AM")
        with col2:
            st.info("Case Import\n\n🟢 Connected - Last Sync: Sep 28, 2026 08:15 AM")
            st.info("Holiday Calendar\n\n🟢 Connected - Last Sync: Sep 28, 2026 06:30 AM")

        st.markdown("#### Data Preview")
        st.dataframe(get_vendor_data(), use_container_width=True, hide_index=True)


# ==========================================
# MAIN APP STRUCTURE
# ==========================================

if __name__ == "__main__":
    if not st.session_state['logged_in']:
        login_view()
    else:
        # --- Top Navbar Area ---
        top_col1, top_col2, top_col3 = st.columns([2, 4, 2])
        with top_col2:
            st.text_input("Search", placeholder="🔍 Search cases, agents, vendors, issues...", label_visibility="collapsed")
        with top_col3:
            st.write("**Arianne Escabillas**")
            st.write("🟢 Available | Admin/Agent")
            if st.button("Sign Out"):
                st.session_state['logged_in'] = False
                st.rerun()

        # --- Sidebar ---
        with st.sidebar:
            st.markdown("### 🟩 HPE CaseFlow")
            st.markdown("Task and Case Management System")
            st.write("---")
            
            # Update current page based on radio button selection
            page_selection = st.radio("Navigation", ["Dashboard", "Monitoring", "Schedule", "Report", "Settings"], label_visibility="collapsed")
            st.session_state['current_page'] = page_selection

        # --- Page Routing ---
        if st.session_state['current_page'] == "Dashboard":
            dashboard_view()
        elif st.session_state['current_page'] == "Monitoring":
            st.title("Monitoring")
            st.write("View all logged in agents, their real-time status and activities.")
            st.info("Monitoring View Placeholder")
        elif st.session_state['current_page'] == "Schedule":
            schedule_view()
        elif st.session_state['current_page'] == "Report":
            report_view()
        elif st.session_state['current_page'] == "Settings":
            settings_view()
