#!/bin/bash

pip3 install numpy==2.1.3 -q

# Deploy the core design matrix module
cp /solution/design_matrix_impl.py /app/design_matrix.py

# Deploy the multi-tool pipeline script
cp /solution/pipeline_impl.sh /app/pipeline.sh
chmod +x /app/pipeline.sh

# Verify via Python validation tool
python3 /app/validate.py

# Verify via CLI
echo "x
1.0
2.0
3.0" | python3 /app/cli.py "x" --json

# Run the multi-tool pipeline
bash /app/pipeline.sh

# Verify via make targets
make -C /app report
