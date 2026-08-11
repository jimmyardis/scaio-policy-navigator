# ATLAS.md

> This file is maintained by Claude Code and read by Atlas (your AI Chief of Staff).
> You don't need to edit it manually — Claude Code updates it at the end of each work session.

## Meta

| Field | Value |
|-------|-------|
| **Project** | SCAIO Policy Navigator |
| **One-liner** | SC AI policy navigator RAG chatbot over 11 SC government policy sources |
| **Status** | shipping |
| **Last Active** | 2026-08-10 |
| **Stall Threshold** | 14 days |
| **Repo** | https://github.com/jimmyardis/scaio-policy-navigator |
| **Site repo** | https://github.com/jimmyardis/scaio (GitHub Pages → www.scaio.org) |
| **Railway** | project `imaginative-abundance`, service `web` (auto-deploys on push) |
| **Stack** | FastAPI, Railway, Pinecone (voyage-3, 1024-dim), Voyage AI, Claude Haiku 4.5, HTML/JS |

## Current State

**Deployed on scaio.org.** The chat bubble is live on all 37 pages, verified
end-to-end in a browser on desktop and mobile against the live site.

Corpus went from 11 external sources (37 vectors) to 47 sources (179 vectors).
scaio.org itself had only ever been indexed as 3 chunks of a March homepage
fetch — the flagship report, primers, articles, briefs and safety pages were
absent entirely, and the bill tracker was invisible because /policy renders
client-side from JSON. Both are fixed: site pages ingest from a local checkout
of the site repo, and each bill/development is indexed as its own record.

## Next Action

Add the two DNS records at Namecheap so `ask.scaio.org` resolves, then flip
`NAVIGATOR_ORIGIN` in `assets/navigator.js` (site repo) from the Railway
hostname to `https://ask.scaio.org`.

## Blockers

- `ask.scaio.org` is created on Railway but unverified until DNS is added at
  Namecheap (CNAME `ask` → `mduwwnnz.up.railway.app`, TXT `_railway-verify.ask`
  → `railway-verify=d0876dbd044ca8c57c63bdc8d388106245a7670a565e0ce763f368522bf0918c`).

## Open Questions

- Should this share infrastructure with the HUD Compliance Suite (same Railway project, shared Postgres)?
- Re-ingest cadence: the corpus is a manual `ingest.py` run. Worth a cron once
  the site publishes on a regular schedule?
- Corpus freshness — the 126th General Assembly adjourned sine die 2026-05-14;
  the tracker JSON was last updated 2026-06-05.

## Session Log

<!-- Append-only. Most recent session on top. Claude Code adds an entry at the end of each work session. -->

### 2026-08-10

- **Shipped the navigator onto scaio.org.** Widget live on all 37 pages,
  verified in-browser against the live site (desktop + 390px mobile).
- **Corpus 37 → 179 vectors, 11 → 47 sources.** The site had never really been
  indexed: `scaio-home` was 3 chunks of a March homepage fetch, and the report,
  primers, articles, briefs and safety pages were absent.
- Decision: **site pages ingest from a local clone, not over HTTP.** A Pages
  build had failed on 2026-06-17 and four committed pages had been 404 for
  eight weeks — fetching live would have silently skipped them. `SCAIO_SITE_ROOT`
  points at the checkout; re-ingest requires `git pull` there first.
- Decision: **one Pinecone record per bill/development, with its own
  `source_id`.** `/policy` extracts as 268 chars because the tracker renders
  client-side from JSON. Indexing all 16 bills under a single source id would
  have let the query layer's 3-chunks-per-source cap return at most 3 of them.
- Added `prune_source()` — a source's vectors are deleted before re-upsert, so
  shrunk pages and dropped bills stop leaving orphans.
- Fixed `embed.js`: it resolved `data-widget-src` against the host page, so on
  scaio.org it would have requested `scaio.org/frontend/widget.html` and 404'd.
  Now resolved against the script's own URL. Also clamped the iframe to the
  viewport (it was a fixed 400×600 and overflowed phones).
- CORS narrowed from `*` to the scaio + localhost origins (`ALLOWED_ORIGINS`
  overrides). `top_k` 8 → 12 for the 5× larger corpus.
- Introduced `assets/navigator.js` in the site repo as the single place the
  backend origin is configured, so re-pointing the navigator never means
  editing 37 pages again.
- Pages build recovered on push (the June failure did not recur); the four
  missing pages are live. Root cause of that failure was never identified —
  no Liquid syntax in the repo. Adding `.nojekyll` would rule out the whole
  class, since nothing here needs Jekyll.
- Confirmed Railway auto-deploys `scaio-policy-navigator` on push to main, and
  identified the service as `imaginative-abundance / web`.
- Left mid-stream: `ask.scaio.org` awaits DNS at Namecheap.

### 2026-05-23

- Created ATLAS.md for project tracking
- No code changes this session — file placement only
