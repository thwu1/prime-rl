#!/bin/bash

# pyyaml is already available via python3-yaml (apt) in the Dockerfile
pip3 install pytest==8.3.4 jsonschema==4.23.0 -q

# Convert YAML target config to JSON for test fixture consumption
python3 -c "
import yaml, json
with open('/app/target_config.yaml') as f:
    data = yaml.safe_load(f)
with open('/app/target_config.json', 'w') as f:
    json.dump(data, f)
"

cd /app
pytest /tests/test_state.py -v
exit_code=$?

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $exit_code
