"""
Growth Ranking Generator v2
Combines: screener score + DCF + analyst targets + fundamentals
Output: ranked growth stocks with 6M/1Y price targets and buy zones
"""
import json

stocks = [
    {'ticker':'AU',    'price':91.61, 'target':123.29, 'rev_g':65,  'earn_g':185, 'fpe':8.4,  'peg':0.78, 'beta':0.62, 'dcf_up':772,  'score':74, 'name':'AngloGold Ashanti'},
    {'ticker':'AR',    'price':36.40, 'target':50.35,  'rev_g':34,  'earn_g':161, 'fpe':7.8,  'peg':0.64, 'beta':0.36, 'dcf_up':674,  'score':61, 'name':'Antero Resources'},
    {'ticker':'EXE',   'price':91.66, 'target':130.04, 'rev_g':41,  'earn_g':0,   'fpe':9.5,  'peg':21.4, 'beta':0.35, 'dcf_up':556,  'score':64, 'name':'Exelixis'},
    {'ticker':'CF',    'price':113.73,'target':126.53, 'rev_g':19,  'earn_g':115, 'fpe':10.2, 'peg':3.34, 'beta':0.42, 'dcf_up':394,  'score':62, 'name':'CF Industries'},
    {'ticker':'NVDA',  'price':223.11,'target':296.81, 'rev_g':85,  'earn_g':214, 'fpe':17.6, 'peg':0.69, 'beta':2.24, 'dcf_up':11,   'score':64, 'name':'NVIDIA'},
    {'ticker':'INCY',  'price':93.13, 'target':107.96,'rev_g':21,  'earn_g':84,  'fpe':10.3, 'peg':0.36, 'beta':0.80, 'dcf_up':143,  'score':73, 'name':'Incyte Corp'},
    {'ticker':'HALO',  'price':66.32, 'target':83.90,  'rev_g':42,  'earn_g':31,  'fpe':6.7,  'peg':0.00, 'beta':0.88, 'dcf_up':108,  'score':65, 'name':'Halozyme Therapeutics'},
    {'ticker':'GMED',  'price':78.96, 'target':110.00, 'rev_g':27,  'earn_g':67,  'fpe':15.3, 'peg':1.49, 'beta':1.00, 'dcf_up':132,  'score':59, 'name':'Globus Medical'},
    {'ticker':'EVR',   'price':345.77,'target':374.60, 'rev_g':100, 'earn_g':107, 'fpe':15.0, 'peg':1.55, 'beta':1.49, 'dcf_up':1046, 'score':59, 'name':'Evercore'},
    {'ticker':'CPAY',  'price':359.57,'target':389.79, 'rev_g':25,  'earn_g':49,  'fpe':11.7, 'peg':0.88, 'beta':0.82, 'dcf_up':86,   'score':61, 'name':'Corpay'},
    {'ticker':'APA',   'price':38.27, 'target':43.27,  'rev_g':-12, 'earn_g':32,  'fpe':9.0,  'peg':0.65, 'beta':0.37, 'dcf_up':37,   'score':59, 'name':'APA Corp'},
    {'ticker':'GEN',   'price':27.12, 'target':30.01,  'rev_g':27,  'earn_g':265, 'fpe':8.3,  'peg':1.59, 'beta':1.09, 'dcf_up':10,   'score':66, 'name':'Gen Digital'},
    {'ticker':'AMG',   'price':310.44,'target':381.00, 'rev_g':10,  'earn_g':74,  'fpe':7.9,  'peg':0.92, 'beta':1.14, 'dcf_up':22,   'score':63, 'name':'Affiliated Managers'},
    {'ticker':'APP',   'price':603.12,'target':648.10, 'rev_g':59,  'earn_g':113, 'fpe':27.5, 'peg':1.69, 'beta':2.37, 'dcf_up':-31,  'score':59, 'name':'AppLovin'},
    {'ticker':'FSLR',  'price':307.97,'target':243.59, 'rev_g':24,  'earn_g':65,  'fpe':13.2, 'peg':0.80, 'beta':1.56, 'dcf_up':-22,  'score':66, 'name':'First Solar'},
    {'ticker':'QCOM',  'price':240.78,'target':177.10, 'rev_g':-4,  'earn_g':173, 'fpe':22.6, 'peg':0.96, 'beta':1.49, 'dcf_up':-48,  'score':59, 'name':'Qualcomm'},
]

def composite_growth_score(s):
    """Growth composite score: Rev(25) + Earn(25) + Analyst(20) + DCF(15) + PEG quality(10) + Beta bonus(-5 to +5)"""
    # Revenue growth: 0-25, normalized to 65% = max
    if s['rev_g'] >= 0:
        rev_score = min(25, s['rev_g'] / 65 * 25)
    else:
        rev_score = max(0, 5 - abs(s['rev_g']) / 5)  # negative rev_g penalized

    # Earnings growth: 0-25, normalized to 200% = max
    earn_score = min(25, max(0, s['earn_g']) / 200 * 25)

    # Analyst upside: 0-20, 40% upside = max
    if s['target']:
        upside = (s['target'] - s['price']) / s['price'] * 100
        anl_score = max(0, min(20, upside / 40 * 20))
    else:
        anl_score = 7  # neutral

    # DCF upside: 0-15, 200% = max
    dcf_score = max(0, min(15, s['dcf_up'] / 200 * 15)) if s['dcf_up'] > 0 else max(0, s['dcf_up'] / 50 * 5)

    # PEG quality: lower = better
    peg = s['peg']
    if peg <= 0 or peg > 10:
        peg_score = 0
    elif peg < 0.3:
        peg_score = 10
    elif peg < 0.5:
        peg_score = 8
    elif peg < 0.8:
        peg_score = 6
    elif peg < 1.2:
        peg_score = 4
    elif peg < 2.0:
        peg_score = 2
    else:
        peg_score = 0.5

    # Beta risk bonus: low beta = bonus, high beta = penalty
    beta = s['beta']
    if beta <= 0.5:
        beta_bonus = 5
    elif beta <= 0.8:
        beta_bonus = 3
    elif beta <= 1.0:
        beta_bonus = 1
    elif beta <= 1.5:
        beta_bonus = -1
    elif beta <= 2.0:
        beta_bonus = -3
    else:
        beta_bonus = -5

    total = rev_score + earn_score + anl_score + dcf_score + peg_score + beta_bonus
    return {
        'rev_score': round(rev_score, 1),
        'earn_score': round(earn_score, 1),
        'anl_score': round(anl_score, 1),
        'dcf_score': round(dcf_score, 1),
        'peg_score': round(peg_score, 1),
        'beta_bonus': beta_bonus,
        'total': round(total, 1),
    }

def calc_targets(s):
    """Calculate 6M and 1Y price targets."""
    price = s['price']
    tgt = s['target']

    # Analyst consensus: annual target
    tgt_1y = tgt if tgt else None

    # 6M conservative: average of current and 1Y target
    tgt_6m_cons = ((price + tgt_1y) / 2) if tgt_1y else price * 1.10

    # 6M aggressive: just the 1Y target (if bullish)
    tgt_6m_agg = tgt_1y if tgt_1y else price * 1.15

    # 1Y conservative: 80% of analyst target
    tgt_1y_cons = tgt_1y * 0.80 if tgt_1y else price * 1.20

    return {
        'target_6m_conservative': round(tgt_6m_cons, 2),
        'target_6m_aggressive': round(tgt_6m_agg, 2),
        'target_1y': round(tgt_1y, 2) if tgt_1y else None,
        'target_1y_conservative': round(tgt_1y_cons, 2),
        'ret_6m_conservative': round((tgt_6m_cons - price) / price * 100, 1),
        'ret_6m_aggressive': round((tgt_6m_agg - price) / price * 100, 1),
        'ret_1y': round((tgt_1y - price) / price * 100, 1) if tgt_1y else None,
        'ret_1y_conservative': round((tgt_1y_cons - price) / price * 100, 1),
    }

def get_action(s, t):
    """Determine BUY/HOLD/WAIT based on current price vs ideal entry."""
    price = s['price']

    # Entry ideal: 15% below current (already at discount if lower than current)
    entry_ideal = price * 0.85
    entry_max = price * 0.92  # 8% below current

    # Check DCF for overvaluation
    if s['dcf_up'] < -30:
        return 'AVOID ⚠️ DCF overvalued', entry_ideal

    ret_1y = t.get('ret_1y', 0) or 0

    if price <= entry_max and ret_1y > 15:
        return '✅ STRONG BUY', entry_ideal
    elif price <= entry_max and ret_1y > 5:
        return '✅ BUY', entry_ideal
    elif price <= entry_ideal:
        return '🟡 BUY on DIP', entry_ideal
    elif ret_1y > 20:
        return '🟡 HOLD — rich entry', entry_ideal
    else:
        return '⚠️ WAIT — not at entry', entry_max


# Compute all metrics
for s in stocks:
    s['gscore'] = composite_growth_score(s)
    s['targets'] = calc_targets(s)
    action, entry = get_action(s, s['targets'])
    s['action'] = action
    s['entry_ideal'] = entry

# Sort by growth score
ranked = sorted(stocks, key=lambda x: -x['gscore']['total'])

# ── Print Report ─────────────────────────────────────────────────────────────
print('\n' + '='*110)
print('📊  GROWTH RANKING  |  Next 6M & 1Y Price Targets + Buy Zones')
print('    Composite Score: Rev Growth(25) + Earn Growth(25) + Analyst Upside(20) + DCF(15) + PEG Quality(10) + Beta Bonus(5)')
print('='*110)

print(f"\n{'Rank':<5} {'Ticker':<6} {'Name':<22} {'G-Score':<9} {'Rev%':<6} {'Ern%':<6} {'AnlUps':<8} {'DCFup':<7} {'PEG':<5} {'β':<5} {'1Y Ret%':<8} {'6M Ret%':<8} {'Price':<8}")
print('-'*110)

for rank, s in enumerate(ranked, 1):
    g = s['gscore']
    t = s['targets']
    upside_pct = f"{t['ret_1y']:+.0f}%" if t.get('ret_1y') else "N/A"
    ret6m_str = f"{t['ret_6m_conservative']:+.0f}%"
print(f"#{rank:<4} {s['ticker']:<6} {s['name'][:20]:<22} {g['total']:<9.1f} "
          f"{s['rev_g']:<6.0f} {s['earn_g']:<6.0f} "
          f"{f\"{t['ret_1y']:+.0f}%\" if t.get('ret_1y') else 'N/A':<8} "
          f"{s['dcf_up']:<+7.0f} "
          f"{s['peg']:<5.2f} {s['beta']:<5.2f} "
          f"{upside_pct:<8} "
          f"{ret6m_str:<8} "
          f"${s['price']:<7.2f}")

print('='*110)

# ── Buy Zones ─────────────────────────────────────────────────────────────────
print('\n💰  BUY ZONES & PRICE TARGETS')
print(f"{'Ticker':<6} {'Price':<8} {'Entry Ideal':<12} {'Max Entry':<10} {'6M Target':<12} {'1Y Target':<12} {'1Y Return':<10} {'DCF Intrinsic':<14} {'Action'}")
print('-'*115)

for rank, s in enumerate(ranked[:15], 1):
    t = s['targets']
    price = s['price']
    entry_ideal = round(s['entry_ideal'], 2)
    entry_max = round(price * 0.92, 2)

    dcf_intrinsic = round(price * (1 + s['dcf_up']/100), 2) if s['dcf_up'] > 0 else None

    tgt_6m = t['target_6m_aggressive']
    tgt_1y = t['target_1y'] or t['target_1y_conservative']
    ret_1y = t.get('ret_1y') or t.get('ret_1y_conservative')
    ret_str = f"{ret_1y:+.0f}%" if ret_1y else "N/A"
    dcf_str = f"${dcf_intrinsic}" if dcf_intrinsic else "N/A"
    dcf_up_str = f"({s['dcf_up']:+.0f}%)"

    print(f"{s['ticker']:<6} ${price:<7.2f} ${entry_ideal:<11.2f} ${entry_max:<9.2f} "
          f"${tgt_6m:<11.2f} ${tgt_1y:<11.2f} "
          f"{ret_str:<10} {dcf_str:<14} {s['action']}")

print('='*115)

# ── Save JSON ─────────────────────────────────────────────────────────────────
output = {
    'generated_at': '2026-06-02',
    'methodology': 'Growth composite: Rev(25) + Earn(25) + Analyst(20) + DCF(15) + PEG(10) + Beta bonus(5)',
    'top15': [
        {
            'rank': r+1,
            'ticker': s['ticker'],
            'name': s['name'],
            'price': s['price'],
            'growth_score': s['gscore']['total'],
            'score_breakdown': {k: v for k, v in s['gscore'].items()},
            'analyst_target': s['target'],
            'dcf_upside': s['dcf_up'],
            'dcf_intrinsic': round(s['price'] * (1 + s['dcf_up']/100), 2) if s['dcf_up'] > 0 else None,
            'entry_ideal': round(s['entry_ideal'], 2),
            'entry_max': round(s['price'] * 0.92, 2),
            'target_6m': s['targets']['target_6m_aggressive'],
            'target_1y': s['targets']['target_1y'] or s['targets']['target_1y_conservative'],
            'return_6m': s['targets']['ret_6m_conservative'],
            'return_1y': s['targets'].get('ret_1y') or s['targets']['ret_1y_conservative'],
            'revenue_growth': s['rev_g'],
            'earnings_growth': s['earn_g'],
            'forward_pe': s['fpe'],
            'peg': s['peg'],
            'beta': s['beta'],
            'screener_score': s['score'],
            'action': s['action'],
        }
        for r, s in enumerate(ranked[:15])
    ]
}

with open('data/growth_ranking.json', 'w') as f:
    json.dump(output, f, indent=2)
print(f"\nSaved to data/growth_ranking.json")

# ── Summary insights ──────────────────────────────────────────────────────────
print('\n🔍 KEY INSIGHTS:')
print('─'*60)

insights = [
    ('AR', 'BEST VALUE-GROWTH: RevG 34% + EarnG 161% + PEG 0.64 + β 0.36. Low beta + exceptional growth + cheap = rare combo. Target $50, entry < $33.'),
    ('EXE', 'HYPERGROWTH at PE 9.5x: RevG 41% + DCF +556% upside. PEG 21x is misleading (EarnG=0 is accounting lag, not business lag). Target $130, entry < $83.'),
    ('AU', 'GOLD + AI TAILWIND: RevG 65% + EarnG 185% + PE 8.4x + PEG 0.78. Best growth-for-price in the ranking. Target $123, entry < $83.'),
    ('HALO', 'BEST RISK-ADJUSTED GROWTH: RevG 42% + PE 6.7x + β 0.88. The cheapest growth in healthcare/biotech. Target $84, entry < $60.'),
    ('CF', 'DEEP VALUE + NITROGEN CYCLE: EarnG 115% + PE 10.2x + DCF +394%. Agriculture play with AI-driven precision farming tailwinds. Target $127, entry < $104.'),
    ('INCY', 'ONCOLOGY COMPOUNDER: RevG 21% + EarnG 84% + PEG 0.36 (cheap for growth). Solid pipeline, low beta. Target $108, entry < $84.'),
    ('NVDA', 'AI INFRASTRUCTURE MOAT: RevG 85% + EarnG 214% — the actual AI beneficiary. High beta (2.24) = volatility but institutional ownership = stability. Target $297, but WAIT for <$210.'),
    ('GMED', 'SPINE GROWTH PLAY: RevG 27% + EarnG 67% + DCF +132%. Cheap vs intrinsic. Target $110, entry < $72.'),
    ('CPAY', 'FLEET MANAGEMENT COMPOUNDER: RevG 25% + stable earng 49% + PE 11.7x. Moat in payment networks. Target $390, entry < $330.'),
    ('EVR', 'INVESTMENT BANKING RECOVERY: RevG 100% + EarnG 107% + DCF +1046%. IPO market recovery = direct beneficiary. Target $375, entry < $315.'),
]

for ticker, text in insights:
    print(f'  {ticker}: {text}')

print('\n⚠️  AVOID: QCOM (-48% DCF, -26% analyst target), FSLR (-22% DCF), APP (-31% DCF) — high PE with deteriorating fundamentals.')