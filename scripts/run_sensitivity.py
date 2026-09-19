"""
Quantitative Master Portfolio — Parameter Sensitivity Runner
============================================================
CLI runner untuk mengeksekusi pengujian Parameter Sensitivity Surface & Robustness Plateau
pada Master Portfolio XAU/USD (5 Z-Score Asia x 7 Expansion Multiplier NY = 35 Matriks).

Contoh Penggunaan:
    python scripts/run_sensitivity.py
    python scripts/run_sensitivity.py --save-chart output/sensitivity_surface_dashboard.png
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

from analytics.parameter_sensitivity import (
    run_parameter_sensitivity_grid,
    print_sensitivity_report,
    plot_parameter_sensitivity_dashboard,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Jalankan Uji Parameter Sensitivity Surface & Robustness Plateau pada Master Portfolio"
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
        default=os.path.join(ROOT_DIR, "output", "sensitivity_surface_dashboard.png"),
        help="Path file output grafik",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    res = run_parameter_sensitivity_grid(data_path=args.data)
    print_sensitivity_report(res)

    if args.save_chart:
        plot_parameter_sensitivity_dashboard(res, save_path=args.save_chart)


if __name__ == "__main__":
    main()
