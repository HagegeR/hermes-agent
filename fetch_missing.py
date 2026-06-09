"""
Smart incremental fetcher: 
- Uses existing 919 scored stocks from russell_1000_scores.json
- Only fetches the 78 missing tickers with retry/backoff
- Saves progress incrementally
"""
import yfinance as yf
import json, time, random

with open('russell_1000_full.txt') as f:
    all_tickers = [t.strip() for t in f if t.strip()]

with open('russell_1000_tickers.txt') as f:
    old_tickers = {t.strip() for t in f if t.strip()}

missing = [t for t in all_tickers if t not in old_tickers]
print(f"Missing tickers: {len(missing)}: {missing}")

# Load existing scored data
with open('russell_1000_scores.json') as f:
    existing = json.load(f)

existing_scored = existing['all_scored']
print(f"Existing scored: {len(existing_scored)}")

def safe_float(val):
    try:
        f = float(val)
        return f if f == f else None
    except: return None

def fetch_one(ticker, attempt=1):
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        if not info or 'quoteType' not in info:
            if attempt < 5:
                wait = 5 * attempt + random.uniform(2, 5)
                print(f"  {ticker}: rate-limited, waiting {wait:.1f}s (attempt {attempt})")
                time.sleep(wait)
                return fetch_one(ticker, attempt + 1)
            return None
        return {'ticker': ticker, 'info': info, 't': t}
    except Exception as e:
        if attempt < 5:
            time.sleep(3 * attempt)
            return fetch_one(ticker, attempt + 1)
        print(f"  {ticker}: failed after retries: {e}")
        return None

def score_one(data):
    if not data:
        return None
    info = data['info']
    t = data['t']
    
    def gn(k, d=None):
        v = info.get(k)
        return v if isinstance(v, (int, float)) and v == v else d
    
    pe = safe_float(info.get('trailingPE')) or safe_float(info.get('forwardPE'))
    val = 25 if (pe and 0<pe<10) else 20 if (pe and pe<15) else 15 if (pe and pe<20) else 10 if (pe and pe<25) else 5 if (pe and pe<35) else 10 if pe is None else 0
    
    rg = None
    try:
        inc = t.income_stmt
        if inc is not None and not inc.empty and 'Total Revenue' in inc.index and len(inc.loc['Total Revenue']) >= 2:
            r0, r1 = inc.loc['Total Revenue'].iloc[0], inc.loc['Total Revenue'].iloc[1]
            if r1 and r1 != 0:
                rg = (r0 - r1) / abs(r1)
    except: pass
    
    gm = None
    try:
        inc = t.income_stmt
        if inc is not None and not inc.empty:
            if 'Gross Profit' in inc.index and 'Total Revenue' in inc.index:
                rev = inc.loc['Total Revenue'].iloc[0] if 'Total Revenue' in inc.index else None
                gp = inc.loc['Gross Profit'].iloc[0] if 'Gross Profit' in inc.index else None
                if rev and rev != 0 and gp:
                    gm = gp / rev
    except: pass
    
    growth = 0
    if rg:
        growth += 12 if rg > 0.3 else 10 if rg > 0.2 else 7 if rg > 0.1 else 4 if rg > 0 else 0
    t_pe = safe_float(info.get('trailingPE'))
    f_pe = safe_float(info.get('forwardPE'))
    if t_pe and f_pe and f_pe > 0:
        peg = (t_pe/f_pe - 1)*100
        growth += 8 if peg > 20 else 5 if peg > 10 else 3 if peg > 0 else 0
    eg = gn('earningsGrowth') or gn('revenueGrowth')
    if eg: growth += 5 if eg > 0.3 else 3 if eg > 0.15 else 1 if eg > 0 else 0
    
    prof = 0
    if gm: prof += 8 if gm > 0.5 else 5 if gm > 0.35 else 3 if gm > 0.2 else 0
    op = gn('operatingMargins') or gn('profitMargins')
    if op: prof += 7 if op > 0.3 else 5 if op > 0.2 else 3 if op > 0.1 else 1 if op > 0 else 0
    roe = gn('returnOnEquity')
    if roe: prof += 5 if roe > 0.25 else 3 if roe > 0.15 else 1 if roe > 0.05 else 0
    
    anl = 0
    try:
        rec = t.recommendations
        if rec is not None and not rec.empty and 'Grade' in rec.columns:
            sb = int((rec['Grade']=='Strong Buy').sum())
            b = int((rec['Grade']=='Buy').sum())
            h = int((rec['Grade']=='Hold').sum())
            s = int((rec['Grade']=='Sell').sum())
            ss = int((rec['Grade']=='Strong Sell').sum())
            tot = sb+b+h+s+ss
            if tot > 0:
                br = (sb+b)/tot
                anl += 10 if br >= 0.7 else 7 if br >= 0.5 else 4 if br >= 0.3 else 0
                sr = (s+ss)/tot
                anl -= 5 if sr > 0.3 else 2 if sr > 0.15 else 0
    except: pass
    
    curr_p = gn('currentPrice') or gn('regularMarketPrice')
    mean_t = None
    try:
        targets = t.analyst_price_targets
        if targets is not None and not targets.empty:
            mean_t = safe_float(targets.iloc[0].get('TargetMean'))
    except: pass
    if curr_p and mean_t and mean_t > 0:
        up = (mean_t - curr_p) / curr_p
        anl += 8 if up > 0.3 else 6 if up > 0.2 else 4 if up > 0.1 else 2 if up > 0 else -3
    else:
        anl += 3
    
    mom = 0
    wk52 = gn('52WeekChange')
    if wk52: mom += 5 if wk52 > 0.3 else 3 if wk52 > 0.15 else 1 if wk52 > 0 else -3 if wk52 < -0.2 else 0
    sma = gn('fiftyDayAverage')
    if sma and curr_p and sma > 0:
        pv = (curr_p - sma) / sma
        mom += 3 if pv > 0.1 else 1 if pv > 0 else -2 if pv < -0.1 else 0
    beta = gn('beta')
    if beta and 0 < beta < 1.0: mom += 2
    
    conf = 0
    mc = gn('marketCap')
    if mc: conf += 2 if mc > 100e9 else 1 if mc > 10e9 else 0
    try:
        nc = len(t.news) if t.news else 0
    except: nc = 0
    if nc > 0: conf += 1
    ip = gn('heldByInstitutionsPercentage')
    if ip: conf += 2 if ip > 0.5 else 1 if ip > 0.2 else 0
    
    total = val + growth + prof + anl + mom + conf
    
    return {
        'ticker': data['ticker'],
        'company_name': info.get('shortName') or info.get('longName') or data['ticker'],
        'sector': info.get('sector') or 'Unknown',
        'industry': info.get('industry') or 'Unknown',
        'total_score': round(total, 1),
        'score_breakdown': {'valuation': val, 'growth': growth, 'profitability': prof,
                           'analyst': anl, 'momentum': mom, 'confidence': conf},
        'pe_ratio': t_pe,
        'forward_pe': f_pe,
        'revenue_growth': rg,
        'gross_margin': gm,
        'profit_margin': op,
        'roe': roe,
        'market_cap': mc,
        'analyst_buy_ratio': None,
        'total_recs': 0,
        'upside_to_target': ((mean_t - curr_p) / curr_p) if (curr_p and mean_t and curr_p > 0) else None,
        'current_price': curr_p,
        'mean_target': mean_t,
        'week52_change': wk52,
        'beta': beta,
        'inst_pct': ip,
        'earnings_growth': eg,
    }

# Fetch missing tickers with delays
new_scored = []
fail_count = 0
for i, ticker in enumerate(missing):
    print(f"[{i+1}/{len(missing)}] Fetching {ticker}...", end='', flush=True)
    data = fetch_one(ticker)
    if data:
        scored = score_one(data)
        if scored:
            new_scored.append(scored)
            mc = scored['market_cap']
            mc_str = f"${mc/1e12:.1f}T" if mc and mc >= 1e12 else f"${mc/1e9:.0f}B" if mc and mc >= 1e9 else ""
            print(f" Score={scored['total_score']} | PE={scored['pe_ratio']} | RevG={scored['revenue_growth']*100:.0f}% | {mc_str}")
        else:
            print(f" FAILED to score")
            fail_count += 1
    else:
        print(f" FAILED to fetch")
        fail_count += 1
    # Brief pause between requests
    time.sleep(0.5)

print(f"\nNew tickers scored: {len(new_scored)}/{len(missing)} (failed: {fail_count})")

# Combine and re-rank
all_scored = existing_scored + new_scored
all_scored.sort(key=lambda x: x['total_score'], reverse=True)
print(f"Total scored: {len(all_scored)}")

# NEW top 50
new_top50 = all_scored[:50]
new_top50_tickers = {s['ticker'] for s in new_top50}

# Compare
old_top50 = {s['ticker'] for s in existing['top_50']}
new_entries = new_top50_tickers - old_top50
dropped = old_top50 - new_top50_tickers

print(f"\n{'='*70}")
print(f"CHANGES FROM PREVIOUS TOP 50:")
print(f"  ✅ NEW ENTRANTS ({len(new_entries)}): {sorted(new_entries)}")
print(f"  ❌ DROPPED ({len(dropped)}): {sorted(dropped)}")

# Print new top 50
print(f"\n{'='*70}")
print("COMPLETE RUSSELL 1000 TOP 50 (now including all constituents)")
print(f"{'='*70}")
for i, s in enumerate(new_top50, 1):
    bd = s['score_breakdown']
    m = []
    if s['pe_ratio']: m.append(f"PE={s['pe_ratio']:.1f}")
    if s['revenue_growth'] is not None: m.append(f"RevG={s['revenue_growth']*100:.1f}%")
    if s['gross_margin'] is not None: m.append(f"GM={s['gross_margin']*100:.1f}%")
    if s['upside_to_target'] is not None: m.append(f"Upside={s['upside_to_target']*100:.1f}%")
    if s['current_price']: m.append(f"${s['current_price']:.2f}")
    mc = s['market_cap']
    if mc:
        if mc >= 1e12: m.append(f"MC=${mc/1e12:.1f}T")
        elif mc >= 1e9: m.append(f"MC=${mc/1e9:.0f}B")
    star = " ⭐ NEW" if s['ticker'] in new_entries else ""
    print(f"\n#{i} {s['ticker']} | {s['company_name'][:40]}{star}")
    print(f"   Score={s['total_score']}/100 | Val={bd['valuation']} Gth={bd['growth']} Prof={bd['profitability']} Anl={bd['analyst']} Mom={bd['momentum']} Conf={bd['confidence']}")
    print(f"   {' | '.join(m)}")

# Save
with open('russell_1000_scores_v2.json', 'w') as f:
    json.dump({'top_50': new_top50, 'all_scored': all_scored, 'total': len(all_scored)}, f, indent=2, default=str)

with open('top50_tickers.txt', 'w') as f:
    for s in new_top50:
        f.write(s['ticker'] + '\n')

print(f"\nSaved: russell_1000_scores_v2.json")