import React, { useEffect, useRef, useState } from "react";
import ScannerTable from "./components/ScannerTable.jsx";
import BestMatchTable from "./components/BestMatchTable.jsx";
import StockDetail from "./components/StockDetail.jsx";
import AboutPage from "./components/AboutPage.jsx";
import DailyHistory from "./components/DailyHistory.jsx";
import { getIndices, getSetups, runScan, runScanAll } from "./api";

export default function App() {
  const [indices, setIndices] = useState([]);
  const [setups, setSetups] = useState([]);
  const [index, setIndex] = useState("NIFTY50");
  const [setup, setSetup] = useState("setup_1");
  const [mode, setMode] = useState("single"); // "single" | "all"
  const [allDirection, setAllDirection] = useState("all"); // "all" | "bullish" | "bearish"
  const [nearMatchScore, setNearMatchScore] = useState(70);
  const [results, setResults] = useState(null);
  const [scanCount, setScanCount] = useState(null);
  const [loading, setLoading] = useState(false);
  const [scanStatus, setScanStatus] = useState("");
  const scanController = useRef(null);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [showAbout, setShowAbout] = useState(false);
  const [lookupSymbol, setLookupSymbol] = useState("");

  useEffect(() => () => scanController.current?.abort(), []);

  useEffect(() => {
    getIndices().then((d) => setIndices(d)).catch((e) => setError(e.message));
    getSetups().then((d) => {
      setSetups(d);
      if (d[0]) setSetup(d[0].id);
    }).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    setResults(null);
    setSelected(null);
    setScanCount(null);
    setScanStatus("");
  }, [index, setup, mode, allDirection, nearMatchScore]);

  async function handleScan() {
    if (scanController.current) return;
    const controller = new AbortController();
    scanController.current = controller;
    const options = { signal: controller.signal, onStatus: setScanStatus };
    setLoading(true);
    setError(null);
    setResults(null);
    try {
      if (mode === "single") {
        const data = await runScan(index, setup, true, nearMatchScore, options);
        setResults(data.results);
        setScanCount(data.count);
      } else {
        const data = await runScanAll(index, allDirection, options);
        setResults(data.results);
        setScanCount(data.count);
      }
      setScanStatus("");
    } catch (e) {
      if (e.name === "AbortError") {
        setScanStatus("Stopped waiting. You can choose another scan.");
      } else {
        setError(e.message);
        setScanStatus("");
      }
      setResults(null);
    } finally {
      scanController.current = null;
      setLoading(false);
    }
  }

  function handleLookup(e) {
    e.preventDefault();
    if (lookupSymbol.trim()) setSelected(lookupSymbol.trim().toUpperCase());
  }

  const bullishSetups = setups.filter((s) => s.direction === "bullish");
  const bearishSetups = setups.filter((s) => s.direction === "bearish");
  const setupName = setups.find((s) => s.id === setup)?.name || "Setup";

  const headerTitle = mode === "single"
    ? `${setupName} — ${index}`
    : `Best matches across all setups — ${index}${allDirection !== "all" ? ` (${allDirection} only)` : ""}`;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">N</div>
          <div className="brand-name">Setup Scanner</div>
        </div>

        <div className="field-group">
          <label className="field-label">Index universe</label>
          <select value={index} disabled={loading} onChange={(e) => setIndex(e.target.value)}>
            {indices.length === 0 && <option value="NIFTY50">NIFTY50</option>}
            {indices.map((i) => (
              <option key={i.id} value={i.id}>{i.id} ({i.symbol_count ?? "?"} stocks)</option>
            ))}
          </select>
        </div>

        <div className="field-group">
          <label className="field-label">Scan mode</label>
          <select value={mode} disabled={loading} onChange={(e) => setMode(e.target.value)}>
            <option value="single">Run one setup</option>
            <option value="all">Best matches across ALL setups</option>
            <option value="history">Daily history (7 days)</option>
          </select>
        </div>

        {mode !== "all" ? (
          <div className="field-group">
            <label className="field-label">Trading setup</label>
            <select value={setup} disabled={loading} onChange={(e) => setSetup(e.target.value)}>
              {setups.length === 0 && <option value="setup_1">Setup 1</option>}
              {bullishSetups.length > 0 && (
                <optgroup label="▲ Bullish">
                  {bullishSetups.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </optgroup>
              )}
              {bearishSetups.length > 0 && (
                <optgroup label="▼ Bearish">
                  {bearishSetups.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </optgroup>
              )}
            </select>
          </div>
        ) : (
          <div className="field-group">
            <label className="field-label">Direction filter</label>
            <select value={allDirection} disabled={loading} onChange={(e) => setAllDirection(e.target.value)}>
              <option value="all">All setups</option>
              <option value="bullish">Bullish only</option>
              <option value="bearish">Bearish only</option>
            </select>
          </div>
        )}

        {mode === "single" && (
          <div className="field-group">
            <label className="field-label">Near-match threshold</label>
            <input
              type="range" min="50" max="100" step="5"
              value={nearMatchScore}
              disabled={loading}
              onChange={(e) => setNearMatchScore(Number(e.target.value))}
            />
            <span className="slider-value">≥ {nearMatchScore}% of conditions</span>
          </div>
        )}

        {mode !== "history" && <button className="primary" onClick={handleScan} disabled={loading}>
          {loading ? "Working…" : "Run scan"}
        </button>}
        {scanStatus && <p className="status-line" role="status">{scanStatus}</p>}
        {loading && <button className="secondary" onClick={() => scanController.current?.abort()}>Stop waiting</button>}

        <form className="field-group" onSubmit={handleLookup}>
          <label className="field-label">Inspect any stock directly</label>
          <input
            type="text" placeholder="e.g. RELIANCE"
            value={lookupSymbol}
            onChange={(e) => setLookupSymbol(e.target.value)}
          />
          <button type="submit" className="secondary">View chart + conditions</button>
        </form>

        <button type="button" className="about-link" onClick={() => setShowAbout(true)}>
          What do these setups actually check?
        </button>

        <div className="sidebar-footnote">
          Public beta: identical scans may reuse results for five minutes. The server may take a minute to wake up. Index lists can use a limited fallback when NSE is unavailable.
        </div>
      </aside>

      <main className="main">
        {showAbout ? (
          <AboutPage onClose={() => setShowAbout(false)} />
        ) : mode === "history" ? (
          <DailyHistory key={`${index}-${setup}`} index={index} setup={setup} />
        ) : (
        <>
        <div className="main-header">
          <h1>{headerTitle}</h1>
        </div>
        <div className="status-line">
          {results
            ? `${results.length} result${results.length === 1 ? "" : "s"} from ${scanCount != null ? scanCount : ""} evaluated · click a stock to see the full condition breakdown and chart`
            : "Choose an index and mode on the left, then run a scan."}
        </div>

        {error && (
          <div className="error-box">
            {error}
            <div className="retry-row">
              <button className="secondary" onClick={handleScan}>Retry</button>
            </div>
          </div>
        )}

        {!error && mode === "single" && results && results.length === 0 && (
          <div className="empty-state">
            No stocks met the {nearMatchScore}% threshold in this scan — this setup may be
            strict by design. Try lowering the near-match slider, or use "Inspect any stock
            directly" on the left to see how close a specific stock came and why.
          </div>
        )}

        {!error && mode === "single" && (!results || results.length > 0) && (
          <ScannerTable results={results} onSelect={setSelected} />
        )}

        {!error && mode === "all" && (
          <BestMatchTable results={results} onSelect={setSelected} />
        )}
        </>
        )}
      </main>

      {selected && (
        <StockDetail
          symbol={selected}
          setup={mode === "single" ? setup : (results?.find((r) => r.symbol === selected)?.best_setup_id || "setup_1")}
          allSetupsForStock={mode === "all" ? results?.find((r) => r.symbol === selected)?.setups : null}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
