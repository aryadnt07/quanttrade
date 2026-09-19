"""
Master Portfolio Configuration Shim (Backward Compatibility)
============================================================
Semua konfigurasi Master Portfolio telah dipusatkan di `configs/portfolio_config.py`.
File ini me-reexport seluruh variabel konfigurasi agar kode lama tetap kompatibel.
"""

from configs.portfolio_config import *
