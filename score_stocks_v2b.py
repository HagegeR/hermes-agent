"""
Re-score from saved data - fix type errors and re-rank
"""
import json, yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

with open('russell_1000_full.txt') as f:
    tickers = [line.strip() for line in f if line.strip()]

# Re-fetch ONLY the ones that might have had issues (from scratch)
# But first let's try scoring what we have and only re-fetch failures
def safe_float(val):
    try:
        f = float(val)
        if f != f:  # NaN check
            return None
        return f
    except (TypeError, ValueError):
        return None

def fetch_one(ticker):
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        financials = {}
        try:
            inc = t.income_stmt
            if inc is not None and not inc.empty:
                financials['revenue'] = inc.loc['Total Revenue'].iloc[0] if 'Total Revenue' in inc.index else None
                if 'Gross Profit' in inc.index and 'Total Revenue' in inc.index and inc.loc['Total Revenue'].iloc[0]:
                    financials['gross_margin'] = inc.loc['Gross Profit'].iloc[0] / inc.loc['Total Revenue'].iloc[0]
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
        return {'ticker': ticker, 'success': False}

def score_stock(data):
    if not data.get('success'):
        return None
    
    info = data.get('info', {})
    financials = data.get('financials', {})
    analyst = data.get('analyst', {})
    target = data.get('target', {})
    
    def get_num(key, default=None):
        val = info.get(key)
        if val is None: return default
        if isinstance(val, (int, float)): return val if val == val else default
        return default
    
    def get_fin(key, default=None):
        val = financials.get(key)
        if val is None: return default
        if isinstance(val, (int, float)): return val if val == val else default
        return default
    
    score = 0
    
    # Valuation
    pe_raw = info.get('trailingPE') or info.get('forwardPE')
    pe = safe_float(pe_raw)
    val_score = 0
    if pe and 0 < pe < 100:
        if pe < 10: val_score = 25
        elif pe < 15: val_score = 20
        elif pe < 20: val_score = 15
        elif pe < 25: val_score = 10
        elif pe < 35: val_score = 5
    elif pe is None: val_score = 10
    score += val_score
    
    # Growth
    growth_score = 0
    rev_g = get_fin('revenue_growth')
    if rev_g is not None:
        if rev_g > 0.3: growth_score += 12
        elif rev_g > 0.2: growth_score += 10
        elif rev_g > 0.1: growth_score += 7
        elif rev_g > 0: growth_score += 4
    t_pe = safe_float(info.get('trailingPE'))
    f_pe = safe_float(info.get('forwardPE'))
    if t_pe and f_pe and f_pe > 0:
        peg_implied = (t_pe / f_pe - 1) * 100
        if peg_implied > 20: growth_score += 8
        elif peg_implied > 10: growth_score += 5
        elif peg_implied > 0: growth_score += 3
    eps_g = get_num('earningsGrowth') or get_num('revenueGrowth')
    if eps_g:
        if eps_g > 0.3: growth_score += 5
        elif eps_g > 0.15: growth_score += 3
        elif eps_g > 0: growth_score += 1
    score += growth_score
    
    # Profitability
    profit_score = 0
    gm = get_fin('gross_margin')
    if gm is not None:
        if gm > 0.5: profit_score += 8
        elif gm > 0.35: profit_score += 5
        elif gm > 0.2: profit_score += 3
    op_m = get_num('operatingMargins') or get_num('profitMargins')
    if op_m:
        if op_m > 0.3: profit_score += 7
        elif op_m > 0.2: profit_score += 5
        elif op_m > 0.1: profit_score += 3
        elif op_m > 0: profit_score += 1
    roe = get_num('returnOnEquity')
    if roe:
        if roe > 0.25: profit_score += 5
        elif roe > 0.15: profit_score += 3
        elif roe > 0.05: profit_score += 1
    score += profit_score
    
    # Analyst
    analyst_score = 0
    sb = analyst.get('strong_buy', 0)
    b = analyst.get('buy', 0)
    h = analyst.get('hold', 0)
    s = analyst.get('sell', 0)
    ss = analyst.get('strong_sell', 0)
    total = sb + b + h + s + ss
    if total > 0:
        buy_r = (sb + b) / total
        if buy_r >= 0.7: analyst_score += 10
        elif buy_r >= 0.5: analyst_score += 7
        elif buy_r >= 0.3: analyst_score += 4
        sell_r = (s + ss) / total
        if sell_r > 0.3: analyst_score -= 5
        elif sell_r > 0.15: analyst_score -= 2
    curr_p = target.get('current_price') or get_num('currentPrice') or get_num('regularMarketPrice')
    mean_t = target.get('mean_target')
    if curr_p and mean_t and mean_t > 0:
        upside = (mean_t - curr_p) / curr_p
        if upside > 0.3: analyst_score += 8
        elif upside > 0.2: analyst_score += 6
        elif upside > 0.1: analyst_score += 4
        elif upside > 0: analyst_score += 2
        else: analyst_score -= 3
    else:
        analyst_score += 3
    score += analyst_score
    
    # Momentum
    momentum_score = 0
    wk52 = get_num('52WeekChange') or get_num('52WeekPriceReturn')
    if wk52:
        if wk52 > 0.3: momentum_score += 5
        elif wk52 > 0.15: momentum_score += 3
        elif wk52 > 0: momentum_score += 1
        elif wk52 < -0.2: momentum_score -= 3
    sma50 = get_num('fiftyDayAverage')
    curr = get_num('currentPrice') or get_num('regularMarketPrice')
    if sma50 and curr and sma50 > 0:
        price_vs_sma = (curr - sma50) / sma50
        if price_vs_sma > 0.1: momentum_score += 3
        elif price_vs_sma > 0: momentum_score += 1
        elif price_vs_sma < -0.1: momentum_score -= 2
    beta = get_num('beta')
    if beta and beta > 0:
        if beta < 1.0: momentum_score += 2
    score += momentum_score
    
    # Confidence
    conf_score = 0
    mc = get_num('marketCap')
    if mc:
        if mc > 100e9: conf_score += 2
        elif mc > 10e9: conf_score += 1
    try:
        news_count = len(t.news) if t.news else 0
    except:
        news_count = 0
    if news_count > 0: conf_score += 1
    inst_pct = get_num('heldByInstitutionsPercentage')
    if inst_pct:
        if inst_pct > 0.5: conf_score += 2
        elif inst_pct > 0.2: conf_score += 1
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
        'revenue_growth': rev_g,
        'gross_margin': gm,
        'profit_margin': op_m,
        'roe': roe,
        'market_cap': mc,
        'analyst_buy_ratio': (sb + b) / total if total > 0 else None,
        'total_recs': total,
        'upside_to_target': ((mean_t - curr_p) / curr_p) if (curr_p and mean_t and curr_p > 0) else None,
        'current_price': curr_p,
        'mean_target': mean_t,
        'week52_change': wk52,
        'beta': beta,
        'inst_pct': inst_pct,
        'earnings_growth': get_num('earningsGrowth'),
    }

# Fetch all data fresh
print("Re-fetching all 995 tickers...")
all_data = []
with ThreadPoolExecutor(max_workers=25) as executor:
    futures = {executor.submit(fetch_one, t): t for t in tickers}
    done = 0
    for future in as_completed(futures):
        all_data.append(future.result())
        done += 1
        if done % 200 == 0:
            print(f"  {done}/{len(tickers)}")

print(f"Fetched. Success: {sum(1 for d in all_data if d.get('success'))}")

# Score all
scored = []
for d in all_data:
    s = score_stock(d)
    if s:
        scored.append(s)

scored.sort(key=lambda x: x['total_score'], reverse=True)
print(f"Scored: {len(scored)}")

# Print top 50
print("\n" + "="*80)
print("UPDATED TOP 50 — COMPLETE RUSSELL 1000 (995 stocks)")
print("="*80)
for i, s in enumerate(scored[:50], 1):
    bd = s['score_breakdown']
    metrics = []
    if s['pe_ratio']: metrics.append(f"PE={s['pe_ratio']:.1f}")
    if s['revenue_growth'] is not None: metrics.append(f"RevG={s['revenue_growth']*100:.1f}%")
    if s['gross_margin'] is not None: metrics.append(f"GM={s['gross_margin']*100:.1f}%")
    if s['analyst_buy_ratio'] is not None: metrics.append(f"BuyR={s['analyst_buy_ratio']*100:.0f}%")
    if s['upside_to_target'] is not None: metrics.append(f"Upside={s['upside_to_target']*100:.1f}%")
    if s['current_price']: metrics.append(f"${s['current_price']:.2f}")
    mc = s['market_cap']
    if mc:
        if mc >= 1e12: metrics.append(f"MC=${mc/1e12:.1f}T")
        elif mc >= 1e9: metrics.append(f"MC=${mc/1e9:.0f}B")
    print(f"\n#{i}: {s['ticker']} — {s['company_name']}")
    print(f"   Score={s['total_score']}/100 | Val={bd['valuation']} Gth={bd['growth']} Prof={bd['profitability']} Anl={bd['analyst']} Mom={bd['momentum']} Conf={bd['confidence']}")
    print(f"   {' | '.join(metrics)}")

# Compare with old
with open('russell_1000_scores.json') as f:
    old_data = json.load(f)
old_top50 = {s['ticker'] for s in old_data['top_50']}
new_top50_tickers = {s['ticker'] for s in scored[:50]}
new_entries = new_top50_tickers - old_top50
dropped = old_top50 - new_top50_tickers

print(f"\n\n{'='*60}")
print("CHANGES:")
print(f"   ✅ NEW in Top 50 ({len(new_entries)}): {sorted(new_entries)}")
print(f"   ❌ DROPPED from Top 50 ({len(dropped)}): {sorted(dropped)}")

# Save
with open('russell_1000_scores_v2.json', 'w') as f:
    json.dump({'top_50': scored[:50], 'all_scored': scored, 'total': len(scored)}, f, indent=2, default=str)

# Also save a simple list for quick reference
with open('top50_tickers.txt', 'w') as f:
    for s in scored[:50]:
        f.write(s['ticker'] + '\n')

print(f"\nSaved to russell_1000_scores_v2.json and top50_tickers.txt")