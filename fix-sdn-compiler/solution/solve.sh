#!/bin/bash

set -e

pip3 install pytest==8.3.4 -q

export PYTHONPATH=/srv/sdn

# Apply all fixes and implement missing feature
python3 /solution/fix_bugs.py

# Verify all tests pass
cd /srv/sdn
python3 -m pytest /tests/test_state.py -v
