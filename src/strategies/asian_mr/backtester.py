"""
Asian Mean Reversion — Backtesting Engine
===========================================
Simulasi bar-by-bar dengan tracking posisi, PnL, dan statistik performa.
"""

from dataclasses import dataclass
from typing import List, Optional
import numpy as np
import pandas as pd

from src.core.types import Direction, ExitReason, Signal, TradeResult
from . import config as cfg
from .signals import (
    check_entry_signal,
    check_exit_conditions,
    get_exit_price,
)


@dataclass
class BacktestStats:
    """Statistik ringkasan hasil backtest."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0

    total_pnl_usd: float = 0.0
    avg_pnl_usd: float = 0.0
    avg_win_usd: float = 0.0
    avg_loss_usd: float = 0.0

    max_drawdown_usd: float = 0.0
    max_drawdown_pct: float = 0.0

    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0

    avg_duration_min: float = 0.0
    max_duration_min: float = 0.0

    # Breakdown per exit reason
    exits_tp: int = 0
    exits_sl: int = 0
    exits_hard_cut: int = 0
    exits_time_stop: int = 0
    exits_session_cutoff: int = 0

    best_trade_usd: float = 0.0
    worst_trade_usd: float = 0.0

    def __str__(self) -> str:
        sep = "-" * 50
        return (
            f"\n{sep}\n"
            f"  BACKTEST RESULTS - Asian Mean Reversion\n"
            f"{sep}\n"
            f"  Total Trades      : {self.total_trades}\n"
            f"  Winning Trades    : {self.winning_trades}\n"
            f"  Losing Trades     : {self.losing_trades}\n"
            f"  Win Rate          : {self.win_rate:.1f}%\n"
            f"{sep}\n"
            f"  Total PnL         : ${self.total_pnl_usd:,.2f}\n"
            f"  Avg PnL/Trade     : ${self.avg_pnl_usd:,.2f}\n"
            f"  Avg Win           : ${self.avg_win_usd:,.2f}\n"
            f"  Avg Loss          : ${self.avg_loss_usd:,.2f}\n"
            f"  Best Trade        : ${self.best_trade_usd:,.2f}\n"
            f"  Worst Trade       : ${self.worst_trade_usd:,.2f}\n"
            f"{sep}\n"
            f"  Max Drawdown      : ${self.max_drawdown_usd:,.2f} ({self.max_drawdown_pct:.2f}%)\n"
            f"  Profit Factor     : {self.profit_factor:.2f}\n"
            f"  Sharpe Ratio      : {self.sharpe_ratio:.2f}\n"
            f"{sep}\n"
            f"  Avg Duration      : {self.avg_duration_min:.1f} min\n"
            f"  Max Duration      : {self.max_duration_min:.1f} min\n"
            f"{sep}\n"
            f"  Exit Breakdown:\n"
            f"    Take Profit     : {self.exits_tp}\n"
            f"    Stop Loss       : {self.exits_sl}\n"
            f"    Hard Cut (|Z|>3.2): {self.exits_hard_cut}\n"
            f"    Time Stop (60m) : {self.exits_time_stop}\n"
            f"    Session Cutoff  : {self.exits_session_cutoff}\n"
            f"{sep}\n"
        )


class Backtester:
    """Mesin backtesting bar-by-bar untuk Asian Mean Reversion."""

    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        self.trades: List[TradeResult] = []
        self.equity_curve: List[float] = []
        self.stats: Optional[BacktestStats] = None

        self._current_signal: Optional[Signal] = None
        self._capital = cfg.INITIAL_CAPITAL
        self._mfe_points = 0.0
        self._mae_points = 0.0
        self.detailed_log_lines: List[str] = []

        self._trades_today = 0
        self._last_trade_date = None

    def run(self) -> BacktestStats:
        self.trades = []
        self.equity_curve = []
        self._current_signal = None
        self._capital = cfg.INITIAL_CAPITAL

        for idx, row in self.df.iterrows():
            unrealized = self._calc_unrealized_pnl(row)
            self.equity_curve.append(self._capital + unrealized)

            current_date = row["datetime"].date()
            if current_date != self._last_trade_date:
                self._trades_today = 0
                self._last_trade_date = current_date

            if self._current_signal is not None:
                self._update_mfe_mae(row)
                exit_reason = check_exit_conditions(row, self._current_signal)
                if exit_reason is not None:
                    self._close_trade(row, idx, exit_reason)
                continue

            if self._trades_today < cfg.MAX_TRADES_PER_DAY:
                signal = check_entry_signal(row, idx)
                if signal is not None:
                    self._open_trade(signal)

        if self._current_signal is not None:
            last_row = self.df.iloc[-1]
            last_idx = len(self.df) - 1
            self._update_mfe_mae(last_row)
            self._close_trade(last_row, last_idx, ExitReason.SESSION_CUTOFF)

        self.stats = self._compute_stats()
        return self.stats

    def _update_mfe_mae(self, row: pd.Series) -> None:
        signal = self._current_signal
        if signal is None:
            return

        if signal.direction.is_long:
            high_diff = row["high"] - signal.entry_price
            low_diff = row["low"] - signal.entry_price
            self._mfe_points = max(self._mfe_points, high_diff)
            self._mae_points = min(self._mae_points, low_diff)
        else:
            low_diff = signal.entry_price - row["low"]
            high_diff = signal.entry_price - row["high"]
            self._mfe_points = max(self._mfe_points, low_diff)
            self._mae_points = min(self._mae_points, high_diff)

    def _open_trade(self, signal: Signal) -> None:
        self._current_signal = signal
        self._mfe_points = 0.0
        self._mae_points = 0.0
        self._trades_today += 1

        self.detailed_log_lines.append(f"=== NEW TRADE ENTRY ===")
        self.detailed_log_lines.append(f"[{signal.datetime}] Direction: {signal.direction.value} | Entry Price: {signal.entry_price:.2f} | Lot: {signal.lot_size:.2f}")
        self.detailed_log_lines.append(f"    -> Indicators: Z-Score = {signal.zscore:.2f} | RSI(14) = {signal.rsi:.2f} | ATR(14) = {signal.atr:.2f}")
        tp_str = f"{signal.take_profit:.2f}" if signal.take_profit is not None else "Dynamic"
        self.detailed_log_lines.append(f"    -> Targets   : TP = {tp_str} | SL = {signal.stop_loss:.2f}")
        self.detailed_log_lines.append("")

    def _close_trade(self, row: pd.Series, idx: int, reason: ExitReason) -> None:
        signal = self._current_signal
        if signal is None:
            return

        exit_price = get_exit_price(row, signal, reason)
        dt = row["datetime"]

        if signal.direction.is_long:
            pnl_points = exit_price - signal.entry_price
        else:
            pnl_points = signal.entry_price - exit_price

        pnl_points -= cfg.SPREAD_USD

        lot = signal.lot_size
        pnl_usd = pnl_points * lot * cfg.POINT_VALUE - (cfg.COMMISSION_USD * 2 * lot)
        duration = (dt - signal.datetime).total_seconds() / 60.0

        mfe_usd = self._mfe_points * lot * cfg.POINT_VALUE
        mae_usd = self._mae_points * lot * cfg.POINT_VALUE

        trade = TradeResult(
            entry_signal=signal,
            exit_index=idx,
            exit_datetime=dt,
            exit_price=exit_price,
            exit_reason=reason,
            pnl_points=pnl_points,
            pnl_usd=pnl_usd,
            duration_minutes=duration,
            lot_size=lot,
            mfe_usd=mfe_usd,
            mae_usd=mae_usd,
        )

        self.detailed_log_lines.append("--- TRADE EXIT ---")
        self.detailed_log_lines.append(f"[{dt}] Reason: {reason.value} | Exit Price: {exit_price:.2f}")
        self.detailed_log_lines.append(f"    -> Result: PnL = ${pnl_usd:.2f} ({pnl_points:.2f} pts) | Duration = {duration:.0f} min | Lot = {lot:.2f}")
        self.detailed_log_lines.append(f"    -> Excursions: MFE = +${mfe_usd:.2f} | MAE = -${abs(mae_usd):.2f}")
        self.detailed_log_lines.append("=======================\n")

        self.trades.append(trade)
        self._capital += pnl_usd
        self._current_signal = None

    def _calc_unrealized_pnl(self, row: pd.Series) -> float:
        if self._current_signal is None:
            return 0.0

        signal = self._current_signal
        if signal.direction.is_long:
            pnl_points = row["close"] - signal.entry_price
        else:
            pnl_points = signal.entry_price - row["close"]

        return pnl_points * signal.lot_size * cfg.POINT_VALUE

    def _compute_stats(self) -> BacktestStats:
        stats = BacktestStats()
        if not self.trades:
            return stats

        stats.total_trades = len(self.trades)
        pnls = [t.pnl_usd for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        stats.winning_trades = len(wins)
        stats.losing_trades = len(losses)
        stats.win_rate = (stats.winning_trades / stats.total_trades) * 100.0

        stats.total_pnl_usd = sum(pnls)
        stats.avg_pnl_usd = np.mean(pnls)
        stats.avg_win_usd = np.mean(wins) if wins else 0.0
        stats.avg_loss_usd = np.mean(losses) if losses else 0.0

        stats.best_trade_usd = max(pnls) if pnls else 0.0
        stats.worst_trade_usd = min(pnls) if pnls else 0.0

        equity = np.array(self.equity_curve)
        if len(equity) > 0:
            peak = np.maximum.accumulate(equity)
            drawdown = peak - equity
            stats.max_drawdown_usd = drawdown.max()
            if peak.max() > 0:
                stats.max_drawdown_pct = (stats.max_drawdown_usd / peak.max()) * 100.0

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        stats.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        if len(pnls) > 1:
            pnl_arr = np.array(pnls)
            mean_ret = pnl_arr.mean()
            std_ret = pnl_arr.std(ddof=1)
            if std_ret > 0:
                trades_per_year = stats.total_trades * (252 / max(1, self._trading_days()))
                stats.sharpe_ratio = (mean_ret / std_ret) * np.sqrt(trades_per_year)

        durations = [t.duration_minutes for t in self.trades]
        stats.avg_duration_min = np.mean(durations)
        stats.max_duration_min = max(durations)

        for t in self.trades:
            if t.exit_reason in (ExitReason.TAKE_PROFIT, ExitReason.TAKE_PROFIT_Z):
                stats.exits_tp += 1
            elif t.exit_reason in (ExitReason.STOP_LOSS, ExitReason.STOP_LOSS_ATR):
                stats.exits_sl += 1
            elif t.exit_reason in (ExitReason.HARD_CUT, ExitReason.HARD_CUT_Z):
                stats.exits_hard_cut += 1
            elif t.exit_reason in (ExitReason.TIME_STOP, ExitReason.TIME_STOP_60M):
                stats.exits_time_stop += 1
            elif t.exit_reason == ExitReason.SESSION_CUTOFF:
                stats.exits_session_cutoff += 1

        return stats

    def _trading_days(self) -> int:
        if self.df.empty:
            return 1
        dates = self.df["datetime"].dt.date.unique()
        return max(len(dates), 1)

    @property
    def trade_log(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame()

        records = []
        for t in self.trades:
            records.append({
                "entry_datetime": t.entry_signal.datetime,
                "exit_datetime": t.exit_datetime,
                "direction": t.entry_signal.direction.value,
                "lot_size": t.entry_signal.lot_size,
                "entry_price": t.entry_signal.entry_price,
                "exit_price": t.exit_price,
                "stop_loss": t.entry_signal.stop_loss,
                "take_profit": t.entry_signal.take_profit,
                "pnl_points": t.pnl_points,
                "pnl_usd": t.pnl_usd,
                "exit_reason": t.exit_reason.value,
                "duration_min": t.duration_minutes,
                "zscore_at_entry": t.entry_signal.zscore,
                "rsi_at_entry": t.entry_signal.rsi,
                "atr_at_entry": t.entry_signal.atr,
                "mfe_usd": t.mfe_usd,
                "mae_usd": t.mae_usd,
            })

        return pd.DataFrame(records)


# Canonical Strategy alias
AsianBacktester = Backtester
