
import { Geometry2d } from './Geometry2d'
import { MatModel } from './Mat'
import { Vec, VecLike } from './Vec'
import { Box } from './Box'

/**
 * Wraps a Geometry2d with an arbitrary 2×3 affine transformation matrix.
 *
 * The matrix transforms LOCAL coordinates to WORLD coordinates:
 *   world = Mat.applyToPoint(matrix, local)
 */
export class TransformedGeometry2d extends Geometry2d {
	constructor(
		private readonly geometry: Geometry2d,
		private readonly matrix: MatModel
	) {
		super({ isFilled: geometry.isFilled, isClosed: geometry.isClosed })
	}

	getVertices(): Vec[] {
		// TODO
		throw new Error('TransformedGeometry2d.getVertices not implemented')
	}

	nearestPoint(point: VecLike): Vec {
		// TODO
		throw new Error('TransformedGeometry2d.nearestPoint not implemented')
	}

	override hitTestPoint(
		point: VecLike,
		margin?: number,
		hitInside?: boolean
	): boolean {
		// TODO
		throw new Error('TransformedGeometry2d.hitTestPoint not implemented')
	}

	override distanceToPoint(point: VecLike, hitInside?: boolean): number {
		// TODO
		throw new Error('TransformedGeometry2d.distanceToPoint not implemented')
	}

	override getBounds(): Box {
		// TODO
		throw new Error('TransformedGeometry2d.getBounds not implemented')
	}

	/**
	 * Return a new TransformedGeometry2d with the composed transformation.
	 * The new transform applies this.matrix first, then the given matrix.
	 */
	transform(matrix: MatModel): TransformedGeometry2d {
		// TODO
		throw new Error('TransformedGeometry2d.transform not implemented')
	}

	getSvgPathData(): string {
		return ''
	}
}
