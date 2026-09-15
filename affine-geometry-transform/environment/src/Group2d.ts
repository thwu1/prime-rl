
import { Geometry2d } from './Geometry2d'
import { Vec, VecLike } from './Vec'
import { Box } from './Box'

/**
 * A composite geometry that contains multiple child geometries.
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
		// TODO
		throw new Error('Group2d.getVertices not implemented')
	}

	nearestPoint(point: VecLike): Vec {
		// TODO
		throw new Error('Group2d.nearestPoint not implemented')
	}

	override hitTestPoint(
		point: VecLike,
		margin?: number,
		hitInside?: boolean
	): boolean {
		// TODO
		throw new Error('Group2d.hitTestPoint not implemented')
	}

	override distanceToPoint(point: VecLike, hitInside?: boolean): number {
		// TODO
		throw new Error('Group2d.distanceToPoint not implemented')
	}

	override getBounds(): Box {
		// TODO
		throw new Error('Group2d.getBounds not implemented')
	}

	override intersectLineSegment(A: VecLike, B: VecLike): VecLike[] {
		// TODO
		throw new Error('Group2d.intersectLineSegment not implemented')
	}

	override intersectCircle(center: VecLike, radius: number): VecLike[] {
		// TODO
		throw new Error('Group2d.intersectCircle not implemented')
	}

	getSvgPathData(): string {
		return ''
	}
}
