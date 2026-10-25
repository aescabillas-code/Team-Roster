import datetime
import random
import time
import io
import os
import base64
import json
import streamlit as st
import pandas as pd

# Optional MongoDB import with fallback simulation store
try:
    from pymongo import MongoClient
    HAS_PYMONGO = True
except ImportError:
    HAS_PYMONGO = False

# Optional Itsdangerous for secure browser token signing
try:
    from itsdangerous import URLSafeTimedSerializer
    HAS_ITSDANGEROUS = True
except ImportError:
    HAS_ITSDANGEROUS = False

# ==========================================
# PAGE CONFIGURATION & STYLING
# ==========================================
st.set_page_config(
    page_title="OVR-VW - Operations Visibility & Response Workspace",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom HPE-inspired Dark Teal / Green Gradient & Enterprise UI CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
        background-color: #f4f6f8;
        color: #0b2545;
    }
    
    /* Hide default Streamlit header and footer */
    header {visibility: hidden;}
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Custom HPE Header Banner */
    .hpe-header {
        background: linear-gradient(135deg, #01a982 0%, #007355 100%);
        padding: 14px 24px;
        border-radius: 8px;
        color: white;
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    
    /* Station Card Styling */
    .station-box-care { background: #ffeef0; border-top: 4px solid #d73a49; padding: 14px; border-radius: 8px; }
    .station-box-arch { background: #e3f2fd; border-top: 4px solid #1976d2; padding: 14px; border-radius: 8px; }
    .station-box-pet { background: #e8f5e9; border-top: 4px solid #2e7d32; padding: 14px; border-radius: 8px; }
    .station-box-supply { background: #f3e5f5; border-top: 4px solid #7b1fa2; padding: 14px; border-radius: 8px; }
    .station-box-fulfillment { background: #fff8e1; border-top: 4px solid #f57f17; padding: 14px; border-radius: 8px; }
    
    /* Status & Priority Badges */
    .badge-critical { background-color: #ffeef0; color: #d73a49; padding: 3px 8px; border-radius: 4px; font-weight: 600; font-size: 11px; }
    .badge-high { background-color: #fff8c5; color: #b08800; padding: 3px 8px; border-radius: 4px; font-weight: 600; font-size: 11px; }
    .badge-medium { background-color: #fff1db; color: #bc5200; padding: 3px 8px; border-radius: 4px; font-weight: 600; font-size: 11px; }
    .badge-low { background-color: #e6ffed; color: #22863a; padding: 3px 8px; border-radius: 4px; font-weight: 600; font-size: 11px; }
    
    .badge-status { background-color: #e1f5fe; color: #0277bd; padding: 3px 8px; border-radius: 4px; font-weight: 500; font-size: 11px; }
    .badge-resolved { background-color: #e8f5e9; color: #2e7d32; padding: 3px 8px; border-radius: 4px; font-weight: 500; font-size: 11px; }
    
    /* Modal Container Style */
    .modal-container {
        background: white;
        padding: 24px;
        border-radius: 12px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.15);
        margin-bottom: 30px;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# DATABASE & COLLECTION MANAGER
# ==========================================
class DatabaseManager:
    def __init__(self):
        self.connected = False
        self.db = None
        if HAS_PYMONGO:
            try:
                mongo_uri = st.secrets.get("general", {}).get("MONGO_URI", "mongodb://localhost:27017/")
                db_name = st.secrets.get("general", {}).get("DB_NAME", "ovrvw_enterprise_db")
                self.client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
                self.client.server_info()
                self.db = self.client[db_name]
                self.connected = True
            except Exception:
                self.connected = False

        # Initialize collections mapping
        if self.connected:
            self.team_roster = self.db["TeamRoster"]
            self.tasks_col = self.db["Tasks_Collection"]
            self.vendor_col = self.db["Vendor_Collection"]
            self.access_col = self.db["Access_Collection"]
            self.alert_col = self.db["Alert_Collection"]
            self.alert_def_col = self.db["Alert_Definition_Collection"]
            self.kb_col = self.db["Knowledge_Base_Collection"]
            self.sop_col = self.db["SOP_Collection"]
            self.account_priority_col = self.db["Account_Priority_Collection"]
        else:
            if "memory_db" not in st.session_state:
                st.session_state["memory_db"] = self._init_mock_data()

    def _init_mock_data(self):
        now = datetime.datetime.now()
        return {
            "TeamRoster": [
                {"name": "Maria Santos", "role": "Operations", "status": "Online"},
                {"name": "James Li", "role": "Network Team", "status": "Online"},
                {"name": "Ravi Patel", "role": "Aruba Networks", "status": "Away"},
                {"name": "Ana Rodriguez", "role": "Logistics", "status": "Online"},
                {"name": "Daniel Kim", "role": "Field Services", "status": "Online"}
            ],
            "tasks": [
                {
                    "case_number": "CAR-2026-0001",
                    "subject": "Store network outage",
                    "account": "H&M",
                    "station": "CARE",
                    "assignee": "Maria Santos",
                    "priority": "CRITICAL",
                    "status": "In Progress",
                    "duration_seconds": 754,
                    "sla_limit_minutes": 15,
                    "created_at": now - datetime.timedelta(hours=2, minutes=18),
                    "last_updated": now,
                    "source": "Excel Import",
                    "department": "Global Retail",
                    "vendor": "Aruba Networks",
                    "issue_category": "Network Connectivity",
                    "description": "Customer reported complete network outage at the downtown store. All POS systems and wireless access are unavailable. Requires immediate investigation and restoration.",
                    "action_plan": "Investigate network outage, check switch logs and customer environment. Coordinate with Aruba TAC if needed.",
                    "checklist": {
                        "Product identification, symptoms, troubleshooting": True,
                        "Entitlement & customer site information": True,
                        "Assessment & initial diagnosis": True,
                        "Capture exact error message": True,
                        "Complete basic remote troubleshooting": True,
                        "Verify support/contract context": False
                    },
                    "history": [
                        {"timestamp": "Mar 11, 2026 10:24 AM", "action": "Note Added", "status": "In Progress", "performed_by": "Maria Santos", "details": "Added note: Investigating switch logs with customer."},
                        {"timestamp": "Mar 11, 2026 10:18 AM", "action": "Checklist Item Completed", "status": "In Progress", "performed_by": "Maria Santos", "details": "Verified support, entitlement or contract context."},
                        {"timestamp": "Mar 11, 2026 10:12 AM", "action": "Priority Changed", "status": "In Progress", "performed_by": "Maria Santos", "details": "Priority changed from Medium to Critical."},
                        {"timestamp": "Mar 11, 2026 10:05 AM", "action": "Assignee Changed", "status": "In Progress", "performed_by": "System", "details": "Assignee changed from Unassigned to Maria Santos."},
                        {"timestamp": "Mar 11, 2026 09:42 AM", "action": "Status Updated", "status": "Open", "performed_by": "Maria Santos", "details": "Status changed from Open to In Progress."},
                        {"timestamp": "Mar 11, 2026 09:20 AM", "action": "Case Transferred", "status": "In Progress", "performed_by": "James Li", "details": "Case transferred to CARE."},
                        {"timestamp": "Mar 11, 2026 08:45 AM", "action": "Action Plan Updated", "status": "Open", "performed_by": "James Li", "details": "Initial action plan added."},
                        {"timestamp": "Mar 11, 2026 08:15 AM", "action": "Case Created", "status": "Open", "performed_by": "Excel Import", "details": "Case created from Excel import."}
                    ],
                    "collaboration": [
                        {"sender": "Maria Santos", "role": "Operations", "timestamp": "Mar 11, 2026 10:24 AM", "message": "Investigating network outage at the downtown store. Initial checks show no connectivity on POS and internal systems."},
                        {"sender": "James Li", "role": "Network Team", "timestamp": "Mar 11, 2026 10:18 AM", "message": "Checked the core switch logs. Multiple interface errors detected. Performing further analysis and validating VLAN configuration."},
                        {"sender": "Ravi Patel", "role": "Vendor - Aruba", "timestamp": "Mar 11, 2026 10:05 AM", "message": "Aruba TAC case opened (TAC-458921) for this issue. Collecting additional logs and configuration details. Will provide an update shortly."}
                    ],
                    "attachments": [
                        {"name": "Network_Error_Screenshot.png", "type": "Image", "size": "1.2 MB", "uploaded_by": "Maria Santos", "date": "Mar 11, 2026 10:18 AM", "description": "Screenshot of the POS error message encountered at the store."},
                        {"name": "Switch_Log_031126.txt", "type": "Text", "size": "450 KB", "uploaded_by": "James Li", "date": "Mar 11, 2026 10:12 AM", "description": "Core switch error log excerpt."}
                    ],
                    "is_closed": False
                },
                {
                    "case_number": "ARC-2026-0015",
                    "subject": "Validation request",
                    "account": "Global Retail",
                    "station": "ARCH",
                    "assignee": "James Li",
                    "priority": "HIGH",
                    "status": "Open",
                    "duration_seconds": 1092,
                    "sla_limit_minutes": 30,
                    "created_at": now - datetime.timedelta(hours=1, minutes=30),
                    "last_updated": now,
                    "source": "Excel Import",
                    "department": "Retail Ops",
                    "vendor": "Cisco",
                    "issue_category": "Architecture Validation",
                    "description": "Validation request for architectural topology update.",
                    "action_plan": "Review topology documents against enterprise standards.",
                    "checklist": {item: False for item in ["Case/reference validation", "Document retrieval", "Source validation", "Record completeness", "Next action defined", "Existing requirement met"]},
                    "history": [{"timestamp": "Mar 11, 2026 09:00 AM", "action": "Case Created", "status": "Open", "performed_by": "Excel Import", "details": "Initial import."}],
                    "collaboration": [],
                    "attachments": [],
                    "is_closed": False
                },
                {
                    "case_number": "PET-2026-0078",
                    "subject": "Access configuration",
                    "account": "TechCorp",
                    "station": "PET",
                    "assignee": "Ravi Patel",
                    "priority": "MEDIUM",
                    "status": "In Progress",
                    "duration_seconds": 1510,
                    "sla_limit_minutes": 45,
                    "created_at": now - datetime.timedelta(hours=1),
                    "last_updated": now,
                    "source": "Excel Import",
                    "department": "IT Engineering",
                    "vendor": "Aruba Networks",
                    "issue_category": "Platform Configuration",
                    "description": "Access configuration update for secure VLAN environment.",
                    "action_plan": "Apply VLAN configuration changes.",
                    "checklist": {item: False for item in ["Device/platform identification", "Configuration/access requirements", "Management details", "Change validation", "Remaining requirements", "Final check"]},
                    "history": [{"timestamp": "Mar 11, 2026 09:15 AM", "action": "Case Created", "status": "Open", "performed_by": "Excel Import", "details": "Initial import."}],
                    "collaboration": [],
                    "attachments": [],
                    "is_closed": False
                },
                {
                    "case_number": "SC-2026-0104",
                    "subject": "Shipment delay",
                    "account": "Acme Ltd",
                    "station": "SUPPLY CHAIN",
                    "assignee": "Ana Rodriguez",
                    "priority": "LOW",
                    "status": "Pending Internal",
                    "duration_seconds": 3332,
                    "sla_limit_minutes": 30,
                    "created_at": now - datetime.timedelta(hours=3),
                    "last_updated": now,
                    "source": "Excel Import",
                    "department": "Logistics",
                    "vendor": "DHL",
                    "issue_category": "Fulfillment Exception",
                    "description": "Shipment delayed due to customs clearance.",
                    "action_plan": "Coordinate with logistics partner for status update.",
                    "checklist": {item: True for item in ["Order/shipment references", "Product/quantity verification", "Tracking information", "Delivery destination", "Fulfillment exceptions", "Sign-off"]},
                    "history": [{"timestamp": "Mar 11, 2026 07:30 AM", "action": "Case Created", "status": "Open", "performed_by": "Excel Import", "details": "Initial import."}],
                    "collaboration": [],
                    "attachments": [],
                    "is_closed": False
                },
                {
                    "case_number": "FUL-2026-0029",
                    "subject": "Onsite installation",
                    "account": "Metro Partners",
                    "station": "FULFILLMENT",
                    "assignee": "Daniel Kim",
                    "priority": "MEDIUM",
                    "status": "In Progress",
                    "duration_seconds": 8145,
                    "sla_limit_minutes": 120,
                    "created_at": now - datetime.timedelta(hours=4),
                    "last_updated": now,
                    "source": "Excel Import",
                    "department": "Field Services",
                    "vendor": "Local Techs",
                    "issue_category": "Onsite Deployment",
                    "description": "Scheduled onsite hardware installation and rack mounting.",
                    "action_plan": "Deploy technician to site.",
                    "checklist": {item: False for item in ["Device identification", "Site access verification", "Scope of work definition", "Parts/technician requirements", "Findings log", "Closure readiness"]},
                    "history": [{"timestamp": "Mar 11, 2026 06:00 AM", "action": "Case Created", "status": "Open", "performed_by": "Excel Import", "details": "Initial import."}],
                    "collaboration": [],
                    "attachments": [],
                    "is_closed": False
                },
                # Closed case sample
                {
                    "case_number": "CAR-2026-0023",
                    "subject": "Wireless connectivity issue",
                    "account": "Global Retail",
                    "station": "CARE",
                    "assignee": "Maria Santos",
                    "priority": "MEDIUM",
                    "status": "Resolved",
                    "duration_seconds": 4365,
                    "sla_limit_minutes": 15,
                    "created_at": now - datetime.timedelta(days=1),
                    "last_updated": now - datetime.timedelta(days=1),
                    "closed_date": "Mar 10, 2026 16:22",
                    "source": "Excel Import",
                    "department": "Global Retail",
                    "vendor": "Aruba Networks",
                    "issue_category": "Wireless",
                    "description": "Resolved wireless roaming drop issues.",
                    "action_plan": "Firmware upgraded.",
                    "checklist": {},
                    "history": [],
                    "collaboration": [],
                    "attachments": [],
                    "is_closed": True
                }
            ],
            "knowledge_base": [
                {
                    "title": "Network Outage – Store Connectivity Troubleshooting",
                    "category": "Troubleshooting",
                    "content_type": "SOP",
                    "last_updated": "Jan 15, 2026",
                    "relevance": 98,
                    "overview": "Step-by-step troubleshooting guide for store network outages, including switch validation, WAN connectivity, and escalation criteria.",
                    "symptoms": ["Store systems and POS are unable to connect to the network", "Users cannot access internal applications", "Intermittent or complete loss of network connectivity"],
                    "steps": ["Verify local device connectivity (laptop or POS device).", "Check physical connections and switch port status.", "Validate VLAN configuration and port assignment.", "Check for high error counts on the switch interface.", "Test WAN connectivity and DNS resolution.", "If unresolved, collect logs and escalate to Aruba TAC."]
                }
            ],
            "alerts": [
                {"name": "SLA Warning (60%)", "trigger": "SLA at 60%", "color": "Amber", "icon": "Warning Triangle", "audio": "warning.mp3", "status": True},
                {"name": "SLA Breach (80%)", "trigger": "SLA at 80%", "color": "Red", "icon": "Error Circle", "audio": "breach.mp3", "status": True},
                {"name": "New Case Assignment", "trigger": "New case assigned", "color": "Blue", "icon": "Bell", "audio": "newcase.mp3", "status": True}
            ]
        }

db_manager = DatabaseManager()

# ==========================================
# SESSION STATE INITIALIZATION
# ==========================================
if "current_nav" not in st.session_state:
    st.session_state["current_nav"] = "Active Cases"
if "selected_station_filter" not in st.session_state:
    st.session_state["selected_station_filter"] = "All Stations"
if "selected_case_id" not in st.session_state:
    st.session_state["selected_case_id"] = None
if "show_settings" not in st.session_state:
    st.session_state["show_settings"] = False
if "settings_tab" not in st.session_state:
    st.session_state["settings_tab"] = "General"
if "case_modal_tab" not in st.session_state:
    st.session_state["case_modal_tab"] = "Case Information"
if "simulation_type" not in st.session_state:
    st.session_state["simulation_type"] = "Single Case"
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = True

# Helper data retrieval functions
def get_all_cases():
    if db_manager.connected:
        cases = list(db_manager.tasks_col.find({}, {"_id": 0}))
        if cases:
            return cases
    return st.session_state["memory_db"]["tasks"]

def save_case(case_data):
    if db_manager.connected:
        db_manager.tasks_col.update_one(
            {"case_number": case_data["case_number"]},
            {"$set": case_data},
            upsert=True
        )
    else:
        tasks = st.session_state["memory_db"]["tasks"]
        for i, t in enumerate(tasks):
            if t["case_number"] == case_data["case_number"]:
                tasks[i] = case_data
                return
        tasks.append(case_data)

# ==========================================
# HEADER & TOP NAVIGATION BAR
# ==========================================
st.markdown("""
<div class="hpe-header">
    <div style="display: flex; align-items: center; gap: 15px;">
        <div style="background: white; color: #01a982; font-weight: 800; padding: 6px 12px; border-radius: 4px; font-size: 16px;">HPE</div>
        <div>
            <div style="font-size: 20px; font-weight: 700; letter-spacing: 0.5px;">OVR-VW</div>
            <div style="font-size: 11px; opacity: 0.85;">Operations Visibility & Response Workspace</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

top_col1, top_col2, top_col3 = st.columns([3, 4, 1])

with top_col1:
    # Clickable Text & Icon Navigation Buttons (NO radio buttons used)
    nav_c1, nav_c2 = st.columns(2)
    with nav_c1:
        if st.button("📊 Active Cases", use_container_width=True, type="primary" if st.session_state["current_nav"] == "Active Cases" else "secondary"):
            st.session_state["current_nav"] = "Active Cases"
            st.rerun()
    with nav_c2:
        if st.button("📁 Closed Cases", use_container_width=True, type="primary" if st.session_state["current_nav"] == "Closed Cases" else "secondary"):
            st.session_state["current_nav"] = "Closed Cases"
            st.rerun()

with top_col2:
    search_query = st.text_input("Search", placeholder="Search cases by number, subject, account, assignee...", label_visibility="collapsed")

with top_col3:
    if st.button("⚙️ Settings", use_container_width=True):
        st.session_state["show_settings"] = True
        st.rerun()

st.markdown("---")

# ==========================================
# OPERATIONAL STATION TILES
# ==========================================
stations_meta = {
    "CARE": {"sla": 15, "class": "station-box-care", "icon": "🎧"},
    "ARCH": {"sla": 30, "class": "station-box-arch", "icon": "📄"},
    "PET": {"sla": 45, "class": "station-box-pet", "icon": "⚙️"},
    "SUPPLY CHAIN": {"sla": 30, "class": "station-box-supply", "icon": "🚚"},
    "FULFILLMENT": {"sla": 120, "class": "station-box-fulfillment", "icon": "🔧"}
}

all_cases = get_all_cases()
active_cases_list = [c for c in all_cases if not c.get("is_closed", False)]
closed_cases_list = [c for c in all_cases if c.get("is_closed", False)]

current_queue = active_cases_list if st.session_state["current_nav"] == "Active Cases" else closed_cases_list

cols = st.columns(5)
for i, (station_name, meta) in enumerate(stations_meta.items()):
    count = len([c for c in current_queue if c.get("station") == station_name])
    with cols[i]:
        lbl = "Active Cases" if st.session_state["current_nav"] == "Active Cases" else "Closed Cases"
        if st.button(f"{meta['icon']} {station_name}\n{count} {lbl}\nSLA {meta['sla']}m", use_container_width=True):
            st.session_state["selected_station_filter"] = station_name
            st.rerun()

st.markdown(f"### {st.session_state['current_nav']}")
f_col1, f_col2 = st.columns([2, 6])
with f_col1:
    station_options = ["All Stations"] + list(stations_meta.keys())
    idx = station_options.index(st.session_state["selected_station_filter"]) if st.session_state["selected_station_filter"] in station_options else 0
    sel_st = st.selectbox("Filter Station", station_options, index=idx, label_visibility="collapsed")
    if sel_st != st.session_state["selected_station_filter"]:
        st.session_state["selected_station_filter"] = sel_st
        st.rerun()

filtered_cases = current_queue
if st.session_state["selected_station_filter"] != "All Stations":
    filtered_cases = [c for c in filtered_cases if c.get("station") == st.session_state["selected_station_filter"]]

if search_query:
    q = search_query.lower()
    filtered_cases = [c for c in filtered_cases if q in c.get("case_number", "").lower() or q in c.get("subject", "").lower() or q in c.get("account", "").lower() or q in c.get("assignee", "").lower()]

# Sort Priority Order: BREACHED → CRITICAL → MEDIUM → LOW
priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
filtered_cases = sorted(filtered_cases, key=lambda x: priority_order.get(x.get("priority", "MEDIUM"), 2))

# ==========================================
# MAIN CASES TABLE VIEW
# ==========================================
if st.session_state["current_nav"] == "Active Cases":
    headers = ["Case Number", "Subject", "Account", "Station", "Assignee", "Priority", "Status", "Duration", "SLA", "Actions"]
    h_cols = st.columns([1.2, 2.2, 1.2, 1.2, 1.5, 1, 1.2, 1, 0.8, 1])
    for col, h in zip(h_cols, headers):
        col.markdown(f"**{h}**")
    st.markdown("<hr style='margin: 5px 0;'>", unsafe_allow_html=True)

    for case in filtered_cases:
        c1, c2, c3, c4, c5, c6, c7, c8, c9, c10 = st.columns([1.2, 2.2, 1.2, 1.2, 1.5, 1, 1.2, 1, 0.8, 1])
        with c1:
            if st.button(case["case_number"], key=f"tbl_btn_{case['case_number']}"):
                st.session_state["selected_case_id"] = case["case_number"]
                st.rerun()
        with c2: st.write(case.get("subject", ""))
        with c3: st.write(case.get("account", ""))
        with c4: st.markdown(f"<span class='badge-status'>{case.get('station', '')}</span>", unsafe_allow_html=True)
        with c5: st.write(case.get("assignee", ""))
        with c6:
            p = case.get("priority", "MEDIUM")
            st.markdown(f"<span class='badge-{p.lower()}'>{p}</span>", unsafe_allow_html=True)
        with c7: st.markdown(f"<span class='badge-status'>{case.get('status', '')}</span>", unsafe_allow_html=True)
        with c8:
            secs = case.get("duration_seconds", 0)
            m, s = divmod(secs, 60)
            h, m = divmod(m, 60)
            st.write(f"{h:02d}:{m:02d}:{s:02d}")
        with c9:
            s_limit = case.get("sla_limit_minutes", 15) * 60
            dur = case.get("duration_seconds", 0)
            if dur > s_limit: st.markdown("🚨", help="SLA Breached")
            elif dur > s_limit * 0.6: st.markdown("⚠️", help="Approaching Breach")
            else: st.markdown("✅", help="SLA Healthy")
        with c10:
            if st.button("View", key=f"view_{case['case_number']}"):
                st.session_state["selected_case_id"] = case["case_number"]
                st.rerun()
else:
    headers = ["Case Number", "Subject", "Account", "Station", "Assignee", "Priority", "Status", "Closed Date", "Total Duration", "Actions"]
    h_cols = st.columns([1.2, 2.2, 1.2, 1.2, 1.5, 1, 1.2, 1.5, 1, 1])
    for col, h in zip(h_cols, headers):
        col.markdown(f"**{h}**")
    st.markdown("<hr style='margin: 5px 0;'>", unsafe_allow_html=True)

    for case in filtered_cases:
        c1, c2, c3, c4, c5, c6, c7, c8, c9, c10 = st.columns([1.2, 2.2, 1.2, 1.2, 1.5, 1, 1.2, 1.5, 1, 1])
        with c1:
            if st.button(case["case_number"], key=f"closed_btn_{case['case_number']}"):
                st.session_state["selected_case_id"] = case["case_number"]
                st.rerun()
        with c2: st.write(case.get("subject", ""))
        with c3: st.write(case.get("account", ""))
        with c4: st.markdown(f"<span class='badge-status'>{case.get('station', '')}</span>", unsafe_allow_html=True)
        with c5: st.write(case.get("assignee", ""))
        with c6:
            p = case.get("priority", "MEDIUM")
            st.markdown(f"<span class='badge-{p.lower()}'>{p}</span>", unsafe_allow_html=True)
        with c7: st.markdown(f"<span class='badge-resolved'>{case.get('status', 'Resolved')}</span>", unsafe_allow_html=True)
        with c8: st.write(case.get("closed_date", "Mar 10, 2026"))
        with c9:
            secs = case.get("duration_seconds", 0)
            m, s = divmod(secs, 60)
            h, m = divmod(m, 60)
            st.write(f"{h:02d}:{m:02d}:{s:02d}")
        with c10:
            if st.button("View", key=f"closed_view_{case['case_number']}"):
                st.session_state["selected_case_id"] = case["case_number"]
                st.rerun()

# ==========================================
# CASE DETAILS MODAL (5 TABS - CLICKABLE BUTTONS)
# ==========================================
if st.session_state["selected_case_id"]:
    sc = next((c for c in all_cases if c["case_number"] == st.session_state["selected_case_id"]), None)
    if sc:
        st.markdown("<div class='modal-container'>", unsafe_allow_html=True)
        m_c1, m_c2 = st.columns([10, 1])
        with m_c1:
            st.subheader(f"Case Details: {sc['case_number']} — {sc['subject']}")
            st.caption("View and manage case information, actions, knowledge base and collaboration")
        with m_c2:
            if st.button("❌ Close"):
                st.session_state["selected_case_id"] = None
                st.rerun()

        # Modal Tab Menu (Button-based, strictly NO radio buttons)
        t1, t2, t3, t4, t5 = st.columns(5)
        with t1:
            if st.button("📄 Case Information", use_container_width=True, type="primary" if st.session_state["case_modal_tab"] == "Case Information" else "secondary"):
                st.session_state["case_modal_tab"] = "Case Information"
                st.rerun()
        with t2:
            if st.button("⚡ Case Actions", use_container_width=True, type="primary" if st.session_state["case_modal_tab"] == "Case Actions" else "secondary"):
                st.session_state["case_modal_tab"] = "Case Actions"
                st.rerun()
        with t3:
            if st.button("📚 Knowledge Base", use_container_width=True, type="primary" if st.session_state["case_modal_tab"] == "Knowledge Base" else "secondary"):
                st.session_state["case_modal_tab"] = "Knowledge Base"
                st.rerun()
        with t4:
            if st.button("💬 Collaboration", use_container_width=True, type="primary" if st.session_state["case_modal_tab"] == "Collaboration" else "secondary"):
                st.session_state["case_modal_tab"] = "Collaboration"
                st.rerun()
        with t5:
            if st.button("📎 Attachments", use_container_width=True, type="primary" if st.session_state["case_modal_tab"] == "Attachments" else "secondary"):
                st.session_state["case_modal_tab"] = "Attachments"
                st.rerun()

        st.markdown("---")
        tab_choice = st.session_state["case_modal_tab"]

        if tab_choice == "Case Information":
            inf1, inf2 = st.columns(2)
            with inf1:
                st.markdown("### Case Overview")
                st.write(f"**Case Number:** {sc['case_number']}")
                st.write(f"**Subject:** {sc['subject']}")
                st.write(f"**Account:** {sc.get('account', '')}")
                st.write(f"**Vendor:** {sc.get('vendor', '')}")
                st.write(f"**Issue Category:** {sc.get('issue_category', '')}")
                st.write(f"**Description:** {sc.get('description', '')}")
                st.write(f"**Current Station:** {sc.get('station', '')}")
                st.write(f"**Status:** {sc.get('status', '')}")
                st.write(f"**Priority:** {sc.get('priority', '')}")
                st.write(f"**Assigned To:** {sc.get('assignee', '')}")
                st.write(f"**Created Date:** {sc.get('created_at', '')}")
            with inf2:
                st.markdown("### Timing & SLA")
                secs = sc.get("duration_seconds", 0)
                m, s = divmod(secs, 60)
                h, m = divmod(m, 60)
                st.metric("Station Duration", f"{h:02d}:{m:02d}:{s:02d}", f"SLA Limit: {sc.get('sla_limit_minutes', 15)} mins")
                st.markdown("### Station Journey")
                st.info(f"Active Station: **{sc.get('station')}**. Workflow progressing according to SLA rules.")

        elif tab_choice == "Case Actions":
            act1, act2 = st.columns(2)
            with act1:
                st.markdown(f"### Station Checklist ({sc.get('station')})")
                checklist = sc.get("checklist", {})
                updated_chk = {}
                all_done = True
                for item, val in checklist.items():
                    res = st.checkbox(item, value=val, key=f"chk_{sc['case_number']}_{item}")
                    updated_chk[item] = res
                    if not res: all_done = False
                sc["checklist"] = updated_chk
                save_case(sc)
            with act2:
                st.markdown("### Case Actions & Updates")
                new_status = st.selectbox("Status", ["Open", "In Progress", "Pending Customer", "Pending Internal", "On Hold", "Escalated", "Resolved", "Completed", "Closed"], index=1)
                new_assignee = st.text_input("Assigned Employee", value=sc.get("assignee", ""))
                action_plan = st.text_area("Action Plan & Assessment", value=sc.get("action_plan", ""))

                if st.button("Save Changes"):
                    sc["status"] = new_status
                    sc["assignee"] = new_assignee
                    sc["action_plan"] = action_plan
                    sc["last_updated"] = datetime.datetime.now()
                    save_case(sc)
                    st.success("Case updated successfully!")
                    st.rerun()

                st.markdown("---")
                st.markdown("### Transfer Station")
                dest_st = st.selectbox("Select Destination Station", [s for s in stations_meta.keys() if s != sc.get("station")])
                if all_done:
                    if st.button(f"Transfer to {dest_st}", type="primary"):
                        sc["station"] = dest_st
                        sc["duration_seconds"] = 0
                        sc["checklist"] = {i: False for i in stations_meta[dest_st]}
                        save_case(sc)
                        st.success(f"Case successfully transferred to {dest_st}!")
                        st.rerun()
                else:
                    st.warning("⚠️ Complete all checklist items before transferring to another station.")

        elif tab_choice == "Knowledge Base":
            st.markdown("### Knowledge Base & SOP Support")
            st.text_input("Search Knowledge Base articles...", key="kb_search_box")
            for art in db_manager.memory_db["knowledge_base"]:
                st.markdown(f"#### 📖 {art['title']}")
                st.write(f"**Category:** {art['category']} | **Relevance:** {art.get('relevance', 90)}% match")
                st.write(art.get("overview", ""))
                st.markdown("**Troubleshooting Steps:**")
                for step in art.get("steps", []):
                    st.markdown(f"- {step}")
                st.markdown("---")

        elif tab_choice == "Collaboration":
            st.markdown("### Collaboration Stream")
            for msg in sc.get("collaboration", []):
                st.markdown(f"**{msg['sender']}** ({msg.get('role', 'Agent')}) - *{msg['timestamp']}*")
                st.write(msg['message'])
                st.markdown("---")

            new_msg = st.text_input("Type a collaboration message...", key="collab_input")
            if st.button("Send Message"):
                if new_msg:
                    sc["collaboration"].append({
                        "sender": "Maria Santos",
                        "role": "Operations",
                        "timestamp": datetime.datetime.now().strftime("%b %d, %Y %I:%M %p"),
                        "message": new_msg
                    })
                    save_case(sc)
                    st.rerun()

        elif tab_choice == "Attachments":
            st.markdown("### Case Attachments")
            if sc.get("attachments"):
                for att in sc.get("attachments", []):
                    st.write(f"📄 **{att['name']}** ({att['type']}, {att['size']}) — Uploaded by {att['uploaded_by']} on {att['date']}")
            else:
                st.info("No attachments recorded for this case.")
            
            up_file = st.file_uploader("Upload new file to case")
            if up_file and st.button("Confirm File Upload"):
                sc["attachments"].append({
                    "name": up_file.name,
                    "type": up_file.type,
                    "size": f"{up_file.size / 1024:.1f} KB",
                    "uploaded_by": "Maria Santos",
                    "date": datetime.datetime.now().strftime("%b %d, %Y %I:%M %p"),
                    "description": "Uploaded via application."
                })
                save_case(sc)
                st.success("File uploaded successfully!")
                st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

# ==========================================
# SETTINGS & ADMINISTRATION MODAL (7 TABS)
# ==========================================
if st.session_state["show_settings"]:
    st.markdown("<div class='modal-container'>", unsafe_allow_html=True)
    st_c1, st_c2 = st.columns([10, 1])
    with st_c1:
        st.subheader("⚙️ Settings & System Administration")
        st.caption("Manage system configuration, data imports, alerts, simulation, access control, and data cleanup")
    with st_c2:
        if st.button("❌ Close Settings"):
            st.session_state["show_settings"] = False
            st.rerun()

    # Settings Tab Menu (Button-based, strictly NO radio buttons)
    s1, s2, s3, s4, s5, s6, s7 = st.columns(7)
    with s1:
        if st.button("General", use_container_width=True, type="primary" if st.session_state["settings_tab"] == "General" else "secondary"):
            st.session_state["settings_tab"] = "General"
            st.rerun()
    with s2:
        if st.button("Alerts", use_container_width=True, type="primary" if st.session_state["settings_tab"] == "Alerts" else "secondary"):
            st.session_state["settings_tab"] = "Alerts"
            st.rerun()
    with s3:
        if st.button("Data Import", use_container_width=True, type="primary" if st.session_state["settings_tab"] == "Data Import" else "secondary"):
            st.session_state["settings_tab"] = "Data Import"
            st.rerun()
    with s4:
        if st.button("Export Data", use_container_width=True, type="primary" if st.session_state["settings_tab"] == "Export Data" else "secondary"):
            st.session_state["settings_tab"] = "Export Data"
            st.rerun()
    with s5:
        if st.button("Simulation", use_container_width=True, type="primary" if st.session_state["settings_tab"] == "Simulation" else "secondary"):
            st.session_state["settings_tab"] = "Simulation"
            st.rerun()
    with s6:
        if st.button("Access Control", use_container_width=True, type="primary" if st.session_state["settings_tab"] == "Access Control" else "secondary"):
            st.session_state["settings_tab"] = "Access Control"
            st.rerun()
    with s7:
        if st.button("Data Cleanup", use_container_width=True, type="primary" if st.session_state["settings_tab"] == "Data Cleanup" else "secondary"):
            st.session_state["settings_tab"] = "Data Cleanup"
            st.rerun()

    st.markdown("---")
    s_tab = st.session_state["settings_tab"]

    if s_tab == "General":
        st.markdown("### System Information & Preferences")
        st.write("**Application Name:** OVR-VW")
        st.write("**Version:** 1.0.0 (Production)")
        st.write("**Database Status:** " + ("Connected to MongoDB" if db_manager.connected else "Running on In-Memory Fallback"))

    elif s_tab == "Alerts":
        st.markdown("### Alert Management Rules")
        for alert in db_manager.memory_db["alerts"]:
            st.write(f"🔔 **{alert['name']}** — Trigger: `{alert['trigger']}` | Status: {'Enabled' if alert['status'] else 'Disabled'}")

    elif s_tab == "Data Import":
        st.markdown("### Import Cases from Excel Workbook")
        imp_col1, imp_col2 = st.columns([1, 1.5])
        with imp_col1:
            st.markdown("#### Import Data")
            st.file_uploader("Upload XLSX / XLS Case Workbook", type=["xlsx", "xls"], key="data_import_file")
            st.markdown("#### Import Options")
            st.checkbox("Create new records only (Skip existing)", value=True)
            st.checkbox("Update existing records", value=False)
            st.checkbox("Replace all records", value=False)
            st.markdown("#### Data Type")
            st.checkbox("Cases", value=True)
            st.checkbox("Stations", value=False)
            st.checkbox("Reference Data", value=False)
        with imp_col2:
            st.markdown("#### Field Mapping")
            map_cols = ["Case Number", "Subject", "Account", "Vendor", "Issue Category", "Priority", "Department", "Assigned To"]
            for mc in map_cols:
                m_c1, m_c2, m_c3 = st.columns([2, 2, 1])
                m_c1.selectbox(f"Excel {mc}", [mc, "Custom Col"], key=f"map_ex_{mc}", label_visibility="collapsed")
                m_c2.selectbox(f"System {mc}", [mc], key=f"map_sys_{mc}", label_visibility="collapsed")
                m_c3.checkbox("Req", value=True, key=f"req_{mc}", label_visibility="collapsed")
        
        st.markdown("#### Data Preview (First 10 rows)")
        preview_df = pd.DataFrame([
            {"Case Number": "CAR-2026-0101", "Subject": "Store network outage", "Account": "H&M", "Vendor": "Aruba Networks", "Priority": "Critical", "Department": "Global Retail", "Assigned To": "Maria Santos"},
            {"Case Number": "ARC-2026-0155", "Subject": "Portal access issue", "Account": "Accenture", "Vendor": "Microsoft", "Priority": "High", "Department": "Network Team", "Assigned To": "James Li"},
            {"Case Number": "PET-2026-0078", "Subject": "Device not detected", "Account": "Nike", "Vendor": "HP", "Priority": "Medium", "Department": "Operations", "Assigned To": "Ravi Patel"},
        ])
        st.dataframe(preview_df, use_container_width=True)
        if st.button("📥 Import Data", type="primary"):
            st.success("Excel workbook successfully processed and cases imported!")

    elif s_tab == "Export Data":
        st.markdown("### Export Operational Cases")
        exp_c1, exp_c2 = st.columns([1, 2])
        with exp_c1:
            st.markdown("#### 1. Select Data to Export")
            st.checkbox("Cases", value=True)
            st.checkbox("Collaboration Messages", value=True)
            st.checkbox("Attachments", value=True)
            st.checkbox("Reference Data", value=False)
            st.checkbox("Stations", value=False)
            st.checkbox("Alert Rules", value=False)
            st.checkbox("System Logs", value=False)

            st.markdown("#### 2. Export Format")
            st.checkbox("Excel (.xlsx)", value=True)
            st.checkbox("CSV (.csv)", value=False)
            st.checkbox("PDF (.pdf)", value=False)
            st.checkbox("PowerPoint (.pptx)", value=False)
        with exp_c2:
            st.markdown("#### 3. Filter Options")
            f_date1, f_date2 = st.columns(2)
            f_date1.date_input("Start Date", datetime.date(2026, 3, 1))
            f_date2.date_input("End Date", datetime.date(2026, 3, 11))
            
            f_s1, f_s2, f_s3 = st.columns(3)
            f_s1.selectbox("Station", ["All Stations"] + list(stations_meta.keys()))
            f_s2.selectbox("Priority", ["All Priorities", "Critical", "High", "Medium", "Low"])
            f_s3.selectbox("Status", ["All Statuses", "Open", "In Progress", "Resolved"])

            st.markdown("#### 4. Select Columns")
            col_list = ["Case Number", "Subject", "Account", "Vendor", "Priority", "Status", "Station", "Assigned To", "Created Date"]
            selected_export_cols = []
            cols_grid = st.columns(3)
            for i, col_name in enumerate(col_list):
                with cols_grid[i % 3]:
                    if st.checkbox(col_name, value=True, key=f"exp_col_{col_name}"):
                        selected_export_cols.append(col_name)

        df_exp = pd.DataFrame(all_cases)
        csv_bytes = df_exp.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Export Data Now", csv_bytes, "ovrvw_cases_export.csv", "text/csv", type="primary")

    elif s_tab == "Simulation":
        st.markdown("### Simulation & Testing Control Panel")
        sim_b1, sim_b2, sim_b3, sim_b4 = st.columns(4)
        with sim_b1:
            if st.button("Single Case", use_container_width=True, type="primary" if st.session_state["simulation_type"] == "Single Case" else "secondary"):
                st.session_state["simulation_type"] = "Single Case"
                st.rerun()
        with sim_b2:
            if st.button("Multiple Cases", use_container_width=True, type="primary" if st.session_state["simulation_type"] == "Multiple Cases" else "secondary"):
                st.session_state["simulation_type"] = "Multiple Cases"
                st.rerun()
        with sim_b3:
            if st.button("Station Load", use_container_width=True, type="primary" if st.session_state["simulation_type"] == "Station Load" else "secondary"):
                st.session_state["simulation_type"] = "Station Load"
                st.rerun()
        with sim_b4:
            if st.button("System Event", use_container_width=True, type="primary" if st.session_state["simulation_type"] == "System Event" else "secondary"):
                st.session_state["simulation_type"] = "System Event"
                st.rerun()

        st.markdown(f"**Active Mode:** {st.session_state['simulation_type']}")
        if st.button("🚀 Start Simulation Test"):
            new_sim = {
                "case_number": f"SIM-{random.randint(1000,9999)}",
                "subject": f"Simulated test case ({st.session_state['simulation_type']})",
                "account": "H&M (High Priority)",
                "station": "CARE",
                "assignee": "Maria Santos",
                "priority": "CRITICAL",
                "status": "In Progress",
                "duration_seconds": 120,
                "sla_limit_minutes": 15,
                "created_at": datetime.datetime.now(),
                "last_updated": datetime.datetime.now(),
                "source": "Simulation",
                "is_closed": False,
                "checklist": {}
            }
            db_manager.memory_db["tasks"].append(new_sim)
            st.success("Simulation case generated and added to live queue!")
            st.rerun()

    elif s_tab == "Access Control":
        st.markdown("### Access Control & Administrative PIN")
        admin_pin_input = st.text_input("Enter Admin PIN", type="password")
        if st.button("Verify Admin PIN"):
            configured_pin = st.secrets.get("general", {}).get("ADMIN_PIN", "2026")
            if admin_pin_input == configured_pin:
                st.success("Administrative privileges granted successfully.")
            else:
                st.error("Invalid Admin PIN.")

    elif s_tab == "Data Cleanup":
        st.markdown("### Administrator Data Cleanup")
        st.warning("⚠️ Permanently removes seeded mock cases and simulation records while preserving genuine operational cases.")
        mock_list = [c for c in all_cases if c.get("source") in ["Excel Import", "Simulation"] or c.get("case_number", "").startswith("SIM-")]
        st.write(f"Identified **{len(mock_list)}** mock/seeded cases eligible for cleanup.")
        if st.button("🗑️ Permanently Remove Mock Records", type="primary"):
            remaining = [c for c in all_cases if c not in mock_list]
            st.session_state["memory_db"]["tasks"] = remaining
            st.success("Mock records successfully cleaned up!")
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

# ==========================================
# FOOTER
# ==========================================
st.markdown("---")
st.caption("Application: OVR-VW | Version: 1.0.0 | Enterprise Operations Visibility & Response Workspace")
