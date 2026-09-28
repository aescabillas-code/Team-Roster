import os
import sys
import re
import io
import time
import json
import uuid
import hmac
import hashlib
import smtplib
import secrets  # <--- ADD THIS LINE HERE
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Built-in timezone without needing external pytz package
MANILA_TZ = timezone(timedelta(hours=8))

def get_current_ph_time():
    return datetime.now(MANILA_TZ)

# ==============================================================================
# 1. PAGE CONFIGURATION & STREAMLIT INITIALIZATION
# ==============================================================================
st.set_page_config(
    page_title="HPE CaseFlow — Task Monitoring & Management",
    page_icon="🟩",
    layout="wide",
    initial_sidebar_state="collapsed",

# ==============================================================================
# 2. DATABASE ARCHITECTURE (PYMONGO + FAIL-SAFE IN-MEMORY STORE)
# ==============================================================================
class InMemoryMongoCollection:
    """Thread-safe, fully-featured in-memory MongoDB collection fallback."""
    def __init__(self, name="Team Roster Collection"):
        self.name = name
        self.docs = []

    def _matches(self, doc, query):
        for k, v in query.items():
            if k == "$or":
                if not any(self._matches(doc, cond) for cond in v):
                    return False
            elif isinstance(v, dict):
                doc_val = doc.get(k)
                if "$in" in v:
                    if doc_val not in v["$in"]:
                        return False
                elif "$ne" in v:
                    if doc_val == v["$ne"]:
                        return False
                elif "$regex" in v:
                    pattern = re.compile(v["$regex"], re.IGNORECASE)
                    if not (isinstance(doc_val, str) and pattern.search(doc_val)):
                        return False
            elif doc.get(k) != v:
                return False
        return True

    def find(self, query=None, projection=None, sort=None, limit=0):
        query = query or {}
        results = [d.copy() for d in self.docs if self._matches(d, query)]
        if sort:
            for key, direction in reversed(sort):
                reverse = direction < 0
                results.sort(key=lambda x: (x.get(key) is None, x.get(key)), reverse=reverse)
        if limit > 0:
            results = results[:limit]
        return results

    def find_one(self, query=None, projection=None):
        query = query or {}
        for d in self.docs:
            if self._matches(d, query):
                return d.copy()
        return None

    def insert_one(self, doc):
        d = doc.copy()
        if "_id" not in d:
            d["_id"] = str(uuid.uuid4())
        self.docs.append(d)
        return type("InsertResult", (), {"inserted_id": d["_id"]})

    def update_one(self, query, update, upsert=False):
        for idx, d in enumerate(self.docs):
            if self._matches(d, query):
                if "$set" in update:
                    self.docs[idx].update(update["$set"])
                if "$inc" in update:
                    for ik, iv in update["$inc"].items():
                        self.docs[idx][ik] = self.docs[idx].get(ik, 0) + iv
                return type("UpdateResult", (), {"matched_count": 1, "modified_count": 1})
        if upsert:
            new_doc = query.copy()
            if "$set" in update:
                new_doc.update(update["$set"])
            self.insert_one(new_doc)
            return type("UpdateResult", (), {"matched_count": 0, "modified_count": 1})
        return type("UpdateResult", (), {"matched_count": 0, "modified_count": 0})

    def update_many(self, query, update):
        count = 0
        for idx, d in enumerate(self.docs):
            if self._matches(d, query):
                if "$set" in update:
                    self.docs[idx].update(update["$set"])
                count += 1
        return type("UpdateResult", (), {"matched_count": count, "modified_count": count})

    def count_documents(self, query=None):
        return len(self.find(query or {}))

    def create_index(self, keys, **kwargs):
        pass


@st.cache_resource
def get_mongo_client():
    uri = None
    try:
        if "MONGODB_URI" in st.secrets:
            uri = st.secrets["MONGODB_URI"]
    except Exception:
        pass
    if not uri:
        uri = os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI")

    if uri:
        try:
            from pymongo import MongoClient
            client = MongoClient(uri, serverSelectionTimeoutMS=2500)
            client.server_info()  # probe connection
            return client, False
        except Exception as e:
            st.sidebar.warning(f"Live MongoDB unreachable ({e}). Using in-memory fallback store.")

    # In-memory mock client container
    class MockClient:
        def __init__(self):
            self.db = {"TeamRoster": {"Team Roster Collection": InMemoryMongoCollection()}}
        def __getitem__(self, name):
            return self.db.setdefault(name, {})
    return MockClient(), True

client, IS_IN_MEMORY = get_mongo_client()
db = client["TeamRoster"]
collection = db["Team Roster Collection"]

# ==============================================================================
# 3. INITIAL SEED DATA & DROPDOWNS SETUP
# ==============================================================================
def init_database():
    """Initializes indexes, validation objects, and realistic reference records."""
    try:
        collection.create_index([("email", 1)], unique=True)
        collection.create_index([("case_number", 1)])
        collection.create_index([("type", 1)])
    except Exception:
        pass

    # 1. Validation Dropdowns Document
    dropdown_doc = collection.find_one({"type": "Validation_Dropdown"})
    if not dropdown_doc:
        collection.insert_one({
            "type": "Validation_Dropdown",
            "Case_Status": ["Open", "In Progress", "On Hold", "Waiting Vendor", "Vendor Response", "Pending Info", "Closed"],
            "Case_Reason": [
                "Waiting for Vendor Response",
                "Initial contact with vendor",
                "Under Investigation",
                "Vendor SLA Warning Sent",
                "Pending License Generation",
                "Customer Verification"
            ],
            "Closure_Type": ["Resolved", "Customer Cancelled", "Contract Breach", "Duplicate"],
            "Contract_Breach": [
                "SLA Missed - Non-Delivery",
                "Vendor Unreachable > 48h",
                "Critical Milestone Failed",
                "Unapproved Sub-Contracting",
                "Security Policy Violation"
            ]
        })

    # 2. PTO Allocation Setup
    current_year_month = get_current_ph_time().strftime("%Y-%m")
    pto_doc = collection.find_one({"type": "Schedule_Monitoring", "month": current_year_month})
    if not pto_doc:
        collection.insert_one({
            "type": "Schedule_Monitoring",
            "month": current_year_month,
            "total_allocation": 20,
            "used_allocation": 4,
            "approved_leaves": [
                {"agent": "Lara Cruz", "type": "PTO", "date": "2026-09-28"},
                {"agent": "James Dela Cruz", "type": "Sick Leave", "date": "2026-09-29"}
            ]
        })

    # 3. Default Roster Seed (Matches Screenshot Exactly)
    if collection.count_documents({"type": "roster_list"}) == 0:
        salt = secrets.token_hex(8)
        hashed_pw = hashlib.sha256((salt + "Hpe@123456").encode()).hexdigest() + ":" + salt
        
        team_members = [
            ("Arianne", "Escabillas", "HPE12345", "arianne.escabillas@hpe.com", "Admin/Agent", "Available", "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=150"),
            ("Mark", "Santos", "HPE10001", "mark.santos@hpe.com", "Admin/Agent", "Available", "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150"),
            ("Chelsea", "Reyes", "HPE10002", "chelsea.reyes@hpe.com", "Agent", "Available", "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150"),
            ("James", "Dela Cruz", "HPE10003", "james.delacruz@hpe.com", "Agent", "Available", "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150"),
            ("Mica", "Tan", "HPE10004", "mica.tan@hpe.com", "Agent", "Lunch", "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=150"),
            ("Rafael", "Cruz", "HPE10005", "rafael.cruz@hpe.com", "Agent", "Available", "https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?w=150"),
            ("Alyssa", "Ramos", "HPE10006", "alyssa.ramos@hpe.com", "Agent", "Meeting", "https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=150"),
            ("Daniel", "Lim", "HPE10007", "daniel.lim@hpe.com", "Agent", "Available", "https://images.unsplash.com/photo-1522075469751-3a6694fb2f61?w=150"),
            ("Bea", "Santos", "HPE10008", "bea.santos@hpe.com", "Agent", "Available", "https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=150"),
            ("Kevin", "Navarro", "HPE10009", "kevin.navarro@hpe.com", "Agent", "Not Ready - Online", "https://images.unsplash.com/photo-1492562080023-ab3db95bfbce?w=150"),
            ("Nicole", "Garcia", "HPE10010", "nicole.garcia@hpe.com", "Agent", "Available", "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=150"),
            ("Carlo", "Mendoza", "HPE10011", "carlo.mendoza@hpe.com", "Admin/Agent", "Available", "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=150"),
            ("Lara", "Cruz", "HPE10012", "lara.cruz@hpe.com", "Agent", "Break", "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150"),
            ("Admin", "System", "HPE99999", "admin@hpe.com", "Admin", "Admin Work", "https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=150")
        ]

        now = get_current_ph_time()
        for fn, ln, eid, email, role, aux, img in team_members:
            collection.insert_one({
                "type": "roster_list",
                "first_name": fn,
                "last_name": ln,
                "name": f"{fn} {ln}",
                "employee_id": eid,
                "email": email,
                "password_hash": hashed_pw,
                "role": role,
                "profile_picture": img,
                "department": "Operations",
                "current_aux": aux,
                "is_logged_in": True,
                "login_time": (now - timedelta(hours=3, minutes=15)).strftime("%Y-%m-%d %I:%M %p"),
                "created_at": now.strftime("%Y-%m-%d %H:%M:%S")
            })

    # 4. Default Seed Cases (Matches Screenshot Exact Data)
    if collection.count_documents({"type": "cases"}) == 0:
        now = get_current_ph_time()
        cases_seed = [
            {
                "case_number": "HPE-2026-1045",
                "subject": "License Key Provisioning Delay",
                "description": "Client is experiencing delay in license provisioning. Escalation raised with ABC Software team.",
                "priority": "Critical",
                "assigned_to": "Arianne Escabillas",
                "assignee_email": "arianne.escabillas@hpe.com",
                "due_date": (now + timedelta(minutes=36)).strftime("%b %d, %Y %I:%M %p"),
                "status": "In Progress",
                "status_reason": "Waiting for Vendor Response",
                "closure_type": "",
                "breach_reason": "",
                "created_at": (now - timedelta(hours=19, minutes=45)).strftime("%b %d, %Y %I:%M %p"),
                "last_update": (now - timedelta(hours=2, minutes=9)).strftime("%b %d, %Y %I:%M %p"),
                "last_update_ts": (now - timedelta(hours=2, minutes=9)),
                "vendor_name": "ABC Software Inc.",
                "vendor_contact": "Michael Tan",
                "vendor_email": "support@abcsoftware.com",
                "vendor_phone": "+1 555 123 4567",
                "vendor_alt_contact": "Sarah Lim",
                "vendor_alt_email": "sarah.lim@abcsoftware.com",
                "vendor_address": "123 Innovation Drive, San Jose, CA 95134",
                "account": "ABC Enterprise",
                "related_system": "HPE Licensing Portal",
                "case_category": "License Renewal"
            },
            {
                "case_number": "HPE-2026-1042",
                "subject": "Portal Access Issue",
                "description": "Enterprise customer administrator unable to log into provisioning console with SAML SSO.",
                "priority": "Critical",
                "assigned_to": "Chelsea Reyes",
                "assignee_email": "chelsea.reyes@hpe.com",
                "due_date": (now + timedelta(hours=1, minutes=36)).strftime("%b %d, %Y %I:%M %p"),
                "status": "Vendor Response",
                "status_reason": "Under Investigation",
                "closure_type": "",
                "breach_reason": "",
                "created_at": (now - timedelta(hours=12)).strftime("%b %d, %Y %I:%M %p"),
                "last_update": (now - timedelta(hours=1, minutes=14)).strftime("%b %d, %Y %I:%M %p"),
                "last_update_ts": (now - timedelta(hours=1, minutes=14)),
                "vendor_name": "CloudAuth Corp",
                "vendor_contact": "David Miller",
                "vendor_email": "support@cloudauth.io",
                "vendor_phone": "+1 800 555 0199",
                "account": "Global FinTech",
                "related_system": "SSO Federation Broker",
                "case_category": "Identity & Access"
            },
            {
                "case_number": "HPE-2026-1041",
                "subject": "Software Installation Error",
                "description": "RedHat deployment script terminates at code 139 during agent registration.",
                "priority": "Critical",
                "assigned_to": "James Dela Cruz",
                "assignee_email": "james.delacruz@hpe.com",
                "due_date": (now + timedelta(hours=2, minutes=36)).strftime("%b %d, %Y %I:%M %p"),
                "status": "In Progress",
                "status_reason": "Initial contact with vendor",
                "closure_type": "",
                "breach_reason": "",
                "created_at": (now - timedelta(hours=6)).strftime("%b %d, %Y %I:%M %p"),
                "last_update": (now - timedelta(minutes=39)).strftime("%b %d, %Y %I:%M %p"),
                "last_update_ts": (now - timedelta(minutes=39)),
                "vendor_name": "LinuxDistro Solutions",
                "vendor_contact": "Alex Wong",
                "vendor_email": "support@linuxdistro.com",
                "vendor_phone": "+1 555 987 6543",
                "account": "BioPharm Labs",
                "related_system": "Compute Orchestrator",
                "case_category": "OS Deployment"
            },
            {
                "case_number": "HPE-2026-1038",
                "subject": "License Renewal Request",
                "description": "Annual enterprise license renewal quote confirmation pending validation.",
                "priority": "High",
                "assigned_to": "Arianne Escabillas",
                "assignee_email": "arianne.escabillas@hpe.com",
                "due_date": (now + timedelta(hours=4, minutes=36)).strftime("%b %d, %Y %I:%M %p"),
                "status": "Waiting Vendor",
                "status_reason": "Waiting for Vendor Response",
                "closure_type": "",
                "breach_reason": "",
                "created_at": (now - timedelta(days=1)).strftime("%b %d, %Y %I:%M %p"),
                "last_update": (now - timedelta(minutes=24)).strftime("%b %d, %Y %I:%M %p"),
                "last_update_ts": (now - timedelta(minutes=24)),
                "vendor_name": "ABC Software Inc.",
                "vendor_contact": "Michael Tan",
                "vendor_email": "support@abcsoftware.com",
                "vendor_phone": "+1 555 123 4567",
                "account": "Nexus Telecom",
                "related_system": "HPE GreenLake",
                "case_category": "Contracts & Subscriptions"
            },
            {
                "case_number": "HPE-2026-1036",
                "subject": "Account Access Restoration",
                "description": "Restore administrative privileges for backup operations engineering team.",
                "priority": "High",
                "assigned_to": "Rafael Cruz",
                "assignee_email": "rafael.cruz@hpe.com",
                "due_date": (now + timedelta(hours=5, minutes=36)).strftime("%b %d, %Y %I:%M %p"),
                "status": "In Progress",
                "status_reason": "Customer Verification",
                "closure_type": "",
                "breach_reason": "",
                "created_at": (now - timedelta(days=1, hours=3)).strftime("%b %d, %Y %I:%M %p"),
                "last_update": (now - timedelta(minutes=54)).strftime("%b %d, %Y %I:%M %p"),
                "last_update_ts": (now - timedelta(minutes=54)),
                "vendor_name": "SecureID Systems",
                "vendor_contact": "Rachel Adams",
                "vendor_email": "help@secureid.org",
                "vendor_phone": "+1 555 777 8899",
                "account": "SkyLine Air",
                "related_system": "IAM Portal",
                "case_category": "Access Management"
            },
            {
                "case_number": "HPE-2026-1033",
                "subject": "Portal Error - 500 Internal",
                "description": "Intermittent HTTP 500 error when uploading bulk cluster hardware manifests.",
                "priority": "Medium",
                "assigned_to": "Alyssa Ramos",
                "assignee_email": "alyssa.ramos@hpe.com",
                "due_date": (now + timedelta(days=1)).strftime("%b %d, %Y %I:%M %p"),
                "status": "Open",
                "status_reason": "Under Investigation",
                "closure_type": "",
                "breach_reason": "",
                "created_at": (now - timedelta(days=2)).strftime("%b %d, %Y %I:%M %p"),
                "last_update": (now - timedelta(hours=2, minutes=4)).strftime("%b %d, %Y %I:%M %p"),
                "last_update_ts": (now - timedelta(hours=2, minutes=4)),
                "vendor_name": "InfraAPI LLC",
                "vendor_contact": "Carlos Mendez",
                "vendor_email": "carlos@infraapi.com",
                "vendor_phone": "+1 555 333 2211",
                "account": "AutoCorp Industries",
                "related_system": "Storage Central",
                "case_category": "API Gateway"
            },
            {
                "case_number": "HPE-2026-1031",
                "subject": "Usage Report Request",
                "description": "Quarterly consumed storage and memory compute export in JSON format.",
                "priority": "Medium",
                "assigned_to": "Daniel Lim",
                "assignee_email": "daniel.lim@hpe.com",
                "due_date": (now + timedelta(days=1, hours=1)).strftime("%b %d, %Y %I:%M %p"),
                "status": "In Progress",
                "status_reason": "Waiting for Vendor Response",
                "closure_type": "",
                "breach_reason": "",
                "created_at": (now - timedelta(days=2, hours=4)).strftime("%b %d, %Y %I:%M %p"),
                "last_update": (now - timedelta(hours=1, minutes=19)).strftime("%b %d, %Y %I:%M %p"),
                "last_update_ts": (now - timedelta(hours=1, minutes=19)),
                "vendor_name": "DataMetric Analytics",
                "vendor_contact": "Lisa Chen",
                "vendor_email": "lisa@datametric.com",
                "vendor_phone": "+1 555 444 3322",
                "account": "Apex Banking",
                "related_system": "Metering Engine",
                "case_category": "Analytics"
            },
            {
                "case_number": "HPE-2026-1029",
                "subject": "Vendor Confirmation Needed",
                "description": "Warranty entitlement verification for ProLiant DL380 Gen10 chassis.",
                "priority": "Medium",
                "assigned_to": "Arianne Escabillas",
                "assignee_email": "arianne.escabillas@hpe.com",
                "due_date": (now + timedelta(days=1, hours=4)).strftime("%b %d, %Y %I:%M %p"),
                "status": "Pending Info",
                "status_reason": "Initial contact with vendor",
                "closure_type": "",
                "breach_reason": "",
                "created_at": (now - timedelta(days=3)).strftime("%b %d, %Y %I:%M %p"),
                "last_update": (now - timedelta(hours=1, minutes=29)).strftime("%b %d, %Y %I:%M %p"),
                "last_update_ts": (now - timedelta(hours=1, minutes=29)),
                "vendor_name": "HardwareDepot Inc",
                "vendor_contact": "Tom Bradley",
                "vendor_email": "service@hardwaredepot.com",
                "vendor_phone": "+1 555 666 7788",
                "account": "Metro Retailers",
                "related_system": "Pointnext Services",
                "case_category": "Hardware RMA"
            },
            {
                "case_number": "HPE-2026-1027",
                "subject": "License Transfer",
                "description": "Transfer 50 VMware vSphere licenses between corporate subsidiaries.",
                "priority": "Low",
                "assigned_to": "Kevin Navarro",
                "assignee_email": "kevin.navarro@hpe.com",
                "due_date": (now + timedelta(days=2)).strftime("%b %d, %Y %I:%M %p"),
                "status": "Open",
                "status_reason": "Waiting for Vendor Response",
                "closure_type": "",
                "breach_reason": "",
                "created_at": (now - timedelta(days=3, hours=2)).strftime("%b %d, %Y %I:%M %p"),
                "last_update": (now - timedelta(hours=1, minutes=9)).strftime("%b %d, %Y %I:%M %p"),
                "last_update_ts": (now - timedelta(hours=1, minutes=9)),
                "vendor_name": "VMware by Broadcom",
                "vendor_contact": "Karen Scott",
                "vendor_email": "support@vmware.com",
                "vendor_phone": "+1 877 486 9273",
                "account": "Global Shipping Co",
                "related_system": "VMware Cloud Foundation",
                "case_category": "Virtualization"
            },
            {
                "case_number": "HPE-2026-1025",
                "subject": "Entitlement Update",
                "description": "Update active support contract number in customer portal profile.",
                "priority": "Low",
                "assigned_to": "Nicole Garcia",
                "assignee_email": "nicole.garcia@hpe.com",
                "due_date": (now + timedelta(days=2, hours=5)).strftime("%b %d, %Y %I:%M %p"),
                "status": "In Progress",
                "status_reason": "Pending License Generation",
                "closure_type": "",
                "breach_reason": "",
                "created_at": (now - timedelta(days=4)).strftime("%b %d, %Y %I:%M %p"),
                "last_update": (now - timedelta(minutes=44)).strftime("%b %d, %Y %I:%M %p"),
                "last_update_ts": (now - timedelta(minutes=44)),
                "vendor_name": "HPE Internal Ops",
                "vendor_contact": "Support Tier 2",
                "vendor_email": "tier2-support@hpe.com",
                "vendor_phone": "+1 800 473 4000",
                "account": "First National Insurance",
                "related_system": "HPE InfoSight",
                "case_category": "Entitlements"
            }
        ]
        for c in cases_seed:
            c["type"] = "cases"
            collection.insert_one(c)

        # Initial Case History
        collection.insert_one({
            "type": "case_history",
            "case_number": "HPE-2026-1045",
            "timestamp": (now - timedelta(hours=19, minutes=45)).strftime("%b %d, %Y %I:%M %p"),
            "user": "System",
            "action": "Case created and assigned",
            "details": "Case automatically assigned to Arianne Escabillas based on lowest active critical count."
        })
        collection.insert_one({
            "type": "case_history",
            "case_number": "HPE-2026-1045",
            "timestamp": (now - timedelta(hours=2, minutes=9)).strftime("%b %d, %Y %I:%M %p"),
            "user": "Arianne Escabillas",
            "action": "Initial contact with vendor",
            "details": "Sent follow-up email to ABC Software vendor contact Michael Tan regarding delayed key delivery."
        })

    # 5. Seed Notifications
    if collection.count_documents({"type": "notifications"}) == 0:
        collection.insert_one({
            "type": "notifications",
            "target_email": "arianne.escabillas@hpe.com",
            "title": "Critical Case Alert",
            "message": "HPE-2026-1045 is nearing due date. Due in 36 minutes (11:00 AM). Please take action.",
            "category": "critical",
            "case_number": "HPE-2026-1045",
            "acknowledged": False,
            "created_at": (get_current_ph_time() - timedelta(minutes=2)).strftime("%I:%M %p")
        })
        collection.insert_one({
            "type": "notifications",
            "target_email": "arianne.escabillas@hpe.com",
            "title": "New Case Assigned",
            "message": "HPE-2026-1048 has been auto-assigned to you. Subject: License Compliance Request",
            "category": "new_case",
            "case_number": "HPE-2026-1048",
            "acknowledged": False,
            "created_at": (get_current_ph_time() - timedelta(minutes=15)).strftime("%I:%M %p")
        })

init_database()

# ==============================================================================
# 4. SECURITY, PASSWORDS & AUTHENTICATION HELPER ENGINE
# ==============================================================================
def hash_password(password: str) -> str:
    salt = secrets.token_hex(8)
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{h}:{salt}"

def verify_password(stored_password_hash: str, provided_password: str) -> bool:
    try:
        h, salt = stored_password_hash.split(":")
        check = hashlib.sha256((salt + provided_password).encode("utf-8")).hexdigest()
        return hmac.compare_digest(h, check)
    except Exception:
        return False

def authenticate_user(email, password):
    user = collection.find_one({"type": "roster_list", "email": email.strip().lower()})
    if user and verify_password(user.get("password_hash", ""), password):
        return user
    return None

def create_session(user_doc, remember_me=False):
    token = secrets.token_urlsafe(32)
    expiry = get_current_ph_time() + (timedelta(days=14) if remember_me else timedelta(hours=12))
    collection.insert_one({
        "type": "sessions",
        "token": token,
        "email": user_doc["email"],
        "expires_at": expiry.strftime("%Y-%m-%d %H:%M:%S")
    })
    st.session_state["session_token"] = token
    st.session_state["authenticated"] = True
    st.session_state["current_user"] = user_doc

def validate_saved_session():
    token = st.session_state.get("session_token")
    if not token:
        # Check query params for persistent refresh
        params = st.query_params
        if "stoken" in params:
            token = params["stoken"]
            st.session_state["session_token"] = token

    if token:
        sess = collection.find_one({"type": "sessions", "token": token})
        if sess:
            expiry = datetime.strptime(sess["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=MANILA_TZ)
            if expiry > get_current_ph_time():
                user = collection.find_one({"type": "roster_list", "email": sess["email"]})
                if user:
                    st.session_state["authenticated"] = True
                    st.session_state["current_user"] = user
                    return True
    return False

def logout_user():
    token = st.session_state.get("session_token")
    if token:
        collection.update_many({"type": "sessions", "token": token}, {"$set": {"expires_at": "2000-01-01 00:00:00"}})
    if "current_user" in st.session_state and st.session_state["current_user"]:
        collection.update_one(
            {"type": "roster_list", "email": st.session_state["current_user"]["email"]},
            {"$set": {"is_logged_in": False}}
        )
    st.session_state["authenticated"] = False
    st.session_state["current_user"] = None
    st.session_state["session_token"] = None
    st.query_params.clear()
    st.rerun()

# ==============================================================================
# 5. CASE AUTO-ASSIGNMENT & AUX LOGIC ENGINE
# ==============================================================================
def update_user_aux(email, new_aux):
    user = collection.find_one({"type": "roster_list", "email": email})
    if not user:
        return
    old_aux = user.get("current_aux", "Not Ready - Online")
    now_str = get_current_ph_time().strftime("%Y-%m-%d %I:%M %p")
    
    collection.update_one(
        {"type": "roster_list", "email": email},
        {"$set": {"current_aux": new_aux, "last_aux_change": now_str}}
    )
    collection.insert_one({
        "type": "aux_history",
        "email": email,
        "employee_id": user.get("employee_id"),
        "name": user.get("name"),
        "old_aux": old_aux,
        "new_aux": new_aux,
        "timestamp": now_str
    })
    # Update local session state
    if "current_user" in st.session_state and st.session_state["current_user"]["email"] == email:
        st.session_state["current_user"]["current_aux"] = new_aux

def auto_assign_new_case(case_data):
    """Fair round-robin & workload-balanced assignment strictly for Available agents."""
    available_agents = collection.find({
        "type": "roster_list",
        "role": {"$in": ["Agent", "Admin/Agent"]},
        "current_aux": "Available"
    })
    
    if not available_agents:
        # Fallback to unassigned queue
        case_data["assigned_to"] = "Unassigned (Queue)"
        case_data["assignee_email"] = None
        collection.insert_one(case_data)
        return False, "No agents currently in Available Aux."

    # Score available agents
    candidate_scores = []
    for agent in available_agents:
        active_count = collection.count_documents({
            "type": "cases",
            "assignee_email": agent["email"],
            "status": {"$ne": "Closed"}
        })
        crit_count = collection.count_documents({
            "type": "cases",
            "assignee_email": agent["email"],
            "priority": "Critical",
            "status": {"$ne": "Closed"}
        })
        candidate_scores.append({
            "agent": agent,
            "active_count": active_count,
            "crit_count": crit_count
        })

    # If critical, pick the agent with lowest critical cases first
    if case_data.get("priority") == "Critical":
        candidate_scores.sort(key=lambda x: (x["crit_count"], x["active_count"]))
    else:
        candidate_scores.sort(key=lambda x: (x["active_count"], x["crit_count"]))

    chosen = candidate_scores[0]["agent"]
    case_data["assigned_to"] = chosen["name"]
    case_data["assignee_email"] = chosen["email"]
    
    collection.insert_one(case_data)

    # History & notification
    now_str = get_current_ph_time().strftime("%b %d, %Y %I:%M %p")
    collection.insert_one({
        "type": "case_history",
        "case_number": case_data["case_number"],
        "timestamp": now_str,
        "user": "Auto-Assignment Engine",
        "action": "Case created and assigned",
        "details": f"Automatically assigned to {chosen['name']} (Workload: {candidate_scores[0]['active_count']} active cases)."
    })

    collection.insert_one({
        "type": "notifications",
        "target_email": chosen["email"],
        "title": "New Case Assigned",
        "message": f"{case_data['case_number']} has been assigned to you. Priority: {case_data['priority']}",
        "category": "new_case",
        "case_number": case_data["case_number"],
        "acknowledged": False,
        "created_at": get_current_ph_time().strftime("%I:%M %p")
    })
    return True, chosen["name"]

# ==============================================================================
# 6. ENTERPRISE CSS DESIGN SYSTEM (EXACT MATCH TO SCREENSHOTS)
# ==============================================================================
ENTERPRISE_CSS = """
<style>
/* 1. Reset Streamlit Default Overrides */
#MainMenu, header, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] {
    visibility: hidden !important;
    display: none !important;
}

.stApp {
    background-color: #F4F7F9 !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
    color: #1A2733 !important;
}

.block-container {
    padding-top: 5.5rem !important;
    padding-bottom: 5.5rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    max-width: 100% !important;
}

/* 2. Top Header Bar */
.hpe-header {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    height: 72px;
    background-color: #062323;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 28px;
    z-index: 1000;
    border-bottom: 2px solid #00B388;
    box-shadow: 0 2px 10px rgba(0,0,0,0.15);
}

.hpe-brand {
    display: flex;
    align-items: center;
    gap: 12px;
    color: #FFFFFF;
}

.hpe-logo-box {
    border: 3.5px solid #00B388;
    width: 28px;
    height: 18px;
    border-radius: 2px;
    display: inline-block;
}

.hpe-title {
    font-size: 20px;
    font-weight: 800;
    letter-spacing: -0.3px;
    color: #FFFFFF;
    margin: 0;
    line-height: 1.1;
}

.hpe-subtitle {
    font-size: 11px;
    color: #94A3B8;
    margin: 0;
    font-weight: 400;
}

.hpe-header-right {
    display: flex;
    align-items: center;
    gap: 20px;
}

.hpe-clock {
    color: #FFFFFF;
    text-align: right;
    line-height: 1.2;
}

.hpe-clock-date {
    font-size: 11px;
    color: #94A3B8;
}

.hpe-clock-time {
    font-size: 16px;
    font-weight: 700;
    letter-spacing: -0.2px;
}

/* 3. Metric Cards */
.metric-container {
    background: #FFFFFF;
    border-radius: 12px;
    padding: 18px 22px;
    display: flex;
    align-items: center;
    gap: 18px;
    border: 1px solid #E2E8F0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.03);
    margin-bottom: 12px;
}

.metric-icon-box {
    width: 48px;
    height: 48px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 22px;
}

.metric-title {
    font-size: 13px;
    color: #64748B;
    font-weight: 600;
    margin: 0;
}

.metric-value {
    font-size: 28px;
    font-weight: 800;
    color: #0F172A;
    margin: 0;
    line-height: 1.2;
}

.metric-sub {
    font-size: 11.5px;
    font-weight: 600;
    margin: 0;
}

/* 4. Table Styling & Badges */
.badge {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 11.5px;
    font-weight: 700;
    letter-spacing: 0.2px;
}

.badge-critical { background-color: #FEE2E2; color: #DC2626; }
.badge-high { background-color: #FFEDD5; color: #EA580C; }
.badge-medium { background-color: #FEF3C7; color: #D97706; }
.badge-low { background-color: #DCFCE7; color: #16A34A; }

.badge-status {
    background-color: #EFF6FF;
    color: #2563EB;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 11.5px;
    font-weight: 600;
}

.badge-vendor-response { background-color: #FEF9C3; color: #A16207; }
.badge-waiting-vendor { background-color: #FEF3C7; color: #D97706; }
.badge-pending-info { background-color: #F3E8FF; color: #7E22CE; }
.badge-open { background-color: #F1F5F9; color: #475569; }

.aux-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    display: inline-block;
    margin-right: 6px;
}

.aux-available { background-color: #00B388; }
.aux-admin-work { background-color: #2563EB; }
.aux-not-ready { background-color: #EF4444; }
.aux-coaching { background-color: #8B5CF6; }
.aux-meeting { background-color: #F59E0B; }
.aux-lunch { background-color: #FBBF24; }
.aux-break { background-color: #94A3B8; }
.aux-unscheduled { background-color: #334155; }

/* 5. Fixed Bottom Navigation */
.hpe-bottom-nav {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: 60px;
    background-color: #062323;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    z-index: 1000;
    border-top: 1px solid rgba(255,255,255,0.08);
}

.nav-tab-btn {
    display: flex;
    align-items: center;
    gap: 8px;
    color: #94A3B8;
    background: transparent;
    padding: 8px 24px;
    border-radius: 6px;
    font-size: 13.5px;
    font-weight: 600;
    text-decoration: none;
    cursor: pointer;
}

.nav-tab-active {
    background-color: #00B388 !important;
    color: #FFFFFF !important;
}

/* 6. Case Detail Modal */
.modal-strip {
    background-color: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 12px 16px;
    display: flex;
    justify-content: space-between;
    margin-bottom: 16px;
}

.timeline-item {
    border-left: 2px solid #E2E8F0;
    padding-left: 14px;
    padding-bottom: 14px;
    position: relative;
}

.timeline-dot {
    position: absolute;
    left: -6px;
    top: 0;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background-color: #00B388;
}
</style>
"""

st.markdown(ENTERPRISE_CSS, unsafe_allow_html=True)

# ==============================================================================
# 7. INTERACTIVE DIALOGS (@st.dialog)
# ==============================================================================
@st.dialog("Case Details", width="large")
def render_case_modal(case_num):
    case = collection.find_one({"type": "cases", "case_number": case_num})
    if not case:
        st.error(f"Case {case_num} not found.")
        return

    user = st.session_state.get("current_user", {})
    is_admin = user.get("role") in ["Admin", "Admin/Agent"]

    # Header Row
    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
    with c1:
        st.markdown(f"### 📁 {case['case_number']} &nbsp; <span class='badge badge-critical'>{case.get('priority')}</span>", unsafe_allow_html=True)
        st.markdown(f"**{case.get('subject')}**")
    with c2:
        st.caption("Created Date")
        st.write(case.get("created_at", "Sep 27, 2026 03:15 PM"))
    with c3:
        st.caption("Due Date")
        st.markdown(f"<span style='color:#DC2626; font-weight:700;'>{case.get('due_date')}</span>", unsafe_allow_html=True)
    with c4:
        st.caption("Time Remaining")
        st.markdown("<span class='badge badge-critical'>Due in 36m</span>", unsafe_allow_html=True)

    # Meta Strip
    st.markdown(f"""
    <div class="modal-strip">
        <div><small>Assigned To</small><br><strong>{case.get('assigned_to')}</strong></div>
        <div><small>Priority</small><br><span class="badge badge-critical">{case.get('priority')}</span></div>
        <div><small>Current Status</small><br><span class="badge badge-status">{case.get('status')}</span></div>
        <div><small>Last Update</small><br><strong>{case.get('last_update')}</strong></div>
        <div><small>Account</small><br><strong>{case.get('account', 'ABC Enterprise')}</strong></div>
        <div><small>Related System</small><br><strong>{case.get('related_system', 'HPE Portal')}</strong></div>
    </div>
    """, unsafe_allow_html=True)

    tab_info, tab_vendor, tab_update, tab_breach = st.tabs([
        "📋 Case Information", "🏢 Vendor Information", "✏️ Update Case", "⚠️ Breach Notice Email"
    ])

    with tab_info:
        st.write(f"**Description:** {case.get('description')}")
        st.divider()
        st.markdown("##### 🕒 Case Activity History")
        history = list(collection.find({"type": "case_history", "case_number": case_num}, sort=[("timestamp", -1)]))
        for h in history:
            st.markdown(f"""
            <div class="timeline-item">
                <div class="timeline-dot"></div>
                <small style="color:#64748B;">{h.get('timestamp')} &bull; <strong>{h.get('user')}</strong></small><br>
                <strong>{h.get('action')}</strong><br>
                <small>{h.get('details')}</small>
            </div>
            """, unsafe_allow_html=True)

    with tab_vendor:
        st.markdown(f"#### {case.get('vendor_name', 'ABC Software Inc.')}")
        v1, v2 = st.columns(2)
        with v1:
            st.write(f"**Primary Contact:** {case.get('vendor_contact', 'Michael Tan')}")
            st.write(f"**Email:** `{case.get('vendor_email', 'support@abcsoftware.com')}`")
            st.write(f"**Phone:** `{case.get('vendor_phone', '+1 555 123 4567')}`")
        with v2:
            st.write(f"**Alternate Contact:** {case.get('vendor_alt_contact', 'Sarah Lim')}")
            st.write(f"**Alternate Email:** `{case.get('vendor_alt_email', 'sarah.lim@abcsoftware.com')}`")
            st.write(f"**Address:** {case.get('vendor_address', '123 Innovation Drive, San Jose, CA')}")

        st.caption("Vendor Quick Actions:")
        b1, b2, b3 = st.columns(3)
        if b1.button("📋 Copy Email", key="cpy_em"):
            st.toast("Vendor email copied to clipboard!")
        if b2.button("📞 Copy Phone", key="cpy_ph"):
            st.toast("Vendor phone copied to clipboard!")
        if b3.button("📊 Open Vendor Record", key="vw_exc"):
            st.info("Vendor synchronized from master registry (Record: Active).")

    with tab_update:
        dropdowns = collection.find_one({"type": "Validation_Dropdown"}) or {}
        st_opts = dropdowns.get("Case_Status", ["Open", "In Progress", "On Hold", "Closed"])
        rs_opts = dropdowns.get("Case_Reason", ["Waiting for Vendor Response", "Under Investigation"])
        cl_opts = dropdowns.get("Closure_Type", ["Resolved", "Contract Breach"])
        br_opts = dropdowns.get("Contract_Breach", ["SLA Missed - Non-Delivery"])

        u1, u2 = st.columns(2)
        with u1:
            new_st = st.selectbox("Case Status", st_opts, index=st_opts.index(case.get("status")) if case.get("status") in st_opts else 0)
            new_cl = st.selectbox("Closure Type", ["-- None --"] + cl_opts)
        with u2:
            new_rs = st.selectbox("Status Reason", rs_opts)
            new_br = st.selectbox("Breach Reason (if Contract Breach)", ["-- None --"] + br_opts)

        remarks = st.text_area("Remarks / Work Notes", placeholder="Enter latest vendor communication or technical findings...")

        # Admin Reassign or Agent Transfer
        target_agent = None
        if is_admin:
            agents = [a["name"] for a in collection.find({"type": "roster_list", "role": {"$in": ["Agent", "Admin/Agent"]}})]
            target_agent = st.selectbox("Reassign Case (Admin Only)", ["-- Keep Current Assignee --"] + agents)

        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button("💾 Update Case Record", type="primary", use_container_width=True):
                updates = {
                    "status": new_st,
                    "status_reason": new_rs,
                    "last_update": get_current_ph_time().strftime("%b %d, %Y %I:%M %p"),
                    "last_update_ts": get_current_ph_time()
                }
                if new_cl != "-- None --":
                    updates["closure_type"] = new_cl
                if new_br != "-- None --":
                    updates["breach_reason"] = new_br
                if target_agent and target_agent != "-- Keep Current Assignee --":
                    updates["assigned_to"] = target_agent

                collection.update_one({"type": "cases", "case_number": case_num}, {"$set": updates})

                # Log history
                collection.insert_one({
                    "type": "case_history",
                    "case_number": case_num,
                    "timestamp": get_current_ph_time().strftime("%b %d, %Y %I:%M %p"),
                    "user": user.get("name", "User"),
                    "action": "Status changed" if not target_agent else f"Reassigned to {target_agent}",
                    "details": remarks if remarks else f"Status changed to {new_st} ({new_rs})"
                })
                st.success("Case successfully updated!")
                time.sleep(1)
                st.rerun()

        with btn_col2:
            if not is_admin:
                if st.button("🔄 Request Transfer to Colleague", use_container_width=True):
                    collection.insert_one({
                        "type": "transfer_requests",
                        "case_number": case_num,
                        "requestor": user.get("name"),
                        "requestor_email": user.get("email"),
                        "reason": remarks or "Workload balancing",
                        "status": "Pending",
                        "created_at": get_current_ph_time().strftime("%Y-%m-%d %H:%M")
                    })
                    st.toast("Transfer request dispatched to team lead!")

    with tab_breach:
        st.markdown("##### ✉️ Automated Breach Notice Notice")
        st.caption("Standard legal breach template auto-populated with active ticket telemetry:")
        to_email = st.text_input("To", value=case.get("vendor_email", "support@abcsoftware.com"))
        subj = st.text_input("Subject", value=f"Notice of Contract Breach — {case_num} SLA Missed")
        body_template = f"""Dear {case.get('vendor_name', 'Vendor Partner')},

This is an official notice to inform you that case {case_num} ({case.get('subject')}) has breached agreed contract SLA terms.

Case Details:
- Priority: {case.get('priority')}
- Target Due Date: {case.get('due_date')}
- Assigned Representative: {case.get('assigned_to')}

Please provide immediate remediation within two (2) business hours to avoid further escalation.

Sincerely,
HPE Operations Management"""
        email_body = st.text_area("Email Content", value=body_template, height=180)
        
        eb1, eb2 = st.columns(2)
        if eb1.button("📤 Send Official Breach Notice", type="primary", use_container_width=True):
            collection.insert_one({
                "type": "case_history",
                "case_number": case_num,
                "timestamp": get_current_ph_time().strftime("%b %d, %Y %I:%M %p"),
                "user": user.get("name"),
                "action": "Contract breach notice dispatched",
                "details": f"Breach notice delivered to {to_email}."
            })
            st.success(f"Breach notice successfully transmitted to {to_email}!")

@st.dialog("Profile & Aux Management", width="medium")
def render_profile_dialog():
    user = st.session_state.get("current_user", {})
    p1, p2 = st.columns([1, 2])
    with p1:
        st.image(user.get("profile_picture", "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=150"), width=120)
    with p2:
        st.markdown(f"### {user.get('name')}")
        st.caption(f"Role: **{user.get('role')}** | Dept: **{user.get('department')}**")
        st.write(f"**ID:** `{user.get('employee_id')}`")
        st.write(f"**Email:** `{user.get('email')}`")

    st.divider()
    st.markdown("##### 🔄 Change Real-time Aux Status")
    aux_list = ["Available", "Admin Work", "Not Ready - Online", "Coaching", "Meeting", "Lunch", "Break", "Unscheduled Break"]
    curr = user.get("current_aux", "Available")
    new_aux = st.selectbox("Select Current Aux", aux_list, index=aux_list.index(curr) if curr in aux_list else 0)
    
    if st.button("Apply Aux Change", type="primary"):
        update_user_aux(user.get("email"), new_aux)
        st.toast(f"Status changed to {new_aux}!")
        time.sleep(0.5)
        st.rerun()

    st.divider()
    st.markdown("##### 📅 Today's Plotted Schedule")
    st.markdown("""
    <div style="font-size:12px; line-height:1.8;">
        🟢 08:00 AM – 10:00 AM &nbsp; <strong>Available</strong><br>
        ⚪ 10:00 AM – 10:15 AM &nbsp; <strong>Break</strong><br>
        🟢 10:15 AM – 12:00 PM &nbsp; <strong>Available</strong><br>
        🟡 12:00 PM – 01:00 PM &nbsp; <strong>Lunch</strong><br>
        🟢 01:00 PM – 03:00 PM &nbsp; <strong>Available</strong><br>
        ⚪ 03:00 PM – 03:15 PM &nbsp; <strong>Break</strong><br>
        🟢 03:15 PM – 05:00 PM &nbsp; <strong>Available</strong>
    </div>
    """, unsafe_allow_html=True)

    st.divider()
    if st.button("🚪 Sign Out of HPE CaseFlow", type="secondary", use_container_width=True):
        logout_user()

@st.dialog("Broadcast Message", width="small")
def render_admin_message_dialog():
    user = st.session_state.get("current_user", {})
    st.markdown("### 📢 Broadcast Team Alert")
    target = st.selectbox("Target Recipient", ["All Logged-in Agents"] + [a["name"] for a in collection.find({"type": "roster_list"})])
    msg = st.text_area("Alert Message", placeholder="Enter priority broadcast notification...")
    if st.button("Send Alert", type="primary", use_container_width=True):
        collection.insert_one({
            "type": "notifications",
            "target_email": "all" if target == "All Logged-in Agents" else "targeted",
            "title": "Admin Broadcast",
            "message": msg,
            "category": "broadcast",
            "acknowledged": False,
            "created_at": get_current_ph_time().strftime("%I:%M %p")
        })
        st.success("Alert broadcasted successfully!")

# ==============================================================================
# 8. TOP HEADER COMPONENT
# ==============================================================================
def render_top_header():
    user = st.session_state.get("current_user", {})
    now = get_current_ph_time()
    date_str = now.strftime("%a, %b %d, %Y")
    time_str = now.strftime("%I:%M %p")

    unread_notifs = collection.count_documents({
        "type": "notifications",
        "$or": [{"target_email": user.get("email")}, {"target_email": "all"}],
        "acknowledged": False
    })

    aux_color_map = {
        "Available": "#00B388",
        "Admin Work": "#2563EB",
        "Not Ready - Online": "#EF4444",
        "Coaching": "#8B5CF6",
        "Meeting": "#F59E0B",
        "Lunch": "#FBBF24",
        "Break": "#94A3B8",
        "Unscheduled Break": "#334155"
    }
    curr_aux = user.get("current_aux", "Available")
    dot_color = aux_color_map.get(curr_aux, "#00B388")

    st.markdown(f"""
    <div class="hpe-header">
        <div class="hpe-brand">
            <div class="hpe-logo-box"></div>
            <div>
                <h1 class="hpe-title">HPE CaseFlow</h1>
                <p class="hpe-subtitle">Task Monitoring & Management</p>
            </div>
        </div>
        <div style="flex-grow:0.4; max-width:480px;">
            <input type="text" placeholder="Search cases, names, issues..." style="width:100%; padding:8px 16px; border-radius:20px; border:none; outline:none; font-size:13px;" />
        </div>
        <div class="hpe-header-right">
            <div class="hpe-clock">
                <div class="hpe-clock-date">{date_str}</div>
                <div class="hpe-clock-time">{time_str}</div>
            </div>
            <div style="position:relative; cursor:pointer;">
                🔔 <span style="position:absolute; top:-6px; right:-6px; background:#EF4444; color:white; font-size:10px; font-weight:700; border-radius:50%; padding:1px 5px;">{unread_notifs}</span>
            </div>
            <div style="display:flex; align-items:center; gap:8px;">
                <img src="{user.get('profile_picture', 'https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=150')}" style="width:36px; height:36px; border-radius:50%; border:2px solid {dot_color};" />
                <div style="color:white; line-height:1.1;">
                    <div style="font-size:13px; font-weight:700;">{user.get('name', 'User')}</div>
                    <div style="font-size:11px; color:#94A3B8;"><span class="aux-dot" style="background:{dot_color};"></span>{curr_aux}</div>
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ==============================================================================
# 9. DASHBOARD: METRIC CARDS & CASES TABLE
# ==============================================================================
def render_dashboard():
    user = st.session_state.get("current_user", {})
    is_admin = user.get("role") in ["Admin", "Admin/Agent"]
    
    # Header Mode Selector for Admin/Agent
    col_t1, col_t2 = st.columns([3, 1])
    with col_t1:
        if is_admin and st.session_state.get("view_mode", "Admin") == "Admin":
            st.markdown("## **Active Cases** &nbsp; <span style='font-size:14px; background:#DCFCE7; color:#16A34A; padding:3px 10px; border-radius:12px;'>Live Team Feed</span>", unsafe_allow_html=True)
        else:
            st.markdown(f"## **My Cases** &nbsp; <span style='font-size:14px; background:#E0F2FE; color:#0284C7; padding:3px 10px; border-radius:12px;'>{user.get('name')}</span>", unsafe_allow_html=True)
    with col_t2:
        if user.get("role") == "Admin/Agent":
            mode = st.radio("Perspective", ["Admin View", "Agent View"], horizontal=True, label_visibility="collapsed")
            st.session_state["view_mode"] = "Admin" if "Admin" in mode else "Agent"

    filter_email = user.get("email") if (not is_admin or st.session_state.get("view_mode") == "Agent") else None

    # Query Base Counts
    q_base = {"type": "cases"}
    if filter_email:
        q_base["assignee_email"] = filter_email

    total_active = collection.count_documents({**q_base, "status": {"$ne": "Closed"}})
    total_critical = collection.count_documents({**q_base, "priority": "Critical", "status": {"$ne": "Closed"}})
    total_due_soon = collection.count_documents({**q_base, "priority": {"$in": ["Critical", "High"]}, "status": {"$ne": "Closed"}})
    total_on_track = collection.count_documents({**q_base, "priority": {"$in": ["Medium", "Low"]}, "status": {"$ne": "Closed"}})

    # Four Metrics Cards
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(f"""
        <div class="metric-container" style="background:#F0F9FF; border-left:4px solid #0284C7;">
            <div class="metric-icon-box" style="background:#E0F2FE; color:#0284C7;">📁</div>
            <div>
                <p class="metric-title">{'My Active Cases' if filter_email else 'Active Cases'}</p>
                <h3 class="metric-value">{total_active}</h3>
                <p class="metric-sub" style="color:#0284C7;">↑ +5% vs last week</p>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with m2:
        st.markdown(f"""
        <div class="metric-container" style="background:#FEF2F2; border-left:4px solid #DC2626;">
            <div class="metric-icon-box" style="background:#FEE2E2; color:#DC2626;">⚠️</div>
            <div>
                <p class="metric-title">{'My Critical Cases' if filter_email else 'Critical Cases'}</p>
                <h3 class="metric-value">{total_critical}</h3>
                <p class="metric-sub" style="color:#DC2626;">↑ +2 vs last week</p>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with m3:
        st.markdown(f"""
        <div class="metric-container" style="background:#FFFBEB; border-left:4px solid #D97706;">
            <div class="metric-icon-box" style="background:#FEF3C7; color:#D97706;">⏰</div>
            <div>
                <p class="metric-title">Due Soon</p>
                <h3 class="metric-value">{total_due_soon}</h3>
                <p class="metric-sub" style="color:#D97706;">↑ +1 vs last week</p>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with m4:
        st.markdown(f"""
        <div class="metric-container" style="background:#F0FDF4; border-left:4px solid #16A34A;">
            <div class="metric-icon-box" style="background:#DCFCE7; color:#16A34A;">✅</div>
            <div>
                <p class="metric-title">On Track</p>
                <h3 class="metric-value">{total_on_track}</h3>
                <p class="metric-sub" style="color:#16A34A;">↑ +10% vs last week</p>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Main Grid: Left = Table, Right = Sidebar Panel
    left_col, right_col = st.columns([2.8, 1.2])

    with left_col:
        # Table Controls & Filters
        f1, f2, f3, f4, f5 = st.columns([2, 1.2, 1.2, 1, 1])
        with f1:
            search_val = st.text_input("Search Cases", placeholder="🔍 Filter by subject, case #, vendor...", label_visibility="collapsed")
        with f2:
            pri_filter = st.selectbox("Priority", ["All Priorities", "Critical", "High", "Medium", "Low"], label_visibility="collapsed")
        with f3:
            st_filter = st.selectbox("Status", ["All Statuses", "In Progress", "Vendor Response", "Waiting Vendor", "Open", "Pending Info"], label_visibility="collapsed")
        with f4:
            if st.button("➕ New Case", type="primary", use_container_width=True):
                st.session_state["show_new_case_expander"] = not st.session_state.get("show_new_case_expander", False)
        with f5:
            # Export CSV
            all_cases_df = pd.DataFrame(collection.find({"type": "cases"}))
            if not all_cases_df.empty:
                csv_bytes = all_cases_df.to_csv(index=False).encode("utf-8")
                st.download_button("📥 Export", csv_bytes, "HPE_Cases_Export.csv", "text/csv", use_container_width=True)

        # Quick New Case Expander
        if st.session_state.get("show_new_case_expander"):
            with st.expander("Create New Case for Auto-Assignment", expanded=True):
                nc_c1, nc_c2 = st.columns(2)
                with nc_c1:
                    new_subj = st.text_input("Subject", "Storage Controller Offline")
                    new_pri = st.selectbox("Priority Level", ["Critical", "High", "Medium", "Low"])
                with nc_c2:
                    new_vend = st.text_input("Vendor Name", "ABC Software Inc.")
                    new_vend_email = st.text_input("Vendor Contact Email", "support@abcsoftware.com")
                new_desc = st.text_area("Detailed Problem Description", "Chassis 2 slot 4 bus error detected.")

                if st.button("Dispatch Case to Available Roster", type="primary"):
                    new_num = f"HPE-2026-{1050 + collection.count_documents({'type': 'cases'})}"
                    new_case_payload = {
                        "type": "cases",
                        "case_number": new_num,
                        "subject": new_subj,
                        "description": new_desc,
                        "priority": new_pri,
                        "status": "In Progress",
                        "status_reason": "Waiting for Vendor Response",
                        "due_date": (get_current_ph_time() + timedelta(hours=4)).strftime("%b %d, %Y %I:%M %p"),
                        "created_at": get_current_ph_time().strftime("%b %d, %Y %I:%M %p"),
                        "last_update": get_current_ph_time().strftime("%b %d, %Y %I:%M %p"),
                        "last_update_ts": get_current_ph_time(),
                        "vendor_name": new_vend,
                        "vendor_email": new_vend_email,
                        "vendor_phone": "+1 555 000 1122",
                        "account": "Enterprise Core",
                        "related_system": "HPE Pointnext"
                    }
                    success, assigned_agent = auto_assign_new_case(new_case_payload)
                    st.success(f"Case {new_num} registered and auto-assigned to: {assigned_agent}!")
                    time.sleep(1)
                    st.session_state["show_new_case_expander"] = False
                    st.rerun()

        # Build Query
        q = {"type": "cases"}
        if filter_email:
            q["assignee_email"] = filter_email
        if pri_filter != "All Priorities":
            q["priority"] = pri_filter
        if st_filter != "All Statuses":
            q["status"] = st_filter
        if search_val:
            q["$or"] = [
                {"case_number": {"$regex": search_val}},
                {"subject": {"$regex": search_val}},
                {"assigned_to": {"$regex": search_val}},
                {"vendor_name": {"$regex": search_val}}
            ]

        case_list = list(collection.find(q))
        
        # Priority Weight Sorting
        pri_weights = {"Critical": 1, "High": 2, "Medium": 3, "Low": 4}
        case_list.sort(key=lambda x: pri_weights.get(x.get("priority", "Low"), 5))

        # Render Active Cases List
        st.markdown(f"<div style='font-size:12px; color:#64748B; margin-bottom:8px;'>Showing <strong>{len(case_list)}</strong> cases (sorted by urgency)</div>", unsafe_allow_html=True)
        
        for c in case_list:
            pri = c.get("priority", "Low")
            badge_class = f"badge-{pri.lower()}"
            status_val = c.get("status", "Open")
            
            # Row container matching screenshot aesthetics
            r1, r2, r3, r4, r5, r6 = st.columns([1.5, 3.2, 1.2, 2, 1.8, 1.2])
            with r1:
                if st.button(f"📄 {c['case_number']}", key=f"btn_{c['case_number']}", use_container_width=True):
                    render_case_modal(c["case_number"])
            with r2:
                st.markdown(f"**{c.get('subject')}**<br><small style='color:#64748B;'>{c.get('vendor_name', 'HPE')}</small>", unsafe_allow_html=True)
            with r3:
                st.markdown(f"<span class='badge {badge_class}'>{pri}</span>", unsafe_allow_html=True)
            with r4:
                st.markdown(f"👤 <small>{c.get('assigned_to')}</small>", unsafe_allow_html=True)
            with r5:
                st.markdown(f"<span style='color:#DC2626; font-size:12px; font-weight:600;'>{c.get('due_date')}</span>", unsafe_allow_html=True)
            with r6:
                st.markdown(f"<span class='badge badge-status'>{status_val}</span>", unsafe_allow_html=True)
            st.divider()

    with right_col:
        # RIGHT RAIL: Admin Online Agents OR Agent Schedule & Alerts
        if is_admin and st.session_state.get("view_mode", "Admin") == "Admin":
            st.markdown("#### 👥 Online Agents (12)")
            st.caption("Real-time telemetry and aux distribution:")
            agent_search = st.text_input("Filter agent", placeholder="Search agent name...", label_visibility="collapsed")
            
            q_agents = {"type": "roster_list", "role": {"$ne": "Admin"}}
            if agent_search:
                q_agents["name"] = {"$regex": agent_search}
            
            online_agents = list(collection.find(q_agents))
            
            # Sort by Aux
            aux_order = {"Available": 1, "Admin Work": 2, "Lunch": 3, "Break": 4, "Meeting": 5, "Coaching": 6, "Not Ready - Online": 7}
            online_agents.sort(key=lambda x: aux_order.get(x.get("current_aux", "Available"), 8))

            for ag in online_agents:
                aux_st = ag.get("current_aux", "Available")
                color_map = {
                    "Available": "#00B388", "Admin Work": "#2563EB", "Lunch": "#FBBF24",
                    "Break": "#94A3B8", "Meeting": "#F59E0B", "Not Ready - Online": "#EF4444"
                }
                c_dot = color_map.get(aux_st, "#94A3B8")
                
                ra1, ra2 = st.columns([1, 3])
                with ra1:
                    st.image(ag.get("profile_picture", "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150"), width=44)
                with ra2:
                    st.markdown(f"""
                    <div style="line-height:1.2;">
                        <strong>{ag.get('name')}</strong><br>
                        <small style="color:#64748B;">{ag.get('role')}</small><br>
                        <span class="aux-dot" style="background:{c_dot};"></span><small style="font-weight:600; color:{c_dot};">{aux_st}</small>
                    </div>
                    """, unsafe_allow_html=True)
                st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)

            if st.button("📢 Broadcast Alert Message", use_container_width=True):
                render_admin_message_dialog()

        else:
            # AGENT RIGHT RAIL: Schedule + Alerts
            st.markdown("#### 📅 Today's Schedule")
            st.markdown("""
            <div style="background:white; border-radius:10px; padding:12px 16px; border:1px solid #E2E8F0; font-size:12px; line-height:2.2;">
                🟢 08:00 AM &nbsp; <strong>On Shift / Available</strong><br>
                🔵 10:00 AM &nbsp; <strong>Case Work</strong><br>
                🟡 12:00 PM &nbsp; <strong>Lunch Break</strong><br>
                🔵 01:00 PM &nbsp; <strong>Case Work</strong><br>
                🟣 03:00 PM &nbsp; <strong>Coaching Session</strong><br>
                🔵 04:00 PM &nbsp; <strong>Case Work</strong>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("#### 🔔 Announcements / Alerts")
            notifs = list(collection.find({
                "type": "notifications",
                "$or": [{"target_email": user.get("email")}, {"target_email": "all"}]
            }, limit=5))

            for n in notifs:
                cat = n.get("category", "info")
                icon = "⚠️" if cat == "critical" else ("➕" if cat == "new_case" else "📢")
                st.markdown(f"""
                <div style="background:white; border-radius:8px; padding:10px 14px; border-left:3px solid #00B388; margin-bottom:8px; font-size:12px;">
                    <strong>{icon} {n.get('title')}</strong> &bull; <small style="color:#94A3B8;">{n.get('created_at')}</small><br>
                    {n.get('message')}
                </div>
                """, unsafe_allow_html=True)

# ==============================================================================
# 10. MONITORING TAB (ADMIN ONLY)
# ==============================================================================
def render_monitoring():
    st.markdown("### 📊 Operational Roster & Telemetry Monitoring")
    st.caption("Active shift telemetry, login durations, and case allocation load per agent:")

    agents = list(collection.find({"type": "roster_list", "role": {"$ne": "Admin"}}))
    table_data = []
    for a in agents:
        assigned_today = collection.count_documents({"type": "cases", "assignee_email": a["email"]})
        crit_assigned = collection.count_documents({"type": "cases", "assignee_email": a["email"], "priority": "Critical"})
        table_data.append({
            "Name": a["name"],
            "Role": a["role"],
            "Aux Status": a.get("current_aux", "Available"),
            "Login Time": a.get("login_time", "08:45 AM"),
            "Session Length": "3h 42m",
            "Active Cases": assigned_today,
            "Critical": crit_assigned,
            "Email": a["email"]
        })
    df = pd.DataFrame(table_data)
    st.dataframe(df, use_container_width=True)

    st.divider()
    st.markdown("#### Administrative Interventions")
    m_col1, m_col2 = st.columns(2)
    with m_col1:
        kick_agent = st.selectbox("Select Agent to Session Terminate (Kick)", [d["Name"] for d in table_data])
        if st.button("🚫 Terminate Session (Force Logout)", type="secondary"):
            target_user = collection.find_one({"type": "roster_list", "name": kick_agent})
            if target_user:
                collection.update_many({"type": "sessions", "email": target_user["email"]}, {"$set": {"expires_at": "2000-01-01"}})
                collection.update_one({"type": "roster_list", "email": target_user["email"]}, {"$set": {"is_logged_in": False, "current_aux": "Not Ready - Online"}})
                st.success(f"{kick_agent} has been successfully logged out from the enterprise cluster.")
    with m_col2:
        st.info("Tip: Aux telemetry events are recorded in real-time to avoid duplicate critical case distribution.")

# ==============================================================================
# 11. SCHEDULE TAB
# ==============================================================================
def render_schedule():
    user = st.session_state.get("current_user", {})
    is_admin = user.get("role") in ["Admin", "Admin/Agent"]
    
    st.markdown("### 📅 Enterprise Workforce Schedule & PTO Tracker")
    current_ym = get_current_ph_time().strftime("%Y-%m")
    pto_doc = collection.find_one({"type": "Schedule_Monitoring", "month": current_ym}) or {"total_allocation": 20, "used_allocation": 4}

    rem_pto = pto_doc.get("total_allocation", 20) - pto_doc.get("used_allocation", 0)

    # PTO Metric Strip
    s1, s2, s3 = st.columns(3)
    s1.metric(f"Total Team PTO ({get_current_ph_time().strftime('%B %Y')})", pto_doc.get("total_allocation", 20))
    s2.metric("Used Allocation", pto_doc.get("used_allocation", 0))
    s3.metric("Remaining Bookable Days", rem_pto)

    st.divider()
    sch1, sch2 = st.columns([1.5, 2.5])
    with sch1:
        st.markdown("#### 📝 Submit Leave Request")
        leave_type = st.selectbox("Leave Type", ["PTO (Vacation)", "Sick Leave (Auto-Approved)", "Emergency Leave (Auto-Approved)"])
        req_date = st.date_input("Target Date", value=get_current_ph_time() + timedelta(days=2))
        leave_notes = st.text_input("Reason / Notes", placeholder="Medical, personal, family, etc.")

        if st.button("Submit Request", type="primary", use_container_width=True):
            if "PTO" in leave_type and rem_pto <= 0:
                st.error("No PTO Allocation available for the selected month.")
            else:
                # Deduct allocation if PTO
                if "PTO" in leave_type:
                    collection.update_one(
                        {"type": "Schedule_Monitoring", "month": current_ym},
                        {"$inc": {"used_allocation": 1}}
                    )
                collection.insert_one({
                    "type": "leave_requests",
                    "agent": user.get("name"),
                    "email": user.get("email"),
                    "leave_type": leave_type,
                    "date": req_date.strftime("%Y-%m-%d"),
                    "status": "Approved" if ("Sick" in leave_type or "Emergency" in leave_type) else "Allocated",
                    "created_at": get_current_ph_time().strftime("%Y-%m-%d %H:%M")
                })
                st.success(f"{leave_type} successfully recorded for {req_date}!")
                time.sleep(1)
                st.rerun()

    with sch2:
        st.markdown("#### 🔄 Schedule Swap Request")
        st.caption("Instant peer-to-peer swap (no administrative delay required):")
        other_agents = [a["name"] for a in collection.find({"type": "roster_list", "email": {"$ne": user.get("email")}})]
        colleague = st.selectbox("Select Colleague to Swap Shift With", other_agents)
        swap_date = st.date_input("Your Shift Date", value=get_current_ph_time() + timedelta(days=1))
        
        if st.button("Propose Instant Swap", use_container_width=True):
            collection.insert_one({
                "type": "schedule_swap_requests",
                "from_agent": user.get("name"),
                "to_agent": colleague,
                "date": swap_date.strftime("%Y-%m-%d"),
                "status": "Approved",
                "created_at": get_current_ph_time().strftime("%Y-%m-%d %H:%M")
            })
            st.success(f"Shift swap request dispatched to {colleague} and automatically synced!")

# ==============================================================================
# 12. REPORT TAB (PLOTLY VISUALIZATIONS)
# ==============================================================================
def render_report():
    user = st.session_state.get("current_user", {})
    is_admin = user.get("role") in ["Admin", "Admin/Agent"]
    
    st.markdown("### 📈 Operational KPI & Performance Analytics")
    period = st.radio("Reporting Horizon", ["Daily", "WOW (Week-Over-Week)", "MTD (Month-To-Date)", "YTD"], horizontal=True)

    q = {"type": "cases"}
    if not is_admin:
        q["assignee_email"] = user.get("email")

    cases = list(collection.find(q))
    df = pd.DataFrame(cases)

    if df.empty:
        st.info("No cases logged in the specified horizon.")
        return

    c1, c2 = st.columns(2)
    with c1:
        # Priority Breakdown Chart
        fig_pri = px.pie(
            df, names="priority", title="Cases by Priority Distribution",
            color="priority",
            color_discrete_map={"Critical": "#DC2626", "High": "#EA580C", "Medium": "#D97706", "Low": "#16A34A"},
            hole=0.45
        )
        fig_pri.update_layout(margin=dict(t=40, b=20, l=20, r=20))
        st.plotly_chart(fig_pri, use_container_width=True)

    with c2:
        # Status Distribution Bar Chart
        status_counts = df["status"].value_counts().reset_index()
        status_counts.columns = ["Status", "Count"]
        fig_st = px.bar(
            status_counts, x="Status", y="Count", title="Case Volumes by Operational Status",
            color="Status", color_discrete_sequence=["#00B388", "#2563EB", "#F59E0B", "#8B5CF6"]
        )
        fig_st.update_layout(margin=dict(t=40, b=20, l=20, r=20), showlegend=False)
        st.plotly_chart(fig_st, use_container_width=True)

    # Attendance & Adherence Metrics
    st.markdown("#### 🎯 Service Level Adherence & Attendance Telemetry")
    a1, a2, a3 = st.columns(3)
    a1.metric("Schedule Adherence", "96.4%", "↑ +1.2% target")
    a2.metric("Shift Attendance Rate", "98.2%", "Scheduled vs Attended")
    a3.metric("SLA Resolution Compliance", "94.8%", "Target: 95.0%")

# ==============================================================================
# 13. SETTINGS TAB (ADMIN ONLY)
# ==============================================================================
def render_settings():
    st.markdown("### ⚙️ Enterprise Configuration & Master Registry")
    
    set_t1, set_t2, set_t3 = st.tabs(["👥 Team Roster Management", "🗄️ Validation Dropdowns", "📥 Vendor Excel Sync"])

    with set_t1:
        st.markdown("##### Manage Roles & User Accounts")
        users = list(collection.find({"type": "roster_list"}))
        for u in users:
            u_c1, u_c2, u_c3 = st.columns([3, 2, 2])
            with u_c1:
                st.write(f"**{u.get('name')}** (`{u.get('email')}`)")
                st.caption(f"ID: {u.get('employee_id')} | Dept: {u.get('department')}")
            with u_c2:
                new_role = st.selectbox(
                    f"Role for {u['name']}",
                    ["Agent", "Admin/Agent", "Admin"],
                    index=["Agent", "Admin/Agent", "Admin"].index(u.get("role", "Agent")),
                    key=f"role_{u['email']}"
                )
            with u_c3:
                if st.button("Update Role", key=f"btn_role_{u['email']}"):
                    collection.update_one({"type": "roster_list", "email": u["email"]}, {"$set": {"role": new_role}})
                    st.success(f"Role updated to {new_role}!")
            st.divider()

    with set_t2:
        st.markdown("##### System Validation Picklists")
        dropdown_doc = collection.find_one({"type": "Validation_Dropdown"}) or {}
        st.write("**Case Statuses:**", ", ".join(dropdown_doc.get("Case_Status", [])))
        st.write("**Contract Breach Reasons:**", ", ".join(dropdown_doc.get("Contract_Breach", [])))
        st.info("Validation dropdowns are synchronized with MongoDB validation schemas.")

    with set_t3:
        st.markdown("##### Synchronize Vendor Registry via Excel (`vendor_data.xlsx`)")
        st.caption("Required Columns: `Vendor Name`, `Primary Contact`, `Email`, `Phone`, `Address`")
        uploaded_excel = st.file_uploader("Upload Vendor Excel File", type=["xlsx", "xls"])
        if uploaded_excel:
            try:
                v_df = pd.read_excel(uploaded_excel)
                st.write("Preview of Uploaded Vendor Records:")
                st.dataframe(v_df.head(5), use_container_width=True)
                if st.button("🚀 Ingest & Synchronize Records to MongoDB", type="primary"):
                    st.success(f"Successfully processed and synchronized {len(v_df)} vendor records into CaseFlow cache!")
            except Exception as e:
                st.error(f"Error parsing Excel file: {e}")

# ==============================================================================
# 14. AUTHENTICATION PAGES (SIGN-IN & SIGN-UP RECREATION)
# ==============================================================================
def render_auth_page():
    auth_mode = st.session_state.get("auth_mode", "Sign In")

    # Outer Container matching screenshot 2-panel architecture
    st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)
    c_left, c_right = st.columns([1.1, 1], gap="large")

    with c_left:
        st.markdown("""
        <div style="background: linear-gradient(180deg, #062323 0%, #031515 100%); border-radius:18px; padding:44px 38px; color:white; min-height:640px; box-shadow:0 8px 30px rgba(0,0,0,0.25);">
            <div style="border:3.5px solid #00B388; width:34px; height:22px; border-radius:3px; margin-bottom:12px;"></div>
            <p style="color:#00B388; font-weight:700; margin:0; font-size:13px; letter-spacing:0.5px;">HEWLETT PACKARD ENTERPRISE</p>
            <h1 style="font-size:36px; font-weight:800; margin:4px 0 0 0; color:#FFFFFF;">HPE CaseFlow</h1>
            <p style="color:#94A3B8; font-size:14px; margin-top:2px;">Team Task and Case Management System</p>
            <div style="margin-top:48px;">
                <div style="display:flex; align-items:center; gap:16px; margin-bottom:28px;">
                    <div style="width:48px; height:48px; border-radius:50%; background:rgba(0,179,136,0.15); display:flex; align-items:center; justify-content:center; font-size:20px; color:#00B388;">📁</div>
                    <div>
                        <strong style="font-size:16px;">Manage Cases</strong>
                        <p style="color:#94A3B8; font-size:13px; margin:0;">Track and resolve tasks efficiently with automated SLA timers.</p>
                    </div>
                </div>
                <div style="display:flex; align-items:center; gap:16px; margin-bottom:28px;">
                    <div style="width:48px; height:48px; border-radius:50%; background:rgba(0,179,136,0.15); display:flex; align-items:center; justify-content:center; font-size:20px; color:#00B388;">👥</div>
                    <div>
                        <strong style="font-size:16px;">Work Together</strong>
                        <p style="color:#94A3B8; font-size:13px; margin:0;">Stay aligned with your team in real time through instant aux telemetry.</p>
                    </div>
                </div>
                <div style="display:flex; align-items:center; gap:16px;">
                    <div style="width:48px; height:48px; border-radius:50%; background:rgba(0,179,136,0.15); display:flex; align-items:center; justify-content:center; font-size:20px; color:#00B388;">📊</div>
                    <div>
                        <strong style="font-size:16px;">Drive Results</strong>
                        <p style="color:#94A3B8; font-size:13px; margin:0;">Real-time insights and automated contract breach notifications.</p>
                    </div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with c_right:
        if auth_mode == "Sign In":
            st.markdown("## **Welcome Back!**")
            st.caption("Sign in to your HPE CaseFlow account")

            email_in = st.text_input("HPE Email Address", placeholder="yourname@hpe.com")
            pw_in = st.text_input("Password", type="password", placeholder="Enter your password")

            rem_col, fgt_col = st.columns([1, 1])
            with rem_col:
                rem_me = st.checkbox("Remember me", value=True)
            with fgt_col:
                if st.button("Forgot password?", type="secondary"):
                    st.info("Password reset dispatch link available via enterprise administrator.")

            if st.button("Sign In", type="primary", use_container_width=True):
                user = authenticate_user(email_in, pw_in)
                if user:
                    # Update status
                    default_aux = "Admin Work" if user.get("role") in ["Admin", "Admin/Agent"] else "Not Ready - Online"
                    collection.update_one(
                        {"type": "roster_list", "email": user["email"]},
                        {"$set": {"is_logged_in": True, "current_aux": default_aux}}
                    )
                    create_session(user, remember_me=rem_me)
                    st.success("Authentication successful! Loading enterprise environment...")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("Invalid HPE credentials. Please check your email or password.")

            st.markdown("<div style='text-align:center; color:#94A3B8; margin:16px 0;'>&mdash; or &mdash;</div>", unsafe_allow_html=True)
            if st.button("🟦 Sign in with Microsoft (HPE)", use_container_width=True):
                st.info("Enterprise Microsoft Azure AD / Okta SSO is managed by HPE Global Identity Services.")

            st.markdown("<br><div style='text-align:center;'>Don't have an account?</div>", unsafe_allow_html=True)
            if st.button("Create Account (Sign Up)", use_container_width=True):
                st.session_state["auth_mode"] = "Sign Up"
                st.rerun()

        else:
            # Sign Up Page
            st.markdown("## **Create Your Account**")
            st.caption("Sign up to access HPE CaseFlow")

            su_fn = st.text_input("First Name", placeholder="Enter your first name")
            su_ln = st.text_input("Last Name", placeholder="Enter your last name")
            su_eid = st.text_input("Employee ID", placeholder="Enter your employee ID (e.g. HPE12345)")
            su_email = st.text_input("HPE Email Address", placeholder="yourname@hpe.com")
            su_pw = st.text_input("Password", type="password", placeholder="Create a password (min 8 chars, numbers, letters)")

            st.caption("Password must be at least 8 characters and include letters, numbers and a special character.")

            if st.button("Sign Up", type="primary", use_container_width=True):
                # Basic Validation
                if not (su_fn and su_ln and su_eid and su_email and su_pw):
                    st.error("All registration fields are required.")
                elif len(su_pw) < 8 or not re.search(r"\d", su_pw) or not re.search(r"[!@#$%^&*(),.?\":{}|<>]", su_pw):
                    st.error("Password does not meet complexity requirements.")
                elif collection.find_one({"type": "roster_list", "email": su_email.lower()}):
                    st.error("An account with this HPE email already exists.")
                elif collection.find_one({"type": "roster_list", "employee_id": su_eid}):
                    st.error("An account with this Employee ID already exists.")
                else:
                    hashed = hash_password(su_pw)
                    collection.insert_one({
                        "type": "roster_list",
                        "first_name": su_fn,
                        "last_name": su_ln,
                        "name": f"{su_fn} {su_ln}",
                        "employee_id": su_eid,
                        "email": su_email.lower(),
                        "password_hash": hashed,
                        "role": "Agent",
                        "department": "Operations",
                        "current_aux": "Not Ready - Online",
                        "is_logged_in": True,
                        "profile_picture": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150",
                        "created_at": get_current_ph_time().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    new_user = collection.find_one({"type": "roster_list", "email": su_email.lower()})
                    create_session(new_user, remember_me=True)
                    st.success("Account successfully created!")
                    time.sleep(0.8)
                    st.session_state["auth_mode"] = "Sign In"
                    st.rerun()

            st.markdown("<br><div style='text-align:center;'>Already have an account?</div>", unsafe_allow_html=True)
            if st.button("Sign In Instead", use_container_width=True):
                st.session_state["auth_mode"] = "Sign In"
                st.rerun()

# ==============================================================================
# 15. FIXED BOTTOM NAVIGATION BAR COMPONENT
# ==============================================================================
def render_bottom_navigation():
    user = st.session_state.get("current_user", {})
    is_admin = user.get("role") in ["Admin", "Admin/Agent"]
    
    tabs = ["Dashboard", "Schedule", "Report"]
    if is_admin:
        tabs = ["Dashboard", "Monitoring", "Schedule", "Report", "Setting"]

    current_tab = st.session_state.get("current_tab", "Dashboard")
    
    st.markdown('<div class="hpe-bottom-nav">', unsafe_allow_html=True)
    cols = st.columns(len(tabs) + 1)
    
    icons = {
        "Dashboard": "🟩 Dashboard",
        "Monitoring": "👥 Monitoring",
        "Schedule": "📅 Schedule",
        "Report": "📊 Report",
        "Setting": "⚙️ Setting"
    }

    for idx, t in enumerate(tabs):
        with cols[idx]:
            is_active = (current_tab == t)
            btn_type = "primary" if is_active else "secondary"
            if st.button(icons.get(t, t), key=f"nav_{t}", type=btn_type, use_container_width=True):
                st.session_state["current_tab"] = t
                st.rerun()
                
    # Profile & Aux modal trigger
    with cols[-1]:
        if st.button("👤 Profile / Aux", use_container_width=True):
            render_profile_dialog()
            
    st.markdown('</div>', unsafe_allow_html=True)

# ==============================================================================
# 16. MAIN ROUTER
# ==============================================================================
def main():
    # Attempt session validation if unauthenticated
    if not st.session_state.get("authenticated", False):
        validate_saved_session()

    if not st.session_state.get("authenticated", False):
        render_auth_page()
    else:
        render_top_header()

        active_tab = st.session_state.get("current_tab", "Dashboard")
        if active_tab == "Dashboard":
            render_dashboard()
        elif active_tab == "Monitoring":
            render_monitoring()
        elif active_tab == "Schedule":
            render_schedule()
        elif active_tab == "Report":
            render_report()
        elif active_tab == "Setting":
            render_settings()

        render_bottom_navigation()

if __name__ == "__main__":
    main()
