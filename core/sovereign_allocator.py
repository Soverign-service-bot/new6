"""Sovereign Allocator implementation for HCAP-01 capital governance."""

from typing import List, Literal

from core.instrument_registry import InstrumentRegistry
from core.types import (
    AgentSignal,
    AllocationDecision,
    MarketSnapshot,
    OrderIntent,
    PortfolioState,
    QEFCDecision,
)


class SovereignAllocator:
    """Portfolio constructor layer with deterministic risk-to-lot conversion."""

    def __init__(self, default_portfolio_multiplier: float = 1.0) -> None:
        self.default_portfolio_multiplier = default_portfolio_multiplier

    def allocate(
        self,
        qefc_decision: QEFCDecision,
        signals: List[AgentSignal],
        snapshot: MarketSnapshot,
        portfolio: PortfolioState,
        registry: InstrumentRegistry,
    ) -> AllocationDecision:
        """Build an AllocationDecision from QEFC risk modulation and signal intent."""
        if not signals:
            return AllocationDecision(
                symbol="",
                action="HOLD",
                proposed_risk_pct=0.0,
                risk_after_QEFC=0.0,
                portfolio_multiplier=self.default_portfolio_multiplier,
                final_risk_pct=0.0,
                orders=[],
                notes="HOLD: No signals provided",
            )

        signal = signals[0]
        proposed_risk_pct = signal.proposed_risk_pct if signal.proposed_risk_pct is not None else 2.0

        risk_after_qefc = proposed_risk_pct * qefc_decision.risk_factor
        portfolio_multiplier = self.default_portfolio_multiplier
        final_risk_pct = risk_after_qefc * portfolio_multiplier

        if signal.intent == "NEUTRAL":
            return AllocationDecision(
                symbol=signal.symbol,
                action="HOLD",
                proposed_risk_pct=proposed_risk_pct,
                risk_after_QEFC=risk_after_qefc,
                portfolio_multiplier=portfolio_multiplier,
                final_risk_pct=0.0,
                orders=[],
                notes="HOLD: signal intent is NEUTRAL",
            )

        if final_risk_pct <= 0.0:
            return AllocationDecision(
                symbol=signal.symbol,
                action="HOLD",
                proposed_risk_pct=proposed_risk_pct,
                risk_after_QEFC=risk_after_qefc,
                portfolio_multiplier=portfolio_multiplier,
                final_risk_pct=0.0,
                orders=[],
                notes="HOLD: final_risk_pct <= 0.0",
            )

        if signal.invalidation_price is None:
            return AllocationDecision(
                symbol=signal.symbol,
                action="REJECT",
                proposed_risk_pct=proposed_risk_pct,
                risk_after_QEFC=risk_after_qefc,
                portfolio_multiplier=portfolio_multiplier,
                final_risk_pct=0.0,
                orders=[],
                notes="REJECT: invalidation_price missing (Safety Guard)",
            )

        current_price = snapshot.price
        sl_distance_points = abs(current_price - signal.invalidation_price)
        if sl_distance_points <= 0.0:
            return AllocationDecision(
                symbol=signal.symbol,
                action="REJECT",
                proposed_risk_pct=proposed_risk_pct,
                risk_after_QEFC=risk_after_qefc,
                portfolio_multiplier=portfolio_multiplier,
                final_risk_pct=0.0,
                orders=[],
                notes="REJECT: stop distance must be > 0",
            )

        risk_amount_usd = portfolio.equity * (final_risk_pct / 100.0)
        if risk_amount_usd <= 0.0:
            return AllocationDecision(
                symbol=signal.symbol,
                action="REJECT",
                proposed_risk_pct=proposed_risk_pct,
                risk_after_QEFC=risk_after_qefc,
                portfolio_multiplier=portfolio_multiplier,
                final_risk_pct=0.0,
                orders=[],
                notes="REJECT: risk_amount_usd <= 0.0",
            )

        lot_size = registry.calc_lot_from_risk(
            risk_amount_usd=risk_amount_usd,
            sl_distance_points=sl_distance_points,
            symbol=signal.symbol,
        )
        if lot_size <= 0.0:
            return AllocationDecision(
                symbol=signal.symbol,
                action="REJECT",
                proposed_risk_pct=proposed_risk_pct,
                risk_after_QEFC=risk_after_qefc,
                portfolio_multiplier=portfolio_multiplier,
                final_risk_pct=0.0,
                orders=[],
                notes="REJECT: lot_size calculated as 0.0",
            )

        side: Literal["BUY", "SELL"] = "BUY" if signal.intent == "LONG" else "SELL"
        order = OrderIntent(
            symbol=signal.symbol,
            side=side,
            quantity=lot_size,
            entry_price=current_price,
            stop_loss=signal.invalidation_price,
            risk_pct_used=final_risk_pct,
            risk_source="HCAP-01",
            metadata={"allocated_lot_size": lot_size},
        )

        return AllocationDecision(
            symbol=signal.symbol,
            action="OPEN",
            proposed_risk_pct=proposed_risk_pct,
            risk_after_QEFC=risk_after_qefc,
            portfolio_multiplier=portfolio_multiplier,
            final_risk_pct=final_risk_pct,
            orders=[order],
            notes=(f"OPEN: {signal.intent} {lot_size} lots @ {current_price} SL={signal.invalidation_price}"),
        )
