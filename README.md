# The Oracle's Ledger

A quantitative stock screener modelled on Warren Buffett's Berkshire Hathaway trading history and Benjamin Graham's value investing principles. Screens **NYSE**, **NASDAQ**, and **ASX** stocks monthly via GitHub Actions.

## How It Works

```
┌──────────────────┐     ┌────────────────┐     ┌──────────────────┐
│  GitHub Actions   │────▶│  Python Script  │────▶│   data/*.json    │
│  (monthly cron)   │     │  (yfinance)     │     │   (committed)    │
└──────────────────┘     └────────────────┘     └────────┬─────────┘
                                                          │
                                                          ▼
                                                 ┌──────────────────┐
                                                 │  React Frontend   │
                                                 │  (GitHub Pages)   │
                                                 └──────────────────┘
```

1. **Screener** (`scripts/screener.py`) — Fetches financial data from Yahoo Finance for ~4,000+ tickers across US and Australian exchanges. Scores each stock against 17 weighted criteria.

2. **GitHub Actions** (`.github/workflows/screener.yml`) — Runs the screener on the 1st of each month (or manually). Commits the JSON results to `data/` and deploys the frontend to GitHub Pages.

3. **Frontend** (`frontend/`) — React app that loads `screener_results.json` and renders an interactive table with filtering, sorting, and per-stock criteria breakdowns.

## Scoring Model

**17 criteria across three categories:**

| Category | Criteria | Max Weight |
|---|---|---|
| **Graham Foundation** | P/E, P/B, Graham Number, Current Ratio, Debt/Equity, Earnings Stability, Dividend History | 43 |
| **Buffett Moat** | ROE, ROIC, FCF Yield, Gross Margin, Margin Trend, Capex/NI, Buybacks, Operating Margin | 60 |
| **Qualitative Proxies** | Insider Ownership, Earnings Growth CAGR | 10 |

Each criterion returns **full pass** (1.0×), **partial pass** (0.5×), **fail** (0.0×), or **no data** (excluded from score). Final score = Σ(result × weight) / Σ(available weights) × 100.

## Quick Start

### Run locally

```bash
# Install Python dependencies
pip install -r requirements.txt

# Run the full screener (2-4 hours for all exchanges)
python scripts/screener.py

# Or screen a single exchange
python scripts/screener.py --exchange ASX
python scripts/screener.py --exchange US

# Adjust minimum market cap
python scripts/screener.py --min-mcap 10  # Large caps only

# Output goes to data/screener_results.json + .xlsx + .csv
```

### View results locally

```bash
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```

The frontend will look for `screener_results.json` in the build output, or you can upload a JSON file manually through the UI.

### Trigger a manual run on GitHub

Go to **Actions** → **Monthly Buffett/Graham Screener** → **Run workflow**. You can choose the exchange and minimum market cap.

## Repo Structure

```
.
├── .github/workflows/
│   └── screener.yml          # Monthly cron + manual trigger
├── scripts/
│   └── screener.py           # Core screening engine
├── frontend/
│   ├── src/App.jsx           # React frontend
│   ├── package.json
│   └── vite.config.js
├── data/
│   ├── screener_results.json # Latest results (auto-committed)
│   ├── meta.json             # Run metadata
│   └── history/              # Archived monthly results
├── ticker_cache/             # Cached Yahoo Finance responses
├── requirements.txt
└── README.md
```

## Data Sources

- **Ticker lists**: ASX official listed companies CSV, NASDAQ screener API, Wikipedia (fallback)
- **Financial data**: Yahoo Finance via `yfinance` (free, no API key)
- **Caching**: Per-ticker 48hr cache in `ticker_cache/` to speed up reruns

## Limitations

- **Quantitative only** — The screener identifies stocks matching Buffett/Graham *quantitative* signals. Qualitative moat assessment (brand strength, switching costs, network effects, management quality) requires human judgment.
- **Yahoo Finance data quality** — Some fields may be missing or delayed. Financial sector stocks often lack Current Ratio and Gross Margin data.
- **Point-in-time snapshot** — No forward estimates beyond P/E forward. No DCF valuation.
- **No position sizing** — Buffett concentrates heavily; this screener doesn't model portfolio construction.

## License

MIT
