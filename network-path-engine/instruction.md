A security operations center detected anomalous alerts spanning multiple segments of a VLAN-segmented enterprise network. Packet captures were collected from four monitoring points during the incident window. The network topology, host registry, VLAN assignments, and security policies are documented.

Reconstruct the complete intrusion chain — from initial external reconnaissance through lateral movement, data access, exfiltration, and persistence — by correlating evidence across all four captures. Decode any covert communication channels discovered in the traffic.

Produce a forensic incident report at `/app/report.json`.

## Available Data

- `/app/captures/perimeter.pcap` — Internet edge router span port
- `/app/captures/dmz_switch.pcap` — DMZ segment (VLAN 100) mirror port
- `/app/captures/core_switch.pcap` — Core distribution switch trunk mirror (802.1Q tagged)
- `/app/captures/internal_monitor.pcap` — Internal segment (VLAN 200) mirror port
- `/app/topology.json` — Network architecture with host registry, VLAN definitions, gateway MACs, and security policies

## Required Output (`/app/report.json`)

```json
{
  "attack_timeline": [
    {"phase": "<phase>", "source_ip": "<ip>", "target": "<ip_or_description>", "technique": "<description>"}
  ],
  "attacker_infrastructure": {
    "external_ip": "<ip>",
    "c2_domains": ["<domain>"],
    "exfil_domains": ["<domain>"]
  },
  "compromised_hosts": [
    {"ip": "<ip>", "method": "<how_compromised>"}
  ],
  "exfiltrated_data": "<decoded_plaintext>",
  "network_anomalies": [
    {"type": "<anomaly_type>", "details": {}}
  ],
  "indicators_of_compromise": {
    "malicious_ips": ["<ip>"],
    "malicious_domains": ["<domain>"],
    "compromised_ips": ["<ip>"],
    "targeted_services": [{"ip": "<ip>", "port": "<int>"}]
  },
  "traffic_summary": {
    "total_packets": "<int>",
    "per_capture": {"perimeter": "<int>", "dmz_switch": "<int>", "core_switch": "<int>", "internal_monitor": "<int>"},
    "protocol_counts": {"tcp": "<int>", "udp": "<int>", "arp": "<int>"}
  }
}
```

**attack_timeline**: Chronologically ordered attack phases reconstructed from packet evidence across all captures. Valid phase identifiers: `reconnaissance`, `initial_access`, `c2_establishment`, `internal_reconnaissance`, `lateral_movement`, `data_access`, `data_exfiltration`, `persistence`. Report only phases with supporting packet evidence.

**attacker_infrastructure**: External addresses and domain names used for attack operations.

**compromised_hosts**: Hosts taken over during the intrusion with the method of compromise.

**exfiltrated_data**: Decoded plaintext of data covertly extracted from the network.

**network_anomalies**: Security-relevant deviations. Valid types: `syn_scan`, `dns_tunneling`, `arp_poisoning`, `cross_vlan_access`.

**indicators_of_compromise**: Consolidated threat indicators from the analysis.

**traffic_summary**: Aggregate packet statistics across all captures.