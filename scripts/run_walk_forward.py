"""
Quantitative Master Portfolio — Walk-Forward / Out-of-Sample Runner
===================================================================
CLI runner untuk mengeksekusi pengujian Walk-Forward / Out-of-Sample Blind Split
pada Master Portfolio XAU/USD (Tahun 1 Training vs Tahun 2 Blind Test).

Contoh Penggunaan:
    python scripts/run_walk_forward.py
    python scripts/run_walk_forward.py --save-chart output/walk_forward_dashboard.png
"""

import argparse
import os
import sys

# Atur encoding UTF-8 untuk Windows terminal
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Pastikan root workspace terdaftar di sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from analytics.walk_forward import (
    run_walk_forward_analysis,
    print_walk_forward_report,
    plot_walk_forward_dashboard,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Jalankan Uji Walk-Forward / Out-of-Sample Blind Split pada Master Portfolio XAU/USD"
    )
    parser.add_argument(
        "--data",
        type=str,
        default=os.path.join(ROOT_DIR, "data", "xauusd-m5-bid-2024-09-08-2026-09-08.csv"),
        help="Path dataset M5",
    )
    parser.add_argument(
        "--split-date",
        type=str,
        default="2025-09-08 00:00:00+00:00",
        help="Tanggal pemisah In-Sample dan Out-of-Sample (default: 2025-09-08)",
    )
    parser.add_argument(
        "--save-chart",
        type=str,
        default=os.path.join(ROOT_DIR, "output", "walk_forward_dashboard.png"),
        help="Path file output grafik",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    print("=" * 76)
    print("   QUANTITATIVE MASTER PORTFOLIO — WALK-FORWARD / OUT-OF-SAMPLE TEST")
    print("=" * 76)
    print(f"  Dataset        : {args.data}")
    print(f"  Split Date     : {args.split_date}")
    print(f"  Chart Output   : {args.save_chart}")
    print("=" * 76 + "\n")

    res = run_walk_forward_analysis(
        data_path=args.data,
        split_date_str=args.split_date,
    )
    print_walk_forward_report(res)

    if args.save_chart:
        plot_walk_forward_dashboard(res, save_path=args.save_chart)


if __name__ == "__main__":
    main()
