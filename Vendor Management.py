"""
HPE CaseFlow
Modern Streamlit case/task management dashboard.

Install:
    pip install -r requirements.txt

MongoDB:
    Set MONGODB_URI in Streamlit secrets or environment.
    The app uses:
        db = client["TeamRoster"]
        roster = db[ROSTER_COLLECTION_NAME]
    Default roster collection: "roster_list"
    Set ROSTER_COLLECTION_NAME="Team Roster Collection" if that is the existing collection.

The current presence/aux state is intentionally stored in a short-lived `presence`
collection so all agent/admin sessions can see it in near-real-time without
polluting the roster record. A TTL index removes stale presence records.

Salesforce:
    Set SALESFORCE_URL in secrets/env when ready. The admin-only Salesforce page
    is already wired as a launch point. The actual API sync is isolated in
    `salesforce_fetch_cases()` so it can be replaced with your OAuth/API code later.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import os
import secrets
from pathlib import Path
import uuid
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import pandas as pd
import streamlit as st
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

# -----------------------------------------------------------------------------
# Page / constants
# -----------------------------------------------------------------------------

st.set_page_config(
    page_title="HPE CaseFlow",
    page_icon="▣",
    layout="wide",
    initial_sidebar_state="collapsed",
)

APP_NAME = "HPE CaseFlow"
DB_NAME = "TeamRoster"
ROSTER_COLLECTION_NAME = os.getenv("ROSTER_COLLECTION_NAME", "roster_list")
SALESFORCE_URL = os.getenv("SALESFORCE_URL", "https://hp.lightning.force.com/")

# Bootstrap administrator requested by the owner.
BOOTSTRAP_ADMIN = {
    "first_name": "Arianne May",
    "last_name": "Escabillas",
    "employee_id": "60187999",
    "email": "arianne-may.escabillas@hpe.com",
    "birthday": "1993-06-17",
    "home_address": "661 Betterlife, Tanzang Luma III, Imus City, Cavite",
    "contact_number": "",
    "role": "admin",
    "password": "Escabillas1993",
}

AUX_OPTIONS = [
    "Active",
    "Break",
    "Lunch",
    "In a Meeting",
    "Coaching",
    "Busy - Away",
    "Unscheduled Break",
    "Admin Task",
]

REGULAR_DEFAULT_AUX = "Busy - Away"
ADMIN_DEFAULT_AUX = "Admin Task"

CASE_STATUSES = [
    "New",
    "Assigned",
    "In Progress",
    "Pending Vendor",
    "Pending Customer",
    "On Hold",
    "Completed",
    "Closed",
    "Contract Breached",
]

PRIORITIES = ["Critical", "High", "Medium", "Low"]

BREACH_REASONS = {
    "Vendor missed committed delivery date":
        "The vendor did not meet the committed delivery date for this case.",
    "Vendor failed to provide an agreed update":
        "The vendor failed to provide the agreed status update for this case.",
    "Vendor failed to meet SLA":
        "The vendor did not meet the applicable service-level commitment for this case.",
    "Repeated vendor delivery failure":
        "The vendor has failed to deliver after documented follow-up attempts.",
}

# -----------------------------------------------------------------------------
# Styling — modeled closely on the supplied reference images
# -----------------------------------------------------------------------------

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
  --navy:#123B59;
  --navy2:#0B2F4A;
  --blue:#0B73C9;
  --blue2:#168BD0;
  --teal:#00A98F;
  --ink:#18324A;
  --muted:#60758A;
  --line:#DCE5ED;
  --bg:#F4F7FA;
  --card:#FFFFFF;
  --critical:#E53935;
  --high:#F28C28;
  --medium:#E4A61A;
  --low:#43A5D8;
  --good:#19A974;
  --shadow:0 5px 18px rgba(20,54,82,.10);
}

html, body, [class*="css"] {
  font-family: Inter, Arial, sans-serif;
}
.stApp { background: var(--bg); color: var(--ink); }
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer, .stDeployButton { display:none !important; }
[data-testid="stToolbar"] { display:none !important; }
[data-testid="stDecoration"] { display:none !important; }
.block-container {
  max-width: 100%;
  padding: .8rem 1rem 1.5rem 1rem;
}
section[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #0A304B 0%, #0B3C5E 100%);
  min-width: 245px;
  max-width: 245px;
}
section[data-testid="stSidebar"] > div { padding-top: .5rem; }
section[data-testid="stSidebar"] .stButton button {
  background: transparent;
  color:#F5FAFF;
  border:0;
  text-align:left;
  border-radius:8px;
  padding:.55rem .8rem;
  font-weight:600;
}
section[data-testid="stSidebar"] .stButton button:hover {
  background:rgba(255,255,255,.10);
  border:0;
}
section[data-testid="stSidebar"] .stButton button[kind="primary"] {
  background:#0D82CE;
  color:white;
}
div[data-testid="stMetric"] {
  background:white;
  border:1px solid var(--line);
  border-radius:12px;
  padding:.65rem .8rem;
  box-shadow:var(--shadow);
}
.case-card {
  background:#fff;
  border:1px solid var(--line);
  border-radius:12px;
  padding:.7rem .85rem;
  margin:.35rem 0;
  box-shadow:0 2px 8px rgba(18,59,89,.05);
}
.topbar {
  background:#fff;
  border-bottom:1px solid var(--line);
  padding:.45rem .75rem;
  margin:-.8rem -1rem .9rem -1rem;
}
.page-title {
  color:var(--navy);
  font-size:1.55rem;
  font-weight:800;
  margin:0;
}
.page-subtitle { color:var(--muted); margin-top:.1rem; }
.section-title { color:var(--navy); font-size:1.05rem; font-weight:800; margin:.5rem 0; }
.alert-box {
  background:#FFF7E8;
  border:1px solid #F2D99E;
  border-radius:12px;
  padding:.75rem 1rem;
}
.badge {
  display:inline-block;
  border-radius:999px;
  padding:2px 9px;
  font-size:.72rem;
  font-weight:700;
}
.badge-critical { background:#FFE2E3; color:#C62828; }
.badge-high { background:#FFE9D8; color:#B85C00; }
.badge-medium { background:#FFF3C9; color:#8A6200; }
.badge-low { background:#E0F1FB; color:#1476A6; }
.badge-good { background:#DCF6E9; color:#087C4B; }
.badge-blue { background:#DDEFFF; color:#1269A5; }
.kpi-card {
  border-radius:12px;
  padding:1rem;
  min-height:105px;
  border:1px solid transparent;
}
.kpi-card .num { font-size:2rem; line-height:1; font-weight:800; }
.kpi-card .label { font-size:.82rem; font-weight:600; margin-top:.4rem; }
.kpi-active { background:#E5F2FC; color:#1170B6; border-color:#CFE7F8; }
.kpi-critical { background:#FFE5E6; color:#C52B31; border-color:#FFD0D2; }
.kpi-due { background:#FFF2CC; color:#8D6500; border-color:#F5E1A4; }
.kpi-track { background:#DCF6E8; color:#0A8250; border-color:#C5EFD9; }
.login-shell {
  min-height:92vh;
  display:flex;
  align-items:center;
  justify-content:center;
  background:linear-gradient(135deg,#6EA3D0 0%,#4B7FAE 45%,#2B5E87 100%);
  border-radius:18px;
  padding:2.2rem;
}
.login-card {
  width:min(1120px,96vw);
  min-height:760px;
  display:grid;
  grid-template-columns: 39% 61%;
  overflow:hidden;
  border-radius:16px;
  background:#fff;
  box-shadow:0 20px 60px rgba(9,35,57,.25);
}
.login-brand {
  color:white;
  padding:2.3rem 2rem;
  position:relative;
  overflow:hidden;
  background:linear-gradient(180deg,#063F68 0%,#0A3151 100%);
}
.login-brand:after {
  content:"";
  position:absolute; inset:0;
  background-image:url("__LOGIN_PANEL__");
  background-position:center bottom;
  background-size:cover;
  opacity:.55;
  mix-blend-mode:screen;
}
.login-brand > * { position:relative; z-index:2; }
.hpe-mark { color:#00A98F; font-size:2.2rem; font-weight:900; line-height:.7; }
.hpe-name { font-size:1.35rem; font-weight:800; margin-top:.8rem; line-height:1.0; }
.hpe-line { width:92px; height:3px; background:#00A98F; margin:1.6rem 0 1.1rem; }
.login-brand h1 { font-size:2.1rem; margin:.1rem 0 .7rem; }
.login-brand p { font-size:1.05rem; color:#EAF4FB; line-height:1.45; }
.login-features { margin-top:2.3rem; display:grid; gap:1.3rem; }
.login-feature b { display:block; font-size:.95rem; }
.login-feature span { display:block; color:#C9DCEA; font-size:.78rem; margin-top:.15rem; }
.login-panel { padding:3rem 3.1rem; background:#fff; }
.login-panel h2 { color:var(--navy); font-size:2.05rem; margin:.5rem 0 .3rem; }
.login-panel .lead { color:var(--muted); margin-bottom:1.8rem; }
@media (max-width:900px) {
  .login-card { grid-template-columns:1fr; }
  .login-brand { min-height:360px; }
  .login-panel { padding:2rem; }
}
div[data-testid="stPopover"] > div { z-index: 1000; }
.profile-pill button {
  border-radius:999px !important;
}
.small-muted { color:#71879A; font-size:.78rem; }
.full-height-table { overflow-x:auto; }
</style>
""".replace("__LOGIN_PANEL__", "data:image/png;base64,PLACEHOLDER"),
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def now_utc() -> datetime:
    return datetime.utcnow()


def today_utc_date() -> date:
    return now_utc().date()


def safe_str(v: Any) -> str:
    return "" if v is None else str(v)


def parse_date(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if not v:
        return None
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def parse_dt(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", ""))
    except Exception:
        return None


def iso_now() -> str:
    return now_utc().isoformat(timespec="seconds")


def password_hash(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 180_000)
    return f"pbkdf2_sha256$180000${salt.hex()}${dk.hex()}"


def password_verify(password: str, encoded: str) -> bool:
    try:
        algo, rounds, salt_hex, digest_hex = encoded.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(dk.hex(), digest_hex)
    except Exception:
        return False


def html_badge(text: str, kind: str) -> str:
    cls = {
        "Critical": "badge-critical",
        "High": "badge-high",
        "Medium": "badge-medium",
        "Low": "badge-low",
        "Completed": "badge-good",
        "Closed": "badge-good",
        "In Progress": "badge-blue",
        "Assigned": "badge-blue",
        "Active": "badge-good",
    }.get(kind, "badge-blue")
    return f'<span class="badge {cls}">{html.escape(text)}</span>'


def urgency_rank(case: Dict[str, Any]) -> Tuple[int, float]:
    priority_rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    due = parse_dt(case.get("due_date"))
    due_ts = due.timestamp() if due else float("inf")
    return priority_rank.get(case.get("priority"), 9), due_ts


def is_active_case(case: Dict[str, Any]) -> bool:
    return case.get("status") not in ("Completed", "Closed")


def due_soon(case: Dict[str, Any], hours: int = 24) -> bool:
    due = parse_dt(case.get("due_date"))
    if not due or not is_active_case(case):
        return False
    delta = due - now_utc()
    return timedelta(0) <= delta <= timedelta(hours=hours)


def is_stale(case: Dict[str, Any], hours: int = 24) -> bool:
    if not is_active_case(case):
        return False
    updated = parse_dt(case.get("last_update"))
    return bool(updated and now_utc() - updated >= timedelta(hours=hours))


def case_bucket(case: Dict[str, Any]) -> str:
    if case.get("priority") == "Critical":
        return "Critical"
    if due_soon(case):
        return "Due Soon"
    return "On Track"


def clean_doc(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return doc
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return out


# -----------------------------------------------------------------------------
# Mongo connection and repositories
# -----------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def get_mongo_client() -> MongoClient:
    uri = None
    try:
        uri = st.secrets.get("MONGODB_URI")
    except Exception:
        uri = None
    uri = uri or os.getenv("MONGODB_URI")
    if not uri:
        raise RuntimeError(
            "MONGODB_URI is not configured. Add it to .streamlit/secrets.toml "
            "or the MONGODB_URI environment variable."
        )
    return MongoClient(
        uri,
        serverSelectionTimeoutMS=4000,
        connectTimeoutMS=4000,
        socketTimeoutMS=8000,
        retryWrites=True,
    )


@st.cache_resource(show_spinner=False)
def get_db():
    client = get_mongo_client()
    db = client[DB_NAME]
    # Index creation is cached so it is not repeated on every interaction.
    # Be defensive with existing collections: if an older deployment contains
    # duplicate data, do not make the whole application fail during startup.
    try:
        db[ROSTER_COLLECTION_NAME].create_index([("email", ASCENDING)], unique=True)
    except PyMongoError:
        db[ROSTER_COLLECTION_NAME].create_index([("email", ASCENDING)])
    try:
        db["cases"].create_index([("case_id", ASCENDING)], unique=True)
    except PyMongoError:
        db["cases"].create_index([("case_id", ASCENDING)])
    db["cases"].create_index([("assigned_to", ASCENDING), ("status", ASCENDING)])
    db["cases"].create_index([("due_date", ASCENDING)])
    try:
        db["presence"].create_index([("email", ASCENDING)], unique=True)
    except PyMongoError:
        db["presence"].create_index([("email", ASCENDING)])
    try:
        db["presence"].create_index([("last_seen", ASCENDING)], expireAfterSeconds=90)
    except PyMongoError:
        pass
    db["schedule"].create_index([("email", ASCENDING), ("date", ASCENDING)])
    db["requests"].create_index([("email", ASCENDING), ("created_at", DESCENDING)])
    db["notifications"].create_index([("email", ASCENDING), ("read", ASCENDING)])
    db["audit_log"].create_index([("created_at", DESCENDING)])
    try:
        db["settings"].create_index([("key", ASCENDING)], unique=True)
    except PyMongoError:
        db["settings"].create_index([("key", ASCENDING)])
    return db


def db_ok(db) -> bool:
    try:
        db.command("ping")
        return True
    except Exception:
        return False


def seed_admin(db):
    roster = db[ROSTER_COLLECTION_NAME]
    email = BOOTSTRAP_ADMIN["email"].lower()
    existing = roster.find_one({"email": email})
    if existing:
        # Keep an existing password/profile untouched; only ensure admin role.
        if existing.get("role") != "admin":
            roster.update_one({"email": email}, {"$set": {"role": "admin"}})
        return
    doc = {
        "first_name": BOOTSTRAP_ADMIN["first_name"],
        "last_name": BOOTSTRAP_ADMIN["last_name"],
        "employee_id": BOOTSTRAP_ADMIN["employee_id"],
        "email": email,
        "birthday": BOOTSTRAP_ADMIN["birthday"],
        "home_address": BOOTSTRAP_ADMIN["home_address"],
        "contact_number": BOOTSTRAP_ADMIN["contact_number"],
        "role": "admin",
        "password_hash": password_hash(BOOTSTRAP_ADMIN["password"]),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "status": "Active",
    }
    roster.insert_one(doc)


def find_user(db, email: str) -> Optional[Dict[str, Any]]:
    return clean_doc(db[ROSTER_COLLECTION_NAME].find_one({"email": email.lower()}))


def create_user(db, data: Dict[str, Any]) -> Tuple[bool, str]:
    data = dict(data)
    data["email"] = data["email"].strip().lower()
    data["password_hash"] = password_hash(data.pop("password"))
    data["role"] = "regular"
    data["status"] = "Active"
    data["created_at"] = iso_now()
    data["updated_at"] = iso_now()
    try:
        db[ROSTER_COLLECTION_NAME].insert_one(data)
        return True, "Account created successfully."
    except DuplicateKeyError:
        return False, "An account with that HPE email already exists."
    except Exception as e:
        return False, f"Unable to create account: {e}"


def save_user_profile(db, email: str, updates: Dict[str, Any]):
    updates["updated_at"] = iso_now()
    db[ROSTER_COLLECTION_NAME].update_one({"email": email}, {"$set": updates})


def list_agents(db) -> List[Dict[str, Any]]:
    return [clean_doc(x) for x in db[ROSTER_COLLECTION_NAME].find(
        {}, {"password_hash": 0}
    ).sort([("last_name", ASCENDING), ("first_name", ASCENDING)])]


def upsert_presence(db, user: Dict[str, Any], aux: str, kicked_until=None):
    now = now_utc()
    doc = {
        "email": user["email"].lower(),
        "employee_id": user.get("employee_id"),
        "name": f'{user.get("first_name","")} {user.get("last_name","")}'.strip(),
        "role": user.get("role", "regular"),
        "aux": aux,
        "last_seen": now,
        "session_id": st.session_state.get("session_id"),
    }
    if kicked_until:
        doc["kicked_until"] = kicked_until
    db["presence"].update_one(
        {"email": user["email"].lower()},
        {"$set": doc},
        upsert=True,
    )


def get_presence(db, email: str) -> Optional[Dict[str, Any]]:
    return clean_doc(db["presence"].find_one({"email": email.lower()}))


def list_presence(db) -> List[Dict[str, Any]]:
    cutoff = now_utc() - timedelta(seconds=90)
    return [clean_doc(x) for x in db["presence"].find({"last_seen": {"$gte": cutoff}})]


def set_presence_aux(db, email: str, aux: str):
    db["presence"].update_one(
        {"email": email.lower()},
        {"$set": {"aux": aux, "last_seen": now_utc()}},
        upsert=True,
    )


def eligible_agent_rows(db) -> List[Dict[str, Any]]:
    agents = list_agents(db)
    pres = {x["email"]: x for x in list_presence(db)}
    rows = []
    for agent in agents:
        if agent.get("role") != "regular":
            continue
        p = pres.get(agent["email"].lower())
        if not p:
            continue
        if p.get("kicked_until") and p["kicked_until"] > now_utc():
            continue
        if p.get("aux") != "Active":
            continue
        active = db["cases"].count_documents({
            "assigned_to": agent["email"].lower(),
            "status": {"$nin": ["Completed", "Closed"]},
        })
        assigned_today = db["cases"].count_documents({
            "assigned_to": agent["email"].lower(),
            "assigned_date": {"$regex": f"^{today_utc_date().isoformat()}"},
        })
        rows.append({
            "agent": agent,
            "active": active,
            "assigned_today": assigned_today,
            "last_assigned_at": agent.get("last_assigned_at") or "",
        })
    return rows


def choose_agent(db) -> Optional[Dict[str, Any]]:
    rows = eligible_agent_rows(db)
    if not rows:
        return None
    rows.sort(key=lambda r: (
        r["assigned_today"],
        r["active"],
        r["last_assigned_at"] or "1970-01-01",
        r["agent"].get("email", ""),
    ))
    return rows[0]["agent"]


def auto_assign_case(db, case_id: str) -> Optional[str]:
    case = db["cases"].find_one({"case_id": case_id})
    if not case or case.get("assigned_to"):
        return case.get("assigned_to")
    agent = choose_agent(db)
    if not agent:
        db["cases"].update_one(
            {"case_id": case_id},
            {"$set": {"assignment_status": "Waiting for available agent",
                      "updated_at": iso_now()}},
        )
        return None

    email = agent["email"].lower()
    assigned = db["cases"].find_one_and_update(
        {"case_id": case_id, "assigned_to": {"$in": [None, ""]}},
        {"$set": {
            "assigned_to": email,
            "assigned_name": f'{agent.get("first_name","")} {agent.get("last_name","")}'.strip(),
            "assigned_at": iso_now(),
            "assigned_date": iso_now(),
            "assignment_status": "Auto Assigned",
            "status": "Assigned",
            "updated_at": iso_now(),
        }},
        return_document=ReturnDocument.AFTER,
    )
    if assigned:
        db[ROSTER_COLLECTION_NAME].update_one(
            {"email": email},
            {"$set": {"last_assigned_at": iso_now()}},
        )
        db["notifications"].insert_one({
            "email": email,
            "type": "assignment",
            "title": "New case auto-assigned",
            "message": f'Case {case_id} has been assigned to you.',
            "case_id": case_id,
            "read": False,
            "created_at": iso_now(),
        })
    return email


def insert_case(db, case: Dict[str, Any]) -> Tuple[bool, str]:
    case = dict(case)
    case.setdefault("case_id", f"CF-{secrets.randbelow(900000)+100000}")
    case.setdefault("created_at", iso_now())
    case.setdefault("updated_at", iso_now())
    case.setdefault("last_update", iso_now())
    case.setdefault("status", "New")
    case.setdefault("assignment_status", "Waiting for assignment")
    case.setdefault("source", "CaseFlow")
    try:
        db["cases"].insert_one(case)
        auto_assign_case(db, case["case_id"])
        return True, case["case_id"]
    except DuplicateKeyError:
        return False, "That case ID already exists."
    except Exception as e:
        return False, str(e)


def update_case(db, case_id: str, updates: Dict[str, Any], actor_email: str):
    updates = dict(updates)
    updates["updated_at"] = iso_now()
    updates["last_update"] = iso_now()
    db["cases"].update_one({"case_id": case_id}, {"$set": updates})
    db["audit_log"].insert_one({
        "actor": actor_email,
        "action": "case_update",
        "case_id": case_id,
        "changes": {k: str(v) for k, v in updates.items()},
        "created_at": iso_now(),
    })


def add_case_update(db, case_id: str, actor_email: str, note: str, status: str):
    db["cases"].update_one(
        {"case_id": case_id},
        {
            "$set": {
                "status": status,
                "last_update": iso_now(),
                "updated_at": iso_now(),
            },
            "$push": {
                "updates": {
                    "author": actor_email,
                    "note": note,
                    "created_at": iso_now(),
                }
            },
        },
    )
    db["audit_log"].insert_one({
        "actor": actor_email,
        "action": "case_update_note",
        "case_id": case_id,
        "note": note,
        "status": status,
        "created_at": iso_now(),
    })


def notify(db, email: str, title: str, message: str, ntype="system", case_id=None):
    db["notifications"].insert_one({
        "email": email.lower(),
        "title": title,
        "message": message,
        "type": ntype,
        "case_id": case_id,
        "read": False,
        "created_at": iso_now(),
    })


# -----------------------------------------------------------------------------
# Realtime reads. These are cached briefly to keep the app smooth; the fragment
# invalidates them on its polling cycle.
# -----------------------------------------------------------------------------

@st.cache_data(ttl=4, show_spinner=False)
def get_cases_cached(scope: str, email: str, stamp: int) -> List[Dict[str, Any]]:
    db = get_db()
    q = {} if scope == "all" else {"assigned_to": email.lower()}
    return [clean_doc(x) for x in db["cases"].find(q).sort([("priority", ASCENDING), ("due_date", ASCENDING)])]


@st.cache_data(ttl=4, show_spinner=False)
def get_agents_cached(stamp: int) -> List[Dict[str, Any]]:
    db = get_db()
    agents = list_agents(db)
    presence = {x["email"]: x for x in list_presence(db)}
    for a in agents:
        p = presence.get(a["email"].lower(), {})
        a["aux"] = p.get("aux", "Offline")
        a["last_seen"] = p.get("last_seen")
        a["kicked_until"] = p.get("kicked_until")
        a["active_cases"] = db["cases"].count_documents({
            "assigned_to": a["email"].lower(),
            "status": {"$nin": ["Completed", "Closed"]},
        })
        a["assigned_today"] = db["cases"].count_documents({
            "assigned_to": a["email"].lower(),
            "assigned_date": {"$regex": f"^{today_utc_date().isoformat()}"},
        })
    return agents


def clear_data_caches():
    get_cases_cached.clear()
    get_agents_cached.clear()


# -----------------------------------------------------------------------------
# Login
# -----------------------------------------------------------------------------

def inject_login_asset():
    try:
        asset_path = Path(__file__).resolve().parent / "hpe_login_panel.png"
        with open(asset_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        # Streamlit already emitted CSS. Add a tiny override with the actual asset.
        st.markdown(
            f"""<style>
            .login-brand:after {{
                background-image:url("data:image/png;base64,{b64}") !important;
            }}
            </style>""",
            unsafe_allow_html=True,
        )
    except Exception:
        pass


def login_brand():
    st.markdown(
        """
        <div class="login-brand">
          <div class="hpe-mark">▔▔</div>
          <div class="hpe-name">Hewlett Packard<br>Enterprise</div>
          <div class="hpe-line"></div>
          <h1>HPE CaseFlow</h1>
          <p>Team Task and Case<br>Management</p>
          <div class="login-features">
            <div class="login-feature"><b>▣ &nbsp; Manage Cases</b><span>Track and resolve tasks efficiently</span></div>
            <div class="login-feature"><b>♧ &nbsp; Team Collaboration</b><span>Work together for better service delivery</span></div>
            <div class="login-feature"><b>▥ &nbsp; Real-Time Visibility</b><span>Stay informed and in control</span></div>
            <div class="login-feature"><b>♢ &nbsp; Secure Access</b><span>HPE employees only</span></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.dialog("Sign In", width="small")
def sign_in_dialog():
    st.caption("Access your HPE CaseFlow account")
    email = st.text_input("HPE Email Address", placeholder="name@hpe.com", key="signin_email")
    pw = st.text_input("Password", type="password", placeholder="Enter your password", key="signin_pw")
    keep = st.checkbox("Keep me signed in", value=True, key="signin_keep")
    c1, c2 = st.columns([1,1])
    with c1:
        if st.button("Sign In", type="primary", use_container_width=True):
            try:
                db = get_db()
                user = find_user(db, email)
                if user and password_verify(pw, user.get("password_hash", "")):
                    st.session_state.user = user
                    st.session_state.logged_in = True
                    st.session_state.page = "Dashboard"
                    st.session_state.session_id = uuid.uuid4().hex
                    default_aux = ADMIN_DEFAULT_AUX if user.get("role") == "admin" else REGULAR_DEFAULT_AUX
                    st.session_state.aux = default_aux
                    upsert_presence(db, user, default_aux)
                    st.rerun()
                else:
                    st.error("Invalid HPE email or password.")
            except Exception as e:
                st.error(f"Unable to sign in: {e}")
    with c2:
        if st.button("Create an Account", use_container_width=True):
            st.session_state.auth_mode = "signup"
            st.rerun()


@st.dialog("Sign Up", width="medium")
def sign_up_dialog():
    st.caption("Create your HPE CaseFlow account")
    c1, c2 = st.columns(2)
    with c1:
        first = st.text_input("First Name", key="su_first")
        emp = st.text_input("Employee ID", key="su_emp")
        email = st.text_input("HPE Email Address", placeholder="name@hpe.com", key="su_email")
        birthday = st.date_input("Birthday", value=date(1995,1,1), min_value=date(1940,1,1), max_value=date.today(), key="su_bday")
        contact = st.text_input("Contact Number", key="su_contact")
    with c2:
        last = st.text_input("Last Name", key="su_last")
        address = st.text_area("Home Address", height=100, key="su_address")
        pw = st.text_input("Password", type="password", key="su_pw")
        cpw = st.text_input("Confirm Password", type="password", key="su_cpw")
    if st.button("Create Account", type="primary", use_container_width=True):
        if not all([first.strip(), last.strip(), emp.strip(), email.strip(), address.strip(), contact.strip(), pw]):
            st.error("Please complete all required fields.")
            return
        if not email.lower().endswith("@hpe.com"):
            st.error("Please use an HPE email address.")
            return
        if pw != cpw:
            st.error("Passwords do not match.")
            return
        db = get_db()
        ok, msg = create_user(db, {
            "first_name": first.strip(),
            "last_name": last.strip(),
            "employee_id": emp.strip(),
            "email": email.strip().lower(),
            "birthday": birthday.isoformat(),
            "home_address": address.strip(),
            "contact_number": contact.strip(),
            "password": pw,
        })
        if ok:
            st.success(msg)
            st.session_state.auth_mode = "signin"
            st.rerun()
        else:
            st.error(msg)


def login_page():
    inject_login_asset()
    st.markdown('<div class="login-shell"><div class="login-card">', unsafe_allow_html=True)
    left, right = st.columns([.39, .61], gap="small")
    with left:
        login_brand()
    with right:
        st.markdown(
            '<div class="login-panel"><h2>Sign In</h2>'
            '<div class="lead">Access your HPE CaseFlow account</div></div>',
            unsafe_allow_html=True,
        )
        # Put Streamlit controls in the white panel area.
        st.text_input("HPE Email Address", placeholder="name@hpe.com", disabled=True, label_visibility="collapsed")
        b1, b2 = st.columns(2)
        with b1:
            if st.button("Sign In", type="primary", use_container_width=True, key="open_signin"):
                sign_in_dialog()
        with b2:
            if st.button("Sign Up", use_container_width=True, key="open_signup"):
                sign_up_dialog()
        st.markdown(
            '<div style="text-align:center;color:#6B7F91;margin-top:1rem">'
            'Sign in to continue or create an HPE CaseFlow account.</div>',
            unsafe_allow_html=True,
        )
    st.markdown("</div></div>", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Layout/navigation
# -----------------------------------------------------------------------------

def init_state():
    defaults = {
        "logged_in": False,
        "user": None,
        "page": "Dashboard",
        "selected_case": None,
        "case_filter": "All",
        "auth_mode": "signin",
        "session_id": uuid.uuid4().hex,
        "aux": None,
        "live_stamp": 0,
        "sidebar_open": True,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def current_user() -> Dict[str, Any]:
    return st.session_state.user


def render_topbar(db):
    user = current_user()
    name = f'{user.get("first_name","")} {user.get("last_name","")}'.strip()
    role = user.get("role", "regular").title()
    notif_count = db["notifications"].count_documents({"email": user["email"], "read": False})
    c1, c2 = st.columns([7, 2], vertical_alignment="center")
    with c1:
        st.markdown(
            f'<div class="page-title">{html.escape(st.session_state.page)}</div>'
            f'<div class="page-subtitle">HPE CaseFlow · Real-time case and workforce visibility</div>',
            unsafe_allow_html=True,
        )
    with c2:
        p1, p2 = st.columns([1,3], vertical_alignment="center")
        with p1:
            st.markdown(f"🔔 **{notif_count}**")
        with p2:
            with st.popover(f"👤 {name}  ·  {role}", use_container_width=True):
                st.markdown(f"**{name}**")
                st.caption(f'{user.get("employee_id","")} · {user.get("email","")}')
                st.divider()
                st.markdown("**AUX / Presence**")
                aux = st.selectbox(
                    "Current status",
                    AUX_OPTIONS,
                    index=AUX_OPTIONS.index(
                        st.session_state.aux or
                        (ADMIN_DEFAULT_AUX if user.get("role") == "admin" else REGULAR_DEFAULT_AUX)
                    ),
                    key="profile_aux",
                    label_visibility="collapsed",
                )
                if aux != st.session_state.aux:
                    st.session_state.aux = aux
                    set_presence_aux(db, user["email"], aux)
                    st.toast(f"AUX changed to {aux}")
                    clear_data_caches()
                st.caption("AUX syncs as live presence and is not stored in the roster profile.")
                if st.button("My Profile", use_container_width=True):
                    st.session_state.page = "Profile"
                    st.rerun()
                if st.button("Sign Out", use_container_width=True):
                    st.session_state.logged_in = False
                    st.session_state.user = None
                    st.session_state.page = "Dashboard"
                    st.rerun()


def sidebar_nav():
    user = current_user()
    is_admin = user.get("role") == "admin"
    if is_admin:
        items = ["Dashboard", "Cases", "Agents", "Schedule", "Requests", "Reports", "Salesforce", "Settings"]
    else:
        items = ["Dashboard", "My Cases", "Schedule", "Requests", "Profile"]

    with st.sidebar:
        st.markdown(
            '<div style="font-size:1.15rem;font-weight:800;color:white;padding:.7rem .7rem 1rem">'
            'HPE CaseFlow</div>',
            unsafe_allow_html=True,
        )
        for item in items:
            active = st.session_state.page == item
            if st.button(
                f"{'●' if active else '○'}  {item}",
                key=f"nav_{item}",
                type="primary" if active else "secondary",
                use_container_width=True,
            ):
                st.session_state.page = item
                st.session_state.selected_case = None
                st.rerun()
        st.divider()
        st.caption("Realtime polling: 4 seconds")
        st.caption("Sidebar can be collapsed with the Streamlit control.")


# -----------------------------------------------------------------------------
# Live presence / alerts
# -----------------------------------------------------------------------------

@st.fragment(run_every="4s")
def live_presence_fragment():
    if not st.session_state.logged_in:
        return
    try:
        db = get_db()
        user = current_user()
        aux = st.session_state.aux or (
            ADMIN_DEFAULT_AUX if user.get("role") == "admin" else REGULAR_DEFAULT_AUX
        )
        upsert_presence(db, user, aux)
        st.session_state.live_stamp = int(datetime.utcnow().timestamp())
    except Exception:
        pass


def user_notifications(db, limit=8):
    return [clean_doc(x) for x in db["notifications"].find(
        {"email": current_user()["email"], "read": False}
    ).sort("created_at", DESCENDING).limit(limit)]


def generate_case_alerts(db, user, cases):
    # Deduplicate by a simple hourly alert key.
    for case in cases:
        cid = case.get("case_id")
        if not cid:
            continue
        if due_soon(case, 4):
            key = f"due4:{cid}:{now_utc().strftime('%Y%m%d%H')}"
            if not db["notifications"].find_one({"email": user["email"], "dedupe_key": key}):
                notify(db, user["email"], "Case due soon",
                       f"Case {cid} is due within 4 hours.", "due", cid)
                db["notifications"].update_one(
                    {"email": user["email"], "case_id": cid, "title": "Case due soon",
                     "dedupe_key": {"$exists": False}},
                    {"$set": {"dedupe_key": key}},
                )
        if case.get("priority") == "Critical":
            key = f"critical:{cid}:{now_utc().strftime('%Y%m%d%H')}"
            if not db["notifications"].find_one({"email": user["email"], "dedupe_key": key}):
                notify(db, user["email"], "Critical case",
                       f"Case {cid} is currently Critical.", "critical", cid)
                db["notifications"].update_one(
                    {"email": user["email"], "case_id": cid, "title": "Critical case",
                     "dedupe_key": {"$exists": False}},
                    {"$set": {"dedupe_key": key}},
                )
        if is_stale(case, 24):
            key = f"stale:{cid}:{now_utc().strftime('%Y%m%d')}"
            if not db["notifications"].find_one({"email": user["email"], "dedupe_key": key}):
                notify(db, user["email"], "Case needs an update",
                       f"Case {cid} has not been updated for 24 hours.", "stale", cid)
                db["notifications"].update_one(
                    {"email": user["email"], "case_id": cid,
                     "title": "Case needs an update",
                     "dedupe_key": {"$exists": False}},
                    {"$set": {"dedupe_key": key}},
                )


# -----------------------------------------------------------------------------
# Common dashboard widgets
# -----------------------------------------------------------------------------

def kpi_tiles(cases: List[Dict[str, Any]], key_prefix="kpi"):
    active = [c for c in cases if is_active_case(c)]
    critical = [c for c in active if c.get("priority") == "Critical"]
    due = [c for c in active if due_soon(c)]
    track = [c for c in active if c.get("priority") != "Critical" and not due_soon(c)]
    cols = st.columns(4, gap="small")
    data = [
        ("Active Cases", len(active), "kpi-active", "All"),
        ("Critical", len(critical), "kpi-critical", "Critical"),
        ("Due Soon", len(due), "kpi-due", "Due Soon"),
        ("On Track", len(track), "kpi-track", "On Track"),
    ]
    for col, (label, num, cls, filter_name) in zip(cols, data):
        with col:
            if st.button(
                f"{num}\n{label}",
                key=f"{key_prefix}_{filter_name}",
                use_container_width=True,
            ):
                st.session_state.case_filter = filter_name
                st.session_state.page = "My Cases" if current_user().get("role") != "admin" else "Cases"
                st.rerun()


def alerts_panel(db, cases):
    st.markdown('<div class="section-title">Alerts for You</div>', unsafe_allow_html=True)
    notes = user_notifications(db, limit=6)
    if not notes:
        st.info("No new alerts.")
        return
    for n in notes:
        cols = st.columns([7, 1])
        with cols[0]:
            icon = "🔴" if n.get("type") in ("critical", "due", "stale") else "🔔"
            st.markdown(f"{icon} **{html.escape(n.get('title',''))}** — {html.escape(n.get('message',''))}")
        with cols[1]:
            if st.button("✓", key=f"read_{n['_id']}"):
                db["notifications"].update_one({"_id": ObjectId(n["_id"])}, {"$set": {"read": True}})
                st.rerun()


def cases_table(cases, key_prefix="cases", show_assignee=False):
    active = [c for c in cases if is_active_case(c)]
    selected_filter = st.session_state.get("case_filter", "All")
    if selected_filter == "Critical":
        active = [c for c in active if c.get("priority") == "Critical"]
    elif selected_filter == "Due Soon":
        active = [c for c in active if due_soon(c)]
    elif selected_filter == "On Track":
        active = [c for c in active if not due_soon(c) and c.get("priority") != "Critical"]

    search = st.text_input("Search cases", placeholder="Search case, subject, vendor, technician…", key=f"{key_prefix}_search")
    if search:
        q = search.lower()
        active = [
            c for c in active if q in " ".join([
                safe_str(c.get("case_id")), safe_str(c.get("subject")),
                safe_str(c.get("vendor")), safe_str(c.get("technician")),
                safe_str(c.get("description"))
            ]).lower()
        ]
    active.sort(key=urgency_rank)

    if not active:
        st.info("No cases match the current view.")
        return

    rows = []
    for c in active:
        rows.append({
            "Case #": c.get("case_id"),
            "Subject": c.get("subject", ""),
            "Priority": c.get("priority", ""),
            "Due Date": safe_str(c.get("due_date", "")).replace("T", " ")[:16],
            "Status": c.get("status", ""),
            "Last Update": safe_str(c.get("last_update", "")).replace("T", " ")[:16],
            "Assigned To": c.get("assigned_name", c.get("assigned_to", "")) if show_assignee else "",
        })
    df = pd.DataFrame(rows)
    event = st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        key=f"{key_prefix}_table",
        column_config={
            "Priority": st.column_config.TextColumn("Priority"),
            "Status": st.column_config.TextColumn("Status"),
        },
    )
    if event.selection.rows:
        idx = event.selection.rows[0]
        st.session_state.selected_case = active[idx]["case_id"]


def case_details(db, case_id: str, admin=False):
    case = clean_doc(db["cases"].find_one({"case_id": case_id}))
    if not case:
        st.warning("Case no longer exists.")
        st.session_state.selected_case = None
        return
    st.markdown(
        f'<div class="section-title">Case {html.escape(case_id)} '
        f'{html_badge(case.get("status",""), case.get("status",""))}</div>',
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns([1.35, 1], gap="large")
    with c1:
        st.markdown(f"### {html.escape(case.get('subject','Untitled case'))}")
        st.write(case.get("description", "No description provided."))
        st.caption(f"Created: {case.get('created_at','')} · Last update: {case.get('last_update','')}")
        if case.get("updates"):
            st.markdown("**Update history**")
            for u in reversed(case["updates"][-8:]):
                st.markdown(f"• **{u.get('author','')}** — {u.get('note','')}  \n<small>{u.get('created_at','')}</small>", unsafe_allow_html=True)
    with c2:
        st.markdown("**Case details**")
        st.write(f"Priority: {case.get('priority','')}")
        st.write(f"Due: {case.get('due_date','')}")
        st.write(f"Assigned to: {case.get('assigned_name',case.get('assigned_to','Waiting'))}")
        st.write(f"Vendor: {case.get('vendor','—')}")
        st.write(f"Technician: {case.get('technician','—')}")
        st.write(f"Source: {case.get('source','CaseFlow')}")
        if case.get("salesforce_url"):
            st.link_button("Open Salesforce Case", case["salesforce_url"], use_container_width=True)
        elif case.get("salesforce_case_id"):
            st.link_button("Open Salesforce", SALESFORCE_URL, use_container_width=True)

    if not admin or case.get("assigned_to") == current_user().get("email"):
        st.markdown("#### Update case")
        s1, s2 = st.columns([1, 2])
        with s1:
            status = st.selectbox(
                "Status",
                CASE_STATUSES,
                index=CASE_STATUSES.index(case.get("status")) if case.get("status") in CASE_STATUSES else 0,
                key=f"status_{case_id}",
            )
        with s2:
            note = st.text_input("Update note", key=f"note_{case_id}", placeholder="Add progress / follow-up note…")
        if st.button("Save Update", type="primary", key=f"save_{case_id}"):
            add_case_update(db, case_id, current_user()["email"], note or "Status updated.", status)
            clear_data_caches()
            st.toast("Case update saved.")
            st.rerun()

        st.markdown("#### Vendor / Technician")
        vendor_email = case.get("vendor_email", "")
        vendor_phone = case.get("vendor_phone", "")
        a, b, c = st.columns(3)
        with a:
            if vendor_email:
                st.link_button("✉ Email Vendor", f"mailto:{vendor_email}", use_container_width=True)
        with b:
            if vendor_phone:
                # navigator.clipboard copies the number; tel: remains the call action.
                st.markdown(
                    f"""<a href="tel:{html.escape(vendor_phone)}"
                    style="display:block;text-align:center;padding:.55rem;background:#0B73C9;
                    color:#fff;border-radius:8px;text-decoration:none;font-weight:600"
                    onclick="navigator.clipboard && navigator.clipboard.writeText('{html.escape(vendor_phone)}')">
                    ☎ Call / Copy Number</a>""",
                    unsafe_allow_html=True,
                )
        with c:
            if case.get("salesforce_url"):
                st.link_button("Vendor/Technician", case["salesforce_url"], use_container_width=True)
            else:
                st.link_button("Vendor/Technician", SALESFORCE_URL, use_container_width=True)

        st.markdown("#### Contract breached")
        breach = st.selectbox("Violation reason", ["Select…"] + list(BREACH_REASONS), key=f"breach_{case_id}")
        if breach != "Select…":
            generated = (
                f"Hello, we are following up regarding case {case_id}. "
                f"{BREACH_REASONS[breach]} Please provide an immediate update and the "
                f"recovery plan / revised delivery commitment."
            )
            edited = st.text_area("Generated message", generated, key=f"breach_msg_{case_id}")
            if st.button("Tag Contract Breached", key=f"breach_save_{case_id}"):
                update_case(db, case_id, {
                    "status": "Contract Breached",
                    "contract_breached_reason": breach,
                    "contract_breach_message": edited,
                }, current_user()["email"])
                st.success("Case tagged as Contract Breached.")
                clear_data_caches()
                st.rerun()
            if vendor_email:
                st.link_button("Email Breach Notice", f"mailto:{vendor_email}?subject={quote(f'Case {case_id} - Contract Breach')}&body={quote(edited)}")


# -----------------------------------------------------------------------------
# Regular dashboard
# -----------------------------------------------------------------------------

def regular_dashboard(db):
    user = current_user()
    cases = get_cases_cached("mine", user["email"], st.session_state.live_stamp)
    generate_case_alerts(db, user, cases)
    active = [c for c in cases if is_active_case(c)]
    critical = [c for c in active if c.get("priority") == "Critical"]
    due = [c for c in active if due_soon(c)]
    track = [c for c in active if c.get("priority") != "Critical" and not due_soon(c)]

    st.markdown(
        f"### Good {('morning' if datetime.now().hour < 12 else 'afternoon' if datetime.now().hour < 18 else 'evening')}, "
        f"{html.escape(user.get('first_name',''))}!",
    )
    st.caption(datetime.now().strftime("%A, %B %d, %Y · %I:%M %p"))

    kpi_tiles(cases, "agent")
    alerts_panel(db, cases)

    st.markdown('<div class="section-title">My Cases (Sorted by Urgency)</div>', unsafe_allow_html=True)
    cases_table(cases, "agent_cases")

    if st.session_state.selected_case:
        st.divider()
        case_details(db, st.session_state.selected_case, admin=False)

    st.divider()
    st.markdown("### Today's Schedule")
    render_agent_schedule(db, user["email"], date.today(), compact=True)

    st.markdown("### Live Adherence & Attendance")
    render_adherence_cards(db, [user])


# -----------------------------------------------------------------------------
# My cases / admin cases
# -----------------------------------------------------------------------------

def regular_cases(db):
    cases = get_cases_cached("mine", current_user()["email"], st.session_state.live_stamp)
    c1, c2 = st.columns([4, 1])
    with c1:
        st.markdown("### My Cases")
        st.caption("Assigned cases are automatically sorted by urgency.")
    with c2:
        if st.button("Clear Filter", use_container_width=True):
            st.session_state.case_filter = "All"
            st.session_state.selected_case = None
            st.rerun()
    cases_table(cases, "my_cases")
    if st.session_state.selected_case:
        st.divider()
        case_details(db, st.session_state.selected_case, admin=False)


def admin_dashboard(db):
    cases = get_cases_cached("all", "", st.session_state.live_stamp)
    active = [c for c in cases if is_active_case(c)]
    agents = get_agents_cached(st.session_state.live_stamp)
    st.markdown("### Team Overview")
    st.caption(datetime.now().strftime("%A, %B %d, %Y · %I:%M %p"))
    kpi_tiles(cases, "admin")
    c1, c2 = st.columns([1.1, 1.9])
    with c1:
        st.markdown("### Agent Status")
        rows = []
        for a in agents:
            if a.get("role") == "regular":
                rows.append({
                    "Agent": f'{a.get("first_name","")} {a.get("last_name","")}',
                    "AUX": a.get("aux","Offline"),
                    "Active": a.get("active_cases",0),
                    "Assigned Today": a.get("assigned_today",0),
                    "Adherence": f'{a.get("adherence_today", 0)}%',
                })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    with c2:
        st.markdown("### Case Distribution")
        dist = pd.DataFrame([
            {"Agent": f'{a.get("first_name","")} {a.get("last_name","")}', "Active": a.get("active_cases",0),
             "Assigned Today": a.get("assigned_today",0)}
            for a in agents if a.get("role") == "regular"
        ])
        if not dist.empty:
            st.bar_chart(dist.set_index("Agent")[["Active","Assigned Today"]])
        else:
            st.info("No regular agents yet.")
    alerts_panel(db, cases)
    st.markdown("### All Active Cases")
    cases_table(cases, "admin_dashboard_cases", show_assignee=True)
    if st.session_state.selected_case:
        st.divider()
        case_details(db, st.session_state.selected_case, admin=True)


def admin_cases(db):
    st.markdown("### Cases")
    st.caption("View, update, reassign and manage all active cases.")
    cases = get_cases_cached("all", "", st.session_state.live_stamp)
    cases_table(cases, "admin_cases", show_assignee=True)
    if st.session_state.selected_case:
        st.divider()
        case_details(db, st.session_state.selected_case, admin=True)
        st.markdown("#### Reassign case")
        agents = [a for a in get_agents_cached(st.session_state.live_stamp) if a.get("role") == "regular"]
        choices = {f'{a.get("first_name")} {a.get("last_name")} · {a.get("aux","Offline")}': a["email"] for a in agents}
        if choices:
            selected = st.selectbox("Agent", list(choices), key=f"reassign_{st.session_state.selected_case}")
            if st.button("Reassign", type="primary"):
                email = choices[selected]
                agent = find_user(db, email)
                update_case(db, st.session_state.selected_case, {
                    "assigned_to": email,
                    "assigned_name": f'{agent.get("first_name")} {agent.get("last_name")}',
                    "assignment_status": "Admin Reassigned",
                    "status": "Assigned",
                }, current_user()["email"])
                notify(db, email, "Case reassigned to you", f'Case {st.session_state.selected_case} was reassigned by admin.', "assignment", st.session_state.selected_case)
                clear_data_caches()
                st.rerun()


# -----------------------------------------------------------------------------
# Schedule / requests
# -----------------------------------------------------------------------------

def get_schedule(db, email: str, start: date, end: date):
    return [clean_doc(x) for x in db["schedule"].find({
        "email": email.lower(),
        "date": {"$gte": start.isoformat(), "$lte": end.isoformat()},
    }).sort([("date", ASCENDING), ("start", ASCENDING)])]


def ensure_daily_schedule(db, email: str, work_date: date):
    existing = list(db["schedule"].find({"email": email.lower(), "date": work_date.isoformat()}))
    if existing:
        return
    # Default workday template. Admin's workforce scheduler can adjust later.
    items = [
        ("08:00", "10:00", "Work / Case Processing", "work"),
        ("10:00", "10:15", "Break", "break"),
        ("10:15", "12:00", "Work / Case Processing", "work"),
        ("12:00", "13:00", "Lunch", "lunch"),
        ("13:00", "15:00", "Work / Case Processing", "work"),
        ("15:00", "15:15", "Break", "break"),
        ("15:15", "17:00", "Work / Case Processing", "work"),
    ]
    for start, end, activity, kind in items:
        db["schedule"].insert_one({
            "email": email.lower(),
            "date": work_date.isoformat(),
            "start": start,
            "end": end,
            "activity": activity,
            "kind": kind,
            "created_at": iso_now(),
            "source": "auto",
        })


def render_agent_schedule(db, email: str, selected_date: date, compact=False):
    ensure_daily_schedule(db, email, selected_date)
    schedule = get_schedule(db, email, selected_date, selected_date)
    if not schedule:
        st.info("No schedule plotted.")
        return
    rows = [{
        "Time": f'{x.get("start")} – {x.get("end")}',
        "Activity": x.get("activity"),
        "Type": x.get("kind","").title(),
    } for x in schedule]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def regular_schedule(db):
    st.markdown("### My Schedule")
    view = st.segmented_control("View", ["Day", "Week", "Month"], default="Day", key="schedule_view")
    selected = st.date_input("Date", value=date.today(), key="agent_schedule_date")
    if view == "Day":
        render_agent_schedule(db, current_user()["email"], selected)
    else:
        if view == "Week":
            start = selected - timedelta(days=selected.weekday())
            end = start + timedelta(days=6)
        else:
            start = selected.replace(day=1)
            next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            end = next_month - timedelta(days=1)
        # Ensure a default schedule for each working day in range.
        cur = start
        while cur <= end:
            if cur.weekday() < 5:
                ensure_daily_schedule(db, current_user()["email"], cur)
            cur += timedelta(days=1)
        schedule = get_schedule(db, current_user()["email"], start, end)
        st.dataframe(pd.DataFrame([{
            "Date": x.get("date"), "Time": f'{x.get("start")} – {x.get("end")}',
            "Activity": x.get("activity"), "Type": x.get("kind","").title()
        } for x in schedule]), use_container_width=True, hide_index=True)


def submit_request(db, req_type, start_date, end_date, reason):
    user = current_user()
    allocation = int(db["settings"].find_one({"key": "pto_allocation"}) or {"value": 5}).get("value", 5)
    used = db["requests"].count_documents({
        "email": user["email"], "type": "PTO", "status": {"$in": ["Approved", "Auto-Approved"]},
        "start_date": {"$gte": f"{date.today().year}-01-01"},
    })
    days = (end_date - start_date).days + 1
    if req_type == "PTO" and used + days > allocation:
        return False, "No allocation for the selected date."
    status = "Auto-Approved" if req_type in ("Sick Leave", "Emergency Leave", "PTO") else "Pending"
    doc = {
        "email": user["email"], "employee_name": f'{user.get("first_name")} {user.get("last_name")}',
        "type": req_type, "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
        "reason": reason, "status": status, "created_at": iso_now(),
    }
    db["requests"].insert_one(doc)
    # Admin notification.
    for a in list_agents(db):
        if a.get("role") == "admin":
            notify(db, a["email"], "New request", f'{doc["employee_name"]} submitted {req_type}.', "request")
    return True, "Request submitted."


def regular_requests(db):
    st.markdown("### Requests")
    tabs = st.tabs(["New Request", "My Requests", "Schedule Swap"])
    with tabs[0]:
        req_type = st.selectbox("Request Type", ["PTO", "Sick Leave", "Emergency Leave"])
        start = st.date_input("Start Date", date.today(), key="req_start")
        end = st.date_input("End Date", date.today(), key="req_end")
        reason = st.text_area("Reason")
        if st.button("Submit Request", type="primary"):
            if end < start:
                st.error("End date cannot be before start date.")
            else:
                ok, msg = submit_request(db, req_type, start, end, reason)
                (st.success if ok else st.error)(msg)
    with tabs[1]:
        reqs = [clean_doc(x) for x in db["requests"].find({"email": current_user()["email"]}).sort("created_at", DESCENDING).limit(30)]
        if reqs:
            st.dataframe(pd.DataFrame([{
                "Date": f'{r.get("start_date")} → {r.get("end_date")}',
                "Type": r.get("type"), "Status": r.get("status"), "Reason": r.get("reason","")
            } for r in reqs]), use_container_width=True, hide_index=True)
        else:
            st.info("No requests yet.")
    with tabs[2]:
        st.caption("A schedule swap is automatically approved when both agents agree.")
        agents = [a for a in list_agents(db) if a.get("role") == "regular" and a["email"] != current_user()["email"]]
        choices = {f'{a.get("first_name")} {a.get("last_name")}': a["email"] for a in agents}
        if choices:
            date_swap = st.date_input("Swap Date", date.today(), key="swap_date")
            partner = st.selectbox("Swap with", list(choices), key="swap_partner")
            if st.button("Request Swap", type="primary"):
                db["requests"].insert_one({
                    "email": current_user()["email"],
                    "type": "Schedule Swap",
                    "start_date": date_swap.isoformat(),
                    "end_date": date_swap.isoformat(),
                    "partner_email": choices[partner],
                    "status": "Pending Partner Agreement",
                    "created_at": iso_now(),
                })
                notify(db, choices[partner], "Schedule swap request",
                       f'{current_user().get("first_name")} wants to swap {date_swap}.',
                       "request")
                st.success("Swap request sent to the other agent.")


def admin_schedule(db):
    st.markdown("### Schedule")
    tabs = st.tabs(["Team Schedule", "Schedule Requests", "Schedule Builder"])
    with tabs[0]:
        selected = st.date_input("Date", date.today(), key="admin_schedule_date")
        agents = [a for a in list_agents(db) if a.get("role") == "regular"]
        for a in agents:
            ensure_daily_schedule(db, a["email"], selected)
        rows = []
        for a in agents:
            sched = get_schedule(db, a["email"], selected, selected)
            for x in sched:
                rows.append({
                    "Agent": f'{a.get("first_name")} {a.get("last_name")}',
                    "AUX": get_presence(db, a["email"]).get("aux","Offline") if get_presence(db, a["email"]) else "Offline",
                    "Time": f'{x.get("start")}–{x.get("end")}',
                    "Activity": x.get("activity"),
                })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    with tabs[1]:
        reqs = [clean_doc(x) for x in db["requests"].find({"status": {"$in": ["Pending", "Pending Partner Agreement"]}}).sort("created_at", DESCENDING)]
        for r in reqs:
            with st.container(border=True):
                st.markdown(f"**{r.get('employee_name','')} · {r.get('type','')}**")
                st.caption(f'{r.get("start_date")} → {r.get("end_date")} · {r.get("reason","")}')
                c1, c2 = st.columns(2)
                if c1.button("Approve", key=f"approve_{r['_id']}"):
                    db["requests"].update_one({"_id": ObjectId(r["_id"])}, {"$set": {"status": "Approved", "approved_at": iso_now(), "approved_by": current_user()["email"]}})
                    notify(db, r["email"], "Request approved", f'Your {r.get("type")} request was approved.', "request")
                    st.rerun()
                if c2.button("Decline", key=f"decline_{r['_id']}"):
                    db["requests"].update_one({"_id": ObjectId(r["_id"])}, {"$set": {"status": "Declined", "approved_by": current_user()["email"]}})
                    notify(db, r["email"], "Request declined", f'Your {r.get("type")} request was declined.', "request")
                    st.rerun()
    with tabs[2]:
        st.caption("The builder keeps a break/lunch/break pattern by default, then adjusts it by queue coverage.")
        agents = [a for a in list_agents(db) if a.get("role") == "regular"]
        if agents:
            agent = st.selectbox("Agent", [f'{a.get("first_name")} {a.get("last_name")}' for a in agents])
            selected_agent = agents[[f'{a.get("first_name")} {a.get("last_name")}' for a in agents].index(agent)]
            selected_date = st.date_input("Date", date.today(), key="builder_date")
            ensure_daily_schedule(db, selected_agent["email"], selected_date)
            sched = get_schedule(db, selected_agent["email"], selected_date, selected_date)
            for x in sched:
                c1,c2,c3,c4,c5 = st.columns([1,1,2,1,1])
                c1.write(x.get("start"))
                c2.write(x.get("end"))
                c3.write(x.get("activity"))
                if c4.button("Edit", key=f"edit_sched_{x['_id']}"):
                    st.session_state[f"editing_sched_{x['_id']}"] = True
                if c5.button("Delete", key=f"del_sched_{x['_id']}"):
                    db["schedule"].delete_one({"_id": ObjectId(x["_id"])})
                    st.rerun()
            with st.expander("Add activity / break / lunch"):
                s = st.time_input("Start", time(10,0))
                e = st.time_input("End", time(10,15))
                activity = st.text_input("Activity", "Meeting")
                kind = st.selectbox("Type", ["meeting","coaching","admin","break","lunch","work"])
                if st.button("Add to Schedule", type="primary"):
                    db["schedule"].insert_one({
                        "email": selected_agent["email"], "date": selected_date.isoformat(),
                        "start": s.strftime("%H:%M"), "end": e.strftime("%H:%M"),
                        "activity": activity, "kind": kind, "source": "admin", "created_at": iso_now()
                    })
                    st.success("Schedule updated.")
                    st.rerun()


# -----------------------------------------------------------------------------
# Admin agents / requests / reports / Salesforce / settings
# -----------------------------------------------------------------------------

def admin_agents(db):
    st.markdown("### Agents")
    agents = get_agents_cached(st.session_state.live_stamp)
    rows = [{
        "Name": f'{a.get("first_name","")} {a.get("last_name","")}',
        "Email": a.get("email",""),
        "AUX": a.get("aux","Offline"),
        "Active Cases": a.get("active_cases",0),
        "Assigned Today": a.get("assigned_today",0),
        "Role": a.get("role",""),
    } for a in agents]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("#### Agent controls")
    regulars = [a for a in agents if a.get("role") == "regular"]
    if not regulars:
        st.info("No regular agents.")
        return
    labels = [f'{a.get("first_name")} {a.get("last_name")} · {a.get("email")}' for a in regulars]
    selected = st.selectbox("Agent", labels)
    agent = regulars[labels.index(selected)]
    c1,c2,c3 = st.columns(3)
    if c1.button("Kick / Pause Assignment"):
        until = now_utc() + timedelta(minutes=30)
        db["presence"].update_one({"email": agent["email"]}, {"$set": {"kicked_until": until, "aux": "Busy - Away", "last_seen": now_utc()}}, upsert=True)
        notify(db, agent["email"], "Assignment paused", "An administrator paused auto-assignment for your session for 30 minutes.", "system")
        clear_data_caches()
        st.success("Agent paused for auto-assignment.")
    if c2.button("Send Missed Case Alert"):
        notify(db, agent["email"], "Missed / ageing case", "Please review your ageing bucket and update any overdue cases.", "stale")
        st.success("Alert sent.")
    if c3.button("Open Bucket"):
        st.session_state.page = "Cases"
        st.session_state.case_filter = "All"
        st.rerun()

    st.markdown("#### Role management")
    new_role = st.selectbox("Set role", ["regular","admin"], key="set_role")
    if st.button("Save Role"):
        db[ROSTER_COLLECTION_NAME].update_one({"email": agent["email"]}, {"$set": {"role": new_role, "updated_at": iso_now()}})
        st.success("Role updated.")
        clear_data_caches()
        st.rerun()


def admin_requests(db):
    st.markdown("### Requests")
    reqs = [clean_doc(x) for x in db["requests"].find().sort("created_at", DESCENDING).limit(100)]
    if reqs:
        st.dataframe(pd.DataFrame([{
            "Date": r.get("created_at",""),
            "Agent": r.get("employee_name",r.get("email","")),
            "Type": r.get("type",""),
            "Range": f'{r.get("start_date")} → {r.get("end_date")}',
            "Status": r.get("status",""),
        } for r in reqs]), use_container_width=True, hide_index=True)
    else:
        st.info("No requests.")


def compute_adherence(db, email: str, start: date, end: date) -> float:
    # A practical baseline: scheduled minutes that are represented by Active/Work
    # presence. Replace with your WFM/attendance feed later without changing UI.
    sched = get_schedule(db, email, start, end)
    if not sched:
        return 100.0
    planned = 0
    covered = 0
    for x in sched:
        try:
            s = datetime.combine(start, datetime.strptime(x["start"], "%H:%M").time())
            e = datetime.combine(start, datetime.strptime(x["end"], "%H:%M").time())
            mins = max(0, int((e-s).total_seconds()/60))
            planned += mins
            if x.get("kind") in ("work", "meeting", "coaching", "admin"):
                covered += mins
        except Exception:
            pass
    return round((covered / planned) * 100, 1) if planned else 100.0


def render_adherence_cards(db, agents):
    rows = []
    for a in agents:
        if a.get("role") == "admin":
            continue
        adh = compute_adherence(db, a["email"], date.today(), date.today())
        a["adherence_today"] = adh
        rows.append({
            "Agent": f'{a.get("first_name")} {a.get("last_name")}',
            "Today Adherence": f"{adh}%",
            "MTD Adherence": f"{adh}%",
            "Attendance": "Present",
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def admin_reports(db):
    st.markdown("### Reports")
    start = st.date_input("Start Date", date.today() - timedelta(days=6), key="report_start")
    end = st.date_input("End Date", date.today(), key="report_end")
    cases = [clean_doc(x) for x in db["cases"].find()]
    active = [c for c in cases if is_active_case(c)]
    agents = [a for a in list_agents(db) if a.get("role") == "regular"]
    summary = {
        "Active Cases": len(active),
        "Critical": len([c for c in active if c.get("priority") == "Critical"]),
        "Due Soon": len([c for c in active if due_soon(c)]),
        "Completed": len([c for c in cases if c.get("status") == "Completed"]),
        "Contract Breached": len([c for c in cases if c.get("status") == "Contract Breached"]),
    }
    st.dataframe(pd.DataFrame([summary]), use_container_width=True, hide_index=True)
    st.markdown("### Daily / MTD Adherence & Attendance")
    render_adherence_cards(db, agents)

    if cases:
        export_df = pd.DataFrame([{
            "Case": c.get("case_id"),
            "Subject": c.get("subject"),
            "Priority": c.get("priority"),
            "Status": c.get("status"),
            "Assigned To": c.get("assigned_name", c.get("assigned_to")),
            "Created": c.get("created_at"),
            "Last Update": c.get("last_update"),
            "Due": c.get("due_date"),
        } for c in cases])
        st.download_button(
            "Export Case Report (CSV)",
            export_df.to_csv(index=False).encode("utf-8"),
            file_name=f"hpe_caseflow_report_{date.today().isoformat()}.csv",
            mime="text/csv",
        )


def salesforce_fetch_cases():
    """
    Placeholder for Salesforce API integration.
    Replace this function with OAuth + REST/SOQL logic when credentials are added.
    Return a list of normalized CaseFlow dictionaries:
      {
        "case_id": "...",
        "subject": "...",
        "priority": "High",
        "due_date": "...",
        "description": "...",
        "vendor": "...",
        "technician": "...",
        "vendor_email": "...",
        "vendor_phone": "...",
        "salesforce_case_id": "...",
        "salesforce_url": "..."
      }
    """
    return []


def sync_salesforce(db):
    incoming = salesforce_fetch_cases()
    created = 0
    for c in incoming:
        if not db["cases"].find_one({"case_id": c.get("case_id")}):
            ok, _ = insert_case(db, {**c, "source": "Salesforce"})
            if ok:
                created += 1
    clear_data_caches()
    return created


def admin_salesforce(db):
    st.markdown("### Salesforce Integration")
    st.caption("Admin-only. The integration point is isolated so credentials/API details can be added later.")
    st.link_button("Open Salesforce", SALESFORCE_URL, use_container_width=False)
    st.code(
        f'SALESFORCE_URL = "{SALESFORCE_URL}"\n'
        'salesforce_fetch_cases() -> normalized CaseFlow records',
        language="python",
    )
    st.info("No Salesforce credentials are hard-coded. Add OAuth/API configuration later.")
    if st.button("Run Salesforce Sync"):
        try:
            n = sync_salesforce(db)
            st.success(f"Sync complete. {n} new case(s) imported.")
        except Exception as e:
            st.error(f"Salesforce sync is not configured yet: {e}")


def admin_settings(db):
    st.markdown("### Settings")
    tabs = st.tabs(["User Management", "PTO Allocation", "System Settings"])
    with tabs[0]:
        agents = list_agents(db)
        st.dataframe(pd.DataFrame([{
            "Name": f'{a.get("first_name")} {a.get("last_name")}',
            "Employee ID": a.get("employee_id"),
            "Email": a.get("email"),
            "Role": a.get("role"),
            "Status": a.get("status"),
        } for a in agents]), use_container_width=True, hide_index=True)
        st.caption("Role changes are saved immediately to the roster collection.")
    with tabs[1]:
        current = db["settings"].find_one({"key": "pto_allocation"})
        allocation = int(current.get("value", 5)) if current else 5
        value = st.number_input("Annual PTO allocation (days)", min_value=0, max_value=100, value=allocation)
        if st.button("Save PTO Allocation"):
            db["settings"].update_one({"key": "pto_allocation"}, {"$set": {"value": int(value), "updated_at": iso_now()}}, upsert=True)
            st.success("PTO allocation saved.")
    with tabs[2]:
        sf = st.text_input("Salesforce URL", value=SALESFORCE_URL)
        poll = st.number_input("Realtime polling interval (seconds)", min_value=4, max_value=60, value=4)
        if st.button("Save System Settings"):
            db["settings"].update_one({"key": "salesforce_url"}, {"$set": {"value": sf}}, upsert=True)
            db["settings"].update_one({"key": "poll_seconds"}, {"$set": {"value": int(poll)}}, upsert=True)
            st.success("Settings saved.")


def profile_page(db):
    u = current_user()
    st.markdown("### My Profile")
    c1,c2 = st.columns(2)
    with c1:
        first = st.text_input("First Name", value=u.get("first_name",""))
        last = st.text_input("Last Name", value=u.get("last_name",""))
        emp = st.text_input("Employee ID", value=u.get("employee_id",""), disabled=True)
        email = st.text_input("HPE Email", value=u.get("email",""), disabled=True)
    with c2:
        bday = st.text_input("Birthday", value=u.get("birthday",""))
        address = st.text_area("Home Address", value=u.get("home_address",""))
        contact = st.text_input("Contact Number", value=u.get("contact_number",""))
    if st.button("Save Profile", type="primary"):
        db[ROSTER_COLLECTION_NAME].update_one(
            {"email": u["email"]},
            {"$set": {
                "first_name": first.strip(), "last_name": last.strip(),
                "birthday": bday, "home_address": address.strip(),
                "contact_number": contact.strip(), "updated_at": iso_now()
            }}
        )
        st.session_state.user = find_user(db, u["email"])
        st.success("Profile saved.")


# -----------------------------------------------------------------------------
# Auto-assignment watchdog
# -----------------------------------------------------------------------------

@st.fragment(run_every="8s")
def assignment_watchdog():
    if not st.session_state.logged_in:
        return
    if current_user().get("role") != "admin":
        return
    try:
        db = get_db()
        # Pick up any new/unassigned cases and assign immediately when a qualified
        # Active agent is present.
        pending = db["cases"].find({
            "assigned_to": {"$in": [None, ""]},
            "status": {"$nin": ["Completed", "Closed"]},
        }).limit(20)
        for c in pending:
            auto_assign_case(db, c["case_id"])
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    init_state()

    try:
        db = get_db()
        seed_admin(db)
        if not db_ok(db):
            st.error("MongoDB is not reachable.")
            return
    except Exception as e:
        # Login cannot function without the roster DB.
        st.markdown(
            """
            <div style="max-width:850px;margin:10vh auto;padding:2rem;background:#fff;
            border-radius:16px;border:1px solid #e1e7ed;box-shadow:0 10px 30px rgba(0,0,0,.08)">
            <h2 style="color:#123B59">HPE CaseFlow</h2>
            <p>MongoDB connection is not configured yet.</p>
            <p>Add <b>MONGODB_URI</b> to <code>.streamlit/secrets.toml</code> or the environment,
            then restart Streamlit.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    if not st.session_state.logged_in:
        login_page()
        return

    # Live presence and assignment watcher are isolated fragments.
    live_presence_fragment()
    assignment_watchdog()

    sidebar_nav()
    render_topbar(db)

    page = st.session_state.page
    role = current_user().get("role")

    if role == "admin":
        if page == "Dashboard":
            admin_dashboard(db)
        elif page == "Cases":
            admin_cases(db)
        elif page == "Agents":
            admin_agents(db)
        elif page == "Schedule":
            admin_schedule(db)
        elif page == "Requests":
            admin_requests(db)
        elif page == "Reports":
            admin_reports(db)
        elif page == "Salesforce":
            admin_salesforce(db)
        elif page == "Settings":
            admin_settings(db)
        elif page == "Profile":
            profile_page(db)
        else:
            admin_dashboard(db)
    else:
        if page == "Dashboard":
            regular_dashboard(db)
        elif page == "My Cases":
            regular_cases(db)
        elif page == "Schedule":
            regular_schedule(db)
        elif page == "Requests":
            regular_requests(db)
        elif page == "Profile":
            profile_page(db)
        else:
            regular_dashboard(db)


if __name__ == "__main__":
    main()
