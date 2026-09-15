#!/bin/bash

# Deploy solver, analyzer, and auditor
cp /solution/solver.py /app/solver.py
cp /solution/analyzer.py /app/analyzer.py
cp /solution/auditor.py /app/auditor.py

# Create solve.sh entry point
cat > /app/solve.sh << 'EOF'
#!/bin/bash
python3 /app/solver.py "$1"
EOF
chmod +x /app/solve.sh

# Create analyze.sh entry point
cat > /app/analyze.sh << 'EOF'
#!/bin/bash
python3 /app/analyzer.py "$1"
EOF
chmod +x /app/analyze.sh

# Create audit.sh entry point
cat > /app/audit.sh << 'EOF'
#!/bin/bash
python3 /app/auditor.py "$1"
EOF
chmod +x /app/audit.sh
