# ============================================================================
# Trenda MT5 Trading Bot - Final Production Dockerfile
# ============================================================================

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC
ENV WINEDEBUG=-all
ENV WINEPREFIX=/home/appuser/.wine
ENV DISPLAY=:99
ENV WINEARCH=win64
ENV WINEDLLOVERRIDES="mscoree,mshtml=" 
ENV PATH="/home/appuser/.local/bin:$PATH"
ENV PYTHONPATH="/app:/app/data-retriever:/app/shared"

# ============================================================================
# System Dependencies & i386 Architecture
# ============================================================================

RUN dpkg --add-architecture i386 && \
    apt-get update && apt-get install -y --no-install-recommends \
    wget curl git gnupg2 software-properties-common ca-certificates cabextract \
    xvfb x11-utils xauth build-essential libpq-dev gfortran libopenblas-dev pkg-config procps \
    libfontconfig1 libfontconfig1:i386 libncurses6:i386 \
    && rm -rf /var/lib/apt/lists/*

# ============================================================================
# Install Python 3.11 & Wine Stable
# ============================================================================

RUN add-apt-repository ppa:deadsnakes/ppa -y && apt-get update && \
    apt-get install -y --no-install-recommends python3.12 python3.12-dev python3-pip && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 && \
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12

RUN mkdir -pm755 /etc/apt/keyrings && \
    wget -O /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key && \
    wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/jammy/winehq-jammy.sources && \
    apt-get update && apt-get install -y --install-recommends winehq-stable && \
    rm -rf /var/lib/apt/lists/*

# ============================================================================
# Create User
# ============================================================================

RUN useradd -m -s /bin/bash appuser
WORKDIR /app

# ============================================================================
# Application Setup (Pip Installation)
# ============================================================================

COPY --chown=appuser:appuser data-retriever/requirements.txt /app/requirements.txt
USER appuser

RUN pip install --no-cache-dir --user --upgrade setuptools wheel pip

RUN pip install --no-cache-dir --user \
    "numpy>=1.24.0" \
    "pandas>=2.0.0" \
    "scipy>=1.10.0"

RUN pip install --no-cache-dir --user pandas-ta

RUN pip install --no-cache-dir --user "rpyc==5.3.1" && \
    pip install --no-cache-dir --user --no-deps "mt5linux==0.1.6"

RUN pip install --no-cache-dir --user -r /app/requirements.txt

# ============================================================================
# Install Python for Windows (Wine)
# ============================================================================

RUN xvfb-run -a wineboot --init && \
    while pgrep wineserver > /dev/null; do sleep 1; done

RUN wget -q -O /tmp/python-installer.exe "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe" && \
    xvfb-run -a wine /tmp/python-installer.exe /quiet InstallAllUsers=1 PrependPath=1 && \
    while pgrep wineserver > /dev/null; do sleep 1; done && \
    rm /tmp/python-installer.exe

RUN xvfb-run -a wine python -m pip install --upgrade setuptools wheel && \
    xvfb-run -a wine python -m pip install MetaTrader5 mt5linux && \
    (wineserver -k || true)

# ============================================================================
# Final Copy & Run
# ============================================================================

USER root
COPY --chown=appuser:appuser data-retriever /app/data-retriever
COPY --chown=appuser:appuser shared /app/shared
COPY --chown=appuser:appuser deployment/entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh && \
    wget -q -O /app/mt5setup.exe "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe" && \
    chown appuser:appuser /app/mt5setup.exe

EXPOSE 8001
USER appuser
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-m", "data-retriever.main"]