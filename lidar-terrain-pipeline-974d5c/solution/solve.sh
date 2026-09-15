#!/bin/bash

pip3 install laspy==2.5.4 -q

# Generate input data
if [ ! -f /app/data/survey.las ]; then
    python3 /app/generate_input.py
fi

# Copy the pipeline helper to /app
cp /solution/run_pipeline.py /app/run_pipeline.py

# Create process.sh
cat > /app/process.sh << 'PROCEOF'
#!/bin/bash
set -e
mkdir -p /app/output
pip3 install laspy==2.5.4 -q 2>/dev/null
python3 /app/run_pipeline.py
PROCEOF
chmod +x /app/process.sh

# Run the pipeline
cd /app
bash /app/process.sh
