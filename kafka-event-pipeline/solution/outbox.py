#!/usr/bin/env python3
"""
Outbox relay: reads pending events from SQLite and publishes them to Kafka.
"""

import json
import sys
import sqlite3
import time
from confluent_kafka import Producer

from config import BOOTSTRAP_SERVERS, OUTBOX_DB_PATH


def _init_outbox(path):
    conn = sqlite3.connect(path)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS outbox_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            key TEXT,
            value TEXT NOT NULL,
            created_at REAL NOT NULL,
            published_at REAL,
            status TEXT DEFAULT 'pending'
        )
    ''')
    conn.commit()
    return conn


def relay_pending(db_path=OUTBOX_DB_PATH, batch_size=500):
    conn = _init_outbox(db_path)
    producer = Producer({'bootstrap.servers': BOOTSTRAP_SERVERS, 'acks': 'all'})

    cur = conn.execute(
        'SELECT id, topic, key, value FROM outbox_events '
        'WHERE status = ? ORDER BY id LIMIT ?',
        ('pending', batch_size),
    )
    rows = cur.fetchall()
    relayed = 0

    for evt_id, topic, key, value in rows:
        try:
            producer.produce(
                topic,
                key=key.encode() if key else None,
                value=value.encode() if isinstance(value, str) else value,
            )
            producer.flush(10)
            conn.execute(
                'UPDATE outbox_events SET status = ?, published_at = ? WHERE id = ?',
                ('published', time.time(), evt_id),
            )
            conn.commit()
            relayed += 1
        except Exception as exc:
            print(f'Failed to relay event {evt_id}: {exc}', file=sys.stderr)
            conn.execute(
                'UPDATE outbox_events SET status = ? WHERE id = ?',
                ('failed', evt_id),
            )
            conn.commit()

    conn.close()
    print(f'Relayed {relayed} events')
    return relayed


if __name__ == '__main__':
    relay_pending()
