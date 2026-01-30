#!/bin/bash
# ============================================================================
# Trenda MT5 Trading Bot - Container Entrypoint
# Starts Xvfb, initializes Wine, runs MT5, then starts Python app
# ============================================================================

set -e

# Configuration
DISPLAY_NUM=99
MT5_INSTALL_DIR="$WINEPREFIX/drive_c/Program Files/MetaTrader 5"
MT5_TERMINAL="$MT5_INSTALL_DIR/terminal64.exe"
MT5_DATA_DIR="$WINEPREFIX/drive_c/users/$USER/AppData/Roaming/MetaQuotes/Terminal"

echo "========================================"
echo "Trenda MT5 Trading Bot - Startup"
echo "========================================"

# ============================================================================
# Start Xvfb (Virtual Framebuffer)
# ============================================================================

echo "[1/5] Starting Xvfb on display :$DISPLAY_NUM..."

# Kill any existing Xvfb process
pkill Xvfb 2>/dev/null || true

# Start Xvfb in the background
Xvfb :$DISPLAY_NUM -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!

# Wait for Xvfb to start
sleep 2

# Verify Xvfb is running
if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "ERROR: Failed to start Xvfb"
    exit 1
fi

export DISPLAY=:$DISPLAY_NUM
echo "    Xvfb started successfully (PID: $XVFB_PID)"

# ============================================================================
# Initialize Wine Prefix
# ============================================================================

echo "[2/5] Initializing Wine prefix..."

# Set Windows 10 mode
if [ ! -d "$WINEPREFIX" ]; then
    echo "    Creating new Wine prefix..."
    winecfg /v win10
    sleep 5
fi

echo "    Wine prefix ready at: $WINEPREFIX"

# ============================================================================
# Install WebView2 Runtime (if not installed)
# ============================================================================

echo "[3/5] Checking WebView2 Runtime..."

if [ -f "/app/webview2setup.exe" ]; then
    echo "    Installing WebView2 Runtime..."
    wine /app/webview2setup.exe /silent /install 2>/dev/null || true
    sleep 3
fi

# ============================================================================
# Install/Run MetaTrader 5
# ============================================================================

echo "[4/5] Starting MetaTrader 5..."

# Check if MT5 is already installed
if [ ! -f "$MT5_TERMINAL" ]; then
    echo "    Installing MetaTrader 5 (first run)..."
    
    if [ -f "/app/mt5setup.exe" ]; then
        # Install MT5 silently
        wine /app/mt5setup.exe /auto 2>/dev/null &
        MT5_INSTALL_PID=$!
        
        # Wait for installation (timeout after 120 seconds)
        TIMEOUT=120
        ELAPSED=0
        while [ ! -f "$MT5_TERMINAL" ] && [ $ELAPSED -lt $TIMEOUT ]; do
            sleep 5
            ELAPSED=$((ELAPSED + 5))
            echo "    Waiting for MT5 installation... ($ELAPSED/${TIMEOUT}s)"
        done
        
        if [ -f "$MT5_TERMINAL" ]; then
            echo "    MT5 installed successfully!"
        else
            echo "WARNING: MT5 installation may not be complete. Continuing anyway..."
        fi
    else
        echo "ERROR: MT5 setup file not found at /app/mt5setup.exe"
    fi
else
    echo "    MT5 is already installed."
fi

# Start MT5 terminal in the background
if [ -f "$MT5_TERMINAL" ]; then
    echo "    Launching MT5 terminal..."
    wine "$MT5_TERMINAL" /portable 2>/dev/null &
    MT5_PID=$!
    
    # Give MT5 time to initialize
    sleep 10
    echo "    MT5 terminal started (PID: $MT5_PID)"
else
    echo "WARNING: MT5 terminal not found. Python app will start without MT5."
fi

# Start mt5linux server (bridge)
if [ -f "$MT5_TERMINAL" ]; then
    echo "    Starting mt5linux server..."
    # Using python from Wine environment (installed in Dockerfile)
    wine python -m mt5linux &
    MT5_SERVER_PID=$!
    echo "    mt5linux server started (PID: $MT5_SERVER_PID)"
    sleep 3
fi

# ============================================================================
# Run Python Application
# ============================================================================

echo "[5/5] Starting Python application..."
echo "========================================"
echo ""

# Execute the CMD passed to the container (default: python main.py)
exec "$@"
