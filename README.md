# HPE Team Operations Control Center

## MongoDB

The app uses the requested database structure:

```python
client = get_mongo_client()
db = client["TeamRoster"]
collection = db["Team Roster Collection"]
```

Set `MONGODB_URI` in the environment/deployment secrets. The app creates indexes and these collections: `Team Roster Collection`, `cases`, `case_history`, `notifications`, `schedules`, `schedule_requests`, `attendance`, and `app_settings`.

## Run

```bash
pip install -r requirements_mongodb.txt
streamlit run hpe_team_operations_app.py
```

## Included

- Popup Sign In / Sign Up
- HPE email validation
- Passwords saved as salted PBKDF2 hashes
- `arianne-may.escabillas@hpe.com` automatically bootstrapped as admin
- Super-admin role changes for other users
- Regular-agent default aux: `Busy - Away`
- Admin default aux: `Admin Task`
- `Available`, `Busy - Away`, `Break`, `Unscheduled Break`, `Lunch`, `In a Meeting`, `Coaching`, `Admin Task`, `Offline`
- Searchable task/case dashboard
- Total Active / Critical / Due Soon / On Track KPI tiles
- Clickable KPI filters
- Urgency sorting and red/yellow/green visual treatment
- Task progress and last update
- Agent availability/current aux/current active load/assigned-today distribution
- Automatic assignment only to available agents
- Fair assignment based on active load, assigned-today count and assignment timestamp
- Agent case alerts for newly assigned, critical, due-soon and 24-hour stale cases
- Status/progress updates
- Contract-breach reason + editable generated vendor message
- Salesforce case link, email link and vendor call link/number copy field
- Admin agent kick/offline and restore controls
- Admin bucket view and ageing alerts
- Admin reassignment
- Admin-only Salesforce pull
- CSV extraction
- Daily and MTD adherence/attendance views
- Agent day/week/month schedules
- Automatic break/lunch schedule generation with staggered coverage
- Admin schedule/activity editing
- PTO allocation check with exact no-allocation error
- Sick Leave and Emergency Leave auto-approval
- Schedule swap approval once both agents agree, without further admin approval
- Admin notifications for submitted requests and processed approvals
- Retractable sidebar
- Wide modern TV/mirror-cast layout
- Lightweight polling with stable Streamlit session state so polling does not intentionally reset the agent's current activity
- MongoDB indexes for common case/assignment/schedule queries

## Realtime / performance

Default polling is 15 seconds. Change with `REFRESH_SECONDS`. The app keeps selected case, navigation and search/filter state in `st.session_state`; heartbeat writes are throttled. For very large deployments, use MongoDB change streams/background workers and a push layer rather than high-frequency Streamlit polling.

## Salesforce

Admin-only. Add later through secrets:

```text
SF_USERNAME
SF_PASSWORD
SF_SECURITY_TOKEN
SF_DOMAIN=login
```

The Salesforce code is isolated in the admin page so your Salesforce URL/API mapping can be replaced without changing the agent dashboard.

## Attendance/adherence source

Populate `attendance` with records like:

```json
{
  "user_id": "<mongo user id>",
  "date": "2026-09-24",
  "planned_minutes": 480,
  "adherent_minutes": 450,
  "attendance_status": "Present"
}
```

The app calculates daily and MTD adherence from those records.

## Production requirements

Use HPE-approved SSO, encrypted/controlled storage for employee personal data, TLS, least-privilege MongoDB credentials, enterprise email/notification services, Salesforce OAuth/Connected App, audit/retention controls, and an atomic queue-claim/transaction mechanism for concurrent auto-assignment workers. The provided assignment algorithm is an MVP implementation of the requested fairness rules.
