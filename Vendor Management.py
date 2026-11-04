from __future__ import annotations
import os
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
from pymongo import MongoClient
from gridfs import GridFSBucket
import base64
from bson import ObjectId
from pymongo.errors import PyMongoError
import streamlit.components.v1 as components

st.set_page_config(page_title="HPE OVR-VW Operations Workspace", page_icon="🟢", layout="wide", initial_sidebar_state="collapsed")

APP_DIR = Path(__file__).resolve().parent
# Locate the bundled frontend whether the folder is named component/components
# and whether Streamlit is launched from the project root or another working directory.
_candidates = [
    APP_DIR / "component",
    APP_DIR / "components",
    Path.cwd() / "component",
    Path.cwd() / "components",
]
COMPONENT_DIR = next(
    (candidate.resolve() for candidate in _candidates if (candidate / "index.html").is_file()),
    None,
)
if COMPONENT_DIR is None:
    st.error("The OVR-VW frontend component could not be found.")
    st.code(
        f"Expected this file: {APP_DIR / 'component' / 'index.html'}\n\n"
        "Keep app.py and the component folder together. The folder must contain index.html.",
        language="text",
    )
    st.stop()

ovrvw_component = components.declare_component("ovrvw_workspace", path=str(COMPONENT_DIR))


def get_mongo_uri() -> str:
    try:
        return str(st.secrets.get("MONGODB_URI", "")).strip()
    except Exception:
        return os.getenv("MONGODB_URI", "").strip()


def get_database_name() -> str:
    try:
        return str(st.secrets.get("MONGODB_DATABASE", "OVRVW")).strip() or "OVRVW"
    except Exception:
        return os.getenv("MONGODB_DATABASE", "OVRVW").strip() or "OVRVW"


@st.cache_resource(show_spinner=False)
def mongo_resources(uri: str, database_name: str):
    client = MongoClient(uri, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000)
    client.admin.command("ping")
    db = client[database_name]
    return client, db, db["workspace_state"], GridFSBucket(db)


uri = get_mongo_uri()
if not uri:
    st.error("MongoDB is not configured. Add MONGODB_URI to .streamlit/secrets.toml or the MONGODB_URI environment variable before using the workspace.")
    st.code('MONGODB_URI = "mongodb+srv://<db_user>:<db_password>@<cluster>.mongodb.net/?retryWrites=true&w=majority"\nMONGODB_DATABASE = "OVRVW"', language="toml")
    st.stop()

try:
    client, database, state_collection, gridfs_bucket = mongo_resources(uri, get_database_name())
    record = state_collection.find_one({"_id": "main"}, {"_id": 0, "state": 1})
    initial_state = (record or {}).get("state", {})
    # Hydrate attachment file bytes from GridFS for the browser preview/download controls.
    for case_list_name in ("activeCasesData", "closedCasesData"):
        for case in initial_state.get(case_list_name, []) or []:
            for attachment in case.get("attachments", []) or []:
                file_id = attachment.get("_gridfs_id")
                if file_id:
                    try:
                        raw = gridfs_bucket.open_download_stream(ObjectId(file_id)).read()
                        attachment["_fileData"] = base64.b64encode(raw).decode("ascii")
                    except Exception:
                        attachment["_fileUnavailable"] = True
except (PyMongoError, Exception) as exc:
    st.error(f"Could not connect to MongoDB: {exc}")
    st.info("Check the MongoDB connection string, database user/password, and Atlas Network Access allowlist.")
    st.stop()

# The HTML app remains the UI. Its embedded component bridge sends state changes to Python,
# which writes the latest full workspace snapshot to MongoDB.
result = ovrvw_component(
    initial_state=initial_state,
    persistence_status="Connected to MongoDB",
    key="ovrvw_main",
    default=None,
)

if isinstance(result, dict) and result.get("_ovrvw_persist"):
    payload = result.get("state", {})
    if isinstance(payload, dict):
        try:
            # Store uploaded attachment binaries in GridFS, not in the 16 MB state document.
            for case_list_name in ("activeCasesData", "closedCasesData"):
                for case in payload.get(case_list_name, []) or []:
                    for attachment in case.get("attachments", []) or []:
                        encoded = attachment.pop("_fileData", None)
                        if encoded and not attachment.get("_gridfs_id"):
                            raw = base64.b64decode(encoded)
                            grid_id = gridfs_bucket.upload_from_stream(
                                attachment.get("name", "attachment.bin"), raw,
                                metadata={"case_id": case.get("id"), "attachment_id": attachment.get("id")},
                            )
                            attachment["_gridfs_id"] = str(grid_id)
            state_collection.replace_one(
                {"_id": "main"},
                {
                    "_id": "main",
                    "state": payload,
                    "updated_at": datetime.now(timezone.utc),
                    "schema_version": 1,
                },
                upsert=True,
            )
            st.session_state["ovrvw_last_saved"] = datetime.now(timezone.utc).isoformat()
        except PyMongoError as exc:
            st.error(f"MongoDB save failed: {exc}")

# Keep the Streamlit chrome out of the way so the original workspace occupies the page.
st.markdown("<style>header[data-testid='stHeader']{height:0;min-height:0} .block-container{padding:0!important;max-width:100%!important} [data-testid='stAppViewContainer']>.main{padding:0!important} footer{visibility:hidden}</style>", unsafe_allow_html=True)
