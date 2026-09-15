#!/usr/bin/env bash

cp /solution/payroll_engine.py /app/payroll_engine.py

cat > /app/payroll <<'WRAPPER'
#!/usr/bin/env python3
import sys
sys.path.insert(0, "/app")
from payroll_engine import main
main()
WRAPPER
chmod +x /app/payroll
