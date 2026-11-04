# HPE OVR-VW Operations Workspace — Streamlit + MongoDB

This package hosts the supplied HTML workspace inside a Streamlit custom component. The HTML/CSS/JavaScript interface is retained rather than rewritten as native Streamlit widgets. The component sends workspace snapshots to Python, and Python persists them in MongoDB.

## What is persisted

- Active and closed cases, case fields, elapsed timers, station journey/history, checklist/action data, notes, resolutions, and collaboration messages
- Workspace preferences and simulation user/settings
- Staff and staffing settings
- Alert rules and simulation event settings
- Import/export configuration and other serializable workspace state included in the snapshot
- Uploaded case attachment binaries in MongoDB GridFS, with attachment metadata in the workspace document

The original HTML's embedded audio binaries and transient modal/toast state are not copied into MongoDB; default audio resources remain packaged with the HTML.

## 1. Install on Windows

Install Python 3.11 or 3.12, then open PowerShell in this folder:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 2. Create MongoDB Atlas database

1. Create a free MongoDB Atlas cluster.
2. Create a database user and password.
3. In **Network Access**, allow the IP address of the machine/server running Streamlit. For local testing, add your current IP. Avoid `0.0.0.0/0` for a production deployment unless you understand the exposure.
4. Copy the Python driver connection string.
5. Create `.streamlit\secrets.toml` (copy the example file) and enter the URI and database name:

```toml
MONGODB_URI = "mongodb+srv://YOUR_USER:YOUR_PASSWORD@YOUR_CLUSTER.mongodb.net/?retryWrites=true&w=majority"
MONGODB_DATABASE = "OVRVW"
```

Do not commit `secrets.toml` to Git or share the connection string.

## 3. Run

```powershell
streamlit run app.py
```

Open the local URL Streamlit prints (normally `http://localhost:8501`).

## 4. Deploy / host online

Deploy this whole folder to Streamlit Community Cloud or another Streamlit host. Add `MONGODB_URI` and `MONGODB_DATABASE` in the host's Secrets settings. In MongoDB Atlas, allow the deployment host's outbound IP range (or use an appropriately secured network strategy). The app is private only if the hosting provider's access controls are configured; MongoDB persistence does not itself make the website private.

## MongoDB layout

Database: `OVRVW` (configurable)  
Collection: `workspace_state`  
Document `_id`: `main`  
Attachment files: MongoDB GridFS (`fs.files` / `fs.chunks`)  
The current workspace snapshot is replaced atomically on each save. Attachment binaries are kept in GridFS so they do not consume the 16 MB workspace-document limit.

## Important notes

- The HTML app includes simulated cases and operational examples. Starting the simulation changes the workspace data and that state will be persisted.
- This package does not add authentication/authorization. For a private multi-user deployment, put the app behind Streamlit's supported authentication or an identity-aware proxy and implement user/role authorization before allowing access.
- This integration saves shared workspace state. It does not provide multi-user conflict resolution or field-level audit/event sourcing. Concurrent editors can overwrite each other's latest snapshot.
- The UI is embedded as a custom component; all interactive actions stay in the supplied HTML/JavaScript. Test the full workflow after deployment, especially browser file uploads, audio playback, and downloads.
