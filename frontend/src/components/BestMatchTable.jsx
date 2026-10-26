import React from "react";

export default function BestMatchTable({ results, onSelect }) {
  if (!results) {
    return <div className="empty-state">Choose a direction filter (or "All setups") and run a scan.</div>;
  }
  if (results.length === 0) {
    return <div className="empty-state">No stocks returned usable data for this scan.</div>;
  }

  return (
    <div className="stock-list">
      {results.map((r) => (
        <div className="stock-card" key={r.symbol} onClick={() => onSelect(r.symbol)}>
          <div className="stock-card-left">
            <span className="stock-symbol">{r.symbol}</span>
            <span className={`badge ${r.best_direction === "bullish" ? "match" : "near"}`}
                  style={r.best_direction === "bearish" ? { background: "var(--bear-soft)", color: "var(--bear)" } : {}}>
              {r.best_direction === "bullish" ? "▲" : "▼"} {r.best_setup_name}
            </span>
          </div>
          <div className="stock-card-right">
            <span className="score-text">{r.qualified_setup_count} setup{r.qualified_setup_count === 1 ? "" : "s"} qualified</span>
            <span className="score-text">avg {r.avg_score}%</span>
            <span className="badge match">{r.best_score}% best</span>
          </div>
        </div>
      ))}
    </div>
  );
}
