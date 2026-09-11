"""
indiankanoon_mcp.py — local MCP server over indiankanoon.org, scraped live
via nodriver (undetected CDP-based Chrome automation) to get past
Cloudflare's bot challenge. See browser.py for how that challenge is
handled and README.md for setup.

Tools
  indiankanoon_search          search results: title/court/author/URL/etc.
  indiankanoon_get_document    metadata + a paginated slice of full text.
  indiankanoon_get_citations   cases actually citing/cited by a document.
  indiankanoon_list_doctypes   reference table of every searchable
                                document-type category/slug.
  indiacode_search              search IndiaCode (indiacode.gov.in) --
                                Central/State Acts, Sections, Rules,
                                Notifications, Ordinances. A real JSON REST
                                API (DSpace), unlike IndianKanoon -- no
                                browser automation needed. See indiacode.py.
  indiacode_get_document        metadata + a paginated slice of an
                                IndiaCode item's full text (already
                                extracted server-side, no PDF parsing).
  indiankanoon_save_answer     save a researched answer to the team's
                                shared Google Sheet, so it can be browsed
                                and inserted by ANYONE on the team from the
                                Google Docs add-on's sidebar -- not just on
                                this machine. See README for one-time OAuth
                                setup (google_oauth_credentials.json).

Claude Desktop config:
  "scratchbrief-ind": {
    "command": "C:\\Users\\HP-LT\\scratchbrief-ind-mcp\\.venv\\Scripts\\python.exe",
    "args": ["C:\\Users\\HP-LT\\scratchbrief-ind-mcp\\indiankanoon_mcp.py"]
  }

Naming: this server and its tools are still named after IndianKanoon even
though IndiaCode is now a second, equally first-class data source in the
same process -- a rename (server name, tool prefixes) is a deliberate
follow-up, not done here, so as not to break the existing Claude Desktop
config / any in-flight usage without a heads-up first.
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from mcp.server.fastmcp import FastMCP

from indiankanoon import (
    search as ik_search,
    get_document as ik_get_document,
    get_citations as ik_get_citations,
    DEFAULT_CHARS,
)
from doctypes import list_doctypes
from indiacode import (
    search as ic_search,
    get_document as ic_get_document,
    DEFAULT_CHARS as INDIACODE_DEFAULT_CHARS,
)

mcp = FastMCP("scratchbrief-ind")

# Shared with docs-addon/Code.gs's listSavedAnswers()/getSavedAnswer() --
# this is the bridge a Claude Desktop research session uses to hand an
# answer to the WHOLE TEAM's Google Docs add-on, not just this machine's.
# Written directly via the real Sheets API (this machine's own Google
# OAuth login, one-time browser consent -- see README), deliberately NOT
# through an Apps Script web app endpoint, which would have to accept
# anonymous internet requests to be callable from a plain HTTP POST.
_SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_OAUTH_CREDENTIALS_FILE = os.environ.get(
    "GOOGLE_OAUTH_CREDENTIALS", str(Path(__file__).parent / "google_oauth_credentials.json")
)
_OAUTH_TOKEN_FILE = Path(__file__).parent / "saved_answers_token.json"
_ANSWERS_SPREADSHEET_ID = os.environ.get("ANSWERS_SPREADSHEET_ID")
_ANSWERS_SHEET_NAME = "Answers"


def _get_sheets_credentials() -> Credentials:
    creds: Credentials | None = None
    if _OAUTH_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(_OAUTH_TOKEN_FILE), _SHEETS_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
        else:
            if not Path(_OAUTH_CREDENTIALS_FILE).exists():
                raise RuntimeError(
                    f"No Google OAuth client credentials at {_OAUTH_CREDENTIALS_FILE} -- "
                    "see README for how to create one (Google Cloud Console: OAuth client, Desktop app type)."
                )
            # Opens a browser for one-time consent -- only happens once per
            # machine; the resulting token is cached and refreshed silently
            # after that, same pattern `clasp login` already uses here.
            flow = InstalledAppFlow.from_client_secrets_file(_OAUTH_CREDENTIALS_FILE, _SHEETS_SCOPES)
            creds = flow.run_local_server(port=0)
        _OAUTH_TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _append_answer_row(row: list[str]) -> None:
    if not _ANSWERS_SPREADSHEET_ID:
        raise RuntimeError("ANSWERS_SPREADSHEET_ID is not set -- see README for how to get it.")
    creds = _get_sheets_credentials()
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{_ANSWERS_SPREADSHEET_ID}/values/"
        f"{urllib.parse.quote(_ANSWERS_SHEET_NAME)}:append?valueInputOption=RAW"
    )
    payload = json.dumps({"values": [row]}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"Sheets API error {err.code}: {err.read().decode('utf-8', 'replace')}") from err


@mcp.tool()
async def indiankanoon_search(
    query: str,
    limit: int = 10,
    doctypes: str | None = None,
    fromdate: str | None = None,
    todate: str | None = None,
    sortby: str | None = None,
) -> list[dict]:
    """
    Search IndiaKanoon: case law from every Indian court/tribunal, PLUS
    legislation -- Central and State Acts, Rules, Regulations, Ordinances,
    and Notifications (IndiaKanoon files all of those together under each
    jurisdiction's "laws" bucket -- there's no separate rules-only filter),
    the Constitution, international treaties, Law Commission reports,
    Constituent Assembly Debates, and Lok Sabha/Rajya Sabha material.
    Returns title, court, author, a snippet, cites/cited_by counts, doc_id,
    and url for each result.

    Use `doctypes` to restrict by category -- call
    indiankanoon_list_doctypes first if you need the exact slug for a
    specific court/jurisdiction/tribunal. Handy umbrella values that work
    without looking anything up: "laws" (all legislation, every
    jurisdiction), "judgments" (all court judgments), "tribunals" (all
    tribunals), "highcourts" (all High Courts), "supremecourt".

    IndiaKanoon's other search operators also work directly inside `query`
    if you need to combine several yourself: cites:<doc_id>,
    citedby:<doc_id> (prefer indiankanoon_get_citations for these --
    clearer intent), author:<name>, bench:<name>.

    Args:
        query: Search text, optionally including the operators above.
        limit: Max results to return (default 10, max 100).
        doctypes: Optional category/slug (or comma-separated list) to
            restrict results to, e.g. "laws", "delhi-laws", "itat".
        fromdate: Restrict to documents on/after this date, "DD-MM-YYYY".
        todate: Restrict to documents on/before this date, "DD-MM-YYYY".
        sortby: "relevance" (default), "mostrecent", or "leastrecent".
    """
    try:
        return await ik_search(
            query,
            limit=limit,
            doctypes=doctypes,
            fromdate=fromdate,
            todate=todate,
            sortby=sortby,
        )
    except (RuntimeError, ValueError) as err:
        return [{"error": str(err)}]


@mcp.tool()
async def indiankanoon_get_citations(
    doc_id: str, direction: str = "citedby", limit: int = 10
) -> list[dict]:
    """
    List the actual cases citing, or cited by, a document -- IndiaKanoon's
    citation graph, for tracing precedent chains (as opposed to
    indiankanoon_search's cites/cited_by fields, which are just counts).

    Args:
        doc_id: The doc id to trace citations for/from (e.g. from a search
            result's doc_id field).
        direction: "citedby" (default) -- later cases relying on this one as
            precedent. "cites" -- the precedents this document itself relies
            on.
        limit: Max results (default 10, max 100).
    """
    try:
        return await ik_get_citations(doc_id, direction=direction, limit=limit)
    except (RuntimeError, ValueError) as err:
        return [{"error": str(err)}]


@mcp.tool()
def indiankanoon_list_doctypes(category: str | None = None) -> dict:
    """
    Reference table of every document-type category/slug IndiaKanoon's
    `doctypes:` search operator understands -- use this to find the exact
    slug for a specific state's laws, a particular High Court, a tribunal,
    etc. before calling indiankanoon_search.

    Args:
        category: Optional filter to just one category: "laws"
            (legislation by jurisdiction/regulator -- Acts, Rules,
            Regulations, Notifications, Ordinances), "supreme_court",
            "high_courts", "district_courts", "tribunals", or "others"
            (Law Commission, Constituent Assembly Debates, Lok Sabha,
            Rajya Sabha). Omit to get all categories at once.
    """
    try:
        return list_doctypes(category)
    except ValueError as err:
        return {"error": str(err)}


@mcp.tool()
async def indiankanoon_get_document(
    url_or_id: str, offset: int = 0, chars: int = DEFAULT_CHARS
) -> dict:
    """
    Fetch one IndiaKanoon judgment/document's metadata (title, court,
    author, bench, equivalent citations) plus a slice of its full text.

    Judgments can run past a MILLION characters (multi-judge Supreme Court
    decisions especially), so `body` is paginated rather than returned
    whole -- check `has_more`/`total_chars` in the response and walk
    forward with `offset` if you need the rest, the same way you'd page
    through a long file. `key_excerpts` (when present) surfaces
    IndiaKanoon's own AI-tagged Issue/Court's Reasoning/Analysis of the
    law/Precedent Analysis passages -- worth checking first if you just
    need the holding rather than the full text.

    A `low_confidence_extraction` field appears if the extracted body looks
    suspiciously small for the page -- treat that as a signal to
    spot-check the live page rather than trusting the text as complete.

    Args:
        url_or_id: A doc id (e.g. "91938676"), or any indiankanoon.org
            /doc/<id>/ or /docfragment/<id>/ URL — e.g. the `url` field
            from an indiankanoon_search result.
        offset: Character offset into the document's body to start from
            (default 0).
        chars: Max characters of body to return in this call (default
            50,000).
    """
    try:
        return await ik_get_document(url_or_id, offset=offset, chars=chars)
    except (RuntimeError, ValueError) as err:
        return {"error": str(err)}


@mcp.tool()
async def indiacode_search(
    query: str,
    limit: int = 10,
    doctypes: str | None = None,
) -> list[dict]:
    """
    Search IndiaCode (indiacode.gov.in) -- India's official consolidated
    legislation repository: Central & State Acts, individual Sections,
    Rules, Notifications, and Ordinances. Complements indiankanoon_search:
    IndiaCode is the authoritative, government-published text of
    legislation itself (not case law), with richer legislative metadata
    (enactment date, ministry, department) than IndianKanoon's `laws`
    doctypes carry.

    Args:
        query: Search text.
        limit: Max results to return (default 10, max 100).
        doctypes: Optional comma-separated filter on IndiaCode's own
            `identifier_collection` facet, e.g. "ACT", "SECTION", "RULE",
            "NOTIFICATION", "ORDINANCE".
    """
    try:
        return await asyncio.to_thread(ic_search, query, limit, doctypes)
    except RuntimeError as err:
        return [{"error": str(err)}]


@mcp.tool()
async def indiacode_get_document(
    uuid: str, offset: int = 0, chars: int = INDIACODE_DEFAULT_CHARS
) -> dict:
    """
    Fetch one IndiaCode item's metadata (title, collection type, act year,
    enactment date, ministry, department) plus a slice of its full text --
    already extracted server-side by IndiaCode itself, no PDF parsing
    needed here. Paginated the same way indiankanoon_get_document is: check
    `has_more`/`total_chars` and walk forward with `offset` for long Acts.

    Args:
        uuid: The item's IndiaCode uuid (from an indiacode_search result's
            `uuid` field).
        offset: Character offset into the document's body to start from.
        chars: Max characters of body to return in this call.
    """
    try:
        return await asyncio.to_thread(ic_get_document, uuid, offset, chars)
    except RuntimeError as err:
        return {"error": str(err)}


@mcp.tool()
def indiankanoon_save_answer(
    title: str,
    answer: str,
    query: str | None = None,
    citations: list[dict] | None = None,
) -> dict:
    """
    Save a researched answer to the team's shared Google Sheet, so it shows
    up in the "Saved answers" panel of EVERY team member's Google Docs
    add-on sidebar (not just this machine's) and can be inserted straight
    into a document from there -- bridges research done in this Claude
    Desktop chat into the whole team's drafting workflow.

    Args:
        title: Short title for this answer (shown in the add-on's list).
        answer: The drafted analysis/answer text itself.
        query: Optional -- the question this answer addresses.
        citations: Optional list of case citations the answer relies on,
            each a dict with any of title/court/doc_id/url/citations --
            indiankanoon_search results can be passed straight through.
    """
    answer_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    row = [
        answer_id,
        title,
        datetime.now(timezone.utc).isoformat(),
        query or "",
        answer,
        json.dumps(citations or []),
    ]
    try:
        _append_answer_row(row)
    except RuntimeError as err:
        return {"error": str(err)}
    return {"id": answer_id}


if __name__ == "__main__":
    mcp.run()
