export type Position = [number, number] | [number, number, number];

export interface StreamSink {
  point: (lambda: number, phi: number, z?: number) => void;
  lineStart: () => void;
  lineEnd: () => void;
  polygonStart: () => void;
  polygonEnd: () => void;
  sphere: () => void;
}

export interface GeoPoint { type: "Point"; coordinates: number[]; }
export interface GeoMultiPoint { type: "MultiPoint"; coordinates: number[][]; }
export interface GeoLineString { type: "LineString"; coordinates: number[][]; }
export interface GeoMultiLineString { type: "MultiLineString"; coordinates: number[][][]; }
export interface GeoPolygon { type: "Polygon"; coordinates: number[][][]; }
export interface GeoMultiPolygon { type: "MultiPolygon"; coordinates: number[][][][]; }
export interface GeoSphere { type: "Sphere"; }
export interface GeoGeometryCollection {
  type: "GeometryCollection";
  geometries: GeoGeometry[];
}

export type GeoGeometry =
  | GeoPoint | GeoMultiPoint
  | GeoLineString | GeoMultiLineString
  | GeoPolygon | GeoMultiPolygon
  | GeoGeometryCollection | GeoSphere;

export interface GeoFeature {
  type: "Feature";
  geometry: GeoGeometry;
  properties?: Record<string, unknown>;
}

export interface GeoFeatureCollection {
  type: "FeatureCollection";
  features: GeoFeature[];
}

export type GeoObject = GeoGeometry | GeoFeature | GeoFeatureCollection;
