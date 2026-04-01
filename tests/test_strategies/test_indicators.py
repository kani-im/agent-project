"""Tests for strategies.indicators module."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from coin_trader.strategies.indicators import (
    _safe_float,
    analyze_ta,
    compute_bollinger_bands,
    compute_ema,
    compute_macd,
    compute_rsi,
    compute_volume_sma,
)


@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame with 200 rows."""
    np.random.seed(42)
    n = 200
    close = 90_000_000 + np.cumsum(np.random.randn(n) * 100_000)
    return pd.DataFrame(
        {
            "open": close - np.random.rand(n) * 50_000,
            "high": close + np.random.rand(n) * 100_000,
            "low": close - np.random.rand(n) * 100_000,
            "close": close,
            "volume": np.random.rand(n) * 10 + 1,
        }
    )


class TestComputeRSI:
    def test_returns_series(self, ohlcv_df: pd.DataFrame) -> None:
        rsi = compute_rsi(ohlcv_df["close"])
        assert isinstance(rsi, pd.Series)
        assert len(rsi) == len(ohlcv_df)

    def test_values_in_range(self, ohlcv_df: pd.DataFrame) -> None:
        rsi = compute_rsi(ohlcv_df["close"])
        valid = rsi.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()


class TestComputeMACD:
    def test_returns_dataframe(self, ohlcv_df: pd.DataFrame) -> None:
        macd_df = compute_macd(ohlcv_df["close"])
        assert isinstance(macd_df, pd.DataFrame)
        assert "MACD_12_26_9" in macd_df.columns


class TestComputeBollingerBands:
    def test_returns_dataframe(self, ohlcv_df: pd.DataFrame) -> None:
        bb = compute_bollinger_bands(ohlcv_df["close"])
        assert isinstance(bb, pd.DataFrame)
        # Column names vary by pandas-ta version (BBU_20_2.0 or BBU_20_2.0_2.0)
        bbu_cols = [c for c in bb.columns if c.startswith("BBU")]
        bbl_cols = [c for c in bb.columns if c.startswith("BBL")]
        assert len(bbu_cols) == 1
        assert len(bbl_cols) == 1

    def test_upper_above_lower(self, ohlcv_df: pd.DataFrame) -> None:
        bb = compute_bollinger_bands(ohlcv_df["close"])
        valid = bb.dropna()
        bbu_col = [c for c in bb.columns if c.startswith("BBU")][0]
        bbl_col = [c for c in bb.columns if c.startswith("BBL")][0]
        assert (valid[bbu_col] >= valid[bbl_col]).all()


class TestComputeEMA:
    def test_returns_series(self, ohlcv_df: pd.DataFrame) -> None:
        ema = compute_ema(ohlcv_df["close"], length=20)
        assert isinstance(ema, pd.Series)
        assert len(ema) == len(ohlcv_df)


class TestComputeVolumeSMA:
    def test_returns_series(self, ohlcv_df: pd.DataFrame) -> None:
        sma = compute_volume_sma(ohlcv_df["volume"], length=20)
        assert isinstance(sma, pd.Series)


class TestAnalyzeTA:
    def test_returns_dict_with_expected_keys(self, ohlcv_df: pd.DataFrame) -> None:
        result = analyze_ta(ohlcv_df)
        expected_keys = {
            "rsi", "macd", "macd_signal", "macd_histogram",
            "bb_lower", "bb_middle", "bb_upper",
            "ema_short", "ema_long", "volume_sma",
            "current_price", "current_volume",
        }
        assert expected_keys == set(result.keys())

    def test_current_price_matches_last_close(self, ohlcv_df: pd.DataFrame) -> None:
        result = analyze_ta(ohlcv_df)
        assert result["current_price"] == float(ohlcv_df["close"].iloc[-1])


class TestSafeFloat:
    def test_valid_value(self) -> None:
        s = pd.Series([1.0, 2.0, 3.0])
        assert _safe_float(s, 1) == 2.0

    def test_nan_value(self) -> None:
        s = pd.Series([1.0, float("nan"), 3.0])
        assert _safe_float(s, 1) is None

    def test_none_series(self) -> None:
        assert _safe_float(None, 0) is None

    def test_out_of_bounds(self) -> None:
        s = pd.Series([1.0])
        assert _safe_float(s, 10) is None
