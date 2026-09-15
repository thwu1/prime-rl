
import { Geometry2d } from './Geometry2d'
import { Mat, MatModel } from './Mat'
import { Vec, VecLike } from './Vec'
import { Box } from './Box'
import { pointInPolygon } from './utils'

/**
 * Wraps a Geometry2d with an arbitrary 2×3 affine transformation matrix.
 * Correctly handles non-uniform scaling, shear, rotation, and translation.
 */
export class TransformedGeometry2d extends Geometry2d {
	private readonly inverse: MatModel

	constructor(
		private readonly geometry: Geometry2d,
		private readonly matrix: MatModel
	) {
		super({ isFilled: geometry.isFilled, isClosed: geometry.isClosed })
		this.inverse = Mat.Inverse(matrix)
	}

	getVertices(): Vec[] {
		return this.geometry.getVertices().map((v) => Mat.applyToPoint(this.matrix, v))
	}

	nearestPoint(point: VecLike): Vec {
		// For non-uniform transforms, we MUST work with world-space edges.
		// The naive transform-to-local approach gives incorrect nearest points
		// because the metric is distorted by non-uniform scaling.
		const verts = this.vertices
		if (verts.length === 0) return new Vec(0, 0)
		if (verts.length === 1) return verts[0].clone()

		let bestDist2 = Infinity
		let bestX = verts[0].x
		let bestY = verts[0].y

		const limit = this.isClosed ? verts.length : verts.length - 1
		for (let i = 0; i < limit; i++) {
			const a = verts[i]
			const b = verts[(i + 1) % verts.length]
			const dx = b.x - a.x
			const dy = b.y - a.y
			const len2 = dx * dx + dy * dy

			let nx: number, ny: number
			if (len2 === 0) {
				nx = a.x
				ny = a.y
			} else {
				const t = ((point.x - a.x) * dx + (point.y - a.y) * dy) / len2
				if (t <= 0) {
					nx = a.x
					ny = a.y
				} else if (t >= 1) {
					nx = b.x
					ny = b.y
				} else {
					nx = a.x + dx * t
					ny = a.y + dy * t
				}
			}

			const ex = point.x - nx
			const ey = point.y - ny
			const d2 = ex * ex + ey * ey
			if (d2 < bestDist2) {
				bestDist2 = d2
				bestX = nx
				bestY = ny
			}
		}

		return new Vec(bestX, bestY)
	}

	override hitTestPoint(
		point: VecLike,
		margin = 0,
		hitInside = false
	): boolean {
		// Check containment first
		if (
			this.isClosed &&
			(this.isFilled || hitInside) &&
			pointInPolygon(point, this.vertices)
		) {
			return true
		}
		// Margin check uses world-space distance
		if (margin <= 0) return false
		return Vec.Dist2(point, this.nearestPoint(point)) <= margin * margin
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

	override getBounds(): Box {
		return Box.FromPoints(this.vertices)
	}

	transform(matrix: MatModel): TransformedGeometry2d {
		return new TransformedGeometry2d(
			this.geometry,
			Mat.Multiply(matrix, this.matrix)
		)
	}

	getSvgPathData(): string {
		return ''
	}
}
