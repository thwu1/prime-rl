#!/bin/bash


cd /app
npm install --quiet 2>/dev/null

# Deploy the correct bufferTime implementation
cp /solution/bufferTime.ts /app/src/bufferTime.ts
