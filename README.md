# HPE CaseFlow

## MongoDB connection — first run

If MongoDB is not configured, the app now opens a **MongoDB Connection Setup** screen instead of stopping with:

> MongoDB connection is not configured yet.

Paste your MongoDB Atlas connection string and click **Test & Connect**.

For a permanent deployment, use Streamlit secrets:

```toml
# .streamlit/secrets.toml
MONGODB_URI = "mongodb+srv://USERNAME:PASSWORD@CLUSTER.mongodb.net/?retryWrites=true&w=majority"
```

Or set the `MONGODB_URI` environment variable.

### Database used

```python
client = get_mongo_client()
db = client["TeamRoster"]
collection = db["roster_list"]
```

The app creates/uses these supporting collections:

- `roster_list`
- `cases`
- `presence`
- `schedule`
- `requests`
- `notifications`
- `audit_log`
- `settings`

The connection screen can test the MongoDB cluster before the login screen is shown.

## Run

```bash
pip install -r requirements.txt
streamlit run hpe_caseflow_app.py
```

## Bootstrap administrator

Email:
`arianne-may.escabillas@hpe.com`

Password:
`Escabillas1993`

Employee ID:
`60187999`

The bootstrap profile is created automatically if it does not already exist.

## Salesforce

Salesforce is admin-only and currently uses:

`https://hp.lightning.force.com/`

The Salesforce API synchronization point is isolated so credentials/OAuth can be added later without rebuilding the dashboard.

## Important

The URI entered through the first-run connection form is held in the current Streamlit session. For a permanent deployment, use `.streamlit/secrets.toml` or the deployment environment. Do not commit a real MongoDB password into source control.
