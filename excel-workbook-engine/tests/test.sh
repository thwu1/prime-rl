#!/bin/bash

pip3 install pytest==8.3.4 openpyxl==3.1.5 -q

# Run the agent's build script if output doesn't exist yet
if [ ! -f /app/output/consolidated_report.xlsx ]; then
    if [ -f /app/build_workbook.py ]; then
        cd /app && python3 build_workbook.py 2>&1 || true
    fi
fi

cd /app
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
