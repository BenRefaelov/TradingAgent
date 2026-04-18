"""
thesis_engine.py — Supabase thesis lifecycle management.

Three responsibilities:
  1. upsert_thesis()  — create or update the active thesis for a ticker.
  2. monitor_thesis() — compare current price against existing thesis levels.
  3. log_scan()       — append every scan result to scan_log (always runs).

A thesis is created only for BUY / WATCH / DCA signals.
An existing active thesis is marked "broken" when the new recommendation
drops to AVOID (technical setup invalidated without hitting the stop).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────

def _get_active_thesis(client: Any, ticker: str) -> Optional[dict]:
    """Return the single active thesis for ticker, or None."""
    try:
        resp = (
            client.table("theses")
            .select("*")
            .eq("ticker", ticker)
            .eq("status", "active")
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None
    except Exception as exc:
        logger.error("get_active_thesis(%s) failed: %s", ticker, exc)
        return None


def _update_thesis_status(client: Any, thesis_id: str, status: str) -> None:
    """Flip status on an existing thesis row."""
    try:
        client.table("theses").update({"status": status}).eq("id", thesis_id).execute()
    except Exception as exc:
        logger.error("update_thesis_status(%s → %s) failed: %s", thesis_id, status, exc)


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def upsert_thesis(
    client: Any,
    ticker: str,
    recommendation: str,
    thesis_text: str,
    entry_zone: Optional[float],
    target_1: Optional[float],
    target_2: Optional[float],
    stop_loss: Optional[float],
    phase_a_score: int,
    phase_b_score: int,
) -> Optional[dict]:
    """
    Create or update the active thesis for `ticker`.

    Rules:
      - AVOID signal + existing active thesis  → mark thesis "broken" and return None.
      - AVOID signal + no active thesis        → do nothing, return None.
      - BUY/WATCH/DCA + no active thesis       → insert new thesis row.
      - BUY/WATCH/DCA + existing active thesis → update scores/text if new scores
                                                 are strictly better on both phases.

    Returns the thesis dict (new or existing) on success, None otherwise.
    """
    existing = _get_active_thesis(client, ticker)

    # ── AVOID: possibly break existing thesis ─────────────────
    if recommendation == "AVOID":
        if existing:
            logger.info("Breaking thesis for %s (new signal: AVOID)", ticker)
            _update_thesis_status(client, existing["id"], "broken")
        return None

    # ── Actionable signal ─────────────────────────────────────
    if not existing:
        # Insert fresh thesis
        row = {
            "ticker":         ticker,
            "thesis":         thesis_text,
            "recommendation": recommendation,
            "entry_zone":     str(entry_zone)  if entry_zone  is not None else None,
            "target_1":       str(target_1)    if target_1    is not None else None,
            "target_2":       str(target_2)    if target_2    is not None else None,
            "stop_loss":      str(stop_loss)   if stop_loss   is not None else None,
            "status":         "active",
            "phase_a_score":  phase_a_score,
            "phase_b_score":  phase_b_score,
        }
        try:
            resp = client.table("theses").insert(row).execute()
            return resp.data[0] if resp.data else None
        except Exception as exc:
            logger.error("Insert thesis(%s) failed: %s", ticker, exc)
            return None

    # ── Update only if new scores are strictly better ─────────
    if (
        phase_a_score > existing["phase_a_score"]
        and phase_b_score > existing["phase_b_score"]
    ):
        updates = {
            "thesis":         thesis_text,
            "recommendation": recommendation,
            "phase_a_score":  phase_a_score,
            "phase_b_score":  phase_b_score,
        }
        # Also refresh price levels if targets improved
        if entry_zone is not None:
            updates["entry_zone"] = str(entry_zone)
        if target_1 is not None:
            updates["target_1"] = str(target_1)
        if target_2 is not None:
            updates["target_2"] = str(target_2)
        if stop_loss is not None:
            updates["stop_loss"] = str(stop_loss)

        try:
            client.table("theses").update(updates).eq("id", existing["id"]).execute()
            existing.update(updates)
        except Exception as exc:
            logger.error("Update thesis(%s) failed: %s", ticker, exc)

    return existing


def monitor_thesis(
    client: Any,
    thesis: dict,
    current_price: float,
) -> str:
    """
    Evaluate the current price against a thesis's levels.

    Verdicts (in priority order):
      stop_hit      — price ≤ stop_loss
      target_2_hit  — price ≥ target_2
      target_1_hit  — price ≥ target_1
      holding       — none of the above

    Side-effect: updates thesis status in Supabase for terminal verdicts.
    """
    def _to_float(val: Any) -> Optional[float]:
        try:
            return float(val) if val is not None else None
        except (ValueError, TypeError):
            return None

    stop    = _to_float(thesis.get("stop_loss"))
    t1      = _to_float(thesis.get("target_1"))
    t2      = _to_float(thesis.get("target_2"))
    thesis_id = thesis.get("id")

    if stop is not None and current_price <= stop:
        verdict = "stop_hit"
    elif t2 is not None and current_price >= t2:
        verdict = "target_2_hit"
    elif t1 is not None and current_price >= t1:
        verdict = "target_1_hit"
    else:
        return "holding"

    # Persist terminal verdict
    terminal = {"stop_hit", "target_2_hit"}
    if verdict in terminal and thesis_id:
        _update_thesis_status(client, thesis_id, verdict)
    elif verdict == "target_1_hit" and thesis_id:
        # target_1_hit is not terminal — thesis stays active, just update status
        _update_thesis_status(client, thesis_id, "target_1_hit")

    return verdict


def log_scan(
    client: Any,
    ticker: str,
    price: Optional[float],
    rsi: Optional[float],
    vol_ratio: Optional[float],
    verdict: str,
    raw_data: dict,
    thesis_id: Optional[str] = None,
) -> None:
    """
    Append one row to scan_log. Always called regardless of recommendation.
    Failures are logged and swallowed — scan must never abort due to logging.
    """
    row: dict[str, Any] = {
        "ticker":    ticker,
        "price":     str(round(price, 4))     if price     is not None else None,
        "rsi":       str(round(rsi, 2))        if rsi       is not None else None,
        "vol_ratio": str(round(vol_ratio, 4)) if vol_ratio is not None else None,
        "verdict":   verdict,
        "raw_data":  raw_data,
    }
    if thesis_id:
        row["thesis_id"] = thesis_id

    try:
        client.table("scan_log").insert(row).execute()
    except Exception as exc:
        logger.error("log_scan(%s) failed: %s", ticker, exc)


def get_all_active_theses(client: Any) -> list[dict]:
    """Fetch every active thesis from Supabase for monitoring."""
    try:
        resp = client.table("theses").select("*").eq("status", "active").execute()
        return resp.data or []
    except Exception as exc:
        logger.error("get_all_active_theses failed: %s", exc)
        return []
