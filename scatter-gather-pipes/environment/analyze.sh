#!/bin/bash
# analyze.sh - Multi-stage scatter-gather web log analysis pipeline
#
# Reads Apache Combined Log Format from stdin. Fans out the single input
# stream via named pipes (FIFOs) to multiple concurrent processing branches.
# Second-stage derived metrics synchronize with first-stage branch results
# through an inter-process key-value store backed by temporary files,
# coordinated with flock(1) advisory file locks. Floating-point derived
# metrics are computed using bc(1).
#

export LC_ALL=C

FIFO_DIR=$(mktemp -d /tmp/logpipe.XXXXXX)
STORE_DIR=$(mktemp -d /tmp/logstore.XXXXXX)
LOCK_DIR=$(mktemp -d /tmp/loglock.XXXXXX)
trap 'rm -rf "$FIFO_DIR" "$STORE_DIR" "$LOCK_DIR"' EXIT

# Create named pipes for each fan-out branch
for name in count hosts pages bytes dates status hourly hostbytes sizes; do
    mkfifo "$FIFO_DIR/$name"
done

# Inter-process value store: write a value under a key (reads from stdin)
# Uses flock for mutual exclusion
writeval() {
    (
        flock -x 200
        cat > "$STORE_DIR/$1"
    ) 200>"$LOCK_DIR/$1.lock"
}

# Inter-process value store: read a stored value by key
# Uses flock for coordination with writers
readval() {
    (
        flock -xn 200 || { echo ""; exit; }
        cat "$STORE_DIR/$1" 2>/dev/null
    ) 200>"$LOCK_DIR/$1.lock"
}

# =====================================================================
# CONSUMER BRANCHES — each reads from its own named pipe
# =====================================================================

# Branch: total request count
( wc -l < "$FIFO_DIR/count" | tr -d ' ' | writeval total_requests ) &

# Branch: host analysis — unique host count + top 10 hosts by requests
(
    awk '{print $1}' < "$FIFO_DIR/hosts" | sort | \
        wc -l | tr -d ' ' | writeval unique_hosts
) &

# Branch: page analysis — unique page count + top 10 pages
(
    awk '{print $7}' < "$FIFO_DIR/pages" | sort | uniq -c > "$STORE_DIR/_pages_counted"
    wc -l < "$STORE_DIR/_pages_counted" | tr -d ' ' | writeval unique_pages
    sort -rn < "$STORE_DIR/_pages_counted" | head -10 > "$STORE_DIR/top_pages"
) &

# Branch: total bytes transferred
( awk '{total += $NF} END {print total}' < "$FIFO_DIR/bytes" | writeval total_bytes ) &

# Branch: unique calendar days
( awk '{print substr($4, 2, 20)}' < "$FIFO_DIR/dates" | sort -u | wc -l | tr -d ' ' | writeval unique_days ) &

# Branch: HTTP status code distribution
( awk '{print $9}' < "$FIFO_DIR/status" | sort | uniq -c | sort -rn > "$STORE_DIR/status_codes" ) &

# Branch: hourly access distribution
( awk '{print substr($4, 14, 2)}' < "$FIFO_DIR/hourly" | sort | uniq -c > "$STORE_DIR/hourly_dist" ) &

# Branch: top 10 hosts by total bytes transferred
( awk '{b[$1]+=$NF} END {for(h in b) print b[h],h}' < "$FIFO_DIR/hostbytes" | sort -rn | head -10 > "$STORE_DIR/top_hosts_bytes" ) &

# Branch: response size percentiles (P50, P95, P99)
(
    awk '{print $10}' < "$FIFO_DIR/sizes" | sort -n > "$STORE_DIR/_all_sizes"
    # TODO: compute percentile values from sorted sizes
    echo "" > "$STORE_DIR/percentiles"
) &

# =====================================================================
# SECOND STAGE — derived metrics depending on first-stage branch outputs
# Uses bc(1) for floating-point arithmetic
# =====================================================================
(
    # Read first-stage computed values
    tr=$(readval total_requests)
    ud=$(readval unique_days)
    tb=$(readval total_bytes)

    # Requests per day (float, 2 decimal places)
    echo "$tr / $ud" | bc | writeval requests_per_day

    # MBytes per day (float, 6 decimal places)
    echo "$tb / $ud / 1048576" | bc | writeval mbytes_per_day

    # Error rate: percentage of 4xx + 5xx responses
    err_count=$(awk '$2 ~ /^[45]/ {s+=$1} END {print s+0}' "$STORE_DIR/status_codes" 2>/dev/null)
    uh=$(readval unique_hosts)
    echo "scale=2; $err_count * 100 / $uh" | bc | writeval error_rate

    # Status class aggregation
    awk '$2 ~ /^2/ {s+=$1} END {print "2xx:"s+0}' "$STORE_DIR/status_codes" 2>/dev/null > "$STORE_DIR/status_classes"
    awk '$2 ~ /^3/ {s+=$1} END {print "3xx:"s+0}' "$STORE_DIR/status_codes" 2>/dev/null >> "$STORE_DIR/status_classes"
    awk '$2 ~ /^4/ {s+=$1} END {print "4xx:"s+0}' "$STORE_DIR/status_codes" 2>/dev/null >> "$STORE_DIR/status_classes"
    awk '$2 ~ /^5/ {s+=$1} END {print "5xx:"s+0}' "$STORE_DIR/status_codes" 2>/dev/null >> "$STORE_DIR/status_classes"
) &

# =====================================================================
# PRODUCER — fan out stdin to all branch FIFOs via tee
# =====================================================================
tee "$FIFO_DIR/count" "$FIFO_DIR/hosts" "$FIFO_DIR/pages" \
    "$FIFO_DIR/bytes" "$FIFO_DIR/dates" "$FIFO_DIR/status" \
    "$FIFO_DIR/hourly" "$FIFO_DIR/hostbytes" "$FIFO_DIR/sizes" > /dev/null

wait

# =====================================================================
# OUTPUT — gather results from the store and print the report
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
