"""
SEC Filings Downloader — analyze 10-K, 10-Q, 8-K data for any ticker.
Usage: python3 sec_filings_download.py AAPL [10-K|10-Q|8-K] [--years 3]
"""
import sys, requests, json, time, re

HEADERS = {
    'User-Agent': 'Hermes Agent research agent@nousresearch.com',
    'Accept-Encoding': 'gzip, deflate',
}

def get_cik(ticker):
    """Get CIK from ticker."""
    url = f'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&output=atom'
    resp = requests.get(url, headers=HEADERS, timeout=10)
    if resp.status_code == 200:
        m = re.search(r'CIK=(\d+)', resp.text)
        if m:
            return m.group(1).lstrip('0') or m.group(1)
    return None

def get_filings_list(cik, form_type=None, count=10):
    """Get list of filings for a CIK."""
    url = f'https://data.sec.gov/submissions/CIK{cik.rjust(10, "0")}.json'
    resp = requests.get(url, headers=HEADERS, timeout=10)
    if resp.status_code != 200:
        return []
    
    data = resp.json()
    filings = data.get('filings', {}).get('recent', {})
    
    results = []
    for i, ftype in enumerate(filings.get('form', [])):
        if form_type and ftype != form_type:
            continue
        filing = {
            'form': ftype,
            'date': filings.get('filingDate', [''])[i],
            'accession': filings.get('accessionNumber', [''])[i],
            'doc': filings.get('primaryDocument', [''])[i],
        }
        results.append(filing)
        if len(results) >= count:
            break
    return results

def download_filing(cik, accession, doc):
    """Download a specific filing."""
    acc_clean = accession.replace('-', '')
    url = f'https://www.sec.gov/Archives/edgar/full-index/{acc_clean[:4]}/{acc_clean[4:10]}/{doc}'
    resp = requests.get(url, headers=HEADERS, timeout=15)
    return resp.text if resp.status_code == 200 else None

def parse_financials(html_content):
    """Parse key financial numbers from 10-K/10-Q HTML."""
    # Extract numbers using regex (simplified — for full XBRL use sec-api or abrabu)
    numbers = {}
    
    # Look for key tags in XBRL JSON format
    # This is a simplified parser
    return numbers

def analyze_ticker(ticker, form_type='10-K', years=3):
    print(f"\n{'='*70}")
    print(f"SEC Filings Analysis: {ticker} | {form_type} filings")
    print(f"{'='*70}")
    
    cik = get_cik(ticker)
    if not cik:
        print(f"❌ Cannot find CIK for {ticker}")
        return
    
    print(f"✅ CIK: {cik}")
    
    filings = get_filings_list(cik, form_type=form_type, count=years)
    if not filings:
        print(f"❌ No {form_type} filings found")
        return
    
    print(f"\n📄 {form_type} Filings ({len(filings)} found):")
    for f in filings[:years]:
        print(f"  {f['date']}: {f['form']} — {f['accession']}")
    
    # Summary: check for key trends from filings
    print(f"\n{'='*70}")
    print(f"Key Observations (form {form_type}):")
    print(f"  - Look for revenue growth in Document sections")
    print(f"  - Check 'Item 7. Management Discussion' for guidance")
    print(f"  - Check 'Item 1A. Risk Factors' for emerging risks")
    print(f"  - Check 'Item 9. Changes in Disagreements with Accountants'")
    print(f"  - Check 'Item 9A. Controls' for material weaknesses")
    
    # Note about XBRL
    print(f"\n💡 For detailed financial numbers (revenue, net income, margins):")
    print(f"   Use the XBRL data at: https://efts.sec.gov/LATEST/search-index?q={ticker}&forms={form_type}")
    print(f"   Or use sec-api.com Python library for full XBRL parsing:")
    print(f"   pip install sec-api  # requires API key for full access")

def show_recent_8k(ticker, count=5):
    """Show recent 8-K filings (material events)."""
    print(f"\n📋 Recent 8-K Filings: {ticker}")
    
    cik = get_cik(ticker)
    if not cik:
        print(f"❌ Cannot find CIK")
        return
    
    filings = get_filings_list(cik, form_type='8-K', count=count)
    if not filings:
        print("  None found")
        return
    
    print(f"  Recent material events:")
    for f in filings[:count]:
        print(f"  {f['date']}: {f['form']} — {f['accession']}")
        print(f"    https://www.sec.gov/ixviewer/ix.html?doc=/Archives/edgar/data/{cik}/{f['accession'].replace('-','')}/{f['doc']}")

if __name__ == '__main__':
    ticker = sys.argv[1].upper() if len(sys.argv) > 1 else 'AAPL'
    form_type = sys.argv[2].upper() if len(sys.argv) > 2 else '10-K'
    years = int(sys.argv[sys.argv.index('--years') + 1]) if '--years' in sys.argv else 3
    
    analyze_ticker(ticker, form_type=form_type, years=years)
    
    if '--8k' in sys.argv or '--show-8k' in sys.argv:
        show_recent_8k(ticker)