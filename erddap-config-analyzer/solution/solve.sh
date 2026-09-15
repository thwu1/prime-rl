#!/usr/bin/env bash

set -e

cp /solution/reconcile_pipeline.py /app/reconcile_pipeline.py
chmod +x /app/reconcile_pipeline.py

cat > /app/reconcile.sh << 'SCRIPT'
#!/usr/bin/env bash
set -e
mkdir -p /app/output/datasets_nccsv
ncdump -h /app/source_data/sample_bathy.nc > /tmp/ncdump_header.txt
python3 /app/reconcile_pipeline.py /tmp/ncdump_header.txt
SCRIPT
chmod +x /app/reconcile.sh

cd /app && bash /app/reconcile.sh
