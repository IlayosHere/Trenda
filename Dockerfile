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
# System Dependencies, Python & Wine Stable
# ============================================================================

RUN dpkg --add-architecture i386 && \
    apt-get update && apt-get install -y --no-install-recommends \
    wget curl git gnupg2 software-properties-common ca-certificates cabextract \
    xvfb x11-utils xauth build-essential libpq-dev gfortran libopenblas-dev pkg-config procps \
    libfontconfig1 libfontconfig1:i386 libncurses6:i386 && \
    add-apt-repository ppa:deadsnakes/ppa -y && apt-get update && \
    apt-get install -y --no-install-recommends python3.12 python3.12-dev python3-pip && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 && \
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 && \
    mkdir -pm755 /etc/apt/keyrings && \
    wget -O /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key && \
    wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/jammy/winehq-jammy.sources && \
    apt-get update && apt-get install -y --install-recommends winehq-stable && \
    rm -rf /var/lib/apt/lists/*

# ============================================================================
# Create User & Setup
# ============================================================================

RUN useradd -m -s /bin/bash appuser
WORKDIR /app

# ============================================================================
# Linux Python Dependencies (Grouped for Caching)
# ============================================================================

COPY --chown=appuser:appuser data-retriever/requirements.txt /app/requirements.txt
USER appuser

RUN pip install --no-cache-dir --user --upgrade setuptools wheel pip && \
    pip install --no-cache-dir --user \
    "numpy>=1.24.0" "pandas>=2.0.0" "scipy>=1.10.0" "pandas-ta" "rpyc==5.3.1" && \
    pip install --no-cache-dir --user --no-deps "mt5linux==0.1.6" && \
    pip install --no-cache-dir --user -r /app/requirements.txt

# ============================================================================
# Wine Side: Python & MT5 (Grouped to minimize wineserver cycles)
# ============================================================================

# Wine Side: Python & Basic Libs
RUN xvfb-run -a wineboot --init && \
    while pgrep wineserver > /dev/null; do sleep 1; done && \
    wget -q -O /tmp/python-installer.exe "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe" && \
    xvfb-run -a wine /tmp/python-installer.exe /quiet InstallAllUsers=1 PrependPath=1 && \
    while pgrep wineserver > /dev/null; do sleep 1; done && \
    rm /tmp/python-installer.exe && \
    xvfb-run -a wine python -m pip install --upgrade setuptools wheel && \
    xvfb-run -a wine python -m pip install --only-binary :all: cffi MetaTrader5 && \
    xvfb-run -a wine python -m pip install --no-deps mt5linux && \
    wineserver -k && sleep 2

# Wine Side: MT5 Terminal (Robust installation with Wine-Mono)
RUN wget -q -O /tmp/wine-mono-9.4.0-x86.msi "https://dl.winehq.org/wine/wine-mono/9.4.0/wine-mono-9.4.0-x86.msi" && \
    xvfb-run -a wine msiexec /i /tmp/wine-mono-9.4.0-x86.msi /quiet /qn && \
    rm /tmp/wine-mono-9.4.0-x86.msi && \
    wget -q -O /tmp/mt5setup.exe "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe" && \
    (Xvfb :99 -screen 0 1024x768x16 &) && \
    export DISPLAY=:99 && \
    wine /tmp/mt5setup.exe /auto /path:"C:\mt5" & \
    echo "Installer started. Waiting up to 20 minutes for terminal64.exe..." && \
    for i in {1..40}; do \
    if find "$WINEPREFIX/drive_c" -name "terminal64.exe" | grep -q .; then \
    echo "Terminal found! Allowing 30s for final sync..." && \
    sleep 30; \
    break; \
    fi; \
    echo "Waiting for MT5... (Attempt $i/40)"; \
    sleep 30; \
    done && \
    wineserver -k && \
    pkill Xvfb && \
    rm /tmp/mt5setup.exe

# ============================================================================
# Final Copy & Run
# ============================================================================

USER root
RUN ln -sf /usr/bin/python3.12 /usr/bin/python
COPY --chown=appuser:appuser data-retriever /app/data-retriever
COPY --chown=appuser:appuser shared /app/shared
COPY --chown=appuser:appuser deployment/entrypoint.sh /app/entrypoint.sh

RUN sed -i 's/\r$//' /app/entrypoint.sh && \
    chmod +x /app/entrypoint.sh && \
    chown appuser:appuser /app/entrypoint.sh

EXPOSE 8001
USER appuser
ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]
CMD ["python3", "-m", "data-retriever.main"]
