import os
import sqlite3
from datetime import datetime, timedelta
import time
import yfinance as yf
import pandas as pd
import requests
from collections import defaultdict
from functools import wraps

# =============================================
# 1. RATE LIMITING DECORATOR (per API key)
# =============================================

def rate_limited(max_per_minute):
    """Decorator to enforce rate limits"""
    def decorate(func):
        calls = defaultdict(int)
        last_reset = datetime.now()

        @wraps(func)
        def rate_limited_function(*args, **kwargs):
            nonlocal calls, last_reset

            now = datetime.now()
            if (now - last_reset).total_seconds() >= 60:
                calls = defaultdict(int)
                last_reset = now

            key = func.__name__
            if calls[key] >= max_per_minute:
                wait = 60 - (now - last_reset).total_seconds()
                if wait > 0:
                    print(f"  Rate limit for {key}. Waiting {wait:.0f}s...")
                    time.sleep(wait + 0.5)
                    calls = defaultdict(int)
                    last_reset = datetime.now()

            calls[key] += 1
            return func(*args, **kwargs)
        return rate_limited_function
    return decorate

# =============================================
# 2. CENTRALIZED FETCHER
# =============================================

class CentralizedDataFetcher:
    def __init__(self, db_path='/root/trading_audit.db'):
        self.db_path = db_path
        self.news_api_key = os.getenv("NEWS_API_KEY", "ee7c65f08e7d4d68905b402e167a8612")
        self.alpha_vantage_key = os.getenv("ALPHA_VANTAGE_KEY", "LLTZRLOWUVAUMSDU")
        self.api_endpoints = {
            'newsapi': "https://newsapi.org/v2/everything",
            'alphavantage': "https://www.alphavantage.co/query"
        }
        # Track AV daily usage (25 req/day free tier)
        self.av_daily_calls = 0
        self.av_day_start = datetime.now().date()

    def get_conn(self):
        return sqlite3.connect(self.db_path)

    def setup_database(self):
        conn = self.get_conn()
        c = conn.cursor()
        for table_sql in [
            '''CREATE TABLE IF NOT EXISTS market_data (id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME, source TEXT, symbol TEXT, price REAL, volume INTEGER,
                signal_type TEXT, signal_strength REAL, headline TEXT, sentiment TEXT,
                open REAL, high REAL, low REAL, adjusted_close REAL,
                dividend_amount REAL, split_coefficient REAL,
                from_symbol TEXT, to_symbol TEXT)''',
            '''CREATE TABLE IF NOT EXISTS news_signals (id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME, source TEXT, headline TEXT, url TEXT,
                sentiment TEXT, relevance REAL)''',
            '''CREATE TABLE IF NOT EXISTS sector_performance (id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME, source TEXT, sector TEXT, performance REAL)''',
            '''CREATE TABLE IF NOT EXISTS fx_data (id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME, source TEXT, from_symbol TEXT, to_symbol TEXT,
                open REAL, high REAL, low REAL, close REAL)'''
        ]:
            c.execute(table_sql)
        conn.commit()
        conn.close()

    def _check_av_daily_limit(self):
        """Track daily Alpha Vantage usage (25 req/day limit)"""
        today = datetime.now().date()
        if today > self.av_day_start:
            self.av_daily_calls = 0
            self.av_day_start = today
        if self.av_daily_calls >= 24:  # Leave 1 buffer
            print("  ALPHA VANTAGE: Daily limit reached (25/25). Skipping remaining AV calls.")
            return False
        self.av_daily_calls += 1
        return True

    def _av_request(self, params, retries=2):
        """Centralized Alpha Vantage request with rate limiting and retries"""
        for attempt in range(retries + 1):
            try:
                params["apikey"] = self.alpha_vantage_key
                r = requests.get(self.api_endpoints['alphavantage'], params=params, timeout=15)
                if r.status_code == 200:
                    return r.json()
                else:
                    note = r.text[:150]
                    print(f"  AV HTTP {r.status_code}: {note}")
            except Exception as e:
                if attempt < retries:
                    print(f"  AV retry {attempt+1}/{retries} after error: {str(e)}")
                    time.sleep(2)
                else:
                    print(f"  AV failed after {retries+1} attempts: {str(e)}")
        return None

    # ---- YFINANCE (60 req/min, effectively unlimited) ----

    @rate_limited(60)
    def fetch_spy_data(self, start_date, end_date):
        try:
            data = yf.download('SPY', start=start_date, end=end_date)
            if not data.empty:
                data = data.reset_index()
                data['source'] = 'yfinance'
                data['symbol'] = 'SPY'
                data['signal_type'] = 'benchmark'
                data['timestamp'] = data['Date'].astype(str)
                cols = ['timestamp', 'source', 'symbol', 'Close', 'Volume', 'signal_type']
                data = data[cols]
                data.columns = ['timestamp', 'source', 'symbol', 'price', 'volume', 'signal_type']
                conn = self.get_conn()
                data.to_sql('market_data', conn, if_exists='append', index=False)
                n = len(data)
                conn.close()
                print(f"  SPY: {n} rec")
                return n
        except Exception as e:
            print(f"  SPY err: {e}")
        return 0

    @rate_limited(60)
    def fetch_crypto_data(self, start_date, end_date):
        total = 0
        for symbol in ["BTC-USD", "ETH-USD"]:
            try:
                data = yf.download(symbol, start=start_date, end=end_date)
                if not data.empty:
                    data = data.reset_index()
                    data['source'] = 'yfinance'
                    data['symbol'] = symbol
                    data['signal_type'] = 'crypto_momentum'
                    data['timestamp'] = data['Date'].astype(str)
                    data['signal_strength'] = data['Close'].pct_change().rolling(3).mean().fillna(0)
                    cols = ['timestamp', 'source', 'symbol', 'Close', 'Volume',
                            'signal_type', 'signal_strength']
                    data = data[cols]
                    data.columns = ['timestamp', 'source', 'symbol', 'price', 'volume',
                                   'signal_type', 'signal_strength']
                    conn = self.get_conn()
                    data.to_sql('market_data', conn, if_exists='append', index=False)
                    n = len(data)
                    conn.close()
                    total += n
                    print(f"  {symbol}: {n} rec")
            except Exception as e:
                print(f"  {symbol} err: {e}")
        return total

    # ---- NEWS API (60 req/min) ----

    @rate_limited(60)
    def fetch_news_signals(self, start_dt, end_dt, queries=None):
        if not self.news_api_key:
            return 0
        if queries is None:
            queries = ["S&P 500 OR SPY", "technology stocks", "Fed OR Federal Reserve",
                       "inflation OR CPI", "earnings"]
        all_sigs = []
        for query in queries:
            params = {"q": query,
                      "from_param": start_dt.strftime("%Y-%m-%d"),
                      "to": end_dt.strftime("%Y-%m-%d"),
                      "sortBy": "publishedAt", "language": "en", "pageSize": 100,
                      "apiKey": self.news_api_key}
            try:
                r = requests.get(self.api_endpoints['newsapi'], params=params, timeout=15)
                if r.status_code == 200:
                    for art in r.json().get("articles", []):
                        try:
                            t = datetime.strptime(art["publishedAt"], "%Y-%m-%dT%H:%M:%SZ")
                            if start_dt <= t <= end_dt:
                                text = art["title"] + " " + (art.get("description", ""))
                                s = "positive" if "up" in text.lower() else \
                                    "negative" if "down" in text.lower() else "neutral"
                                all_sigs.append({"timestamp": t, "source": "newsapi",
                                    "headline": art["title"], "url": art["url"],
                                    "sentiment": s, "relevance": 0.8})
                        except:
                            pass
            except:
                pass
        if all_sigs:
            conn = self.get_conn()
            pd.DataFrame(all_sigs).to_sql('news_signals', conn, if_exists='append', index=False)
            n = len(all_sigs)
            conn.close()
            print(f"  News: {n} sig")
            return n
        return 0

    # ---- ALPHA VANTAGE (25 req/day, 5 req/min) ----
    # Strategy: fetch each symbol ONCE (compact covers all periods)

    def fetch_all_alphavantage(self, periods):
        """Fetch all AV data in one efficient pass (25/min daily limit)."""

        if not self.alpha_vantage_key:
            print("  AV: no key")
            return {'tech_stocks': 0, 'fx': 0}

        # Fetch tech stocks once (compact covers all our periods)
        tech_total = 0
        symbols = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]
        for sym in symbols:
            if not self._check_av_daily_limit():
                break
            data = self._av_request({"function": "TIME_SERIES_DAILY", "symbol": sym, "outputsize": "compact"})
            if data and "Time Series (Daily)" in data:
                records = []
                tsd = data["Time Series (Daily)"]
                for date_str, values in tsd.items():
                    # Check if it falls within any of our periods
                    for period_name, s, e in periods:
                        if s <= date_str <= e:
                            records.append({
                                "timestamp": date_str, "source": "alphavantage", "symbol": sym,
                                "open": float(values["1. open"]), "high": float(values["2. high"]),
                                "low": float(values["3. low"]), "close": float(values["4. close"]),
                                "volume": int(values["5. volume"]),
                                "adjusted_close": float(values["4. close"]),
                                "dividend_amount": 0.0, "split_coefficient": 1.0
                            })
                            break  # Match against first matching period
                if records:
                    conn = self.get_conn()
                    pd.DataFrame(records).to_sql('market_data', conn, if_exists='append', index=False)
                    conn.close()
                    tech_total += len(records)
                    print(f"  AV {sym}: {len(records)} rec")
                else:
                    print(f"  AV {sym}: 0 rec in range")
            else:
                note = ""
                if data:
                    note = data.get("Note", data.get("Information", ""))
                print(f"  AV {sym}: {'no data in range' if data else 'failed'} {note[:90]}")
            time.sleep(15)  # 15s spacing for AV rate limit

        # Fetch FX data once
        fx_total = 0
        fx_pairs = [("USD", "EUR"), ("USD", "JPY"), ("USD", "GBP")]
        for from_sym, to_sym in fx_pairs:
            if not self._check_av_daily_limit():
                break
            data = self._av_request({
                "function": "FX_DAILY", "from_symbol": from_sym, "to_symbol": to_sym, "outputsize": "compact"
            })
            if data and "Time Series FX (Daily)" in data:
                records = []
                tsd = data["Time Series FX (Daily)"]
                for date_str, values in tsd.items():
                    for period_name, s, e in periods:
                        if s <= date_str <= e:
                            records.append({
                                "timestamp": date_str, "source": "alphavantage",
                                "from_symbol": from_sym, "to_symbol": to_sym,
                                "open": float(values["1. open"]), "high": float(values["2. high"]),
                                "low": float(values["3. low"]), "close": float(values["4. close"])
                            })
                            break
                if records:
                    conn = self.get_conn()
                    pd.DataFrame(records).to_sql('fx_data', conn, if_exists='append', index=False)
                    conn.close()
                    fx_total += len(records)
                    print(f"  FX {from_sym}/{to_sym}: {len(records)} rec")
            else:
                note = ""
                if data:
                    note = data.get("Note", data.get("Information", ""))
                print(f"  FX {from_sym}/{to_sym}: {'no data' if data else 'failed'} {note[:90]}")
            time.sleep(15)

        return {'tech_stocks': tech_total, 'fx': fx_total}

    # ---- BATCH PER PERIOD ----

    def fetch_period(self, period_name, start_date, end_date):
        print(f"\n{'='*50}\n  {period_name} ({start_date} to {end_date})\n{'='*50}")
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')

        spy    = self.fetch_spy_data(start_date, end_date)
        crypto = self.fetch_crypto_data(start_date, end_date)
        news   = self.fetch_news_signals(start_dt, end_dt)

        total = spy + crypto + news
        print(f"  -> {total} rec")
        return {'period': period_name, 'spy': spy, 'crypto': crypto,
                'news': news, 'total': total}


# =============================================
# 3. MAIN
# =============================================

def backfill_database():
    periods = [
        ("May 2022",  "2022-05-01", "2022-05-31"),
        ("Sep 2022",  "2022-09-01", "2022-09-30"),
        ("Oct 2022",  "2022-10-01", "2022-10-31"),
        ("Jan 2023",  "2023-01-01", "2023-01-31"),
    ]

    fetcher = CentralizedDataFetcher()
    fetcher.setup_database()

    # Step 1: Fast data (yfinance + news) — one pass per period
    per_period = []
    for pn, s, e in periods:
        r = fetcher.fetch_period(pn, s, e)
        per_period.append(r)

    # Step 2: Alpha Vantage — one pass for ALL periods (compact covers everything)
    av_results = fetcher.fetch_all_alphavantage(periods)
    print(f"\n  AV total: {av_results['tech_stocks']} tech + {av_results['fx']} FX records")

    # Summary
    df = pd.DataFrame(per_period)
    df['tech_stocks'] = av_results['tech_stocks']
    df['fx'] = av_results['fx']

    df.to_csv('/root/backfill_summary.csv', index=False)

    print(f"\n{'='*50}")
    print("  BACKFILL COMPLETE")
    print(f"{'='*50}")
    print(df)
    print(f"\n  TOTAL records: {df['total'].sum() + av_results['tech_stocks'] + av_results['fx']}")
    print(f"  DB: /root/trading_audit.db")
    print(f"  Summary: /root/backfill_summary.csv")

    return df


if __name__ == "__main__":
    backfill_database()