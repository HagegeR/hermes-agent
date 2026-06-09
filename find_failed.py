"""
Step 1: Identify which Russell 1000 tickers were NOT scored (fetch failed)
"""
import yfinance as yf
import json

with open('russell_1000_tickers.txt') as f:
    all_tickers = [line.strip() for line in f if line.strip()]

# Load existing scored results
with open('russell_1000_scores.json') as f:
    data = json.load(f)

scored_tickers = {s['ticker'] for s in data['all_scored']}
failed_tickers = [t for t in all_tickers if t not in scored_tickers]

print(f"Total in list:     {len(all_tickers)}")
print(f"Successfully scored: {len(scored_tickers)}")
print(f"Failed to score:     {len(failed_tickers)}")
print(f"\nFailed tickers ({len(failed_tickers)}):")
print(failed_tickers)

# Quick check: try fetching one failed ticker to see what's happening
if failed_tickers:
    t = yf.Ticker(failed_tickers[0])
    info = t.info
    print(f"\nSample failed ticker {failed_tickers[0]} info keys: {list(info.keys())[:20] if info else 'EMPTY'}")
    print(f"Info not empty: {bool(info)}")
    
    # Check if it's a delisted/merged ticker
    try:
        hist = t.history(period='1d')
        print(f"History length: {len(hist)}")
    except Exception as e:
        print(f"History error: {e}")