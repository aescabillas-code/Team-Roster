from __future__ import annotations

import hashlib
import hmac
import html
import io
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import streamlit as st
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import PyMongoError
from bson import ObjectId
from bson.binary import Binary

# ---------------------------------------------------------------------------
# OVR-VW | Operations Visibility & Response Workspace
# MongoDB-backed multi-user Streamlit application.
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="HPE OVR-VW | Operations Visibility & Response Workspace",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

APP_NAME = "OVR-VW"
DB_NAME = os.getenv("MONGODB_DB", "OVR_VW")
STATIONS = ["CARE", "ARCH", "PET", "SUPPLY CHAIN", "FULFILLMENT"]
SLA_DEFAULTS = {
    "CARE": 15, "ARCH": 30, "PET": 45, "SUPPLY CHAIN": 30, "FULFILLMENT": 120
}
STATION_COLORS = {
    "CARE": "#e6295b", "ARCH": "#078bd0", "PET": "#10a85b",
    "SUPPLY CHAIN": "#7c3fe4", "FULFILLMENT": "#e8a900"
}
STATION_TINTS = {
    "CARE": "#fde8ed", "ARCH": "#e5f3fc", "PET": "#e8f8ed",
    "SUPPLY CHAIN": "#f1e9ff", "FULFILLMENT": "#fff5d7"
}
CHECKLIST_DEFAULTS = [
    "Confirm the product, model and serial number.",
    "Capture the exact alert, error message or customer symptom.",
    "Complete applicable remote/basic troubleshooting checks.",
    "Verify support, entitlement or contract context.",
    "Record customer contact, site and required reference information.",
    "Document the assessment and recommended next action.",
]
STATUSES = [
    "Open", "In Progress", "Pending Internal", "Pending Customer",
    "Waiting", "Resolved", "Completed", "Closed"
]
PRIORITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
CLOSED_STATUSES = {"RESOLVED", "COMPLETED", "CLOSED"}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root{--navy:#081b3b;--teal:#008f83;--blue:#0868e8;--line:#dfe5ec;--muted:#5d6b82}
html,body,[class*="css"]{font-family:Inter,system-ui,sans-serif!important;color:var(--navy)}
.stApp{background:#f7f9fc}
header[data-testid="stHeader"],footer,#MainMenu{visibility:hidden;height:0}
.block-container{max-width:100%!important;padding:.5rem 1.15rem 2rem!important}
div[data-testid="stVerticalBlock"]{gap:.55rem}
.topbar{margin:-.5rem -1.15rem .8rem;padding:12px 2rem;min-height:78px;display:flex;align-items:center;gap:20px;color:#071a37;background:linear-gradient(110deg,#fff 0%,#e8f6f7 43%,#087c84 56%,#06384f 72%,#061b36 100%);border-bottom:1px solid #d7e1e9}
.hpe-mark{display:flex;align-items:center;gap:10px;font-size:26px;font-weight:800;color:#070b15;white-space:nowrap}
.hpe-box{width:82px;height:28px;border:5px solid #009b84;display:inline-block}
.brand-divider{width:2px;height:52px;background:#0a1930;opacity:.8}
.brand-title{font-size:32px;line-height:1;font-weight:800;letter-spacing:-1.3px}
.brand-sub{font-size:14px;margin-top:4px;color:#14223a}
.top-spacer{flex:1}
.panel{border:1px solid var(--line);background:white;border-radius:10px;padding:14px}
.panel-title{font-size:22px;font-weight:800;margin:0}
.panel-subtitle{color:#53627a;font-size:14px;margin-top:2px}
.station-card{border:1px solid var(--station);border-radius:9px;background:linear-gradient(135deg,var(--tint),#fff 90%);overflow:hidden;min-height:160px}
.station-main{display:flex;align-items:center;padding:14px;gap:12px;min-height:116px}
.station-icon{width:64px;height:64px;flex:0 0 64px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;background:var(--station);font-size:27px;font-weight:700}
.station-name{font-weight:800;font-size:14px;margin-bottom:6px;white-space:nowrap}
.station-count{font-size:36px;line-height:1;font-weight:800}
.station-label{font-size:13px;margin-top:3px}
.station-sla{padding:8px 14px;background:var(--tint);color:var(--station);border-top:1px solid var(--station);font-size:13px;font-weight:600}
.pill{display:inline-block;padding:5px 10px;border-radius:7px;font-size:12px;font-weight:700;white-space:nowrap}
.care{background:#fde1e8;color:#c51b45}.arch{background:#dcedfb;color:#006fbd}.pet{background:#dcf6e5;color:#087e3e}.supply{background:#eee4ff;color:#5e24c4}.fulfillment{background:#fff0c2;color:#9a5600}
.critical{background:#ffdce3;color:#c80c31}.high{background:#fce2e8;color:#b71e3d}.medium{background:#fff0c4;color:#995000}.low{background:#dcf7e5;color:#087b39}
.inprogress,.open,.completed{background:#e0efff;color:#075bc5}.pending,.closed{background:#e9edf2;color:#4b5b70}.resolved{background:#dcf7e5;color:#087b39}
.metric{background:#f7f9fc;border:1px solid #e7ebf1;border-radius:9px;padding:12px;text-align:center}
.metric-label{font-size:12px;color:#52617a;font-weight:600}
.metric-value{font-size:25px;font-weight:800;margin:5px 0}
.case-modal-head{background:linear-gradient(105deg,#006d70,#009c8c);color:white;padding:18px 22px;border-radius:10px;margin-bottom:12px}
.small-muted{color:#617087;font-size:12px}
.alertbox{border:1px solid #f3cb68;background:#fff5d9;border-radius:8px;padding:12px;color:#9b5300}
div[data-testid="stDataFrame"]{border:1px solid #e0e5ec;border-radius:8px}
.stButton button{border-radius:8px;font-weight:600;min-height:38px}
@media(max-width:900px){.topbar{padding:10px;gap:8px}.hpe-box{width:44px;height:20px}.hpe-mark{font-size:20px}.brand-title{font-size:23px}.brand-sub{font-size:11px}.station-icon{width:44px;height:44px;flex-basis:44px}.station-count{font-size:27px}.station-main{padding:9px;gap:7px}}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def cfg(key: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(key, os.getenv(key, default)))
    except Exception:
        return os.getenv(key, default)


@st.cache_resource(show_spinner=False)
def mongo_client():
    uri = cfg("MONGODB_URI")
    if not uri:
        return None
    client = MongoClient(uri, serverSelectionTimeoutMS=7000, connectTimeoutMS=7000)
    client.admin.command("ping")
    return client


def get_db():
    client = mongo_client()
    return client[DB_NAME] if client is not None else None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now_utc().isoformat(timespec="seconds")


def parse_dt(value: Any) -> datetime:
    if not value:
        return now_utc()
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return now_utc()


def fmt_duration(seconds: int | float) -> str:
    s = max(0, int(seconds or 0))
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def station_seconds(case: dict) -> int:
    history = case.get("station_history") or []
    if not history:
        return 0
    return max(0, int((now_utc() - parse_dt(history[-1].get("entered_at"))).total_seconds()))


def total_seconds(case: dict) -> int:
    created = parse_dt(case.get("created_at"))
    end = parse_dt(case.get("closed_at")) if case.get("closed_at") else now_utc()
    return max(0, int((end - created).total_seconds()))


def is_closed(case: dict) -> bool:
    return str(case.get("status", "")).upper() in CLOSED_STATUSES


def col(name: str):
    return get_db()[name]


def ensure_indexes():
    db = get_db()
    db.users.create_index([("email", ASCENDING)], unique=True)
    db.cases.create_index([("case_number", ASCENDING)], unique=True)
    db.cases.create_index([("status", ASCENDING), ("station", ASCENDING)])
    db.alert_events.create_index([("created_at", DESCENDING)])
    db.attachments.create_index([("case_id", ASCENDING)])
    db.collaboration.create_index([("case_id", ASCENDING), ("created_at", ASCENDING)])
    db.knowledge_base.create_index([("title", ASCENDING)])


def password_hash(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return salt.hex(), digest.hex()


def password_ok(password: str, salt_hex: str, digest_hex: str) -> bool:
    _, check = password_hash(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(check, digest_hex)


def allowed_email(email: str) -> bool:
    domains = [d.strip().lower().lstrip("@") for d in cfg("ALLOWED_EMAIL_DOMAINS", "hpe.com").split(",") if d.strip()]
    return "@" in email and email.rsplit("@", 1)[1].lower() in domains


def log_case(case_id: str, action: str, details: str, status: str | None = None):
    user = st.session_state.get("user", {})
    col("case_history").insert_one({
        "case_id": case_id, "at": iso_now(), "action": action,
        "status": status or "", "by": user.get("name", "System"),
        "email": user.get("email", ""), "details": details
    })


def get_case(case_id: str) -> dict | None:
    return col("cases").find_one({"_id": ObjectId(case_id)})


def public_case(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


def all_cases() -> list[dict]:
    return [public_case(x) for x in col("cases").find({}).sort("created_at", DESCENDING)]


def user_role() -> str:
    return st.session_state.get("user", {}).get("role", "Agent")


def require_admin():
    if user_role() != "Admin":
        st.error("Administrator access is required for this action.")
        return False
    return True


def create_alert(case: dict, event_type: str, message: str, severity: str = "warning"):
    col("alert_events").insert_one({
        "case_id": str(case.get("_id", case.get("id", ""))),
        "case_number": case.get("case_number", ""),
        "station": case.get("station", ""),
        "event_type": event_type, "message": message, "severity": severity,
        "created_at": iso_now(), "acknowledged_by": [], "active": True
    })


def check_sla_events(case: dict):
    if is_closed(case):
        return
    sla = int(get_setting("sla", SLA_DEFAULTS).get(case["station"], SLA_DEFAULTS[case["station"]]))
    elapsed = station_seconds(case)
    pct = elapsed / max(1, sla * 60) * 100
    fired = case.get("sla_alert_levels", [])
    for threshold, level in [(60, "AMBER"), (80, "RED"), (100, "BREACH")]:
        if pct >= threshold and level not in fired:
            case_id = case["id"]
            create_alert(case, level, f"{case['case_number']} reached {threshold}% of {case['station']} SLA.", "critical" if level != "AMBER" else "warning")
            fired.append(level)
            col("cases").update_one({"_id": ObjectId(case_id)}, {"$set": {"sla_alert_levels": fired}})


def get_setting(key: str, default: Any = None) -> Any:
    doc = col("settings").find_one({"_id": key})
    return doc.get("value", default) if doc else default


def save_setting(key: str, value: Any):
    col("settings").update_one({"_id": key}, {"$set": {"value": value, "updated_at": iso_now()}}, upsert=True)


def render_header():
    u = st.session_state.get("user", {})
    st.markdown(f"""
    <div class="topbar">
      <div class="hpe-mark"><span class="hpe-box"></span><span>HPE</span></div>
      <div class="brand-divider"></div>
      <div><div class="brand-title">OVR-VW</div><div class="brand-sub">Operations Visibility &amp; Response Workspace</div></div>
      <div class="top-spacer"></div>
      <div style="text-align:right;color:#fff"><b>{u.get('name','')}</b><br><small>{u.get('role','')}</small></div>
    </div>""", unsafe_allow_html=True)


def login_screen():
    st.markdown("<div style='max-width:540px;margin:6vh auto 0' class='panel'>", unsafe_allow_html=True)
    st.markdown("## OVR-VW Access")
    st.caption("Sign in with your registered company email.")
    login_tab, register_tab = st.tabs(["Sign In", "Register"])
    with login_tab:
        with st.form("login_form"):
            email = st.text_input("Company email", key="login_email").strip().lower()
            password = st.text_input("Password", type="password", key="login_password")
            submit = st.form_submit_button("Sign In", type="primary", use_container_width=True)
        if submit:
            user = col("users").find_one({"email": email, "active": True})
            if user and password_ok(password, user["salt"], user["password_hash"]):
                st.session_state.user = {"id": str(user["_id"]), "name": user["name"], "email": email, "role": user["role"]}
                st.rerun()
            st.error("Email or password is incorrect, or the account is inactive.")
    with register_tab:
        with st.form("register_form"):
            name = st.text_input("Full name")
            email = st.text_input("Company email").strip().lower()
            password = st.text_input("Password", type="password")
            confirm = st.text_input("Confirm password", type="password")
            admin_code = st.text_input("Admin setup code (leave blank for Agent)", type="password")
            submit = st.form_submit_button("Create Account", type="primary", use_container_width=True)
        if submit:
            if not name.strip() or not allowed_email(email):
                st.error("Enter your name and an approved company email address.")
            elif len(password) < 10:
                st.error("Use a password with at least 10 characters.")
            elif password != confirm:
                st.error("Passwords do not match.")
            elif col("users").find_one({"email": email}):
                st.error("An account already exists for this email.")
            else:
                salt, digest = password_hash(password)
                role = "Admin" if admin_code and hmac.compare_digest(admin_code, cfg("ADMIN_SETUP_CODE")) else "Agent"
                col("users").insert_one({"name": name.strip(), "email": email, "salt": salt, "password_hash": digest,
                                         "role": role, "active": True, "created_at": iso_now()})
                st.success(f"Account created as {role}. Sign in to continue.")
    st.markdown("</div>", unsafe_allow_html=True)


def station_badge(station: str) -> str:
    cls = {"CARE":"care","ARCH":"arch","PET":"pet","SUPPLY CHAIN":"supply","FULFILLMENT":"fulfillment"}.get(station, "care")
    return f'<span class="pill {cls}">{station}</span>'


def priority_badge(priority: str) -> str:
    cls = str(priority).lower()
    return f'<span class="pill {cls}">{priority}</span>'


def status_badge(status: str) -> str:
    s = str(status).upper()
    cls = "inprogress" if s == "IN PROGRESS" else ("resolved" if s == "RESOLVED" else ("closed" if s == "CLOSED" else "pending"))
    return f'<span class="pill {cls}">{status}</span>'


def station_cards(cases: list[dict], closed: bool = False):
    cols = st.columns(5, gap="small")
    for i, station in enumerate(STATIONS):
        count = sum(1 for c in cases if c.get("station") == station)
        icon = {"CARE":"♧","ARCH":"▤","PET":"⚙","SUPPLY CHAIN":"♧","FULFILLMENT":"⚒"}[station]
        with cols[i]:
            st.markdown(f"""
            <div class="station-card" style="--station:{STATION_COLORS[station]};--tint:{STATION_TINTS[station]}">
              <div class="station-main"><div class="station-icon">{icon}</div><div>
                <div class="station-name">{station}</div><div class="station-count">{count}</div>
                <div class="station-label">{'Closed Cases' if closed else 'Active Cases'}</div>
              </div></div>
              <div class="station-sla">◷ &nbsp; SLA {int(get_setting('sla',SLA_DEFAULTS).get(station,SLA_DEFAULTS[station]))} minutes</div>
            </div>""", unsafe_allow_html=True)


@st.fragment(run_every=1)
def dashboard():
    cases = all_cases()
    active = [c for c in cases if not is_closed(c)]
    for case in active:
        check_sla_events(case)
    closed = [c for c in cases if is_closed(c)]
    tab_active, tab_closed = st.tabs(["Active Cases  ·  Current operational queue", "Closed Cases  ·  Resolved case history"])
    with tab_active:
        station_cards(active)
        st.markdown("<div class='panel-title'>Active Cases</div><div class='panel-subtitle'>Live operational cases across all stations</div>", unsafe_allow_html=True)
        render_case_list(active, False)
    with tab_closed:
        station_cards(closed, True)
        st.markdown("<div class='panel-title'>Closed Cases</div><div class='panel-subtitle'>Resolved, completed and closed case history</div>", unsafe_allow_html=True)
        render_case_list(closed, True)


def render_case_list(cases: list[dict], closed: bool):
    q = st.text_input("Search cases", key="closed_search" if closed else "active_search",
                      placeholder="Search case number, subject, account, assignee...")
    c1, c2, c3 = st.columns([1,1,1])
    station = c1.selectbox("Station", ["All Stations"] + STATIONS, key="closed_station" if closed else "active_station")
    priority = c2.selectbox("Priority", ["All Priorities"] + PRIORITIES, key="closed_priority" if closed else "active_priority")
    status_options = ["All Statuses"] + (["Resolved","Completed","Closed"] if closed else STATUSES[:5])
    status = c3.selectbox("Status", status_options, key="closed_status" if closed else "active_status")
    filtered = list(cases)
    if q:
        filtered = [c for c in filtered if q.lower() in " ".join(str(c.get(k,"")) for k in ["case_number","subject","account","assignee","station"]).lower()]
    if station != "All Stations":
        filtered = [c for c in filtered if c.get("station") == station]
    if priority != "All Priorities":
        filtered = [c for c in filtered if c.get("priority") == priority]
    if status != "All Statuses":
        filtered = [c for c in filtered if c.get("status","").upper() == status.upper()]
    filtered.sort(key=lambda c: (0 if c.get("priority") == "CRITICAL" else 1, -station_seconds(c)), reverse=False)
    rows = []
    for c in filtered:
        elapsed = total_seconds(c) if closed else station_seconds(c)
        sla = int(get_setting("sla", SLA_DEFAULTS).get(c["station"], SLA_DEFAULTS[c["station"]])) * 60
        pct = elapsed / max(sla, 1) * 100
        indicator = "🔴" if pct >= 80 else ("🟠" if pct >= 60 else "🟢")
        rows.append({
            "Case Number": c.get("case_number"), "Subject": c.get("subject"), "Account": c.get("account"),
            "Station": c.get("station"), "Assignee": c.get("assignee"), "Priority": c.get("priority"),
            "Status": c.get("status"), "Duration": fmt_duration(elapsed), "SLA": indicator,
            "Closed Date": c.get("closed_at","")[:16].replace("T"," ") if closed else ""
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                     height=min(550, 42 + len(rows)*38))
        choices = {f"{c['case_number']} — {c['subject']}": c["id"] for c in filtered}
        pick = st.selectbox("Open case details", ["Select a case..."] + list(choices),
                            key="open_closed_case" if closed else "open_active_case")
        if pick != "Select a case..." and st.button("View Case", type="primary", key="view_closed_case" if closed else "view_active_case"):
            st.session_state.open_case_id = choices[pick]
            st.rerun()
    else:
        st.info("No cases match the selected filters.")


def render_case_detail(case_id: str):
    case = get_case(case_id)
    if not case:
        st.warning("This case is no longer available.")
        st.session_state.open_case_id = None
        return
    cid = str(case["_id"])
    st.markdown("<div class='case-modal-head'><h2 style='margin:0;color:white'>Case Details</h2><div>Case information, actions, knowledge base, collaboration and attachments</div></div>", unsafe_allow_html=True)
    a,b,c,d,e = st.columns([1.2,1.4,.8,1,1])
    a.markdown(f"**Case Number**<br><b>{html.escape(str(case['case_number']))}</b>", unsafe_allow_html=True)
    b.markdown(f"**Subject**<br>{html.escape(str(case['subject']))}", unsafe_allow_html=True)
    c.markdown(f"**Priority**<br>{priority_badge(case['priority'])}", unsafe_allow_html=True)
    with d:
        new_status = st.selectbox("Status", STATUSES, index=STATUSES.index(case["status"]) if case["status"] in STATUSES else 1, key=f"case_status_{cid}")
        if new_status != case["status"]:
            col("cases").update_one({"_id":case["_id"]},{"$set":{"status":new_status,"updated_at":iso_now()}})
            log_case(cid,"Status Updated",f"{case['status']} → {new_status}",new_status)
            st.rerun()
    with e:
        st.markdown(f"**Station**<br>{station_badge(case['station'])}", unsafe_allow_html=True)
    tabs = st.tabs(["Case Information","Case Actions","Knowledge Base","Collaboration","Attachments"])
    with tabs[0]:
        left,right = st.columns([1,1.4])
        with left:
            st.markdown("### Case Overview")
            details = {
                "Account":case.get("account"),"Vendor":case.get("vendor",""),"Department":case.get("department",""),
                "Issue Category":case.get("issue_category",""),"Assignee":case.get("assignee",""),
                "Created":case.get("created_at",""),"Last Updated":case.get("updated_at",""),
                "Source":case.get("source","Manual")
            }
            st.dataframe(pd.DataFrame([{"Field":k,"Value":v} for k,v in details.items()]),hide_index=True,use_container_width=True)
            st.markdown("### Description")
            st.write(case.get("description",""))
        with right:
            st.markdown("### SLA & Timing")
            elapsed = station_seconds(case)
            sla_seconds = int(get_setting("sla",SLA_DEFAULTS).get(case["station"],SLA_DEFAULTS[case["station"]]))*60
            pct = min(100, elapsed/max(1,sla_seconds)*100)
            x,y,z = st.columns(3)
            x.metric("Station Duration",fmt_duration(elapsed))
            y.metric("Total Elapsed",fmt_duration(total_seconds(case)))
            z.metric("SLA Used",f"{pct:.0f}%")
            st.progress(min(1.0,pct/100))
            if pct >= 100: st.error("SLA breached")
            elif pct >= 80: st.error("Critical SLA warning")
            elif pct >= 60: st.warning("SLA approaching threshold")
            st.markdown("### Station Journey")
            hist = case.get("station_history",[])
            for station_name in STATIONS:
                done = any(h.get("station")==station_name for h in hist)
                st.write(("✓" if done else "○") + "  " + station_name)
            st.markdown("### Station Duration History")
            if hist:
                history_rows=[]
                for h in hist:
                    seconds = h.get("duration_seconds",0)
                    if not h.get("exited_at") and h.get("station")==case["station"]:
                        seconds=station_seconds(case)
                    history_rows.append({"Station":h["station"],"Entered":h.get("entered_at",""),"Exited":h.get("exited_at",""),"Duration":fmt_duration(seconds)})
                st.dataframe(pd.DataFrame(history_rows),hide_index=True,use_container_width=True)
    with tabs[1]:
        st.markdown("### Station Checklist")
        checklist = case.get("checklist") or [{"text":x,"done":False} for x in CHECKLIST_DEFAULTS]
        for i,item in enumerate(checklist):
            c1,c2 = st.columns([.9,.1])
            done = c1.checkbox(item.get("text",""),value=bool(item.get("done")),key=f"check_{cid}_{i}")
            if done != bool(item.get("done")):
                checklist[i]["done"]=done
                col("cases").update_one({"_id":case["_id"]},{"$set":{"checklist":checklist,"updated_at":iso_now()}})
                log_case(cid,"Checklist Updated",f"{item['text']} — {'Completed' if done else 'Reopened'}",case["status"])
                st.rerun()
            if c2.button("×",key=f"delete_check_{cid}_{i}",help="Delete checklist item"):
                checklist.pop(i)
                col("cases").update_one({"_id":case["_id"]},{"$set":{"checklist":checklist}})
                log_case(cid,"Checklist Item Deleted",item.get("text",""))
                st.rerun()
        with st.form(f"add_check_{cid}"):
            new_item=st.text_input("Add checklist item",placeholder="Enter a new action/check")
            add=st.form_submit_button("＋ Add Item")
        if add and new_item.strip():
            checklist.append({"text":new_item.strip(),"done":False})
            col("cases").update_one({"_id":case["_id"]},{"$set":{"checklist":checklist}})
            log_case(cid,"Checklist Item Added",new_item.strip())
            st.rerun()
        st.divider()
        with st.form(f"action_plan_{cid}"):
            plan=st.text_area("Action Plan",value=case.get("action_plan",""),height=100)
            summary=st.text_area("Resolution / Assessment Notes",value=case.get("resolution",""),height=90)
            save=st.form_submit_button("Save Case Actions",type="primary")
        if save:
            col("cases").update_one({"_id":case["_id"]},{"$set":{"action_plan":plan,"resolution":summary,"updated_at":iso_now()}})
            log_case(cid,"Case Actions Saved","Action plan and assessment updated.")
            st.success("Case actions saved.")
            st.rerun()
        all_done = bool(checklist) and all(x.get("done") for x in checklist)
        next_station = STATIONS[STATIONS.index(case["station"])+1] if case["station"] in STATIONS[:-1] else None
        if next_station:
            if not all_done:
                st.warning("Complete every checklist item before transferring this case.")
            if st.button(f"Transfer to {next_station}",disabled=not all_done,type="primary",key=f"transfer_{cid}"):
                history=case.get("station_history",[])
                if history:
                    history[-1]["exited_at"]=iso_now()
                    history[-1]["duration_seconds"]=station_seconds(case)
                history.append({"station":next_station,"entered_at":iso_now(),"exited_at":"","duration_seconds":0})
                reset_check=[{"text":x,"done":False} for x in CHECKLIST_DEFAULTS]
                col("cases").update_one({"_id":case["_id"]},{"$set":{"station":next_station,"station_history":history,"checklist":reset_check,"updated_at":iso_now(),"sla_alert_levels":[]}})
                log_case(cid,"Case Transferred",f"{case['station']} → {next_station}")
                create_alert({**case,"station":next_station},"TRANSFER",f"{case['case_number']} transferred to {next_station}.","info")
                st.success(f"Transferred to {next_station}.")
                st.rerun()
        else:
            st.markdown("### Final Station Resolution")
            if st.button("Close Case",type="primary",key=f"close_{cid}"):
                if not case.get("resolution","").strip():
                    st.error("Enter the resolution/assessment notes before closing.")
                else:
                    history=case.get("station_history",[])
                    if history:
                        history[-1]["exited_at"]=iso_now()
                        history[-1]["duration_seconds"]=station_seconds(case)
                    col("cases").update_one({"_id":case["_id"]},{"$set":{"status":"Closed","closed_at":iso_now(),"station_history":history,"updated_at":iso_now()}})
                    log_case(cid,"Case Closed",case.get("resolution",""),"Closed")
                    st.session_state.open_case_id=None
                    st.success("Case closed.")
                    st.rerun()
        st.markdown("### Case History")
        hist_rows=list(col("case_history").find({"case_id":cid}).sort("at",DESCENDING).limit(100))
        if hist_rows:
            st.dataframe(pd.DataFrame([{k:r.get(k,"") for k in ["at","action","status","by","details"]} for r in hist_rows]),hide_index=True,use_container_width=True)
        else:
            st.caption("No history recorded yet.")
    with tabs[2]:
        st.markdown("### Knowledge Base")
        q=st.text_input("Search knowledge articles",key=f"kb_search_{cid}")
        articles=list(col("knowledge_base").find({"active":True}).limit(100))
        if q:
            articles=[a for a in articles if q.lower() in (a.get("title","")+" "+a.get("content","")+" "+a.get("tags","")).lower()]
        if articles:
            for art in articles:
                with st.expander(f"{art.get('title','Untitled')}  ·  {art.get('category','General')}"):
                    st.write(art.get("content",""))
                    st.caption(art.get("tags",""))
        else:
            st.info("No matching knowledge articles. Administrators can add articles in Settings.")
    with tabs[3]:
        st.markdown("### Collaboration")
        messages=list(col("collaboration").find({"case_id":cid}).sort("created_at",ASCENDING).limit(200))
        for msg in messages:
            st.markdown(f"**{html.escape(str(msg.get('name','User')))}** · <small>{html.escape(str(msg.get('created_at','')))}</small><br>{html.escape(str(msg.get('message','')))}",unsafe_allow_html=True)
        with st.form(f"collab_{cid}",clear_on_submit=True):
            message=st.text_input("Message")
            send=st.form_submit_button("Send Message",type="primary")
        if send and message.strip():
            u=st.session_state.user
            col("collaboration").insert_one({"case_id":cid,"name":u["name"],"email":u["email"],"message":message.strip(),"created_at":iso_now()})
            log_case(cid,"Collaboration Message",message.strip())
            st.rerun()
        st.info("Messages are stored in MongoDB and shared with other signed-in users. A live video bridge requires a separate conferencing provider.")
    with tabs[4]:
        st.markdown("### Attachments")
        uploads=st.file_uploader("Upload case files",accept_multiple_files=True,key=f"uploads_{cid}")
        if uploads:
            for up in uploads:
                if up.size > 10*1024*1024:
                    st.error(f"{up.name} exceeds the 10 MB per-file limit.")
                    continue
                exists=col("attachments").find_one({"case_id":cid,"filename":up.name,"size":up.size})
                if not exists:
                    col("attachments").insert_one({"case_id":cid,"filename":up.name,"content_type":up.type,"size":up.size,
                                                   "data":Binary(up.getvalue()),"uploaded_by":st.session_state.user["email"],"created_at":iso_now()})
                    log_case(cid,"Attachment Uploaded",up.name)
        files=list(col("attachments").find({"case_id":cid}))
        for f in files:
            x,y=st.columns([.8,.2])
            x.write(f"📎 {f['filename']}  ·  {f['size']:,} bytes")
            y.download_button("Download",bytes(f["data"]),file_name=f["filename"],mime=f.get("content_type","application/octet-stream"),key=f"download_{f['_id']}")
            if user_role()=="Admin" and st.button("Delete",key=f"delete_attachment_{f['_id']}"):
                col("attachments").delete_one({"_id":f["_id"]})
                st.rerun()
    if st.button("← Back to Dashboard",key=f"back_{cid}"):
        st.session_state.open_case_id=None
        st.rerun()


def create_case(case_data: dict, simulated: bool = False) -> str:
    case_data.setdefault("case_number", f"OVR-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:5].upper()}")
    case_data.setdefault("created_at", iso_now())
    case_data.setdefault("updated_at", iso_now())
    case_data.setdefault("status", "In Progress")
    case_data.setdefault("priority", "MEDIUM")
    case_data.setdefault("checklist", [{"text":x,"done":False} for x in CHECKLIST_DEFAULTS])
    case_data.setdefault("station_history", [{"station":case_data["station"],"entered_at":iso_now(),"exited_at":"","duration_seconds":0}])
    case_data.setdefault("sla_alert_levels", [])
    case_data["is_simulated"] = simulated
    case_data["created_by"] = st.session_state.user["email"]
    result=col("cases").insert_one(case_data)
    log_case(str(result.inserted_id),"Case Created","Case created.")
    return str(result.inserted_id)


def settings_page():
    st.markdown("<div class='panel-title'>Settings</div><div class='panel-subtitle'>Manage alert rules, data, simulation and access</div>",unsafe_allow_html=True)
    tabs=st.tabs(["General","Alert Management","Data Import","Export Data","Simulation","Users & KB"])
    with tabs[0]:
        st.markdown("### Station SLA Configuration")
        sla=get_setting("sla",SLA_DEFAULTS)
        with st.form("sla_settings"):
            updated={}
            cols=st.columns(5)
            for i,s in enumerate(STATIONS):
                updated[s]=cols[i].number_input(f"{s} (minutes)",min_value=1,max_value=1440,value=int(sla.get(s,SLA_DEFAULTS[s])))
            save=st.form_submit_button("Save SLA Settings",type="primary")
        if save:
            if require_admin():
                save_setting("sla",updated)
                st.success("SLA settings saved.")
        st.markdown("### Case Creation")
        with st.form("manual_case"):
            a,b,c=st.columns(3)
            case_number=a.text_input("Case Number (optional)")
            subject=b.text_input("Subject")
            account=c.text_input("Account")
            d,e,f=st.columns(3)
            station=d.selectbox("Station",STATIONS)
            assignee=e.text_input("Assignee")
            priority=f.selectbox("Priority",PRIORITIES,index=2)
            vendor=st.text_input("Vendor")
            description=st.text_area("Description")
            submit=st.form_submit_button("Create Case",type="primary")
        if submit:
            if not subject.strip() or not account.strip():
                st.error("Subject and Account are required.")
            elif require_admin():
                data={"subject":subject.strip(),"account":account.strip(),"station":station,"assignee":assignee.strip() or "Unassigned",
                      "priority":priority,"vendor":vendor.strip(),"description":description.strip(),"source":"Manual"}
                if case_number.strip(): data["case_number"]=case_number.strip()
                try:
                    cid=create_case(data)
                    st.success(f"Case created: {cid}")
                except Exception as ex: st.error(f"Could not create case: {ex}")
    with tabs[1]:
        st.markdown("### Alert Management")
        rules=get_setting("alert_rules",[
            {"name":"SLA Amber","threshold":60,"color":"Amber","icon":"⚠","enabled":True},
            {"name":"SLA Red","threshold":80,"color":"Red","icon":"!","enabled":True},
            {"name":"SLA Breach","threshold":100,"color":"Dark Red","icon":"▲","enabled":True},
            {"name":"High Priority Account","threshold":0,"color":"Purple","icon":"★","enabled":True},
        ])
        edited=[]
        for i,r in enumerate(rules):
            with st.expander(r["name"],expanded=False):
                a,b,c,d=st.columns([2,1,1,1])
                name=a.text_input("Name",r["name"],key=f"rule_name_{i}")
                threshold=b.number_input("Threshold %",0,100,int(r.get("threshold",0)),key=f"rule_threshold_{i}")
                color=c.selectbox("Color",["Amber","Red","Dark Red","Purple","Blue","Green"],index=["Amber","Red","Dark Red","Purple","Blue","Green"].index(r.get("color","Amber")) if r.get("color","Amber") in ["Amber","Red","Dark Red","Purple","Blue","Green"] else 0,key=f"rule_color_{i}")
                enabled=d.checkbox("Enabled",bool(r.get("enabled",True)),key=f"rule_enabled_{i}")
                icon=st.text_input("Icon",r.get("icon","⚠"),key=f"rule_icon_{i}")
                edited.append({"name":name,"threshold":threshold,"color":color,"icon":icon,"enabled":enabled})
        with st.form("add_alert_rule"):
            new_rule=st.text_input("New alert rule name")
            new_threshold=st.number_input("Trigger threshold (%)",0,100,60)
            add_rule=st.form_submit_button("＋ Add Alert Rule")
        if add_rule and new_rule.strip():
            edited.append({"name":new_rule.strip(),"threshold":new_threshold,"color":"Amber","icon":"⚠","enabled":True})
        if st.button("Save Alert Rules",type="primary"):
            if require_admin():
                save_setting("alert_rules",edited)
                st.success("Alert rules saved.")
    with tabs[2]:
        st.markdown("### Import Cases")
        up=st.file_uploader("Upload Excel or CSV",type=["xlsx","xls","csv"],key="case_import")
        if up:
            try:
                df=pd.read_csv(up) if up.name.lower().endswith(".csv") else pd.read_excel(up)
                st.dataframe(df.head(20),use_container_width=True)
                mapping={}
                fields=["case_number","subject","account","station","assignee","priority","status","description","vendor","department","issue_category"]
                for field in fields:
                    options=["(skip)"]+list(df.columns)
                    default=next((x for x in df.columns if x.lower().replace(" ","_")==field),"(skip)")
                    mapping[field]=st.selectbox(f"Map {field}",options,index=options.index(default),key=f"map_{field}")
                if st.button("Import Previewed Rows",type="primary"):
                    if not require_admin(): return
                    imported=0
                    for _,row in df.iterrows():
                        data={k:str(row[v]).strip() for k,v in mapping.items() if v!="(skip)" and pd.notna(row[v])}
                        if not data.get("subject") or not data.get("account") or data.get("station") not in STATIONS:
                            continue
                        data.setdefault("assignee","Unassigned")
                        data.setdefault("priority","MEDIUM")
                        data.setdefault("status","In Progress")
                        data["source"]=up.name
                        create_case(data)
                        imported+=1
                    st.success(f"Imported {imported} case(s).")
            except Exception as ex: st.error(f"Import failed: {ex}")
        st.download_button("Download Import Template",pd.DataFrame(columns=["case_number","subject","account","station","assignee","priority","status","description"]).to_csv(index=False),"ovr_vw_import_template.csv","text/csv")
    with tabs[3]:
        st.markdown("### Export Operational Data")
        cases=all_cases()
        df=pd.DataFrame([{k:c.get(k,"") for k in ["case_number","subject","account","station","assignee","priority","status","created_at","closed_at","source"]} for c in cases])
        if df.empty: st.info("No case data to export.")
        else:
            st.dataframe(df,use_container_width=True,hide_index=True)
            a,b=st.columns(2)
            with a:
                st.download_button("Export CSV",df.to_csv(index=False).encode(),"ovr_vw_export.csv","text/csv",use_container_width=True)
                excel=io.BytesIO()
                with pd.ExcelWriter(excel,engine="openpyxl") as writer: df.to_excel(writer,index=False,sheet_name="Cases")
                st.download_button("Export Excel",excel.getvalue(),"ovr_vw_export.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",use_container_width=True)
            with b:
                st.download_button("Export JSON",json.dumps(cases,default=str,indent=2).encode(),"ovr_vw_export.json","application/json",use_container_width=True)
    with tabs[4]:
        st.markdown("### Simulation Controls")
        st.caption("Simulation data is only created when explicitly triggered.")
        with st.form("simulation"):
            sim_type=st.selectbox("Simulation Type",["Single Case","Multiple Cases","Station Load","High Priority H&M Event"])
            station=st.selectbox("Station",STATIONS)
            priority=st.selectbox("Priority",PRIORITIES,index=0)
            account=st.text_input("Account","H&M" if sim_type=="High Priority H&M Event" else "Global Retail")
            subject=st.text_input("Subject","Store network outage")
            assignee=st.text_input("Assignee","Unassigned")
            description=st.text_area("Description","Simulated case for testing workflow and SLA alert behavior.")
            trigger=st.checkbox("Trigger shared alert",True)
            start=st.form_submit_button("▶ Start Simulation",type="primary")
        if start:
            if not require_admin(): return
            n={"Single Case":1,"Multiple Cases":5,"Station Load":10,"High Priority H&M Event":1}[sim_type]
            created=[]
            for i in range(n):
                is_hm=sim_type=="High Priority H&M Event"
                data={"subject":subject if i==0 else f"{subject} #{i+1}","account":account,"station":"CARE" if is_hm else station,
                      "assignee":assignee,"priority":"CRITICAL" if is_hm else priority,"description":description,
                      "vendor":"Aruba Networks","issue_category":"Network Connectivity","source":"Simulation"}
                if is_hm: data["created_at"]=iso_now()
                created.append(create_case(data,True))
            if trigger:
                event={"title":"Simulation Alert","message":f"{account}: {subject}","case_id":created[0],"created_at":iso_now(),"show_after_seconds":3,"active":True}
                col("simulation_events").insert_one(event)
            st.success(f"Created {n} simulated case(s).")
            st.rerun()
        sims=[c for c in all_cases() if c.get("is_simulated")]
        if sims:
            st.dataframe(pd.DataFrame([{"Case":c["case_number"],"Subject":c["subject"],"Station":c["station"],"Priority":c["priority"]} for c in sims]),use_container_width=True,hide_index=True)
            if st.button("Reset Simulated Cases"):
                if require_admin():
                    for s in sims: col("cases").delete_one({"_id":ObjectId(s["id"])})
                    st.success("Simulated cases removed.")
                    st.rerun()
    with tabs[5]:
        st.markdown("### User Administration")
        if require_admin():
            users=list(col("users").find({},{"password_hash":0,"salt":0}))
            if users:
                st.dataframe(pd.DataFrame([{"Name":u["name"],"Email":u["email"],"Role":u["role"],"Active":u.get("active",True)} for u in users]),use_container_width=True,hide_index=True)
                user_email=st.selectbox("Select user",[""]+[u["email"] for u in users])
                if user_email:
                    target=next(u for u in users if u["email"]==user_email)
                    x,y=st.columns(2)
                    role=x.selectbox("Role",["Admin","Agent"],index=0 if target["role"]=="Admin" else 1,key="user_role_edit")
                    active=y.checkbox("Account active",bool(target.get("active",True)),key="user_active_edit")
                    if st.button("Update User"):
                        col("users").update_one({"_id":target["_id"]},{"$set":{"role":role,"active":active}})
                        st.success("User updated.")
                        st.rerun()
        st.divider()
        st.markdown("### Knowledge Base Articles")
        with st.form("kb_add"):
            title=st.text_input("Article title")
            category=st.text_input("Category","General")
            tags=st.text_input("Tags")
            content=st.text_area("Article content",height=140)
            save=st.form_submit_button("Save Article")
        if save and title.strip() and content.strip():
            if require_admin():
                col("knowledge_base").insert_one({"title":title.strip(),"category":category.strip(),"tags":tags.strip(),"content":content.strip(),"active":True,"created_at":iso_now()})
                st.success("Knowledge article saved.")
                st.rerun()
        articles=list(col("knowledge_base").find({"active":True}))
        for art in articles:
            with st.expander(art["title"]):
                st.write(art.get("content",""))
                if user_role()=="Admin" and st.button("Deactivate Article",key=f"deactivate_{art['_id']}"):
                    col("knowledge_base").update_one({"_id":art["_id"]},{"$set":{"active":False}})
                    st.rerun()


@st.fragment(run_every=2)
def alerts_panel():
    # Release delayed simulation alerts once their configured delay has elapsed.
    for sim in col("simulation_events").find({"active": True, "delivered": {"$ne": True}}):
        created = parse_dt(sim.get("created_at"))
        delay = int(sim.get("show_after_seconds", 3))
        if (now_utc() - created).total_seconds() >= delay:
            target = col("cases").find_one({"_id": ObjectId(sim["case_id"])}) if sim.get("case_id") else None
            if target:
                create_alert(target, "SIMULATION", sim.get("message", "Simulation alert"), "critical")
            col("simulation_events").update_one({"_id": sim["_id"]}, {"$set": {"delivered": True}})
    events=list(col("alert_events").find({"active":True}).sort("created_at",DESCENDING).limit(20))
    if not events: return
    pending=[]
    email=st.session_state.user["email"]
    for ev in events:
        if email not in ev.get("acknowledged_by",[]):
            pending.append(ev)
    if pending:
        ev=pending[0]
        st.markdown(f"<div class='alertbox'><b>🔔 {ev.get('event_type','Alert')} · {ev.get('case_number','')}</b><br>{ev.get('message','')}</div>",unsafe_allow_html=True)
        a,b=st.columns([.25,.75])
        with a:
            if st.button("Acknowledge",key=f"ack_{ev['_id']}"):
                col("alert_events").update_one({"_id":ev["_id"]},{"$addToSet":{"acknowledged_by":email}})
                st.rerun()
        with b:
            if ev.get("case_id") and st.button("View Case",key=f"alert_view_{ev['_id']}"):
                try: st.session_state.open_case_id=ev["case_id"]
                except Exception: pass
                col("alert_events").update_one({"_id":ev["_id"]},{"$addToSet":{"acknowledged_by":email}})
                st.rerun()


def main():
    if not cfg("MONGODB_URI"):
        st.error("MongoDB is not configured. Add MONGODB_URI to .streamlit/secrets.toml before running OVR-VW.")
        st.code('MONGODB_URI = "mongodb+srv://<username>:<password>@<cluster>/<database>?retryWrites=true&w=majority"\\nMONGODB_DB = "OVR_VW"\\nALLOWED_EMAIL_DOMAINS = "hpe.com"\\nADMIN_SETUP_CODE = "replace-with-a-long-random-code"')
        st.stop()
    try:
        db=get_db()
        ensure_indexes()
    except Exception as ex:
        st.error(f"MongoDB connection failed: {ex}")
        st.info("Check the Atlas connection string, database user permissions, network access list, and internet connection.")
        st.stop()
    if not st.session_state.get("user"):
        login_screen()
        return
    user=col("users").find_one({"_id":ObjectId(st.session_state.user["id"]),"active":True})
    if not user:
        st.session_state.clear()
        st.rerun()
    render_header()
    nav1,nav2,nav3,nav4=st.columns([1,1,1,5])
    with nav1:
        if st.button("Dashboard",use_container_width=True,type="primary" if st.session_state.get("page","Dashboard")=="Dashboard" else "secondary"):
            st.session_state.page="Dashboard";st.rerun()
    with nav2:
        if st.button("Settings",use_container_width=True,type="primary" if st.session_state.get("page")=="Settings" else "secondary"):
            st.session_state.page="Settings";st.rerun()
    with nav3:
        if st.button("Sign Out",use_container_width=True):
            st.session_state.clear();st.rerun()
    with nav4:
        q=st.text_input("Global search",placeholder="Search cases by number, subject, account, assignee...",label_visibility="collapsed",key="global_search")
    alerts_panel()
    if q:
        results=[c for c in all_cases() if q.lower() in " ".join(str(c.get(k,"")) for k in ["case_number","subject","account","assignee","station"]).lower()]
        st.markdown("### Search Results")
        if results:
            for c in results[:50]:
                if st.button(f"{c['case_number']}  ·  {c['subject']}  ·  {c['station']}",key=f"search_{c['id']}"):
                    st.session_state.open_case_id=c["id"];st.rerun()
        else: st.info("No matching cases.")
    elif st.session_state.get("page","Dashboard")=="Settings":
        settings_page()
    elif st.session_state.get("open_case_id"):
        render_case_detail(st.session_state.open_case_id)
    else:
        dashboard()
    st.markdown("<div class='small-muted' style='text-align:center;padding:18px'>OVR-VW · Operations Visibility &amp; Response Workspace · MongoDB Connected</div>",unsafe_allow_html=True)


if __name__ == "__main__":
    main()
