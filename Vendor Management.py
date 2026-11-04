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


def get_setting(name: str, default: str = "") -> str:
    """Read Streamlit Secrets first, then fall back to hosting environment variables.

    On Render, configure sensitive values under Dashboard > Service > Environment.
    Locally, values may be placed in .streamlit/secrets.toml or environment variables.
    """
    value = ""
    try:
        value = str(st.secrets.get(name, "")).strip()
    except Exception:
        # st.secrets may not exist when running outside Streamlit or without secrets.toml.
        value = ""

    if not value:
        value = str(os.getenv(name, "")).strip()

    return value or default


def get_mongo_uri() -> str:
    return get_setting("MONGODB_URI")


def get_database_name() -> str:
    return get_setting("MONGODB_DATABASE", "OVRVW")


@st.cache_resource(show_spinner=False)
def mongo_resources(uri: str, database_name: str):
    client = MongoClient(uri, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000)
    client.admin.command("ping")
    db = client[database_name]
    return client, db, db["workspace_state"], GridFSBucket(db)


uri = get_mongo_uri()
if not uri:
    st.error("MongoDB is not configured.")
    st.markdown(
        "**For Render hosting:** open your Streamlit service in the Render dashboard, "
        "go to **Environment**, and add `MONGODB_URI` as a secret environment variable. "
        "Set `MONGODB_DATABASE` to `OVRVW`. Do not place credentials in the source code "
        "or commit them to GitHub."
    )
    st.markdown(
        "**For local development only:** you may alternatively use "
        "`.streamlit/secrets.toml` or set environment variables."
    )
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
