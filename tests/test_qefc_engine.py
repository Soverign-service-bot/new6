# tests/test_qefc_engine.py
"""
Unit tests for QEFC Meta-Engine (core/qefc_engine.py).

QEFC-010: Sprint 2 Implementation Tests

Mandatory test cases per Handoff 1:
1. Signal fusion → base states {T, C, N, F}
2. W supervisory override (risk_factor = 0.0)
3. F→T forbidden (irreversibility)
4. Cooldown after W or F before T allowed
"""

from core.qefc_engine import QEFCEngine, _CompressedMeta
from core.types import (
    AgentSignal,
    PortfolioState,
    QEFCState,
    RegimeInfo,
)

# ============================================================
# TEST FIXTURES
# ============================================================


def make_signal(
    intent: str = "LONG",
    confidence: float = 0.8,
    agent_name: str = "TestAgent",
    symbol: str = "XAUUSD",
) -> AgentSignal:
    """Helper to create AgentSignal for testing."""
    return AgentSignal(
        agent_name=agent_name,
        symbol=symbol,
        intent=intent,  # type: ignore[arg-type]
        confidence=confidence,
        invalidation_price=None,
    )


def make_regime(
    confidence: float = 0.8,
    divergence_score: float = 0.3,
    label: str = "TREND_RUN",
) -> RegimeInfo:
    """Helper to create RegimeInfo for testing."""
    return RegimeInfo(
        regime_label=label,
        confidence=confidence,
        divergence_score=divergence_score,
    )


def make_portfolio(
    drawdown_pct: float = 2.0,
    equity_floor_breach: bool = False,
) -> PortfolioState:
    """Helper to create PortfolioState for testing."""
    return PortfolioState(
        equity=100000.0,
        balance=100000.0,
        drawdown_pct=drawdown_pct,
        open_positions=0,
        margin_used_pct=0.0,
        equity_floor_breach=equity_floor_breach,
    )


# ============================================================
# TEST: SIGNAL FUSION
# ============================================================


class TestSignalFusion:
    """Test base state inference {T, C, N, F}."""

    def test_high_consensus_returns_T(self) -> None:
        """High consensus (all LONG with high confidence) → T."""
        engine = QEFCEngine()
        signals = [
            make_signal(intent="LONG", confidence=0.9),
            make_signal(intent="LONG", confidence=0.85),
            make_signal(intent="LONG", confidence=0.8),
        ]
        regime = make_regime()
        portfolio = make_portfolio()

        decision = engine.evaluate(signals, regime, portfolio)

        assert decision.state == QEFCState.T
        assert decision.risk_factor == 1.0

    def test_high_conflict_returns_C(self) -> None:
        """High conflict (mixed LONG/SHORT) → C."""
        engine = QEFCEngine(conflict_threshold=0.5)
        signals = [
            make_signal(intent="LONG", confidence=0.9),
            make_signal(intent="SHORT", confidence=0.9),
        ]
        regime = make_regime()
        portfolio = make_portfolio()

        decision = engine.evaluate(signals, regime, portfolio)

        assert decision.state == QEFCState.C
        assert decision.risk_factor == 0.5

    def test_low_consensus_returns_F(self) -> None:
        """Low consensus (all SHORT with high confidence) → F."""
        engine = QEFCEngine()
        signals = [
            make_signal(intent="SHORT", confidence=0.9),
            make_signal(intent="SHORT", confidence=0.85),
        ]
        regime = make_regime()
        portfolio = make_portfolio()

        decision = engine.evaluate(signals, regime, portfolio)

        assert decision.state == QEFCState.F
        assert decision.risk_factor == 0.0

    def test_uncertain_returns_N(self) -> None:
        """Uncertain signals (NEUTRAL or weak) → N."""
        engine = QEFCEngine()
        signals = [
            make_signal(intent="NEUTRAL", confidence=0.5),
            make_signal(intent="NEUTRAL", confidence=0.5),
        ]
        regime = make_regime()
        portfolio = make_portfolio()

        decision = engine.evaluate(signals, regime, portfolio)

        assert decision.state == QEFCState.N
        assert decision.risk_factor == 0.0

    def test_empty_signals_returns_N(self) -> None:
        """No signals → N (wait)."""
        engine = QEFCEngine()
        signals: list[AgentSignal] = []
        regime = make_regime()
        portfolio = make_portfolio()

        decision = engine.evaluate(signals, regime, portfolio)

        assert decision.state == QEFCState.N
        assert decision.risk_factor == 0.0


# ============================================================
# TEST: W OVERRIDE
# ============================================================


class TestWOverride:
    """Test W supervisory override behavior."""

    def test_W_overrides_T_on_high_drawdown(self) -> None:
        """
        MANDATORY: Even with perfect consensus (would be T),
        W triggers when drawdown_pct > threshold.
        Result: risk_factor = 0.0
        """
        engine = QEFCEngine(max_drawdown_pct=10.0)
        # Perfect consensus signals → would be T
        signals = [
            make_signal(intent="LONG", confidence=0.95),
            make_signal(intent="LONG", confidence=0.9),
        ]
        regime = make_regime(confidence=0.9, divergence_score=0.2)
        # High drawdown triggers W
        portfolio = make_portfolio(drawdown_pct=15.0)

        decision = engine.evaluate(signals, regime, portfolio)

        assert decision.state == QEFCState.W
        assert decision.risk_factor == 0.0
        assert "W_OVERRIDE" in decision.reason_codes
        assert "DRAWDOWN_BREACH" in decision.reason_codes

    def test_W_overrides_T_on_high_divergence(self) -> None:
        """
        MANDATORY: Even with perfect consensus (would be T),
        W triggers when divergence_score > threshold.
        Result: risk_factor = 0.0
        """
        engine = QEFCEngine(divergence_threshold=0.8)
        # Perfect consensus signals → would be T
        signals = [
            make_signal(intent="LONG", confidence=0.95),
            make_signal(intent="LONG", confidence=0.9),
        ]
        # High divergence triggers W
        regime = make_regime(confidence=0.9, divergence_score=0.9)
        portfolio = make_portfolio(drawdown_pct=2.0)

        decision = engine.evaluate(signals, regime, portfolio)

        assert decision.state == QEFCState.W
        assert decision.risk_factor == 0.0
        assert "W_OVERRIDE" in decision.reason_codes
        assert "DIVERGENCE_BREACH" in decision.reason_codes

    def test_W_overrides_T_on_equity_floor_breach(self) -> None:
        """W triggers on equity_floor_breach."""
        engine = QEFCEngine()
        signals = [
            make_signal(intent="LONG", confidence=0.95),
        ]
        regime = make_regime()
        portfolio = make_portfolio(equity_floor_breach=True)

        decision = engine.evaluate(signals, regime, portfolio)

        assert decision.state == QEFCState.W
        assert decision.risk_factor == 0.0
        assert "EQUITY_FLOOR_BREACH" in decision.reason_codes

    def test_W_sets_risk_factor_zero(self) -> None:
        """W always sets risk_factor = 0.0."""
        engine = QEFCEngine(max_drawdown_pct=5.0)
        signals = [make_signal(intent="LONG", confidence=1.0)]
        regime = make_regime()
        portfolio = make_portfolio(drawdown_pct=10.0)

        decision = engine.evaluate(signals, regime, portfolio)

        assert decision.state == QEFCState.W
        assert decision.risk_factor == 0.0


# ============================================================
# TEST: COOLDOWN MECHANISM
# ============================================================


class TestCooldownMechanism:
    """Test cooldown barriers after W and F."""

    def test_T_blocked_after_W_until_cooldown_expires(self) -> None:
        """
        MANDATORY: After W, T is blocked for cooldown_bars.
        System returns N (wait) instead of T.
        """
        engine = QEFCEngine(cooldown_bars=4, max_drawdown_pct=10.0)

        # First call: trigger W
        signals = [make_signal(intent="LONG", confidence=0.9)]
        regime = make_regime()
        portfolio_high_dd = make_portfolio(drawdown_pct=15.0)
        decision1 = engine.evaluate(signals, regime, portfolio_high_dd)
        assert decision1.state == QEFCState.W

        # Subsequent calls: T should be blocked during cooldown
        portfolio_normal = make_portfolio(drawdown_pct=2.0)
        for i in range(4):  # cooldown_bars = 4
            decision = engine.evaluate(signals, regime, portfolio_normal)
            # T blocked → forced to N
            if decision.state != QEFCState.W:  # Not another W trigger
                assert decision.state == QEFCState.N, f"Bar {i + 1}: Expected N, got {decision.state}"
                assert "W_COOLDOWN_ACTIVE" in decision.reason_codes

    def test_T_blocked_after_F_until_cooldown_expires(self) -> None:
        """
        MANDATORY: After F, T is blocked for cooldown_bars.
        System returns N (wait) instead of T.
        """
        engine = QEFCEngine(cooldown_bars=4)

        # First call: trigger F (all SHORT signals)
        signals_short = [
            make_signal(intent="SHORT", confidence=0.9),
            make_signal(intent="SHORT", confidence=0.85),
        ]
        regime = make_regime()
        portfolio = make_portfolio()
        decision1 = engine.evaluate(signals_short, regime, portfolio)
        assert decision1.state == QEFCState.F

        # Subsequent calls: T should be blocked during cooldown
        signals_long = [
            make_signal(intent="LONG", confidence=0.9),
            make_signal(intent="LONG", confidence=0.85),
        ]
        for i in range(3):  # First 3 bars of cooldown
            decision = engine.evaluate(signals_long, regime, portfolio)
            # T blocked → forced to N
            assert decision.state == QEFCState.N, f"Bar {i + 1}: Expected N, got {decision.state}"
            # Either F_COOLDOWN_ACTIVE or F_TO_T_BLOCKED
            assert any(code in decision.reason_codes for code in ["F_COOLDOWN_ACTIVE", "F_TO_T_BLOCKED"])

    def test_T_allowed_after_cooldown_expires_from_W(self) -> None:
        """After cooldown expires from W, T is allowed."""
        engine = QEFCEngine(cooldown_bars=2, max_drawdown_pct=10.0)

        # Trigger W
        signals = [make_signal(intent="LONG", confidence=0.9)]
        regime = make_regime()
        portfolio_high_dd = make_portfolio(drawdown_pct=15.0)
        engine.evaluate(signals, regime, portfolio_high_dd)

        # Wait out cooldown
        portfolio_normal = make_portfolio(drawdown_pct=2.0)
        for _ in range(2):  # cooldown_bars = 2
            engine.evaluate(signals, regime, portfolio_normal)

        # Now T should be allowed
        decision = engine.evaluate(signals, regime, portfolio_normal)
        assert decision.state == QEFCState.T


# ============================================================
# TEST: IRREVERSIBILITY (F→T FORBIDDEN)
# ============================================================


class TestIrreversibility:
    """Test F→T forbidden constraint."""

    def test_F_to_T_transition_forbidden(self) -> None:
        """
        MANDATORY: F→T direct transition is FORBIDDEN.
        Even if cooldown has expired, F cannot go directly to T.
        System returns N instead.
        """
        engine = QEFCEngine(cooldown_bars=2)

        # First call: trigger F
        signals_short = [
            make_signal(intent="SHORT", confidence=0.9),
            make_signal(intent="SHORT", confidence=0.85),
        ]
        regime = make_regime()
        portfolio = make_portfolio()
        decision1 = engine.evaluate(signals_short, regime, portfolio)
        assert decision1.state == QEFCState.F

        # Wait out cooldown completely
        signals_neutral = [make_signal(intent="NEUTRAL", confidence=0.5)]
        for _ in range(3):  # More than cooldown_bars
            engine.evaluate(signals_neutral, regime, portfolio)

        # Now try to go to T directly from previous F state
        # But first we need to get back to F
        decision_f = engine.evaluate(signals_short, regime, portfolio)
        assert decision_f.state == QEFCState.F

        # Now signals indicate T, but F→T is forbidden
        signals_long = [
            make_signal(intent="LONG", confidence=0.95),
            make_signal(intent="LONG", confidence=0.9),
        ]
        decision = engine.evaluate(signals_long, regime, portfolio)

        # F→T blocked → forced to N
        assert decision.state == QEFCState.N
        assert "F_TO_T_BLOCKED" in decision.reason_codes

    def test_F_to_N_allowed(self) -> None:
        """F→N is allowed (neutral recovery)."""
        engine = QEFCEngine()

        # First call: trigger F
        signals_short = [
            make_signal(intent="SHORT", confidence=0.9),
        ]
        regime = make_regime()
        portfolio = make_portfolio()
        decision1 = engine.evaluate(signals_short, regime, portfolio)
        assert decision1.state == QEFCState.F

        # Now send neutral signals → N
        signals_neutral = [make_signal(intent="NEUTRAL", confidence=0.5)]
        decision2 = engine.evaluate(signals_neutral, regime, portfolio)

        assert decision2.state == QEFCState.N

    def test_F_to_C_allowed(self) -> None:
        """F→C is allowed (partial recovery via conflict)."""
        engine = QEFCEngine(conflict_threshold=0.5)

        # First call: trigger F
        signals_short = [make_signal(intent="SHORT", confidence=0.9)]
        regime = make_regime()
        portfolio = make_portfolio()
        decision1 = engine.evaluate(signals_short, regime, portfolio)
        assert decision1.state == QEFCState.F

        # Now send conflicting signals → C
        signals_conflict = [
            make_signal(intent="LONG", confidence=0.9),
            make_signal(intent="SHORT", confidence=0.9),
        ]
        decision2 = engine.evaluate(signals_conflict, regime, portfolio)

        assert decision2.state == QEFCState.C


# ============================================================
# TEST: DIMENSIONAL COMPRESSION
# ============================================================


class TestDimensionalCompression:
    """Test < 10 meta-features constraint."""

    def test_meta_features_count_under_10(self) -> None:
        """CompressedMeta has < 10 fields (9 total)."""
        # Count fields in _CompressedMeta
        from dataclasses import fields

        meta_fields = fields(_CompressedMeta)
        assert len(meta_fields) < 10, f"Expected < 10 fields, got {len(meta_fields)}"
        assert len(meta_fields) == 9, f"Expected exactly 9 fields, got {len(meta_fields)}"

    def test_compression_produces_valid_meta(self) -> None:
        """_compress_inputs produces valid CompressedMeta."""
        engine = QEFCEngine()
        signals = [
            make_signal(intent="LONG", confidence=0.8),
            make_signal(intent="SHORT", confidence=0.6),
        ]
        regime = make_regime(confidence=0.7, divergence_score=0.4)
        portfolio = make_portfolio(drawdown_pct=5.0)

        meta = engine._compress_inputs(signals, regime, portfolio)

        assert isinstance(meta, _CompressedMeta)
        assert -1.0 <= meta.consensus_score <= 1.0
        assert 0.0 <= meta.conflict_intensity <= 2.0  # Max std for [-1, 1]
        assert meta.regime_confidence == 0.7
        assert meta.divergence_score == 0.4
        assert meta.drawdown_pct == 5.0


# ============================================================
# TEST: SUPERVISOR STATE
# ============================================================


class TestSupervisorState:
    """Test SupervisorState tracking."""

    def test_supervisor_state_initialized(self) -> None:
        """SupervisorState initializes with safe defaults."""
        engine = QEFCEngine()
        state = engine.supervisor_state

        assert state.previous_final_state == QEFCState.N
        assert state.bars_since_W == 999
        assert state.bars_since_F == 999
        assert state.W_lock is False

    def test_reset_clears_supervisor_state(self) -> None:
        """reset() clears supervisor state."""
        engine = QEFCEngine(max_drawdown_pct=10.0)

        # Trigger W to modify state
        signals = [make_signal(intent="LONG", confidence=0.9)]
        regime = make_regime()
        portfolio = make_portfolio(drawdown_pct=15.0)
        engine.evaluate(signals, regime, portfolio)

        # Reset
        engine.reset()

        state = engine.supervisor_state
        assert state.previous_final_state == QEFCState.N
        assert state.bars_since_W == 999


# ============================================================
# TEST: RISK FACTOR MAPPING
# ============================================================


class TestRiskFactorMapping:
    """Test state → risk_factor mapping."""

    def test_T_returns_full_risk_factor(self) -> None:
        """T state → risk_factor = 1.0."""
        engine = QEFCEngine()
        signals = [
            make_signal(intent="LONG", confidence=0.95),
            make_signal(intent="LONG", confidence=0.9),
        ]
        regime = make_regime()
        portfolio = make_portfolio()

        decision = engine.evaluate(signals, regime, portfolio)

        assert decision.state == QEFCState.T
        assert decision.risk_factor == 1.0

    def test_C_returns_half_risk_factor(self) -> None:
        """C state → risk_factor = 0.5."""
        engine = QEFCEngine(conflict_threshold=0.5)
        signals = [
            make_signal(intent="LONG", confidence=0.9),
            make_signal(intent="SHORT", confidence=0.9),
        ]
        regime = make_regime()
        portfolio = make_portfolio()

        decision = engine.evaluate(signals, regime, portfolio)

        assert decision.state == QEFCState.C
        assert decision.risk_factor == 0.5

    def test_N_returns_zero_risk_factor(self) -> None:
        """N state → risk_factor = 0.0."""
        engine = QEFCEngine()
        signals = [make_signal(intent="NEUTRAL", confidence=0.5)]
        regime = make_regime()
        portfolio = make_portfolio()

        decision = engine.evaluate(signals, regime, portfolio)

        assert decision.state == QEFCState.N
        assert decision.risk_factor == 0.0

    def test_F_returns_zero_risk_factor(self) -> None:
        """F state → risk_factor = 0.0."""
        engine = QEFCEngine()
        signals = [
            make_signal(intent="SHORT", confidence=0.9),
            make_signal(intent="SHORT", confidence=0.85),
        ]
        regime = make_regime()
        portfolio = make_portfolio()

        decision = engine.evaluate(signals, regime, portfolio)

        assert decision.state == QEFCState.F
        assert decision.risk_factor == 0.0
