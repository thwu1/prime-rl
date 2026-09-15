import { Vector } from "../vector.js";

export function lerp(a: Vector, b: Vector, t: number): Vector {
  return a.scale(1 - t).add(b.scale(t));
}

export function lerpScalar(a: number, b: number, t: number): number {
  return a * (1 - t) + b * t;
}
