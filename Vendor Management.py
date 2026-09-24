import os, secrets, hashlib
from datetime import datetime, date, timedelta, time as dtime
from urllib.parse import quote
import pandas as pd
import streamlit as st
from pymongo import MongoClient, ASCENDING, DESCENDING

st.set_page_config(page_title='HPE Case Operations Control Center', page_icon='📊', layout='wide', initial_sidebar_state='collapsed')
ADMIN_EMAIL='arianne-may.escabillas@hpe.com'; SF_BASE=os.getenv('SF_BASE_URL','https://hp.lightning.force.com/').rstrip('/')+'/'
STATUSES=['New','Assigned','In Progress','Waiting for Vendor','Waiting for Technician','Waiting for Customer','Pending Internal','Completed','Contract Breached','Cancelled']
AUX=['Available','Busy - Away','Break','Unscheduled Break','Lunch','In a Meeting','Coaching','Admin Task','Offline']
BREACH=['Vendor missed committed date','Vendor failed to provide update','Vendor delivered incomplete service','Vendor SLA violation','Other']
LEAVES=['PTO','Sick Leave','Emergency Leave']
ACTIVITIES=['Queue / Production','Break','Lunch','Meeting','Coaching','Admin Task','Training','Other']

st.markdown('''<style>
#MainMenu,footer,header{visibility:hidden}.block-container{max-width:100%;padding:.7rem 1.2rem 1.5rem}.app{background:linear-gradient(100deg,#081d30,#0e3a5c,#1769aa);color:white;border-radius:14px;padding:15px 20px;margin-bottom:12px}.title{font-size:1.35rem;font-weight:800}.sub{font-size:.78rem;opacity:.8}.kpi{background:white;border:1px solid #dbe4ee;border-radius:14px;padding:13px 16px;min-height:108px;box-shadow:0 2px 8px #0f172a0a}.kl{font-size:.72rem;text-transform:uppercase;font-weight:700;color:#64748b}.kv{font-size:2rem;font-weight:850;color:#172b4d}.blue{border-left:5px solid #1769aa}.red{border-left:5px solid #c62828}.yellow{border-left:5px solid #d69e00}.green{border-left:5px solid #2e7d32}.section{font-size:1.1rem;font-weight:800;color:#172b4d;margin:16px 0 8px}.stButton>button{border-radius:8px}
</style>''',unsafe_allow_html=True)

@st.cache_resource(show_spinner=False)
def mongo():
    uri=st.secrets.get('MONGO_URI',None) if hasattr(st,'secrets') else None
    uri=uri or os.getenv('MONGO_URI')
    if not uri: raise RuntimeError('MONGO_URI is not configured.')
    return MongoClient(uri,maxPoolSize=30,serverSelectionTimeoutMS=5000)

def db(): return mongo()['TeamRoster']
def C():
    d=db(); return {k:d[k] for k in ['Team Roster Collection','Cases','Case History','Schedules','Schedule Requests','Settings','Assignment Logs','Attendance','Notifications']}
@st.cache_resource(show_spinner=False)
def indexes():
    c=C(); c['Team Roster Collection'].create_index('employee_id',unique=True); c['Team Roster Collection'].create_index('email',unique=True); c['Cases'].create_index([('status',ASCENDING),('due_at',ASCENDING)]); c['Cases'].create_index([('assigned_to',ASCENDING),('status',ASCENDING)]); c['Notifications'].create_index([('user_id',ASCENDING),('read',ASCENDING)]); return True

def oid(x):
    from bson import ObjectId
    try:return ObjectId(str(x))
    except:return x

def h(p):
    s=secrets.token_bytes(16); return s.hex()+':'+hashlib.pbkdf2_hmac('sha256',p.encode(),s,220000).hex()
def vh(p,x):
    try:s,d=x.split(':'); return secrets.compare_digest(hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(s),220000).hex(),d)
    except:return False

def ud(u): return f"{u.get('first_name','')} {u.get('last_name','')}".strip()
def now(): return datetime.now()
def dt(x):
    if isinstance(x,datetime): return x
    try:return datetime.fromisoformat(str(x).replace('Z','+00:00')).replace(tzinfo=None)
    except:return None

def urgency(c):
    if c.get('status') in ['Completed','Cancelled']: return 'On Track'
    d=dt(c.get('due_at')); rem=(d-now()) if d else timedelta(days=365)
    if str(c.get('priority','')).lower()=='critical' or rem<=timedelta(hours=2): return 'Critical'
    if rem<=timedelta(hours=8): return 'Due Soon'
    return 'On Track'

def progress(status): return {'New':0,'Assigned':15,'In Progress':45,'Waiting for Vendor':55,'Waiting for Technician':55,'Waiting for Customer':55,'Pending Internal':65,'Contract Breached':80,'Completed':100,'Cancelled':100}.get(status,0)

def notify(uid,title,msg,sev='info',key=None): C()['Notifications'].insert_one({'user_id':oid(uid),'title':title,'message':msg,'severity':sev,'read':False,'dedupe_key':key,'created_at':now()})
def notices(uid): return list(C()['Notifications'].find({'user_id':oid(uid),'read':False}).sort('created_at',DESCENDING).limit(10))

def bootstrap():
    u=C()['Team Roster Collection'].find_one({'email':ADMIN_EMAIL})
    if u and u.get('role')!='admin': C()['Team Roster Collection'].update_one({'_id':u['_id']},{'$set':{'role':'admin','admin_protected':True}})

def signup(d):
    c=C()['Team Roster Collection']; email=d['email'].strip().lower()
    if not email.endswith('@hpe.com'): return False,'Use an HPE email address.'
    if c.find_one({'$or':[{'employee_id':d['employee_id'].strip()},{'email':email}]}): return False,'Employee ID or email already exists.'
    role='admin' if email==ADMIN_EMAIL else 'regular'; aux='Admin Task' if role=='admin' else 'Busy - Away'
    c.insert_one({**d,'email':email,'employee_id':d['employee_id'].strip(),'password_hash':h(d.pop('password')),'role':role,'aux':aux,'active':True,'pto_allocation':15,'created_at':now(),'last_seen':now(),'admin_protected':role=='admin'})
    return True,'Account created. You can now sign in.'

def login(e,p):
    u=C()['Team Roster Collection'].find_one({'employee_id':e.strip(),'active':True})
    if u and vh(p,u.get('password_hash','')):
        C()['Team Roster Collection'].update_one({'_id':u['_id']},{'$set':{'last_seen':now()}}); return u

def cases(uid=None):
    q={'status':{'$nin':['Completed','Cancelled']}}; q.update({'assigned_to':oid(uid)} if uid else {})
    rows=[]
    for c in C()['Cases'].find(q).sort('due_at',ASCENDING):
        c['_id']=str(c['_id']); c['urgency']=urgency(c); c['progress']=c.get('progress',progress(c.get('status'))); rows.append(c)
    return pd.DataFrame(rows)

def load(uid): return C()['Cases'].count_documents({'assigned_to':oid(uid),'status':{'$nin':['Completed','Cancelled']}})
def dayassign(uid): return C()['Assignment Logs'].count_documents({'agent_id':oid(uid),'assignment_day':date.today().isoformat()})
def available(): return list(C()['Team Roster Collection'].find({'role':'regular','active':True,'aux':'Available'}))
def fair_agent():
    a=available();
    if not a:return None
    return sorted(a,key=lambda u:(dayassign(u['_id']),load(u['_id']),u.get('last_assigned_at',datetime.min)))[0]

def assign(cid,actor=None):
    c=C()['Cases']; case=c.find_one({'_id':oid(cid)}); a=fair_agent()
    if not case:return False,'Case not found'
    if case.get('assigned_to'):return True,'Already assigned'
    if not a:return False,'No Available agent'
    t=now(); r=c.update_one({'_id':case['_id'],'assigned_to':None},{'$set':{'assigned_to':a['_id'],'status':'Assigned','updated_at':t,'last_agent_update':t}})
    if r.modified_count:
        C()['Assignment Logs'].insert_one({'case_id':case['_id'],'agent_id':a['_id'],'assignment_day':t.date().isoformat(),'assigned_at':t,'actor_id':oid(actor) if actor else None}); C()['Team Roster Collection'].update_one({'_id':a['_id']},{'$set':{'last_assigned_at':t}}); C()['Team Roster Collection']; notify(a['_id'],'New Case Assigned',f"Case {case['case_number']} was assigned to you.",'critical' if urgency(case)=='Critical' else 'info')
    return True,ud(a)

def update_case(cid,uid,status,prog,note='',reason=None):
    c=C()['Cases']; t=now(); x={'status':status,'progress':int(prog),'updated_at':t,'last_agent_update':t}
    if status=='Contract Breached': x.update(contract_breached=True,breach_reason=reason)
    c.update_one({'_id':oid(cid)},{'$set':x}); C()['Case History'].insert_one({'case_id':oid(cid),'actor_id':oid(uid),'action':'Case Updated','details':note or f'Status changed to {status}.','created_at':t})

def reassign(cid,aid,admin):
    c=C()['Cases']; t=now(); case=c.find_one({'_id':oid(cid)}); a=C()['Team Roster Collection'].find_one({'_id':oid(aid)})
    if not case or not a:return
    c.update_one({'_id':case['_id']},{'$set':{'assigned_to':a['_id'],'status':'Assigned','updated_at':t}}); C()['Assignment Logs'].insert_one({'case_id':case['_id'],'agent_id':a['_id'],'assigned_at':t,'assignment_day':t.date().isoformat(),'manual_reassignment':True,'actor_id':oid(admin)}); notify(a['_id'],'Case Reassigned',f"Case {case['case_number']} was assigned to you.");

def breach_msg(c,r): return f"Hello {c.get('vendor') or 'the assigned vendor'},\n\nThis is a follow-up regarding case {c.get('case_number')} ({c.get('subject')}). The committed delivery date was {c.get('due_at')}. Our records indicate a contract/SLA violation: {r}.\n\nPlease provide an immediate status update and recovery plan.\n\nThank you."
def sfurl(c): return c.get('salesforce_url') or (f"{SF_BASE}lightning/r/Case/{c['salesforce_id']}/view" if c.get('salesforce_id') else SF_BASE)

def schedule(uid,start,end):
    return list(C()['Schedules'].find({'user_id':oid(uid),'schedule_date':{'$gte':start.isoformat(),'$lte':end.isoformat()}}).sort([('schedule_date',ASCENDING),('start_time',ASCENDING)]))
def gen_schedule(uid,d):
    if schedule(uid,d,d):return
    s=datetime.combine(d,dtime(9)); e=datetime.combine(d,dtime(18)); blocks=[(s,s+timedelta(hours=2),'Queue / Production'),(s+timedelta(hours=2),s+timedelta(hours=2,minutes=15),'Break'),(s+timedelta(hours=2,minutes=15),s+timedelta(hours=4,minutes=15),'Queue / Production'),(s+timedelta(hours=4,minutes=15),s+timedelta(hours=5,minutes=15),'Lunch'),(s+timedelta(hours=5,minutes=15),s+timedelta(hours=7,minutes=15),'Queue / Production'),(s+timedelta(hours=7,minutes=15),s+timedelta(hours=7,minutes=30),'Break'),(s+timedelta(hours=7,minutes=30),e,'Queue / Production')]
    C()['Schedules'].insert_many([{'user_id':oid(uid),'schedule_date':d.isoformat(),'start_time':a.strftime('%H:%M'),'end_time':b.strftime('%H:%M'),'activity':x,'auto_generated':True,'created_at':now()} for a,b,x in blocks])
def pto_ok(uid,d):
    u=C()['Team Roster Collection'].find_one({'_id':oid(uid)}); alloc=int(u.get('pto_allocation',15)); used=C()['Schedule Requests'].count_documents({'user_id':oid(uid),'request_type':'Leave','leave_type':'PTO','status':'Approved','request_date':{'$gte':f'{d.year}-01-01','$lte':f'{d.year}-12-31'}}); return used<alloc
def request(uid,typ,d,start=None,end=None,target=None,leave=None,notes=''):
    r={'user_id':oid(uid),'request_type':typ,'request_date':d.isoformat(),'start_time':start.strftime('%H:%M') if start else None,'end_time':end.strftime('%H:%M') if end else None,'target_agent_id':oid(target) if target else None,'leave_type':leave,'notes':notes,'status':'Pending','created_at':now()}; x=C()['Schedule Requests'].insert_one(r)
    if typ=='Leave' and (leave in ['Sick Leave','Emergency Leave'] or (leave=='PTO' and pto_ok(uid,d))): C()['Schedule Requests'].update_one({'_id':x.inserted_id},{'$set':{'status':'Approved','approved_at':now()}}); r['status']='Approved'
    elif typ=='Leave' and leave=='PTO': C()['Schedule Requests'].update_one({'_id':x.inserted_id},{'$set':{'status':'Rejected','rejection_reason':'No allocation for the selected date.'}}); r['status']='Rejected'
    for a in C()['Team Roster Collection'].find({'role':'admin','active':True}): notify(a['_id'],'New Request',f"{typ} request submitted for {d}")
    return x.inserted_id,r['status']

def metrics(uid=None,mtd=False):
    q={}; q['user_id']=oid(uid) if uid else {'$exists':True}; q['date']={'$gte':(date.today().replace(day=1) if mtd else date.today()).isoformat(),'$lte':date.today().isoformat()}; ev=list(C()['Attendance'].find(q)); unexpected=sum(e.get('aux')=='Unscheduled Break' for e in ev); return 100.0, max(0,100-unexpected*2)

def render_case_list(df,user):
    if df.empty: st.info('No cases found.'); return
    df=df.copy(); df['_r']=df.urgency.map({'Critical':0,'Due Soon':1,'On Track':2}); df=df.sort_values(['_r','due_at'],na_position='last')
    for _,r in df.iterrows():
        icon={'Critical':'🔴','Due Soon':'🟡','On Track':'🟢'}[r.urgency]; last=dt(r.get('last_agent_update')); last=last.strftime('%b %d %I:%M %p') if last else '—'
        with st.container(border=True):
            a,b,c,d,e=st.columns([.8,3.2,1.2,1.5,.9]); a.markdown(f'### {icon}'); b.markdown(f"**{r.case_number} — {r.subject}**  \n{r.get('customer') or 'No customer'} • {r.status} • Last update: {last}"); c.metric('Progress',f"{r.progress}%"); d.write(f"**Due**\n{r.get('due_at') or '—'}");
            if e.button('Open',key='open_'+r['_id']):st.session_state['selected_case']=r['_id']; st.rerun()

def kpis(df):
    vals=[('Total Active Cases',len(df),'blue',None),('Critical',int((df.urgency=='Critical').sum()) if not df.empty else 0,'red','Critical'),('Due Soon',int((df.urgency=='Due Soon').sum()) if not df.empty else 0,'yellow','Due Soon'),('On Track',int((df.urgency=='On Track').sum()) if not df.empty else 0,'green','On Track')]; cols=st.columns(4)
    for i,(n,v,cl,f) in enumerate(vals):
        with cols[i]: st.markdown(f'<div class="kpi {cl}"><div class="kl">{n}</div><div class="kv">{v}</div></div>',unsafe_allow_html=True); st.button('View '+n,key='k'+str(i),use_container_width=True,on_click=lambda x=f:st.session_state.update(kpi_filter=x))

def detail(cid,user):
    c=C()['Cases'].find_one({'_id':oid(cid)}); 
    if not c:return
    if st.button('← Back'):st.session_state.pop('selected_case',None);st.rerun()
    st.markdown(f"## {c['case_number']} — {c['subject']}"); a,b,c1,d=st.columns(4); a.metric('Urgency',urgency(c)); b.metric('Status',c.get('status')); c1.metric('Progress',f"{c.get('progress',progress(c.get('status')))}%"); d.metric('Last Update',dt(c.get('last_agent_update')).strftime('%Y-%m-%d %H:%M') if dt(c.get('last_agent_update')) else '—'); st.progress(c.get('progress',0)/100)
    l,r=st.columns([1.5,1]);
    with l:
        for k,label in [('customer','Customer'),('vendor','Vendor'),('technician','Technician'),('priority','Priority'),('due_at','Due'),('description','Description')]:st.write(f"**{label}:** {c.get(k) or '—'}")
        st.markdown(f'[Open / Contact through Salesforce Case]({sfurl(c)})')
        email=c.get('vendor_email'); phone=c.get('vendor_phone');
        if email: st.markdown(f'<a href="mailto:{quote(email)}?subject={quote("Case "+c["case_number"]+" Follow-up")}"><button style="padding:8px;width:100%">✉️ Email Vendor / Technician</button></a>',unsafe_allow_html=True)
        if phone: st.markdown(f"<button onclick=\"navigator.clipboard.writeText('{str(phone).replace(chr(39),chr(92)+chr(39))}')\" style='padding:8px;width:100%;margin-top:6px'>📞 Copy Vendor Number</button>",unsafe_allow_html=True)
    with r:
        if user['role']=='regular':
            with st.form('update_case'):
                s=st.selectbox('Status',STATUSES,index=STATUSES.index(c.get('status')) if c.get('status') in STATUSES else 0); p=st.slider('Progress',0,100,int(c.get('progress',0))); note=st.text_area('Update note'); br=None; msg=''
                if s=='Contract Breached':br=st.selectbox('Contract breach reason',BREACH);msg=st.text_area('Generated message',breach_msg(c,br),height=220)
                if st.form_submit_button('Save Case Update',use_container_width=True):update_case(cid,user['_id'],s,p,note,br);st.success('Saved.');st.rerun()
            if c.get('vendor_email'):
                msg=breach_msg(c,c.get('breach_reason') or 'Contract/SLA violation'); st.markdown(f'<a href="mailto:{quote(c["vendor_email"])}?subject={quote("Contract Breach - "+c["case_number"])}&body={quote(msg)}"><button style="padding:8px;width:100%;margin-top:6px">✉️ Email Contract Breach Message</button></a>',unsafe_allow_html=True)
        else:
            agents=list(C()['Team Roster Collection'].find({'role':'regular','active':True}).sort('last_name',ASCENDING)); labels={str(a['_id']):ud(a) for a in agents}; ids=list(labels)
            if ids:
                cur=str(c.get('assigned_to')) if c.get('assigned_to') else None; sel=st.selectbox('Assigned agent',ids,index=ids.index(cur) if cur in ids else 0,format_func=lambda x:labels[x]);
                if st.button('Reassign Case',use_container_width=True):reassign(cid,sel,user['_id']);st.success('Reassigned.');st.rerun()
    h=list(C()['Case History'].find({'case_id':oid(cid)}).sort('created_at',DESCENDING).limit(100));
    if h:st.dataframe(pd.DataFrame([{'Date':x.get('created_at'),'Action':x.get('action'),'Details':x.get('details')} for x in h]),use_container_width=True,hide_index=True)

def schedule_view(user):
    st.markdown('## My Schedule'); v=st.radio('View',['Day','Week','Month'],horizontal=True); today=date.today(); start=today if v=='Day' else today-timedelta(days=today.weekday()) if v=='Week' else today.replace(day=1); end=start if v=='Day' else start+timedelta(days=6) if v=='Week' else (date(today.year+1,1,1)-timedelta(days=1) if today.month==12 else date(today.year,today.month+1,1)-timedelta(days=1)); rows=schedule_view_data(user['_id'],start,end); st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True) if rows else st.info('No schedule.')
    st.markdown('### Submit Leave / Schedule Request'); agents=list(C()['Team Roster Collection'].find({'role':'regular','active':True,'_id':{'$ne':user['_id']}})); labels={str(a['_id']):ud(a) for a in agents}
    with st.form('request'):
        typ=st.selectbox('Request type',['Leave','Schedule Swap','Schedule Change']); d=st.date_input('Date',today); leave=st.selectbox('Leave type',LEAVES) if typ=='Leave' else None; start_t=st.time_input('Start',dtime(9)); end_t=st.time_input('End',dtime(18)); target=st.selectbox('Swap with',list(labels),format_func=lambda x:labels[x]) if typ=='Schedule Swap' and labels else None; notes=st.text_area('Notes')
        if st.form_submit_button('Submit Request',use_container_width=True):
            rid,status=request(user['_id'],typ,d,start_t,end_t,target,leave,notes); 
            if typ=='Schedule Swap' and target: C()['Schedule Requests'].update_one({'_id':rid},{'$set':{'status':'Approved'}});notify(oid(target),'Schedule Swap',f"{ud(user)} requested a swap for {d}.");status='Approved'
            st.error('No allocation for the selected date.') if status=='Rejected' else st.success('Automatically approved.' if status=='Approved' else 'Request submitted to admin.')

def schedule_view_data(uid,s,e): return [{'Date':x.get('schedule_date'),'Start':x.get('start_time'),'End':x.get('end_time'),'Activity':x.get('activity'),'Notes':x.get('notes','')} for x in schedule(uid,s,e)]

def agent_dash(user):
    for n in notices(user['_id']):
        st.warning(f"{n['title']}: {n['message']}" if n.get('severity')!='critical' else f"🔴 {n['title']}: {n['message']}")
    q=st.text_input('Search my cases',placeholder='Case number, subject, customer, vendor…'); df=cases(user['_id']);
    if q and not df.empty:
        q=q.lower();df=df[df.apply(lambda r:q in str(r.get('case_number','')).lower() or q in str(r.get('subject','')).lower() or q in str(r.get('customer','')).lower() or q in str(r.get('vendor','')).lower(),axis=1)]
    kpis(df); f=st.session_state.get('kpi_filter'); df=df[df.urgency==f] if f else df; st.markdown('<div class="section">My Active Cases</div>',unsafe_allow_html=True);render_case_list(df,user); st.markdown('<div class="section">Today\'s Schedule</div>',unsafe_allow_html=True); rows=schedule_view_data(user['_id'],date.today(),date.today());
    if not rows:gen_schedule(user['_id'],date.today());rows=schedule_view_data(user['_id'],date.today(),date.today())
    st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    da,dd=metrics(user['_id']);ma,md=metrics(user['_id'],True); a,b,c,d=st.columns(4);a.metric('Daily Attendance',f'{da:.1f}%');b.metric('Daily Adherence',f'{dd:.1f}%');c.metric('MTD Attendance',f'{ma:.1f}%');d.metric('MTD Adherence',f'{md:.1f}%')

def agent_aux(user):
    x=st.sidebar.selectbox('My Aux',AUX,index=AUX.index(user.get('aux','Busy - Away')) if user.get('aux') in AUX else 1)
    if x!=user.get('aux'):C()['Team Roster Collection'].update_one({'_id':user['_id']},{'$set':{'aux':x,'last_seen':now()}});C()['Attendance'].insert_one({'user_id':user['_id'],'aux':x,'date':date.today().isoformat(),'timestamp':now()});st.rerun()

def admin_dash(user):
    q=st.text_input('Search all active cases',placeholder='Case number, subject, customer, vendor…');df=cases();
    if q and not df.empty:
        q=q.lower();df=df[df.apply(lambda r:q in str(r.get('case_number','')).lower() or q in str(r.get('subject','')).lower() or q in str(r.get('customer','')).lower() or q in str(r.get('vendor','')).lower(),axis=1)]
    kpis(df);f=st.session_state.get('kpi_filter');df=df[df.urgency==f] if f else df;st.markdown('<div class="section">All Active Cases</div>',unsafe_allow_html=True);render_case_list(df,user);st.markdown('<div class="section">Agent Distribution & Aux</div>',unsafe_allow_html=True); agent_table();
    a,b=metrics();ma,md=metrics(mtd=True);c1,c2,c3,c4=st.columns(4);c1.metric('Overall Daily Attendance',f'{a:.1f}%');c2.metric('Overall Daily Adherence',f'{b:.1f}%');c3.metric('Overall MTD Attendance',f'{ma:.1f}%');c4.metric('Overall MTD Adherence',f'{md:.1f}%')

def agent_table():
    rows=[]
    for u in C()['Team Roster Collection'].find({'role':'regular'}):rows.append({'Agent':ud(u),'Employee ID':u.get('employee_id'),'Aux':u.get('aux'),'Active Cases':load(u['_id']),'Today Assigned':dayassign(u['_id']),'Active':u.get('active',True)})
    st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)

def admin_agents(user):
    agent_table(); agents=list(C()['Team Roster Collection'].find({'role':'regular'}));labels={str(a['_id']):ud(a) for a in agents};
    if not labels:return
    sel=st.selectbox('Agent',list(labels),format_func=lambda x:labels[x]);a=C()['Team Roster Collection'].find_one({'_id':oid(sel)});st.write(f"Aux: **{a.get('aux')}** • Active Cases: **{load(a['_id'])}** • Today Assigned: **{dayassign(a['_id'])}**")
    x,y,z=st.columns(3)
    if x.button('Kick / Offline',use_container_width=True):C()['Team Roster Collection'].update_one({'_id':a['_id']},{'$set':{'active':False,'aux':'Offline'}});notify(a['_id'],'Offline','You were set Offline by an admin.');st.rerun()
    if y.button('Restore',use_container_width=True):C()['Team Roster Collection'].update_one({'_id':a['_id']},{'$set':{'active':True,'aux':'Busy - Away'}});st.rerun()
    if z.button('Send Ageing Alert',use_container_width=True):notify(a['_id'],'Ageing Case Alert',f'Please review cases with no update for 24+ hours.','warning');st.success('Alert sent.')
    render_case_list(cases(a['_id']),user)

def admin_schedule(user):
    st.markdown('## Agent Schedule'); agents=list(C()['Team Roster Collection'].find({'role':'regular'}));labels={str(a['_id']):ud(a) for a in agents};
    if agents:
        aid=st.selectbox('Agent',list(labels),format_func=lambda x:labels[x]);d=st.date_input('Date',date.today());x,y=st.columns(2)
        if x.button('Generate Default Schedule',use_container_width=True):gen_schedule(oid(aid),d);st.rerun()
        if y.button('Send Schedule Alert',use_container_width=True):notify(oid(aid),'Schedule Reminder',f'Please follow your plotted schedule for {d}.');st.success('Alert sent.')
        st.dataframe(pd.DataFrame(schedule_view_data(oid(aid),d,d)),use_container_width=True,hide_index=True)
    st.markdown('### Requests'); req=list(C()['Schedule Requests'].find({}).sort('created_at',DESCENDING).limit(100));
    if req:
        st.dataframe(pd.DataFrame([{'ID':str(r['_id']),'Agent':ud(C()['Team Roster Collection'].find_one({'_id':r['user_id']}) or {}),'Type':r.get('request_type'),'Leave':r.get('leave_type'),'Date':r.get('request_date'),'Status':r.get('status')} for r in req]),use_container_width=True,hide_index=True)
        for r in [x for x in req if x.get('status')=='Pending']:
            a,b=st.columns(2)
            if a.button('Approve',key='ap'+str(r['_id'])):C()['Schedule Requests'].update_one({'_id':r['_id']},{'$set':{'status':'Approved','approved_at':now()}});notify(r['user_id'],'Request Approved',f"Your request for {r.get('request_date')} was approved.");st.rerun()
            if b.button('Reject',key='re'+str(r['_id'])):C()['Schedule Requests'].update_one({'_id':r['_id']},{'$set':{'status':'Rejected'}});notify(r['user_id'],'Request Rejected',f"Your request for {r.get('request_date')} was rejected.");st.rerun()
    st.markdown('### Add Activity')
    if agents:
        with st.form('activity'):
            aid=st.selectbox('Agent',[str(a['_id']) for a in agents],format_func=lambda x:labels[x]);d=st.date_input('Date',date.today());s=st.time_input('Start',dtime(9));e=st.time_input('End',dtime(10));act=st.selectbox('Activity',ACTIVITIES);notes=st.text_input('Notes')
            if st.form_submit_button('Add Activity',use_container_width=True):C()['Schedules'].insert_one({'user_id':oid(aid),'schedule_date':d.isoformat(),'start_time':s.strftime('%H:%M'),'end_time':e.strftime('%H:%M'),'activity':act,'notes':notes,'created_at':now()});notify(oid(aid),'Schedule Updated',f'{act} was added for {d}.');st.success('Added.')

def admin_users(user):
    if user.get('email','').lower()!=ADMIN_EMAIL:return st.error('Restricted to the designated admin.')
    us=list(C()['Team Roster Collection'].find({}));st.dataframe(pd.DataFrame([{'ID':str(u['_id']),'Name':ud(u),'Employee ID':u.get('employee_id'),'Email':u.get('email'),'Role':u.get('role'),'Aux':u.get('aux'),'Active':u.get('active')} for u in us]),use_container_width=True,hide_index=True);labels={str(u['_id']):ud(u) for u in us};sel=st.selectbox('User',list(labels),format_func=lambda x:labels[x]);u=C()['Team Roster Collection'].find_one({'_id':oid(sel)});role=st.selectbox('Role',['regular','admin'],index=1 if u.get('role')=='admin' else 0)
    if st.button('Save Role',use_container_width=True):
        if u.get('email','').lower()==ADMIN_EMAIL and role!='admin':st.error('Designated admin cannot be demoted.')
        else:C()['Team Roster Collection'].update_one({'_id':u['_id']},{'$set':{'role':role}});st.success('Role saved.');st.rerun()

def admin_sf():
    st.markdown('## Salesforce / External Data');st.markdown(f'[Open Salesforce]({SF_BASE})');st.caption('Admin-only. Add SF credentials later through Streamlit secrets/environment variables.')
    st.code('SF_BASE_URL=https://hp.lightning.force.com/\nSF_USERNAME=...\nSF_PASSWORD=...\nSF_SECURITY_TOKEN=...\nSF_DOMAIN=login')

def reports():
    rows=[]
    for c in C()['Cases'].find({}):rows.append({'Case':c.get('case_number'),'Subject':c.get('subject'),'Status':c.get('status'),'Progress':c.get('progress',0),'Urgency':urgency(c),'Priority':c.get('priority'),'Due':c.get('due_at'),'Last Update':c.get('last_agent_update'),'Assigned':str(c.get('assigned_to') or ''),'Source':c.get('source')})
    if rows:
        df=pd.DataFrame(rows);st.dataframe(df,use_container_width=True,hide_index=True);st.download_button('Extract Case Report CSV',df.to_csv(index=False).encode(),f'case_report_{date.today()}.csv','text/csv',use_container_width=True)
    st.markdown('### WFM Settings');a,b,c=st.columns(3);pto=a.number_input('Default PTO allocation',0,int(db()['Settings'].find_one({'key':'pto'}) .get('value',15) if db()['Settings'].find_one({'key':'pto'}) else 15));br=b.number_input('Break minutes',0,15);lu=c.number_input('Lunch minutes',0,60)
    if st.button('Save WFM Settings',use_container_width=True):
        for k,v in [('pto',pto),('break',br),('lunch',lu)]:C()['Settings'].update_one({'key':k},{'$set':{'value':v}},upsert=True)
        st.success('Settings saved.')

def auth():
    st.markdown('<div style="max-width:700px;margin:8vh auto;text-align:center"><h1>HPE Case Operations Control Center</h1><p style="color:#64748b">Case tracking • Auto assignment • Workforce scheduling • Reporting</p></div>',unsafe_allow_html=True)
    if 'auth_action' not in st.session_state:st.session_state.auth_action='Sign In'
    a,b=st.columns(2)
    if a.button('Sign In',use_container_width=True,type='primary'):st.session_state.auth_action='Sign In'
    if b.button('Sign Up',use_container_width=True):st.session_state.auth_action='Sign Up'
    if st.session_state.auth_action=='Sign In':
        with st.form('login'):
            e=st.text_input('Employee ID');p=st.text_input('Account Password',type='password')
            if st.form_submit_button('Sign In',use_container_width=True):
                u=login(e,p)
                if u:st.session_state.user=u;st.rerun()
                else:st.error('Invalid account or password.')
    else:
        with st.form('signup'):
            a,b=st.columns(2);fn=a.text_input('First Name *');ln=b.text_input('Last Name *');eid=a.text_input('Employee ID *');email=b.text_input('HPE Email *');bd=a.date_input('Birthday *',date(1995,1,1),min_value=date(1900,1,1),max_value=date.today());phone=b.text_input('Contact Number *');addr=st.text_area('Home Address *');pw=a.text_input('Account Password *',type='password');cp=b.text_input('Confirm Password *',type='password')
            if st.form_submit_button('Create Account',use_container_width=True):
                if not all([fn,ln,eid,email,phone,addr,pw,cp]):st.error('Complete all required fields.')
                elif pw!=cp:st.error('Passwords do not match.')
                elif len(pw)<10:st.error('Password must be at least 10 characters.')
                else:
                    d={'first_name':fn,'last_name':ln,'employee_id':eid,'email':email,'birthday':bd.isoformat(),'home_address':addr,'contact_number':phone,'password':pw};ok,msg=signup(d);st.success(msg) if ok else st.error(msg)

try:indexes();bootstrap()
except Exception as e:st.error('MongoDB setup failed.');st.code(str(e));st.stop()
if 'user' not in st.session_state:auth();st.stop()
user=C()['Team Roster Collection'].find_one({'_id':oid(st.session_state.user['_id'])})
if not user or not user.get('active',True):st.session_state.pop('user',None);st.error('Account inactive.');st.stop()
st.session_state.user=user
if user['role']=='admin':
    C()['Team Roster Collection'].update_one({'_id':user['_id']},{'$set':{'aux':'Admin Task'}});user['aux']='Admin Task'
else:agent_aux(user)

st.markdown(f'<div class="app"><div class="title">HPE Case Operations Control Center</div><div class="sub">{ud(user)} • {user.get("employee_id")} • {user.get("role","").upper()} • {user.get("aux","")} • Live polling region</div></div>',unsafe_allow_html=True)
with st.sidebar:
    st.markdown('### Navigation')
    nav=st.radio('Go to',['Dashboard','My Bucket','My Schedule'] if user['role']=='regular' else ['Dashboard','Agent Aux & Buckets','Agent Schedule','User & Roles','Salesforce','Reports'])
    if st.button('Sign Out',use_container_width=True):st.session_state.clear();st.rerun()

try:frag=st.fragment
except AttributeError:frag=None

def run(fn):
    if frag:
        @frag(run_every=f'{int(os.getenv("AUTO_REFRESH_SECONDS","15"))}s')
        def x():fn()
        x()
    else:fn()

if st.session_state.get('selected_case'):run(lambda:detail(st.session_state.selected_case,user));st.stop()
if user['role']=='regular':
    {'Dashboard':lambda:agent_dash(user),'My Bucket':lambda:render_case_list(cases(user['_id']),user),'My Schedule':lambda:schedule_view(user)}[nav]()
else:
    {'Dashboard':lambda:admin_dash(user),'Agent Aux & Buckets':lambda:admin_agents(user),'Agent Schedule':lambda:admin_schedule(user),'User & Roles':lambda:admin_users(user),'Salesforce':admin_sf,'Reports':reports}[nav]()
