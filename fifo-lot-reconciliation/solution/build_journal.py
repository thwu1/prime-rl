#!/usr/bin/env python3
"""
Build hledger portfolio journal from brokerage CSV transaction history.

Reads /app/transactions.csv, parses each transaction, and computes:
- Tax lot tracking with FIFO disposal by acquisition date
- Stock split adjustments (share doubling, cost basis halving)
- IRS wash sale detection (30-day rule) with proportional disallowance
- Gain/loss classification by holding period (short-term vs long-term)
- Gift lot handling with donor's original acquisition date

"""

import csv
import re
from datetime import datetime


def parse_date(s):
    """Parse YYYY-MM-DD string to datetime."""
    return datetime.strptime(s.strip(), "%Y-%m-%d")


def fmt_usd(amount):
    """Format dollar amount for hledger: positive $X.XX, negative $-X.XX."""
    if amount >= 0:
        return f"${amount:.2f}"
    return f"$-{abs(amount):.2f}"


def held_over_one_year(acq_date_str, sell_date_str):
    """Determine if holding period exceeds one year (long-term)."""
    acq = parse_date(acq_date_str)
    sell = parse_date(sell_date_str)
    try:
        anniversary = acq.replace(year=acq.year + 1)
    except ValueError:
        # Feb 29 edge case
        anniversary = acq.replace(year=acq.year + 1, day=28)
    return sell > anniversary


def lot_account(ticker, acq_date, cost_per_share):
    """Construct the lot subaccount path per naming convention."""
    return f"assets:broker:{ticker.lower()}:{acq_date}_${cost_per_share:.2f}"


def read_transactions(path):
    """Parse the brokerage CSV into a list of transaction dicts."""
    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append({
                "date":     row["Date"].strip(),
                "type":     row["Type"].strip(),
                "security": row["Security"].strip(),
                "shares":   int(row["Shares"]) if row["Shares"].strip() else 0,
                "price":    float(row["Price"]) if row["Price"].strip() else 0.0,
                "amount":   float(row["Amount"]) if row["Amount"].strip() else 0.0,
                "notes":    row.get("Notes", "").strip(),
            })
    return rows


def build_journal(csv_path, journal_path):
    """Main logic: read CSV, compute all entries, write the journal."""
    txns = read_transactions(csv_path)

    # Per-ticker lot state: ticker -> [{acq_date, cost, shares}, ...]
    lots = {}
    # Pending wash sale adjustments: ticker -> disallowed_amount
    pending_wash = {}
    # Accumulated journal entry strings
    entries = []

    for i, tx in enumerate(txns):
        kind = tx["type"]

        # ── DEPOSIT ──────────────────────────────────────────────
        if kind == "DEPOSIT":
            entries.append(
                f"{tx['date']} Initial deposit\n"
                f"    assets:broker:cash  ${tx['amount']:.2f}\n"
                f"    equity:opening"
            )

        # ── BUY ──────────────────────────────────────────────────
        elif kind == "BUY":
            ticker = tx["security"]
            shares = tx["shares"]
            price = tx["price"]
            cash = tx["amount"]

            # Check if this buy is a wash sale replacement purchase
            if ticker in pending_wash:
                disallowed = pending_wash.pop(ticker)
                adj_cost = price + disallowed / shares
                acct = lot_account(ticker, tx["date"], adj_cost)
                lots.setdefault(ticker, []).append(
                    {"acq_date": tx["date"], "cost": adj_cost, "shares": shares}
                )
                entries.append(
                    f"{tx['date']} Buy {shares} {ticker} @ ${price:.2f}"
                    f"  ; wash sale replacement — basis adjusted to ${adj_cost:.2f}\n"
                    f"    {acct}  {shares} {ticker} @ ${adj_cost:.2f}\n"
                    f"    assets:broker:cash  {fmt_usd(-cash)}\n"
                    f"    revenues:gains:short-term  {fmt_usd(-disallowed)}"
                )
            else:
                acct = lot_account(ticker, tx["date"], price)
                lots.setdefault(ticker, []).append(
                    {"acq_date": tx["date"], "cost": price, "shares": shares}
                )
                entries.append(
                    f"{tx['date']} Buy {shares} {ticker} @ ${price:.2f}\n"
                    f"    {acct}  {shares} {ticker} @ ${price:.2f}\n"
                    f"    assets:broker:cash  {fmt_usd(-cash)}"
                )

        # ── TRANSFER_IN (gift) ───────────────────────────────────
        elif kind == "TRANSFER_IN":
            ticker = tx["security"]
            shares = tx["shares"]
            price = tx["price"]
            cash = tx["amount"]

            # Extract donor's original acquisition date from notes
            m = re.search(r"donor acquired (\d{4}-\d{2}-\d{2})", tx["notes"])
            donor_date = m.group(1) if m else tx["date"]

            acct = lot_account(ticker, donor_date, price)
            lots.setdefault(ticker, []).append(
                {"acq_date": donor_date, "cost": price, "shares": shares}
            )
            entries.append(
                f"{tx['date']} Receive {shares} {ticker} as gift"
                f"  ; donor acquired {donor_date} at ${price:.2f}/share\n"
                f"    {acct}  {shares} {ticker} @ ${price:.2f}\n"
                f"    revenues:gifts  {fmt_usd(-cash)}"
            )

        # ── SPLIT ────────────────────────────────────────────────
        elif kind == "SPLIT":
            ticker = tx["security"]
            m = re.search(r"(\d+):(\d+)", tx["notes"])
            numerator = int(m.group(1))
            denominator = int(m.group(2))
            ratio = numerator / denominator

            current = lots.get(ticker, [])
            lines = [
                f"{tx['date']} {ticker} {numerator}:{denominator} forward stock split"
                f"  ; shares double, cost basis halves"
            ]

            updated_lots = []
            total_new_shares = 0

            for lot in current:
                old_shares = lot["shares"]
                new_shares = int(old_shares * ratio)
                new_cost = lot["cost"] / ratio
                old_acct = lot_account(ticker, lot["acq_date"], lot["cost"])
                new_acct = lot_account(ticker, lot["acq_date"], new_cost)

                # Close pre-split lot, open post-split lot
                lines.append(f"    {old_acct}  -{old_shares} {ticker}")
                lines.append(f"    {new_acct}  {new_shares} {ticker}")
                total_new_shares += new_shares - old_shares
                updated_lots.append({
                    "acq_date": lot["acq_date"],
                    "cost": new_cost,
                    "shares": new_shares,
                })

            # Balance additional shares via equity:adjustments
            lines.append(f"    equity:adjustments  -{total_new_shares} {ticker}")

            lots[ticker] = updated_lots
            entries.append("\n".join(lines))

        # ── SELL ─────────────────────────────────────────────────
        elif kind == "SELL":
            ticker = tx["security"]
            to_sell = tx["shares"]
            sell_px = tx["price"]
            proceeds = tx["amount"]
            sell_date = tx["date"]

            # Sort lots by acquisition date for FIFO disposal
            fifo_lots = sorted(
                lots.get(ticker, []), key=lambda l: l["acq_date"]
            )

            disposals = []  # (snapshot_dict, shares_taken, is_long_term)
            remaining = to_sell
            st_gain = 0.0
            lt_gain = 0.0

            for lot in fifo_lots:
                if remaining <= 0 or lot["shares"] <= 0:
                    continue
                take = min(remaining, lot["shares"])
                gain = take * (sell_px - lot["cost"])
                is_lt = held_over_one_year(lot["acq_date"], sell_date)

                # Snapshot the lot info before modifying shares
                disposals.append((
                    {"acq_date": lot["acq_date"], "cost": lot["cost"]},
                    take,
                    is_lt,
                ))
                if is_lt:
                    lt_gain += gain
                else:
                    st_gain += gain

                lot["shares"] -= take
                remaining -= take

            total_gain = st_gain + lt_gain

            # Wash sale detection: if loss, look ahead for replacement buy
            # within 30 calendar days of the sale
            if total_gain < 0:
                sell_dt = parse_date(sell_date)
                for j in range(i + 1, len(txns)):
                    ftx = txns[j]
                    if ftx["type"] == "BUY" and ftx["security"] == ticker:
                        buy_dt = parse_date(ftx["date"])
                        days_gap = (buy_dt - sell_dt).days
                        if 0 < days_gap <= 30:
                            repl_shares = ftx["shares"]
                            # Proportional disallowance when fewer replacement
                            # shares than shares sold at a loss
                            proportion = min(repl_shares, to_sell) / to_sell
                            disallowed = abs(total_gain) * proportion
                            pending_wash[ticker] = disallowed
                            break

            # Construct journal entry for the sale
            lines = [
                f"{sell_date} Sell {to_sell} {ticker} @ ${sell_px:.2f}  ; FIFO"
            ]
            for snap, take, _ in disposals:
                acct = lot_account(ticker, snap["acq_date"], snap["cost"])
                lines.append(
                    f"    {acct}  -{take} {ticker} @ ${snap['cost']:.2f}"
                )
            lines.append(f"    assets:broker:cash  ${proceeds:.2f}")

            # Gains/losses split by holding period
            if lt_gain != 0:
                lines.append(
                    f"    revenues:gains:long-term  {fmt_usd(-lt_gain)}"
                )
            if st_gain != 0:
                lines.append(
                    f"    revenues:gains:short-term  {fmt_usd(-st_gain)}"
                )
            entries.append("\n".join(lines))

        # ── DIVIDEND ─────────────────────────────────────────────
        elif kind == "DIVIDEND":
            amt = tx["amount"]
            ticker = tx["security"]
            entries.append(
                f"{tx['date']} Dividend from {ticker} holdings\n"
                f"    assets:broker:cash  ${amt:.2f}\n"
                f"    revenues:dividends  {fmt_usd(-amt)}"
            )

    # ── Write the journal file ───────────────────────────────────
    with open(journal_path, "w") as f:
        f.write("; Investment Portfolio Journal - Brokerage Account 2024\n")
        f.write(";\n")
        f.write("; Lot tracking: manual subaccounts\n")
        f.write(
            ";   Format: assets:broker:<ticker>:<acq-date>_$<per-share-cost>\n"
        )
        f.write(";   Gift lots use the donor's original acquisition date\n")
        f.write(
            ";   Cost basis reflects post-split and wash-sale adjustments\n"
        )
        f.write(";\n")
        f.write("; Disposal: FIFO by acquisition date\n")
        f.write("; Gains: short-term (held <= 1yr) vs long-term (held > 1yr)\n")
        f.write("\n")
        for entry in entries:
            f.write(entry + "\n\n")

    print(f"Journal written to {journal_path}")


if __name__ == "__main__":
    build_journal("/app/transactions.csv", "/app/portfolio.journal")
