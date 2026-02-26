# tests/test_feature_engineer.py
"""
Tests for Shadow Feature Factory (FeatureEngineer)

Validates:
- Technical indicator computation (RSI, MACD, ATR, BBands)
- NaN handling for early bars
- Feature extraction for individual bars
- Deterministic, reproducible outputs
"""

import pandas as pd
import pytest

from data.feature_engineer import FeatureEngineer


def create_sample_ohlcv(periods: int = 100) -> pd.DataFrame:
    """Helper to create sample OHLCV data for testing."""
    timestamps = pd.date_range(start="2024-01-01", periods=periods, freq="15min")
    # Create realistic price movement
    base_price = 100.0
    prices = [base_price + i * 0.1 + (i % 10) * 0.05 for i in range(periods)]

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": prices,
            "high": [p + 0.5 for p in prices],
            "low": [p - 0.5 for p in prices],
            "close": [p + 0.2 for p in prices],
            "volume": [1000 + i * 10 for i in range(periods)],
        }
    )


class TestFeatureEngineer:
    """Test suite for FeatureEngineer."""

    def test_initialization(self) -> None:
        """Test that FeatureEngineer initializes with default parameters."""
        engineer = FeatureEngineer()
        assert engineer.rsi_period == 14
        assert engineer.macd_fast == 12
        assert engineer.macd_slow == 26
        assert engineer.macd_signal == 9
        assert engineer.atr_period == 14
        assert engineer.bb_period == 20
        assert engineer.bb_std == 2.0

    def test_custom_parameters(self) -> None:
        """Test that custom parameters are applied correctly."""
        engineer = FeatureEngineer(
            rsi_period=21,
            macd_fast=5,
            macd_slow=13,
            macd_signal=5,
            atr_period=10,
            bb_period=10,
            bb_std=1.5,
        )
        assert engineer.rsi_period == 21
        assert engineer.macd_fast == 5
        assert engineer.bb_std == 1.5

    def test_compute_features_adds_columns(self) -> None:
        """Test that compute_features adds expected indicator columns."""
        df = create_sample_ohlcv(periods=100)
        engineer = FeatureEngineer()
        enriched = engineer.compute_features(df)

        # Verify original columns are preserved
        assert "timestamp" in enriched.columns
        assert "close" in enriched.columns

        # Verify indicator columns are added
        expected_features = [
            "rsi_14",
            "macd",
            "macd_signal",
            "macd_hist",
            "atr_14",
            "bb_upper",
            "bb_mid",
            "bb_lower",
        ]
        for feat in expected_features:
            assert feat in enriched.columns, f"Missing feature: {feat}"

    def test_rsi_values_in_valid_range(self) -> None:
        """Test that RSI values are in valid range [0, 100]."""
        df = create_sample_ohlcv(periods=100)
        engineer = FeatureEngineer()
        enriched = engineer.compute_features(df)

        # Drop NaN values (early bars)
        rsi_values = enriched["rsi_14"].dropna()
        assert len(rsi_values) > 0, "No valid RSI values computed"
        assert (rsi_values >= 0).all(), "RSI below 0 detected"
        assert (rsi_values <= 100).all(), "RSI above 100 detected"

    def test_nan_handling_early_bars(self) -> None:
        """Test that early bars have NaN for indicators requiring history."""
        df = create_sample_ohlcv(periods=50)
        engineer = FeatureEngineer()
        enriched = engineer.compute_features(df)

        # RSI: pandas-ta computes from bar 0 but bar 0 is NaN
        assert pd.isna(enriched.loc[0, "rsi_14"]), "Expected NaN for RSI at bar 0"
        # Bar 1+ have values (pandas-ta is lenient)
        assert pd.notna(enriched.loc[10, "rsi_14"]), "Expected value for RSI at bar 10"

        # Bollinger Bands need ~20 bars
        assert pd.isna(enriched.loc[0, "bb_upper"]), "Expected NaN for BB at bar 0"
        assert pd.isna(enriched.loc[15, "bb_upper"]), "Expected NaN for BB at bar 15"

        # Later bars should have valid values
        assert pd.notna(enriched.loc[30, "rsi_14"]), "Expected valid RSI at bar 30"
        assert pd.notna(enriched.loc[30, "bb_upper"]), "Expected valid BB at bar 30"

    def test_extract_features_for_bar(self) -> None:
        """Test extracting features dictionary for a specific bar."""
        df = create_sample_ohlcv(periods=100)
        engineer = FeatureEngineer()
        enriched = engineer.compute_features(df)

        # Extract features from a bar with sufficient history
        features = engineer.extract_features_for_bar(enriched, index=50)

        # Verify all expected features are present (non-NaN)
        expected_keys = {"rsi_14", "macd", "macd_signal", "macd_hist", "atr_14", "bb_upper", "bb_mid", "bb_lower"}
        assert expected_keys.issubset(features.keys()), f"Missing features: {expected_keys - features.keys()}"

        # Verify values are floats
        for key, value in features.items():
            assert isinstance(value, float), f"{key} should be float, got {type(value)}"

    def test_extract_features_excludes_nan(self) -> None:
        """Test that NaN values are excluded from extracted features."""
        df = create_sample_ohlcv(periods=30)
        engineer = FeatureEngineer()
        enriched = engineer.compute_features(df)

        # Extract features from early bar (will have some NaNs)
        features = engineer.extract_features_for_bar(enriched, index=5)

        # Verify no NaN values in the dictionary
        for key, value in features.items():
            assert not pd.isna(value), f"{key} should not contain NaN"

        # Some features should be missing entirely (not included in dict)
        # Bollinger Bands should not be present at bar 5 (needs ~20 bars)
        assert "bb_upper" not in features, "BB should not be present at bar 5 (insufficient history)"
        assert "bb_mid" not in features, "BB should not be present at bar 5 (insufficient history)"
        assert "bb_lower" not in features, "BB should not be present at bar 5 (insufficient history)"

    def test_deterministic_output(self) -> None:
        """Test that feature computation is deterministic (same input → same output)."""
        df = create_sample_ohlcv(periods=100)
        engineer = FeatureEngineer()

        # Compute features twice
        enriched1 = engineer.compute_features(df)
        enriched2 = engineer.compute_features(df)

        # Verify results are identical
        pd.testing.assert_frame_equal(enriched1, enriched2)

    def test_missing_columns_raises_error(self) -> None:
        """Test that missing required columns raises ValueError."""
        df = pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=10, freq="15min")})
        engineer = FeatureEngineer()

        with pytest.raises(ValueError, match="missing required columns"):
            engineer.compute_features(df)

    def test_atr_is_positive(self) -> None:
        """Test that ATR values are positive (volatility measure)."""
        df = create_sample_ohlcv(periods=100)
        engineer = FeatureEngineer()
        enriched = engineer.compute_features(df)

        atr_values = enriched["atr_14"].dropna()
        assert len(atr_values) > 0, "No valid ATR values computed"
        assert (atr_values > 0).all(), "ATR should be positive"

    def test_bollinger_bands_ordering(self) -> None:
        """Test that Bollinger Bands maintain proper ordering (lower < mid < upper)."""
        df = create_sample_ohlcv(periods=100)
        engineer = FeatureEngineer()
        enriched = engineer.compute_features(df)

        # Check bars with all valid BB values
        valid_bb = enriched.dropna(subset=["bb_lower", "bb_mid", "bb_upper"])
        assert len(valid_bb) > 0, "No valid BB values"

        for idx, row in valid_bb.iterrows():
            assert row["bb_lower"] < row["bb_mid"], f"BB lower >= mid at index {idx}"
            assert row["bb_mid"] < row["bb_upper"], f"BB mid >= upper at index {idx}"

    def test_macd_histogram_calculation(self) -> None:
        """Test that MACD histogram equals MACD - Signal."""
        df = create_sample_ohlcv(periods=100)
        engineer = FeatureEngineer()
        enriched = engineer.compute_features(df)

        # Check bars with all valid MACD values
        valid_macd = enriched.dropna(subset=["macd", "macd_signal", "macd_hist"])
        assert len(valid_macd) > 0, "No valid MACD values"

        for idx, row in valid_macd.iterrows():
            expected_hist = row["macd"] - row["macd_signal"]
            assert abs(row["macd_hist"] - expected_hist) < 1e-6, f"MACD histogram mismatch at index {idx}"
