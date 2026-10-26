"""
Indicator engine (System 3 from the design doc).

Pure pandas implementations - no TA-Lib dependency. Every function takes
a DataFrame with 'open'/'high'/'low'/'close'/'volume' and returns it with
indicator columns appended. Timeframe-agnostic.
"""
import pandas as pd
import numpy as np


def add_ema(df: pd.DataFrame, period: int) -> pd.DataFrame:
    col = f"ema{period}"
    df[col] = df["close"].ewm(span=period, adjust=False).mean()
    return df


def add_macd(df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    return df


def add_rsi(df: pd.DataFrame, period=14) -> pd.DataFrame:
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


def add_stochastic(df: pd.DataFrame, k_period=14, d_period=3, smooth=3) -> pd.DataFrame:
    low_min = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    raw_k = 100 * (df["close"] - low_min) / (high_max - low_min)
    df["stoch_k"] = raw_k.rolling(smooth).mean()
    df["stoch_d"] = df["stoch_k"].rolling(d_period).mean()
    return df


def add_bollinger(df: pd.DataFrame, period=20, num_std=2) -> pd.DataFrame:
    mid = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std()
    df["bb_mid"] = mid
    df["bb_upper"] = mid + num_std * std
    df["bb_lower"] = mid - num_std * std
    return df


def add_adx(df: pd.DataFrame, period=14) -> pd.DataFrame:
    high, low, close = df["high"], df["low"], df["close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()

    df["plus_di"] = plus_di
    df["minus_di"] = minus_di
    df["adx"] = adx
    return df


def add_volume_avg(df: pd.DataFrame, period=20) -> pd.DataFrame:
    df["vol_avg"] = df["volume"].rolling(period).mean()
    return df


def compute_all_indicators(df: pd.DataFrame, ema_periods=(5, 13, 26, 50, 200)) -> pd.DataFrame:
    """Run the full indicator set on one timeframe."""
    df = df.copy()
    for p in ema_periods:
        df = add_ema(df, p)
    df = add_macd(df)
    df = add_rsi(df)
    df = add_stochastic(df)
    df = add_bollinger(df)
    df = add_adx(df)
    df = add_volume_avg(df)
    return df


def resample_ohlcv(daily_df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Derive weekly ('W') or monthly ('ME') candles from daily data."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = daily_df.resample(rule).agg(agg).dropna(how="any")
    return out
