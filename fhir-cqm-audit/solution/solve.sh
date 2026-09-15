#!/bin/bash

pip3 install requests==2.32.3 -q

# Start the FHIR server (kills any existing instance first)
/app/start_fhir.sh

# Wait for server to be fully responsive with data
for i in $(seq 1 15); do
    if curl -s http://localhost:8080/fhir/Patient 2>/dev/null | grep -q '"resourceType"'; then
        break
    fi
    sleep 1
done

# Run the audit
python3 /solution/solve_helper.py
