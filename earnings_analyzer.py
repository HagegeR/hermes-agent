"""
Earnings Analyzer — upcoming, historical, and implied move analysis.
Usage: python3 earnings_analyzer.py AAPL [--upcoming] [--history] [--implied-move] [--full]
"""
import sys, yfinance as yf, datetime, time

def safe_float(v):
    try:
        f = float(v)
        return f if f == f else None
    except: return None

def show_upcoming(ticker):
    """Show upcoming earnings for a ticker."""
    t = yf.Ticker(ticker)
    info = t.info
    company = info.get('shortName') or ticker
    
    try:
        ed = t.earnings_dates
        if ed is not None and not ed.empty:
            # Filter future earnings
            future = ed[ed.index >= datetime.datetime.now()].sort_index()
            past = ed[ed.index < datetime.datetime.now()].sort_index()
            
            print(f"\n📅 UPCOMING EARNINGS: {company} ({ticker})")
            if not future.empty:
                for idx, row in future.iterrows():
                    date = idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx)
                    eps_for = row.get('Earnings Estimate', 'N/A')
                    eps_rep = row.get('Reported EPS', 'N/A')
                    surprise = row.get('Earnings Surprise', 'N/A')
                    print(f"  {date}: Est EPS={eps_for} | Reported={eps_rep} | Surprise={surprise}")
            else:
                print(f"  No upcoming earnings scheduled (check yfinance for next date)")
            
            # Last 4 earnings
            print(f"\n📊 LAST 4 EARNINGS:")
            for idx, row in past.tail(4).iterrows():
                date = idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx)
                eps_est = row.get('Earnings Estimate', 'N/A')
                eps_rep = row.get('Reported EPS', 'N/A')
                surprise = row.get('Earnings Surprise', 'N/A')
                surprise_pct = row.get('Surprise Percent', 'N/A')
                
                if eps_rep is not None and eps_est is not None:
                    try:
                        beat = float(eps_rep) > float(eps_est)
                        flag = '✅ BEAT' if beat else '❌ MISS'
                    except:
                        flag = '—'
                else:
                    flag = '—'
                
                print(f"  {date}: Est={eps_est} Rep={eps_rep} {flag}")
    except Exception as e:
        print(f"  No earnings dates data: {e}")
    
    # Next earnings date from info
    next_earnings = info.get('earningsNext')
    if next_earnings:
        print(f"\n  Next earnings: {next_earnings}")

def show_history(ticker):
    """Show historical beat/miss pattern."""
    print(f"\n📈 EARNINGS HISTORY: {ticker}")
    
    t = yf.Ticker(ticker)
    
    try:
        inc = t.income_stmt
        if inc is not None and not inc.empty:
            # Show quarterly results
            print("\n  Quarterly Revenue & Net Income:")
            if 'Total Revenue' in inc.index:
                revs = inc.loc['Total Revenue'].head(8)
                nis = inc.loc['Net Income'].head(8) if 'Net Income' in inc.index else None
                
                for i, (date, rev) in enumerate(revs.items()):
                    ni_val = nis.iloc[i] if nis is not None else None
                    date_str = str(date)[:10] if hasattr(date, '__str__') else str(date)
                    rev_str = f"${rev/1e9:.1f}B" if rev else "N/A"
                    ni_str = f"${nis.iloc[i]/1e9:.1f}B" if ni_val else "N/A"
                    print(f"    {date_str}: Rev={rev_str} NI={ni_str}")
    except Exception as e:
        print(f"  Error: {e}")
    
    # Quarterly EPS vs estimate (approximate)
    print("\n  Note: For full beat/miss history, use Bloomberg Terminal or FactSet.")
    print("  yfinance provides earnings_dates table — check with --upcoming flag.")

def show_implied_move(ticker, expiry=None):
    """Calculate implied move from options."""
    print(f"\n📊 OPTIONS IMPLIED MOVE: {ticker}")
    
    t = yf.Ticker(ticker)
    info = t.info
    price = info.get('currentPrice') or info.get('regularMarketPrice')
    
    if not price:
        print(f"  Cannot determine current price")
        return
    
    # Get nearest expiry
    if expiry:
        dates = [expiry]
    else:
        dates = t.options if t.options else []
    
    if not dates:
        print(f"  No options data available")
        return
    
    print(f"  Current Price: ${price:.2f}")
    print(f"  Available expirations: {dates[:6]}")
    
    for exp in dates[:3]:  # Check nearest 3
        opt = t.option_chain(exp)
        
        # ATM = nearest strike to current price
        calls = opt.calls
        puts = opt.puts
        
        if calls.empty:
            continue
        
        # Find ATM strike
        atm_call = calls.iloc[(calls['strike'] - price).abs().argsort().iloc[0]]
        atm_put = puts.iloc[(puts['strike'] - price).abs().argsort().iloc[0]]
        
        atm_strike = atm_call['strike']
        atm_iv_call = atm_call['impliedVolatility']
        atm_iv_put = atm_put['impliedVolatility']
        atm_iv = max(atm_iv_call or 0, atm_iv_put or 0)
        
        # Days to expiry
        exp_date = datetime.datetime.strptime(exp, '%Y-%m-%d')
        dte = (exp_date - datetime.datetime.now()).days
        dte = max(dte, 1)
        
        # Implied move
        if atm_iv and atm_iv > 0:
            move_pct = atm_iv * (dte / 365) ** 0.5 * 100
            move_dollar = price * atm_iv * (dte / 365) ** 0.5
            
            print(f"\n  Expiry: {exp} (DTE={dte}d):")
            print(f"    ATM Strike: ${atm_strike:.2f}")
            print(f"    ATM IV: {atm_iv*100:.1f}%")
            print(f"    Implied Move: ±{move_pct:.1f}% (${price - move_dollar:.2f} to ${price + move_dollar:.2f})")
            
            # Earnings binary
            if dte <= 14:
                print(f"    🔔 EARNINGS within {dte} days — move IS the earnings event")

def show_full(ticker):
    """Full earnings analysis."""
    show_upcoming(ticker)
    show_history(ticker)
    show_implied_move(ticker)

if __name__ == '__main__':
    ticker = sys.argv[1].upper() if len(sys.argv) > 1 else 'AAPL'
    
    if '--upcoming' in sys.argv:
        show_upcoming(ticker)
    elif '--history' in sys.argv:
        show_history(ticker)
    elif '--implied-move' in sys.argv:
        exp = sys.argv[sys.argv.index('--expiry') + 1] if '--expiry' in sys.argv else None
        show_implied_move(ticker, expiry=exp)
    elif '--full' in sys.argv:
        show_full(ticker)
    else:
        print(f"Usage: python3 earnings_analyzer.py <TICKER> [--upcoming|--history|--implied-move|--full]")
        print(f"Example: python3 earnings_analyzer.py NVDA --full")