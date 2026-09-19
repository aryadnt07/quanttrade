"""
Live Trading Configuration Shim (Backward Compatibility)
=========================================================
Semua konfigurasi live trading telah dipusatkan di `configs/live_config.py`.
File ini me-reexport seluruh variabel konfigurasi agar skrip yang memanggil
`from live import live_config` tetap berjalan 100% kompatibel tanpa modifikasi.
"""

import sys
import configs.live_config

# Alias module object in sys.modules to ensure singleton identity
sys.modules[__name__] = configs.live_config
