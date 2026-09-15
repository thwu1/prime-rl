#!/bin/bash

# Create the pipeline entry point
cat > /app/solver << 'PIPELINE'
#!/bin/bash
exec python3 /solution/solver.py
PIPELINE
chmod +x /app/solver

# Run the full pipeline
/app/solver
