# Network Redesign Change Request CR-2024-047

## Objective

Redesign the office network from a single-WAN flat routing model to a multi-WAN architecture with per-VLAN VPN policy routing, comprehensive firewall zone restructuring, and security hardening.

## 1. Backup WAN Connection

An LTE modem is connected to eth1 providing a backup internet connection.

Connection parameters:
- IP address: 100.64.0.2/30 (carrier-grade NAT address space — the carrier performs upstream NAT)
- Gateway: 100.64.0.1
- DNS servers: 1.1.1.1, 8.8.8.8

This backup connection must be available as a failover path for all internal networks. Under normal operation, all traffic should prefer the primary WAN (eth0); the backup should only carry traffic when the primary path or a VLAN's designated VPN tunnel is unavailable.

Since this is a CGNAT connection, outgoing traffic through this interface requires address translation at the router.

## 2. WireGuard Site-to-Site VPN to HQ

Complete the existing vpn_hq interface by adding the HQ peer configuration:

- Peer public key: xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg=
- Endpoint: vpn.hq.example.com:51820
- Persistent keepalive: 25 seconds
- Route allowed IPs: yes

The HQ tunnel is exclusively for reaching the headquarters private network (172.16.0.0/12). The tunnel MUST NOT attract default-route traffic (0.0.0.0/0) — doing so would create a routing conflict with the commercial VPN and break internet access for other VLANs. Only traffic destined for the HQ range should traverse this tunnel.

The HQ network's routers have static routes back to our office subnets (10.0.10.0/24, 10.0.20.0/24, etc.), so traffic returning from HQ reaches us without address translation on the tunnel. The firewall zone for this tunnel should reflect that — no source address rewriting is needed.

## 3. Commercial VPN for Guest Privacy

Create a new WireGuard tunnel for routing guest internet traffic through a commercial VPN provider:

- Interface name: vpn_ext
- Private key: gN65BkIKy1eCE9pP1wdc8ROUgxU3ZdQbFmcqEIa7cFo=
- Address: 10.8.0.2/24
- Peer public key: HIgo9xNzJMWLKASShiTqIybxR0V1tB1YBjMBOAtiSw4=
- Peer endpoint: vpn.provider.example.com:51821
- Peer AllowedIPs: 0.0.0.0/0 (all traffic routed through tunnel)
- Persistent keepalive: 25 seconds

The commercial VPN provider expects all traffic to originate from the tunnel endpoint address (10.8.0.2). Traffic from internal subnets must be source-translated before entering the tunnel.

## 4. Per-VLAN Traffic Routing Policy

Design a policy routing architecture so that each VLAN's traffic takes the appropriate exit path:

**Corporate (10.0.20.0/24):**
Traffic destined for HQ (172.16.0.0/12) must be routed through vpn_hq using routing table 100. All other corporate traffic uses the default routing table (primary WAN).

**Guest (10.0.40.0/24):**
ALL guest traffic must be routed through vpn_ext using routing table 200. Guest traffic must NEVER exit through the primary WAN — the existing guest-to-WAN forwarding path must be eliminated. If the VPN tunnel is unavailable, guest traffic may fall back to the backup WAN only.

**Management (10.0.10.0/24):**
Internet via primary WAN with failover to backup WAN. Must also be able to reach HQ resources through vpn_hq and manage IoT devices directly.

**IoT (10.0.30.0/24):**
Internet via primary WAN with failover to backup WAN. Outbound access is restricted (see Section 6).

## 5. Firewall Zone Architecture

Each WAN connection and VPN tunnel requires its own firewall zone for independent access control. Design the zone model so that:

- Every zone has the correct network interface(s) bound via `list network` entries — a zone without network bindings is effectively disconnected
- Zones where the router performs source address translation have masquerade enabled
- Zones carrying traffic to destinations with return routes to our subnets do not need masquerade
- Zone-to-zone forwarding rules enforce the per-VLAN traffic policy from Section 4, including failover paths to the backup WAN for all internal segments
- Guest zone isolation is strictly enforced: no forwarding from guest to any internal zone (management, corporate, IoT) or to the HQ VPN

## 6. IoT Outbound Restrictions

IoT devices should only be permitted outbound WAN access to:
- HTTP and HTTPS (TCP ports 80 and 443) — for cloud services and firmware updates
- NTP (UDP port 123) — for time synchronization

All other outbound IoT traffic to the WAN must be rejected. Implement this as ordered firewall rules: allow the permitted ports first, then a catch-all reject.

## 7. DNS Security

All DNS queries (port 53, TCP and UDP) from the guest and IoT networks must be intercepted and redirected (DNAT) to the router. This prevents devices on these networks from using external DNS servers, which would bypass the VPN tunnel (DNS leak) or allow IoT devices to exfiltrate data via DNS tunneling.

## 8. IPv6 Configuration

Enable IPv6 Unique Local Addresses (ULA) with prefix fd12:3456:789a::/48 in the network globals.

Assign /64 IPv6 subnets (via ip6assign) to the management and corporate VLANs only. Do NOT assign IPv6 addressing to IoT or guest VLANs — IPv6 traffic from these segments could bypass the IPv4-only policy routing and VPN tunnels, creating a security gap.

## 9. WAN Ingress Hardening

Rate-limit incoming TCP connections on the primary WAN to 25 per minute to mitigate connection flood attacks.
