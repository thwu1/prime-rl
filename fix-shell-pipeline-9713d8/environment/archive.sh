#!/bin/bash
source /app/config.sh

file_num=1
for f in "$@"; do
    cat "$HEADER_FILE" "$f" > "${ARCHIVE_DIR}/$((file_num++)).txt"
done
