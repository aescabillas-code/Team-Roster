import datetime
import json
import random
import time
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# ==========================================
# PAGE CONFIGURATION & CUSTOM CSS INJECTION
# ==========================================
st.set_page_config(
    page_title="HPE | OVR-VW - Operations Visibility & Response Workspace",
    page_icon="🟢",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Custom CSS matching exact HPE Teal / Modern Web Theme & Styling
st.markdown(
    """
<style>
    /* Hide Streamlit elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {
        padding-top: 1rem;
        padding-bottom: 2rem;
        padding-left: 2rem;
        padding-right: 2rem;
        max-width: 100% !important;
    }
    
    /* Global Fonts & Colors */
    body {
        font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
        background-color: #f4f7f9;
        color: #1a2b3c;
    }
    
    /* Top Header Bar */
    .top-bar {
        background: linear-gradient(135deg, #005f73 0%, #00a896 100%);
        color: white;
        padding: 12px 24px;
        border-radius: 8px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 16px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.07);
    }
    
    /* Station Metric Cards Styling */
    .metric-card-container {
        display: flex;
        gap: 12px;
        margin-bottom: 20px;
    }
    .metric-card {
        flex: 1;
        border-radius: 10px;
        background: #ffffff;
        border: 1px solid #e2e8f0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.04);
        padding: 14px 16px;
        transition: transform 0.2s, box-shadow 0.2s;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 10px rgba(0,0,0,0.08);
    }
    .metric-card-care { border-top: 4px solid #ff4d6d; }
    .metric-card-arch { border-top: 4px solid #0077b6; }
    .metric-card-pet { border-top: 4px solid #2b9348; }
    .metric-card-sc { border-top: 4px solid #7209b7; }
    .metric-card-ful { border-top: 4px solid #e0a96d; }

    /* Custom Badge Styles */
    .badge {
        padding: 4px 10px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.75rem;
        display: inline-block;
        text-align: center;
    }
    /* Stations */
    .st-care { background-color: #ffe5ec; color: #d90429; }
    .st-arch { background-color: #e0f2fe; color: #0369a1; }
    .st-pet { background-color: #dcfce7; color: #15803d; }
    .st-sc { background-color: #f3e8ff; color: #6b21a8; }
    .st-ful { background-color: #fef3c7; color: #b45309; }
    
    /* Priorities */
    .pr-critical { background-color: #ff4d6d; color: white; }
    .pr-high { background-color: #ffccd5; color: #c9184a; }
    .pr-medium { background-color: #fef3c7; color: #b45309; }
    .pr-low { background-color: #dcfce7; color: #15803d; }
    
    /* Statuses */
    .st-in-progress { background-color: #e0f2fe; color: #0284c7; }
    .st-open { background-color: #f1f5f9; color: #475569; }
    .st-pending-internal { background-color: #f8fafc; color: #64748b; border: 1px dashed #cbd5e1; }
    .st-pending-customer { background-color: #fef2f2; color: #991b1b; }
    .st-resolved { background-color: #dcfce7; color: #166534; }
    .st-completed { background-color: #dbeafe; color: #1e40af; }
    .st-closed { background-color: #f3f4f6; color: #374151; }

    /* Modal Overlay Backdrop */
    .modal-backdrop {
        position: fixed;
        top: 0; left: 0; width: 100vw; height: 100vh;
        background: rgba(15, 23, 42, 0.65);
        backdrop-filter: blur(4px);
        z-index: 999990;
    }
    .custom-modal {
        position: fixed;
        top: 50%; left: 50%;
        transform: translate(-50%, -50%);
        width: 88vw;
        max-width: 1250px;
        height: 88vh;
        background: #ffffff;
        border-radius: 12px;
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.3), 0 10px 10px -5px rgba(0, 0, 0, 0.2);
        z-index: 999999;
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }
    
    /* SLA Status Icons */
    .sla-ok { color: #10b981; font-weight: bold; }
    .sla-warn { color: #f59e0b; font-weight: bold; }
    .sla-breach { color: #ef4444; font-weight: bold; }
</style>
""",
    unsafe_allow_html=True,
)

# ==========================================
# INITIALIZE SESSION STATE & MOCK DATA
# ==========================================
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Active Cases"

if "selected_case_id" not in st.session_state:
    st.session_state.selected_case_id = None

if "show_settings" not in st.session_state:
    st.session_state.show_settings = False

# Initial Active Cases Dataset
if "active_cases" not in st.session_state:
    st.session_state.active_cases = [
        {
            "case_number": "CAR-2026-0001",
            "subject": "Store network outage",
            "account": "H&M",
            "station": "CARE",
            "assignee": "Maria Santos",
            "priority": "CRITICAL",
            "status": "In Progress",
            "duration": "00:12:34",
            "sla": "warn",
            "sla_limit": "15 minutes",
            "vendor": "Aruba Networks",
            "issue_category": "Network Connectivity",
            "description": "Customer reported complete network outage at the downtown store. All POS systems and wireless access are unavailable. Requires immediate investigation and restoration.",
            "checklist": [
                {
                    "text": "Confirm the HPE/Aruba product, model and serial number.",
                    "completed": True,
                },
                {
                    "text": "Capture the exact alert, error message or customer symptom.",
                    "completed": True,
                },
                {
                    "text": "Complete the applicable remote/basic troubleshooting checks.",
                    "completed": True,
                },
                {
                    "text": "Verify support, entitlement or contract context when applicable.",
                    "completed": True,
                },
                {
                    "text": "Record customer contact, site and required reference information.",
                    "completed": False,
                },
                {
                    "text": "Document the assessment and recommended next action.",
                    "completed": False,
                },
            ],
            "history": [
                {
                    "dt": "Mar 11, 2026 10:24 AM",
                    "action": "Note Added",
                    "status": "In Progress",
                    "by": "Maria Santos",
                    "details": "Added note: Investigating switch logs with customer.",
                },
                {
                    "dt": "Mar 11, 2026 10:18 AM",
                    "action": "Checklist Item Completed",
                    "status": "In Progress",
                    "by": "Maria Santos",
                    "details": "Verified support, entitlement or contract context.",
                },
                {
                    "dt": "Mar 11, 2026 10:12 AM",
                    "action": "Priority Changed",
                    "status": "In Progress",
                    "by": "Maria Santos",
                    "details": "Priority changed from Medium to Critical.",
                },
                {
                    "dt": "Mar 11, 2026 10:05 AM",
                    "action": "Assignee Changed",
                    "status": "In Progress",
                    "by": "System",
                    "details": "Assignee changed from Unassigned to Maria Santos.",
                },
                {
                    "dt": "Mar 11, 2026 09:42 AM",
                    "action": "Status Updated",
                    "status": "Open",
                    "by": "Maria Santos",
                    "details": "Status changed from Open to In Progress.",
                },
                {
                    "dt": "Mar 11, 2026 09:20 AM",
                    "action": "Case Transferred",
                    "status": "In Progress",
                    "by": "James Li",
                    "details": "Case transferred to CARE.",
                },
                {
                    "dt": "Mar 11, 2026 08:45 AM",
                    "action": "Action Plan Updated",
                    "status": "Open",
                    "by": "James Li",
                    "details": "Initial action plan added.",
                },
                {
                    "dt": "Mar 11, 2026 08:15 AM",
                    "action": "Case Created",
                    "status": "Open",
                    "by": "Excel Import",
                    "details": "Case created from Excel import.",
                },
            ],
            "messages": [
                {
                    "user": "Maria Santos",
                    "time": "Mar 11, 2026 10:24 AM",
                    "role": "Operations",
                    "text": "Investigating network outage at the downtown store. Initial checks show no connectivity on POS and internal systems.",
                },
                {
                    "user": "James Li",
                    "time": "Mar 11, 2026 10:18 AM",
                    "role": "Network Team",
                    "text": "Checked the core switch logs. Multiple interface errors detected. Performing further analysis and validating VLAN configuration.",
                },
                {
                    "user": "Ravi Patel",
                    "time": "Mar 11, 2026 10:05 AM",
                    "role": "Vendor - Aruba",
                    "text": "Aruba TAC case opened (TAC-458921) for this issue. Collecting additional logs and configuration details. Will provide an update shortly.",
                },
                {
                    "user": "Maria Santos",
                    "time": "Mar 11, 2026 09:42 AM",
                    "role": "Operations",
                    "text": "Customer confirmed all store systems are down. No wireless access available. Requested immediate assistance.",
                },
                {
                    "user": "System",
                    "time": "Mar 11, 2026 08:15 AM",
                    "role": "System",
                    "text": "Case created via Excel import and assigned to Maria Santos.",
                },
            ],
            "attachments": [
                {
                    "name": "Network_Error_Screenshot.png",
                    "type": "Image",
                    "size": "1.2 MB",
                    "by": "Maria Santos",
                    "date": "Mar 11, 2026 10:18 AM",
                    "desc": "Screenshot of the POS error message encountered at the store.",
                },
                {
                    "name": "Switch_Log_031126.txt",
                    "type": "Text",
                    "size": "450 KB",
                    "by": "James Li",
                    "date": "Mar 11, 2026 10:12 AM",
                    "desc": "Core switch log output.",
                },
                {
                    "name": "Store_Topology_Diagram.pdf",
                    "type": "PDF",
                    "size": "2.4 MB",
                    "by": "Ravi Patel",
                    "date": "Mar 11, 2026 09:55 AM",
                    "desc": "Network topology for downtown store.",
                },
                {
                    "name": "Customer_Incident_Details.xlsx",
                    "type": "Excel",
                    "size": "320 KB",
                    "by": "Maria Santos",
                    "date": "Mar 11, 2026 09:42 AM",
                    "desc": "Detailed incident form from store manager.",
                },
                {
                    "name": "Aruba_Support_Response.msg",
                    "type": "Email",
                    "size": "1.1 MB",
                    "by": "James Li",
                    "date": "Mar 11, 2026 09:20 AM",
                    "desc": "TAC case confirmation email.",
                },
                {
                    "name": "Site_Photos.zip",
                    "type": "ZIP",
                    "size": "3.8 MB",
                    "by": "Maria Santos",
                    "date": "Mar 11, 2026 09:05 AM",
                    "desc": "Rack cabling photos.",
                },
                {
                    "name": "POS_Error_Log.txt",
                    "type": "Text",
                    "size": "280 KB",
                    "by": "System",
                    "date": "Mar 11, 2026 08:50 AM",
                    "desc": "Automated POS crash dump.",
                },
                {
                    "name": "Network_Test_Results.pdf",
                    "type": "PDF",
                    "size": "960 KB",
                    "by": "Ravi Patel",
                    "date": "Mar 11, 2026 08:35 AM",
                    "desc": "Ping and trace route log results.",
                },
            ],
        },
        {
            "case_number": "ARC-2026-0015",
            "subject": "Validation request",
            "account": "Global Retail",
            "station": "ARCH",
            "assignee": "James Li",
            "priority": "HIGH",
            "status": "Open",
            "duration": "00:18:20",
            "sla": "warn",
            "sla_limit": "30 minutes",
            "vendor": "HPE Systems",
            "issue_category": "Architecture Review",
            "description": "Validation request for new store deployment architecture.",
            "checklist": [],
            "history": [],
            "messages": [],
            "attachments": [],
        },
        {
            "case_number": "PET-2026-0078",
            "subject": "Access configuration",
            "account": "TechCorp",
            "station": "PET",
            "assignee": "Ravi Patel",
            "priority": "MEDIUM",
            "status": "In Progress",
            "duration": "00:25:10",
            "sla": "warn",
            "sla_limit": "45 minutes",
            "vendor": "Aruba Networks",
            "issue_category": "Security Access",
            "description": "Configuration of privilege elevation and access controls.",
            "checklist": [],
            "history": [],
            "messages": [],
            "attachments": [],
        },
        {
            "case_number": "SC-2026-0104",
            "subject": "Shipment delay",
            "account": "Acme Ltd",
            "station": "SUPPLY CHAIN",
            "assignee": "Ana Rodriguez",
            "priority": "LOW",
            "status": "Pending Internal",
            "duration": "01:05:32",
            "sla": "ok",
            "sla_limit": "30 minutes",
            "vendor": "Logistics Core",
            "issue_category": "Hardware Delivery",
            "description": "Custom switch component transit delay.",
            "checklist": [],
            "history": [],
            "messages": [],
            "attachments": [],
        },
        {
            "case_number": "FUL-2026-0022",
            "subject": "Stock update delay",
            "account": "Lazada",
            "station": "FULFILLMENT",
            "assignee": "Kevin Tan",
            "priority": "MEDIUM",
            "status": "In Progress",
            "duration": "02:15:45",
            "sla": "warn",
            "sla_limit": "120 minutes",
            "vendor": "Oracle",
            "issue_category": "System Performance",
            "description": "Stock synchronization delay from warehouse inventory.",
            "checklist": [],
            "history": [],
            "messages": [],
            "attachments": [],
        },
        {
            "case_number": "CAR-2026-0008",
            "subject": "Hardware not detected",
            "account": "RetailCo",
            "station": "CARE",
            "assignee": "Lisa Chen",
            "priority": "HIGH",
            "status": "Open",
            "duration": "00:09:12",
            "sla": "ok",
            "sla_limit": "15 minutes",
            "vendor": "Aruba Networks",
            "issue_category": "Hardware Fail",
            "description": "AP-515 node 2 missing on controller dashboard.",
            "checklist": [],
            "history": [],
            "messages": [],
            "attachments": [],
        },
        {
            "case_number": "ARC-2026-0013",
            "subject": "Portal access issue",
            "account": "Accenture",
            "station": "ARCH",
            "assignee": "James Li",
            "priority": "HIGH",
            "status": "Open",
            "duration": "00:28:51",
            "sla": "warn",
            "sla_limit": "30 minutes",
            "vendor": "Microsoft",
            "issue_category": "System Access",
            "description": "Azure tenant login authentication failure.",
            "checklist": [],
            "history": [],
            "messages": [],
            "attachments": [],
        },
        {
            "case_number": "PET-2026-0081",
            "subject": "Platform access issue",
            "account": "GreenField",
            "station": "PET",
            "assignee": "Sophie Tan",
            "priority": "LOW",
            "status": "Pending Customer",
            "duration": "00:12:18",
            "sla": "ok",
            "sla_limit": "45 minutes",
            "vendor": "HPE Cloud",
            "issue_category": "IAM",
            "description": "Customer unable to reset tenant admin password.",
            "checklist": [],
            "history": [],
            "messages": [],
            "attachments": [],
        },
        {
            "case_number": "SC-2026-0112",
            "subject": "Tracking information",
            "account": "Blue Ocean",
            "station": "SUPPLY CHAIN",
            "assignee": "Carlos Mendez",
            "priority": "MEDIUM",
            "status": "Open",
            "duration": "00:55:40",
            "sla": "warn",
            "sla_limit": "30 minutes",
            "vendor": "DHL Express",
            "issue_category": "Waybill",
            "description": "Waybill update missing for replacement router.",
            "checklist": [],
            "history": [],
            "messages": [],
            "attachments": [],
        },
        {
            "case_number": "FUL-2026-0034",
            "subject": "Site access request",
            "account": "Prime Retail",
            "station": "FULFILLMENT",
            "assignee": "Emma Wilson",
            "priority": "HIGH",
            "status": "In Progress",
            "duration": "01:42:15",
            "sla": "warn",
            "sla_limit": "120 minutes",
            "vendor": "Security Ops",
            "issue_category": "Badge Access",
            "description": "Technician badge clearance for data room access.",
            "checklist": [],
            "history": [],
            "messages": [],
            "attachments": [],
        },
    ]

# Initial Closed Cases Dataset
if "closed_cases" not in st.session_state:
    st.session_state.closed_cases = [
        {
            "case_number": "CAR-2026-0023",
            "subject": "Wireless connectivity issue",
            "account": "Global Retail",
            "station": "CARE",
            "assignee": "Maria Santos",
            "priority": "MEDIUM",
            "status": "Resolved",
            "closed_date": "Mar 10, 2026 16:22",
            "total_duration": "01:12:45",
        },
        {
            "case_number": "ARC-2026-0018",
            "subject": "Document verification",
            "account": "Summit Group",
            "station": "ARCH",
            "assignee": "James Li",
            "priority": "LOW",
            "status": "Completed",
            "closed_date": "Mar 10, 2026 14:05",
            "total_duration": "00:48:12",
        },
    ]


# Helper HTML Formatter Functions
def get_station_badge(station):
    mapping = {
        "CARE": '<span class="badge st-care">CARE</span>',
        "ARCH": '<span class="badge st-arch">ARCH</span>',
        "PET": '<span class="badge st-pet">PET</span>',
        "SUPPLY CHAIN": '<span class="badge st-sc">SUPPLY CHAIN</span>',
        "FULFILLMENT": '<span class="badge st-ful">FULFILLMENT</span>',
    }
    return mapping.get(station, f'<span class="badge">{station}</span>')


def get_priority_badge(priority):
    mapping = {
        "CRITICAL": '<span class="badge pr-critical">CRITICAL</span>',
        "HIGH": '<span class="badge pr-high">HIGH</span>',
        "MEDIUM": '<span class="badge pr-medium">MEDIUM</span>',
        "LOW": '<span class="badge pr-low">LOW</span>',
    }
    return mapping.get(priority, f'<span class="badge">{priority}</span>')


def get_status_badge(status):
    mapping = {
        "In Progress": '<span class="badge st-in-progress">In Progress</span>',
        "Open": '<span class="badge st-open">Open</span>',
        "Pending Internal": (
            '<span class="badge st-pending-internal">Pending Internal</span>'
        ),
        "Pending Customer": (
            '<span class="badge st-pending-customer">Pending Customer</span>'
        ),
        "Resolved": '<span class="badge st-resolved">Resolved</span>',
        "Completed": '<span class="badge st-completed">Completed</span>',
        "Closed": '<span class="badge st-closed">Closed</span>',
    }
    return mapping.get(status, f'<span class="badge">{status}</span>')


# ==========================================
# HEADER REGION
# ==========================================
hdr_col1, hdr_col2, hdr_col3 = st.columns([4, 6, 1])

with hdr_col1:
    st.markdown(
        """
        <div style="display: flex; align-items: center; gap: 15px;">
            <div style="background: #00b4d8; padding: 6px 12px; border-radius: 4px; font-weight: 900; color: white; font-size: 20px;">HPE</div>
            <div>
                <h2 style="margin: 0; padding: 0; color: #005f73; line-height: 1.1;">OVR-VW</h2>
                <span style="font-size: 13px; color: #64748b;">Operations Visibility & Response Workspace</span>
            </div>
        </div>
    """,
        unsafe_allow_html=True,
    )

with hdr_col2:
    search_query = st.text_input(
        "Global Search",
        placeholder="🔍 Search cases by number, subject, account, assignee...",
        label_visibility="collapsed",
    )

with hdr_col3:
    if st.button("⚙️ Settings", use_container_width=True):
        st.session_state.show_settings = True
        st.rerun()

st.markdown("<hr style='margin: 12px 0; border-color: #e2e8f0;'/>", unsafe_allow_html=True)

# ==========================================
# TOP TAB TOGGLE (ACTIVE VS CLOSED CASES)
# ==========================================
tab_col1, tab_col2, _ = st.columns([3, 3, 6])

with tab_col1:
    active_btn_type = (
        "primary" if st.session_state.active_tab == "Active Cases" else "secondary"
    )
    if st.button(
        "Active Cases\nCurrent operational queue",
        use_container_width=True,
        type=active_btn_type,
    ):
        st.session_state.active_tab = "Active Cases"
        st.rerun()

with tab_col2:
    closed_btn_type = (
        "primary" if st.session_state.active_tab == "Closed Cases" else "secondary"
    )
    if st.button(
        "Closed Cases\nResolved case history",
        use_container_width=True,
        type=closed_btn_type,
    ):
        st.session_state.active_tab = "Closed Cases"
        st.rerun()

st.markdown("<br/>", unsafe_allow_html=True)

# ==========================================
# METRIC CARDS REGION (DYNAMIC COUNTS)
# ==========================================
if st.session_state.active_tab == "Active Cases":
    cards_data = [
        {
            "name": "CARE",
            "count": len([c for c in st.session_state.active_cases if c["station"] == "CARE"]),
            "sla": "15 minutes",
            "class": "metric-card-care",
            "icon": "🎧",
        },
        {
            "name": "ARCH",
            "count": len([c for c in st.session_state.active_cases if c["station"] == "ARCH"]),
            "sla": "30 minutes",
            "class": "metric-card-arch",
            "icon": "📄",
        },
        {
            "name": "PET",
            "count": len([c for c in st.session_state.active_cases if c["station"] == "PET"]),
            "sla": "45 minutes",
            "class": "metric-card-pet",
            "icon": "⚙️",
        },
        {
            "name": "SUPPLY CHAIN",
            "count": len(
                [c for c in st.session_state.active_cases if c["station"] == "SUPPLY CHAIN"]
            ),
            "sla": "30 minutes",
            "class": "metric-card-sc",
            "icon": "🚚",
        },
        {
            "name": "FULFILLMENT",
            "count": len(
                [c for c in st.session_state.active_cases if c["station"] == "FULFILLMENT"]
            ),
            "sla": "120 minutes",
            "class": "metric-card-ful",
            "icon": "🔧",
        },
    ]
else:
    cards_data = [
        {
            "name": "CARE",
            "count": 42,
            "sla": "15 minutes",
            "class": "metric-card-care",
            "icon": "🎧",
        },
        {
            "name": "ARCH",
            "count": 38,
            "sla": "30 minutes",
            "class": "metric-card-arch",
            "icon": "📄",
        },
        {
            "name": "PET",
            "count": 27,
            "sla": "45 minutes",
            "class": "metric-card-pet",
            "icon": "⚙️",
        },
        {
            "name": "SUPPLY CHAIN",
            "count": 31,
            "sla": "30 minutes",
            "class": "metric-card-sc",
            "icon": "🚚",
        },
        {
            "name": "FULFILLMENT",
            "count": 26,
            "sla": "120 minutes",
            "class": "metric-card-ful",
            "icon": "🔧",
        },
    ]

m_cols = st.columns(5)
for i, card in enumerate(cards_data):
    with m_cols[i]:
        label_text = (
            "Active Cases"
            if st.session_state.active_tab == "Active Cases"
            else "Closed Cases"
        )
        st.markdown(
            f"""
            <div class="metric-card {card['class']}">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-size: 24px;">{card['icon']}</span>
                    <strong style="color: #475569;">{card['name']}</strong>
                </div>
                <div style="font-size: 32px; font-weight: 800; margin: 8px 0; color: #0f172a;">{card['count']}</div>
                <div style="font-size: 12px; color: #64748b;">{label_text}</div>
                <hr style="margin: 8px 0; border-color: #f1f5f9;"/>
                <div style="font-size: 11px; color: #64748b;">⏰ SLA <strong>{card['sla']}</strong></div>
            </div>
        """,
            unsafe_allow_html=True,
        )

st.markdown("<br/>", unsafe_allow_html=True)

# ==========================================
# ACTIVE CASES VIEW
# ==========================================
if st.session_state.active_tab == "Active Cases":
    st.subheader("Active Cases")
    st.caption("Live operational cases across all stations")

    filter_col1, filter_col2, filter_col3 = st.columns([6, 3, 3])
    with filter_col2:
        station_filter = st.selectbox(
            "Filter Station",
            [
                "All Stations",
                "CARE",
                "ARCH",
                "PET",
                "SUPPLY CHAIN",
                "FULFILLMENT",
            ],
            key="act_station_filter",
        )
    with filter_col3:
        st.markdown(
            """
            <div style='text-align: right; padding-top: 25px; font-size: 12px; color: #64748b;'>
                🔄 Last updated: Mar 11, 2026 10:24:12 AM
            </div>
        """,
            unsafe_allow_html=True,
        )

    # Filter cases
    filtered_cases = st.session_state.active_cases
    if station_filter != "All Stations":
        filtered_cases = [
            c for c in filtered_cases if c["station"] == station_filter
        ]
    if search_query:
        sq = search_query.lower()
        filtered_cases = [
            c
            for c in filtered_cases
            if sq in c["case_number"].lower()
            or sq in c["subject"].lower()
            or sq in c["account"].lower()
            or sq in c["assignee"].lower()
        ]

    # Render Table Headers
    t_head = st.columns([1.5, 2.5, 1.5, 1.2, 1.5, 1.2, 1.5, 1.2, 0.8, 1.2])
    t_head[0].markdown("**Case Number**")
    t_head[1].markdown("**Subject**")
    t_head[2].markdown("**Account**")
    t_head[3].markdown("**Station**")
    t_head[4].markdown("**Assignee**")
    t_head[5].markdown("**Priority**")
    t_head[6].markdown("**Status**")
    t_head[7].markdown("**Duration**")
    t_head[8].markdown("**SLA**")
    t_head[9].markdown("**Actions**")

    st.markdown("<hr style='margin: 4px 0;'/>", unsafe_allow_html=True)

    # Table Rows
    for idx, c in enumerate(filtered_cases):
        r_cols = st.columns([1.5, 2.5, 1.5, 1.2, 1.5, 1.2, 1.5, 1.2, 0.8, 1.2])

        if r_cols[0].button(
            c["case_number"], key=f"btn_case_{c['case_number']}_{idx}"
        ):
            st.session_state.selected_case_id = c["case_number"]
            st.rerun()

        r_cols[1].write(c["subject"])
        r_cols[2].write(c["account"])
        r_cols[3].markdown(
            get_station_badge(c["station"]), unsafe_allow_html=True
        )
        r_cols[4].write(c["assignee"])
        r_cols[5].markdown(
            get_priority_badge(c["priority"]), unsafe_allow_html=True
        )
        r_cols[6].markdown(
            get_status_badge(c["status"]), unsafe_allow_html=True
        )

        dur_color = "#ef4444" if c["sla"] == "breach" else "#000000"
        r_cols[7].markdown(
            f"<span style='color: {dur_color}; font-weight: 600;'>{c['duration']}</span>",
            unsafe_allow_html=True,
        )

        if c["sla"] == "breach":
            r_cols[8].markdown(
                "<span class='sla-breach'>🚨</span>", unsafe_allow_html=True
            )
        elif c["sla"] == "warn":
            r_cols[8].markdown(
                "<span class='sla-warn'>⚠️</span>", unsafe_allow_html=True
            )
        else:
            r_cols[8].markdown(
                "<span class='sla-ok'>✅</span>", unsafe_allow_html=True
            )

        if r_cols[9].button(
            "View", key=f"view_act_{c['case_number']}_{idx}"
        ):
            st.session_state.selected_case_id = c["case_number"]
            st.rerun()

        st.markdown(
            "<hr style='margin: 2px 0; border-color: #f1f5f9;'/>",
            unsafe_allow_html=True,
        )

# ==========================================
# CLOSED CASES VIEW
# ==========================================
else:
    st.subheader("Closed Cases")
    st.caption("Resolved, completed and closed cases")

    fc1, fc2, fc3, fc4 = st.columns([4, 2, 2, 2])
    with fc1:
        st.text_input(
            "Search closed cases",
            placeholder="🔍 Search closed cases...",
            label_visibility="collapsed",
        )
    with fc2:
        st.selectbox(
            "Date Filter",
            ["All Dates", "Today", "This Week", "This Month"],
            label_visibility="collapsed",
        )
    with fc3:
        st.selectbox(
            "Station Filter",
            [
                "All Stations",
                "CARE",
                "ARCH",
                "PET",
                "SUPPLY CHAIN",
                "FULFILLMENT",
            ],
            label_visibility="collapsed",
        )
    with fc4:
        st.selectbox(
            "Status Filter",
            ["All Statuses", "Resolved", "Completed", "Closed"],
            label_visibility="collapsed",
        )

    t_head = st.columns([1.5, 2.5, 1.5, 1.2, 1.5, 1.2, 1.5, 1.8, 1.2, 1.0])
    t_head[0].markdown("**Case Number**")
    t_head[1].markdown("**Subject**")
    t_head[2].markdown("**Account**")
    t_head[3].markdown("**Station**")
    t_head[4].markdown("**Assignee**")
    t_head[5].markdown("**Priority**")
    t_head[6].markdown("**Status**")
    t_head[7].markdown("**Closed Date**")
    t_head[8].markdown("**Total Duration**")
    t_head[9].markdown("**Actions**")

    st.markdown("<hr style='margin: 4px 0;'/>", unsafe_allow_html=True)

    for idx, c in enumerate(st.session_state.closed_cases):
        r_cols = st.columns([1.5, 2.5, 1.5, 1.2, 1.5, 1.2, 1.5, 1.8, 1.2, 1.0])
        r_cols[0].write(c["case_number"])
        r_cols[1].write(c["subject"])
        r_cols[2].write(c["account"])
        r_cols[3].markdown(
            get_station_badge(c["station"]), unsafe_allow_html=True
        )
        r_cols[4].write(c["assignee"])
        r_cols[5].markdown(
            get_priority_badge(c["priority"]), unsafe_allow_html=True
        )
        r_cols[6].markdown(
            get_status_badge(c["status"]), unsafe_allow_html=True
        )
        r_cols[7].write(c["closed_date"])
        r_cols[8].write(c["total_duration"])
        r_cols[9].button("View", key=f"view_closed_{idx}")
        st.markdown(
            "<hr style='margin: 2px 0; border-color: #f1f5f9;'/>",
            unsafe_allow_html=True,
        )

# ==========================================
# SETTINGS & CONFIGURATION MODAL WINDOW
# ==========================================
if st.session_state.show_settings:
    st.markdown(
        '<div class="modal-backdrop"></div>', unsafe_allow_html=True
    )

    with st.container():
        st.markdown(
            """
            <div style="background-color: #005f73; padding: 16px 24px; border-radius: 8px 8px 0 0; color: white;">
                <div style="font-size: 20px; font-weight: bold;">⚙️ Settings</div>
                <div style="font-size: 13px; opacity: 0.9;">Manage system configuration, data and preferences</div>
            </div>
        """,
            unsafe_allow_html=True,
        )

        st.markdown("<br/>", unsafe_allow_html=True)

        # Settings Tabs
        s_tab1, s_tab2, s_tab3, s_tab4, s_tab5 = st.tabs(
            [
                "⚙️ General",
                "🔔 Alert Management",
                "📤 Data Import",
                "📊 Export Data",
                "🎮 Simulation",
            ]
        )

        # SETTINGS TAB 1: GENERAL
        with s_tab1:
            sg_c1, sg_c2, sg_c3 = st.columns(3)
            with sg_c1:
                st.markdown("#### ℹ️ System Information")
                st.write("**Application Name:** OVR-VW")
                st.write("**Version:** 1.0.0")
                st.write("**Environment:** Production")
                st.write("**Database:** MongoDB (Vektor)")
                st.write("**Last Updated:** Mar 11, 2026 10:24 AM")
                st.write("**Maintained By:** Operations Team")

                st.markdown("---")
                st.markdown("#### ⚙️ Preferences")
                st.selectbox(
                    "Default View", ["Active Cases", "Closed Cases"]
                )
                st.selectbox("Cases Per Page", ["10", "25", "50", "100"])
                st.selectbox(
                    "Time Zone", ["Asia/Manila (GMT+8)", "UTC", "EST"]
                )
                st.toggle("Enable Audio Alerts", value=True)
                st.toggle("Show Case Notifications", value=True)

            with sg_c2:
                st.markdown("#### 🔔 Notification Settings")
                st.checkbox("New Case Assignment", value=True)
                st.checkbox("SLA Warning (Amber)", value=True)
                st.checkbox("SLA Breach (Red)", value=True)
                st.checkbox("Case Status Update", value=True)
                st.checkbox("Case Transfer", value=False)
                st.checkbox("Collaboration Messages", value=False)
                st.checkbox("Daily Summary", value=False)

                st.markdown("---")
                st.markdown("#### 💻 Display Settings")
                st.selectbox("Theme", ["Light (Default)", "Dark", "HPE Teal"])
                st.selectbox("Table Density", ["Compact", "Comfortable"])
                st.selectbox("Font Size", ["Medium (Default)", "Small", "Large"])

            with sg_c3:
                st.markdown("#### ⏰ SLA Settings")
                st.caption("Configure SLA thresholds per station")
                sla_table = pd.DataFrame(
                    [
                        {
                            "Station": "CARE",
                            "SLA (min)": 15,
                            "Warning (60%)": 9,
                            "Critical (80%)": 12,
                        },
                        {
                            "Station": "ARCH",
                            "SLA (min)": 30,
                            "Warning (60%)": 18,
                            "Critical (80%)": 24,
                        },
                        {
                            "Station": "PET",
                            "SLA (min)": 45,
                            "Warning (60%)": 27,
                            "Critical (80%)": 36,
                        },
                        {
                            "Station": "SUPPLY CHAIN",
                            "SLA (min)": 30,
                            "Warning (60%)": 18,
                            "Critical (80%)": 24,
                        },
                        {
                            "Station": "FULFILLMENT",
                            "SLA (min)": 120,
                            "Warning (60%)": 72,
                            "Critical (80%)": 96,
                        },
                    ]
                )
                st.dataframe(sla_table, use_container_width=True)

        # SETTINGS TAB 2: ALERT MANAGEMENT
        with s_tab2:
            sa_col1, sa_col2 = st.columns([6, 6])
            with sa_col1:
                st.markdown("#### 🔔 Alert Rules (10)")
                st.button("➕ Add Alert Rule", type="primary")
                alert_rules = [
                    {
                        "Rule": "SLA Warning (60%)",
                        "Trigger": "SLA at 60%",
                        "Color": "🟠",
                        "Status": "Active",
                    },
                    {
                        "Rule": "SLA Breach (80%)",
                        "Trigger": "SLA at 80%",
                        "Color": "🔴",
                        "Status": "Active",
                    },
                    {
                        "Rule": "New Case Assignment",
                        "Trigger": "New case assigned",
                        "Color": "🔵",
                        "Status": "Active",
                    },
                ]
                st.dataframe(
                    pd.DataFrame(alert_rules), use_container_width=True
                )

            with sa_col2:
                st.markdown("#### ✏️ Alert Details")
                st.text_input("Alert Name *", value="SLA Warning (60%)")
                st.text_area(
                    "Description",
                    value="Triggered when a case reaches 60% of the station SLA time.",
                )
                st.selectbox(
                    "Trigger Event *",
                    ["SLA at Percentage", "New Case", "Case Transfer"],
                )
                st.number_input("Threshold (%) *", value=60)
                st.selectbox("Alert Color *", ["Amber", "Red", "Blue", "Green"])
                if st.button("▶️ Send Test Alert"):
                    st.warning(
                        "⚠️ **SLA Warning (60%)**\nCase CAR-2026-0104 is approaching SLA."
                    )

        # SETTINGS TAB 3: DATA IMPORT (Exact match to image 1000059138.png)[cite: 11]
        with s_tab3:
            di_col1, di_col2 = st.columns([5, 7])
            with di_col1:
                st.markdown("#### 📤 Import Data")
                st.caption(
                    "Upload an Excel file to create or update cases, stations and reference data."
                )
                st.file_uploader(
                    "Drag and drop your Excel file here",
                    type=["xlsx", "xls"],
                    help="Maximum file size: 10 MB",
                )

                st.markdown("---")
                st.markdown("#### ⚙️ Import Options")
                st.radio(
                    "Record Handling",
                    [
                        "Create new records only (Skip records that already exist.)",
                        "Update existing records (Update matching records, create new if not found.)",
                        "Replace all records (Clear existing data and import new records.)",
                    ],
                    label_visibility="collapsed",
                )

                st.markdown("---")
                st.markdown("#### 📦 Data Type")
                st.checkbox(
                    "Cases (Import new cases and update existing cases.)",
                    value=True,
                )
                st.checkbox(
                    "Stations (Import station configuration.)", value=True
                )
                st.checkbox(
                    "Reference Data (Import accounts, vendors, departments, etc.)",
                    value=True,
                )

            with di_col2:
                map_hdr_c1, map_hdr_c2, map_hdr_c3 = st.columns([6, 3, 3])
                with map_hdr_c1:
                    st.markdown("#### 🔗 Field Mapping")
                    st.caption(
                        "Map columns from your Excel file to system fields."
                    )
                with map_hdr_c2:
                    st.button("🔄 Auto Map")
                with map_hdr_c3:
                    st.button("📥 Download Template")

                mapping_df = pd.DataFrame(
                    [
                        {
                            "Excel Column": "Case Number",
                            "Maps To (System Field)": "Case Number",
                            "Data Type": "Text",
                            "Required": False,
                        },
                        {
                            "Excel Column": "Subject",
                            "Maps To (System Field)": "Subject",
                            "Data Type": "Text",
                            "Required": True,
                        },
                        {
                            "Excel Column": "Account",
                            "Maps To (System Field)": "Account",
                            "Data Type": "Text",
                            "Required": True,
                        },
                        {
                            "Excel Column": "Vendor",
                            "Maps To (System Field)": "Vendor",
                            "Data Type": "Text",
                            "Required": False,
                        },
                        {
                            "Excel Column": "Issue Category",
                            "Maps To (System Field)": "Issue Category",
                            "Data Type": "Dropdown",
                            "Required": True,
                        },
                        {
                            "Excel Column": "Priority",
                            "Maps To (System Field)": "Priority",
                            "Data Type": "Dropdown",
                            "Required": True,
                        },
                        {
                            "Excel Column": "Department",
                            "Maps To (System Field)": "Department",
                            "Data Type": "Dropdown",
                            "Required": False,
                        },
                        {
                            "Excel Column": "Assigned To",
                            "Maps To (System Field)": "Assigned To",
                            "Data Type": "User",
                            "Required": False,
                        },
                    ]
                )
                st.dataframe(mapping_df, use_container_width=True)

                st.markdown("---")
                prev_c1, prev_c2 = st.columns([8, 4])
                with prev_c1:
                    st.markdown("#### 📋 Data Preview")
                    st.caption(
                        "Preview the first 10 rows from your file."
                    )
                with prev_c2:
                    st.markdown(
                        "<div style='text-align:right; font-weight:bold; color:#005f73;'>Total Rows: 250</div>",
                        unsafe_allow_html=True,
                    )

                preview_df = pd.DataFrame(
                    [
                        {
                            "Case Number": "CAR-2026-0101",
                            "Subject": "Store network outage",
                            "Account": "H&M",
                            "Vendor": "Aruba Networks",
                            "Issue Category": "Network Connectivity",
                            "Priority": "Critical",
                            "Department": "Global Retail",
                            "Assigned To": "Maria Santos",
                        },
                        {
                            "Case Number": "ARC-2026-0155",
                            "Subject": "Portal access issue",
                            "Account": "Accenture",
                            "Vendor": "Microsoft",
                            "Issue Category": "System Access",
                            "Priority": "High",
                            "Department": "Network Team",
                            "Assigned To": "James Li",
                        },
                        {
                            "Case Number": "PET-2026-0078",
                            "Subject": "Device not detected",
                            "Account": "Nike",
                            "Vendor": "HP",
                            "Issue Category": "Hardware/Device",
                            "Priority": "Medium",
                            "Department": "Operations",
                            "Assigned To": "Ravi Patel",
                        },
                        {
                            "Case Number": "SC-2026-0104",
                            "Subject": "Order sync failure",
                            "Account": "Zalora",
                            "Vendor": "SAP",
                            "Issue Category": "Application/Error",
                            "Priority": "High",
                            "Department": "Supply Chain",
                            "Assigned To": "Sarah Davis",
                        },
                        {
                            "Case Number": "FUL-2026-0022",
                            "Subject": "Stock update delay",
                            "Account": "Lazada",
                            "Vendor": "Oracle",
                            "Issue Category": "System Performance",
                            "Priority": "Medium",
                            "Department": "Fulfillment",
                            "Assigned To": "Kevin Tan",
                        },
                    ]
                )
                st.dataframe(preview_df, use_container_width=True)

        # SETTINGS TAB 4: EXPORT DATA (Exact match to image 1000059135.png)[cite: 12]
        with s_tab4:
            ed_col1, ed_col2 = st.columns([5, 7])
            with ed_col1:
                st.markdown("#### 📊 Export Data")
                st.caption("Download system data for reporting, analysis or backup.")

                st.markdown("**1. Select Data to Export**")
                st.checkbox(
                    "Cases (Case details, status, timelines and history)",
                    value=True,
                )
                st.checkbox(
                    "Collaboration Messages (Messages and attachments)",
                    value=True,
                )
                st.checkbox(
                    "Attachments (File details and links)", value=True
                )
                st.checkbox(
                    "Reference Data (Accounts, vendors, departments, etc.)"
                )
                st.checkbox("Stations (Station configuration and SLA settings)")
                st.checkbox("Alert Rules (Configured alerts and notifications)")
                st.checkbox("System Logs (System activity and audit logs)")

                st.markdown("---")
                st.markdown("**2. Export Format**")
                st.radio(
                    "Format Options",
                    [
                        "Excel (.xlsx) - Best for analysis and reporting",
                        "CSV (.csv) - Lightweight format for data processing",
                        "PDF (.pdf) - Formatted report (summary only)",
                        "PowerPoint (.pptx) - Slides with tables and charts",
                    ],
                    label_visibility="collapsed",
                )

            with ed_col2:
                st.markdown("#### 🔍 3. Filter Options (Optional)")
                d_c1, d_c2, d_c3 = st.columns(3)
                with d_c1:
                    st.selectbox("Date Range", ["Last 30 Days", "Custom Range"])
                with d_c2:
                    st.text_input("From Date", value="Mar 01, 2026")
                with d_c3:
                    st.text_input("To Date", value="Mar 11, 2026")

                f_c1, f_c2, f_c3 = st.columns(3)
                with f_c1:
                    st.selectbox("Station", ["All Stations", "CARE", "ARCH"])
                with f_c2:
                    st.selectbox(
                        "Priority", ["All Priorities", "Critical", "High"]
                    )
                with f_c3:
                    st.selectbox(
                        "Status", ["All Statuses", "In Progress", "Open"]
                    )

                f_c4, f_c5, f_c6 = st.columns(3)
                with f_c4:
                    st.selectbox("Account", ["All Accounts", "H&M", "Nike"])
                with f_c5:
                    st.selectbox(
                        "Vendor", ["All Vendors", "Aruba Networks", "Microsoft"]
                    )
                with f_c6:
                    st.selectbox(
                        "Assignee",
                        ["All Assignees", "Maria Santos", "James Li"],
                    )

                st.checkbox("Include deleted/archived records")

                st.markdown("---")
                col_hdr1, col_hdr2 = st.columns([7, 5])
                with col_hdr1:
                    st.markdown("#### 📋 4. Select Columns")
                    st.caption("Choose the columns to include in the export file.")
                with col_hdr2:
                    st.checkbox("Select All", value=True)

                st.text_input(
                    "Search columns",
                    placeholder="🔍 Search columns...",
                    label_visibility="collapsed",
                )

                # Checkbox columns grid simulation
                cc1, cc2, cc3, cc4, cc5 = st.columns(5)
                with cc1:
                    st.checkbox("Case Number", value=True)
                    st.checkbox("Priority", value=True)
                    st.checkbox("Due Date")
                with cc2:
                    st.checkbox("Subject", value=True)
                    st.checkbox("Status", value=True)
                    st.checkbox("Total Elapsed")
                with cc3:
                    st.checkbox("Account", value=True)
                    st.checkbox("Station", value=True)
                    st.checkbox("Current Duration", value=True)
                with cc4:
                    st.checkbox("Vendor", value=True)
                    st.checkbox("Assigned To", value=True)
                    st.checkbox("SLA (minutes)", value=True)
                with cc5:
                    st.checkbox("Issue Category", value=True)
                    st.checkbox("Created Date", value=True)
                    st.checkbox("SLA Remaining", value=True)

                st.markdown("---")
                prev_ex1, prev_ex2 = st.columns([8, 4])
                with prev_ex1:
                    st.markdown("#### 📊 5. Preview Data")
                    st.caption(
                        "Preview the first 10 rows based on your selected options."
                    )
                with prev_ex2:
                    st.markdown(
                        "<div style='text-align:right; font-weight:bold; color:#005f73;'>Total Records: 1,248</div>",
                        unsafe_allow_html=True,
                    )

                export_preview_df = pd.DataFrame(
                    [
                        {
                            "Case Number": "CAR-2026-0101",
                            "Subject": "Store network outage",
                            "Account": "H&M",
                            "Vendor": "Aruba Networks",
                            "Priority": "Critical",
                            "Status": "In Progress",
                            "Station": "CARE",
                            "Assigned To": "Maria Santos",
                            "Created Date": "Mar 11, 2026 09:15",
                        },
                        {
                            "Case Number": "ARC-2026-0155",
                            "Subject": "Portal access issue",
                            "Account": "Accenture",
                            "Vendor": "Microsoft",
                            "Priority": "High",
                            "Status": "Open",
                            "Station": "ARCH",
                            "Assigned To": "James Li",
                            "Created Date": "Mar 11, 2026 08:42",
                        },
                        {
                            "Case Number": "PET-2026-0078",
                            "Subject": "Device not detected",
                            "Account": "Nike",
                            "Vendor": "HP",
                            "Priority": "Medium",
                            "Status": "In Progress",
                            "Station": "PET",
                            "Assigned To": "Ravi Patel",
                            "Created Date": "Mar 11, 2026 08:30",
                        },
                    ]
                )
                st.dataframe(export_preview_df, use_container_width=True)

        # SETTINGS TAB 5: SIMULATION
        with s_tab5:
            st.markdown("#### 🎮 Operations Simulation Engine")
            st.caption(
                "Generate mock cases and system events for training and testing purposes."
            )
            if st.button("🚀 Start Simulation", type="primary"):
                st.success("Simulation started successfully!")

        st.markdown("<hr/>", unsafe_allow_html=True)
        modal_b1, modal_b2, modal_b3 = st.columns([2, 8, 2])
        with modal_b1:
            if st.session_state.settings_tab == "Export Data":
                st.checkbox("Open file after export", value=True)
        with modal_b2:
            pass
        with modal_b3:
            if st.session_state.settings_tab == "Export Data":
                st.button("📥 Export Data", type="primary", use_container_width=True)
            elif st.session_state.settings_tab == "Data Import":
                st.button("📤 Import Data", type="primary", use_container_width=True)

        if st.button("❌ Close Settings Window", key="close_settings_btn"):
            st.session_state.show_settings = False
            st.rerun()
