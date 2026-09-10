"""
Master Multi-Regime Portfolio — Execution Engine
================================================
Mesin orkestrator terpadu portofolio kuantitatif:
1. Asian Mean Reversion (M5) — 01:00 to 04:30 UTC
2. New York Opening Range Breakout (M5) — 13:45 to 16:30 UTC

Menyatukan eksekusi trade secara kronologis pada akun modal $10,000,
mengimplementasikan alokasi risiko asimetris (2.0% Asia : 1.0% NY),
dynamic compounding, de-risking cooldown, dan metrik atribusi bulanan.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd

import portfolio_config as pcfg
import config as acfg
import ny_config as ny_cfg

# Modul Asian Mean Reversion
from engine.engine_asia.indicators import compute_all as compute_asian_indicators
from engine.engine_asia.backtester import Backtester as AsianBacktester, BacktestStats as AsianStats

# Modul New York ORB
from engine.engine_ny.ny_strategy import compute_ny_indicators
from engine.engine_ny.ny_engine import NYBacktester, NYStats


@dataclass
class PortfolioTradeRecord:
    """Struktur data standar trade gabungan portofolio."""
    strategy: str                     # "ASIAN_MR" atau "NY_ORB"
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

    # Breakdown Modul 1: Asian Mean Reversion
    asian_trades: int = 0
    asian_wins: int = 0
    asian_pnl_usd: float = 0.0
    asian_win_rate: float = 0.0
    asian_pf: float = 0.0

    # Breakdown Modul 2: New York ORB
    ny_trades: int = 0
    ny_wins: int = 0
    ny_pnl_usd: float = 0.0
    ny_win_rate: float = 0.0
    ny_pf: float = 0.0

    # Monthly breakdown table
    monthly_pnl_df: pd.DataFrame = field(default_factory=pd.DataFrame)

    def __str__(self) -> str:
        sep = "=" * 64
        subsep = "-" * 64
        a_risk = getattr(pcfg, "ASIAN_RISK_PCT", 0.02) * 100
        ny_risk = getattr(pcfg, "NY_RISK_PCT", 0.01) * 100
        pos_sizing_str = f"Asymmetric Compounding (Asia: {a_risk:.1f}% | NY: {ny_risk:.1f}%)" if pcfg.USE_COMPOUNDING else "Fixed Dollar Risk"
        risk_ctrl_str = f"Dynamic De-Risking={'ON (50% Cooldown)' if getattr(pcfg, 'ENABLE_DYNAMIC_DERISKING', False) else 'OFF'}"

        res = (
            f"\n{sep}\n"
            f"   QUANTITATIVE MASTER PORTFOLIO — PERFORMANCE REPORT\n"
            f"{sep}\n"
            f"  Initial Capital     : ${self.initial_capital:,.2f}\n"
            f"  Ending Capital      : ${self.ending_capital:,.2f}\n"
            f"  Total Net PnL       : ${self.total_net_pnl_usd:+,.2f} (+{self.roi_pct:.2f}%)\n"
            f"  Profit Factor       : {self.profit_factor:.2f}\n"
            f"  Sharpe Ratio (Ann.) : {self.sharpe_ratio:.2f}\n"
            f"  Max Drawdown        : ${self.max_drawdown_usd:,.2f} ({self.max_drawdown_pct:.2f}%)\n"
            f"  Position Sizing     : {pos_sizing_str}\n"
            f"  Risk Control        : {risk_ctrl_str}\n"
            f"{subsep}\n"
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
        if getattr(pcfg, "ENABLE_STRATEGY_2", False):
            res += (
                f"  2. New York Opening Range Breakout (13:45 - 16:30 UTC):\n"
                f"     Trades           : {self.ny_trades} ({self.ny_trades/max(1, self.total_trades)*100:.1f}% alokasi)\n"
                f"     Win Rate / PF    : {self.ny_win_rate:.1f}% / {self.ny_pf:.2f}\n"
                f"     Net PnL          : ${self.ny_pnl_usd:+,.2f}\n"
            )
        res += f"{sep}\n"
        return res


class PortfolioEngine:
    """Orkestrator eksekusi portofolio gabungan."""

    def __init__(self, df_m5: pd.DataFrame):
        self.df_raw = df_m5.copy()
        self.trades: List[PortfolioTradeRecord] = []
        self.equity_curve: List[float] = []
        self.equity_dates: List[pd.Timestamp] = []
        self.asian_equity: List[float] = []
        self.ny_equity: List[float] = []
        self.stats: PortfolioStats = PortfolioStats()

        # Dataframe per modul
        self.df_asian: Optional[pd.DataFrame] = None
        self.df_ny: Optional[pd.DataFrame] = None

    def run(self) -> PortfolioStats:
        """Jalankan simulasi portofolio terpadu."""
        asian_trades = []
        if getattr(pcfg, "ENABLE_ASIAN_MR", True):
            print("      [1/3] Menjalankan modul Asian Mean Reversion (M5)...")
            self.df_asian = compute_asian_indicators(self.df_raw)
            bt_asian = AsianBacktester(self.df_asian)
            asian_stats = bt_asian.run()
            asian_trades = bt_asian.trades
        else:
            print("      [1/3] Modul Asian Mean Reversion dinonaktifkan.")

        ny_trades = []
        if getattr(pcfg, "ENABLE_STRATEGY_2", False):
            print("      [2/3] Menjalankan modul New York ORB (M5)...")
            self.df_ny = compute_ny_indicators(self.df_raw)
            bt_ny = NYBacktester(self.df_ny)
            ny_stats = bt_ny.run()
            ny_trades = bt_ny.trades
        else:
            print("      [2/3] Modul New York ORB dinonaktifkan.")

        print("      [3/3] Mensinkronkan trade log kronologis & kurva ekuitas portofolio...")
        self._merge_and_sync_trades(asian_trades, ny_trades)
        self._compute_portfolio_metrics()

        return self.stats

    def _merge_and_sync_trades(self, asian_trades, ny_trades):
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

        # 2. Konversi trade NY ORB
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
        ny_cum = 0.0
        init_cap = pcfg.PORTFOLIO_INITIAL_CAPITAL
        curr_equity = init_cap

        self.equity_curve = [init_cap]
        self.asian_equity = [init_cap]
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
                    strat_risk_pct = getattr(pcfg, "ASIAN_RISK_PCT", 0.02)
                    fixed_baseline_usd = getattr(pcfg, "ASIAN_FIXED_RISK_USD", 80.0)
                else:
                    strat_risk_pct = getattr(pcfg, "NY_RISK_PCT", 0.01)
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
            else:
                ny_cum += t.pnl_usd

            self.equity_curve.append(init_cap + cum_pnl)
            self.asian_equity.append(init_cap + asian_cum)
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

        # Max Drawdown
        equity_arr = np.array(self.equity_curve)
        peaks = np.maximum.accumulate(equity_arr)
        dds = peaks - equity_arr
        stats.max_drawdown_usd = dds.max()
        if peaks.max() > 0:
            stats.max_drawdown_pct = (stats.max_drawdown_usd / peaks.max()) * 100.0

        # Annualized Sharpe Ratio
        trading_days = max(1, len(self.df_raw["datetime"].dt.date.unique()))
        trades_per_year = stats.total_trades * (pcfg.ANNUAL_TRADING_DAYS / trading_days)
        mean_ret = np.mean(pnls)
        std_ret = np.std(pnls, ddof=1)
        stats.sharpe_ratio = (mean_ret / std_ret) * np.sqrt(trades_per_year) if std_ret > 0 else 0.0

        # Breakdown Asian MR
        a_trades = [t for t in self.trades if t.strategy == "ASIAN_MR"]
        stats.asian_trades = len(a_trades)
        stats.asian_wins = len([t for t in a_trades if t.pnl_usd > 0])
        stats.asian_pnl_usd = sum(t.pnl_usd for t in a_trades)
        stats.asian_win_rate = (stats.asian_wins / stats.asian_trades * 100.0) if stats.asian_trades > 0 else 0.0
        a_losses_sum = abs(sum(t.pnl_usd for t in a_trades if t.pnl_usd <= 0))
        a_wins_sum = sum(t.pnl_usd for t in a_trades if t.pnl_usd > 0)
        stats.asian_pf = (a_wins_sum / a_losses_sum) if a_losses_sum > 0 else float("inf")

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
            if "NY_ORB" not in m_pivot.columns:
                m_pivot["NY_ORB"] = 0.0
            m_pivot["TOTAL"] = m_pivot["ASIAN_MR"] + m_pivot["NY_ORB"]
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
