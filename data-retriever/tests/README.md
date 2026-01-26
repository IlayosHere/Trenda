# MT5 Trading Test Suite

Comprehensive test suite for MT5 trading functionality with 56 tests covering all aspects of trading operations.

## 📝 Note: Two Test Runners

There are **two different test runners** in this directory:

1. **`run_tests.py`** - Runs only the 56 tests from `test_mt5_trading.py` (this file)
2. **`run_all_tests.py`** - Runs ALL test files (1000+ test cases across multiple files)

## 🚀 Quick Start: Run ALL Tests

### Run the 56 tests from test_mt5_trading.py:
```bash
python tests/run_tests.py
```

### Run ALL test files (comprehensive suite):
```bash
python tests/run_all_tests.py
```

This runs all 56 tests automatically.

## 📋 Running Tests

### Run All Tests (56 tests)
```bash
python tests/run_tests.py
```

### Run Specific Tests
```bash
python tests/run_tests.py 38 39 40
# Runs only tests 38, 39, and 40
```

## 📊 Test Categories & Details

### Core Operations (1-10)
Basic trading operations: initialization, order placement, position verification, closing.

- **Test 1**: MT5 initialization
- **Test 2**: Place BUY order with SL/TP
- **Test 3**: Verify position matching
- **Test 4**: Verify position idempotence
- **Test 5**: Symbol constraint (active block)
- **Test 6**: Symbol constraint (different allowed)
- **Test 7**: Close position
- **Test 8**: Cooldown constraint
- **Test 9**: Place SELL order with SL/TP
- **Test 10**: Magic number filtering

### Logic (11)
Constraint logic precision tests.

### Edge Cases (12-16)
Invalid inputs, edge cases, error handling.

- **Test 12**: Invalid symbol
- **Test 13**: Zero volume
- **Test 14**: Invalid order type
- **Test 15**: Negative SL/TP
- **Test 16**: Close invisible ticket

### Stress (17)
Burst stress testing with multiple symbols.

### Extended (19-37)
Connection handling, retry logic, verification, concurrency, error categorization.

- **Test 19**: Connection reinit
- **Test 20**: Connection failure
- **Test 21**: Zero price failure
- **Test 22**: Symbol visibility
- **Test 23**: Price normalization
- **Test 24**: Tick failure
- **Test 25**: Retry logic success
- **Test 26**: Retry exhaustion
- **Test 27**: Verification leak
- **Test 28**: Mismatch triggers close
- **Test 29**: Verification missing position
- **Test 30**: Concurrency stress
- **Test 31**: Trade mode validation
- **Test 32**: SL/TP distance validation
- **Test 33**: Close frozen retry
- **Test 34**: Verify volume mismatch
- **Test 35**: Verify slippage mismatch
- **Test 36**: JPY position consistency
- **Test 37**: Market moved retry

### New Comprehensive (38-46)
Recently added comprehensive tests:

- **Test 38**: Volume normalization with `volume_step` (0.13 with step 0.1 → 0.1)
- **Test 39**: Order returns DONE but `positions_get()` returns empty
- **Test 40**: MT5 ticket reuse - symbol validation
- **Test 41**: Trade mode changes to CLOSEONLY between validation and sending
- **Test 42**: Expiration time timezone handling (MT5 vs our timezone)
- **Test 43**: Main loop stops on fatal error (system shutdown)
- **Test 44**: PARTIAL_SUCCESS (10010) error handling
- **Test 45**: MARKET_CLOSED (10018) error handling
- **Test 46**: AutoTrading disabled (10026) is FATAL

### Edge Cases & Bugs (47-56)
Comprehensive edge case tests to find potential bugs:

- **Test 47**: Volume normalization edge cases (boundaries, invalid values, precision)
- **Test 48**: Price normalization edge cases (negative, zero, high precision)
- **Test 49**: SL/TP distance validation edge cases (minimum distance, zero stops)
- **Test 50**: Expiration time edge cases (zero, large, None tick)
- **Test 51**: All error codes properly categorized
- **Test 52**: Symbol validation edge cases (empty, whitespace, None)
- **Test 53**: Volume zero and negative validation
- **Test 54**: Price zero and negative validation
- **Test 55**: Retry infinite loop prevention
- **Test 56**: Fresh price validation in retry mechanism

### Shutdown (18)
MT5 shutdown and cleanup.

## ✅ What to Expect

When you run all tests:
1. MT5 will be initialized
2. Tests will run sequentially
3. Each test shows PASS/FAIL
4. Summary at the end shows: `X/56 Passed`
5. Exit code: 0 = all passed, 1 = some failed

## 🔧 Requirements

- MT5 must be open and logged into a DEMO account
- Python 3.7+
- All dependencies installed
- Algo Trading enabled in MT5

## 📝 Test Details

### Volume Normalization (Test 38, 47)
Tests that volume is correctly normalized to `volume_step`:
- 0.13 with step 0.1 → 0.1 (rounds down)
- 0.15 with step 0.1 → 0.2 (rounds up)
- Boundary conditions (min/max)
- Invalid values (zero, negative)
- Floating point precision

### Order DONE but Position Missing (Test 39)
Tests edge case where MT5 returns DONE but position doesn't appear immediately.
- Verification handles this gracefully
- Returns True (treats as already closed)

### Ticket Reuse Protection (Test 40)
Explains why ticket reuse won't happen:
- We verify immediately after opening
- We track positions in database
- We use magic numbers to filter
- We verify symbol matches
- Positions close quickly (hours/days, not months/years)

### Trade Mode Changes (Test 41)
Tests trade mode validation:
- CLOSEONLY mode is detected and rejected
- If mode changes between validation and sending, MT5 returns error 10017
- Error is categorized as FATAL

### Expiration Timezone (Test 42, 50)
Tests expiration time calculation:
- Uses MT5 `tick.time` (server timezone)
- No timezone conversion needed
- Ensures no mismatch between calculation and MT5 interpretation
- Edge cases: zero, large values, None tick

### Fatal Error Shutdown (Test 43)
Tests system shutdown on fatal errors:
- `shutdown_system()` sets shutdown flag
- Main loop checks flag every iteration
- System exits on critical failures

### Error Code Handling (Test 44, 45, 46, 51)
Tests error categorization:
- **10010 (PARTIAL_SUCCESS)**: Not retryable, not fatal
- **10018 (MARKET_CLOSED)**: Not fatal, not immediately retryable
- **10026 (AutoTrading disabled)**: FATAL, should abort
- All known error codes properly categorized

### Validation Edge Cases (Test 48, 49, 52, 53, 54)
Tests input validation:
- Negative prices/SL/TP
- Zero prices/volumes
- Empty/whitespace symbols
- High precision rounding
- SL/TP distance validation

### Retry Mechanism (Test 55, 56)
Tests retry logic:
- Infinite loop prevention
- Fresh price validation
- Invalid price handling

## 🐛 Troubleshooting

### MT5 Not Initialized
If tests fail with "MT5 initialization failed":
1. Ensure MT5 is running
2. Ensure you're logged into a DEMO account
3. Check MT5 connection settings

### Test Timeout
Some tests may take time due to:
- Network latency
- MT5 server response time
- Retry logic delays

### Permission Errors
If you get permission errors:
- Ensure MT5 allows automated trading
- Check that Algo Trading is enabled in MT5

## 💡 Additional Options

- `python tests/run_tests.py --list` - List all available tests
- `python tests/run_tests.py --new` - Run only new tests (38-46)
- `python tests/run_tests.py --edge` - Run edge case tests (47-56)
- `python tests/run_tests.py --all-new` - Run all new tests (38-56)
