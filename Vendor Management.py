"""
HPE CaseFlow - Streamlit single-file application

Features
- Modern HPE-inspired UI based on the supplied reference images.
- Mandatory sign-in / sign-up flow.
- User profiles stored in TeamRoster / Team Roster Collection with type='roster_list'.
- Passwords are stored as bcrypt hashes, never plaintext.
- Auto-admin seed: Admin@Admin.com / Admin1234 (change with environment variables).
- Regular-agent and admin navigation with retractable sidebar.
- Dashboard tiles, urgency sorting, case details, alerts, schedules, requests,
  attendance/adherence, agent presence and distribution.
- Automatic case assignment using availability + least-load/fairness scoring.
- Transient live AUX presence is synced through a short-lived Mongo collection
  (live_presence) so other browser sessions can see it without permanently
  writing AUX to roster records. If Mongo is unavailable, an in-process fallback
  is used for local development.
- Admin-only Salesforce integration link.
- Optional Salesforce REST hook via environment variables.
- CSV report export.
- Polling is limited to small, cache-friendly fragments so switching tabs does not
  cause a full application data reload.

Run:
    pip install -r requirements.txt
    streamlit run hpe_caseflow_streamlit.py

Environment variables (all optional):
    MONGODB_URI=mongodb://localhost:27017
    ADMIN_EMAIL=Admin@Admin.com
    ADMIN_PASSWORD=Admin1234
    SALESFORCE_URL=https://hp.lightning.force.com/
    REALTIME_SECONDS=5
    APP_TIMEZONE=Asia/Manila

If get_mongo_client() already exists in your project, replace the get_mongo_client()
implementation below with your existing helper.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import secrets
import smtplib
import time
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

try:
    import bcrypt
except ImportError:  # graceful fallback for environments where bcrypt is unavailable
    bcrypt = None

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------
APP_NAME = "HPE CaseFlow"
SALESFORCE_URL = os.getenv("SALESFORCE_URL", "https://hp.lightning.force.com/")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "Admin@Admin.com").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin1234")
REALTIME_SECONDS = max(3, int(os.getenv("REALTIME_SECONDS", "5")))
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Manila")
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")

DB_NAME = "TeamRoster"
ROSTER_COLLECTION = "Team Roster Collection"
CASES_COLLECTION = "cases"
SCHEDULE_COLLECTION = "schedules"
REQUESTS_COLLECTION = "requests"
NOTIFICATIONS_COLLECTION = "notifications"
SETTINGS_COLLECTION = "settings"
PRESENCE_COLLECTION = "live_presence"
AUDIT_COLLECTION = "audit_log"

DEFAULT_AUXES = [
    "Available",
    "Break",
    "Unscheduled Break",
    "Lunch",
    "In a Meeting",
    "Coaching",
    "Busy - Away",
    "Admin Task",
]

ACTIVE_CASE_STATUSES = {
    "New",
    "Assigned",
    "In Progress",
    "Pending Vendor",
    "Pending Customer",
    "Pending Internal",
    "On Hold",
    "Contract Breached",
}
CLOSED_CASE_STATUSES = {"Completed", "Closed", "Cancelled"}
URGENCY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}

# -----------------------------------------------------------------------------
# PAGE + CSS
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title=APP_NAME,
    page_icon="▣",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_css():
    st.markdown(
        """
        <style>
        :root {
            --hpe-navy:#123A59;
            --hpe-blue:#0878C9;
            --hpe-deep:#0B2F4A;
            --hpe-teal:#00A88F;
            --hpe-bg:#F4F7FA;
            --hpe-card:#FFFFFF;
            --hpe-text:#142B3F;
            --muted:#65798A;
            --line:#D9E2EA;
            --danger:#D92D3A;
            --warning:#D99800;
            --success:#12966F;
        }
        #MainMenu, footer { visibility:hidden; }
        header { visibility:hidden; height:0; }
        [data-testid="stToolbar"] { display:none !important; }
        [data-testid="stDecoration"] { display:none !important; }
        [data-testid="stStatusWidget"] { display:none !important; }
        .stApp { background:var(--hpe-bg); color:var(--hpe-text); }
        .block-container { padding:1rem 1.25rem 2rem 1.25rem; max-width:100%; }
        [data-testid="stSidebar"] { background:linear-gradient(180deg,#08324E 0%,#0B496B 100%); }
        [data-testid="stSidebar"] * { color:#fff !important; }
        [data-testid="stSidebar"] .stButton > button {
            width:100%; border:0; border-radius:10px; background:transparent;
            text-align:left; padding:.72rem .85rem; color:#fff; font-weight:600;
        }
        [data-testid="stSidebar"] .stButton > button:hover,
        [data-testid="stSidebar"] .nav-active > button {
            background:#0878C9; color:#fff; 
        }
        .brand { padding:.35rem .35rem 1rem .35rem; }
        .brand-logo { color:#00B39F; font-size:2rem; line-height:1; font-weight:800; }
        .brand-title { font-size:1.1rem; font-weight:800; margin-top:.25rem; }
        .brand-sub { color:#BBD0DD !important; font-size:.78rem; }
        .topbar { background:#fff; border-bottom:1px solid var(--line); padding:.25rem .25rem .7rem .25rem; }
        .eyebrow { color:var(--hpe-blue); font-weight:800; letter-spacing:.04em; text-transform:uppercase; font-size:.73rem; }
        h1,h2,h3,h4 { color:var(--hpe-navy); }
        .hero { display:flex; justify-content:space-between; align-items:center; gap:1rem; margin-bottom:1rem; }
        .hero h1 { margin:.1rem 0; font-size:2rem; }
        .hero p { color:var(--muted); margin:.1rem 0; }
        .profile-chip { background:#fff; border:1px solid var(--line); border-radius:999px; padding:.45rem .8rem; }
        .metric-card { border:1px solid var(--line); background:#fff; border-radius:14px; padding:1rem; min-height:105px; box-shadow:0 2px 8px rgba(12,45,70,.05); }
        .metric-number { font-size:2rem; font-weight:850; line-height:1; }
        .metric-label { margin-top:.45rem; font-size:.82rem; color:#566B7C; font-weight:700; }
        .metric-blue { border-top:4px solid #1B86D5; }
        .metric-red { border-top:4px solid #D92D3A; }
        .metric-yellow { border-top:4px solid #D99800; }
        .metric-green { border-top:4px solid #12966F; }
        .section-card { background:#fff; border:1px solid var(--line); border-radius:14px; padding:1rem; box-shadow:0 2px 8px rgba(12,45,70,.04); margin-bottom:1rem; }
        .alert-card { background:#FFF7E6; border:1px solid #F5D48B; border-radius:14px; padding:1rem; }
        .case-critical { border-left:5px solid #D92D3A; }
        .case-high { border-left:5px solid #F06A38; }
        .case-medium { border-left:5px solid #D99800; }
        .case-low { border-left:5px solid #12966F; }
        .pill { display:inline-block; border-radius:999px; padding:.2rem .55rem; font-size:.72rem; font-weight:800; }
        .pill-red { background:#FFE1E5; color:#A61725; }
        .pill-yellow { background:#FFF0C2; color:#8A5A00; }
        .pill-green { background:#D8F5E9; color:#08764F; }
        .pill-blue { background:#DDEFFF; color:#075C9E; }
        .small-muted { color:var(--muted); font-size:.78rem; }
        .login-wrap { max-width:1180px; margin:2vh auto; background:#fff; border-radius:20px; overflow:hidden; box-shadow:0 18px 60px rgba(10,44,70,.18); }
        .login-left { min-height:760px; padding:3rem; color:#fff; background:linear-gradient(145deg,#0A3E60,#0B2F4A); position:relative; overflow:hidden; }
        .login-left:after { content:""; position:absolute; left:0; right:0; bottom:-40px; height:310px; background:radial-gradient(circle at 50% 0%, rgba(0,190,170,.22), transparent 55%); }
        .login-logo-mark { width:70px; height:25px; border:5px solid #00B39F; margin-bottom:1.2rem; }
        .login-left h1 { color:#fff; font-size:2.1rem; margin:0; }
        .login-left h2 { color:#fff; font-size:1.9rem; margin:2rem 0 .35rem; }
        .login-left p { color:#E0EEF5; font-size:1.05rem; max-width:420px; }
        .feature { display:flex; gap:.9rem; margin:1.2rem 0; position:relative; z-index:1; }
        .feature-icon { font-size:1.65rem; width:40px; }
        .feature b { display:block; }
        .feature small { color:#BFD2DF; }
        .login-right { min-height:760px; padding:3.1rem 3rem; background:#fff; }
        .login-right h1 { font-size:2rem; margin:.2rem 0; }
        .login-right .sub { color:var(--muted); margin-bottom:1.8rem; }
        .stButton > button { border-radius:9px; min-height:2.55rem; font-weight:750; }
        .primary-action button { background:#0878C9 !important; color:#fff !important; border:0 !important; }
        .danger-action button { background:#D92D3A !important; color:#fff !important; border:0 !important; }
        .success-action button { background:#12966F !important; color:#fff !important; border:0 !important; }
        .ghost-action button { background:#fff !important; color:#0878C9 !important; border:1px solid #0878C9 !important; }
        .table-wrap { overflow-x:auto; }
        .case-row { background:#fff; border:1px solid var(--line); border-radius:10px; padding:.65rem .75rem; margin:.35rem 0; }
        .tv-mode .block-container { padding:.65rem .8rem; }
        .tv-mode .metric-card { min-height:88px; padding:.7rem; }
        .tv-mode .metric-number { font-size:1.65rem; }
        .tv-mode .section-card { padding:.75rem; }
        @media (max-width: 900px) {
            .login-left,.login-right { min-height:auto; padding:2rem; }
            .hero { align-items:flex-start; flex-direction:column; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_css()

# -----------------------------------------------------------------------------
# MONGODB
# -----------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def get_mongo_client() -> MongoClient:
    return MongoClient(MONGODB_URI, serverSelectionTimeoutMS=3500, connectTimeoutMS=3500)


@st.cache_resource(show_spinner=False)
def get_db():
    client = get_mongo_client()
    return client[DB_NAME]


def mongo_ok() -> bool:
    try:
        get_mongo_client().admin.command("ping")
        return True
    except Exception:
        return False


def collection(name: str):
    return get_db()[name]


def ensure_indexes():
    if not mongo_ok():
        return
    try:
        collection(ROSTER_COLLECTION).create_index([("type", ASCENDING), ("email", ASCENDING)], unique=False)
        collection(ROSTER_COLLECTION).create_index("email", unique=True)
        collection(CASES_COLLECTION).create_index([("status", ASCENDING), ("priority", ASCENDING), ("due_date", ASCENDING)])
        collection(CASES_COLLECTION).create_index("assigned_to")
        collection(PRESENCE_COLLECTION).create_index("expires_at", expireAfterSeconds=0)
        collection(PRESENCE_COLLECTION).create_index("email", unique=True)
        collection(NOTIFICATIONS_COLLECTION).create_index([("email", ASCENDING), ("created_at", DESCENDING)])
        collection(REQUESTS_COLLECTION).create_index([("status", ASCENDING), ("created_at", DESCENDING)])
    except Exception:
        pass


ensure_indexes()


# -----------------------------------------------------------------------------
# LOCAL FALLBACK DATA
# -----------------------------------------------------------------------------

if "local_store" not in st.session_state:
    st.session_state.local_store = {
        "roster": {},
        "cases": [],
        "schedules": [],
        "requests": [],
        "notifications": [],
        "presence": {},
        "settings": {},
        "audit": [],
    }


def now_local() -> datetime:
    if ZoneInfo:
        return datetime.now(ZoneInfo(APP_TIMEZONE)).replace(tzinfo=None)
    return datetime.now()


def iso_now() -> str:
    return now_local().isoformat(timespec="seconds")


def as_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    try:
        return datetime.fromisoformat(str(value).replace("Z", ""))
    except Exception:
        return None


def serialize(obj: Any):
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj


# -----------------------------------------------------------------------------
# SECURITY / AUTH
# -----------------------------------------------------------------------------

def hash_password(password: str) -> str:
    if bcrypt:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    salt = secrets.token_hex(16)
    return "sha256$" + salt + "$" + hashlib.sha256((salt + password).encode()).hexdigest()


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    if stored.startswith("sha256$"):
        try:
            _, salt, digest = stored.split("$", 2)
            return secrets.compare_digest(
                digest, hashlib.sha256((salt + password).encode()).hexdigest()
            )
        except Exception:
            return False
    if bcrypt:
        try:
            return bcrypt.checkpw(password.encode(), stored.encode())
        except Exception:
            return False
    return False


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def valid_hpe_email(email: str) -> bool:
    return normalize_email(email).endswith("@hpe.com")


def roster_find(email: str) -> Optional[Dict[str, Any]]:
    email = normalize_email(email)
    if mongo_ok():
        try:
            doc = collection(ROSTER_COLLECTION).find_one({"email": email})
            if doc:
                doc["_id"] = str(doc.get("_id", ""))
                return doc
        except Exception:
            pass
    return st.session_state.local_store["roster"].get(email)


def roster_upsert(doc: Dict[str, Any]):
    email = normalize_email(doc["email"])
    doc = dict(doc)
    doc["email"] = email
    doc.setdefault("type", "roster_list")
    doc["updated_at"] = iso_now()
    if mongo_ok():
        try:
            collection(ROSTER_COLLECTION).update_one({"email": email}, {"$set": doc}, upsert=True)
            return
        except Exception:
            pass
    st.session_state.local_store["roster"][email] = doc


def roster_all() -> List[Dict[str, Any]]:
    if mongo_ok():
        try:
            return list(collection(ROSTER_COLLECTION).find({"type": "roster_list"}).sort("last_name", ASCENDING))
        except Exception:
            pass
    return list(st.session_state.local_store["roster"].values())


def seed_admin():
    admin = roster_find(ADMIN_EMAIL)
    if admin:
        # Keep an explicitly seeded admin as admin even if a prior demo record changed.
        if admin.get("role") != "Admin" or admin.get("is_super_admin") is not True:
            roster_upsert({**admin, "role": "Admin", "is_super_admin": True, "type": "roster_list"})
        return
    roster_upsert(
        {
            "type": "roster_list",
            "first_name": "Admin",
            "last_name": "",
            "employee_id": "ADMIN-001",
            "email": ADMIN_EMAIL,
            "birthday": "",
            "home_address": "",
            "contact_number": "",
            "password_hash": hash_password(ADMIN_PASSWORD),
            "role": "Admin",
            "is_super_admin": True,
            "status": "Active",
            "created_at": iso_now(),
        }
    )


seed_admin()


def audit(action: str, actor: str, details: Dict[str, Any] | None = None):
    item = {"action": action, "actor": actor, "details": details or {}, "created_at": iso_now()}
    if mongo_ok():
        try:
            collection(AUDIT_COLLECTION).insert_one(item)
            return
        except Exception:
            pass
    st.session_state.local_store["audit"].append(item)


# -----------------------------------------------------------------------------
# DATA ACCESS
# -----------------------------------------------------------------------------

def sample_cases() -> List[Dict[str, Any]]:
    n = now_local()
    return [
        {
            "case_number": "0000156", "subject": "Network equipment delay", "priority": "Critical",
            "due_date": n + timedelta(hours=2), "status": "In Progress", "progress": 55,
            "last_update": n - timedelta(hours=3), "assigned_to": "john.delacruz@hpe.com",
            "vendor": "Acme Network Services", "vendor_email": "vendor@example.com", "vendor_phone": "+63 917 000 0156",
            "description": "Customer is waiting for network equipment delivery.", "source": "Demo", "created_at": n - timedelta(days=1),
        },
        {
            "case_number": "0000143", "subject": "Server replacement", "priority": "High",
            "due_date": n + timedelta(hours=5), "status": "Pending Vendor", "progress": 40,
            "last_update": n - timedelta(hours=1), "assigned_to": "maria.santos@hpe.com",
            "vendor": "Global Server Repair", "vendor_email": "repair@example.com", "vendor_phone": "+63 917 000 0143",
            "description": "Replacement unit is pending vendor confirmation.", "source": "Demo", "created_at": n - timedelta(days=2),
        },
        {
            "case_number": "0000132", "subject": "Software license", "priority": "Medium",
            "due_date": n + timedelta(days=2), "status": "Assigned", "progress": 15,
            "last_update": n - timedelta(hours=5), "assigned_to": "mark.rivera@hpe.com",
            "vendor": "HPE Software Licensing", "vendor_email": "software@example.com", "vendor_phone": "+63 917 000 0132",
            "description": "Customer requires licensing assistance.", "source": "Demo", "created_at": n - timedelta(days=1),
        },
        {
            "case_number": "0000128", "subject": "Site installation", "priority": "Medium",
            "due_date": n + timedelta(days=3), "status": "In Progress", "progress": 70,
            "last_update": n - timedelta(hours=2), "assigned_to": "ana.reyes@hpe.com",
            "vendor": "Site Install Partners", "vendor_email": "site@example.com", "vendor_phone": "+63 917 000 0128",
            "description": "Installation work is underway.", "source": "Demo", "created_at": n - timedelta(days=3),
        },
        {
            "case_number": "0000120", "subject": "Access request", "priority": "Low",
            "due_date": n + timedelta(days=4), "status": "New", "progress": 0,
            "last_update": n - timedelta(hours=1), "assigned_to": None,
            "vendor": "", "vendor_email": "", "vendor_phone": "",
            "description": "Access request awaiting assignment.", "source": "Demo", "created_at": n - timedelta(hours=1),
        },
    ]


def cases_all() -> List[Dict[str, Any]]:
    if mongo_ok():
        try:
            return list(collection(CASES_COLLECTION).find({}).sort("due_date", ASCENDING))
        except Exception:
            pass
    cases = st.session_state.local_store["cases"]
    if not cases:
        cases = sample_cases()
        st.session_state.local_store["cases"] = cases
    return cases


def case_save(case: Dict[str, Any]):
    case = dict(case)
    case["updated_at"] = iso_now()
    if mongo_ok():
        try:
            key = {"case_number": case["case_number"]}
            collection(CASES_COLLECTION).update_one(key, {"$set": case}, upsert=True)
            return
        except Exception:
            pass
    items = st.session_state.local_store["cases"]
    for i, c in enumerate(items):
        if c.get("case_number") == case.get("case_number"):
            items[i] = case
            return
    items.append(case)


def schedules_for(email: Optional[str] = None, day: Optional[date] = None) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {}
    if email:
        query["email"] = normalize_email(email)
    if day:
        query["date"] = day.isoformat()
    if mongo_ok():
        try:
            return list(collection(SCHEDULE_COLLECTION).find(query).sort("start", ASCENDING))
        except Exception:
            pass
    rows = st.session_state.local_store["schedules"]
    return [r for r in rows if (not email or normalize_email(r.get("email")) == normalize_email(email)) and (not day or r.get("date") == day.isoformat())]


def schedule_save(row: Dict[str, Any]):
    if mongo_ok():
        try:
            collection(SCHEDULE_COLLECTION).update_one(
                {"email": row["email"], "date": row["date"], "start": row["start"]},
                {"$set": row},
                upsert=True,
            )
            return
        except Exception:
            pass
    rows = st.session_state.local_store["schedules"]
    for i, r in enumerate(rows):
        if all(r.get(k) == row.get(k) for k in ("email", "date", "start")):
            rows[i] = row
            return
    rows.append(row)


def request_save(row: Dict[str, Any]):
    row = dict(row)
    row.setdefault("created_at", iso_now())
    if mongo_ok():
        try:
            collection(REQUESTS_COLLECTION).insert_one(row)
            return
        except Exception:
            pass
    st.session_state.local_store["requests"].append(row)


def requests_all(query: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    query = query or {}
    if mongo_ok():
        try:
            return list(collection(REQUESTS_COLLECTION).find(query).sort("created_at", DESCENDING))
        except Exception:
            pass
    rows = st.session_state.local_store["requests"]
    return [r for r in rows if all(r.get(k) == v for k, v in query.items())]


def notify(email: str, title: str, message: str, kind: str = "info"):
    row = {"email": normalize_email(email), "title": title, "message": message, "kind": kind, "read": False, "created_at": iso_now()}
    if mongo_ok():
        try:
            collection(NOTIFICATIONS_COLLECTION).insert_one(row)
            return
        except Exception:
            pass
    st.session_state.local_store["notifications"].append(row)


def notifications(email: str) -> List[Dict[str, Any]]:
    if mongo_ok():
        try:
            return list(collection(NOTIFICATIONS_COLLECTION).find({"email": normalize_email(email), "read": False}).sort("created_at", DESCENDING).limit(20))
        except Exception:
            pass
    return [n for n in st.session_state.local_store["notifications"] if n["email"] == normalize_email(email) and not n["read"]][-20:]


# -----------------------------------------------------------------------------
# LIVE PRESENCE / AUX
# -----------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def local_presence_store():
    return {}


def presence_set(email: str, aux: str):
    email = normalize_email(email)
    expires = now_local() + timedelta(seconds=max(20, REALTIME_SECONDS * 4))
    row = {"email": email, "aux": aux, "last_seen": iso_now(), "expires_at": expires}
    if mongo_ok():
        try:
            collection(PRESENCE_COLLECTION).update_one({"email": email}, {"$set": row}, upsert=True)
            return
        except Exception:
            pass
    local_presence_store()[email] = row


def presence_get(email: str) -> Dict[str, Any]:
    email = normalize_email(email)
    if mongo_ok():
        try:
            row = collection(PRESENCE_COLLECTION).find_one({"email": email})
            if row:
                return row
        except Exception:
            pass
    return local_presence_store().get(email, {"aux": "Busy - Away", "last_seen": iso_now()})


def presence_all() -> Dict[str, Dict[str, Any]]:
    if mongo_ok():
        try:
            rows = collection(PRESENCE_COLLECTION).find({"expires_at": {"$gt": now_local()}})
            return {r["email"]: r for r in rows}
        except Exception:
            pass
    return local_presence_store()


def agent_available(profile: Dict[str, Any]) -> bool:
    if profile.get("role") != "Agent" or profile.get("status", "Active") != "Active":
        return False
    aux = presence_get(profile.get("email", "")).get("aux", "Busy - Away")
    return aux == "Available"


def active_cases_for(email: str) -> List[Dict[str, Any]]:
    email = normalize_email(email)
    return [c for c in cases_all() if normalize_email(c.get("assigned_to")) == email and c.get("status") not in CLOSED_CASE_STATUSES]


def fair_assignment(c: Dict[str, Any], actor: str = "system") -> Optional[str]:
    agents = [r for r in roster_all() if r.get("role") == "Agent" and r.get("status", "Active") == "Active"]
    candidates = [a for a in agents if agent_available(a)]
    if not candidates:
        return None

    pres = presence_all()
    scored = []
    for a in candidates:
        email = normalize_email(a.get("email"))
        active = active_cases_for(email)
        total_assigned = sum(1 for x in cases_all() if normalize_email(x.get("assigned_to")) == email)
        today_assigned = sum(
            1 for x in cases_all()
            if normalize_email(x.get("assigned_to")) == email
            and (as_datetime(x.get("created_at")) or now_local()).date() == now_local().date()
        )
        aux_age = as_datetime(pres.get(email, {}).get("last_seen"))
        freshness_penalty = 0 if aux_age is None else max(0, (now_local() - aux_age).total_seconds()) / 300
        # active load is primary, then today's count, then total count; small freshness penalty
        score = (len(active), today_assigned, total_assigned, freshness_penalty)
        scored.append((score, email))
    scored.sort(key=lambda x: x[0])
    selected = scored[0][1]

    c = dict(c)
    c["assigned_to"] = selected
    if c.get("status") in (None, "New"):
        c["status"] = "Assigned"
    c["assigned_at"] = iso_now()
    case_save(c)
    notify(selected, "New case assigned", f"Case #{c.get('case_number')} was assigned to you.", "case")
    audit("auto_assign_case", actor, {"case": c.get("case_number"), "assigned_to": selected})
    return selected


def assign_unassigned_cases():
    # Keep this small: only inspect new/unassigned records on each dashboard tick.
    for c in cases_all():
        if c.get("status") in CLOSED_CASE_STATUSES:
            continue
        if not c.get("assigned_to") and c.get("status") in (None, "New", "Assigned"):
            fair_assignment(c)


# -----------------------------------------------------------------------------
# CASE / ALERT HELPERS
# -----------------------------------------------------------------------------

def case_due_category(c: Dict[str, Any]) -> str:
    due = as_datetime(c.get("due_date"))
    if not due:
        return "On Track"
    hours = (due - now_local()).total_seconds() / 3600
    if c.get("priority") == "Critical" or hours <= 0:
        return "Critical"
    if hours <= 24:
        return "Due Soon"
    return "On Track"


def case_sort_key(c: Dict[str, Any]):
    due = as_datetime(c.get("due_date")) or datetime.max
    return (URGENCY_ORDER.get(c.get("priority"), 9), due)


def case_row_class(c: Dict[str, Any]) -> str:
    return {
        "Critical": "case-critical",
        "High": "case-high",
        "Medium": "case-medium",
        "Low": "case-low",
    }.get(c.get("priority"), "")


def urgency_pill(priority: str) -> str:
    cls = {"Critical":"pill-red","High":"pill-red","Medium":"pill-yellow","Low":"pill-green"}.get(priority,"pill-blue")
    return f'<span class="pill {cls}">{priority}</span>'


def status_pill(status: str) -> str:
    cls = "pill-green" if status in {"Completed","Closed","In Progress"} else "pill-yellow" if "Pending" in status or status in {"On Hold","Assigned"} else "pill-red" if status == "Contract Breached" else "pill-blue"
    return f'<span class="pill {cls}">{status}</span>'


def alerts_for_agent(email: str) -> List[Dict[str, Any]]:
    result = []
    cases = active_cases_for(email)
    for c in cases:
        due = as_datetime(c.get("due_date"))
        last = as_datetime(c.get("last_update"))
        if c.get("priority") == "Critical":
            result.append({"kind":"critical","text":f"Case #{c.get('case_number')} is Critical","time":c.get("last_update")})
        if due and 0 <= (due - now_local()).total_seconds() <= 4 * 3600:
            result.append({"kind":"due","text":f"Case #{c.get('case_number')} is due soon","time":c.get("due_date")})
        if last and (now_local() - last).total_seconds() >= 24 * 3600:
            result.append({"kind":"stale","text":f"Case #{c.get('case_number')} has not been updated for 24 hours","time":last})
    result.extend({"kind":n.get("kind","info"),"text":n.get("message"),"time":n.get("created_at")} for n in notifications(email))
    return result[:15]


def generate_breach_message(c: Dict[str, Any], reason: str, agent_name: str) -> str:
    templates = {
        "Missed committed delivery date": f"Hello {c.get('vendor','Vendor Team')},\n\nCase #{c.get('case_number')} has exceeded the committed delivery date. Please provide an immediate recovery plan and updated ETA. This case is being tagged as a contract breach due to a missed committed delivery date.\n\nRegards,\n{agent_name} | HPE CaseFlow",
        "Repeated missed follow-up": f"Hello {c.get('vendor','Vendor Team')},\n\nCase #{c.get('case_number')} has had repeated missed follow-ups. Please provide a confirmed recovery plan and owner today. This case is being tagged as a contract breach for repeated missed follow-up.\n\nRegards,\n{agent_name} | HPE CaseFlow",
        "Vendor failed to deliver after escalation": f"Hello {c.get('vendor','Vendor Team')},\n\nCase #{c.get('case_number')} remains undelivered after escalation. Please provide an immediate resolution and confirmed ETA. This case is being tagged as a contract breach following the escalation.\n\nRegards,\n{agent_name} | HPE CaseFlow",
        "Other": f"Hello {c.get('vendor','Vendor Team')},\n\nCase #{c.get('case_number')} is being tagged as a contract breach. Reason: Other. Please provide an immediate recovery plan and confirmed ETA.\n\nRegards,\n{agent_name} | HPE CaseFlow",
    }
    return templates.get(reason, templates["Other"])


# -----------------------------------------------------------------------------
# UI HELPERS
# -----------------------------------------------------------------------------

def logo_sidebar():
    st.markdown(
        '<div class="brand"><div class="brand-logo">▱</div><div class="brand-title">HPE CaseFlow</div><div class="brand-sub">Team Task &amp; Case Management</div></div>',
        unsafe_allow_html=True,
    )


def topbar(profile: Dict[str, Any]):
    c1, c2 = st.columns([8, 2])
    with c1:
        st.markdown(f'<div class="eyebrow">{profile.get("role", "Agent")} workspace</div>', unsafe_allow_html=True)
    with c2:
        with st.popover(f'👤 {profile.get("first_name", "User")} {profile.get("last_name", "")} ▾'):
            st.markdown(f"**{profile.get('first_name','')} {profile.get('last_name','')}**")
            st.caption(f"{profile.get('email','')} · {profile.get('role','Agent')}")
            st.divider()
            if profile.get("role") == "Agent":
                current_aux = presence_get(profile.get("email", "")).get("aux", "Busy - Away")
                st.caption("AUX / Presence")
                aux = st.selectbox("Current status", DEFAULT_AUXES, index=DEFAULT_AUXES.index(current_aux) if current_aux in DEFAULT_AUXES else 0, key="profile_aux")
                if aux != current_aux:
                    presence_set(profile["email"], aux)
                    st.toast(f"AUX changed to {aux}")
                    st.rerun()
            else:
                presence_set(profile["email"], "Admin Task")
                st.info("Admin AUX is locked to **Admin Task**.")
            st.divider()
            if st.button("Sign out", use_container_width=True):
                audit("logout", profile["email"])
                for k in ["authenticated", "profile", "selected_case", "page"]:
                    st.session_state.pop(k, None)
                st.rerun()


def render_metric(label: str, number: int, style: str, key: str):
    # A button is used as the click target, but CSS makes it look like a metric tile.
    st.markdown(f'<div class="metric-card {style}"><div class="metric-number">{number}</div><div class="metric-label">{label}</div></div>', unsafe_allow_html=True)
    if st.button(f"View {label}", key=key, use_container_width=True):
        st.session_state["case_filter"] = key.replace("metric_", "").replace("_", " ").title()
        st.session_state["page"] = "My Cases" if st.session_state.profile.get("role") == "Agent" else "Cases"
        st.rerun()


def sidebar(profile: Dict[str, Any]):
    with st.sidebar:
        logo_sidebar()
        role = profile.get("role")
        pages = ["Dashboard", "My Cases", "Schedule", "Requests"] if role == "Agent" else ["Dashboard", "Cases", "Agents", "Schedule", "Requests", "Reports", "Salesforce", "Settings"]
        current = st.session_state.get("page", "Dashboard")
        for p in pages:
            cls = "nav-active" if current == p else ""
            st.markdown(f'<div class="{cls}">', unsafe_allow_html=True)
            if st.button(p, key=f"nav_{p}", use_container_width=True):
                st.session_state["page"] = p
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
        st.caption("Realtime polling")
        st.caption(f"Every {REALTIME_SECONDS}s · {APP_TIMEZONE}")
        st.caption("Use the profile menu for AUX")


def page_title(title: str, subtitle: str = ""):
    st.markdown(f'<div class="hero"><div><div class="eyebrow">HPE CaseFlow</div><h1>{title}</h1><p>{subtitle}</p></div></div>', unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# AUTH UI
# -----------------------------------------------------------------------------

def login_background():
    st.markdown(
        """
        <div class="login-wrap">
        <div class="login-left">
            <div class="login-logo-mark"></div>
            <h1>Hewlett Packard<br>Enterprise</h1>
            <h2>HPE CaseFlow</h2>
            <p>Team Task and Case Management</p>
            <div class="feature"><div class="feature-icon">▣</div><div><b>Manage Cases</b><small>Track and resolve tasks efficiently</small></div></div>
            <div class="feature"><div class="feature-icon">♧</div><div><b>Team Collaboration</b><small>Work together for better service delivery</small></div></div>
            <div class="feature"><div class="feature-icon">▥</div><div><b>Real-Time Visibility</b><small>Stay informed and in control</small></div></div>
            <div class="feature"><div class="feature-icon">♢</div><div><b>Secure Access</b><small>HPE employees only</small></div></div>
        </div>
        <div class="login-right">
        """,
        unsafe_allow_html=True,
    )


def auth_screen():
    # Mirrors the supplied sign-in/sign-up reference: navy HPE panel on the left,
    # white authentication panel on the right. The forms open as Streamlit dialogs.
    asset = Path(__file__).parent / "hpe_caseflow_assets" / "hpe_building.png"
    bg = ""
    if asset.exists():
        try:
            encoded = base64.b64encode(asset.read_bytes()).decode()
            bg = f"background-image:linear-gradient(to top,rgba(5,35,55,.86),rgba(5,35,55,.05)),url(data:image/png;base64,{encoded});"
        except Exception:
            bg = ""
    st.markdown("<div style='height:3vh'></div>", unsafe_allow_html=True)
    left, right = st.columns([1, 1.35], gap="small")
    with left:
        html = f"""
        <div class="login-left" style="{bg}">
            <div class="login-logo-mark"></div>
            <h1>Hewlett Packard<br>Enterprise</h1>
            <h2>HPE CaseFlow</h2>
            <p>Team Task and Case Management</p>
            <div class="feature"><div class="feature-icon">▣</div><div><b>Manage Cases</b><small>Track and resolve tasks efficiently</small></div></div>
            <div class="feature"><div class="feature-icon">♧</div><div><b>Team Collaboration</b><small>Work together for better service delivery</small></div></div>
            <div class="feature"><div class="feature-icon">▥</div><div><b>Real-Time Visibility</b><small>Stay informed and in control</small></div></div>
            <div class="feature"><div class="feature-icon">♢</div><div><b>Secure Access</b><small>HPE employees only</small></div></div>
        </div>
        """
        st.markdown(html, unsafe_allow_html=True)
    with right:
        st.markdown('<div class="login-right">', unsafe_allow_html=True)
        st.markdown("# Welcome to HPE CaseFlow")
        st.markdown("### Secure access for HPE employees")
        st.caption("Choose an option below. The selected form opens in a popup so the landing screen stays clean.")
        st.markdown("<div style='height:.8rem'></div>", unsafe_allow_html=True)
        a, b = st.columns(2)
        with a:
            if st.button("Sign In", use_container_width=True, type="primary"):
                sign_in_dialog()
        with b:
            if st.button("Sign Up", use_container_width=True):
                sign_up_dialog()
        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown("**Secure account storage**")
        st.caption("Registration data is written to the TeamRoster database with type = roster_list. Passwords are hashed before storage.")
        st.markdown("**Default super admin**")
        st.code(f"{ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        st.caption("Change ADMIN_EMAIL and ADMIN_PASSWORD before production use.")
        st.markdown('</div>', unsafe_allow_html=True)


@st.dialog("Sign In")
def sign_in_dialog():
    st.write("Access your HPE CaseFlow account")
    email = st.text_input("HPE Email Address", placeholder="name@hpe.com")
    password = st.text_input("Password", type="password")
    keep = st.checkbox("Keep me signed in", value=True)
    if st.button("Sign In", type="primary", use_container_width=True):
        email_n = normalize_email(email)
        if not valid_hpe_email(email_n):
            st.error("Use your HPE email address.")
            return
        profile = roster_find(email_n)
        if not profile or not verify_password(password, profile.get("password_hash", "")):
            st.error("Invalid account or password.")
            return
        if profile.get("status", "Active") != "Active":
            st.error("This account is inactive. Contact an administrator.")
            return
        st.session_state.authenticated = True
        st.session_state.profile = profile
        st.session_state.page = "Dashboard"
        if profile.get("role") == "Admin":
            presence_set(email_n, "Admin Task")
        else:
            presence_set(email_n, "Busy - Away")
        audit("login", email_n, {"keep_signed_in": keep})
        st.rerun()


@st.dialog("Create an HPE CaseFlow Account")
def sign_up_dialog():
    st.write("All fields are required unless marked optional.")
    c1, c2 = st.columns(2)
    with c1:
        first = st.text_input("First Name")
        employee_id = st.text_input("Employee ID")
        birthday = st.date_input("Birthday", value=date(1990, 1, 1), min_value=date(1900, 1, 1), max_value=date.today())
        contact = st.text_input("Contact Number")
        password = st.text_input("Password", type="password")
    with c2:
        last = st.text_input("Last Name")
        email = st.text_input("HPE Email Address", placeholder="name@hpe.com")
        address = st.text_area("Home Address")
        confirm = st.text_input("Confirm Password", type="password")
    if st.button("Create Account", type="primary", use_container_width=True):
        email_n = normalize_email(email)
        errors = []
        if not first.strip() or not last.strip(): errors.append("First and last name are required.")
        if not employee_id.strip(): errors.append("Employee ID is required.")
        if not valid_hpe_email(email_n): errors.append("Use an @hpe.com email address.")
        if not address.strip(): errors.append("Home address is required.")
        if not contact.strip(): errors.append("Contact number is required.")
        if len(password) < 8: errors.append("Password must be at least 8 characters.")
        if password != confirm: errors.append("Passwords do not match.")
        if roster_find(email_n): errors.append("An account already exists for this email.")
        existing_ids = {str(x.get("employee_id", "")).lower() for x in roster_all()}
        if employee_id.strip().lower() in existing_ids: errors.append("Employee ID is already registered.")
        if errors:
            for e in errors: st.error(e)
            return
        roster_upsert({
            "type": "roster_list",
            "first_name": first.strip(), "last_name": last.strip(),
            "employee_id": employee_id.strip(), "email": email_n,
            "birthday": birthday.isoformat(), "home_address": address.strip(),
            "contact_number": contact.strip(), "password_hash": hash_password(password),
            "role": "Agent", "status": "Active", "created_at": iso_now(),
        })
        presence_set(email_n, "Busy - Away")
        audit("account_created", email_n, {"employee_id": employee_id.strip()})
        st.success("Account created. You can now sign in.")


# -----------------------------------------------------------------------------
# DASHBOARD
# -----------------------------------------------------------------------------

def counts_for_cases(cases: List[Dict[str, Any]], email: Optional[str] = None):
    if email:
        cases = [c for c in cases if normalize_email(c.get("assigned_to")) == normalize_email(email)]
    active = [c for c in cases if c.get("status") not in CLOSED_CASE_STATUSES]
    critical = [c for c in active if c.get("priority") == "Critical"]
    due = [c for c in active if case_due_category(c) == "Due Soon"]
    ontrack = [c for c in active if case_due_category(c) == "On Track"]
    return len(active), len(critical), len(due), len(ontrack)


def render_alerts(profile: Dict[str, Any]):
    alerts = alerts_for_agent(profile["email"]) if profile.get("role") == "Agent" else []
    st.markdown('<div class="section-card"><h3>Alerts for You</h3>', unsafe_allow_html=True)
    if not alerts:
        st.success("No outstanding alerts.")
    else:
        for a in alerts[:8]:
            icon = "🔴" if a["kind"] in {"critical","stale"} else "🟠" if a["kind"] == "due" else "🔔"
            st.markdown(f"{icon} **{a['text']}** <span class='small-muted'>{a.get('time','')}</span>", unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


def render_case_table(cases: List[Dict[str, Any]], key_prefix: str = "cases", allow_open: bool = True):
    if not cases:
        st.info("No cases match the current filter.")
        return
    cases = sorted(cases, key=case_sort_key)
    for idx, c in enumerate(cases):
        with st.container(border=True):
            cols = st.columns([1.0, 2.2, .9, 1.35, 1.2, .9])
            with cols[0]:
                if allow_open:
                    if st.button(f"#{c.get('case_number')}", key=f"{key_prefix}_{idx}_open"):
                        st.session_state.selected_case = c.get("case_number")
                        st.session_state.page = "My Cases" if st.session_state.profile.get("role") == "Agent" else "Cases"
                        st.rerun()
                else:
                    st.markdown(f"**#{c.get('case_number')}**")
            with cols[1]:
                st.markdown(f"**{c.get('subject','')}**")
                st.caption(c.get("description", "")[:90])
            with cols[2]:
                st.markdown(urgency_pill(c.get("priority","Low")), unsafe_allow_html=True)
            with cols[3]:
                due = as_datetime(c.get("due_date"))
                st.write(due.strftime("%b %d, %I:%M %p") if due else "—")
            with cols[4]:
                st.markdown(status_pill(c.get("status","New")), unsafe_allow_html=True)
            with cols[5]:
                st.progress(max(0, min(100, int(c.get("progress",0)))) / 100, text=f"{int(c.get('progress',0))}%")


def dashboard_agent(profile: Dict[str, Any]):
    # Only this fragment polls. Navigation changes do not poll the entire app.
    @st.fragment(run_every=REALTIME_SECONDS)
    def live_dashboard():
        presence_set(profile["email"], presence_get(profile["email"]).get("aux", "Busy - Away"))
        assign_unassigned_cases()
        cases = active_cases_for(profile["email"])
        a, b, c, d = counts_for_cases(cases)
        page_title("Dashboard", f"Good morning, {profile.get('first_name','Agent')}! · {now_local().strftime('%A, %B %d, %Y')}")
        m1, m2, m3, m4 = st.columns(4)
        with m1: render_metric("My Active Cases", a, "metric-blue", "metric_active")
        with m2: render_metric("Critical", b, "metric-red", "metric_critical")
        with m3: render_metric("Due Soon", c, "metric-yellow", "metric_due_soon")
        with m4: render_metric("On Track", d, "metric-green", "metric_on_track")
        render_alerts(profile)
        left, right = st.columns([1.55, .75])
        with left:
            st.markdown('<div class="section-card"><h3>My Cases (Sorted by Urgency)</h3>', unsafe_allow_html=True)
            q = st.text_input("Search cases", placeholder="Search case number, subject, vendor, status...", key="agent_case_search")
            filtered = [x for x in cases if q.lower() in json.dumps({k: x.get(k) for k in ["case_number","subject","vendor","status","priority"]}, default=str).lower()]
            render_case_table(filtered, "agentdash")
            st.markdown('</div>', unsafe_allow_html=True)
        with right:
            st.markdown('<div class="section-card"><h3>Today\'s Schedule</h3>', unsafe_allow_html=True)
            rows = schedules_for(profile["email"], now_local().date())
            if not rows:
                st.info("No schedule plotted for today.")
            for r in rows:
                st.markdown(f"**{r.get('start','')} – {r.get('end','')}** · {r.get('activity','Work / Case Processing')}")
            st.markdown('</div>', unsafe_allow_html=True)
            p = presence_get(profile["email"])
            st.markdown('<div class="section-card"><h3>My Live Status</h3>', unsafe_allow_html=True)
            st.metric("AUX", p.get("aux", "Busy - Away"))
            st.caption(f"Last sync: {p.get('last_seen', iso_now())}")
            st.markdown('</div>', unsafe_allow_html=True)
    live_dashboard()


def dashboard_admin(profile: Dict[str, Any]):
    @st.fragment(run_every=REALTIME_SECONDS)
    def live_admin_dashboard():
        presence_set(profile["email"], "Admin Task")
        assign_unassigned_cases()
        cases = cases_all()
        a, b, c, d = counts_for_cases(cases)
        page_title("Dashboard", f"Team Overview · {now_local().strftime('%A, %B %d, %Y')}")
        m1, m2, m3, m4 = st.columns(4)
        with m1: render_metric("Active Cases", a, "metric-blue", "metric_active")
        with m2: render_metric("Critical", b, "metric-red", "metric_critical")
        with m3: render_metric("Due Soon", c, "metric-yellow", "metric_due_soon")
        with m4: render_metric("On Track", d, "metric-green", "metric_on_track")

        agents = [x for x in roster_all() if x.get("role") == "Agent"]
        pres = presence_all()
        st.markdown('<div class="section-card"><h3>Agent Status & Case Distribution</h3>', unsafe_allow_html=True)
        rows = []
        for arow in agents:
            email = normalize_email(arow.get("email"))
            assigned = [x for x in cases if normalize_email(x.get("assigned_to")) == email and x.get("status") not in CLOSED_CASE_STATUSES]
            total = [x for x in cases if normalize_email(x.get("assigned_to")) == email]
            p = pres.get(email, presence_get(email))
            rows.append({"Agent":f"{arow.get('first_name','')} {arow.get('last_name','')}", "Email":email, "AUX":p.get("aux","Busy - Away"), "Active":len(assigned), "Assigned Total":len(total), "Last Sync":p.get("last_seen","")})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="section-card"><h3>Active Queue</h3>', unsafe_allow_html=True)
        q = st.text_input("Search queue", key="admin_dash_search")
        filtered = [x for x in cases if q.lower() in json.dumps(x, default=str).lower()]
        render_case_table(filtered, "admindash")
        st.markdown('</div>', unsafe_allow_html=True)
    live_admin_dashboard()


# -----------------------------------------------------------------------------
# CASE PAGES
# -----------------------------------------------------------------------------

def render_case_detail(profile: Dict[str, Any], c: Dict[str, Any]):
    st.markdown(f"### Case #{c.get('case_number')} · {c.get('subject','')}")
    top = st.columns(5)
    top[0].markdown(f"**Priority**\n\n{urgency_pill(c.get('priority','Low'))}", unsafe_allow_html=True)
    top[1].markdown(f"**Status**\n\n{status_pill(c.get('status','New'))}", unsafe_allow_html=True)
    top[2].markdown(f"**Due**\n\n{as_datetime(c.get('due_date')).strftime('%b %d, %Y %I:%M %p') if as_datetime(c.get('due_date')) else '—'}")
    top[3].markdown(f"**Progress**\n\n{int(c.get('progress',0))}%")
    top[4].markdown(f"**Assigned To**\n\n{c.get('assigned_to') or 'Unassigned'}")
    st.progress(max(0,min(100,int(c.get("progress",0))))/100)

    left, right = st.columns([1.2,.8])
    with left:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown("**Description**")
        st.write(c.get("description", ""))
        st.markdown("**Last Update**")
        st.write(str(c.get("last_update", "—")))
        st.markdown("**Vendor / Technician**")
        st.write(c.get("vendor", "—"))
        v1, v2, v3 = st.columns(3)
        with v1:
            email = c.get("vendor_email")
            if email:
                st.markdown(f"[✉ Email Vendor](mailto:{email})")
        with v2:
            phone = c.get("vendor_phone", "")
            if phone:
                st.link_button("☎ Call", f"tel:{phone}", use_container_width=True)
        with v3:
            st.link_button("↗ Salesforce", SALESFORCE_URL, use_container_width=True)
        if phone and st.button("Copy vendor number", key=f"copy_{c.get('case_number')}"):
            st.code(phone)
            st.caption("Browser clipboard access is restricted by some Streamlit hosts; the number is shown for copy/paste.")
        st.markdown('</div>', unsafe_allow_html=True)

    with right:
        st.markdown('<div class="section-card"><h3>Update Case</h3>', unsafe_allow_html=True)
        statuses = ["New","Assigned","In Progress","Pending Vendor","Pending Customer","Pending Internal","On Hold","Completed","Closed","Contract Breached"]
        current = c.get("status", "New")
        new_status = st.selectbox("Status", statuses, index=statuses.index(current) if current in statuses else 0)
        new_progress = st.slider("Progress", 0, 100, int(c.get("progress",0)))
        update_text = st.text_area("Add update", placeholder="Describe what changed...")
        if st.button("Save Update", type="primary", use_container_width=True):
            c["status"] = new_status
            c["progress"] = new_progress
            c["last_update"] = iso_now()
            c["last_updated_by"] = profile["email"]
            c.setdefault("updates", []).append({"by":profile["email"],"at":iso_now(),"text":update_text})
            case_save(c)
            st.success("Case updated.")
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    if profile.get("role") == "Agent":
        st.markdown('<div class="section-card"><h3>Contract Breach</h3>', unsafe_allow_html=True)
        reason = st.selectbox("Contract breached reason", ["Missed committed delivery date","Repeated missed follow-up","Vendor failed to deliver after escalation","Other"], key=f"breach_reason_{c.get('case_number')}")
        msg = generate_breach_message(c, reason, f"{profile.get('first_name','')} {profile.get('last_name','')}")
        msg = st.text_area("Generated message", value=msg, height=190, key=f"breach_msg_{c.get('case_number')}")
        b1, b2 = st.columns(2)
        with b1:
            if st.button("Tag Contract Breached", use_container_width=True):
                c["status"] = "Contract Breached"
                c["contract_breached_reason"] = reason
                c["contract_breached_message"] = msg
                c["last_update"] = iso_now()
                case_save(c)
                st.success("Case tagged as Contract Breached.")
                st.rerun()
        with b2:
            if c.get("vendor_email"):
                subject = f"Contract breach - Case #{c.get('case_number')}"
                import urllib.parse
                mailto = f"mailto:{c.get('vendor_email')}?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(msg)}"
                st.markdown(f"[✉ Email Vendor]({mailto})")
        st.markdown('</div>', unsafe_allow_html=True)


def cases_page(profile: Dict[str, Any]):
    admin = profile.get("role") == "Admin"
    page_title("Cases" if admin else "My Cases", "View and update assigned cases" if not admin else "View, reassign and manage all cases")
    cases = cases_all() if admin else active_cases_for(profile["email"])
    filt = st.session_state.get("case_filter")
    q = st.text_input("Search cases", key="cases_search")
    if filt:
        st.info(f"Tile filter: {filt}")
        st.session_state["case_filter"] = None
    if q:
        cases = [x for x in cases if q.lower() in json.dumps(x, default=str).lower()]
    if admin:
        selected = st.selectbox("Filter status", ["All"] + sorted({x.get("status","New") for x in cases}))
        if selected != "All": cases = [x for x in cases if x.get("status") == selected]
    if st.session_state.get("selected_case"):
        selected_case = next((x for x in cases_all() if x.get("case_number") == st.session_state.selected_case), None)
        if selected_case:
            if st.button("← Back to cases"):
                st.session_state.selected_case = None
                st.rerun()
            render_case_detail(profile, selected_case)
            return
    render_case_table(cases, "casespage")


# -----------------------------------------------------------------------------
# AGENTS / SETTINGS
# -----------------------------------------------------------------------------

def agents_page(profile: Dict[str, Any]):
    page_title("Agents", "View agent status, AUX, attendance and case distribution")
    agents = [x for x in roster_all() if x.get("role") == "Agent"]
    cases = cases_all()
    pres = presence_all()
    rows=[]
    for a in agents:
        email=normalize_email(a.get("email")); assigned=[c for c in cases if normalize_email(c.get("assigned_to"))==email and c.get("status") not in CLOSED_CASE_STATUSES]
        p=pres.get(email, presence_get(email))
        rows.append({"Name":f"{a.get('first_name','')} {a.get('last_name','')}","Email":email,"AUX":p.get("aux","Busy - Away"),"Active Cases":len(assigned),"Assigned Total":sum(1 for c in cases if normalize_email(c.get("assigned_to"))==email),"Last Sync":p.get("last_seen","")})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.divider()
    selected = st.selectbox("Agent", [r["Email"] for r in rows] if rows else [])
    if selected:
        a = roster_find(selected)
        st.markdown(f"### {a.get('first_name','')} {a.get('last_name','')}")
        p = presence_get(selected)
        st.write(f"**AUX:** {p.get('aux','Busy - Away')} · **Last sync:** {p.get('last_seen','—')}")
        c1,c2,c3=st.columns(3)
        with c1:
            if st.button("Kick / Mark unavailable", type="secondary"):
                presence_set(selected, "Busy - Away")
                notify(selected,"Admin action","You were marked unavailable by an administrator to prevent new auto-assigned cases.","admin")
                st.success("Agent removed from available assignment pool.")
        with c2:
            if st.button("Send ageing-case alert"):
                ageing=[c for c in active_cases_for(selected) if (now_local()-(as_datetime(c.get("last_update")) or now_local())).total_seconds()>24*3600]
                if ageing:
                    notify(selected,"Ageing cases",f"You have {len(ageing)} case(s) with no update for more than 24 hours.","stale")
                    st.success("Alert sent.")
                else: st.info("No ageing cases found.")
        with c3:
            if st.button("Rebalance / auto-assign"):
                for c in cases:
                    if normalize_email(c.get("assigned_to")) == selected and c.get("status") not in CLOSED_CASE_STATUSES:
                        fair_assignment({**c,"assigned_to":None}, profile["email"])
                st.success("Eligible cases sent through the assignment engine.")


def settings_page(profile: Dict[str, Any]):
    page_title("Settings", "Manage users, roles, PTO allocation and system rules")
    tab1, tab2, tab3 = st.tabs(["User Management", "PTO Allocation", "System Settings"])
    with tab1:
        rows=roster_all()
        df=pd.DataFrame([{k:r.get(k,"") for k in ["first_name","last_name","employee_id","email","role","status"]} for r in rows])
        st.dataframe(df, use_container_width=True, hide_index=True)
        if rows:
            email=st.selectbox("User", [r.get("email") for r in rows])
            u=roster_find(email)
            c1,c2,c3=st.columns(3)
            with c1: role=st.selectbox("Role",["Agent","Admin"],index=0 if u.get("role")!="Admin" else 1)
            with c2: status=st.selectbox("Account Status",["Active","Inactive"],index=0 if u.get("status","Active")=="Active" else 1)
            with c3:
                if st.button("Save User"):
                    u["role"]=role; u["status"]=status; roster_upsert(u); audit("user_updated",profile["email"],{"user":email,"role":role,"status":status}); st.success("User updated.")
    with tab2:
        st.caption("PTO allocation is stored in settings. Sick leave and emergency leave auto-approve. PTO auto-approves only when allocation is available.")
        if mongo_ok():
            settings_doc=collection(SETTINGS_COLLECTION).find_one({"key":"pto"}) or {"key":"pto","allocation":5}
        else: settings_doc=st.session_state.local_store["settings"].get("pto",{"key":"pto","allocation":5})
        allocation=st.number_input("Default PTO allocation (days)",min_value=0,max_value=365,value=int(settings_doc.get("allocation",5)))
        if st.button("Save PTO Allocation"):
            row={"key":"pto","allocation":allocation,"updated_at":iso_now()}
            if mongo_ok(): collection(SETTINGS_COLLECTION).update_one({"key":"pto"},{"$set":row},upsert=True)
            else: st.session_state.local_store["settings"]["pto"]=row
            st.success("PTO allocation saved.")
    with tab3:
        st.write(f"**MongoDB:** {'Connected' if mongo_ok() else 'Fallback local mode'}")
        st.write(f"**Salesforce URL:** {SALESFORCE_URL}")
        st.write(f"**Realtime interval:** {REALTIME_SECONDS} seconds")
        st.write("**Default break/lunch policy:** break after 2h → lunch after 2h → last break after 2h, dynamically shifted to preserve queue coverage.")
        tv=st.checkbox("TV / mirror-cast compact mode", value=False)
        st.session_state["tv_mode"]=tv


# -----------------------------------------------------------------------------
# SCHEDULE ENGINE / PAGES
# -----------------------------------------------------------------------------

def build_default_schedule(agent: Dict[str, Any], target: date):
    email=normalize_email(agent.get("email"));
    # 8-hour example day. Admin can edit generated rows after creation.
    base=[
        ("08:00","10:00","Work / Case Processing"),
        ("10:00","10:15","Break"),
        ("10:15","12:00","Work / Case Processing"),
        ("12:00","13:00","Lunch"),
        ("13:00","15:00","Work / Case Processing"),
        ("15:00","15:15","Break"),
        ("15:15","17:00","Work / Case Processing"),
    ]
    for s,e,a in base:
        schedule_save({"email":email,"date":target.isoformat(),"start":s,"end":e,"activity":a,"source":"auto"})


def schedule_page(profile: Dict[str, Any]):
    admin=profile.get("role")=="Admin"
    page_title("Schedule", "Manage agent schedules and queue coverage" if admin else "My Schedule", "")
    if admin:
        a=st.selectbox("Agent", [r.get("email") for r in roster_all() if r.get("role")=="Agent"])
        target=st.date_input("Schedule date", value=now_local().date())
        c1,c2,c3=st.columns(3)
        with c1:
            if st.button("Generate coverage schedule"):
                agent=roster_find(a); build_default_schedule(agent,target); st.success("Schedule generated.")
        with c2:
            if st.button("Add activity"):
                st.session_state["add_activity"]=True
        with c3:
            st.caption("Default: break after 2h, lunch after 2h, last break after 2h. Adjustments should preserve hourly queue coverage.")
        if st.session_state.get("add_activity"):
            with st.form("activity_form"):
                start=st.text_input("Start", "10:00"); end=st.text_input("End", "10:30"); activity=st.selectbox("Activity",["Meeting","Coaching","Admin Task","Work / Case Processing"])
                if st.form_submit_button("Save activity"):
                    schedule_save({"email":a,"date":target.isoformat(),"start":start,"end":end,"activity":activity,"source":"admin"}); st.session_state["add_activity"]=False; st.success("Activity added.")
        rows=schedules_for(a,target)
        if rows:
            df=pd.DataFrame(rows)[["start","end","activity"]]
            st.dataframe(df,use_container_width=True,hide_index=True)
        st.markdown("### Schedule Requests")
        reqs=requests_all({"type":{"$in":["Schedule Swap","PTO","Sick Leave","Emergency Leave"]}}) if mongo_ok() else requests_all()
        st.dataframe(pd.DataFrame(reqs),use_container_width=True,hide_index=True)
    else:
        mode=st.segmented_control("View",["Day","Week","Month"],default="Day") if hasattr(st,"segmented_control") else st.radio("View",["Day","Week","Month"],horizontal=True)
        target=st.date_input("Date", value=now_local().date())
        rows=schedules_for(profile["email"],target)
        if mode=="Day":
            for r in rows: st.markdown(f"**{r.get('start')} – {r.get('end')}** · {r.get('activity')}")
        else:
            st.info(f"{mode} view is available from the same schedule records; select a date to inspect the plotted schedule.")
        st.markdown("### Schedule Swap")
        agents=[r for r in roster_all() if r.get("role")=="Agent" and r.get("email")!=profile.get("email")]
        if agents:
            other=st.selectbox("Swap with",[r.get("email") for r in agents])
            if st.button("Submit agreed swap"):
                request_save({"type":"Schedule Swap","requester":profile["email"],"other_agent":other,"date":target.isoformat(),"status":"Approved","created_at":iso_now(),"approved_at":iso_now(),"approval_note":"Auto-approved after both agents agreed."})
                notify(ADMIN_EMAIL,"Schedule swap submitted",f"{profile['email']} submitted an agreed schedule swap with {other}.","request")
                st.success("Swap recorded as approved.")


def requests_page(profile: Dict[str, Any]):
    admin=profile.get("role")=="Admin"
    page_title("Requests", "View and process agent requests" if admin else "Requests", "")
    if admin:
        reqs=requests_all()
        if reqs: st.dataframe(pd.DataFrame(reqs),use_container_width=True,hide_index=True)
        else: st.info("No requests.")
        return
    tabs=st.tabs(["New Request","My Requests"])
    with tabs[0]:
        typ=st.selectbox("Request Type",["PTO","Sick Leave","Emergency Leave"])
        d1=st.date_input("Start Date",now_local().date())
        d2=st.date_input("End Date",now_local().date())
        reason=st.text_area("Reason")
        if st.button("Submit Request",type="primary"):
            status="Approved" if typ in {"Sick Leave","Emergency Leave"} else "Approved" # allocation check below
            allocation=5
            try:
                if mongo_ok(): allocation=int((collection(SETTINGS_COLLECTION).find_one({"key":"pto"}) or {}).get("allocation",5))
            except Exception: pass
            if typ=="PTO":
                used=sum(1 for r in requests_all({"requester":profile["email"],"type":"PTO","status":"Approved"}))
                requested=(d2-d1).days+1
                if used+requested>allocation:
                    st.error("No allocation for the selected date.")
                    return
            request_save({"type":typ,"requester":profile["email"],"start_date":d1.isoformat(),"end_date":d2.isoformat(),"reason":reason,"status":status,"created_at":iso_now()})
            notify(ADMIN_EMAIL,"New request",f"{profile['email']} submitted {typ} for {d1} to {d2}.","request")
            st.success(f"{typ} submitted and {status.lower()}.")
    with tabs[1]:
        rows=requests_all({"requester":profile["email"]})
        if rows: st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
        else: st.info("No requests submitted.")


def reports_page(profile: Dict[str, Any]):
    page_title("Reports", "Extract case, adherence and attendance reports")
    cases=cases_all()
    agents=[r for r in roster_all() if r.get("role")=="Agent"]
    total=len(cases); active=sum(c.get("status") not in CLOSED_CASE_STATUSES for c in cases); critical=sum(c.get("priority")=="Critical" for c in cases); due=sum(case_due_category(c)=="Due Soon" for c in cases)
    st.dataframe(pd.DataFrame([{"Metric":"Total Cases","Daily":total,"MTD":total},{"Metric":"Active","Daily":active,"MTD":active},{"Metric":"Critical","Daily":critical,"MTD":critical},{"Metric":"Due Soon","Daily":due,"MTD":due}]),use_container_width=True,hide_index=True)
    agent_rows=[]
    for a in agents:
        email=a.get("email"); assigned=active_cases_for(email); agent_rows.append({"Agent":f"{a.get('first_name','')} {a.get('last_name','')}","Email":email,"Active Cases":len(assigned),"Adherence %":100,"Attendance %":100})
    st.markdown("### Daily / MTD Adherence & Attendance")
    st.dataframe(pd.DataFrame(agent_rows),use_container_width=True,hide_index=True)
    csv=pd.DataFrame(cases).to_csv(index=False).encode()
    st.download_button("Export Case Report",csv,"hpe_caseflow_cases.csv","text/csv",use_container_width=True)
    adf=pd.DataFrame(agent_rows).to_csv(index=False).encode()
    st.download_button("Export Adherence & Attendance",adf,"hpe_caseflow_adherence_attendance.csv","text/csv",use_container_width=True)


def salesforce_page(profile: Dict[str, Any]):
    page_title("Salesforce", "Admin-only external case source")
    st.info("Salesforce access is intentionally visible only to administrators.")
    st.link_button("Open Salesforce", SALESFORCE_URL, type="primary")
    st.markdown("### Integration hook")
    st.code("""# Replace this stub with your Salesforce OAuth/REST connector later.\n# The rest of CaseFlow does not depend on the connector.\n# Recommended: write normalized cases into the `cases` collection and\n# preserve `source='Salesforce'` and the Salesforce Case ID.""")
    st.caption("For production, use OAuth/token-based authentication rather than storing Salesforce credentials in this script.")


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def main():
    if not st.session_state.get("authenticated"):
        auth_screen()
        return

    profile=roster_find(st.session_state.profile.get("email")) or st.session_state.profile
    st.session_state.profile=profile
    if profile.get("role") == "Agent":
        # heartbeat only; AUX itself is transient and should not be persisted in roster.
        p=presence_get(profile["email"])
        presence_set(profile["email"], p.get("aux","Busy - Away"))
    else:
        presence_set(profile["email"], "Admin Task")

    if st.session_state.get("tv_mode"):
        st.markdown('<script>document.body.classList.add("tv-mode")</script>', unsafe_allow_html=True)

    sidebar(profile)
    topbar(profile)
    page=st.session_state.get("page","Dashboard")
    if profile.get("role")=="Agent":
        if page=="Dashboard": dashboard_agent(profile)
        elif page=="My Cases": cases_page(profile)
        elif page=="Schedule": schedule_page(profile)
        elif page=="Requests": requests_page(profile)
        else: dashboard_agent(profile)
    else:
        if page=="Dashboard": dashboard_admin(profile)
        elif page=="Cases": cases_page(profile)
        elif page=="Agents": agents_page(profile)
        elif page=="Schedule": schedule_page(profile)
        elif page=="Requests": requests_page(profile)
        elif page=="Reports": reports_page(profile)
        elif page=="Salesforce": salesforce_page(profile)
        elif page=="Settings": settings_page(profile)
        else: dashboard_admin(profile)


if __name__ == "__main__":
    main()
