import { Vector } from "../vector.js";

export function rotate2D(v: Vector, angleRad: number): Vector {
  if (v.dimension !== 2) throw new Error("rotate2D requires 2D vector");
  const [x, y] = v.components;
  const cos = Math.cos(angleRad);
  const sin = Math.sin(angleRad);
  return new Vector([x * cos - y * sin, x * sin + y * cos]);
}

export function scale(v: Vector, factors: number[]): Vector {
  if (v.dimension !== factors.length) throw new Error("Dimension mismatch");
  return new Vector(v.components.map((c, i) => c * factors[i]));
}
