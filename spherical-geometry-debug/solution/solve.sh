#!/bin/bash

cd /app

npm install --silent 2>/dev/null

python3 /solution/fix_all.py

npx tsc
