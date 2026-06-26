"""
Matplotlib visualizations for FinSentinel.

Charts produced:
  1. Scatter — executive confidence vs EPS beat/miss (all quarters)
  2. Bar     — top 10 integrity gap companies
  3. Time series — sentiment vs stock price reaction for 3 most misleading companies
"""

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # non-interactive backend for headless environments
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

logger = logging.getLogger(__name__)
OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"

PALETTE = {
    "primary": "#1565C0",
    "accent": "#E53935",
    "neutral": "#546E7A",
    "highlight": "#FB8C00",
    "bg": "#F5F7FA",
    "grid": "#E0E0E0",
}


def _save(fig: plt.Figure, name: str) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / name
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=PALETTE["bg"])
    plt.close(fig)
    logger.info("Saved chart: %s", path)


def plot_confidence_vs_eps(df: pd.DataFrame) -> None:
    """
    Scatter plot: x = confidence score, y = EPS surprise, coloured by integrity gap.
    """
    data = df.dropna(subset=["confidence_score", "eps_surprise", "integrity_gap"]).copy()
    if data.empty:
        logger.warning("No data for scatter plot.")
        return

    fig, ax = plt.subplots(figsize=(10, 7), facecolor=PALETTE["bg"])
    ax.set_facecolor(PALETTE["bg"])

    sc = ax.scatter(
        data["confidence_score"],
        data["eps_surprise"],
        c=data["integrity_gap"],
        cmap="RdYlGn_r",
        alpha=0.75,
        s=80,
        edgecolors="white",
        linewidths=0.5,
    )

    cbar = fig.colorbar(sc, ax=ax, pad=0.02)
    cbar.set_label("Integrity Gap Score", fontsize=11)

    # Reference lines
    ax.axhline(0, color=PALETTE["neutral"], linewidth=1, linestyle="--", alpha=0.6)
    ax.axvline(5.5, color=PALETTE["neutral"], linewidth=1, linestyle="--", alpha=0.6)

    # Annotate quadrants
    ax.text(8.5, ax.get_ylim()[0] * 0.9, "Overconfident\n& Missed",
            ha="center", fontsize=9, color=PALETTE["accent"], alpha=0.8)
    ax.text(2.5, ax.get_ylim()[1] * 0.85, "Cautious\n& Beat",
            ha="center", fontsize=9, color=PALETTE["primary"], alpha=0.8)

    # Label top outliers
    top_gap = data.nlargest(5, "integrity_gap")
    for _, row in top_gap.iterrows():
        ax.annotate(
            f"{row['ticker']} {row['quarter']}",
            xy=(row["confidence_score"], row["eps_surprise"]),
            xytext=(8, 4),
            textcoords="offset points",
            fontsize=7,
            color=PALETTE["accent"],
        )

    ax.set_xlabel("Executive Confidence Score (1–10)", fontsize=12)
    ax.set_ylabel("EPS Surprise (Actual − Estimate, $)", fontsize=12)
    ax.set_title("Executive Confidence vs EPS Beat/Miss\nAll Quarters Analyzed",
                 fontsize=14, fontweight="bold", pad=15)
    ax.grid(color=PALETTE["grid"], linewidth=0.5)
    ax.set_xlim(0.5, 10.5)

    _save(fig, "01_confidence_vs_eps.png")


def plot_top10_integrity_gap(company_agg: pd.DataFrame) -> None:
    """
    Horizontal bar chart of the 10 companies with highest average integrity gap.
    """
    top10 = company_agg.head(10).copy()
    if top10.empty:
        logger.warning("No data for bar chart.")
        return

    top10 = top10.sort_values("avg_integrity_gap")  # ascending for horizontal bar

    fig, ax = plt.subplots(figsize=(10, 6), facecolor=PALETTE["bg"])
    ax.set_facecolor(PALETTE["bg"])

    colors = [PALETTE["accent"] if g > 3 else PALETTE["highlight"] if g > 1.5
              else PALETTE["neutral"] for g in top10["avg_integrity_gap"]]

    bars = ax.barh(
        top10["ticker"],
        top10["avg_integrity_gap"],
        color=colors,
        edgecolor="white",
        linewidth=0.5,
        height=0.6,
    )

    # Value labels
    for bar, val in zip(bars, top10["avg_integrity_gap"]):
        ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
                f"{val:.2f}", va="center", fontsize=9, color=PALETTE["neutral"])

    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Average Integrity Gap Score", fontsize=12)
    ax.set_title("Top 10 Companies by Integrity Gap Score\n"
                 "(Higher = Executive more optimistic than results justified)",
                 fontsize=13, fontweight="bold", pad=12)
    ax.grid(axis="x", color=PALETTE["grid"], linewidth=0.5)

    # Legend
    from matplotlib.patches import Patch
    legend_els = [
        Patch(color=PALETTE["accent"], label="High concern (gap > 3)"),
        Patch(color=PALETTE["highlight"], label="Moderate (gap 1.5–3)"),
        Patch(color=PALETTE["neutral"], label="Low (gap < 1.5)"),
    ]
    ax.legend(handles=legend_els, loc="lower right", fontsize=9)

    _save(fig, "02_top10_integrity_gap.png")


def plot_sentiment_vs_stock(df: pd.DataFrame, company_agg: pd.DataFrame) -> None:
    """
    Time series for the 3 most misleading companies:
    dual-axis plot of confidence score and stock price reaction by quarter.
    """
    top3_tickers = company_agg.head(3)["ticker"].tolist()
    if not top3_tickers:
        logger.warning("No data for time series chart.")
        return

    fig, axes = plt.subplots(len(top3_tickers), 1,
                             figsize=(12, 4.5 * len(top3_tickers)),
                             facecolor=PALETTE["bg"])
    if len(top3_tickers) == 1:
        axes = [axes]

    for ax, ticker in zip(axes, top3_tickers):
        ax.set_facecolor(PALETTE["bg"])
        sub = df[df["ticker"] == ticker].copy()
        sub = sub.sort_values("quarter")

        if sub.empty:
            continue

        quarters = sub["quarter"].tolist()
        x = range(len(quarters))

        color1, color2 = PALETTE["primary"], PALETTE["accent"]

        ax.bar(x, sub["confidence_score"], color=color1, alpha=0.6,
               label="Confidence Score", width=0.4)

        ax2 = ax.twinx()
        ax2.plot(x, sub["stock_reaction"], color=color2, marker="o",
                 linewidth=2, label="Stock Reaction (%)")
        ax2.axhline(0, color=PALETTE["neutral"], linewidth=0.8, linestyle=":")

        ax.set_xticks(list(x))
        ax.set_xticklabels(quarters, rotation=45, ha="right", fontsize=9)
        ax.set_ylabel("Confidence Score (1–10)", color=color1, fontsize=10)
        ax2.set_ylabel("Stock Reaction % (Day After)", color=color2, fontsize=10)
        ax.set_title(f"{ticker} — Earnings Confidence vs Market Reaction",
                     fontsize=12, fontweight="bold")
        ax.grid(axis="y", color=PALETTE["grid"], linewidth=0.5)

        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9)

    fig.suptitle("Top 3 Most Misleading Companies: Sentiment vs Market Reality",
                 fontsize=14, fontweight="bold", y=1.01)
    fig.tight_layout()
    _save(fig, "03_sentiment_vs_stock.png")


def generate_all_charts(df: pd.DataFrame, company_agg: pd.DataFrame) -> None:
    plot_confidence_vs_eps(df)
    plot_top10_integrity_gap(company_agg)
    plot_sentiment_vs_stock(df, company_agg)
    logger.info("All charts generated in %s", OUTPUT_DIR)
