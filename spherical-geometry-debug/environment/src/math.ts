export const epsilon = 1e-6;
export const epsilon2 = 1e-12;
export const pi = Math.PI;
export const halfPi = pi / 2;
export const quarterPi = pi / 4;
export const tau = pi * 2;
export const degrees = 180 / pi;
export const radians = pi / 180;

export const abs = Math.abs;
export const atan = Math.atan;
export const atan2 = Math.atan2;
export const cos = Math.cos;
export const ceil = Math.ceil;
export const exp = Math.exp;
export const floor = Math.floor;
export const hypot = Math.hypot;
export const log = Math.log;
export const pow = Math.pow;
export const sin = Math.sin;
export const sign = Math.sign;
export const sqrt = Math.sqrt;
export const tan = Math.tan;

export function acos(x: number): number {
  return x > 1 ? 0 : x < -1 ? pi : Math.acos(x);
}

export function asin(x: number): number {
  return x > 1 ? halfPi : x < -1 ? -halfPi : Math.asin(x);
}

export function haversin(x: number): number {
  const s = sin(x / 2);
  return s * s;
}
