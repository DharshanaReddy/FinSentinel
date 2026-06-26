"""
Compute the Integrity Gap Score and produce aggregated analytics.

Integrity Gap Score = executive_confidence_score - eps_normalized_score
  Positive  → executive was more optimistic than results justified
  Negative  → executive under-promised and over-delivered
"""

import logging
from pathlib import Path

import pandas as pd

from src.database import get_connection

logger = logging.getLogger(__name__)
OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"


def build_master_dataframe() -> pd.DataFrame:
    """
    Join transcripts, sentiment scores, and financial results into
    a single flat DataFrame for analysis.
    """
    query = """
        SELECT
            c.ticker,
            c.name,
            t.quarter,
            t.filing_date,
            s.confidence_score,
            s.optimism_score,
            s.hedging_count,
            s.numerical_commitments,
            f.eps_estimate,
            f.eps_actual,
            f.eps_surprise,
            f.stock_reaction
        FROM sentiment_scores s
        JOIN transcripts t       ON t.id = s.transcript_id
        JOIN companies c         ON c.id = t.company_id
        LEFT JOIN financial_results f
            ON f.company_id = t.company_id AND f.quarter = t.quarter
        ORDER BY c.ticker, t.quarter
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)

    if df.empty:
        logger.warning("No data found — have you run the collection and scoring steps?")
        return df

    # Normalize EPS surprise to 1-10 scale (clip at ±2 dollars)
    clip = 2.0
    df["eps_normalized"] = (
        df["eps_surprise"]
        .clip(-clip, clip)
        .apply(lambda x: round(1 + (x + clip) / (2 * clip) * 9, 2))
    )

    # Core metric: how much more confident the exec was vs what results showed
    df["integrity_gap"] = (df["confidence_score"] - df["eps_normalized"]).round(2)

    return df


def compute_company_aggregates(df: pd.DataFrame) -> pd.DataFrame:
    """Average integrity gap per company across all quarters."""
    agg = (
        df.groupby(["ticker", "name"])
        .agg(
            quarters_analyzed=("quarter", "count"),
            avg_confidence=("confidence_score", "mean"),
            avg_optimism=("optimism_score", "mean"),
            avg_hedging=("hedging_count", "mean"),
            avg_eps_surprise=("eps_surprise", "mean"),
            avg_integrity_gap=("integrity_gap", "mean"),
            worst_gap=("integrity_gap", "max"),
        )
        .reset_index()
        .sort_values("avg_integrity_gap", ascending=False)
        .round(2)
    )
    return agg


def top_misleading_quarters(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Quarters where exec language was most optimistic but results were worst."""
    worst = df.dropna(subset=["eps_surprise", "confidence_score"]).copy()
    worst = worst[worst["integrity_gap"] > 0]
    # Secondary sort: among equal gaps, rank by worst stock reaction
    return (
        worst.sort_values(["integrity_gap", "stock_reaction"], ascending=[False, True])
        .head(n)[["ticker", "quarter", "confidence_score", "optimism_score",
                   "hedging_count", "eps_surprise", "stock_reaction", "integrity_gap"]]
        .reset_index(drop=True)
    )


def worst_stock_reactions(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Quarters with the largest negative stock reaction after earnings."""
    data = df.dropna(subset=["stock_reaction"]).copy()
    return (
        data[data["stock_reaction"] < 0]
        .sort_values("stock_reaction")
        .head(n)[["ticker", "quarter", "confidence_score", "eps_surprise",
                   "stock_reaction", "integrity_gap"]]
        .reset_index(drop=True)
    )


def run_analysis() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Run full analysis pipeline. Returns (master_df, company_agg, worst_quarters).
    """
    df = build_master_dataframe()
    if df.empty:
        return df, pd.DataFrame(), pd.DataFrame()

    company_agg = compute_company_aggregates(df)
    worst_q = top_misleading_quarters(df)

    OUTPUT_DIR.mkdir(exist_ok=True)

    # Export CSVs
    df.to_csv(OUTPUT_DIR / "all_scores.csv", index=False)
    company_agg.to_csv(OUTPUT_DIR / "company_integrity_gaps.csv", index=False)
    worst_q.to_csv(OUTPUT_DIR / "worst_quarters.csv", index=False)

    logger.info("Analysis complete. Results saved to %s", OUTPUT_DIR)
    return df, company_agg, worst_q


def generate_findings_report(df: pd.DataFrame, company_agg: pd.DataFrame,
                              worst_q: pd.DataFrame) -> None:
    """Write a markdown findings report to output/findings.md."""
    if company_agg.empty:
        logger.warning("No data for report generation.")
        return

    top10 = company_agg.head(10)
    bottom3 = company_agg.tail(3)  # most honest executives

    lines = [
        "# FinSentinel — Earnings Call Integrity Report",
        "",
        f"**Analysis date:** {pd.Timestamp.now().strftime('%Y-%m-%d')}  ",
        f"**Companies analyzed:** {company_agg.shape[0]}  ",
        f"**Total quarters analyzed:** {df.shape[0]}  ",
        "",
        "---",
        "",
        "## Key Findings",
        "",
        "### 1. Companies With Highest Integrity Gap (Most Overconfident)",
        "",
        "| Rank | Ticker | Company | Avg Confidence | Avg EPS Surprise | Avg Gap |",
        "|------|--------|---------|---------------|-----------------|---------|",
    ]
    for i, row in enumerate(top10.itertuples(), 1):
        lines.append(
            f"| {i} | {row.ticker} | {row.name} | {row.avg_confidence:.1f} "
            f"| {row.avg_eps_surprise:+.3f} | **{row.avg_integrity_gap:.2f}** |"
        )

    lines += [
        "",
        "### 2. Worst Individual Quarters (High Talk, Poor Results)",
        "",
        "| Ticker | Quarter | Confidence | EPS Surprise | Stock Reaction | Gap |",
        "|--------|---------|-----------|-------------|---------------|-----|",
    ]
    for row in worst_q.head(10).itertuples():
        reaction = f"{row.stock_reaction:+.1f}%" if pd.notna(row.stock_reaction) else "N/A"
        surprise = f"{row.eps_surprise:+.3f}" if pd.notna(row.eps_surprise) else "N/A"
        lines.append(
            f"| {row.ticker} | {row.quarter} | {row.confidence_score:.1f} "
            f"| {surprise} | {reaction} | {row.integrity_gap:.2f} |"
        )

    lines += [
        "",
        "### 3. Most Honest Executives (Lowest Integrity Gap)",
        "",
        "| Ticker | Company | Avg Gap |",
        "|--------|---------|---------|",
    ]
    for row in bottom3.itertuples():
        lines.append(f"| {row.ticker} | {row.name} | {row.avg_integrity_gap:.2f} |")

    lines += [
        "",
        "---",
        "",
        "## Methodology",
        "",
        "1. **Transcripts** sourced from SEC EDGAR 8-K filings (free, public).",
        "2. **Sentiment scoring** performed by GPT-4o-mini on the Management Discussion section.",
        "3. **EPS data** pulled from Yahoo Finance via `yfinance`.",
        "4. **Integrity Gap** = Executive Confidence Score (1-10) minus Normalized EPS Result (1-10).",
        "   A gap > 2 is considered materially misleading.",
        "",
        "---",
        "*Generated by FinSentinel. Not investment advice.*",
    ]

    report_path = OUTPUT_DIR / "findings.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Findings report written to %s", report_path)
