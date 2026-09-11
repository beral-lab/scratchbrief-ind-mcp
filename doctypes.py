"""
doctypes.py — IndiaKanoon's full `doctypes:` operator taxonomy.

Extracted from the checkbox `name`/`value` pairs on indiankanoon.org's own
/advanced.html form (2026-09-06) — the exact slugs the site's search backend
accepts, not guessed. Combine several with commas in one operator, e.g.
`doctypes:union-laws,delhi-laws` or `doctypes:supremecourt,scorders`.

There is no separate "rules"/"notifications"/"regulations" doctype: those
are filed as ordinary documents inside the same jurisdiction's `*-laws`
bucket alongside Acts (a Central Rule sits in `union-laws` right next to
the Central Act it's made under). "Laws" is IndiaKanoon's umbrella term for
all legislation — Acts, Rules, Regulations, Ordinances, Notifications.
"""
from __future__ import annotations

# category -> {slug: label}
DOCTYPES: dict[str, dict[str, str]] = {
    "laws": {
        "union-laws": "Union of India",
        "constitution-and-amendments": "Constitution and Amendments",
        "treaties": "International Treaties",
        "unitednations": "UN Treaties",
        "andhra-laws": "Andhra Pradesh",
        "arunachal-laws": "Arunachal Pradesh",
        "assam-laws": "Assam",
        "bihar-laws": "Bihar",
        "chandigarh-laws": "UT Chandigarh",
        "chattisgarh-laws": "Chattisgarh",
        "delhi-laws": "NCT Delhi",
        "goa-laws": "Goa",
        "gujarat-laws": "Gujarat",
        "haryana-laws": "Haryana",
        "himachal-laws": "Himachal Pradesh",
        "jk-laws": "Jammu and Kashmir",
        "jharkhand-laws": "Jharkhand",
        "karnataka-laws": "Karnataka",
        "kerala-laws": "Kerala",
        "mp-laws": "Madhya Pradesh",
        "mh-laws": "Maharashtra",
        "manipur-laws": "Manipur",
        "meghalaya-laws": "Meghalaya",
        "mizoram-laws": "Mizoram",
        "nagaland-laws": "Nagaland",
        "odisha-laws": "Odisha",
        "puducherry-laws": "Puducherry",
        "punjab-laws": "Punjab",
        "rajasthan-laws": "Rajasthan",
        "sikkim-laws": "Sikkim",
        "tn-laws": "Tamil Nadu",
        "telengana-laws": "Telangana",
        "tripura-laws": "Tripura",
        "uttarakhand-laws": "Uttarakhand",
        "up-laws": "Uttar Pradesh",
        "wb-laws": "West Bengal",
        "andaman-laws": "Andaman and Nicobar Islands",
        "dadra-laws": "Dadra and Nagar Haveli",
        "lakshadweep-laws": "Lakshadweep",
        "daman-laws": "Daman and Diu",
        "bengaluru-laws": "Greater Bengaluru City Corporation",
        "eci": "Election Commission",
        "fssai": "FSSAI",
        "irdai": "IRDAI",
        "rbi": "RBI",
        "sebi": "SEBI",
        "trai": "TRAI",
        "bis": "BIS",
        "cbfc": "CBFC",
        "british-india": "British India (historical)",
        "mysore-laws": "Mysore State (historical)",
        "nagpurprovince-laws": "Nagpur Province (historical)",
        "britishpunjab-laws": "Punjab Province (historical)",
        "utdprovinces-laws": "United Provinces (historical)",
        "centralprovinces-laws": "Central Provinces and Berar (historical)",
        "chotanagpur-laws": "Chota Nagpur Division (historical)",
        "bhopal-laws": "Bhopal State (historical)",
        "bombay-laws": "Bombay Presidency (historical)",
        "bengalpresidency-laws": "Bengal Presidency (historical)",
        "madhyabharat-laws": "Madhya Bharat (historical)",
        "madras-laws": "Madras Presidency (historical)",
        "vindhya-laws": "Vindhya Province (historical)",
    },
    "supreme_court": {
        "supremecourt": "Supreme Court of India",
        "scorders": "Supreme Court - Daily Orders",
    },
    "high_courts": {
        "allahabad": "Allahabad High Court",
        "andhra": "Andhra Pradesh High Court",
        "amravati": "Andhra Pradesh High Court - Amravati",
        "bombay": "Bombay High Court",
        "kolkata": "Calcutta High Court",
        "kolkata_app": "Calcutta High Court - Appellate",
        "chattisgarh": "Chhattisgarh High Court",
        "delhi": "Delhi High Court",
        "delhiorders": "Delhi High Court - Orders",
        "gauhati": "Gauhati High Court",
        "gujarat": "Gujarat High Court",
        "himachal_pradesh": "Himachal Pradesh High Court",
        "jammu": "Jammu and Kashmir High Court",
        "srinagar": "Jammu and Kashmir High Court - Srinagar",
        "jharkhand": "Jharkhand High Court",
        "karnataka": "Karnataka High Court",
        "kerala": "Kerala High Court",
        "madhyapradesh": "Madhya Pradesh High Court",
        "manipur": "Manipur High Court",
        "meghalaya": "Meghalaya High Court",
        "chennai": "Madras High Court",
        "orissa": "Orissa High Court",
        "patna": "Patna High Court",
        "patna_orders": "Patna High Court - Orders",
        "punjab": "Punjab-Haryana High Court",
        "jaipur": "Rajasthan High Court - Jaipur",
        "jodhpur": "Rajasthan High Court - Jodhpur",
        "sikkim": "Sikkim High Court",
        "uttaranchal": "Uttarakhand High Court",
        "tripura": "Tripura High Court",
        "telangana": "Telangana High Court",
    },
    "district_courts": {
        "delhidc": "Delhi District Court",
        "bangaloredc": "Bangalore District Court",
    },
    "tribunals": {
        "aptel": "Appellate Tribunal for Electricity (APTEL)",
        "authority": "Authority for Advance Rulings",
        "cat": "Central Administrative Tribunal (CAT)",
        "cegat": "CEGAT",
        "cerc": "Central Electricity Regulatory Commission (CERC)",
        "cic": "Central Information Commission (CIC)",
        "clb": "Company Law Board (CLB)",
        "consumer": "Consumer Courts",
        "copyrightboard": "Copyright Board",
        "drat": "Debt Recovery Appellate Tribunal",
        "greentribunal": "National Green Tribunal",
        "cci": "Competition Commission of India (CCI)",
        "ipab": "Intellectual Property Appellate Board (IPAB)",
        "itat": "Income Tax Appellate Tribunal (ITAT)",
        "mrtp": "Monopolies and Restrictive Trade Practices (MRTP)",
        "sebisat": "Securities Appellate Tribunal (SAT)",
        "stt": "State Taxation Tribunals",
        "tdsat": "Telecom Disputes Settlement Tribunal (TDSAT)",
        "trademark": "Intellectual Property (Trademark) Tribunal",
        "cestat": "CESTAT",
        "nclat": "National Company Law Appellate Tribunal (NCLAT)",
    },
    "others": {
        "lawcommission": "Law Commission Reports",
        "debates": "Constituent Assembly Debates",
        "loksabha": "Lok Sabha",
        "rajyasabha": "Rajya Sabha",
    },
}

# IndiaKanoon's backend already understands these umbrella terms natively
# (confirmed via its own generated facet links, e.g.
# `doctypes:supremecourt,scorders,highcourts`) -- no client-side expansion
# needed for them.
NATIVE_ALIASES = {"laws", "judgments", "tribunals", "highcourts", "supremecourt"}

# This project's own DOCTYPES category keys use underscores
# (district_courts, others, ...) and are NOT themselves valid `doctypes:`
# operator values -- only the native aliases above are. This maps the
# category keys that aren't already native aliases to the raw slugs they
# expand to.
_CATEGORY_EXPANSIONS: dict[str, str] = {
    "supreme_court": "supremecourt,scorders",
    "high_courts": "highcourts",
    "district_courts": ",".join(DOCTYPES["district_courts"]),
    "others": ",".join(DOCTYPES["others"]),
}


def resolve_doctypes(value: str) -> str:
    """Expands a comma-separated mix of this project's category names and/or
    raw slugs into the string IndiaKanoon's `doctypes:` operator wants.
    Native umbrella terms (laws, judgments, tribunals, highcourts,
    supremecourt) and individual slugs pass through unchanged."""
    out: list[str] = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        out.append(_CATEGORY_EXPANSIONS.get(token, token))
    return ",".join(out)


def list_doctypes(category: str | None = None) -> dict:
    """Returns the doctype reference table, optionally filtered to one
    category (laws, supreme_court, high_courts, district_courts, tribunals,
    others)."""
    if category is None:
        return DOCTYPES
    if category not in DOCTYPES:
        raise ValueError(
            f"Unknown category {category!r}. Valid categories: "
            f"{sorted(DOCTYPES)}"
        )
    return {category: DOCTYPES[category]}
