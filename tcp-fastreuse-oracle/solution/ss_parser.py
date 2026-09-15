#!/usr/bin/env python3
"""
Parses ss -tnep output to extract TCP connection state.

Handles variable-width columns, wildcard addresses, optional process info,
and multiple TCP states (ESTAB, LISTEN, TIME-WAIT, CLOSE-WAIT, etc.).

"""

import argparse
import json
import re
import sys

VALID_STATES = frozenset({
    'ESTAB', 'SYN-SENT', 'SYN-RECV', 'FIN-WAIT-1', 'FIN-WAIT-2',
    'TIME-WAIT', 'CLOSE', 'CLOSE-WAIT', 'LAST-ACK', 'LISTEN', 'CLOSING',
})


def parse_addr_port(addr_str):
    """Parse address:port string. Handles IPv4 and [IPv6]:port."""
    if addr_str.startswith('['):
        bracket_end = addr_str.rindex(']')
        ip = addr_str[1:bracket_end]
        port = int(addr_str[bracket_end + 2:])
    else:
        last_colon = addr_str.rindex(':')
        ip = addr_str[:last_colon]
        port_str = addr_str[last_colon + 1:]
        port = int(port_str) if port_str != '*' else 0
    return ip, port


def parse_ss(text):
    lines = text.strip().split('\n')
    connections = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Skip header
        if line.startswith('State') or line.startswith('Netid'):
            continue

        parts = line.split()
        if len(parts) < 5:
            continue

        state = parts[0]
        if state not in VALID_STATES:
            continue

        local_ip, local_port = parse_addr_port(parts[3])
        peer_ip, peer_port = parse_addr_port(parts[4])

        conn = {
            'state': state,
            'local_ip': local_ip,
            'local_port': local_port,
            'peer_ip': peer_ip,
            'peer_port': peer_port,
        }

        rest = ' '.join(parts[5:])
        if 'users:' in rest:
            pid_m = re.search(r'pid=(\d+)', rest)
            fd_m = re.search(r'fd=(\d+)', rest)
            if pid_m:
                conn['pid'] = int(pid_m.group(1))
            if fd_m:
                conn['fd'] = int(fd_m.group(1))

        connections.append(conn)

    return connections


def main():
    parser = argparse.ArgumentParser(description='Parse ss -tnep output')
    parser.add_argument('ss_file', help='Path to ss output file')
    parser.add_argument('output', help='Path to output JSON file')
    args = parser.parse_args()

    with open(args.ss_file) as f:
        text = f.read()

    connections = parse_ss(text)

    with open(args.output, 'w') as f:
        json.dump(connections, f, indent=2)


if __name__ == '__main__':
    main()
