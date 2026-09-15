import { GeoObject, StreamSink } from "./types";

function streamGeometry(geometry: any, stream: StreamSink): void {
  if (geometry && streamGeometryType.hasOwnProperty(geometry.type)) {
    streamGeometryType[geometry.type](geometry, stream);
  }
}

const streamObjectType: Record<string, (object: any, stream: StreamSink) => void> = {
  Feature(object, stream) {
    streamGeometry(object.geometry, stream);
  },
  FeatureCollection(object, stream) {
    const features = object.features;
    for (let i = 0; i < features.length; i++) {
      streamGeometry(features[i].geometry, stream);
    }
  }
};

const streamGeometryType: Record<string, (object: any, stream: StreamSink) => void> = {
  Sphere(_object, stream) {
    stream.sphere();
  },
  Point(object, stream) {
    const c = object.coordinates;
    stream.point(c[0], c[1], c[2]);
  },
  MultiPoint(object, stream) {
    const coords = object.coordinates;
    for (let i = 0; i < coords.length; i++) {
      stream.point(coords[i][0], coords[i][1], coords[i][2]);
    }
  },
  LineString(object, stream) {
    streamLine(object.coordinates, stream, 0);
  },
  MultiLineString(object, stream) {
    const coords = object.coordinates;
    for (let i = 0; i < coords.length; i++) {
      streamLine(coords[i], stream, 0);
    }
  },
  Polygon(object, stream) {
    streamPolygon(object.coordinates, stream);
  },
  MultiPolygon(object, stream) {
    const coords = object.coordinates;
    for (let i = 0; i < coords.length; i++) {
      streamPolygon(coords[i], stream);
    }
  },
  GeometryCollection(object, stream) {
    const geometries = object.geometries;
    for (let i = 0; i < geometries.length; i++) {
      streamGeometry(geometries[i], stream);
    }
  }
};

function streamLine(coordinates: number[][], stream: StreamSink, closed: number): void {
  const n = coordinates.length - closed;
  stream.lineStart();
  for (let i = 0; i < n; i++) {
    const c = coordinates[i];
    stream.point(c[0], c[1], c[2]);
  }
  stream.lineEnd();
}

function streamPolygon(coordinates: number[][][], stream: StreamSink): void {
  stream.polygonStart();
  for (let i = 0; i < coordinates.length; i++) {
    streamLine(coordinates[i], stream, 1);
  }
  stream.polygonEnd();
}

export function geoStream(object: GeoObject, stream: StreamSink): void {
  if (object && streamObjectType.hasOwnProperty((object as any).type)) {
    streamObjectType[(object as any).type](object, stream);
  } else {
    streamGeometry(object, stream);
  }
}
