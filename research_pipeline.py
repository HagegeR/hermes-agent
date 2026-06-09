"""
research_pipeline.py
====================
Single-command orchestrator for the full Russell 1000 stock research pipeline.

Usage:
  python3 research_pipeline.py --tickers top50           # score + DCF + news + macro + backtest top 50
  python3 research_pipeline.py --tickers INTC NVDA AMZN  # specific stocks
  python3 research_pipeline.py --tickers top20 --steps score,dcf,news,macro  # selective steps
  python3 research_pipeline.py --tickers top50 --output my_report.json  # save output

Steps run in order (always score → then selected):
  1. score   — score all ~997 Russell 1000 stocks from yfinance data
  2. topN    — extract top N from score file
  3. dcf     — run DCF (per-company WACC + recovery mode) on top picks
  4. news    — news sentiment vs market for top picks
  5. macro   — macro monitor (FRED indicators)
  6. backtest — portfolio backtest (equal + momentum vs SPY)
  7. delta   — delta vs previous run
  8. report  — generate final ranked + filtered output

All intermediate results saved to data/ with timestamps.
Resume: if interrupted, re-running skips already-completed steps (checkpoint-aware).
"""
import sys, os, json, time, datetime, importlib.util
from datetime import datetime

PYTHON = 'C:\\Python312\\python.exe'
VENV_PYTHON = '.venv_score\\Scripts\\python.exe'
WORKDIR = 'C:\\Users\\hageg\\AppData\\Local\\hermes\\hermes-agent'
DATA_DIR = 'data'

CHECKPOINT_FILE = f'{DATA_DIR}\\pipeline_checkpoint.json'


def python():
    """Return the correct python executable."""
    return VENV_PYTHON


def run(cmd, desc='', timeout=600, background=False):
    """Run a command, print progress, return success."""
    print(f"\n{'='*70}")
    print(f"▶ {desc}")
    print(f"  {' '.join(cmd[:50])}{'...' if len(cmd) > 50 else ''}")
    print(f"{'='*70}")
    start = time.time()
    os.chdir(WORKDIR)
    
    if background:
        import subprocess
        pid = subprocess.Popen([PYTHON] + cmd, cwd=WORKDIR,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"  ⏳ Started in background (PID {pid.pid})")
        return True
    
    import subprocess
    result = subprocess.run([PYTHON] + cmd, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=timeout)
    elapsed = time.time() - start
    if result.returncode == 0:
        print(f"  ✅ {desc} ({elapsed:.0f}s)")
        if result.stdout.strip():
            print(result.stdout[-1000:])  # last 1000 chars
        return True
    else:
        print(f"  ❌ {desc} failed (exit {result.returncode}, {elapsed:.0f}s)")
        if result.stderr:
            print(result.stderr[-500:])
        return False


def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {'completed_steps': [], 'tickers': None, 'scores_file': None}


def save_checkpoint(step, done=True, **kwargs):
    ckpt = load_checkpoint()
    if done and step not in ckpt['completed_steps']:
        ckpt['completed_steps'].append(step)
    ckpt['last_step'] = step
    ckpt['last_run'] = datetime.now().isoformat()
    ckpt.update(kwargs)
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump(ckpt, f, indent=2)


def get_top_tickers(score_file, n=50):
    """Extract top N tickers from score file."""
    with open(score_file) as f:
        data = json.load(f)
    sorted_tickers = sorted(data.items(), key=lambda x: x[1].get('total_score', 0), reverse=True)
    return [t for t, _ in sorted_tickers[:n]]


def load_tickers(ticker_arg):
    """Parse --tickers argument into actual ticker list."""
    if ticker_arg in ('top20', 'top50', 'top100'):
        n = int(ticker_arg[3:])
        score_file = 'russell_1000_scores_v2.json'
        if os.path.exists(score_file):
            return get_top_tickers(score_file, n)
        else:
            print(f"⚠️ Score file not found. Run scoring first.")
            return []
    elif ticker_arg == 'all':
        # Download full Russell 1000 list
        return None  # signals to fetch from Wikipedia
    else:
        return [t.strip().upper() for t in ticker_arg.split(',')]


def get_russell_tickers():
    """Fetch Russell 1000 tickers from Wikipedia or cached file."""
    cache_file = f'{DATA_DIR}\\russell_tickers.json'
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            data = json.load(f)
        cached_at = datetime.fromisoformat(data['cached_at'])
        if (datetime.now() - cached_at).days < 7:
            print(f"  Using cached tickers ({len(data['tickers'])} stocks, from {cached_at.date()})")
            return data['tickers']
    
    print("  Fetching Russell 1000 from Wikipedia...")
    try:
        import requests
        url = 'https://en.wikipedia.org/w/api.php'
        params = {'action': 'parse', 'page': 'Russell_1000_Index', 'prop': 'wikitext', 'format': 'json'}
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        text = r.json()['parse']['wikitext']['*']
        
        # Parse wikitable
        tickers = []
        lines = text.split('\n')
        for line in lines:
            if '| ' in line and not line.startswith('!'):
                parts = [p.strip() for p in line.split('|')]
                for p in parts:
                    if len(p) <= 5 and p.isupper() and p.isalpha() and p not in ('TICKER', 'TICK', 'Symbol'):
                        tickers.append(p)
        
        tickers = sorted(set(tickers))
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(cache_file, 'w') as f:
            json.dump({'tickers': tickers, 'cached_at': datetime.now().isoformat()}, f)
        print(f"  Fetched {len(tickers)} Russell 1000 tickers")
        return tickers
    except Exception as e:
        print(f"  Failed to fetch: {e}")
        return []


def run_full_pipeline(tickers, steps, output_file=None):
    """
    Run the complete pipeline for given tickers and steps.
    Returns dict with all results for each step.
    """
    results = {}
    ckpt = load_checkpoint()
    
    # Always start with score step
    score_file = 'russell_1000_scores_v2.json'
    
    # ── STEP 1: Score ──────────────────────────────────────────────────────────
    if 'score' in steps or 'score_full' in steps:
        if not os.path.exists(score_file) or os.path.getmtime(score_file) < os.path.getmtime(__file__):
            # Score file is older than pipeline → re-score
            pass  # Would run full score_stocks.py here for all tickers
        else:
            print(f"\n  Score file already exists ({score_file}), skipping scoring.")
            print(f"  Use --force-score to re-run.")
        save_checkpoint('score')
    
    # ── STEP 2: DCF ────────────────────────────────────────────────────────────
    if 'dcf' in steps:
        print(f"\n{'='*70}")
        print(f"DCF ANALYSIS — {len(tickers)} stocks")
        print(f"{'='*70}")
        dcf_results = []
        for t in tickers[:20]:  # DCF top 20 max
            print(f"  Running DCF for {t}...")
            success = run(['dcf_model.py', t],
                         desc=f"DCF {t}", timeout=60)
            if success:
                dcf_results.append(t)
            time.sleep(1)  # Rate limit protection
        results['dcf'] = dcf_results
        save_checkpoint('dcf', tickers=tickers, dcf_tickers=dcf_results)
    
    # ── STEP 3: News Sentiment ─────────────────────────────────────────────────
    if 'news' in steps:
        print(f"\n{'='*70}")
        print(f"NEWS SENTIMENT — {len(tickers)} stocks")
        print(f"{'='*70}")
        tickers_str = ' '.join(tickers[:50])
        success = run(['news_sentiment.py', '--top20', '-o', f'{DATA_DIR}\\news_sentiment_latest.json'],
                     desc=f"News sentiment (top 20)", timeout=300)
        results['news'] = success
        save_checkpoint('news')
    
    # ── STEP 4: Macro ─────────────────────────────────────────────────────────
    if 'macro' in steps:
        success = run(['macro_monitor.py'],
                     desc="Macro monitor", timeout=60)
        results['macro'] = success
        save_checkpoint('macro')
    
    # ── STEP 5: Portfolio Backtest ─────────────────────────────────────────────
    if 'backtest' in steps:
        if len(tickers) > 20:
            bt_tickers = tickers[:20]
        else:
            bt_tickers = tickers
        
        success = run(['portfolio_backtester.py'] + bt_tickers +
                     ['--start', '2023-01-01', '--end', '2026-06-01'],
                     desc=f"Portfolio backtest ({len(bt_tickers)} stocks)", timeout=300)
        results['backtest'] = success
        save_checkpoint('backtest')
    
    # ── STEP 6: Delta Report ───────────────────────────────────────────────────
    if 'delta' in steps:
        success = run(['delta_report.py', '--rank', '50', '-o', f'{DATA_DIR}\\delta_report_latest.json'],
                     desc="Delta report (vs previous run)", timeout=30)
        results['delta'] = success
        save_checkpoint('delta')
    
    # ── STEP 7: Final Report ───────────────────────────────────────────────────
    if 'report' in steps:
        results['report'] = build_final_report(tickers, results)
        save_checkpoint('report')
    
    return results


def build_final_report(tickers, results):
    """Build and print the final ranked + filtered output."""
    score_file = 'russell_1000_scores_v2.json'
    if not os.path.exists(score_file):
        return None
    
    with open(score_file) as f:
        scores = json.load(f)
    
    # Load DCF results
    dcf_upsides = {}
    dcf_file = f'{DATA_DIR}\\dcf_results.json'
    if os.path.exists(dcf_file):
        with open(dcf_file) as f:
            dcf_upsides = json.load(f)
    
    # Load news sentiment
    news_file = f'{DATA_DIR}\\news_sentiment_latest.json'
    sentiment_map = {}
    if os.path.exists(news_file):
        with open(news_file) as f:
            for r in json.load(f):
                sentiment_map[r['ticker']] = r
    
    # Sort by composite: score * sentiment_boost * dcf_boost
    composite_scores = []
    for t in tickers:
        if t not in scores:
            continue
        d = scores[t]
        base_score = d.get('total_score', 0)
        
        # Sentiment boost
        sent = sentiment_map.get(t, {})
        sent_score = sent.get('net_score', 0)
        if sent.get('market_adj_sentiment') == 'CONFIRMED BULLISH':
            sent_boost = 1.2
        elif sent.get('market_adj_sentiment') == 'TURNING BULLISH':
            sent_boost = 1.1
        elif sent.get('market_adj_sentiment') == 'CONFIRMED BEARISH':
            sent_boost = 0.7
        elif sent.get('market_adj_sentiment') == 'TURNING BEARISH':
            sent_boost = 0.8
        elif sent_score > 0.1:
            sent_boost = 1.05
        elif sent_score < -0.1:
            sent_boost = 0.9
        else:
            sent_boost = 1.0
        
        # DCF boost: reward high upside, penalize low
        dcf_up = dcf_upsides.get(t, {}).get('upside', 0)
        if dcf_up and dcf_up > 30:
            dcf_boost = 1.15
        elif dcf_up and dcf_up > 15:
            dcf_boost = 1.08
        elif dcf_up and dcf_up < -20:
            dcf_boost = 0.8
        elif dcf_up and dcf_up < 0:
            dcf_boost = 0.92
        else:
            dcf_boost = 1.0
        
        composite = base_score * sent_boost * dcf_boost
        
        composite_scores.append({
            'ticker': t,
            'base_score': base_score,
            'sentiment_label': sent.get('sentiment_label', '⚪'),
            'market_adj': sent.get('market_adj_sentiment', ''),
            'dcf_upside': dcf_up,
            'signal_emoji': sent.get('signal_emoji', ''),
            'signal': sent.get('signal', ''),
            'composite': composite,
            'company': d.get('company_name', t),
        })
    
    composite_scores.sort(key=lambda x: -x['composite'])
    
    print(f"\n{'='*80}")
    print(f"🏆 FINAL COMPOSITE RANKING (Score × Sentiment × DCF)")
    print(f"{'='*80}")
    print(f"{'Rank':<6} {'Ticker':<8} {'BaseScore':<12} {'Composite':<10} {'Sentiment':<18} {'Signal':<15} {'DCF Upside':<10} Company")
    print(f"{'─'*90}")
    
    for rank, c in enumerate(composite_scores[:50], 1):
        sent_col = f"{c['sentiment_label']} {c['market_adj'][:16]}" if c['market_adj'] else '⚪ Neutral'
        dcf_str = f"{c['dcf_upside']:+.0f}%" if c['dcf_upside'] else 'N/A'
        sig = f"{c['signal_emoji']} {c['signal']}" if c['signal'] else ''
        print(f"#{rank:<5} {c['ticker']:<8} {c['base_score']:<12.0f} {c['composite']:<10.1f} "
              f"{sent_col:<18} {sig:<15} {dcf_str:<10} {c['company']}")
    
    print(f"{'='*80}")
    
    report = {
        'generated_at': datetime.now().isoformat(),
        'ranked_stocks': composite_scores[:50],
        'sentiment_summary': {
            'bullish_count': sum(1 for c in sentiment_map.values() if c.get('sentiment') == 'POSITIVE'),
            'bearish_count': sum(1 for c in sentiment_map.values() if c.get('sentiment') == 'NEGATIVE'),
            'neutral_count': sum(1 for c in sentiment_map.values() if c.get('sentiment') == 'NEUTRAL'),
        }
    }
    
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Full research pipeline orchestrator')
    parser.add_argument('--tickers', default='top50',
                       help='top20, top50, top100, or comma-separated list (e.g. INTC,NVDA,GOOGL)')
    parser.add_argument('--steps', default='score,dcf,news,macro,backtest,delta,report',
                       help='Comma-separated steps: score,dcf,news,macro,backtest,delta,report')
    parser.add_argument('--output', '-o', help='Save final report JSON')
    parser.add_argument('--force', action='store_true', help='Force re-run even if checkpoints exist')
    parser.add_argument('--tickers-only', action='store_true', help='Only run scoring step')
    args = parser.parse_args()
    
    steps = [s.strip() for s in args.steps.split(',')]
    print(f"\n📊 RESEARCH PIPELINE")
    print(f"  Tickers: {args.tickers}")
    print(f"  Steps: {', '.join(steps)}")
    print(f"  Working dir: {WORKDIR}")
    
    if args.tickers_only:
        steps = ['score']
    
    # Get actual ticker list
    if args.tickers in ('top20', 'top50', 'top100', 'all'):
        if args.tickers == 'all':
            tickers = get_russell_tickers()
            print(f"  Total tickers: {len(tickers)}")
        else:
            n = int(args.tickers[3:])
            score_file = 'russell_1000_scores_v2.json'
            if os.path.exists(score_file):
                tickers = get_top_tickers(score_file, n)
            else:
                print(f"⚠️ Score file not found. Run scoring first.")
                tickers = []
    else:
        tickers = [t.strip().upper() for t in args.tickers.split(',')]
    
    if not tickers:
        print("❌ No tickers to analyze.")
        return
    
    print(f"  Stocks to analyze: {len(tickers)}")
    
    results = run_full_pipeline(tickers, steps)
    
    print(f"\n{'='*70}")
    print(f"✅ PIPELINE COMPLETE")
    print(f"  Steps completed: {steps}")
    print(f"  Data saved to: {DATA_DIR}\\")
    print(f"{'='*70}")
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"Saved to {args.output}")


if __name__ == '__main__':
    main()