#!/usr/bin/env python3
"""
Run the fill simulation across three queue position models and write results.json.
"""

import json
import numpy as np
from microstructure import (
    OrderBook,
    RiskAdverseQueueModel,
    ProbQueueModel,
    power_prob_func,
    log_prob_func,
)

DEPTH_EVENT = 1
TRADE_EVENT = 2
DEPTH_SNAPSHOT_EVENT = 4
EXCH_EVENT = 1 << 31
LOCAL_EVENT = 1 << 30
BUY_EVENT = 1 << 29
SELL_EVENT = 1 << 28


def run_simulation(data, orders_cfg, queue_model):
    """Run the fill simulation for one queue model."""
    tick_size = orders_cfg["tick_size"]
    lot_size = orders_cfg["lot_size"]
    maker_fee_rate = orders_cfg["maker_fee_rate"]
    orders = orders_cfg["orders"]

    ob = OrderBook(tick_size, lot_size)

    order_states = {}
    order_active = {}
    order_placed = {}

    for o in orders:
        order_active[o["id"]] = True
        order_placed[o["id"]] = False

    fills = []

    def record_fill(o, fill_time, fill_price):
        qty = o["qty"]
        fee = fill_price * qty * maker_fee_rate
        fills.append({
            "order_id": o["id"],
            "filled": True,
            "fill_time_ns": fill_time,
            "fill_price": fill_price,
            "qty": qty,
            "fee": fee,
            "side": o["side"],
        })
        order_active[o["id"]] = False

    for i in range(len(data)):
        event = data[i]
        ev = int(event['ev'])
        exch_ts = int(event['exch_ts'])
        px = float(event['px'])
        qty = float(event['qty'])

        is_trade = (ev & TRADE_EVENT) != 0
        is_depth = (ev & DEPTH_EVENT) != 0
        is_snapshot = (ev & DEPTH_SNAPSHOT_EVENT) != 0
        is_buy = (ev & BUY_EVENT) != 0
        is_sell = (ev & SELL_EVENT) != 0

        prev_qty, new_qty = ob.process_event(event)

        # Place orders at submit time
        for o in orders:
            oid = o["id"]
            if not order_placed[oid] and exch_ts >= o["submit_time_ns"]:
                side = o["side"]
                order_price = o["price"]
                if side == "buy":
                    dq = ob.best_bid_qty
                else:
                    dq = ob.best_ask_qty
                order_states[oid] = queue_model.new_order(dq)
                order_placed[oid] = True

        # Process trade events for queue position
        if is_trade:
            for o in orders:
                oid = o["id"]
                if not order_active[oid] or not order_placed[oid]:
                    continue

                side = o["side"]
                order_price = o["price"]

                if side == "buy" and is_sell and px < order_price:
                    record_fill(o, exch_ts, order_price)
                    continue
                if side == "sell" and is_buy and px > order_price:
                    record_fill(o, exch_ts, order_price)
                    continue

                if side == "buy" and is_sell and px == order_price:
                    queue_model.trade(order_states[oid], qty)
                    exec_qty = queue_model.is_filled(order_states[oid])
                    if exec_qty >= o["qty"]:
                        record_fill(o, exch_ts, order_price)
                elif side == "sell" and is_buy and px == order_price:
                    queue_model.trade(order_states[oid], qty)
                    exec_qty = queue_model.is_filled(order_states[oid])
                    if exec_qty >= o["qty"]:
                        record_fill(o, exch_ts, order_price)

        # Process depth events for queue position
        if is_depth or is_snapshot:
            for o in orders:
                oid = o["id"]
                if not order_active[oid] or not order_placed[oid]:
                    continue

                side = o["side"]
                order_price = o["price"]

                if side == "buy" and is_buy and px == order_price:
                    queue_model.depth(order_states[oid], prev_qty, new_qty)
                elif side == "sell" and is_sell and px == order_price:
                    queue_model.depth(order_states[oid], prev_qty, new_qty)

            # Price improvement fill check
            best_ask = ob.best_ask
            best_bid = ob.best_bid
            for o in orders:
                oid = o["id"]
                if not order_active[oid] or not order_placed[oid]:
                    continue
                side = o["side"]
                order_price = o["price"]
                if side == "buy" and order_price >= best_ask:
                    record_fill(o, exch_ts, order_price)
                elif side == "sell" and order_price <= best_bid:
                    record_fill(o, exch_ts, order_price)

    # Record unfilled orders
    for o in orders:
        if order_active[o["id"]]:
            fills.append({"order_id": o["id"], "filled": False})

    # Compute aggregates
    position = 0.0
    balance = 0.0
    total_fees = 0.0
    for f in fills:
        if not f["filled"]:
            continue
        v = f["fill_price"] * f["qty"]
        fee = f["fee"]
        total_fees += fee
        if f["side"] == "buy":
            balance -= v
            position += f["qty"]
        else:
            balance += v
            position -= f["qty"]
    balance -= total_fees

    return {
        "fills": [{k: v for k, v in f.items() if k != "side"} for f in fills],
        "position": position,
        "balance": balance,
        "total_fees": total_fees,
    }


def main():
    raw = np.load('/app/market_data.npz')
    data = raw['data']

    with open('/app/orders.json') as f:
        orders_cfg = json.load(f)

    lot_size = orders_cfg["lot_size"]

    models = {
        "risk_adverse": RiskAdverseQueueModel(lot_size),
        "prob_power_2": ProbQueueModel(lot_size, power_prob_func(2.0)),
        "prob_log": ProbQueueModel(lot_size, log_prob_func()),
    }

    results = {}
    for name, model in models.items():
        results[name] = run_simulation(data, orders_cfg, model)

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Wrote /app/results.json")
    for name in results:
        filled = sum(1 for f in results[name]["fills"] if f["filled"])
        print(f"  {name}: {filled} fills, pos={results[name]['position']}, "
              f"bal={results[name]['balance']:.4f}")


if __name__ == "__main__":
    main()
