"""Tests for strategies.ml_model module."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from coin_trader.strategies.ml_model import (
    MIN_TRAIN_SAMPLES,
    PREDICTION_HORIZON,
    PriceDirectionModel,
)


@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame with enough data for training."""
    np.random.seed(42)
    n = 300
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


@pytest.fixture
def small_df() -> pd.DataFrame:
    np.random.seed(42)
    n = 30  # Too small for training
    close = 90_000_000 + np.cumsum(np.random.randn(n) * 100_000)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1000,
            "low": close - 1000,
            "close": close,
            "volume": np.ones(n),
        }
    )


class TestPriceDirectionModel:
    def test_not_trained_by_default(self) -> None:
        model = PriceDirectionModel()
        assert not model.is_trained

    def test_predict_untrained_returns_zero(self, ohlcv_df: pd.DataFrame) -> None:
        model = PriceDirectionModel()
        direction, conf = model.predict(ohlcv_df)
        assert direction == 0
        assert conf == 0.0

    def test_build_features(self, ohlcv_df: pd.DataFrame) -> None:
        model = PriceDirectionModel()
        features = model.build_features(ohlcv_df)
        assert isinstance(features, pd.DataFrame)
        assert len(features) > 0
        assert "returns_1" in features.columns
        assert "rsi" in features.columns

    def test_build_labels(self, ohlcv_df: pd.DataFrame) -> None:
        model = PriceDirectionModel()
        labels = model.build_labels(ohlcv_df)
        assert isinstance(labels, pd.Series)
        assert set(labels.dropna().unique()).issubset({-1, 0, 1})

    def test_train_success(self, ohlcv_df: pd.DataFrame) -> None:
        model = PriceDirectionModel()
        result = model.train(ohlcv_df)
        assert result is True
        assert model.is_trained

    def test_train_insufficient_data(self, small_df: pd.DataFrame) -> None:
        model = PriceDirectionModel()
        result = model.train(small_df)
        assert result is False
        assert not model.is_trained

    def test_predict_after_training(self, ohlcv_df: pd.DataFrame) -> None:
        model = PriceDirectionModel()
        model.train(ohlcv_df)
        direction, confidence = model.predict(ohlcv_df)
        assert direction in (-1, 0, 1)
        assert 0.0 <= confidence <= 1.0
