"""
DCF Valuation Model v2 — per-company WACC + recovery mode for turnaround stocks.
Usage:
  python3 dcf_model.py INTC           # auto WACC from beta, auto mode detection
  python3 dcf_model.py NVDA --wacc 13.85   # override WACC
  python3 dcf_model.py INTC --recovery     # force recovery mode (3-stage)
  python3 dcf_model.py INTC --mode standard  # force standard 1-stage
"""
import sys, yfinance as yf
import numpy_financial as npf
import pandas as pd


RISK_FREE = 0.045       # 10Y Treasury ~4.5%
EQUITY_PREM = 0.055     # Historical equity risk premium ~5.5%
DEFAULT_WACC = 0.10
TERMINAL_GROWTH = 0.025


def calc_wacc(beta: float, risk_free: float = RISK_FREE, equity_prem: float = EQUITY_PREM) -> float:
    """CAPM-based WACC: risk_free + beta * equity_prem. Min 6%, max 20%."""
    if not beta or beta <= 0:
        return DEFAULT_WACC
    wacc = risk_free + beta * equity_prem
    return max(0.06, min(0.20, wacc))


def detect_turnaround(ticker: str) -> bool:
    """Return True if stock looks like a turnaround candidate (PE < 15, RevG < 5%)."""
    try:
        tk = yf.Ticker(ticker)
        info = tk.info
        pe = info.get('trailingPE') or info.get('forwardPE') or 999
        rg = info.get('revenueGrowth') or 0.10
        try:
            pe = float(pe)
            rg = float(rg)
        except (ValueError, TypeError):
            return False
        
        # Additional signals of turnaround: declining margins, restructuring
        fcf = info.get('freeCashflow')
        if fcf and fcf < 0:
            return True
        if pe < 15 and rg < 0.05 and rg >= 0:
            return True
        return False
    except:
        return False


def get_fcf(ticker: str):
    """Extract Free Cash Flow from yfinance — tries multiple methods."""
    t = yf.Ticker(ticker)
    
    try:
        cf = t.cashflow
        if cf is not None and not cf.empty:
            if 'Free Cash Flow' in cf.index:
                fcf = cf.loc['Free Cash Flow'].iloc[0]
                if fcf and fcf > 0:
                    return fcf, 'cashflow_statement'
    except: pass
    
    try:
        cf = t.cashflow
        if cf is not None and not cf.empty:
            ocf = cf.loc['Operating Cash Flow'].iloc[0] if 'Operating Cash Flow' in cf.index else 0
            capex = cf.loc['Capital Expenditures'].iloc[0] if 'Capital Expenditures' in cf.index else 0
            if ocf and ocf > 0:
                fcf = ocf - abs(capex) if capex else ocf
                if fcf > 0:
                    return fcf, 'ocf_minus_capex'
    except: pass
    
    try:
        inc = t.income_stmt
        if inc is not None and not inc.empty:
            ni = inc.loc['Net Income'].iloc[0] if 'Net Income' in inc.index else 0
            if ni and ni > 0:
                return ni * 0.1, 'net_income_proxy'
    except: pass
    
    return None, 'none'


def get_shares(ticker: str):
    t = yf.Ticker(ticker)
    info = t.info
    shares = (info.get('sharesOutstanding') or info.get('impliedSharesOutstanding'))
    if shares:
        return shares
    try:
        bs = t.balance_sheet
        if bs is not None and not bs.empty and 'Ordinary Shares Number' in bs.index:
            return bs.loc['Ordinary Shares Number'].iloc[0]
    except: pass
    return None


def get_net_debt(ticker: str):
    t = yf.Ticker(ticker)
    try:
        bs = t.balance_sheet
        if bs is not None and not bs.empty:
            total_debt = bs.loc['Total Debt'].iloc[0] if 'Total Debt' in bs.index else 0
            cash = bs.loc['Cash And Cash Equivalents'].iloc[0] if 'Cash And Cash Equivalents' in bs.index else 0
            nd = total_debt - cash if total_debt else None
            return nd
    except: pass
    return None


def get_beta(ticker: str) -> float:
    t = yf.Ticker(ticker)
    info = t.info
    beta = info.get('beta') or info.get('betaToMarket')
    if beta:
        try:
            return float(beta)
        except (ValueError, TypeError):
            pass
    return None


def get_revenue_growth(ticker: str) -> float:
    t = yf.Ticker(ticker)
    info = t.info
    rg = info.get('revenueGrowth') or info.get('earningsGrowth') or 0.05
    try:
        return float(rg)
    except (ValueError, TypeError):
        return 0.05


def run_dcf_standard(ticker, years, wacc, terminal_growth, fcf, rg, fcf_margin=None):
    """Standard 1-stage DCF: constant growth forever."""
    projections = []
    for yr in range(1, years + 1):
        proj = fcf * (1 + rg) ** yr
        projections.append(proj)
    
    pv_total = sum(proj / (1 + wacc) ** yr for yr, proj in enumerate(projections, 1))
    terminal_fcf = projections[-1] * (1 + terminal_growth)
    terminal_value = terminal_fcf / (wacc - terminal_growth)
    pv_terminal = terminal_value / (1 + wacc) ** years
    
    return {
        'stage': 'Standard (1-stage)',
        'pv_fcf': pv_total,
        'pv_terminal': pv_terminal,
        'enterprise_value': pv_total + pv_terminal,
        'projections': projections,
        'terminal_fcf': terminal_fcf,
        'terminal_value': terminal_value,
    }


def run_dcf_recovery(ticker, years, wacc, terminal_growth, fcf, rg, sector_growth=0.08):
    """
    3-stage recovery DCF:
      Stage 1 (Years 1-2): Depressed FCF — assume current FCF or slight decline
      Stage 2 (Years 3-5): Recovery — FCF grows at sector average rate
      Stage 3 (terminal): Steady-state at terminal_growth
    """
    stage1_years = 2
    stage2_years = years - stage1_years
    
    projections = []
    for yr in range(1, years + 1):
        if yr <= stage1_years:
            # Stage 1: depressed — flat or slight growth (company is in turnaround)
            proj = fcf * 0.95 ** yr  # slight decline as margins depressed
        else:
            # Stage 2: recovery — grow at sector average
            proj = fcf * (1 + sector_growth) ** (yr - stage1_years)
        projections.append(proj)
    
    pv_total = sum(proj / (1 + wacc) ** yr for yr, proj in enumerate(projections, 1))
    terminal_fcf = projections[-1] * (1 + terminal_growth)
    terminal_value = terminal_fcf / (wacc - terminal_growth)
    pv_terminal = terminal_value / (1 + wacc) ** years
    
    return {
        'stage': 'Recovery (3-stage)',
        'stage1_years': stage1_years,
        'stage2_years': stage2_years,
        'sector_growth': sector_growth,
        'pv_fcf': pv_total,
        'pv_terminal': pv_terminal,
        'enterprise_value': pv_total + pv_terminal,
        'projections': projections,
        'terminal_fcf': terminal_fcf,
        'terminal_value': terminal_value,
    }


def run_dcf_hypergrowth(ticker, years, wacc, terminal_growth, fcf, rg):
    """
    Hypergrowth DCF for stocks with RevG > 30%:
      Years 1-3: Use actual expected growth (high)
      Years 4-5: Taper to terminal growth
      Terminal: steady-state
    """
    projections = []
    for yr in range(1, years + 1):
        if yr <= 3:
            proj = fcf * (1 + rg) ** yr
        else:
            # Taper growth linearly from rg to terminal_growth
            taper = 1 - (yr - 3) / 3
            effective_g = rg * taper + terminal_growth * (1 - taper)
            proj = projections[-1] * (1 + effective_g)
        projections.append(proj)
    
    pv_total = sum(proj / (1 + wacc) ** yr for yr, proj in enumerate(projections, 1))
    terminal_fcf = projections[-1] * (1 + terminal_growth)
    terminal_value = terminal_fcf / (wacc - terminal_growth)
    pv_terminal = terminal_value / (1 + wacc) ** years
    
    return {
        'stage': 'Hypergrowth (3-stage tapered)',
        'pv_fcf': pv_total,
        'pv_terminal': pv_terminal,
        'enterprise_value': pv_total + pv_terminal,
        'projections': projections,
        'terminal_fcf': terminal_fcf,
        'terminal_value': terminal_value,
    }


def run_dcf(ticker, years=5, wacc=None, terminal_growth=TERMINAL_GROWTH,
            mode=None, recovery_sector_growth=0.08):
    """
    Run DCF for a ticker with automatic WACC and mode detection.
    
    Args:
        ticker: stock symbol
        years: projection period (default 5)
        wacc: override WACC (default: CAPM-based from beta)
        terminal_growth: perpetual growth rate (default 2.5%)
        mode: 'standard' | 'recovery' | 'hypergrowth' | None (auto-detect)
        recovery_sector_growth: sector growth rate for recovery stage (default 8%)
    """
    t = yf.Ticker(ticker)
    info = t.info
    
    company = info.get('shortName') or info.get('longName') or ticker
    price = info.get('currentPrice') or info.get('regularMarketPrice')
    beta = get_beta(ticker)
    shares = get_shares(ticker)
    net_debt = get_net_debt(ticker)
    mc = info.get('marketCap')
    
    # Auto-detect WACC from beta
    if wacc is None:
        wacc = calc_wacc(beta) if beta else DEFAULT_WACC
    
    # Auto-detect DCF mode
    rg = get_revenue_growth(ticker)
    
    if mode is None:
        if rg > 0.30:
            mode = 'hypergrowth'
        elif detect_turnaround(ticker):
            mode = 'recovery'
        else:
            mode = 'standard'
    
    # Get FCF
    fcf, fcf_method = get_fcf(ticker)
    if not fcf:
        print(f"❌ Cannot determine FCF for {ticker}")
        return None
    
    # Get revenue & FCF margin
    fcf_margin = None
    try:
        inc = t.income_stmt
        if inc is not None and not inc.empty and 'Total Revenue' in inc.index:
            revenue = inc.loc['Total Revenue'].iloc[0]
            if revenue and revenue > 0:
                fcf_margin = fcf / revenue
    except: pass
    
    # Run appropriate DCF stage
    if mode == 'recovery':
        dcf = run_dcf_recovery(ticker, years, wacc, terminal_growth, fcf, rg, recovery_sector_growth)
    elif mode == 'hypergrowth':
        dcf = run_dcf_hypergrowth(ticker, years, wacc, terminal_growth, fcf, rg)
    else:
        dcf = run_dcf_standard(ticker, years, wacc, terminal_growth, fcf, rg)
    
    # Calculate equity value
    ev = dcf['enterprise_value']
    equity_value = ev - net_debt if net_debt and net_debt > 0 else ev
    price_per_share = equity_value / shares if shares else None
    
    # Print results
    print(f"\n{'='*65}")
    print(f"DCF Model: {ticker} | {dcf['stage']}")
    print(f"WACC: {wacc*100:.2f}% | Terminal: {terminal_growth*100:.1f}% | RevG: {rg*100:.1f}%")
    if beta:
        print(f"Beta: {beta:.2f} → CAPM WACC = {wacc*100:.2f}%")
    print(f"{'='*65}")
    print(f"\nCompany: {company}")
    if price:
        print(f"Current Price: ${price:.2f}")
    print(f"FCF: ${fcf/1e9:.2f}B | Margin: {fcf_margin*100:.1f}% | Method: {fcf_method}")
    print(f"Shares: {shares/1e6:.1f}M" if shares else "Shares: N/A")
    
    # Projections
    print(f"\nFCF Projections:")
    for yr, proj in enumerate(dcf['projections'], 1):
        pv = proj / (1 + wacc) ** yr
        print(f"  Year {yr}: ${proj/1e9:.3f}B  →  PV=${pv/1e9:.3f}B")
    
    print(f"\nTerminal:")
    print(f"  Terminal FCF: ${dcf['terminal_fcf']/1e9:.2f}B")
    print(f"  Terminal Value: ${dcf['terminal_value']/1e9:.2f}B")
    print(f"  PV of Terminal: ${dcf['pv_terminal']/1e9:.2f}B")
    
    print(f"\n{'─'*65}")
    print(f"RESULTS:")
    print(f"  Sum of PV (FCF):  ${dcf['pv_fcf']/1e9:.2f}B")
    print(f"  PV of Terminal:    ${dcf['pv_terminal']/1e9:.2f}B")
    print(f"  Enterprise Value:  ${ev/1e9:.2f}B")
    print(f"  Equity Value:     ${equity_value/1e9:.2f}B")
    
    verdict = None
    if price_per_share and price:
        upside = (price_per_share - price) / price * 100
        print(f"\n  Intrinsic Value:  ${price_per_share:.2f}")
        print(f"  Current Price:    ${price:.2f}")
        print(f"  Upside/(Downside): {upside:+.1f}%")
        
        if upside > 30:
            verdict = '✅ STRONG BUY — >30% upside'
        elif upside > 15:
            verdict = '🟢 BUY — 15-30% upside'
        elif upside > 0:
            verdict = '⚪ HOLD — modest positive upside'
        elif upside > -15:
            verdict = '🟡 HOLD/WAIT — slight overvaluation'
        else:
            verdict = '🔴 AVOID — significant overvaluation'
        print(f"  → {verdict}")
    
    print(f"{'='*65}")
    
    return {
        'ticker': ticker,
        'company': company,
        'mode': dcf['stage'],
        'wacc': wacc,
        'beta': beta,
        'fcf': fcf,
        'fcf_margin': fcf_margin,
        'revenue_growth': rg,
        'terminal_growth': terminal_growth,
        'projections': dcf['projections'],
        'pv_fcf': dcf['pv_fcf'],
        'pv_terminal': dcf['pv_terminal'],
        'enterprise_value': ev,
        'equity_value': equity_value,
        'intrinsic_value': price_per_share,
        'current_price': price,
        'upside': ((price_per_share - price) / price * 100) if (price_per_share and price) else None,
        'net_debt': net_debt,
        'shares': shares,
        'verdict': verdict,
    }


if __name__ == '__main__':
    ticker = sys.argv[1] if len(sys.argv) > 1 else 'AAPL'
    
    years = 5
    wacc_override = None
    terminal_growth = TERMINAL_GROWTH
    mode = None
    
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == '--years' and i+1 < len(sys.argv):
            years = int(sys.argv[i+1]); i += 2
        elif sys.argv[i] == '--wacc' and i+1 < len(sys.argv):
            wacc_override = float(sys.argv[i+1]) / 100; i += 2
        elif sys.argv[i] == '--terminal-growth' and i+1 < len(sys.argv):
            terminal_growth = float(sys.argv[i+1]) / 100; i += 2
        elif sys.argv[i] == '--recovery':
            mode = 'recovery'; i += 1
        elif sys.argv[i] == '--hypergrowth':
            mode = 'hypergrowth'; i += 1
        elif sys.argv[i] == '--standard':
            mode = 'standard'; i += 1
        elif sys.argv[i] == '--mode' and i+1 < len(sys.argv):
            mode = sys.argv[i+1]; i += 2
        else:
            i += 1
    
    result = run_dcf(ticker, years=years, wacc=wacc_override,
                     terminal_growth=terminal_growth, mode=mode)
    
    if result:
        print(f"\n[JSON Output for pipeline integration]")
        print(f"ticker={result['ticker']} mode={result['mode']} wacc={result['wacc']:.4f} "
              f"upside={result['upside']} intrinsic={result['intrinsic_value']} "
              f"current={result['current_price']}")