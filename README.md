# 📈 QuantTrade: Systematic Multi-Regime Quantitative Trading System (XAU/USD)

An institutional-grade systematic algorithmic trading portfolio for **XAU/USD (Gold)** combining two uncorrelated intraday strategies:
1. **Asian Mean Reversion (M5)** — Capturing mean-reverting deviations during low-volatility Asian consolidation (01:00 – 04:30 UTC).
2. **New York Opening Range Breakout (M5)** — Harvesting directional liquidity momentum during New York market opening expansions (13:45 – 16:30 UTC).

Operates on a **single combined capital account ($10,000 USD)** with **asymmetric risk budgeting** (Asia 2.0% : NY 1.0%), **dynamic compounding**, and **automated de-risking cooldown** protection.

---

## 🚀 Performance Overview (2-Year Backtest: Sep 2024 – Sep 2026)

| Performance Metric | QuantTrade Master Portfolio | Institutional Benchmark |
| :--- | :---: | :---: |
| **Initial Capital** | **$10,000.00 USD** | $10,000.00 USD |
| **Ending Capital** | **$467,118.80 USD** | - |
| **Net Profit (PnL)** | **+$457,118.80 USD** | - |
| **Return on Investment (ROI)** | **+4,571.19%** | > 100% |
| **Profit Factor (PF)** | **2.12** | > 1.50 (Grade A) |
| **Sharpe Ratio (Annualized)** | **3.76** | > 2.00 (Elite) |
| **Maximum Drawdown (%)** | **4.05%** | < 20.00% |
| **Maximum Drawdown (USD)** | $18,935.86 USD | - |
| **Total Trades** | 660 trades | - |
| **Win Rate** | **59.2%** (391W / 269L) | > 50.0% |
| **Monthly Win Rate** | **96.0%** (24 / 25 Profitable Months) | > 75.0% |

---

## 🏛️ Institutional Stress Testing Suite

All 4 institutional stress testing pillars have been rigorously executed:

| Test Methodology | Description & Parameters | Empirical Result | Institutional Verdict |
| :--- | :--- | :--- | :---: |
| **🎲 Monte Carlo Simulation** | 1,000 randomized permutations of trade sequence | **Median Capital $382,430 USD**, VaR95 DD 16.96%, **Risk of Ruin 0.00%** | **PASSED (Grade A)** |
| **✂️ Walk-Forward Blind Split** | Year 1 In-Sample Training vs Year 2 Out-of-Sample Blind Test | **WFE 80.3%**, OOS ROI **+522.7%**, PF **2.12**, Max DD **4.04%** | **PASSED (Anti-Overfitting)** |
| **🏔️ Parameter Sensitivity Surface** | 35-cell parameter matrix (Z 1.4–1.8 × NY Exp 1.5x–2.1x) | **100% Cells Profitable (35/35)**, Broad Profit Plateau ($141k – $784k) | **PASSED (Robust Plateau)** |
| **🧱 Friction & Slippage Decay** | Stress test across round-turn friction ($0.00 to $3.00 USD/oz) | **Break-Even Limit $2.28 USD/oz (7.6x ECN Spread Buffer)** | **PASSED (High Resilience)** |

---

## 📂 Repository Structure

```text
quanttrade/
├── data/                                 # Historical M5 tick/bar dataset
│   └── xauusd-m5-bid-2024-09-08-2026-09-08.csv
├── engine/                               # Quantitative strategy engines
│   ├── engine_asia/                      # Asian Mean Reversion module
│   ├── engine_ny/                        # New York ORB module
│   └── engine_portfolio/                 # Portfolio management & stress testing engines
│       ├── portfolio_engine.py
│       ├── monte_carlo.py
│       ├── walk_forward.py
│       ├── parameter_sensitivity.py
│       └── friction_decay.py
├── visualization/                        # Quantitative charts & dashboards
│   ├── visualization_asia/
│   ├── visualization_ny/
│   └── visualization_portfolio/
├── testing/                              # Institutional Stress Test Runners
│   ├── main_monte_carlo.py               # 1,000-run Monte Carlo runner
│   ├── main_walk_forward.py              # Walk-Forward OOS runner
│   ├── main_sensitivity.py              # Parameter Sensitivity Surface runner
│   └── main_friction_decay.py            # Friction & Slippage Decay runner
├── output/                               # Output dashboards, charts & CSV logs
├── config.py                             # Asian MR configuration
├── ny_config.py                          # New York ORB configuration
├── portfolio_config.py                   # Master Portfolio configuration
├── main_portfolio.py                     # Master Portfolio CLI entry point
├── main.py                               # Standalone Asian MR runner
├── main_ny.py                            # Standalone New York ORB runner
├── requirements.txt                      # Python dependencies
└── README.md
```

---

## 🛠️ Quick Start & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/aryadnt07/quanttrade.git
cd quanttrade
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the Master Portfolio
```bash
python main_portfolio.py
```

### 4. Run Institutional Stress Testing Suite
```bash
# Monte Carlo Simulation (1,000 Permutations)
python testing/main_monte_carlo.py

# Walk-Forward Out-of-Sample Blind Split (Year 1 vs Year 2)
python testing/main_walk_forward.py

# Parameter Sensitivity Surface & Robustness Plateau (35 Grid Cells)
python testing/main_sensitivity.py

# Friction & Slippage Decay Curve ($0.00 to $3.00 USD/oz)
python testing/main_friction_decay.py
```

---

## ⚡ Recommended Live Execution Environment
- **Broker Account**: Raw Spread / ECN Account (e.g. Exness Raw Spread, IC Markets Raw).
- **Average Friction Target**: $\le \$0.25\ \text{USD/oz}$ (Spread + Commission).
- **Execution Latency**: Ultra-low latency VPS ($< 5\text{ ms}$ ping to broker trade servers in London LD4 / New York NY4).
- **Swap Category**: Swap-Free Extended (Islamic / Eligible regional accounts).

---

## 📄 License
This project is proprietary and intended for quantitative algorithmic trading research and institutional strategy deployment.
