"""
New York Opening Range Breakout (NY ORB) — Execution Engine & Backtester
=========================================================================
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

from configs import ny_config as cfg
from engine.ny.strategy import NYStrategy, NYSignal, Direction, compute_ny_indicators
from engine.ny.trade_manager import NYTradeManager, NYTrade, ExitReason


@dataclass
class NYStats:
    """Statistik performa strategi New York ORB."""
    initial_capital: float = cfg.INITIAL_CAPITAL
    ending_capital: float = 0.0
    total_net_pnl_usd: float = 0.0
    roi_pct: float = 0.0

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0

    total_r: float = 0.0
    avg_r: float = 0.0
    core_win_rate: float = 0.0
    core_trades: int = 0

    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_usd: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_r: float = 0.0

    avg_pnl_usd: float = 0.0
    avg_win_usd: float = 0.0
    avg_loss_usd: float = 0.0
    best_trade_usd: float = 0.0
    worst_trade_usd: float = 0.0

    exit_counts: Dict[str, int] = field(default_factory=dict)
    monthly_pnl_df: pd.DataFrame = field(default_factory=pd.DataFrame)

    def __str__(self) -> str:
        sep = "=" * 64
        subsep = "-" * 64
        return (
            f"\n{sep}\n"
            f"   NEW YORK OPENING RANGE BREAKOUT (NY ORB) — BACKTEST REPORT\n"
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
        """Eksekusi simulasi New York ORB (M1 Bar Magnifier jika df_m1 tersedia, else M5)."""
        if self.df_m1 is not None:
            return self._run_m1()
        return self._run_m5()

    def _run_m1(self) -> NYStats:
        """Eksekusi presisi sub-bar M1 (Bar Magnifier) dengan setup sinyal M5."""
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

        self._compute_metrics(self.df_raw)
        return self.stats

    def _run_m5(self) -> NYStats:
        """Eksekusi simulasi New York ORB pada dataset M5."""
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

            if self.trade_manager.has_open_position:
                last_row = window.iloc[-1]
                closed = self.trade_manager.update_bar(last_row, is_last_window_bar=True)
                if closed:
                    self.equity_curve.append(self.trade_manager.current_capital)
                    self.equity_dates.append(last_row["datetime"])

        self._compute_metrics(df)
        return self.stats

    def _compute_metrics(self, df: pd.DataFrame):
        """Hitung seluruh metrik statistik kuantitatif."""
        stats = self.stats
        trades = self.trades
        stats.total_trades = len(trades)

        if stats.total_trades == 0:
            stats.ending_capital = stats.initial_capital
            return

        pnls = [t.pnl_usd for t in trades]
        r_mults = [t.r_multiple for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        stats.winning_trades = len(wins)
        stats.losing_trades = len(losses)
        stats.win_rate = (stats.winning_trades / stats.total_trades) * 100.0

        stats.total_r = sum(r_mults)
        stats.avg_r = np.mean(r_mults) if r_mults else 0.0

        core_trades = [t for t in trades if t.exit_reason != ExitReason.TIME]
        stats.core_trades = len(core_trades)
        core_wins = len([t for t in core_trades if t.exit_reason == ExitReason.TP])
        stats.core_win_rate = (core_wins / len(core_trades) * 100.0) if core_trades else 0.0

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

        # Max Drawdown USD & %
        eq_arr = np.array(self.equity_curve)
        peaks = np.maximum.accumulate(eq_arr)
        drawdowns = peaks - eq_arr
        stats.max_drawdown_usd = drawdowns.max()
        if peaks.max() > 0:
            stats.max_drawdown_pct = (stats.max_drawdown_usd / peaks.max()) * 100.0

        # Max Drawdown R
        cum_r = np.cumsum(r_mults)
        peak_r = np.maximum.accumulate(cum_r)
        stats.max_drawdown_r = float((cum_r - peak_r).min())

        # Annualized Sharpe Ratio
        trading_days = max(1, len(df["datetime"].dt.date.unique()))
        trades_per_year = stats.total_trades * (252.0 / trading_days)
        mean_ret = np.mean(pnls)
        std_ret = np.std(pnls, ddof=1)
        stats.sharpe_ratio = (mean_ret / std_ret) * np.sqrt(trades_per_year) if std_ret > 0 else 0.0

        # Exit counts
        reasons = {}
        for t in trades:
            r = t.exit_reason.value
            reasons[r] = reasons.get(r, 0) + 1
        stats.exit_counts = reasons

        # Monthly breakdown
        df_trades = self.trade_log
        if not df_trades.empty:
            df_trades["month"] = df_trades["entry_datetime"].dt.strftime("%Y-%m")
            m_pnl = df_trades.groupby("month")["pnl_usd"].sum().reset_index()
            stats.monthly_pnl_df = m_pnl

    @property
    def trade_log(self) -> pd.DataFrame:
        """Konversi closed trades ke pd.DataFrame."""
        if not self.trades:
            return pd.DataFrame()
        rows = []
        for t in self.trades:
            rows.append({
                "entry_datetime": t.signal.datetime,
                "exit_datetime": t.exit_datetime,
                "direction": t.signal.direction.value,
                "lot_size": t.signal.lot_size,
                "entry_price": t.signal.entry_price,
                "exit_price": t.exit_price,
                "r_multiple": t.r_multiple,
                "pnl_usd": t.pnl_usd,
                "pnl_points": t.pnl_points,
                "exit_reason": t.exit_reason.value,
                "duration_min": t.duration_minutes,
                "mfe_usd": t.mfe_usd,
                "mae_usd": t.mae_usd,
            })
        return pd.DataFrame(rows)
