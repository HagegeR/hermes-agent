"""
delta_report.py
===============
Compare two score runs and produce a human-readable delta report.
Shows what changed: new entries, dropped stocks, rank movements, score changes.

Usage:
  python3 delta_report.py                            # auto-detect previous vs current
  python3 delta_report.py --prev prev.json --curr curr.json
  python3 delta_report.py --ticker INTC              # show history for one ticker
  python3 delta_report.py --rank 20                 # show top N changes
"""
import sys, json, os, datetime
from datetime import datetime


def load_scores(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return None


def build_rankings(scores: dict, top_n: int = 50):
    """Return sorted list of (ticker, score_dict, rank) for top N."""
    sorted_tickers = sorted(scores.items(), key=lambda x: x[1].get('total_score', 0), reverse=True)
    return [(t, d, r + 1) for r, (t, d) in enumerate(sorted_tickers[:top_n])]


def compute_delta(prev_scores, curr_scores, top_n=50):
    prev_rank = {t: r for t, d, r in build_rankings(prev_scores, top_n * 2)}
    curr_rank = {t: r for t, d, r in build_rankings(curr_scores, top_n * 2)}
    
    prev_top = set(prev_rank.keys())
    curr_top = set(curr_rank.keys())
    
    new_entries = curr_top - prev_top
    dropped = prev_top - curr_top
    still_in = prev_top & curr_top
    
    changes = []
    for t in still_in:
        old_rank = prev_rank.get(t, 999)
        new_rank = curr_rank.get(t, 999)
        old_score = prev_scores.get(t, {}).get('total_score', 0)
        new_score = curr_scores.get(t, {}).get('total_score', 0)
        rank_delta = old_rank - new_rank  # positive = moved up
        score_delta = new_score - old_score
        
        changes.append({
            'ticker': t,
            'old_rank': old_rank,
            'new_rank': new_rank,
            'rank_delta': rank_delta,
            'old_score': old_score,
            'new_score': new_score,
            'score_delta': score_delta,
        })
    
    changes.sort(key=lambda x: (-x['new_score']))
    return {
        'new_entries': [(t, curr_scores[t], curr_rank.get(t)) for t in new_entries],
        'dropped': [(t, prev_scores[t], prev_rank.get(t)) for t in dropped],
        'changes': changes,
    }


def print_delta_report(delta, prev_file, curr_file, top_n=50):
    prev_date = datetime.fromtimestamp(os.path.getmtime(prev_file)).strftime('%Y-%m-%d') if os.path.exists(prev_file) else 'N/A'
    curr_date = datetime.fromtimestamp(os.path.getmtime(curr_file)).strftime('%Y-%m-%d') if os.path.exists(curr_file) else 'N/A'
    
    print(f"\n{'='*80}")
    print(f"📊 DELTA REPORT | Previous: {prev_date} → Current: {curr_date}")
    print(f"{'='*80}")
    
    # New entries (bought signal)
    if delta['new_entries']:
        print(f"\n🟢 NEW TOP {len(delta['new_entries'])} ENTRIES (+buy signal):")
        print(f"{'Ticker':<8} {'Rank':<6} {'Score':<8} {'Val':<5} {'Gth':<6} {'Prof':<6} {'Anl':<5} {'Mom':<5} {'Conf':<5} Company")
        print(f"{'─'*75}")
        for t, d, rank in sorted(delta['new_entries'], key=lambda x: x[2]):
            s = d.get('total_score', 0)
            print(f"{t:<8} #{rank:<5} {s:<8.0f} "
                  f"{d.get('valuation',0):<5.0f} {d.get('growth',0):<6.1f} {d.get('profitability',0):<6.1f} "
                  f"{d.get('analyst',0):<5.0f} {d.get('momentum',0):<5.0f} {d.get('confidence',0):<5.0f} "
                  f"{d.get('company_name', t)}")
    
    # Dropped (sell signal)
    if delta['dropped']:
        print(f"\n🔴 DROPPED FROM TOP {len(delta['dropped'])} (-sell signal):")
        print(f"{'Ticker':<8} {'PrevRank':<10} {'Score':<8} {'Val':<5} {'Gth':<6} {'Prof':<6} {'Anl':<5} {'Mom':<5} {'Conf':<5} Company")
        print(f"{'─'*75}")
        for t, d, old_rank in sorted(delta['dropped'], key=lambda x: x[2]):
            s = d.get('total_score', 0)
            print(f"{t:<8} #{old_rank:<9} {s:<8.0f} "
                  f"{d.get('valuation',0):<5.0f} {d.get('growth',0):<6.1f} {d.get('profitability',0):<6.1f} "
                  f"{d.get('analyst',0):<5.0f} {d.get('momentum',0):<5.0f} {d.get('confidence',0):<5.0f} "
                  f"{d.get('company_name', t)}")
    
    # Biggest rank improvements
    movers_up = [c for c in delta['changes'] if c['rank_delta'] >= 3]
    movers_down = [c for c in delta['changes'] if c['rank_delta'] <= -3]
    
    if movers_up:
        print(f"\n⬆️  RANK IMPROVERS (moved up ≥3):")
        print(f"{'Ticker':<8} {'From':<6} {'To':<5} {'ΔRank':<8} {'Score':<8} {'ScoreΔ':<8} Val  Gth  Prof  Anl  Mom  Conf")
        print(f"{'─'*75}")
        for c in sorted(movers_up, key=lambda x: -x['rank_delta'])[:15]:
            d = curr_scores.get(c['ticker'], {})
            print(f"{c['ticker']:<8} #{c['old_rank']:<5} #{c['new_rank']:<4} {'+' + str(c['rank_delta']):<8} "
                  f"{c['new_score']:<8.0f} {'+' + str(round(c['score_delta'],1)):<8} "
                  f"{d.get('valuation',0):<5.0f} {d.get('growth',0):<5.1f} {d.get('profitability',0):<5.1f} "
                  f"{d.get('analyst',0):<5.0f} {d.get('momentum',0):<5.0f} {d.get('confidence',0):<5.0f}")
    
    if movers_down:
        print(f"\n⬇️  RANK FALLERS (dropped ≥3):")
        print(f"{'Ticker':<8} {'From':<6} {'To':<5} {'ΔRank':<8} {'Score':<8} {'ScoreΔ':<8} Val  Gth  Prof  Anl  Mom  Conf")
        print(f"{'─'*75}")
        for c in sorted(movers_down, key=lambda x: x['rank_delta'])[:15]:
            d = curr_scores.get(c['ticker'], {})
            print(f"{c['ticker']:<8} #{c['old_rank']:<5} #{c['new_rank']:<4} {c['rank_delta']:<8} "
                  f"{c['new_score']:<8.0f} {c['score_delta']:<+8.1f} "
                  f"{d.get('valuation',0):<5.0f} {d.get('growth',0):<5.1f} {d.get('profitability',0):<5.1f} "
                  f"{d.get('analyst',0):<5.0f} {d.get('momentum',0):<5.0f} {d.get('confidence',0):<5.0f}")
    
    # Top 20 current
    print(f"\n🏆 CURRENT TOP 20:")
    print(f"{'Rank':<6} {'Ticker':<8} {'Score':<8} {'Val':<5} {'Gth':<6} {'Prof':<6} {'Anl':<5} {'Mom':<5} {'Conf':<5} Company")
    print(f"{'─'*75}")
    curr_sorted = sorted(curr_scores.items(), key=lambda x: x[1].get('total_score', 0), reverse=True)[:20]
    for rank, (t, d) in enumerate(curr_sorted, 1):
        print(f"#{rank:<5} {t:<8} {d.get('total_score',0):<8.0f} "
              f"{d.get('valuation',0):<5.0f} {d.get('growth',0):<6.1f} {d.get('profitability',0):<6.1f} "
              f"{d.get('analyst',0):<5.0f} {d.get('momentum',0):<5.0f} {d.get('confidence',0):<5.0f} "
              f"{d.get('company_name', '')}")
    
    print(f"\n{'='*80}")
    
    # Summary stats
    new_count = len(delta['new_entries'])
    dropped_count = len(delta['dropped'])
    improved_count = len([c for c in delta['changes'] if c['rank_delta'] > 0])
    declined_count = len([c for c in delta['changes'] if c['rank_delta'] < 0])
    
    print(f"SUMMARY: {new_count} new entries | {dropped_count} dropped | "
          f"{improved_count} improved | {declined_count} declined | "
          f"{len(delta['changes'])} stocks tracked in top {top_n}")
    
    return delta


def save_delta_json(delta, output_path='delta_report.json'):
    with open(output_path, 'w') as f:
        json.dump(delta, f, indent=2, default=str)
    print(f"Saved delta JSON to {output_path}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Delta report for stock screener runs')
    parser.add_argument('--prev', help='Previous scores JSON file')
    parser.add_argument('--curr', help='Current scores JSON file')
    parser.add_argument('--rank', type=int, default=50, help='Top N to track (default 50)')
    parser.add_argument('--ticker', help='Show history for single ticker')
    parser.add_argument('--output', '-o', help='Save JSON output')
    args = parser.parse_args()
    
    # Auto-detect files
    curr_file = args.curr or 'russell_1000_scores_v2.json'
    
    # Find previous run: look for second-most-recent .json score file
    if not args.prev:
        score_files = sorted(
            [f for f in os.listdir('.') if f.startswith('russell_1000_scores') and f.endswith('.json')],
            key=os.path.getmtime, reverse=True
        )
        if len(score_files) >= 2:
            args.prev = score_files[1]
        elif len(score_files) == 1:
            print(f"⚠️ Only one score file found ({score_files[0]}). No previous to compare.")
            args.prev = score_files[0]
    
    prev_file = args.prev or curr_file
    
    prev_scores = load_scores(prev_file)
    curr_scores = load_scores(curr_file)
    
    if not curr_scores:
        print(f"❌ Current scores file not found: {curr_file}")
        sys.exit(1)
    
    if not prev_scores:
        print(f"⚠️ Previous scores file not found: {prev_file}. Showing current top 50 only.")
        prev_scores = {}
    
    # Single ticker history
    if args.ticker:
        ticker = args.ticker.upper()
        for scores, label, fname in [(curr_scores, 'CURRENT', curr_file), (prev_scores, 'PREVIOUS', prev_file)]:
            if ticker in scores:
                d = scores[ticker]
                print(f"\n{ticker} ({label} — {fname}):")
                print(f"  Score: {d.get('total_score', 0):.0f}")
                print(f"  PE: {d.get('pe_ratio', 'N/A')} | RevG: {d.get('revenue_growth', 'N/A')}")
                print(f"  Price: ${d.get('current_price', 'N/A')} | MCap: ${d.get('market_cap', 'N/A')}")
                print(f"  Company: {d.get('company_name', 'N/A')}")
        sys.exit(0)
    
    delta = compute_delta(prev_scores, curr_scores, args.rank)
    print_delta_report(delta, prev_file, curr_file, args.rank)
    
    if args.output:
        save_delta_json(delta, args.output)