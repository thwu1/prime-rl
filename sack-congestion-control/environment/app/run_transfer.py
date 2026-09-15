"""
Transfer orchestrator: starts emulators, sender, and receiver, then
verifies the result.

Usage:
  python3 run_transfer.py --file INPUT --output OUTPUT [options]

Prints a JSON result to stdout with keys: success, original_md5,
received_md5, original_size, received_size.
"""

import subprocess
import time
import argparse
import hashlib
import json
import os
import sys
import socket
import signal


def _find_free_ports(n):
    """Return *n* free UDP ports on 127.0.0.1."""
    socks = []
    ports = []
    for _ in range(n):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1', 0))
        ports.append(s.getsockname()[1])
        socks.append(s)
    for s in socks:
        s.close()
    return ports


def _kill(proc):
    try:
        proc.kill()
        proc.wait(timeout=3)
    except Exception:
        pass


def run_transfer(file_path, output_path, loss=0.0, delay=10.0,
                 jitter=5.0, reorder=0.0, corrupt=0.0, duplicate=0.0,
                 seed=42, sender_log=None, receiver_log=None,
                 timeout=60):

    sender_port, receiver_port, emu_fwd_port, emu_rev_port = \
        _find_free_ports(4)

    procs = []

    try:
        # Forward emulator: sender → receiver
        procs.append(subprocess.Popen([
            sys.executable, '/app/emulator.py',
            '--listen-port', str(emu_fwd_port),
            '--forward-port', str(receiver_port),
            '--loss', str(loss),
            '--delay', str(delay),
            '--jitter', str(jitter),
            '--reorder', str(reorder),
            '--corrupt', str(corrupt),
            '--duplicate', str(duplicate),
            '--seed', str(seed),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

        # Reverse emulator: receiver → sender  (less loss on ACK path)
        procs.append(subprocess.Popen([
            sys.executable, '/app/emulator.py',
            '--listen-port', str(emu_rev_port),
            '--forward-port', str(sender_port),
            '--loss', str(loss / 2),
            '--delay', str(delay),
            '--jitter', str(jitter),
            '--reorder', str(reorder / 2),
            '--seed', str(seed + 1),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

        time.sleep(0.3)

        # Receiver
        recv_cmd = [
            sys.executable, '/app/receiver.py',
            '--listen-port', str(receiver_port),
            '--sender-host', '127.0.0.1',
            '--sender-port', str(emu_rev_port),
            '--output', output_path,
        ]
        if receiver_log:
            recv_cmd += ['--log', receiver_log]
        procs.append(subprocess.Popen(recv_cmd,
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL))

        time.sleep(0.2)

        # Sender
        send_cmd = [
            sys.executable, '/app/sender.py',
            '--dest-host', '127.0.0.1',
            '--dest-port', str(emu_fwd_port),
            '--listen-port', str(sender_port),
            '--file', file_path,
        ]
        if sender_log:
            send_cmd += ['--log', sender_log]
        sender_proc = subprocess.Popen(send_cmd,
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
        procs.append(sender_proc)

        sender_proc.wait(timeout=timeout)
        # give receiver a moment to flush
        procs[2].wait(timeout=5)

    except subprocess.TimeoutExpired:
        pass
    finally:
        for p in procs:
            _kill(p)

    # ---- verify ----
    with open(file_path, 'rb') as fh:
        original_md5 = hashlib.md5(fh.read()).hexdigest()
    original_size = os.path.getsize(file_path)

    if os.path.exists(output_path):
        with open(output_path, 'rb') as fh:
            received_md5 = hashlib.md5(fh.read()).hexdigest()
        received_size = os.path.getsize(output_path)
    else:
        received_md5 = None
        received_size = 0

    return {
        'success': original_md5 == received_md5,
        'original_md5': original_md5,
        'received_md5': received_md5,
        'original_size': original_size,
        'received_size': received_size,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--file', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--loss', type=float, default=0.0)
    p.add_argument('--delay', type=float, default=10.0)
    p.add_argument('--jitter', type=float, default=5.0)
    p.add_argument('--reorder', type=float, default=0.0)
    p.add_argument('--corrupt', type=float, default=0.0)
    p.add_argument('--duplicate', type=float, default=0.0)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--sender-log', default=None)
    p.add_argument('--receiver-log', default=None)
    p.add_argument('--timeout', type=int, default=60)
    a = p.parse_args()

    result = run_transfer(
        a.file, a.output,
        loss=a.loss, delay=a.delay, jitter=a.jitter,
        reorder=a.reorder, corrupt=a.corrupt, duplicate=a.duplicate,
        seed=a.seed, sender_log=a.sender_log,
        receiver_log=a.receiver_log, timeout=a.timeout,
    )

    print(json.dumps(result))
    sys.exit(0 if result['success'] else 1)


if __name__ == '__main__':
    main()
