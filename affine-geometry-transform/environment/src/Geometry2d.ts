
import { Box } from './Box'
import {
	intersectCirclePolygon,
	intersectCirclePolyline,
	intersectLineSegmentPolygon,
	intersectLineSegmentPolyline,
	linesIntersect,
} from './intersect'
import { pointInPolygon } from './utils'
import { Vec, VecLike } from './Vec'

/** @public */
export interface Geometry2dOptions {
	isFilled: boolean
	isClosed: boolean
}

/**
 * Abstract base class for 2D geometries.
 *
 * Subclasses must implement: getVertices(), nearestPoint(), getSvgPathData().
 *
 * Default implementations are provided for hitTestPoint, distanceToPoint,
 * distanceToLineSegment, hitTestLineSegment, intersectLineSegment,
 * intersectCircle, getBounds, and getLength. These defaults operate on the
 * vertices returned by getVertices() and the nearestPoint() implementation.
 */
export abstract class Geometry2d {
	isFilled: boolean
	isClosed: boolean

	constructor(opts: Geometry2dOptions) {
		this.isFilled = opts.isFilled
		this.isClosed = opts.isClosed
	}

	abstract getVertices(): Vec[]
	abstract nearestPoint(point: VecLike): Vec
	abstract getSvgPathData(): string

	hitTestPoint(point: VecLike, margin = 0, hitInside = false): boolean {
		if (
			this.isClosed &&
			(this.isFilled || hitInside) &&
			pointInPolygon(point, this.vertices)
		) {
			return true
		}
		return Vec.Dist2(point, this.nearestPoint(point)) <= margin * margin
	}

	distanceToPoint(point: VecLike, hitInside = false): number {
		return (
			Vec.Dist(point, this.nearestPoint(point)) *
			(this.isClosed &&
			(this.isFilled || hitInside) &&
			pointInPolygon(point, this.vertices)
				? -1
				: 1)
		)
	}

	distanceToLineSegment(A: VecLike, B: VecLike): number {
		if (Vec.Equals(A, B)) return this.distanceToPoint(A, false)
		const { vertices } = this
		if (vertices.length === 0) throw Error('no vertices')
		if (vertices.length === 1) return Vec.Dist(A, vertices[0])
		let nearest: Vec | undefined
		let dist = Infinity
		const nextLimit = this.isClosed ? vertices.length : vertices.length - 1
		for (let i = 0; i < vertices.length; i++) {
			const p = vertices[i]
			if (i < nextLimit) {
				const next = vertices[(i + 1) % vertices.length]
				if (linesIntersect(A, B, p, next)) return 0
			}
			const q = Vec.NearestPointOnLineSegment(A, B, p, true)
			const d = Vec.Dist2(p, q)
			if (d < dist) {
				dist = d
				nearest = q
			}
		}
		if (!nearest) throw Error('nearest point not found')
		dist = Math.sqrt(dist)
		return this.isClosed && this.isFilled && pointInPolygon(nearest, this.vertices)
			? -dist
			: dist
	}

	hitTestLineSegment(A: VecLike, B: VecLike, distance = 0): boolean {
		return this.distanceToLineSegment(A, B) <= distance
	}

	intersectLineSegment(A: VecLike, B: VecLike): VecLike[] {
		const intersections = this.isClosed
			? intersectLineSegmentPolygon(A, B, this.vertices)
			: intersectLineSegmentPolyline(A, B, this.vertices)
		return intersections ?? []
	}

	intersectCircle(center: VecLike, radius: number): VecLike[] {
		const intersections = this.isClosed
			? intersectCirclePolygon(center, radius, this.vertices)
			: intersectCirclePolyline(center, radius, this.vertices)
		return intersections ?? []
	}

	getBounds(): Box {
		return Box.FromPoints(this.vertices)
	}

	getLength(): number {
		const verts = this.getVertices()
		if (verts.length === 0) return 0
		let prev = verts[0]
		let length = 0
		for (let i = 1; i < verts.length; i++) {
			length += Vec.Dist(prev, verts[i])
			prev = verts[i]
		}
		if (this.isClosed) {
			length += Vec.Dist(verts[verts.length - 1], verts[0])
		}
		return length
	}

	getArea(): number {
		if (!this.isClosed) return 0
		const { vertices } = this
		let area = 0
		for (let i = 0, n = vertices.length; i < n; i++) {
			const curr = vertices[i]
			const next = vertices[(i + 1) % n]
			area += curr.x * next.y - next.x * curr.y
		}
		return area / 2
	}

	private _vertices: Vec[] | undefined
	get vertices(): Vec[] {
		if (!this._vertices) {
			this._vertices = this.getVertices()
		}
		return this._vertices
	}

	private _bounds: Box | undefined
	get bounds(): Box {
		if (!this._bounds) {
			this._bounds = this.getBounds()
		}
		return this._bounds
	}

	get center(): Vec {
		return this.bounds.center
	}
}
