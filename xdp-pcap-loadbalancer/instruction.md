`/app/lb_processor.py` contains a skeleton with pcap read/write helpers. The `process_packets()` function raises `NotImplementedError`. Implement a network load balancer packet processor that reads `/app/input.pcap` and `/app/config.json`, producing `/app/output.pcap` and `/app/stats.json`. Only the Python 3 standard library may be used. Use `tshark` to inspect the input traffic.

## Configuration (`/app/config.json`)

- `vip`: Virtual IP that clients target
- `lb_ip`: Source IP the load balancer uses in forwarded packets
- `lb_mac`: Load balancer MAC address
- `backends`: Array of `{ip, mac, weight}` backend servers

## Required Behavior

**TCP/UDP destined for VIP** — Forward to a weighted backend. Packets belonging to the same flow must always reach the same backend. Rewrite L2 and L3 source/destination addresses so the packet appears to originate from the load balancer and is addressed to the chosen backend. All protocol checksums in the rewritten packet must be valid.

**ICMP echo request targeting VIP** — Respond on behalf of the VIP with a properly formed echo reply.

**ARP request for VIP** — Respond on behalf of the VIP.

**802.1Q (VLAN) frames** — Tags must be preserved through all processing.

**Non-IPv4/non-ARP traffic** (e.g. IPv6) — Pass through byte-for-byte unchanged.

**Malformed packets** (shorter than a valid Ethernet header) — Drop silently.

## Required Output: `/app/stats.json`

```json
{
  "summary": {"total_input":0,"total_output":0,"dropped":0,"load_balanced":0,"icmp_replies":0,"arp_replies":0,"passthrough":0},
  "flows": [{"src_ip":"...","dst_ip":"...","src_port":0,"dst_port":0,"protocol":"TCP","packet_count":0,"backend_ip":"..."}],
  "backends": [{"ip":"...","packet_count":0,"byte_count":0}]
}
```

Counts must be self-consistent: `total_output = load_balanced + icmp_replies + arp_replies + passthrough`, `total_input = total_output + dropped`, sum of backend `packet_count` = `load_balanced`, sum of flow `packet_count` = `load_balanced`.