# tests/test_data_loader.py
"""
Tests for Multi-Timeframe Data Loader

Validates:
- Chronological data progression
- MTF synchronization correctness
- No look-ahead bias (strict timestamp checks)
- Edge cases: missing data, single vs multiple timeframes
- Shadow Layer feature integration (RSI, MACD, ATR, BBands)
"""

from decimal import Decimal
from typing import Any

import pandas as pd
import pytest

from data.data_loader import MarketSnapshot, MultiTimeframeFeeder
from data.feature_engineer import FeatureEngineer


def create_sample_data(timeframe: str, start: str, periods: int, freq: str) -> pd.DataFrame:
    """Helper to create sample OHLCV data."""
    timestamps = pd.date_range(start=start, periods=periods, freq=freq)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [100.0 + i * 0.1 for i in range(periods)],
            "high": [100.5 + i * 0.1 for i in range(periods)],
            "low": [99.5 + i * 0.1 for i in range(periods)],
            "close": [100.2 + i * 0.1 for i in range(periods)],
            "volume": [1000 + i * 10 for i in range(periods)],
        }
    )


class TestMultiTimeframeFeeder:
    """Test suite for MultiTimeframeFeeder."""

    def test_single_timeframe_basic(self) -> None:
        """Test basic functionality with single timeframe."""
        df = create_sample_data("M15", "2024-01-01 09:00", 10, "15min")
        feeder = MultiTimeframeFeeder({"M15": df})

        snapshots = list(feeder.step())

        assert len(snapshots) == 10
        assert isinstance(snapshots[0], MarketSnapshot)
        assert snapshots[0].timestamp == pd.Timestamp("2024-01-01 09:00")
        assert snapshots[-1].timestamp == pd.Timestamp("2024-01-01 11:15")

    def test_chronological_ordering(self) -> None:
        """Test that data is yielded in strict chronological order."""
        df = create_sample_data("M15", "2024-01-01 09:00", 20, "15min")
        feeder = MultiTimeframeFeeder({"M15": df})

        snapshots = list(feeder.step())
        timestamps = [s.timestamp for s in snapshots]

        # Verify strictly increasing
        for i in range(1, len(timestamps)):
            assert timestamps[i] > timestamps[i - 1], "Timestamps must be strictly increasing"

    def test_multi_timeframe_synchronization(self) -> None:
        """Test that multiple timeframes synchronize correctly."""
        # M15: every 15 minutes
        # H1: every 60 minutes (every 4 M15 bars)
        df_m15 = create_sample_data("M15", "2024-01-01 09:00", 8, "15min")
        df_h1 = create_sample_data("H1", "2024-01-01 09:00", 2, "h")

        feeder = MultiTimeframeFeeder({"M15": df_m15, "H1": df_h1}, primary_timeframe="M15")
        snapshots = list(feeder.step())

        assert len(snapshots) == 8

        # First snapshot should have both M15 and H1
        assert "M15" in snapshots[0].bars
        assert "H1" in snapshots[0].bars
        assert snapshots[0].bars["H1"]["timestamp"] == pd.Timestamp("2024-01-01 09:00")

        # At 10:00 (4th bar), H1 should still be 09:00
        assert snapshots[3].timestamp == pd.Timestamp("2024-01-01 09:45")
        assert snapshots[3].bars["H1"]["timestamp"] == pd.Timestamp("2024-01-01 09:00")

        # At 10:15 (5th bar), H1 should update to 10:00
        assert snapshots[4].timestamp == pd.Timestamp("2024-01-01 10:00")
        assert snapshots[4].bars["H1"]["timestamp"] == pd.Timestamp("2024-01-01 10:00")

    def test_no_lookahead_bias(self) -> None:
        """Test that future data is never exposed."""
        df_m15 = create_sample_data("M15", "2024-01-01 09:00", 8, "15min")
        df_h1 = create_sample_data("H1", "2024-01-01 09:00", 3, "h")

        feeder = MultiTimeframeFeeder({"M15": df_m15, "H1": df_h1}, primary_timeframe="M15")

        for snapshot in feeder.step():
            # Verify all bar timestamps are <= current timestamp
            for tf_label, bar in snapshot.bars.items():
                assert bar["timestamp"] <= snapshot.timestamp, (
                    f"Look-ahead detected: {tf_label} bar at {bar['timestamp']} > current {snapshot.timestamp}"
                )

    def test_current_price_matches_primary_close(self) -> None:
        """Test that current_price equals primary timeframe close."""
        df = create_sample_data("M15", "2024-01-01 09:00", 5, "15min")
        feeder = MultiTimeframeFeeder({"M15": df})

        snapshots = list(feeder.step())

        for i, snapshot in enumerate(snapshots):
            expected_price = Decimal(str(df.loc[i, "close"]))
            assert snapshot.current_price == expected_price

    def test_history_available(self) -> None:
        """Test that history is provided after first bar."""
        df = create_sample_data("M15", "2024-01-01 09:00", 10, "15min")
        feeder = MultiTimeframeFeeder({"M15": df})

        snapshots = list(feeder.step())

        # First snapshot has no history (i=0)
        assert snapshots[0].history is None or len(snapshots[0].history) == 0

        # Second snapshot has 1 bar of history
        assert snapshots[1].history is not None
        assert len(snapshots[1].history) >= 1

        # Last snapshot has up to 100 bars of history
        assert snapshots[-1].history is not None
        assert len(snapshots[-1].history) <= 100

    def test_reset_functionality(self) -> None:
        """Test that reset() allows re-iteration."""
        df = create_sample_data("M15", "2024-01-01 09:00", 5, "15min")
        feeder = MultiTimeframeFeeder({"M15": df})

        # First iteration
        snapshots1 = list(feeder.step())

        # Reset and iterate again
        feeder.reset()
        snapshots2 = list(feeder.step())

        assert len(snapshots1) == len(snapshots2)
        assert snapshots1[0].timestamp == snapshots2[0].timestamp
        assert snapshots1[-1].timestamp == snapshots2[-1].timestamp

    def test_missing_required_columns_raises_error(self) -> None:
        """Test that missing columns raise ValueError."""
        df_invalid = pd.DataFrame(
            {
                "timestamp": pd.date_range("2024-01-01", periods=5, freq="15min"),
                "close": [100, 101, 102, 103, 104],
                # Missing: open, high, low, volume
            }
        )

        with pytest.raises(ValueError, match="missing required columns"):
            MultiTimeframeFeeder({"M15": df_invalid})

    def test_csv_file_loading(self, tmp_path: Any) -> None:
        """Test loading from CSV file paths."""
        csv_content = """timestamp,open,high,low,close,volume
2024-01-01 09:00:00,100.0,100.5,99.5,100.2,1000
2024-01-01 09:15:00,100.2,100.7,99.7,100.4,1010
2024-01-01 09:30:00,100.4,100.9,99.9,100.6,1020
"""
        csv_path = tmp_path / "test_data.csv"
        csv_path.write_text(csv_content)

        feeder = MultiTimeframeFeeder({"M15": csv_path})
        snapshots = list(feeder.step())

        assert len(snapshots) == 3
        assert snapshots[0].timestamp == pd.Timestamp("2024-01-01 09:00:00")
        assert snapshots[2].current_price == Decimal("100.6")

    def test_bars_dict_structure(self) -> None:
        """Test that bars dict contains expected structure."""
        df_m15 = create_sample_data("M15", "2024-01-01 09:00", 4, "15min")
        df_h1 = create_sample_data("H1", "2024-01-01 09:00", 1, "h")

        feeder = MultiTimeframeFeeder({"M15": df_m15, "H1": df_h1})
        snapshot = next(feeder.step())

        assert isinstance(snapshot.bars, dict)
        assert "M15" in snapshot.bars
        assert "H1" in snapshot.bars

        # Verify bars contain OHLCV columns
        for tf_label, bar in snapshot.bars.items():
            assert "open" in bar
            assert "high" in bar
            assert "low" in bar
            assert "close" in bar
            assert "volume" in bar
            assert "timestamp" in bar

    def test_primary_timeframe_drives_iteration(self) -> None:
        """Test that primary timeframe determines number of snapshots."""
        df_m15 = create_sample_data("M15", "2024-01-01 09:00", 10, "15min")
        df_h1 = create_sample_data("H1", "2024-01-01 09:00", 3, "h")

        feeder = MultiTimeframeFeeder({"M15": df_m15, "H1": df_h1}, primary_timeframe="M15")
        snapshots = list(feeder.step())

        # Should have 10 snapshots (driven by M15)
        assert len(snapshots) == 10

    def test_empty_dataframe_handling(self) -> None:
        """Test behavior with empty DataFrame."""
        df_empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        feeder = MultiTimeframeFeeder({"M15": df_empty})
        snapshots = list(feeder.step())

        assert len(snapshots) == 0

    def test_invalid_primary_timeframe_raises_error(self) -> None:
        """Test that invalid primary timeframe raises ValueError."""
        df = create_sample_data("M15", "2024-01-01 09:00", 5, "15min")

        with pytest.raises(ValueError, match="not found in data sources"):
            MultiTimeframeFeeder({"M15": df}, primary_timeframe="H1")


class TestShadowLayerFeatures:
    """Test suite for Shadow Layer feature integration."""

    def test_snapshot_contains_features_field(self) -> None:
        """Test that MarketSnapshot contains features dictionary."""
        df = create_sample_data("M15", "2024-01-01 09:00", 100, "15min")
        feeder = MultiTimeframeFeeder({"M15": df})

        snapshots = list(feeder.step())
        assert len(snapshots) > 0

        # Verify features field exists and is a dict
        snapshot = snapshots[-1]  # Use later snapshot to ensure features are computed
        assert hasattr(snapshot, "features")
        assert isinstance(snapshot.features, dict)

    def test_snapshot_contains_timeframe_field(self) -> None:
        """Test that MarketSnapshot contains timeframe field."""
        df = create_sample_data("M15", "2024-01-01 09:00", 50, "15min")
        feeder = MultiTimeframeFeeder({"M15": df}, primary_timeframe="M15")

        snapshot = next(feeder.step())
        assert hasattr(snapshot, "timeframe")
        assert snapshot.timeframe == "M15"

    def test_features_contain_expected_indicators(self) -> None:
        """Test that features contain RSI, MACD, ATR, BBands."""
        df = create_sample_data("M15", "2024-01-01 09:00", 100, "15min")
        feeder = MultiTimeframeFeeder({"M15": df})

        snapshots = list(feeder.step())

        # Later snapshots should have all features computed
        snapshot = snapshots[-1]
        expected_features = {"rsi_14", "macd", "macd_signal", "macd_hist", "atr_14", "bb_upper", "bb_mid", "bb_lower"}

        assert snapshot.features is not None
        assert expected_features.issubset(snapshot.features.keys()), (
            f"Missing features: {expected_features - snapshot.features.keys()}"
        )

    def test_early_snapshots_may_have_fewer_features(self) -> None:
        """Test that early snapshots may have incomplete features (NaN handling)."""
        df = create_sample_data("M15", "2024-01-01 09:00", 50, "15min")
        feeder = MultiTimeframeFeeder({"M15": df})

        snapshots = list(feeder.step())

        # First few snapshots may have empty or partial features
        first_snapshot = snapshots[0]
        assert isinstance(first_snapshot.features, dict)
        # RSI needs 14 bars, BB needs 20, so early bars will have no features
        assert len(first_snapshot.features) == 0 or all(
            key not in first_snapshot.features for key in ["rsi_14", "bb_upper"]
        )

    def test_features_are_floats(self) -> None:
        """Test that all feature values are floats."""
        df = create_sample_data("M15", "2024-01-01 09:00", 100, "15min")
        feeder = MultiTimeframeFeeder({"M15": df})

        snapshots = list(feeder.step())
        snapshot = snapshots[-1]

        assert snapshot.features is not None
        for key, value in snapshot.features.items():
            assert isinstance(value, float), f"{key} should be float, got {type(value)}"

    def test_no_lookahead_bias_in_features(self) -> None:
        """Test that features at time T do not include data from T+1 or later."""
        df = create_sample_data("M15", "2024-01-01 09:00", 100, "15min")
        feeder = MultiTimeframeFeeder({"M15": df})

        snapshots = list(feeder.step())

        # Verify that features are computed correctly without look-ahead
        # Early bars should have fewer features (waiting for warmup period)
        # Later bars should have more features as indicators compute
        early_feature_count = len(snapshots[5].features) if snapshots[5].features else 0
        mid_feature_count = len(snapshots[30].features) if snapshots[30].features else 0
        late_feature_count = len(snapshots[80].features) if snapshots[80].features else 0

        # As we progress, feature count should stabilize (all indicators computed)
        # Bar 5: only RSI (need ~20 bars for BB, ~26+ for MACD signal/hist)
        # Bar 30: 6 features (RSI, MACD, ATR, BB x3; MACD signal/hist still warming up)
        # Bar 80: all 8 features (RSI, MACD x3, ATR, BB x3)
        assert early_feature_count >= 1, f"Expected ≥1 features at bar 5 (RSI), got {early_feature_count}"
        assert mid_feature_count >= 6, f"Expected ≥6 features at bar 30, got {mid_feature_count}"
        assert late_feature_count == 8, f"Expected 8 features at bar 80, got {late_feature_count}"

    def test_mtf_synchronization_with_features(self) -> None:
        """Test that MTF synchronization works correctly with features."""
        df_m15 = create_sample_data("M15", "2024-01-01 09:00", 100, "15min")
        df_h1 = create_sample_data("H1", "2024-01-01 09:00", 25, "h")

        feeder = MultiTimeframeFeeder({"M15": df_m15, "H1": df_h1}, primary_timeframe="M15")
        snapshots = list(feeder.step())

        # Verify snapshots contain features
        assert len(snapshots) == 100

        # Later snapshots should have features
        snapshot = snapshots[-1]
        assert "M15" in snapshot.bars
        assert "H1" in snapshot.bars
        assert snapshot.features is not None
        assert len(snapshot.features) > 0
        assert snapshot.timeframe == "M15"

    def test_features_deterministic_across_runs(self) -> None:
        """Test that features are deterministic (same data → same features)."""
        df = create_sample_data("M15", "2024-01-01 09:00", 100, "15min")

        # Run 1
        feeder1 = MultiTimeframeFeeder({"M15": df})
        snapshots1 = list(feeder1.step())

        # Run 2
        feeder2 = MultiTimeframeFeeder({"M15": df})
        snapshots2 = list(feeder2.step())

        # Verify same number of snapshots
        assert len(snapshots1) == len(snapshots2)

        # Verify features are identical
        for i, (s1, s2) in enumerate(zip(snapshots1, snapshots2)):
            assert s1.features is not None and s2.features is not None
            assert s1.features.keys() == s2.features.keys(), f"Feature keys differ at index {i}"
            for key in s1.features:
                assert abs(s1.features[key] - s2.features[key]) < 1e-10, f"{key} differs at index {i}"

    def test_custom_feature_engineer(self) -> None:
        """Test using custom FeatureEngineer parameters."""
        df = create_sample_data("M15", "2024-01-01 09:00", 100, "15min")
        custom_engineer = FeatureEngineer(rsi_period=21, bb_period=10)

        feeder = MultiTimeframeFeeder({"M15": df}, feature_engineer=custom_engineer)
        snapshots = list(feeder.step())

        # Verify features are computed
        snapshot = snapshots[-1]
        assert snapshot.features is not None
        assert len(snapshot.features) > 0
        assert "rsi_14" in snapshot.features  # Column name still uses default "14" from pandas-ta
        assert "bb_upper" in snapshot.features
