#!/bin/bash
# Traffic Analysis Module v1.2
# Analyzes captured network traffic for known exploit signatures
# Outputs active threat correlation to CVE identifiers
# Requires: tshark, jq

PCAP_FILE="/app/traffic.pcap"
OUTPUT_FILE="/app/active_threats.json"

if [ ! -f "$PCAP_FILE" ]; then
    echo '{"active_exploits": []}' > "$OUTPUT_FILE"
    echo "[-] No PCAP file found at $PCAP_FILE"
    exit 0
fi

# --- Detect Shellshock (CVE-2014-6271) ---
# Look for function definition pattern "() {" indicative of Bash function injection
SHELLSHOCK=$(tshark -r "$PCAP_FILE" \
    -Y 'http.request.uri contains "() {"' \
    -T fields -e ip.src -e frame.number \
    2>/dev/null | head -1)

# --- Detect Log4Shell (CVE-2021-44228) ---
# Look for JNDI lookup patterns in HTTP traffic
LOG4SHELL=$(tshark -r "$PCAP_FILE" \
    -Y 'tcp.dstport == 80 and http.user_agent contains "jndi:"' \
    -T fields -e ip.src -e frame.number \
    2>/dev/null | head -1)

# --- Detect Path Traversal (CVE-2021-41773) ---
# Look for encoded directory traversal sequences in HTTP URIs
PATHTRAVERSAL=$(tshark -r "$PCAP_FILE" \
    -Y 'http.request.uri contains "%2e"' \
    -T fields -e ip.src -e frame.number \
    2>/dev/null | head -1)

# Build output JSON using jq
jq -n \
    --arg ss "$SHELLSHOCK" \
    --arg l4s "$LOG4SHELL" \
    --arg pt "$PATHTRAVERSAL" \
    '{active_exploits: [
        (if $ss != "" then {cve_id: "CVE-2014-6271", source_ip: ($ss | split("\t") | .[0]), evidence_frame: ($ss | split("\t") | .[1])} else empty end),
        (if $l4s != "" then {cve_id: "CVE-2021-44228", source_ip: ($l4s | split("\t") | .[0]), evidence_frame: ($l4s | split("\t") | .[1])} else empty end),
        (if $pt != "" then {cve_id: "CVE-2021-41773", source_ip: ($pt | split("\t") | .[0]), evidence_frame: ($pt | split("\t") | .[1])} else empty end)
    ]}' > "$OUTPUT_FILE"

DETECTED=$(jq '.active_exploits | length' "$OUTPUT_FILE")
echo "[+] Traffic analysis complete: $DETECTED active exploit(s) detected"
