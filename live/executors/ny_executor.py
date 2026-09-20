"""
New York Opening Range Breakout (ORB) Live Execution Engine
===========================================================
Opening Range: 09:30 - 09:45 NY Local Time (Dynamic DST Wall Street)
Jendela Entry: 09:45 - 12:30 NY Local Time (Cutoff 12:25 / 16:25 UTC)
Alokasi Risiko: 2.0%
Target Reward:Risk: 2.0R
Model: US Equities Open Momentum Breakout dengan Filter Ekspansi & Anti-Chasing
"""

from datetime import datetime
from typing import Dict, Any, Optional
import pandas as pd

from configs import live_config as lcfg


class NYExecutorMixin:
    """Mixin pembentukan box opening range dan eksekusi New York ORB."""

    def _evaluate_ny_orb(self, df_m5: pd.DataFrame, now_utc: datetime, tick: dict, equity: float, open_pendings: list):
        """Evaluasi pembentukan box OR dan eksekusi breakout New York."""
        if (
            not lcfg.ENABLE_NY_ORB
            or self.trades_today["NY"]
            or self._order_in_flight["NY"]
            or self._reconcile_broker_orders("NY")
        ):
            return

        hm = (now_utc.hour, now_utc.minute)
        sched = self.today_schedule

        # 1. Hitung Box Opening Range New York (09:30 - 09:45 NY Local)
        if self.ny_or_high is None and hm >= sched.get("NY_ENTRY_START", (14, 45)):
            df_day = df_m5[df_m5["datetime"].dt.date == now_utc.date()]
            or_h, or_m = sched.get("NY_OR_START", (14, 30))
            or_bars = df_day[(df_day["datetime"].dt.hour == or_h) & (df_day["datetime"].dt.minute >= or_m) & (df_day["datetime"].dt.minute < or_m + 15)]
            if len(or_bars) >= 2:
                self.ny_or_high = or_bars["high"].max()
                self.ny_or_low = or_bars["low"].min()
                self.ny_or_range = self.ny_or_high - self.ny_or_low
                self.logger.info(f"[📦 NY OR FORMED ({sched.get('NY_TZ_NAME', 'UTC')})] High: {self.ny_or_high:.2f} | Low: {self.ny_or_low:.2f} | Range: {self.ny_or_range:.2f} pts")

        if self.ny_or_high is None or self.ny_or_range is None or self.ny_or_range <= 0:
            return

        # 2. Cek jendela entri (09:45 - 12:30 NY Local)
        if not (sched.get("NY_ENTRY_START", (14, 45)) <= hm < sched.get("NY_ENTRY_END", (17, 30))):
            return

        risk_usd = equity * lcfg.NY_RISK_PCT
        risk = self.ny_or_range
        raw_lot = risk_usd / (risk * lcfg.POINT_VALUE)
        lot = max(lcfg.MIN_LOT, min(round(raw_lot / lcfg.LOT_STEP) * lcfg.LOT_STEP, lcfg.MAX_LOT))
        lot = round(lot, 2)

        # MODE B: PENDING STOP ORDER OCO (Point #1 Audit)
        if lcfg.BREAKOUT_EXECUTION_MODE == "PENDING_STOP_OCO":
            if not self.pending_orders["NY"] and not self.trades_today["NY"]:
                self._order_in_flight["NY"] = True
                try:
                    self.logger.info("\n[📦 MENANAM STOP ORDER NY] Memasang Buy Stop & Sell Stop di server MT5...")
                    bs_sl = self.ny_or_low
                    bs_tp = self.ny_or_high + risk * lcfg.NY_TARGET_RR
                    res_b = self.connector.place_pending_order("BUY_STOP", lot, self.ny_or_high, bs_sl, bs_tp, "NY-BuyStop")

                    ss_sl = self.ny_or_high
                    ss_tp = self.ny_or_low - risk * lcfg.NY_TARGET_RR
                    res_s = self.connector.place_pending_order("SELL_STOP", lot, self.ny_or_low, ss_sl, ss_tp, "NY-SellStop")

                    if res_b.success and res_s.success:
                        self.pending_orders["NY"] = [res_b.order_id, res_s.order_id]
                        self.logger.info(f"[✓] BUY STOP (Ticket {res_b.order_id}) & SELL STOP (Ticket {res_s.order_id}) AKTIF DI SERVER BROKER!\n")
                    else:
                        self._handle_order_result("NY", res_b if not res_b.success else res_s)
                finally:
                    self._order_in_flight["NY"] = False
            return

        # MODE A: FAST-TICK BREAKOUT WITH EXPANSION FILTER & ANTI-CHASING (100% Causal)
        prev_close = df_m5["close"].shift(1)
        tr1 = df_m5["high"] - df_m5["low"]
        tr2 = (df_m5["high"] - prev_close).abs()
        tr3 = (df_m5["low"] - prev_close).abs()
        tr_series = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        prior_tr = tr_series.iloc[-2]
        prior_tr_sma20 = tr_series.iloc[:-1].rolling(20).mean().iloc[-1]

        if pd.isna(prior_tr_sma20) or prior_tr_sma20 <= 0 or prior_tr <= lcfg.NY_EXPANSION * prior_tr_sma20:
            return

        current_ask = tick["ask"]
        current_bid = tick["bid"]

        # Long Breakout
        if current_ask > self.ny_or_high:
            if current_ask > self.ny_or_high + lcfg.MAX_CHASE_USD:
                self.logger.warning(f"[🛑 ANTI-CHASING NY] Ask {current_ask:.2f} sudah melompat > ${lcfg.MAX_CHASE_USD:.2f} di atas NY High ({self.ny_or_high:.2f}). Order dibatalkan demi keamanan!")
                self.trades_today["NY"] = True
                return

            if tick["spread"] > lcfg.MAX_SPREAD_USD:
                return

            sl = self.ny_or_low
            tp = self.ny_or_high + risk * lcfg.NY_TARGET_RR
            self.logger.info(f"\n[⚡ BREAKOUT NY LONG] Ask {current_ask:.2f} > NY High {self.ny_or_high:.2f} | Lot: {lot} | SL: {sl:.2f} | TP: {tp:.2f}")
            self._order_in_flight["NY"] = True
            try:
                res = self.connector.open_market_order("BUY", volume=lot, sl=sl, tp=tp, comment="NY-ORB-FLG")
                self._handle_order_result("NY", res)
            finally:
                self._order_in_flight["NY"] = False

        # Short Breakout
        elif current_bid < self.ny_or_low:
            if current_bid < self.ny_or_low - lcfg.MAX_CHASE_USD:
                self.logger.warning(f"[🛑 ANTI-CHASING NY] Bid {current_bid:.2f} sudah melompat > ${lcfg.MAX_CHASE_USD:.2f} di bawah NY Low ({self.ny_or_low:.2f}). Order dibatalkan demi keamanan!")
                self.trades_today["NY"] = True
                return

            if tick["spread"] > lcfg.MAX_SPREAD_USD:
                return

            sl = self.ny_or_high
            tp = self.ny_or_low - risk * lcfg.NY_TARGET_RR
            self.logger.info(f"\n[⚡ BREAKOUT NY SHORT] Bid {current_bid:.2f} < NY Low {self.ny_or_low:.2f} | Lot: {lot} | SL: {sl:.2f} | TP: {tp:.2f}")
            self._order_in_flight["NY"] = True
            try:
                res = self.connector.open_market_order("SELL", volume=lot, sl=sl, tp=tp, comment="NY-ORB-FLG")
                self._handle_order_result("NY", res)
            finally:
                self._order_in_flight["NY"] = False
