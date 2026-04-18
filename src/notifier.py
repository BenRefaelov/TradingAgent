"""
notifier.py — Telegram push notifications (no server, no polling).

All messages are sent via a direct HTTPS POST to the Telegram Bot API.
All user-facing text is in Hebrew. HTML parse_mode is used throughout.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# ──────────────────────────────────────────────────────────────
# Internal
# ──────────────────────────────────────────────────────────────

def _send_message(token: str, chat_id: str, text: str) -> None:
    """POST a single HTML message to Telegram. Raises on HTTP error."""
    url = _TELEGRAM_API.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Telegram send failed: %s", exc)
        raise


def _fmt_price(value: Optional[float], currency: str = "$") -> str:
    if value is None:
        return "—"
    return f"{currency}{value:,.2f}"


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def notify_new_thesis(
    token: str,
    chat_id: str,
    ticker: str,
    recommendation: str,
    trend: str,
    price: float,
    rsi: Optional[float],
    vol_ratio: Optional[float],
    phase_a_score: int,
    phase_b_score: int,
    entry_zone: Optional[float],
    target_1: Optional[float],
    target_2: Optional[float],
    stop_loss: Optional[float],
) -> None:
    """Full BUY/WATCH alert for a newly created thesis."""
    emoji = {"BUY": "🟢", "WATCH": "🟡", "DCA": "🔵", "AVOID": "🔴"}.get(recommendation, "⚪")
    trend_he = {"BULLISH": "שורי", "BEARISH": "דובי", "NEUTRAL": "ניטרלי"}.get(trend, trend)

    rsi_str = f"{rsi:.1f}" if rsi is not None else "—"
    vol_str = f"{vol_ratio:.1f}x" if vol_ratio is not None else "—"

    text = (
        f"{emoji} <b>{ticker} — {recommendation}</b>\n\n"
        f"מגמה: {trend_he}\n"
        f"מחיר: {_fmt_price(price)} | RSI: {rsi_str} | Vol: {vol_str}\n\n"
        f"Phase A: {phase_a_score}/5  |  Phase B: {phase_b_score}/6\n\n"
        f"כניסה:  {_fmt_price(entry_zone)}\n"
        f"יעד 1:  {_fmt_price(target_1)}\n"
        f"יעד 2:  {_fmt_price(target_2)}\n"
        f"סטופ:   {_fmt_price(stop_loss)}"
    )
    try:
        _send_message(token, chat_id, text)
    except Exception as exc:
        logger.error("notify_new_thesis failed for %s: %s", ticker, exc)


def notify_thesis_update(
    token: str,
    chat_id: str,
    ticker: str,
    verdict: str,
    current_price: float,
) -> None:
    """Short status-change alert when a thesis hits a milestone."""
    verdict_map = {
        "target_1_hit": ("🎯", f"{ticker} — יעד 1 הושג"),
        "target_2_hit": ("🏆", f"{ticker} — יעד 2 הושג"),
        "stop_hit":     ("🛑", f"{ticker} — סטופ לוס הופעל"),
        "broken":       ("⚠️", f"{ticker} — תזה נשברה"),
    }
    emoji, headline = verdict_map.get(verdict, ("ℹ️", f"{ticker} — עדכון סטטוס"))

    text = (
        f"{emoji} <b>{headline}</b>\n"
        f"מחיר נוכחי: {_fmt_price(current_price)}"
    )
    try:
        _send_message(token, chat_id, text)
    except Exception as exc:
        logger.error("notify_thesis_update failed for %s: %s", ticker, exc)


def notify_scan_summary(
    token: str,
    chat_id: str,
    total: int,
    results: list[dict],
) -> None:
    """Brief post-scan digest grouped by recommendation."""
    buys   = [r["ticker"] for r in results if r.get("recommendation") == "BUY"]
    watches = [r["ticker"] for r in results if r.get("recommendation") == "WATCH"]
    dcas   = [r["ticker"] for r in results if r.get("recommendation") == "DCA"]

    lines = [f"📊 <b>סיכום סריקה — {total} נכסים</b>\n"]

    if buys:
        lines.append(f"🟢 BUY ({len(buys)}): {', '.join(buys)}")
    if watches:
        lines.append(f"🟡 WATCH ({len(watches)}): {', '.join(watches)}")
    if dcas:
        lines.append(f"🔵 DCA ({len(dcas)}): {', '.join(dcas)}")
    if not buys and not watches and not dcas:
        lines.append("⚪ אין הזדמנויות נוספות כרגע")

    text = "\n".join(lines)
    try:
        _send_message(token, chat_id, text)
    except Exception as exc:
        logger.error("notify_scan_summary failed: %s", exc)


def notify_error(
    token: str,
    chat_id: str,
    ticker: str,
    error: str,
) -> None:
    """Best-effort error ping — never raises."""
    text = f"⚠️ <b>שגיאה בסריקת {ticker}</b>\n<code>{error[:300]}</code>"
    try:
        _send_message(token, chat_id, text)
    except Exception:
        pass  # error handler must not itself raise
