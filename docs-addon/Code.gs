/**
 * IndianKanoon research sidebar for Google Docs.
 *
 * Talks to api_server.py (../api_server.py) over UrlFetchApp -- a
 * server-to-server call from Apps Script's own infrastructure, not a
 * browser fetch from the sidebar -- so no CORS setup is needed on the
 * backend. BACKEND_URL/BACKEND_TOKEN come from Script Properties rather
 * than being hardcoded, since BACKEND_URL will be a tunnel URL that can
 * change and BACKEND_TOKEN is a secret.
 *
 * Set them once: Project Settings (gear icon) > Script Properties, or run
 * setBackendConfig_() below from the editor with real values filled in.
 */

function onOpen() {
  DocumentApp.getUi()
    .createAddonMenu()
    .addItem('Search case law', 'showSidebar')
    .addToUi();
}

function onHomepage(e) {
  showSidebar();
}

function showSidebar() {
  const html = HtmlService.createHtmlOutputFromFile('Sidebar').setTitle('ScratchBrief-Ind');
  DocumentApp.getUi().showSidebar(html);
}

// DEFAULT_BACKEND_URL/DEFAULT_BACKEND_TOKEN are defined in LocalConfig.gs,
// not here -- that file is gitignored (holds this machine's live tunnel URL
// and proxy secret, rewritten by start-backend.ps1 on every restart) while
// this file is version-controlled, so the real values never end up in git.
// Apps Script shares global scope across every .gs file in the project, so
// they're still visible here. If Script Properties are set, they win
// regardless (see getBackendConfig_ below).

// Convenience one-off setup, if you'd rather override via Script Properties
// than edit the constants above. Run once from the Apps Script editor.
function setBackendConfig_() {
  PropertiesService.getScriptProperties().setProperties({
    BACKEND_URL: 'https://YOUR-TUNNEL-SUBDOMAIN.trycloudflare.com',
    BACKEND_TOKEN: 'PASTE_IK_PROXY_TOKEN_HERE',
  });
}

function getBackendConfig_() {
  const props = PropertiesService.getScriptProperties();
  const url = props.getProperty('BACKEND_URL') || DEFAULT_BACKEND_URL;
  const token = props.getProperty('BACKEND_TOKEN') || DEFAULT_BACKEND_TOKEN;
  if (!url || !token) {
    throw new Error(
      'Backend not configured -- set BACKEND_URL and BACKEND_TOKEN in Script Properties.'
    );
  }
  return { url, token };
}

// Cloudflare (or any proxy in front of the backend) can hand back a plain
// HTML/text error page instead of JSON -- e.g. a 502 during the ~minute a
// Quick Tunnel takes to finish reconnecting after a restart (confirmed
// live). JSON.parse on that raw text throws a cryptic "Unexpected token"
// syntax error instead of saying what's actually wrong, so every backend
// call parses defensively through this instead of JSON.parse directly.
function parseBackendResponse_(response) {
  const code = response.getResponseCode();
  const text = response.getContentText();
  let body;
  try {
    body = JSON.parse(text);
  } catch (e) {
    throw new Error(
      'Backend returned a non-JSON response (HTTP ' + code + '): ' + text.slice(0, 200) +
      ' -- if this just followed a restart, the tunnel may still be reconnecting; wait a bit and retry.'
    );
  }
  if (code >= 400) {
    throw new Error((body && body.detail) || 'Backend error ' + code);
  }
  return body;
}

function callBackend_(path, params) {
  const { url, token } = getBackendConfig_();
  const qs = Object.keys(params || {})
    .filter((k) => params[k] !== undefined && params[k] !== null && params[k] !== '')
    .map((k) => encodeURIComponent(k) + '=' + encodeURIComponent(params[k]))
    .join('&');
  const fullUrl = url.replace(/\/$/, '') + path + (qs ? '?' + qs : '');
  const fetchOptions = { headers: { Authorization: 'Bearer ' + token }, muteHttpExceptions: true };
  let response = UrlFetchApp.fetch(fullUrl, fetchOptions);
  // 502/503/504/524 are gateway-level failures (the Cloudflare tunnel
  // reconnecting, or IndianKanoon's own Cloudflare challenge re-escalating
  // mid-request) rather than an application error -- both self-heal within
  // seconds, so one retry avoids surfacing a transient blip as a hard error.
  if ([502, 503, 504, 524].indexOf(response.getResponseCode()) !== -1) {
    Utilities.sleep(4000);
    response = UrlFetchApp.fetch(fullUrl, fetchOptions);
  }
  return parseBackendResponse_(response);
}

/** Called from Sidebar.html via google.script.run. */
function searchCaseLaw(query, options) {
  options = options || {};
  return callBackend_('/search', {
    q: query,
    limit: options.limit,
    doctypes: options.doctypes,
    fromdate: options.fromdate,
    todate: options.todate,
    sortby: options.sortby,
    author: options.author,
    bench: options.bench,
  });
}

function getDocument(docId, offset, chars) {
  return callBackend_('/doc/' + encodeURIComponent(docId), { offset: offset, chars: chars });
}

function getCitations(docId, direction) {
  return callBackend_('/citations/' + encodeURIComponent(docId), { direction: direction, limit: 10 });
}

function locateInDocument(docId, snippet) {
  return callBackend_('/doc/' + encodeURIComponent(docId) + '/locate', { snippet: snippet });
}

/** IndiaCode (indiacode.gov.in) -- a second, separate legislation source
 *  in this same add-on (Central/State Acts, Sections, Rules,
 *  Notifications, Ordinances), not merged into the IndianKanoon search
 *  above since the result shape genuinely differs (collection/act_year/
 *  ministry/department, not court/cites/cited_by). See api_server.py's
 *  /indiacode/* endpoints and indiacode.py. */
function searchIndiaCode(query, options) {
  options = options || {};
  return callBackend_('/indiacode/search', {
    q: query,
    limit: options.limit,
    doctypes: options.doctypes,
  });
}

function getIndiaCodeDocument(itemUuid, offset, chars) {
  return callBackend_('/indiacode/doc/' + encodeURIComponent(itemUuid), { offset: offset, chars: chars });
}

/** Clause/definition lookup -- select a defined term in the draft, jump
 *  straight to where the currently-open IndiaCode item defines it. Indian
 *  legislative drafting convention: definitions read `"term" means ...`
 *  (straight or curly quotes) inside a numbered clause, so this is pattern
 *  matching on that convention, not real parsing -- it'll miss a term
 *  defined by cross-reference to another Act, or phrased without "means"
 *  (e.g. "includes"). Fetches the item's full text in one shot (capped)
 *  rather than reusing whatever's paginated into the panel already, since
 *  a definitions section (usually early) may be well past what's loaded. */
function findDefinitionInIndiaCode(itemUuid, term) {
  const term_ = (term || '').trim();
  if (!term_) throw new Error('Select a term in the document first.');
  const doc = getIndiaCodeDocument(itemUuid, 0, 300000);
  const body = doc.body || '';
  const escaped = term_.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp('["\u2018\u2019\u201c\u201d]\\s*' + escaped + '\\s*["\u2018\u2019\u201c\u201d]\\s*means\\b', 'i');
  const match = re.exec(body);
  if (!match) {
    return { found: false, term: term_, title: doc.title };
  }
  const rest = body.slice(match.index, match.index + 3000);
  const endMatch = /;\s*\n|\n\s*\n/.exec(rest);
  const clause = (endMatch ? rest.slice(0, endMatch.index + 1) : rest.slice(0, 1000)).trim();
  return { found: true, term: term_, clause: clause, title: doc.title, url: doc.url };
}

/** Old Ollama-backed relevance-over-a-result-list flow. Left in place,
 *  unused by Sidebar.html now that getDocDigest() below (Claude-backed,
 *  per-document) covers this -- kept only as a fallback path if Ollama is
 *  ever preferred over the Claude Code CLI again. */
function getAssist(context, results) {
  const { url, token } = getBackendConfig_();
  const fullUrl = url.replace(/\/$/, '') + '/assist';
  const response = UrlFetchApp.fetch(fullUrl, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({ context: context, results: results }),
    headers: { Authorization: 'Bearer ' + token },
    muteHttpExceptions: true,
  });
  return parseBackendResponse_(response);
}

/** Sends the current drafting context + a page of search results (title/
 *  court/snippet only, not full text) to /rank_relevance -- one Claude call
 *  covering the whole page, so a relevance tag can render at the TOP of
 *  every result CARD right after search, instead of only being available
 *  after opening one document's full text via getDocDigest() below. */
function getResultRelevance(context, results) {
  const { url, token } = getBackendConfig_();
  const fullUrl = url.replace(/\/$/, '') + '/rank_relevance';
  const response = UrlFetchApp.fetch(fullUrl, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({ context: context, results: results }),
    headers: { Authorization: 'Bearer ' + token },
    muteHttpExceptions: true,
  });
  return parseBackendResponse_(response);
}

/** Sends the current drafting context + the full text currently loaded in
 *  one document's panel to /doc_assist, which uses the Claude Code CLI
 *  (already logged in on this machine) to pick the most relevant paragraph
 *  and draft a ready-to-insert citation sentence. Replaces the old
 *  Ollama-backed getAssist() above, and lives at the bottom of each
 *  document's full-text view instead of below the whole results list. */
function getDocDigest(context, docText, meta) {
  const { url, token } = getBackendConfig_();
  const fullUrl = url.replace(/\/$/, '') + '/doc_assist';
  const response = UrlFetchApp.fetch(fullUrl, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({
      context: context,
      doc_text: docText,
      title: meta.title,
      court: meta.court,
      citations: meta.citations,
    }),
    headers: { Authorization: 'Bearer ' + token },
    muteHttpExceptions: true,
  });
  return parseBackendResponse_(response);
}

// ---------------------------------------------------------------------
// Shared answers (cross-team) -- backed by a Google Sheet this script
// project owns, rather than a file on any one person's machine, so every
// team member's sidebar (each running this same script) can read answers
// saved by ANYONE on the team. Written directly by indiankanoon_mcp.py's
// indiankanoon_save_answer tool via the real Sheets API, authenticated
// with each machine's own Google OAuth login (see README) -- deliberately
// NOT via an Apps Script web app endpoint, which would have to accept
// anonymous internet requests (gated only by an app-level token) to be
// callable from a plain, unauthenticated Python HTTP call.
// ---------------------------------------------------------------------

const ANSWERS_HEADER_ = ['id', 'title', 'created_at', 'query', 'answer', 'citations_json'];

/** Auto-creates the shared spreadsheet on first call and remembers its id
 *  in Script Properties -- run this once (e.g. open "Saved answers" in the
 *  sidebar) before configuring SPREADSHEET_ID on the Python side, so both
 *  sides end up pointed at the same sheet. */
function getAnswersSheet_() {
  const props = PropertiesService.getScriptProperties();
  let sheetId = props.getProperty('ANSWERS_SHEET_ID');
  let ss;
  if (sheetId) {
    try {
      ss = SpreadsheetApp.openById(sheetId);
    } catch (e) {
      sheetId = null; // stored id no longer valid (e.g. sheet deleted) -- recreate below
    }
  }
  if (!sheetId) {
    ss = SpreadsheetApp.create('IndianKanoon Saved Answers');
    props.setProperty('ANSWERS_SHEET_ID', ss.getId());
  }
  let sheet = ss.getSheetByName('Answers');
  if (!sheet) {
    sheet = ss.getSheets()[0];
    sheet.setName('Answers');
    sheet.appendRow(ANSWERS_HEADER_);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

/** Prints the shared sheet's id and share URL -- run once from the Apps
 *  Script editor after the sheet auto-creates, to get the id for
 *  SPREADSHEET_ID on the Python side and to share the sheet itself with
 *  the team's Google accounts (Sheets access is separate from who the
 *  add-on is installed for). No trailing underscore, unlike this file's
 *  other internal helpers, specifically so it's selectable in the
 *  editor's Run dropdown (Apps Script hides "_"-suffixed functions there). */
function printAnswersSheetInfo() {
  const sheet = getAnswersSheet_();
  const ss = sheet.getParent();
  Logger.log('Spreadsheet ID: ' + ss.getId());
  Logger.log('URL: ' + ss.getUrl());
}

/** Lists saved answers (id/title/created_at/query only), newest first --
 *  see getSavedAnswer for the full text and citations of one. */
function listSavedAnswers() {
  const values = getAnswersSheet_().getDataRange().getValues();
  return values.slice(1)
    .map(function (r) { return { id: r[0], title: r[1], created_at: r[2], query: r[3] }; })
    .reverse();
}

/** Full record for one saved answer, including citations. */
function getSavedAnswer(id) {
  const values = getAnswersSheet_().getDataRange().getValues();
  for (let i = 1; i < values.length; i++) {
    if (values[i][0] === id) {
      let citations = [];
      try { citations = JSON.parse(values[i][5] || '[]'); } catch (e) { /* malformed JSON -- leave empty rather than fail the whole read */ }
      return { id: values[i][0], title: values[i][1], created_at: values[i][2], query: values[i][3], answer: values[i][4], citations: citations };
    }
  }
  throw new Error('Saved answer not found: ' + id);
}

/** Grabs the user's current selection, or (if nothing is selected) the
 *  paragraph/list item the cursor sits in -- so the sidebar can search on
 *  whatever's actually being drafted instead of making the user retype it. */
function getContextText() {
  const doc = DocumentApp.getActiveDocument();
  const selection = doc.getSelection();
  if (selection) {
    const text = selection
      .getRangeElements()
      .map(function (rangeEl) {
        const el = rangeEl.getElement();
        if (!el.editAsText) return '';
        const full = el.asText().getText();
        return rangeEl.isPartial()
          ? full.substring(rangeEl.getStartOffset(), rangeEl.getEndOffsetInclusive() + 1)
          : full;
      })
      .join(' ')
      .replace(/\s+/g, ' ')
      .trim();
    if (text) return text;
  }
  const cursor = doc.getCursor();
  if (cursor) {
    let el = cursor.getElement();
    while (
      el &&
      el.getType() !== DocumentApp.ElementType.PARAGRAPH &&
      el.getType() !== DocumentApp.ElementType.LIST_ITEM
    ) {
      el = el.getParent();
    }
    if (el && el.editAsText) {
      return el.asText().getText().replace(/\s+/g, ' ').trim();
    }
  }
  return '';
}

/** Inserts text at the cursor, or appends to the doc if nothing is focused
 *  (e.g. the sidebar just grabbed focus away from the editor). */
function insertCitation(text) {
  const doc = DocumentApp.getActiveDocument();
  const cursor = doc.getCursor();
  if (cursor) {
    cursor.insertText(text);
  } else {
    doc.getBody().appendParagraph(text);
  }
}

// ---------------------------------------------------------------------
// Find All / Link to Cites -- Lexis-for-Word-style "scan the doc for
// citation-shaped text, then link it to its source in place." IndiaKanoon
// has no entity-recognition API to call, so this is pattern matching, same
// spirit as Lexis's own Find All (a recognizer, not full NLP) -- it will
// miss unusual formats and can false-positive on an ordinary capitalized
// phrase containing "v."/"vs.".
// ---------------------------------------------------------------------

const CITATION_PATTERNS_ = [
  { type: 'AIR', re: /\bAIR\s*\d{4}\s+[A-Z]{2,4}\s+\d+\b/g },
  { type: 'SCC', re: /\(?\d{4}\)?\s+\d+\s+SCC\s+\d+\b/g },
  { type: 'SCC OnLine', re: /\b\d{4}\s+SCC\s+OnLine\s+[A-Z][A-Za-z]*\s+\d+\b/g },
  { type: 'Neutral', re: /\b\d{4}\s+INSC\s+\d+\b/g },
  // Slash-delimited case/appeal numbers, e.g. "C/SCA/5236/2024" -- real
  // Indian court/tribunal numbering is too heterogeneous to enumerate
  // (every court and tribunal has its own scheme), so this only catches
  // the single-token slash-separated shape, not e.g. "CA D.33686/2023"
  // (space-separated) -- a known coverage gap, not attempted further.
  { type: 'Case number', re: /\b[A-Z]{1,6}(?:\/[A-Z0-9.]+){1,5}\/\d{4}\b/g },
  // Case name, e.g. "Kesavananda Bharati v. State of Kerala" -- deliberately
  // conservative but broadened past a clean-prose case name to also catch
  // real scraped-judgment text: optional "M/S "/"M/s " prefix, "versus" as
  // well as "v."/"vs", and connector words/parentheticals that are
  // near-universal in Indian case names ("State of X", "& Ors.", "(M.P.)",
  // "(Patel)") -- confirmed against the user's actual pasted judgment
  // text, which the earlier version caught almost none of. Deliberately
  // still excludes "for"/"in" (see below) to limit false positives on
  // ordinary prose. Uses [ \t]+ rather than \s+ between words on purpose:
  // \s+ also matches the newline Body.editAsText() inserts at paragraph
  // boundaries, and confirmed live that this let the pattern silently
  // fuse the end of one paragraph with the start of a LATER one across a
  // blank paragraph into one false match -- [ \t]+ makes a paragraph break
  // a hard stop instead. Known remaining gap: scraped text with ZERO space
  // between two unrelated capitalized words WITHIN one paragraph (e.g.
  // "...MAHETAHirenkumar...", an artifact of the source page's own
  // markup) can still fuse them into one false match -- not fixable by
  // pattern matching alone without real NLP.
  {
    type: 'Case name',
    re: /\b(?:M\/[Ss][ \t]+)?[A-Z][A-Za-z.&'-]*(?:[ \t]+(?:[A-Z][A-Za-z.&'-]*|of|and|the|&|Ors\.?|Anr\.?|Others|Ltd\.?|Pvt\.?|Limited|Private|\([A-Za-z.\s]{1,30}\))){0,8}[ \t]+(?:vs?\.?|versus)[ \t]+(?:M\/[Ss][ \t]+)?[A-Z][A-Za-z.&'-]*(?:[ \t]+(?:[A-Z][A-Za-z.&'-]*|of|and|the|&|Ors\.?|Anr\.?|Others|Ltd\.?|Pvt\.?|Limited|Private|\([A-Za-z.\s]{1,30}\))){0,8}\b/g,
  },
  // IndiaCode-flavored (see IC_TYPES_ in Sidebar.html, which routes these
  // two types to IndiaCode's own search/link instead of IndianKanoon's):
  // statute/rule references, e.g. "the Right to Information Act, 2005" or
  // "Section 5 of the Indian Evidence Act, 1872". Same conservative,
  // pattern-not-NLP spirit as Case name above -- won't catch a lowercase
  // or heavily abbreviated reference, and other legislation types
  // (Ordinances, Regulations) aren't covered yet.
  {
    type: 'Act',
    re: /\b(?:Section\s+\d+[A-Za-z]?(?:\([0-9a-zA-Z]+\))?\s+of\s+the\s+)?[A-Z][A-Za-z,.&'-]*(?:[ \t]+(?:[A-Z][A-Za-z,.&'-]*|of|and|the|&|to|for)){0,10}[ \t]+Act,?[ \t]+\d{4}\b/g,
  },
  {
    type: 'Rules',
    re: /\b[A-Z][A-Za-z,.&'-]*(?:[ \t]+(?:[A-Z][A-Za-z,.&'-]*|of|and|the|&|to|for)){0,10}[ \t]+Rules,?[ \t]+\d{4}\b/g,
  },
];

/** Scans the WHOLE document body (not just the selection) for
 *  citation-shaped text. Returns {text, type, start, end} objects with
 *  start/end as offsets into Body.editAsText()'s flattened text -- the
 *  same coordinate space linkFoundCitation() needs to hyperlink the exact
 *  matched span in place, and which setLinkUrl() itself doesn't disturb
 *  (it only sets an attribute over existing characters), so offsets from
 *  one findAllCitations() call stay valid across multiple linking calls. */
function findAllCitations() {
  const fullText = DocumentApp.getActiveDocument().getBody().editAsText().getText();
  const seen = {};
  const matches = [];
  CITATION_PATTERNS_.forEach(function (p) {
    p.re.lastIndex = 0;
    let m;
    while ((m = p.re.exec(fullText)) !== null) {
      const start = m.index;
      const end = start + m[0].length - 1; // inclusive, matches setLinkUrl's convention
      const key = start + ':' + end;
      if (seen[key]) continue;
      seen[key] = true;
      matches.push({ text: m[0], type: p.type, start: start, end: end });
    }
  });
  matches.sort(function (a, b) { return a.start - b.start; });
  return matches;
}

/** Hyperlinks the exact [start, end] span (as found by findAllCitations)
 *  to `url`, without touching the surrounding text. */
function linkFoundCitation(start, end, url) {
  DocumentApp.getActiveDocument().getBody().editAsText().setLinkUrl(start, end, url);
}

const FIND_ALL_HIGHLIGHT_COLOR_ = '#fff3a3';

/** Flags every match where it actually lives in the document, not just in
 *  the sidebar list -- the closest a Docs Add-on can get to Grammarly's
 *  "underlined right in your text" feel. Real limits vs. an actual
 *  Grammarly-style experience: this can't hook into keystrokes (Docs
 *  exposes no onEdit-style trigger for content changes) so it's scan-then-
 *  highlight, not live-as-you-type, and there's no way to show a hover
 *  card at a specific point in the canvas-rendered text -- only actual
 *  text formatting (background color here), which is why the sidebar list
 *  carries the per-match actions instead. */
function highlightCitationMatches(matches) {
  const bodyText = DocumentApp.getActiveDocument().getBody().editAsText();
  matches.forEach(function (m) {
    bodyText.setBackgroundColor(m.start, m.end, FIND_ALL_HIGHLIGHT_COLOR_);
  });
}

function clearCitationHighlights(matches) {
  const bodyText = DocumentApp.getActiveDocument().getBody().editAsText();
  matches.forEach(function (m) {
    bodyText.setBackgroundColor(m.start, m.end, null);
  });
}

/** Table of authorities / bulk citation export -- takes whatever Find All
 *  currently has (entries carry {type, text, url?, title?}; url/title are
 *  only set for ones the user actually linked via "Search & link"), dedupes
 *  by type+identity, and appends a grouped, headed list at the END of the
 *  document -- the conventional place for a TOA, not at the cursor. Also
 *  doubles as a flat bulk-export: entries without a url still show up,
 *  just labeled unlinked, so this works even for a doc where nothing's
 *  been linked yet. */
function insertTableOfAuthorities(entries) {
  const groups = {};
  const seen = {};
  (entries || []).forEach(function (e) {
    const identity = (e.title || e.text || '').toLowerCase();
    const key = e.type + '|' + identity;
    if (seen[key]) return;
    seen[key] = true;
    const list = groups[e.type] || (groups[e.type] = []);
    list.push(e);
  });
  const body = DocumentApp.getActiveDocument().getBody();
  body.appendPageBreak();
  body.appendParagraph('TABLE OF AUTHORITIES').setHeading(DocumentApp.ParagraphHeading.HEADING1);
  Object.keys(groups).sort().forEach(function (type) {
    body.appendParagraph(type).setHeading(DocumentApp.ParagraphHeading.HEADING2);
    groups[type].forEach(function (e) {
      const line = e.url ? (e.title || e.text) + ' — ' + e.url : e.text + ' (not linked)';
      body.appendParagraph(line).setHeading(DocumentApp.ParagraphHeading.NORMAL);
    });
  });
  return { inserted: (entries || []).length };
}

// ---------------------------------------------------------------------
// Cross-reference checker -- flags internal references (e.g. "through
// Claim D", "under Section 7") to a label that's never actually defined
// anywhere else in the document. This is the tractable version of "catch
// an inconsistent citation": genuinely verifying that inline prose citing
// "Section 5" matches what a linked citation ACTUALLY says needs real
// document understanding, which isn't attempted here -- this instead
// catches the concrete, common drafting slip of renaming/renumbering a
// claim or section and missing one of the places that refers back to it.
// A label counts as "defined" if some paragraph in the doc STARTS with it
// (e.g. "Claim A: ..." or "Section 5. ..."), same convention this doc's
// own drafting already uses.
// ---------------------------------------------------------------------

const XREF_LABEL_TYPES_ = 'Claim|Section|Part|Schedule|Annexure|Article|Clause';

function checkCrossReferences() {
  const body = DocumentApp.getActiveDocument().getBody();
  const fullText = body.editAsText().getText();
  const paragraphCount = body.getNumChildren();

  const defined = {};
  for (let i = 0; i < paragraphCount; i++) {
    const el = body.getChild(i);
    if (typeof el.asText !== 'function' && !el.editAsText) continue;
    let text;
    try { text = el.asText().getText(); } catch (e) { continue; }
    const m = new RegExp('^\\s*(' + XREF_LABEL_TYPES_ + ')\\s+([A-Z0-9]+)\\b').exec(text);
    if (m) defined[m[1] + ' ' + m[2]] = true;
  }

  const re = new RegExp('\\b(' + XREF_LABEL_TYPES_ + ')\\s+([A-Z0-9]+)\\b', 'g');
  const issues = [];
  const seen = {};
  let m;
  while ((m = re.exec(fullText)) !== null) {
    const label = m[1] + ' ' + m[2];
    if (defined[label]) continue;
    const start = m.index;
    const end = start + m[0].length - 1;
    const key = start + ':' + end;
    if (seen[key]) continue;
    seen[key] = true;
    issues.push({ label: label, text: m[0], start: start, end: end });
  }
  return issues;
}

const XREF_HIGHLIGHT_COLOR_ = '#fcdada';

function highlightXrefIssues(issues) {
  const bodyText = DocumentApp.getActiveDocument().getBody().editAsText();
  issues.forEach(function (m) { bodyText.setBackgroundColor(m.start, m.end, XREF_HIGHLIGHT_COLOR_); });
}

function clearXrefHighlights(issues) {
  const bodyText = DocumentApp.getActiveDocument().getBody().editAsText();
  issues.forEach(function (m) { bodyText.setBackgroundColor(m.start, m.end, null); });
}

// ---------------------------------------------------------------------
// Compare / redline -- word-level diff of the current selection (or
// cursor paragraph) against either a saved answer or another Google Doc
// the user has access to, to catch when a drafted position has drifted
// from earlier research or an earlier draft. Diff renders in the sidebar
// (insertions/deletions styled inline) rather than as tracked changes in
// the doc itself -- simpler and doesn't touch Docs' own suggestion API.
// ---------------------------------------------------------------------

function extractDocId_(urlOrId) {
  const m = /\/d\/([a-zA-Z0-9_-]+)/.exec(urlOrId || '');
  return m ? m[1] : (urlOrId || '').trim();
}

const COMPARE_OTHER_TEXT_CAP_ = 20000; // keeps the O(n*m) diff below bounded for a whole other-doc's text

function getCompareSourceText(source) {
  if (source.kind === 'saved') {
    return getSavedAnswer(source.id).answer || '';
  }
  if (source.kind === 'gdoc') {
    const id = extractDocId_(source.urlOrId);
    let otherDoc;
    try {
      otherDoc = DocumentApp.openById(id);
    } catch (err) {
      throw new Error('Could not open that Google Doc -- check the link and that you have access to it.');
    }
    return otherDoc.getBody().getText().slice(0, COMPARE_OTHER_TEXT_CAP_);
  }
  throw new Error('Unknown compare source: ' + source.kind);
}

/** Classic LCS-based word diff -- O(n*m), fine for a selection/paragraph
 *  (current side) against a saved answer or capped other-doc excerpt
 *  (other side): hundreds to low thousands of words, not meant for
 *  whole-book-length diffing. */
function wordDiff_(oldText, newText) {
  const a = (oldText || '').split(/(\s+)/).filter(function (s) { return s.length > 0; });
  const b = (newText || '').split(/(\s+)/).filter(function (s) { return s.length > 0; });
  const n = a.length, m = b.length;
  const dp = new Array(n + 1);
  for (let i = 0; i <= n; i++) dp[i] = new Array(m + 1).fill(0);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const result = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { result.push({ type: 'equal', text: a[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { result.push({ type: 'delete', text: a[i] }); i++; }
    else { result.push({ type: 'insert', text: b[j] }); j++; }
  }
  while (i < n) { result.push({ type: 'delete', text: a[i] }); i++; }
  while (j < m) { result.push({ type: 'insert', text: b[j] }); j++; }
  return result;
}

function compareWithSource(currentText, source) {
  const otherText = getCompareSourceText(source);
  if (!otherText) throw new Error('Nothing to compare against -- that source has no text.');
  return { diff: wordDiff_(otherText, currentText) };
}

// ---------------------------------------------------------------------
// Set/Check Cite Format -- a single configurable template every citation
// insert goes through, plus a light structural check for the recognized
// citation types above. Not a full citation-style validator (there's no
// single settled "house style" the way Bluebook is for US practice) --
// just spacing/structure conformance for the formats Find All recognizes.
// ---------------------------------------------------------------------

const DEFAULT_CITE_TEMPLATE_ = '{title}, {court}{citations} ({url})';
const CITE_TEMPLATE_KEY_ = 'CITE_TEMPLATE';

function getCiteTemplate() {
  return PropertiesService.getUserProperties().getProperty(CITE_TEMPLATE_KEY_) || DEFAULT_CITE_TEMPLATE_;
}

function setCiteTemplate(template) {
  PropertiesService.getUserProperties().setProperty(CITE_TEMPLATE_KEY_, template || DEFAULT_CITE_TEMPLATE_);
}

/** Fills {title}/{court}/{citations}/{url}/{doc_id} placeholders in the
 *  configured template from a search-result-shaped object. */
function formatCitation(result) {
  const template = getCiteTemplate();
  const citations = result.citations ? ', ' + result.citations : '';
  return template
    .replace(/\{title\}/g, result.title || '')
    .replace(/\{court\}/g, result.court || '')
    .replace(/\{citations\}/g, citations)
    .replace(/\{url\}/g, result.url || '')
    .replace(/\{doc_id\}/g, result.doc_id || '');
}

const CITE_FORMAT_CHECKS_ = {
  'AIR': /^AIR\s\d{4}\s[A-Z]{2,4}\s\d+$/,
  'SCC': /^\(\d{4}\)\s\d+\sSCC\s\d+$/,
  'SCC OnLine': /^\d{4}\sSCC\sOnLine\s[A-Z][A-Za-z]*\s\d+$/,
  'Neutral': /^\d{4}\sINSC\s\d+$/,
};

/** Structural well-formedness check for one of Find All's recognized
 *  citation types -- e.g. catches "AIR1963SC1554" (missing spaces) even
 *  though findAllCitations()'s looser pattern would still have matched it.
 *  Returns {checked:false} for "Case name", which has no fixed structure
 *  to check against. */
function checkCitationFormat(text, type) {
  const re = CITE_FORMAT_CHECKS_[type];
  if (!re) return { checked: false };
  return { checked: true, wellFormed: re.test(text.trim()) };
}

// ---------------------------------------------------------------------
// Work Folders -- save search results into named folders for later reuse,
// persisted per-user via PropertiesService (no backend involved). Note:
// Apps Script caps a single property value around 9KB, so this is good
// for realistic research-session sizes, not an unbounded archive.
// ---------------------------------------------------------------------

const FOLDERS_KEY_ = 'IK_FOLDERS';

function listFolders() {
  const raw = PropertiesService.getUserProperties().getProperty(FOLDERS_KEY_);
  return raw ? JSON.parse(raw) : {};
}

function saveToFolder(folderName, item) {
  const folders = listFolders();
  if (!folders[folderName]) folders[folderName] = [];
  if (!folders[folderName].some(function (x) { return x.doc_id === item.doc_id; })) {
    folders[folderName].push(item);
  }
  try {
    PropertiesService.getUserProperties().setProperty(FOLDERS_KEY_, JSON.stringify(folders));
  } catch (err) {
    throw new Error('Could not save -- folders storage may be full: ' + err.message);
  }
  return folders;
}

function removeFromFolder(folderName, docId) {
  const folders = listFolders();
  if (folders[folderName]) {
    folders[folderName] = folders[folderName].filter(function (x) { return x.doc_id !== docId; });
    if (!folders[folderName].length) delete folders[folderName];
  }
  PropertiesService.getUserProperties().setProperty(FOLDERS_KEY_, JSON.stringify(folders));
  return folders;
}
