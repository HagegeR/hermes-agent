"""
Test rate limit and score only the highest-impact missing tickers
"""
import yfinance as yf, time, json

# Test if rate limit cleared
test = ['NVDA', 'AMD', 'V', 'C']
for ticker in test:
    t = yf.Ticker(ticker)
    try:
        info = t.info
        if info and 'quoteType' in info:
            print(f"✅ {ticker}: PE={info.get('trailingPE')}, MC={info.get('marketCap')}, RevGrowth={info.get('revenueGrowth')}")
        else:
            print(f"❌ {ticker}: still rate limited")
    except Exception as e:
        print(f"❌ {ticker}: {e}")
    time.sleep(1)