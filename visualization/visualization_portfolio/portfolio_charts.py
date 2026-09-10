"""
Quantitative Master Portfolio — Visualization Dashboard
========================================================
Visualisasi 4-panel terpadu tingkat institusional untuk portofolio kuantitatif multi-sesi XAU/USD:
Panel 1: Master Price Chart dengan eksekusi Asian MR & New York ORB
Panel 2: Atribusi Keuntungan Bulanan (Asian MR vs NY ORB Side-by-Side dengan Nominal Bar)
Panel 3: Underwater Drawdown Portofolio
Panel 4: Compounded Portfolio Equity Curve & Individual Strategy Growth dengan HUD Metrics
"""

import os
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

import portfolio_config as pcfg
from engine.engine_portfolio.portfolio_engine import PortfolioStats, PortfolioTradeRecord


# ─────────────────────────────────────────────
#  STYLE SETUP (DARK THEME QUANTITATIVE)
# ─────────────────────────────────────────────

plt.rcParams.update({
    "figure.facecolor": "#0b0e14",
    "axes.facecolor": "#111827",
    "axes.edgecolor": "#1f2937",
    "axes.labelcolor": "#9ca3af",
    "text.color": "#e0f2fe",
    "xtick.color": "#9ca3af",
    "ytick.color": "#9ca3af",
    "grid.color": "#1f2937",
    "grid.alpha": 0.35,
    "font.family": "sans-serif",
    "font.size": 9,
})

# Palet warna konsisten institusional
COLOR_ASIAN    = "#38bdf8"         # Cyan / Sky Blue untuk Asian MR
COLOR_NY       = "#fbbf24"         # Emas / Amber untuk New York ORB
COLOR_TOTAL    = "#22c55e"         # Hijau Zamrud untuk Total Portofolio
COLOR_LOSS     = "#ef4444"         # Merah untuk kerugian
COLOR_DRAWDOWN = "#ef444433"       # Translucent red drawdown


def _fmt_bar_val(v: float) -> str:
    """Format nilai mata uang ringkas & presisi untuk label di atas bar."""
    sign = "+" if v >= 0 else "-"
    abs_v = abs(v)
    if abs_v >= 10_000:
        return f"{sign}${abs_v/1000.0:.1f}k".replace("$", r"\$")
    else:
        return f"{sign}${abs_v:,.0f}".replace("$", r"\$")


def plot_portfolio_dashboard(
    df_raw: pd.DataFrame,
    trades: List[PortfolioTradeRecord],
    stats: PortfolioStats,
    equity_dates: List[pd.Timestamp],
    equity_curve: List[float],
    asian_equity: List[float],
    ny_equity: Optional[List[float]] = None,
    save_path: Optional[str] = None,
) -> None:
    """Render dashboard visual 4-panel untuk portofolio kuantitatif."""
    fig, axes = plt.subplots(
        4, 1,
        figsize=(18, 15),
        height_ratios=[2.2, 1.3, 1.0, 1.8],
        gridspec_kw={"hspace": 0.30},
    )

    fig.suptitle(
        "Quantitative Master Portfolio Dashboard — XAU/USD (Asian MR + NY ORB)\n"
        "Multi-Session Systematic Strategy | Capital: $10,000 | Dynamic Compounding & De-Risking".replace("$", r"\$"),
        fontsize=15,
        fontweight="bold",
        color="#38bdf8",
        y=0.988,
    )

    # ── Panel 1: Master Price & Multi-Strategy Executions ──
    ax0 = axes[0]
    ax0.set_title("Master Price Action & Multi-Session Executions (Asian MR + New York ORB)",
                  fontsize=11, fontweight="bold", color="#93c5fd", loc="left")

    step = max(1, len(df_raw) // 1600)
    sampled_df = df_raw.iloc[::step]
    ax0.plot(sampled_df["datetime"], sampled_df["close"], color="#60a5fa", linewidth=0.85, alpha=0.45, label="XAU/USD M5 Close")

    asian_plotted = False
    ny_plotted = False

    for t in trades:
        m = "^" if "LONG" in t.direction or "BUY" in t.direction else "v"
        if t.strategy == "ASIAN_MR":
            lbl = "Asian MR Entry" if not asian_plotted else None
            ax0.scatter(t.entry_datetime, t.entry_price, color=COLOR_ASIAN, marker=m, s=36, zorder=5, label=lbl)
            asian_plotted = True
        elif t.strategy == "NY_ORB":
            lbl = "NY ORB Entry" if not ny_plotted else None
            ax0.scatter(t.entry_datetime, t.entry_price, color=COLOR_NY, marker=m, s=36, zorder=5, label=lbl)
            ny_plotted = True

    ax0.set_ylabel("Price (USD)", fontsize=10)
    ax0.legend(loc="upper left", facecolor="#1f2937", edgecolor="#374151", fontsize=8)
    ax0.grid(True, linestyle="--", alpha=0.2)
    ax0.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

    # ── Panel 2: Monthly PnL Attribution (Asian MR vs NY ORB Side-by-Side) ──
    ax1 = axes[1]
    ax1.set_title("Monthly PnL Strategy Attribution (Asian Mean Reversion vs NY ORB Breakout)",
                  fontsize=11, fontweight="bold", color="#93c5fd", loc="left")

    if not stats.monthly_pnl_df.empty:
        m_df = stats.monthly_pnl_df.copy()
        months = list(m_df.index)
        x = np.arange(len(months))
        width = 0.36

        vals_asia = m_df["ASIAN_MR"].values
        vals_ny = m_df["NY_ORB"].values
        vals_tot = m_df["TOTAL"].values

        # Bar Asian MR (kiri) & NY ORB (kanan)
        bar_a = ax1.bar(x - width / 2, vals_asia, width=width, color=COLOR_ASIAN, alpha=0.85,
                        edgecolor="#0b0e14", label=f"Asian MR (+{vals_asia.sum():,.0f} USD)")
        bar_ny = ax1.bar(x + width / 2, vals_ny, width=width, color=COLOR_NY, alpha=0.85,
                         edgecolor="#0b0e14", label=f"NY ORB (+{vals_ny.sum():,.0f} USD)")

        ax1.axhline(0, color="#6b7280", linewidth=0.8, linestyle="--")
        ax1.set_xticks(x)
        ax1.set_xticklabels(months, rotation=45, ha="right", fontsize=8)

        # Hitung headroom & offset
        all_vals = list(vals_asia) + list(vals_ny)
        max_v = max(all_vals) if all_vals else 100
        min_v = min(all_vals) if all_vals else -100
        y_span = max_v - min(0, min_v)
        y_pad = y_span * 0.025

        # Nominal label di atas/bawah masing-masing bar dengan rotasi 90 derajat agar tidak bertumpukan
        for idx in range(len(months)):
            va = vals_asia[idx]
            vny = vals_ny[idx]

            # Label Asian MR (Cyan, vertikal di atas bar)
            pos_y_a = va + y_pad if va >= 0 else va - y_pad * 1.2
            ax1.text(
                x[idx] - width / 2, pos_y_a, _fmt_bar_val(va),
                ha="center", va="bottom" if va >= 0 else "top", fontsize=7.2,
                fontweight="bold", color=COLOR_ASIAN, rotation=90
            )

            # Label NY ORB (Gold, vertikal di atas bar)
            pos_y_ny = vny + y_pad if vny >= 0 else vny - y_pad * 1.2
            ax1.text(
                x[idx] + width / 2, pos_y_ny, _fmt_bar_val(vny),
                ha="center", va="bottom" if vny >= 0 else "top", fontsize=7.2,
                fontweight="bold", color=COLOR_NY, rotation=90
            )

        ax1.set_ylim(-9500, max_v * 1.35)
        ax1.tick_params(axis="x", pad=6)

        # Label banner atribusi
        pos_m = sum(1 for v in vals_tot if v >= 0)
        tot_m = len(vals_tot)
        pct_pos = (pos_m / tot_m * 100.0) if tot_m > 0 else 0.0
        banner_text = (
            f"Profitable Months: {pos_m}/{tot_m} ({pct_pos:.1f}%) | "
            f"Asian MR: +{vals_asia.sum():,.2f} USD | NY ORB: +{vals_ny.sum():,.2f} USD | Total: +{vals_tot.sum():,.2f} USD"
        )
        ax1.text(
            0.02, 0.90, banner_text,
            transform=ax1.transAxes, color="#fbbf24", fontsize=8.5, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#1f2937", edgecolor="#374151")
        )

    ax1.set_ylabel("Monthly PnL (USD)", fontsize=9)
    ax1.legend(loc="upper right", facecolor="#1f2937", edgecolor="#374151", fontsize=8)
    ax1.grid(True, linestyle="--", alpha=0.2)

    # ── Panel 3: Combined Underwater Drawdown ──
    ax2 = axes[2]
    ax2.set_title("Portfolio Underwater Drawdown Profile (%)", fontsize=11, fontweight="bold", color="#93c5fd", loc="left")
    if len(equity_curve) > 1:
        eq_arr = np.array(equity_curve)
        peak_arr = np.maximum.accumulate(eq_arr)
        dd_pct = ((peak_arr - eq_arr) / peak_arr) * 100.0

        ax2.plot(equity_dates, -dd_pct, color=COLOR_LOSS, linewidth=1.0)
        ax2.fill_between(equity_dates, 0, -dd_pct, color=COLOR_DRAWDOWN, label="Drawdown Area")
        ax2.axhline(-stats.max_drawdown_pct, color=COLOR_NY, linestyle=":", linewidth=1.1,
                    label=f"Max Drawdown: {stats.max_drawdown_pct:.2f}% ({stats.max_drawdown_usd:,.2f} USD)")

    ax2.set_ylabel("Drawdown (%)", fontsize=9)
    ax2.set_ylim(-max(6.0, stats.max_drawdown_pct * 1.4), 0.5)
    ax2.legend(loc="lower left", facecolor="#1f2937", edgecolor="#374151", fontsize=8)
    ax2.grid(True, linestyle="--", alpha=0.2)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

    # ── Panel 4: Compounded Portfolio Equity Growth & Individual Strategies ──
    ax3 = axes[3]
    ax3.set_title("Compounded Master Portfolio Equity Growth (Initial Capital: $10,000 USD)".replace("$", r"\$"),
                  fontsize=11, fontweight="bold", color="#93c5fd", loc="left")

    if len(equity_curve) > 1:
        ax3.plot(equity_dates, equity_curve, color=COLOR_TOTAL, linewidth=2.2,
                 label=f"Master Portfolio ({stats.ending_capital:,.2f} USD)", zorder=6)

        if len(asian_equity) == len(equity_dates):
            ax3.plot(equity_dates, asian_equity, color=COLOR_ASIAN, linewidth=1.2, linestyle="--",
                     alpha=0.85, label=f"Asian MR Component (+{stats.asian_pnl_usd:,.2f} USD)")
        if ny_equity and len(ny_equity) == len(equity_dates):
            ax3.plot(equity_dates, ny_equity, color=COLOR_NY, linewidth=1.2, linestyle="--",
                     alpha=0.85, label=f"NY ORB Component (+{stats.ny_pnl_usd:,.2f} USD)")

        # Start account balance strictly from 10,000 (Initial Capital), not 0
        y_max = max(equity_curve) * 1.05
        ax3.set_ylim(bottom=stats.initial_capital, top=y_max)
        y_ticks = [stats.initial_capital] + [t for t in range(100000, int(y_max) + 50000, 100000)]
        ax3.set_yticks(y_ticks)
        ax3.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"${int(x):,}" if x >= 1000 else f"{int(x)}"))

        # Kotak ringkasan metrik kinerja HUD di area kosong atas-tengah
        metrics_box = (
            f"Net PnL: +{stats.total_net_pnl_usd:,.2f} USD (+{stats.roi_pct:.1f}%)  |  "
            f"Win Rate: {stats.win_rate:.1f}% ({stats.winning_trades}W / {stats.losing_trades}L)  |  "
            f"Profit Factor: {stats.profit_factor:.2f}  |  "
            f"Sharpe: {stats.sharpe_ratio:.2f}  |  "
            f"Max DD: {stats.max_drawdown_pct:.2f}% ({stats.max_drawdown_usd:,.2f} USD)"
        )

        ax3.text(
            0.58, 0.88, metrics_box, transform=ax3.transAxes, fontsize=8.5, fontweight="bold",
            ha="center", va="top", color="#e0f2fe",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#1e293b", edgecolor="#8b5cf6", alpha=0.95)
        )

    ax3.set_ylabel("Account Balance (USD)", fontsize=9)
    ax3.set_xlabel("Date (UTC)", fontsize=9)
    ax3.legend(loc="upper left", facecolor="#1f2937", edgecolor="#374151", fontsize=8)
    ax3.grid(True, linestyle="--", alpha=0.2)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

    if save_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        abs_path = os.path.abspath(save_path)
        plt.savefig(abs_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
        print(f"[+] Master Portfolio Dashboard disimpan ke: {abs_path}")
        plt.close(fig)
    else:
        plt.show()


def print_portfolio_trade_log(trade_log: pd.DataFrame) -> None:
    """Cetak ringkasan trade log gabungan ke konsol."""
    if trade_log.empty:
        print("\n[!] Tidak ada trade portofolio yang dihasilkan.\n")
        return

    print("\n" + "=" * 135)
    print("   QUANTITATIVE MASTER PORTFOLIO — CHRONOLOGICAL TRADE LOG (HEAD & TAIL)")
    print("=" * 135)

    display_cols = [
        "strategy", "entry_datetime", "exit_datetime", "direction", "lot_size",
        "entry_price", "exit_price", "pnl_usd", "exit_reason", "duration_min",
    ]
    available = [c for c in display_cols if c in trade_log.columns]

    pd.set_option("display.max_columns", 15)
    pd.set_option("display.width", 135)
    pd.set_option("display.float_format", lambda x: f"{x:.2f}")

    sample_view = pd.concat([trade_log[available].head(10), trade_log[available].tail(10)])
    print(sample_view.to_string(index=False))
    print("=" * 135 + "\n")


def print_monthly_attribution_table(monthly_df: pd.DataFrame) -> None:
    """Cetak tabel atribusi performa bulanan gabungan."""
    if monthly_df.empty:
        return

    print("=" * 68)
    print("   MONTHLY ATTRIBUTION TABLE (ASIAN MR vs NY ORB)")
    print("=" * 68)
    print(f"{'Month':<10} | {'Asian MR PnL':>15} | {'NY ORB PnL':>15} | {'Total PnL':>15}")
    print("-" * 68)

    for idx, row in monthly_df.iterrows():
        a_pnl = row.get("ASIAN_MR", 0.0)
        ny_pnl = row.get("NY_ORB", 0.0)
        tot = row.get("TOTAL", 0.0)
        print(f"{idx:<10} | {a_pnl:>+14.2f}$ | {ny_pnl:>+14.2f}$ | {tot:>+14.2f}$")

    print("-" * 68)
    tot_a = monthly_df["ASIAN_MR"].sum() if "ASIAN_MR" in monthly_df.columns else 0.0
    tot_ny = monthly_df["NY_ORB"].sum() if "NY_ORB" in monthly_df.columns else 0.0
    tot_all = monthly_df["TOTAL"].sum() if "TOTAL" in monthly_df.columns else 0.0
    print(f"{'TOTAL':<10} | {tot_a:>+14.2f}$ | {tot_ny:>+14.2f}$ | {tot_all:>+14.2f}$")
    print("=" * 68 + "\n")
