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
    live-check      Uji komprehensif kesiapan sistem live trading (10 tahap diagnostik)
    telegram-test   Uji koneksi dan pengiriman notifikasi ke Telegram Bot
    monte-carlo     Jalankan simulasi stress test Monte Carlo
    walk-forward    Jalankan validasi Out-Of-Sample Walk-Forward
    friction-decay  Jalankan stress test ketahanan Friction & Slippage
    sensitivity     Jalankan analisis Robustness Plateau / Parameter Sensitivity Surface

Usage:
    python main.py                          # Menjalankan Master Portfolio (default)
    python main.py portfolio [args...]
    python main.py portfolio --tick         # Master Portfolio Level 3.0 Real Tick Replay (Ask/Bid Exact)
    python main.py asia [args...]
    python main.py london [args...]
    python main.py ny [args...]
    python main.py live [--check-only]
    python main.py live-check
    python main.py telegram-test
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
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run_portfolio(args):
    """Eksekusi Master Portfolio multi-sesi."""
    from src.strategies.portfolio import config as pcfg
    from src.strategies.ny_orb import config as ny_cfg
    from src.data.loader import load_csv
    from src.data.mtf_loader import load_mtf_dataset
    from src.strategies.portfolio.engine import PortfolioEngine
    from research.visualization.portfolio_charts import (
        plot_portfolio_dashboard,
        print_portfolio_trade_log,
        print_monthly_attribution_table,
    )

    data_m5_path = args.data or getattr(pcfg, "DEFAULT_DATA_M5", "data/xauusd-m5-bid-2021-09-08-2026-09-08.csv")
    data_m1_path = args.data_m1 or getattr(pcfg, "DEFAULT_DATA_M1", "data/xauusd-m1-bid-2021-09-08-2026-09-08.csv")

    # ── TICK REPLAY MODE (LEVEL 3.0 FIDELITY) ──
    if getattr(args, "tick", False):
        from src.data.tick_loader import load_tick_csv
        from src.strategies.portfolio.tick_engine import TickPortfolioEngine

        tick_path = getattr(args, "data_tick", "data/xauusd-tick-2026-08-08-2026-09-08.csv")
        initial_cap = getattr(args, "balance", pcfg.PORTFOLIO_INITIAL_CAPITAL)

        print()
        print("=" * 68)
        print("   QUANTITATIVE MASTER PORTFOLIO — XAU/USD (TICK REPLAY LEVEL 3.0)")
        print("   [Execution: Real Tick Replay (Ask/Bid Exact) | Dynamic Spreads & Slippage]")
        print("=" * 68)
        print()

        # 1. Load Data
        print(f"[1/4] Loading Tick dataset dari: {tick_path}...")
        tick_dataset = load_tick_csv(tick_path)
        print(f"      Loaded {len(tick_dataset):,} ticks ({len(tick_dataset.unique_dates)} hari aktif)")
        print(f"      Rentang Tick: {tick_dataset.start_dt} — {tick_dataset.end_dt}")

        print(f"      Loading companion M5 data untuk ORB box locking: {data_m5_path}...")
        df_m5 = load_csv(data_m5_path)
        print(f"      Loaded {len(df_m5):,} M5 bars")

        # Konfigurasi Master Portofolio
        print()
        print("      --- KONFIGURASI MASTER PORTOFOLIO (TICK LEVEL 3.0) ---")
        print(f"      Modal Awal          : ${initial_cap:,.2f} USD")
        print(f"      Modul 1 (Asia MR)   : {pcfg.ASIAN_ENTRY_WINDOW} (Risk: {pcfg.ASIAN_RISK_PCT*100:.1f}%)")
        if getattr(pcfg, "ENABLE_LONDON_ORB", False):
            print(f"      Modul 2 (London ORB): {pcfg.LONDON_ENTRY_WINDOW} (Risk: {pcfg.LONDON_RISK_PCT*100:.1f}%)")
        if pcfg.ENABLE_STRATEGY_2:
            print(f"      Modul 3 (NY ORB)    : {pcfg.NY_ENTRY_WINDOW} (Risk: {pcfg.NY_RISK_PCT*100:.1f}%)")
        print(f"      Spread Filter Max   : $0.60 (Strict Execution Guard)")
        print(f"      Anti-Chase Slippage : London $1.69 / NY $2.84")
        print(f"      Execution Fills     : BUY @ Ask, SELL @ Bid (Real Spread Cost)")
        print()

        # 2. Run Portfolio Engine
        print("[2/4] Mengeksekusi modul kuantitatif pada 5+ Juta Tick...")
        engine = TickPortfolioEngine(tick_dataset=tick_dataset, df_m5=df_m5, initial_capital=initial_cap)
        stats = engine.run()

        # 3. Compile & Export Report
        print("[3/4] Mengompilasi performa portofolio & tabel atribusi...")
        print(stats)
        print_monthly_attribution_table(stats.monthly_pnl_df)
        trade_log = engine.trade_log
        print_portfolio_trade_log(trade_log)

        export_trades = args.export_trades
        if export_trades == "output/portfolio_trades.csv":
            export_trades = "output/portfolio_trades_tick.csv"
        if export_trades:
            os.makedirs(os.path.dirname(os.path.abspath(export_trades)), exist_ok=True)
            trade_log.to_csv(export_trades, index=False)
            print(f"[✓] Master tick trade log disimpan ke: {export_trades}")

        export_log = args.export_log
        if export_log == "output/portfolio_log.txt":
            export_log = "output/portfolio_log_tick.txt"
        if export_log:
            os.makedirs(os.path.dirname(os.path.abspath(export_log)), exist_ok=True)
            with open(export_log, "w", encoding="utf-8") as f:
                f.write(str(stats))
                f.write("\n\n")
                f.write("MONTHLY ATTRIBUTION:\n")
                f.write(stats.monthly_pnl_df.to_string())
            print(f"[✓] Laporan teks disimpan ke: {export_log}")

        # 4. Chart Visualization
        if not args.no_chart:
            save_chart = args.save_chart
            if save_chart == "output/portfolio_chart.png":
                save_chart = "output/portfolio_chart_tick.png"
            print(f"[4/4] Me-render visual dashboard portofolio tick ke {save_chart}...")
            try:
                start_ts = tick_dataset.start_dt
                end_ts = tick_dataset.end_dt
                df_m5_slice = df_m5[(df_m5["datetime"] >= start_ts) & (df_m5["datetime"] <= end_ts)].copy()
                if len(df_m5_slice) < 50:
                    df_m5_slice = df_m5.tail(1000).copy()

                plot_portfolio_dashboard(
                    df_raw=df_m5_slice,
                    trades=engine.trades,
                    stats=stats,
                    equity_dates=engine.equity_dates,
                    equity_curve=engine.equity_curve,
                    asian_equity=engine.asian_equity,
                    london_equity=engine.london_equity,
                    ny_equity=engine.ny_equity,
                    save_path=save_chart,
                )
                print(f"[✓] Visual dashboard tersimpan ke: {save_chart}")
            except Exception as e:
                print(f"[!] Gagal me-render visual dashboard: {e}")
        else:
            print("[4/4] Visualisasi dilewati (--no-chart)")

        print("\n[✓] Simulasi Quantitative Master Portfolio Tick Replay Level 3.0 selesai sukses!\n")
        return

    print()
    print("=" * 68)
    print("   QUANTITATIVE MASTER PORTFOLIO — XAU/USD")
    use_m1 = not args.no_m1 and os.path.exists(data_m1_path)
    exec_mode = "M1 Bar Magnifier (1-Min Precision)" if use_m1 else "M5 Native Engine"
    mtf_mode = "M5 + H1 MTF" if args.use_mtf else "M5 Native"
    print(f"   [{mtf_mode} | Execution: {exec_mode}]")
    print("=" * 68)
    print()

    # 1. Load Data
    if args.use_mtf:
        ny_cfg.USE_HTF_TREND_FILTER = True
        print("[1/4] Loading Multi-Timeframe data (M5, H1, H4, M15)...")
        df_m5, htf_dfs = load_mtf_dataset(
            m5_path=data_m5_path,
            h1_path=getattr(args, "data_h1", "data/xauusd-h1-bid-2021-09-08-2026-09-08.csv"),
            h4_path=getattr(args, "data_h4", "data/xauusd-h4-bid-2021-09-08-2026-09-08.csv"),
            m15_path=getattr(args, "data_m15", "data/xauusd-m15-bid-2021-09-08-2026-09-08.csv")
        )
        print(f"      Loaded {len(df_m5):,} M5 execution bars dengan fitur HTF terpadu")
    else:
        ny_cfg.USE_HTF_TREND_FILTER = False
        print(f"[1/4] Loading native M5 data dari: {data_m5_path}")
        df_m5 = load_csv(data_m5_path)
        print(f"      Loaded {len(df_m5):,} raw M5 execution bars (M5 Murni)")
    print(f"      Rentang M5: {df_m5['datetime'].iloc[0]} — {df_m5['datetime'].iloc[-1]}")

    df_m1 = None
    if use_m1:
        print(f"      Loading M1 Bar Magnifier data dari: {data_m1_path}")
        df_m1 = load_csv(data_m1_path)
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

    # 2. Run Portfolio Engine
    print("[2/4] Mengeksekusi modul kuantitatif dengan asymmetric compounding...")
    engine = PortfolioEngine(df_m5, df_m1=df_m1)
    stats = engine.run()

    # 3. Compile & Export Report
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

    # 4. Chart Visualization
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
            print(f"[✓] Visual dashboard tersimpan ke: {args.save_chart}")
        except Exception as e:
            print(f"[!] Gagal me-render visual dashboard: {e}")
    else:
        print("[4/4] Visualisasi dilewati (--no-chart)")
    print("\n[✓] Simulasi Quantitative Master Portfolio selesai sukses!\n")


def run_asia(args):
    """Eksekusi Standalone Asian Mean Reversion."""
    import src.strategies.asian_mr.config as cfg
    from src.strategies.asian_mr.signals import compute_asian_indicators
    from src.strategies.asian_mr.backtester import Backtester
    from src.data.loader import load_csv, get_default_data_path
    from research.visualization.asia_charts import plot_full_report, print_trade_log

    print()
    print("=" * 62)
    print("   ASIAN MEAN REVERSION -- XAU/USD M5 BACKTEST")
    print("=" * 62)
    print()

    data_path = args.data or get_default_data_path()
    print(f"[1/4] Loading data dari: {data_path}")
    df = load_csv(data_path)
    print(f"      Loaded {len(df):,} bars")
    print(f"      Range: {df['datetime'].iloc[0]} — {df['datetime'].iloc[-1]}\n")

    print("[2/4] Menghitung indikator (SMA, Z-Score, RSI, ATR)...")
    df = compute_asian_indicators(df)

    print("[3/4] Menjalankan backtest...")
    bt = Backtester(df)
    stats = bt.run()
    print(stats)
    trade_log = bt.trade_log
    print_trade_log(trade_log)

    if args.export_trades:
        os.makedirs(os.path.dirname(os.path.abspath(args.export_trades)), exist_ok=True)
        trade_log.to_csv(args.export_trades, index=False)
        print(f"[✓] Trade log disimpan ke: {args.export_trades}")

    if not args.no_chart and args.save_chart:
        print("[4/4] Generating visual report...")
        plot_full_report(df, bt.trades, stats, save_path=args.save_chart)
    else:
        print("[4/4] Chart dilewati (--no-chart)")
    print("\n[✓] Backtest selesai.\n")


def run_london(args):
    """Eksekusi Standalone London Pit ORB."""
    import src.strategies.london_orb.config as cfg
    from src.data.loader import load_csv, get_default_data_path
    from src.strategies.london_orb.signals import compute_london_indicators
    from src.strategies.london_orb.backtester import LondonBacktester

    data_path = args.data or get_default_data_path()
    use_m1 = not args.no_m1 and os.path.exists(args.data_m1)
    exec_mode = "M1 Bar Magnifier (1-Min Precision)" if use_m1 else "M5 Native Engine"

    print()
    print("=" * 64)
    print("   LONDON PIT OPENING RANGE BREAKOUT (LONDON ORB) — XAU/USD")
    print(f"   [Execution Mode: {exec_mode}]")
    print("=" * 64)

    print(f"[*] Loading data M5: {data_path}")
    df_m5 = load_csv(data_path)
    print(f"[✓] Data M5 berhasil dimuat: {len(df_m5):,} bar")

    df_m1 = None
    if use_m1:
        print(f"[*] Loading data M1 Bar Magnifier: {args.data_m1}")
        df_m1 = load_csv(args.data_m1)
        print(f"[✓] Data M1 berhasil dimuat: {len(df_m1):,} sub-bars")

    print("[*] Menghitung indikator teknikal & Opening Range M15 (08:00 - 08:15 UTC)...")
    df_m5 = compute_london_indicators(df_m5)

    print(f"[*] Menjalankan simulasi London Pit ORB ({exec_mode})...")
    bt = LondonBacktester(df_m5, df_m1=df_m1)
    stats = bt.run()
    print(stats)

    if args.export_trades:
        os.makedirs(os.path.dirname(os.path.abspath(args.export_trades)), exist_ok=True)
        bt.trade_log.to_csv(args.export_trades, index=False)
        print(f"[✓] Trade log diekspor ke: {args.export_trades} ({len(bt.trade_log)} baris)")
    print("[✓] Eksekusi London Pit ORB selesai.\n")


def run_ny(args):
    """Eksekusi Standalone New York ORB."""
    import src.strategies.ny_orb.config as cfg
    from src.data.loader import load_csv, get_default_data_path
    from src.strategies.ny_orb.signals import compute_ny_indicators
    from src.strategies.ny_orb.backtester import NYBacktester
    from research.visualization.ny_charts import plot_ny_dashboard

    data_path = args.data or get_default_data_path()
    use_m1 = not args.no_m1 and os.path.exists(args.data_m1)
    exec_mode = "M1 Bar Magnifier (1-Min Precision)" if use_m1 else "M5 Native Engine"

    print()
    print("=" * 64)
    print("   NEW YORK OPENING RANGE BREAKOUT (NY ORB) — XAU/USD")
    print(f"   [Execution Mode: {exec_mode}]")
    print("=" * 64)

    print(f"[*] Loading data M5: {data_path}")
    df_m5 = load_csv(data_path)
    print(f"[✓] Data M5 berhasil dimuat: {len(df_m5):,} bar")

    df_m1 = None
    if use_m1:
        print(f"[*] Loading data M1 Bar Magnifier: {args.data_m1}")
        df_m1 = load_csv(args.data_m1)
        print(f"[✓] Data M1 berhasil dimuat: {len(df_m1):,} sub-bars")

    print("[*] Menghitung indikator teknikal & Opening Range M15 (13:30 - 13:45 UTC)...")
    df_m5 = compute_ny_indicators(df_m5)

    print(f"[*] Menjalankan simulasi New York ORB ({exec_mode})...")
    bt = NYBacktester(df_m5, df_m1=df_m1)
    stats = bt.run()
    print(stats)

    if args.export_trades:
        os.makedirs(os.path.dirname(os.path.abspath(args.export_trades)), exist_ok=True)
        bt.trade_log.to_csv(args.export_trades, index=False)
        print(f"[✓] Trade log diekspor ke: {args.export_trades} ({len(bt.trade_log)} baris)")

    if not args.no_chart and args.save_chart:
        os.makedirs(os.path.dirname(os.path.abspath(args.save_chart)), exist_ok=True)
        plot_ny_dashboard(df_m5, bt.trades, stats, save_path=args.save_chart)
    print("[✓] Eksekusi New York ORB selesai.\n")


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
    parser_portfolio.add_argument("--data-h1", type=str, default="data/xauusd-h1-bid-2021-09-08-2026-09-08.csv", help="Path data H1 CSV")
    parser_portfolio.add_argument("--data-h4", type=str, default="data/xauusd-h4-bid-2021-09-08-2026-09-08.csv", help="Path data H4 CSV")
    parser_portfolio.add_argument("--data-m15", type=str, default="data/xauusd-m15-bid-2021-09-08-2026-09-08.csv", help="Path data M15 CSV")
    parser_portfolio.add_argument("--use-mtf", action="store_true", help="Aktifkan HTF trend filter")
    parser_portfolio.add_argument("--no-m1", action="store_true", help="Nonaktifkan M1 Bar Magnifier")
    parser_portfolio.add_argument("--no-chart", action="store_true", help="Nonaktifkan render chart")
    parser_portfolio.add_argument("--save-chart", type=str, default="output/portfolio_chart.png", help="Path output chart")
    parser_portfolio.add_argument("--export-trades", type=str, default="output/portfolio_trades.csv", help="Path output trade log")
    parser_portfolio.add_argument("--export-log", type=str, default="output/portfolio_log.txt", help="Path output text report")
    parser_portfolio.add_argument("--tick", action="store_true", help="Aktifkan Level 3.0 Real Tick-by-Tick Replay Engine")
    parser_portfolio.add_argument("--data-tick", type=str, default="data/xauusd-tick-2026-08-08-2026-09-08.csv", help="Path data Tick CSV")
    parser_portfolio.add_argument("--balance", type=float, default=10000.0, help="Modal awal portofolio")

    # ── 2. ASIA ──
    parser_asia = subparsers.add_parser("asia", help="Jalankan Standalone Asian Mean Reversion")
    parser_asia.add_argument("--data", type=str, default=None, help="Path data M5 CSV")
    parser_asia.add_argument("--no-chart", action="store_true", help="Nonaktifkan render chart")
    parser_asia.add_argument("--save-chart", type=str, default=None, help="Path output chart")
    parser_asia.add_argument("--export-trades", type=str, default=None, help="Path output trade log")

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

    # ── 10. LIVE CHECK ──
    parser_live_check = subparsers.add_parser("live-check", help="Jalankan uji kesiapan & diagnostik menyeluruh sistem live (10 tahap)")

    # ── 11. TELEGRAM TEST ──
    parser_tg = subparsers.add_parser("telegram-test", help="Uji koneksi dan pengiriman notifikasi ke Telegram Bot")

    # Default to portfolio if no args provided
    if len(sys.argv) == 1:
        sys.argv.append("portfolio")

    args = parser.parse_args()

    if args.command == "portfolio" or args.command is None:
        run_portfolio(args)

    elif args.command == "asia":
        run_asia(args)

    elif args.command == "london":
        run_london(args)

    elif args.command == "ny":
        run_ny(args)

    elif args.command == "live":
        if args.check_only:
            from src.execution.diagnostics import run_connection_test
            run_connection_test()
        else:
            from src.execution.runner import LivePortfolioTrader
            runner = LivePortfolioTrader()
            runner.start()

    elif args.command == "live-check":
        from src.execution.system_check import main as live_check_main
        sys.exit(live_check_main())

    elif args.command == "telegram-test":
        from src.execution.notifications import test_telegram_connection
        success = test_telegram_connection()
        sys.exit(0 if success else 1)

    elif args.command == "monte-carlo":
        from research.analytics.monte_carlo import main as mc_main
        sys.argv = [sys.argv[0]] + [arg for arg in sys.argv[1:] if arg != "monte-carlo"]
        mc_main()

    elif args.command == "walk-forward":
        from research.analytics.walk_forward import main as wf_main
        sys.argv = [sys.argv[0]] + [arg for arg in sys.argv[1:] if arg != "walk-forward"]
        wf_main()

    elif args.command == "friction-decay":
        from research.analytics.friction_decay import main as fd_main
        sys.argv = [sys.argv[0]] + [arg for arg in sys.argv[1:] if arg != "friction-decay"]
        fd_main()

    elif args.command == "sensitivity":
        from research.analytics.parameter_sensitivity import main as ps_main
        sys.argv = [sys.argv[0]] + [arg for arg in sys.argv[1:] if arg != "sensitivity"]
        ps_main()


if __name__ == "__main__":
    main()
