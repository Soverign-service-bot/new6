# QEFC-013 — Sprint 5: Implement Virtual Broker (simulation/virtual_broker.py)

## Meta
- Status: READY_TO_COMMIT
- Owner: Quant-Engineer
- Priority: P0
- Branch: bot/QEFC-013-sprint-5-implement-virtual-broker-simulation-vir
- Scope (files):
  - `simulation/virtual_broker.py` (create)
  - `simulation/__init__.py` (create empty package)
  - `tests/test_virtual_broker.py` (create)
  - `core/types.py` (modify — add ExecutionReport dataclass)
- Acceptance Criteria:
  - VirtualBroker implements execution guard: only executes if verdict.approved == True
  - VirtualBroker handles kill-switch: if verdict.kill_switch == True or decision.action == "FLATTEN", simulate flattening all positions
  - Fill simulation at snapshot.price with 0 slippage/commission (baseline)
  - ExecutionReport dataclass added to core/types.py with executed quantities, fill prices, and status
  - Rejected verdicts result in empty/rejected ExecutionReport (no execution)
  - Kill-switch verdicts result in flatten execution at snapshot.price
  - All validation commands pass (ruff, mypy, pytest)
  - tests/test_virtual_broker.py proves rejected verdicts → no execution and kill-switch → flatten
- Validation Commands:
  - ruff check .
  - ruff format .
  - mypy .
  - pytest -q

---

## Handoff Packets

### Handoff 1 — Orchestrator → Quant-Engineer
**Goal**
- Implement the Virtual Broker — the "Lab Executor" layer of Sovereign-Quant
- File: `simulation/virtual_broker.py`
- Class: `VirtualBroker`
- Core Method: `execute(self, verdict: RiskVerdict, decision: AllocationDecision, snapshot: MarketSnapshot) -> ExecutionReport`

**Doctrine Reference**
- ORG_DOCTRINE.md §2 (Authority Hierarchy): Virtual Broker is Layer 6 (execution simulation)
- ARCHITECTURE.md §2 (Hard Laws): Execution must respect risk veto authority

**LAB EXECUTOR REQUIREMENTS (MANDATORY)**

#### 1. Execution Guard (MUST IMPLEMENT)
The broker MUST ONLY execute orders if `verdict.approved == True`.

```python
if not verdict.approved:
    # REJECT: Return empty/rejected ExecutionReport
    # UNLESS kill_switch is active (see Kill-Switch Handling)
    if not verdict.kill_switch:
        return ExecutionReport(
            status="REJECTED",
            reason=verdict.reason,
            executed_orders=[],
            timestamp=datetime.utcnow(),
        )
```

**Behavior:**
- `verdict.approved == False` and `verdict.kill_switch == False` → Return rejected ExecutionReport with empty executed_orders
- `verdict.approved == True` → Proceed to fill simulation (see Fill Simulation)

#### 2. Kill-Switch Handling (MUST IMPLEMENT)
If `verdict.kill_switch == True` OR `decision.action == "FLATTEN"`, the broker MUST simulate flattening all positions at the current `snapshot.price`.

```python
if verdict.kill_switch or decision.action == "FLATTEN":
    # Simulate flattening all open positions at snapshot.price
    # For baseline: assume we have 1 open position to flatten
    flatten_order = ExecutedOrder(
        symbol=decision.symbol,
        side="SELL" if <current_position_is_long> else "BUY",
        quantity=<position_quantity>,
        fill_price=snapshot.price,
        slippage=0.0,
        commission=0.0,
        timestamp=datetime.utcnow(),
    )
    return ExecutionReport(
        status="FLATTENED",
        reason=verdict.reason if verdict.kill_switch else "FLATTEN action",
        executed_orders=[flatten_order],
        timestamp=datetime.utcnow(),
    )
```

**Behavior:**
- Kill-switch takes precedence over normal execution guard
- Simulate closing all open positions at `snapshot.price`
- Return ExecutionReport with status="FLATTENED"

**Note for Baseline:**
For this baseline implementation, you can assume a simple position tracker (e.g., a dict or instance variable tracking open positions). Full position management will be added in a future sprint.

#### 3. Fill Simulation (MUST IMPLEMENT)
For approved orders (verdict.approved == True and no kill-switch), simulate execution at `snapshot.price`.

```python
# For each order in decision.orders:
executed_orders = []
for order in decision.orders:
    executed = ExecutedOrder(
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        fill_price=snapshot.price,  # Baseline: 0 slippage
        slippage=0.0,
        commission=0.0,
        timestamp=datetime.utcnow(),
    )
    executed_orders.append(executed)

return ExecutionReport(
    status="EXECUTED",
    reason="Orders filled",
    executed_orders=executed_orders,
    timestamp=datetime.utcnow(),
)
```

**Baseline Assumptions:**
- 0 slippage: fill price = snapshot.price
- 0 commission
- Structure code to allow adding slippage/commission models later

**Behavior:**
- Transform OrderIntent → ExecutedOrder with fill_price = snapshot.price
- Return ExecutionReport with status="EXECUTED"

#### 4. Type Extension (MUST IMPLEMENT)
Create two new dataclasses in `core/types.py`:

**ExecutedOrder:**
```python
@dataclass(frozen=True)
class ExecutedOrder:
    """Record of a filled order."""
    symbol: Symbol
    side: Literal["BUY", "SELL"]
    quantity: float
    fill_price: float
    slippage: float = 0.0
    commission: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
```

**ExecutionReport:**
```python
@dataclass(frozen=True)
class ExecutionReport:
    """Result of broker execution attempt."""
    status: Literal["EXECUTED", "REJECTED", "FLATTENED", "PARTIAL"]
    reason: Optional[str] = None
    executed_orders: List[ExecutedOrder] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)
```

**Changes to `core/types.py`:**
- Add `ExecutedOrder` dataclass
- Add `ExecutionReport` dataclass
- Both must be immutable (frozen=True)

**Proposed Implementation**

### Class Structure
```python
# simulation/virtual_broker.py

from typing import Dict, Optional
from core.types import (
    AllocationDecision,
    ExecutedOrder,
    ExecutionReport,
    MarketSnapshot,
    RiskVerdict,
)


class VirtualBroker:
    """
    Lab Execution Simulator
    
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
        # Implement execution logic here...
```

**Test Coverage Requirements**

### Test Suite Structure
```python
# tests/test_virtual_broker.py

import pytest
from simulation.virtual_broker import VirtualBroker
from core.types import (
    AllocationDecision,
    ExecutionReport,
    MarketSnapshot,
    OrderIntent,
    RiskVerdict,
)


class TestExecutionGuard:
    """Test that rejected verdicts result in no execution"""
    
    def test_reject_when_verdict_not_approved(self):
        """Should return REJECTED report when verdict.approved == False"""
        pass
    
    def test_rejected_report_has_empty_orders(self):
        """Rejected ExecutionReport should have empty executed_orders list"""
        pass
    
    def test_execute_when_verdict_approved(self):
        """Should execute orders when verdict.approved == True"""
        pass


class TestKillSwitch:
    """Test kill-switch and flatten behavior"""
    
    def test_flatten_when_kill_switch_true(self):
        """Should flatten positions when verdict.kill_switch == True"""
        pass
    
    def test_flatten_when_action_flatten(self):
        """Should flatten positions when decision.action == 'FLATTEN'"""
        pass
    
    def test_flatten_report_status(self):
        """ExecutionReport should have status='FLATTENED' for kill-switch"""
        pass
    
    def test_flatten_closes_at_snapshot_price(self):
        """Flatten should execute at snapshot.price"""
        pass


class TestFillSimulation:
    """Test normal order execution"""
    
    def test_fill_at_snapshot_price(self):
        """Should fill orders at snapshot.price (0 slippage baseline)"""
        pass
    
    def test_zero_commission_baseline(self):
        """Baseline should use 0 commission"""
        pass
    
    def test_executed_report_status(self):
        """ExecutionReport should have status='EXECUTED' for normal fills"""
        pass


class TestPositionTracking:
    """Test position state updates"""
    
    def test_position_updated_after_buy(self):
        """Position should increase after BUY execution"""
        pass
    
    def test_position_updated_after_sell(self):
        """Position should decrease after SELL execution"""
        pass
```

**Proposed Changes**
- Create `simulation/` package directory
- Create `simulation/__init__.py` (empty)
- Create `simulation/virtual_broker.py` with `VirtualBroker` class
- Extend `core/types.py` to add `ExecutedOrder` and `ExecutionReport` dataclasses
- Create `tests/test_virtual_broker.py` with comprehensive test suite
- Ensure strict enforcement: NO execution without approval, ALWAYS flatten on kill-switch

**Risks / Open Questions**
1. **Position Tracking Scope**: Baseline uses simple dict. Full position management (multi-symbol, partial closes, etc.) deferred to future sprint.
2. **Slippage Model**: Baseline assumes 0 slippage. Future: add configurable slippage models (fixed spread, percentage, etc.).
3. **Commission Model**: Baseline assumes 0 commission. Future: add per-lot or percentage commission.
4. **Fill Guarantees**: Baseline assumes all orders fill instantly. Future: add partial fills, rejection scenarios.
5. **Time Simulation**: Baseline uses real datetime.utcnow(). Future: injectable time for deterministic backtesting.

**Acceptance Criteria**
- [x] `simulation/virtual_broker.py` created with `VirtualBroker` class
- [x] `simulation/__init__.py` created (empty package marker)
- [x] `execute()` method implements execution guard, kill-switch handling, and fill simulation
- [x] `core/types.py` extended with `ExecutedOrder` and `ExecutionReport` dataclasses
- [x] Execution guard: `verdict.approved == False` → REJECTED ExecutionReport with empty orders
- [x] Kill-switch: `verdict.kill_switch == True` or `decision.action == "FLATTEN"` → FLATTENED ExecutionReport
- [x] Fill simulation: approved orders filled at `snapshot.price` with 0 slippage/commission
- [x] `tests/test_virtual_broker.py` created with 4 test classes
- [x] All tests pass: ruff, mypy, pytest
- [x] Tests prove rejected verdicts result in no execution
- [x] Tests prove kill-switch results in flatten actions

---

## Implementation Updates
- (2026-02-27 00:18) Task created, handoff packet written, TASKBOARD updated to IN_PROGRESS
- (2026-02-27 00:22) Implemented QEFC-013 Virtual Broker execution layer.

  Files touched:
  - `core/types.py` (extended with ExecutedOrder and ExecutionReport dataclasses)
  - `simulation/__init__.py` (created package)
  - `simulation/virtual_broker.py` (created VirtualBroker class)
  - `tests/test_virtual_broker.py` (created comprehensive test suite)

  Summary of changes:
  - Added `ExecutedOrder` dataclass with symbol, side, quantity, fill_price, slippage, commission
  - Added `ExecutionReport` dataclass with status (EXECUTED/REJECTED/FLATTENED/PARTIAL), reason, executed_orders
  - Implemented `VirtualBroker` with three-tier execution logic:
    1. Priority 1: Kill-switch handling (overrides everything)
    2. Priority 2: Execution guard (respects risk veto)
    3. Priority 3: Normal fill simulation at snapshot.price
  - Simple position tracker using dict {symbol: quantity} (positive=LONG, negative=SHORT)
  - Baseline: 0 slippage, 0 commission, instant fills
  - Added 4 test classes covering execution guard, kill-switch, fill simulation, and position tracking (17 test cases total)

  Risks / open questions:
  - Position tracking is baseline (single symbol focus). Multi-symbol management deferred to future sprint.
  - Kill-switch flattens only the symbol in decision (not portfolio-wide). Portfolio-wide flatten requires orchestrator enhancement.

  Validation commands and results:
  - `ruff check .` → pass
  - `ruff format .` → pass (22 files unchanged)
  - `mypy .` → pass (`Success: no issues found in 21 source files`)
  - `pytest -q` → pass (`104 passed`, warnings only)

## Review Notes
- (2026-02-27 00:25) Reviewer assessment — APPROVED:
  
  **Scope Verification:**
  - ✅ `simulation/virtual_broker.py` created with 145 LOC (clean, focused implementation)
  - ✅ `simulation/__init__.py` created (package marker)
  - ✅ `tests/test_virtual_broker.py` created with 282 LOC (17 test cases across 4 classes)
  - ✅ `core/types.py` extended with ExecutedOrder and ExecutionReport (minimal diff)
  
  **Acceptance Criteria Review:**
  - ✅ Execution guard implemented correctly:
    - Lines 68-72: Rejects when `verdict.approved == False` and `kill_switch == False`
    - Returns `ExecutionReport(status="REJECTED", executed_orders=[])`
  - ✅ Kill-switch handling implemented correctly:
    - Lines 61-66: Priority 1 check for `verdict.kill_switch or decision.action == "FLATTEN"`
    - `_flatten_positions()` method closes positions at `snapshot.price`
    - Handles LONG→SELL and SHORT→BUY correctly (line 93)
  - ✅ Fill simulation baseline correct:
    - Lines 116-145: Fills at `snapshot.price` with 0 slippage/commission
    - Position tracking updates correctly (lines 130-135)
  - ✅ Type extensions clean and immutable:
    - ExecutedOrder: frozen dataclass with 7 fields (lines 257-266)
    - ExecutionReport: frozen dataclass with status literal type (lines 269-284)
  - ✅ Test coverage comprehensive:
    - TestExecutionGuard: 3 tests proving rejected verdicts → no execution
    - TestKillSwitch: 5 tests proving kill-switch → flatten actions
    - TestFillSimulation: 4 tests proving baseline fill behavior
    - TestPositionTracking: 5 tests proving position state updates
  
  **Code Quality:**
  - ✅ Clean separation of concerns (3 methods: execute, _flatten_positions, _fill_orders)
  - ✅ Type hints complete and mypy-compliant
  - ✅ Docstrings present on all public methods
  - ✅ Priority ordering explicit in execute() method documentation
  - ✅ Edge case handled: flatten with no position returns empty executed_orders list
  
  **Validation Evidence:**
  - ✅ ruff check: pass
  - ✅ ruff format: pass
  - ✅ mypy: pass (21 source files)
  - ✅ pytest: 104 passed (17 new tests for broker, all passing)
  
  **Minimal Diff:**
  - ✅ Only touched scoped files
  - ✅ No refactoring of existing code
  - ✅ Type extensions placed in correct location (EXECUTION LAYER section)
  
  **Risks Acknowledged:**
  - Position tracking is baseline (documented limitation for future enhancement)
  - Kill-switch flattens per-symbol not portfolio-wide (orchestrator responsibility)
  
  **Verdict:** All acceptance criteria met. Implementation is deterministic, well-tested, and respects authority boundaries. Code is production-ready for lab simulation use case.
  
  APPROVED: QEFC-013

## Final Gate
**Ready-to-Commit Statement**
- [x] Criteria met
- [x] Checks green locally
- [x] Minimal diff verified

READY_FOR_REVIEW: QEFC-013