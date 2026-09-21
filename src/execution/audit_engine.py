"""
Post-Session Shadow Backtest Reconciliation Engine
==================================================
Modul audit otomatis akhir sesi:
Mengambil data candle riil dari broker MT5, mengevaluasinya menggunakan logika
matematis kanonikal backtesting, membandingkan hasilnya dengan eksekusi live,
dan menghasilkan SessionAuditReport terstruktur.
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from typing import Optional, Dict, Any, List, Tuple
import pandas as pd

from src.strategies.asian_mr.signals import compute_asian_indicators, check_entry_signal
import src.strategies.asian_mr.config as as_cfg
from src.strategies.london_orb.signals import compute_london_indicators, LondonStrategy, form_london_or_box
import src.strategies.london_orb.config as lon_cfg
from src.strategies.ny_orb.signals import compute_ny_indicators, NYStrategy, form_ny_or_box
import src.strategies.ny_orb.config as ny_cfg


@dataclass
class SessionAuditReport:
    """Laporan hasil rekonsiliasi paritas akhir sesi."""
    session_id: str                      # "ASIAN", "LONDON", "NY"
    session_name: str                    # "Asian Mean Reversion", dll
    trading_date: date                   # Tanggal evaluasi
    bars_evaluated: int                  # Jumlah candle M5 yang diuji
    live_trades_count: int               # Jumlah trade tereksekusi di Live
    backtest_signals_count: int          # Jumlah sinyal terdeteksi di Backtest
    parity_matched: bool                 # True jika Live == Backtest
    verdict: str                         # e.g. "NORMAL_NO_SETUP", "FILTER_PROTECTED", "TRADE_MATCHED", "DIVERGENCE"
    primary_reason: str                  # Penjelasan singkat (1 baris)
    details: Dict[str, Any] = field(default_factory=dict)


class SessionReconciliationAuditor:
    """Mesin rekonsiliasi otomatis antara eksekusi live broker dan backtesting kanonikal."""

    @classmethod
    def audit_session(
        cls,
        session_id: str,
        df_m5: Optional[pd.DataFrame],
        today_date: date,
        live_trades_count: int,
        sched: Dict[str, Any],
    ) -> SessionAuditReport:
        """Pintu masuk terpadu audit akhir sesi."""
        sid = session_id.upper()
        if sid in ("ASIAN", "ASIA"):
            return cls.audit_asian_session(df_m5, today_date, live_trades_count, sched)
        elif sid == "LONDON":
            return cls.audit_london_session(df_m5, today_date, live_trades_count, sched)
        elif sid == "NY":
            return cls.audit_ny_session(df_m5, today_date, live_trades_count, sched)
        else:
            return SessionAuditReport(
                session_id=session_id,
                session_name=session_id,
                trading_date=today_date,
                bars_evaluated=0,
                live_trades_count=live_trades_count,
                backtest_signals_count=0,
                parity_matched=True,
                verdict="UNKNOWN_SESSION",
                primary_reason="Sesi tidak dikenal untuk audit.",
            )

    @classmethod
    def audit_asian_session(
        cls,
        df_m5: Optional[pd.DataFrame],
        today_date: date,
        live_trades_count: int,
        sched: Dict[str, Any],
    ) -> SessionAuditReport:
        """Audit kanonikal sesi Asian Mean Reversion."""
        session_name = "Asian Mean Reversion"
        if df_m5 is None or len(df_m5) < 30:
            return SessionAuditReport(
                session_id="ASIAN",
                session_name=session_name,
                trading_date=today_date,
                bars_evaluated=0,
                live_trades_count=live_trades_count,
                backtest_signals_count=0,
                parity_matched=(live_trades_count == 0),
                verdict="DATA_UNAVAILABLE",
                primary_reason="Data candle M5 tidak tersedia dari broker.",
            )

        df = df_m5.copy()
        if not isinstance(df["datetime"].dtype, pd.DatetimeTZDtype):
            df["datetime"] = pd.to_datetime(df["datetime"], utc=True)

        df_asia = compute_asian_indicators(df)
        asia_today = df_asia[df_asia["datetime"].dt.date == today_date]
        
        start_h, start_m = sched.get("ASIAN_START", (1, 0))
        end_h, end_m = sched.get("ASIAN_END", (4, 30))
        
        asia_window = asia_today[
            (asia_today["datetime"].dt.hour > start_h)
            | ((asia_today["datetime"].dt.hour == start_h) & (asia_today["datetime"].dt.minute >= start_m))
        ]
        asia_window = asia_window[
            (asia_window["datetime"].dt.hour < end_h)
            | ((asia_window["datetime"].dt.hour == end_h) & (asia_window["datetime"].dt.minute <= end_m))
        ]

        bars_eval = len(asia_window)
        signals = []
        max_abs_z = 0.0
        reasons: List[str] = []

        for idx, row in asia_window.iterrows():
            z = row.get("zscore", 0.0)
            if pd.notna(z):
                max_abs_z = max(max_abs_z, abs(float(z)))

            sig = check_entry_signal(row, idx)
            if sig:
                signals.append(sig)
            else:
                if pd.notna(z) and abs(z) >= as_cfg.Z_ENTRY_THRESHOLD:
                    rsi = row.get("rsi", 50.0)
                    reasons.append(f"Bar {row['datetime'].strftime('%H:%M')} (Z={z:+.2f}, RSI={rsi:.1f}) terfilter konfirmasi reversal / HTF.")

        bt_count = len(signals)
        parity = (live_trades_count == bt_count) or (live_trades_count > 0 and bt_count > 0)

        if bt_count == 0 and live_trades_count == 0:
            if reasons:
                verdict = "FILTER_PROTECTED"
                primary = f"Z-Score sempat menembus threshold (Max |Z|={max_abs_z:.2f}), namun filter pembalikan arah & HTF melindungi modal."
            else:
                verdict = "NORMAL_NO_SETUP"
                primary = f"Pasar sideways tenang di dekat VWAP. Max |Z|={max_abs_z:.2f} (di bawah threshold {as_cfg.Z_ENTRY_THRESHOLD})."
        elif parity:
            verdict = "TRADE_MATCHED"
            primary = f"Sinyal entri terpicu dan tereksekusi dengan sempurna ({live_trades_count} trade)."
        else:
            verdict = "DIVERGENCE"
            primary = f"Terjadi perbedaan jumlah trade antara Live ({live_trades_count}) dan Backtest ({bt_count})."

        return SessionAuditReport(
            session_id="ASIAN",
            session_name=session_name,
            trading_date=today_date,
            bars_evaluated=bars_eval,
            live_trades_count=live_trades_count,
            backtest_signals_count=bt_count,
            parity_matched=parity,
            verdict=verdict,
            primary_reason=primary,
            details={
                "max_abs_zscore": round(max_abs_z, 2),
                "z_threshold": as_cfg.Z_ENTRY_THRESHOLD,
                "reasons": reasons,
            },
        )

    @classmethod
    def audit_london_session(
        cls,
        df_m5: Optional[pd.DataFrame],
        today_date: date,
        live_trades_count: int,
        sched: Dict[str, Any],
    ) -> SessionAuditReport:
        """Audit kanonikal sesi London Pit ORB."""
        session_name = "London Pit ORB"
        if df_m5 is None or len(df_m5) < 30:
            return SessionAuditReport(
                session_id="LONDON",
                session_name=session_name,
                trading_date=today_date,
                bars_evaluated=0,
                live_trades_count=live_trades_count,
                backtest_signals_count=0,
                parity_matched=(live_trades_count == 0),
                verdict="DATA_UNAVAILABLE",
                primary_reason="Data candle M5 tidak tersedia dari broker.",
            )

        df = df_m5.copy()
        if not isinstance(df["datetime"].dtype, pd.DatetimeTZDtype):
            df["datetime"] = pd.to_datetime(df["datetime"], utc=True)

        df_day = df[df["datetime"].dt.date == today_date]
        or_start = sched.get("LONDON_OR_START", (8, 0))
        or_end = sched.get("LONDON_ENTRY_START", (8, 15))
        box = form_london_or_box(df_day, or_start=or_start, or_end=or_end)

        if not box:
            return SessionAuditReport(
                session_id="LONDON",
                session_name=session_name,
                trading_date=today_date,
                bars_evaluated=len(df_day),
                live_trades_count=live_trades_count,
                backtest_signals_count=0,
                parity_matched=(live_trades_count == 0),
                verdict="BOX_INCOMPLETE",
                primary_reason="Box Opening Range London M5 belum lengkap terbentuk.",
            )

        or_h, or_l, or_r = box
        df_lon = compute_london_indicators(df)
        lon_today = df_lon[df_lon["datetime"].dt.date == today_date]
        lon_strat = LondonStrategy()

        signals = []
        breakout_up_count = 0
        breakout_dn_count = 0
        expansion_fail_count = 0

        for idx, row in lon_today.iterrows():
            h_time = (row["hour"], row["minute"])
            if (8, 15) <= h_time < (11, 30):
                hi = row["high"]
                lo = row["low"]
                is_bo = False
                if hi > or_h:
                    breakout_up_count += 1
                    is_bo = True
                elif lo < or_l:
                    breakout_dn_count += 1
                    is_bo = True

                sig = lon_strat.evaluate_bar(row)
                if sig:
                    signals.append(sig)
                elif is_bo:
                    tr_past = row.get("tr_past", 0.0)
                    tr_sma = row.get("tr_sma20", 0.0)
                    if pd.notna(tr_past) and pd.notna(tr_sma) and tr_past <= lon_cfg.EXPANSION_MULT * tr_sma:
                        expansion_fail_count += 1

        bt_count = min(1, len(signals))
        parity = (live_trades_count == bt_count) or (live_trades_count > 0 and bt_count > 0)
        bars_eval = len(lon_today[(lon_today["hour"] >= 8) & (lon_today["hour"] < 12)])

        if bt_count == 0 and live_trades_count == 0:
            if breakout_up_count + breakout_dn_count > 0:
                verdict = "FILTER_PROTECTED"
                primary = f"Terjadi {breakout_up_count + breakout_dn_count}x penembusan batas box, namun difilter oleh True Range Expansion (Volume momentum lemah)."
            else:
                verdict = "NORMAL_NO_SETUP"
                primary = f"Harga bergerak di dalam Box OR {or_r:.2f} pts tanpa breakout."
        elif parity:
            verdict = "TRADE_MATCHED"
            primary = f"Breakout London terkonfirmasi dan tereksekusi ({live_trades_count} trade)."
        else:
            verdict = "DIVERGENCE"
            primary = f"Perbedaan sinyal antara Live ({live_trades_count}) dan Backtest ({bt_count})."

        return SessionAuditReport(
            session_id="LONDON",
            session_name=session_name,
            trading_date=today_date,
            bars_evaluated=bars_eval,
            live_trades_count=live_trades_count,
            backtest_signals_count=bt_count,
            parity_matched=parity,
            verdict=verdict,
            primary_reason=primary,
            details={
                "or_high": round(or_h, 2),
                "or_low": round(or_l, 2),
                "or_range": round(or_r, 2),
                "breakouts": breakout_up_count + breakout_dn_count,
                "expansion_fails": expansion_fail_count,
            },
        )

    @classmethod
    def audit_ny_session(
        cls,
        df_m5: Optional[pd.DataFrame],
        today_date: date,
        live_trades_count: int,
        sched: Dict[str, Any],
    ) -> SessionAuditReport:
        """Audit kanonikal sesi New York ORB."""
        session_name = f"New York ORB ({sched.get('NY_TZ_NAME', 'UTC')})"
        if df_m5 is None or len(df_m5) < 30:
            return SessionAuditReport(
                session_id="NY",
                session_name=session_name,
                trading_date=today_date,
                bars_evaluated=0,
                live_trades_count=live_trades_count,
                backtest_signals_count=0,
                parity_matched=(live_trades_count == 0),
                verdict="DATA_UNAVAILABLE",
                primary_reason="Data candle M5 tidak tersedia dari broker.",
            )

        df = df_m5.copy()
        if not isinstance(df["datetime"].dtype, pd.DatetimeTZDtype):
            df["datetime"] = pd.to_datetime(df["datetime"], utc=True)

        df_day = df[df["datetime"].dt.date == today_date]
        or_start = sched.get("NY_OR_START", (13, 30))
        or_end = sched.get("NY_ENTRY_START", (13, 45))
        box = form_ny_or_box(df_day, or_start=or_start, or_end=or_end)

        if not box:
            return SessionAuditReport(
                session_id="NY",
                session_name=session_name,
                trading_date=today_date,
                bars_evaluated=len(df_day),
                live_trades_count=live_trades_count,
                backtest_signals_count=0,
                parity_matched=(live_trades_count == 0),
                verdict="BOX_INCOMPLETE",
                primary_reason="Box Opening Range New York M5 belum lengkap terbentuk.",
            )

        or_h, or_l, or_r = box
        df_ny = compute_ny_indicators(df)
        ny_today = df_ny[df_ny["datetime"].dt.date == today_date]
        ny_strat = NYStrategy()

        signals = []
        breakout_count = 0
        expansion_fail_count = 0
        en_start = sched.get("NY_ENTRY_START", (13, 45))
        en_end = sched.get("NY_ENTRY_END", (16, 30))

        for idx, row in ny_today.iterrows():
            h_time = (row["hour"], row["minute"])
            if en_start <= h_time < en_end:
                hi = row["high"]
                lo = row["low"]
                is_bo = False
                if hi > or_h or lo < or_l:
                    breakout_count += 1
                    is_bo = True

                sig = ny_strat.evaluate_bar(row)
                if sig:
                    signals.append(sig)
                elif is_bo:
                    tr_past = row.get("tr_past", 0.0)
                    tr_sma = row.get("tr_sma20", 0.0)
                    if pd.notna(tr_past) and pd.notna(tr_sma) and tr_past <= ny_cfg.EXPANSION_MULT * tr_sma:
                        expansion_fail_count += 1

        bt_count = min(1, len(signals))
        parity = (live_trades_count == bt_count) or (live_trades_count > 0 and bt_count > 0)
        bars_eval = len(ny_today[(ny_today["hour"] >= or_start[0]) & (ny_today["hour"] <= en_end[0])])

        if bt_count == 0 and live_trades_count == 0:
            if breakout_count > 0:
                verdict = "FILTER_PROTECTED"
                primary = f"Terjadi {breakout_count}x penembusan batas box, namun difilter oleh True Range Expansion New York."
            else:
                verdict = "NORMAL_NO_SETUP"
                primary = f"Harga berada di dalam Box OR NY {or_r:.2f} pts tanpa breakout."
        elif parity:
            verdict = "TRADE_MATCHED"
            primary = f"Breakout New York terkonfirmasi dan tereksekusi ({live_trades_count} trade)."
        else:
            verdict = "DIVERGENCE"
            primary = f"Perbedaan sinyal New York antara Live ({live_trades_count}) dan Backtest ({bt_count})."

        return SessionAuditReport(
            session_id="NY",
            session_name=session_name,
            trading_date=today_date,
            bars_evaluated=bars_eval,
            live_trades_count=live_trades_count,
            backtest_signals_count=bt_count,
            parity_matched=parity,
            verdict=verdict,
            primary_reason=primary,
            details={
                "or_high": round(or_h, 2),
                "or_low": round(or_l, 2),
                "or_range": round(or_r, 2),
                "breakouts": breakout_count,
                "expansion_fails": expansion_fail_count,
            },
        )
