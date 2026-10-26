import pandas as pd
import math


def _latest(df):
    return df.iloc[-1]


def safe_round(value, decimals=2):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, decimals)


def close_above_ema(df: pd.DataFrame, period: int) -> dict:
    row = _latest(df)
    ema_val = row[f"ema{period}"]
    passed = bool(row["close"] > ema_val)
    return {"passed": passed, "value": safe_round(row["close"]),
            "threshold": safe_round(ema_val),
            "detail": f"close {'>' if passed else '<='} EMA{period}"}


def ema_above_ema(df: pd.DataFrame, fast: int, slow: int) -> dict:
    row = _latest(df)
    a, b = row[f"ema{fast}"], row[f"ema{slow}"]
    passed = bool(a > b)
    return {"passed": passed, "value": safe_round(a), "threshold": safe_round(b),
            "detail": f"EMA{fast} {'>' if passed else '<='} EMA{slow}"}


def macd_crossover(df: pd.DataFrame, lookback: int = 1) -> dict:
    prev, curr = df.iloc[-1 - lookback], df.iloc[-1]
    passed = bool(prev["macd"] <= prev["macd_signal"] and curr["macd"] > curr["macd_signal"])
    return {"passed": passed, "value": safe_round(curr["macd"] - curr["macd_signal"], 3),
            "threshold": 0,
            "detail": "MACD crossed above signal" if passed else "no fresh MACD crossover"}


def ema_rising(df: pd.DataFrame, period: int, months: int = 3) -> dict:
    col = f"ema{period}"
    vals = df[col].iloc[-(months + 1):].tolist()
    passed = all(vals[i] > vals[i - 1] for i in range(1, len(vals))) and len(vals) == months + 1
    return {"passed": bool(passed), "value": [safe_round(v) for v in vals],
            "threshold": f"strictly increasing over {months} periods",
            "detail": f"EMA{period} rising {months} periods" if passed else f"EMA{period} not consistently rising"}


def ema_support(df: pd.DataFrame, period: int, tolerance: float = 0.01) -> dict:
    row = _latest(df)
    ema_val = row[f"ema{period}"]
    near = abs(row["low"] - ema_val) / ema_val <= tolerance
    closed_above = row["close"] > ema_val
    passed = bool(near and closed_above)
    return {"passed": passed, "value": safe_round(row["low"]),
            "threshold": safe_round(ema_val),
            "detail": f"low within {tolerance:.0%} of EMA{period} and closed above" if passed
                      else f"no qualifying EMA{period} support interaction"}


def ema_bullish_setup(df: pd.DataFrame, fast=5, mid=13, slow=26, crossover_lookback: int = 5) -> dict:
    window = df.iloc[-(crossover_lookback + 1):]
    crossed = False
    for i in range(1, len(window)):
        prev, curr = window.iloc[i - 1], window.iloc[i]
        cross_mid = prev[f"ema{fast}"] <= prev[f"ema{mid}"] and curr[f"ema{fast}"] > curr[f"ema{mid}"]
        cross_slow = prev[f"ema{fast}"] <= prev[f"ema{slow}"] and curr[f"ema{fast}"] > curr[f"ema{slow}"]
        if cross_mid or cross_slow:
            crossed = True
            break

    row = _latest(df)
    aligned = bool(row[f"ema{fast}"] > row[f"ema{mid}"] > row[f"ema{slow}"])
    passed = bool(crossed and aligned)
    return {"passed": passed,
            "value": {"aligned_now": aligned, "recent_crossover": crossed},
            "threshold": f"EMA{fast} > EMA{mid} > EMA{slow} after a crossover within {crossover_lookback} periods",
            "detail": "bullish EMA structure confirmed" if passed else "no confirmed bullish EMA structure"}


def stochastic_above(df: pd.DataFrame, level: float = 80) -> dict:
    row = _latest(df)
    k = row["stoch_k"]
    if pd.isna(k):
        return {"passed": False, "value": None, "threshold": level,
                "detail": "Stochastic undefined (flat price range this period)"}
    passed = bool(k > level)
    return {"passed": passed, "value": safe_round(k, 1), "threshold": level,
            "detail": f"Stochastic %K {'>' if passed else '<='} {level}"}


def rsi_bounce(df: pd.DataFrame, reference: float = 60, tolerance: float = 1,
               lookback: int = 5) -> dict:
    window = df["rsi"].iloc[-(lookback + 1):]
    latest = window.iloc[-1]
    prev = window.iloc[-2]
    if pd.isna(latest) or pd.isna(prev):
        return {"passed": False, "value": None, "threshold": f"{reference} \u00b1 {tolerance}",
                "detail": "insufficient data for RSI"}
    touched = bool(((window - reference).abs() <= tolerance).any())
    turning_up = bool(latest > prev)
    passed = touched and turning_up
    return {"passed": passed, "value": safe_round(latest, 1),
            "threshold": f"{reference} \u00b1 {tolerance}",
            "detail": "RSI touched reference and is turning up" if passed
                      else "no qualifying RSI bounce"}


CONDITION_REGISTRY = {
    "close_above_ema50": lambda df: close_above_ema(df, 50),
    "close_above_ema200": lambda df: close_above_ema(df, 200),
    "ema50_above_ema200": lambda df: ema_above_ema(df, 50, 200),
    "macd_crossover": lambda df: macd_crossover(df),
    "ema50_rising_3": lambda df: ema_rising(df, 50, 3),
    "ema_support_50": lambda df: ema_support(df, 50, 0.01),
    "ema_bullish_5_13_26": lambda df: ema_bullish_setup(df, 5, 13, 26),
    "stochastic_above_80": lambda df: stochastic_above(df, 80),
    "rsi_bounce_60": lambda df: rsi_bounce(df, 60, 1),
}

# Registered separately at the bottom of this module (see
# conditions_v2.py) to keep the two generations of conditions readable;
# merged into one registry so setup configs can reference either freely.
from . import conditions_v2 as _v2

CONDITION_REGISTRY.update({
    "price_above_ema50": lambda df: close_above_ema(df, 50),
    "price_below_ema50": lambda df: _v2.price_below_ema(df, 50),
    "macd_uptick": _v2.macd_uptick,
    "macd_downtick": _v2.macd_downtick,
    "macd_above_zero": _v2.macd_above_zero,
    "macd_below_zero": _v2.macd_below_zero,
    "rsi_above_60": lambda df: _v2.rsi_above(df, 60),
    "rsi_below_40": lambda df: _v2.rsi_below(df, 40),
    "rsi_above_40": lambda df: _v2.rsi_above(df, 40),
    "rsi_below_60": lambda df: _v2.rsi_below(df, 60),
    "rsi_uptick": _v2.rsi_uptick,
    "rsi_downtick": _v2.rsi_downtick,
    "rsi_bounce_60_bullish": lambda df: rsi_bounce(df, 60, 1),
    "rsi_bounce_40_bearish": lambda df: rsi_bounce(df, 40, 1),
    "adx_rising_above_15": lambda df: _v2.adx_rising_above(df, 15),
    "di_bullish": _v2.di_bullish,
    "di_bearish": _v2.di_bearish,
    "stoch_pco": lambda df: _v2.stoch_crossover(df, "bullish"),
    "stoch_nco": lambda df: _v2.stoch_crossover(df, "bearish"),
    "stoch_pco_from_oversold": lambda df: _v2.stoch_crossover(df, "bullish", from_zone="oversold"),
    "stoch_nco_from_overbought": lambda df: _v2.stoch_crossover(df, "bearish", from_zone="overbought"),
    "stochastic_below_20": lambda df: _v2.indicator_below(df, "stoch_k", 20, "Stochastic"),
    "bbnc_downside": lambda df: _v2.bb_not_challenged(df, "lower", 5),
    "bbnc_upside": lambda df: _v2.bb_not_challenged(df, "upper", 5),
    "ubbc": lambda df: _v2.bb_challenged(df, "upper", 3, 2),
    "lbbc": lambda df: _v2.bb_challenged(df, "lower", 3, 2),
    "volume_above_avg": lambda df: _v2.volume_above_average(df, 1.0),
    "double_screen_bullish": lambda df: _v2.double_screen_confirmation(df, "bullish"),
    "double_screen_bearish": lambda df: _v2.double_screen_confirmation(df, "bearish"),
    "bullish_candle_pattern": _v2.bullish_candle_pattern,
    "bearish_candle_pattern": _v2.bearish_candle_pattern,
    "bullish_divergence_rsi": lambda df: _v2.regular_divergence(df, "bullish", "rsi"),
    "bearish_divergence_rsi": lambda df: _v2.regular_divergence(df, "bearish", "rsi"),
    "higher_lows_2": lambda df: _v2.swing_structure(df, "up", n_points=2),
    "lower_highs_2": lambda df: _v2.swing_structure(df, "down", n_points=2),
    "double_bottom": lambda df: _v2.double_pattern(df, "bottom"),
    "double_top": lambda df: _v2.double_pattern(df, "top"),
    "trendline_breakout_up": lambda df: _v2.trendline_break(df, "up"),
    "trendline_breakdown": lambda df: _v2.trendline_break(df, "down"),
    "triangle_breakout_up": lambda df: _v2.triangle_breakout(df, "up"),
    "triangle_breakdown": lambda df: _v2.triangle_breakout(df, "down"),
    "macd_nco": _v2.macd_crossover_down,
})
