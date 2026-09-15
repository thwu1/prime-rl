#!/usr/bin/env python3
"""
Solve the hledger portfolio journal by fixing all errors.


Fixes:
1. SELL 130 ACME on 2024-05-15: wrong FIFO (used lots 2024-01-15 + 2024-02-20
   instead of gift lot 2021-03-15 + 2024-01-15). Gains were $1462.50, should be $2597.50.
2. SELL 50 ACME on 2024-10-15: posted to parent account without lot breakdown.
   Should use specific identification from lot 2024-02-20_$52.00 with $500.00 gain.
3. SELL 80 WIDG on 2024-11-01: posted to parent account without lot breakdown.
   FIFO: 20 from 2024-03-10_$18.75 + 60 from 2024-06-01_$21.50, gain $455.00.
4. Dividend on 2024-08-10: posted to expenses:dividends, should be revenues:dividends.
"""

import re


def fix_journal(path):
    with open(path, "r") as f:
        content = f.read()

    # Fix 1: Replace the broken SELL 130 ACME transaction
    old_sell1 = """2024-05-15 Sell 130 ACME @ $58.25
    assets:broker:acme:2024-01-15_$45.50   -100 ACME @ $45.50
    assets:broker:acme:2024-02-20_$52.00   -30 ACME @ $52.00
    assets:broker:cash                     $7572.50
    revenues:gains                         $-1462.50"""

    new_sell1 = """2024-05-15 Sell 130 ACME @ $58.25  ; disposal:FIFO
    assets:broker:acme:2021-03-15_$22.00   -40 ACME @ $22.00
    assets:broker:acme:2024-01-15_$45.50   -90 ACME @ $45.50
    assets:broker:cash                     $7572.50
    revenues:gains                         $-2597.50"""

    content = content.replace(old_sell1, new_sell1)

    # Fix 2: Replace the incomplete SELL 50 ACME transaction
    old_sell3 = """2024-10-15 Sell 50 ACME @ $62.00  ; disposal:spec-id lot:2024-02-20_$52.00
    assets:broker:acme                     -50 ACME @ $62.00
    assets:broker:cash                     $3100.00"""

    new_sell3 = """2024-10-15 Sell 50 ACME @ $62.00  ; disposal:spec-id lot:2024-02-20_$52.00
    assets:broker:acme:2024-02-20_$52.00   -50 ACME @ $52.00
    assets:broker:cash                     $3100.00
    revenues:gains                         $-500.00"""

    content = content.replace(old_sell3, new_sell3)

    # Fix 3: Replace the incomplete SELL 80 WIDG transaction
    old_sell4 = """2024-11-01 Sell 80 WIDG @ $26.50
    assets:broker:widg                     -80 WIDG @ $26.50
    assets:broker:cash                     $2120.00"""

    new_sell4 = """2024-11-01 Sell 80 WIDG @ $26.50  ; disposal:FIFO
    assets:broker:widg:2024-03-10_$18.75   -20 WIDG @ $18.75
    assets:broker:widg:2024-06-01_$21.50   -60 WIDG @ $21.50
    assets:broker:cash                     $2120.00
    revenues:gains                         $-455.00"""

    content = content.replace(old_sell4, new_sell4)

    # Fix 4: Change expenses:dividends to revenues:dividends
    content = content.replace("expenses:dividends", "revenues:dividends")

    with open(path, "w") as f:
        f.write(content)


if __name__ == "__main__":
    fix_journal("/app/portfolio.journal")
