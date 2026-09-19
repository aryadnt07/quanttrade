"""
Telegram Notifier Shim (Backward Compatibility)
==============================================
Modul notifikasi Telegram telah dipusatkan di folder khusus `live/telegram/`.
File ini me-reexport seluruh kelas dan fungsi agar skrip yang memanggil
`from live.telegram_notifier import ...` tetap berjalan 100% kompatibel.
"""

import os
import sys

# Pastikan path root repositori terdaftar di sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live.telegram.notifier import TelegramNotifier, test_telegram_connection

__all__ = ["TelegramNotifier", "test_telegram_connection"]

if __name__ == "__main__":
    test_telegram_connection()
