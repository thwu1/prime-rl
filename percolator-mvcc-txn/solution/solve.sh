#!/bin/bash


pip3 install redis==5.2.1 -q

# Start Redis for timestamp oracle
redis-server --daemonize yes --loglevel warning 2>/dev/null || true
sleep 1

cp /solution/oracle_impl.py /app/mvcc/oracle.py
cp /solution/storage_impl.py /app/mvcc/storage.py
cp /solution/transaction_impl.py /app/mvcc/transaction.py

cd /app && python3 -c "
from mvcc import TimestampOracle, MemoryStorage, Transaction

oracle = TimestampOracle()
storage = MemoryStorage()
txn = Transaction(oracle, storage)
txn.begin()
txn.set(b'smoke', b'test')
assert txn.commit() is True

r = Transaction(oracle, storage)
r.begin()
assert r.get(b'smoke') == b'test'
print('Smoke test passed — implementation loaded successfully.')
"
