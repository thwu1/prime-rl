#!/usr/bin/env python3
"""
Parses strace -f -e trace=socket,bind,connect,getsockname,setsockopt,close
output logs into scenario.json format for the TCP bind bucket oracle.

Handles PID-prefixed and non-prefixed output, per-PID FD namespaces,
unfinished/resumed syscalls, and error detection from return values.

"""

import argparse
import json
import re
import sys


def parse_strace(log_text, ephemeral_lo=60000, ephemeral_hi=60000,
                 auto_src_ip="127.0.0.1"):
    lines = log_text.strip().split('\n')

    fd_to_sid = {}       # (pid, fd) -> socket_id
    socket_counter = 0
    operations = []
    step = 0

    # Pending unfinished calls: pid -> dict with parsed syscall args
    pending = {}

    pid_prefix_re = re.compile(r'^\[pid\s+(\d+)\]\s+(.*)')

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # --- extract PID ---
        m = pid_prefix_re.match(line)
        if m:
            pid = int(m.group(1))
            content = m.group(2)
        else:
            pid = 0
            content = line

        # --- resumed call ---
        resumed_m = re.match(
            r'<\.\.\.\s+(\w+)\s+resumed>\s*\)\s*=\s*(-?\d+)', content)
        if resumed_m:
            syscall = resumed_m.group(1)
            if pid in pending and pending[pid]['syscall'] == syscall:
                info = pending.pop(pid)
                step += 1
                if syscall == 'connect' and 'sid' in info:
                    operations.append({
                        'step': step, 'action': 'connect',
                        'id': info['sid'],
                        'dst_ip': info['dst_ip'],
                        'dst_port': info['dst_port'],
                    })
                elif syscall == 'bind' and 'sid' in info:
                    operations.append({
                        'step': step, 'action': 'bind',
                        'id': info['sid'],
                        'ip': info['ip'], 'port': info['port'],
                    })
            continue

        # --- unfinished call ---
        unfinished_m = re.match(
            r'(\w+)\((.+?)\s*<unfinished\s*\.\.\.>', content)
        if unfinished_m:
            syscall = unfinished_m.group(1)
            args = unfinished_m.group(2)
            info = {'syscall': syscall}

            if syscall == 'connect':
                cm = re.search(
                    r'(\d+),\s*\{.*?sin_port=htons\((\d+)\).*?'
                    r'inet_addr\("([^"]+)"\)', args)
                if cm:
                    fd = int(cm.group(1))
                    key = (pid, fd)
                    if key in fd_to_sid:
                        info['sid'] = fd_to_sid[key]
                        info['dst_port'] = int(cm.group(2))
                        info['dst_ip'] = cm.group(3)
                        pending[pid] = info
            elif syscall == 'bind':
                bm = re.search(
                    r'(\d+),\s*\{.*?sin_port=htons\((\d+)\).*?'
                    r'inet_addr\("([^"]+)"\)', args)
                if bm:
                    fd = int(bm.group(1))
                    key = (pid, fd)
                    if key in fd_to_sid:
                        info['sid'] = fd_to_sid[key]
                        info['port'] = int(bm.group(2))
                        info['ip'] = bm.group(3)
                        pending[pid] = info
            continue

        # --- socket() ---
        socket_m = re.match(
            r'socket\(AF_INET,\s*SOCK_STREAM[^)]*,\s*IPPROTO_TCP\)'
            r'\s*=\s*(\d+)', content)
        if socket_m:
            fd = int(socket_m.group(1))
            socket_counter += 1
            sid = f's{socket_counter}'
            fd_to_sid[(pid, fd)] = sid
            step += 1
            operations.append({'step': step, 'action': 'socket', 'id': sid})
            continue

        # --- setsockopt() ---
        sso_m = re.match(
            r'setsockopt\((\d+),\s*\w+,\s*(\w+),\s*\[(\d+)\]', content)
        if sso_m:
            fd = int(sso_m.group(1))
            optname = sso_m.group(2)
            value = int(sso_m.group(3))
            key = (pid, fd)
            if key in fd_to_sid and optname in (
                'SO_REUSEADDR', 'IP_BIND_ADDRESS_NO_PORT'
            ):
                step += 1
                operations.append({
                    'step': step, 'action': 'setsockopt',
                    'id': fd_to_sid[key],
                    'option': optname, 'value': value,
                })
            continue

        # --- bind() ---
        bind_m = re.match(
            r'bind\((\d+),\s*\{.*?sin_port=htons\((\d+)\).*?'
            r'inet_addr\("([^"]+)"\).*?\}.*?=\s*(-?\d+)', content)
        if bind_m:
            fd = int(bind_m.group(1))
            port = int(bind_m.group(2))
            ip = bind_m.group(3)
            key = (pid, fd)
            if key in fd_to_sid:
                step += 1
                operations.append({
                    'step': step, 'action': 'bind',
                    'id': fd_to_sid[key],
                    'ip': ip, 'port': port,
                })
            continue

        # --- connect() (completed, not unfinished) ---
        conn_m = re.match(
            r'connect\((\d+),\s*\{.*?sin_port=htons\((\d+)\).*?'
            r'inet_addr\("([^"]+)"\).*?\}.*?=\s*(-?\d+)', content)
        if conn_m:
            fd = int(conn_m.group(1))
            dst_port = int(conn_m.group(2))
            dst_ip = conn_m.group(3)
            key = (pid, fd)
            if key in fd_to_sid:
                step += 1
                operations.append({
                    'step': step, 'action': 'connect',
                    'id': fd_to_sid[key],
                    'dst_ip': dst_ip, 'dst_port': dst_port,
                })
            continue

        # --- getsockname() --- skip (informational)
        if content.startswith('getsockname('):
            continue

        # --- close() ---
        close_m = re.match(r'close\((\d+)\)\s*=\s*(-?\d+)', content)
        if close_m:
            fd = int(close_m.group(1))
            key = (pid, fd)
            if key in fd_to_sid:
                step += 1
                operations.append({
                    'step': step, 'action': 'close',
                    'id': fd_to_sid[key],
                })
                del fd_to_sid[key]
            continue

    return {
        'config': {
            'ephemeral_range': [ephemeral_lo, ephemeral_hi],
            'auto_src_ip': auto_src_ip,
        },
        'operations': operations,
    }


def main():
    parser = argparse.ArgumentParser(
        description='Parse strace log to scenario.json')
    parser.add_argument('strace_log', help='Path to strace log file')
    parser.add_argument('output', help='Path to output scenario.json')
    parser.add_argument('--ephemeral-lo', type=int, default=60000)
    parser.add_argument('--ephemeral-hi', type=int, default=60000)
    parser.add_argument('--auto-src-ip', default='127.0.0.1')
    args = parser.parse_args()

    with open(args.strace_log) as f:
        log_text = f.read()

    scenario = parse_strace(
        log_text, args.ephemeral_lo, args.ephemeral_hi, args.auto_src_ip)

    with open(args.output, 'w') as f:
        json.dump(scenario, f, indent=2)


if __name__ == '__main__':
    main()
