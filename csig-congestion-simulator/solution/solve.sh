#!/bin/bash

# Copy engine to /app
cp /solution/csig_engine.py /app/csig_engine.py

# Create simulate.sh entry point
echo '#!/bin/bash' > /app/simulate.sh
echo 'python3 /app/csig_engine.py' >> /app/simulate.sh
chmod +x /app/simulate.sh

# Create analyze.sh entry point
echo '#!/bin/bash' > /app/analyze.sh
echo 'python3 /app/csig_engine.py' >> /app/analyze.sh
chmod +x /app/analyze.sh

# Run the analysis
cd /app && bash /app/simulate.sh
