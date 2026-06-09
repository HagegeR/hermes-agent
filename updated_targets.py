"""
Quick analyst targets for new top 20 entrants + original best performers
"""
import yfinance as yf, json, time

NEW_STARS = ['NVDA', 'EOG', 'QCOM', 'APA', 'MU', 'HAS', 'IT', 'AU', 'AR', 'INCY',
             'EXE', 'HALO', 'GILD', 'AMG', 'GMED', 'CPAY', 'ADBE', 'AMGN', 'LRCX', 'KLAC']

def safe_float(v):
    try:
        f = float(v)
        return f if f == f else None
    except: return None

results = {}
for i, ticker in enumerate(NEW_STARS):
    print(f"[{i+1}/{len(NEW_STARS)}] {ticker}...", end='', flush=True)
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        
        # Analyst targets
        mean_t, high_t, low_t = None, None, None
        try:
            targets = t.analyst_price_targets
            if targets is not None and not targets.empty:
                row = targets.iloc[0]
                mean_t = safe_float(row.get('TargetMean'))
                high_t = safe_float(row.get('TargetHigh'))
                low_t = safe_float(row.get('TargetLow'))
        except: pass
        
        if not mean_t:
            mean_t = info.get('targetMeanPrice')
        if not high_t:
            high_t = info.get('targetHighPrice')
        if not low_t:
            low_t = info.get('targetLowPrice')
        
        curr_p = info.get('currentPrice') or info.get('regularMarketPrice')
        
        results[ticker] = {
            'company': info.get('shortName') or info.get('longName') or ticker,
            'sector': info.get('sector') or 'Unknown',
            'current_price': curr_p,
            'mean_target': mean_t,
            'high_target': high_t,
            'low_target': low_t,
            'upside_mean': ((mean_t - curr_p) / curr_p) if curr_p and mean_t else None,
            'upside_high': ((high_t - curr_p) / curr_p) if curr_p and high_t else None,
            'trailing_pe': safe_float(info.get('trailingPE')),
            'forward_pe': safe_float(info.get('forwardPE')),
            'revenue_growth': info.get('revenueGrowth'),
            'earnings_growth': info.get('earningsGrowth'),
            'market_cap': info.get('marketCap'),
            'week52_change': info.get('52WeekChange'),
            'beta': info.get('beta'),
            'inst_pct': info.get('heldByInstitutionsPercentage'),
        }
        mc = results[ticker]['market_cap']
        mc_s = f"${mc/1e12:.1f}T" if mc and mc>=1e12 else f"${mc/1e9:.0f}B" if mc and mc>=1e9 else ""
        up = results[ticker]['upside_mean']
        up_s = f"{up*100:.1f}%" if up else "N/A"
        print(f" Price=${curr_p:.2f} | Target=${mean_t:.2f} | Upside={up_s} | MC={mc_s}")
    except Exception as e:
        print(f" ERROR: {e}")
    time.sleep(0.3)

with open('updated_targets.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nSaved to updated_targets.json")