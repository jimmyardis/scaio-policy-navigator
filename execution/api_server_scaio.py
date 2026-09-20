#!/usr/bin/env python3
"""
Sky — SCAIO's AI guide · FastAPI RAG Query Server

3-layer architecture:
  Layer 1: Retrieve — embed query via Voyage AI, fetch top-k from Pinecone
  Layer 2: Augment  — deduplicate, filter by score, build context block
  Layer 3: Generate — Claude answers from context only (model: CLAUDE_MODEL)

Run:
    source venv/bin/activate
    uvicorn execution.api_server_scaio:app --port 8001 --reload

Or directly:
    python execution/api_server_scaio.py
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")  # no-op on Railway (env vars injected directly)

import voyageai
from pinecone import Pinecone
from anthropic import Anthropic
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# ── Config ─────────────────────────────────────────────────────────────────────

VOYAGE_MODEL    = "voyage-3"
CLAUDE_MODEL    = "claude-haiku-4-5-20251001"
MIN_SCORE       = 0.35   # drop chunks below this cosine similarity
MIN_CHUNKS      = 2      # if fewer pass threshold, return "not enough info" (first turn only)
MAX_HISTORY_TURNS = 6    # prior turns replayed to Claude, newest kept
REPO_ROOT       = Path(__file__).parent.parent
SOURCES_FILE    = REPO_ROOT / "corpus" / "tier1_sources.json"
FRONTEND_DIR    = REPO_ROOT / "frontend"

# ── Startup / client init ──────────────────────────────────────────────────────

def _require(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        print(f"[ERROR] {key} not set in .env")
        sys.exit(1)
    return val

voyage_client   = voyageai.Client(api_key=_require("VOYAGE_API_KEY"))
pinecone_index  = Pinecone(api_key=_require("PINECONE_API_KEY")).Index(
    os.environ.get("PINECONE_INDEX_SCAIO", "scaio-policy")
)
anthropic_client = Anthropic(api_key=_require("ANTHROPIC_API_KEY"))

# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Sky — SCAIO",
    description="RAG-powered Q&A over South Carolina AI policy corpus",
    version="1.0.0",
)

# The embedded widget runs in an iframe served from this origin, so it calls
# /query same-origin and needs no CORS grant. These entries cover direct calls
# from scaio.org page scripts and local development. Override in Railway with
# a comma-separated ALLOWED_ORIGINS if the site moves.
DEFAULT_ORIGINS = [
    "https://www.scaio.org",
    "https://scaio.org",
    "https://ask.scaio.org",
    "http://localhost:8001",
    "http://127.0.0.1:8001",
]
ALLOWED_ORIGINS = [
    o.strip() for o in
    os.environ.get("ALLOWED_ORIGINS", ",".join(DEFAULT_ORIGINS)).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ── Static files & page routes ─────────────────────────────────────────────────

app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


@app.get("/ask", include_in_schema=False)
def ask_page():
    return FileResponse(str(FRONTEND_DIR / "ask.html"))

# ── Request / response models ──────────────────────────────────────────────────

class Turn(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1, max_length=8000)


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=5, max_length=1000)
    history: list[Turn] = Field(
        default_factory=list,
        description="Prior turns, oldest first. Only the last MAX_HISTORY_TURNS are used.",
    )
    top_k: int = Field(default=12, ge=1, le=20)
    tier_filter: Optional[int] = Field(default=None, description="1, 2, or 3")
    include_sources: bool = True


class SourceCitation(BaseModel):
    title: str
    url: str
    tier: int
    date: str
    chunk_index: int


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceCitation]
    chunks_used: int


# ── Layer 1: Retrieve ──────────────────────────────────────────────────────────

def retrieve(question: str, top_k: int, tier_filter: Optional[int]) -> list[dict]:
    """Embed question and fetch top-k chunks from Pinecone."""
    result = voyage_client.embed([question], model=VOYAGE_MODEL, input_type="query")
    query_vec = result.embeddings[0]

    pinecone_filter = {}
    if tier_filter is not None:
        pinecone_filter["tier"] = {"$eq": tier_filter}

    kwargs = dict(vector=query_vec, top_k=top_k, include_metadata=True)
    if pinecone_filter:
        kwargs["filter"] = pinecone_filter

    response = pinecone_index.query(**kwargs)
    return response.matches


# ── Layer 2: Augment ───────────────────────────────────────────────────────────

def build_context(matches: list) -> tuple[str, list[SourceCitation]]:
    """
    Filter by score, deduplicate overlapping chunks from the same source,
    and build a context string + citations list.
    """
    seen_sources: dict[str, int] = {}   # source_id → count of chunks used
    context_parts = []
    citations = []

    for match in matches:
        if match.score < MIN_SCORE:
            continue

        m = match.metadata
        source_id = m.get("source_id", "")

        # Allow at most 3 chunks per source to prevent one doc dominating
        if seen_sources.get(source_id, 0) >= 3:
            continue
        seen_sources[source_id] = seen_sources.get(source_id, 0) + 1

        date_str = m.get("date") or "n/d"
        header = f"[Source: {m.get('source_title')} | tier: {m.get('tier')} | date: {date_str}]"
        context_parts.append(f"{header}\n{m.get('text', '')}")

        citations.append(SourceCitation(
            title=m.get("source_title", ""),
            url=m.get("source_url", ""),
            tier=int(m.get("tier", 1)),
            date=m.get("date") or "",
            chunk_index=int(m.get("chunk_index", 0)),
        ))

    context = "\n\n---\n\n".join(context_parts)
    return context, citations


SYSTEM_PROMPT = """\
You are Sky, SCAIO's guide to South Carolina and artificial intelligence. SCAIO is the \
South Carolina Artificial Intelligence Observatory. You answer from SCAIO's published work — \
the flagship report, the primers, the journal, the policy briefs, the bill and policy trackers — \
and from official South Carolina government sources.

Answer questions using ONLY the information in the <context> block below, together with what \
has already been said earlier in this conversation. If the context does not contain enough \
information to answer fully, say so clearly and specifically — do not speculate or draw on \
outside knowledge.

Cite the specific source(s) you draw from using [Source: Title] inline notation.

When you state a count, take it from what a source explicitly says. Do not tally items yourself \
and report the total as fact — if you are listing things, let the list speak rather than \
counting it. If a source gives a number that conflicts with the items you can see, say so \
plainly instead of picking one.

If the user is asking about the conversation itself — following up, correcting you, or asking \
what you meant — answer from the conversation directly. If you got something wrong, say so \
plainly and correct it; do not repeat the error and do not pretend the earlier turn did not happen.

Keep answers concise and factual. Use bullet points for lists of bills, initiatives, or agencies. \
If someone asks who or what you are: you are Sky, and you search SCAIO's published research to answer.\
"""


def build_user_message(question: str, context: str) -> str:
    if not context.strip():
        context = (
            "(No SCAIO sources matched this message. It is most likely a follow-up about "
            "the conversation so far — answer from the earlier turns.)"
        )
    return f"<context>\n{context}\n</context>\n\nQuestion: {question}"


# ── Layer 3: Generate ──────────────────────────────────────────────────────────

def generate(question: str, context: str, history: list["Turn"]) -> str:
    """Call Claude with the augmented prompt, preceded by recent conversation turns."""
    messages = [{"role": t.role, "content": t.content} for t in history[-MAX_HISTORY_TURNS:]]

    # Claude requires the first message to be from the user and roles to alternate.
    while messages and messages[0]["role"] != "user":
        messages.pop(0)

    messages.append({"role": "user", "content": build_user_message(question, context)})

    message = anthropic_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    return message.content[0].text


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    # Layer 1: Retrieve
    matches = retrieve(req.question, req.top_k, req.tier_filter)

    # Layer 2: Augment
    context, citations = build_context(matches)

    # A follow-up ("what do you mean?", "you said 9 but listed 10") rarely retrieves
    # anything on its own, because it is embedded as a standalone search query. Bailing
    # out here would answer every follow-up with the no-corpus line without ever asking
    # Claude. Only short-circuit when there is no conversation to fall back on.
    if len(citations) < MIN_CHUNKS and not req.history:
        return QueryResponse(
            answer=(
                "I don't have enough information in the current corpus to answer that question. "
                "Try rephrasing, or check back as the corpus grows."
            ),
            sources=[],
            chunks_used=0,
        )

    # Layer 3: Generate
    answer = generate(req.question, context, req.history)

    if not req.include_sources:
        citations = []

    return QueryResponse(answer=answer, sources=citations, chunks_used=len(citations))


@app.get("/health")
def health():
    try:
        stats = pinecone_index.describe_index_stats()
        total = stats.total_vector_count
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Pinecone unavailable: {e}")
    return {
        "status": "ok",
        "index": os.environ.get("PINECONE_INDEX_SCAIO", "scaio-policy"),
        "total_vectors": total,
    }


@app.get("/sources")
def sources():
    with open(SOURCES_FILE) as f:
        return json.load(f)


# ── Dev entrypoint ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("execution.api_server_scaio:app", host="0.0.0.0", port=8001, reload=True)
