#!/usr/bin/env python3
"""
=============================================================================
 ENTRY SCANNER — Technical Price Analysis for Buffett/Graham Screener
 
 Takes the top-scoring stocks from the screener and evaluates whether
 current prices represent attractive entry points using:
   - 200-week moving average (long-term value floor)
   - 52-week (1yr) moving average
   - 50-week moving average (intermediate trend)
   - Distance from 52-week high/low
   - RSI (oversold detection)
   - Price vs intrinsic value proxies (earnings yield, FCF yield)
   
 Designed to run as a second pass after screener.py, or standalone.
 
 USAGE:
   python scripts/entry_scanner.py                           # Scan top 50 from latest results
   python scripts/entry_scanner.py --top 100                 # Scan top 100
   python scripts/entry_scanner.py --ticker AAPL BHP.AX      # Scan specific tickers
   python scripts/entry_scanner.py --input data/screener_results.json
   python scripts/entry_scanner.py --ma-period 200           # Custom MA period (weeks)
   python scripts/entry_scanner.py --output data/entry_signals
=============================================================================
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# Moving average periods (in weeks)
MA_PERIODS = {
    "ma_200w": 200,   # ~3.8 years — Buffett's long-term value floor
    "ma_100w": 100,   # ~1.9 years — intermediate
    "ma_52w": 52,     # 1 year
    "ma_50w": 50,     # ~1 year (common technical level)
}

# How many years of weekly data to fetch (needs 200 weeks = ~4 years minimum)
HISTORY_YEARS = 5

# RSI period (in weeks)
RSI_PERIOD = 14


# ─────────────────────────────────────────────────────────────────────────────
# TECHNICAL ANALYSIS FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def compute_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """Compute Relative Strength Index from a price series."""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    # Use exponential smoothing after initial SMA (Wilder's method)
    for i in range(period, len(avg_gain)):
        avg_gain.iloc[i] = (avg_gain.iloc[i - 1] * (period - 1) + gain.iloc[i]) / period
        avg_loss.iloc[i] = (avg_loss.iloc[i - 1] * (period - 1) + loss.iloc[i]) / period

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_percentile_rank(prices: pd.Series, lookback: int = 260) -> float:
    """
    Where does the current price sit relative to the last N weeks?
    Returns 0-100 (0 = at the bottom, 100 = at the top).
    """
    if len(prices) < lookback:
        lookback = len(prices)
    window = prices.iloc[-lookback:]
    current = prices.iloc[-1]
    rank = (window < current).sum() / len(window) * 100
    return round(rank, 1)


def analyse_ticker(ticker: str) -> dict | None:
    """
    Fetch weekly price history and compute all entry signals for a single ticker.
    Returns a dict of signals or None if data is insufficient.
    """
    try:
        stock = yf.Ticker(ticker)

        # Fetch weekly data — need 200+ weeks
        hist = stock.history(period=f"{HISTORY_YEARS}y", interval="1wk")

        if hist is None or hist.empty or len(hist) < 52:
            logger.warning(f"{ticker}: Insufficient weekly data ({len(hist) if hist is not None else 0} weeks)")
            return None

        close = hist["Close"].dropna()

        if len(close) < 52:
            return None

        current_price = float(close.iloc[-1])
        result = {
            "ticker": ticker,
            "current_price": round(current_price, 2),
            "price_date": close.index[-1].strftime("%Y-%m-%d"),
            "weeks_of_data": len(close),
            "currency": "AUD" if ticker.endswith(".AX") else "USD",
        }

        # ── Moving Averages ──
        for ma_name, period in MA_PERIODS.items():
            if len(close) >= period:
                ma_value = float(close.rolling(window=period).mean().iloc[-1])
                distance_pct = ((current_price - ma_value) / ma_value) * 100

                result[f"{ma_name}_value"] = round(ma_value, 2)
                result[f"{ma_name}_distance_pct"] = round(distance_pct, 2)
                result[f"{ma_name}_below"] = current_price < ma_value
            else:
                result[f"{ma_name}_value"] = None
                result[f"{ma_name}_distance_pct"] = None
                result[f"{ma_name}_below"] = None

        # ── 52-Week High / Low ──
        weekly_52 = close.iloc[-52:]
        high_52w = float(weekly_52.max())
        low_52w = float(weekly_52.min())

        result["high_52w"] = round(high_52w, 2)
        result["low_52w"] = round(low_52w, 2)
        result["pct_from_52w_high"] = round(((current_price - high_52w) / high_52w) * 100, 2)
        result["pct_from_52w_low"] = round(((current_price - low_52w) / low_52w) * 100, 2)

        # Where in the 52w range? 0% = at the low, 100% = at the high
        if high_52w != low_52w:
            result["range_52w_position"] = round(
                ((current_price - low_52w) / (high_52w - low_52w)) * 100, 1
            )
        else:
            result["range_52w_position"] = 50.0

        # ── RSI (Weekly) ──
        rsi = compute_rsi(close, RSI_PERIOD)
        if not rsi.empty and pd.notna(rsi.iloc[-1]):
            result["rsi_weekly"] = round(float(rsi.iloc[-1]), 1)
        else:
            result["rsi_weekly"] = None

        # ── Percentile Rank ──
        result["percentile_5yr"] = compute_percentile_rank(close, 260)
        result["percentile_3yr"] = compute_percentile_rank(close, 156)
        result["percentile_1yr"] = compute_percentile_rank(close, 52)

        # ── Trend Assessment ──
        # Is price above or below key MAs? Stack alignment = strong trend
        ma_alignment = []
        for ma_name in ["ma_50w", "ma_100w", "ma_200w"]:
            if result.get(f"{ma_name}_below") is not None:
                ma_alignment.append(result[f"{ma_name}_below"])

        if all(ma_alignment):
            result["ma_regime"] = "below_all"       # Deep value — price below ALL MAs
        elif not any(ma_alignment):
            result["ma_regime"] = "above_all"       # Strong uptrend
        elif ma_alignment[0] and not ma_alignment[-1]:
            result["ma_regime"] = "short_term_weak"  # Below short MAs, above long
        else:
            result["ma_regime"] = "mixed"

        # ── Price Momentum (rate of change) ──
        if len(close) >= 13:
            roc_13w = ((current_price / float(close.iloc[-13])) - 1) * 100
            result["momentum_13w"] = round(roc_13w, 2)
        else:
            result["momentum_13w"] = None

        if len(close) >= 26:
            roc_26w = ((current_price / float(close.iloc[-26])) - 1) * 100
            result["momentum_26w"] = round(roc_26w, 2)
        else:
            result["momentum_26w"] = None

        # ── Volatility (weekly std dev annualised) ──
        weekly_returns = close.pct_change().dropna()
        if len(weekly_returns) >= 52:
            vol_annual = float(weekly_returns.iloc[-52:].std()) * (52 ** 0.5) * 100
            result["volatility_annual"] = round(vol_annual, 2)
        else:
            result["volatility_annual"] = None

        # ── Max Drawdown (from 52w high) ──
        running_max = weekly_52.cummax()
        drawdown = ((weekly_52 - running_max) / running_max) * 100
        result["max_drawdown_52w"] = round(float(drawdown.min()), 2)

        # ── Composite Entry Signal ──
        result["entry_signals"] = _compute_entry_signals(result)
        result["entry_score"] = _compute_entry_score(result)

        return result

    except Exception as e:
        logger.error(f"Error analysing {ticker}: {e}")
        return None


def _compute_entry_signals(r: dict) -> list[str]:
    """Generate human-readable entry signals from the analysis."""
    signals = []

    # 200-week MA signals
    if r.get("ma_200w_below"):
        dist = abs(r.get("ma_200w_distance_pct", 0))
        if dist > 20:
            signals.append(f"🔴 DEEP VALUE: {dist:.1f}% below 200-week MA — extreme dislocation")
        elif dist > 10:
            signals.append(f"🟡 VALUE: {dist:.1f}% below 200-week MA — significant discount")
        else:
            signals.append(f"🟢 Below 200-week MA by {dist:.1f}% — potential entry zone")
    elif r.get("ma_200w_distance_pct") is not None:
        dist = r["ma_200w_distance_pct"]
        if dist > 50:
            signals.append(f"⚠️ Extended: {dist:.1f}% above 200-week MA — elevated risk")
        elif dist > 25:
            signals.append(f"⚠️ Stretched: {dist:.1f}% above 200-week MA")

    # 52-week MA signals
    if r.get("ma_52w_below"):
        signals.append(f"Below 1-year MA by {abs(r.get('ma_52w_distance_pct', 0)):.1f}%")

    # 52-week range
    pos = r.get("range_52w_position", 50)
    if pos < 20:
        signals.append(f"Near 52-week low (bottom {pos:.0f}% of range)")
    elif pos > 90:
        signals.append(f"Near 52-week high (top {100-pos:.0f}% of range)")

    # RSI
    rsi = r.get("rsi_weekly")
    if rsi is not None:
        if rsi < 30:
            signals.append(f"RSI oversold ({rsi:.0f})")
        elif rsi < 40:
            signals.append(f"RSI approaching oversold ({rsi:.0f})")
        elif rsi > 70:
            signals.append(f"RSI overbought ({rsi:.0f})")

    # Drawdown
    dd = r.get("max_drawdown_52w", 0)
    if dd < -30:
        signals.append(f"Significant 52w drawdown ({dd:.1f}%)")
    elif dd < -20:
        signals.append(f"Notable 52w drawdown ({dd:.1f}%)")

    # MA regime
    regime = r.get("ma_regime")
    if regime == "below_all":
        signals.append("Price below ALL major MAs — deep value territory")
    elif regime == "short_term_weak":
        signals.append("Short-term weakness, long-term trend intact")

    return signals


def _compute_entry_score(r: dict) -> float:
    """
    Compute a composite entry attractiveness score (0-100).
    Higher = more attractive entry point.

    This is the ENTRY score, not the quality score (that's the Buffett score).
    A stock can have a high Buffett score but low entry score (great company, expensive)
    or a low Buffett score but high entry score (cheap but maybe for a reason).

    The magic is when BOTH scores are high.
    """
    score = 50.0  # Neutral baseline
    weights_applied = 0

    # ── 200-Week MA Position (heaviest weight — this is the core signal) ──
    dist_200w = r.get("ma_200w_distance_pct")
    if dist_200w is not None:
        if dist_200w < -20:
            score += 25      # Deep below 200w MA
        elif dist_200w < -10:
            score += 18
        elif dist_200w < -5:
            score += 12
        elif dist_200w < 0:
            score += 8       # Just below
        elif dist_200w < 10:
            score += 2       # Slightly above — neutral
        elif dist_200w < 25:
            score -= 5       # Moderately above
        elif dist_200w < 50:
            score -= 12      # Stretched
        else:
            score -= 20      # Very extended
        weights_applied += 1

    # ── 52-Week MA Position ──
    dist_52w = r.get("ma_52w_distance_pct")
    if dist_52w is not None:
        if dist_52w < -15:
            score += 12
        elif dist_52w < -5:
            score += 8
        elif dist_52w < 0:
            score += 4
        elif dist_52w > 20:
            score -= 8
        weights_applied += 1

    # ── 52-Week Range Position ──
    pos = r.get("range_52w_position")
    if pos is not None:
        if pos < 15:
            score += 10
        elif pos < 30:
            score += 6
        elif pos < 50:
            score += 2
        elif pos > 85:
            score -= 8
        elif pos > 70:
            score -= 4
        weights_applied += 1

    # ── RSI ──
    rsi = r.get("rsi_weekly")
    if rsi is not None:
        if rsi < 30:
            score += 10
        elif rsi < 40:
            score += 5
        elif rsi > 70:
            score -= 8
        elif rsi > 60:
            score -= 3
        weights_applied += 1

    # ── Drawdown ──
    dd = r.get("max_drawdown_52w", 0)
    if dd < -30:
        score += 8
    elif dd < -20:
        score += 4

    # ── Momentum (contrarian — negative momentum = potential entry) ──
    mom_26 = r.get("momentum_26w")
    if mom_26 is not None:
        if mom_26 < -20:
            score += 6     # Sharp decline — contrarian entry
        elif mom_26 < -10:
            score += 3
        elif mom_26 > 30:
            score -= 5     # Chasing momentum

    # ── Percentile rank ──
    pctile = r.get("percentile_3yr")
    if pctile is not None:
        if pctile < 15:
            score += 8
        elif pctile < 30:
            score += 4
        elif pctile > 85:
            score -= 6

    # Clamp to 0-100
    score = max(0, min(100, score))
    return round(score, 1)


# ─────────────────────────────────────────────────────────────────────────────
# COMBINED SCORING — Merge quality + entry timing
# ─────────────────────────────────────────────────────────────────────────────

def compute_combined_score(buffett_score: float, entry_score: float,
                           quality_weight: float = 0.6, entry_weight: float = 0.4) -> float:
    """
    The money metric: combine Buffett quality score with entry timing score.
    
    Default 60/40 weighting — quality matters more than timing, but timing
    matters a lot. Buffett himself says "wonderful company at fair price > 
    fair company at wonderful price" but he also waits for fat pitches.
    """
    return round(
        buffett_score * quality_weight + entry_score * entry_weight, 1
    )


# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT
# ─────────────────────────────────────────────────────────────────────────────

def export_entry_results(results: list[dict], screener_data: dict | None,
                         filename: str = "data/entry_signals"):
    """Export entry scanner results to JSON and a summary CSV."""

    # Merge with screener scores if available
    screener_lookup = {}
    if screener_data and "stocks" in screener_data:
        for s in screener_data["stocks"]:
            screener_lookup[s["ticker"]] = s

    output_records = []
    for r in results:
        screener = screener_lookup.get(r["ticker"], {})
        buffett_score = screener.get("buffett_score")

        record = {
            **r,
            "buffett_score": buffett_score,
            "combined_score": (
                compute_combined_score(buffett_score, r["entry_score"])
                if buffett_score is not None else None
            ),
            "sector": screener.get("sector", ""),
            "industry": screener.get("industry", ""),
            "market_cap_b": screener.get("market_cap_b"),
            "name": screener.get("name", r["ticker"]),
            # Key fundamentals for quick reference
            "pe_trailing": screener.get("pe_trailing"),
            "roe": screener.get("roe"),
            "roic": screener.get("roic"),
            "fcf_yield": screener.get("fcf_yield"),
        }
        output_records.append(record)

    # Sort by combined score (or entry score if no screener data)
    sort_key = "combined_score" if any(r.get("combined_score") for r in output_records) else "entry_score"
    output_records.sort(key=lambda x: x.get(sort_key) or 0, reverse=True)

    json_output = {
        "generated": datetime.now().isoformat(),
        "total_scanned": len(results),
        "ma_periods": MA_PERIODS,
        "quality_weight": 0.6,
        "entry_weight": 0.4,
        "stocks": output_records,
    }

    # JSON
    json_path = f"{filename}.json"
    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=str)
    logger.info(f"Entry signals exported to {json_path}")

    # CSV summary
    csv_records = []
    for r in output_records:
        csv_records.append({
            "ticker": r["ticker"],
            "name": r.get("name", ""),
            "exchange": "ASX" if r["ticker"].endswith(".AX") else "US",
            "price": r["current_price"],
            "buffett_score": r.get("buffett_score"),
            "entry_score": r["entry_score"],
            "combined_score": r.get("combined_score"),
            "ma_200w": r.get("ma_200w_value"),
            "dist_200w_%": r.get("ma_200w_distance_pct"),
            "below_200w": r.get("ma_200w_below"),
            "ma_52w": r.get("ma_52w_value"),
            "dist_52w_%": r.get("ma_52w_distance_pct"),
            "below_52w": r.get("ma_52w_below"),
            "52w_range_%": r.get("range_52w_position"),
            "rsi_weekly": r.get("rsi_weekly"),
            "drawdown_52w_%": r.get("max_drawdown_52w"),
            "volatility_%": r.get("volatility_annual"),
            "momentum_26w_%": r.get("momentum_26w"),
            "ma_regime": r.get("ma_regime"),
            "pe": r.get("pe_trailing"),
            "roe": r.get("roe"),
            "roic": r.get("roic"),
            "fcf_yield": r.get("fcf_yield"),
            "signals": " | ".join(r.get("entry_signals", [])),
        })

    df = pd.DataFrame(csv_records)
    csv_path = f"{filename}.csv"
    df.to_csv(csv_path, index=False)
    logger.info(f"CSV summary exported to {csv_path}")

    return json_path, csv_path


def print_summary(results: list[dict], screener_data: dict | None = None):
    """Print a formatted console summary."""

    screener_lookup = {}
    if screener_data and "stocks" in screener_data:
        for s in screener_data["stocks"]:
            screener_lookup[s["ticker"]] = s

    # Merge and sort
    merged = []
    for r in results:
        sc = screener_lookup.get(r["ticker"], {})
        bs = sc.get("buffett_score")
        combined = compute_combined_score(bs, r["entry_score"]) if bs else None
        merged.append({**r, "buffett_score": bs, "combined_score": combined, "name": sc.get("name", r["ticker"])})

    sort_key = "combined_score" if any(m.get("combined_score") for m in merged) else "entry_score"
    merged.sort(key=lambda x: x.get(sort_key) or 0, reverse=True)

    print("\n" + "=" * 110)
    print("  ENTRY SCANNER — Price vs Moving Average Analysis")
    print("=" * 110)

    print(f"\n{'Rank':<5} {'Ticker':<10} {'Company':<25} {'Price':>8} "
          f"{'200w MA':>8} {'Dist%':>7} {'52w MA':>8} {'Dist%':>7} "
          f"{'RSI':>5} {'Entry':>6} {'Buff.':>6} {'COMB':>6}")
    print("-" * 110)

    for i, r in enumerate(merged[:50]):
        below_200w = "▼" if r.get("ma_200w_below") else "▲" if r.get("ma_200w_below") is not None else " "
        below_52w = "▼" if r.get("ma_52w_below") else "▲" if r.get("ma_52w_below") is not None else " "

        print(
            f"{i+1:<5} "
            f"{r['ticker']:<10} "
            f"{r.get('name', '')[:23]:<25} "
            f"{r['current_price']:>8.2f} "
            f"{_f(r.get('ma_200w_value')):>8} "
            f"{below_200w}{_f(r.get('ma_200w_distance_pct'), '%'):>6} "
            f"{_f(r.get('ma_52w_value')):>8} "
            f"{below_52w}{_f(r.get('ma_52w_distance_pct'), '%'):>6} "
            f"{_f(r.get('rsi_weekly')):>5} "
            f"{r['entry_score']:>6.1f} "
            f"{_f(r.get('buffett_score')):>6} "
            f"{_f(r.get('combined_score')):>6}"
        )

    # Show stocks with strongest entry signals
    below_200w = [m for m in merged if m.get("ma_200w_below")]
    if below_200w:
        print(f"\n{'─' * 60}")
        print(f"  BELOW 200-WEEK MA ({len(below_200w)} stocks)")
        print(f"{'─' * 60}")
        for r in below_200w:
            print(f"  {r['ticker']:<10} {r.get('name', '')[:25]:<27} "
                  f"{r.get('ma_200w_distance_pct', 0):>+.1f}%  "
                  f"Entry: {r['entry_score']:.0f}  Buffett: {_f(r.get('buffett_score'))}")

    below_52w = [m for m in merged if m.get("ma_52w_below") and not m.get("ma_200w_below")]
    if below_52w:
        print(f"\n{'─' * 60}")
        print(f"  BELOW 52-WEEK MA BUT ABOVE 200-WEEK ({len(below_52w)} stocks)")
        print(f"{'─' * 60}")
        for r in below_52w:
            dist_52 = r.get('ma_52w_distance_pct')
            dist_200 = r.get('ma_200w_distance_pct')
            print(f"  {r['ticker']:<10} {r.get('name', '')[:25]:<27} "
                  f"52w: {f'{dist_52:>+.1f}%' if dist_52 is not None else '—':>8}  "
                  f"200w: {f'{dist_200:>+.1f}%' if dist_200 is not None else '—':>8}  "
                  f"Entry: {r['entry_score']:.0f}")


def _f(val, suffix=""):
    if val is None:
        return "—"
    return f"{val:.1f}{suffix}"


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def run_entry_scanner(
    input_file: str = "data/screener_results.json",
    top_n: int = 50,
    tickers: list[str] | None = None,
    output_name: str = "data/entry_signals",
):
    """Run the entry scanner on top screener results or specific tickers."""

    screener_data = None

    if tickers:
        # Scan specific tickers
        ticker_list = tickers
        logger.info(f"Scanning {len(ticker_list)} specified tickers")
    else:
        # Load screener results
        input_path = Path(input_file)
        if not input_path.exists():
            logger.error(f"Screener results not found at {input_file}")
            logger.error("Run screener.py first, or specify --ticker")
            sys.exit(1)

        with open(input_path) as f:
            screener_data = json.load(f)

        # Take top N by Buffett score
        stocks = sorted(
            screener_data.get("stocks", []),
            key=lambda s: s.get("buffett_score", 0),
            reverse=True,
        )[:top_n]

        ticker_list = [s["ticker"] for s in stocks]
        logger.info(f"Scanning top {len(ticker_list)} stocks from {input_file}")

    # ── Analyse each ticker ──
    results = []
    for i, ticker in enumerate(ticker_list):
        logger.info(f"[{i+1}/{len(ticker_list)}] Analysing {ticker}...")
        result = analyse_ticker(ticker)
        if result:
            results.append(result)

    logger.info(f"Successfully analysed {len(results)}/{len(ticker_list)} tickers")

    # ── Output ──
    print_summary(results, screener_data)
    paths = export_entry_results(results, screener_data, output_name)

    print(f"\n{'=' * 60}")
    print(f"  COMPLETE — {len(results)} stocks analysed")
    print(f"  JSON: {paths[0]}")
    print(f"  CSV:  {paths[1]}")
    print(f"{'=' * 60}\n")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Entry Scanner — Price vs Moving Average Analysis"
    )
    parser.add_argument(
        "--input", type=str, default="data/screener_results.json",
        help="Path to screener results JSON (default: data/screener_results.json)"
    )
    parser.add_argument(
        "--top", type=int, default=50,
        help="Number of top screener results to scan (default: 50)"
    )
    parser.add_argument(
        "--ticker", nargs="+", type=str, default=None,
        help="Specific tickers to scan (overrides --input)"
    )
    parser.add_argument(
        "--output", type=str, default="data/entry_signals",
        help="Output filename base (default: data/entry_signals)"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    run_entry_scanner(
        input_file=args.input,
        top_n=args.top,
        tickers=args.ticker,
        output_name=args.output,
    )
