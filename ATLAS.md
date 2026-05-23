# ATLAS.md

> This file is maintained by Claude Code and read by Atlas (your AI Chief of Staff).
> You don't need to edit it manually — Claude Code updates it at the end of each work session.

## Meta

| Field | Value |
|-------|-------|
| **Project** | SCAIO Policy Navigator |
| **One-liner** | SC AI policy navigator RAG chatbot over 11 SC government policy sources |
| **Status** | shipping |
| **Last Active** | 2026-05-23 |
| **Stall Threshold** | 14 days |
| **Repo** | https://github.com/jimmyardis/scaio-policy-navigator |
| **Stack** | FastAPI, Railway, Pinecone (voyage-3, 1024-dim), Voyage AI, Claude claude-sonnet-4-6, HTML/JS |

## Current State

Live at `web-production-015441.up.railway.app`. 11 Tier 1 SC policy sources ingested (37 Pinecone vectors). Endpoints `/ask`, `/health`, `/sources`, `/query`, `widget.html`, and `embed.js` all working. Last commit was 2026-03-26 — no active development in ~2 months, but the service is stable.

## Next Action

Expand the corpus by adding more SC government + SCAIO sources to `corpus/tier1_sources.json` and re-running `python execution/ingest.py`.

## Blockers

- None

## Open Questions

- Should this share infrastructure with the HUD Compliance Suite (same Railway project, shared Postgres)?
- Is there a v2 scope or is this feature-complete as a standalone widget?

## Session Log

<!-- Append-only. Most recent session on top. Claude Code adds an entry at the end of each work session. -->

### 2026-05-23

- Created ATLAS.md for project tracking
- No code changes this session — file placement only
