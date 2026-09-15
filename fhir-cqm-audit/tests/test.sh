#!/bin/bash

pip3 install pytest==8.3.4 requests==2.32.3 -q

# Always ensure the FHIR server is running (restart to reload persisted state)
/app/start_fhir.sh

# Wait for server to be fully responsive with data
for i in $(seq 1 15); do
    if curl -s http://localhost:8080/fhir/Patient 2>/dev/null | grep -q '"resourceType"'; then
        break
    fi
    sleep 1
done

# Run pytest and capture exit code
pytest /tests/test_state.py -v --tb=short 2>&1
PYTEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $PYTEST_EXIT
