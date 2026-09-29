"""
================================================================================
APPLICATION: HPE CaseFlow — Task Monitoring & Management System
VISUAL SPECIFICATION: Exact reproduction of HPE Enterprise Reference (1000057381_2.png)
ARCHITECTURE: Single-file production Streamlit application with PyMongo persistence
================================================================================
"""

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
import secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# ==============================================================================
# 1. PAGE CONFIGURATION & TIMEZONE INITIALIZATION
# ==============================================================================
st.set_page_config(
    page_title="HPE CaseFlow — Task Monitoring & Management",
    page_icon="🟩",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Asia/Manila Timezone (UTC+8) using Python's built-in standard library
MANILA_TZ = timezone(timedelta(hours=8))

def get_current_ph_time():
    return datetime.now(MANILA_TZ)

# ==============================================================================
# 2. DATABASE ARCHITECTURE (PYMONGO + FAIL-SAFE IN-MEMORY STORE)
# ==============================================================================
class InMemoryMongoCollection:
    """Thread-safe, fully-featured in-memory MongoDB collection fallback."""
    def __init__(self, name="Team Roster Collection"):
        self.name = name
        self.docs = []
        self._indexes = {}

    def _matches(self, doc, query):
        for k, v in query.items():
            if k == "$or":
                if not any(self._matches(doc, cond) for cond in v):
                    return False
            elif "." in k:
                parts = k.split(".")
                curr = doc
                for p in parts:
                    if isinstance(curr, dict):
                        curr = curr.get(p)
                    else:
                        curr = None
                        break
                if isinstance(v, dict):
                    if "$in" in v and curr not in v["$in"]: return False
                    if "$ne" in v and curr == v["$ne"]: return False
                    if "$regex" in v and not (isinstance(curr, str) and re.search(v["$regex"], curr, re.IGNORECASE)): return False
                elif curr != v:
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
                    for sk, sv in update["$set"].items():
                        if "." in sk:
                            parts = sk.split(".")
                            curr = self.docs[idx]
                            for p in parts[:-1]:
                                curr = curr.setdefault(p, {})
                            curr[parts[-1]] = sv
                        else:
                            self.docs[idx][sk] = sv
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
                    for sk, sv in update["$set"].items():
                        if "." in sk:
                            parts = sk.split(".")
                            curr = self.docs[idx]
                            for p in parts[:-1]:
                                curr = curr.setdefault(p, {})
                            curr[parts[-1]] = sv
                        else:
                            self.docs[idx][sk] = sv
                count += 1
        return type("UpdateResult", (), {"matched_count": count, "modified_count": count})

    def delete_many(self, query):
        initial = len(self.docs)
        self.docs = [d for d in self.docs if not self._matches(d, query)]
        return type("DeleteResult", (), {"deleted_count": initial - len(self.docs)})

    def replace_one(self, query, replacement, upsert=False):
        for idx, d in enumerate(self.docs):
            if self._matches(d, query):
                new_d = replacement.copy()
                if "_id" not in new_d:
                    new_d["_id"] = d.get("_id", str(uuid.uuid4()))
                self.docs[idx] = new_d
                return type("UpdateResult", (), {"matched_count": 1, "modified_count": 1})
        if upsert:
            self.insert_one(replacement)
            return type("UpdateResult", (), {"matched_count": 0, "modified_count": 1})
        return type("UpdateResult", (), {"matched_count": 0, "modified_count": 0})

    def count_documents(self, query=None):
        return len(self.find(query or {}))

    def create_index(self, keys, **kwargs):
        idx_name = "_".join(f"{k}_{v}" for k, v in keys)
        self._indexes[idx_name] = kwargs

    def drop_index(self, name):
        self._indexes.pop(name, None)

    def index_information(self):
        return self._indexes


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
            client.server_info()
            return client, False
        except Exception as e:
            st.sidebar.warning(f"Live MongoDB unreachable ({e}). Using in-memory fallback store.")

    class MockClient:
        def __init__(self):
            self.db = {
                "TeamRoster": {
                    "Team Roster Collection": InMemoryMongoCollection("Team Roster Collection"),
                    "Cases_Collection": InMemoryMongoCollection("Cases_Collection"),
                    "Validation_Dropdown": InMemoryMongoCollection("Validation_Dropdown")
                }
            }
        def __getitem__(self, name):
            return self.db.setdefault(name, {
                "Team Roster Collection": InMemoryMongoCollection("Team Roster Collection"),
                "Cases_Collection": InMemoryMongoCollection("Cases_Collection"),
                "Validation_Dropdown": InMemoryMongoCollection("Validation_Dropdown")
            })
    return MockClient(), True

client, IS_IN_MEMORY = get_mongo_client()
db = client["TeamRoster"]
collection = db["Team Roster Collection"]
cases_collection = db["Cases_Collection"]
validation_collection = db["Validation_Dropdown"]

# ==============================================================================
# 3. INITIAL SEED DATA & DROPDOWNS SETUP
# ==============================================================================
def init_database():
    """Initializes indexes, validation objects, and realistic reference records."""
    try:
        # Cleanly drop legacy unique indexes that conflict with polymorphic schemas
        try:
            existing_indexes = collection.index_information()
            for idx_name in list(existing_indexes.keys()):
                if idx_name not in ["_id_", "_id"]:
                    collection.drop_index(idx_name)
        except Exception:
            pass

        collection.create_index([("type", 1)], unique=True)
        cases_collection.create_index([("case_number", 1)], sparse=True)
        cases_collection.create_index([("type", 1)])
    except Exception:
        pass

    # 1. Validation Dropdowns Document in Validation_Dropdown collection
    try:
        dropdown_doc = validation_collection.find_one({"type": "Validation_Dropdown"})
        if not dropdown_doc:
            validation_collection.insert_one({
                "type": "Validation_Dropdown",
                "Case_Status": ["Open", "In Progress", "On Hold", "Waiting Vendor", "Vendor Response", "Pending Info", "Closed"],
                "Case_Reason": [
                    "Waiting for Vendor Response",
                    "Initial contact with vendor",
                    "Under Investigation",
                    "Vendor SLA Warning Sent",
                    "Pending License Generation",
                    "Customer Verification",
                    "Resolved - Contract Complete"
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
    except Exception:
        pass

    # 2. Schedule & PTO Setup in Team Roster Collection
    try:
        current_year_month = get_current_ph_time().strftime("%Y-%m")
        pto_doc = collection.find_one({"type": "Schedule_Monitoring"})
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
    except Exception:
        pass

    # 3. Default Roster Seed: ALL contained under type: "roster_list" in Team Roster Collection
    try:
        roster_doc = collection.find_one({"type": "roster_list"})
        if not roster_doc or not roster_doc.get("Data"):
            salt = secrets.token_hex(8)
            hashed_pw = hashlib.sha256((salt + "Hpe@123456").encode()).hexdigest() + ":" + salt
            
            team_members = [
                ("Arianne", "Escabillas", "HPE12345", "arianne.escabillas@hpe.com", "Admin/Agent", "Admin Work", "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=150"),
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
            seed_data = []
            for fn, ln, eid, email, role, aux, img in team_members:
                seed_data.append({
                    "first_name": str(fn),
                    "last_name": str(ln),
                    "name": str(f"{fn} {ln}"),
                    "employee_id": str(eid),
                    "email": str(email),
                    "password_hash": str(hashed_pw),
                    "role": str(role),
                    "profile_picture": str(img),
                    "department": "Operations",
                    "current_aux": str(aux),
                    "is_logged_in": "true",
                    "login_time": "08:45 AM",
                    "created_at": str(now.strftime("%Y-%m-%d %H:%M:%S")),
                    "updated_at": str(now.strftime("%Y-%m-%d %H:%M:%S"))
                })
            collection.update_one(
                {"type": "roster_list"},
                {"$set": {"type": "roster_list", "Data": seed_data}},
                upsert=True
            )
    except Exception:
        pass

    # Ensure single document container for sessions
    try:
        if not collection.find_one({"type": "sessions"}):
            collection.insert_one({"type": "sessions", "Data": []})
    except Exception:
        pass

    # Ensure single document container for aux_history
    try:
        if not collection.find_one({"type": "aux_history"}):
            collection.insert_one({"type": "aux_history", "Data": []})
    except Exception:
        pass

    # 4. Default Seed Cases: ALL contained in Cases_Collection
    try:
        if cases_collection.count_documents({"type": "cases"}) == 0:
            cases_seed = [
                {
                    "case_number": "HPE-2026-1045",
                    "subject": "License Key Provisioning Delay",
                    "priority": "Critical",
                    "assigned_to": "Mark Santos",
                    "assignee_email": "mark.santos@hpe.com",
                    "assignee_avatar": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150",
                    "due_date": "Sep 28, 2026 11:00 AM",
                    "status": "In Progress",
                    "status_reason": "Waiting for Vendor Response",
                    "last_update": "Sep 28, 2026 8:15 AM",
                    "elapsed": "2h 9m ago",
                    "vendor_name": "ABC Software Inc.",
                    "vendor_contact": "Michael Tan",
                    "vendor_email": "support@abcsoftware.com",
                    "vendor_phone": "+1 555 123 4567",
                    "vendor_alt_contact": "Sarah Lim",
                    "vendor_alt_email": "sarah.lim@abcsoftware.com",
                    "vendor_address": "123 Innovation Drive, San Jose, CA 95134",
                    "account": "ABC Enterprise",
                    "related_system": "HPE Licensing Portal",
                    "case_category": "License Renewal",
                    "created_at": "Sep 27, 2026 03:15 PM"
                },
                {
                    "case_number": "HPE-2026-1042",
                    "subject": "Portal Access Issue",
                    "priority": "Critical",
                    "assigned_to": "Chelsea Reyes",
                    "assignee_email": "chelsea.reyes@hpe.com",
                    "assignee_avatar": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150",
                    "due_date": "Sep 28, 2026 12:00 PM",
                    "status": "Vendor Response",
                    "status_reason": "Under Investigation",
                    "last_update": "Sep 28, 2026 9:10 AM",
                    "elapsed": "1h 14m ago",
                    "vendor_name": "CloudAuth Corp",
                    "vendor_contact": "David Miller",
                    "vendor_email": "support@cloudauth.io",
                    "vendor_phone": "+1 800 555 0199",
                    "account": "Global FinTech",
                    "related_system": "SSO Federation Broker",
                    "case_category": "Identity & Access",
                    "created_at": "Sep 27, 2026 04:00 PM"
                },
                {
                    "case_number": "HPE-2026-1041",
                    "subject": "Software Installation Error",
                    "priority": "Critical",
                    "assigned_to": "James Dela Cruz",
                    "assignee_email": "james.delacruz@hpe.com",
                    "assignee_avatar": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150",
                    "due_date": "Sep 28, 2026 1:00 PM",
                    "status": "In Progress",
                    "status_reason": "Initial contact with vendor",
                    "last_update": "Sep 28, 2026 9:45 AM",
                    "elapsed": "39m ago",
                    "vendor_name": "LinuxDistro Solutions",
                    "vendor_contact": "Alex Wong",
                    "vendor_email": "support@linuxdistro.com",
                    "vendor_phone": "+1 555 987 6543",
                    "account": "BioPharm Labs",
                    "related_system": "Compute Orchestrator",
                    "case_category": "OS Deployment",
                    "created_at": "Sep 27, 2026 05:00 PM"
                },
                {
                    "case_number": "HPE-2026-1038",
                    "subject": "License Renewal Request",
                    "priority": "High",
                    "assigned_to": "Arianne Escabillas",
                    "assignee_email": "arianne.escabillas@hpe.com",
                    "assignee_avatar": "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=150",
                    "due_date": "Sep 28, 2026 3:00 PM",
                    "status": "Waiting Vendor",
                    "status_reason": "Waiting for Vendor Response",
                    "last_update": "Sep 28, 2026 10:00 AM",
                    "elapsed": "24m ago",
                    "vendor_name": "ABC Software Inc.",
                    "vendor_contact": "Michael Tan",
                    "vendor_email": "support@abcsoftware.com",
                    "vendor_phone": "+1 555 123 4567",
                    "account": "Nexus Telecom",
                    "related_system": "HPE GreenLake",
                    "case_category": "Contracts & Subscriptions",
                    "created_at": "Sep 27, 2026 06:00 PM"
                },
                {
                    "case_number": "HPE-2026-1036",
                    "subject": "Account Access Restoration",
                    "priority": "High",
                    "assigned_to": "Rafael Cruz",
                    "assignee_email": "rafael.cruz@hpe.com",
                    "assignee_avatar": "https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?w=150",
                    "due_date": "Sep 28, 2026 4:00 PM",
                    "status": "In Progress",
                    "status_reason": "Customer Verification",
                    "last_update": "Sep 28, 2026 9:30 AM",
                    "elapsed": "54m ago",
                    "vendor_name": "SecureID Systems",
                    "vendor_contact": "Rachel Adams",
                    "vendor_email": "help@secureid.org",
                    "vendor_phone": "+1 555 777 8899",
                    "account": "SkyLine Air",
                    "related_system": "IAM Portal",
                    "case_category": "Access Management",
                    "created_at": "Sep 27, 2026 07:00 PM"
                },
                {
                    "case_number": "HPE-2026-1033",
                    "subject": "Portal Error - 500",
                    "priority": "Medium",
                    "assigned_to": "Alyssa Ramos",
                    "assignee_email": "alyssa.ramos@hpe.com",
                    "assignee_avatar": "https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=150",
                    "due_date": "Sep 29, 2026 10:00 AM",
                    "status": "Open",
                    "status_reason": "Under Investigation",
                    "last_update": "Sep 28, 2026 8:20 AM",
                    "elapsed": "2h 4m ago",
                    "vendor_name": "InfraAPI LLC",
                    "vendor_contact": "Carlos Mendez",
                    "vendor_email": "carlos@infraapi.com",
                    "vendor_phone": "+1 555 333 2211",
                    "account": "AutoCorp Industries",
                    "related_system": "Storage Central",
                    "case_category": "API Gateway",
                    "created_at": "Sep 27, 2026 08:00 PM"
                },
                {
                    "case_number": "HPE-2026-1031",
                    "subject": "Usage Report Request",
                    "priority": "Medium",
                    "assigned_to": "Daniel Lim",
                    "assignee_email": "daniel.lim@hpe.com",
                    "assignee_avatar": "https://images.unsplash.com/photo-1522075469751-3a6694fb2f61?w=150",
                    "due_date": "Sep 29, 2026 11:00 AM",
                    "status": "In Progress",
                    "status_reason": "Waiting for Vendor Response",
                    "last_update": "Sep 28, 2026 9:05 AM",
                    "elapsed": "1h 19m ago",
                    "vendor_name": "DataMetric Analytics",
                    "vendor_contact": "Lisa Chen",
                    "vendor_email": "lisa@datametric.com",
                    "vendor_phone": "+1 555 444 3322",
                    "account": "Apex Banking",
                    "related_system": "Metering Engine",
                    "case_category": "Analytics",
                    "created_at": "Sep 27, 2026 09:00 PM"
                },
                {
                    "case_number": "HPE-2026-1029",
                    "subject": "Vendor Confirmation Needed",
                    "priority": "Medium",
                    "assigned_to": "Arianne Escabillas",
                    "assignee_email": "arianne.escabillas@hpe.com",
                    "assignee_avatar": "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=150",
                    "due_date": "Sep 29, 2026 2:00 PM",
                    "status": "Pending Info",
                    "status_reason": "Initial contact with vendor",
                    "last_update": "Sep 28, 2026 8:55 AM",
                    "elapsed": "1h 29m ago",
                    "vendor_name": "HardwareDepot Inc",
                    "vendor_contact": "Tom Bradley",
                    "vendor_email": "service@hardwaredepot.com",
                    "vendor_phone": "+1 555 666 7788",
                    "account": "Metro Retailers",
                    "related_system": "Pointnext Services",
                    "case_category": "Hardware RMA",
                    "created_at": "Sep 27, 2026 10:00 PM"
                },
                {
                    "case_number": "HPE-2026-1027",
                    "subject": "License Transfer",
                    "priority": "Low",
                    "assigned_to": "Kevin Navarro",
                    "assignee_email": "kevin.navarro@hpe.com",
                    "assignee_avatar": "https://images.unsplash.com/photo-1492562080023-ab3db95bfbce?w=150",
                    "due_date": "Sep 30, 2026 10:00 AM",
                    "status": "Open",
                    "status_reason": "Waiting for Vendor Response",
                    "last_update": "Sep 28, 2026 9:15 AM",
                    "elapsed": "1h 9m ago",
                    "vendor_name": "VMware by Broadcom",
                    "vendor_contact": "Karen Scott",
                    "vendor_email": "support@vmware.com",
                    "vendor_phone": "+1 877 486 9273",
                    "account": "Global Shipping Co",
                    "related_system": "VMware Cloud Foundation",
                    "case_category": "Virtualization",
                    "created_at": "Sep 27, 2026 11:00 PM"
                },
                {
                    "case_number": "HPE-2026-1025",
                    "subject": "Entitlement Update",
                    "priority": "Low",
                    "assigned_to": "Nicole Garcia",
                    "assignee_email": "nicole.garcia@hpe.com",
                    "assignee_avatar": "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=150",
                    "due_date": "Sep 30, 2026 3:00 PM",
                    "status": "In Progress",
                    "status_reason": "Pending License Generation",
                    "last_update": "Sep 28, 2026 9:40 AM",
                    "elapsed": "44m ago",
                    "vendor_name": "HPE Internal Ops",
                    "vendor_contact": "Support Tier 2",
                    "vendor_email": "tier2-support@hpe.com",
                    "vendor_phone": "+1 800 473 4000",
                    "account": "First National Insurance",
                    "related_system": "HPE InfoSight",
                    "case_category": "Entitlements",
                    "created_at": "Sep 28, 2026 12:00 AM"
                },
                # Seeded Closed Cases
                {
                    "case_number": "HPE-2026-1020",
                    "subject": "Firmware Patch 4.1.2 Validation",
                    "priority": "Medium",
                    "assigned_to": "Arianne Escabillas",
                    "assignee_email": "arianne.escabillas@hpe.com",
                    "assignee_avatar": "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=150",
                    "due_date": "Sep 27, 2026 11:00 AM",
                    "status": "Closed",
                    "status_reason": "Resolved - Contract Complete",
                    "closure_type": "Resolved",
                    "last_update": "Sep 27, 2026 2:15 PM",
                    "elapsed": "1d ago",
                    "vendor_name": "ABC Software Inc.",
                    "vendor_email": "support@abcsoftware.com",
                    "created_at": "Sep 25, 2026 09:00 AM"
                },
                {
                    "case_number": "HPE-2026-1018",
                    "subject": "Legacy Storage License Decommission",
                    "priority": "Low",
                    "assigned_to": "Mark Santos",
                    "assignee_email": "mark.santos@hpe.com",
                    "assignee_avatar": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150",
                    "due_date": "Sep 26, 2026 05:00 PM",
                    "status": "Closed",
                    "status_reason": "Resolved - Contract Complete",
                    "closure_type": "Resolved",
                    "last_update": "Sep 26, 2026 4:30 PM",
                    "elapsed": "2d ago",
                    "vendor_name": "HPE Storage Ops",
                    "vendor_email": "tier2-storage@hpe.com",
                    "created_at": "Sep 24, 2026 10:00 AM"
                }
            ]
            for c in cases_seed:
                c["type"] = "cases"
                c["description"] = f"Operational ticket for {c['subject']}."
                cases_collection.insert_one(c)

            cases_collection.insert_one({
                "type": "case_history",
                "case_number": "HPE-2026-1045",
                "timestamp": "Sep 27, 2026 03:15 PM",
                "user": "System",
                "action": "Case created and assigned",
                "details": "Case automatically assigned to Mark Santos based on lowest active critical count."
            })
    except Exception:
        pass

    # 5. Seed Notifications: ALL contained under type: "notifications" in Team Roster Collection
    try:
        notif_doc = collection.find_one({"type": "notifications"})
        if not notif_doc or not notif_doc.get("Data"):
            collection.update_one(
                {"type": "notifications"},
                {"$set": {
                    "type": "notifications",
                    "Data": [{
                        "target_email": "arianne.escabillas@hpe.com",
                        "title": "Critical Case Alert",
                        "message": "HPE-2026-1045 is nearing due date. Due in 36 minutes (11:00 AM). Please take action.",
                        "category": "critical",
                        "case_number": "HPE-2026-1045",
                        "acknowledged": "false",
                        "created_at": "10:22 AM"
                    }]
                }},
                upsert=True
            )
    except Exception:
        pass

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
    roster_doc = collection.find_one({"type": "roster_list"}) or {}
    users = roster_doc.get("Data", [])
    for user in users:
        if str(user.get("email", "")).strip().lower() == str(email).strip().lower():
            if verify_password(user.get("password_hash", ""), password):
                return user
    return None

def create_session(user_doc, remember_me=False):
    token = str(secrets.token_urlsafe(32))
    now = get_current_ph_time()
    expiry = now + (timedelta(days=14) if remember_me else timedelta(hours=12))
    
    session_data = {
        "token": str(token),
        "email": str(user_doc["email"]),
        "employee_id": str(user_doc.get("employee_id", "")),
        "name": str(user_doc.get("name", "")),
        "role": str(user_doc.get("role", "")),
        "remember_me": "true" if remember_me else "false",
        "login_time": str(now.strftime("%Y-%m-%d %I:%M %p")),
        "expires_at": str(expiry.strftime("%Y-%m-%d %H:%M:%S")),
        "status": "active"
    }

    # All sessions go inside type: 'sessions' in Team Roster Collection
    sess_doc = collection.find_one({"type": "sessions"}) or {}
    sess_list = sess_doc.get("Data", [])
    sess_list = [s for s in sess_list if s.get("email") != user_doc["email"]]
    sess_list.append(session_data)
    collection.update_one(
        {"type": "sessions"},
        {"$set": {"type": "sessions", "Data": sess_list}},
        upsert=True
    )

    st.session_state["session_token"] = token
    st.session_state["authenticated"] = True
    st.session_state["current_user"] = user_doc

def validate_saved_session():
    token = st.session_state.get("session_token")
    if not token:
        params = st.query_params
        if "stoken" in params:
            token = params["stoken"]
            st.session_state["session_token"] = token

    if token:
        sess_doc = collection.find_one({"type": "sessions"}) or {}
        sess_list = sess_doc.get("Data", [])
        for sess in sess_list:
            if sess.get("token") == token and sess.get("status") == "active":
                expiry = datetime.strptime(sess["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=MANILA_TZ)
                if expiry > get_current_ph_time():
                    roster_doc = collection.find_one({"type": "roster_list"}) or {}
                    for u in roster_doc.get("Data", []):
                        if u.get("email") == sess.get("email"):
                            st.session_state["authenticated"] = True
                            st.session_state["current_user"] = u
                            return True
    return False

def logout_user():
    token = st.session_state.get("session_token")
    sess_doc = collection.find_one({"type": "sessions"}) or {}
    sess_list = sess_doc.get("Data", [])
    for s in sess_list:
        if s.get("token") == token:
            s["status"] = "terminated"
            s["expires_at"] = "2000-01-01 00:00:00"
    collection.update_one({"type": "sessions"}, {"$set": {"Data": sess_list}}, upsert=True)

    curr_user = st.session_state.get("current_user")
    if curr_user:
        roster_doc = collection.find_one({"type": "roster_list"}) or {}
        users = roster_doc.get("Data", [])
        for u in users:
            if u.get("email") == curr_user.get("email"):
                u["is_logged_in"] = "false"
        collection.update_one({"type": "roster_list"}, {"$set": {"Data": users}}, upsert=True)

    st.session_state["authenticated"] = False
    st.session_state["current_user"] = None
    st.session_state["session_token"] = None
    st.session_state["show_profile_flyout"] = False
    st.session_state["manual_logout"] = True
    st.query_params.clear()
    st.rerun()

# ==============================================================================
# 5. REAL-TIME AUX ENGINE (INSTANT PERSISTENCE ON CHANGE)
# ==============================================================================
def update_user_aux(email, new_aux):
    roster_doc = collection.find_one({"type": "roster_list"}) or {}
    users = roster_doc.get("Data", [])
    old_aux = "Not Ready - Online"
    now_str = get_current_ph_time().strftime("%Y-%m-%d %I:%M %p")
    found_user = None

    for u in users:
        if u.get("email") == email:
            old_aux = u.get("current_aux", "Available")
            u["current_aux"] = str(new_aux)
            u["last_aux_change"] = str(now_str)
            u["updated_at"] = str(now_str)
            found_user = u
            break
    collection.update_one({"type": "roster_list"}, {"$set": {"Data": users}}, upsert=True)

    # All aux history contained inside type: 'aux_history' in Team Roster Collection
    aux_doc = collection.find_one({"type": "aux_history"}) or {}
    aux_list = aux_doc.get("Data", [])
    aux_list.append({
        "email": str(email),
        "employee_id": str(found_user.get("employee_id") if found_user else ""),
        "name": str(found_user.get("name") if found_user else ""),
        "old_aux": str(old_aux),
        "new_aux": str(new_aux),
        "timestamp": str(now_str)
    })
    collection.update_one({"type": "aux_history"}, {"$set": {"type": "aux_history", "Data": aux_list}}, upsert=True)

    if "current_user" in st.session_state and st.session_state["current_user"]["email"] == email:
        st.session_state["current_user"]["current_aux"] = new_aux

def on_aux_dropdown_change():
    """Triggered instantly when user chooses a new status in the Profile Flyout."""
    selected_aux = st.session_state.get("flyout_aux_selector")
    user = st.session_state.get("current_user")
    if user and selected_aux:
        update_user_aux(user["email"], selected_aux)
        st.toast(f"Status changed to {selected_aux}!", icon="🟢")

def auto_assign_new_case(case_data):
    """Fair round-robin & workload-balanced assignment strictly for Available agents."""
    roster_doc = collection.find_one({"type": "roster_list"}) or {}
    users = roster_doc.get("Data", [])
    available_agents = [
        u for u in users
        if u.get("role") in ["Agent", "Admin/Agent"] and u.get("current_aux") == "Available"
    ]
    
    if not available_agents:
        case_data["assigned_to"] = "Unassigned (Queue)"
        case_data["assignee_email"] = None
        cases_collection.insert_one(case_data)
        return False, "No agents currently in Available Aux."

    candidate_scores = []
    for agent in available_agents:
        active_count = cases_collection.count_documents({
            "type": "cases",
            "assignee_email": agent["email"],
            "status": {"$ne": "Closed"}
        })
        crit_count = cases_collection.count_documents({
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

    if case_data.get("priority") == "Critical":
        candidate_scores.sort(key=lambda x: (x["crit_count"], x["active_count"]))
    else:
        candidate_scores.sort(key=lambda x: (x["active_count"], x["crit_count"]))

    chosen = candidate_scores[0]["agent"]
    case_data["assigned_to"] = chosen["name"]
    case_data["assignee_email"] = chosen["email"]
    case_data["assignee_avatar"] = chosen.get("profile_picture", "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150")

    # All cases go to Cases_Collection
    cases_collection.insert_one(case_data)

    now_str = get_current_ph_time().strftime("%b %d, %Y %I:%M %p")
    cases_collection.insert_one({
        "type": "case_history",
        "case_number": case_data["case_number"],
        "timestamp": now_str,
        "user": "Auto-Assignment Engine",
        "action": "Case created and assigned",
        "details": f"Automatically assigned to {chosen['name']} (Active Workload: {candidate_scores[0]['active_count']} cases)."
    })

    # All notifications go inside type: 'notifications' in Team Roster Collection
    notif_doc = collection.find_one({"type": "notifications"}) or {}
    notif_list = notif_doc.get("Data", [])
    notif_list.append({
        "target_email": str(chosen["email"]),
        "title": "New Case Assigned",
        "message": f"{case_data['case_number']} has been assigned to you. Priority: {case_data['priority']}",
        "category": "new_case",
        "case_number": str(case_data["case_number"]),
        "acknowledged": "false",
        "created_at": str(get_current_ph_time().strftime("%I:%M %p"))
    })
    collection.update_one({"type": "notifications"}, {"$set": {"type": "notifications", "Data": notif_list}}, upsert=True)

    return True, chosen["name"]

# ==============================================================================
# 6. ENTERPRISE CSS DESIGN SYSTEM (PIXEL-PERFECT SPECIFICATION)
# ==============================================================================
ENTERPRISE_CSS = """
<style>
/* 1. Global Reset & Streamlit Toolbar Neutralization */
#MainMenu, header, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] {
    visibility: hidden !important;
    display: none !important;
}

.stApp {
    background-color: #F8FAFC !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
    color: #1E293B !important;
}

.block-container {
    padding-top: 5.2rem !important;
    padding-bottom: 95px !important;
    padding-left: 28px !important;
    padding-right: 28px !important;
    max-width: 100% !important;
}

/* 2. Top Header Bar */
div[class*="st-key-hpe_top_bar_container"] {
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    right: 0 !important;
    height: 68px !important;
    background-color: #042121 !important;
    border-bottom: 2.5px solid #00B388 !important;
    z-index: 10000 !important;
    display: flex !important;
    align-items: center !important;
    padding: 0 28px !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.18) !important;
}

div[class*="st-key-hpe_top_bar_container"] [data-testid="stHorizontalBlock"] {
    align-items: center !important;
    gap: 16px !important;
}

/* Header Profile Pill */
div[class*="st-key-top_profile_pill_btn"] button {
    background: #FFFFFF !important;
    color: #0F172A !important;
    border: 1px solid #CBD5E1 !important;
    border-radius: 24px !important;
    padding: 4px 12px !important;
    font-size: 12px !important;
    font-weight: 700 !important;
    display: flex !important;
    align-items: center !important;
    gap: 6px !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.06) !important;
}

div[class*="st-key-top_profile_pill_btn"] button:hover {
    border-color: #00B388 !important;
}

/* 3. PROFILE FLYOUT DROPDOWN CARD (ANCHORED TO TOP-RIGHT) */
div[class*="st-key-profile_flyout_card"] {
    position: fixed !important;
    top: 72px !important;
    right: 28px !important;
    width: 460px !important;
    background: #FFFFFF !important;
    border-radius: 16px !important;
    box-shadow: 0 16px 40px rgba(0, 0, 0, 0.22) !important;
    border: 1px solid #E2E8F0 !important;
    z-index: 99999 !important;
    padding: 22px 24px !important;
}

.flyout-pointer {
    position: absolute;
    top: -8px;
    right: 48px;
    width: 16px;
    height: 16px;
    background: #FFFFFF;
    transform: rotate(45deg);
    border-top: 1px solid #E2E8F0;
    border-left: 1px solid #E2E8F0;
}

/* Profile Flyout Aux Selector: Border Around & Transparent Teal */
div[class*="st-key-profile_aux_wrapper"] {
    margin-top: 4px !important;
    margin-bottom: 0px !important;
}

div[class*="st-key-profile_aux_wrapper"] [data-testid="stSelectbox"] {
    margin-bottom: 0px !important;
    padding-bottom: 0px !important;
}

div[class*="st-key-profile_aux_wrapper"] [data-testid="stElementContainer"] {
    margin-bottom: 0px !important;
    padding-bottom: 0px !important;
}

div[class*="st-key-profile_aux_wrapper"] div[data-baseweb="select"] {
    border: 1.5px solid #00B388 !important;
    border-radius: 8px !important;
    background-color: rgba(0, 179, 136, 0.08) !important;
    min-height: 40px !important;
    box-shadow: none !important;
}

div[class*="st-key-profile_aux_wrapper"] div[data-baseweb="select"]:hover,
div[class*="st-key-profile_aux_wrapper"] div[data-baseweb="select"]:focus-within {
    background-color: rgba(0, 179, 136, 0.14) !important;
    border-color: #009671 !important;
}

div[class*="st-key-profile_aux_wrapper"] div[data-baseweb="select"] > div {
    background-color: transparent !important;
    border: none !important;
    min-height: 38px !important;
}

div[class*="st-key-profile_aux_wrapper"] div[data-baseweb="select"] span {
    color: #062323 !important;
    font-weight: 700 !important;
    font-size: 13.5px !important;
}

div[class*="st-key-profile_aux_wrapper"] div[data-baseweb="select"] svg {
    fill: #00B388 !important;
}

/* Reduced space below aux selector using compact divider */
.flyout-divider {
    margin: 6px 0 10px 0 !important;
    border: none !important;
    border-top: 1px solid #E2E8F0 !important;
}

/* 4. SEGMENTED TILE TOGGLE FOR VIEW (MATCHING MOCKUP 1000057253) */
div[class*="st-key-view_mode_segmented_tile"] {
    background: #E2E8F0 !important;
    border-radius: 10px !important;
    padding: 3px !important;
    border: 1px solid #CBD5E1 !important;
    display: inline-flex !important;
    align-items: center !important;
}

div[class*="st-key-view_mode_segmented_tile"] [data-testid="stHorizontalBlock"] {
    gap: 2px !important;
    align-items: center !important;
}

div[class*="st-key-view_mode_segmented_tile"] button {
    border-radius: 8px !important;
    font-size: 13.5px !important;
    font-weight: 700 !important;
    padding: 6px 18px !important;
    height: 38px !important;
    border: none !important;
    transition: all 0.2s ease !important;
}

div[class*="st-key-view_mode_segmented_tile"] button[kind="secondary"],
div[class*="st-key-view_mode_segmented_tile"] button[data-testid="baseButton-secondary"] {
    background-color: transparent !important;
    color: #475569 !important;
}

div[class*="st-key-view_mode_segmented_tile"] button[kind="secondary"]:hover,
div[class*="st-key-view_mode_segmented_tile"] button[data-testid="baseButton-secondary"]:hover {
    background-color: rgba(255, 255, 255, 0.5) !important;
    color: #0F172A !important;
}

div[class*="st-key-view_mode_segmented_tile"] button[kind="primary"],
div[class*="st-key-view_mode_segmented_tile"] button[data-testid="baseButton-primary"] {
    background-color: #0A385C !important;
    color: #FFFFFF !important;
    box-shadow: 0 2px 6px rgba(10, 56, 92, 0.35) !important;
}

/* 5. 4 Metric KPI Cards */
.metric-card-box {
    background: #FFFFFF;
    border-radius: 12px;
    padding: 16px 18px;
    display: flex;
    align-items: center;
    gap: 16px;
    border: 1px solid #E2E8F0;
    box-shadow: 0 1px 2px rgba(0,0,0,0.02);
    height: 102px;
}

.metric-circle-icon {
    width: 44px;
    height: 44px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
    flex-shrink: 0;
}

.metric-card-label {
    font-size: 13px;
    font-weight: 600;
    color: #475569;
    margin: 0;
}

.metric-card-val {
    font-size: 30px;
    font-weight: 800;
    color: #0F172A;
    margin: 2px 0 0 0;
    line-height: 1;
}

.metric-card-trend {
    font-size: 11.5px;
    font-weight: 700;
    margin-top: 4px;
}

/* 6. Online Agents Right Panel (Card Container) */
.agents-panel-card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 14px;
    padding: 16px 18px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.02);
}

.agent-row-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 7px 0;
    border-bottom: 1px solid #F8FAFC;
}

/* 7. Priority & Status Badges (Exact Mockup Colors) */
.badge {
    display: inline-block;
    padding: 3px 12px;
    border-radius: 20px;
    font-size: 11.5px;
    font-weight: 700;
    text-align: center;
}

.badge-critical { background-color: #FEE2E2; color: #DC2626; }
.badge-high { background-color: #FFEDD5; color: #EA580C; }
.badge-medium { background-color: #FEF3C7; color: #D97706; }
.badge-low { background-color: #DCFCE7; color: #16A34A; }

.badge-status {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 6px;
    font-size: 11.5px;
    font-weight: 600;
    text-align: center;
}

.st-in-progress { background-color: #E0F2FE; color: #0284C7; }
.st-vendor-response { background-color: #FEF9C3; color: #A16207; }
.st-waiting-vendor { background-color: #FEF3C7; color: #D97706; }
.st-open { background-color: #F1F5F9; color: #475569; }
.st-pending-info { background-color: #F3E8FF; color: #7E22CE; }
.st-closed { background-color: #F1F5F9; color: #64748B; }

.aux-badge {
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 700;
    display: inline-block;
}

.aux-avail { background-color: #DCFCE7; color: #16A34A; }
.aux-lunch { background-color: #FEF3C7; color: #D97706; }
.aux-meeting { background-color: #FEE2E2; color: #DC2626; }
.aux-not-ready { background-color: #F1F5F9; color: #475569; }
.aux-break { background-color: #FEF3C7; color: #D97706; }

/* 8. Action Toolbar Styling */
div[class*="st-key-action_toolbar_container"] {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
}

div[class*="st-key-action_toolbar_container"] button {
    border: 1px solid #CBD5E1 !important;
    background: #FFFFFF !important;
    border-radius: 8px !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    padding: 5px 12px !important;
    height: 36px !important;
}

/* 9. Fixed Bottom Navigation Bar */
div[class*="st-key-hpe_bottom_nav_container"] {
    position: fixed !important;
    bottom: 0 !important;
    left: 0 !important;
    right: 0 !important;
    width: 100vw !important;
    height: 72px !important;
    background-color: #042121 !important;
    border-top: 1px solid rgba(255, 255, 255, 0.15) !important;
    z-index: 99998 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 10px 140px 10px 40px !important;
    box-shadow: 0 -4px 16px rgba(0, 0, 0, 0.35) !important;
}

div[class*="st-key-hpe_bottom_nav_container"] > div {
    width: 100% !important;
    max-width: 1300px !important;
    margin: 0 auto !important;
}

div[class*="st-key-hpe_bottom_nav_container"] [data-testid="stHorizontalBlock"] {
    align-items: center !important;
    justify-content: space-between !important;
    gap: 18px !important;
}

div[class*="st-key-hpe_bottom_nav_container"] button {
    background-color: transparent !important;
    color: #94A3B8 !important;
    border: 1px solid transparent !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 14.5px !important;
    padding: 8px 24px !important;
    height: 46px !important;
    transition: all 0.2s ease !important;
}

div[class*="st-key-hpe_bottom_nav_container"] button:hover {
    background-color: rgba(255, 255, 255, 0.08) !important;
    color: #FFFFFF !important;
}

div[class*="st-key-hpe_bottom_nav_container"] button[kind="primary"],
div[class*="st-key-hpe_bottom_nav_container"] button[data-testid="baseButton-primary"] {
    background-color: #00B388 !important;
    color: #FFFFFF !important;
    font-weight: 700 !important;
    border: none !important;
    box-shadow: 0 2px 8px rgba(0, 179, 136, 0.35) !important;
}

/* 10. Dashboard Table Header */
div[class*="st-key-dashboard_table_header"] {
    background-color: #F1F5F9 !important;
    border: 1px solid #E2E8F0 !important;
    border-radius: 8px !important;
    padding: 8px 10px !important;
    margin-bottom: 6px !important;
}

div[class*="st-key-dashboard_table_header"] [data-testid="stMarkdownContainer"] p {
    font-size: 12px !important;
    font-weight: 700 !important;
    color: #475569 !important;
    letter-spacing: 0.3px !important;
    margin: 0 !important;
}
</style>
"""

st.markdown(ENTERPRISE_CSS, unsafe_allow_html=True)

# ==============================================================================
# 7. INTERACTIVE CASE MODAL DIALOG (@st.dialog)
# ==============================================================================
@st.dialog("Case Details", width="large")
def render_case_modal(case_num):
    case = cases_collection.find_one({"type": "cases", "case_number": case_num})
    if not case:
        st.error(f"Case {case_num} not found.")
        return

    user = st.session_state.get("current_user", {})
    is_admin = user.get("role") in ["Admin", "Admin/Agent"]

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
        if case.get("status") == "Closed":
            st.markdown("<span class='badge badge-status st-closed'>Ticket Closed</span>", unsafe_allow_html=True)
        else:
            st.markdown("<span class='badge badge-critical'>Due in 36m</span>", unsafe_allow_html=True)

    tab_info, tab_vendor, tab_update, tab_breach = st.tabs([
        "📋 Case Information", "🏢 Vendor Information", "✏️ Update Case", "⚠️ Breach Notice Email"
    ])

    with tab_info:
        st.write(f"**Description:** {case.get('description')}")
        st.divider()
        st.markdown("##### 🕒 Case Activity History")
        history = list(cases_collection.find({"type": "case_history", "case_number": case_num}, sort=[("timestamp", -1)]))
        for h in history:
            st.markdown(f"• **{h.get('timestamp')}** - *{h.get('user')}*: **{h.get('action')}** ({h.get('details')})")

    with tab_vendor:
        st.markdown(f"#### {case.get('vendor_name', 'ABC Software Inc.')}")
        st.write(f"**Contact:** {case.get('vendor_contact', 'Michael Tan')} | **Email:** `{case.get('vendor_email', 'support@abcsoftware.com')}`")
        if st.button("📋 Copy Email", key="cpy_modal_em"):
            st.toast("Vendor email copied!")

    with tab_update:
        dropdowns = validation_collection.find_one({"type": "Validation_Dropdown"}) or {}
        st_opts = dropdowns.get("Case_Status", ["Open", "In Progress", "On Hold", "Closed"])
        new_st = st.selectbox("Status", st_opts, index=st_opts.index(case.get("status")) if case.get("status") in st_opts else 0)
        remarks = st.text_area("Remarks / Work Notes")

        target_agent = None
        if is_admin:
            roster_doc = collection.find_one({"type": "roster_list"}) or {}
            agents = [u["name"] for u in roster_doc.get("Data", []) if u.get("role") in ["Agent", "Admin/Agent"]]
            target_agent = st.selectbox("Reassign Case (Admin Only)", ["-- Keep Current Assignee --"] + agents)

        if st.button("💾 Update Case", type="primary"):
            updates = {"status": new_st, "last_update": get_current_ph_time().strftime("%b %d, %Y %I:%M %p")}
            if target_agent and target_agent != "-- Keep Current Assignee --":
                updates["assigned_to"] = target_agent
            cases_collection.update_one({"type": "cases", "case_number": case_num}, {"$set": updates})
            st.success("Case updated successfully!")
            time.sleep(0.5)
            st.rerun()

    with tab_breach:
        st.markdown("##### ✉️ Automated Breach Notice Notice")
        to_email = st.text_input("To", value=case.get("vendor_email", "support@abcsoftware.com"))
        subj = st.text_input("Subject", value=f"Notice of Contract Breach — {case_num} SLA Missed")
        body_template = f"Dear Partner,\n\nCase {case_num} has breached SLA. Immediate remediation required."
        st.text_area("Body", value=body_template, height=120)
        if st.button("📤 Send Notice", type="primary"):
            st.success(f"Breach notice delivered to {to_email}!")

@st.dialog("Broadcast Message", width="small")
def render_admin_message_dialog():
    st.markdown("### 📢 Broadcast Team Alert")
    roster_doc = collection.find_one({"type": "roster_list"}) or {}
    all_names = [u["name"] for u in roster_doc.get("Data", [])]
    target = st.selectbox("Target Recipient", ["All Logged-in Agents"] + all_names)
    msg = st.text_area("Alert Message", placeholder="Enter priority broadcast notification...")
    if st.button("Send Alert", type="primary", use_container_width=True):
        notif_doc = collection.find_one({"type": "notifications"}) or {}
        notif_list = notif_doc.get("Data", [])
        notif_list.append({
            "target_email": "all" if target == "All Logged-in Agents" else str(target),
            "title": "Admin Broadcast",
            "message": str(msg),
            "category": "broadcast",
            "acknowledged": "false",
            "created_at": str(get_current_ph_time().strftime("%I:%M %p"))
        })
        collection.update_one({"type": "notifications"}, {"$set": {"type": "notifications", "Data": notif_list}}, upsert=True)
        st.success("Alert broadcasted successfully!")

# ==============================================================================
# 8. TOP-RIGHT ALIGNED PROFILE FLYOUT DROPDOWN (EXACT VISUAL RECREATION)
# ==============================================================================
def render_profile_flyout():
    user = st.session_state.get("current_user", {})
    with st.container(key="profile_flyout_card"):
        st.markdown('<div class="flyout-pointer"></div>', unsafe_allow_html=True)
        c1, c2 = st.columns([5, 1])
        with c2:
            if st.button("✕", key="btn_close_prof_flyout"):
                st.session_state["show_profile_flyout"] = False
                st.rerun()

        st.markdown(f"""
        <div style="display:flex; gap:16px; align-items:center; margin-bottom:14px;">
            <img src="{user.get('profile_picture', 'https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=150')}" style="width:68px; height:68px; border-radius:50%; object-fit:cover; border:2.5px solid #00B388;" />
            <div>
                <h3 style="margin:0; font-size:18px; font-weight:800; color:#0F172A;">{user.get('name', 'Arianne Escabillas')}</h3>
                <span style="background:#E6F7F3; color:#00B388; font-size:11px; font-weight:700; padding:2px 8px; border-radius:10px;">{user.get('role', 'Admin')}</span>
                <p style="margin:4px 0 0 0; font-size:12px; color:#64748B;">{user.get('email', 'arianne.escabillas@hpe.com')}</p>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("<label style='font-size:12px; font-weight:700; color:#475569;'>Current Status / Aux (Real-Time Auto-Update)</label>", unsafe_allow_html=True)
        
        # Aux Selector with Border, Transparent Teal Background & Compact Spacing
        with st.container(key="profile_aux_wrapper"):
            aux_list = ["Available", "Admin Work", "Not Ready - Online", "Coaching", "Meeting", "Lunch", "Break", "Unscheduled Break"]
            curr_aux = user.get("current_aux", "Admin Work")
            st.selectbox(
                "Aux",
                aux_list,
                index=aux_list.index(curr_aux) if curr_aux in aux_list else 1,
                key="flyout_aux_selector",
                on_change=on_aux_dropdown_change,
                label_visibility="collapsed"
            )

        # Compact Divider to Reduce Space Below Aux Selector
        st.markdown('<hr class="flyout-divider">', unsafe_allow_html=True)
        
        # CONDITIONAL TODAY'S SCHEDULE (OMITTED FOR PURE ADMIN AS THEY HAVE NO PLOTTED SHIFTS)
        if user.get("role") != "Admin":
            sc_h1, sc_h2 = st.columns([1.5, 1])
            with sc_h1:
                st.markdown("<strong style='font-size:13px; color:#0F172A;'>Today's Schedule</strong>", unsafe_allow_html=True)
            with sc_h2:
                st.markdown("<span style='font-size:11px; color:#64748B; float:right;'>Monday, Sep 28, 2026 📅</span>", unsafe_allow_html=True)

            st.markdown("""
            <div style="margin-top:6px;">
                <div style="display:flex; justify-content:space-between; padding:5px 0; font-size:12px; border-bottom:1px solid #F8FAFC;"><span>🟢 08:00 AM – 10:00 AM</span> <strong style="color:#00B388;">Available</strong></div>
                <div style="display:flex; justify-content:space-between; padding:5px 0; font-size:12px; border-bottom:1px solid #F8FAFC;"><span>⚪ 10:00 AM – 10:15 AM</span> <strong style="color:#94A3B8;">Break</strong></div>
                <div style="display:flex; justify-content:space-between; padding:5px 0; font-size:12px; border-bottom:1px solid #F8FAFC;"><span>🟢 10:15 AM – 12:00 PM</span> <strong style="color:#00B388;">Available</strong></div>
                <div style="display:flex; justify-content:space-between; padding:5px 0; font-size:12px; border-bottom:1px solid #F8FAFC;"><span>🟡 12:00 PM – 01:00 PM</span> <strong style="color:#D97706;">Lunch</strong></div>
                <div style="display:flex; justify-content:space-between; padding:5px 0; font-size:12px; border-bottom:1px solid #F8FAFC;"><span>🟢 01:00 PM – 03:00 PM</span> <strong style="color:#00B388;">Available</strong></div>
                <div style="display:flex; justify-content:space-between; padding:5px 0; font-size:12px; border-bottom:1px solid #F8FAFC;"><span>⚪ 03:00 PM – 03:15 PM</span> <strong style="color:#94A3B8;">Break</strong></div>
                <div style="display:flex; justify-content:space-between; padding:5px 0; font-size:12px;"><span>🟢 03:15 PM – 05:00 PM</span> <strong style="color:#00B388;">Available</strong></div>
            </div>
            """, unsafe_allow_html=True)
            st.markdown('<hr class="flyout-divider">', unsafe_allow_html=True)

        act1, act2 = st.columns(2)
        with act1:
            if st.button("🔒 Change Password", key="flyout_change_pw", use_container_width=True):
                st.info("Password self-service active via HPE SSO.")
        with act2:
            if st.button("🚪 Sign Out", key="flyout_logout_btn", type="secondary", use_container_width=True):
                logout_user()

# ==============================================================================
# 9. TOP HEADER (PROFILE TRIGGER AT UPPER-RIGHT CORNER)
# ==============================================================================
def render_top_header():
    user = st.session_state.get("current_user", {})
    curr_aux = user.get("current_aux", "Admin Work")

    notif_doc = collection.find_one({"type": "notifications"}) or {}
    notifs = notif_doc.get("Data", [])
    unread_notifs = sum(1 for n in notifs if (n.get("target_email") in [user.get("email"), "all"]) and (str(n.get("acknowledged")).lower() in ["false", "0"]))

    with st.container(key="hpe_top_bar_container"):
        c_brand, c_search, c_bell, c_prof, c_time = st.columns([3.0, 4.2, 0.5, 2.5, 1.8])

        with c_brand:
            st.markdown("""
            <div style="display:flex; align-items:center; gap:10px;">
                <div style="border:3.5px solid #00B388; width:26px; height:18px; border-radius:2px;"></div>
                <div style="color:white; line-height:1.15;">
                    <strong style="font-size:19px; letter-spacing:-0.2px;">HPE &nbsp;CaseFlow</strong><br>
                    <small style="color:#94A3B8; font-size:11px;">Task Monitoring & Management</small>
                </div>
            </div>
            """, unsafe_allow_html=True)

        with c_search:
            st.text_input("Global Search", placeholder="🔍 Search cases, names, issues...", label_visibility="collapsed")

        with c_bell:
            st.markdown(f"""
            <div style="position:relative; text-align:center; font-size:20px; cursor:pointer; color:white; padding-top:4px;">
                🔔<span style="position:absolute; top:-3px; right:2px; background:#EF4444; color:white; font-size:10px; font-weight:800; border-radius:50%; padding:1px 5px;">{unread_notifs}</span>
            </div>
            """, unsafe_allow_html=True)

        with c_prof:
            with st.container(key="top_profile_pill_btn"):
                btn_label = f"👤 {user.get('name', 'Arianne Escabillas')} • {curr_aux} ▾"
                if st.button(btn_label, key="btn_open_profile_top_right", use_container_width=True):
                    st.session_state["show_profile_flyout"] = not st.session_state.get("show_profile_flyout", False)
                    st.rerun()

        with c_time:
            st.markdown("""
            <div style="text-align:right; color:white; line-height:1.15;">
                <small style="color:#94A3B8; font-size:11px;">Mon, Sep 28, 2026</small><br>
                <strong style="font-size:16px;">10:24 AM</strong>
            </div>
            """, unsafe_allow_html=True)

    if st.session_state.get("show_profile_flyout", False):
        render_profile_flyout()

# ==============================================================================
# 10. DASHBOARD: PERFECT HORIZONTAL ALIGNMENT (TILES & SCHEDULE/ROSTER)
# ==============================================================================
def render_dashboard():
    user = st.session_state.get("current_user", {})
    user_role = user.get("role", "Admin/Agent")

    # Perspective State Management
    if "view_mode" not in st.session_state:
        st.session_state["view_mode"] = "Admin" if user_role in ["Admin", "Admin/Agent"] else "Agent"
    
    if user_role == "Agent":
        st.session_state["view_mode"] = "Agent"

    is_admin_mode = (st.session_state["view_mode"] == "Admin")

    # Query Base Filter on Cases_Collection
    q_base = {"type": "cases"}
    if not is_admin_mode:
        q_base["assignee_email"] = user.get("email")

    total_active = cases_collection.count_documents({**q_base, "status": {"$ne": "Closed"}})
    total_critical = cases_collection.count_documents({**q_base, "priority": "Critical", "status": {"$ne": "Closed"}})
    total_due_soon = cases_collection.count_documents({**q_base, "priority": {"$in": ["Critical", "High"]}, "status": {"$ne": "Closed"}})
    total_on_track = cases_collection.count_documents({**q_base, "priority": {"$in": ["Medium", "Low"]}, "status": {"$ne": "Closed"}})

    # ==========================================================================
    # 2-COLUMN MASTER GRID (STATUS TILES & SCHEDULE/AGENTS START AT SAME BASELINE)
    # ==========================================================================
    main_left, main_right = st.columns([2.88, 1.12], gap="large")

    # --------------------------------------------------------------------------
    # LEFT COLUMN: STATUS TILES + TABLE
    # --------------------------------------------------------------------------
    with main_left:
        # Header Row: Title & Segmented Tile (Admin/Agent)
        hd_col1, hd_col2 = st.columns([2.5, 1.5])
        with hd_col1:
            pass  # Kept clean to maintain exact vertical baseline with right rail
        with hd_col2:
            if user_role == "Admin/Agent":
                st.markdown("<div style='text-align:right; margin-bottom:8px;'>", unsafe_allow_html=True)
                with st.container(key="view_mode_segmented_tile"):
                    t_col1, t_col2 = st.columns(2)
                    with t_col1:
                        is_adm_active = (st.session_state["view_mode"] == "Admin")
                        btn_kind_adm = "primary" if is_adm_active else "secondary"
                        if st.button("Admin View", key="btn_tile_admin_view", type=btn_kind_adm, use_container_width=True):
                            st.session_state["view_mode"] = "Admin"
                            st.rerun()
                    with t_col2:
                        is_agt_active = (st.session_state["view_mode"] == "Agent")
                        btn_kind_agt = "primary" if is_agt_active else "secondary"
                        if st.button("Agent View", key="btn_tile_agent_view", type=btn_kind_agt, use_container_width=True):
                            st.session_state["view_mode"] = "Agent"
                            st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

        # 4 Metric Cards Exactly Aligned
        mc1, mc2, mc3, mc4 = st.columns(4)
        with mc1:
            st.markdown(f"""
            <div class="metric-card-box">
                <div class="metric-circle-icon" style="background:#EDF5FD; color:#0284C7;">📁</div>
                <div>
                    <p class="metric-card-label">{'Active Cases' if is_admin_mode else 'My Active Cases'}</p>
                    <h3 class="metric-card-val">{total_active}</h3>
                    <p class="metric-card-trend" style="color:#0284C7;">↑ +5% <span style="font-weight:400; color:#64748B;">vs last week</span></p>
                </div>
            </div>
            """, unsafe_allow_html=True)
        with mc2:
            st.markdown(f"""
            <div class="metric-card-box">
                <div class="metric-circle-icon" style="background:#FDF2F2; color:#DC2626;">⚠️</div>
                <div>
                    <p class="metric-card-label">{'Critical Cases' if is_admin_mode else 'My Critical Cases'}</p>
                    <h3 class="metric-card-val">{total_critical}</h3>
                    <p class="metric-card-trend" style="color:#DC2626;">↑ +2 <span style="font-weight:400; color:#64748B;">vs last week</span></p>
                </div>
            </div>
            """, unsafe_allow_html=True)
        with mc3:
            st.markdown(f"""
            <div class="metric-card-box">
                <div class="metric-circle-icon" style="background:#FEF6EC; color:#D97706;">⏰</div>
                <div>
                    <p class="metric-card-label">Due Soon</p>
                    <h3 class="metric-card-val">{total_due_soon}</h3>
                    <p class="metric-card-trend" style="color:#D97706;">↑ +3 <span style="font-weight:400; color:#64748B;">vs last week</span></p>
                </div>
            </div>
            """, unsafe_allow_html=True)
        with mc4:
            st.markdown(f"""
            <div class="metric-card-box">
                <div class="metric-circle-icon" style="background:#EDFAF3; color:#16A34A;">✅</div>
                <div>
                    <p class="metric-card-label">On Track</p>
                    <h3 class="metric-card-val">{total_on_track}</h3>
                    <p class="metric-card-trend" style="color:#16A34A;">↑ +10% <span style="font-weight:400; color:#64748B;">vs last week</span></p>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

        # Title & Toolbar
        t_head, t_act = st.columns([1.5, 2.5])
        with t_head:
            heading = "Active Cases" if is_admin_mode else "My Cases"
            st.markdown(f"""
            <div style="display:flex; align-items:center; gap:10px; margin-top:4px;">
                <h2 style="font-size:22px; font-weight:800; color:#0F172A; margin:0;">{heading}</h2>
                <span style="background:#DCFCE7; color:#16A34A; font-size:12px; font-weight:700; padding:2px 10px; border-radius:12px;">{total_active} cases</span>
            </div>
            """, unsafe_allow_html=True)
        with t_act:
            with st.container(key="action_toolbar_container"):
                a1, a2, a3, a4, a5 = st.columns([1.1, 1.2, 1.5, 1.1, 0.5])
                with a1:
                    st.checkbox("Select All", key="chk_sel_all")
                with a2:
                    if st.button("🔄 Reassign", key="btn_tb_reassign", use_container_width=True):
                        st.toast("Multi-case reassignment enabled.")
                with a3:
                    st.selectbox("Status", ["Change Status ▾", "In Progress", "Waiting Vendor", "Vendor Response", "Closed"], label_visibility="collapsed")
                with a4:
                    if st.button("📥 Export", key="btn_tb_export", use_container_width=True):
                        all_cases = list(cases_collection.find(q_base))
                        if all_cases:
                            csv_bytes = pd.DataFrame(all_cases).to_csv(index=False).encode("utf-8")
                            st.download_button("Download CSV", csv_bytes, "HPE_Cases_Export.csv", "text/csv")
                with a5:
                    if st.button("⟳", key="btn_tb_refresh", help="Refresh Data", use_container_width=True):
                        st.rerun()

        # Filter Strip (With Include Closed Cases Option)[cite: 10, 11]
        f1, f2, f3, f4 = st.columns([2.5, 1.2, 1.3, 1.5])
        with f1:
            search_val = st.text_input("Search", placeholder="🔍 Search by case #, subject, assignee...", label_visibility="collapsed")
        with f2:
            pri_filter = st.selectbox("Priority", ["All Priorities", "Critical", "High", "Medium", "Low"], label_visibility="collapsed")
        with f3:
            st_filter = st.selectbox("Filter Status", ["All Statuses", "Open", "In Progress", "Vendor Response", "Waiting Vendor", "Closed"], label_visibility="collapsed")
        with f4:
            include_closed = st.checkbox("Include Closed Cases", key="chk_include_closed_cases")

        if st.button("➕ Register New Case for Auto-Assignment"):
            st.session_state["show_new_case_expander"] = not st.session_state.get("show_new_case_expander", False)

        if st.session_state.get("show_new_case_expander"):
            with st.expander("New Case Submission", expanded=True):
                nc_c1, nc_c2 = st.columns(2)
                with nc_c1:
                    new_subj = st.text_input("Subject", "Storage Controller Bus Failure")
                    new_pri = st.selectbox("Priority Level", ["Critical", "High", "Medium", "Low"])
                with nc_c2:
                    new_vend = st.text_input("Vendor Name", "ABC Software Inc.")
                    new_vend_email = st.text_input("Vendor Contact Email", "support@abcsoftware.com")
                new_desc = st.text_area("Detailed Problem Description", "Chassis controller PCIe bus disconnect.")

                if st.button("Dispatch Case to Available Roster", type="primary"):
                    new_num = f"HPE-2026-{1050 + cases_collection.count_documents({'type': 'cases'})}"
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
                        "elapsed": "Just now",
                        "vendor_name": new_vend,
                        "vendor_email": new_vend_email,
                        "account": "Enterprise Core",
                        "related_system": "HPE Pointnext"
                    }
                    success, assigned_agent = auto_assign_new_case(new_case_payload)
                    st.success(f"Case {new_num} registered and auto-assigned to: {assigned_agent}!")
                    time.sleep(1)
                    st.session_state["show_new_case_expander"] = False
                    st.rerun()

        st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)

        # Table Header
        with st.container(key="dashboard_table_header"):
            h_chk, h_num, h_sub, h_pri, h_ass, h_due, h_st, h_up, h_opt = st.columns([0.4, 1.6, 2.8, 1.2, 1.8, 1.6, 1.4, 1.8, 0.4])
            with h_chk: st.markdown("**☐**")
            with h_num: st.markdown("**Case #  ⇅**")
            with h_sub: st.markdown("**Subject**")
            with h_pri: st.markdown("**Priority  ⇅**")
            with h_ass: st.markdown("**Assigned To  ⇅**")
            with h_due: st.markdown("**Due Date  ⇅**")
            with h_st: st.markdown("**Current Status  ⇅**")
            with h_up: st.markdown("**Last Update  ⇅**")
            with h_opt: st.markdown("**Actions**")

        # Query Formulation on Cases_Collection
        q = q_base.copy()
        if pri_filter != "All Priorities":
            q["priority"] = pri_filter
        if st_filter != "All Statuses":
            q["status"] = st_filter
        elif not include_closed:
            q["status"] = {"$ne": "Closed"}

        if search_val:
            q["$or"] = [
                {"case_number": {"$regex": search_val}},
                {"subject": {"$regex": search_val}},
                {"assigned_to": {"$regex": search_val}}
            ]

        cases = list(cases_collection.find(q))
        for c in cases:
            pri = c.get("priority", "Low")
            badge_pri = f"badge-{pri.lower()}"
            status_val = c.get("status", "Open")
            
            st_cls_map = {
                "In Progress": "st-in-progress",
                "Vendor Response": "st-vendor-response",
                "Waiting Vendor": "st-waiting-vendor",
                "Open": "st-open",
                "Pending Info": "st-pending-info",
                "Closed": "st-closed"
            }
            badge_st = st_cls_map.get(status_val, "st-open")

            rc1, rc2, rc3, rc4, rc5, rc6, rc7, rc8, rc9 = st.columns([0.4, 1.6, 2.8, 1.2, 1.8, 1.6, 1.4, 1.8, 0.4])
            with rc1:
                st.checkbox("", key=f"chk_c_{c['case_number']}_{'adm' if is_admin_mode else 'agt'}", label_visibility="collapsed")
            with rc2:
                if st.button(f"{c['case_number']}", key=f"btn_case_{c['case_number']}_{'adm' if is_admin_mode else 'agt'}"):
                    render_case_modal(c["case_number"])
            with rc3:
                st.markdown(f"<span style='font-size:13px; font-weight:500; color:#1E293B;'>{c.get('subject')}</span>", unsafe_allow_html=True)
            with rc4:
                st.markdown(f"<span class='badge {badge_pri}'>{pri}</span>", unsafe_allow_html=True)
            with rc5:
                assignee_label = "Me" if (not is_admin_mode and c.get('assignee_email') == user.get('email')) else c.get('assigned_to')
                st.markdown(f"""
                <div style="display:flex; align-items:center; gap:8px;">
                    <img src="{c.get('assignee_avatar', 'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150')}" style="width:24px; height:24px; border-radius:50%; object-fit:cover;" />
                    <span style="font-size:12.5px; font-weight:600; color:#334155;">{assignee_label}</span>
                </div>
                """, unsafe_allow_html=True)
            with rc6:
                due_color = "#64748B" if status_val == "Closed" else "#DC2626"
                st.markdown(f"<span style='color:{due_color}; font-size:12px; font-weight:600;'>{c.get('due_date')}</span>", unsafe_allow_html=True)
            with rc7:
                st.markdown(f"<span class='badge-status {badge_st}'>{status_val}</span>", unsafe_allow_html=True)
            with rc8:
                st.markdown(f"""
                <div style="line-height:1.2;">
                    <span style="font-size:12px; color:#475569;">{c.get('last_update')}</span><br>
                    <small style="color:#94A3B8; font-size:11px;">{c.get('elapsed', '1h ago')}</small>
                </div>
                """, unsafe_allow_html=True)
            with rc9:
                st.markdown("<span style='color:#64748B; font-weight:700; cursor:pointer;'>⋮</span>", unsafe_allow_html=True)
            st.divider()

        # Pagination Footer
        p_info, p_btns = st.columns([1, 1])
        with p_info:
            st.caption(f"Showing 1 - {len(cases)} of {total_active} cases")
        with p_btns:
            st.markdown("""
            <div style="display:flex; justify-content:flex-end; gap:6px; align-items:center;">
                <span style="border:1px solid #CBD5E1; border-radius:6px; padding:4px 10px; font-size:12px; cursor:pointer;">&lt;</span>
                <span style="background:#00B388; color:white; border-radius:6px; padding:4px 10px; font-size:12px; font-weight:700;">1</span>
                <span style="border:1px solid #CBD5E1; border-radius:6px; padding:4px 10px; font-size:12px; cursor:pointer;">2</span>
                <span style="border:1px solid #CBD5E1; border-radius:6px; padding:4px 10px; font-size:12px; cursor:pointer;">3</span>
                <span style="border:1px solid #CBD5E1; border-radius:6px; padding:4px 10px; font-size:12px; cursor:pointer;">&gt;</span>
            </div>
            """, unsafe_allow_html=True)

    # --------------------------------------------------------------------------
    # RIGHT COLUMN: EXACTLY ALIGNED WITH THE METRIC CARDS
    # --------------------------------------------------------------------------
    with main_right:
        if is_admin_mode:
            # 1. ADMIN RIGHT RAIL: ONLINE AGENTS (12)
            st.markdown('<div class="agents-panel-card">', unsafe_allow_html=True)
            st.markdown("""
            <h3 style="font-size:17px; font-weight:800; color:#0F172A; margin:0 0 2px 0;">Online Agents</h3>
            <p style="font-size:12px; color:#64748B; margin:0 0 12px 0;">Agent and Admin/Agent Currently Logged In</p>
            """, unsafe_allow_html=True)

            agent_search = st.text_input("Search agent...", placeholder="🔍 Search agent...", label_visibility="collapsed", key="search_agent_input")
            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

            roster_doc = collection.find_one({"type": "roster_list"}) or {}
            online_roster = roster_doc.get("Data", [])
            aux_cls_map = {
                "Available": "aux-avail",
                "Lunch": "aux-lunch",
                "Meeting": "aux-meeting",
                "Break": "aux-break",
                "Not Ready - Online": "aux-not-ready",
                "Admin Work": "aux-avail"
            }

            for ag in online_roster:
                if ag.get("role") != "Admin":
                    if not agent_search or (agent_search.lower() in ag.get("name", "").lower()):
                        aux = ag.get("current_aux", "Available")
                        cls_name = aux_cls_map.get(aux, "aux-avail")
                        st.markdown(f"""
                        <div class="agent-row-item">
                            <div style="display:flex; align-items:center; gap:10px;">
                                <img src="{ag.get('profile_picture', 'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150')}" style="width:34px; height:34px; border-radius:50%; object-fit:cover;" />
                                <div style="line-height:1.2;">
                                    <strong style="font-size:13px; color:#0F172A;">{ag.get('name')}</strong><br>
                                    <small style="font-size:11px; color:#64748B;">{ag.get('role')}</small>
                                </div>
                            </div>
                            <span class="aux-badge {cls_name}">{aux}</span>
                        </div>
                        """, unsafe_allow_html=True)

            st.markdown("<div style='text-align:center; color:#94A3B8; padding-top:12px; cursor:pointer;'>⋮</div>", unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

            if st.button("📢 Broadcast Alert Message", use_container_width=True):
                render_admin_message_dialog()

        else:
            # 2. AGENT RIGHT RAIL: TODAY'S SCHEDULE + ANNOUNCEMENTS + QUICK ACTIONS
            sc_c1, sc_c2 = st.columns([2, 1])
            with sc_c1:
                st.markdown("#### 📅 Today's Schedule")
            with sc_c2:
                st.markdown("<span style='font-size:12px; color:#0284C7; font-weight:700; float:right; cursor:pointer;'>View All</span>", unsafe_allow_html=True)
                
            st.markdown("""
            <div style="background:white; border-radius:10px; padding:12px 16px; border:1px solid #E2E8F0; font-size:12px; line-height:2.2; margin-bottom:16px;">
                🟢 08:00 AM &nbsp; <strong>On Shift / Available</strong><br>
                🔵 10:00 AM &nbsp; <strong>Case Work</strong><br>
                🟡 12:00 PM &nbsp; <strong>Lunch Break</strong><br>
                🔵 01:00 PM &nbsp; <strong>Case Work</strong><br>
                🟣 03:00 PM &nbsp; <strong>Coaching Session</strong><br>
                🔵 04:00 PM &nbsp; <strong>Case Work</strong>
            </div>
            """, unsafe_allow_html=True)

            al_c1, al_c2 = st.columns([2, 1])
            with al_c1:
                st.markdown("#### 🔔 Announcements / Alerts")
            with al_c2:
                st.markdown("<span style='font-size:12px; color:#0284C7; font-weight:700; float:right; cursor:pointer;'>View All</span>", unsafe_allow_html=True)

            notif_doc = collection.find_one({"type": "notifications"}) or {}
            notifs = [n for n in notif_doc.get("Data", []) if n.get("target_email") in [user.get("email"), "all"]][-5:]

            for n in reversed(notifs):
                cat = n.get("category", "info")
                icon = "⚠️" if cat == "critical" else ("➕" if cat == "new_case" else "📢")
                st.markdown(f"""
                <div style="background:white; border-radius:8px; padding:10px 14px; border-left:3px solid #00B388; margin-bottom:8px; font-size:12px;">
                    <strong>{icon} {n.get('title')}</strong> &bull; <small style="color:#94A3B8;">{n.get('created_at')}</small><br>
                    {n.get('message')}
                </div>
                """, unsafe_allow_html=True)

            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
            st.markdown("#### ⚡ Quick Actions")
            qa1, qa2 = st.columns(2)
            with qa1:
                if st.button("✉️ Send Message", use_container_width=True):
                    st.toast("Direct messaging workspace active.")
                if st.button("📅 View Schedule", use_container_width=True):
                    st.session_state["current_tab"] = "Schedule"
                    st.rerun()
            with qa2:
                if st.button("🔄 Request Transfer", use_container_width=True):
                    st.toast("Open a case to initiate peer transfer.")
                if st.button("📊 View Report", use_container_width=True):
                    st.session_state["current_tab"] = "Report"
                    st.rerun()

# ==============================================================================
# 11. MONITORING TAB (ADMIN ONLY)
# ==============================================================================
def render_monitoring():
    st.markdown("### 📊 Operational Roster & Telemetry Monitoring")
    st.caption("Active shift telemetry, login durations, and case allocation load per agent:")

    roster_doc = collection.find_one({"type": "roster_list"}) or {}
    agents = [u for u in roster_doc.get("Data", []) if u.get("role") != "Admin"]
    table_data = []
    for a in agents:
        assigned_today = cases_collection.count_documents({"type": "cases", "assignee_email": a["email"]})
        crit_assigned = cases_collection.count_documents({"type": "cases", "assignee_email": a["email"], "priority": "Critical"})
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
        if table_data:
            kick_agent = st.selectbox("Select Agent to Session Terminate (Kick)", [d["Name"] for d in table_data])
            if st.button("🚫 Terminate Session (Force Logout)", type="secondary"):
                # Terminate inside type: 'sessions'
                sess_doc = collection.find_one({"type": "sessions"}) or {}
                sess_list = sess_doc.get("Data", [])
                for s in sess_list:
                    if s.get("name") == kick_agent:
                        s["status"] = "terminated"
                        s["expires_at"] = "2000-01-01 00:00:00"
                collection.update_one({"type": "sessions"}, {"$set": {"Data": sess_list}}, upsert=True)

                # Update inside type: 'roster_list'
                for u in agents:
                    if u.get("name") == kick_agent:
                        u["is_logged_in"] = "false"
                        u["current_aux"] = "Not Ready - Online"
                collection.update_one({"type": "roster_list"}, {"$set": {"Data": roster_doc.get("Data", [])}}, upsert=True)
                st.success(f"{kick_agent} has been successfully logged out from the enterprise cluster.")
    with m_col2:
        st.info("Tip: Aux telemetry events are recorded in real-time to avoid duplicate critical case distribution.")

# ==============================================================================
# 12. SCHEDULE TAB
# ==============================================================================
def render_schedule():
    user = st.session_state.get("current_user", {})
    st.markdown("### 📅 Enterprise Workforce Schedule & PTO Tracker")
    current_ym = get_current_ph_time().strftime("%Y-%m")
    pto_doc = collection.find_one({"type": "Schedule_Monitoring"}) or {"total_allocation": 20, "used_allocation": 4}

    rem_pto = pto_doc.get("total_allocation", 20) - pto_doc.get("used_allocation", 0)

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
                if "PTO" in leave_type:
                    collection.update_one(
                        {"type": "Schedule_Monitoring"},
                        {"$inc": {"used_allocation": 1}}
                    )
                st.success(f"{leave_type} successfully recorded for {req_date}!")
                time.sleep(0.8)
                st.rerun()

    with sch2:
        st.markdown("#### 🔄 Schedule Swap Request")
        roster_doc = collection.find_one({"type": "roster_list"}) or {}
        other_agents = [u["name"] for u in roster_doc.get("Data", []) if u.get("email") != user.get("email")]
        if other_agents:
            colleague = st.selectbox("Select Colleague to Swap Shift With", other_agents)
            swap_date = st.date_input("Your Shift Date", value=get_current_ph_time() + timedelta(days=1))
            if st.button("Propose Instant Swap", use_container_width=True):
                st.success(f"Shift swap request dispatched to {colleague} and automatically synced!")

# ==============================================================================
# 13. REPORT TAB (PLOTLY VISUALIZATIONS)
# ==============================================================================
def render_report():
    user = st.session_state.get("current_user", {})
    is_admin = user.get("role") in ["Admin", "Admin/Agent"]
    
    st.markdown("### 📈 Operational KPI & Performance Analytics")
    period = st.radio("Reporting Horizon", ["Daily", "WOW (Week-Over-Week)", "MTD (Month-To-Date)", "YTD"], horizontal=True)

    q = {"type": "cases"}
    if not is_admin:
        q["assignee_email"] = user.get("email")

    cases = list(cases_collection.find(q))
    df = pd.DataFrame(cases)

    if df.empty:
        st.info("No cases logged in the specified horizon.")
        return

    c1, c2 = st.columns(2)
    with c1:
        fig_pri = px.pie(
            df, names="priority", title="Cases by Priority Distribution",
            color="priority",
            color_discrete_map={"Critical": "#DC2626", "High": "#EA580C", "Medium": "#D97706", "Low": "#16A34A"},
            hole=0.45
        )
        fig_pri.update_layout(margin=dict(t=40, b=20, l=20, r=20))
        st.plotly_chart(fig_pri, use_container_width=True)

    with c2:
        status_counts = df["status"].value_counts().reset_index()
        status_counts.columns = ["Status", "Count"]
        fig_st = px.bar(
            status_counts, x="Status", y="Count", title="Case Volumes by Operational Status",
            color="Status", color_discrete_sequence=["#00B388", "#2563EB", "#F59E0B", "#8B5CF6", "#64748B"]
        )
        fig_st.update_layout(margin=dict(t=40, b=20, l=20, r=20), showlegend=False)
        st.plotly_chart(fig_st, use_container_width=True)

    st.markdown("#### 🎯 Service Level Adherence & Attendance Telemetry")
    a1, a2, a3 = st.columns(3)
    a1.metric("Schedule Adherence", "96.4%", "↑ +1.2% target")
    a2.metric("Shift Attendance Rate", "98.2%", "Scheduled vs Attended")
    a3.metric("SLA Resolution Compliance", "94.8%", "Target: 95.0%")

# ==============================================================================
# 14. SETTINGS TAB (ADMIN ONLY)
# ==============================================================================
def render_settings():
    st.markdown("### ⚙️ Enterprise Configuration & Master Registry")
    
    set_t1, set_t2, set_t3 = st.tabs(["👥 Team Roster Management", "🗄️ Validation Dropdowns", "📥 Vendor Excel Sync"])

    with set_t1:
        st.markdown("##### Manage Roles & User Accounts")
        roster_doc = collection.find_one({"type": "roster_list"}) or {}
        users = roster_doc.get("Data", [])
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
                    u["role"] = new_role
                    collection.update_one({"type": "roster_list"}, {"$set": {"Data": users}}, upsert=True)
                    st.success(f"Role updated to {new_role}!")
            st.divider()

    with set_t2:
        st.markdown("##### System Validation Picklists")
        dropdown_doc = validation_collection.find_one({"type": "Validation_Dropdown"}) or {}
        st.write("**Case Statuses:**", ", ".join(dropdown_doc.get("Case_Status", [])))
        st.write("**Contract Breach Reasons:**", ", ".join(dropdown_doc.get("Contract_Breach", [])))
        st.info("Validation dropdowns are synchronized with MongoDB Validation_Dropdown schema.")

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
# 15. AUTHENTICATION PAGES (SIGN-IN & SIGN-UP)
# ==============================================================================
def render_auth_page():
    auth_mode = st.session_state.get("auth_mode", "Sign In")

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
                    default_aux = "Admin Work" if user.get("role") in ["Admin", "Admin/Agent"] else "Not Ready - Online"
                    
                    # Update login status inside type: 'roster_list' Data
                    roster_doc = collection.find_one({"type": "roster_list"}) or {}
                    users = roster_doc.get("Data", [])
                    for u in users:
                        if u.get("email") == user["email"]:
                            u["is_logged_in"] = "true"
                            u["current_aux"] = str(default_aux)
                    collection.update_one({"type": "roster_list"}, {"$set": {"Data": users}}, upsert=True)

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
            # SIGN UP SCREEN: ALL contained under type: "roster_list" in Team Roster Collection
            st.markdown("## **Create Your Account**")
            st.caption("Sign up to access HPE CaseFlow")

            su_fn = st.text_input("First Name", placeholder="Enter your first name")
            su_ln = st.text_input("Last Name", placeholder="Enter your last name")
            su_eid = st.text_input("Employee ID", placeholder="Enter your employee ID (e.g. HPE12345)")
            su_email = st.text_input("HPE Email Address", placeholder="yourname@hpe.com")
            su_pw = st.text_input("Password", type="password", placeholder="Create a password (min 8 chars, numbers, letters)")

            st.caption("Password must be at least 8 characters and include letters, numbers and a special character.")

            if st.button("Sign Up", type="primary", use_container_width=True):
                roster_doc = collection.find_one({"type": "roster_list"}) or {}
                existing_users = roster_doc.get("Data", [])
                
                email_exists = any(u.get("email", "").strip().lower() == str(su_email).strip().lower() for u in existing_users)
                eid_exists = any(str(u.get("employee_id", "")).strip() == str(su_eid).strip() for u in existing_users)

                if not (su_fn and su_ln and su_eid and su_email and su_pw):
                    st.error("All registration fields are required.")
                elif len(su_pw) < 8 or not re.search(r"\d", su_pw) or not re.search(r"[!@#$%^&*(),.?\":{}|<>]", su_pw):
                    st.error("Password does not meet complexity requirements.")
                elif email_exists:
                    st.error("An account with this HPE email already exists.")
                elif eid_exists:
                    st.error("An account with this Employee ID already exists.")
                else:
                    hashed = hash_password(su_pw)
                    now_str = get_current_ph_time().strftime("%Y-%m-%d %H:%M:%S")
                    
                    new_user = {
                        "first_name": str(su_fn).strip(),
                        "last_name": str(su_ln).strip(),
                        "name": str(f"{su_fn} {su_ln}").strip(),
                        "employee_id": str(su_eid).strip(),
                        "email": str(su_email).strip().lower(),
                        "password_hash": str(hashed),
                        "role": "Agent",
                        "department": "Operations",
                        "current_aux": "Not Ready - Online",
                        "is_logged_in": "true",
                        "profile_picture": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150",
                        "created_at": str(now_str),
                        "updated_at": str(now_str)
                    }

                    # Contained under type: "roster_list" (does not generate multiple documents)
                    existing_users.append(new_user)
                    collection.update_one(
                        {"type": "roster_list"},
                        {"$set": {"type": "roster_list", "Data": existing_users}},
                        upsert=True
                    )
                    
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
# 16. FIXED BOTTOM NAVIGATION (BIGGER & SPREAD OUT)
# ==============================================================================
def render_bottom_navigation():
    """Renders bottom navigation tabs pinned inside the dark teal bar."""
    user = st.session_state.get("current_user", {})
    is_admin = user.get("role") in ["Admin", "Admin/Agent"]
    
    tabs = ["Dashboard", "Schedule", "Report"]
    if is_admin:
        tabs = ["Dashboard", "Monitoring", "Schedule", "Report", "Setting"]

    current_tab = st.session_state.get("current_tab", "Dashboard")
    
    icons = {
        "Dashboard": "⊞  Dashboard",
        "Monitoring": "👥  Monitoring",
        "Schedule": "📅  Schedule",
        "Report": "📊  Report",
        "Setting": "⚙️  Setting"
    }

    with st.container(key="hpe_bottom_nav_container"):
        cols = st.columns(len(tabs))
        for idx, t in enumerate(tabs):
            with cols[idx]:
                is_active = (current_tab == t)
                btn_type = "primary" if is_active else "secondary"
                if st.button(icons.get(t, t), key=f"nav_tab_{t}", type=btn_type, use_container_width=True):
                    st.session_state["current_tab"] = t
                    st.rerun()

# ==============================================================================
# 17. MAIN ROUTER
# ==============================================================================
def main():
    if not st.session_state.get("authenticated", False):
        validate_saved_session()

    # Initial showcase auto-auth with Arianne Escabillas (unless manually signed out)
    if not st.session_state.get("authenticated", False) and not st.session_state.get("manual_logout", False):
        roster_doc = collection.find_one({"type": "roster_list"}) or {}
        admin_user = next((u for u in roster_doc.get("Data", []) if u.get("email") == "arianne.escabillas@hpe.com"), None)
        if admin_user:
            create_session(admin_user, remember_me=True)
            st.rerun()

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
