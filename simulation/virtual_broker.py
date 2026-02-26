"""Virtual Broker implementation for lab execution simulation."""

from typing import Dict, Literal

from core.types import (
    AllocationDecision,
    ExecutedOrder,
    ExecutionReport,
    MarketSnapshot,
    RiskVerdict,
)


class VirtualBroker:
    """
    Lab Execution Simulator.

    Responsibilities:
    - Respect risk veto authority (execution guard)
    - Handle kill-switch and flatten actions
    - Simulate order fills at market price
    - Track positions (baseline: simple dict)

    Baseline Assumptions:
    - 0 slippage
    - 0 commission
    - Instant fills at snapshot.price
    """

    def __init__(self) -> None:
        """Initialize broker with empty position tracker."""
        # Simple position tracker: {symbol: quantity}
        # Positive = LONG, Negative = SHORT
        self.positions: Dict[str, float] = {}

    def execute(
        self,
        verdict: RiskVerdict,
        decision: AllocationDecision,
        snapshot: MarketSnapshot,
    ) -> ExecutionReport:
        """
        Execute (or reject) an allocation decision based on risk verdict.

        Algorithm:
        1. Check kill-switch first (highest priority)
        2. Check execution guard (verdict.approved)
        3. Simulate fills at snapshot.price
        4. Update position tracker

        Args:
            verdict: Risk verdict (approved/rejected/kill-switch)
            decision: Allocation decision with orders
            snapshot: Current market snapshot

        Returns:
            ExecutionReport with execution status and filled orders
        """
        # Priority 1: Kill-switch handling (overrides everything)
        if verdict.kill_switch or decision.action == "FLATTEN":
            return self._flatten_positions(
                symbol=decision.symbol,
                snapshot=snapshot,
                reason=verdict.reason if verdict.reason else "Kill-switch or FLATTEN action",
            )

        # Priority 2: Execution guard (respect risk veto)
        if not verdict.approved:
            return ExecutionReport(
                status="REJECTED",
                reason=verdict.reason or "Risk veto rejected execution",
                executed_orders=[],
            )

        # Priority 3: Normal execution (approved orders)
        return self._fill_orders(decision=decision, snapshot=snapshot)

    def _flatten_positions(
        self,
        symbol: str,
        snapshot: MarketSnapshot,
        reason: str,
    ) -> ExecutionReport:
        """Simulate flattening all positions at snapshot price."""
        executed_orders = []

        # Check if we have an open position for this symbol
        position_qty = self.positions.get(symbol, 0.0)

        if position_qty != 0.0:
            # Close position: LONG → SELL, SHORT → BUY
            close_side: Literal["BUY", "SELL"] = "SELL" if position_qty > 0 else "BUY"
            flatten_order = ExecutedOrder(
                symbol=symbol,
                side=close_side,
                quantity=abs(position_qty),
                fill_price=snapshot.price,
                slippage=0.0,
                commission=0.0,
            )
            executed_orders.append(flatten_order)

            # Update position tracker
            self.positions[symbol] = 0.0

        return ExecutionReport(
            status="FLATTENED",
            reason=reason,
            executed_orders=executed_orders,
        )

    def _fill_orders(
        self,
        decision: AllocationDecision,
        snapshot: MarketSnapshot,
    ) -> ExecutionReport:
        """Simulate normal order fills at snapshot price (0 slippage baseline)."""
        executed_orders = []

        for order in decision.orders:
            executed = ExecutedOrder(
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                fill_price=snapshot.price,
                slippage=0.0,
                commission=0.0,
            )
            executed_orders.append(executed)

            # Update position tracker
            current_position = self.positions.get(order.symbol, 0.0)
            if order.side == "BUY":
                self.positions[order.symbol] = current_position + order.quantity
            else:  # SELL
                self.positions[order.symbol] = current_position - order.quantity

        return ExecutionReport(
            status="EXECUTED",
            reason="Orders filled at market price",
            executed_orders=executed_orders,
        )
