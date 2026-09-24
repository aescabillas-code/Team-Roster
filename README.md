
# HPE Case Operations Control Center — Streamlit MVP

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

The app creates `case_control_center.db` automatically.

## Included in this MVP

- Mandatory sign-in and account creation
- Regular and admin role separation
- Employee profile fields requested in the specification
- Secure password hashing with PBKDF2 (do not use this SQLite/demo auth as a substitute for enterprise SSO)
- Modern responsive dashboard designed for wide/TV display
- Retractable Streamlit sidebar
- Search
- KPI tiles for Total Active, Critical, Due Soon and On Track
- Clickable KPI filtering
- Active-case list sorted by urgency
- Red/yellow/green urgency treatment
- Case detail view and history
- Regular-agent case bucket
- Agent case status updates
- Contract breach tagging and reason
- Salesforce case link
- Optional Salesforce pull for admins
- Auto-assignment to available agents using least-active-load logic
- Agent aux states, including Unscheduled Break
- Admin agent aux monitoring
- Admin ability to take an agent out of assignment / restore them
- Admin case reassignment
- Agent alerts for critical, due-soon and 24-hour stale cases
- Schedule tab for agents
- PTO / schedule / swap request capture
- Admin schedule request approval/rejection
- Admin activity creation
- CSV report extraction
- Automatic UI polling for near-real-time database updates

## Important production changes

This is a functional MVP scaffold, not a production HPE deployment. Before production:

1. Replace local password authentication with HPE-approved SSO/identity provider.
2. Store employee personal information in an approved encrypted database with proper retention and access controls.
3. Use PostgreSQL/Azure SQL/etc. rather than SQLite for concurrent users.
4. Implement transactional queue locking for auto-assignment so two app instances cannot assign the same case simultaneously.
5. Add a background worker/event consumer for true event-driven Salesforce ingestion.
6. Add Salesforce OAuth / Connected App and field mapping approved by your Salesforce administrators.
7. Add email/Teams notifications through an approved enterprise connector/service.
8. Add audit logging, permission checks, CSRF/session hardening and security monitoring.
9. Implement the exact workforce-management rules for breaks/lunch, hourly queue coverage, PTO allocation and swap approval.
10. Deploy behind HTTPS and your organization's identity/security controls.

## Salesforce environment variables

Example:

```bash
SF_USERNAME="service.account@hpe.com"
SF_PASSWORD="..."
SF_SECURITY_TOKEN="..."
SF_DOMAIN="login"
```

For Streamlit Cloud or another deployment platform, put these in the platform's secret manager rather than in source code.

## Real-time behavior

The dashboard polls the database every 15 seconds using `streamlit-autorefresh`. This means users do not manually refresh the browser. For true real-time production behavior, use an event/queue mechanism or database change notifications and push updates through an appropriate service.

## Automatic assignment

A new case is assigned only to active regular agents whose aux is `Available`. The current MVP chooses the available agent with the lowest active-case load. The assignment logic should be replaced with your actual queue/WFM rules, including skills, priority, language, shift, concurrency and coverage requirements.

## Privacy

The signup form collects birthday, home address and phone number because they were part of the requested specification. In a real enterprise application, confirm that each field is necessary, provide the appropriate privacy notice, restrict access, encrypt sensitive data and follow the organization's retention policy.
