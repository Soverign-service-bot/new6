# data/feature_engineer.py
"""
Shadow Feature Factory for QEFC

Computes technical indicators using pandas-ta.
Enriches market snapshots with features in the Shadow Layer.
"""

from typing import Dict

import pandas as pd
import pandas_ta as ta


class FeatureEngineer:
    """
    Technical indicator computation engine.

    Computes a standard set of indicators (RSI, MACD, ATR, Bollinger Bands)
    and returns them as a dictionary of features for each bar.

    Example:
        >>> df = pd.DataFrame({"open": [...], "high": [...], "low": [...], "close": [...], "volume": [...]})
        >>> engineer = FeatureEngineer()
        >>> enriched_df = engineer.compute_features(df)
        >>> print(enriched_df[["close", "rsi_14", "macd", "atr_14"]].tail())
    """

    def __init__(
        self,
        rsi_period: int = 14,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        atr_period: int = 14,
        bb_period: int = 20,
        bb_std: float = 2.0,
    ) -> None:
        """
        Initialize feature engineer with indicator parameters.

        Args:
            rsi_period: Period for RSI calculation (default: 14)
            macd_fast: Fast EMA period for MACD (default: 12)
            macd_slow: Slow EMA period for MACD (default: 26)
            macd_signal: Signal line period for MACD (default: 9)
            atr_period: Period for ATR calculation (default: 14)
            bb_period: Period for Bollinger Bands (default: 20)
            bb_std: Standard deviations for Bollinger Bands (default: 2.0)
        """
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.atr_period = atr_period
        self.bb_period = bb_period
        self.bb_std = bb_std

    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute technical indicators and add as columns to DataFrame.

        Args:
            df: DataFrame with OHLCV columns (open, high, low, close, volume)

        Returns:
            DataFrame with added feature columns:
                - rsi_14: Relative Strength Index
                - macd: MACD line
                - macd_signal: MACD signal line
                - macd_hist: MACD histogram
                - atr_14: Average True Range
                - bb_upper: Bollinger Band upper
                - bb_mid: Bollinger Band middle (SMA)
                - bb_lower: Bollinger Band lower

        Note:
            Early bars will have NaN values until sufficient history is available.
            Callers should handle NaN appropriately (forward-fill, drop, or use placeholder).
        """
        # Validate required columns
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(df.columns):
            raise ValueError(f"DataFrame missing required columns. Expected: {required}, got: {set(df.columns)}")

        # Make a copy to avoid modifying original
        enriched = df.copy()

        # Compute RSI
        enriched["rsi_14"] = ta.rsi(enriched["close"], length=self.rsi_period)

        # Compute MACD
        macd_result = ta.macd(
            enriched["close"],
            fast=self.macd_fast,
            slow=self.macd_slow,
            signal=self.macd_signal,
        )
        if macd_result is not None:
            enriched["macd"] = macd_result[f"MACD_{self.macd_fast}_{self.macd_slow}_{self.macd_signal}"]
            enriched["macd_signal"] = macd_result[f"MACDs_{self.macd_fast}_{self.macd_slow}_{self.macd_signal}"]
            enriched["macd_hist"] = macd_result[f"MACDh_{self.macd_fast}_{self.macd_slow}_{self.macd_signal}"]

        # Compute ATR
        enriched["atr_14"] = ta.atr(
            enriched["high"],
            enriched["low"],
            enriched["close"],
            length=self.atr_period,
        )

        # Compute Bollinger Bands
        bb_result = ta.bbands(
            enriched["close"],
            length=self.bb_period,
            lower_std=self.bb_std,
            upper_std=self.bb_std,
        )
        if bb_result is not None:
            # pandas-ta returns columns like BBL_20_2.0_2.0 (with extra suffix)
            # Find the actual column names dynamically
            bb_cols = {col: col for col in bb_result.columns}
            for col in bb_cols:
                if col.startswith(f"BBL_{self.bb_period}"):
                    enriched["bb_lower"] = bb_result[col]
                elif col.startswith(f"BBM_{self.bb_period}"):
                    enriched["bb_mid"] = bb_result[col]
                elif col.startswith(f"BBU_{self.bb_period}"):
                    enriched["bb_upper"] = bb_result[col]

        return enriched

    def extract_features_for_bar(self, enriched_df: pd.DataFrame, index: int) -> Dict[str, float]:
        """
        Extract features dictionary for a specific bar.

        Args:
            enriched_df: DataFrame with computed features (output of compute_features)
            index: Row index to extract features from

        Returns:
            Dictionary of feature name -> value (e.g., {"rsi_14": 65.3, "atr_14": 0.0045})
            NaN values are excluded from the dictionary.
        """
        feature_cols = [
            "rsi_14",
            "macd",
            "macd_signal",
            "macd_hist",
            "atr_14",
            "bb_upper",
            "bb_mid",
            "bb_lower",
        ]

        features = {}
        for col in feature_cols:
            if col in enriched_df.columns:
                value = enriched_df.loc[index, col]
                # Only include non-NaN values
                if pd.notna(value):
                    features[col] = float(value)

        return features
