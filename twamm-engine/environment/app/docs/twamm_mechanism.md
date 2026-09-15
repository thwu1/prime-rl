# TWAMM — Time-Weighted Average Market Maker

## Concept

A TWAMM enables large token trades to execute smoothly over many blocks by
splitting each long-term order into infinitely many infinitely small *virtual
sub-orders* that trade against an embedded constant-product AMM (CPAMM).

The CPAMM maintains the invariant **x · y = k** (no trading fees). The TWAMM
does not add or remove liquidity — only the virtual sub-orders interact with
the pool.

## Long-term orders

Each order specifies:
- Which token to sell (`x` or `y`)
- A total amount to sell
- A start block and end block

An order sells at a constant rate: `total_sell_amount / (end_block - start_block)`
tokens per block.

## Order pools

Orders selling the same token during any given block interval are pooled. The
pool's aggregate received output is distributed to each contributing order in
proportion to its sell rate relative to the pool's total sell rate.

At any moment there are at most two order pools active: one selling X and one
selling Y. Either (or both) may be empty.

## Lazy evaluation & interval splitting

Because the virtual sub-orders are deterministic (they interact only with the
embedded AMM, not with external actors), their cumulative effect can be
computed analytically regardless of how many blocks have elapsed.

However, when the active set of orders changes (an order starts or expires),
the selling rates change, and a fresh calculation is needed. The simulator
must identify every such **boundary block** and compute each constant-rate
interval separately, carrying the AMM reserves forward.

## Output distribution

After computing the AMM's new reserves for an interval:

- **X that left the AMM** (i.e. went to Y-sellers) =
  `x_before + x_sold_in_interval − x_after`
- **Y that left the AMM** (i.e. went to X-sellers) =
  `y_before + y_sold_in_interval − y_after`

These amounts are split among orders proportionally by sell rate.

## Conservation laws

Two invariants must hold over the entire simulation:

1. **Product invariant**: `x_final · y_final = x_initial · y_initial`
2. **Token conservation** (per token):
   `initial_reserve + total_sold = final_reserve + total_received`
