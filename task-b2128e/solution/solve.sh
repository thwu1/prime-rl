#!/bin/bash

cd /app

# Step 1: Transform namespaced XML queries using XSLT
xsltproc /app/transform.xsl /app/raw_queries.xml > /app/queries.xml

# Step 2: Extract syslog data from pcap using tshark (JSON format)
tshark -r /app/router_logs.pcap -T json 2>/dev/null > /tmp/pcap_data.json

# Step 3: Compute OSPF routes from merged topology data
python3 /solution/ospf_solver.py

# Step 4: Validate output structure with jq
jq -e '
  length == 15 and
  (map(has("router","destination","next_hop","cost","route_type")) | all) and
  (map(.router | startswith("R")) | all) and
  (map(.next_hop | startswith("R")) | all) and
  (map(.cost >= 0) | all)
' /app/results.json > /dev/null
