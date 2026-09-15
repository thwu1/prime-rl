Construct a complete hledger journal at `/app/portfolio.journal` from the 2024 brokerage transaction history at `/app/transactions.csv`. All APEX share counts and prices in the CSV after the June 1 stock split are post-split values.

The journal must:

- Track all investment lots using hledger's manual subaccount method with FIFO disposal by acquisition date
- Record the APEX 2:1 forward stock split (June 1) by transferring shares from pre-split lot subaccounts to new post-split subaccounts with doubled share counts and halved per-share cost basis; use `equity:adjustments` to balance the additional shares created by the split
- Apply IRS wash sale rules: when substantially identical securities are purchased within 30 calendar days after selling at a loss, the disallowed portion of the loss must be added to the replacement lot's per-share cost basis (if fewer replacement shares are purchased than were sold at a loss, only the proportional loss is disallowed)
- Classify each realized gain or loss as short-term (held <= 1 year) or long-term (held > 1 year); for gifted lots, the holding period begins on the donor's original acquisition date
- All transactions must balance and `hledger -f /app/portfolio.journal check` must succeed

## Account Naming Convention

- `assets:broker:cash`
- `assets:broker:<ticker>:<acquisition-date>_$<per-share-cost>` (e.g., `assets:broker:apex:2024-01-15_$25.00`). Use the lot's original acquisition date (donor's date for gifts). The per-share cost must reflect the current cost basis including any stock split adjustments and wash sale adjustments.
- `revenues:gains:short-term` and `revenues:gains:long-term`
- `revenues:dividends`
- `revenues:gifts`
- `equity:opening`
- `equity:adjustments`