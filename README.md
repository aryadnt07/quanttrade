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

## 📂 Institutional Directory Architecture (Option B Production-Grade)

```text
quanttrade/
├── src/
│   ├── core/                          # Domain primitives (Direction, Signal, Pure math indicators, Stats)
│   ├── strategies/                    # Canonical quantitative strategy implementations
│   │   ├── asian_mr/                  # Asian Mean Reversion (config, signals, backtester)
│   │   ├── london_orb/                # London Pit ORB (config, signals, backtester, trade_manager)
│   │   ├── ny_orb/                    # New York ORB (config, signals, backtester, trade_manager)
│   │   └── portfolio/                 # Master Portfolio Engine & cross-strategy allocator
│   ├── execution/                     # Production MetaTrader 5 Live Trading Bridge
│   │   ├── runner.py                  # LivePortfolioTrader 24/7 Engine
│   │   ├── mt5_connector.py           # Broker API adapter, IPC guards, Order sender
│   │   ├── risk_manager.py            # Daily Loss Circuit Breaker, Single-instance lock
│   │   ├── position_manager.py        # Position exits, Z-Neutral TP, Time-stop cutoffs
│   │   ├── scheduler.py               # Multi-session scheduling & DST offset detection
│   │   ├── system_check.py            # 10-stage live system pre-flight audit suite
│   │   ├── executors/                 # Session execution modules (asia, london, ny)
│   │   └── notifications/             # Telegram real-time push alerting engine
│   ├── data/                          # Data pipelines (CSV loader & multi-timeframe engine)
│   └── observability/                 # Thread-safe dual logger & trade journal recorder
├── research/                          # Quantitative research & validation suite
│   ├── analytics/                     # Monte Carlo, Walk-Forward, Friction Decay, Sensitivity
│   └── visualization/                 # Publication-grade dark HUD performance dashboards
├── tests/                             # Enterprise automated testing suites
│   ├── unit/                          # Unit tests for indicators & signal models
│   ├── integration/                   # Integration tests for backtest engines & portfolio
│   └── live/                          # Live execution audit guards & risk control tests
├── deploy/                            # Windows VPS 1-Click Automation Scripts
│   ├── CHECK_CONNECTION.bat          # 1-Click MT5 connection health check
│   ├── TEST_LIVE_SYSTEM.bat          # 1-Click 10-stage pre-flight readiness audit
│   ├── START_LIVE_BOT.bat            # 1-Click 24/7 live trading runner
│   └── UPDATE_LIVE_BOT.bat           # 1-Click hot-reloader (graceful stop, git pull, auto-restart)
├── docs/                              # Architecture, stress test reports & deployment guides
│   ├── ARCHITECTURE.md
│   ├── STRESS_TEST_REPORT.md
│   └── VPS_DEPLOYMENT_GUIDE.md
├── data/                              # Historical tick & bar datasets (gitignored)
├── output/                            # Performance charts, CSV logs, & visual dashboards (gitignored)
├── logs/                              # Runtime logs & circuit breaker states (gitignored)
├── main.py                            # Unified Master CLI Entry Point
├── requirements.txt                   # Project dependencies
└── README.md
```

---

## 🛠️ Unified CLI Usage

QuantTrade provides a clean, unified command-line interface via `main.py`:

### 1. Master Portfolio Execution
```bash
# Run full Master Portfolio (Asia MR + London ORB + NY ORB)
python main.py portfolio

# Run without rendering chart (fast mode)
python main.py portfolio --no-chart
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
# 1-Stage Connection Health Check
python main.py live --check-only

# Comprehensive 8-Stage System Readiness Diagnostic & Dry-Run
python main.py live-check

# Start live multi-session execution bot (24/7 Engine)
python main.py live
```

> **VPS Automation Shortcuts** (inside `deploy/` directory):
> - `deploy/TEST_LIVE_SYSTEM.bat`: 1-Click 8-stage pre-flight readiness diagnostic (Zero-risk broker dry-run).
> - `deploy/CHECK_CONNECTION.bat`: 1-Click quick MT5 ping & account check.
> - `deploy/START_LIVE_BOT.bat`: 1-Click launcher for 24/7 automated live trading.
> - `deploy/UPDATE_LIVE_BOT.bat`: 1-Click hot-reloader (graceful stop, `git pull`, and auto-restart).

---

## ⚡ Recommended Live Execution Environment
- **Broker Account**: Raw Spread / ECN Account (e.g. Exness Raw Spread, IC Markets Raw).
- **Average Friction Target**: $\le \$0.25\ \text{USD/oz}$ (Spread + Commission).
- **Execution Latency**: Ultra-low latency VPS ($< 5\text{ ms}$ ping to broker trade servers in London LD4 / New York NY4).
- **Swap Category**: Swap-Free Extended (Islamic / Eligible regional accounts).

---

## 📄 License
This project is proprietary and intended for quantitative algorithmic trading research and institutional strategy deployment.
