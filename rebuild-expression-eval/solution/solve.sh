#!/bin/bash

# Install the solution as /app/myeval
cp /solution/evalx.py /app/evalx_solution.py
chmod +x /app/evalx_solution.py

cat > /app/myeval << 'WRAPPER'
#!/bin/bash
exec python3 /app/evalx_solution.py "$@"
WRAPPER
chmod +x /app/myeval
