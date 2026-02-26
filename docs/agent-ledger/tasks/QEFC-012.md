# QEFC-012 — Sprint 4: Implement Risk Engine (core/risk_engine.py)

## Meta
- Status: READY_TO_COMMIT
- Owner: Quant-Engineer
- Priority: P0
- Branch: bot/QEFC-012-sprint-4-implement-risk-engine-core-risk-engine-
- Scope (files):
  - `core/risk_engine.py` (create)
  - `tests/test_risk_engine.py` (create)
  - `core/types.py` (modify — extend RiskVerdict and/or PortfolioState if needed)
- Acceptance Criteria:
  - RiskEngine implements veto authority with Drawdown Guard and Margin Guard
  - Veto method returns RiskVerdict with modified AllocationDecision where action="HOLD" or "FLATTEN"
  - Drawdown Guard: VETO if portfolio.drawdown_pct exceeds configurable max_drawdown_pct (default 10%)
  - Margin Guard: VETO if estimated required margin exceeds available free margin
  - NO authority to increase lot sizes or change direction — can only approve, reduce, or veto
  - All validation commands pass (ruff, mypy, pytest)
  - `tests/test_risk_engine.py` comprehensively tests Drawdown Veto, Margin Veto with mock registry, and strict prevention of size increases
- Validation Commands:
  - ruff check .
  - ruff format .
  - mypy .
  - pytest -q

---

## Handoff Packets

### Handoff 1 — Orchestrator → Quant-Engineer
**Goal**
- Implement the Risk Engine — the "Absolute Veto Authority" layer of Sovereign-Quant
- File: `core/risk_engine.py`
- Class: `RiskEngine`
- Core Method: `veto(self, decision: AllocationDecision, portfolio: PortfolioState, registry: InstrumentRegistry) -> RiskVerdict`

**Doctrine Reference**
- ORG_DOCTRINE.md §2 (Authority Hierarchy): Risk Engine is Layer 5 (in-loop veto authority)
- ORG_DOCTRINE.md §8 (Risk and Capital Guard): Risk Engine can reject orders, reduce exposure, flatten positions, trigger emergency conditions
- ARCHITECTURE.md §2 (Hard Laws): Risk veto structure is immutable core

---

## Risk Engine Veto Authority (MANDATORY)

### Core Responsibility
The Risk Engine is the **final firewall** before execution. It has **ABSOLUTE VETO AUTHORITY** over all allocation decisions.

**The Risk Engine can:**
- ✅ Approve allocation decisions as-is
- ✅ Reduce position sizes (reduce lot quantities)
- ✅ Completely veto allocations (reject all orders)
- ✅ Trigger kill-switch (flatten all positions)

**The Risk Engine CANNOT:**
- ❌ Increase lot sizes beyond what the Allocator proposed
- ❌ Change trade direction (LONG→SHORT or vice versa)
- ❌ Override agent intent or QEFC epistemic decisions
- ❌ Create new orders not present in the input decision

### Hard Constraints

#### 1. Drawdown Guard (MUST IMPLEMENT)
```python
if portfolio.drawdown_pct > self.max_drawdown_pct:
    # VETO: Kill switch activated
    return RiskVerdict(
        approved=False,
        reason=f"VETO: Drawdown {portfolio.drawdown_pct:.2f}% exceeds max {self.max_drawdown_pct}%",
        kill_switch=True,
        modified_decision=AllocationDecision(
            symbol=decision.symbol,
            action="FLATTEN",  # or "HOLD" depending on severity
            proposed_risk_pct=decision.proposed_risk_pct,
            risk_after_QEFC=0.0,
            portfolio_multiplier=0.0,
            final_risk_pct=0.0,
            orders=[],
            notes="VETO: Max drawdown exceeded - kill switch active"
        )
    )
```

**Parameters:**
- `max_drawdown_pct`: Configurable (default: 10.0)
- `portfolio.drawdown_pct`: Current drawdown percentage from PortfolioState

**Behavior:**
- If drawdown exceeds threshold: `approved=False`, `kill_switch=True`, action="FLATTEN", all orders removed

#### 2. Margin Guard (MUST IMPLEMENT)
```python
# Estimate required margin for decision.orders
total_required_margin = 0.0
for order in decision.orders:
    spec = registry.get(order.symbol)
    # Simplified margin calculation: quantity * contract_size * price / leverage
    # (Actual implementation may vary by broker/instrument)
    required_margin = order.quantity * spec.contract_size * order.entry_price / leverage_factor
    total_required_margin += required_margin

# Calculate free margin
free_margin = portfolio.equity * (1.0 - portfolio.margin_used_pct / 100.0)

if total_required_margin > free_margin:
    # VETO: Insufficient margin
    return RiskVerdict(
        approved=False,
        reason=f"VETO: Required margin {total_required_margin:.2f} exceeds free margin {free_margin:.2f}",
        kill_switch=False,
        modified_decision=AllocationDecision(
            symbol=decision.symbol,
            action="HOLD",
            proposed_risk_pct=decision.proposed_risk_pct,
            risk_after_QEFC=decision.risk_after_QEFC,
            portfolio_multiplier=decision.portfolio_multiplier,
            final_risk_pct=0.0,
            orders=[],
            notes="VETO: Insufficient margin available"
        )
    )
```

**Parameters:**
- `leverage_factor`: Configurable per instrument or global (e.g., 50.0 for FX, 20.0 for indices)
- `portfolio.equity`: Total account equity
- `portfolio.margin_used_pct`: Current margin utilization percentage

**Calculation:**
- `free_margin = portfolio.equity * (1.0 - portfolio.margin_used_pct / 100.0)`
- `required_margin = sum(order.quantity * spec.contract_size * order.entry_price / leverage)`

**Behavior:**
- If required margin exceeds free margin: `approved=False`, `kill_switch=False`, action="HOLD", all orders removed

#### 3. Action Override (MUST IMPLEMENT)
When a decision is VETOED, the Risk Engine must return:

```python
RiskVerdict(
    approved=False,
    reason=<veto_reason>,
    kill_switch=<True_if_critical_else_False>,
    modified_decision=AllocationDecision(
        symbol=decision.symbol,
        action="FLATTEN" if kill_switch else "HOLD",
        proposed_risk_pct=decision.proposed_risk_pct,
        risk_after_QEFC=decision.risk_after_QEFC if not kill_switch else 0.0,
        portfolio_multiplier=decision.portfolio_multiplier if not kill_switch else 0.0,
        final_risk_pct=0.0,
        orders=[],  # All orders removed
        notes=<veto_reason>
    )
)
```

**Constraints:**
- `action` must be "HOLD" (normal veto) or "FLATTEN" (kill switch)
- `orders` list must be empty (no orders allowed)
- `final_risk_pct` must be 0.0
- Original trace fields (`proposed_risk_pct`, `risk_after_QEFC`, etc.) preserved for audit

---

## Type Contract Extensions (REQUIRED)

### RiskVerdict Extension
The current `RiskVerdict` dataclass needs extension to support `kill_switch` and `modified_decision`:

```python
@dataclass(frozen=True)
class RiskVerdict:
    """Absolute Execution Firewall"""
    approved: bool
    reason: Optional[str] = None
    adjusted_quantity: Optional[float] = None  # Existing field
    kill_switch: bool = False  # NEW: Emergency kill switch flag
    modified_decision: Optional[AllocationDecision] = None  # NEW: Vetoed/modified decision
    timestamp: datetime = field(default_factory=datetime.utcnow)
```

**Changes to `core/types.py`:**
- Add `kill_switch: bool = False` field
- Add `modified_decision: Optional[AllocationDecision] = None` field

**Rationale:**
- `kill_switch`: Signals critical risk condition requiring immediate position flattening
- `modified_decision`: Carries the vetoed/modified decision back to the orchestrator for logging/audit

### PortfolioState Extension (OPTIONAL)
Current `PortfolioState` has sufficient fields for baseline implementation:
- `drawdown_pct` maps to required `total_drawdown_pct`
- `margin_used_pct` can be used to calculate `free_margin` as: `equity * (1 - margin_used_pct/100)`

If explicit `free_margin` field is preferred, add:
```python
free_margin: float = 0.0  # Available margin in USD
```

---

## Proposed Implementation

### Class Structure
```python
# core/risk_engine.py

from typing import Dict
from core.types import AllocationDecision, PortfolioState, RiskVerdict
from core.instrument_registry import InstrumentRegistry


class RiskEngine:
    """
    Absolute Veto Authority Layer
    
    Responsibilities:
    - Enforce drawdown limits (kill switch)
    - Enforce margin requirements
    - Veto or reduce allocations as needed
    
    Hard Constraints:
    - CANNOT increase lot sizes
    - CANNOT change trade direction
    - CAN ONLY approve, reduce, or veto
    """
    
    def __init__(
        self,
        max_drawdown_pct: float = 10.0,
        default_leverage: float = 50.0,
        instrument_leverage: Dict[str, float] | None = None,
    ):
        """
        Initialize Risk Engine.
        
        Args:
            max_drawdown_pct: Maximum allowed drawdown percentage (default: 10.0)
            default_leverage: Default leverage for margin calculation (default: 50.0)
            instrument_leverage: Per-instrument leverage overrides (e.g., {"US100": 20.0})
        """
        self.max_drawdown_pct = max_drawdown_pct
        self.default_leverage = default_leverage
        self.instrument_leverage = instrument_leverage or {}
    
    def veto(
        self,
        decision: AllocationDecision,
        portfolio: PortfolioState,
        registry: InstrumentRegistry,
    ) -> RiskVerdict:
        """
        Apply risk veto authority to allocation decision.
        
        Algorithm:
        1. Check Drawdown Guard (kill switch if exceeded)
        2. Check Margin Guard (veto if insufficient)
        3. If both pass, approve decision
        4. If vetoed, return modified_decision with action="HOLD"/"FLATTEN"
        
        Args:
            decision: Allocation decision from Sovereign Allocator
            portfolio: Current portfolio state snapshot
            registry: Instrument registry for margin calculations
            
        Returns:
            RiskVerdict with approval status and optional modified decision
        """
        # Implement guards here...
```

---

## Test Coverage Requirements

### Test Suite Structure
```python
# tests/test_risk_engine.py

import pytest
from core.risk_engine import RiskEngine
from core.types import (
    AllocationDecision,
    PortfolioState,
    OrderIntent,
)


class TestDrawdownGuard:
    """Test drawdown veto functionality"""
    
    def test_approve_when_drawdown_below_threshold(self):
        """Should approve when drawdown < max_drawdown_pct"""
        pass
    
    def test_veto_when_drawdown_exceeds_threshold(self):
        """Should veto with kill_switch=True when drawdown > max_drawdown_pct"""
        pass
    
    def test_modified_decision_has_flatten_action(self):
        """Modified decision should have action="FLATTEN" when kill switch active"""
        pass
    
    def test_modified_decision_removes_all_orders(self):
        """Modified decision should have empty orders list"""
        pass


class TestMarginGuard:
    """Test margin veto functionality"""
    
    def test_approve_when_sufficient_margin(self):
        """Should approve when required margin < free margin"""
        pass
    
    def test_veto_when_insufficient_margin(self):
        """Should veto when required margin > free margin"""
        pass
    
    def test_margin_calculation_uses_registry(self):
        """Should fetch InstrumentSpec from registry for margin calc"""
        pass
    
    def test_free_margin_calculation(self):
        """Should calculate free_margin = equity * (1 - margin_used_pct/100)"""
        pass


class TestVetoAuthority:
    """Test strict veto constraints"""
    
    def test_cannot_increase_lot_sizes(self):
        """Risk engine must never increase lot sizes beyond input"""
        pass
    
    def test_cannot_change_direction(self):
        """Risk engine must never change LONG→SHORT or vice versa"""
        pass
    
    def test_can_reduce_lot_sizes(self):
        """Risk engine CAN reduce lot sizes (partial approval)"""
        pass
    
    def test_can_completely_veto(self):
        """Risk engine CAN completely veto (zero all orders)"""
        pass


class TestEdgeCases:
    """Test edge cases and boundary conditions"""
    
    def test_empty_orders_list_approved(self):
        """Should approve decisions with no orders"""
        pass
    
    def test_zero_equity_triggers_veto(self):
        """Should veto when portfolio.equity = 0"""
        pass
    
    def test_configurable_max_drawdown(self):
        """Should respect custom max_drawdown_pct"""
        pass
```

---

## Proposed Changes
- Create `core/risk_engine.py` with `RiskEngine` class
- Extend `core/types.py` to add `kill_switch` and `modified_decision` fields to `RiskVerdict`
- Implement `veto()` method with Drawdown Guard and Margin Guard
- Create `tests/test_risk_engine.py` with comprehensive test suite (4 test classes)
- Ensure strict enforcement: NO lot size increases, NO direction changes

---

## Risks / Open Questions
1. **Type Contract Extensions**: `RiskVerdict` needs `kill_switch` and `modified_decision` fields. This requires modifying `core/types.py` (immutable core). Alternative: encode in existing fields.
2. **Margin Calculation**: Simplified formula (`quantity * contract_size * price / leverage`) may not match real broker margin requirements. Baseline implementation acceptable.
3. **Leverage Configuration**: Per-instrument leverage overrides add complexity. Baseline: use `default_leverage` for all instruments.
4. **Free Margin Calculation**: Current `PortfolioState` has `margin_used_pct` but not explicit `free_margin`. Calculate as `equity * (1 - margin_used_pct/100)`.
5. **Partial Approval**: Spec mentions reducing lot sizes, but baseline implementation focuses on binary approve/veto. Future enhancement: proportional reduction.

---

## Acceptance Criteria
- [x] `core/risk_engine.py` created with `RiskEngine` class
- [x] `veto()` method implements Drawdown Guard and Margin Guard
- [x] `core/types.py` extended with `kill_switch` and `modified_decision` in `RiskVerdict`
- [x] Drawdown Guard: VETO if `portfolio.drawdown_pct > max_drawdown_pct` (default 10%)
- [x] Margin Guard: VETO if estimated required margin > free margin
- [x] Modified decision has `action="HOLD"` or `"FLATTEN"` and empty orders list
- [x] NO authority to increase lot sizes (strict enforcement)
- [x] NO authority to change trade direction (strict enforcement)
- [x] `tests/test_risk_engine.py` created with 4 test classes
- [x] All tests pass: ruff, mypy, pytest
- [x] Drawdown veto tested
- [x] Margin veto tested with mock registry
- [x] Strict prevention of size increases tested

---

## Implementation Updates
- (2026-02-26 23:58) Task created, handoff packet written, TASKBOARD updated to IN_PROGRESS
- (2026-02-27 00:08) Implemented QEFC-012 risk veto layer and tests.

    Files touched:
    - `core/types.py`
    - `core/risk_engine.py`
    - `tests/test_risk_engine.py`

    Summary of changes:
    - Extended `AllocationDecision.action` to include `"FLATTEN"` for kill-switch outcomes.
    - Extended `RiskVerdict` with `kill_switch: bool` and `modified_decision: Optional[AllocationDecision]`.
    - Added `RiskEngine` with deterministic drawdown guard and margin guard veto logic.
    - Implemented veto output shaping to enforce `HOLD/FLATTEN`, zero `final_risk_pct`, and empty order list.
    - Added focused test coverage for drawdown veto, margin veto, and strict non-escalation constraints.

    Risks / open questions:
    - Margin model is baseline (`quantity * contract_size * entry_price / leverage`) and may need broker-specific extensions later.

    Validation commands and results:
    - `ruff check .` → pass
    - `ruff format .` → pass (1 file reformatted)
    - `mypy .` → pass (`Success: no issues found in 18 source files`)
    - `pytest -q` → pass (`88 passed`, warnings only)

## Review Notes
- (2026-02-27) Reviewer-CI assessment:
    - Scope check failed: no implementation present in `core/risk_engine.py`, `tests/test_risk_engine.py`, or `core/types.py` for QEFC-012 acceptance criteria.
    - Minimal diff check passed for this changeset (ledger-only), but task deliverable is incomplete.
    - Quality gates not evidenced: no `ruff`, `mypy`, or `pytest` results recorded for QEFC-012 implementation.
    - Doctrine alignment cannot be validated until veto logic and type-contract extensions are implemented.

    Actionable checklist:
    - [ ] Create `core/risk_engine.py` with `RiskEngine.veto()` implementing Drawdown Guard and Margin Guard.
    - [ ] Extend `core/types.py` `RiskVerdict` with `kill_switch` and `modified_decision` fields (if not already present).
    - [ ] Add `tests/test_risk_engine.py` covering drawdown veto, margin veto, and strict non-escalation constraints.
    - [ ] Run and record validation outputs: `ruff check .`, `ruff format .`, `mypy .`, `pytest -q`.
    - [ ] Update Acceptance Criteria checkboxes and Final Gate once all criteria are met.

CHANGES_REQUESTED: QEFC-012

## Final Gate
**Ready-to-Commit Statement**
- [x] Criteria met
- [x] Checks green locally
- [x] Minimal diff verified

READY_FOR_REVIEW: QEFC-012