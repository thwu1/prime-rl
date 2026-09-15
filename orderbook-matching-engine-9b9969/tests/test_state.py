
import json
import os
import socket
import sqlite3
import struct
import subprocess
import time

import pytest


SIDE_MAP_W = {'SELL': 0, 'BUY': 1}
LIFESPAN_MAP_W = {'FAK': 0, 'GFD': 1}


def build_rtgx_bytes(operations_data):
    """Build RTGX binary wire protocol data as raw bytes."""
    config = operations_data['config']
    operations = operations_data['operations']
    config_json = json.dumps(config).encode('utf-8')

    buf = b'RTGX'
    buf += struct.pack('>I', len(config_json))
    buf += config_json

    for op in operations:
        if op['type'] == 'insert':
            trader_bytes = op['trader'].encode('utf-8').ljust(32, b'\x00')[:32]
            buf += struct.pack('B', 1)
            buf += trader_bytes
            buf += struct.pack('>IBiIB',
                               op['order_id'],
                               SIDE_MAP_W[op['side']],
                               op['price'],
                               op['volume'],
                               LIFESPAN_MAP_W[op['lifespan']])
        elif op['type'] == 'amend':
            trader_bytes = op['trader'].encode('utf-8').ljust(32, b'\x00')[:32]
            buf += struct.pack('B', 2)
            buf += trader_bytes
            buf += struct.pack('>II', op['order_id'], op['new_volume'])
        elif op['type'] == 'cancel':
            trader_bytes = op['trader'].encode('utf-8').ljust(32, b'\x00')[:32]
            buf += struct.pack('B', 3)
            buf += trader_bytes
            buf += struct.pack('>I', op['order_id'])
        elif op['type'] == 'snapshot':
            buf += struct.pack('B', 4)

    return buf


def write_binary_file(path, operations_data):
    """Encode operations in the RTGX binary wire protocol format."""
    buf = build_rtgx_bytes(operations_data)
    with open(path, 'wb') as f:
        f.write(buf)


def run_engine(operations_data, binary_mode=False):
    """Write input, run engine, return parsed output."""
    if binary_mode:
        bin_path = '/app/_test_input.bin'
        write_binary_file(bin_path, operations_data)
        result = subprocess.run(
            ['python3', '/app/engine.py', '--binary', bin_path,
             '/app/_test_output.json'],
            capture_output=True, text=True, cwd='/app', timeout=30
        )
    else:
        json_path = '/app/_test_input.json'
        with open(json_path, 'w') as f:
            json.dump(operations_data, f)
        result = subprocess.run(
            ['python3', '/app/engine.py', json_path,
             '/app/_test_output.json'],
            capture_output=True, text=True, cwd='/app', timeout=30
        )
    assert result.returncode == 0, (
        f"Engine failed (rc={result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert os.path.exists('/app/_test_output.json'), \
        "Engine did not produce /app/_test_output.json"
    with open('/app/_test_output.json') as f:
        return json.load(f)


def find_free_port():
    """Find an available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def run_engine_via_socket(operations_data, extra_args=None):
    """Start engine in serve mode, send RTGX data via TCP, return result."""
    port = find_free_port()
    cmd = ['python3', '/app/engine.py']
    if extra_args:
        cmd.extend(extra_args)
    cmd.extend(['--serve', f'0.0.0.0:{port}'])

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)

    binary_data = build_rtgx_bytes(operations_data)

    # Wait for server to be ready
    connected = False
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(('127.0.0.1', port))
            connected = True
            break
        except (ConnectionRefusedError, OSError):
            s.close()
            time.sleep(0.05)

    if not connected:
        proc.kill()
        stdout, stderr = proc.communicate(timeout=5)
        raise RuntimeError(
            f"Could not connect to server on port {port}. "
            f"stderr: {stderr.decode()}")

    s.sendall(binary_data)
    s.shutdown(socket.SHUT_WR)

    response = b''
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        response += chunk
    s.close()

    proc.wait(timeout=10)
    return json.loads(response.decode('utf-8'))


def run_engine_with_audit(operations_data, audit_db_path,
                          binary_mode=False):
    """Run engine with --audit flag, return parsed output."""
    if os.path.exists(audit_db_path):
        os.remove(audit_db_path)

    if binary_mode:
        bin_path = '/app/_test_audit_input.bin'
        write_binary_file(bin_path, operations_data)
        result = subprocess.run(
            ['python3', '/app/engine.py', '--binary',
             '--audit', audit_db_path,
             bin_path, '/app/_test_audit_output.json'],
            capture_output=True, text=True, cwd='/app', timeout=30
        )
    else:
        json_path = '/app/_test_audit_input.json'
        with open(json_path, 'w') as f:
            json.dump(operations_data, f)
        result = subprocess.run(
            ['python3', '/app/engine.py',
             '--audit', audit_db_path,
             json_path, '/app/_test_audit_output.json'],
            capture_output=True, text=True, cwd='/app', timeout=30
        )
    assert result.returncode == 0, (
        f"Engine with --audit failed (rc={result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    with open('/app/_test_audit_output.json') as f:
        return json.load(f)


STANDARD_CONFIG = {
    "maker_fee": -0.0001,
    "taker_fee": 0.0002,
    "tick_size": 100,
    "position_limit": 50,
    "active_order_count_limit": 5,
    "active_volume_limit": 200
}


# ========== Core matching engine tests ==========


def test_basic_matching_and_fees():
    """Basic insert, match, fill event, fee calculation, accounts."""
    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "A", "order_id": 0, "side": "BUY",
             "price": 10000, "volume": 20, "lifespan": "GFD"},
            {"type": "insert", "trader": "B", "order_id": 0, "side": "SELL",
             "price": 10000, "volume": 10, "lifespan": "GFD"},
            {"type": "snapshot"},
        ]
    }
    out = run_engine(ops)
    ev = out['events']

    assert ev[0] == {"type": "placed", "trader": "A", "order_id": 0,
                     "side": "BUY", "price": 10000, "remaining": 20}

    assert ev[1] == {"type": "fill", "maker": "A", "taker": "B",
                     "price": 10000, "volume": 10,
                     "maker_fee": -10, "taker_fee": 20}

    assert ev[2] == {"type": "snapshot", "bids": [[10000, 10]], "asks": []}

    assert out['accounts']['A'] == {"position": 10, "balance": -99990,
                                    "total_fees": -10}
    assert out['accounts']['B'] == {"position": -10, "balance": 99980,
                                    "total_fees": 20}


def test_partial_fill_gfd_placement():
    """GFD taker partially fills, remainder placed in book."""
    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "A", "order_id": 0, "side": "BUY",
             "price": 10000, "volume": 5, "lifespan": "GFD"},
            {"type": "insert", "trader": "B", "order_id": 0, "side": "SELL",
             "price": 9900, "volume": 8, "lifespan": "GFD"},
            {"type": "snapshot"},
        ]
    }
    out = run_engine(ops)
    ev = out['events']

    assert ev[0] == {"type": "placed", "trader": "A", "order_id": 0,
                     "side": "BUY", "price": 10000, "remaining": 5}
    assert ev[1] == {"type": "fill", "maker": "A", "taker": "B",
                     "price": 10000, "volume": 5,
                     "maker_fee": -5, "taker_fee": 10}
    assert ev[2] == {"type": "placed", "trader": "B", "order_id": 0,
                     "side": "SELL", "price": 9900, "remaining": 3}
    assert ev[3] == {"type": "snapshot", "bids": [], "asks": [[9900, 3]]}

    assert out['accounts']['A'] == {"position": 5, "balance": -49995,
                                    "total_fees": -5}
    assert out['accounts']['B'] == {"position": -5, "balance": 49990,
                                    "total_fees": 10}


def test_price_time_priority():
    """Two buys at same price: first inserted matches first (FIFO)."""
    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "A", "order_id": 0, "side": "BUY",
             "price": 10000, "volume": 10, "lifespan": "GFD"},
            {"type": "insert", "trader": "B", "order_id": 0, "side": "BUY",
             "price": 10000, "volume": 10, "lifespan": "GFD"},
            {"type": "insert", "trader": "C", "order_id": 0, "side": "SELL",
             "price": 10000, "volume": 15, "lifespan": "GFD"},
            {"type": "snapshot"},
        ]
    }
    out = run_engine(ops)
    ev = out['events']

    assert ev[0]['type'] == 'placed' and ev[0]['trader'] == 'A'
    assert ev[1]['type'] == 'placed' and ev[1]['trader'] == 'B'

    assert ev[2] == {"type": "fill", "maker": "A", "taker": "C",
                     "price": 10000, "volume": 10,
                     "maker_fee": -10, "taker_fee": 20}
    assert ev[3] == {"type": "fill", "maker": "B", "taker": "C",
                     "price": 10000, "volume": 5,
                     "maker_fee": -5, "taker_fee": 10}

    assert ev[4] == {"type": "snapshot", "bids": [[10000, 5]], "asks": []}

    assert out['accounts']['A'] == {"position": 10, "balance": -99990,
                                    "total_fees": -10}
    assert out['accounts']['B'] == {"position": 5, "balance": -49995,
                                    "total_fees": -5}
    assert out['accounts']['C'] == {"position": -15, "balance": 149970,
                                    "total_fees": 30}


def test_multi_level_sweep():
    """Taker sweeps across multiple price levels."""
    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "A", "order_id": 0, "side": "BUY",
             "price": 10000, "volume": 10, "lifespan": "GFD"},
            {"type": "insert", "trader": "A", "order_id": 1, "side": "BUY",
             "price": 9800, "volume": 15, "lifespan": "GFD"},
            {"type": "insert", "trader": "B", "order_id": 0, "side": "SELL",
             "price": 9800, "volume": 18, "lifespan": "GFD"},
            {"type": "snapshot"},
        ]
    }
    out = run_engine(ops)
    ev = out['events']

    assert ev[2] == {"type": "fill", "maker": "A", "taker": "B",
                     "price": 10000, "volume": 10,
                     "maker_fee": -10, "taker_fee": 20}
    assert ev[3] == {"type": "fill", "maker": "A", "taker": "B",
                     "price": 9800, "volume": 8,
                     "maker_fee": round(9800 * 8 * -0.0001),
                     "taker_fee": round(9800 * 8 * 0.0002)}

    assert round(9800 * 8 * -0.0001) == -8
    assert round(9800 * 8 * 0.0002) == 16

    assert ev[4] == {"type": "snapshot", "bids": [[9800, 7]], "asks": []}

    assert out['accounts']['A'] == {"position": 18, "balance": -178382,
                                    "total_fees": -18}
    assert out['accounts']['B'] == {"position": -18, "balance": 178364,
                                    "total_fees": 36}


def test_fak_behavior():
    """FAK order: partial fill then cancel, and no-match cancel."""
    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "A", "order_id": 0, "side": "BUY",
             "price": 10000, "volume": 5, "lifespan": "GFD"},
            {"type": "insert", "trader": "B", "order_id": 0, "side": "SELL",
             "price": 9900, "volume": 8, "lifespan": "FAK"},
            {"type": "insert", "trader": "C", "order_id": 0, "side": "BUY",
             "price": 10000, "volume": 10, "lifespan": "FAK"},
            {"type": "snapshot"},
        ]
    }
    out = run_engine(ops)
    ev = out['events']

    assert ev[0]['type'] == 'placed'

    assert ev[1] == {"type": "fill", "maker": "A", "taker": "B",
                     "price": 10000, "volume": 5,
                     "maker_fee": -5, "taker_fee": 10}
    assert ev[2] == {"type": "cancelled", "trader": "B", "order_id": 0,
                     "remaining_cancelled": 3}

    assert ev[3] == {"type": "cancelled", "trader": "C", "order_id": 0,
                     "remaining_cancelled": 10}

    assert ev[4] == {"type": "snapshot", "bids": [], "asks": []}

    assert out['accounts']['C'] == {"position": 0, "balance": 0,
                                    "total_fees": 0}


def test_amend_operations():
    """Amend: normal decrease and edge case (new_volume < filled)."""
    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "A", "order_id": 0, "side": "BUY",
             "price": 10000, "volume": 20, "lifespan": "GFD"},
            {"type": "insert", "trader": "B", "order_id": 0, "side": "SELL",
             "price": 10000, "volume": 8, "lifespan": "GFD"},

            {"type": "amend", "trader": "A", "order_id": 0,
             "new_volume": 15},
            {"type": "snapshot"},

            {"type": "amend", "trader": "A", "order_id": 0, "new_volume": 5},
            {"type": "snapshot"},

            {"type": "amend", "trader": "A", "order_id": 99,
             "new_volume": 1},
            {"type": "snapshot"},
        ]
    }
    out = run_engine(ops)
    ev = out['events']

    assert ev[0]['type'] == 'placed'
    assert ev[1]['type'] == 'fill'

    assert ev[2] == {"type": "amended", "trader": "A", "order_id": 0,
                     "volume_removed": 5}
    assert ev[3] == {"type": "snapshot", "bids": [[10000, 7]], "asks": []}

    assert ev[4] == {"type": "amended", "trader": "A", "order_id": 0,
                     "volume_removed": 7}
    assert ev[5] == {"type": "snapshot", "bids": [], "asks": []}

    assert ev[6] == {"type": "snapshot", "bids": [], "asks": []}

    assert len(ev) == 7


def test_rejection_rules():
    """Self-cross, active order count, and active volume rejections."""
    ops = {
        "config": STANDARD_CONFIG,
        "operations": [
            {"type": "insert", "trader": "A", "order_id": 0, "side": "BUY",
             "price": 9800, "volume": 5, "lifespan": "GFD"},
            {"type": "insert", "trader": "A", "order_id": 1, "side": "SELL",
             "price": 9700, "volume": 3, "lifespan": "GFD"},

            {"type": "insert", "trader": "Eve", "order_id": 0, "side": "BUY",
             "price": 9000, "volume": 5, "lifespan": "GFD"},
            {"type": "insert", "trader": "Eve", "order_id": 1, "side": "BUY",
             "price": 9100, "volume": 5, "lifespan": "GFD"},
            {"type": "insert", "trader": "Eve", "order_id": 2, "side": "BUY",
             "price": 9200, "volume": 5, "lifespan": "GFD"},
            {"type": "insert", "trader": "Eve", "order_id": 3, "side": "BUY",
             "price": 9300, "volume": 5, "lifespan": "GFD"},
            {"type": "insert", "trader": "Eve", "order_id": 4, "side": "BUY",
             "price": 9400, "volume": 5, "lifespan": "GFD"},
            {"type": "insert", "trader": "Eve", "order_id": 5, "side": "BUY",
             "price": 9500, "volume": 5, "lifespan": "GFD"},

            {"type": "insert", "trader": "Frank", "order_id": 0,
             "side": "BUY", "price": 9000, "volume": 195, "lifespan": "GFD"},
            {"type": "insert", "trader": "Frank", "order_id": 1,
             "side": "BUY", "price": 9100, "volume": 10, "lifespan": "GFD"},
        ]
    }
    out = run_engine(ops)
    ev = out['events']

    assert ev[0] == {"type": "placed", "trader": "A", "order_id": 0,
                     "side": "BUY", "price": 9800, "remaining": 5}
    assert ev[1] == {"type": "reject", "trader": "A", "order_id": 1,
                     "reason": "self-cross"}

    for i in range(5):
        assert ev[2 + i]['type'] == 'placed' and ev[2 + i]['trader'] == 'Eve'
    assert ev[7] == {"type": "reject", "trader": "Eve", "order_id": 5,
                     "reason": "active-order-count"}

    assert ev[8] == {"type": "placed", "trader": "Frank", "order_id": 0,
                     "side": "BUY", "price": 9000, "remaining": 195}
    assert ev[9] == {"type": "reject", "trader": "Frank", "order_id": 1,
                     "reason": "active-volume"}


def test_rejection_priority():
    """Rejection checks applied in fixed order: count, volume, self-cross.
    When multiple conditions apply, the first checked one wins."""
    ops = {
        "config": {
            "maker_fee": -0.0001,
            "taker_fee": 0.0002,
            "tick_size": 100,
            "position_limit": 100,
            "active_order_count_limit": 2,
            "active_volume_limit": 50
        },
        "operations": [
            {"type": "insert", "trader": "A", "order_id": 0, "side": "BUY",
             "price": 10000, "volume": 30, "lifespan": "GFD"},
            {"type": "insert", "trader": "A", "order_id": 1, "side": "BUY",
             "price": 9800, "volume": 15, "lifespan": "GFD"},

            {"type": "insert", "trader": "A", "order_id": 2, "side": "SELL",
             "price": 9700, "volume": 10, "lifespan": "GFD"},

            {"type": "cancel", "trader": "A", "order_id": 1},

            {"type": "insert", "trader": "A", "order_id": 3, "side": "SELL",
             "price": 9900, "volume": 40, "lifespan": "GFD"},

            {"type": "cancel", "trader": "A", "order_id": 0},

            {"type": "insert", "trader": "A", "order_id": 4, "side": "SELL",
             "price": 10000, "volume": 20, "lifespan": "GFD"},

            {"type": "insert", "trader": "A", "order_id": 5, "side": "BUY",
             "price": 10100, "volume": 10, "lifespan": "GFD"},
        ]
    }
    out = run_engine(ops)
    ev = out['events']

    assert ev[0] == {"type": "placed", "trader": "A", "order_id": 0,
                     "side": "BUY", "price": 10000, "remaining": 30}
    assert ev[1] == {"type": "placed", "trader": "A", "order_id": 1,
                     "side": "BUY", "price": 9800, "remaining": 15}

    assert ev[2] == {"type": "reject", "trader": "A", "order_id": 2,
                     "reason": "active-order-count"}

    assert ev[3] == {"type": "cancelled", "trader": "A", "order_id": 1,
                     "remaining_cancelled": 15}

    assert ev[4] == {"type": "reject", "trader": "A", "order_id": 3,
                     "reason": "active-volume"}

    assert ev[5] == {"type": "cancelled", "trader": "A", "order_id": 0,
                     "remaining_cancelled": 30}

    assert ev[6] == {"type": "placed", "trader": "A", "order_id": 4,
                     "side": "SELL", "price": 10000, "remaining": 20}

    assert ev[7] == {"type": "reject", "trader": "A", "order_id": 5,
                     "reason": "self-cross"}


def test_position_breach_maker():
    """Maker position breach: cascading cancellation of remaining orders."""
    ops = {
        "config": STANDARD_CONFIG,
        "operations": [
            {"type": "insert", "trader": "Gina", "order_id": 0,
             "side": "BUY", "price": 10000, "volume": 30, "lifespan": "GFD"},
            {"type": "insert", "trader": "Gina", "order_id": 1,
             "side": "BUY", "price": 9600, "volume": 25, "lifespan": "GFD"},
            {"type": "insert", "trader": "Gina", "order_id": 2,
             "side": "SELL", "price": 10500, "volume": 5, "lifespan": "GFD"},

            {"type": "insert", "trader": "Hank", "order_id": 0,
             "side": "SELL", "price": 10000, "volume": 30, "lifespan": "GFD"},

            {"type": "insert", "trader": "Ivan", "order_id": 0,
             "side": "SELL", "price": 9600, "volume": 25, "lifespan": "GFD"},

            {"type": "snapshot"},
        ]
    }
    out = run_engine(ops)
    ev = out['events']

    assert ev[0]['type'] == 'placed' and ev[0]['trader'] == 'Gina'
    assert ev[1]['type'] == 'placed' and ev[1]['trader'] == 'Gina'
    assert ev[2]['type'] == 'placed' and ev[2]['trader'] == 'Gina'

    assert ev[3] == {"type": "fill", "maker": "Gina", "taker": "Hank",
                     "price": 10000, "volume": 30,
                     "maker_fee": -30, "taker_fee": 60}

    assert ev[4] == {"type": "fill", "maker": "Gina", "taker": "Ivan",
                     "price": 9600, "volume": 25,
                     "maker_fee": -24, "taker_fee": 48}

    assert ev[5] == {"type": "breach", "trader": "Gina"}

    assert ev[6] == {"type": "cancelled", "trader": "Gina", "order_id": 2,
                     "remaining_cancelled": 5}

    assert ev[7] == {"type": "snapshot", "bids": [], "asks": []}

    assert out['accounts']['Gina'] == {"position": 55,
                                       "balance": -539946, "total_fees": -54}
    assert out['accounts']['Hank'] == {"position": -30,
                                       "balance": 299940, "total_fees": 60}
    assert out['accounts']['Ivan'] == {"position": -25,
                                       "balance": 239952, "total_fees": 48}


def test_position_breach_taker():
    """Taker position breach: taker's existing orders cancelled."""
    ops = {
        "config": STANDARD_CONFIG,
        "operations": [
            {"type": "insert", "trader": "X", "order_id": 0, "side": "BUY",
             "price": 10000, "volume": 45, "lifespan": "GFD"},
            {"type": "insert", "trader": "Y", "order_id": 0, "side": "SELL",
             "price": 10000, "volume": 45, "lifespan": "GFD"},

            {"type": "insert", "trader": "Z", "order_id": 0, "side": "SELL",
             "price": 9800, "volume": 20, "lifespan": "GFD"},

            {"type": "insert", "trader": "X", "order_id": 1, "side": "BUY",
             "price": 9500, "volume": 5, "lifespan": "GFD"},

            {"type": "insert", "trader": "X", "order_id": 2, "side": "BUY",
             "price": 9800, "volume": 10, "lifespan": "GFD"},

            {"type": "snapshot"},
        ]
    }
    out = run_engine(ops)
    ev = out['events']

    assert ev[0]['type'] == 'placed' and ev[0]['trader'] == 'X'
    assert ev[1] == {"type": "fill", "maker": "X", "taker": "Y",
                     "price": 10000, "volume": 45,
                     "maker_fee": -45, "taker_fee": 90}

    assert ev[2] == {"type": "placed", "trader": "Z", "order_id": 0,
                     "side": "SELL", "price": 9800, "remaining": 20}
    assert ev[3] == {"type": "placed", "trader": "X", "order_id": 1,
                     "side": "BUY", "price": 9500, "remaining": 5}

    assert ev[4] == {"type": "fill", "maker": "Z", "taker": "X",
                     "price": 9800, "volume": 10,
                     "maker_fee": -10, "taker_fee": 20}

    assert ev[5] == {"type": "breach", "trader": "X"}

    assert ev[6] == {"type": "cancelled", "trader": "X", "order_id": 1,
                     "remaining_cancelled": 5}

    assert ev[7] == {"type": "snapshot", "bids": [], "asks": [[9800, 10]]}

    assert out['accounts']['X'] == {"position": 55, "balance": -547975,
                                    "total_fees": -25}
    assert out['accounts']['Z'] == {"position": -10, "balance": 98010,
                                    "total_fees": -10}


def test_mutual_breach():
    """Both maker and taker breach position limit from the same fill."""
    ops = {
        "config": {
            "maker_fee": -0.0001,
            "taker_fee": 0.0002,
            "tick_size": 100,
            "position_limit": 10,
            "active_order_count_limit": 10,
            "active_volume_limit": 200
        },
        "operations": [
            {"type": "insert", "trader": "M", "order_id": 0, "side": "BUY",
             "price": 10000, "volume": 15, "lifespan": "GFD"},
            {"type": "insert", "trader": "T", "order_id": 0, "side": "SELL",
             "price": 12000, "volume": 5, "lifespan": "GFD"},
            {"type": "insert", "trader": "T", "order_id": 1, "side": "SELL",
             "price": 10000, "volume": 15, "lifespan": "GFD"},
            {"type": "snapshot"},
        ]
    }
    out = run_engine(ops)
    ev = out['events']

    assert ev[0] == {"type": "placed", "trader": "M", "order_id": 0,
                     "side": "BUY", "price": 10000, "remaining": 15}
    assert ev[1] == {"type": "placed", "trader": "T", "order_id": 0,
                     "side": "SELL", "price": 12000, "remaining": 5}

    assert ev[2] == {"type": "fill", "maker": "M", "taker": "T",
                     "price": 10000, "volume": 15,
                     "maker_fee": -15, "taker_fee": 30}

    assert ev[3] == {"type": "breach", "trader": "M"}
    assert ev[4] == {"type": "breach", "trader": "T"}
    assert ev[5] == {"type": "cancelled", "trader": "T", "order_id": 0,
                     "remaining_cancelled": 5}

    assert ev[6] == {"type": "snapshot", "bids": [], "asks": []}

    assert out['accounts']['M'] == {"position": 15, "balance": -149985,
                                    "total_fees": -15}
    assert out['accounts']['T'] == {"position": -15, "balance": 149970,
                                    "total_fees": 30}


def test_cancel_operation():
    """Cancel removes order from book, produces correct event."""
    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "A", "order_id": 0, "side": "BUY",
             "price": 10000, "volume": 15, "lifespan": "GFD"},
            {"type": "insert", "trader": "A", "order_id": 1, "side": "BUY",
             "price": 9800, "volume": 10, "lifespan": "GFD"},
            {"type": "snapshot"},
            {"type": "cancel", "trader": "A", "order_id": 0},
            {"type": "snapshot"},
            {"type": "cancel", "trader": "A", "order_id": 99},
            {"type": "snapshot"},
        ]
    }
    out = run_engine(ops)
    ev = out['events']

    assert ev[0]['type'] == 'placed'
    assert ev[1]['type'] == 'placed'
    assert ev[2] == {"type": "snapshot",
                     "bids": [[10000, 15], [9800, 10]], "asks": []}

    assert ev[3] == {"type": "cancelled", "trader": "A", "order_id": 0,
                     "remaining_cancelled": 15}
    assert ev[4] == {"type": "snapshot", "bids": [[9800, 10]], "asks": []}

    assert ev[5] == {"type": "snapshot", "bids": [[9800, 10]], "asks": []}
    assert len(ev) == 6


def test_comprehensive_scenario():
    """Full integrated scenario: 9 traders, all features exercised."""
    ops = {
        "config": STANDARD_CONFIG,
        "operations": [
            {"type": "insert", "trader": "Alice", "order_id": 0,
             "side": "BUY", "price": 10000, "volume": 20, "lifespan": "GFD"},
            {"type": "insert", "trader": "Alice", "order_id": 1,
             "side": "BUY", "price": 9800, "volume": 15, "lifespan": "GFD"},
            {"type": "insert", "trader": "Bob", "order_id": 0,
             "side": "SELL", "price": 10000, "volume": 10, "lifespan": "GFD"},
            {"type": "snapshot"},

            {"type": "insert", "trader": "Carol", "order_id": 0,
             "side": "SELL", "price": 9800, "volume": 18, "lifespan": "FAK"},
            {"type": "snapshot"},

            {"type": "insert", "trader": "Alice", "order_id": 2,
             "side": "SELL", "price": 9700, "volume": 5, "lifespan": "GFD"},

            {"type": "amend", "trader": "Alice", "order_id": 1,
             "new_volume": 10},
            {"type": "snapshot"},

            {"type": "cancel", "trader": "Alice", "order_id": 1},
            {"type": "snapshot"},

            {"type": "insert", "trader": "Dave", "order_id": 0,
             "side": "BUY", "price": 10000, "volume": 10, "lifespan": "FAK"},

            {"type": "insert", "trader": "Eve", "order_id": 0,
             "side": "BUY", "price": 9000, "volume": 5, "lifespan": "GFD"},
            {"type": "insert", "trader": "Eve", "order_id": 1,
             "side": "BUY", "price": 9100, "volume": 5, "lifespan": "GFD"},
            {"type": "insert", "trader": "Eve", "order_id": 2,
             "side": "BUY", "price": 9200, "volume": 5, "lifespan": "GFD"},
            {"type": "insert", "trader": "Eve", "order_id": 3,
             "side": "BUY", "price": 9300, "volume": 5, "lifespan": "GFD"},
            {"type": "insert", "trader": "Eve", "order_id": 4,
             "side": "BUY", "price": 9400, "volume": 5, "lifespan": "GFD"},
            {"type": "insert", "trader": "Eve", "order_id": 5,
             "side": "BUY", "price": 9500, "volume": 5, "lifespan": "GFD"},

            {"type": "insert", "trader": "Frank", "order_id": 0,
             "side": "BUY", "price": 9000, "volume": 195, "lifespan": "GFD"},
            {"type": "insert", "trader": "Frank", "order_id": 1,
             "side": "BUY", "price": 9100, "volume": 10, "lifespan": "GFD"},

            {"type": "insert", "trader": "Gina", "order_id": 0,
             "side": "BUY", "price": 10000, "volume": 30, "lifespan": "GFD"},
            {"type": "insert", "trader": "Gina", "order_id": 1,
             "side": "BUY", "price": 9600, "volume": 25, "lifespan": "GFD"},
            {"type": "insert", "trader": "Gina", "order_id": 2,
             "side": "SELL", "price": 10500, "volume": 5, "lifespan": "GFD"},
            {"type": "insert", "trader": "Hank", "order_id": 0,
             "side": "SELL", "price": 10000, "volume": 30, "lifespan": "GFD"},
            {"type": "insert", "trader": "Ivan", "order_id": 0,
             "side": "SELL", "price": 9600, "volume": 25, "lifespan": "GFD"},

            {"type": "snapshot"},
        ]
    }
    out = run_engine(ops)
    ev = out['events']

    assert ev[0] == {"type": "placed", "trader": "Alice", "order_id": 0,
                     "side": "BUY", "price": 10000, "remaining": 20}
    assert ev[1] == {"type": "placed", "trader": "Alice", "order_id": 1,
                     "side": "BUY", "price": 9800, "remaining": 15}
    assert ev[2] == {"type": "fill", "maker": "Alice", "taker": "Bob",
                     "price": 10000, "volume": 10,
                     "maker_fee": -10, "taker_fee": 20}
    assert ev[3] == {"type": "snapshot",
                     "bids": [[10000, 10], [9800, 15]], "asks": []}

    assert ev[4] == {"type": "fill", "maker": "Alice", "taker": "Carol",
                     "price": 10000, "volume": 10,
                     "maker_fee": -10, "taker_fee": 20}
    assert ev[5] == {"type": "fill", "maker": "Alice", "taker": "Carol",
                     "price": 9800, "volume": 8,
                     "maker_fee": -8, "taker_fee": 16}
    assert ev[6] == {"type": "snapshot", "bids": [[9800, 7]], "asks": []}

    assert ev[7] == {"type": "reject", "trader": "Alice", "order_id": 2,
                     "reason": "self-cross"}

    assert ev[8] == {"type": "amended", "trader": "Alice", "order_id": 1,
                     "volume_removed": 5}
    assert ev[9] == {"type": "snapshot", "bids": [[9800, 2]], "asks": []}

    assert ev[10] == {"type": "cancelled", "trader": "Alice", "order_id": 1,
                      "remaining_cancelled": 2}
    assert ev[11] == {"type": "snapshot", "bids": [], "asks": []}

    assert ev[12] == {"type": "cancelled", "trader": "Dave", "order_id": 0,
                      "remaining_cancelled": 10}

    for i in range(5):
        assert ev[13 + i]['type'] == 'placed' and \
            ev[13 + i]['trader'] == 'Eve'
    assert ev[18] == {"type": "reject", "trader": "Eve", "order_id": 5,
                      "reason": "active-order-count"}

    assert ev[19] == {"type": "placed", "trader": "Frank", "order_id": 0,
                      "side": "BUY", "price": 9000, "remaining": 195}
    assert ev[20] == {"type": "reject", "trader": "Frank", "order_id": 1,
                      "reason": "active-volume"}

    assert ev[21] == {"type": "placed", "trader": "Gina", "order_id": 0,
                      "side": "BUY", "price": 10000, "remaining": 30}
    assert ev[22] == {"type": "placed", "trader": "Gina", "order_id": 1,
                      "side": "BUY", "price": 9600, "remaining": 25}
    assert ev[23] == {"type": "placed", "trader": "Gina", "order_id": 2,
                      "side": "SELL", "price": 10500, "remaining": 5}

    assert ev[24] == {"type": "fill", "maker": "Gina", "taker": "Hank",
                      "price": 10000, "volume": 30,
                      "maker_fee": -30, "taker_fee": 60}
    assert ev[25] == {"type": "fill", "maker": "Gina", "taker": "Ivan",
                      "price": 9600, "volume": 25,
                      "maker_fee": -24, "taker_fee": 48}
    assert ev[26] == {"type": "breach", "trader": "Gina"}
    assert ev[27] == {"type": "cancelled", "trader": "Gina", "order_id": 2,
                      "remaining_cancelled": 5}

    assert ev[28] == {"type": "snapshot",
                      "bids": [[9400, 5], [9300, 5], [9200, 5],
                               [9100, 5], [9000, 200]],
                      "asks": []}

    assert len(ev) == 29

    accts = out['accounts']
    assert accts['Alice'] == {"position": 28, "balance": -278372,
                              "total_fees": -28}
    assert accts['Bob'] == {"position": -10, "balance": 99980,
                            "total_fees": 20}
    assert accts['Carol'] == {"position": -18, "balance": 178364,
                              "total_fees": 36}
    assert accts['Dave'] == {"position": 0, "balance": 0, "total_fees": 0}
    assert accts['Eve'] == {"position": 0, "balance": 0, "total_fees": 0}
    assert accts['Frank'] == {"position": 0, "balance": 0, "total_fees": 0}
    assert accts['Gina'] == {"position": 55, "balance": -539946,
                             "total_fees": -54}
    assert accts['Hank'] == {"position": -30, "balance": 299940,
                             "total_fees": 60}
    assert accts['Ivan'] == {"position": -25, "balance": 239952,
                             "total_fees": 48}


# ========== Binary wire protocol tests ==========


def test_binary_mode_matching():
    """Binary mode produces identical output to JSON mode for basic match."""
    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "Alpha", "order_id": 0,
             "side": "BUY", "price": 10000, "volume": 20, "lifespan": "GFD"},
            {"type": "insert", "trader": "Beta", "order_id": 0,
             "side": "SELL", "price": 10000, "volume": 10, "lifespan": "GFD"},
            {"type": "snapshot"},
        ]
    }
    json_out = run_engine(ops, binary_mode=False)
    bin_out = run_engine(ops, binary_mode=True)
    assert json_out == bin_out


def test_binary_mode_all_operations():
    """Binary mode handles insert, amend, cancel, snapshot, and FAK."""
    ops = {
        "config": STANDARD_CONFIG,
        "operations": [
            {"type": "insert", "trader": "Alice", "order_id": 0,
             "side": "BUY", "price": 10000, "volume": 20, "lifespan": "GFD"},
            {"type": "insert", "trader": "Bob", "order_id": 0,
             "side": "SELL", "price": 10000, "volume": 10, "lifespan": "GFD"},
            {"type": "amend", "trader": "Alice", "order_id": 0,
             "new_volume": 15},
            {"type": "snapshot"},
            {"type": "cancel", "trader": "Alice", "order_id": 0},
            {"type": "insert", "trader": "Carol", "order_id": 0,
             "side": "SELL", "price": 9800, "volume": 5, "lifespan": "FAK"},
            {"type": "snapshot"},
        ]
    }
    json_out = run_engine(ops, binary_mode=False)
    bin_out = run_engine(ops, binary_mode=True)
    assert json_out == bin_out

    ev = bin_out['events']
    assert ev[0]['type'] == 'placed'
    assert ev[1]['type'] == 'fill'
    assert ev[2]['type'] == 'amended'
    assert ev[3]['type'] == 'snapshot'
    assert ev[4]['type'] == 'cancelled'
    assert ev[5]['type'] == 'cancelled'  # FAK Carol no-match
    assert ev[6]['type'] == 'snapshot'


def test_binary_mode_breach_and_rejection():
    """Binary mode correctly produces breach and reject events."""
    ops = {
        "config": {
            "maker_fee": -0.0001,
            "taker_fee": 0.0002,
            "tick_size": 100,
            "position_limit": 10,
            "active_order_count_limit": 10,
            "active_volume_limit": 200
        },
        "operations": [
            {"type": "insert", "trader": "Maker", "order_id": 0,
             "side": "BUY", "price": 10000, "volume": 15, "lifespan": "GFD"},
            {"type": "insert", "trader": "Taker", "order_id": 0,
             "side": "SELL", "price": 10000, "volume": 15, "lifespan": "GFD"},
            {"type": "snapshot"},
        ]
    }
    json_out = run_engine(ops, binary_mode=False)
    bin_out = run_engine(ops, binary_mode=True)
    assert json_out == bin_out

    ev = bin_out['events']
    breach_events = [e for e in ev if e['type'] == 'breach']
    assert len(breach_events) == 2
    assert breach_events[0]['trader'] == 'Maker'
    assert breach_events[1]['trader'] == 'Taker'


# ========== TCP socket server tests ==========


def test_socket_server_basic():
    """Socket server accepts connection, processes RTGX, returns JSON."""
    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "SA", "order_id": 0, "side": "BUY",
             "price": 10000, "volume": 20, "lifespan": "GFD"},
            {"type": "insert", "trader": "SB", "order_id": 0, "side": "SELL",
             "price": 10000, "volume": 10, "lifespan": "GFD"},
        ]
    }
    result = run_engine_via_socket(ops)

    assert len(result['events']) == 2
    assert result['events'][0]['type'] == 'placed'
    assert result['events'][1]['type'] == 'fill'
    assert result['events'][1]['maker'] == 'SA'
    assert result['events'][1]['taker'] == 'SB'
    assert result['events'][1]['volume'] == 10

    assert result['accounts']['SA'] == {
        "position": 10, "balance": -99990, "total_fees": -10}
    assert result['accounts']['SB'] == {
        "position": -10, "balance": 99980, "total_fees": 20}


def test_socket_server_multi_trader():
    """Socket server handles complex scenario with multiple traders."""
    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "NetA", "order_id": 0,
             "side": "BUY", "price": 10000, "volume": 10, "lifespan": "GFD"},
            {"type": "insert", "trader": "NetB", "order_id": 0,
             "side": "BUY", "price": 10000, "volume": 10, "lifespan": "GFD"},
            {"type": "insert", "trader": "NetC", "order_id": 0,
             "side": "SELL", "price": 10000, "volume": 15, "lifespan": "GFD"},
            {"type": "snapshot"},
        ]
    }
    sock_out = run_engine_via_socket(ops)
    json_out = run_engine(ops, binary_mode=False)
    assert sock_out == json_out


def test_socket_server_with_audit():
    """Socket server with --audit writes correct SQLite database."""
    db_path = '/app/_test_sock_audit.db'
    if os.path.exists(db_path):
        os.remove(db_path)

    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "AudA", "order_id": 0,
             "side": "BUY", "price": 10000, "volume": 20, "lifespan": "GFD"},
            {"type": "insert", "trader": "AudB", "order_id": 0,
             "side": "SELL", "price": 10000, "volume": 10, "lifespan": "GFD"},
        ]
    }
    result = run_engine_via_socket(ops, extra_args=['--audit', db_path])

    assert result['events'][0]['type'] == 'placed'
    assert result['events'][1]['type'] == 'fill'

    # Verify audit database was created and populated
    assert os.path.exists(db_path), "Audit database not created in serve mode"
    conn = sqlite3.connect(db_path)
    events = conn.execute(
        "SELECT seq, type FROM events ORDER BY seq").fetchall()
    assert len(events) == 2
    assert events[0] == (0, 'placed')
    assert events[1] == (1, 'fill')

    accounts = conn.execute(
        "SELECT trader, position FROM accounts ORDER BY trader").fetchall()
    assert len(accounts) == 2
    assert accounts[0] == ('AudA', 10)
    assert accounts[1] == ('AudB', -10)
    conn.close()


# ========== SQLite audit trail tests ==========


def test_audit_json_mode():
    """Running engine with --audit in JSON mode creates correct SQLite DB."""
    db_path = '/app/_test_audit_json.db'
    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "Ax", "order_id": 0, "side": "BUY",
             "price": 10000, "volume": 20, "lifespan": "GFD"},
            {"type": "insert", "trader": "Bx", "order_id": 0, "side": "SELL",
             "price": 10000, "volume": 10, "lifespan": "GFD"},
            {"type": "snapshot"},
        ]
    }
    out = run_engine_with_audit(ops, db_path)

    assert os.path.exists(db_path)
    conn = sqlite3.connect(db_path)

    # Check events table
    events = conn.execute(
        "SELECT seq, type, data FROM events ORDER BY seq").fetchall()
    assert len(events) == 3
    assert events[0][0] == 0 and events[0][1] == 'placed'
    assert events[1][0] == 1 and events[1][1] == 'fill'
    assert events[2][0] == 2 and events[2][1] == 'snapshot'

    # Check accounts table
    accounts = conn.execute(
        "SELECT trader, position, balance, total_fees "
        "FROM accounts ORDER BY trader").fetchall()
    assert len(accounts) == 2
    assert accounts[0] == ('Ax', 10, -99990, -10)
    assert accounts[1] == ('Bx', -10, 99980, 20)

    conn.close()


def test_audit_schema_columns():
    """Audit database has exact table and column structure."""
    db_path = '/app/_test_audit_schema.db'
    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "SchA", "order_id": 0,
             "side": "BUY", "price": 10000, "volume": 5, "lifespan": "GFD"},
        ]
    }
    run_engine_with_audit(ops, db_path)

    conn = sqlite3.connect(db_path)

    # Verify events table columns
    ev_info = conn.execute("PRAGMA table_info(events)").fetchall()
    ev_cols = {row[1]: row[2] for row in ev_info}
    assert 'seq' in ev_cols
    assert 'type' in ev_cols
    assert 'data' in ev_cols
    assert ev_cols['seq'].upper() == 'INTEGER'
    assert ev_cols['type'].upper() == 'TEXT'
    assert ev_cols['data'].upper() == 'TEXT'

    # Verify accounts table columns
    acct_info = conn.execute("PRAGMA table_info(accounts)").fetchall()
    acct_cols = {row[1]: row[2] for row in acct_info}
    assert 'trader' in acct_cols
    assert 'position' in acct_cols
    assert 'balance' in acct_cols
    assert 'total_fees' in acct_cols

    conn.close()


def test_audit_event_data_is_json():
    """Each event's data column contains valid JSON matching the event."""
    db_path = '/app/_test_audit_data.db'
    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "Jx", "order_id": 0, "side": "BUY",
             "price": 10000, "volume": 20, "lifespan": "GFD"},
            {"type": "insert", "trader": "Kx", "order_id": 0, "side": "SELL",
             "price": 10000, "volume": 10, "lifespan": "GFD"},
            {"type": "snapshot"},
        ]
    }
    out = run_engine_with_audit(ops, db_path)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT seq, type, data FROM events ORDER BY seq").fetchall()

    for seq, evt_type, data_str in rows:
        parsed = json.loads(data_str)
        assert parsed['type'] == evt_type
        # Verify the parsed event matches the engine output
        assert parsed == out['events'][seq]

    conn.close()


# ========== Makefile tests ==========


def test_makefile_has_all_targets():
    """Makefile exists with all required targets."""
    assert os.path.exists('/app/Makefile'), \
        "Makefile not found at /app/Makefile"
    with open('/app/Makefile') as f:
        content = f.read()
    for target in ('process', 'replay', 'validate', 'serve',
                   'audit-summary', 'filter-events'):
        assert target in content, \
            f"Makefile missing '{target}' target"


def test_makefile_process_target():
    """make process target runs the engine in JSON mode."""
    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "MkA", "order_id": 0,
             "side": "BUY", "price": 10000, "volume": 10, "lifespan": "GFD"},
            {"type": "snapshot"},
        ]
    }
    with open('/app/_mk_proc_in.json', 'w') as f:
        json.dump(ops, f)
    result = subprocess.run(
        ['make', '-f', '/app/Makefile', 'process',
         'INPUT=/app/_mk_proc_in.json', 'OUTPUT=/app/_mk_proc_out.json'],
        capture_output=True, text=True, cwd='/app', timeout=30
    )
    assert result.returncode == 0, \
        f"make process failed:\n{result.stderr}"
    with open('/app/_mk_proc_out.json') as f:
        out = json.load(f)
    assert out['events'][0] == {"type": "placed", "trader": "MkA",
                                "order_id": 0, "side": "BUY",
                                "price": 10000, "remaining": 10}


def test_makefile_replay_target():
    """make replay target processes binary input."""
    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "MkB", "order_id": 0,
             "side": "BUY", "price": 10000, "volume": 10, "lifespan": "GFD"},
            {"type": "snapshot"},
        ]
    }
    write_binary_file('/app/_mk_replay_in.bin', ops)
    result = subprocess.run(
        ['make', '-f', '/app/Makefile', 'replay',
         'INPUT=/app/_mk_replay_in.bin', 'OUTPUT=/app/_mk_replay_out.json'],
        capture_output=True, text=True, cwd='/app', timeout=30
    )
    assert result.returncode == 0, \
        f"make replay failed:\n{result.stderr}"
    with open('/app/_mk_replay_out.json') as f:
        out = json.load(f)
    assert out['events'][0] == {"type": "placed", "trader": "MkB",
                                "order_id": 0, "side": "BUY",
                                "price": 10000, "remaining": 10}


def test_makefile_validate_target():
    """make validate succeeds against provided scenarios."""
    result = subprocess.run(
        ['make', '-f', '/app/Makefile', 'validate'],
        capture_output=True, text=True, cwd='/app', timeout=30
    )
    assert result.returncode == 0, \
        f"make validate failed:\n{result.stderr}\n{result.stdout}"


def test_makefile_audit_summary():
    """make audit-summary uses sqlite3 CLI to produce tab-separated output."""
    db_path = '/app/_mk_audit_summary.db'
    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "Alpha", "order_id": 0,
             "side": "BUY", "price": 10000, "volume": 20, "lifespan": "GFD"},
            {"type": "insert", "trader": "Beta", "order_id": 0,
             "side": "SELL", "price": 10000, "volume": 10, "lifespan": "GFD"},
            {"type": "snapshot"},
        ]
    }
    run_engine_with_audit(ops, db_path)

    result = subprocess.run(
        ['make', '-f', '/app/Makefile', 'audit-summary',
         f'AUDIT_DB={db_path}'],
        capture_output=True, text=True, cwd='/app', timeout=30
    )
    assert result.returncode == 0, \
        f"make audit-summary failed:\n{result.stderr}"

    lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
    assert len(lines) >= 5, \
        f"Expected at least 5 output lines, got {len(lines)}: {lines}"

    # First line: total count
    parts = lines[0].split('\t')
    assert parts[0] == 'total'
    assert parts[1] == '3'

    # Next lines: per-type counts sorted alphabetically
    type_lines = lines[1:4]
    type_data = [l.split('\t') for l in type_lines]
    assert type_data[0][0] == 'fill' and type_data[0][1] == '1'
    assert type_data[1][0] == 'placed' and type_data[1][1] == '1'
    assert type_data[2][0] == 'snapshot' and type_data[2][1] == '1'

    # Remaining: per-trader accounts sorted alphabetically
    acct_lines = lines[4:]
    assert len(acct_lines) == 2
    a_parts = acct_lines[0].split('\t')
    assert a_parts[0] == 'Alpha'
    assert a_parts[1] == '10'
    assert a_parts[2] == '-99990'
    assert a_parts[3] == '-10'

    b_parts = acct_lines[1].split('\t')
    assert b_parts[0] == 'Beta'
    assert b_parts[1] == '-10'
    assert b_parts[2] == '99980'
    assert b_parts[3] == '20'


def test_makefile_filter_events():
    """make filter-events uses jq to filter events by type."""
    ops = {
        "config": {**STANDARD_CONFIG, "position_limit": 100},
        "operations": [
            {"type": "insert", "trader": "FltA", "order_id": 0,
             "side": "BUY", "price": 10000, "volume": 20, "lifespan": "GFD"},
            {"type": "insert", "trader": "FltB", "order_id": 0,
             "side": "SELL", "price": 10000, "volume": 10, "lifespan": "GFD"},
            {"type": "snapshot"},
        ]
    }
    in_path = '/app/_mk_filter_in.json'
    out_path = '/app/_mk_filter_out.json'
    with open(in_path, 'w') as f:
        json.dump(ops, f)
    subprocess.run(
        ['python3', '/app/engine.py', in_path, out_path],
        check=True, cwd='/app', timeout=30
    )

    # Filter for 'fill' events
    result = subprocess.run(
        ['make', '-f', '/app/Makefile', 'filter-events',
         f'INPUT={out_path}', 'EVENT_TYPE=fill'],
        capture_output=True, text=True, cwd='/app', timeout=30
    )
    assert result.returncode == 0, \
        f"make filter-events failed:\n{result.stderr}"

    filtered = json.loads(result.stdout)
    assert isinstance(filtered, list)
    assert len(filtered) == 1
    assert filtered[0]['type'] == 'fill'
    assert filtered[0]['maker'] == 'FltA'
    assert filtered[0]['taker'] == 'FltB'

    # Filter for 'snapshot' events
    result2 = subprocess.run(
        ['make', '-f', '/app/Makefile', 'filter-events',
         f'INPUT={out_path}', 'EVENT_TYPE=snapshot'],
        capture_output=True, text=True, cwd='/app', timeout=30
    )
    assert result2.returncode == 0
    filtered2 = json.loads(result2.stdout)
    assert len(filtered2) == 1
    assert filtered2[0]['type'] == 'snapshot'

    # Filter for type with no matches yields empty array
    result3 = subprocess.run(
        ['make', '-f', '/app/Makefile', 'filter-events',
         f'INPUT={out_path}', 'EVENT_TYPE=breach'],
        capture_output=True, text=True, cwd='/app', timeout=30
    )
    assert result3.returncode == 0
    filtered3 = json.loads(result3.stdout)
    assert filtered3 == []
