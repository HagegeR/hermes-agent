import json

with open('russell_1000_scores_v2.json') as f:
    data = json.load(f)
top50 = data['top_50']

with open('updated_targets.json') as f:
    targets = json.load(f)

for i, s in enumerate(top50[:20], 1):
    t = targets.get(s['ticker'], {})
    price = t.get('current_price') or s.get('current_price') or 0
    mean_t = t.get('mean_target') or s.get('mean_target')
    high_t = t.get('high_target')
    low_t = t.get('low_target')
    up_mean = t.get('upside_mean') or s.get('upside_to_target')
    rg = s.get('revenue_growth', 0) or 0
    rg = rg if rg is not None else 0
    pe = s.get('pe_ratio') or 0
    fwd = s.get('forward_pe') or 0
    mc = s.get('market_cap') or 0
    eg = (t.get('earnings_growth') or s.get('earnings_growth') or 0)
    eg = eg if eg is not None else 0
    mc_s = f"${mc/1e12:.1f}T" if mc>=1e12 else f"${mc/1e9:.0f}B" if mc>=1e9 else ""
    up6 = up_mean/2*100 if up_mean else 0
    up1 = (up_mean + eg)*100 if (up_mean is not None and eg) else (up_mean*100 if up_mean else 0)
    sig = "BUY" if up_mean and up_mean > 0.1 else "SELL" if up_mean and up_mean < 0 else "HOLD"
    ideal = mean_t * 0.85 if mean_t else 0
    zone = "BUY ZONE" if price <= ideal * 1.05 else "WAIT"
    mean_s = f"{mean_t:.2f}" if mean_t else "N/A"
    print(f"#{i} {s['ticker']:5s} ${price:.2f} → ${mean_s} | {up_mean*100:+.1f}% | 6M:{up6:+.1f}% 1Y:{up1:+.1f}% | PE={pe:.0f} FwdPE={fwd:.0f} | RevG={rg*100:.0f}% | {sig} {zone} | MC={mc_s}")