#!/bin/bash
# ============================================================================
# Trenda MT5 Trading Bot - Container Entrypoint
# Starts Xvfb, initializes Wine, runs MT5, then starts Python app
# ============================================================================

set -e

# Configuration
DISPLAY_NUM=99
MT5_INSTALL_DIR="/home/appuser/.wine/drive_c/mt5"
MT5_TERMINAL="$MT5_INSTALL_DIR/terminal64.exe"
MT5_DATA_DIR="$MT5_INSTALL_DIR" # In portable mode, data dir is the same as install dir

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
# Run MetaTrader 5 (Static Installation)
# ============================================================================

echo "[4/5] Starting MetaTrader 5..."

# Check if MT5 is installed (should be from Docker build at C:\Program Files\MetaTrader 5)
if [ ! -f "$MT5_TERMINAL" ]; then
    echo "ERROR: MT5 terminal not found at $MT5_TERMINAL. Build may have failed."
    echo "    Searching for terminal64.exe..."
    ALT_PATH=$(find "$WINEPREFIX/drive_c" -name "terminal64.exe" | head -n 1)
    if [ -n "$ALT_PATH" ]; then
        MT5_TERMINAL="$ALT_PATH"
        echo "    Found at alternative path: $MT5_TERMINAL"
    else
        ls -R "$WINEPREFIX/drive_c/Program Files" 2>/dev/null || echo "      (Program Files not found)"
        exit 1
    fi
fi

# Start MT5 terminal in the background
echo "    Launching MT5 terminal..."
# Always use portable mode to keep data local
wine "$MT5_TERMINAL" /portable /notimeout /skipupdate 2>/tmp/mt5_terminal.log &
MT5_PID=$!

# Give MT5 time to initialize
sleep 15
echo "    MT5 terminal process status: $(ps -p $MT5_PID -o state= || echo 'DEAD')"

# Start mt5linux server (bridge)
if [ -f "$MT5_TERMINAL" ]; then
    echo "    Starting mt5linux server..."
    # Using python from Wine environment (installed in Dockerfile)
    wine python -m mt5linux 2>/tmp/mt5_server_err.log &
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
