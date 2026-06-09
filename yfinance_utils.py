"""
yfinance_utils.py
=================
Universal yfinance v1.4.1 MultiIndex column extractor.
Used by ALL scripts that download price data.

yfinance v1.4.1 returns MultiIndex columns: (Price, Ticker) for single-ticker downloads
e.g. [('Close', 'INTC'), ('High', 'INTC'), ...] — two-level MultiIndex

This module provides safe extraction of OHLCV columns that works regardless of:
- Single-ticker vs multi-ticker batch downloads
- auto_adjust=True vs False
- Price column MultiIndex vs simple columns
- TZ-aware vs TZ-naive indexes
"""
import pandas as pd
import yfinance as yf


def get_close(df: pd.DataFrame) -> pd.Series:
    """
    Universal Close price extractor for yfinance v1.4.1.
    
    Handles all yfinance column structures:
    1. MultiIndex (Price, Ticker) — e.g. [('Close','INTC'), ('High','INTC'), ...]
    2. Simple ['Close', 'High', ...] columns
    3. Single-column DataFrame (no column name)
    4. MultiIndex with only one price type (squeeze)
    
    Returns:
        pd.Series with DatetimeIndex
    
    Raises:
        ValueError: if df is empty, None, or has no Close column
    """
    if df is None or df.empty:
        raise ValueError("Empty DataFrame passed to get_close()")
    
    # Case 1: MultiIndex columns from yfinance v1.4.1 single-ticker OR multi-ticker download
    # Single-ticker structure: [('Close','INTC'), ('High','INTC'), ...] → levels: [Price types], [Tickers]
    # Multi-ticker structure: [('Close','INTC'), ('Close','NVDA'), ('High','INTC'), ('High','NVDA'), ...]
    #                          OR [('Close', 'INTC'), ('High', 'INTC'), ...] when auto_adjust=True
    if isinstance(df.columns, pd.MultiIndex):
        l0_values = df.columns.get_level_values(0).tolist()
        l1_values = df.columns.get_level_values(1).tolist()
        n_tickers = len(set(l1_values))
        n_price_types = len(set(l0_values))
        
        # Determine which level is ticker vs price type
        # If level 1 has ticker-like values (long names, multiple unique) and level 0 has OHLCV → (Price, Ticker)
        # If level 0 has few OHLCV types and level 1 has ticker-like values → (Ticker, Price)
        ohlcv = {'Open', 'High', 'Low', 'Close', 'Volume', 'Adj Close'}
        
        if n_price_types <= 6 and set(l0_values).issubset(ohlcv):
            # level 0 = price types → structure is (Price, Ticker)
            if 'Close' in l0_values:
                idx = l0_values.index('Close')
            elif 'Adj Close' in l0_values:
                idx = l0_values.index('Adj Close')
            elif len(df.columns.levels[0]) == 1:
                idx = 0
            else:
                idx = 0
            
            if n_tickers == 1:
                # Single-ticker MultiIndex → squeeze to Series
                result = df.iloc[:, idx].squeeze()
            else:
                # Multi-ticker: extract Close column (which may span multiple tickers)
                # Return the entire Close column — caller must handle multi-ticker case
                result = df.iloc[:, idx]
                if isinstance(result, pd.DataFrame):
                    result = result.squeeze() if len(result.columns) == 1 else result
                return result
        else:
            # level 0 = tickers → structure is (Ticker, Price)
            idx = 0
            result = df.iloc[:, idx].squeeze()
        
        if isinstance(result, pd.DataFrame):
            result = result.squeeze()
        return result
    
    # Case 2: Simple columns ['Close', 'High', ...]
    if 'Close' in df.columns:
        col = df['Close']
        # If it's a DataFrame with one column, squeeze
        if isinstance(col, pd.DataFrame):
            col = col.squeeze()
        return col
    
    # Case 3: Single column (no 'Close' name)
    if len(df.columns) == 1:
        result = df.iloc[:, 0]
        if isinstance(result, pd.DataFrame):
            result = result.squeeze()
        return result
    
    # Fallback: first column
    result = df.iloc[:, 0]
    if isinstance(result, pd.DataFrame):
        result = result.squeeze()
    return result


def get_ohlcv(df: pd.DataFrame) -> dict:
    """
    Extract all OHLCV columns from yfinance MultiIndex DataFrame.
    Returns dict with keys: open, high, low, close, volume (lowercase)
    Missing columns return None.
    """
    if df is None or df.empty:
        return {}
    
    result = {}
    
    if isinstance(df.columns, pd.MultiIndex):
        l0_values = df.columns.get_level_values(0).tolist()
        for price_type in ['Open', 'High', 'Low', 'Close', 'Volume']:
            if price_type in l0_values:
                idx = l0_values.index(price_type)
                col = df.iloc[:, idx]
                if isinstance(col, pd.DataFrame):
                    col = col.squeeze()
                result[price_type.lower()] = col
            else:
                result[price_type.lower()] = None
    else:
        for price_type in ['open', 'high', 'low', 'close', 'volume']:
            col = df.get(price_type.capitalize(), df.get(price_type))
            if col is not None and isinstance(col, pd.DataFrame):
                col = col.squeeze()
            result[price_type] = col
    
    return result


def download_price(ticker: str, start: str, end: str, auto_adjust: bool = True) -> pd.Series:
    """
    Download Close price for one ticker, returns clean pd.Series.
    Handles yfinance MultiIndex quirks automatically.
    """
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=auto_adjust)
    return get_close(df)


def download_batch(tickers: list, start: str, end: str, auto_adjust: bool = True,
                   batch_size: int = 15, delay: float = 0.3) -> pd.DataFrame:
    """
    Download prices for multiple tickers in batches.
    
    Args:
        tickers: list of ticker symbols
        start: start date YYYY-MM-DD
        end: end date YYYY-MM-DD
        auto_adjust: use auto_adjust (default True)
        batch_size: tickers per batch (default 15)
        delay: seconds between batches (default 0.3)
    
    Returns:
        pd.DataFrame with Close prices, columns = tickers, index = dates
    """
    import time
    
    all_data = {}
    total_batches = (len(tickers) + batch_size - 1) // batch_size
    
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        batch_num = i // batch_size + 1
        print(f"  Batch {batch_num}/{total_batches}: {batch[:5]}{'...' if len(batch) > 5 else ''}")
        
        try:
            df = yf.download(batch, start=start, end=end, progress=False, auto_adjust=auto_adjust)
            
            if df is None or df.empty:
                print(f"    ⚠️ No data for batch")
                continue
            
            # MultiIndex: (Price, Ticker) when multiple tickers — group_cols=None keeps this structure
            if isinstance(df.columns, pd.MultiIndex) and len(df.columns.levels[0]) > 1:
                # group_cols=None gives (Ticker, Price) structure
                # Try to extract Close for each ticker
                if 'Close' in df.columns.get_level_values(1):
                    # Structure: (Ticker, Price) → level 1 = Price types
                    for ticker in batch:
                        if (ticker, 'Close') in df.columns:
                            all_data[ticker] = df[(ticker, 'Close')]
                        elif ticker in df.columns.get_level_values(0):
                            # Structure: (Price, Ticker) → check level 1 for ticker
                            pass
                elif len(df.columns.levels[0]) == len(batch):
                    # Structure: (Ticker, Price) — level 0 = tickers
                    for ticker in batch:
                        if ticker in df.columns.get_level_values(0):
                            cols_for_ticker = df[ticker]
                            if 'Close' in cols_for_ticker.columns:
                                all_data[ticker] = cols_for_ticker['Close'].squeeze()
                            elif len(cols_for_ticker.columns) == 1:
                                all_data[ticker] = cols_for_ticker.iloc[:, 0]
                else:
                    # Fallback: try level 1
                    for ticker in batch:
                        try:
                            col = get_close(df[ticker])
                            all_data[ticker] = col
                        except:
                            pass
            else:
                # Single ticker or simple columns — try get_close
                for ticker in batch:
                    try:
                        if ticker in df.columns.get_level_values(0) if isinstance(df.columns, pd.MultiIndex) else ticker in df.columns:
                            all_data[ticker] = get_close(df[ticker] if isinstance(df.columns, pd.MultiIndex) else df)
                        else:
                            all_data[ticker] = get_close(df)
                        break  # only one ticker in this df
                    except:
                        pass
        
        except Exception as e:
            print(f"    ❌ Batch error: {e}")
        
        if i + batch_size < len(tickers):
            time.sleep(delay)
    
    if not all_data:
        return pd.DataFrame()
    
    prices = pd.DataFrame(all_data)
    prices = prices.dropna()
    
    # Normalize index to tz-naive UTC for consistency
    prices.index = pd.to_datetime(prices.index)
    if prices.index.tz is not None:
        prices.index = prices.index.tz_localize(None)
    
    return prices


if __name__ == '__main__':
    # Quick test
    print("Testing get_close() with INTC...")
    df = yf.download('INTC', start='2023-01-01', end='2023-01-10', progress=False, auto_adjust=True)
    close = get_close(df)
    print(f"  Type: {type(close)}, Shape: {close.shape}")
    print(f"  Head:\n{close.head()}")
    
    print("\nTesting download_price()...")
    s = download_price('GOOGL', '2023-01-01', '2023-01-10')
    print(f"  Type: {type(s)}, Shape: {s.shape}")
    print(f"  Head:\n{s.head()}")