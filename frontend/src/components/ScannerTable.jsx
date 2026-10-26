import React from "react";

function tfScore(tf) {
  if (!tf || tf.error) return { passed: 0, total: 0 };
  const conds = Object.values(tf.conditions);
  return { passed: conds.filter((c) => c.passed).length, total: conds.length };
}

export default function ScannerTable({ results, onSelect }) {
  if (!results || results.length === 0) {
    return <div className="empty-state">No matches yet. Run a scan from the sidebar.</div>;
  }

  return (
    <div className="stock-list">
      {results.map((r) => {
        const m = tfScore(r.timeframes.monthly);
        const w = tfScore(r.timeframes.weekly);
        const d = tfScore(r.timeframes.daily);
        return (
          <div className="stock-card" key={r.symbol} onClick={() => onSelect(r.symbol)}>
            <div className="stock-card-left">
              <span className="stock-symbol">{r.symbol}</span>
              <div className="tf-pills">
                <span className={`tf-pill ${m.passed === m.total ? "full" : ""}`}>M {m.passed}/{m.total}</span>
                <span className={`tf-pill ${w.passed === w.total ? "full" : ""}`}>W {w.passed}/{w.total}</span>
                <span className={`tf-pill ${d.passed === d.total ? "full" : ""}`}>D {d.passed}/{d.total}</span>
              </div>
            </div>
            <div className="stock-card-right">
              <span className="score-text">{r.score}%</span>
              <span className={`badge ${r.qualified ? "match" : "near"}`}>
                {r.qualified ? "Match" : "Near match"}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
