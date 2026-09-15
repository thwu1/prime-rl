
import { pointInPolygon } from './utils'
import { Vec, VecLike } from './Vec'
import { Edge2d } from './Edge2d'
import { Geometry2d, Geometry2dOptions } from './Geometry2d'

/** Open polyline through a sequence of points. */
export class Polyline2d extends Geometry2d {
	protected _points: Vec[]
	private _segments?: Edge2d[]

	constructor(
		config: Omit<Geometry2dOptions, 'isFilled' | 'isClosed'> & { points: Vec[] }
	) {
		super({ isClosed: false, isFilled: false, ...config })
		this._points = config.points
		if (config.points.length < 2) {
			throw new Error('Polyline2d requires at least 2 points')
		}
	}

	protected get segments(): Edge2d[] {
		if (!this._segments) {
			this._segments = []
			const { vertices } = this
			for (let i = 0, n = vertices.length - 1; i < n; i++) {
				this._segments.push(new Edge2d({ start: vertices[i], end: vertices[i + 1] }))
			}
			if (this.isClosed) {
				this._segments.push(
					new Edge2d({ start: vertices[vertices.length - 1], end: vertices[0] })
				)
			}
		}
		return this._segments
	}

	override getLength(): number {
		return this.segments.reduce((acc, seg) => acc + seg.getLength(), 0)
	}

	getVertices(): Vec[] {
		return this._points
	}

	nearestPoint(A: VecLike): Vec {
		const { vertices } = this
		let bestX = vertices[0].x
		let bestY = vertices[0].y
		let bestDist2 = (A.x - bestX) ** 2 + (A.y - bestY) ** 2

		const limit = this.isClosed ? vertices.length : vertices.length - 1
		for (let i = 0; i < limit; i++) {
			const start = vertices[i]
			const end = vertices[(i + 1) % vertices.length]
			const dx = end.x - start.x
			const dy = end.y - start.y
			const len2 = dx * dx + dy * dy

			let nx: number, ny: number
			if (len2 === 0) {
				nx = start.x
				ny = start.y
			} else {
				const t = ((A.x - start.x) * dx + (A.y - start.y) * dy) / len2
				if (t <= 0) {
					nx = start.x
					ny = start.y
				} else if (t >= 1) {
					nx = end.x
					ny = end.y
				} else {
					nx = start.x + dx * t
					ny = start.y + dy * t
				}
			}

			const ex = A.x - nx
			const ey = A.y - ny
			const d2 = ex * ex + ey * ey
			if (d2 < bestDist2) {
				bestX = nx
				bestY = ny
				bestDist2 = d2
			}
		}

		return new Vec(bestX, bestY)
	}

	override hitTestPoint(point: VecLike, margin = 0, hitInside = false): boolean {
		return this.distanceToPoint(point, hitInside) <= margin
	}

	override distanceToPoint(point: VecLike, hitInside = false): number {
		const nearest = this.nearestPoint(point)
		const dist = Vec.Dist(point, nearest)
		if (
			this.isClosed &&
			(this.isFilled || hitInside) &&
			pointInPolygon(point, this.vertices)
		) {
			return -dist
		}
		return dist
	}

	getSvgPathData(): string {
		return ''
	}
}
