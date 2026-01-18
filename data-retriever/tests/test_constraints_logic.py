import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from externals.meta_trader.constraints import MT5Constraints
from configuration.broker_config import MT5_MAGIC_NUMBER, MT5_MIN_TRADE_INTERVAL_MINUTES

class TestMT5ConstraintsLogic(unittest.TestCase):
    def setUp(self):
        # mock the connection and mt5
        self.mock_conn = MagicMock()
        self.mock_mt5 = MagicMock()
        self.mock_conn.mt5 = self.mock_mt5
        self.mock_conn.initialize.return_value = True
        
        # Initialize constraints with mocked connection
        self.constraints = MT5Constraints(self.mock_conn)
        
        # Consistent time for all tests
        self.now_ts = 1700000000.0  # arbitrary fixed timestamp
        self.min_gap_seconds = MT5_MIN_TRADE_INTERVAL_MINUTES * 60

    def mock_tick(self, timestamp):
        tick = MagicMock()
        tick.time = timestamp
        self.mock_mt5.symbol_info_tick.return_value = tick

    def create_mock_trade(self, start_time):
        trade = MagicMock()
        trade.time = start_time
        trade.magic = MT5_MAGIC_NUMBER
        return trade

    def test_fresh_start_allowed(self):
        """Case: No trades ever. Should be allowed."""
        self.mock_tick(self.now_ts)
        self.mock_mt5.positions_get.return_value = []
        self.mock_mt5.history_deals_get.return_value = []
        
        is_blocked, reason = self.constraints.is_trade_open("EURUSD")
        self.assertFalse(is_blocked)
        self.assertEqual(reason, "")

    def test_global_limit_reached(self):
        """Case: 4 trades already open for this bot. Should be blocked."""
        self.mock_tick(self.now_ts)
        # 4 trades with our magic number
        trades = [self.create_mock_trade(self.now_ts - 1000) for _ in range(4)]
        self.mock_mt5.positions_get.return_value = trades
        
        is_blocked, reason = self.constraints.is_trade_open("EURUSD")
        self.assertTrue(is_blocked)
        self.assertIn("Global limit reached", reason)

    def test_active_trade_too_recent(self):
        """Case: Trade opened 209 mins ago (Limit is 210). Should be blocked."""
        # 209 minutes = 12540 seconds
        start_time = self.now_ts - (209 * 60)
        self.mock_tick(self.now_ts)
        self.mock_mt5.positions_get.return_value = [self.create_mock_trade(start_time)]
        # ensure it's filtered by symbol in the code
        self.mock_mt5.positions_get.side_effect = lambda symbol=None, ticket=None: \
            [self.create_mock_trade(start_time)] if symbol == "EURUSD" else []

        is_blocked, reason = self.constraints.is_trade_open("EURUSD")
        self.assertTrue(is_blocked)
        self.assertIn("Recent active position", reason)

    def test_active_trade_safe_time(self):
        """Case: Trade opened 211 mins ago. Should be allowed."""
        # 211 minutes = 12660 seconds
        start_time = self.now_ts - (211 * 60)
        self.mock_tick(self.now_ts)
        self.mock_mt5.positions_get.return_value = [] # For global check
        self.mock_mt5.positions_get.side_effect = None
        self.mock_mt5.positions_get.return_value = [self.create_mock_trade(start_time)]
        self.mock_mt5.history_deals_get.return_value = []

        is_blocked, reason = self.constraints.is_trade_open("EURUSD")
        self.assertFalse(is_blocked)

    def test_history_trade_too_recent(self):
        """Case: Closed trade started 209 mins ago. Should be blocked."""
        start_time = self.now_ts - (209 * 60)
        self.mock_tick(self.now_ts)
        self.mock_mt5.positions_get.return_value = []
        
        # Mock a historical deal
        deal = self.create_mock_trade(start_time)
        deal.entry = self.mock_mt5.DEAL_ENTRY_IN
        self.mock_mt5.history_deals_get.return_value = [deal]

        is_blocked, reason = self.constraints.is_trade_open("EURUSD")
        self.assertTrue(is_blocked)
        self.assertIn("Recent historical trade", reason)

    def test_history_trade_safe_time(self):
        """Case: Closed trade started 211 mins ago. Should be allowed."""
        start_time = self.now_ts - (211 * 60)
        self.mock_tick(self.now_ts)
        self.mock_mt5.positions_get.return_value = []
        
        deal = self.create_mock_trade(start_time)
        deal.entry = self.mock_mt5.DEAL_ENTRY_IN
        self.mock_mt5.history_deals_get.return_value = [deal]

        is_blocked, reason = self.constraints.is_trade_open("EURUSD")
        self.assertFalse(is_blocked)

if __name__ == "__main__":
    unittest.main()
