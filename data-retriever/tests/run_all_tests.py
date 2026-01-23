"""
MT5 Complete Test Suite Runner
==============================

Single entry point to run all MT5 tests. This script executes all test categories
and provides comprehensive reporting.

Usage:
    python run_all_tests.py
    python run_all_tests.py --verbose
    python run_all_tests.py --category "Error Codes"
"""

import sys
import os
import argparse
import time
from typing import List, Tuple

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_all_tests(verbose: bool = False, category_filter: str = None) -> Tuple[bool, List[Tuple[str, bool, float]]]:
    """
    Run all MT5 test categories.
    
    Args:
        verbose: If True, show detailed output for each test
        category_filter: If provided, only run tests matching this category name
    
    Returns:
        Tuple of (all_passed, results_list) where results_list contains
        (category_name, passed, duration) tuples
    """
    print("\n" + "=" * 80)
    print("MT5 COMPREHENSIVE TEST SUITE - 1000+ TEST CASES")
    print("=" * 80)
    print(f"Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    if category_filter:
        print(f"Filter: Running only '{category_filter}' category")
    print("=" * 80)
    
    # Import all test modules
    test_modules = [
        ("All MT5 Error Codes", "test_mt5_error_codes", "test_all_mt5_error_codes"),
        ("Price Movement & Slippage", "test_mt5_price_movement", "test_price_movement_scenarios"),
        ("Order Expiration & Timing", "test_mt5_order_expiration", "test_order_expiration_scenarios"),
        ("Network & Connection Failures", "test_mt5_network_failures", "test_network_failure_scenarios"),
        ("Broker Rejections", "test_mt5_broker_rejections", "test_broker_rejection_scenarios"),
        ("Parameter Edge Cases", "test_mt5_parameter_edge_cases", "test_parameter_edge_cases"),
        ("Real-time Trading", "test_mt5_realtime_trading", "test_realtime_trading_scenarios"),
        ("Validation Paths", "test_mt5_validation_paths", "test_all_validation_paths"),
        ("Concurrency", "test_mt5_concurrency", "test_concurrency_scenarios"),
        ("Position Verification", "test_mt5_position_verification", "test_position_verification_edge_cases"),
        ("Massive Granular Expansion", "test_mt5_granular_expansion", "test_massive_granular_expansion"),
        ("Real-World Scenarios", "test_mt5_real_world_scenarios", "test_real_world_scenarios"),
        ("Bug Detection Tests", "test_mt5_bug_detection", "test_bug_detection_scenarios"),
    ]
    
    # Filter out modules that don't exist yet
    available_modules = []
    for category_name, module_name, function_name in test_modules:
        try:
            __import__(module_name)
            available_modules.append((category_name, module_name, function_name))
        except ImportError:
            if verbose:
                print(f"Skipping {category_name} - module not found")
    
    test_modules = available_modules
    
    results = []
    total_start = time.time()
    
    for category_name, module_name, function_name in test_modules:
        # Apply category filter if specified
        if category_filter and category_filter.lower() not in category_name.lower():
            continue
        
        try:
            if verbose:
                print(f"\n{'='*80}")
                print(f"Running: {category_name}")
                print(f"{'='*80}")
            
            start_time = time.time()
            
            # Dynamically import and run test
            module = __import__(module_name, fromlist=[function_name])
            test_func = getattr(module, function_name)
            result = test_func()
            
            duration = time.time() - start_time
            results.append((category_name, result, duration))
            
            status = "[PASSED]" if result else "[FAILED]"
            print(f"\n{status}: {category_name} ({duration:.2f}s)")
            
        except ImportError as e:
            print(f"\n[SKIPPED]: {category_name} - Module not found: {e}")
            results.append((category_name, False, 0.0))
        except Exception as e:
            duration = time.time() - start_time if 'start_time' in locals() else 0.0
            print(f"\n[ERROR] in {category_name}: {str(e)}")
            if verbose:
                import traceback
                traceback.print_exc()
            results.append((category_name, False, duration))
    
    total_duration = time.time() - total_start
    
    # Print summary
    print("\n" + "=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)
    
    passed_count = sum(1 for _, result, _ in results if result)
    total_count = len(results)
    
    for category_name, result, duration in results:
        status = "[PASSED]" if result else "[FAILED]"
        print(f"  {status}: {category_name:.<50} ({duration:>6.2f}s)")
    
    print("=" * 80)
    print(f"Total: {passed_count}/{total_count} categories passed")
    print(f"Total Duration: {total_duration:.2f}s")
    print(f"Completed at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    all_passed = all(result for _, result, _ in results)
    return all_passed, results


def main():
    """Main entry point for test runner."""
    parser = argparse.ArgumentParser(description='Run MT5 comprehensive test suite')
    parser.add_argument('--verbose', '-v', action='store_true', 
                       help='Show verbose output for each test')
    parser.add_argument('--category', '-c', type=str, default=None,
                       help='Run only tests matching this category name')
    parser.add_argument('--auto', '-a', action='store_true',
                       help='Run tests automatically without confirmation')
    
    args = parser.parse_args()
    
    if not args.auto:
        response = input("\nRun comprehensive test suite? (y/n): ").lower()
        if not response.startswith('y'):
            print("Tests cancelled.")
            return
    
    success, results = run_all_tests(verbose=args.verbose, category_filter=args.category)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
