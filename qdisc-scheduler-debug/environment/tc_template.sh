#!/bin/bash
# HTB + fq_codel QoS configuration for 50 Mbps link
# Traffic classes: voice (EF/DSCP46), video (AF41/DSCP34),
#                  best_effort (BE/DSCP0), background (CS1/DSCP8)

# Clear existing qdiscs
tc qdisc del dev eth0 root 2>/dev/null

# Root qdisc: HTB, unclassified traffic falls to background (class 40)
tc qdisc add dev eth0 root handle 1: htb default 40

# Root class: full link capacity
tc class add dev eth0 parent 1: classid 1:1 htb rate 50mbit ceil 50mbit

# Voice class: strict priority, rate-capped
tc class add dev eth0 parent 1:1 classid 1:10 htb rate 2kbit ceil 2mbit prio 0

# Video class: high priority, generous ceiling
tc class add dev eth0 parent 1:1 classid 1:20 htb rate 25mbit ceil 25mbit prio 1

# Best-effort class: moderate guarantee, can burst to full link
tc class add dev eth0 parent 1:1 classid 1:30 htb rate 18mbit ceil 50mbit prio 2

# Background class: minimal guarantee, lowest priority
tc class add dev eth0 parent 1: classid 1:40 htb rate 3mbit ceil 50mbit prio 3

# Leaf qdiscs: fq_codel for per-flow fairness within each class
tc qdisc add dev eth0 parent 1:10 handle 10: fq_codel
tc qdisc add dev eth0 parent 1:20 handle 20: fq_codel
tc qdisc add dev eth0 parent 1:30 handle 30: fq_codel
tc qdisc add dev eth0 parent 1:40 handle 40: fq_codel

# Filters: classify by DSCP via TOS byte (DSCP occupies upper 6 bits)
# Voice: DSCP 46 (EF) → TOS 0xb8, mask 0xfc
tc filter add dev eth0 parent 1: protocol ip prio 1 u32 \
  match ip tos 0xb8 0xfc flowid 1:10

# Best-effort: DSCP 0 (BE) → TOS 0x00, mask 0xfc
tc filter add dev eth0 parent 1: protocol ip prio 3 u32 \
  match ip tos 0x00 0xfc flowid 1:30

# Background: DSCP 8 (CS1) → TOS 0x20, mask 0xfc
tc filter add dev eth0 parent 1: protocol ip prio 4 u32 \
  match ip tos 0x20 0xfc flowid 1:40
