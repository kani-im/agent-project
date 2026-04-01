"""Technical analysis indicators using pandas-ta."""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta


def compute_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Compute Relative Strength Index."""
    return ta.rsi(close, length=length)


def compute_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """Compute MACD (returns DataFrame with MACD, histogram, signal)."""
    return ta.macd(close, fast=fast, slow=slow, signal=signal)


def compute_bollinger_bands(
    close: pd.Series,
    length: int = 20,
    std: float = 2.0,
) -> pd.DataFrame:
    """Compute Bollinger Bands (lower, mid, upper, bandwidth, %b)."""
    return ta.bbands(close, length=length, std=std)


def compute_ema(close: pd.Series, length: int = 20) -> pd.Series:
    """Compute Exponential Moving Average."""
    return ta.ema(close, length=length)


def compute_volume_sma(volume: pd.Series, length: int = 20) -> pd.Series:
    """Compute Simple Moving Average of volume."""
    return ta.sma(volume, length=length)


def analyze_ta(df: pd.DataFrame) -> dict:
    """Run all TA indicators on a DataFrame with OHLCV columns.

    Args:
        df: DataFrame with columns: open, high, low, close, volume.

    Returns:
        Dict with latest indicator values.
    """
    close = df["close"]
    volume = df["volume"]

    rsi = compute_rsi(close)
    macd_df = compute_macd(close)
    bb = compute_bollinger_bands(close)
    ema_short = compute_ema(close, length=9)
    ema_long = compute_ema(close, length=21)
    vol_sma = compute_volume_sma(volume)

    latest = len(df) - 1

    # MACD column names from pandas-ta
    macd_col = f"MACD_12_26_9"
    macd_signal_col = f"MACDs_12_26_9"
    macd_hist_col = f"MACDh_12_26_9"

    # Bollinger Bands column names
    bbl_col = f"BBL_20_2.0"
    bbm_col = f"BBM_20_2.0"
    bbu_col = f"BBU_20_2.0"

    return {
        "rsi": _safe_float(rsi, latest),
        "macd": _safe_float(macd_df.get(macd_col), latest),
        "macd_signal": _safe_float(macd_df.get(macd_signal_col), latest),
        "macd_histogram": _safe_float(macd_df.get(macd_hist_col), latest),
        "bb_lower": _safe_float(bb.get(bbl_col), latest),
        "bb_middle": _safe_float(bb.get(bbm_col), latest),
        "bb_upper": _safe_float(bb.get(bbu_col), latest),
        "ema_short": _safe_float(ema_short, latest),
        "ema_long": _safe_float(ema_long, latest),
        "volume_sma": _safe_float(vol_sma, latest),
        "current_price": float(close.iloc[latest]),
        "current_volume": float(volume.iloc[latest]),
    }


def _safe_float(series: pd.Series | None, idx: int) -> float | None:
    if series is None:
        return None
    try:
        val = series.iloc[idx]
        if pd.isna(val):
            return None
        return float(val)
    except (IndexError, KeyError):
        return None
