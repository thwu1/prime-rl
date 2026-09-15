#!/usr/bin/env python3
"""Limit order book matching engine with JSON, binary, validate, serve, and audit modes."""

import json
import socket as socket_mod
import sqlite3
import struct
import sys
from collections import deque
from bisect import insort_left


class Order:
    __slots__ = ('trader', 'order_id', 'side', 'price', 'volume',
                 'remaining', 'lifespan')

    def __init__(self, trader, order_id, side, price, volume, lifespan):
        self.trader = trader
        self.order_id = order_id
        self.side = side
        self.price = price
        self.volume = volume
        self.remaining = volume
        self.lifespan = lifespan


class TraderState:
    __slots__ = ('position', 'balance', 'total_fees', 'active_orders',
                 'active_volume')

    def __init__(self):
        self.position = 0
        self.balance = 0
        self.total_fees = 0
        self.active_orders = {}
        self.active_volume = 0

    def highest_buy_price(self):
        best = None
        for o in self.active_orders.values():
            if o.side == 'BUY' and o.remaining > 0:
                if best is None or o.price > best:
                    best = o.price
        return best

    def lowest_sell_price(self):
        best = None
        for o in self.active_orders.values():
            if o.side == 'SELL' and o.remaining > 0:
                if best is None or o.price < best:
                    best = o.price
        return best


class Engine:
    def __init__(self, config):
        self.maker_fee_rate = config['maker_fee']
        self.taker_fee_rate = config['taker_fee']
        self.position_limit = config['position_limit']
        self.order_count_limit = config['active_order_count_limit']
        self.volume_limit = config['active_volume_limit']

        self.events = []
        self.traders = {}

        self.bid_prices = []
        self.ask_neg_prices = []
        self.levels = {}
        self.level_volumes = {}

    def _get_trader(self, name):
        if name not in self.traders:
            self.traders[name] = TraderState()
        return self.traders[name]

    def process(self, op):
        t = op['type']
        if t == 'insert':
            self._insert(op)
        elif t == 'amend':
            self._amend(op)
        elif t == 'cancel':
            self._cancel(op)
        elif t == 'snapshot':
            self._snapshot()

    def _add_to_book(self, order):
        price = order.price
        if price not in self.levels:
            self.levels[price] = deque()
            self.level_volumes[price] = 0
            if order.side == 'SELL':
                insort_left(self.ask_neg_prices, -price)
            else:
                insort_left(self.bid_prices, price)
        self.levels[price].append(order)
        self.level_volumes[price] += order.remaining

    def _remove_volume(self, price, volume, side):
        self.level_volumes[price] -= volume
        if self.level_volumes[price] == 0:
            del self.levels[price]
            del self.level_volumes[price]
            if side == 'SELL':
                self.ask_neg_prices.remove(-price)
            else:
                self.bid_prices.remove(price)

    def _insert(self, op):
        trader_name = op['trader']
        order_id = op['order_id']
        side = op['side']
        price = op['price']
        volume = op['volume']
        lifespan = op['lifespan']

        ts = self._get_trader(trader_name)

        if len(ts.active_orders) >= self.order_count_limit:
            self.events.append({'type': 'reject', 'trader': trader_name,
                                'order_id': order_id,
                                'reason': 'active-order-count'})
            return

        if ts.active_volume + volume > self.volume_limit:
            self.events.append({'type': 'reject', 'trader': trader_name,
                                'order_id': order_id,
                                'reason': 'active-volume'})
            return

        if side == 'BUY':
            ls = ts.lowest_sell_price()
            if ls is not None and price >= ls:
                self.events.append({'type': 'reject', 'trader': trader_name,
                                    'order_id': order_id,
                                    'reason': 'self-cross'})
                return
        else:
            hb = ts.highest_buy_price()
            if hb is not None and price <= hb:
                self.events.append({'type': 'reject', 'trader': trader_name,
                                    'order_id': order_id,
                                    'reason': 'self-cross'})
                return

        order = Order(trader_name, order_id, side, price, volume, lifespan)

        breached = []
        if side == 'SELL' and self.bid_prices:
            self._match_sell(order, breached)
        elif side == 'BUY' and self.ask_neg_prices:
            self._match_buy(order, breached)

        if order.remaining > 0:
            if lifespan == 'GFD':
                self._add_to_book(order)
                ts.active_orders[order_id] = order
                ts.active_volume += order.remaining
                self.events.append({
                    'type': 'placed', 'trader': trader_name,
                    'order_id': order_id, 'side': side,
                    'price': price, 'remaining': order.remaining
                })
            else:
                self.events.append({
                    'type': 'cancelled', 'trader': trader_name,
                    'order_id': order_id,
                    'remaining_cancelled': order.remaining
                })
                order.remaining = 0

        for bt in breached:
            self.events.append({'type': 'breach', 'trader': bt})
            self._cancel_all(bt)

    def _match_sell(self, order, breached):
        while (order.remaining > 0 and self.bid_prices
               and self.bid_prices[-1] >= order.price):
            best = self.bid_prices[-1]
            self._fill_at_level(order, best, breached)
            if best in self.level_volumes and self.level_volumes[best] == 0:
                del self.levels[best]
                del self.level_volumes[best]
                self.bid_prices.pop()

    def _match_buy(self, order, breached):
        while (order.remaining > 0 and self.ask_neg_prices
               and -self.ask_neg_prices[-1] <= order.price):
            best = -self.ask_neg_prices[-1]
            self._fill_at_level(order, best, breached)
            if best in self.level_volumes and self.level_volumes[best] == 0:
                del self.levels[best]
                del self.level_volumes[best]
                self.ask_neg_prices.pop()

    def _fill_at_level(self, taker, level_price, breached):
        queue = self.levels[level_price]
        total = self.level_volumes[level_price]

        while taker.remaining > 0 and total > 0:
            while queue and queue[0].remaining == 0:
                queue.popleft()
            if not queue:
                break

            passive = queue[0]
            vol = min(taker.remaining, passive.remaining)

            m_fee = round(level_price * vol * self.maker_fee_rate)
            t_fee = round(level_price * vol * self.taker_fee_rate)

            passive.remaining -= vol
            m_ts = self._get_trader(passive.trader)
            if passive.side == 'SELL':
                m_ts.balance += level_price * vol
                m_ts.position -= vol
            else:
                m_ts.balance -= level_price * vol
                m_ts.position += vol
            m_ts.balance -= m_fee
            m_ts.total_fees += m_fee
            m_ts.active_volume -= vol
            if passive.remaining == 0:
                if passive.order_id in m_ts.active_orders:
                    del m_ts.active_orders[passive.order_id]

            taker.remaining -= vol
            t_ts = self._get_trader(taker.trader)
            if taker.side == 'SELL':
                t_ts.balance += level_price * vol
                t_ts.position -= vol
            else:
                t_ts.balance -= level_price * vol
                t_ts.position += vol
            t_ts.balance -= t_fee
            t_ts.total_fees += t_fee

            total -= vol

            self.events.append({
                'type': 'fill',
                'maker': passive.trader,
                'taker': taker.trader,
                'price': level_price,
                'volume': vol,
                'maker_fee': m_fee,
                'taker_fee': t_fee,
            })

            if abs(m_ts.position) > self.position_limit:
                if passive.trader not in breached:
                    breached.append(passive.trader)

        self.level_volumes[level_price] = total

        t_ts = self._get_trader(taker.trader)
        if abs(t_ts.position) > self.position_limit:
            if taker.trader not in breached:
                breached.append(taker.trader)

    def _cancel_all(self, trader_name):
        ts = self._get_trader(trader_name)
        for oid in sorted(ts.active_orders.keys()):
            order = ts.active_orders[oid]
            if order.remaining > 0:
                self._remove_volume(order.price, order.remaining, order.side)
                rem = order.remaining
                order.remaining = 0
                ts.active_volume -= rem
                self.events.append({
                    'type': 'cancelled',
                    'trader': trader_name,
                    'order_id': oid,
                    'remaining_cancelled': rem,
                })
        ts.active_orders.clear()

    def _amend(self, op):
        trader_name = op['trader']
        order_id = op['order_id']
        new_volume = op['new_volume']

        ts = self._get_trader(trader_name)
        if order_id not in ts.active_orders:
            return
        order = ts.active_orders[order_id]
        if order.remaining <= 0:
            return
        if new_volume >= order.volume:
            return

        filled = order.volume - order.remaining
        if new_volume < filled:
            diff = order.remaining
        else:
            diff = order.volume - new_volume

        self._remove_volume(order.price, diff, order.side)
        order.volume -= diff
        order.remaining -= diff
        ts.active_volume -= diff

        if order.remaining == 0:
            del ts.active_orders[order_id]

        self.events.append({
            'type': 'amended',
            'trader': trader_name,
            'order_id': order_id,
            'volume_removed': diff,
        })

    def _cancel(self, op):
        trader_name = op['trader']
        order_id = op['order_id']

        ts = self._get_trader(trader_name)
        if order_id not in ts.active_orders:
            return
        order = ts.active_orders[order_id]
        if order.remaining <= 0:
            return

        rem = order.remaining
        self._remove_volume(order.price, rem, order.side)
        order.remaining = 0
        ts.active_volume -= rem
        del ts.active_orders[order_id]

        self.events.append({
            'type': 'cancelled',
            'trader': trader_name,
            'order_id': order_id,
            'remaining_cancelled': rem,
        })

    def _snapshot(self):
        bids = []
        for p in reversed(self.bid_prices):
            if p in self.level_volumes:
                bids.append([p, self.level_volumes[p]])

        asks = []
        for neg_p in reversed(self.ask_neg_prices):
            p = -neg_p
            if p in self.level_volumes:
                asks.append([p, self.level_volumes[p]])

        self.events.append({'type': 'snapshot', 'bids': bids, 'asks': asks})

    def get_accounts(self):
        result = {}
        for name, ts in self.traders.items():
            result[name] = {
                'position': ts.position,
                'balance': ts.balance,
                'total_fees': ts.total_fees,
            }
        return result


# ---- Binary wire protocol parser ----

_SIDE_MAP = {0: 'SELL', 1: 'BUY'}
_LIFESPAN_MAP = {0: 'FAK', 1: 'GFD'}


def parse_binary_data(data):
    """Parse RTGX binary wire protocol data from raw bytes."""
    offset = 0
    magic = data[offset:offset + 4]
    if magic != b'RTGX':
        raise ValueError(f"Bad magic: {magic!r}, expected b'RTGX'")
    offset += 4

    config_len = struct.unpack('>I', data[offset:offset + 4])[0]
    offset += 4
    config = json.loads(data[offset:offset + config_len].decode('utf-8'))
    offset += config_len

    operations = []
    while offset < len(data):
        tag = data[offset]
        offset += 1

        if tag == 1:  # Insert
            trader = data[offset:offset + 32].split(b'\x00', 1)[0] \
                .decode('utf-8')
            offset += 32
            order_id, side_b, price, volume, lifespan_b = struct.unpack(
                '>IBiIB', data[offset:offset + 14])
            offset += 14
            operations.append({
                'type': 'insert', 'trader': trader,
                'order_id': order_id, 'side': _SIDE_MAP[side_b],
                'price': price, 'volume': volume,
                'lifespan': _LIFESPAN_MAP[lifespan_b],
            })
        elif tag == 2:  # Amend
            trader = data[offset:offset + 32].split(b'\x00', 1)[0] \
                .decode('utf-8')
            offset += 32
            order_id, new_volume = struct.unpack(
                '>II', data[offset:offset + 8])
            offset += 8
            operations.append({
                'type': 'amend', 'trader': trader,
                'order_id': order_id, 'new_volume': new_volume,
            })
        elif tag == 3:  # Cancel
            trader = data[offset:offset + 32].split(b'\x00', 1)[0] \
                .decode('utf-8')
            offset += 32
            order_id = struct.unpack('>I', data[offset:offset + 4])[0]
            offset += 4
            operations.append({
                'type': 'cancel', 'trader': trader,
                'order_id': order_id,
            })
        elif tag == 4:  # Snapshot
            operations.append({'type': 'snapshot'})
        else:
            raise ValueError(f"Unknown message tag: 0x{tag:02x} "
                             f"at offset {offset - 1}")

    return config, operations


def parse_binary(filepath):
    """Parse a RTGX binary wire protocol file."""
    with open(filepath, 'rb') as f:
        data = f.read()
    return parse_binary_data(data)


# ---- Run engine ----

def run_engine_on(config, operations):
    engine = Engine(config)
    for op in operations:
        engine.process(op)
    return {
        'events': engine.events,
        'accounts': engine.get_accounts(),
    }


# ---- SQLite audit trail ----

def write_audit(db_path, output):
    """Write engine output to an SQLite audit database."""
    conn = sqlite3.connect(db_path)
    conn.execute('''CREATE TABLE IF NOT EXISTS events(
        seq INTEGER PRIMARY KEY,
        type TEXT NOT NULL,
        data TEXT NOT NULL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS accounts(
        trader TEXT PRIMARY KEY,
        position INTEGER NOT NULL,
        balance INTEGER NOT NULL,
        total_fees INTEGER NOT NULL
    )''')

    for i, event in enumerate(output['events']):
        conn.execute('INSERT INTO events(seq, type, data) VALUES (?, ?, ?)',
                     (i, event['type'], json.dumps(event)))

    for trader, acct in output['accounts'].items():
        conn.execute(
            'INSERT INTO accounts(trader, position, balance, total_fees) '
            'VALUES (?, ?, ?, ?)',
            (trader, acct['position'], acct['balance'], acct['total_fees']))

    conn.commit()
    conn.close()


# ---- CLI modes ----

def mode_json(input_path, output_path, audit_db=None):
    with open(input_path) as f:
        data = json.load(f)
    output = run_engine_on(data['config'], data['operations'])
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    if audit_db:
        write_audit(audit_db, output)


def mode_binary(input_path, output_path, audit_db=None):
    config, operations = parse_binary(input_path)
    output = run_engine_on(config, operations)
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    if audit_db:
        write_audit(audit_db, output)


def mode_validate(scenario_path):
    with open(scenario_path) as f:
        scenario = json.load(f)

    config = scenario['input']['config']
    operations = scenario['input']['operations']
    expected = scenario['expected_output']

    output = run_engine_on(config, operations)

    if output == expected:
        print(f"PASS: {scenario_path}", file=sys.stderr)
        return True
    else:
        print(f"FAIL: {scenario_path}", file=sys.stderr)
        if len(output['events']) != len(expected['events']):
            print(f"  Events: expected {len(expected['events'])}, "
                  f"got {len(output['events'])}", file=sys.stderr)
        for i, (got, exp) in enumerate(
                zip(output['events'], expected['events'])):
            if got != exp:
                print(f"  Event {i} mismatch:", file=sys.stderr)
                print(f"    expected: {exp}", file=sys.stderr)
                print(f"    got:      {got}", file=sys.stderr)
                break
        if output['accounts'] != expected['accounts']:
            print(f"  Accounts mismatch", file=sys.stderr)
        return False


def mode_serve(host_port, audit_db=None):
    host, port_str = host_port.rsplit(':', 1)
    port = int(port_str)

    srv = socket_mod.socket(socket_mod.AF_INET, socket_mod.SOCK_STREAM)
    srv.setsockopt(socket_mod.SOL_SOCKET, socket_mod.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(1)

    conn, _ = srv.accept()
    data = b''
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk

    config, operations = parse_binary_data(data)
    output = run_engine_on(config, operations)

    if audit_db:
        write_audit(audit_db, output)

    result_bytes = json.dumps(output, indent=2).encode('utf-8')
    conn.sendall(result_bytes)
    conn.close()
    srv.close()


def main():
    args = sys.argv[1:]

    # Extract --audit flag (can appear anywhere in args)
    audit_db = None
    if '--audit' in args:
        idx = args.index('--audit')
        audit_db = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    if not args:
        print("Usage:", file=sys.stderr)
        print("  engine.py [--audit <db>] <input.json> <output.json>",
              file=sys.stderr)
        print("  engine.py --binary [--audit <db>] <input.bin> <output.json>",
              file=sys.stderr)
        print("  engine.py --validate <scenario.json>", file=sys.stderr)
        print("  engine.py --serve [--audit <db>] <host:port>",
              file=sys.stderr)
        sys.exit(1)

    if args[0] == '--validate':
        if len(args) < 2:
            print("Usage: engine.py --validate <scenario.json>",
                  file=sys.stderr)
            sys.exit(1)
        ok = mode_validate(args[1])
        sys.exit(0 if ok else 1)

    if args[0] == '--serve':
        if len(args) < 2:
            print("Usage: engine.py --serve <host:port>", file=sys.stderr)
            sys.exit(1)
        mode_serve(args[1], audit_db)
        return

    if args[0] == '--binary':
        if len(args) < 3:
            print("Usage: engine.py --binary <input.bin> <output.json>",
                  file=sys.stderr)
            sys.exit(1)
        mode_binary(args[1], args[2], audit_db)
    else:
        if len(args) < 2:
            print("Usage: engine.py <input.json> <output.json>",
                  file=sys.stderr)
            sys.exit(1)
        mode_json(args[0], args[1], audit_db)


if __name__ == '__main__':
    main()
