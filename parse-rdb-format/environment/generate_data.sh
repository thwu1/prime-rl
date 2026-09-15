#!/bin/bash
set -e

# Start Redis with explicit config
redis-server --daemonize yes --dir /tmp --dbfilename dump.rdb --save "" --appendonly no
sleep 2

# Database 0: various data types and encodings
redis-cli SET greeting "Hello, World!"
redis-cli SET counter 42
redis-cli SET big_number 2147483647
redis-cli SET negative -100
redis-cli SET medium_number 12345
redis-cli SET long_value "The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog."
redis-cli HSET server:config host 127.0.0.1 port 6379 timeout 300 loglevel notice
redis-cli RPUSH events click scroll keypress submit hover
redis-cli SADD languages python rust go java typescript
redis-cli ZADD highscores 1500.5 Alice 1200.75 Bob 980 Charlie 2100.25 Diana 750.5 Eve
redis-cli SET with_expiry ephemeral
redis-cli EXPIREAT with_expiry 4102444800
redis-cli SADD primes 2 3 5 7 11 13 17 19 23 29

# Database 2
redis-cli -n 2 SET alt_db_key value_in_db2
redis-cli -n 2 HSET info type benchmark version 1.0

# Persist and copy
redis-cli SAVE
cp /tmp/dump.rdb /app/data.rdb

# Shutdown
redis-cli SHUTDOWN NOSAVE || true
