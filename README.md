# NIFTY Multi-Setup Scanner

For public hosting, MongoDB daily history, and the automatic seven-day retention
setup, see [DEPLOYMENT.md](DEPLOYMENT.md). The deployment files are prepared locally;
connect your own GitHub, Render, and MongoDB Atlas accounts to publish a URL.

Now supports 9 setups total: your original Setup 1, plus 8 new setups
from Setups_for_AI.xlsx (4 bullish/bearish pairs: 3rd Wave, Triangle
Breakout, Ending Diagonal Triangle, Trend Reversal Swing).

## Two scan modes (sidebar dropdown)
- **Run one setup**: same as before, setups grouped Bullish/Bearish in the dropdown.
- **Best matches across ALL setups**: fetches each stock once, evaluates
  it against every setup (or just bullish/bearish if filtered), and
  ranks stocks by how many setups they qualify for, tie-broken by
  average score across all setups evaluated.

## Confidence flags
Every condition result includes a confidence level:
- **exact**: standard, unambiguous technical calculation (EMA, MACD,
  RSI, Stochastic, ADX/DI, Bollinger Band touch rules, candlestick
  patterns, volume).
- **approximate**: a best-effort automated proxy for a genuinely
  discretionary chart-reading judgment (trendline breaks, triangle/
  Ending-Diagonal-Triangle patterns, swing/HL-LH structure, divergence,
  double top/bottom). These are flagged with an "APPROX" badge in the
  stock detail panel and may disagree with manual chart reading -
  they are not a certified reproduction of Elliott Wave / trendline
  analysis.

## Design decisions worth knowing
- **"Must Have" only**: each setup sheet marks Volume as mandatory
  ("Must Have"); other "Supporting Indicators" (like divergence) are
  informational and were NOT forced into the pass/fail logic unless
  the sheet marked them mandatory.
- **Stop Loss / Target rows** are trade-management info, not screening
  criteria - omitted entirely from the scoring logic.
- **"Histogram Converging + TLBO in Histogram"** and a couple of other
  pattern-within-a-pattern clauses were too underspecified to encode
  confidently and were omitted rather than guessed at.
- Parameters used per your answers: BBNC = closed beyond band + band
  turned in price's direction (5-bar window); UBBC/LBBC = at least 2 of
  the last 3 candles closed at/beyond the band; uptick/downtick = single
  bar-over-bar; RSI touch-and-bounce tolerance = ±1.

See prior versions of this README (same repo history) for full run
instructions - run.sh/run.bat in backend/ and frontend/, or manual
python -m venv venv / pip install / uvicorn, npm install / npm run dev.
