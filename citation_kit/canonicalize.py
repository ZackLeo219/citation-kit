"""Identifier canonicalization + cross-source entity resolution.

Same paper coming from different APIs needs to canonicalize to the same
`cite_id`. Resolution order (strongest → weakest signal):

  1. DOI       → `doi:<lowercased-doi>` (after stripping URL prefixes)
  2. PubMed    → `pmid:<numeric-id>`
  3. arXiv     → `arxiv:<id-without-version>`  (e.g. `2401.12345`)
  4. Semantic Scholar → `s2:<paperId>`
  5. URL       → `url:<8-char-hash-of-canonicalized-url>`

Adapters call `pick_cite_id(identifiers_dict)` with whatever they extracted
from the API response; this function picks the strongest available scheme.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse, urlunparse


# DOI regex: catches both bare DOIs and URL-prefixed DOIs.
# Bare: 10.NNNN/anything-here
# URL: https://doi.org/10.NNNN/... or https://dx.doi.org/...
# `\d+` (not `\d{4,9}`) — DOI registrant codes are usually 4-9 digits but the
# spec allows any positive integer; some publishers (mostly non-English)
# legitimately use shorter codes. We're parsing not validating.
_DOI_RE = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/)?(10\.\d+/[^\s/?#]+(?:/[^\s/?#]+)*)",
    re.IGNORECASE,
)

# arXiv ID: new style 2401.12345 (5-or-more digits, optional vN), legacy hep-th/9901001
_ARXIV_NEW_RE = re.compile(r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b")
_ARXIV_OLD_RE = re.compile(r"\b([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?\b")

# PubMed numeric ID — usually 7-9 digits, but technically can be more.
_PMID_RE = re.compile(r"^\d{1,12}$")


def normalize_doi(raw: str) -> str | None:
    """Extract bare DOI from a string that might be a URL or already-bare DOI.
    Returns lowercased DOI or None if not parseable."""
    if not raw:
        return None
    m = _DOI_RE.search(raw.strip())
    if not m:
        return None
    return m.group(1).lower().rstrip(".,;)")


def normalize_pmid(raw: str | int) -> str | None:
    """PubMed ID is a positive integer, sometimes returned as int sometimes str."""
    if raw is None:
        return None
    s = str(raw).strip()
    if _PMID_RE.match(s) and s != "0":
        return s
    return None


def normalize_arxiv_id(raw: str) -> str | None:
    """arXiv ID without version suffix. Accepts new (`2401.12345`), old
    (`hep-th/9901001`), or full URL (`https://arxiv.org/abs/2401.12345v2`)."""
    if not raw:
        return None
    s = raw.strip()
    if "arxiv.org/" in s.lower():
        s = s.split("arxiv.org/", 1)[1]
        s = s.removeprefix("abs/").removeprefix("pdf/").rsplit(".pdf", 1)[0]
    m = _ARXIV_NEW_RE.search(s) or _ARXIV_OLD_RE.search(s)
    if m:
        return m.group(1)
    return None


def canonicalize_url(raw: str) -> str:
    """Produce a stable URL string for hashing.

    Steps:
      - lowercase scheme + host
      - strip default ports (80, 443)
      - strip trailing slash from path (but keep `/` for root)
      - strip common tracking params (utm_*, fbclid, gclid, ref, source, ...)
      - sort remaining query params for deterministic order
      - drop fragment
    """
    if not raw:
        return ""
    try:
        p = urlparse(raw.strip())
    except Exception:
        return raw.strip()
    scheme = (p.scheme or "https").lower()
    host = (p.hostname or "").lower()
    if p.port and not (
        (scheme == "http" and p.port == 80) or (scheme == "https" and p.port == 443)
    ):
        host = f"{host}:{p.port}"
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    # Query: drop tracking, sort
    if p.query:
        kept = []
        for kv in p.query.split("&"):
            if not kv:
                continue
            k = kv.split("=", 1)[0]
            kl = k.lower()
            if kl.startswith("utm_") or kl in {
                "fbclid", "gclid", "ref", "source", "ref_src", "ref_url", "_hsenc",
                "_hsmi", "mc_cid", "mc_eid", "yclid", "msclkid",
            }:
                continue
            kept.append(kv)
        kept.sort()
        query = "&".join(kept)
    else:
        query = ""
    return urlunparse((scheme, host, path, "", query, ""))


def url_hash(url: str) -> str:
    """8-char hex hash of canonicalized URL — used in `url:<hash>` cite_ids."""
    canon = canonicalize_url(url)
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:8]


def pick_cite_id(identifiers: dict[str, str]) -> str:
    """Given an adapter-collected dict of identifier candidates, pick the
    strongest one and format as `<scheme>:<id>` cite_id.

    Recognized keys (any subset is fine):
      doi, pmid, arxiv, s2 (or s2_paper_id), url

    Raises ValueError if no recognizable identifier present (caller should not
    register such records — it would be a fully anonymous citation).
    """
    # Try each in priority order.
    if doi := identifiers.get("doi"):
        normalized = normalize_doi(doi)
        if normalized:
            return f"doi:{normalized}"
    if pmid := identifiers.get("pmid"):
        normalized = normalize_pmid(pmid)
        if normalized:
            return f"pmid:{normalized}"
    if arxiv := identifiers.get("arxiv"):
        normalized = normalize_arxiv_id(arxiv)
        if normalized:
            return f"arxiv:{normalized}"
    if s2 := (identifiers.get("s2") or identifiers.get("s2_paper_id")):
        s2 = str(s2).strip()
        if s2:
            return f"s2:{s2}"
    if url := identifiers.get("url"):
        h = url_hash(url)
        if h:
            return f"url:{h}"
    raise ValueError(f"no recognizable identifier in {list(identifiers.keys())}")


def canonical_url_for(identifiers: dict[str, str], fallback_url: str = "") -> str:
    """Build the canonical clickable URL for a record. Prefers DOI URL > PubMed
    URL > arXiv URL > S2 URL > whatever URL the adapter provided."""
    if doi := normalize_doi(identifiers.get("doi", "")):
        return f"https://doi.org/{doi}"
    if pmid := normalize_pmid(identifiers.get("pmid", "")):
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    if arxiv := normalize_arxiv_id(identifiers.get("arxiv", "")):
        return f"https://arxiv.org/abs/{arxiv}"
    if s2 := (identifiers.get("s2") or identifiers.get("s2_paper_id")):
        return f"https://www.semanticscholar.org/paper/{s2}"
    return identifiers.get("url") or fallback_url
