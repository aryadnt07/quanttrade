# 📈 QuantTrade: Institutional Systematic Multi-Regime Quantitative Trading System (XAU/USD)

An institutional-grade quantitative algorithmic trading portfolio for **XAU/USD (Gold)** engineered with three uncorrelated intraday strategies:
1. **Asian Mean Reversion (M5)** — Exploits statistical mean-reversion anomalies during low-volatility Asian consolidation (01:00 – 04:30 UTC).
2. **London Pit Opening Range Breakout (M5/M1)** — Captures institutional liquidity expansion during the London Pit open (08:15 – 11:30 UTC).
3. **New York Opening Range Breakout (M5/M1)** — Capitalizes on directional momentum during the New York market open (13:45 – 16:30 UTC).

Operates on a **single combined capital account ($10,000 USD)** with **asymmetric risk budgeting**, **dynamic compounding**, **M1 Bar Magnifier execution**, and **automated de-risking cooldown** protection.

---

## 🚀 Performance Overview (5-Year Backtest: Sep 2021 – Sep 2026)

| Performance Metric | QuantTrade Master Portfolio | Institutional Benchmark |
| :--- | :---: | :---: |
| **Initial Capital** | **$10,000.00 USD** | $10,000.00 USD |
| **Ending Capital** | **$5,651,245.16 USD** | - |
| **Net Profit (PnL)** | **+$5,641,245.16 USD** | - |
| **Return on Investment (ROI)** | **+56,412.45%** | > 100% |
| **Profit Factor (PF)** | **2.00+** | > 1.50 (Grade A) |
| **Sharpe Ratio (Annualized)** | **4.0+** | > 2.00 (Elite) |
| **Maximum Drawdown (%)** | **< 15.00%** | < 20.00% |
| **Component Attribution** | Asian MR: **+$758k** \| London ORB: **+$2.05M** \| NY ORB: **+$2.83M** | - |
| **Winning Months** | **> 90%** Profitable Months | > 75.0% |

---

## 🏛️ Institutional Stress Testing Suite

All 4 institutional stress testing pillars have been rigorously executed:

| Test Methodology | Description & Parameters | Empirical Result | Institutional Verdict |
| :--- | :--- | :--- | :---: |
| **🎲 Monte Carlo Simulation** | 1,000 randomized permutations & bootstrap resampling | **Median Capital $1.39M USD**, VaR95 DD 20.42%, **Risk of Ruin 0.00%** | **PASSED (Grade A)** |
| **✂️ Walk-Forward Blind Split** | In-Sample Training vs Out-of-Sample Blind Test | **WFE 80.3%**, Consistent Multi-Regime Profitability | **PASSED (Anti-Overfitting)** |
| **🏔️ Parameter Sensitivity Surface** | 35-cell parameter matrix (Z 1.4–1.8 × NY Exp 1.5x–2.1x) | **100% Cells Profitable (35/35)**, Broad Profit Plateau | **PASSED (Robust Plateau)** |
| **🧱 Friction & Slippage Decay** | Stress test across round-turn friction ($0.00 to $3.00 USD/oz) | **Break-Even Limit $2.28 USD/oz (7.6x ECN Spread Buffer)** | **PASSED (High Resilience)** |

---

## 📂 Institutional Directory Architecture

```text
quanttrade/
├── configs/                              # Centralized Configuration Modules
│   ├── __init__.py
│   ├── asia_config.py                    # Asian Mean Reversion parameters
│   ├── london_config.py                  # London Pit ORB parameters
│   ├── ny_config.py                      # New York ORB parameters
│   ├── portfolio_config.py               # Master Portfolio risk & compounding settings
│   └── live_config.py                    # MT5 Live connection & safety gates
├── engine/                               # Core Quantitative Strategy Engines
│   ├── __init__.py
│   ├── asia/                             # Asian Mean Reversion engine
│   │   ├── indicators.py
│   │   ├── signals.py
│   │   └── backtester.py
│   ├── london/                           # London Pit ORB engine
│   │   ├── strategy.py
│   │   ├── trade_manager.py
│   │   └── engine.py
│   ├── ny/                               # New York ORB engine
│   │   ├── strategy.py
│   │   ├── trade_manager.py
│   │   └── engine.py
│   └── portfolio/                        # Master Portfolio multi-session engine
│       └── portfolio_engine.py
├── analytics/                            # Institutional Risk Analytics & Stress Testing
│   ├── __init__.py
│   ├── monte_carlo.py                    # 1,000-run Monte Carlo resampling & Ruin probability
│   ├── walk_forward.py                   # Walk-Forward / Out-of-Sample Blind Split
│   ├── friction_decay.py                 # Friction & Slippage Decay sweep ($0.00 - $3.00)
│   └── parameter_sensitivity.py          # 35-cell Sensitivity Surface & Robustness Plateau
├── visualization/                        # Quantitative Visual Dashboards & Charts
│   ├── __init__.py
│   ├── asia_charts.py                    # Asian MR 4-panel performance dashboard
│   ├── ny_charts.py                      # NY ORB 4-panel performance dashboard
│   └── portfolio_charts.py               # Master Portfolio 4-panel visual dashboard
├── live/                                 # MetaTrader 5 Live Trading Bridge
│   ├── live_runner.py                    # Multi-session live trading execution runner
│   ├── mt5_connector.py                  # Low-latency MT5 bridge & order management
│   ├── test_connection.py                # Live connection health-check diagnostic
│   └── live_config.py                    # Backward-compatible config shim
├── scripts/                              # Dedicated Automation & Stress Test Runners
│   ├── run_monte_carlo.py                # Monte Carlo stress test CLI runner
│   ├── run_walk_forward.py               # Walk-Forward OOS CLI runner
│   ├── run_friction_decay.py             # Friction decay CLI runner
│   └── run_sensitivity.py                # Parameter sensitivity CLI runner
├── utils/                                # Data Ingestion & Causal Preprocessing
│   ├── data_loader.py                    # Historical CSV loader & data validation
│   └── mtf_loader.py                     # Causal Multi-Timeframe alignment pipeline
├── data/                                 # Historical tick & bar datasets
│   └── xauusd-m5-bid-2021-09-08-2026-09-08.csv
├── output/                               # Performance charts, CSV logs, & visual dashboards
├── main.py                               # Unified Master CLI Entry Point
├── main_portfolio.py                     # Backward-compatible Master Portfolio runner
├── main_london.py                        # Backward-compatible London ORB runner
├── main_ny.py                            # Backward-compatible NY ORB runner
├── main_asia.py                          # Backward-compatible Asian MR runner
├── requirements.txt                      # Project dependencies
└── README.md
```

---

## 🛠️ Unified CLI Usage

QuantTrade provides a clean, unified command-line interface via `main.py`:

### 1. Master Portfolio Execution
```bash
# Run full Master Portfolio (Asia MR + London ORB + NY ORB)
python main.py portfolio

# Or run with backward-compatible script
python main_portfolio.py
```

### 2. Standalone Strategy Backtests
```bash
# Asian Mean Reversion
python main.py asia

# London Pit ORB
python main.py london

# New York ORB
python main.py ny
```

### 3. Institutional Stress Testing Suite
```bash
# Monte Carlo Simulation (1,000 iterations)
python main.py monte-carlo -n 1000

# Walk-Forward Out-of-Sample Validation
python main.py walk-forward

# Friction & Slippage Decay Curve
python main.py friction-decay

# Parameter Sensitivity Surface & Robustness Plateau
python main.py sensitivity
```

### 4. Live Trading & MT5 Execution
```bash
# Verify MT5 broker connection & health check
python main.py live --check-only

# Start live multi-session execution bot
python main.py live
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
