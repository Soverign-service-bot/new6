"""Tests for HCAP-01 SovereignAllocator risk-to-lot traceability."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pytest

from core.sovereign_allocator import SovereignAllocator
from core.types import (
    AgentSignal,
    MarketSnapshot,
    PortfolioState,
    QEFCDecision,
    QEFCState,
)


@dataclass
class StubRegistry:
    """Simple stub to track sizing inputs and return a fixed lot."""

    next_lot: float = 0.5
    last_risk_amount: float = 0.0
    last_sl_distance: float = 0.0
    last_symbol: str = ""

    def calc_lot_from_risk(
        self,
        risk_amount_usd: float,
        sl_distance_points: float,
        symbol: str,
    ) -> float:
        self.last_risk_amount = risk_amount_usd
        self.last_sl_distance = sl_distance_points
        self.last_symbol = symbol
        return self.next_lot


def make_signal(
    *,
    intent: Literal["LONG", "SHORT", "NEUTRAL"] = "LONG",
    invalidation_price: float | None = 1.19,
    proposed_risk_pct: float | None = 2.0,
) -> AgentSignal:
    return AgentSignal(
        agent_name="trend_agent",
        symbol="EURUSD",
        intent=intent,
        confidence=0.8,
        invalidation_price=invalidation_price,
        proposed_risk_pct=proposed_risk_pct,
        timestamp=datetime.utcnow(),
    )


def make_qefc(*, risk_factor: float, state: QEFCState = QEFCState.T) -> QEFCDecision:
    return QEFCDecision(
        state=state,
        risk_factor=risk_factor,
        reason_codes=["test"],
        cooldown_bars=0,
        timestamp=datetime.utcnow(),
    )


def make_snapshot(*, price: float = 1.20) -> MarketSnapshot:
    return MarketSnapshot(symbol="EURUSD", price=price, timestamp=datetime.utcnow())


def make_portfolio(*, equity: float = 10_000.0) -> PortfolioState:
    return PortfolioState(
        equity=equity,
        balance=10_000.0,
        drawdown_pct=0.0,
        open_positions=0,
        margin_used_pct=0.0,
        equity_floor_breach=False,
        timestamp=datetime.utcnow(),
    )


class TestRiskToLotMath:
    def test_final_risk_math_and_registry_inputs(self) -> None:
        allocator = SovereignAllocator(default_portfolio_multiplier=1.0)
        registry = StubRegistry(next_lot=0.37)

        decision = allocator.allocate(
            qefc_decision=make_qefc(risk_factor=0.5),
            signals=[make_signal(proposed_risk_pct=2.0)],
            snapshot=make_snapshot(price=1.2000),
            portfolio=make_portfolio(equity=10_000.0),
            registry=registry,  # type: ignore[arg-type]
        )

        assert decision.action == "OPEN"
        assert decision.proposed_risk_pct == pytest.approx(2.0)
        assert decision.risk_after_QEFC == pytest.approx(1.0)
        assert decision.portfolio_multiplier == pytest.approx(1.0)
        assert decision.final_risk_pct == pytest.approx(1.0)
        assert registry.last_risk_amount == pytest.approx(100.0)
        assert registry.last_sl_distance == pytest.approx(0.01)
        assert registry.last_symbol == "EURUSD"
        assert decision.orders[0].quantity == pytest.approx(0.37)

    def test_stop_distance_uses_absolute_difference_for_short(self) -> None:
        allocator = SovereignAllocator()
        registry = StubRegistry(next_lot=0.2)

        decision = allocator.allocate(
            qefc_decision=make_qefc(risk_factor=1.0),
            signals=[make_signal(intent="SHORT", invalidation_price=1.2100)],
            snapshot=make_snapshot(price=1.2000),
            portfolio=make_portfolio(),
            registry=registry,  # type: ignore[arg-type]
        )

        assert decision.action == "OPEN"
        assert registry.last_sl_distance == pytest.approx(0.01)


class TestSafetyGuard:
    def test_reject_when_invalidation_price_missing(self) -> None:
        allocator = SovereignAllocator()
        registry = StubRegistry(next_lot=0.8)

        decision = allocator.allocate(
            qefc_decision=make_qefc(risk_factor=1.0),
            signals=[make_signal(invalidation_price=None)],
            snapshot=make_snapshot(),
            portfolio=make_portfolio(),
            registry=registry,  # type: ignore[arg-type]
        )

        assert decision.action == "REJECT"
        assert decision.orders == []
        assert decision.notes is not None
        assert "Safety Guard" in decision.notes


class TestTraceFields:
    def test_hcap_trace_fields_present_and_consistent(self) -> None:
        allocator = SovereignAllocator(default_portfolio_multiplier=1.0)
        registry = StubRegistry(next_lot=1.23)

        decision = allocator.allocate(
            qefc_decision=make_qefc(risk_factor=0.4),
            signals=[make_signal(proposed_risk_pct=2.5)],
            snapshot=make_snapshot(price=1.3000),
            portfolio=make_portfolio(equity=20_000.0),
            registry=registry,  # type: ignore[arg-type]
        )

        assert decision.action == "OPEN"
        assert decision.proposed_risk_pct == pytest.approx(2.5)
        assert decision.risk_after_QEFC == pytest.approx(1.0)
        assert decision.portfolio_multiplier == pytest.approx(1.0)
        assert decision.final_risk_pct == pytest.approx(1.0)
        assert decision.orders[0].quantity == pytest.approx(1.23)
        assert decision.orders[0].metadata["allocated_lot_size"] == pytest.approx(1.23)


class TestDirectionPreservation:
    def test_long_maps_to_buy(self) -> None:
        allocator = SovereignAllocator()
        registry = StubRegistry(next_lot=0.4)

        decision = allocator.allocate(
            qefc_decision=make_qefc(risk_factor=1.0),
            signals=[make_signal(intent="LONG")],
            snapshot=make_snapshot(),
            portfolio=make_portfolio(),
            registry=registry,  # type: ignore[arg-type]
        )

        assert decision.action == "OPEN"
        assert decision.orders[0].side == "BUY"

    def test_short_maps_to_sell(self) -> None:
        allocator = SovereignAllocator()
        registry = StubRegistry(next_lot=0.4)

        decision = allocator.allocate(
            qefc_decision=make_qefc(risk_factor=1.0),
            signals=[make_signal(intent="SHORT", invalidation_price=1.21)],
            snapshot=make_snapshot(price=1.20),
            portfolio=make_portfolio(),
            registry=registry,  # type: ignore[arg-type]
        )

        assert decision.action == "OPEN"
        assert decision.orders[0].side == "SELL"

    def test_neutral_stays_hold(self) -> None:
        allocator = SovereignAllocator()
        registry = StubRegistry(next_lot=0.4)

        decision = allocator.allocate(
            qefc_decision=make_qefc(risk_factor=1.0),
            signals=[make_signal(intent="NEUTRAL")],
            snapshot=make_snapshot(),
            portfolio=make_portfolio(),
            registry=registry,  # type: ignore[arg-type]
        )

        assert decision.action == "HOLD"
        assert decision.orders == []


class TestAdditionalRejections:
    def test_reject_when_lot_size_is_zero(self) -> None:
        allocator = SovereignAllocator()
        registry = StubRegistry(next_lot=0.0)

        decision = allocator.allocate(
            qefc_decision=make_qefc(risk_factor=1.0),
            signals=[make_signal()],
            snapshot=make_snapshot(),
            portfolio=make_portfolio(),
            registry=registry,  # type: ignore[arg-type]
        )

        assert decision.action == "REJECT"
        assert decision.notes is not None
        assert "lot_size" in decision.notes

    def test_hold_when_qefc_risk_factor_zero(self) -> None:
        allocator = SovereignAllocator()
        registry = StubRegistry(next_lot=0.4)

        decision = allocator.allocate(
            qefc_decision=make_qefc(risk_factor=0.0, state=QEFCState.W),
            signals=[make_signal()],
            snapshot=make_snapshot(),
            portfolio=make_portfolio(),
            registry=registry,  # type: ignore[arg-type]
        )

        assert decision.action == "HOLD"
        assert decision.final_risk_pct == 0.0

    def test_reject_when_portfolio_equity_zero(self) -> None:
        allocator = SovereignAllocator()
        registry = StubRegistry(next_lot=0.4)

        decision = allocator.allocate(
            qefc_decision=make_qefc(risk_factor=1.0),
            signals=[make_signal()],
            snapshot=make_snapshot(),
            portfolio=make_portfolio(equity=0.0),
            registry=registry,  # type: ignore[arg-type]
        )

        assert decision.action == "REJECT"
        assert decision.notes is not None
        assert "risk_amount_usd" in decision.notes

    def test_hold_when_signals_empty(self) -> None:
        allocator = SovereignAllocator()
        registry = StubRegistry(next_lot=0.4)

        decision = allocator.allocate(
            qefc_decision=make_qefc(risk_factor=1.0),
            signals=[],
            snapshot=make_snapshot(),
            portfolio=make_portfolio(),
            registry=registry,  # type: ignore[arg-type]
        )

        assert decision.action == "HOLD"
        assert decision.orders == []
