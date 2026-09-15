# Order Book Analytics Requirements

## Tool Interface

Build `/app/reconstruct.py` to process XMBO binary files and compute order book analytics.

    Usage: python3 /app/reconstruct.py [input_file] [output_file]

- `input_file`: Path to an XMBO binary file (default: `/app/data/session.xmbo`)
- `output_file`: Path for JSON output (default: `/app/output/analytics.json`)

The output directory should be created automatically if it does not exist.

## Processing Rules

1. Parse the XMBO file header to determine record count, record size, etc.
2. Read all records and **sort by sequence number** (ascending) before processing.
3. Maintain a limit order book mapping order IDs to their current price, size, and side.
4. Process each record according to its action type (see format specification).
5. For **Trade** and **Fill** actions, accumulate volume and value for VWAP computation.
6. Track bid-ask spread after processing each message.
7. Detect iceberg reload patterns across Fill/Add pairs.
8. After all messages are processed, compute final book state metrics.
9. Write all analytics as a single JSON object to the output file.

## Required Output Fields

The JSON output must contain exactly these fields:

| Field              | Type         | Description                                              |
|--------------------|--------------|----------------------------------------------------------|
| `session_vwap`     | float        | Volume-weighted average price: sum(price * qty) / sum(qty) across all Trade and Fill events. Rounded to 6 decimal places. |
| `total_volume`     | int          | Total quantity traded: sum of the size field across all Trade ('T') and Fill ('F') events. |
| `trade_count`      | int          | Count of Trade ('T') and Fill ('F') events.              |
| `max_spread`       | float        | Maximum bid-ask spread observed: max(best_ask - best_bid) in price units, tracked after each message only when both bid and ask sides have at least one order. Rounded to 6 decimal places. |
| `iceberg_count`    | int          | Number of iceberg reloads detected (see definition below). |
| `final_best_bid`   | float / null | Best (highest) bid price after all messages processed. Rounded to 6 decimal places. `null` if no bid orders remain. |
| `final_best_ask`   | float / null | Best (lowest) ask price after all messages processed. Rounded to 6 decimal places. `null` if no ask orders remain. |
| `final_bid_size`   | int          | Total quantity across all orders at the best bid price level. 0 if no bids. |
| `final_ask_size`   | int          | Total quantity across all orders at the best ask price level. 0 if no asks. |
| `bid_depth_levels` | int          | Number of distinct price levels on the bid side.         |
| `ask_depth_levels` | int          | Number of distinct price levels on the ask side.         |
| `num_messages`     | int          | Total number of records processed.                       |

## Iceberg Reload Detection

An **iceberg reload** occurs when:

1. A **Fill** ('F') event occurs at price P on side S at timestamp T_fill.
2. A subsequent **Add** ('A') event occurs at the **same price P** and **same side S** at timestamp T_add.
3. The time difference T_add - T_fill is **at most 100 microseconds** (100,000 nanoseconds).

Each such (Fill, Add) pair counts as one iceberg reload. A single Fill can trigger at most one iceberg detection (matched to the first qualifying Add).
