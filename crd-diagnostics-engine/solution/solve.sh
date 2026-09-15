#!/bin/bash

set -euo pipefail

cd /app
npm install --silent 2>/dev/null

cp /solution/crd-engine-fixed.ts /app/src/crd-engine.ts
