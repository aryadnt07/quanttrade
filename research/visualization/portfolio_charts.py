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

from src.strategies.portfolio import config as pcfg
from src.strategies.portfolio.engine import PortfolioStats, PortfolioTradeRecord


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
COLOR_LONDON   = "#a855f7"         # Ungu / Electric Purple untuk London Pit ORB
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
    london_equity: Optional[List[float]] = None,
    ny_equity: Optional[List[float]] = None,
    save_path: Optional[str] = None,
) -> None:
    """Render dashboard visual 4-panel untuk portofolio kuantitatif."""
    fig, axes = plt.subplots(
        4, 1,
        figsize=(25, 17),
        height_ratios=[2.0, 1.6, 1.0, 1.8],
        gridspec_kw={"hspace": 0.32},
    )

    active_modules = []
    if getattr(pcfg, "ENABLE_ASIAN_MR", True): active_modules.append("Asian MR")
    if getattr(pcfg, "ENABLE_LONDON_ORB", False): active_modules.append("London ORB")
    if getattr(pcfg, "ENABLE_STRATEGY_2", False): active_modules.append("NY ORB")
    strat_title = " + ".join(active_modules)

    fig.suptitle(
        f"Quantitative Master Portfolio Dashboard — XAU/USD ({strat_title})\n"
        "Multi-Regime Systematic Strategy | Capital: $10,000 | Dynamic Compounding & De-Risking".replace("$", r"\$"),
        fontsize=15,
        fontweight="bold",
        color="#38bdf8",
        y=0.988,
    )

    # ── Panel 1: Master Price & Multi-Strategy Executions ──
    ax0 = axes[0]
    ax0.set_title(f"Master Price Action & Multi-Session Executions ({strat_title})",
                  fontsize=11, fontweight="bold", color="#93c5fd", loc="left")

    step = max(1, len(df_raw) // 1600)
    sampled_df = df_raw.iloc[::step]
    ax0.plot(sampled_df["datetime"], sampled_df["close"], color="#60a5fa", linewidth=0.85, alpha=0.45, label="XAU/USD M5 Close")

    asian_plotted = False
    london_plotted = False
    ny_plotted = False

    for t in trades:
        m = "^" if "LONG" in t.direction or "BUY" in t.direction else "v"
        if t.strategy == "ASIAN_MR":
            lbl = "Asian MR Entry" if not asian_plotted else None
            ax0.scatter(t.entry_datetime, t.entry_price, color=COLOR_ASIAN, marker=m, s=36, zorder=5, label=lbl)
            asian_plotted = True
        elif t.strategy == "LONDON_ORB":
            lbl = "London ORB Entry" if not london_plotted else None
            ax0.scatter(t.entry_datetime, t.entry_price, color=COLOR_LONDON, marker=m, s=36, zorder=5, label=lbl)
            london_plotted = True
        elif t.strategy == "NY_ORB":
            lbl = "NY ORB Entry" if not ny_plotted else None
            ax0.scatter(t.entry_datetime, t.entry_price, color=COLOR_NY, marker=m, s=36, zorder=5, label=lbl)
            ny_plotted = True

    ax0.set_ylabel("Price (USD)", fontsize=10)
    ax0.legend(loc="upper left", facecolor="#1f2937", edgecolor="#374151", fontsize=8)
    is_short_span = len(df_raw) > 0 and (df_raw["datetime"].max() - df_raw["datetime"].min()).days <= 90
    date_fmt = "%d %b %Y" if is_short_span else "%b %Y"
    ax0.xaxis.set_major_formatter(mdates.DateFormatter(date_fmt))

    # ── Panel 2: Monthly PnL Attribution (Side-by-Side) ──
    ax1 = axes[1]
    ax1.set_title(f"Monthly PnL Strategy Attribution ({strat_title})",
                  fontsize=11, fontweight="bold", color="#93c5fd", loc="left")

    if not stats.monthly_pnl_df.empty:
        m_df = stats.monthly_pnl_df.copy()
        months = list(m_df.index)
        x = np.arange(len(months))

        has_london = "LONDON_ORB" in m_df.columns and getattr(pcfg, "ENABLE_LONDON_ORB", False)
        width = 0.30 if has_london else 0.38

        vals_asia = m_df["ASIAN_MR"].values if "ASIAN_MR" in m_df.columns else np.zeros(len(months))
        vals_lon = m_df["LONDON_ORB"].values if has_london else np.zeros(len(months))
        vals_ny = m_df["NY_ORB"].values if "NY_ORB" in m_df.columns else np.zeros(len(months))
        vals_tot = m_df["TOTAL"].values if "TOTAL" in m_df.columns else vals_asia + vals_lon + vals_ny

        if has_london:
            ax1.bar(x - width, vals_asia, width=width, color=COLOR_ASIAN, alpha=0.90,
                    edgecolor="#0b0e14", linewidth=0.6, label=f"Asian MR (+{vals_asia.sum():,.0f} USD)")
            ax1.bar(x, vals_lon, width=width, color=COLOR_LONDON, alpha=0.90,
                    edgecolor="#0b0e14", linewidth=0.6, label=f"London ORB (+{vals_lon.sum():,.0f} USD)")
            ax1.bar(x + width, vals_ny, width=width, color=COLOR_NY, alpha=0.90,
                    edgecolor="#0b0e14", linewidth=0.6, label=f"NY ORB (+{vals_ny.sum():,.0f} USD)")
            all_vals = list(vals_asia) + list(vals_lon) + list(vals_ny)
        else:
            ax1.bar(x - width / 2, vals_asia, width=width, color=COLOR_ASIAN, alpha=0.90,
                    edgecolor="#0b0e14", linewidth=0.6, label=f"Asian MR (+{vals_asia.sum():,.0f} USD)")
            ax1.bar(x + width / 2, vals_ny, width=width, color=COLOR_NY, alpha=0.90,
                    edgecolor="#0b0e14", linewidth=0.6, label=f"NY ORB (+{vals_ny.sum():,.0f} USD)")
            all_vals = list(vals_asia) + list(vals_ny)
        max_v = max(all_vals) if all_vals else 100
        min_v = min(all_vals) if all_vals else -100
        y_span = max_v - min(0, min_v)
        y_pad = y_span * 0.028

        # Nominal label di atas/bawah masing-masing bar dengan rotasi 90 derajat agar persis seperti dashboard klasik
        for idx in range(len(months)):
            va = vals_asia[idx]
            vny = vals_ny[idx]

            # Label Asian MR (Cyan, vertikal)
            if abs(va) > 0:
                pos_y_a = va + y_pad if va >= 0 else va - y_pad * 1.25
                ax1.text(
                    x[idx] - width if has_london else x[idx] - width / 2, pos_y_a, _fmt_bar_val(va),
                    ha="center", va="bottom" if va >= 0 else "top", fontsize=7.2 if has_london else 7.8,
                    fontweight="bold", color=COLOR_ASIAN, rotation=90
                )

            # Label London ORB (Ungu / Electric Purple, vertikal)
            if has_london:
                vlon = vals_lon[idx]
                if abs(vlon) > 0:
                    pos_y_lon = vlon + y_pad if vlon >= 0 else vlon - y_pad * 1.25
                    ax1.text(
                        x[idx], pos_y_lon, _fmt_bar_val(vlon),
                        ha="center", va="bottom" if vlon >= 0 else "top", fontsize=7.2,
                        fontweight="bold", color=COLOR_LONDON, rotation=90
                    )

            # Label NY ORB (Gold / Amber, vertikal)
            if abs(vny) > 0:
                pos_y_ny = vny + y_pad if vny >= 0 else vny - y_pad * 1.25
                ax1.text(
                    x[idx] + width if has_london else x[idx] + width / 2, pos_y_ny, _fmt_bar_val(vny),
                    ha="center", va="bottom" if vny >= 0 else "top", fontsize=7.2 if has_london else 7.8,
                    fontweight="bold", color=COLOR_NY, rotation=90
                )

        banner_text = (
            f"Profitable Months: {sum(1 for v in vals_tot if v >= 0)}/{len(vals_tot)} "
            f"({sum(1 for v in vals_tot if v >= 0)/len(vals_tot)*100.0:.1f}%) | "
            f"Asian MR: +${vals_asia.sum():,.0f} USD | "
            + (f"London ORB: +${vals_lon.sum():,.0f} USD | " if has_london else "")
            + f"NY ORB: +${vals_ny.sum():,.0f} USD | Total: +${vals_tot.sum():,.0f} USD"
        ).replace("$", r"\$")

        ax1.axhline(0, color="#6b7280", linewidth=0.8, linestyle="--")
        ax1.set_xticks(x)
        ax1.set_xticklabels(months, rotation=45, ha="right", fontsize=8)
        y_min_bound = min(-100.0, min_v * 1.35) if min_v < 0 else -50.0
        y_max_bound = max(100.0, max_v * 1.42)
        ax1.set_ylim(y_min_bound, y_max_bound)
        ax1.tick_params(axis="x", pad=6)

        ax1.text(
            0.02, 0.90, banner_text,
            transform=ax1.transAxes, color="#fbbf24", fontsize=8.2, fontweight="bold",
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
    ax2.xaxis.set_major_formatter(mdates.DateFormatter(date_fmt))

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
        if london_equity and len(london_equity) == len(equity_dates):
            ax3.plot(equity_dates, london_equity, color=COLOR_LONDON, linewidth=1.2, linestyle="--",
                     alpha=0.85, label=f"London ORB Component (+{stats.london_pnl_usd:,.2f} USD)")
        if ny_equity and len(ny_equity) == len(equity_dates):
            ax3.plot(equity_dates, ny_equity, color=COLOR_NY, linewidth=1.2, linestyle="--",
                     alpha=0.85, label=f"NY ORB Component (+{stats.ny_pnl_usd:,.2f} USD)")

        # Start account balance with small buffer around initial capital and equity range
        y_min = min(equity_curve)
        y_max = max(equity_curve)
        y_bottom = min(stats.initial_capital, y_min) * 0.995
        y_top = max(stats.initial_capital, y_max) * 1.008
        ax3.set_ylim(bottom=y_bottom, top=y_top)

        y_range = y_top - y_bottom
        if y_range > 2_000_000:
            step = 1_000_000
        elif y_range > 500_000:
            step = 250_000
        elif y_range > 150_000:
            step = 100_000
        elif y_range > 20_000:
            step = 10_000
        elif y_range > 5_000:
            step = 1_000
        elif y_range > 1_000:
            step = 250
        elif y_range > 200:
            step = 100
        else:
            step = 50

        first_tick = int(np.ceil(y_bottom / step) * step)
        y_ticks = [t for t in range(first_tick, int(y_top) + step, step)]
        if stats.initial_capital not in y_ticks and y_bottom <= stats.initial_capital <= y_top:
            y_ticks = sorted(y_ticks + [stats.initial_capital])
        ax3.set_yticks(y_ticks)
        ax3.yaxis.set_major_formatter(plt.FuncFormatter(
            lambda x, p: f"${x/1_000_000:.1f}M" if x >= 1_000_000 else (f"${int(x/1000):,}k" if x >= 10000 else f"${int(x):,}")
        ))

        # Kotak ringkasan metrik kinerja HUD di area kosong atas-tengah
        metrics_box = (
            f"Net PnL: +${stats.total_net_pnl_usd:,.2f} USD (+{stats.roi_pct:.1f}%) | PF: {stats.profit_factor:.2f} | Sharpe: {stats.sharpe_ratio:.2f} | Sortino: {stats.sortino_ratio:.2f} | Calmar: {stats.calmar_ratio:.2f}\n"
            f"Win Rate: {stats.win_rate:.1f}% ({stats.winning_trades}W / {stats.losing_trades}L) | Expectancy: ${stats.expectancy_usd:+,.2f} | "
            f"Max DD: {stats.max_drawdown_pct:.2f}% (${stats.max_drawdown_usd:,.2f}) | VaR(95%): {stats.var_95_pct:.2f}%"
        ).replace("$", r"\$")

        ax3.text(
            0.55, 0.88, metrics_box, transform=ax3.transAxes, fontsize=8.2, fontweight="bold",
            ha="center", va="top", color="#e0f2fe",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#1e293b", edgecolor="#8b5cf6", alpha=0.95)
        )

    ax3.set_ylabel("Account Balance (USD)", fontsize=9)
    ax3.set_xlabel("Date (UTC)", fontsize=9)
    ax3.legend(loc="upper left", facecolor="#1f2937", edgecolor="#374151", fontsize=8)
    ax3.grid(True, linestyle="--", alpha=0.2)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter(date_fmt))

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

    has_london = "LONDON_ORB" in monthly_df.columns
    if has_london:
        sep_len = 86
        header = f"{'Month':<10} | {'Asian MR PnL':>15} | {'London ORB PnL':>15} | {'NY ORB PnL':>15} | {'Total PnL':>15}"
    else:
        sep_len = 68
        header = f"{'Month':<10} | {'Asian MR PnL':>15} | {'NY ORB PnL':>15} | {'Total PnL':>15}"

    print("=" * sep_len)
    print(f"   MONTHLY ATTRIBUTION TABLE ({'ASIAN MR + LONDON ORB + NY ORB' if has_london else 'ASIAN MR vs NY ORB'})")
    print("=" * sep_len)
    print(header)
    print("-" * sep_len)

    for idx, row in monthly_df.iterrows():
        a_pnl = row.get("ASIAN_MR", 0.0)
        lon_pnl = row.get("LONDON_ORB", 0.0)
        ny_pnl = row.get("NY_ORB", 0.0)
        tot = row.get("TOTAL", 0.0)
        if has_london:
            print(f"{idx:<10} | {a_pnl:>+14.2f}$ | {lon_pnl:>+14.2f}$ | {ny_pnl:>+14.2f}$ | {tot:>+14.2f}$")
        else:
            print(f"{idx:<10} | {a_pnl:>+14.2f}$ | {ny_pnl:>+14.2f}$ | {tot:>+14.2f}$")

    print("-" * sep_len)
    tot_a = monthly_df["ASIAN_MR"].sum() if "ASIAN_MR" in monthly_df.columns else 0.0
    tot_lon = monthly_df["LONDON_ORB"].sum() if "LONDON_ORB" in monthly_df.columns else 0.0
    tot_ny = monthly_df["NY_ORB"].sum() if "NY_ORB" in monthly_df.columns else 0.0
    tot_all = monthly_df["TOTAL"].sum() if "TOTAL" in monthly_df.columns else 0.0

    if has_london:
        print(f"{'TOTAL':<10} | {tot_a:>+14.2f}$ | {tot_lon:>+14.2f}$ | {tot_ny:>+14.2f}$ | {tot_all:>+14.2f}$")
    else:
        print(f"{'TOTAL':<10} | {tot_a:>+14.2f}$ | {tot_ny:>+14.2f}$ | {tot_all:>+14.2f}$")
    print("=" * sep_len + "\n")
