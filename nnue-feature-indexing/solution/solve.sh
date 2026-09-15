#!/bin/bash

# Copy the reference implementation to /app/
cp /solution/nnue_features.py /app/nnue_features.py

# Verify it loads correctly
python3 -c "
import sys
sys.path.insert(0, '/app')
from nnue_features import (
    parse_fen, active_features, make_move,
    needs_refresh, feature_delta, feature_index, king_bucket
)
# Smoke test: starting position
pos = parse_fen('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1')
b, f = active_features(pos, True)
assert b == 3
assert len(f) == 32
# Verify e2e4
pos2 = make_move(pos, 'e2e4')
b2, f2 = active_features(pos2, True)
assert len(f2) == 32
print('Solution verified successfully')
"
