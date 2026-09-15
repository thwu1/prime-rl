An event-sourced exchange matching engine at `/app/` exhibits incorrect behavior — fill quantities are wrong during multi-level matching, state diverges between live processing and snapshot-accelerated replay, and certain book operations lose numerical precision. The engine also lacks support for IOC, FOK, and iceberg order types, and the market data feed at `/app/market_data.py` is unimplemented. The exchange semantics reference is at `/app/SPEC.md`. Original (buggy) sources are preserved at `/opt/app-src/`.

Codebase:
- `/app/engine.py` — order book and matching logic
- `/app/models.py` — data models (Order, Trade, Side, OrderType)
- `/app/snapshot.py` — snapshot serialization/deserialization
- `/app/replay.py` — replay engine
- `/app/journal.py` — event journal (JSONL format)
- `/app/market_data.py` — market data feed (stub)
- `/app/SPEC.md` — exchange semantics reference

A production event log at `/app/production.jsonl` contains interleaved NEW_ORDER, CANCEL, and TRADE records from a prior trading session. Build a trade surveillance pipeline using `jq` for JSONL-to-CSV transformation and `sqlite3` for database analytics:

Create a SQLite database at `/app/surveillance/exchange.db` with tables `orders` (order_id, trader_id, side, price, quantity, timestamp), `trades` (trade_id, buy_order_id, sell_order_id, buyer_id, seller_id, price, quantity, timestamp), and `cancellations` (target_order_id, timestamp) populated from the production log. Execute surveillance queries to produce:

- `/app/surveillance/wash_pairs.csv` — trader pairs with 4 or more mutual trades (columns: `buyer_id,seller_id,trade_count`), sorted by trade_count descending, with header row
- `/app/surveillance/cancel_ratios.csv` — per-trader cancel ratios (columns: `trader_id,orders,cancels,ratio`), sorted by ratio descending then trader_id ascending, ratio rounded to 4 decimals, with header row
- `/app/surveillance/vwap.txt` — single line: volume-weighted average price across all trades, rounded to 4 decimal places

Fix all engine bugs and implement all missing features. Produce all surveillance outputs.