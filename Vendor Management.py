import os, re, hashlib, secrets
from datetime import datetime, date, timedelta, time
from urllib.parse import quote
import pandas as pd
import streamlit as st
from pymongo import MongoClient, ASCENDING, DESCENDING
from bson import ObjectId
try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

st.set_page_config(page_title='HPE Team Operations Control Center', page_icon='◈', layout='wide', initial_sidebar_state='collapsed')
APP='HPE Team Operations Control Center'; SUPER='arianne-may.escabillas@hpe.com'; POLL=int(os.getenv('REFRESH_SECONDS','15'))
STATUSES=['New','Assigned','In Progress','Waiting for Vendor','Waiting for Customer','Pending Internal','Contract Breached','Completed','Cancelled']
AUX=['Available','Busy - Away','Break','Unscheduled Break','Lunch','In a Meeting','Coaching','Admin Task','Offline']
BREACH=['Vendor missed committed date','Vendor failed to provide update','Vendor SLA violation','Vendor delivered incomplete service','Vendor failed to meet agreed commitment','Other']
ACTIVITIES=['Queue','Break','Lunch','Meeting','Coaching','Admin Task','Training','Other']
REQUESTS=['PTO','Sick Leave','Emergency Leave','Schedule Change','Schedule Swap']
RANK={'Critical':0,'Due Soon':1,'On Track':2}

st.markdown('''<style>
#MainMenu,footer,header{visibility:hidden}.block-container{max-width:100%;padding:.7rem 1rem 1.5rem}[data-testid="stSidebar"]{min-width:260px}
.appbar{background:linear-gradient(105deg,#092238,#14547d);color:#fff;border-radius:14px;padding:14px 20px;margin-bottom:10px;display:flex;justify-content:space-between}.brand{font-size:1.3rem;font-weight:800}.sub{font-size:.75rem;opacity:.8}
.kpi{background:#fff;border:1px solid #dce4ec;border-radius:13px;padding:14px 16px;min-height:105px;box-shadow:0 2px 8px #0f23370b}.kpi-title{font-size:.72rem;text-transform:uppercase;color:#68798b;font-weight:800}.kpi-value{font-size:2rem;font-weight:850;color:#172b4d}.blue{border-left:5px solid #1976b8}.red{border-left:5px solid #c62828}.yellow{border-left:5px solid #d69e00}.green{border-left:5px solid #2e7d32}
.badge{display:inline-block;border-radius:999px;padding:3px 9px;font-size:.69rem;font-weight:800}.badge-red{background:#fdecec;color:#a61c1c}.badge-yellow{background:#fff5d6;color:#8a5c00}.badge-green{background:#e9f7ec;color:#21672a}.small{font-size:.74rem;color:#68798b}
</style>''', unsafe_allow_html=True)

@st.cache_resource(show_spinner=False)
def mongo():
    uri=os.getenv('MONGODB_URI')
    return MongoClient(uri,serverSelectionTimeoutMS=3500,connectTimeoutMS=3500,maxPoolSize=30,retryWrites=True) if uri else None

def db(): return mongo()['TeamRoster'] if mongo() else None
def col(n='Team Roster Collection'): return db()[n] if db() else None
@st.cache_resource(show_spinner=False)
def indexes():
    if not db(): return
    try:
        col().create_index('email',unique=True); col().create_index('employee_id',unique=True)
        db().cases.create_index([('status',ASCENDING),('due_at',ASCENDING)]); db().cases.create_index([('assigned_to',ASCENDING),('status',ASCENDING)])
        db().cases.create_index('updated_at'); db().case_history.create_index([('case_id',ASCENDING),('created_at',DESCENDING)])
        db().schedules.create_index([('user_id',ASCENDING),('schedule_date',ASCENDING)]); db().schedule_requests.create_index([('status',ASCENDING),('created_at',DESCENDING)])
        db().notifications.create_index([('user_id',ASCENDING),('read',ASCENDING)]); db().attendance.create_index([('user_id',ASCENDING),('date',ASCENDING)])
    except Exception: pass

def now(): return datetime.now().isoformat(timespec='seconds')
def hpw(p,s=None):
    s=s or secrets.token_bytes(16); return s.hex()+':'+hashlib.pbkdf2_hmac('sha256',p.encode(),s,210000).hex()
def vpw(p,x):
    try:
        s,h=x.split(':'); return secrets.compare_digest(hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(s),210000).hex(),h)
    except: return False

def user_find(x): return col().find_one({'$or':[{'email':x.strip().lower()},{'employee_id':x.strip()}]})
def auth(x,p):
    u=user_find(x)
    if u and u.get('active',True) and vpw(p,u.get('password_hash','')):
        col().update_one({'_id':u['_id']},{'$set':{'last_seen':now()}}); u['last_seen']=now(); return u

def create_user(d):
    email = d['email'].strip().lower()

    if not re.match(r'^[^@\s]+@hpe\.com$', email):
        return False, 'Use an @hpe.com email address.'

    if col().find_one({
        '$or': [
            {'email': email},
            {'employee_id': d['employee_id'].strip()}
        ]
    }):
        return False, 'Employee ID or email already exists.'

    role = 'admin' if email == SUPER else 'regular'

    try:
        password = d['password']

        user_doc = {
            **{k: v for k, v in d.items() if k != 'password'},
            'email': email,
            'password_hash': hpw(password),
            'role': role,
            'aux': 'Admin Task' if role == 'admin' else 'Busy - Away',
            'active': True,
            'created_at': now(),
            'last_seen': now(),
            'pto_allocation': 15,
            'pto_used': 0,
            'attendance_status': 'Present'
        }

        col().insert_one(user_doc)

    except Exception as e:
        return False, str(e)

    return True, 'Account created. Please sign in.'

def set_aux(uid,a): col().update_one({'_id':uid},{'$set':{'aux':a,'last_seen':now()}})
def users(role=None):
    q={'role':role} if role else {}; return list(col().find(q,{'password_hash':0}).sort([('last_name',1),('first_name',1)]))
def userdf(role=None): return pd.DataFrame(users(role))

def urgency(c):
    if c.get('status') in ('Completed','Cancelled'): return 'On Track'
    d=pd.to_datetime(c.get('due_at'),errors='coerce')
    if pd.isna(d): return 'On Track'
    rem=d-pd.Timestamp.now()
    return 'Critical' if str(c.get('priority','')).lower()=='critical' or rem<=pd.Timedelta(hours=2) else ('Due Soon' if rem<=pd.Timedelta(hours=8) else 'On Track')

def row(c):
    return {'id':str(c['_id']),'case_number':c.get('case_number',''),'subject':c.get('subject',''),'customer':c.get('customer',''),'vendor':c.get('vendor',''),'technician':c.get('technician',''),'status':c.get('status','New'),'priority':c.get('priority','Medium'),'progress':int(c.get('progress',0)),'due_at':c.get('due_at',''),'last_update':c.get('last_update',c.get('updated_at','')),'assigned_to':c.get('assigned_to'),'assigned_to_name':c.get('assigned_to_name','Unassigned'),'salesforce_url':c.get('salesforce_url',''),'vendor_email':c.get('vendor_email',''),'vendor_phone':c.get('vendor_phone',''),'description':c.get('description',''),'source':c.get('source','Internal'),'breach_reason':c.get('breach_reason','')}

def cases(search='',uid=None,closed=False):
    q={}
    if not closed:q['status']={'$nin':['Completed','Cancelled']}
    if uid:q['assigned_to']=uid
    if search.strip():
        rx={'$regex':re.escape(search.strip()),'$options':'i'};q['$or']=[{'case_number':rx},{'subject':rx},{'customer':rx},{'vendor':rx}]
    out=pd.DataFrame([row(x) for x in col('cases').find(q).sort('due_at',ASCENDING)])
    if out.empty:return out
    out['urgency']=out.apply(lambda x:urgency(x.to_dict()),axis=1);out['_rank']=out.urgency.map(RANK);return out.sort_values(['_rank','due_at'],kind='stable').reset_index(drop=True)

def case(cid):
    try:c=col('cases').find_one({'_id':ObjectId(cid)})
    except:c=None
    return row(c) if c else None

def history(cid,uid,action,detail=''): db().case_history.insert_one({'case_id':str(cid),'actor_id':uid,'action':action,'details':detail,'created_at':now()})
def notify(uid,title,msg,kind='general'):
    if uid:db().notifications.insert_one({'user_id':uid,'title':title,'message':msg,'kind':kind,'created_at':now(),'read':False})
def unread(uid):return db().notifications.count_documents({'user_id':uid,'read':False})
def notes(uid):return list(db().notifications.find({'user_id':uid}).sort('created_at',DESCENDING).limit(12))

def load(uid):return col('cases').count_documents({'assigned_to':uid,'status':{'$nin':['Completed','Cancelled']}})
def assign(cid,actor=None):
    c=col('cases').find_one({'_id':cid}); agents=users('regular'); agents=[a for a in agents if a.get('active',True) and a.get('aux')=='Available']
    if not c or not agents:return None
    ranked=[]
    for a in agents:
        active=load(a['_id']); today=col('cases').count_documents({'assigned_to':a['_id'],'assigned_at':{'$regex':'^'+date.today().isoformat()}});ranked.append((active,today,a.get('last_assignment_at',''),a))
    a=sorted(ranked,key=lambda x:(x[0],x[1],x[2] or ''))[0][3]; stamp=now(); name=f"{a['first_name']} {a['last_name']}"
    r=col('cases').update_one({'_id':cid,'assigned_to':{'$exists':False}},{'$set':{'assigned_to':a['_id'],'assigned_to_name':name,'status':'Assigned','assigned_at':stamp,'last_update':stamp,'updated_at':stamp}})
    if r.modified_count:
        col().update_one({'_id':a['_id']},{'$set':{'last_assignment_at':stamp}});history(cid,actor,'Auto Assigned',name);notify(a['_id'],'New case assigned',f"{c.get('case_number')} was assigned to you.",'case');return a

def create_case(d,actor=None):
    stamp=now();doc={**d,'status':'New','progress':0,'created_at':stamp,'updated_at':stamp,'last_update':stamp,'contract_breached':False}
    try:r=col('cases').insert_one(doc)
    except Exception:return False,'Case number already exists.'
    assign(r.inserted_id,actor);return True,'Case created and queued for assignment.'

def update_case(cid,uid,status,progress,note='',reason=''):
    u={'status':status,'progress':int(progress),'updated_at':now(),'last_update':now()}
    if status=='Contract Breached':u.update(contract_breached=True,breach_reason=reason)
    r=col('cases').update_one({'_id':ObjectId(cid)},{'$set':u})
    if r.modified_count:history(cid,uid,'Case Updated',note);return True
    return False

def reassign(cid,aid,actor):
    a=col().find_one({'_id':aid,'role':'regular'});name=f"{a['first_name']} {a['last_name']}" if a else ''
    if not a:return False
    r=col('cases').update_one({'_id':ObjectId(cid)},{'$set':{'assigned_to':aid,'assigned_to_name':name,'status':'Assigned','assigned_at':now(),'updated_at':now(),'last_update':now()}})
    if r.modified_count:history(cid,actor,'Admin Reassigned',name);notify(aid,'Case reassigned','A case was reassigned to you.','case');return True
    return False

def breach_msg(c,reason):
    t={'Vendor missed committed date':'The committed delivery date has been missed. Please provide an immediate status update and revised commitment.','Vendor failed to provide update':'We have not received the required status update. Please provide an update and next action as soon as possible.','Vendor SLA violation':'The agreed SLA has not been met. Please provide the reason for the delay and an immediate recovery plan.','Vendor delivered incomplete service':'The delivered service remains incomplete. Please confirm the outstanding items and committed completion date.','Vendor failed to meet agreed commitment':'The agreed commitment has not been met. Please provide the recovery plan and revised completion date.','Other':'The agreed service commitment has not been met. Please provide an immediate status update and recovery plan.'};return f"Hello, we are following up regarding case {c['case_number']}. {t.get(reason,t['Other'])}"

def generate_alerts(u):
    if u['role']!='regular':return
    df=cases(uid=u['_id'])
    for _,r in df.iterrows():
        d=pd.to_datetime(r.last_update,errors='coerce');typ=r.urgency
        if typ in ('Critical','Due Soon'):
            key=f"{typ}:{r.id}:{date.today().isoformat()}:{datetime.now().hour}"
            if not db().notifications.find_one({'dedupe':key}):
                notify(u['_id'],typ,f"{r.case_number} is {typ.lower()}.",typ.lower());db().notifications.update_one({'user_id':u['_id'],'message':{'$regex':re.escape(r.case_number)},'dedupe':{'$exists':False}},{'$set':{'dedupe':key}})
        if not pd.isna(d) and datetime.now()-d.to_pydatetime()>=timedelta(hours=24):
            key=f"stale:{r.id}:{date.today().isoformat()}"
            if not db().notifications.find_one({'dedupe':key}):notify(u['_id'],'24-hour update reminder',f"{r.case_number} has not been updated for 24 hours.",'stale');db().notifications.update_one({'user_id':u['_id'],'message':{'$regex':re.escape(r.case_number)},'dedupe':{'$exists':False}},{'$set':{'dedupe':key}})

def schedule(uid,start,end):return pd.DataFrame(list(db().schedules.find({'user_id':uid,'schedule_date':{'$gte':start.isoformat(),'$lte':end.isoformat()}}).sort([('schedule_date',1),('start_time',1)])))
def add_sched(uid,d,s,e,a,n=''):db().schedules.insert_one({'user_id':uid,'schedule_date':d.isoformat(),'start_time':s.strftime('%H:%M'),'end_time':e.strftime('%H:%M'),'activity':a,'notes':n,'status':'Scheduled','created_at':now()})
def request(u,typ,d,s,e,target=None,n=''):
    if typ=='PTO' and int(u.get('pto_allocation',15))-int(u.get('pto_used',0))<=0:return False,'No allocation for the selected date.'
    status='Approved' if typ in ('Sick Leave','Emergency Leave') else 'Pending';db().schedule_requests.insert_one({'user_id':u['_id'],'request_type':typ,'request_date':d.isoformat(),'start_time':s.strftime('%H:%M'),'end_time':e.strftime('%H:%M'),'target_user_id':target,'status':status,'notes':n,'created_at':now()})
    if typ=='PTO':col().update_one({'_id':u['_id']},{'$inc':{'pto_used':1}})
    for a in users('admin'):notify(a['_id'],'New schedule request',f"{u['first_name']} {u['last_name']} submitted {typ}.",'schedule')
    if status=='Approved':notify(u['_id'],f'{typ} approved',f'Your {typ.lower()} request for {d.isoformat()} was auto-approved.','schedule')
    return True,'Request submitted.'
def requests_df():return pd.DataFrame(list(db().schedule_requests.find().sort('created_at',DESCENDING)))
def approve(rid,ok=True):
    r=db().schedule_requests.find_one({'_id':ObjectId(rid)});db().schedule_requests.update_one({'_id':ObjectId(rid)},{'$set':{'status':'Approved' if ok else 'Rejected','processed_at':now()}})
    if r:notify(r['user_id'],'Request processed',f"Your {r['request_type']} request was {'approved' if ok else 'rejected'}.",'schedule')
def swap(rid):
    r=db().schedule_requests.find_one({'_id':ObjectId(rid)});t=db().schedule_requests.find_one({'request_type':'Schedule Swap','request_date':r['request_date'],'user_id':r['target_user_id'],'target_user_id':r['user_id'],'status':'Pending'}) if r else None
    if not t:return False
    db().schedule_requests.update_many({'_id':{'$in':[r['_id'],t['_id']]}},{'$set':{'status':'Approved','processed_at':now()}});notify(r['user_id'],'Schedule swap approved','Both agents agreed.','schedule');notify(t['user_id'],'Schedule swap approved','Both agents agreed.','schedule');return True

def auto_sched(d):
    agents=users('regular');
    for i,a in enumerate([x for x in agents if x.get('active',True)]):
        base=datetime.combine(d,time(9))+timedelta(minutes=15*i)
        for act,st in [('Break',base+timedelta(hours=2)),('Lunch',base+timedelta(hours=4)),('Break',base+timedelta(hours=6))]:
            en=st+timedelta(minutes=60 if act=='Lunch' else 15)
            if not db().schedules.find_one({'user_id':a['_id'],'schedule_date':d.isoformat(),'start_time':st.strftime('%H:%M'),'activity':act}):add_sched(a['_id'],d,st.time(),en.time(),act,'Auto-generated coverage schedule')

def adh(uid=None,mtd=False):
    d=date.today();start=d.replace(day=1) if mtd else d;q={'date':{'$gte':start.isoformat(),'$lte':d.isoformat()}};q.update({'user_id':uid} if uid else {})
    rows=list(db().attendance.find(q));
    if not rows:return 0.0
    p=sum(float(x.get('planned_minutes',0)) for x in rows);a=sum(float(x.get('adherent_minutes',0)) for x in rows);return round(a/p*100,1) if p else 0.0

@st.dialog('Sign In')
def signin():
    with st.form('signin'):
        a=st.text_input('HPE email or Employee ID');p=st.text_input('Password',type='password');ok=st.form_submit_button('Sign In',use_container_width=True)
    if ok:
        u=auth(a,p)
        if u:st.session_state.user=u;st.rerun()
        else:st.error('Invalid account, password, or inactive account.')
@st.dialog("Sign Up")
def signup_dialog():

    with st.form("signup"):

        a, b = st.columns(2)

        first = a.text_input("First name *")
        last = b.text_input("Last name *")

        eid = a.text_input("Employee ID *")
        email = b.text_input("HPE email address *")

        bd = a.date_input("Birthday *", date(1995, 1, 1))
        phone = b.text_input("Contact number *")

        address = st.text_area("Home address *")

        pw = a.text_input("Account password *", type="password")
        pw2 = b.text_input("Confirm password *", type="password")

        agree = st.checkbox(
            "I confirm the information is accurate."
        )

        ok = st.form_submit_button(
            "Create Account",
            use_container_width=True
        )

    if ok:

        if not agree or not all(
            [first, last, eid, email, phone, address, pw, pw2]
        ):
            st.error(
                "Complete all required fields and confirm the information."
            )

        elif pw != pw2:
            st.error("Passwords do not match.")

        elif len(pw) < 10:
            st.error("Password must be at least 10 characters.")

        else:

            good, msg = create_user({
                'first_name': first,
                'last_name': last,
                'employee_id': eid,
                'email': email,
                'birthday': bd.isoformat(),
                'home_address': address,
                'contact_number': phone,
                'password': pw
            })

            if good:
                st.success(msg)
            else:
                st.error(msg)

def auth_screen():
    st.markdown('<div style="max-width:760px;margin:9vh auto;text-align:center"><div style="font-size:2.2rem;font-weight:850;color:#092238">HPE Team Operations Control Center</div><div class="small">Secure case tracking • workforce coverage • assignment • adherence</div></div>',unsafe_allow_html=True)
    a,b,c=st.columns([1,2,1]);
    with b:
        if st.button('Sign In',type='primary',use_container_width=True):signin()
        if st.button('Sign Up', use_container_width=True):signup_dialog()
        if not mongo():st.warning('Set MONGODB_URI before using the app.')

def badge(x):return f'<span class="badge {"badge-red" if x=="Critical" else "badge-yellow" if x=="Due Soon" else "badge-green"}">{x}</span>'
def render_cases(df,user):
    if df.empty:st.info('No cases found.');return
    for _,r in df.iterrows():
        with st.container(border=True):
            a,b,c,d,e=st.columns([1,3.4,1.2,1.5,1])
            a.markdown(badge(r.urgency),unsafe_allow_html=True);b.markdown(f"**{r.case_number} — {r.subject}**  \n<span class='small'>{r.customer or 'No customer'} • Assigned: {r.assigned_to_name} • Last update: {r.last_update or '—'}</span>",unsafe_allow_html=True);c.write(r.status);d.write(f"{r.progress}%");d.progress(r.progress/100);e.write(f"Due: {r.due_at or '—'}")
            if st.button('Open',key='open_'+r.id,use_container_width=True):st.session_state.selected_case=r.id;st.rerun()
def dashboard(user):
    st.markdown('## My Cases' if user['role']=='regular' else '## Operations Dashboard');q=st.text_input('Search cases',placeholder='Search case number, task, customer, vendor…',label_visibility='collapsed',key='search');df=cases(q,user['_id'] if user['role']=='regular' else None);vals=[len(df),int((df.urgency=='Critical').sum()) if not df.empty else 0,int((df.urgency=='Due Soon').sum()) if not df.empty else 0,int((df.urgency=='On Track').sum()) if not df.empty else 0];cards=[('Total Active Cases',vals[0],'blue',None),('Critical',vals[1],'red','Critical'),('Due Soon',vals[2],'yellow','Due Soon'),('On Track',vals[3],'green','On Track')]
    cc=st.columns(4)
    for c,(lab,v,cl,f) in zip(cc,cards):
        with c:st.markdown(f'<div class="kpi {cl}"><div class="kpi-title">{lab}</div><div class="kpi-value">{v}</div></div>',unsafe_allow_html=True);st.button('View '+lab,key='view_'+lab,on_click=lambda x=f:set_filter(x),use_container_width=True)
    f=st.session_state.get('filter');view=df if not f else df[df.urgency==f]
    if f:
        st.info('Showing: '+f)
        if st.button('Clear filter'):st.session_state.filter=None;st.rerun()
    st.markdown('### Active Cases');render_cases(view,user)
    if user['role']=='admin':
        st.markdown('### Agent Availability & Distribution');agent_distribution()
def set_filter(x):st.session_state.filter=x
def agent_distribution():
    rows=[]
    for a in users('regular'):rows.append({'Agent':f"{a['first_name']} {a['last_name']}",'Employee ID':a['employee_id'],'Aux':a.get('aux',''),'Active':'Yes' if a.get('active',True) else 'No','Active Cases':load(a['_id']),'Assigned Today':col('cases').count_documents({'assigned_to':a['_id'],'assigned_at':{'$regex':'^'+date.today().isoformat()}}),'Last Seen':a.get('last_seen','')})
    st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)

def detail(c,user):
    st.markdown(f'## Case {c["case_number"]}');
    if st.button('← Back to cases'):st.session_state.selected_case=None;st.rerun()
    a,b,d,e=st.columns(4);a.metric('Status',c['status']);b.metric('Progress',f"{c['progress']}%");d.metric('Urgency',urgency(c));e.metric('Assigned To',c['assigned_to_name']);st.progress(c['progress']/100)
    l,r=st.columns([1.6,1]);
    with l:st.write(f"**Subject:** {c['subject']}");st.write(f"**Customer:** {c['customer'] or '—'}");st.write(f"**Vendor:** {c['vendor'] or '—'}");st.write(f"**Technician:** {c['technician'] or '—'}");st.write(f"**Due:** {c['due_at'] or '—'}");st.write(f"**Last Update:** {c['last_update'] or '—'}");st.write(f"**Description:** {c['description'] or '—'}")
    with r:
        if c['salesforce_url']:st.link_button('Contact Vendor / Technician in Salesforce',c['salesforce_url'],use_container_width=True)
        if c['vendor_email']:st.link_button('Email Vendor',f"mailto:{c['vendor_email']}?subject={quote('Case '+c['case_number'])}",use_container_width=True)
        if c['vendor_phone']:st.link_button('Call Vendor',f"tel:{c['vendor_phone']}",use_container_width=True);st.text_input('Vendor number — copy',c['vendor_phone'],key='phone_'+c['id'])
    if user['role']=='regular' and c['assigned_to']==user['_id']:
        st.divider();st.markdown('### Update Case')
        with st.form('upd_'+c['id']):
            s=st.selectbox('Status',STATUSES,index=STATUSES.index(c['status']) if c['status'] in STATUSES else 0);p=st.slider('Progress',0,100,c['progress'],5);n=st.text_area('Update / follow-up note');br=''
            if s=='Contract Breached':br=st.selectbox('Contract breached reason',BREACH);st.text_area('Generated vendor message — editable',breach_msg(c,br),height=150,key='msg_'+c['id'])
            if st.form_submit_button('Save Update',use_container_width=True):update_case(c['id'],user['_id'],s,p,n,br);st.success('Saved to MongoDB.');st.rerun()
    if user['role']=='admin':
        st.divider();ag=users('regular');ids=[x['_id'] for x in ag];
        if ids:
            sel=st.selectbox('Assign to',ids,index=ids.index(c['assigned_to']) if c['assigned_to'] in ids else 0,format_func=lambda x:next(f"{a['first_name']} {a['last_name']} ({a['employee_id']})" for a in ag if a['_id']==x))
            if st.button('Reassign Case'):reassign(c['id'],sel,user['_id']);st.success('Reassigned.');st.rerun()
    h=list(db().case_history.find({'case_id':c['id']}).sort('created_at',DESCENDING));
    if h:st.markdown('### Case History');st.dataframe(pd.DataFrame(h)[['created_at','action','details']],use_container_width=True,hide_index=True)

def agent_schedule(u):
    st.markdown('## My Schedule');v=st.radio('View',['Day','Week','Month'],horizontal=True);today=date.today();start=today if v=='Day' else today-timedelta(days=today.weekday()) if v=='Week' else today.replace(day=1);end=start if v=='Day' else start+timedelta(days=6) if v=='Week' else (date(start.year+1,1,1) if start.month==12 else date(start.year,start.month+1,1))-timedelta(days=1);df=schedule(u['_id'],start,end);st.dataframe(df,use_container_width=True,hide_index=True) if not df.empty else st.info('No schedule entries.')
    t=schedule(u['_id'],today,today)
    if not t.empty:
        cur=datetime.now().strftime('%H:%M');up=t[t.start_time>=cur]
        if not up.empty:st.info(f"⏰ Upcoming: **{up.iloc[0].activity}** at **{up.iloc[0].start_time}–{up.iloc[0].end_time}**")
    st.divider();st.markdown('### Leave / Schedule Request')
    with st.form('request'):
        typ=st.selectbox('Request type',REQUESTS);d=st.date_input('Date',today);s=st.time_input('Start',time(9));e=st.time_input('End',time(18));target=None;agents=userdf('regular');others=agents[agents['_id']!=u['_id']]
        if typ=='Schedule Swap' and not others.empty:target=st.selectbox('Swap with',others['_id'].tolist(),format_func=lambda x:next(f"{a['first_name']} {a['last_name']}" for a in agents.to_dict('records') if a['_id']==x))
        n=st.text_area('Notes')
        if st.form_submit_button('Submit Request',use_container_width=True):ok,msg=request(u,typ,d,s,e,target,n);st.success(msg) if ok else st.error(msg)

def admin_agents(u):
    st.markdown('## Agent Management');ag=users('regular');
    if not ag:return st.info('No regular agents.')
    st.dataframe(pd.DataFrame([{'Agent':f"{a['first_name']} {a['last_name']}",'Employee ID':a['employee_id'],'Aux':a.get('aux',''),'Active':a.get('active',True),'Active Cases':load(a['_id']),'Assigned Today':col('cases').count_documents({'assigned_to':a['_id'],'assigned_at':{'$regex':'^'+date.today().isoformat()}}),'Last Seen':a.get('last_seen','')} for a in ag]),use_container_width=True,hide_index=True)
    ids=[a['_id'] for a in ag];sel=st.selectbox('Agent',ids,format_func=lambda x:next(f"{a['first_name']} {a['last_name']} ({a['employee_id']})" for a in ag if a['_id']==x));a=col().find_one({'_id':sel});x,y,z=st.columns(3)
    with x:
        ax=st.selectbox('Aux',AUX,index=AUX.index(a.get('aux','Busy - Away')) if a.get('aux','Busy - Away') in AUX else 1)
        if st.button('Update Aux'):set_aux(sel,ax);st.rerun()
    with y:
        if a.get('active',True):
            if st.button('Kick / Set Offline'):col().update_one({'_id':sel},{'$set':{'active':False,'aux':'Offline'}});st.rerun()
        else:
            if st.button('Restore Agent'):col().update_one({'_id':sel},{'$set':{'active':True,'aux':'Busy - Away'}});st.rerun()
    with z:
        if st.button('Send Ageing Alert'):notify(sel,'Admin ageing-case alert','Please review your ageing bucket immediately.','stale');st.success('Alert sent.')
    st.markdown('### Bucket');render_cases(cases(uid=sel),u);st.markdown('### Change Role')
    role=st.selectbox('Role',['regular','admin'],index=1 if a.get('role')=='admin' else 0)
    if u['email']==SUPER and st.button('Save Role'):col().update_one({'_id':sel},{'$set':{'role':role}});st.rerun()

def admin_sched():
    st.markdown('## Agent Schedule');d=st.date_input('Schedule date',date.today());
    if st.button('Generate Break / Lunch Coverage'):auto_sched(d);st.success('Generated.');st.rerun()
    df=pd.DataFrame(list(db().schedules.find({'schedule_date':d.isoformat()})));st.dataframe(df,use_container_width=True,hide_index=True) if not df.empty else st.info('No schedules.')
    st.divider();st.markdown('### Requests');rq=requests_df();
    if rq.empty:st.info('No requests.')
    else:
        st.dataframe(rq,use_container_width=True,hide_index=True)
        for _,r in rq[rq.status=='Pending'].iterrows():
            a,b,c=st.columns([3,1,1]);a.write(f"**{r.request_type}** — {r.request_date}")
            if r.request_type=='Schedule Swap':
                if b.button('Check Swap',key='sw'+str(r['_id'])):swap(str(r['_id']));st.rerun()
            else:
                if b.button('Approve',key='ap'+str(r['_id'])):approve(str(r['_id']),True);st.rerun()
                if c.button('Reject',key='re'+str(r['_id'])):approve(str(r['_id']),False);st.rerun()
    st.divider();st.markdown('### Add Activity');ag=users('regular')
    if ag:
        with st.form('activity'):
            aid=st.selectbox('Agent',[a['_id'] for a in ag],format_func=lambda x:next(f"{a['first_name']} {a['last_name']}" for a in ag if a['_id']==x));dd=st.date_input('Date',d);s=st.time_input('Start',time(9));e=st.time_input('End',time(10));act=st.selectbox('Activity',ACTIVITIES);n=st.text_input('Notes')
            if st.form_submit_button('Save Activity'):add_sched(aid,dd,s,e,act,n);st.rerun()

def admin_reports():
    st.markdown('## Reports & Adherence');df=cases(closed=True)
    if not df.empty:st.download_button('Extract Case Report',df.to_csv(index=False).encode(),file_name='case_report.csv',mime='text/csv',use_container_width=True);st.dataframe(df,use_container_width=True,hide_index=True)
    ag=users('regular');rows=[{'Agent':f"{a['first_name']} {a['last_name']}",'Employee ID':a['employee_id'],'Daily Adherence %':adh(a['_id']),'MTD Adherence %':adh(a['_id'],True),'Attendance':a.get('attendance_status','Present'),'Aux':a.get('aux','')} for a in ag];st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True) if rows else None
    x,y=st.columns(2);x.metric('Overall Daily Adherence',f'{adh()}%');y.metric('Overall MTD Adherence',f'{adh(mtd=True)}%')

def admin_sf():
    st.markdown('## Salesforce — Admin Only');st.caption('Add Salesforce credentials later as deployment secrets; no credentials are hard-coded.')
    if st.button('Pull Latest Salesforce Cases'):
        try:
            from simple_salesforce import Salesforce
            sf=Salesforce(username=os.getenv('SF_USERNAME'),password=os.getenv('SF_PASSWORD'),security_token=os.getenv('SF_SECURITY_TOKEN'),domain=os.getenv('SF_DOMAIN','login'));q=sf.query('SELECT Id,CaseNumber,Subject,Status,Priority,CreatedDate,LastModifiedDate FROM Case ORDER BY LastModifiedDate DESC LIMIT 100');st.session_state.sf=pd.DataFrame(q['records'])
        except Exception as e:st.error(str(e))
    if 'sf' in st.session_state:st.dataframe(st.session_state.sf,use_container_width=True,hide_index=True)

def admin_settings():
    st.markdown('## Admin Settings');p=st.number_input('Default PTO allocation',min_value=0,value=15);br=st.number_input('Break minutes',min_value=0,value=15);ln=st.number_input('Lunch minutes',min_value=0,value=60);poll=st.number_input('Polling seconds',min_value=5,max_value=120,value=POLL)
    if st.button('Save Settings'):db().app_settings.update_one({'_id':'ops'},{'$set':{'pto_allocation':p,'break_minutes':br,'lunch_minutes':ln,'refresh_seconds':poll,'updated_at':now()}},upsert=True);st.success('Saved.')

indexes()
if not mongo():auth_screen();st.stop()
if 'user' not in st.session_state:auth_screen();st.stop()
u=col().find_one({'_id':st.session_state.user['_id']});st.session_state.user=u
if st.session_state.get('hb',0)+60<datetime.now().timestamp():col().update_one({'_id':u['_id']},{'$set':{'last_seen':now()}});st.session_state.hb=datetime.now().timestamp()
if st_autorefresh:st_autorefresh(interval=POLL*1000,key='realtime_poll')

st.markdown(f'<div class="appbar"><div><div class="brand">{APP}</div><div class="sub">● Live data • {datetime.now().strftime("%H:%M:%S")}</div></div><div style="text-align:right"><b>{u["first_name"]} {u["last_name"]}</b><div class="sub">{u.get("role","regular").upper()} • {u.get("employee_id","")}</div></div></div>',unsafe_allow_html=True)
if u['role']=='regular':
    generate_alerts(u)
    a,b,c=st.columns([2,5,1]);
    with a:
        ax=st.selectbox('Aux',AUX,index=AUX.index(u.get('aux','Busy - Away')) if u.get('aux','Busy - Away') in AUX else 1,key='top_aux');
        if ax!=u.get('aux'):set_aux(u['_id'],ax);st.rerun()
    with b:
        un=unread(u['_id']);
        if un:st.warning(f'🔔 {un} notification(s) need attention.')
    with c:
        if st.button('Sign Out'):st.session_state.clear();st.rerun()
else:
    st.info('Admin Aux: Admin Task')
    if st.button('Sign Out'):st.session_state.clear();st.rerun()

with st.sidebar:
    st.markdown('### Navigation')
    page=st.radio('Go to',['Dashboard','My Schedule'] if u['role']=='regular' else ['Dashboard','Agent Management','Agent Schedule','Salesforce','Reports','Settings'],key='nav')

if st.session_state.get('selected_case'):
    c=case(st.session_state.selected_case)
    if c:detail(c,u)
    else:st.session_state.selected_case=None;st.rerun()
    st.stop()

if u['role']=='regular':
    if page=='Dashboard':dashboard(u)
    else:agent_schedule(u)
else:
    {'Dashboard':lambda:dashboard(u),'Agent Management':lambda:admin_agents(u),'Agent Schedule':admin_sched,'Salesforce':admin_sf,'Reports':admin_reports,'Settings':admin_settings}[page]()
