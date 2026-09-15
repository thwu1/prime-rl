#!/bin/bash

set -e

# Copy the Python implementation
cp /solution/portfolio_impl.py /app/portfolio_engine.py

# Create a wrapper script that invokes python3 explicitly
cat > /app/portfolio << 'WRAPPER'
#!/bin/bash
exec python3 /app/portfolio_engine.py "$@"
WRAPPER

chmod +x /app/portfolio
