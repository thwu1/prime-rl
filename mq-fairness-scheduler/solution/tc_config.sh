#!/bin/bash
#
# Linux tc (traffic control) configuration for the weighted scenario.
# Sets up a classful HTB hierarchy on a dummy interface to replicate
# the weighted scenario's bandwidth allocation policy.
#
# Weighted scenario: 80 Mbps global, 4 flows with weights 1, 3, 2, 2
# Total weight = 8, per-weight rate = 10 Mbps

# Create dummy interface
ip link add mqsim0 type dummy 2>/dev/null || true
ip link set mqsim0 up

# Remove any existing qdisc
tc qdisc del dev mqsim0 root 2>/dev/null || true

# Root HTB qdisc
tc qdisc add dev mqsim0 root handle 1: htb default 40

# Root class enforcing 80 Mbps global rate limit
tc class add dev mqsim0 parent 1: classid 1:1 htb rate 80mbit burst 80kb

# Flow 0: weight 1 -> guaranteed rate = 10mbit, can borrow up to 80mbit
tc class add dev mqsim0 parent 1:1 classid 1:10 htb rate 10mbit ceil 80mbit burst 10kb

# Flow 1: weight 3 -> guaranteed rate = 30mbit, can borrow up to 80mbit
tc class add dev mqsim0 parent 1:1 classid 1:20 htb rate 30mbit ceil 80mbit burst 30kb

# Flow 2: weight 2 -> guaranteed rate = 20mbit, can borrow up to 80mbit
tc class add dev mqsim0 parent 1:1 classid 1:30 htb rate 20mbit ceil 80mbit burst 20kb

# Flow 3: weight 2 -> guaranteed rate = 20mbit, can borrow up to 80mbit
tc class add dev mqsim0 parent 1:1 classid 1:40 htb rate 20mbit ceil 80mbit burst 20kb

# Classification filters: map flows to classes by source port
tc filter add dev mqsim0 parent 1: protocol ip prio 1 u32 \
    match ip sport 5000 0xffff flowid 1:10
tc filter add dev mqsim0 parent 1: protocol ip prio 1 u32 \
    match ip sport 5001 0xffff flowid 1:20
tc filter add dev mqsim0 parent 1: protocol ip prio 1 u32 \
    match ip sport 5002 0xffff flowid 1:30
tc filter add dev mqsim0 parent 1: protocol ip prio 1 u32 \
    match ip sport 5003 0xffff flowid 1:40
