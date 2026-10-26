"""
Second-generation condition primitives, added for the multi-setup
library (3rd Wave, Triangle Breakout, Ending Diagonal Triangle, Trend
Reversal Swing - bullish and bearish).

Every condition returns:
    {"passed": bool, "value": ..., "threshold": ..., "detail": "...",
     "confidence": "exact" | "approximate"}

"exact" = a standard, unambiguous technical calculation.
"approximate" = a best-effort proxy for a genuinely discretionary
chart-reading judgment (trendlines, triangles, swing patterns). These
are flagged so the UI can visually distinguish them - they are not
guaranteed to match what a trained eye would call on the chart.
"""
import pandas as pd
import numpy as np
from .conditions import safe_round, _latest


# ---------------------------------------------------------------------
# Generic single-indicator helpers (uptick/downtick, above/below level)
# ---------------------------------------------------------------------

def indicator_uptick(df: pd.DataFrame, col: str, label: str) -> dict:
    curr, prev = df[col].iloc[-1], df[col].iloc[-2]
    if pd.isna(curr) or pd.isna(prev):
        return {"passed": False, "value": None, "threshold": "rising vs prior bar",
                "detail": f"{label} insufficient data", "confidence": "exact"}
    passed = bool(curr > prev)
    return {"passed": passed, "value": safe_round(curr), "threshold": safe_round(prev),
            "detail": f"{label} {'ticked up' if passed else 'did not tick up'} vs prior bar",
            "confidence": "exact"}


def indicator_downtick(df: pd.DataFrame, col: str, label: str) -> dict:
    curr, prev = df[col].iloc[-1], df[col].iloc[-2]
    if pd.isna(curr) or pd.isna(prev):
        return {"passed": False, "value": None, "threshold": "falling vs prior bar",
                "detail": f"{label} insufficient data", "confidence": "exact"}
    passed = bool(curr < prev)
    return {"passed": passed, "value": safe_round(curr), "threshold": safe_round(prev),
            "detail": f"{label} {'ticked down' if passed else 'did not tick down'} vs prior bar",
            "confidence": "exact"}


def indicator_above(df: pd.DataFrame, col: str, level: float, label: str) -> dict:
    val = df[col].iloc[-1]
    if pd.isna(val):
        return {"passed": False, "value": None, "threshold": level,
                "detail": f"{label} insufficient data", "confidence": "exact"}
    passed = bool(val > level)
    return {"passed": passed, "value": safe_round(val), "threshold": level,
            "detail": f"{label} {'>' if passed else '<='} {level}", "confidence": "exact"}


def indicator_below(df: pd.DataFrame, col: str, level: float, label: str) -> dict:
    val = df[col].iloc[-1]
    if pd.isna(val):
        return {"passed": False, "value": None, "threshold": level,
                "detail": f"{label} insufficient data", "confidence": "exact"}
    passed = bool(val < level)
    return {"passed": passed, "value": safe_round(val), "threshold": level,
            "detail": f"{label} {'<' if passed else '>='} {level}", "confidence": "exact"}


# MACD
def macd_uptick(df): return indicator_uptick(df, "macd", "MACD")
def macd_downtick(df): return indicator_downtick(df, "macd", "MACD")
def macd_above_zero(df): return indicator_above(df, "macd", 0, "MACD")
def macd_below_zero(df): return indicator_below(df, "macd", 0, "MACD")

def macd_crossover_down(df, lookback=1) -> dict:
    """Fresh MACD-below-signal crossover (NCO) - bearish counterpart to Setup 1's macd_crossover."""
    prev, curr = df.iloc[-1 - lookback], df.iloc[-1]
    passed = bool(prev["macd"] >= prev["macd_signal"] and curr["macd"] < curr["macd_signal"])
    return {"passed": passed, "value": safe_round(curr["macd"] - curr["macd_signal"], 3),
            "threshold": 0, "detail": "MACD crossed below signal" if passed else "no fresh MACD NCO",
            "confidence": "exact"}

# RSI
def rsi_above(df, level): return indicator_above(df, "rsi", level, "RSI")
def rsi_below(df, level): return indicator_below(df, "rsi", level, "RSI")
def rsi_uptick(df): return indicator_uptick(df, "rsi", "RSI")
def rsi_downtick(df): return indicator_downtick(df, "rsi", "RSI")

def price_below_ema(df, period=50) -> dict:
    row = df.iloc[-1]
    ema_val = row[f"ema{period}"]
    passed = bool(row["close"] < ema_val)
    return {"passed": passed, "value": safe_round(row["close"]), "threshold": safe_round(ema_val),
            "detail": f"close {'<' if passed else '>='} EMA{period}", "confidence": "exact"}

# ADX / DI
def adx_rising_above(df, level=15) -> dict:
    row, prev = df.iloc[-1], df.iloc[-2]
    if pd.isna(row["adx"]) or pd.isna(prev["adx"]):
        return {"passed": False, "value": None, "threshold": level,
                "detail": "ADX insufficient data", "confidence": "exact"}
    passed = bool(row["adx"] > level and row["adx"] > prev["adx"])
    return {"passed": passed, "value": safe_round(row["adx"]), "threshold": level,
            "detail": f"ADX {'>' if passed else 'not >'} {level} and rising", "confidence": "exact"}


def di_bullish(df) -> dict:
    row = _latest(df)
    passed = bool(row["plus_di"] > row["minus_di"])
    return {"passed": passed, "value": safe_round(row["plus_di"]), "threshold": safe_round(row["minus_di"]),
            "detail": f"+DI {'>' if passed else '<='} -DI", "confidence": "exact"}


def di_bearish(df) -> dict:
    row = _latest(df)
    passed = bool(row["minus_di"] > row["plus_di"])
    return {"passed": passed, "value": safe_round(row["minus_di"]), "threshold": safe_round(row["plus_di"]),
            "detail": f"-DI {'>' if passed else '<='} +DI", "confidence": "exact"}


# Stochastic crossovers
def stoch_crossover(df, direction="bullish", from_zone=None, lookback=1) -> dict:
    prev, curr = df.iloc[-1 - lookback], df.iloc[-1]
    if direction == "bullish":
        crossed = bool(prev["stoch_k"] <= prev["stoch_d"] and curr["stoch_k"] > curr["stoch_d"])
        zone_ok = True
        if from_zone == "oversold":
            zone_ok = bool(prev["stoch_k"] < 20)
        passed = crossed and zone_ok
        label = "Stochastic PCO" + (" from oversold" if from_zone else "")
    else:
        crossed = bool(prev["stoch_k"] >= prev["stoch_d"] and curr["stoch_k"] < curr["stoch_d"])
        zone_ok = True
        if from_zone == "overbought":
            zone_ok = bool(prev["stoch_k"] > 80)
        passed = crossed and zone_ok
        label = "Stochastic NCO" + (" from overbought" if from_zone else "")
    return {"passed": bool(passed), "value": safe_round(curr["stoch_k"], 1), "threshold": safe_round(curr["stoch_d"], 1),
            "detail": f"{label} {'confirmed' if passed else 'not confirmed'}", "confidence": "exact"}


# Bollinger Band conditions
def _band_slope(df, col, lookback=3):
    vals = df[col].iloc[-(lookback + 1):]
    if len(vals) < 2 or vals.isna().any():
        return 0
    return vals.iloc[-1] - vals.iloc[0]


def bb_not_challenged(df, side="lower", lookback=5) -> dict:
    """
    BBNC per your definition: 'challenged' = a candle closed beyond the
    band AND the band turned in price's direction. Not-challenged is the
    absence of that over the recent window.
    """
    band_col = "bb_lower" if side == "lower" else "bb_upper"
    window = df.iloc[-lookback:]
    if side == "lower":
        closed_beyond = (window["close"] < window[band_col]).any()
        band_turning = _band_slope(df, band_col) < 0  # band curving down = "turned toward" a downside challenge
    else:
        closed_beyond = (window["close"] > window[band_col]).any()
        band_turning = _band_slope(df, band_col) > 0

    challenged = bool(closed_beyond and band_turning)
    passed = not challenged
    return {"passed": passed, "value": bool(closed_beyond), "threshold": f"no close beyond {side} band + band turning ({lookback}-bar window)",
            "detail": f"{side} band {'challenged' if challenged else 'not challenged'} recently", "confidence": "exact"}


def bb_challenged(df, side="upper", lookback=3, min_touches=2) -> dict:
    """UBBC/LBBC: at least min_touches of the last `lookback` candles closed at/beyond the band."""
    band_col = "bb_upper" if side == "upper" else "bb_lower"
    window = df.iloc[-lookback:]
    if side == "upper":
        touches = int((window["close"] >= window[band_col]).sum())
    else:
        touches = int((window["close"] <= window[band_col]).sum())
    passed = bool(touches >= min_touches)
    return {"passed": passed, "value": touches, "threshold": f">= {min_touches} closes in last {lookback} bars",
            "detail": f"{side.upper()} band challenged {touches}/{lookback} recent candles", "confidence": "exact"}


# Volume
def volume_above_average(df, multiplier=1.0) -> dict:
    row = _latest(df)
    if pd.isna(row["vol_avg"]):
        return {"passed": False, "value": None, "threshold": None,
                "detail": "insufficient data for volume average", "confidence": "exact"}
    threshold = row["vol_avg"] * multiplier
    passed = bool(row["volume"] > threshold)
    return {"passed": passed, "value": safe_round(row["volume"], 0), "threshold": safe_round(threshold, 0),
            "detail": f"volume {'above' if passed else 'not above'} {multiplier}x average", "confidence": "exact"}


# Double Screen Confirmation (explicitly defined by user)
def double_screen_confirmation(df, direction="bullish") -> dict:
    macd_tick = macd_uptick(df) if direction == "bullish" else macd_downtick(df)
    stoch_tick = indicator_uptick(df, "stoch_k", "Stochastic") if direction == "bullish" else indicator_downtick(df, "stoch_k", "Stochastic")
    rsi_tick = rsi_uptick(df) if direction == "bullish" else rsi_downtick(df)
    passed = bool(macd_tick["passed"] and (stoch_tick["passed"] or rsi_tick["passed"]))
    return {"passed": passed, "value": {"macd": macd_tick["passed"], "stoch": stoch_tick["passed"], "rsi": rsi_tick["passed"]},
            "threshold": f"MACD {direction} tick AND (Stoch or RSI {direction} tick)",
            "detail": "Double Screen Confirmation " + ("met" if passed else "not met"), "confidence": "exact"}


# Candlestick patterns (standard OHLC rules)
def bullish_candle_pattern(df) -> dict:
    c, p = df.iloc[-1], df.iloc[-2]
    engulfing = bool(c["close"] > c["open"] and p["close"] < p["open"] and
                      c["close"] > p["open"] and c["open"] < p["close"])
    piercing = bool(p["close"] < p["open"] and c["open"] < p["low"] and
                     c["close"] > (p["open"] + p["close"]) / 2 and c["close"] < p["open"])
    passed = bool(engulfing or piercing)
    which = "Bullish Engulfing" if engulfing else ("Piercing Line" if piercing else "none")
    return {"passed": passed, "value": which, "threshold": "Engulfing or Piercing pattern",
            "detail": f"candle pattern: {which}", "confidence": "exact"}


def bearish_candle_pattern(df) -> dict:
    c, p = df.iloc[-1], df.iloc[-2]
    engulfing = bool(c["close"] < c["open"] and p["close"] > p["open"] and
                      c["close"] < p["open"] and c["open"] > p["close"])
    dark_cloud = bool(p["close"] > p["open"] and c["open"] > p["high"] and
                       c["close"] < (p["open"] + p["close"]) / 2 and c["close"] > p["open"])
    passed = bool(engulfing or dark_cloud)
    which = "Bearish Engulfing" if engulfing else ("Dark Cloud Cover" if dark_cloud else "none")
    return {"passed": passed, "value": which, "threshold": "Engulfing or Dark Cloud Cover pattern",
            "detail": f"candle pattern: {which}", "confidence": "exact"}


# ---------------------------------------------------------------------
# Swing / pivot detection - the shared basis for divergence, HL/LH
# structure, double top/bottom, and the trendline/triangle proxies.
# APPROXIMATE: a simple N-bar fractal, not a claim to match your
# discretionary chart reading exactly.
# ---------------------------------------------------------------------

def find_pivots(series: pd.Series, window: int = 3):
    """Return (pivot_high_idx, pivot_low_idx) - integer positions where
    the value is the max/min within +/- window bars."""
    highs, lows = [], []
    vals = series.values
    n = len(vals)
    for i in range(window, n - window):
        seg = vals[i - window:i + window + 1]
        if np.isnan(seg).any():
            continue
        if vals[i] == seg.max() and vals[i] == np.max(seg):
            highs.append(i)
        if vals[i] == seg.min():
            lows.append(i)
    return highs, lows


def regular_divergence(df, direction="bearish", indicator_col="rsi", window=3, lookback=90) -> dict:
    """
    Your definition: bearish = price makes a Higher High while the
    indicator makes a Lower High. Bullish = price makes a Lower Low
    while the indicator makes a Higher Low.
    """
    recent = df.iloc[-lookback:] if len(df) > lookback else df
    price_highs, price_lows = find_pivots(recent["close"], window)

    if direction == "bearish":
        if len(price_highs) < 2:
            return {"passed": False, "value": None, "threshold": "2 pivot highs required",
                    "detail": "not enough pivot highs to assess divergence", "confidence": "approximate"}
        i1, i2 = price_highs[-2], price_highs[-1]
        price_hh = recent["close"].iloc[i2] > recent["close"].iloc[i1]
        ind_lh = recent[indicator_col].iloc[i2] < recent[indicator_col].iloc[i1]
        passed = bool(price_hh and ind_lh)
        detail = "bearish divergence: price HH, indicator LH" if passed else "no bearish divergence detected"
    else:
        if len(price_lows) < 2:
            return {"passed": False, "value": None, "threshold": "2 pivot lows required",
                    "detail": "not enough pivot lows to assess divergence", "confidence": "approximate"}
        i1, i2 = price_lows[-2], price_lows[-1]
        price_ll = recent["close"].iloc[i2] < recent["close"].iloc[i1]
        ind_hl = recent[indicator_col].iloc[i2] > recent[indicator_col].iloc[i1]
        passed = bool(price_ll and ind_hl)
        detail = "bullish divergence: price LL, indicator HL" if passed else "no bullish divergence detected"

    return {"passed": passed, "value": None, "threshold": f"{direction} divergence vs {indicator_col}",
            "detail": detail, "confidence": "approximate"}


def swing_structure(df, direction="up", window=3, n_points=2, lookback=90) -> dict:
    """'Uptrend with 2 HLs' / 'downtrend with 2 LHs' proxy: last n_points
    pivot lows (up) or pivot highs (down) are strictly increasing/decreasing."""
    recent = df.iloc[-lookback:] if len(df) > lookback else df
    highs, lows = find_pivots(recent["close"], window)
    pts = lows if direction == "up" else highs
    if len(pts) < n_points:
        return {"passed": False, "value": None, "threshold": f"{n_points} pivots required",
                "detail": "not enough pivots to assess trend structure", "confidence": "approximate"}
    last_pts = pts[-n_points:]
    vals = [recent["close"].iloc[i] for i in last_pts]
    if direction == "up":
        passed = all(vals[i] > vals[i - 1] for i in range(1, len(vals)))
        detail = f"{n_points} rising pivot lows (higher lows)" if passed else "pivot lows not consistently rising"
    else:
        passed = all(vals[i] < vals[i - 1] for i in range(1, len(vals)))
        detail = f"{n_points} falling pivot highs (lower highs)" if passed else "pivot highs not consistently falling"
    return {"passed": bool(passed), "value": [safe_round(v) for v in vals], "threshold": None,
            "detail": detail, "confidence": "approximate"}


def double_pattern(df, direction="bottom", window=3, tolerance=0.03, min_gap=8, max_gap=10, lookback=90) -> dict:
    """Double Top/Bottom proxy: last two pivot highs (top) or lows
    (bottom) within `tolerance` of each other, spaced min_gap-max_gap
    candles apart (your '8-10 candles' rule), followed by a reversal
    candle in the expected direction."""
    recent = df.iloc[-lookback:] if len(df) > lookback else df
    highs, lows = find_pivots(recent["close"], window)
    pts = lows if direction == "bottom" else highs
    if len(pts) < 2:
        return {"passed": False, "value": None, "threshold": None,
                "detail": f"not enough pivots to assess double {direction}", "confidence": "approximate"}
    i1, i2 = pts[-2], pts[-1]
    gap = i2 - i1
    v1, v2 = recent["close"].iloc[i1], recent["close"].iloc[i2]
    close_enough = abs(v1 - v2) / v1 <= tolerance
    spaced_right = min_gap <= gap <= max_gap
    reversal = bullish_candle_pattern(df)["passed"] if direction == "bottom" else bearish_candle_pattern(df)["passed"]
    passed = bool(close_enough and spaced_right and reversal)
    return {"passed": passed, "value": {"gap_candles": gap, "level_diff_pct": safe_round(abs(v1 - v2) / v1 * 100, 1)},
            "threshold": f"levels within {tolerance:.0%}, {min_gap}-{max_gap} candles apart, + reversal candle",
            "detail": f"double {direction} {'confirmed' if passed else 'not confirmed'} (approximate)",
            "confidence": "approximate"}


def trendline_break(df, direction="up", window=3, n_pivots=3, lookback=90) -> dict:
    """
    TLBO/TLBD proxy: fit a line through the last n_pivots pivot lows
    (for a breakout up through downtrend resistance is actually pivot
    HIGHS; for breakDOWN through uptrend support use pivot LOWS), then
    check if the latest close breaks through that projected line.
    NOTE: real trendlines are subjective (your own annotation matters
    more than any formula) - this is the least reliable proxy in the
    system, flagged accordingly.
    """
    recent = df.iloc[-lookback:] if len(df) > lookback else df
    highs, lows = find_pivots(recent["close"], window)
    pts = highs if direction == "up" else lows  # breaking UP through a highs-trendline; breaking DOWN through a lows-trendline
    if len(pts) < n_pivots:
        return {"passed": False, "value": None, "threshold": f"{n_pivots} pivots required",
                "detail": "not enough pivots to fit a trendline", "confidence": "approximate"}
    recent_pts = pts[-n_pivots:]
    xs = np.array(recent_pts)
    ys = recent["close"].iloc[recent_pts].values
    slope, intercept = np.polyfit(xs, ys, 1)
    projected = slope * (len(recent) - 1) + intercept
    latest_close = recent["close"].iloc[-1]
    if direction == "up":
        passed = bool(latest_close > projected and slope <= 0)  # breaking UP through a flat/declining resistance line
    else:
        passed = bool(latest_close < projected and slope >= 0)  # breaking DOWN through a flat/rising support line
    return {"passed": passed, "value": safe_round(latest_close), "threshold": safe_round(projected),
            "detail": f"trendline break {direction} {'detected' if passed else 'not detected'} (approximate, regression-based proxy)",
            "confidence": "approximate"}


def triangle_breakout(df, direction="up", squeeze_lookback=20, squeeze_threshold=0.6) -> dict:
    """
    Triangle / Ending Diagonal Triangle proxy: Bollinger Band width
    contracted (squeeze) over the recent window, then price closes
    beyond the band in `direction`. This is a rough stand-in for real
    triangle/Elliott-wave pattern recognition - the lowest-confidence
    proxy in the system.
    """
    width = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
    recent_width = width.iloc[-squeeze_lookback:]
    if recent_width.isna().any():
        return {"passed": False, "value": None, "threshold": None,
                "detail": "insufficient data for squeeze detection", "confidence": "approximate"}
    was_squeezed = bool(recent_width.iloc[0] > 0 and recent_width.min() < recent_width.iloc[0] * squeeze_threshold)
    row = _latest(df)
    if direction == "up":
        breakout = bool(row["close"] > row["bb_upper"])
    else:
        breakout = bool(row["close"] < row["bb_lower"])
    passed = bool(was_squeezed and breakout)
    return {"passed": passed, "value": {"was_squeezed": was_squeezed, "breakout": breakout},
            "threshold": "BB squeeze followed by a breakout close beyond the band",
            "detail": f"triangle/EDT breakout {direction} {'detected' if passed else 'not detected'} (approximate, squeeze-based proxy)",
            "confidence": "approximate"}
