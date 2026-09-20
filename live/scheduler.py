"""
Live Session Schedule & Dynamic DST Manager
===========================================
Pengelola jadwal sesi trading harian (Asia, London, New York) dengan dukungan
pelacakan Daylight Saving Time (DST) dinamis Wall Street via zoneinfo (America/New_York).
"""

from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional

from configs import live_config as lcfg


class SessionScheduleManager:
    """Pengelola jadwal sesi dinamis dengan dukungan Daylight Saving Time (DST)."""

    @staticmethod
    def get_today_schedule(today_utc_date: date) -> Dict[str, Any]:
        """
        Hitung batas waktu (jam, menit) untuk setiap sesi pada tanggal UTC tertentu.
        
        Sesi:
        - Asian: 01:00 - 04:30 UTC (Cutoff 06:00 UTC)
        - London: OR 08:00 - 08:15 UTC, Entry 08:15 - 11:30 UTC (Cutoff 11:25 UTC)
        - New York: OR 09:30 - 09:45 NY Local, Entry 09:45 - 12:30 NY Local (DST Dynamic)
        """
        schedule: Dict[str, Any] = {}

        # 1. Asian Session (Tokyo/Singapore — No DST, UTC Statis)
        schedule["ASIAN_START"] = lcfg.ASIAN_START_TIME
        schedule["ASIAN_END"] = lcfg.ASIAN_END_TIME
        schedule["ASIAN_CUTOFF"] = lcfg.ASIAN_CUTOFF_TIME

        # 2. London Session
        if getattr(lcfg, "USE_LONDON_LOCAL_TIME", False):
            lon_tz = ZoneInfo("Europe/London")
            dt_lon_or = datetime(today_utc_date.year, today_utc_date.month, today_utc_date.day, 8, 0, tzinfo=lon_tz).astimezone(timezone.utc)
            dt_lon_en = datetime(today_utc_date.year, today_utc_date.month, today_utc_date.day, 8, 15, tzinfo=lon_tz).astimezone(timezone.utc)
            dt_lon_co = datetime(today_utc_date.year, today_utc_date.month, today_utc_date.day, 11, 25, tzinfo=lon_tz).astimezone(timezone.utc)
            schedule["LONDON_OR_START"] = (dt_lon_or.hour, dt_lon_or.minute)
            schedule["LONDON_ENTRY_START"] = (dt_lon_en.hour, dt_lon_en.minute)
            schedule["LONDON_CUTOFF"] = (dt_lon_co.hour, dt_lon_co.minute)
        else:
            schedule["LONDON_OR_START"] = lcfg.LONDON_OR_START
            schedule["LONDON_ENTRY_START"] = lcfg.LONDON_ENTRY_START
            schedule["LONDON_CUTOFF"] = lcfg.LONDON_CUTOFF_TIME

        schedule["LONDON_ENTRY_END"] = lcfg.LONDON_ENTRY_END

        # 3. New York Session (Wall Street Open 09:30 AM America/New_York — DST Dynamic)
        if getattr(lcfg, "USE_DYNAMIC_DST", True):
            ny_tz = ZoneInfo("America/New_York")
            dt_ny_or = datetime(today_utc_date.year, today_utc_date.month, today_utc_date.day, 9, 30, tzinfo=ny_tz).astimezone(timezone.utc)
            dt_ny_en = datetime(today_utc_date.year, today_utc_date.month, today_utc_date.day, 9, 45, tzinfo=ny_tz).astimezone(timezone.utc)
            dt_ny_end = datetime(today_utc_date.year, today_utc_date.month, today_utc_date.day, 12, 30, tzinfo=ny_tz).astimezone(timezone.utc)
            dt_ny_co = datetime(today_utc_date.year, today_utc_date.month, today_utc_date.day, 12, 25, tzinfo=ny_tz).astimezone(timezone.utc)

            schedule["NY_OR_START"] = (dt_ny_or.hour, dt_ny_or.minute)
            schedule["NY_ENTRY_START"] = (dt_ny_en.hour, dt_ny_en.minute)
            schedule["NY_ENTRY_END"] = (dt_ny_end.hour, dt_ny_end.minute)
            schedule["NY_CUTOFF"] = (dt_ny_co.hour, dt_ny_co.minute)
            schedule["NY_TZ_NAME"] = dt_ny_or.tzname()
        else:
            schedule["NY_OR_START"] = lcfg.NY_OR_START
            schedule["NY_ENTRY_START"] = lcfg.NY_ENTRY_START
            schedule["NY_ENTRY_END"] = lcfg.NY_ENTRY_END
            schedule["NY_CUTOFF"] = lcfg.NY_CUTOFF_TIME
            schedule["NY_TZ_NAME"] = "STATIC_UTC"

        return schedule
