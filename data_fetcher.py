import MetaTrader5 as mt5
import pandas as pd

def fetch_data(symbol, timeframe_mt5, lookback_candles):
    """Fetches OHLC data from MT5 for the 'line graph' analysis."""
    rates = mt5.copy_rates_from_pos(symbol, timeframe_mt5, 0, lookback_candles)
    if rates is None or len(rates) == 0:
        print(f"Failed to get data for {symbol} on TF {timeframe_mt5}")
        return None
    return convert_graph_data(rates)

def convert_graph_data(data):
    fetched_data = pd.DataFrame(data)
    fetched_data['time'] = pd.to_datetime(fetched_data['time'], unit='s')
    # Set time as index, which is good practice
    fetched_data.set_index('time', inplace=True)
    return fetched_data