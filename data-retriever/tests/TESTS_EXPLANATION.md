# MT5 Trading Test Suite - Explained (Sequential)

This document explains each test case performed in `test_mt5_trading.py` in its exact execution order (1 to 18).

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
- **Expectation**: Filtering logic shows a isolated counts for the bot.

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
- **Goal**: Attempt to open 5 different pairs in a split second.
- **Expectation**: Locks/queues handle it correctly; multiple trades are opened sequentially.

---

## Cleanup (18)

### 18. Shutdown MT5
- **Goal**: Safely disconnect from the MT5 server.
- **Expectation**: MT5 terminal connection is released.
