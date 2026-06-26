"""
LLM-powered sentiment analysis of earnings call transcripts via OpenAI API.

Each transcript's Management Discussion section is scored on:
  - executive_confidence  (1-10)
  - forward_guidance_optimism  (1-10)
  - hedging_language_count  (integer)
  - numerical_commitments  (integer)
"""

import json
import logging
import os
import time

from openai import OpenAI

from src.database import get_connection
from src.data_collection.sec_edgar import count_hedge_words

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a financial analyst specializing in detecting
executive communication patterns in earnings calls. Analyze the provided
Management Discussion text and return ONLY a valid JSON object with these keys:

{
  "executive_confidence": <integer 1-10>,
  "forward_guidance_optimism": <integer 1-10>,
  "hedging_language_count": <integer>,
  "numerical_commitments": <integer>,
  "rationale": "<one sentence explaining your scores>"
}

Scoring guide:
- executive_confidence: 1 = very cautious/defensive, 10 = extremely bullish/assertive
- forward_guidance_optimism: 1 = bleak outlook, 10 = rosy projections
- hedging_language_count: count occurrences of hedging words (challenging, uncertain, headwinds, etc.)
- numerical_commitments: count specific numerical targets given (revenue guidance, margin targets, user growth %, etc.)
"""


def _call_openai(client: OpenAI, text: str) -> dict:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Earnings call transcript excerpt:\n\n{text}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=400,
    )
    return json.loads(response.choices[0].message.content)


def score_transcript(transcript_id: int, mgmt_text: str, client: OpenAI) -> dict:
    """
    Score a single transcript. Returns the parsed score dict.
    Falls back to heuristic scoring if the API call fails.
    """
    try:
        scores = _call_openai(client, mgmt_text)
        # Validate expected keys are present
        required = {"executive_confidence", "forward_guidance_optimism",
                    "hedging_language_count", "numerical_commitments"}
        if not required.issubset(scores.keys()):
            raise ValueError(f"Missing keys in LLM response: {scores}")
        return scores
    except Exception as exc:
        logger.warning("OpenAI call failed for transcript %d: %s. Using heuristics.", transcript_id, exc)
        return _heuristic_score(mgmt_text)


def _heuristic_score(text: str) -> dict:
    """
    Fallback scorer that uses keyword counting when the LLM is unavailable.
    Produces scores calibrated to match LLM outputs roughly.
    """
    hedging = count_hedge_words(text)
    positive_words = ["growth", "strong", "record", "beat", "exceeded",
                      "accelerat", "momentum", "outperform", "robust"]
    positive_count = sum(text.lower().count(w) for w in positive_words)

    # Rough confidence: more positive words, fewer hedges = higher score
    ratio = positive_count / max(hedging, 1)
    confidence = min(10, max(1, round(5 + ratio * 1.5)))
    optimism = min(10, max(1, round(5 + ratio)))

    # Count sentences with % or $ as numerical commitments
    numerical = sum(1 for sent in text.split(".") if "%" in sent or "$" in sent)

    return {
        "executive_confidence": confidence,
        "forward_guidance_optimism": optimism,
        "hedging_language_count": hedging,
        "numerical_commitments": min(numerical, 20),
        "rationale": "Heuristic fallback score (OpenAI unavailable)",
    }


def run_sentiment_analysis(use_openai: bool = True) -> None:
    """
    Score all transcripts that don't yet have a sentiment score.
    """
    client = None
    if use_openai:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("OPENAI_API_KEY not set — falling back to heuristics.")
            use_openai = False
        else:
            client = OpenAI(api_key=api_key)

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT t.id, t.mgmt_section, c.ticker, t.quarter
            FROM transcripts t
            JOIN companies c ON c.id = t.company_id
            LEFT JOIN sentiment_scores s ON s.transcript_id = t.id
            WHERE s.id IS NULL AND t.mgmt_section IS NOT NULL AND t.mgmt_section != ''
        """).fetchall()

    logger.info("Scoring %d transcripts...", len(rows))

    for row in rows:
        transcript_id = row["id"]
        mgmt_text = row["mgmt_section"]
        ticker = row["ticker"]
        quarter = row["quarter"]

        if use_openai and client:
            scores = score_transcript(transcript_id, mgmt_text, client)
            time.sleep(0.3)  # gentle rate limit
        else:
            scores = _heuristic_score(mgmt_text)

        with get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sentiment_scores
                   (transcript_id, confidence_score, optimism_score,
                    hedging_count, numerical_commitments, raw_llm_response)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    transcript_id,
                    scores.get("executive_confidence"),
                    scores.get("forward_guidance_optimism"),
                    scores.get("hedging_language_count"),
                    scores.get("numerical_commitments"),
                    json.dumps(scores),
                ),
            )
        logger.info("  Scored %s %s (confidence=%.1f, optimism=%.1f)",
                    ticker, quarter,
                    scores.get("executive_confidence", 0),
                    scores.get("forward_guidance_optimism", 0))
