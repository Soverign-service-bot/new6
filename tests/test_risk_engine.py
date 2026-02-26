"""Tests for RiskEngine veto behavior and authority constraints."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pytest

from core.instrument_registry import InstrumentSpec
from core.risk_engine import RiskEngine
from core.types import AllocationDecision, OrderIntent, PortfolioState


@dataclass
class StubRegistry:
    contract_size: float = 100_000.0

    def get(self, symbol: str) -> InstrumentSpec:
        return InstrumentSpec(
            symbol=symbol,
            tick_size=0.0001,
            point_value=10.0,
            contract_size=self.contract_size,
            min_lot=0.01,
            max_lot=100.0,
            lot_step=0.01,
        )


def make_portfolio(
    *,
    drawdown_pct: float = 0.0,
    equity: float = 10_000.0,
    margin_used_pct: float = 10.0,
) -> PortfolioState:
    return PortfolioState(
        equity=equity,
        balance=equity,
        drawdown_pct=drawdown_pct,
        open_positions=1,
        margin_used_pct=margin_used_pct,
        equity_floor_breach=False,
        timestamp=datetime.utcnow(),
    )


def make_decision(*, quantity: float = 0.5, side: Literal["BUY", "SELL"] = "BUY") -> AllocationDecision:
    order = OrderIntent(
        symbol="EURUSD",
        side=side,
        quantity=quantity,
        entry_price=1.20,
        stop_loss=1.19,
        risk_pct_used=1.0,
    )
    return AllocationDecision(
        symbol="EURUSD",
        action="OPEN",
        proposed_risk_pct=2.0,
        risk_after_QEFC=1.0,
        portfolio_multiplier=1.0,
        final_risk_pct=1.0,
        orders=[order],
        notes="allocator output",
        timestamp=datetime.utcnow(),
    )


class TestDrawdownGuard:
    def test_approve_when_drawdown_below_threshold(self) -> None:
        engine = RiskEngine(max_drawdown_pct=10.0)

        verdict = engine.veto(
            decision=make_decision(),
            portfolio=make_portfolio(drawdown_pct=5.0),
            registry=StubRegistry(),  # type: ignore[arg-type]
        )

        assert verdict.approved is True
        assert verdict.kill_switch is False
        assert verdict.modified_decision is None

    def test_veto_when_drawdown_exceeds_threshold(self) -> None:
        engine = RiskEngine(max_drawdown_pct=10.0)

        verdict = engine.veto(
            decision=make_decision(),
            portfolio=make_portfolio(drawdown_pct=12.5),
            registry=StubRegistry(),  # type: ignore[arg-type]
        )

        assert verdict.approved is False
        assert verdict.kill_switch is True
        assert verdict.modified_decision is not None
        assert verdict.modified_decision.action == "FLATTEN"
        assert verdict.modified_decision.orders == []
        assert verdict.modified_decision.final_risk_pct == pytest.approx(0.0)


class TestMarginGuard:
    def test_approve_when_sufficient_margin(self) -> None:
        engine = RiskEngine(default_leverage=100.0)

        verdict = engine.veto(
            decision=make_decision(quantity=0.1),
            portfolio=make_portfolio(equity=10_000.0, margin_used_pct=20.0),
            registry=StubRegistry(contract_size=100_000.0),  # type: ignore[arg-type]
        )

        assert verdict.approved is True

    def test_veto_when_insufficient_margin(self) -> None:
        engine = RiskEngine(default_leverage=10.0)

        verdict = engine.veto(
            decision=make_decision(quantity=5.0),
            portfolio=make_portfolio(equity=1_000.0, margin_used_pct=90.0),
            registry=StubRegistry(contract_size=100_000.0),  # type: ignore[arg-type]
        )

        assert verdict.approved is False
        assert verdict.kill_switch is False
        assert verdict.modified_decision is not None
        assert verdict.modified_decision.action == "HOLD"
        assert verdict.modified_decision.orders == []
        assert verdict.modified_decision.final_risk_pct == pytest.approx(0.0)


class TestVetoAuthority:
    def test_cannot_increase_lot_sizes(self) -> None:
        engine = RiskEngine(default_leverage=100.0)
        decision = make_decision(quantity=0.25)

        verdict = engine.veto(
            decision=decision,
            portfolio=make_portfolio(),
            registry=StubRegistry(),  # type: ignore[arg-type]
        )

        if verdict.modified_decision is not None:
            for original, modified in zip(decision.orders, verdict.modified_decision.orders):
                assert modified.quantity <= original.quantity
        else:
            assert decision.orders[0].quantity == pytest.approx(0.25)

    def test_cannot_change_direction(self) -> None:
        engine = RiskEngine(default_leverage=100.0)
        decision = make_decision(side="SELL")

        verdict = engine.veto(
            decision=decision,
            portfolio=make_portfolio(),
            registry=StubRegistry(),  # type: ignore[arg-type]
        )

        if verdict.modified_decision is not None and verdict.modified_decision.orders:
            for original, modified in zip(decision.orders, verdict.modified_decision.orders):
                assert original.side == modified.side
        else:
            assert decision.orders[0].side == "SELL"


class TestEdgeCases:
    def test_empty_orders_list_approved(self) -> None:
        engine = RiskEngine()
        decision = AllocationDecision(
            symbol="EURUSD",
            action="HOLD",
            proposed_risk_pct=0.0,
            risk_after_QEFC=0.0,
            portfolio_multiplier=1.0,
            final_risk_pct=0.0,
            orders=[],
            notes="no orders",
            timestamp=datetime.utcnow(),
        )

        verdict = engine.veto(
            decision=decision,
            portfolio=make_portfolio(),
            registry=StubRegistry(),  # type: ignore[arg-type]
        )

        assert verdict.approved is True

    def test_configurable_max_drawdown(self) -> None:
        engine = RiskEngine(max_drawdown_pct=5.0)

        verdict = engine.veto(
            decision=make_decision(),
            portfolio=make_portfolio(drawdown_pct=6.0),
            registry=StubRegistry(),  # type: ignore[arg-type]
        )

        assert verdict.approved is False
        assert verdict.kill_switch is True
