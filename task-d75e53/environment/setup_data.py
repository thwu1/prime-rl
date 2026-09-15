#!/usr/bin/env python3
"""Generate task data for BGP anomaly audit.
Creates SQLite database, XML topology, RPKI VRPs, and BGP policy config.
"""
import sqlite3
import json
import os

TIMESTAMP = '2024-01-15T08:00:00Z'

ROUTERS = [
    (1, 'R1', 65001, '1.1.1.1', 'tier1'),
    (2, 'R2', 65002, '2.2.2.2', 'tier1'),
    (3, 'R3', 65010, '3.3.3.3', 'transit'),
    (4, 'R4', 65020, '4.4.4.4', 'transit'),
    (5, 'R5', 65100, '5.5.5.5', 'stub'),
    (6, 'R6', 65200, '6.6.6.6', 'stub'),
]

PEERING_SESSIONS = [
    (1,  1, '172.16.12.1', '172.16.12.2', 65002, 'Established'),
    (2,  2, '172.16.12.2', '172.16.12.1', 65001, 'Established'),
    (3,  1, '172.16.13.1', '172.16.13.3', 65010, 'Established'),
    (4,  3, '172.16.13.3', '172.16.13.1', 65001, 'Established'),
    (5,  2, '172.16.24.2', '172.16.24.4', 65020, 'Established'),
    (6,  4, '172.16.24.4', '172.16.24.2', 65002, 'Established'),
    (7,  3, '172.16.34.3', '172.16.34.4', 65020, 'Established'),
    (8,  4, '172.16.34.4', '172.16.34.3', 65010, 'Established'),
    (9,  3, '172.16.35.3', '172.16.35.5', 65100, 'Established'),
    (10, 5, '172.16.35.5', '172.16.35.3', 65010, 'Established'),
    (11, 4, '172.16.46.4', '172.16.46.6', 65200, 'Established'),
    (12, 6, '172.16.46.6', '172.16.46.4', 65020, 'Established'),
]

AS_PATHS = [
    (1,  '65001'),
    (2,  '65002'),
    (3,  '65010'),
    (4,  '65020'),
    (5,  '65100'),
    (6,  '65200'),
    (7,  '65002 65020'),
    (8,  '65010 65100'),
    (9,  '65002 65020 65200'),
    (10, '65010 65001'),
    (11, '65020 65002'),
    (12, '65001 65010'),
    (13, '65001 65010 65100'),
    (14, '65020 65200'),
    (15, '65010 65020'),
    (16, '65020 65010'),
    (17, '65010 65020 65002'),
    (18, '65010 65020 65200'),
    (19, '65020 65010 65001'),
    (20, '65020 65010 65100'),
    (21, '65002 65001'),
    (22, '65001 65002'),
]

# (entry_id, router_id, prefix, prefix_length, next_hop, local_pref, med,
#  weight, origin_type, is_best, learned_from_ip, path_id, timestamp)
RIB_ENTRIES = [
    # R1 (AS 65001)
    (1,  1, '10.1.0.0',   16, '0.0.0.0',    100, 0, 32768, 'igp', 1, None,          None, TIMESTAMP),
    (2,  1, '10.2.0.0',   16, '172.16.12.2', 100, 0, 0, 'igp', 1, '172.16.12.2', 2,  TIMESTAMP),
    (3,  1, '10.10.0.0',  16, '172.16.13.3',  80, 0, 0, 'igp', 1, '172.16.13.3', 3,  TIMESTAMP),
    (4,  1, '10.10.0.0',  24, '172.16.13.3', 150, 0, 0, 'igp', 1, '172.16.13.3', 3,  TIMESTAMP),
    (5,  1, '10.20.0.0',  16, '172.16.12.2', 100, 0, 0, 'igp', 1, '172.16.12.2', 7,  TIMESTAMP),
    (6,  1, '10.100.0.0', 16, '172.16.13.3', 150, 0, 0, 'igp', 1, '172.16.13.3', 8,  TIMESTAMP),
    (7,  1, '10.200.0.0', 16, '172.16.12.2', 100, 0, 0, 'igp', 1, '172.16.12.2', 9,  TIMESTAMP),
    # R2 (AS 65002)
    (8,  2, '10.2.0.0',   16, '0.0.0.0',    100, 0, 32768, 'igp', 1, None,          None, TIMESTAMP),
    (9,  2, '10.1.0.0',   16, '172.16.12.1', 100, 0, 0, 'igp', 1, '172.16.12.1', 1,  TIMESTAMP),
    (10, 2, '10.10.0.0',  16, '172.16.12.1', 100, 0, 0, 'igp', 1, '172.16.12.1', 12, TIMESTAMP),
    (11, 2, '10.10.0.0',  24, '172.16.12.1', 100, 0, 0, 'igp', 1, '172.16.12.1', 12, TIMESTAMP),
    (12, 2, '10.20.0.0',  16, '172.16.24.4', 150, 0, 0, 'igp', 1, '172.16.24.4', 4,  TIMESTAMP),
    (13, 2, '10.100.0.0', 16, '172.16.12.1', 100, 0, 0, 'igp', 1, '172.16.12.1', 13, TIMESTAMP),
    (14, 2, '10.200.0.0', 16, '172.16.24.4', 150, 0, 0, 'igp', 1, '172.16.24.4', 14, TIMESTAMP),
    (15, 2, '10.100.0.0', 24, '172.16.24.4', 150, 0, 0, 'igp', 1, '172.16.24.4', 14, TIMESTAMP),
    # R3 (AS 65010)
    (16, 3, '10.10.0.0',  16, '0.0.0.0',    100, 0, 32768, 'igp', 1, None,          None, TIMESTAMP),
    (17, 3, '10.10.0.0',  24, '0.0.0.0',    100, 0, 32768, 'igp', 1, None,          None, TIMESTAMP),
    (18, 3, '10.1.0.0',   16, '172.16.13.1',  50, 0, 0, 'igp', 1, '172.16.13.1', 1,  TIMESTAMP),
    (19, 3, '10.2.0.0',   16, '172.16.34.4', 100, 0, 0, 'igp', 1, '172.16.34.4', 11, TIMESTAMP),
    (20, 3, '10.20.0.0',  16, '172.16.34.4', 100, 0, 0, 'igp', 1, '172.16.34.4', 4,  TIMESTAMP),
    (21, 3, '10.100.0.0', 16, '172.16.35.5', 150, 0, 0, 'igp', 1, '172.16.35.5', 5,  TIMESTAMP),
    (22, 3, '10.200.0.0', 16, '172.16.34.4', 100, 0, 0, 'igp', 1, '172.16.34.4', 14, TIMESTAMP),
    # R4 (AS 65020)
    (23, 4, '10.20.0.0',  16, '0.0.0.0',    100, 0, 32768, 'igp', 1, None,          None, TIMESTAMP),
    (24, 4, '10.2.0.0',   16, '172.16.24.2',  50, 0, 0, 'igp', 1, '172.16.24.2', 2,  TIMESTAMP),
    (25, 4, '10.1.0.0',   16, '172.16.34.3', 100, 0, 0, 'igp', 1, '172.16.34.3', 10, TIMESTAMP),
    (26, 4, '10.10.0.0',  16, '172.16.34.3', 100, 0, 0, 'igp', 1, '172.16.34.3', 3,  TIMESTAMP),
    (27, 4, '10.10.0.0',  24, '172.16.34.3', 100, 0, 0, 'igp', 1, '172.16.34.3', 3,  TIMESTAMP),
    (28, 4, '10.100.0.0', 16, '172.16.34.3', 100, 0, 0, 'igp', 1, '172.16.34.3', 8,  TIMESTAMP),
    (29, 4, '10.200.0.0', 16, '172.16.46.6', 150, 0, 0, 'igp', 1, '172.16.46.6', 6,  TIMESTAMP),
    (30, 4, '10.100.0.0', 24, '172.16.46.6', 150, 0, 0, 'igp', 1, '172.16.46.6', 6,  TIMESTAMP),
    # R5 (AS 65100)
    (31, 5, '10.100.0.0', 16, '0.0.0.0',    100, 0, 32768, 'igp', 1, None,          None, TIMESTAMP),
    (32, 5, '10.1.0.0',   16, '172.16.35.3',  50, 0, 0, 'igp', 1, '172.16.35.3', 10, TIMESTAMP),
    (33, 5, '10.2.0.0',   16, '172.16.35.3',  50, 0, 0, 'igp', 1, '172.16.35.3', 17, TIMESTAMP),
    (34, 5, '10.10.0.0',  16, '172.16.35.3',  50, 0, 0, 'igp', 1, '172.16.35.3', 3,  TIMESTAMP),
    (35, 5, '10.10.0.0',  24, '172.16.35.3',  50, 0, 0, 'igp', 1, '172.16.35.3', 3,  TIMESTAMP),
    (36, 5, '10.20.0.0',  16, '172.16.35.3',  50, 0, 0, 'igp', 1, '172.16.35.3', 15, TIMESTAMP),
    (37, 5, '10.200.0.0', 16, '172.16.35.3',  50, 0, 0, 'igp', 1, '172.16.35.3', 18, TIMESTAMP),
    # R6 (AS 65200)
    (38, 6, '10.200.0.0', 16, '0.0.0.0',    100, 0, 32768, 'igp', 1, None,          None, TIMESTAMP),
    (39, 6, '10.100.0.0', 24, '0.0.0.0',    100, 0, 32768, 'igp', 1, None,          None, TIMESTAMP),
    (40, 6, '10.1.0.0',   16, '172.16.46.4',  50, 0, 0, 'igp', 1, '172.16.46.4', 19, TIMESTAMP),
    (41, 6, '10.2.0.0',   16, '172.16.46.4',  50, 0, 0, 'igp', 1, '172.16.46.4', 11, TIMESTAMP),
    (42, 6, '10.10.0.0',  16, '172.16.46.4',  50, 0, 0, 'igp', 1, '172.16.46.4', 16, TIMESTAMP),
    (43, 6, '10.10.0.0',  24, '172.16.46.4',  50, 0, 0, 'igp', 1, '172.16.46.4', 16, TIMESTAMP),
    (44, 6, '10.20.0.0',  16, '172.16.46.4',  50, 0, 0, 'igp', 1, '172.16.46.4', 4,  TIMESTAMP),
    (45, 6, '10.100.0.0', 16, '172.16.46.4',  50, 0, 0, 'igp', 1, '172.16.46.4', 20, TIMESTAMP),
    # Non-best alternate paths (noise)
    (46, 3, '10.2.0.0',   16, '172.16.13.1',  50, 10, 0, 'igp', 0, '172.16.13.1', 22, TIMESTAMP),
    (47, 4, '10.1.0.0',   16, '172.16.24.2',  50, 10, 0, 'igp', 0, '172.16.24.2', 21, TIMESTAMP),
]

COMMUNITIES = [
    (3,  '65001:100'),
    (4,  '65001:100'),
    (6,  '65001:100'),
    (6,  '65100:10'),
    (12, '65002:100'),
    (14, '65002:100'),
    (15, '65002:100'),
    (21, '65010:100'),
    (29, '65020:100'),
    (30, '65020:100'),
]

TOPOLOGY_XML = '''\
<?xml version="1.0" encoding="UTF-8"?>
<network-topology xmlns="urn:example:bgp-topology"
                  xmlns:bgp="urn:example:bgp-policy">
  <topology-id>isp-network-2024</topology-id>
  <last-updated>2024-01-15T08:00:00Z</last-updated>
  <autonomous-systems>
    <as>
      <asn>65001</asn>
      <name>TierOne-Alpha</name>
      <tier>tier1</tier>
      <router-id>1.1.1.1</router-id>
      <hostname>R1</hostname>
    </as>
    <as>
      <asn>65002</asn>
      <name>TierOne-Beta</name>
      <tier>tier1</tier>
      <router-id>2.2.2.2</router-id>
      <hostname>R2</hostname>
    </as>
    <as>
      <asn>65010</asn>
      <name>Transit-Gamma</name>
      <tier>transit</tier>
      <router-id>3.3.3.3</router-id>
      <hostname>R3</hostname>
    </as>
    <as>
      <asn>65020</asn>
      <name>Transit-Delta</name>
      <tier>transit</tier>
      <router-id>4.4.4.4</router-id>
      <hostname>R4</hostname>
    </as>
    <as>
      <asn>65100</asn>
      <name>Customer-Epsilon</name>
      <tier>stub</tier>
      <router-id>5.5.5.5</router-id>
      <hostname>R5</hostname>
    </as>
    <as>
      <asn>65200</asn>
      <name>Customer-Zeta</name>
      <tier>stub</tier>
      <router-id>6.6.6.6</router-id>
      <hostname>R6</hostname>
    </as>
  </autonomous-systems>
  <interconnections>
    <link id="link-1">
      <local-as>65001</local-as>
      <remote-as>65002</remote-as>
      <bgp:relationship type="peer"/>
      <addresses>
        <local>172.16.12.1</local>
        <remote>172.16.12.2</remote>
      </addresses>
    </link>
    <link id="link-2">
      <local-as>65001</local-as>
      <remote-as>65010</remote-as>
      <bgp:relationship type="customer-provider">
        <bgp:provider>65001</bgp:provider>
        <bgp:customer>65010</bgp:customer>
      </bgp:relationship>
      <addresses>
        <local>172.16.13.1</local>
        <remote>172.16.13.3</remote>
      </addresses>
    </link>
    <link id="link-3">
      <local-as>65002</local-as>
      <remote-as>65020</remote-as>
      <bgp:relationship type="customer-provider">
        <bgp:provider>65002</bgp:provider>
        <bgp:customer>65020</bgp:customer>
      </bgp:relationship>
      <addresses>
        <local>172.16.24.2</local>
        <remote>172.16.24.4</remote>
      </addresses>
    </link>
    <link id="link-4">
      <local-as>65010</local-as>
      <remote-as>65020</remote-as>
      <bgp:relationship type="peer"/>
      <addresses>
        <local>172.16.34.3</local>
        <remote>172.16.34.4</remote>
      </addresses>
    </link>
    <link id="link-5">
      <local-as>65010</local-as>
      <remote-as>65100</remote-as>
      <bgp:relationship type="customer-provider">
        <bgp:provider>65010</bgp:provider>
        <bgp:customer>65100</bgp:customer>
      </bgp:relationship>
      <addresses>
        <local>172.16.35.3</local>
        <remote>172.16.35.5</remote>
      </addresses>
    </link>
    <link id="link-6">
      <local-as>65020</local-as>
      <remote-as>65200</remote-as>
      <bgp:relationship type="customer-provider">
        <bgp:provider>65020</bgp:provider>
        <bgp:customer>65200</bgp:customer>
      </bgp:relationship>
      <addresses>
        <local>172.16.46.4</local>
        <remote>172.16.46.6</remote>
      </addresses>
    </link>
  </interconnections>
</network-topology>
'''

RPKI_VRPS = {
    "metadata": {
        "generated": "2024-01-15T07:55:00Z",
        "source": "rpki-validator",
        "serialNumber": 48291,
        "trust-anchors": ["afrinic", "apnic", "arin", "lacnic", "ripe"]
    },
    "roas": [
        {"asn": "AS65001", "prefix": "10.1.0.0/16",   "maxLength": 16, "ta": "arin"},
        {"asn": "AS65002", "prefix": "10.2.0.0/16",   "maxLength": 16, "ta": "arin"},
        {"asn": "AS65010", "prefix": "10.10.0.0/16",  "maxLength": 16, "ta": "arin"},
        {"asn": "AS65020", "prefix": "10.20.0.0/16",  "maxLength": 16, "ta": "arin"},
        {"asn": "AS65100", "prefix": "10.100.0.0/16", "maxLength": 24, "ta": "arin"},
        {"asn": "AS65200", "prefix": "10.200.0.0/16", "maxLength": 16, "ta": "arin"}
    ]
}

BGP_POLICY_CONF = '''\
!
! BGP Routing Policy Configuration
! Network: 6-AS Tiered ISP Topology
! Last modified: 2024-01-14
!
! ===================================================================
! Router R1 (AS 65001 - Tier-1)
! ===================================================================
!
router bgp 65001
 bgp router-id 1.1.1.1
 bgp log-neighbor-changes
 !
 ! Peer: TierOne-Beta
 neighbor 172.16.12.2 remote-as 65002
 neighbor 172.16.12.2 description eBGP peer with TierOne-Beta
 neighbor 172.16.12.2 route-map PEER-INBOUND in
 neighbor 172.16.12.2 route-map PEER-OUTBOUND out
 neighbor 172.16.12.2 send-community both
 neighbor 172.16.12.2 soft-reconfiguration inbound
 !
 ! Customer: Transit-Gamma
 neighbor 172.16.13.3 remote-as 65010
 neighbor 172.16.13.3 description eBGP customer Transit-Gamma
 neighbor 172.16.13.3 route-map CUSTOMER-INBOUND in
 neighbor 172.16.13.3 route-map CUSTOMER-OUTBOUND out
 neighbor 172.16.13.3 send-community both
 neighbor 172.16.13.3 default-originate
 neighbor 172.16.13.3 soft-reconfiguration inbound
 neighbor 172.16.13.3 prefix-list CUSTOMER-65010-IN in
!
! ===================================================================
! Router R2 (AS 65002 - Tier-1)
! ===================================================================
!
router bgp 65002
 bgp router-id 2.2.2.2
 bgp log-neighbor-changes
 !
 ! Peer: TierOne-Alpha
 neighbor 172.16.12.1 remote-as 65001
 neighbor 172.16.12.1 description eBGP peer with TierOne-Alpha
 neighbor 172.16.12.1 route-map PEER-INBOUND in
 neighbor 172.16.12.1 route-map PEER-OUTBOUND out
 neighbor 172.16.12.1 send-community both
 neighbor 172.16.12.1 soft-reconfiguration inbound
 !
 ! Customer: Transit-Delta
 neighbor 172.16.24.4 remote-as 65020
 neighbor 172.16.24.4 description eBGP customer Transit-Delta
 neighbor 172.16.24.4 route-map CUSTOMER-INBOUND in
 neighbor 172.16.24.4 route-map CUSTOMER-OUTBOUND out
 neighbor 172.16.24.4 send-community both
 neighbor 172.16.24.4 default-originate
 neighbor 172.16.24.4 soft-reconfiguration inbound
 neighbor 172.16.24.4 prefix-list CUSTOMER-65020-IN in
!
! ===================================================================
! Router R3 (AS 65010 - Transit)
! ===================================================================
!
router bgp 65010
 bgp router-id 3.3.3.3
 bgp log-neighbor-changes
 !
 ! Provider: TierOne-Alpha
 neighbor 172.16.13.1 remote-as 65001
 neighbor 172.16.13.1 description eBGP provider TierOne-Alpha
 neighbor 172.16.13.1 route-map PROVIDER-INBOUND in
 neighbor 172.16.13.1 route-map PROVIDER-OUTBOUND out
 neighbor 172.16.13.1 send-community both
 neighbor 172.16.13.1 soft-reconfiguration inbound
 !
 ! Peer: Transit-Delta
 neighbor 172.16.34.4 remote-as 65020
 neighbor 172.16.34.4 description eBGP peer with Transit-Delta
 neighbor 172.16.34.4 route-map PEER-INBOUND in
 neighbor 172.16.34.4 route-map PEER-OUTBOUND out
 neighbor 172.16.34.4 send-community both
 neighbor 172.16.34.4 soft-reconfiguration inbound
 !
 ! Customer: Customer-Epsilon
 neighbor 172.16.35.5 remote-as 65100
 neighbor 172.16.35.5 description eBGP customer Customer-Epsilon
 neighbor 172.16.35.5 route-map CUSTOMER-INBOUND in
 neighbor 172.16.35.5 route-map CUSTOMER-OUTBOUND out
 neighbor 172.16.35.5 send-community both
 neighbor 172.16.35.5 default-originate
 neighbor 172.16.35.5 soft-reconfiguration inbound
 neighbor 172.16.35.5 prefix-list CUSTOMER-65100-IN in
!
! ===================================================================
! Router R4 (AS 65020 - Transit)
! ===================================================================
!
router bgp 65020
 bgp router-id 4.4.4.4
 bgp log-neighbor-changes
 !
 ! Provider: TierOne-Beta
 neighbor 172.16.24.2 remote-as 65002
 neighbor 172.16.24.2 description eBGP provider TierOne-Beta
 neighbor 172.16.24.2 route-map PROVIDER-INBOUND in
 neighbor 172.16.24.2 route-map PROVIDER-OUTBOUND out
 neighbor 172.16.24.2 send-community both
 neighbor 172.16.24.2 soft-reconfiguration inbound
 !
 ! Peer: Transit-Gamma
 neighbor 172.16.34.3 remote-as 65010
 neighbor 172.16.34.3 description eBGP peer with Transit-Gamma
 neighbor 172.16.34.3 route-map PEER-INBOUND in
 neighbor 172.16.34.3 route-map PEER-OUTBOUND out
 neighbor 172.16.34.3 send-community both
 neighbor 172.16.34.3 soft-reconfiguration inbound
 !
 ! Customer: Customer-Zeta
 neighbor 172.16.46.6 remote-as 65200
 neighbor 172.16.46.6 description eBGP customer Customer-Zeta
 neighbor 172.16.46.6 route-map CUSTOMER-INBOUND in
 neighbor 172.16.46.6 route-map CUSTOMER-OUTBOUND out
 neighbor 172.16.46.6 send-community both
 neighbor 172.16.46.6 default-originate
 neighbor 172.16.46.6 soft-reconfiguration inbound
 neighbor 172.16.46.6 prefix-list CUSTOMER-65200-IN in
!
! ===================================================================
! Router R5 (AS 65100 - Stub)
! ===================================================================
!
router bgp 65100
 bgp router-id 5.5.5.5
 bgp log-neighbor-changes
 !
 ! Provider: Transit-Gamma
 neighbor 172.16.35.3 remote-as 65010
 neighbor 172.16.35.3 description eBGP provider Transit-Gamma
 neighbor 172.16.35.3 route-map PROVIDER-INBOUND in
 neighbor 172.16.35.3 route-map PROVIDER-OUTBOUND out
 neighbor 172.16.35.3 send-community both
 neighbor 172.16.35.3 soft-reconfiguration inbound
!
! ===================================================================
! Router R6 (AS 65200 - Stub)
! ===================================================================
!
router bgp 65200
 bgp router-id 6.6.6.6
 bgp log-neighbor-changes
 !
 ! Provider: Transit-Delta
 neighbor 172.16.46.4 remote-as 65020
 neighbor 172.16.46.4 description eBGP provider Transit-Delta
 neighbor 172.16.46.4 route-map PROVIDER-INBOUND in
 neighbor 172.16.46.4 route-map PROVIDER-OUTBOUND out
 neighbor 172.16.46.4 send-community both
 neighbor 172.16.46.4 soft-reconfiguration inbound
!
! ===================================================================
! Route-map Definitions (Global)
! ===================================================================
!
route-map CUSTOMER-INBOUND permit 10
 set local-preference 150
 set community additive
!
route-map PEER-INBOUND permit 10
 set local-preference 100
 set community additive
!
route-map PROVIDER-INBOUND permit 10
 set local-preference 50
 set community additive
!
route-map CUSTOMER-OUTBOUND permit 10
!
route-map PEER-OUTBOUND permit 10
!
route-map PROVIDER-OUTBOUND permit 10
!
! ===================================================================
! Prefix Lists
! ===================================================================
!
ip prefix-list CUSTOMER-65010-IN permit 10.10.0.0/16 le 24
ip prefix-list CUSTOMER-65020-IN permit 10.20.0.0/16 le 24
ip prefix-list CUSTOMER-65100-IN permit 10.100.0.0/16 le 24
ip prefix-list CUSTOMER-65200-IN permit 10.200.0.0/16 le 24
!
end
'''


def create_directories():
    os.makedirs('/data/rpki', exist_ok=True)
    os.makedirs('/data/configs', exist_ok=True)
    os.makedirs('/app', exist_ok=True)


def create_database():
    conn = sqlite3.connect('/data/bgp_monitor.db')
    c = conn.cursor()

    c.executescript('''
        CREATE TABLE routers (
            router_id   INTEGER PRIMARY KEY,
            hostname    TEXT NOT NULL,
            asn         INTEGER NOT NULL,
            loopback_ip TEXT NOT NULL,
            tier        TEXT NOT NULL
        );

        CREATE TABLE peering_sessions (
            session_id      INTEGER PRIMARY KEY,
            local_router_id INTEGER NOT NULL,
            local_ip        TEXT NOT NULL,
            remote_ip       TEXT NOT NULL,
            remote_asn      INTEGER NOT NULL,
            state           TEXT NOT NULL DEFAULT 'Established',
            FOREIGN KEY (local_router_id) REFERENCES routers(router_id)
        );

        CREATE TABLE as_path_segments (
            path_id INTEGER PRIMARY KEY,
            segment TEXT NOT NULL
        );

        CREATE TABLE rib_entries (
            entry_id        INTEGER PRIMARY KEY,
            router_id       INTEGER NOT NULL,
            prefix          TEXT NOT NULL,
            prefix_length   INTEGER NOT NULL,
            next_hop        TEXT,
            local_pref      INTEGER NOT NULL DEFAULT 100,
            med             INTEGER NOT NULL DEFAULT 0,
            weight          INTEGER NOT NULL DEFAULT 0,
            origin_type     TEXT NOT NULL DEFAULT 'igp',
            is_best         INTEGER NOT NULL DEFAULT 1,
            learned_from_ip TEXT,
            path_id         INTEGER,
            timestamp       TEXT NOT NULL,
            FOREIGN KEY (router_id) REFERENCES routers(router_id),
            FOREIGN KEY (path_id) REFERENCES as_path_segments(path_id)
        );

        CREATE TABLE route_communities (
            entry_id  INTEGER NOT NULL,
            community TEXT NOT NULL,
            FOREIGN KEY (entry_id) REFERENCES rib_entries(entry_id)
        );

        CREATE INDEX idx_rib_router ON rib_entries(router_id);
        CREATE INDEX idx_rib_prefix ON rib_entries(prefix, prefix_length);
        CREATE INDEX idx_rib_best ON rib_entries(is_best);
        CREATE INDEX idx_peer_router ON peering_sessions(local_router_id);
    ''')

    c.executemany(
        'INSERT INTO routers VALUES (?,?,?,?,?)', ROUTERS)
    c.executemany(
        'INSERT INTO peering_sessions VALUES (?,?,?,?,?,?)', PEERING_SESSIONS)
    c.executemany(
        'INSERT INTO as_path_segments VALUES (?,?)', AS_PATHS)
    c.executemany(
        'INSERT INTO rib_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
        RIB_ENTRIES)
    c.executemany(
        'INSERT INTO route_communities VALUES (?,?)', COMMUNITIES)

    conn.commit()
    conn.close()


def create_topology_xml():
    with open('/data/network_topology.xml', 'w') as f:
        f.write(TOPOLOGY_XML)


def create_rpki_vrps():
    with open('/data/rpki/validated_roas.json', 'w') as f:
        json.dump(RPKI_VRPS, f, indent=2)


def create_bgp_policy():
    with open('/data/configs/bgp_policy.conf', 'w') as f:
        f.write(BGP_POLICY_CONF)


if __name__ == '__main__':
    create_directories()
    create_database()
    create_topology_xml()
    create_rpki_vrps()
    create_bgp_policy()
    print('Data generation complete.')
