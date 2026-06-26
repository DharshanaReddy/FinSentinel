# FinSentinel — Earnings Call Integrity Tracker

> **Do fintech executives tell investors the truth?**  
> FinSentinel cross-references what executives *say* on earnings calls with what the numbers actually *show* — and quantifies the gap.

---

## Why This Matters

Earnings calls are the primary channel through which public company executives communicate with investors. Research consistently shows that executive tone and language choices move markets — but do they reflect reality? In fintech, where growth narratives drive outsized valuations, the risk of misleading communication is especially high.

FinSentinel answers: *Which executives were most overconfident relative to their actual results?*

---

## Methodology

### Pipeline Overview

```
SEC EDGAR 8-K filings          Yahoo Finance EPS data
         │                              │
         ▼                              ▼
   Transcript extraction        EPS actual vs estimate
         │                              │
         └──────────────┬───────────────┘
                        ▼
              LLM Sentiment Scoring
          (GPT-4o-mini via OpenAI API)
                        │
                        ▼
           Integrity Gap Score Calculation
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
          CSV exports       Markdown report
              │
              ▼
         Matplotlib charts
```

### Integrity Gap Score

```
Integrity Gap = Executive Confidence Score (1–10)
              − Normalized EPS Result (1–10)
```

- **Positive gap** → Executive was more optimistic than results justified
- **Negative gap** → Executive under-promised and over-delivered (rare and admirable)
- **Gap > 2** → Considered materially misleading by this methodology

### LLM Scoring Dimensions

Each transcript's Management Discussion section is scored by GPT-4o-mini on:

| Metric | Range | Description |
|--------|-------|-------------|
| `executive_confidence` | 1–10 | Overall assertiveness and bullishness of tone |
| `forward_guidance_optimism` | 1–10 | How rosy the outlook for future quarters appears |
| `hedging_language_count` | Integer | Occurrences of "challenging", "uncertain", "headwinds", etc. |
| `numerical_commitments` | Integer | Specific numerical targets given (revenue %, margin, users) |

---

## Key Findings

> *Note: Run the pipeline with real data to populate your own findings. The examples below are illustrative of the analysis pattern.*

### Finding 1: Optimism Peaks Before Worst Misses
Across the fintech universe, executive confidence scores averaged **6.8/10** in quarters where EPS was subsequently missed by >$0.10. This suggests a consistent pattern of over-optimism before bad results — rather than honest pre-signaling of challenges.

### Finding 2: Hedging Language Is a Lagging, Not Leading, Indicator
Companies with high hedging word counts (>15 per call) typically had already reported a miss in the *prior* quarter. Executives hedge after disappointment, not before — which limits the signal value of cautious language for investors trying to anticipate results.

### Finding 3: Small-Cap Fintech Shows Larger Integrity Gaps
Companies with market caps under $2B showed 40% larger average integrity gaps than large-cap peers (PayPal, Block). Smaller companies face stronger pressure to maintain investor confidence and may face fewer institutional accountability checks on their narrative.

---

## Project Structure

```
FinSentinel/
├── main.py                          # Pipeline entry point
├── requirements.txt
├── .env.example                     # Copy to .env and add your OpenAI key
├── finsentinel.log                  # Run log (auto-generated)
├── src/
│   ├── database.py                  # SQLite schema + helpers
│   ├── data_collection/
│   │   ├── sec_edgar.py             # EDGAR 8-K transcript fetching
│   │   └── financial_data.py        # yfinance EPS + stock reaction data
│   ├── analysis/
│   │   ├── sentiment.py             # OpenAI LLM scoring
│   │   └── integrity_gap.py         # Integrity Gap computation + report
│   └── visualization/
│       └── charts.py                # Matplotlib charts
├── data/
│   └── finsentinel.db               # SQLite database (auto-generated)
└── output/
    ├── all_scores.csv               # Full per-quarter dataset
    ├── company_integrity_gaps.csv   # Aggregated per company
    ├── worst_quarters.csv           # Top misleading quarters
    ├── findings.md                  # Auto-generated markdown report
    ├── 01_confidence_vs_eps.png     # Scatter: confidence vs EPS beat/miss
    ├── 02_top10_integrity_gap.png   # Bar: top 10 integrity gap companies
    └── 03_sentiment_vs_stock.png    # Time series: sentiment vs stock reaction
```

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/your-username/FinSentinel.git
cd FinSentinel
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env and add your OpenAI API key
```

```
OPENAI_API_KEY=sk-...
```

> **No OpenAI key?** The pipeline includes a heuristic fallback scorer — results will be less precise but the pipeline will still run end-to-end.

### 3. Run the full pipeline

```bash
python main.py
```

Or run individual steps:

```bash
python main.py --step collect     # Pull data from EDGAR + Yahoo Finance
python main.py --step score       # Run LLM sentiment analysis
python main.py --step analyze     # Compute Integrity Gap + export CSVs
python main.py --step visualize   # Generate charts
```

---

## Technologies Used

| Technology | Purpose |
|-----------|---------|
| **Python 3.11+** | Core language |
| **SQLite** | Local data storage (no server needed) |
| **OpenAI API** (GPT-4o-mini) | LLM sentiment scoring of transcripts |
| **SEC EDGAR API** | Free public API for 8-K filings and transcripts |
| **yfinance** | EPS estimates, actuals, and stock price history |
| **pandas** | Data manipulation and aggregation |
| **matplotlib / seaborn** | Visualization |
| **python-dotenv** | Environment variable management |
| **BeautifulSoup4 / lxml** | HTML parsing of EDGAR filing pages |

---

## Data Sources

- **SEC EDGAR Full-Text Search**: `https://efts.sec.gov/LATEST/search-index` — free, no registration required, subject to SEC fair-use policy (~10 req/s)
- **Yahoo Finance via yfinance**: Free, no API key required, subject to Yahoo ToS

---

## Limitations & Caveats

- Not all 8-K filings contain earnings call transcripts — some companies publish transcripts separately or use third-party services (Seeking Alpha, Motley Fool). Coverage varies by company.
- EPS surprise alone is an imperfect proxy for "misleading" communication. A miss can result from macro factors outside management's control.
- LLM scoring introduces model-dependent noise. All scores should be treated as directional, not precise.
- **This project is for research and educational purposes only. Nothing here constitutes investment advice.**

---

## License

MIT License. See `LICENSE` for details.
