"""
Institutional Tick-Replay Backtesting Engine
============================================
High-fidelity tick-by-tick portfolio backtester for XAU/USD:
1. Asian Mean Reversion (01:00 - 04:30 UTC)
2. London Pit ORB (08:15 - 11:30 UTC)
3. New York ORB (09:30 - 12:30 ET / 13:45 - 16:30 UTC)

Key Institutional Advantages:
- Zero Intrabar Ambiguity: Microsecond-precision resolution of Stop Loss vs Take Profit.
- Real Broker Bid/Ask: BUY fills at actual askPrice, SELL fills at actual bidPrice.
- Dynamic Spread: Spread is never assumed flat; calculated dynamically per tick.
- Slippage & Anti-Chase: Captures real tick gaps and enforces anti-chase limits ($1.69 / $2.84).
- Asymmetric Compounding: Compounding per strategy with dynamic de-risking.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, date, time
from typing import List, Dict, Any, Optional, Tuple
import os
import math
import numpy as np
import pandas as pd

from src.core.types import PortfolioTradeRecord, Direction, ExitReason
from src.data.tick_loader import TickDataset
from src.strategies.portfolio import config as pcfg
from src.strategies.asian_mr import config as acfg
from src.strategies.london_orb import config as lcfg
from src.strategies.ny_orb import config as ny_cfg
from src.execution import config as exec_cfg
from src.strategies.portfolio.engine import PortfolioStats

# Precomputed indicator functions
from src.strategies.asian_mr.signals import compute_asian_indicators, check_entry_signal
from src.strategies.london_orb.signals import compute_london_indicators
from src.strategies.ny_orb.signals import compute_ny_indicators

MAX_SPREAD_USD = getattr(exec_cfg, "MAX_SPREAD_USD", 0.60)
LONDON_MAX_CHASE_USD = getattr(exec_cfg, "LONDON_MAX_CHASE_USD", 1.69)
NY_MAX_CHASE_USD = getattr(exec_cfg, "NY_MAX_CHASE_USD", 2.84)
POINT_VALUE = 100.0


@dataclass
class ActiveTickPosition:
    """Representasi posisi trading aktif dalam simulasi tick."""
    strategy: str               # "ASIAN_MR", "LONDON_ORB", "NY_ORB"
    direction: str              # "BUY" / "SELL" (atau "LONG" / "SHORT")
    entry_datetime: pd.Timestamp
    entry_price: float
    stop_loss: float
    take_profit: Optional[float]
    lot_size: float
    initial_risk: float
    target_rr: float
    entry_ms: int
    mfe_usd: float = 0.0
    mae_usd: float = 0.0


class TickPortfolioEngine:
    """
    Mesin simulasi tick replay multi-strategi XAU/USD beresolusi milidetik.
    """

    def __init__(
        self,
        tick_dataset: TickDataset,
        df_m5: Optional[pd.DataFrame] = None,
        initial_capital: float = pcfg.PORTFOLIO_INITIAL_CAPITAL,
        m5_df: Optional[pd.DataFrame] = None,
        initial_equity: Optional[float] = None,
    ):
        if df_m5 is None and m5_df is not None:
            df_m5 = m5_df
        if initial_equity is not None:
            initial_capital = initial_equity
        if df_m5 is None:
            raise ValueError("df_m5 must be provided")

        self.ds = tick_dataset
        self.df_m5_raw = df_m5.copy()
        self.initial_capital = initial_capital
        self.current_capital = initial_capital

        self.trades: List[PortfolioTradeRecord] = []
        self.equity_curve: List[float] = [initial_capital]
        self.equity_dates: List[pd.Timestamp] = [self.ds.datetimes[0] if len(self.ds.datetimes) > 0 else pd.Timestamp.now(tz="UTC")]
        self.asian_equity: List[float] = [initial_capital]
        self.london_equity: List[float] = [initial_capital]
        self.ny_equity: List[float] = [initial_capital]
        self.asian_cum: float = 0.0
        self.london_cum: float = 0.0
        self.ny_cum: float = 0.0
        self.stats: PortfolioStats = PortfolioStats(initial_capital=initial_capital)

        # Precompute indikator M5 untuk filter & sinyal
        print("      [TickEngine] Mengompilasi indikator M5 (Asia MR, London ORB, NY ORB)...")
        self.df_m5_asian = compute_asian_indicators(self.df_m5_raw)
        self.df_m5_london = compute_london_indicators(self.df_m5_raw)
        self.df_m5_ny = compute_ny_indicators(self.df_m5_raw)

        # Indexing M5 berdasarkan datetime UTC untuk O(1) lookup (pertahankan kolom datetime)
        self.df_m5_asian.set_index("datetime", drop=False, inplace=True)
        self.df_m5_london.set_index("datetime", drop=False, inplace=True)
        self.df_m5_ny.set_index("datetime", drop=False, inplace=True)

        # De-risking tracker
        self.consecutive_losing_days = 0
        self.last_day_pnl = 0.0

    def _calculate_lot(self, risk_points: float, risk_pct: float) -> float:
        if risk_points <= 0:
            return 0.01
        
        effective_risk_pct = risk_pct
        if pcfg.ENABLE_DYNAMIC_DERISKING and self.consecutive_losing_days >= pcfg.DERISKING_CONSECUTIVE_DAYS:
            effective_risk_pct *= 0.5  # Pangkas risiko 50% jika cooling down

        risk_usd = self.current_capital * effective_risk_pct
        raw_lot = risk_usd / (risk_points * POINT_VALUE)
        lot = round(round(raw_lot / 0.01) * 0.01, 2)
        return max(0.01, min(lot, 10.0))

    def run(self) -> PortfolioStats:
        """Eksekusi simulasi seluruh hari trading dari tick dataset."""
        print(f"      [TickEngine] Memulai replay 5.2M+ ticks di modal awal ${self.initial_capital:,.2f} USD...")

        for cur_date in self.ds.unique_dates:
            s_idx, e_idx = self.ds.day_slices[cur_date]
            if s_idx >= e_idx:
                continue

            day_ts = self.ds.timestamps_ms[s_idx:e_idx]
            day_asks = self.ds.asks[s_idx:e_idx]
            day_bids = self.ds.bids[s_idx:e_idx]
            day_spreads = self.ds.spreads[s_idx:e_idx]
            day_dts = self.ds.datetimes[s_idx:e_idx]

            day_start_capital = self.current_capital
            self._simulate_trading_day(cur_date, day_ts, day_asks, day_bids, day_spreads, day_dts)
            day_pnl = self.current_capital - day_start_capital

            # Update dynamic de-risking
            if day_pnl < 0:
                self.consecutive_losing_days += 1
            elif day_pnl > 0:
                self.consecutive_losing_days = 0

        self._compute_portfolio_metrics()
        return self.stats

    def _simulate_trading_day(
        self,
        trading_date: date,
        ts_arr: np.ndarray,
        asks: np.ndarray,
        bids: np.ndarray,
        spreads: np.ndarray,
        dts: pd.DatetimeIndex,
    ):
        """Simulasi pergerakan tick dalam satu hari trading kalender."""
        n_ticks = len(ts_arr)
        if n_ticks == 0:
            return

        # Status sesi harian (1 trade per hari per strategi)
        asian_done = not getattr(pcfg, "ENABLE_ASIAN_MR", True)
        london_done = not getattr(pcfg, "ENABLE_LONDON_ORB", True)
        ny_done = not getattr(pcfg, "ENABLE_STRATEGY_2", True)

        # Opening Range Box states
        # London (08:00 - 08:15 UTC)
        lor_high = -1.0
        lor_low = 1e9
        lor_box_ready = False
        lor_expansion_ok = False
        london_pending_limit: Optional[Tuple[str, float, float, float, float]] = None # dir, limit, sl, tp, lot

        # New York (09:30 - 09:45 ET = 13:30 - 13:45 UTC during EDT)
        ny_high = -1.0
        ny_low = 1e9
        ny_box_ready = False
        ny_expansion_ok = False
        ny_pending_limit: Optional[Tuple[str, float, float, float, float]] = None

        # Posisi aktif per strategi
        active_pos: Dict[str, Optional[ActiveTickPosition]] = {
            "ASIAN_MR": None,
            "LONDON_ORB": None,
            "NY_ORB": None,
        }

        # Cache M5 timestamp untuk Asian MR agar evaluasi hanya terjadi tiap pergantian candle M5
        last_evaluated_m5_asia: Optional[pd.Timestamp] = None

        # Iterasi seluruh tick hari ini
        for i in range(n_ticks):
            t_ms = int(ts_arr[i])
            dt = dts[i]
            ask = float(asks[i])
            bid = float(bids[i])
            spd = float(spreads[i])
            h = dt.hour
            m = dt.minute

            # ──────────────────────────────────────────────────────────
            # 1. EVALUASI POSISI AKTIF (SL / TP / Cutoff / MFE / MAE)
            # ──────────────────────────────────────────────────────────
            for strat_key in ("ASIAN_MR", "LONDON_ORB", "NY_ORB"):
                pos = active_pos[strat_key]
                if pos is None:
                    continue

                # Update MFE / MAE
                if pos.direction in ("BUY", "LONG"):
                    cur_pnl_pts = bid - pos.entry_price
                    pos.mfe_usd = max(pos.mfe_usd, cur_pnl_pts * pos.lot_size * POINT_VALUE)
                    pos.mae_usd = min(pos.mae_usd, cur_pnl_pts * pos.lot_size * POINT_VALUE)
                else:
                    cur_pnl_pts = pos.entry_price - ask
                    pos.mfe_usd = max(pos.mfe_usd, cur_pnl_pts * pos.lot_size * POINT_VALUE)
                    pos.mae_usd = min(pos.mae_usd, cur_pnl_pts * pos.lot_size * POINT_VALUE)

                # Evaluasi Exit per Strategi
                exit_occurred = False
                exit_price = 0.0
                exit_reason = ExitReason.STOP_LOSS

                if strat_key == "LONDON_ORB":
                    if pos.direction == "BUY":
                        if bid <= pos.stop_loss:
                            exit_occurred, exit_price, exit_reason = True, bid, ExitReason.SL
                        elif pos.take_profit and bid >= pos.take_profit:
                            exit_occurred, exit_price, exit_reason = True, pos.take_profit, ExitReason.TP
                        elif (h > 11) or (h == 11 and m >= 30):
                            exit_occurred, exit_price, exit_reason = True, bid, ExitReason.TIME
                    else:
                        if ask >= pos.stop_loss:
                            exit_occurred, exit_price, exit_reason = True, ask, ExitReason.SL
                        elif pos.take_profit and ask <= pos.take_profit:
                            exit_occurred, exit_price, exit_reason = True, pos.take_profit, ExitReason.TP
                        elif (h > 11) or (h == 11 and m >= 30):
                            exit_occurred, exit_price, exit_reason = True, ask, ExitReason.TIME

                elif strat_key == "NY_ORB":
                    if pos.direction == "BUY":
                        if bid <= pos.stop_loss:
                            exit_occurred, exit_price, exit_reason = True, bid, ExitReason.SL
                        elif pos.take_profit and bid >= pos.take_profit:
                            exit_occurred, exit_price, exit_reason = True, pos.take_profit, ExitReason.TP
                        elif (h > 16) or (h == 16 and m >= 30):
                            exit_occurred, exit_price, exit_reason = True, bid, ExitReason.TIME
                    else:
                        if ask >= pos.stop_loss:
                            exit_occurred, exit_price, exit_reason = True, ask, ExitReason.SL
                        elif pos.take_profit and ask <= pos.take_profit:
                            exit_occurred, exit_price, exit_reason = True, pos.take_profit, ExitReason.TP
                        elif (h > 16) or (h == 16 and m >= 30):
                            exit_occurred, exit_price, exit_reason = True, ask, ExitReason.TIME

                elif strat_key == "ASIAN_MR":
                    # Hard SL & TP limit orders
                    duration_min = (dt - pos.entry_datetime).total_seconds() / 60.0
                    if pos.direction in ("BUY", "LONG"):
                        if bid <= pos.stop_loss:
                            exit_occurred, exit_price, exit_reason = True, bid, ExitReason.STOP_LOSS
                        elif pos.take_profit and bid >= pos.take_profit:
                            exit_occurred, exit_price, exit_reason = True, pos.take_profit, ExitReason.TAKE_PROFIT
                        elif duration_min >= acfg.MAX_TRADE_DURATION_MIN:
                            exit_occurred, exit_price, exit_reason = True, bid, ExitReason.TIME_STOP
                        elif (h > 4) or (h == 4 and m >= 30):
                            exit_occurred, exit_price, exit_reason = True, bid, ExitReason.SESSION_CUTOFF
                    else:
                        if ask >= pos.stop_loss:
                            exit_occurred, exit_price, exit_reason = True, ask, ExitReason.STOP_LOSS
                        elif pos.take_profit and ask <= pos.take_profit:
                            exit_occurred, exit_price, exit_reason = True, pos.take_profit, ExitReason.TAKE_PROFIT
                        elif duration_min >= acfg.MAX_TRADE_DURATION_MIN:
                            exit_occurred, exit_price, exit_reason = True, ask, ExitReason.TIME_STOP
                        elif (h > 4) or (h == 4 and m >= 30):
                            exit_occurred, exit_price, exit_reason = True, ask, ExitReason.SESSION_CUTOFF

                    # Z-Neutral & Hard-Cut exit dievaluasi pada boundary M5
                    if not exit_occurred and (m % 5 == 0 and dt.second < 2):
                        # Ambil candle M5 terakhir yang sudah closed
                        m5_closed_dt = dt.floor("5min") - pd.Timedelta(minutes=5)
                        if m5_closed_dt in self.df_m5_asian.index:
                            row_m5 = self.df_m5_asian.loc[m5_closed_dt]
                            z = row_m5.get("zscore", np.nan)
                            if pd.notna(z):
                                if abs(z) >= acfg.Z_HARD_CUT:
                                    exit_occurred = True
                                    exit_price = bid if pos.direction in ("BUY", "LONG") else ask
                                    exit_reason = ExitReason.HARD_CUT_Z
                                elif abs(z) <= acfg.Z_EXIT_THRESHOLD:
                                    exit_occurred = True
                                    exit_price = bid if pos.direction in ("BUY", "LONG") else ask
                                    exit_reason = ExitReason.TAKE_PROFIT_Z

                if exit_occurred:
                    self._close_position(pos, dt, exit_price, exit_reason)
                    active_pos[strat_key] = None

            # ──────────────────────────────────────────────────────────
            # 2. STRATEGI 1: ASIAN MEAN REVERSION (01:00 - 04:30 UTC)
            # ──────────────────────────────────────────────────────────
            if not asian_done and active_pos["ASIAN_MR"] is None:
                if 1 <= h < 4 or (h == 4 and m < 30):
                    # Evaluasi dilakukan persis di pergantian candle M5
                    m5_boundary = dt.floor("5min")
                    if m5_boundary != last_evaluated_m5_asia:
                        last_evaluated_m5_asia = m5_boundary
                        # Ambil candle M5 tertutup sebelumnya (iloc[-2] live equivalent)
                        m5_prev = m5_boundary - pd.Timedelta(minutes=5)
                        if m5_prev in self.df_m5_asian.index:
                            row_m5 = self.df_m5_asian.loc[m5_prev]
                            # Evaluasi sinyal entry
                            sig = check_entry_signal(row_m5, 0)
                            if sig is not None:
                                # Proteksi Spread
                                if spd <= getattr(acfg, "MAX_SPREAD_USD", 0.60):
                                    direction = "BUY" if sig.direction.is_long else "SELL"
                                    fill_price = ask if direction == "BUY" else bid
                                    risk_pts = abs(fill_price - sig.stop_loss)
                                    lot = self._calculate_lot(risk_pts, pcfg.ASIAN_RISK_PCT)

                                    active_pos["ASIAN_MR"] = ActiveTickPosition(
                                        strategy="ASIAN_MR",
                                        direction=direction,
                                        entry_datetime=dt,
                                        entry_price=fill_price,
                                        stop_loss=sig.stop_loss,
                                        take_profit=sig.take_profit,
                                        lot_size=lot,
                                        initial_risk=risk_pts,
                                        target_rr=1.0,
                                        entry_ms=t_ms,
                                    )
                                    asian_done = True

            # ──────────────────────────────────────────────────────────
            # 3. STRATEGI 2: LONDON PIT ORB (08:00 - 11:30 UTC)
            # ──────────────────────────────────────────────────────────
            # A. Pembentukan Opening Range Box (08:00 - 08:15 UTC)
            if h == 8 and m < 15:
                if bid > lor_high:
                    lor_high = bid
                if bid < lor_low:
                    lor_low = bid
            elif h == 8 and m >= 15 and not lor_box_ready:
                # Kunci box OR
                lor_box_ready = True
                or_range = lor_high - lor_low
                # Validasi filter ekspansi M5
                m5_prior = dt.floor("5min") - pd.Timedelta(minutes=5)
                if m5_prior in self.df_m5_london.index:
                    row_lon = self.df_m5_london.loc[m5_prior]
                    tr = row_lon.get("tr_past", row_lon.get("tr", 0.0))
                    tr_sma = row_lon.get("tr_sma20", 0.0)
                    lor_expansion_ok = (tr > lcfg.EXPANSION_MULT * tr_sma) if tr_sma > 0 else False
                else:
                    lor_expansion_ok = True

            # B. Evaluasi Breakout Entry (08:15 - 11:30 UTC)
            if not london_done and active_pos["LONDON_ORB"] is None and lor_box_ready:
                if (h == 8 and m >= 15) or (8 < h < 11) or (h == 11 and m < 30):
                    if lor_expansion_ok and (lor_high > lor_low):
                        or_range = lor_high - lor_low

                        # 1. Cek Pending Limit Order Fill jika ada
                        if london_pending_limit is not None:
                            p_dir, p_limit, p_sl, p_tp, p_lot = london_pending_limit
                            if p_dir == "BUY" and ask <= p_limit:
                                active_pos["LONDON_ORB"] = ActiveTickPosition(
                                    strategy="LONDON_ORB",
                                    direction="BUY",
                                    entry_datetime=dt,
                                    entry_price=p_limit,
                                    stop_loss=p_sl,
                                    take_profit=p_tp,
                                    lot_size=p_lot,
                                    initial_risk=abs(p_limit - p_sl),
                                    target_rr=lcfg.TARGET_RR,
                                    entry_ms=t_ms,
                                )
                                london_done = True
                                london_pending_limit = None
                            elif p_dir == "SELL" and bid >= p_limit:
                                active_pos["LONDON_ORB"] = ActiveTickPosition(
                                    strategy="LONDON_ORB",
                                    direction="SELL",
                                    entry_datetime=dt,
                                    entry_price=p_limit,
                                    stop_loss=p_sl,
                                    take_profit=p_tp,
                                    lot_size=p_lot,
                                    initial_risk=abs(p_limit - p_sl),
                                    target_rr=lcfg.TARGET_RR,
                                    entry_ms=t_ms,
                                )
                                london_done = True
                                london_pending_limit = None

                        # 2. Long Breakout Check
                        elif ask > lor_high and spd <= MAX_SPREAD_USD:
                            chase = ask - lor_high
                            sl = lor_low
                            risk_pts = abs(ask - sl)
                            lot = self._calculate_lot(risk_pts, pcfg.LONDON_RISK_PCT)
                            tp = ask + (or_range * lcfg.TARGET_RR)

                            if chase > LONDON_MAX_CHASE_USD:
                                # Fallback Limit Order
                                limit_price = lor_high + LONDON_MAX_CHASE_USD
                                london_pending_limit = ("BUY", limit_price, sl, tp, lot)
                            else:
                                active_pos["LONDON_ORB"] = ActiveTickPosition(
                                    strategy="LONDON_ORB",
                                    direction="BUY",
                                    entry_datetime=dt,
                                    entry_price=ask,
                                    stop_loss=sl,
                                    take_profit=tp,
                                    lot_size=lot,
                                    initial_risk=risk_pts,
                                    target_rr=lcfg.TARGET_RR,
                                    entry_ms=t_ms,
                                )
                                london_done = True

                        # 3. Short Breakout Check
                        elif bid < lor_low and spd <= MAX_SPREAD_USD:
                            chase = lor_low - bid
                            sl = lor_high
                            risk_pts = abs(bid - sl)
                            lot = self._calculate_lot(risk_pts, pcfg.LONDON_RISK_PCT)
                            tp = bid - (or_range * lcfg.TARGET_RR)

                            if chase > LONDON_MAX_CHASE_USD:
                                limit_price = lor_low - LONDON_MAX_CHASE_USD
                                london_pending_limit = ("SELL", limit_price, sl, tp, lot)
                            else:
                                active_pos["LONDON_ORB"] = ActiveTickPosition(
                                    strategy="LONDON_ORB",
                                    direction="SELL",
                                    entry_datetime=dt,
                                    entry_price=bid,
                                    stop_loss=sl,
                                    take_profit=tp,
                                    lot_size=lot,
                                    initial_risk=risk_pts,
                                    target_rr=lcfg.TARGET_RR,
                                    entry_ms=t_ms,
                                )
                                london_done = True

            # ──────────────────────────────────────────────────────────
            # 4. STRATEGI 3: NEW YORK ORB (13:30 - 16:30 UTC / EDT)
            # ──────────────────────────────────────────────────────────
            # A. Pembentukan Opening Range Box (13:30 - 13:45 UTC)
            if h == 13 and 30 <= m < 45:
                if bid > ny_high:
                    ny_high = bid
                if bid < ny_low:
                    ny_low = bid
            elif h == 13 and m >= 45 and not ny_box_ready:
                ny_box_ready = True
                or_range = ny_high - ny_low
                m5_prior = dt.floor("5min") - pd.Timedelta(minutes=5)
                if m5_prior in self.df_m5_ny.index:
                    row_ny = self.df_m5_ny.loc[m5_prior]
                    tr = row_ny.get("tr_past", row_ny.get("tr", 0.0))
                    tr_sma = row_ny.get("tr_sma20", 0.0)
                    ny_expansion_ok = (tr > ny_cfg.EXPANSION_MULT * tr_sma) if tr_sma > 0 else False
                else:
                    ny_expansion_ok = True

            # B. Evaluasi Breakout Entry (13:45 - 16:30 UTC)
            if not ny_done and active_pos["NY_ORB"] is None and ny_box_ready:
                if (h == 13 and m >= 45) or (13 < h < 16) or (h == 16 and m < 30):
                    if ny_expansion_ok and (ny_high > ny_low):
                        or_range = ny_high - ny_low

                        # 1. Cek Pending Limit Order Fill
                        if ny_pending_limit is not None:
                            p_dir, p_limit, p_sl, p_tp, p_lot = ny_pending_limit
                            if p_dir == "BUY" and ask <= p_limit:
                                active_pos["NY_ORB"] = ActiveTickPosition(
                                    strategy="NY_ORB",
                                    direction="BUY",
                                    entry_datetime=dt,
                                    entry_price=p_limit,
                                    stop_loss=p_sl,
                                    take_profit=p_tp,
                                    lot_size=p_lot,
                                    initial_risk=abs(p_limit - p_sl),
                                    target_rr=ny_cfg.TARGET_RR,
                                    entry_ms=t_ms,
                                )
                                ny_done = True
                                ny_pending_limit = None
                            elif p_dir == "SELL" and bid >= p_limit:
                                active_pos["NY_ORB"] = ActiveTickPosition(
                                    strategy="NY_ORB",
                                    direction="SELL",
                                    entry_datetime=dt,
                                    entry_price=p_limit,
                                    stop_loss=p_sl,
                                    take_profit=p_tp,
                                    lot_size=p_lot,
                                    initial_risk=abs(p_limit - p_sl),
                                    target_rr=ny_cfg.TARGET_RR,
                                    entry_ms=t_ms,
                                )
                                ny_done = True
                                ny_pending_limit = None

                        # 2. Long Breakout
                        elif ask > ny_high and spd <= MAX_SPREAD_USD:
                            chase = ask - ny_high
                            sl = ny_low
                            risk_pts = abs(ask - sl)
                            lot = self._calculate_lot(risk_pts, pcfg.NY_RISK_PCT)
                            tp = ask + (or_range * ny_cfg.TARGET_RR)

                            if chase > NY_MAX_CHASE_USD:
                                limit_price = ny_high + NY_MAX_CHASE_USD
                                ny_pending_limit = ("BUY", limit_price, sl, tp, lot)
                            else:
                                active_pos["NY_ORB"] = ActiveTickPosition(
                                    strategy="NY_ORB",
                                    direction="BUY",
                                    entry_datetime=dt,
                                    entry_price=ask,
                                    stop_loss=sl,
                                    take_profit=tp,
                                    lot_size=lot,
                                    initial_risk=risk_pts,
                                    target_rr=ny_cfg.TARGET_RR,
                                    entry_ms=t_ms,
                                )
                                ny_done = True

                        # 3. Short Breakout
                        elif bid < ny_low and spd <= MAX_SPREAD_USD:
                            chase = ny_low - bid
                            sl = ny_high
                            risk_pts = abs(bid - sl)
                            lot = self._calculate_lot(risk_pts, pcfg.NY_RISK_PCT)
                            tp = bid - (or_range * ny_cfg.TARGET_RR)

                            if chase > NY_MAX_CHASE_USD:
                                limit_price = ny_low - NY_MAX_CHASE_USD
                                ny_pending_limit = ("SELL", limit_price, sl, tp, lot)
                            else:
                                active_pos["NY_ORB"] = ActiveTickPosition(
                                    strategy="NY_ORB",
                                    direction="SELL",
                                    entry_datetime=dt,
                                    entry_price=bid,
                                    stop_loss=sl,
                                    take_profit=tp,
                                    lot_size=lot,
                                    initial_risk=risk_pts,
                                    target_rr=ny_cfg.TARGET_RR,
                                    entry_ms=t_ms,
                                )
                                ny_done = True

        # Tutup posisi aktif yang tersisa di penghujung hari jika ada
        last_dt = dts[-1]
        last_bid = float(bids[-1])
        last_ask = float(asks[-1])
        for strat_key, pos in active_pos.items():
            if pos is not None:
                p_exit = last_bid if pos.direction in ("BUY", "LONG") else last_ask
                self._close_position(pos, last_dt, p_exit, ExitReason.SESSION_CUTOFF)

    def _close_position(
        self,
        pos: ActiveTickPosition,
        exit_dt: pd.Timestamp,
        exit_price: float,
        reason: ExitReason,
    ):
        """Kalkulasi PnL riil, compounding saldo, dan pencatatan trade record."""
        is_buy = pos.direction in ("BUY", "LONG")
        if is_buy:
            pnl_pts = exit_price - pos.entry_price
        else:
            pnl_pts = pos.entry_price - exit_price

        pnl_usd = round(pnl_pts * pos.lot_size * POINT_VALUE, 2)
        duration_min = max(0.1, (exit_dt - pos.entry_datetime).total_seconds() / 60.0)

        record = PortfolioTradeRecord(
            strategy=pos.strategy,
            entry_datetime=pos.entry_datetime,
            exit_datetime=exit_dt,
            direction=pos.direction,
            lot_size=pos.lot_size,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            pnl_usd=pnl_usd,
            pnl_points=round(pnl_pts, 3),
            exit_reason=reason.value if hasattr(reason, "value") else str(reason),
            duration_minutes=round(duration_min, 2),
            mfe_usd=round(pos.mfe_usd, 2),
            mae_usd=round(pos.mae_usd, 2),
        )

        self.trades.append(record)
        self.current_capital += pnl_usd
        if pos.strategy == "ASIAN_MR":
            self.asian_cum += pnl_usd
        elif pos.strategy == "LONDON_ORB":
            self.london_cum += pnl_usd
        elif pos.strategy == "NY_ORB":
            self.ny_cum += pnl_usd

        self.equity_curve.append(self.current_capital)
        self.asian_equity.append(self.initial_capital + self.asian_cum)
        self.london_equity.append(self.initial_capital + self.london_cum)
        self.ny_equity.append(self.initial_capital + self.ny_cum)
        self.equity_dates.append(exit_dt)

    def _compute_portfolio_metrics(self):
        """Kompilasi seluruh metrik kuantitatif dan atribusi portofolio."""
        s = self.stats
        s.initial_capital = self.initial_capital
        s.ending_capital = round(self.current_capital, 2)
        s.total_net_pnl_usd = round(self.current_capital - self.initial_capital, 2)
        s.roi_pct = round((s.total_net_pnl_usd / self.initial_capital) * 100, 2)

        s.total_trades = len(self.trades)
        if s.total_trades == 0:
            return

        wins = [t.pnl_usd for t in self.trades if t.pnl_usd > 0]
        losses = [t.pnl_usd for t in self.trades if t.pnl_usd < 0]

        s.winning_trades = len(wins)
        s.losing_trades = len(losses)
        s.win_rate = round((s.winning_trades / s.total_trades) * 100, 1)

        total_gain = sum(wins) if wins else 0.0
        total_loss = abs(sum(losses)) if losses else 0.0

        s.profit_factor = round(total_gain / total_loss, 2) if total_loss > 0 else 999.0
        s.avg_pnl_usd = round(s.total_net_pnl_usd / s.total_trades, 2)
        s.avg_win_usd = round(sum(wins) / len(wins), 2) if wins else 0.0
        s.avg_loss_usd = round(sum(losses) / len(losses), 2) if losses else 0.0

        all_pnls = [t.pnl_usd for t in self.trades]
        s.best_trade_usd = round(max(all_pnls), 2) if all_pnls else 0.0
        s.worst_trade_usd = round(min(all_pnls), 2) if all_pnls else 0.0

        # Drawdown kalkulasi
        eq = np.array(self.equity_curve)
        peaks = np.maximum.accumulate(eq)
        dds = (peaks - eq) / peaks
        s.max_drawdown_pct = round(float(np.max(dds)) * 100, 2) if len(dds) > 0 else 0.0
        s.max_drawdown_usd = round(float(np.max(peaks - eq)), 2) if len(eq) > 0 else 0.0
        s.avg_drawdown_pct = round(float(np.mean(dds)) * 100, 2) if len(dds) > 0 else 0.0

        # CAGR & Rasio Sharpe
        days = max(1, (self.ds.unique_dates[-1] - self.ds.unique_dates[0]).days)
        years = days / 365.25
        if years > 0 and s.ending_capital > 0:
            s.cagr_pct = round(((s.ending_capital / s.initial_capital) ** (1.0 / years) - 1.0) * 100, 2)

        # Sharpe ratio
        trade_returns = np.array([t.pnl_usd / self.initial_capital for t in self.trades])
        if len(trade_returns) > 1 and np.std(trade_returns) > 0:
            trades_per_year = s.total_trades / max(0.01, years)
            s.daily_sharpe_ratio = round(float((np.mean(trade_returns) / np.std(trade_returns)) * math.sqrt(trades_per_year)), 2)
            neg_ret = trade_returns[trade_returns < 0]
            if len(neg_ret) > 0 and np.std(neg_ret) > 0:
                s.sortino_ratio = round(float((np.mean(trade_returns) / np.std(neg_ret)) * math.sqrt(trades_per_year)), 2)

        if s.max_drawdown_pct > 0:
            s.calmar_ratio = round(s.cagr_pct / s.max_drawdown_pct, 2)

        # Atribusi per strategi
        asia_t = [t for t in self.trades if t.strategy == "ASIAN_MR"]
        lon_t = [t for t in self.trades if t.strategy == "LONDON_ORB"]
        ny_t = [t for t in self.trades if t.strategy == "NY_ORB"]

        s.asian_trades = len(asia_t)
        s.asian_pnl_usd = round(sum(t.pnl_usd for t in asia_t), 2)
        asia_w = [t.pnl_usd for t in asia_t if t.pnl_usd > 0]
        asia_l = [abs(t.pnl_usd) for t in asia_t if t.pnl_usd < 0]
        s.asian_win_rate = round((len(asia_w) / max(1, len(asia_t))) * 100, 1)
        s.asian_pf = round(sum(asia_w) / sum(asia_l), 2) if sum(asia_l) > 0 else 999.0

        s.london_trades = len(lon_t)
        s.london_pnl_usd = round(sum(t.pnl_usd for t in lon_t), 2)
        lon_w = [t.pnl_usd for t in lon_t if t.pnl_usd > 0]
        lon_l = [abs(t.pnl_usd) for t in lon_t if t.pnl_usd < 0]
        s.london_win_rate = round((len(lon_w) / max(1, len(lon_t))) * 100, 1)
        s.london_pf = round(sum(lon_w) / sum(lon_l), 2) if sum(lon_l) > 0 else 999.0

        s.ny_trades = len(ny_t)
        s.ny_pnl_usd = round(sum(t.pnl_usd for t in ny_t), 2)
        ny_w = [t.pnl_usd for t in ny_t if t.pnl_usd > 0]
        ny_l = [abs(t.pnl_usd) for t in ny_t if t.pnl_usd < 0]
        s.ny_win_rate = round((len(ny_w) / max(1, len(ny_t))) * 100, 1)
        s.ny_pf = round(sum(ny_w) / sum(ny_l), 2) if sum(ny_l) > 0 else 999.0

        # Monthly attribution table
        df_t = self.trade_log
        if not df_t.empty:
            df_t["month_str"] = df_t["entry_datetime"].dt.strftime("%Y-%m")
            m_pivot = df_t.pivot_table(index="month_str", columns="strategy", values="pnl_usd", aggfunc="sum", fill_value=0.0)
            for strat_col in ("ASIAN_MR", "LONDON_ORB", "NY_ORB"):
                if strat_col not in m_pivot.columns:
                    m_pivot[strat_col] = 0.0
            m_pivot["TOTAL"] = m_pivot["ASIAN_MR"] + m_pivot["LONDON_ORB"] + m_pivot["NY_ORB"]
            s.monthly_pnl_df = m_pivot

    @property
    def trade_log(self) -> pd.DataFrame:
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
