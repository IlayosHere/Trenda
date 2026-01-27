"""
MT5 Comprehensive Test Suite Runner
===================================

Main test runner that executes all MT5 test modules and provides a comprehensive
summary of test results.

This runner:
- Executes all test categories
- Provides detailed test results
- Handles errors gracefully
- Generates summary reports
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_comprehensive_tests():
    """
    Run all comprehensive MT5 tests.
    
    This function executes all test categories and provides a comprehensive
    summary of results. Each test category is run independently, and errors
    in one category do not prevent others from running.
    
    Returns:
        bool: True if all test categories passed, False otherwise.
    """
    print("\n" + "=" * 70)
    print("MT5 COMPREHENSIVE TEST SUITE - 1000+ TEST CASES")
    print("=" * 70)
    
    # Import all test modules
    from test_mt5_error_codes import test_all_mt5_error_codes
    from test_mt5_price_movement import test_price_movement_scenarios
    from test_mt5_order_expiration import test_order_expiration_scenarios
    from test_mt5_network_failures import test_network_failure_scenarios
    from test_mt5_broker_rejections import test_broker_rejection_scenarios
    from test_mt5_parameter_edge_cases import test_parameter_edge_cases
    from test_mt5_realtime_trading import test_realtime_trading_scenarios
    from test_mt5_validation_paths import test_all_validation_paths
    from test_mt5_concurrency import test_concurrency_scenarios
    from test_mt5_position_verification import test_position_verification_edge_cases
    from test_mt5_granular_expansion import test_massive_granular_expansion
    from test_mt5_real_world_scenarios import test_real_world_scenarios
    
    categories = [
        ("All MT5 Error Codes", test_all_mt5_error_codes),
        ("Price Movement & Slippage", test_price_movement_scenarios),
        ("Order Expiration & Timing", test_order_expiration_scenarios),
        ("Network & Connection Failures", test_network_failure_scenarios),
        ("Broker Rejections", test_broker_rejection_scenarios),
        ("Parameter Edge Cases", test_parameter_edge_cases),
        ("Real-time Trading", test_realtime_trading_scenarios),
        ("Validation Paths", test_all_validation_paths),
        ("Concurrency", test_concurrency_scenarios),
        ("Position Verification", test_position_verification_edge_cases),
        ("Massive Granular Expansion", test_massive_granular_expansion),
        ("Real-World Scenarios", test_real_world_scenarios),
    ]
    
    results = []
    for name, test_func in categories:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n  ERROR in {name}: {str(e)}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    for name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"  {status}: {name}")
    
    total_passed = sum(1 for _, result in results if result)
    print(f"\n  Total: {total_passed}/{len(results)} categories passed")
    print("=" * 70)
    
    return all(result for _, result in results)


if __name__ == "__main__":
    if input("Run comprehensive test suite? (y/n): ").lower().startswith('y'):
        success = run_comprehensive_tests()
        sys.exit(0 if success else 1)
