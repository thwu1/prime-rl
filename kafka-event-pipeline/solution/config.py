
BOOTSTRAP_SERVERS = 'localhost:9092'
CONSUMER_GROUP = 'order-processor'
DEDUP_DB_PATH = '/app/dedup.db'
SAGA_DB_PATH = '/app/saga_state.db'
OUTBOX_DB_PATH = '/app/outbox.db'

PRODUCER_CONFIG = {
    'bootstrap.servers': BOOTSTRAP_SERVERS,
    'acks': 'all',
    'enable.idempotence': True,
}

CONSUMER_CONFIG = {
    'bootstrap.servers': BOOTSTRAP_SERVERS,
    'group.id': CONSUMER_GROUP,
    'auto.offset.reset': 'earliest',
    'enable.auto.commit': False,
}
