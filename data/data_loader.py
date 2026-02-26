# data/data_loader.py
"""
Multi-Timeframe Data Loader for Sovereign-Quant

Provides bar-by-bar simulation with strict timestamp alignment
to prevent look-ahead bias across multiple timeframes.
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Dict, Iterator, Optional, Union

import pandas as pd

from data.feature_engineer import FeatureEngineer


@dataclass(frozen=True)
class MarketSnapshot:
    """
    Synchronized multi-timeframe market state at a specific timestamp.

    Attributes:
        timestamp: Current simulation timestamp
        current_price: Most recent close price
        bars: Dict of current bar data for each timeframe (e.g., {"M15": pd.Series, "H1": pd.Series})
        history: Optional recent history DataFrame (for lookback features)
        features: Dict of technical indicators computed in Shadow Layer (e.g., {"rsi_14": 65.3})
        timeframe: Primary timeframe for this snapshot (e.g., "M15", "H1", "H4")
    """

    timestamp: pd.Timestamp
    current_price: Decimal
    bars: Dict[str, pd.Series]
    history: Optional[pd.DataFrame] = None
    features: Optional[Dict[str, float]] = None
    timeframe: str = "M15"

    def __post_init__(self) -> None:
        """Initialize mutable defaults properly."""
        if self.features is None:
            object.__setattr__(self, "features", {})


class MultiTimeframeFeeder:
    """
    Generator-based multi-timeframe data loader.

    Loads OHLCV data for multiple timeframes and yields synchronized
    MarketSnapshot objects in strict chronological order.

    Prevents look-ahead bias by only exposing data that would be
    available at each timestamp in real-time.

    Example:
        >>> data_m15 = pd.read_csv("EURUSD_M15.csv", parse_dates=["timestamp"])
        >>> data_h1 = pd.read_csv("EURUSD_H1.csv", parse_dates=["timestamp"])
        >>> feeder = MultiTimeframeFeeder({"M15": data_m15, "H1": data_h1})
        >>> for snapshot in feeder.step():
        ...     print(snapshot.timestamp, snapshot.current_price)
    """

    def __init__(
        self,
        data_sources: Dict[str, Union[pd.DataFrame, Path, str]],
        primary_timeframe: Optional[str] = None,
        feature_engineer: Optional[FeatureEngineer] = None,
    ):
        """
        Initialize multi-timeframe feeder.

        Args:
            data_sources: Dict mapping timeframe label to DataFrame or CSV path.
                         Each DataFrame must have columns: timestamp, open, high, low, close, volume
            primary_timeframe: Which timeframe drives the simulation (default: smallest/first)
            feature_engineer: Optional FeatureEngineer to compute technical indicators.
                             If None, features will be empty dict.

        Raises:
            ValueError: If data is invalid or timeframes don't align
        """
        self.data: Dict[str, pd.DataFrame] = {}
        self.primary_timeframe: str = primary_timeframe or ""
        self.feature_engineer = feature_engineer or FeatureEngineer()

        # Load and validate all data sources
        for tf_label, source in data_sources.items():
            if isinstance(source, pd.DataFrame):
                df = source.copy()
            else:
                df = pd.read_csv(source, parse_dates=["timestamp"])

            # Validate required columns
            required_cols = {"timestamp", "open", "high", "low", "close", "volume"}
            if not required_cols.issubset(df.columns):
                raise ValueError(
                    f"Timeframe {tf_label} missing required columns. Expected: {required_cols}, got: {set(df.columns)}"
                )

            # Sort by timestamp and reset index
            df = df.sort_values("timestamp").reset_index(drop=True)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            self.data[tf_label] = df

        # Determine primary timeframe if not specified
        if not self.primary_timeframe:
            self.primary_timeframe = list(self.data.keys())[0]

        if self.primary_timeframe not in self.data:
            raise ValueError(f"Primary timeframe '{self.primary_timeframe}' not found in data sources")

        # Pre-compute features for all timeframes using Shadow Layer
        self._enriched_data: Dict[str, pd.DataFrame] = {}
        for tf_label, df in self.data.items():
            self._enriched_data[tf_label] = self.feature_engineer.compute_features(df)

        # Initialize position indices for each timeframe
        self._positions: Dict[str, int] = {tf: 0 for tf in self.data.keys()}

    def step(self) -> Iterator[MarketSnapshot]:
        """
        Generator that yields MarketSnapshot objects in chronological order.

        Each snapshot includes pre-computed technical indicators in the Shadow Layer.

        Yields:
            MarketSnapshot: Synchronized market state at each timestamp with features
        """
        primary_df = self.data[self.primary_timeframe]
        primary_enriched = self._enriched_data[self.primary_timeframe]

        for i in range(len(primary_df)):
            current_timestamp = primary_df.loc[i, "timestamp"]
            current_bar = primary_df.iloc[i]

            # Advance all other timeframes to align with current timestamp
            # (only show bars that have completed by this timestamp)
            aligned_bars: Dict[str, pd.Series] = {self.primary_timeframe: current_bar}

            for tf_label, df in self.data.items():
                if tf_label == self.primary_timeframe:
                    continue

                # Find the most recent bar that completed before/at current_timestamp
                pos = self._positions[tf_label]
                while pos < len(df) - 1 and df.loc[pos + 1, "timestamp"] <= current_timestamp:
                    pos += 1
                self._positions[tf_label] = pos

                # Only include if we have valid data at this position
                if pos < len(df) and df.loc[pos, "timestamp"] <= current_timestamp:
                    aligned_bars[tf_label] = df.iloc[pos]

            # Build current price from primary timeframe close
            current_price = Decimal(str(current_bar["close"]))

            # Optional: Build history (last N bars from primary timeframe)
            history = None
            if i > 0:
                history = primary_df.iloc[max(0, i - 100) : i].copy()

            # Extract features from enriched data for current bar
            features = self.feature_engineer.extract_features_for_bar(primary_enriched, i)

            yield MarketSnapshot(
                timestamp=current_timestamp,
                current_price=current_price,
                bars=aligned_bars,
                history=history,
                features=features,
                timeframe=self.primary_timeframe,
            )

    def reset(self) -> None:
        """Reset the feeder to the beginning."""
        self._positions = {tf: 0 for tf in self.data.keys()}
