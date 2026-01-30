"""
Test Validation Script
======================

Quick script to validate all test files can be imported and basic structure is correct.
"""

import sys
import os
import importlib.util

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logger import get_logger

logger = get_logger(__name__)

test_files = [
    "test_mt5_utils",
    "test_mt5_error_codes",
    "test_mt5_price_movement",
    "test_mt5_order_expiration",
    "test_mt5_network_failures",
    "test_mt5_broker_rejections",
    "test_mt5_parameter_edge_cases",
    "test_mt5_realtime_trading",
    "test_mt5_validation_paths",
    "test_mt5_concurrency",
    "test_mt5_position_verification",
    "test_mt5_granular_expansion",
    "test_mt5_real_world_scenarios",
    "test_mt5_bug_detection",
]

logger.info("Validating test files...")
logger.info("=" * 70)

errors = []
for test_file in test_files:
    try:
        file_path = os.path.join(os.path.dirname(__file__), f"{test_file}.py")
        if not os.path.exists(file_path):
            logger.error(f"{test_file}: File not found")
            errors.append(f"{test_file}: File not found")
            continue
        
        spec = importlib.util.spec_from_file_location(test_file, file_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        logger.info(f"{test_file}: Import successful")
    except Exception as e:
        logger.error(f"{test_file}: {str(e)}")
        errors.append(f"{test_file}: {str(e)}")
        import traceback
        traceback.print_exc()

logger.info("=" * 70)
if errors:
    logger.error(f"Found {len(errors)} errors:")
    for error in errors:
        logger.error(f"  - {error}")
    sys.exit(1)
else:
    logger.info("All test files validated successfully!")
    sys.exit(0)
