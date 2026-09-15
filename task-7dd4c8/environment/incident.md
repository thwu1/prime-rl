# Incident Report

## Background

During USGv6 conformance testing of an IPv6 network protection device,
automated monitoring detected anomalous traffic patterns. Ten packet
captures were collected from a passive tap positioned upstream of the
device under test. Each capture file contains traffic from a single
logical flow (one or two packets sharing the same source/destination pair).

## Observations

- Some flows exhibit unusual fragmentation behavior
- Extension header usage varies across flows — some patterns are unexpected
- At least one flow appears to use a mechanism that has been deprecated by the IETF
- Standard IPv6 traffic is also present in the captures

## Request

Perform a complete security analysis of all captures. Classify each flow,
identify all security-relevant findings, and develop an nftables firewall
policy suitable for an IPv6 network protection device.
