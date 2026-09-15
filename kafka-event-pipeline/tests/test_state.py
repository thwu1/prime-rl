"""
Tests for event-driven order processing pipeline.
"""

import json
import os
import sys
import time
import uuid
import subprocess
import sqlite3
import pytest

KAFKA_HOME = os.environ.get('KAFKA_HOME', '/opt/kafka')
BOOTSTRAP = 'localhost:9092'


# --- Helpers ----------------------------------------------------------------

def wait_for_kafka(timeout=60):
    start = time.time()
    while time.time() - start < timeout:
        try:
            result = subprocess.run(
                [f'{KAFKA_HOME}/bin/kafka-topics.sh', '--bootstrap-server', BOOTSTRAP, '--list'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def get_topic_description(topic):
    result = subprocess.run(
        [f'{KAFKA_HOME}/bin/kafka-topics.sh', '--bootstrap-server', BOOTSTRAP,
         '--describe', '--topic', topic],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout, result.returncode


def get_topic_configs(topic):
    result = subprocess.run(
        [f'{KAFKA_HOME}/bin/kafka-configs.sh', '--bootstrap-server', BOOTSTRAP,
         '--entity-type', 'topics', '--entity-name', topic, '--describe'],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout, result.returncode


def produce_message(topic, value, key=None):
    from confluent_kafka import Producer
    p = Producer({'bootstrap.servers': BOOTSTRAP})
    raw = value.encode('utf-8') if isinstance(value, str) else value
    p.produce(topic, value=raw, key=key.encode('utf-8') if key else None)
    p.flush(10)


def consume_messages(topic, timeout=20, max_msgs=500):
    from confluent_kafka import Consumer, KafkaError
    c = Consumer({
        'bootstrap.servers': BOOTSTRAP,
        'group.id': f'test-{uuid.uuid4()}',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': True,
    })
    c.subscribe([topic])

    msgs = []
    start = time.time()
    empty = 0

    while time.time() - start < timeout and empty < 8:
        msg = c.poll(2.0)
        if msg is None:
            empty += 1
            continue
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                empty += 1
                continue
            continue
        empty = 0
        try:
            val = json.loads(msg.value().decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            val = msg.value().decode('utf-8', errors='replace')
        msgs.append({
            'key': msg.key().decode('utf-8') if msg.key() else None,
            'value': val,
        })
        if len(msgs) >= max_msgs:
            break

    c.close()
    return msgs


# --- Session fixture --------------------------------------------------------

@pytest.fixture(scope='session', autouse=True)
def kafka_ready():
    assert wait_for_kafka(), "Kafka broker is not available"


# --- Processor fixture (module-scoped: runs once) ---------------------------

@pytest.fixture(scope='module')
def processor_run(kafka_ready):
    ts = int(time.time() * 1000)

    # 1) Valid create_order
    valid_cmd = {
        'command_type': 'create_order',
        'order_id': f'ord-v-{ts}',
        'customer_id': f'cust-v-{ts}',
        'items': [
            {'product_id': 'p1', 'price': 25.0, 'quantity': 2},
            {'product_id': 'p2', 'price': 50.0, 'quantity': 1},
        ],
        'idempotency_key': f'ik-v-{ts}',
        'timestamp': time.time(),
    }
    produce_message('order-commands', json.dumps(valid_cmd))

    # 2-3) Duplicate create_order (same idempotency key)
    dup_cmd = {
        'command_type': 'create_order',
        'order_id': f'ord-d-{ts}',
        'customer_id': f'cust-d-{ts}',
        'items': [{'product_id': 'p3', 'price': 10.0, 'quantity': 3}],
        'idempotency_key': f'ik-d-{ts}',
        'timestamp': time.time(),
    }
    produce_message('order-commands', json.dumps(dup_cmd))
    produce_message('order-commands', json.dumps(dup_cmd))

    # 4) Invalid command (missing fields)
    invalid_cmd = {'bad': True, 'marker': f'inv-{ts}'}
    produce_message('order-commands', json.dumps(invalid_cmd))

    # 5) Non-JSON garbage
    produce_message('order-commands', f'not-json-{ts}')

    # 6) Cancel order
    cancel_cmd = {
        'command_type': 'cancel_order',
        'order_id': f'ord-c-{ts}',
        'customer_id': f'cust-c-{ts}',
        'items': [],
        'idempotency_key': f'ik-c-{ts}',
        'timestamp': time.time(),
    }
    produce_message('order-commands', json.dumps(cancel_cmd))

    # Clear dedup DB for clean run
    dedup_path = '/app/dedup.db'
    if os.path.exists(dedup_path):
        os.remove(dedup_path)

    # Run processor
    proc = subprocess.run(
        ['python3', '/app/processor.py'],
        capture_output=True, text=True, timeout=120,
        cwd='/app',
    )

    time.sleep(3)

    order_events = consume_messages('order-events')
    customer_states = consume_messages('customer-state')
    dead_letters = consume_messages('dead-letter')

    return {
        'ts': ts,
        'valid_cmd': valid_cmd,
        'dup_cmd': dup_cmd,
        'cancel_cmd': cancel_cmd,
        'proc': proc,
        'order_events': order_events,
        'customer_states': customer_states,
        'dead_letters': dead_letters,
    }


# --- Topic Configuration Tests ---------------------------------------------

class TestTopicConfigurations:

    def _assert_topic_exists(self, topic):
        desc, rc = get_topic_description(topic)
        assert rc == 0 and topic in desc, f"Topic '{topic}' does not exist"
        return desc

    def _count_partitions(self, topic):
        desc = self._assert_topic_exists(topic)
        partition_lines = [
            l for l in desc.strip().split('\n')
            if '\tPartition:' in l and 'Leader:' in l
        ]
        return len(partition_lines)

    def _assert_config_value(self, topic, config_key, expected_fragment):
        configs, rc = get_topic_configs(topic)
        assert rc == 0, f"Failed to get configs for '{topic}'"
        lines = [l for l in configs.split('\n') if config_key in l]
        assert len(lines) > 0, (
            f"Config '{config_key}' not set for topic '{topic}'. "
            f"Full output:\n{configs}"
        )
        text = ' '.join(lines)
        assert expected_fragment in text, (
            f"Expected '{config_key}' containing '{expected_fragment}' for "
            f"topic '{topic}', got: {text}"
        )

    # order-commands
    def test_order_commands_partitions(self):
        assert self._count_partitions('order-commands') == 6

    def test_order_commands_cleanup_policy(self):
        self._assert_config_value('order-commands', 'cleanup.policy', 'delete')

    def test_order_commands_retention(self):
        self._assert_config_value('order-commands', 'retention.ms', '604800000')

    # order-events
    def test_order_events_partitions(self):
        assert self._count_partitions('order-events') == 6

    def test_order_events_compaction(self):
        self._assert_config_value('order-events', 'cleanup.policy', 'compact')

    def test_order_events_dirty_ratio(self):
        self._assert_config_value('order-events', 'min.cleanable.dirty.ratio', '0.1')

    # customer-state
    def test_customer_state_partitions(self):
        assert self._count_partitions('customer-state') == 3

    def test_customer_state_compaction(self):
        self._assert_config_value('customer-state', 'cleanup.policy', 'compact')

    # saga-state
    def test_saga_state_partitions(self):
        assert self._count_partitions('saga-state') == 6

    def test_saga_state_cleanup_policy(self):
        configs, _ = get_topic_configs('saga-state')
        cleanup_lines = [l for l in configs.split('\n') if 'cleanup.policy' in l]
        assert len(cleanup_lines) > 0, "No cleanup.policy for saga-state"
        text = cleanup_lines[0]
        assert 'compact' in text and 'delete' in text, (
            f"saga-state cleanup.policy must include both compact and delete: {text}"
        )

    # notifications
    def test_notifications_partitions(self):
        assert self._count_partitions('notifications') == 3

    def test_notifications_retention(self):
        self._assert_config_value('notifications', 'retention.ms', '86400000')

    # dead-letter
    def test_dead_letter_partitions(self):
        assert self._count_partitions('dead-letter') == 1

    def test_dead_letter_retention(self):
        self._assert_config_value('dead-letter', 'retention.ms', '2592000000')


# --- Processor Tests --------------------------------------------------------

class TestProcessor:

    def test_processor_exits_successfully(self, processor_run):
        assert processor_run['proc'].returncode == 0, (
            f"Processor exited with {processor_run['proc'].returncode}\n"
            f"stdout: {processor_run['proc'].stdout}\n"
            f"stderr: {processor_run['proc'].stderr}"
        )

    def test_order_created_event_exists(self, processor_run):
        ts = processor_run['ts']
        order_id = f'ord-v-{ts}'
        events = [
            e for e in processor_run['order_events']
            if isinstance(e['value'], dict) and e['value'].get('order_id') == order_id
        ]
        assert len(events) >= 1, f"No event found for order {order_id}"
        assert events[0]['value']['event_type'] == 'OrderCreated'

    def test_order_created_total_amount(self, processor_run):
        ts = processor_run['ts']
        order_id = f'ord-v-{ts}'
        events = [
            e for e in processor_run['order_events']
            if isinstance(e['value'], dict) and e['value'].get('order_id') == order_id
            and e['value'].get('event_type') == 'OrderCreated'
        ]
        assert len(events) >= 1
        total = events[0]['value']['total_amount']
        assert abs(total - 100.0) < 0.01, f"Expected total_amount=100.0, got {total}"

    def test_order_event_keyed_by_order_id(self, processor_run):
        ts = processor_run['ts']
        order_id = f'ord-v-{ts}'
        events = [
            e for e in processor_run['order_events']
            if isinstance(e['value'], dict) and e['value'].get('order_id') == order_id
        ]
        assert len(events) >= 1
        assert events[0]['key'] == order_id, (
            f"Event key should be '{order_id}', got '{events[0]['key']}'"
        )

    def test_idempotency_deduplication(self, processor_run):
        ts = processor_run['ts']
        order_id = f'ord-d-{ts}'
        created = [
            e for e in processor_run['order_events']
            if isinstance(e['value'], dict)
            and e['value'].get('order_id') == order_id
            and e['value'].get('event_type') == 'OrderCreated'
        ]
        assert len(created) == 1, (
            f"Duplicate commands must produce exactly 1 OrderCreated event, "
            f"got {len(created)}"
        )

    def test_cancel_order_event(self, processor_run):
        ts = processor_run['ts']
        order_id = f'ord-c-{ts}'
        events = [
            e for e in processor_run['order_events']
            if isinstance(e['value'], dict) and e['value'].get('order_id') == order_id
        ]
        assert len(events) >= 1, f"No event for cancelled order {order_id}"
        assert events[0]['value']['event_type'] == 'OrderCancelled'

    def test_customer_state_updated(self, processor_run):
        ts = processor_run['ts']
        cust_id = f'cust-v-{ts}'
        states = [
            s for s in processor_run['customer_states']
            if isinstance(s['value'], dict) and s['key'] == cust_id
        ]
        assert len(states) >= 1, f"No customer-state update for {cust_id}"

    def test_dead_letter_receives_invalid(self, processor_run):
        dl = processor_run['dead_letters']
        assert len(dl) >= 2, (
            f"Expected at least 2 dead-letter messages (invalid JSON + missing fields), "
            f"got {len(dl)}"
        )


# --- Saga Tests -------------------------------------------------------------

class TestSaga:

    def test_saga_success_path(self):
        order_event = {
            'event_type': 'OrderCreated',
            'order_id': f'saga-ok-{int(time.time() * 1000)}',
            'customer_id': 'cust-saga-ok',
            'items': [{'product_id': 'p1', 'price': 50.0, 'quantity': 2}],
            'total_amount': 100.0,
            'timestamp': time.time(),
        }
        result = subprocess.run(
            ['python3', '/app/saga.py', json.dumps(order_event)],
            capture_output=True, text=True, timeout=30, cwd='/app',
        )
        assert result.returncode == 0, f"saga.py failed: {result.stderr}"
        output = json.loads(result.stdout.strip().split('\n')[-1])
        assert output['status'] == 'completed', f"Saga should complete: {output}"

    def test_saga_payment_decline(self):
        order_event = {
            'event_type': 'OrderCreated',
            'order_id': f'saga-pd-{int(time.time() * 1000)}',
            'customer_id': 'cust-saga-pd',
            'items': [{'product_id': 'p1', 'price': 6000.0, 'quantity': 2}],
            'total_amount': 12000.0,
            'timestamp': time.time(),
        }
        result = subprocess.run(
            ['python3', '/app/saga.py', json.dumps(order_event)],
            capture_output=True, text=True, timeout=30, cwd='/app',
        )
        assert result.returncode == 0
        output = json.loads(result.stdout.strip().split('\n')[-1])
        assert output['status'] == 'failed', f"Saga should fail on payment: {output}"
        assert 'error' in output

    def test_saga_inventory_failure(self):
        order_event = {
            'event_type': 'OrderCreated',
            'order_id': f'saga-if-{int(time.time() * 1000)}',
            'customer_id': 'cust-saga-if',
            'items': [{'product_id': 'p1', 'price': 10.0, 'quantity': 200}],
            'total_amount': 2000.0,
            'timestamp': time.time(),
        }
        result = subprocess.run(
            ['python3', '/app/saga.py', json.dumps(order_event)],
            capture_output=True, text=True, timeout=30, cwd='/app',
        )
        assert result.returncode == 0
        output = json.loads(result.stdout.strip().split('\n')[-1])
        assert output['status'] == 'failed'

    def test_saga_state_persisted_success(self):
        order_event = {
            'event_type': 'OrderCreated',
            'order_id': f'saga-db-{int(time.time() * 1000)}',
            'customer_id': 'cust-saga-db',
            'items': [{'product_id': 'p1', 'price': 20.0, 'quantity': 1}],
            'total_amount': 20.0,
            'timestamp': time.time(),
        }
        subprocess.run(
            ['python3', '/app/saga.py', json.dumps(order_event)],
            capture_output=True, text=True, timeout=30, cwd='/app',
        )

        assert os.path.exists('/app/saga_state.db'), "Saga state DB not found"
        conn = sqlite3.connect('/app/saga_state.db')
        cur = conn.execute(
            'SELECT status, completed_steps FROM saga_instances WHERE order_id = ?',
            (order_event['order_id'],)
        )
        row = cur.fetchone()
        conn.close()

        assert row is not None, "No saga record in DB"
        assert row[0] == 'completed', f"Expected status 'completed', got '{row[0]}'"
        steps = json.loads(row[1])
        assert len(steps) == 4, f"Expected 4 completed steps, got {len(steps)}"
        for name in ('validate_order', 'reserve_inventory', 'process_payment', 'confirm_order'):
            assert name in steps, f"Step '{name}' missing from completed_steps"

    def test_saga_state_persisted_failure(self):
        order_event = {
            'event_type': 'OrderCreated',
            'order_id': f'saga-fl-{int(time.time() * 1000)}',
            'customer_id': 'cust-saga-fl',
            'items': [{'product_id': 'p1', 'price': 5500.0, 'quantity': 2}],
            'total_amount': 11000.0,
            'timestamp': time.time(),
        }
        subprocess.run(
            ['python3', '/app/saga.py', json.dumps(order_event)],
            capture_output=True, text=True, timeout=30, cwd='/app',
        )

        conn = sqlite3.connect('/app/saga_state.db')
        cur = conn.execute(
            'SELECT status FROM saga_instances WHERE order_id = ?',
            (order_event['order_id'],)
        )
        row = cur.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 'failed', f"Expected status 'failed', got '{row[0]}'"


# --- Outbox Relay Tests -----------------------------------------------------

class TestOutboxRelay:

    def test_outbox_relay_publishes_and_marks(self):
        db_path = '/app/outbox.db'
        marker = f'ob-{int(time.time() * 1000)}'

        conn = sqlite3.connect(db_path)
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
        test_value = json.dumps({'type': 'outbox_test', 'marker': marker})
        conn.execute(
            'INSERT INTO outbox_events (topic, key, value, created_at, status) '
            'VALUES (?, ?, ?, ?, ?)',
            ('notifications', 'outbox-key', test_value, time.time(), 'pending')
        )
        conn.commit()
        conn.close()

        result = subprocess.run(
            ['python3', '/app/outbox.py'],
            capture_output=True, text=True, timeout=30, cwd='/app',
        )
        assert result.returncode == 0, f"outbox.py failed: {result.stderr}"

        conn = sqlite3.connect(db_path)
        cur = conn.execute(
            "SELECT status, published_at FROM outbox_events WHERE value LIKE ?",
            (f'%{marker}%',)
        )
        row = cur.fetchone()
        conn.close()

        assert row is not None, "Outbox event not found after relay"
        assert row[0] == 'published', f"Expected status 'published', got '{row[0]}'"
        assert row[1] is not None, "published_at should be set"


# --- File Existence Tests ---------------------------------------------------

class TestFileExistence:

    def test_processor_exists(self):
        assert os.path.exists('/app/processor.py')

    def test_saga_exists(self):
        assert os.path.exists('/app/saga.py')

    def test_outbox_exists(self):
        assert os.path.exists('/app/outbox.py')

    def test_config_module_exists(self):
        assert os.path.exists('/app/config.py') or os.path.exists('/app/kafka_config.py')

    def test_models_module_exists(self):
        assert os.path.exists('/app/models.py')

    def test_setup_topics_exists(self):
        assert os.path.exists('/app/setup_topics.sh')
