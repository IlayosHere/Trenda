# ============================================================================
# Trenda MT5 Trading Bot - Production Dockerfile
# Base: Ubuntu 22.04 with Python 3.11, Wine Stable, Xvfb
# ============================================================================

FROM ubuntu:22.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Set Wine environment variables
ENV WINEDEBUG=-all
ENV WINEPREFIX=/home/appuser/.wine
ENV DISPLAY=:99
ENV WINEARCH=win64

# Python environment
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/home/appuser/.local/bin:$PATH"
ENV PYTHONPATH="/app:/app/data-retriever:/app/shared"

# ============================================================================
# System Dependencies
# ============================================================================

RUN apt-get update && apt-get install -y --no-install-recommends \
    # Basic utilities
    wget \
    curl \
    gnupg2 \
    software-properties-common \
    ca-certificates \
    cabextract \
    # Required for Wine
    xvfb \
    x11-utils \
    xauth \
    # Build dependencies for Python packages
    build-essential \
    libpq-dev \
    # Clean up
    && rm -rf /var/lib/apt/lists/*

# ============================================================================
# Install Python 3.11 from deadsnakes PPA (more compatible with packages)
# ============================================================================

RUN add-apt-repository ppa:deadsnakes/ppa -y \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    python3.11-distutils \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.11 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

# Install pip for Python 3.11
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11

# ============================================================================
# Install Wine Stable from WineHQ
# ============================================================================

RUN dpkg --add-architecture i386 \
    && mkdir -pm755 /etc/apt/keyrings \
    && wget -O /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key \
    && wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/jammy/winehq-jammy.sources \
    && apt-get update \
    && apt-get install -y --install-recommends winehq-stable \
    && rm -rf /var/lib/apt/lists/*

# ============================================================================
# Create non-root user
# ============================================================================

RUN useradd -m -s /bin/bash appuser \
    && mkdir -p /home/appuser/.wine \
    && chown -R appuser:appuser /home/appuser

# ============================================================================
# Application Setup
# ============================================================================

WORKDIR /app

COPY --chown=appuser:appuser data-retriever/requirements.txt /app/requirements.txt

USER appuser

# Install Python dependencies with better error handling
RUN pip install --no-cache-dir --user --upgrade setuptools wheel pip

# Install packages individually to better handle version conflicts
RUN pip install --no-cache-dir --user APScheduler python-dotenv psycopg2-binary requests pytest pytest-mock

# Install data science packages
RUN pip install --no-cache-dir --user "numpy>=1.21.0" "pandas>=1.5.0" "scipy>=1.7.0"

# Install pandas-ta (use latest compatible version)
RUN pip install --no-cache-dir --user pandas-ta

# Install MT5 bridge
RUN pip install --no-cache-dir --user mt5linux

# ============================================================================
# Install Python for Windows (for mt5linux server)
# ============================================================================

# Initialize Wine, install Python 3.11, and install MetaTrader5 + mt5linux
RUN xvfb-run -a wine wineboot --init \
    && xvfb-run -a winecfg /v win10 \
    && wget -q -O /tmp/python-installer.exe "https://www.python.org/ftp/python/3.11.5/python-3.11.5-amd64.exe" \
    && xvfb-run -a wine /tmp/python-installer.exe /quiet InstallAllUsers=1 PrependPath=1 \
    && rm /tmp/python-installer.exe \
    && xvfb-run -a wine python -m pip install --upgrade setuptools wheel \
    && xvfb-run -a wine python -m pip install MetaTrader5 mt5linux \
    && (wineserver -k || true)

# Switch back to root for remaining setup
USER root

# Copy application code
COPY --chown=appuser:appuser data-retriever /app/data-retriever
COPY --chown=appuser:appuser shared /app/shared

# Copy and set up entrypoint script
COPY --chown=appuser:appuser deployment/entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh

# Download MetaTrader 5 installer
RUN wget -q -O /app/mt5setup.exe "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe" \
    && wget -q -O /app/webview2setup.exe "https://msedge.sf.dl.delivery.mp.microsoft.com/filestreamingservice/files/c1336fd6-a2eb-4669-9b03-949fc70ace0e/MicrosoftEdgeWebview2Setup.exe" \
    && chown appuser:appuser /app/mt5setup.exe /app/webview2setup.exe

# ============================================================================
# Runtime Configuration
# ============================================================================

# Expose application port
EXPOSE 8001

# Switch to non-root user for runtime
USER appuser

# Set entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]

# Default command - run the Python application from the data-retriever directory
CMD ["python", "data-retriever/main.py"]
