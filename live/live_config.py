"""
Live Trading Configuration Shim (Backward Compatibility)
=========================================================
Semua konfigurasi live trading telah dipusatkan di `configs/live_config.py`.
File ini me-reexport seluruh variabel konfigurasi agar skrip yang memanggil
`from live import live_config` tetap berjalan 100% kompatibel tanpa modifikasi.
"""

from configs.live_config import *
