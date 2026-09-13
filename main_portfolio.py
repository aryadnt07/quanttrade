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
from utils.mtf_loader import load_mtf_dataset
from engine.engine_portfolio.portfolio_engine import PortfolioEngine
from visualization.visualization_portfolio.portfolio_charts import (
    plot_portfolio_dashboard,
    print_portfolio_trade_log,
    print_monthly_attribution_table,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Quantitative Master Portfolio - XAU/USD (Asia MR + NY ORB Multi-Timeframe)"
    )
    parser.add_argument(
        "--data", type=str, default=getattr(pcfg, "DEFAULT_DATA_M5", "data/xauusd-m5-bid-2021-09-08-2026-09-08.csv"),
        help="Path ke file CSV data M5 (OHLC)",
    )
    parser.add_argument(
        "--data-h1", type=str, default=getattr(pcfg, "DEFAULT_DATA_H1", "data/xauusd-h1-bid-2021-09-08-2026-09-08.csv"),
        help="Path ke file CSV data H1 (opsional, auto-resample jika tidak ada)",
    )
    parser.add_argument(
        "--data-h4", type=str, default=getattr(pcfg, "DEFAULT_DATA_H4", "data/xauusd-h4-bid-2021-09-08-2026-09-08.csv"),
        help="Path ke file CSV data H4 (opsional, auto-resample jika tidak ada)",
    )
    parser.add_argument(
        "--data-m15", type=str, default=getattr(pcfg, "DEFAULT_DATA_M15", "data/xauusd-m15-bid-2021-09-08-2026-09-08.csv"),
        help="Path ke file CSV data M15 (opsional)",
    )
    parser.add_argument(
        "--use-mtf", action="store_true",
        help="Aktifkan filter konfluensi Higher Timeframe (H1 Trend Filter). Default: False (M5 murni seperti semula)",
    )
    parser.add_argument(
        "--data-m1", type=str, default=getattr(pcfg, "DEFAULT_DATA_M1", "data/xauusd-m1-bid-2021-09-08-2026-09-08.csv"),
        help="Path ke file CSV data M1 untuk eksekusi Bar Magnifier (opsional)",
    )
    parser.add_argument(
        "--use-m1", action="store_true", default=getattr(pcfg, "USE_M1_EXECUTION", True),
        help="Aktifkan eksekusi presisi 1-menit (Bar Magnifier) untuk London & NY ORB. Default: True",
    )
    parser.add_argument(
        "--no-m1", action="store_true",
        help="Nonaktifkan eksekusi M1 (jalankan murni M5)",
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
    use_m1 = args.use_m1 and not args.no_m1 and os.path.exists(args.data_m1)
    exec_mode = "M1 Bar Magnifier (1-Min Precision)" if use_m1 else "M5 Native Engine"
    mtf_mode = "M5 + H1 MTF" if args.use_mtf else "M5 Native"
    print(f"   [{mtf_mode} | Execution: {exec_mode}]")
    print("=" * 68)
    print()

    # ── 1. LOAD DATA ──
    if args.use_mtf:
        import ny_config as ny_cfg
        ny_cfg.USE_HTF_TREND_FILTER = True
        print(f"[1/4] Loading Multi-Timeframe data (M5, H1, H4, M15)...")
        df_m5, htf_dfs = load_mtf_dataset(
            m5_path=args.data,
            h1_path=args.data_h1,
            h4_path=args.data_h4,
            m15_path=args.data_m15
        )
        print(f"      Loaded {len(df_m5):,} M5 execution bars dengan fitur HTF terpadu")
    else:
        import ny_config as ny_cfg
        ny_cfg.USE_HTF_TREND_FILTER = False
        print(f"[1/4] Loading native M5 data dari: {args.data}")
        df_m5 = load_csv(args.data)
        print(f"      Loaded {len(df_m5):,} raw M5 execution bars (M5 Murni)")
    print(f"      Rentang M5: {df_m5['datetime'].iloc[0]} — {df_m5['datetime'].iloc[-1]}")

    df_m1 = None
    if use_m1:
        print(f"      Loading M1 Bar Magnifier data dari: {args.data_m1}")
        df_m1 = load_csv(args.data_m1)
        df_m1['date'] = df_m1['datetime'].dt.date
        df_m1['hour'] = df_m1['datetime'].dt.hour
        df_m1['minute'] = df_m1['datetime'].dt.minute
        print(f"      Loaded {len(df_m1):,} raw M1 sub-bars untuk Bar Magnifier Execution")
    print()

    # Print Konfigurasi Portofolio
    print("      --- KONFIGURASI MASTER PORTOFOLIO ---")
    print(f"      Modal Awal          : ${pcfg.PORTFOLIO_INITIAL_CAPITAL:,.2f} USD")
    print(f"      Modul 1 (Asia MR)   : {pcfg.ASIAN_ENTRY_WINDOW} (Risk: {pcfg.ASIAN_RISK_PCT*100:.1f}%)")
    if getattr(pcfg, "ENABLE_LONDON_ORB", False):
        print(f"      Modul 2 (London ORB): {pcfg.LONDON_ENTRY_WINDOW} (Risk: {pcfg.LONDON_RISK_PCT*100:.1f}%)")
    if pcfg.ENABLE_STRATEGY_2:
        print(f"      Modul 3 (NY ORB)    : {pcfg.NY_ENTRY_WINDOW} (Risk: {pcfg.NY_RISK_PCT*100:.1f}%)")
    derisk_str = f"ON (50% risk pangkas jika {pcfg.DERISKING_CONSECUTIVE_DAYS} hari rugi berturut-turut)" if pcfg.ENABLE_DYNAMIC_DERISKING else "OFF"
    print(f"      Dynamic De-Risking  : {derisk_str}")
    print(f"      Bar Magnifier (M1)  : {'ACTIVE' if df_m1 is not None else 'OFF (M5)'}")
    print()

    # ── 2. JALANKAN PORTOFOLIO ENGINE ──
    print("[2/4] Mengeksekusi modul kuantitatif dengan asymmetric compounding...")
    engine = PortfolioEngine(df_m5, df_m1=df_m1)
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
                london_equity=engine.london_equity,
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
