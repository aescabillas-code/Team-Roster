import os
import re
import io
import json
import math
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF
import streamlit as st
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Optional AI support:
# pip install openai
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# ============================================================
# CONFIG
# ============================================================

APP_NAME = "Knowledge Base"
DATA_DIR = Path("knowledge_base_data")
PDF_DIR = DATA_DIR / "pdfs"
DB_PATH = DATA_DIR / "knowledge_base.db"

DATA_DIR.mkdir(exist_ok=True)
PDF_DIR.mkdir(exist_ok=True)

st.set_page_config(
    page_title="Knowledge Base",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# CSS
# ============================================================

st.markdown(
    """
<style>
:root {
    --navy: #0b2538;
    --navy-2: #123b50;
    --teal: #00a982;
    --teal-dark: #007f72;
    --green-soft: #e7f8f1;
    --bg: #f5f8fa;
    --white: #ffffff;
    --border: #d9e3e8;
    --text: #102d42;
    --muted: #687b87;
}

html, body, [class*="css"] {
    font-family: Arial, Helvetica, sans-serif;
}

.stApp {
    background: linear-gradient(180deg, #f8fbfc 0%, #f2f6f8 100%);
    color: var(--text);
}

[data-testid="stHeader"] { background: transparent; }

.kb-topbar {
    display: flex;
    align-items: center;
    min-height: 76px;
    padding: 8px 10px 12px 8px;
    border-bottom: 1px solid #dfe7eb;
    background: linear-gradient(105deg, #ffffff 0%, #f7fbfc 70%, #e8f7f7 100%);
    margin-bottom: 8px;
}

.brand-block { width: 145px; }
.brand-mark {
    width: 46px;
    height: 7px;
    border: 3px solid #00a982;
    margin-bottom: 7px;
}
.brand-name { font-size: 14px; font-weight: 700; line-height: 1.05; color: #111; }
.brand-divider { height: 45px; width: 1px; background: #b8c7cf; margin: 0 22px 0 8px; }
.app-title { font-size: 28px; font-weight: 700; color: var(--text); line-height: 1; }
.app-subtitle { margin-top: 5px; font-size: 14px; color: #304a5c; }
.title-block { flex: 1; }
.top-tagline { text-align: right; color: #18394e; font-size: 12px; line-height: 1.3; margin-right: 12px; }
.top-actions { width: 36px; }
.bell { font-size: 22px; color: var(--navy); }

.exact-answer-card {
    background: linear-gradient(110deg, #f1fcf8, #ffffff 65%);
    border: 1px solid #7ad8bd;
    border-radius: 10px;
    padding: 18px 20px 16px;
    box-shadow: 0 3px 12px rgba(12, 54, 70, .05);
    margin-top: 8px;
}
.exact-answer-head { display: flex; justify-content: space-between; align-items: center; }
.exact-answer-title { color: #07866b; font-size: 19px; font-weight: 700; vertical-align: middle; }
.check-circle {
    display: inline-flex; width: 31px; height: 31px; border-radius: 50%;
    align-items: center; justify-content: center; background: #00a982; color: white;
    font-weight: 800; margin-right: 8px;
}
.match-pill { background: #d9f5ea; color: #087b64; font-weight: 700; padding: 5px 12px; border-radius: 20px; font-size: 12px; }
.exact-answer-note { margin: 5px 0 10px 39px; color: var(--muted); font-size: 12px; }
.exact-answer-text {
    margin: 0 0 12px 0; padding: 14px 18px; border-left: 4px solid var(--teal);
    background: rgba(255,255,255,.78); color: #172f42; font-size: 16px; line-height: 1.55;
}
.answer-meta { display: flex; flex-wrap: wrap; gap: 22px; color: #506672; font-size: 12px; padding-left: 2px; }

.source-header { background: white; border: 1px solid var(--border); border-bottom: 0; border-radius: 10px 10px 0 0; padding: 14px 16px; }
.source-title { font-size: 18px; font-weight: 700; color: var(--text); }
.source-meta { color: var(--muted); font-size: 12px; margin-top: 3px; }

.panel-title { font-size: 19px; font-weight: 700; color: var(--text); margin: 5px 0 12px; }
.related-title { color: #0561a0; font-weight: 700; font-size: 14px; padding-left: 30px; }
.related-number { float: left; width: 23px; height: 23px; background: #dfe9ed; border-radius: 4px; text-align: center; line-height: 23px; font-weight: 700; color: #294a5c; }
.related-meta { color: var(--muted); font-size: 11px; margin: 4px 0 7px 30px; }
.related-text { color: #354b59; font-size: 12px; line-height: 1.45; margin-left: 30px; }

.welcome-card {
    margin: 42px auto; max-width: 720px; text-align: center; background: white;
    border: 1px solid var(--border); border-radius: 14px; padding: 42px;
    box-shadow: 0 5px 18px rgba(12,54,70,.05);
}
.welcome-icon { font-size: 42px; color: var(--teal); }
.welcome-title { font-size: 25px; font-weight: 700; color: var(--text); margin-top: 8px; }
.welcome-text { color: var(--muted); max-width: 560px; margin: 10px auto; line-height: 1.6; font-size: 14px; }
.welcome-stats { display: flex; justify-content: center; gap: 35px; color: #57707e; margin-top: 18px; font-size: 12px; }

.page-heading { display:flex; justify-content:space-between; align-items:center; margin: 18px 0; }
.page-title { font-size: 26px; font-weight: 700; color: var(--text); }
.page-description { color: var(--muted); font-size: 13px; margin-top: 4px; }
.admin-badge { background:#e4f6f0; color:#087c63; font-size:11px; font-weight:700; border-radius:20px; padding:6px 12px; }
.admin-card { max-width:420px; margin:80px auto 20px; text-align:center; }
.admin-icon { font-size:40px; color:var(--teal); }
.admin-title { font-size:24px; font-weight:700; color:var(--text); }
.admin-subtitle { color:var(--muted); margin-top:5px; font-size:13px; }
.content-gap { height: 10px; }
.bottom-nav-spacer { height: 46px; }
.bottom-nav-label { text-align:center; color:#6c808b; font-size:10px; padding:4px 0 8px; }

/* Streamlit controls */
button[kind="primary"] { background: var(--teal) !important; border-color: var(--teal) !important; }
button[kind="primary"]:hover { background: var(--teal-dark) !important; }
[data-testid="stFileUploader"] { background: white; border-radius: 10px; border: 1px dashed #9ab1bc; }
[data-testid="stVerticalBlockBorderWrapper"] { border-color: var(--border) !important; border-radius: 9px !important; }
.stDownloadButton button { border-color: #00a982 !important; color: #087b64 !important; }

@media (max-width: 900px) {
    .brand-block { width: 110px; }
    .brand-divider, .top-tagline { display: none; }
    .app-title { font-size: 22px; }
    .app-subtitle { font-size: 12px; }
    .exact-answer-title { font-size: 16px; }
}
</style>
""",
    unsafe_allow_html=True,
)

# ============================================================
# DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            file_hash TEXT UNIQUE NOT NULL,
            category TEXT DEFAULT 'General',
            page_count INTEGER DEFAULT 0,
            file_size INTEGER DEFAULT 0,
            uploaded_at TEXT NOT NULL,
            indexed_at TEXT,
            status TEXT DEFAULT 'Indexed'
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            page_number INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            FOREIGN KEY(document_id) REFERENCES documents(id)
        );
        """
    )
    conn.commit()
    conn.close()


init_db()

# ============================================================
# HELPERS
# ============================================================

def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def make_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def split_text(text: str, chunk_size=1100, overlap=180):
    """
    Splits text approximately by words while preserving overlap.
    """
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0

    while start < len(words):
        end = min(len(words), start + chunk_size)
        chunk = " ".join(words[start:end]).strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(words):
            break

        start = max(0, end - overlap)

    return chunks


def extract_pdf(pdf_bytes: bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []

    for page_number, page in enumerate(doc, start=1):
        text = clean_text(page.get_text("text"))
        pages.append((page_number, text))

    return pages, len(doc)


def save_pdf(file_name: str, pdf_bytes: bytes, file_hash: str):
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name)
    destination = PDF_DIR / f"{file_hash[:12]}_{safe_name}"
    destination.write_bytes(pdf_bytes)
    return str(destination)


def document_exists(file_hash):
    conn = db()
    row = conn.execute(
        "SELECT id FROM documents WHERE file_hash = ?",
        (file_hash,),
    ).fetchone()
    conn.close()
    return row


def add_document(file_name, pdf_bytes, category="General"):
    file_hash = make_hash(pdf_bytes)

    if document_exists(file_hash):
        return False, "This PDF has already been uploaded."

    try:
        pages, page_count = extract_pdf(pdf_bytes)
    except Exception as e:
        return False, f"Could not read PDF: {e}"

    stored_path = save_pdf(file_name, pdf_bytes, file_hash)

    conn = db()
    now = datetime.now().isoformat(timespec="seconds")

    cursor = conn.execute(
        """
        INSERT INTO documents
        (filename, stored_path, file_hash, category, page_count,
         file_size, uploaded_at, indexed_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_name,
            stored_path,
            file_hash,
            category,
            page_count,
            len(pdf_bytes),
            now,
            now,
            "Indexed",
        ),
    )

    document_id = cursor.lastrowid

    for page_number, page_text in pages:
        page_chunks = split_text(page_text)

        for chunk_index, chunk in enumerate(page_chunks):
            conn.execute(
                """
                INSERT INTO chunks
                (document_id, page_number, chunk_index, text)
                VALUES (?, ?, ?, ?)
                """,
                (
                    document_id,
                    page_number,
                    chunk_index,
                    chunk,
                ),
            )

    conn.commit()
    conn.close()

    return True, f"{file_name} indexed successfully."


def get_documents():
    conn = db()
    rows = conn.execute(
        """
        SELECT *
        FROM documents
        ORDER BY uploaded_at DESC
        """
    ).fetchall()
    conn.close()
    return rows


def get_categories():
    conn = db()
    rows = conn.execute(
        """
        SELECT DISTINCT category
        FROM documents
        ORDER BY category
        """
    ).fetchall()
    conn.close()
    return [r["category"] for r in rows]


def get_all_chunks():
    conn = db()
    rows = conn.execute(
        """
        SELECT
            c.id,
            c.document_id,
            c.page_number,
            c.chunk_index,
            c.text,
            d.filename,
            d.category,
            d.stored_path
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        ORDER BY c.id
        """
    ).fetchall()
    conn.close()
    return rows


def delete_document(document_id):
    conn = db()

    row = conn.execute(
        "SELECT stored_path FROM documents WHERE id = ?",
        (document_id,),
    ).fetchone()

    if row:
        try:
            Path(row["stored_path"]).unlink(missing_ok=True)
        except Exception:
            pass

    conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
    conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    conn.commit()
    conn.close()


def format_bytes(value):
    if value is None:
        return "0 B"

    value = float(value)

    if value < 1024:
        return f"{value:.0f} B"
    if value < 1024**2:
        return f"{value / 1024:.1f} KB"
    if value < 1024**3:
        return f"{value / 1024**2:.1f} MB"

    return f"{value / 1024**3:.1f} GB"


def exact_passage(text, query, max_sentences=4, max_chars=1400):
    """Return verbatim text from the indexed PDF; never paraphrase."""
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    sentences = [s.strip() for s in sentences if s.strip()]

    terms = [
        t.lower()
        for t in re.findall(r"[A-Za-z0-9]+", query)
        if len(t) > 2
    ]

    if not terms or not sentences:
        return normalized[:max_chars]

    scored = []
    for i, sentence in enumerate(sentences):
        lower = sentence.lower()
        score = sum(lower.count(term) for term in terms)
        if score:
            scored.append((score, i))

    if not scored:
        return normalized[:max_chars]

    scored.sort(key=lambda x: (-x[0], x[1]))
    selected = set()

    for _, i in scored[:max_sentences]:
        selected.add(i)
        if len(selected) < max_sentences and i + 1 < len(sentences):
            selected.add(i + 1)

    passage = " ".join(sentences[i] for i in sorted(selected))

    if len(passage) > max_chars:
        passage = passage[:max_chars].rsplit(" ", 1)[0] + "..."

    return passage


def make_snippet(text, query, radius=260):
    text_clean = re.sub(r"\s+", " ", text).strip()
    if not query:
        return text_clean[:radius] + ("..." if len(text_clean) > radius else "")

    terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 2]

    positions = []
    lower = text_clean.lower()

    for term in terms:
        pos = lower.find(term)
        if pos >= 0:
            positions.append(pos)

    if not positions:
        return text_clean[:radius] + ("..." if len(text_clean) > radius else "")

    center = min(positions)
    start = max(0, center - radius // 2)
    end = min(len(text_clean), start + radius)

    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text_clean) else ""

    return prefix + text_clean[start:end] + suffix


# ============================================================
# SEARCH
# ============================================================

@st.cache_data(ttl=30, show_spinner=False)
def build_search_index():
    rows = get_all_chunks()

    if not rows:
        return None, [], []

    texts = [row["text"] for row in rows]

    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        ngram_range=(1, 2),
        min_df=1,
        max_df=0.98,
        sublinear_tf=True,
    )

    matrix = vectorizer.fit_transform(texts)

    return vectorizer, matrix, [dict(r) for r in rows]


def search_documents(query, category="All Categories", top_k=10):
    query = query.strip()

    if not query:
        return []

    vectorizer, matrix, rows = build_search_index()

    if vectorizer is None:
        return []

    query_vector = vectorizer.transform([query])
    scores = cosine_similarity(query_vector, matrix).flatten()

    results = []

    for idx, score in enumerate(scores):
        row = rows[idx]

        if category != "All Categories" and row["category"] != category:
            continue

        if score <= 0:
            continue

        results.append(
            {
                **row,
                "score": float(score),
                "snippet": make_snippet(row["text"], query),
                "exact_passage": exact_passage(row["text"], query),
            }
        )

    results.sort(key=lambda x: x["score"], reverse=True)

    return results[:top_k]


# ============================================================
# AI Q&A
# ============================================================

def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key or OpenAI is None:
        return None

    try:
        return OpenAI(api_key=api_key)
    except Exception:
        return None


def extractive_answer(question, results):
    if not results:
        return (
            "I could not find relevant information in the uploaded knowledge base."
        )

    selected = results[:5]

    answer_parts = []

    for item in selected:
        text = item["text"].strip()

        # Keep answer reasonably concise.
        if len(text) > 700:
            text = text[:700].rsplit(" ", 1)[0] + "..."

        answer_parts.append(text)

    return "\n\n".join(answer_parts)


def ai_answer(question, results):
    if not results:
        return (
            "I could not find relevant information in the uploaded documents.",
            [],
        )

    client = get_openai_client()

    if client is None:
        return extractive_answer(question, results), results[:5]

    context_blocks = []

    for i, item in enumerate(results[:8], start=1):
        context_blocks.append(
            f"""
SOURCE {i}
Document: {item['filename']}
Page: {item['page_number']}
Category: {item['category']}

CONTENT:
{item['text']}
"""
        )

    context = "\n".join(context_blocks)

    system_prompt = """
You are a company knowledge-base assistant.

Answer the user's question using ONLY the provided document context.
Do not invent policies, procedures, facts, dates, or instructions.
If the documents do not contain enough information, explicitly say that
the knowledge base does not provide enough information.

Keep answers concise and practical.
When appropriate, use numbered steps or bullet points.

Do not cite a source that was not provided in the context.
"""

    user_prompt = f"""
QUESTION:
{question}

DOCUMENT CONTEXT:
{context}

Answer the question using only the document context.
"""

    try:
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )

        answer = response.choices[0].message.content.strip()
        return answer, results[:8]

    except Exception as e:
        # Graceful fallback if AI service is unavailable.
        return (
            "AI answering is temporarily unavailable. "
            "Here are the most relevant passages from the knowledge base:\n\n"
            + extractive_answer(question, results)
        ), results[:5]


# ============================================================
# PDF VIEWER
# ============================================================

def render_pdf_page(document_path, page_number):
    try:
        pdf = fitz.open(document_path)

        if page_number < 1 or page_number > len(pdf):
            return None

        page = pdf[page_number - 1]

        pix = page.get_pixmap(
            matrix=fitz.Matrix(1.45, 1.45),
            alpha=False,
        )

        return pix.tobytes("png")

    except Exception:
        return None


# ============================================================
# UI STATE
# ============================================================

if "page" not in st.session_state:
    st.session_state.page = "Search"

if "selected_document" not in st.session_state:
    st.session_state.selected_document = None

if "selected_page" not in st.session_state:
    st.session_state.selected_page = 1

if "search_query" not in st.session_state:
    st.session_state.search_query = ""

if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False


# ============================================================
# PDF HIGHLIGHTING
# ============================================================

def render_pdf_page_highlighted(document_path, page_number, query=""):
    """Render a PDF page and highlight matching terms in the query."""
    try:
        pdf = fitz.open(document_path)

        if page_number < 1 or page_number > len(pdf):
            return None

        page = pdf[page_number - 1]

        terms = [
            t for t in re.findall(r"[A-Za-z0-9]+", query)
            if len(t) > 2
        ]

        # Highlight the most useful query terms directly on the source page.
        # We use temporary annotations only in the in-memory PDF object.
        highlighted = set()
        for term in terms[:12]:
            try:
                for rect in page.search_for(term):
                    key = (round(rect.x0, 1), round(rect.y0, 1),
                           round(rect.x1, 1), round(rect.y1, 1))
                    if key in highlighted:
                        continue
                    highlighted.add(key)
                    annot = page.add_highlight_annot(rect)
                    annot.update()
            except Exception:
                continue

        pix = page.get_pixmap(
            matrix=fitz.Matrix(1.45, 1.45),
            alpha=False,
        )

        return pix.tobytes("png")

    except Exception:
        return None


# ============================================================
# ADMIN AUTHENTICATION
# ============================================================

def get_admin_pin():
    """Read the admin PIN from Streamlit secrets first, then environment."""
    try:
        pin = st.secrets.get("ADMIN_PIN")
        if pin:
            return str(pin)
    except Exception:
        pass

    return os.getenv("ADMIN_PIN", "")


def admin_is_configured():
    return bool(get_admin_pin())


# ============================================================
# HEADER
# ============================================================

st.markdown(
    """
    <div class="kb-topbar">
        <div class="brand-block">
            <div class="brand-mark"></div>
            <div class="brand-name">Hewlett Packard<br>Enterprise</div>
        </div>
        <div class="brand-divider"></div>
        <div class="title-block">
            <div class="app-title">Knowledge Base</div>
            <div class="app-subtitle">Find exact information from your organization's documents</div>
        </div>
        <div class="top-tagline">
            Your Knowledge.<br>Anytime. Anywhere.
        </div>
        <div class="top-actions">
            <span class="bell">♧</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Gear button / admin menu in the upper-right.
g1, g2 = st.columns([20, 1], gap="small")
with g2:
    with st.popover("⚙", use_container_width=True):
        st.markdown("**Administration**")
        st.caption("Document management is restricted to administrators.")

        if st.button("🔒 Manage Documents", use_container_width=True):
            if st.session_state.admin_authenticated:
                st.session_state.page = "Manage Documents"
                st.rerun()
            else:
                st.session_state.page = "Admin Login"
                st.rerun()

        if st.session_state.admin_authenticated:
            if st.button("Sign out admin", use_container_width=True):
                st.session_state.admin_authenticated = False
                st.session_state.page = "Search"
                st.rerun()

# ============================================================
# ADMIN LOGIN
# ============================================================

if st.session_state.page == "Admin Login":
    st.markdown(
        """
        <div class="admin-card">
            <div class="admin-icon">⚙</div>
            <div class="admin-title">Admin Access</div>
            <div class="admin-subtitle">Enter the administrator PIN to manage documents.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not admin_is_configured():
        st.error(
            "Admin access is not configured. Set ADMIN_PIN in Streamlit Secrets "
            "or as an environment variable before using Manage Documents."
        )
        if st.button("Back to Search", type="primary"):
            st.session_state.page = "Search"
            st.rerun()
    else:
        with st.form("admin_login_form"):
            pin = st.text_input(
                "Admin PIN",
                type="password",
                placeholder="Enter admin PIN",
            )
            submitted = st.form_submit_button("Unlock", type="primary", use_container_width=True)

        if submitted:
            if pin == get_admin_pin():
                st.session_state.admin_authenticated = True
                st.session_state.page = "Manage Documents"
                st.rerun()
            else:
                st.error("Incorrect admin PIN.")

        if st.button("Cancel", use_container_width=True):
            st.session_state.page = "Search"
            st.rerun()

# ============================================================
# ADMIN: MANAGE DOCUMENTS
# ============================================================

elif st.session_state.page == "Manage Documents":
    if not st.session_state.admin_authenticated:
        st.session_state.page = "Admin Login"
        st.rerun()

    st.markdown(
        """
        <div class="page-heading">
            <div>
                <div class="page-title">Manage Documents</div>
                <div class="page-description">Upload, manage, and index PDF documents for the knowledge base.</div>
            </div>
            <div class="admin-badge">ADMIN ONLY</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    upload_col, library_col = st.columns([0.95, 1.35], gap="large")

    with upload_col:
        st.markdown('<div class="panel-title">Upload Documents</div>', unsafe_allow_html=True)
        category = st.selectbox(
            "Category",
            [
                "General", "Policies", "Procedures", "Technical Support",
                "Licensing", "Training", "Product", "Account Management", "Other",
            ],
            key="admin_category",
        )

        uploaded_files = st.file_uploader(
            "Drag and drop PDF files here",
            type=["pdf"],
            accept_multiple_files=True,
            key="admin_uploader",
        )

        if uploaded_files:
            st.caption(f"{len(uploaded_files)} PDF file(s) selected")
            for f in uploaded_files:
                st.write(f"📄 {f.name} · {format_bytes(len(f.getvalue()))}")

        if st.button("Upload & Index Documents", type="primary", use_container_width=True):
            if not uploaded_files:
                st.warning("Select at least one PDF file.")
            else:
                progress = st.progress(0)
                success_count = 0
                for i, uploaded_file in enumerate(uploaded_files):
                    ok, message = add_document(
                        uploaded_file.name,
                        uploaded_file.getvalue(),
                        category,
                    )
                    if ok:
                        success_count += 1
                        st.success(message)
                    else:
                        st.warning(message)
                    progress.progress((i + 1) / len(uploaded_files))

                build_search_index.clear()
                st.success(f"Completed. {success_count} document(s) indexed.")

    with library_col:
        st.markdown('<div class="panel-title">Document Library</div>', unsafe_allow_html=True)
        docs = get_documents()

        lc1, lc2 = st.columns([1.5, 1])
        with lc1:
            library_search = st.text_input(
                "Search documents",
                placeholder="Search documents...",
                label_visibility="collapsed",
                key="library_search",
            )
        with lc2:
            library_category = st.selectbox(
                "Library category",
                ["All Categories"] + get_categories(),
                label_visibility="collapsed",
                key="library_category",
            )

        filtered_docs = []
        for doc in docs:
            if library_search and library_search.lower() not in doc["filename"].lower():
                continue
            if library_category != "All Categories" and doc["category"] != library_category:
                continue
            filtered_docs.append(doc)

        if not filtered_docs:
            st.info("No documents match the current filters.")
        else:
            for doc in filtered_docs:
                with st.container(border=True):
                    a, b = st.columns([4, 1])
                    with a:
                        st.markdown(f"**📄 {doc['filename']}**")
                        st.caption(
                            f"{doc['category']} · {doc['page_count']} pages · "
                            f"{format_bytes(doc['file_size'])} · ✓ {doc['status']}"
                        )
                    with b:
                        if st.button("Delete", key=f"admin_delete_{doc['id']}"):
                            delete_document(doc["id"])
                            build_search_index.clear()
                            st.rerun()

    if st.button("← Back to Search"):
        st.session_state.page = "Search"
        st.rerun()

# ============================================================
# SEARCH KNOWLEDGE BASE
# ============================================================

else:
    st.session_state.page = "Search"

    # Search controls.
    search_col, button_col, filter_col = st.columns([6.4, 1.0, 1.0], gap="small")

    with search_col:
        query = st.text_input(
            "Search",
            value=st.session_state.search_query,
            placeholder="What should I check or find in the knowledge base?",
            label_visibility="collapsed",
            key="main_search_box",
        )

    with button_col:
        search_clicked = st.button("Search", type="primary", use_container_width=True)

    with filter_col:
        with st.popover("☷ Filters", use_container_width=True):
            category = st.selectbox(
                "Category",
                ["All Categories"] + get_categories(),
                key="search_category",
            )
            top_k = st.selectbox(
                "Results",
                [5, 10, 20],
                index=1,
                key="search_top_k",
            )

    if search_clicked:
        st.session_state.search_query = query

    active_query = st.session_state.search_query.strip()
    category = st.session_state.get("search_category", "All Categories")
    top_k = st.session_state.get("search_top_k", 10)

    if active_query:
        results = search_documents(
            active_query,
            category=category,
            top_k=top_k,
        )

        if not results:
            st.warning(
                "No exact source passage was found. Try different keywords or upload another document."
            )
        else:
            best = results[0]
            best_score = min(99, max(1, round(best["score"] * 100)))

            # ====================================================
            # EXACT ANSWER — ALWAYS FIRST
            # ====================================================
            st.markdown(
                f"""
                <div class="exact-answer-card">
                    <div class="exact-answer-head">
                        <div>
                            <span class="check-circle">✓</span>
                            <span class="exact-answer-title">Exact Answer (from PDF)</span>
                        </div>
                        <span class="match-pill">{best_score}% match</span>
                    </div>
                    <div class="exact-answer-note">
                        Verbatim text extracted from the uploaded document. No AI paraphrasing applied.
                    </div>
                    <div class="exact-answer-text">“{best['exact_passage']}”</div>
                    <div class="answer-meta">
                        <span>📄 <b>{best['filename']}</b></span>
                        <span>Page {best['page_number']}</span>
                        <span>Category {best['category']}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            copy_col, spacer = st.columns([1, 5])
            with copy_col:
                st.download_button(
                    "Copy Answer",
                    data=best["exact_passage"],
                    file_name="exact_answer.txt",
                    mime="text/plain",
                    use_container_width=True,
                )

            st.markdown('<div class="content-gap"></div>', unsafe_allow_html=True)

            # ====================================================
            # SOURCE PDF DIRECTLY BELOW EXACT ANSWER
            # ====================================================
            source_col, related_col = st.columns([1.55, 0.9], gap="large")

            with source_col:
                st.markdown(
                    f"""
                    <div class="source-header">
                        <div>
                            <div class="source-title">▣ Source Document</div>
                            <div class="source-meta">{best['filename']} · Page {best['page_number']} of document</div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                image_bytes = render_pdf_page_highlighted(
                    best["stored_path"],
                    best["page_number"],
                    active_query,
                )

                if image_bytes:
                    st.image(image_bytes, use_container_width=True)
                else:
                    st.error("Unable to render the source PDF page.")

                st.caption(
                    "The highlighted text above is the matching source passage. "
                    "The wording is taken directly from the uploaded PDF."
                )

            # ====================================================
            # RELATED RESULTS
            # ====================================================
            with related_col:
                st.markdown('<div class="panel-title">Related Results</div>', unsafe_allow_html=True)

                for i, result in enumerate(results[1:], start=2):
                    score = min(99, max(1, round(result["score"] * 100)))

                    with st.container(border=True):
                        st.markdown(
                            f"""
                            <div class="related-number">{i}</div>
                            <div class="related-title">{result['filename']}</div>
                            <div class="related-meta">Page {result['page_number']} · {result['category']} · {score}% match</div>
                            <div class="related-text">“{result['exact_passage']}”</div>
                            """,
                            unsafe_allow_html=True,
                        )

                        if st.button(
                            "Use this answer",
                            key=f"related_{result['id']}",
                            use_container_width=True,
                        ):
                            st.session_state.selected_document = result["stored_path"]
                            st.session_state.selected_page = result["page_number"]
                            st.session_state.search_query = active_query
                            st.session_state.selected_result_id = result["id"]
                            st.rerun()

    else:
        # ========================================================
        # EMPTY STATE
        # ========================================================
        docs = get_documents()
        total_pages = sum(int(d["page_count"] or 0) for d in docs)

        st.markdown(
            f"""
            <div class="welcome-card">
                <div class="welcome-icon">⌕</div>
                <div class="welcome-title">Search your knowledge base</div>
                <div class="welcome-text">
                    Ask a question or enter keywords. The system will return the exact wording
                    from your uploaded PDFs and show the matching source page.
                </div>
                <div class="welcome-stats">
                    <span><b>{len(docs)}</b> documents</span>
                    <span><b>{total_pages:,}</b> indexed pages</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

# ============================================================
# BOTTOM NAVIGATION
# ============================================================

st.markdown('<div class="bottom-nav-spacer"></div>', unsafe_allow_html=True)
nav_left, nav_center, nav_right = st.columns([1, 2, 1])
with nav_center:
    if st.button("⌕  Search Knowledge Base", use_container_width=True):
        st.session_state.page = "Search"
        st.rerun()

st.markdown(
    """
    <div class="bottom-nav-label">
        Knowledge Base · Exact PDF Search
    </div>
    """,
    unsafe_allow_html=True,
)

