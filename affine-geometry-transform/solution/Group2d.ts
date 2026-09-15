
import { Geometry2d } from './Geometry2d'
import { Vec, VecLike } from './Vec'
import { Box } from './Box'

/**
 * A composite geometry that contains multiple child geometries.
 * Operations delegate to children and combine results.
 */
export class Group2d extends Geometry2d {
	public readonly children: Geometry2d[]

	constructor(config: { children: Geometry2d[] }) {
		super({ isFilled: false, isClosed: true })
		this.children = config.children
		if (this.children.length === 0) {
			throw new Error('Group2d must have at least one child')
		}
	}

	getVertices(): Vec[] {
		return this.children.flatMap((c) => c.getVertices())
	}

	nearestPoint(point: VecLike): Vec {
		let bestDist2 = Infinity
		let bestPoint: Vec | undefined

		for (const child of this.children) {
			const p = child.nearestPoint(point)
			const d2 = Vec.Dist2(p, point)
			if (d2 < bestDist2) {
				bestDist2 = d2
				bestPoint = p
			}
		}

		if (!bestPoint) throw new Error('No children in Group2d')
		return bestPoint
	}

	override hitTestPoint(
		point: VecLike,
		margin = 0,
		hitInside = false
	): boolean {
		return this.children.some((c) => c.hitTestPoint(point, margin, hitInside))
	}

	override distanceToPoint(point: VecLike, hitInside = false): number {
		let minDist = Infinity
		for (const child of this.children) {
			const d = child.distanceToPoint(point, hitInside)
			if (Math.abs(d) < Math.abs(minDist) || (d < 0 && minDist > 0)) {
				minDist = d
			}
		}
		return minDist
	}

	override getBounds(): Box {
		if (this.children.length === 0) return new Box()
		let box = this.children[0].getBounds().clone()
		for (let i = 1; i < this.children.length; i++) {
			box.expand(this.children[i].getBounds())
		}
		return box
	}

	override intersectLineSegment(A: VecLike, B: VecLike): VecLike[] {
		return this.children.flatMap((c) => c.intersectLineSegment(A, B))
	}

	override intersectCircle(center: VecLike, radius: number): VecLike[] {
		return this.children.flatMap((c) => c.intersectCircle(center, radius))
	}

	getSvgPathData(): string {
		return ''
	}
}
