"""
analyzer.py — Technical Edge Playbook V23 analysis engine.

Phase A (Pre-Signal): 5 signals that detect reversal setups.
Phase B (Confluence):  6 independent confirmation checks.

Data sources:
  - Stocks (NYSE/NASDAQ): yfinance — daily 1y, weekly 3y
  - Crypto:               ccxt (Binance) — daily 1y, weekly 3y

All indicators are computed from raw OHLCV data; no TA library dependency.
If data is unavailable a signal returns None (not fabricated as True/False).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Result type
# ──────────────────────────────────────────────────────────────

@dataclass
class AnalysisResult:
    ticker: str
    asset_type: str                          # "stock" | "crypto"
    price: Optional[float]
    rsi: Optional[float]
    vol_ratio: Optional[float]
    trend: str                               # "BULLISH" | "BEARISH" | "NEUTRAL"
    phase_a_score: int
    phase_b_score: int
    phase_a_signals: dict[str, bool]
    phase_b_checks: dict[str, bool]
    recommendation: str                      # "BUY" | "WATCH" | "DCA" | "AVOID"
    entry_zone: Optional[float]
    target_1: Optional[float]
    target_2: Optional[float]
    stop_loss: Optional[float]
    thesis_text: str
    error: Optional[str] = None


# ──────────────────────────────────────────────────────────────
# Data fetching
# ──────────────────────────────────────────────────────────────

def _fetch_stock_data(ticker: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (daily_1y, weekly_3y) DataFrames for a stock ticker."""
    import yfinance as yf
    t = yf.Ticker(ticker)
    daily  = t.history(period="1y",  interval="1d",  auto_adjust=True)
    weekly = t.history(period="3y",  interval="1wk", auto_adjust=True)
    return daily, weekly


def _fetch_crypto_data(ticker: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (daily_1y, weekly_3y) DataFrames for a crypto ticker via ccxt/Binance."""
    import ccxt
    exchange = ccxt.binance({"enableRateLimit": True})
    symbol = f"{ticker}/USDT"

    def _to_df(ohlcv: list) -> pd.DataFrame:
        df = pd.DataFrame(
            ohlcv,
            columns=["timestamp", "Open", "High", "Low", "Close", "Volume"],
        )
        df["Date"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("Date", inplace=True)
        df.drop(columns=["timestamp"], inplace=True)
        return df.astype(float)

    daily_raw  = exchange.fetch_ohlcv(symbol, timeframe="1d",  limit=365)
    weekly_raw = exchange.fetch_ohlcv(symbol, timeframe="1w",  limit=160)
    return _to_df(daily_raw), _to_df(weekly_raw)


# ──────────────────────────────────────────────────────────────
# Indicator helpers
# ──────────────────────────────────────────────────────────────

def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder-smoothed RSI."""
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _compute_vol_ratio(df: pd.DataFrame, window: int = 20) -> Optional[float]:
    """Current volume / 20-day average volume. Returns None on insufficient data."""
    if len(df) < window + 1 or df["Volume"].iloc[-1] == 0:
        return None
    avg = df["Volume"].iloc[-(window + 1):-1].mean()
    if pd.isna(avg) or avg == 0:
        return None
    return round(float(df["Volume"].iloc[-1] / avg), 4)


def _pivot_lows(series: np.ndarray) -> list[float]:
    """Return values at local minima (requires neighbour on both sides)."""
    return [
        series[i]
        for i in range(1, len(series) - 1)
        if series[i] < series[i - 1] and series[i] < series[i + 1]
    ]


# ──────────────────────────────────────────────────────────────
# Phase A — Pre-Signal (5 signals)
# ──────────────────────────────────────────────────────────────

def detect_higher_low(df: pd.DataFrame, lookback: int = 30) -> Optional[bool]:
    """
    Higher Low: at least two successive local swing lows are rising.
    Returns None when there are fewer than two pivot lows in the window.
    """
    if len(df) < lookback:
        return None
    lows = df["Low"].tail(lookback).values
    pivots = _pivot_lows(lows)
    if len(pivots) < 2:
        return None
    return bool(all(pivots[i] > pivots[i - 1] for i in range(1, len(pivots))))


def detect_bullish_divergence(
    df: pd.DataFrame,
    rsi: pd.Series,
    lookback: int = 30,
) -> Optional[bool]:
    """
    Bullish Divergence: price makes a lower low while RSI makes a higher low
    within the last `lookback` bars.
    """
    if len(df) < lookback or rsi.dropna().empty:
        return None

    price_arr = df["Close"].tail(lookback).values
    rsi_arr   = rsi.tail(lookback).values

    price_pivots: list[tuple[int, float]] = []
    for i in range(1, len(price_arr) - 1):
        if price_arr[i] < price_arr[i - 1] and price_arr[i] < price_arr[i + 1]:
            price_pivots.append((i, price_arr[i]))

    if len(price_pivots) < 2:
        return None

    p1_idx, p1_price = price_pivots[-2]
    p2_idx, p2_price = price_pivots[-1]

    p1_rsi = rsi_arr[p1_idx]
    p2_rsi = rsi_arr[p2_idx]

    if np.isnan(p1_rsi) or np.isnan(p2_rsi):
        return None

    return bool(p2_price < p1_price and p2_rsi > p1_rsi)


def detect_hammer_or_engulfing(df: pd.DataFrame) -> Optional[bool]:
    """
    Reversal Candle: detects either a Hammer or a Bullish Engulfing on the last bar.

    Hammer:
      - Lower shadow ≥ 2× body
      - Upper shadow ≤ body
      - Body is not zero-length

    Bullish Engulfing:
      - Previous candle is bearish
      - Current candle is bullish and its body fully engulfs the previous body
    """
    if len(df) < 2:
        return None

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    body_curr  = abs(float(curr["Close"]) - float(curr["Open"]))
    lower_curr = float(min(curr["Close"], curr["Open"])) - float(curr["Low"])
    upper_curr = float(curr["High"]) - float(max(curr["Close"], curr["Open"]))

    # Hammer
    if body_curr > 0 and lower_curr >= 2 * body_curr and upper_curr <= body_curr:
        return True

    # Bullish Engulfing
    bearish_prev = float(prev["Close"]) < float(prev["Open"])
    bullish_curr = float(curr["Close"]) > float(curr["Open"])
    engulfs      = (
        float(curr["Open"])  < float(prev["Close"]) and
        float(curr["Close"]) > float(prev["Open"])
    )
    if bearish_prev and bullish_curr and engulfs:
        return True

    return False


def detect_vsa_selling_climax(
    df: pd.DataFrame,
    vol_multiplier: float = 1.5,
    lookback: int = 30,
    compression_bars: int = 3,
) -> Optional[bool]:
    """
    VSA Selling Climax:
      1. A bearish candle with volume > vol_multiplier × 20-day average.
      2. Followed by `compression_bars` bars of below-average volume
         where price does not make a new low (supply absorbed).
    """
    min_len = lookback + compression_bars + 5
    if len(df) < min_len:
        return None

    tail   = df.tail(lookback + compression_bars)
    vol_20 = df["Volume"].iloc[-(lookback + compression_bars + 5):-(compression_bars + 1)].mean()
    if pd.isna(vol_20) or vol_20 == 0:
        return None

    # Search within the tail (excluding the last `compression_bars` slots)
    search_end = len(tail) - compression_bars
    for i in range(search_end):
        candle = tail.iloc[i]
        is_high_vol = float(candle["Volume"]) > vol_20 * vol_multiplier
        is_bearish  = float(candle["Close"])  < float(candle["Open"])
        if not (is_high_vol and is_bearish):
            continue

        subsequent      = tail.iloc[i + 1: i + 1 + compression_bars]
        avg_subseq_vol  = subsequent["Volume"].mean()
        price_held      = float(subsequent["Low"].min()) >= float(candle["Low"]) * 0.99

        if avg_subseq_vol < vol_20 and price_held:
            return True

    return False


def detect_sma_curl_up(df: pd.DataFrame, slope_lookback: int = 5) -> Optional[bool]:
    """
    SMA Curl Up: SMA20 is above SMA50 AND its slope over the last
    `slope_lookback` bars is positive (curling upward).
    """
    close = df["Close"]
    if len(close) < 50 + slope_lookback:
        return None

    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()

    curr_sma20 = sma20.iloc[-1]
    curr_sma50 = sma50.iloc[-1]
    prev_sma20 = sma20.iloc[-slope_lookback - 1]

    if any(pd.isna(v) for v in (curr_sma20, curr_sma50, prev_sma20)):
        return None

    return bool(curr_sma20 > curr_sma50 and curr_sma20 > prev_sma20)


# ──────────────────────────────────────────────────────────────
# Phase B — Confluence (6 checks)
# ──────────────────────────────────────────────────────────────

def check_trend_filter(
    df: pd.DataFrame,
    weekly_df: Optional[pd.DataFrame] = None,
) -> tuple[Optional[bool], Optional[bool], str]:
    """
    Returns (above_sma150, above_sma200, trend_label).

    Uses daily data for SMA150/200. If daily has < 200 bars, falls back to
    weekly data (each bar = one week, so 200 weekly bars ≈ 4 years).
    """
    close   = df["Close"]
    price   = float(close.iloc[-1])

    sma150_val = close.rolling(150).mean().iloc[-1] if len(close) >= 150 else np.nan
    sma200_val = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else np.nan

    # Fall back to weekly when daily lacks bars
    if pd.isna(sma150_val) and weekly_df is not None and len(weekly_df) >= 150:
        weekly_close = weekly_df["Close"]
        weekly_price = float(weekly_close.iloc[-1])
        sma150_val   = weekly_close.rolling(150).mean().iloc[-1]
        sma200_val   = weekly_close.rolling(200).mean().iloc[-1] if len(weekly_close) >= 200 else np.nan
        price        = weekly_price  # use weekly price for comparison

    above_150 = None if pd.isna(sma150_val) else bool(price > float(sma150_val))
    above_200 = None if pd.isna(sma200_val) else bool(price > float(sma200_val))

    if above_200 is True and above_150 is True:
        trend = "BULLISH"
    elif above_200 is False and above_150 is False:
        trend = "BEARISH"
    else:
        trend = "NEUTRAL"

    return above_150, above_200, trend


def check_fibonacci_level(df: pd.DataFrame, tolerance: float = 0.03) -> Optional[bool]:
    """
    Returns True if the current price is within ±tolerance of the 0.618
    or 0.5 Fibonacci retracement of the last 60-bar swing.
    """
    lookback = min(60, len(df))
    if lookback < 10:
        return None

    tail        = df.tail(lookback)
    swing_high  = float(tail["High"].max())
    swing_low   = float(tail["Low"].min())
    price       = float(df["Close"].iloc[-1])

    if swing_high <= swing_low:
        return None

    rng      = swing_high - swing_low
    fib_618  = swing_high - 0.618 * rng
    fib_50   = swing_high - 0.500 * rng

    near_618 = abs(price - fib_618) / fib_618 <= tolerance
    near_50  = abs(price - fib_50)  / fib_50  <= tolerance

    return bool(near_618 or near_50)


def check_volume_confirmation(df: pd.DataFrame, threshold: float = 1.30) -> Optional[bool]:
    """Returns True if the last bar's volume is ≥ threshold × 20-day average."""
    ratio = _compute_vol_ratio(df)
    if ratio is None:
        return None
    return bool(ratio >= threshold)


def check_gap_breakaway(df: pd.DataFrame, min_gap_pct: float = 0.01) -> Optional[bool]:
    """
    Returns True if any of the last 3 candles opened at least min_gap_pct
    above the prior close (a breakaway gap to the upside).
    """
    if len(df) < 4:
        return None
    for i in range(-3, 0):
        try:
            gap_pct = (float(df["Open"].iloc[i]) - float(df["Close"].iloc[i - 1])) / \
                      float(df["Close"].iloc[i - 1])
            if gap_pct >= min_gap_pct:
                return True
        except (IndexError, ZeroDivisionError):
            continue
    return False


def check_rsi_oversold(rsi: pd.Series, threshold: float = 40.0) -> Optional[bool]:
    """Returns True if the latest RSI reading is below threshold."""
    if rsi is None or rsi.dropna().empty:
        return None
    val = rsi.iloc[-1]
    return None if pd.isna(val) else bool(float(val) < threshold)


# ──────────────────────────────────────────────────────────────
# Targets
# ──────────────────────────────────────────────────────────────

def _calculate_targets(
    df: pd.DataFrame,
) -> tuple[float, float, float, float]:
    """
    entry   = current close
    stop    = 20-bar swing low (floored at −7% to avoid absurdly tight stops)
    target1 = entry + 1.5 × risk   (risk = entry − stop)
    target2 = entry + 3.0 × risk
    """
    price = float(df["Close"].iloc[-1])
    swing_low = float(df["Low"].tail(20).min())

    # Ensure stop is at most 7% below price so risk/reward stays sensible
    stop = max(swing_low, price * 0.93)
    risk = max(price - stop, price * 0.02)   # minimum 2% risk

    return (
        round(price,          4),
        round(price + 1.5 * risk, 4),
        round(price + 3.0 * risk, 4),
        round(stop,           4),
    )


# ──────────────────────────────────────────────────────────────
# Recommendation logic
# ──────────────────────────────────────────────────────────────

def _determine_recommendation(
    phase_a: int,
    phase_b: int,
    trend: str,
    rsi: Optional[float],
) -> str:
    if phase_a >= 3 and phase_b >= 4 and trend == "BULLISH":
        return "BUY"
    if phase_a >= 2 and phase_b >= 3:
        return "WATCH"
    if phase_b >= 2 and rsi is not None and rsi < 35:
        return "DCA"
    return "AVOID"


# ──────────────────────────────────────────────────────────────
# Thesis text (programmatic; Gemini enhancement is optional)
# ──────────────────────────────────────────────────────────────

_SIGNAL_LABELS_HE: dict[str, str] = {
    "higher_low":      "Higher Low — שפל עולה",
    "divergence":      "Bullish Divergence — סטייה שורית",
    "reversal_candle": "Reversal Candle — Hammer / Engulfing",
    "vsa_climax":      "VSA Selling Climax",
    "sma_curl":        "SMA Curl Up — SMA20 מעל SMA50",
}

_CHECK_LABELS_HE: dict[str, str] = {
    "above_sma150": "מחיר מעל SMA150",
    "above_sma200": "מחיר מעל SMA200",
    "fibonacci":    "רמת Fibonacci (0.5 / 0.618)",
    "volume":       "Volume ≥ 130% ממוצע",
    "gap":          "Breakaway Gap שורי",
    "rsi_oversold": "RSI < 40 — אזור קנייה",
}


def _build_thesis_text(
    ticker: str,
    result_dict: dict,
) -> str:
    """Build a Hebrew thesis summary without any LLM call."""
    rec    = result_dict["recommendation"]
    trend  = result_dict["trend"]
    pa     = result_dict["phase_a_score"]
    pb     = result_dict["phase_b_score"]
    sigs   = [_SIGNAL_LABELS_HE.get(k, k) for k, v in result_dict["phase_a_signals"].items() if v]
    checks = [_CHECK_LABELS_HE.get(k, k)   for k, v in result_dict["phase_b_checks"].items()  if v]

    trend_he = {"BULLISH": "שורי", "BEARISH": "דובי", "NEUTRAL": "ניטרלי"}.get(trend, trend)

    lines = [
        f"תזה טכנית ל-{ticker} | המלצה: {rec} | מגמה: {trend_he}",
        "",
        f"Phase A — {pa}/5:",
        *([f"  • {s}" for s in sigs] or ["  (אין סיגנלים פעילים)"]),
        "",
        f"Phase B — {pb}/6:",
        *([f"  • {c}" for c in checks] or ["  (אין אישורים)"]),
    ]
    return "\n".join(lines)


def _try_gemini_thesis(
    ticker: str,
    result_dict: dict,
    api_key: Optional[str],
) -> Optional[str]:
    """
    Optional: enrich thesis text with a Gemini Flash call.
    Returns None (silently) if the key is missing or the call fails.
    """
    if not api_key:
        return None
    try:
        import google.generativeai as genai  # type: ignore
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = (
            f"אתה אנליסט טכני. סכם בעברית בשלוש משפטים קצרים את התזה הבאה עבור {ticker}:\n"
            f"המלצה: {result_dict['recommendation']}, מגמה: {result_dict['trend']}, "
            f"Phase A: {result_dict['phase_a_score']}/5, Phase B: {result_dict['phase_b_score']}/6.\n"
            f"סיגנלים: {', '.join(k for k,v in result_dict['phase_a_signals'].items() if v)}.\n"
            f"אישורים: {', '.join(k for k,v in result_dict['phase_b_checks'].items() if v)}."
        )
        resp = model.generate_content(prompt)
        return resp.text.strip()
    except Exception as exc:
        logger.warning("Gemini thesis generation failed: %s", exc)
        return None


# ──────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────

def analyze(
    ticker: str,
    asset_type: str,
    gemini_api_key: Optional[str] = None,
) -> AnalysisResult:
    """
    Run the full Technical Edge Playbook analysis on one ticker.

    Returns an AnalysisResult. On any data-fetch failure the result has
    error set and all scores are 0 / recommendation is "AVOID".
    """
    # ── Fetch ──────────────────────────────────────────────────
    try:
        if asset_type == "crypto":
            df_daily, df_weekly = _fetch_crypto_data(ticker)
        else:
            df_daily, df_weekly = _fetch_stock_data(ticker)

        if df_daily.empty or len(df_daily) < 30:
            raise ValueError(f"Insufficient daily data: {len(df_daily)} bars")
    except Exception as exc:
        logger.error("Data fetch failed for %s: %s", ticker, exc)
        return AnalysisResult(
            ticker=ticker, asset_type=asset_type, price=None, rsi=None,
            vol_ratio=None, trend="NEUTRAL", phase_a_score=0, phase_b_score=0,
            phase_a_signals={}, phase_b_checks={}, recommendation="AVOID",
            entry_zone=None, target_1=None, target_2=None, stop_loss=None,
            thesis_text="", error=str(exc),
        )

    # ── Core indicators ────────────────────────────────────────
    rsi_series = _compute_rsi(df_daily["Close"])
    rsi_val    = float(rsi_series.iloc[-1]) if not rsi_series.dropna().empty else None
    vol_ratio  = _compute_vol_ratio(df_daily)
    price      = float(df_daily["Close"].iloc[-1])

    # ── Phase A — 5 signals ────────────────────────────────────
    hl  = detect_higher_low(df_daily)
    div = detect_bullish_divergence(df_daily, rsi_series)
    ham = detect_hammer_or_engulfing(df_daily)
    vsa = detect_vsa_selling_climax(df_daily)
    sma = detect_sma_curl_up(df_daily)

    phase_a_signals = {
        "higher_low":      bool(hl)  if hl  is not None else False,
        "divergence":      bool(div) if div is not None else False,
        "reversal_candle": bool(ham) if ham is not None else False,
        "vsa_climax":      bool(vsa) if vsa is not None else False,
        "sma_curl":        bool(sma) if sma is not None else False,
    }
    phase_a_score = sum(phase_a_signals.values())

    # ── Phase B — 6 checks ─────────────────────────────────────
    above_150, above_200, trend = check_trend_filter(df_daily, df_weekly)
    fib  = check_fibonacci_level(df_daily)
    vol  = check_volume_confirmation(df_daily)
    gap  = check_gap_breakaway(df_daily)
    rsi_os = check_rsi_oversold(rsi_series)

    phase_b_checks = {
        "above_sma150": bool(above_150) if above_150 is not None else False,
        "above_sma200": bool(above_200) if above_200 is not None else False,
        "fibonacci":    bool(fib)       if fib       is not None else False,
        "volume":       bool(vol)       if vol       is not None else False,
        "gap":          bool(gap)       if gap       is not None else False,
        "rsi_oversold": bool(rsi_os)   if rsi_os    is not None else False,
    }
    phase_b_score = sum(phase_b_checks.values())

    # ── Recommendation ─────────────────────────────────────────
    recommendation = _determine_recommendation(phase_a_score, phase_b_score, trend, rsi_val)

    # ── Targets ────────────────────────────────────────────────
    entry_zone, target_1, target_2, stop_loss = _calculate_targets(df_daily)

    # ── Thesis text ────────────────────────────────────────────
    result_dict = {
        "recommendation": recommendation,
        "trend":          trend,
        "phase_a_score":  phase_a_score,
        "phase_b_score":  phase_b_score,
        "phase_a_signals": phase_a_signals,
        "phase_b_checks":  phase_b_checks,
    }
    thesis_text = (
        _try_gemini_thesis(ticker, result_dict, gemini_api_key)
        or _build_thesis_text(ticker, result_dict)
    )

    return AnalysisResult(
        ticker=ticker,
        asset_type=asset_type,
        price=round(price, 4),
        rsi=round(rsi_val, 2) if rsi_val is not None else None,
        vol_ratio=vol_ratio,
        trend=trend,
        phase_a_score=phase_a_score,
        phase_b_score=phase_b_score,
        phase_a_signals=phase_a_signals,
        phase_b_checks=phase_b_checks,
        recommendation=recommendation,
        entry_zone=entry_zone,
        target_1=target_1,
        target_2=target_2,
        stop_loss=stop_loss,
        thesis_text=thesis_text,
        error=None,
    )
