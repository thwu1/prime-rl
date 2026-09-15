# Netfilter Packet Flow Simulator - Specification

## Overview

This document specifies a simplified model of the Linux netfilter packet processing
pipeline for inbound packets, focusing on the interaction between iptables chains and
the conntrack (connection tracking) subsystem.

## Chain Processing Order

Inbound packets traverse the following processing stages in strict order:

1. **raw/PREROUTING** - Earliest hook. Rules here execute before connection tracking.
2. **Conntrack Decision** - The connection tracking subsystem processes the packet
   (unless bypassed by NOTRACK). This is NOT a user-configurable chain but an
   internal kernel decision point between raw and mangle.
3. **mangle/PREROUTING** - Executes after conntrack. Packets that were dropped by
   conntrack never reach this chain.
4. **filter/INPUT** - Final chain for locally-destined packets. Determines whether
   the packet is accepted or dropped by the firewall.

A packet counter is maintained for each chain, incremented each time a packet enters
that chain.

## Rule Matching

Rules within a chain are evaluated sequentially (first to last). The first rule whose
match criteria are satisfied determines the action for that packet. If no rule matches,
the chain's default policy applies (ACCEPT for all chains in this model).

### Match Criteria

A rule's `match` field is a dictionary of field-value pairs. ALL specified fields must
match for the rule to apply. An empty match `{}` matches every packet.

Supported match fields:
- `proto` - Protocol string: `"tcp"` or `"udp"`
- `src_ip` - Source IP address (exact string match)
- `dst_ip` - Destination IP address (exact string match)
- `src_port` - Source port number (integer)
- `dst_port` - Destination port number (integer)

### Actions

- **ACCEPT** - Packet continues to the next processing stage.
- **DROP** - Packet is immediately discarded. No further chains process it.
- **NOTRACK** - (raw/PREROUTING only) Marks the packet to bypass conntrack entirely.
  The packet proceeds directly to mangle/PREROUTING without conntrack processing.

## Connection Tracking (conntrack)

The conntrack subsystem maintains a table of known network flows, subject to a
configurable maximum size (`conntrack_max`).

### Flow Identification

A flow is uniquely identified by its 5-tuple:
`(proto, src_ip, src_port, dst_ip, dst_port)`

Multiple packets with the same 5-tuple belong to the same flow.

### Conntrack Processing Logic

When a packet reaches the conntrack decision point (after raw/PREROUTING, before
mangle/PREROUTING):

1. If the packet was marked NOTRACK by a raw rule, conntrack is skipped entirely.
   The packet proceeds to mangle/PREROUTING.

2. Compute the packet's flow key (5-tuple).

3. If the flow key matches an existing **confirmed** entry in the conntrack table,
   the packet is associated with that flow and proceeds to mangle/PREROUTING.

4. If the flow key does NOT match any existing entry (new flow):
   a. If `len(conntrack_table) < conntrack_max`: a new entry is allocated and the
      packet proceeds to mangle/PREROUTING. The entry is initially **unconfirmed**.
   b. If `len(conntrack_table) >= conntrack_max`: the packet is **silently dropped**.
      It never reaches mangle/PREROUTING. This is a "conntrack drop" (CT_DROP).

### Flow Confirmation

A conntrack entry becomes **confirmed** only when the packet that created it
successfully completes its entire traversal through the network stack — that is,
the packet reaches filter/INPUT and receives an ACCEPT verdict.

If the packet is dropped by any chain after conntrack (e.g., by a DROP rule in
filter/INPUT), the unconfirmed entry is removed from the conntrack table. This
means:

- Packets that are DROPped by iptables rules do NOT leave permanent entries in
  the conntrack table.
- A conntrack table can have room for new flows even with a small `conntrack_max`
  if all new-flow packets are being DROPped (entries are created then immediately
  removed).

Entries are processed sequentially — each packet's conntrack entry is either
confirmed or removed before the next packet is processed.

## Input Format

Each scenario is a JSON file with this structure:

```json
{
  "conntrack_max": <integer>,
  "rules": {
    "raw_PREROUTING": [<rule>, ...],
    "mangle_PREROUTING": [<rule>, ...],
    "filter_INPUT": [<rule>, ...]
  },
  "packets": [<packet>, ...]
}
```

Each rule:
```json
{"match": {"field": "value", ...}, "action": "ACTION"}
```

Each packet:
```json
{
  "proto": "tcp"|"udp",
  "src_ip": "<ip_address>",
  "src_port": <integer>,
  "dst_ip": "<ip_address>",
  "dst_port": <integer>
}
```

## Output Format

For each scenario, produce a JSON file with:

```json
{
  "counters": {
    "raw_PREROUTING": <int>,
    "mangle_PREROUTING": <int>,
    "filter_INPUT": <int>
  },
  "conntrack_entries": <int>,
  "conntrack_drops": <int>,
  "verdicts": ["ACCEPT"|"DROP"|"CT_DROP", ...]
}
```

- `counters` - Number of packets that entered each chain.
- `conntrack_entries` - Number of confirmed entries remaining in the conntrack
  table after all packets are processed.
- `conntrack_drops` - Total number of packets silently dropped due to conntrack
  table overflow.
- `verdicts` - Per-packet final verdict list (same length as input packets):
  - `"ACCEPT"` - Packet was accepted by filter/INPUT.
  - `"DROP"` - Packet was dropped by an iptables rule (in filter/INPUT).
  - `"CT_DROP"` - Packet was dropped by conntrack due to table overflow.
