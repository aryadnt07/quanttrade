# CRITICAL QUANT TRADING SYSTEM AUDIT: LIVE ↔ BACKTEST SEMANTIC PARITY

## 1. Executive Summary

This adversarial audit evaluates the semantic equivalence between the LIVE execution engine (MT5) and the BACKTEST engine across the `asian_mr` (Mean Reversion) and `ny_orb` (Breakout) strategies. 

**Verdict: MATERIAL PARITY FAILURE (P0/P1)**

While the codebase demonstrates a strong architectural separation between domain logic and execution (e.g., `ILiveStrategy`, `IBroker`), there are critical semantic divergences in how the backtest evaluates time series data versus how the live engine interacts with real-world broker execution. 

The most severe finding (P0) is an **Exit Logic Disconnect in the Asian Mean Reversion strategy**: The live engine sends a hard Take Profit (TP) order to the MT5 broker, while the backtest completely ignores the hard TP and only exits based on Z-Score neutrality at the candle close. This guarantees that live trading and backtesting will produce completely different trade durations, win rates, and PnL distributions.

---

## 2. Overall Parity Verdict

**OVERALL SEMANTIC PARITY: MATERIAL PARITY FAILURE**

### A. SIGNAL PARITY
**PARTIAL**: Backtest and Live use the same core indicators and logic (`signals.py`). However, backtest enters exactly at the candle `close` (Asian MR) or `or_high` (NY ORB), whereas live enters at the `Ask`/`Bid` tick price. 

### B. EXECUTION PARITY
**NO**: Live execution is subject to broker `stops_level` rejections, exact tick evaluation, and slippage. Backtest assumes perfect execution at requested prices with zero slippage on stop-losses.

### C. RISK PARITY
**PARTIAL**: Live calculates position sizes using the assumed entry price (candle `close` in Asian MR), but executes at `Ask`/`Bid`. This creates a slight misalignment between intended risk and actual executed risk.

### D. EXIT PARITY
**NO (P0 Failure)**: Major divergences exist in Take Profit evaluation (Asian MR) and Spread handling for Short Stop Losses (Asian MR).

### E. STATE PARITY
**YES**: State management (daily trade counts, lockouts, session schedules) is well synchronized between live and backtest.

---

## 3. Critical Findings & Parity Failures

### 🚨 [P0] Asian MR: Ignored Hard Take Profit in Backtest
**Component:** Exit Parity
**Severity:** P0 (Invalidates Backtest)
**Direction of Bias:** Unknown (highly divergent)

* **LIVE Behavior:** `evaluate_asian_entry` generates an `OrderIntent` with a specific `take_profit` (set to `row["anchor"]`). The live runner dispatches this to `mt5_connector.open_market_order`, which sends the hard TP to the MT5 server. If the price touches this TP intrabar, the broker immediately closes the trade for a profit.
* **BACKTEST Behavior:** In `asian_mr/signals.py`, `check_exit_conditions()` **completely ignores** `signal.take_profit`. It only checks if `zscore` returns to the neutral zone (`[-0.5, 0.5]`). 
* **Impact:** In the backtest, price can spike and hit the anchor intrabar, but if the candle closes with the Z-Score outside the neutral zone, the backtest will *stay in the trade*. Live would have already exited with a profit.

### 🚨 [P1] Asian MR: Short Stop-Loss Spread Discrepancy
**Component:** Exit Parity (Bid/Ask)
**Severity:** P1
**Direction of Bias:** Optimistic in Backtest

* **LIVE Behavior:** MT5 triggers a Stop Loss for a SHORT position when the **Ask** price reaches the SL level.
* **BACKTEST Behavior:** In `asian_mr/signals.py`, `check_exit_conditions()` triggers SL if the candle `high` >= `stop_loss`. Standard OHLC data is based on the Bid price. 
* **Impact:** Because `Ask = Bid + Spread`, the Ask price is always higher. Live short trades will be stopped out earlier/more frequently than the backtest indicates. (Note: The `ny_orb` backtester correctly fixes this by adding `cfg.SPREAD_USD` to the high/low for shorts in `NYTradeManager`, but `asian_mr` does not).

### ⚠️ [P2] Intrabar Sequence Assumption (SL before TP)
**Component:** Same-Candle Semantics
**Severity:** P2
**Direction of Bias:** Pessimistic in Backtest

* **LIVE Behavior:** Depends entirely on the actual tick sequence (whether the price spiked up then down, or down then up).
* **BACKTEST Behavior:** In both `asian_mr/signals.py` and `ny_orb/trade_manager.py`, the backtest always evaluates Stop Loss **before** Take Profit. 
* **Impact:** If a single 5-minute candle spans both the SL and TP levels, the backtest guarantees a loss, whereas live execution might have hit the TP first. 

### ⚠️ [P2] Broker Stops Level Rejection
**Component:** Order Validation
**Severity:** P2
**Direction of Bias:** Optimistic in Backtest

* **LIVE Behavior:** In `mt5_connector.py` (Line 348), if the requested TP is closer to the entry price than the broker's `stops_level`, the live engine cancels the TP (`tp = None`) to prevent order rejection.
* **BACKTEST Behavior:** Assumes the TP is perfectly placed regardless of how close it is to the entry price.
* **Impact:** Live trades may occasionally run without a hard TP (relying only on Z-Score or session cutoff), exposing the live account to higher risk and different trade durations than backtested.

---

## 4. Full Parity Matrix

| Component | LIVE | BACKTEST | Same Semantics? | Severity |
|---|---|---|---|---|
| **Market Data** | Live Ticks (Bid/Ask) + M5 | OHLC M5 (Bid-based) | PARTIAL | P2 |
| **Timezone/DST** | Dynamic UTC translation | Fixed UTC translation | EXACTLY PARITY | - |
| **Session Bounds** | `is_in_any_active_window` | `is_in_entry_window` | EXACTLY PARITY | - |
| **Indicators** | Shared `signals.py` | Shared `signals.py` | EXACTLY PARITY | - |
| **Entry Trigger** | Ask/Bid crossing levels | OHLC crossing levels | PARTIAL | P2 |
| **Entry Price** | MT5 Executed (Ask/Bid) | Candle Close / `or_high` | SEMANTICALLY DIFFERENT | P2 |
| **Spread Handling** | Real MT5 Spread | Fixed `cfg.SPREAD_USD` on exit | SEMANTICALLY DIFFERENT | P2 |
| **Slippage** | Real Market Slippage | Zero Slippage Assumed | SEMANTICALLY DIFFERENT | P2 |
| **SL Evaluation** | Broker Server (Tick) | `signals.py` / `trade_manager.py` | SEMANTICALLY DIFFERENT | P1 |
| **TP Evaluation** | Broker Server (Tick) | Z-Score (Asia) / H/L (NY) | **NO PARITY** | **P0** |
| **Position Sizing**| Based on Signal (Close) | Based on Signal (Close) | EXACTLY PARITY | - |
| **Timeout Exit** | 16:30 UTC / 06:00 UTC | 16:30 UTC / 06:00 UTC | EXACTLY PARITY | - |
| **Order Execution**| Market/Pending OCO | Simulated immediate | SEMANTICALLY DIFFERENT | P2 |

---

## 5. Quantitative Impact Assessment

For the **[P0] Ignored Hard Take Profit** issue in Asian MR:
1. **How many trades affected?** Any trade where price touches the VWAP/SMA (anchor) intrabar but reverses before the candle closes.
2. **Backtest Bias?** Unknown, but likely alters win rate and trade duration significantly. The backtest might show a loss where live showed a win, or vice-versa (if live TP is hit, but backtest stays in and rides a bigger trend).
3. **Validity:** The Asian MR backtest is currently testing a different exit strategy than what is running live. The backtest results cannot be trusted to represent live performance.

For the **[P1] Short Stop-Loss Spread** issue in Asian MR:
1. **How many trades affected?** Any short trade where the high of the candle comes within `spread` distance of the Stop Loss.
2. **Backtest Bias?** Optimistic. The backtest will survive stop hunts that will kill the live trade.
3. **Validity:** Win rate and max drawdown for short trades are likely overstated in the backtest.

---

## 6. Minimum Safe Fixes

### Fix 1: Align Asian MR Take Profit Logic (P0)
**File:** `src/strategies/asian_mr/signals.py`
**Function:** `check_exit_conditions`
**Fix:** Add hard TP evaluation before Z-Score evaluation to match live MT5 behavior.
```python
    # Take Profit (Hard TP sent to broker)
    if signal.direction.is_long and high >= signal.take_profit:
        return ExitReason.TAKE_PROFIT
    if signal.direction.is_short and low <= signal.take_profit:
        return ExitReason.TAKE_PROFIT
```

### Fix 2: Align Asian MR Short SL with Spread (P1)
**File:** `src/strategies/asian_mr/signals.py`
**Function:** `check_exit_conditions`
**Fix:** Apply simulated spread to the candle high when evaluating Short SLs.
```python
    ask_high = high + cfg.SPREAD_USD
    if signal.direction.is_short and ask_high >= signal.stop_loss:
        return ExitReason.STOP_LOSS
```

### Fix 3: Implement Stops Level Rejection in Backtest (P2)
**File:** `src/strategies/asian_mr/backtester.py` & `src/strategies/ny_orb/backtester.py`
**Fix:** If the initial risk (SL distance) or TP distance is less than a configured `STOPS_LEVEL`, either cancel the TP (to match live) or reject the entry entirely.

---
*Audit completed by Antigravity Quantitative Systems Auditor.*
