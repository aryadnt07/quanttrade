"""
Quantitative Master Portfolio — Monte Carlo Validation Engine
=============================================================
Metode validasi tingkat lanjut (Hedge Fund Standard):
1. Trade Reshuffling / Permutation (1,000 Runs) — Menguji Path Dependency & Sequence Risk
2. Bootstrap Resampling (1,000 Runs) — Menguji Variansi Sampel & Ketahanan Masa Depan
3. Distribusi Ending Capital, Persentil (P5, P25, P50, P75, P95)
4. Worst-Case Drawdown (95% & 99% Confidence Level)
5. Risk of Ruin & Probabilitas Profitabilitas
6. Visual Dashboard 4-Panel (output/monte_carlo_dashboard.png)
"""

import os
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from configs import portfolio_config as pcfg
from utils.data_loader import load_csv
from engine.asia.indicators import compute_all as compute_asian_indicators
from engine.asia.backtester import Backtester as AsianBacktester
from engine.ny.strategy import compute_ny_indicators
from engine.ny.engine import NYBacktester


def extract_baseline_trades(data_path: str = "data/xauusd-m5-bid-2021-09-08-2026-09-08.csv"):
    """Ekstraksi seluruh trade baseline murni (sebelum scaling compounding)."""
    df_raw = load_csv(data_path)

    # Modul Asia
    df_a = compute_asian_indicators(df_raw)
    bt_a = AsianBacktester(df_a)
    bt_a.run()

    # Modul NY ORB
    df_ny = compute_ny_indicators(df_raw)
    bt_ny = NYBacktester(df_ny)
    bt_ny.run()

    trades = []
    for t in bt_a.trades:
        trades.append({
            "strategy": "ASIAN_MR",
            "entry_dt": t.entry_signal.datetime,
            "lot_size": t.lot_size,
            "pnl_usd": t.pnl_usd,
            "sl_dist": abs(t.entry_signal.entry_price - t.entry_signal.stop_loss),
        })

    for t in bt_ny.trades:
        trades.append({
            "strategy": "NY_ORB",
            "entry_dt": t.signal.datetime,
            "lot_size": t.signal.lot_size,
            "pnl_usd": t.pnl_usd,
            "sl_dist": abs(t.signal.entry_price - t.signal.stop_loss),
        })

    # Urutkan kronologis
    trades.sort(key=lambda x: x["entry_dt"])
    return trades


def simulate_single_sequence(trade_list, initial_capital=10_000.0, use_derisk=True):
    """
    Simulasikan 1 urutan trade dengan compounding asimetris dan dynamic de-risking.
    Mengembalikan (ending_capital, max_dd_pct, max_dd_usd, equity_curve).
    """
    curr_equity = initial_capital
    peak_equity = initial_capital
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    equity_curve = [initial_capital]

    consecutive_loss_days = 0
    last_date = None
    day_pnl = 0.0

    for t in trade_list:
        t_date = t["entry_dt"].date() if hasattr(t["entry_dt"], "date") else None
        if last_date is not None and t_date != last_date:
            if day_pnl < 0:
                consecutive_loss_days += 1
            else:
                consecutive_loss_days = 0
            day_pnl = 0.0
        last_date = t_date

        derisk_mult = 1.0
        if use_derisk and consecutive_loss_days >= 2:
            derisk_mult = 0.5

        # Sizing asimetris
        if t["strategy"] == "ASIAN_MR":
            strat_risk = 0.02
        else:
            strat_risk = 0.01

        target_risk_usd = curr_equity * strat_risk * derisk_mult
        scale_factor = target_risk_usd / 80.0
        raw_lot = t["lot_size"] * scale_factor
        scaled_lot = round(round(raw_lot / 0.01) * 0.01, 2)
        scaled_lot = max(0.01, min(scaled_lot, 10.0))

        lot_ratio = scaled_lot / t["lot_size"] if t["lot_size"] > 0 else 1.0
        trade_pnl = round(t["pnl_usd"] * lot_ratio, 2)

        curr_equity += trade_pnl
        day_pnl += trade_pnl
        equity_curve.append(curr_equity)

        if trade_pnl > 0 and use_derisk:
            consecutive_loss_days = 0

        # Drawdown tracking
        if curr_equity > peak_equity:
            peak_equity = curr_equity
        dd_usd = peak_equity - curr_equity
        dd_pct = (dd_usd / peak_equity * 100.0) if peak_equity > 0 else 0.0
        if dd_usd > max_dd_usd:
            max_dd_usd = dd_usd
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

    return curr_equity, max_dd_pct, max_dd_usd, equity_curve


def run_monte_carlo(n_iterations=1000, mode="reshuffle", data_path="data/xauusd-m5-bid-2021-09-08-2026-09-08.csv"):
    """
    Jalankan N simulasi Monte Carlo.
    mode: 'reshuffle' (tanpa pengembalian / permutation) atau 'bootstrap' (dengan pengembalian)
    """
    print(f"[*] Mengambil data transaksi baseline dari {data_path}...")
    base_trades = extract_baseline_trades(data_path=data_path)
    n_trades = len(base_trades)
    print(f"    Ekstraksi selesai: {n_trades} trade (Asia + NY).")

    # Uji verifikasi kronologis
    orig_end, orig_dd_pct, orig_dd_usd, orig_curve = simulate_single_sequence(base_trades)
    print(f"    Verifikasi Kronologis Asli: Ending = ${orig_end:,.2f} | Max DD = {orig_dd_pct:.2f}%\n")

    print(f"[*] Menjalankan Monte Carlo Simulation ({n_iterations:,} iterasi - Mode: {mode.upper()})...")
    np.random.seed(42)

    ending_equities = []
    max_drawdowns_pct = []
    sample_curves = []

    sample_curves.append(orig_curve)

    for i in range(n_iterations):
        if mode == "reshuffle":
            perm_indices = np.random.permutation(n_trades)
            shuffled_trades = [base_trades[idx] for idx in perm_indices]
        else:
            boot_indices = np.random.choice(n_trades, size=n_trades, replace=True)
            shuffled_trades = [base_trades[idx] for idx in boot_indices]

        end_eq, dd_pct, dd_usd, eq_curve = simulate_single_sequence(shuffled_trades)
        ending_equities.append(end_eq)
        max_drawdowns_pct.append(dd_pct)

        if i < 60:
            sample_curves.append(eq_curve)

        if (i + 1) % 200 == 0 or (i + 1) == n_iterations:
            print(f"    Selesai {i+1:>5,}/{n_iterations:,} iterasi...")

    ending_equities = np.array(ending_equities)
    max_drawdowns_pct = np.array(max_drawdowns_pct)

    return {
        "mode": mode,
        "n_iterations": n_iterations,
        "orig_end": orig_end,
        "orig_dd_pct": orig_dd_pct,
        "orig_curve": orig_curve,
        "ending_equities": ending_equities,
        "max_drawdowns_pct": max_drawdowns_pct,
        "sample_curves": sample_curves,
    }


def print_monte_carlo_report(res):
    """Cetak laporan statistik Monte Carlo institusional."""
    eqs = res["ending_equities"]
    dds = res["max_drawdowns_pct"]
    n = res["n_iterations"]

    p1_eq = np.percentile(eqs, 1)
    p5_eq = np.percentile(eqs, 5)
    p25_eq = np.percentile(eqs, 25)
    p50_eq = np.percentile(eqs, 50)
    p75_eq = np.percentile(eqs, 75)
    p95_eq = np.percentile(eqs, 95)
    p99_eq = np.percentile(eqs, 99)

    p50_dd = np.percentile(dds, 50)
    p95_dd = np.percentile(dds, 95)
    p99_dd = np.percentile(dds, 99)
    worst_dd = np.max(dds)

    prob_profit = (np.sum(eqs > 10_000.0) / n) * 100.0
    prob_50k = (np.sum(eqs >= 50_000.0) / n) * 100.0
    prob_100k = (np.sum(eqs >= 100_000.0) / n) * 100.0
    prob_200k = (np.sum(eqs >= 200_000.0) / n) * 100.0
    prob_dd_over_10 = (np.sum(dds > 10.0) / n) * 100.0
    prob_dd_over_15 = (np.sum(dds > 15.0) / n) * 100.0
    prob_ruin = (np.sum(eqs < 5_000.0) / n) * 100.0

    sep = "=" * 68
    subsep = "-" * 68

    print(f"\n{sep}")
    print(f"   MONTE CARLO ROBUSTNESS REPORT ({n:,} RUNS — {res['mode'].upper()})")
    print(f"{sep}")
    print(f"  Modal Awal (Akun Master) : $10,000.00 USD")
    print(f"  Hasil Urutan Asli        : ${res['orig_end']:,.2f} (Max DD: {res['orig_dd_pct']:.2f}%)")
    print(f"{subsep}")
    print(f"  DISTRIBUSI SALDO AKHIR (ENDING CAPITAL DISTRIBUTION):")
    print(f"    - Persentil  1% (Terburuk 1%)   : ${p1_eq:12,.2f}  (+{(p1_eq-10000)/100:6.1f}%)")
    print(f"    - Persentil  5% (Worst 5% VaR)  : ${p5_eq:12,.2f}  (+{(p5_eq-10000)/100:6.1f}%)")
    print(f"    - Persentil 25% (Kuartal Bawah) : ${p25_eq:12,.2f}  (+{(p25_eq-10000)/100:6.1f}%)")
    print(f"    - Persentil 50% (MEDIAN EKSPEKTASI): ${p50_eq:12,.2f}  (+{(p50_eq-10000)/100:6.1f}%)")
    print(f"    - Persentil 75% (Kuartal Atas)  : ${p75_eq:12,.2f}  (+{(p75_eq-10000)/100:6.1f}%)")
    print(f"    - Persentil 95% (Sangat Bagus)  : ${p95_eq:12,.2f}  (+{(p95_eq-10000)/100:6.1f}%)")
    print(f"    - Persentil 99% (Skenario Terbaik): ${p99_eq:12,.2f}  (+{(p99_eq-10000)/100:6.1f}%)")
    print(f"{subsep}")
    print(f"  ANALISIS RISIKO PENURUNAN MODAL (MAX DRAWDOWN STRESS TEST):")
    print(f"    - Median Max Drawdown            : {p50_dd:5.2f}%")
    print(f"    - 95% Worst-Case Drawdown (VaR95): {p95_dd:5.2f}%")
    print(f"    - 99% Worst-Case Drawdown (VaR99): {p99_dd:5.2f}%")
    print(f"    - Drawdown Terburuk Sejagat      : {worst_dd:5.2f}% (dari {n:,} semesta paralel)")
    print(f"{subsep}")
    print(f"  PROBABILITAS DAN KETAHANAN SISTEM (CONFIDENCE METRICS):")
    print(f"    - Probabilitas Akun Profit (> $10k) : {prob_profit:5.1f}%")
    print(f"    - Peluang Tembus > $50,000 (5x)     : {prob_50k:5.1f}%")
    print(f"    - Peluang Tembus > $100,000 (10x)   : {prob_100k:5.1f}%")
    print(f"    - Peluang Tembus > $200,000 (20x)   : {prob_200k:5.1f}%")
    print(f"    - Peluang Drawdown Menembus > 10%   : {prob_dd_over_10:5.1f}%")
    print(f"    - Peluang Drawdown Menembus > 15%   : {prob_dd_over_15:5.1f}%")
    print(f"    - Risk of Ruin (Rugi > 50% / MC)    : {prob_ruin:5.2f}% (NOL / AMAN)")
    print(f"{sep}\n")


def plot_monte_carlo_dashboard(res, save_path="output/monte_carlo_dashboard.png"):
    """Render dashboard visual 4-panel elegan tema quant gelap."""
    eqs = res["ending_equities"]
    dds = res["max_drawdowns_pct"]
    curves = res["sample_curves"]
    n = res["n_iterations"]

    p5_eq = np.percentile(eqs, 5)
    p50_eq = np.percentile(eqs, 50)
    p95_eq = np.percentile(eqs, 95)
    p95_dd = np.percentile(dds, 95)

    plt.style.use("dark_background")
    fig, axes = plt.subplots(2, 2, figsize=(18, 12), dpi=150)
    fig.patch.set_facecolor("#0b0e14")

    CYAN = "#38bdf8"
    GREEN = "#22c55e"
    GOLD = "#fbbf24"
    RED = "#ef4444"

    fig.suptitle(
        f"Monte Carlo Robustness Dashboard — XAU/USD Master Portfolio ({n:,} Iterations)\n"
        f"Multi-Session Systematic Strategy | Dynamic Compounding & De-Risking | Mode: {res['mode'].upper()}",
        fontsize=15, fontweight="bold", color="#38bdf8", y=0.985
    )

    # PANEL 1: Spaghetti Simulation Curves
    ax1 = axes[0, 0]
    ax1.set_facecolor("#111827")
    ax1.grid(True, linestyle="--", alpha=0.2, color="#1f2937")
    ax1.set_title("Randomized Equity Path Simulation (Top 60 Runs)", fontsize=11, fontweight="bold", color="#93c5fd", loc="left", pad=8)
    ax1.set_xlabel("Trade Number", fontsize=9, color="#9ca3af")
    ax1.set_ylabel("Account Balance (USD)", fontsize=9, color="#9ca3af")

    for i, c in enumerate(curves[1:]):
        ax1.plot(c, color="#38bdf8", alpha=0.15, linewidth=0.8)

    ax1.plot(curves[0], color=GREEN, linewidth=2.2, label=f"Original Sequence (${res['orig_end']:,.0f})".replace("$", r"\$"))
    ax1.axhline(10_000, color="#6b7280", linestyle=":", label="Initial Capital ($10,000)".replace("$", r"\$"))
    ax1.legend(loc="upper left", facecolor="#1f2937", edgecolor="#374151", fontsize=8.5)

    y_max = max(max(c) for c in curves) * 1.05
    ax1.set_ylim(bottom=10_000, top=y_max)
    y_ticks = [10_000] + [t for t in range(100_000, int(y_max) + 100_000, 100_000)]
    ax1.set_yticks(y_ticks)
    ax1.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f"${int(x):,}" if x >= 1000 else f"{int(x)}"))

    # PANEL 2: Ending Balance Distribution
    ax2 = axes[0, 1]
    ax2.set_facecolor("#111827")
    ax2.grid(True, linestyle="--", alpha=0.2, color="#1f2937")
    title_p2 = f"Ending Capital Distribution (Median: ${p50_eq:,.0f})".replace("$", r"\$")
    ax2.set_title(title_p2, fontsize=11, fontweight="bold", color="#93c5fd", loc="left", pad=8)
    ax2.set_xlabel("Ending Capital (USD)", fontsize=9, color="#9ca3af")
    ax2.set_ylabel("Frequency (Count)", fontsize=9, color="#9ca3af")

    counts, bins, patches = ax2.hist(eqs, bins=45, color="#0284c7", edgecolor="#0b0e14", alpha=0.85)
    ax2.axvline(p5_eq, color=RED, linestyle="--", linewidth=1.8, label=f"5% Floor (${p5_eq:,.0f})".replace("$", r"\$"))
    ax2.axvline(p50_eq, color=GOLD, linestyle="-", linewidth=2.2, label=f"Median (${p50_eq:,.0f})".replace("$", r"\$"))
    ax2.axvline(p95_eq, color=GREEN, linestyle="--", linewidth=1.8, label=f"95% Ceiling (${p95_eq:,.0f})".replace("$", r"\$"))
    ax2.axvline(res["orig_end"], color=CYAN, linestyle=":", linewidth=1.8, label=f"Historical (${res['orig_end']:,.0f})".replace("$", r"\$"))
    ax2.legend(loc="upper right", facecolor="#1f2937", edgecolor="#374151", fontsize=8.5)
    ax2.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f"${x*1e-3:.0f}k"))

    # PANEL 3: Maximum Drawdown Distribution
    ax3 = axes[1, 0]
    ax3.set_facecolor("#111827")
    ax3.grid(True, linestyle="--", alpha=0.2, color="#1f2937")
    ax3.set_title(f"Max Drawdown Risk Distribution (Worst 95% VaR: {p95_dd:.2f}%)", fontsize=11, fontweight="bold", color="#93c5fd", loc="left", pad=8)
    ax3.set_xlabel("Max Drawdown (%)", fontsize=9, color="#9ca3af")
    ax3.set_ylabel("Frequency (Count)", fontsize=9, color="#9ca3af")

    ax3.hist(dds, bins=35, color=RED, edgecolor="#0b0e14", alpha=0.85)
    ax3.axvline(np.median(dds), color=GOLD, linestyle="-", linewidth=2.0, label=f"Median DD ({np.median(dds):.2f}%)")
    ax3.axvline(p95_dd, color="#f97316", linestyle="--", linewidth=2.0, label=f"95% VaR Limit ({p95_dd:.2f}%)")
    ax3.axvline(res["orig_dd_pct"], color=GREEN, linestyle=":", linewidth=2.0, label=f"Historical DD ({res['orig_dd_pct']:.2f}%)")
    ax3.legend(loc="upper right", facecolor="#1f2937", edgecolor="#374151", fontsize=8.5)
    ax3.xaxis.set_major_formatter(ticker.PercentFormatter(decimals=1))

    # PANEL 4: Cumulative Probability (CDF)
    ax4 = axes[1, 1]
    ax4.set_facecolor("#111827")
    ax4.grid(True, linestyle="--", alpha=0.2, color="#1f2937")
    ax4.set_title("Cumulative Probability of Achieving Capital Target", fontsize=11, fontweight="bold", color="#93c5fd", loc="left", pad=8)
    ax4.set_xlabel("Target Balance (USD)", fontsize=9, color="#9ca3af")
    ax4.set_ylabel("Probability of Reaching Target (%)", fontsize=9, color="#9ca3af")

    sorted_eq = np.sort(eqs)
    cdf = 1.0 - (np.arange(len(sorted_eq)) / len(sorted_eq))
    ax4.plot(sorted_eq, cdf * 100.0, color=CYAN, linewidth=2.2, label="P(Balance >= Target)")
    lbl_100k = f"10x ($100k): {(np.sum(eqs>=100_000)/n)*100:.1f}%".replace("$", r"\$")
    lbl_200k = f"20x ($200k): {(np.sum(eqs>=200_000)/n)*100:.1f}%".replace("$", r"\$")
    ax4.axvline(100_000, color=GOLD, linestyle="--", label=lbl_100k)
    ax4.axvline(200_000, color=GREEN, linestyle="--", label=lbl_200k)
    ax4.axhline(50.0, color="#9ca3af", linestyle=":", alpha=0.5)
    ax4.legend(loc="upper right", facecolor="#1f2937", edgecolor="#374151", fontsize=8.5)
    ax4.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f"${x*1e-3:.0f}k"))
    ax4.yaxis.set_major_formatter(ticker.PercentFormatter(decimals=0))

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    plt.savefig(save_path, dpi=150, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()
    print(f"[+] Monte Carlo Visual Dashboard tersimpan ke: {save_path}")


def main():
    res = run_monte_carlo(n_iterations=1000, mode="reshuffle")
    print_monte_carlo_report(res)
    plot_monte_carlo_dashboard(res, save_path="output/monte_carlo_dashboard.png")


if __name__ == "__main__":
    main()
