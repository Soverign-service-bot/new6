"""Risk Engine implementation for veto authority in the Sovereign-Quant stack."""

from dataclasses import replace
from typing import Dict

from core.instrument_registry import InstrumentRegistry
from core.types import AllocationDecision, PortfolioState, RiskVerdict


class RiskEngine:
    """Absolute veto authority layer before execution."""

    def __init__(
        self,
        max_drawdown_pct: float = 10.0,
        default_leverage: float = 50.0,
        instrument_leverage: Dict[str, float] | None = None,
    ) -> None:
        self.max_drawdown_pct = max_drawdown_pct
        self.default_leverage = default_leverage
        self.instrument_leverage = instrument_leverage or {}

    def veto(
        self,
        decision: AllocationDecision,
        portfolio: PortfolioState,
        registry: InstrumentRegistry,
    ) -> RiskVerdict:
        """Apply drawdown and margin guards to an allocation decision."""
        if portfolio.drawdown_pct > self.max_drawdown_pct:
            reason = f"VETO: Drawdown {portfolio.drawdown_pct:.2f}% exceeds max {self.max_drawdown_pct:.2f}%"
            return self._veto(decision=decision, reason=reason, kill_switch=True)

        required_margin = self._required_margin(decision=decision, registry=registry)
        free_margin = self._free_margin(portfolio=portfolio)

        if required_margin > free_margin:
            reason = f"VETO: Required margin {required_margin:.2f} exceeds free margin {free_margin:.2f}"
            return self._veto(decision=decision, reason=reason, kill_switch=False)

        return RiskVerdict(approved=True, reason="APPROVED")

    def _free_margin(self, portfolio: PortfolioState) -> float:
        free_margin = portfolio.equity * (1.0 - portfolio.margin_used_pct / 100.0)
        return max(0.0, free_margin)

    def _required_margin(self, decision: AllocationDecision, registry: InstrumentRegistry) -> float:
        total_required_margin = 0.0
        for order in decision.orders:
            spec = registry.get(order.symbol)
            entry_price = order.entry_price if order.entry_price is not None else 0.0
            leverage = self.instrument_leverage.get(order.symbol, self.default_leverage)
            if leverage <= 0:
                leverage = self.default_leverage if self.default_leverage > 0 else 1.0
            required_margin = abs(order.quantity) * spec.contract_size * entry_price / leverage
            total_required_margin += required_margin
        return total_required_margin

    def _veto(self, decision: AllocationDecision, reason: str, kill_switch: bool) -> RiskVerdict:
        modified_decision = replace(
            decision,
            action="FLATTEN" if kill_switch else "HOLD",
            risk_after_QEFC=0.0 if kill_switch else decision.risk_after_QEFC,
            portfolio_multiplier=0.0 if kill_switch else decision.portfolio_multiplier,
            final_risk_pct=0.0,
            orders=[],
            notes=reason,
        )

        return RiskVerdict(
            approved=False,
            reason=reason,
            adjusted_quantity=0.0,
            kill_switch=kill_switch,
            modified_decision=modified_decision,
        )
