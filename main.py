"""
Asian Mean Reversion -- XAU/USD M5 Backtest
Quantitative Trading Strategy

Strategi mean-reverting berbasis Z-Score pada sesi Asia
(00:00-06:00 UTC) dengan konfirmasi RSI & filter ATR.

Usage:
    python main.py                    # Jalankan dengan data sintetis
    python main.py --data path/to.csv # Jalankan dengan data kustom
    python main.py --no-chart         # Tanpa visualisasi
"""

import argparse
import os
import sys

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

import config as cfg
from engine.engine_asia.indicators import compute_all
from engine.engine_asia.backtester import Backtester
from utils.data_loader import load_csv, get_default_data_path
from visualization.visualization_asia.charts import plot_full_report, print_trade_log


def parse_args():
    parser = argparse.ArgumentParser(
        description="Asian Mean Reversion Backtester - XAU/USD M5"
    )
    parser.add_argument(
        "--data", type=str, default=None,
        help="Path ke file CSV data M5 (default: generate data sintetis)",
    )
    parser.add_argument(
        "--days", type=int, default=30,
        help="Jumlah hari data sintetis jika --data tidak diberikan (default: 30)",
    )
    parser.add_argument(
        "--no-chart", action="store_true",
        help="Jalankan tanpa menampilkan chart (hanya print statistik)",
    )
    parser.add_argument(
        "--save-chart", type=str, default=None,
        help="Path untuk menyimpan chart sebagai image file (PNG/JPG)",
    )
    parser.add_argument(
        "--export-trades", type=str, default=None,
        help="Path untuk export trade log ke CSV",
    )
    parser.add_argument(
        "--export-log", type=str, default=None,
        help="Path untuk export log eksekusi detil ke TXT",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    print()
    print("=" * 62)
    print("   ASIAN MEAN REVERSION -- XAU/USD M5 BACKTEST")
    print("=" * 62)
    print()

    # ── 1. LOAD DATA ──
    data_path = args.data if args.data else "data/xauusd-m5-bid-2026-02-08-2026-09-08.csv"
    print(f"[1/4] Loading data dari: {data_path}")
    df = load_csv(data_path)

    print(f"      Loaded {len(df)} bars")
    print(f"      Range: {df['datetime'].iloc[0]} — {df['datetime'].iloc[-1]}")
    print()

    # ── 2. HITUNG INDIKATOR ──
    print("[2/4] Menghitung indikator (SMA, Z-Score, RSI, ATR)...")
    df = compute_all(df)

    # Print konfigurasi aktif
    print(f"      Anchor       : {'VWAP' if cfg.USE_VWAP else f'SMA({cfg.ROLLING_WINDOW})'}")
    print(f"      Z-Entry      : ±{cfg.Z_ENTRY_THRESHOLD}")
    print(f"      Z-Exit       : [{-cfg.Z_EXIT_THRESHOLD}, {cfg.Z_EXIT_THRESHOLD}]")
    print(f"      Z-Hard Cut   : ±{cfg.Z_HARD_CUT}")
    rsi_desc = f"{cfg.RSI_PERIOD} (OB={cfg.RSI_OVERBOUGHT}, OS={cfg.RSI_OVERSOLD})" if getattr(cfg, "USE_RSI_FILTER", True) else "DISABLED (Bypassed)"
    print(f"      RSI Filter   : {rsi_desc}")
    print(f"      ATR Period   : {cfg.ATR_PERIOD} (SL multiplier={cfg.ATR_SL_MULTIPLIER}×)")
    print(f"      ATR Min Gate : ${cfg.ATR_MIN_THRESHOLD}")
    print(f"      ATR Max Gate : {cfg.ATR_ANOMALY_MULTIPLIER}× SMA(ATR,{cfg.ATR_SMA_PERIOD})")
    print(f"      Time Stop    : {cfg.MAX_TRADE_DURATION_MIN} min")
    pos_sizing_str = f"Dynamic (Fixed Risk ${cfg.FIXED_RISK_USD:,.2f})" if getattr(cfg, "USE_DYNAMIC_LOT", False) else f"Static ({cfg.LOT_SIZE} lot)"
    print(f"      Position Size: {pos_sizing_str}")
    htf_str = f"Active ({cfg.HTF_TIMEFRAME} EMA {cfg.HTF_EMA_PERIOD}, Mode: {cfg.HTF_FILTER_MODE})" if getattr(cfg, "USE_HTF_TREND_FILTER", False) else "DISABLED"
    print(f"      HTF Filter   : {htf_str}")
    print(f"      Session      : {cfg.SESSION_ENTRY_START}–{cfg.SESSION_HARD_CUTOFF} UTC (Entry stops at {cfg.SESSION_ENTRY_END})")
    print()

    # ── 3. JALANKAN BACKTEST ──
    print("[3/4] Menjalankan backtest...")
    bt = Backtester(df)
    stats = bt.run()

    # Print hasil
    print(stats)

    # Print trade log
    trade_log = bt.trade_log
    print_trade_log(trade_log)

    # Export trades jika diminta
    if args.export_trades:
        trade_log.to_csv(args.export_trades, index=False)
        print(f"[✓] Trade log disimpan ke: {args.export_trades}")
        
    if args.export_log:
        with open(args.export_log, "w", encoding="utf-8") as f:
            f.write("\n".join(bt.detailed_log_lines))
        print(f"[✓] Detailed log disimpan ke: {args.export_log}")

    # ── 4. VISUALISASI ──
    if not args.no_chart:
        print("[4/4] Generating chart...")
        try:
            plot_full_report(
                df=df,
                trades=bt.trades,
                stats=stats,
                equity_curve=bt.equity_curve,
                save_path=args.save_chart,
            )
        except Exception as e:
            print(f"[!] Error saat membuat chart: {e}")
            print("    Gunakan --no-chart untuk skip visualisasi.")
    else:
        print("[4/4] Chart dilewati (--no-chart)")

    print("\n[✓] Backtest selesai.\n")


if __name__ == "__main__":
    main()
