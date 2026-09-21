# XAU/USD M5 Quantitative Trading System — Software Architecture Review

> **Date:** 2026-09-21  
> **Scope:** Full repository analysis, architectural proposal, migration plan  
> **Status:** PROPOSAL ONLY — No files modified

---

## PHASE 1 — Full Repository Inventory

### Complete File Tree (Current)

```
flg/
├── .env                              # SECRETS — Not in Git ✓
├── .env.example                      # Template for secrets ✓
├── .gitignore                        # Well-configured ✓
├── README.md                         # Project documentation
├── requirements.txt                  # Dependencies
├── main.py                           # Unified CLI dispatcher (10KB)
├── main_asia.py                      # Standalone Asia backtest runner
├── main_london.py                    # Standalone London backtest runner
├── main_ny.py                        # Standalone NY backtest runner
├── main_portfolio.py                 # Portfolio backtest runner
│
├── configs/
│   ├── __init__.py
│   ├── asia_config.py                # Asia MR strategy parameters
│   ├── london_config.py              # London ORB strategy parameters
│   ├── ny_config.py                  # NY ORB strategy parameters
│   ├── portfolio_config.py           # Portfolio composition & risk
│   └── live_config.py                # Live execution parameters + .env loading
│
├── engine/
│   ├── __init__.py                   # Re-exports all backtester classes
│   ├── asia/
│   │   ├── __init__.py
│   │   ├── indicators.py             # SMA, VWAP, Z-Score, RSI, ATR, ADX, HTF EMA
│   │   ├── signals.py                # Entry/exit signal logic + data classes
│   │   └── backtester.py             # Bar-by-bar simulation engine
│   ├── london/
│   │   ├── __init__.py
│   │   ├── strategy.py               # Opening range + signal generation
│   │   ├── engine.py                 # Backtester (M5 + M1 Bar Magnifier)
│   │   └── trade_manager.py          # Position lifecycle management
│   ├── ny/
│   │   ├── __init__.py
│   │   ├── strategy.py               # Opening range + signal generation
│   │   ├── engine.py                 # Backtester (M5 + M1 Bar Magnifier)
│   │   └── trade_manager.py          # Position lifecycle management
│   └── portfolio/
│       ├── __init__.py
│       └── portfolio_engine.py       # Multi-strategy orchestrator
│
├── live/
│   ├── live_runner.py                # Master orchestrator (18KB) — uses mixins
│   ├── mt5_connector.py              # MetaTrader 5 IPC bridge (22KB)
│   ├── risk_manager.py               # PID lock, circuit breaker, reconciliation
│   ├── position_manager.py           # Active position lifecycle + exits
│   ├── scheduler.py                  # Session schedule + DST handling
│   ├── logger.py                     # Dual logging + QuickEdit + Trade Journal
│   ├── live_config.py                # SHIM → re-exports configs/live_config.py
│   ├── telegram_notifier.py          # SHIM → re-exports live/telegram/
│   ├── test_connection.py            # MT5 connection health check
│   ├── executors/
│   │   ├── __init__.py
│   │   ├── asia_executor.py          # Asia MR live signal evaluation + order
│   │   ├── london_executor.py        # London ORB live breakout execution
│   │   └── ny_executor.py            # NY ORB live breakout execution
│   └── telegram/
│       ├── __init__.py
│       └── notifier.py               # Telegram HTTP API notification engine
│
├── analytics/
│   ├── __init__.py
│   ├── monte_carlo.py                # Monte Carlo resampling simulation
│   ├── walk_forward.py               # Walk-forward OOS validation
│   ├── friction_decay.py             # Slippage/friction stress test
│   └── parameter_sensitivity.py      # Parameter sensitivity surface
│
├── scripts/
│   ├── run_monte_carlo.py            # CLI runner for Monte Carlo
│   ├── run_walk_forward.py           # CLI runner for Walk-Forward
│   ├── run_friction_decay.py         # CLI runner for Friction Decay
│   └── run_sensitivity.py            # CLI runner for Parameter Sensitivity
│
├── utils/
│   ├── __init__.py
│   ├── data_loader.py                # CSV loader + preprocessing
│   └── mtf_loader.py                 # Multi-timeframe data pipeline
│
├── visualization/
│   ├── __init__.py
│   ├── asia_charts.py                # Asia MR dashboard charts
│   ├── ny_charts.py                  # NY ORB dashboard charts
│   └── portfolio_charts.py           # Portfolio dashboard charts
│
├── tests/
│   └── test_live_audit_guards.py     # Live trading safety tests (24KB)
│
├── deploy/
│   ├── START_LIVE_BOT.bat            # VPS startup script
│   ├── CHECK_CONNECTION.bat          # Connection check script
│   ├── TEST_LIVE_SYSTEM.bat          # System check script
│   └── UPDATE_LIVE_BOT.bat           # Git pull + restart script
│
├── docs/
│   ├── INSTITUTIONAL_STRESS_TEST_REPORT_5YR.md
│   └── VPS_DEPLOYMENT_GUIDE.md
│
├── data/                             # GENERATED — Not in Git ✓
│   ├── .gitkeep
│   ├── xauusd-m1-bid-*.csv           # ~109MB
│   └── xauusd-m5-bid-*.csv           # ~22MB
│
├── output/                           # GENERATED — Not in Git ✓
│   ├── .gitkeep
│   ├── *.csv                         # Trade logs
│   ├── *.png                         # Dashboard images
│   └── portfolio_log.txt             # Text reports
│
└── logs/                             # GENERATED — Not in Git ✓
    ├── .gitkeep
    ├── live_trading.log
    ├── live_trading.log.*.log
    ├── live_trade_journal.csv
    └── daily_circuit_breaker_state.json
```

### File Classification Matrix

| File/Dir | Production | Research | Generated | Config | Version Control |
|---|---|---|---|---|---|
| `engine/` | ✅ (shared) | ✅ (shared) | ❌ | ❌ | ✅ |
| `live/` | ✅ | ❌ | ❌ | ❌ | ✅ |
| `analytics/` | ❌ | ✅ | ❌ | ❌ | ✅ |
| `scripts/` | ❌ | ✅ | ❌ | ❌ | ✅ |
| `configs/` | ✅ | ✅ | ❌ | ✅ | ✅ |
| `utils/` | ✅ | ✅ | ❌ | ❌ | ✅ |
| `visualization/` | ❌ | ✅ | ❌ | ❌ | ✅ |
| `tests/` | ✅ | ❌ | ❌ | ❌ | ✅ |
| `deploy/` | ✅ | ❌ | ❌ | ✅ | ✅ |
| `data/` | ❌ | ❌ | ✅ | ❌ | ❌ |
| `output/` | ❌ | ❌ | ✅ | ❌ | ❌ |
| `logs/` | ❌ | ❌ | ✅ | ❌ | ❌ |
| `main*.py` | ✅ | ✅ | ❌ | ❌ | ✅ |
| `.env` | ✅ | ❌ | ❌ | ✅ | ❌ |

---

## PHASE 2 — Architectural Boundaries

### Actual Layer Map (Current State)

```
DATA LAYER          → utils/data_loader.py, utils/mtf_loader.py
                    ↓
INDICATOR LAYER     → engine/asia/indicators.py
                    → (London/NY compute indicators inline in strategy.py)
                    ↓
SIGNAL LAYER        → engine/asia/signals.py
                    → engine/london/strategy.py
                    → engine/ny/strategy.py
                    ↓
STRATEGY LAYER      → (merged with Signal layer above)
                    ↓
BACKTEST LAYER      → engine/asia/backtester.py
                    → engine/london/engine.py
                    → engine/ny/engine.py
                    ↓
PORTFOLIO LAYER     → engine/portfolio/portfolio_engine.py
                    ↓
EXECUTION LAYER     → live/live_runner.py + mixins
                    → live/executors/*_executor.py
                    ↓
BROKER ADAPTER      → live/mt5_connector.py
                    ↓
RISK MANAGEMENT     → live/risk_manager.py
                    → live/position_manager.py
                    ↓
MONITORING          → live/telegram/notifier.py
                    → live/logger.py
                    ↓
SCHEDULING          → live/scheduler.py
```

### Architectural Violations Detected

| # | Violation | Severity | Location |
|---|---|---|---|
| V1 | `position_manager.py` imports `engine.asia.indicators.compute_all` | 🔴 **HIGH** | [position_manager.py:21](file:///d:/Codingan/flg/live/position_manager.py#L21) |
| V2 | `position_manager.py` imports `MetaTrader5` directly | 🟡 MEDIUM | [position_manager.py:18](file:///d:/Codingan/flg/live/position_manager.py#L18) |
| V3 | London/NY signal generation logic is **duplicated** between `engine/*/engine.py` (backtester) and `live/executors/*_executor.py` | 🔴 **HIGH** | Multiple files |
| V4 | `data_loader.py` (shared utility) imports `configs.asia_config` — couples a general utility to a specific strategy | 🟡 MEDIUM | [data_loader.py:16](file:///d:/Codingan/flg/utils/data_loader.py#L16) |
| V5 | `configs/live_config.py` duplicates Asia exit parameters (`ASIA_Z_EXIT_THRESHOLD`, `ASIA_Z_HARD_CUT`, `ASIA_MAX_DURATION_MIN`) instead of referencing `asia_config.py` | 🟡 MEDIUM | [live_config.py:178-181](file:///d:/Codingan/flg/configs/live_config.py#L178-L181) |
| V6 | London/NY trade_manager.py files have near-identical structure (code duplication) | 🟡 MEDIUM | `engine/london/trade_manager.py` & `engine/ny/trade_manager.py` |
| V7 | `LondonStats` and `NYStats` dataclasses are near-identical copies | 🟡 MEDIUM | `engine/london/engine.py` & `engine/ny/engine.py` |
| V8 | Five `main_*.py` files at project root instead of clean subcommand modules | 🟢 LOW | Root directory |
| V9 | `live/live_config.py` and `live/telegram_notifier.py` are shim files that exist only for backward compatibility | 🟢 LOW | `live/` directory |

---

## PHASE 3 — Research vs Production Separation

### Current State

The current project **does not have explicit separation** between research and production code. The `engine/` package is shared between both contexts, which is actually correct — this is the **canonical strategy logic** that both backtesting and live execution should use.

However, the **live execution code** (`live/`) and the **research/validation code** (`analytics/`, `scripts/`, `visualization/`) are already naturally separated. This is a **good architectural instinct**.

### Assessment

| Context | Files | Isolation Quality |
|---|---|---|
| **Strategy Core** | `engine/*` | ✅ Good — shared by both backtest and live |
| **Live Execution** | `live/*` | ✅ Good — separate package |
| **Research/Validation** | `analytics/*`, `scripts/*` | ✅ Good — separate packages |
| **Visualization** | `visualization/*` | ✅ Good — pure presentation |
| **Entry Points** | `main*.py` | 🟡 Scattered at root |
| **Configuration** | `configs/*` | 🟡 Mixed backtest + live params in same files |

---

## PHASE 4 — Three Architectural Options

### OPTION A: Minimal Refactor

```
flg/
├── configs/
│   ├── asia.py                    # renamed from asia_config.py
│   ├── london.py
│   ├── ny.py
│   ├── portfolio.py
│   └── live.py
├── engine/
│   ├── asia/                      # UNCHANGED
│   ├── london/                    # UNCHANGED
│   ├── ny/                        # UNCHANGED
│   └── portfolio/                 # UNCHANGED
├── live/
│   ├── executors/                 # UNCHANGED
│   ├── telegram/                  # UNCHANGED
│   ├── live_runner.py             # UNCHANGED
│   ├── mt5_connector.py
│   ├── risk_manager.py
│   ├── position_manager.py
│   ├── scheduler.py
│   └── logger.py
├── analytics/                     # UNCHANGED
├── cli/                           # NEW: move main_*.py here
│   ├── __init__.py
│   ├── backtest_asia.py
│   ├── backtest_london.py
│   ├── backtest_ny.py
│   └── backtest_portfolio.py
├── utils/                         # UNCHANGED
├── visualization/                 # UNCHANGED
├── tests/                         # UNCHANGED
├── deploy/                        # UNCHANGED
├── docs/                          # UNCHANGED
├── data/                          # UNCHANGED
├── output/                        # UNCHANGED
├── logs/                          # UNCHANGED
├── main.py                        # Simplified CLI dispatcher
├── .env
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

| Attribute | Assessment |
|---|---|
| **Advantages** | Minimal disruption; fixes root clutter; preserves all imports |
| **Disadvantages** | Doesn't solve duplication; doesn't fix V1 violation |
| **Migration Complexity** | 🟢 Low (rename + move 4 files) |
| **Maintenance Complexity** | 🟡 Same as current |
| **Scalability** | 🟡 Limited — still coupled |
| **Use Case** | Solo developer, quick cleanup |

---

### OPTION B: Production-Grade Quantitative Architecture

```
quanttrade/
├── src/
│   ├── core/                          # Domain primitives (NO external deps)
│   │   ├── __init__.py
│   │   ├── types.py                   # Direction, ExitReason, Signal, TradeResult
│   │   ├── indicators.py              # Pure math: SMA, RSI, ATR, Z-Score, ADX
│   │   └── stats.py                   # BacktestStats, PortfolioStats base
│   │
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── asian_mr/
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   ├── signals.py             # Entry/exit logic (uses core/indicators)
│   │   │   └── backtester.py
│   │   ├── london_orb/
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   ├── signals.py
│   │   │   ├── backtester.py
│   │   │   └── trade_manager.py
│   │   ├── ny_orb/
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   ├── signals.py
│   │   │   ├── backtester.py
│   │   │   └── trade_manager.py
│   │   └── portfolio/
│   │       ├── __init__.py
│   │       ├── config.py
│   │       └── engine.py
│   │
│   ├── execution/                     # Live trading ONLY
│   │   ├── __init__.py
│   │   ├── config.py                  # Live-specific config (loads .env)
│   │   ├── runner.py                  # LivePortfolioTrader
│   │   ├── mt5_connector.py           # Broker adapter
│   │   ├── risk_manager.py            # PID lock, circuit breaker
│   │   ├── position_manager.py        # Active position exits
│   │   ├── scheduler.py               # Session schedule + DST
│   │   ├── executors/
│   │   │   ├── __init__.py
│   │   │   ├── asia.py
│   │   │   ├── london.py
│   │   │   └── ny.py
│   │   └── notifications/
│   │       ├── __init__.py
│   │       └── telegram.py
│   │
│   ├── data/                          # Data loading & processing
│   │   ├── __init__.py
│   │   ├── loader.py                  # CSV loader (decoupled from strategy config)
│   │   └── mtf_loader.py
│   │
│   └── observability/                 # Logging & monitoring
│       ├── __init__.py
│       └── logger.py
│
├── research/                          # Research & validation (NOT imported by production)
│   ├── analytics/
│   │   ├── monte_carlo.py
│   │   ├── walk_forward.py
│   │   ├── friction_decay.py
│   │   └── parameter_sensitivity.py
│   └── visualization/
│       ├── asia_charts.py
│       ├── ny_charts.py
│       └── portfolio_charts.py
│
├── tests/
│   ├── unit/
│   │   ├── test_indicators.py
│   │   ├── test_asian_signals.py
│   │   ├── test_london_signals.py
│   │   └── test_ny_signals.py
│   ├── integration/
│   │   ├── test_backtest_asia.py
│   │   └── test_backtest_portfolio.py
│   └── live/
│       └── test_audit_guards.py
│
├── deploy/
│   ├── START_LIVE_BOT.bat
│   ├── CHECK_CONNECTION.bat
│   ├── TEST_LIVE_SYSTEM.bat
│   └── UPDATE_LIVE_BOT.bat
│
├── docs/
│   ├── STRESS_TEST_REPORT.md
│   └── VPS_DEPLOYMENT_GUIDE.md
│
├── data/                              # Market data (gitignored)
├── output/                            # Backtest results (gitignored)
├── logs/                              # Runtime logs (gitignored)
│
├── main.py                            # Unified CLI entry point
├── .env
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

| Attribute | Assessment |
|---|---|
| **Advantages** | Clear separation of concerns; eliminates duplication; enforces dependency direction; research can't accidentally import live code |
| **Disadvantages** | Moderate migration effort; all imports must be updated |
| **Migration Complexity** | 🟡 Medium (restructure + update all imports) |
| **Maintenance Complexity** | 🟢 Low — clear boundaries |
| **Scalability** | ✅ Good — add strategies by adding `src/strategies/<name>/` |
| **Use Case** | Solo developer going to production; small team |

---

### OPTION C: Institutional / Long-Term Scalable Architecture

```
quanttrade/
├── src/quanttrade/                    # Installable Python package
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── types.py                   # Enums, dataclasses, protocols
│   │   ├── indicators/
│   │   │   ├── __init__.py
│   │   │   ├── moving_averages.py
│   │   │   ├── oscillators.py         # RSI, ADX
│   │   │   ├── volatility.py          # ATR, True Range
│   │   │   ├── statistical.py         # Z-Score, Std Dev
│   │   │   └── htf.py                 # Higher-timeframe EMA
│   │   ├── stats.py
│   │   └── interfaces.py             # Abstract Strategy, Backtester protocols
│   │
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── registry.py               # Strategy discovery & registration
│   │   ├── asian_mr/
│   │   ├── london_orb/
│   │   ├── ny_orb/
│   │   └── portfolio/
│   │
│   ├── backtest/
│   │   ├── __init__.py
│   │   ├── engine.py                 # Generic backtest runner
│   │   └── bar_magnifier.py          # M1 sub-bar execution
│   │
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── position_sizing.py
│   │   ├── circuit_breaker.py
│   │   └── portfolio_risk.py
│   │
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── runner.py
│   │   ├── scheduler.py
│   │   └── reconciliation.py
│   │
│   ├── brokers/
│   │   ├── __init__.py
│   │   ├── base.py                   # Abstract broker interface
│   │   └── mt5/
│   │       ├── __init__.py
│   │       ├── connector.py
│   │       └── order_manager.py
│   │
│   ├── notifications/
│   │   ├── __init__.py
│   │   ├── base.py                   # Abstract notifier
│   │   └── telegram.py
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   ├── loader.py
│   │   └── mtf.py
│   │
│   └── observability/
│       ├── __init__.py
│       └── logger.py
│
├── apps/                             # Application entry points
│   ├── backtest/
│   │   └── __main__.py
│   ├── live/
│   │   └── __main__.py
│   └── research/
│       └── __main__.py
│
├── research/                         # Independent research workspace
│   ├── analytics/
│   ├── visualization/
│   └── notebooks/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── live/
│   └── conftest.py
│
├── configs/                          # All configuration files
│   ├── strategies/
│   │   ├── asian_mr.yaml
│   │   ├── london_orb.yaml
│   │   └── ny_orb.yaml
│   ├── environments/
│   │   ├── development.yaml
│   │   ├── paper.yaml
│   │   └── production.yaml
│   └── portfolio.yaml
│
├── deploy/
├── docs/
├── data/
├── output/
├── logs/
│
├── pyproject.toml                    # Package definition
├── main.py
├── .env
├── .env.example
├── .gitignore
└── README.md
```

| Attribute | Assessment |
|---|---|
| **Advantages** | Scales to 10+ strategies, multiple brokers, multiple instruments; abstract interfaces enable testing; installable package; YAML configs |
| **Disadvantages** | Over-engineered for 3 strategies on 1 instrument; high migration cost; requires pyproject.toml setup; YAML migration adds complexity |
| **Migration Complexity** | 🔴 High (full restructure + package setup + YAML migration) |
| **Maintenance Complexity** | 🟡 Higher upfront, lower long-term |
| **Scalability** | ✅ Excellent |
| **Use Case** | Multi-developer team; multi-instrument platform; institutional fund |

---

## PHASE 5 — Recommended Architecture

> **Recommendation: OPTION B** — Production-Grade Quantitative Architecture

### Rationale

1. This is a **single-developer, single-instrument, 3-strategy system** — Option C is over-engineered
2. Option A doesn't fix the critical violations (V1, V3, V5)
3. Option B provides the right balance: **clean boundaries without unnecessary abstraction**
4. Python module configs (`.py`) are appropriate for this scale — YAML would add unnecessary parsing complexity

### Where Should Each Thing Live?

| Component | Recommended Location |
|---|---|
| Strategy logic (signals, rules) | `src/strategies/<name>/signals.py` |
| Indicators (pure math) | `src/core/indicators.py` |
| Backtest engine | `src/strategies/<name>/backtester.py` |
| Execution engine | `src/execution/runner.py` |
| MT5 connector | `src/execution/mt5_connector.py` |
| Risk manager | `src/execution/risk_manager.py` |
| Portfolio manager | `src/strategies/portfolio/engine.py` |
| Configuration | `src/strategies/<name>/config.py` + `src/execution/config.py` |
| Telegram notifier | `src/execution/notifications/telegram.py` |
| Logger | `src/observability/logger.py` |
| Data loader | `src/data/loader.py` |
| Research analytics | `research/analytics/` |
| Visualization | `research/visualization/` |
| Research scripts | CLI subcommands in `main.py` |
| Backtest output | `output/` |
| Audit reports | `docs/` |
| Trade logs | `logs/` |
| Runtime logs | `logs/` |
| Deployment scripts | `deploy/` |
| Unit tests | `tests/unit/` |
| Integration tests | `tests/integration/` |

---

## PHASE 6 — Dependency Direction

### Allowed Dependency Graph

```
                    ┌───────────────────┐
                    │    src/core/       │  ← ZERO external deps (pure Python + numpy/pandas)
                    │  types, indicators │
                    │  stats             │
                    └────────┬──────────┘
                             │ imports
                    ┌────────▼──────────┐
                    │  src/strategies/   │  ← imports core ONLY
                    │  signals, config   │  ← NO broker imports
                    │  backtester        │  ← NO MT5 imports
                    └────────┬──────────┘
                             │ imports
                    ┌────────▼──────────┐
                    │    src/data/       │  ← imports core ONLY
                    │  loader, mtf       │  ← NO strategy config imports
                    └────────┬──────────┘
                             │ imports
              ┌──────────────▼──────────────┐
              │      src/execution/          │  ← imports strategies + data + core
              │  runner, risk_manager,       │  ← imports MT5 connector
              │  position_manager, scheduler │  ← imports notifications
              │  executors/*                 │
              └──────────────┬──────────────┘
                             │ imports
              ┌──────────────▼──────────────┐
              │  src/execution/mt5_connector │  ← ONLY module that imports MetaTrader5
              └─────────────────────────────┘
                             │
              ┌──────────────▼──────────────┐
              │  src/execution/notifications │  ← imports configs ONLY
              │  telegram.py                 │  ← NO strategy logic imports
              └─────────────────────────────┘

    ╔═══════════════════════════════════════════════╗
    ║            RESEARCH BOUNDARY                  ║
    ║  research/ → imports src/strategies, src/core ║
    ║  research/ → NEVER imports src/execution      ║
    ╚═══════════════════════════════════════════════╝
```

### Dependency Rules

1. `src/core/` → imports NOTHING from the project (only numpy, pandas)
2. `src/strategies/` → imports `src/core/` only
3. `src/data/` → imports `src/core/` only (NO strategy config)
4. `src/execution/` → imports `src/strategies/`, `src/data/`, `src/core/`
5. `src/execution/mt5_connector.py` → is the ONLY file that `import MetaTrader5`
6. `research/` → imports `src/strategies/`, `src/core/`, `src/data/` — **NEVER** `src/execution/`
7. `tests/` → imports anything it needs to test

---

## PHASE 7 — Single Source of Truth

### Duplication Found

| Logic | Location 1 (Backtest) | Location 2 (Live) | Parity? |
|---|---|---|---|
| Asia MR indicators | `engine/asia/indicators.py` | `live/executors/asia_executor.py` imports from engine | ✅ Shared |
| Asia MR entry signals | `engine/asia/signals.py` | `live/executors/asia_executor.py` imports from engine | ✅ Shared |
| Asia MR exit logic | `engine/asia/signals.py` (`check_exit_conditions`) | `live/position_manager.py` (inline reimplementation) | 🔴 **DIVERGED** |
| London ORB opening range | `engine/london/strategy.py` | `live/executors/london_executor.py` (reimplemented) | 🔴 **DIVERGED** |
| London ORB breakout detection | `engine/london/engine.py` | `live/executors/london_executor.py` (reimplemented) | 🔴 **DIVERGED** |
| NY ORB opening range | `engine/ny/strategy.py` | `live/executors/ny_executor.py` (reimplemented) | 🔴 **DIVERGED** |
| NY ORB breakout detection | `engine/ny/engine.py` | `live/executors/ny_executor.py` (reimplemented) | 🔴 **DIVERGED** |
| True Range calculation | `engine/asia/indicators.py` | `live/executors/london_executor.py` & `ny_executor.py` (inline) | 🔴 **DUPLICATED** |
| Position sizing | `engine/asia/signals.py` (`_calculate_lot_size`) | `live/executors/asia_executor.py` (different formula) | 🟡 Different context (OK) |
| Z-Score exit thresholds | `configs/asia_config.py` | `configs/live_config.py` (duplicated constants) | 🔴 **DUPLICATED** |
| London/NY Stats dataclass | `engine/london/engine.py` | `engine/ny/engine.py` | 🔴 **DUPLICATED** |
| London/NY TradeManager | `engine/london/trade_manager.py` | `engine/ny/trade_manager.py` | 🔴 **DUPLICATED** |

### Recommended Canonical Locations

- **Indicators**: `src/core/indicators.py` — single implementation
- **Asia MR exit logic**: `src/strategies/asian_mr/signals.py` — live should import from here, not reimplement
- **London/NY OR formation**: `src/strategies/<name>/signals.py` — live executors should call a shared function
- **True Range**: `src/core/indicators.py::calc_true_range()` — never inline
- **BreakoutStats**: `src/core/stats.py` — parameterized base class for London/NY stats
- **TradeManager**: `src/core/trade_manager.py` — parameterized base for London/NY

---

## PHASE 8 — Configuration Architecture

### Current State

Configuration is split across 5 Python files and 1 `.env` file. The split is **mostly logical** but has issues:

| Config File | Contains | Issue |
|---|---|---|
| `asia_config.py` | Strategy params + backtest params + data paths | Mixes strategy & infrastructure |
| `london_config.py` | Strategy params + backtest params | Clean |
| `ny_config.py` | Strategy params + backtest params | Clean |
| `portfolio_config.py` | Portfolio composition + imports from strategy configs | Clean |
| `live_config.py` | Broker, risk, timing, Telegram, logging, safety guards | 🟡 Monolithic (185 lines) — too many concerns |
| `.env` | Telegram tokens, DRY_RUN flag | ✅ Good — secrets separated |

### Recommended Configuration Hierarchy

```
STRATEGY CONFIG (per strategy)          → Signal parameters, session timing, entry/exit rules
    ↓ imported by
PORTFOLIO CONFIG                        → Strategy switches, risk allocation, compounding
    ↓ imported by
LIVE EXECUTION CONFIG                   → Broker params, safety guards, execution mode
    ↓ reads from
ENVIRONMENT SECRETS (.env)              → API tokens, credentials, DRY_RUN flag
```

### Key Fix

`configs/live_config.py` lines 178-181 duplicate Asia exit parameters. These should reference `configs.asia_config` directly:

```python
# WRONG (current):
ASIA_Z_EXIT_THRESHOLD = 0.5
ASIA_Z_HARD_CUT = 3.2
ASIA_MAX_DURATION_MIN = 60

# RIGHT (proposed):
from configs.asia_config import Z_EXIT_THRESHOLD as ASIA_Z_EXIT_THRESHOLD
from configs.asia_config import Z_HARD_CUT as ASIA_Z_HARD_CUT
from configs.asia_config import MAX_TRADE_DURATION_MIN as ASIA_MAX_DURATION_MIN
```

---

## PHASE 9 — Data Architecture

### Current State: ✅ Good

- `data/` is gitignored ✅
- `.gitkeep` preserves directory ✅
- CSV files are large (109MB M1, 22MB M5) and correctly excluded ✅

### Recommendation

No changes needed. The current structure is correct:

```
data/
├── .gitkeep
├── xauusd-m1-bid-*.csv    # Raw M1 data (gitignored)
└── xauusd-m5-bid-*.csv    # Raw M5 data (gitignored)
```

If the project grows to multiple instruments, use:

```
data/
├── xauusd/
│   ├── m1/
│   └── m5/
├── eurusd/
│   ├── m1/
│   └── m5/
└── .gitkeep
```

---

## PHASE 10 — Output / Artifact Management

### Current State

`output/` is a single flat folder containing trade CSVs, chart PNGs, and text reports. This works at current scale but should be structured if output grows.

### Recommendation

```
output/                              # All gitignored
├── .gitkeep
├── backtests/                       # Backtest results
│   ├── portfolio_trades.csv
│   ├── london_trades.csv
│   └── ny_trades.csv
├── charts/                          # Generated images
│   ├── portfolio_chart.png
│   ├── monte_carlo_dashboard.png
│   └── sensitivity_surface.png
└── reports/                         # Text/markdown reports
    └── portfolio_log.txt
```

> **Note**: Don't overdo this for 3 strategies. The current flat `output/` is acceptable.

---

## PHASE 11 — Test Architecture

### Current State: 🔴 Insufficient

Only **1 test file** exists: `tests/test_live_audit_guards.py` (435 lines, 24KB). This file covers live trading safety only. **Zero unit tests** exist for:

- Indicators (SMA, RSI, ATR, Z-Score)
- Signal generation (entry/exit logic)
- Backtester correctness
- Data loader edge cases
- Configuration validation

### Recommended Structure

```
tests/
├── conftest.py                      # Shared fixtures (sample DataFrames, configs)
├── unit/
│   ├── test_indicators.py           # Test each indicator function
│   ├── test_asian_signals.py        # Test entry/exit signal logic
│   ├── test_london_signals.py
│   ├── test_ny_signals.py
│   ├── test_data_loader.py          # CSV parsing edge cases
│   ├── test_position_sizing.py      # Lot calculation
│   └── test_stats.py                # Statistics computation
├── integration/
│   ├── test_asian_backtester.py     # End-to-end backtest on sample data
│   ├── test_london_backtester.py
│   ├── test_ny_backtester.py
│   └── test_portfolio_engine.py
├── live/
│   └── test_audit_guards.py         # Existing file (KEEP)
└── strategy/
    ├── test_backtest_parity.py       # Verify backtest & live use same signals
    └── test_config_consistency.py    # Verify no duplicated constants
```

### Naming Convention

- `test_<module_name>.py` — mirrors source file
- `Test<ClassName>` — test class
- `test_<behavior>_<scenario>` — test method

---

## PHASE 12 — Live Trading Isolation

### Current State: ✅ Mostly Good

The `live/` package is self-contained. Research code (`analytics/`, `scripts/`, `visualization/`) does **not** import from `live/`. This is correct.

### Remaining Risk

The **only violation** is `position_manager.py` importing `engine.asia.indicators.compute_all`. This creates a coupling where changes to backtest indicator code could affect live trading. The live system should compute indicators through its own validated pipeline.

### Architecture Recommendation

```
src/
├── strategies/     # Canonical signal logic (shared)
├── execution/      # Live-only code (NEVER imported by research)
│   └── ...

research/           # NEVER imports execution/
    └── ...
```

**Guard**: Add a CI check or import linter that fails if `research/` ever imports from `src/execution/`.

---

## PHASE 13 — Deployment Architecture

### Current State: ✅ Adequate

```
deploy/
├── START_LIVE_BOT.bat       # Main startup
├── CHECK_CONNECTION.bat     # Quick health check
├── TEST_LIVE_SYSTEM.bat     # Full system diagnostic
└── UPDATE_LIVE_BOT.bat      # Git pull + restart
```

This is a Windows VPS deployment with batch files. It's simple, appropriate for a single-instance bot.

### Recommendation

No changes needed. If multi-environment deployment becomes necessary:

```
deploy/
├── production/
│   ├── START_LIVE_BOT.bat
│   └── .env.production
├── paper/
│   ├── START_PAPER_BOT.bat
│   └── .env.paper
└── common/
    ├── CHECK_CONNECTION.bat
    └── UPDATE_BOT.bat
```

---

## PHASE 14 — Security Structure

### Current State: ✅ Good

| Item | Location | In Git? | Status |
|---|---|---|---|
| `.env` (Telegram tokens, DRY_RUN) | Root | ❌ Gitignored | ✅ Safe |
| `.env.example` | Root | ✅ | ✅ No secrets |
| MT5 credentials | Windows terminal (IPC) | N/A | ✅ Never in code |
| Broker API keys | Not needed (MT5 IPC) | N/A | ✅ Safe |
| `bot.lock` | Root | ❌ Gitignored | ✅ Safe |

> **No secrets are stored in source code.** ✅

---

## PHASE 15 — Naming Conventions

### Issues Found

| Current Name | Issue | Suggested Name |
|---|---|---|
| `engine/` | Ambiguous — could mean execution engine | `strategies/` or keep `engine/` |
| `engine/asia/` | Abbreviation inconsistent | `engine/asian_mr/` |
| `engine/ny/` | Too abbreviated | `engine/ny_orb/` |
| `engine/london/engine.py` | File named same as parent package | `engine/london/backtester.py` |
| `engine/ny/engine.py` | Same issue | `engine/ny/backtester.py` |
| `live/live_runner.py` | Redundant prefix | `live/runner.py` |
| `live/live_config.py` | Shim file — confusing | DELETE (fix imports) |
| `live/live_system_check.py` | Long name | `live/system_check.py` |
| `main_asia.py` | Root clutter | `cli/backtest_asia.py` |
| `utils/` | Generic dumping ground risk | `data/` (since it only contains loaders) |

### Recommendation

- `engine/` → keep as `engine/` (clear enough in context)
- All strategy folders should use full descriptive names: `asian_mr/`, `london_orb/`, `ny_orb/`
- Eliminate shim files after a transition period
- `utils/` should be renamed to `data/` since it only contains data loaders, or split into `src/data/`

---

## PHASE 16 — Migration Map

### Major Module Moves (Option B)

| Current Path | Proposed Path | Why | Import Changes |
|---|---|---|---|
| `engine/asia/indicators.py` | `src/core/indicators.py` | Pure math belongs in core | All imports of `engine.asia.indicators` → `src.core.indicators` |
| `engine/asia/signals.py` | `src/strategies/asian_mr/signals.py` | Strategy-specific logic | `engine.asia.signals` → `src.strategies.asian_mr.signals` |
| `engine/asia/backtester.py` | `src/strategies/asian_mr/backtester.py` | Strategy-specific | `engine.asia.backtester` → `src.strategies.asian_mr.backtester` |
| `engine/london/strategy.py` | `src/strategies/london_orb/signals.py` | Rename for consistency | `engine.london.strategy` → `src.strategies.london_orb.signals` |
| `engine/london/engine.py` | `src/strategies/london_orb/backtester.py` | Rename to reflect purpose | `engine.london.engine` → `src.strategies.london_orb.backtester` |
| `engine/london/trade_manager.py` | `src/strategies/london_orb/trade_manager.py` | Keep | Path change only |
| `engine/ny/` | `src/strategies/ny_orb/` | Same as London | Path change only |
| `engine/portfolio/portfolio_engine.py` | `src/strategies/portfolio/engine.py` | Simplify name | `engine.portfolio.portfolio_engine` → `src.strategies.portfolio.engine` |
| `live/live_runner.py` | `src/execution/runner.py` | Cleaner name | `live.live_runner` → `src.execution.runner` |
| `live/mt5_connector.py` | `src/execution/mt5_connector.py` | Move to execution | Path change only |
| `live/risk_manager.py` | `src/execution/risk_manager.py` | Move to execution | Path change only |
| `live/position_manager.py` | `src/execution/position_manager.py` | Move to execution | Path change only |
| `live/scheduler.py` | `src/execution/scheduler.py` | Move to execution | Path change only |
| `live/logger.py` | `src/observability/logger.py` | Separate concern | `live.logger` → `src.observability.logger` |
| `live/executors/` | `src/execution/executors/` | Move to execution | Path change only |
| `live/telegram/` | `src/execution/notifications/` | Generalize name | `live.telegram` → `src.execution.notifications` |
| `utils/data_loader.py` | `src/data/loader.py` | Proper domain name | `utils.data_loader` → `src.data.loader` |
| `utils/mtf_loader.py` | `src/data/mtf_loader.py` | Proper domain name | `utils.mtf_loader` → `src.data.mtf_loader` |
| `analytics/` | `research/analytics/` | Separate from production | `analytics.*` → `research.analytics.*` |
| `visualization/` | `research/visualization/` | Separate from production | `visualization.*` → `research.visualization.*` |
| `scripts/` | Merged into `main.py` CLI | Eliminate separate runners | Remove; CLI handles dispatch |
| `configs/asia_config.py` | `src/strategies/asian_mr/config.py` | Co-locate with strategy | `configs.asia_config` → `src.strategies.asian_mr.config` |
| `configs/london_config.py` | `src/strategies/london_orb/config.py` | Co-locate | Same pattern |
| `configs/ny_config.py` | `src/strategies/ny_orb/config.py` | Co-locate | Same pattern |
| `configs/portfolio_config.py` | `src/strategies/portfolio/config.py` | Co-locate | Same pattern |
| `configs/live_config.py` | `src/execution/config.py` | Co-locate | `configs.live_config` → `src.execution.config` |
| `main_asia.py` | DELETE (absorbed into `main.py` CLI) | Root cleanup | N/A |
| `main_london.py` | DELETE | Root cleanup | N/A |
| `main_ny.py` | DELETE | Root cleanup | N/A |
| `main_portfolio.py` | DELETE | Root cleanup | N/A |
| `live/live_config.py` | DELETE (shim) | Remove backward compat shim | N/A |
| `live/telegram_notifier.py` | DELETE (shim) | Remove backward compat shim | N/A |

---

## PHASE 17 — Remove / Keep / Move / Merge

| Current Path | Action | Proposed Path | Reason |
|---|---|---|---|
| `main.py` | **KEEP** | `main.py` | Unified CLI entry point |
| `main_asia.py` | **MERGE** | Into `main.py` subcommand | Eliminate root clutter |
| `main_london.py` | **MERGE** | Into `main.py` subcommand | Same |
| `main_ny.py` | **MERGE** | Into `main.py` subcommand | Same |
| `main_portfolio.py` | **MERGE** | Into `main.py` subcommand | Same |
| `engine/__init__.py` | **MOVE** | `src/strategies/__init__.py` | Rename package |
| `engine/asia/` | **MOVE** | `src/strategies/asian_mr/` | Full descriptive name |
| `engine/london/` | **MOVE** | `src/strategies/london_orb/` | Full descriptive name |
| `engine/ny/` | **MOVE** | `src/strategies/ny_orb/` | Full descriptive name |
| `engine/portfolio/` | **MOVE** | `src/strategies/portfolio/` | Same |
| `engine/asia/indicators.py` | **SPLIT** | `src/core/indicators.py` (shared) + strategy-specific in `signals.py` | Shared math shouldn't be strategy-scoped |
| `live/` | **MOVE** | `src/execution/` | Cleaner name |
| `live/live_config.py` | **DELETE** | N/A | Shim — fix imports instead |
| `live/telegram_notifier.py` | **DELETE** | N/A | Shim — fix imports instead |
| `live/test_connection.py` | **MOVE** | `src/execution/diagnostics.py` | More descriptive |
| `live/live_system_check.py` | **MOVE** | `src/execution/system_check.py` | Drop redundant prefix |
| `configs/` | **SPLIT** | Each config co-located with its module | Strategy configs belong with strategies |
| `utils/` | **RENAME** | `src/data/` | Contents are all data-related |
| `analytics/` | **MOVE** | `research/analytics/` | Research code |
| `scripts/` | **MERGE** | Into `main.py` CLI subcommands | Eliminate redundant runners |
| `visualization/` | **MOVE** | `research/visualization/` | Research code |
| `tests/` | **KEEP+EXPAND** | `tests/unit/`, `tests/integration/`, `tests/live/` | Add missing test categories |
| `deploy/` | **KEEP** | `deploy/` | Unchanged |
| `docs/` | **KEEP** | `docs/` | Unchanged |
| `data/` | **KEEP** | `data/` | Unchanged |
| `output/` | **KEEP** | `output/` | Unchanged |
| `logs/` | **KEEP** | `logs/` | Unchanged |
| `.env` | **KEEP** | `.env` | Unchanged |
| `.env.example` | **KEEP** | `.env.example` | Unchanged |
| `.gitignore` | **KEEP** | `.gitignore` | Unchanged |
| `requirements.txt` | **KEEP** | `requirements.txt` | Unchanged |
| `README.md` | **KEEP** | `README.md` | Unchanged |

---

## PHASE 18 — Import Graph Analysis

### Most Imported Module

`configs/live_config.py` is imported by **every file in `live/`** — this is correct; it's the central configuration.

### Import Hotspots

```
configs.live_config    ← imported by 10+ files (OK — it's config)
configs.asia_config    ← imported by engine/asia/* + utils/data_loader (problem)
engine.asia.indicators ← imported by engine/asia/backtester + live/position_manager + live/executors/asia_executor
```

### Circular Dependencies

**None found.** The import graph is acyclic. ✅

### God Modules

| Module | Lines | Responsibilities | Verdict |
|---|---|---|---|
| `live/mt5_connector.py` | 542 | Connection, tick data, rates, orders, pending orders, close, timezone probe | 🟡 Borderline — but coherent (single broker adapter) |
| `live/live_runner.py` | 400 | State management, daily reset, tick cycle, weekend standby, main loop | 🟡 Acceptable with mixins |
| `engine/portfolio/portfolio_engine.py` | 597 | Trade merging, compounding, metrics, monthly breakdown | 🟡 Large but cohesive |
| `live/live_system_check.py` | ~600+ | Full system diagnostic | 🟢 Standalone diagnostic — OK |
| `engine/london/engine.py` | 435 | Full M5 + M1 backtester + stats | 🟡 Could split stats out |
| `engine/ny/engine.py` | 459 | Full M5 + M1 backtester + stats | 🟡 Near-duplicate of London |

---

## PHASE 19 — God Module Detection

### `live/position_manager.py` — Violation

This module does **too many things**:
1. Position tracking & notification (Entry/Exit)
2. OCO cancellation logic
3. Asia MR exit logic (Z-Score neutral, time-stop, hard-cut)
4. London session cutoff logic
5. NY session cutoff logic
6. **Directly imports `engine.asia.indicators.compute_all`** (couples live to backtest)

**Recommendation**: Extract Asia MR exit conditions into `src/strategies/asian_mr/signals.py::check_live_exit()` and have `position_manager.py` call it through dependency injection.

### `live/live_runner.py` — Acceptable

Uses mixin pattern effectively. Each session's evaluation logic is delegated to its executor. The runner itself handles state management and the main loop. **No action needed.**

---

## PHASE 20 — Entry Point Architecture

### Current: Scattered

```
python main.py                    # CLI dispatcher
python main.py portfolio          # → imports main_portfolio.py
python main.py asia               # → imports main_asia.py
python main.py live               # → imports live/live_runner.py
python main.py monte-carlo        # → imports scripts/run_monte_carlo.py
```

### Recommended: Unified

```
python main.py backtest portfolio [args...]
python main.py backtest asia [args...]
python main.py backtest london [args...]
python main.py backtest ny [args...]
python main.py live [--check-only] [--dry-run]
python main.py live-check
python main.py research monte-carlo [-n 1000]
python main.py research walk-forward
python main.py research friction-decay
python main.py research sensitivity
python main.py telegram-test
```

This groups commands by **context** (backtest, live, research) making intent clear.

---

## PHASE 21 — Final Recommended Directory Tree

```
quanttrade/                                     # Project root (renamed from "flg")
│
├── src/                                        # Production source code
│   ├── core/                                   # Domain primitives — ZERO external deps
│   │   ├── __init__.py
│   │   ├── types.py                            # Direction, ExitReason, Signal, TradeResult dataclasses
│   │   ├── indicators.py                       # SMA, RSI, ATR, Z-Score, ADX, True Range, HTF EMA
│   │   └── stats.py                            # Base BacktestStats, BreakoutStats classes
│   │
│   ├── strategies/                             # Strategy implementations
│   │   ├── __init__.py
│   │   ├── asian_mr/                           # Asian Mean Reversion
│   │   │   ├── __init__.py
│   │   │   ├── config.py                       # Strategy parameters
│   │   │   ├── signals.py                      # Entry/exit signal logic
│   │   │   └── backtester.py                   # Simulation engine
│   │   ├── london_orb/                         # London Opening Range Breakout
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   ├── signals.py
│   │   │   ├── backtester.py
│   │   │   └── trade_manager.py
│   │   ├── ny_orb/                             # New York Opening Range Breakout
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   ├── signals.py
│   │   │   ├── backtester.py
│   │   │   └── trade_manager.py
│   │   └── portfolio/                          # Multi-strategy portfolio
│   │       ├── __init__.py
│   │       ├── config.py
│   │       └── engine.py
│   │
│   ├── execution/                              # Live trading ONLY
│   │   ├── __init__.py
│   │   ├── config.py                           # Live config + .env loading
│   │   ├── runner.py                           # LivePortfolioTrader
│   │   ├── mt5_connector.py                    # MetaTrader 5 broker adapter
│   │   ├── risk_manager.py                     # PID lock, circuit breaker, reconciliation
│   │   ├── position_manager.py                 # Active position exits
│   │   ├── scheduler.py                        # Session schedule + DST
│   │   ├── system_check.py                     # Pre-execution diagnostic
│   │   ├── diagnostics.py                      # Connection health check
│   │   ├── executors/
│   │   │   ├── __init__.py
│   │   │   ├── asia.py                         # Asia MR live executor
│   │   │   ├── london.py                       # London ORB live executor
│   │   │   └── ny.py                           # NY ORB live executor
│   │   └── notifications/
│   │       ├── __init__.py
│   │       └── telegram.py                     # Telegram HTTP notification engine
│   │
│   ├── data/                                   # Data loading & processing
│   │   ├── __init__.py
│   │   ├── loader.py                           # CSV loader (decoupled from strategy config)
│   │   └── mtf_loader.py                       # Multi-timeframe alignment pipeline
│   │
│   └── observability/                          # Logging infrastructure
│       ├── __init__.py
│       └── logger.py                           # Dual logging + QuickEdit + TradeJournal
│
├── research/                                   # Research & validation (NEVER imports execution/)
│   ├── analytics/
│   │   ├── __init__.py
│   │   ├── monte_carlo.py
│   │   ├── walk_forward.py
│   │   ├── friction_decay.py
│   │   └── parameter_sensitivity.py
│   └── visualization/
│       ├── __init__.py
│       ├── asia_charts.py
│       ├── ny_charts.py
│       └── portfolio_charts.py
│
├── tests/
│   ├── conftest.py                             # Shared test fixtures
│   ├── unit/
│   │   ├── test_indicators.py
│   │   ├── test_asian_signals.py
│   │   ├── test_london_signals.py
│   │   ├── test_ny_signals.py
│   │   ├── test_data_loader.py
│   │   └── test_position_sizing.py
│   ├── integration/
│   │   ├── test_asian_backtester.py
│   │   ├── test_london_backtester.py
│   │   ├── test_ny_backtester.py
│   │   └── test_portfolio_engine.py
│   ├── live/
│   │   └── test_audit_guards.py
│   └── strategy/
│       ├── test_backtest_live_parity.py
│       └── test_config_consistency.py
│
├── deploy/
│   ├── START_LIVE_BOT.bat
│   ├── CHECK_CONNECTION.bat
│   ├── TEST_LIVE_SYSTEM.bat
│   └── UPDATE_LIVE_BOT.bat
│
├── docs/
│   ├── STRESS_TEST_REPORT.md
│   └── VPS_DEPLOYMENT_GUIDE.md
│
├── data/                                       # Gitignored market data
│   └── .gitkeep
├── output/                                     # Gitignored backtest results
│   └── .gitkeep
├── logs/                                       # Gitignored runtime logs
│   └── .gitkeep
│
├── main.py                                     # Unified CLI entry point
├── .env                                        # Secrets (gitignored)
├── .env.example                                # Template
├── .gitignore
├── requirements.txt
└── README.md
```

---

## PHASE 22 — Architectural Rules

### Rules for This Repository

**RULE 1: Strategy code must NEVER import MetaTrader5.**  
Only `src/execution/mt5_connector.py` may import `MetaTrader5`. Strategies must be broker-agnostic.

**RULE 2: Live execution must use the same canonical signal implementation as backtesting.**  
The Asia MR exit logic in `position_manager.py` must call functions from `src/strategies/asian_mr/signals.py`, not reimplement them.

**RULE 3: Generated artifacts must NEVER live inside Python source packages.**  
CSVs, PNGs, logs, lock files → `data/`, `output/`, `logs/` only. Never inside `src/`.

**RULE 4: Secrets must NEVER exist in source control.**  
All API tokens, credentials, and environment-specific values must be in `.env` (gitignored). The `.env.example` template must contain only placeholder values.

**RULE 5: Research code must NEVER import from `src/execution/`.**  
`research/` may import `src/core/`, `src/strategies/`, `src/data/` — never live execution modules.

**RULE 6: Configuration constants must have a SINGLE SOURCE OF TRUTH.**  
If `ASIA_Z_EXIT_THRESHOLD = 0.5` exists in `asia_config.py`, the live config must import it, not duplicate it.

**RULE 7: Pure mathematical functions (indicators) must be stateless and strategy-agnostic.**  
`calc_rsi()`, `calc_atr()`, `calc_zscore()` should take parameters, not read from config modules directly.

**RULE 8: The `src/core/` package must have ZERO imports from other project packages.**  
It may only import standard library, numpy, and pandas.

**RULE 9: Every strategy must be self-contained in its own directory.**  
Adding a new strategy = creating `src/strategies/<name>/` with `config.py`, `signals.py`, `backtester.py`.

**RULE 10: The unified CLI (`main.py`) is the ONLY entry point for end users.**  
No more standalone `main_asia.py`, `main_london.py` etc.

**RULE 11: All timestamps in the system must be UTC.**  
No local time should leak into data processing, logging, or signal evaluation.

**RULE 12: Shim files for backward compatibility must be time-limited and tracked.**  
If a shim is created (like `live/live_config.py`), set a deadline for removal and document it.

**RULE 13: Code duplication between London ORB and NY ORB must be eliminated through parameterization.**  
`trade_manager.py`, `Stats` dataclasses, and `engine.py` should share a base implementation.

**RULE 14: The PID lock file path must be configurable and must be in a gitignored location.**  
Currently `bot.lock` is at root and gitignored — acceptable but should be in `logs/`.

**RULE 15: Every module must have a clear single responsibility.**  
`position_manager.py` should NOT contain indicator computation for Asia MR exits.

---

## PHASE 23 — Final Review

### 1. What is wrong with the CURRENT structure?

The current structure is **surprisingly good for a solo project**. The main issues are:
- **5 entry point files** cluttering the root (`main_asia.py`, etc.)
- **Signal logic duplication** between backtest engines and live executors
- **Configuration duplication** (Asia exit params in both `asia_config.py` and `live_config.py`)
- **2 shim files** that exist only for backward compatibility
- **Near-zero test coverage** outside of live safety guards
- **Code duplication** between London and NY ORB implementations

### 2. What is the biggest architectural risk?

> **Backtest-live divergence of signal logic.** The London/NY ORB breakout detection is reimplemented in the live executors rather than sharing the canonical engine logic. If someone changes the backtest strategy, the live executor may not be updated, leading to **different behavior in production vs research**.

### 3. Which files are currently in the wrong location?

- `utils/data_loader.py` — shouldn't import `configs.asia_config` (couples utility to strategy)
- `live/position_manager.py` — shouldn't import `engine.asia.indicators` (couples live to backtest internals)
- `engine/asia/indicators.py` — shared math (SMA, RSI, ATR) should be in `core/`, not nested under a strategy

### 4. Which modules should become the canonical source of truth?

- `engine/asia/signals.py` → canonical for ALL Asia MR signal logic (backtest + live)
- `engine/london/strategy.py` → canonical for London ORB signals (live executor should import, not reimplement)
- `engine/ny/strategy.py` → canonical for NY ORB signals

### 5. Where should live trading code live?

`src/execution/` — completely isolated from research code, with its own `config.py`.

### 6. Where should backtesting code live?

`src/strategies/<name>/backtester.py` — co-located with the strategy it tests.

### 7. Where should strategy code live?

`src/strategies/<name>/` — each strategy is a self-contained directory.

### 8. Where should data live?

`data/` at project root — gitignored, never inside source packages.

### 9. Where should generated results live?

`output/` at project root — gitignored. Optionally subdivide into `output/backtests/`, `output/charts/`, `output/reports/`.

### 10. Where should tests live?

`tests/` with subdirectories: `unit/`, `integration/`, `live/`, `strategy/`.

### 11. Where should deployment code live?

`deploy/` — unchanged.

### 12. How can we prevent research code from accidentally affecting live trading?

- **Directory boundary**: `research/` is a separate top-level directory
- **Import guard**: CI linter that fails if `research/` imports from `src/execution/`
- **No shared state**: research code never writes to `logs/` or `bot.lock`

### 13. How can we prevent live code from diverging from backtest logic?

- **Canonical signal functions**: Live executors import entry/exit logic from `src/strategies/`
- **Parity test**: `tests/strategy/test_backtest_live_parity.py` verifies identical signal output
- **Config single source**: No duplicated constants

### 14. What should NEVER be put into Git?

- `.env` (secrets)
- `data/*.csv` (large datasets)
- `output/*` (generated artifacts)
- `logs/*` (runtime logs)
- `bot.lock` (PID lockfile)
- `__pycache__/` (byte-compiled Python)
- `*.log` files
- Any file > 10MB
- Any API key, token, or credential

### 15. What structure would still make sense at 10 strategies, 20 symbols, multiple brokers?

The recommended Option B structure scales cleanly:

```
src/strategies/
├── asian_mr/              # Strategy 1
├── london_orb/            # Strategy 2
├── ny_orb/                # Strategy 3
├── session_momentum/      # Strategy 4 (future)
├── mean_reversion_h1/     # Strategy 5 (future)
└── portfolio/             # Portfolio orchestrator

src/execution/
├── brokers/               # Multiple broker adapters
│   ├── base.py            # Abstract interface
│   ├── mt5/               # MetaTrader 5
│   ├── fix/               # FIX protocol (future)
│   └── ibkr/              # Interactive Brokers (future)
├── executors/             # Per-strategy executors
│   ├── asian_mr.py
│   ├── london_orb.py
│   └── ...
```

At Option C scale (10+ strategies), you'd want:
- Strategy registry for auto-discovery
- YAML config files
- Abstract strategy interface
- Plugin architecture for brokers

But **Option B is the right choice today**. Don't build for 10 strategies when you have 3.

---

> **Summary**: This is a well-built solo-developer quantitative trading system with solid fundamentals. The primary risks are signal logic duplication between backtest and live, insufficient test coverage, and some configuration duplication. The recommended Option B architecture addresses these without over-engineering.
