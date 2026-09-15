#!/bin/bash

# Copy optimizer implementation into the working environment
cp /solution/optimizer.py /app/optimizer.py

# Create the optimize.sh entry point
printf '#!/bin/bash\npython3 /app/optimizer.py "$1"\n' > /app/optimize.sh
chmod +x /app/optimize.sh
