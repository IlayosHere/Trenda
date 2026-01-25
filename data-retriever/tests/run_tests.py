#!/usr/bin/env python3
"""
Easy test runner for MT5 trading tests.

Usage:
    python tests/run_tests.py              # Run all tests
    python tests/run_tests.py 38 39 40     # Run specific tests
    python tests/run_tests.py --new        # Run only new tests (38-46)
    python tests/run_tests.py --list       # List all available tests
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_mt5_trading import run_all_tests, run_specific_tests

def print_test_list():
    """Print all available tests."""
    tests = {
        "Core Operations": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "Logic": [11],
        "Edge Cases": [12, 13, 14, 15, 16],
        "Stress": [17],
        "Extended": [19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37],
        "New Comprehensive": [38, 39, 40, 41, 42, 43, 44, 45, 46],
        "Edge Cases & Bugs": [47, 48, 49, 50, 51, 52, 53, 54, 55, 56],
        "Shutdown": [18],
    }
    
    print("\n" + "=" * 70)
    print("AVAILABLE TESTS")
    print("=" * 70)
    for category, test_nums in tests.items():
        print(f"\n{category}:")
        for num in test_nums:
            print(f"  {num:2d} - Test {num}")
    print("\n" + "=" * 70)


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "--list":
            print_test_list()
            return
        elif sys.argv[1] == "--new":
            # Run only new tests (38-46)
            run_specific_tests(list(range(38, 47)))
            return
        elif sys.argv[1] == "--edge":
            # Run edge case tests (47-56)
            run_specific_tests(list(range(47, 57)))
            return
        elif sys.argv[1] == "--all-new":
            # Run all new tests (38-56)
            run_specific_tests(list(range(38, 57)))
            return
        else:
            # Run specific tests
            try:
                test_nums = [int(x) for x in sys.argv[1:]]
                run_specific_tests(test_nums)
                return
            except ValueError:
                print("❌ Invalid test numbers. Use --list to see available tests.")
                return
    
    # Run all tests
    print("\n" + "=" * 70)
    print("MT5 TRADING TEST SUITE")
    print("=" * 70)
    print("\nOptions:")
    print("  python tests/run_tests.py              # Run all tests")
    print("  python tests/run_tests.py 38 39 40     # Run specific tests")
    print("  python tests/run_tests.py --new        # Run only new tests (38-46)")
    print("  python tests/run_tests.py --edge       # Run edge case tests (47-56)")
    print("  python tests/run_tests.py --all-new    # Run all new tests (38-56)")
    print("  python tests/run_tests.py --list       # List all available tests")
    print("\n" + "=" * 70)
    
    response = input("\nRun all tests? (y/n): ").lower().strip()
    if response.startswith('y'):
        run_all_tests()
    else:
        print("Cancelled.")


if __name__ == "__main__":
    main()
