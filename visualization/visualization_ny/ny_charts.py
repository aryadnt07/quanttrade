"""
New York Opening Range Breakout (NY ORB) — Performance Dashboard
=================================================================
Dashboard 4-panel tingkat institusional untuk strategi New York ORB:
Panel 1: Price Action XAU/USD M5 & Sinyal Eksekusi Breakout (13:30 - 17:00 UTC)
Panel 2: Bar Chart Performa PnL Bulanan dengan Nominal Nilai (Monthly Net PnL USD)
Panel 3: Profil Underwater Drawdown Portofolio Terdedikasi (%)
Panel 4: Equity Curve Growth (Starting Capital: $10,000 USD) dengan Metrik Kinerja HUD
"""

import os
from typing import List, Optional
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

import ny_config as cfg
from engine.engine_ny.ny_engine import NYStats
from engine.engine_ny.ny_trade_manager import NYTrade


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

COLOR_ACCENT   = "#fbbf24"       # Emas / Amber NY ORB
COLOR_BUY      = "#22c55e"       # Hijau cerah Buy/TP
COLOR_SELL     = "#ef4444"       # Merah Sell/SL
COLOR_TIME     = "#a855f7"       # Ungu Time Cutoff
COLOR_DRAWDOWN = "#ef444433"     # Translucent red drawdown


def plot_ny_dashboard(
    df_raw: pd.DataFrame,
    trades: List[NYTrade],
    stats: NYStats,
    equity_dates: List[pd.Timestamp],
    equity_curve: List[float],
    save_path: Optional[str] = None
) -> None:
    """Render dashboard visual institusional 4-panel untuk NY ORB."""
    fig, axes = plt.subplots(
        4, 1,
        figsize=(18, 15),
        height_ratios=[2.2, 1.3, 1.0, 1.8],
        gridspec_kw={"hspace": 0.30},
    )

    fig.suptitle(
        "New York Opening Range Breakout (NY ORB) — Performance Dashboard\n"
        "Session: 13:45 - 16:30 UTC | Target: 2.0R | Stop: Midpoint Range | Cutoff: 17:00 UTC",
        fontsize=15,
        fontweight="bold",
        color=COLOR_ACCENT,
        y=0.988,
    )

    # ── Panel 1: Price Action & Trade Entries ──
    ax0 = axes[0]
    ax0.set_title("XAU/USD M5 Price Action & NY ORB Executions (13:30 - 17:00 UTC)",
                  fontsize=11, fontweight="bold", color="#93c5fd", loc="left")

    step = max(1, len(df_raw) // 1600)
    sampled_df = df_raw.iloc[::step]
    ax0.plot(sampled_df["datetime"], sampled_df["close"], color="#60a5fa", linewidth=0.85, alpha=0.45, label="XAU/USD M5 Close")

    buy_trades = [t for t in trades if t.signal.direction.value == "BUY"]
    sell_trades = [t for t in trades if t.signal.direction.value == "SELL"]

    if buy_trades:
        b_dates = [t.signal.datetime for t in buy_trades]
        b_prices = [t.signal.entry_price for t in buy_trades]
        ax0.scatter(b_dates, b_prices, marker="^", color=COLOR_BUY, s=36, zorder=5, label=f"BUY Breakout ({len(buy_trades)})")

    if sell_trades:
        s_dates = [t.signal.datetime for t in sell_trades]
        s_prices = [t.signal.entry_price for t in sell_trades]
        ax0.scatter(s_dates, s_prices, marker="v", color=COLOR_SELL, s=36, zorder=5, label=f"SELL Breakout ({len(sell_trades)})")

    ax0.set_ylabel("Price (USD)", fontsize=10)
    ax0.grid(True, linestyle="--", alpha=0.2)
    ax0.legend(loc="upper left", facecolor="#1f2937", edgecolor="#374151", fontsize=8)
    ax0.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

    # ── Panel 2: Monthly Net PnL (with Exact Nominal Labels) ──
    ax1 = axes[1]
    ax1.set_title("Monthly Net PnL (USD) — NY Opening Range Breakout",
                  fontsize=11, fontweight="bold", color="#93c5fd", loc="left")
    if not stats.monthly_pnl_df.empty:
        m_df = stats.monthly_pnl_df
        months = m_df["month"].tolist()
        m_pnls = m_df["pnl_usd"].tolist()
        bar_colors = [COLOR_BUY if v >= 0 else COLOR_SELL for v in m_pnls]

        x_indices = np.arange(len(months))
        ax1.bar(x_indices, m_pnls, color=bar_colors, edgecolor="#0b0e14", width=0.65, alpha=0.85)
        ax1.axhline(0, color="#6b7280", linestyle="--", linewidth=0.8)
        ax1.set_xticks(x_indices)
        ax1.set_xticklabels(months, rotation=45, ha="right", fontsize=8)
        ax1.set_ylabel("Net PnL (USD)", fontsize=9)
        ax1.grid(True, linestyle="--", alpha=0.2)

        # Tambahkan nominal di atas/bawah bar
        max_abs = max(abs(p) for p in m_pnls) if m_pnls else 100
        y_offset = max_abs * 0.04
        for idx, val in enumerate(m_pnls):
            y_pos = val + y_offset if val >= 0 else val - y_offset * 1.6
            lbl = f"+${val:,.0f}" if val >= 0 else f"-${abs(val):,.0f}"
            ax1.text(
                idx, y_pos, lbl.replace("$", r"\$"),
                ha="center", va="bottom" if val >= 0 else "top", fontsize=7.5,
                fontweight="bold", color=COLOR_BUY if val >= 0 else COLOR_SELL
            )
        ax1.set_ylim(min(0, min(m_pnls) * 1.35), max(m_pnls) * 1.35)

        # Label ringkasan banner
        pos_months = sum(1 for v in m_pnls if v >= 0)
        tot_months = len(m_pnls)
        tot_net = sum(m_pnls)
        pct_pos = (pos_months / tot_months * 100.0) if tot_months > 0 else 0.0
        banner_text = (
            f"Profitable Months: {pos_months}/{tot_months} ({pct_pos:.1f}%) | "
            f"Total Net: +{tot_net:,.2f} USD"
        )
        ax1.text(
            0.02, 0.90, banner_text,
            transform=ax1.transAxes, color=COLOR_ACCENT, fontsize=8.5, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#1f2937", edgecolor="#374151")
        )

    # ── Panel 3: Dedicated Underwater Drawdown Profile (%) ──
    ax2 = axes[2]
    ax2.set_title("Portfolio Underwater Drawdown Profile (%)",
                  fontsize=11, fontweight="bold", color="#93c5fd", loc="left")
    if len(equity_dates) == len(equity_curve) and len(equity_curve) > 1:
        eq_arr = np.array(equity_curve)
        peak = np.maximum.accumulate(eq_arr)
        dd_pct = ((peak - eq_arr) / peak) * 100.0

        ax2.plot(equity_dates, -dd_pct, color=COLOR_SELL, linewidth=1.0)
        ax2.fill_between(equity_dates, 0, -dd_pct, color=COLOR_DRAWDOWN, label="Drawdown Area")
        ax2.axhline(-stats.max_drawdown_pct, color=COLOR_ACCENT, linestyle=":", linewidth=1.1,
                    label=f"Max Drawdown: {stats.max_drawdown_pct:.2f}% ({stats.max_drawdown_usd:,.2f} USD)")

    ax2.set_ylabel("Drawdown (%)", fontsize=9)
    ax2.set_ylim(-max(6.0, stats.max_drawdown_pct * 1.4), 0.5)
    ax2.legend(loc="lower left", facecolor="#1f2937", edgecolor="#374151", fontsize=8)
    ax2.grid(True, linestyle="--", alpha=0.2)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

    # ── Panel 4: Equity Curve Growth (Starting from $10,000 USD) ──
    ax3 = axes[3]
    ax3.set_title("Equity Curve Growth (Initial Capital: $10,000 USD)".replace("$", r"\$"),
                  fontsize=11, fontweight="bold", color="#93c5fd", loc="left")

    if len(equity_dates) == len(equity_curve) and len(equity_curve) > 0:
        eq_arr = np.array(equity_curve)
        init_cap = cfg.INITIAL_CAPITAL

        ax3.plot(equity_dates, equity_curve, color=COLOR_ACCENT, linewidth=1.8, label=f"NY ORB Equity ({equity_curve[-1]:,.2f} USD)")
        ax3.axhline(init_cap, color="#6b7280", linestyle=":", label=f"Initial Capital ({init_cap:,.0f} USD)")

        # Account balance mulai dari 10,000 bukan 0
        y_max = max(equity_curve) * 1.05
        ax3.set_ylim(bottom=init_cap, top=y_max)
        span = y_max - init_cap
        step = 5000 if span <= 35000 else (20000 if span <= 100000 else 100000)
        first_step = int((init_cap // step + 1) * step)
        y_ticks = [init_cap] + [t for t in range(first_step, int(y_max) + step, step)]
        ax3.set_yticks(y_ticks)
        ax3.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"${int(x):,}" if x >= 1000 else f"{int(x)}"))

        # HUD Metrics Box di area kosong atas-tengah
        stats_text = (
            f"Net PnL: +{stats.total_net_pnl_usd:,.2f} USD (+{(stats.total_net_pnl_usd/init_cap)*100:.1f}%)  |  "
            f"Win Rate: {stats.win_rate:.1f}% ({stats.winning_trades}W / {stats.losing_trades}L)  |  "
            f"Profit Factor: {stats.profit_factor:.2f}  |  "
            f"Sharpe: {stats.sharpe_ratio:.2f}  |  "
            f"Max DD: {stats.max_drawdown_usd:,.2f} USD ({stats.max_drawdown_pct:.2f}%)"
        )
        ax3.text(
            0.58, 0.88, stats_text,
            transform=ax3.transAxes, fontsize=8.5, fontweight="bold",
            ha="center", va="top", color="#e0f2fe",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#1e293b", edgecolor="#f59e0b", alpha=0.9)
        )

    ax3.set_ylabel("Account Balance (USD)", fontsize=9)
    ax3.set_xlabel("Date (UTC)", fontsize=9)
    ax3.grid(True, linestyle="--", alpha=0.2)
    ax3.legend(loc="upper left", facecolor="#1f2937", edgecolor="#374151", fontsize=8)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

    if save_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        abs_path = os.path.abspath(save_path)
        plt.savefig(abs_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
        print(f"      [✓] Dashboard NY ORB berhasil disimpan ke: {abs_path}")
        plt.close(fig)
    else:
        plt.show()
