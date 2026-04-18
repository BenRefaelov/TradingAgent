"""
main.py — Trading Agent entry point.

Execution flow per scan cycle:
  1. Load configuration from environment variables.
  2. Determine scan mode: all assets | crypto-only.
  3. Load watchlist (Supabase first, WATCHLIST env-var fallback).
  4. Monitor all currently active theses against current prices.
  5. Analyse every ticker in scope.
  6. Upsert theses for actionable signals (BUY / WATCH / DCA).
  7. Log every scan result to scan_log.
  8. Send status-change alerts + scan summary to Telegram.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from analyzer import AnalysisResult, analyze
from notifier import (
    notify_error,
    notify_new_thesis,
    notify_scan_summary,
    notify_thesis_update,
)
from thesis_engine import (
    get_all_active_theses,
    log_scan,
    monitor_thesis,
    upsert_thesis,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────

def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise EnvironmentError(f"Required environment variable '{name}' is not set.")
    return val


def _optional_env(name: str) -> Optional[str]:
    return os.getenv(name) or None


def _build_supabase_client() -> Optional[Any]:
    url = _optional_env("SUPABASE_URL")
    key = _optional_env("SUPABASE_KEY")
    if not url or not key:
        logger.warning("Supabase credentials missing — running without DB persistence.")
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception as exc:
        logger.error("Supabase client init failed: %s", exc)
        return None


def _is_crypto_only_run() -> bool:
    """
    Crypto-only mode is triggered either by:
      - CRYPTO_ONLY=true env var (set by scan.yml when hour == 03 UTC), or
      - current UTC hour being 3 (safety net for local runs).
    """
    if os.getenv("CRYPTO_ONLY", "").lower() == "true":
        return True
    return datetime.now(timezone.utc).hour == 3


# ──────────────────────────────────────────────────────────────
# Watchlist loading
# ──────────────────────────────────────────────────────────────

def _load_watchlist(db: Optional[Any]) -> list[dict]:
    """Return list of {ticker, type} dicts from Supabase or WATCHLIST env-var."""
    if db is not None:
        try:
            resp = db.table("watchlist").select("ticker,type").eq("active", True).execute()
            if resp.data:
                logger.info("Loaded %d tickers from Supabase watchlist.", len(resp.data))
                return resp.data
        except Exception as exc:
            logger.warning("Supabase watchlist fetch failed (%s) — falling back to env.", exc)

    raw = os.getenv("WATCHLIST", "[]")
    try:
        items = json.loads(raw)
        if not isinstance(items, list):
            raise ValueError("WATCHLIST must be a JSON array.")
        logger.info("Loaded %d tickers from WATCHLIST env-var.", len(items))
        return items
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("WATCHLIST env-var parse error: %s", exc)
        return []


# ──────────────────────────────────────────────────────────────
# Per-ticker orchestration
# ──────────────────────────────────────────────────────────────

def _process_ticker(
    item: dict,
    db: Optional[Any],
    tg_token: Optional[str],
    tg_chat:  Optional[str],
    gemini_key: Optional[str],
    active_theses_map: dict[str, dict],
) -> dict:
    """
    Run full analysis on one ticker, manage thesis lifecycle, and return a
    slim result dict for the summary notification.
    """
    ticker     = item["ticker"]
    asset_type = item.get("type", "stock")

    logger.info("Analysing %s (%s) …", ticker, asset_type)

    # ── Analysis ───────────────────────────────────────────────
    try:
        result: AnalysisResult = analyze(ticker, asset_type, gemini_key)
    except Exception as exc:
        logger.error("analyze() crashed for %s: %s", ticker, exc)
        if tg_token and tg_chat:
            notify_error(tg_token, tg_chat, ticker, str(exc))
        return {"ticker": ticker, "recommendation": "ERROR", "error": str(exc)}

    if result.error:
        logger.warning("Analysis incomplete for %s: %s", ticker, result.error)
        if tg_token and tg_chat:
            notify_error(tg_token, tg_chat, ticker, result.error)
        return {"ticker": ticker, "recommendation": "AVOID", "error": result.error}

    # ── Monitor existing active thesis ─────────────────────────
    existing_thesis = active_theses_map.get(ticker)
    verdict         = "no_thesis"
    thesis_id       = None

    if existing_thesis and result.price is not None:
        verdict   = monitor_thesis(db, existing_thesis, result.price) if db else "holding"
        thesis_id = existing_thesis.get("id")

        if verdict in ("stop_hit", "target_1_hit", "target_2_hit") and tg_token and tg_chat:
            notify_thesis_update(tg_token, tg_chat, ticker, verdict, result.price)

    # ── Upsert thesis for actionable signals ───────────────────
    if db and result.recommendation != "AVOID":
        new_thesis = upsert_thesis(
            client        = db,
            ticker        = ticker,
            recommendation= result.recommendation,
            thesis_text   = result.thesis_text,
            entry_zone    = result.entry_zone,
            target_1      = result.target_1,
            target_2      = result.target_2,
            stop_loss     = result.stop_loss,
            phase_a_score = result.phase_a_score,
            phase_b_score = result.phase_b_score,
        )

        # Only send Telegram alert when a brand-new thesis is created
        if new_thesis and new_thesis.get("id") != (existing_thesis or {}).get("id"):
            thesis_id = new_thesis["id"]
            if tg_token and tg_chat and result.recommendation == "BUY":
                notify_new_thesis(
                    token          = tg_token,
                    chat_id        = tg_chat,
                    ticker         = ticker,
                    recommendation = result.recommendation,
                    trend          = result.trend,
                    price          = result.price,
                    rsi            = result.rsi,
                    vol_ratio      = result.vol_ratio,
                    phase_a_score  = result.phase_a_score,
                    phase_b_score  = result.phase_b_score,
                    entry_zone     = result.entry_zone,
                    target_1       = result.target_1,
                    target_2       = result.target_2,
                    stop_loss      = result.stop_loss,
                )
        elif new_thesis is None and result.recommendation == "AVOID":
            verdict = "broken"

    # ── Log scan ───────────────────────────────────────────────
    if db:
        raw_data = {
            "phase_a_signals": result.phase_a_signals,
            "phase_b_checks":  result.phase_b_checks,
            "recommendation":  result.recommendation,
            "trend":           result.trend,
        }
        log_scan(
            client    = db,
            ticker    = ticker,
            price     = result.price,
            rsi       = result.rsi,
            vol_ratio = result.vol_ratio,
            verdict   = verdict if verdict != "no_thesis" else result.recommendation.lower(),
            raw_data  = raw_data,
            thesis_id = thesis_id,
        )

    logger.info(
        "%s → %s | Phase A: %d/5 | Phase B: %d/6 | trend: %s",
        ticker, result.recommendation,
        result.phase_a_score, result.phase_b_score, result.trend,
    )

    return {
        "ticker":         ticker,
        "recommendation": result.recommendation,
        "price":          result.price,
        "rsi":            result.rsi,
    }


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("=== Trading Agent scan started at %s ===", datetime.now(timezone.utc).isoformat())

    # Config
    tg_token   = _optional_env("TELEGRAM_TOKEN")
    tg_chat    = _optional_env("TELEGRAM_CHAT_ID")
    gemini_key = _optional_env("GEMINI_API_KEY")

    db          = _build_supabase_client()
    crypto_only = _is_crypto_only_run()

    logger.info("Scan mode: %s", "crypto-only" if crypto_only else "all assets")

    # Watchlist
    watchlist = _load_watchlist(db)
    if not watchlist:
        logger.error("Empty watchlist — aborting.")
        return

    if crypto_only:
        watchlist = [w for w in watchlist if w.get("type") == "crypto"]
        logger.info("Crypto-only filter applied: %d tickers.", len(watchlist))

    if not watchlist:
        logger.info("No tickers in scope for this scan mode.")
        return

    # Pre-load all active theses to avoid N+1 DB queries
    active_theses: list[dict] = get_all_active_theses(db) if db else []
    active_theses_map: dict[str, dict] = {t["ticker"]: t for t in active_theses}
    logger.info("Loaded %d active theses for monitoring.", len(active_theses_map))

    # Analyse
    scan_results: list[dict] = []
    for item in watchlist:
        result = _process_ticker(
            item               = item,
            db                 = db,
            tg_token           = tg_token,
            tg_chat            = tg_chat,
            gemini_key         = gemini_key,
            active_theses_map  = active_theses_map,
        )
        scan_results.append(result)

    # Summary notification
    if tg_token and tg_chat:
        notify_scan_summary(
            token   = tg_token,
            chat_id = tg_chat,
            total   = len(scan_results),
            results = scan_results,
        )

    logger.info("=== Scan complete. %d tickers processed. ===", len(scan_results))


if __name__ == "__main__":
    main()
