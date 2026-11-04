from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import PyMongoError
from gridfs import GridFSBucket
from bson import ObjectId
from pydantic import BaseModel, Field

APP_NAME = "HPE OVR-VW Operations Workspace API"
DB_NAME = os.getenv("MONGODB_DATABASE", "OVRVW")
MONGO_URI = os.getenv("MONGODB_URI", "").strip()
API_KEY = os.getenv("OVRVW_API_KEY", "").strip()

app = FastAPI(
    title=APP_NAME,
    description=(
        "REST API for the OVR-VW operations workspace. The Streamlit UI and API "
        "share the same MongoDB workspace document and GridFS attachment store."
    ),
    version="1.0.0",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Configure allowed browser origins with comma-separated OVRVW_CORS_ORIGINS.
# Keep empty (no browser CORS access) unless a separate browser client needs it.
_origins = [x.strip() for x in os.getenv("OVRVW_CORS_ORIGINS", "").split(",") if x.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key"],
    )

_client: MongoClient | None = None
_db = None
_state = None
_events = None
_gridfs = None


def resources():
    global _client, _db, _state, _events, _gridfs
    if not MONGO_URI:
        raise HTTPException(status_code=503, detail="MongoDB is not configured on the API service.")
    if _client is None:
        try:
            _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000)
            _client.admin.command("ping")
            _db = _client[DB_NAME]
            _state = _db["workspace_state"]
            _events = _db["api_audit_events"]
            _gridfs = GridFSBucket(_db)
        except PyMongoError as exc:
            _client = None
            raise HTTPException(status_code=503, detail=f"MongoDB connection failed: {exc}") from exc
    return _db, _state, _events, _gridfs


def authorize(x_api_key: str | None):
    # API key is mandatory for data routes. Health remains public.
    if not API_KEY:
        raise HTTPException(status_code=503, detail="Set OVRVW_API_KEY on the API service before using data endpoints.")
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key.")


def audit(events, action: str, detail: dict[str, Any] | None = None):
    events.insert_one({
        "action": action,
        "detail": detail or {},
        "created_at": datetime.now(timezone.utc),
    })


class WorkspacePayload(BaseModel):
    state: dict[str, Any] = Field(default_factory=dict)


class CasePayload(BaseModel):
    case: dict[str, Any]


@app.get("/", include_in_schema=False)
def root():
    return {"service": APP_NAME, "docs": "/api/docs", "health": "/api/v1/health"}


@app.get("/api/v1/health")
def health():
    try:
        _, state, _, _ = resources()
        state.database.client.admin.command("ping")
        return {"status": "ok", "database": DB_NAME, "mongodb": "connected"}
    except HTTPException:
        raise
    except Exception as exc:
        return JSONResponse(status_code=503, content={"status": "error", "detail": str(exc)})


@app.get("/api/v1/workspace")
def get_workspace(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    authorize(x_api_key)
    _, state_collection, _, _ = resources()
    doc = state_collection.find_one({"_id": "main"}, {"_id": 0, "state": 1, "updated_at": 1, "schema_version": 1})
    if not doc:
        return {"state": {}, "updated_at": None, "schema_version": 1}
    updated = doc.get("updated_at")
    return {
        "state": doc.get("state", {}),
        "updated_at": updated.isoformat() if updated else None,
        "schema_version": doc.get("schema_version", 1),
    }


@app.put("/api/v1/workspace")
def put_workspace(payload: WorkspacePayload, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    authorize(x_api_key)
    _, state_collection, events, _ = resources()
    now = datetime.now(timezone.utc)
    state_collection.replace_one(
        {"_id": "main"},
        {"_id": "main", "state": payload.state, "updated_at": now, "schema_version": 1},
        upsert=True,
    )
    audit(events, "workspace.replace", {"top_level_keys": sorted(payload.state.keys())})
    return {"saved": True, "updated_at": now.isoformat()}


@app.get("/api/v1/cases")
def list_cases(
    status: str = Query(default="all", pattern="^(all|active|closed)$"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    authorize(x_api_key)
    _, state_collection, _, _ = resources()
    doc = state_collection.find_one({"_id": "main"}, {"_id": 0, "state.activeCasesData": 1, "state.closedCasesData": 1})
    state = (doc or {}).get("state", {})
    active = state.get("activeCasesData", []) or []
    closed = state.get("closedCasesData", []) or []
    if status == "active":
        result = active
    elif status == "closed":
        result = closed
    else:
        result = active + closed
    return {"count": len(result), "cases": result}


@app.get("/api/v1/cases/{case_id}")
def get_case(case_id: str, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    authorize(x_api_key)
    _, state_collection, _, _ = resources()
    doc = state_collection.find_one({"_id": "main"}, {"_id": 0, "state.activeCasesData": 1, "state.closedCasesData": 1})
    state = (doc or {}).get("state", {})
    for status, key in (("active", "activeCasesData"), ("closed", "closedCasesData")):
        for case in state.get(key, []) or []:
            if str(case.get("id", "")) == case_id:
                return {"status": status, "case": case}
    raise HTTPException(status_code=404, detail="Case not found.")


@app.put("/api/v1/cases/{case_id}")
def upsert_case(
    case_id: str,
    payload: CasePayload,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    authorize(x_api_key)
    case = payload.case
    if str(case.get("id", "")) != case_id:
        raise HTTPException(status_code=400, detail="case.id must match the case_id in the URL.")
    _, state_collection, events, _ = resources()
    doc = state_collection.find_one({"_id": "main"}) or {"_id": "main", "state": {}}
    state = doc.get("state", {}) or {}
    active = state.get("activeCasesData", []) or []
    closed = state.get("closedCasesData", []) or []
    target_key = "closedCasesData" if str(case.get("status", "")).lower() in {"closed", "complete", "completed"} else "activeCasesData"
    active = [c for c in active if str(c.get("id", "")) != case_id]
    closed = [c for c in closed if str(c.get("id", "")) != case_id]
    if target_key == "activeCasesData":
        active.append(case)
    else:
        closed.append(case)
    state["activeCasesData"] = active
    state["closedCasesData"] = closed
    now = datetime.now(timezone.utc)
    state_collection.replace_one(
        {"_id": "main"},
        {"_id": "main", "state": state, "updated_at": now, "schema_version": 1},
        upsert=True,
    )
    audit(events, "case.upsert", {"case_id": case_id, "bucket": target_key})
    return {"saved": True, "case_id": case_id, "bucket": target_key, "updated_at": now.isoformat()}


@app.get("/api/v1/attachments/{file_id}")
def download_attachment(file_id: str, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    authorize(x_api_key)
    _, _, _, bucket = resources()
    try:
        stream = bucket.open_download_stream(ObjectId(file_id))
        from fastapi.responses import StreamingResponse
        def chunks():
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        metadata = stream.metadata or {}
        return StreamingResponse(
            chunks(),
            media_type=metadata.get("content_type", "application/octet-stream"),
            headers={"Content-Disposition": f'attachment; filename="{stream.filename}"'},
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Attachment not found.")


@app.get("/api/v1/audit")
def list_audit(
    limit: int = Query(default=100, ge=1, le=500),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    authorize(x_api_key)
    _, _, events, _ = resources()
    rows = list(events.find({}, {"_id": 0}).sort("created_at", -1).limit(limit))
    for row in rows:
        if row.get("created_at"):
            row["created_at"] = row["created_at"].isoformat()
    return {"count": len(rows), "events": rows}


@app.post("/api/v1/attachments")
async def upload_attachment(
    file: UploadFile = File(...),
    case_id: str = Query(default=""),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    authorize(x_api_key)
    _, _, events, bucket = resources()
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Attachment exceeds the 20 MB API upload limit.")
    file_id = bucket.upload_from_stream(
        file.filename or "attachment.bin",
        raw,
        metadata={"case_id": case_id, "content_type": file.content_type or "application/octet-stream"},
    )
    audit(events, "attachment.upload", {"file_id": str(file_id), "case_id": case_id, "filename": file.filename})
    return {
        "file_id": str(file_id),
        "filename": file.filename,
        "content_type": file.content_type,
        "size_bytes": len(raw),
        "download_url": f"/api/v1/attachments/{file_id}",
    }
