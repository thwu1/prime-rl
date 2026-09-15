import { atan2, cos, radians, sin, tau } from "./math";
import { geoStream } from "./stream";
import { GeoObject, StreamSink } from "./types";
import { Adder } from "./adder";

let areaSum: Adder;
let areaRingSum: Adder;
let lambda00a: number;
let phi00a: number;
let lambda0a: number;
let cosPhi0a: number;
let sinPhi0a: number;

function noop(): void {}

const areaStream: StreamSink = {
  point: noop,
  lineStart: noop,
  lineEnd: noop,
  polygonStart(): void {
    areaRingSum = new Adder();
    areaStream.lineStart = areaRingStart;
    areaStream.lineEnd = areaRingEnd;
  },
  polygonEnd(): void {
    const areaRing = +areaRingSum;
    areaSum.add(areaRing);
    areaStream.lineStart = noop;
    areaStream.lineEnd = noop;
    areaStream.point = noop;
  },
  sphere(): void {
    areaSum.add(tau);
  }
};

function areaRingStart(): void {
  areaStream.point = areaPointFirst;
}

function areaRingEnd(): void {
  areaPoint(lambda00a, phi00a);
}

function areaPointFirst(lambda: number, phi: number): void {
  areaStream.point = areaPoint;
  lambda00a = lambda;
  phi00a = phi;
  lambda *= radians;
  phi *= radians;
  lambda0a = lambda;
  const p = phi / 2 + Math.PI / 2;
  cosPhi0a = cos(p);
  sinPhi0a = sin(p);
}

function areaPoint(lambda: number, phi: number): void {
  lambda *= radians;
  phi *= radians;
  phi = phi / 2 + Math.PI / 2;

  const dLambda = lambda - lambda0a;
  const sdLambda = dLambda >= 0 ? 1 : -1;
  const adLambda = sdLambda * dLambda;
  const cosPhi = cos(phi);
  const sinPhi = sin(phi);
  const k = sinPhi0a * sinPhi;
  const u = cosPhi0a * cosPhi + k * cos(adLambda);
  const v = k * sdLambda * sin(adLambda);
  areaRingSum.add(atan2(v, u));

  lambda0a = lambda;
  cosPhi0a = cosPhi;
  sinPhi0a = sinPhi;
}

export function sphericalArea(object: GeoObject): number {
  areaSum = new Adder();
  geoStream(object, areaStream);
  return +areaSum * 2;
}

export { areaRingSum, areaStream };
