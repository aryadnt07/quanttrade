# CRITICAL QUANT TRADING SYSTEM AUDIT
## FOCUS: IDEMPOTENCY + DUPLICATE ORDER PREVENTION

### 1. Executive Summary
This report presents an adversarial analysis of the FLG quantitative trading system's idempotency guarantees. The central question of the audit was: *"Can the same trading intent ever reach the broker more than once?"*

**Verdict: UNSAFE.**
The current architecture **cannot guarantee** at-most-once execution under network failure conditions. The system treats `UNKNOWN` order states (timeouts) as `FAILED` states, abandons running threads, and relies on delayed broker-state reconciliation. This creates a critical race condition that guarantees duplicate orders during high-latency network events.

### 2. Actual Execution Flow
The standard execution path follows:
1. `_tick_cycle()` in `runner.py` pulls data.
2. `LondonLiveStrategy.evaluate_entry()` evaluates signals.
3. If valid, `runner._dispatch_order_intent()` sets `order_in_flight = True`.
4. `MT5Connector.open_market_order()` delegates execution to a `ThreadPoolExecutor` for timeout guarding.
5. If successful, `trades_today` flag is set to `True`, locking the session.
6. `order_in_flight` is set to `False`.

### 3. Trading Intent Definition
In this repository, a unique trading intent is defined by:
`Strategy ID (e.g., LONDON)` + `Trading Day (Date)`

The bot enforces a strict "One Trade Per Session Per Day" rule using the `trades_today` boolean flag in each strategy. This is a sound conceptual model, provided the flag state accurately reflects broker state.

### 4. Signal Identity
The system **lacks an explicit cryptographic or deterministic idempotency key** (such as a UUID client order ID).
Duplicate detection relies entirely on after-the-fact state observation:
*"Does the broker report an open position or a closed deal with my Magic Number and Strategy Comment?"*
Because there is no unique intent ID passed to the broker, the broker cannot natively deduplicate multiple identical market order requests.

### 5. Entry Idempotency (The Critical Vulnerability)
**Entry execution is NOT idempotent.**
Because the system lacks an Idempotency Key, duplicate requests sent to the broker *will* be executed as distinct orders. The system attempts to prevent duplicates locally using `trades_today` and `order_in_flight` flags, but these flags are brittle under timeout conditions.

### 6. Order Timeout Analysis (P0 Vulnerability)
In `mt5_connector.py`, `_safe_order_send` uses a `ThreadPoolExecutor` with a `timeout_sec=10.0`.
```python
        except concurrent.futures.TimeoutError:
            print(f"[💥 IPC TIMEOUT] mt5.order_send() melampaui batas waktu...")
            executor.shutdown(wait=False, cancel_futures=True)
            return None
```
**CRITICAL FLAW:** `cancel_futures=True` only cancels futures that *have not started*. The `mt5.order_send` call is already running in a C-extension thread. Python cannot forcefully kill it.
The main thread receives `None`, treats it as a failure (`OrderResult(False)`), and continues. The abandoned thread continues trying to send the order to the broker!

### 7. Retry Analysis
When an order "fails" (including timeouts), `runner.py` and `risk_manager.py` handle it via `_handle_order_result` and `reconcile_broker_orders`.
If `mt5.positions_get()` does not YET show the position (because MT5 hasn't synced the network response), reconciliation fails.
The `retry_count` is incremented.
Crucially, in `runner.py`:
```python
        finally:
            strategy.order_in_flight = False
```
Because `order_in_flight` is reset to `False` and `trades_today` is still `False`, the very next tick will generate the SAME signal and send a SECOND order. If the abandoned thread from the previous attempt eventually succeeds, **two positions are created.**

### 8. Concurrency Analysis
The main event loop is single-threaded, preventing parallel evaluation of the same tick. However, the use of `ThreadPoolExecutor` in the connector introduces uncontrolled background concurrency during timeouts, as abandoned threads can execute concurrently with subsequent main-loop ticks.

### 9. Restart Analysis
**PARTIAL SAFETY.** Upon restart, `runner.py` calls `_sync_state_from_broker()`, which queries `history_deals_get` for today's deals. If the bot crashed *after* broker execution but *before* saving local state, the restart logic successfully detects the executed deal via Magic Number/Comment and sets `trades_today = True`. This prevents replay, assuming the MT5 API responds correctly.

### 10. Reconnect Analysis
**PARTIAL SAFETY.** Similar to restart, if MT5 disconnects and reconnects, reconciliation logic relies on `positions_get` and `history_deals_get`. However, if the MT5 terminal API is momentarily desynced from the broker server immediately after a reconnect, the bot might falsely assume no position exists.

### 11. Multi-Instance Analysis
**PARTIAL SAFETY.** `RiskManager.acquire_pid_lock()` effectively prevents two bot processes from running on the same OS by checking process liveness via OS APIs. However, this does not protect against running two bots on *different VMs* connected to the same MT5 account.

### 12. Partial Close Idempotency
**VERIFIED SAFE.** The bot's exit logic (`close_position`) sends a `TRADE_ACTION_DEAL` that explicitly specifies `position=ticket`. MetaTrader 5 guarantees that an action against a specific ticket is idempotent. If a timeout occurs and the bot retries closing the same ticket, the broker will reject the second attempt because the ticket is already closed. The bot does not currently use partial closes.

### 13. SL/TP Modification Idempotency
N/A. The current bot architecture sets SL/TP strictly at entry and does not dynamically modify them via `TRADE_ACTION_SLTP`. All exits are executed as market closes.

### 14. Order ↔ Position Correlation
The system correlates positions using the `magic_number` and the order `comment` (e.g., "London"). This correlation is generally sound but lacks a 1:1 signal-to-order mapping. If two positions are accidentally opened with the "London" comment, the bot's logic will simply see that *a* position exists and assume fulfillment.

### 15. Ownership Analysis
The bot reliably distinguishes its positions from manual positions by filtering on `lcfg.MAGIC_NUMBER`. Manual positions have a magic number of 0.

### 16. State Update Ordering
The system follows this order:
1. `order_in_flight = True` (Local lock)
2. `order_send` (Broker Request)
3. `order_in_flight = False` (Local unlock)
4. `trades_today = True` (if success)

The flaw is unlocking `order_in_flight` even when the broker response is `UNKNOWN` (timeout). The system defaults to "assume failure", which is dangerous.

### 17. At-Most-Once / At-Least-Once Analysis
The system currently attempts **At-Least-Once** semantics. It prefers retrying an order if it believes it failed. In financial systems, Entry Orders must use **At-Most-Once** semantics (better to miss a trade than double your risk), while Exit Orders should use At-Least-Once semantics (you MUST close the position eventually).

### 18. Failure Scenario Matrix

| Scenario | Duplicate Possible? | Reason | Severity |
|---|---|---|---|
| Same signal detected twice | NO | `trades_today` flag prevents it. | Safe |
| Order request times out | **YES** | Abandoned threads + local state retry. | P0 |
| Order succeeds, response lost | **YES** | Reconciliation fails if MT5 history lags. | P0 |
| Bot crashes after execution | NO | `_sync_state_from_broker` restores state. | Safe |
| Restart before state persistence | NO | Relies on MT5 broker history. | Safe |
| Two bot instances (same OS) | NO | PID Lockfile prevents execution. | Safe |
| Two bot instances (diff OS) | **YES** | No distributed lock. | P1 |

### 19. Idempotency Matrix

| Operation | Unique Identity | Current Protection | Duplicate Possible? |
|---|---|---|---|
| Entry | Strategy + Date | `trades_today`, `order_in_flight` | **YES (Timeout Race)** |
| Full Close | Ticket ID | MT5 Ticket Validation | NO |
| OCO Pending | Strategy + Date | `trades_today`, `pending_orders` | NO |

### 20. Critical Invariants
1. **UNKNOWN ≠ FAILED.** A timeout means the order state is unknown. The bot must NOT retry an entry order if the previous attempt timed out.
2. **Abandoned Threads are Lethal.** A thread blocked on a network call cannot be killed. It must be assumed that it will eventually execute.
3. **Session Lock.** Once an intent is dispatched, the session must lock until absolute proof of failure is received.

### 21. P0/P1 Findings
- **[P0] Timeout Retry Race Condition:** `_safe_order_send` masking timeouts as `None`, combined with `finally: strategy.order_in_flight = False`, guarantees duplicate execution if the broker executes the order but the local network response times out.
- **[P1] Distributed Lock Absence:** The PID lock protects a single OS but does not protect the MT5 account from accidental multi-VM deployment.

### 22. Conceptual Minimum Safe Architecture
1. **UNKNOWN Order State Handling:** If `order_send` times out, the bot MUST set `trades_today = True` or enter a `CIRCUIT_BREAKER_HALT` state. It is infinitely safer to miss the trade than to double-enter.
2. **Idempotency Keys:** If the broker supports it, inject a unique UUID into a custom field (or the `comment` field if parseable) *before* sending. Reconciliation must search for this exact UUID.

### 23. Final Idempotency Verdict

**A. SIGNAL DUPLICATION**
PARTIAL (Protected by memory flags, vulnerable to timeout resets).

**B. ENTRY DUPLICATION**
**YES** (Timeout and abandoned thread race conditions guarantee duplication).

**C. UNKNOWN ORDER RESULT**
**NO** (Architecture treats UNKNOWN as FAILED and triggers retries).

**D. RESTART SAFETY**
YES (Assuming MT5 history API is responsive).

**E. RECONNECT SAFETY**
YES (Reconciliation catches it if MT5 syncs fast enough).

**F. CONCURRENCY SAFETY**
**NO** (`ThreadPoolExecutor` abandons threads that continue execution).

**G. MULTI-INSTANCE SAFETY**
PARTIAL (Safe on single OS, unsafe on distributed OS).

**H. EXIT IDEMPOTENCY**
YES (Protected by MT5 ticket validation).

**I. OVERALL IDEMPOTENCY**
**UNSAFE**
