#!/bin/bash

cp /solution/clab_federator.py /app/clab_federator.py
chmod +x /app/clab_federator.py

echo "Federation engine installed at /app/clab_federator.py"
python3 /app/clab_federator.py check /app/federation_specs/full.federation.yml
python3 /app/clab_federator.py check /app/federation_specs/advanced.federation.yml
