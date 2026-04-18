"""
test_single.py — Offline smoke test for a single ticker.

Runs the full analysis pipeline without Supabase or Telegram.
Prints a structured report to stdout.

Usage:
  python test_single.py AAPL stock
  python test_single.py BTC  crypto
  python test_single.py NVDA          # stock is the default type
"""

from __future__ import annotations

import sys
import logging

# Show analyzer logs during local testing
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def _banner(title: str) -> None:
    width = 60
    print("\n" + "─" * width)
    print(f"  {title}")
    print("─" * width)


def _fmt(label: str, value: object, width: int = 20) -> str:
    return f"  {label:<{width}} {value}"


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("Usage: python test_single.py <TICKER> [stock|crypto]")
        sys.exit(1)

    ticker     = args[0].upper()
    asset_type = args[1].lower() if len(args) > 1 else "stock"

    if asset_type not in ("stock", "crypto"):
        print(f"Unknown asset type '{asset_type}'. Use 'stock' or 'crypto'.")
        sys.exit(1)

    print(f"\nFetching data for {ticker} ({asset_type}) …")

    # Import here so path errors are obvious
    try:
        from src.analyzer import analyze
    except ModuleNotFoundError:
        # Allow running from the project root or the src/ directory
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
        from analyzer import analyze  # type: ignore

    result = analyze(ticker, asset_type, gemini_api_key=None)

    # ── Header ────────────────────────────────────────────────
    _banner(f"Analysis: {ticker} ({asset_type.upper()})")

    if result.error:
        print(f"\n  ⚠️  ERROR: {result.error}\n")
        sys.exit(1)

    # ── Price / indicators ────────────────────────────────────
    _banner("Market Data")
    print(_fmt("Price:",        f"${result.price:,.4f}" if result.price else "—"))
    print(_fmt("RSI (14):",     f"{result.rsi:.2f}"     if result.rsi   else "—"))
    print(_fmt("Volume ratio:", f"{result.vol_ratio:.2f}x" if result.vol_ratio else "—"))
    print(_fmt("Trend:",        result.trend))

    # ── Phase A ───────────────────────────────────────────────
    _banner(f"Phase A — Pre-Signal  ({result.phase_a_score}/5)")
    labels = {
        "higher_low":      "Higher Low",
        "divergence":      "Bullish Divergence",
        "reversal_candle": "Reversal Candle",
        "vsa_climax":      "VSA Selling Climax",
        "sma_curl":        "SMA Curl Up",
    }
    for key, label in labels.items():
        val = result.phase_a_signals.get(key)
        mark = "✅" if val else "❌"
        print(f"  {mark}  {label}")

    # ── Phase B ───────────────────────────────────────────────
    _banner(f"Phase B — Confluence  ({result.phase_b_score}/6)")
    checks = {
        "above_sma150": "Price > SMA150",
        "above_sma200": "Price > SMA200",
        "fibonacci":    "Fibonacci 0.5/0.618",
        "volume":       "Volume ≥ 130%",
        "gap":          "Breakaway Gap",
        "rsi_oversold": "RSI < 40",
    }
    for key, label in checks.items():
        val = result.phase_b_checks.get(key)
        mark = "✅" if val else "❌"
        print(f"  {mark}  {label}")

    # ── Recommendation ────────────────────────────────────────
    _banner("Recommendation")
    emoji = {"BUY": "🟢", "WATCH": "🟡", "DCA": "🔵", "AVOID": "🔴"}.get(
        result.recommendation, "⚪"
    )
    print(f"\n  {emoji}  {result.recommendation}\n")

    # ── Levels ────────────────────────────────────────────────
    if result.recommendation != "AVOID":
        _banner("Price Levels")
        print(_fmt("Entry zone:", f"${result.entry_zone:,.4f}" if result.entry_zone else "—"))
        print(_fmt("Target 1:",   f"${result.target_1:,.4f}"   if result.target_1   else "—"))
        print(_fmt("Target 2:",   f"${result.target_2:,.4f}"   if result.target_2   else "—"))
        print(_fmt("Stop loss:",  f"${result.stop_loss:,.4f}"  if result.stop_loss  else "—"))

    # ── Thesis text ───────────────────────────────────────────
    _banner("Thesis")
    for line in result.thesis_text.splitlines():
        print(f"  {line}")
    print()


if __name__ == "__main__":
    main()
