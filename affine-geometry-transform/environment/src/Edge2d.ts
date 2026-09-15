
import { Vec, VecLike } from './Vec'
import { Geometry2d } from './Geometry2d'

/** A line segment between two points. */
export class Edge2d extends Geometry2d {
	private _start: Vec
	private _end: Vec

	constructor(config: { start: Vec; end: Vec }) {
		super({ isClosed: false, isFilled: false })
		this._start = config.start
		this._end = config.end
	}

	override getLength(): number {
		return Vec.Dist(this._start, this._end)
	}

	getVertices(): Vec[] {
		return [this._start, this._end]
	}

	nearestPoint(point: VecLike): Vec {
		return Vec.NearestPointOnLineSegment(this._start, this._end, point, true)
	}

	override distanceToPoint(point: VecLike, _hitInside = false): number {
		return Vec.Dist(point, this.nearestPoint(point))
	}

	getSvgPathData(): string {
		return ''
	}
}
