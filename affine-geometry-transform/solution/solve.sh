#!/bin/bash

set -euo pipefail

# Install Node.js dependencies
cd /app && npm install --ignore-scripts 2>/dev/null

# Fix off-by-one bug in intersectLineSegmentPolygon
# The polygon version incorrectly uses the polyline loop bound (points.length - 1),
# which skips the closing edge of the polygon.
python3 -c "
with open('/app/src/intersect.ts', 'r') as f:
    lines = f.readlines()
in_fn = False
for i, line in enumerate(lines):
    if 'function intersectLineSegmentPolygon' in line:
        in_fn = True
    if in_fn and 'points.length - 1' in line:
        lines[i] = line.replace('points.length - 1', 'points.length')
        break
with open('/app/src/intersect.ts', 'w') as f:
    f.writelines(lines)
"

# Copy solution implementations
cp /solution/TransformedGeometry2d.ts /app/src/TransformedGeometry2d.ts
cp /solution/Group2d.ts /app/src/Group2d.ts
cp /solution/ellipseIntersect.ts /app/src/ellipseIntersect.ts
