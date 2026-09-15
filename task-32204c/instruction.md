A raw network capture at `/app/data/market_feed.pcap` contains UDP multicast traffic from a market data feed alongside unrelated network noise. The feed carries Market-by-Order (MBO) messages for multiple financial instruments across two redundant delivery channels.

A SQLite reference database at `/app/data/instruments.db` provides instrument metadata (symbols, tick sizes, price scaling factors) and channel configuration (ports, multicast groups).

The complete binary protocol specification -- including payload structure, record layout, message semantics, sequencing rules, and the required output schema -- is documented at `/app/docs/protocol_spec.md`.

Produce a SQLite database at `/app/output/analysis.db` that conforms to the output schema defined in the protocol specification. All four tables (`metrics`, `trades`, `gaps`, `latency`) must be present with every required column correctly populated for each instrument in the feed.