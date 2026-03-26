# SCAIO Policy Navigator — RAG Query API SOP

## Purpose

Expose a FastAPI endpoint that accepts a natural-language question, retrieves the top-k relevant chunks from Pinecone, and returns a grounded answer via Claude claude-sonnet-4-6.

---

## Architecture (3-layer)

```
User question
     │
     ▼
[Layer 1] Retrieval
     │  Embed query via Voyage AI (voyage-3, input_type="query")
     │  Query Pinecone scaio-policy index, top_k=8
     │  Optional: filter by tier, date range, tags
     ▼
[Layer 2] Augmentation
     │  Build context block from retrieved chunk texts + metadata
     │  Deduplicate overlapping chunks from same source
     │  Inject into system prompt as <context> XML block
     ▼
[Layer 3] Generation
     │  Claude claude-sonnet-4-6 with structured system prompt
     │  Returns: answer + cited sources list
     ▼
JSON response to client
```

---

## Endpoints

### `POST /query`

**Request body:**
```json
{
  "question": "What AI legislation has SC passed in 2024?",
  "top_k": 8,
  "tier_filter": null,
  "include_sources": true
}
```

**Response:**
```json
{
  "answer": "...",
  "sources": [
    {
      "title": "SC H.5253 — AI in Education",
      "url": "https://...",
      "tier": 1,
      "date": "2024",
      "chunk_index": 3
    }
  ],
  "chunks_used": 6
}
```

### `GET /health`

Returns `{"status": "ok", "index": "scaio-policy", "total_vectors": N}`.

### `GET /sources`

Returns the contents of `corpus/tier1_sources.json` for the frontend to display available sources.

---

## System prompt structure

```
You are the SCAIO Policy Navigator, an expert assistant on South Carolina AI policy.
Answer questions using ONLY the provided context. If the context does not contain
enough information, say so clearly — do not speculate.

Always cite the specific source(s) you draw from using [Source: Title] notation.

<context>
{retrieved chunks, each prefaced with [Source: title | tier: N | date: YYYY]}
</context>
```

---

## Implementation file

`execution/api_server_scaio.py` — separate from the museum API server.

```python
from fastapi import FastAPI
from pydantic import BaseModel
app = FastAPI(title="SCAIO Policy Navigator")
```

Run: `uvicorn execution.api_server_scaio:app --port 8001`

---

## Environment variables required

```
VOYAGE_API_KEY
PINECONE_API_KEY
PINECONE_INDEX_SCAIO   # = scaio-policy
ANTHROPIC_API_KEY
```

---

## Retrieval quality guidelines

- `top_k=8` is the baseline; increase to 12 for broad policy questions.
- Use `tier_filter=1` to restrict to authoritative SC government sources.
- Context window budget: 8 chunks × ~600 tokens ≈ 4,800 tokens. Well within Claude's window.
- Minimum relevance score threshold: `0.35` (cosine similarity). Chunks below this are excluded. Note: Voyage AI cosine scores on a small policy corpus typically land in the 0.45–0.55 range for on-topic queries — 0.70 would exclude everything.
- If fewer than 2 chunks clear threshold, return a "not enough information" response rather than hallucinating.

---

## Extending the API

- **Date filter**: pass `date_gte` / `date_lte` params; translated to Pinecone metadata filter `{"date": {"$gte": "2024"}}`.
- **Tag filter**: `{"tags": {"$in": ["legislation"]}}`.
- **Multi-index fan-out**: query both `scaio-policy` and a future `scaio-news` index, merge results by score.
- **Streaming**: use `anthropic.messages.stream()` and `StreamingResponse` from FastAPI.
