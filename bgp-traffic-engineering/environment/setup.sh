#!/bin/bash
set -e

# Check if already set up
if ip netns list 2>/dev/null | grep -q "^r1 "; then
    echo "Topology already initialized."
    # Verify daemons are running
    for ns in r1 r2 r3 r4; do
        if ! ip netns exec $ns test -e /var/run/frr/$ns/bgpd.pid 2>/dev/null; then
            echo "WARNING: bgpd not running in $ns, restarting daemons..."
            ip netns exec $ns /usr/lib/frr/zebra -d \
                -f /etc/frr/$ns/zebra.conf \
                -i /var/run/frr/$ns/zebra.pid \
                -z /var/run/frr/$ns/zserv.api \
                --vty_socket /var/run/frr/$ns \
                --log file:/var/log/frr/$ns/zebra.log 2>/dev/null || true
            sleep 1
            ip netns exec $ns /usr/lib/frr/staticd -d \
                -f /etc/frr/$ns/staticd.conf \
                -i /var/run/frr/$ns/staticd.pid \
                -z /var/run/frr/$ns/zserv.api \
                --vty_socket /var/run/frr/$ns \
                --log file:/var/log/frr/$ns/staticd.log 2>/dev/null || true
            sleep 0.5
            ip netns exec $ns /usr/lib/frr/bgpd -d \
                -f /etc/frr/$ns/bgpd.conf \
                -i /var/run/frr/$ns/bgpd.pid \
                -z /var/run/frr/$ns/zserv.api \
                --vty_socket /var/run/frr/$ns \
                --log file:/var/log/frr/$ns/bgpd.log 2>/dev/null || true
        fi
    done
    exit 0
fi

echo "=== Creating network namespaces ==="
for ns in r1 r2 r3 r4; do
    ip netns add $ns
    ip netns exec $ns ip link set lo up
    ip netns exec $ns sysctl -q -w net.ipv4.ip_forward=1
done

echo "=== Creating veth pairs and assigning addresses ==="

# r1 <-> r2: 10.0.12.0/30
ip link add veth12a type veth peer name veth12b
ip link set veth12a netns r1
ip link set veth12b netns r2
ip netns exec r1 ip addr add 10.0.12.1/30 dev veth12a
ip netns exec r1 ip link set veth12a up
ip netns exec r2 ip addr add 10.0.12.2/30 dev veth12b
ip netns exec r2 ip link set veth12b up

# r2 <-> r3: 10.0.23.0/30
ip link add veth23a type veth peer name veth23b
ip link set veth23a netns r2
ip link set veth23b netns r3
ip netns exec r2 ip addr add 10.0.23.1/30 dev veth23a
ip netns exec r2 ip link set veth23a up
ip netns exec r3 ip addr add 10.0.23.2/30 dev veth23b
ip netns exec r3 ip link set veth23b up

# r3 <-> r4: 10.0.34.0/30
ip link add veth34a type veth peer name veth34b
ip link set veth34a netns r3
ip link set veth34b netns r4
ip netns exec r3 ip addr add 10.0.34.1/30 dev veth34a
ip netns exec r3 ip link set veth34a up
ip netns exec r4 ip addr add 10.0.34.2/30 dev veth34b
ip netns exec r4 ip link set veth34b up

# r1 <-> r4: 10.0.14.0/30
ip link add veth14a type veth peer name veth14b
ip link set veth14a netns r1
ip link set veth14b netns r4
ip netns exec r1 ip addr add 10.0.14.1/30 dev veth14a
ip netns exec r1 ip link set veth14a up
ip netns exec r4 ip addr add 10.0.14.2/30 dev veth14b
ip netns exec r4 ip link set veth14b up

echo "=== Configuring loopback addresses ==="
ip netns exec r1 ip addr add 10.255.0.1/32 dev lo
ip netns exec r2 ip addr add 10.255.0.2/32 dev lo
ip netns exec r3 ip addr add 10.255.0.3/32 dev lo
ip netns exec r4 ip addr add 10.255.0.4/32 dev lo

echo "=== Adding static routes for iBGP loopback reachability (AS65002: r2<->r3) ==="
ip netns exec r2 ip route add 10.255.0.3/32 via 10.0.23.2
ip netns exec r3 ip route add 10.255.0.2/32 via 10.0.23.1

echo "=== Adding blackhole routes for originated prefixes ==="
# r1 prefixes
ip netns exec r1 ip route add blackhole 10.1.0.0/24
ip netns exec r1 ip route add blackhole 10.1.1.0/24

# r4 prefixes
ip netns exec r4 ip route add blackhole 10.4.0.0/22
ip netns exec r4 ip route add blackhole 10.4.0.0/24
ip netns exec r4 ip route add blackhole 10.4.1.0/24
ip netns exec r4 ip route add blackhole 10.4.2.0/24
ip netns exec r4 ip route add blackhole 10.4.3.0/24

echo "=== Starting FRR daemons ==="
for ns in r1 r2 r3 r4; do
    mkdir -p /var/run/frr/$ns /var/log/frr/$ns /etc/frr/$ns

    # Create minimal zebra config
    echo "hostname $ns" > /etc/frr/$ns/zebra.conf

    # Create minimal staticd config
    echo "hostname $ns" > /etc/frr/$ns/staticd.conf

    # Copy BGP config
    cp /app/configs/$ns.conf /etc/frr/$ns/bgpd.conf

    # Create vtysh.conf
    echo "service integrated-vtysh-config" > /etc/frr/$ns/vtysh.conf

    # Start zebra
    ip netns exec $ns /usr/lib/frr/zebra -d \
        -f /etc/frr/$ns/zebra.conf \
        -i /var/run/frr/$ns/zebra.pid \
        -z /var/run/frr/$ns/zserv.api \
        --vty_socket /var/run/frr/$ns \
        --log file:/var/log/frr/$ns/zebra.log

    sleep 1

    # Start staticd
    ip netns exec $ns /usr/lib/frr/staticd -d \
        -f /etc/frr/$ns/staticd.conf \
        -i /var/run/frr/$ns/staticd.pid \
        -z /var/run/frr/$ns/zserv.api \
        --vty_socket /var/run/frr/$ns \
        --log file:/var/log/frr/$ns/staticd.log

    sleep 0.5

    # Start bgpd
    ip netns exec $ns /usr/lib/frr/bgpd -d \
        -f /etc/frr/$ns/bgpd.conf \
        -i /var/run/frr/$ns/bgpd.pid \
        -z /var/run/frr/$ns/zserv.api \
        --vty_socket /var/run/frr/$ns \
        --log file:/var/log/frr/$ns/bgpd.log

    echo "  Started FRR daemons in namespace $ns"
done

echo ""
echo "=== Topology initialized ==="
echo ""
echo "Interact with routers using:"
echo "  ip netns exec <r1|r2|r3|r4> vtysh --vty_socket /var/run/frr/<router>"
echo ""
echo "Example:"
echo "  ip netns exec r1 vtysh --vty_socket /var/run/frr/r1 -c 'show bgp summary'"
echo ""
echo "Waiting for BGP initialization..."
sleep 5
echo "Ready."
