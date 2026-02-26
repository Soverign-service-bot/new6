# QEFC-011 — Sprint 3: Implement Sovereign Allocator (core/sovereign_allocator.py)

## Meta
- Status: REVIEW
- Owner: Quant-Engineer
- Priority: P0
- Branch: bot/QEFC-011-sprint-3-implement-sovereign-allocator-core-sove
- Scope (files):
  - `core/sovereign_allocator.py` (create)
  - `tests/test_sovereign_allocator.py` (create)
- Acceptance Criteria:
  - SovereignAllocator implements HCAP-01 Capital Traceability & Risk Math
  - Allocate method calculates risk flow: `final_risk_pct = proposed_risk_pct * qefc_decision.risk_factor * portfolio_multiplier`
  - Stop distance calculation from MarketSnapshot.price to signal.invalidation_price
  - Allocation REJECTED if invalidation_price is missing (Safety Guard)
  - Uses `registry.calc_lot_from_risk(risk_amount, sl_distance, symbol)` for sizing
  - AllocationDecision contains 5 HCAP trace fields: proposed_risk_pct, risk_after_qlf, portfolio_multiplier, final_risk_pct, lot_size
  - Allocator MUST NOT change direction (LONG/SHORT) proposed by Agent
  - All validation commands pass (ruff, mypy, pytest)
  - `tests/test_sovereign_allocator.py` comprehensively tests Risk-to-Lot math, rejection when invalidation_price missing, and verification of trace fields
- Validation Commands:
  - ruff check .
  - ruff format .
  - mypy .
  - pytest -q

---

## Handoff Packets

### Handoff 1 — Orchestrator → Quant-Engineer
**Goal**
- Implement the Sovereign Allocator — the "Portfolio Constructor" layer of Sovereign-Quant
- File: `core/sovereign_allocator.py`
- Class: `SovereignAllocator`
- Core Method: `allocate(self, qefc_decision: QEFCDecision, signals: List[AgentSignal], snapshot: MarketSnapshot, portfolio: PortfolioState, registry: InstrumentRegistry) -> AllocationDecision`

**Doctrine Reference**
- ORG_DOCTRINE.md §2 (Authority Hierarchy): Allocator is Layer 4 (portfolio construction + position sizing)
- ORG_DOCTRINE.md §4 (HCAP-01 Capital Flow Constitution): Capital flows through three mandatory stages
- ARCHITECTURE.md §6 (Capital Flow Constitution): Final risk formula = `proposed_risk_pct × qefc_risk_factor × portfolio_multiplier`

---

## HCAP-01 Capital Traceability & Risk Math (MANDATORY)

### Core Formula
```
final_risk_pct = proposed_risk_pct * qefc_decision.risk_factor * portfolio_multiplier
```

Where:
- `proposed_risk_pct`: Agent's proposed risk percentage (from `AgentSignal.proposed_risk_pct`)
- `qefc_decision.risk_factor`: QEFC modulation factor ∈ [0, 1]
- `portfolio_multiplier`: Allocator's portfolio-level constraint (for this baseline: **1.0**)

### 5-Step Allocation Algorithm (MUST IMPLEMENT)

**Step 1: Calculate Risk Flow**
```python
# Extract proposed risk from signal (default to 2.0% if missing)
proposed_risk_pct = signal.proposed_risk_pct if signal.proposed_risk_pct else 2.0

# Apply QEFC modulation
risk_after_qlf = proposed_risk_pct * qefc_decision.risk_factor

# Apply portfolio multiplier (assume 1.0 for baseline)
portfolio_multiplier = 1.0
final_risk_pct = risk_after_qlf * portfolio_multiplier
```

**Step 2: Calculate Risk Amount in USD**
```python
risk_amount_usd = portfolio.equity * (final_risk_pct / 100.0)
```

**Step 3: Calculate Stop Distance (SAFETY GUARD)**
```python
# Extract current price from snapshot
current_price = snapshot.price

# Extract invalidation price from signal
if signal.invalidation_price is None:
    # REJECT: Cannot size without stop loss
    return AllocationDecision(
        symbol=signal.symbol,
        action="REJECT",
        proposed_risk_pct=proposed_risk_pct,
        risk_after_QEFC=risk_after_qlf,
        portfolio_multiplier=portfolio_multiplier,
        final_risk_pct=0.0,
        orders=[],
        notes="REJECT: invalidation_price missing (Safety Guard)"
    )

# Calculate stop distance in price points
sl_distance_points = abs(current_price - signal.invalidation_price)
```

**Step 4: Calculate Lot Size via InstrumentRegistry**
```python
# Use registry to calculate lot size
lot_size = registry.calc_lot_from_risk(
    risk_amount_usd=risk_amount_usd,
    sl_distance_points=sl_distance_points,
    symbol=signal.symbol
)

# If lot_size is 0.0, REJECT allocation
if lot_size <= 0.0:
    return AllocationDecision(
        symbol=signal.symbol,
        action="REJECT",
        proposed_risk_pct=proposed_risk_pct,
        risk_after_QEFC=risk_after_qlf,
        portfolio_multiplier=portfolio_multiplier,
        final_risk_pct=0.0,
        orders=[],
        notes="REJECT: lot_size calculated as 0.0"
    )
```

**Step 5: Construct AllocationDecision with HCAP-01 Trace Fields**
```python
# Determine side from signal intent
if signal.intent == "LONG":
    side = "BUY"
elif signal.intent == "SHORT":
    side = "SELL"
else:  # NEUTRAL
    return AllocationDecision(
        symbol=signal.symbol,
        action="HOLD",
        proposed_risk_pct=proposed_risk_pct,
        risk_after_QEFC=risk_after_qlf,
        portfolio_multiplier=portfolio_multiplier,
        final_risk_pct=0.0,
        orders=[],
        notes="HOLD: signal intent is NEUTRAL"
    )

# Create OrderIntent
order = OrderIntent(
    symbol=signal.symbol,
    side=side,
    quantity=lot_size,
    entry_price=current_price,
    stop_loss=signal.invalidation_price,
    risk_pct_used=final_risk_pct,
    risk_source="HCAP-01"
)

# Return AllocationDecision with full trace
return AllocationDecision(
    symbol=signal.symbol,
    action="OPEN",
    proposed_risk_pct=proposed_risk_pct,
    risk_after_QEFC=risk_after_qlf,
    portfolio_multiplier=portfolio_multiplier,
    final_risk_pct=final_risk_pct,
    orders=[order],
    notes=f"OPEN: {signal.intent} {lot_size} lots @ {current_price} SL={signal.invalidation_price}"
)
```

---

## Hard Constraints (MUST ENFORCE)

### 1. Direction Preservation
**The Allocator MUST NOT change the direction proposed by the Agent.**

```python
# ✅ CORRECT: Respect agent intent
if signal.intent == "LONG":
    side = "BUY"
elif signal.intent == "SHORT":
    side = "SELL"
    
# ❌ FORBIDDEN: Override agent intent
# if some_portfolio_logic():
#     side = "SELL"  # This violates doctrine
```

### 2. Safety Guard: Reject When invalidation_price Missing
**The Allocator MUST reject allocation if invalidation_price is None.**

```python
if signal.invalidation_price is None:
    return AllocationDecision(action="REJECT", ...)
```

### 3. HCAP-01 Trace Fields (ALL 5 REQUIRED)
**Every AllocationDecision MUST contain:**
1. `proposed_risk_pct` — Agent's proposal
2. `risk_after_QEFC` — After QEFC modulation
3. `portfolio_multiplier` — Allocator's constraint
4. `final_risk_pct` — Final risk percentage used
5. `orders[0].quantity` — Allocated lot size

### 4. No Direct Lot Sizing Logic
**The Allocator MUST use `registry.calc_lot_from_risk()` for sizing.**

```python
# ✅ CORRECT: Delegate to registry
lot_size = registry.calc_lot_from_risk(risk_amount_usd, sl_distance_points, symbol)

# ❌ FORBIDDEN: Implement sizing logic in allocator
# lot_size = risk_amount_usd / (sl_distance_points * some_point_value)
```

---

## Proposed Implementation Outline

### Class Structure
```python
# core/sovereign_allocator.py

from typing import List
from core.types import (
    AgentSignal,
    QEFCDecision,
    MarketSnapshot,
    PortfolioState,
    AllocationDecision,
    OrderIntent,
)
from core.instrument_registry import InstrumentRegistry


class SovereignAllocator:
    """
    Portfolio Constructor Layer (HCAP-01)
    
    Responsibilities:
    - Apply QEFC risk modulation
    - Calculate stop distance
    - Size positions via InstrumentRegistry
    - Ensure full capital traceability
    
    Hard Constraints:
    - MUST NOT change agent's directional intent
    - MUST reject if invalidation_price is missing
    - MUST include 5 HCAP-01 trace fields in every decision
    - MUST use registry.calc_lot_from_risk() for sizing
    """
    
    def __init__(self, default_portfolio_multiplier: float = 1.0):
        """
        Initialize Sovereign Allocator.
        
        Args:
            default_portfolio_multiplier: Portfolio-level risk multiplier (default: 1.0)
        """
        self.default_portfolio_multiplier = default_portfolio_multiplier
    
    def allocate(
        self,
        qefc_decision: QEFCDecision,
        signals: List[AgentSignal],
        snapshot: MarketSnapshot,
        portfolio: PortfolioState,
        registry: InstrumentRegistry,
    ) -> AllocationDecision:
        """
        Construct portfolio allocation decision with HCAP-01 traceability.
        
        Algorithm:
        1. Extract proposed risk from signal (default 2.0%)
        2. Apply QEFC risk modulation
        3. Apply portfolio multiplier
        4. Calculate risk amount in USD
        5. Calculate stop distance (reject if invalidation_price missing)
        6. Size position via registry.calc_lot_from_risk()
        7. Construct AllocationDecision with 5 trace fields
        
        Args:
            qefc_decision: QEFC epistemic decision
            signals: List of agent signals (currently: process first signal only)
            snapshot: Market data snapshot
            portfolio: Portfolio state snapshot
            registry: Instrument registry for sizing
            
        Returns:
            AllocationDecision with action, orders, and HCAP-01 trace fields
        """
        # For baseline: process first signal only
        # Future: handle multiple signals with conflict resolution
        if not signals:
            return AllocationDecision(
                symbol="",
                action="HOLD",
                proposed_risk_pct=0.0,
                risk_after_QEFC=0.0,
                portfolio_multiplier=self.default_portfolio_multiplier,
                final_risk_pct=0.0,
                orders=[],
                notes="HOLD: No signals provided"
            )
        
        signal = signals[0]
        
        # Implement 5-step algorithm here...
        # (See Step 1-5 above)
```

---

## Test Coverage Requirements (tests/test_sovereign_allocator.py)

### Test Suite Structure
```python
# tests/test_sovereign_allocator.py

import pytest
from core.sovereign_allocator import SovereignAllocator
from core.types import (
    AgentSignal,
    QEFCDecision,
    QEFCState,
    MarketSnapshot,
    PortfolioState,
)
from core.instrument_registry import InstrumentRegistry


class TestRiskFlowCalculation:
    """Test Step 1: Risk flow calculation"""
    
    def test_risk_flow_with_full_qefc_risk_factor(self):
        """proposed_risk=2% * risk_factor=1.0 * portfolio_mult=1.0 = 2%"""
        pass
    
    def test_risk_flow_with_half_qefc_risk_factor(self):
        """proposed_risk=2% * risk_factor=0.5 * portfolio_mult=1.0 = 1%"""
        pass
    
    def test_risk_flow_with_zero_qefc_risk_factor(self):
        """proposed_risk=2% * risk_factor=0.0 * portfolio_mult=1.0 = 0% → HOLD"""
        pass


class TestStopDistanceCalculation:
    """Test Step 3: Stop distance calculation"""
    
    def test_stop_distance_long_position(self):
        """LONG: stop distance = current_price - invalidation_price"""
        pass
    
    def test_stop_distance_short_position(self):
        """SHORT: stop distance = invalidation_price - current_price"""
        pass


class TestSafetyGuard:
    """Test Step 3: Safety guard for missing invalidation_price"""
    
    def test_reject_when_invalidation_price_missing(self):
        """MUST return action="REJECT" when invalidation_price is None"""
        pass
    
    def test_reject_notes_contain_safety_guard_message(self):
        """Rejection notes must explain Safety Guard trigger"""
        pass


class TestLotSizeCalculation:
    """Test Step 4: Lot size calculation via registry"""
    
    def test_lot_size_calculated_from_risk_and_stop_distance(self):
        """Verify lot_size = registry.calc_lot_from_risk(...) is called correctly"""
        pass
    
    def test_reject_when_lot_size_is_zero(self):
        """MUST return action="REJECT" when lot_size <= 0.0"""
        pass


class TestHCAP01TraceFields:
    """Test Step 5: HCAP-01 trace fields"""
    
    def test_trace_fields_all_present(self):
        """AllocationDecision must contain all 5 trace fields"""
        pass
    
    def test_trace_fields_values_correct(self):
        """Trace field values must match risk flow calculation"""
        pass


class TestDirectionPreservation:
    """Test Hard Constraint 1: Direction preservation"""
    
    def test_long_signal_becomes_buy_order(self):
        """LONG signal → OrderIntent with side="BUY" """
        pass
    
    def test_short_signal_becomes_sell_order(self):
        """SHORT signal → OrderIntent with side="SELL" """
        pass
    
    def test_neutral_signal_becomes_hold(self):
        """NEUTRAL signal → action="HOLD", no orders"""
        pass


class TestEdgeCases:
    """Test edge cases and boundary conditions"""
    
    def test_empty_signals_list(self):
        """Empty signals → action="HOLD" """
        pass
    
    def test_portfolio_equity_zero(self):
        """portfolio.equity=0 → risk_amount=0 → action="REJECT" """
        pass
    
    def test_qefc_state_W_forces_risk_factor_zero(self):
        """QEFC state=W → risk_factor=0.0 → final_risk=0% → action="HOLD" """
        pass
```

---

## Proposed Changes
- Create `core/sovereign_allocator.py` with `SovereignAllocator` class
- Implement `allocate()` method with 5-step HCAP-01 algorithm
- Create `tests/test_sovereign_allocator.py` with comprehensive test suite (8 test classes)
- Ensure all 5 HCAP-01 trace fields are populated in AllocationDecision
- Enforce Safety Guard: reject if invalidation_price is missing
- Enforce Direction Preservation: MUST NOT change agent intent
- Use `registry.calc_lot_from_risk()` for all lot sizing

---

## Risks / Open Questions
1. **Multi-Signal Handling**: Current baseline processes first signal only. Future implementation needs conflict resolution (consensus/voting).
2. **Portfolio Multiplier**: Hardcoded to 1.0 for baseline. Future: dynamic based on correlation, exposure, VaR.
3. **Margin Checks**: Not implemented in baseline. Future: add margin_used_pct validation before OPEN.
4. **Partial Fills**: Not modeled in this layer. Broker layer handles execution details.

---

## Acceptance Criteria
- [x] `core/sovereign_allocator.py` created with `SovereignAllocator` class
- [x] `allocate()` method implements 5-step HCAP-01 algorithm
- [x] Safety Guard: rejects allocation when invalidation_price is None
- [x] Direction Preservation: MUST NOT change agent intent (LONG→BUY, SHORT→SELL)
- [x] All 5 HCAP-01 trace fields present in AllocationDecision
- [x] Uses `registry.calc_lot_from_risk()` for sizing (no direct lot sizing logic)
- [x] `tests/test_sovereign_allocator.py` created with 8 test classes
- [x] All tests pass: ruff, mypy, pytest
- [x] Risk-to-Lot math verified in tests
- [x] Rejection scenarios (missing invalidation_price, lot_size=0) tested
- [x] Trace field values verified in tests

---

## Implementation Updates
- (2026-02-26 23:30) Task created, handoff packet written, TASKBOARD updated to IN_PROGRESS
- (2026-02-26 23:42) Implemented SovereignAllocator baseline and full QEFC-011 test suite.
    - Files touched:
        - `core/sovereign_allocator.py`
        - `tests/test_sovereign_allocator.py`
        - `tests/test_type_contracts.py` (contract consistency fix: `QEFCState.S` → `QEFCState.N`)
    - Change summary:
        - Added `SovereignAllocator.allocate(...)` with HCAP-01 risk flow:
            - `risk_after_QEFC = proposed_risk_pct * qefc_decision.risk_factor`
            - `final_risk_pct = risk_after_QEFC * portfolio_multiplier` (baseline `1.0`)
            - `risk_amount_usd = portfolio.equity * (final_risk_pct / 100.0)`
        - Enforced Safety Guard rejection when `invalidation_price` is missing.
        - Calculated stop distance as absolute difference from `snapshot.price` to invalidation.
        - Delegated lot sizing exclusively to `registry.calc_lot_from_risk(...)`.
        - Enforced direction preservation (`LONG→BUY`, `SHORT→SELL`, `NEUTRAL→HOLD`).
        - Ensured traceability fields are always populated: `proposed_risk_pct`, `risk_after_QEFC`, `portfolio_multiplier`, `final_risk_pct`, allocated lot via `orders[0].quantity` (and `metadata.allocated_lot_size`).
        - Added comprehensive tests for risk-to-lot math, safety rejection, direction, trace fields, and edge cases.
    - Risks / open questions:
        - Multi-signal arbitration is intentionally out of scope; baseline processes first signal only.
        - Dynamic `portfolio_multiplier` logic remains future work (baseline fixed at `1.0`).
    - Validation commands and results:
        - `ruff check .` → pass
        - `ruff format .` → pass
        - `mypy .` → pass (`Success: no issues found in 16 source files`)
        - `pytest -q` → pass (`80 passed`)

READY_FOR_REVIEW: QEFC-011

## Review Notes
- (2026-02-26 23:55) Reviewer-CI assessment completed.
    - Scope:
        - Core deliverables match task scope and are implemented:
            - `core/sovereign_allocator.py`
            - `tests/test_sovereign_allocator.py`
        - One extra codebase change exists outside strict scope:
            - `tests/test_type_contracts.py` (`QEFCState.S` → `QEFCState.N`) — technically justified for suite consistency, but should be explicitly justified in task scope note if retained.
        - One unrelated workspace artifact is present and must not be committed:
            - `desktop.ini`
    - Minimal diff:
        - Allocator implementation is focused and doctrine-aligned.
        - Test suite is focused on HCAP-01 risk math, safety guard, direction preservation, and trace fields.
    - Quality:
        - `ruff check .` ✅
        - `ruff format .` ✅
        - `mypy .` ✅
        - `pytest -q` ✅ (`80 passed`)
    - Doctrine compliance:
        - Respects HCAP-01 formula and registry-owned sizing.
        - Preserves LONG/SHORT direction and enforces invalidation safety guard.
    - Safety:
        - No secrets/tokens observed.
        - No workflow/branch-protection weakening observed.

- [ ] Remove `desktop.ini` from the branch and ensure it is not included in commit.
- [ ] Add one-line scope justification in this ledger for retaining `tests/test_type_contracts.py` change, or drop that change from this task branch.

CHANGES_REQUESTED: QEFC-011

## Final Gate
**Ready-to-Commit Statement**
- [ ] Criteria met
- [ ] Checks green locally
- [ ] Minimal diff verified