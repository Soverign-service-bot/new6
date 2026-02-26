# QEFC-010 — Sprint 2: Implement QLF Meta-Engine (core/qefc_engine.py)

## Meta
- Status: READY_TO_COMMIT
- Owner: Quant-Engineer
- Priority: P0
- Branch: bot/QEFC-010-sprint-2-implement-qlf-meta-engine-core-qefc-eng
- Scope (files):
  - `core/qefc_engine.py` (create)
  - `core/types.py` (modify — add PortfolioState if missing, update QEFCState enum)
  - `tests/test_qefc_engine.py` (create)
- Acceptance Criteria:
  - QEFC Engine implements QLF state machine with base states {T, C, N, F}
  - W (Withdrawal) is a **supervisory override** that forces risk_factor = 0.0
  - F→T direct transition is **forbidden** (irreversibility constraint)
  - Cooldown: After W or F, T is blocked for `cooldown_bars` (default 4)
  - Dimensional compression: < 10 internal variables before state collapse
  - All validation commands pass (ruff, mypy, pytest)
  - Unit tests prove: (a) W overrides T, (b) cooldown blocks T after W/F, (c) F→T forbidden
- Validation Commands:
  - ruff check .
  - ruff format .
  - mypy .
  - pytest -q

---

## Handoff Packets

### Handoff 1 — Orchestrator → Quant-Engineer
**Goal**
- Implement the QEFC Meta-Engine — the "decision-about-decision" core of Sovereign-Quant
- File: `core/qefc_engine.py`
- Class: `QEFCEngine`
- Core Method: `evaluate(self, signals: List[AgentSignal], regime: RegimeInfo, portfolio: PortfolioState) -> QEFCDecision`

**Doctrine Reference (ORG_DOCTRINE.md §9)**
- QEFC = "decision-about-decision" — not indicator, not strategy
- QEFC is Epistemic Governor, not data processor
- QEFC core logic ≤ 300 LOC (per v2.2.2)
- Dimensional Compression Law: < 10 meta-dimensions before state collapse (per v2.2.2 §III)

---

## QLF State Topology (QECF Theoretical Framework)

### Base Epistemic States: {T, C, N, F}
```
T = True      → High alignment, full allocation (risk_factor ≈ 1.0)
C = Conflict  → Mixed evidence, half-risk / hedge (risk_factor ≈ 0.5)
N = Neutral   → Insufficient confirmation, wait (risk_factor = 0.0)
F = False     → Toxic regime, withdraw (risk_factor = 0.0)
```

### Supervisory Override: W (Withdrawal)
```
W = Withdrawal → Emergency override, close all + freeze (risk_factor = 0.0)
```
**W is NOT a base epistemic state.**
W is a **supervisory override** that:
- Forces `QEFCDecision.risk_factor = 0.0` regardless of signal fusion result
- Is triggered by portfolio/regime conditions (drawdown, divergence, equity breach)
- Has asymmetric authority — cannot be overridden by high consensus

### Topology Constraints (MUST BE ENFORCED)

**1. Separation of SupervisorState from Inference**
```
┌─────────────────────────────────────────────────────────────┐
│                    QEFCEngine                               │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐    ┌─────────────────────────────┐ │
│  │  Signal Fusion      │    │  SupervisorState            │ │
│  │  (Pure Inference)   │    │  (External State Tracker)   │ │
│  │                     │    │                             │ │
│  │  signals → {T,C,N,F}│    │  - cooldown_counter: int    │ │
│  │                     │    │  - W_lock: bool             │ │
│  │  No side effects    │    │  - previous_final_state     │ │
│  │  No mutation        │    │  - bars_since_W: int        │ │
│  └─────────────────────┘    │  - bars_since_F: int        │ │
│            │                └─────────────────────────────┘ │
│            ▼                             │                  │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              Final State Resolution                     ││
│  │  Apply W override → Apply cooldown → Emit QEFCDecision  ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

**Key Principle**: QEFCEngine may **READ** supervisor state but must **NOT reset W internally** without explicit supervisor rules.

**2. Irreversibility Constraint**
```
F → T : FORBIDDEN (even if signals strongly indicate T)

Allowed transitions from F:
  F → N (neutral recovery)
  F → C (partial recovery)
  F → F (remain toxic)
  F → W (override)
```

**3. Cooldown Mechanism**
```
If previous_final_state ∈ {W, F}:
    cooldown_bars_remaining = cooldown_bars - bars_since_{W|F}
    
    If cooldown_bars_remaining > 0:
        T is BLOCKED → force state to N (wait)
    
Default: cooldown_bars = 4
```

---

## Required Implementation — QECF Theoretical Controls

### 1. Signal Fusion (Multiverse Operator)
- Resolve conflicting Agent signals into a base state: {T, C, N, F}
- Algorithm:
  ```python
  consensus_score = weighted_sum(signal.intent * signal.confidence)
  conflict_intensity = std(signal_intents) or entropy measure
  
  if consensus_score > HIGH_THRESHOLD and conflict_intensity < LOW:
      base_state = T
  elif conflict_intensity > HIGH_THRESHOLD:
      base_state = C
  elif consensus_score < LOW_THRESHOLD:
      base_state = F
  else:
      base_state = N  # Neutral (was S in old terminology)
  ```
- **Pure function**: No side effects, no mutation of supervisor state
- Returns `base_state` before override checks

### 2. Withdrawal Control (W) — Supervisory Override
- W is triggered when **ANY** of:
  - `portfolio.drawdown_pct > MAX_DRAWDOWN_THRESHOLD` (default: 10%)
  - `regime.divergence_score > DIVERGENCE_THRESHOLD` (default: 0.8)
  - `portfolio.equity_floor_breach == True`
  - External kill-switch flag (future)
- W effects:
  - `state = W`
  - `risk_factor = 0.0`
  - `reason_codes = ["W_OVERRIDE", <trigger_reason>]`
  - Update supervisor state: `W_lock = True`, reset `bars_since_W = 0`
- **Asymmetric Authority**: W **cannot** be overridden by high consensus

### 3. Cooldown Enforcement
- **After W**: Block T for `cooldown_bars` (default: 4)
- **After F**: Block T for `cooldown_bars` (default: 4)
- Implementation:
  ```python
  if supervisor.bars_since_W < cooldown_bars:
      if fused_state == T:
          final_state = N  # Block T, force wait
  
  if supervisor.bars_since_F < cooldown_bars:
      if fused_state == T:
          final_state = N  # Block T, force wait
  ```

### 4. F→T Transition Block (Irreversibility)
- **FORBIDDEN**: `previous_final_state == F` and `fused_state == T`
- Implementation:
  ```python
  if supervisor.previous_final_state == F and fused_state == T:
      final_state = N  # Force through N first
      reason_codes.append("F_TO_T_BLOCKED")
  ```
- This is **separate** from cooldown — even if cooldown expired, F→T is forbidden

---

## Dimensional Compression (Mandatory per v2.2.2 §III)

Before state collapse, reduce inputs to ≤ 10 meta-features:
```python
@dataclass
class CompressedMeta:
    """< 10 dimensions for QEFC state collapse."""
    consensus_score: float        # 1. Weighted signal agreement
    conflict_intensity: float     # 2. Signal disagreement measure
    regime_confidence: float      # 3. From RegimeInfo
    divergence_score: float       # 4. From RegimeInfo
    drawdown_pct: float           # 5. From PortfolioState
    equity_floor_breach: bool     # 6. From PortfolioState
    volatility_anomaly: bool      # 7. Derived flag
    # Supervisor state (read-only)
    bars_since_W: int             # 8. Cooldown tracking
    bars_since_F: int             # 9. Cooldown tracking
```
Total: **9 dimensions** (under 10 limit)

---

## Data Contracts

### Input: `PortfolioState` (add to core/types.py if missing)
```python
@dataclass(frozen=True)
class PortfolioState:
    """Read-only portfolio snapshot for QEFC consumption."""
    equity: float
    balance: float
    drawdown_pct: float  # Current drawdown as percentage (0-100)
    open_positions: int
    margin_used_pct: float
    equity_floor_breach: bool = False
    timestamp: datetime = field(default_factory=datetime.utcnow)
```

### Output: `QEFCDecision` (update in core/types.py)
```python
@dataclass(frozen=True)
class QEFCDecision:
    state: QEFCState          # T, C, N, F, or W
    risk_factor: float        # ∈ [0, 1]
    reason_codes: List[str] = field(default_factory=list)
    cooldown_bars: int = 0    # Bars remaining in cooldown
    timestamp: datetime = field(default_factory=datetime.utcnow)
```

### Update: `QEFCState` enum (in core/types.py)
```python
class QEFCState(str, Enum):
    """
    Quaternary Logic Framework State
    
    Base epistemic states: {T, C, N, F}
    Supervisory override: W
    """
    T = "T"  # True - alignment
    C = "C"  # Conflict - mixed evidence
    N = "N"  # Neutral - insufficient confirmation (replaces S)
    F = "F"  # False - toxic regime
    W = "W"  # Withdrawal - supervisory override
```

---

## Class Structure

```python
@dataclass
class SupervisorState:
    """External state tracker for cooldown and W-lock."""
    previous_final_state: QEFCState = QEFCState.N
    bars_since_W: int = 999  # Large default = no recent W
    bars_since_F: int = 999  # Large default = no recent F
    W_lock: bool = False


class QEFCEngine:
    """QEFC Meta-Engine — Epistemic Capital Governor."""
    
    def __init__(
        self,
        consensus_threshold_high: float = 0.7,
        consensus_threshold_low: float = 0.3,
        conflict_threshold: float = 0.5,
        max_drawdown_pct: float = 10.0,
        divergence_threshold: float = 0.8,
        cooldown_bars: int = 4,  # Default cooldown after W or F
    ) -> None:
        self._supervisor = SupervisorState()
        # Store thresholds...
    
    def evaluate(
        self,
        signals: List[AgentSignal],
        regime: RegimeInfo,
        portfolio: PortfolioState,
    ) -> QEFCDecision:
        """Core method — returns QEFC decision."""
        ...
    
    def _compress_inputs(self, signals, regime, portfolio) -> CompressedMeta:
        """Dimensional compression to < 10 features."""
        ...
    
    def _fuse_signals(self, meta: CompressedMeta) -> QEFCState:
        """Pure signal fusion → base state {T, C, N, F}."""
        ...
    
    def _should_trigger_W(self, meta: CompressedMeta, portfolio: PortfolioState) -> bool:
        """Check W override conditions."""
        ...
    
    def _update_supervisor(self, final_state: QEFCState) -> None:
        """Update supervisor state after decision."""
        ...
```

---

## Algorithm Pseudocode

```python
def evaluate(self, signals, regime, portfolio) -> QEFCDecision:
    # 1. Dimensional Compression
    meta = self._compress_inputs(signals, regime, portfolio)
    
    # 2. Check W Override (Supervisory Authority)
    if self._should_trigger_W(meta, portfolio):
        decision = self._emit_W(meta)
        self._update_supervisor(QEFCState.W)
        return decision
    
    # 3. Signal Fusion → Base State {T, C, N, F}
    fused_state = self._fuse_signals(meta)
    reason_codes = []
    
    # 4. Apply F→T Transition Block (Irreversibility)
    if self._supervisor.previous_final_state == QEFCState.F and fused_state == QEFCState.T:
        fused_state = QEFCState.N
        reason_codes.append("F_TO_T_BLOCKED")
    
    # 5. Apply Cooldown Barriers
    if fused_state == QEFCState.T:
        if self._supervisor.bars_since_W < self._cooldown_bars:
            fused_state = QEFCState.N
            reason_codes.append("W_COOLDOWN_ACTIVE")
        elif self._supervisor.bars_since_F < self._cooldown_bars:
            fused_state = QEFCState.N
            reason_codes.append("F_COOLDOWN_ACTIVE")
    
    # 6. Emit Decision
    final_state = fused_state
    risk_factor = self._state_to_risk_factor(final_state)
    
    decision = QEFCDecision(
        state=final_state,
        risk_factor=risk_factor,
        reason_codes=reason_codes,
        cooldown_bars=max(0, self._cooldown_bars - min(
            self._supervisor.bars_since_W,
            self._supervisor.bars_since_F
        )),
    )
    
    # 7. Update Supervisor State
    self._update_supervisor(final_state)
    
    return decision
```

---

## Acceptance Criteria

### 1. Code Quality
- `ruff check .` → All checks passed!
- `ruff format .` → Files formatted or unchanged
- `mypy .` → Success: no issues found
- `pytest -q` → All tests pass

### 2. Functional Requirements
- [ ] `QEFCEngine.evaluate()` returns `QEFCDecision`
- [ ] Base states {T, C, N, F} correctly mapped from signal fusion
- [ ] W state sets `risk_factor = 0.0` regardless of signals
- [ ] F→T direct transition is **forbidden** (blocked even after cooldown)
- [ ] T is blocked for `cooldown_bars` after W
- [ ] T is blocked for `cooldown_bars` after F
- [ ] Dimensional compression: < 10 internal variables

### 3. Unit Tests (MANDATORY)

```python
# tests/test_qefc_engine.py

class TestSignalFusion:
    """Test base state inference {T, C, N, F}."""
    def test_high_consensus_returns_T(self) -> None: ...
    def test_high_conflict_returns_C(self) -> None: ...
    def test_low_consensus_returns_F(self) -> None: ...
    def test_uncertain_returns_N(self) -> None: ...  # N replaces S


class TestWOverride:
    """Test W supervisory override behavior."""
    
    def test_W_overrides_T_on_high_drawdown(self) -> None:
        """
        MANDATORY: Even with perfect consensus (would be T),
        W triggers when drawdown_pct > threshold.
        Result: risk_factor = 0.0
        """
        ...
    
    def test_W_overrides_T_on_high_divergence(self) -> None:
        """
        MANDATORY: Even with perfect consensus (would be T),
        W triggers when divergence_score > threshold.
        Result: risk_factor = 0.0
        """
        ...
    
    def test_W_sets_risk_factor_zero(self) -> None:
        """W always sets risk_factor = 0.0."""
        ...


class TestCooldownMechanism:
    """Test cooldown barriers after W and F."""
    
    def test_T_blocked_after_W_until_cooldown_expires(self) -> None:
        """
        MANDATORY: After W, T is blocked for cooldown_bars.
        System returns N (wait) instead of T.
        """
        ...
    
    def test_T_blocked_after_F_until_cooldown_expires(self) -> None:
        """
        MANDATORY: After F, T is blocked for cooldown_bars.
        System returns N (wait) instead of T.
        """
        ...
    
    def test_T_allowed_after_cooldown_expires(self) -> None:
        """After cooldown expires, T is allowed (unless F→T)."""
        ...


class TestIrreversibility:
    """Test F→T forbidden constraint."""
    
    def test_F_to_T_transition_forbidden(self) -> None:
        """
        MANDATORY: F→T direct transition is FORBIDDEN.
        Even if cooldown has expired, F cannot go directly to T.
        System returns N instead.
        """
        ...
    
    def test_F_to_N_allowed(self) -> None:
        """F→N is allowed (neutral recovery)."""
        ...
    
    def test_F_to_C_allowed(self) -> None:
        """F→C is allowed (partial recovery)."""
        ...


class TestDimensionalCompression:
    """Test < 10 meta-features constraint."""
    def test_meta_features_count_under_10(self) -> None: ...
```

### 4. Doctrine Compliance
- [ ] QEFC core logic ≤ 300 LOC
- [ ] No portfolio sizing (Allocator's job)
- [ ] No order execution (Broker's job)
- [ ] No risk veto (Risk layer's job)
- [ ] Consumes RegimeInfo, does not compute it
- [ ] Returns immutable QEFCDecision
- [ ] SupervisorState separated from pure inference logic

---

## Risks / Open Questions

1. **Resolved**: State naming — use {T, C, N, F} + W (N replaces S)
2. **Open**: Exact consensus/conflict formulas — start simple, can refine later
3. **Risk**: State oscillation → mitigated by cooldown mechanism
4. **Risk**: Over-engineering → keep ≤ 300 LOC per doctrine
5. **Decision**: SupervisorState is internal to QEFCEngine but conceptually separate from fusion

---

## Implementation Updates

### 2026-02-26 22:45 — Quant-Engineer — Implementation Complete

**Files Modified:**
- `core/types.py` (+22 lines) — Updated QEFCState enum (S→N), added PortfolioState dataclass
- `core/qefc_engine.py` (253 lines) — Created QEFCEngine class with evaluate() method
- `tests/test_qefc_engine.py` (370 lines) — Created comprehensive unit tests
- `tests/test_type_contracts.py` (+1 line) — Updated QEFCState test (S→N)

**Implementation Summary:**

1. **QEFCState Enum Update (core/types.py)**
   - Replaced S (Suppressed) with N (Neutral) per QEFC/QLF terminology
   - W documented as "supervisory override" not base epistemic state
   - PortfolioState dataclass added for QEFC consumption

2. **QEFCEngine Implementation (core/qefc_engine.py)**
   - `SupervisorState` dataclass for cooldown/W-lock tracking (separated from inference)
   - `_CompressedMeta` dataclass with 9 dimensions (< 10 limit)
   - `evaluate()` method implements:
     - Dimensional compression
     - W supervisory override (risk_factor = 0.0)
     - Signal fusion → base states {T, C, N, F}
     - F→T transition block (irreversibility)
     - Cooldown barriers after W or F
   - LOC count: 253 (under 300 constraint)

3. **Unit Tests (tests/test_qefc_engine.py)**
   - `TestSignalFusion`: 5 tests for base state inference
   - `TestWOverride`: 4 tests proving W overrides signals
   - `TestCooldownMechanism`: 3 tests proving cooldown blocks T
   - `TestIrreversibility`: 3 tests proving F→T forbidden
   - `TestDimensionalCompression`: 2 tests for < 10 features
   - `TestSupervisorState`: 2 tests for state tracking
   - `TestRiskFactorMapping`: 4 tests for state→risk_factor

**Validation Results:**
```
✓ ruff check .    → All checks passed!
✓ ruff format .   → 3 files reformatted
✓ mypy .          → Success: no issues found in 14 source files
✓ pytest -q       → 69 passed, 105 warnings in 0.35s
```

**Acceptance Criteria Verification:**
- [x] `QEFCEngine.evaluate()` returns `QEFCDecision`
- [x] Base states {T, C, N, F} correctly mapped from signal fusion
- [x] W state sets `risk_factor = 0.0` regardless of signals
- [x] F→T direct transition is **forbidden** (blocked even after cooldown)
- [x] T is blocked for `cooldown_bars` after W (tested: `test_T_blocked_after_W_until_cooldown_expires`)
- [x] T is blocked for `cooldown_bars` after F (tested: `test_T_blocked_after_F_until_cooldown_expires`)
- [x] Dimensional compression: 9 internal variables (< 10) (tested: `test_meta_features_count_under_10`)

**Mandatory Test Evidence:**
- W overrides T: `test_W_overrides_T_on_high_drawdown`, `test_W_overrides_T_on_high_divergence`
- Cooldown blocks T: `test_T_blocked_after_W_until_cooldown_expires`, `test_T_blocked_after_F_until_cooldown_expires`
- F→T forbidden: `test_F_to_T_transition_forbidden`

**Doctrine Compliance:**
- [x] QEFC core logic ≤ 300 LOC (253 LOC actual)
- [x] No portfolio sizing (Allocator's job)
- [x] No order execution (Broker's job)
- [x] No risk veto (Risk layer's job)
- [x] Consumes RegimeInfo, does not compute it
- [x] Returns immutable QEFCDecision
- [x] SupervisorState separated from pure inference logic

**READY_FOR_REVIEW: QEFC-010**

## Review Notes
- 2026-02-26 23:10 — Reviewer-CI Gate Review
- Scope: Aligned with QEFC-010 declared scope (`core/qefc_engine.py`, `core/types.py`, `tests/test_qefc_engine.py`) with one justified adjacency update in `tests/test_type_contracts.py` to keep enum contract consistent after S→N transition.
- Minimal Diff: Changes remain focused on QEFCEngine + required contracts/tests; no unrelated refactor observed.
- Quality: Validation evidence present and green (`ruff check .`, `mypy .`, `pytest -q` with 69 passed).
- Doctrine: QLF topology honored (base states {T,C,N,F}, W supervisory override, cooldown + F→T irreversibility, dimensional compression under 10).
- Safety: No secrets/tokens introduced; no workflow/branch-protection weakening detected in scope.

READY_TO_COMMIT: QEFC-010

## Final Gate
**Ready-to-Commit Statement**
- [x] Criteria met
- [x] Checks green locally
- [x] Minimal diff verified

---

## Checkpoint

### Next Prompt to Trigger Quant-Engineer
```
Implement QEFC-010: Create core/qefc_engine.py with QEFCEngine class per Handoff 1 specifications.

Files in scope:
- core/qefc_engine.py (create)
- core/types.py (modify: add PortfolioState, update QEFCState enum to include N)
- tests/test_qefc_engine.py (create)

Key requirements:
1. Signal fusion → base states {T, C, N, F}
2. W supervisory override (risk_factor = 0.0)
3. F→T forbidden (irreversibility)
4. Cooldown bars = 4 after W or F before T allowed

Validation: ruff check ., mypy ., pytest -q

Mark READY_FOR_REVIEW when complete, update TASKBOARD status to REVIEW.
```

### Files in Scope
| File | Action | Description |
|------|--------|-------------|
| `core/qefc_engine.py` | CREATE | QEFCEngine class with evaluate() method |
| `core/types.py` | MODIFY | Add PortfolioState, update QEFCState enum (S→N) |
| `tests/test_qefc_engine.py` | CREATE | Mandatory unit tests per acceptance criteria |

### Expected Output Markers
- `READY_FOR_REVIEW` — Implementation complete, tests passing, awaiting review
- `READY_TO_COMMIT` — Review passed, minimal diff verified, ready for merge