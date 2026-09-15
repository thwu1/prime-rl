import { polygonContains } from "./polygonContains";
import { sphericalDistance } from "./distance";
import { epsilon2, radians } from "./math";
import { GeoObject } from "./types";

function containsGeometry(
  geometry: any,
  point: [number, number]
): boolean {
  if (!geometry) return false;
  switch (geometry.type) {
    case "Sphere":
      return true;
    case "Point":
      return containsPoint(geometry.coordinates, point);
    case "MultiPoint": {
      const coords = geometry.coordinates;
      for (let i = 0; i < coords.length; i++) {
        if (containsPoint(coords[i], point)) return true;
      }
      return false;
    }
    case "LineString":
      return containsLine(geometry.coordinates, point);
    case "MultiLineString": {
      const coords = geometry.coordinates;
      for (let i = 0; i < coords.length; i++) {
        if (containsLine(coords[i], point)) return true;
      }
      return false;
    }
    case "Polygon":
      return containsPolygon(geometry.coordinates, point);
    case "MultiPolygon": {
      const coords = geometry.coordinates;
      for (let i = 0; i < coords.length; i++) {
        if (containsPolygon(coords[i], point)) return true;
      }
      return false;
    }
    case "GeometryCollection": {
      const geoms = geometry.geometries;
      for (let i = 0; i < geoms.length; i++) {
        if (containsGeometry(geoms[i], point)) return true;
      }
      return false;
    }
    default:
      return false;
  }
}

function containsPoint(
  coordinates: number[],
  point: [number, number]
): boolean {
  return (
    sphericalDistance(
      coordinates as [number, number],
      point
    ) === 0
  );
}

function containsLine(
  coordinates: number[][],
  point: [number, number]
): boolean {
  let ao = 0;
  let bo: number;
  for (let i = 0; i < coordinates.length; i++) {
    bo = sphericalDistance(coordinates[i] as [number, number], point);
    if (bo === 0) return true;
    if (i > 0) {
      const ab = sphericalDistance(
        coordinates[i] as [number, number],
        coordinates[i - 1] as [number, number]
      );
      if (
        ab > 0 &&
        ao <= ab &&
        bo <= ab &&
        (ao + bo - ab) * (1 - Math.pow((ao - bo) / ab, 2)) <
          epsilon2 * ab
      ) {
        return true;
      }
    }
    ao = bo;
  }
  return false;
}

function containsPolygon(
  coordinates: number[][][],
  point: [number, number]
): boolean {
  const rings = coordinates.map(ringRadians);
  const pt: [number, number] = [
    point[0] * radians,
    point[1] * radians
  ];
  return polygonContains(rings, pt) !== 0;
}

function ringRadians(ring: number[][]): [number, number][] {
  const result: [number, number][] = ring.map(
    (p) => [p[0] * radians, p[1] * radians] as [number, number]
  );
  result.pop();
  return result;
}

export function sphericalContains(
  object: GeoObject,
  point: [number, number]
): boolean {
  const obj = object as any;
  if (obj && obj.type === "Feature") {
    return containsGeometry(obj.geometry, point);
  } else if (obj && obj.type === "FeatureCollection") {
    const features = obj.features;
    for (let i = 0; i < features.length; i++) {
      if (containsGeometry(features[i].geometry, point)) return true;
    }
    return false;
  } else {
    return containsGeometry(obj, point);
  }
}
