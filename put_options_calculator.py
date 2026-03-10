"""
Long-Dated Put Options Sizing Calculator
=========================================
Calculates position sizing for 6-12 month SPY/SPX puts
used as the short-beta / long-vol component of the BTAL replication.

Inputs: current price, OTM%, expiry, budget
Outputs: contracts, cost, delta, break-even, roll schedule
"""

import numpy as np
from datetime import datetime, timedelta
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")


def black_scholes_put(S, K, T, r, sigma):
    """Black-Scholes put price."""
    if T <= 0:
        return max(K - S, 0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    from scipy.stats import norm
    put = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return put


def put_delta(S, K, T, r, sigma):
    """Black-Scholes put delta."""
    if T <= 0:
        return -1.0 if S < K else 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    from scipy.stats import norm
    return norm.cdf(d1) - 1.0


def calculate_position(spy_price, otm_pct, months_to_expiry, budget_dollars,
                       vol=None, risk_free=0.045, contract_mult=100):
    """
    Calculate put position sizing.

    Args:
        spy_price: current SPY price
        otm_pct: how far OTM (e.g., 0.05 = 5% OTM)
        months_to_expiry: months until expiry
        budget_dollars: max premium to spend
        vol: implied vol (if None, estimated from VIX)
        risk_free: risk-free rate
        contract_mult: shares per contract (100 for SPY)
    """
    strike = spy_price * (1 - otm_pct)
    T = months_to_expiry / 12.0

    if vol is None:
        try:
            vix = yf.Ticker("^VIX")
            vix_hist = vix.history(period="5d")
            vol = vix_hist["Close"].iloc[-1] / 100.0
        except Exception:
            vol = 0.18

    put_price = black_scholes_put(spy_price, strike, T, risk_free, vol)
    delta = put_delta(spy_price, strike, T, risk_free, vol)

    cost_per_contract = put_price * contract_mult
    max_contracts = int(budget_dollars / cost_per_contract) if cost_per_contract > 0 else 0
    total_cost = max_contracts * cost_per_contract
    total_delta = max_contracts * delta * contract_mult
    notional_protected = max_contracts * strike * contract_mult
    breakeven = strike - put_price

    return {
        "spy_price": spy_price,
        "strike": round(strike, 2),
        "otm_pct": otm_pct * 100,
        "months": months_to_expiry,
        "vol": vol,
        "put_price_per_share": round(put_price, 2),
        "cost_per_contract": round(cost_per_contract, 2),
        "max_contracts": max_contracts,
        "total_cost": round(total_cost, 2),
        "delta_per_contract": round(delta, 4),
        "total_delta_shares": round(total_delta, 1),
        "notional_protected": round(notional_protected, 2),
        "breakeven": round(breakeven, 2),
        "annual_cost_pct": round(total_cost / notional_protected * (12 / months_to_expiry) * 100, 2) if notional_protected > 0 else 0,
    }


def main():
    print("=" * 70)
    print("  LONG-DATED PUT OPTIONS CALCULATOR")
    print("  For BTAL Replication: Short-Beta / Long-Vol Component")
    print("=" * 70)

    try:
        spy = yf.Ticker("SPY")
        spy_price = spy.history(period="1d")["Close"].iloc[-1]
    except Exception:
        spy_price = 570.0
    print(f"\n  Current SPY: ${spy_price:.2f}")

    AUM = 550_000
    DEFENSIVE_SLEEVE = 0.30
    PUT_BUDGET_PCT = 0.03
    budget = AUM * PUT_BUDGET_PCT

    print(f"  AUM: ${AUM:,.0f}")
    print(f"  Defensive sleeve: {DEFENSIVE_SLEEVE*100:.0f}%")
    print(f"  Put budget: {PUT_BUDGET_PCT*100:.0f}% of AUM = ${budget:,.0f}")

    scenarios = [
        (0.05, 6),   (0.05, 9),  (0.05, 12),
        (0.10, 6),   (0.10, 9),  (0.10, 12),
        (0.07, 6),   (0.07, 9),  (0.07, 12),
    ]

    print(f"\n  {'OTM%':>5} {'Months':>6} {'Strike':>8} {'Put$/sh':>8} {'$/Cont':>8} "
          f"{'#Cont':>6} {'TotCost':>9} {'Delta':>7} {'B/E':>8} {'Ann%':>6}")
    print(f"  {'-'*82}")

    results = []
    for otm, months in scenarios:
        r = calculate_position(spy_price, otm, months, budget)
        results.append(r)
        print(f"  {r['otm_pct']:>4.0f}% {r['months']:>6} ${r['strike']:>7.0f} "
              f"${r['put_price_per_share']:>7.2f} ${r['cost_per_contract']:>7.0f} "
              f"{r['max_contracts']:>6} ${r['total_cost']:>8,.0f} "
              f"{r['delta_per_contract']:>7.3f} ${r['breakeven']:>7.0f} "
              f"{r['annual_cost_pct']:>5.1f}%")

    print(f"\n  {'='*70}")
    print(f"  RECOMMENDED POSITION")
    print(f"  {'='*70}")

    rec = calculate_position(spy_price, 0.07, 9, budget)
    print(f"""
  Strike: ${rec['strike']:.0f} ({rec['otm_pct']:.0f}% OTM)
  Expiry: 9 months out
  Contracts: {rec['max_contracts']}
  Total cost: ${rec['total_cost']:,.0f} ({rec['total_cost']/AUM*100:.1f}% of AUM)
  Delta exposure: {rec['total_delta_shares']:.0f} SPY share equivalents
  Notional protected: ${rec['notional_protected']:,.0f}
  Break-even: SPY at ${rec['breakeven']:.0f} ({(rec['breakeven']/spy_price-1)*100:.1f}% from current)
  Annualized cost: {rec['annual_cost_pct']:.1f}% of notional

  ROLL SCHEDULE:
  - Buy 9-month puts every 6 months (3 months before expiry)
  - Sell existing puts when rolling (capture remaining time value)
  - Target roll dates: January and July (mid-year / year-end positioning)
  - If VIX < 15 at roll time, consider extending to 12 months for cheaper vol
  - If VIX > 25 at roll time, consider shorter 6-month to reduce premium outlay""")

    rec_spx = calculate_position(spy_price * 10, 0.07, 9, budget,
                                  contract_mult=100)
    print(f"""
  SPX ALTERNATIVE (larger notional per contract):
  - SPX strike: ~${rec_spx['strike']:.0f}
  - Contracts: {rec_spx['max_contracts']}
  - Total cost: ${rec_spx['total_cost']:,.0f}
  - Better for larger AUM (fewer contracts, lower commission)""")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
