#!/bin/bash
# Corrected analyze.sh — all bugs fixed and missing features implemented.
# Uses flock(1) for inter-process synchronization and bc(1) for float math.
#

export LC_ALL=C

FIFO_DIR=$(mktemp -d /tmp/logpipe.XXXXXX)
STORE_DIR=$(mktemp -d /tmp/logstore.XXXXXX)
LOCK_DIR=$(mktemp -d /tmp/loglock.XXXXXX)
trap 'rm -rf "$FIFO_DIR" "$STORE_DIR" "$LOCK_DIR"' EXIT

for name in count hosts pages bytes dates status hourly hostbytes sizes; do
    mkfifo "$FIFO_DIR/$name"
done

# FIX: writeval uses exclusive lock (was already correct in broken version)
writeval() {
    (
        flock -x 200
        cat > "$STORE_DIR/$1"
    ) 200>"$LOCK_DIR/$1.lock"
}

# FIX 1+2: readval with wait-for-file loop and shared blocking lock.
# Broken version had: no wait loop, flock -xn (exclusive non-blocking).
# Fixed: busy-wait until file exists and is non-empty, then shared blocking lock.
readval() {
    while [ ! -s "$STORE_DIR/$1" ]; do sleep 0.01; done
    (
        flock -s 200
        cat "$STORE_DIR/$1"
    ) 200>"$LOCK_DIR/$1.lock"
}

# =====================================================================
# CONSUMER BRANCHES
# =====================================================================

# Branch: total request count
( wc -l < "$FIFO_DIR/count" | tr -d ' ' | writeval total_requests ) &

# FIX 3: Host analysis — add uniq -c, produce both unique count and top-10 list.
# Broken: sort | wc -l (counted all lines, not unique; no top_hosts_req file).
(
    awk '{print $1}' < "$FIFO_DIR/hosts" | sort | uniq -c > "$STORE_DIR/_hosts_counted"
    wc -l < "$STORE_DIR/_hosts_counted" | tr -d ' ' | writeval unique_hosts
    sort -rn < "$STORE_DIR/_hosts_counted" | head -10 > "$STORE_DIR/top_hosts_req"
) &

# Branch: page analysis (correct in broken version)
(
    awk '{print $7}' < "$FIFO_DIR/pages" | sort | uniq -c > "$STORE_DIR/_pages_counted"
    wc -l < "$STORE_DIR/_pages_counted" | tr -d ' ' | writeval unique_pages
    sort -rn < "$STORE_DIR/_pages_counted" | head -10 > "$STORE_DIR/top_pages"
) &

# FIX 4: Use $10 (response bytes) instead of $NF (user-agent fragment)
( awk '{total += $10} END {print total}' < "$FIFO_DIR/bytes" | writeval total_bytes ) &

# FIX 5: substr($4, 2, 11) extracts "DD/Mon/YYYY" (11 chars, not 20)
( awk '{print substr($4, 2, 11)}' < "$FIFO_DIR/dates" | sort -u | wc -l | tr -d ' ' | writeval unique_days ) &

# Branch: status code distribution (correct in broken version)
( awk '{print $9}' < "$FIFO_DIR/status" | sort | uniq -c | sort -rn > "$STORE_DIR/status_codes" ) &

# Branch: hourly distribution (correct in broken version)
( awk '{print substr($4, 14, 2)}' < "$FIFO_DIR/hourly" | sort | uniq -c > "$STORE_DIR/hourly_dist" ) &

# FIX 6: $10 instead of $NF for host-byte accumulation
( awk '{b[$1]+=$10} END {for(h in b) print b[h],h}' < "$FIFO_DIR/hostbytes" | sort -rn | head -10 > "$STORE_DIR/top_hosts_bytes" ) &

# FIX 7: Full percentile computation (P50, P95, P99 via nearest-rank)
# Broken: just wrote empty string to percentiles file.
(
    awk '{print $10}' < "$FIFO_DIR/sizes" | sort -n > "$STORE_DIR/_all_sizes"
    n=$(wc -l < "$STORE_DIR/_all_sizes" | tr -d ' ')
    if [ "$n" -gt 0 ]; then
        p50_idx=$(awk "BEGIN {x=$n*0.50; i=int(x); if(x>i) i++; print i}")
        p95_idx=$(awk "BEGIN {x=$n*0.95; i=int(x); if(x>i) i++; print i}")
        p99_idx=$(awk "BEGIN {x=$n*0.99; i=int(x); if(x>i) i++; print i}")
        p50=$(sed -n "${p50_idx}p" "$STORE_DIR/_all_sizes")
        p95=$(sed -n "${p95_idx}p" "$STORE_DIR/_all_sizes")
        p99=$(sed -n "${p99_idx}p" "$STORE_DIR/_all_sizes")
        printf "P50:%s\nP95:%s\nP99:%s\n" "$p50" "$p95" "$p99" > "$STORE_DIR/percentiles"
    fi
) &

# =====================================================================
# SECOND STAGE — derived metrics with bc(1) and proper synchronization
# =====================================================================
(
    tr=$(readval total_requests)
    ud=$(readval unique_days)
    tb=$(readval total_bytes)

    # FIX 8: bc with sufficient scale + printf for correct rounding.
    # Broken: no scale (integer division).
    rpd=$(echo "scale=10; $tr / $ud" | bc)
    printf "%.2f" "$rpd" | writeval requests_per_day

    mpd=$(echo "scale=10; $tb / $ud / 1048576" | bc)
    printf "%.6f" "$mpd" | writeval mbytes_per_day

    # FIX 9: Wait for status_codes file before computing derived status metrics.
    # Broken: read status_codes immediately (might not exist yet).
    while [ ! -s "$STORE_DIR/status_codes" ]; do sleep 0.01; done

    # FIX 10: Use total_requests (not unique_hosts) as denominator for error rate.
    # Broken: used $uh (unique_hosts).
    err_count=$(awk '$2 ~ /^[45]/ {s+=$1} END {print s+0}' "$STORE_DIR/status_codes")
    er=$(echo "scale=10; $err_count / $tr * 100" | bc)
    printf "%.2f" "$er" | writeval error_rate

    # Status class aggregation (now synchronized with status_codes)
    awk '$2 ~ /^2/ {s+=$1} END {print "2xx:"s+0}' "$STORE_DIR/status_codes" > "$STORE_DIR/status_classes"
    awk '$2 ~ /^3/ {s+=$1} END {print "3xx:"s+0}' "$STORE_DIR/status_codes" >> "$STORE_DIR/status_classes"
    awk '$2 ~ /^4/ {s+=$1} END {print "4xx:"s+0}' "$STORE_DIR/status_codes" >> "$STORE_DIR/status_classes"
    awk '$2 ~ /^5/ {s+=$1} END {print "5xx:"s+0}' "$STORE_DIR/status_codes" >> "$STORE_DIR/status_classes"
) &

# =====================================================================
# PRODUCER — fan out stdin to all branch FIFOs
# =====================================================================
tee "$FIFO_DIR/count" "$FIFO_DIR/hosts" "$FIFO_DIR/pages" \
    "$FIFO_DIR/bytes" "$FIFO_DIR/dates" "$FIFO_DIR/status" \
    "$FIFO_DIR/hourly" "$FIFO_DIR/hostbytes" "$FIFO_DIR/sizes" > /dev/null

wait

# =====================================================================
# OUTPUT
# =====================================================================
echo "TOTAL_REQUESTS:$(readval total_requests)"
echo "TOTAL_BYTES:$(readval total_bytes)"
echo "UNIQUE_HOSTS:$(readval unique_hosts)"
echo "UNIQUE_PAGES:$(readval unique_pages)"
echo "UNIQUE_DAYS:$(readval unique_days)"
echo "REQUESTS_PER_DAY:$(readval requests_per_day)"
echo "MBYTES_PER_DAY:$(readval mbytes_per_day)"
echo "ERROR_RATE:$(readval error_rate)"

echo "---TOP_HOSTS_BY_REQUESTS---"
cat "$STORE_DIR/top_hosts_req" 2>/dev/null

echo "---TOP_HOSTS_BY_BYTES---"
cat "$STORE_DIR/top_hosts_bytes" 2>/dev/null

echo "---TOP_PAGES---"
cat "$STORE_DIR/top_pages" 2>/dev/null

echo "---STATUS_CODES---"
cat "$STORE_DIR/status_codes" 2>/dev/null

echo "---STATUS_CLASSES---"
cat "$STORE_DIR/status_classes" 2>/dev/null

echo "---HOURLY_DISTRIBUTION---"
cat "$STORE_DIR/hourly_dist" 2>/dev/null

echo "---RESPONSE_SIZE_PERCENTILES---"
cat "$STORE_DIR/percentiles" 2>/dev/null
