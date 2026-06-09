#!/usr/bin/env python3
"""
Russell 1000 Screener — ONE COMMAND to get the complete ranked stock list.
Fetches all ~997 Russell 1000 constituents, scores them, updates analyst targets,
and prints the full top 50 with 6M/1Y projections and buy zones.

Usage: .venv_score/Scripts/python.exe russell_screener.py

Dependencies: yfinance, beautifulsoup4, requests, pandas, numpy
Install: uv pip install yfinance beautifulsoup4 requests pandas numpy --python .venv_score
"""
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
import json, time, random, sys, re

# ─── CONFIG ───────────────────────────────────────────────────────────────────
PARALLEL_WORKERS = 15
BATCH_DELAY = 2        # seconds between batches (rate limit protection)
RETRY_MAX = 3
TOP_N = 50
OUTPUT_FILE = 'russell_1000_scores.json'
PARTIAL_FILE = 'russell_1000_partial.json'
TICKER_LIST_FILE = 'russell_1000_tickers.txt'
FULL_LIST_FILE = 'russell_1000_full.txt'
TARGETS_FILE = 'updated_targets.json'
# ───────────────────────────────────────────────────────────────────────────────

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# ─── STEP 0: CHECK ENV ────────────────────────────────────────────────────────
def check_env():
    try:
        yf.Ticker('AAPL').info
        log("✅ yfinance working")
        return True
    except Exception as e:
        log(f"❌ yfinance rate limited or error: {e}")
        return False

# ─── STEP 1: GET TICKERS ─────────────────────────────────────────────────────
def get_russell_tickers():
    """Fetch Russell 1000 from Wikipedia wikitable (sortable table)."""
    try:
        import requests
        from bs4 import BeautifulSoup
        resp = requests.get(
            'https://en.wikipedia.org/wiki/Russell_1000_Index',
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=15
        )
        soup = BeautifulSoup(resp.text, 'html.parser')
        tables = soup.find_all('table', class_='wikitable sortable')
        
        tickers = set()
        for tbl in tables:
            rows = tbl.find_all('tr')
            if len(rows) > 100:  # Constituent table has ~1000 rows
                for row in rows[1:]:
                    cells = row.find_all(['td', 'th'])
                    for cell in cells[:3]:
                        text = cell.get_text(strip=True)
                        if re.match(r'^[A-Z]{1,5}$', text) and 1 <= len(text) <= 5:
                            tickers.add(text)
                            break
        
        # Save both filtered and full list
        with open(TICKER_LIST_FILE, 'w') as f:
            for t in sorted(tickers):
                f.write(t + '\n')
        with open(FULL_LIST_FILE, 'w') as f:
            for t in sorted(tickers):
                f.write(t + '\n')
        
        log(f"✅ Russell 1000: {len(tickers)} tickers fetched from Wikipedia")
        return sorted(tickers)
    except Exception as e:
        log(f"❌ Wikipedia fetch failed: {e}")
        # Fallback: load existing
        try:
            with open(FULL_LIST_FILE) as f:
                tickers = [l.strip() for l in f if l.strip()]
            log(f"✅ Loaded {len(tickers)} tickers from cache")
            return tickers
        except:
            return []

# ─── STEP 2: SCORING ──────────────────────────────────────────────────────────
def safe_float(v):
    try:
        f = float(v)
        return f if f == f else None
    except: return None

def fetch_ticker_data(ticker):
    """Fetch yfinance data for one ticker with retry logic."""
    for attempt in range(RETRY_MAX):
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}
            if not info or 'quoteType' not in info:
                raise ValueError("Empty info")
            
            financials = {}
            try:
                inc = t.income_stmt
                if inc is not None and not inc.empty:
                    if 'Total Revenue' in inc.index:
                        rev = inc.loc['Total Revenue']
                        financials['revenue'] = rev.iloc[0] if len(rev) > 0 else None
                        if len(rev) >= 2 and rev.iloc[1] and rev.iloc[1] != 0:
                            financials['revenue_growth'] = (rev.iloc[0] - rev.iloc[1]) / abs(rev.iloc[1])
                    if 'Gross Profit' in inc.index and 'Total Revenue' in inc.index:
                        rev_v = inc.loc['Total Revenue'].iloc[0] if 'Total Revenue' in inc.index else None
                        gp = inc.loc['Gross Profit'].iloc[0] if 'Gross Profit' in inc.index else None
                        if rev_v and rev_v != 0 and gp:
                            financials['gross_margin'] = gp / rev_v
            except: pass
            
            analyst = {}
            try:
                rec = t.recommendations
                if rec is not None and not rec.empty and 'Grade' in rec.columns:
                    analyst = {
                        'strong_buy': int((rec['Grade'] == 'Strong Buy').sum()),
                        'buy': int((rec['Grade'] == 'Buy').sum()),
                        'hold': int((rec['Grade'] == 'Hold').sum()),
                        'sell': int((rec['Grade'] == 'Sell').sum()),
                        'strong_sell': int((rec['Grade'] == 'Strong Sell').sum()),
                    }
            except: pass
            
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
            except: pass
            
            return {'ticker': ticker, 'info': info, 'financials': financials,
                    'analyst': analyst, 'target': target, 'success': True}
        except Exception as e:
            if attempt < RETRY_MAX - 1:
                time.sleep(3 * (attempt + 1) + random.uniform(1, 3))
            else:
                return {'ticker': ticker, 'success': False, 'error': str(e)}

def score_stock(data):
    """Score a stock on 6 dimensions: Val, Growth, Profit, Analyst, Momentum, Confidence."""
    if not data.get('success'):
        return None
    
    info = data['info']
    fin = data['financials']
    anl = data['analyst']
    tgt = data['target']
    
    def gn(k, d=None):
        v = info.get(k)
        return v if isinstance(v, (int, float)) and v == v else d
    
    # Valuation (0-25)
    pe = safe_float(info.get('trailingPE')) or safe_float(info.get('forwardPE'))
    val = 25 if (pe and 0 < pe < 10) else 20 if (pe and pe < 15) else 15 if (pe and pe < 20) else 10 if (pe and pe < 25) else 5 if (pe and pe < 35) else 10 if pe is None else 0
    
    # Growth (0-25)
    rg = fin.get('revenue_growth')
    gr = 0
    if rg: gr += 12 if rg > 0.3 else 10 if rg > 0.2 else 7 if rg > 0.1 else 4 if rg > 0 else 0
    t_pe = safe_float(info.get('trailingPE')); f_pe = safe_float(info.get('forwardPE'))
    if t_pe and f_pe and f_pe > 0:
        peg = (t_pe / f_pe - 1) * 100
        gr += 8 if peg > 20 else 5 if peg > 10 else 3 if peg > 0 else 0
    eg = gn('earningsGrowth') or gn('revenueGrowth')
    if eg: gr += 5 if eg > 0.3 else 3 if eg > 0.15 else 1 if eg > 0 else 0
    
    # Profitability (0-20)
    gm = fin.get('gross_margin')
    pr = 0
    if gm: pr += 8 if gm > 0.5 else 5 if gm > 0.35 else 3 if gm > 0.2 else 0
    op = gn('operatingMargins') or gn('profitMargins')
    if op: pr += 7 if op > 0.3 else 5 if op > 0.2 else 3 if op > 0.1 else 1 if op > 0 else 0
    roe = gn('returnOnEquity')
    if roe: pr += 5 if roe > 0.25 else 3 if roe > 0.15 else 1 if roe > 0.05 else 0
    
    # Analyst Sentiment (0-20)
    sb = anl.get('strong_buy', 0); b = anl.get('buy', 0)
    h = anl.get('hold', 0); s = anl.get('sell', 0); ss = anl.get('strong_sell', 0)
    tot = sb + b + h + s + ss
    anl_s = 0
    if tot > 0:
        br = (sb + b) / tot
        anl_s += 10 if br >= 0.7 else 7 if br >= 0.5 else 4 if br >= 0.3 else 0
        sr = (s + ss) / tot
        anl_s -= 5 if sr > 0.3 else 2 if sr > 0.15 else 0
    curr_p = tgt.get('current_price') or gn('currentPrice') or gn('regularMarketPrice')
    mean_t = tgt.get('mean_target') or gn('targetMeanPrice')
    if curr_p and mean_t and mean_t > 0:
        up = (mean_t - curr_p) / curr_p
        anl_s += 8 if up > 0.3 else 6 if up > 0.2 else 4 if up > 0.1 else 2 if up > 0 else -3
    else:
        anl_s += 3  # partial credit for having data
    
    # Momentum (0-10)
    wk52 = gn('52WeekChange')
    mom = 0
    if wk52: mom += 5 if wk52 > 0.3 else 3 if wk52 > 0.15 else 1 if wk52 > 0 else -3 if wk52 < -0.2 else 0
    sma = gn('fiftyDayAverage')
    if sma and curr_p and sma > 0:
        pv = (curr_p - sma) / sma
        mom += 3 if pv > 0.1 else 1 if pv > 0 else -2 if pv < -0.1 else 0
    beta = gn('beta')
    if beta and 0 < beta < 1.0: mom += 2
    
    # Confidence (0-5)
    mc = gn('marketCap')
    conf = 0
    if mc: conf += 2 if mc > 100e9 else 1 if mc > 10e9 else 0
    ip = gn('heldByInstitutionsPercentage')
    if ip: conf += 2 if ip > 0.5 else 1 if ip > 0.2 else 0
    try: nc = len(t.news) if t.news else 0
    except: nc = 0
    if nc > 0: conf += 1
    
    total = val + gr + pr + anl_s + mom + conf
    return {
        'ticker': data['ticker'],
        'company_name': info.get('shortName') or info.get('longName') or data['ticker'],
        'sector': info.get('sector') or 'Unknown',
        'industry': info.get('industry') or 'Unknown',
        'total_score': round(total, 1),
        'score_breakdown': {'valuation': val, 'growth': gr, 'profitability': pr,
                           'analyst': anl_s, 'momentum': mom, 'confidence': conf},
        'pe_ratio': t_pe, 'forward_pe': f_pe,
        'revenue_growth': rg, 'gross_margin': gm,
        'profit_margin': op, 'roe': roe, 'market_cap': mc,
        'analyst_buy_ratio': (sb + b) / tot if tot > 0 else None,
        'total_recs': tot,
        'upside_to_target': ((mean_t - curr_p) / curr_p) if (curr_p and mean_t and curr_p > 0) else None,
        'current_price': curr_p, 'mean_target': mean_t,
        'week52_change': wk52, 'beta': beta, 'inst_pct': ip,
        'earnings_growth': eg,
        'score_components': {'val': val, 'gr': gr, 'pr': pr, 'anl': anl_s, 'mom': mom, 'conf': conf}
    }

def load_cached():
    """Load cached scored results if available."""
    try:
        with open(OUTPUT_FILE) as f:
            d = json.load(f)
        scored = {s['ticker']: s for s in d.get('all_scored', d.get('top_50', []))}
        log(f"📦 Loaded {len(scored)} cached scores")
        return scored
    except:
        return {}

def fetch_all_tickers(tickers, cached, resume=True):
    """Fetch data for all tickers with batching and rate limit protection."""
    remaining = [t for t in tickers if t not in cached]
    all_data = list(cached.values())
    
    log(f"📊 Total: {len(tickers)} tickers | Cached: {len(cached)} | To fetch: {len(remaining)}")
    
    if not remaining:
        return all_data
    
    total_batches = (len(remaining) + 49) // 50
    for batch_start in range(0, len(remaining), 50):
        batch = remaining[batch_start:batch_start + 50]
        batch_num = batch_start // 50 + 1
        log(f"  Batch {batch_num}/{total_batches}: {batch[0]}...{batch[-1]}")
        
        batch_results = {}
        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as ex:
            futures = {ex.submit(fetch_ticker_data, t): t for t in batch}
            for future in as_completed(futures):
                result = future.result()
                if result and result.get('success'):
                    batch_results[result['ticker']] = result
        
        for ticker in batch:
            if ticker in batch_results:
                scored = score_stock(batch_results[ticker])
                if scored:
                    all_data.append(scored)
        
        log(f"    → {len(all_data)} scored so far. Sleeping {BATCH_DELAY}s...")
        time.sleep(BATCH_DELAY)
    
    return all_data

def rank_and_print(all_data):
    """Rank and print the top 50 stocks."""
    all_data.sort(key=lambda x: x.get('total_score', 0), reverse=True)
    top50 = all_data[:TOP_N]
    
    # Save
    with open(OUTPUT_FILE, 'w') as f:
        json.dump({'top_50': top50, 'all_scored': all_data, 'total': len(all_data)}, f, indent=2, default=str)
    
    print("\n" + "="*85)
    print(f"🏆 TOP {TOP_N} RUSSELL 1000 STOCKS — {time.strftime('%Y-%m-%d %H:%M')}")
    print("="*85)
    print(f"{'Rank':4s} {'Ticker':6s} {'Company':36s} {'Score':6s} {'Val':3s} {'Gr':3s} {'Pr':3s} {'Anl':3s} {'Mom':3s} {'Conf':3s}  Key Metrics")
    print("-"*85)
    
    for i, s in enumerate(top50, 1):
        sc = s.get('score_components', {})
        val_s = sc.get('val', 0)
        gr_s = sc.get('gr', 0)
        pr_s = sc.get('pr', 0)
        anl_s = sc.get('anl', 0)
        mom_s = sc.get('mom', 0)
        conf_s = sc.get('conf', 0)
        
        pe = s.get('pe_ratio')
        rg = s.get('revenue_growth')
        gm = s.get('gross_margin')
        up = s.get('upside_to_target')
        price = s.get('current_price')
        
        metrics = []
        if pe: metrics.append(f"PE={pe:.0f}")
        if rg is not None: metrics.append(f"RevG={rg*100:.0f}%")
        if gm is not None: metrics.append(f"GM={gm*100:.0f}%")
        if up is not None: metrics.append(f"Upside={up*100:.0f}%")
        if price: metrics.append(f"${price:.2f}")
        mc = s.get('market_cap', 0)
        if mc:
            if mc >= 1e12: metrics.append(f"MC=${mc/1e12:.1f}T")
            elif mc >= 1e9: metrics.append(f"MC=${mc/1e9:.0f}B")
        
        name = s.get('company_name', s['ticker'])[:36]
        print(f"#{i:2d} {s['ticker']:6s} {name:36s} {s['total_score']:5.1f}  {val_s:2d}  {gr_s:2d}  {pr_s:2d}  {anl_s:2d}  {mom_s:2d}  {conf_s:2d}  {' | '.join(metrics)}")
    
    return top50, all_data

def print_summary(top50, all_data):
    """Print investment summary with buy zones."""
    print(f"\n\n{'='*85}")
    print("📋 INVESTMENT SUMMARY")
    print("="*85)
    
    # Load analyst targets for top stocks
    top_tickers = [s['ticker'] for s in top50[:20]]
    targets_data = {}
    
    for ticker in top_tickers:
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}
            mean_t = info.get('targetMeanPrice')
            curr_p = info.get('currentPrice') or info.get('regularMarketPrice')
            if mean_t and curr_p:
                targets_data[ticker] = {
                    'price': curr_p,
                    'mean_target': mean_t,
                    'high_target': info.get('targetHighPrice'),
                    'low_target': info.get('targetLowPrice'),
                    'upside': (mean_t - curr_p) / curr_p,
                    'earnings_growth': info.get('earningsGrowth') or info.get('revenueGrowth') or 0,
                    'beta': info.get('beta') or 1.0,
                }
        except:
            pass
        time.sleep(0.2)
    
    for ticker in top_tickers[:15]:
        t = targets_data.get(ticker)
        if not t:
            # Try from scored data
            for s in top50:
                if s['ticker'] == ticker:
                    up = s.get('upside_to_target')
                    price = s.get('current_price') or 0
                    mean_t = s.get('mean_target')
                    if mean_t and price:
                        t = {
                            'price': price,
                            'mean_target': mean_t,
                            'upside': up,
                            'earnings_growth': s.get('earnings_growth') or 0,
                            'beta': s.get('beta') or 1.0,
                        }
                    break
        
        if not t:
            # Find in scored data
            for s in top50:
                if s['ticker'] == ticker:
                    t = {'price': s.get('current_price') or 0, 'mean_target': s.get('mean_target'),
                         'upside': s.get('upside_to_target'), 'earnings_growth': s.get('earnings_growth') or 0,
                         'beta': s.get('beta') or 1.0}
                    break
        
        if not t:
            continue
        
        price = t.get('price', 0) or 0
        mean_t = t.get('mean_target') or 0
        up = t.get('upside') or 0
        eg = t.get('earnings_growth') or 0
        beta = t.get('beta') or 1.0
        if isinstance(eg, str): eg = 0
        
        up6m = up / 2 if up else 0
        up1y = up + eg if (up and eg) else (up if up else 0)
        ideal_buy = mean_t * 0.85 if mean_t else 0
        
        if mean_t and price:
            ideal_pct = (mean_t - price) / mean_t * 100 if mean_t else 0
        else:
            ideal_pct = 0
        
        buy_status = "✅ BUY ZONE" if (mean_t and price <= mean_t * 0.90) else "⚠️  WAIT" if (mean_t and price > mean_t) else "📍 NEAR TARGET"
        
        for s in top50:
            if s['ticker'] == ticker:
                company = s.get('company_name', ticker)[:30]
                pe = s.get('pe_ratio') or 0
                rg = s.get('revenue_growth') or 0
                rg_s = f"{rg*100:.0f}%" if rg is not None else "N/A"
                break
        else:
            company = ticker
            pe = 0; rg_s = "N/A"
        
        print(f"  {ticker:6s} | {company:30s} | ${price:.2f} → ${mean_t:.2f if mean_t else 0} ({up*100:+.1f}%) | 6M:{up6m*100:+.1f}% 1Y:{up1y*100:+.1f}% | PE={pe:.0f} RevG={rg_s} | {buy_status}")
    
    print(f"\n✅ Results saved to: {OUTPUT_FILE}")
    print(f"✅ Total stocks scored: {len(all_data)}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    log("🚀 Russell 1000 Screener starting...")
    
    # Check environment
    check_env()
    
    # Step 1: Get tickers
    tickers = get_russell_tickers()
    if not tickers:
        log("❌ No tickers found. Exiting.")
        return
    
    # Step 2: Load cache and fetch remaining
    cached = load_cached()
    all_data = fetch_all_tickers(tickers, cached)
    
    if not all_data:
        log("❌ No data fetched. Check rate limits and retry.")
        return
    
    # Step 3: Rank and print
    top50, all_scored = rank_and_print(all_data)
    
    # Step 4: Summary with targets
    print_summary(top50, all_scored)

if __name__ == '__main__':
    main()