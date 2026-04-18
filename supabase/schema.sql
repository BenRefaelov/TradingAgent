-- Trading Agent — Supabase Schema
-- Run once in Supabase SQL Editor: Dashboard → SQL Editor → New Query → Paste → Run

-- ────────────────────────────────────────────
-- 1. watchlist
-- ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS watchlist (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker     TEXT        UNIQUE NOT NULL,
    type       TEXT        NOT NULL CHECK (type IN ('stock', 'crypto')),
    active     BOOLEAN     NOT NULL DEFAULT true,
    added_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ────────────────────────────────────────────
-- 2. theses
-- ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS theses (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker           TEXT        NOT NULL,
    thesis           TEXT        NOT NULL,
    recommendation   TEXT        NOT NULL CHECK (recommendation IN ('BUY', 'WATCH', 'DCA', 'AVOID')),
    entry_zone       NUMERIC(12,4),
    target_1         NUMERIC(12,4),
    target_2         NUMERIC(12,4),
    stop_loss        NUMERIC(12,4),
    status           TEXT        NOT NULL DEFAULT 'active'
                                 CHECK (status IN ('active', 'target_1_hit', 'target_2_hit', 'stop_hit', 'broken')),
    phase_a_score    INTEGER     NOT NULL DEFAULT 0,
    phase_b_score    INTEGER     NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Auto-update updated_at on every row change
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_theses_updated_at ON theses;
CREATE TRIGGER trg_theses_updated_at
    BEFORE UPDATE ON theses
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ────────────────────────────────────────────
-- 3. scan_log
-- ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scan_log (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    thesis_id  UUID        REFERENCES theses(id) ON DELETE SET NULL,
    ticker     TEXT        NOT NULL,
    price      NUMERIC(12,4),
    rsi        NUMERIC(6,2),
    vol_ratio  NUMERIC(8,4),
    verdict    TEXT,
    raw_data   JSONB,
    scanned_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ────────────────────────────────────────────
-- Indexes
-- ────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_theses_ticker_status ON theses (ticker, status);
CREATE INDEX IF NOT EXISTS idx_scan_log_scanned_at  ON scan_log (scanned_at DESC);
CREATE INDEX IF NOT EXISTS idx_scan_log_ticker      ON scan_log (ticker);

-- ────────────────────────────────────────────
-- Seed data — 5 stocks + 3 crypto
-- ────────────────────────────────────────────
INSERT INTO watchlist (ticker, type) VALUES
    ('AAPL', 'stock'),
    ('NVDA', 'stock'),
    ('MSFT', 'stock'),
    ('TSLA', 'stock'),
    ('AMZN', 'stock'),
    ('BTC',  'crypto'),
    ('ETH',  'crypto'),
    ('SOL',  'crypto')
ON CONFLICT (ticker) DO NOTHING;
