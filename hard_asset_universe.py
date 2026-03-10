"""
Tactical Hard Asset ETF — Universe
===================================
Static and tactical tickers, tier labels. No K-1s.
"""

# Static sleeve (never traded)
COM = "COM"   # Direxion Auspice Broad Commodity
SHY = "SHY"   # Short Treasury / cash proxy

# Tactical 14-ETF universe by tier (max 2 per tier in selection)
TACTICAL_TIERS = {
    1: ["TILL", "PDBA", "MOO", "LAND"],   # Agriculture
    2: ["XLE", "XOP", "OIH"],             # Energy
    3: ["COPX", "LIT", "PICK", "REMX"],   # Industrial Metals
    4: ["GDX", "SLV", "SIL"],              # Precious Metals
}

def get_all_tactical():
    out = []
    for tier, tickers in TACTICAL_TIERS.items():
        out.extend(tickers)
    return out

def get_ticker_to_tier():
    d = {}
    for tier, tickers in TACTICAL_TIERS.items():
        for t in tickers:
            d[t] = tier
    return d

ALL_TACTICAL = get_all_tactical()
TICKER_TO_TIER = get_ticker_to_tier()

# All tickers needed for backtest (COM + SHY + tactical + COMOD)
COMOD_TICKERS = ["DBC", "DX-Y.NYB"]  # DBC = commodity trend; DX-Y.NYB = DXY
BACKTEST_TICKERS = [COM, SHY] + ALL_TACTICAL + COMOD_TICKERS
