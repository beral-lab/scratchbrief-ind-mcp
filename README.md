# scratchbrief-ind-mcp

A local MCP server that searches [IndiaKanoon](https://indiankanoon.org) —
case law from every Indian court and tribunal, PLUS legislation (Central
and State Acts, Rules, Regulations, Ordinances, Notifications), the
Constitution, international treaties, Law Commission reports, Constituent
Assembly Debates, and Lok Sabha/Rajya Sabha material — and fetches full
document text, scraped live via [nodriver](https://github.com/ultrafunkamsterdam/nodriver).

## Setup

```bash
cd scratchbrief-ind-mcp
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Requires an existing Chrome/Chromium install (nodriver finds it
automatically — no separate `playwright install` step needed).

Then add it to Claude Desktop's `claude_desktop_config.json`
(`%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "scratchbrief-ind": {
      "command": "C:\\Users\\HP-LT\\scratchbrief-ind-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\Users\\HP-LT\\scratchbrief-ind-mcp\\indiankanoon_mcp.py"]
    }
  }
}
```

Restart Claude Desktop. You should see `indiankanoon_search`,
`indiankanoon_get_document`, `indiankanoon_get_citations`, and
`indiankanoon_list_doctypes` available as tools.

## Tools exposed

- **indiankanoon_search(query, limit?, doctypes?, fromdate?, todate?, sortby?)**
  — search results with title, court, author, snippet, cites/cited_by
  counts, doc_id, and url. `doctypes` restricts to a category (see below);
  `fromdate`/`todate` are `"DD-MM-YYYY"` (confirmed against IndiaKanoon's own
  advanced-search form); `sortby` is `"relevance"` (default), `"mostrecent"`,
  or `"leastrecent"`. IndiaKanoon's other search operators also work
  directly inside `query`: `cites:<id>`, `citedby:<id>` (prefer
  `indiankanoon_get_citations` for these), `author:<name>`, `bench:<name>`.
- **indiankanoon_get_document(url_or_id, offset?, chars?)** — metadata
  (title, court, author, bench, equivalent citations) plus a slice of full
  text, by doc id or any `/doc/<id>/` / `/docfragment/<id>/` URL. Body text
  is **paginated**, not returned whole — see below.
- **indiankanoon_get_citations(doc_id, direction?, limit?)** — the actual
  cases citing (`direction="citedby"`, default) or cited by
  (`direction="cites"`) a document, for tracing precedent chains — as
  opposed to `search()`'s `cites`/`cited_by` fields, which are just counts.
- **indiankanoon_list_doctypes(category?)** — reference table of every
  `doctypes:` slug IndiaKanoon accepts, optionally filtered to one category.
  Use this to find the exact slug for a specific state/court/tribunal before
  calling `indiankanoon_search`.

## Accurate retrieval on long documents

Judgments can run past **a million characters** — confirmed on the
Puttaswamy privacy judgment (9 separate opinions): 1,012,196 characters,
~7,942 paragraphs. Dumping that whole thing into one MCP response risks
silent truncation by the transport or blowing the caller's context, so
`get_document` handles it deliberately:

- **Pagination** — `offset`/`chars` (default 50,000 chars/call) slice the
  body; the response's `total_chars` and `has_more` tell you whether/where
  to page further, same pattern as reading a long file in chunks.
- **`key_excerpts`** — IndiaKanoon's own "Prism" AI tagging labels specific
  passages in some judgments as `Issue` / `Court's Reasoning` / `Analysis
  of the law` / `Precedent Analysis`. These come back as a structured list
  (`[{type, text}, ...]`) separate from the full body, so retrieval can
  target the holding directly instead of scanning the whole document. Not
  every judgment has these tags (confirmed present, 23 of them, on the
  Puttaswamy judgment; it's a newer feature so older/shorter documents may
  have none — `key_excerpts` is just `[]` then).
- **`low_confidence_extraction`** — a tripwire, not a quality score. It
  fires only when the extracted body is suspiciously small relative to the
  size of IndiaKanoon's own content container for that page (`div.judgments`
  / `div.akoma-ntoso`'s own HTML, not the whole page — the whole page also
  carries a large constant amount of boilerplate, including a Google
  Translate widget with 100+ language options, that swamps the ratio for
  genuinely short documents and produced a false positive during testing
  before this was corrected to compare against the container instead).
  This exists because exactly this kind of silent under-extraction happened
  for real once already (see below) with nothing flagging it.

## The bug this was built to never repeat silently again

An earlier version of `get_document` selected body text only from `<pre>`
tags. It turns out IndiaKanoon uses `<pre>` for the short `key_excerpts`
tags above, while the bulk of a judgment's actual text sits in ordinary
`<p>` tags interleaved between them — so that selector was silently
dropping nearly everything. Confirmed on Puttaswamy: 7,410 characters
extracted (broken) vs. 1,012,196 (correct, after the fix). The fix clones
the whole content container, strips only the known header elements
(title/court/author/bench/citations), and takes all remaining text — so it
can't miss a content tag it didn't anticipate. `low_confidence_extraction`
above is the automated tripwire for if this class of bug ever recurs with a
future markup change.

## Legislation, rules, and everything else — the `doctypes:` taxonomy

IndiaKanoon indexes far more than court judgments. `doctypes.py` holds the
full reference table (122 slugs total), extracted from the exact
`name`/`value` pairs on IndiaKanoon's own `/advanced.html` form (2026-09-06)
— not guessed:

| Category | What's in it | Example slugs |
|---|---|---|
| `laws` (62 slugs) | Central & every State/UT's legislation — Acts, Rules, Regulations, Ordinances, Notifications all filed together (IndiaKanoon has no separate rules-only filter; a Rule sits in the same `*-laws` bucket as the Act it's made under) — plus the Constitution, international/UN treaties, and historical presidencies | `union-laws`, `delhi-laws`, `mh-laws`, `constitution-and-amendments`, `treaties`, `rbi`, `sebi`, `irdai`, `trai` |
| `supreme_court` (2) | Supreme Court judgments and daily orders | `supremecourt`, `scorders` |
| `high_courts` (31) | Every High Court, several with a separate orders/appellate slug | `delhi`, `bombay`, `chennai` (=Madras), `allahabad`, `karnataka` |
| `district_courts` (2) | Delhi and Bangalore district courts | `delhidc`, `bangaloredc` |
| `tribunals` (21) | CAT, ITAT, NCLAT, CERC, CCI, NGT, CIC, consumer courts, and more | `itat`, `nclat`, `cerc`, `cic`, `greentribunal` |
| `others` (4) | Law Commission reports, Constituent Assembly Debates, Parliament | `lawcommission`, `debates`, `loksabha`, `rajyasabha` |

Umbrella values IndiaKanoon's backend understands natively (confirmed via
its own generated facet links) — no need to look up individual slugs for
these: **`laws`**, **`judgments`** (all courts), **`tribunals`**,
**`highcourts`**, **`supremecourt`**. `indiankanoon_search`'s `doctypes`
param also accepts this project's own category names
(`supreme_court`/`high_courts`/`district_courts`/`others`, underscored,
since those aren't native IndiaKanoon slugs) and expands them — see
`resolve_doctypes()` in `doctypes.py`. Combine several with commas, e.g.
`doctypes="delhi-laws,itat"`.

Confirmed live: `indiankanoon_search("motor vehicles", doctypes="union-laws")`
returns actual sections of the Motor Vehicles Act, 1988, and
`indiankanoon_get_document` correctly extracts their text via the same
`div.akoma-ntoso` template used for the Constitution.

## Selectors — confirmed live, not placeholders

Unlike a from-scratch scrape of a site I can't see, these were checked
against real rendered pages on 2026-09-06:

- Search results: `article.result` blocks, with `.result_title a` (title),
  `a.cite_tag` (the "Full Document" link is the canonical doc URL — more
  reliable than the title link, which sometimes points at `/docfragment/`),
  `.docsource` (court), `.headline` (snippet).
- Document pages come in **two templates**: judgments use `div.judgments`;
  statutes/constitutional articles use `div.akoma-ntoso` instead. Both share
  the same `h2.doc_title` / `h3.docsource_main` / `h3.doc_author` /
  `h3.doc_bench` / `h3.doc_citations` header markup, and — this matters,
  see below — body text is **not** reliably confined to one kind of child
  tag in either template, so `get_document` takes the container's full text
  rather than selecting specific tags within it.

If IndiaKanoon changes its markup, `indiankanoon.py`'s `_EXTRACT_RESULTS_JS`
/ `_EXTRACT_DOCUMENT_JS` constants are where to fix it — open a page in a
real browser, inspect, adjust the `querySelector` calls.

## Known limitation: Chrome launches can hang under memory pressure

While building this, a live `get_document()` call intermittently hung
indefinitely rather than erroring — traced to the underlying Chrome
subprocess launch itself stalling, observed specifically on a machine
that was down to <1GB free RAM with 40+ other Chrome processes already
running. `browser.py` guards every CDP call (`evaluate`, navigation) *and*
the browser launch itself with a hard timeout that resets the shared browser
state on expiry (implemented via non-blocking `asyncio.wait`, not
`asyncio.wait_for`, since the latter's cancel-and-wait behavior hangs the
same way if the inner call ignores cancellation).

If a tool call ever seems stuck for more than ~30-90s:
- Check Task Manager / `wmic process where "name='chrome.exe' and CommandLine
  like '%scratchbrief-ind-mcp%'"` for orphaned Chrome processes tied to this
  project's `.chrome-profile` — safe to kill, they're isolated to this
  project's profile dir and won't be your regular Chrome windows.
- Close some of your own Chrome tabs if memory is tight; Chrome launches
  get slower/less reliable well before the system fully runs out of memory.
- Deleting `.chrome-profile/` resets everything (loses the cached
  clearance cookie, costing one extra headful warm-up on the next call).

## Shared "saved answers" (optional)

`indiankanoon_save_answer` writes to a shared Google Sheet via the real
Sheets API, so a saved answer shows up in the Google Docs add-on's Saved
tab for anyone on the team, not just the machine that ran the tool. Setup:

1. Create a Google Cloud OAuth client (Desktop app type) and save its
   downloaded JSON as `google_oauth_credentials.json` in this directory
   (or point `GOOGLE_OAUTH_CREDENTIALS` at it elsewhere) — gitignored,
   never commit this file.
2. Create a Google Sheet for the team to share, and set its ID as
   `ANSWERS_SPREADSHEET_ID` in this MCP server's environment (see the
   Claude Desktop config example above — add it under `env`).
3. First call to `indiankanoon_save_answer` opens a browser for one-time
   OAuth consent; the resulting token is cached in
   `saved_answers_token.json` (also gitignored) and refreshed silently
   after that.

Without `ANSWERS_SPREADSHEET_ID` set, `indiankanoon_save_answer` raises a
clear error rather than silently writing nowhere.

## A note on terms of service

This scrapes IndiaKanoon's public pages directly (no account, no paywall
bypass) rather than automating a logged-in session. Worth checking
IndiaKanoon's terms before relying on this for heavy/automated use —
scraping frequency and Cloudflare's presence both suggest they'd rather
this be used lightly than hammered.
