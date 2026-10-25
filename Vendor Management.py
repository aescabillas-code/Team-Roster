"""
OVR-VW — Operations Visibility & Response Workspace
Single-file Streamlit implementation inspired by the supplied UI references.

Run:
    py -m pip install streamlit pandas openpyxl pymongo
    streamlit run ovr_vw_app.py

Optional:
    Set MONGODB_URI in .streamlit/secrets.toml to enable MongoDB persistence.
    Without MongoDB, the app uses a local SQLite database (ovr_vw.db).

Notes:
- The script implements the dashboard, active/closed case views, case detail tabs,
  SLA timing, checklists, collaboration, attachments metadata, settings, alerts,
  Excel/CSV import, exports, and simulation controls.
- The supplied screenshots are visual references; some external services (real
  desktop notifications, multi-user push/audio delivery, and object storage) need
  deployment-specific configuration to work across browsers/users.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

APP_NAME = "OVR-VW"
DB_PATH = Path("ovr_vw.db")
STATIONS = ["CARE", "ARCH", "PET", "SUPPLY CHAIN", "FULFILLMENT"]
SLA_DEFAULTS = {"CARE": 15, "ARCH": 30, "PET": 45, "SUPPLY CHAIN": 30, "FULFILLMENT": 120}
STATION_CLASS = {"CARE": "care", "ARCH": "arch", "PET": "pet", "SUPPLY CHAIN": "supply", "FULFILLMENT": "fulfillment"}
STATION_COLORS = {"CARE": "#e6295b", "ARCH": "#078bd0", "PET": "#10a85b", "SUPPLY CHAIN": "#7c3fe4", "FULFILLMENT": "#e8a900"}
PRIORITY_COLORS = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
STATUS_COLORS = {"IN PROGRESS": "inprogress", "OPEN": "open", "PENDING INTERNAL": "pending", "PENDING CUSTOMER": "pending", "WAITING": "pending", "RESOLVED": "resolved", "COMPLETED": "completed", "CLOSED": "closed"}

st.set_page_config(page_title="OVR-VW | Operations Visibility & Response Workspace", page_icon="◈", layout="wide", initial_sidebar_state="collapsed")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root { --navy:#081b3b; --teal:#008f83; --blue:#0868e8; --line:#dfe5ec; --muted:#5d6b82; }
html, body, [class*="css"] { font-family:Inter,system-ui,sans-serif !important; color:var(--navy); }
.stApp { background:#f7f9fc; }
header[data-testid="stHeader"], footer, #MainMenu { visibility:hidden; height:0; }
.block-container { max-width:100% !important; padding:0.5rem 1.15rem 2rem !important; }
div[data-testid="stVerticalBlock"] { gap:.55rem; }
.topbar { margin:-.5rem -1.15rem .8rem; padding:12px 2rem; min-height:78px; display:flex; align-items:center; gap:20px; color:#071a37; background:linear-gradient(110deg,#fff 0%,#e8f6f7 43%,#087c84 56%,#06384f 72%,#061b36 100%); border-bottom:1px solid #d7e1e9; }
.hpe-mark { display:flex; align-items:center; gap:10px; font-size:26px; font-weight:800; color:#070b15; white-space:nowrap; }
.hpe-box { width:82px; height:28px; border:5px solid #009b84; display:inline-block; }
.brand-divider { width:2px; height:52px; background:#0a1930; opacity:.8; }
.brand-title { font-size:32px; line-height:1; font-weight:800; letter-spacing:-1.3px; }
.brand-sub { font-size:14px; margin-top:4px; color:#14223a; }
.top-spacer { flex:1; }
.top-search { min-width:300px; max-width:480px; width:36%; background:#fff; padding:13px 17px; border-radius:12px; color:#66738a; box-shadow:0 1px 4px #0001; font-size:14px; }
.section-tabs { display:flex; gap:8px; margin:4px 0 12px; }
.section-tab { flex:1; text-align:center; padding:12px 8px; border-radius:8px; background:#e9eef4; font-weight:700; font-size:16px; }
.section-tab.active { color:#fff; background:linear-gradient(100deg,#009d8d,#008d83); }
.station-card { border:1px solid var(--station); border-radius:9px; background:linear-gradient(135deg,var(--tint),#fff 90%); overflow:hidden; min-height:171px; }
.station-main { display:flex; align-items:center; padding:16px 16px 10px; gap:14px; min-height:125px; }
.station-icon { width:76px; height:76px; flex:0 0 76px; border-radius:50%; display:flex; align-items:center; justify-content:center; color:#fff; background:var(--station); font-size:31px; font-weight:700; }
.station-name { font-weight:800; font-size:16px; margin-bottom:6px; white-space:nowrap; }
.station-count { font-size:39px; line-height:1; font-weight:800; }
.station-label { font-size:14px; margin-top:3px; }
.station-sla { padding:9px 16px; background:var(--tint); color:var(--station); border-top:1px solid var(--station); font-size:14px; font-weight:600; }
.panel { border:1px solid var(--line); background:white; border-radius:10px; padding:14px; }
.panel-title { font-size:22px; font-weight:800; margin:0; }
.panel-subtitle { color:#53627a; font-size:14px; margin-top:2px; }
.case-modal-head { background:linear-gradient(105deg,#006d70,#009c8c); color:white; padding:18px 22px; border-radius:10px 10px 0 0; margin:-1rem -1rem 1rem; }
.metric { background:#f7f9fc; border:1px solid #e7ebf1; border-radius:9px; padding:12px; text-align:center; }
.metric-label { font-size:12px; color:#52617a; font-weight:600; }
.metric-value { font-size:27px; font-weight:800; margin:5px 0; }
.pill { display:inline-block; padding:5px 10px; border-radius:7px; font-size:12px; font-weight:700; white-space:nowrap; }
.care {background:#fde1e8;color:#c51b45}.arch {background:#dcedfb;color:#006fbd}.pet {background:#dcf6e5;color:#087e3e}.supply {background:#eee4ff;color:#5e24c4}.fulfillment {background:#fff0c2;color:#9a5600}
.critical {background:#ffdce3;color:#c80c31}.high {background:#fce2e8;color:#b71e3d}.medium {background:#fff0c4;color:#995000}.low {background:#dcf7e5;color:#087b39}
.inprogress,.open,.completed {background:#e0efff;color:#075bc5}.pending,.closed {background:#e9edf2;color:#4b5b70}.resolved {background:#dcf7e5;color:#087b39}
.alertbox { border:1px solid #f3cb68; background:#fff5d9; border-radius:8px; padding:12px; color:#9b5300; }
.info-box { background:#e7f3ff; color:#145ba4; border-radius:8px; padding:10px 12px; font-size:13px; }
.small-muted { color:#617087; font-size:12px; }
div[data-testid="stDataFrame"] { border:1px solid #e0e5ec; border-radius:8px; }
.stButton button { border-radius:8px; font-weight:600; min-height:38px; }
div[data-testid="stForm"] { border:0; }
hr { margin:.5rem 0; border-color:#e5e9ef; }
@media(max-width:900px) { .topbar{padding:10px;gap:8px}.hpe-box{width:44px;height:20px}.hpe-mark{font-size:20px}.brand-title{font-size:23px}.brand-sub{font-size:11px}.top-search{display:none}.station-icon{width:48px;height:48px;flex-basis:48px}.station-count{font-size:29px}.station-main{padding:10px;gap:8px} }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def db_connect():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    with db_connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS cases (
            id TEXT PRIMARY KEY, case_number TEXT UNIQUE, subject TEXT, account TEXT, station TEXT,
            assignee TEXT, priority TEXT, status TEXT, created_at TEXT, updated_at TEXT,
            closed_at TEXT, description TEXT, vendor TEXT, department TEXT, issue_category TEXT,
            action_plan TEXT, resolution TEXT, source TEXT, total_elapsed_seconds INTEGER DEFAULT 0,
            checklist TEXT DEFAULT '[]', station_history TEXT DEFAULT '[]', case_history TEXT DEFAULT '[]',
            collaboration TEXT DEFAULT '[]', attachments TEXT DEFAULT '[]', is_simulated INTEGER DEFAULT 0
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
        con.execute("""CREATE TABLE IF NOT EXISTS alerts (id TEXT PRIMARY KEY, name TEXT, trigger_event TEXT,
            threshold INTEGER, color TEXT, icon TEXT, audio_name TEXT, enabled INTEGER, description TEXT,
            stations TEXT, in_app INTEGER, desktop INTEGER)""")
        count = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        if count == 0:
            seed_cases(con)
        if con.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0:
            defaults = {
                "sla": SLA_DEFAULTS, "notifications": {"New Case Assignment": True, "SLA Warning (Amber)": True,
                "SLA Breach (Red)": True, "Case Status Update": True, "Case Transfer": False,
                "Collaboration Messages": False, "Daily Summary": False},
                "preferences": {"default_view":"Active Cases","cases_per_page":"25","timezone":"Asia/Manila",
                "date_format":"MMM DD, YYYY","time_format":"12 Hour (AM/PM)","theme":"Light (Default)",
                "table_density":"Compact","font_size":"Medium (Default)","audio_alerts":True,"case_notifications":True},
            }
            for k, v in defaults.items():
                con.execute("INSERT INTO settings(key,value) VALUES(?,?)", (k, json.dumps(v)))
        if con.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 0:
            seed_alerts(con)


def seed_cases(con):
    samples = [
        ("CAR-2026-0001","Store network outage","H&M","CARE","Maria Santos","CRITICAL","In Progress","Network connectivity","Aruba Networks","Global Retail"),
        ("ARC-2026-0015","Validation request","Global Retail","ARCH","James Li","HIGH","Open","Validation","HPE","Global Retail"),
        ("PET-2026-0078","Access configuration","TechCorp","PET","Ravi Patel","MEDIUM","In Progress","Access","HPE","Technology"),
        ("SC-2026-0104","Shipment delay","Acme Ltd","SUPPLY CHAIN","Ana Rodriguez","LOW","Pending Internal","Shipment","Third-party","Logistics"),
        ("FUL-2026-0029","Onsite installation","Metro Partners","FULFILLMENT","Daniel Kim","MEDIUM","In Progress","Installation","Third-party","Field Services"),
        ("CAR-2026-0008","Hardware not detected","RetailCo","CARE","Lisa Chen","HIGH","Open","Hardware","HPE","Retail"),
        ("ARC-2026-0019","Document retrieval","Summit Group","ARCH","Mark Johnson","MEDIUM","In Progress","Documentation","HPE","Enterprise"),
        ("PET-2026-0081","Platform access issue","GreenField","PET","Sophie Tan","LOW","Pending Customer","Access","HPE","Technology"),
        ("SC-2026-0112","Tracking information","Blue Ocean","SUPPLY CHAIN","Carlos Mendez","MEDIUM","Open","Tracking","Third-party","Logistics"),
        ("FUL-2026-0034","Site access request","Prime Retail","FULFILLMENT","Emma Wilson","HIGH","In Progress","Site access","Third-party","Field Services"),
    ]
    base = datetime.now() - timedelta(minutes=12)
    for i, row in enumerate(samples):
        cn, subject, account, station, assignee, priority, status, issue, vendor, dept = row
        created = (base - timedelta(minutes=i*13)).isoformat(timespec="seconds")
        checklist = [{"text": t, "done": i < 4} for t in [
            "Confirm the product, model and serial number.",
            "Capture the exact alert, error message or customer symptom.",
            "Complete applicable remote/basic troubleshooting checks.",
            "Verify support, entitlement or contract context.",
            "Record customer contact, site and required reference information.",
            "Document the assessment and recommended next action."]]
        history = [{"at":created,"action":"Case Created","status":status,"by":"Excel Import","details":"Case created from imported operational data."}]
        con.execute("""INSERT INTO cases(id,case_number,subject,account,station,assignee,priority,status,created_at,updated_at,
            description,vendor,department,issue_category,action_plan,source,total_elapsed_seconds,checklist,station_history,case_history,collaboration,attachments)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()),cn,subject,account,station,assignee,priority,status,created,created,
             f"Customer reported {subject.lower()}. Investigate, document findings and coordinate the next action.",vendor,dept,issue,
             "Investigate the issue, validate relevant logs and coordinate with the responsible team.","Sample starter data",0,
             json.dumps(checklist),json.dumps([{"station":station,"entered_at":created,"exited_at":"","duration_seconds":0}]),
             json.dumps(history),json.dumps([]),json.dumps([])))


def seed_alerts(con):
    rows = [
        ("SLA Warning (60%)","SLA at Percentage",60,"Amber","Warning Triangle","warning.mp3",1,"Triggered when a case reaches 60% of the station SLA time."),
        ("SLA Breach (80%)","SLA at Percentage",80,"Red","Exclamation Circle","breach.mp3",1,"Triggered when a case reaches 80% of the station SLA time."),
        ("New Case Assignment","New case assigned",0,"Blue","Bell","newcase.mp3",1,"A case was assigned to a team member."),
        ("High Priority Account","High priority account",0,"Purple","Star","highpriority.mp3",1,"A high-priority account case was created."),
        ("Case Transfer","Case transferred",0,"Green","Transfer","transfer.mp3",1,"A case was transferred between stations."),
        ("Collaboration Request","New collaboration message",0,"Blue","Users","collaboration.mp3",1,"A new collaboration message was added."),
        ("Case Status Update","Status changed",0,"Grey","Clipboard","status.mp3",1,"A case status changed."),
        ("Case Due Soon","Due within 15 minutes",0,"Amber","Clock","duesoon.mp3",1,"A case is due soon."),
        ("Simulation Alert","Simulation triggered",0,"Purple","Flask","simulation.mp3",1,"A simulation was triggered."),
        ("System Alert","System event/error",0,"Red","Settings","system.mp3",1,"A system event or error occurred."),
    ]
    for name, trig, threshold, color, icon, audio, enabled, desc in rows:
        con.execute("INSERT INTO alerts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()),name,trig,threshold,color,icon,audio,enabled,desc,json.dumps(["All Stations"]),1,1))


def get_setting(key, fallback=None):
    with db_connect() as con:
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else fallback


def save_setting(key, value):
    with db_connect() as con:
        con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value)))


def all_cases():
    with db_connect() as con:
        df = pd.read_sql_query("SELECT * FROM cases ORDER BY created_at DESC", con)
    if df.empty:
        return df
    for col in ["checklist","station_history","case_history","collaboration","attachments"]:
        df[col] = df[col].apply(lambda x: json.loads(x or "[]"))
    return df


def update_case(case_id, **fields):
    allowed = {"subject","account","station","assignee","priority","status","updated_at","closed_at","description",
               "vendor","department","issue_category","action_plan","resolution","source","total_elapsed_seconds",
               "checklist","station_history","case_history","collaboration","attachments"}
    values = {}
    for k, v in fields.items():
        if k in allowed:
            if k in {"checklist","station_history","case_history","collaboration","attachments"}:
                v = json.dumps(v)
            values[k] = v
    if not values:
        return
    values["updated_at"] = now_iso()
    sql = ", ".join(f"{k}=?" for k in values)
    with db_connect() as con:
        con.execute(f"UPDATE cases SET {sql} WHERE id=?", (*values.values(), case_id))


def add_history(case, action, details, by="Current User"):
    hist = case["case_history"]
    hist.insert(0, {"at": now_iso(), "action": action, "status": case["status"], "by": by, "details": details})
    update_case(case["id"], case_history=hist)


def format_duration(seconds):
    seconds = max(0, int(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def current_station_seconds(case):
    history = case["station_history"] or []
    if not history:
        return 0
    last = history[-1]
    entered = last.get("entered_at")
    try:
        return max(0, int((datetime.now() - datetime.fromisoformat(entered)).total_seconds()))
    except Exception:
        return 0


def case_elapsed(case):
    try:
        created = datetime.fromisoformat(case["created_at"])
        return int((datetime.now() - created).total_seconds())
    except Exception:
        return int(case.get("total_elapsed_seconds", 0) or 0)


def case_closed(case):
    return str(case.get("status","")).upper() in {"CLOSED","RESOLVED","COMPLETED"}


def station_badge(station):
    return f'<span class="pill {STATION_CLASS.get(station,"care")}">{station}</span>'


def priority_badge(priority):
    return f'<span class="pill {PRIORITY_COLORS.get(str(priority).upper(),"medium")}">{priority}</span>'


def status_badge(status):
    return f'<span class="pill {STATUS_COLORS.get(str(status).upper(),"pending")}">{status}</span>'


def header():
    st.markdown("""
    <div class="topbar">
      <div class="hpe-mark"><span class="hpe-box"></span><span>HPE</span></div>
      <div class="brand-divider"></div>
      <div><div class="brand-title">OVR-VW</div><div class="brand-sub">Operations Visibility &amp; Response Workspace</div></div>
      <div class="top-spacer"></div>
      <div class="top-search">⌕ &nbsp; Search cases by number, subject, account, assignee...</div>
      <div style="font-size:34px;color:white;padding-left:8px">⚙</div>
    </div>
    """, unsafe_allow_html=True)


def station_cards(df, closed=False):
    cols = st.columns(5, gap="small")
    for i, station in enumerate(STATIONS):
        count = int((df["station"] == station).sum()) if not df.empty else 0
        tint = {"CARE":"#fde8ed","ARCH":"#e5f3fc","PET":"#e8f8ed","SUPPLY CHAIN":"#f1e9ff","FULFILLMENT":"#fff5d7"}[station]
        icon = {"CARE":"♧","ARCH":"▤","PET":"⚙","SUPPLY CHAIN":"♧","FULFILLMENT":"⚒"}[station]
        with cols[i]:
            st.markdown(f"""
            <div class="station-card" style="--station:{STATION_COLORS[station]};--tint:{tint}">
              <div class="station-main"><div class="station-icon">{icon}</div><div>
                <div class="station-name">{station}</div><div class="station-count">{count}</div>
                <div class="station-label">{'Closed Cases' if closed else 'Active Cases'}</div>
              </div><div style="font-size:26px;margin-left:auto">›</div></div>
              <div class="station-sla">◷ &nbsp; SLA {SLA_DEFAULTS[station]} minutes</div>
            </div>""", unsafe_allow_html=True)


def render_case_table(df, closed=False):
    if df.empty:
        st.info("No cases match the selected filters.")
        return
    view = df.copy()
    search = st.text_input("Search closed cases..." if closed else "Search active cases...", key="closed_search" if closed else "active_search", label_visibility="collapsed", placeholder="Search cases by number, subject, account, assignee...")
    if search:
        mask = view[["case_number","subject","account","assignee","station"]].fillna("").astype(str).apply(lambda col: col.str.contains(search, case=False)).any(axis=1)
        view = view[mask]
    c1,c2,c3 = st.columns([1.2,1,1])
    station_filter = c1.selectbox("Station", ["All Stations"]+STATIONS, key="closed_station" if closed else "active_station")
    if station_filter != "All Stations":
        view = view[view.station == station_filter]
    if closed:
        status_filter = c2.selectbox("Status", ["All Statuses","Resolved","Completed","Closed"], key="closed_status")
        if status_filter != "All Statuses":
            view = view[view.status.str.upper() == status_filter.upper()]
        date_filter = c3.selectbox("Closed date", ["All Dates","Last 7 days","Last 30 days"], key="closed_date")
        if date_filter != "All Dates" and "closed_at" in view:
            cutoff = datetime.now() - timedelta(days=7 if date_filter=="Last 7 days" else 30)
            view = view[view.closed_at.fillna("").apply(lambda x: bool(x) and datetime.fromisoformat(x) >= cutoff)]
    else:
        c2.markdown(f"<div class='small-muted' style='padding-top:12px'>Last updated<br>{datetime.now().strftime('%b %d, %Y %I:%M:%S %p')}</div>", unsafe_allow_html=True)
        c3.caption("Durations update on rerun")
    cols = ["case_number","subject","account","station","assignee","priority","status",
            "closed_at" if closed else "duration","total_duration","actions"]
    rows = []
    for _, case in view.iterrows():
        station = case["station"]
        dur = format_duration(case_elapsed(case) if closed else current_station_seconds(case))
        rows.append({
            "Case Number":case["case_number"],"Subject":case["subject"],"Account":case["account"],
            "Station":station,"Assignee":case["assignee"],"Priority":case["priority"],"Status":case["status"],
            "Closed Date": (case.get("closed_at") or "")[:16].replace("T"," ") if closed else "",
            "Duration":dur,"Total Duration":format_duration(case_elapsed(case)),
            "Actions": "View"
        })
    display = pd.DataFrame(rows)
    st.dataframe(display, use_container_width=True, hide_index=True, height=min(540, 38 + 42*len(display)),
                 column_config={
                     "Case Number":st.column_config.TextColumn(width="medium"),
                     "Subject":st.column_config.TextColumn(width="large"),
                     "Account":st.column_config.TextColumn(width="medium"),
                     "Station":st.column_config.TextColumn(width="medium"),
                     "Assignee":st.column_config.TextColumn(width="medium"),
                 })
    choices = [f'{r["case_number"]} — {r["subject"]}' for _,r in view.iterrows()]
    if choices:
        selected = st.selectbox("Open case details", ["Select a case..."]+choices, key="select_closed_case" if closed else "select_active_case", label_visibility="collapsed")
        if selected != "Select a case...":
            if st.button("View selected case", type="primary", key="view_closed" if closed else "view_active"):
                st.session_state.open_case_id = view.iloc[choices.index(selected)]["id"]
                st.rerun()


def render_dashboard():
    all_df = all_cases()
    active = all_df[~all_df.status.fillna("").str.upper().isin(["CLOSED","RESOLVED","COMPLETED"])]
    closed = all_df[all_df.status.fillna("").str.upper().isin(["CLOSED","RESOLVED","COMPLETED"])]
    active_tab, closed_tab = st.tabs(["Active Cases\nCurrent operational queue", "Closed Cases\nResolved case history"])
    with active_tab:
        station_cards(active, False)
        st.markdown("<div style='height:10px'></div><div class='panel-title'>Active Cases</div><div class='panel-subtitle'>Live operational cases across all stations</div>", unsafe_allow_html=True)
        render_case_table(active, False)
    with closed_tab:
        station_cards(closed, True)
        st.markdown("<div style='height:10px'></div><div class='panel-title'>Closed Cases</div><div class='panel-subtitle'>Resolved, completed and closed cases</div>", unsafe_allow_html=True)
        render_case_table(closed, True)


def render_case_detail(case_id):
    df = all_cases()
    match = df[df.id == case_id]
    if match.empty:
        st.session_state.open_case_id = None
        st.warning("Case no longer exists.")
        return
    case = match.iloc[0].to_dict()
    st.markdown(f"<div class='case-modal-head'><h2 style='margin:0;color:white'>Case Details</h2><div>View and manage case information, actions, knowledge base and collaboration</div></div>", unsafe_allow_html=True)
    top1,top2,top3,top4,top5 = st.columns([1.2,1.4,.7,1,1])
    top1.markdown(f"**Case Number**<br><span style='font-size:20px;font-weight:800'>{case['case_number']}</span>", unsafe_allow_html=True)
    top2.markdown(f"**Subject**<br><b>{case['subject']}</b>", unsafe_allow_html=True)
    top3.markdown(f"**Priority**<br>{priority_badge(case['priority'])}", unsafe_allow_html=True)
    with top4:
        new_status = st.selectbox("Status", ["Open","In Progress","Pending Internal","Pending Customer","Waiting","Resolved","Completed","Closed"], index=["Open","In Progress","Pending Internal","Pending Customer","Waiting","Resolved","Completed","Closed"].index(case["status"]) if case["status"] in ["Open","In Progress","Pending Internal","Pending Customer","Waiting","Resolved","Completed","Closed"] else 1, key=f"status_{case_id}")
        if new_status != case["status"]:
            update_case(case_id, status=new_status)
            add_history(case, "Status Updated", f"Status changed from {case['status']} to {new_status}.")
            st.rerun()
    with top5:
        new_station = st.selectbox("Current Station", STATIONS, index=STATIONS.index(case["station"]), key=f"station_{case_id}")
        if new_station != case["station"]:
            history = case["station_history"]
            if history:
                history[-1]["exited_at"] = now_iso()
                history[-1]["duration_seconds"] = current_station_seconds(case)
            history.append({"station":new_station,"entered_at":now_iso(),"exited_at":"","duration_seconds":0})
            update_case(case_id, station=new_station, station_history=history)
            add_history(case, "Station Changed", f"Station changed to {new_station}.")
            st.rerun()
    tabs = st.tabs(["Case Information","Case Actions","Knowledge Base","Collaboration","Attachments"])
    with tabs[0]:
        left,right = st.columns([.9,1.6])
        with left:
            st.markdown("### Case Overview")
            info = {"Case Number":case["case_number"],"Subject":case["subject"],"Account":case["account"],"Vendor":case["vendor"],
                    "Issue":case["issue_category"],"Description":case["description"],"Current Station":case["station"],
                    "Status":case["status"],"Priority":case["priority"],"Assigned To":case["assignee"],"Department":case["department"],
                    "Created Date":case["created_at"],"Last Updated":case["updated_at"],"Source":case["source"]}
            st.dataframe(pd.DataFrame([{"Field":k,"Value":v} for k,v in info.items()]), hide_index=True, use_container_width=True, height=440)
        with right:
            st.markdown("### Timing & SLA")
            elapsed = current_station_seconds(case)
            sla = int(get_setting("sla",SLA_DEFAULTS).get(case["station"], SLA_DEFAULTS[case["station"]]))*60
            remaining = sla-elapsed
            m1,m2,m3 = st.columns(3)
            m1.metric("Station Duration",format_duration(elapsed))
            m2.metric("Time Remaining",format_duration(max(0,remaining)))
            m3.metric("Total Elapsed Time",format_duration(case_elapsed(case)))
            if remaining <= 0:
                st.error("SLA Breached — this case has exceeded its station SLA.")
            elif remaining <= sla*.4:
                st.warning(f"Approaching SLA breach — {format_duration(remaining)} remaining.")
            else:
                st.success("Within station SLA.")
            st.markdown("### Station Journey")
            st.write(" → ".join([x["station"] for x in case["station_history"]]))
            st.markdown("### Station Duration & SLA Status")
            hist = case["station_history"]
            st.dataframe(pd.DataFrame([{"Station":x["station"],"Entered At":x.get("entered_at",""),"Exited At":x.get("exited_at",""),
                "Duration":format_duration(x.get("duration_seconds",0) if x.get("exited_at") else current_station_seconds(case)),
                "SLA Limit":f"{SLA_DEFAULTS[x['station']]} minutes","SLA Status":"Completed" if x.get("exited_at") else ("Breached" if current_station_seconds(case)>SLA_DEFAULTS[x["station"]]*60 else "In Progress")} for x in hist]), hide_index=True, use_container_width=True)
    with tabs[1]:
        left,right = st.columns([1.15,1])
        with left:
            st.markdown(f"### Station Checklist ({case['station']})")
            checklist = case["checklist"]
            done = sum(1 for x in checklist if x.get("done"))
            st.progress(done/max(1,len(checklist)), text=f"{done} / {len(checklist)} completed")
            changed = False
            for i,item in enumerate(checklist):
                v = st.checkbox(item["text"], value=item.get("done",False), key=f"check_{case_id}_{i}")
                if v != item.get("done",False):
                    checklist[i]["done"] = v; changed=True
            if changed:
                update_case(case_id, checklist=checklist)
                add_history(case, "Checklist Updated", "Checklist items updated.")
                st.rerun()
            st.info("Complete required checklist items before transferring the case.")
        with right:
            st.markdown("### Case Actions")
            with st.form(f"action_form_{case_id}"):
                assignee = st.selectbox("Current Assignee",["Unassigned","Maria Santos","James Li","Ravi Patel","Ana Rodriguez","Daniel Kim","Lisa Chen","Mark Johnson","Sophie Tan","Carlos Mendez","Emma Wilson"], index=0 if case["assignee"] not in ["Maria Santos","James Li","Ravi Patel","Ana Rodriguez","Daniel Kim","Lisa Chen","Mark Johnson","Sophie Tan","Carlos Mendez","Emma Wilson"] else ["Maria Santos","James Li","Ravi Patel","Ana Rodriguez","Daniel Kim","Lisa Chen","Mark Johnson","Sophie Tan","Carlos Mendez","Emma Wilson"].index(case["assignee"]))
                priority = st.selectbox("Priority",["Critical","High","Medium","Low"],index=["Critical","High","Medium","Low"].index(case["priority"].title()) if case["priority"].title() in ["Critical","High","Medium","Low"] else 2)
                department = st.text_input("Department",case["department"] or "")
                account = st.text_input("Account",case["account"] or "")
                vendor = st.text_input("Vendor",case["vendor"] or "")
                issue = st.text_input("Issue Category",case["issue_category"] or "")
                action_plan = st.text_area("Action Plan",case["action_plan"] or "",max_chars=500)
                save = st.form_submit_button("Save Changes",type="primary",use_container_width=True)
            if save:
                update_case(case_id,assignee=assignee,priority=priority.upper(),department=department,account=account,vendor=vendor,issue_category=issue,action_plan=action_plan)
                add_history(case,"Case Actions Updated","Assignee, priority or case details updated.")
                st.success("Changes saved.")
                st.rerun()
            st.markdown("### Transfer Station")
            destination = st.selectbox("Select Destination Station",[x for x in STATIONS if x!=case["station"]],key=f"dest_{case_id}")
            if not all(x.get("done") for x in case["checklist"]):
                st.warning("Complete all checklist items before transferring the case.")
            if st.button(f"Transfer to {destination}",disabled=not all(x.get("done") for x in case["checklist"]),key=f"transfer_{case_id}",use_container_width=True):
                hist=case["station_history"]
                if hist:
                    hist[-1]["exited_at"]=now_iso(); hist[-1]["duration_seconds"]=current_station_seconds(case)
                hist.append({"station":destination,"entered_at":now_iso(),"exited_at":"","duration_seconds":0})
                update_case(case_id,station=destination,station_history=hist)
                add_history(case,"Case Transferred",f"Case transferred to {destination}.")
                st.success("Case transferred.")
                st.rerun()
            st.markdown("### Close / Resolve Case")
            resolution = st.text_area("Resolution Summary",case["resolution"] or "",key=f"resolution_{case_id}")
            b1,b2=st.columns(2)
            if b1.button("Resolve Case",key=f"resolve_{case_id}",use_container_width=True):
                update_case(case_id,status="Resolved",resolution=resolution,closed_at=now_iso())
                add_history(case,"Case Resolved",resolution or "Case resolved.")
                st.rerun()
            if b2.button("Close Case",key=f"close_{case_id}",use_container_width=True):
                update_case(case_id,status="Closed",resolution=resolution,closed_at=now_iso())
                add_history(case,"Case Closed",resolution or "Case closed.")
                st.rerun()
        st.markdown("### Case History")
        st.dataframe(pd.DataFrame([{"Date & Time":x.get("at",""),"Action":x.get("action",""),"Status":x.get("status",""),"Performed By":x.get("by",""),"Details":x.get("details","")} for x in case["case_history"]]),hide_index=True,use_container_width=True)
    with tabs[2]:
        left,right=st.columns([1,1.1])
        with left:
            st.markdown("### Search Knowledge Base")
            query=st.text_input("Search solutions, troubleshooting guides and SOPs",value=case["issue_category"] or case["subject"],key=f"kb_{case_id}")
            category=st.selectbox("Category",["All Categories","Network","Hardware","Access","Process","Escalation"])
            if st.button("Search",key=f"kbsearch_{case_id}",type="primary"):
                st.session_state[f"kbquery_{case_id}"]=query
            q=st.session_state.get(f"kbquery_{case_id}",query).lower()
            articles=[
                ("Network Outage – Store Connectivity Troubleshooting","Step-by-step troubleshooting for store network outages, switch validation, WAN checks and escalation criteria.","Network • SOP • Troubleshooting"),
                ("Aruba Switch – No Connectivity","Common causes and resolution steps for Aruba switches with no network connectivity.","Aruba • Network • Hardware"),
                ("Store POS System – Network Access Issues","Troubleshooting steps for POS network access failures, including DNS, DHCP and VLAN verification.","POS • Network • Store"),
                ("Escalation Guide – Network Infrastructure","When to escalate network issues and what information is required.","Escalation • Process"),
            ]
            for title,desc,tags in articles:
                if not q or any(w in (title+" "+desc+" "+tags).lower() for w in q.split()):
                    with st.container(border=True):
                        st.markdown(f"**{title}**")
                        st.caption(desc)
                        st.caption(tags)
                        if st.button("View article",key=f"article_{case_id}_{title}"):
                            st.session_state[f"article_{case_id}"]=title
        with right:
            title=st.session_state.get(f"article_{case_id}","Network Outage – Store Connectivity Troubleshooting")
            st.markdown(f"### Article Details\n**{title}**")
            st.info("Overview: Validate local connectivity, switch checks, WAN connectivity and escalation criteria.")
            st.markdown("**Troubleshooting Steps**\n\n1. Verify local device connectivity.\n2. Check physical connections and switch port status.\n3. Validate VLAN configuration and port assignment.\n4. Check switch interface errors.\n5. Test WAN connectivity and DNS resolution.\n6. Collect logs and escalate to the relevant support team.")
            st.markdown("**Related Articles**\n\n- Aruba Switch – No Connectivity\n- Store POS System – Network Access Issues\n- Escalation Guide – Network Infrastructure")
    with tabs[3]:
        left,right=st.columns([1.6,.8])
        with left:
            st.markdown("### Collaboration")
            messages=case["collaboration"]
            if not messages:
                st.caption("No collaboration messages yet.")
            for msg in sorted(messages,key=lambda x:x.get("at",""),reverse=True):
                with st.container(border=True):
                    st.markdown(f"**{msg.get('by','Team member')}** · {msg.get('at','')}")
                    st.write(msg.get("message",""))
                    st.caption(msg.get("team","Operations"))
            with st.form(f"collab_form_{case_id}"):
                message=st.text_area("Type a message...",key=f"message_{case_id}")
                team=st.selectbox("Team",["Operations","Network Team","Vendor","Account Team","System"])
                send=st.form_submit_button("Send",type="primary")
            if send and message.strip():
                messages.append({"at":now_iso(),"by":"Current User","message":message.strip(),"team":team})
                update_case(case_id,collaboration=messages)
                add_history(case,"Collaboration Message",message[:120])
                st.rerun()
        with right:
            st.markdown("### Participants")
            st.write("🟢 Maria Santos — Operations")
            st.write("🟢 James Li — Network Team")
            st.write("🟠 Ravi Patel — Vendor")
            st.write("⚪ Sarah Davis — Account Team")
            st.markdown("### Recent Activity")
            for h in case["case_history"][:5]:
                st.caption(f"• {h.get('action')} — {h.get('at','')}")
    with tabs[4]:
        st.markdown("### Attachments")
        files=case["attachments"]
        upload=st.file_uploader("Upload file",key=f"upload_{case_id}",accept_multiple_files=True)
        if upload:
            for f in upload:
                if not any(x.get("name")==f.name for x in files):
                    files.append({"name":f.name,"type":f.type or "file","size":len(f.getvalue()),"uploaded_by":"Current User","at":now_iso(),"description":""})
            update_case(case_id,attachments=files)
            st.success("Attachment metadata saved. Configure object storage for durable file contents.")
            st.rerun()
        if files:
            st.dataframe(pd.DataFrame([{"File Name":f.get("name"),"Type":f.get("type"),"Size":f"{f.get('size',0)/1024:.1f} KB","Uploaded By":f.get("uploaded_by"),"Date Uploaded":f.get("at")} for f in files]),hide_index=True,use_container_width=True)
            selected=st.selectbox("Select attachment", [f.get("name") for f in files],key=f"att_select_{case_id}")
            desc=st.text_input("File Description",next((f.get("description","") for f in files if f.get("name")==selected),""))
            if st.button("Save description",key=f"att_desc_{case_id}"):
                for f in files:
                    if f.get("name")==selected:f["description"]=desc
                update_case(case_id,attachments=files);st.success("Description saved.")
        else:
            st.caption("No files attached to this case.")
    st.divider()
    if st.button("✕ Close Case Details",key=f"close_detail_{case_id}"):
        st.session_state.open_case_id=None
        st.rerun()


def render_general_settings():
    st.markdown("### System Information")
    a,b,c=st.columns(3)
    with a:
        st.markdown("<div class='panel'><b>Application Name</b><br>OVR-VW<br><br><b>Version</b><br>1.0.0<br><br><b>Environment</b><br>Production / Local<br><br><b>Database</b><br>SQLite (MongoDB optional)</div>",unsafe_allow_html=True)
    with b:
        st.markdown("### Notification Settings")
        notifications=get_setting("notifications",{})
        for key,desc in [("New Case Assignment","Notify when a case is assigned to you"),("SLA Warning (Amber)","Notify when a case is approaching SLA threshold (60%)"),("SLA Breach (Red)","Notify when a case has breached SLA threshold (80%)"),("Case Status Update","Notify when case status is changed"),("Case Transfer","Notify when a case is transferred"),("Collaboration Messages","Notify for new collaboration messages"),("Daily Summary","Receive a daily case summary")]:
            notifications[key]=st.checkbox(key+" — "+desc,value=notifications.get(key,False),key="notify_"+key)
        if st.button("Save Notification Settings",type="primary"):
            save_setting("notifications",notifications);st.success("Notification preferences saved.")
    with c:
        st.markdown("### SLA Settings")
        sla=get_setting("sla",SLA_DEFAULTS).copy()
        with st.form("sla_form"):
            for station in STATIONS:
                sla[station]=st.number_input(f"{station} SLA (minutes)",min_value=1,max_value=1440,value=int(sla.get(station,SLA_DEFAULTS[station])),key="sla_"+station)
            saved=st.form_submit_button("Save SLA Settings",type="primary")
        if saved:
            save_setting("sla",sla);st.success("SLA settings saved.")
        st.markdown("### Preferences")
        prefs=get_setting("preferences",{})
        with st.form("pref_form"):
            prefs["default_view"]=st.selectbox("Default View",["Active Cases","Closed Cases"],index=["Active Cases","Closed Cases"].index(prefs.get("default_view","Active Cases")))
            prefs["cases_per_page"]=st.selectbox("Cases Per Page",["10","25","50","100"],index=["10","25","50","100"].index(str(prefs.get("cases_per_page","25"))))
            prefs["timezone"]=st.selectbox("Time Zone",["Asia/Manila","UTC","America/New_York","Europe/London"],index=["Asia/Manila","UTC","America/New_York","Europe/London"].index(prefs.get("timezone","Asia/Manila")))
            prefs["theme"]=st.selectbox("Theme",["Light (Default)","Dark"],index=["Light (Default)","Dark"].index(prefs.get("theme","Light (Default)")))
            prefs["table_density"]=st.selectbox("Table Density",["Compact","Comfortable"],index=["Compact","Comfortable"].index(prefs.get("table_density","Compact")))
            prefs["audio_alerts"]=st.checkbox("Enable Audio Alerts",value=prefs.get("audio_alerts",True))
            prefs["case_notifications"]=st.checkbox("Show Case Notifications",value=prefs.get("case_notifications",True))
            ps=st.form_submit_button("Save Preferences")
        if ps:
            save_setting("preferences",prefs);st.success("Preferences saved.")
    st.divider()
    st.markdown("### System Actions")
    x,y=st.columns(2)
    with x:
        st.markdown("**Import Data from Excel**")
        st.caption("Upload an Excel or CSV file to create or update cases.")
        if st.button("Open Data Import",use_container_width=True):
            st.session_state.settings_tab="Data Import";st.rerun()
    with y:
        st.markdown("**Export Data**")
        st.caption("Export cases, collaboration history, case history and reference data.")
        if st.button("Open Export Data",use_container_width=True):
            st.session_state.settings_tab="Export Data";st.rerun()
    st.markdown("### Clear Data")
    st.warning("This permanently deletes selected local database records. Export a backup first.")
    with st.form("clear_form"):
        clear_cases=st.checkbox("Clear all cases")
        clear_alerts=st.checkbox("Clear alert rules")
        clear_settings=st.checkbox("Clear settings (will restore defaults)")
        confirm=st.checkbox("I understand this cannot be undone.")
        clear=st.form_submit_button("Clear Selected Data",type="primary")
    if clear:
        if not confirm or not (clear_cases or clear_alerts or clear_settings):
            st.error("Select at least one data category and confirm the action.")
        else:
            with db_connect() as con:
                if clear_cases: con.execute("DELETE FROM cases")
                if clear_alerts: con.execute("DELETE FROM alerts")
                if clear_settings: con.execute("DELETE FROM settings")
            if clear_settings: init_db()
            st.success("Selected data cleared.")
            st.rerun()


def render_alert_management():
    with db_connect() as con:
        alerts=pd.read_sql_query("SELECT * FROM alerts ORDER BY name",con)
    left,right=st.columns([1.05,1])
    with left:
        st.markdown("### Alert Rules")
        st.caption(f"Configure alerts for cases, stations and system events. ({len(alerts)})")
        if st.button("＋ Add Alert",type="primary"):
            with db_connect() as con:
                con.execute("INSERT INTO alerts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),"New Alert","System event",0,"Blue","Bell","",1,"New alert description",json.dumps(["All Stations"]),1,1))
            st.rerun()
        for _,a in alerts.iterrows():
            with st.container(border=True):
                col1,col2,col3=st.columns([3,.7,.7])
                col1.markdown(f"**{a['name']}**")
                col1.caption(f"{a['trigger_event']} · {a['color']} · {a['icon']} · {a['audio_name'] or 'No audio'}")
                enabled=col2.checkbox("Enabled",value=bool(a["enabled"]),key=f"alert_enabled_{a['id']}")
                if enabled != bool(a["enabled"]):
                    with db_connect() as con: con.execute("UPDATE alerts SET enabled=? WHERE id=?",(int(enabled),a["id"]))
                    st.rerun()
                if col3.button("Edit",key=f"edit_alert_{a['id']}"):
                    st.session_state.selected_alert=a["id"]
                if col3.button("Delete",key=f"delete_alert_{a['id']}"):
                    with db_connect() as con: con.execute("DELETE FROM alerts WHERE id=?",(a["id"],))
                    st.rerun()
    with right:
        selected=st.session_state.get("selected_alert")
        row=alerts[alerts.id==selected] if selected else alerts.head(1)
        if row.empty:
            st.info("Add or select an alert to edit.")
            return
        a=row.iloc[0]
        st.markdown("### Alert Details")
        with st.form("alert_edit_form"):
            name=st.text_input("Alert Name",a["name"])
            desc=st.text_area("Description",a["description"] or "")
            trigger=st.selectbox("Trigger Event",["SLA at Percentage","New case assigned","High priority account","Case transferred","New collaboration message","Status changed","Due within 15 minutes","Simulation triggered","System event/error"],index=["SLA at Percentage","New case assigned","High priority account","Case transferred","New collaboration message","Status changed","Due within 15 minutes","Simulation triggered","System event/error"].index(a["trigger_event"]) if a["trigger_event"] in ["SLA at Percentage","New case assigned","High priority account","Case transferred","New collaboration message","Status changed","Due within 15 minutes","Simulation triggered","System event/error"] else 0)
            t1,t2=st.columns(2)
            threshold=t1.number_input("Threshold (%)",0,100,int(a["threshold"] or 60))
            color=t2.selectbox("Alert Color",["Amber","Red","Blue","Purple","Green","Grey"],index=["Amber","Red","Blue","Purple","Green","Grey"].index(a["color"]) if a["color"] in ["Amber","Red","Blue","Purple","Green","Grey"] else 0)
            icon=st.selectbox("Icon",["Warning Triangle","Exclamation Circle","Bell","Star","Transfer","Users","Clipboard","Clock","Flask","Settings"],index=["Warning Triangle","Exclamation Circle","Bell","Star","Transfer","Users","Clipboard","Clock","Flask","Settings"].index(a["icon"]) if a["icon"] in ["Warning Triangle","Exclamation Circle","Bell","Star","Transfer","Users","Clipboard","Clock","Flask","Settings"] else 0)
            audio=st.file_uploader("Audio Notification (MP3/WAV)",type=["mp3","wav"],key="alert_audio")
            audio_name=audio.name if audio else (a["audio_name"] or "")
            stations=st.multiselect("Applies To",["All Stations"]+STATIONS,default=json.loads(a["stations"] or '["All Stations"]'))
            inapp=st.checkbox("Send In-App Notification",value=bool(a["in_app"]))
            desktop=st.checkbox("Show Desktop Notification",value=bool(a["desktop"]))
            save=st.form_submit_button("Save Changes",type="primary")
        if save:
            with db_connect() as con:
                con.execute("UPDATE alerts SET name=?,trigger_event=?,threshold=?,color=?,icon=?,audio_name=?,description=?,stations=?,in_app=?,desktop=? WHERE id=?",
                            (name,trigger,threshold,color,icon,audio_name,desc,json.dumps(stations),int(inapp),int(desktop),a["id"]))
            if audio:
                Path("uploaded_alert_audio").mkdir(exist_ok=True)
                Path("uploaded_alert_audio",audio.name).write_bytes(audio.getvalue())
            st.success("Alert configuration saved.")
            st.rerun()
        if st.button("▶ Send Test Alert"):
            st.session_state.test_alert={"name":name,"color":color,"icon":icon,"description":desc}
        if st.session_state.get("test_alert"):
            t=st.session_state.test_alert
            st.markdown(f"<div class='alertbox'><b>⚠ {t['name']}</b><br>{t['description']}</div>",unsafe_allow_html=True)


def render_import():
    """Excel import workspace matching the supplied OVR-VW reference."""
    st.markdown("### ☁ Import Data")
    st.caption("Upload an Excel file to create or update cases, stations and reference data.")
    left, right = st.columns([0.78, 1.82], gap="medium")
    with left:
        with st.container(border=True):
            st.markdown("#### ⇧ Import Data")
            st.caption("Upload an Excel file to create or update cases, stations and reference data.")
            uploaded = st.file_uploader("Browse File — .xlsx, .xls (maximum 10 MB)", type=["xlsx", "xls"], key="case_import")
            if uploaded and uploaded.size > 10 * 1024 * 1024:
                st.error("Maximum file size is 10 MB.")
                uploaded = None
        with st.container(border=True):
            st.markdown("#### ⚙ Import Options")
            import_mode = st.radio("Import behavior", ["Create new records only", "Update existing records", "Replace all records"],
                captions=["Skip records that already exist.", "Update matching records, create new if not found.", "Clear existing data and import new records."], key="import_mode")
            st.markdown("#### ▤ Data Type")
            import_cases = st.checkbox("Cases", value=True, help="Import new cases and update existing cases.", key="import_cases")
            st.caption("Import new cases and update existing cases.")
            import_stations = st.checkbox("Stations", value=True, key="import_stations")
            st.caption("Import station configuration.")
            import_reference = st.checkbox("Reference Data", value=True, key="import_reference")
            st.caption("Import accounts, vendors, departments, etc.")

    with right:
        if not uploaded:
            with st.container(border=True):
                st.markdown("#### 🔗 Field Mapping")
                st.caption("Map columns from your Excel file to system fields.")
                st.info("Upload an Excel workbook to configure field mapping and preview the data.")
                st.markdown("#### ▤ Data Preview")
                st.caption("The first 10 rows will appear here after upload.")
            return
        try:
            source_df = pd.read_excel(uploaded)
            if source_df.empty:
                st.warning("The selected workbook has no rows.")
                return
            system_fields = ["Ignore", "Case Number", "Subject", "Account", "Vendor", "Issue Category", "Priority", "Status", "Station", "Department", "Assigned To", "Description", "Action Plan", "Due Date"]
            normalized = {str(c).strip().lower().replace("_", " "): c for c in source_df.columns}
            aliases = {"case number":"case number", "case_number":"case number", "case id":"case number", "assigned to":"assigned to", "assignee":"assigned to", "current station":"station", "issue category":"issue category"}
            defaults = {}
            for c in source_df.columns:
                k = str(c).strip().lower().replace("_", " ")
                k = aliases.get(k, k)
                match = next((f for f in system_fields if f.lower() == k), "Ignore")
                defaults[str(c)] = match
            if st.button("↻ Auto Map", key="import_auto_map"):
                st.session_state["import_mapping"] = defaults
                st.rerun()
            a,b = st.columns([1,1])
            with a:
                st.markdown("#### 🔗 Field Mapping")
                st.caption("Map columns from your Excel file to system fields.")
            with b:
                template = pd.DataFrame(columns=["Case Number", "Subject", "Account", "Vendor", "Issue Category", "Priority", "Status", "Station", "Department", "Assigned To", "Description", "Action Plan"])
                tb = io.BytesIO()
                with pd.ExcelWriter(tb, engine="openpyxl") as writer: template.to_excel(writer, index=False, sheet_name="Cases")
                st.download_button("⇩ Download Template", tb.getvalue(), "ovr_vw_import_template.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="import_template")
            map_cols = st.columns([1,1,0.7,0.45])
            for col, title in zip(map_cols, ["Excel Column", "Maps To (System Field)", "Data Type", "Required"]):
                col.markdown(f"**{title}**")
            mapping = {}
            required_fields = {"Subject", "Account", "Issue Category", "Priority"}
            prior = st.session_state.get("import_mapping", defaults)
            for idx, colname in enumerate(source_df.columns):
                row = st.columns([1,1,0.7,0.45])
                row[0].write(str(colname))
                choices = system_fields
                initial = prior.get(str(colname), defaults.get(str(colname), "Ignore"))
                if initial not in choices: initial = "Ignore"
                target = row[1].selectbox("Map", choices, index=choices.index(initial), key=f"map_{idx}_{str(colname)}", label_visibility="collapsed")
                mapping[str(colname)] = target
                dtype = "Dropdown" if target in {"Priority", "Status", "Station", "Issue Category", "Department"} else ("User" if target == "Assigned To" else "Text")
                row[2].write(dtype)
                row[3].checkbox("Required", value=(target in required_fields), key=f"req_{idx}_{str(colname)}", label_visibility="collapsed")
            st.session_state["import_mapping"] = mapping
            st.divider()
            st.markdown("#### ▤ Data Preview")
            st.caption("Preview the first 10 rows from your file.")
            st.markdown(f"<div style='text-align:right'>Total Rows: <b style='color:#0868e8'>{len(source_df):,}</b></div>", unsafe_allow_html=True)
            st.dataframe(source_df.head(10), use_container_width=True, hide_index=True, height=235)
            if st.button("⇧ Import Data", type="primary", key="run_import", use_container_width=True):
                if not import_cases:
                    st.warning("Currently this import workflow processes case records. Select Cases to proceed.")
                    return
                reverse = {}
                for source_col, target in mapping.items():
                    if target != "Ignore": reverse[target] = source_col
                required_missing = [f for f in required_fields if f not in reverse]
                if required_missing:
                    st.error("Map the required fields before importing: " + ", ".join(sorted(required_missing)))
                    return
                def value(row, field, default=""):
                    source_col = reverse.get(field)
                    if not source_col or pd.isna(row[source_col]): return default
                    return str(row[source_col]).strip()
                if import_mode == "Replace all records":
                    with db_connect() as con: con.execute("DELETE FROM cases")
                imported = skipped = 0
                for _, r in source_df.iterrows():
                    number = value(r, "Case Number", f"OVR-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:5].upper()}")
                    station = value(r, "Station", "CARE").upper()
                    if station not in STATIONS: station = "CARE"
                    priority = value(r, "Priority", "MEDIUM").upper()
                    if priority not in PRIORITY_COLORS: priority = "MEDIUM"
                    status = value(r, "Status", "Open").title()
                    with db_connect() as con:
                        exists = con.execute("SELECT id FROM cases WHERE case_number=?", (number,)).fetchone()
                        if exists and import_mode == "Create new records only":
                            skipped += 1
                            continue
                        if exists:
                            con.execute("UPDATE cases SET subject=?,account=?,station=?,assignee=?,priority=?,status=?,vendor=?,department=?,issue_category=?,description=?,action_plan=?,updated_at=? WHERE case_number=?",
                                (value(r,"Subject"),value(r,"Account"),station,value(r,"Assigned To","Unassigned"),priority,status,value(r,"Vendor"),value(r,"Department"),value(r,"Issue Category"),value(r,"Description"),value(r,"Action Plan"),now_iso(),number))
                        else:
                            created = now_iso()
                            checklist = [{"text":x,"done":False} for x in ["Confirm product/model/serial number","Capture error message or symptom","Complete troubleshooting checks","Verify support entitlement","Record customer contact and reference","Document assessment and next action"]]
                            con.execute("""INSERT INTO cases(id,case_number,subject,account,station,assignee,priority,status,created_at,updated_at,description,vendor,department,issue_category,action_plan,source,checklist,station_history,case_history,collaboration,attachments)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (str(uuid.uuid4()),number,value(r,"Subject","Imported case"),value(r,"Account"),station,value(r,"Assigned To","Unassigned"),priority,status,created,created,value(r,"Description"),value(r,"Vendor"),value(r,"Department"),value(r,"Issue Category"),value(r,"Action Plan"),"Excel Import",json.dumps(checklist),json.dumps([{"station":station,"entered_at":created,"exited_at":"","duration_seconds":0}]),json.dumps([{"at":created,"action":"Case Created","status":status,"by":"Excel Import","details":"Case created from import."}]),"[]","[]"))
                        imported += 1
                st.success(f"Import complete. Created/updated: {imported}; skipped: {skipped}.")
                st.rerun()
        except Exception as e:
            st.error(f"Unable to read import file: {e}")


def render_export():
    """Configurable data export with filters, field selection, and XLSX/CSV/PDF/PPTX output."""
    st.markdown("### ▤ Export Data")
    st.caption("Download system data for reporting, analysis or backup.")
    df = all_cases().copy()
    if df.empty:
        st.info("No cases to export.")
        return
    # Normalize timestamps and filter options.
    for col in ["created_at", "updated_at", "closed_at"]:
        if col in df.columns: df[col] = pd.to_datetime(df[col], errors="coerce")
    active, left = st.columns([0.8, 1.9], gap="medium")
    with active:
        with st.container(border=True):
            st.markdown("#### 1. Select Data to Export")
            data_cases = st.checkbox("📄 Cases", value=True, key="export_cases")
            st.caption("Case details, status, timelines and history")
            data_collab = st.checkbox("▤ Collaboration Messages", value=True, key="export_collab")
            st.caption("Messages and attachments")
            data_attachments = st.checkbox("📎 Attachments", value=True, key="export_attachments")
            st.caption("File details and links")
            data_reference = st.checkbox("▤ Reference Data", value=False, key="export_reference")
            st.caption("Accounts, vendors, departments, etc.")
            data_stations = st.checkbox("▤ Stations", value=False, key="export_stations")
            st.caption("Station configuration and SLA settings")
            data_alerts = st.checkbox("♧ Alert Rules", value=False, key="export_alerts")
            st.caption("Configured alerts and notifications")
            data_logs = st.checkbox("▤ System Logs", value=False, key="export_logs")
            st.caption("System activity and audit logs")
            st.divider()
            st.markdown("#### 2. Export Format")
            export_format = st.radio("Format", ["Excel (.xlsx)", "CSV (.csv)", "PDF (.pdf)", "PowerPoint (.pptx)"], key="export_format", label_visibility="collapsed")
            open_after = st.checkbox("Open file after export", value=True, key="export_open_after")
    with left:
        with st.container(border=True):
            st.markdown("#### 3. Filter Options (Optional)")
            date_col1,date_col2,date_col3 = st.columns([0.7,1,1])
            with date_col1: date_range = st.selectbox("Date Range", ["All Dates", "Last 7 Days", "Last 30 Days", "This Month", "Custom Range"], index=2, key="export_date_range")
            min_date = df["created_at"].min().date() if "created_at" in df and df["created_at"].notna().any() else datetime.now().date()
            max_date = datetime.now().date()
            if date_range == "Custom Range":
                with date_col2: start_date = st.date_input("From", value=min_date, key="export_start")
                with date_col3: end_date = st.date_input("To", value=max_date, key="export_end")
            else:
                with date_col2: st.text_input("From", value=(datetime.now()-timedelta(days=30)).strftime("%b %d, %Y") if date_range=="Last 30 Days" else "—", disabled=True, key="export_from_display")
                with date_col3: st.text_input("To", value=datetime.now().strftime("%b %d, %Y"), disabled=True, key="export_to_display")
                end_date = max_date
                start_date = min_date
                if date_range == "Last 7 Days": start_date = (datetime.now()-timedelta(days=7)).date()
                elif date_range == "Last 30 Days": start_date = (datetime.now()-timedelta(days=30)).date()
                elif date_range == "This Month": start_date = datetime.now().replace(day=1).date()
            f1,f2,f3 = st.columns(3)
            with f1: station_filter = st.selectbox("Station", ["All Stations"]+STATIONS, key="export_station")
            with f2: priority_filter = st.selectbox("Priority", ["All Priorities"]+["CRITICAL","HIGH","MEDIUM","LOW"], key="export_priority")
            with f3: status_filter = st.selectbox("Status", ["All Statuses"]+sorted(df.status.dropna().astype(str).unique().tolist()), key="export_status")
            f4,f5,f6 = st.columns(3)
            with f4: account_filter = st.selectbox("Account", ["All Accounts"]+sorted(df.account.dropna().astype(str).unique().tolist()), key="export_account")
            with f5: vendor_filter = st.selectbox("Vendor", ["All Vendors"]+sorted(df.vendor.dropna().astype(str).unique().tolist()), key="export_vendor")
            with f6: assignee_filter = st.selectbox("Assignee", ["All Assignees"]+sorted(df.assignee.dropna().astype(str).unique().tolist()), key="export_assignee")
            include_archived = st.checkbox("Include deleted/archived records", value=False, key="export_archived")
        # Filter data
        filtered = df.copy()
        if "created_at" in filtered.columns:
            dates = filtered["created_at"].dt.date
            filtered = filtered[(dates >= start_date) & (dates <= end_date)]
        for col, val in [("station",station_filter),("priority",priority_filter),("status",status_filter),("account",account_filter),("vendor",vendor_filter),("assignee",assignee_filter)]:
            if val not in {"All Stations","All Priorities","All Statuses","All Accounts","All Vendors","All Assignees"}:
                filtered = filtered[filtered[col].fillna("").astype(str).str.upper()==str(val).upper()]
        with st.container(border=True):
            st.markdown("#### 4. Select Columns")
            excluded = {"checklist","station_history","case_history","collaboration","attachments"}
            candidates = [c for c in filtered.columns if c not in excluded]
            pretty = {c: c.replace("_", " ").title() for c in candidates}
            default_cols = [c for c in candidates if c in {"case_number","subject","account","vendor","issue_category","priority","status","station","assignee","created_at","closed_at","total_elapsed_seconds","updated_at"}]
            search_col = st.text_input("⌕ Search columns", key="export_search_columns", placeholder="Search columns...")
            select_all = st.checkbox("Select All", value=False, key="export_select_all")
            visible_cols = [c for c in candidates if search_col.lower() in pretty[c].lower()]
            chosen = []
            cols = st.columns(5)
            for i,c in enumerate(visible_cols):
                with cols[i%5]:
                    if st.checkbox(pretty[c], value=(select_all or c in default_cols), key=f"export_col_{c}"):
                        chosen.append(c)
            if not chosen: chosen = [c for c in default_cols if c in candidates]
            out_df = filtered[chosen].copy() if chosen else filtered.copy()
            st.markdown(f"#### 5. Preview Data <span style='float:right;font-size:13px'>Total Records: <b style='color:#0868e8'>{len(filtered):,}</b></span>", unsafe_allow_html=True)
            st.dataframe(out_df.head(10), use_container_width=True, hide_index=True, height=220)
            if export_format.startswith("Excel"):
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                    if data_cases: out_df.to_excel(writer, index=False, sheet_name="Cases")
                    if data_collab:
                        messages = [{"Case Number":r.get("case_number"), **m} for _,r in filtered.iterrows() for m in (r.get("collaboration") or [])]
                        pd.DataFrame(messages).to_excel(writer, index=False, sheet_name="Collaboration"[:31])
                    if data_attachments:
                        attachments = [{"Case Number":r.get("case_number"), **a} for _,r in filtered.iterrows() for a in (r.get("attachments") or [])]
                        pd.DataFrame(attachments).to_excel(writer, index=False, sheet_name="Attachments")
                    if data_reference:
                        pd.DataFrame({"Reference Type":["Accounts","Vendors","Departments"],"Count":[filtered.account.nunique(),filtered.vendor.nunique(),filtered.department.nunique()]}).to_excel(writer,index=False,sheet_name="Reference Data")
                    if data_stations: pd.DataFrame([{"Station":s,"SLA Minutes":SLA_DEFAULTS[s]} for s in STATIONS]).to_excel(writer,index=False,sheet_name="Stations")
                    if data_alerts:
                        with db_connect() as con: alert_df = pd.read_sql_query("SELECT name,trigger_event,threshold,color,icon,audio_name,enabled,description FROM alerts",con)
                        alert_df.to_excel(writer,index=False,sheet_name="Alert Rules")
                payload, filename, mime = buffer.getvalue(), "ovr_vw_export.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            elif export_format.startswith("CSV"):
                payload, filename, mime = out_df.to_csv(index=False).encode("utf-8-sig"), "ovr_vw_export.csv", "text/csv"
            elif export_format.startswith("PDF"):
                try:
                    from reportlab.lib import colors
                    from reportlab.lib.pagesizes import landscape, A4
                    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
                    from reportlab.lib.styles import getSampleStyleSheet
                    buff = io.BytesIO(); doc = SimpleDocTemplate(buff, pagesize=landscape(A4))
                    rows = [list(out_df.columns)] + out_df.head(500).fillna("").astype(str).values.tolist()
                    table = Table(rows, repeatRows=1)
                    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e7edf5")),("TEXTCOLOR",(0,0),(-1,0),colors.HexColor("#081b3b")),("GRID",(0,0),(-1,-1),.3,colors.HexColor("#d5dce6")),("FONTSIZE",(0,0),(-1,-1),7),("VALIGN",(0,0),(-1,-1),"TOP")] ))
                    doc.build([Paragraph("OVR-VW — Data Export",getSampleStyleSheet()["Title"]),Spacer(1,12),table]); payload=buff.getvalue(); filename="ovr_vw_export.pdf"; mime="application/pdf"
                except ImportError:
                    st.error("PDF export requires ReportLab. Install with: pip install reportlab")
                    return
            else:
                try:
                    from pptx import Presentation
                    from pptx.util import Inches, Pt
                    prs=Presentation(); slide=prs.slides.add_slide(prs.slide_layouts[0]); slide.shapes.title.text="OVR-VW Data Export"
                    slide.placeholders[1].text=f"Generated {datetime.now():%b %d, %Y %I:%M %p} | {len(filtered)} records"
                    slide=prs.slides.add_slide(prs.slide_layouts[5]); slide.shapes.title.text="Case Data Preview"
                    rows = [list(out_df.columns)] + out_df.head(12).fillna("").astype(str).values.tolist()
                    table = slide.shapes.add_table(len(rows), max(1,len(rows[0])), Inches(.25), Inches(1.3), Inches(12.7), Inches(5.3)).table
                    for ri,row in enumerate(rows):
                        for ci,val in enumerate(row):
                            table.cell(ri,ci).text=str(val)[:70]
                            for p in table.cell(ri,ci).text_frame.paragraphs:
                                for run in p.runs: run.font.size=Pt(8)
                    slide=prs.slides.add_slide(prs.slide_layouts[5]); slide.shapes.title.text="Cases by Station"
                    for i,(station,count) in enumerate(filtered.station.value_counts().items()):
                        p=slide.shapes.add_textbox(Inches(.8), Inches(1.4+i*.45), Inches(8), Inches(.4)).text_frame.paragraphs[0]; p.text=f"{station}: {count}"
                    buff=io.BytesIO(); prs.save(buff); payload=buff.getvalue(); filename="ovr_vw_export.pptx"; mime="application/vnd.openxmlformats-officedocument.presentationml.presentation"
                except ImportError:
                    st.error("PowerPoint export requires python-pptx. Install with: pip install python-pptx")
                    return
            st.download_button("⇩ Export Data", payload, filename, mime, type="primary", use_container_width=True, key="download_export")


def render_simulation():
    st.markdown("### Simulation")
    st.caption("Generate mock cases and system events for training and testing.")
    left,right=st.columns([1.1,1])
    with left:
        sim_type=st.radio("Select Simulation Type",["Single Case","Multiple Cases","Station Load","System Event"],horizontal=True)
        with st.form("simulation_form"):
            station=st.selectbox("Station",STATIONS)
            priority=st.selectbox("Priority",["CRITICAL","HIGH","MEDIUM","LOW"],index=1)
            account=st.selectbox("Account",["H&M (High Priority Account)","Global Retail","TechCorp","Acme Ltd","Metro Partners"])
            issue=st.selectbox("Issue Category",["Network Connectivity","Hardware","Access","Shipment","Installation","System Event"])
            vendor=st.selectbox("Vendor",["Aruba Networks","HPE","Third-party","Cisco"])
            assignee=st.selectbox("Assignee",["Unassigned","Maria Santos","James Li","Ravi Patel","Ana Rodriguez","Daniel Kim"])
            subject=st.text_input("Subject",f"Simulated {issue.lower()} - {account.split(' (')[0]}")
            description=st.text_area("Description","This is a simulated case for training and testing the alert and workflow process.")
            trigger_alert=st.selectbox("Trigger Alert",["Yes - Pop-up alert for all users","Yes - In-app only","No"])
            alert_delay=st.number_input("Alert Timing (seconds)",min_value=0,max_value=120,value=5)
            audio=st.file_uploader("Audio Alert (Optional)",type=["mp3","wav"],key="simulation_audio")
            start=st.form_submit_button("▶ Start Simulation",type="primary",use_container_width=True)
        if start:
            count={"Single Case":1,"Multiple Cases":5,"Station Load":10,"System Event":0}[sim_type]
            if sim_type=="System Event":
                st.session_state.sim_alert={"title":"Simulation System Event","message":description,"delay":int(alert_delay),"created":time.time()}
                st.success("System event simulation triggered.")
            else:
                for n in range(count):
                    cn_prefix={"CARE":"CAR","ARCH":"ARC","PET":"PET","SUPPLY CHAIN":"SC","FULFILLMENT":"FUL"}[station]
                    with db_connect() as con:
                        existing=con.execute("SELECT COUNT(*) FROM cases WHERE case_number LIKE ?",(f"{cn_prefix}-SIM-%",)).fetchone()[0]
                        cn=f"{cn_prefix}-SIM-{existing+1:04d}"
                        created=now_iso()
                        checklist=[{"text":x,"done":False} for x in ["Confirm product, model and serial number","Capture error message or customer symptom","Complete troubleshooting checks","Verify support and entitlement","Record customer contact and reference","Document assessment and next action"]]
                        hist=[{"at":created,"action":"Case Created","status":"Open","by":"Simulation","details":"Simulated case created."}]
                        con.execute("""INSERT INTO cases(id,case_number,subject,account,station,assignee,priority,status,created_at,updated_at,description,vendor,department,issue_category,action_plan,source,checklist,station_history,case_history,collaboration,attachments,is_simulated)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                        (str(uuid.uuid4()),cn,subject if n==0 else f"{subject} #{n+1}",account.split(" (")[0],station,assignee,priority,"In Progress",created,created,description,vendor,"Operations",issue,"Investigate the simulated issue and record findings.","Simulation",json.dumps(checklist),json.dumps([{"station":station,"entered_at":created,"exited_at":"","duration_seconds":0}]),json.dumps(hist),"[]","[]"))
                if trigger_alert!="No":
                    st.session_state.sim_alert={"title":"Simulation Alert","message":f"{subject} — {account.split(' (')[0]}","delay":int(alert_delay),"created":time.time()}
                st.success(f"Simulation created {count} case(s).")
                st.rerun()
    with right:
        st.markdown("### Current Active Cases (Live View)")
        df=all_cases()
        active=df[~df.status.str.upper().isin(["CLOSED","RESOLVED","COMPLETED"])]
        station_filter=st.selectbox("Filter station",["All Stations"]+STATIONS,key="sim_station")
        if station_filter!="All Stations": active=active[active.station==station_filter]
        if not active.empty:
            st.dataframe(active[["case_number","subject","station","priority","status"]].head(10),hide_index=True,use_container_width=True)
        st.markdown("### Simulated Cases History")
        sim=df[df.is_simulated==1]
        if not sim.empty:
            st.dataframe(sim[["case_number","subject","station","priority","created_at"]].head(15),hide_index=True,use_container_width=True)
            chosen=st.selectbox("Choose simulation to remove",["Select..."]+sim.case_number.tolist())
            if chosen!="Select..." and st.button("Delete selected simulation"):
                with db_connect() as con: con.execute("DELETE FROM cases WHERE case_number=?",(chosen,))
                st.rerun()
        else:
            st.caption("No simulated cases yet.")
        if st.button("Reset Simulation",type="secondary"):
            with db_connect() as con: con.execute("DELETE FROM cases WHERE is_simulated=1")
            st.session_state.sim_alert=None
            st.success("Simulated cases removed.")
            st.rerun()
    alert=st.session_state.get("sim_alert")
    if alert and time.time()-alert.get("created",time.time()) >= alert.get("delay",0):
        st.warning(f"🔔 **{alert['title']}** — {alert['message']}")
        if st.button("View simulated case"):
            df=all_cases(); sims=df[df.is_simulated==1]
            if not sims.empty: st.session_state.open_case_id=sims.iloc[0]["id"]
            st.session_state.sim_alert=None
            st.rerun()
        if st.button("Dismiss alert"):
            st.session_state.sim_alert=None;st.rerun()


def render_settings():
    st.markdown("<div class='panel-title'>Settings</div><div class='panel-subtitle'>Manage system configuration, data and preferences</div>",unsafe_allow_html=True)
    names=["General","Alert Management","Data Import","Export Data","Simulation"]
    if "settings_tab" not in st.session_state: st.session_state.settings_tab="General"
    active=st.session_state.settings_tab
    cols=st.columns(5)
    for i,name in enumerate(names):
        with cols[i]:
            if st.button(("⚙ " if name=="General" else "♧ " if name=="Alert Management" else "⇧ " if name=="Data Import" else "⇩ " if name=="Export Data" else "▷ ")+name,use_container_width=True,type="primary" if active==name else "secondary",key="settings_"+name):
                st.session_state.settings_tab=name;st.rerun()
    st.divider()
    if active=="General": render_general_settings()
    elif active=="Alert Management": render_alert_management()
    elif active=="Data Import": render_import()
    elif active=="Export Data": render_export()
    elif active=="Simulation": render_simulation()


def main():
    init_db()
    header()
    if "open_case_id" not in st.session_state: st.session_state.open_case_id=None
    if "page" not in st.session_state: st.session_state.page="Dashboard"
    nav1,nav2,nav3=st.columns([1,1,3])
    with nav1:
        if st.button("Active Cases",type="primary" if st.session_state.page=="Dashboard" else "secondary",use_container_width=True):
            st.session_state.page="Dashboard";st.rerun()
    with nav2:
        if st.button("⚙ Settings",type="primary" if st.session_state.page=="Settings" else "secondary",use_container_width=True):
            st.session_state.page="Settings";st.rerun()
    with nav3:
        q=st.text_input("Global case search",placeholder="Search cases by number, subject, account, assignee...",label_visibility="collapsed",key="global_search")
    if st.session_state.page=="Settings":
        render_settings()
    else:
        if q:
            df=all_cases()
            mask=df[["case_number","subject","account","assignee","station"]].fillna("").astype(str).apply(lambda col: col.str.contains(q,case=False)).any(axis=1)
            found=df[mask]
            st.markdown("### Search Results")
            if not found.empty:
                st.dataframe(found[["case_number","subject","account","station","assignee","priority","status"]],hide_index=True,use_container_width=True)
                options=[f"{r['case_number']} — {r['subject']}" for _,r in found.iterrows()]
                pick=st.selectbox("Open result",["Select..."]+options)
                if pick!="Select..." and st.button("View search result"):
                    st.session_state.open_case_id=found.iloc[options.index(pick)]["id"];st.rerun()
            else: st.info("No matching cases.")
        else:
            render_dashboard()
    if st.session_state.open_case_id:
        st.divider()
        render_case_detail(st.session_state.open_case_id)
    st.markdown("<div class='small-muted' style='text-align:center;padding:18px'>Application: OVR-VW &nbsp; | &nbsp; Version: 1.0.0 &nbsp; | &nbsp; Operations Visibility &amp; Response Workspace</div>",unsafe_allow_html=True)


if __name__ == "__main__":
    main()
