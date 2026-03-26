# SCAIO Policy Navigator — Ingestion Pipeline SOP

## Purpose

Transform raw policy sources (URLs and PDFs) into Pinecone vector chunks that the RAG query layer can retrieve at inference time. Every chunk carries structured metadata so queries can filter by tier, date, or source.

---

## Inputs

| Type | How supplied |
|------|-------------|
| Web URLs | `corpus/tier1_sources.json` → `url` field |
| PDFs (remote) | `corpus/tier1_sources.json` → `url` ends in `.pdf` |
| PDFs (local) | `corpus/tier1_sources.json` → `local_path` field |

### Source JSON schema

```json
{
  "id": "unique-slug",
  "title": "Human-readable title",
  "url": "https://...",
  "local_path": null,
  "tier": 1,
  "date": "YYYY-MM-DD or YYYY or null",
  "tags": ["legislation", "ai-strategy", ...]
}
```

Tier meanings:
- **Tier 1** — Primary SC government sources and scaio.org content (authoritative)
- **Tier 2** — Secondary coverage, federal guidance, national context
- **Tier 3** — Background / supporting / news

---

## Outputs

Upserted vectors in Pinecone index `scaio-policy` with metadata:

| Field | Type | Description |
|-------|------|-------------|
| `source_id` | str | Slug from sources JSON |
| `source_title` | str | Human-readable title |
| `source_url` | str | Canonical URL |
| `date` | str | ISO date or year string |
| `tier` | int | 1, 2, or 3 |
| `chunk_index` | int | 0-based chunk position within source |
| `chunk_total` | int | Total chunks for this source |
| `text` | str | Raw chunk text (stored in metadata for retrieval) |

---

## Pipeline steps

```
source_list.json
      │
      ▼
[1] Fetch & extract
      │  URL → trafilatura (html→text) or requests+BS4 fallback
      │  PDF → pdfplumber (page→text concat)
      ▼
[2] Chunk
      │  600-token target, 100-token overlap
      │  Tokenizer: tiktoken cl100k_base
      │  Min chunk: 50 tokens (drop trailing remnants below threshold)
      ▼
[3] Embed
      │  Model: voyage-3 via voyageai Python SDK
      │  Batch size: 96 texts per API call (SDK default)
      │  Output dimension: 1024
      ▼
[4] Upsert to Pinecone
         Index: scaio-policy (serverless, us-east-1)
         ID format: {source_id}_chunk_{chunk_index:04d}
         Batch size: 100 vectors per upsert call
```

---

## Running the pipeline

```bash
# Full run (all sources in tier1_sources.json)
source venv/bin/activate
python execution/ingest.py

# Dry run (fetch + chunk, no embed/upsert)
python execution/ingest.py --dry-run

# Single source by id
python execution/ingest.py --id sc-house-ai-committee

# Skip already-ingested sources (checks Pinecone for existing IDs)
python execution/ingest.py --skip-existing
```

---

## Environment variables required

```
VOYAGE_API_KEY        # Voyage AI dashboard
PINECONE_API_KEY      # Pinecone console
PINECONE_INDEX_SCAIO  # = scaio-policy
```

---

## Error handling & self-annealing

- **Fetch failure**: log warning, continue to next source. Re-runnable.
- **Empty extract**: skip source, log `[SKIP] empty content: {title}`.
- **Voyage rate limit (429)**: exponential backoff, max 5 retries.
- **Pinecone upsert error**: retry up to 3×, then log and continue.
- Re-running is safe: Pinecone upsert is idempotent (same vector ID overwrites).

---

## Verification

After ingest, run the spot-check query:

```bash
python execution/ingest.py --verify
```

This queries Pinecone with "South Carolina artificial intelligence policy" and prints the top-3 chunks with metadata. Confirm `tier`, `source_title`, and `text` look correct.

---

## Adding new sources

1. Add entry to `corpus/tier1_sources.json` (or create `corpus/tier2_sources.json`).
2. Run `python execution/ingest.py --id <new-slug>`.
3. Verify with `--verify`.
4. Commit updated sources JSON.
