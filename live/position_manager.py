"""
Live Position Lifecycle & Exit Manager
======================================
Pengawas posisi trading aktif dan eksekusi exit khusus:
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

from configs import live_config as lcfg
from engine.asia.indicators import compute_all as compute_asian_indicators


class PositionManagementMixin:
    """Mixin pengawas dan eksekutor penutupan posisi aktif serta pembatalan pending OCO."""

    def _track_and_notify_positions(self, current_open_positions: list):
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

                # Kirim notifikasi Telegram saat posisi terisi (Entry)
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

                # Catat ke Trade Journal CSV & File Log
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
                self.logger.info(f"[🚀 POSISI TERISI] {sess} {dir_str} {p.volume:.2f} Lot @ {p.price_open:.3f} | Ticket: {ticket} | SL: {p.sl:.3f} | TP: {p.tp:.3f}")

        # 2. Deteksi posisi yang baru saja ditutup (Exit)
        closed_tickets = [t for t in list(self.tracked_positions.keys()) if t not in current_tickets]
        for ticket in closed_tickets:
            info = self.tracked_positions[ticket]
            deals = mt5.history_deals_get(position=ticket)
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
            acc = self.connector.get_account_status()
            curr_bal = acc.balance if acc else 0.0

            # Kirim notifikasi Telegram saat posisi selesai (Exit)
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

            # Catat ke Trade Journal CSV & File Log
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
            self.logger.info(f"[🎯 POSISI SELESAI] {info['session']} Ticket {ticket} -> Net PnL: ${pnl_usd:+.2f} ({r_mult:+.2f}R) | Alasan: {reason}")

            del self.tracked_positions[ticket]

    def _handle_oco_cancellation(self, open_positions: list, open_pendings: list):
        """Jika salah satu order stop terpicu dan aktif, batalkan pending order seberangnya."""
        for pos in open_positions:
            comm = pos.comment or ""
            if "London" in comm:
                # Batalkan semua pending order London yang masih tersisa
                for pend in open_pendings:
                    if "London" in (pend.comment or ""):
                        self.logger.info(f"[⚡ OCO TRIGGERED] Posisi London aktif (Ticket {pos.ticket}). Membatalkan Pending Order Ticket {pend.ticket}...")
                        self.connector.cancel_pending_order(pend.ticket)
                        self.trades_today["LONDON"] = True
            elif "NY" in comm:
                # Batalkan semua pending order NY yang masih tersisa
                for pend in open_pendings:
                    if "NY" in (pend.comment or ""):
                        self.logger.info(f"[⚡ OCO TRIGGERED] Posisi NY aktif (Ticket {pos.ticket}). Membatalkan Pending Order Ticket {pend.ticket}...")
                        self.connector.cancel_pending_order(pend.ticket)
                        self.trades_today["NY"] = True

    def _manage_open_positions(self, positions: list, df_m5: pd.DataFrame, now_utc: datetime):
        """Kelola kondisi keluar khusus (Z-Score Neutral, Time-Stop 60m, Hard Cut |Z|>=3.2, Session Cutoff)."""
        hm = (now_utc.hour, now_utc.minute)
        sched = self.today_schedule

        # Mendukung dynamic mock patch pada live.live_runner.compute_asian_indicators
        lr_mod = sys.modules.get("live.live_runner")
        indicator_func = getattr(lr_mod, "compute_asian_indicators", compute_asian_indicators)

        for pos in positions:
            ticket = pos.ticket
            profit = pos.profit
            comment = pos.comment or ""

            # 1. Kelola Posisi Asia Mean Reversion
            if "AsiaMR" in comment:
                # A. Hard Cutoff 06:00 UTC
                if hm >= sched.get("ASIAN_CUTOFF", (6, 0)):
                    self.logger.info(f"[!] Session Cutoff Asia (06:00 UTC) tercapai. Menutup Ticket {ticket} (PnL: ${profit:+.2f})...")
                    res = self.connector.close_position(ticket, comment="Cutoff-06:00")
                    if not res.success:
                        self.logger.error(f"[X] Gagal menutup posisi Cutoff Ticket {ticket}: {res.comment}")
                    continue

                # Ambil data indikator Asia
                df_asia = indicator_func(df_m5)
                latest_z = float(df_asia["zscore"].iloc[-2]) if len(df_asia) >= 2 else float(df_asia["zscore"].iloc[-1])
                is_buy = (pos.type == mt5.ORDER_TYPE_BUY)

                # B. Time Stop (60 Menit - Point P1-001 Audit)
                offset_sec = self.connector.get_broker_server_utc_offset_seconds()
                pos_open_utc_ts = pos.time - offset_sec
                duration_min = (now_utc.timestamp() - pos_open_utc_ts) / 60.0
                max_duration = getattr(lcfg, "ASIA_MAX_DURATION_MIN", 60)
                if duration_min >= max_duration:
                    self.logger.info(f"[⏱️ TIME-STOP ASIA] Durasi trading {duration_min:.1f}m >= {max_duration}m. Menutup Ticket {ticket} (PnL: ${profit:+.2f})...")
                    res = self.connector.close_position(ticket, comment="TimeStop-60m")
                    if not res.success:
                        self.logger.error(f"[X] Gagal menutup posisi TimeStop Ticket {ticket}: {res.comment}")
                    continue

                # C. Hard Cut (|Z| >= 3.2 - Point P1-001 Audit)
                z_hard_cut = getattr(lcfg, "ASIA_Z_HARD_CUT", 3.2)
                if (is_buy and latest_z <= -z_hard_cut) or (not is_buy and latest_z >= z_hard_cut):
                    self.logger.warning(f"[💥 HARD-CUT ASIA] Z-Score ekstrim ({latest_z:.2f}) melampaui limit {z_hard_cut}. Menutup Ticket {ticket} (PnL: ${profit:+.2f})...")
                    res = self.connector.close_position(ticket, comment="HardCut-Z3.2")
                    if not res.success:
                        self.logger.error(f"[X] Gagal menutup posisi HardCut Ticket {ticket}: {res.comment}")
                    continue

                # D. Smart Exit Z-score Mean Reversion (Parity: [-0.5, 0.5])
                z_exit_thresh = getattr(lcfg, "ASIA_Z_EXIT_THRESHOLD", 0.5)
                if is_buy and latest_z >= -z_exit_thresh:
                    self.logger.info(f"[🎯 TP MEAN-REVERSION ASIA] Z-Score netral ({latest_z:.2f} >= -{z_exit_thresh}). Menutup Ticket {ticket} (PnL: ${profit:+.2f})...")
                    res = self.connector.close_position(ticket, comment="TP-Z-Neutral")
                    if not res.success:
                        self.logger.error(f"[X] Gagal menutup posisi TP-Z Ticket {ticket}: {res.comment}")
                    continue
                elif not is_buy and latest_z <= z_exit_thresh:
                    self.logger.info(f"[🎯 TP MEAN-REVERSION ASIA] Z-Score netral ({latest_z:.2f} <= +{z_exit_thresh}). Menutup Ticket {ticket} (PnL: ${profit:+.2f})...")
                    res = self.connector.close_position(ticket, comment="TP-Z-Neutral")
                    if not res.success:
                        self.logger.error(f"[X] Gagal menutup posisi TP-Z Ticket {ticket}: {res.comment}")
                    continue

            # 2. Kelola Posisi London Pit ORB
            elif "London" in comment:
                if hm >= sched.get("LONDON_CUTOFF", (11, 25)):
                    self.logger.info(f"[!] Session Cutoff London tercapai. Menutup Ticket {ticket} (PnL: ${profit:+.2f})...")
                    res = self.connector.close_position(ticket, comment="Cutoff-London")
                    if not res.success:
                        self.logger.error(f"[X] Gagal menutup posisi Cutoff London Ticket {ticket}: {res.comment}")
                    continue

            # 3. Kelola Posisi New York ORB
            elif "NY" in comment:
                if hm >= sched.get("NY_CUTOFF", (12, 25)):
                    self.logger.info(f"[!] Session Cutoff NY tercapai. Menutup Ticket {ticket} (PnL: ${profit:+.2f})...")
                    res = self.connector.close_position(ticket, comment="Cutoff-NY")
                    if not res.success:
                        self.logger.error(f"[X] Gagal menutup posisi Cutoff NY Ticket {ticket}: {res.comment}")
                    continue
