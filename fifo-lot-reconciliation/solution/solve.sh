#!/usr/bin/env bash

cd /app

# Step 1: Examine the source transaction data
echo "=== Step 1: Reading source CSV ==="
head -1 /app/transactions.csv
wc -l /app/transactions.csv
echo ""

# Step 2: Identify transaction types and key events requiring special handling
echo "=== Step 2: Analyzing transaction types ==="
awk -F, 'NR>1 {print $2}' /app/transactions.csv | sort | uniq -c
echo ""
echo "Checking for stock splits..."
grep SPLIT /app/transactions.csv
echo ""
echo "Checking for gift transfers (donor holding period matters)..."
grep TRANSFER_IN /app/transactions.csv
echo ""
echo "Checking for potential wash sales (sells at loss followed by buys within 30 days)..."
grep -E 'SELL|BUY' /app/transactions.csv
echo ""

# Step 3: Build the journal programmatically from the CSV
# This script reads the CSV, tracks lots with FIFO disposal ordering,
# applies stock split adjustments (2:1 → double shares, halve cost basis),
# detects IRS wash sales (buy within 30 days of a loss sale, with
# proportional disallowance), classifies gains by holding period using
# the donor's acquisition date for gifted lots, and outputs a balanced
# hledger journal.
echo "=== Step 3: Building journal from CSV ==="
python3 /solution/build_journal.py
echo ""

# Step 4: Validate the journal parses and balances
echo "=== Step 4: Validating journal integrity ==="
hledger -f /app/portfolio.journal check && echo "Journal check: PASS"
echo ""

# Step 5: Verify lot positions after all transactions
echo "=== Step 5: Final lot positions ==="
hledger -f /app/portfolio.journal bal assets:broker -N --flat
echo ""

# Step 6: Verify capital gains classification
echo "=== Step 6: Realized gains by holding period ==="
hledger -f /app/portfolio.journal bal revenues:gains -N --flat
echo ""

# Step 7: Verify cash balance
echo "=== Step 7: Cash balance ==="
hledger -f /app/portfolio.journal bal assets:broker:cash -N
echo ""

# Step 8: Verify dividends
echo "=== Step 8: Dividend income ==="
hledger -f /app/portfolio.journal bal revenues:dividends -N
echo ""

# Step 9: Verify stock split equity adjustments
echo "=== Step 9: Equity adjustments from stock split ==="
hledger -f /app/portfolio.journal bal equity:adjustments -N -E
