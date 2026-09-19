"""
Quantitative Master Portfolio — Friction & Slippage Runner
==========================================================
CLI runner untuk mengeksekusi pengujian Friction & Slippage Decay Curve
pada Master Portfolio XAU/USD ($0.00 s/d $3.00 USD/oz).

Contoh Penggunaan:
    python scripts/run_friction_decay.py
    python scripts/run_friction_decay.py --save-chart output/friction_decay_dashboard.png
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

from analytics.friction_decay import (
    run_friction_decay_sweep,
    print_friction_report,
    plot_friction_decay_dashboard,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Jalankan Uji Friction & Slippage Decay Curve pada Master Portfolio"
    )
    parser.add_argument(
        "--data",
        type=str,
        default=os.path.join(ROOT_DIR, "data", "xauusd-m5-bid-2024-09-08-2026-09-08.csv"),
        help="Path dataset M5",
    )
    parser.add_argument(
        "--save-chart",
        type=str,
        default=os.path.join(ROOT_DIR, "output", "friction_decay_dashboard.png"),
        help="Path file output grafik",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    res = run_friction_decay_sweep(data_path=args.data)
    print_friction_report(res)

    if args.save_chart:
        plot_friction_decay_dashboard(res, save_path=args.save_chart)


if __name__ == "__main__":
    main()
