"""
indiacode.py — indiacode.gov.in, India's official consolidated-legislation
repository (Central & State Acts, Sections, Rules, Notifications,
Ordinances). Unlike indiankanoon.py, this needs no browser automation: it's
a DSpace 9 instance with a real, public JSON REST API and no Cloudflare
challenge -- confirmed live (2026-09-11) via `/server/api/discover/search`.

TLS note: indiacode.gov.in's certificate doesn't match its own hostname
(confirmed via `curl -v`: SEC_E_WRONG_PRINCIPAL). A real misconfiguration
on their end, not a MITM concern for a public, read-only government
database -- _SSL_CONTEXT below skips verification rather than failing
every request. Worth re-checking occasionally in case they fix it.

Full text: DSpace auto-extracts plain text from each item's PDF into a
"TEXT" bundle (via Apache Tika) at ingest time -- get_document() reads
that directly, no PDF parsing needed on our side.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://indiacode.gov.in"
_API = f"{BASE_URL}/server/api"
DEFAULT_CHARS = 50_000

_SSL_CONTEXT = ssl.create_default_context()
_SSL_CONTEXT.check_hostname = False
_SSL_CONTEXT.verify_mode = ssl.CERT_NONE


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=_SSL_CONTEXT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"IndiaCode API error {err.code} for {url}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"Could not reach IndiaCode: {err}") from err


def _meta(metadata: dict, key: str) -> str | None:
    values = metadata.get(key)
    return values[0]["value"] if values else None


def _summarize(item: dict) -> dict:
    metadata = item.get("metadata", {})
    handle = item.get("handle")
    return {
        "title": item.get("name"),
        "uuid": item.get("uuid"),
        "collection": _meta(metadata, "dc.identifier.collection"),
        "act_year": _meta(metadata, "dc.date.act_year"),
        "enact_date": _meta(metadata, "dc.date.enact_date"),
        "ministry": _meta(metadata, "dc.identifier.ministry_name"),
        "department": _meta(metadata, "dc.identifier.department_name"),
        "url": f"{BASE_URL}/handle/{handle}" if handle else None,
    }


def search(query: str, limit: int = 10, doctypes: str | None = None) -> list[dict]:
    """
    Full-text search across IndiaCode. `doctypes` restricts to one or more
    of the `identifier_collection` facet values (comma-separated), e.g.
    "ACT", "SECTION", "RULE", "NOTIFICATION", "ORDINANCE" -- confirmed live
    via /server/api/discover/facets/identifier_collection.
    """
    params = {"query": query, "size": str(min(max(limit, 1), 100))}
    url = f"{_API}/discover/search/objects?" + urllib.parse.urlencode(params)
    if doctypes:
        for slug in doctypes.split(","):
            slug = slug.strip()
            if slug:
                url += f"&f.identifier_collection={urllib.parse.quote(slug)},equals"
    data = _get_json(url)
    objects = (
        data.get("_embedded", {})
        .get("searchResult", {})
        .get("_embedded", {})
        .get("objects", [])
    )
    return [
        _summarize(o["_embedded"]["indexableObject"])
        for o in objects
        if o.get("_embedded", {}).get("indexableObject")
    ]


def _fetch_text_bundle(uuid: str) -> str | None:
    bundles = _get_json(f"{_API}/core/items/{uuid}/bundles").get("_embedded", {}).get("bundles", [])
    text_bundle = next((b for b in bundles if b.get("name") == "TEXT"), None)
    if not text_bundle:
        return None
    bitstreams_url = text_bundle["_links"]["bitstreams"]["href"]
    bitstreams = _get_json(bitstreams_url).get("_embedded", {}).get("bitstreams", [])
    txt = next((b for b in bitstreams if b.get("name", "").endswith(".txt")), None)
    if not txt:
        return None
    content_url = txt["_links"]["content"]["href"]
    req = urllib.request.Request(content_url)
    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as err:
        raise RuntimeError(f"Could not fetch IndiaCode document text: {err}") from err


def get_document(uuid: str, offset: int = 0, chars: int = DEFAULT_CHARS) -> dict:
    """
    Fetch one IndiaCode item's metadata plus a slice of its extracted full
    text. Paginated the same way indiankanoon.py's get_document is --
    Central Acts especially can run long.
    """
    item = _get_json(f"{_API}/core/items/{uuid}")
    metadata = item.get("metadata", {})
    full_body = _fetch_text_bundle(uuid) or ""
    total_chars = len(full_body)
    handle = item.get("handle")
    return {
        "title": item.get("name"),
        "uuid": uuid,
        "collection": _meta(metadata, "dc.identifier.collection"),
        "act_year": _meta(metadata, "dc.date.act_year"),
        "enact_date": _meta(metadata, "dc.date.enact_date"),
        "ministry": _meta(metadata, "dc.identifier.ministry_name"),
        "department": _meta(metadata, "dc.identifier.department_name"),
        "url": f"{BASE_URL}/handle/{handle}" if handle else None,
        "body": full_body[offset : offset + chars],
        "offset": offset,
        "total_chars": total_chars,
        "chars_returned": len(full_body[offset : offset + chars]),
        "has_more": offset + chars < total_chars,
    }
