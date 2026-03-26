# SCAIO Policy Navigator — Frontend SOP

## Purpose

Two chat surfaces — a standalone `/ask` page and an embeddable widget — both powered by the same FastAPI backend. The embed variant can be dropped on any page with a single `<script>` tag.

---

## File layout

```
frontend/
  ask.html      — standalone /ask page (full chrome)
  widget.html   — minimal chat window for iframe embed
  embed.js      — floating bubble injector (one <script> tag)
```

---

## API contract

All frontend files read a single `const API_BASE` at the top of each file. Swap this for the Railway deploy URL at deploy time — no other changes needed.

```js
const API_BASE = 'http://localhost:8001';
```

### Endpoints consumed

| Endpoint | Method | Used in |
|----------|--------|---------|
| `/query` | POST | ask.html, widget.html |
| `/sources` | GET | ask.html (corpus section) |
| `/health` | GET | optional status indicator |

### POST /query payload

```json
{
  "question": "<user input>",
  "top_k": 8,
  "include_sources": true
}
```

### POST /query response

```json
{
  "answer": "...",
  "sources": [{ "title": "", "url": "", "tier": 1, "date": "", "chunk_index": 0 }],
  "chunks_used": 6
}
```

Citations are rendered as clickable links below the answer bubble. Deduplicate by URL before rendering (server may return the same source across multiple chunks).

---

## Component structure — ask.html

```
<body>
  Hero                   — headline + 2-sentence explainer
  HowItWorks             — 3-card strip: Search → Retrieve → Cite
  CorpusSection          — GET /sources → title + link + tier badge
  ChatInterface
    SuggestedChips       — 4 starter questions, hide after first query
    ConversationThread   — alternating user/assistant bubbles
      AssistantBubble    — answer text (markdown-lite) + Citations
    InputBar             — textarea + send button + loading state
</body>
```

---

## Component structure — widget.html

Identical to ChatInterface only. No Hero, HowItWorks, CorpusSection, no nav/footer. Designed for `width:400px; height:600px` iframe. Same API calls.

---

## Embed strategy — embed.js

Injects:
1. A fixed floating button (bottom-right, 60×60px circle, `--color-accent` background)
2. On click: an iframe pointing at `widget.html`, 400×600px, positioned above the button
3. Second click: toggles iframe visibility

Drop on any page:
```html
<script src="/frontend/embed.js"></script>
```

The script reads `data-widget-src` from its own `<script>` tag to allow custom widget URL:
```html
<script src="/frontend/embed.js" data-widget-src="https://example.com/widget.html"></script>
```

---

## Theming — CSS variables

Defined in `:root` in each file. Swap values without touching layout.

```css
:root {
  --color-primary: #1a3a5c;
  --color-accent:  #2e86de;
  --color-bg:      #f8f9fa;
  --color-text:    #1a1a2e;
  --font:          'Inter', sans-serif;
}
```

---

## Markdown rendering

Answers from Claude use `##` headers, `-` bullets, `**bold**`. Use a lightweight renderer:
- Replace `## text` → `<h3>`
- Replace `**text**` → `<strong>`
- Replace `- text` or `* text` → `<li>` inside `<ul>`
- Preserve `\n\n` as paragraph breaks
- No external markdown library — keep the file self-contained.

---

## UX behaviours

- **Loading state**: replace send button with spinner, disable input, show "Searching policy corpus…" placeholder text in a typing bubble
- **Not enough info**: render answer bubble with a muted style and an info icon — distinct from a normal answer
- **Citations**: deduplicate by URL, render as `[1] Title (date)` links below the answer bubble. Each citation is `<a target="_blank" rel="noopener">`.
- **Suggested chips**: 4 starter questions rendered as pill buttons. Hide the chip row after the first query is sent.
- **Scroll**: auto-scroll conversation thread to bottom after each new message pair.
- **Enter to send**: `Shift+Enter` for newline, `Enter` to submit.

---

## CORS

FastAPI server is configured with `allow_origins=["*"]` — no CORS issues expected when serving these files from any origin. If the server is locked down to specific origins later, add the frontend's origin to `allow_origins` in `execution/api_server_scaio.py`.

---

## Deploy checklist

1. Update `API_BASE` in ask.html, widget.html, embed.js to Railway URL
2. Serve static files from FastAPI with `app.mount("/", StaticFiles(directory="frontend"))` or deploy frontend separately (Vercel/Netlify)
3. Update `data-widget-src` in any embed `<script>` tags to point to the deployed widget URL
