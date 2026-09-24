
import os
import re
import io
import time
import hashlib
import hmac
from datetime import datetime, date, time as dtime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import PyMongoError, DuplicateKeyError

try:
    import bcrypt
except ImportError:
    bcrypt = None

# ============================================================
# CASEFLOW — HPE TEAM TASK / CASE MANAGEMENT
# MongoDB: TeamRoster / Team Roster Collection
# Salesforce: https://hp.lightning.force.com/
#
# Recommended:
#   pip install streamlit pymongo bcrypt pandas openpyxl
#
# MongoDB URI:
#   .streamlit/secrets.toml
#       MONGO_URI="mongodb+srv://..."
#
# The app intentionally stores password hashes, never plaintext
# passwords. All operational changes are persisted to MongoDB.
# ============================================================

APP_TZ = ZoneInfo("Asia/Manila")
DEFAULT_SF_URL = "https://hp.lightning.force.com/"
AUTO_ADMIN_EMAIL = "arianne-may.escabillas@hpe.com"

DB_NAME = "TeamRoster"
USER_COLLECTION = "Team Roster Collection"

POLL_SECONDS = 5
DUE_SOON_HOURS = 4
STALE_HOURS = 24

AUX_OPTIONS = [
    "Available",
    "Admin Task",
    "Break",
    "Lunch",
    "In a Meeting",
    "Coaching",
    "Busy - Away",
    "Unscheduled Break",
]

CASE_STATUSES = [
    "New",
    "Assigned",
    "In Progress",
    "Pending Vendor",
    "Pending Technician",
    "Waiting for Customer",
    "Completed",
    "Contract Breached",
    "Cancelled",
]

PRIORITIES = ["Critical", "High", "Medium", "Low"]

BREACH_REASONS = {
    "Vendor missed committed delivery": "The vendor did not deliver within the committed timeframe.",
    "Vendor failed to respond": "The vendor failed to provide the required response or update within the expected timeframe.",
    "Vendor missed scheduled appointment": "The vendor failed to attend or complete the scheduled appointment.",
    "Repeated vendor delay": "The vendor has repeatedly delayed delivery despite follow-up.",
    "Other contractual violation": "The vendor did not meet the applicable contractual service requirement.",
}

REQUEST_TYPES = ["Sick Leave", "Emergency Leave", "PTO", "Schedule Swap", "Schedule Change"]

st.set_page_config(
    page_title="HPE CaseFlow",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------- Styling ---------------------------

st.markdown(
    """
<style>
:root {
  --navy:#10243e;
  --blue:#1769aa;
  --green:#16855b;
  --yellow:#c98b00;
  --red:#c63c3c;
  --bg:#f4f7fb;
  --card:#ffffff;
  --muted:#68778d;
}
html, body, [class*="css"] { font-family: Inter, Arial, sans-serif; }
[data-testid="stAppViewContainer"] { background:var(--bg); }
[data-testid="stHeader"] { background:rgba(0,0,0,0); }
.block-container { padding-top: 1rem; max-width: 1800px; }
.hero {
  background:linear-gradient(135deg,#10243e,#1769aa);
  color:white; border-radius:18px; padding:20px 24px; margin-bottom:16px;
  box-shadow:0 8px 24px rgba(16,36,62,.12);
}
.hero h1 { margin:0; font-size:28px; }
.hero p { margin:5px 0 0; opacity:.85; }
.metric-card {
  background:white; border:1px solid #e5eaf0; border-radius:16px;
  padding:14px 16px; box-shadow:0 3px 12px rgba(20,40,70,.06);
  min-height:100px;
}
.metric-title { color:#6b7788; font-size:13px; }
.metric-value { font-size:30px; font-weight:750; color:#10243e; }
.metric-sub { color:#7b8797; font-size:12px; }
.case-red { border-left:6px solid #c63c3c !important; }
.case-yellow { border-left:6px solid #c98b00 !important; }
.case-green { border-left:6px solid #16855b !important; }
.case-card {
  background:white; border:1px solid #e3e9f0; border-radius:13px;
  padding:12px 15px; margin-bottom:8px;
}
.case-id { color:#1769aa; font-weight:700; }
.muted { color:#6b7788; }
.badge {
 display:inline-block; border-radius:999px; padding:3px 9px; font-size:11px;
 background:#edf2f7; margin-right:4px;
}
.badge-red { background:#fdeaea; color:#a52222; }
.badge-yellow { background:#fff4d6; color:#8c6300; }
.badge-green { background:#e4f6ee; color:#0b7048; }
.alert-box {
 background:#fff7df; border:1px solid #efd37a; padding:10px 12px;
 border-radius:10px; margin-bottom:8px;
}
.small-note { font-size:12px; color:#6b7788; }
</style>
""",
    unsafe_allow_html=True,
)

# ------------------------- Utilities -------------------------

def now():
    return datetime.now(APP_TZ).replace(tzinfo=None)

def oid_str(value):
    return str(value) if value is not None else ""

def normalize_email(email):
    return (email or "").strip().lower()

def safe_text(value):
    return "" if value is None else str(value)

def parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None

def fmt_dt(value):
    dt = parse_dt(value)
    return dt.strftime("%b %d, %Y %I:%M %p") if dt else "—"

def hours_since(value):
    dt = parse_dt(value)
    if not dt:
        return None
    return (now() - dt).total_seconds() / 3600

def hash_password(password):
    if bcrypt:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    # Fallback so the app can start, but bcrypt is strongly recommended.
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 200_000
    ).hex()
    return f"pbkdf2${salt}${digest}"

def verify_password(password, stored):
    if not stored:
        return False
    try:
        if stored.startswith("$2"):
            return bool(bcrypt and bcrypt.checkpw(password.encode(), stored.encode()))
        if stored.startswith("pbkdf2$"):
            _, salt, digest = stored.split("$", 2)
            check = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), salt.encode(), 200_000
            ).hex()
            return hmac.compare_digest(check, digest)
    except Exception:
        return False
    return False

def priority_rank(priority):
    return {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}.get(priority, 4)

def case_bucket(case):
    status = case.get("status", "")
    if status in ("Completed", "Cancelled"):
        return "Closed"
    priority = case.get("priority", "Medium")
    due = parse_dt(case.get("due_at"))
    if priority == "Critical":
        return "Critical"
    if due and due <= now():
        return "Critical"
    if due and due <= now() + timedelta(hours=DUE_SOON_HOURS):
        return "Due Soon"
    return "On Track"

def urgency_score(case):
    bucket = case_bucket(case)
    bucket_rank = {"Critical": 0, "Due Soon": 1, "On Track": 2, "Closed": 3}.get(bucket, 3)
    return (
        bucket_rank,
        priority_rank(case.get("priority")),
        parse_dt(case.get("due_at")) or datetime.max,
        parse_dt(case.get("created_at")) or datetime.max,
    )

def is_active_case(case):
    return case.get("status") not in ("Completed", "Cancelled")

def case_row_class(case):
    bucket = case_bucket(case)
    return {"Critical": "case-red", "Due Soon": "case-yellow", "On Track": "case-green"}.get(bucket, "")

# ------------------------- MongoDB ---------------------------

@st.cache_resource(show_spinner=False)
def get_mongo_client():
    uri = None
    try:
        uri = st.secrets.get("MONGO_URI")
    except Exception:
        pass
    uri = uri or os.getenv("MONGO_URI") or os.getenv("MONGODB_URI")
    if not uri:
        raise RuntimeError(
            "MongoDB connection is not configured. Add MONGO_URI to "
            ".streamlit/secrets.toml or as an environment variable."
        )
    client = MongoClient(
        uri,
        maxPoolSize=30,
        minPoolSize=2,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        retryWrites=True,
    )
    client.admin.command("ping")
    return client

def get_db():
    return get_mongo_client()[DB_NAME]

def init_db():
    db = get_db()
    db[USER_COLLECTION].create_index([("email", ASCENDING)], unique=True)
    db[USER_COLLECTION].create_index([("employee_id", ASCENDING)], unique=True, sparse=True)
    db["cases"].create_index([("status", ASCENDING), ("due_at", ASCENDING)])
    db["cases"].create_index([("assigned_to", ASCENDING), ("status", ASCENDING)])
    db["cases"].create_index([("created_at", DESCENDING)])
    db["alerts"].create_index([("user_email", ASCENDING), ("read", ASCENDING), ("created_at", DESCENDING)])
    db["schedules"].create_index([("email", ASCENDING), ("schedule_date", ASCENDING)])
    db["requests"].create_index([("status", ASCENDING), ("created_at", DESCENDING)])
    db["audit_logs"].create_index([("created_at", DESCENDING)])

    # Guarantee the requested owner is an admin.
    db[USER_COLLECTION].update_one(
        {"email": AUTO_ADMIN_EMAIL},
        {"$set": {"role": "admin", "email": AUTO_ADMIN_EMAIL, "updated_at": now()},
         "$setOnInsert": {
             "first_name": "Arianne May",
             "last_name": "Escabillas",
             "created_at": now(),
             "aux": "Admin Task",
             "active": True,
         }},
        upsert=True,
    )

def audit(action, actor, target=None, details=None):
    get_db()["audit_logs"].insert_one({
        "created_at": now(),
        "actor": normalize_email(actor),
        "action": action,
        "target": target,
        "details": details or {},
    })

def create_alert(email, title, message, severity="info"):
    get_db()["alerts"].insert_one({
        "user_email": normalize_email(email),
        "title": title,
        "message": message,
        "severity": severity,
        "read": False,
        "created_at": now(),
    })

# ------------------------- Auth -------------------------------

def get_user(email):
    return get_db()[USER_COLLECTION].find_one({"email": normalize_email(email)})

def sign_up(data):
    db = get_db()
    email = normalize_email(data["email"])
    if not re.match(r"^[A-Za-z0-9._%+-]+@hpe\.com$", email):
        return False, "Use a valid HPE email address ending in @hpe.com."
    if len(data["password"]) < 8:
        return False, "Password must be at least 8 characters."
    if db[USER_COLLECTION].find_one({"email": email}):
        return False, "An account with that email already exists."
    if db[USER_COLLECTION].find_one({"employee_id": data["employee_id"]}):
        return False, "That employee ID is already registered."

    doc = {
        "first_name": data["first_name"].strip(),
        "last_name": data["last_name"].strip(),
        "employee_id": data["employee_id"].strip(),
        "email": email,
        "birthday": str(data["birthday"]),
        "home_address": data["home_address"].strip(),
        "contact_number": data["contact_number"].strip(),
        "password_hash": hash_password(data["password"]),
        "role": "regular",
        "aux": "Busy - Away",
        "active": True,
        "kicked": False,
        "created_at": now(),
        "updated_at": now(),
        "daily_case_count": 0,
        "mtd_case_count": 0,
        "pto_allocation": {"PTO": 0, "Sick Leave": 0, "Emergency Leave": 0},
    }
    try:
        db[USER_COLLECTION].insert_one(doc)
        audit("user_signup", email)
        return True, "Account created. You can now sign in."
    except DuplicateKeyError:
        return False, "Email or employee ID is already registered."
    except Exception as exc:
        return False, f"Could not create account: {exc}"

def authenticate(email, password):
    user = get_user(email)
    if not user or not verify_password(password, user.get("password_hash", "")):
        return None
    if not user.get("active", True):
        return None
    if user.get("kicked"):
        return None
    return user

def logout():
    st.session_state.pop("user", None)
    st.session_state.pop("selected_case", None)
    st.session_state.pop("selected_tile", None)
    st.rerun()

# ------------------------- Case assignment -------------------

def eligible_agents():
    db = get_db()
    excluded = {"Break", "Lunch", "In a Meeting", "Coaching", "Busy - Away", "Unscheduled Break", "Admin Task"}
    return list(db[USER_COLLECTION].find(
        {
            "role": "regular",
            "active": True,
            "kicked": {"$ne": True},
            "aux": {"$nin": list(excluded)},
        },
        {
            "email": 1, "first_name": 1, "last_name": 1,
            "aux": 1, "daily_case_count": 1, "mtd_case_count": 1,
        }
    ))

def active_load(email):
    return get_db()["cases"].count_documents({
        "assigned_to": normalize_email(email),
        "status": {"$nin": ["Completed", "Cancelled"]},
    })

def fair_agent():
    agents = eligible_agents()
    if not agents:
        return None

    # Fairness uses today's assigned count first, then active load,
    # then MTD count, then the oldest last-assignment timestamp.
    db = get_db()
    scored = []
    for a in agents:
        email = a["email"]
        recent = db["cases"].find_one(
            {"assigned_to": email},
            sort=[("assigned_at", DESCENDING)],
            projection={"assigned_at": 1},
        )
        last_assigned = parse_dt(recent.get("assigned_at")) if recent else datetime.min
        scored.append((
            int(a.get("daily_case_count", 0)),
            active_load(email),
            int(a.get("mtd_case_count", 0)),
            last_assigned,
            email,
            a,
        ))
    scored.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4]))
    return scored[0][5]

def assign_case(case_id, actor="system"):
    db = get_db()
    case = db["cases"].find_one({"_id": case_id})
    if not case or case.get("assigned_to"):
        return False, "Case is already assigned or does not exist."

    agent = fair_agent()
    if not agent:
        return False, "No eligible agent is currently available."

    email = agent["email"]
    ts = now()

    result = db["cases"].update_one(
        {"_id": case_id, "assigned_to": {"$in": [None, ""]}},
        {"$set": {
            "assigned_to": email,
            "assigned_at": ts,
            "status": "Assigned",
            "updated_at": ts,
            "last_updated_by": actor,
        }},
    )
    if result.modified_count:
        db[USER_COLLECTION].update_one(
            {"email": email},
            {"$inc": {"daily_case_count": 1, "mtd_case_count": 1},
             "$set": {"updated_at": ts}},
        )
        create_alert(
            email,
            "New case assigned",
            f"Case {case.get('case_number', oid_str(case_id))} was automatically assigned to you.",
            "info",
        )
        audit("case_auto_assigned", actor, oid_str(case_id), {"agent": email})
        return True, email
    return False, "Case assignment changed before it could be completed."

def auto_assign_new_cases():
    db = get_db()
    for case in db["cases"].find({
        "status": {"$in": ["New", "Assigned"]},
        "$or": [{"assigned_to": {"$exists": False}}, {"assigned_to": None}, {"assigned_to": ""}],
    }).sort("created_at", ASCENDING).limit(25):
        assign_case(case["_id"])

# ------------------------- Alerts -----------------------------

def generate_case_alerts(user_email=None):
    db = get_db()
    query = {"status": {"$nin": ["Completed", "Cancelled"]}}
    if user_email:
        query["assigned_to"] = normalize_email(user_email)

    cases = list(db["cases"].find(query).limit(300))
    existing_recent = {
        (a.get("user_email"), a.get("title"), a.get("case_id"))
        for a in db["alerts"].find({
            "created_at": {"$gte": now() - timedelta(hours=24)},
            "case_id": {"$exists": True},
        }, {"user_email": 1, "title": 1, "case_id": 1})
    }

    for c in cases:
        email = c.get("assigned_to")
        if not email:
            continue
        cid = oid_str(c["_id"])
        due = parse_dt(c.get("due_at"))
        title = None
        message = None
        severity = "info"

        if c.get("priority") == "Critical" or (due and due <= now()):
            title = "Critical case"
            message = f"{c.get('case_number', cid)} requires immediate attention."
            severity = "critical"
        elif due and due <= now() + timedelta(hours=DUE_SOON_HOURS):
            title = "Case due soon"
            message = f"{c.get('case_number', cid)} is due within {DUE_SOON_HOURS} hours."
            severity = "warning"
        elif hours_since(c.get("last_updated_at")) and hours_since(c.get("last_updated_at")) >= STALE_HOURS:
            title = "Case needs an update"
            message = f"{c.get('case_number', cid)} has not been updated for 24 hours."
            severity = "warning"

        key = (normalize_email(email), title, cid)
        if title and key not in existing_recent:
            db["alerts"].insert_one({
                "user_email": normalize_email(email),
                "title": title,
                "message": message,
                "severity": severity,
                "case_id": c["_id"],
                "read": False,
                "created_at": now(),
            })

def unread_alerts(email):
    return list(get_db()["alerts"].find(
        {"user_email": normalize_email(email), "read": False},
        sort=[("created_at", DESCENDING)],
        limit=20,
    ))

# ------------------------- Schedule / Requests ---------------

def get_schedule(email, start_date, days=1):
    end_date = start_date + timedelta(days=days)
    return list(get_db()["schedules"].find({
        "email": normalize_email(email),
        "schedule_date": {"$gte": start_date.isoformat(), "$lt": end_date.isoformat()},
    }).sort([("schedule_date", ASCENDING), ("start_time", ASCENDING)]))

def create_default_schedule(email, target_date):
    db = get_db()
    day = target_date.weekday()
    if day >= 5:
        return

    existing = db["schedules"].count_documents({
        "email": normalize_email(email),
        "schedule_date": target_date.isoformat(),
    })
    if existing:
        return

    # Default 8-hour day. Break/lunch positions are subsequently
    # recalculated by admin using queue coverage.
    blocks = [
        ("Work", "08:00", "10:00"),
        ("Break", "10:00", "10:15"),
        ("Work", "10:15", "12:15"),
        ("Lunch", "12:15", "13:15"),
        ("Work", "13:15", "15:15"),
        ("Break", "15:15", "15:30"),
        ("Work", "15:30", "17:00"),
    ]
    docs = [{
        "email": normalize_email(email),
        "schedule_date": target_date.isoformat(),
        "activity": activity,
        "start_time": start,
        "end_time": end,
        "status": "Approved",
        "created_at": now(),
        "updated_at": now(),
    } for activity, start, end in blocks]
    db["schedules"].insert_many(docs)

def auto_schedule_all_agents(target_date=None):
    target_date = target_date or date.today()
    db = get_db()
    agents = list(db[USER_COLLECTION].find({"role": "regular", "active": True}, {"email": 1}))
    for a in agents:
        create_default_schedule(a["email"], target_date)

def submit_request(user, request_type, payload):
    db = get_db()
    doc = {
        "request_type": request_type,
        "email": user["email"],
        "created_at": now(),
        "status": "Pending",
        "payload": payload,
    }

    if request_type in ("Sick Leave", "Emergency Leave"):
        doc["status"] = "Approved"
    elif request_type == "PTO":
        selected = date.fromisoformat(payload["date"])
        allocation = float(user.get("pto_allocation", {}).get("PTO", 0))
        used = db["requests"].count_documents({
            "email": user["email"],
            "request_type": "PTO",
            "status": "Approved",
            "payload.date": payload["date"],
        })
        if allocation - used <= 0:
            return False, "No allocation for the selected date."
        doc["status"] = "Approved"

    db["requests"].insert_one(doc)
    audit("request_submitted", user["email"], details={"type": request_type})
    if user["email"] != AUTO_ADMIN_EMAIL:
        create_alert(AUTO_ADMIN_EMAIL, "New request submitted", f"{user['email']} submitted {request_type}.")
    return True, f"{request_type} submitted successfully."

def approve_request(request_id, admin_email):
    db = get_db()
    req = db["requests"].find_one({"_id": request_id})
    if not req:
        return False
    db["requests"].update_one(
        {"_id": request_id},
        {"$set": {"status": "Approved", "approved_by": admin_email, "approved_at": now()}}
    )
    create_alert(req["email"], "Request approved", f"Your {req['request_type']} request was approved.")
    audit("request_approved", admin_email, oid_str(request_id))
    return True

def deny_request(request_id, admin_email):
    db = get_db()
    req = db["requests"].find_one({"_id": request_id})
    if not req:
        return False
    db["requests"].update_one(
        {"_id": request_id},
        {"$set": {"status": "Denied", "approved_by": admin_email, "approved_at": now()}}
    )
    create_alert(req["email"], "Request denied", f"Your {req['request_type']} request was denied.")
    audit("request_denied", admin_email, oid_str(request_id))
    return True

# ------------------------- Data helpers -----------------------

def get_cases_for_user(user):
    db = get_db()
    q = {"status": {"$nin": ["Completed", "Cancelled"]}}
    if user["role"] != "admin":
        q["assigned_to"] = user["email"]
    return list(db["cases"].find(q).sort([("priority", ASCENDING), ("due_at", ASCENDING)]).limit(1000))

def get_case(case_id):
    try:
        from bson import ObjectId
        return get_db()["cases"].find_one({"_id": ObjectId(case_id)})
    except Exception:
        return None

def save_case_update(case_id, user, fields):
    db = get_db()
    fields["updated_at"] = now()
    fields["last_updated_at"] = now()
    fields["last_updated_by"] = user["email"]
    result = db["cases"].update_one({"_id": case_id}, {"$set": fields})
    if result.modified_count:
        audit("case_updated", user["email"], oid_str(case_id), fields)
        return True
    return False

def contract_breach_message(case, reason):
    return (
        f"Subject: Contract Breach – Case {case.get('case_number', '')}\n\n"
        f"Hello Vendor,\n\n"
        f"This is to formally document a contract breach related to case "
        f"{case.get('case_number', '')}. The identified violation is: {reason}\n\n"
        f"Please provide the required corrective action and an updated delivery "
        f"commitment at the earliest opportunity.\n\n"
        f"Regards,\nHPE Support"
    )

# ------------------------- Login UI ---------------------------

def login_screen():
    st.markdown(
        """
        <div class="hero">
          <h1>HPE CaseFlow</h1>
          <p>Case management • Queue coverage • Agent schedules • Adherence</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1, 1])
    with left:
        st.subheader("Welcome")
        st.write("Sign in to access your role-based workspace.")
        st.caption("New to CaseFlow? Create your profile using your HPE email.")

    with right:
        action = st.radio("Account", ["Sign in", "Sign up"], horizontal=True, key="auth_action")

        if action == "Sign in":
            with st.form("login_form"):
                email = st.text_input("HPE email")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Sign in", use_container_width=True)
            if submitted:
                try:
                    init_db()
                    user = authenticate(email, password)
                    if user:
                        if normalize_email(user["email"]) == AUTO_ADMIN_EMAIL:
                            user["role"] = "admin"
                            user["aux"] = "Admin Task"
                            get_db()[USER_COLLECTION].update_one(
                                {"email": AUTO_ADMIN_EMAIL},
                                {"$set": {"role": "admin", "aux": "Admin Task", "updated_at": now()}}
                            )
                        else:
                            # Requested default for regular agents.
                            if user.get("role") != "admin" and not user.get("aux"):
                                user["aux"] = "Busy - Away"
                        st.session_state.user = user
                        st.rerun()
                    else:
                        st.error("Invalid account, password, or inactive/kicked account.")
                except Exception as exc:
                    st.error(str(exc))

        else:
            with st.form("signup_form"):
                c1, c2 = st.columns(2)
                first = c1.text_input("First name")
                last = c2.text_input("Last name")
                employee_id = st.text_input("Employee ID")
                email = st.text_input("HPE email address")
                birthday = st.date_input("Birthday", min_value=date(1940,1,1), max_value=date.today())
                address = st.text_area("Home address")
                phone = st.text_input("Contact number")
                password = st.text_input("Password", type="password")
                confirm = st.text_input("Confirm password", type="password")
                submit = st.form_submit_button("Create account", use_container_width=True)

            if submit:
                if password != confirm:
                    st.error("Passwords do not match.")
                elif not all([first, last, employee_id, email, address, phone, password]):
                    st.error("Complete all required fields.")
                else:
                    try:
                        init_db()
                        ok, msg = sign_up({
                            "first_name": first,
                            "last_name": last,
                            "employee_id": employee_id,
                            "email": email,
                            "birthday": birthday,
                            "home_address": address,
                            "contact_number": phone,
                            "password": password,
                        })
                        (st.success if ok else st.error)(msg)
                    except Exception as exc:
                        st.error(str(exc))

# ------------------------- Sidebar ----------------------------

def render_sidebar(user):
    with st.sidebar:
        st.markdown("### HPE CaseFlow")
        st.caption(f"{user.get('first_name','')} {user.get('last_name','')}")
        st.caption(user["email"])

        unread = unread_alerts(user["email"])
        if unread:
            st.warning(f"🔔 {len(unread)} unread alert(s)")

        if user["role"] == "admin":
            options = ["Dashboard", "Agent Schedule", "Cases", "Agents", "Requests", "Reports", "Settings"]
        else:
            options = ["Dashboard", "My Schedule", "My Cases", "Requests", "Profile"]

        page = st.radio("Navigation", options, key="nav_page")

        st.divider()
        st.markdown("**Current AUX**")
        aux_options = AUX_OPTIONS if user["role"] == "admin" else [
            "Available", "Break", "Lunch", "In a Meeting", "Coaching", "Busy - Away", "Unscheduled Break"
        ]
        current_aux = st.selectbox("AUX", aux_options, index=aux_options.index(user.get("aux", "Busy - Away"))
                                   if user.get("aux", "Busy - Away") in aux_options else 0,
                                   key="current_aux")
        if st.button("Save AUX", use_container_width=True):
            get_db()[USER_COLLECTION].update_one(
                {"email": user["email"]},
                {"$set": {"aux": current_aux, "updated_at": now()}}
            )
            st.session_state.user["aux"] = current_aux
            audit("aux_changed", user["email"], details={"aux": current_aux})
            st.success("AUX updated.")
            st.rerun()

        if st.button("Refresh now", use_container_width=True):
            st.rerun()
        if st.button("Sign out", use_container_width=True):
            logout()

    return page

# ------------------------- Dashboard --------------------------

def metric_button(label, value, key, selected):
    cls = "metric-card"
    if selected == key:
        cls += " case-green"
    st.markdown(
        f'<div class="{cls}"><div class="metric-title">{label}</div>'
        f'<div class="metric-value">{value}</div></div>',
        unsafe_allow_html=True,
    )
    return st.button(f"View {label}", key=f"metric_{key}", use_container_width=True)

def render_alerts(user):
    alerts = unread_alerts(user["email"])
    if not alerts:
        return
    with st.expander(f"🔔 Alerts ({len(alerts)})", expanded=True):
        for a in alerts:
            st.markdown(
                f'<div class="alert-box"><b>{a.get("title")}</b><br>{a.get("message")}'
                f'<div class="small-note">{fmt_dt(a.get("created_at"))}</div></div>',
                unsafe_allow_html=True,
            )
            if st.button("Mark read", key=f"read_{a['_id']}"):
                get_db()["alerts"].update_one({"_id": a["_id"]}, {"$set": {"read": True}})
                st.rerun()

def render_case_card(case, user):
    bucket = case_bucket(case)
    css = case_row_class(case)
    due = parse_dt(case.get("due_at"))
    assigned = case.get("assigned_to") or "Unassigned"
    st.markdown(
        f"""
        <div class="case-card {css}">
          <span class="case-id">{case.get('case_number', oid_str(case['_id']))}</span>
          <span class="badge">{case.get('priority','Medium')}</span>
          <span class="badge">{case.get('status','New')}</span>
          <span class="badge">{bucket}</span>
          <br>
          <b>{case.get('title','Untitled case')}</b>
          <div class="muted">{case.get('description','')[:180]}</div>
          <div class="small-note">
            Assigned: {assigned} · Due: {fmt_dt(due)} · Last update: {fmt_dt(case.get('last_updated_at'))}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Open case", key=f"open_{case['_id']}"):
        st.session_state.selected_case = oid_str(case["_id"])
        st.rerun()

def render_case_list(cases, user, title="Active Cases"):
    st.subheader(title)
    search = st.text_input(
        "Search cases",
        placeholder="Case number, title, vendor, technician, status...",
        key=f"search_{title}",
    )
    filtered = cases
    if search:
        s = search.lower()
        filtered = [
            c for c in cases
            if s in safe_text(c.get("case_number")).lower()
            or s in safe_text(c.get("title")).lower()
            or s in safe_text(c.get("description")).lower()
            or s in safe_text(c.get("vendor_name")).lower()
            or s in safe_text(c.get("technician_name")).lower()
            or s in safe_text(c.get("status")).lower()
        ]

    filtered.sort(key=urgency_score)
    if not filtered:
        st.info("No cases match the current view.")
    else:
        for c in filtered:
            render_case_card(c, user)

def render_dashboard(user):
    db = get_db()
    auto_assign_new_cases()
    generate_case_alerts(user["email"])
    render_alerts(user)

    cases = get_cases_for_user(user)
    active = [c for c in cases if is_active_case(c)]

    critical = [c for c in active if case_bucket(c) == "Critical"]
    due_soon = [c for c in active if case_bucket(c) == "Due Soon"]
    on_track = [c for c in active if case_bucket(c) == "On Track"]

    if user["role"] == "admin":
        all_active = list(db["cases"].find({"status": {"$nin": ["Completed", "Cancelled"]}}))
        active = all_active
        critical = [c for c in active if case_bucket(c) == "Critical"]
        due_soon = [c for c in active if case_bucket(c) == "Due Soon"]
        on_track = [c for c in active if case_bucket(c) == "On Track"]

    st.markdown(
        f"""
        <div class="hero">
          <h1>{'Admin Command Center' if user['role']=='admin' else 'My Case Dashboard'}</h1>
          <p>{now().strftime('%A, %B %d, %Y · %I:%M %p')} · Live queue monitoring</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    cols = st.columns(4)
    labels = [
        ("Active Cases", len(active), "all"),
        ("Critical", len(critical), "critical"),
        ("Due Soon", len(due_soon), "due"),
        ("On Track", len(on_track), "track"),
    ]
    for col, (label, value, key) in zip(cols, labels):
        with col:
            st.markdown(
                f'<div class="metric-card"><div class="metric-title">{label}</div>'
                f'<div class="metric-value">{value}</div>'
                f'<div class="metric-sub">Click below to filter</div></div>',
                unsafe_allow_html=True,
            )
            if st.button(f"View {label}", key=f"tile_{key}", use_container_width=True):
                st.session_state.selected_tile = key

    selected = st.session_state.get("selected_tile", "all")
    if selected == "critical":
        shown = critical
        heading = "Critical Cases"
    elif selected == "due":
        shown = due_soon
        heading = "Cases Due Soon"
    elif selected == "track":
        shown = on_track
        heading = "On-Track Cases"
    else:
        shown = active
        heading = "All Active Cases"

    if user["role"] == "admin":
        st.subheader("Queue & Agent Coverage")
        render_agent_status_strip()

    render_case_list(shown, user, heading)

def render_agent_status_strip():
    agents = list(get_db()[USER_COLLECTION].find(
        {"role": "regular", "active": True},
        {"first_name":1,"last_name":1,"email":1,"aux":1,"daily_case_count":1}
    ).sort("first_name", ASCENDING))
    if not agents:
        st.info("No regular agents are registered.")
        return

    rows = []
    for a in agents:
        rows.append({
            "Agent": f"{a.get('first_name','')} {a.get('last_name','')}",
            "AUX": a.get("aux","Busy - Away"),
            "Active": active_load(a["email"]),
            "Assigned Today": a.get("daily_case_count", 0),
            "Email": a["email"],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ------------------------- Case detail ------------------------

def render_case_detail(user):
    case_id = st.session_state.get("selected_case")
    case = get_case(case_id)
    if not case:
        st.warning("Case not found.")
        st.session_state.pop("selected_case", None)
        return

    if user["role"] != "admin" and case.get("assigned_to") != user["email"]:
        st.error("This case is not assigned to your profile.")
        return

    if st.button("← Back to dashboard"):
        st.session_state.pop("selected_case", None)
        st.rerun()

    st.markdown(
        f"""
        <div class="hero">
          <h1>{case.get('case_number', oid_str(case['_id']))}</h1>
          <p>{case.get('title','Untitled case')} · {case.get('priority','Medium')} · {case.get('status','New')}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Priority", case.get("priority", "Medium"))
    c2.metric("Status", case.get("status", "New"))
    c3.metric("Assigned", case.get("assigned_to") or "Unassigned")
    c4.metric("Due", fmt_dt(case.get("due_at")))

    with st.expander("Case information", expanded=True):
        st.write(case.get("description", "No description."))
        st.write(f"**Vendor:** {case.get('vendor_name','—')}")
        st.write(f"**Technician:** {case.get('technician_name','—')}")
        st.write(f"**Vendor phone:** {case.get('vendor_phone','—')}")
        st.write(f"**Last update:** {fmt_dt(case.get('last_updated_at'))}")

    if user["role"] == "admin" or case.get("assigned_to") == user["email"]:
        st.subheader("Case actions")
        status = st.selectbox("Status", CASE_STATUSES, index=CASE_STATUSES.index(case.get("status"))
                              if case.get("status") in CASE_STATUSES else 0)
        note = st.text_area("Update / work note", value=case.get("latest_note",""))

        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Save case update", use_container_width=True):
                save_case_update(case["_id"], user, {
                    "status": status,
                    "latest_note": note,
                })
                st.success("Case updated and saved.")
                st.rerun()

        with c2:
            sf = case.get("salesforce_url") or DEFAULT_SF_URL
            st.link_button("Contact Vendor / Technician", sf, use_container_width=True)

        with c3:
            phone = safe_text(case.get("vendor_phone"))
            if phone:
                st.markdown(
                    f'<a href="tel:{quote_plus(phone)}" style="text-decoration:none">'
                    f'<button style="width:100%;height:38px">📞 Call Vendor</button></a>',
                    unsafe_allow_html=True,
                )
                st.code(phone, language=None)
            else:
                st.caption("No vendor number is stored for this case.")

        st.subheader("Contract breach")
        reason = st.selectbox("Contract breached reason", [""] + list(BREACH_REASONS.keys()))
        if reason:
            generated = contract_breach_message(case, BREACH_REASONS[reason])
            edited = st.text_area("Generated message — editable before sending", generated, height=230)
            if st.button("Mark Contract Breached & Save", use_container_width=True):
                save_case_update(case["_id"], user, {
                    "status": "Contract Breached",
                    "contract_breached": True,
                    "contract_breach_reason": reason,
                    "contract_breach_message": edited,
                })
                st.success("Contract breach saved.")
                st.rerun()
            st.info("The Email button can be connected to your approved email connector later. "
                    "The generated message is already persisted with the case when saved.")

# ------------------------- Regular pages ---------------------

def render_my_schedule(user):
    st.header("My Schedule")
    view = st.radio("View", ["Day", "Week", "Month"], horizontal=True)
    days = {"Day": 1, "Week": 7, "Month": 31}[view]
    start = date.today()
    create_default_schedule(user["email"], start)
    rows = get_schedule(user["email"], start, days)

    if not rows:
        st.info("No schedule has been published.")
        return
    df = pd.DataFrame([{
        "Date": r.get("schedule_date"),
        "Activity": r.get("activity"),
        "Start": r.get("start_time"),
        "End": r.get("end_time"),
        "Status": r.get("status"),
    } for r in rows])
    st.dataframe(df, use_container_width=True, hide_index=True)

def render_requests(user):
    st.header("Leave & Schedule Requests")
    st.caption("Sick Leave and Emergency Leave are auto-approved. PTO is auto-approved only when allocation is available.")

    request_type = st.selectbox("Request type", REQUEST_TYPES)
    if request_type in ("Sick Leave", "Emergency Leave", "PTO"):
        selected = st.date_input("Date", value=date.today(), min_value=date.today())
        reason = st.text_area("Reason")
        if st.button("Submit request"):
            ok, msg = submit_request(user, request_type, {
                "date": selected.isoformat(),
                "reason": reason,
            })
            (st.success if ok else st.error)(msg)

    elif request_type == "Schedule Swap":
        agents = list(get_db()[USER_COLLECTION].find(
            {"role":"regular","active":True,"email":{"$ne":user["email"]}},
            {"email":1,"first_name":1,"last_name":1}
        ))
        target = st.selectbox(
            "Swap with",
            agents,
            format_func=lambda a: f"{a.get('first_name','')} {a.get('last_name','')} — {a['email']}",
        )
        swap_date = st.date_input("Swap date", value=date.today(), min_value=date.today())
        if st.button("Submit mutual swap request"):
            ok, msg = submit_request(user, request_type, {
                "date": swap_date.isoformat(),
                "with_agent": target["email"] if target else "",
                "mutual_consent": True,
            })
            (st.success if ok else st.error)(msg)

    else:
        st.info("Select a request type to continue.")

    st.subheader("My submitted requests")
    reqs = list(get_db()["requests"].find({"email": user["email"]}).sort("created_at", DESCENDING).limit(50))
    if reqs:
        st.dataframe(pd.DataFrame([{
            "Type": r["request_type"],
            "Status": r["status"],
            "Submitted": fmt_dt(r.get("created_at")),
            "Payload": str(r.get("payload", {})),
        } for r in reqs]), use_container_width=True, hide_index=True)

def render_profile(user):
    st.header("My Profile")
    st.write(f"**Name:** {user.get('first_name')} {user.get('last_name')}")
    st.write(f"**Employee ID:** {user.get('employee_id','—')}")
    st.write(f"**Email:** {user.get('email')}")
    st.write(f"**Birthday:** {user.get('birthday','—')}")
    st.write(f"**Home address:** {user.get('home_address','—')}")
    st.write(f"**Contact number:** {user.get('contact_number','—')}")
    st.write(f"**Role:** {user.get('role')}")
    st.write(f"**AUX:** {user.get('aux')}")
    st.subheader("PTO Allocation")
    st.json(user.get("pto_allocation", {}))

# ------------------------- Admin pages ------------------------

def render_admin_schedule(user):
    st.header("Agent Schedule")
    st.caption("Approve schedule changes/requests and publish queue coverage schedules.")

    c1, c2 = st.columns(2)
    target_date = c1.date_input("Schedule date", value=date.today())
    if c2.button("Auto-schedule all agents"):
        auto_schedule_all_agents(target_date)
        st.success("Default schedules generated. Admin can adjust activities below.")
        st.rerun()

    st.subheader("Pending requests")
    pending = list(get_db()["requests"].find({"status":"Pending"}).sort("created_at", DESCENDING).limit(100))
    for r in pending:
        with st.container(border=True):
            st.write(f"**{r['request_type']}** — {r['email']} — {fmt_dt(r['created_at'])}")
            st.json(r.get("payload", {}))
            a, d = st.columns(2)
            if a.button("Approve", key=f"approve_{r['_id']}"):
                approve_request(r["_id"], user["email"])
                st.rerun()
            if d.button("Deny", key=f"deny_{r['_id']}"):
                deny_request(r["_id"], user["email"])
                st.rerun()

    st.subheader("Add activity")
    agents = list(get_db()[USER_COLLECTION].find({"role":"regular","active":True},
                                                   {"email":1,"first_name":1,"last_name":1}))
    if agents:
        with st.form("activity_form"):
            agent = st.selectbox("Agent", agents,
                                 format_func=lambda a: f"{a.get('first_name')} {a.get('last_name')}")
            activity = st.selectbox("Activity", ["Meeting", "Coaching", "Admin Task", "Break", "Lunch", "Work"])
            start = st.time_input("Start", value=dtime(10,0))
            end = st.time_input("End", value=dtime(10,30))
            if st.form_submit_button("Add activity"):
                get_db()["schedules"].insert_one({
                    "email": agent["email"],
                    "schedule_date": target_date.isoformat(),
                    "activity": activity,
                    "start_time": start.strftime("%H:%M"),
                    "end_time": end.strftime("%H:%M"),
                    "status": "Approved",
                    "created_at": now(),
                    "updated_at": now(),
                })
                create_alert(agent["email"], "Schedule updated",
                             f"{activity} was added to your schedule for {target_date}.")
                audit("schedule_activity_added", user["email"], details={"agent":agent["email"],"activity":activity})
                st.success("Activity added.")

    st.subheader("Coverage view")
    coverage = []
    for a in agents:
        rows = get_schedule(a["email"], target_date, 1)
        for r in rows:
            coverage.append({
                "Agent": f"{a.get('first_name')} {a.get('last_name')}",
                "Activity": r["activity"],
                "Start": r["start_time"],
                "End": r["end_time"],
                "Status": r["status"],
            })
    if coverage:
        st.dataframe(pd.DataFrame(coverage), use_container_width=True, hide_index=True)

def render_admin_cases(user):
    st.header("All Cases")
    cases = list(get_db()["cases"].find().sort("created_at", DESCENDING).limit(2000))
    render_case_list(cases, user, "Case Management")

    st.subheader("Manual assignment")
    unassigned = [c for c in cases if is_active_case(c) and not c.get("assigned_to")]
    if unassigned:
        options = st.selectbox("Unassigned case", unassigned,
                               format_func=lambda c: c.get("case_number", oid_str(c["_id"])))
        if st.button("Auto-assign selected case"):
            ok, result = assign_case(options["_id"], user["email"])
            (st.success if ok else st.error)(f"Assigned to {result}" if ok else result)

def render_agents(user):
    st.header("Agent Management")
    agents = list(get_db()[USER_COLLECTION].find().sort([("role", ASCENDING), ("first_name", ASCENDING)]))
    rows = []
    for a in agents:
        rows.append({
            "Name": f"{a.get('first_name','')} {a.get('last_name','')}",
            "Email": a.get("email"),
            "Role": a.get("role"),
            "AUX": a.get("aux"),
            "Active Cases": active_load(a["email"]) if a.get("role") == "regular" else 0,
            "Assigned Today": a.get("daily_case_count", 0),
            "Active": a.get("active", True),
            "Kicked": a.get("kicked", False),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.subheader("Agent actions")
    if agents:
        selected = st.selectbox("Agent", agents,
                                format_func=lambda a: f"{a.get('first_name')} {a.get('last_name')} — {a.get('email')}")
        st.write(f"Current AUX: **{selected.get('aux','Busy - Away')}**")
        c1, c2, c3 = st.columns(3)
        if c1.button("Kick / remove from auto-assignment"):
            get_db()[USER_COLLECTION].update_one(
                {"_id": selected["_id"]},
                {"$set":{"kicked":True,"aux":"Busy - Away","updated_at":now()}}
            )
            create_alert(selected["email"], "Removed from queue", "An administrator temporarily removed you from auto-assignment.", "warning")
            audit("agent_kicked", user["email"], selected["email"])
            st.success("Agent removed from auto-assignment.")
        if c2.button("Restore to queue"):
            get_db()[USER_COLLECTION].update_one(
                {"_id": selected["_id"]},
                {"$set":{"kicked":False,"aux":"Available","updated_at":now()}}
            )
            create_alert(selected["email"], "Returned to queue", "You are available for auto-assignment.")
            audit("agent_restored", user["email"], selected["email"])
            st.success("Agent restored.")
        if c3.button("View bucket"):
            st.session_state["admin_bucket_agent"] = selected["email"]
            st.rerun()

    if st.session_state.get("admin_bucket_agent"):
        email = st.session_state["admin_bucket_agent"]
        st.subheader(f"Bucket: {email}")
        bucket = list(get_db()["cases"].find({
            "assigned_to": email,
            "status":{"$nin":["Completed","Cancelled"]},
        }).sort("due_at", ASCENDING))
        render_case_list(bucket, user, f"{email} Bucket")

    st.subheader("Role management")
    st.caption("The automatic admin owner is always protected: " + AUTO_ADMIN_EMAIL)
    if normalize_email(user["email"]) == AUTO_ADMIN_EMAIL:
        target = st.selectbox("User to update", agents,
                              format_func=lambda a: f"{a.get('first_name')} {a.get('last_name')} — {a.get('email')}")
        role = st.selectbox("Role", ["regular", "admin"], index=0 if target.get("role")=="regular" else 1)
        if st.button("Save role"):
            get_db()[USER_COLLECTION].update_one(
                {"_id":target["_id"]},
                {"$set":{"role":role,"updated_at":now()}}
            )
            audit("role_changed", user["email"], target["email"], {"role":role})
            st.success("Role updated.")
            st.rerun()

def render_requests_admin(user):
    st.header("Requests")
    reqs = list(get_db()["requests"].find().sort("created_at", DESCENDING).limit(200))
    if not reqs:
        st.info("No requests.")
        return
    st.dataframe(pd.DataFrame([{
        "Type": r["request_type"],
        "Agent": r["email"],
        "Status": r["status"],
        "Submitted": fmt_dt(r.get("created_at")),
        "Payload": str(r.get("payload", {})),
    } for r in reqs]), use_container_width=True, hide_index=True)

def render_reports(user):
    st.header("Reports")
    db = get_db()
    users = list(db[USER_COLLECTION].find({"role":"regular"}))
    rows = []
    for u in users:
        cases = list(db["cases"].find({"assigned_to":u["email"]}))
        completed = [c for c in cases if c.get("status")=="Completed"]
        active = [c for c in cases if is_active_case(c)]
        rows.append({
            "Agent": f"{u.get('first_name')} {u.get('last_name')}",
            "Email": u["email"],
            "AUX": u.get("aux"),
            "Active Cases": len(active),
            "Completed": len(completed),
            "Assigned Today": u.get("daily_case_count", 0),
            "MTD Assigned": u.get("mtd_case_count", 0),
        })
    df = pd.DataFrame(rows)
    st.subheader("Agent performance")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if not df.empty:
        csv = df.to_csv(index=False).encode()
        st.download_button("Export CSV", csv, "caseflow_agent_report.csv", "text/csv")

    # Daily/MTD attendance/adherence from schedule vs recorded AUX.
    st.subheader("Daily / MTD adherence & attendance")
    st.caption("The framework records schedule/AUX data in MongoDB. You can extend the calculation rules to match your team's official adherence policy.")
    today = date.today().isoformat()
    schedule_count = db["schedules"].count_documents({"schedule_date": today})
    st.metric("Published schedules today", schedule_count)

def render_settings(user):
    st.header("Settings")
    st.subheader("External Salesforce")
    st.write("Admin-only Salesforce access:")
    st.link_button("Open Salesforce", DEFAULT_SF_URL)
    st.caption("Salesforce API integration is intentionally isolated so the API/token can be added later without changing the dashboard UI.")

    st.subheader("MongoDB diagnostics")
    try:
        get_mongo_client().admin.command("ping")
        st.success(f"MongoDB connected · database: {DB_NAME} · user collection: {USER_COLLECTION}")
    except Exception as exc:
        st.error(str(exc))

    st.subheader("System configuration")
    st.write({
        "Polling interval (seconds)": POLL_SECONDS,
        "Due soon window (hours)": DUE_SOON_HOURS,
        "Stale case window (hours)": STALE_HOURS,
        "Auto admin": AUTO_ADMIN_EMAIL,
        "Timezone": str(APP_TZ),
    })

# ------------------------- Realtime loop ---------------------

@st.fragment(run_every=f"{POLL_SECONDS}s")
def realtime_tick(user):
    # Fragment reruns only this lightweight section instead of resetting
    # the full Streamlit page. User-entered widget state remains intact.
    try:
        auto_assign_new_cases()
        generate_case_alerts(user["email"])
        db = get_db()

        active = db["cases"].count_documents({
            "status":{"$nin":["Completed","Cancelled"]}
        })
        unread = db["alerts"].count_documents({
            "user_email":user["email"], "read":False
        })
        st.caption(
            f"🟢 Live · {now().strftime('%I:%M:%S %p')} · "
            f"{active} active queue cases · {unread} unread alerts"
        )
    except Exception as exc:
        st.caption(f"Live polling paused: {exc}")

# ------------------------- Main -------------------------------

def main():
    if "user" not in st.session_state:
        login_screen()
        return

    try:
        init_db()
    except Exception as exc:
        st.error("MongoDB is not available.")
        st.code(str(exc))
        st.info(
            "Set MONGO_URI in .streamlit/secrets.toml, then restart Streamlit. "
            "The app will create the required collections and indexes automatically."
        )
        return

    # Refresh the user record so AUX/role changes from another session
    # are reflected without requiring logout.
    current = get_user(st.session_state.user["email"])
    if not current:
        logout()
    st.session_state.user = current
    user = current

    if user["email"] == AUTO_ADMIN_EMAIL:
        if user.get("role") != "admin" or user.get("aux") != "Admin Task":
            get_db()[USER_COLLECTION].update_one(
                {"email": AUTO_ADMIN_EMAIL},
                {"$set":{"role":"admin","aux":"Admin Task","updated_at":now()}}
            )
            user = get_user(AUTO_ADMIN_EMAIL)
            st.session_state.user = user

    page = render_sidebar(user)

    if st.session_state.get("selected_case"):
        render_case_detail(user)
    elif page == "Dashboard":
        render_dashboard(user)
    elif page == "My Schedule":
        render_my_schedule(user)
    elif page == "My Cases":
        render_case_list(get_cases_for_user(user), user, "My Active Cases")
    elif page == "Requests":
        if user["role"] == "admin":
            render_requests_admin(user)
        else:
            render_requests(user)
    elif page == "Profile":
        render_profile(user)
    elif page == "Agent Schedule":
        render_admin_schedule(user)
    elif page == "Cases":
        render_admin_cases(user)
    elif page == "Agents":
        render_agents(user)
    elif page == "Reports":
        render_reports(user)
    elif page == "Settings":
        render_settings(user)

    # Keep this last so it never takes over the active form/page.
    realtime_tick(user)

if __name__ == "__main__":
    main()
