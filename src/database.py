"""SQLite database setup and helpers for FinSentinel."""

import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "finsentinel.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database() -> None:
    """Create all tables if they don't already exist."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS companies (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker      TEXT UNIQUE NOT NULL,
                name        TEXT NOT NULL,
                sector      TEXT DEFAULT 'Fintech'
            );

            CREATE TABLE IF NOT EXISTS transcripts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id      INTEGER NOT NULL REFERENCES companies(id),
                quarter         TEXT NOT NULL,   -- e.g. "Q3 2023"
                filing_date     TEXT NOT NULL,
                accession_no    TEXT UNIQUE NOT NULL,
                raw_text        TEXT,
                mgmt_section    TEXT,            -- extracted Management Discussion section
                UNIQUE(company_id, quarter)
            );

            CREATE TABLE IF NOT EXISTS financial_results (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id      INTEGER NOT NULL REFERENCES companies(id),
                quarter         TEXT NOT NULL,
                period_date     TEXT,
                eps_estimate    REAL,
                eps_actual      REAL,
                eps_surprise    REAL,            -- actual - estimate
                revenue_actual  REAL,
                stock_reaction  REAL,            -- % price change day after earnings
                UNIQUE(company_id, quarter)
            );

            CREATE TABLE IF NOT EXISTS sentiment_scores (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_id           INTEGER NOT NULL REFERENCES transcripts(id),
                confidence_score        REAL,    -- 1-10
                optimism_score          REAL,    -- 1-10
                hedging_count           INTEGER,
                numerical_commitments   INTEGER,
                raw_llm_response        TEXT,
                UNIQUE(transcript_id)
            );
        """)
    print(f"[DB] Database initialized at {DB_PATH}")


def upsert_company(ticker: str, name: str) -> int:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO companies (ticker, name) VALUES (?, ?)",
            (ticker, name),
        )
        row = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (ticker,)
        ).fetchone()
        return row["id"]
