# Trading Lock Mechanism - Complete Flow Explanation

## Overview

The trading lock mechanism prevents the system from trading after a critical failure occurs. When something goes seriously wrong (e.g., a position cannot be closed), the system:
1. Creates a lock file
2. Shuts down immediately
3. On restart, checks for the lock file and refuses to trade until it's manually cleared

This prevents the system from continuing to trade in an unsafe state.

---

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    NORMAL OPERATION                             │
│  System running → Trading allowed → Positions open/close        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Critical Failure Occurs
                              │ (e.g., position close fails)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              CRITICAL FAILURE DETECTED                           │
│  position_closing.py: close_position() fails after retries      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 1: Log Critical Error                                     │
│  logger.critical("CRITICAL FAILURE: Failed to close...")        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 2: Create Lock File                                       │
│  _trading_lock.create_lock(error_message)                       │
│  → Writes JSON file: logs/trading_lock.json                     │
│  → Contains: reason, timestamp, locked_by                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 3: Shut Down System                                        │
│  shutdown_system(error_message)                                 │
│  → Logs shutdown reason                                         │
│  → Sets shutdown flag                                           │
│  → sys.exit(1) - Process terminates                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SYSTEM RESTART                                │
│  User restarts the system (python main.py)                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 4: Check for Lock File on Startup                         │
│  constraints.py: can_execute_trade()                            │
│  → Calls _trading_lock.is_trading_allowed()                    │
│  → Checks if logs/trading_lock.json exists                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                 │
            Lock File Exists?    No Lock File?
                    │                 │
                    ▼                 ▼
┌───────────────────────────┐  ┌───────────────────────────┐
│  Step 5a: Trading BLOCKED │  │  Step 5b: Trading ALLOWED │
│  Returns:                 │  │  Returns:                 │
│  is_allowed = False       │  │  is_allowed = True        │
│  reason = "Failed to..."  │  │  reason = ""              │
└───────────────────────────┘  └───────────────────────────┘
                    │
                    │ User manually clears lock
                    │ (delete file or call clear_lock())
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 6: Lock Cleared                                           │
│  _trading_lock.clear_lock()                                     │
│  → Deletes logs/trading_lock.json                               │
│  → Trading can resume                                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Detailed Step-by-Step Flow

### Step 1: Critical Failure Occurs

**Location:** `position_closing.py` → `close_position()`

**What happens:**
```python
# System tries to close a position
for attempt in range(1, MT5_CLOSE_RETRY_ATTEMPTS + 1):
    status = self._attempt_close(ticket, attempt)
    if status.success:
        break  # Success!
    
# If we get here, all retries failed
if not success:
    # CRITICAL FAILURE - proceed to Step 2
```

**Example scenario:**
- Position ticket 12345 needs to be closed
- System tries 2 times (configurable)
- Both attempts fail (network error, broker rejection, etc.)
- System determines this is a critical failure

---

### Step 2: Create Lock File

**Location:** `position_closing.py` → `close_position()` → `_trading_lock.create_lock()`

**What happens:**
```python
error_message = "Failed to close position 12345 after 2 attempts"
_trading_lock.create_lock(error_message)
```

**Inside `create_lock()`:**
1. Creates a JSON object with:
   - `reason`: "Failed to close position 12345 after 2 attempts"
   - `timestamp`: "2026-01-23T20:13:49.465181+00:00"
   - `locked_by`: "TradingLock"

2. Writes to file: `logs/trading_lock.json`
   ```json
   {
     "reason": "Failed to close position 12345 after 2 attempts",
     "timestamp": "2026-01-23T20:13:49.465181+00:00",
     "locked_by": "TradingLock"
   }
   ```

3. Logs critical message:
   ```
   🔒 TRADING LOCKED: Failed to close position 12345 after 2 attempts
   Lock file: logs/trading_lock.json
   To resume trading, delete the lock file or call clear_lock()
   ```

**Why this matters:**
- Lock file persists even after system shuts down
- On restart, system will see this file and know trading was locked
- Prevents system from trading again until issue is resolved

---

### Step 3: Shut Down System

**Location:** `position_closing.py` → `shutdown_system()` → `system_shutdown.py`

**What happens:**
```python
from system_shutdown import shutdown_system
shutdown_system(error_message)
```

**Inside `shutdown_system()`:**
1. Logs critical shutdown message
2. Creates lock file (if not already created)
3. Sets shutdown flag: `_shutdown_requested = True`
4. Exits process: `sys.exit(1)`

**Result:**
- Process terminates immediately
- Main loop stops
- Finally block runs (cleanup MT5, scheduler)
- System is completely stopped

---

### Step 4: System Restart - Check for Lock

**Location:** `constraints.py` → `can_execute_trade()` → `_trading_lock.is_trading_allowed()`

**What happens when system restarts:**

1. User starts system: `python main.py`
2. System initializes MT5, scheduler, etc.
3. When code tries to place a trade, it calls:
   ```python
   can_execute_trade("EURUSD")
   ```

4. First thing `can_execute_trade()` does:
   ```python
   is_allowed, lock_reason = _trading_lock.is_trading_allowed()
   if not is_allowed:
       return TradeBlockStatus(True, f"🔒 TRADING LOCKED: {lock_reason}")
   ```

5. `is_trading_allowed()` checks:
   - Does `logs/trading_lock.json` exist?
   - If YES → Read file, return `is_allowed=False` with reason
   - If NO → Return `is_allowed=True`

---

### Step 5a: Trading is Blocked (Lock File Exists)

**What happens:**
```python
# In can_execute_trade()
is_allowed, lock_reason = _trading_lock.is_trading_allowed()
# Returns: (False, "Failed to close position 12345 after 2 attempts (locked at 2026-01-23...)")

# Trade is blocked
return TradeBlockStatus(True, "🔒 TRADING LOCKED: Failed to close position...")
```

**Result:**
- `place_order()` is never called
- System continues running (monitoring, logging)
- But NO trades are executed
- User must manually clear the lock

---

### Step 5b: Trading is Allowed (No Lock File)

**What happens:**
```python
# In can_execute_trade()
is_allowed, lock_reason = _trading_lock.is_trading_allowed()
# Returns: (True, "")

# Continue with normal trade checks
# (check positions, cooldown, etc.)
```

**Result:**
- System operates normally
- Trades can be placed
- No restrictions

---

### Step 6: Clear the Lock

**How to clear the lock:**

**Option 1: Delete the file manually**
```bash
# Delete the lock file
rm logs/trading_lock.json
# Or on Windows:
del logs\trading_lock.json
```

**Option 2: Use the API**
```python
from externals.meta_trader import clear_trading_lock
clear_trading_lock()  # Returns True if cleared
```

**Option 3: In tests**
```python
from externals.meta_trader.safeguards import _trading_lock
_trading_lock.clear_lock()
```

**What happens:**
1. Lock file is deleted
2. System logs: "✅ Trading lock cleared. Trading can resume."
3. Next call to `can_execute_trade()` will return `is_allowed=True`
4. Trading can resume

---

## Key Components

### 1. TradingLock Class (`safeguards.py`)
- **Purpose:** Manages the lock file
- **Key methods:**
  - `create_lock(reason)` - Creates lock file
  - `is_trading_allowed()` - Checks if lock exists
  - `clear_lock()` - Deletes lock file

### 2. System Shutdown (`system_shutdown.py`)
- **Purpose:** Handles immediate system shutdown
- **Key function:**
  - `shutdown_system(reason)` - Logs, creates lock, exits process

### 3. Position Closing (`position_closing.py`)
- **Purpose:** Detects critical failures
- **When it triggers:**
  - Position close fails after all retries
  - Position verification fails (position still open after close)

### 4. Constraints (`constraints.py`)
- **Purpose:** Checks lock before allowing trades
- **First check:** Always checks `is_trading_allowed()` before any trade

---

## Example Scenarios

### Scenario 1: Position Close Fails

```
1. System tries to close position 12345
2. Attempt 1: Fails (network timeout)
3. Wait 1 second
4. Attempt 2: Fails (broker rejection)
5. All retries exhausted
6. Create lock: "Failed to close position 12345 after 2 attempts"
7. Shut down system
8. System stops
9. User restarts system
10. System checks lock file → Trading BLOCKED
11. User investigates issue, fixes it
12. User deletes lock file
13. System can trade again
```

### Scenario 2: Position Verification Fails

```
1. System closes position 12345
2. Order send returns: SUCCESS
3. System waits 0.5 seconds
4. System checks: Is position still open?
5. Position is STILL OPEN (verification fails)
6. Create lock: "Position 12345 still OPEN after close signal was confirmed"
7. Shut down system
8. System stops
```

### Scenario 3: Normal Operation (No Lock)

```
1. System starts
2. No lock file exists
3. System checks: is_trading_allowed() → True
4. Trading proceeds normally
5. Positions open/close successfully
```

---

## Why This Design?

1. **Safety First:** If something critical fails, stop trading immediately
2. **Persistence:** Lock survives restarts - system won't forget it was locked
3. **Manual Control:** User must explicitly clear the lock after fixing the issue
4. **Clear Communication:** Lock file contains reason and timestamp
5. **Fail-Safe:** If lock file is corrupted, system blocks trading (safer than allowing)

---

## File Locations

- **Lock file:** `data-retriever/logs/trading_lock.json`
- **Code files:**
  - `externals/meta_trader/safeguards.py` - TradingLock class
  - `externals/meta_trader/position_closing.py` - Detects failures
  - `system_shutdown.py` - Handles shutdown
  - `externals/meta_trader/constraints.py` - Checks lock before trading

---

## Summary

The trading lock mechanism is a **safety net** that:
1. **Detects** critical failures (position close fails)
2. **Records** the failure in a persistent lock file
3. **Stops** the system immediately
4. **Prevents** trading on restart until lock is cleared
5. **Requires** manual intervention to resume trading

This ensures the system never continues trading in an unsafe state after a critical failure.
