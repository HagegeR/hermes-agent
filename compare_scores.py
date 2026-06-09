import json
from collections import Counter

with open('russell_1000_scores.json') as f:
    curr = json.load(f)
with open('russell_1000_scores_v2.json') as f:
    prev = json.load(f)

ct = curr['top_50']
pt = prev['top_50']
ct_tickers = set(s['ticker'] for s in ct)
pt_tickers = set(s['ticker'] for s in pt)
new_set = ct_tickers - pt_tickers
drop_set = pt_tickers - ct_tickers
pd = {s['ticker']: s for s in pt}

print('=== NEW ENTRIES ===')
for s in ct:
    if s['ticker'] in new_set:
        i = ct.index(s)+1
        rg = f"{s['revenue_growth']*100:.1f}%" if s['revenue_growth'] else 'N/A'
        mc = f"${s['market_cap']/1e9:.0f}B" if s['market_cap'] else 'N/A'
        pe = f"{s['pe_ratio']:.1f}" if s['pe_ratio'] else 'N/A'
        gm = f"{s['gross_margin']*100:.0f}%" if s['gross_margin'] else 'N/A'
        print(f'#{i} {s["ticker"]:6s} score={s["total_score"]} PE={pe} RevG={rg} GM={gm} ${s["current_price"]} MC={mc}')

print()
print('=== DROPPED ===')
for s in pt:
    if s['ticker'] in drop_set:
        rg = f"{s['revenue_growth']*100:.1f}%" if s['revenue_growth'] else 'N/A'
        pe = f"{s['pe_ratio']:.1f}" if s['pe_ratio'] else 'N/A'
        print(f'  {s["ticker"]:6s} score={s["total_score"]} PE={pe} RevG={rg} ${s["current_price"]}')

print()
print('=== TOP 20 RANK MOVEMENT ===')
for s in ct[:20]:
    t = s['ticker']
    cs = s['total_score']
    prev_rank = None
    for i, ps in enumerate(pt):
        if ps['ticker'] == t:
            prev_rank = i+1; break
    curr_rank = ct.index(s)+1
    diff_rank = prev_rank - curr_rank if prev_rank else 0
    rg = f"{s['revenue_growth']*100:.0f}%" if s['revenue_growth'] else 'N/A'
    pe = f"{s['pe_ratio']:.0f}" if s['pe_ratio'] else 'N/A'
    sb = s.get('score_breakdown', {})
    mc = f"${s['market_cap']/1e9:.0f}B" if s['market_cap'] else 'N/A'
    arrow = chr(8593) if diff_rank > 0 else chr(8595) if diff_rank < 0 else '='
    prev_s = f'prev=#{prev_rank}' if prev_rank else 'NEW'
    print(f'#{curr_rank:2d} {t:6s} {arrow} {prev_s} | score={cs} | Val={sb.get("valuation",0)} Gr={sb.get("growth",0)} Pr={sb.get("profitability",0)} Anl={sb.get("analyst",0)} Mom={sb.get("momentum",0)} | PE={pe} RevG={rg} ${s["current_price"]} {mc}')

print()
sectors = Counter(s['sector'] for s in ct)
print('=== SECTOR BREAKDOWN TOP 50 ===')
for sec, cnt in sectors.most_common():
    print(f'  {sec}: {cnt}')

print()
print('=== TOP 10 BY ANALYST UPSIDE ===')
with_ups = [(s, s.get('upside_to_target', 0) or 0) for s in ct if s.get('upside_to_target')]
with_ups.sort(key=lambda x: x[1], reverse=True)
for s, up in with_ups[:10]:
    tgt = s.get('mean_target', 0) or 0
    pe = f"{s['pe_ratio']:.0f}" if s['pe_ratio'] else 'N/A'
    print(f'  {s["ticker"]}: {up*100:+.1f}% | target=${tgt:.2f} | ${s["current_price"]} | PE={pe}')

print()
print('=== BIGGEST SCORE CHANGES (>=2 pts) ===')
for s in ct:
    t = s['ticker']
    cs = s['total_score']
    ps_data = pd.get(t, {})
    ps = ps_data.get('total_score', 0)
    diff = cs - ps
    if abs(diff) >= 2:
        print(f'  {t}: {ps}->{cs} ({"+" if diff > 0 else ""}{diff})')

print(f'\nTotal: curr={curr["total"]}, prev={prev["total"]}')
