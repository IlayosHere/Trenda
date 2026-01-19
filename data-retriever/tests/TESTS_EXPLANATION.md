# MT5 Trading Test Suite - Explained (Sequential)

This document explains each test case performed in `test_mt5_trading.py` in its exact execution order (1 to 30).

## Core Operations (1-10)

### 1. Initialize MT5
- **Goal**: Connect to the MetaTrader 5 terminal and verify account details.
- **Expectation**: Success message with account login and server info.

### 2. Place BUY Order (with SL/TP)
- **Goal**: Enter a market BUY trade and confirm Stop Loss and Take Profit are set.
- **Expectation**: A new ticket ID is received and SL/TP levels are visible in the terminal.

### 3. Verify SL/TP (Matching)
- **Goal**: Check if the bot can read the broker's prices without errors.
- **Expectation**: Function returns `True`; no position is closed.

### 4. Verify SL/TP (Idempotence)
- **Goal**: Run the verification again to ensure it doesn't fail on repeated calls.
- **Expectation**: Returns `True` (Stable verification).

### 5. Symbol Constraint (Active Block)
- **Goal**: Try to open the *same* symbol while it is already open.
- **Expectation**: BLOCKED. Prevents duplicate trades on one pair.

### 6. Symbol Constraint (Different Allowed)
- **Goal**: Check if a *different* symbol can be traded while the first is open.
- **Expectation**: ALLOWED. Verification that constraints are pair-specific.

### 7. Close Position
- **Goal**: Request an immediate closure of the test ticket.
- **Expectation**: Terminal confirms the trade is fully removed.

### 8. Cooldown Constraint (History Block)
- **Goal**: Try to open a trade immediately after closing one on the same pair.
- **Expectation**: BLOCKED. Enforces the 3.5-hour "breathing room".

### 9. Place SELL Order (with SL/TP)
- **Goal**: Confirm short-selling logic works exactly like buying.
- **Expectation**: Success message; position is closed immediately after verification.

### 10. Magic Number Filtering
- **Goal**: Ensure the bot only "sees" its own trades and ignores your manual trades.
- **Expectation**: Filtering logic shows isolated counts for the bot.

---

## Logical Precision (11)

### 11. Cooldown Clock (Mocked Time)
- **Goal**: Verify the 210-minute cooldown using high-speed simulation.
- **Scenario**: Checks that 209 mins = Blocked, while 211 mins = Allowed.
- **Expectation**: Pass. Provides mathematical certainty without waiting 3 hours.

---

## Edge Case Testing (12-16)

### 12. Invalid Symbol
- **Goal**: Try to trade a non-existent pair like "XYZ_ABC".
- **Expectation**: Handled gracefully (Returns `None`).

### 13. Zero Volume
- **Goal**: Try to trade with 0.0 lot size.
- **Expectation**: Rejected by MT5 or the Handler for invalid volume.

### 14. Invalid Order Type
- **Goal**: Send a trade signal with an impossible direction (e.g., #999).
- **Expectation**: Rejected before reaching the server.

### 15. Negative SL/TP
- **Goal**: Test system stability against "impossible" math values.
- **Expectation**: Rejected or sanitized to prevent broker errors.

### 16. Invisible Ticket
- **Goal**: Try to close a ticket #999999 that doesn't exist.
- **Expectation**: Success (True). The bot confirms the ticket isn't open anyway.

---

## Stress & Load (17)

### 17. Burst Orders
- **Goal**: Attempt to open multiple different pairs in a split second.
- **Expectation**: Locks/queues handle it correctly; multiple trades are opened sequentially.

---

## Extended Coverage (19-30)

### 19. Connection Re-init (Mocked)
- **Goal**: Ensure the bot can reconnect if the terminal/broker disconnects during a task.
- **Expectation**: Automatical re-initialization triggered on first failure.

### 20. Initialization Failure
- **Goal**: Handle cases where MT5 terminal is closed or refuses to start.
- **Expectation**: Graceful exit without crashing.

### 21. Reject 0.0 Price
- **Goal**: Prevent sending trades with 0.0 price to the broker.
- **Expectation**: Application-level block.

### 22. Symbol Visibility
- **Goal**: Verify the bot can auto-select and enable symbols that are hidden in the Market Watch.
- **Expectation**: Symbol is selected and trade is placed.

### 23. Price Normalization
- **Goal**: Ensure prices are rounded to the correct decimals (digits) for each symbol (e.g., 3 vs 5).
- **Expectation**: Request sent with correctly rounded numbers.

### 24. Tick Info Failure
- **Goal**: Handle cases where the broker fails to provide current price data.
- **Expectation**: Graceful abort of order placement.

### 25. Recovery after Transient Failure
- **Goal**: Test retry logic when a "Close" signal is rejected by the server (e.g., "Request Rejected").
- **Expectation**: Succeeds on second attempt; position is confirmed closed.

### 26. Retry Exhaustion
- **Goal**: Ensure the bot gives up and logs a CRITICAL error after maximum close attempts fail.
- **Expectation**: Detected failure after all retries; emergency alerted.

### 27. Detect Ghost Positions
- **Goal**: Handle cases where the broker says "DONE" but the position remains open in the terminal.
- **Expectation**: Verification logic detects the leak and returns `False`.

### 28. Mismatch triggers closure
- **Goal**: If a position's SL/TP doesn't match the signal (due to broker error), close it immediately for safety.
- **Expectation**: Auto-closure triggered and logged.

### 29. Missing Position in Verification
- **Goal**: Handle cases where a position is closed (e.g., by SL hit) while the bot is trying to verify it.
- **Expectation**: Returns `True` (safe) since the position is indeed gone.

### 30. Concurrency (Shared Lock)
- **Goal**: Simulate multi-threaded signals to ensure the global `mt5_lock` prevents race conditions.
- **Expectation**: All threads wait for the lock and execute sequentially without errors.

---

## Cleanup (18)

### 18. Shutdown MT5
- **Goal**: Safely disconnect from the MT5 server.
- **Expectation**: MT5 terminal connection is released.
