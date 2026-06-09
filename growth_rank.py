"""
Growth Ranking v2 — composite growth score with 6M/1Y price targets and buy zones.
"""
import json, os

stocks = [
    {'t': 'AU',    'p': 91.61,  'tgt': 123.29, 'rg': 65,  'eg': 185, 'fpe': 8.4,  'peg': 0.78, 'beta': 0.62, 'dcf': 772,  'scr': 74, 'n': 'AngloGold Ashanti'},
    {'t': 'AR',    'p': 36.40,  'tgt': 50.35,  'rg': 34,  'eg': 161, 'fpe': 7.8,  'peg': 0.64, 'beta': 0.36, 'dcf': 674,  'scr': 61, 'n': 'Antero Resources'},
    {'t': 'EXE',   'p': 91.66,  'tgt': 130.04, 'rg': 41,  'eg': 0,    'fpe': 9.5,  'peg': 21.4, 'beta': 0.35, 'dcf': 556,  'scr': 64, 'n': 'Exelixis'},
    {'t': 'CF',    'p': 113.73, 'tgt': 126.53, 'rg': 19,  'eg': 115, 'fpe': 10.2, 'peg': 3.34, 'beta': 0.42, 'dcf': 394,  'scr': 62, 'n': 'CF Industries'},
    {'t': 'NVDA',  'p': 223.11, 'tgt': 296.81, 'rg': 85,  'eg': 214, 'fpe': 17.6, 'peg': 0.69, 'beta': 2.24, 'dcf': 11,   'scr': 64, 'n': 'NVIDIA'},
    {'t': 'INCY',  'p': 93.13,  'tgt': 107.96, 'rg': 21,  'eg': 84,  'fpe': 10.3, 'peg': 0.36, 'beta': 0.80, 'dcf': 143,  'scr': 73, 'n': 'Incyte Corp'},
    {'t': 'HALO',  'p': 66.32,  'tgt': 83.90,  'rg': 42,  'eg': 31,  'fpe': 6.7,  'peg': 0.00, 'beta': 0.88, 'dcf': 108,  'scr': 65, 'n': 'Halozyme Therapeutics'},
    {'t': 'GMED',  'p': 78.96,  'tgt': 110.00, 'rg': 27,  'eg': 67,  'fpe': 15.3, 'peg': 1.49, 'beta': 1.00, 'dcf': 132,  'scr': 59, 'n': 'Globus Medical'},
    {'t': 'EVR',   'p': 345.77, 'tgt': 374.60, 'rg': 100, 'eg': 107, 'fpe': 15.0, 'peg': 1.55, 'beta': 1.49, 'dcf': 1046, 'scr': 59, 'n': 'Evercore'},
    {'t': 'CPAY',  'p': 359.57, 'tgt': 389.79, 'rg': 25,  'eg': 49,  'fpe': 11.7, 'peg': 0.88, 'beta': 0.82, 'dcf': 86,   'scr': 61, 'n': 'Corpay'},
    {'t': 'APA',   'p': 38.27,  'tgt': 43.27,  'rg': -12, 'eg': 32,  'fpe': 9.0,  'peg': 0.65, 'beta': 0.37, 'dcf': 37,   'scr': 59, 'n': 'APA Corp'},
    {'t': 'GEN',   'p': 27.12,  'tgt': 30.01,  'rg': 27,  'eg': 265, 'fpe': 8.3,  'peg': 1.59, 'beta': 1.09, 'dcf': 10,   'scr': 66, 'n': 'Gen Digital'},
    {'t': 'AMG',   'p': 310.44, 'tgt': 381.00, 'rg': 10,  'eg': 74,  'fpe': 7.9,  'peg': 0.92, 'beta': 1.14, 'dcf': 22,   'scr': 63, 'n': 'Affiliated Managers'},
    {'t': 'APP',   'p': 603.12, 'tgt': 648.10, 'rg': 59,  'eg': 113, 'fpe': 27.5, 'peg': 1.69, 'beta': 2.37, 'dcf': -31,  'scr': 59, 'n': 'AppLovin'},
    {'t': 'FSLR',  'p': 307.97, 'tgt': 243.59, 'rg': 24,  'eg': 65,  'fpe': 13.2, 'peg': 0.80, 'beta': 1.56, 'dcf': -22,  'scr': 66, 'n': 'First Solar'},
    {'t': 'QCOM',  'p': 240.78, 'tgt': 177.10, 'rg': -4,  'eg': 173, 'fpe': 22.6, 'peg': 0.96, 'beta': 1.49, 'dcf': -48,  'scr': 59, 'n': 'Qualcomm'},
]

def gscore(s):
    rev = max(0, s['rg']) / 65 * 25 if s['rg'] >= 0 else max(0, 5 - abs(s['rg']) / 5)
    earn = min(25, max(0, s['eg']) / 200 * 25)
    if s['tgt']:
        upside = (s['tgt'] - s['p']) / s['p'] * 100
        anl = max(0, min(20, upside / 40 * 20))
    else:
        anl = 7
    if s['dcf'] > 0:
        dcf = max(0, min(15, s['dcf'] / 200 * 15))
    else:
        dcf = max(-5, s['dcf'] / 50 * 5)
    peg = s['peg']
    if peg <= 0 or peg > 10:
        pscore = 0
    elif peg < 0.3:
        pscore = 10
    elif peg < 0.5:
        pscore = 8
    elif peg < 0.8:
        pscore = 6
    elif peg < 1.2:
        pscore = 4
    elif peg < 2.0:
        pscore = 2
    else:
        pscore = 0.5
    b = s['beta']
    if b <= 0.5:
        bb = 5
    elif b <= 0.8:
        bb = 3
    elif b <= 1.0:
        bb = 1
    elif b <= 1.5:
        bb = -1
    elif b <= 2.0:
        bb = -3
    else:
        bb = -5
    total = rev + earn + anl + dcf + pscore + bb
    return {
        'rev': round(rev, 1), 'earn': round(earn, 1), 'anl': round(anl, 1),
        'dcf': round(dcf, 1), 'peg': round(pscore, 1), 'beta': bb, 'total': round(total, 1)
    }

def targets(s):
    p = s['p']
    tgt = s['tgt']
    t6m = ((p + tgt) / 2) if tgt else p * 1.10
    r1y = round((tgt - p) / p * 100, 1) if tgt else None
    r6m = round((t6m - p) / p * 100, 1)
    entry_ideal = p * 0.85
    entry_max = p * 0.92
    if s['dcf'] < -30:
        action = 'AVOID'
    elif p <= entry_max and (r1y or 0) > 15:
        action = 'STRONG BUY'
    elif p <= entry_max and (r1y or 0) > 5:
        action = 'BUY'
    elif p <= entry_ideal:
        action = 'BUY on DIP'
    elif (r1y or 0) > 20:
        action = 'HOLD-rich'
    else:
        action = 'WAIT'
    return {
        't6m': round(t6m, 2), 't1y': round(tgt, 2) if tgt else None,
        'r6m': r6m, 'r1y': r1y,
        'eid': round(entry_ideal, 2), 'emx': round(entry_max, 2),
        'action': action
    }

for s in stocks:
    s['_g'] = gscore(s)
    s['_t'] = targets(s)

ranked = sorted(stocks, key=lambda x: -x['_g']['total'])

print("=" * 110)
print("TOP GROWTH STOCKS — Next 6M & 1Y Price Targets + Buy Zones")
print("=" * 110)
hdr = "{:<4} {:<6} {:<20} {:<6} {:<5} {:<5} {:<7} {:<7} {:<5} {:<5} {:<8} {:<8}"
print(hdr.format('#', 'Ticker', 'Name', 'G-Sc', 'RevG', 'ErnG', '1YRet%', 'DCFup%', 'PEG', 'Beta', '6MRet%', 'Price'))
print("-" * 110)
for i, s in enumerate(ranked, 1):
    g = s['_g']
    t = s['_t']
    r1y = str(t['r1y']) + '%' if t['r1y'] else 'N/A'
    r6m = str(t['r6m']) + '%'
    dcf_s = str(s['dcf']) + '%'
    row = "{:<4} {:<6} {:<20} {:<6.1f} {:<5.0f} {:<5.0f} {:<7} {:<7} {:<5.2f} {:<5.2f} {:<8} ${:<7.2f}"
    print(row.format(i, s['t'], s['n'][:19], g['total'], s['rg'], s['eg'], r1y, dcf_s, s['peg'], s['beta'], r6m, s['p']))

print("=" * 110)
print("")
print("BUY ZONES:")
hdr2 = "{:<6} {:<7} {:<11} {:<9} {:<9} {:<14} {:<15} {:<8}"
print(hdr2.format('Ticker', 'Price', 'EntryIdeal', '6MTarget', '1YTarget', 'DCFIntrinsic', 'Action', '1YRet%'))
print("-" * 100)
for s in ranked[:15]:
    t = s['_t']
    dcf_int = str(round(s['p'] * (1 + s['dcf']/100), 2)) if s['dcf'] > 0 else 'N/A'
    r1y = (str(t['r1y']) + '%') if t['r1y'] else 'N/A'
    t1y_s = ('$' + str(t['t1y'])) if t['t1y'] else 'N/A'
    row2 = "{:<6} ${:<6.2f} ${:<10.2f} ${:<8.2f} {:<9} {:<14} {:<15} {:<8}"
    print(row2.format(s['t'], s['p'], t['eid'], t['t6m'], t1y_s, dcf_int, t['action'], r1y))

print("=" * 110)

os.makedirs('data', exist_ok=True)
output = {
    'generated_at': '2026-06-02',
    'rankings': [
        {
            'rank': i+1, 'ticker': s['t'], 'name': s['n'], 'price': s['p'],
            'growth_score': s['_g']['total'],
            'analyst_target': s['tgt'],
            'dcf_upside': s['dcf'],
            'dcf_intrinsic': round(s['p'] * (1 + s['dcf']/100), 2) if s['dcf'] > 0 else None,
            'entry_ideal': s['_t']['eid'], 'entry_max': s['_t']['emx'],
            'target_6m': s['_t']['t6m'], 'target_1y': s['_t']['t1y'],
            'return_6m': s['_t']['r6m'], 'return_1y': s['_t']['r1y'],
            'revenue_growth': s['rg'], 'earnings_growth': s['eg'],
            'forward_pe': s['fpe'], 'peg': s['peg'], 'beta': s['beta'],
            'screener_score': s['scr'], 'action': s['_t']['action'],
        }
        for i, s in enumerate(ranked)
    ]
}
with open('data/growth_ranking.json', 'w') as f:
    json.dump(output, f, indent=2)
print("\nSaved to data/growth_ranking.json")

print("\n\n=== TOP 10 GROWTH STOCKS ===")
for i, s in enumerate(ranked[:10], 1):
    t = s['_t']
    r1y = (str(t['r1y']) + '%') if t['r1y'] else 'N/A'
    print(f"#{i} {s['t']} ({s['n']}): G-Score={s['_g']['total']:.1f} | RevG={s['rg']}% | EarnG={s['eg']}% | 1Y={r1y} | Target=${t['t1y']} | EntryIdeal=${t['eid']} | {t['action']}")