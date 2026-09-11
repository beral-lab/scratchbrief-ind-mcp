# IndianKanoon research sidebar for Google Docs

A Docs sidebar add-on that searches IndianKanoon and inserts citations/
snippets at the cursor. It's a thin client over `../api_server.py`, which
itself just imports `../indiankanoon.py` directly (same Chrome instance,
same profile, same Cloudflare-clearance dance as `indiankanoon_mcp.py`).

Not a hosted product — this is scaffolded to run entirely under your own
account: the backend on your machine, the add-on installed only for you.

## Why the backend has to stay local

`browser.py` needs to be able to pop a real, visible Chrome window for the
occasional Cloudflare warm-up, and keeps a persistent profile on disk. That
doesn't fit a stateless cloud container. So: run `api_server.py` on this
machine (where the MCP server already works) and reach it from Apps Script
through a tunnel, rather than porting the scraper to a headless host.

## 1. Run the backend

```bash
cd ..
.venv\Scripts\pip install -r docs-addon\requirements-api.txt
set IK_PROXY_TOKEN=<pick-a-random-secret>
.venv\Scripts\python api_server.py
```

Confirm it's up: `curl http://127.0.0.1:8791/health`.

## 2. Tunnel it

Pick one — either works, a free Cloudflare Quick Tunnel is enough to start:

```bash
cloudflared tunnel --url http://127.0.0.1:8791
```

Note the `https://<random>.trycloudflare.com` URL it prints. (Quick Tunnels
change URL on every restart — fine for testing; for daily use, a named
Cloudflare Tunnel or a reserved ngrok domain avoids re-pasting the URL into
Script Properties each time.)

## 3. Push the Apps Script project

Needs [`clasp`](https://github.com/google/clasp) (`npm install -g @google/clasp`).

```bash
cd docs-addon
clasp login
clasp create --type standalone --title "IndianKanoon Research"
clasp push
```

Use `standalone`, not `docs` -- `--type docs` binds the script to one new
Google Doc it creates for you. This needs to be an unbound (standalone)
script so it installs as an Editor Add-on and shows up under Extensions in
*any* Doc you open, via Test Deployments below.

`clasp create` writes a `.clasp.json` here pointing at the new script.

## 4. Configure the backend URL/token

In the Apps Script editor (`clasp open`): Project Settings (gear icon) →
Script Properties → add `BACKEND_URL` (the tunnel URL from step 2) and
`BACKEND_TOKEN` (the `IK_PROXY_TOKEN` from step 1). Or edit and run
`setBackendConfig_()` in `Code.gs` once instead.

## 5. Install it for yourself

In the Apps Script editor: Deploy → Test deployments → install for your
account. Open any Google Doc, and it'll appear under Extensions (or the
add-ons side panel) as "IndianKanoon Research."

## Using it

Type a query (or hit "Search from selection/cursor" to search on whatever
you're currently writing) and hit Search. Each result has:
- **Insert citation** / **Insert snippet** — drop text at the cursor
- **View full text** — jumps straight to the passage the result matched on
  (via `/doc/{id}/locate`), with the exact AI-tagged Issue/Reasoning/
  Analysis excerpts (when IndiaKanoon has them) insertable individually
- **Cited by (N)** / **Cites (N)** — walk the real citation graph
- **"AI check: which of these actually help my draft?"** (below the
  results) — sends your draft + the results to a local LLM (see below) to
  judge actual relevance and draft an insertable, cited sentence

Below the search box, three more tools (loosely modeled on Lexis for
Microsoft Office's Word ribbon, minus the two features that need licensed
content we have no source for — Shepard's-style "is this still good law"
validation, and practitioner Guidance notes):

- **Find citations in doc** — scans the WHOLE document (not just search
  results) for citation-shaped text: AIR/SCC/SCC OnLine/neutral citations,
  slash-delimited case numbers ("C/SCA/5236/2024"), and case names
  (handles "M/S " prefixes, "v."/"vs"/"versus", "& Ors.", parentheticals
  like "(M.P.)" — broadened against the user's own real scraped-judgment
  text, which the first version caught almost none of). Auto-runs the
  first time you open the panel, rather than waiting for a click.
  Heuristic pattern matching, like Lexis's own Find All — not full NLP —
  so it will miss unusual formats, and confirmed live gaps worth knowing:
  - Court/tribunal case-number formats are too heterogeneous to enumerate;
    only the slash-delimited shape is caught (a space-separated one like
    "CA D.33686/2023" isn't).
  - Scraped text with ZERO space between two unrelated capitalized words
    (a source-page markup artifact, not something we introduce) can fuse
    them into one false match — not fixable by pattern matching alone.
  - A real bug caught and fixed during testing: matches could bridge
    across a paragraph break and silently fuse the end of one paragraph
    with the start of a later one, because `\s` in the pattern also
    matches the newline `editAsText()` inserts between paragraphs — fixed
    by requiring same-paragraph whitespace between words in a case name.

  Every match is **highlighted directly in the document text** (a real
  yellow background applied to the exact span, confirmed live) — not just
  listed in the sidebar, closer to how a flagged item actually looks in
  Grammarly. Re-scanning clears the previous scan's highlights first, and
  there's a manual "Clear highlights" button. Real platform ceiling worth
  being upfront about: this is scan-then-highlight, not live-as-you-type —
  Docs exposes no edit/keystroke event an Add-on can listen for, and there's
  no way to show a hover card at a specific point in the canvas-rendered
  text, only actual text formatting. So it can't be a true Grammarly clone;
  this is the closest equivalent the platform allows.

  Each match also gets:
  - **Check format** — flags whether it's structurally well-formed for its
    type (spacing/structure only, not a full citation-style validator)
  - **Search & link** — searches IndianKanoon for that exact text and, once
    you pick the right result, hyperlinks the ORIGINAL matched text in the
    document to it in place (via `Text.setLinkUrl`) — confirmed against a
    real Doc: the link lands on exactly the matched span, not a character
    off in either direction, and a trailing comma right after a case name
    is correctly left out of the link. Known limit: this is a plain
    keyword search, so an exact case name isn't guaranteed to surface that
    exact case first among the results — always check which result you're
    actually linking to.
- **Folders** — save search results into named folders (`PropertiesService`,
  per-user, no backend involved) for later reuse across sessions. Each
  saved item can be re-inserted (through the same Cite format template) or
  removed.
- **Cite format** — one editable template (`{title} {court} {citations}
  {url} {doc_id}`) that every citation insert goes through — from search
  results, Folders, or anywhere else — so they're all worded consistently
  instead of each button having its own ad-hoc format.

## Optional: the "AI check" feature needs Ollama

That one feature calls a local model through [Ollama](https://ollama.com)
rather than any hosted API — no account, no key, works offline. Everything
else above works without this.

```bash
# after installing Ollama:
ollama pull qwen2.5:3b
```

`api_server.py` calls `http://127.0.0.1:11434` by default (override with
`OLLAMA_URL`) and `qwen2.5:3b` by default (override with `OLLAMA_MODEL`).
Confirmed by hand on a 7.6GB-RAM, no-GPU laptop: an 8B model thrashes to
disk and becomes unusable (~5.5s/token); 3B is the practical ceiling on
modest hardware, at tens of seconds per call. On better hardware, a larger
model will reason more reliably.

**This is genuinely weaker than a hosted model** — in testing it flipped
its own answer on the same input between runs. Treat its relevance calls
and drafts as a starting point to verify, not a citation to trust outright.

## Known limits

- Backend calls are serialized by `browser.py`'s lock — one search or
  document fetch at a time, same as the MCP server.
- Whoever holds `BACKEND_TOKEN` can query IndianKanoon through your local
  Chrome profile — keep the tunnel URL and token out of anywhere shared.
- The "AI check" feature's quality is capped by whatever Ollama model fits
  on this machine — see above.
- Find All is regex-based recognition, not NLP — it won't catch every
  citation format, and "Search & link" is a plain keyword search against
  IndianKanoon, so an exact case name doesn't guarantee the exact case is
  among the top results (confirmed: searching the literal text of a famous
  case name surfaced other, unrelated cases first) — always check which
  result you're actually linking to before confirming.
- Folders are stored one JSON blob per user under `PropertiesService`,
  capped around 9KB total — good for a research session's worth of saves,
  not an unbounded archive.
