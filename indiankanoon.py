"""
indiankanoon.py — search + document fetch against indiankanoon.org.

Selectors below were confirmed against the live site via a real rendered
page (nodriver) on 2026-09-06 — not guessed. Search results are
`article.result` blocks; document pages are the `div.judgments` (judgments)
or `div.akoma-ntoso` (statutes/constitutional articles) block, with body
text taken from the whole container minus its header elements (see
_EXTRACT_DOCUMENT_JS -- an earlier <pre>-only selector silently dropped
most of the text on long judgments). See README.md if these ever need
updating (IndiaKanoon's markup has reportedly been stable for years).
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote

from browser import BASE_URL, evaluate, new_page
from doctypes import resolve_doctypes

RESULTS_PER_PAGE = 10
MAX_LIMIT = 100

_DOC_ID_RE = re.compile(r"/doc(?:fragment)?/(\d+)/")

# nodriver's evaluate() hands back complex (non-primitive) results as CDP's
# nested "deep serialized" wrapper format, not plain JSON -- but a *string*
# result comes through untouched. So the JS below does its own
# JSON.stringify() and Python does the json.loads(), sidestepping that
# entirely rather than trying to unwrap CDP's format by hand.
_EXTRACT_RESULTS_JS = r"""
JSON.stringify(Array.from(document.querySelectorAll('article.result')).map(el => {
  const titleLink = el.querySelector('.result_title a');
  const citeTags = Array.from(el.querySelectorAll('a.cite_tag'));
  const fullDocLink = citeTags.find(a => a.textContent.trim() === 'Full Document');
  const authorLink = citeTags.find(a => a.href.includes('authorid:'));
  const citesLink = citeTags.find(a => a.href.includes('formInput=cites:'));
  const citedbyLink = citeTags.find(a => a.href.includes('formInput=citedby:'));
  const headline = el.querySelector('.headline');
  const docsource = el.querySelector('.docsource');
  const numMatch = s => {
    if (!s) return null;
    const m = s.textContent.match(/\d+/);
    return m ? parseInt(m[0], 10) : null;
  };
  return {
    title: titleLink ? titleLink.textContent.trim() : null,
    url: fullDocLink ? fullDocLink.href : (titleLink ? titleLink.href : null),
    court: docsource ? docsource.textContent.trim() : null,
    author: authorLink ? authorLink.textContent.trim() : null,
    snippet: headline ? headline.textContent.replace(/\s+/g, ' ').trim() : null,
    cites: numMatch(citesLink),
    cited_by: numMatch(citedbyLink),
  };
}))
"""

_EXTRACT_DOCUMENT_JS = r"""
JSON.stringify((() => {
  // Judgments use div.judgments; statutes/constitutional articles use
  // div.akoma-ntoso instead. Both share the same doc_title/docsource_main/
  // etc. header markup.
  //
  // IMPORTANT: the body text is NOT reliably confined to one kind of tag.
  // Long judgments interleave ordinary <p> paragraphs with short <pre>
  // islands (IndiaKanoon's "Prism" AI tagging marks specific sentences with
  // title="Issue"/"Court's Reasoning"/etc.) -- selecting only <pre> (or
  // only <section class="akn-section">) silently drops most of the text.
  // Confirmed against a ~140-page, 9-judge judgment: a <pre>-only selector
  // captured 7410 of what should be tens of thousands of characters. So:
  // clone the whole container, strip the known header elements, and take
  // everything else's textContent in document order -- that can't miss a
  // content tag we didn't anticipate.
  const root = document.querySelector('div.judgments, div.akoma-ntoso');
  if (!root) return null;
  const container_html_len = root.outerHTML.length;
  const title = root.querySelector('h2.doc_title');
  const court = root.querySelector('h3.docsource_main');
  const citations = root.querySelector('h3.doc_citations');
  const author = root.querySelector('h3.doc_author');
  const bench = root.querySelector('h3.doc_bench');
  const clean = (el, prefix) =>
    el ? el.textContent.replace(prefix, '').trim() : null;

  const clone = root.cloneNode(true);
  clone.querySelectorAll(
    'h2.doc_title, h3.docsource_main, h3.doc_citations, h3.doc_author, ' +
    'h3.doc_bench, div.covers, form, script, style'
  ).forEach(el => el.remove());
  const body = clone.textContent.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();

  // IndiaKanoon's own "Prism" AI tagging labels specific sentences/passages
  // with title="Issue" / "Court's Reasoning" / "Analysis of the law" /
  // "Precedent Analysis" on some <pre> elements -- expose these as
  // structured excerpts so retrieval can target (e.g.) the holding directly
  // instead of scanning the full body. Not every judgment has these (it's
  // a newer feature); key_excerpts is just [] when absent.
  const key_excerpts = Array.from(root.querySelectorAll('pre[title]')).map(el => ({
    type: el.getAttribute('title'),
    text: el.textContent.trim(),
  })).filter(e => e.text);

  return {
    title: title ? title.textContent.trim() : null,
    court: court ? court.textContent.trim() : null,
    citations: clean(citations, 'Equivalent citations:'),
    author: clean(author, 'Author:'),
    bench: clean(bench, 'Bench:'),
    body: body,
    key_excerpts: key_excerpts,
    container_html_len: container_html_len,
  };
})())
"""


def _doc_url(doc_id: str) -> str:
    return f"{BASE_URL}/doc/{doc_id}/"


def _normalize_result(item: dict) -> dict:
    if item.get("url"):
        m = _DOC_ID_RE.search(item["url"])
        if m:
            item["doc_id"] = m.group(1)
            item["url"] = _doc_url(m.group(1))
    return item


_SORTBY = {"relevance": None, "mostrecent": "mostrecent", "leastrecent": "leastrecent"}

_CASE_SEP_RE = re.compile(r"\s+(?:v\.?|vs\.?|versus)\s+", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[.,]")


def _normalize_case_text(s: str) -> str:
    """Normalizes a case name/query for exact-match comparison: lowercase,
    "v."/"vs"/"versus" collapsed to one separator, punctuation and repeated
    whitespace stripped. Confirmed gap this targets (see docs-addon/README):
    searching a case's literal name doesn't guarantee it ranks first among
    IndiaKanoon's own keyword-relevance results."""
    s = _CASE_SEP_RE.sub(" v ", s.strip().lower())
    s = _PUNCT_RE.sub("", s)
    return " ".join(s.split())


def _exact_match_rank(query_norm: str, item: dict) -> int:
    if not query_norm:
        return 0
    title_norm = _normalize_case_text(item.get("title") or "")
    if not title_norm:
        return 0
    if title_norm == query_norm:
        return 2
    if query_norm in title_norm:
        return 1
    return 0


async def search(
    query: str,
    limit: int = 10,
    doctypes: str | None = None,
    fromdate: str | None = None,
    todate: str | None = None,
    sortby: str | None = None,
    author: str | None = None,
    bench: str | None = None,
) -> list[dict]:
    """
    Searches IndiaKanoon for `query`, paging through results (10/page) until
    `limit` is reached or results run out. `doctypes`/`fromdate`/`todate`/
    `sortby`/`author`/`bench` are convenience params for IndiaKanoon's own
    search operators; the same operators (plus cites:, citedby:) also work
    typed directly inside `query` if you need to combine several yourself.

    Results are then locally re-sorted (stable, so relevance order is kept
    among non-matches) to put any result whose title exactly or
    substring-matches the query first -- e.g. searching a case's exact name
    surfaces that case itself ahead of merely keyword-similar ones.

    Args:
        fromdate/todate: Dates as "DD-MM-YYYY" (confirmed against
            IndiaKanoon's own advanced-search form), inclusive range.
        sortby: "relevance" (default), "mostrecent", or "leastrecent".
        author/bench: Judge name / bench composition, IndiaKanoon's own
            author:/bench: operators.
    """
    limit = max(1, min(limit, MAX_LIMIT))
    query_norm = _normalize_case_text(query)
    if doctypes:
        query = f"{query} doctypes:{resolve_doctypes(doctypes)}"
    if fromdate:
        query = f"{query} fromdate:{fromdate}"
    if todate:
        query = f"{query} todate:{todate}"
    if author:
        query = f"{query} author:{author}"
    if bench:
        query = f"{query} bench:{bench}"
    if sortby:
        if sortby not in _SORTBY:
            raise ValueError(f"sortby must be one of {sorted(_SORTBY)}")
        if _SORTBY[sortby]:
            query = f"{query} sortby:{_SORTBY[sortby]}"
    results: list[dict] = []
    pagenum = 0

    while len(results) < limit:
        url = f"{BASE_URL}/search/?formInput={quote(query)}"
        if pagenum:
            url += f"&pagenum={pagenum}"
        page = await new_page(url)
        raw = await evaluate(page, _EXTRACT_RESULTS_JS)
        batch = json.loads(raw) if raw else []
        if not batch:
            break
        results.extend(_normalize_result(item) for item in batch)
        if len(batch) < RESULTS_PER_PAGE:
            break
        pagenum += 1

    results = results[:limit]
    results.sort(key=lambda item: -_exact_match_rank(query_norm, item))
    return results


DEFAULT_CHARS = 50_000

# Below this ratio of (extracted body length / the *content container's own*
# outerHTML length -- not the whole page), the extraction is almost
# certainly missing content -- as happened for real when a <pre>-only
# selector captured 7,410 of what should have been 1,012,196 characters.
# Deliberately compared against the container, not the full page: the page
# also carries a large, constant amount of unrelated boilerplate (nav,
# sidebar filters, a Google Translate widget with 100+ language options,
# etc.) that swamps the ratio for short documents -- confirmed by a
# genuinely complete, single-paragraph Act section otherwise scoring as
# "low confidence" against whole-page length. Against just the container,
# a real short document still runs ~0.5-0.9 (mostly text, modest tag
# overhead); the confirmed-broken case above was ~0.005.
_LOW_EXTRACTION_RATIO = 0.15


async def get_document(
    url_or_id: str, offset: int = 0, chars: int = DEFAULT_CHARS
) -> dict:
    """
    Fetches one document's metadata + a slice of its full text, by doc id or
    any /doc/<id>/ / /docfragment/<id>/ URL. Judgments can run past a
    million characters (e.g. multi-judge Supreme Court decisions), so body
    text is paginated rather than returned whole: walk it via `offset` using
    the returned `total_chars` / `has_more`, the same pattern as paging
    through a long file.
    """
    doc_id = url_or_id.strip()
    m = _DOC_ID_RE.search(doc_id)
    if m:
        doc_id = m.group(1)
    elif not doc_id.isdigit():
        raise ValueError(
            "url_or_id must be an IndiaKanoon doc id (digits), or a "
            "/doc/<id>/ or /docfragment/<id>/ URL"
        )

    url = _doc_url(doc_id)
    page = await new_page(url)
    raw = await evaluate(page, _EXTRACT_DOCUMENT_JS)
    data = json.loads(raw) if raw else None
    if data is None:
        raise RuntimeError(f"NOT_FOUND: no judgment content at {url}")

    full_body = data.pop("body")
    total_chars = len(full_body)
    container_html_len = data.pop("container_html_len", 0)
    low_confidence = (
        container_html_len > 0
        and total_chars / container_html_len < _LOW_EXTRACTION_RATIO
    )

    data["doc_id"] = doc_id
    data["url"] = url
    data["total_chars"] = total_chars
    data["offset"] = offset
    data["body"] = full_body[offset : offset + chars]
    data["chars_returned"] = len(data["body"])
    data["has_more"] = offset + chars < total_chars
    if low_confidence:
        data["low_confidence_extraction"] = (
            "Body text is unusually small relative to the page's total size "
            "-- extraction may be incomplete for this document's template. "
            "Worth spot-checking against the live page."
        )
    return data


async def get_citations(
    doc_id: str, direction: str = "citedby", limit: int = 10
) -> list[dict]:
    """
    Lists the actual cases citing (or cited by) a document -- IndiaKanoon's
    own citation graph, via its `cites:`/`citedby:` search operators -- as
    opposed to search()'s cites/cited_by fields, which are just counts.

    Args:
        doc_id: The doc id to trace citations for/from.
        direction: "citedby" (cases that cite this one -- forward citations,
            i.e. later cases relying on this precedent) or "cites" (cases
            this one cites -- the precedents it relies on).
        limit: Max results (default 10, max 100 -- see search()).
    """
    if direction not in ("cites", "citedby"):
        raise ValueError('direction must be "cites" or "citedby"')
    return await search(f"{direction}:{doc_id}", limit=limit)
