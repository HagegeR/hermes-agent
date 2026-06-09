import json

with open('russell_1000_scores_v2.json') as f:
    data = json.load(f)
top50 = data['top_50']

with open('updated_targets.json') as f:
    targets = json.load(f)

for i, s in enumerate(top50[:20], 1):
    ticker = s['ticker']
    t = targets.get(ticker, {})
    
    price = t.get('current_price') or s.get('current_price') or 0
    mean_t = t.get('mean_target') or s.get('mean_target') or 0
    high_t = t.get('high_target') or 0
    low_t = t.get('low_target') or 0
    up_mean = t.get('upside_mean')
    if up_mean is None:
        up_mean = s.get('upside_to_target')
    up_mean = up_mean if up_mean is not None else 0
    
    rg = s.get('revenue_growth') or 0
    if rg is None: rg = 0
    pe = s.get('pe_ratio') or 0
    fwd = s.get('forward_pe') or 0
    mc = s.get('market_cap') or 0
    eg = (t.get('earnings_growth') or s.get('earnings_growth')) or 0
    if eg is None: eg = 0
    
    mc_s = f"${mc/1e12:.1f}T" if mc >= 1e12 else f"${mc/1e9:.0f}B" if mc >= 1e9 else ""
    
    up6 = up_mean / 2 * 100
    up1 = (up_mean + eg) * 100
    
    sig = "BUY" if up_mean > 0.1 else "SELL" if up_mean < 0 else "HOLD"
    ideal = mean_t * 0.85 if mean_t else 0
    zone = "BUY ZONE" if price <= ideal * 1.05 else "WAIT"
    mean_s = f"{mean_t:.2f}" if mean_t else "N/A"
    up_s = f"{up_mean*100:+.1f}%" if up_mean is not None else "N/A"
    
    print(f"#{i} {ticker:5s} | ${price:.2f} → ${mean_s} | {up_s} | 6M:{up6:+.1f}% 1Y:{up1:+.1f}% | PE={pe:.0f} Fwd={fwd:.0f} | RevG={rg*100:.0f}% | {sig} | {zone} | {mc_s}")