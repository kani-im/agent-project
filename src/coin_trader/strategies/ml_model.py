"""Lightweight ML model for price direction prediction."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler

from coin_trader.core.logging import get_logger
from coin_trader.strategies.indicators import (
    compute_bollinger_bands,
    compute_ema,
    compute_macd,
    compute_rsi,
)

log = get_logger(__name__)

# Minimum number of candles required for training
MIN_TRAIN_SAMPLES = 100

# Prediction horizon: N candles ahead
PREDICTION_HORIZON = 5


class PriceDirectionModel:
    """GradientBoosting classifier predicting price direction (up/down/neutral)."""

    def __init__(self) -> None:
        self._model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=3,
            learning_rate=0.1,
            random_state=42,
        )
        self._scaler = StandardScaler()
        self._is_trained = False

    @property
    def is_trained(self) -> bool:
        return self._is_trained

    def build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Build feature matrix from OHLCV DataFrame."""
        close = df["close"]
        volume = df["volume"]

        features = pd.DataFrame(index=df.index)

        # Price-based features
        features["returns_1"] = close.pct_change(1)
        features["returns_5"] = close.pct_change(5)
        features["returns_10"] = close.pct_change(10)

        # Volatility
        features["volatility_10"] = close.pct_change().rolling(10).std()

        # RSI
        rsi = compute_rsi(close, length=14)
        if rsi is not None:
            features["rsi"] = rsi

        # MACD
        macd_df = compute_macd(close)
        if macd_df is not None:
            features["macd_hist"] = macd_df.get("MACDh_12_26_9")

        # Bollinger Bands %b
        bb = compute_bollinger_bands(close)
        if bb is not None:
            bbu = bb.get("BBU_20_2.0")
            bbl = bb.get("BBL_20_2.0")
            if bbu is not None and bbl is not None:
                bb_range = bbu - bbl
                bb_range = bb_range.replace(0, np.nan)
                features["bb_pct"] = (close - bbl) / bb_range

        # EMA crossover
        ema_short = compute_ema(close, length=9)
        ema_long = compute_ema(close, length=21)
        if ema_short is not None and ema_long is not None:
            features["ema_diff"] = (ema_short - ema_long) / ema_long

        # Volume features
        vol_mean = volume.rolling(20).mean()
        vol_mean = vol_mean.replace(0, np.nan)
        features["volume_ratio"] = volume / vol_mean

        return features.dropna()

    def build_labels(self, df: pd.DataFrame) -> pd.Series:
        """Build labels: 1 (up), 0 (neutral), -1 (down) based on future returns."""
        future_returns = df["close"].pct_change(PREDICTION_HORIZON).shift(
            -PREDICTION_HORIZON
        )
        threshold = 0.005  # 0.5% threshold

        labels = pd.Series(0, index=df.index)
        labels[future_returns > threshold] = 1
        labels[future_returns < -threshold] = -1
        return labels

    def train(self, df: pd.DataFrame) -> bool:
        """Train the model on historical OHLCV data.

        Returns True if training succeeded.
        """
        if len(df) < MIN_TRAIN_SAMPLES:
            log.warning("ml_insufficient_data", rows=len(df))
            return False

        features = self.build_features(df)
        labels = self.build_labels(df).loc[features.index]

        # Drop rows with NaN labels (last PREDICTION_HORIZON rows)
        mask = labels.notna()
        features = features[mask]
        labels = labels[mask]

        if len(features) < 50:
            return False

        X = features.values
        y = labels.values.astype(int)

        self._scaler.fit(X)
        X_scaled = self._scaler.transform(X)

        self._model.fit(X_scaled, y)
        self._is_trained = True

        accuracy = self._model.score(X_scaled, y)
        log.info("ml_model_trained", samples=len(X), accuracy=round(accuracy, 4))
        return True

    def predict(self, df: pd.DataFrame) -> tuple[int, float]:
        """Predict direction for the latest data point.

        Returns:
            Tuple of (direction: -1/0/1, confidence: 0.0-1.0).
        """
        if not self._is_trained:
            return 0, 0.0

        features = self.build_features(df)
        if features.empty:
            return 0, 0.0

        X = features.iloc[[-1]].values
        X_scaled = self._scaler.transform(X)

        prediction = int(self._model.predict(X_scaled)[0])
        probabilities = self._model.predict_proba(X_scaled)[0]
        confidence = float(max(probabilities))

        return prediction, confidence
