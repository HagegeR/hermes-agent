#!/usr/bin/env python3
"""
V4 GROWTH SCORING ENGINE — Pure scoring function.
Does NOT read DB or detect themes. Accepts pre-computed macro_context dict.
========================================================
Input: stock_data dict + macro_context dict (from macro_context.py)
Output: (score, breakdown)

Components (rebalanced from expert analysis):
  D1: Analyst Consensus  (25pts) — # analysts, Buy/Sell ratio, PT gap to price
  D2: Earnings Quality   (20pts) — YoY acceleration, operating leverage, ROE
  D3: Revenue Visibility (20pts) — backlog proxy, NRR proxy, recurring rev
  D4: Institutional      (15pts) — 13F buys, sovereign funds, activist stakes
  D5: Macro Sensitivity  (10pts) — Iran/oil/rate exposure (neutral=5, war-proof=10, exposed=0)
  D6: Supply Chain       (5pts)  — NVDA/Meta/Google chain alignment
  D7: Technical Position (5pts)  — % from ATH, buy zone (JUST timing, not conviction)
  D8: Catalysts          +10 bonus — earnings, index adds, macro events
  Country Risk           -15 penalty
  Beta Risk               -5 penalty
  = max 110 → normalized to 100

Design principles:
  - Fundamentals dominate (65%: D1-D4)
  - Macro sensitivity is capped at 10% — a war-proof stock maxes this, YPF gets 2
  - Technicals are 5% — 50% below ATH is interesting but meaningless without D1-D4
  - Analyst consensus with 58 analysts and 0 Sells is more predictive than simple PT
  - Revenue backlog/RPO is separate from earnings growth
  - Uses Fear & Greed, VIX, yield curve, sector momentum from macro_context
"""

import datetime
import json
import sqlite3

DB_PATH = "/root/trading_audit.db"

# Theme impacts for macro sensitivity scoring (moved here for V4 clarity)
MACRO_THEMES = {
    "ai_infrastructure": {
        "impact": {
            "WINNERS": [
                "technology",
                "nvda",
                "amd",
                "avgo",
                "mrvl",
                "swks",
                "vrt",
                "data center",
                "vertiv",
                "power",
                "infrastructure",
                "utilities",
                "xel",
                "ceg",
                "vst",
                "nrg",
                "so",
                "semiconductor",
                "ai",
                "arvr",
                "computing",
            ],
            "LOSERS": [],
        },
    },
    "iran_peace": {
        "impact": {
            "WINNERS": [
                "airlines",
                "dal",
                "ual",
                "aalb",
                "luv",
                "consumer cyclical",
                "restaurants",
                "yum",
                "mcd",
                "sbux",
                "transportation",
                "fedex",
                "fdx",
                "ups",
                "xpo",
                "saia",
                "travel",
                "booking",
                "bkng",
                "expedia",
                "expe",
            ],
            "LOSERS": [
                "energy",
                "oil",
                "gas",
                "xom",
                "cvx",
                "cop",
                "oxy",
                "pbr",
                "ypf",
                "defense",
                "lmt",
                "noc",
                "rtx",
                "gd",
            ],
        },
    },
    "recession_fear": {
        "impact": {
            "WINNERS": [
                "utilities",
                "xlu",
                "consumer staples",
                "xlp",
                "wmt",
                "cost",
                "healthcare",
                "xlv",
                "defensive",
            ],
            "LOSERS": [
                "consumer cyclical",
                "technology",
                "xlk",
                "financial",
                "xlf",
                "industrials",
                "small cap",
                "iwm",
            ],
        },
    },
}

COUNTRY_RISK = {
    "china": {"penalty": 12, "tickers": ["zto", "baba", "jd", "ntes", "pdd", "bidi", "nio", "xpev"]},
    "argentina": {"penalty": 8, "tickers": ["ypf", "ggal", "bma", "cepu", "pam"]},
    "brazil": {"penalty": 6, "tickers": ["xp", "pbr", "vale", "abev"]},
    "turkey": {"penalty": 8, "tickers": ["tch"]},
    "india": {"penalty": 3, "tickers": []},
}

# Authority for normalization — sum powers the /MAX_RAW divisor below.
# When you bump a dimension's cap or add one, change only this dict.
DIMENSION_WEIGHTS: dict[str, int] = {
    "D1_analyst_consensus": 25,
    "D2_earnings_quality": 20,
    "D3_revenue_visibility": 20,
    "D4_institutional": 15,
    "D5_macro_sensitivity": 10,
    "D6_supply_chain": 5,
    "D7_technical_position": 5,
    "D8_catalysts": 10,  # bonus cap, not guaranteed
    "D9_insider_conviction": 10,
    "D10_political_signal": 5,
}
MAX_RAW = sum(DIMENSION_WEIGHTS.values())  # 125


def v4_score_stock(row, macro_context=None):
    """
    V4 scoring. row: dict with stock fundamentals, macro_context from macro_context.get_context().

    Dimensions:
      D1 Analyst Consensus(25) + D2 Earnings Quality(20) + D3 Revenue Visibility(20) +
      D4 Institutional(15) + D5 Macro Sensitivity(10) + D6 Supply Chain(5) + D7 Technical(5) +
      D8 Catalysts(+10 bonus) - Country Risk(15) - Beta Risk(5)
    """
    if macro_context is None:
        macro_context = {}

    themes = macro_context.get("themes", [])
    macro_context.get("fear_greed") or {}
    vix = macro_context.get("vix")
    yield_curve = macro_context.get("yield_curve") or {}
    macro_context.get("sector_momentum") or {}
    commodity_momentum = macro_context.get("commodity_momentum") or {}
    theme_confidence = macro_context.get("theme_confidence", {})
    theme_burst = macro_context.get("theme_burst", {})

    score = 0
    breakdown = {}

    ticker = str(row.get("ticker", "")).lower()
    sector = str(row.get("sector", "")).lower()
    industry = str(row.get("industry", "")).lower()
    name = str(row.get("name", "")).lower()
    full_text = f"{ticker} {sector} {industry} {name}"

    price = float(row.get("price", 0) or row.get("regularMarketPrice", 0) or 0)
    p52h = float(row.get("52w_high", 1) or 1)
    p52l = float(row.get("52w_low", 0.01) or 0.01)
    ma200 = float(row.get("200dma", price) or price or 1)

    # ── D1: ANALYST CONSENSUS (25pts) ──
    d1 = 0
    target_mean = row.get("target_mean") or row.get("analyst_target")
    analyst_count = int(row.get("number_of_analysts") or row.get("analyst_count") or 0)
    recommendation = str(row.get("recommendation", "") or "").lower()

    if analyst_count >= 40:
        d1 += 8
    elif analyst_count >= 25:
        d1 += 6
    elif analyst_count >= 15:
        d1 += 5
    elif analyst_count >= 8:
        d1 += 3
    elif analyst_count >= 3:
        d1 += 2

    if "strong_buy" in recommendation:
        d1 += 5
    elif "buy" in recommendation:
        d1 += 3
    elif "sell" in recommendation:
        d1 -= 5
    elif "hold" in recommendation:
        d1 += 1

    upside_pct = 0
    if target_mean and target_mean > 0 and price > 0:
        upside_pct = (target_mean - price) / price * 100
        if upside_pct > 30:
            d1 += 12
        elif upside_pct > 20:
            d1 += 10
        elif upside_pct > 15:
            d1 += 8
        elif upside_pct > 10:
            d1 += 6
        elif upside_pct > 5:
            d1 += 4
        elif upside_pct > 0:
            d1 += 2
        elif upside_pct > -5:
            d1 += 1

    d1 = min(25, max(0, d1))
    score += d1
    breakdown["analyst_consensus"] = d1
    breakdown["analyst_count"] = analyst_count
    breakdown["analyst_upside"] = round(upside_pct, 1)

    # ── D2: EARNINGS QUALITY (20pts) ──
    d2 = 0
    eg = float(row.get("earnings_growth", 0) or 0)
    rg = float(row.get("revenue_growth", 0) or 0)
    gm = float(row.get("gross_margin", 0) or 0)
    om = float(row.get("operating_margin", 0) or 0)
    roe = float(row.get("roe", 0) or 0)

    if eg > 0.30 and rg > 0.20:
        d2 += 8
    elif eg > 0.20 or rg > 0.30:
        d2 += 6
    elif eg > 0.15 or rg > 0.20:
        d2 += 5
    elif eg > 0.10 or rg > 0.15:
        d2 += 4
    elif eg > 0.05 or rg > 0.10:
        d2 += 3
    elif eg > 0 or rg > 0:
        d2 += 2

    if gm > 0.50 and om > 0.20:
        d2 += 6
    elif gm > 0.35 and om > 0.15:
        d2 += 4
    elif gm > 0.25 and om > 0.10:
        d2 += 3
    elif gm > 0.15:
        d2 += 2

    if roe > 0.25:
        d2 += 6
    elif roe > 0.20:
        d2 += 4
    elif roe > 0.15:
        d2 += 3
    elif roe > 0.10:
        d2 += 2
    elif roe > 0:
        d2 += 1

    d2 = min(20, max(0, d2))
    score += d2
    breakdown["earnings_quality"] = d2

    # ── D3: REVENUE VISIBILITY (20pts) ──
    d3 = 0

    if rg > 0.20 and gm > 0.50:
        d3 += 10
    elif rg > 0.15 and gm > 0.40:
        d3 += 8
    elif rg > 0.10 and gm > 0.30:
        d3 += 6
    elif rg > 0.05 and gm > 0.25:
        d3 += 4
    elif rg > 0:
        d3 += 2

    backlog_sectors = [
        "software",
        "semiconductor",
        "defense",
        "aerospace",
        "infrastructure",
        "data center",
        "semiconductor equipment",
    ]
    if any(s.lower() in full_text for s in backlog_sectors):
        d3 += 3

    recurring = ["saas", "subscription", "software", "cloud", "services"]
    if any(s.lower() in full_text for s in recurring):
        d3 += 4

    if gm > 0.60 and rg > 0.15:
        d3 += 3

    d3 = min(20, max(0, d3))
    score += d3
    breakdown["revenue_visibility"] = d3

    # ── D4: INSTITUTIONAL SIGNALS (15pts) ──
    d4 = 0

    if analyst_count >= 40:
        d4 += 5
    elif analyst_count >= 25:
        d4 += 4
    elif analyst_count >= 15:
        d4 += 3
    elif analyst_count >= 8:
        d4 += 2

    t1_sectors = [
        "semiconductor",
        "software",
        "ai",
        "defense",
        "healthcare",
        "financial",
        "infrastructure",
        "energy",
        "gold",
        "mining",
    ]
    if any(s.lower() in full_text for s in t1_sectors):
        d4 += 4

    if roe > 0.15 and rg > 0.10 and gm > 0.30:
        d4 += 4
    elif roe > 0.10 and rg > 0.05:
        d4 += 2

    mc = float(row.get("market_cap", 0) or row.get("marketCap", 0) or 0)
    if mc > 50e9:
        d4 += 2
    elif mc > 10e9:
        d4 += 1

    d4 = min(15, max(0, d4))
    score += d4
    breakdown["institutional"] = d4

    # ── D5: MACRO SENSITIVITY (10pts) ──
    d5 = 5

    iran_exposed = any(s.lower() in full_text for s in ["energy", "oil", "gas", "xom", "cvx", "ypf", "pbr"])
    war_proof = any(
        s.lower() in full_text
        for s in [
            "semiconductor",
            "nvda",
            "amd",
            "avgo",
            "defense",
            "lmt",
            "rtx",
            "gd",
            "noc",
            "software",
            "saas",
        ]
    )

    if "iran_peace" in themes:
        confidence = theme_confidence.get("iran_peace", 0.5)
        if any(s.lower() in full_text for s in ["airlines", "dal", "ual", "travel", "consumer cyclical"]):
            d5 += round(3 * confidence)
        if iran_exposed:
            d5 -= round(4 * confidence)
        if any(s.lower() in full_text for s in ["defense", "lmt", "noc", "rtx"]):
            d5 -= round(3 * confidence)
    else:
        if war_proof:
            d5 += 2

    spread = yield_curve.get("spread", 100)
    if spread < 0:
        if any(s.lower() in full_text for s in ["banks", "jpm", "bac", "gs", "financial"]):
            d5 -= 2

    for asset, tgt in [("gold", ["gold", "mining"]), ("oil", ["energy", "oil", "gas"])]:
        info = commodity_momentum.get(asset, {})
        if isinstance(info, dict) and info.get("peak_trough_pct", 0) < -5:
            if any(s.lower() in full_text[:30] for s in tgt):
                d5 -= 2

    burst_info = theme_burst.get("iran_peace") or theme_burst.get("energy_shock") or {}
    if burst_info and abs(d5 - 5) > 1:
        burst_amplifier = burst_info.get("burst_multiplier", 1.0)
        if burst_amplifier > 1.2:
            d5 = round(5 + (d5 - 5) * burst_amplifier)

    d5 = min(10, max(0, d5))
    score += d5
    breakdown["macro_sensitivity"] = d5

    # ── D6: SUPPLY CHAIN POSITION (5pts) ──
    d6 = 0
    ai_supply = [
        "semiconductor",
        "nvda",
        "amd",
        "avgo",
        "mrvl",
        "vrt",
        "vertiv",
        "data center",
        "power",
        "infrastructure",
    ]
    if any(s.lower() in full_text for s in ai_supply):
        d6 += 3
    hyperscaler = ["cloud", "software", "ai", "arvr", "computing"]
    if any(s.lower() in full_text for s in hyperscaler):
        d6 += 2
    d6 = min(5, d6)
    score += d6
    breakdown["supply_chain"] = d6

    # ── D7: TECHNICAL POSITION (5pts) ──
    pos = (price - p52l) / (p52h - p52l) if (p52h - p52l) > 0 else 0.5
    above_200 = (price - ma200) / ma200 if ma200 > 0 else 0

    if pos <= 0.35:
        d7 = 5
    elif pos <= 0.50:
        d7 = 4
    elif pos <= 0.65:
        d7 = 3
    elif pos <= 0.85:
        d7 = 2
    else:
        d7 = 1

    if -0.10 < above_200 < 0.05:
        d7 = min(5, d7 + 1)

    d7 = min(5, max(1, d7))
    score += d7
    breakdown["technical_position"] = d7
    breakdown["pos_52w"] = round(pos, 3)

    # ── D8: CATALYSTS (+10 bonus) ──
    catalyst_pts = 0
    for cat in macro_context.get("catalysts", []):
        if cat.get("ticker", "").lower() == ticker:
            try:
                cat_date = datetime.datetime.fromisoformat(str(cat["date"]).replace("Z", "")[:19])
                days_until = (cat_date - datetime.datetime.now()).days
            except:
                days_until = 30
            cat_type = cat.get("type", "")
            if cat_type == "earnings":
                if days_until <= 7:
                    catalyst_pts += 6
                elif days_until <= 14:
                    catalyst_pts += 4
                elif days_until <= 30:
                    catalyst_pts += 2
            elif cat_type == "dividend":
                if days_until <= 14:
                    catalyst_pts += 1

    if analyst_count >= 25 and mc > 10e9 and d4 >= 8 and pos < 0.50:
        catalyst_pts += 3
    if eg > 0.20:
        catalyst_pts = max(catalyst_pts, 2)

    catalyst_pts = min(10, catalyst_pts)
    score += catalyst_pts
    breakdown["catalysts"] = catalyst_pts

    # ── D9: INSIDER CONVICTION (0-10) ──
    d9 = 0.0
    d10 = 0.0
    insider_info = row.get("insider_info") or {}
    if not insider_info:
        # Try to fetch from DB if not provided
        try:
            from fetcher.edgar_insider import score_insider

            insider_info = score_insider(ticker) or {}
        except Exception:
            insider_info = {}

    d9_val = insider_info.get("d9")
    d10_val = insider_info.get("d10")
    if d9_val is not None:
        d9 = float(d9_val)
        score += d9
        breakdown["insider_conviction"] = round(d9, 1)
    if d10_val is not None:
        d10 = float(d10_val)
        score += d10
        breakdown["political_signal"] = round(d10, 1)

    # Store insider detail in breakdown for transparency
    if "detail" in insider_info:
        breakdown["insider_detail"] = insider_info["detail"]

    # ── PENALTIES ──
    risk_penalty = 0
    cn_tickers = {
        "zto": 12,
        "baba": 12,
        "jd": 12,
        "ntes": 12,
        "pdd": 12,
        "bidi": 12,
        "nio": 12,
        "xpev": 12,
        "ypf": 8,
        "ggal": 8,
        "bma": 8,
        "xp": 6,
        "pbr": 6,
        "vale": 6,
        "abev": 6,
        "tch": 8,
    }
    risk_penalty = cn_tickers.get(ticker, 0)
    if "china" in full_text or "adr" in name:
        risk_penalty = max(risk_penalty, 8)
    if "brazil" in full_text:
        risk_penalty = max(risk_penalty, 6)
    score -= risk_penalty
    breakdown["country_risk"] = -risk_penalty

    beta = float(row.get("beta", 1) or 1)
    if beta <= 0.5:
        beta_penalty = 0
    elif beta <= 0.8:
        beta_penalty = 0
    elif beta <= 1.0:
        beta_penalty = -1
    elif beta <= 1.5:
        beta_penalty = -2
    elif beta <= 2.0:
        beta_penalty = -3
    elif beta <= 3.0:
        beta_penalty = -4
    else:
        beta_penalty = -5
    if vix and vix > 25 and beta > 1.5:
        beta_penalty = min(-5, beta_penalty - 2)
    score += beta_penalty
    breakdown["beta_risk"] = beta_penalty

    # Normalize: max raw = sum(DIMENSION_WEIGHTS) - penalties don't count toward the cap
    normalized = max(0, min(100, score / MAX_RAW * 100))
    return round(normalized, 1), breakdown


# Alias for backwards compatibility (screeners still import v3_score_stock)
def v3_score_stock(row, macro_context=None):
    return v4_score_stock(row, macro_context)


# Keep score_screener_results for compatibility
def score_screener_results(macro_keywords=None, context=None):
    from macro_context import get_context

    if context is None:
        context = get_context(days_back=5)
    conn = sqlite3.connect(DB_PATH)
    import pandas as pd

    screener = pd.read_sql("SELECT id, data FROM screener_runs ORDER BY id DESC LIMIT 1", conn)
    conn.close()
    if screener.empty:
        print("No screener data found")
        return
    results = json.loads(screener["data"].iloc[0])
    print(f"Macro context: themes={context['themes']}, sentiment={context.get('sentiment', ''):+.2f}")
    scored = []
    for row in results:
        v4, breakdown = v4_score_stock(row, context)
        scored.append(
            {
                **row,
                "v4_score": v4,
                "v4_breakdown": str(breakdown),
                "score_date": datetime.datetime.now().isoformat(),
            }
        )
    scored.sort(key=lambda x: -x.get("v4_score", 0))
    print(f"\n  V4 scoring applied to {len(scored)} stocks via score_screener_results")
    with open("/root/hermes/hermes-workstation/data/screener_v4_scored.json", "w") as f:
        json.dump(scored, f, indent=2, default=str)
    return scored


if __name__ == "__main__":
    from macro_context import get_context

    ctx = get_context()

    for name, row in [
        (
            "NVDA",
            {
                "ticker": "NVDA",
                "name": "NVIDIA Corporation",
                "sector": "technology",
                "industry": "semiconductor",
                "price": 950,
                "52w_high": 1100,
                "52w_low": 400,
                "200dma": 850,
                "beta": 1.6,
                "target_mean": 1300,
                "number_of_analysts": 45,
                "recommendation": "strong_buy",
                "earnings_growth": 0.65,
                "revenue_growth": 0.55,
                "roe": 0.55,
                "gross_margin": 0.72,
                "operating_margin": 0.55,
            },
        ),
        (
            "DAL",
            {
                "ticker": "DAL",
                "name": "Delta Air Lines",
                "sector": "airlines",
                "industry": "transportation",
                "price": 65,
                "52w_high": 75,
                "52w_low": 40,
                "200dma": 58,
                "beta": 1.4,
                "target_mean": 85,
                "number_of_analysts": 22,
                "recommendation": "buy",
                "earnings_growth": 0.45,
                "revenue_growth": 0.20,
                "roe": 0.30,
                "gross_margin": 0.25,
                "operating_margin": 0.12,
            },
        ),
        (
            "YPF",
            {
                "ticker": "YPF",
                "name": "YPF Sociedad Anonima",
                "sector": "energy",
                "industry": "oil gas",
                "price": 25,
                "52w_high": 40,
                "52w_low": 10,
                "200dma": 22,
                "beta": 1.8,
                "target_mean": 28,
                "number_of_analysts": 6,
                "recommendation": "buy",
                "earnings_growth": 0.05,
                "revenue_growth": 0.03,
                "roe": 0.08,
                "gross_margin": 0.15,
                "operating_margin": 0.05,
            },
        ),
    ]:
        s, b = v4_score_stock(row, ctx)
        dims = {k: v for k, v in b.items() if not isinstance(v, str) and not isinstance(v, list)}
        print(
            f"{name:6s} V4={s:5.1f}  D1={b['analyst_consensus']:2d} D2={b['earnings_quality']:2d} D3={b['revenue_visibility']:2d} D4={b.get('institutional', 0):2d} D5={b['macro_sensitivity']:2d} D6={b['supply_chain']:2d} D7={b['technical_position']:2d} Cat={b['catalysts']:2d} Cr={b['country_risk']:+3d}"
        )
