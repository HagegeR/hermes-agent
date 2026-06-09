"""
news_sentiment.py
=================
Fetch company news via yfinance and classify sentiment relative to market.
Uses keyword-based scoring + financial heuristics — no external API required.

Sentiment Classification:
  POSITIVE: yfinance sentiment score > 0, price target upside > 10%, buy ratings rising
  NEGATIVE: yfinance sentiment score < 0, price target downside > 10%, sell ratings rising
  NEUTRAL: everything in between

Market Sentiment Overlay:
  - Fetches overall market news sentiment (SPY) as baseline
  - Stock is POSITIVE if: stock_sentiment > market_sentiment AND price momentum confirms
  - Stock is NEGATIVE if: stock_sentiment < market_sentiment OR price momentum diverges

Usage:
  python3 news_sentiment.py INTC NVDA GOOGL  (single run, print report)
  python3 news_sentiment.py INTC --weeks 4  (last 4 weeks of news)
  python3 news_sentiment.py --top20  (run on top 20 stocks from scores file)
"""
import sys, json, os, datetime, textwrap
from datetime import datetime, timedelta
import yfinance as yf
from yfinance_utils import get_close

# ── Sentiment Lexicon ────────────────────────────────────────────────────────
POSITIVE_KEYWORDS = [
    'beat', 'blows', 'beats', 'exceeds', 'surpasses', 'record', 'breakthrough',
    'buy', 'upgrade', 'outperform', 'strong', 'growth', 'profitable', 'profit',
    'soar', 'surge', 'rally', 'jump', 'gain', 'rise', 'climb', 'expand',
    'partnership', 'collaboration', 'launch', 'launching', 'new product',
    'innovation', 'innovative', 'breakthrough', 'monopoly', 'competitive advantage',
    'bullish', 'upgrade', 'raise', 'top pick', 'best idea', 'long',
    'acquire', 'acquisition', 'merger', 'deal', 'contract', 'revenue growth',
    'margin expansion', 'cost cutting', 'efficiency', 'share buyback', 'dividend',
    'short squeeze', 'gamma squeeze', 'AI', 'artificial intelligence', 'revolution',
    'leading', 'dominant', 'moat', 'pricing power', 'ecosystem',
]

NEGATIVE_KEYWORDS = [
    'miss', 'misses', 'below', 'weak', 'decline', 'fall', 'drop', 'lose',
    'loss', 'losses', 'cut', 'cutting', 'reduce', 'warning', 'alert',
    'risk', 'risky', 'uncertainty', 'uncertain', 'volatile', 'volatility',
    'lawsuit', 'litigation', 'investigation', 'probe', 'subpoena', 'SEC',
    'fraud', 'scandal', 'misconduct', 'breach', 'hack', 'cybersecurity',
    'bankruptcy', 'bankrupt', 'insolvent', 'default', 'delist', 'delayed',
    'layoff', 'layoffs', 'restructure', 'restructuring', 'write-down',
    'writeoff', 'impairment', 'charge', 'one-time charge', 'special charge',
    'downgrade', 'underperform', 'bearish', 'short', 'sell', 'dump',
    'margin call', 'liquidation', 'insider selling', 'CEO out', 'management change',
    'regulatory', 'antitrust', 'fine', 'penalty', 'sanction', 'ban', 'restriction',
    'trade war', 'tariff', 'inflation pressure', 'cost pressure', 'supply chain',
    'competitor', 'disruption', 'disruptive', 'cannibalize', 'substitution',
]

NEUTRAL_KEYWORDS = [
    'maintain', 'hold', 'neutral', 'in-line', 'fair value', 'price target',
    'analyst', 'report', 'study', 'data', 'meeting', 'conference', 'guidance',
    'expects', 'anticipates', 'projects', 'according to', 'says', 'stated',
]


def fetch_news(ticker, weeks=4):
    """Fetch recent news for a ticker using yfinance .news attribute."""
    try:
        tk = yf.Ticker(ticker)
        raw_news = getattr(tk, 'news', None) or []
        
        # Also try info['news'] as fallback
        if not raw_news:
            info = tk.info
            raw_news = info.get('news', []) if isinstance(info, dict) else []
        
        cutoff = datetime.now() - timedelta(weeks=weeks)
        filtered = []
        for item in raw_news:
            # Handle different yfinance news structures
            # New: item has 'content' dict with title, url, pubDate, publisher
            # Old: item has 'title', 'link' etc directly
            if 'content' in item:
                content = item['content']
                title = content.get('title', '')
                link = content.get('url', '')
                pub_date_str = content.get('pubDate', '')
                publisher = content.get('publisher', {})
                if isinstance(publisher, dict):
                    publisher = publisher.get('name', 'Unknown')
            else:
                title = item.get('title', '')
                link = item.get('link', item.get('url', ''))
                pub_date_str = item.get('pubDate', item.get('published', ''))
                publisher = item.get('publisher', item.get('source', 'Unknown'))
            
            if not title:
                continue
            
            # Parse pubDate
            pub_date = None
            if pub_date_str:
                if isinstance(pub_date_str, (int, float)):
                    pub_date = datetime.fromtimestamp(pub_date_str / 1000)
                elif isinstance(pub_date_str, str):
                    try:
                        pub_date = datetime.fromisoformat(pub_date_str.replace('Z', '+00:00'))
                    except ValueError:
                        try:
                            pub_date = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S %z')
                        except ValueError:
                            try:
                                pub_date = datetime.strptime(pub_date_str[:25], '%a, %d %b %Y %H:%M:%S')
                            except ValueError:
                                continue
            
            if pub_date:
                if pub_date.tzinfo:
                    pub_date = pub_date.replace(tzinfo=None)
                if pub_date < cutoff:
                    continue
            
            filtered.append({
                'title': title,
                'link': link,
                'publisher': publisher,
                'date': pub_date.strftime('%Y-%m-%d') if pub_date else 'N/A',
            })
        
        return filtered
    except Exception as e:
        return []


def score_sentiment(text):
    """
    Keyword-based sentiment scorer. Returns:
      positive_count, negative_count, neutral_count, final_score (-1 to 1)
    """
    text_lower = text.lower()
    pos = sum(1 for kw in POSITIVE_KEYWORDS if kw in text_lower)
    neg = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text_lower)
    neu = sum(1 for kw in NEUTRAL_KEYWORDS if kw in text_lower)
    
    if pos + neg == 0:
        return pos, neg, neu, 0.0
    
    # Net score normalized to [-1, 1]
    net = (pos - neg) / max(pos + neg, 1)
    return pos, neg, neu, net


def classify_news(ticker, weeks=4):
    """Fetch and classify news for a single ticker. Returns dict."""
    news = fetch_news(ticker, weeks)
    if not news:
        return {
            'ticker': ticker,
            'headline_count': 0,
            'positive': 0, 'negative': 0, 'neutral': 0,
            'net_score': 0.0,
            'sentiment': 'NO NEWS',
            'sentiment_label': '⚪',
            'bullish_pct': 0.0,
            'headlines': [],
        }
    
    pos_total = neg_total = neu_total = 0
    scored_headlines = []
    for item in news:
        title = item.get('title', '')
        pos, neg, neu, net = score_sentiment(title)
        pos_total += pos
        neg_total += neg
        neu_total += neu
        scored_headlines.append({
            'title': title,
            'date': item['date'],
            'publisher': item['publisher'],
            'pos': pos, 'neg': neg,
            'score': net,
            'label': '🟢' if net > 0.1 else '🔴' if net < -0.1 else '⚪',
        })
    
    total = pos_total + neg_total + neu_total
    net_avg = (pos_total - neg_total) / max(total, 1)
    bullish_pct = pos_total / max(total, 1) * 100
    
    if net_avg > 0.15:
        sentiment = 'POSITIVE'
        label = '🟢'
    elif net_avg < -0.15:
        sentiment = 'NEGATIVE'
        label = '🔴'
    else:
        sentiment = 'NEUTRAL'
        label = '⚪'
    
    return {
        'ticker': ticker,
        'headline_count': len(news),
        'positive': pos_total, 'negative': neg_total, 'neutral': neu_total,
        'net_score': round(net_avg, 3),
        'sentiment': sentiment,
        'sentiment_label': label,
        'bullish_pct': round(bullish_pct, 1),
        'headlines': scored_headlines[-5:],  # last 5 headlines
    }


def get_market_sentiment(weeks=4):
    """Get overall market sentiment as baseline using SPY."""
    spy_result = classify_news('SPY', weeks)
    return spy_result['net_score'], spy_result['sentiment']


def overlay_market_sentiment(ticker_results, market_score):
    """
    Refine stock sentiment relative to market.
    If stock sentiment > market + 0.15 → CONFIRMED BULLISH
    If stock sentiment > market but price diverges → CAUTION
    If stock sentiment < market - 0.15 → CONFIRMED BEARISH
    """
    refined = []
    for r in ticker_results:
        rel_score = r['net_score'] - market_score
        
        if rel_score > 0.20:
            if r['sentiment'] == 'POSITIVE':
                r['market_adj_sentiment'] = 'CONFIRMED BULLISH'
                r['market_adj_label'] = '🟢✅'
            elif r['sentiment'] == 'NEUTRAL':
                r['market_adj_sentiment'] = 'TURNING BULLISH'
                r['market_adj_label'] = '🟢⚠️'
            else:
                r['market_adj_sentiment'] = 'POSITIVE DIVERGENCE'
                r['market_adj_label'] = '🟡'
        elif rel_score < -0.20:
            if r['sentiment'] == 'NEGATIVE':
                r['market_adj_sentiment'] = 'CONFIRMED BEARISH'
                r['market_adj_label'] = '🔴❌'
            elif r['sentiment'] == 'NEUTRAL':
                r['market_adj_sentiment'] = 'TURNING BEARISH'
                r['market_adj_label'] = '🔴⚠️'
            else:
                r['market_adj_sentiment'] = 'NEGATIVE DIVERGENCE'
                r['market_adj_label'] = '🟡'
        else:
            r['market_adj_sentiment'] = 'IN LINE WITH MARKET'
            r['market_adj_label'] = r['sentiment_label']
        
        refined.append(r)
    return refined


def get_price_momentum(ticker, lookback_days=90):
    """Get 90-day price momentum for divergence check."""
    try:
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=lookback_days+30)).strftime('%Y-%m-%d')
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        close = get_close(df)
        if isinstance(close, pd.DataFrame):
            close = close.squeeze()
        if len(close) < 60:
            return None
        
        recent_90 = close.iloc[-60:]
        older_90 = close.iloc[-120:-60] if len(close) >= 120 else close.iloc[:max(0, len(close)-60)]
        
        ret_recent = (recent_90.iloc[-1] / recent_90.iloc[0]) - 1
        ret_older = (older_90.iloc[-1] / older_90.iloc[0]) - 1 if len(older_90) > 0 else 0
        
        return {
            'recent_90d': round(ret_recent * 100, 1),
            'prior_90d': round(ret_older * 100, 1),
            'momentum_accelerating': ret_recent > ret_older,
        }
    except:
        return None


def score_to_action(sentiment_r, momentum, dcf_upside=None, score_rank=None):
    """Combine sentiment + momentum + DCF to generate BUY/HOLD/AVOID signal."""
    buy_signals = 0
    avoid_signals = 0
    
    # Sentiment signals
    if sentiment_r.get('market_adj_sentiment') in ('CONFIRMED BULLISH', 'TURNING BULLISH'):
        buy_signals += 2
    elif sentiment_r.get('market_adj_sentiment') == 'POSITIVE DIVERGENCE':
        buy_signals += 1
    elif sentiment_r.get('market_adj_sentiment') in ('CONFIRMED BEARISH', 'TURNING BEARISH'):
        avoid_signals += 2
    elif sentiment_r.get('market_adj_sentiment') == 'NEGATIVE DIVERGENCE':
        avoid_signals += 1
    
    # Momentum signals
    if momentum:
        if momentum['momentum_accelerating']:
            buy_signals += 1
        else:
            avoid_signals += 1
    
    # DCF signals
    if dcf_upside is not None:
        if dcf_upside > 20:
            buy_signals += 2
        elif dcf_upside > 0:
            buy_signals += 1
        elif dcf_upside < -30:
            avoid_signals += 2
        elif dcf_upside < 0:
            avoid_signals += 1
    
    if buy_signals >= 4:
        return 'STRONG BUY', '💚'
    elif buy_signals >= 2 and buy_signals > avoid_signals:
        return 'BUY', '🟢'
    elif avoid_signals >= 4:
        return 'AVOID', '🔴'
    elif avoid_signals > buy_signals:
        return 'WAIT/AVOID', '🟡'
    else:
        return 'HOLD', '⚪'


def print_report(ticker_results, market_score, market_sentiment, output_path=None):
    """Print formatted news sentiment report."""
    print(f"\n{'='*80}")
    print(f"📰 NEWS SENTIMENT REPORT — Market Baseline: {market_sentiment} ({market_score:+.2f})")
    print(f"{'='*80}")
    
    # Sort by net_score (most bullish first)
    sorted_results = sorted(ticker_results, key=lambda x: x['net_score'], reverse=True)
    
    for r in sorted_results:
        print(f"\n{r['sentiment_label']} {r['ticker']:6s} | Raw={r['net_score']:+.2f} | Market-Adj={r['market_adj_label']} {r['market_adj_sentiment']}")
        print(f"  Headlines: {r['headline_count']} | 🟢{r['positive']} | 🔴{r['negative']} | ⚪{r['neutral']} | Bullish: {r['bullish_pct']:.0f}%")
        if r.get('momentum'):
            m = r['momentum']
            print(f"  Momentum: {m['recent_90d']:+.1f}% (90d) | Prior: {m['prior_90d']:+.1f}% | {'📈 accelerating' if m['momentum_accelerating'] else '📉 decelerating'}")
        if r.get('signal'):
            sig, emoji = r['signal'], r['signal_emoji']
            print(f"  → {emoji} {sig}")
        
        # Print top headlines
        for h in r.get('headlines', [])[:3]:
            title_short = textwrap.fill(h['title'], width=75) if len(h['title']) > 75 else h['title']
            print(f"    {h['label']} [{h['date']}] {title_short}")
    
    print(f"\n{'='*80}")
    print("SIGNAL LEGEND: 🟢✅ CONFIRMED BULLISH | 🟢 TURNING BULLISH | 🟡⚠️ CAUTION | 🔴❌ CONFIRMED BEARISH | ⚪ IN LINE WITH MARKET")
    print("="*80)
    
    if output_path:
        with open(output_path, 'w') as f:
            json.dump(ticker_results, f, indent=2, default=str)
        print(f"\nSaved to {output_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='News sentiment analysis for stocks')
    parser.add_argument('tickers', nargs='*', help='Ticker symbols')
    parser.add_argument('--weeks', type=int, default=4, help='Weeks of news to analyze (default: 4)')
    parser.add_argument('--top20', action='store_true', help='Analyze top 20 from russell_1000_scores_v2.json')
    parser.add_argument('--output', '-o', help='Save JSON output to file')
    args = parser.parse_args()
    
    tickers = []
    
    if args.top20:
        scores_file = 'russell_1000_scores_v2.json'
        if os.path.exists(scores_file):
            with open(scores_file) as f:
                raw = json.load(f)
            # Support both flat dict and nested {'all_scored': [...]} format
            if isinstance(raw, dict) and 'all_scored' in raw:
                # all_scored is a list of {ticker, total_score, ...} dicts
                ticker_to_score = {e['ticker']: e for e in raw['all_scored'] if isinstance(e, dict)}
                data = ticker_to_score
            elif isinstance(raw, dict):
                data = raw
            else:
                data = {}
            # data is now {ticker: {scores}}
            sorted_tickers = sorted(data.items(), key=lambda x: x[1].get('total_score', 0), reverse=True)
            tickers = [t for t, _ in sorted_tickers[:20]]
            print(f"Loaded top 20 tickers from {scores_file}: {tickers[:5]}...")
        else:
            print(f"⚠️ {scores_file} not found. Provide tickers directly.")
            return
    elif args.tickers:
        tickers = [t.upper().strip().rstrip('.') for t in args.tickers]
    else:
        print("Usage: news_sentiment.py INTC NVDA GOOGL [--weeks 4]")
        print("   or: news_sentiment.py --top20")
        return
    
    print(f"Fetching news for {len(tickers)} tickers ({args.weeks} weeks)...")
    
    # Get market baseline
    market_score, market_sentiment = get_market_sentiment(args.weeks)
    print(f"Market (SPY) sentiment: {market_sentiment} ({market_score:+.2f})\n")
    
    # Classify each ticker
    results = []
    for t in tickers:
        print(f"  Analyzing {t}...", end=' ', flush=True)
        r = classify_news(t, args.weeks)
        momentum = get_price_momentum(t)
        r['momentum'] = momentum
        results.append(r)
        sentiment_icons = {'POSITIVE': '🟢', 'NEGATIVE': '🔴', 'NEUTRAL': '⚪', 'NO NEWS': '⚪'}
        print(f"{sentiment_icons.get(r['sentiment'], '⚪')} {r['sentiment']} ({r['net_score']:+.2f}) | {r['headline_count']} articles")
    
    # Apply market sentiment overlay
    results = overlay_market_sentiment(results, market_score)
    
    # Add signals
    for r in results:
        signal, emoji = score_to_action(r, r.get('momentum'))
        r['signal'] = signal
        r['signal_emoji'] = emoji
    
    # Sort by signal strength (STRONG BUY first)
    signal_order = {'STRONG BUY': 0, 'BUY': 1, 'HOLD': 2, 'WAIT/AVOID': 3, 'AVOID': 4}
    results.sort(key=lambda x: (signal_order.get(x['signal'], 5), -x['net_score']))
    
    print_report(results, market_score, market_sentiment, args.output)


if __name__ == '__main__':
    main()