"""
Asian Mean Reversion Live Execution Engine
==========================================
Sesi: 01:00 - 04:30 UTC
Alokasi Risiko: 1.0%
Model: Statistical Arbitrage / Mean Reversion (Z-Score + RSI Filter)
"""

import sys
from datetime import datetime
from typing import Dict, Any, Optional
import pandas as pd

from configs import live_config as lcfg
from engine.asia.indicators import compute_all as compute_asian_indicators
from engine.asia.signals import (
    check_entry_signal as check_asian_entry,
    Direction as AsianDirection,
)


class AsiaExecutorMixin:
    """Mixin eksekutor sinyal dan sizing Asian Mean Reversion."""

    def _evaluate_asian_mr(self, df_m5: pd.DataFrame, now_utc: datetime, tick: dict, equity: float):
        """Evaluasi sinyal dan eksekusi entri sesi Asia MR."""
        if (
            not lcfg.ENABLE_ASIAN_MR
            or self.trades_today["ASIAN"]
            or self._order_in_flight["ASIAN"]
            or self._reconcile_broker_orders("ASIAN")
        ):
            return

        hm = (now_utc.hour, now_utc.minute)
        sched = self.today_schedule
        if not (sched.get("ASIAN_START", (1, 0)) <= hm < sched.get("ASIAN_END", (4, 30))):
            return

        # Mendukung dynamic mock patch pada live.live_runner.compute_asian_indicators & check_asian_entry
        lr_mod = sys.modules.get("live.live_runner")
        indicator_func = getattr(lr_mod, "compute_asian_indicators", compute_asian_indicators)
        entry_func = getattr(lr_mod, "check_asian_entry", check_asian_entry)

        # Sinyal Asia dievaluasi pada bar M5 yang baru saja selesai (iloc[-2])
        df_asia = indicator_func(df_m5)
        eval_row = df_asia.iloc[-2] if len(df_asia) >= 2 else df_asia.iloc[-1]
        sig = entry_func(eval_row, len(df_asia) - 2)
        if sig is None:
            return

        # Proteksi Spread
        if tick["spread"] > lcfg.MAX_SPREAD_USD:
            return

        risk_usd = equity * lcfg.ASIAN_RISK_PCT
        sl_dist = abs(sig.entry_price - sig.stop_loss)
        if sl_dist <= 0:
            return

        raw_lot = risk_usd / (sl_dist * lcfg.POINT_VALUE)
        lot = max(lcfg.MIN_LOT, min(round(raw_lot / lcfg.LOT_STEP) * lcfg.LOT_STEP, lcfg.MAX_LOT))
        lot = round(lot, 2)

        dir_str = "BUY" if sig.direction == AsianDirection.LONG else "SELL"

        # Validasi TP & Stop Level Broker (P1-006 Safeguard)
        sym_info = self.connector.get_symbol_info(lcfg.SYMBOL)
        point = sym_info.point if sym_info else 0.01
        stops_level = (sym_info.stops_level * point) if sym_info and hasattr(sym_info, "stops_level") else 0.30

        tp_val = sig.take_profit
        if dir_str == "BUY":
            if tp_val is not None and tp_val <= tick["ask"] + stops_level:
                self.logger.warning(f"[⚠️ INVALID TP SAFEGUARD] TP ({tp_val:.2f}) <= Ask+StopLevel ({tick['ask']+stops_level:.2f}). Mengosongkan hard TP di broker, mengandalkan dynamic Z-Neutral exit.")
                tp_val = None
        else:
            if tp_val is not None and tp_val >= tick["bid"] - stops_level:
                self.logger.warning(f"[⚠️ INVALID TP SAFEGUARD] TP ({tp_val:.2f}) >= Bid-StopLevel ({tick['bid']-stops_level:.2f}). Mengosongkan hard TP di broker, mengandalkan dynamic Z-Neutral exit.")
                tp_val = None

        tp_log = f"{tp_val:.2f}" if tp_val is not None else "Dynamic Z-Neutral"
        self.logger.info(f"\n[🚀 SINYAL ASIA MR] {dir_str} {lot} Lot XAU/USD | Entry: {sig.entry_price:.2f} | SL: {sig.stop_loss:.2f} | TP: {tp_log}")

        self._order_in_flight["ASIAN"] = True
        try:
            res = self.connector.open_market_order(
                direction=dir_str,
                volume=lot,
                sl=sig.stop_loss,
                tp=tp_val,
                comment="AsiaMR-FLG"
            )
            self._handle_order_result("ASIAN", res)
        finally:
            self._order_in_flight["ASIAN"] = False
