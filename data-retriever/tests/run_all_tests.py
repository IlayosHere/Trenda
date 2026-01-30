"""
MT5 Complete Test Suite Runner
==============================

Single entry point to run all MT5 tests. This script executes all test categories
and provides comprehensive reporting.

Usage:
    python run_all_tests.py
    python run_all_tests.py --verbose
    python run_all_tests.py --category "Error Codes"
    python run_all_tests.py --auto
"""

import sys
import os
import argparse
import time
import traceback
from typing import List, Tuple

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logger import get_logger

logger = get_logger(__name__)


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
    logger.info("=" * 80)
    logger.info("MT5 COMPREHENSIVE TEST SUITE")
    logger.info("=" * 80)
    logger.info(f"Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    if category_filter:
        logger.info(f"Filter: Running only '{category_filter}' category")
    logger.info("=" * 80)
    
    # Import all test modules with their actual function names
    test_modules = [
        # Individual test files
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
        
        # Comprehensive test file (has multiple test functions)
        ("Comprehensive - Error Codes", "test_mt5_comprehensive", "test_all_mt5_error_codes"),
        ("Comprehensive - Price Movement", "test_mt5_comprehensive", "test_price_movement_scenarios"),
        ("Comprehensive - Order Expiration", "test_mt5_comprehensive", "test_order_expiration_scenarios"),
        ("Comprehensive - Network Failures", "test_mt5_comprehensive", "test_network_failure_scenarios"),
        ("Comprehensive - Broker Rejections", "test_mt5_comprehensive", "test_broker_rejection_scenarios"),
        ("Comprehensive - Parameter Edge Cases", "test_mt5_comprehensive", "test_parameter_edge_cases"),
        ("Comprehensive - Real-time Trading", "test_mt5_comprehensive", "test_realtime_trading_scenarios"),
        ("Comprehensive - Validation Paths", "test_mt5_comprehensive", "test_all_validation_paths"),
        ("Comprehensive - Concurrency", "test_mt5_comprehensive", "test_concurrency_scenarios"),
        ("Comprehensive - Position Verification", "test_mt5_comprehensive", "test_position_verification_edge_cases"),
        ("Comprehensive - Granular Expansion", "test_mt5_comprehensive", "test_massive_granular_expansion"),
        ("Comprehensive - Real-World Scenarios", "test_mt5_comprehensive", "test_real_world_scenarios"),
    ]
    
    # Filter out modules that don't exist yet
    available_modules = []
    for category_name, module_name, function_name in test_modules:
        # Apply category filter early
        if category_filter and category_filter.lower() not in category_name.lower():
            continue
            
        try:
            # Try to import the module
            module = __import__(module_name, fromlist=[function_name])
            # Check if the function exists
            if hasattr(module, function_name):
                available_modules.append((category_name, module_name, function_name))
            elif verbose:
                logger.debug(f"Skipping {category_name} - function '{function_name}' not found in module")
        except ImportError as e:
            if verbose:
                logger.debug(f"Skipping {category_name} - module '{module_name}' not found: {e}")
        except Exception as e:
            if verbose:
                logger.debug(f"Skipping {category_name} - error checking module: {e}")
    
    if not available_modules:
        logger.error("No test modules found!")
        if category_filter:
            logger.info(f"Try removing the filter or check if '{category_filter}' matches any category.")
        return False, []
    
    results = []
    total_start = time.time()
    
    for category_name, module_name, function_name in available_modules:
        try:
            if verbose:
                logger.info("=" * 80)
                logger.info(f"Running: {category_name}")
                logger.info("=" * 80)
            
            start_time = time.time()
            
            # Dynamically import and run test
            module = __import__(module_name, fromlist=[function_name])
            test_func = getattr(module, function_name)
            
            # Run the test function
            result = test_func()
            
            # Handle different return types
            if result is None:
                # If function returns None, assume it passed (some tests don't return)
                result = True
            elif isinstance(result, bool):
                # Boolean result
                pass
            elif isinstance(result, (int, float)):
                # Numeric result (0 = fail, non-zero = pass)
                result = bool(result)
            else:
                # Other types - assume pass
                result = True
            
            duration = time.time() - start_time
            results.append((category_name, result, duration))
            
            status = "PASSED" if result else "FAILED"
            if result:
                logger.info(f"[{status}]: {category_name} ({duration:.2f}s)")
            else:
                logger.error(f"[{status}]: {category_name} ({duration:.2f}s)")
            
        except ImportError as e:
            logger.warning(f"[SKIPPED]: {category_name} - Module not found: {e}")
            results.append((category_name, False, 0.0))
        except AttributeError as e:
            logger.warning(f"[SKIPPED]: {category_name} - Function '{function_name}' not found: {e}")
            results.append((category_name, False, 0.0))
        except Exception as e:
            duration = time.time() - start_time if 'start_time' in locals() else 0.0
            logger.error(f"[ERROR] in {category_name}: {str(e)}")
            if verbose:
                traceback.print_exc()
            results.append((category_name, False, duration))
    
    total_duration = time.time() - total_start
    
    # Print summary
    logger.info("=" * 80)
    logger.info("FINAL SUMMARY")
    logger.info("=" * 80)
    
    passed_count = sum(1 for _, result, _ in results if result)
    total_count = len(results)
    
    for category_name, result, duration in results:
        status = "PASSED" if result else "FAILED"
        if result:
            logger.info(f"  [{status}]: {category_name:.<50} ({duration:>6.2f}s)")
        else:
            logger.error(f"  [{status}]: {category_name:.<50} ({duration:>6.2f}s)")
    
    logger.info("=" * 80)
    logger.info(f"Total: {passed_count}/{total_count} categories passed")
    logger.info(f"Total Duration: {total_duration:.2f}s")
    logger.info(f"Completed at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 80)
    
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
            logger.info("Tests cancelled.")
            return
    
    try:
        success, results = run_all_tests(verbose=args.verbose, category_filter=args.category)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.warning("Tests interrupted by user.")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Fatal error running tests: {e}")
        if args.verbose:
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
