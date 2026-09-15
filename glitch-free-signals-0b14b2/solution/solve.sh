#!/bin/bash

cp /solution/graph_fixed.ts /app/src/graph.ts
cp /solution/signal_fixed.ts /app/src/signal.ts
cp /solution/computed_fixed.ts /app/src/computed.ts
cp /solution/effect_fixed.ts /app/src/effect.ts
cp /solution/untracked_fixed.ts /app/src/untracked.ts

cd /app && npm install 2>/dev/null 1>/dev/null
