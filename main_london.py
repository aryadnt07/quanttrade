"""
London Pit Opening Range Breakout (London Pit ORB) — Standalone Runner
=======================================================================
Eksekusi backtest mandiri untuk strategi London Pit ORB pada XAU/USD M5.
Mencetak statistik performa, mengekspor log trade ke CSV, dan menghasilkan ringkasan.

Usage:
    python main_london.py
    python main_london.py --data data/xauusd-m5-bid-2021-09-08-2026-09-08.csv
    python main_london.py --no-chart
"""

import argparse
import os
import sys

# Windows UTF-8 encoding fix
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

import configs.london_config as cfg
from utils.data_loader import load_csv, get_default_data_path
from engine.london.strategy import compute_london_indicators
from engine.london.engine import LondonBacktester


def parse_args():
    parser = argparse.ArgumentParser(description="London Pit Opening Range Breakout (London Pit ORB) Runner")
    parser.add_argument("--data", type=str, default=None, help="Path ke file data CSV M5")
    parser.add_argument("--data-m1", type=str, default="data/xauusd-m1-bid-2021-09-08-2026-09-08.csv", help="Path ke file data CSV M1 untuk Bar Magnifier")
    parser.add_argument("--use-m1", action="store_true", default=True, help="Aktifkan eksekusi M1 Bar Magnifier (Default: True jika file ada)")
    parser.add_argument("--no-m1", action="store_true", help="Nonaktifkan eksekusi M1 (jalankan murni M5)")
    parser.add_argument("--no-chart", action="store_true", help="Jangan generate gambar chart")
    parser.add_argument("--save-chart", type=str, default="output/london_chart.png", help="Path output file chart")
    parser.add_argument("--export-trades", type=str, default="output/london_trades.csv", help="Path output trade log CSV")
    return parser.parse_args()


def main():
    args = parse_args()

    print("\n" + "=" * 64)
    print("   LONDON PIT OPENING RANGE BREAKOUT (LONDON ORB) — XAU/USD")
    use_m1 = args.use_m1 and not args.no_m1 and os.path.exists(args.data_m1)
    mode_str = "M1 Bar Magnifier (1-Min Precision)" if use_m1 else "M5 Native Engine"
    print(f"   [Execution Mode: {mode_str}]")
    print("=" * 64)

    # 1. Load Data M5
    data_path = args.data or get_default_data_path()
    print(f"[*] Loading data M5: {data_path}")
    df = load_csv(data_path)
    print(f"[✓] Data M5 berhasil dimuat: {len(df):,} bar")

    # Load Data M1 jika aktif
    df_m1 = None
    if use_m1:
        print(f"[*] Loading data M1 Bar Magnifier: {args.data_m1}")
        df_m1 = load_csv(args.data_m1)
        print(f"[✓] Data M1 berhasil dimuat: {len(df_m1):,} sub-bars")

    # 2. Hitung Indikator & Opening Range
    print("[*] Menghitung indikator teknikal & Opening Range M15 (08:00 - 08:15 UTC)...")
    df_london = compute_london_indicators(df)

    # 3. Jalankan Backtest
    print(f"[*] Menjalankan simulasi London Pit ORB ({mode_str})...")
    bt = LondonBacktester(df_london, initial_capital=cfg.INITIAL_CAPITAL, df_m1=df_m1)
    stats = bt.run()

    # 4. Cetak Laporan Performa
    print(stats)

    # 5. Export Trade Log ke CSV
    if args.export_trades:
        os.makedirs(os.path.dirname(os.path.abspath(args.export_trades)), exist_ok=True)
        trade_df = bt.trade_log
        if not trade_df.empty:
            trade_df.to_csv(args.export_trades, index=False)
            print(f"[✓] Trade log diekspor ke: {args.export_trades} ({len(trade_df)} baris)")
        else:
            print("[!] Tidak ada trade yang dihasilkan untuk diekspor.")

    print("[✓] Eksekusi London Pit ORB selesai.\n")


if __name__ == "__main__":
    main()
