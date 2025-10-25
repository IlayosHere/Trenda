import pandas as pd


def print_analysis_results(
    trend_df: pd.DataFrame, high_df: pd.DataFrame, low_df: pd.DataFrame
) -> None:
    """
    Formats and prints all three analysis DataFrames to the console.

    Args:
        trend_df (pd.DataFrame): DataFrame of trend results.
        high_df (pd.DataFrame): DataFrame of structural high prices.
        low_df (pd.DataFrame): DataFrame of structural low prices.
    """

    print("\n" + "=" * 45)
    print("--- 📊 Snake-Line Trend Analysis Results ---")
    print("=" * 45)
    print(trend_df)

    print("\n" + "=" * 45)
    print("--- 📈 Confirmed Structural HIGH Prices ---")
    print("=" * 45)
    # Use to_string() for better formatting of None/NaN
    print(high_df.to_string(float_format="%.5f"))

    print("\n" + "=" * 45)
    print("--- 📉 Confirmed Structural LOW Prices ---")
    print("=" * 45)
    print(low_df.to_string(float_format="%.5f"))


def print_status(message: str) -> None:
    """Prints a standard status message."""
    print(message)


def print_error(message: str) -> None:
    """Prints an error message."""
    print(f"--- ❌ {message} ---")


def print_completion(start_time: float, end_time: float) -> None:
    """Prints a summary of the execution time."""
    print(f"\n--- ✅ Analysis Complete (Took {end_time - start_time:.2f}s) ---")


def print_shutdown(start_time: float, end_time: float) -> None:
    """Prints the total execution time including shutdown."""
    print(f"\nTotal execution time: {end_time - start_time:.2f}s")
