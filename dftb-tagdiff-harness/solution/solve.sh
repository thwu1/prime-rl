#!/usr/bin/env bash

# Deploy corrected tagdiff.sh and harness.sh implementations
cp /solution/tagdiff_impl.sh /app/tagdiff.sh
cp /solution/harness_impl.sh /app/harness.sh
chmod +x /app/tagdiff.sh
chmod +x /app/harness.sh
