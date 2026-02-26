# QEFC-009 — Expand Instrument Registry: Add Multi-Asset Coverage (FX, Indices, Commodities, Crypto)

## Meta
- Status: IN_PROGRESS
- Owner: Quant-Engineer
- Priority: P2
- Branch: bot/QEFC-009-expand-instrument-registry-add-multi-asset-cover
- Scope (files):
  - `config/instruments.yaml` (modify - add new instruments)
  - `tests/test_instrument_registry.py` (optional - add validation tests for new instruments)
- Acceptance Criteria:
  - Minimum 20 total instruments across 4 asset classes (FX, Indices, Commodities, Crypto)
  - All instruments have required fields: symbol, tick_size, point_value, contract_size, min_lot, max_lot, lot_step
  - Valid YAML syntax maintained
  - At least 7 FX pairs (current: 1, add: 6)
  - At least 5 indices (current: 1, add: 4)
  - At least 4 commodities (current: 1, add: 3)
  - At least 4 crypto instruments (current: 0, add: 4)
  - All validation commands pass (ruff, mypy, pytest)
  - Registry loads all instruments without errors
- Validation Commands:
  - ruff check .
  - ruff format .
  - mypy .
  - pytest -q

---

## Handoff Packets

### Handoff 1 — Orchestrator → Quant-Engineer
**Goal**
- Expand the Instrument Registry to cover multiple asset classes for portfolio diversification
- Enable Sovereign Allocator to construct diversified portfolios across FX, Indices, Commodities, and Crypto
- Support correlation-based portfolio constraints and multi-instrument strategies
- Establish realistic observable space for production trading system

**Context from ORG_DOCTRINE.md:**
- "Allocator manages diversification" (ORG_DOCTRINE §6.2)
- "Correlation caps belong exclusively to the portfolio layer" (ORG_DOCTRINE §4)
- "Portfolio diversification: Allocator-bound" (ORG_DOCTRINE §11)
- InstrumentSpec supports asset_class field for classification (FX, COMMODITY, INDEX, CRYPTO)
- Current coverage: 3 instruments (1 FX, 1 Index, 1 Commodity, 0 Crypto) - insufficient for diversified portfolio

**Scope (Files to Modify)**

**A) Modify: `config/instruments.yaml`**

Expand from 3 instruments to minimum 20 instruments across 4 asset classes.

**Required Additions:**

**1. FX Pairs (add 6, total 7):**
- Current: EURUSD
- Add:
  - GBPUSD (British Pound / US Dollar)
  - USDJPY (US Dollar / Japanese Yen)
  - AUDUSD (Australian Dollar / US Dollar)
  - USDCHF (US Dollar / Swiss Franc)
  - NZDUSD (New Zealand Dollar / US Dollar)
  - USDCAD (US Dollar / Canadian Dollar)

**2. Indices (add 4, total 5):**
- Current: US100 (Nasdaq 100)
- Add:
  - SPX or US500 (S&P 500)
  - US30 (Dow Jones Industrial Average)
  - GER30 or DAX (German DAX 30)
  - JP225 (Nikkei 225)

**3. Commodities (add 3, total 4):**
- Current: XAUUSD (Gold)
- Add:
  - XAGUSD (Silver / US Dollar)
  - USOIL or WTI (West Texas Intermediate Crude Oil)
  - UKOIL or BRENT (Brent Crude Oil)

**4. Crypto (add 4, total 4):**
- Current: None
- Add:
  - BTCUSD (Bitcoin / US Dollar)
  - ETHUSD (Ethereum / US Dollar)
  - BNBUSD (Binance Coin / US Dollar)
  - ADAUSD (Cardano / US Dollar)

**Field Specifications per Asset Class:**

All instruments must have these fields:
- `symbol`: String identifier
- `tick_size`: Minimum price movement
- `point_value`: Dollar value per 1.0 point move per 1.0 lot
- `contract_size`: Standard contract size
- `min_lot`: Minimum position size
- `max_lot`: Maximum position size
- `lot_step`: Lot size increment

**Realistic Values by Asset Class:**

**FX Pairs:**
- tick_size: 0.00001 (5 decimal places for majors), 0.001 (3 decimals for JPY pairs)
- point_value: 10.0 (per standard lot)
- contract_size: 100000 (standard lot)
- min_lot: 0.01
- max_lot: 50.0 to 100.0
- lot_step: 0.01

**Indices:**
- tick_size: 0.01 to 1.0 (varies by broker)
- point_value: 10.0 to 25.0 (varies: US100=10, SPX=50, US30=10, GER30=25, JP225=10)
- contract_size: 1 (CFD)
- min_lot: 0.1 to 0.01
- max_lot: 10.0 to 50.0
- lot_step: 0.1 or 0.01

**Commodities:**
- tick_size: 0.01 (metals), 0.01 (oil)
- point_value: 100.0 (gold/silver), 10.0 (oil)
- contract_size: 100 (metals), 1000 (oil barrels)
- min_lot: 0.01
- max_lot: 50.0 to 100.0
- lot_step: 0.01

**Crypto:**
- tick_size: 0.01 to 0.1 (varies by asset value)
- point_value: 1.0 to 10.0 (varies by broker CFD specs)
- contract_size: 1 (1 coin CFD)
- min_lot: 0.01 to 0.1
- max_lot: 10.0 to 50.0
- lot_step: 0.01 to 0.1

**Example YAML Structure for Each Asset Class:**

```yaml
instruments:
  # Existing instruments (keep unchanged)
  XAUUSD:
    symbol: XAUUSD
    tick_size: 0.01
    point_value: 100.0
    contract_size: 100
    min_lot: 0.01
    max_lot: 100.0
    lot_step: 0.01
  
  # ... existing EURUSD, US100 ...
  
  # FX - New additions
  GBPUSD:
    symbol: GBPUSD
    tick_size: 0.00001
    point_value: 10.0
    contract_size: 100000
    min_lot: 0.01
    max_lot: 100.0
    lot_step: 0.01
  
  USDJPY:
    symbol: USDJPY
    tick_size: 0.001
    point_value: 10.0
    contract_size: 100000
    min_lot: 0.01
    max_lot: 100.0
    lot_step: 0.01
  
  # Indices - New additions
  SPX:
    symbol: SPX
    tick_size: 0.01
    point_value: 50.0
    contract_size: 1
    min_lot: 0.01
    max_lot: 10.0
    lot_step: 0.01
  
  US30:
    symbol: US30
    tick_size: 1.0
    point_value: 10.0
    contract_size: 1
    min_lot: 0.1
    max_lot: 20.0
    lot_step: 0.1
  
  # Commodities - New additions
  XAGUSD:
    symbol: XAGUSD
    tick_size: 0.01
    point_value: 50.0
    contract_size: 5000
    min_lot: 0.01
    max_lot: 50.0
    lot_step: 0.01
  
  USOIL:
    symbol: USOIL
    tick_size: 0.01
    point_value: 10.0
    contract_size: 1000
    min_lot: 0.01
    max_lot: 50.0
    lot_step: 0.01
  
  # Crypto - New additions
  BTCUSD:
    symbol: BTCUSD
    tick_size: 0.1
    point_value: 1.0
    contract_size: 1
    min_lot: 0.01
    max_lot: 10.0
    lot_step: 0.01
  
  ETHUSD:
    symbol: ETHUSD
    tick_size: 0.01
    point_value: 1.0
    contract_size: 1
    min_lot: 0.1
    max_lot: 50.0
    lot_step: 0.1
```

**Note on Values:**
- Values are realistic but simplified for demonstration
- Actual broker specs may vary (MT5, MT4, cTrader, etc.)
- point_value and contract_size should match target broker's CFD specifications
- For production, consult broker's instrument specification sheets

**B) Optional: Update Tests (`tests/test_instrument_registry.py`)**

Consider adding test cases to validate:
1. All 20+ instruments load successfully
2. Each asset class is represented (FX count >= 7, Indices >= 5, Commodities >= 4, Crypto >= 4)
3. No duplicate symbols
4. All instruments have positive values for required numeric fields
5. calc_lot_from_risk works correctly for instruments from each asset class

**Example Test (optional):**
```python
def test_multi_asset_coverage() -> None:
    """Test that registry covers multiple asset classes."""
    registry = InstrumentRegistry()
    symbols = registry.list_symbols()
    
    # Minimum coverage requirements
    assert len(symbols) >= 20, f"Expected >= 20 instruments, got {len(symbols)}"
    
    # Test samples from each asset class
    fx_samples = ["EURUSD", "GBPUSD", "USDJPY"]
    index_samples = ["US100", "SPX", "US30"]
    commodity_samples = ["XAUUSD", "XAGUSD", "USOIL"]
    crypto_samples = ["BTCUSD", "ETHUSD"]
    
    for sample in fx_samples + index_samples + commodity_samples + crypto_samples:
        assert sample in symbols, f"Expected {sample} in registry"
```

**Constraints**

1. **Minimal Diff:**
   - Only modify `config/instruments.yaml`
   - Optional: add test cases to `tests/test_instrument_registry.py`
   - No changes to `core/instrument_registry.py` (existing implementation handles arbitrary instrument count)

2. **No Breaking Changes:**
   - Keep existing 3 instruments (XAUUSD, EURUSD, US100) unchanged
   - Only add new instruments (append-only)
   - Maintain YAML structure and field naming

3. **Doctrine Compliance:**
   - Supports Allocator diversification requirements (ORG_DOCTRINE §4)
   - Enables correlation-based portfolio construction
   - No agent code changes (passive spec source)

4. **Data Quality:**
   - All numeric fields must be positive (> 0)
   - tick_size, point_value, contract_size must be realistic
   - min_lot <= max_lot
   - lot_step <= (max_lot - min_lot)

5. **YAML Validity:**
   - Maintain proper indentation (2 spaces)
   - Valid YAML syntax (test with yaml.safe_load)
   - UTF-8 encoding

**Risks / Open Questions**

- **Risk**: Broker-specific specs may vary (point_value, contract_size) → Mitigate: Use common CFD broker specs (e.g., IC Markets, OANDA)
- **Risk**: Crypto specs highly variable across brokers → Mitigate: Use standardized CFD contract sizes (1 coin = 1 contract)
- **Risk**: Too many instruments may overwhelm testing → Mitigate: Keep to minimum 20, maximum 30
- **Question**: Should we add asset_class field to InstrumentSpec? → Answer: Deferred to future task (would require schema change)
- **Question**: Should we validate min_lot/max_lot constraints? → Answer: Optional for this sprint, focus on expansion
- **Question**: Include exotic pairs or only majors? → Answer: Majors only for Sprint 2 (EURUSD, GBPUSD, USDJPY, AUDUSD, USDCHF, NZDUSD, USDCAD)

**Acceptance Criteria** (from Meta, expanded)

1. **Coverage Requirements:**
   - Total instruments: >= 20
   - FX pairs: >= 7 (current 1 + add 6)
   - Indices: >= 5 (current 1 + add 4)
   - Commodities: >= 4 (current 1 + add 3)
   - Crypto: >= 4 (current 0 + add 4)

2. **Data Quality:**
   - All instruments have 7 required fields (symbol, tick_size, point_value, contract_size, min_lot, max_lot, lot_step)
   - All numeric fields > 0
   - Valid YAML syntax
   - UTF-8 encoding

3. **Registry Loading:**
   - InstrumentRegistry loads all instruments without errors
   - list_symbols() returns all 20+ symbols
   - get() works for all new instruments
   - calc_lot_from_risk() works for samples from each asset class

4. **Code Quality:**
   - `ruff check .` → All checks passed!
   - `ruff format .` → Files formatted or unchanged
   - `mypy .` → Success: no issues found
   - `pytest -q` → All tests pass (existing + optional new tests)

5. **No Breaking Changes:**
   - Existing 3 instruments unchanged (XAUUSD, EURUSD, US100)
   - Existing tests still pass
   - No changes to core/instrument_registry.py

**Validation Steps**

1. Run `ruff check .` → verify no linting errors
2. Run `mypy .` → verify type hints still correct
3. Run `pytest -q` → verify all tests pass
4. Manual smoke test:
   ```python
   from core.instrument_registry import InstrumentRegistry
   
   reg = InstrumentRegistry()
   symbols = reg.list_symbols()
   print(f"Total instruments: {len(symbols)}")  # Should be >= 20
   print(f"Symbols: {sorted(symbols)}")
   
   # Test samples from each asset class
   for symbol in ["GBPUSD", "SPX", "XAGUSD", "BTCUSD"]:
       spec = reg.get(symbol)
       print(f"{symbol}: {spec}")
       
       # Test lot calculation
       lot = reg.calc_lot_from_risk(100.0, 50.0, symbol)
       print(f"  Lot size for $100 risk, 50pt SL: {lot}")
   ```

**Next Actions for Quant-Engineer**

1. Review current `config/instruments.yaml` (3 instruments)
2. Add minimum 17 new instruments (6 FX, 4 Indices, 3 Commodities, 4 Crypto)
3. Use realistic but simplified broker specs (refer to handoff examples)
4. Maintain YAML formatting and structure
5. Optional: Add test case for multi-asset coverage
6. Run all validation commands
7. Test registry loading with expanded instrument set
8. Document implementation in this ledger
9. Mark task READY_FOR_REVIEW and update TASKBOARD status to REVIEW

**Research References (for realistic specs):**
- IC Markets Contract Specifications: https://www.icmarkets.com/global/en/trading-conditions/contract-specifications
- OANDA FX/Indices/Commodities specs
- Common CFD broker specifications for crypto (1 coin = 1 contract standard)
- MT5/MT4 symbol specifications

**Doctrine Alignment:**
- ✓ Supports "Allocator manages diversification" (ORG_DOCTRINE §6.2)
- ✓ Enables "Correlation caps belong to portfolio layer" (ORG_DOCTRINE §4)
- ✓ Facilitates "Portfolio construction + position sizing" (ORG_DOCTRINE §2.4)
- ✓ No violation of authority boundaries (passive spec source)
- ✓ Governed Extension Layer work (not Immutable Core)

---

## Implementation Updates

### 2026-02-26 20:50 — Quant-Engineer — Implementation Complete

**Files Modified:**
- `config/instruments.yaml` (+173 lines) - Added 17 new instruments across 4 asset classes
- `tests/test_instrument_registry.py` (+96 lines) - Added 7 new test cases for multi-asset validation

**Changes Summary:**

1. **Instrument Expansion (config/instruments.yaml)**
   - Added 6 FX pairs: GBPUSD, USDJPY, AUDUSD, USDCHF, NZDUSD, USDCAD
   - Added 4 indices: SPX, US30, GER30, JP225
   - Added 3 commodities: XAGUSD, USOIL, UKOIL
   - Added 4 crypto: BTCUSD, ETHUSD, BNBUSD, ADAUSD
   - Total instruments: 20 (was 3, added 17)
   - All instruments have 7 required fields with realistic broker specs
   - Grouped by asset class with comments for clarity

2. **Test Coverage (tests/test_instrument_registry.py)**
   - Added new test class: `TestMultiAssetCoverage`
   - 7 new test cases:
     - `test_minimum_instrument_count` - Validates >= 20 instruments
     - `test_fx_coverage` - Validates >= 7 FX pairs
     - `test_index_coverage` - Validates >= 5 indices
     - `test_commodity_coverage` - Validates >= 4 commodities
     - `test_crypto_coverage` - Validates >= 4 crypto instruments
     - `test_all_new_instruments_loadable` - Validates all 17 new instruments load correctly
     - `test_calc_lot_from_risk_across_asset_classes` - Validates lot calculation for each asset class

**Validation Results:**
```
✓ ruff check . → All checks passed!
✓ mypy . → Success: no issues found in 12 source files
✓ pytest -q → 46 passed, 20 warnings in 0.31s (39 existing + 7 new)
```

**Instrument Specifications Used:**

FX Pairs (realistic major pair specs):
- tick_size: 0.00001 (5 decimals) for majors, 0.001 (3 decimals) for JPY pairs
- point_value: 10.0 per standard lot
- contract_size: 100000 (standard lot)
- min_lot: 0.01, max_lot: 100.0, lot_step: 0.01

Indices (CFD specs):
- tick_size: 0.01 to 1.0 (varies by index)
- point_value: 10.0 to 50.0 (SPX=50, US30/US100/JP225=10, GER30=25)
- contract_size: 1 (CFD)
- min_lot: 0.01 to 0.1, max_lot: 10.0 to 50.0, lot_step: 0.01 to 0.1

Commodities (metals & oil CFD specs):
- tick_size: 0.01
- point_value: 50.0 (silver), 10.0 (oil)
- contract_size: 5000 (silver), 1000 (oil barrels)
- min_lot: 0.01, max_lot: 50.0, lot_step: 0.01

Crypto (CFD specs, 1 coin = 1 contract):
- tick_size: 0.0001 to 0.1 (varies by asset value)
- point_value: 1.0
- contract_size: 1 (1 coin)
- min_lot: 0.01 to 1.0, max_lot: 10.0 to 100.0, lot_step: 0.01 to 1.0

**Risks Mitigated:**
- Used standard CFD broker specs (IC Markets style)
- Kept crypto specs simple (1 coin = 1 contract standard)
- All numeric fields > 0, min_lot <= max_lot validated in tests
- YAML syntax validated (yaml.safe_load works correctly)

**Doctrine Compliance:**
- ✓ Supports Allocator diversification requirements (ORG_DOCTRINE §6.2)
- ✓ Enables correlation-based portfolio construction (ORG_DOCTRINE §4)
- ✓ No changes to core/instrument_registry.py (passive spec source)
- ✓ No authority boundary violations (Governed Extension Layer work only)

**Deterministic Proof:**
- Ran pytest 3 times → Same 46 passed results each time
- YAML loading is deterministic (no randomness)
- All test assertions use exact value checks or bounded range checks

**Acceptance Criteria Verification:**
- [x] Total instruments: 20 >= 20 ✓
- [x] FX pairs: 7 >= 7 ✓
- [x] Indices: 5 >= 5 ✓
- [x] Commodities: 4 >= 4 ✓
- [x] Crypto: 4 >= 4 ✓
- [x] All instruments have 7 required fields ✓
- [x] Valid YAML syntax ✓
- [x] All validation commands pass ✓
- [x] Registry loads all instruments without errors ✓
- [x] No breaking changes to existing instruments ✓

**Ready for Review:** YES

---

**READY_FOR_REVIEW: QEFC-009**

## Review Notes
- (timestamp) ...

## Review Notes
- (timestamp) ...

## Final Gate
**Ready-to-Commit Statement**
- [ ] Criteria met
- [ ] Checks green locally
- [ ] Minimal diff verified