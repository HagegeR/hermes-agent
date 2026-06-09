"""
Smart Russell 1000 scorer with rate-limit handling, retries, and incremental saves.
"""
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
import time, json, random

with open('russell_1000_full.txt') as f:
    tickers = [line.strip() for line in f if line.strip()]

print(f"Total tickers: {len(tickers)}")

# Load any previously saved partial results
try:
    with open('russell_1000_partial.json') as f:
        partial = json.load(f)
    done_tickers = set(s['ticker'] for s in partial['all_scored'])
    print(f"Resuming: {len(done_tickers)} already done")
except Exception:
    partial = {'all_scored': []}
    done_tickers = set()

remaining = [t for t in tickers if t not in done_tickers]
print(f"Remaining to process: {len(remaining)}")

MAX_RETRIES = 3
RETRY_DELAY = 10  # seconds

def safe_float(val):
    try:
        f = float(val)
        return f if f == f else None
    except (TypeError, ValueError):
        return None

def fetch_ticker(ticker, attempt=1):
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        
        # Check if rate limited
        if not info or 'quoteType' not in info:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt + random.uniform(1, 3))
                return fetch_ticker(ticker, attempt + 1)
            return {'ticker': ticker, 'success': False, 'rate_limited': True}
        
        financials = {}
        try:
            inc = t.income_stmt
            if inc is not None and not inc.empty and len(inc.columns) > 0:
                financials['revenue'] = inc.loc['Total Revenue'].iloc[0] if 'Total Revenue' in inc.index else None
                if 'Gross Profit' in inc.index and 'Total Revenue' in inc.index:
                    rev = inc.loc['Total Revenue'].iloc[0] if 'Total Revenue' in inc.index else None
                    gp = inc.loc['Gross Profit'].iloc[0] if 'Gross Profit' in inc.index else None
                    if rev and rev != 0:
                        financials['gross_margin'] = gp / rev
                if len(inc.loc['Total Revenue']) >= 2:
                    r0 = inc.loc['Total Revenue'].iloc[0]
                    r1 = inc.loc['Total Revenue'].iloc[1]
                    if r1 and r1 != 0:
                        financials['revenue_growth'] = (r0 - r1) / abs(r1)
        except Exception:
            pass
        
        analyst = {}
        try:
            rec = t.recommendations
            if rec is not None and not rec.empty and 'Grade' in rec.columns:
                analyst['strong_buy'] = int((rec['Grade'] == 'Strong Buy').sum())
                analyst['buy'] = int((rec['Grade'] == 'Buy').sum())
                analyst['hold'] = int((rec['Grade'] == 'Hold').sum())
                analyst['sell'] = int((rec['Grade'] == 'Sell').sum())
                analyst['strong_sell'] = int((rec['Grade'] == 'Strong Sell').sum())
        except Exception:
            pass
        
        target = {}
        try:
            targets = t.analyst_price_targets
            if targets is not None and not targets.empty:
                row = targets.iloc[0]
                target = {
                    'current_price': safe_float(row.get('Current')),
                    'mean_target': safe_float(row.get('TargetMean')),
                    'high_target': safe_float(row.get('TargetHigh')),
                    'low_target': safe_float(row.get('TargetLow')),
                }
        except Exception:
            pass
        
        return {'ticker': ticker, 'info': info, 'financials': financials,
                'analyst': analyst, 'target': target, 'success': True}
    except Exception as e:
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY * attempt)
            return fetch_ticker(ticker, attempt + 1)
        return {'ticker': ticker, 'success': False, 'error': str(e)}

def score_stock(data):
    if not data.get('success'):
        return None
    
    info = data.get('info', {})
    financials = data.get('financials', {})
    analyst = data.get('analyst', {})
    target = data.get('target', {})
    
    def gn(key, default=None):
        val = info.get(key)
        if val is None: return default
        return val if isinstance(val, (int, float)) and val == val else default
    
    def gf(key, default=None):
        val = financials.get(key)
        if val is None: return default
        return val if isinstance(val, (int, float)) and val == val else default
    
    score = 0
    pe = safe_float(info.get('trailingPE')) or safe_float(info.get('forwardPE'))
    val_score = 25 if (pe and 0 < pe < 10) else 20 if (pe and pe < 15) else 15 if (pe and pe < 20) else 10 if (pe and pe < 25) else 5 if (pe and pe < 35) else 10 if pe is None else 0
    score += val_score
    
    growth_score = 0
    rg = gf('revenue_growth')
    if rg:
        growth_score += 12 if rg > 0.3 else 10 if rg > 0.2 else 7 if rg > 0.1 else 4 if rg > 0 else 0
    t_pe = safe_float(info.get('trailingPE'))
    f_pe = safe_float(info.get('forwardPE'))
    if t_pe and f_pe and f_pe > 0:
        peg = (t_pe / f_pe - 1) * 100
        growth_score += 8 if peg > 20 else 5 if peg > 10 else 3 if peg > 0 else 0
    eg = gn('earningsGrowth') or gn('revenueGrowth')
    if eg:
        growth_score += 5 if eg > 0.3 else 3 if eg > 0.15 else 1 if eg > 0 else 0
    score += growth_score
    
    profit_score = 0
    gm = gf('gross_margin')
    if gm: profit_score += 8 if gm > 0.5 else 5 if gm > 0.35 else 3 if gm > 0.2 else 0
    op = gn('operatingMargins') or gn('profitMargins')
    if op: profit_score += 7 if op > 0.3 else 5 if op > 0.2 else 3 if op > 0.1 else 1 if op > 0 else 0
    roe = gn('returnOnEquity')
    if roe: profit_score += 5 if roe > 0.25 else 3 if roe > 0.15 else 1 if roe > 0.05 else 0
    score += profit_score
    
    analyst_score = 0
    sb = analyst.get('strong_buy', 0); b = analyst.get('buy', 0)
    h = analyst.get('hold', 0); s = analyst.get('sell', 0); ss = analyst.get('strong_sell', 0)
    total = sb + b + h + s + ss
    if total > 0:
        br = (sb + b) / total
        analyst_score += 10 if br >= 0.7 else 7 if br >= 0.5 else 4 if br >= 0.3 else 0
        sr = (s + ss) / total
        analyst_score -= 5 if sr > 0.3 else 2 if sr > 0.15 else 0
    curr_p = target.get('current_price') or gn('currentPrice') or gn('regularMarketPrice')
    mean_t = target.get('mean_target')
    if curr_p and mean_t and mean_t > 0:
        up = (mean_t - curr_p) / curr_p
        analyst_score += 8 if up > 0.3 else 6 if up > 0.2 else 4 if up > 0.1 else 2 if up > 0 else -3
    else:
        analyst_score += 3
    score += analyst_score
    
    momentum_score = 0
    wk52 = gn('52WeekChange')
    if wk52: momentum_score += 5 if wk52 > 0.3 else 3 if wk52 > 0.15 else 1 if wk52 > 0 else -3 if wk52 < -0.2 else 0
    sma50 = gn('fiftyDayAverage'); curr = gn('currentPrice') or gn('regularMarketPrice')
    if sma50 and curr and sma50 > 0:
        pv = (curr - sma50) / sma50
        momentum_score += 3 if pv > 0.1 else 1 if pv > 0 else -2 if pv < -0.1 else 0
    beta = gn('beta')
    if beta and beta > 0 and beta < 1.0: momentum_score += 2
    score += momentum_score
    
    conf_score = 0
    mc = gn('marketCap')
    if mc: conf_score += 2 if mc > 100e9 else 1 if mc > 10e9 else 0
    try:
        nc = len(t.news) if t.news else 0
    except:
        nc = 0
    if nc > 0: conf_score += 1
    ip = gn('heldByInstitutionsPercentage')
    if ip: conf_score += 2 if ip > 0.5 else 1 if ip > 0.2 else 0
    score += conf_score
    
    return {
        'ticker': data['ticker'],
        'company_name': info.get('shortName') or info.get('longName') or data['ticker'],
        'sector': info.get('sector') or 'Unknown',
        'industry': info.get('industry') or 'Unknown',
        'total_score': round(score, 1),
        'score_breakdown': {'valuation': val_score, 'growth': growth_score,
                           'profitability': profit_score, 'analyst': analyst_score,
                           'momentum': momentum_score, 'confidence': conf_score},
        'pe_ratio': t_pe,
        'forward_pe': f_pe,
        'revenue_growth': rg,
        'gross_margin': gm,
        'profit_margin': op,
        'roe': roe,
        'market_cap': mc,
        'analyst_buy_ratio': (sb + b) / total if total > 0 else None,
        'total_recs': total,
        'upside_to_target': ((mean_t - curr_p) / curr_p) if (curr_p and mean_t and curr_p > 0) else None,
        'current_price': curr_p,
        'mean_target': mean_t,
        'week52_change': wk52,
        'beta': beta,
        'inst_pct': ip,
        'earnings_growth': eg,
    }

# Process with lower concurrency to avoid rate limiting
all_scored = list(partial['all_scored'])
done_tickers = {s['ticker'] for s in all_scored}
batch_size = 20

print(f"Already scored: {len(done_tickers)} | Remaining: {len(remaining)}")
print("Starting batch processing...")

for i in range(0, len(remaining), batch_size):
    batch = remaining[i:i+batch_size]
    print(f"  Batch {i//batch_size + 1}/{(len(remaining)+batch_size-1)//batch_size}: {batch[0]}...{batch[-1]}")
    
    batch_results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_ticker, t): t for t in batch}
        for future in as_completed(futures):
            batch_results.append(future.result())
    
    for d in batch_results:
        s = score_stock(d)
        if s:
            all_scored.append(s)
    
    # Save progress every batch
    all_scored.sort(key=lambda x: x['total_score'], reverse=True)
    with open('russell_1000_partial.json', 'w') as f:
        json.dump({'all_scored': all_scored}, f, default=str)
    
    print(f"  → {len(all_scored)} total scored so far. Sleeping to avoid rate limit...")
    time.sleep(3)  # Brief pause between batches

print(f"\nFinal: {len(all_scored)} stocks scored")

# Final full ranking
all_scored.sort(key=lambda x: x['total_score'], reverse=True)

# Print top 50
print("\n" + "="*80)
print("COMPLETE RUSSELL 1000 TOP 50 (995 stocks)")
print("="*80)
for i, s in enumerate(all_scored[:50], 1):
    bd = s['score_breakdown']
    m = []
    if s['pe_ratio']: m.append(f"PE={s['pe_ratio']:.1f}")
    if s['revenue_growth'] is not None: m.append(f"RevG={s['revenue_growth']*100:.1f}%")
    if s['gross_margin'] is not None: m.append(f"GM={s['gross_margin']*100:.1f}%")
    if s['analyst_buy_ratio'] is not None: m.append(f"BuyR={s['analyst_buy_ratio']*100:.0f}%")
    if s['upside_to_target'] is not None: m.append(f"Upside={s['upside_to_target']*100:.1f}%")
    if s['current_price']: m.append(f"${s['current_price']:.2f}")
    mc = s['market_cap']
    if mc:
        if mc >= 1e12: m.append(f"MC=${mc/1e12:.1f}T")
        elif mc >= 1e9: m.append(f"MC=${mc/1e9:.0f}B")
    print(f"\n#{i} {s['ticker']} | {s['company_name'][:40]}")
    print(f"   Score={s['total_score']}/100 | Val={bd['valuation']} Gth={bd['growth']} Prof={bd['profitability']} Anl={bd['analyst']} Mom={bd['momentum']} Conf={bd['confidence']}")
    print(f"   {' | '.join(m)}")

# Compare
with open('russell_1000_scores.json') as f:
    old = json.load(f)
old_tickers = {s['ticker'] for s in old['top_50']}
new_tickers = {s['ticker'] for s in all_scored[:50]}
new_entries = new_tickers - old_tickers
dropped = old_tickers - new_tickers

print(f"\n\n{'='*60}")
print(f"CHANGES FROM PREVIOUS ANALYSIS:")
print(f"  ✅ NEW ENTRANTS ({len(new_entries)}): {sorted(new_entries)}")
print(f"  ❌ DROPPED ({len(dropped)}): {sorted(dropped)}")

with open('russell_1000_scores_v2.json', 'w') as f:
    json.dump({'top_50': all_scored[:50], 'all_scored': all_scored, 'total': len(all_scored)}, f, indent=2, default=str)

with open('top50_tickers.txt', 'w') as f:
    for s in all_scored[:50]:
        f.write(s['ticker'] + '\n')

print(f"\nSaved: russell_1000_scores_v2.json, top50_tickers.txt")