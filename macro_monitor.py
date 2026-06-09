"""
Macro Dashboard — key economic indicators via FRED API and direct data sources.
Usage: python3 macro_monitor.py [--api-key YOUR_FRED_KEY]
For basic data: no API key needed for most observations.
"""
import requests, json, time

# ─── INDICATOR DEFINITIONS ──────────────────────────────────────────────────
INDICATORS = {
    # Interest rates
    'Fed Funds Rate': {'code': 'DFF', 'unit': '%', 'inverse': False},
    '2Y Treasury':    {'code': 'DGS2', 'unit': '%', 'inverse': False},
    '10Y Treasury':  {'code': 'DGS10', 'unit': '%', 'inverse': False},
    'Yield Curve (10Y-2Y)': {'code': 'T10Y2Y', 'unit': 'bps', 'inverse': False},
    '30Y Mortgage': {'code': 'MORTGAGE30US', 'unit': '%', 'inverse': False},
    # Inflation
    'CPI YoY':          {'code': 'CPIAUCSL', 'unit': '%', 'inverse': False, 'transform': 'pct_change_12'},
    'Core CPI':         {'code': 'CPILFESL', 'unit': '%', 'inverse': False, 'transform': 'pct_change_12'},
    'PCE Inflation':    {'code': 'PCECTPI', 'unit': '%', 'inverse': False, 'transform': 'pct_change_12'},
    '5Y Breakeven':     {'code': 'T5YIE', 'unit': '%', 'inverse': False},
    # Growth
    'GDP QoQ':          {'code': 'AWHGDP', 'unit': '%', 'inverse': False},
    'ISM Manufacturing':{'code': 'MANEMP', 'unit': '', 'inverse': False},
    'Jobless Claims':   {'code': 'ICSA', 'unit': 'K', 'inverse': True},  # Lower = bullish
    'Consumer Confidence': {'code': 'PPI', 'unit': '', 'inverse': False},  # rough proxy
    # Risk
    'VIX':              {'code': 'VIXCLS', 'unit': '', 'inverse': True},  # Lower = bullish
    'IG Spread':        {'code': 'BAMLC0A0CMTY', 'unit': 'bps', 'inverse': True},  # Lower = bullish
    'HY Spread':        {'code': 'BAMLHYH0AEHYM', 'unit': 'bps', 'inverse': True},  # Lower = bullish
}

SIGNALS = {
    'Fed Funds Rate':    {'bull': [0, 3], 'bear': [6, 10], 'label': 'Rate Environment'},
    'CPI YoY':          {'bull': [0, 3], 'bear': [5, 100], 'label': 'Inflation'},
    'Yield Curve':      {'bull': [50, 500], 'bear': [-300, 0], 'label': 'Recession Risk'},
    'VIX':               {'bull': [0, 20], 'bear': [40, 100], 'label': 'Market Stress'},
    'ISM Manufacturing': {'bull': [50, 100], 'bear': [0, 45], 'label': 'Manufacturing'},
    'GDP QoQ':          {'bull': [0, 10], 'bear': [-10, 0], 'label': 'Growth'},
}

def get_fred(key, code):
    """Fetch current value from FRED API."""
    url = f'https://api.stlouisfed.org/fred/series/observations?series_id={code}&api_key={key}&file_type=json&limit=2&sort_order=desc'
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            obs = data.get('observations', [])
            if len(obs) >= 2:
                v1 = float(obs[0]['value'])
                v2 = float(obs[1]['value'])
                return v1, v2, obs[0]['date']
        elif resp.status_code == 400 and 'api_key' in resp.text:
            # Try without API key (basic endpoint)
            url2 = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}&vintage_date=latest'
            r2 = requests.get(url2, timeout=10)
            if r2.status_code == 200:
                lines = r2.text.strip().split('\n')
                if len(lines) >= 2:
                    last = lines[-1].split(',')
                    prev = lines[-2].split(',')
                    return float(last[1]), float(prev[1]), last[0]
    except Exception as e:
        print(f"    Warning: {e}")
    return None, None, None

def get_observation_direct(code):
    """Get current value directly from FRED graph endpoint (no API key needed)."""
    try:
        url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}&vintage_date=latest'
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            lines = resp.text.strip().split('\n')
            if len(lines) >= 2:
                last = lines[-1].split(',')
                prev = lines[-2].split(',')
                try:
                    v_curr = float(last[1]) if last[1] != '.' else None
                    v_prev = float(prev[1]) if prev[1] != '.' else None
                    return v_curr, v_prev, last[0]
                except:
                    pass
    except:
        pass
    return None, None, None

def get_m2():
    """Get M2 Money Supply (approximation)."""
    # M2 is weekly on Fridays
    return get_observation_direct('M2SL')

def get_sp500():
    """Get S&P 500 PE ratio (Shiller)."""
    return get_observation_direct('SP500')

def signal(name, value, indicator_info):
    """Determine if indicator is bullish/bearish for stocks."""
    if value is None:
        return 'N/A'
    
    # Check specific signals
    for key in SIGNALS:
        if key in name or key.replace('YoY', '').strip() in name:
            s = SIGNALS[key]
            if 'bull' in s and 'bear' in s:
                lo_bull, hi_bull = s['bull']
                lo_bear, hi_bear = s['bear']
                if lo_bull <= value <= hi_bull:
                    return '🟢 Bullish'
                elif lo_bear <= value <= hi_bear:
                    return '🔴 Bearish'
                else:
                    return '🟡 Neutral'
    
    return '—'

def main():
    print(f"\n{'='*70}")
    print("MACRO DASHBOARD — {time.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}")
    
    api_key = None
    try:
        with open('.fred_api_key') as f:
            api_key = f.read().strip()
    except: pass
    
    results = []
    
    for name, info in INDICATORS.items():
        code = info['code']
        unit = info['unit']
        inverse = info.get('inverse', False)
        
        print(f"\n{name} ({code})...")
        
        if api_key:
            v_curr, v_prev, date = get_fred(api_key, code)
        else:
            v_curr, v_prev, date = get_observation_direct(code)
        
        if v_curr is None:
            print(f"  ⚠️  No data")
            results.append({'name': name, 'value': None, 'change': None, 'date': None, 'signal': 'N/A'})
            continue
        
        # Transform if needed
        if info.get('transform') == 'pct_change_12' and v_curr and v_prev:
            # Annual percentage change
            v_curr_transformed = ((v_curr - v_prev) / abs(v_prev) * 100) if v_prev != 0 else 0
        else:
            v_curr_transformed = v_curr
        
        # 1-month change
        change = v_curr_transformed - (v_curr or 0)  # simplified
        
        sig = signal(name, v_curr_transformed, info)
        
        results.append({
            'name': name,
            'value': v_curr_transformed,
            'unit': unit,
            'prev': v_prev,
            'date': date,
            'signal': sig
        })
        
        val_str = f"{v_curr_transformed:.2f}{unit}" if unit else f"{v_curr_transformed:.2f}"
        date_str = f" ({date})" if date else ""
        print(f"  Current: {val_str}{date_str} | {sig}")
    
    # Additional market data
    print(f"\n{'='*70}")
    print("MARKET CONTEXT")
    print(f"{'='*70}")
    
    # Check if yield curve is inverted
    try:
        yc = [r for r in results if 'Yield Curve' in r['name']][0]
        if yc['value'] is not None:
            if yc['value'] < 0:
                print(f"  ⚠️  Yield curve INVERTED ({yc['value']:.0f}bps) — recession risk elevated")
            else:
                print(f"  ✅ Yield curve normal ({yc['value']:.0f}bps)")
    except: pass
    
    # VIX
    try:
        vix = [r for r in results if 'VIX' in r['name']][0]
        if vix['value'] is not None:
            if vix['value'] > 30:
                print(f"  ⚠️  VIX {vix['value']:.0f} — HIGH market fear, defensive positioning")
            elif vix['value'] > 20:
                print(f"  🟡 VIX {vix['value']:.0f} — elevated, watch for volatility")
            else:
                print(f"  ✅ VIX {vix['value']:.0f} — calm markets")
    except: pass
    
    # Inflation
    try:
        cpi = [r for r in results if 'CPI' in r['name']][0]
        if cpi['value'] is not None:
            if cpi['value'] > 4:
                print(f"  🔴 CPI {cpi['value']:.1f}% — above Fed target, potential rate pressure")
            elif cpi['value'] > 2.5:
                print(f"  🟡 CPI {cpi['value']:.1f}% — above 2% target, Fed watchful")
            else:
                print(f"  ✅ CPI {cpi['value']:.1f}% — at or below Fed target")
    except: pass
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY:")
    bullish = sum(1 for r in results if '🟢' in (r.get('signal') or ''))
    bearish = sum(1 for r in results if '🔴' in (r.get('signal') or ''))
    neutral = sum(1 for r in results if '🟡' in (r.get('signal') or ''))
    
    print(f"  🟢 Bullish indicators: {bullish}")
    print(f"  🟡 Neutral indicators: {neutral}")
    print(f"  🔴 Bearish indicators: {bearish}")
    
    if bullish > bearish and bearish == 0:
        print(f"\n  → MACRO ENVIRONMENT: 🟢 RISK-ON")
    elif bearish > bullish:
        print(f"\n  → MACRO ENVIRONMENT: 🔴 RISK-OFF")
    else:
        print(f"\n  → MACRO ENVIRONMENT: 🟡 MIXED")

if __name__ == '__main__':
    main()