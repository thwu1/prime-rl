import { asin, atan2, cos, degrees, epsilon, epsilon2, hypot, radians, sin } from "./math";
import { geoStream } from "./stream";
import { GeoObject, StreamSink } from "./types";
import { Adder } from "./adder";

let W0: number, W1: number;
let X0: number, Y0: number, Z0: number;
let X1: number, Y1: number, Z1: number;
let X2: Adder, Y2: Adder, Z2: Adder;
let lambda00c: number, phi00c: number;
let x0c: number, y0c: number, z0c: number;

function noop(): void {}

const centroidStream: StreamSink = {
  sphere: noop,
  point: centroidPoint,
  lineStart: centroidLineStart,
  lineEnd: centroidLineEnd,
  polygonStart(): void {
    centroidStream.lineStart = centroidRingStart;
    centroidStream.lineEnd = centroidRingEnd;
  },
  polygonEnd(): void {
    centroidStream.lineStart = centroidLineStart;
    centroidStream.lineEnd = centroidLineEnd;
  }
};

function centroidPoint(lambda: number, phi: number): void {
  lambda *= radians;
  phi *= radians;
  const cosPhi = cos(phi);
  centroidPointCartesian(cosPhi * cos(lambda), cosPhi * sin(lambda), sin(phi));
}

function centroidPointCartesian(x: number, y: number, z: number): void {
  ++W0;
  X0 += (x - X0) / W0;
  Y0 += (y - Y0) / W0;
  Z0 += (z - Z0) / W0;
}

function centroidLineStart(): void {
  centroidStream.point = centroidLinePointFirst;
}

function centroidLinePointFirst(lambda: number, phi: number): void {
  lambda *= radians;
  phi *= radians;
  const cosPhi = cos(phi);
  x0c = cosPhi * cos(lambda);
  y0c = cosPhi * sin(lambda);
  z0c = sin(phi);
  centroidStream.point = centroidLinePoint;
  centroidPointCartesian(x0c, y0c, z0c);
}

function centroidLinePoint(lambda: number, phi: number): void {
  lambda *= radians;
  phi *= radians;
  const cosPhi = cos(phi);
  const x = cosPhi * cos(lambda);
  const y = cosPhi * sin(lambda);
  const z = sin(phi);
  const wx = y0c * z - z0c * y;
  const wy = z0c * x - x0c * z;
  const wz = x0c * y - y0c * x;
  const wLen = Math.sqrt(wx * wx + wy * wy + wz * wz);
  const weight = atan2(wLen, x0c * x + y0c * y + z0c * z);
  W1 += weight;
  X1 += weight * (x0c + (x0c = x));
  Y1 += weight * (y0c + (y0c = y));
  Z1 += weight * (z0c + (z0c = z));
  centroidPointCartesian(x0c, y0c, z0c);
}

function centroidLineEnd(): void {
  centroidStream.point = centroidPoint;
}

function centroidRingStart(): void {
  centroidStream.point = centroidRingPointFirst;
}

function centroidRingEnd(): void {
  centroidRingPoint(lambda00c, phi00c);
  centroidStream.point = centroidPoint;
}

function centroidRingPointFirst(lambda: number, phi: number): void {
  lambda00c = lambda;
  phi00c = phi;
  lambda *= radians;
  phi *= radians;
  centroidStream.point = centroidRingPoint;
  const cosPhi = cos(phi);
  x0c = cosPhi * cos(lambda);
  y0c = cosPhi * sin(lambda);
  z0c = sin(phi);
  centroidPointCartesian(x0c, y0c, z0c);
}

function centroidRingPoint(lambda: number, phi: number): void {
  lambda *= radians;
  phi *= radians;
  const cosPhi = cos(phi);
  const x = cosPhi * cos(lambda);
  const y = cosPhi * sin(lambda);
  const z = sin(phi);
  const cx = y0c * z - z0c * y;
  const cy = z0c * x - x0c * z;
  const cz = x0c * y - y0c * x;
  const m = hypot(cx, cy, cz);
  const w = asin(m);
  const v = m !== 0 ? w / m : 0;
  X2.add(v * cx);
  Y2.add(v * cy);
  Z2.add(v * cz);
  W1 += w;
  X1 += w * (x0c + (x0c = x));
  Y1 += w * (y0c + (y0c = y));
  Z1 += w * (z0c + (z0c = z));
  centroidPointCartesian(x0c, y0c, z0c);
}

export function sphericalCentroid(object: GeoObject): [number, number] {
  W0 = W1 = X0 = Y0 = Z0 = X1 = Y1 = Z1 = 0;
  X2 = new Adder();
  Y2 = new Adder();
  Z2 = new Adder();
  geoStream(object, centroidStream);

  let x = +X2;
  let y = +Y2;
  let z = +Z2;
  let m = hypot(x, y, z);

  if (m < epsilon2) {
    x = X1;
    y = Y1;
    z = Z1;
    if (W1 < epsilon) {
      x = X0;
      y = Y0;
      z = Z0;
    }
    m = hypot(x, y, z);
    if (m < epsilon2) return [NaN, NaN];
  }

  return [atan2(y, x) * degrees, asin(z / m) * degrees];
}
