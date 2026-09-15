# Network Requirements Specification

## Overview

This OpenWrt router manages a small office network segmented into four VLANs, with two WireGuard VPN tunnels for site-to-site connectivity and guest traffic isolation.

## 1. Network Segmentation (VLANs on bridge br-lan)

The router uses a single bridge `br-lan` with VLAN filtering enabled (DSA). Physical ports are assigned to VLANs as untagged access ports with PVID:

| VLAN | Name       | Ports     | Subnet         | Gateway    |
|------|------------|-----------|----------------|------------|
| 10   | Management | lan1,lan2 | 10.0.10.0/24   | 10.0.10.1  |
| 20   | Corporate  | lan3,lan4 | 10.0.20.0/24   | 10.0.20.1  |
| 30   | IoT        | lan5      | 10.0.30.0/24   | 10.0.30.1  |
| 40   | Guest      | wireless  | 10.0.40.0/24   | 10.0.40.1  |

The Management interface uses `br-lan.10`, Corporate uses `br-lan.20`, IoT uses `br-lan.30`. Guest uses a separate `br-guest` bridge (wireless-only, no physical ports).

## 2. WireGuard VPN Tunnels

### vpn_hq (Site-to-Site to HQ)
- Purpose: Connect to headquarters network (172.16.0.0/12)
- Interface name: vpn_hq
- Local address: 10.0.99.2/24
- Endpoint: vpn.hq.example.com:51820
- AllowedIPs: Only HQ network range (172.16.0.0/12)
- **Important**: The HQ tunnel must NOT capture all traffic (0.0.0.0/0). It is only for reaching HQ internal resources. Setting AllowedIPs to 0.0.0.0/0 would create a routing conflict with the commercial VPN and break internet access for all VLANs.

### vpn_ext (Commercial VPN for Guest)
- Purpose: Route all guest traffic through a commercial VPN for privacy
- Interface name: vpn_ext
- Local address: 10.8.0.2/24
- Endpoint: vpn.provider.example.com:51821
- AllowedIPs: 0.0.0.0/0 (all traffic routed through this tunnel)

## 3. Firewall Zones

Each zone must have the correct network interface(s) assigned via `list network` entries. A zone without any network assignment is effectively disconnected.

| Zone     | Networks | Input  | Output | Forward | Masquerade |
|----------|----------|--------|--------|---------|------------|
| mgmt     | mgmt     | ACCEPT | ACCEPT | REJECT  | No         |
| corp     | corp     | ACCEPT | ACCEPT | REJECT  | No         |
| iot      | iot      | DROP   | ACCEPT | REJECT  | No         |
| guest    | guest    | REJECT | ACCEPT | REJECT  | No         |
| wan      | wan,wan6 | REJECT | ACCEPT | REJECT  | Yes        |
| vpn_hq   | vpn_hq   | ACCEPT | ACCEPT | REJECT  | No         |
| vpn_ext  | vpn_ext  | REJECT | ACCEPT | REJECT  | Yes        |

## 4. Forwarding Rules (zone-to-zone traffic)

| Source → Dest    | Policy | Purpose                               |
|------------------|--------|---------------------------------------|
| mgmt → wan       | ACCEPT | Management internet access            |
| mgmt → vpn_hq   | ACCEPT | Management can reach HQ               |
| mgmt → iot       | ACCEPT | Management can manage IoT devices     |
| corp → wan       | ACCEPT | Corporate internet access             |
| corp → vpn_hq   | ACCEPT | Corporate can reach HQ resources      |
| iot → wan        | ACCEPT | IoT internet (restricted by rules)    |
| guest → vpn_ext | ACCEPT | Guest traffic routed through VPN      |

All other zone-to-zone traffic is denied by the default forward policy (REJECT) on each zone.

## 5. Policy-Based Routing

| Source Network  | Destination     | Table | Via     | Priority |
|-----------------|-----------------|-------|---------|----------|
| 10.0.20.0/24    | 172.16.0.0/12   | 100   | vpn_hq  | 100      |
| 10.0.40.0/24    | all (default)   | 200   | vpn_ext | 200      |

- Corporate users (10.0.20.0/24) reaching HQ networks (172.16.0.0/12) are routed through vpn_hq via routing table 100.
- **All** guest traffic (10.0.40.0/24) must be routed through vpn_ext (commercial VPN) via routing table 200. Without this rule, guest traffic would exit through the WAN directly, defeating the privacy VPN.

## 6. DHCP Pools

Each VLAN network requires a DHCP pool referencing the correct UCI interface name.

| Network    | Interface | Start | Limit | Lease Time |
|------------|-----------|-------|-------|------------|
| Management | mgmt      | 100   | 100   | 12h        |
| Corporate  | corp      | 100   | 100   | 12h        |
| IoT        | iot       | 100   | 50    | 24h        |
| Guest      | guest     | 100   | 150   | 2h         |

## 7. Special Firewall Rules

- **IoT Port Restriction**: IoT devices can only reach the internet on ports 80, 443 (TCP) and 123 (UDP/NTP). All other outbound IoT traffic to WAN is rejected.
- **Guest DNS Redirect**: All DNS traffic (port 53) from the **guest** network must be DNAT-redirected to the router itself. This prevents DNS leaks through the VPN tunnel by forcing all guest DNS queries to be resolved locally.
- **WAN Rate Limiting**: Incoming WAN TCP connections are rate-limited to 25/minute.
