
import { Vec, VecLike } from './Vec'

/** @public */
export class Box {
	constructor(
		public x = 0,
		public y = 0,
		public w = 0,
		public h = 0
	) {}

	get minX() { return this.x }
	get minY() { return this.y }
	get maxX() { return this.x + this.w }
	get maxY() { return this.y + this.h }
	get width() { return this.w }
	get height() { return this.h }

	get center(): Vec {
		return new Vec(this.x + this.w / 2, this.y + this.h / 2)
	}

	get corners(): Vec[] {
		return [
			new Vec(this.x, this.y),
			new Vec(this.x + this.w, this.y),
			new Vec(this.x + this.w, this.y + this.h),
			new Vec(this.x, this.y + this.h),
		]
	}

	get sides(): [Vec, Vec][] {
		const c = this.corners
		return [
			[c[0], c[1]],
			[c[1], c[2]],
			[c[2], c[3]],
			[c[3], c[0]],
		]
	}

	clone(): Box {
		return new Box(this.x, this.y, this.w, this.h)
	}

	expand(other: Box): Box {
		const minX = Math.min(this.x, other.x)
		const minY = Math.min(this.y, other.y)
		const maxX = Math.max(this.maxX, other.maxX)
		const maxY = Math.max(this.maxY, other.maxY)
		this.x = minX
		this.y = minY
		this.w = maxX - minX
		this.h = maxY - minY
		return this
	}

	containsPoint(p: VecLike, margin = 0): boolean {
		return !(
			p.x < this.minX - margin ||
			p.y < this.minY - margin ||
			p.x > this.maxX + margin ||
			p.y > this.maxY + margin
		)
	}

	static FromPoints(points: VecLike[]): Box {
		if (points.length === 0) return new Box()
		let minX = Infinity, minY = Infinity
		let maxX = -Infinity, maxY = -Infinity
		for (const p of points) {
			if (p.x < minX) minX = p.x
			if (p.y < minY) minY = p.y
			if (p.x > maxX) maxX = p.x
			if (p.y > maxY) maxY = p.y
		}
		return new Box(minX, minY, maxX - minX, maxY - minY)
	}

	static Collides(A: Box, B: Box): boolean {
		return !(A.maxX < B.minX || A.minX > B.maxX || A.maxY < B.minY || A.minY > B.maxY)
	}

	static Equals(a: Box, b: Box): boolean {
		return a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h
	}
}
