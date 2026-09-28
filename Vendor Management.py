import os
import io
import smtplib
import secrets
import hashlib
from datetime import datetime, date, time, timedelta
from email.message import EmailMessage
from pathlib import Path

import bcrypt
import pandas as pd
import plotly.express as px
import streamlit as st
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

try:
    import extra_streamlit_components as stx
except ImportError:
    stx = None

# ============================================================
# HPE CaseFlow
# ============================================================

st.set_page_config(
    page_title="HPE CaseFlow",
    page_icon="▣",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CookieManager is initialized inside main() once per Streamlit run.
# The stable key preserves browser-side cookie state across reruns without
# creating a custom component at module import time.
_COOKIE_MANAGER = None

APP_TITLE = "HPE CaseFlow"
DB_NAME = "TeamRoster"
COLLECTION_NAME = "Team Roster Collection"
BASE_DIR = Path(__file__).parent
VENDOR_FILE = BASE_DIR / "vendor_data.xlsx"

AUXES = [
    "Available", "Admin Work", "Not Ready - Online", "Coaching",
    "Meeting", "Lunch", "Break", "Unscheduled Break"
]
AUX_COLOR = {
    "Available": "#16b77a",
    "Admin Work": "#2389e8",
    "Not Ready - Online": "#ef4444",
    "Coaching": "#8b35e8",
    "Meeting": "#f59e0b",
    "Lunch": "#fbbf24",
    "Break": "#94a3b8",
    "Unscheduled Break": "#334155",
}
PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
DEFAULT_VALIDATION = {
    "Case_Status": ["Open", "In Progress", "On Hold", "Pending Vendor",
                    "Pending Internal", "Resolved", "Closed"],
    "Case_Reason": ["Waiting for Vendor Response", "Waiting for Internal Team",
                    "Customer Response", "Investigation", "Pending Approval"],
    "Closure_Type": ["Resolved", "Contact Breach", "Duplicate",
                     "Cancelled", "No Action Required"],
    "Contract_Breach": ["Vendor No Response", "Late Delivery",
                        "Incomplete Information", "Scope Change", "Others"],
}
LEAVE_TYPES = ["PTO", "Sick Leave", "Emergency Leave", "Schedule Swap"]


# ============================================================
# UI
# ============================================================

st.markdown("""
<style>
:root{--navy:#071d33;--navy2:#0d2b46;--teal:#00c7a7;--blue:#0878df;
--bg:#edf4fb;--card:#fff;--text:#0b1730;--muted:#60708a;--border:#dce6f0;
--danger:#ef3f4f;--warning:#f4b72b;--success:#14b879}
.stApp{background:linear-gradient(135deg,#edf5fc 0%,#f8fbff 100%);color:var(--text)}
header[data-testid="stHeader"]{background:transparent}
section[data-testid="stSidebar"]{background:linear-gradient(180deg,#092139,#0c2c47);border-right:1px solid #173b58}
section[data-testid="stSidebar"] *{color:#fff!important}
.block-container{padding:.8rem 1rem 2rem;max-width:100%}
.hpe-topbar{background:linear-gradient(90deg,#071b30,#123653);color:#fff;padding:10px 16px;
border-radius:14px;display:flex;align-items:center;gap:14px;margin-bottom:10px;
box-shadow:0 6px 20px rgba(4,24,42,.12)}
.hpe-brand{font-size:22px;font-weight:800;line-height:1}
.hpe-sub{font-size:12px;opacity:.8;margin-top:4px}
.hpe-logo{width:48px;height:17px;border:4px solid #08d7b7;display:inline-block}
.page-title{font-size:30px;font-weight:800;color:#0a1730;margin:2px 0 0}
.page-subtitle{color:#61728c;font-size:14px;margin-bottom:12px}
.card,.metric{background:#fff;border:1px solid #e0e9f2;border-radius:13px;
box-shadow:0 4px 18px rgba(20,54,84,.05)}
.card{padding:14px}.metric{padding:14px 16px;min-height:105px}
.metric .label{font-size:13px;color:#61728c;font-weight:600}.metric .value{font-size:30px;font-weight:800;line-height:1.1;margin-top:6px}
.metric .delta{font-size:12px;margin-top:6px}
.badge{display:inline-block;padding:4px 9px;border-radius:8px;font-size:12px;font-weight:700}
.badge-critical{background:#ffdfe2;color:#d9253a}.badge-high{background:#ffe9d4;color:#b85b00}
.badge-medium{background:#fff1bd;color:#8d6500}.badge-low{background:#d9f8ee;color:#0b8a63}
.badge-open{background:#e7eef6;color:#28415e}.badge-progress{background:#dceeff;color:#0874c8}
.badge-hold{background:#ffe7b2;color:#8a5c00}.badge-track{background:#d8f6e9;color:#0d8c61}
.table-head{background:#eef4fa;border-radius:8px;padding:8px;font-size:12px;font-weight:800;color:#42536b}
.auth-left{background:linear-gradient(145deg,rgba(3,30,49,.96),rgba(0,86,91,.8));
padding:48px;color:#fff;border-radius:18px 0 0 18px;min-height:620px}
.auth-right{background:#fff;padding:42px;border-radius:0 18px 18px 0;min-height:620px}
.auth-brand{font-size:44px;font-weight:900}.auth-brand span{color:#11d8bb}
.auth-feature{display:flex;gap:13px;margin-top:28px}.auth-icon{border:2px solid #11d8bb;border-radius:50%;padding:10px}
.small-muted{color:#6d7e94;font-size:12px}
button[kind="primary"]{border-radius:9px}
div[data-baseweb="select"]>div,div[data-baseweb="input"]>div{border-radius:9px}
hr{border-color:#e3ebf3}
@media(max-width:900px){.auth-left{display:none}.auth-right{border-radius:18px}.block-container{padding:.6rem}.page-title{font-size:24px}}
</style>
""", unsafe_allow_html=True)


# ============================================================
# MongoDB
# ============================================================

@st.cache_resource(show_spinner=False)
def get_mongo_client():
    uri = None
    try:
        uri = st.secrets["mongo"]["uri"]
    except Exception:
        uri = os.getenv("MONGO_URI")
    if not uri:
        raise RuntimeError(
            'MongoDB is not configured. Add [mongo] uri="..." to '
            '.streamlit/secrets.toml or set MONGO_URI.'
        )

    client = MongoClient(uri, serverSelectionTimeoutMS=3500, connectTimeoutMS=3500)
    client.admin.command("ping")

    # Indexes are created once when the cached Mongo client is initialized.
    # Do not perform create_index() inside collection(), because collection()
    # is called by many read/write helpers during a single page render.
    col = client[DB_NAME][COLLECTION_NAME]
    try:
        col.create_index([("type", ASCENDING)])
        col.create_index([("type", ASCENDING), ("roster_list.email", ASCENDING)])
        col.create_index(
            [("type", ASCENDING), ("case.case_no", ASCENDING)],
            unique=True, sparse=True
        )
        col.create_index(
            [("type", ASCENDING), ("session.token_hash", ASCENDING)],
            unique=True, sparse=True
        )
    except Exception:
        # Existing conflicting indexes/data should not prevent the app from
        # starting; MongoDB will continue using any indexes already present.
        pass

    return client


@st.cache_resource(show_spinner=False)
def get_collection():
    # Collection handles are lightweight references and can safely be cached
    # alongside the cached MongoClient.
    return get_mongo_client()[DB_NAME][COLLECTION_NAME]


def collection():
    return get_collection()


def db_ok():
    try:
        get_mongo_client().admin.command("ping")
        return True
    except Exception:
        return False


def docs(kind, limit=None):
    cur = collection().find({"type": kind}, {"_id": 0})
    if limit:
        cur = cur.limit(limit)
    return list(cur)


def one(kind, query):
    return collection().find_one({"type": kind, **query}, {"_id": 0})


def upsert(kind, query, payload):
    collection().update_one(
        {"type": kind, **query},
        {"$set": {"type": kind, **payload}},
        upsert=True,
    )


def insert(kind, payload):
    collection().insert_one({"type": kind, **payload})


# ============================================================
# Authentication and persistent sessions
# ============================================================

def pw_hash(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def pw_check(password, hashed):
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def cookie_manager():
    return _COOKIE_MANAGER


def set_cookie(name, value, days=30):
    cm = cookie_manager()
    if cm:
        cm.set(name, value, expires_at=datetime.now() + timedelta(days=days))


def get_cookie(name):
    cm = cookie_manager()
    if cm:
        try:
            return cm.get(name)
        except Exception:
            return None
    return None


def delete_cookie(name):
    cm = cookie_manager()
    if cm:
        try:
            cm.delete(name)
        except Exception:
            pass


def full_name(user):
    return f"{user.get('first_name','')} {user.get('last_name','')}".strip()


def find_user(email):
    email = str(email).strip().lower()
    d = one("roster_list", {"roster_list.email": email})
    return d.get("roster_list") if d else None


def signup(first, last, employee_id, email, password):
    email = email.strip().lower()
    if not email.endswith("@hpe.com"):
        return False, "Please use a valid @hpe.com email address."
    if find_user(email):
        return False, "An account already exists for this HPE email."
    if len(password) < 8:
        return False, "Password must be at least 8 characters."
    roster = {
        "first_name": str(first),
        "last_name": str(last),
        "employee_id": str(employee_id),
        "email": str(email),
        "hpe_email": str(email),
        "password_hash": str(pw_hash(password)),
        "role": "Agent",
        "account_status": "Active",
        "current_aux": "Not Ready - Online",
        "profile_pic": "",
        "birthday": "",
        "home_address": "",
        "contact_number": "",
        "department": "Operations",
        "created_at": datetime.now().isoformat(),
    }
    try:
        # Required schema: type = roster_list, with all registration data in one object.
        collection().insert_one({"type": "roster_list", "roster_list": roster})
        return True, "Account created successfully."
    except DuplicateKeyError:
        return False, "An account already exists."
    except Exception as exc:
        return False, f"Could not create account: {exc}"


def authenticate(email, password):
    u = find_user(email)
    if not u or u.get("account_status", "Active") != "Active":
        return None
    return u if pw_check(password, u.get("password_hash", "")) else None


def create_session(email, remember):
    token = secrets.token_urlsafe(48)
    expiry = datetime.now() + timedelta(days=30 if remember else 1)
    upsert("sessions", {"session.token_hash": sha(token)}, {
        "session": {
            "token_hash": sha(token),
            "email": email.lower(),
            "created_at": datetime.now().isoformat(),
            "expires_at": expiry.isoformat(),
        }
    })
    set_cookie("hpe_caseflow_session", token, 30 if remember else 1)
    return token


def session_user():
    email = None
    if st.session_state.get("user"):
        email = st.session_state.user.get("email")
    else:
        token = get_cookie("hpe_caseflow_session")
        if not token:
            return None
        d = one("sessions", {"session.token_hash": sha(token)})
        if not d:
            return None
        try:
            if datetime.fromisoformat(d["session"]["expires_at"]) < datetime.now():
                return None
        except Exception:
            return None
        email = d["session"]["email"]
        
    # Re-verify the user's active status against the database
    if email:
        u = find_user(email)
        if u and u.get("account_status", "Active") == "Active":
            return u
    return None


def logout():
    token = get_cookie("hpe_caseflow_session")
    if token:
        try:
            collection().delete_one({"type": "sessions", "session.token_hash": sha(token)})
        except Exception:
            pass
    # Do not call st.rerun() here. Let this run finish so CookieManager can
    # deliver the browser-side delete instruction.
    delete_cookie("hpe_caseflow_session")
    st.session_state.clear()
    st.session_state.auth_mode = "signin"
    st.session_state.logged_out = True
    return True


# ============================================================
# Validation dropdowns
# ============================================================

def validation():
    d = one("Validation_Dropdown", {})
    if not d:
        upsert("Validation_Dropdown", {}, {"Validation_Dropdown": DEFAULT_VALIDATION})
        return DEFAULT_VALIDATION
    return d.get("Validation_Dropdown", DEFAULT_VALIDATION)


# ============================================================
# Demo data - used only to make a newly connected database usable.
# Remove seed_demo() if you want a completely empty production database.
# ============================================================

def seed_demo():
    if not one("Validation_Dropdown", {}):
        upsert("Validation_Dropdown", {}, {"Validation_Dropdown": DEFAULT_VALIDATION})

    if not docs("cases"):
        now = datetime.now()
        subjects = [
            "Portal Access Issue", "License Renewal Delay", "Installation Error",
            "Vendor Confirmation", "Software Licensing", "Portal Access Request",
            "Account Escalation", "Data Sync Issue", "System Error",
            "User Access Request", "Contract Update", "Renewal Confirmation",
        ]
        priorities = ["Critical", "Critical", "High", "High", "Medium", "Medium", "Low"]
        names = [
            "Maria Santos", "John Dela Cruz", "Liza Garcia", "Mark Tan",
            "Christine Reyes", "James Lim", "Anna Co", "Kevin Ramos",
        ]
        for i in range(1, 25):
            c = {
                "case_no": f"HC-2026-{1045-i:04d}",
                "subject": subjects[i % len(subjects)],
                "description": "Client is experiencing an issue requiring follow-up and resolution.",
                "priority": priorities[i % len(priorities)],
                "assigned_to": names[i % len(names)],
                "due_date": (now + timedelta(hours=[2, 4, 7, 16, 24, 36, 60][i % 7])).isoformat(),
                "created_date": (now - timedelta(hours=4+i)).isoformat(),
                "last_update": (now - timedelta(minutes=i*8)).isoformat(),
                "status": ["In Progress", "On Hold", "Open", "Pending Vendor"][i % 4],
                "status_reason": "Waiting for Vendor Response",
                "closure_type": "",
                "breach_reason": "",
                "case_type": "License Renewal",
                "account": "ABC Enterprise",
                "related_system": "HPE Licensing Portal",
                "vendor_name": "ABC Software Inc.",
                "vendor_email": "support@abcsoftware.com",
                "vendor_phone": "+1 555 123 4567",
                "remarks": "",
                "history": [
                    {"time": (now-timedelta(hours=4)).isoformat(),
                     "actor": "System", "event": "Case created and assigned."}
                ],
            }
            try:
                collection().insert_one({"type": "cases", "case": c})
            except Exception:
                pass


def seed_schedule():
    if one("Schedule_Monitoring", {"schedule.date": date.today().isoformat()}):
        return
    names = ["Arianne Escabillas", "John Dela Cruz", "Maria Santos", "Liza Garcia", "Mark Tan"]
    activities = []
    for name in names:
        activities.append({
            "agent": name,
            "date": date.today().isoformat(),
            "activities": [
                {"start":"08:00","end":"10:00","type":"Case Work"},
                {"start":"10:00","end":"10:15","type":"Break"},
                {"start":"10:15","end":"12:00","type":"Case Work"},
                {"start":"12:00","end":"13:00","type":"Lunch"},
                {"start":"13:00","end":"15:00","type":"Case Work"},
                {"start":"15:00","end":"15:15","type":"Break"},
                {"start":"15:15","end":"17:00","type":"Case Work"},
            ],
        })
    upsert("Schedule_Monitoring", {"schedule.date": date.today().isoformat()}, {
        "schedule": {"date": date.today().isoformat(), "activities": activities,
                     "updated_at": datetime.now().isoformat()}
    })


# ============================================================
# Case engine
# ============================================================

def dt(value):
    """Parse a timestamp used for general case history/update fields.
    Invalid values retain the previous safe-now behavior for those fields.
    Due dates use due_dt() so malformed dates are never treated as due now.
    """
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return datetime.now()


def due_dt(value):
    """Return a valid due date, or None when the source is missing/invalid."""
    if value is None or not str(value).strip():
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def all_cases():
    return [d.get("case", {}) for d in docs("cases")]


def active_cases(cases=None):
    cases = all_cases() if cases is None else cases
    return [c for c in cases if c.get("status") not in ("Resolved", "Closed")]


def agents():
    out = []
    for d in docs("roster_list"):
        u = d.get("roster_list", {})
        if u.get("account_status", "Active") == "Active" and u.get("role") in ("Agent", "Admin/Agent"):
            out.append(u)
    return out


def active_count(name, cases=None):
    return sum(1 for c in active_cases(cases) if c.get("assigned_to") == name)


def critical_count(name, cases=None):
    return sum(1 for c in active_cases(cases)
               if c.get("assigned_to") == name and c.get("priority") == "Critical")


def today_assigned(name, cases=None):
    today = date.today().isoformat()
    cases = all_cases() if cases is None else cases
    return sum(1 for c in cases
               if c.get("assigned_to") == name and str(c.get("created_date","")).startswith(today))


def auto_assign_case(case):
    candidates = [u for u in agents() if u.get("current_aux") == "Available"]
    if not candidates:
        return None

    cases = all_cases()
    active = active_cases(cases)
    critical = case.get("priority") == "Critical"
    if critical:
        # First distribute critical work to agents with no active critical case,
        # then minimize active load and today's assignments.
        candidates.sort(key=lambda u: (
            critical_count(full_name(u), active) > 0,
            active_count(full_name(u), active),
            today_assigned(full_name(u), cases)
        ))
    else:
        candidates.sort(key=lambda u: (
            active_count(full_name(u), active),
            today_assigned(full_name(u), cases),
            critical_count(full_name(u), active)
        ))

    chosen = full_name(candidates[0])
    now = datetime.now().isoformat()
    result = collection().find_one_and_update(
        {"type":"cases", "case.case_no":case.get("case_no"),
         "case.assigned_to":{"$in":[None, ""]}},
        {"$set":{"case.assigned_to":chosen, "case.last_update":now},
         "$push":{"case.history":{
             "time":now,"actor":"System",
             "event":f"Case automatically assigned to {chosen}."
         }}}
    )
    if result:
        insert("alerts", {"alert":{
            "to":chosen, "kind":"new_case", "title":"New Case Assigned to You",
            "message":"A new case has been automatically assigned to you.",
            "case_no":case.get("case_no"), "priority":case.get("priority"),
            "due_date":case.get("due_date"), "created_at":now, "ack":False
        }})
        return chosen
    return None


def auto_assign_unassigned():
    for c in all_cases():
        if not c.get("assigned_to") and c.get("status") not in ("Resolved","Closed"):
            auto_assign_case(c)


def update_case(case_no, updates, actor, event=None):
    now = datetime.now().isoformat()
    updates = dict(updates)
    updates["last_update"] = now
    update = {"$set": {f"case.{k}":v for k,v in updates.items()}}
    if event:
        update["$push"] = {"case.history":{"time":now,"actor":actor,"event":event}}
    collection().update_one({"type":"cases","case.case_no":case_no}, update)


# ============================================================
# Alerts
# ============================================================

def alerts_for(name):
    try:
        return [
            d.get("alert", {}) for d in collection().find(
                {"type":"alerts","alert.to":{"$in":[name,"ALL"]}},
                {"_id":0}
            ).sort("alert.created_at", DESCENDING).limit(50)
        ]
    except Exception:
        return []


def ack_alert(a):
    collection().update_one(
        {"type":"alerts","alert.created_at":a.get("created_at"),
         "alert.title":a.get("title")},
        {"$set":{"alert.ack":True}}
    )


def generate_critical_alerts():
    now = datetime.now()
    for c in active_cases():
        if c.get("priority") != "Critical":
            continue
        due = due_dt(c.get("due_date"))
        if due is None:
            continue
        minutes = (due - now).total_seconds()/60
        if 0 < minutes <= 120:
            recent = collection().find_one({
                "type":"alerts","alert.kind":"critical_due",
                "alert.case_no":c.get("case_no"),
                "alert.created_at":{"$gte":(now-timedelta(minutes=30)).isoformat()}
            })
            if not recent:
                insert("alerts", {"alert":{
                    "to":"ALL","kind":"critical_due","title":"Critical Case Alert",
                    "message":"A critical case is nearing its due date and is not resolved or closed.",
                    "case_no":c.get("case_no"),"priority":"Critical",
                    "due_date":c.get("due_date"),"created_at":now.isoformat(),"ack":False
                }})


# ============================================================
# Authentication screens
# ============================================================

def send_reset_email(email, token):
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT","587"))
    username = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    if not all([host, username, password]):
        return False
    base = os.getenv("APP_BASE_URL","http://localhost:8501")
    link = f"{base}?reset={token}"
    msg = EmailMessage()
    msg["Subject"] = "HPE CaseFlow Password Reset"
    msg["From"] = username
    msg["To"] = email
    msg.set_content(
        f"Reset your HPE CaseFlow password using this link:\n{link}\n\n"
        "The link expires in 1 hour."
    )
    try:
        with smtplib.SMTP(host,port,timeout=15) as server:
            server.starttls()
            server.login(username,password)
            server.send_message(msg)
        return True
    except Exception:
        return False


def auth_page():
    mode = st.session_state.get("auth_mode","signin")
    left = """
    <div class="auth-left">
      <div style="font-size:20px;font-weight:800">▱ Hewlett Packard<br>Enterprise</div>
      <div class="auth-brand" style="margin-top:45px">HPE<br><span>CaseFlow</span></div>
      <div style="font-size:18px;line-height:1.35">Team Task and<br>Case Management System</div>
      <div class="auth-feature"><div class="auth-icon">□</div><div><b>Manage Cases</b><br><small>Track and resolve tasks efficiently</small></div></div>
      <div class="auth-feature"><div class="auth-icon">♙</div><div><b>Work Together</b><br><small>Stay aligned with your team</small></div></div>
      <div class="auth-feature"><div class="auth-icon">▥</div><div><b>Drive Results</b><br><small>Real-time insights and reporting</small></div></div>
    </div>
    """
    a,b = st.columns(2)
    with a:
        st.markdown(left, unsafe_allow_html=True)
    with b:
        st.markdown('<div class="auth-right">', unsafe_allow_html=True)

        if mode == "signin":
            st.markdown("## Welcome Back!")
            st.caption("Sign in to your HPE CaseFlow account")
            email = st.text_input("HPE Email Address", placeholder="yourname@hpe.com")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            remember = st.checkbox("Remember me", value=True)
            c1,c2 = st.columns(2)
            with c1:
                if st.button("Sign In", type="primary", use_container_width=True):
                    user = authenticate(email,password)
                    if user:
                        st.session_state.user = user
                        st.session_state.page = "Dashboard"
                        create_session(user["email"],remember)
                        st.success("Signed in successfully.")
                        # Do not call st.rerun() here. CookieManager needs this
                        # script run to finish so the browser can receive the
                        # cookie write instruction. The main() flow continues
                        # into the dashboard in this same run.
                        return True
                    else:
                        st.error("Invalid email/password or inactive account.")
            with c2:
                if st.button("Forgot password?", use_container_width=True):
                    st.session_state.auth_mode="forgot"; st.rerun()
            st.divider()
            st.button("▦  Sign in with Microsoft (HPE)",use_container_width=True,disabled=True)
            st.write("")
            if st.button("Don't have an account?  Sign up",use_container_width=True):
                st.session_state.auth_mode="signup"; st.rerun()

        elif mode == "signup":
            if st.button("← Back to Sign In"):
                st.session_state.auth_mode="signin"; st.rerun()
            st.markdown("## Create Your Account")
            st.caption("Sign up to access HPE CaseFlow")
            first = st.text_input("First Name")
            last = st.text_input("Last Name")
            employee = st.text_input("Employee ID")
            email = st.text_input("HPE Email Address")
            password = st.text_input("Password", type="password")
            st.caption("Password must be at least 8 characters.")
            if st.button("Sign Up",type="primary",use_container_width=True):
                ok,msg=signup(first,last,employee,email,password)
                (st.success if ok else st.error)(msg)
                if ok:
                    st.session_state.auth_mode="signin"

        else:
            if st.button("← Back to Sign In"):
                st.session_state.auth_mode="signin"; st.rerun()
            st.markdown("## Reset Password")
            email=st.text_input("HPE Email Address")
            if st.button("Send Reset Link",type="primary",use_container_width=True):
                user=find_user(email)
                if not user:
                    st.error("No account was found for that email.")
                else:
                    token=secrets.token_urlsafe(32)
                    upsert("password_resets",{"reset.email":email.lower()}, {
                        "reset":{"email":email.lower(),"token_hash":sha(token),
                                 "expires_at":(datetime.now()+timedelta(hours=1)).isoformat()}
                    })
                    if send_reset_email(email,token):
                        st.success("Reset link sent to your HPE email.")
                    else:
                        st.info("Reset token created. Configure SMTP_HOST, SMTP_USER and SMTP_PASSWORD for automatic email delivery.")

        st.markdown('</div>', unsafe_allow_html=True)


# ============================================================
# Navigation/profile
# ============================================================

def set_aux(user,new_aux):
    email=user["email"].lower()
    old=user.get("current_aux","")
    collection().update_one(
        {"type":"roster_list","roster_list.email":email},
        {"$set":{"roster_list.current_aux":new_aux}}
    )
    insert("Aux_History",{"aux":{
        "agent":full_name(user),"employee_id":user.get("employee_id",""),
        "from":old,"to":new_aux,"time":datetime.now().isoformat()
    }})
    user["current_aux"]=new_aux
    st.session_state.user=user
    auto_assign_unassigned()


def render_sidebar(user, container=None):
    """Render authenticated navigation into a clearable sidebar container."""
    target = container if container is not None else st.sidebar
    with target.container():
        role=user.get("role","Agent")
        pages=["Dashboard","Schedule","Report"]
        if role in ("Admin","Admin/Agent"):
            pages=["Dashboard","Monitoring","Schedule","Report","Settings"]

        target.markdown(
            '<div style="padding:10px 8px 18px"><span class="hpe-logo"></span>'
            '<div style="color:white;font-size:20px;font-weight:800;margin-top:8px">HPE CaseFlow</div>'
            '<div style="color:#b7c8d8;font-size:11px">Team Task and Case Management System</div></div>',
            unsafe_allow_html=True
        )
        current=st.session_state.get("page","Dashboard")
        for page in pages:
            if target.button(page, use_container_width=True,
                              type="primary" if page==current else "secondary",
                              key=f"sidebar_nav_{page}"):
                st.session_state.page=page
                st.rerun()
        target.divider()
        target.caption("HPE CaseFlow v1.0.0")
        if target.button("Sign Out",use_container_width=True,key="sidebar_signout"):
            return logout()
    return False


def topbar(user, container=None):
    """Render topbar/profile into a clearable main-page container."""
    target = container if container is not None else st
    with target.container():
        st.markdown(
            f'<div class="hpe-topbar"><span class="hpe-logo"></span>'
            f'<div><div class="hpe-brand">HPE CaseFlow</div><div class="hpe-sub">Team Task and Case Management System</div></div>'
            f'<div style="flex:1"></div><div style="font-size:25px">♧</div>'
            f'<div><b>{full_name(user)}</b><br><span style="font-size:12px;opacity:.8">{user.get("role","Agent")}</span></div>'
            f'<div style="background:#0aa88f;border-radius:20px;padding:8px 14px">'
            f'<span style="color:#baffdc">●</span> {user.get("current_aux","Available")}</div></div>',
            unsafe_allow_html=True
        )
        if st.button("Profile ▾",key="profile_button"):
            st.session_state.profile_open=not st.session_state.get("profile_open",False)
            st.rerun()
        if st.session_state.get("profile_open"):
            with st.container(border=True):
                st.markdown(f"### {full_name(user)}")
                st.caption(f'{user.get("role","Agent")} · {user.get("employee_id","")}')
                st.caption(user.get("email",""))
                idx=AUXES.index(user.get("current_aux")) if user.get("current_aux") in AUXES else 0
                new_aux=st.selectbox("Current Status / Aux",AUXES,index=idx)
                if new_aux != user.get("current_aux"):
                    set_aux(user,new_aux)
                    st.success(f"Status changed to {new_aux}")
                    st.rerun()
                if user.get("role") in ("Agent","Admin/Agent"):
                    st.markdown("**Today's Schedule**")
                    render_schedule_for_user(full_name(user))
                x,y,z=st.columns(3)
                with x:
                    if st.button("View Profile"): st.session_state.page="Settings"; st.rerun()
                with y:
                    if st.button("Notifications"):
                        st.session_state.show_alerts=True
                with z:
                    if st.button("Sign Out"):
                        return logout()
    return False


def render_schedule_for_user(name):
    d=one("Schedule_Monitoring",{"schedule.date":date.today().isoformat()})
    acts=[]
    if d:
        for a in d.get("schedule",{}).get("activities",[]):
            if a.get("agent")==name:
                acts=a.get("activities",[])
    if not acts:
        acts=[
            {"start":"08:00","end":"10:00","type":"Available"},
            {"start":"10:00","end":"10:15","type":"Break"},
            {"start":"10:15","end":"12:00","type":"Available"},
            {"start":"12:00","end":"13:00","type":"Lunch"},
            {"start":"13:00","end":"15:00","type":"Available"},
            {"start":"15:00","end":"15:15","type":"Break"},
            {"start":"15:15","end":"17:00","type":"Available"},
        ]
    for a in acts:
        st.markdown(f'`{a["start"]} – {a["end"]}` &nbsp; **{a["type"]}**')


# ============================================================
# Case detail
# ============================================================

@st.dialog("Case Details", width="large")
def case_dialog(case,user):
    v=validation()
    st.markdown(f"### {case.get('case_no')} · {case.get('subject')}")
    a,b,c,d=st.columns(4)
    a.metric("Priority",case.get("priority"))
    b.metric("Status",case.get("status"))
    due_value = due_dt(case.get("due_date"))
    c.metric("Due", due_value.strftime("%b %d, %Y %I:%M %p") if due_value else "Not set")
    c4=(datetime.now()-dt(case.get("last_update"))).total_seconds()/3600
    d.metric("Last Update",f"{c4:.1f}h ago")

    t1,t2,t3,t4=st.tabs(["Case Information","Vendor Information","Communication","Attachments"])
    with t1:
        st.write(case.get("description",""))
        st.json({k:case.get(k,"") for k in [
            "case_no","subject","priority","assigned_to","due_date",
            "created_date","last_update","status","case_type","account","related_system"
        ]})
        if case.get("history"):
            st.markdown("**Case History**")
            for h in reversed(case["history"][-10:]):
                st.write(f'{h.get("time")} · {h.get("actor")} · {h.get("event")}')
    with t2:
        st.markdown(f"**{case.get('vendor_name','Vendor')}**")
        st.text_input("Vendor Email",value=case.get("vendor_email",""),key=f"vendor_email_{case['case_no']}")
        st.text_input("Vendor Phone",value=case.get("vendor_phone",""),key=f"vendor_phone_{case['case_no']}")
        st.caption("The values are copyable directly from the fields. Vendor data can be synchronized from the Excel file in Settings.")
    with t3:
        st.text_area("Communication / Notes",height=160,key=f"comm_{case['case_no']}")
    with t4:
        st.info("Attachment metadata can be stored in the case document and files can be linked through your deployment's storage layer.")

    st.divider()
    st.markdown("### Update Case")
    c1,c2=st.columns(2)
    statuses=v.get("Case_Status",DEFAULT_VALIDATION["Case_Status"])
    reasons=v.get("Case_Reason",DEFAULT_VALIDATION["Case_Reason"])
    closures=v.get("Closure_Type",DEFAULT_VALIDATION["Closure_Type"])
    breaches=v.get("Contract_Breach",DEFAULT_VALIDATION["Contract_Breach"])
    with c1:
        status=st.selectbox("Case Status",statuses,
            index=statuses.index(case.get("status")) if case.get("status") in statuses else 0)
        reason=st.selectbox("Status Reason",reasons,
            index=reasons.index(case.get("status_reason")) if case.get("status_reason") in reasons else 0)
    with c2:
        closure=st.selectbox("Closure Type",[""]+closures)
        breach=st.selectbox("Breach Reason",[""]+breaches)
    remarks=st.text_area("Remarks / Update",max_chars=1000)

    if closure=="Contact Breach" and breach:
        st.markdown("### Automated Breach Notice Email")
        to=st.text_input("To",value=case.get("vendor_email",""))
        subject=st.text_input("Subject",value=f"Notice of Contract Breach – {case.get('case_no')}")
        body=st.text_area(
            "Email",
            value=(
                f"Dear {case.get('vendor_name','Vendor')},\n\n"
                f"This is to inform you that case {case.get('case_no')} is nearing or has reached "
                f"contract breach due to {breach}.\n\nPlease provide an update at your earliest convenience.\n\nThank you."
            ),
            height=170
        )
        e1,e2=st.columns(2)
        with e1:
            if st.button("Edit Email",key=f"edit_email_{case['case_no']}"): st.info("Edit the fields above before sending.")
        with e2:
            if st.button("Send Email",type="primary",key=f"send_email_{case['case_no']}"):
                st.success("Email queued. Configure SMTP for live delivery.")

    role=user.get("role")
    if role in ("Admin","Admin/Agent"):
        st.markdown("### Admin Actions")
        choices=[""]+[full_name(u) for u in agents()]
        assignee=st.selectbox("Reassign To",choices,key=f"reassign_{case['case_no']}")
        if assignee and st.button("Reassign Case",key=f"reassign_btn_{case['case_no']}"):
            update_case(case["case_no"],{"assigned_to":assignee},full_name(user),
                        f"Case reassigned to {assignee} by {full_name(user)}")
            insert("alerts",{"alert":{
                "to":assignee,"kind":"reassigned","title":"Case Reassigned to You",
                "message":"A case has been reassigned to you by the administrator.",
                "case_no":case["case_no"],"priority":case.get("priority"),
                "due_date":case.get("due_date"),"created_at":datetime.now().isoformat(),"ack":False
            }})
            st.success("Case reassigned.")
            st.rerun()
    else:
        choices=[""]+[full_name(u) for u in agents() if full_name(u)!=full_name(user)]
        target=st.selectbox("Request Transfer To",choices,key=f"transfer_{case['case_no']}")
        if target and st.button("Request Transfer",key=f"transfer_btn_{case['case_no']}"):
            now=datetime.now().isoformat()
            insert("transfer_requests",{"request":{
                "case_no":case["case_no"],"from":full_name(user),"to":target,
                "status":"Pending","created_at":now
            }})
            insert("alerts",{"alert":{
                "to":target,"kind":"transfer_request","title":"Case Transfer Request",
                "message":f"{full_name(user)} requested to transfer a case to you.",
                "case_no":case["case_no"],"priority":case.get("priority"),
                "due_date":case.get("due_date"),"created_at":now,"ack":False
            }})
            st.success("Transfer request sent.")
            st.rerun()

    if st.button("Update Case",type="primary",key=f"save_case_{case['case_no']}"):
        update_case(
            case["case_no"],
            {"status":status,"status_reason":reason,"closure_type":closure,
             "breach_reason":breach,"remarks":remarks},
            full_name(user),
            f"Status changed to {status} by {full_name(user)}"
        )
        st.success("Case updated.")
        st.rerun()


# ============================================================
# Dashboard
# ============================================================

def metric(label,value,icon):
    st.markdown(
        f'<div class="metric"><div style="font-size:27px">{icon}</div>'
        f'<div class="label">{label}</div><div class="value">{value}</div></div>',
        unsafe_allow_html=True
    )


def dashboard(user):
    auto_assign_unassigned()
    generate_critical_alerts()
    role=user.get("role")
    data=active_cases()
    if role not in ("Admin","Admin/Agent"):
        data=[c for c in data if c.get("assigned_to")==full_name(user)]

    st.markdown('<div class="page-title">Dashboard</div>'
                '<div class="page-subtitle">Welcome back. Here’s what’s happening today.</div>',
                unsafe_allow_html=True)

    st.text_input("Search",placeholder="Search cases, names, vendors, or issues...",
                  label_visibility="collapsed",key="global_case_search")
    q=st.session_state.get("global_case_search","").lower()

    # Calculate metrics using the FULL unmodified dataset
    critical=[c for c in data if c.get("priority")=="Critical"]
    due=[]
    for c in data:
        due_value = due_dt(c.get("due_date"))
        if due_value is not None and 0 <= (due_value-datetime.now()).total_seconds()/3600 <= 24:
            due.append(c)
    on_track=[c for c in data if c.get("status") in ("Open","In Progress") and c.get("priority")!="Critical"]

    cols=st.columns(4)
    for col,(label,value,icon) in zip(cols,[
        ("Active Cases",len(data),"▣"),("Critical",len(critical),"⚠"),
        ("Due Soon",len(due),"◷"),("On Track",len(on_track),"✓")
    ]):
        with col: metric(label,value,icon)

    # NOW apply the search filter exclusively for the table rendering
    if q:
        data=[c for c in data if q in str(c).lower()]

    if role in ("Admin","Admin/Agent"):
        st.markdown("### Admin Case Queue")
        selected=[]
        with st.expander("Bulk Case Actions"):
            selected=st.multiselect(
                "Select cases to reassign",
                [c.get("case_no") for c in data],
                key="bulk_cases"
            )
            target=st.selectbox("Reassign selected cases to",
                                [""]+[full_name(u) for u in agents()],
                                key="bulk_target")
            if st.button("Reassign Selected") and selected and target:
                for no in selected:
                    update_case(no,{"assigned_to":target},full_name(user),
                                f"Bulk reassigned to {target} by {full_name(user)}")
                    insert("alerts",{"alert":{
                        "to":target,"kind":"reassigned","title":"Case Reassigned to You",
                        "message":"A case has been reassigned to you by the administrator.",
                        "case_no":no,"created_at":datetime.now().isoformat(),"ack":False
                    }})
                st.success("Selected cases reassigned.")
                st.rerun()
    else:
        st.markdown("### My Cases")

    header=st.columns([1.1,2.1,1,1.5,1.7,1.2,1.6])
    for col,h in zip(header,["Case #","Subject","Priority","Assigned To","Due Date","Status","Last Update"]):
        col.markdown(f'<div class="table-head">{h}</div>',unsafe_allow_html=True)

    data=sorted(data,key=lambda c:(PRIORITY_ORDER.get(c.get("priority","Low"),9),due_dt(c.get("due_date")) or datetime.max))
    for c in data[:100]:
        cols=st.columns([1.1,2.1,1,1.5,1.7,1.2,1.6])
        if cols[0].button(c.get("case_no",""),key=f"open_case_{c.get('case_no')}"):
            case_dialog(c,user)
        cols[1].write(c.get("subject",""))
        p=c.get("priority","Low")
        cols[2].markdown(f'<span class="badge badge-{p.lower()}">{p}</span>',unsafe_allow_html=True)
        cols[3].write(c.get("assigned_to","Unassigned"))
        due_value = due_dt(c.get("due_date"))
        cols[4].write(due_value.strftime("%b %d, %Y %I:%M %p") if due_value else "Not set")
        s=c.get("status","Open")
        sc={"In Progress":"progress","On Hold":"hold","Open":"open","Resolved":"track","Closed":"track"}.get(s,"open")
        cols[5].markdown(f'<span class="badge badge-{sc}">{s}</span>',unsafe_allow_html=True)
        hours=(datetime.now()-dt(c.get("last_update"))).total_seconds()/3600
        cols[6].write(f'{dt(c.get("last_update")).strftime("%b %d, %I:%M %p")} ({hours:.1f}h)')

    if role in ("Admin","Admin/Agent"):
        st.markdown("### Agents Online")
        cc=st.columns(4)
        for i,u in enumerate(agents()):
            with cc[i%4]:
                st.markdown(
                    f'<div class="card"><b>{full_name(u)}</b><br>'
                    f'<span style="color:{AUX_COLOR.get(u.get("current_aux"),"#16b77a")}">●</span> '
                    f'{u.get("current_aux","")}</div>',
                    unsafe_allow_html=True
                )


# ============================================================
# Monitoring
# ============================================================

def monitoring(user):
    st.markdown('<div class="page-title">Monitoring</div>'
                '<div class="page-subtitle">Realtime agent status and activities.</div>',
                unsafe_allow_html=True)
    users=agents()
    cases=all_cases()
    active=active_cases(cases)
    vals=[
        ("Total Logged In",len(users)),
        ("Available",sum(u.get("current_aux")=="Available" for u in users)),
        ("On AUX",sum(u.get("current_aux") in ("Lunch","Break","Unscheduled Break") for u in users)),
        ("Meeting/Coaching",sum(u.get("current_aux") in ("Meeting","Coaching") for u in users)),
        ("Not Ready",sum(u.get("current_aux")=="Not Ready - Online" for u in users)),
    ]
    cc=st.columns(5)
    for col,(label,val) in zip(cc,vals):
        with col: metric(label,val,"●")

    q=st.text_input("Agent Search",placeholder="Search agent name or employee ID...")
    for u in users:
        if q and q.lower() not in str(u).lower():
            continue
        a,b,c,d,e=st.columns([2.3,1.2,1.5,1.2,1.2])
        a.write(f'**{full_name(u)}**\n\n{u.get("employee_id","")}')
        b.write(u.get("role"))
        c.markdown(f'<span style="color:{AUX_COLOR.get(u.get("current_aux"),"#16b77a")}">●</span> {u.get("current_aux")}',
                   unsafe_allow_html=True)
        d.write(active_count(full_name(u), active))
        if e.button("View",key=f"view_agent_{u.get('employee_id')}"):
            st.session_state.monitor_agent=u

    if st.session_state.get("monitor_agent"):
        u=st.session_state.monitor_agent
        st.divider()
        st.markdown(f"### {full_name(u)}")
        t1,t2,t3=st.tabs(["Overview","Aux History","Case Assignment"])
        with t1:
            st.write(f'Role: {u.get("role")} · Status: {u.get("current_aux")}')
            st.write(f"Active Cases: {active_count(full_name(u), active)}")
            st.write(f"Today's Assigned: {today_assigned(full_name(u), cases)}")
        with t2:
            for d in docs("Aux_History"):
                h=d.get("aux",{})
                if h.get("agent")==full_name(u): st.write(h)
        with t3:
            for c in cases:
                if c.get("assigned_to")==full_name(u):
                    st.write(f'{c.get("case_no")} · {c.get("priority")} · {c.get("status")}')
        x,y=st.columns(2)
        with x:
            message=st.text_area("Popup message to agent",key="monitor_message")
            if st.button("Send Pop-up Message"):
                insert("alerts",{"alert":{
                    "to":full_name(u),"kind":"admin_message","title":"Message from Admin",
                    "message":message,"created_at":datetime.now().isoformat(),"ack":False
                }})
                st.success("Message sent.")
        with y:
            if st.button("Kick User"):
                collection().update_one(
                    {"type":"roster_list","roster_list.email":u.get("email")},
                    {"$set":{"roster_list.account_status":"Inactive"}}
                )
                st.success("User access disabled.")
                st.session_state.pop("monitor_agent",None)
                st.rerun()

    if st.button("Export Monitoring Data"):
        rows=[]
        for u in users:
            rows.append({
                "Agent":full_name(u),"Employee ID":u.get("employee_id"),
                "Role":u.get("role"),"Aux":u.get("current_aux"),
                "Active Cases":active_count(full_name(u), active),
                "Today Assigned":today_assigned(full_name(u), cases)
            })
        st.download_button("Download CSV",pd.DataFrame(rows).to_csv(index=False),
                           "monitoring.csv","text/csv")


# ============================================================
# Schedule
# ============================================================

def month_days(year,month):
    first=date(year,month,1)
    last=date(year+1,1,1)-timedelta(days=1) if month==12 else date(year,month+1,1)-timedelta(days=1)
    start=first-timedelta(days=(first.weekday()+1)%7)
    return [start+timedelta(days=i) for i in range(42)]


def schedule_page(user):
    admin=user.get("role") in ("Admin","Admin/Agent")
    st.markdown('<div class="page-title">Schedule</div>'
                '<div class="page-subtitle">Manage PTO allocation, leave, schedules and activities.</div>',
                unsafe_allow_html=True)

    if hasattr(st,"segmented_control"):
        view=st.segmented_control("View",["Month","Week","Day"],default="Month")
    else:
        view=st.radio("View",["Month","Week","Day"],horizontal=True)

    a,b,c=st.columns([1.2,1.2,1])
    with a:
        st.markdown("### PTO Allocation Calendar")
        chosen=st.date_input("Calendar Date",date.today(),label_visibility="collapsed")
        headers=st.columns(7)
        for x,h in zip(headers,["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]):
            x.markdown(f"**{h}**")
        days=month_days(chosen.year,chosen.month)
        for row in range(6):
            cols=st.columns(7)
            for i,col in enumerate(cols):
                d=days[row*7+i]
                if col.button(str(d.day),key=f"cal_{d.isoformat()}",use_container_width=True):
                    st.session_state.selected_date=d
    with b:
        st.markdown("### PTO Allocation Summary")
        x,y,z,w=st.columns(4)
        x.metric("Total Allocation",10)
        y.metric("Used",6)
        z.metric("Remaining",4)
        w.metric("Fully Allocated",3)
        st.write("Fully allocated dates: Sep 14 · Sep 24 · Sep 29")
        if admin and st.button("Set Allocation"):
            st.session_state.set_allocation=True
        if st.session_state.get("set_allocation"):
            d=st.date_input("Allocation Date",date.today())
            amount=st.number_input("Available slots",min_value=0,value=1)
            if st.button("Save Allocation"):
                upsert("PTO_Allocation",{"allocation.date":d.isoformat()},
                       {"allocation":{"date":d.isoformat(),"slots":int(amount)}})
                st.success("Allocation saved.")
    with c:
        st.markdown("### Leave Requests")
        for d in docs("leave_requests",10):
            r=d.get("request",{})
            st.write(f'**{r.get("agent")}** · {r.get("type")} · {r.get("date")} · {r.get("status")}')

    st.divider()
    if admin:
        st.markdown("### Schedule Assignment")
        rows=[]
        for u in agents():
            rows.append({
                "Agent":full_name(u),"Role":u.get("role"),
                "08:00":"Case Work","10:00":"Break","10:15":"Case Work",
                "12:00":"Lunch","13:00":"Case Work","15:00":"Break","15:15":"Case Work"
            })
        if rows: st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
        c1,c2,c3,c4=st.columns(4)
        with c1:
            if st.button("Auto Plot",type="primary"): auto_plot()
        with c2:
            if st.button("Edit Schedule"):
                st.session_state.edit_schedule=True
        with c3:
            if st.button("Save Changes"):
                st.success("Schedule changes saved.")
        with c4:
            export_schedule()
        if st.session_state.get("edit_schedule"):
            st.markdown("### Add / Edit Schedule")
            selected_agent=st.selectbox("Agent",[full_name(u) for u in agents()])
            activity=st.selectbox("Activity",["Case Work","Admin Work","Meeting","Coaching","Lunch","Break","Training","PTO","Sick Leave","Emergency Leave"])
            start=st.time_input("Start",time(8,0))
            end=st.time_input("End",time(9,0))
            day=st.date_input("Date",st.session_state.get("selected_date",date.today()))
            if st.button("Plot Activity"):
                d=one("Schedule_Monitoring",{"schedule.date":day.isoformat()})
                data=d.get("schedule",{}) if d else {"date":day.isoformat(),"activities":[]}
                existing=data.get("activities",[])
                if not isinstance(existing, list):
                    existing=[]
                entry=next((x for x in existing if isinstance(x, dict) and x.get("agent")==selected_agent),None)
                if not entry:
                    entry={"agent":selected_agent,"date":day.isoformat(),"activities":[]}
                    existing.append(entry)
                entry["activities"].append({"start":start.strftime("%H:%M"),"end":end.strftime("%H:%M"),"type":activity})
                upsert("Schedule_Monitoring",{"schedule.date":day.isoformat()},
                       {"schedule":{"date":day.isoformat(),"activities":existing,"updated_at":datetime.now().isoformat()}})
                st.success("Activity plotted.")
    else:
        name=full_name(user)
        st.markdown("### My Schedule")
        d=one("Schedule_Monitoring",{"schedule.date":date.today().isoformat()})
        mine=[]
        if d:
            mine=[a for a in d.get("schedule",{}).get("activities",[]) if a.get("agent")==name]
        if mine:
            st.dataframe(pd.DataFrame(mine[0].get("activities",[])),use_container_width=True,hide_index=True)
        else:
            st.info("No schedule has been plotted yet.")

        st.markdown("### Submit Request")
        request_type=st.selectbox("Request Type",["PTO","Sick Leave","Emergency Leave"])
        request_date=st.date_input("Date",st.session_state.get("selected_date",date.today()))
        reason=st.text_input("Reason")
        remarks=st.text_area("Remarks")
        if st.button("Submit Request",type="primary"):
            if request_type=="PTO":
                alloc=one("PTO_Allocation",{"allocation.date":request_date.isoformat()})
                if alloc and int(alloc.get("allocation",{}).get("slots",0))>0:
                    insert("leave_requests",{"request":{
                        "agent":name,"type":"PTO","date":request_date.isoformat(),
                        "reason":reason,"remarks":remarks,"status":"Pending",
                        "created_at":datetime.now().isoformat()
                    }})
                    st.success("PTO request submitted for approval.")
                else:
                    st.error("No Allocation for the selected date.")
            else:
                insert("leave_requests",{"request":{
                    "agent":name,"type":request_type,"date":request_date.isoformat(),
                    "reason":reason,"remarks":remarks,"status":"Auto-Approved",
                    "created_at":datetime.now().isoformat()
                }})
                st.success(f"{request_type} request auto-approved.")

        st.markdown("### Schedule Swap Request")
        target=st.selectbox("Select advocate",[""]+[full_name(u) for u in agents() if full_name(u)!=name])
        if st.button("Send Schedule Swap"):
            if target:
                now=datetime.now().isoformat()
                insert("schedule_swaps",{"swap":{
                    "from":name,"to":target,"date":request_date.isoformat(),
                    "status":"Pending","created_at":now
                }})
                insert("alerts",{"alert":{
                    "to":target,"kind":"schedule_swap","title":"Schedule Swap Request",
                    "message":f"{name} requested to swap schedules with you.",
                    "created_at":now,"ack":False
                }})
                st.success("Schedule swap request sent.")


def auto_plot():
    today=date.today().isoformat()
    leave={r.get("request",{}).get("agent") for r in docs("leave_requests")
           if r.get("request",{}).get("date")==today and r.get("request",{}).get("status") in ("Approved","Auto-Approved")}
    entries=[]
    for u in agents():
        name=full_name(u)
        if name in leave:
            continue
        entries.append({
            "agent":name,"date":today,
            "activities":[
                {"start":"08:00","end":"10:00","type":"Case Work"},
                {"start":"10:00","end":"10:15","type":"Break"},
                {"start":"10:15","end":"12:00","type":"Case Work"},
                {"start":"12:00","end":"13:00","type":"Lunch"},
                {"start":"13:00","end":"15:00","type":"Case Work"},
                {"start":"15:00","end":"15:15","type":"Break"},
                {"start":"15:15","end":"17:00","type":"Case Work"},
            ]
        })
    upsert("Schedule_Monitoring",{"schedule.date":today},
           {"schedule":{"date":today,"activities":entries,"updated_at":datetime.now().isoformat()}})
    st.success("Schedule auto-plotted. Leave records were excluded.")


def export_schedule():
    rows=[]
    for d in docs("Schedule_Monitoring"):
        s=d.get("schedule",{})
        for a in s.get("activities",[]):
            for x in a.get("activities",[]):
                rows.append({"Date":s.get("date"),"Agent":a.get("agent"),
                             "Start":x.get("start"),"End":x.get("end"),"Activity":x.get("type")})
    if rows:
        st.download_button("Export",pd.DataFrame(rows).to_csv(index=False),
                           "schedule.csv","text/csv")


# ============================================================
# Reports
# ============================================================

def report_page(user):
    admin=user.get("role") in ("Admin","Admin/Agent")
    st.markdown('<div class="page-title">Reports</div>'
                '<div class="page-subtitle">Visualize case resolution, attendance and adherence.</div>',
                unsafe_allow_html=True)
    if hasattr(st,"segmented_control"):
        period=st.segmented_control("Period",["Daily","WOW","MTD","YTD"],default="MTD")
    else:
        period=st.radio("Period",["Daily","WOW","MTD","YTD"],horizontal=True,index=2)

    cases=all_cases()
    if not admin:
        cases=[c for c in cases if c.get("assigned_to")==full_name(user)]
    resolved=[c for c in cases if c.get("status")=="Resolved"]
    breached=[c for c in cases if c.get("closure_type")=="Contact Breach" or c.get("breach_reason")]
    rate=(len(resolved)/len(cases)*100) if cases else 0

    c=st.columns(4)
    for col,label,value in zip(c,["Total Cases","Resolved Cases","Breached Cases","On-Time Resolution"],
                              [len(cases),len(resolved),len(breached),f"{rate:.0f}%"]):
        with col: metric(label,value,"▣")

    a,b=st.columns([1.3,1])
    with a:
        st.markdown("### Case Trend")
        if cases:
            df=pd.DataFrame([{"Date":dt(x.get("last_update")).date(),"Status":x.get("status")} for x in cases])
            g=df.groupby(["Date","Status"]).size().reset_index(name="Cases")
            fig=px.line(g,x="Date",y="Cases",color="Status",markers=True)
            fig.update_layout(height=300,margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig,use_container_width=True)
    with b:
        st.markdown("### Case Distribution by Priority")
        s=pd.Series([x.get("priority","Low") for x in cases], dtype=str).value_counts()
        if not s.empty:
            fig=px.pie(values=s.values,names=s.index,hole=.55)
            fig.update_layout(height=300,margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig,use_container_width=True)

    a,b=st.columns(2)
    with a:
        st.markdown("### Resolution Time (Average - Hours)")
        rows=[]
        for x in resolved:
            rows.append({"Priority":x.get("priority"),
                         "Hours":max(0,(dt(x.get("last_update"))-dt(x.get("created_date"))).total_seconds()/3600)})
        if rows:
            g=pd.DataFrame(rows).groupby("Priority",as_index=False).Hours.mean()
            st.plotly_chart(px.bar(g,x="Priority",y="Hours"),use_container_width=True)
    with b:
        st.markdown("### Case Status")
        s=pd.Series([x.get("status","Open") for x in cases]).value_counts().reset_index()
        s.columns=["Status","Cases"]
        st.dataframe(s,use_container_width=True,hide_index=True)

    st.markdown("### Attendance Summary")
    attendance_docs=docs("Attendance")
    if attendance_docs:
        st.dataframe(pd.DataFrame([x.get("attendance",{}) for x in attendance_docs]),
                     use_container_width=True,hide_index=True)
    else:
        st.info("Attendance is calculated from login, approved PTO, sick/emergency leave and schedule records. No attendance records have been synchronized yet.")

    st.markdown("### Adherence Summary")
    adherence_docs=docs("Adherence")
    if adherence_docs:
        st.dataframe(pd.DataFrame([x.get("adherence",{}) for x in adherence_docs]),
                     use_container_width=True,hide_index=True)
    else:
        st.info("Adherence compares actual AUX history against Schedule_Monitoring plotted activities. No adherence records have been synchronized yet.")

    st.markdown("### Case Details")
    rows=[]
    for x in resolved[-30:]:
        rows.append({
            "Date Resolved":dt(x.get("last_update")).strftime("%b %d, %Y %I:%M %p"),
            "Case #":x.get("case_no"),"Subject":x.get("subject"),
            "Priority":x.get("priority"),"Status":x.get("status"),
            "Resolution Time (hrs)":round(max(0,(dt(x.get("last_update"))-dt(x.get("created_date"))).total_seconds()/3600),1),
            "Breach":"Yes" if x in breached else "No"
        })
    if rows:
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)


# ============================================================
# Settings
# ============================================================

def settings_page(user):
    if user.get("role") not in ("Admin","Admin/Agent"):
        st.error("Settings is available to Admin and Admin/Agent only.")
        return

    st.markdown('<div class="page-title">Settings</div>'
                '<div class="page-subtitle">Manage users, external sources and system configuration.</div>',
                unsafe_allow_html=True)

    t1,t2,t3,t4=st.tabs(["Team Management","External Sources","Vendor Management","System Configuration"])

    with t1:
        roster=[d.get("roster_list",{}) for d in docs("roster_list")]
        if roster:
            df=pd.DataFrame([{
                "Name":full_name(u),"Employee ID":u.get("employee_id"),
                "Email":u.get("email"),"Role":u.get("role"),
                "Status":u.get("account_status"),"Current Aux":u.get("current_aux")
            } for u in roster])
            st.dataframe(df,use_container_width=True,hide_index=True)

        st.markdown("### Edit User Information / Role")
        emails=[u.get("email") for u in roster]
        if emails:
            selected=st.selectbox("Select User",emails)
            u=find_user(selected)
            role=st.selectbox("Role",["Agent","Admin/Agent","Admin"],
                              index=["Agent","Admin/Agent","Admin"].index(u.get("role","Agent")))
            status=st.selectbox("Account Status",["Active","Inactive"],
                                index=0 if u.get("account_status","Active")=="Active" else 1)
            first=st.text_input("First Name",value=u.get("first_name",""))
            last=st.text_input("Last Name",value=u.get("last_name",""))
            employee=st.text_input("Employee ID",value=u.get("employee_id",""))
            if st.button("Save Changes",type="primary"):
                collection().update_one(
                    {"type":"roster_list","roster_list.email":selected},
                    {"$set":{
                        "roster_list.first_name":first,
                        "roster_list.last_name":last,
                        "roster_list.employee_id":employee,
                        "roster_list.role":role,
                        "roster_list.account_status":status
                    }}
                )
                st.success("User information and role updated.")
                st.rerun()
        else:
            st.info("No registered users yet.")

    with t2:
        st.markdown("### External Data Sources")
        vendor=st.file_uploader("Vendor Data Excel",type=["xlsx","xls"],key="vendor_source")
        if vendor and st.button("Sync Vendor Data",key="sync_vendor"):
            try:
                df=pd.read_excel(io.BytesIO(vendor.getvalue()))
                df.columns=[str(c).strip().lower().replace(" ","_") for c in df.columns]
                for row in df.fillna("").astype(str).to_dict("records"):
                    collection().update_one(
                        {"type":"Vendor_Data","vendor.email":row.get("email",""),
                         "vendor.vendor_name":row.get("vendor_name","")},
                        {"$set":{"type":"Vendor_Data","vendor":row,
                                 "last_updated":datetime.now().isoformat()}},
                        upsert=True
                    )
                st.success(f"Synchronized {len(df)} vendor records.")
            except Exception as exc:
                st.error(f"Vendor sync failed: {exc}")

        case_file=st.file_uploader("Case Import Excel",type=["xlsx","xls"],key="case_source")
        if case_file and st.button("Import Cases",key="import_cases"):
            try:
                df=pd.read_excel(io.BytesIO(case_file.getvalue()))
                df.columns=[str(c).strip().lower().replace(" ","_") for c in df.columns]
                for row in df.fillna("").to_dict("records"):
                    no=str(row.get("case_no") or row.get("case") or f"HC-{datetime.now():%Y%m%d}-{secrets.randbelow(9999):04d}")
                    c={
                        "case_no":no,"subject":str(row.get("subject","")),
                        "description":str(row.get("description","")),
                        "priority":str(row.get("priority","Medium")),
                        "assigned_to":str(row.get("assigned_to","")) or None,
                        "due_date":str(row.get("due_date") or (datetime.now()+timedelta(days=1)).isoformat()),
                        "created_date":datetime.now().isoformat(),
                        "last_update":datetime.now().isoformat(),
                        "status":str(row.get("status","Open")),
                        "status_reason":str(row.get("status_reason","")),
                        "closure_type":"","breach_reason":"",
                        "case_type":str(row.get("case_type","")),
                        "account":str(row.get("account","")),
                        "related_system":str(row.get("related_system","")),
                        "vendor_name":str(row.get("vendor_name","")),
                        "vendor_email":str(row.get("vendor_email","")),
                        "vendor_phone":str(row.get("vendor_phone","")),
                        "history":[]
                    }
                    collection().update_one({"type":"cases","case.case_no":no},
                                            {"$set":{"type":"cases","case":c}},upsert=True)
                auto_assign_unassigned()
                st.success(f"Imported {len(df)} cases.")
            except Exception as exc:
                st.error(f"Case import failed: {exc}")

        st.markdown("### Validation_Dropdown")
        st.json(validation())
        st.caption("Stored as type='Validation_Dropdown' with Case_Status, Case_Reason, Closure_Type and Contract_Breach.")

    with t3:
        vendors=[d.get("vendor",{}) for d in docs("Vendor_Data")]
        if vendors:
            st.dataframe(pd.DataFrame(vendors),use_container_width=True,hide_index=True)
        else:
            st.info("No vendor records synchronized yet.")

    with t4:
        st.checkbox("Realtime dashboard refresh",value=True)
        st.number_input("Refresh interval (seconds)",min_value=5,max_value=120,value=15)
        st.checkbox("Automatic case assignment",value=True)
        st.checkbox("Critical case alerts",value=True)
        st.info("Use Streamlit's deployment secrets/environment variables for MongoDB and SMTP. Avoid putting passwords directly in source code.")


# ============================================================
# Alerts center
# ============================================================

def alert_center(user):
    pending=[a for a in alerts_for(full_name(user)) if not a.get("ack")]
    if pending:
        # Read the state and consume it immediately 
        expanded = bool(st.session_state.get("show_alerts", False))
        st.session_state.show_alerts = False
        
        with st.expander(f"🔔 Alerts ({len(pending)})",expanded=expanded):
            for a in pending[:8]:
                alert_key = sha("|".join(str(a.get(k,"")) for k in ("created_at","title","kind","case_no","to")))[:16]
                st.warning(f'**{a.get("title","Alert")}** — {a.get("message","")}')
                if a.get("case_no"):
                    st.caption(f'Case: {a["case_no"]} · Priority: {a.get("priority","")} · Due: {a.get("due_date","")}')
                if st.button("Acknowledge",key=f"ack_{alert_key}"):
                    ack_alert(a)
                    # Keep the expander open for the upcoming rerun
                    st.session_state.show_alerts = True 
                    st.rerun()


# ============================================================
# Password reset
# ============================================================

def reset_screen(token):
    st.markdown("## Set New Password")
    email=st.text_input("HPE Email")
    new_pw=st.text_input("New Password",type="password")
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Reset Password",type="primary", use_container_width=True):
            d=one("password_resets",{"reset.token_hash":sha(token)})
            valid=False
            if d:
                try:
                    valid=datetime.fromisoformat(d["reset"]["expires_at"]) > datetime.now()
                except Exception:
                    valid=False
            if not valid:
                st.error("Invalid or expired reset token.")
                return
            if len(new_pw)<8:
                st.error("Password must be at least 8 characters.")
                return
            
            collection().update_one(
                {"type":"roster_list","roster_list.email":email.lower()},
                {"$set":{"roster_list.password_hash":pw_hash(new_pw)}}
            )
            st.success("Password reset successfully. You may now sign in.")
            st.query_params.clear()
            
    with c2:
        if st.button("Return to Sign In", use_container_width=True):
            st.query_params.clear()
            st.rerun()


# ============================================================
# Main
# ============================================================

def main():
    # Initialize structural session-state keys before authentication/page rendering.
    st.session_state.setdefault("auth_mode", "signin")
    st.session_state.setdefault("page", "Dashboard")
    st.session_state.setdefault("profile_open", False)
    st.session_state.setdefault("show_alerts", False)

    global _COOKIE_MANAGER
    # Initialize the custom component during normal Streamlit execution,
    # after page configuration and exactly once per run. The stable key keeps
    # browser cookie state across reruns without module-import side effects.
    if stx is not None and _COOKIE_MANAGER is None:
        _COOKIE_MANAGER = stx.CookieManager(key="hpe_cookie_manager")

    reset_token=st.query_params.get("reset")
    if reset_token:
        reset_screen(reset_token)
        return

    if not db_ok():
        st.error("MongoDB connection is not configured yet.")
        st.code(
            '[mongo]\n'
            'uri = "mongodb+srv://USERNAME:PASSWORD@CLUSTER.mongodb.net/?retryWrites=true&w=majority"'
        )
        st.info("Put this in .streamlit/secrets.toml or set MONGO_URI in the environment.")
        return

    seed_demo()
    seed_schedule()

    user=st.session_state.get("user") or session_user()
    if not user:
        # Render authentication inside a clearable placeholder. On successful
        # sign-in, remove the auth UI and continue rendering the dashboard in
        # the same run. This avoids both st.stop() dead ends and overlapping
        # login/dashboard layouts while still allowing CookieManager to finish
        # its browser-side cookie write.
        auth_placeholder = st.empty()
        with auth_placeholder.container():
            signed_in=auth_page()
        if not signed_in:
            return
        auth_placeholder.empty()
        user=st.session_state.get("user")
        if not user:
            return

    st.session_state.user=user
    st.session_state.setdefault("page","Dashboard")
    sidebar_placeholder = st.sidebar.empty()
    sidebar_logged_out = render_sidebar(user, sidebar_placeholder)
    if sidebar_logged_out:
        sidebar_placeholder.empty()
        auth_placeholder = st.empty()
        with auth_placeholder.container():
            auth_page()
        return

    topbar_placeholder = st.empty()
    topbar_logged_out = topbar(user, topbar_placeholder)
    if topbar_logged_out:
        topbar_placeholder.empty()
        sidebar_placeholder.empty()
        auth_placeholder = st.empty()
        with auth_placeholder.container():
            auth_page()
        return
    alert_center(user)

    page=st.session_state.page
    if page=="Dashboard":
        dashboard(user)
    elif page=="Monitoring":
        monitoring(user)
    elif page=="Schedule":
        schedule_page(user)
    elif page=="Report":
        report_page(user)
    elif page=="Settings":
        settings_page(user)


if __name__=="__main__":
    main()
