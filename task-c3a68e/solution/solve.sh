#!/usr/bin/env bash

pip3 install tomli-w==1.0.0 -q

cd /app

# ---------------------------------------------------------------------------
# Use sqlite3 to query chip reference database for valid fix parameters
# ---------------------------------------------------------------------------

# Determine which DMA controller the hash peripheral is wired to
HASH_DMA=$(sqlite3 /app/reference/chip_reference.db \
    "SELECT DISTINCT controller FROM dma_channels WHERE peripheral='hash' ORDER BY 1 LIMIT 1;")
echo "sqlite3: hash peripheral uses DMA controller: $HASH_DMA"

# Find alternative GPIO port for i2c1 that avoids gpio_b conflict
I2C1_ALT_GPIO=$(sqlite3 /app/reference/chip_reference.db \
    "SELECT DISTINCT 'gpio_' || lower(substr(pin, 2, 1))
     FROM pin_assignments
     WHERE peripheral='i2c1'
       AND lower(substr(pin, 1, 2)) != 'pb'
     ORDER BY 1
     LIMIT 1;")
echo "sqlite3: i2c1 alternative GPIO port: $I2C1_ALT_GPIO"

# ---------------------------------------------------------------------------
# Use jq to extract actual memory usage from build manifest
# ---------------------------------------------------------------------------

SENSOR_RAM=$(jq '.tasks.sensor_hub.total_ram_used' /app/reference/build_manifest.json)
echo "jq: sensor_hub actual RAM usage: $SENSOR_RAM bytes"

# ---------------------------------------------------------------------------
# Run analyzer with tool-derived parameters
# ---------------------------------------------------------------------------

python3 /solution/analyzer.py \
    --hash-dma "$HASH_DMA" \
    --i2c1-gpio "$I2C1_ALT_GPIO" \
    --sensor-ram "$SENSOR_RAM"

# ---------------------------------------------------------------------------
# Use graphviz to render dependency graph
# ---------------------------------------------------------------------------

dot -Tsvg /app/output/task_graph.dot -o /app/output/task_graph.svg
echo "graphviz: rendered task_graph.svg"
