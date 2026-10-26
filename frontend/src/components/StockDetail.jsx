import React, { useEffect, useRef, useState } from "react";
import { createChart } from "lightweight-charts";
import { getStockDetail, getStockHistory, downloadUrl } from "../api";

const TF_LABELS = { monthly: "Monthly", weekly: "Weekly", daily: "Daily" };
const EMA_COLORS = { 5: "#7AA2F7", 13: "#E08860", 26: "#C792EA", 50: "#5FB98A", 200: "#E37568" };

export default function StockDetail({ symbol, setup, allSetupsForStock, scanDetail, snapshotDetail, snapshotDate, onClose }) {
  // allSetupsForStock (only present when opened from "Best matches across
  // all setups"): the full breakdown for EVERY setup this stock was
  // evaluated against, already fetched by the scan-all call. Letting the
  // person switch between them here - rather than only ever showing
  // whichever setup happened to score best - is what surfaces a setup's
  // Monthly section (e.g. Setup 1) even when the "best" match for that
  // stock was a Weekly/Daily-only setup with no Monthly component at all.
  const hasMultipleSetups = Array.isArray(allSetupsForStock) && allSetupsForStock.length > 0;
  const [activeSetupId, setActiveSetupId] = useState(setup);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [chartError, setChartError] = useState(null);
  const chartRef = useRef(null);
  const chartInstance = useRef(null);

  useEffect(() => {
    setActiveSetupId(setup);
  }, [symbol, setup]);

  useEffect(() => {
    setDetail(null);
    setError(null);

    if (snapshotDetail) {
      setDetail(snapshotDetail);
      return;
    }
    if (scanDetail) {
      setDetail(scanDetail);
      return;
    }

    if (hasMultipleSetups) {
      // Already have every setup's breakdown client-side from the
      // scan-all response - no extra fetch, and guaranteed to match
      // exactly what the list showed (same data, not a re-fetch).
      const found = allSetupsForStock.find((s) => s.setup_id === activeSetupId);
      if (found) setDetail(found);
      else setError(`No data for setup ${activeSetupId}`);
      return;
    }

    getStockDetail(symbol, activeSetupId).then(setDetail).catch((e) => setError(e.message));
  }, [symbol, activeSetupId, hasMultipleSetups, allSetupsForStock, scanDetail, snapshotDetail]);

  useEffect(() => {
    if (!chartRef.current || chartInstance.current) return;
    chartInstance.current = createChart(chartRef.current, {
      layout: { background: { color: "transparent" }, textColor: "#9C988C" },
      grid: { vertLines: { color: "#2C2B27" }, horzLines: { color: "#2C2B27" } },
      width: chartRef.current.clientWidth,
      height: 480,
      timeScale: { borderColor: "#3A3934" },
      rightPriceScale: { borderColor: "#3A3934" },
    });

    const resizeObserver = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      chartInstance.current?.applyOptions({ width, height });
    });
    resizeObserver.observe(chartRef.current);

    return () => {
      resizeObserver.disconnect();
      chartInstance.current?.remove();
      chartInstance.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chartInstance.current) return;
    setChartError(null);
    getStockHistory(symbol, "daily")
      .then((hist) => {
        const chart = chartInstance.current;
        const candleSeries = chart.addCandlestickSeries({
          upColor: "#5FB98A",
          downColor: "#E37568",
          borderVisible: false,
          wickUpColor: "#5FB98A",
          wickDownColor: "#E37568",
        });
        candleSeries.setData(hist.candles);

        Object.entries(hist.ema || {}).forEach(([period, series]) => {
          if (!series.length) return;
          const line = chart.addLineSeries({
            color: EMA_COLORS[period] || "#888",
            lineWidth: 1,
            title: `EMA${period}`,
          });
          line.setData(series);
        });

        chart.timeScale().fitContent();
      })
      .catch((e) => setChartError(e.message));
  }, [symbol]);

  return (
    <div className="detail-overlay" onClick={onClose}>
      <div className="detail-panel" onClick={(e) => e.stopPropagation()}>
        <div className="detail-panel-header">
          <div>
            <h2>{symbol}</h2>
            {detail && (
              <span className={`status-pill ${detail.qualified ? "match" : "partial"}`}>
                {detail.qualified ? "Setup match" : `${detail.score}% of conditions met`}
              </span>
            )}
          </div>
          <button className="close-btn" onClick={onClose}>Close ✕</button>
        </div>

        {hasMultipleSetups && (
          <div className="setup-switcher">
            <label className="field-label" style={{ marginBottom: 6, display: "block" }}>
              This stock was checked against every setup — pick one to view:
            </label>
            <select value={activeSetupId} onChange={(e) => setActiveSetupId(e.target.value)}>
              {allSetupsForStock.map((s) => (
                <option key={s.setup_id} value={s.setup_id}>
                  {s.direction === "bullish" ? "▲ " : "▼ "}{s.setup_name} — {s.score}%
                  {s.qualified ? " (qualified)" : ""}
                </option>
              ))}
            </select>
          </div>
        )}

        {snapshotDetail && <p className="status-line">Saved conditions from {snapshotDate}. Last market candle: {snapshotDetail.data_as_of || "unknown"}. Charts and CSV downloads are not archived with daily runs.</p>}
        {!snapshotDetail && <div className="chart-container" ref={chartRef} />}
        {!snapshotDetail && detail?.price_fetched_at && (
          <p className="status-line">These conditions use scan prices requested at {new Date(detail.price_fetched_at).toLocaleString()}. The chart is loaded separately and may show newer data.</p>
        )}
        {chartError && (
          <div className="empty-state" style={{ padding: "8px 0 16px", fontSize: 12 }}>
            Chart data unavailable: {chartError}
          </div>
        )}

        {!snapshotDetail && <div className="download-row">
          <a style={{ textDecoration: "none" }} href={downloadUrl(symbol, "daily")}>
            <button className="secondary">⬇ Daily CSV</button>
          </a>
          <a style={{ textDecoration: "none" }} href={downloadUrl(symbol, "weekly")}>
            <button className="secondary">⬇ Weekly CSV</button>
          </a>
          <a style={{ textDecoration: "none" }} href={downloadUrl(symbol, "monthly")}>
            <button className="secondary">⬇ Monthly CSV</button>
          </a>
        </div>}

        {error && <div className="empty-state">{error}</div>}

        {detail && !detail.timeframes.monthly && (
          <div className="footnote" style={{ marginTop: 0, marginBottom: 14 }}>
            This setup has no Monthly component — it's evaluated on {Object.keys(detail.timeframes).map((t) => TF_LABELS[t] || t).join(" + ")} only.
            {hasMultipleSetups && " Switch to \"Setup 1\" above to see a Monthly breakdown for this stock."}
          </div>
        )}

        {detail &&
          Object.entries(detail.timeframes).map(([tf, tfData]) => (
            <div className="tf-block" key={tf}>
              <div className="tf-block-header">
                <span>{TF_LABELS[tf] || tf}</span>
                <span>{tfData.passed ? "PASS" : "FAIL"}</span>
              </div>
              {tfData.error && <div className="condition-row">{tfData.error}</div>}
              {Object.entries(tfData.conditions || {}).map(([condId, cond]) => (
                <div className="condition-row" key={condId}>
                  <div>
                    <div className="cond-name">
                      {condId.replace(/_/g, " ")}
                      {cond.confidence === "approximate" && (
                        <span style={{
                          marginLeft: 8, fontSize: 10, fontWeight: 600, textTransform: "uppercase",
                          color: "var(--near)", background: "var(--near-soft)", padding: "1px 6px", borderRadius: 10,
                        }}>approx</span>
                      )}
                    </div>
                    <div className="cond-detail">{cond.detail}</div>
                  </div>
                  <span className={`cond-mark ${cond.passed ? "pass" : "fail"}`}>
                    {cond.passed ? "✓" : "✗"}
                  </span>
                </div>
              ))}
            </div>
          ))}

        <div className="footnote">
          Scheduled daily condition results are retained for seven calendar days. Chart data is fetched separately and is not stored in daily history.
        </div>
      </div>
    </div>
  );
}
