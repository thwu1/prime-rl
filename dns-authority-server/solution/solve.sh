#!/bin/bash

# Repair the broken DNS server by analyzing the reference pcap capture.
# The repair script parses the pcap binary to discover required protocol
# behaviors, extracts the zone parser from the broken server, and generates
# a corrected server incorporating all discovered features.

python3 /solution/repair_server.py
