
"""Fix all three bugs in the event-sourced matching engine."""


def fix_engine():
    """Bug 1: Matching uses order.quantity instead of order.remaining for fill
    computation. When an incoming order matches multiple resting orders, the
    fill quantity for subsequent matches is calculated from the original order
    quantity rather than the remaining unfilled quantity, causing overfills."""
    with open("/app/engine.py", "r") as f:
        src = f.read()

    src = src.replace(
        "fill_qty = min(buy_order.quantity, resting.remaining)",
        "fill_qty = min(buy_order.remaining, resting.remaining)",
    )
    src = src.replace(
        "fill_qty = min(sell_order.quantity, resting.remaining)",
        "fill_qty = min(sell_order.remaining, resting.remaining)",
    )

    with open("/app/engine.py", "w") as f:
        f.write(src)


def fix_snapshot():
    """Bug 2: Snapshot serialization converts Decimal prices to float, losing
    precision. Decimal(float(Decimal('100.10'))) produces
    Decimal('100.0999999999999943157318115234375'), which is not equal to the
    original Decimal('100.10'). This corrupts order prices after snapshot
    restore, breaking cancel operations and state hash comparisons."""
    with open("/app/snapshot.py", "r") as f:
        src = f.read()

    src = src.replace(
        '"price": float(order.price),',
        '"price": str(order.price),',
    )
    src = src.replace(
        'price=Decimal(data["price"]),',
        'price=Decimal(str(data["price"])),',
    )

    with open("/app/snapshot.py", "w") as f:
        f.write(src)


def fix_replay():
    """Bug 3: Replay from snapshot uses >= instead of > for the sequence number
    boundary check. The snapshot already includes the effect of the last event
    (last_seq), so replaying events with seq >= last_seq causes the boundary
    event to be processed twice, creating duplicate orders in the book."""
    with open("/app/replay.py", "r") as f:
        src = f.read()

    src = src.replace(
        'if ev["seq"] >= last_seq:',
        'if ev["seq"] > last_seq:',
    )

    with open("/app/replay.py", "w") as f:
        f.write(src)


if __name__ == "__main__":
    fix_engine()
    fix_snapshot()
    fix_replay()
    print("All fixes applied.")
