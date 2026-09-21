"""
New York Opening Range Breakout (NY ORB) — Execution Engine & Backtester
========================================================================
Mesin backtest event-driven sesuai spesifikasi kuantitatif:
- Pembentukan Opening Range M15 (13:30 - 13:45 UTC)
- Evaluasi sinyal pada jendela 13:45 - 16:30 UTC
- Filter True Range Ekspansi > 1.5x SMA20 TR (100% Kausal)
- Pelacakan TP (2.0R), SL (-1.0R), dan TIME exit (16:30 UTC)
- Perhitungan statistik: Win Rate, Total R, Profit Factor, Sharpe, Max Drawdown
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
import numpy as np
import pandas as pd

from src.core.types import Direction, ExitReason
from src.core.stats import BreakoutStats
from . import config as cfg
from .signals import (
    NYStrategy,
    NYSignal,
    compute_ny_indicators,
)
from .trade_manager import NYTradeManager, NYTrade


@dataclass
class NYStats(BreakoutStats):
    """Statistik performa strategi New York ORB."""

    def __str__(self) -> str:
        sep = "=" * 64
        subsep = "-" * 64
        return (
            f"\n{sep}\n"
            f"   NEW YORK OPENING RANGE BREAKOUT (NY ORB) — REPORT\n"
            f"{sep}\n"
            f"  Initial Capital     : ${self.initial_capital:,.2f}\n"
            f"  Ending Capital      : ${self.ending_capital:,.2f}\n"
            f"  Total Net PnL       : ${self.total_net_pnl_usd:+,.2f} (+{self.roi_pct:.2f}%)\n"
            f"  Total R-Multiple    : {self.total_r:+.1f} R (Avg: {self.avg_r:+.3f} R/trade)\n"
            f"  Profit Factor       : {self.profit_factor:.2f}\n"
            f"  Sharpe Ratio (Ann.) : {self.sharpe_ratio:.2f}\n"
            f"  Max Drawdown        : ${self.max_drawdown_usd:,.2f} ({self.max_drawdown_pct:.2f}%) | {self.max_drawdown_r:.1f} R\n"
            f"{subsep}\n"
            f"  Total Trades        : {self.total_trades} trades\n"
            f"  Core WR (TP/SL only): {self.core_win_rate:.1f}% ({self.winning_trades} W / {self.losing_trades} L)\n"
            f"  Avg PnL / Trade     : ${self.avg_pnl_usd:+,.2f}\n"
            f"  Avg Win / Avg Loss  : ${self.avg_win_usd:,.2f} / ${self.avg_loss_usd:,.2f}\n"
            f"  Best / Worst Trade  : ${self.best_trade_usd:,.2f} / ${self.worst_trade_usd:,.2f}\n"
            f"{subsep}\n"
            f"  Exit Breakdown      :\n"
            + "\n".join(f"    - {k:<18}: {v} trades" for k, v in self.exit_counts.items()) + "\n"
            f"{sep}\n"
        )


class NYBacktester:
    """Mesin simulasi event-driven New York ORB."""

    def __init__(self, df: pd.DataFrame, initial_capital: float = cfg.INITIAL_CAPITAL, df_m1: Optional[pd.DataFrame] = None):
        self.df_raw = df.copy()
        self.df_m1 = df_m1.copy() if df_m1 is not None else None
        self.initial_capital = initial_capital
        self.strategy = NYStrategy()
        self.trade_manager = NYTradeManager(current_capital=initial_capital)

        self.equity_curve: List[float] = [initial_capital]
        self.equity_dates: List[pd.Timestamp] = []
        self.stats: NYStats = NYStats(initial_capital=initial_capital)

    @property
    def trades(self) -> List[NYTrade]:
        return self.trade_manager.closed_trades

    def run(self) -> NYStats:
        if self.df_m1 is not None:
            return self._run_m1()
        return self._run_m5()

    def _run_m1(self) -> NYStats:
        if "or_high" not in self.df_raw.columns or "tr_sma20" not in self.df_raw.columns:
            df_m5 = compute_ny_indicators(self.df_raw)
        else:
            df_m5 = self.df_raw

        df_m5 = df_m5.copy()
        df_m5["expansion_ok"] = True
        if cfg.USE_EXPANSION_FILTER:
            df_m5["expansion_ok"] = (df_m5["tr_past"] > cfg.EXPANSION_MULT * df_m5["tr_sma20"]) & (df_m5["tr_sma20"] > 0)

        m1 = self.df_m1.copy()
        if "date" not in m1.columns:
            m1["date"] = m1["datetime"].dt.date
        if "hour" not in m1.columns:
            m1["hour"] = m1["datetime"].dt.hour
        if "minute" not in m1.columns:
            m1["minute"] = m1["datetime"].dt.minute

        cols_to_map = ["datetime", "expansion_ok"]
        htf_col = getattr(cfg, "HTF_COL", "h1_ema50")
        if htf_col in df_m5.columns:
            cols_to_map.append(htf_col)

        m1 = pd.merge_asof(
            m1.sort_values("datetime"),
            df_m5[cols_to_map].sort_values("datetime"),
            on="datetime",
            direction="backward"
        )

        self.equity_dates.append(m1["datetime"].iloc[0])

        for date, day_m1 in m1.groupby("date"):
            trade_count_today = 0
            or_bars = day_m1[(day_m1["hour"] == 13) & (day_m1["minute"] >= 30) & (day_m1["minute"] < 45)]
            if len(or_bars) < cfg.MIN_ORB_BARS:
                continue

            or_high = or_bars["high"].max()
            or_low = or_bars["low"].min()
            or_range = or_high - or_low
            if or_range <= 0:
                continue

            window = day_m1[((day_m1["hour"] == 13) & (day_m1["minute"] >= 45)) |
                            ((day_m1["hour"] > 13) & (day_m1["hour"] < 16)) |
                            ((day_m1["hour"] == 16) & (day_m1["minute"] < 30))].copy()
            if window.empty:
                continue

            n_rows = len(window)
            for i, (_, row) in enumerate(window.iterrows()):
                is_last_bar = (i == n_rows - 1)

                if self.trade_manager.has_open_position:
                    closed = self.trade_manager.update_bar(row, is_last_window_bar=is_last_bar)
                    if closed:
                        self.equity_curve.append(self.trade_manager.current_capital)
                        self.equity_dates.append(row["datetime"])

                if not self.trade_manager.has_open_position:
                    if not getattr(cfg, "ALLOW_REENTRY", False) and trade_count_today >= getattr(cfg, "MAX_TRADES_PER_DAY", 1):
                        continue

                    if not row.get("expansion_ok", False):
                        continue

                    htf_ema = row.get(htf_col, np.nan)
                    htf_filter_active = getattr(cfg, "USE_HTF_TREND_FILTER", False) and pd.notna(htf_ema)

                    # Long
                    if row["high"] > or_high:
                        if htf_filter_active and row["close"] < htf_ema:
                            continue
                        entry = or_high
                        risk = or_range
                        sl = entry - risk
                        tp = entry + risk * cfg.TARGET_RR
                        sig = NYSignal(
                            datetime=row["datetime"],
                            direction=Direction.BUY,
                            entry_price=entry,
                            stop_loss=sl,
                            take_profit=tp,
                            initial_risk=risk,
                            or_high=or_high,
                            or_low=or_low,
                            or_range=or_range
                        )
                        self.trade_manager.open_position(sig, capital=self.trade_manager.current_capital)
                        trade_count_today += 1
                        closed = self.trade_manager.update_bar(row, is_last_window_bar=is_last_bar)
                        if closed:
                            self.equity_curve.append(self.trade_manager.current_capital)
                            self.equity_dates.append(row["datetime"])

                    # Short
                    elif row["low"] < or_low:
                        if htf_filter_active and row["close"] > htf_ema:
                            continue
                        entry = or_low
                        risk = or_range
                        sl = entry + risk
                        tp = entry - risk * cfg.TARGET_RR
                        sig = NYSignal(
                            datetime=row["datetime"],
                            direction=Direction.SELL,
                            entry_price=entry,
                            stop_loss=sl,
                            take_profit=tp,
                            initial_risk=risk,
                            or_high=or_high,
                            or_low=or_low,
                            or_range=or_range
                        )
                        self.trade_manager.open_position(sig, capital=self.trade_manager.current_capital)
                        trade_count_today += 1
                        closed = self.trade_manager.update_bar(row, is_last_window_bar=is_last_bar)
                        if closed:
                            self.equity_curve.append(self.trade_manager.current_capital)
                            self.equity_dates.append(row["datetime"])

            if self.trade_manager.has_open_position:
                last_row = window.iloc[-1]
                closed = self.trade_manager.update_bar(last_row, is_last_window_bar=True)
                if closed:
                    self.equity_curve.append(self.trade_manager.current_capital)
                    self.equity_dates.append(last_row["datetime"])

        self._compute_stats()
        return self.stats

    def _run_m5(self) -> NYStats:
        if "or_high" not in self.df_raw.columns or "tr_sma20" not in self.df_raw.columns:
            df = compute_ny_indicators(self.df_raw)
        else:
            df = self.df_raw

        self.equity_dates.append(df["datetime"].iloc[0])

        for date, day_df in df.groupby("date"):
            trade_count_today = 0
            or_df = day_df[(day_df["hour"] == 13) & (day_df["minute"] >= 30) & (day_df["minute"] < 45)]
            if len(or_df) < cfg.MIN_ORB_BARS:
                continue

            or_high = or_df["high"].max()
            or_low = or_df["low"].min()
            or_range = or_high - or_low
            if or_range <= 0:
                continue

            window = day_df[((day_df["hour"] == 13) & (day_df["minute"] >= 45)) |
                            ((day_df["hour"] > 13) & (day_df["hour"] < 16)) |
                            ((day_df["hour"] == 16) & (day_df["minute"] < 30))].copy()

            if window.empty:
                continue

            n_rows = len(window)
            for i, (_, row) in enumerate(window.iterrows()):
                is_last_bar = (i == n_rows - 1)

                if self.trade_manager.has_open_position:
                    closed = self.trade_manager.update_bar(row, is_last_window_bar=is_last_bar)
                    if closed:
                        self.equity_curve.append(self.trade_manager.current_capital)
                        self.equity_dates.append(row["datetime"])

                if not self.trade_manager.has_open_position:
                    if not getattr(cfg, "ALLOW_REENTRY", False) and trade_count_today >= getattr(cfg, "MAX_TRADES_PER_DAY", 1):
                        continue

                    expansion_ok = True
                    if cfg.USE_EXPANSION_FILTER:
                        tr = row.get("tr_past", row["tr"])
                        tr_sma = row["tr_sma20"]
                        if pd.isna(tr_sma) or tr_sma == 0:
                            expansion_ok = False
                        else:
                            expansion_ok = tr > cfg.EXPANSION_MULT * tr_sma

                    if not expansion_ok:
                        continue

                    htf_col = getattr(cfg, "HTF_COL", "h1_ema50")
                    htf_ema = row.get(htf_col, row.get("h1_ema50", row.get("htf_ema", np.nan)))
                    htf_filter_active = getattr(cfg, "USE_HTF_TREND_FILTER", False) and pd.notna(htf_ema)

                    # Long
                    if row["high"] > or_high:
                        if htf_filter_active and row["close"] < htf_ema:
                            continue
                        entry = or_high
                        risk = or_range
                        sl = entry - risk
                        tp = entry + risk * cfg.TARGET_RR
                        sig = NYSignal(
                            datetime=row["datetime"],
                            direction=Direction.BUY,
                            entry_price=entry,
                            stop_loss=sl,
                            take_profit=tp,
                            initial_risk=risk,
                            or_high=or_high,
                            or_low=or_low,
                            or_range=or_range
                        )
                        self.trade_manager.open_position(sig, capital=self.trade_manager.current_capital)
                        trade_count_today += 1
                        closed = self.trade_manager.update_bar(row, is_last_window_bar=is_last_bar)
                        if closed:
                            self.equity_curve.append(self.trade_manager.current_capital)
                            self.equity_dates.append(row["datetime"])

                    # Short
                    elif row["low"] < or_low:
                        if htf_filter_active and row["close"] > htf_ema:
                            continue
                        entry = or_low
                        risk = or_range
                        sl = entry + risk
                        tp = entry - risk * cfg.TARGET_RR
                        sig = NYSignal(
                            datetime=row["datetime"],
                            direction=Direction.SELL,
                            entry_price=entry,
                            stop_loss=sl,
                            take_profit=tp,
                            initial_risk=risk,
                            or_high=or_high,
                            or_low=or_low,
                            or_range=or_range
                        )
                        self.trade_manager.open_position(sig, capital=self.trade_manager.current_capital)
                        trade_count_today += 1
                        closed = self.trade_manager.update_bar(row, is_last_window_bar=is_last_bar)
                        if closed:
                            self.equity_curve.append(self.trade_manager.current_capital)
                            self.equity_dates.append(row["datetime"])

        self._compute_stats()
        return self.stats

    def _compute_stats(self) -> None:
        trades = self.trades
        st = self.stats

        st.ending_capital = self.trade_manager.current_capital
        st.total_net_pnl_usd = round(st.ending_capital - st.initial_capital, 2)
        st.roi_pct = round((st.total_net_pnl_usd / st.initial_capital) * 100.0, 2)

        st.total_trades = len(trades)
        if st.total_trades == 0:
            return

        wins = [t for t in trades if t.pnl_usd > 0]
        losses = [t for t in trades if t.pnl_usd < 0]
        core_trades = [t for t in trades if t.exit_reason in (ExitReason.TP, ExitReason.SL)]

        st.winning_trades = len(wins)
        st.losing_trades = len(losses)
        st.win_rate = round(len(wins) / st.total_trades * 100.0, 1)

        core_wins = len([t for t in core_trades if t.exit_reason == ExitReason.TP])
        st.core_trades = len(core_trades)
        st.core_win_rate = round(core_wins / len(core_trades) * 100.0, 1) if core_trades else 0.0

        r_multiples = [t.r_multiple for t in trades]
        st.total_r = round(float(np.sum(r_multiples)), 2)
        st.avg_r = round(float(np.mean(r_multiples)), 3)

        gross_profit = sum(t.pnl_usd for t in wins)
        gross_loss = abs(sum(t.pnl_usd for t in losses))
        st.profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 999.0

        pnls = [t.pnl_usd for t in trades]
        st.avg_pnl_usd = round(float(np.mean(pnls)), 2)
        st.avg_win_usd = round(float(np.mean([t.pnl_usd for t in wins])), 2) if wins else 0.0
        st.avg_loss_usd = round(float(np.mean([t.pnl_usd for t in losses])), 2) if losses else 0.0
        st.best_trade_usd = max(pnls) if pnls else 0.0
        st.worst_trade_usd = min(pnls) if pnls else 0.0

        caps = np.array(self.equity_curve)
        peaks = np.maximum.accumulate(caps)
        dds = peaks - caps
        st.max_drawdown_usd = round(float(np.max(dds)), 2) if len(dds) > 0 else 0.0
        dd_pcts = (dds / peaks) * 100.0
        st.max_drawdown_pct = round(float(np.max(dd_pcts)), 2) if len(dd_pcts) > 0 else 0.0

        std_pnl = np.std(pnls, ddof=1) if len(pnls) > 1 else 0.0
        if std_pnl > 0:
            st.sharpe_ratio = round((st.avg_pnl_usd / std_pnl) * np.sqrt(252 * (st.total_trades / (5 * 252))), 2)

        for t in trades:
            st.exit_counts[t.exit_reason.value] = st.exit_counts.get(t.exit_reason.value, 0) + 1

    @property
    def trade_log(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame()
        records = []
        for t in self.trades:
            records.append({
                "entry_datetime": t.signal.datetime,
                "exit_datetime": t.exit_datetime,
                "direction": t.signal.direction.value,
                "entry_price": t.signal.entry_price,
                "exit_price": t.exit_price,
                "stop_loss": t.signal.stop_loss,
                "take_profit": t.signal.take_profit,
                "lot_size": t.signal.lot_size,
                "pnl_usd": t.pnl_usd,
                "pnl_points": t.pnl_points,
                "r_multiple": t.r_multiple,
                "exit_reason": t.exit_reason.value,
                "duration_minutes": t.duration_minutes,
                "mfe_usd": t.mfe_usd,
                "mae_usd": t.mae_usd,
            })
        return pd.DataFrame(records)
