"""
Audit Parity Hari Ini (Live Data vs Backtest Strategy)
=====================================================
Skrip independen untuk membedah bar per bar M5 hari ini dari MT5
dan mencocokkan dengan aturan sinyal Backtesting (Asian MR, London ORB, NY ORB).
"""

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timezone
from src.execution import config as lcfg
from src.strategies.asian_mr.signals import compute_asian_indicators, check_entry_signal
import src.strategies.asian_mr.config as as_cfg
import src.strategies.london_orb.config as lon_cfg
import src.strategies.ny_orb.config as ny_cfg
from src.execution.scheduler import SessionScheduleManager


def audit():
    if not mt5.initialize():
        print("Gagal inisialisasi MT5")
        return

    rates = mt5.copy_rates_from_pos(lcfg.SYMBOL, mt5.TIMEFRAME_M5, 0, 500)
    mt5.shutdown()
    if rates is None or len(rates) == 0:
        print("Tidak ada data rates")
        return

    df = pd.DataFrame(rates)
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    today = datetime.now(timezone.utc).date()
    sched = SessionScheduleManager.get_today_schedule(today)

    print("=" * 60)
    print(f"   HASIL AUDIT DATA PASAR HARI INI ({today} UTC)")
    print("=" * 60)

    # 1. ASIAN MR
    print("\n--- [1] SESI ASIAN MEAN REVERSION (01:00 - 04:30 UTC) ---")
    df_asia = compute_asian_indicators(df)
    asia_today = df_asia[df_asia["datetime"].dt.date == today]
    asia_window = asia_today[
        (asia_today["datetime"].dt.hour >= 1)
        & (
            (asia_today["datetime"].dt.hour < 4)
            | ((asia_today["datetime"].dt.hour == 4) & (asia_today["datetime"].dt.minute <= 30))
        )
    ]
    print(f"• Total Candle M5 di Jendela Asia : {len(asia_window)} bar")
    signals = []
    reasons = []
    for idx, row in asia_window.iterrows():
        sig = check_entry_signal(row, idx)
        if sig:
            signals.append(sig)
        else:
            z = row.get("zscore", 0.0)
            rsi = row.get("rsi", 50.0)
            atr = row.get("atr", 0.0)
            atr_sma = row.get("atr_sma", 0.0)
            vol_ok = (atr >= as_cfg.ATR_MIN_THRESHOLD) and (atr <= atr_sma * as_cfg.ATR_ANOMALY_MULTIPLIER) if pd.notna(atr) and pd.notna(atr_sma) else False
            if abs(z) >= as_cfg.Z_ENTRY_THRESHOLD:
                reasons.append(
                    f"Bar {row['datetime'].strftime('%H:%M')} UTC -> Z-Score: {z:+.2f} (Memenuhi |Z|>={as_cfg.Z_ENTRY_THRESHOLD}), "
                    f"RSI: {rsi:.1f}, Vol_filter: {vol_ok}"
                )

    print(f"• Sinyal Terpicu di Backtest      : {len(signals)} trade")
    if len(signals) == 0:
        print("• Mengapa Tidak Ada Trade di Sesi Asia?")
        if reasons:
            print("  Detail candle yang sempat menyentuh Z-Score threshold tapi difilter:")
            for r in reasons:
                print("   -", r)
        else:
            z_min = asia_window["zscore"].min()
            z_max = asia_window["zscore"].max()
            print(f"  Z-Score bergerak antara [{z_min:.2f} s/d {z_max:.2f}]. Tidak ada yang menembus ambang batas |Z| >= 2.0.")

    # 2. LONDON ORB
    print("\n--- [2] SESI LONDON PIT ORB (08:00 - 11:30 UTC) ---")
    or_bars = df[
        (df["datetime"].dt.date == today)
        & (df["datetime"].dt.hour == 8)
        & (df["datetime"].dt.minute < 15)
    ]
    if len(or_bars) >= 2:
        or_h = or_bars["high"].max()
        or_l = or_bars["low"].min()
        or_r = or_h - or_l
        print(f"• Box Opening Range M5           : High = {or_h:.2f} | Low = {or_l:.2f} | Range = {or_r:.2f} pts (${or_r:.2f})")
        # Evaluasi menggunakan compute_london_indicators & LondonStrategy kanonikal
        from src.strategies.london_orb.signals import compute_london_indicators, LondonStrategy
        df_lon = compute_london_indicators(df)
        lon_strat = LondonStrategy()
        lon_today = df_lon[df_lon["datetime"].dt.date == today]
        lon_signals = []
        for idx, row in lon_today.iterrows():
            sig = lon_strat.evaluate_bar(row)
            if sig:
                lon_signals.append((row["datetime"], sig))

        print(f"• Total Sinyal London Terpicu di Backtest: {len(lon_signals)}")
        if len(lon_signals) == 0:
            print("• Mengapa Tidak Ada Trade di Sesi London?")
            # Cek filter ekspansi pada bar-bar yang menembus box
            for idx, row in lon_today.iterrows():
                h_time = (row["hour"], row["minute"])
                if (8, 15) <= h_time < (11, 30):
                    hi = row["high"]
                    lo = row["low"]
                    if hi > or_h or lo < or_l:
                        tr_past = row.get("tr_past", 0.0)
                        tr_sma = row.get("tr_sma20", 0.0)
                        cutoff = lon_cfg.EXPANSION_MULT * tr_sma
                        passed = tr_past > cutoff
                        side = "Breakout HIGH" if hi > or_h else "Breakout LOW"
                        print(f"  - Bar {row['datetime'].strftime('%H:%M')} UTC ({side}): TR candle sebelumnya = {tr_past:.2f} pts vs Syarat Minimum = {cutoff:.2f} pts (1.5 x SMA20={tr_sma:.2f}). Lolos? {passed}")

        en_bars = df[
            (df["datetime"].dt.date == today)
            & (
                ((df["datetime"].dt.hour == 8) & (df["datetime"].dt.minute >= 15))
                | ((df["datetime"].dt.hour > 8) & (df["datetime"].dt.hour < 11))
                | ((df["datetime"].dt.hour == 11) & (df["datetime"].dt.minute <= 30))
            )
        ]
        break_up = en_bars[en_bars["high"] > or_h]
        break_dn = en_bars[en_bars["low"] < or_l]
        print(f"• Jendela Entry (08:15-11:30)    : Total {len(en_bars)} bar")
        print(f"  - Bar breakout HIGH            : {len(break_up)} bar")
        print(f"  - Bar breakout LOW             : {len(break_dn)} bar")
        if not break_up.empty:
            first_up = break_up.iloc[0]
            print(f"  - Breakout High pertama terjadi: {first_up['datetime'].strftime('%H:%M')} UTC @ {first_up['high']:.2f}")
        if not break_dn.empty:
            first_dn = break_dn.iloc[0]
            print(f"  - Breakout Low pertama terjadi : {first_dn['datetime'].strftime('%H:%M')} UTC @ {first_dn['low']:.2f}")

    # 3. NY ORB
    print("\n--- [3] SESI NEW YORK ORB ---")
    ny_or_h, ny_or_m = sched["NY_OR_START"]
    ny_or_bars = df[
        (df["datetime"].dt.date == today)
        & (df["datetime"].dt.hour == ny_or_h)
        & (df["datetime"].dt.minute >= ny_or_m)
        & (df["datetime"].dt.minute < ny_or_m + 15)
    ]
    if len(ny_or_bars) >= 2:
        ny_h = ny_or_bars["high"].max()
        ny_l = ny_or_bars["low"].min()
        ny_r = ny_h - ny_l
        print(f"• Box Opening Range NY M5        : High = {ny_h:.2f} | Low = {ny_l:.2f} | Range = {ny_r:.2f} pts (${ny_r:.2f})")
    else:
        print(f"• Sesi NY baru dimulai / bar OR belum lengkap ({len(ny_or_bars)} bar)")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    audit()
