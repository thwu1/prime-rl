#!/usr/bin/python3
"""Portfolio lot-tracking engine for ledger-format investment journals."""

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP


def q2(d):
    """Quantize Decimal to 2 decimal places."""
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Journal parsing
# ---------------------------------------------------------------------------

def parse_journal(filepath):
    """Return (prices, transactions) from a ledger-format journal."""
    prices = []
    transactions = []

    with open(filepath) as fh:
        lines = fh.readlines()

    i = 0
    while i < len(lines):
        raw = lines[i].rstrip("\n")
        stripped = raw.strip()

        if not stripped or stripped.startswith(";"):
            i += 1
            continue

        # Skip automated transaction rules and their postings
        if stripped.startswith("="):
            i += 1
            while i < len(lines) and lines[i][:1] in (" ", "\t"):
                i += 1
            continue

        # Price directive: P DATE COMMODITY $PRICE
        m = re.match(r"^P\s+(\d{4}/\d{2}/\d{2})\s+(\S+)\s+\$([0-9.]+)", raw)
        if m:
            prices.append((m.group(1), m.group(2), Decimal(m.group(3))))
            i += 1
            continue

        # Transaction header: DATE [*!] DESCRIPTION
        m = re.match(r"^(\d{4}/\d{2}/\d{2})\s+", raw)
        if m:
            txn_date = m.group(1)
            postings = []
            i += 1
            while i < len(lines) and lines[i][:1] in (" ", "\t"):
                p = lines[i].strip()
                if p and not p.startswith(";"):
                    postings.append(p)
                i += 1
            transactions.append((txn_date, postings))
            continue

        i += 1

    return prices, transactions


# ---------------------------------------------------------------------------
# Posting classification
# ---------------------------------------------------------------------------

# Buy with lot annotation: ACCOUNT  QTY COMMODITY {$COST} [YYYY/MM/DD]
_RE_BUY_LOT = re.compile(
    r"^(\S+(?:\s+\S+)*?)\s+(\d+(?:\.\d+)?)\s+([A-Z]+)\s+"
    r"\{\$([0-9.]+)\}\s+\[(\d{4}/\d{2}/\d{2})\]"
)

# Buy with total cost: ACCOUNT  QTY COMMODITY @@ $TOTAL
_RE_BUY_TOTAL = re.compile(
    r"^(\S+(?:\s+\S+)*?)\s+(\d+(?:\.\d+)?)\s+([A-Z]+)\s+@@\s+\$([0-9.]+)"
)

# Sell: ACCOUNT  -QTY COMMODITY @ $PRICE
_RE_SELL = re.compile(
    r"^(\S+(?:\s+\S+)*?)\s+-(\d+(?:\.\d+)?)\s+([A-Z]+)\s+@\s+\$([0-9.]+)"
)


def classify_posting(posting, txn_date):
    """Return a dict describing a buy/sell, or None for irrelevant lines."""
    # Virtual postings start with ( or [
    if posting.startswith("(") or posting.startswith("["):
        return None

    m = _RE_BUY_LOT.match(posting)
    if m:
        return {
            "type": "buy",
            "qty": Decimal(m.group(2)),
            "commodity": m.group(3),
            "cost": Decimal(m.group(4)),
            "lot_date": m.group(5),
        }

    m = _RE_BUY_TOTAL.match(posting)
    if m:
        qty = Decimal(m.group(2))
        total = Decimal(m.group(4))
        return {
            "type": "buy",
            "qty": qty,
            "commodity": m.group(3),
            "cost": total / qty,
            "lot_date": txn_date,
        }

    m = _RE_SELL.match(posting)
    if m:
        return {
            "type": "sell",
            "qty": Decimal(m.group(2)),
            "commodity": m.group(3),
            "price": Decimal(m.group(4)),
        }

    return None


# ---------------------------------------------------------------------------
# Core processing with wash sale detection
# ---------------------------------------------------------------------------

def process(transactions, method="fifo", cutoff=None):
    """Replay transactions and return (lots, gains) with wash sale analysis."""
    lots = defaultdict(list)
    gains = []

    # Pre-collect all events in chronological order
    events = []
    for txn_date, postings in transactions:
        if cutoff and txn_date > cutoff:
            break
        for line in postings:
            p = classify_posting(line, txn_date)
            if p is not None:
                events.append((txn_date, p))

    # Track pending wash sale cost adjustments: event_index -> total_adjustment
    pending_adjustments = {}

    for i, (date, event) in enumerate(events):
        if event["type"] == "buy":
            adj = pending_adjustments.pop(i, Decimal("0"))
            lot_cost = event["cost"]
            if adj:
                lot_cost = event["cost"] + adj / event["qty"]
            lots[event["commodity"]].append({
                "qty": event["qty"],
                "cost": lot_cost,
                "date": event["lot_date"],
            })

        elif event["type"] == "sell":
            com = event["commodity"]
            sell_qty = event["qty"]
            sale_price = event["price"]

            clots = lots[com]

            # Determine lot consumption order
            if method == "lifo":
                order = list(range(len(clots) - 1, -1, -1))
            elif method == "hifo":
                order = sorted(range(len(clots)),
                               key=lambda x: clots[x]["cost"], reverse=True)
            else:  # fifo
                order = list(range(len(clots)))

            remaining = sell_qty
            cost_basis = Decimal("0")
            earliest_lot_date = None
            exhausted = []

            for idx in order:
                if remaining <= 0:
                    break
                lot = clots[idx]
                take = min(remaining, lot["qty"])
                cost_basis += take * lot["cost"]
                if earliest_lot_date is None or lot["date"] < earliest_lot_date:
                    earliest_lot_date = lot["date"]
                remaining -= take
                if take == lot["qty"]:
                    exhausted.append(idx)
                else:
                    lot["qty"] -= take

            for idx in sorted(exhausted, reverse=True):
                clots.pop(idx)

            proceeds = sell_qty * sale_price
            gain = q2(proceeds - q2(cost_basis))

            # Wash sale detection (forward-looking, 30 calendar days)
            disallowed = Decimal("0")
            if gain < 0:
                sell_dt = datetime.strptime(date, "%Y/%m/%d")
                replacement_total = Decimal("0")
                replacement_events = []

                for j in range(i + 1, len(events)):
                    future_date, future_event = events[j]
                    future_dt = datetime.strptime(future_date, "%Y/%m/%d")
                    days_diff = (future_dt - sell_dt).days
                    if days_diff > 30:
                        break
                    if (future_event["type"] == "buy"
                            and future_event["commodity"] == com):
                        replacement_events.append((j, future_event["qty"]))
                        replacement_total += future_event["qty"]

                if replacement_total > 0:
                    replacement_shares = min(replacement_total, sell_qty)
                    abs_loss = abs(gain)
                    disallowed = q2(replacement_shares / sell_qty * abs_loss)

                    # Distribute adjustment across replacement lots
                    allocated = Decimal("0")
                    for evt_idx, evt_qty in replacement_events:
                        share = min(evt_qty, replacement_shares - allocated)
                        if share <= 0:
                            break
                        lot_adj = q2(share / sell_qty * abs_loss)
                        pending_adjustments[evt_idx] = (
                            pending_adjustments.get(evt_idx, Decimal("0"))
                            + lot_adj
                        )
                        allocated += share

            # Holding period classification
            sell_dt = datetime.strptime(date, "%Y/%m/%d")
            earliest_dt = datetime.strptime(earliest_lot_date, "%Y/%m/%d")
            holding_days = (sell_dt - earliest_dt).days
            holding_period = ("long-term" if holding_days > 365
                              else "short-term")

            adjusted_gain = q2(gain + disallowed)

            gains.append({
                "date": date,
                "commodity": com,
                "qty_sold": sell_qty,
                "price": sale_price,
                "proceeds": q2(proceeds),
                "cost_basis": q2(cost_basis),
                "gain": gain,
                "wash_sale_disallowed": disallowed,
                "adjusted_gain": adjusted_gain,
                "holding_period": holding_period,
            })

    return lots, gains


def latest_price(prices, commodity, as_of):
    """Most-recent price for commodity on or before as_of date string."""
    best = None
    for dt, com, px in prices:
        if com == commodity and dt <= as_of:
            if best is None or dt >= best[0]:
                best = (dt, px)
    return best[1] if best else None


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def fmt_lots(lots):
    out = []
    for com, lst in lots.items():
        for lot in lst:
            tc = q2(lot["qty"] * lot["cost"])
            out.append({
                "commodity": com,
                "quantity": float(lot["qty"]),
                "cost_per_unit": float(q2(lot["cost"])),
                "total_cost": float(tc),
                "acquisition_date": lot["date"],
            })
    out.sort(key=lambda x: (x["acquisition_date"], x["commodity"],
                            x["cost_per_unit"]))
    return {"lots": out}


def fmt_gains(gains):
    txns = []
    total_gain = Decimal("0")
    total_disallowed = Decimal("0")
    total_adjusted = Decimal("0")
    st_adjusted = Decimal("0")
    lt_adjusted = Decimal("0")

    for g in gains:
        txns.append({
            "date": g["date"],
            "commodity": g["commodity"],
            "quantity_sold": float(g["qty_sold"]),
            "sale_price_per_unit": float(g["price"]),
            "total_proceeds": float(g["proceeds"]),
            "total_cost_basis": float(g["cost_basis"]),
            "realized_gain": float(g["gain"]),
            "wash_sale_disallowed": float(g["wash_sale_disallowed"]),
            "adjusted_gain": float(g["adjusted_gain"]),
            "holding_period": g["holding_period"],
        })
        total_gain += g["gain"]
        total_disallowed += g["wash_sale_disallowed"]
        total_adjusted += g["adjusted_gain"]
        if g["holding_period"] == "long-term":
            lt_adjusted += g["adjusted_gain"]
        else:
            st_adjusted += g["adjusted_gain"]

    return {
        "transactions": txns,
        "total_realized_gain": float(q2(total_gain)),
        "total_wash_sale_disallowed": float(q2(total_disallowed)),
        "total_adjusted_gain": float(q2(total_adjusted)),
        "short_term_adjusted_gain": float(q2(st_adjusted)),
        "long_term_adjusted_gain": float(q2(lt_adjusted)),
    }


def fmt_market(lots, prices, date):
    agg = {}
    total_cost = Decimal("0")

    for com, lst in lots.items():
        tq = sum(l["qty"] for l in lst)
        lc = sum(l["qty"] * l["cost"] for l in lst)
        total_cost += lc
        px = latest_price(prices, com, date)
        if px is None:
            continue
        mv = tq * px
        agg[com] = {
            "commodity": com,
            "total_quantity": float(tq),
            "market_price": float(q2(px)),
            "market_value": float(q2(mv)),
        }

    ordered = sorted(agg.values(), key=lambda x: x["commodity"])
    tmv = sum(Decimal(str(h["market_value"])) for h in ordered)
    tcq = q2(total_cost)
    ug = q2(tmv - tcq)

    return {
        "date": date,
        "holdings": ordered,
        "total_market_value": float(q2(tmv)),
        "total_cost_basis": float(tcq),
        "total_unrealized_gain": float(ug),
    }


# ---------------------------------------------------------------------------
# Validate — cross-check against ledger CLI
# ---------------------------------------------------------------------------

def cmd_validate(date, prices, txns):
    """Cross-validate commodity holdings against ledger CLI balance output."""
    lots, _ = process(txns, "fifo", date)
    holdings = {}
    for com, lst in lots.items():
        tq = sum(float(l["qty"]) for l in lst)
        if tq > 0:
            holdings[com] = round(tq, 2)

    # ledger --end is exclusive, so add one day
    dt = datetime.strptime(date, "%Y/%m/%d")
    end_dt = dt + timedelta(days=1)
    end_str = end_dt.strftime("%Y/%m/%d")

    res = subprocess.run(
        ["ledger", "-f", "/app/portfolio.journal", "balance",
         "Assets:Brokerage", "--flat", "--no-total",
         "--end", end_str, "--columns", "200"],
        capture_output=True, text=True, timeout=30
    )

    ledger_holdings = {}
    for line in res.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                qty = round(float(parts[0].replace(",", "")), 2)
                com = parts[1]
                if re.match(r'^[A-Z]+$', com):
                    ledger_holdings[com] = qty
            except ValueError:
                continue

    valid = True
    all_coms = set(list(holdings.keys()) + list(ledger_holdings.keys()))
    for com in all_coms:
        if abs(holdings.get(com, 0) - ledger_holdings.get(com, 0)) > 0.01:
            valid = False

    out = {
        "valid": valid,
        "holdings": dict(sorted(holdings.items())),
        "ledger_holdings": dict(sorted(ledger_holdings.items())),
    }
    print(json.dumps(out, indent=2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Portfolio lot-tracking engine")
    sp = ap.add_subparsers(dest="cmd")

    p1 = sp.add_parser("lots")
    p1.add_argument("--date")
    p1.add_argument("--method", default="fifo",
                     choices=["fifo", "lifo", "hifo"])

    p2 = sp.add_parser("realized-gains")
    p2.add_argument("--date")
    p2.add_argument("--method", default="fifo",
                     choices=["fifo", "lifo", "hifo"])

    p3 = sp.add_parser("market-value")
    p3.add_argument("--date", required=True)
    p3.add_argument("--method", default="fifo",
                     choices=["fifo", "lifo", "hifo"])

    p4 = sp.add_parser("validate")
    p4.add_argument("--date", required=True)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        sys.exit(1)

    prices, txns = parse_journal("/app/portfolio.journal")

    if args.cmd == "validate":
        cmd_validate(args.date, prices, txns)
        return

    lot_data, gain_data = process(txns, args.method,
                                  getattr(args, "date", None))

    if args.cmd == "lots":
        result = fmt_lots(lot_data)
    elif args.cmd == "realized-gains":
        result = fmt_gains(gain_data)
    elif args.cmd == "market-value":
        result = fmt_market(lot_data, prices, args.date)
    else:
        ap.print_help()
        sys.exit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
