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
from typing import Dict, Any, Optional, List
import pandas as pd

from src.execution import config as lcfg
from src.core.types import OrderIntent, ExitIntent, OrderResult
from src.core.interfaces import IBroker, ILiveStrategy
from src.strategies.ny_orb.signals import evaluate_ny_entry, evaluate_ny_exit


class NYLiveStrategy:
    """
    Komponen Strategi Live New York ORB (Pure Strategy Composition).
    Merangkum state internal (or_high, or_low, or_range, pending_orders, trades_today)
    dan penanganan order breakout OCO / fast-tick untuk sesi Wall Street.
    """

    def __init__(self, logger=None):
        self._strategy_id = "NY"
        self._name = "New York ORB"
        self._magic_number = lcfg.MAGIC_NUMBER
        self.trades_today = False
        self.order_in_flight = False
        self.retry_count = 0
        self.or_high: Optional[float] = None
        self.or_low: Optional[float] = None
        self.or_range: Optional[float] = None
        self.pending_orders: List[int] = []
        self.logger = logger

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def magic_number(self) -> int:
        return self._magic_number

    def can_trade(self) -> bool:
        """Cek kelayakan eksekusi strategi New York."""
        return lcfg.ENABLE_NY_ORB and not self.trades_today and not self.order_in_flight

    def on_daily_reset(self, today_date: Any, schedule: Dict[str, Any]) -> None:
        """Reset state box opening range dan counter harian."""
        self.trades_today = False
        self.order_in_flight = False
        self.retry_count = 0
        self.or_high = None
        self.or_low = None
        self.or_range = None
        self.pending_orders = []

    def reconcile_broker_orders(self, broker: IBroker, magic_number: int) -> bool:
        """Periksa apakah posisi/deal New York sudah aktif atau selesai di broker."""
        open_pos = broker.get_open_positions(magic_number)
        for p in open_pos:
            comm = getattr(p, "comment", "") or ""
            if "NY" in comm:
                if self.logger:
                    self.logger.warning(f"[🛡️ RECONCILIATION MATCH] Posisi NY (Ticket {p.ticket}) sudah aktif di broker!")
                self.trades_today = True
                self.retry_count = 0
                return True

        if hasattr(broker, "get_today_deals"):
            today_deals = broker.get_today_deals(magic_number)
            for d in today_deals:
                comm = getattr(d, "comment", "") or ""
                if "NY" in comm:
                    if self.logger:
                        self.logger.warning(f"[🛡️ RECONCILIATION MATCH] Deal NY (Ticket {d.ticket}) sudah tercatat di history broker!")
                    self.trades_today = True
                    self.retry_count = 0
                    return True

        if hasattr(broker, "get_open_pending_orders"):
            open_pendings = broker.get_open_pending_orders(magic_number)
            for o in open_pendings:
                comm = getattr(o, "comment", "") or ""
                if "NY" in comm and o.ticket not in self.pending_orders:
                    self.pending_orders.append(o.ticket)

        return False

    def handle_oco(self, open_positions: List[Any], open_pendings: List[Any], broker: IBroker) -> None:
        """Jika salah satu order stop NY terpicu, batalkan pending order seberangnya."""
        for pos in open_positions:
            comm = getattr(pos, "comment", "") or ""
            if "NY" in comm:
                for pend in open_pendings:
                    pend_comm = getattr(pend, "comment", "") or ""
                    if "NY" in pend_comm:
                        if self.logger:
                            self.logger.info(f"[⚡ OCO TRIGGERED] Posisi NY aktif (Ticket {pos.ticket}). Membatalkan Pending Order Ticket {pend.ticket}...")
                        broker.cancel_pending_order(pend.ticket)
                        self.trades_today = True
                        self.pending_orders = [t for t in self.pending_orders if t != pend.ticket]

    def evaluate_entry(
        self,
        df_m5: pd.DataFrame,
        tick: Dict[str, Any],
        equity: float,
        now_utc: datetime,
        schedule: Dict[str, Any],
        open_pendings: Optional[List[Any]] = None,
        broker: Optional[IBroker] = None,
    ) -> Optional[OrderIntent]:
        """Evaluasi pembentukan box Opening Range New York dan kondisi breakout."""
        if not self.can_trade():
            return None

        hm = (now_utc.hour, now_utc.minute)
        sched = schedule

        # 1. Hitung Box Opening Range New York (09:30 - 09:45 NY Local)
        if self.or_high is None and hm >= sched.get("NY_ENTRY_START", (14, 45)):
            df_day = df_m5[df_m5["datetime"].dt.date == now_utc.date()]
            or_h, or_m = sched.get("NY_OR_START", (14, 30))
            or_bars = df_day[(df_day["datetime"].dt.hour == or_h) & (df_day["datetime"].dt.minute >= or_m) & (df_day["datetime"].dt.minute < or_m + 15)]
            if len(or_bars) >= 2:
                self.or_high = or_bars["high"].max()
                self.or_low = or_bars["low"].min()
                self.or_range = self.or_high - self.or_low
                if self.logger:
                    self.logger.info(f"[📦 NY OR FORMED ({sched.get('NY_TZ_NAME', 'UTC')})] High: {self.or_high:.2f} | Low: {self.or_low:.2f} | Range: {self.or_range:.2f} pts")

        if self.or_high is None or self.or_range is None or self.or_range <= 0:
            return None

        # 2. Cek jendela entri (09:45 - 12:30 NY Local)
        if not (sched.get("NY_ENTRY_START", (14, 45)) <= hm < sched.get("NY_ENTRY_END", (17, 30))):
            return None

        risk_usd = equity * lcfg.NY_RISK_PCT
        risk = self.or_range
        raw_lot = risk_usd / (risk * lcfg.POINT_VALUE)
        lot = max(lcfg.MIN_LOT, min(round(raw_lot / lcfg.LOT_STEP) * lcfg.LOT_STEP, lcfg.MAX_LOT))
        lot = round(lot, 2)

        # MODE B: PENDING STOP ORDER OCO
        if lcfg.BREAKOUT_EXECUTION_MODE == "PENDING_STOP_OCO":
            if not self.pending_orders and not self.trades_today and broker:
                self.order_in_flight = True
                try:
                    if self.logger:
                        self.logger.info("\n[📦 MENANAM STOP ORDER NY] Memasang Buy Stop & Sell Stop di server MT5...")
                    bs_sl = self.or_low
                    bs_tp = self.or_high + risk * lcfg.NY_TARGET_RR
                    res_b = broker.place_pending_order("BUY_STOP", lot, self.or_high, bs_sl, bs_tp, "NY-BuyStop")

                    ss_sl = self.or_high
                    ss_tp = self.or_low - risk * lcfg.NY_TARGET_RR
                    res_s = broker.place_pending_order("SELL_STOP", lot, self.or_low, ss_sl, ss_tp, "NY-SellStop")

                    if res_b.success and res_s.success:
                        self.pending_orders = [res_b.order_id, res_s.order_id]
                        if self.logger:
                            self.logger.info(f"[✓] BUY STOP (Ticket {res_b.order_id}) & SELL STOP (Ticket {res_s.order_id}) AKTIF DI SERVER BROKER!\n")
                    else:
                        self.on_order_result(res_b if not res_b.success else res_s, broker)
                finally:
                    self.order_in_flight = False
            return None

        # MODE A: FAST-TICK BREAKOUT VIA STRATEGY DOMAIN EVALUATION
        eval_result = evaluate_ny_entry(
            df_m5=df_m5,
            tick=tick,
            equity=equity,
            now_utc=now_utc,
            sched=sched,
            or_high=self.or_high,
            or_low=self.or_low,
            or_range=self.or_range,
            risk_pct=lcfg.NY_RISK_PCT,
            point_value=lcfg.POINT_VALUE,
            lot_step=lcfg.LOT_STEP,
            min_lot=lcfg.MIN_LOT,
            max_lot=lcfg.MAX_LOT,
            max_spread=lcfg.MAX_SPREAD_USD,
            max_chase=lcfg.MAX_CHASE_USD,
            target_rr=lcfg.NY_TARGET_RR,
            expansion_mult=lcfg.NY_EXPANSION,
        )
        if eval_result is None:
            return None

        if eval_result["status"] == "CHASE_BLOCKED":
            if self.logger:
                self.logger.warning(f"[🛑 ANTI-CHASING NY] {eval_result['message']}")
            self.trades_today = True
            return None

        if eval_result["status"] == "SPREAD_BLOCKED":
            return None

        if eval_result["status"] == "VALID" and eval_result.get("intent"):
            return eval_result["intent"]

        return None

    def evaluate_exit(
        self,
        position: Any,
        df_m5: pd.DataFrame,
        now_utc: datetime,
        broker_utc_offset_sec: int = 0,
        schedule: Optional[Dict[str, Any]] = None,
    ) -> Optional[ExitIntent]:
        """Evaluasi kondisi keluar khusus New York ORB (Session Cutoff 12:25 NY Local)."""
        comm = getattr(position, "comment", "") or ""
        if "NY" not in comm:
            return None

        sched = schedule or {}
        return evaluate_ny_exit(
            position=position,
            now_utc=now_utc,
            cutoff_hm=sched.get("NY_CUTOFF", (12, 25)),
        )

    def on_order_result(self, res: OrderResult, broker: Optional[IBroker] = None) -> None:
        """Callback penanganan hasil eksekusi order New York."""
        if res.success:
            if self.logger:
                self.logger.info(f"[✓] ORDER NY BERHASIL! Ticket: {res.order_id} @ {res.price}\n")
            self.trades_today = True
            self.retry_count = 0
        else:
            if broker and self.reconcile_broker_orders(broker, self.magic_number):
                return
            self.retry_count += 1
            if self.logger:
                self.logger.error(f"[X] ORDER NY GAGAL ({self.retry_count}/{lcfg.MAX_SESSION_RETRIES}): {res.comment}")
            if self.retry_count >= lcfg.MAX_SESSION_RETRIES:
                if self.logger:
                    self.logger.warning(f"[🔒 SESI DILOCKOUT] Batas maksimal percobaan tercapai. Sesi NY dikunci hari ini.")
                self.trades_today = True


class NYExecutorMixin:
    """Mixin delegator untuk kompatibilitas mundur (Legacy Adapter)."""

    def _evaluate_ny_orb(self, df_m5: pd.DataFrame, now_utc: datetime, tick: dict, equity: float, open_pendings: list):
        """Evaluasi pembentukan box OR dan eksekusi breakout New York."""
        strat = getattr(self, "_ny_strategy", None)
        if strat is None:
            if not hasattr(self, "_fallback_ny_strat"):
                self._fallback_ny_strat = NYLiveStrategy(logger=getattr(self, "logger", None))
            strat = self._fallback_ny_strat
            strat.trades_today = self.trades_today.get("NY", False)
            strat.order_in_flight = self._order_in_flight.get("NY", False)
            strat.or_high = getattr(self, "ny_or_high", None)
            strat.or_low = getattr(self, "ny_or_low", None)
            strat.or_range = getattr(self, "ny_or_range", None)
            strat.pending_orders = getattr(self, "pending_orders", {}).get("NY", [])

        if not strat.can_trade() or self._reconcile_broker_orders("NY"):
            return

        intent = strat.evaluate_entry(
            df_m5=df_m5,
            tick=tick,
            equity=equity,
            now_utc=now_utc,
            schedule=self.today_schedule,
            open_pendings=open_pendings,
            broker=self.connector,
        )
        self.ny_or_high = strat.or_high
        self.ny_or_low = strat.or_low
        self.ny_or_range = strat.or_range

        if intent is None:
            return

        dir_str = intent.action
        tag = "LONG" if dir_str == "BUY" else "SHORT"
        cmp_price = tick["ask"] if dir_str == "BUY" else tick["bid"]
        comp_sym = ">" if dir_str == "BUY" else "<"
        ref_level = strat.or_high if dir_str == "BUY" else strat.or_low
        self.logger.info(f"\n[⚡ BREAKOUT NY {tag}] Price {cmp_price:.2f} {comp_sym} NY {ref_level:.2f} | Lot: {intent.volume} | SL: {intent.stop_loss:.2f} | TP: {intent.take_profit:.2f}")

        self._order_in_flight["NY"] = True
        strat.order_in_flight = True
        try:
            res = self.connector.open_market_order(
                direction=intent.action,
                volume=intent.volume,
                sl=intent.stop_loss,
                tp=intent.take_profit,
                comment=intent.comment,
            )
            self._handle_order_result("NY", res)
            strat.on_order_result(res, self.connector)
        finally:
            self._order_in_flight["NY"] = False
            strat.order_in_flight = False
