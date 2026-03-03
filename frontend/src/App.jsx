import { useState, useEffect, useMemo } from "react";

const SECTOR_COLORS = {
  "Technology": "#2563eb",
  "Consumer Staples": "#059669",
  "Financials": "#7c3aed",
  "Healthcare": "#dc2626",
  "Industrials": "#d97706",
  "Energy": "#78716c",
  "Consumer Discretionary": "#ec4899",
  "Communication Services": "#6366f1",
  "Real Estate": "#0891b2",
  "Materials": "#65a30d",
  "Utilities": "#a16207",
};

function getScoreColor(score) {
  if (score >= 70) return "#059669";
  if (score >= 55) return "#d97706";
  if (score >= 40) return "#ea580c";
  return "#dc2626";
}

function fmt(val, suffix = "", decimals = 1) {
  if (val === null || val === undefined) return "—";
  return `${Number(val).toFixed(decimals)}${suffix}`;
}

export default function App() {
  const [data, setData] = useState(null);
  const [entryData, setEntryData] = useState(null);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState("screener");
  const [expandedRow, setExpandedRow] = useState(null);
  const [sortBy, setSortBy] = useState("score");
  const [sortDir, setSortDir] = useState("desc");
  const [sectorFilter, setSectorFilter] = useState("All");
  const [exchangeFilter, setExchangeFilter] = useState("All");
  const [minScore, setMinScore] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [uploadMode, setUploadMode] = useState(false);

  // Load data from the JSON file (deployed alongside the app)
  useEffect(() => {
    async function loadData() {
      try {
        // Try loading from the deployed location first
        let resp = await fetch("./screener_results.json");
        if (!resp.ok) {
          // Fallback: try data/ subdirectory (local dev)
          resp = await fetch("./data/screener_results.json");
        }
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const json = await resp.json();
        setData(json);

        // Try loading metadata
        try {
          let metaResp = await fetch("./meta.json");
          if (!metaResp.ok) metaResp = await fetch("./data/meta.json");
          if (metaResp.ok) setMeta(await metaResp.json());
        } catch {}

        // Try loading entry signals
        try {
          let entryResp = await fetch("./entry_signals.json");
          if (!entryResp.ok) entryResp = await fetch("./data/entry_signals.json");
          if (entryResp.ok) setEntryData(await entryResp.json());
        } catch {}

        setLoading(false);
      } catch (e) {
        console.log("No pre-loaded data found, showing upload prompt.", e);
        setLoading(false);
        setUploadMode(true);
      }
    }
    loadData();
  }, []);

  // File upload handler (for manual use / local development)
  function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const json = JSON.parse(ev.target.result);
        setData(json);
        setUploadMode(false);
        setError(null);
      } catch (err) {
        setError("Invalid JSON file");
      }
    };
    reader.readAsText(file);
  }

  // Process and filter stocks
  const stocks = useMemo(() => {
    if (!data?.stocks) return [];

    let list = data.stocks.filter((s) => s.buffett_score !== null);

    if (sectorFilter !== "All") list = list.filter((s) => s.sector === sectorFilter);
    if (exchangeFilter !== "All") list = list.filter((s) => s.exchange === exchangeFilter);
    if (minScore > 0) list = list.filter((s) => s.buffett_score >= minScore);
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      list = list.filter(
        (s) =>
          s.ticker.toLowerCase().includes(q) ||
          s.name.toLowerCase().includes(q) ||
          (s.industry || "").toLowerCase().includes(q)
      );
    }

    list.sort((a, b) => {
      let aVal, bVal;
      switch (sortBy) {
        case "score": aVal = a.buffett_score || 0; bVal = b.buffett_score || 0; break;
        case "pe": aVal = a.pe_trailing || 999; bVal = b.pe_trailing || 999; break;
        case "fcf": aVal = a.fcf_yield || -999; bVal = b.fcf_yield || -999; break;
        case "roic": aVal = a.roic || -999; bVal = b.roic || -999; break;
        case "roe": aVal = a.roe || -999; bVal = b.roe || -999; break;
        case "mcap": aVal = a.market_cap_b || 0; bVal = b.market_cap_b || 0; break;
        case "name": return sortDir === "asc" ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
        default: aVal = a.buffett_score || 0; bVal = b.buffett_score || 0;
      }
      return sortDir === "desc" ? bVal - aVal : aVal - bVal;
    });

    return list;
  }, [data, sectorFilter, exchangeFilter, minScore, sortBy, sortDir, searchQuery]);

  const sectors = useMemo(() => {
    if (!data?.stocks) return ["All"];
    const s = new Set(data.stocks.map((s) => s.sector).filter(Boolean));
    return ["All", ...Array.from(s).sort()];
  }, [data]);

  const exchanges = useMemo(() => {
    if (!data?.stocks) return ["All"];
    const e = new Set(data.stocks.map((s) => s.exchange).filter(Boolean));
    return ["All", ...Array.from(e).sort()];
  }, [data]);

  function handleSort(key) {
    if (sortBy === key) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortBy(key);
      setSortDir(key === "pe" || key === "name" ? "asc" : "desc");
    }
  }

  function sortIndicator(key) {
    if (sortBy !== key) return "";
    return sortDir === "desc" ? " ▼" : " ▲";
  }

  // ── Sector breakdown stats ──
  const sectorStats = useMemo(() => {
    const top50 = stocks.slice(0, 50);
    const counts = {};
    top50.forEach((s) => {
      const sec = s.sector || "Unknown";
      counts[sec] = (counts[sec] || 0) + 1;
    });
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([sector, count]) => ({ sector, count }));
  }, [stocks]);

  // ── Upload / Loading states ──
  if (loading) {
    return (
      <div style={styles.loadingContainer}>
        <div style={styles.spinner} />
        <p style={styles.loadingText}>Loading screener data...</p>
      </div>
    );
  }

  if (uploadMode || !data) {
    return (
      <div style={styles.page}>
        <div style={styles.header}>
          <h1 style={styles.title}>The Oracle's Ledger</h1>
          <div style={styles.subtitle}>Buffett–Graham Quantitative Stock Screener</div>
        </div>
        <div style={styles.uploadContainer}>
          <h2 style={styles.uploadTitle}>Load Screener Results</h2>
          <p style={styles.uploadDesc}>
            No pre-loaded data found. Upload the JSON output from the screener script,
            or run the GitHub Actions workflow to generate fresh data.
          </p>
          <label style={styles.uploadBtn}>
            Upload screener_results.json
            <input
              type="file"
              accept=".json"
              onChange={handleFileUpload}
              style={{ display: "none" }}
            />
          </label>
          {error && <p style={styles.errorText}>{error}</p>}
          <div style={styles.uploadHint}>
            <code style={styles.code}>python scripts/screener.py --output data/screener_results</code>
          </div>
        </div>
      </div>
    );
  }

  // ── Main App ──
  return (
    <div style={styles.page}>
      {/* Header */}
      <div style={styles.header}>
        <h1 style={styles.title}>The Oracle's Ledger</h1>
        <div style={styles.subtitle}>Buffett–Graham Quantitative Stock Screener</div>
        {meta && (
          <div style={styles.metaBar}>
            Last run: {new Date(meta.last_run).toLocaleDateString("en-AU", { day: "numeric", month: "long", year: "numeric" })}
            {" · "}{data.total_screened} stocks scored
            {" · "}Exchanges: {meta.exchange}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div style={styles.tabBar}>
        {[
          { id: "screener", label: "Screener" },
          { id: "entry", label: "Entry Scanner" },
          { id: "sectors", label: "Sector Analysis" },
          { id: "methodology", label: "Methodology" },
        ].map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            style={{
              ...styles.tabBtn,
              ...(activeTab === t.id ? styles.tabBtnActive : {}),
            }}
          >
            {t.label}
          </button>
        ))}
        {/* Upload override */}
        <label style={styles.uploadSmall}>
          ↑ Load JSON
          <input type="file" accept=".json" onChange={handleFileUpload} style={{ display: "none" }} />
        </label>
      </div>

      <div style={styles.content}>
        {/* ══════════════ SCREENER TAB ══════════════ */}
        {activeTab === "screener" && (
          <>
            {/* Controls */}
            <div style={styles.controlsBar}>
              <div style={styles.controlGroup}>
                <span style={styles.controlLabel}>Search</span>
                <input
                  type="text"
                  placeholder="Ticker, name, or industry..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  style={{ ...styles.select, width: 220 }}
                />
              </div>
              <div style={styles.controlGroup}>
                <span style={styles.controlLabel}>Exchange</span>
                <select value={exchangeFilter} onChange={(e) => setExchangeFilter(e.target.value)} style={styles.select}>
                  {exchanges.map((ex) => <option key={ex} value={ex}>{ex}</option>)}
                </select>
              </div>
              <div style={styles.controlGroup}>
                <span style={styles.controlLabel}>Sector</span>
                <select value={sectorFilter} onChange={(e) => setSectorFilter(e.target.value)} style={styles.select}>
                  {sectors.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div style={styles.controlGroup}>
                <span style={styles.controlLabel}>Min Score: {minScore}%</span>
                <input type="range" min={0} max={80} step={5} value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} style={{ width: 100 }} />
              </div>
              <div style={{ marginLeft: "auto", ...styles.controlLabel }}>
                {stocks.length} stocks shown
              </div>
            </div>

            {/* Table */}
            <div style={styles.tableWrapper}>
              <table style={styles.table}>
                <thead>
                  <tr>
                    <th style={styles.th} onClick={() => handleSort("score")}>Score{sortIndicator("score")}</th>
                    <th style={styles.th} onClick={() => handleSort("name")}>Company{sortIndicator("name")}</th>
                    <th style={styles.th}>Exch</th>
                    <th style={styles.th}>Sector</th>
                    <th style={styles.th} onClick={() => handleSort("mcap")}>MCap ($B){sortIndicator("mcap")}</th>
                    <th style={styles.th} onClick={() => handleSort("pe")}>P/E{sortIndicator("pe")}</th>
                    <th style={styles.th} onClick={() => handleSort("roe")}>ROE{sortIndicator("roe")}</th>
                    <th style={styles.th} onClick={() => handleSort("roic")}>ROIC{sortIndicator("roic")}</th>
                    <th style={styles.th} onClick={() => handleSort("fcf")}>FCF Yld{sortIndicator("fcf")}</th>
                    <th style={styles.th}>Moat</th>
                  </tr>
                </thead>
                <tbody>
                  {stocks.map((s, idx) => {
                    const isExpanded = expandedRow === s.ticker;
                    const scoreColor = getScoreColor(s.buffett_score);
                    return [
                      <tr
                        key={s.ticker}
                        onClick={() => setExpandedRow(isExpanded ? null : s.ticker)}
                        style={{
                          ...styles.tr,
                          ...(idx % 2 === 1 ? styles.trAlt : {}),
                          ...(isExpanded ? styles.trExpanded : {}),
                          cursor: "pointer",
                        }}
                      >
                        <td style={styles.td}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <div style={styles.scoreBarBg}>
                              <div style={{ ...styles.scoreBarFill, width: `${s.buffett_score}%`, background: scoreColor }} />
                            </div>
                            <span style={{ fontWeight: 600, color: scoreColor, fontFamily: "'JetBrains Mono', monospace", fontSize: 13 }}>
                              {s.buffett_score.toFixed(1)}
                            </span>
                          </div>
                        </td>
                        <td style={{ ...styles.td, textAlign: "left" }}>
                          <span style={{ fontFamily: "'Newsreader', Georgia, serif", fontWeight: 600, fontSize: 14 }}>
                            {s.name}
                          </span>
                          <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, color: "#888", marginLeft: 6 }}>
                            {s.ticker}
                          </span>
                        </td>
                        <td style={styles.tdMono}>{s.exchange}</td>
                        <td style={{ ...styles.td, fontFamily: "'DM Sans'", fontSize: 11 }}>
                          <span style={{
                            display: "inline-block", width: 8, height: 8, borderRadius: "50%",
                            background: SECTOR_COLORS[s.sector] || "#888", marginRight: 5, verticalAlign: "middle"
                          }} />
                          {s.sector}
                        </td>
                        <td style={styles.tdMono}>{fmt(s.market_cap_b, "", 1)}</td>
                        <td style={styles.tdMono}>{fmt(s.pe_trailing, "x")}</td>
                        <td style={styles.tdMono}>{fmt(s.roe, "%")}</td>
                        <td style={styles.tdMono}>{fmt(s.roic, "%")}</td>
                        <td style={styles.tdMono}>{fmt(s.fcf_yield, "%")}</td>
                        <td style={{ ...styles.td, fontFamily: "'DM Sans'", fontSize: 11 }}>{s.margin_trend || "—"}</td>
                      </tr>,
                      isExpanded && (
                        <tr key={s.ticker + "-detail"}>
                          <td colSpan={10} style={{ padding: 0, background: "#f9f7f2" }}>
                            <div style={styles.detailContent}>
                              {/* Left: Criteria breakdown */}
                              <div>
                                <h4 style={styles.detailHeading}>Criteria Breakdown</h4>
                                {s.criteria && Object.entries(s.criteria).map(([key, c]) => (
                                  <div key={key} style={styles.checkRow}>
                                    <span style={{
                                      color: c.result === "pass" ? "#059669" : c.result === "partial" ? "#d97706" : c.result === "fail" ? "#dc2626" : "#aaa",
                                      fontFamily: "'DM Sans'", fontSize: 12,
                                    }}>
                                      {c.result === "pass" ? "✓" : c.result === "partial" ? "◐" : c.result === "fail" ? "✗" : "○"}{" "}
                                      {c.name}
                                    </span>
                                    <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, color: "#888" }}>
                                      wt: {c.weight}
                                    </span>
                                  </div>
                                ))}
                              </div>
                              {/* Right: Key metrics */}
                              <div>
                                <h4 style={styles.detailHeading}>Key Metrics</h4>
                                <div style={styles.metricsGrid}>
                                  {[
                                    ["P/E (Trailing)", fmt(s.pe_trailing, "x")],
                                    ["P/E (Forward)", fmt(s.pe_forward, "x")],
                                    ["P/B", fmt(s.pb_ratio, "x")],
                                    ["EV/EBITDA", fmt(s.ev_ebitda, "x")],
                                    ["Graham P/E×P/B", fmt(s.graham_number_check, "", 1)],
                                    ["ROE", fmt(s.roe, "%")],
                                    ["ROIC", fmt(s.roic, "%")],
                                    ["ROA", fmt(s.roa, "%")],
                                    ["Gross Margin", fmt(s.gross_margin, "%")],
                                    ["Op. Margin", fmt(s.operating_margin, "%")],
                                    ["FCF Yield", fmt(s.fcf_yield, "%")],
                                    ["Capex/NI", fmt(s.capex_to_net_income, "%")],
                                    ["Current Ratio", fmt(s.current_ratio, "x")],
                                    ["Debt/Equity", fmt(s.debt_to_equity, "x")],
                                    ["Div Yield", fmt(s.dividend_yield, "%")],
                                    ["Div Years", s.dividend_years ?? "—"],
                                    ["Share Trend", s.shares_trend || "—"],
                                    ["Insider %", fmt(s.insider_pct, "%")],
                                    ["Earnings CAGR", fmt(s.earnings_cagr, "%")],
                                    ["EPS +ve Yrs", s.eps_positive_years != null ? `${s.eps_positive_years}/${s.eps_total_years}` : "—"],
                                  ].map(([label, val], i) => (
                                    <div key={i} style={styles.metricItem}>
                                      <span style={styles.metricLabel}>{label}</span>
                                      <span style={styles.metricValue}>{val}</span>
                                    </div>
                                  ))}
                                </div>
                                <h4 style={{ ...styles.detailHeading, marginTop: 16 }}>Sub-Scores</h4>
                                <div style={{ display: "flex", gap: 16 }}>
                                  {[
                                    ["Graham", s.graham_score],
                                    ["Moat", s.buffett_moat_score],
                                    ["Qualitative", s.qualitative_proxy_score],
                                  ].map(([label, val]) => (
                                    <div key={label} style={styles.subScoreBox}>
                                      <span style={styles.subScoreLabel}>{label}</span>
                                      <span style={{ ...styles.subScoreValue, color: getScoreColor(val || 0) }}>
                                        {val != null ? val.toFixed(1) : "—"}
                                      </span>
                                    </div>
                                  ))}
                                  <div style={styles.subScoreBox}>
                                    <span style={styles.subScoreLabel}>Data Coverage</span>
                                    <span style={styles.subScoreValue}>{s.data_coverage?.toFixed(0)}%</span>
                                  </div>
                                </div>
                              </div>
                            </div>
                          </td>
                        </tr>
                      ),
                    ];
                  })}
                </tbody>
              </table>
            </div>
            <p style={styles.footnote}>
              Click any row to expand. Data sourced from Yahoo Finance. Screener runs monthly via GitHub Actions.
            </p>
          </>
        )}

        {/* ══════════════ ENTRY SCANNER TAB ══════════════ */}
        {activeTab === "entry" && (
          <EntryTab entryData={entryData} />
        )}

        {/* ══════════════ SECTOR TAB ══════════════ */}
        {activeTab === "sectors" && (
          <div>
            <h2 style={styles.sectionTitle}>Sector Distribution (Top 50 by Score)</h2>
            <div style={styles.sectorGrid}>
              {sectorStats.map(({ sector, count }) => (
                <div key={sector} style={styles.sectorRow}>
                  <span style={{ ...styles.sectorName, color: SECTOR_COLORS[sector] || "#666" }}>
                    <span style={{
                      display: "inline-block", width: 10, height: 10, borderRadius: "50%",
                      background: SECTOR_COLORS[sector] || "#888", marginRight: 8
                    }} />
                    {sector}
                  </span>
                  <div style={styles.sectorBarBg}>
                    <div style={{ ...styles.sectorBarFill, width: `${(count / 50) * 100}%`, background: SECTOR_COLORS[sector] || "#888" }} />
                  </div>
                  <span style={styles.sectorCount}>{count}</span>
                </div>
              ))}
            </div>

            <h2 style={{ ...styles.sectionTitle, marginTop: 32 }}>Exchange Breakdown</h2>
            {exchanges.filter(e => e !== "All").map(exch => {
              const exchStocks = (data?.stocks || []).filter(s => s.exchange === exch && s.buffett_score != null);
              const avg = exchStocks.length > 0 ? exchStocks.reduce((a, s) => a + s.buffett_score, 0) / exchStocks.length : 0;
              const top = [...exchStocks].sort((a, b) => b.buffett_score - a.buffett_score)[0];
              return (
                <div key={exch} style={styles.exchCard}>
                  <h3 style={styles.exchName}>{exch}</h3>
                  <p style={styles.exchStat}>{exchStocks.length} stocks · Avg score: {avg.toFixed(1)}</p>
                  {top && (
                    <p style={styles.exchTop}>
                      Top: <strong>{top.ticker}</strong> ({top.name}) — {top.buffett_score.toFixed(1)}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* ══════════════ METHODOLOGY TAB ══════════════ */}
        {activeTab === "methodology" && (
          <div>
            <h2 style={styles.sectionTitle}>Scoring Methodology</h2>
            <p style={styles.methodDesc}>
              Each stock is scored against {data?.criteria_count || 17} weighted criteria derived from
              Benjamin Graham's <em>The Intelligent Investor</em> and Warren Buffett's Berkshire
              Hathaway trading history. Criteria return full pass (1.0×), partial pass (0.5×),
              fail (0.0×), or no data (excluded). Final score = Σ(result × weight) / Σ(available weights) × 100.
            </p>

            {[
              { cat: "Graham Foundation", criteria: [
                { name: "P/E < 15", full: "P/E < 15", partial: "P/E 15–20", weight: 8 },
                { name: "P/B < 1.5", full: "P/B < 1.5", partial: "P/B 1.5–3.0", weight: 7 },
                { name: "Graham Number (P/E×P/B < 22.5)", full: "< 22.5", partial: "22.5–35", weight: 6 },
                { name: "Current Ratio > 2.0", full: "CR > 2.0", partial: "CR 1.2–2.0", weight: 4 },
                { name: "Low Debt (D/E < 0.5)", full: "D/E < 0.5", partial: "D/E 0.5–1.0", weight: 6 },
                { name: "Earnings Stability", full: "All years positive", partial: "≤1 loss year", weight: 8 },
                { name: "Dividend History", full: "20+ years", partial: "10–20 years", weight: 4 },
              ]},
              { cat: "Buffett Moat Metrics", criteria: [
                { name: "ROE > 15%", full: "ROE > 20%", partial: "ROE 15–20%", weight: 10 },
                { name: "ROIC > 12%", full: "ROIC > 15%", partial: "ROIC 12–15%", weight: 10 },
                { name: "FCF Yield > 5%", full: "> 5%", partial: "3.5–5%", weight: 9 },
                { name: "Gross Margin > 40%", full: "> 40%", partial: "25–40%", weight: 7 },
                { name: "Stable/Expanding Margins", full: "Expanding", partial: "Stable (±2%)", weight: 7 },
                { name: "Low Capex/NI", full: "< 25%", partial: "25–50%", weight: 6 },
                { name: "Share Buybacks", full: "Declining", partial: "Stable", weight: 5 },
                { name: "Operating Margin > 15%", full: "> 20%", partial: "15–20%", weight: 6 },
              ]},
              { cat: "Qualitative Proxies", criteria: [
                { name: "Insider Ownership > 5%", full: "> 10%", partial: "5–10%", weight: 4 },
                { name: "Earnings Growth CAGR", full: "> 15%", partial: "10–15%", weight: 6 },
              ]},
            ].map((group) => (
              <div key={group.cat} style={{ marginBottom: 28 }}>
                <h3 style={styles.methodCatTitle}>{group.cat}</h3>
                <div style={styles.methodTable}>
                  <div style={styles.methodHeaderRow}>
                    <span style={{ flex: 3 }}>Criterion</span>
                    <span style={{ flex: 2, textAlign: "center" }}>Full Pass (1.0×)</span>
                    <span style={{ flex: 2, textAlign: "center" }}>Partial (0.5×)</span>
                    <span style={{ flex: 1, textAlign: "center" }}>Weight</span>
                  </div>
                  {group.criteria.map((c, i) => (
                    <div key={i} style={{ ...styles.methodRow, ...(i % 2 === 1 ? { background: "#f5f3ed" } : {}) }}>
                      <span style={{ flex: 3, fontWeight: 500 }}>{c.name}</span>
                      <span style={{ flex: 2, textAlign: "center", color: "#059669", fontWeight: 600 }}>{c.full}</span>
                      <span style={{ flex: 2, textAlign: "center", color: "#d97706", fontWeight: 600 }}>{c.partial}</span>
                      <span style={{ flex: 1, textAlign: "center" }}>
                        <span style={styles.weightBadge}>{c.weight}</span>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function EntryTab({ entryData }) {
  const [entrySortBy, setEntrySortBy] = useState("combined");
  const [entryExpanded, setEntryExpanded] = useState(null);
  const [showOnlyBelow200w, setShowOnlyBelow200w] = useState(false);
  const [showOnlyBelow52w, setShowOnlyBelow52w] = useState(false);

  const entryStocks = useMemo(() => {
    if (!entryData?.stocks) return [];
    let list = [...entryData.stocks];

    if (showOnlyBelow200w) list = list.filter(s => s.ma_200w_below);
    if (showOnlyBelow52w) list = list.filter(s => s.ma_52w_below);

    list.sort((a, b) => {
      switch (entrySortBy) {
        case "combined": return (b.combined_score || 0) - (a.combined_score || 0);
        case "entry": return (b.entry_score || 0) - (a.entry_score || 0);
        case "buffett": return (b.buffett_score || 0) - (a.buffett_score || 0);
        case "dist_200w": return (a.ma_200w_distance_pct ?? 999) - (b.ma_200w_distance_pct ?? 999);
        case "dist_52w": return (a.ma_52w_distance_pct ?? 999) - (b.ma_52w_distance_pct ?? 999);
        case "rsi": return (a.rsi_weekly ?? 999) - (b.rsi_weekly ?? 999);
        default: return 0;
      }
    });

    return list;
  }, [entryData, entrySortBy, showOnlyBelow200w, showOnlyBelow52w]);

  const below200w = entryStocks.filter(s => s.ma_200w_below).length;
  const below52w = entryStocks.filter(s => s.ma_52w_below).length;

  if (!entryData) {
    return (
      <div style={{ textAlign: "center", padding: 60 }}>
        <h2 style={{ fontFamily: "'Newsreader'", fontSize: 22, marginBottom: 12 }}>No Entry Scanner Data</h2>
        <p style={{ fontFamily: "'DM Sans'", color: "#888", fontSize: 14 }}>
          Run the entry scanner to generate price analysis:<br />
          <code style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, background: "#f0ede8", padding: "3px 8px", borderRadius: 3 }}>
            python scripts/entry_scanner.py
          </code>
        </p>
      </div>
    );
  }

  function maDistBar(dist, below) {
    if (dist == null) return <span style={{ color: "#ccc" }}>—</span>;
    const absD = Math.abs(dist);
    const maxW = 80;
    const barW = Math.min(absD / 40 * maxW, maxW);
    const color = below ? "#059669" : dist > 25 ? "#dc2626" : "#d97706";

    return (
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        {below && (
          <div style={{ width: maxW, height: 6, background: "#e8e6e1", borderRadius: 3, overflow: "hidden", direction: "rtl" }}>
            <div style={{ width: barW, height: "100%", background: color, borderRadius: 3 }} />
          </div>
        )}
        <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, fontWeight: 600, color, minWidth: 52, textAlign: "right" }}>
          {dist > 0 ? "+" : ""}{dist.toFixed(1)}%
        </span>
        {!below && (
          <div style={{ width: maxW, height: 6, background: "#e8e6e1", borderRadius: 3, overflow: "hidden" }}>
            <div style={{ width: barW, height: "100%", background: color, borderRadius: 3 }} />
          </div>
        )}
      </div>
    );
  }

  return (
    <>
      {/* Summary cards */}
      <div style={{ display: "flex", gap: 16, marginBottom: 20, flexWrap: "wrap" }}>
        <div style={{ ...entryStyles.summaryCard, borderLeftColor: "#059669" }}>
          <div style={entryStyles.summaryNum}>{below200w}</div>
          <div style={entryStyles.summaryLabel}>Below 200-Week MA</div>
        </div>
        <div style={{ ...entryStyles.summaryCard, borderLeftColor: "#2563eb" }}>
          <div style={entryStyles.summaryNum}>{below52w}</div>
          <div style={entryStyles.summaryLabel}>Below 52-Week MA</div>
        </div>
        <div style={{ ...entryStyles.summaryCard, borderLeftColor: "#7c3aed" }}>
          <div style={entryStyles.summaryNum}>{entryStocks.filter(s => s.rsi_weekly && s.rsi_weekly < 40).length}</div>
          <div style={entryStyles.summaryLabel}>RSI Below 40</div>
        </div>
        <div style={{ ...entryStyles.summaryCard, borderLeftColor: "#d97706" }}>
          <div style={entryStyles.summaryNum}>{entryStocks.length}</div>
          <div style={entryStyles.summaryLabel}>Stocks Scanned</div>
        </div>
      </div>

      {/* Controls */}
      <div style={styles.controlsBar}>
        <div style={styles.controlGroup}>
          <span style={styles.controlLabel}>Sort</span>
          <select value={entrySortBy} onChange={e => setEntrySortBy(e.target.value)} style={styles.select}>
            <option value="combined">Combined Score</option>
            <option value="entry">Entry Score</option>
            <option value="buffett">Buffett Score</option>
            <option value="dist_200w">Dist. from 200w MA</option>
            <option value="dist_52w">Dist. from 52w MA</option>
            <option value="rsi">RSI (Lowest)</option>
          </select>
        </div>
        <label style={{ ...styles.controlLabel, cursor: "pointer", display: "flex", alignItems: "center", gap: 4 }}>
          <input type="checkbox" checked={showOnlyBelow200w} onChange={e => setShowOnlyBelow200w(e.target.checked)} />
          Below 200w MA only
        </label>
        <label style={{ ...styles.controlLabel, cursor: "pointer", display: "flex", alignItems: "center", gap: 4 }}>
          <input type="checkbox" checked={showOnlyBelow52w} onChange={e => setShowOnlyBelow52w(e.target.checked)} />
          Below 52w MA only
        </label>
        <div style={{ marginLeft: "auto", ...styles.controlLabel }}>{entryStocks.length} shown</div>
      </div>

      {/* Table */}
      <div style={styles.tableWrapper}>
        <table style={{ ...styles.table, minWidth: 1100 }}>
          <thead>
            <tr>
              <th style={styles.th}>Combined</th>
              <th style={styles.th}>Company</th>
              <th style={styles.th}>Price</th>
              <th style={{ ...styles.th, minWidth: 200 }}>vs 200-Week MA</th>
              <th style={{ ...styles.th, minWidth: 200 }}>vs 52-Week MA</th>
              <th style={styles.th}>52w Range</th>
              <th style={styles.th}>RSI</th>
              <th style={styles.th}>Entry</th>
              <th style={styles.th}>Buffett</th>
            </tr>
          </thead>
          <tbody>
            {entryStocks.map((s, idx) => {
              const isExp = entryExpanded === s.ticker;
              return [
                <tr
                  key={s.ticker}
                  onClick={() => setEntryExpanded(isExp ? null : s.ticker)}
                  style={{ ...styles.tr, ...(idx % 2 === 1 ? styles.trAlt : {}), cursor: "pointer" }}
                >
                  <td style={styles.td}>
                    <span style={{
                      fontFamily: "'JetBrains Mono'", fontSize: 14, fontWeight: 700,
                      color: getScoreColor(s.combined_score || s.entry_score || 0)
                    }}>
                      {s.combined_score != null ? s.combined_score.toFixed(1) : s.entry_score?.toFixed(1) || "—"}
                    </span>
                  </td>
                  <td style={{ ...styles.td, textAlign: "left" }}>
                    <span style={{ fontFamily: "'Newsreader'", fontWeight: 600, fontSize: 14 }}>{s.name || s.ticker}</span>
                    <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, color: "#888", marginLeft: 6 }}>{s.ticker}</span>
                  </td>
                  <td style={styles.tdMono}>{s.currency === "AUD" ? "A$" : "$"}{s.current_price?.toFixed(2)}</td>
                  <td style={styles.td}>{maDistBar(s.ma_200w_distance_pct, s.ma_200w_below)}</td>
                  <td style={styles.td}>{maDistBar(s.ma_52w_distance_pct, s.ma_52w_below)}</td>
                  <td style={styles.td}>
                    {s.range_52w_position != null && (
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <div style={{ width: 60, height: 8, background: "#e8e6e1", borderRadius: 4, position: "relative" }}>
                          <div style={{
                            position: "absolute", width: 6, height: 12, top: -2, borderRadius: 2,
                            background: s.range_52w_position < 30 ? "#059669" : s.range_52w_position > 80 ? "#dc2626" : "#d97706",
                            left: `${Math.min(s.range_52w_position, 97)}%`,
                          }} />
                        </div>
                        <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>{s.range_52w_position.toFixed(0)}%</span>
                      </div>
                    )}
                  </td>
                  <td style={styles.tdMono}>
                    {s.rsi_weekly != null && (
                      <span style={{
                        color: s.rsi_weekly < 30 ? "#059669" : s.rsi_weekly < 40 ? "#d97706" : s.rsi_weekly > 70 ? "#dc2626" : "#666",
                        fontWeight: s.rsi_weekly < 40 ? 700 : 400,
                      }}>
                        {s.rsi_weekly.toFixed(0)}
                      </span>
                    )}
                  </td>
                  <td style={styles.tdMono}>
                    <span style={{ color: getScoreColor(s.entry_score || 0) }}>{s.entry_score?.toFixed(0) || "—"}</span>
                  </td>
                  <td style={styles.tdMono}>
                    <span style={{ color: getScoreColor(s.buffett_score || 0) }}>{s.buffett_score?.toFixed(0) || "—"}</span>
                  </td>
                </tr>,
                isExp && (
                  <tr key={s.ticker + "-exp"}>
                    <td colSpan={9} style={{ padding: 0, background: "#f9f7f2" }}>
                      <div style={{ padding: "20px 24px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
                        <div>
                          <h4 style={styles.detailHeading}>Entry Signals</h4>
                          {(s.entry_signals || []).map((sig, i) => (
                            <div key={i} style={{ fontFamily: "'DM Sans'", fontSize: 13, padding: "4px 0", lineHeight: 1.4 }}>{sig}</div>
                          ))}
                          {(!s.entry_signals || s.entry_signals.length === 0) && (
                            <div style={{ fontFamily: "'DM Sans'", fontSize: 13, color: "#aaa" }}>No significant signals</div>
                          )}
                          <h4 style={{ ...styles.detailHeading, marginTop: 16 }}>MA Regime</h4>
                          <span style={{
                            fontFamily: "'DM Sans'", fontSize: 13, fontWeight: 600,
                            color: s.ma_regime === "below_all" ? "#059669" : s.ma_regime === "above_all" ? "#dc2626" : "#d97706",
                          }}>
                            {s.ma_regime === "below_all" ? "Below ALL MAs — Deep Value" :
                             s.ma_regime === "above_all" ? "Above ALL MAs — Strong Uptrend" :
                             s.ma_regime === "short_term_weak" ? "Short-term Weak, Long-term Intact" : "Mixed"}
                          </span>
                        </div>
                        <div>
                          <h4 style={styles.detailHeading}>Technical Detail</h4>
                          <div style={styles.metricsGrid}>
                            {[
                              ["200w MA", s.ma_200w_value != null ? `$${s.ma_200w_value.toFixed(2)}` : "—"],
                              ["Dist. 200w", fmt(s.ma_200w_distance_pct, "%")],
                              ["100w MA", s.ma_100w_value != null ? `$${s.ma_100w_value.toFixed(2)}` : "—"],
                              ["Dist. 100w", fmt(s.ma_100w_distance_pct, "%")],
                              ["52w MA", s.ma_52w_value != null ? `$${s.ma_52w_value.toFixed(2)}` : "—"],
                              ["Dist. 52w", fmt(s.ma_52w_distance_pct, "%")],
                              ["52w High", s.high_52w != null ? `$${s.high_52w.toFixed(2)}` : "—"],
                              ["52w Low", s.low_52w != null ? `$${s.low_52w.toFixed(2)}` : "—"],
                              ["From 52w High", fmt(s.pct_from_52w_high, "%")],
                              ["Weekly RSI", fmt(s.rsi_weekly, "", 0)],
                              ["13w Momentum", fmt(s.momentum_13w, "%")],
                              ["26w Momentum", fmt(s.momentum_26w, "%")],
                              ["Annual Vol.", fmt(s.volatility_annual, "%")],
                              ["Max DD (52w)", fmt(s.max_drawdown_52w, "%")],
                              ["3yr Percentile", fmt(s.percentile_3yr, "%", 0)],
                              ["1yr Percentile", fmt(s.percentile_1yr, "%", 0)],
                            ].map(([label, val], i) => (
                              <div key={i} style={styles.metricItem}>
                                <span style={styles.metricLabel}>{label}</span>
                                <span style={styles.metricValue}>{val}</span>
                              </div>
                            ))}
                          </div>
                          {s.pe_trailing && (
                            <>
                              <h4 style={{ ...styles.detailHeading, marginTop: 12 }}>Fundamentals</h4>
                              <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                                {[
                                  ["P/E", fmt(s.pe_trailing, "x")],
                                  ["ROE", fmt(s.roe, "%")],
                                  ["ROIC", fmt(s.roic, "%")],
                                  ["FCF Yield", fmt(s.fcf_yield, "%")],
                                ].map(([l, v]) => (
                                  <div key={l} style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>
                                    <span style={{ color: "#888" }}>{l}: </span><strong>{v}</strong>
                                  </div>
                                ))}
                              </div>
                            </>
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                ),
              ];
            })}
          </tbody>
        </table>
      </div>
      <p style={styles.footnote}>
        Combined Score = 60% Buffett Quality + 40% Entry Timing. Click rows for detail. Green bars = below MA (attractive).
      </p>
    </>
  );
}

const entryStyles = {
  summaryCard: {
    background: "white", border: "1px solid #e8e6e1", borderLeft: "4px solid",
    borderRadius: 8, padding: "16px 20px", minWidth: 140,
  },
  summaryNum: { fontFamily: "'JetBrains Mono'", fontSize: 28, fontWeight: 700, color: "#1a1a1a" },
  summaryLabel: { fontFamily: "'DM Sans'", fontSize: 11, color: "#888", textTransform: "uppercase", letterSpacing: 0.5, marginTop: 2 },
};

// ── Styles ──
const styles = {
  page: { fontFamily: "'Newsreader', Georgia, serif", background: "#faf9f6", minHeight: "100vh", color: "#1a1a1a" },
  header: {
    background: "linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)",
    color: "#faf9f6", padding: "36px 32px 28px", position: "relative",
    backgroundImage: "repeating-linear-gradient(90deg, transparent, transparent 80px, rgba(255,255,255,0.015) 80px, rgba(255,255,255,0.015) 81px)",
  },
  title: { fontFamily: "'Newsreader', Georgia, serif", fontWeight: 700, fontSize: 30, letterSpacing: -0.5, margin: 0 },
  subtitle: { fontFamily: "'DM Sans', sans-serif", fontSize: 12, fontWeight: 400, color: "rgba(250,249,246,0.5)", marginTop: 4, letterSpacing: 0.5, textTransform: "uppercase" },
  metaBar: { fontFamily: "'DM Sans', sans-serif", fontSize: 11, color: "rgba(250,249,246,0.4)", marginTop: 10, letterSpacing: 0.3 },

  tabBar: { display: "flex", gap: 0, background: "#1a1a2e", padding: "0 32px", alignItems: "center" },
  tabBtn: { fontFamily: "'DM Sans', sans-serif", fontSize: 13, fontWeight: 600, padding: "12px 24px", border: "none", background: "transparent", color: "rgba(250,249,246,0.45)", cursor: "pointer", borderBottom: "2px solid transparent", transition: "all 0.2s", letterSpacing: 0.3 },
  tabBtnActive: { color: "#faf9f6", borderBottomColor: "#e2b340" },
  uploadSmall: { marginLeft: "auto", fontFamily: "'DM Sans'", fontSize: 11, color: "rgba(250,249,246,0.35)", cursor: "pointer", padding: "8px 16px" },

  content: { padding: "24px 32px", maxWidth: 1500, margin: "0 auto" },

  controlsBar: { display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", marginBottom: 20, padding: "14px 20px", background: "white", border: "1px solid #e8e6e1", borderRadius: 8 },
  controlGroup: { display: "flex", alignItems: "center", gap: 8 },
  controlLabel: { fontFamily: "'DM Sans', sans-serif", fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.8, color: "#888" },
  select: { fontFamily: "'DM Sans', sans-serif", fontSize: 13, padding: "6px 10px", border: "1px solid #d4d1c9", borderRadius: 4, background: "#faf9f6", color: "#1a1a1a" },

  tableWrapper: { background: "white", border: "1px solid #e8e6e1", borderRadius: 8, overflow: "auto" },
  table: { width: "100%", borderCollapse: "collapse", minWidth: 1000 },
  th: { fontFamily: "'DM Sans', sans-serif", fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.8, color: "#888", padding: "14px 10px", textAlign: "center", borderBottom: "2px solid #e8e6e1", cursor: "pointer", userSelect: "none", whiteSpace: "nowrap" },
  tr: { borderBottom: "1px solid #f0ede8", transition: "background 0.15s" },
  trAlt: { background: "#fdfcfa" },
  trExpanded: { background: "#f5f3ed" },
  td: { fontFamily: "'DM Sans', sans-serif", fontSize: 13, padding: "11px 10px", textAlign: "center", verticalAlign: "middle" },
  tdMono: { fontFamily: "'JetBrains Mono', monospace", fontSize: 12, padding: "11px 10px", textAlign: "center", verticalAlign: "middle" },

  scoreBarBg: { width: 80, height: 7, background: "#e8e6e1", borderRadius: 4, overflow: "hidden", display: "inline-block", verticalAlign: "middle" },
  scoreBarFill: { height: "100%", borderRadius: 4, transition: "width 0.3s ease" },

  detailContent: { padding: "20px 24px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 },
  detailHeading: { fontFamily: "'DM Sans', sans-serif", fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.8, color: "#888", marginBottom: 10, marginTop: 0 },
  checkRow: { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "3px 0" },

  metricsGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 16px" },
  metricItem: { display: "flex", justifyContent: "space-between", padding: "3px 0", borderBottom: "1px solid #f0ede8" },
  metricLabel: { fontFamily: "'DM Sans'", fontSize: 11, color: "#888" },
  metricValue: { fontFamily: "'JetBrains Mono'", fontSize: 12, fontWeight: 500 },

  subScoreBox: { background: "white", border: "1px solid #e8e6e1", borderRadius: 6, padding: "8px 14px", textAlign: "center" },
  subScoreLabel: { fontFamily: "'DM Sans'", fontSize: 10, color: "#888", display: "block", textTransform: "uppercase", letterSpacing: 0.5 },
  subScoreValue: { fontFamily: "'JetBrains Mono'", fontSize: 16, fontWeight: 600, display: "block", marginTop: 2 },

  footnote: { fontFamily: "'DM Sans'", fontSize: 11, color: "#aaa", marginTop: 12, textAlign: "center" },

  // Sector tab
  sectionTitle: { fontFamily: "'Newsreader', Georgia, serif", fontSize: 22, fontWeight: 600, marginBottom: 16 },
  sectorGrid: { maxWidth: 700 },
  sectorRow: { display: "flex", alignItems: "center", gap: 12, padding: "8px 0", borderBottom: "1px solid #f0ede8" },
  sectorName: { fontFamily: "'DM Sans'", fontSize: 13, fontWeight: 600, width: 200, flexShrink: 0 },
  sectorBarBg: { flex: 1, height: 10, background: "#e8e6e1", borderRadius: 5, overflow: "hidden" },
  sectorBarFill: { height: "100%", borderRadius: 5, transition: "width 0.3s" },
  sectorCount: { fontFamily: "'JetBrains Mono'", fontSize: 13, fontWeight: 600, width: 30, textAlign: "right" },

  exchCard: { background: "white", border: "1px solid #e8e6e1", borderRadius: 8, padding: "16px 20px", marginBottom: 12, maxWidth: 500 },
  exchName: { fontFamily: "'DM Sans'", fontSize: 16, fontWeight: 700, margin: "0 0 4px" },
  exchStat: { fontFamily: "'DM Sans'", fontSize: 13, color: "#666", margin: "0 0 4px" },
  exchTop: { fontFamily: "'DM Sans'", fontSize: 12, color: "#888", margin: 0 },

  // Methodology tab
  methodDesc: { fontFamily: "'Newsreader', Georgia, serif", fontSize: 15, lineHeight: 1.6, color: "#555", marginBottom: 24, maxWidth: 800 },
  methodCatTitle: { fontFamily: "'Newsreader'", fontSize: 18, fontWeight: 600, marginBottom: 10, paddingBottom: 6, borderBottom: "2px solid #1a1a2e", display: "inline-block" },
  methodTable: { background: "white", border: "1px solid #e8e6e1", borderRadius: 8, overflow: "hidden" },
  methodHeaderRow: { display: "flex", padding: "12px 16px", background: "#1a1a2e", color: "#faf9f6", fontFamily: "'DM Sans'", fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.8 },
  methodRow: { display: "flex", padding: "10px 16px", borderBottom: "1px solid #f0ede8", fontFamily: "'DM Sans'", fontSize: 13, alignItems: "center" },
  weightBadge: { fontFamily: "'JetBrains Mono'", fontSize: 12, fontWeight: 700, background: "#1a1a2e", color: "#e2b340", padding: "2px 8px", borderRadius: 3 },

  // Upload screen
  uploadContainer: { maxWidth: 500, margin: "60px auto", textAlign: "center", padding: "40px", background: "white", border: "1px solid #e8e6e1", borderRadius: 12 },
  uploadTitle: { fontFamily: "'Newsreader'", fontSize: 24, fontWeight: 600, marginBottom: 12 },
  uploadDesc: { fontFamily: "'DM Sans'", fontSize: 14, color: "#666", lineHeight: 1.6, marginBottom: 24 },
  uploadBtn: { display: "inline-block", fontFamily: "'DM Sans'", fontSize: 14, fontWeight: 600, background: "#1a1a2e", color: "#faf9f6", padding: "12px 28px", borderRadius: 6, cursor: "pointer" },
  uploadHint: { marginTop: 20, fontFamily: "'DM Sans'", fontSize: 12, color: "#aaa" },
  code: { fontFamily: "'JetBrains Mono'", fontSize: 11, background: "#f0ede8", padding: "4px 8px", borderRadius: 3 },
  errorText: { fontFamily: "'DM Sans'", fontSize: 13, color: "#dc2626", marginTop: 12 },

  // Loading
  loadingContainer: { display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100vh", background: "#faf9f6" },
  spinner: { width: 40, height: 40, border: "3px solid #e8e6e1", borderTopColor: "#1a1a2e", borderRadius: "50%", animation: "spin 0.8s linear infinite" },
  loadingText: { fontFamily: "'DM Sans'", fontSize: 14, color: "#888", marginTop: 16 },
};
