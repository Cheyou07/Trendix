import React from "react";

const SETUP_DOCS = [
  {
    id: "setup_1",
    direction: "bullish",
    name: "Setup 1 — Multi-Timeframe Trend",
    summary: "The original setup. Requires agreement across all three timeframes: a monthly uptrend, a weekly momentum entry, and daily long-term structure.",
    timeframes: [
      { label: "Monthly (3 conditions)", points: [
        "Close above the 50 EMA",
        "A fresh MACD crossover above its signal line (not just already above it)",
        "50 EMA rising for 3 straight months",
      ]},
      { label: "Weekly (5 conditions)", points: [
        "Close above the 50 EMA",
        "Price touched the 50 EMA (within 1%) and closed back above it (\"support\")",
        "Bullish 5/13/26 EMA structure: a recent crossover followed by 5 > 13 > 26 alignment",
        "Stochastic %K above 80",
        "RSI touched ~60 and turned back up",
      ]},
      { label: "Daily (4 conditions)", points: [
        "Close above the 200 EMA",
        "50 EMA above the 200 EMA",
        "Same EMA-support and EMA-structure checks as weekly, on the daily chart",
      ]},
    ],
  },
  {
    id: "setup_2_3",
    direction: "pair",
    name: "3rd Wave Setup — Bullish / Bearish",
    summary: "A trend-continuation setup: weekly momentum confirms the larger trend is intact and healthy, daily conditions time the entry into what would be an Elliott-Wave-style \"3rd wave\" move.",
    timeframes: [
      { label: "Weekly", points: [
        "MACD ticking in the setup's direction (up for bullish, down for bearish)",
        "Bollinger Band on the opposite side \"not challenged\" — no recent close-through with the band curving that way (a sign the trend hasn't been threatened)",
        "Price on the correct side of the 50 EMA",
      ]},
      { label: "Daily", points: [
        "Two rising pivot lows (bullish) or falling pivot highs (bearish) — basic trend structure",
        "A trendline break in the setup's direction, alongside the opposite Bollinger Band being actively challenged",
        "RSI past 60/40 and ticking further in that direction",
        "ADX above 15 and rising, with +DI/-DI confirming direction",
        "MACD ticking, Stochastic crossing in that direction",
        "Volume above its 20-day average (required in every setup)",
      ]},
    ],
  },
  {
    id: "setup_4_5",
    direction: "pair",
    name: "Triangle Breakout / Breakdown — Bullish / Bearish",
    summary: "Looks for a consolidation (\"triangle\") that resolves in the trend's direction, with momentum and volume confirming the breakout is real rather than a false move.",
    timeframes: [
      { label: "Weekly", points: [
        "MACD ticking in the setup's direction and on the correct side of zero",
        "Bollinger Band \"not challenged\" on the opposite side",
        "Double Screen Confirmation: MACD ticks that way AND (Stochastic or RSI also ticks that way)",
        "Price on the correct side of the 50 EMA",
      ]},
      { label: "Daily", points: [
        "A detected \"squeeze then breakout\" pattern (Bollinger Band width contracts, then price closes beyond the band) — this is the triangle proxy",
        "A trendline break in the same direction",
        "The band on the breakout side being actively challenged",
        "Stochastic and RSI in the trend's favor, ADX rising above 15, +DI/-DI confirming",
        "Double Screen Confirmation again on the daily chart",
        "Volume above average",
      ]},
    ],
  },
  {
    id: "setup_6_7",
    direction: "pair",
    name: "Ending Diagonal Triangle — Bullish / Bearish Reversal",
    summary: "A reversal setup: looks for a prior trend running out of steam (divergence) right as a wedge/triangle-like squeeze resolves the other way. This is the most pattern-reliant setup and leans most heavily on approximated conditions.",
    timeframes: [
      { label: "Weekly", points: [
        "MACD ticking in the new (reversal) direction",
        "Bollinger Band \"not challenged\" on the side of the OLD trend",
      ]},
      { label: "Daily", points: [
        "A squeeze-then-breakout pattern in the reversal direction (the EDT/triangle proxy)",
        "Regular RSI divergence: price makes a new high/low the indicator doesn't confirm",
        "The relevant band being challenged, RSI past 60/40, ADX rising, +DI/-DI confirming",
        "Double Screen Confirmation",
        "A fresh MACD crossover in the reversal direction",
        "Volume above average",
      ]},
    ],
  },
  {
    id: "setup_8_9",
    direction: "pair",
    name: "Trend Reversal Swing — Bullish / Bearish (Double Bottom / Double Top)",
    summary: "Classic double-bottom (or double-top) reversal: two similar price lows/highs spaced 8–10 candles apart, confirmed by a reversal candlestick pattern and supporting momentum.",
    timeframes: [
      { label: "Weekly", points: [
        "Bollinger Band \"not challenged\" on the side of the prior trend",
      ]},
      { label: "Daily", points: [
        "Two pivot lows/highs within ~3% of each other, 8–10 candles apart, followed by a reversal candle (Bullish/Bearish Engulfing, Piercing Line, or Dark Cloud Cover)",
        "Volume above average on the reversal candle",
        "MACD ticking in the new direction",
        "RSI past the midpoint (40 for bullish, 60 for bearish)",
        "Stochastic crossing up from oversold / down from overbought",
        "+DI/-DI confirming the new direction",
      ]},
    ],
  },
];

export default function AboutPage({ onClose }) {
  return (
    <div className="about-page">
      <div className="about-header">
        <h1>About this scanner</h1>
        <button className="close-btn" onClick={onClose}>Close ✕</button>
      </div>

      <section className="about-section">
        <h2>How it works</h2>
        <p>
          You pick an index (NIFTY50/100/200/500/Bank) and either one setup or
          "Best matches across all setups." The scanner pulls fresh price data
          for every stock, computes indicators (EMA, MACD, RSI, Stochastic,
          ADX/DI, Bollinger Bands), checks every condition in the chosen
          setup(s), and shows you which stocks pass. Nothing is stored on the
          server between scans — data is fetched live and held only in memory
          for that session.
        </p>
      </section>

      <section className="about-section">
        <h2>Reading the "confidence" badges</h2>
        <p>
          Every condition in a stock's breakdown is either <strong>exact</strong> or
          flagged <span className="approx-badge">APPROX</span>. Exact conditions are
          standard, unambiguous technical calculations (EMA levels, RSI
          thresholds, candlestick patterns, and so on). Approximate conditions
          — trendline breaks, triangle/Ending-Diagonal-Triangle patterns, swing
          structure, and divergence — are best-effort automated proxies for
          genuinely discretionary chart reading. They won't always agree with
          what a trained eye would call by looking at the chart directly, so
          treat them as a helpful narrowing tool, not a final verdict.
        </p>
      </section>

      {SETUP_DOCS.map((setup) => (
        <section className="about-section setup-doc" key={setup.id}>
          <h2>
            {setup.direction === "bullish" && <span className="dir-tag bullish">▲ BULLISH</span>}
            {setup.direction === "bearish" && <span className="dir-tag bearish">▼ BEARISH</span>}
            {setup.direction === "pair" && <span className="dir-tag pair">▲▼ BULL / BEAR PAIR</span>}
            {setup.name}
          </h2>
          <p className="setup-summary">{setup.summary}</p>
          {setup.timeframes.map((tf) => (
            <div key={tf.label} className="setup-tf">
              <div className="setup-tf-label">{tf.label}</div>
              <ul>
                {tf.points.map((point, i) => <li key={i}>{point}</li>)}
              </ul>
            </div>
          ))}
        </section>
      ))}

      <section className="about-section">
        <h2>What's intentionally excluded</h2>
        <ul>
          <li>Stop Loss / Target levels — trade-management info, not screening criteria.</li>
          <li>"Histogram Converging" and a couple of similarly underspecified pattern-within-a-pattern clauses that had no single standard definition.</li>
          <li>"Supporting Indicators" that weren't explicitly marked "Must Have" in the original setup definitions are informational only and don't affect pass/fail — except Volume, which every setup marks as mandatory.</li>
        </ul>
      </section>
    </div>
  );
}
