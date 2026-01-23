"""Tests for the TradingLock module."""
import sys
import os
import unittest
import tempfile
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from externals.meta_trader.safeguards import TradingLock
from externals.meta_trader.safeguard_storage import SafeguardStorage


class TestTradingLock(unittest.TestCase):
    """Unit tests for TradingLock class."""
    
    def setUp(self):
        """Create a temporary lock file path for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.lock_file = Path(self.temp_dir) / "test_lock.json"
        storage = SafeguardStorage(lock_file=self.lock_file)
        self.trading_lock = TradingLock(storage=storage)
    
    def tearDown(self):
        """Clean up temp files after each test."""
        if self.lock_file.exists():
            self.lock_file.unlink()
        Path(self.temp_dir).rmdir()
    
    # ─────────────────────────────────────────────────────────────
    # TEST 1: Fresh state - trading allowed
    # ─────────────────────────────────────────────────────────────
    def test_1_fresh_state_trading_allowed(self):
        """Without lock file, trading should be allowed."""
        is_allowed, reason = self.trading_lock.is_trading_allowed()
        
        self.assertTrue(is_allowed)
        self.assertEqual(reason, "")
        self.assertFalse(self.trading_lock.is_locked())
    
    # ─────────────────────────────────────────────────────────────
    # TEST 2: Create lock creates file and blocks trading
    # ─────────────────────────────────────────────────────────────
    def test_2_create_lock_blocks_trading(self):
        """create_lock should create lock file and block trading."""
        reason = "Test emergency - position close failed"
        self.trading_lock.create_lock(reason)
        
        # Lock file should exist
        self.assertTrue(self.lock_file.exists())
        
        # Trading should be blocked
        is_allowed, lock_reason = self.trading_lock.is_trading_allowed()
        self.assertFalse(is_allowed)
        self.assertIn(reason, lock_reason)
        self.assertTrue(self.trading_lock.is_locked())
    
    # ─────────────────────────────────────────────────────────────
    # TEST 3: Lock file content is valid JSON
    # ─────────────────────────────────────────────────────────────
    def test_3_lock_file_json_structure(self):
        """Lock file should contain valid JSON with required fields."""
        self.trading_lock.trigger_emergency_lock("Test reason")
        
        with open(self.lock_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.assertIn("reason", data)
        self.assertIn("timestamp", data)
        self.assertIn("locked_by", data)
        self.assertEqual(data["reason"], "Test reason")
    
    # ─────────────────────────────────────────────────────────────
    # TEST 4: Clear lock resumes trading
    # ─────────────────────────────────────────────────────────────
    def test_4_clear_lock_resumes_trading(self):
        """clear_lock should remove lock file and allow trading again."""
        self.trading_lock.trigger_emergency_lock("Test lock")
        self.assertTrue(self.safeguards.is_locked())
        
        # Clear the lock
        result = self.safeguards.clear_lock()
        self.assertTrue(result)
        
        # Trading should resume
        self.assertFalse(self.lock_file.exists())
        is_allowed, _ = self.safeguards.is_trading_allowed()
        self.assertTrue(is_allowed)
    
    # ─────────────────────────────────────────────────────────────
    # TEST 5: Clear lock when no lock exists
    # ─────────────────────────────────────────────────────────────
    def test_5_clear_nonexistent_lock(self):
        """clear_lock should return False when no lock exists."""
        result = self.safeguards.clear_lock()
        self.assertFalse(result)
    
    # ─────────────────────────────────────────────────────────────
    # TEST 6: Corrupted lock file treated as locked
    # ─────────────────────────────────────────────────────────────
    def test_6_corrupted_lock_file_blocks_trading(self):
        """Corrupted lock file should block trading for safety."""
        # Write invalid JSON
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_file, 'w') as f:
            f.write("not valid json {{}{}")
        
        is_allowed, reason = self.safeguards.is_trading_allowed()
        self.assertFalse(is_allowed)
        self.assertIn("corrupted", reason.lower())
    
    # ─────────────────────────────────────────────────────────────
    # TEST 7: Multiple locks overwrite previous
    # ─────────────────────────────────────────────────────────────
    def test_7_multiple_locks_overwrite(self):
        """Multiple lock calls should overwrite with latest reason."""
        self.trading_lock.trigger_emergency_lock("First reason")
        self.trading_lock.trigger_emergency_lock("Second reason")
        
        is_allowed, reason = self.safeguards.is_trading_allowed()
        self.assertFalse(is_allowed)
        self.assertIn("Second reason", reason)
        self.assertNotIn("First reason", reason)
    
    # ─────────────────────────────────────────────────────────────
    # TEST 8: Lock creation failure raises RuntimeError
    # ─────────────────────────────────────────────────────────────
    def test_8_lock_creation_failure_raises(self):
        """trigger_emergency_lock should raise RuntimeError if file cannot be created."""
        import platform
        
        # Use a path that cannot be created on any platform
        if platform.system() == "Windows":
            # Windows: Use an invalid filename with reserved characters
            invalid_path = Path("Z:\\NonExistent\\<>|:*?\\lock.json")
        else:
            # Unix: Use root path that requires elevated permissions
            invalid_path = Path("/root_that_does_not_exist_xyz/lock.json")
        
        storage = SafeguardStorage(lock_file=invalid_path)
        trading_lock = TradingLock(storage=storage)
        
        with self.assertRaises(RuntimeError) as context:
            trading_lock.create_lock("Should fail")
        
        self.assertIn("CRITICAL", str(context.exception))


class TestSafeguardsIntegration(unittest.TestCase):
    """Integration tests with MT5Constraints."""
    
    def setUp(self):
        """Set up mocked constraints with safeguards."""
        self.temp_dir = tempfile.mkdtemp()
        self.lock_file = Path(self.temp_dir) / "test_lock.json"
    
    def tearDown(self):
        """Clean up."""
        if self.lock_file.exists():
            self.lock_file.unlink()
        Path(self.temp_dir).rmdir()
    
    def test_constraints_blocked_when_locked(self):
        """can_execute_trade should return blocked when safeguards are locked."""
        from unittest.mock import MagicMock, patch
        from externals.meta_trader.constraints import MT5Constraints
        
        # Create mock connection
        mock_conn = MagicMock()
        mock_conn.initialize.return_value = True
        constraints = MT5Constraints(mock_conn)
        
        # Create locked trading lock
        storage = SafeguardStorage(lock_file=self.lock_file)
        trading_lock = TradingLock(storage=storage)
        trading_lock.create_lock("Test integration lock")
        
        # Patch in the constraints module where it's imported at top-level
        with patch('externals.meta_trader.constraints._trading_lock', trading_lock):
            is_blocked, reason = constraints.can_execute_trade("EURUSD")
        
        self.assertTrue(is_blocked)
        self.assertIn("TRADING LOCKED", reason)


if __name__ == "__main__":
    unittest.main()
