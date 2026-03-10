"""
CRDBX Risk-On ETF Surf
======================
Broad factor/style ETF ranking based on CRDBX-derived risk-on days.

Outputs:
1) Text report: crdbx_daily_etf_analysis.txt
2) Regime daily data: crdbx_regime_daily.csv
3) Rank table: crdbx_riskon_etf_rankings.csv
"""

import os
import warnings

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from fee_analyzer import TICKER_CATEGORY_MAP
except Exception:
    TICKER_CATEGORY_MAP = {}

MANUAL_FACTOR_ETFS = {
    "SPMO": "S&P 500 Momentum",
    "MTUM": "MSCI USA Momentum",
    "SPHB": "S&P 500 High Beta",
    "RSP": "S&P 500 Equal Weight",
    "QQQ": "Nasdaq 100",
    "QQQM": "Nasdaq 100 Mini",
    "IWF": "Russell 1000 Growth",
    "VUG": "Vanguard Growth",
    "SCHG": "Schwab Growth",
    "SPYG": "SPDR Growth",
    "IWD": "Russell 1000 Value",
    "SCHV": "Schwab Value",
    "SPYV": "SPDR Value",
    "VTV": "Vanguard Value",
    "USMV": "MSCI USA Min Vol",
    "SPLV": "S&P 500 Low Volatility",
    "LGLV": "US Large Cap Low Vol",
    "QUAL": "MSCI USA Quality",
    "VIG": "Dividend Appreciation",
    "DGRO": "Dividend Growth",
    "SCHD": "US Dividend Equity",
    "HDV": "High Dividend",
    "XLU": "Utilities Sector",
    "SPY": "S&P 500 Baseline",
    "VOO": "S&P 500 Baseline",
}

EXCLUDED_TICKERS = {"CRDBX"}


def get_tr(ticker, start, end):
    t = yf.Ticker(ticker)
    h = t.history(start=start, end=end, auto_adjust=False)
    if h.empty:
        return pd.Series(dtype=float), set()
    h.index = h.index.tz_localize(None)
    nav = h["Close"]
    divs = h.get("Dividends", pd.Series(0.0, index=h.index))
    dist_dates = set(divs[divs > 0].index)
    sh = 1.0
    out = []
    for dt in h.index:
        d = divs.loc[dt] if dt in divs.index else 0.0
        p = nav.loc[dt]
        if d > 0 and p > 0:
            sh *= (1 + d / p)
        out.append(sh * p)
    return pd.Series(out, index=h.index, name=ticker), dist_dates


def build_factor_universe():
    allowed_categories = {
        "US Large Cap Growth",
        "US Large Cap Value",
        "US Dividend",
        "US Dividend Growth",
        "US Utilities",
        "US Large Cap",
    }
    desc = {}
    for ticker, category in TICKER_CATEGORY_MAP.items():
        if category in allowed_categories:
            desc[ticker] = category
    desc.update(MANUAL_FACTOR_ETFS)
    for t in EXCLUDED_TICKERS:
        desc.pop(t, None)
    return dict(sorted(desc.items()))


def classify_regime(cr, sp, idx, dist_dates):
    cr_r = cr.reindex(idx).pct_change()
    sp_r = sp.reindex(idx).pct_change()

    dist_window = set()
    for d in dist_dates:
        for offset in (-1, 0, 1):
            dist_window.add(d + pd.Timedelta(days=offset))

    regime = pd.Series("AMBIGUOUS", index=idx)
    ratio_series = pd.Series(np.nan, index=idx)

    for i, dt in enumerate(idx):
        spy_move = sp_r.iloc[i]
        cr_move = cr_r.iloc[i]
        if pd.isna(spy_move) or pd.isna(cr_move):
            regime.iloc[i] = "AMBIGUOUS"
            continue
        if dt in dist_window:
            regime.iloc[i] = "EXCLUDED"
            continue
        if abs(spy_move) < 0.0015:
            regime.iloc[i] = "AMBIGUOUS"
            continue
        if abs(cr_move) < 0.0003 and abs(spy_move) >= 0.0015:
            regime.iloc[i] = "OFF"
            continue
        ratio = cr_move / spy_move
        ratio_series.iloc[i] = ratio
        if ratio > 0.70 and abs(cr_move) > 0.002:
            regime.iloc[i] = "ON"
    return regime, ratio_series, cr_r, sp_r


def compute_on_metrics(etf_ret, spy_ret, on_mask, min_on_days=60):
    d = pd.DataFrame({"etf": etf_ret, "spy": spy_ret, "on": on_mask}).dropna()
    d = d[d["on"]]
    n = len(d)
    if n < min_on_days:
        return None
    r = d["etf"]
    s = d["spy"]
    var_s = np.var(s)
    beta = np.cov(r, s)[0, 1] / var_s if var_s > 0 else np.nan
    valid = s.abs() > 0.0005
    ratio_med = (r[valid] / s[valid]).median() if valid.sum() > 0 else np.nan
    return {
        "on_days": n,
        "avg_daily_pct": r.mean() * 100,
        "ann_proxy_pct": r.mean() * 252 * 100,
        "beta_spy": beta,
        "ratio_spy_median": ratio_med,
        "win_rate_pct": (r > 0).mean() * 100,
        "worst_day_pct": r.min() * 100,
        "best_day_pct": r.max() * 100,
        "vol_ann_pct": r.std() * np.sqrt(252) * 100,
    }


def add_composite_score(df):
    if df.empty:
        return df
    out = df.copy()
    out["r_avg"] = out["avg_daily_pct"].rank(pct=True)
    out["r_ratio"] = out["ratio_spy_median"].rank(pct=True)
    out["r_win"] = out["win_rate_pct"].rank(pct=True)
    out["r_worst"] = out["worst_day_pct"].rank(pct=True)  # less negative is better
    out["beta_control"] = 1.0 - ((out["beta_spy"] - 1.0).abs().clip(upper=1.5) / 1.5)
    out["composite_score"] = 100 * (
        0.35 * out["r_avg"] +
        0.20 * out["r_ratio"] +
        0.20 * out["r_win"] +
        0.15 * out["r_worst"] +
        0.10 * out["beta_control"]
    )
    out = out.sort_values("composite_score", ascending=False).reset_index(drop=True)
    out["rank"] = np.arange(1, len(out) + 1)
    return out


def evaluate_window(data, regime_idx, regime_series, etf_map, window_name, min_on_days=60):
    sp_ret = data["SPY"].reindex(regime_idx).pct_change()
    on_mask = regime_series == "ON"
    rows = []
    for t, desc in etf_map.items():
        if t not in data:
            continue
        etf_ret = data[t].reindex(regime_idx).pct_change()
        m = compute_on_metrics(etf_ret, sp_ret, on_mask, min_on_days=min_on_days)
        if m is None:
            continue
        m["etf"] = t
        m["description"] = desc
        m["window"] = window_name
        rows.append(m)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return add_composite_score(df)


def print_rank_table(p, title, df, width=140, top_n=15):
    p("\n" + "=" * width)
    p(title)
    p("=" * width)
    if df.empty:
        p("No ETFs passed minimum sample filter.")
        return
    p(f"{'Rank':>4s} {'ETF':6s} {'Description':.<28s} {'Score':>7s} {'Avg':>9s} {'Ann':>9s} {'Beta':>8s} {'Ratio':>8s} {'Win':>8s} {'Worst':>9s} {'Best':>8s} {'N_ON':>6s}")
    p("-" * width)
    for _, r in df.head(top_n).iterrows():
        p(
            f"{int(r['rank']):>4d} {r['etf']:6s} {str(r['description'])[:28]:.<28s} "
            f"{r['composite_score']:>6.1f} "
            f"{r['avg_daily_pct']:>+8.4f}% {r['ann_proxy_pct']:>+8.2f}% "
            f"{r['beta_spy']:>8.3f} {r['ratio_spy_median']:>8.3f} "
            f"{r['win_rate_pct']:>7.1f}% {r['worst_day_pct']:>+8.2f}% "
            f"{r['best_day_pct']:>+7.2f}% {int(r['on_days']):>6d}"
        )


def main():
    recent_start = "2023-03-01"
    end_date = "2026-03-07"
    warmup = "2005-01-01"
    min_on_days = 60
    width = 140

    etf_map = build_factor_universe()
    all_tickers = sorted(set(etf_map.keys()) | {"SPY", "CRDBX"})

    lines = []

    def p(s=""):
        lines.append(s)
        print(s)

    p("=" * width)
    p("CRDBX RISK-ON ETF SURF -- FACTOR/STYLE UNIVERSE")
    p("=" * width)
    p(f"Universe size: {len(etf_map)} factor/style ETFs (no leveraged/inverse)")
    p(f"Fetching total-return series for {len(all_tickers)} tickers...")

    data = {}
    crdbx_dist_dates = set()
    for t in all_tickers:
        try:
            s, dd = get_tr(t, warmup, end_date)
            if not s.empty:
                data[t] = s
                if t == "CRDBX":
                    crdbx_dist_dates = dd
                p(f"  {t:6s} {len(s)} days")
            else:
                p(f"  {t:6s} NO DATA")
        except Exception as e:
            p(f"  {t:6s} ERROR: {e}")

    if "CRDBX" not in data or "SPY" not in data:
        p("ERROR: Need both CRDBX and SPY data.")
        return

    # Base regime series windows
    idx_full = data["CRDBX"].index.intersection(data["SPY"].index)
    idx_recent = idx_full[idx_full >= pd.Timestamp(recent_start)]
    if len(idx_recent) == 0:
        p("ERROR: No recent overlap after start date filter.")
        return

    regime_full, ratio_full, cr_r_full, sp_r_full = classify_regime(
        data["CRDBX"], data["SPY"], idx_full, crdbx_dist_dates
    )
    regime_recent, ratio_recent, cr_r_recent, sp_r_recent = classify_regime(
        data["CRDBX"], data["SPY"], idx_recent, crdbx_dist_dates
    )

    for lbl, idx, regime in (
        ("Recent window", idx_recent, regime_recent),
        ("Full-history window", idx_full, regime_full),
    ):
        on_n = int((regime == "ON").sum())
        off_n = int((regime == "OFF").sum())
        amb_n = int((regime == "AMBIGUOUS").sum())
        exc_n = int((regime == "EXCLUDED").sum())
        p(f"\n{lbl}: {len(idx)} days ({idx[0].date()} to {idx[-1].date()})")
        p(f"  ON={on_n} OFF={off_n} AMBIG={amb_n} EXCL={exc_n}")

    recent_rank = evaluate_window(
        data, idx_recent, regime_recent, etf_map, "recent", min_on_days=min_on_days
    )
    full_rank = evaluate_window(
        data, idx_full, regime_full, etf_map, "full_history", min_on_days=min_on_days
    )

    print_rank_table(
        p,
        "PRIMARY RANKING: RECENT WINDOW (2023-03 TO PRESENT)",
        recent_rank,
        width=width,
        top_n=20,
    )
    print_rank_table(
        p,
        "ROBUSTNESS CHECK: FULL-HISTORY WINDOW",
        full_rank,
        width=width,
        top_n=20,
    )

    # Merge ranks for stability flags
    join_cols = ["etf", "description", "rank", "composite_score", "on_days", "avg_daily_pct", "ann_proxy_pct", "beta_spy", "ratio_spy_median", "win_rate_pct", "worst_day_pct", "best_day_pct"]
    recent_trim = recent_rank[join_cols].rename(
        columns={
            "rank": "rank_recent",
            "composite_score": "score_recent",
            "on_days": "on_days_recent",
            "avg_daily_pct": "avg_recent_pct",
            "ann_proxy_pct": "ann_recent_pct",
            "beta_spy": "beta_recent",
            "ratio_spy_median": "ratio_recent",
            "win_rate_pct": "win_recent_pct",
            "worst_day_pct": "worst_recent_pct",
            "best_day_pct": "best_recent_pct",
        }
    )
    full_trim = full_rank[join_cols].rename(
        columns={
            "rank": "rank_full",
            "composite_score": "score_full",
            "on_days": "on_days_full",
            "avg_daily_pct": "avg_full_pct",
            "ann_proxy_pct": "ann_full_pct",
            "beta_spy": "beta_full",
            "ratio_spy_median": "ratio_full",
            "win_rate_pct": "win_full_pct",
            "worst_day_pct": "worst_full_pct",
            "best_day_pct": "best_full_pct",
        }
    )
    combined = recent_trim.merge(full_trim, on=["etf", "description"], how="left")
    combined["rank_gap"] = (combined["rank_recent"] - combined["rank_full"]).abs()
    combined["robustness_flag"] = np.where(
        combined["rank_full"].isna(),
        "insufficient_full_data",
        np.where(combined["rank_gap"] <= 5, "stable", np.where(combined["rank_gap"] <= 12, "moderate", "unstable")),
    )
    combined = combined.sort_values(["rank_recent", "score_recent"], ascending=[True, False]).reset_index(drop=True)

    # Action list: top 5 + alternates with similar profile
    p("\n" + "=" * width)
    p("ACTION LIST")
    p("=" * width)
    top5 = combined.head(5)
    for i, (_, r) in enumerate(top5.iterrows(), 1):
        p(
            f"{i}. {r['etf']} ({r['description']}) "
            f"-- recent rank {int(r['rank_recent'])}, score {r['score_recent']:.1f}, "
            f"robustness: {r['robustness_flag']}"
        )

    alternates = combined[(combined["rank_recent"] <= 12) & (combined["robustness_flag"] != "unstable")].head(8)
    alt_symbols = [t for t in alternates["etf"].tolist() if t not in top5["etf"].tolist()][:3]
    if alt_symbols:
        p("Alternates: " + ", ".join(alt_symbols))
    else:
        p("Alternates: none passed stability filter beyond top 5.")

    p("\nSample caveats:")
    p(f"- Minimum ON-day requirement per ETF: {min_on_days} days.")
    p("- Rankings are no-lag upper bounds; live execution will underperform due to timing/friction.")
    p("- Newer funds can rank high but be less robust due to shorter full-history overlap.")

    # Validation checks requested in plan
    leaders = {"SPMO", "QQQ", "MTUM", "IWF"}
    seen_leaders = [t for t in combined.head(15)["etf"].tolist() if t in leaders]
    p("\nValidation checks:")
    p(f"- ETFs passing sample filter: {len(combined)}")
    p(f"- Prior known leaders seen in top 15: {', '.join(seen_leaders) if seen_leaders else 'none'}")

    # Write outputs
    txt_out = os.path.join(SCRIPT_DIR, "crdbx_daily_etf_analysis.txt")
    with open(txt_out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nSaved report: {txt_out}")

    regime_out = os.path.join(SCRIPT_DIR, "crdbx_regime_daily.csv")
    regime_df = pd.DataFrame(
        {
            "date": idx_recent,
            "regime": regime_recent.values,
            "crdbx_ret": cr_r_recent.values,
            "spy_ret": sp_r_recent.values,
            "crdbx_spy_ratio": ratio_recent.values,
        }
    )
    regime_df.to_csv(regime_out, index=False)
    print(f"Saved regime daily data: {regime_out}")

    rank_out = os.path.join(SCRIPT_DIR, "crdbx_riskon_etf_rankings.csv")
    combined.to_csv(rank_out, index=False)
    print(f"Saved ETF ranking table: {rank_out}")


if __name__ == "__main__":
    main()
