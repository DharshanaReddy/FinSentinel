"""
Fetch earnings press releases from SEC EDGAR 8-K filings.

Strategy:
  1. Download the master ticker→CIK map from EDGAR
  2. For each company, fetch their filing history via data.sec.gov/submissions/
  3. Find 8-K filings and download EX-99.1 (earnings press release)
  4. Extract the "prepared remarks" / management discussion section

No API key required. Rate-limited to ~8 req/s per SEC fair-use policy.
"""

import re
import time
import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.database import get_connection, upsert_company

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "FinSentinel/1.0 research@finsentinel.dev",
    "Accept-Encoding": "gzip, deflate",
}

_TICKER_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"

_HEDGE_WORDS = [
    "challenging", "uncertain", "uncertainty", "headwinds", "difficult",
    "volatile", "volatility", "cautious", "risk", "concern", "pressure",
    "macro", "slowdown", "decelerate",
]

_MGMT_MARKERS = [
    "prepared remarks", "management's discussion", "management discussion",
    "opening remarks", "ceo remarks", "chief executive",
]

_QA_MARKERS = [
    "question-and-answer", "q&a session", "questions and answers",
    "question and answer", "operator instructions",
]

# Cache so we only download it once per run
_ticker_cik_cache: dict[str, str] = {}


def _get(url: str, params: dict = None, timeout: int = 30) -> requests.Response:
    time.sleep(0.13)
    resp = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp


def _load_ticker_cik_map() -> dict[str, str]:
    """Return {ticker_upper: zero_padded_10digit_cik}."""
    global _ticker_cik_cache
    if _ticker_cik_cache:
        return _ticker_cik_cache
    try:
        data = _get(_TICKER_CIK_URL).json()
        for entry in data.values():
            ticker = entry.get("ticker", "").upper()
            cik = str(entry.get("cik_str", "")).zfill(10)
            if ticker:
                _ticker_cik_cache[ticker] = cik
        logger.info("Loaded %d ticker→CIK mappings from EDGAR", len(_ticker_cik_cache))
    except Exception as exc:
        logger.error("Failed to load ticker→CIK map: %s", exc)
    return _ticker_cik_cache


def _get_cik(ticker: str) -> Optional[str]:
    mapping = _load_ticker_cik_map()
    return mapping.get(ticker.upper())


def _get_8k_filings(cik: str, max_filings: int = 8) -> list[dict]:
    """
    Return up to max_filings recent 8-K accession numbers from the
    EDGAR submissions JSON endpoint.
    """
    url = _SUBMISSIONS_URL.format(cik=cik)
    try:
        data = _get(url).json()
    except Exception as exc:
        logger.warning("Could not fetch submissions for CIK %s: %s", cik, exc)
        return []

    filings = data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    accessions = filings.get("accessionNumber", [])
    dates = filings.get("filingDate", [])

    results = []
    for form, acc, date in zip(forms, accessions, dates):
        if form in ("8-K", "8-K/A") and date >= "2021-01-01":
            results.append({"accession_no": acc, "filing_date": date})
        if len(results) >= max_filings:
            break
    return results


def _get_filing_documents(cik: str, accession_no: str) -> list[dict]:
    """
    Fetch the filing index and return list of {filename, description, type}.
    """
    acc_clean = accession_no.replace("-", "")
    index_url = (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{acc_clean}/{accession_no}-index.htm"
    )
    try:
        resp = _get(index_url)
        soup = BeautifulSoup(resp.text, "lxml")
        docs = []
        for row in soup.select("table tr"):
            cells = row.find_all("td")
            if len(cells) >= 3:
                link = cells[2].find("a")
                if link:
                    docs.append({
                        "filename": link.get_text(strip=True),
                        "url": "https://www.sec.gov" + link["href"],
                        "description": cells[1].get_text(strip=True) if len(cells) > 1 else "",
                        "type": cells[3].get_text(strip=True) if len(cells) > 3 else "",
                    })
        return docs
    except Exception as exc:
        logger.debug("Index fetch failed for %s: %s", accession_no, exc)
        return []


def _fetch_document_text(url: str) -> str:
    """Download and extract plain text from an HTML/HTM document."""
    try:
        resp = _get(url)
        soup = BeautifulSoup(resp.text, "lxml")
        return soup.get_text(separator="\n", strip=True)
    except Exception as exc:
        logger.debug("Document fetch failed %s: %s", url, exc)
        return ""


def _is_earnings_document(text: str) -> bool:
    """Heuristic: does this document look like an earnings press release?"""
    lower = text.lower()
    keywords = ["earnings", "quarterly results", "fourth quarter", "third quarter",
                "second quarter", "first quarter", "fiscal year", "revenue", "eps"]
    return sum(1 for kw in keywords if kw in lower) >= 3


def extract_mgmt_section(text: str) -> str:
    """
    Extract the management prepared-remarks / MD&A section.
    Falls back to the full document (capped at 8000 chars).
    """
    if not text:
        return ""
    lower = text.lower()

    start_idx = 0
    for marker in _MGMT_MARKERS:
        idx = lower.find(marker)
        if idx != -1:
            start_idx = idx
            break

    end_idx = len(text)
    for marker in _QA_MARKERS:
        idx = lower.find(marker, start_idx + 100)
        if idx != -1:
            end_idx = min(end_idx, idx)

    section = text[start_idx:end_idx].strip()
    return section[:8000] if section else text[:8000]


def count_hedge_words(text: str) -> int:
    lower = text.lower()
    return sum(lower.count(w) for w in _HEDGE_WORDS)


def infer_quarter(filing_date: str) -> str:
    try:
        month = int(filing_date[5:7])
        year = filing_date[:4]
        return f"Q{(month - 1) // 3 + 1} {year}"
    except Exception:
        return "Unknown"


def collect_transcripts(companies: list[dict]) -> None:
    """
    For each company: look up CIK → fetch 8-K list → download EX-99.1
    earnings documents → store in DB.
    """
    _load_ticker_cik_map()  # warm the cache once

    for company in companies:
        ticker = company["ticker"]
        name = company["name"]
        company_id = upsert_company(ticker, name)

        cik = _get_cik(ticker)
        if not cik:
            logger.warning("No CIK found for %s, skipping", ticker)
            continue

        logger.info("Collecting filings for %s (CIK %s)", ticker, cik)
        filings = _get_8k_filings(cik)

        stored = 0
        for filing in filings:
            accession_no = filing["accession_no"]
            filing_date = filing["filing_date"]
            quarter = infer_quarter(filing_date)

            with get_connection() as conn:
                if conn.execute(
                    "SELECT id FROM transcripts WHERE accession_no = ?", (accession_no,)
                ).fetchone():
                    continue

            # Get the document list for this filing
            docs = _get_filing_documents(cik, accession_no)
            if not docs:
                continue

            # Prefer EX-99.1 (earnings press release); fall back to first .htm
            target_doc = None
            for doc in docs:
                if "99.1" in doc.get("type", "") or "99.1" in doc.get("description", ""):
                    target_doc = doc
                    break
            if not target_doc:
                for doc in docs:
                    if doc["url"].endswith((".htm", ".html")):
                        target_doc = doc
                        break

            if not target_doc:
                continue

            raw_text = _fetch_document_text(target_doc["url"])
            if not raw_text or not _is_earnings_document(raw_text):
                continue

            mgmt_section = extract_mgmt_section(raw_text)

            with get_connection() as conn:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO transcripts
                           (company_id, quarter, filing_date, accession_no, raw_text, mgmt_section)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (company_id, quarter, filing_date, accession_no,
                         raw_text[:50000], mgmt_section),
                    )
                    stored += 1
                    logger.info("  Stored %s %s", ticker, quarter)
                except Exception as exc:
                    logger.debug("DB insert failed %s %s: %s", ticker, quarter, exc)

        if stored == 0:
            logger.warning("  No earnings documents stored for %s", ticker)
