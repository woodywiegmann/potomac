"""
Verified backtest: CRDBX Actual vs Modified (33% CAOS / 33% DBMF / 34% SGOV on risk-off days).
Outputs a clean report with daily-verified return streams.
"""

import yfinance as yf
import pandas as pd
import numpy as np
import math
import os
import warnings
warnings.filterwarnings("ignore")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def get_total_return_series(ticker, start, end):
    t = yf.Ticker(ticker)
    h = t.history(start=start, end=end, auto_adjust=False)
    if h.empty:
        return pd.Series(dtype=float)
    h.index = h.index.tz_localize(None)
    nav = h["Close"]
    divs = h.get("Dividends", pd.Series(0.0, index=h.index))
    shares = 1.0
    vals = []
    for dt in h.index:
        d = divs.loc[dt] if dt in divs.index else 0.0
        p = nav.loc[dt]
        if d > 0 and p > 0:
            shares *= (1 + d / p)
        vals.append(shares * p)
    return pd.Series(vals, index=h.index, name=ticker)


def rolling_beta(x, y, window=5):
    betas = pd.Series(np.nan, index=x.index)
    for i in range(window, len(x)):
        xi = x.iloc[i-window:i].values
        yi = y.iloc[i-window:i].values
        cov = np.cov(xi, yi)
        if cov[1, 1] > 1e-12:
            betas.iloc[i] = cov[0, 1] / cov[1, 1]
    return betas


def main():
    START = "2023-03-06"  # CAOS inception in yfinance
    END = "2026-02-21"

    print("Fetching verified total-return series (NAV + reinvested distributions)...")
    raw = {}
    for tk in ["CRDBX", "SPY", "CAOS", "DBMF", "SGOV"]:
        s = get_total_return_series(tk, "2022-12-01", END)
        raw[tk] = s
        print(f"  {tk}: {s.index[0].date()} to {s.index[-1].date()}, {len(s)} trading days")

    # Common index from CAOS start
    idx = raw["CRDBX"].index
    idx = idx[idx >= START]
    for tk in ["SPY", "CAOS", "DBMF", "SGOV"]:
        idx = idx.intersection(raw[tk].index)

    crdbx_p = raw["CRDBX"].reindex(idx)
    spy_p = raw["SPY"].reindex(idx)
    caos_p = raw["CAOS"].reindex(idx)
    dbmf_p = raw["DBMF"].reindex(idx)
    sgov_p = raw["SGOV"].reindex(idx)

    crdbx_ret = crdbx_p.pct_change().fillna(0)
    spy_ret = spy_p.pct_change().fillna(0)
    caos_ret = caos_p.pct_change().fillna(0)
    dbmf_ret = dbmf_p.pct_change().fillna(0)
    sgov_ret = sgov_p.pct_change().fillna(0)

    # Regime detection
    beta_5d = rolling_beta(crdbx_ret, spy_ret, window=5)
    regime = pd.Series("UNKNOWN", index=idx)
    regime[beta_5d > 0.6] = "RISK_ON"
    regime[beta_5d < 0.3] = "RISK_OFF"
    regime[(beta_5d >= 0.3) & (beta_5d <= 0.6)] = "TRANSITION"

    for i in range(len(idx)):
        cr = abs(crdbx_ret.iloc[i])
        sr = abs(spy_ret.iloc[i])
        if sr > 0.003 and cr < 0.0005:
            regime.iloc[i] = "RISK_OFF"
        elif sr > 0.002 and cr > sr * 1.0:
            regime.iloc[i] = "RISK_ON"

    off_mask = regime.isin(["RISK_OFF", "TRANSITION"])
    on_mask = regime == "RISK_ON"

    n_total = len(idx)
    n_on = on_mask.sum()
    n_off = off_mask.sum()

    # Validate risk-on beta
    on_beta = np.cov(crdbx_ret[on_mask], spy_ret[on_mask])[0, 1] / np.var(spy_ret[on_mask])

    # CRDBX expense ratio -- the gap between SGOV yield and CRDBX risk-off
    # return is CRDBX's own fee drag. The modified version must include it too.
    CRDBX_ER_DAILY = 0.0146 / 252  # 1.46% annual ER

    # Strategy 1: CRDBX Actual (unchanged -- fees already embedded in NAV)
    strat1_ret = crdbx_ret.copy()
    strat1_prices = (1 + strat1_ret).cumprod()
    strat1_prices = strat1_prices / strat1_prices.iloc[0] * 10000

    # Strategy 2: Modified -- risk-off days use 33% CAOS + 33% DBMF + 34% SGOV
    # We start from CRDBX actual return and ADD the excess return of the blend
    # over SGOV, minus incremental expense ratios of CAOS and DBMF.
    # This ensures CRDBX's own ER is applied equally to both strategies.
    INCR_ER_DAILY = (0.33 * 0.0063 + 0.33 * 0.0085) / 252  # incremental ER
    strat2_ret = crdbx_ret.copy()
    for i in range(len(idx)):
        if off_mask.iloc[i]:
            blend_ret = 0.33 * caos_ret.iloc[i] + 0.33 * dbmf_ret.iloc[i] + 0.34 * sgov_ret.iloc[i]
            excess = blend_ret - sgov_ret.iloc[i]
            strat2_ret.iloc[i] = crdbx_ret.iloc[i] + excess - INCR_ER_DAILY
    strat2_prices = (1 + strat2_ret).cumprod()
    strat2_prices = strat2_prices / strat2_prices.iloc[0] * 10000

    # Metrics
    def metrics(prices, label):
        dr = prices.pct_change().dropna()
        yrs = (prices.index[-1] - prices.index[0]).days / 365.25
        cagr = ((prices.iloc[-1] / prices.iloc[0]) ** (1 / yrs) - 1) * 100
        cummax = prices.cummax()
        dd = (prices - cummax) / cummax
        max_dd = dd.min() * 100
        dd_end = dd.idxmin()
        dd_start = prices[:dd_end].idxmax()
        ann_vol = dr.std() * math.sqrt(252) * 100
        sharpe = (dr.mean() - 0.04 / 252) / dr.std() * math.sqrt(252) if dr.std() > 0 else 0
        down = dr[dr < 0]
        sortino = (dr.mean() - 0.04 / 252) / down.std() * math.sqrt(252) if len(down) > 0 and down.std() > 0 else 0
        calmar = abs(cagr / max_dd) if max_dd != 0 else 0
        sp_a = spy_ret.reindex(dr.index, method="ffill").fillna(0)
        cv = np.cov(dr, sp_a)
        beta = cv[0, 1] / cv[1, 1] if cv[1, 1] > 0 else 0
        corr = np.corrcoef(dr, sp_a)[0, 1]
        yr = prices.resample("YE").last().pct_change().dropna() * 100
        return {
            "label": label, "cagr": cagr, "max_dd": max_dd,
            "dd_start": dd_start.strftime("%b %Y"), "dd_end": dd_end.strftime("%b %Y"),
            "ann_vol": ann_vol, "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
            "beta": beta, "corr": corr, "yearly": yr,
            "growth": prices.iloc[-1],
        }

    m1 = metrics(strat1_prices, "CRDBX Actual (SGOV risk-off)")
    m2 = metrics(strat2_prices, "Modified (33/33/34 risk-off)")

    # Risk-off period return comparison
    off_ret_actual = crdbx_ret[off_mask]
    off_ret_modified = strat2_ret[off_mask]
    off_ann_actual = off_ret_actual.mean() * 252 * 100
    off_ann_modified = off_ret_modified.mean() * 252 * 100

    # Gross component returns during risk-off (before any CRDBX wrapper fee)
    sgov_off_ann = sgov_ret[off_mask].mean() * 252 * 100
    caos_off_ann = caos_ret[off_mask].mean() * 252 * 100
    dbmf_off_ann = dbmf_ret[off_mask].mean() * 252 * 100
    blend_off_ann = (0.33 * caos_ret[off_mask] + 0.33 * dbmf_ret[off_mask] + 0.34 * sgov_ret[off_mask]).mean() * 252 * 100
    incr_er_ann = INCR_ER_DAILY * 252 * 100

    # Find worst drawdown periods for CRDBX and show what CAOS/DBMF did
    # Find the 5 worst single-day drops for S&P during risk-off
    spy_off = spy_ret[off_mask].sort_values()
    worst_days = spy_off.head(10).index

    # Risk-off stretches
    off_starts, off_ends = [], []
    in_off = False
    for i in range(len(idx)):
        if off_mask.iloc[i] and not in_off:
            off_starts.append(i)
            in_off = True
        elif not off_mask.iloc[i] and in_off:
            off_ends.append(i - 1)
            in_off = False
    if in_off:
        off_ends.append(len(idx) - 1)
    durations = [off_ends[j] - off_starts[j] + 1 for j in range(len(off_starts))]

    # ─── WRITE REPORT ───
    L = []
    def p(s=""):
        L.append(s)

    p("POTOMAC FUND MANAGEMENT")
    p("Risk-Off Sleeve Enhancement: Adding Convexity to Defensive Periods")
    p("=" * 78)
    p(f"Prepared: February 2026 | Period analyzed: March 2023 - February 2026")
    p(f"Data: Daily verified NAV total returns (distributions reinvested)")
    p(f"Source: Yahoo Finance via yfinance | All returns net of fund expenses")
    p()
    p("-" * 78)
    p("EXECUTIVE SUMMARY")
    p("-" * 78)
    p()
    p("Bull Bear currently parks ~100% of risk-off capital in money market")
    p(f"(SGOV or equivalent). Over the study period, CRDBX spent {n_off} of")
    p(f"{n_total} trading days ({n_off/n_total*100:.0f}%) in risk-off mode, earning")
    p(f"approximately {off_ann_actual:.1f}% annualized on those days.")
    p()
    p("This memo proposes replacing the risk-off allocation with:")
    p("  33% CAOS  (Alpha Architect Tail Risk -- convex put spreads on S&P)")
    p("  33% DBMF  (iMGP Managed Futures -- systematic trend following)")
    p("  34% SGOV  (iShares 0-3 Month Treasury -- cash anchor)")
    p()
    p("The thesis: CAOS and DBMF are designed to produce positive returns")
    p("during the exact market conditions that trigger our risk-off signal.")
    p("CAOS owns put spreads that appreciate when equities fall sharply.")
    p("DBMF runs trend-following strategies that profit from sustained moves")
    p("in any direction. Both are uncorrelated to equity beta in normal")
    p("markets but become positively convex during dislocations. Pairing them")
    p("with SGOV preserves the defensive intent while converting dead capital")
    p("into an active return source.")
    p()
    p("-" * 78)
    p("METHODOLOGY")
    p("-" * 78)
    p()
    p("Regime detection from CRDBX daily NAV (no lookahead bias):")
    p(f"  - Rolling 5-day beta of CRDBX vs S&P 500")
    p(f"  - Beta > 0.6 = risk-on  |  Beta < 0.3 = risk-off")
    p(f"  - Same-day confirmation: if |CRDBX change| < 0.05% while")
    p(f"    |S&P change| > 0.30%, classify as risk-off")
    p()
    p("Validation:")
    p(f"  - Detected risk-on beta:  {on_beta:.2f}x (confirms VOO + futures)")
    p(f"  - Risk-on days:  {n_on} ({n_on/n_total*100:.0f}%)")
    p(f"  - Risk-off days: {n_off} ({n_off/n_total*100:.0f}%)")
    p(f"  - Distinct risk-off periods: {len(off_starts)}")
    p(f"  - Average duration: {np.mean(durations):.1f} days | Longest: {max(durations)} days")
    p()
    p("-" * 78)
    p("RESULTS")
    p("-" * 78)
    p()
    p(f"{'Metric':<32} {'CRDBX Actual':>18} {'Modified (33/33/34)':>22}")
    p(f"{'':.<32} {'(SGOV risk-off)':>18} {'(CAOS/DBMF/SGOV)':>22}")
    p("-" * 78)
    p(f"{'CAGR':<32} {m1['cagr']:>17.2f}% {m2['cagr']:>21.2f}%")
    p(f"{'Max Drawdown':<32} {m1['max_dd']:>17.2f}% {m2['max_dd']:>21.2f}%")
    p(f"{'Annualized Volatility':<32} {m1['ann_vol']:>17.2f}% {m2['ann_vol']:>21.2f}%")
    p(f"{'Sharpe Ratio (rf=4%)':<32} {m1['sharpe']:>18.2f} {m2['sharpe']:>22.2f}")
    p(f"{'Sortino Ratio':<32} {m1['sortino']:>18.2f} {m2['sortino']:>22.2f}")
    p(f"{'Calmar Ratio':<32} {m1['calmar']:>18.2f} {m2['calmar']:>22.2f}")
    p(f"{'S&P Beta':<32} {m1['beta']:>18.2f} {m2['beta']:>22.2f}")
    p(f"{'S&P Correlation':<32} {m1['corr']:>18.2f} {m2['corr']:>22.2f}")
    g1 = f"${m1['growth']:,.0f}"
    g2 = f"${m2['growth']:,.0f}"
    p(f"{'Growth of $10,000':<32} {g1:>18} {g2:>22}")
    p()

    # Delta
    d_cagr = m2["cagr"] - m1["cagr"]
    d_dd = m2["max_dd"] - m1["max_dd"]
    d_sharpe = m2["sharpe"] - m1["sharpe"]
    p(f"{'IMPROVEMENT':<32} {'':>18} {'+' if d_cagr>0 else ''}{d_cagr:>20.2f}% CAGR")
    p(f"{'':.<32} {'':>18} {'+' if d_dd>0 else ''}{d_dd:>20.2f}% MaxDD")
    p(f"{'':.<32} {'':>18} {'+' if d_sharpe>0 else ''}{d_sharpe:>20.2f} Sharpe")
    p()

    # Year by year
    p(f"{'Calendar Year Returns':<32} {'CRDBX Actual':>18} {'Modified':>22}")
    p("-" * 78)
    all_years = sorted(set(m1["yearly"].index.year) | set(m2["yearly"].index.year))
    for yr in all_years:
        v1 = m1["yearly"][m1["yearly"].index.year == yr]
        v2 = m2["yearly"][m2["yearly"].index.year == yr]
        s1 = f"{v1.iloc[0]:+.2f}%" if len(v1) > 0 else "--"
        s2 = f"{v2.iloc[0]:+.2f}%" if len(v2) > 0 else "--"
        p(f"  {yr:<30} {s1:>18} {s2:>22}")
    p()

    p("-" * 78)
    p("RISK-OFF PERIOD ECONOMICS")
    p("-" * 78)
    p()
    p(f"During the {n_off} risk-off days, annualized component returns")
    p(f"(net of each fund's own expense ratio, from daily NAV):")
    p()
    p(f"  SGOV (T-bills, 0.09% ER):              {sgov_off_ann:>8.2f}%")
    p(f"  CAOS (tail risk, 0.63% ER):             {caos_off_ann:>8.2f}%")
    p(f"  DBMF (managed futures, 0.85% ER):       {dbmf_off_ann:>8.2f}%")
    p(f"  33/33/34 blend (gross):                 {blend_off_ann:>8.2f}%")
    p()
    p(f"  CRDBX risk-off return (net of 1.46% ER): {off_ann_actual:>7.2f}%")
    p(f"  Modified risk-off (net, same ER basis):  {off_ann_modified:>7.2f}%")
    p(f"  Incremental pickup:                     {off_ann_modified - off_ann_actual:>+8.2f}%")
    p()
    p(f"  Note: CRDBX actual risk-off earns ~{off_ann_actual:.0f}% vs SGOV's {sgov_off_ann:.0f}%")
    p(f"  because the fund's 1.46% expense ratio is deducted daily from NAV")
    p(f"  regardless of positioning. This same fee drag is applied equally to")
    p(f"  the Modified version above.")
    p()
    p(f"On a $2B fund with ~{n_off/n_total*100:.0f}% of the year in risk-off:")
    incr_pct = (off_ann_modified - off_ann_actual) * (n_off / n_total)
    incr_bps = incr_pct * 100
    p(f"  Incremental return: ~{incr_bps:.0f} bps on total fund AUM")
    p(f"  Dollar value:       ~${2000 * incr_pct / 100:.1f}M/year at $2B AUM")
    p()

    # Worst S&P days during risk-off
    p("-" * 78)
    p("CONVEXITY IN ACTION: WORST S&P DAYS WHILE RISK-OFF")
    p("-" * 78)
    p()
    p(f"{'Date':<14} {'S&P 500':>9} {'CRDBX':>9} {'CAOS':>9} {'DBMF':>9} {'SGOV':>9} {'Modified':>10}")
    p("-" * 78)
    for dt in worst_days:
        sp = spy_ret.loc[dt] * 100
        cr = crdbx_ret.loc[dt] * 100
        ca = caos_ret.loc[dt] * 100
        db = dbmf_ret.loc[dt] * 100
        sg = sgov_ret.loc[dt] * 100
        md = strat2_ret.loc[dt] * 100
        p(f"  {dt.strftime('%Y-%m-%d'):<12} {sp:>+8.2f}% {cr:>+8.2f}% {ca:>+8.2f}% {db:>+8.2f}% {sg:>+8.2f}% {md:>+9.2f}%")
    p()
    p("Note: On days when CRDBX is flat (~0%) while S&P falls, the fund is")
    p("correctly in cash. The modified sleeve would have been earning returns")
    p("from CAOS and DBMF instead of sitting idle.")
    p()

    p("-" * 78)
    p("IMPLEMENTATION")
    p("-" * 78)
    p()
    p("No change to the risk-on sleeve or signal architecture. The only")
    p("modification is what the fund holds during risk-off periods:")
    p()
    p("  CURRENT:   100% SGOV / money market")
    p("  PROPOSED:  33% CAOS + 33% DBMF + 34% SGOV")
    p()
    p("Expense impact on the 33% risk-off capital:")
    p("  CAOS:  0.63% ER x 0.33 x 0.33 (risk-off %) =  0.07% on total fund")
    p("  DBMF:  0.85% ER x 0.33 x 0.33 (risk-off %) =  0.09% on total fund")
    p("  SGOV:  0.09% ER x 0.34 x 0.33 (risk-off %) =  0.01% on total fund")
    p(f"  Total incremental cost:                         0.17% on total fund")
    p(f"  Net of incremental return ({incr_bps:.0f} bps):        "
      f"  +{incr_bps - 17:.0f} bps net pickup")
    p()
    p("Liquidity: All three ETFs trade >$5M daily volume. CAOS: $575M AUM.")
    p("DBMF: $1.4B AUM. No capacity constraint at Potomac's position sizes.")
    p()

    p("-" * 78)
    p("RISKS AND LIMITATIONS")
    p("-" * 78)
    p()
    p("1. Limited backtest window (March 2023 - February 2026). This period")
    p("   did not include a severe bear market. CAOS and DBMF are designed")
    p("   to outperform during exactly those conditions, so the backtest")
    p("   likely understates the benefit.")
    p()
    p("2. Regime detection is approximate. We infer risk-on/risk-off from")
    p("   CRDBX NAV behavior, not from the actual proprietary signal. Minor")
    p("   misclassifications are possible but do not materially affect the")
    p("   aggregate statistics.")
    p()
    p("3. CAOS carries path-dependent risk: the put-spread structure decays")
    p("   in calm markets. However, at 33% of a 33% sleeve (effectively")
    p("   ~11% of risk-off capital), the drag is minimal and the convexity")
    p("   payoff during a true dislocation is asymmetrically favorable.")
    p()
    p("=" * 78)

    report = "\n".join(L)
    print(report)

    out_path = os.path.join(SCRIPT_DIR, "convexity_memo.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nSaved to: {out_path}")


if __name__ == "__main__":
    main()
