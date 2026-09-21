"""
Asian Mean Reversion Live Execution Engine
==========================================
Sesi: 01:00 - 04:30 UTC
Alokasi Risiko: 1.0%
Model: Statistical Arbitrage / Mean Reversion (Z-Score + RSI Filter)
"""

import sys
import time
from datetime import datetime
from typing import Dict, Any, Optional, List
import pandas as pd

from src.execution import config as lcfg
from src.core.types import OrderIntent, ExitIntent, OrderResult
from src.core.interfaces import IBroker, ILiveStrategy
from src.strategies.asian_mr.signals import (
    compute_asian_indicators,
    check_entry_signal as check_asian_entry,
    evaluate_asian_entry,
    evaluate_asian_exit,
)


class AsiaLiveStrategy:
    """
    Komponen Strategi Live Asian Mean Reversion (Pure Strategy Composition).
    Merangkum state internal (trades_today, retry_count, in-flight mutex)
    dan logika evaluasi sinyal entry/exit.
    """

    def __init__(self, logger=None):
        self._strategy_id = "ASIAN"
        self._name = "Asia MR"
        self._magic_number = lcfg.MAGIC_NUMBER
        self.trades_today = False
        self.order_in_flight = False
        self.retry_count = 0
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
        """Cek kelayakan eksekusi: strategi aktif, belum trade hari ini, dan tidak in-flight."""
        return lcfg.ENABLE_ASIAN_MR and not self.trades_today and not self.order_in_flight

    def on_daily_reset(self, today_date: Any, schedule: Dict[str, Any]) -> None:
        """Reset state trading harian."""
        self.trades_today = False
        self.order_in_flight = False
        self.retry_count = 0

    def reconcile_broker_orders(self, broker: IBroker, magic_number: int) -> bool:
        """Periksa apakah posisi/deal Asia sudah ada di broker hari ini."""
        open_pos = broker.get_open_positions(magic_number)
        for p in open_pos:
            comm = getattr(p, "comment", "") or ""
            if "AsiaMR" in comm:
                if self.logger:
                    self.logger.warning(f"[🛡️ RECONCILIATION MATCH] Posisi ASIAN (Ticket {p.ticket}) sudah aktif di broker!")
                self.trades_today = True
                self.retry_count = 0
                return True

        if hasattr(broker, "get_today_deals"):
            today_deals = broker.get_today_deals(magic_number)
            for d in today_deals:
                comm = getattr(d, "comment", "") or ""
                if "AsiaMR" in comm:
                    if self.logger:
                        self.logger.warning(f"[🛡️ RECONCILIATION MATCH] Deal ASIAN (Ticket {d.ticket}) sudah tercatat di history broker!")
                    self.trades_today = True
                    self.retry_count = 0
                    return True

        return False

    def handle_oco(self, open_positions: List[Any], open_pendings: List[Any], broker: IBroker) -> None:
        """Asia MR tidak menggunakan pending stop order OCO."""
        pass

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
        """Evaluasi kondisi sinyal entry Asia Mean Reversion."""
        if not self.can_trade():
            return None

        hm = (now_utc.hour, now_utc.minute)
        sched = schedule
        if not (sched.get("ASIAN_START", (1, 0)) <= hm < sched.get("ASIAN_END", (4, 30))):
            return None

        # Mendukung dynamic mock patch pada live_runner / execution runner
        runner_mod = sys.modules.get("src.execution.runner") or sys.modules.get("live.live_runner")
        indicator_func = getattr(runner_mod, "compute_asian_indicators", compute_asian_indicators)
        entry_func = getattr(runner_mod, "check_asian_entry", check_asian_entry)

        stops_level = 0.30
        if broker and hasattr(broker, "get_symbol_info"):
            sym_info = broker.get_symbol_info(lcfg.SYMBOL)
            point = sym_info.point if sym_info else 0.01
            stops_level = (sym_info.stops_level * point) if sym_info and hasattr(sym_info, "stops_level") else 0.30

        return evaluate_asian_entry(
            df_m5=df_m5,
            tick=tick,
            equity=equity,
            now_utc=now_utc,
            sched=sched,
            risk_pct=lcfg.ASIAN_RISK_PCT,
            max_spread=lcfg.MAX_SPREAD_USD,
            point_value=lcfg.POINT_VALUE,
            lot_step=lcfg.LOT_STEP,
            min_lot=lcfg.MIN_LOT,
            max_lot=lcfg.MAX_LOT,
            symbol_stops_level=stops_level,
            indicator_func=indicator_func,
            entry_func=entry_func,
        )

    def evaluate_exit(
        self,
        position: Any,
        df_m5: pd.DataFrame,
        now_utc: datetime,
        broker_utc_offset_sec: int = 0,
        schedule: Optional[Dict[str, Any]] = None,
    ) -> Optional[ExitIntent]:
        """Evaluasi kondisi keluar khusus Asia Mean Reversion."""
        comm = getattr(position, "comment", "") or ""
        if "AsiaMR" not in comm:
            return None

        sched = schedule or {}
        runner_mod = sys.modules.get("src.execution.runner") or sys.modules.get("live.live_runner")
        indicator_func = getattr(runner_mod, "compute_asian_indicators", None)

        return evaluate_asian_exit(
            position=position,
            df_m5=df_m5,
            now_utc=now_utc,
            broker_utc_offset_sec=broker_utc_offset_sec,
            cutoff_hm=sched.get("ASIAN_CUTOFF", (6, 0)),
            max_duration_min=getattr(lcfg, "ASIA_MAX_DURATION_MIN", 60),
            z_hard_cut=getattr(lcfg, "ASIA_Z_HARD_CUT", 3.2),
            z_exit_thresh=getattr(lcfg, "ASIA_Z_EXIT_THRESHOLD", 0.5),
            indicator_func=indicator_func,
        )

    def on_order_result(self, res: OrderResult, broker: Optional[IBroker] = None) -> None:
        """Callback penanganan hasil eksekusi order."""
        if res.success:
            if self.logger:
                self.logger.info(f"[✓] ORDER ASIAN BERHASIL! Ticket: {res.order_id} @ {res.price}\n")
            self.trades_today = True
            self.retry_count = 0
        else:
            if broker and self.reconcile_broker_orders(broker, self.magic_number):
                return
            self.retry_count += 1
            if self.logger:
                self.logger.error(f"[X] ORDER ASIAN GAGAL ({self.retry_count}/{lcfg.MAX_SESSION_RETRIES}): {res.comment}")
            if self.retry_count >= lcfg.MAX_SESSION_RETRIES:
                if self.logger:
                    self.logger.warning(f"[🔒 SESI DILOCKOUT] Batas maksimal percobaan tercapai. Sesi ASIAN dikunci hari ini.")
                self.trades_today = True


class AsiaExecutorMixin:
    """Mixin delegator untuk kompatibilitas mundur (Legacy Adapter)."""

    def _evaluate_asian_mr(self, df_m5: pd.DataFrame, now_utc: datetime, tick: dict, equity: float):
        """Evaluasi sinyal dan eksekusi entri sesi Asia MR via OrderIntent."""
        strat = getattr(self, "_asian_strategy", None)
        if strat is None:
            # Fallback jika mixin digunakan secara mandiri
            if not hasattr(self, "_fallback_asia_strat"):
                self._fallback_asia_strat = AsiaLiveStrategy(logger=getattr(self, "logger", None))
            strat = self._fallback_asia_strat
            strat.trades_today = self.trades_today.get("ASIAN", False)
            strat.order_in_flight = self._order_in_flight.get("ASIAN", False)

        if not strat.can_trade() or self._reconcile_broker_orders("ASIAN"):
            return

        intent = strat.evaluate_entry(
            df_m5=df_m5,
            tick=tick,
            equity=equity,
            now_utc=now_utc,
            schedule=self.today_schedule,
            broker=self.connector,
        )
        if intent is None:
            return

        tp_log = f"{intent.take_profit:.2f}" if intent.take_profit is not None else "Dynamic Z-Neutral"
        self.logger.info(f"\n[🚀 SINYAL ASIA MR] {intent.action} {intent.volume} Lot XAU/USD | Entry: {intent.entry_price:.2f} | SL: {intent.stop_loss:.2f} | TP: {tp_log}")

        self._order_in_flight["ASIAN"] = True
        strat.order_in_flight = True
        try:
            res = self.connector.open_market_order(
                direction=intent.action,
                volume=intent.volume,
                sl=intent.stop_loss,
                tp=intent.take_profit,
                comment=intent.comment,
            )
            self._handle_order_result("ASIAN", res)
            strat.on_order_result(res, self.connector)
        finally:
            self._order_in_flight["ASIAN"] = False
            strat.order_in_flight = False
