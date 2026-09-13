"""
Quantitative Master Portfolio — Monte Carlo Main Runner
========================================================
CLI runner untuk mengeksekusi simulasi Monte Carlo 1,000 permutasi
dan bootstrap resampling pada Master Portfolio XAU/USD multi-sesi.

Contoh Penggunaan:
    python testing/main_monte_carlo.py
    python testing/main_monte_carlo.py --iterations 1000 --mode reshuffle
    python testing/main_monte_carlo.py --iterations 1000 --mode bootstrap
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

from engine.engine_portfolio.monte_carlo import (
    run_monte_carlo,
    print_monte_carlo_report,
    plot_monte_carlo_dashboard,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Jalankan Simulasi Monte Carlo pada Master Portfolio Kuantitatif XAU/USD"
    )
    parser.add_argument(
        "--iterations", "-n",
        type=int,
        default=1000,
        help="Jumlah iterasi simulasi (default: 1000)",
    )
    parser.add_argument(
        "--mode", "-m",
        type=str,
        choices=["reshuffle", "bootstrap"],
        default="reshuffle",
        help="Metode simulasi: 'reshuffle' (trade permutation) atau 'bootstrap' (sampling with replacement)",
    )
    parser.add_argument(
        "--data",
        type=str,
        default=os.path.join(ROOT_DIR, "data", "xauusd-m5-bid-2021-09-08-2026-09-08.csv"),
        help="Path dataset M5",
    )
    parser.add_argument(
        "--save-chart",
        type=str,
        default=os.path.join(ROOT_DIR, "output", "monte_carlo_dashboard.png"),
        help="Path file output grafik",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    print("=" * 70)
    print("   QUANTITATIVE MASTER PORTFOLIO — MONTE CARLO STRESS TEST")
    print("=" * 70)
    print(f"  Dataset        : {args.data}")
    print(f"  Iterasi        : {args.iterations:,}")
    print(f"  Metode         : {args.mode.upper()}")
    print(f"  Chart Output   : {args.save_chart}")
    print("=" * 70 + "\n")

    res = run_monte_carlo(n_iterations=args.iterations, mode=args.mode, data_path=args.data)
    print_monte_carlo_report(res)

    if args.save_chart:
        plot_monte_carlo_dashboard(res, save_path=args.save_chart)


if __name__ == "__main__":
    main()
