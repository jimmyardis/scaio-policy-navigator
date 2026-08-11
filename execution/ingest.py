#!/usr/bin/env python3
"""
SCAIO Policy Navigator — Corpus Ingestion Pipeline

Fetches each source (URL or PDF), chunks at 600 tokens with 100-token overlap,
embeds via Voyage AI (voyage-3), and upserts to Pinecone index 'scaio-policy'.

Usage:
    python execution/ingest.py                        # full run
    python execution/ingest.py --dry-run              # fetch+chunk only, no embed/upsert
    python execution/ingest.py --id sc-house-ai-committee
    python execution/ingest.py --skip-existing        # skip IDs already in Pinecone
    python execution/ingest.py --verify               # spot-check query after ingest
"""

import argparse
import json
import os
import sys
import time
import io
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ── Config ─────────────────────────────────────────────────────────────────────

CHUNK_TOKENS   = 600
OVERLAP_TOKENS = 100
MIN_CHUNK_TOKENS = 50
EMBED_BATCH    = 96    # Voyage AI max texts per batch
UPSERT_BATCH   = 100   # Pinecone max vectors per upsert
VOYAGE_MODEL   = "voyage-3"
EMBED_DIM      = 1024

SOURCES_FILE = Path(__file__).parent.parent / "corpus" / "tier1_sources.json"

# Local checkout of the scaio.org site repo (jimmyardis/scaio). Sources with a
# `site_path` are read from here rather than fetched over HTTP, so ingestion
# tracks `main` instead of whatever GitHub Pages happens to be serving.
SITE_ROOT = Path(os.environ.get("SCAIO_SITE_ROOT", Path.home() / "scaio"))

# ── Imports after config (give dotenv a chance to run) ─────────────────────────

import tiktoken
import trafilatura
import requests
from bs4 import BeautifulSoup
import pdfplumber
import voyageai
from pinecone import Pinecone

# ── Init clients ───────────────────────────────────────────────────────────────

def init_clients():
    voyage_key  = os.environ.get("VOYAGE_API_KEY", "").strip()
    pinecone_key = os.environ.get("PINECONE_API_KEY", "").strip()
    index_name  = os.environ.get("PINECONE_INDEX_SCAIO", "scaio-policy").strip()

    if not voyage_key:
        print("[ERROR] VOYAGE_API_KEY not set in .env — cannot embed.")
        sys.exit(1)
    if not pinecone_key:
        print("[ERROR] PINECONE_API_KEY not set in .env — cannot upsert.")
        sys.exit(1)

    vc = voyageai.Client(api_key=voyage_key)
    pc = Pinecone(api_key=pinecone_key)
    index = pc.Index(index_name)
    return vc, index

# ── Tokenizer ──────────────────────────────────────────────────────────────────

ENC = tiktoken.get_encoding("cl100k_base")

def tokenize(text: str) -> list[int]:
    return ENC.encode(text)

def detokenize(tokens: list[int]) -> str:
    return ENC.decode(tokens)

# ── Fetch ──────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SCAIO-Ingest/1.0; +https://scaio.org)"
    )
}

def fetch_url(url: str) -> str | None:
    """Fetch a URL and return clean text. Returns None on failure."""
    try:
        # Try trafilatura first (best for article/policy pages)
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(
                downloaded,
                include_tables=True,
                include_links=False,
                no_fallback=False,
            )
            if text and len(text.strip()) > 200:
                return text.strip()

        # Fallback: requests + BS4
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        if text and len(text.strip()) > 200:
            return text.strip()

        print(f"  [SKIP] empty content after fetch: {url}")
        return None

    except Exception as e:
        print(f"  [WARN] fetch failed for {url}: {e}")
        return None


def fetch_pdf_url(url: str) -> str | None:
    """Download a PDF from URL and extract text via pdfplumber."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return extract_pdf_bytes(resp.content, url)
    except Exception as e:
        print(f"  [WARN] PDF fetch failed for {url}: {e}")
        return None


def extract_pdf_bytes(data: bytes, label: str = "") -> str | None:
    """Extract text from PDF bytes using pdfplumber."""
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = []
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
            text = "\n\n".join(pages)
            if len(text.strip()) > 200:
                return text.strip()
            print(f"  [SKIP] empty PDF content: {label}")
            return None
    except Exception as e:
        print(f"  [WARN] PDF parse failed for {label}: {e}")
        return None


def extract_pdf_local(path: str) -> str | None:
    """Extract text from a local PDF file."""
    try:
        with open(path, "rb") as f:
            return extract_pdf_bytes(f.read(), path)
    except Exception as e:
        print(f"  [WARN] local PDF read failed for {path}: {e}")
        return None


def extract_html_local(path: Path) -> str | None:
    """Extract readable text from a local HTML file."""
    try:
        html = path.read_text(encoding="utf-8", errors="replace")
        text = trafilatura.extract(
            html,
            include_tables=True,
            include_links=False,
            no_fallback=False,
        )
        if text and len(text.strip()) > 200:
            return text.strip()
        print(f"  [SKIP] empty content after extract: {path}")
        return None
    except Exception as e:
        print(f"  [WARN] local HTML read failed for {path}: {e}")
        return None


# ── JSON trackers ──────────────────────────────────────────────────────────────
#
# bills.json and policy-developments.json drive the /policy tracker client-side,
# so HTML extraction sees an empty page. These build one self-contained record
# per bill / development instead of chunking a blob, and each record carries its
# own citation metadata so the retriever treats bills as independent sources
# rather than collapsing them under one per-source cap.

def _fmt(label: str, value) -> str:
    if not value:
        return ""
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    return f"{label}: {value}\n"


def build_bill_records(data: dict, source: dict) -> list[dict]:
    session = data.get("session", "")
    note    = data.get("session_note", "")
    updated = data.get("last_updated", "")
    records = []

    for bill in data.get("bills", []):
        num   = bill.get("bill_number", "")
        title = bill.get("title", "")
        text = (
            f"South Carolina AI legislation tracker — {num}: {title}\n"
            f"Session: {session}\n"
            + _fmt("Status", bill.get("status"))
            + _fmt("Last action", bill.get("last_action_date"))
            + _fmt("Sponsors", bill.get("sponsors"))
            + _fmt("Impact score (1-10)", bill.get("impact_score"))
            + f"\n{bill.get('summary', '')}\n"
            + (f"\n{bill.get('explanation', '')}\n" if bill.get("explanation") else "")
            + f"\nSession note: {note}\n"
            f"Tracker last updated: {updated}"
        )
        records.append({
            "text":      text.strip(),
            "record_id": f"{source['id']}-{num.replace('.', '').lower()}",
            "title":     f"SCAIO Bill Tracker — {num} {title}",
            "url":       bill.get("url") or source.get("url", ""),
            "date":      bill.get("last_action_date", ""),
        })
    return records


def build_development_records(data: dict, source: dict) -> list[dict]:
    updated = data.get("last_updated", "")
    records = []

    for dev in data.get("developments", []):
        text = (
            f"South Carolina AI policy development — {dev.get('title', '')}\n"
            + _fmt("Type", dev.get("type_label") or dev.get("type"))
            + _fmt("Date", dev.get("date_label") or dev.get("date"))
            + _fmt("Status", dev.get("status"))
            + _fmt("Issuing body", dev.get("source"))
            + f"\n{dev.get('summary', '')}\n"
            f"\nTracker last updated: {updated}"
        )
        records.append({
            "text":      text.strip(),
            "record_id": f"{source['id']}-{dev.get('id', len(records))}",
            "title":     f"SCAIO Policy Tracker — {dev.get('title', '')}",
            "url":       dev.get("url") or source.get("url", ""),
            "date":      dev.get("date", ""),
        })
    return records


JSON_BUILDERS = {
    "json_bills":        build_bill_records,
    "json_developments": build_development_records,
}


def fetch_source(source: dict) -> str | list[dict] | None:
    """
    Route fetch based on source type.

    Returns raw text (to be chunked), a list of pre-formed record dicts
    (already chunk-sized, with their own citation metadata), or None.
    """
    url        = source.get("url", "")
    local_path = source.get("local_path")
    site_path  = source.get("site_path")
    fmt        = source.get("format", "")

    if fmt in JSON_BUILDERS:
        path = SITE_ROOT / site_path if site_path else None
        try:
            if path:
                data = json.loads(path.read_text(encoding="utf-8"))
            else:
                resp = requests.get(url, headers=HEADERS, timeout=30)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            print(f"  [WARN] JSON load failed for {site_path or url}: {e}")
            return None
        return JSON_BUILDERS[fmt](data, source)

    if site_path:
        return extract_html_local(SITE_ROOT / site_path)

    if local_path:
        return extract_pdf_local(local_path)

    if url.lower().endswith(".pdf"):
        return fetch_pdf_url(url)

    return fetch_url(url)

# ── Chunker ────────────────────────────────────────────────────────────────────

def chunk_text(text: str) -> list[str]:
    """
    Split text into chunks of ~CHUNK_TOKENS with OVERLAP_TOKENS overlap.
    Returns list of decoded chunk strings.
    """
    tokens = tokenize(text)
    chunks = []
    start = 0
    step = CHUNK_TOKENS - OVERLAP_TOKENS  # advance by non-overlapping portion

    while start < len(tokens):
        end = start + CHUNK_TOKENS
        chunk_tokens = tokens[start:end]
        if len(chunk_tokens) >= MIN_CHUNK_TOKENS:
            chunks.append(detokenize(chunk_tokens))
        start += step

    return chunks

# ── Embedder ───────────────────────────────────────────────────────────────────

def embed_texts(vc: voyageai.Client, texts: list[str]) -> list[list[float]]:
    """Embed texts in batches via Voyage AI with retry on rate limit."""
    all_embeddings = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i : i + EMBED_BATCH]
        for attempt in range(6):
            try:
                result = vc.embed(batch, model=VOYAGE_MODEL, input_type="document")
                all_embeddings.extend(result.embeddings)
                break
            except Exception as e:
                if "429" in str(e) or "rate" in str(e).lower():
                    wait = 2 ** attempt
                    print(f"  [RATE LIMIT] waiting {wait}s...")
                    time.sleep(wait)
                else:
                    raise
    return all_embeddings

# ── Pinecone upsert ────────────────────────────────────────────────────────────

def upsert_chunks(
    index,
    source: dict,
    chunks: list,
    embeddings: list[list[float]],
):
    """
    Upsert chunk vectors into Pinecone.

    `chunks` is either a list of plain strings (chunked prose) or a list of
    record dicts from a JSON tracker, which carry their own id/title/url and
    are indexed as independent sources.
    """
    vectors = []
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        if isinstance(chunk, dict):
            vec_id = chunk["record_id"]
            meta = {
                "source_id":    chunk["record_id"],
                "source_title": chunk["title"],
                "source_url":   chunk.get("url", ""),
                "date":         chunk.get("date") or "",
                "text":         chunk["text"],
            }
        else:
            vec_id = f"{source['id']}_chunk_{i:04d}"
            meta = {
                "source_id":    source["id"],
                "source_title": source["title"],
                "source_url":   source.get("url", ""),
                "date":         source.get("date") or "",
                "text":         chunk,
            }

        meta.update({
            "tier":        source.get("tier", 1),
            "chunk_index": i,
            "chunk_total": len(chunks),
        })
        vectors.append({"id": vec_id, "values": emb, "metadata": meta})

    for i in range(0, len(vectors), UPSERT_BATCH):
        batch = vectors[i : i + UPSERT_BATCH]
        for attempt in range(4):
            try:
                index.upsert(vectors=batch)
                break
            except Exception as e:
                if attempt == 3:
                    print(f"  [ERROR] upsert failed after retries: {e}")
                else:
                    time.sleep(2 ** attempt)

# ── Existing ID check ──────────────────────────────────────────────────────────

def prune_source(index, source_id: str) -> int:
    """
    Delete every existing vector belonging to a source before re-upserting it.

    Both id schemes are prefixed with the source id, so a prefix list covers
    prose chunks and JSON records alike. Without this, a page that shrinks (or
    a bill dropped from the tracker) leaves orphan vectors behind forever.
    """
    # Both prefixes end in a separator so sibling ids that merely start with
    # this source id (site-report vs site-report-chapter-01) are never caught.
    try:
        stale = []
        for prefix in (f"{source_id}_chunk_", f"{source_id}-"):
            for page in index.list(prefix=prefix, limit=99):
                stale.extend(page if isinstance(page, list) else [page])
        if stale:
            for i in range(0, len(stale), UPSERT_BATCH):
                index.delete(ids=stale[i : i + UPSERT_BATCH])
        return len(stale)
    except Exception as e:
        print(f"  [WARN] prune failed for {source_id}: {e}")
        return 0


def source_exists_in_pinecone(index, source_id: str) -> bool:
    """Check if at least one chunk for this source_id exists in Pinecone."""
    try:
        first_id = f"{source_id}_chunk_0000"
        result = index.fetch(ids=[first_id])
        return first_id in (result.vectors or {})
    except Exception:
        return False

# ── Verify ─────────────────────────────────────────────────────────────────────

def verify(vc: voyageai.Client, index):
    query = "South Carolina artificial intelligence policy"
    print(f"\n[VERIFY] Querying: '{query}'")
    emb = embed_texts(vc, [query])[0]
    results = index.query(vector=emb, top_k=3, include_metadata=True)
    for match in results.matches:
        m = match.metadata
        print(f"\n  score={match.score:.4f}")
        print(f"  id:    {match.id}")
        print(f"  title: {m.get('source_title')}")
        print(f"  tier:  {m.get('tier')}  date: {m.get('date')}")
        print(f"  chunk: {m.get('chunk_index')}/{m.get('chunk_total')}")
        print(f"  text:  {m.get('text', '')[:300]}...")

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SCAIO corpus ingestion")
    parser.add_argument("--dry-run",       action="store_true", help="fetch+chunk only, no embed/upsert")
    parser.add_argument("--id",            type=str, default=None, help="ingest only this source id")
    parser.add_argument("--skip-existing", action="store_true", help="skip sources already in Pinecone")
    parser.add_argument("--verify",        action="store_true", help="run spot-check query after ingest")
    args = parser.parse_args()

    # Load sources
    with open(SOURCES_FILE) as f:
        sources = json.load(f)

    if args.id:
        sources = [s for s in sources if s["id"] == args.id]
        if not sources:
            print(f"[ERROR] No source with id='{args.id}' found.")
            sys.exit(1)

    # Init clients (skip on dry-run to avoid key requirement)
    vc, index = (None, None)
    if not args.dry_run:
        vc, index = init_clients()

    total_chunks = 0

    for source in sources:
        print(f"\n{'='*60}")
        print(f"[SOURCE] {source['id']} — {source['title']}")
        print(f"  url: {source.get('url', source.get('local_path', 'n/a'))}")

        # Skip check
        if args.skip_existing and index:
            if source_exists_in_pinecone(index, source["id"]):
                print("  [SKIP] already in Pinecone")
                continue

        # Fetch
        fetched = fetch_source(source)
        if not fetched:
            print("  [SKIP] no content extracted")
            continue

        # JSON trackers arrive pre-chunked as records; prose gets chunked here.
        if isinstance(fetched, list):
            chunks = fetched
            print(f"  built {len(chunks)} records (one per tracker entry)")
        else:
            print(f"  fetched {len(fetched):,} chars")
            chunks = chunk_text(fetched)
            print(f"  chunked into {len(chunks)} pieces ({CHUNK_TOKENS}t / {OVERLAP_TOKENS}t overlap)")

        sample = chunks[0]["text"] if isinstance(chunks[0], dict) else chunks[0]

        if args.dry_run:
            print(f"  [DRY RUN] sample chunk 0:")
            print(f"    {sample[:300]}...")
            total_chunks += len(chunks)
            continue

        # Embed
        print(f"  embedding via {VOYAGE_MODEL}...")
        texts = [c["text"] if isinstance(c, dict) else c for c in chunks]
        embeddings = embed_texts(vc, texts)
        print(f"  embedded {len(embeddings)} vectors (dim={len(embeddings[0])})")

        # Replace any prior vectors for this source, then upsert
        removed = prune_source(index, source["id"])
        if removed:
            print(f"  pruned {removed} stale vectors")
        upsert_chunks(index, source, chunks, embeddings)
        print(f"  upserted {len(chunks)} vectors to Pinecone")

        # Print sample chunk metadata
        print(f"\n  --- SAMPLE CHUNK 0 ---")
        print(f"  title: {source['title']}")
        print(f"  tier:  {source['tier']}  date: {source.get('date', '')}")
        print(f"  dim:   {len(embeddings[0])}")
        print(f"  text:  {sample[:400]}...")

        total_chunks += len(chunks)

    print(f"\n{'='*60}")
    print(f"[DONE] Total chunks processed: {total_chunks}")

    if args.verify and not args.dry_run:
        verify(vc, index)


if __name__ == "__main__":
    main()
