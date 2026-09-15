#!/usr/bin/env python3
"""
Apply all fixes to the spherical geometry library.

"""

import os

# ============================================================================
# Fix 1: area.ts — two bugs
#   Bug A: phi transformation uses PI/2 instead of PI/4 (Cagnoli's theorem
#          requires half the angular distance from the south pole)
#   Bug B: missing normalization of negative ring area (clockwise-wound
#          polygons produce negative ring sums that must be corrected by
#          adding tau = 2*pi)
# ============================================================================

area_path = "/app/src/area.ts"
with open(area_path, "r") as f:
    area_src = f.read()

# Fix A: correct the phi transformation constant (two occurrences)
area_src = area_src.replace(
    "phi / 2 + Math.PI / 2;",
    "phi / 2 + Math.PI / 4;",
)

# Fix B: add negative-area normalization in polygonEnd
area_src = area_src.replace(
    "areaSum.add(areaRing);",
    "areaSum.add(areaRing < 0 ? tau + areaRing : areaRing);",
)

with open(area_path, "w") as f:
    f.write(area_src)

print("Fixed area.ts")

# ============================================================================
# Fix 2: centroid.ts — one bug
#   The area weight multiplier v should be -w/m (negative), not w/m.
#   Per Brock's inertia tensor for a spherical triangle, the cross-product
#   contribution must be negated so the centroid vector points inward.
# ============================================================================

centroid_path = "/app/src/centroid.ts"
with open(centroid_path, "r") as f:
    centroid_src = f.read()

centroid_src = centroid_src.replace(
    "const v = m !== 0 ? w / m : 0;",
    "const v = m !== 0 ? -w / m : 0;",
)

with open(centroid_path, "w") as f:
    f.write(centroid_src)

print("Fixed centroid.ts")

# ============================================================================
# Fix 3: polygonContains.ts — one bug
#   The sign multiplier for phiArc is inverted. When the XOR condition
#   (antimeridian !== (delta >= 0)) is true, the sign should be -1 (not +1).
# ============================================================================

pc_path = "/app/src/polygonContains.ts"
with open(pc_path, "r") as f:
    pc_src = f.read()

pc_src = pc_src.replace(
    "(antimeridian !== (delta >= 0) ? 1 : -1) * asin(intersection[2])",
    "(antimeridian !== (delta >= 0) ? -1 : 1) * asin(intersection[2])",
)

with open(pc_path, "w") as f:
    f.write(pc_src)

print("Fixed polygonContains.ts")

# ============================================================================
# Fix 4: distance.ts — complete rewrite
#   Replace Euclidean stub with Vincenty formula for great-circle distance.
# ============================================================================

distance_src = '''\
import { abs, atan2, cos, radians, sin, sqrt } from "./math";

export function sphericalDistance(
  a: [number, number],
  b: [number, number]
): number {
  const lambda0 = a[0] * radians;
  const phi0 = a[1] * radians;
  const lambda1 = b[0] * radians;
  const phi1 = b[1] * radians;

  const sinPhi0 = sin(phi0);
  const cosPhi0 = cos(phi0);
  const sinPhi1 = sin(phi1);
  const cosPhi1 = cos(phi1);

  const delta = abs(lambda1 - lambda0);
  const cosDelta = cos(delta);
  const sinDelta = sin(delta);

  const x = cosPhi1 * sinDelta;
  const y = cosPhi0 * sinPhi1 - sinPhi0 * cosPhi1 * cosDelta;
  const z = sinPhi0 * sinPhi1 + cosPhi0 * cosPhi1 * cosDelta;

  return atan2(sqrt(x * x + y * y), z);
}
'''

with open("/app/src/distance.ts", "w") as f:
    f.write(distance_src)

print("Replaced distance.ts")

# ============================================================================
# Fix 5: interpolate.ts — complete rewrite
#   Replace linear stub with proper great-circle (SLERP) interpolation
#   using haversine distance and sin-weighted Cartesian blending.
# ============================================================================

interpolate_src = '''\
import { asin, atan2, cos, degrees, radians, sin, sqrt } from "./math";

function haversin(x: number): number {
  const s = sin(x / 2);
  return s * s;
}

export interface InterpolateResult {
  (t: number): [number, number];
  distance: number;
}

export function sphericalInterpolate(
  a: [number, number],
  b: [number, number]
): InterpolateResult {
  const x0 = a[0] * radians;
  const y0 = a[1] * radians;
  const x1 = b[0] * radians;
  const y1 = b[1] * radians;
  const cy0 = cos(y0);
  const sy0 = sin(y0);
  const cy1 = cos(y1);
  const sy1 = sin(y1);
  const kx0 = cy0 * cos(x0);
  const ky0 = cy0 * sin(x0);
  const kx1 = cy1 * cos(x1);
  const ky1 = cy1 * sin(x1);
  const d = 2 * asin(sqrt(haversin(y1 - y0) + cy0 * cy1 * haversin(x1 - x0)));
  const k = sin(d);

  const fn = (d
    ? function (t: number): [number, number] {
        const td = t * d;
        const B = sin(td) / k;
        const A = sin(d - td) / k;
        const x = A * kx0 + B * kx1;
        const y = A * ky0 + B * ky1;
        const z = A * sy0 + B * sy1;
        return [
          atan2(y, x) * degrees,
          atan2(z, sqrt(x * x + y * y)) * degrees,
        ];
      }
    : function (): [number, number] {
        return [x0 * degrees, y0 * degrees];
      }) as InterpolateResult;

  fn.distance = d;

  return fn;
}
'''

with open("/app/src/interpolate.ts", "w") as f:
    f.write(interpolate_src)

print("Replaced interpolate.ts")
print("All fixes applied successfully.")
