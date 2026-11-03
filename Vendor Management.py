"""OVR-VW Operations Workspace - API + static host (FastAPI + MongoDB).

Run:  uvicorn main:app --host 0.0.0.0 --port 8000
Env:  MONGODB_URI (required) · MONGODB_DB · JWT_SECRET (required in prod) · REGISTER_CODE (optional)
      ALLOWED_ORIGINS (comma list, default *) · TOKEN_HOURS (default 12) · MAX_UPLOAD_MB (default 25)
"""
import hashlib, hmac, logging, os, secrets, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import gridfs
import jwt
from bson import ObjectId
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from pymongo import ASCENDING, MongoClient, ReturnDocument

log = logging.getLogger("ovr-vw")
# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
MONGODB_URI = None

# Try Streamlit Secrets first
try:
    import streamlit as st

    if "MONGODB_URI" in st.secrets:
        MONGODB_URI = st.secrets["MONGODB_URI"]

    DB_NAME = st.secrets.get("MONGODB_DB", "ovr_vw")
    JWT_SECRET = st.secrets.get("JWT_SECRET")

except Exception:
    DB_NAME = None
    JWT_SECRET = None

# Fall back to environment variables
MONGODB_URI = MONGODB_URI or os.getenv("MONGODB_URI")
DB_NAME = DB_NAME or os.getenv("MONGODB_DB", "ovr_vw")
JWT_SECRET = JWT_SECRET or os.getenv("JWT_SECRET")

if not MONGODB_URI:
    raise RuntimeError(
        "MONGODB_URI not found. Configure it in Streamlit Secrets "
        "or as an environment variable."
    )

if not JWT_SECRET:
    JWT_SECRET = secrets.token_urlsafe(48)
    log.warning(
        "JWT_SECRET not configured. Using temporary secret; "
        "all sessions will be invalidated after restart."
    )

REGISTER_CODE = os.getenv("REGISTER_CODE", "")
TOKEN_HOURS = int(os.getenv("TOKEN_HOURS", "12"))
MAX_UPLOAD = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024
WS_KEYS = {"staff", "rules", "config"}            # shared workspace documents

client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=8000)
db = client[DB_NAME]
fs = gridfs.GridFS(db)
now_ms = lambda: int(time.time() * 1000)


def next_seq() -> int:
    r = db.counters.find_one_and_update({"_id": "seq"}, {"$inc": {"v": 1}}, upsert=True,
                                        return_document=ReturnDocument.AFTER)
    return int(r["v"])


app = FastAPI(title="OVR-VW Operations Workspace API")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("ALLOWED_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _indexes():
    db.users.create_index("username", unique=True)
    db.cases.create_index([("seq", ASCENDING)])
    db.workspace.create_index([("seq", ASCENDING)])
    db.uploads_log.create_index([("at", ASCENDING)])


# ---------------------------------------------------------------- auth
def hash_pw(pw: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    return salt.hex() + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000).hex()


def check_pw(pw: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$")
        return hmac.compare_digest(hash_pw(pw, bytes.fromhex(salt)), stored)
    except Exception:
        return False


def make_token(u: dict) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    return jwt.encode({"sub": u["username"], "name": u["display_name"], "role": u["role"], "exp": exp},
                      JWT_SECRET, algorithm="HS256")


def auth(authorization: str = Header(default="")) -> dict:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not signed in")
    try:
        p = jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired")
    return {"username": p["sub"], "display_name": p["name"], "role": p["role"]}


class Cred(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    code: Optional[str] = None


@app.post("/api/auth/register")
def register(b: Cred):
    un = b.username.strip().lower()
    if len(un) < 3 or len(b.password) < 8:
        raise HTTPException(400, "Username min 3 chars, password min 8 chars")
    if REGISTER_CODE and b.code != REGISTER_CODE:
        raise HTTPException(403, "Invalid invite code")
    role = "admin" if db.users.count_documents({}) == 0 else "user"
    u = {"username": un, "display_name": (b.display_name or b.username).strip(), "role": role,
         "pw": hash_pw(b.password), "created_at": now_ms()}
    try:
        db.users.insert_one(u)
    except Exception:
        raise HTTPException(409, "Username already exists")
    return {"token": make_token(u), "user": {"username": un, "display_name": u["display_name"], "role": role}}


@app.post("/api/auth/login")
def login(b: Cred):
    u = db.users.find_one({"username": b.username.strip().lower()})
    if not u or not check_pw(b.password, u["pw"]):
        raise HTTPException(400, "Wrong username or password")
    return {"token": make_token(u), "user": {"username": u["username"], "display_name": u["display_name"], "role": u["role"]}}


@app.get("/api/auth/me")
def me(u: dict = Depends(auth)):
    return u


# ---------------------------------------------------------------- shared data
class DocIn(BaseModel):
    data: Any = None
    h: str = ""
    client: Optional[str] = None
    closed: bool = False
    sla: Optional[dict] = None


@app.put("/api/workspace/{key}")
def put_ws(key: str, b: DocIn, u: dict = Depends(auth)):
    if key not in WS_KEYS:
        raise HTTPException(404, "Unknown workspace document")
    seq = next_seq()
    db.workspace.update_one({"_id": key}, {"$set": {"data": b.data, "h": b.h, "seq": seq, "client": b.client,
                                                     "updated_by": u["username"], "saved_at": now_ms()}}, upsert=True)
    return {"seq": seq}


@app.put("/api/cases/{cid}")
def put_case(cid: str, b: DocIn, u: dict = Depends(auth)):
    seq = next_seq()
    db.cases.update_one({"_id": cid}, {"$set": {"data": b.data, "closed": b.closed, "h": b.h, "sla": b.sla,
                                                 "seq": seq, "deleted": False, "client": b.client,
                                                 "updated_by": u["username"], "saved_at": now_ms()}}, upsert=True)
    return {"seq": seq}


@app.delete("/api/cases/{cid}")
def del_case(cid: str, client_id: Optional[str] = None, u: dict = Depends(auth)):
    seq = next_seq()
    db.cases.update_one({"_id": cid}, {"$set": {"data": None, "deleted": True, "seq": seq, "client": client_id,
                                                 "updated_by": u["username"], "saved_at": now_ms()}}, upsert=True)
    return {"seq": seq}


@app.get("/api/changes")
def changes(since: int = 0, u: dict = Depends(auth)):
    c = db.counters.find_one({"_id": "seq"})
    cur = int(c["v"]) if c else 0
    q = {"seq": {"$gt": since, "$lte": cur}}
    ws = [{"key": d["_id"], "data": d.get("data"), "h": d.get("h"), "seq": d["seq"], "client": d.get("client"),
           "updated_by": d.get("updated_by")} for d in db.workspace.find(q)]
    cs = [{"id": d["_id"], "data": d.get("data"), "closed": d.get("closed", False), "deleted": d.get("deleted", False),
           "h": d.get("h"), "sla": d.get("sla"), "saved_at": d.get("saved_at"), "seq": d["seq"],
           "client": d.get("client"), "updated_by": d.get("updated_by")} for d in db.cases.find(q)]
    return {"seq": cur, "now": now_ms(), "workspace": ws, "cases": cs}


# per-user preferences (theme, density, notification toggles...)
@app.get("/api/prefs")
def get_prefs(u: dict = Depends(auth)):
    d = db.prefs.find_one({"_id": u["username"]})
    return {"data": d.get("data") if d else None}


@app.put("/api/prefs")
def put_prefs(b: DocIn, u: dict = Depends(auth)):
    db.prefs.update_one({"_id": u["username"]}, {"$set": {"data": b.data, "saved_at": now_ms()}}, upsert=True)
    return {"ok": True}


# ---------------------------------------------------------------- files (GridFS)
@app.post("/api/files")
def upload_file(file: UploadFile = File(...), kind: str = Form("attachment"), case_id: str = Form(""),
                u: dict = Depends(auth)):
    data = file.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"File exceeds {MAX_UPLOAD // 1048576} MB")
    fid = fs.put(data, filename=file.filename, content_type=file.content_type,
                 kind=kind, case_id=case_id, uploaded_by=u["username"])
    db.uploads_log.insert_one({"file_id": fid, "name": file.filename, "size": len(data), "kind": kind,
                               "case_id": case_id, "by": u["username"], "at": now_ms()})
    return {"id": str(fid)}


@app.get("/api/files/{fid}")
def get_file(fid: str, u: dict = Depends(auth)):
    try:
        f = fs.get(ObjectId(fid))
    except Exception:
        raise HTTPException(404, "File not found")
    return Response(f.read(), media_type=f.content_type or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{f.filename}"'})


# ---------------------------------------------------------------- front-end + health
@app.get("/health")
def health():
    client.admin.command("ping")
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index():
    html = (Path(__file__).parent / "static" / "workspace.html").read_text(encoding="utf-8")
    return html.replace("__API_BASE__", "")
