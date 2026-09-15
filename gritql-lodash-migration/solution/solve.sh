#!/bin/bash

set -e

cd /app

# Write the GritQL pattern files
python3 /solution/write_pattern.py

# Verify the inline pattern tests pass
grit patterns test

# Verify apply works on a sample file
echo "import _ from 'lodash';" > /tmp/verify.js
echo "const k = _.keys(obj);" >> /tmp/verify.js
grit apply lodash_to_native /tmp/verify.js
echo "=== Verification result ==="
cat /tmp/verify.js
rm -f /tmp/verify.js
