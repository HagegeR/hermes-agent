"""
Russell 1000 Stock Scorer
Downloads financials, analyst data, and news for all Russell 1000 stocks,
then scores and ranks them.
"""
import yfinance as yf
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import json
import sys

# Load tickers
with open('russell_1000_tickers.txt') as f:
    tickers = [line.strip() for line in f if line.strip()]

print(f"Loaded {len(tickers)} tickers")

def fetch_ticker_data(ticker):
    """Fetch all data for a single ticker."""
    try:
        t = yf.Ticker(ticker)
        
        # Get info (contains most metrics)
        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass
        
        # Get financials
        financials = {}
        try:
            inc = t.income_stmt
            if inc is not None and not inc.empty:
                financials['revenue'] = inc.loc['Total Revenue'].iloc[0] if 'Total Revenue' in inc.index else None
                financials['net_income'] = inc.loc['Net Income'].iloc[0] if 'Net Income' in inc.index else None
                financials['gross_margin'] = (inc.loc['Gross Profit'].iloc[0] / inc.loc['Total Revenue'].iloc[0]) if 'Gross Profit' in inc.index and 'Total Revenue' in inc.index and inc.loc['Total Revenue'].iloc[0] else None
                # YoY revenue growth
                if len(inc.loc['Total Revenue']) >= 2:
                    r0 = inc.loc['Total Revenue'].iloc[0]
                    r1 = inc.loc['Total Revenue'].iloc[1]
                    if r1 and r1 != 0:
                        financials['revenue_growth'] = (r0 - r1) / abs(r1)
                    else:
                        financials['revenue_growth'] = None
                else:
                    financials['revenue_growth'] = None
        except Exception:
            financials = {}
        
        # Get analyst recommendations
        analyst = {}
        try:
            rec = t.recommendations
            if rec is not None and not rec.empty:
                analyst['strong_buy'] = int((rec['Grade'] == 'Strong Buy').sum()) if 'Grade' in rec.columns else 0
                analyst['buy'] = int((rec['Grade'] == 'Buy').sum()) if 'Grade' in rec.columns else 0
                analyst['hold'] = int((rec['Grade'] == 'Hold').sum()) if 'Grade' in rec.columns else 0
                analyst['sell'] = int((rec['Grade'] == 'Sell').sum()) if 'Grade' in rec.columns else 0
                analyst['strong_sell'] = int((rec['Grade'] == 'Strong Sell').sum()) if 'Grade' in rec.columns else 0
        except Exception:
            analyst = {}
        
        # Get target price
        target = {}
        try:
            targets = t.analyst_price_targets
            if targets is not None and not targets.empty:
                target['current_price'] = targets.iloc[0].get('Current', None) if len(targets) > 0 else None
                target['mean_target'] = targets.iloc[0].get('TargetMean', None) if len(targets) > 0 else None
                target['high_target'] = targets.iloc[0].get('TargetHigh', None) if len(targets) > 0 else None
                target['low_target'] = targets.iloc[0].get('TargetLow', None) if len(targets) > 0 else None
        except Exception:
            target = {}
        
        # Get news count (recent news)
        news_count = 0
        try:
            news = t.news
            if news:
                # Count news from last 30 days
                import datetime
                cutoff = datetime.datetime.now() - datetime.timedelta(days=30)
                news_count = len(news)
        except Exception:
            pass
        
        return {
            'ticker': ticker,
            'info': info,
            'financials': financials,
            'analyst': analyst,
            'target': target,
            'news_count': news_count,
            'success': True
        }
    except Exception as e:
        return {'ticker': ticker, 'success': False, 'error': str(e)}

def score_stock(data):
    """Score a single stock based on various metrics."""
    if not data.get('success'):
        return None
    
    info = data.get('info', {})
    financials = data.get('financials', {})
    analyst = data.get('analyst', {})
    target = data.get('target', {})
    
    score = 0
    score_details = {}
    
    # ---- Valuation Score (0-25 pts) ----
    val_score = 0
    pe_ratio = info.get('trailingPE') or info.get('forwardPE')
    if pe_ratio and pe_ratio > 0 and pe_ratio < 100:
        # Lower PE is better (value), but we cap at 100
        if pe_ratio < 10:
            val_score += 25
        elif pe_ratio < 15:
            val_score += 20
        elif pe_ratio < 20:
            val_score += 15
        elif pe_ratio < 25:
            val_score += 10
        elif pe_ratio < 35:
            val_score += 5
    elif pe_ratio is None or pe_ratio == 0:
        val_score += 10  # No PE available, partial credit
    score += val_score
    score_details['valuation'] = val_score
    
    # ---- Growth Score (0-25 pts) ----
    growth_score = 0
    
    # Revenue growth
    rev_growth = financials.get('revenue_growth')
    if rev_growth is not None:
        if rev_growth > 0.3:
            growth_score += 12
        elif rev_growth > 0.2:
            growth_score += 10
        elif rev_growth > 0.1:
            growth_score += 7
        elif rev_growth > 0:
            growth_score += 4
    
    # Forward PE vs trailing PE (growth indicator)
    trailing_pe = info.get('trailingPE')
    forward_pe = info.get('forwardPE')
    if trailing_pe and forward_pe and forward_pe > 0:
        peg_implied = (trailing_pe / forward_pe - 1) * 100
        # If forward PE < trailing PE, indicates expected growth
        if peg_implied > 20:
            growth_score += 8
        elif peg_implied > 10:
            growth_score += 5
        elif peg_implied > 0:
            growth_score += 3
    
    # EPS growth (from info)
    eps_growth = info.get('earningsGrowth') or info.get('revenueGrowth')
    if eps_growth and isinstance(eps_growth, (int, float)):
        if eps_growth > 0.3:
            growth_score += 5
        elif eps_growth > 0.15:
            growth_score += 3
        elif eps_growth > 0:
            growth_score += 1
    
    score += growth_score
    score_details['growth'] = growth_score
    
    # ---- Profitability Score (0-20 pts) ----
    profit_score = 0
    
    gross_margin = financials.get('gross_margin')
    if gross_margin is not None:
        if gross_margin > 0.5:
            profit_score += 8
        elif gross_margin > 0.35:
            profit_score += 5
        elif gross_margin > 0.2:
            profit_score += 3
    
    # Profit margins from info
    op_margin = info.get('operatingMargins') or info.get('profitMargins')
    if op_margin and isinstance(op_margin, (int, float)):
        if op_margin > 0.3:
            profit_score += 7
        elif op_margin > 0.2:
            profit_score += 5
        elif op_margin > 0.1:
            profit_score += 3
        elif op_margin > 0:
            profit_score += 1
    
    # ROE
    roe = info.get('returnOnEquity')
    if roe and isinstance(roe, (int, float)):
        if roe > 0.25:
            profit_score += 5
        elif roe > 0.15:
            profit_score += 3
        elif roe > 0.05:
            profit_score += 1
    
    score += profit_score
    score_details['profitability'] = profit_score
    
    # ---- Analyst Sentiment Score (0-20 pts) ----
    analyst_score = 0
    
    # Buy ratings ratio
    strong_buy = analyst.get('strong_buy', 0)
    buy = analyst.get('buy', 0)
    hold = analyst.get('hold', 0)
    sell = analyst.get('sell', 0)
    strong_sell = analyst.get('strong_sell', 0)
    total_recs = strong_buy + buy + hold + sell + strong_sell
    
    if total_recs > 0:
        buy_ratio = (strong_buy + buy) / total_recs
        if buy_ratio >= 0.7:
            analyst_score += 10
        elif buy_ratio >= 0.5:
            analyst_score += 7
        elif buy_ratio >= 0.3:
            analyst_score += 4
        
        # Sell ratio penalty
        sell_ratio = (sell + strong_sell) / total_recs
        if sell_ratio > 0.3:
            analyst_score -= 5
        elif sell_ratio > 0.15:
            analyst_score -= 2
    
    # Upside from target price
    current_price = target.get('current_price') or info.get('currentPrice') or info.get('regularMarketPrice')
    mean_target = target.get('mean_target')
    if current_price and mean_target and mean_target > 0:
        upside = (mean_target - current_price) / current_price
        if upside > 0.3:
            analyst_score += 8
        elif upside > 0.2:
            analyst_score += 6
        elif upside > 0.1:
            analyst_score += 4
        elif upside > 0:
            analyst_score += 2
        else:
            analyst_score -= 3  # No upside
    else:
        analyst_score += 3  # Partial credit for having analyst data
    
    score += analyst_score
    score_details['analyst'] = analyst_score
    
    # ---- Momentum / Price Action (0-10 pts) ----
    momentum_score = 0
    
    # 52-week performance
    week52_change = info.get('52WeekChange') or info.get('52WeekPriceReturn')
    if week52_change and isinstance(week52_change, (int, float)):
        if week52_change > 0.3:
            momentum_score += 5
        elif week52_change > 0.15:
            momentum_score += 3
        elif week52_change > 0:
            momentum_score += 1
        elif week52_change < -0.2:
            momentum_score -= 3  # Strong penalty for being in downtrend
    
    # Recent price strength (vs 50-day)
    sma50 = info.get('fiftyDayAverage')
    current = info.get('currentPrice') or info.get('regularMarketPrice')
    if sma50 and current and sma50 > 0:
        price_vs_sma50 = (current - sma50) / sma50
        if price_vs_sma50 > 0.1:
            momentum_score += 3
        elif price_vs_sma50 > 0:
            momentum_score += 1
        elif price_vs_sma50 < -0.1:
            momentum_score -= 2
    
    # Beta (lower is safer, but not negative for scoring)
    beta = info.get('beta')
    if beta and isinstance(beta, (int, float)):
        if beta < 1.0:  # Lower volatility
            momentum_score += 2
    
    score += momentum_score
    score_details['momentum'] = momentum_score
    
    # ---- Market Confidence (0-5 pts) ----
    confidence_score = 0
    
    # Market cap (larger = more liquid/stable)
    market_cap = info.get('marketCap')
    if market_cap:
        if market_cap > 100e9:  # > 100B
            confidence_score += 2
        elif market_cap > 10e9:  # > 10B
            confidence_score += 1
    
    # News count (some activity is good)
    if data.get('news_count', 0) > 0:
        confidence_score += 1
    
    # Institutional ownership
    if info.get('heldByInstitutionsPercentage') or info.get('floatShares'):
        inst_pct = info.get('heldByInstitutionsPercentage')
        if inst_pct and inst_pct > 0.5:
            confidence_score += 2
        elif inst_pct and inst_pct > 0.2:
            confidence_score += 1
    
    score += confidence_score
    score_details['confidence'] = confidence_score
    
    return {
        'ticker': data['ticker'],
        'company_name': info.get('shortName') or info.get('longName') or data['ticker'],
        'sector': info.get('sector') or 'Unknown',
        'industry': info.get('industry') or 'Unknown',
        'total_score': round(score, 1),
        'score_breakdown': score_details,
        'pe_ratio': info.get('trailingPE'),
        'forward_pe': info.get('forwardPE'),
        'revenue_growth': financials.get('revenue_growth'),
        'gross_margin': financials.get('gross_margin'),
        'profit_margin': info.get('profitMargins'),
        'roe': info.get('returnOnEquity'),
        'market_cap': info.get('marketCap'),
        'analyst_buy_ratio': (strong_buy + buy) / total_recs if total_recs > 0 else None,
        'total_recs': total_recs,
        'upside_to_target': ((mean_target - current_price) / current_price) if (current_price and mean_target and current_price > 0) else None,
        'current_price': current_price,
        'mean_target': mean_target,
        'week52_change': info.get('52WeekChange'),
        'beta': info.get('beta'),
        'inst_pct': info.get('heldByInstitutionsPercentage'),
    }

# Process in parallel batches
print("Fetching data for all stocks...")
all_data = []
batch_size = 50
total_batches = (len(tickers) + batch_size - 1) // batch_size

with ThreadPoolExecutor(max_workers=20) as executor:
    futures = {executor.submit(fetch_ticker_data, t): t for t in tickers}
    completed = 0
    for future in as_completed(futures):
        result = future.result()
        all_data.append(result)
        completed += 1
        if completed % 100 == 0:
            print(f"  Processed {completed}/{len(tickers)} stocks...")

print(f"Fetched data for {sum(1 for d in all_data if d.get('success'))} stocks successfully")

# Score all stocks
print("Scoring all stocks...")
scored = []
for data in all_data:
    scored_stock = score_stock(data)
    if scored_stock:
        scored.append(scored_stock)

# Sort by total score descending
scored.sort(key=lambda x: x['total_score'], reverse=True)

# Print top 50
print("\n" + "="*80)
print("TOP 50 RUSSELL 1000 STOCKS BY COMPOSITE SCORE")
print("="*80)

for i, stock in enumerate(scored[:50], 1):
    print(f"\n#{i}: {stock['ticker']} — {stock['company_name']}")
    print(f"   Score: {stock['total_score']:.1f}/100")
    print(f"   Sector: {stock['sector']} | Industry: {stock['industry']}")
    
    bd = stock['score_breakdown']
    print(f"   Breakdown: Val={bd['valuation']:.0f}/25 | Growth={bd['growth']:.0f}/25 | Profit={bd['profitability']:.0f}/20 | Analyst={bd['analyst']:.0f}/20 | Momentum={bd['momentum']:.0f}/10 | Confidence={bd['confidence']:.0f}/5")
    
    # Key metrics
    metrics = []
    if stock['pe_ratio']:
        metrics.append(f"PE={stock['pe_ratio']:.1f}")
    if stock['revenue_growth'] is not None:
        metrics.append(f"Rev Growth={stock['revenue_growth']*100:.1f}%")
    if stock['gross_margin'] is not None:
        metrics.append(f"Gross Margin={stock['gross_margin']*100:.1f}%")
    if stock['analyst_buy_ratio'] is not None:
        metrics.append(f"Buy Ratio={stock['analyst_buy_ratio']*100:.1f}%")
    if stock['upside_to_target'] is not None:
        metrics.append(f"Upside={stock['upside_to_target']*100:.1f}%")
    if stock['current_price']:
        metrics.append(f"Price=${stock['current_price']:.2f}")
    if stock['market_cap']:
        mc = stock['market_cap']
        if mc >= 1e12:
            metrics.append(f"Mkt Cap=${mc/1e12:.1f}T")
        elif mc >= 1e9:
            metrics.append(f"Mkt Cap=${mc/1e9:.0f}B")
    
    print(f"   Key Metrics: {' | '.join(metrics)}")

# Save results to JSON
results = {
    'top_50': scored[:50],
    'all_scored': scored,
    'total_analyzed': len(scored)
}

with open('russell_1000_scores.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n\nResults saved to russell_1000_scores.json")
print(f"Total stocks analyzed: {len(scored)}")