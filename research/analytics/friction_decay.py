"""
Quantitative Master Portfolio — Friction & Slippage Decay Curve Engine
========================================================================
Metode validasi tingkat lanjut (Hedge Fund Institutional Standard):
1. Menguji batas ketahanan eksekusi (Execution Resilience & Decay Curve)
   terhadap lonjakan spread broker, komisi, dan slippage ekstrim.
2. Menguji rentang total friction (Round-Turn Spread + Slippage) dari:
   $0.00 s/d $3.00 USD/oz ($0 s/d $300 / lot).
3. Mengidentifikasi metrik kunci institusional:
   - Break-Even Friction Threshold (F_BE)
   - Safety Buffer Multiplier
   - Decay Half-Life (F_50%)
   - Sub-strategy Fragility
4. Menghasilkan visual dashboard 4-panel institusional.
"""

import os
import sys
import time
from typing import Dict, Any, List, Tuple
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# Windows console encoding fix
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.strategies.portfolio import config as pcfg
from src.strategies.asian_mr import config as acfg
from src.strategies.ny_orb import config as ny_cfg
from src.data.loader import load_csv
from src.strategies.asian_mr.signals import compute_asian_indicators as compute_asian
from src.strategies.asian_mr.backtester import AsianBacktester as AsianBT
from src.strategies.ny_orb.signals import compute_ny_indicators
from src.strategies.ny_orb.backtester import NYBacktester


# ─────────────────────────────────────────────
#  STYLE SETUP (DARK THEME QUANTITATIVE)
# ─────────────────────────────────────────────

COLOR_BG      = "#0b0e14"
COLOR_PANEL   = "#111827"
COLOR_GRID    = "#1f2937"
COLOR_CYAN    = "#38bdf8"
COLOR_GOLD    = "#fbbf24"
COLOR_GREEN   = "#22c55e"
COLOR_RED     = "#ef4444"
COLOR_PURPLE  = "#a855f7"
COLOR_MUTED   = "#9ca3af"


def extract_raw_trades(data_path: str = "data/xauusd-m5-bid-2021-09-08-2026-09-08.csv") -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """Ekstraksi transaksi murni (zero friction) dari Asian MR dan NY ORB."""
    print("[1/3] Memuat dataset XAU/USD M5 & mengekstraksi transaksi murni (zero-friction)...")
    df_raw = load_csv(data_path)
    df_a = compute_asian(df_raw)
    df_ny = compute_ny_indicators(df_raw)

    # 1. Asian MR trades
    orig_a_spread = acfg.SPREAD_USD
    acfg.SPREAD_USD = 0.0
    bt_a = AsianBT(df_a)
    bt_a.run()
    asian_raw = []
    for t in bt_a.trades:
        is_long = (t.entry_signal.direction.value == "LONG")
        entry_p = t.entry_signal.entry_price
        exit_p = t.exit_price
        raw_pts = (exit_p - entry_p) if is_long else (entry_p - exit_p)
        sl_dist = abs(entry_p - t.entry_signal.stop_loss)
        asian_raw.append({
            "strategy": "ASIAN_MR",
            "entry_dt": t.entry_signal.datetime,
            "entry_price": entry_p,
            "exit_price": exit_p,
            "direction": "BUY" if is_long else "SELL",
            "raw_points": raw_pts,
            "sl_dist": sl_dist,
        })
    acfg.SPREAD_USD = orig_a_spread

    # 2. NY ORB trades
    orig_ny_spread = ny_cfg.SPREAD_USD
    ny_cfg.SPREAD_USD = 0.0
    bt_ny = NYBacktester(df_ny)
    bt_ny.run()
    ny_raw = []
    for t in bt_ny.trades:
        dir_str = t.signal.direction.value
        entry_p = t.signal.entry_price
        exit_p = t.exit_price
        raw_pts = (exit_p - entry_p) if dir_str == "BUY" else (entry_p - exit_p)
        sl_dist = abs(entry_p - t.signal.stop_loss)
        ny_raw.append({
            "strategy": "NY_ORB",
            "entry_dt": t.signal.datetime,
            "entry_price": entry_p,
            "exit_price": exit_p,
            "direction": dir_str,
            "raw_points": raw_pts,
            "sl_dist": sl_dist,
        })
    ny_cfg.SPREAD_USD = orig_ny_spread

    master_raw = sorted(asian_raw + ny_raw, key=lambda x: x["entry_dt"])
    print(f"      Transaksi Murni Terekstraksi: {len(asian_raw)} Asian + {len(ny_raw)} NY = {len(master_raw)} Master.")
    return master_raw, asian_raw, ny_raw


def simulate_portfolio_under_friction(
    trades: List[Dict],
    friction_usd: float,
    initial_capital: float = 10_000.0,
    is_master: bool = True,
    fixed_strat_name: str = None
) -> Dict[str, Any]:
    """Simulasi portofolio dengan penalti friction spread + slippage pada setiap trade."""
    equity = initial_capital
    peak = initial_capital
    max_dd_pct = 0.0
    wins = 0
    losses = 0
    gross_profit = 0.0
    gross_loss = 0.0

    current_day = None
    day_pnl = 0.0
    consecutive_loss_days = 0
    in_cooldown = False

    for t in trades:
        dt = t["entry_dt"]
        day_date = dt.date()
        if current_day is None:
            current_day = day_date
        elif day_date != current_day:
            if day_pnl < 0:
                consecutive_loss_days += 1
                if consecutive_loss_days >= pcfg.DERISKING_CONSECUTIVE_DAYS:
                    in_cooldown = True
            else:
                consecutive_loss_days = 0
                in_cooldown = False
            current_day = day_date
            day_pnl = 0.0

        if is_master:
            base_risk = pcfg.ASIAN_RISK_PCT if t["strategy"] == "ASIAN_MR" else pcfg.NY_RISK_PCT
        else:
            base_risk = pcfg.ASIAN_RISK_PCT if fixed_strat_name == "ASIAN_MR" else pcfg.NY_RISK_PCT

        eff_risk = base_risk * pcfg.DERISKING_RATIO if (in_cooldown and pcfg.ENABLE_DYNAMIC_DERISKING) else base_risk

        risk_capital = equity * eff_risk
        sl_dist = t["sl_dist"]
        if sl_dist > 0:
            lot = risk_capital / (sl_dist * 100.0)
            lot = max(pcfg.MIN_LOT, min(pcfg.MAX_LOT, round(lot, 2)))
        else:
            lot = pcfg.MIN_LOT

        pnl_pts = t["raw_points"] - friction_usd
        pnl_usd = pnl_pts * lot * 100.0

        equity += pnl_usd
        day_pnl += pnl_usd

        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
        if dd > max_dd_pct:
            max_dd_pct = dd

        if pnl_usd > 0:
            wins += 1
            gross_profit += pnl_usd
            if in_cooldown:
                in_cooldown = False
                consecutive_loss_days = 0
        else:
            losses += 1
            gross_loss += abs(pnl_usd)

    pf = gross_profit / gross_loss if gross_loss > 0 else 99.0
    wr = (wins / len(trades) * 100.0) if len(trades) > 0 else 0.0

    return {
        "friction": friction_usd,
        "ending_capital": max(0.0, equity),
        "net_pnl": equity - initial_capital,
        "roi_pct": (equity - initial_capital) / initial_capital * 100.0,
        "win_rate": wr,
        "profit_factor": pf,
        "max_dd_pct": max_dd_pct,
        "total_trades": len(trades),
    }


def run_friction_decay_sweep(
    data_path: str = "data/xauusd-m5-bid-2021-09-08-2026-09-08.csv",
    friction_levels: List[float] = None,
) -> Dict[str, Any]:
    """Eksekusi sweep friction decay across Master, Asian MR, and NY ORB."""
    if friction_levels is None:
        friction_levels = [
            0.00, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60,
            0.75, 1.00, 1.25, 1.50, 1.75, 2.00, 2.50, 3.00
        ]

    print("=" * 76)
    print("   FRICTION & SLIPPAGE DECAY CURVE — STRESS TESTING ENGINE")
    print("=" * 76)
    print(f"  Rentang Friction Diuji : {friction_levels[0]:.2f} s/d {friction_levels[-1]:.2f} USD/oz")
    print(f"  Jumlah Titik Evaluasi  : {len(friction_levels)} level friction")
    print("=" * 76 + "\n")

    t0 = time.time()
    master_raw, asian_raw, ny_raw = extract_raw_trades(data_path)

    print("\n[2/3] Mensimulasikan kurva degradasi friction pada seluruh level...")
    master_results = []
    asian_results = []
    ny_results = []

    for f in friction_levels:
        m_res = simulate_portfolio_under_friction(master_raw, f, is_master=True)
        a_res = simulate_portfolio_under_friction(asian_raw, f, is_master=False, fixed_strat_name="ASIAN_MR")
        ny_res = simulate_portfolio_under_friction(ny_raw, f, is_master=False, fixed_strat_name="NY_ORB")

        master_results.append(m_res)
        asian_results.append(a_res)
        ny_results.append(ny_res)

    def find_breakeven(results: List[Dict[str, Any]]) -> float:
        for k in range(len(results) - 1):
            p1 = results[k]["net_pnl"]
            p2 = results[k + 1]["net_pnl"]
            f1 = results[k]["friction"]
            f2 = results[k + 1]["friction"]
            if p1 >= 0 and p2 < 0:
                return f1 + (0 - p1) / (p2 - p1) * (f2 - f1)
        if results[-1]["net_pnl"] >= 0:
            return results[-1]["friction"]
        return 0.0

    be_master = find_breakeven(master_results)
    be_asian = find_breakeven(asian_results)
    be_ny = find_breakeven(ny_results)

    def find_half_life(results: List[Dict[str, Any]]) -> float:
        base_profit = results[0]["net_pnl"]
        target = base_profit * 0.5
        for k in range(len(results) - 1):
            p1 = results[k]["net_pnl"]
            p2 = results[k + 1]["net_pnl"]
            f1 = results[k]["friction"]
            f2 = results[k + 1]["friction"]
            if p1 >= target and p2 < target:
                return f1 + (target - p1) / (p2 - p1) * (f2 - f1)
        return results[0]["friction"]

    half_master = find_half_life(master_results)

    elapsed = time.time() - t0
    print(f"\n[✓] Simulasi Friction Decay selesai dalam {elapsed:.2f} detik!")

    return {
        "friction_levels": friction_levels,
        "master_results": master_results,
        "asian_results": asian_results,
        "ny_results": ny_results,
        "be_master": be_master,
        "be_asian": be_asian,
        "be_ny": be_ny,
        "half_master": half_master,
        "baseline_spread": 0.30,
    }


def print_friction_report(res: Dict[str, Any]) -> None:
    """Cetak laporan komprehensif degradasi friction ke console."""
    f_levels = res["friction_levels"]
    m_res = res["master_results"]
    be_m = res["be_master"]
    be_a = res["be_asian"]
    be_ny = res["be_ny"]
    base_spread = res["baseline_spread"]
    buffer_ratio = be_m / base_spread if base_spread > 0 else 0.0

    sep = "=" * 90
    subsep = "-" * 90

    print(sep)
    print("   FRICTION & SLIPPAGE DECAY CURVE REPORT (INSTITUTIONAL STRESS TEST)")
    print("   XAU/USD Master Portfolio vs Standalone Sub-Strategies")
    print(sep)

    print(f"{'Friction ($/oz)':<15} | {'Master Capital':<16} | {'Master Net PnL':<15} | {'Master WR':<10} | {'Master PF':<10} | {'Max DD %':<8}")
    print(subsep)
    for m in m_res:
        f = m["friction"]
        tag = " (Baseline)" if abs(f - base_spread) < 1e-4 else ""
        f_str = f"${f:.2f}{tag}"
        print(f"{f_str:<15} | ${m['ending_capital']:<15,.2f} | ${m['net_pnl']:<14,.2f} | {m['win_rate']:<9.1f}% | {m['profit_factor']:<9.2f} | {m['max_dd_pct']:<7.2f}%")

    print(f"\n{sep}")
    print("ANALISIS METRIK KUNCI KETAHANAN EKSEKUSI (INSTITUTIONAL STRESS PROFILE):")
    print(f"  1. Master Portfolio Break-Even Friction (F_BE)  : ${be_m:.2f} USD/oz (${be_m*100:.0f} / lot)")
    print(f"  2. Normal Baseline Spread                     : ${base_spread:.2f} USD/oz ($30 / lot)")
    print(f"  3. Safety Buffer Multiplier                   : {buffer_ratio:.1f}x Normal Spread!")
    print(f"  4. Decay Half-Life (Profit Turun 50%)          : ${res['half_master']:.2f} USD/oz")
    print(f"  5. Standalone Asian MR Break-Even             : ${be_a:.2f} USD/oz")
    print(f"  6. Standalone New York ORB Break-Even         : ${be_ny:.2f} USD/oz")
    print(sep)
    print("=" * 90 + "\n")


def plot_friction_decay_dashboard(
    res: Dict[str, Any],
    save_path: str = "output/friction_decay_dashboard.png"
) -> None:
    """Render 4-panel visual dashboard grafik degradasi friction."""
    f_levels = res["friction_levels"]
    m_res = res["master_results"]
    a_res = res["asian_results"]
    ny_res = res["ny_results"]
    be_m = res["be_master"]
    base_spread = res["baseline_spread"]

    plt.rcParams.update({
        "figure.facecolor": COLOR_BG,
        "axes.facecolor": COLOR_PANEL,
        "axes.edgecolor": COLOR_GRID,
        "axes.labelcolor": "#9ca3af",
        "text.color": "#e0f2fe",
        "xtick.color": "#9ca3af",
        "ytick.color": "#9ca3af",
        "font.family": "sans-serif",
        "font.size": 9,
    })

    fig, axes = plt.subplots(2, 2, figsize=(18, 13), dpi=150)
    fig.subplots_adjust(hspace=0.28, wspace=0.20, top=0.92, bottom=0.07, left=0.08, right=0.94)

    fig.suptitle(
        "Friction & Slippage Decay Curve Dashboard — Institutional Execution Stress Test\n"
        "XAU/USD Master Portfolio (Asian Mean Reversion + New York ORB) | Friction Range: $0.00 – $3.00 USD/oz",
        fontsize=14, fontweight="bold", color="#38bdf8", y=0.985
    )

    m_cap = [m["ending_capital"] for m in m_res]
    m_pf  = [m["profit_factor"] for m in m_res]
    m_wr  = [m["win_rate"] for m in m_res]
    m_dd  = [m["max_dd_pct"] for m in m_res]

    a_pf  = [a["profit_factor"] for a in a_res]
    ny_pf = [ny["profit_factor"] for ny in ny_res]

    # PANEL 1: Ending Capital & Equity Decay Curve
    ax1 = axes[0, 0]
    ax1.set_title("Master Portfolio Capital Decay Curve (Initial: $10,000 USD)".replace("$", r"\$"),
                  fontsize=11, fontweight="bold", color="#93c5fd", loc="left", pad=10)

    ax1.plot(f_levels, m_cap, color=COLOR_GREEN, linewidth=2.5, marker="o", markersize=5, label="Master Portfolio Ending Capital")
    ax1.axhline(10_000.0, color="#ef4444", linestyle="--", linewidth=1.5, label="Initial Capital / Break-Even Threshold ($10,000)".replace("$", r"\$"))
    ax1.axvline(base_spread, color=COLOR_GOLD, linestyle=":", linewidth=2.0, label=f"Normal ECN Spread (${base_spread:.2f})".replace("$", r"\$"))
    ax1.axvline(be_m, color="#f43f5e", linestyle="-.", linewidth=2.0, label=f"Break-Even Limit (${be_m:.2f} / {be_m/base_spread:.1f}x Buffer)".replace("$", r"\$"))

    ax1.axvspan(0.0, be_m, color="#22c55e", alpha=0.08, label="Profitable Zone")
    ax1.axvspan(be_m, max(f_levels), color="#ef4444", alpha=0.08, label="Loss Zone (Friction Drag)")

    ax1.set_xlabel("Round-Turn Friction / Spread + Slippage (USD/oz)", fontsize=9, color="#9ca3af")
    ax1.set_ylabel("Ending Portfolio Capital ($ USD)".replace("$", r"\$"), fontsize=9, color="#9ca3af")
    ax1.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, p: f"${v:,.0f}"))
    ax1.set_xlim(0.0, max(f_levels))
    ax1.set_ylim(bottom=0.0)
    ax1.grid(True, linestyle="--", alpha=0.25, color=COLOR_GRID)
    ax1.legend(loc="upper right", framealpha=0.85, facecolor=COLOR_PANEL, edgecolor=COLOR_GRID, fontsize=8.5)

    # PANEL 2: Profit Factor Decay Surface
    ax2 = axes[0, 1]
    ax2.set_title("Mathematical Expectancy Decay (Profit Factor vs Friction)",
                  fontsize=11, fontweight="bold", color="#93c5fd", loc="left", pad=10)

    ax2.plot(f_levels, m_pf, color=COLOR_CYAN, linewidth=2.5, marker="s", markersize=5, label="Master Combined Portfolio")
    ax2.plot(f_levels, a_pf, color="#38bdf8", linestyle="--", linewidth=1.8, marker="^", markersize=4, alpha=0.85, label="Asian Mean Reversion")
    ax2.plot(f_levels, ny_pf, color=COLOR_GOLD, linestyle="--", linewidth=1.8, marker="d", markersize=4, alpha=0.85, label="New York ORB Breakout")

    ax2.axhline(1.0, color="#ef4444", linestyle="-", linewidth=1.8, label="Break-Even Expectancy (PF = 1.0)")
    ax2.axhline(1.5, color="#22c55e", linestyle=":", linewidth=1.5, label="Institutional Threshold (PF = 1.5)")
    ax2.axvline(be_m, color="#f43f5e", linestyle="-.", linewidth=1.5)

    ax2.set_xlabel("Round-Turn Friction / Spread + Slippage (USD/oz)", fontsize=9, color="#9ca3af")
    ax2.set_ylabel("Profit Factor", fontsize=9, color="#9ca3af")
    ax2.set_xlim(0.0, max(f_levels))
    ax2.set_ylim(0.0, max(m_pf) * 1.08)
    ax2.grid(True, linestyle="--", alpha=0.25, color=COLOR_GRID)
    ax2.legend(loc="upper right", framealpha=0.85, facecolor=COLOR_PANEL, edgecolor=COLOR_GRID, fontsize=8.5)

    # PANEL 3: Win Rate Degradation (%)
    ax3 = axes[1, 0]
    ax3.set_title("Win Rate Degradation from Execution Drag (%)",
                  fontsize=11, fontweight="bold", color="#93c5fd", loc="left", pad=10)

    ax3.plot(f_levels, m_wr, color="#a78bfa", linewidth=2.5, marker="o", markersize=5, label="Master Win Rate (%)")
    ax3.axvline(base_spread, color=COLOR_GOLD, linestyle=":", linewidth=2.0)
    ax3.axvline(be_m, color="#f43f5e", linestyle="-.", linewidth=2.0)

    wr_base = next(m["win_rate"] for m in m_res if abs(m["friction"] - base_spread) < 1e-4)
    ax3.scatter([base_spread], [wr_base], color=COLOR_GOLD, s=70, zorder=5)

    ax3.set_xlabel("Round-Turn Friction / Spread + Slippage (USD/oz)", fontsize=9, color="#9ca3af")
    ax3.set_ylabel("Win Rate (%)", fontsize=9, color="#9ca3af")
    ax3.yaxis.set_major_formatter(ticker.PercentFormatter())
    ax3.set_xlim(0.0, max(f_levels))
    ax3.set_ylim(0.0, 70.0)
    ax3.grid(True, linestyle="--", alpha=0.25, color=COLOR_GRID)
    ax3.legend(loc="upper right", framealpha=0.85, facecolor=COLOR_PANEL, edgecolor=COLOR_GRID, fontsize=8.5)

    # PANEL 4: Maximum Drawdown Escalation Surface (%)
    ax4 = axes[1, 1]
    ax4.set_title("Maximum Drawdown Escalation Under Severe Friction (%)",
                  fontsize=11, fontweight="bold", color="#93c5fd", loc="left", pad=10)

    ax4.plot(f_levels, m_dd, color="#f87171", linewidth=2.5, marker="v", markersize=5, label="Max Drawdown (%)")
    ax4.axvline(base_spread, color=COLOR_GOLD, linestyle=":", linewidth=2.0)
    ax4.axvline(be_m, color="#f43f5e", linestyle="-.", linewidth=2.0)
    ax4.axhline(20.0, color="#fbbf24", linestyle="--", linewidth=1.5, label="Institutional Max DD Cap (20%)")

    dd_base = next(m["max_dd_pct"] for m in m_res if abs(m["friction"] - base_spread) < 1e-4)
    ax4.scatter([base_spread], [dd_base], color=COLOR_GOLD, s=70, zorder=5)

    ax4.set_xlabel("Round-Turn Friction / Spread + Slippage (USD/oz)", fontsize=9, color="#9ca3af")
    ax4.set_ylabel("Max Drawdown (%)", fontsize=9, color="#9ca3af")
    ax4.yaxis.set_major_formatter(ticker.PercentFormatter())
    ax4.set_xlim(0.0, max(f_levels))
    ax4.set_ylim(0.0, 100.0)
    ax4.grid(True, linestyle="--", alpha=0.25, color=COLOR_GRID)
    ax4.legend(loc="upper left", framealpha=0.85, facecolor=COLOR_PANEL, edgecolor=COLOR_GRID, fontsize=8.5)

    if save_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        abs_path = os.path.abspath(save_path)
        if os.path.exists(abs_path):
            try:
                os.remove(abs_path)
            except Exception:
                pass
        plt.savefig(abs_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
        print(f"[+] Friction Decay Dashboard disimpan ke: {abs_path}")
        plt.close(fig)
    else:
        plt.show()


def main():
    res = run_friction_decay_sweep()
    print_friction_report(res)
    plot_friction_decay_dashboard(res, save_path="output/friction_decay_dashboard.png")


if __name__ == "__main__":
    main()
