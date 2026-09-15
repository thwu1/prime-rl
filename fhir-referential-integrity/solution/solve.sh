#!/bin/bash

cd /app

# Step 1: Write the FHIRPath anonymization configuration
python3 /solution/write_config.py

# Step 2: Run the anonymization engine
python3 /solution/anonymizer.py

# Step 3: Deploy and run the jq+openssl compliance validator
cp /solution/validate.sh /app/validate.sh
chmod +x /app/validate.sh
bash /app/validate.sh
