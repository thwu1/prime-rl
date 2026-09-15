#!/bin/bash

# Install the corrected pre-receive hook
cp /solution/pre-receive-fixed.sh /app/hooks/pre-receive
chmod +x /app/hooks/pre-receive
