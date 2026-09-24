# HPE CaseFlow — Streamlit build

## Included
- Modern HPE CaseFlow interface based on the supplied sign-in/sign-up and agent/admin reference images.
- Mandatory sign-in and sign-up.
- `TeamRoster` MongoDB database.
- Configurable roster collection; default is `roster_list`.
- Bootstrap admin:
  - Email: `arianne-may.escabillas@hpe.com`
  - Password: `Escabillas1993`
  - Employee ID: `60187999`
- Role-based regular-agent and admin views.
- Real-time presence/AUX polling through a short-lived MongoDB `presence` collection.
- Automatic case assignment to currently `Active` regular agents using a fairness sort based on assigned-today count, active load, and last assignment time.
- Critical/due-soon/stale-case alerts.
- Case status/progress updates and audit logging.
- Vendor/technician email, call/copy-number, Salesforce launch point, and contract-breach message generation.
- Agent schedule, automatic break/lunch template, schedule requests, leave requests, PTO allocation, and schedule swaps.
- Admin agent controls, reassignment, reports, CSV export, Salesforce integration placeholder, and role management.
- Realtime daily/MTD adherence and attendance framework.
- Streamlit menu/footer/deploy controls hidden and collapsible sidebar.
- Heavy reads are cached briefly and the live presence/assignment checks are isolated in Streamlit fragments to avoid full-page reloads on every poll.

## MongoDB setup

Add a secret:

```toml
# .streamlit/secrets.toml
MONGODB_URI = "mongodb+srv://USERNAME:PASSWORD@CLUSTER/..."
```

The app uses:

```python
client = get_mongo_client()
db = client["TeamRoster"]
collection = db[ROSTER_COLLECTION_NAME]
```

By default:

```python
ROSTER_COLLECTION_NAME = "roster_list"
```

If your existing collection must remain exactly `Team Roster Collection`, set:

```bash
ROSTER_COLLECTION_NAME="Team Roster Collection"
```

The app also creates supporting collections:
- `cases`
- `presence`
- `schedule`
- `requests`
- `notifications`
- `audit_log`
- `settings`

AUX is treated as live presence. It is written to `presence` so other sessions can see it in realtime; the roster profile itself is not changed by AUX activity. A TTL index removes stale presence records.

## Run

```bash
pip install -r requirements.txt
streamlit run hpe_caseflow_app.py
```

## Salesforce

The admin-only Salesforce page already points to:

`https://hp.lightning.force.com/`

The function `salesforce_fetch_cases()` is deliberately isolated. Replace that function with your OAuth/REST/SOQL implementation when the Salesforce API credentials are available. The rest of the app does not need to be redesigned.

## Important production notes

1. The requested bootstrap password is present as the fallback bootstrap credential in the script. For a production deployment, move it to a secret and rotate it.
2. Do not store plaintext passwords. The app stores PBKDF2 password hashes in the roster collection.
3. The current adherence calculation is a UI/database framework. For true production adherence and attendance, connect your authoritative WFM/timekeeping feed to the `compute_adherence()`/attendance layer.
4. Salesforce browser access is launched externally. Salesforce normally blocks arbitrary iframe embedding, so the app does not attempt to iframe the Salesforce console.
5. Streamlit still reruns for normal widget interactions by design. This build avoids expensive repeated database reads through short TTL caching, session state, and fragments; navigation does not deliberately clear the user's selected case or work state unless the page itself changes it.
