import React, { useEffect, useState } from "react";
import { getDailyRuns, getDailyRun } from "../api";
import ScannerTable from "./ScannerTable";
import StockDetail from "./StockDetail";

export default function DailyHistory({ index, setup }) {
  const [runs, setRuns] = useState([]);
  const [day, setDay] = useState("");
  const [run, setRun] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(""); setRun(null); setRuns([]); setDay(""); setSelected(null);
    getDailyRuns(index, setup).then((items) => {
      if (cancelled) return;
      setRuns(items); setDay(items[0]?.run_date || "");
      if (!items.length) setLoading(false);
    }).catch((e) => { if (!cancelled) { setError(e.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [index, setup, refresh]);

  useEffect(() => {
    if (!day) return;
    let cancelled = false;
    setLoading(true); setError(""); setRun(null); setSelected(null);
    getDailyRun(index, setup, day).then((data) => {
      if (!cancelled) setRun(data);
    }).catch((e) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [index, setup, day]);

  return <section>
    <h1>Daily history — {index}</h1>
    <p className="status-line">One scheduled run per setup per India-calendar day. Today and the previous six days are retained. Live scans do not overwrite these results.</p>
    <div className="download-row">
      <select aria-label="Saved run date" value={day} onChange={(e) => setDay(e.target.value)} disabled={!runs.length}>
        {!runs.length && <option value="">No saved dates</option>}
        {runs.map((r) => <option key={r.run_date} value={r.run_date}>{r.run_date} · {r.setup_name}{r.complete ? "" : " · partial"}</option>)}
      </select>
      <button className="secondary" onClick={() => setRefresh((n) => n + 1)} disabled={loading}>Refresh history</button>
    </div>
    {error && <div className="error-box">{error}</div>}
    {loading && <p className="status-line" role="status">Loading saved runs…</p>}
    {!loading && !error && !runs.length && <div className="empty-state">No daily run saved yet for this index and setup. Results appear after the scheduled run completes.</div>}
    {run && <>
      <p className="status-line">Captured {new Date(run.captured_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST · {run.count}/{run.expected_count} configured symbols evaluated. All scores are included; click a stock for its saved conditions.</p>
      {!run.complete && <div className="error-box">Partial run. Missing data: {run.missing_symbols.join(", ")}</div>}
      <ScannerTable results={run.results} onSelect={setSelected} />
    </>}
    {selected && run && <StockDetail key={`${day}-${selected}`} symbol={selected} setup={setup}
      snapshotDetail={run.results.find((r) => r.symbol === selected)}
      snapshotDate={day} onClose={() => setSelected(null)} />}
  </section>;
}
