"""
FinSentinel — Earnings Call Integrity Tracker
Entry point for the full pipeline.

Usage:
    python main.py [--step collect|score|analyze|visualize|all]

Steps:
    collect   — Pull 8-K transcripts from SEC EDGAR + EPS data from Yahoo Finance
    score     — Run LLM sentiment analysis on transcripts
    analyze   — Compute Integrity Gap Scores and export CSVs / markdown report
    visualize — Generate matplotlib charts
    all       — Run every step in sequence (default)
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("finsentinel.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("finsentinel")

# ── Company universe ─────────────────────────────────────────────────────────
COMPANIES = [
    {"ticker": "PYPL",  "name": "PayPal"},
    {"ticker": "SOFI",  "name": "SoFi Technologies"},
    {"ticker": "AFRM",  "name": "Affirm Holdings"},
    {"ticker": "UPST",  "name": "Upstart Holdings"},
    {"ticker": "LC",    "name": "LendingClub"},
    {"ticker": "GDOT",  "name": "Green Dot"},
    {"ticker": "NCNO",  "name": "nCino"},
    {"ticker": "PGY",   "name": "Pagaya Technologies"},
    {"ticker": "DAVE",  "name": "Dave Inc"},
    {"ticker": "ML",    "name": "MoneyLion"},
    {"ticker": "SQ",    "name": "Block Inc"},
    {"ticker": "HOOD",  "name": "Robinhood Markets"},
    {"ticker": "COIN",  "name": "Coinbase Global"},
    {"ticker": "OPEN",  "name": "Opendoor Technologies"},
    {"ticker": "LMND",  "name": "Lemonade"},
    {"ticker": "ROOT",  "name": "Root Inc"},
    {"ticker": "RELY",  "name": "Remitly Global"},
    {"ticker": "TOST",  "name": "Toast Inc"},
    {"ticker": "BILL",  "name": "Bill Holdings"},
    {"ticker": "MQ",    "name": "Marqeta"},
    {"ticker": "FLYW",  "name": "Flywire"},
    {"ticker": "STER",  "name": "Sterling Check"},
    {"ticker": "RPAY",  "name": "Repay Holdings"},
    {"ticker": "IIIV",  "name": "i3 Verticals"},
    {"ticker": "PAYA",  "name": "Paya Holdings"},
    {"ticker": "PRAA",  "name": "PRA Group"},
    {"ticker": "ENVA",  "name": "Enova International"},
    {"ticker": "WRLD",  "name": "World Acceptance"},
    {"ticker": "RM",    "name": "Regional Management"},
    {"ticker": "ATLC",  "name": "Atlanticus Holdings"},
    {"ticker": "NRDS",  "name": "NerdWallet"},
    {"ticker": "OPFI",  "name": "OppFi"},
    {"ticker": "LPRO",  "name": "Open Lending"},
    {"ticker": "FLFR",  "name": "Flaherty & Crumrine"},
]


def step_collect() -> None:
    from src.database import initialize_database
    from src.data_collection.sec_edgar import collect_transcripts
    from src.data_collection.financial_data import collect_financial_results

    logger.info("=== Step 1: Data Collection ===")
    initialize_database()
    collect_transcripts(COMPANIES)
    collect_financial_results(COMPANIES)


def step_score() -> None:
    from src.analysis.sentiment import run_sentiment_analysis

    logger.info("=== Step 2: LLM Sentiment Analysis ===")
    use_openai = bool(os.getenv("OPENAI_API_KEY"))
    if not use_openai:
        logger.warning("OPENAI_API_KEY not set — heuristic fallback will be used.")
    run_sentiment_analysis(use_openai=use_openai)


def step_analyze() -> tuple:
    from src.analysis.integrity_gap import run_analysis, generate_findings_report

    logger.info("=== Step 3: Integrity Gap Analysis ===")
    df, company_agg, worst_q = run_analysis()
    if not df.empty:
        generate_findings_report(df, company_agg, worst_q)
    return df, company_agg, worst_q


def step_visualize(df, company_agg) -> None:
    from src.visualization.charts import generate_all_charts

    logger.info("=== Step 4: Visualizations ===")
    if df.empty:
        logger.warning("No data to visualize.")
        return
    generate_all_charts(df, company_agg)


def main() -> None:
    parser = argparse.ArgumentParser(description="FinSentinel Pipeline")
    parser.add_argument(
        "--step",
        choices=["collect", "score", "analyze", "visualize", "all"],
        default="all",
        help="Which pipeline step to run (default: all)",
    )
    args = parser.parse_args()

    df, company_agg = None, None

    if args.step in ("collect", "all"):
        step_collect()

    if args.step in ("score", "all"):
        step_score()

    if args.step in ("analyze", "all"):
        df, company_agg, _ = step_analyze()

    if args.step in ("visualize", "all"):
        if df is None:
            # Load from DB without re-running full analysis
            from src.analysis.integrity_gap import build_master_dataframe, compute_company_aggregates
            df = build_master_dataframe()
            company_agg = compute_company_aggregates(df)
        step_visualize(df, company_agg)

    logger.info("=== FinSentinel pipeline complete. Check output/ for results. ===")


if __name__ == "__main__":
    main()
