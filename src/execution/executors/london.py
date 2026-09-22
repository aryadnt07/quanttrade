"""
London Pit Opening Range Breakout (ORB) Live Execution Engine
============================================================
Opening Range: 08:00 - 08:15 UTC
Jendela Entry: 08:15 - 11:30 UTC (Cutoff 11:25 UTC)
Alokasi Risiko: 2.0%
Model: Momentum Breakout dengan Filter Ekspansi Volatilitas (ATR SMA20) & Anti-Chasing
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
import pandas as pd

from src.execution import config as lcfg
from src.core.types import OrderIntent, ExitIntent, OrderResult
from src.core.interfaces import IBroker, ILiveStrategy
from src.strategies.london_orb.signals import evaluate_london_entry, evaluate_london_exit


class LondonLiveStrategy:
    """
    Komponen Strategi Live London Pit ORB (Pure Strategy Composition).
    Merangkum state internal (or_high, or_low, or_range, pending_orders, trades_today)
    dan penanganan order breakout OCO / fast-tick.
    """

    def __init__(self, logger=None):
        self._strategy_id = "LONDON"
        self._name = "London Pit ORB"
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
        """Cek kelayakan eksekusi strategi."""
        return lcfg.ENABLE_LONDON_ORB and not self.trades_today and not self.order_in_flight

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
        """Periksa apakah posisi/deal London sudah aktif atau selesai di broker."""
        open_pos = broker.get_open_positions(magic_number)
        for p in open_pos:
            comm = getattr(p, "comment", "") or ""
            if "London" in comm:
                if self.logger:
                    self.logger.warning(f"[🛡️ RECONCILIATION MATCH] Posisi LONDON (Ticket {p.ticket}) sudah aktif di broker!")
                self.trades_today = True
                self.retry_count = 0
                return True

        if hasattr(broker, "get_today_deals"):
            today_deals = broker.get_today_deals(magic_number)
            for d in today_deals:
                comm = getattr(d, "comment", "") or ""
                if "London" in comm:
                    if self.logger:
                        self.logger.warning(f"[🛡️ RECONCILIATION MATCH] Deal LONDON (Ticket {d.ticket}) sudah tercatat di history broker!")
                    self.trades_today = True
                    self.retry_count = 0
                    return True

        if hasattr(broker, "get_open_pending_orders"):
            open_pendings = broker.get_open_pending_orders(magic_number)
            for o in open_pendings:
                comm = getattr(o, "comment", "") or ""
                if "London" in comm and o.ticket not in self.pending_orders:
                    self.pending_orders.append(o.ticket)

        return False

    def handle_oco(self, open_positions: List[Any], open_pendings: List[Any], broker: IBroker) -> None:
        """Jika salah satu order stop London terpicu, batalkan pending order seberangnya."""
        for pos in open_positions:
            comm = getattr(pos, "comment", "") or ""
            if "London" in comm:
                for pend in open_pendings:
                    pend_comm = getattr(pend, "comment", "") or ""
                    if "London" in pend_comm:
                        if self.logger:
                            self.logger.info(f"[⚡ OCO TRIGGERED] Posisi London aktif (Ticket {pos.ticket}). Membatalkan Pending Order Ticket {pend.ticket}...")
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
        """Evaluasi pembentukan box Opening Range dan kondisi breakout London."""
        if not self.can_trade():
            return None

        hm = (now_utc.hour, now_utc.minute)
        sched = schedule

        # 1. Hitung Box Opening Range (08:00 - 08:15 UTC)
        if self.or_high is None and hm >= sched.get("LONDON_ENTRY_START", (8, 15)):
            df_day = df_m5[df_m5["datetime"].dt.date == now_utc.date()]
            or_h, or_m = sched.get("LONDON_OR_START", (8, 0))
            lor_bars = df_day[(df_day["datetime"].dt.hour == or_h) & (df_day["datetime"].dt.minute < 15)]
            if len(lor_bars) >= 2:
                self.or_high = lor_bars["high"].max()
                self.or_low = lor_bars["low"].min()
                self.or_range = self.or_high - self.or_low
                if self.logger:
                    self.logger.info(f"[📦 LONDON OR FORMED] High: {self.or_high:.2f} | Low: {self.or_low:.2f} | Range: {self.or_range:.2f} pts")

        if self.or_high is None or self.or_range is None or self.or_range <= 0:
            return None

        # 2. Cek jendela entri (08:15 - 11:30 UTC)
        if not (sched.get("LONDON_ENTRY_START", (8, 15)) <= hm < sched.get("LONDON_ENTRY_END", (11, 30))):
            return None

        risk_usd = equity * lcfg.LONDON_RISK_PCT
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
                        self.logger.info("\n[📦 MENANAM STOP ORDER LONDON] Memasang Buy Stop & Sell Stop di server MT5...")
                    bs_sl = self.or_low
                    bs_tp = self.or_high + risk * lcfg.LONDON_TARGET_RR
                    res_b = broker.place_pending_order("BUY_STOP", lot, self.or_high, bs_sl, bs_tp, "London-BuyStop")

                    ss_sl = self.or_high
                    ss_tp = self.or_low - risk * lcfg.LONDON_TARGET_RR
                    res_s = broker.place_pending_order("SELL_STOP", lot, self.or_low, ss_sl, ss_tp, "London-SellStop")

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
        eval_result = evaluate_london_entry(
            df_m5=df_m5,
            tick=tick,
            equity=equity,
            now_utc=now_utc,
            sched=sched,
            or_high=self.or_high,
            or_low=self.or_low,
            or_range=self.or_range,
            risk_pct=lcfg.LONDON_RISK_PCT,
            point_value=lcfg.POINT_VALUE,
            lot_step=lcfg.LOT_STEP,
            min_lot=lcfg.MIN_LOT,
            max_lot=lcfg.MAX_LOT,
            max_spread=lcfg.MAX_SPREAD_USD,
            max_chase=lcfg.MAX_CHASE_USD,
            target_rr=lcfg.LONDON_TARGET_RR,
            expansion_mult=lcfg.LONDON_EXPANSION,
        )
        if eval_result is None:
            return None

        if eval_result["status"] == "CHASE_BLOCKED":
            if self.logger:
                self.logger.warning(f"[🛑 ANTI-CHASING LONDON] {eval_result['message']}")
            if eval_result.get("intent"):
                return eval_result["intent"]
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
        """Evaluasi kondisi keluar khusus London Pit ORB (Session Cutoff 11:25 UTC)."""
        comm = getattr(position, "comment", "") or ""
        if "London" not in comm:
            return None

        sched = schedule or {}
        return evaluate_london_exit(
            position=position,
            now_utc=now_utc,
            cutoff_hm=sched.get("LONDON_CUTOFF", (11, 25)),
        )

    def on_order_result(self, res: OrderResult, broker: Optional[IBroker] = None) -> None:
        """Callback penanganan hasil eksekusi order London."""
        if res.success:
            if self.logger:
                self.logger.info(f"[✓] ORDER LONDON BERHASIL! Ticket: {res.order_id} @ {res.price}\n")
            self.trades_today = True
            self.retry_count = 0
        else:
            if broker and self.reconcile_broker_orders(broker, self.magic_number):
                return
            self.retry_count += 1
            if self.logger:
                self.logger.error(f"[X] ORDER LONDON GAGAL ({self.retry_count}/{lcfg.MAX_SESSION_RETRIES}): {res.comment}")
            if self.retry_count >= lcfg.MAX_SESSION_RETRIES:
                if self.logger:
                    self.logger.warning(f"[🔒 SESI DILOCKOUT] Batas maksimal percobaan tercapai. Sesi LONDON dikunci hari ini.")
                self.trades_today = True


class LondonExecutorMixin:
    """Mixin delegator untuk kompatibilitas mundur (Legacy Adapter)."""

    def _evaluate_london_orb(self, df_m5: pd.DataFrame, now_utc: datetime, tick: dict, equity: float, open_pendings: list):
        """Evaluasi pembentukan box OR dan eksekusi breakout London."""
        strat = getattr(self, "_london_strategy", None)
        if strat is None:
            if not hasattr(self, "_fallback_london_strat"):
                self._fallback_london_strat = LondonLiveStrategy(logger=getattr(self, "logger", None))
            strat = self._fallback_london_strat
            strat.trades_today = self.trades_today.get("LONDON", False)
            strat.order_in_flight = self._order_in_flight.get("LONDON", False)
            strat.or_high = getattr(self, "london_or_high", None)
            strat.or_low = getattr(self, "london_or_low", None)
            strat.or_range = getattr(self, "london_or_range", None)
            strat.pending_orders = getattr(self, "pending_orders", {}).get("LONDON", [])

        if not strat.can_trade() or self._reconcile_broker_orders("LONDON"):
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
        self.london_or_high = strat.or_high
        self.london_or_low = strat.or_low
        self.london_or_range = strat.or_range

        if intent is None:
            return

        dir_str = intent.action
        tag = "LONG" if "BUY" in dir_str else "SHORT"
        cmp_price = tick["ask"] if "BUY" in dir_str else tick["bid"]
        comp_sym = ">" if "BUY" in dir_str else "<"
        ref_level = strat.or_high if "BUY" in dir_str else strat.or_low
        self.logger.info(f"\n[⚡ BREAKOUT LONDON {tag}] Price {cmp_price:.2f} {comp_sym} LOR {ref_level:.2f} | Lot: {intent.volume} | SL: {intent.stop_loss:.2f} | TP: {intent.take_profit:.2f} | Action: {intent.action}")

        self._order_in_flight["LONDON"] = True
        strat.order_in_flight = True
        try:
            res = self.connector.execute_order_intent(intent)
            self._handle_order_result("LONDON", res)
            strat.on_order_result(res, self.connector)
        finally:
            self._order_in_flight["LONDON"] = False
            strat.order_in_flight = False
