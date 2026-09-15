#!/bin/bash
# Downloads simdjson single-header distribution for building stream_analyzer.

set -e
cd /app

if [ -f simdjson.h ] && [ -f simdjson.cpp ]; then
    exit 0
fi

SIMDJSON_TAG="v4.6.4"
BASE="https://raw.githubusercontent.com/simdjson/simdjson/${SIMDJSON_TAG}/singleheader"

echo "Downloading simdjson ${SIMDJSON_TAG}..."
curl -sfL "${BASE}/simdjson.h" -o simdjson.h || {
    echo "Tag ${SIMDJSON_TAG} not found, trying master..."
    BASE="https://raw.githubusercontent.com/simdjson/simdjson/master/singleheader"
    curl -sfL "${BASE}/simdjson.h" -o simdjson.h
}
curl -sfL "${BASE}/simdjson.cpp" -o simdjson.cpp
echo "simdjson downloaded."
