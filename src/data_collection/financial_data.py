"""
Pull EPS estimates vs actuals and stock price reactions from Yahoo Finance
using the yfinance library (no API key required).
"""

import logging
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd

from src.database import get_connection

logger = logging.getLogger(__name__)


def _normalize_eps_surprise(surprise: float, clip: float = 2.0) -> float:
    """
    Map an EPS surprise (dollars) to a 1-10 scale.
    surprise = actual - estimate
    Positive = beat, negative = miss.
    clip defines the dollar range that maps to the extremes.
    """
    clamped = max(-clip, min(clip, surprise))
    # scale [-clip, +clip] -> [1, 10]
    return round(1 + (clamped + clip) / (2 * clip) * 9, 2)


def fetch_eps_data(ticker: str) -> list[dict]:
    """
    Return a list of quarterly EPS records for a ticker.
    Each record: {quarter, period_date, eps_estimate, eps_actual, eps_surprise}
    """
    try:
        stock = yf.Ticker(ticker)
        earnings = stock.earnings_dates  # DataFrame indexed by Earnings Date
        if earnings is None or earnings.empty:
            logger.warning("No earnings data for %s", ticker)
            return []

        records = []
        for date_idx, row in earnings.iterrows():
            try:
                dt = pd.Timestamp(date_idx).to_pydatetime()
                quarter = _date_to_quarter(dt)
                estimate = row.get("EPS Estimate")
                actual = row.get("Reported EPS")
                if pd.isna(estimate) or pd.isna(actual):
                    continue
                surprise = round(float(actual) - float(estimate), 4)
                records.append({
                    "quarter": quarter,
                    "period_date": dt.strftime("%Y-%m-%d"),
                    "eps_estimate": float(estimate),
                    "eps_actual": float(actual),
                    "eps_surprise": surprise,
                    "eps_normalized": _normalize_eps_surprise(surprise),
                })
            except Exception as exc:
                logger.debug("Row parse error for %s: %s", ticker, exc)
        return records

    except Exception as exc:
        logger.warning("yfinance error for %s: %s", ticker, exc)
        return []


def fetch_stock_reaction(ticker: str, period_date: str) -> float:
    """
    Compute the 1-day stock price change (%) on the trading day after earnings.
    Returns 0.0 on failure.
    """
    try:
        dt = datetime.strptime(period_date, "%Y-%m-%d")
        start = dt - timedelta(days=1)
        end = dt + timedelta(days=3)
        hist = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                           end=end.strftime("%Y-%m-%d"), progress=False)
        if hist.empty or len(hist) < 2:
            return 0.0
        prices = hist["Close"].values
        reaction = round((float(prices[1]) - float(prices[0])) / float(prices[0]) * 100, 2)
        return reaction
    except Exception as exc:
        logger.debug("Stock reaction fetch failed for %s %s: %s", ticker, period_date, exc)
        return 0.0


def collect_financial_results(companies: list[dict]) -> None:
    """
    Main entry point: for each company fetch EPS data and persist to DB.
    """
    for company in companies:
        ticker = company["ticker"]
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM companies WHERE ticker = ?", (ticker,)
            ).fetchone()
            if not row:
                logger.warning("Company not found in DB: %s", ticker)
                continue
            company_id = row["id"]

        logger.info("Fetching financial results for %s", ticker)
        eps_records = fetch_eps_data(ticker)

        for rec in eps_records:
            stock_reaction = fetch_stock_reaction(ticker, rec["period_date"])
            with get_connection() as conn:
                try:
                    conn.execute(
                        """INSERT OR REPLACE INTO financial_results
                           (company_id, quarter, period_date, eps_estimate,
                            eps_actual, eps_surprise, stock_reaction)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (company_id, rec["quarter"], rec["period_date"],
                         rec["eps_estimate"], rec["eps_actual"],
                         rec["eps_surprise"], stock_reaction),
                    )
                except Exception as exc:
                    logger.debug("DB insert error for %s %s: %s", ticker, rec["quarter"], exc)

        logger.info("  Stored %d quarters for %s", len(eps_records), ticker)


def _date_to_quarter(dt: datetime) -> str:
    q = (dt.month - 1) // 3 + 1
    return f"Q{q} {dt.year}"
