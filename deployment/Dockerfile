# ============================================================================
# Trenda MT5 Trading Bot - Production Dockerfile
# Base: Ubuntu 22.04 with Python 3.12, Wine Stable, Xvfb
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
# Install Python 3.12 from deadsnakes PPA
# ============================================================================

RUN add-apt-repository ppa:deadsnakes/ppa -y \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    python3.12-distutils \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.12 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1

# Install pip for Python 3.12
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12

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

# Copy requirements first for layer caching
COPY --chown=appuser:appuser requirements.txt /app/

# Switch to non-root user for pip install
USER appuser

# Install Python dependencies
# Note: MetaTrader5 package is Windows-only, we use Wine for MT5 terminal
RUN pip install --no-cache-dir --user \
    APScheduler \
    pandas \
    python-dotenv \
    psycopg2-binary \
    requests \
    numpy \
    pandas_ta \
    scipy \
    mt5linux

# ============================================================================
# Install Python for Windows (for mt5linux server)
# ============================================================================

# Initialize Wine, install Python 3.11, and install MetaTrader5 + mt5linux
RUN xvfb-run -a wine wineboot --init \
    && xvfb-run -a winecfg /v win10 \
    && wget -q -O /tmp/python-installer.exe "https://www.python.org/ftp/python/3.11.5/python-3.11.5-amd64.exe" \
    && xvfb-run -a wine /tmp/python-installer.exe /quiet InstallAllUsers=1 PrependPath=1 \
    && rm /tmp/python-installer.exe \
    && xvfb-run -a wine python -m pip install MetaTrader5 mt5linux \
    && (wineserver -k || true)

# Switch back to root for remaining setup
USER root

# Copy application code
COPY --chown=appuser:appuser . /app/

# Copy and set up entrypoint script
COPY --chown=appuser:appuser entrypoint.sh /app/
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

# Default command - run the Python application
CMD ["python", "main.py"]
