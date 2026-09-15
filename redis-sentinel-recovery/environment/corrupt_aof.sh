#!/bin/bash
AOF_DIR="/data/redis-node-a/appendonlydir"
INCR_FILE=$(find "$AOF_DIR" -name "*.incr.aof" | head -1)
if [ -z "$INCR_FILE" ]; then
    echo "ERROR: No incremental AOF file found in $AOF_DIR"
    exit 1
fi
printf '*3\r\n$3\r\nSET\r\n$11\r\ncrash_write\r\n$999\r\nINCOMPLETE_DAT' >> "$INCR_FILE"
echo "Corrupted AOF file: $INCR_FILE"
