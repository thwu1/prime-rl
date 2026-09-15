import { radians } from "./math";

export interface InterpolateResult {
  (t: number): [number, number];
  distance: number;
}

export function sphericalInterpolate(
  a: [number, number],
  b: [number, number]
): InterpolateResult {
  const fn = function (t: number): [number, number] {
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  } as InterpolateResult;

  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  fn.distance = Math.sqrt(dx * dx + dy * dy) * radians;

  return fn;
}
