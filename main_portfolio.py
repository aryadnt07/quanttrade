"""
Quantitative Master Portfolio — CLI Entry Point
===============================================
Eksekusi portofolio kuantitatif multi-sesi terpadu untuk XAU/USD:
- Modul 1: Asian Mean Reversion M5 (01:00 - 04:30 UTC, Risk 2.0%)
- Modul 2: New York Opening Range Breakout M5 (13:45 - 16:30 UTC, Risk 1.0%)

Beroperasi pada satu akun modal tunggal ($10,000)
dengan kontrol risiko asimetris, compounding pertumbuhan, dan de-risking dinamis.

Usage:
    python main_portfolio.py --data data/xauusd-m5-bid-2024-09-08-2026-09-08.csv
    python main_portfolio.py --data data/... --save-chart output/portfolio_chart.png --export-trades output/portfolio_trades.csv
"""

import argparse
import os
import sys

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import portfolio_config as pcfg
from utils.data_loader import load_csv
from engine.engine_portfolio.portfolio_engine import PortfolioEngine
from visualization.visualization_portfolio.portfolio_charts import (
    plot_portfolio_dashboard,
    print_portfolio_trade_log,
    print_monthly_attribution_table,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Quantitative Master Portfolio - XAU/USD (Asia MR + NY ORB)"
    )
    parser.add_argument(
        "--data", type=str, default="data/xauusd-m5-bid-2024-09-08-2026-09-08.csv",
        help="Path ke file CSV data M5 (OHLC)",
    )
    parser.add_argument(
        "--no-chart", action="store_true",
        help="Jalankan tanpa generate chart visual",
    )
    parser.add_argument(
        "--save-chart", type=str, default="output/portfolio_chart.png",
        help="Path output file image chart (PNG)",
    )
    parser.add_argument(
        "--export-trades", type=str, default="output/portfolio_trades.csv",
        help="Path export trade log master ke CSV",
    )
    parser.add_argument(
        "--export-log", type=str, default="output/portfolio_log.txt",
        help="Path export summary report ke TXT",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    print()
    print("=" * 68)
    print("   QUANTITATIVE MASTER PORTFOLIO — XAU/USD")
    print("   [Multi-Session: Asian Mean Reversion + New York ORB]")
    print("=" * 68)
    print()

    # ── 1. LOAD DATA ──
    print(f"[1/4] Loading M5 data dari: {args.data}")
    df_m5 = load_csv(args.data)
    print(f"      Loaded {len(df_m5):,} raw M5 bars")
    print(f"      Rentang: {df_m5['datetime'].iloc[0]} — {df_m5['datetime'].iloc[-1]}")
    print()

    # Print Konfigurasi Portofolio
    print("      --- KONFIGURASI MASTER PORTOFOLIO ---")
    print(f"      Modal Awal          : ${pcfg.PORTFOLIO_INITIAL_CAPITAL:,.2f} USD")
    print(f"      Modul 1 (Asia MR)   : {pcfg.ASIAN_ENTRY_WINDOW} (Risk: {pcfg.ASIAN_RISK_PCT*100:.1f}%)")
    if pcfg.ENABLE_STRATEGY_2:
        print(f"      Modul 2 (NY ORB)    : {pcfg.NY_ENTRY_WINDOW} (Risk: {pcfg.NY_RISK_PCT*100:.1f}%)")
    derisk_str = f"ON (50% risk pangkas jika {pcfg.DERISKING_CONSECUTIVE_DAYS} hari rugi berturut-turut)" if pcfg.ENABLE_DYNAMIC_DERISKING else "OFF"
    print(f"      Dynamic De-Risking  : {derisk_str}")
    print()

    # ── 2. JALANKAN PORTOFOLIO ENGINE ──
    print("[2/4] Mengeksekusi modul kuantitatif dengan asymmetric compounding...")
    engine = PortfolioEngine(df_m5)
    stats = engine.run()

    # ── 3. LAPORAN & ATRIBUSI BULANAN ──
    print("[3/4] Mengompilasi performa portofolio & tabel atribusi...")
    print(stats)
    print_monthly_attribution_table(stats.monthly_pnl_df)
    trade_log = engine.trade_log
    print_portfolio_trade_log(trade_log)

    if args.export_trades:
        os.makedirs(os.path.dirname(os.path.abspath(args.export_trades)), exist_ok=True)
        trade_log.to_csv(args.export_trades, index=False)
        print(f"[✓] Master trade log disimpan ke: {args.export_trades}")

    if args.export_log:
        os.makedirs(os.path.dirname(os.path.abspath(args.export_log)), exist_ok=True)
        with open(args.export_log, "w", encoding="utf-8") as f:
            f.write(str(stats))
            f.write("\n\n")
            f.write("MONTHLY ATTRIBUTION:\n")
            f.write(stats.monthly_pnl_df.to_string())
        print(f"[✓] Laporan teks disimpan ke: {args.export_log}")

    # ── 4. VISUALISASI DASHBOARD ──
    if not args.no_chart:
        print("[4/4] Me-render visual dashboard portofolio 4-panel...")
        try:
            plot_portfolio_dashboard(
                df_raw=df_m5,
                trades=engine.trades,
                stats=stats,
                equity_dates=engine.equity_dates,
                equity_curve=engine.equity_curve,
                asian_equity=engine.asian_equity,
                ny_equity=engine.ny_equity,
                save_path=args.save_chart,
            )
        except Exception as e:
            print(f"[!] Gagal me-render chart: {e}")
    else:
        print("[4/4] Visualisasi dilewati (--no-chart)")

    print("\n[✓] Simulasi Quantitative Master Portfolio selesai sukses!\n")


if __name__ == "__main__":
    main()
