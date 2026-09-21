"""
Quantitative Master Portfolio — Institutional Live Execution Runner (MT5)
========================================================================
Master Orchestrator untuk eksekusi live multi-sesi XAU/USD di MetaTrader 5:
1. Asian Mean Reversion (01:00 - 04:30 UTC | Risk: 1.0%)
2. London Pit Opening Range Breakout (08:15 - 11:30 UTC | Risk: 2.0%)
3. New York Opening Range Breakout (Dynamic US DST | Risk: 2.0%)

Clean Architecture & Strategy Pattern (Pure Composition):
- Decoupled Broker Port: IBroker (MT5Connector / MockBroker)
- Decoupled Strategy Port: ILiveStrategy (AsiaLiveStrategy, LondonLiveStrategy, NYLiveStrategy)
- Composed Service Components: RiskManager, PositionManager, SessionScheduleManager
"""

import sys
import time
import atexit
from datetime import datetime, timezone, date
from typing import Optional, Dict, Any, List, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pandas as pd
import MetaTrader5 as mt5

from src.execution import config as lcfg
from src.execution.mt5_connector import MT5Connector
from src.execution.notifications import TelegramNotifier
from src.observability.logger import get_logger, disable_quick_edit_mode, TradeJournal

# Domain interfaces and types
from src.core.interfaces import IBroker, ILiveStrategy
from src.core.types import OrderIntent, ExitIntent, OrderResult, Direction as AsianDirection
from src.strategies.asian_mr.signals import (
    compute_asian_indicators,
    check_entry_signal as check_asian_entry,
)

# Execution Components & Strategies
from src.execution.risk_manager import RiskManager, RiskManagementMixin, is_process_running
from src.execution.position_manager import PositionManager, PositionManagementMixin
from src.execution.scheduler import SessionScheduleManager
from src.execution.executors.asia import AsiaLiveStrategy, AsiaExecutorMixin
from src.execution.executors.london import LondonLiveStrategy, LondonExecutorMixin
from src.execution.executors.ny import NYLiveStrategy, NYExecutorMixin
from src.execution.audit_engine import SessionReconciliationAuditor


class _StrategyStateProxy(dict):
    """Proxy dictionary yang menyinkronkan state ke object ILiveStrategy secara bidirectional."""

    def __init__(self, trader, attr_name: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._trader = trader
        self._attr_name = attr_name

    def __getitem__(self, key: str):
        strat = self._trader._strategy_map.get(key)
        if strat and hasattr(strat, self._attr_name):
            return getattr(strat, self._attr_name)
        return super().get(key, False)

    def __setitem__(self, key: str, value: Any):
        super().__setitem__(key, value)
        strat = self._trader._strategy_map.get(key)
        if strat and hasattr(strat, self._attr_name):
            setattr(strat, self._attr_name, value)


class LivePortfolioTrader:
    """
    Master Bot Live Trading Orchestrator untuk XAU/USD di MetaTrader 5.
    Menggunakan Pure Composition (Strategy Pattern):
    - Tidak lagi mewarisi Mixin God Object.
    - Mengelola daftar ILiveStrategy polimorfik.
    - Menginjeksi IBroker, RiskManager, dan PositionManager.
    """

    def __init__(
        self,
        connector: Optional[IBroker] = None,
        notifier: Optional[TelegramNotifier] = None,
        strategies: Optional[List[ILiveStrategy]] = None,
        risk_manager: Optional[RiskManager] = None,
        position_manager: Optional[PositionManager] = None,
    ):
        self.logger = get_logger()
        self.journal = TradeJournal()
        self.connector = connector if connector is not None else MT5Connector()
        self.telegram = notifier if notifier is not None else TelegramNotifier()

        # Composed Services
        self.risk_manager = risk_manager if risk_manager is not None else RiskManager(
            connector=self.connector,
            telegram=self.telegram,
            logger=self.logger,
        )
        self.position_manager = position_manager if position_manager is not None else PositionManager(
            connector=self.connector,
            telegram=self.telegram,
            journal=self.journal,
            logger=self.logger,
        )

        # Composed Autonomous Strategies (Strategy Pattern)
        if strategies is not None:
            self.strategies: List[ILiveStrategy] = strategies
        else:
            self.strategies: List[ILiveStrategy] = [
                AsiaLiveStrategy(logger=self.logger),
                LondonLiveStrategy(logger=self.logger),
                NYLiveStrategy(logger=self.logger),
            ]
        self._strategy_map: Dict[str, ILiveStrategy] = {s.strategy_id: s for s in self.strategies}

        # Lifecycle & Scheduling state
        self.current_trading_day: Optional[date] = None
        self.today_schedule: Dict[str, Any] = {}
        self.last_daily_heartbeat_day: Optional[date] = None
        self.last_heartbeat_time = 0.0

        # State Proxies (Bidirectional mapping to strategy objects for backward compatibility)
        self.trades_today = _StrategyStateProxy(self, "trades_today", {"ASIAN": False, "LONDON": False, "NY": False})
        self._order_in_flight = _StrategyStateProxy(self, "order_in_flight", {"ASIAN": False, "LONDON": False, "NY": False})
        self.retry_counts = _StrategyStateProxy(self, "retry_count", {"ASIAN": 0, "LONDON": 0, "NY": 0})

        # Session transition and OR notification tracking
        self._current_phase: Optional[str] = None
        self._or_notified: Dict[str, bool] = {"LONDON": False, "NY": False}
        self._is_feed_stale: bool = False
        self._last_stale_warn: float = 0.0
        self._last_stale_tele_warn: float = 0.0


    # ─────────────────────────────────────────────────────────────
    # BACKWARD COMPATIBILITY PROPERTIES (LEGACY TEST SUPPORT)
    # ─────────────────────────────────────────────────────────────
    @property
    def tracked_positions(self) -> Dict[int, Dict[str, Any]]:
        return self.position_manager.tracked_positions

    @tracked_positions.setter
    def tracked_positions(self, val: Dict[int, Dict[str, Any]]):
        self.position_manager.tracked_positions = val

    @property
    def starting_daily_equity(self) -> Optional[float]:
        return self.risk_manager.starting_daily_equity

    @starting_daily_equity.setter
    def starting_daily_equity(self, val: Optional[float]):
        self.risk_manager.starting_daily_equity = val

    @property
    def daily_circuit_breaker_tripped(self) -> bool:
        return self.risk_manager.daily_circuit_breaker_tripped

    @daily_circuit_breaker_tripped.setter
    def daily_circuit_breaker_tripped(self, val: bool):
        self.risk_manager.daily_circuit_breaker_tripped = val

    @property
    def _lock_acquired(self) -> bool:
        return self.risk_manager._lock_acquired

    @_lock_acquired.setter
    def _lock_acquired(self, val: bool):
        self.risk_manager._lock_acquired = val

    @property
    def london_or_high(self) -> Optional[float]:
        strat = self._strategy_map.get("LONDON")
        return getattr(strat, "or_high", None)

    @london_or_high.setter
    def london_or_high(self, val: Optional[float]):
        strat = self._strategy_map.get("LONDON")
        if strat:
            strat.or_high = val

    @property
    def london_or_low(self) -> Optional[float]:
        strat = self._strategy_map.get("LONDON")
        return getattr(strat, "or_low", None)

    @london_or_low.setter
    def london_or_low(self, val: Optional[float]):
        strat = self._strategy_map.get("LONDON")
        if strat:
            strat.or_low = val

    @property
    def london_or_range(self) -> Optional[float]:
        strat = self._strategy_map.get("LONDON")
        return getattr(strat, "or_range", None)

    @london_or_range.setter
    def london_or_range(self, val: Optional[float]):
        strat = self._strategy_map.get("LONDON")
        if strat:
            strat.or_range = val

    @property
    def ny_or_high(self) -> Optional[float]:
        strat = self._strategy_map.get("NY")
        return getattr(strat, "or_high", None)

    @ny_or_high.setter
    def ny_or_high(self, val: Optional[float]):
        strat = self._strategy_map.get("NY")
        if strat:
            strat.or_high = val

    @property
    def ny_or_low(self) -> Optional[float]:
        strat = self._strategy_map.get("NY")
        return getattr(strat, "or_low", None)

    @ny_or_low.setter
    def ny_or_low(self, val: Optional[float]):
        strat = self._strategy_map.get("NY")
        if strat:
            strat.or_low = val

    @property
    def ny_or_range(self) -> Optional[float]:
        strat = self._strategy_map.get("NY")
        return getattr(strat, "or_range", None)

    @ny_or_range.setter
    def ny_or_range(self, val: Optional[float]):
        strat = self._strategy_map.get("NY")
        if strat:
            strat.or_range = val

    @property
    def pending_orders(self) -> Dict[str, List[int]]:
        l_strat = self._strategy_map.get("LONDON")
        ny_strat = self._strategy_map.get("NY")
        return {
            "LONDON": getattr(l_strat, "pending_orders", []),
            "NY": getattr(ny_strat, "pending_orders", []),
        }

    @pending_orders.setter
    def pending_orders(self, val: Dict[str, List[int]]):
        if "LONDON" in val:
            l_strat = self._strategy_map.get("LONDON")
            if l_strat:
                l_strat.pending_orders = val["LONDON"]
        if "NY" in val:
            ny_strat = self._strategy_map.get("NY")
            if ny_strat:
                ny_strat.pending_orders = val["NY"]

    # ─────────────────────────────────────────────────────────────
    # DELEGATED SERVICE METHODS
    # ─────────────────────────────────────────────────────────────
    def _acquire_pid_lock(self) -> bool:
        return self.risk_manager.acquire_pid_lock()

    def _release_pid_lock(self):
        self.risk_manager.release_pid_lock()

    def _load_or_init_daily_circuit_breaker(self, today_date: date):
        self.risk_manager.load_or_init_daily_circuit_breaker(today_date)

    def _check_daily_circuit_breaker(self, current_equity: float, today_date: Optional[date] = None) -> bool:
        return self.risk_manager.check_daily_circuit_breaker(current_equity, today_date)

    def _track_and_notify_positions(self, open_positions: list):
        self.position_manager.track_and_notify_positions(open_positions)

    def _handle_oco_cancellation(self, open_positions: list, open_pendings: list):
        self.position_manager.handle_oco_cancellation(open_positions, open_pendings, self.trades_today)

    def _manage_open_positions(self, positions: list, df_m5: pd.DataFrame, now_utc: datetime):
        self.position_manager.manage_open_positions(positions, df_m5, now_utc, self.today_schedule, self.strategies)

    def _reconcile_broker_orders(self, session: str) -> bool:
        strat = self._strategy_map.get(session)
        if strat:
            return strat.reconcile_broker_orders(self.connector, lcfg.MAGIC_NUMBER)
        return False

    def _handle_order_result(self, session: str, res):
        strat = self._strategy_map.get(session)
        if strat:
            strat.on_order_result(res, self.connector)

    def _evaluate_asian_mr(self, df_m5: pd.DataFrame, now_utc: datetime, tick: dict, equity: float):
        strat = self._strategy_map.get("ASIAN")
        if strat:
            if not strat.can_trade() or strat.reconcile_broker_orders(self.connector, lcfg.MAGIC_NUMBER):
                return
            intent = strat.evaluate_entry(
                df_m5=df_m5, tick=tick, equity=equity, now_utc=now_utc, schedule=self.today_schedule, broker=self.connector
            )
            if intent:
                self._dispatch_order_intent(strat, intent)

    def _evaluate_london_orb(self, df_m5: pd.DataFrame, now_utc: datetime, tick: dict, equity: float, open_pendings: list):
        strat = self._strategy_map.get("LONDON")
        if strat:
            if not strat.can_trade() or strat.reconcile_broker_orders(self.connector, lcfg.MAGIC_NUMBER):
                return
            intent = strat.evaluate_entry(
                df_m5=df_m5, tick=tick, equity=equity, now_utc=now_utc, schedule=self.today_schedule, open_pendings=open_pendings, broker=self.connector
            )
            if intent:
                self._dispatch_order_intent(strat, intent)

    def _evaluate_ny_orb(self, df_m5: pd.DataFrame, now_utc: datetime, tick: dict, equity: float, open_pendings: list):
        strat = self._strategy_map.get("NY")
        if strat:
            if not strat.can_trade() or strat.reconcile_broker_orders(self.connector, lcfg.MAGIC_NUMBER):
                return
            intent = strat.evaluate_entry(
                df_m5=df_m5, tick=tick, equity=equity, now_utc=now_utc, schedule=self.today_schedule, open_pendings=open_pendings, broker=self.connector
            )
            if intent:
                self._dispatch_order_intent(strat, intent)

    # ─────────────────────────────────────────────────────────────
    # ORDER DISPATCH & POLYMORPHIC TICKS
    # ─────────────────────────────────────────────────────────────
    def _probe_and_recover_order(
        self,
        strategy: ILiveStrategy,
        intent: OrderIntent,
        probe_timeout_sec: Optional[float] = None,
        poll_interval_sec: Optional[float] = None,
    ) -> OrderResult:
        """
        Active Probing Loop: Memverifikasi apakah order yang mengalami IPC Timeout
        ternyata berhasil dieksekusi di broker (menyelamatkan trade tanpa risiko order dobel).
        """
        if probe_timeout_sec is None:
            probe_timeout_sec = getattr(lcfg, "PROBE_TIMEOUT_SEC", 15.0)
        if poll_interval_sec is None:
            poll_interval_sec = getattr(lcfg, "PROBE_INTERVAL_SEC", 3.0)

        strat_id_prefix = strategy.strategy_id.upper()
        start_time = time.time()
        self.logger.warning(
            f"[⏱️ ACTIVE PROBING] Order {intent.comment} ({strategy.name}) mengalami timeout jaringan! "
            f"Melakukan investigasi broker selama {probe_timeout_sec:.0f}s untuk melacak status deal..."
        )

        while True:
            # 1. Cek apakah posisi terbuka sudah ada di broker
            open_pos = self.connector.get_open_positions(lcfg.MAGIC_NUMBER)
            for p in open_pos:
                comm = getattr(p, "comment", "") or ""
                if intent.comment in comm or strat_id_prefix in comm.upper() or strategy.name.split()[0].upper() in comm.upper():
                    self.logger.info(
                        f"[🛡️ PROBE RECOVERY SUCCESS] Order {strategy.name} (Ticket #{p.ticket}) "
                        f"berhasil diverifikasi aktif di broker! Trade terselamatkan (0 Trade Hilang)."
                    )
                    return OrderResult(
                        success=True,
                        retcode=10009,
                        order_id=p.ticket,
                        price=getattr(p, "price_open", intent.entry_price),
                        volume=getattr(p, "volume", intent.volume),
                        comment=f"Recovered via Active Probe: #{p.ticket}",
                    )

            # 2. Cek apakah deal sudah tercatat di history hari ini
            if hasattr(self.connector, "get_today_deals"):
                deals = self.connector.get_today_deals(lcfg.MAGIC_NUMBER)
                for d in deals:
                    comm = getattr(d, "comment", "") or ""
                    if intent.comment in comm or strat_id_prefix in comm.upper() or strategy.name.split()[0].upper() in comm.upper():
                        self.logger.info(
                            f"[🛡️ PROBE RECOVERY SUCCESS] Deal {strategy.name} (Ticket #{d.ticket}) "
                            f"ditemukan di history broker! Trade terselamatkan."
                        )
                        return OrderResult(
                            success=True,
                            retcode=10009,
                            order_id=d.ticket,
                            price=getattr(d, "price", intent.entry_price),
                            volume=getattr(d, "volume", intent.volume),
                            comment=f"Recovered from deals: #{d.ticket}",
                        )

            if time.time() - start_time >= probe_timeout_sec:
                break
            time.sleep(poll_interval_sec)

        # Broker terbukti 100% bersih dari order lama
        self.logger.warning(
            f"[🔍 PROBE VERIFIED CLEAN] Broker terkonfirmasi bersih dari order {intent.comment}. "
            f"Tidak ada posisi/deal yang terbentuk di server broker."
        )
        return OrderResult(
            success=False,
            retcode=-10008,
            order_id=0,
            price=0.0,
            volume=0.0,
            comment="IPC Timeout: Verified not executed at broker after active probing",
        )

    def _dispatch_order_intent(self, strategy: ILiveStrategy, intent: OrderIntent):
        """Kirim OrderIntent ke broker adapter dengan proteksi in-flight mutex & Active Probing."""
        strategy.order_in_flight = True
        tp_log = f"{intent.take_profit:.2f}" if intent.take_profit is not None else "None"
        try:
            # Pastikan idempotency tag berbasis tanggal tersemat di comment
            today_tag = datetime.now(timezone.utc).strftime("%y%m%d")
            if today_tag not in intent.comment:
                intent.comment = f"{intent.comment}-{today_tag}"

            self.logger.info(
                f"\n[🚀 SINYAL {strategy.name.upper()}] {intent.action} {intent.volume} Lot {lcfg.SYMBOL} "
                f"| Entry: {intent.entry_price:.2f} | SL: {intent.stop_loss:.2f} | TP: {tp_log} | Tag: {intent.comment}"
            )
            res = self.connector.open_market_order(
                direction=intent.action,
                volume=intent.volume,
                sl=intent.stop_loss,
                tp=intent.take_profit,
                comment=intent.comment,
            )

            # Jika terjadi IPC Timeout (retcode == -10008 atau "Timeout" in res.comment)
            if not res.success and getattr(lcfg, "ENABLE_ACTIVE_PROBING", True) and (res.retcode == -10008 or "Timeout" in res.comment or "TIMEOUT" in res.comment.upper()):
                # Masuk Active Probing untuk menyelamatkan trade tanpa risiko order ganda
                recovered_res = self._probe_and_recover_order(strategy, intent)
                if recovered_res.success:
                    res = recovered_res
                else:
                    # Broker terbukti bersih dari order lama. Sekarang RE-FIRE jika kuota retry masih ada!
                    if strategy.retry_count < lcfg.MAX_SESSION_RETRIES:
                        tick = self.connector.get_tick(lcfg.SYMBOL) if hasattr(self.connector, "get_tick") else self.connector.get_current_tick(lcfg.SYMBOL)
                        if tick:
                            curr_price = tick["ask"] if intent.action.upper() == "BUY" else tick["bid"]
                            slippage = abs(curr_price - intent.entry_price)
                            max_allowed_slip = getattr(lcfg, "MAX_REFIRE_SLIPPAGE_USD", 1.50)

                            if slippage <= max_allowed_slip:
                                self.logger.info(
                                    f"[🔄 RE-FIRE ORDER ({strategy.retry_count + 1}/{lcfg.MAX_SESSION_RETRIES})] "
                                    f"Menembak ulang order {strategy.name} setelah verifikasi bersih (Slippage: ${slippage:.2f} <= ${max_allowed_slip:.2f})..."
                                )
                                intent.entry_price = curr_price
                                refire_res = self.connector.open_market_order(
                                    direction=intent.action,
                                    volume=intent.volume,
                                    sl=intent.stop_loss,
                                    tp=intent.take_profit,
                                    comment=intent.comment,
                                )
                                res = refire_res
                            else:
                                self.logger.warning(
                                    f"[⚠️ RE-FIRE ABORTED] Harga pasar melompat (${slippage:.2f} > batas ${max_allowed_slip:.2f}). "
                                    f"Re-fire dibatalkan demi disiplin slippage."
                                )

            strategy.on_order_result(res, self.connector)
            if not res.success and strategy.retry_count >= lcfg.MAX_SESSION_RETRIES:
                self.telegram.notify_session_lockout(
                    session_name=strategy.name,
                    retry_count=strategy.retry_count,
                    max_retries=lcfg.MAX_SESSION_RETRIES,
                )
        finally:
            strategy.order_in_flight = False

    def _sync_state_from_broker(self):
        """Sinkronkan status transaksi hari ini dari broker secara polimorfik."""
        open_pos = self.connector.get_open_positions(lcfg.MAGIC_NUMBER)
        self.position_manager.track_and_notify_positions(open_pos)

        # Polimorfik reconcile untuk setiap strategi
        for strat in self.strategies:
            strat.reconcile_broker_orders(self.connector, lcfg.MAGIC_NUMBER)

        status_str = ", ".join([f"{s.strategy_id}: {'DONE' if s.trades_today else 'READY'}" for s in self.strategies])
        self.logger.info(f"[*] State Recovery Hari Ini -> [{status_str}]")

    def _reset_daily_state_if_needed(self, today_date: date):
        """Reset state, counter, dan hitung ulang jadwal sesi jika tanggal UTC berganti."""
        if self.current_trading_day is None:
            self.current_trading_day = today_date
            self.today_schedule = SessionScheduleManager.get_today_schedule(today_date)
            self.risk_manager.load_or_init_daily_circuit_breaker(today_date)
            return

        if self.current_trading_day != today_date:
            self.current_trading_day = today_date
            self.today_schedule = SessionScheduleManager.get_today_schedule(today_date)
            self.risk_manager.load_or_init_daily_circuit_breaker(today_date)

            # Polimorfik reset untuk setiap strategi
            for strat in self.strategies:
                strat.on_daily_reset(today_date, self.today_schedule)

            self._or_notified = {"LONDON": False, "NY": False}
            self._current_phase = None


            ny_tz = self.today_schedule.get("NY_TZ_NAME", "UTC")
            self.logger.info(f"[📅 PERGANTIAN HARI UTC] Tanggal baru: {today_date}. Counter trade harian di-reset.")
            self.logger.info(f"   • Jadwal Asia MR  : {self.today_schedule['ASIAN_START'][0]:02d}:{self.today_schedule['ASIAN_START'][1]:02d} - {self.today_schedule['ASIAN_END'][0]:02d}:{self.today_schedule['ASIAN_END'][1]:02d} UTC")
            self.logger.info(f"   • Jadwal London   : OR {self.today_schedule['LONDON_OR_START'][0]:02d}:{self.today_schedule['LONDON_OR_START'][1]:02d} UTC | Entry {self.today_schedule['LONDON_ENTRY_START'][0]:02d}:{self.today_schedule['LONDON_ENTRY_START'][1]:02d} - {self.today_schedule['LONDON_ENTRY_END'][0]:02d}:{self.today_schedule['LONDON_ENTRY_END'][1]:02d} UTC")
            self.logger.info(f"   • Jadwal New York : OR {self.today_schedule['NY_OR_START'][0]:02d}:{self.today_schedule['NY_OR_START'][1]:02d} UTC | Entry {self.today_schedule['NY_ENTRY_START'][0]:02d}:{self.today_schedule['NY_ENTRY_START'][1]:02d} - {self.today_schedule['NY_ENTRY_END'][0]:02d}:{self.today_schedule['NY_ENTRY_END'][1]:02d} UTC ({ny_tz})")

            if self.last_daily_heartbeat_day != today_date:
                self.last_daily_heartbeat_day = today_date
                acc = self.connector.get_account_status()
                if acc:
                    ping = 2.5
                    try:
                        term = mt5.terminal_info()
                        if term and hasattr(term, "ping_last"):
                            ping = float(term.ping_last) / 1000.0
                    except Exception:
                        pass

                    is_wknd = self._is_market_closed_weekend(datetime.now(timezone.utc))
                    next_sess = "Weekend Standby (Market Opens Monday 01:00 UTC)" if is_wknd else "Asian Session (01:00 UTC)"
                    self.telegram.notify_daily_heartbeat(
                        balance=acc.balance,
                        equity=acc.equity,
                        free_margin=acc.free_margin,
                        server=acc.server,
                        latency_ms=ping,
                        next_session=next_sess
                    )

    @staticmethod
    def _is_market_closed_weekend(now_utc: datetime) -> bool:
        """Deteksi apakah pasar XAU/USD sedang tutup di akhir pekan."""
        wd = now_utc.weekday()
        if wd == 4 and now_utc.hour >= 22:
            return True
        if wd == 5:
            return True
        if wd == 6 and now_utc.hour < 22:
            return True
        return False

    def _weekend_standby_cycle(self, now_utc: datetime):
        """Siklus hibernasi akhir pekan (ultra hemat CPU)."""
        today_date = now_utc.date()
        self._reset_daily_state_if_needed(today_date)

        curr_time_sec = time.time()
        if curr_time_sec - self.last_heartbeat_time >= 1800.0 or self.last_heartbeat_time == 0.0:
            self.last_heartbeat_time = curr_time_sec
            day_name = now_utc.strftime("%A")
            self.logger.info(f"[😴 WEEKEND STANDBY] Pasar {lcfg.SYMBOL} tutup ({day_name}). Bot hibernasi hemat CPU (Next: Senin 01:00 UTC).")

    def _is_in_any_active_window(self, now_utc: datetime) -> bool:
        """Cek apakah saat ini berada dalam jendela entri aktif."""
        hm = (now_utc.hour, now_utc.minute)
        sched = self.today_schedule
        if sched.get("ASIAN_START") and sched["ASIAN_START"] <= hm < sched["ASIAN_END"]:
            return True
        if sched.get("LONDON_ENTRY_START") and sched["LONDON_ENTRY_START"] <= hm < sched["LONDON_ENTRY_END"]:
            return True
        if sched.get("NY_ENTRY_START") and sched["NY_ENTRY_START"] <= hm < sched["NY_ENTRY_END"]:
            return True
        return False

    def _get_active_session_name(self, now_utc: datetime) -> str:
        """Deteksi nama sesi trading saat ini."""
        hm = (now_utc.hour, now_utc.minute)
        sched = self.today_schedule
        if sched.get("ASIAN_START") and sched["ASIAN_START"] <= hm < sched["ASIAN_END"]:
            return "Asia MR"
        elif sched.get("LONDON_ENTRY_START") and sched["LONDON_ENTRY_START"] <= hm < sched["LONDON_ENTRY_END"]:
            return "London Pit ORB"
        elif sched.get("NY_ENTRY_START") and sched["NY_ENTRY_START"] <= hm < sched["NY_ENTRY_END"]:
            return f"New York ORB ({sched.get('NY_TZ_NAME', 'UTC')})"
        return "Di Luar Jendela Trading"

    def _determine_session_phase(self, now_utc: datetime) -> Tuple[str, str, str, str]:
        """
        Deteksi fase sesi trading saat ini beserta metadata informasi.
        Returns:
            Tuple (phase_key, session_name, window_info, details)
        """
        hm = (now_utc.hour, now_utc.minute)
        sched = self.today_schedule

        # 1. Asian Session (01:00 - 04:30 UTC)
        if sched.get("ASIAN_START") and sched["ASIAN_START"] <= hm < sched["ASIAN_END"]:
            return (
                "ASIA_WINDOW",
                "Asian Mean Reversion",
                f"{sched['ASIAN_START'][0]:02d}:{sched['ASIAN_START'][1]:02d} - {sched['ASIAN_END'][0]:02d}:{sched['ASIAN_END'][1]:02d} UTC",
                "Strategi Mean Reversion (Bollinger Bands + RSI + EMA200). Risk: 1.0%",
            )

        # 2. London OR Formation (08:00 - 08:15 UTC)
        if sched.get("LONDON_OR_START") and sched["LONDON_OR_START"] <= hm < sched["LONDON_ENTRY_START"]:
            return (
                "LONDON_OR",
                "London Pit Opening Range (Forming)",
                f"{sched['LONDON_OR_START'][0]:02d}:{sched['LONDON_OR_START'][1]:02d} - {sched['LONDON_ENTRY_START'][0]:02d}:{sched['LONDON_ENTRY_START'][1]:02d} UTC",
                f"Memantau pembentukan Box Opening Range M5. Entry dibuka pukul {sched['LONDON_ENTRY_START'][0]:02d}:{sched['LONDON_ENTRY_START'][1]:02d} UTC.",
            )

        # 3. London Entry Window (08:15 - 11:30 UTC)
        if sched.get("LONDON_ENTRY_START") and sched["LONDON_ENTRY_START"] <= hm < sched["LONDON_ENTRY_END"]:
            return (
                "LONDON_ENTRY",
                "London Pit Breakout Entry Window",
                f"{sched['LONDON_ENTRY_START'][0]:02d}:{sched['LONDON_ENTRY_START'][1]:02d} - {sched['LONDON_ENTRY_END'][0]:02d}:{sched['LONDON_ENTRY_END'][1]:02d} UTC",
                "Jendela entri breakout aktif. Risk: 2.0%",
            )

        # 4. New York OR Formation
        if sched.get("NY_OR_START") and sched["NY_OR_START"] <= hm < sched["NY_ENTRY_START"]:
            ny_tz = sched.get("NY_TZ_NAME", "UTC")
            return (
                "NY_OR",
                "New York Opening Range (Forming)",
                f"{sched['NY_OR_START'][0]:02d}:{sched['NY_OR_START'][1]:02d} - {sched['NY_ENTRY_START'][0]:02d}:{sched['NY_ENTRY_START'][1]:02d} UTC ({ny_tz})",
                f"Memantau pembentukan Box Opening Range M5 New York. Entry dibuka pukul {sched['NY_ENTRY_START'][0]:02d}:{sched['NY_ENTRY_START'][1]:02d} UTC.",
            )

        # 5. New York Entry Window
        if sched.get("NY_ENTRY_START") and sched["NY_ENTRY_START"] <= hm < sched["NY_ENTRY_END"]:
            ny_tz = sched.get("NY_TZ_NAME", "UTC")
            return (
                "NY_ENTRY",
                "New York Breakout Entry Window",
                f"{sched['NY_ENTRY_START'][0]:02d}:{sched['NY_ENTRY_START'][1]:02d} - {sched['NY_ENTRY_END'][0]:02d}:{sched['NY_ENTRY_END'][1]:02d} UTC ({ny_tz})",
                "Jendela entri New York aktif. Risk: 2.0%",
            )

        return ("STANDBY", "Standby / Flat", "Di Luar Jendela Trading", "")

    def _check_session_transitions(self, now_utc: datetime):
        """Pantau pergantian fase/sesi dan kirim notifikasi Telegram saat transisi terjadi."""
        phase_key, session_name, window_info, details = self._determine_session_phase(now_utc)
        sched = self.today_schedule

        # Inisialisasi awal saat bot pertama kali mengecek
        if self._current_phase is None:
            self._current_phase = phase_key
            return

        if phase_key == self._current_phase:
            return

        old_phase = self._current_phase
        self._current_phase = phase_key

        # 1. Notifikasi Penutupan Sesi Lama (Cutoff / Window Ended) dengan Shadow Backtest Audit
        if old_phase in ("ASIA_WINDOW", "LONDON_ENTRY", "NY_ENTRY"):
            session_key = "ASIAN" if old_phase == "ASIA_WINDOW" else ("LONDON" if old_phase == "LONDON_ENTRY" else "NY")
            live_count = 1 if self.trades_today.get(session_key, False) else 0

            # Tarik data candle M5 terkini dari broker untuk audit rekonsiliasi
            df_m5_audit = None
            try:
                if hasattr(self.connector, "get_live_rates"):
                    df_m5_audit = self.connector.get_live_rates(symbol=lcfg.SYMBOL, timeframe=mt5.TIMEFRAME_M5, count=300)
                elif hasattr(self.connector, "get_recent_candles"):
                    df_m5_audit = self.connector.get_recent_candles(symbol=lcfg.SYMBOL, timeframe=mt5.TIMEFRAME_M5, count=300)
            except Exception as e:
                self.logger.warning(f"[⚠️ AUDIT ERROR] Gagal mengambil candle M5 untuk audit: {e}")

            audit_rep = SessionReconciliationAuditor.audit_session(
                session_id=session_key,
                df_m5=df_m5_audit,
                today_date=now_utc.date(),
                live_trades_count=live_count,
                sched=sched,
            )
            self.logger.info(
                f"[🔍 SHADOW AUDIT {session_key}] Paritas: {'MATCH' if audit_rep.parity_matched else 'DIVERGENCE'} "
                f"| Live: {audit_rep.live_trades_count} | Backtest: {audit_rep.backtest_signals_count} | {audit_rep.primary_reason}"
            )

            if old_phase == "ASIA_WINDOW":
                self.telegram.notify_session_close(
                    session_name="Asian Mean Reversion",
                    trades_executed_today=bool(self.trades_today.get("ASIAN", False)),
                    next_session_info=f"London OR pukul {sched.get('LONDON_OR_START', (8, 0))[0]:02d}:{sched.get('LONDON_OR_START', (8, 0))[1]:02d} UTC",
                    audit_report=audit_rep,
                )
            elif old_phase == "LONDON_ENTRY":
                self.telegram.notify_session_close(
                    session_name="London Pit ORB",
                    trades_executed_today=bool(self.trades_today.get("LONDON", False)),
                    next_session_info=f"New York OR pukul {sched.get('NY_OR_START', (13, 30))[0]:02d}:{sched.get('NY_OR_START', (13, 30))[1]:02d} UTC",
                    audit_report=audit_rep,
                )
            elif old_phase == "NY_ENTRY":
                self.telegram.notify_session_close(
                    session_name=f"New York ORB ({sched.get('NY_TZ_NAME', 'UTC')})",
                    trades_executed_today=bool(self.trades_today.get("NY", False)),
                    next_session_info="Asian Session besok pukul 01:00 UTC",
                    audit_report=audit_rep,
                )

        # 2. Notifikasi Pembukaan Sesi Baru
        if phase_key in ("ASIA_WINDOW", "LONDON_OR", "LONDON_ENTRY", "NY_OR", "NY_ENTRY"):
            self.telegram.notify_session_open(
                session_name=session_name,
                window_info=window_info,
                details=details,
            )

    def _tick_cycle(self, now_utc: Optional[datetime] = None) -> bool:
        """Siklus evaluasi pasar tiap tick secara polimorfik."""
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        today_date = now_utc.date()
        self._reset_daily_state_if_needed(today_date)
        self._check_session_transitions(now_utc)

        tick = self.connector.get_tick(lcfg.SYMBOL) if hasattr(self.connector, "get_tick") else self.connector.get_current_tick(lcfg.SYMBOL)
        if not tick:
            return False

        df_m5 = None
        if hasattr(self.connector, "get_live_rates"):
            df_m5 = self.connector.get_live_rates(symbol=lcfg.SYMBOL, timeframe=mt5.TIMEFRAME_M5, count=200)
        elif hasattr(self.connector, "get_recent_candles"):
            df_m5 = self.connector.get_recent_candles(symbol=lcfg.SYMBOL, timeframe=mt5.TIMEFRAME_M5, count=200)

        if df_m5 is None or len(df_m5) < 65:
            return False

        # P2: Stale Market Data / Frozen Feed Detection (dikecualikan saat akhir pekan / pasar tutup)
        if getattr(lcfg, "ENABLE_STALE_FEED_GUARD", True) and not self._is_market_closed_weekend(now_utc):
            last_candle_time = df_m5["datetime"].iloc[-1]
            if hasattr(last_candle_time, "tzinfo") and last_candle_time.tzinfo is not None:
                compare_now = now_utc if now_utc.tzinfo is not None else now_utc.replace(tzinfo=timezone.utc)
            else:
                compare_now = now_utc.astimezone(timezone.utc).replace(tzinfo=None) if now_utc.tzinfo is not None else now_utc

            lag_seconds = (compare_now - last_candle_time).total_seconds()
            max_stale_sec = getattr(lcfg, "MAX_STALE_FEED_SECONDS", 900.0)

            if lag_seconds > max_stale_sec:
                curr_sec = time.time()
                # 1. Throttle logging di console (tiap 5 menit)
                if curr_sec - self._last_stale_warn >= 300.0:
                    self._last_stale_warn = curr_sec
                    self.logger.warning(
                        f"[⚠️ STALE MARKET DATA] Feed candle M5 terhenti! Candle terakhir: {last_candle_time} "
                        f"(Lag: {lag_seconds / 60.0:.1f}m > batas {max_stale_sec / 60.0:.1f}m). Evaluasi tick ditangguhkan hingga feed fresh."
                    )

                # 2. Notifikasi Telegram (Kirim saat pertama kali terdeteksi atau reminder tiap 30 menit)
                if not self._is_feed_stale or (curr_sec - self._last_stale_tele_warn >= 1800.0):
                    self._is_feed_stale = True
                    self._last_stale_tele_warn = curr_sec
                    last_candle_str = last_candle_time.strftime("%Y-%m-%d %H:%M:%S UTC") if hasattr(last_candle_time, "strftime") else str(last_candle_time)
                    if hasattr(self.telegram, "notify_stale_data_warning") and self.telegram.is_configured:
                        self.telegram.notify_stale_data_warning(
                            symbol=lcfg.SYMBOL,
                            lag_minutes=round(lag_seconds / 60.0, 1),
                            last_candle_time_str=last_candle_str,
                            max_allowed_minutes=round(max_stale_sec / 60.0, 1),
                        )
                return False
            else:
                # 3. Notifikasi Pemulihan saat feed kembali normal (Recovery)
                if self._is_feed_stale:
                    self._is_feed_stale = False
                    self.logger.info(
                        f"[✅ FEED RECOVERED] Feed candle M5 kembali fresh (Lag: {lag_seconds / 60.0:.1f}m). Melanjutkan trading normal."
                    )
                    if hasattr(self.telegram, "notify_stale_data_recovered") and self.telegram.is_configured:
                        self.telegram.notify_stale_data_recovered(
                            symbol=lcfg.SYMBOL,
                            lag_minutes=round(lag_seconds / 60.0, 1),
                        )

        curr_time_sec = time.time()
        if curr_time_sec - self.last_heartbeat_time >= 60.0:
            self.last_heartbeat_time = curr_time_sec
            active_session = self._get_active_session_name(now_utc)
            self.logger.info(f"Heartbeat | Bid: {tick['bid']:.2f} | Ask: {tick['ask']:.2f} | Spread: ${tick['spread']:.2f} | Sesi: {active_session}")

        # 1. KELOLA POSISI AKTIF & PENDING ORDERS OCO SECARA POLIMORFIK
        open_positions = self.connector.get_open_positions(lcfg.MAGIC_NUMBER)
        open_pendings = self.connector.get_open_pending_orders(lcfg.MAGIC_NUMBER) if hasattr(self.connector, "get_open_pending_orders") else []

        self.position_manager.track_and_notify_positions(open_positions)

        # Polimorfik OCO Cancellation untuk setiap strategi yang mendukung
        for strat in self.strategies:
            strat.handle_oco(open_positions, open_pendings, self.connector)

        # Polimorfik Position Exit Management
        if open_positions:
            self.position_manager.manage_open_positions(open_positions, df_m5, now_utc, self.today_schedule, self.strategies)

        # Cek Daily Loss Circuit Breaker
        acc = self.connector.get_account_status()
        if acc:
            tripped = self.risk_manager.check_daily_circuit_breaker(acc.equity, today_date)
            if tripped:
                for strat in self.strategies:
                    strat.trades_today = True

        # 2. EVALUASI SINYAL ENTRI BARU SECARA POLIMORFIK
        is_in_active_window = self._is_in_any_active_window(now_utc)
        if len(open_positions) < lcfg.MAX_OPEN_TRADES and not self.risk_manager.daily_circuit_breaker_tripped:
            equity = acc.equity if acc else 1000.0
            for strat in self.strategies:
                if not strat.can_trade():
                    continue
                if strat.reconcile_broker_orders(self.connector, lcfg.MAGIC_NUMBER):
                    continue

                intent = strat.evaluate_entry(
                    df_m5=df_m5,
                    tick=tick,
                    equity=equity,
                    now_utc=now_utc,
                    schedule=self.today_schedule,
                    open_pendings=open_pendings,
                    broker=self.connector,
                )
                if intent:
                    self._dispatch_order_intent(strat, intent)

        # 3. Cek apakah Box Opening Range telah terbentuk untuk London & New York
        for strat in self.strategies:
            sid = strat.strategy_id
            if sid in self._or_notified and not self._or_notified[sid]:
                or_h = getattr(strat, "or_high", None)
                or_l = getattr(strat, "or_low", None)
                or_r = getattr(strat, "or_range", None)
                if or_h is not None and or_l is not None and or_r is not None and or_r > 0:
                    self._or_notified[sid] = True
                    self.telegram.notify_or_formed(
                        session_name=strat.name,
                        or_high=or_h,
                        or_low=or_l,
                        or_range=or_r,
                    )

        return is_in_active_window

    def start(self):
        """Memulai loop eksekusi live bot."""
        if not self._acquire_pid_lock():
            sys.exit(1)
        atexit.register(self._release_pid_lock)

        if getattr(lcfg, "DISABLE_QUICK_EDIT", True):
            if disable_quick_edit_mode():
                self.logger.info("[🛡️ QUICK-EDIT PROTECTION] QuickEdit Mode dinonaktifkan (Terminal kebal freeze mouse).")

        tg_status = f"ON ({self.telegram.mode} - Option A)" if self.telegram.is_configured else "OFF"
        banner = (
            f"\n{'=' * 76}\n"
            f"   QUANTITATIVE MASTER PORTFOLIO — INSTITUTIONAL LIVE TRADER (MT5)\n"
            f"   Simbol: {lcfg.SYMBOL} | Magic: {lcfg.MAGIC_NUMBER}\n"
            f"   Mode Eksekusi Breakout : [{lcfg.BREAKOUT_EXECUTION_MODE}]\n"
            f"   Dynamic DST Tracking   : [{'ON (Wall Street Local Time)' if lcfg.USE_DYNAMIC_DST else 'OFF'}]\n"
            f"   Mode Trading           : {'[DRY RUN - SIMULASI]' if lcfg.DRY_RUN else '[REAL ORDER EXECUTION]'}\n"
            f"   Telegram Notifier      : [{tg_status}]\n"
            f"   Dual Logging           : [ON -> File: {getattr(lcfg, 'LOG_DIR', 'logs')} | Retensi: {getattr(lcfg, 'LOG_BACKUP_COUNT_DAYS', 30)} hari]\n"
            f"   Trade Journal CSV      : [ON -> {getattr(lcfg, 'TRADE_JOURNAL_FILE', 'logs/live_trade_journal.csv')}]\n"
            f"   Architecture           : [PURE STRATEGY COMPOSITION — {len(self.strategies)} STRATEGIES]\n"
            f"{'=' * 76}\n"
        )
        print(banner)
        self.logger.info("Bot Live Execution Engine diinisialisasi.")

        if not self.connector.connect():
            self.logger.error("[X] GAGAL: Tidak dapat terhubung ke MetaTrader 5. Pastikan MT5 terbuka dan login.")
            self.telegram.notify_critical_alert("Koneksi MT5 Gagal", "Bot tidak dapat terhubung ke terminal MetaTrader 5.")
            sys.exit(1)

        acc = self.connector.get_account_status()
        if acc:
            self.logger.info(f"[✓] Terhubung ke Akun : {acc.login} ({acc.server})")
            self.logger.info(f"    Saldo Akun        : ${acc.balance:,.2f} {acc.currency}")
            self.logger.info(f"    Ekuitas Akun      : ${acc.equity:,.2f} {acc.currency}")
            self.logger.info(f"    Margin Bebas      : ${acc.free_margin:,.2f} {acc.currency}")

            if not acc.trade_allowed:
                warn_msg = (
                    "\n" + "!" * 76 + "\n"
                    "  [⚠️ PERINGATAN PENTING] FITUR 'ALGO TRADING' DI MT5 SAAT INI NONAKTIF!\n"
                    "  Silakan KLIK tombol 'Algo Trading' pada toolbar MT5 hingga berwarna HIJAU.\n"
                    "!" * 76 + "\n"
                )
                print(warn_msg)
                self.logger.warning("[⚠️ ALGO TRADING DISABLED] Tombol 'Algo Trading' di terminal MT5 belum aktif!")

            if self.telegram.is_configured:
                ok = self.telegram.notify_startup(
                    account=acc.login,
                    server=acc.server,
                    balance=acc.balance,
                    equity=acc.equity,
                    symbol=lcfg.SYMBOL,
                    active_strategies=[s.name for s in self.strategies],
                )
                if ok:
                    self.logger.info("[📱 TELEGRAM] Notifikasi startup berhasil dikirim ke Telegram.")
                else:
                    self.logger.warning("[⚠️ TELEGRAM] Gagal mengirim notifikasi startup ke Telegram.")

        today_utc = datetime.now(timezone.utc).date()
        self.current_trading_day = today_utc
        self.today_schedule = SessionScheduleManager.get_today_schedule(today_utc)
        self._load_or_init_daily_circuit_breaker(today_utc)
        self._sync_state_from_broker()

        self.logger.info("[*] Memulai loop pemantauan pasar real-time (Tekan Ctrl+C untuk stop)...")

        try:
            while True:
                now_utc = datetime.now(timezone.utc)

                if self._is_market_closed_weekend(now_utc):
                    self._weekend_standby_cycle(now_utc)
                    time.sleep(60.0)
                    continue

                is_active_window = self._tick_cycle(now_utc)
                sleep_duration = lcfg.POLL_INTERVAL_FAST_SEC if is_active_window else lcfg.POLL_INTERVAL_IDLE_SEC
                time.sleep(sleep_duration)
        except KeyboardInterrupt:
            self.logger.info("\n[!] Perintah berhenti diterima. Mematikan bot...")
            acc = self.connector.get_account_status()
            bal = acc.balance if acc else None
            eq = acc.equity if acc else None
            if self.telegram.is_configured:
                self.telegram.notify_shutdown(reason="Manual Stop (Ctrl+C)", balance=bal, equity=eq)
                self.logger.info("[📱 TELEGRAM] Notifikasi shutdown terkirim ke Telegram.")
        except Exception as e:
            err_msg = f"Runtime loop exception: {str(e)}"
            self.logger.critical(f"\n[💥 CRITICAL EXCEPTION] {err_msg}")
            acc = self.connector.get_account_status()
            bal = acc.balance if acc else None
            eq = acc.equity if acc else None
            self.telegram.notify_shutdown(reason=f"Critical Error: {str(e)}", balance=bal, equity=eq)
            self.telegram.notify_critical_alert("Runtime Exception", err_msg)
            raise e
        finally:
            self.connector.shutdown()
            self._release_pid_lock()
            self.logger.info("[✓] Koneksi MT5 ditutup dengan aman. Bot berhenti.")


if __name__ == "__main__":
    bot = LivePortfolioTrader()
    bot.start()
