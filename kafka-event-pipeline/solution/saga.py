#!/usr/bin/env python3
"""
Saga orchestrator for order fulfillment.
Steps: validate_order → reserve_inventory → process_payment → confirm_order.
On failure, compensating actions run in reverse.
"""

import json
import sys
import time
import sqlite3
from confluent_kafka import Producer

from config import BOOTSTRAP_SERVERS, SAGA_DB_PATH


# ── Saga steps ───────────────────────────────────────────────────────────

def validate_order(ctx):
    order = ctx['order_event']
    if not order.get('items') or len(order['items']) == 0:
        raise ValueError('Order has no items')
    if order.get('total_amount', 0) <= 0:
        raise ValueError('Invalid order total')
    return {'validated': True}


def compensate_validate(ctx):
    pass


def reserve_inventory(ctx):
    order = ctx['order_event']
    for item in order.get('items', []):
        if item.get('quantity', 0) > 100:
            raise ValueError(
                f"Insufficient inventory for item {item.get('product_id', 'unknown')}"
            )
    return {'reserved': True, 'reservation_id': f"res-{order['order_id']}"}


def compensate_inventory(ctx):
    return {'released': ctx.get('reserve_inventory_result', {}).get('reservation_id')}


def process_payment(ctx):
    order = ctx['order_event']
    total = order.get('total_amount', 0)
    if total > 10000:
        raise ValueError(f'Payment declined for amount {total}')
    return {'payment_id': f"pay-{order['order_id']}", 'amount': total}


def compensate_payment(ctx):
    return {'refunded': ctx.get('process_payment_result', {}).get('payment_id')}


def confirm_order(ctx):
    order = ctx['order_event']
    return {'confirmed': True, 'confirmation_id': f"conf-{order['order_id']}"}


def compensate_confirm(ctx):
    pass


STEPS = [
    ('validate_order', validate_order, compensate_validate),
    ('reserve_inventory', reserve_inventory, compensate_inventory),
    ('process_payment', process_payment, compensate_payment),
    ('confirm_order', confirm_order, compensate_confirm),
]


# ── Persistence ──────────────────────────────────────────────────────────

def _init_db(path):
    conn = sqlite3.connect(path)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS saga_instances (
            saga_id TEXT PRIMARY KEY,
            order_id TEXT,
            status TEXT,
            current_step TEXT,
            completed_steps TEXT,
            created_at REAL,
            updated_at REAL,
            error TEXT
        )
    ''')
    conn.commit()
    return conn


def _save(conn, saga_id, order_id, status, current_step, completed_steps, error=None):
    now = time.time()
    conn.execute('''
        INSERT INTO saga_instances
            (saga_id, order_id, status, current_step, completed_steps, created_at, updated_at, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(saga_id) DO UPDATE SET
            status=excluded.status,
            current_step=excluded.current_step,
            completed_steps=excluded.completed_steps,
            updated_at=excluded.updated_at,
            error=excluded.error
    ''', (saga_id, order_id, status, current_step,
          json.dumps(completed_steps), now, now, error))
    conn.commit()


# ── Execution ────────────────────────────────────────────────────────────

def execute_saga(order_event, db_path=SAGA_DB_PATH):
    producer = Producer({'bootstrap.servers': BOOTSTRAP_SERVERS, 'acks': 'all'})
    db = _init_db(db_path)

    saga_id = f"saga-{order_event['order_id']}-{int(time.time() * 1000)}"
    order_id = order_event['order_id']

    _save(db, saga_id, order_id, 'started', '', [])

    completed = []
    ctx = {'order_event': order_event}

    for name, action, _ in STEPS:
        _save(db, saga_id, order_id, 'executing', name, completed)
        try:
            result = action(ctx)
            ctx[name + '_result'] = result
            completed.append(name)
        except Exception as exc:
            # ── Compensate in reverse ──
            _save(db, saga_id, order_id, 'compensating', name, completed, str(exc))
            for comp_name in reversed(completed):
                comp_fn = next(c for n, _, c in STEPS if n == comp_name)
                try:
                    comp_fn(ctx)
                except Exception:
                    pass

            _save(db, saga_id, order_id, 'failed', name, completed, str(exc))
            _publish_notification(producer, order_id, 'saga_failed',
                                  {'saga_id': saga_id, 'failed_step': name, 'error': str(exc)})
            producer.flush()
            db.close()
            return {'saga_id': saga_id, 'status': 'failed', 'error': str(exc)}

    _save(db, saga_id, order_id, 'completed', '', completed)

    # Publish saga state to Kafka
    producer.produce(
        'saga-state',
        key=saga_id.encode(),
        value=json.dumps({
            'saga_id': saga_id,
            'order_id': order_id,
            'status': 'completed',
            'completed_steps': completed,
            'timestamp': time.time(),
        }).encode(),
    )
    _publish_notification(producer, order_id, 'saga_completed', {'saga_id': saga_id})
    producer.flush()
    db.close()
    return {'saga_id': saga_id, 'status': 'completed'}


def _publish_notification(producer, order_id, ntype, details):
    notification = {
        'order_id': order_id,
        'type': ntype,
        'details': details,
        'timestamp': time.time(),
    }
    producer.produce(
        'notifications',
        key=order_id.encode(),
        value=json.dumps(notification).encode(),
    )


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python3 saga.py <order_event_json>', file=sys.stderr)
        sys.exit(1)
    order_event = json.loads(sys.argv[1])
    result = execute_saga(order_event)
    print(json.dumps(result))
