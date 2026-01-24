# Trading Lock Scripts

Scripts for managing the trading lock file.

## Scripts

### 1. `clear_trading_lock.py` - Clear Lock

Clears the lock file and allows trading to resume.

**Usage:**
```bash
python scripts/clear_trading_lock.py
```

**What it does:**
- Checks the current lock status
- Displays the lock reason
- Asks for confirmation
- Clears the file
- System will detect the change within 10 seconds (if running)

---

### 2. `create_trading_lock.py` - Create Lock Manually

Creates a lock manually to pause trading (for testing or maintenance).

**Usage:**
```bash
# With reason from command line
python scripts/create_trading_lock.py "Manual pause for maintenance"

# Or without reason (will prompt for input)
python scripts/create_trading_lock.py
```

**What it does:**
- Checks if a lock already exists
- Prompts/receives a reason for locking
- Creates the lock file
- System will detect the change within 10 seconds and pause trading

---

## How It Works

### Automatic Check in Main Loop

The main loop in `main.py` checks the lock status every 10 seconds:

1. **If a lock is created** (manually or automatically):
   - System detects the change
   - Log: `🔒 Trading LOCKED - Trading PAUSED: [reason]`
   - Trading is automatically blocked (system still runs, but no trades are executed)

2. **If a lock is deleted**:
   - System detects the change
   - Log: `✅ Trading lock cleared - Trading RESUMED automatically`
   - Trading automatically resumes

### Where Is Trading Blocked?

The blocking happens in `constraints.py` → `can_execute_trade()`:
- Every call to `place_order()` goes through `can_execute_trade()`
- The function checks the lock **before** any other checks
- If lock exists → returns `is_blocked=True` → trade is not executed

---

## Usage Examples

### Scenario 1: Manual Pause for Maintenance
```bash
# 1. Create lock
python scripts/create_trading_lock.py "Maintenance - checking positions"

# 2. System detects within 10 seconds and stops trading
# 3. Perform maintenance...

# 4. Clear the lock
python scripts/clear_trading_lock.py

# 5. System detects within 10 seconds and resumes trading
```

### Scenario 2: Check Lock Status
```bash
# Simply run the clear script - it will show the status
python scripts/clear_trading_lock.py
```

---

## Lock File Location

The lock file is located at:
```
data-retriever/logs/trading_lock.json
```

You can also delete it manually:
```bash
# Windows
del data-retriever\logs\trading_lock.json

# Linux/Mac
rm data-retriever/logs/trading_lock.json
```

---

## Notes

- The system **does not shut down** when locked - it only stops executing trades
- The scheduler continues running (data refresh, monitoring)
- Only trading is blocked
- Changes are detected automatically within 10 seconds
