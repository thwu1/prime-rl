
import { Box } from './Box'
import { intersectLineSegmentCircle } from './intersect'
import { Vec, VecLike } from './Vec'
import { Geometry2d, Geometry2dOptions } from './Geometry2d'
import { pointInPolygon } from './utils'

const PI2 = Math.PI * 2
const CIRCLE_VERTEX_COUNT = 64

/** Circle geometry. Center is at (radius, radius) in local space by default. */
export class Circle2d extends Geometry2d {
	private _center: Vec
	private _radius: number
	private _x: number
	private _y: number

	constructor(
		config: Omit<Geometry2dOptions, 'isClosed'> & {
			x?: number
			y?: number
			radius: number
			isFilled: boolean
		}
	) {
		super({ isClosed: true, ...config })
		const { x = 0, y = 0, radius } = config
		this._x = x
		this._y = y
		this._center = new Vec(radius + x, radius + y)
		this._radius = radius
	}

	get circleCenter(): Vec {
		return this._center
	}

	get radius(): number {
		return this._radius
	}

	override getBounds(): Box {
		return new Box(this._x, this._y, this._radius * 2, this._radius * 2)
	}

	getVertices(): Vec[] {
		const { _center, _radius: radius } = this
		const n = CIRCLE_VERTEX_COUNT
		const vertices: Vec[] = []
		for (let i = 0; i < n; i++) {
			const angle = (i / n) * PI2
			vertices.push(
				new Vec(
					_center.x + radius * Math.cos(angle),
					_center.y + radius * Math.sin(angle)
				)
			)
		}
		return vertices
	}

	nearestPoint(point: VecLike): Vec {
		const { _center, _radius: radius } = this
		const dx = point.x - _center.x
		const dy = point.y - _center.y
		const len = Math.sqrt(dx * dx + dy * dy)
		if (len === 0) return new Vec(_center.x + radius, _center.y)
		const scale = radius / len
		return new Vec(_center.x + dx * scale, _center.y + dy * scale)
	}

	override distanceToPoint(point: VecLike, hitInside = false): number {
		const { _center, _radius: radius } = this
		const dx = point.x - _center.x
		const dy = point.y - _center.y
		const dist = Math.sqrt(dx * dx + dy * dy)
		const distToEdge = dist - radius
		if (distToEdge < 0 && (this.isFilled || hitInside)) {
			return distToEdge
		}
		return Math.abs(distToEdge)
	}

	override hitTestPoint(point: VecLike, margin = 0, hitInside = false): boolean {
		const { _center, _radius: radius } = this
		const dx = point.x - _center.x
		const dy = point.y - _center.y
		const dist2 = dx * dx + dy * dy
		if ((this.isFilled || hitInside) && dist2 <= radius * radius) {
			return true
		}
		const outerR = radius + margin
		if (dist2 > outerR * outerR) return false
		const innerR = radius - margin
		if (innerR <= 0) return true
		return dist2 >= innerR * innerR
	}

	override hitTestLineSegment(A: VecLike, B: VecLike, distance = 0): boolean {
		return (
			intersectLineSegmentCircle(A, B, this._center, this._radius + distance) !== null
		)
	}

	getSvgPathData(): string {
		return ''
	}
}
