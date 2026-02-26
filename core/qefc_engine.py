# core/qefc_engine.py
"""
QEFC Meta-Engine — Epistemic Capital Governor

Implements the Quaternary Logic Framework (QLF) state machine.
Base epistemic states: {T, C, N, F}
Supervisory override: W (Withdrawal)

Doctrine constraints (ORG_DOCTRINE v2.2.2):
- Core logic ≤ 300 LOC
- Dimensional compression: < 10 meta-features before state collapse
- QEFC does NOT: size positions, execute orders, apply risk veto

QEFC-010: Sprint 2 Implementation
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import List

from core.types import (
    AgentSignal,
    PortfolioState,
    QEFCDecision,
    QEFCState,
    RegimeInfo,
)

# ============================================================
# SUPERVISOR STATE (Cooldown & W-Lock Tracker)
# ============================================================


@dataclass
class SupervisorState:
    """
    External state tracker for cooldown and W-lock.

    Separated from pure signal fusion logic per QEFC topology.
    QEFCEngine reads this but does not reset W without supervisor rules.
    """

    previous_final_state: QEFCState = QEFCState.N
    bars_since_W: int = 999  # Large default = no recent W
    bars_since_F: int = 999  # Large default = no recent F
    W_lock: bool = False


# ============================================================
# COMPRESSED META-FEATURES (< 10 dimensions)
# ============================================================


@dataclass
class _CompressedMeta:
    """
    Dimensional compression for QEFC state collapse.

    Total: 9 dimensions (under 10 limit per v2.2.2 §III).
    """

    consensus_score: float  # 1. Weighted signal agreement [-1, 1]
    conflict_intensity: float  # 2. Signal disagreement [0, 1]
    regime_confidence: float  # 3. From RegimeInfo
    divergence_score: float  # 4. From RegimeInfo
    drawdown_pct: float  # 5. From PortfolioState
    equity_floor_breach: bool  # 6. From PortfolioState
    volatility_anomaly: bool  # 7. Derived flag
    bars_since_W: int  # 8. Cooldown tracking (read-only)
    bars_since_F: int  # 9. Cooldown tracking (read-only)


# ============================================================
# QEFC ENGINE
# ============================================================


class QEFCEngine:
    """
    QEFC Meta-Engine — Epistemic Capital Governor.

    Implements QLF state machine with:
    - Signal fusion → base states {T, C, N, F}
    - W supervisory override (risk_factor = 0.0)
    - F→T forbidden (irreversibility)
    - Cooldown after W or F before T allowed
    """

    # Risk factor mapping for each state
    _STATE_RISK_FACTORS: dict[QEFCState, float] = {
        QEFCState.T: 1.0,  # Full allocation
        QEFCState.C: 0.5,  # Half-risk / hedge
        QEFCState.N: 0.0,  # Wait
        QEFCState.F: 0.0,  # Withdraw
        QEFCState.W: 0.0,  # Emergency override
    }

    def __init__(
        self,
        consensus_threshold_high: float = 0.7,
        consensus_threshold_low: float = -0.3,
        conflict_threshold: float = 0.5,
        max_drawdown_pct: float = 10.0,
        divergence_threshold: float = 0.8,
        cooldown_bars: int = 4,
    ) -> None:
        """
        Initialize QEFC Engine with configurable thresholds.

        Args:
            consensus_threshold_high: Score above which → T
            consensus_threshold_low: Score below which → F
            conflict_threshold: Intensity above which → C
            max_drawdown_pct: Drawdown % to trigger W
            divergence_threshold: Divergence score to trigger W
            cooldown_bars: Bars to wait after W or F before T allowed
        """
        self._consensus_high = consensus_threshold_high
        self._consensus_low = consensus_threshold_low
        self._conflict_threshold = conflict_threshold
        self._max_drawdown_pct = max_drawdown_pct
        self._divergence_threshold = divergence_threshold
        self._cooldown_bars = cooldown_bars
        self._supervisor = SupervisorState()

    def evaluate(
        self,
        signals: List[AgentSignal],
        regime: RegimeInfo,
        portfolio: PortfolioState,
    ) -> QEFCDecision:
        """
        Core method — returns QEFC decision.

        Algorithm:
        1. Dimensional compression (< 10 features)
        2. Check W override (supervisory authority)
        3. Signal fusion → base state {T, C, N, F}
        4. Apply F→T transition block (irreversibility)
        5. Apply cooldown barriers
        6. Emit decision and update supervisor
        """
        # 1. Dimensional Compression
        meta = self._compress_inputs(signals, regime, portfolio)

        # 2. Check W Override (Supervisory Authority)
        w_reason = self._check_w_trigger(meta)
        if w_reason:
            return self._emit_w(w_reason)

        # 3. Signal Fusion → Base State {T, C, N, F}
        fused_state = self._fuse_signals(meta)
        reason_codes: list[str] = []

        # 4. Apply F→T Transition Block (Irreversibility)
        if self._supervisor.previous_final_state == QEFCState.F and fused_state == QEFCState.T:
            fused_state = QEFCState.N
            reason_codes.append("F_TO_T_BLOCKED")

        # 5. Apply Cooldown Barriers
        if fused_state == QEFCState.T:
            if self._supervisor.bars_since_W < self._cooldown_bars:
                fused_state = QEFCState.N
                reason_codes.append("W_COOLDOWN_ACTIVE")
            elif self._supervisor.bars_since_F < self._cooldown_bars:
                fused_state = QEFCState.N
                reason_codes.append("F_COOLDOWN_ACTIVE")

        # 6. Emit Decision
        final_state = fused_state
        risk_factor = self._STATE_RISK_FACTORS[final_state]
        cooldown_remaining = max(
            0,
            self._cooldown_bars - min(self._supervisor.bars_since_W, self._supervisor.bars_since_F),
        )

        decision = QEFCDecision(
            state=final_state,
            risk_factor=risk_factor,
            reason_codes=reason_codes,
            cooldown_bars=cooldown_remaining,
            timestamp=datetime.now(UTC),
        )

        # 7. Update Supervisor State
        self._update_supervisor(final_state)

        return decision

    def _compress_inputs(
        self,
        signals: List[AgentSignal],
        regime: RegimeInfo,
        portfolio: PortfolioState,
    ) -> _CompressedMeta:
        """Dimensional compression to < 10 features."""
        # Compute consensus score: weighted average of signal intents
        # LONG = +1, SHORT = -1, NEUTRAL = 0
        intent_values: list[float] = []
        weights: list[float] = []
        for sig in signals:
            if sig.intent == "LONG":
                intent_values.append(1.0)
            elif sig.intent == "SHORT":
                intent_values.append(-1.0)
            else:
                intent_values.append(0.0)
            weights.append(sig.confidence)

        if weights and sum(weights) > 0:
            consensus_score = sum(v * w for v, w in zip(intent_values, weights)) / sum(weights)
        else:
            consensus_score = 0.0

        # Compute conflict intensity: std of intents (simplified)
        if len(intent_values) > 1:
            mean_intent = sum(intent_values) / len(intent_values)
            variance = sum((v - mean_intent) ** 2 for v in intent_values) / len(intent_values)
            conflict_intensity = variance**0.5
        else:
            conflict_intensity = 0.0

        # Volatility anomaly: high divergence or low regime confidence
        volatility_anomaly = (
            regime.confidence < 0.5,
            (regime.divergence_score or 0.0) > 0.6,
        )

        return _CompressedMeta(
            consensus_score=consensus_score,
            conflict_intensity=conflict_intensity,
            regime_confidence=regime.confidence,
            divergence_score=regime.divergence_score or 0.0,
            drawdown_pct=portfolio.drawdown_pct,
            equity_floor_breach=portfolio.equity_floor_breach,
            volatility_anomaly=any(volatility_anomaly),
            bars_since_W=self._supervisor.bars_since_W,
            bars_since_F=self._supervisor.bars_since_F,
        )

    def _check_w_trigger(self, meta: _CompressedMeta) -> str | None:
        """Check W override conditions. Returns trigger reason or None."""
        if meta.drawdown_pct > self._max_drawdown_pct:
            return "DRAWDOWN_BREACH"
        if meta.divergence_score > self._divergence_threshold:
            return "DIVERGENCE_BREACH"
        if meta.equity_floor_breach:
            return "EQUITY_FLOOR_BREACH"
        return None

    def _fuse_signals(self, meta: _CompressedMeta) -> QEFCState:
        """Pure signal fusion → base state {T, C, N, F}."""
        # High conflict → C
        if meta.conflict_intensity > self._conflict_threshold:
            return QEFCState.C

        # High consensus → T
        if meta.consensus_score > self._consensus_high:
            return QEFCState.T

        # Low consensus → F
        if meta.consensus_score < self._consensus_low:
            return QEFCState.F

        # Default → N (neutral/wait)
        return QEFCState.N

    def _emit_w(self, trigger_reason: str) -> QEFCDecision:
        """Emit W decision and update supervisor."""
        decision = QEFCDecision(
            state=QEFCState.W,
            risk_factor=0.0,
            reason_codes=["W_OVERRIDE", trigger_reason],
            cooldown_bars=self._cooldown_bars,
            timestamp=datetime.now(UTC),
        )
        self._update_supervisor(QEFCState.W)
        return decision

    def _update_supervisor(self, final_state: QEFCState) -> None:
        """Update supervisor state after decision."""
        # Increment all cooldown counters
        self._supervisor.bars_since_W += 1
        self._supervisor.bars_since_F += 1

        # Reset relevant counter based on final state
        if final_state == QEFCState.W:
            self._supervisor.bars_since_W = 0
            self._supervisor.W_lock = True
        elif final_state == QEFCState.F:
            self._supervisor.bars_since_F = 0

        # Update previous state
        self._supervisor.previous_final_state = final_state

    @property
    def supervisor_state(self) -> SupervisorState:
        """Read-only access to supervisor state (for testing/inspection)."""
        return self._supervisor

    def reset(self) -> None:
        """Reset engine state (for testing)."""
        self._supervisor = SupervisorState()
