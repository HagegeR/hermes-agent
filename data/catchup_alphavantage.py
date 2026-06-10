#!/usr/bin/env python3
"""
Catch-up script for Alpha Vantage data.
Run this AFTER the daily API limit has reset (next calendar day).
Fetches tech stocks + FX data in one pass using the centralized fetcher.
"""
import os, sys, time, sqlite3, pandas as pd
from datetime import datetime

# Add parent to path
sys.path.insert(0, '/root')
from centralized_fetcher import CentralizedDataFetcher

periods = [
    ("May 2022",  "2022-05-01", "2022-05-31"),
    ("Sep 2022",  "2022-09-01", "2022-09-30"),
    ("Oct 2022",  "2022-10-01", "2022-10-31"),
    ("Jan 2023",  "2023-01-01", "2023-01-31"),
]

fetcher = CentralizedDataFetcher()

print(f"=== Alpha Vantage catch-up ({datetime.now().isoformat()}) ===")
print("This will use ~8 API calls (5 tech + 3 FX)")
av = fetcher.fetch_all_alphavantage(periods)
print(f"\nResult: {av['tech_stocks']} tech + {av['fx']} FX records")

# Verify
conn = fetcher.get_conn()
for table in ['market_data', 'fx_data']:
    try:
        df = pd.read_sql(f"SELECT source, COUNT(*) FROM {table} WHERE source='alphavantage' GROUP BY source", conn)
        if not df.empty:
            print(f"  {table}: {df.values}")
    except:
        pass
conn.close()