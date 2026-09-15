#!/bin/bash
set -e

mkdir -p /app/data

# Start Redis with suboptimal encoding thresholds matching valkey.conf
redis-server \
    --daemonize yes \
    --dir /tmp \
    --dbfilename dump.rdb \
    --save "" \
    --port 6399 \
    --loglevel warning \
    --rdbcompression yes \
    --protected-mode no \
    --hash-max-listpack-entries 3 \
    --hash-max-listpack-value 64 \
    --zset-max-listpack-entries 5 \
    --zset-max-listpack-value 64 \
    --set-max-intset-entries 3

# Wait for server to be ready
for i in $(seq 1 30); do
    redis-cli -p 6399 PING > /dev/null 2>&1 && break
    sleep 0.5
done

CLI="redis-cli -p 6399"

# === DB 0 ===

# 50 string keys with integer values (tests integer-encoded strings)
for i in $(seq 1 50); do
    $CLI SET "user:$i" "$((i * 100))" > /dev/null
done

# 5 string keys with text values (tests raw/embstr/LZF encodings)
$CLI SET "config:app_name" "MyApplication-Production-Server-v2.1" > /dev/null
$CLI SET "config:description" "This is a longer configuration value that tests raw string encoding in the RDB format" > /dev/null
$CLI SET "config:secret_key" "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6" > /dev/null
$CLI SET "config:api_endpoint" "https://api.example.com/v3/resources" > /dev/null
$CLI SET "config:feature_flags" "enable_cache=true;max_retries=3;timeout_ms=5000;debug=false" > /dev/null

# Hash with 5 fields (exceeds threshold 3 → hashtable instead of listpack)
$CLI HSET "session:data" username alice role admin login_time 1700000000 ip_addr "192.168.1.100" user_agent "Mozilla/5.0" > /dev/null

# Hash with 200 fields (always hashtable, exceeds any reasonable threshold)
for i in $(seq 1 200); do
    $CLI HSET "metrics:daily" "metric_$i" "$((i * 7 + 13))" > /dev/null
done

# List with 10 items (single listpack node)
for i in $(seq 1 10); do
    $CLI RPUSH "queue:jobs" "job_task_$i" > /dev/null
done

# List with 1000 items (multiple quicklist nodes)
for i in $(seq 1 1000); do
    $CLI RPUSH "logs:recent" "log_entry_${i}_event_data" > /dev/null
done

# Set with 5 integer members (exceeds threshold 3 → hashtable instead of intset)
$CLI SADD "tags:active" 1 2 3 4 5 > /dev/null

# Set with 200 string members (always hashtable)
for i in $(seq 1 200); do
    $CLI SADD "users:online" "user_$(printf '%04d' $i)" > /dev/null
done

# Sorted set with 10 members (exceeds threshold 5 → skiplist instead of listpack)
for i in $(seq 1 10); do
    $CLI ZADD "leaderboard:scores" "$((i * 100))" "player_$i" > /dev/null
done

# Sorted set with 500 members (always skiplist)
for i in $(seq 1 500); do
    $CLI ZADD "rankings:global" "$((i * 3 + 7))" "contestant_$(printf '%04d' $i)" > /dev/null
done

# 3 string keys with millisecond-precision TTL
$CLI SET "cache:page:1" "cached_homepage_content_v1" > /dev/null
$CLI PEXPIREAT "cache:page:1" 1893456000000 > /dev/null

$CLI SET "cache:page:2" "cached_about_content_v2" > /dev/null
$CLI PEXPIREAT "cache:page:2" 1924992000000 > /dev/null

$CLI SET "cache:page:3" "cached_contact_content_v3" > /dev/null
$CLI PEXPIREAT "cache:page:3" 1956528000000 > /dev/null

# === DB 2 (tests database selection with redis-cli -n) ===
$CLI -n 2 SET "db2:key1" "value_in_db2_first" > /dev/null
$CLI -n 2 SET "db2:key2" "value_in_db2_second" > /dev/null
$CLI -n 2 SET "db2:key3" "value_in_db2_third" > /dev/null
$CLI -n 2 SET "db2:counter" "42" > /dev/null
$CLI -n 2 SET "db2:flag" "1" > /dev/null

# Synchronous save
$CLI SAVE > /dev/null

# Copy the RDB file
cp /tmp/dump.rdb /app/data/dump.rdb

# Verify
ls -la /app/data/dump.rdb
echo "RDB contains $(wc -c < /app/data/dump.rdb) bytes"

# Shutdown server
$CLI SHUTDOWN NOSAVE > /dev/null 2>&1 || true

echo "RDB file generated successfully at /app/data/dump.rdb"
