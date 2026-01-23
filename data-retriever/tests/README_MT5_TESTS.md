# MT5 Test Suite Documentation

## Quick Start

**Run all tests with a single command:**
```bash
python tests/run_all_tests.py
```

**All tests have been fixed and should pass.** See [TEST_FIXES.md](TEST_FIXES.md) for details on fixes applied.

For detailed explanations of all tests, see [README_MT5_TESTS_DETAILED.md](README_MT5_TESTS_DETAILED.md)

## Overview

The MT5 test suite has been split into focused, modular test files for better maintainability and organization. Each test file covers a specific aspect of MT5 trading functionality.

## Test Structure

### Core Test Files

1. **test_mt5_utils.py** - Shared utilities and helper functions used across all test modules
   - Mock setup functions
   - Common test configurations
   - Logging utilities

2. **test_mt5_error_codes.py** - Tests all MT5 error codes and retcodes
   - Error code handling (10004-10065)
   - Error response processing
   - Error logging verification

3. **test_mt5_price_movement.py** - Tests price movement and slippage scenarios
   - Exact price matches
   - Slippage within deviation limits
   - Excessive slippage detection
   - Different point values (standard vs JPY pairs)

4. **test_mt5_order_expiration.py** - Tests order expiration and timing
   - Expiration time calculation
   - Various expiration durations
   - Timestamp boundary conditions

5. **test_mt5_network_failures.py** - Tests network and connection failures
   - Connection initialization failures
   - Connection drops during operations
   - Network timeout handling

6. **test_mt5_broker_rejections.py** - Tests broker rejection scenarios
   - Market closed rejections
   - Insufficient funds
   - AutoTrading disabled

7. **test_mt5_parameter_edge_cases.py** - Tests edge cases with all parameters
   - Volume edge cases
   - Price edge cases
   - SL/TP edge cases
   - Deviation and magic number variations

8. **test_mt5_realtime_trading.py** - Tests real-time trading scenarios
   - Order placement with moving prices
   - Price volatility scenarios

9. **test_mt5_validation_paths.py** - Tests all validation paths
   - Symbol validation
   - Trade mode validation
   - Price validation
   - SL/TP distance validation

10. **test_mt5_concurrency.py** - Tests concurrency and race conditions
    - Concurrent order placement
    - Thread safety
    - Lock mechanisms

11. **test_mt5_position_verification.py** - Tests position verification edge cases
    - Missing position handling
    - SL/TP mismatch detection
    - Volume mismatch detection
    - Price slippage detection

12. **test_mt5_granular_expansion.py** - Massive granular test expansion
    - All digit precisions
    - All stops level combinations
    - Price rounding edge cases
    - Boundary conditions
    - Parameter variations

13. **test_mt5_real_world_scenarios.py** - Tests real-world trading scenarios
    - Price movement during order placement
    - High volatility scenarios
    - Order expiration
    - Partial fills
    - Requotes

14. **test_mt5_runner.py** - Main test runner
    - Executes all test categories
    - Provides comprehensive summary
    - Error handling

## Running Tests

### Run All Tests

```bash
python tests/test_mt5_runner.py
```

### Run Individual Test Files

```bash
python tests/test_mt5_error_codes.py
python tests/test_mt5_price_movement.py
# ... etc
```

### Run with pytest (if available)

```bash
pytest tests/test_mt5_*.py -v
```

## Test Documentation Standards

Each test file includes:
- Module-level docstring describing the test category
- Function-level docstrings for each test function
- Inline comments explaining complex test scenarios
- Clear test names and descriptions

## Test Utilities

The `test_mt5_utils.py` module provides:

- `setup_mock_mt5()` - Sets up MT5 constants in mock objects
- `create_mock_connection()` - Creates configured mock connections
- `create_symbol_info()` - Creates mock symbol info objects
- `log_test()` - Consistent test result logging

## Best Practices

1. **Use shared utilities** - Always use functions from `test_mt5_utils.py` for consistency
2. **Document test scenarios** - Explain what each test verifies
3. **Handle errors gracefully** - Tests should handle both success and failure cases
4. **Mock appropriately** - Use mocks to isolate units under test
5. **Clear test names** - Test names should clearly describe what they verify

## Maintenance

When adding new tests:
1. Place them in the appropriate existing test file if the category matches
2. Create a new test file if it's a new category
3. Update this README with the new test file
4. Ensure all tests use shared utilities from `test_mt5_utils.py`
5. Add comprehensive documentation

## Migration from Old Test File

The original `test_mt5_comprehensive.py` has been split into these modular files. The old file can be kept for reference but should not be used for new development.
