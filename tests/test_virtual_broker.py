"""Tests for VirtualBroker execution simulation."""

from datetime import datetime
from typing import Literal

import pytest

from core.types import (
    AllocationDecision,
    MarketSnapshot,
    OrderIntent,
    RiskVerdict,
)
from simulation.virtual_broker import VirtualBroker


def make_verdict(*, approved: bool = True, kill_switch: bool = False, reason: str = "test") -> RiskVerdict:
    """Helper to create RiskVerdict."""
    return RiskVerdict(
        approved=approved,
        reason=reason,
        kill_switch=kill_switch,
        timestamp=datetime.utcnow(),
    )


def make_decision(
    *,
    action: Literal["OPEN", "CLOSE", "HOLD", "REJECT", "FLATTEN"] = "OPEN",
    quantity: float = 0.5,
    side: Literal["BUY", "SELL"] = "BUY",
) -> AllocationDecision:
    """Helper to create AllocationDecision."""
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
        action=action,
        proposed_risk_pct=2.0,
        risk_after_QEFC=1.0,
        portfolio_multiplier=1.0,
        final_risk_pct=1.0,
        orders=[order] if action == "OPEN" else [],
        notes="test decision",
        timestamp=datetime.utcnow(),
    )


def make_snapshot(*, price: float = 1.20) -> MarketSnapshot:
    """Helper to create MarketSnapshot."""
    return MarketSnapshot(
        symbol="EURUSD",
        price=price,
        timestamp=datetime.utcnow(),
    )


class TestExecutionGuard:
    """Test that rejected verdicts result in no execution."""

    def test_reject_when_verdict_not_approved(self) -> None:
        broker = VirtualBroker()

        report = broker.execute(
            verdict=make_verdict(approved=False, reason="drawdown exceeded"),
            decision=make_decision(),
            snapshot=make_snapshot(),
        )

        assert report.status == "REJECTED"
        assert report.executed_orders == []
        assert "drawdown exceeded" in (report.reason or "")

    def test_rejected_report_has_empty_orders(self) -> None:
        broker = VirtualBroker()

        report = broker.execute(
            verdict=make_verdict(approved=False),
            decision=make_decision(quantity=1.0),
            snapshot=make_snapshot(),
        )

        assert report.status == "REJECTED"
        assert len(report.executed_orders) == 0

    def test_execute_when_verdict_approved(self) -> None:
        broker = VirtualBroker()

        report = broker.execute(
            verdict=make_verdict(approved=True),
            decision=make_decision(),
            snapshot=make_snapshot(),
        )

        assert report.status == "EXECUTED"
        assert len(report.executed_orders) > 0


class TestKillSwitch:
    """Test kill-switch and flatten behavior."""

    def test_flatten_when_kill_switch_true(self) -> None:
        broker = VirtualBroker()
        # Set up a position first
        broker.positions["EURUSD"] = 0.5  # LONG position

        report = broker.execute(
            verdict=make_verdict(approved=False, kill_switch=True, reason="max drawdown"),
            decision=make_decision(),
            snapshot=make_snapshot(price=1.21),
        )

        assert report.status == "FLATTENED"
        assert len(report.executed_orders) == 1
        assert report.executed_orders[0].side == "SELL"
        assert report.executed_orders[0].quantity == pytest.approx(0.5)
        assert broker.positions["EURUSD"] == pytest.approx(0.0)

    def test_flatten_when_action_flatten(self) -> None:
        broker = VirtualBroker()
        # Set up a SHORT position
        broker.positions["EURUSD"] = -0.3

        report = broker.execute(
            verdict=make_verdict(approved=True),  # Approved but action is FLATTEN
            decision=make_decision(action="FLATTEN"),
            snapshot=make_snapshot(price=1.19),
        )

        assert report.status == "FLATTENED"
        assert len(report.executed_orders) == 1
        assert report.executed_orders[0].side == "BUY"  # Close SHORT with BUY
        assert report.executed_orders[0].quantity == pytest.approx(0.3)

    def test_flatten_report_status(self) -> None:
        broker = VirtualBroker()
        broker.positions["EURUSD"] = 1.0

        report = broker.execute(
            verdict=make_verdict(approved=False, kill_switch=True),
            decision=make_decision(),
            snapshot=make_snapshot(),
        )

        assert report.status == "FLATTENED"
        assert "FLATTENED" in report.status

    def test_flatten_closes_at_snapshot_price(self) -> None:
        broker = VirtualBroker()
        broker.positions["EURUSD"] = 0.8

        report = broker.execute(
            verdict=make_verdict(approved=False, kill_switch=True),
            decision=make_decision(),
            snapshot=make_snapshot(price=1.2345),
        )

        assert report.executed_orders[0].fill_price == pytest.approx(1.2345)

    def test_flatten_with_no_position_returns_empty(self) -> None:
        broker = VirtualBroker()
        # No position set

        report = broker.execute(
            verdict=make_verdict(approved=False, kill_switch=True),
            decision=make_decision(),
            snapshot=make_snapshot(),
        )

        assert report.status == "FLATTENED"
        assert report.executed_orders == []


class TestFillSimulation:
    """Test normal order execution."""

    def test_fill_at_snapshot_price(self) -> None:
        broker = VirtualBroker()

        report = broker.execute(
            verdict=make_verdict(approved=True),
            decision=make_decision(quantity=0.4),
            snapshot=make_snapshot(price=1.2500),
        )

        assert report.status == "EXECUTED"
        assert len(report.executed_orders) == 1
        assert report.executed_orders[0].fill_price == pytest.approx(1.2500)

    def test_zero_commission_baseline(self) -> None:
        broker = VirtualBroker()

        report = broker.execute(
            verdict=make_verdict(approved=True),
            decision=make_decision(),
            snapshot=make_snapshot(),
        )

        assert report.executed_orders[0].commission == pytest.approx(0.0)

    def test_zero_slippage_baseline(self) -> None:
        broker = VirtualBroker()

        report = broker.execute(
            verdict=make_verdict(approved=True),
            decision=make_decision(),
            snapshot=make_snapshot(),
        )

        assert report.executed_orders[0].slippage == pytest.approx(0.0)

    def test_executed_report_status(self) -> None:
        broker = VirtualBroker()

        report = broker.execute(
            verdict=make_verdict(approved=True),
            decision=make_decision(),
            snapshot=make_snapshot(),
        )

        assert report.status == "EXECUTED"


class TestPositionTracking:
    """Test position state updates."""

    def test_position_updated_after_buy(self) -> None:
        broker = VirtualBroker()

        broker.execute(
            verdict=make_verdict(approved=True),
            decision=make_decision(side="BUY", quantity=0.5),
            snapshot=make_snapshot(),
        )

        assert broker.positions["EURUSD"] == pytest.approx(0.5)

    def test_position_updated_after_sell(self) -> None:
        broker = VirtualBroker()
        broker.positions["EURUSD"] = 1.0

        broker.execute(
            verdict=make_verdict(approved=True),
            decision=make_decision(side="SELL", quantity=0.3),
            snapshot=make_snapshot(),
        )

        assert broker.positions["EURUSD"] == pytest.approx(0.7)

    def test_position_accumulates_multiple_buys(self) -> None:
        broker = VirtualBroker()

        broker.execute(
            verdict=make_verdict(approved=True),
            decision=make_decision(side="BUY", quantity=0.2),
            snapshot=make_snapshot(),
        )
        broker.execute(
            verdict=make_verdict(approved=True),
            decision=make_decision(side="BUY", quantity=0.3),
            snapshot=make_snapshot(),
        )

        assert broker.positions["EURUSD"] == pytest.approx(0.5)

    def test_position_goes_negative_on_short(self) -> None:
        broker = VirtualBroker()

        broker.execute(
            verdict=make_verdict(approved=True),
            decision=make_decision(side="SELL", quantity=0.4),
            snapshot=make_snapshot(),
        )

        assert broker.positions["EURUSD"] == pytest.approx(-0.4)
