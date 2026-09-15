#!/usr/bin/env python3
"""Event-sourcing order processor.
Consumes commands from order-commands, produces domain events,
maintains customer aggregates, deduplicates, and dead-letters failures.
"""
import json
import sys
import sqlite3
import time
from confluent_kafka import Consumer, Producer, KafkaError

from config import BOOTSTRAP_SERVERS, PRODUCER_CONFIG, CONSUMER_CONFIG, DEDUP_DB_PATH


def _init_dedup(path):
    conn = sqlite3.connect(path)
    conn.execute(
        'CREATE TABLE IF NOT EXISTS processed_keys '
        '(idempotency_key TEXT PRIMARY KEY, processed_at REAL)'
    )
    conn.commit()
    return conn


def _is_dup(conn, key):
    return conn.execute(
        'SELECT 1 FROM processed_keys WHERE idempotency_key = ?', (key,)
    ).fetchone() is not None


def _mark(conn, key):
    conn.execute(
        'INSERT OR IGNORE INTO processed_keys (idempotency_key, processed_at) VALUES (?, ?)',
        (key, time.time()),
    )
    conn.commit()


REQUIRED_FIELDS = ('command_type', 'order_id', 'customer_id', 'items', 'idempotency_key')


def _handle_command(cmd, producer, dedup_conn):
    """Validate, deduplicate, and produce events."""
    for f in REQUIRED_FIELDS:
        if f not in cmd:
            return f'Missing required field: {f}'

    if _is_dup(dedup_conn, cmd['idempotency_key']):
        return None

    ctype = cmd['command_type']

    if ctype == 'create_order':
        total = sum(float(i['price']) for i in cmd['items'])
        event = {
            'event_type': 'OrderCreated',
            'order_id': cmd['order_id'],
            'customer_id': cmd['customer_id'],
            'items': cmd['items'],
            'total_amount': total,
            'timestamp': cmd.get('timestamp', time.time()),
        }
        producer.produce(
            'order-events',
            key=cmd['customer_id'].encode(),
            value=json.dumps(event).encode(),
        )

    elif ctype == 'cancel_order':
        event = {
            'event_type': 'OrderCancelled',
            'order_id': cmd['order_id'],
            'customer_id': cmd['customer_id'],
            'timestamp': cmd.get('timestamp', time.time()),
        }
        producer.produce(
            'order-events',
            key=cmd['order_id'].encode(),
            value=json.dumps(event).encode(),
        )

    else:
        return f"Unknown command_type: {ctype}"

    producer.flush()
    _mark(dedup_conn, cmd['order_id'])
    return None


def _dead_letter(msg_value, error, producer):
    dl = {
        'original_value': msg_value,
        'error': error,
        'timestamp': time.time(),
    }
    producer.produce('dead-letter', value=json.dumps(dl).encode())
    producer.flush()


def run_batch():
    producer = Producer(PRODUCER_CONFIG)
    consumer = Consumer(CONSUMER_CONFIG)
    consumer.subscribe(['order-commands'])
    dedup_conn = _init_dedup(DEDUP_DB_PATH)

    processed = 0
    empty_polls = 0

    while empty_polls < 3:
        msg = consumer.poll(3.0)
        if msg is None:
            empty_polls += 1
            continue
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                empty_polls += 1
                continue
            print(f'Consumer error: {msg.error()}', file=sys.stderr)
            continue

        empty_polls = 0
        raw = msg.value().decode('utf-8', errors='replace')

        try:
            cmd = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            consumer.commit(msg)
            continue

        err = _handle_command(cmd, producer, dedup_conn)
        if err:
            _dead_letter(raw, err, producer)
        else:
            processed += 1

        consumer.commit(msg)

    consumer.close()
    dedup_conn.close()
    print(f'Processed {processed} commands')
    return processed


if __name__ == '__main__':
    run_batch()
