"""
Quantitative Trading System — Unified Master CLI
=================================================
Institutional-grade quantitative algorithmic trading framework for XAU/USD.

Subcommands:
    portfolio       Eksekusi Master Portfolio (Asian MR + London ORB + NY ORB)
    asia            Eksekusi standalone Asian Mean Reversion
    london          Eksekusi standalone London Pit ORB
    ny              Eksekusi standalone New York ORB
    live            Uji koneksi atau jalankan MT5 Live Execution Runner
    monte-carlo     Jalankan simulasi stress test Monte Carlo
    walk-forward    Jalankan validasi Out-Of-Sample Walk-Forward
    friction-decay  Jalankan stress test ketahanan Friction & Slippage
    sensitivity     Jalankan analisis Robustness Plateau / Parameter Sensitivity Surface

Usage:
    python main.py                          # Menjalankan Master Portfolio (default)
    python main.py portfolio [args...]
    python main.py asia [args...]
    python main.py london [args...]
    python main.py ny [args...]
    python main.py live [--check-only]
    python main.py monte-carlo [-n 1000]
    python main.py walk-forward
    python main.py friction-decay
    python main.py sensitivity
"""

import os
import sys
import argparse

# Windows UTF-8 encoding fix
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(
        description="Institutional Quantitative Trading System - XAU/USD Multi-Session Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Pilihan modul/perintah untuk dijalankan")

    # ── 1. PORTFOLIO ──
    parser_portfolio = subparsers.add_parser("portfolio", help="Jalankan Master Portfolio Multi-Sesi")
    parser_portfolio.add_argument("--data", type=str, default=None, help="Path data M5 CSV")
    parser_portfolio.add_argument("--data-m1", type=str, default="data/xauusd-m1-bid-2021-09-08-2026-09-08.csv", help="Path data M1 CSV")
    parser_portfolio.add_argument("--use-mtf", action="store_true", help="Aktifkan HTF trend filter")
    parser_portfolio.add_argument("--no-m1", action="store_true", help="Nonaktifkan M1 Bar Magnifier")
    parser_portfolio.add_argument("--no-chart", action="store_true", help="Nonaktifkan render chart")
    parser_portfolio.add_argument("--save-chart", type=str, default="output/portfolio_chart.png", help="Path output chart")
    parser_portfolio.add_argument("--export-trades", type=str, default="output/portfolio_trades.csv", help="Path output trade log")
    parser_portfolio.add_argument("--export-log", type=str, default="output/portfolio_log.txt", help="Path output text report")

    # ── 2. ASIA ──
    parser_asia = subparsers.add_parser("asia", help="Jalankan Standalone Asian Mean Reversion")
    parser_asia.add_argument("--data", type=str, default=None, help="Path data M5 CSV")
    parser_asia.add_argument("--no-chart", action="store_true", help="Nonaktifkan render chart")
    parser_asia.add_argument("--save-chart", type=str, default=None, help="Path output chart")
    parser_asia.add_argument("--export-trades", type=str, default=None, help="Path output trade log")
    parser_asia.add_argument("--export-log", type=str, default=None, help="Path output text report")

    # ── 3. LONDON ──
    parser_london = subparsers.add_parser("london", help="Jalankan Standalone London Pit ORB")
    parser_london.add_argument("--data", type=str, default=None, help="Path data M5 CSV")
    parser_london.add_argument("--data-m1", type=str, default="data/xauusd-m1-bid-2021-09-08-2026-09-08.csv", help="Path data M1 CSV")
    parser_london.add_argument("--no-m1", action="store_true", help="Nonaktifkan M1 Bar Magnifier")
    parser_london.add_argument("--no-chart", action="store_true", help="Nonaktifkan render chart")
    parser_london.add_argument("--save-chart", type=str, default="output/london_chart.png", help="Path output chart")
    parser_london.add_argument("--export-trades", type=str, default="output/london_trades.csv", help="Path output trade log")

    # ── 4. NY ──
    parser_ny = subparsers.add_parser("ny", help="Jalankan Standalone New York ORB")
    parser_ny.add_argument("--data", type=str, default=None, help="Path data M5 CSV")
    parser_ny.add_argument("--data-m1", type=str, default="data/xauusd-m1-bid-2021-09-08-2026-09-08.csv", help="Path data M1 CSV")
    parser_ny.add_argument("--no-m1", action="store_true", help="Nonaktifkan M1 Bar Magnifier")
    parser_ny.add_argument("--no-chart", action="store_true", help="Nonaktifkan render chart")
    parser_ny.add_argument("--save-chart", type=str, default="output/ny_chart.png", help="Path output chart")
    parser_ny.add_argument("--export-trades", type=str, default="output/ny_trades.csv", help="Path output trade log")

    # ── 5. LIVE ──
    parser_live = subparsers.add_parser("live", help="Live MT5 Connector / Runner")
    parser_live.add_argument("--check-only", action="store_true", help="Hanya jalankan connection health check tanpa trading")

    # ── 6. MONTE CARLO ──
    parser_mc = subparsers.add_parser("monte-carlo", help="Jalankan simulasi Monte Carlo 1,000 runs")
    parser_mc.add_argument("-n", "--iterations", type=int, default=1000, help="Jumlah iterasi")
    parser_mc.add_argument("-m", "--mode", choices=["reshuffle", "bootstrap"], default="reshuffle", help="Metode simulasi")
    parser_mc.add_argument("--data", type=str, default="data/xauusd-m5-bid-2021-09-08-2026-09-08.csv", help="Path data CSV")
    parser_mc.add_argument("--save-chart", type=str, default="output/monte_carlo_dashboard.png", help="Path output chart")

    # ── 7. WALK FORWARD ──
    parser_wf = subparsers.add_parser("walk-forward", help="Jalankan validasi Walk-Forward Out-Of-Sample")
    parser_wf.add_argument("--data", type=str, default="data/xauusd-m5-bid-2024-09-08-2026-09-08.csv", help="Path data CSV")
    parser_wf.add_argument("--split-date", type=str, default="2025-09-08 00:00:00+00:00", help="Tanggal split")
    parser_wf.add_argument("--save-chart", type=str, default="output/walk_forward_dashboard.png", help="Path output chart")

    # ── 8. FRICTION DECAY ──
    parser_fd = subparsers.add_parser("friction-decay", help="Jalankan uji ketahanan Friction & Slippage")
    parser_fd.add_argument("--data", type=str, default="data/xauusd-m5-bid-2024-09-08-2026-09-08.csv", help="Path data CSV")
    parser_fd.add_argument("--save-chart", type=str, default="output/friction_decay_dashboard.png", help="Path output chart")

    # ── 9. PARAMETER SENSITIVITY ──
    parser_ps = subparsers.add_parser("sensitivity", help="Jalankan uji Parameter Sensitivity Surface 5x7")
    parser_ps.add_argument("--data", type=str, default="data/xauusd-m5-bid-2024-09-08-2026-09-08.csv", help="Path data CSV")
    parser_ps.add_argument("--save-chart", type=str, default="output/sensitivity_surface_dashboard.png", help="Path output chart")

    # Jika dipanggil tanpa argumen sama sekali, default ke master portfolio
    if len(sys.argv) == 1:
        sys.argv.append("portfolio")

    args = parser.parse_args()

    if args.command == "portfolio" or args.command is None:
        import main_portfolio
        sys.argv = [sys.argv[0]] + [arg for arg in sys.argv[1:] if arg != "portfolio"]
        main_portfolio.main()

    elif args.command == "asia":
        import main_asia
        sys.argv = [sys.argv[0]] + [arg for arg in sys.argv[1:] if arg != "asia"]
        main_asia.main()

    elif args.command == "london":
        import main_london
        sys.argv = [sys.argv[0]] + [arg for arg in sys.argv[1:] if arg != "london"]
        main_london.main()

    elif args.command == "ny":
        import main_ny
        sys.argv = [sys.argv[0]] + [arg for arg in sys.argv[1:] if arg != "ny"]
        main_ny.main()

    elif args.command == "live":
        if args.check_only:
            from live.test_connection import main as live_test
            live_test()
        else:
            from live.live_runner import LivePortfolioTrader
            runner = LivePortfolioTrader()
            runner.start()

    elif args.command == "monte-carlo":
        from scripts.run_monte_carlo import main as mc_main
        sys.argv = [sys.argv[0]] + [arg for arg in sys.argv[1:] if arg != "monte-carlo"]
        mc_main()

    elif args.command == "walk-forward":
        from scripts.run_walk_forward import main as wf_main
        sys.argv = [sys.argv[0]] + [arg for arg in sys.argv[1:] if arg != "walk-forward"]
        wf_main()

    elif args.command == "friction-decay":
        from scripts.run_friction_decay import main as fd_main
        sys.argv = [sys.argv[0]] + [arg for arg in sys.argv[1:] if arg != "friction-decay"]
        fd_main()

    elif args.command == "sensitivity":
        from scripts.run_sensitivity import main as ps_main
        sys.argv = [sys.argv[0]] + [arg for arg in sys.argv[1:] if arg != "sensitivity"]
        ps_main()


if __name__ == "__main__":
    main()
