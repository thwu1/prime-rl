#!/bin/bash
# Setup multi-area OSPF network topology using Linux network namespaces and FRR
set -e

# Idempotency check
if ip netns list 2>/dev/null | grep -q "^R1"; then
    echo "Topology already initialized."
    exit 0
fi

echo "Creating OSPF network topology..."

# Create network namespaces for each router
for r in R1 R2 R3 R4 R5; do
    ip netns add "$r"
    ip netns exec "$r" ip link set lo up
    ip netns exec "$r" sysctl -w net.ipv4.ip_forward=1 > /dev/null
done

# Create veth pairs between routers
# R1-R2 (Area 0 backbone)
ip link add r1-r2 type veth peer name r2-r1
ip link set r1-r2 netns R1
ip link set r2-r1 netns R2
ip netns exec R1 ip link set r1-r2 up
ip netns exec R2 ip link set r2-r1 up

# R2-R3 (Area 0 backbone)
ip link add r2-r3 type veth peer name r3-r2
ip link set r2-r3 netns R2
ip link set r3-r2 netns R3
ip netns exec R2 ip link set r2-r3 up
ip netns exec R3 ip link set r3-r2 up

# R2-R4 (Area 1)
ip link add r2-r4 type veth peer name r4-r2
ip link set r2-r4 netns R2
ip link set r4-r2 netns R4
ip netns exec R2 ip link set r2-r4 up
ip netns exec R4 ip link set r4-r2 up

# R3-R5 (Area 2)
ip link add r3-r5 type veth peer name r5-r3
ip link set r3-r5 netns R3
ip link set r5-r3 netns R5
ip netns exec R3 ip link set r3-r5 up
ip netns exec R5 ip link set r5-r3 up

# Assign IP addresses
# R1
ip netns exec R1 ip addr add 10.0.1.1/32 dev lo
ip netns exec R1 ip addr add 10.1.12.1/24 dev r1-r2

# R2
ip netns exec R2 ip addr add 10.0.2.2/32 dev lo
ip netns exec R2 ip addr add 10.1.12.2/24 dev r2-r1
ip netns exec R2 ip addr add 10.1.23.2/24 dev r2-r3
ip netns exec R2 ip addr add 10.1.24.2/24 dev r2-r4

# R3
ip netns exec R3 ip addr add 10.0.3.3/32 dev lo
ip netns exec R3 ip addr add 10.1.23.3/24 dev r3-r2
ip netns exec R3 ip addr add 10.1.35.3/24 dev r3-r5

# R4
ip netns exec R4 ip addr add 10.0.4.4/32 dev lo
ip netns exec R4 ip addr add 10.1.24.4/24 dev r4-r2

# R5
ip netns exec R5 ip addr add 10.0.5.5/32 dev lo
ip netns exec R5 ip addr add 10.1.35.5/24 dev r5-r3

# Create FRR configuration directories
for r in R1 R2 R3 R4 R5; do
    mkdir -p /etc/frr/"$r" /var/run/frr/"$r" /var/log/frr/"$r"
done

# Write daemons file for each router
for r in R1 R2 R3 R4 R5; do
    cat > /etc/frr/"$r"/daemons << 'EOF'
ospfd=yes
vtysh_enable=yes
EOF
done

# Write vtysh.conf for each router
for r in R1 R2 R3 R4 R5; do
    cat > /etc/frr/"$r"/vtysh.conf << 'EOF'
service integrated-vtysh-config
EOF
done

# ===== Router Configurations =====

# R1 - Area 0 backbone router (correct configuration)
cat > /etc/frr/R1/frr.conf << 'EOF'
hostname R1
log syslog informational
!
router ospf
 ospf router-id 10.0.1.1
 network 10.0.1.1/32 area 0
 network 10.1.12.0/24 area 0
exit
!
EOF

# R2 - ABR for Area 0 and Area 1
cat > /etc/frr/R2/frr.conf << 'EOF'
hostname R2
log syslog informational
!
interface r2-r3
 ip ospf dead-interval 60
exit
!
router ospf
 ospf router-id 10.0.2.2
 network 10.0.2.2/32 area 0
 network 10.1.12.0/24 area 0
 network 10.1.23.0/24 area 0
exit
!
EOF

# R3 - ABR for Area 0 and Area 2 NSSA (correct configuration)
cat > /etc/frr/R3/frr.conf << 'EOF'
hostname R3
log syslog informational
!
router ospf
 ospf router-id 10.0.3.3
 network 10.0.3.3/32 area 0
 network 10.1.23.0/24 area 0
 network 10.1.35.0/24 area 2
 area 2 nssa
exit
!
EOF

# R4 - Area 1 internal router (correct configuration)
cat > /etc/frr/R4/frr.conf << 'EOF'
hostname R4
log syslog informational
!
router ospf
 ospf router-id 10.0.4.4
 network 10.0.4.4/32 area 1
 network 10.1.24.0/24 area 1
exit
!
EOF

# R5 - Area 2 ASBR (redistributes external routes)
cat > /etc/frr/R5/frr.conf << 'EOF'
hostname R5
log syslog informational
!
ip route 172.16.0.0/24 blackhole
ip route 172.16.1.0/24 blackhole
!
ip prefix-list EXTERNAL_NETS seq 10 permit 172.16.0.0/24
!
route-map EXTERNAL permit 10
 match ip address prefix-list EXTERNAL_NETS
exit
!
router ospf
 ospf router-id 10.0.5.5
 network 10.0.5.5/32 area 2
 network 10.1.35.0/24 area 2
 area 2 stub
 redistribute static route-map EXTERNAL
exit
!
EOF

# Start FRR daemons in each namespace
for r in R1 R2 R3 R4 R5; do
    echo "Starting FRR in $r..."
    ip netns exec "$r" /usr/lib/frr/zebra -d -N "$r" -u root -g root \
        --log file:/var/log/frr/"$r"/zebra.log
    sleep 1
    ip netns exec "$r" /usr/lib/frr/staticd -d -N "$r" -u root -g root \
        --log file:/var/log/frr/"$r"/staticd.log
    sleep 0.5
    ip netns exec "$r" /usr/lib/frr/ospfd -d -N "$r" -u root -g root \
        --log file:/var/log/frr/"$r"/ospfd.log
    sleep 0.5
done

# Wait for daemons to initialize
sleep 3

echo "OSPF network topology initialized with 5 routers (R1-R5)."
echo "FRR configs: /etc/frr/<router>/frr.conf"
echo "FRR logs: /var/log/frr/<router>/"
