# MongoDB setup for HPE Case Operations Control Center

The updated app now handles missing MongoDB configuration gracefully instead of failing immediately.

## 1. MongoDB Atlas

Create:

`.streamlit/secrets.toml`

with:

```toml
MONGO_URI = "mongodb+srv://USERNAME:PASSWORD@YOUR-CLUSTER.mongodb.net/?retryWrites=true&w=majority"
```

Replace the placeholders with your Atlas credentials.

If the username or password contains characters such as `@`, `:`, `/`, `?`, or `#`, URL-encode those credentials before putting them in the URI.

## 2. Local MongoDB

Use:

```toml
MONGO_URI = "mongodb://localhost:27017"
```

## 3. Database

The app uses:

- Database: `TeamRoster`
- Primary collection: `Team Roster Collection`

The following collections are created/initialized automatically after a successful connection:

- Team Roster Collection
- Cases
- Case History
- Schedules
- Schedule Requests
- Settings
- Assignment Logs
- Attendance
- Notifications

Indexes are also created automatically.

## 4. What changed

The modified script now:

- Checks the MongoDB URI before accessing collections.
- Tests the MongoDB connection with `ping`.
- Supports both `MONGO_URI` and `MONGODB_URI`.
- Shows a MongoDB setup/diagnostics screen if the URI is missing or invalid.
- Provides a Retry Connection button.
- Provides an Initialize / Repair Database action after a successful connection.
- Does not put MongoDB credentials into the Python source.
- Keeps Salesforce optional; Salesforce is not required for the app to start.

Restart Streamlit after changing `.streamlit/secrets.toml`.
