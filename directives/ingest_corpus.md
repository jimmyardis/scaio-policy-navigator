# SCAIO Policy Navigator — Ingestion Pipeline SOP

## Purpose

Transform raw policy sources (URLs and PDFs) into Pinecone vector chunks that the RAG query layer can retrieve at inference time. Every chunk carries structured metadata so queries can filter by tier, date, or source.

---

## Inputs

All sources live in `corpus/tier1_sources.json`. The `format` and path fields
decide how a source is fetched:

| Type | How supplied |
|------|-------------|
| Web URLs | `url` field, `format: "html"` |
| PDFs (remote) | `url` ends in `.pdf` |
| PDFs (local) | `local_path` — absolute path |
| scaio.org pages | `site_path` — path relative to `SCAIO_SITE_ROOT`, `format: "html"` |
| scaio.org trackers | `site_path` + `format: "json_bills"` or `"json_developments"` |

### Source JSON schema

```json
{
  "id": "unique-slug",
  "title": "Human-readable title",
  "url": "https://...",
  "local_path": null,
  "site_path": "report/chapter-01-the-setting.html",
  "format": "html",
  "tier": 1,
  "date": "YYYY-MM-DD or YYYY or null",
  "tags": ["legislation", "ai-strategy", ...]
}
```

**No source `id` may be a prefix of another** (`site-report` alongside
`site-report-home` is fine; the pruner keys on `{id}_chunk_` and `{id}-`).

### Why site pages come from a local checkout

`site_path` sources are read from a clone of `jimmyardis/scaio`
(`SCAIO_SITE_ROOT`, default `~/scaio`), not fetched over HTTP. Ingestion then
tracks `main` rather than whatever GitHub Pages happens to be serving — in
Aug 2026 a failed Pages build left four committed pages 404 on the live site
for eight weeks. **Run `git pull` in the site checkout before re-ingesting.**

### JSON trackers

`bills.json` and `policy-developments.json` drive the /policy page
client-side, so HTML extraction of `/policy/` yields ~268 characters and the
bill tracker is invisible to retrieval. These sources bypass the chunker:
each bill / development becomes one self-contained record carrying its own
`source_id`, title and URL, so the query layer's 3-chunks-per-source cap
cannot collapse 16 bills into a single entry.

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
      │  URL       → trafilatura (html→text) or requests+BS4 fallback
      │  PDF       → pdfplumber (page→text concat)
      │  site_path → trafilatura over the local file
      │  json_*    → one pre-formed record per tracker entry
      ▼
[2] Chunk                       (skipped for JSON records — already sized)
      │  600-token target, 100-token overlap
      │  Tokenizer: tiktoken cl100k_base
      │  Min chunk: 50 tokens (drop trailing remnants below threshold)
      ▼
[3] Embed
      │  Model: voyage-3 via voyageai Python SDK
      │  Batch size: 96 texts per API call (SDK default)
      │  Output dimension: 1024
      ▼
[4] Prune, then upsert to Pinecone
         Index: scaio-policy (serverless, us-east-1)
         Prune: delete this source's existing vectors first, so shrunk pages
                and dropped bills don't leave orphans behind
         ID format: {source_id}_chunk_{chunk_index:04d}   (prose)
                    {source_id}-{record-key}              (JSON records)
         Batch size: 100 vectors per upsert call
```

---

## Running the pipeline

```bash
# Full run (all sources in tier1_sources.json)
cd ~/scaio && git pull            # site sources are read from this checkout
cd ~/scaio-policy-navigator
set -a; source ~/.env; set +a     # keys live in ~/.env, not the repo
source ~/venv/bin/activate
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
SCAIO_SITE_ROOT       # optional; clone of jimmyardis/scaio, default ~/scaio
```

---

## Error handling & self-annealing

- **Fetch failure**: log warning, continue to next source. Re-runnable.
- **Empty extract**: skip source, log `[SKIP] empty content: {title}`.
- **Voyage rate limit (429)**: exponential backoff, max 5 retries.
- **Pinecone upsert error**: retry up to 3×, then log and continue.
- Re-running is safe: a source is pruned and re-upserted as a unit, and pruning
  only happens *after* a successful fetch — a failed fetch leaves the existing
  vectors untouched.
- `--skip-existing` probes for `{id}_chunk_0000` and so does not recognise
  JSON-record sources; it will re-ingest them. Harmless, just not skipped.

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
