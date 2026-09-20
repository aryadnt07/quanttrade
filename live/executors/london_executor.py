"""
London Pit Opening Range Breakout (ORB) Live Execution Engine
============================================================
Opening Range: 08:00 - 08:15 UTC
Jendela Entry: 08:15 - 11:30 UTC (Cutoff 11:25 UTC)
Alokasi Risiko: 2.0%
Model: Momentum Breakout dengan Filter Ekspansi Volatilitas (ATR SMA20) & Anti-Chasing
"""

from datetime import datetime
from typing import Dict, Any, Optional
import pandas as pd

from configs import live_config as lcfg


class LondonExecutorMixin:
    """Mixin pembentukan box opening range dan eksekusi London Pit ORB."""

    def _evaluate_london_orb(self, df_m5: pd.DataFrame, now_utc: datetime, tick: dict, equity: float, open_pendings: list):
        """Evaluasi pembentukan box OR dan eksekusi breakout London."""
        if (
            not lcfg.ENABLE_LONDON_ORB
            or self.trades_today["LONDON"]
            or self._order_in_flight["LONDON"]
            or self._reconcile_broker_orders("LONDON")
        ):
            return

        hm = (now_utc.hour, now_utc.minute)
        sched = self.today_schedule

        # 1. Hitung Box Opening Range (08:00 - 08:15 UTC)
        if self.london_or_high is None and hm >= sched.get("LONDON_ENTRY_START", (8, 15)):
            df_day = df_m5[df_m5["datetime"].dt.date == now_utc.date()]
            or_h, or_m = sched.get("LONDON_OR_START", (8, 0))
            lor_bars = df_day[(df_day["datetime"].dt.hour == or_h) & (df_day["datetime"].dt.minute < 15)]
            if len(lor_bars) >= 2:
                self.london_or_high = lor_bars["high"].max()
                self.london_or_low = lor_bars["low"].min()
                self.london_or_range = self.london_or_high - self.london_or_low
                self.logger.info(f"[📦 LONDON OR FORMED] High: {self.london_or_high:.2f} | Low: {self.london_or_low:.2f} | Range: {self.london_or_range:.2f} pts")

        if self.london_or_high is None or self.london_or_range is None or self.london_or_range <= 0:
            return

        # 2. Cek jendela entri (08:15 - 11:30 UTC)
        if not (sched.get("LONDON_ENTRY_START", (8, 15)) <= hm < sched.get("LONDON_ENTRY_END", (11, 30))):
            return

        risk_usd = equity * lcfg.LONDON_RISK_PCT
        risk = self.london_or_range
        raw_lot = risk_usd / (risk * lcfg.POINT_VALUE)
        lot = max(lcfg.MIN_LOT, min(round(raw_lot / lcfg.LOT_STEP) * lcfg.LOT_STEP, lcfg.MAX_LOT))
        lot = round(lot, 2)

        # MODE B: PENDING STOP ORDER OCO (Point #1 Audit)
        if lcfg.BREAKOUT_EXECUTION_MODE == "PENDING_STOP_OCO":
            if not self.pending_orders["LONDON"] and not self.trades_today["LONDON"]:
                self._order_in_flight["LONDON"] = True
                try:
                    self.logger.info("\n[📦 MENANAM STOP ORDER LONDON] Memasang Buy Stop & Sell Stop di server MT5...")
                    bs_sl = self.london_or_low
                    bs_tp = self.london_or_high + risk * lcfg.LONDON_TARGET_RR
                    res_b = self.connector.place_pending_order("BUY_STOP", lot, self.london_or_high, bs_sl, bs_tp, "London-BuyStop")

                    ss_sl = self.london_or_high
                    ss_tp = self.london_or_low - risk * lcfg.LONDON_TARGET_RR
                    res_s = self.connector.place_pending_order("SELL_STOP", lot, self.london_or_low, ss_sl, ss_tp, "London-SellStop")

                    if res_b.success and res_s.success:
                        self.pending_orders["LONDON"] = [res_b.order_id, res_s.order_id]
                        self.logger.info(f"[✓] BUY STOP (Ticket {res_b.order_id}) & SELL STOP (Ticket {res_s.order_id}) AKTIF DI SERVER BROKER!\n")
                    else:
                        self._handle_order_result("LONDON", res_b if not res_b.success else res_s)
                finally:
                    self._order_in_flight["LONDON"] = False
            return

        # MODE A: FAST-TICK BREAKOUT WITH EXPANSION FILTER & ANTI-CHASING (100% Causal)
        prev_close = df_m5["close"].shift(1)
        tr1 = df_m5["high"] - df_m5["low"]
        tr2 = (df_m5["high"] - prev_close).abs()
        tr3 = (df_m5["low"] - prev_close).abs()
        tr_series = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        prior_tr = tr_series.iloc[-2]
        prior_tr_sma20 = tr_series.iloc[:-1].rolling(20).mean().iloc[-1]

        if pd.isna(prior_tr_sma20) or prior_tr_sma20 <= 0 or prior_tr <= lcfg.LONDON_EXPANSION * prior_tr_sma20:
            return

        current_ask = tick["ask"]
        current_bid = tick["bid"]

        # Long Breakout
        if current_ask > self.london_or_high:
            if current_ask > self.london_or_high + lcfg.MAX_CHASE_USD:
                self.logger.warning(f"[🛑 ANTI-CHASING LONDON] Ask {current_ask:.2f} sudah melompat > ${lcfg.MAX_CHASE_USD:.2f} di atas OR High ({self.london_or_high:.2f}). Order dibatalkan demi keamanan!")
                self.trades_today["LONDON"] = True
                return

            if tick["spread"] > lcfg.MAX_SPREAD_USD:
                return

            sl = self.london_or_low
            tp = self.london_or_high + risk * lcfg.LONDON_TARGET_RR
            self.logger.info(f"\n[⚡ BREAKOUT LONDON LONG] Ask {current_ask:.2f} > LOR High {self.london_or_high:.2f} | Lot: {lot} | SL: {sl:.2f} | TP: {tp:.2f}")
            self._order_in_flight["LONDON"] = True
            try:
                res = self.connector.open_market_order("BUY", volume=lot, sl=sl, tp=tp, comment="London-ORB-FLG")
                self._handle_order_result("LONDON", res)
            finally:
                self._order_in_flight["LONDON"] = False

        # Short Breakout
        elif current_bid < self.london_or_low:
            if current_bid < self.london_or_low - lcfg.MAX_CHASE_USD:
                self.logger.warning(f"[🛑 ANTI-CHASING LONDON] Bid {current_bid:.2f} sudah melompat > ${lcfg.MAX_CHASE_USD:.2f} di bawah OR Low ({self.london_or_low:.2f}). Order dibatalkan demi keamanan!")
                self.trades_today["LONDON"] = True
                return

            if tick["spread"] > lcfg.MAX_SPREAD_USD:
                return

            sl = self.london_or_high
            tp = self.london_or_low - risk * lcfg.LONDON_TARGET_RR
            self.logger.info(f"\n[⚡ BREAKOUT LONDON SHORT] Bid {current_bid:.2f} < LOR Low {self.london_or_low:.2f} | Lot: {lot} | SL: {sl:.2f} | TP: {tp:.2f}")
            self._order_in_flight["LONDON"] = True
            try:
                res = self.connector.open_market_order("SELL", volume=lot, sl=sl, tp=tp, comment="London-ORB-FLG")
                self._handle_order_result("LONDON", res)
            finally:
                self._order_in_flight["LONDON"] = False
