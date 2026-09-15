import { Position } from './types';

/**
 * Finds the magnitude of the cross product of two vectors (if we pretend
 * they're in three dimensions)
 *
 * @param {Position} a First vector
 * @param {Position} b Second vector
 * @private
 * @returns {number} The magnitude of the cross product
 */
function crossProduct(a: Position, b: Position): number {
  return (a[0] * b[1]) - (a[1] * b[0]);
}

/**
 * Finds the dot product of two vectors.
 *
 * @param {Position} a First vector
 * @param {Position} b Second vector
 * @private
 * @returns {number} The dot product
 */
function dotProduct(a: Position, b: Position): number {
  return (a[0] * b[0]) + (a[1] * b[1]);
}

/**
 * Finds the intersection (if any) between two line segments a and b, given the
 * line segments' end points a1, a2 and b1, b2.
 *
 * This algorithm is based on Schneider and Eberly.
 * http://www.cimec.org.ar/~ncalvo/Schneider_Eberly.pdf
 * Page 244.
 *
 * @param {Position} a1 point of first line
 * @param {Position} a2 point of first line
 * @param {Position} b1 point of second line
 * @param {Position} b2 point of second line
 * @param {boolean=} noEndpointTouch whether to skip single touchpoints
 *                                         (meaning connected segments) as
 *                                         intersections
 * @returns {Position[]|null} If the lines intersect, the point of
 * intersection. If they overlap, the two end points of the overlapping segment.
 * Otherwise, null.
 */
export default function segmentIntersection(a1: Position, a2: Position, b1: Position, b2: Position, noEndpointTouch?: boolean): Position[] | null {
  const va: Position = [a2[0] - a1[0], a2[1] - a1[1]];
  const vb: Position = [b2[0] - b1[0], b2[1] - b1[1]];

  function toPoint(p: Position, s: number, d: Position): Position {
    return [
      p[0] + s * d[0],
      p[1] + s * d[1]
    ];
  }

  const e: Position = [b1[0] - a1[0], b1[1] - a1[1]];
  let kross    = crossProduct(va, vb);
  let sqrKross = kross * kross;
  const sqrLenA  = dotProduct(va, va);

  if (sqrKross > 0) {
    const s = crossProduct(e, vb) / kross;
    if (s < 0 || s > 1) {
      return null;
    }
    const t = crossProduct(e, va) / kross;
    if (t < 0 || t > 1) {
      return null;
    }
    if (s === 0 || s === 1) {
      return noEndpointTouch ? null : [toPoint(a1, s, va)];
    }
    if (t === 0 || t === 1) {
      return noEndpointTouch ? null : [toPoint(b1, t, vb)];
    }
    return [toPoint(a1, s, va)];
  }

  kross = crossProduct(e, va);
  sqrKross = kross * kross;

  if (sqrKross > 0) {
    return null;
  }

  const sa = dotProduct(va, e) / sqrLenA;
  const sb = sa + dotProduct(va, vb) / sqrLenA;
  const smin = Math.min(sa, sb);
  const smax = Math.max(sa, sb);

  if (smin <= 1 && smax >= 0) {

    if (smin === 1) {
      return noEndpointTouch ? null : [toPoint(a1, smin > 0 ? smin : 0, va)];
    }

    if (smax === 0) {
      return noEndpointTouch ? null : [toPoint(a1, smax < 1 ? smax : 1, va)];
    }

    if (noEndpointTouch && smin === 0 && smax === 1) return null;

    return [
      toPoint(a1, smin > 0 ? smin : 0, va),
      toPoint(a1, smax < 1 ? smax : 1, va)
    ];
  }

  return null;
}
