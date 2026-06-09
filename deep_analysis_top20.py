"""
Deep-dive analysis on Top 20 Russell 1000 stocks:
- Analyst 6-month and 1-year price targets
- Buy zone / margin of safety calculation
- Growth projections
- Best investment ranking
"""
import yfinance as yf
import json
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import os

# Top 20 tickers

# ── Auto-version check: reload top 20 from latest score file if newer ────────
def get_top20_from_scores(scores_path="russell_1000_scores_v2.json", output_path="top20_deep_analysis.json"):
    """If score file is newer than output, reload top 20 tickers from it."""
    if not os.path.exists(scores_path):
        return None
    scores_mtime = os.path.getmtime(scores_path)
    if os.path.exists(output_path):
        out_mtime = os.path.getmtime(output_path)
        if scores_mtime > out_mtime:
            print(f"⚠️  Score file updated since last run — reloading top 20 from {scores_path}")
            try:
                with open(scores_path) as f:
                    raw = json.load(f)
                all_scored = raw["all_scored"]
                sorted_all = sorted(all_scored, key=lambda x: x.get("total_score", 0), reverse=True)
                return [e["ticker"] for e in sorted_all[:20]]
            except Exception as e:
                print(f"⚠️  Could not reload from score file: {e}")
                return None
    return None

_auto_top20 = get_top20_from_scores()
_default_top20 = ['AU', 'INCY', 'CACC', 'FSLR', 'GEN', 'HALO', 'EXE', 'AMG',
                  'EXEL', 'GILD', 'CF', 'AR', 'CPAY', 'APP', 'EVR', 'GLPI',
                  'GMED', 'AGNC', 'AL', 'COLB']
if _auto_top20:
    TOP20 = _auto_top20
    print(f"✅ Loaded top 20 from score file: {TOP20[:5]}...")
else:
    print(f"ℹ️  Using hardcoded top 20: {_default_top20[:5]}...")
    TOP20 = _default_top20

def fetch_deep_data(ticker):
    try:
        t = yf.Ticker(ticker)
        info = t.info

        # Current price
        current_price = (info.get('currentPrice')
                        or info.get('regularMarketPrice')
                        or info.get('fiftyDayAverage')
                        or 0)

        # Analyst price targets
        target_info = {}
        try:
            targets = t.analyst_price_targets
            if targets is not None and not targets.empty:
                row = targets.iloc[0]
                target_info = {
                    'current': row.get('Current', current_price),
                    'mean_target': row.get('TargetMean', None),
                    'high_target': row.get('TargetHigh', None),
                    'low_target': row.get('TargetLow', None),
                }
        except Exception:
            target_info = {}

        # Use info fields as fallback
        if not target_info.get('mean_target'):
            target_info['mean_target'] = info.get('targetMeanPrice')
        if not target_info.get('high_target'):
            target_info['high_target'] = info.get('targetHighPrice')
        if not target_info.get('low_target'):
            target_info['low_target'] = info.get('targetLowPrice')

        # Recommendations summary
        recs = {}
        try:
            rec = t.recommendations
            if rec is not None and not rec.empty:
                if 'Grade' in rec.columns:
                    recs['strong_buy'] = int((rec['Grade'] == 'Strong Buy').sum())
                    recs['buy'] = int((rec['Grade'] == 'Buy').sum())
                    recs['hold'] = int((rec['Grade'] == 'Hold').sum())
                    recs['sell'] = int((rec['Grade'] == 'Sell').sum())
                    recs['strong_sell'] = int((rec['Grade'] == 'Strong Sell').sum())
                    recs['total'] = sum(recs.values())
                    recs['buy_ratio'] = (recs['strong_buy'] + recs['buy']) / recs['total'] if recs['total'] else 0
        except Exception:
            pass

        # Forward EPS & PE
        forward_eps = info.get('forwardEps') or info.get('trailingEps')
        trailing_eps = info.get('trailingEps')
        trailing_pe = info.get('trailingPE') or 0
        forward_pe = info.get('forwardPE') or 0

        # Revenue estimates (YoY growth from info)
        revenue_growth = info.get('revenueGrowth') or 0
        earnings_growth = info.get('earningsGrowth') or 0

        # Earnings per share next 5 years (annualized growth rate)
        eps_5y = info.get('earningsQuarterlyGrowth') or info.get('revenueGrowth') or 0

        # 52-week range
        week52_high = info.get('fiftyTwoWeekHigh')
        week52_low = info.get('fiftyTwoWeekLow')
        week52_change = info.get('52WeekChange') or 0

        # Market cap
        market_cap = info.get('marketCap', 0)

        # PEG ratio (trailing PE / expected earnings growth)
        peg_ratio = info.get('pegRatio') or 0

        # Analyst earnings estimates
        earnings_est = {}
        try:
            ed = t.earnings_estimate
            if ed is not None and not ed.empty:
                for col in ed.columns:
                    if 'forward' in col.lower():
                        earnings_est['next_q_eps'] = ed[col].iloc[0] if len(ed) > 0 else None
                        break
        except Exception:
            pass

        # Revenue estimates
        try:
            rd = t.revenue_estimate
            if rd is not None and not rd.empty:
                for col in rd.columns:
                    if 'forward' in col.lower() or '+0y' in col or '+1y' in col:
                        earnings_est['next_rev'] = rd[col].iloc[0] if len(ed) > 0 else None
                        break
        except Exception:
            pass

        # Institutional ownership
        inst_pct = info.get('heldByInstitutionsPercentage', 0) or 0

        # Beta
        beta = info.get('beta', 1.0) or 1.0

        return {
            'ticker': ticker,
            'company_name': info.get('shortName') or info.get('longName') or ticker,
            'sector': info.get('sector') or 'Unknown',
            'current_price': current_price,
            'mean_target': target_info.get('mean_target'),
            'high_target': target_info.get('high_target'),
            'low_target': target_info.get('low_target'),
            'week52_high': week52_high,
            'week52_low': week52_low,
            'week52_change': week52_change,
            'trailing_pe': trailing_pe,
            'forward_pe': forward_pe,
            'forward_eps': forward_eps,
            'trailing_eps': trailing_eps,
            'peg_ratio': peg_ratio,
            'revenue_growth': revenue_growth,
            'earnings_growth': earnings_growth,
            'market_cap': market_cap,
            'inst_pct': inst_pct,
            'beta': beta,
            'recs': recs,
            'info': info,
            'success': True
        }
    except Exception as e:
        return {'ticker': ticker, 'success': False, 'error': str(e)}

# Fetch all top 20 in parallel
print("Fetching deep data for top 20...")
results = []
with ThreadPoolExecutor(max_workers=10) as ex:
    futures = {ex.submit(fetch_deep_data, t): t for t in TOP20}
    for f in as_completed(futures):
        results.append(f.result())

print("Data fetched. Analyzing...\n")

def analyze_stock(d):
    if not d.get('success'):
        return None

    t = d['ticker']
    current = d['current_price'] or 0
    mean = d['mean_target'] or current
    high = d['high_target'] or mean
    low = d['low_target'] or mean

    recs = d.get('recs', {})
    total_recs = recs.get('total', 0)
    buy_ratio = recs.get('buy_ratio', 0)

    # Upside to mean target
    upside_mean = ((mean - current) / current) if current > 0 else 0
    upside_high = ((high - current) / current) if current > 0 else 0
    upside_low = ((low - current) / current) if current > 0 else 0

    # Distance from 52-week high/low
    dist_52w_high = ((current - high) / high) if high > 0 else 0
    dist_52w_low = ((current - low) / low) if low > 0 else 0

    # BUY ZONE: We define as price within 10% of mean target
    # (i.e., significant upside remaining but not at target yet)
    buy_zone_upper = mean * 0.90  # 10% below mean = good entry
    buy_zone_lower = low if low > mean * 0.7 else mean * 0.80  # Conservative: 20% below mean

    # Conservative buy price: average of low target and 20% below mean
    conservative_buy = (low * 0.4 + mean * 0.6 * 0.85) if low > 0 else mean * 0.80
    ideal_buy = mean * 0.85  # 15% below mean target = great entry

    # Growth estimate: forward EPS growth vs trailing
    forward_eps = d.get('forward_eps') or 0
    trailing_eps = d.get('trailing_eps') or 0
    eps_growth_est = ((forward_eps - trailing_eps) / trailing_eps) if trailing_eps > 0 else 0

    # Implied 6-month growth (annualized from analyst target horizon)
    # Mean target is typically 12-month; 6-month = half the upside
    implied_6m_upside = upside_mean / 2 if upside_mean > 0 else 0

    # 1-year projection: mean target upside + expected earnings growth
    expected_1y_total = upside_mean + d.get('earnings_growth', 0)

    # PE valuation vs sector
    fwd_pe = d.get('forward_pe') or d.get('trailing_pe') or 0
    trail_pe = d.get('trailing_pe') or 0

    # Scorecard
    scorecard = {}

    # Valuation score
    val_score = 0
    if trail_pe > 0 and trail_pe < 100:
        if trail_pe < 15:
            val_score = 5
        elif trail_pe < 25:
            val_score = 3
        elif trail_pe < 40:
            val_score = 1
        else:
            val_score = -1
    scorecard['valuation'] = val_score

    # Upside score
    up_score = 0
    if upside_mean > 0.3:
        up_score = 5
    elif upside_mean > 0.2:
        up_score = 4
    elif upside_mean > 0.1:
        up_score = 3
    elif upside_mean > 0:
        up_score = 2
    else:
        up_score = -1
    scorecard['upside'] = up_score

    # Analyst conviction score
    conv_score = 0
    if total_recs >= 10:
        if buy_ratio >= 0.7:
            conv_score = 5
        elif buy_ratio >= 0.5:
            conv_score = 3
        elif buy_ratio >= 0.3:
            conv_score = 1
        else:
            conv_score = -2
    elif total_recs > 0:
        if buy_ratio >= 0.6:
            conv_score = 3
        elif buy_ratio >= 0.4:
            conv_score = 1
    scorecard['conviction'] = conv_score

    # Growth score
    gr_score = 0
    eg = d.get('earnings_growth', 0) or 0
    rg = d.get('revenue_growth', 0) or 0
    if eg > 0.3 or rg > 0.4:
        gr_score = 5
    elif eg > 0.2 or rg > 0.25:
        gr_score = 4
    elif eg > 0.1 or rg > 0.15:
        gr_score = 3
    elif eg > 0 or rg > 0:
        gr_score = 2
    scorecard['growth'] = gr_score

    # Safety score
    safety_score = 0
    beta_val = d.get('beta')
    if beta_val and beta_val < 1.0:
        safety_score += 2
    if fwd_pe and fwd_pe < trail_pe and fwd_pe > 0:
        safety_score += 2  # Expanding earnings = safer
    elif fwd_pe and fwd_pe > trail_pe * 1.5:
        safety_score -= 1
    if d.get('inst_pct', 0) > 0.5:
        safety_score += 1
    scorecard['safety'] = safety_score

    total_score = val_score + up_score + conv_score + gr_score + safety_score

    return {
        'ticker': t,
        'company_name': d['company_name'],
        'sector': d['sector'],
        'current_price': current,
        'mean_target': mean,
        'high_target': high,
        'low_target': low,
        'upside_mean_pct': upside_mean * 100,
        'upside_high_pct': upside_high * 100,
        'upside_low_pct': upside_low * 100,
        'conservative_buy': conservative_buy,
        'ideal_buy': ideal_buy,
        '6m_expected': implied_6m_upside * 100,
        '1y_expected': expected_1y_total * 100,
        'trailing_pe': trail_pe,
        'forward_pe': fwd_pe,
        'peg_ratio': d.get('peg_ratio'),
        'revenue_growth': d.get('revenue_growth', 0) * 100,
        'earnings_growth': d.get('earnings_growth', 0) * 100,
        'inst_pct': d.get('inst_pct', 0) * 100,
        'beta': d.get('beta'),
        'buy_ratio': buy_ratio * 100,
        'total_recs': total_recs,
        'scorecard': scorecard,
        'investment_score': total_score,
        'market_cap': d['market_cap'],
        'week52_high': d.get('week52_high'),
        'week52_low': d.get('week52_low'),
    }

# Analyze all
analyzed = [analyze_stock(r) for r in results if analyze_stock(r)]
analyzed.sort(key=lambda x: x['investment_score'], reverse=True)

# Print results
print("=" * 90)
print("TOP 20 DEEP-DIVE: GROWTH PROJECTIONS & BUY ZONES")
print("=" * 90)

for i, s in enumerate(analyzed, 1):
    mc = s['market_cap']
    mc_str = f"${mc/1e12:.1f}T" if mc >= 1e12 else f"${mc/1e9:.0f}B"

    print(f"\n{'─'*90}")
    print(f"#{i} {s['ticker']} — {s['company_name']} [{s['sector']}]")
    print(f"   💰 Price: ${s['current_price']:.2f} | Market Cap: {mc_str} | Beta: {s['beta']:.2f}")
    print(f"   📊 Trailing PE: {s['trailing_pe']:.1f}x | Forward PE: {s['forward_pe']:.1f}x | PEG: {s['peg_ratio']:.2f}")
    print(f"   📈 Rev Growth: {s['revenue_growth']:.1f}%/yr | Earnings Growth: {s['earnings_growth']:.1f}%/yr")
    print(f"")
    print(f"   🎯 ANALYST TARGETS:")
    print(f"      Low:    ${s['low_target']:.2f}  ({s['upside_low_pct']:+.1f}%)")
    print(f"      Mean:   ${s['mean_target']:.2f}  ({s['upside_mean_pct']:+.1f}%)")
    print(f"      High:   ${s['high_target']:.2f}  ({s['upside_high_pct']:+.1f}%)")
    print(f"")
    print(f"   💵 BUY ZONES:")
    print(f"      ✅ IDEAL ENTRY:    ${s['ideal_buy']:.2f}  (within {((1 - s['ideal_buy']/s['mean_target'])*100):.0f}% of mean target)")
    print(f"      ⚠️  CONSERVATIVE:   ${s['conservative_buy']:.2f}")
    print(f"      📌 CURRENT PRICE:  ${s['current_price']:.2f}  {'✅ BELOW ideal entry — BUY NOW' if s['current_price'] <= s['ideal_buy'] else '⚠️  ABOVE ideal — WAIT for pullback'}")
    print(f"")
    print(f"   📅 GROWTH PROJECTIONS:")
    print(f"      6-Month Expected Return:  {s['6m_expected']:+.1f}%")
    print(f"      1-Year Total Return:      {s['1y_expected']:+.1f}%  (upside + earnings growth)")
    print(f"")
    print(f"   🏅 Analyst Conviction: {s['buy_ratio']:.0f}% Buy | {s['total_recs']} analysts | Inst. Ownership: {s['inst_pct']:.0f}%")
    print(f"   📋 Scorecard: Val={s['scorecard']['valuation']} | Upside={s['scorecard']['upside']} | Conviction={s['scorecard']['conviction']} | Growth={s['scorecard']['growth']} | Safety={s['scorecard']['safety']}  →  INVESTMENT SCORE: {s['investment_score']}/21")

# Best investment ranking
print(f"\n\n{'='*90}")
print("🏆 BEST INVESTMENT RANKING (6-month & 1-year outlook)")
print("="*90)

# Sort by investment score for best overall
by_score = sorted(analyzed, key=lambda x: x['investment_score'], reverse=True)

# Sort by 6-month upside
by_6m = sorted(analyzed, key=lambda x: x['6m_expected'], reverse=True)

# Sort by 1-year total return
by_1y = sorted(analyzed, key=lambda x: x['1y_expected'], reverse=True)

# Best risk/reward (1y return / beta)
by_risk_adj = sorted(analyzed, key=lambda x: x['1y_expected'] / max(x['beta'], 0.5), reverse=True)

print("\n📊 BY INVESTMENT SCORE (best overall quality):")
for i, s in enumerate(by_score[:10], 1):
    below_entry = "✅ BUY" if s['current_price'] <= s['ideal_buy'] else "⚠️  WAIT"
    print(f"   {i}. {s['ticker']} | Score={s['investment_score']}/21 | 6m={s['6m_expected']:+.1f}% | 1y={s['1y_expected']:+.1f}% | {below_entry} @ ${s['current_price']:.2f}")

print("\n🚀 BY 6-MONTH EXPECTED RETURN:")
for i, s in enumerate(by_6m[:10], 1):
    below_entry = "✅ BUY" if s['current_price'] <= s['ideal_buy'] else "⚠️  WAIT"
    print(f"   {i}. {s['ticker']} | 6m={s['6m_expected']:+.1f}% | 1y={s['1y_expected']:+.1f}% | Score={s['investment_score']} | {below_entry} @ ${s['current_price']:.2f}")

print("\n📈 BY 1-YEAR TOTAL RETURN (upside + earnings growth):")
for i, s in enumerate(by_1y[:10], 1):
    below_entry = "✅ BUY" if s['current_price'] <= s['ideal_buy'] else "⚠️  WAIT"
    print(f"   {i}. {s['ticker']} | 1y={s['1y_expected']:+.1f}% | 6m={s['6m_expected']:+.1f}% | Score={s['investment_score']} | {below_entry} @ ${s['current_price']:.2f}")

print("\n🛡️  BY RISK-ADJUSTED RETURN (1y return / Beta):")
for i, s in enumerate(by_risk_adj[:10], 1):
    risk_adj = s['1y_expected'] / max(s['beta'], 0.5)
    below_entry = "✅ BUY" if s['current_price'] <= s['ideal_buy'] else "⚠️  WAIT"
    print(f"   {i}. {s['ticker']} | Risk-adj={risk_adj:.1f} | Beta={s['beta']:.2f} | 1y={s['1y_expected']:+.1f}% | {below_entry} @ ${s['current_price']:.2f}")

# SAVE
with open('top20_deep_analysis.json', 'w') as f:
    json.dump(analyzed, f, indent=2, default=str)

print(f"\n\nFull data saved to top20_deep_analysis.json")