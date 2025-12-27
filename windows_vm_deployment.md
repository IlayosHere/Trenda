# 🪟 Windows VM Deployment Guide (MT5 Focus)

This guide provides a detailed, step-by-step process for deploying the Trenda project on a Windows Virtual Machine (VM) to enable MetaTrader 5 (MT5) integration.

---

## 📋 Table of Contents
1. [VM Preparation](#1-vm-preparation)
2. [Software Installation](#2-software-installation)
3. [MetaTrader 5 Configuration](#3-metatrader-5-configuration)
4. [Project Setup](#4-project-setup)
5. [Database Setup](#5-database-setup)
6. [Running the Services](#6-running-the-services)
7. [Automating Startup](#7-automating-startup)

---

## 1. VM Preparation
* **OS**: Windows Server 2019/2022 or Windows 10/11 Pro.
* **RAM**: Minimum 4GB (8GB recommended for smooth development and multiple MT5 terminals).
* **Network**: Ensure "Public" or "Private" network is configured, and keep Python/Uvicorn ports allowed in the Firewall.

---

## 2. Software Installation
Open PowerShell and install the following:

### A. Python 3.9+
1. [Download Python](https://www.python.org/downloads/).
2. **CRITICAL**: Check the box **"Add Python to PATH"** during installation.
3. Verify: `python --version`

### B. Git
1. [Download Git](https://git-scm.com/download/win).
2. Install with default settings.
3. Verify: `git --version`

### C. PostgreSQL (Optional but Recommended on VM)
If you aren't using a cloud database:
1. [Download PostgreSQL](https://www.postgresql.org/download/windows/).
2. Follow the wizard and note down the `POSTGRES_PASSWORD`.

---

## 3. MetaTrader 5 Configuration
1. **Install MT5**: Install the terminal from your broker's website.
2. **Login**: Ensure you are logged into your trading account.
3. **Allow Algo Trading**:
    * Go to **Tools > Options > Expert Advisors**.
    * Check **"Allow Algo Trading"**.
    * Check **"Allow DLL imports"**.
4. **Keep terminal open**: The Python script communicates with the running MT5 process.

---

## 4. Project Setup
1. **Clone the Repo**:
   ```powershell
   git clone <your-repo-url>
   cd Trenda
   ```
2. **Create Virtual Environment**:
   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   ```
3. **Install Core Dependencies**:
   ```powershell
   pip install -r data-retriever/requirements.txt
   pip install -r data-api/requirements.txt
   ```

---

## 5. Database Setup
Create a `.env` file in the root directory:
```env
# Broker Settings
BROKER_PROVIDER=MT5

# Database Settings
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
POSTGRES_DB=trenda
DB_HOST=localhost
DB_PORT=5432

# Logging
LOG_LEVEL=INFO
LOG_FILE=logs/app.log
```

---

## 6. Running the Services
You need two separate terminal windows (with `venv` activated) to run both services.

### Window 1: Data Retriever
```powershell
cd data-retriever
python main.py
```

### Window 2: Data API
```powershell
cd data-api
python -m uvicorn controller:app --host 0.0.0.0 --port 8000
```

---

## 7. Automating Startup
To ensure the system restarts if the VM reboots:

1. **Create a Batch File (`run_trenda.bat`)**:
   ```batch
   @echo off
   cd /d C:\path\to\Trenda
   call venv\Scripts\activate
   start cmd /k "python data-retriever/main.py"
   start cmd /k "uvicorn data-api.controller:app --host 0.0.0.0 --port 8000"
   ```
2. **Add to Startup**:
   * Press `Win + R`, type `shell:startup`, and press Enter.
   * Paste a shortcut to your `.bat` file there.

---

## 🛠️ Troubleshooting
* **MT5 Error 1000**: Ensure the MT5 terminal is actually open and logged in.
* **ModuleNotFoundError**: Always ensure you have activated the virtual environment (`.\venv\Scripts\activate`).
* **Port 8000 blocked**: Open "Windows Firewall with Advanced Security" and create an Inbound Rule for Port 8000.
