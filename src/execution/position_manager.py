"""
Live Position Lifecycle & Exit Manager
======================================
Pengawas posisi trading aktif dan eksekusi exit:
1. Asia MR Time-Stop 60 Menit (Point P1-001 Audit)
2. Asia MR Hard-Cut Z-Score (|Z| >= 3.2)
3. Asia MR Dynamic Z-Score Mean Reversion Exit ([-0.5, 0.5])
4. Session Cutoffs (Asia 06:00 UTC, London 11:25 UTC, NY Cutoff)
5. Pending Stop OCO Cancellation Handler (Point #1 Audit)
6. Entry & Exit Telegram Notifier & Trade Journal Logger
"""

import sys
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import pandas as pd
import MetaTrader5 as mt5

from src.execution import config as lcfg
from src.core.types import ExitIntent, OrderResult
from src.strategies.asian_mr.signals import evaluate_asian_exit
from src.strategies.london_orb.signals import evaluate_london_exit
from src.strategies.ny_orb.signals import evaluate_ny_exit


class PositionManager:
    """
    Komponen Pengawas Siklus Hidup Posisi & Eksekusi Exit (Service Component).
    Merekam posisi aktif, notifikasi Telegram, pencatatan jurnal,
    serta eksekusi penutupan order berdasarkan ExitIntent.
    """

    def __init__(self, connector=None, telegram=None, journal=None, logger=None):
        self.connector = connector
        self.telegram = telegram
        self.journal = journal
        self.logger = logger
        self.tracked_positions: Dict[int, Dict[str, Any]] = {}

    def track_and_notify_positions(self, current_open_positions: list):
        """Pantau posisi baru untuk notifikasi Entry, dan deteksi penutupan untuk notifikasi Exit."""
        current_tickets = set()

        # 1. Deteksi posisi baru (Entry)
        for p in current_open_positions:
            ticket = p.ticket
            current_tickets.add(ticket)
            if ticket not in self.tracked_positions:
                comm = p.comment or ""
                sess = "Asia MR" if "Asia" in comm else ("London ORB" if "London" in comm else "New York ORB")
                dir_str = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
                risk_usd = abs(p.price_open - p.sl) * p.volume * lcfg.POINT_VALUE if p.sl else 0.0

                self.tracked_positions[ticket] = {
                    "session": sess,
                    "direction": dir_str,
                    "volume": p.volume,
                    "price_open": p.price_open,
                    "sl": p.sl,
                    "tp": p.tp,
                    "risk_usd": risk_usd,
                    "comment": comm,
                    "symbol": p.symbol,
                }

                if self.telegram and hasattr(self.telegram, "notify_entry"):
                    self.telegram.notify_entry(
                        session=sess,
                        direction=dir_str,
                        volume=p.volume,
                        price=p.price_open,
                        sl=p.sl,
                        tp=p.tp,
                        risk_usd=risk_usd,
                        ticket=ticket,
                        symbol=p.symbol,
                    )

                if self.journal and hasattr(self.journal, "record_entry"):
                    self.journal.record_entry(
                        session=sess,
                        ticket=ticket,
                        action=dir_str,
                        volume=p.volume,
                        open_price=p.price_open,
                        sl=p.sl,
                        tp=p.tp,
                        slippage_pts=0.0,
                        comment=comm,
                    )
                if self.logger:
                    self.logger.info(f"[🚀 POSISI TERISI] {sess} {dir_str} {p.volume:.2f} Lot @ {p.price_open:.3f} | Ticket: {ticket} | SL: {p.sl:.3f} | TP: {p.tp:.3f}")

        # 2. Deteksi posisi yang baru saja ditutup (Exit)
        closed_tickets = [t for t in list(self.tracked_positions.keys()) if t not in current_tickets]
        for ticket in closed_tickets:
            info = self.tracked_positions[ticket]
            deals = mt5.history_deals_get(position=ticket) if hasattr(mt5, "history_deals_get") else None
            exit_price = info["price_open"]
            pnl_usd = 0.0
            reason = "Position Closed"

            if deals:
                exit_deals = [d for d in deals if d.entry == 1]
                if exit_deals:
                    last_deal = exit_deals[-1]
                    exit_price = last_deal.price
                    pnl_usd = last_deal.profit
                    deal_comm = (last_deal.comment or "").lower()
                    if "[tp" in deal_comm or "tp" in deal_comm:
                        reason = "Target Hit (TP)"
                    elif "[sl" in deal_comm or "sl" in deal_comm:
                        reason = "Stop Loss (SL)"
                    elif "cutoff" in deal_comm:
                        reason = f"Session Cutoff ({last_deal.comment})"
                    elif "z-neutral" in deal_comm:
                        reason = "Z-Neutral Mean Reversion"
                    else:
                        reason = last_deal.comment or "Position Closed"

            r_mult = (pnl_usd / info["risk_usd"]) if info["risk_usd"] > 0 else 0.0
            curr_bal = 0.0
            if self.connector and hasattr(self.connector, "get_account_status"):
                acc = self.connector.get_account_status()
                curr_bal = acc.balance if acc else 0.0

            if self.telegram and hasattr(self.telegram, "notify_exit"):
                self.telegram.notify_exit(
                    session=info["session"],
                    direction=info["direction"],
                    volume=info["volume"],
                    open_price=info["price_open"],
                    close_price=exit_price,
                    pnl_usd=pnl_usd,
                    r_multiple=r_mult,
                    reason=reason,
                    ticket=ticket,
                    balance=curr_bal,
                    symbol=info.get("symbol", lcfg.SYMBOL),
                )

            if self.journal and hasattr(self.journal, "record_exit"):
                self.journal.record_exit(
                    session=info["session"],
                    ticket=ticket,
                    action=info["direction"],
                    volume=info["volume"],
                    open_price=info["price_open"],
                    close_price=exit_price,
                    sl=info["sl"],
                    tp=info["tp"],
                    net_pnl_usd=pnl_usd,
                    r_multiple=r_mult,
                    exit_reason=reason,
                    slippage_pts=0.0,
                    comment=info.get("comment", ""),
                )
            if self.logger:
                self.logger.info(f"[🎯 POSISI SELESAI] {info['session']} Ticket {ticket} -> Net PnL: ${pnl_usd:+.2f} ({r_mult:+.2f}R) | Alasan: {reason}")

            del self.tracked_positions[ticket]

    def execute_exit(self, position: Any, exit_intent: ExitIntent) -> bool:
        """Eksekusi penutupan posisi via broker adapter berdasarkan ExitIntent."""
        if not exit_intent.should_exit:
            return False

        ticket = position.ticket
        profit = getattr(position, "profit", 0.0)

        if self.logger:
            if exit_intent.comment == "TimeStop-60m":
                self.logger.info(f"[⏱️ TIME-STOP ASIA] {exit_intent.reason}. Menutup Ticket {ticket} (PnL: ${profit:+.2f})...")
            elif exit_intent.comment == "HardCut-Z3.2":
                self.logger.warning(f"[💥 HARD-CUT ASIA] {exit_intent.reason}. Menutup Ticket {ticket} (PnL: ${profit:+.2f})...")
            elif exit_intent.comment == "TP-Z-Neutral":
                self.logger.info(f"[🎯 TP MEAN-REVERSION ASIA] {exit_intent.reason}. Menutup Ticket {ticket} (PnL: ${profit:+.2f})...")
            elif "Cutoff" in exit_intent.comment:
                self.logger.info(f"[!] {exit_intent.reason} tercapai. Menutup Ticket {ticket} (PnL: ${profit:+.2f})...")
            else:
                self.logger.info(f"[🎯 EXIT TRIGGERED] {exit_intent.reason}. Menutup Ticket {ticket} (PnL: ${profit:+.2f})...")

        if self.connector:
            res = self.connector.close_position(ticket, comment=exit_intent.comment)
            if not res.success and self.logger:
                self.logger.error(f"[X] Gagal menutup posisi Ticket {ticket}: {res.comment}")
            return res.success
        return False

    def handle_oco_cancellation(self, open_positions: list, open_pendings: list, trades_today: Optional[dict] = None):
        """Jika salah satu order stop terpicu dan aktif, batalkan pending order seberangnya."""
        if not self.connector:
            return

        for pos in open_positions:
            comm = pos.comment or ""
            if "London" in comm:
                for pend in open_pendings:
                    if "London" in (pend.comment or ""):
                        if self.logger:
                            self.logger.info(f"[⚡ OCO TRIGGERED] Posisi London aktif (Ticket {pos.ticket}). Membatalkan Pending Order Ticket {pend.ticket}...")
                        self.connector.cancel_pending_order(pend.ticket)
                        if trades_today is not None:
                            trades_today["LONDON"] = True
            elif "NY" in comm:
                for pend in open_pendings:
                    if "NY" in (pend.comment or ""):
                        if self.logger:
                            self.logger.info(f"[⚡ OCO TRIGGERED] Posisi NY aktif (Ticket {pos.ticket}). Membatalkan Pending Order Ticket {pend.ticket}...")
                        self.connector.cancel_pending_order(pend.ticket)
                        if trades_today is not None:
                            trades_today["NY"] = True

    def manage_open_positions(self, positions: list, df_m5: pd.DataFrame, now_utc: datetime, today_schedule: dict, strategies: Optional[list] = None):
        """Kelola kondisi keluar khusus melalui domain strategy evaluator (ExitIntent)."""
        sched = today_schedule
        runner_mod = sys.modules.get("src.execution.runner") or sys.modules.get("live.live_runner")
        indicator_func = getattr(runner_mod, "compute_asian_indicators", None)

        offset_sec = 0
        if self.connector and hasattr(self.connector, "get_broker_server_utc_offset_seconds"):
            offset_sec = self.connector.get_broker_server_utc_offset_seconds()

        for pos in positions:
            comment = pos.comment or ""
            exit_intent: Optional[ExitIntent] = None

            # Jika strategies list disediakan, delegasikan ke strategy yang cocok
            if strategies:
                matched_strat = None
                for strat in strategies:
                    if strat.strategy_id == "ASIAN" and "AsiaMR" in comment:
                        matched_strat = strat
                        break
                    elif strat.strategy_id == "LONDON" and "London" in comment:
                        matched_strat = strat
                        break
                    elif strat.strategy_id == "NY" and "NY" in comment:
                        matched_strat = strat
                        break

                if matched_strat:
                    exit_intent = matched_strat.evaluate_exit(
                        position=pos,
                        df_m5=df_m5,
                        now_utc=now_utc,
                        broker_utc_offset_sec=offset_sec,
                        schedule=sched,
                    )

            if exit_intent is None:
                # Direct fallback evaluation
                if "AsiaMR" in comment:
                    exit_intent = evaluate_asian_exit(
                        position=pos,
                        df_m5=df_m5,
                        now_utc=now_utc,
                        broker_utc_offset_sec=offset_sec,
                        cutoff_hm=sched.get("ASIAN_CUTOFF", (6, 0)),
                        max_duration_min=getattr(lcfg, "ASIA_MAX_DURATION_MIN", 60),
                        z_hard_cut=getattr(lcfg, "ASIA_Z_HARD_CUT", 3.2),
                        z_exit_thresh=getattr(lcfg, "ASIA_Z_EXIT_THRESHOLD", 0.5),
                        indicator_func=indicator_func,
                    )
                elif "London" in comment:
                    exit_intent = evaluate_london_exit(
                        position=pos,
                        now_utc=now_utc,
                        cutoff_hm=sched.get("LONDON_CUTOFF", (11, 25)),
                    )
                elif "NY" in comment:
                    exit_intent = evaluate_ny_exit(
                        position=pos,
                        now_utc=now_utc,
                        cutoff_hm=sched.get("NY_CUTOFF", (12, 25)),
                    )

            if exit_intent and exit_intent.should_exit:
                self.execute_exit(pos, exit_intent)


class PositionManagementMixin:
    """Mixin delegator untuk kompatibilitas mundur dengan kode atau test legacy."""

    def _get_position_manager(self) -> PositionManager:
        if not hasattr(self, "_position_manager_inst") or self._position_manager_inst is None:
            self._position_manager_inst = getattr(self, "position_manager", None)
            if self._position_manager_inst is None:
                self._position_manager_inst = PositionManager(
                    connector=getattr(self, "connector", None),
                    telegram=getattr(self, "telegram", None),
                    journal=getattr(self, "journal", None),
                    logger=getattr(self, "logger", None),
                )
                self._position_manager_inst.tracked_positions = getattr(self, "tracked_positions", {})
        return self._position_manager_inst

    def _track_and_notify_positions(self, current_open_positions: list):
        pm = self._get_position_manager()
        pm.tracked_positions = self.tracked_positions
        pm.track_and_notify_positions(current_open_positions)
        self.tracked_positions = pm.tracked_positions

    def _handle_oco_cancellation(self, open_positions: list, open_pendings: list):
        pm = self._get_position_manager()
        pm.handle_oco_cancellation(open_positions, open_pendings, getattr(self, "trades_today", None))

    def _manage_open_positions(self, positions: list, df_m5: pd.DataFrame, now_utc: datetime):
        pm = self._get_position_manager()
        sched = getattr(self, "today_schedule", {})
        strats = getattr(self, "strategies", None)
        pm.manage_open_positions(positions, df_m5, now_utc, sched, strategies=strats)
