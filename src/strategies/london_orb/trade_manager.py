"""
London Pit Opening Range Breakout (London Pit ORB) — Trade Manager
===================================================================
Pengelola siklus posisi trading London Pit ORB:
- Pelacakan TP (2.0R), SL (-1.0R), dan TIME exit (11:30 UTC)
- Perhitungan R-Multiple dan PnL dolar riil dengan sizing institusional
- Pemantauan durasi dan evaluasi exit
"""

from dataclasses import dataclass
from typing import Optional, List
import pandas as pd

from src.core.types import ExitReason, Direction
from . import config as cfg
from .signals import LondonSignal


@dataclass
class LondonTrade:
    """Record hasil penutupan posisi London Pit ORB."""
    signal: LondonSignal
    exit_datetime: pd.Timestamp
    exit_price: float
    exit_reason: ExitReason
    r_multiple: float
    pnl_usd: float
    pnl_points: float
    duration_minutes: float
    mfe_usd: float = 0.0
    mae_usd: float = 0.0


class LondonTradeManager:
    """Manajer posisi aktif untuk strategi London Pit ORB."""

    def __init__(self, current_capital: float = cfg.INITIAL_CAPITAL):
        self.current_capital = current_capital
        self.active_signal: Optional[LondonSignal] = None
        self.duration_minutes: float = 0.0
        self.mfe_usd: float = 0.0
        self.mae_usd: float = 0.0
        self.closed_trades: List[LondonTrade] = []

    @property
    def has_open_position(self) -> bool:
        return self.active_signal is not None

    def calculate_lot(self, risk_points: float, capital: float, risk_pct: Optional[float] = None) -> float:
        if risk_points <= 0:
            return cfg.MIN_LOT

        if risk_pct is not None:
            risk_usd = capital * risk_pct
        else:
            risk_usd = cfg.FIXED_RISK_USD

        raw_lot = risk_usd / (risk_points * cfg.POINT_VALUE)
        step = cfg.LOT_STEP
        lot = round(round(raw_lot / step) * step, 2)
        return max(cfg.MIN_LOT, min(lot, cfg.MAX_LOT))

    def open_position(self, signal: LondonSignal, capital: Optional[float] = None, risk_pct: Optional[float] = None) -> None:
        cap = capital if capital is not None else self.current_capital
        signal.lot_size = self.calculate_lot(signal.initial_risk, cap, risk_pct)

        self.active_signal = signal
        self.duration_minutes = 0.0
        self.mfe_usd = 0.0
        self.mae_usd = 0.0

    def update_bar(self, row: pd.Series, is_last_window_bar: bool = False) -> Optional[LondonTrade]:
        if not self.has_open_position:
            return None

        sig = self.active_signal
        bar_dt = row["datetime"]
        h = row["high"]
        l = row["low"]
        c = row["close"]
        if pd.notna(bar_dt) and pd.notna(sig.datetime):
            self.duration_minutes = (bar_dt - sig.datetime).total_seconds() / 60.0
        else:
            self.duration_minutes += 1.0

        # Update MFE / MAE
        if sig.direction == Direction.BUY:
            self.mfe_usd = max(self.mfe_usd, (h - sig.entry_price) * sig.lot_size * cfg.POINT_VALUE)
            self.mae_usd = min(self.mae_usd, (l - sig.entry_price) * sig.lot_size * cfg.POINT_VALUE)
        else:
            self.mfe_usd = max(self.mfe_usd, (sig.entry_price - l) * sig.lot_size * cfg.POINT_VALUE)
            self.mae_usd = min(self.mae_usd, (sig.entry_price - h) * sig.lot_size * cfg.POINT_VALUE)

        # 1. Evaluasi SL & TP
        if sig.direction == Direction.BUY:
            if l <= sig.stop_loss:
                return self._close_position(bar_dt, sig.stop_loss, ExitReason.SL, -1.0)
            elif h >= sig.take_profit:
                return self._close_position(bar_dt, sig.take_profit, ExitReason.TP, cfg.TARGET_RR)
        else:
            ask_h = h + getattr(cfg, "SPREAD_USD", 0.30)
            ask_l = l + getattr(cfg, "SPREAD_USD", 0.30)
            if ask_h >= sig.stop_loss:
                return self._close_position(bar_dt, sig.stop_loss, ExitReason.SL, -1.0)
            elif ask_l <= sig.take_profit:
                return self._close_position(bar_dt, sig.take_profit, ExitReason.TP, cfg.TARGET_RR)

        # 2. Evaluasi Time Cutoff (11:30 UTC)
        if is_last_window_bar:
            move = (c - sig.entry_price) if sig.direction == Direction.BUY else (sig.entry_price - c)
            r_mult = move / sig.initial_risk if sig.initial_risk > 0 else 0.0
            return self._close_position(bar_dt, c, ExitReason.TIME, r_mult)

        return None

    def _close_position(self, exit_dt: pd.Timestamp, exit_price: float, reason: ExitReason, r_multiple: float) -> LondonTrade:
        sig = self.active_signal
        spread_deduction = cfg.SPREAD_USD

        if sig.direction == Direction.BUY:
            pnl_pts = exit_price - sig.entry_price - spread_deduction
        else:
            pnl_pts = sig.entry_price - exit_price - spread_deduction

        pnl_usd = round(pnl_pts * sig.lot_size * cfg.POINT_VALUE, 2)

        trade = LondonTrade(
            signal=sig,
            exit_datetime=exit_dt,
            exit_price=exit_price,
            exit_reason=reason,
            r_multiple=round(r_multiple, 3),
            pnl_usd=pnl_usd,
            pnl_points=round(pnl_pts, 3),
            duration_minutes=self.duration_minutes,
            mfe_usd=round(self.mfe_usd, 2),
            mae_usd=round(self.mae_usd, 2)
        )

        self.closed_trades.append(trade)
        self.current_capital += pnl_usd
        self.active_signal = None
        return trade
