Build an executable at `/app/feed_engine` that reconstructs Nasdaq limit order books from PCAP network capture files containing ITCH 5.0 market data delivered via MoldUDP64 over UDP.

**Usage**: `/app/feed_engine <captures_dir> <queries_file>`

Read all `.pcap` files from `<captures_dir>`. Each file is a standard libpcap capture (little-endian magic `0xa1b2c3d4`, Ethernet link layer). Captures contain mixed network traffic; extract only IPv4/UDP packets with destination port 26400 — each such UDP payload is one MoldUDP64 downstream packet. Ignore all non-IPv4, non-UDP, and wrong-port traffic. Protocol specifications are at `/app/spec/itch_5.0_specification.txt` and `/app/spec/moldudp64_specification.txt`. `tshark` is available in the environment. When multiple files are present, merge all extracted ITCH messages by timestamp before processing.

**Order Book**: Maintain per-symbol books from Add Order (with and without MPID attribution), Cancel, Delete, Replace, and Execution messages. Replace kills the original order and creates a new one inheriting side, symbol, and MPID. Cancels reduce shares cumulatively; orders reaching zero shares are removed. Executions reduce remaining shares similarly.

**VWAP and Volume**: Per-symbol from printable executions only. Order Executed messages are always printable at the order's current price. Order Executed With Price is printable only when its printable indicator is `Y`, at the stated execution price. Non-cross Trade and Cross Trade messages are always included. Broken Trade reverses a prior execution by match number. Omit zero-volume symbols.

**Output**: JSON to stdout with keys `vwap`, `volume`, `bbo`, and `diagnostics`:
```json
{
  "vwap": {"AAPL": 150.58},
  "volume": {"AAPL": 600},
  "bbo": [{"symbol":"AAPL","timestamp_ns":34201000000000,
    "bid_price":150.0,"bid_size":1000,"ask_price":150.5,"ask_size":300}],
  "diagnostics": {
    "sessions": ["SESS001"],
    "total_messages": 42,
    "gaps": [{"session":"SESS001","expected_seq":14,"actual_seq":16}],
    "heartbeat_count": 2
  }
}
```

BBO reflects book state after all messages with timestamp <= query timestamp. Aggregate shares at the best price level per side. Missing side: `null` price, `0` size. VWAP = total_notional / total_volume.

**Diagnostics**: `sessions` — unique session IDs (trimmed of trailing spaces), sorted alphabetically. `total_messages` — ITCH messages successfully extracted across all captures. `gaps` — sequence discontinuities within sessions (expected next vs actual sequence number received), sorted by session then expected_seq. `heartbeat_count` — total heartbeat packets observed across all captures. Unknown order references must be silently ignored.

**Queries**: `{"bbo_queries": [{"symbol": "AAPL", "timestamp_ns": 34201000000000}]}`
