import { cartesian, cartesianCross, cartesianNormalizeInPlace } from "./cartesian";
import { abs, asin, atan2, cos, epsilon, epsilon2, halfPi, pi, quarterPi, sign, sin, tau } from "./math";
import { Adder } from "./adder";

function longitude(point: [number, number]): number {
  return abs(point[0]) <= pi
    ? point[0]
    : sign(point[0]) * ((abs(point[0]) + pi) % tau - pi);
}

export function polygonContains(
  polygon: [number, number][][],
  point: [number, number]
): number {
  const lambda = longitude(point);
  let phi = point[1];
  const sinPhi = sin(phi);
  const normal: [number, number, number] = [sin(lambda), -cos(lambda), 0];
  let angle = 0;
  let winding = 0;

  const sum = new Adder();

  if (sinPhi === 1) phi = halfPi + epsilon;
  else if (sinPhi === -1) phi = -halfPi - epsilon;

  for (let i = 0, n = polygon.length; i < n; ++i) {
    const ring = polygon[i];
    const m = ring.length;
    if (!m) continue;

    let point0 = ring[m - 1];
    let lambda0 = longitude(point0);
    let phi0 = point0[1] / 2 + quarterPi;
    let sinPhi0 = sin(phi0);
    let cosPhi0 = cos(phi0);

    for (let j = 0; j < m; ++j) {
      const point1 = ring[j];
      const lambda1 = longitude(point1);
      const phi1 = point1[1] / 2 + quarterPi;
      const sinPhi1 = sin(phi1);
      const cosPhi1 = cos(phi1);
      const delta = lambda1 - lambda0;
      const sgn = delta >= 0 ? 1 : -1;
      const absDelta = sgn * delta;
      const antimeridian = absDelta > pi;
      const k = sinPhi0 * sinPhi1;

      sum.add(
        atan2(
          k * sgn * sin(absDelta),
          cosPhi0 * cosPhi1 + k * cos(absDelta)
        )
      );
      angle += antimeridian ? delta + sgn * tau : delta;

      if (
        (antimeridian !== (lambda0 >= lambda)) !==
        (lambda1 >= lambda)
      ) {
        const arc = cartesianCross(cartesian(point0), cartesian(point1));
        cartesianNormalizeInPlace(arc);
        const intersection = cartesianCross(normal, arc);
        cartesianNormalizeInPlace(intersection);
        const phiArc =
          (antimeridian !== (delta >= 0) ? 1 : -1) * asin(intersection[2]);
        if (phi > phiArc || (phi === phiArc && (arc[0] || arc[1]))) {
          winding += antimeridian !== (delta >= 0) ? 1 : -1;
        }
      }

      lambda0 = lambda1;
      sinPhi0 = sinPhi1;
      cosPhi0 = cosPhi1;
      point0 = point1;
    }
  }

  const southPoleInside =
    angle < -epsilon || (angle < epsilon && +sum < -epsilon2);
  return (southPoleInside ? 1 : 0) ^ (winding & 1);
}
