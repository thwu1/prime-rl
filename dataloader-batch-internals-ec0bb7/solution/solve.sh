#!/bin/bash

cd /app

# Fix jest.config.js: remove empty transform override that disables ts-jest preset
cat > jest.config.js << 'JEST_EOF'
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  testMatch: ['**/__tests__/**/*.test.ts'],
};
JEST_EOF

# Fix tsconfig.json: change module from esnext to commonjs
python3 -c "
import json
with open('tsconfig.json', 'r') as f:
    config = json.load(f)
config['compilerOptions']['module'] = 'commonjs'
with open('tsconfig.json', 'w') as f:
    json.dump(config, f, indent=2)
"

# Install dependencies
npm install 2>/dev/null

# Fix dataloader.ts (6 bugs)
cp /solution/dataloader_fixed.ts /app/src/dataloader.ts

# Fix lru-cache.ts (get() must promote to MRU on access)
cp /solution/lru_cache_fixed.ts /app/src/lru-cache.ts

# Fix batch-coalescer.ts (scheduling pattern + flush lifecycle)
cp /solution/batch_coalescer_fixed.ts /app/src/batch-coalescer.ts

# Fix request-scope.ts (scheduler wiring + LRU cache + dispose lifecycle)
cp /solution/request_scope_fixed.ts /app/src/request-scope.ts
