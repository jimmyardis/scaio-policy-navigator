#!/usr/bin/env python3
"""
SCAIO Policy Navigator — FastAPI RAG Query Server

3-layer architecture:
  Layer 1: Retrieve — embed query via Voyage AI, fetch top-k from Pinecone
  Layer 2: Augment  — deduplicate, filter by score, build context block
  Layer 3: Generate — Claude claude-sonnet-4-6 answers from context only

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

load_dotenv(Path(__file__).parent.parent / ".env")

import voyageai
from pinecone import Pinecone
from anthropic import Anthropic
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ── Config ─────────────────────────────────────────────────────────────────────

VOYAGE_MODEL    = "voyage-3"
CLAUDE_MODEL    = "claude-sonnet-4-6"
MIN_SCORE       = 0.35   # drop chunks below this cosine similarity
MIN_CHUNKS      = 2      # if fewer pass threshold, return "not enough info"
SOURCES_FILE    = Path(__file__).parent.parent / "corpus" / "tier1_sources.json"

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
    title="SCAIO Policy Navigator",
    description="RAG-powered Q&A over South Carolina AI policy corpus",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request / response models ──────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=5, max_length=1000)
    top_k: int = Field(default=8, ge=1, le=20)
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
You are the SCAIO Policy Navigator, an expert assistant on South Carolina artificial intelligence policy, legislation, and ecosystem.

Answer questions using ONLY the information in the <context> block below. \
If the context does not contain enough information to answer fully, say so clearly and specifically — do not speculate or draw on outside knowledge.

Cite the specific source(s) you draw from using [Source: Title] inline notation.

Keep answers concise and factual. Use bullet points for lists of bills, initiatives, or agencies.\
"""


def build_user_message(question: str, context: str) -> str:
    return f"<context>\n{context}\n</context>\n\nQuestion: {question}"


# ── Layer 3: Generate ──────────────────────────────────────────────────────────

def generate(question: str, context: str) -> str:
    """Call Claude with the augmented prompt."""
    message = anthropic_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_message(question, context)}],
    )
    return message.content[0].text


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    # Layer 1: Retrieve
    matches = retrieve(req.question, req.top_k, req.tier_filter)

    # Layer 2: Augment
    context, citations = build_context(matches)

    if len(citations) < MIN_CHUNKS:
        return QueryResponse(
            answer=(
                "I don't have enough information in the current corpus to answer that question. "
                "Try rephrasing, or check back as the corpus grows."
            ),
            sources=[],
            chunks_used=0,
        )

    # Layer 3: Generate
    answer = generate(req.question, context)

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
