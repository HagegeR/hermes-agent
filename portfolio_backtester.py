"""
Portfolio Backtester — test strategies against historical price data from yfinance.
Usage:
  python3 portfolio_backtester.py INTC NVDA GOOGL --start 2023-01-01 --end 2026-06-01
  python3 portfolio_backtester.py INTC NVDA GOOGL --start 2023-01-01 --end 2026-06-01 --strategy equal-weight
  python3 portfolio_backtester.py INTC NVDA GOOGL --start 2023-01-01 --end 2026-06-01 --strategy momentum
  python3 portfolio_backtester.py INTC NVDA GOOGL --start 2023-01-01 --end 2026-06-01 --strategy value
"""
import sys, pandas as pd, numpy as np, datetime
import yfinance as yf
from yfinance_utils import get_close


def get_prices(tickers, start, end):
    """Download historical Close prices for all tickers."""
    data = {}
    for t in tickers:
        try:
            df = yf.download(t, start=start, end=end, progress=False, auto_adjust=True)
            if df is None or df.empty:
                print(f"  ⚠️  {t}: no data")
                continue
            col = get_close(df)
            if isinstance(col, pd.DataFrame):
                col = col.squeeze()
            if not isinstance(col, pd.Series) or len(col) <= 1:
                print(f"  ⚠️  {t}: insufficient data ({type(col).__name__}, len={getattr(len(col), '__call__', lambda: '?')()})")
                continue
            data[t] = col
            print(f"  ✅ {t}: {len(col)} trading days")
        except Exception as e:
            print(f"  ❌ {t}: {e}")
    
    if not data:
        print("❌ No price data available — all tickers failed to download")
        return None
    
    prices = pd.DataFrame(data)
    prices.index = pd.to_datetime(prices.index)
    if prices.index.tz is not None:
        prices.index = prices.index.tz_localize(None)
    prices = prices.dropna()
    return prices


def _spy_stats(prices_or_start_end, end_or_none=None):
    """Download SPY and return stats dict. Accepts either (start, end) strings or prices DataFrame."""
    if isinstance(prices_or_start_end, pd.DataFrame):
        start_str = str(prices_or_start_end.index[0])[:10]
        end_str = str(prices_or_start_end.index[-1])[:10]
    else:
        start_str = prices_or_start_end
        end_str = end_or_none
    
    try:
        df = yf.download('SPY', start=start_str, end=end_str, progress=False, auto_adjust=True)
        close = get_close(df)
        if isinstance(close, pd.DataFrame):
            close = close.squeeze()
        if not isinstance(close, pd.Series) or len(close) <= 1:
            return None
        ret = close.pct_change().dropna()
        cum = (1 + ret).cumprod()
        total = cum.iloc[-1] - 1
        annual = (1 + total) ** (252 / len(ret)) - 1
        vol = ret.std() * np.sqrt(252)
        return {
            'total': total * 100,
            'annual': annual * 100,
            'vol': vol * 100,
            'sharpe': annual / vol if vol > 0 else 0,
            'max_dd': ((cum / cum.cummax()) - 1).min() * 100,
        }
    except Exception as e:
        print(f"    SPY download error: {e}")
        return None


def backtest(prices, weights, name='Portfolio'):
    """Run a backtest given prices and weights."""
    if prices.empty:
        return None
    
    daily_ret = prices.pct_change().dropna()
    portfolio_ret = (daily_ret * weights).sum(axis=1)
    cumulative = (1 + portfolio_ret).cumprod()
    
    total_ret = cumulative.iloc[-1] - 1
    annual_ret = (1 + total_ret) ** (252 / len(portfolio_ret)) - 1
    annual_vol = portfolio_ret.std() * np.sqrt(252)
    sharpe = annual_ret / annual_vol if annual_vol > 0 else 0
    max_dd = ((cumulative / cumulative.cummax()) - 1).min()
    win_rate = (portfolio_ret > 0).mean()
    
    spy = _spy_stats(prices)
    alpha = (annual_ret - spy['annual'] / 100) if spy else None
    excess_sharpe = (sharpe - spy['sharpe']) if spy and spy['sharpe'] else None
    
    return {
        'strategy': name,
        'start': str(prices.index[0])[:10],
        'end': str(prices.index[-1])[:10],
        'total_ret': total_ret * 100,
        'annual_ret': annual_ret * 100,
        'annual_vol': annual_vol * 100,
        'sharpe': sharpe,
        'max_dd': max_dd * 100,
        'win_rate': win_rate * 100,
        'spy_total': spy['total'] if spy else None,
        'spy_annual': spy['annual'] if spy else None,
        'spy_sharpe': spy['sharpe'] if spy else None,
        'spy_max_dd': spy['max_dd'] if spy else None,
        'alpha': (alpha * 100) if alpha is not None else None,
        'excess_sharpe': excess_sharpe if excess_sharpe is not None else None,
    }


def strategy_equal_weight(prices):
    n = len(prices.columns)
    return pd.Series(1/n, index=prices.columns)


def strategy_value(prices):
    """Inverse-PE weighting: lower PE = higher weight. Use 1/PE as weight proxy."""
    weights = pd.Series(1.0, index=prices.columns)
    for t in prices.columns:
        try:
            tk = yf.Ticker(t)
            info = tk.info
            pe = info.get('trailingPE') or info.get('forwardPE') or 20
            weights[t] = 1 / max(pe, 1)
        except:
            weights[t] = 0.5
    total = weights.sum()
    return weights / total if total > 0 else weights


def strategy_top_performer(prices, lookback=60, top_n=None):
    """Top performers by momentum get equal weight, rest 0.
    If top_n is None, use top half of tickers."""
    returns = prices.iloc[-lookback:].pct_change().mean()
    if top_n is None:
        top_n = max(1, len(prices.columns) // 2)
    top_tickers = returns.nlargest(min(top_n, len(prices.columns))).index
    weights = pd.Series(0.0, index=prices.columns)
    for t in top_tickers:
        weights[t] = 1 / len(top_tickers)
    return weights


def print_result(res):
    if res is None:
        return
    print(f"\n{res['strategy']}:")
    print(f"  Period:         {res['start']} → {res['end']}")
    print(f"  Total Return:   {res['total_ret']:+.1f}%")
    print(f"  Annual Return:  {res['annual_ret']:+.1f}%")
    print(f"  Annual Vol:     {res['annual_vol']:.1f}%")
    print(f"  Sharpe Ratio:   {res['sharpe']:.2f}")
    print(f"  Max Drawdown:   {res['max_dd']:.1f}%")
    print(f"  Win Rate:       {res['win_rate']:.1f}%")
    if res.get('spy_annual') is not None:
        print(f"  Alpha vs SPY:   {res['alpha']:+.1f}%")
        print(f"  Excess Sharpe:  {res['excess_sharpe']:+.2f}" if res.get('excess_sharpe') is not None else "")
        print(f"  SPY Total:      {res['spy_total']:+.1f}% | Sharpe: {res['spy_sharpe']:.2f} | MaxDD: {res['spy_max_dd']:.1f}%")


def individual_returns(prices):
    """Print per-ticker stats."""
    rets = prices.pct_change().mean() * 252 * 100
    print(f"\nIndividual Stock Performance:")
    for t in sorted(rets.index, key=lambda x: rets[x], reverse=True):
        vol = prices[t].pct_change().std() * np.sqrt(252) * 100
        sr = rets[t] / vol if vol else 0
        print(f"  {t:6s}: Return={rets[t]:+.1f}% | Vol={vol:.1f}% | Sharpe={sr:.2f}")


def main():
    # Parse args: tickers are non-flag, non-date strings
    tickers = [t.upper() for t in sys.argv[1:]
               if not t.startswith('--') and len(t) != 10]
    
    if not tickers:
        print("Usage: python3 portfolio_backtester.py INTC NVDA GOOGL --start 2023-01-01 [--end 2026-06-01] [--strategy equal-weight|momentum|value]")
        return
    
    start = '2023-01-01'; end = '2026-01-01'; strategy = 'equal-weight'
    for i, arg in enumerate(sys.argv):
        if arg == '--start' and i+1 < len(sys.argv): start = sys.argv[i+1]
        if arg == '--end' and i+1 < len(sys.argv): end = sys.argv[i+1]
        if arg == '--strategy' and i+1 < len(sys.argv): strategy = sys.argv[i+1]
    
    print(f"\n{'='*70}")
    print(f"PORTFOLIO BACKTEST")
    print(f"Tickers: {tickers}")
    print(f"Period: {start} to {end}")
    print(f"Strategy: {strategy}")
    print(f"{'='*70}")
    
    prices = get_prices(tickers, start, end)
    if prices is None or prices.empty:
        return
    
    print(f"\nDate range: {prices.index[0].date()} to {prices.index[-1].date()} | {len(prices)} trading days")
    
    if strategy == 'equal-weight':
        weights = strategy_equal_weight(prices)
        result = backtest(prices, weights, 'Equal Weight')
    elif strategy == 'top-performer' or strategy == 'momentum':
        weights = strategy_top_performer(prices)
        result = backtest(prices, weights, 'Momentum Top-3')
    elif strategy == 'value':
        weights = strategy_value(prices)
        result = backtest(prices, weights, 'Value-Weighted')
    else:
        weights = strategy_equal_weight(prices)
        result = backtest(prices, weights, strategy)
    
    print_result(result)
    
    # Also run momentum strategy for comparison
    mom_weights = strategy_top_performer(prices)
    mom_result = backtest(prices, mom_weights, 'Momentum Top-3')
    print_result(mom_result)
    
    individual_returns(prices)


if __name__ == '__main__':
    main()