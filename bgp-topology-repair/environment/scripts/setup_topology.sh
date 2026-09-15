#!/bin/bash
# Setup the 5-router BGP lab topology using Linux network namespaces and FRR
set -e

# Check if already set up
if ip netns list 2>/dev/null | grep -q "^r1 "; then
    echo "Topology already exists, skipping setup."
    exit 0
fi

echo "Setting up BGP lab topology..."

# Enable IP forwarding
sysctl -w net.ipv4.ip_forward=1 > /dev/null 2>&1 || true

# Create network namespaces
for ns in r1 r2 r3 r4 r5; do
    ip netns add "$ns"
    ip netns exec "$ns" ip link set lo up
    ip netns exec "$ns" sysctl -w net.ipv4.ip_forward=1 > /dev/null 2>&1 || true
done

# --- Create veth pairs and assign to namespaces ---

# R1-R2 (AS 65000 internal)
ip link add r1-eth0 type veth peer name r2-eth0
ip link set r1-eth0 netns r1
ip link set r2-eth0 netns r2
ip netns exec r1 ip addr add 10.0.12.1/24 dev r1-eth0
ip netns exec r2 ip addr add 10.0.12.2/24 dev r2-eth0
ip netns exec r1 ip link set r1-eth0 up
ip netns exec r2 ip link set r2-eth0 up

# R2-R3 (AS 65000 internal)
ip link add r2-eth1 type veth peer name r3-eth0
ip link set r2-eth1 netns r2
ip link set r3-eth0 netns r3
ip netns exec r2 ip addr add 10.0.23.2/24 dev r2-eth1
ip netns exec r3 ip addr add 10.0.23.3/24 dev r3-eth0
ip netns exec r2 ip link set r2-eth1 up
ip netns exec r3 ip link set r3-eth0 up

# R1-R4 (eBGP link)
ip link add r1-eth1 type veth peer name r4-eth0
ip link set r1-eth1 netns r1
ip link set r4-eth0 netns r4
ip netns exec r1 ip addr add 10.0.14.1/24 dev r1-eth1
ip netns exec r4 ip addr add 10.0.14.4/24 dev r4-eth0
ip netns exec r1 ip link set r1-eth1 up
ip netns exec r4 ip link set r4-eth0 up

# R3-R5 (eBGP link)
ip link add r3-eth1 type veth peer name r5-eth0
ip link set r3-eth1 netns r3
ip link set r5-eth0 netns r5
ip netns exec r3 ip addr add 10.0.35.3/24 dev r3-eth1
ip netns exec r5 ip addr add 10.0.35.5/24 dev r5-eth0
ip netns exec r3 ip link set r3-eth1 up
ip netns exec r5 ip link set r5-eth0 up

# --- Configure loopback addresses ---
ip netns exec r1 ip addr add 10.255.0.1/32 dev lo
ip netns exec r2 ip addr add 10.255.0.2/32 dev lo
ip netns exec r3 ip addr add 10.255.0.3/32 dev lo
ip netns exec r4 ip addr add 10.255.1.4/32 dev lo
ip netns exec r5 ip addr add 10.255.2.5/32 dev lo

# --- Add networks for BGP advertisement ---

# AS 65000 network (on R2)
ip netns exec r2 ip addr add 192.168.100.1/24 dev lo

# R4 (AS 65001) advertised networks
ip netns exec r4 ip addr add 172.16.0.1/24 dev lo
ip netns exec r4 ip addr add 172.16.1.1/24 dev lo
ip netns exec r4 ip addr add 172.18.0.1/24 dev lo

# R5 (AS 65002) advertised networks
ip netns exec r5 ip addr add 172.17.0.1/24 dev lo
ip netns exec r5 ip addr add 172.17.1.1/24 dev lo
ip netns exec r5 ip addr add 172.18.0.2/24 dev lo

# --- Create FRR runtime directories ---
for ns in r1 r2 r3 r4 r5; do
    mkdir -p "/var/run/frr/$ns"
    cp "/app/configs/$ns.conf" "/var/run/frr/$ns/frr.conf"
done
mkdir -p /var/log/frr

# --- Start FRR daemons per namespace ---

# Start zebra first (routing table manager)
for ns in r1 r2 r3 r4 r5; do
    ip netns exec "$ns" /usr/lib/frr/zebra -d \
        -f "/var/run/frr/$ns/frr.conf" \
        -i "/var/run/frr/$ns/zebra.pid" \
        -z "/var/run/frr/$ns/zserv.api" \
        --vty_socket "/var/run/frr/$ns" \
        --log "file:/var/log/frr/$ns-zebra.log" \
        -u root -g root
done

sleep 2

# Start staticd (for static route support via vtysh)
for ns in r1 r2 r3 r4 r5; do
    ip netns exec "$ns" /usr/lib/frr/staticd -d \
        -f "/var/run/frr/$ns/frr.conf" \
        -i "/var/run/frr/$ns/staticd.pid" \
        -z "/var/run/frr/$ns/zserv.api" \
        --vty_socket "/var/run/frr/$ns" \
        --log "file:/var/log/frr/$ns-staticd.log" \
        -u root -g root
done

sleep 1

# Start OSPF on AS 65000 routers (R1, R2, R3)
for ns in r1 r2 r3; do
    ip netns exec "$ns" /usr/lib/frr/ospfd -d \
        -f "/var/run/frr/$ns/frr.conf" \
        -i "/var/run/frr/$ns/ospfd.pid" \
        -z "/var/run/frr/$ns/zserv.api" \
        --vty_socket "/var/run/frr/$ns" \
        --log "file:/var/log/frr/$ns-ospfd.log" \
        -u root -g root
done

sleep 2

# Start BGP on all routers
for ns in r1 r2 r3 r4 r5; do
    ip netns exec "$ns" /usr/lib/frr/bgpd -d \
        -f "/var/run/frr/$ns/frr.conf" \
        -i "/var/run/frr/$ns/bgpd.pid" \
        -z "/var/run/frr/$ns/zserv.api" \
        --vty_socket "/var/run/frr/$ns" \
        --log "file:/var/log/frr/$ns-bgpd.log" \
        -u root -g root
done

echo "Topology setup complete. Waiting for initial convergence..."
sleep 5
echo "Ready. Use '/app/scripts/router.sh <r1-r5> [command]' to access routers."
