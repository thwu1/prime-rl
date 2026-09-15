Complete the seven stubbed operation functions in `/app/pkt_engine.c`.

The program is a userspace Ethernet packet transformation engine. It reads hex-encoded Ethernet frames from stdin (one per line), applies a configurable pipeline of operations specified via command-line arguments, and writes transformed frames as hex to stdout. Any packet that fails an operation or matches a filter is silently dropped.

The skeleton provides: packed header structs for Ethernet, VLAN, IPv4, IPv6, and ICMP; hex I/O routines; command-line argument parsing and pipeline dispatch; an RFC 1071 one's complement partial-sum helper (`csum_partial`); and a VLAN-aware L3 locator (`find_l3`) that skips 802.1Q/802.1ad tags to find the network-layer header offset. Study these thoroughly before implementing.

The seven operations to implement are `vlan-pop`, `vlan-push`, `echo-reply`, `forward`, `filter`, `tag`, and `untag`. Each function's contract — its expected behavior, parameters, and return semantics — is documented in the source comments above its stub. All operations must correctly handle VLAN-tagged frames, including nested Q-in-Q (802.1ad wrapping 802.1Q).

Build with `make` in `/app/`.