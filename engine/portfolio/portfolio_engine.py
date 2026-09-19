"""
Master Multi-Regime Portfolio — Execution Engine
================================================
Mesin orkestrator terpadu portofolio kuantitatif:
1. Asian Mean Reversion (M5) — 01:00 to 04:30 UTC
2. London Pit Opening Range Breakout (M5) — 08:15 to 11:30 UTC
3. New York Opening Range Breakout (M5) — 13:45 to 16:30 UTC

Menyatukan eksekusi trade secara kronologis pada akun modal $10,000,
mengimplementasikan alokasi risiko asimetris, dynamic compounding,
de-risking cooldown, dan metrik atribusi bulanan.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd

from configs import portfolio_config as pcfg
from configs import asia_config as acfg
from configs import ny_config as ny_cfg
from configs import london_config as london_cfg

# Modul Asian Mean Reversion
from engine.asia.indicators import compute_all as compute_asian_indicators
from engine.asia.backtester import Backtester as AsianBacktester, BacktestStats as AsianStats

# Modul New York ORB
from engine.ny.strategy import compute_ny_indicators
from engine.ny.engine import NYBacktester, NYStats

# Modul London Pit ORB
from engine.london.strategy import compute_london_indicators
from engine.london.engine import LondonBacktester, LondonStats


@dataclass
class PortfolioTradeRecord:
    """Struktur data standar trade gabungan portofolio."""
    strategy: str                     # "ASIAN_MR", "LONDON_ORB", atau "NY_ORB"
    entry_datetime: pd.Timestamp
    exit_datetime: pd.Timestamp
    direction: str                    # "LONG" / "BUY" / "SHORT" / "SELL"
    lot_size: float
    entry_price: float
    exit_price: float
    pnl_usd: float
    pnl_points: float
    exit_reason: str
    duration_minutes: float
    mfe_usd: float = 0.0
    mae_usd: float = 0.0


@dataclass
class PortfolioStats:
    """Statistik komprehensif master portofolio gabungan."""
    initial_capital: float = pcfg.PORTFOLIO_INITIAL_CAPITAL
    ending_capital: float = 0.0
    total_net_pnl_usd: float = 0.0
    roi_pct: float = 0.0

    # Trade counts & win rate
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0

    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_usd: float = 0.0
    max_drawdown_pct: float = 0.0

    avg_pnl_usd: float = 0.0
    avg_win_usd: float = 0.0
    avg_loss_usd: float = 0.0
    best_trade_usd: float = 0.0
    worst_trade_usd: float = 0.0

    # ────────────────────────────────────────────────────────
    # INSTITUTIONAL METRICS (Formula Sheet pyquantnews.com)
    # ────────────────────────────────────────────────────────
    daily_sharpe_ratio: float = 0.0
    expectancy_usd: float = 0.0
    expectancy_ratio: float = 0.0

    var_95_pct: float = 0.0
    var_99_pct: float = 0.0
    var_95_usd: float = 0.0
    var_99_usd: float = 0.0

    mean_mae_usd: float = 0.0
    max_mae_usd: float = 0.0
    mean_mfe_usd: float = 0.0
    max_mfe_usd: float = 0.0

    cvar_95_pct: float = 0.0
    cvar_99_pct: float = 0.0
    cvar_95_usd: float = 0.0
    cvar_99_usd: float = 0.0

    avg_drawdown_pct: float = 0.0
    sortino_ratio: float = 0.0
    cagr_pct: float = 0.0
    calmar_ratio: float = 0.0

    # Breakdown Modul 1: Asian Mean Reversion
    asian_trades: int = 0
    asian_wins: int = 0
    asian_pnl_usd: float = 0.0
    asian_win_rate: float = 0.0
    asian_pf: float = 0.0

    # Breakdown Modul 2: London Pit ORB
    london_trades: int = 0
    london_wins: int = 0
    london_pnl_usd: float = 0.0
    london_win_rate: float = 0.0
    london_pf: float = 0.0

    # Breakdown Modul 3: New York ORB
    ny_trades: int = 0
    ny_wins: int = 0
    ny_pnl_usd: float = 0.0
    ny_win_rate: float = 0.0
    ny_pf: float = 0.0

    # Monthly breakdown table
    monthly_pnl_df: pd.DataFrame = field(default_factory=pd.DataFrame)

    def __str__(self) -> str:
        sep = "=" * 68
        subsep = "-" * 68
        a_risk = getattr(pcfg, "ASIAN_RISK_PCT", 0.01) * 100
        l_risk = getattr(pcfg, "LONDON_RISK_PCT", 0.02) * 100
        ny_risk = getattr(pcfg, "NY_RISK_PCT", 0.02) * 100
        pos_sizing_str = f"Asymmetric Compounding (Asia: {a_risk:.1f}% | London: {l_risk:.1f}% | NY: {ny_risk:.1f}%)" if pcfg.USE_COMPOUNDING else "Fixed Dollar Risk"
        risk_ctrl_str = f"Dynamic De-Risking={'ON (50% Cooldown)' if getattr(pcfg, 'ENABLE_DYNAMIC_DERISKING', False) else 'OFF'}"

        w_ratio = self.winning_trades / max(1, self.total_trades)
        l_ratio = self.losing_trades / max(1, self.total_trades)

        res = (
            f"\n{sep}\n"
            f"   QUANTITATIVE MASTER PORTFOLIO — PERFORMANCE REPORT\n"
            f"{sep}\n"
            f"  Initial Capital     : ${self.initial_capital:,.2f}\n"
            f"  Ending Capital      : ${self.ending_capital:,.2f}\n"
            f"  Total Net PnL       : ${self.total_net_pnl_usd:+,.2f} (+{self.roi_pct:.2f}%)\n"
            f"  Profit Factor       : {self.profit_factor:.2f}\n"
            f"  CAGR (Ann. Growth)  : +{self.cagr_pct:.2f}%\n"
            f"  Position Sizing     : {pos_sizing_str}\n"
            f"  Risk Control        : {risk_ctrl_str}\n"
            f"{subsep}\n"
            f"  INSTITUTIONAL QUANT STANDARDS (pyquantnews.com Formula Sheet):\n"
            f"  1. Sharpe Ratio (Ann.)      : {self.daily_sharpe_ratio:.2f} (Excess return over 4.0% US Treasury)\n"
            f"  2. Expectancy               : ${self.expectancy_usd:+,.2f} / trade (Ratio: {self.expectancy_ratio:+.2f}R)\n"
            f"     Formula: (W/T * AWR) - (L/T * ALR) -> ({w_ratio:.1%} * ${self.avg_win_usd:,.2f}) - ({l_ratio:.1%} * ${abs(self.avg_loss_usd):,.2f})\n"
            f"  3. Value at Risk (VaR)      : 95% Conf = {self.var_95_pct:.2f}% (${self.var_95_usd:,.2f})\n"
            f"                              : 99% Conf = {self.var_99_pct:.2f}% (${self.var_99_usd:,.2f})\n"
            f"  4. Mean Adverse Excursion   : Avg MAE = ${self.mean_mae_usd:,.2f} | Max MAE = ${self.max_mae_usd:,.2f}\n"
            f"     Mean Favorable Excursion : Avg MFE = ${self.mean_mfe_usd:,.2f} | Max MFE = ${self.max_mfe_usd:,.2f}\n"
            f"  5. Cond. Value at Risk(CVaR): CVaR 95% = {self.cvar_95_pct:.2f}% (${self.cvar_95_usd:,.2f})\n"
            f"                              : CVaR 99% = {self.cvar_99_pct:.2f}% (${self.cvar_99_usd:,.2f})\n"
            f"  6. Drawdown (Peak-Trough)   : Max DD = {self.max_drawdown_pct:.2f}% (${self.max_drawdown_usd:,.2f}) | Avg DD = {self.avg_drawdown_pct:.2f}%\n"
            f"  7. Sortino Ratio (Ann.)     : {self.sortino_ratio:.2f} (Downside deviation risk-adjusted)\n"
            f"  8. Calmar Ratio             : {self.calmar_ratio:.2f} (CAGR {self.cagr_pct:.2f}% / Max DD {self.max_drawdown_pct:.2f}%)\n"
            f"{subsep}\n"
            f"  EXECUTION PROFILE & TRADE METRICS:\n"
            f"  Combined Trades     : {self.total_trades} trades\n"
            f"  Winning Trades      : {self.winning_trades} ({self.win_rate:.1f}%)\n"
            f"  Losing Trades       : {self.losing_trades}\n"
            f"  Avg PnL / Trade     : ${self.avg_pnl_usd:+,.2f}\n"
            f"  Avg Win / Avg Loss  : ${self.avg_win_usd:,.2f} / ${self.avg_loss_usd:,.2f}\n"
            f"  Best / Worst Trade  : ${self.best_trade_usd:,.2f} / ${self.worst_trade_usd:,.2f}\n"
            f"{subsep}\n"
            f"  STRATEGY ATTRIBUTION BREAKDOWN:\n"
            f"  1. Asian Mean Reversion (01:00 - 04:30 UTC):\n"
            f"     Trades           : {self.asian_trades} ({self.asian_trades/max(1, self.total_trades)*100:.1f}% alokasi)\n"
            f"     Win Rate / PF    : {self.asian_win_rate:.1f}% / {self.asian_pf:.2f}\n"
            f"     Net PnL          : ${self.asian_pnl_usd:+,.2f}\n"
        )
        if getattr(pcfg, "ENABLE_LONDON_ORB", False):
            res += (
                f"  2. London Pit Opening Range Breakout (08:15 - 11:30 UTC):\n"
                f"     Trades           : {self.london_trades} ({self.london_trades/max(1, self.total_trades)*100:.1f}% alokasi)\n"
                f"     Win Rate / PF    : {self.london_win_rate:.1f}% / {self.london_pf:.2f}\n"
                f"     Net PnL          : ${self.london_pnl_usd:+,.2f}\n"
            )
        if getattr(pcfg, "ENABLE_STRATEGY_2", False):
            res += (
                f"  3. New York Opening Range Breakout (13:45 - 16:30 UTC):\n"
                f"     Trades           : {self.ny_trades} ({self.ny_trades/max(1, self.total_trades)*100:.1f}% alokasi)\n"
                f"     Win Rate / PF    : {self.ny_win_rate:.1f}% / {self.ny_pf:.2f}\n"
                f"     Net PnL          : ${self.ny_pnl_usd:+,.2f}\n"
            )
        res += f"{sep}\n"
        return res


class PortfolioEngine:
    """Orkestrator eksekusi portofolio gabungan."""

    def __init__(self, df_m5: pd.DataFrame, df_m1: Optional[pd.DataFrame] = None):
        self.df_raw = df_m5.copy()
        self.df_m1 = df_m1
        self.trades: List[PortfolioTradeRecord] = []
        self.equity_curve: List[float] = []
        self.equity_dates: List[pd.Timestamp] = []
        self.asian_equity: List[float] = []
        self.london_equity: List[float] = []
        self.ny_equity: List[float] = []
        self.stats: PortfolioStats = PortfolioStats()

        # Dataframe per modul
        self.df_asian: Optional[pd.DataFrame] = None
        self.df_london: Optional[pd.DataFrame] = None
        self.df_ny: Optional[pd.DataFrame] = None

    def run(self) -> PortfolioStats:
        """Jalankan simulasi portofolio terpadu."""
        asian_trades = []
        if getattr(pcfg, "ENABLE_ASIAN_MR", True):
            print("      [1/4] Menjalankan modul Asian Mean Reversion (M5)...")
            self.df_asian = compute_asian_indicators(self.df_raw)
            bt_asian = AsianBacktester(self.df_asian)
            asian_stats = bt_asian.run()
            asian_trades = bt_asian.trades
        else:
            print("      [1/4] Modul Asian Mean Reversion dinonaktifkan.")

        london_trades = []
        if getattr(pcfg, "ENABLE_LONDON_ORB", True):
            mode_desc = "M1 Bar Magnifier" if self.df_m1 is not None else "M5"
            print(f"      [2/4] Menjalankan modul London Pit ORB ({mode_desc})...")
            self.df_london = compute_london_indicators(self.df_raw)
            bt_london = LondonBacktester(self.df_london, df_m1=self.df_m1)
            london_stats = bt_london.run()
            london_trades = bt_london.trades
        else:
            print("      [2/4] Modul London Pit ORB dinonaktifkan.")

        ny_trades = []
        if getattr(pcfg, "ENABLE_STRATEGY_2", False):
            mode_desc = "M1 Bar Magnifier" if self.df_m1 is not None else "M5"
            print(f"      [3/4] Menjalankan modul New York ORB ({mode_desc})...")
            self.df_ny = compute_ny_indicators(self.df_raw)
            bt_ny = NYBacktester(self.df_ny, df_m1=self.df_m1)
            ny_stats = bt_ny.run()
            ny_trades = bt_ny.trades
        else:
            print("      [3/4] Modul New York ORB dinonaktifkan.")

        print("      [4/4] Mensinkronkan trade log kronologis & kurva ekuitas portofolio...")
        self._merge_and_sync_trades(asian_trades, london_trades, ny_trades)
        self._compute_portfolio_metrics()

        return self.stats

    def _merge_and_sync_trades(self, asian_trades, london_trades, ny_trades):
        """Gabungkan hasil trade dengan asymmetric compounding & dynamic de-risking."""
        self.trades.clear()
        raw_trades: List[PortfolioTradeRecord] = []

        # 1. Konversi trade Asia
        for t in asian_trades:
            raw_trades.append(PortfolioTradeRecord(
                strategy="ASIAN_MR",
                entry_datetime=t.entry_signal.datetime,
                exit_datetime=t.exit_datetime,
                direction=t.entry_signal.direction.value,
                lot_size=t.entry_signal.lot_size,
                entry_price=t.entry_signal.entry_price,
                exit_price=t.exit_price,
                pnl_usd=t.pnl_usd,
                pnl_points=t.pnl_points,
                exit_reason=t.exit_reason.value,
                duration_minutes=t.duration_minutes,
                mfe_usd=t.mfe_usd,
                mae_usd=t.mae_usd,
            ))

        # 2. Konversi trade London Pit ORB
        for t in london_trades:
            raw_trades.append(PortfolioTradeRecord(
                strategy="LONDON_ORB",
                entry_datetime=t.signal.datetime,
                exit_datetime=t.exit_datetime,
                direction=t.signal.direction.value,
                lot_size=t.signal.lot_size,
                entry_price=t.signal.entry_price,
                exit_price=t.exit_price,
                pnl_usd=t.pnl_usd,
                pnl_points=t.pnl_points,
                exit_reason=t.exit_reason.value,
                duration_minutes=t.duration_minutes,
                mfe_usd=t.mfe_usd,
                mae_usd=t.mae_usd,
            ))

        # 3. Konversi trade NY ORB
        for t in ny_trades:
            raw_trades.append(PortfolioTradeRecord(
                strategy="NY_ORB",
                entry_datetime=t.signal.datetime,
                exit_datetime=t.exit_datetime,
                direction=t.signal.direction.value,
                lot_size=t.signal.lot_size,
                entry_price=t.signal.entry_price,
                exit_price=t.exit_price,
                pnl_usd=t.pnl_usd,
                pnl_points=t.pnl_points,
                exit_reason=t.exit_reason.value,
                duration_minutes=t.duration_minutes,
                mfe_usd=t.mfe_usd,
                mae_usd=t.mae_usd,
            ))

        # Urutkan secara kronologis berdasarkan waktu entri
        raw_trades.sort(key=lambda x: x.entry_datetime)

        # Bangun kurva ekuitas diskrit trade-by-trade
        cum_pnl = 0.0
        asian_cum = 0.0
        london_cum = 0.0
        ny_cum = 0.0
        init_cap = pcfg.PORTFOLIO_INITIAL_CAPITAL
        curr_equity = init_cap

        self.equity_curve = [init_cap]
        self.asian_equity = [init_cap]
        self.london_equity = [init_cap]
        self.ny_equity = [init_cap]
        self.equity_dates = [self.df_raw["datetime"].iloc[0]]

        consecutive_loss_days = 0
        last_trade_date = None
        current_day_pnl = 0.0

        for t in raw_trades:
            t_date = t.entry_datetime.date()

            # Update tracker hari rugi berturut-turut jika tanggal berganti
            if last_trade_date is not None and t_date != last_trade_date:
                if current_day_pnl < 0:
                    consecutive_loss_days += 1
                else:
                    consecutive_loss_days = 0
                current_day_pnl = 0.0
            last_trade_date = t_date

            # Dynamic De-Risking Cooldown (Pangkas risiko 50% jika 2 hari rugi berturut-turut)
            derisk_multiplier = 1.0
            if getattr(pcfg, "ENABLE_DYNAMIC_DERISKING", False):
                if consecutive_loss_days >= getattr(pcfg, "DERISKING_CONSECUTIVE_DAYS", 2):
                    derisk_multiplier = getattr(pcfg, "DERISKING_RATIO", 0.5)

            # Dynamic Equity Compounding (% Risk Sizing Asimetris)
            if pcfg.USE_COMPOUNDING:
                if t.strategy == "ASIAN_MR":
                    strat_risk_pct = getattr(pcfg, "ASIAN_RISK_PCT", 0.01)
                    fixed_baseline_usd = getattr(pcfg, "ASIAN_FIXED_RISK_USD", 80.0)
                elif t.strategy == "LONDON_ORB":
                    strat_risk_pct = getattr(pcfg, "LONDON_RISK_PCT", 0.02)
                    fixed_baseline_usd = getattr(pcfg, "LONDON_FIXED_RISK_USD", 80.0)
                else:  # NY_ORB
                    strat_risk_pct = getattr(pcfg, "NY_RISK_PCT", 0.02)
                    fixed_baseline_usd = getattr(pcfg, "NY_FIXED_RISK_USD", 80.0)

                target_risk_usd = curr_equity * strat_risk_pct * derisk_multiplier
                scale_factor = target_risk_usd / fixed_baseline_usd
                raw_lot = t.lot_size * scale_factor
                scaled_lot = round(round(raw_lot / pcfg.LOT_STEP) * pcfg.LOT_STEP, 2)
                scaled_lot = max(pcfg.MIN_LOT, min(scaled_lot, pcfg.MAX_LOT))
                lot_ratio = scaled_lot / t.lot_size if t.lot_size > 0 else 1.0

                t.lot_size = scaled_lot
                t.pnl_usd = round(t.pnl_usd * lot_ratio, 2)
                t.mfe_usd = round(t.mfe_usd * lot_ratio, 2)
                t.mae_usd = round(t.mae_usd * lot_ratio, 2)

            # Update equity tracking
            cum_pnl += t.pnl_usd
            curr_equity += t.pnl_usd
            current_day_pnl += t.pnl_usd

            if t.strategy == "ASIAN_MR":
                asian_cum += t.pnl_usd
            elif t.strategy == "LONDON_ORB":
                london_cum += t.pnl_usd
            else:
                ny_cum += t.pnl_usd

            self.equity_curve.append(init_cap + cum_pnl)
            self.asian_equity.append(init_cap + asian_cum)
            self.london_equity.append(init_cap + london_cum)
            self.ny_equity.append(init_cap + ny_cum)
            self.equity_dates.append(t.exit_datetime)

            # Reset status de-risking jika trade mencetak profit
            if t.pnl_usd > 0 and getattr(pcfg, "ENABLE_DYNAMIC_DERISKING", False):
                consecutive_loss_days = 0

            self.trades.append(t)

    def _compute_portfolio_metrics(self):
        """Kalkulasi metrik gabungan portofolio."""
        stats = self.stats
        stats.initial_capital = pcfg.PORTFOLIO_INITIAL_CAPITAL
        stats.total_trades = len(self.trades)

        if stats.total_trades == 0:
            return

        pnls = [t.pnl_usd for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        stats.winning_trades = len(wins)
        stats.losing_trades = len(losses)
        stats.win_rate = (stats.winning_trades / stats.total_trades) * 100.0

        stats.total_net_pnl_usd = sum(pnls)
        stats.ending_capital = stats.initial_capital + stats.total_net_pnl_usd
        stats.roi_pct = (stats.total_net_pnl_usd / stats.initial_capital) * 100.0

        stats.avg_pnl_usd = np.mean(pnls)
        stats.avg_win_usd = np.mean(wins) if wins else 0.0
        stats.avg_loss_usd = np.mean(losses) if losses else 0.0
        stats.best_trade_usd = max(pnls) if pnls else 0.0
        stats.worst_trade_usd = min(pnls) if pnls else 0.0

        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        stats.profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")

        # Peak-to-trough drawdown
        equity_arr = np.array(self.equity_curve)
        peaks = np.maximum.accumulate(equity_arr)
        drawdowns_usd = peaks - equity_arr
        drawdowns_pct = np.where(peaks > 0, (drawdowns_usd / peaks) * 100.0, 0.0)
        stats.max_drawdown_usd = float(drawdowns_usd.max())
        stats.max_drawdown_pct = float(drawdowns_pct.max())
        active_dds = drawdowns_pct[drawdowns_pct > 0]
        stats.avg_drawdown_pct = float(np.mean(active_dds)) if len(active_dds) > 0 else 0.0

        # Daily returns
        trading_dates = sorted(self.df_raw["datetime"].dt.date.unique())
        total_trading_days = max(1, len(trading_dates))
        time_span_days = (self.df_raw["datetime"].iloc[-1] - self.df_raw["datetime"].iloc[0]).days
        years = max(1.0 / 252.0, time_span_days / 365.25)

        # Map exits to daily equity
        df_t = self.trade_log
        if not df_t.empty:
            df_t["exit_date"] = df_t["exit_datetime"].dt.date
            daily_trade_pnl = df_t.groupby("exit_date")["pnl_usd"].sum()
        else:
            daily_trade_pnl = pd.Series(dtype=float)

        daily_equity_series = pd.Series(index=trading_dates, dtype=float)
        curr_eq = stats.initial_capital
        for d in trading_dates:
            if d in daily_trade_pnl.index:
                curr_eq += daily_trade_pnl.loc[d]
            daily_equity_series.loc[d] = curr_eq

        # Daily percentage return series: r_d
        prev_eq = daily_equity_series.shift(1).fillna(stats.initial_capital)
        daily_returns = (daily_equity_series - prev_eq) / prev_eq
        returns_arr = daily_returns.values

        # Sharpe ratio
        rf_ann = 0.04
        rf_daily = rf_ann / 252.0
        excess_returns = returns_arr - rf_daily
        std_ret = np.std(returns_arr, ddof=1)
        stats.daily_sharpe_ratio = float((np.mean(excess_returns) / std_ret) * np.sqrt(252)) if std_ret > 0 else 0.0
        stats.sharpe_ratio = stats.daily_sharpe_ratio

        # Expectancy
        w_ratio = stats.winning_trades / stats.total_trades
        l_ratio = stats.losing_trades / stats.total_trades
        stats.expectancy_usd = float((w_ratio * stats.avg_win_usd) - (l_ratio * abs(stats.avg_loss_usd)))
        if abs(stats.avg_loss_usd) > 0:
            stats.expectancy_ratio = float((w_ratio * (stats.avg_win_usd / abs(stats.avg_loss_usd))) - l_ratio)
        else:
            stats.expectancy_ratio = float("inf")

        # VaR
        q_05 = float(np.quantile(returns_arr, 0.05))
        q_01 = float(np.quantile(returns_arr, 0.01))
        stats.var_95_pct = float(max(0.0, -q_05 * 100.0))
        stats.var_99_pct = float(max(0.0, -q_01 * 100.0))
        stats.var_95_usd = float(stats.ending_capital * (stats.var_95_pct / 100.0))
        stats.var_99_usd = float(stats.ending_capital * (stats.var_99_pct / 100.0))

        # CVaR
        tail_95 = returns_arr[returns_arr <= q_05]
        stats.cvar_95_pct = float(max(0.0, -np.mean(tail_95) * 100.0)) if len(tail_95) > 0 else stats.var_95_pct
        stats.cvar_95_usd = float(stats.ending_capital * (stats.cvar_95_pct / 100.0))

        tail_99 = returns_arr[returns_arr <= q_01]
        stats.cvar_99_pct = float(max(0.0, -np.mean(tail_99) * 100.0)) if len(tail_99) > 0 else stats.var_99_pct
        stats.cvar_99_usd = float(stats.ending_capital * (stats.cvar_99_pct / 100.0))

        # MAE / MFE
        mae_list = [abs(t.mae_usd) for t in self.trades]
        mfe_list = [t.mfe_usd for t in self.trades]
        stats.mean_mae_usd = float(np.mean(mae_list)) if mae_list else 0.0
        stats.max_mae_usd = float(max(mae_list)) if mae_list else 0.0
        stats.mean_mfe_usd = float(np.mean(mfe_list)) if mfe_list else 0.0
        stats.max_mfe_usd = float(max(mfe_list)) if mfe_list else 0.0

        # Sortino
        downside_diff = np.minimum(0.0, returns_arr - rf_daily)
        downside_dev = np.sqrt(np.mean(downside_diff ** 2)) * np.sqrt(252)
        annual_excess_return = (np.mean(returns_arr) * 252) - rf_ann
        stats.sortino_ratio = float(annual_excess_return / downside_dev) if downside_dev > 0 else 0.0

        # Calmar
        if stats.ending_capital > 0 and stats.initial_capital > 0 and years > 0:
            stats.cagr_pct = float(((stats.ending_capital / stats.initial_capital) ** (1.0 / years) - 1.0) * 100.0)
        else:
            stats.cagr_pct = 0.0

        stats.calmar_ratio = float(stats.cagr_pct / stats.max_drawdown_pct) if stats.max_drawdown_pct > 0 else float("inf")

        # Breakdown Asian MR
        a_trades = [t for t in self.trades if t.strategy == "ASIAN_MR"]
        stats.asian_trades = len(a_trades)
        stats.asian_wins = len([t for t in a_trades if t.pnl_usd > 0])
        stats.asian_pnl_usd = sum(t.pnl_usd for t in a_trades)
        stats.asian_win_rate = (stats.asian_wins / stats.asian_trades * 100.0) if stats.asian_trades > 0 else 0.0
        a_losses_sum = abs(sum(t.pnl_usd for t in a_trades if t.pnl_usd <= 0))
        a_wins_sum = sum(t.pnl_usd for t in a_trades if t.pnl_usd > 0)
        stats.asian_pf = (a_wins_sum / a_losses_sum) if a_losses_sum > 0 else float("inf")

        # Breakdown London Pit ORB
        lon_tr = [t for t in self.trades if t.strategy == "LONDON_ORB"]
        stats.london_trades = len(lon_tr)
        stats.london_wins = len([t for t in lon_tr if t.pnl_usd > 0])
        stats.london_pnl_usd = sum(t.pnl_usd for t in lon_tr)
        stats.london_win_rate = (stats.london_wins / stats.london_trades * 100.0) if stats.london_trades > 0 else 0.0
        lon_losses_sum = abs(sum(t.pnl_usd for t in lon_tr if t.pnl_usd <= 0))
        lon_wins_sum = sum(t.pnl_usd for t in lon_tr if t.pnl_usd > 0)
        stats.london_pf = (lon_wins_sum / lon_losses_sum) if lon_losses_sum > 0 else float("inf")

        # Breakdown NY ORB
        ny_tr = [t for t in self.trades if t.strategy == "NY_ORB"]
        stats.ny_trades = len(ny_tr)
        stats.ny_wins = len([t for t in ny_tr if t.pnl_usd > 0])
        stats.ny_pnl_usd = sum(t.pnl_usd for t in ny_tr)
        stats.ny_win_rate = (stats.ny_wins / stats.ny_trades * 100.0) if stats.ny_trades > 0 else 0.0
        ny_losses_sum = abs(sum(t.pnl_usd for t in ny_tr if t.pnl_usd <= 0))
        ny_wins_sum = sum(t.pnl_usd for t in ny_tr if t.pnl_usd > 0)
        stats.ny_pf = (ny_wins_sum / ny_losses_sum) if ny_losses_sum > 0 else float("inf")

        # Monthly breakdown
        df_t = self.trade_log
        if not df_t.empty:
            df_t["month_str"] = df_t["entry_datetime"].dt.strftime("%Y-%m")
            m_pivot = df_t.pivot_table(index="month_str", columns="strategy", values="pnl_usd", aggfunc="sum", fill_value=0.0)
            if "ASIAN_MR" not in m_pivot.columns:
                m_pivot["ASIAN_MR"] = 0.0
            if "LONDON_ORB" not in m_pivot.columns:
                m_pivot["LONDON_ORB"] = 0.0
            if "NY_ORB" not in m_pivot.columns:
                m_pivot["NY_ORB"] = 0.0
            m_pivot["TOTAL"] = m_pivot["ASIAN_MR"] + m_pivot["LONDON_ORB"] + m_pivot["NY_ORB"]
            stats.monthly_pnl_df = m_pivot

    @property
    def trade_log(self) -> pd.DataFrame:
        """Dataframe trade log terpadu."""
        if not self.trades:
            return pd.DataFrame()

        rows = []
        for t in self.trades:
            rows.append({
                "strategy": t.strategy,
                "entry_datetime": t.entry_datetime,
                "exit_datetime": t.exit_datetime,
                "direction": t.direction,
                "lot_size": t.lot_size,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl_usd": t.pnl_usd,
                "pnl_points": t.pnl_points,
                "exit_reason": t.exit_reason,
                "duration_min": t.duration_minutes,
                "mfe_usd": t.mfe_usd,
                "mae_usd": t.mae_usd,
            })
        return pd.DataFrame(rows)
