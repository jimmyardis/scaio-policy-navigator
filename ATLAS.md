# ATLAS.md

> This file is maintained by Claude Code and read by Atlas (your AI Chief of Staff).
> You don't need to edit it manually — Claude Code updates it at the end of each work session.

## Meta

| Field | Value |
|-------|-------|
| **Project** | SCAIO Policy Navigator |
| **One-liner** | SC AI policy navigator RAG chatbot over 11 SC government policy sources |
| **Status** | shipping |
| **Last Active** | 2026-09-23 |
| **Stall Threshold** | 14 days |
| **Repo** | https://github.com/jimmyardis/scaio-policy-navigator |
| **Site repo** | https://github.com/jimmyardis/scaio (GitHub Pages → www.scaio.org) |
| **Railway** | project `imaginative-abundance`, service `web` (auto-deploys on push) |
| **Stack** | FastAPI, Railway, Pinecone (voyage-3, 1024-dim), Voyage AI, Claude Haiku 4.5, HTML/JS |

## Current State

**Deployed on scaio.org as "Sky."** The assistant was renamed from "SC AI Policy
Navigator" to Sky across the widget, the `/ask` page and the system prompt — the
old name undersold a corpus that covers the whole observatory, not just policy.
Sky now carries conversation memory (last 6 turns) and can answer follow-ups,
corrections and questions about itself.

Corpus is 52 sources / ~216 vectors. A latent ingest bug was found and fixed:
trafilatura was discarding every heading that sits inside a link wrapper, which
on scaio.org meant all primer card titles and all section headings. Local pages
now extract through a structure-preserving pass, and all 39 site sources were
re-ingested; chunk counts rose materially (chapter 6: 3 → 9).

`ask.scaio.org` is still not serving. See Blockers — it now needs a one-line DNS
change at Namecheap.

## Next Action

Update the `ask` CNAME at Namecheap to the **new** target
`xqal1j57.up.railway.app`, then flip `NAVIGATOR_ORIGIN` in `assets/navigator.js`
(site repo) from the Railway hostname to `https://ask.scaio.org`.

## Blockers

- `ask.scaio.org` needs its Namecheap CNAME changed from
  `mduwwnnz.up.railway.app` to **`xqal1j57.up.railway.app`**. The original
  custom-domain entry had gone stale on Railway's side: DNS was correct and
  Railway reported `syncStatus: ACTIVE`, but its edge returned "Application not
  found" for `Host: ask.scaio.org` while serving the same edge IP correctly for
  the service hostname, so ownership validation could never complete.
  `customDomainIssueCertificate` did not clear it; deleting and re-creating the
  domain did, and the re-created entry was assigned a different edge host.

## Open Questions

- Should this share infrastructure with the HUD Compliance Suite (same Railway project, shared Postgres)?
- Re-ingest cadence: the corpus is a manual `ingest.py` run. Worth a cron once
  the site publishes on a regular schedule?
- Corpus freshness — the 126th General Assembly adjourned sine die 2026-05-14;
  the tracker JSON was last updated 2026-06-05.

## Session Log

<!-- Append-only. Most recent session on top. Claude Code adds an entry at the end of each work session. -->

### 2026-09-23

- **Renamed the assistant to Sky** across widget, `/ask`, embed labels and the
  system prompt. Sky introduces itself and knows its own name.
- **Added conversation memory.** `/query` was stateless, so a follow-up like
  "you listed 10 but said 9" was embedded as a standalone search query, matched
  nothing above `MIN_SCORE`, failed the `MIN_CHUNKS` gate and returned the
  no-corpus line **without Claude ever being called**. Requests now carry recent
  turns; the thin-retrieval short-circuit only fires when there is no
  conversation to fall back on.
- **Fixed identity questions.** "Who are you?" retrieves nothing, so it hit the
  same short-circuit on a fresh thread. Recognised meta-questions now bypass it;
  off-corpus questions ("capital of France?") still short-circuit.
- **Root-caused a bad answer to an ingest bug, not a model bug.** The primer
  count was wrong because `trafilatura` drops headings inside link wrappers —
  the Learn hub was indexed as description paragraphs with no titles at all.
  Replaced the local-HTML extractor with a structure-preserving pass and
  re-ingested all 39 site sources. This had been degrading every site-sourced
  answer, not just this one.
- Stripped stale "Primer NN —" prefixes from corpus source titles so Sky's
  citations match what a reader sees on the page.
- Site work (site repo): unified all primers into one un-numbered "Primers"
  section including the two AI Safety primers, which had been orphaned from the
  Learn hub; corrected two stale status labels (Journal "Coming Soon" with ten
  articles published; report labelled Edition 0.1 with 0.2 content); published a
  new **county-council primer** built from SCAIO's own infrastructure reporting.
- **Diagnosed `ask.scaio.org`.** Serving Railway's `*.up.railway.app` wildcard
  cert and "Application not found" from the edge. Deleted and re-created the
  custom domain, which produced a new required CNAME target. Left pending on the
  registrar change — see Blockers.
- Decision: did **not** flip `NAVIGATOR_ORIGIN` to `ask.scaio.org`. Pointing the
  live widget at a hostname without a working cert would break chat on all 37
  pages.

### 2026-09-19

- Published "Everywhere at Once" (SC Senate AI committee commentary) on
  scaio.org in the journal template; added it to `corpus/tier1_sources.json`
  and ingested (3 vectors) plus re-ingested `site-home` (5). Verified live:
  `/query` about the committee chair answers from the new article.
- Built the SCAIO content agent in the **site** repo (not here): monitor →
  fact-verified draft → PR → Telegram digest; LinkedIn/Facebook posting on
  merge, dormant until credentials exist. Test PR jimmyardis/scaio#1.
- Gotcha: `gh auth token` returns `$GITHUB_TOKEN` when set, and `~/.env`'s
  GITHUB_TOKEN is stale for these repos — pushes here need
  `env -u GITHUB_TOKEN` or the gh credential helper.
- Left for later: content-agent Phase 3 (auto-ingest merged posts here) —
  directive says ask before changing the Railway deployment.

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
