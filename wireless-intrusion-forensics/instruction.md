A packet capture at `/app/evidence08.pcap` contains 802.11 wireless traffic from a WEP-encrypted network that was attacked and fully compromised. An unknown station performed a multi-phase wireless intrusion: management frame injection to disrupt legitimate clients, traffic injection to accelerate WEP IV collection, key recovery, decryption, and administrative takeover of the access point.

Conduct a forensic investigation, **evaluate** the attack methodology by classifying the specific technique and computing effectiveness metrics, and **create** working tshark display filters that would detect each attack phase if deployed as monitoring rules.

Produce `/app/assessment.json` with these exact keys:

**Network Identification:**
- `ssid` (string): Target AP SSID
- `bssid` (string): Target AP BSSID (lowercase colon-separated hex)

**Key Recovery:**
- `wep_key` (string): Recovered WEP key (uppercase colon-separated hex)

**Attacker Identification:**
- `attacker_mac` (string): MAC of the attacking station (lowercase colon-separated hex)

**Attack Technique Evaluation:**
- `attack_technique` (string): The IV amplification technique used by the attacker. Must be exactly one of: `"arp-replay"`, `"chopchop"`, `"fragmentation"`, `"caffe-latte"`, or `"korek-chopchop"`. Determine this by evaluating the frame size distribution, traffic directionality, and injection patterns in the capture.
- `technique_evidence` (string): A sentence explaining which specific traffic characteristics (frame sizes, directionality, protocol patterns) led to your classification. Must reference at least one concrete numeric observation from the PCAP.

**Capture Statistics:**
- `capture_duration_seconds` (int): Total capture duration, rounded to nearest second
- `total_wep_data_frames` (int): Count of WEP-encrypted data frames (type/subtype 0x20, Protected flag set) on the target BSS
- `total_unique_ivs` (int): Count of unique WEP initialization vectors across all stations for the target AP
- `attacker_unique_ivs` (int): Count of unique IVs from frames sourced by the attacking station
- `attacker_iv_share` (float): Percentage of unique IVs attributable to the attacker (1 decimal place, e.g. `47.5`)

**Deauthentication Analysis:**
- `deauth_frame_count` (int): Total deauthentication frames (type/subtype 0x0c) on the target BSS

**Post-Compromise:**
- `admin_username` (string): WAP administrative username from decrypted HTTP traffic
- `admin_password` (string): WAP administrative password from decrypted HTTP traffic
- `new_admin_passphrase` (string): The passphrase the attacker changed on the WAP admin interface

**Detection Engineering** (create working tshark display filters):
- `deauth_detection_filter` (string): A tshark display filter expression that matches all deauthentication frames on the compromised AP's BSS — and only those frames (no false positives from other frame types)
- `replay_detection_filter` (string): A tshark display filter expression that matches the attacker's injected WEP data frames on the target BSS — must match only WEP-protected data frames from the attacking station

Both detection filters will be validated by running them against the PCAP. The deauth filter must produce frames that are exclusively deauth type; the replay filter must produce exclusively WEP data frames from a single source MAC matching your reported attacker.