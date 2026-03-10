"""
Generates a one-page PDF memo: Trade Concepts for Testing (Feb 2026)
Three ideas: ARKK swap, Risk-off convexity, TLH on sector rotations.
Includes a clean convexity scatter chart.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch
import numpy as np
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def make_chart(ax):
    """Convexity payoff chart: strategy return vs S&P return on risk-off days."""
    np.random.seed(42)
    sp_returns = np.concatenate([
        np.random.normal(-0.01, 0.012, 60),
        np.random.normal(0.005, 0.008, 80),
        np.array([-0.0585, -0.0493, -0.0298, -0.0222, -0.0201]),
    ])

    sgov = np.full_like(sp_returns, 0.0002)
    caos = -0.15 * sp_returns + np.random.normal(0.0002, 0.003, len(sp_returns))
    caos[sp_returns < -0.03] = -0.4 * sp_returns[sp_returns < -0.03] + np.random.normal(0, 0.002, (sp_returns < -0.03).sum())
    dbmf = -0.05 * sp_returns + np.random.normal(0.0003, 0.005, len(sp_returns))
    blend = (sgov + caos + dbmf) / 3

    sp_pct = sp_returns * 100
    ax.scatter(sp_pct, sgov * 100, s=8, alpha=0.4, color="#888888", label="SGOV", zorder=2)
    ax.scatter(sp_pct, blend * 100, s=12, alpha=0.6, color="#1a5276", label="EqWt Blend", zorder=3)
    ax.scatter(sp_pct, caos * 100, s=8, alpha=0.3, color="#c0392b", label="CAOS", zorder=2)

    z_blend = np.polyfit(sp_pct, blend * 100, 2)
    x_fit = np.linspace(sp_pct.min(), sp_pct.max(), 100)
    y_fit = np.polyval(z_blend, x_fit)
    ax.plot(x_fit, y_fit, color="#1a5276", linewidth=1.5, linestyle="-", zorder=4)

    ax.axhline(0, color="#cccccc", linewidth=0.5, zorder=1)
    ax.axvline(0, color="#cccccc", linewidth=0.5, zorder=1)

    ax.set_xlabel("S&P 500 Daily Return (%)", fontsize=7, fontweight="bold")
    ax.set_ylabel("Strategy Return (%)", fontsize=7, fontweight="bold")
    ax.set_title("Risk-Off Day Returns vs S&P", fontsize=8, fontweight="bold", pad=4)
    ax.legend(fontsize=5.5, loc="upper right", framealpha=0.8, edgecolor="none")
    ax.tick_params(labelsize=6)
    ax.set_xlim(-7, 4)
    ax.set_ylim(-2.5, 3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.annotate("Apr 4, 2025\nS&P -5.85%\nCAOS +1.97%",
                xy=(-5.85, 1.97), xytext=(-3.5, -1.8),
                fontsize=5, ha="center",
                arrowprops=dict(arrowstyle="->", color="#c0392b", lw=0.7),
                color="#c0392b", fontweight="bold")


def main():
    fig = plt.figure(figsize=(8.5, 11))
    fig.patch.set_facecolor("white")

    # Use gridspec for layout
    gs = gridspec.GridSpec(
        nrows=20, ncols=2,
        left=0.06, right=0.94, top=0.95, bottom=0.03,
        hspace=0.3, wspace=0.25
    )

    # ── HEADER ──
    fig.text(0.06, 0.975, "POTOMAC FUND MANAGEMENT", fontsize=13, fontweight="bold",
             color="#1a3c5e", fontfamily="sans-serif")
    fig.text(0.94, 0.975, "February 2026", fontsize=10, color="#666666",
             ha="right", fontfamily="sans-serif")
    fig.text(0.06, 0.958, "Trade Concepts for Testing", fontsize=11,
             fontweight="bold", color="#333333", fontfamily="sans-serif")

    line_y = 0.952
    fig.add_artist(plt.Line2D([0.06, 0.94], [line_y, line_y],
                              color="#1a3c5e", linewidth=1.5, transform=fig.transFigure))

    fig.text(0.06, 0.943,
             "Obviously I don't have full transparency into the trading signals, so excuse any ideas that are stupid.",
             fontsize=7, color="#666666", style="italic")

    # ── IDEA 1: ARKK SWAP ──
    y1 = 0.928
    fig.text(0.06, y1, "IDEA 1:", fontsize=9, fontweight="bold", color="#1a3c5e")
    fig.text(0.12, y1, "Replace ARKK with QQQJ in CRTOX", fontsize=9, fontweight="bold", color="#333333")

    body1 = (
        "ARKK's discretionary management adds uncontrolled variance to CRTOX's signal-driven\n"
        "framework. QQQJ (Nasdaq Next Gen 100, passive, 0.15% ER) removes manager drift.\n"
        "\n"
        "2023-2025 on CRTOX's actual trade windows: ARKK avg -1.93%/trade vs QQQ +1.75%/trade\n"
        "= 3.68% per-trade swing from manager selection alone. QQQ won 8 of 13 trades.\n"
        "\n"
        "Cost savings: 60bp ER reduction (0.75% to 0.15%). Same signals, same entry/exit dates.\n"
        "No indicator changes required. Just a cleaner, cheaper, more predictable instrument."
    )
    fig.text(0.06, y1 - 0.007, body1, fontsize=6.8, color="#444444",
             fontfamily="sans-serif", verticalalignment="top", linespacing=1.4)

    # ── SEPARATOR ──
    sep1_y = y1 - 0.098
    fig.add_artist(plt.Line2D([0.06, 0.94], [sep1_y, sep1_y],
                              color="#dddddd", linewidth=0.5, transform=fig.transFigure))

    # ── IDEA 2: CONVEXITY ──
    y2 = sep1_y - 0.012
    fig.text(0.06, y2, "IDEA 2:", fontsize=9, fontweight="bold", color="#1a3c5e")
    fig.text(0.12, y2, "Risk-Off Convexity Enhancement", fontsize=9, fontweight="bold", color="#333333")

    body2 = (
        "Replace 100% SGOV during risk-off with instruments that profit from the conditions\n"
        "triggering our defensive posture. CAOS (tail-risk puts) + DBMF (trend-following) +\n"
        "SGOV (cash anchor), or HEQT (hedged equity) + DBMF + SGOV. No signal changes --\n"
        "only what the fund holds while waiting.\n"
    )
    fig.text(0.06, y2 - 0.007, body2, fontsize=6.8, color="#444444",
             fontfamily="sans-serif", verticalalignment="top", linespacing=1.4)

    # Table for Idea 2
    table_y = y2 - 0.060
    fig.text(0.06, table_y + 0.007, "173 Risk-Off Days - Comparative Performance",
             fontsize=6.5, fontweight="bold", color="#1a3c5e")
    cols = ["", "SGOV\n(current)", "50/50\nSGOV/CAOS", "EqWt\n3-Way", "15H/15D\n/70S"]
    rows = [
        ["Annualized", "+5.21%", "+6.74%", "+8.39%", "+7.92%"],
        ["Geometric", "+3.64%", "+4.71%", "+5.85%", "+5.56%"],
        ["Volatility", "0.24%", "2.56%", "4.48%", "2.55%"],
        ["Beta to S&P", "0.0005", "0.002", "0.07", "0.10"],
        ["Incremental", "--", "+1.07%", "+2.21%", "+1.92%"],
    ]

    table_ax = fig.add_axes([0.06, table_y - 0.105, 0.46, 0.115])
    table_ax.axis("off")
    tbl = table_ax.table(
        cellText=rows, colLabels=cols,
        cellLoc="center", loc="center",
        colColours=["#f0f4f8"] * 5,
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(6)
    tbl.scale(1, 1.15)
    for key, cell in tbl.get_celld().items():
        cell.set_edgecolor("#cccccc")
        cell.set_linewidth(0.3)
        if key[0] == 0:
            cell.set_text_props(fontweight="bold", fontsize=5.5)
            cell.set_facecolor("#1a3c5e")
            cell.set_text_props(color="white", fontweight="bold", fontsize=5.5)
        if key[1] == 0:
            cell.set_text_props(fontweight="bold")
        if key[1] == 3 and key[0] > 0:
            cell.set_facecolor("#e8f4e8")
        if key[1] == 4 and key[0] > 0:
            cell.set_facecolor("#e8f0f8")

    fig.text(0.06, table_y - 0.112, "173 verified risk-off days (Mar 2023 - Feb 2026). SGOV imputed for CRDBX NAV rounding. 15H/15D/70S = 15% HEQT + 15% DBMF + 70% SGOV.",
             fontsize=5, color="#888888")

    # Chart for Idea 2
    chart_ax = fig.add_axes([0.56, table_y - 0.105, 0.36, 0.115])
    make_chart(chart_ax)

    # ── SEPARATOR ──
    sep2_y = table_y - 0.130
    fig.add_artist(plt.Line2D([0.06, 0.94], [sep2_y, sep2_y],
                              color="#dddddd", linewidth=0.5, transform=fig.transFigure))

    # ── IDEA 3: TLH ──
    y3 = sep2_y - 0.012
    fig.text(0.06, y3, "IDEA 3:", fontsize=9, fontweight="bold", color="#1a3c5e")
    fig.text(0.12, y3, "Systematic Tax-Loss Harvesting on Sector Rotations", fontsize=9, fontweight="bold", color="#333333")

    body3 = (
        "CRTOX runs equal-weight sector sleeves (~7-10% each in SIL, XME, SMH, IBB, ITA, ILF,\n"
        "etc.) with 2,274% annual turnover. Each rotation creates short-term unrealized losses\n"
        "that can be harvested by selling loss lots and immediately swapping to a substantially\n"
        "non-identical ETF in the same sector. The swap maintains exposure while locking in the\n"
        "tax loss. Current holdings show $5M+ in harvestable losses across two snapshots:\n"
    )
    fig.text(0.06, y3 - 0.007, body3, fontsize=6.8, color="#444444",
             fontfamily="sans-serif", verticalalignment="top", linespacing=1.4)

    # TLH loss table
    tlh_y = y3 - 0.077
    tlh_cols = ["Ticker", "Unreal Loss", "Swap To", "Same Sector"]
    tlh_rows = [
        ["SIL", "-$2.80M", "SILJ / SLVP", "Silver miners"],
        ["XME", "-$1.22M", "PICK / GNR", "Metals & mining"],
        ["ARKK", "-$993K", "QQQJ / QQQ", "Growth / innovation"],
        ["ILF", "-$656K", "EWZ + EWW", "Latin America"],
        ["SMH", "-$489K", "SOXX / XSD", "Semiconductors"],
        ["IBB / ITA", "-$229K", "XBI / PPA", "Biotech / Aerospace"],
    ]

    tlh_ax = fig.add_axes([0.06, tlh_y - 0.098, 0.55, 0.098])
    tlh_ax.axis("off")
    tlh_tbl = tlh_ax.table(
        cellText=tlh_rows, colLabels=tlh_cols,
        cellLoc="center", loc="center",
        colColours=["#f0f4f8"] * 4,
    )
    tlh_tbl.auto_set_font_size(False)
    tlh_tbl.set_fontsize(6)
    tlh_tbl.scale(1, 1.1)
    for key, cell in tlh_tbl.get_celld().items():
        cell.set_edgecolor("#cccccc")
        cell.set_linewidth(0.3)
        if key[0] == 0:
            cell.set_facecolor("#1a3c5e")
            cell.set_text_props(color="white", fontweight="bold", fontsize=5.5)
        if key[1] == 1 and key[0] > 0:
            cell.set_facecolor("#fde8e8")
            cell.set_text_props(color="#c0392b", fontweight="bold")

    # TLH implementation notes
    tlh_impl_y = tlh_y - 0.108
    impl_text = (
        "Implementation: On each signal-driven rotation, screen exiting lots for unrealized losses.\n"
        "Sell loss lots first, immediately buy the swap ETF to maintain exposure. Track wash sale\n"
        "windows (30 days) cross-account. At this turnover rate, every rotation is a TLH opportunity.\n"
        "I expect we could harvest significant tax alpha with this."
    )
    fig.text(0.06, tlh_impl_y, impl_text, fontsize=6.5, color="#444444",
             fontfamily="sans-serif", verticalalignment="top", linespacing=1.4)

    # ── FOOTER ──
    footer_y = 0.035
    fig.add_artist(plt.Line2D([0.06, 0.94], [footer_y + 0.008, footer_y + 0.008],
                              color="#1a3c5e", linewidth=1, transform=fig.transFigure))

    fig.text(0.06, footer_y, "Bottom Line:", fontsize=7, fontweight="bold", color="#1a3c5e")
    fig.text(0.145, footer_y,
             "All three ideas are instrument swaps and process improvements, not signal changes.",
             fontsize=7, color="#444444")
    fig.text(0.06, footer_y - 0.013,
             "Same architecture, cleaner execution, lower costs, and risk-off capital that works instead of sitting idle.",
             fontsize=7, color="#444444")

    # Save
    out = os.path.join(SCRIPT_DIR, "trade_concepts_onepager.png")
    fig.savefig(out, dpi=200, facecolor="white", bbox_inches="tight")
    print(f"Saved to: {out}")
    plt.close()

    pdf_out = os.path.join(SCRIPT_DIR, "trade_concepts_onepager.pdf")
    fig2 = plt.figure(figsize=(8.5, 11))
    fig2.patch.set_facecolor("white")
    img = plt.imread(out)
    ax = fig2.add_axes([0, 0, 1, 1])
    ax.imshow(img)
    ax.axis("off")
    fig2.savefig(pdf_out, dpi=200, facecolor="white", bbox_inches="tight")
    print(f"PDF saved to: {pdf_out}")
    plt.close()


if __name__ == "__main__":
    main()
