#!/usr/bin/env python3
"""
=============================================================================
 THE ORACLE'S LEDGER — Buffett/Graham Quantitative Stock Screener
 Screens NYSE, NASDAQ, and ASX stocks against a weighted scoring model
 derived from Warren Buffett's Berkshire Hathaway trading history
 and Benjamin Graham's value investing principles.
=============================================================================

 SETUP:
   pip install yfinance pandas openpyxl tqdm

 USAGE:
   python buffett_graham_screener.py                    # Full run, all exchanges
   python buffett_graham_screener.py --exchange ASX     # ASX only
   python buffett_graham_screener.py --exchange US      # NYSE + NASDAQ only
   python buffett_graham_screener.py --top 50           # Show top 50 results
   python buffett_graham_screener.py --min-mcap 5       # Min market cap $5B
   python buffett_graham_screener.py --refresh-tickers  # Re-download ticker lists
   python buffett_graham_screener.py --output results   # Custom output filename

 OUTPUT:
   - Console summary of top-scoring stocks
   - Excel workbook with full results, scoring breakdown, and methodology
   - CSV export for further analysis

 NOTES:
   - Uses Yahoo Finance (free, no API key needed)
   - Full run across ~4000+ tickers takes 2-4 hours due to rate limits
   - Results are cached in ticker_cache/ to speed up reruns
   - ASX tickers are appended with .AX for Yahoo Finance
=============================================================================
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

try:
    from tqdm import tqdm
except ImportError:
    # Fallback if tqdm not installed
    def tqdm(iterable, **kwargs):
        total = kwargs.get("total", None)
        desc = kwargs.get("desc", "")
        for i, item in enumerate(iterable):
            if total:
                print(f"\r{desc} {i+1}/{total}", end="", flush=True)
            yield item
        print()

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

CACHE_DIR = Path("ticker_cache")
CACHE_DIR.mkdir(exist_ok=True)

CACHE_EXPIRY_HOURS = 48  # Re-fetch data after this many hours

# Rate limiting to avoid Yahoo Finance throttling
REQUEST_DELAY = 0.4  # seconds between requests
BATCH_SIZE = 50       # pause longer every N requests
BATCH_DELAY = 5       # seconds to pause between batches

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# TICKER UNIVERSE — Getting the full list of stocks to screen
# ─────────────────────────────────────────────────────────────────────────────

def get_us_tickers(min_mcap_billions: float = 2.0) -> list[dict]:
    """
    Get NYSE + NASDAQ tickers. Uses a combination of approaches:
    1. Try to download from NASDAQ's FTP (free, comprehensive)
    2. Fall back to a curated large/mid-cap list
    
    Returns list of dicts with 'ticker', 'name', 'exchange', 'sector'
    """
    cache_file = CACHE_DIR / "us_tickers.json"
    
    if cache_file.exists():
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 168:  # Refresh weekly
            with open(cache_file) as f:
                return json.load(f)
    
    logger.info("Fetching US ticker list...")
    tickers = []
    
    # Method 1: Try NASDAQ screener API
    try:
        import requests
        
        url = "https://api.nasdaq.com/api/screener/stocks"
        params = {
            "tableonly": "true",
            "limit": 10000,
            "offset": 0,
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        data = resp.json()
        
        for row in data.get("data", {}).get("table", {}).get("rows", []):
            # Filter by market cap
            mcap_str = row.get("marketCap", "0")
            try:
                mcap = float(mcap_str.replace(",", "")) if mcap_str else 0
            except (ValueError, AttributeError):
                mcap = 0
            
            if mcap >= min_mcap_billions * 1e9:
                tickers.append({
                    "ticker": row.get("symbol", "").strip(),
                    "name": row.get("name", ""),
                    "exchange": "US",
                    "sector": row.get("sector", ""),
                })
        
        logger.info(f"Found {len(tickers)} US tickers from NASDAQ API")
    except Exception as e:
        logger.warning(f"NASDAQ API failed: {e}. Using fallback list.")
    
    # Method 2: Fallback — use a broad list from yfinance screening
    if len(tickers) < 100:
        logger.info("Using fallback ticker list approach...")
        # Get S&P 500 + additional large caps as baseline
        try:
            sp500_table = pd.read_html(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            )[0]
            for _, row in sp500_table.iterrows():
                tickers.append({
                    "ticker": row["Symbol"].replace(".", "-"),
                    "name": row.get("Security", ""),
                    "exchange": "US",
                    "sector": row.get("GICS Sector", ""),
                })
        except Exception as e:
            logger.warning(f"Wikipedia S&P 500 fetch failed: {e}")
        
        # Add Russell 1000 extras
        try:
            r1000 = pd.read_html(
                "https://en.wikipedia.org/wiki/Russell_1000_Index"
            )[2]
            existing = {t["ticker"] for t in tickers}
            for _, row in r1000.iterrows():
                sym = str(row.get("Ticker", row.get("Symbol", ""))).strip()
                if sym and sym not in existing:
                    tickers.append({
                        "ticker": sym.replace(".", "-"),
                        "name": row.get("Company", ""),
                        "exchange": "US",
                        "sector": "",
                    })
        except Exception:
            pass
        
        logger.info(f"Fallback: {len(tickers)} US tickers")
    
    # Cache results
    with open(cache_file, "w") as f:
        json.dump(tickers, f)
    
    return tickers


def get_asx_tickers(min_mcap_billions: float = 0.5) -> list[dict]:
    """
    Get the full ASX listed company universe. ASX tickers need .AX suffix
    for Yahoo Finance.
    
    Data sources (in priority order):
    1. ASX official listed companies CSV (~2,200 securities)
       URL: https://asx.com.au/asx/research/listedCompanies.do (export=csv)
    2. Yahoo Finance screener for ASX exchange
    3. Wikipedia ASX 200 + hardcoded majors as last resort
    
    Market cap filtering happens later via Yahoo Finance data, since the
    ASX CSV doesn't include market cap. We fetch all tickers here and let
    the scoring pipeline handle the min_mcap gate.
    """
    cache_file = CACHE_DIR / "asx_tickers.json"
    
    if cache_file.exists():
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 168:  # Refresh weekly
            with open(cache_file) as f:
                return json.load(f)
    
    logger.info("Fetching ASX ticker list...")
    tickers = []
    seen = set()
    
    # ── Method 1: ASX Official Listed Companies CSV ──
    # This is the authoritative source — every listed entity on the ASX.
    # The CSV has columns: "ASX code", "Company name", "Listing date",
    # "GICs industry group"
    try:
        import requests
        
        url = "https://asx.com.au/asx/research/ASXListedCompanies.csv"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        
        # The CSV has a couple of header/title rows before the actual data.
        # Read it and skip junk rows.
        from io import StringIO
        content = resp.text
        
        # Find the actual header row (contains "ASX code" or "Company name")
        lines = content.strip().split("\n")
        header_idx = 0
        for i, line in enumerate(lines):
            if "company name" in line.lower() or "asx code" in line.lower():
                header_idx = i
                break
        
        csv_data = "\n".join(lines[header_idx:])
        df = pd.read_csv(StringIO(csv_data))
        
        # Normalise column names (ASX changes these occasionally)
        df.columns = [c.strip().lower() for c in df.columns]
        
        code_col = next(
            (c for c in df.columns if "code" in c or "ticker" in c or "symbol" in c),
            df.columns[0]
        )
        name_col = next(
            (c for c in df.columns if "name" in c or "company" in c),
            df.columns[1] if len(df.columns) > 1 else None
        )
        sector_col = next(
            (c for c in df.columns if "gics" in c or "industry" in c or "sector" in c),
            None
        )
        
        for _, row in df.iterrows():
            sym = str(row[code_col]).strip().upper()
            
            # Skip invalid codes (empty, too long, non-alpha, ETFs with numbers)
            if not sym or len(sym) > 5 or not sym.replace("1", "").isalpha():
                continue
            # Skip common ETF/warrant/option suffixes
            if any(sym.endswith(s) for s in ["W", "O", "N"]) and len(sym) > 3:
                pass  # Some legit 4-letter tickers end in these, so let them through
            
            if sym not in seen:
                tickers.append({
                    "ticker": f"{sym}.AX",
                    "name": str(row[name_col]).strip() if name_col else "",
                    "exchange": "ASX",
                    "sector": str(row[sector_col]).strip() if sector_col and pd.notna(row.get(sector_col)) else "",
                })
                seen.add(sym)
        
        logger.info(f"Found {len(tickers)} ASX tickers from ASX official CSV")
        
    except Exception as e:
        logger.warning(f"ASX official CSV failed: {e}")
    
    # ── Method 2: Yahoo Finance screener for ASX ──
    # If the ASX CSV gave us a decent list, skip this.
    if len(tickers) < 200:
        try:
            import requests
            
            # Yahoo Finance screener endpoint for ASX-listed stocks
            url = "https://query2.finance.yahoo.com/v1/finance/screener"
            params = {
                "formatted": "true",
                "lang": "en-AU",
                "region": "AU",
                "count": 250,
                "offset": 0,
            }
            body = {
                "size": 250,
                "offset": 0,
                "sortField": "intradaymarketcap",
                "sortType": "DESC",
                "quoteType": "EQUITY",
                "query": {
                    "operator": "AND",
                    "operands": [
                        {"operator": "eq", "operands": ["exchange", "ASX"]},
                    ]
                }
            }
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Content-Type": "application/json",
            }
            
            # Paginate to get more results
            offset = 0
            while offset < 2500:
                body["offset"] = offset
                resp = requests.post(url, json=body, headers=headers, timeout=30)
                data = resp.json()
                quotes = (
                    data.get("finance", {})
                    .get("result", [{}])[0]
                    .get("quotes", [])
                )
                
                if not quotes:
                    break
                
                for q in quotes:
                    sym = q.get("symbol", "")
                    if sym and sym not in seen and sym.endswith(".AX"):
                        code = sym.replace(".AX", "")
                        tickers.append({
                            "ticker": sym,
                            "name": q.get("longName") or q.get("shortName", ""),
                            "exchange": "ASX",
                            "sector": q.get("sector", ""),
                        })
                        seen.add(code)
                
                offset += 250
                time.sleep(1)
            
            logger.info(f"Yahoo Finance screener added tickers, total now: {len(tickers)}")
            
        except Exception as e:
            logger.warning(f"Yahoo Finance ASX screener failed: {e}")
    
    # ── Method 3: Fallback — Wikipedia ASX 200 + hardcoded majors ──
    # Only used if both primary sources fail.
    if len(tickers) < 150:
        logger.info("Using fallback ASX ticker sources...")
        
        # Wikipedia ASX 200
        try:
            tables = pd.read_html(
                "https://en.wikipedia.org/wiki/S%26P/ASX_200"
            )
            for table in tables:
                code_col = None
                for col in table.columns:
                    if "code" in str(col).lower() or "ticker" in str(col).lower():
                        code_col = col
                        break
                if code_col is None:
                    continue
                for _, row in table.iterrows():
                    sym = str(row.get(code_col, "")).strip().upper()
                    if sym and len(sym) <= 4 and sym.isalpha() and sym not in seen:
                        name_col = next(
                            (c for c in table.columns
                             if "company" in str(c).lower() or "name" in str(c).lower()),
                            None
                        )
                        tickers.append({
                            "ticker": f"{sym}.AX",
                            "name": str(row.get(name_col, "")) if name_col else "",
                            "exchange": "ASX",
                            "sector": str(row.get("GICS industry group", row.get("Sector", ""))),
                        })
                        seen.add(sym)
            logger.info(f"Wikipedia fallback added tickers, total now: {len(tickers)}")
        except Exception as e:
            logger.warning(f"Wikipedia ASX 200 fallback also failed: {e}")
        
        # Hardcoded majors as absolute last resort
        asx_majors = [
            "BHP", "CBA", "CSL", "NAB", "WBC", "ANZ", "FMG", "WES", "WOW",
            "MQG", "TLS", "RIO", "ALL", "STO", "WDS", "JHX", "TCL", "GMG",
            "REA", "COL", "SHL", "QAN", "AGL", "ORG", "IAG", "SUN", "QBE",
            "NST", "EVN", "MIN", "S32", "CPU", "ASX", "MPL", "RHC", "COH",
            "PME", "XRO", "WTC", "TNE", "REH", "JBH", "SUL", "HVN", "DMP",
            "TWE", "A2M", "BRG", "SEK", "CAR", "EDV", "FPH", "IEL", "APA",
            "AZJ", "SCG", "GPT", "MGR", "LLC", "AMC", "ORA", "BSL", "SVW",
            "DOW", "NHF", "AUB", "BEN", "BOQ", "HUB", "NWL", "CGF",
        ]
        for sym in asx_majors:
            if sym not in seen:
                tickers.append({
                    "ticker": f"{sym}.AX",
                    "name": "",
                    "exchange": "ASX",
                    "sector": "",
                })
                seen.add(sym)
        
        logger.info(f"Hardcoded fallback added, total now: {len(tickers)}")
    
    logger.info(f"Final ASX ticker count: {len(tickers)}")
    
    with open(cache_file, "w") as f:
        json.dump(tickers, f)
    
    return tickers


# ─────────────────────────────────────────────────────────────────────────────
# DATA FETCHING — Pull financials from Yahoo Finance
# ─────────────────────────────────────────────────────────────────────────────

def fetch_stock_data(ticker: str) -> dict | None:
    """
    Fetch all required financial data for a single ticker.
    Returns a flat dict of metrics or None if data is insufficient.
    Uses caching to avoid redundant API calls.
    """
    cache_file = CACHE_DIR / f"{ticker.replace('.', '_')}.json"
    
    # Check cache
    if cache_file.exists():
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < CACHE_EXPIRY_HOURS:
            with open(cache_file) as f:
                cached = json.load(f)
                if cached.get("valid"):
                    return cached
    
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        
        # Skip if we can't get basic data
        if not info.get("marketCap"):
            return None
        
        # ── Basic Info ──
        data = {
            "ticker": ticker,
            "name": info.get("longName") or info.get("shortName", ticker),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "exchange": "ASX" if ticker.endswith(".AX") else "US",
            "currency": info.get("currency", "USD"),
            "market_cap": info.get("marketCap", 0),
            "market_cap_b": round(info.get("marketCap", 0) / 1e9, 2),
        }
        
        # ── Valuation Metrics ──
        data["pe_trailing"] = info.get("trailingPE")
        data["pe_forward"] = info.get("forwardPE")
        data["pb_ratio"] = info.get("priceToBook")
        data["ps_ratio"] = info.get("priceToSalesTrailing12Months")
        data["ev_ebitda"] = info.get("enterpriseToEbitda")
        data["peg_ratio"] = info.get("pegRatio")
        
        # Graham Number check: P/E × P/B < 22.5
        pe = data["pe_trailing"]
        pb = data["pb_ratio"]
        data["graham_number_check"] = (
            (pe * pb) if (pe and pb and pe > 0 and pb > 0) else None
        )
        
        # ── Profitability / Moat Metrics ──
        data["roe"] = _pct(info.get("returnOnEquity"))
        data["roa"] = _pct(info.get("returnOnAssets"))
        data["gross_margin"] = _pct(info.get("grossMargins"))
        data["operating_margin"] = _pct(info.get("operatingMargins"))
        data["profit_margin"] = _pct(info.get("profitMargins"))
        data["revenue_growth"] = _pct(info.get("revenueGrowth"))
        data["earnings_growth"] = _pct(info.get("earningsGrowth"))
        
        # ── Balance Sheet / Safety ──
        data["current_ratio"] = info.get("currentRatio")
        data["debt_to_equity"] = info.get("debtToEquity")
        if data["debt_to_equity"]:
            data["debt_to_equity"] = round(data["debt_to_equity"] / 100, 2)  # yfinance returns as %
        data["quick_ratio"] = info.get("quickRatio")
        data["total_debt"] = info.get("totalDebt", 0)
        data["total_cash"] = info.get("totalCash", 0)
        data["net_cash"] = (data["total_cash"] or 0) - (data["total_debt"] or 0)
        
        # ── Cash Flow / Owner Earnings ──
        data["free_cash_flow"] = info.get("freeCashflow")
        data["operating_cash_flow"] = info.get("operatingCashflow")
        
        # FCF Yield = FCF / Market Cap
        if data["free_cash_flow"] and data["market_cap"]:
            data["fcf_yield"] = round(
                (data["free_cash_flow"] / data["market_cap"]) * 100, 2
            )
        else:
            data["fcf_yield"] = None
        
        # ── Dividend Info ──
        data["dividend_yield"] = _pct(info.get("dividendYield"))
        data["payout_ratio"] = _pct(info.get("payoutRatio"))
        
        # ── Share Count Trend (buybacks proxy) ──
        data["shares_outstanding"] = info.get("sharesOutstanding")
        
        # ── Historical Analysis — requires fetching financials ──
        # Earnings history for stability check
        try:
            financials = stock.financials
            if financials is not None and not financials.empty:
                net_income_row = None
                for label in ["Net Income", "Net Income Common Stockholders"]:
                    if label in financials.index:
                        net_income_row = financials.loc[label]
                        break
                
                if net_income_row is not None:
                    eps_values = net_income_row.dropna().values
                    positive_years = sum(1 for v in eps_values if v > 0)
                    data["eps_positive_years"] = positive_years
                    data["eps_total_years"] = len(eps_values)
                    
                    # Earnings growth (oldest to newest)
                    if len(eps_values) >= 2 and eps_values[-1] != 0:
                        data["earnings_cagr"] = round(
                            ((eps_values[0] / eps_values[-1]) ** (1 / len(eps_values)) - 1) * 100, 2
                        ) if eps_values[-1] > 0 and eps_values[0] > 0 else None
                    else:
                        data["earnings_cagr"] = None
                else:
                    data["eps_positive_years"] = None
                    data["eps_total_years"] = None
                    data["earnings_cagr"] = None
                    
                # Gross margin trend from financials
                if "Gross Profit" in financials.index and "Total Revenue" in financials.index:
                    gp = financials.loc["Gross Profit"].dropna()
                    rev = financials.loc["Total Revenue"].dropna()
                    if len(gp) >= 3 and len(rev) >= 3:
                        margins = (gp / rev * 100).dropna()
                        if len(margins) >= 3:
                            recent = margins.iloc[0]
                            oldest = margins.iloc[-1]
                            diff = recent - oldest
                            data["margin_trend"] = (
                                "expanding" if diff > 2 else
                                "stable" if abs(diff) <= 2 else
                                "declining"
                            )
                            data["margin_trend_delta"] = round(diff, 2)
                        else:
                            data["margin_trend"] = None
                            data["margin_trend_delta"] = None
                    else:
                        data["margin_trend"] = None
                        data["margin_trend_delta"] = None
            else:
                data["eps_positive_years"] = None
                data["eps_total_years"] = None
                data["earnings_cagr"] = None
                data["margin_trend"] = None
                data["margin_trend_delta"] = None
                
        except Exception:
            data["eps_positive_years"] = None
            data["eps_total_years"] = None
            data["earnings_cagr"] = None
            data["margin_trend"] = None
            data["margin_trend_delta"] = None
        
        # ── ROIC Calculation ──
        # ROIC = NOPAT / Invested Capital
        # NOPAT ≈ Operating Income × (1 - tax rate)
        # Invested Capital ≈ Total Equity + Total Debt - Cash
        try:
            bs = stock.balance_sheet
            fins = stock.financials
            
            if bs is not None and fins is not None and not bs.empty and not fins.empty:
                op_income = _get_row(fins, ["Operating Income", "EBIT"])
                total_equity = _get_row(bs, ["Total Stockholder Equity", "Stockholders Equity", "Total Equity Gross Minority Interest"])
                total_debt_bs = _get_row(bs, ["Total Debt", "Long Term Debt"])
                cash = _get_row(bs, ["Cash And Cash Equivalents", "Cash"])
                
                if op_income and total_equity:
                    tax_rate = 0.25  # Approximate
                    nopat = op_income * (1 - tax_rate)
                    invested_capital = total_equity + (total_debt_bs or 0) - (cash or 0)
                    
                    if invested_capital > 0:
                        data["roic"] = round((nopat / invested_capital) * 100, 2)
                    else:
                        data["roic"] = None
                else:
                    data["roic"] = None
                    
                # Capex to Net Income ratio
                cf = stock.cashflow
                if cf is not None and not cf.empty:
                    capex = _get_row(cf, ["Capital Expenditure", "Capital Expenditures"])
                    net_inc = _get_row(fins, ["Net Income", "Net Income Common Stockholders"])
                    if capex and net_inc and net_inc > 0:
                        data["capex_to_net_income"] = round((abs(capex) / net_inc) * 100, 2)
                    else:
                        data["capex_to_net_income"] = None
                else:
                    data["capex_to_net_income"] = None
            else:
                data["roic"] = None
                data["capex_to_net_income"] = None
                
        except Exception:
            data["roic"] = None
            data["capex_to_net_income"] = None
        
        # ── Share count history (buyback detection) ──
        try:
            hist = stock.history(period="5y", interval="3mo")
            if not hist.empty and "Volume" in hist.columns:
                # Use quarterly share count from balance sheet if available
                if bs is not None and not bs.empty:
                    shares_row = None
                    for label in ["Share Issued", "Ordinary Shares Number", "Common Stock"]:
                        if label in bs.index:
                            shares_row = bs.loc[label].dropna()
                            break
                    
                    if shares_row is not None and len(shares_row) >= 2:
                        newest = shares_row.iloc[0]
                        oldest = shares_row.iloc[-1]
                        if oldest > 0:
                            change = ((newest - oldest) / oldest) * 100
                            data["shares_change_pct"] = round(change, 2)
                            data["shares_trend"] = (
                                "declining" if change < -2 else
                                "stable" if abs(change) <= 2 else
                                "increasing"
                            )
                        else:
                            data["shares_change_pct"] = None
                            data["shares_trend"] = None
                    else:
                        data["shares_change_pct"] = None
                        data["shares_trend"] = None
                else:
                    data["shares_change_pct"] = None
                    data["shares_trend"] = None
            else:
                data["shares_change_pct"] = None
                data["shares_trend"] = None
        except Exception:
            data["shares_change_pct"] = None
            data["shares_trend"] = None
        
        # ── Dividend history length ──
        try:
            divs = stock.dividends
            if divs is not None and len(divs) > 0:
                first_div = divs.index[0]
                data["dividend_years"] = max(
                    1, (datetime.now() - first_div.to_pydatetime().replace(tzinfo=None)).days // 365
                )
            else:
                data["dividend_years"] = 0
        except Exception:
            data["dividend_years"] = 0
        
        # ── Insider ownership ──
        data["insider_pct"] = _pct(info.get("heldPercentInsiders"))
        data["institution_pct"] = _pct(info.get("heldPercentInstitutions"))
        
        data["valid"] = True
        data["fetch_time"] = datetime.now().isoformat()
        
        # Cache the result
        with open(cache_file, "w") as f:
            json.dump(data, f, default=str)
        
        return data
        
    except Exception as e:
        logger.debug(f"Failed to fetch {ticker}: {e}")
        return None


def _pct(val):
    """Convert decimal ratio to percentage, handling None."""
    if val is None:
        return None
    try:
        return round(float(val) * 100, 2)
    except (ValueError, TypeError):
        return None


def _get_row(df, labels: list):
    """Get the most recent value from a DataFrame for any matching row label."""
    for label in labels:
        if label in df.index:
            vals = df.loc[label].dropna()
            if len(vals) > 0:
                return float(vals.iloc[0])
    return None


# ─────────────────────────────────────────────────────────────────────────────
# SCORING ENGINE — The Buffett/Graham composite score
# ─────────────────────────────────────────────────────────────────────────────

# Each criterion: (name, key, test_function, weight, category)
# test_function returns: 1.0 (full pass), 0.5 (partial), 0.0 (fail), or None (no data)

CRITERIA = [
    # ── Graham Foundation ──
    {
        "name": "P/E < 15 (Deep Value)",
        "key": "pe_score",
        "category": "Graham",
        "weight": 8,
        "test": lambda d: (
            1.0 if d.get("pe_trailing") and 0 < d["pe_trailing"] < 15 else
            0.5 if d.get("pe_trailing") and 0 < d["pe_trailing"] < 20 else
            0.0 if d.get("pe_trailing") and d["pe_trailing"] > 0 else None
        ),
    },
    {
        "name": "P/B < 1.5 (Asset Value)",
        "key": "pb_score",
        "category": "Graham",
        "weight": 7,
        "test": lambda d: (
            1.0 if d.get("pb_ratio") and 0 < d["pb_ratio"] < 1.5 else
            0.5 if d.get("pb_ratio") and 0 < d["pb_ratio"] < 3.0 else
            0.0 if d.get("pb_ratio") and d["pb_ratio"] > 0 else None
        ),
    },
    {
        "name": "Graham Number (P/E × P/B < 22.5)",
        "key": "graham_combined_score",
        "category": "Graham",
        "weight": 6,
        "test": lambda d: (
            1.0 if d.get("graham_number_check") and d["graham_number_check"] < 22.5 else
            0.5 if d.get("graham_number_check") and d["graham_number_check"] < 35 else
            0.0 if d.get("graham_number_check") else None
        ),
    },
    {
        "name": "Current Ratio > 2.0 (Liquidity)",
        "key": "current_ratio_score",
        "category": "Graham",
        "weight": 4,
        "test": lambda d: (
            1.0 if d.get("current_ratio") and d["current_ratio"] > 2.0 else
            0.5 if d.get("current_ratio") and d["current_ratio"] > 1.2 else
            0.0 if d.get("current_ratio") else None
        ),
    },
    {
        "name": "Low Debt (D/E < 0.5)",
        "key": "debt_score",
        "category": "Graham",
        "weight": 6,
        "test": lambda d: (
            1.0 if d.get("debt_to_equity") is not None and d["debt_to_equity"] < 0.5 else
            0.5 if d.get("debt_to_equity") is not None and d["debt_to_equity"] < 1.0 else
            0.0 if d.get("debt_to_equity") is not None else None
        ),
    },
    {
        "name": "Earnings Stability (Positive EPS)",
        "key": "eps_stability_score",
        "category": "Graham",
        "weight": 8,
        "test": lambda d: (
            1.0 if d.get("eps_positive_years") and d.get("eps_total_years") and 
                   d["eps_positive_years"] == d["eps_total_years"] else
            0.5 if d.get("eps_positive_years") and d.get("eps_total_years") and
                   d["eps_positive_years"] >= d["eps_total_years"] - 1 else
            0.0 if d.get("eps_total_years") else None
        ),
    },
    {
        "name": "Dividend History (20yr+)",
        "key": "dividend_score",
        "category": "Graham",
        "weight": 4,
        "test": lambda d: (
            1.0 if d.get("dividend_years") and d["dividend_years"] >= 20 else
            0.5 if d.get("dividend_years") and d["dividend_years"] >= 10 else
            0.0
        ),
    },
    
    # ── Buffett Moat Metrics ──
    {
        "name": "ROE > 15% (5yr proxy)",
        "key": "roe_score",
        "category": "Buffett Moat",
        "weight": 10,
        "test": lambda d: (
            1.0 if d.get("roe") and d["roe"] > 20 else
            0.5 if d.get("roe") and d["roe"] > 15 else
            0.0 if d.get("roe") else None
        ),
    },
    {
        "name": "ROIC > 12% (Capital Efficiency)",
        "key": "roic_score",
        "category": "Buffett Moat",
        "weight": 10,
        "test": lambda d: (
            1.0 if d.get("roic") and d["roic"] > 15 else
            0.5 if d.get("roic") and d["roic"] > 12 else
            0.0 if d.get("roic") else None
        ),
    },
    {
        "name": "FCF Yield > 5% (Owner Earnings)",
        "key": "fcf_score",
        "category": "Buffett Moat",
        "weight": 9,
        "test": lambda d: (
            1.0 if d.get("fcf_yield") and d["fcf_yield"] > 5 else
            0.5 if d.get("fcf_yield") and d["fcf_yield"] > 3.5 else
            0.0 if d.get("fcf_yield") else None
        ),
    },
    {
        "name": "Gross Margin > 40% (Pricing Power)",
        "key": "gross_margin_score",
        "category": "Buffett Moat",
        "weight": 7,
        "test": lambda d: (
            1.0 if d.get("gross_margin") and d["gross_margin"] > 40 else
            0.5 if d.get("gross_margin") and d["gross_margin"] > 25 else
            0.0 if d.get("gross_margin") else None
        ),
    },
    {
        "name": "Stable/Expanding Margins",
        "key": "margin_trend_score",
        "category": "Buffett Moat",
        "weight": 7,
        "test": lambda d: (
            1.0 if d.get("margin_trend") == "expanding" else
            0.5 if d.get("margin_trend") == "stable" else
            0.0 if d.get("margin_trend") == "declining" else None
        ),
    },
    {
        "name": "Low Capex/NI < 50% (Capital Light)",
        "key": "capex_score",
        "category": "Buffett Moat",
        "weight": 6,
        "test": lambda d: (
            1.0 if d.get("capex_to_net_income") and d["capex_to_net_income"] < 25 else
            0.5 if d.get("capex_to_net_income") and d["capex_to_net_income"] < 50 else
            0.0 if d.get("capex_to_net_income") else None
        ),
    },
    {
        "name": "Share Buybacks (Declining Count)",
        "key": "buyback_score",
        "category": "Buffett Moat",
        "weight": 5,
        "test": lambda d: (
            1.0 if d.get("shares_trend") == "declining" else
            0.5 if d.get("shares_trend") == "stable" else
            0.0 if d.get("shares_trend") == "increasing" else None
        ),
    },
    {
        "name": "Operating Margin > 15%",
        "key": "op_margin_score",
        "category": "Buffett Moat",
        "weight": 6,
        "test": lambda d: (
            1.0 if d.get("operating_margin") and d["operating_margin"] > 20 else
            0.5 if d.get("operating_margin") and d["operating_margin"] > 15 else
            0.0 if d.get("operating_margin") else None
        ),
    },
    
    # ── Buffett Qualitative Proxies ──
    {
        "name": "Insider Ownership > 5%",
        "key": "insider_score",
        "category": "Qualitative Proxy",
        "weight": 4,
        "test": lambda d: (
            1.0 if d.get("insider_pct") and d["insider_pct"] > 10 else
            0.5 if d.get("insider_pct") and d["insider_pct"] > 5 else
            0.0 if d.get("insider_pct") is not None else None
        ),
    },
    {
        "name": "Earnings Growth > 10% CAGR",
        "key": "growth_score",
        "category": "Qualitative Proxy",
        "weight": 6,
        "test": lambda d: (
            1.0 if d.get("earnings_cagr") and d["earnings_cagr"] > 15 else
            0.5 if d.get("earnings_cagr") and d["earnings_cagr"] > 10 else
            0.0 if d.get("earnings_cagr") is not None else None
        ),
    },
]


def score_stock(data: dict) -> dict:
    """
    Score a single stock against all criteria.
    Returns the data dict augmented with scores.
    """
    total_score = 0
    total_weight = 0
    total_possible = 0
    breakdown = {}
    
    for criterion in CRITERIA:
        result = criterion["test"](data)
        weight = criterion["weight"]
        
        if result is not None:
            total_score += result * weight
            total_weight += weight
            breakdown[criterion["key"]] = {
                "name": criterion["name"],
                "category": criterion["category"],
                "result": result,
                "weight": weight,
                "weighted_score": result * weight,
            }
        else:
            breakdown[criterion["key"]] = {
                "name": criterion["name"],
                "category": criterion["category"],
                "result": None,
                "weight": weight,
                "weighted_score": 0,
            }
        
        total_possible += weight
    
    # Percentage based on criteria where we have data
    pct = round((total_score / total_weight) * 100, 1) if total_weight > 0 else 0
    
    # Data coverage — what % of criteria had data
    data_coverage = round((total_weight / total_possible) * 100, 1) if total_possible > 0 else 0
    
    data["buffett_score"] = pct
    data["raw_score"] = round(total_score, 2)
    data["max_possible_score"] = total_weight
    data["total_possible_score"] = total_possible
    data["data_coverage"] = data_coverage
    data["score_breakdown"] = breakdown
    
    # Category sub-scores
    for cat in ["Graham", "Buffett Moat", "Qualitative Proxy"]:
        cat_score = sum(
            v["weighted_score"] for v in breakdown.values()
            if v["category"] == cat and v["result"] is not None
        )
        cat_weight = sum(
            v["weight"] for v in breakdown.values()
            if v["category"] == cat and v["result"] is not None
        )
        data[f"{cat.lower().replace(' ', '_')}_score"] = (
            round((cat_score / cat_weight) * 100, 1) if cat_weight > 0 else None
        )
    
    return data


# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT — Excel workbook with multiple sheets
# ─────────────────────────────────────────────────────────────────────────────

def export_results(results: list[dict], filename: str = "buffett_graham_screener"):
    """Export results to Excel, CSV, and JSON (for the React frontend)."""
    
    if not results:
        logger.error("No results to export!")
        return
    
    # ── Build clean results for JSON/React consumption ──
    json_records = []
    for r in results:
        breakdown = r.get("score_breakdown", {})
        criteria_results = {}
        for key, info in breakdown.items():
            criteria_results[key] = {
                "name": info["name"],
                "category": info["category"],
                "result": (
                    "pass" if info["result"] == 1.0 else
                    "partial" if info["result"] == 0.5 else
                    "fail" if info["result"] == 0.0 else
                    "no_data"
                ),
                "weight": info["weight"],
                "weighted_score": info["weighted_score"],
            }
        
        json_records.append({
            "ticker": r.get("ticker", ""),
            "name": r.get("name", ""),
            "exchange": r.get("exchange", ""),
            "sector": r.get("sector", ""),
            "industry": r.get("industry", ""),
            "currency": r.get("currency", ""),
            "market_cap_b": r.get("market_cap_b"),
            # Scores
            "buffett_score": r.get("buffett_score"),
            "data_coverage": r.get("data_coverage"),
            "graham_score": r.get("graham_score"),
            "buffett_moat_score": r.get("buffett_moat_score"),
            "qualitative_proxy_score": r.get("qualitative_proxy_score"),
            # Valuation
            "pe_trailing": r.get("pe_trailing"),
            "pe_forward": r.get("pe_forward"),
            "pb_ratio": r.get("pb_ratio"),
            "ps_ratio": r.get("ps_ratio"),
            "ev_ebitda": r.get("ev_ebitda"),
            "graham_number_check": r.get("graham_number_check"),
            "peg_ratio": r.get("peg_ratio"),
            # Profitability
            "roe": r.get("roe"),
            "roic": r.get("roic"),
            "roa": r.get("roa"),
            "gross_margin": r.get("gross_margin"),
            "operating_margin": r.get("operating_margin"),
            "profit_margin": r.get("profit_margin"),
            "margin_trend": r.get("margin_trend"),
            "margin_trend_delta": r.get("margin_trend_delta"),
            # Cash Flow
            "fcf_yield": r.get("fcf_yield"),
            "capex_to_net_income": r.get("capex_to_net_income"),
            # Balance Sheet
            "current_ratio": r.get("current_ratio"),
            "debt_to_equity": r.get("debt_to_equity"),
            # Growth
            "earnings_cagr": r.get("earnings_cagr"),
            "eps_positive_years": r.get("eps_positive_years"),
            "eps_total_years": r.get("eps_total_years"),
            "revenue_growth": r.get("revenue_growth"),
            "earnings_growth": r.get("earnings_growth"),
            # Shareholder
            "dividend_yield": r.get("dividend_yield"),
            "dividend_years": r.get("dividend_years"),
            "payout_ratio": r.get("payout_ratio"),
            "shares_trend": r.get("shares_trend"),
            "shares_change_pct": r.get("shares_change_pct"),
            # Ownership
            "insider_pct": r.get("insider_pct"),
            "institution_pct": r.get("institution_pct"),
            # Criteria breakdown
            "criteria": criteria_results,
        })
    
    # ── JSON export (for React frontend) ──
    json_output = {
        "generated": datetime.now().isoformat(),
        "total_screened": len(results),
        "criteria_count": len(CRITERIA),
        "stocks": json_records,
    }
    
    json_path = f"{filename}.json"
    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=str)
    logger.info(f"JSON exported to {json_path}")
    
    # ── Main results DataFrame ──
    main_cols = [
        "ticker", "name", "exchange", "sector", "industry",
        "market_cap_b", "currency",
        "buffett_score", "data_coverage",
        "graham_score", "buffett_moat_score", "qualitative_proxy_score",
        # Valuation
        "pe_trailing", "pe_forward", "pb_ratio", "ps_ratio", "ev_ebitda",
        "graham_number_check", "peg_ratio",
        # Profitability
        "roe", "roic", "roa",
        "gross_margin", "operating_margin", "profit_margin",
        "margin_trend", "margin_trend_delta",
        # Cash Flow
        "fcf_yield", "capex_to_net_income",
        # Balance Sheet
        "current_ratio", "debt_to_equity", "quick_ratio",
        # Growth & Stability
        "earnings_cagr", "eps_positive_years", "eps_total_years",
        "revenue_growth", "earnings_growth",
        # Shareholder
        "dividend_yield", "dividend_years", "payout_ratio",
        "shares_trend", "shares_change_pct",
        # Ownership
        "insider_pct", "institution_pct",
    ]
    
    df = pd.DataFrame(results)
    
    # Ensure all columns exist
    for col in main_cols:
        if col not in df.columns:
            df[col] = None
    
    df = df[main_cols].sort_values("buffett_score", ascending=False)
    
    # ── Score breakdown sheet ──
    breakdown_rows = []
    for r in results:
        bd = r.get("score_breakdown", {})
        for key, info in bd.items():
            breakdown_rows.append({
                "ticker": r["ticker"],
                "name": r.get("name", ""),
                "buffett_score": r.get("buffett_score", 0),
                "criterion": info["name"],
                "category": info["category"],
                "result": (
                    "PASS" if info["result"] == 1.0 else
                    "PARTIAL" if info["result"] == 0.5 else
                    "FAIL" if info["result"] == 0.0 else
                    "NO DATA"
                ),
                "weight": info["weight"],
                "weighted_score": info["weighted_score"],
            })
    
    df_breakdown = pd.DataFrame(breakdown_rows)
    
    # ── Methodology sheet ──
    method_rows = []
    for c in CRITERIA:
        method_rows.append({
            "Criterion": c["name"],
            "Category": c["category"],
            "Weight": c["weight"],
            "Full Pass": "1.0 × weight",
            "Partial Pass": "0.5 × weight",
            "Description": f"Category: {c['category']}, Weight: {c['weight']}/10",
        })
    df_method = pd.DataFrame(method_rows)
    
    # ── Write Excel ──
    excel_path = f"{filename}.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Screener Results", index=False)
        df_breakdown.to_excel(writer, sheet_name="Score Breakdown", index=False)
        df_method.to_excel(writer, sheet_name="Methodology", index=False)
        
        # Auto-adjust column widths
        for sheet_name in writer.sheets:
            ws = writer.sheets[sheet_name]
            for column_cells in ws.columns:
                max_length = max(
                    len(str(cell.value or "")) for cell in column_cells
                )
                col_letter = column_cells[0].column_letter
                ws.column_dimensions[col_letter].width = min(max_length + 2, 40)
    
    # ── Write CSV ──
    csv_path = f"{filename}.csv"
    df.to_csv(csv_path, index=False)
    
    logger.info(f"Results exported to {excel_path}, {csv_path}, and {json_path}")
    return excel_path, csv_path, json_path


# ─────────────────────────────────────────────────────────────────────────────
# MAIN — Orchestrate the full screening run
# ─────────────────────────────────────────────────────────────────────────────

def run_screener(
    exchange: str = "ALL",
    min_mcap_b: float = 2.0,
    top_n: int = 100,
    output_name: str = "buffett_graham_screener",
    refresh_tickers: bool = False,
):
    """
    Run the full Buffett/Graham screener.
    
    Args:
        exchange: "US", "ASX", or "ALL"
        min_mcap_b: Minimum market cap in billions (USD for US, AUD for ASX)
        top_n: Number of top results to display in console
        output_name: Base filename for output files
        refresh_tickers: Force re-download of ticker lists
    """
    print("\n" + "=" * 70)
    print("  THE ORACLE'S LEDGER — Buffett/Graham Stock Screener")
    print("=" * 70)
    print(f"  Exchange:   {exchange}")
    print(f"  Min MCap:   ${min_mcap_b}B")
    print(f"  Started:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70 + "\n")
    
    if refresh_tickers:
        for f in CACHE_DIR.glob("*_tickers.json"):
            f.unlink()
    
    # ── Collect tickers ──
    tickers = []
    
    if exchange in ("US", "ALL"):
        us_tickers = get_us_tickers(min_mcap_billions=min_mcap_b)
        tickers.extend(us_tickers)
        logger.info(f"US tickers: {len(us_tickers)}")
    
    if exchange in ("ASX", "ALL"):
        asx_mcap = min_mcap_b * 0.5  # Lower threshold for ASX (smaller market)
        asx_tickers = get_asx_tickers(min_mcap_billions=asx_mcap)
        tickers.extend(asx_tickers)
        logger.info(f"ASX tickers: {len(asx_tickers)}")
    
    logger.info(f"Total tickers to screen: {len(tickers)}")
    
    # ── Fetch & Score ──
    results = []
    errors = 0
    
    # Market cap thresholds (in billions)
    # ASX uses a lower bar since the market is smaller
    mcap_thresholds = {
        "US": min_mcap_b,
        "ASX": min_mcap_b * 0.5,  # e.g. $1B for ASX if $2B for US
    }
    
    for i, t in enumerate(tqdm(tickers, desc="Screening", total=len(tickers))):
        ticker_sym = t["ticker"]
        
        try:
            data = fetch_stock_data(ticker_sym)
            
            if data:
                # Apply market cap filter (essential for ASX where the ticker
                # list doesn't pre-filter by market cap)
                exch = data.get("exchange", t.get("exchange", "US"))
                mcap_min = mcap_thresholds.get(exch, min_mcap_b)
                
                if data.get("market_cap_b", 0) < mcap_min:
                    logger.debug(
                        f"Skipping {ticker_sym}: mcap ${data.get('market_cap_b', 0):.1f}B "
                        f"below ${mcap_min}B threshold"
                    )
                    continue
                
                scored = score_stock(data)
                results.append(scored)
            else:
                errors += 1
                
        except Exception as e:
            logger.debug(f"Error on {ticker_sym}: {e}")
            errors += 1
        
        # Rate limiting
        time.sleep(REQUEST_DELAY)
        if (i + 1) % BATCH_SIZE == 0:
            logger.info(f"Processed {i+1}/{len(tickers)} — pausing...")
            time.sleep(BATCH_DELAY)
    
    logger.info(f"Successfully scored {len(results)} stocks ({errors} errors)")
    
    # ── Sort & Display ──
    results.sort(key=lambda x: x.get("buffett_score", 0), reverse=True)
    
    print("\n" + "=" * 70)
    print(f"  TOP {min(top_n, len(results))} STOCKS BY BUFFETT/GRAHAM SCORE")
    print("=" * 70)
    print(f"{'Rank':<5} {'Score':<7} {'Ticker':<10} {'Name':<30} {'Exch':<5} "
          f"{'MCap($B)':<9} {'P/E':<7} {'ROE%':<7} {'ROIC%':<7} {'FCF%':<7}")
    print("-" * 100)
    
    for i, r in enumerate(results[:top_n]):
        print(
            f"{i+1:<5} "
            f"{r.get('buffett_score', 0):<7.1f} "
            f"{r['ticker']:<10} "
            f"{(r.get('name', '')[:28]):<30} "
            f"{r.get('exchange', ''):<5} "
            f"{r.get('market_cap_b', 0):<9.1f} "
            f"{_fmt(r.get('pe_trailing'), 'x'):<7} "
            f"{_fmt(r.get('roe'), '%'):<7} "
            f"{_fmt(r.get('roic'), '%'):<7} "
            f"{_fmt(r.get('fcf_yield'), '%'):<7}"
        )
    
    # ── Sector breakdown ──
    print("\n" + "-" * 50)
    print("SECTOR BREAKDOWN (Top 50)")
    print("-" * 50)
    top50 = results[:50]
    sector_counts = {}
    for r in top50:
        s = r.get("sector", "Unknown") or "Unknown"
        sector_counts[s] = sector_counts.get(s, 0) + 1
    for sector, count in sorted(sector_counts.items(), key=lambda x: -x[1]):
        bar = "█" * count
        print(f"  {sector:<30} {count:>3}  {bar}")
    
    # ── Exchange breakdown ──
    print("\n" + "-" * 50)
    print("EXCHANGE BREAKDOWN")
    print("-" * 50)
    for exch in ["US", "ASX"]:
        exch_results = [r for r in results if r.get("exchange") == exch]
        if exch_results:
            avg = sum(r.get("buffett_score", 0) for r in exch_results) / len(exch_results)
            top = exch_results[0] if exch_results else None
            print(f"  {exch}: {len(exch_results)} stocks scored, avg score: {avg:.1f}")
            if top:
                print(f"       Top pick: {top['ticker']} ({top.get('name', '')}) — {top['buffett_score']:.1f}")
    
    # ── Export ──
    paths = export_results(results, output_name)
    
    print(f"\n{'=' * 70}")
    print(f"  COMPLETE — {len(results)} stocks scored")
    if paths:
        print(f"  Excel: {paths[0]}")
        print(f"  CSV:   {paths[1]}")
    print(f"{'=' * 70}\n")
    
    return results


def _fmt(val, suffix=""):
    """Format a value for console display."""
    if val is None:
        return "—"
    return f"{val:.1f}{suffix}"


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Buffett/Graham Stock Screener for NYSE, NASDAQ, and ASX"
    )
    parser.add_argument(
        "--exchange", choices=["US", "ASX", "ALL"], default="ALL",
        help="Which exchange(s) to screen (default: ALL)"
    )
    parser.add_argument(
        "--min-mcap", type=float, default=2.0,
        help="Minimum market cap in billions USD (default: 2.0)"
    )
    parser.add_argument(
        "--top", type=int, default=100,
        help="Number of top results to display (default: 100)"
    )
    parser.add_argument(
        "--output", type=str, default="buffett_graham_screener",
        help="Output filename base (default: buffett_graham_screener)"
    )
    parser.add_argument(
        "--refresh-tickers", action="store_true",
        help="Force re-download of ticker lists"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    run_screener(
        exchange=args.exchange,
        min_mcap_b=args.min_mcap,
        top_n=args.top,
        output_name=args.output,
        refresh_tickers=args.refresh_tickers,
    )
