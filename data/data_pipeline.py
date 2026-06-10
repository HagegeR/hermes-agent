#!/usr/bin/env python3
"""
Weekly data refresh pipeline.
Fetches current data from all available sources and stores in SQLite.
Handles rate limits gracefully with retries on next run.
"""

import os, sqlite3, time, yfinance as yf, pandas as pd, requests
from datetime import datetime, timedelta
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler('/root/data_pipeline.log'),
        logging.StreamHandler()
    ]
)

class DataPipeline:
    def __init__(self, db_path='/root/trading_audit.db'):
        self.db_path = db_path
        self.news_api_key = "ee7c65f08e7d4d68905b402e167a8612"
        self.av_key = "LLTZRLOWUVAUMSDU"
        self.today = datetime.now()
        self.start_30d = (self.today - timedelta(days=30)).strftime('%Y-%m-%d')
        self.end_today = self.today.strftime('%Y-%m-%d')

    def get_conn(self):
        return sqlite3.connect(self.db_path)

    def fetch_yfinance(self):
        """Fetch SPY + crypto + tech stocks + FX data"""
        logging.info("=== YFINANCE (all markets) ===")
        conn = self.get_conn()
        total = 0

        # SPY
        data = yf.download('SPY', start=self.start_30d, end=self.end_today)
        if not data.empty:
            data = data.reset_index()
            data['source'] = 'yfinance'
            data['symbol'] = 'SPY'
            data['signal_type'] = 'benchmark'
            data['timestamp'] = data['Date'].astype(str)
            cols = ['timestamp', 'source', 'symbol', 'Close', 'Volume', 'signal_type']
            data = data[cols]
            data.columns = ['timestamp', 'source', 'symbol', 'price', 'volume', 'signal_type']
            data.to_sql('market_data', conn, if_exists='append', index=False)
            logging.info(f"  SPY: {len(data)} records")
            total += len(data)

        # BTC + ETH
        for sym in ["BTC-USD", "ETH-USD"]:
            data = yf.download(sym, start=self.start_30d, end=self.end_today)
            if not data.empty:
                data = data.reset_index()
                data['source'] = 'yfinance'
                data['symbol'] = sym
                data['signal_type'] = 'crypto_momentum'
                data['timestamp'] = data['Date'].astype(str)
                data['signal_strength'] = data['Close'].pct_change().rolling(3).mean().fillna(0)
                cols = ['timestamp', 'source', 'symbol', 'Close', 'Volume', 'signal_type', 'signal_strength']
                data = data[cols]
                data.columns = ['timestamp', 'source', 'symbol', 'price', 'volume',
                               'signal_type', 'signal_strength']
                data.to_sql('market_data', conn, if_exists='append', index=False)
                logging.info(f"  {sym}: {len(data)} records")
                total += len(data)

        # Tech stocks
        for sym in ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]:
            data = yf.download(sym, start=self.start_30d, end=self.end_today)
            if not data.empty:
                data = data.reset_index()
                data['source'] = 'yfinance'
                data['symbol'] = sym
                data['signal_type'] = 'benchmark'
                data['timestamp'] = data['Date'].astype(str)
                cols = ['timestamp', 'source', 'symbol', 'Close', 'Volume', 'signal_type']
                data = data[cols]
                data.columns = ['timestamp', 'source', 'symbol', 'price', 'volume', 'signal_type']
                data.to_sql('market_data', conn, if_exists='append', index=False)
                logging.info(f"  {sym}: {len(data)} records")
                total += len(data)

        # FX via Yahoo Finance
        fx_map = {"EUR/USD": "EURUSD=X", "USD/JPY": "JPY=X", "GBP/USD": "GBPUSD=X"}
        for pair_name, ticker in fx_map.items():
            data = yf.download(ticker, start=self.start_30d, end=self.end_today)
            if not data.empty:
                from_sym, to_sym = pair_name.split('/')
                data = data.reset_index()
                data['source'] = 'yfinance'
                data['from_symbol'] = from_sym
                data['to_symbol'] = to_sym
                data['timestamp'] = data['Date'].astype(str)
                cols = ['timestamp', 'source', 'from_symbol', 'to_symbol', 'Open', 'High', 'Low', 'Close']
                data = data[cols]
                data.columns = ['timestamp', 'source', 'from_symbol', 'to_symbol', 'open', 'high', 'low', 'close']
                data.to_sql('fx_data', conn, if_exists='append', index=False)
                logging.info(f"  {pair_name}: {len(data)} records")
                total += len(data)

        conn.close()
        return total

    def fetch_news(self):
        """Fetch recent news. Returns count or 0 if rate limited."""
        logging.info("=== NEWSAPI ===")
        conn = self.get_conn()
        queries = [
            "S&P 500 OR SPY OR stock market",
            "technology stocks OR tech sector",
            "Federal Reserve OR Fed interest rates",
            "inflation OR CPI OR economic data",
            "earnings OR quarterly results",
            "recession OR GDP OR economic growth"
        ]

        all_articles = []
        for query in queries:
            params = {
                "q": query,
                "from_param": self.start_30d,
                "to": self.end_today,
                "sortBy": "relevancy",
                "language": "en",
                "pageSize": 100,
                "apiKey": self.news_api_key
            }
            try:
                r = requests.get("https://newsapi.org/v2/everything", params=params, timeout=15)
                if r.status_code == 200:
                    for art in r.json().get("articles", []):
                        try:
                            pub = datetime.strptime(art["publishedAt"], "%Y-%m-%dT%H:%M:%SZ")
                            text = art["title"] + " " + (art.get("description", ""))
                            pos_words = ["up","rally","gain","bullish","growth","record","surge","jump"]
                            neg_words = ["down","drop","loss","bearish","decline","crash","recession","slump"]
                            sentiment = "positive" if any(w in text.lower() for w in pos_words) else \
                                        "negative" if any(w in text.lower() for w in neg_words) else "neutral"
                            all_articles.append({
                                "timestamp": pub, "source": "newsapi",
                                "headline": art["title"], "url": art["url"],
                                "sentiment": sentiment, "relevance": 0.8
                            })
                        except:
                            pass
                elif r.status_code == 429:
                    logging.warning(f"  NewsAPI rate limited (429)")
                    break
                else:
                    logging.warning(f"  NewsAPI HTTP {r.status_code}")
            except Exception as e:
                logging.warning(f"  NewsAPI error: {e}")

        # Dedup by URL
        seen = set()
        unique = [a for a in all_articles if not (a["url"] in seen or seen.add(a["url"]))]

        if unique:
            pd.DataFrame(unique).to_sql('news_signals', conn, if_exists='append', index=False)
            logging.info(f"  Stored {len(unique)} articles")
            conn.close()
            return len(unique)
        logging.info(f"  No articles")
        conn.close()
        return 0

    def fetch_alphavantage(self):
        """Fetch Alpha Vantage data. Returns True if successful, False if rate limited."""
        logging.info("=== ALPHA VANTAGE ===")
        av_key_status = requests.get("https://www.alphavantage.co/query", params={
            "function": "TIME_SERIES_DAILY", "symbol": "AAPL", "outputsize": "compact", "apikey": self.av_key
        }, timeout=15).json()

        if "Time Series (Daily)" not in av_key_status:
            note = av_key_status.get("Note", av_key_status.get("Information", "unknown"))
            logging.warning(f"  Daily limit still active: {note[:80]}")
            return False

        logging.info("  Daily limit reset! Fetching data...")
        conn = self.get_conn()

        # Tech stocks (5 symbols × 1 call each = 5 calls)
        for sym in ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]:
            data = requests.get("https://www.alphavantage.co/query", params={
                "function": "TIME_SERIES_DAILY", "symbol": sym,
                "outputsize": "compact", "apikey": self.av_key
            }, timeout=15).json()

            if "Time Series (Daily)" in data:
                records = []
                for date_str, vals in data["Time Series (Daily)"].items():
                    records.append({
                        "timestamp": date_str, "source": "alphavantage", "symbol": sym,
                        "open": float(vals["1. open"]), "high": float(vals["2. high"]),
                        "low": float(vals["3. low"]), "close": float(vals["4. close"]),
                        "volume": int(vals["5. volume"]),
                        "adjusted_close": float(vals["4. close"]),
                        "dividend_amount": 0.0, "split_coefficient": 1.0
                    })
                pd.DataFrame(records).to_sql('market_data', conn, if_exists='append', index=False)
                logging.info(f"  {sym}: {len(records)} records")
            time.sleep(15)  # Respect 5 req/min limit

        # FX pairs (3 calls)
        for frm, to in [("USD","EUR"), ("USD","JPY"), ("USD","GBP")]:
            data = requests.get("https://www.alphavantage.co/query", params={
                "function": "FX_DAILY", "from_symbol": frm, "to_symbol": to,
                "outputsize": "compact", "apikey": self.av_key
            }, timeout=15).json()

            if "Time Series FX (Daily)" in data:
                records = []
                for date_str, vals in data["Time Series FX (Daily)"].items():
                    records.append({
                        "timestamp": date_str, "source": "alphavantage",
                        "from_symbol": frm, "to_symbol": to,
                        "open": float(vals["1. open"]), "high": float(vals["2. high"]),
                        "low": float(vals["3. low"]), "close": float(vals["4. close"])
                    })
                pd.DataFrame(records).to_sql('fx_data', conn, if_exists='append', index=False)
                logging.info(f"  FX {frm}/{to}: {len(records)} records")
            time.sleep(15)

        conn.close()
        return True

    def summary(self):
        """Print database summary"""
        conn = self.get_conn()
        logging.info("=== DATABASE SUMMARY ===")
        for table in ['market_data', 'news_signals', 'fx_data', 'sector_performance']:
            try:
                cnt = pd.read_sql(f"SELECT COUNT(*) as c FROM {table}", conn)['c'].iloc[0]
                dates = pd.read_sql(f"SELECT MIN(timestamp) as first, MAX(timestamp) as last FROM {table} WHERE timestamp IS NOT NULL AND timestamp != ''", conn)
                first = str(dates['first'].iloc[0]) if dates['first'].iloc[0] else 'N/A'
                last = str(dates['last'].iloc[0]) if dates['last'].iloc[0] else 'N/A'
                logging.info(f"  {table}: {cnt:,} rows ({first} → {last})")
            except Exception as e:
                logging.info(f"  {table}: ERROR - {e}")
        conn.close()

    def run(self):
        """Run the full pipeline"""
        logging.info(f"\n{'='*60}")
        logging.info(f"  DATA PIPELINE RUN: {self.today.isoformat()}")
        logging.info(f"  Range: {self.start_30d} → {self.end_today}")
        logging.info(f"{'='*60}")

        # 1. yfinance (always works, covers everything)
        yf_count = self.fetch_yfinance()
        logging.info(f"  yfinance: {yf_count} records")

        # 2. NewsAPI (may be rate limited)
        try:
            news_count = self.fetch_news()
        except Exception as e:
            logging.warning(f"  NewsAPI failed: {e}")
            news_count = -1

        # 3. Alpha Vantage (bonus - only if limit has reset)
        try:
            av_success = self.fetch_alphavantage()
        except Exception as e:
            logging.warning(f"  Alpha Vantage failed: {e}")
            av_success = False

        # 4. Summary
        self.summary()

        logging.info(f"\n{'='*60}")
        logging.info(f"  PIPELINE COMPLETE")
        logging.info(f"  yfinance: {yf_count} | News: {news_count} | AV: {'✅' if av_success else '⏳ skipped'}")
        logging.info(f"{'='*60}")

        return {
            'yfinance': yf_count,
            'news': news_count,
            'av_success': av_success
        }


if __name__ == "__main__":
    pipeline = DataPipeline()
    pipeline.run()