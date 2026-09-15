Build a fill simulator that replays L2 market data and determines limit order fills using probability-based queue position estimation, as used in HFT backtesting systems for modeling realistic order execution.

## Data

- `/app/market_data.npz` — NumPy structured array `data` with dtype fields: `ev` (u8 event flags), `exch_ts` (i8), `local_ts` (i8), `px` (f8 price), `qty` (f8 quantity), `order_id` (u8), `ival` (i8), `fval` (f8). Event types encoded in lower 8 bits of `ev`: `DEPTH_EVENT=1`, `TRADE_EVENT=2`, `DEPTH_SNAPSHOT_EVENT=4`. Side flags: `BUY_EVENT=1<<29`, `SELL_EVENT=1<<28`. Validity flags: `EXCH_EVENT=1<<31`, `LOCAL_EVENT=1<<30`.
- `/app/orders.json` — limit orders: `{order_id, side, price, qty, submit_event_idx}[]`
- `/app/config.json` — `{tick_size, lot_size, maker_fee, taker_fee}`

## Requirements

Implement `/app/simulator.py` with:

**Probability functions** — each with `prob(front, back) -> float` where `front` is queue quantity ahead, `back` is quantity behind:
`PowerProbQueueFunc(n)`: `back^n/(back^n+front^n)`;
`LogProbQueueFunc()`: `ln(1+back)/(ln(1+back)+ln(1+front))`;
`LogProbQueueFunc2()`: `ln(1+back)/ln(1+back+front)`;
`PowerProbQueueFunc2(n)`: `back^n/(back+front)^n`;
`PowerProbQueueFunc3(n)`: `1-(front/(front+back))^n`

**`QueuePos`** — with float attributes `front_q_qty` and `cum_trade_qty`

**`OrderBook(tick_size, lot_size)`** — L2 book tracking: `update_bid(price_tick, qty)->prev_qty`, `update_ask(price_tick, qty)->prev_qty`, `bid_qty_at_tick(price_tick)->float`, `ask_qty_at_tick(price_tick)->float`, properties `best_bid_tick`, `best_ask_tick`, `tick_size`, `lot_size`

**`ProbQueueModel(prob_func)`** — queue position estimator:
- `new_order(side, price_tick, book) -> QueuePos`: init `front_q_qty` from book depth at order price
- `trade(qpos, qty)`: `front_q_qty -= qty`, `cum_trade_qty += qty`
- `depth(qpos, prev_qty, new_qty)`: compute `chg = prev_qty - new_qty`; subtract `cum_trade_qty` and reset it; if `chg < 0` cap front at `new_qty`; if `chg > 0`, decompose into `front` (=`front_q_qty`) and `back` (=`prev_qty - front`), compute `prob(front, back)`, then `est = front - (1-prob)*chg + min(0, back - prob*chg)` capped at `new_qty`
- `is_filled(qpos, lot_size) -> float`: return executable qty when `front_q_qty < 0`

**Fill rules**: A buy order fills when (a) `best_ask <= order_price` after any book update, (b) a SELL trade occurs at a price below the order's price, or (c) a SELL trade at the order's price drives `front_q_qty` negative via queue exhaustion. Mirror for sell orders with BUY trades and `best_bid`. Only `DEPTH_EVENT` (not `DEPTH_SNAPSHOT_EVENT`) triggers `ProbQueueModel.depth()`. All fills use `maker_fee`.

**`run_simulation(data, orders_spec, config, prob_func)`** returning `(fills_dict, book_snapshots_dict)`

Create `/app/run_simulation.py` that runs simulations with `PowerProbQueueFunc(2)`, `PowerProbQueueFunc(3)`, and `LogProbQueueFunc()`, writing `/app/results.json`:
```json
{
  "probabilities": {
    "power2_front10_back5": "<prob(10,5) with PowerProbQueueFunc(2)>",
    "power3_3_front10_back5": "<prob(10,5) with PowerProbQueueFunc3(3)>",
    "log_front10_back5": "<prob(10,5) with LogProbQueueFunc>",
    "log2_front10_back5": "<prob(10,5) with LogProbQueueFunc2>",
    "power2_2_front10_back5": "<prob(10,5) with PowerProbQueueFunc2(2)>"
  },
  "fills": {
    "power_n2": {"filled_order_ids": [], "total_fills": 0, "pnl": 0.0, "total_fees": 0.0, "final_position": 0.0},
    "power_n3": {"filled_order_ids": [], "total_fills": 0, "pnl": 0.0, "total_fees": 0.0, "final_position": 0.0},
    "log": {"filled_order_ids": [], "total_fills": 0, "pnl": 0.0, "total_fees": 0.0, "final_position": 0.0}
  },
  "book_snapshots": {
    "event_500": {"best_bid": 0.0, "best_ask": 0.0},
    "event_1000": {"best_bid": 0.0, "best_ask": 0.0},
    "event_1500": {"best_bid": 0.0, "best_ask": 0.0}
  }
}
```

Execute via `python3 /app/run_simulation.py`.