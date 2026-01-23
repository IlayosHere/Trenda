# MT5 Test Suite - Detailed Documentation

## Overview

This comprehensive test suite validates the MT5 trading system across 13 different test categories, covering over 1000 test cases. The tests are designed to ensure reliability, catch bugs, and verify correct behavior under all conditions including edge cases, error scenarios, and real-world situations.

## Quick Start

**Run all tests with a single command:**
```bash
python tests/run_all_tests.py
```

**Run with verbose output:**
```bash
python tests/run_all_tests.py --verbose
```

**Run a specific category:**
```bash
python tests/run_all_tests.py --category "Error Codes"
```

## Test Categories Explained

### 1. All MT5 Error Codes (100+ tests)

**Purpose:** Ensures the system correctly handles and processes every known MT5 error code.

**What it tests:**
- **Error Code Recognition**: Verifies that all MT5 error codes (10004-10065) are properly recognized and handled
- **Error Response Handling**: Confirms that error responses are correctly returned to the caller
- **Error Logging**: Validates that errors are logged with appropriate detail levels
- **Error Code Descriptions**: Tests that error messages are meaningful and informative

**Why it matters:** In production, brokers can return various error codes. The system must handle all of them gracefully without crashing or losing data. This test ensures every error code path is tested.

**Example scenarios:**
- Requote errors (10004) - price changed before order execution
- Request rejected (10006) - broker rejected the order
- Market closed (10018) - trading not available
- Insufficient funds (10019) - account balance too low
- AutoTrading disabled (10026) - server-side trading disabled

---

### 2. Price Movement & Slippage (200+ tests)

**Purpose:** Validates that the system correctly handles price changes and slippage during order execution.

**What it tests:**
- **Exact Price Matches**: Orders executed at exactly the requested price
- **Acceptable Slippage**: Price differences within the allowed deviation limit (typically 20 pips)
- **Excessive Slippage**: Price differences exceeding limits trigger position closure
- **Negative Slippage**: Price moves in favor of the trader
- **Different Point Values**: Standard pairs (0.0001) vs JPY pairs (0.01)
- **Boundary Conditions**: Slippage exactly at the limit (20 pips) vs just over (21 pips)

**Why it matters:** In real trading, prices constantly move. The system must detect when execution prices differ significantly from requested prices and take appropriate action (close positions) to prevent unexpected losses.

**Example scenarios:**
- Requested: 1.10000, Actual: 1.10000 → ✅ Acceptable (exact match)
- Requested: 1.10000, Actual: 1.10020 → ✅ Acceptable (20 pips, at limit)
- Requested: 1.10000, Actual: 1.10021 → ❌ Unacceptable (21 pips, exceeds limit, position closed)
- Requested: 1.10000, Actual: 1.10100 → ❌ Unacceptable (100 pips, extreme slippage)

---

### 3. Order Expiration & Timing (100+ tests)

**Purpose:** Ensures orders are configured with correct expiration times based on current market time.

**What it tests:**
- **Expiration Calculation**: Expiration time = current tick time + expiration seconds
- **Various Durations**: 0 seconds, 10 seconds, 60 seconds, 5 minutes, etc.
- **Timestamp Boundaries**: Very small timestamps (0) and very large timestamps (999999999)
- **Time Accuracy**: Verifies expiration is calculated correctly and included in order request

**Why it matters:** Orders must expire at the correct time. If expiration is calculated incorrectly, orders might expire too early (rejected) or too late (unintended execution).

**Example scenarios:**
- Current time: 1000, Expiration: 10s → Order expires at 1010 ✅
- Current time: 1000, Expiration: 0s → Order expires immediately ✅
- Current time: 0, Expiration: 10s → Order expires at 10 ✅

---

### 4. Network & Connection Failures (50+ tests)

**Purpose:** Validates graceful handling of network issues and connection problems.

**What it tests:**
- **Initialization Failures**: Connection cannot be established at startup
- **Mid-Operation Failures**: Connection drops while placing an order
- **Position Closing Failures**: Connection lost while closing a position
- **Error Responses**: System returns appropriate error indicators (None/False) when connection fails

**Why it matters:** Network issues are common in production. The system must fail gracefully without crashing, losing data, or leaving positions in an unknown state.

**Example scenarios:**
- Connection fails during initialization → Returns None, no order placed ✅
- Connection drops while placing order → Returns None, order not executed ✅
- Connection lost during position close → Returns False, position status unknown ✅

---

### 5. Broker Rejections & Market Conditions (100+ tests)

**Purpose:** Ensures the system correctly processes and handles broker-side rejections.

**What it tests:**
- **Market Closed**: Broker rejects order because market is closed
- **Insufficient Funds**: Account balance too low for the order
- **AutoTrading Disabled**: Server or terminal has auto-trading disabled
- **Error Code Processing**: Rejection error codes are properly returned

**Why it matters:** Brokers can reject orders for various reasons. The system must recognize these rejections and handle them appropriately, not treat them as system failures.

**Example scenarios:**
- Order placed when market closed → Returns error code 10018 ✅
- Order exceeds account balance → Returns error code 10019 ✅
- AutoTrading button not enabled → Returns error code 10026 ✅

---

### 6. Parameter Edge Cases (300+ tests)

**Purpose:** Tests extreme values and boundary conditions for all order parameters.

**What it tests:**
- **Volume Edge Cases**: Zero, very small (0.0000001), very large (999999.99), standard (0.01)
- **Price Edge Cases**: Zero, very small, very large, negative (should reject)
- **SL/TP Edge Cases**: Zero, negative (should reject), too close to price (should reject), valid distances
- **Deviation Values**: Zero, negative, very large (1000)
- **Magic Numbers**: Zero, negative, very large, standard configuration value

**Why it matters:** Users might accidentally or intentionally provide extreme values. The system must validate inputs and reject invalid ones while accepting valid extremes.

**Example scenarios:**
- Volume: 0.0 → Handled (may reject or accept depending on broker) ✅
- Volume: 999999.99 → Handled (may reject if exceeds account) ✅
- Price: -1.0 → Rejected (negative price invalid) ✅
- SL: -1.0 → Rejected (negative SL invalid) ✅
- SL too close (5 points when minimum is 10) → Rejected ✅

---

### 7. Real-Time Trading Scenarios (100+ tests)

**Purpose:** Simulates real market conditions with moving prices during order placement.

**What it tests:**
- **Price Movement During Order**: Price changes between order request and execution
- **High Volatility**: Rapid price changes (50+ pip movements)
- **Dynamic Price Updates**: Multiple price updates during single operation

**Why it matters:** Real markets are dynamic. Prices change constantly. The system must handle price movements correctly and use current prices when executing orders.

**Example scenarios:**
- Price moves: 1.1000 → 1.1005 → 1.1010 during order placement ✅
- High volatility: 50 pip price swing during execution ✅

---

### 8. Validation Paths (200+ tests)

**Purpose:** Ensures all validation checks work correctly, rejecting invalid orders.

**What it tests:**
- **Symbol Validation**: Invalid symbols, symbols not in market watch
- **Trade Mode Validation**: Trading disabled, close-only mode
- **Price Validation**: Zero prices rejected
- **SL/TP Validation**: Negative values rejected, distances too close rejected
- **Tick Info Validation**: Missing tick information handled

**Why it matters:** Invalid orders should be caught before sending to the broker, saving time and preventing errors. This test ensures all validation paths are working.

**Example scenarios:**
- Invalid symbol "INVALID" → Rejected before broker call ✅
- Symbol not visible → Attempts to select, fails if selection fails ✅
- Trading disabled → Rejected immediately ✅
- Zero price → Rejected (price must be provided) ✅
- SL too close → Rejected (doesn't meet minimum distance) ✅

---

### 9. Concurrency & Race Conditions (50+ tests)

**Purpose:** Validates thread safety and prevents race conditions in concurrent operations.

**What it tests:**
- **Concurrent Order Placement**: Multiple orders placed simultaneously
- **Thread Safety**: Locks prevent data corruption
- **Race Condition Prevention**: Operations don't interfere with each other
- **Lock Mechanisms**: Proper locking prevents deadlocks

**Why it matters:** In production, multiple threads might place orders simultaneously. The system must use proper locking to prevent data corruption, race conditions, and ensure thread safety.

**Example scenarios:**
- 10 threads place orders concurrently → All complete successfully ✅
- No data corruption or race conditions ✅
- Locks prevent simultaneous access to shared resources ✅

---

### 10. Position Verification Edge Cases (100+ tests)

**Purpose:** Ensures position verification correctly detects mismatches and triggers closures.

**What it tests:**
- **Missing Positions**: Position already closed (returns True)
- **SL Mismatch**: Stop loss differs from expected → Position closed
- **TP Mismatch**: Take profit differs from expected → Position closed
- **Volume Mismatch**: Executed volume differs from requested → Position closed
- **Price Slippage**: Execution price exceeds allowed slippage → Position closed
- **Exact Match**: All parameters match → Verification passes

**Why it matters:** Brokers sometimes modify orders (sliding SL/TP, partial fills, price adjustments). The system must detect these changes and close positions to prevent unexpected behavior.

**Example scenarios:**
- Position not found → Returns True (already closed, acceptable) ✅
- SL expected: 1.1, Actual: 1.15 → Mismatch detected, position closed ✅
- Volume expected: 0.01, Actual: 0.02 → Mismatch detected, position closed ✅
- Price expected: 1.1, Actual: 1.1021 (exceeds deviation) → Position closed ✅
- All parameters match → Verification passes ✅

---

### 11. Massive Granular Expansion (500+ tests)

**Purpose:** Comprehensive testing across all parameter combinations and edge cases.

**What it tests:**
- **All Digit Precisions**: 0-8 decimal places (different symbol types)
- **All Stops Level Combinations**: 0-100 points for stops_level and freeze_level
- **Price Rounding**: Various prices rounded to different decimal precisions
- **SL/TP Distance Boundaries**: Exactly at limit, just below, just above
- **Volume Variations**: All possible volume values
- **Expiration Times**: All possible expiration durations
- **Deviation Values**: All deviation settings
- **Order Types**: Buy and sell orders
- **Comment Variations**: Empty, short, long, special characters
- **Magic Number Variations**: All possible magic numbers
- **Close Retry Scenarios**: Success on first try, second try, etc.

**Why it matters:** This exhaustive test ensures the system works correctly across all possible combinations of parameters, catching edge cases that might not be found in normal testing.

**Example scenarios:**
- Symbol with 0 digits (integers) → Handled correctly ✅
- Symbol with 8 digits (cryptocurrency precision) → Handled correctly ✅
- Stops level: 0, Freeze: 0 → No minimum distance required ✅
- Stops level: 100, Freeze: 50 → Minimum distance = 100 points ✅
- Price 1.1111111 rounded to 5 digits → 1.11111 ✅

---

### 12. Real-World Trading Scenarios (100+ tests)

**Purpose:** Simulates actual trading situations that occur in production.

**What it tests:**
- **Price Movement During Order**: Price changes while order is being placed
- **High Volatility**: Rapid price changes (50 pip movements)
- **Order Expiration**: Order expires before it can be filled
- **Partial Fills**: Only part of the order is executed
- **Requotes**: Broker requests new price due to price change

**Why it matters:** These scenarios happen regularly in live trading. The system must handle them correctly to avoid losses and ensure reliable operation.

**Example scenarios:**
- Price moves 5 pips during order placement → Order uses current price ✅
- High volatility: 50 pip swing → System handles correctly ✅
- Order expires before fill → Error code 10022 returned ✅
- Partial fill → Error code 10010 returned ✅
- Requote requested → Error code 10004 returned ✅

---

### 13. Bug Detection Tests (20+ tests)

**Purpose:** Specifically designed to find bugs, edge cases, and potential issues.

**What it tests:**
- **Lock Deadlock Prevention**: Multiple operations don't cause deadlocks
- **None/Null Handling**: Missing data (None values) handled gracefully
- **Negative Values**: Negative prices, volumes handled correctly
- **Extremely Large Values**: Very large numbers don't cause overflow
- **String Injection**: Malicious strings don't cause security issues
- **Invalid Tickets**: Invalid position tickets handled correctly
- **Type Mismatches**: Wrong data types handled gracefully
- **Concurrent Operations**: Multiple threads don't corrupt data
- **Missing Attributes**: Objects with missing attributes handled
- **NaN/Infinity**: Invalid floating point values rejected
- **Empty Strings**: Empty inputs handled correctly
- **Unicode Symbols**: Non-ASCII characters handled
- **Rapid Operations**: Many operations in quick succession
- **Zero Values**: Zero expected values in verification
- **Connection Failures**: Mid-operation connection loss
- **Thread Safety**: Shared connections used safely

**Why it matters:** These tests specifically target scenarios that could reveal bugs. They test edge cases, error conditions, and unusual inputs that might not occur in normal operation but could cause issues if not handled.

**Example scenarios:**
- None symbol_info → Returns None gracefully, doesn't crash ✅
- Negative price → Rejected, doesn't cause errors ✅
- NaN value → Rejected, doesn't cause calculation errors ✅
- Empty string symbol → Handled gracefully ✅
- 20 concurrent operations → All complete successfully ✅

---

## Test Utilities

The `test_mt5_utils.py` module provides shared utilities:

- **`setup_mock_mt5()`**: Configures mock MT5 objects with all necessary constants
- **`create_mock_connection()`**: Creates a fully configured mock connection
- **`create_symbol_info()`**: Creates mock symbol information with specified parameters
- **`log_test()`**: Provides consistent test result logging format

## Running Tests

### Single Command (Recommended)

```bash
# Run all tests
python tests/run_all_tests.py

# Run with verbose output
python tests/run_all_tests.py --verbose

# Run specific category
python tests/run_all_tests.py --category "Error Codes"

# Auto-run without confirmation
python tests/run_all_tests.py --auto
```

### Individual Test Files

```bash
python tests/test_mt5_error_codes.py
python tests/test_mt5_price_movement.py
python tests/test_mt5_bug_detection.py
# ... etc
```

### Using pytest (if available)

```bash
pytest tests/test_mt5_*.py -v
pytest tests/test_mt5_error_codes.py -v
```

## Test Results Interpretation

- **✓ PASS**: Test passed, functionality works as expected
- **✗ FAIL**: Test failed, indicates a potential bug or issue
- **✗ ERROR**: Test encountered an exception, indicates a crash or unhandled error
- **✗ SKIPPED**: Test module not found or couldn't be imported

## What to Look For

When reviewing test results, pay attention to:

1. **Failed Tests**: Indicate potential bugs that need fixing
2. **Error Tests**: Indicate crashes or unhandled exceptions
3. **Consistent Failures**: Patterns of failures suggest systemic issues
4. **Edge Case Failures**: Failures in edge case tests indicate robustness issues

## Adding New Tests

When adding new tests:

1. **Choose the Right Category**: Add to existing file if category matches
2. **Use Shared Utilities**: Always use functions from `test_mt5_utils.py`
3. **Document Thoroughly**: Explain what the test verifies and why
4. **Handle Errors**: Tests should handle both success and failure cases
5. **Update README**: Add new test categories to this documentation

## Maintenance

- **Regular Updates**: Update tests when adding new features
- **Bug Regression**: Add tests for any bugs found in production
- **Edge Cases**: Continuously add edge case tests
- **Documentation**: Keep this README updated with new test categories

## Summary

This test suite provides comprehensive coverage of the MT5 trading system, ensuring reliability, correctness, and robustness across all scenarios from normal operation to extreme edge cases. Running these tests regularly helps catch bugs early and ensures the system remains stable as it evolves.
