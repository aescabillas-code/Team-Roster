import os, sqlite3, hashlib, secrets, smtplib
from email.message import EmailMessage
from datetime import datetime, date, timedelta, time
import pandas as pd
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

try:
    from simple_salesforce import Salesforce
except ImportError:
    Salesforce = None

st.set_page_config(page_title="HPE Case Operations Control Center", page_icon="◈",
                   layout="wide", initial_sidebar_state="collapsed")

DB_PATH = os.getenv("CASE_DB_PATH", "case_control_center.db")
REFRESH_SECONDS = max(10, int(os.getenv("REFRESH_SECONDS", "15")))
SUPER_ADMIN_EMAIL = "arianne-may.escabillas@hpe.com"

STATUS_OPTIONS = ["New","Assigned","In Progress","Waiting for Vendor",
                   "Waiting for Customer","Pending Internal","Completed",
                   "Contract Breached","Cancelled"]
AUX_OPTIONS = ["Available","Busy - Away","Break","Unscheduled Break","Lunch",
               "In a Meeting","Coaching","Admin Task","Offline"]
BREACH_REASONS = ["Vendor missed committed date","Vendor failed to provide update",
                  "Vendor delivered incomplete service","Vendor SLA violation",
                  "Vendor did not respond within required timeframe","Other"]
LEAVE_TYPES = ["PTO","Sick Leave","Emergency Leave"]
ACTIVITIES = ["Queue","Break","Lunch","Meeting","Coaching","Admin Task",
              "Training","PTO","Sick Leave","Emergency Leave"]

st.markdown("""
<style>
#MainMenu,footer,header{visibility:hidden}
.block-container{max-width:100%;padding:.65rem 1rem 1.5rem}
.appbar{background:linear-gradient(100deg,#0b1f33,#164d75);color:#fff;padding:13px 18px;border-radius:13px;margin-bottom:10px;display:flex;justify-content:space-between}
.appbar-title{font-weight:800;font-size:1.25rem}.appbar-sub{opacity:.8;font-size:.76rem}
.kpi{background:#fff;border:1px solid #dbe3ec;border-radius:13px;padding:14px 16px;min-height:104px;box-shadow:0 1px 4px #0f172a0a}
.kpi-label{color:#66788a;font-size:.72rem;font-weight:800;text-transform:uppercase}.kpi-value{color:#172b4d;font-size:2rem;font-weight:850}
.kpi-total{border-left:5px solid #1769aa}.kpi-critical{border-left:5px solid #c62828}.kpi-due{border-left:5px solid #d69e00}.kpi-track{border-left:5px solid #2e7d32}
.pill{border-radius:999px;padding:3px 9px;font-size:.68rem;font-weight:800;display:inline-block}
.red{background:#fdecec;color:#a51d1d}.yellow{background:#fff5d9;color:#805500}.green{background:#eaf7ed;color:#236a2a}.blue{background:#e9f2fb;color:#145b91}
button{border-radius:8px!important}
</style>
""", unsafe_allow_html=True)

def db():
    c=sqlite3.connect(DB_PATH,check_same_thread=False,timeout=15); c.row_factory=sqlite3.Row; return c

def init_db():
    c=db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,first_name TEXT,last_name TEXT,
      employee_id TEXT UNIQUE,email TEXT UNIQUE,birthday TEXT,home_address TEXT,
      contact_number TEXT,password_hash TEXT,role TEXT DEFAULT 'regular',
      aux TEXT DEFAULT 'Busy - Away',active INTEGER DEFAULT 1,last_seen TEXT,
      created_at TEXT,pto_allocation REAL DEFAULT 15,pto_used REAL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS cases(
      id INTEGER PRIMARY KEY AUTOINCREMENT,case_number TEXT UNIQUE,subject TEXT,
      description TEXT,customer TEXT,vendor TEXT,technician TEXT,vendor_email TEXT,
      vendor_phone TEXT,salesforce_url TEXT,status TEXT DEFAULT 'New',
      priority TEXT DEFAULT 'Medium',progress INTEGER DEFAULT 0,due_at TEXT,
      created_at TEXT,updated_at TEXT,last_agent_update TEXT,assigned_to INTEGER,
      source TEXT DEFAULT 'Internal',contract_breached INTEGER DEFAULT 0,breach_reason TEXT);
    CREATE TABLE IF NOT EXISTS case_history(
      id INTEGER PRIMARY KEY AUTOINCREMENT,case_id INTEGER,actor_id INTEGER,
      action TEXT,details TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS schedules(
      id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,schedule_date TEXT,
      start_time TEXT,end_time TEXT,activity TEXT,status TEXT DEFAULT 'Scheduled',notes TEXT);
    CREATE TABLE IF NOT EXISTS schedule_requests(
      id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,request_type TEXT,
      request_date TEXT,start_time TEXT,end_time TEXT,target_user_id INTEGER,
      status TEXT DEFAULT 'Pending',notes TEXT,created_at TEXT,approved_at TEXT);
    CREATE TABLE IF NOT EXISTS notifications(
      id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,title TEXT,message TEXT,
      severity TEXT DEFAULT 'info',is_read INTEGER DEFAULT 0,created_at TEXT);
    CREATE TABLE IF NOT EXISTS attendance(
      id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,work_date TEXT,
      scheduled_minutes INTEGER DEFAULT 0,available_minutes INTEGER DEFAULT 0,
      attendance_minutes INTEGER DEFAULT 0,adherence_minutes INTEGER DEFAULT 0,status TEXT);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
    """)
    defaults={"pto_default_allocation":"15","pto_daily_limit":"1","break_minutes":"15",
              "lunch_minutes":"60","auto_assign_enabled":"1","refresh_seconds":str(REFRESH_SECONDS),
              "first_break_after_hours":"2","lunch_after_hours":"2","last_break_after_hours":"2"}
    for k,v in defaults.items(): c.execute("INSERT OR IGNORE INTO settings VALUES(?,?)",(k,v))
    c.commit(); c.close()

def setting(k,d=None):
    c=db(); r=c.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone(); c.close()
    return r["value"] if r else d

def set_setting(k,v):
    c=db(); c.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(k,str(v))); c.commit(); c.close()

def hash_pw(p,s=None):
    s=s or secrets.token_bytes(16); return s.hex()+":"+hashlib.pbkdf2_hmac("sha256",p.encode(),s,180000).hex()

def check_pw(p,stored):
    try:
        s,h=stored.split(":"); return secrets.compare_digest(hashlib.pbkdf2_hmac("sha256",p.encode(),bytes.fromhex(s),180000).hex(),h)
    except: return False

def ensure_superadmin():
    c=db(); r=c.execute("SELECT id FROM users WHERE lower(email)=?",(SUPER_ADMIN_EMAIL,)).fetchone()
    if not r:
        now=datetime.now().isoformat(timespec="seconds")
        c.execute("""INSERT INTO users(first_name,last_name,employee_id,email,birthday,home_address,contact_number,password_hash,role,aux,active,last_seen,created_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  ("Arianne","May Escabillas","SUPERADMIN",SUPER_ADMIN_EMAIL,"1990-01-01","—","—",
                   hash_pw(secrets.token_urlsafe(16)),"admin","Admin Task",1,now,now))
    else: c.execute("UPDATE users SET role='admin',active=1,aux='Admin Task' WHERE lower(email)=?",(SUPER_ADMIN_EMAIL,))
    c.commit(); c.close()

def users():
    c=db(); r=c.execute("SELECT * FROM users ORDER BY last_name,first_name").fetchall(); c.close()
    return pd.DataFrame([dict(x) for x in r])

def login(e,p):
    c=db(); r=c.execute("SELECT * FROM users WHERE employee_id=? AND active=1",(e.strip(),)).fetchone()
    if r and check_pw(p,r["password_hash"]):
        c.execute("UPDATE users SET last_seen=? WHERE id=?",(datetime.now().isoformat(timespec="seconds"),r["id"])); c.commit(); c.close()
        return dict(r)
    c.close(); return None

def signup(d):
    c=db()
    try:
        c.execute("""INSERT INTO users(first_name,last_name,employee_id,email,birthday,home_address,contact_number,password_hash,role,aux,active,last_seen,created_at,pto_allocation)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (d["first"],d["last"],d["eid"],d["email"].lower(),d["birthday"].isoformat(),d["address"],
                   d["phone"],hash_pw(d["pw"]),"regular","Busy - Away",1,datetime.now().isoformat(timespec="seconds"),
                   datetime.now().isoformat(timespec="seconds"),float(setting("pto_default_allocation","15"))))
        c.commit(); return True,"Account created."
    except sqlite3.IntegrityError: return False,"Employee ID or email already exists."
    finally: c.close()

def set_aux(uid,aux):
    c=db(); c.execute("UPDATE users SET aux=?,last_seen=? WHERE id=?",(aux,datetime.now().isoformat(timespec="seconds"),uid)); c.commit(); c.close()

def notify(uid,title,msg,severity="info"):
    c=db(); c.execute("INSERT INTO notifications(user_id,title,message,severity,created_at) VALUES(?,?,?,?,?)",
                      (uid,title,msg,severity,datetime.now().isoformat(timespec="seconds"))); c.commit(); c.close()

def notifications(uid):
    c=db(); r=c.execute("SELECT * FROM notifications WHERE user_id=? AND is_read=0 ORDER BY created_at DESC",(uid,)).fetchall(); c.close()
    return [dict(x) for x in r]

def urgency(r):
    if r["status"] in ("Completed","Cancelled"): return "On Track"
    due=pd.to_datetime(r["due_at"],errors="coerce")
    if pd.isna(due): return "On Track"
    left=due-pd.Timestamp.now()
    if str(r["priority"]).lower()=="critical" or left<=pd.Timedelta(hours=2): return "Critical"
    if left<=pd.Timedelta(hours=8): return "Due Soon"
    return "On Track"

def active_cases(search="",uid=None):
    c=db(); sql="""SELECT ca.*,u.first_name||' '||u.last_name assignee,u.employee_id assignee_employee_id,u.aux assignee_aux
                   FROM cases ca LEFT JOIN users u ON ca.assigned_to=u.id
                   WHERE ca.status NOT IN ('Completed','Cancelled')"""
    p=[]
    if uid is not None: sql+=" AND ca.assigned_to=?"; p.append(uid)
    if search:
        q=f"%{search.lower()}%"; sql+=" AND (lower(ca.case_number) LIKE ? OR lower(ca.subject) LIKE ? OR lower(coalesce(ca.customer,'')) LIKE ? OR lower(coalesce(ca.vendor,'')) LIKE ?)"; p += [q]*4
    sql+=" ORDER BY ca.due_at ASC"; r=c.execute(sql,p).fetchall(); c.close()
    out=[]
    for x in r: d=dict(x); d["urgency"]=urgency(x); out.append(d)
    return pd.DataFrame(out)

def all_cases():
    c=db(); r=c.execute("SELECT ca.*,u.first_name||' '||u.last_name assignee FROM cases ca LEFT JOIN users u ON ca.assigned_to=u.id ORDER BY ca.created_at DESC").fetchall(); c.close()
    return pd.DataFrame([dict(x) for x in r])

def get_case(cid):
    c=db(); r=c.execute("SELECT ca.*,u.first_name||' '||u.last_name assignee FROM cases ca LEFT JOIN users u ON ca.assigned_to=u.id WHERE ca.id=?",(cid,)).fetchone(); c.close()
    return dict(r) if r else None

def eligible():
    c=db(); r=c.execute("SELECT * FROM users WHERE role='regular' AND active=1 AND aux='Available'").fetchall(); c.close(); return [dict(x) for x in r]

def assign_case(cid):
    a=eligible()
    if not a: return None
    c=db(); choices=[]
    for x in a:
        active=c.execute("SELECT count(*) n FROM cases WHERE assigned_to=? AND status NOT IN ('Completed','Cancelled')",(x["id"],)).fetchone()["n"]
        today=c.execute("SELECT count(*) n FROM case_history WHERE actor_id=? AND action='Auto Assigned' AND date(created_at)=date('now','localtime')",(x["id"],)).fetchone()["n"]
        last=c.execute("SELECT max(created_at) t FROM case_history WHERE actor_id=? AND action='Auto Assigned'",(x["id"],)).fetchone()["t"] or ""
        choices.append((active,today,last,x))
    choices.sort(key=lambda z:(z[0],z[1],z[2])); x=choices[0][3]; now=datetime.now().isoformat(timespec="seconds")
    c.execute("UPDATE cases SET assigned_to=?,status='Assigned',updated_at=?,last_agent_update=? WHERE id=?",(x["id"],now,now,cid))
    c.execute("INSERT INTO case_history(case_id,actor_id,action,details,created_at) VALUES(?,?,?,?,?)",(cid,x["id"],"Auto Assigned",f"Assigned to {x['first_name']} {x['last_name']}",now))
    c.commit(); c.close()
    case=get_case(cid); notify(x["id"],"New case assigned",f"Case #{case['case_number']} was assigned to you.","warning")
    return x

def update_case(cid,uid,status,progress,note="",reason=None):
    now=datetime.now().isoformat(timespec="seconds"); c=db(); r=c.execute("SELECT * FROM cases WHERE id=?",(cid,)).fetchone()
    if not r: c.close(); return
    c.execute("""UPDATE cases SET status=?,progress=?,updated_at=?,last_agent_update=?,contract_breached=?,breach_reason=? WHERE id=?""",
              (status,max(0,min(100,int(progress))),now,now,1 if status=="Contract Breached" else r["contract_breached"],
               reason if status=="Contract Breached" else r["breach_reason"],cid))
    c.execute("INSERT INTO case_history(case_id,actor_id,action,details,created_at) VALUES(?,?,?,?,?)",(cid,uid,"Case Updated",(note or "")+(f" | Breach: {reason}" if reason else ""),now))
    c.commit(); c.close()

def reassign(cid,aid,adminid):
    now=datetime.now().isoformat(timespec="seconds"); c=db(); a=c.execute("SELECT * FROM users WHERE id=?",(aid,)).fetchone()
    c.execute("UPDATE cases SET assigned_to=?,status='Assigned',updated_at=? WHERE id=?",(aid,now,cid))
    c.execute("INSERT INTO case_history(case_id,actor_id,action,details,created_at) VALUES(?,?,?,?,?)",(cid,adminid,"Admin Reassigned",f"Reassigned to {a['first_name']} {a['last_name']}",now))
    c.commit(); c.close(); notify(aid,"Case reassigned",f"Case #{get_case(cid)['case_number']} was reassigned to you.","warning")

def breach_message(case,reason):
    t={
      "Vendor missed committed date":"Hello, regarding case {case}, the committed delivery date has passed. Please provide the reason for the delay and a revised delivery commitment.",
      "Vendor failed to provide update":"Hello, regarding case {case}, the required vendor update was not received within the expected timeframe. Please provide an immediate status update and next action.",
      "Vendor delivered incomplete service":"Hello, regarding case {case}, the delivered service remains incomplete. Please provide the outstanding items and revised completion commitment.",
      "Vendor SLA violation":"Hello, regarding case {case}, the applicable service level has been exceeded. Please provide the reason and recovery plan.",
      "Vendor did not respond within required timeframe":"Hello, regarding case {case}, the required response was not received within the agreed timeframe. Please respond with current status and recovery plan.",
      "Other":"Hello, regarding case {case}, this case is being tagged as a contract breach based on the documented follow-up outcome. Please provide current status and recovery plan."
    }
    return t.get(reason,t["Other"]).format(case=case["case_number"])

def send_email(to,subject,body):
    host,user,pwd=os.getenv("SMTP_HOST"),os.getenv("SMTP_USER"),os.getenv("SMTP_PASSWORD")
    if not all([host,user,pwd,to]): return False,"Email service is not configured."
    try:
        m=EmailMessage(); m["From"]=user; m["To"]=to; m["Subject"]=subject; m.set_content(body)
        with smtplib.SMTP(host,int(os.getenv("SMTP_PORT","587")),timeout=10) as s:
            s.starttls(); s.login(user,pwd); s.send_message(m)
        return True,"Email sent."
    except Exception as e: return False,str(e)

def schedule(uid,start,end):
    c=db(); r=c.execute("SELECT * FROM schedules WHERE user_id=? AND schedule_date BETWEEN ? AND ? ORDER BY schedule_date,start_time",(uid,start.isoformat(),end.isoformat())).fetchall(); c.close()
    return pd.DataFrame([dict(x) for x in r])

def add_schedule(uid,d,stt,ett,activity,notes=""):
    c=db(); c.execute("INSERT INTO schedules(user_id,schedule_date,start_time,end_time,activity,notes) VALUES(?,?,?,?,?,?)",(uid,d.isoformat(),stt.strftime("%H:%M"),ett.strftime("%H:%M"),activity,notes)); c.commit(); c.close()

def requests_df():
    c=db(); r=c.execute("""SELECT r.*,u.first_name||' '||u.last_name requester,t.first_name||' '||t.last_name target_agent
                          FROM schedule_requests r LEFT JOIN users u ON r.user_id=u.id LEFT JOIN users t ON r.target_user_id=t.id ORDER BY r.created_at DESC""").fetchall(); c.close()
    return pd.DataFrame([dict(x) for x in r])

def auto_leave(uid,kind,d):
    c=db(); u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    if kind=="PTO":
        remain=float(u["pto_allocation"])-float(u["pto_used"]); daily=float(setting("pto_daily_limit","1"))
        if remain<daily: c.close(); return False,"No allocation for the selected date."
        c.execute("UPDATE users SET pto_used=pto_used+? WHERE id=?",(daily,uid))
    now=datetime.now().isoformat(timespec="seconds")
    c.execute("""INSERT INTO schedule_requests(user_id,request_type,request_date,status,notes,created_at,approved_at)
                 VALUES(?,?,?,?,?,?,?)""",(uid,kind,d.isoformat(),"Approved","Auto-approved",now,now))
    c.commit(); c.close()
    for _,a in users().query("role=='admin'").iterrows(): notify(int(a["id"]),f"{kind} approved",f"{kind} for {d} was auto-approved.","success")
    return True,"Approved"

def build_breaks(agent_ids,d):
    for i,uid in enumerate(agent_ids):
        off=(i*15)%60
        b1=(datetime.combine(d,time(8,0))+timedelta(hours=2,minutes=off))
        lunch=b1+timedelta(hours=2,minutes=30); b2=lunch+timedelta(hours=2,minutes=30)
        add_schedule(uid,d,b1.time(),(b1+timedelta(minutes=int(setting("break_minutes","15")))).time(),"Break","Auto-scheduled")
        add_schedule(uid,d,lunch.time(),(lunch+timedelta(minutes=int(setting("lunch_minutes","60")))).time(),"Lunch","Auto-scheduled")
        add_schedule(uid,d,b2.time(),(b2+timedelta(minutes=int(setting("break_minutes","15")))).time(),"Break","Auto-scheduled")

def adherence(d1,d2,uid=None):
    us=users(); us=us[us.role=="regular"] if not us.empty else us
    if uid is not None: us=us[us.id==uid]
    out=[]
    c=db()
    for _,u in us.iterrows():
        r=c.execute("SELECT sum(scheduled_minutes)s,sum(attendance_minutes)a,sum(adherence_minutes)d FROM attendance WHERE user_id=? AND work_date BETWEEN ? AND ?",(int(u.id),d1.isoformat(),d2.isoformat())).fetchone()
        s,a,d=r["s"] or 0,r["a"] or 0,r["d"] or 0
        out.append({"Agent":f"{u.first_name} {u.last_name}","Employee ID":u.employee_id,"Aux":u.aux,
                    "Attendance %":round(a/s*100,1) if s else 0,"Adherence %":round(d/s*100,1) if s else 0,"Scheduled Minutes":s})
    c.close(); return pd.DataFrame(out)

def sf_client():
    if Salesforce is None or not all(os.getenv(k) for k in ["SF_USERNAME","SF_PASSWORD","SF_SECURITY_TOKEN"]): return None
    try: return Salesforce(username=os.getenv("SF_USERNAME"),password=os.getenv("SF_PASSWORD"),security_token=os.getenv("SF_SECURITY_TOKEN"),domain=os.getenv("SF_DOMAIN","login"))
    except: return None

def sf_pull():
    sf=sf_client()
    if not sf: return None,"Salesforce credentials are not configured."
    try:
        r=sf.query("SELECT Id,CaseNumber,Subject,Status,Priority,CreatedDate,LastModifiedDate FROM Case ORDER BY LastModifiedDate DESC LIMIT 100")
        return pd.DataFrame(r.get("records",[])),None
    except Exception as e: return None,str(e)

def case_list(df,user):
    if df.empty: st.info("No active cases."); return
    df=df.copy(); df["_r"]=df.urgency.map({"Critical":0,"Due Soon":1,"On Track":2}); df=df.sort_values(["_r","due_at"])
    for _,r in df.iterrows():
        u=r.urgency
        cls={"Critical":"red","Due Soon":"yellow","On Track":"green"}.get(u,"blue")
        with st.container(border=True):
            a,b,c,d,e=st.columns([1.05,3.5,1.35,1.6,1])
            a.markdown(f'<span class="pill {cls}">{u}</span>',unsafe_allow_html=True)
            b.markdown(f"**{r.case_number} — {r.subject}**<br><small>Last update: {r.last_agent_update or '—'} • Assigned: {r.assignee or 'Unassigned'}</small>",unsafe_allow_html=True)
            c.write(f"{r.status}\n\n{int(r.progress)}%")
            d.write(f"Due\n{r.due_at or '—'}")
            if e.button("Open",key=f"open_{int(r.id)}"): st.session_state["selected_case"]=int(r.id); st.rerun()

def dashboard(user):
    st.markdown("## "+("My Case Dashboard" if user["role"]=="regular" else "Operations Dashboard"))
    search=st.text_input("Search",placeholder="Search case number, subject, customer, vendor…",label_visibility="collapsed")
    df=active_cases(search,user["id"] if user["role"]=="regular" else None)
    vals=[len(df),int((df.urgency=="Critical").sum()) if not df.empty else 0,int((df.urgency=="Due Soon").sum()) if not df.empty else 0,int((df.urgency=="On Track").sum()) if not df.empty else 0]
    cards=[("Total Active Cases",vals[0],"kpi-total",None),("Critical",vals[1],"kpi-critical","Critical"),("Due Soon",vals[2],"kpi-due","Due Soon"),("On Track",vals[3],"kpi-track","On Track")]
    if "kpi_filter" not in st.session_state: st.session_state["kpi_filter"]=None
    for col,(lab,val,css,filt) in zip(st.columns(4),cards):
        with col:
            st.markdown(f'<div class="kpi {css}"><div class="kpi-label">{lab}</div><div class="kpi-value">{val}</div></div>',unsafe_allow_html=True)
            if st.button(f"View {lab}",key=f"k_{lab}",use_container_width=True): st.session_state["kpi_filter"]=filt; st.rerun()
    filt=st.session_state["kpi_filter"]
    show=df[df.urgency==filt] if filt else df
    if filt:
        st.info(f"Showing {filt} cases.")
        if st.button("Clear filter"): st.session_state["kpi_filter"]=None; st.rerun()
    st.markdown("### Active Cases"); case_list(show,user)
    if user["role"]=="admin":
        st.markdown("### Agent Live Distribution")
        u=users(); u=u[u.role=="regular"] if not u.empty else u; rows=[]
        for _,a in u.iterrows():
            c=db(); active=c.execute("SELECT count(*)n FROM cases WHERE assigned_to=? AND status NOT IN ('Completed','Cancelled')",(int(a.id),)).fetchone()["n"]; assigned=c.execute("SELECT count(*)n FROM cases WHERE assigned_to=?",(int(a.id),)).fetchone()["n"]; c.close()
            rows.append({"Agent":f"{a.first_name} {a.last_name}","Employee ID":a.employee_id,"Aux":a.aux,"Active Cases":active,"Total Assigned":assigned,"Eligible":bool(a.active and a.aux=="Available")})
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)

def case_detail(user,cid):
    r=get_case(cid)
    if not r: st.error("Case not found."); return
    if st.button("← Back"): st.session_state["selected_case"]=None; st.rerun()
    st.markdown(f"## {r['case_number']}")
    a,b,c=st.columns(3); a.metric("Status",r["status"]); b.metric("Progress",f"{r['progress']}%"); c.metric("Urgency",urgency(r)); st.progress(r["progress"]/100)
    a,b=st.columns(2)
    with a:
        st.write(f"**Subject:** {r['subject']}"); st.write(f"**Customer:** {r['customer'] or '—'}"); st.write(f"**Vendor:** {r['vendor'] or '—'}"); st.write(f"**Technician:** {r['technician'] or '—'}")
    with b:
        st.write(f"**Assigned:** {r['assignee'] or 'Unassigned'}"); st.write(f"**Priority:** {r['priority']}"); st.write(f"**Due:** {r['due_at'] or '—'}"); st.write(f"**Last update:** {r['last_agent_update'] or '—'}")
    st.write(f"**Description:** {r['description'] or '—'}")
    x,y,z=st.columns(3)
    if r["salesforce_url"]: x.link_button("Open Salesforce Case",r["salesforce_url"],use_container_width=True)
    if r["vendor_email"]: y.link_button("Email Vendor",f"mailto:{r['vendor_email']}",use_container_width=True)
    if r["vendor_phone"]:
        z.markdown(f'<a href="tel:{r["vendor_phone"]}" style="display:block;text-align:center;border:1px solid #dbe3ec;padding:7px;border-radius:8px;text-decoration:none">☎ Call Vendor</a>',unsafe_allow_html=True)
        st.code(r["vendor_phone"])
    if user["role"]=="regular":
        st.divider(); st.markdown("### Update Case")
        with st.form(f"u{cid}"):
            status=st.selectbox("Status",STATUS_OPTIONS,index=STATUS_OPTIONS.index(r["status"]) if r["status"] in STATUS_OPTIONS else 0)
            progress=st.slider("Progress",0,100,int(r["progress"]),5); note=st.text_area("Update / follow-up notes")
            reason=None; generated=""
            if status=="Contract Breached":
                reason=st.selectbox("Contract breached reason",BREACH_REASONS); generated=breach_message(r,reason)
                st.text_area("Generated editable vendor message",generated,height=150)
            if st.form_submit_button("Save Case Update",use_container_width=True):
                update_case(cid,user["id"],status,progress,note,reason); st.success("Case updated."); st.rerun()
        if r["contract_breached"] and r["vendor_email"]:
            msg=breach_message(r,r["breach_reason"] or "Other")
            edit=st.text_area("Editable breach email",msg,key=f"email_{cid}",height=150)
            if st.button("Send Email to Vendor",key=f"send_{cid}",use_container_width=True):
                ok,m=send_email(r["vendor_email"],f"Contract follow-up — Case {r['case_number']}",edit); st.success(m) if ok else st.error(m)
    else:
        st.divider(); st.markdown("### Admin Reassignment")
        u=users(); a=u[u.role=="regular"]
        if not a.empty:
            labels={int(x.id):f"{x.first_name} {x.last_name} ({x.employee_id})" for _,x in a.iterrows()}; ids=list(labels)
            chosen=st.selectbox("Reassign to",ids,index=ids.index(r["assigned_to"]) if r["assigned_to"] in ids else 0,format_func=lambda x:labels[x])
            if st.button("Reassign",use_container_width=True): reassign(cid,chosen,user["id"]); st.success("Reassigned."); st.rerun()

def alerts(user):
    ns=notifications(user["id"])
    for n in ns[:5]:
        (st.error if n["severity"]=="warning" else st.success if n["severity"]=="success" else st.info)(f"**{n['title']}** — {n['message']}")
    df=active_cases(uid=user["id"])
    if not df.empty:
        if (df.urgency=="Critical").any(): st.error(f"🔴 {(df.urgency=='Critical').sum()} critical case(s).")
        if (df.urgency=="Due Soon").any(): st.warning(f"🟡 {(df.urgency=='Due Soon').sum()} due-soon case(s).")
        cutoff=datetime.now()-timedelta(hours=24); stale=0
        for _,r in df.iterrows():
            try: stale += int(datetime.fromisoformat(r.last_agent_update)<cutoff)
            except: stale += 1
        if stale: st.warning(f"⚠️ {stale} case(s) have not been updated for 24+ hours.")

def my_schedule(user):
    st.markdown("## My Schedule"); view=st.radio("View",["Day","Week","Month"],horizontal=True); today=date.today()
    if view=="Day": start=end=today
    elif view=="Week": start=today-timedelta(days=today.weekday()); end=start+timedelta(days=6)
    else: start=today.replace(day=1); end=(date(start.year+1,1,1)-timedelta(days=1)) if start.month==12 else (date(start.year,start.month+1,1)-timedelta(days=1))
    df=schedule(user["id"],start,end)
    if df.empty: st.info("No schedule entries.")
    else: st.dataframe(df[["schedule_date","start_time","end_time","activity","status","notes"]],use_container_width=True,hide_index=True)
    st.divider(); st.markdown("### Leave Request")
    with st.form("leave"):
        kind=st.selectbox("Request",LEAVE_TYPES); d=st.date_input("Date",today); notes=st.text_area("Notes")
        if st.form_submit_button("Submit",use_container_width=True):
            ok,m=auto_leave(user["id"],kind,d); st.success(m) if ok else st.error(m)
    st.markdown("### Schedule Swap")
    u=users(); a=u[(u.role=="regular")&(u.id!=user["id"])]
    if not a.empty:
        with st.form("swap"):
            target=st.selectbox("Swap with",a.id.tolist(),format_func=lambda x:f"{a.loc[a.id==x,'first_name'].iloc[0]} {a.loc[a.id==x,'last_name'].iloc[0]}")
            d=st.date_input("Swap date",today,key="swapd"); agreed=st.checkbox("Both agents have agreed.")
            if st.form_submit_button("Submit Swap",use_container_width=True):
                if agreed:
                    c=db(); c.execute("""INSERT INTO schedule_requests(user_id,request_type,request_date,target_user_id,status,notes,created_at,approved_at)
                                         VALUES(?,?,?,?,?,?,?,?)""",(user["id"],"Schedule Swap",d.isoformat(),target,"Approved","Mutually agreed swap",datetime.now().isoformat(timespec="seconds"),datetime.now().isoformat(timespec="seconds"))); c.commit(); c.close()
                    for _,ad in u[u.role=="admin"].iterrows(): notify(int(ad.id),"Schedule swap","A mutually agreed swap was submitted.","success")
                    st.success("Swap recorded.")
                else: st.error("Both agents must agree.")

def admin_agents(user):
    st.markdown("## Agent Control")
    u=users(); a=u[u.role=="regular"]; rows=[]
    for _,x in a.iterrows():
        c=db(); active=c.execute("SELECT count(*)n FROM cases WHERE assigned_to=? AND status NOT IN ('Completed','Cancelled')",(int(x.id),)).fetchone()["n"]; assigned=c.execute("SELECT count(*)n FROM cases WHERE assigned_to=?",(int(x.id),)).fetchone()["n"]; c.close()
        rows.append({"Agent":f"{x.first_name} {x.last_name}","Employee ID":x.employee_id,"Aux":x.aux,"Active Cases":active,"Assigned":assigned,"Eligible":bool(x.active and x.aux=="Available"),"Last Seen":x.last_seen})
    st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    if a.empty:return
    ids=a.id.tolist(); labels={int(x.id):f"{x.first_name} {x.last_name} ({x.employee_id})" for _,x in a.iterrows()}; chosen=st.selectbox("Agent",ids,format_func=lambda x:labels[x])
    x,y,z=st.columns(3)
    if x.button("Kick / Offline",use_container_width=True):
        c=db(); c.execute("UPDATE users SET active=0,aux='Offline' WHERE id=?",(chosen,)); c.commit(); c.close(); notify(chosen,"Removed from assignment","Admin set you Offline.","warning"); st.rerun()
    if y.button("Restore",use_container_width=True):
        c=db(); c.execute("UPDATE users SET active=1,aux='Busy - Away' WHERE id=?",(chosen,)); c.commit(); c.close(); st.rerun()
    if z.button("Ageing Alert",use_container_width=True): notify(chosen,"Ageing case alert","Please review your ageing case bucket.","warning"); st.success("Sent.")
    if st.button("View Bucket",use_container_width=True): case_list(active_cases(uid=chosen),user)

def admin_roles(user):
    if user["email"].lower()!=SUPER_ADMIN_EMAIL:return
    st.markdown("## User Roles"); u=users()
    for _,x in u.iterrows():
        if x.email.lower()==SUPER_ADMIN_EMAIL: continue
        a,b=st.columns([3,1]); a.write(f"**{x.first_name} {x.last_name}** — {x.email}")
        role=b.selectbox("Role",["regular","admin"],index=1 if x.role=="admin" else 0,key=f"role{x.id}")
        if st.button("Save",key=f"save{x.id}"):
            c=db(); c.execute("UPDATE users SET role=? WHERE id=?",(role,int(x.id))); c.commit(); c.close(); st.rerun()

def admin_schedule(user):
    st.markdown("## Agent Schedule")
    req=requests_df()
    if not req.empty:
        st.dataframe(req[["id","requester","request_type","request_date","target_agent","status","notes"]],use_container_width=True,hide_index=True)
        for _,r in req[req.status=="Pending"].iterrows():
            a,b=st.columns(2)
            if a.button("Approve",key=f"ap{r.id}"):
                c=db(); c.execute("UPDATE schedule_requests SET status='Approved',approved_at=? WHERE id=?",(datetime.now().isoformat(timespec="seconds"),int(r.id))); c.commit(); c.close(); notify(int(r.user_id),"Request approved",f"Request #{r.id} approved.","success"); st.rerun()
            if b.button("Reject",key=f"re{r.id}"):
                c=db(); c.execute("UPDATE schedule_requests SET status='Rejected' WHERE id=?",(int(r.id),)); c.commit(); c.close(); st.rerun()
    st.divider(); u=users(); a=u[u.role=="regular"]; 
    if a.empty:return
    d=st.date_input("Schedule date",date.today())
    if st.button("Generate Default Break/Lunch Plan",use_container_width=True): build_breaks(a.id.tolist(),d); st.success("Generated.")
    st.markdown("### Add Activity")
    with st.form("activity"):
        uid=st.selectbox("Agent",a.id.tolist(),format_func=lambda x:f"{a.loc[a.id==x,'first_name'].iloc[0]} {a.loc[a.id==x,'last_name'].iloc[0]}")
        stt=st.time_input("Start",time(9)); ett=st.time_input("End",time(10)); act=st.selectbox("Activity",ACTIVITIES); notes=st.text_input("Notes")
        if st.form_submit_button("Add Activity",use_container_width=True): add_schedule(uid,d,stt,ett,act,notes); st.success("Added.")
    st.markdown("### Coverage Rules")
    b1=st.number_input("First break after hours",.5,6.,float(setting("first_break_after_hours","2")),.5)
    l=st.number_input("Lunch after break hours",.5,6.,float(setting("lunch_after_hours","2")), .5)
    b2=st.number_input("Final break after lunch hours",.5,6.,float(setting("last_break_after_hours","2")),.5)
    if st.button("Save Rules"): set_setting("first_break_after_hours",b1); set_setting("lunch_after_hours",l); set_setting("last_break_after_hours",b2); st.success("Saved.")

def admin_external():
    st.markdown("## Salesforce — Admin Only")
    if st.button("Pull Latest Salesforce Cases",use_container_width=True):
        data,err=sf_pull()
        if err: st.error(err)
        else: st.session_state["sf"]=data
    if "sf" in st.session_state: st.dataframe(st.session_state["sf"],use_container_width=True,hide_index=True)

def admin_reports():
    st.markdown("## Reports")
    x=all_cases()
    if not x.empty:
        x["urgency"]=x.apply(urgency,axis=1); st.dataframe(x,use_container_width=True,hide_index=True)
        st.download_button("Extract Case Report CSV",x.to_csv(index=False).encode(),f"case_report_{date.today()}.csv","text/csv",use_container_width=True)
    st.divider(); st.markdown("### Daily / MTD Attendance & Adherence")
    today=date.today(); month=today.replace(day=1)
    t=adherence(today,today); m=adherence(month,today)
    a,b=st.columns(2); a.dataframe(t,use_container_width=True,hide_index=True); b.dataframe(m,use_container_width=True,hide_index=True)
    if not m.empty: st.metric("MTD Avg Adherence",f"{m['Adherence %'].mean():.1f}%"); st.metric("MTD Avg Attendance",f"{m['Attendance %'].mean():.1f}%")
    st.divider(); st.markdown("### System Settings")
    p=st.number_input("Default PTO allocation",0,365,float(setting("pto_default_allocation","15")))
    lim=st.number_input("Daily PTO limit",0,30,float(setting("pto_daily_limit","1")))
    ref=st.number_input("Polling interval seconds",10,300,int(setting("refresh_seconds",str(REFRESH_SECONDS))))
    auto=st.checkbox("Auto assignment enabled",setting("auto_assign_enabled","1")=="1")
    if st.button("Save Settings"): set_setting("pto_default_allocation",p); set_setting("pto_daily_limit",lim); set_setting("refresh_seconds",ref); set_setting("auto_assign_enabled","1" if auto else "0"); st.success("Saved.")

def auth():
    st.markdown("<div style='max-width:680px;margin:7vh auto;text-align:center'><h1>HPE Case Operations Control Center</h1><p>Case tracking • auto assignment • workforce scheduling • reporting</p></div>",unsafe_allow_html=True)
    a,b=st.tabs(["Sign In","Create Account"])
    with a:
        with st.form("login"):
            eid=st.text_input("Employee ID"); pw=st.text_input("Password",type="password")
            if st.form_submit_button("Sign In",use_container_width=True):
                u=login(eid,pw)
                if u:
                    aux="Admin Task" if u["role"]=="admin" else "Busy - Away"; set_aux(u["id"],aux); u["aux"]=aux; st.session_state["user"]=u; st.rerun()
                else: st.error("Invalid credentials.")
    with b:
        with st.form("signup"):
            x,y=st.columns(2); first=x.text_input("First name *"); last=y.text_input("Last name *"); eid=x.text_input("Employee ID *"); email=y.text_input("HPE email *")
            birthday=x.date_input("Birthday *",date(1995,1,1),date(1900,1,1),date.today()); phone=y.text_input("Contact number *"); address=st.text_area("Home address *"); p=x.text_input("Password *",type="password"); p2=y.text_input("Confirm password *")
            if st.form_submit_button("Create Account",use_container_width=True):
                if not all([first,last,eid,email,phone,address,p,p2]): st.error("Complete all fields.")
                elif not email.lower().endswith("@hpe.com"): st.error("Use an HPE email.")
                elif p!=p2 or len(p)<10: st.error("Passwords must match and be at least 10 characters.")
                else:
                    ok,msg=signup({"first":first,"last":last,"eid":eid,"email":email,"birthday":birthday,"phone":phone,"address":address,"pw":p}); st.success(msg) if ok else st.error(msg)

init_db(); ensure_superadmin()
if "user" not in st.session_state: auth(); st.stop()
if st_autorefresh: st_autorefresh(interval=REFRESH_SECONDS*1000,key="live_poll")
user=st.session_state["user"]

st.markdown(f"<div class='appbar'><div><div class='appbar-title'>HPE Case Operations Control Center</div><div class='appbar-sub'>Live queue • case tracking • workforce schedule</div></div><div><b>{user['first_name']} {user['last_name']}</b><br><small>{user['role'].upper()} • {user['employee_id']}</small></div></div>",unsafe_allow_html=True)

if user["role"]=="regular": alerts(user)

with st.sidebar:
    st.markdown("### Navigation")
    menu=["Dashboard","My Schedule"] if user["role"]=="regular" else ["Dashboard","Agent Control","Schedules","User Roles","Salesforce","Reports"]
    page=st.radio("Menu",menu)
    st.divider()
    if user["role"]=="regular":
        aux=st.selectbox("My Aux",AUX_OPTIONS,index=AUX_OPTIONS.index(user["aux"]) if user["aux"] in AUX_OPTIONS else 1)
        if aux!=user["aux"]: set_aux(user["id"],aux); user["aux"]=aux; st.session_state["user"]=user; st.rerun()
    if st.button("Mark alerts read"): db().execute("UPDATE notifications SET is_read=1 WHERE user_id=?",(user["id"],)); st.rerun()
    if st.button("Sign Out"): st.session_state.clear(); st.rerun()

selected=st.session_state.get("selected_case")
if selected: case_detail(user,selected); st.stop()

if page=="Dashboard": dashboard(user)
elif page=="My Schedule": my_schedule(user)
elif page=="Agent Control": admin_agents(user)
elif page=="Schedules": admin_schedule(user)
elif page=="User Roles": admin_roles(user)
elif page=="Salesforce": admin_external()
elif page=="Reports": admin_reports()
