#!/usr/bin/env python3
"""
Naive UDP client — demonstrates ephemeral port exhaustion.

Each bind() exclusively locks a source port. Without port sharing,
only 64 connections are possible with 64 ports, even though 8
destinations could support 512 unique 4-tuples.
"""
import socket
import sys

PORT_LO, PORT_HI = 50000, 50063
NUM_PORTS = PORT_HI - PORT_LO + 1
DESTINATIONS = [('127.0.0.1', 9001 + i) for i in range(8)]

sockets = []
failed = False
for i in range(400):
    dst_ip, dst_port = DESTINATIONS[i % len(DESTINATIONS)]
    src_port = PORT_LO + (i % NUM_PORTS)

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(('127.0.0.1', src_port))
        s.connect((dst_ip, dst_port))
        sockets.append(s)
    except OSError as e:
        s.close()
        if not failed:
            print(f"FAILED at connection {i}: {e}")
            print(f"  Tried to bind port {src_port} which is already in use")
            print(f"  Without SO_REUSEADDR, each port can only be bound once")
            failed = True
        break

print(f"\nResult: {len(sockets)} / 400 connections created")
print(f"Source ports: {PORT_LO}-{PORT_HI} ({NUM_PORTS} available)")
print(f"Destinations: {len(DESTINATIONS)}")
print(f"Theoretical max with port reuse: {NUM_PORTS * len(DESTINATIONS)}")
print(f"Actual: limited to {NUM_PORTS} because bind() locks ports exclusively")

for s in sockets:
    s.close()
