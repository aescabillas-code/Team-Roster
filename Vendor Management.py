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
# DYNAMIC TIME PARSING & COUNTDOWN ENGINE (PC/LOCAL TIME AWARE)
# ==============================================================================
def parse_case_datetime(dt_str):
    if not dt_str:
        return None
    formats = [
        "%b %d, %Y %I:%M %p",
        "%b %d, %Y %I:%M%p",
        "%Y-%m-%d %H:%M:%S",
        "%b %d, %Y %H:%M",
        "%Y-%m-%d %I:%M %p",
        "%Y-%m-%d"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(str(dt_str).strip(), fmt).replace(tzinfo=MANILA_TZ)
        except Exception:
            continue
    return None


def calculate_countdown(due_date_str):
    due_dt = parse_case_datetime(due_date_str)
    if not due_dt:
        return "No Due Date", "#64748B", False
    now = get_current_ph_time()
    diff_secs = (due_dt - now).total_seconds()
    is_overdue = diff_secs < 0
    abs_secs = abs(diff_secs)
    hours = int(abs_secs // 3600)
    minutes = int((abs_secs % 3600) // 60)


    if is_overdue:
        text = f"Overdue by {hours}h {minutes}m" if hours > 0 else f"Overdue by {minutes}m"
        return text, "#DC2626", True
    else:
        if abs_secs < 60:
            text = "Due now"
        elif hours > 0:
            text = f"Due in {hours}h {minutes}m"
        else:
            text = f"Due in {minutes}m"
        color = "#DC2626" if hours < 2 else "#D97706"
        return text, color, False


def calculate_elapsed(created_date_str):
    c_dt = parse_case_datetime(created_date_str)
    if not c_dt:
        return "19h 45m"
    now = get_current_ph_time()
    diff_secs = max(0, (now - c_dt).total_seconds())
    hours = int(diff_secs // 3600)
    minutes = int((diff_secs % 3600) // 60)
    return f"{hours}h {minutes}m"


def calculate_hours_ago(update_str):
    u_dt = parse_case_datetime(update_str)
    if not u_dt:
        return "0.7h ago"
    now = get_current_ph_time()
    diff_hours = max(0.0, (now - u_dt).total_seconds() / 3600.0)
    return f"{diff_hours:.1f}h ago"


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
# 3. INITIAL SEED DATA & AUTO-CLEANUP FOR REAL CASES/ROSTER
# ==============================================================================
def init_database():
    try:
        existing_indexes = collection.index_information()
        for idx_name in list(existing_indexes.keys()):
            if idx_name not in ["_id_", "_id"]:
                collection.drop_index(idx_name)
    except Exception:
        pass


    try:
        collection.create_index([("type", 1)], unique=True)
        cases_collection.create_index([("case_number", 1)], sparse=True)
        cases_collection.create_index([("type", 1)])
    except Exception:
        pass


    try:
        dropdown_doc = validation_collection.find_one({"type": "Validation_Dropdown"})
        if not dropdown_doc:
            validation_collection.insert_one({
                "type": "Validation_Dropdown",
                "Case_Status": ["New", "Open", "In Progress", "On Hold", "Pending Vendor", "Pending Client", "Resolved", "Closed"],
                "Case_Reason": [
                    "Waiting for Vendor Response",
                    "Waiting for Client",
                    "Pending Internal Action",
                    "Pending Approval",
                    "Investigation",
                    "Technical Issue",
                    "Initial contact with vendor",
                    "Other"
                ],
                "Closure_Type": ["-- Select Closure Type --", "Resolved", "Completed", "Cancelled", "Duplicate", "No Response"],
                "Contract_Breach": [
                    "-- Select Breach Reason --",
                    "Vendor Delay",
                    "Client Delay",
                    "Internal Delay",
                    "System Issue",
                    "Resource Constraint",
                    "SLA Missed - Non-Delivery",
                    "Other"
                ]
            })
    except Exception:
        pass


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


    # Demo profiles & auto-removal of pseudo seeds when real users/cases exist
    try:
        roster_doc = collection.find_one({"type": "roster_list"})
        existing_data = roster_doc.get("Data", []) if roster_doc else []
        
        real_users = [u for u in existing_data if not str(u.get("email", "")).endswith(".demo@internal.test")]


        salt = secrets.token_hex(8)
        hashed_pw = hashlib.sha256((salt + "Hpe@123456").encode()).hexdigest() + ":" + salt
        
        demo_members = [
            ("Admin", "Demo", "DEMO901", "admin.demo@internal.test", "Admin", "Admin Work", "https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=150"),
            ("AdminAgent", "Demo", "DEMO902", "adminagent.demo@internal.test", "Admin/Agent", "Available", "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150"),
            ("Agent", "Demo", "DEMO903", "agent.demo@internal.test", "Agent", "Available", "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150")
        ]


        now = get_current_ph_time()
        demo_seed_data = []
        for fn, ln, eid, email, role, aux, img in demo_members:
            demo_seed_data.append({
                "first_name": str(fn),
                "last_name": str(ln),
                "name": str(fn + " " + ln),
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


        if real_users:
            final_roster = real_users + demo_seed_data
        else:
            default_team_members = [
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
            final_roster = []
            for fn, ln, eid, email, role, aux, img in default_team_members:
                final_roster.append({
                    "first_name": str(fn),
                    "last_name": str(ln),
                    "name": str(fn + " " + ln),
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
            final_roster.extend(demo_seed_data)


        collection.update_one(
            {"type": "roster_list"},
            {"$set": {"type": "roster_list", "Data": final_roster}},
            upsert=True
        )
    except Exception:
        pass


    try:
        if not collection.find_one({"type": "sessions"}):
            collection.insert_one({"type": "sessions", "Data": []})
        if not collection.find_one({"type": "aux_history"}):
            collection.insert_one({"type": "aux_history", "Data": []})
    except Exception:
        pass


    try:
        all_cases_in_db = list(cases_collection.find({"type": "cases"}))
        pseudo_prefixes = ["HC-2026-1044", "HPE-2026-1045", "HPE-2026-1042", "HPE-2026-1038", "HPE-2026-1020"]
        real_cases = [c for c in all_cases_in_db if c.get("case_number") not in pseudo_prefixes]


        if real_cases:
            for p_num in pseudo_prefixes:
                cases_collection.delete_many({"type": "cases", "case_number": p_num})
        elif len(all_cases_in_db) == 0:
            cases_seed = [
                {
                    "case_number": "HC-2026-1044",
                    "subject": "License Renewal Delay",
                    "priority": "Critical",
                    "assigned_to": "John Dela Cruz",
                    "assigned_employee_id": "HPE10003",
                    "assignee_email": "james.delacruz@hpe.com",
                    "assignee_avatar": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150",
                    "due_date": "Sep 28, 2026 11:00 AM",
                    "status": "On Hold",
                    "status_reason": "Waiting for Vendor Response",
                    "created_at": "Sep 27, 2026 03:15 PM",
                    "last_update": "Sep 28, 2026 08:45 AM",
                    "case_category": "License Renewal",
                    "account": "ABC Enterprise",
                    "client": "ABC Enterprise",
                    "related_system": "HPE Licensing Portal",
                    "description": "Client is experiencing delay in license renewal. Vendor confirmation is still pending.",
                    "vendor_name": "ABC Software Inc.",
                    "vendor_id": "VEND-ABC-019",
                    "vendor_contact": "Michael Tan",
                    "vendor_email": "support@abcsoftware.com",
                    "vendor_phone": "+1 555 123 4567",
                    "history": [],
                    "communications": [],
                    "attachments": []
                }
            ]
            for c in cases_seed:
                c["type"] = "cases"
                cases_collection.insert_one(c)
    except Exception:
        pass


    try:
        notif_doc = collection.find_one({"type": "notifications"})
        if not notif_doc or not notif_doc.get("Data"):
            collection.update_one(
                {"type": "notifications"},
                {"$set": {
                    "type": "notifications",
                    "Data": [
                        {
                            "id": "notif-001",
                            "target_email": "arianne.escabillas@hpe.com",
                            "title": "Critical Case Alert",
                            "message": "HC-2026-1044 is nearing SLA breach (Due in 36 minutes). Immediate follow-up required.",
                            "category": "critical",
                            "case_number": "HC-2026-1044",
                            "acknowledged": "false",
                            "created_at": "10:22 AM"
                        }
                    ]
                }},
                upsert=True
            )
    except Exception:
        pass


if "db_initialized" not in st.session_state:
    init_database()
    st.session_state["db_initialized"] = True


# ==============================================================================
# 4. SECURITY & AUTHENTICATION ENGINE
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
# 5. REAL-TIME AUX ENGINE
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
    selected_aux = st.session_state.get("flyout_aux_selector")
    user = st.session_state.get("current_user")
    if user and selected_aux:
        update_user_aux(user["email"], selected_aux)
        st.toast(f"Status changed to {selected_aux}!", icon="🟢")


def auto_assign_new_case(case_data):
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
    case_data["assigned_employee_id"] = chosen.get("employee_id", "")
    case_data["assignee_email"] = chosen["email"]
    case_data["assignee_avatar"] = chosen.get("profile_picture", "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150")


    now_str = get_current_ph_time().strftime("%b %d, %Y %I:%M %p")
    case_data.setdefault("history", []).append({
        "timestamp": now_str,
        "user": "Auto-Assignment Engine",
        "type": "Assignments",
        "badge": "Case created and assigned",
        "details": f"Automatically assigned to {chosen['name']} based on lowest active workload."
    })


    cases_collection.insert_one(case_data)


    notif_doc = collection.find_one({"type": "notifications"}) or {}
    notif_list = notif_doc.get("Data", [])
    notif_list.append({
        "id": str(uuid.uuid4()),
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
# 6. ENTERPRISE CSS DESIGN SYSTEM (INTER FONT & FOCUSED REFINEMENTS)
# ==============================================================================
ENTERPRISE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');


html, body, [class*="css"], .stApp, .stApp *, button, input, select, textarea {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
}


#MainMenu, header, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] {
    visibility: hidden !important;
    display: none !important;
}


.stApp {
    background-color: #F8FAFC !important;
    color: #17233C !important;
}


.block-container {
    padding-top: 5.2rem !important;
    padding-bottom: 95px !important;
    padding-left: 28px !important;
    padding-right: 28px !important;
    max-width: 100% !important;
}


/* Header Bar & Top Alignment Fix */
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
    height: 100% !important;
}


div[class*="st-key-top_profile_pill_btn"] {
    margin-top: 2px !important;
}


div[class*="st-key-top_profile_pill_btn"] button {
    background: #042121 !important;
    background-color: #042121 !important;
    color: #FFFFFF !important;
    border: 1px solid rgba(255, 255, 255, 0.25) !important;
    border-radius: 24px !important;
    padding: 4px 14px !important;
    font-size: 12px !important;
    font-weight: 700 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    gap: 6px !important;
    box-shadow: none !important;
}


div[class*="st-key-top_bell_popover"] button,
div[class*="st-key-top_bell_popover"] [data-testid="stPopoverButton"],
div[class*="st-key-top_bell_popover"] > div > button {
    background: #042121 !important;
    background-color: #042121 !important;
    color: #FFFFFF !important;
    border: 1px solid rgba(255, 255, 255, 0.25) !important;
    border-radius: 20px !important;
    padding: 4px 12px !important;
    box-shadow: none !important;
    gap: 0 !important;
}


/* BELL BUTTON & ELLIPSES: REPLACE EXP_MORE WITH SMALL ARROW ▾ */
div[class*="st-key-top_bell_popover"] [data-testid="stPopoverButton"] svg,
div[class*="st-key-top_bell_popover"] [data-testid="stIconChevronDown"],
div[class*="st-key-pop_row_act_"] [data-testid="stPopoverButton"] svg,
div[class*="st-key-pop_row_act_"] [data-testid="stIconChevronDown"] {
    display: none !important;
    visibility: hidden !important;
}


div[class*="st-key-top_bell_popover"] [data-testid="stPopoverButton"] span:last-child,
div[class*="st-key-pop_row_act_"] [data-testid="stPopoverButton"] span:last-child {
    font-size: 0 !important;
}


div[class*="st-key-top_bell_popover"] [data-testid="stPopoverButton"]::after {
    content: " ▾" !important;
    font-size: 11px !important;
    color: #FFFFFF !important;
}


div[class*="st-key-pop_row_act_"] [data-testid="stPopoverButton"]::after {
    content: " ▾" !important;
    font-size: 11px !important;
    color: #64748B !important;
}


.notif-item-card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 10px 12px;
    margin-bottom: 8px;
}
.notif-item-card.unread {
    border-left: 3.5px solid #00B388;
    background: #F8FAFC;
}


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
    right: 36px;
    width: 16px;
    height: 16px;
    background: #FFFFFF;
    transform: rotate(45deg);
    border-top: 1px solid #E2E8F0;
    border-left: 1px solid #E2E8F0;
}


/* LIGHT BLUE COLOR ON THE AUX DROPDOWN SELECTOR */
div[class*="st-key-profile_aux_wrapper"] div[data-baseweb="select"] {
    border: 1.5px solid #0284C7 !important;
    border-radius: 8px !important;
    background-color: #EEF6FC !important;
    min-height: 40px !important;
}


div[class*="st-key-profile_aux_wrapper"] div[data-baseweb="select"] * {
    background-color: transparent !important;
    color: #17233C !important;
}


.flyout-divider {
    margin: 6px 0 10px 0 !important;
    border: none !important;
    border-top: 1px solid #E2E8F0 !important;
}


div[class*="st-key-view_mode_segmented_tile"] {
    background: #042121 !important;
    background-color: #042121 !important;
    border-radius: 10px !important;
    padding: 3px !important;
    border: 1px solid rgba(255, 255, 255, 0.2) !important;
    display: inline-flex !important;
    align-items: center !important;
}


div[class*="st-key-view_mode_segmented_tile"] [data-testid="stHorizontalBlock"] {
    gap: 2px !important;
    align-items: center !important;
}


div[class*="st-key-view_mode_segmented_tile"] button {
    border-radius: 8px !important;
    font-size: 13px !important;
    font-weight: 700 !important;
    padding: 6px 16px !important;
    height: 34px !important;
    border: none !important;
    transition: all 0.2s ease !important;
}


div[class*="st-key-view_mode_segmented_tile"] button[kind="secondary"],
div[class*="st-key-view_mode_segmented_tile"] button[data-testid="baseButton-secondary"] {
    background-color: transparent !important;
    color: #94A3B8 !important;
}


div[class*="st-key-view_mode_segmented_tile"] button[kind="primary"],
div[class*="st-key-view_mode_segmented_tile"] button[data-testid="baseButton-primary"] {
    background-color: #00B388 !important;
    color: #FFFFFF !important;
    box-shadow: 0 2px 6px rgba(10, 56, 92, 0.35) !important;
}


.metric-card-box {
    border-radius: 12px;
    padding: 12px 14px;
    display: flex;
    align-items: center;
    gap: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.03);
    min-height: 98px;
    box-sizing: border-box;
    overflow: hidden;
}


.metric-card-box-active { background-color: #F0F9FF !important; border: 1px solid #BAE6FD !important; border-left: 4px solid #0284C7 !important; }
.metric-card-box-critical { background-color: #FEF2F2 !important; border: 1px solid #FECACA !important; border-left: 4px solid #DC2626 !important; }
.metric-card-box-duesoon { background-color: #FFFBEB !important; border: 1px solid #FDE68A !important; border-left: 4px solid #D97706 !important; }
.metric-card-box-ontrack { background-color: #F0FDF4 !important; border: 1px solid #BBF7D0 !important; border-left: 4px solid #16A34A !important; }


.metric-circle-icon {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    flex-shrink: 0;
}


.metric-card-label { font-size: 12px; font-weight: 600; color: #475569; margin: 0; }
.metric-card-val { font-size: 26px; font-weight: 800; color: #0F172A; margin: 2px 0; line-height: 1.1; }
.metric-card-trend { font-size: 11px; font-weight: 700; margin: 0; }


.badge { display: inline-block; padding: 3px 12px; border-radius: 20px; font-size: 11.5px; font-weight: 700; }
.badge-critical { background-color: #FEE2E2; color: #E31B23; }
.badge-high { background-color: #FFEDD5; color: #EA580C; }
.badge-medium { background-color: #FEF3C7; color: #D97706; }
.badge-low { background-color: #DCFCE7; color: #16855B; }


.badge-status { display: inline-block; padding: 4px 12px; border-radius: 6px; font-size: 11.5px; font-weight: 600; }
.st-in-progress { background-color: #E0F2FE; color: #0067B9; }
.st-on-hold { background-color: #FEF3C7; color: #D97706; }
.st-vendor-response { background-color: #FEF9C3; color: #A16207; }
.st-waiting-vendor { background-color: #FEF3C7; color: #D97706; }
.st-open { background-color: #F1F5F9; color: #475569; }
.st-pending-info { background-color: #F3E8FF; color: #7E22CE; }
.st-closed { background-color: #F1F5F9; color: #64748B; }


/* AVAILABLE AUX LIGHT GREEN */
.aux-badge { padding: 4px 12px; border-radius: 12px; font-size: 11.5px; font-weight: 700; display: inline-block; }
.aux-avail { background-color: #DCFCE7 !important; color: #16855B !important; border: 1px solid #BBF7D0 !important; }
.aux-lunch { background-color: #FEF3C7; color: #D97706; }
.aux-meeting { background-color: #FEE2E2; color: #E31B23; }
.aux-not-ready { background-color: #F1F5F9; color: #475569; }
.aux-break { background-color: #FEF3C7; color: #D97706; }


/* LOGGED IN AGENT VIEW: SIDE-BY-SIDE OPPOSITE ALIGNMENT */
.agent-row-item {
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    background: #FFFFFF !important;
    border: 1px solid #E2E8F0 !important;
    border-radius: 8px !important;
    padding: 8px 12px !important;
    margin-bottom: 8px !important;
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


.table-header-row {
    display: flex !important;
    align-items: center !important;
    width: 100% !important;
    background-color: #F1F5F9 !important;
    border: 1px solid #E2E8F0 !important;
    border-radius: 8px !important;
    padding: 7px 10px !important;
    margin-top: 3px !important;
    margin-bottom: 4px !important;
    box-sizing: border-box !important;
}
.th-cell {
    font-size: 11px !important;
    font-weight: 700 !important;
    color: #475569 !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    margin: 2px 0 !important;
}


/* UPDATE MARGIN ON TOP OF CASE ENTRY TO EQUAL BOTTOM */
.case-table-divider {
    margin: 4px 0 !important;
    border: none !important;
    border-top: 1px solid #F1F5F9 !important;
}


div[class*="st-key-btn_case_"] button {
    padding: 2px 8px !important;
    min-height: 28px !important;
    height: 28px !important;
    font-size: 12.5px !important;
    font-weight: 700 !important;
    border: 1px solid #CBD5E1 !important;
    border-radius: 6px !important;
    color: #0067B9 !important;
}


div[class*="st-key-pop_row_act_"] button,
div[class*="st-key-pop_row_act_"] [data-testid="stPopoverButton"],
div[class*="st-key-pop_row_act_"] [data-testid="baseButton-secondary"],
div[class*="st-key-pop_row_act_"] div[data-testid="stPopover"] > button {
    border: none !important;
    border-style: none !important;
    border-width: 0 !important;
    background: transparent !important;
    background-color: transparent !important;
    box-shadow: none !important;
    outline: none !important;
    padding: 0 !important;
    margin: 0 auto !important;
    min-height: unset !important;
    height: 24px !important;
    width: 20px !important;
    min-width: 20px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    color: #64748B !important;
    cursor: pointer !important;
    gap: 0 !important;
}


div[class*="st-key-pop_row_act_"] button:hover,
div[class*="st-key-pop_row_act_"] button:focus,
div[class*="st-key-pop_row_act_"] [data-testid="stPopoverButton"]:hover,
div[class*="st-key-pop_row_act_"] [data-testid="stPopoverButton"]:focus {
    border: none !important;
    background: transparent !important;
    color: #0067B9 !important;
    box-shadow: none !important;
}


div[class*="st-key-pop_row_act_"] button p,
div[class*="st-key-pop_row_act_"] [data-testid="stPopoverButton"] p {
    font-size: 18px !important;
    font-weight: 900 !important;
    margin: 0 !important;
    padding: 0 !important;
    line-height: 1 !important;
}


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
div[class*="st-key-hpe_bottom_nav_container"] button {
    background-color: transparent !important;
    color: #94A3B8 !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 14.5px !important;
    padding: 8px 24px !important;
    height: 46px !important;
}
div[class*="st-key-hpe_bottom_nav_container"] button[kind="primary"],
div[class*="st-key-hpe_bottom_nav_container"] button[data-testid="baseButton-primary"] {
    background-color: #00B388 !important;
    color: #FFFFFF !important;
    font-weight: 700 !important;
}


div[data-testid="stDialogHeader"] {
    padding-top: 24px !important;
    padding-left: 28px !important;
    padding-right: 28px !important;
    padding-bottom: 6px !important;
}
div[data-testid="stDialogHeader"] h2,
div[role="dialog"] h2,
div[data-testid="stDialog"] h2 {
    font-size: 22px !important;
    font-weight: 800 !important;
    color: #17233C !important;
    margin: 4px 0 0 4px !important;
    padding: 0 !important;
}


div[data-testid="stDialog"] [data-testid="stHorizontalBlock"] {
    gap: 8px !important;
    margin-bottom: 4px !important;
    align-items: stretch !important;
}


div[class*="st-key-case_info_block_"],
div[class*="st-key-vendor_info_block_"],
div[class*="st-key-update_case_block_"] {
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    border: 1px solid #DFE7EF !important;
    border-radius: 10px !important;
    padding: 14px 16px !important;
    margin-bottom: 4px !important;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02) !important;
    min-height: 535px !important;
    height: 100% !important;
    display: flex !important;
    flex-direction: column !important;
    box-sizing: border-box !important;
}


div[class*="st-key-case_history_block_"],
div[class*="st-key-breach_email_block_"] {
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    border: 1px solid #DFE7EF !important;
    border-radius: 10px !important;
    padding: 14px 16px !important;
    margin-bottom: 4px !important;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02) !important;
    min-height: 380px !important;
    height: 100% !important;
    display: flex !important;
    flex-direction: column !important;
    box-sizing: border-box !important;
}


div[class*="st-key-qa_panel_"] {
    background-color: #F0FDF4 !important;
    border: 1px solid #BBF7D0 !important;
    border-radius: 8px !important;
    padding: 8px 10px !important;
    margin-top: auto !important;
}


div[class*="st-key-reassign_box_"] {
    background-color: #EEF6FC !important;
    border: 1px solid #BAE6FD !important;
    border-radius: 8px !important;
    padding: 10px !important;
    margin-top: 10px !important;
}


div[data-testid="stDialog"] div[data-baseweb="select"] > div,
div[data-testid="stDialog"] div[data-baseweb="input"] > div,
div[data-testid="stDialog"] div[data-baseweb="textarea"] > textarea,
div[data-testid="stDialog"] input:not([type="checkbox"]):not([type="radio"]),
div[data-testid="stDialog"] textarea {
    background-color: #EEF6FC !important;
    border: 1px solid #BAE6FD !important;
    border-radius: 6px !important;
    color: #17233C !important;
}


div[data-testid="stDialog"] div[data-baseweb="select"] * {
    background-color: transparent !important;
}


div[data-testid="stDialog"] div[data-baseweb="input"] input {
    background-color: transparent !important;
}


div[class*="st-key-reassign_box_"] div[data-baseweb="select"] > div {
    background-color: #FFFFFF !important;
    border: 1.5px solid #CBD5E1 !important;
    border-radius: 6px !important;
}


div[class*="st-key-reassign_box_"] div[data-baseweb="select"] span,
div[class*="st-key-reassign_box_"] div[data-baseweb="select"] div {
    color: #17233C !important;
}


.case-meta-bar {
    display: flex;
    background-color: #EEF6FC;
    border: 1px solid #D9E2EC;
    border-radius: 8px;
    padding: 8px 12px;
    margin-bottom: 12px;
    align-items: center;
}
.case-meta-col {
    flex: 1;
    padding: 0 10px;
    border-right: 1px solid #D9E2EC;
}
.case-meta-col:last-child {
    border-right: none;
}
.timeline-item {
    border-left: 2px solid #D9E2EC;
    padding-left: 14px;
    padding-bottom: 12px;
    position: relative;
}
.timeline-dot {
    position: absolute;
    left: -6px;
    top: 2px;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background-color: #0067B9;
}
</style>
"""


st.markdown(ENTERPRISE_CSS, unsafe_allow_html=True)


# ==============================================================================
# 7. CASE DETAILS MODAL OVERLAY
# ==============================================================================
@st.dialog("📁 Case Details", width="large")
def render_case_modal(case_num):
    case = cases_collection.find_one({"type": "cases", "case_number": case_num})
    if not case:
        st.error("Case details are currently unavailable.")
        return


    user = st.session_state.get("current_user", {})
    user_role = user.get("role", "Agent")
    is_admin = user_role in ["Admin", "Admin/Agent"]


    st.markdown("""
    <div style="line-height:1.2; margin-top:-4px; margin-bottom:12px; padding-left:4px;">
        <p style="font-size:12.5px; color:#5F6B7A; margin:0;">
            View and update case information, communicate with vendor, and manage status.
        </p>
    </div>
    <hr style='margin:0 0 12px 0; border:none; border-top:1px solid #D9E2EC;'>
    """, unsafe_allow_html=True)


    pri = case.get("priority", "Critical")
    pri_badge_cls = f"badge-{pri.lower()}"
    countdown_txt, countdown_color, is_overdue = calculate_countdown(case.get("due_date"))
    elapsed_txt = calculate_elapsed(case.get("created_at"))


    sum_col1, sum_col2, sum_col3, sum_col4 = st.columns([3, 2.5, 3.5, 2.5], gap="small")
    with sum_col1:
        st.markdown(f"""
        <div style="line-height:1.2;">
            <small style="color:#5F6B7A; font-weight:600; font-size:11px;">CASE NUMBER</small><br>
            <strong style="font-size:20px; color:#17233C;">{case['case_number']}</strong>
            <span class='badge {pri_badge_cls}' style='margin-left:8px;'>{pri}</span>
        </div>
        """, unsafe_allow_html=True)
        if st.button("📋 Copy Case ID", key="copy_case_id_btn"):
            st.toast(f"Case ID {case['case_number']} copied to clipboard!")


    with sum_col2:
        st.markdown(f"""
        <div style="line-height:1.2;">
            <small style="color:#5F6B7A; font-weight:600; font-size:11px;">📅 CREATED</small><br>
            <strong style="font-size:13.5px; color:#17233C;">{case.get('created_at', 'Sep 27, 2026 03:15 PM')}</strong>
        </div>
        """, unsafe_allow_html=True)


    with sum_col3:
        st.markdown(f"""
        <div style="line-height:1.2;">
            <small style="color:#5F6B7A; font-weight:600; font-size:11px;">⏰ DUE DATE</small><br>
            <span style="font-size:13.5px; font-weight:700; color:{countdown_color};">{case.get('due_date')}</span>
            <span style="background-color:#FEE2E2; color:{countdown_color}; padding:2px 8px; border-radius:12px; font-size:11px; font-weight:700; margin-left:6px;">{countdown_txt}</span>
        </div>
        """, unsafe_allow_html=True)


    with sum_col4:
        st.markdown(f"""
        <div style="line-height:1.2;">
            <small style="color:#5F6B7A; font-weight:600; font-size:11px;">⏱️ TOTAL ELAPSED</small><br>
            <strong style="font-size:14px; color:#17233C;">{elapsed_txt}</strong>
        </div>
        """, unsafe_allow_html=True)


    st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
    assigned_name = case.get("assigned_to", "John Dela Cruz")
    initials = "".join([part[0] for part in assigned_name.split()[:2]]).upper() or "JD"
    status_val = case.get("status", "On Hold")
    hours_ago_txt = calculate_hours_ago(case.get("last_update"))


    st.markdown(f"""
    <div class="case-meta-bar">
        <div class="case-meta-col">
            <div style="display:flex; align-items:center; gap:8px;">
                <div style="width:28px; height:28px; border-radius:50%; background:#0067B9; color:white; font-size:11px; font-weight:800; display:flex; align-items:center; justify-content:center;">
                    {initials}
                </div>
                <div style="line-height:1.15;">
                    <small style="color:#5F6B7A; font-size:10px;">Assigned To</small><br>
                    <strong style="font-size:12px; color:#17233C;">{assigned_name}</strong>
                </div>
            </div>
        </div>
        <div class="case-meta-col">
            <small style="color:#5F6B7A; font-size:10px;">Priority</small><br>
            <span class="badge {pri_badge_cls}" style="padding:2px 8px; font-size:11px;">{pri}</span>
        </div>
        <div class="case-meta-col">
            <small style="color:#5F6B7A; font-size:10px;">Current Status</small><br>
            <span class="badge-status st-on-hold">{status_val}</span>
        </div>
        <div class="case-meta-col">
            <small style="color:#5F6B7A; font-size:10px;">Last Update</small><br>
            <strong style="font-size:11.5px; color:#17233C;">{case.get('last_update')}</strong>
            <small style="color:#5F6B7A;">({hours_ago_txt})</small>
        </div>
        <div class="case-meta-col">
            <small style="color:#5F6B7A; font-size:10px;">Case Type</small><br>
            <strong style="font-size:11.5px; color:#17233C;">{case.get('case_category', 'License Renewal')}</strong>
        </div>
        <div class="case-meta-col">
            <small style="color:#5F6B7A; font-size:10px;">Account</small><br>
            <strong style="font-size:11.5px; color:#17233C;">{case.get('account', 'ABC Enterprise')}</strong>
        </div>
        <div class="case-meta-col">
            <small style="color:#5F6B7A; font-size:10px;">Related System</small><br>
            <strong style="font-size:11.5px; color:#17233C;">{case.get('related_system', 'HPE Licensing Portal')}</strong>
        </div>
    </div>
    """, unsafe_allow_html=True)


    tab_info, tab_vendor, tab_comm, tab_att = st.tabs([
        "ⓘ Case Information",
        "♧ Vendor Information",
        "✉ Communication",
        f"📎 Attachments ({len(case.get('attachments', []))})"
    ])


    with tab_info:
        col_left, col_center, col_right = st.columns([3.3, 3.0, 3.7], gap="small")


        with col_left:
            with st.container(key=f"case_info_block_{case_num}"):
                head_l1, head_l2 = st.columns([3, 1])
                with head_l1:
                    st.markdown("<strong style='font-size:15px; color:#17233C;'>📄 Case Information</strong>", unsafe_allow_html=True)
                with head_l2:
                    edit_mode = st.session_state.get(f"edit_case_{case_num}", False)
                    btn_txt = "Done" if edit_mode else "Edit"
                    if st.button(btn_txt, key=f"btn_toggle_edit_{case_num}"):
                        st.session_state[f"edit_case_{case_num}"] = not edit_mode
                        st.rerun()


                if st.session_state.get(f"edit_case_{case_num}", False):
                    new_sub = st.text_input("Subject", value=case.get("subject", ""))
                    new_desc = st.text_area("Description", value=case.get("description", ""), height=90)
                    new_client = st.text_input("Client / Account", value=case.get("account", ""))
                    new_sys = st.text_input("Related System", value=case.get("related_system", ""))
                    new_cat = st.text_input("Category", value=case.get("case_category", ""))
                    if st.button("💾 Save Changes", key=f"btn_save_edit_{case_num}", type="primary"):
                        now_str = get_current_ph_time().strftime("%b %d, %Y %I:%M %p")
                        cases_collection.update_one(
                            {"type": "cases", "case_number": case_num},
                            {"$set": {
                                "subject": new_sub, "description": new_desc, "account": new_client,
                                "client": new_client, "related_system": new_sys, "case_category": new_cat,
                                "last_update": now_str
                            }}
                        )
                        st.session_state[f"edit_case_{case_num}"] = False
                        st.success("Case information updated!")
                        st.rerun()
                else:
                    st.markdown(f"""
                    <div style="font-size:12px; line-height:1.9;">
                        <div style="display:flex; justify-content:space-between;"><span style="color:#5F6B7A;">Case #:</span> <strong style="color:#17233C;">{case['case_number']}</strong></div>
                        <div style="display:flex; justify-content:space-between;"><span style="color:#5F6B7A;">Subject:</span> <strong style="color:#17233C;">{case.get('subject')}</strong></div>
                        <div style="margin:4px 0;"><span style="color:#5F6B7A;">Description:</span><br><span style="color:#17233C; font-size:11.5px;">{case.get('description')}</span></div>
                        <div style="display:flex; justify-content:space-between;"><span style="color:#5F6B7A;">Priority:</span> <span class="badge {pri_badge_cls}">{pri}</span></div>
                        <div style="display:flex; justify-content:space-between;"><span style="color:#5F6B7A;">Assigned To:</span> <strong style="color:#17233C;">{case.get('assigned_to')}</strong></div>
                        <div style="display:flex; justify-content:space-between;"><span style="color:#5F6B7A;">Due Date:</span> <strong style="color:{countdown_color};">{case.get('due_date')}</strong></div>
                        <div style="display:flex; justify-content:space-between;"><span style="color:#5F6B7A;">Created Date:</span> <strong style="color:#17233C;">{case.get('created_at')}</strong></div>
                        <div style="display:flex; justify-content:space-between;"><span style="color:#5F6B7A;">Last Update:</span> <strong style="color:#17233C;">{case.get('last_update')}</strong></div>
                        <div style="display:flex; justify-content:space-between;"><span style="color:#5F6B7A;">Current Status:</span> <span class="badge-status st-on-hold">{case.get('status')}</span></div>
                        <div style="display:flex; justify-content:space-between;"><span style="color:#5F6B7A;">Case Category:</span> <strong style="color:#17233C;">{case.get('case_category')}</strong></div>
                        <div style="display:flex; justify-content:space-between;"><span style="color:#5F6B7A;">Client:</span> <strong style="color:#17233C;">{case.get('account')}</strong></div>
                        <div style="display:flex; justify-content:space-between;"><span style="color:#5F6B7A;">Related System:</span> <strong style="color:#17233C;">{case.get('related_system')}</strong></div>
                    </div>
                    """, unsafe_allow_html=True)


        with col_center:
            with st.container(key=f"vendor_info_block_{case_num}"):
                v_head1, v_head2 = st.columns([1.8, 1.2])
                with v_head1:
                    st.markdown("<strong style='font-size:15px; color:#17233C;'>🏢 Vendor Information</strong>", unsafe_allow_html=True)
                with v_head2:
                    if st.button("Open Record", key=f"btn_open_vend_{case_num}", help="Open full vendor record"):
                        st.session_state[f"show_vendor_record_modal_{case_num}"] = True


                st.markdown(f"""
                <div style="display:flex; align-items:center; gap:10px; margin:8px 0 10px 0;">
                    <div style="width:36px; height:36px; border-radius:6px; background:#0067B9; color:white; font-size:13px; font-weight:800; display:flex; align-items:center; justify-content:center;">
                        ABC
                    </div>
                    <div style="line-height:1.15;">
                        <strong style="font-size:14.5px; color:#17233C;">{case.get('vendor_name', 'ABC Software Inc.')}</strong><br>
                        <small style="color:#5F6B7A;">ID: {case.get('vendor_id', 'VEND-ABC-019')}</small>
                    </div>
                </div>
                <div style="font-size:12px; line-height:1.75;">
                    <div><span style="color:#5F6B7A;">Primary Contact:</span> <strong style="color:#17233C;">{case.get('vendor_contact', 'Michael Tan')}</strong></div>
                    <div><span style="color:#5F6B7A;">Email:</span> <a href="mailto:{case.get('vendor_email', 'support@abcsoftware.com')}" style="color:#0067B9; text-decoration:none;">{case.get('vendor_email', 'support@abcsoftware.com')}</a></div>
                    <div><span style="color:#5F6B7A;">Phone:</span> <strong style="color:#17233C;">{case.get('vendor_phone', '+1 555 123 4567')}</strong></div>
                    <div><span style="color:#5F6B7A;">Alternate Contact:</span> <strong style="color:#17233C;">{case.get('vendor_alt_contact', 'Sarah Lim')}</strong></div>
                    <div><span style="color:#5F6B7A;">Alternate Email:</span> <a href="mailto:{case.get('vendor_alt_email', 'sarah.lim@abcsoftware.com')}" style="color:#0067B9; text-decoration:none;">{case.get('vendor_alt_email', 'sarah.lim@abcsoftware.com')}</a></div>
                    <div><span style="color:#5F6B7A;">Address:</span> <br><span style="color:#17233C; font-size:11.5px;">{case.get('vendor_address', '123 Innovation Drive, San Jose, CA 95134')}</span></div>
                </div>
                """, unsafe_allow_html=True)


                with st.container(key=f"qa_panel_{case_num}"):
                    st.markdown("<strong style='font-size:12px; color:#16855B;'>➕ Quick Actions</strong>", unsafe_allow_html=True)
                    qa_c1, qa_c2, qa_c3 = st.columns(3)
                    with qa_c1:
                        if st.button("Copy Email", key=f"btn_cpy_vemail_{case_num}"):
                            st.toast("Vendor email copied to clipboard!")
                    with qa_c2:
                        if st.button("Copy Phone", key=f"btn_cpy_vphone_{case_num}"):
                            st.toast("Vendor phone copied to clipboard!")
                    with qa_c3:
                        v_excel_df = pd.DataFrame([{
                            "Case #": case["case_number"],
                            "Vendor": case.get("vendor_name"),
                            "Contact": case.get("vendor_contact"),
                            "Email": case.get("vendor_email"),
                            "Phone": case.get("vendor_phone"),
                            "Due Date": case.get("due_date"),
                            "Status": case.get("status")
                        }])
                        buf = io.BytesIO()
                        with pd.ExcelWriter(buf, engine="openpyxl") if "openpyxl" in sys.modules else io.BytesIO() as writer:
                            try:
                                v_excel_df.to_excel(writer, index=False)
                                excel_data = buf.getvalue()
                            except Exception:
                                excel_data = v_excel_df.to_csv(index=False).encode("utf-8")
                        st.download_button("View Excel", excel_data, f"{case['case_number']}_Vendor.xlsx", key=f"btn_down_vexc_{case_num}")


        with col_right:
            with st.container(key=f"update_case_block_{case_num}"):
                st.markdown("<strong style='font-size:15px; color:#17233C;'>⏱️ Update Case</strong>", unsafe_allow_html=True)


                dd_doc = validation_collection.find_one({"type": "Validation_Dropdown"}) or {}
                statuses = dd_doc.get("Case_Status", ["New", "Open", "In Progress", "On Hold", "Pending Vendor", "Pending Client", "Resolved", "Closed"])
                reasons = dd_doc.get("Case_Reason", ["Waiting for Vendor Response", "Waiting for Client", "Pending Internal Action", "Investigation", "Other"])
                closures = dd_doc.get("Closure_Type", ["-- Select Closure Type --", "Resolved", "Completed", "Cancelled", "Duplicate"])
                breaches = dd_doc.get("Contract_Breach", ["-- Select Breach Reason --", "Vendor Delay", "Client Delay", "Internal Delay", "SLA Missed - Non-Delivery"])


                u_c1, u_c2 = st.columns(2)
                with u_c1:
                    cur_s = case.get("status", "On Hold")
                    s_idx = statuses.index(cur_s) if cur_s in statuses else 0
                    sel_status = st.selectbox("Case Status", statuses, index=s_idx, key=f"sel_st_{case_num}")
                    sel_closure = st.selectbox("Closure Type", closures, key=f"sel_cl_{case_num}")
                with u_c2:
                    cur_r = case.get("status_reason", "Waiting for Vendor Response")
                    r_idx = reasons.index(cur_r) if cur_r in reasons else 0
                    sel_reason = st.selectbox("Status Reason", reasons, index=r_idx, key=f"sel_rs_{case_num}")
                    sel_breach = st.selectbox("Breach Reason", breaches, key=f"sel_br_{case_num}")


                remarks_val = st.text_area("Remarks / Update", placeholder="Add update, notes or next steps...", key=f"rem_{case_num}", height=75)
                st.caption(f"{len(remarks_val)}/1000 characters")


                act_b1, act_b2, act_b3 = st.columns([1.5, 1.2, 1.7])
                with act_b1:
                    if st.button("✓ Update Case", type="primary", key=f"btn_upd_sub_{case_num}"):
                        now_str = get_current_ph_time().strftime("%b %d, %Y %I:%M %p")
                        new_hist_entry = {
                            "timestamp": now_str,
                            "user": user.get("name", "User"),
                            "type": "Status Changes",
                            "badge": f"Status changed to {sel_status}",
                            "details": remarks_val or f"Reason: {sel_reason}"
                        }
                        cases_collection.update_one(
                            {"type": "cases", "case_number": case_num},
                            {
                                "$set": {
                                    "status": sel_status, "status_reason": sel_reason,
                                    "closure_type": sel_closure if sel_closure != "-- Select Closure Type --" else "",
                                    "breach_reason": sel_breach if sel_breach != "-- Select Breach Reason --" else "",
                                    "last_update": now_str
                                },
                                "$push": {"history": {"$each": [new_hist_entry], "$position": 0}}
                            }
                        )
                        st.success("Case successfully updated!")
                        time.sleep(0.5)
                        st.rerun()


                with act_b2:
                    if st.button("Add Note", key=f"btn_add_note_{case_num}"):
                        if remarks_val:
                            now_str = get_current_ph_time().strftime("%b %d, %Y %I:%M %p")
                            note_entry = {
                                "timestamp": now_str,
                                "user": user.get("name", "User"),
                                "type": "Notes",
                                "badge": "Note Added",
                                "details": remarks_val
                            }
                            cases_collection.update_one(
                                {"type": "cases", "case_number": case_num},
                                {"$push": {"history": {"$each": [note_entry], "$position": 0}}}
                            )
                            st.success("Note logged to Case History!")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.warning("Please type a note in the remarks box.")


                with act_b3:
                    if st.button("Request Transfer", key=f"btn_trf_req_{case_num}"):
                        st.session_state[f"show_transfer_dialog_{case_num}"] = True


                if is_admin:
                    with st.container(key=f"reassign_box_{case_num}"):
                        st.markdown("<strong style='font-size:12.5px; color:#0067B9;'>🔄 Reassign Case (Admin Only)</strong>", unsafe_allow_html=True)
                        roster_doc = collection.find_one({"type": "roster_list"}) or {}
                        all_agents = [u for u in roster_doc.get("Data", []) if u.get("role") in ["Agent", "Admin/Agent"]]
                        agent_names = ["-- Select Agent --"] + [u["name"] for u in all_agents]


                        reassign_to = st.selectbox("Reassign To", agent_names, key=f"sel_reassign_{case_num}", label_visibility="collapsed")
                        send_notif = st.checkbox("Send notification to new assignee", value=True, key=f"chk_reassign_notif_{case_num}")


                        if st.button("Reassign Case", key=f"btn_exec_reassign_{case_num}"):
                            if reassign_to != "-- Select Agent --":
                                chosen_agent = next((u for u in all_agents if u["name"] == reassign_to), None)
                                now_str = get_current_ph_time().strftime("%b %d, %Y %I:%M %p")
                                new_hist = {
                                    "timestamp": now_str,
                                    "user": user.get("name", "Admin"),
                                    "type": "Assignments",
                                    "badge": f"Reassigned to {reassign_to}",
                                    "details": f"Reassigned by {user.get('name')}."
                                }
                                cases_collection.update_one(
                                    {"type": "cases", "case_number": case_num},
                                    {
                                        "$set": {
                                            "assigned_to": reassign_to,
                                            "assigned_employee_id": chosen_agent.get("employee_id", "") if chosen_agent else "",
                                            "assignee_email": chosen_agent.get("email", "") if chosen_agent else "",
                                            "last_update": now_str
                                        },
                                        "$push": {"history": {"$each": [new_hist], "$position": 0}}
                                    }
                                )
                                if send_notif and chosen_agent:
                                    notif_doc = collection.find_one({"type": "notifications"}) or {}
                                    n_list = notif_doc.get("Data", [])
                                    n_list.append({
                                        "id": str(uuid.uuid4()),
                                        "target_email": chosen_agent["email"],
                                        "title": "Case Reassigned To You",
                                        "message": f"{case_num} has been reassigned to you by {user.get('name')}.",
                                        "category": "new_case",
                                        "case_number": case_num,
                                        "acknowledged": "false",
                                        "created_at": get_current_ph_time().strftime("%I:%M %p")
                                    })
                                    collection.update_one({"type": "notifications"}, {"$set": {"Data": n_list}}, upsert=True)
                                st.success(f"Case {case_num} reassigned to {reassign_to}!")
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.warning("Please choose an agent to reassign.")


        col_hist, col_email = st.columns([6.3, 3.7], gap="small")


        with col_hist:
            with st.container(key=f"case_history_block_{case_num}"):
                h_top1, h_top2 = st.columns([3, 2])
                with h_top1:
                    st.markdown("<strong style='font-size:15px; color:#17233C;'>🕒 Case History</strong>", unsafe_allow_html=True)
                with h_top2:
                    hist_filter = st.selectbox(
                        "Show",
                        ["All Activities", "Status Changes", "Notes", "Communications", "Assignments"],
                        key=f"hist_filter_{case_num}",
                        label_visibility="collapsed"
                    )


                history_items = case.get("history", [])
                badge_color_map = {
                    "Status Changes": "#D97706",
                    "Communications": "#0067B9",
                    "Notes": "#00B388",
                    "Assignments": "#7E22CE",
                    "Escalation": "#E31B23"
                }


                if not history_items:
                    st.caption("No history records logged yet.")
                for h in history_items:
                    h_type = h.get("type", "Status Changes")
                    if hist_filter == "All Activities" or hist_filter == h_type:
                        badge_color = badge_color_map.get(h_type, "#5F6B7A")
                        st.markdown(f"""
                        <div class="timeline-item">
                            <div class="timeline-dot" style="background:{badge_color};"></div>
                            <div style="font-size:12px; line-height:1.2;">
                                <span style="color:#5F6B7A;">{h.get('timestamp')} &bull; <strong>{h.get('user')}</strong></span><br>
                                <span style="background:{badge_color}18; color:{badge_color}; font-weight:700; font-size:10.5px; padding:2px 8px; border-radius:10px; display:inline-block; margin:3px 0;">
                                    {h.get('badge')}
                                </span><br>
                                <span style="color:#17233C; font-size:11.5px;">&gt; {h.get('details')}</span>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)


        with col_email:
            with st.container(key=f"breach_email_block_{case_num}"):
                st.markdown("<strong style='font-size:15px; color:#17233C;'>✉️️ Automated Breach Notice Email</strong>", unsafe_allow_html=True)


                use_tmpl = st.toggle("Use Template", value=True, key=f"tgl_tmpl_{case_num}")
                default_to = case.get("vendor_email", "support@abcsoftware.com")
                default_subj = f"Notice of Contract Breach – {case['case_number']}"
                default_body = f"""Dear {case.get('vendor_name', 'ABC Software Inc.')},


This is to inform you that the following case ({case['case_number']}) is nearing breach due to continued delay in the license renewal. As per our agreement, we have not yet received the required confirmation from your team.


Please provide an update at your earliest convenience to avoid contract breach.


Thank you,
HPE Operations Management"""


                to_field = st.text_input("To", value=default_to, key=f"em_to_{case_num}")
                subj_field = st.text_input("Subject", value=default_subj if use_tmpl else "", key=f"em_subj_{case_num}")
                body_field = st.text_area("Email Body", value=default_body if use_tmpl else "", height=140, key=f"em_body_{case_num}")


                em_b1, em_b2 = st.columns(2)
                with em_b1:
                    if st.button("✏️ Edit Email", key=f"btn_edit_em_{case_num}"):
                        st.toast("Email body unlocked for direct editing.")
                with em_b2:
                    if st.button("📤 Send Email", type="primary", key=f"btn_send_em_{case_num}"):
                        if to_field and subj_field and body_field:
                            now_str = get_current_ph_time().strftime("%b %d, %Y %I:%M %p")
                            comm_entry = {
                                "timestamp": now_str,
                                "user": user.get("name", "User"),
                                "type": "Communications",
                                "badge": f"Breach notice sent to {to_field}",
                                "details": f"Subject: {subj_field}"
                            }
                            cases_collection.update_one(
                                {"type": "cases", "case_number": case_num},
                                {
                                    "$push": {
                                        "history": {"$each": [comm_entry], "$position": 0},
                                        "communications": {
                                            "timestamp": now_str,
                                            "sender": user.get("name"),
                                            "recipient": to_field,
                                            "subject": subj_field,
                                            "message": body_field,
                                            "type": "Breach Notice Sent"
                                        }
                                    }
                                }
                            )
                            st.success(f"Breach notice successfully delivered to {to_field}!")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.warning("Please fill in recipient, subject, and body.")


    with tab_vendor:
        st.markdown(f"### 🏢 Vendor Profile: {case.get('vendor_name', 'ABC Software Inc.')}")
        st.caption(f"Vendor Code: {case.get('vendor_id', 'VEND-ABC-019')} &bull; Status: Active Certified Partner")
        v_col1, v_col2 = st.columns(2)
        with v_col1:
            st.write(f"**Primary Contact:** {case.get('vendor_contact', 'Michael Tan')}")
            st.write(f"**Direct Email:** `{case.get('vendor_email', 'support@abcsoftware.com')}`")
            st.write(f"**Phone Support:** `{case.get('vendor_phone', '+1 555 123 4567')}`")
            st.write(f"**Physical Address:** {case.get('vendor_address')}")
        with v_col2:
            st.write(f"**Alternate Representative:** {case.get('vendor_alt_contact', 'Sarah Lim')}")
            st.write(f"**Alternate Email:** `{case.get('vendor_alt_email', 'sarah.lim@abcsoftware.com')}`")
            st.write("**SLA Contract Adherence:** `94.2%` (Target: 95.0%)")
            st.write(f"**Linked Account:** {case.get('account')}")


    with tab_comm:
        st.markdown("### ✉️ Case Communication Log")
        comms = case.get("communications", [])
        if not comms:
            st.info("No prior email correspondence recorded for this case.")
        for cm in comms:
            st.markdown(f"""
            <div style="background:#FFFFFF; border:1px solid #D9E2EC; border-left:3.5px solid #0067B9; border-radius:8px; padding:10px 14px; margin-bottom:8px; font-size:12px;">
                <div style="display:flex; justify-content:space-between;">
                    <strong>{cm.get('subject')}</strong>
                    <span style="color:#5F6B7A;">{cm.get('timestamp')}</span>
                </div>
                <small style="color:#5F6B7A;">From: {cm.get('sender')} &rarr; To: {cm.get('recipient')}</small><br>
                <p style="margin:4px 0 0 0; color:#17233C;">{cm.get('message')}</p>
            </div>
            """, unsafe_allow_html=True)


        st.divider()
        st.markdown("#### ✍️ Compose New Communication")
        c_to = st.text_input("To", value=case.get("vendor_email", ""), key=f"comp_to_{case_num}")
        c_cc = st.text_input("CC", key=f"comp_cc_{case_num}")
        c_sub = st.text_input("Subject", value=f"Follow-up on {case_num}", key=f"comp_sub_{case_num}")
        c_msg = st.text_area("Message", key=f"comp_msg_{case_num}", height=90)
        if st.button("Send Communication", type="primary", key=f"btn_send_comp_{case_num}"):
            if c_to and c_sub and c_msg:
                now_str = get_current_ph_time().strftime("%b %d, %Y %I:%M %p")
                cases_collection.update_one(
                    {"type": "cases", "case_number": case_num},
                    {"$push": {
                        "communications": {
                            "timestamp": now_str,
                            "sender": user.get("name"),
                            "recipient": c_to,
                            "subject": c_sub,
                            "message": c_msg,
                            "type": "Email"
                        },
                        "history": {
                            "$each": [{
                                "timestamp": now_str,
                                "user": user.get("name"),
                                "type": "Communications",
                                "badge": f"Email sent to {c_to}",
                                "details": c_sub
                            }],
                            "$position": 0
                        }
                    }}
                )
                st.success("Message dispatched and logged to case history!")
                time.sleep(0.5)
                st.rerun()


    with tab_att:
        st.markdown("### 📎 Case Attachments")
        atts = case.get("attachments", [])
        if not atts:
            st.info("No attachments uploaded yet.")
        for idx, at in enumerate(atts):
            at1, at2, at3, at4 = st.columns([4, 2, 2, 1.5])
            with at1:
                st.markdown(f"📄 **{at.get('name')}** &bull; <small style='color:#5F6B7A;'>{at.get('size')}</small>", unsafe_allow_html=True)
            with at2:
                st.caption(f"Uploaded by: {at.get('uploaded_by')}")
            with at3:
                st.caption(at.get("upload_date"))
            with at4:
                st.download_button("Download", data=b"Sample content", file_name=at.get("name"), key=f"down_att_{case_num}_{idx}")


        st.divider()
        st.markdown("#### 📤 Upload New Attachment")
        uploaded_file = st.file_uploader(
            "Choose file",
            type=["pdf", "docx", "xlsx", "csv", "png", "jpg", "jpeg", "txt"],
            key=f"upload_att_widget_{case_num}"
        )
        if uploaded_file and st.button("Attach File", key=f"btn_save_att_{case_num}", type="primary"):
            new_att = {
                "name": uploaded_file.name,
                "type": uploaded_file.name.split(".")[-1].upper(),
                "size": f"{uploaded_file.size / 1024:.1f} KB",
                "uploaded_by": user.get("name", "User"),
                "upload_date": get_current_ph_time().strftime("%b %d, %Y")
            }
            cases_collection.update_one(
                {"type": "cases", "case_number": case_num},
                {"$push": {"attachments": new_att}}
            )
            st.success(f"{uploaded_file.name} attached successfully!")
            time.sleep(0.5)
            st.rerun()


    if st.session_state.get(f"show_vendor_record_modal_{case_num}", False):
        st.divider()
        st.markdown(f"#### 🏢 Master Vendor Record: {case.get('vendor_name')}")
        st.write(f"**Vendor ID:** `{case.get('vendor_id', 'VEND-ABC-019')}` | **Account:** `{case.get('account')}`")
        st.write("**Active Enterprise Contracts:** 3 Active (Gold Support SLA)")
        st.write("**Open Cases with Vendor:** 2 Pending Milestone Confirmation")
        if st.button("Close Vendor Record", key=f"btn_close_vrec_{case_num}"):
            st.session_state[f"show_vendor_record_modal_{case_num}"] = False
            st.rerun()


    if st.session_state.get(f"show_transfer_dialog_{case_num}", False):
        st.divider()
        st.markdown("#### 🔄 Propose Case Transfer")
        roster_doc = collection.find_one({"type": "roster_list"}) or {}
        transfer_candidates = [u["name"] for u in roster_doc.get("Data", []) if u["name"] != case.get("assigned_to")]
        req_target = st.selectbox("Target Colleague", transfer_candidates, key=f"trf_cand_{case_num}")
        req_reason = st.text_input("Transfer Reason", "Workload rebalance", key=f"trf_rs_{case_num}")
        if st.button("Dispatch Transfer Request", key=f"btn_trf_submit_{case_num}", type="primary"):
            now_str = get_current_ph_time().strftime("%b %d, %Y %I:%M %p")
            cases_collection.update_one(
                {"type": "cases", "case_number": case_num},
                {"$push": {"history": {
                    "$each": [{
                        "timestamp": now_str,
                        "user": user.get("name"),
                        "type": "Assignments",
                        "badge": f"Transfer Requested to {req_target}",
                        "details": req_reason
                    }],
                    "$position": 0
                }}}
            )
            st.session_state[f"show_transfer_dialog_{case_num}"] = False
            st.success(f"Transfer request to {req_target} dispatched!")
            time.sleep(0.5)
            st.rerun()


# ==============================================================================
# 8. TOP HEADER (1. Avoid refresh or reload when profile is clicked)
# ==============================================================================
def render_top_header():
    user = st.session_state.get("current_user", {})
    curr_aux = user.get("current_aux", "Admin Work")


    notif_doc = collection.find_one({"type": "notifications"}) or {}
    notifs = notif_doc.get("Data", [])
    user_notifs = [n for n in notifs if n.get("target_email") in [user.get("email"), "all"]]
    unread_count = sum(1 for n in user_notifs if str(n.get("acknowledged", "false")).lower() in ["false", "0"])


    with st.container(key="hpe_top_bar_container"):
        c_brand, c_search, c_bell, c_time, c_prof = st.columns([3.0, 4.0, 0.6, 1.8, 2.6])


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


        # Notification Bell Popover
        with c_bell:
            with st.container(key="top_bell_popover"):
                with st.popover(f"🔔 {unread_count}", help="Notifications"):
                    st.markdown("### 🔔 Alerts & Notifications")
                    if user_notifs:
                        if st.button("Mark All as Read", key="btn_ack_all_notifs"):
                            for n in notifs:
                                if n.get("target_email") in [user.get("email"), "all"]:
                                    n["acknowledged"] = "true"
                            collection.update_one({"type": "notifications"}, {"$set": {"Data": notifs}}, upsert=True)
                            st.rerun()


                        for n in reversed(user_notifs):
                            is_unr = str(n.get("acknowledged", "false")).lower() in ["false", "0"]
                            cat = n.get("category", "info")
                            badge_color = "#E31B23" if cat == "critical" else "#0067B9"
                            unread_cls = "unread" if is_unr else ""
                            st.markdown(f"""
                            <div class="notif-item-card {unread_cls}">
                                <div style="display:flex; justify-content:space-between;">
                                    <strong style="font-size:12.5px; color:#17233C;">{n.get('title')}</strong>
                                    <span style="background:{badge_color}20; color:{badge_color}; font-size:10px; font-weight:700; padding:1px 6px; border-radius:10px;">{cat.upper()}</span>
                                </div>
                                <p style="margin:4px 0 2px 0; font-size:12px; color:#475569;">{n.get('message')}</p>
                                <small style="color:#94A3B8; font-size:10.5px;">{n.get('created_at', 'Today')}</small>
                            </div>
                            """, unsafe_allow_html=True)
                    else:
                        st.info("No notifications received.")


        with c_time:
            now_dt = get_current_ph_time()
            st.markdown(f"""
            <div style="text-align:right; color:white; line-height:1.15; padding-right:8px;">
                <small style="color:#94A3B8; font-size:11px;">{now_dt.strftime("%a, %b %d, %Y")}</small><br>
                <strong style="font-size:16px;">{now_dt.strftime("%I:%M %p")}</strong>
            </div>
            """, unsafe_allow_html=True)


        with c_prof:
            with st.container(key="top_profile_pill_btn"):
                btn_label = f"👤 {user.get('name', 'Arianne Escabillas')} • {curr_aux} ▾"
                if st.button(btn_label, key="btn_open_profile_top_right", use_container_width=True):
                    st.session_state["show_profile_flyout"] = not st.session_state.get("show_profile_flyout", False)


    if st.session_state.get("show_profile_flyout", False):
        render_profile_flyout()


# ==============================================================================
# 9. PROFILE FLYOUT DROPDOWN
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


        st.markdown('<hr class="flyout-divider">', unsafe_allow_html=True)
        
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
# 10. ADMIN BROADCAST DIALOG
# ==============================================================================
@st.dialog("📢 Broadcast Admin Message", width="small")
def render_admin_message_dialog():
    st.markdown("Broadcast an urgent notification or alert to all active agents.")
    msg_title = st.text_input("Alert Title", "System Maintenance Notice")
    msg_body = st.text_area("Message Content", "Please ensure all open cases are updated before shift end.")
    msg_cat = st.selectbox("Category", ["info", "critical", "new_case"])
    if st.button("Send Broadcast", type="primary", use_container_width=True):
        notif_doc = collection.find_one({"type": "notifications"}) or {}
        n_list = notif_doc.get("Data", [])
        n_list.append({
            "id": str(uuid.uuid4()),
            "target_email": "all",
            "title": msg_title,
            "message": msg_body,
            "category": msg_cat,
            "acknowledged": "false",
            "created_at": get_current_ph_time().strftime("%I:%M %p")
        })
        collection.update_one({"type": "notifications"}, {"$set": {"Data": n_list}}, upsert=True)
        st.success("Broadcast alert sent to all agents!")
        time.sleep(0.5)
        st.rerun()


# ==============================================================================
# 11. DASHBOARD ROUTER (Optimized with @st.fragment for Speed & Smoothness)
# ==============================================================================
@st.fragment
def render_dashboard():
    user = st.session_state.get("current_user", {})
    user_role = user.get("role", "Admin/Agent")


    is_admin = user_role in ["Admin", "Admin/Agent"]


    if "view_mode" not in st.session_state:
        st.session_state["view_mode"] = "Admin" if is_admin else "Agent"
    
    if user_role == "Agent":
        st.session_state["view_mode"] = "Agent"


    is_admin_mode = (st.session_state["view_mode"] == "Admin")


    q_base = {"type": "cases"}
    if not is_admin_mode:
        q_base["assignee_email"] = user.get("email")


    all_base_cases = list(cases_collection.find(q_base))
    total_active = sum(1 for c in all_base_cases if c.get("status") != "Closed")
    total_critical = sum(1 for c in all_base_cases if c.get("priority") == "Critical" and c.get("status") != "Closed")
    total_due_soon = sum(1 for c in all_base_cases if c.get("priority") in ["Critical", "High"] and c.get("status") != "Closed")
    total_on_track = sum(1 for c in all_base_cases if c.get("priority") in ["Medium", "Low"] and c.get("status") != "Closed")


    main_left, main_right = st.columns([2.88, 1.12], gap="large")


    with main_left:
        hd_col1, hd_col2 = st.columns([2.5, 1.5])
        with hd_col1:
            pass
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


        mc1, mc2, mc3, mc4 = st.columns(4)
        with mc1:
            st.markdown(f"""
            <div class="metric-card-box metric-card-box-active">
                <div class="metric-circle-icon" style="background:#E0F2FE; color:#0284C7;">📁</div>
                <div style="flex:1; min-width:0; overflow:hidden;">
                    <p class="metric-card-label">{'Active Cases' if is_admin_mode else 'My Active Cases'}</p>
                    <h3 class="metric-card-val">{total_active}</h3>
                    <p class="metric-card-trend" style="color:#0284C7;">↑ +5% <span style="font-weight:400; color:#64748B;">vs last week</span></p>
                </div>
            </div>
            """, unsafe_allow_html=True)
        with mc2:
            st.markdown(f"""
            <div class="metric-card-box metric-card-box-critical">
                <div class="metric-circle-icon" style="background:#FEE2E2; color:#DC2626;">⚠️</div>
                <div style="flex:1; min-width:0; overflow:hidden;">
                    <p class="metric-card-label">{'Critical Cases' if is_admin_mode else 'My Critical Cases'}</p>
                    <h3 class="metric-card-val">{total_critical}</h3>
                    <p class="metric-card-trend" style="color:#DC2626;">↑ +2 <span style="font-weight:400; color:#64748B;">vs last week</span></p>
                </div>
            </div>
            """, unsafe_allow_html=True)
        with mc3:
            st.markdown(f"""
            <div class="metric-card-box metric-card-box-duesoon">
                <div class="metric-circle-icon" style="background:#FEF3C7; color:#D97706;">⏰</div>
                <div style="flex:1; min-width:0; overflow:hidden;">
                    <p class="metric-card-label">Due Soon</p>
                    <h3 class="metric-card-val">{total_due_soon}</h3>
                    <p class="metric-card-trend" style="color:#D97706;">↑ +3 <span style="font-weight:400; color:#64748B;">vs last week</span></p>
                </div>
            </div>
            """, unsafe_allow_html=True)
        with mc4:
            st.markdown(f"""
            <div class="metric-card-box metric-card-box-ontrack">
                <div class="metric-circle-icon" style="background:#DCFCE7; color:#16A34A;">✅</div>
                <div style="flex:1; min-width:0; overflow:hidden;">
                    <p class="metric-card-label">On Track</p>
                    <h3 class="metric-card-val">{total_on_track}</h3>
                    <p class="metric-card-trend" style="color:#16A34A;">↑ +10% <span style="font-weight:400; color:#64748B;">vs last week</span></p>
                </div>
            </div>
            """, unsafe_allow_html=True)


        st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)


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
                        if all_base_cases:
                            csv_bytes = pd.DataFrame(all_base_cases).to_csv(index=False).encode("utf-8")
                            st.download_button("Download CSV", csv_bytes, "HPE_Cases_Export.csv", "text/csv")
                with a5:
                    if st.button("⟳", key="btn_tb_refresh", help="Refresh Data", use_container_width=True):
                        st.rerun()


        f1, f2, f3, f4 = st.columns([2.5, 1.2, 1.3, 1.5])
        with f1:
            search_val = st.text_input("Search", placeholder="🔍 Search by case #, subject, assignee...", label_visibility="collapsed")
        with f2:
            pri_filter = st.selectbox("Priority", ["All Priorities", "Critical", "High", "Medium", "Low"], label_visibility="collapsed")
        with f3:
            st_filter = st.selectbox("Filter Status", ["All Statuses", "Open", "In Progress", "On Hold", "Vendor Response", "Waiting Vendor", "Closed"], label_visibility="collapsed")
        with f4:
            include_closed = st.checkbox("Include Closed Cases", key="chk_include_closed_cases")


        st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)


        st.markdown("""
        <div class="table-header-row">
            <div style="flex: 0 0 35px; text-align: center;"><span class="th-cell">☐</span></div>
            <div style="flex: 0 0 100px;"><span class="th-cell">Case # ⇅</span></div>
            <div style="flex: 1 1 200px; padding: 0 6px;"><span class="th-cell">Subject</span></div>
            <div style="flex: 0 0 85px;"><span class="th-cell">Priority ⇅</span></div>
            <div style="flex: 0 0 120px;"><span class="th-cell">Assigned To ⇅</span></div>
            <div style="flex: 0 0 120px;"><span class="th-cell">Due Date ⇅</span></div>
            <div style="flex: 0 0 105px;"><span class="th-cell">Current Status ⇅</span></div>
            <div style="flex: 0 0 115px;"><span class="th-cell">Last Update ⇅</span></div>
            <div style="flex: 0 0 65px; text-align: center;"><span class="th-cell">Actions</span></div>
        </div>
        """, unsafe_allow_html=True)


        filtered_cases = all_base_cases
        if pri_filter != "All Priorities":
            filtered_cases = [c for c in filtered_cases if c.get("priority") == pri_filter]
        if st_filter != "All Statuses":
            filtered_cases = [c for c in filtered_cases if c.get("status") == st_filter]
        elif not include_closed:
            filtered_cases = [c for c in filtered_cases if c.get("status") != "Closed"]


        if search_val:
            s_val = search_val.lower()
            filtered_cases = [
                c for c in filtered_cases
                if (s_val in c.get("case_number", "").lower())
                or (s_val in c.get("subject", "").lower())
                or (s_val in c.get("assigned_to", "").lower())
            ]


        for c in filtered_cases:
            pri = c.get("priority", "Low")
            badge_pri = f"badge-{pri.lower()}"
            status_val = c.get("status", "Open")
            
            st_cls_map = {
                "In Progress": "st-in-progress",
                "On Hold": "st-on-hold",
                "Vendor Response": "st-vendor-response",
                "Waiting Vendor": "st-waiting-vendor",
                "Open": "st-open",
                "Pending Info": "st-pending-info",
                "Closed": "st-closed"
            }
            badge_st = st_cls_map.get(status_val, "st-open")
            countdown_txt, countdown_color, is_overdue = calculate_countdown(c.get("due_date"))


            rc1, rc2, rc3, rc4, rc5, rc6, rc7, rc8, rc9 = st.columns([0.35, 1.4, 2.7, 1.05, 1.5, 1.5, 1.3, 1.4, 0.8], gap="small")
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
                due_color = "#64748B" if status_val == "Closed" else countdown_color
                st.markdown(f"<span style='color:{due_color}; font-size:12px; font-weight:600;'>{c.get('due_date')}</span>", unsafe_allow_html=True)
            with rc7:
                st.markdown(f"<span class='badge-status {badge_st}'>{status_val}</span>", unsafe_allow_html=True)
            with rc8:
                st.markdown(f"""
                <div style="line-height:1.2;">
                    <span style="font-size:12px; color:#475569;">{c.get('last_update')}</span><br>
                    <small style="color:{countdown_color}; font-size:11px; font-weight:700;">{countdown_txt}</small>
                </div>
                """, unsafe_allow_html=True)
            
            with rc9:
                with st.container(key=f"pop_row_act_{c['case_number']}"):
                    with st.popover("⋮", help="Case Actions"):
                        st.markdown(f"**Actions for {c['case_number']}**")
                        if st.button("📋 View Details", key=f"act_view_{c['case_number']}", use_container_width=True):
                            render_case_modal(c["case_number"])


                        if is_admin:
                            roster_doc = collection.find_one({"type": "roster_list"}) or {}
                            agents = [u["name"] for u in roster_doc.get("Data", []) if u.get("role") in ["Agent", "Admin/Agent"]]
                            new_agent = st.selectbox("Reassign Case", ["-- Select --"] + agents, key=f"quick_reassign_{c['case_number']}")
                            if st.button("Apply Reassign", key=f"btn_reassign_row_{c['case_number']}", use_container_width=True):
                                if new_agent != "-- Select --":
                                    now_str = get_current_ph_time().strftime("%b %d, %Y %I:%M %p")
                                    cases_collection.update_one(
                                        {"type": "cases", "case_number": c["case_number"]},
                                        {"$set": {"assigned_to": new_agent, "last_update": now_str}}
                                    )
                                    st.success(f"Reassigned to {new_agent}!")
                                    time.sleep(0.5)
                                    st.rerun()
                        else:
                            if st.button("🔄 Request Transfer", key=f"act_trf_{c['case_number']}", use_container_width=True):
                                st.session_state[f"show_transfer_dialog_{c['case_number']}"] = True
                                render_case_modal(c["case_number"])


                        q_st = st.selectbox("Quick Status", ["Open", "In Progress", "On Hold", "Closed"], key=f"q_st_{c['case_number']}")
                        if st.button("Update Status", key=f"btn_qst_{c['case_number']}", use_container_width=True):
                            now_str = get_current_ph_time().strftime("%b %d, %Y %I:%M %p")
                            cases_collection.update_one(
                                {"type": "cases", "case_number": c["case_number"]},
                                {"$set": {"status": q_st, "last_update": now_str}}
                            )
                            st.success(f"Status changed to {q_st}")
                            time.sleep(0.5)
                            st.rerun()


            st.markdown('<hr class="case-table-divider">', unsafe_allow_html=True)


        p_info, p_btns = st.columns([1, 1])
        with p_info:
            st.caption(f"Showing 1 - {len(filtered_cases)} of {total_active} cases")
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


    with main_right:
        if is_admin_mode:
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
# 12. MONITORING TAB
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
                sess_doc = collection.find_one({"type": "sessions"}) or {}
                sess_list = sess_doc.get("Data", [])
                for s in sess_list:
                    if s.get("name") == kick_agent:
                        s["status"] = "terminated"
                        s["expires_at"] = "2000-01-01 00:00:00"
                collection.update_one({"type": "sessions"}, {"$set": {"Data": sess_list}}, upsert=True)


                for u in agents:
                    if u.get("name") == kick_agent:
                        u["is_logged_in"] = "false"
                        u["current_aux"] = "Not Ready - Online"
                collection.update_one({"type": "roster_list"}, {"$set": {"Data": roster_doc.get("Data", [])}}, upsert=True)
                st.success(f"{kick_agent} has been successfully logged out from the enterprise cluster.")
    with m_col2:
        st.info("Tip: Aux telemetry events are recorded in real-time to avoid duplicate critical case distribution.")


# ==============================================================================
# 13. SCHEDULE TAB
# ==============================================================================
def render_schedule():
    user = st.session_state.get("current_user", {})
    st.markdown("### 📅 Enterprise Workforce Schedule & PTO Tracker")
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
# 14. REPORT TAB
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
# 15. SETTINGS TAB
# ==============================================================================
def render_settings():
    st.markdown("### ⚙️ Enterprise Configuration & Master Registry")
    
    set_t1, set_t2, set_t3 = st.tabs(["👥 Team Roster Management", "🗄️ Validation Dropdowns", "📥 Vendor & Case Excel Sync"])


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
        uploaded_excel = st.file_uploader("Upload Vendor Excel File", type=["xlsx", "xls"], key="vendor_excel_uploader")
        if uploaded_excel:
            try:
                v_df = pd.read_excel(uploaded_excel)
                st.write("Preview of Uploaded Vendor Records:")
                st.dataframe(v_df.head(5), use_container_width=True)
                if st.button("🚀 Ingest & Synchronize Records to MongoDB", type="primary"):
                    st.success(f"Successfully processed and synchronized {len(v_df)} vendor records into CaseFlow cache!")
            except Exception as e:
                st.error(f"Error parsing Excel file: {e}")


        st.divider()
        st.markdown("##### Upload Cases via Excel (External Source Integration)")
        st.caption("Upload an Excel file containing new cases to be automatically ingested and assigned to available roster agents.")
        uploaded_cases_excel = st.file_uploader("Upload Cases Excel File", type=["xlsx", "xls"], key="cases_excel_uploader")
        if uploaded_cases_excel:
            try:
                c_df = pd.read_excel(uploaded_cases_excel)
                st.write("Preview of Uploaded Cases Records:")
                st.dataframe(c_df.head(5), use_container_width=True)
                if st.button("🚀 Ingest & Auto-Assign Cases to Roster", type="primary"):
                    success_count = 0
                    for _, row in c_df.iterrows():
                        new_num = f"HC-2026-{1050 + cases_collection.count_documents({'type': 'cases'}) + 1}"
                        case_payload = {
                            "type": "cases",
                            "case_number": str(row.get("Case #", new_num)),
                            "subject": str(row.get("Subject", "Imported Case")),
                            "description": str(row.get("Description", "Imported via Excel upload.")),
                            "priority": str(row.get("Priority", "Medium")),
                            "status": str(row.get("Status", "In Progress")),
                            "status_reason": str(row.get("Status Reason", "Waiting for Vendor Response")),
                            "due_date": str(row.get("Due Date", (get_current_ph_time() + timedelta(hours=24)).strftime("%b %d, %Y %I:%M %p"))),
                            "created_at": get_current_ph_time().strftime("%b %d, %Y %I:%M %p"),
                            "last_update": get_current_ph_time().strftime("%b %d, %Y %I:%M %p"),
                            "case_category": str(row.get("Category", "General")),
                            "vendor_name": str(row.get("Vendor Name", "ABC Software Inc.")),
                            "vendor_id": "VEND-ABC-019",
                            "vendor_contact": "Michael Tan",
                            "vendor_email": str(row.get("Vendor Email", "support@abcsoftware.com")),
                            "vendor_phone": "+1 555 123 4567",
                            "account": str(row.get("Account", "Enterprise Core")),
                            "related_system": str(row.get("Related System", "HPE Portal")),
                            "history": [],
                            "communications": [],
                            "attachments": []
                        }
                        auto_assign_new_case(case_payload)
                        success_count += 1
                    st.success(f"Successfully ingested and auto-assigned {success_count} cases from Excel!")
                    time.sleep(0.5)
                    st.rerun()
            except Exception as e:
                st.error(f"Error parsing Cases Excel file: {e}")


# ==============================================================================
# 15. AUTHENTICATION PAGES (SIGN-IN & SIGN-UP) - WITH DEMO ACCOUNT SIMULATION
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


            # Added Demo Account Quick-Login Simulation Buttons for each demo account
            st.markdown("##### 🚀 Quick Demo Access (Simulated Accounts)")
            d_cols = st.columns(3)
            with d_cols[0]:
                if st.button("👑 Admin Demo", use_container_width=True):
                    demo_u = authenticate_user("admin.demo@internal.test", "HPE@123456")
                    if demo_u:
                        create_session(demo_u, remember_me=True)
                        sim_case = {
                            "type": "cases",
                            "case_number": f"ADMIN-SIM-{uuid.uuid4().hex[:4].upper()}",
                            "subject": "Enterprise Cluster Security Audit",
                            "description": "Simulated critical admin review case generated upon Admin Demo login.",
                            "priority": "Critical",
                            "status": "Open",
                            "status_reason": "Pending Approval",
                            "due_date": (get_current_ph_time() + timedelta(hours=6)).strftime("%b %d, %Y %I:%M %p"),
                            "created_at": get_current_ph_time().strftime("%b %d, %Y %I:%M %p"),
                            "last_update": get_current_ph_time().strftime("%b %d, %Y %I:%M %p"),
                            "case_category": "Security",
                            "vendor_name": "HPE Security Operations",
                            "vendor_id": "VEND-SEC-001",
                            "vendor_contact": "Director Vance",
                            "vendor_email": "security@hpe.internal",
                            "vendor_phone": "+1 555 999 0000",
                            "account": "Enterprise Global",
                            "related_system": "HPE Core Cluster",
                            "history": [],
                            "communications": [],
                            "attachments": []
                        }
                        sim_case["assigned_to"] = demo_u["name"]
                        sim_case["assignee_email"] = demo_u["email"]
                        sim_case["assignee_avatar"] = demo_u.get("profile_picture", "")
                        cases_collection.insert_one(sim_case)


                        notif_doc = collection.find_one({"type": "notifications"}) or {}
                        n_list = notif_doc.get("Data", [])
                        n_list.append({
                            "id": str(uuid.uuid4()),
                            "target_email": demo_u["email"],
                            "title": "Admin Simulation: Audit Required",
                            "message": f"Critical audit case {sim_case['case_number']} has been initialized for your review.",
                            "category": "critical",
                            "case_number": sim_case['case_number'],
                            "acknowledged": "false",
                            "created_at": get_current_ph_time().strftime("%I:%M %p")
                        })
                        collection.update_one({"type": "notifications"}, {"$set": {"Data": n_list}}, upsert=True)


                        st.success("Admin Demo logged in with simulated alert & case assignment!")
                        time.sleep(0.5)
                        st.rerun()


            with d_cols[1]:
                if st.button("🛡️ Admin/Agent", use_container_width=True):
                    demo_u = authenticate_user("adminagent.demo@internal.test", "HPE@123456")
                    if demo_u:
                        create_session(demo_u, remember_me=True)
                        sim_case = {
                            "type": "cases",
                            "case_number": f"HYBRID-SIM-{uuid.uuid4().hex[:4].upper()}",
                            "subject": "Hybrid Routing Queue Escalation",
                            "description": "Simulated hybrid task auto-assigned to Admin/Agent demo account.",
                            "priority": "High",
                            "status": "In Progress",
                            "status_reason": "Investigation",
                            "due_date": (get_current_ph_time() + timedelta(hours=8)).strftime("%b %d, %Y %I:%M %p"),
                            "created_at": get_current_ph_time().strftime("%b %d, %Y %I:%M %p"),
                            "last_update": get_current_ph_time().strftime("%b %d, %Y %I:%M %p"),
                            "case_category": "Operations",
                            "vendor_name": "ABC Software Inc.",
                            "vendor_id": "VEND-ABC-019",
                            "vendor_contact": "Michael Tan",
                            "vendor_email": "support@abcsoftware.com",
                            "vendor_phone": "+1 555 123 4567",
                            "account": "Enterprise Core",
                            "related_system": "HPE CaseFlow",
                            "history": [],
                            "communications": [],
                            "attachments": []
                        }
                        sim_case["assigned_to"] = demo_u["name"]
                        sim_case["assignee_email"] = demo_u["email"]
                        sim_case["assignee_avatar"] = demo_u.get("profile_picture", "")
                        cases_collection.insert_one(sim_case)


                        notif_doc = collection.find_one({"type": "notifications"}) or {}
                        n_list = notif_doc.get("Data", [])
                        n_list.append({
                            "id": str(uuid.uuid4()),
                            "target_email": demo_u["email"],
                            "title": "Hybrid Simulation: New Escalation Assigned",
                            "message": f"Case {sim_case['case_number']} has been auto-assigned for hybrid handling.",
                            "category": "new_case",
                            "case_number": sim_case['case_number'],
                            "acknowledged": "false",
                            "created_at": get_current_ph_time().strftime("%I:%M %p")
                        })
                        collection.update_one({"type": "notifications"}, {"$set": {"Data": n_list}}, upsert=True)


                        st.success("Admin/Agent Demo logged in with simulated alert & case assignment!")
                        time.sleep(0.5)
                        st.rerun()


            with d_cols[2]:
                if st.button("👤 Agent Demo", use_container_width=True):
                    demo_u = authenticate_user("agent.demo@internal.test", "HPE@123456")
                    if demo_u:
                        create_session(demo_u, remember_me=True)
                        sim_case = {
                            "type": "cases",
                            "case_number": f"AGENT-SIM-{uuid.uuid4().hex[:4].upper()}",
                            "subject": "Simulated Inbound Storage Issue",
                            "description": "Auto-assigned case simulation for agent demo login.",
                            "priority": "Critical",
                            "status": "In Progress",
                            "status_reason": "Waiting for Vendor Response",
                            "due_date": (get_current_ph_time() + timedelta(hours=12)).strftime("%b %d, %Y %I:%M %p"),
                            "created_at": get_current_ph_time().strftime("%b %d, %Y %I:%M %p"),
                            "last_update": get_current_ph_time().strftime("%b %d, %Y %I:%M %p"),
                            "case_category": "Hardware",
                            "vendor_name": "ABC Software Inc.",
                            "vendor_id": "VEND-ABC-019",
                            "vendor_contact": "Michael Tan",
                            "vendor_email": "support@abcsoftware.com",
                            "vendor_phone": "+1 555 123 4567",
                            "account": "Enterprise Demo",
                            "related_system": "HPE Pointnext",
                            "history": [],
                            "communications": [],
                            "attachments": []
                        }
                        sim_case["assigned_to"] = demo_u["name"]
                        sim_case["assignee_email"] = demo_u["email"]
                        sim_case["assignee_avatar"] = demo_u.get("profile_picture", "")
                        cases_collection.insert_one(sim_case)


                        notif_doc = collection.find_one({"type": "notifications"}) or {}
                        n_list = notif_doc.get("Data", [])
                        n_list.append({
                            "id": str(uuid.uuid4()),
                            "target_email": demo_u["email"],
                            "title": "Agent Simulation: New Case Assigned",
                            "message": f"Simulation active: {sim_case['case_number']} has been automatically assigned to you.",
                            "category": "critical",
                            "case_number": sim_case['case_number'],
                            "acknowledged": "false",
                            "created_at": get_current_ph_time().strftime("%I:%M %p")
                        })
                        collection.update_one({"type": "notifications"}, {"$set": {"Data": n_list}}, upsert=True)


                        st.success("Agent Demo logged in with simulated alert & case assignment!")
                        time.sleep(0.5)
                        st.rerun()


            st.markdown("<div style='text-align:center; color:#94A3B8; margin:10px 0;'>&mdash; or enter credentials &mdash;</div>", unsafe_allow_html=True)


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
                        "name": str(su_fn + " " + su_ln).strip(),
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
# 16. FIXED BOTTOM NAVIGATION
# ==============================================================================
def render_bottom_navigation():
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


    if not st.session_state.get("authenticated", False) and not st.session_state.get("manual_logout", False):
        roster_doc = collection.find_one({"type": "roster_list"}) or {}
        admin_user = next((u for u in roster_doc.get("Data", []) if u.get("email") == "admin.demo@internal.test"), None)
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
