# Trenda: Forex Trend Analysis System

Trenda is a comprehensive system for analyzing Forex trends using the Snake-Line strategy. It consists of a Data Retriever that fetches market data via MetaTrader 5 (MT5), analyzes it, and stores the results in a PostgreSQL database.

## Project Structure

- **`data-retriever/`**: A background service that connects to MetaTrader 5, fetches candle data, analyzes it, and stores the results in a PostgreSQL database.

## Prerequisites

Before running the project, ensure you have the following installed:

1.  **Python 3.8+**
2.  **PostgreSQL**: A running PostgreSQL instance.
3.  **MetaTrader 5 (MT5) Terminal**: Installed and configured on your Windows machine (required for `data-retriever`).
4.  **MT5 Account**: A demo or real account logged into the MT5 terminal.

## Setup Instructions

### 1. Database Setup

Ensure your PostgreSQL database is running. You can create a database named `trenda` (or whatever you prefer) and a user. The schema will be managed by the application logic (tables are expected to exist or be created by migration scripts if available, otherwise check `db.py` / `database` folder for schema definitions).

### 2. Environment Configuration

Create a `.env` file in the root of the `data-retriever` directory (or a shared one if you prefer to copy it).

**Example `.env`:**

```ini
# Database Configuration
DB_NAME=trenda
DB_USER=postgres
DB_PASSWORD=yourpassword
DB_HOST=localhost
DB_PORT=5432

# Broker/MT5 Configuration (for data-retriever)
BROKER_PROVIDER=mt5
```

### 3. Data Retriever (Background Service)

The Data Retriever collects and analyzes market data.

1.  Navigate to the directory:
    ```bash
    cd data-retriever
    ```
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
3.  Run the bot:
    ```bash
    python main.py
    ```
    _Note: This will attempt to launch/connect to your MT5 terminal. Ensure MT5 is installed._

## Troubleshooting

- **MT5 Initialization Failed**: Ensure the MT5 terminal is installed and not blocked by a firewall. The Python `MetaTrader5` package must be able to launch or connect to the `terminal64.exe`.
- **Database Connection Failed**: Double-check your `.env` variables and ensure the PostgreSQL service is active.
