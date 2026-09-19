"""
Asian Mean Reversion — Visualization Charts
==============================================
Dashboard 4-panel elegan tingkat institusional:
Panel 1: Price Action XAU/USD M5 & Sinyal Eksekusi Mean Reversion
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

import configs.asia_config as cfg
from engine.asia.signals import Direction, TradeResult
from engine.asia.backtester import BacktestStats


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

COLOR_CYAN     = "#38bdf8"
COLOR_BUY      = "#22c55e"       # Hijau cerah Long
COLOR_SELL     = "#ef4444"       # Merah Short
COLOR_GOLD     = "#fbbf24"
COLOR_DRAWDOWN = "#ef444433"


def plot_full_report(
    df: pd.DataFrame,
    trades: List[TradeResult],
    stats: BacktestStats,
    equity_curve: List[float],
    save_path: Optional[str] = None,
) -> None:
    """
    Generate dashboard visual institusional 4-panel bebas polusi visual.
    
    Panel 1: Price Action & Entry Points
    Panel 2: Monthly Net PnL Bar Chart
    Panel 3: Dedicated Underwater Drawdown Profile (%)
    Panel 4: Equity Curve Growth & HUD Metrics
    """
    fig, axes = plt.subplots(
        4, 1,
        figsize=(18, 15),
        height_ratios=[2.2, 1.3, 1.0, 1.8],
        gridspec_kw={"hspace": 0.30},
    )

    fig.suptitle(
        "Asian Mean Reversion (M5) — Performance Dashboard\n"
        "Anchor: SMA(20) | Z-Score Trigger: ±1.6 | SL: 1.5× ATR | Time Stop: 60M",
        fontsize=15,
        fontweight="bold",
        color="#38bdf8",
        y=0.988,
    )

    _plot_price_panel(axes[0], df, trades)
    _plot_monthly_pnl_panel(axes[1], trades)
    _plot_drawdown_panel(axes[2], trades, stats)
    _plot_equity_panel(axes[3], trades, stats)

    if save_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        abs_path = os.path.abspath(save_path)
        plt.savefig(abs_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
        print(f"[+] Chart disimpan ke: {abs_path}")
        plt.close(fig)
    else:
        plt.show()


# ─────────────────────────────────────────────
#  PANEL 1: PRICE + SIGNALS
# ─────────────────────────────────────────────

def _plot_price_panel(ax: plt.Axes, df: pd.DataFrame, trades: List[TradeResult]) -> None:
    """Price chart bersih dengan sampling dan marker transaksi."""
    ax.set_title("XAU/USD M5 Price Action & Asian MR Trade Executions (01:00 - 04:30 UTC)",
                 fontsize=11, fontweight="bold", color="#93c5fd", loc="left")

    step = max(1, len(df) // 1600)
    sampled = df.iloc[::step]
    ax.plot(sampled["datetime"], sampled["close"], color="#60a5fa", linewidth=0.85, alpha=0.45, label="XAU/USD M5 Close")

    long_trades = [t for t in trades if t.entry_signal.direction == Direction.LONG]
    short_trades = [t for t in trades if t.entry_signal.direction == Direction.SHORT]

    if long_trades:
        l_dts = [t.entry_signal.datetime for t in long_trades]
        l_prs = [t.entry_signal.entry_price for t in long_trades]
        ax.scatter(l_dts, l_prs, color=COLOR_BUY, marker="^", s=36, zorder=5, label=f"Long Entry ({len(long_trades)})")

    if short_trades:
        s_dts = [t.entry_signal.datetime for t in short_trades]
        s_prs = [t.entry_signal.entry_price for t in short_trades]
        ax.scatter(s_dts, s_prs, color=COLOR_SELL, marker="v", s=36, zorder=5, label=f"Short Entry ({len(short_trades)})")

    ax.set_ylabel("Price (USD)", fontsize=10)
    ax.grid(True, linestyle="--", alpha=0.2)
    ax.legend(loc="upper left", facecolor="#1f2937", edgecolor="#374151", fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))


# ─────────────────────────────────────────────
#  PANEL 2: MONTHLY NET PNL BAR CHART
# ─────────────────────────────────────────────

def _plot_monthly_pnl_panel(ax: plt.Axes, trades: List[TradeResult]) -> None:
    """Bar chart performa bulanan selama periode trading dengan nominal dolar."""
    ax.set_title("Monthly Net PnL (USD) — Consistency Across Regimes",
                 fontsize=11, fontweight="bold", color="#93c5fd", loc="left")

    if not trades:
        return

    rows = []
    for t in trades:
        rows.append({
            "dt": t.entry_signal.datetime,
            "pnl": t.pnl_usd,
        })
    df_t = pd.DataFrame(rows)
    df_t["month"] = df_t["dt"].dt.strftime("%Y-%m")
    m_pnl = df_t.groupby("month")["pnl"].sum()

    months = list(m_pnl.index)
    pnls = m_pnl.values
    colors = [COLOR_BUY if p >= 0 else COLOR_SELL for p in pnls]

    x = np.arange(len(months))
    ax.bar(x, pnls, color=colors, width=0.65, edgecolor="#0b0e14", alpha=0.85)

    ax.axhline(0, color="#6b7280", linewidth=0.8, linestyle="--")
    ax.set_xticks(x)
    ax.set_xticklabels(months, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Net PnL (USD)", fontsize=9)
    ax.grid(True, linestyle="--", alpha=0.2)

    # Tambahkan nominal di atas/bawah bar
    max_abs = max(abs(p) for p in pnls) if len(pnls) > 0 else 100
    y_offset = max_abs * 0.04
    for idx, val in enumerate(pnls):
        y_pos = val + y_offset if val >= 0 else val - y_offset * 1.6
        lbl = f"+${val:,.0f}" if val >= 0 else f"-${abs(val):,.0f}"
        ax.text(
            idx, y_pos, lbl.replace("$", r"\$"),
            ha="center", va="bottom" if val >= 0 else "top", fontsize=7.5,
            fontweight="bold", color=COLOR_BUY if val >= 0 else COLOR_SELL
        )
    ax.set_ylim(min(0, min(pnls) * 1.35), max(pnls) * 1.35)

    # Label ringkasan
    pos_months = sum(1 for p in pnls if p >= 0)
    total_months = len(pnls)
    win_pct = (pos_months / total_months * 100.0) if total_months > 0 else 0.0
    tot_net = sum(pnls)
    banner_text = (
        f"Profitable Months: {pos_months}/{total_months} ({win_pct:.1f}%) | "
        f"Total Net: +{tot_net:,.2f} USD"
    )
    ax.text(
        0.02, 0.90, banner_text,
        transform=ax.transAxes,
        fontsize=8.5, fontweight="bold", color=COLOR_GOLD,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#1f2937", edgecolor="#374151")
    )


# ─────────────────────────────────────────────
#  PANEL 3: DEDICATED UNDERWATER DRAWDOWN
# ─────────────────────────────────────────────

def _plot_drawdown_panel(
    ax: plt.Axes,
    trades: List[TradeResult],
    stats: BacktestStats,
) -> None:
    """Panel terdedikasi profil drawdown (%) kronologis."""
    ax.set_title("Portfolio Underwater Drawdown Profile (%)",
                 fontsize=11, fontweight="bold", color="#93c5fd", loc="left")

    if not trades:
        return

    init_cap = cfg.INITIAL_CAPITAL
    dates = [trades[0].entry_signal.datetime]
    equities = [init_cap]

    curr = init_cap
    for t in trades:
        curr += t.pnl_usd
        dates.append(t.exit_datetime)
        equities.append(curr)

    eq_arr = np.array(equities)
    peak = np.maximum.accumulate(eq_arr)
    dd_pct = ((peak - eq_arr) / peak) * 100.0

    ax.plot(dates, -dd_pct, color=COLOR_SELL, linewidth=1.0)
    ax.fill_between(dates, 0, -dd_pct, color=COLOR_DRAWDOWN, label="Drawdown Area")
    ax.axhline(-stats.max_drawdown_pct, color=COLOR_GOLD, linestyle=":", linewidth=1.1,
               label=f"Max Drawdown: {stats.max_drawdown_pct:.2f}% ({stats.max_drawdown_usd:,.2f} USD)")

    ax.set_ylabel("Drawdown (%)", fontsize=9)
    ax.set_ylim(-max(5.0, stats.max_drawdown_pct * 1.4), 0.5)
    ax.legend(loc="lower left", facecolor="#1f2937", edgecolor="#374151", fontsize=8)
    ax.grid(True, linestyle="--", alpha=0.2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))


# ─────────────────────────────────────────────
#  PANEL 4: EQUITY CURVE GROWTH
# ─────────────────────────────────────────────

def _plot_equity_panel(
    ax: plt.Axes,
    trades: List[TradeResult],
    stats: BacktestStats,
) -> None:
    """Kurva ekuitas kronologis trade-by-trade mulai dari $10,000 USD."""
    ax.set_title("Equity Curve Growth (Initial Capital: $10,000 USD)".replace("$", r"\$"),
                 fontsize=11, fontweight="bold", color="#93c5fd", loc="left")

    if not trades:
        return

    init_cap = cfg.INITIAL_CAPITAL
    dates = [trades[0].entry_signal.datetime]
    equities = [init_cap]

    curr = init_cap
    for t in trades:
        curr += t.pnl_usd
        dates.append(t.exit_datetime)
        equities.append(curr)

    eq_arr = np.array(equities)

    # Plot ekuitas
    ax.plot(dates, eq_arr, color=COLOR_CYAN, linewidth=1.8, label=f"Asian MR Equity ({equities[-1]:,.2f} USD)")
    ax.axhline(init_cap, color="#6b7280", linestyle=":", label=f"Initial Capital ({init_cap:,.0f} USD)")

    # Account balance mulai dari 10,000 bukan 0
    y_max = max(equities) * 1.05
    ax.set_ylim(bottom=init_cap, top=y_max)
    span = y_max - init_cap
    step = 2000 if span <= 15000 else (5000 if span <= 35000 else 20000)
    first_step = int((init_cap // step + 1) * step)
    y_ticks = [init_cap] + [t for t in range(first_step, int(y_max) + step, step)]
    ax.set_yticks(y_ticks)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"${int(x):,}" if x >= 1000 else f"{int(x)}"))

    # HUD Box di area atas-tengah
    stats_text = (
        f"Net PnL: +{stats.total_pnl_usd:,.2f} USD (+{(stats.total_pnl_usd/init_cap)*100:.1f}%)  |  "
        f"Win Rate: {stats.win_rate:.1f}% ({stats.winning_trades}W / {stats.losing_trades}L)  |  "
        f"Profit Factor: {stats.profit_factor:.2f}  |  "
        f"Sharpe: {stats.sharpe_ratio:.2f}  |  "
        f"Max DD: {stats.max_drawdown_usd:,.2f} USD ({stats.max_drawdown_pct:.2f}%)"
    )
    ax.text(
        0.58, 0.88, stats_text,
        transform=ax.transAxes, fontsize=8.5, fontweight="bold",
        ha="center", va="top", color="#e0f2fe",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#1e293b", edgecolor="#0ea5e9", alpha=0.9)
    )

    ax.set_ylabel("Account Balance (USD)", fontsize=9)
    ax.set_xlabel("Date (UTC)", fontsize=9)
    ax.grid(True, linestyle="--", alpha=0.2)
    ax.legend(loc="upper left", facecolor="#1f2937", edgecolor="#374151", fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))


# ─────────────────────────────────────────────
#  STANDALONE: TRADE LOG TABLE
# ─────────────────────────────────────────────

def print_trade_log(trade_log: pd.DataFrame) -> None:
    """Print trade log ke console dengan format rapi."""
    if trade_log.empty:
        print("\n[!] Tidak ada trade yang dihasilkan.\n")
        return

    print("\n" + "=" * 120)
    print("  ASIAN MEAN REVERSION — TRADE LOG (HEAD & TAIL)")
    print("=" * 120)

    display_cols = [
        "entry_datetime", "exit_datetime", "direction", "lot_size",
        "entry_price", "exit_price", "pnl_usd",
        "exit_reason", "duration_min",
    ]
    available = [c for c in display_cols if c in trade_log.columns]

    pd.set_option("display.max_columns", 15)
    pd.set_option("display.width", 120)
    pd.set_option("display.float_format", lambda x: f"{x:.2f}")

    if len(trade_log) > 20:
        head_tail = pd.concat([trade_log[available].head(10), trade_log[available].tail(10)])
        print(head_tail.to_string(index=False))
    else:
        print(trade_log[available].to_string(index=False))
    print("=" * 120 + "\n")
