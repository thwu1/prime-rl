
/** @public */
export interface VecLike {
	x: number
	y: number
}

/** @public */
export class Vec {
	constructor(
		public x = 0,
		public y = 0
	) {}

	clone(): Vec {
		return new Vec(this.x, this.y)
	}

	static From(v: VecLike): Vec {
		return new Vec(v.x, v.y)
	}

	static Add(A: VecLike, B: VecLike): Vec {
		return new Vec(A.x + B.x, A.y + B.y)
	}

	static Sub(A: VecLike, B: VecLike): Vec {
		return new Vec(A.x - B.x, A.y - B.y)
	}

	static Mul(A: VecLike, t: number): Vec {
		return new Vec(A.x * t, A.y * t)
	}

	static Div(A: VecLike, t: number): Vec {
		return new Vec(A.x / t, A.y / t)
	}

	static Neg(A: VecLike): Vec {
		return new Vec(-A.x, -A.y)
	}

	static Dist(A: VecLike, B: VecLike): number {
		return Math.sqrt((A.x - B.x) ** 2 + (A.y - B.y) ** 2)
	}

	static Dist2(A: VecLike, B: VecLike): number {
		return (A.x - B.x) ** 2 + (A.y - B.y) ** 2
	}

	static Len(A: VecLike): number {
		return Math.sqrt(A.x * A.x + A.y * A.y)
	}

	static Len2(A: VecLike): number {
		return A.x * A.x + A.y * A.y
	}

	static Uni(A: VecLike): Vec {
		const l = Vec.Len(A)
		if (l === 0) return new Vec(0, 0)
		return new Vec(A.x / l, A.y / l)
	}

	static Equals(A: VecLike, B: VecLike): boolean {
		return Math.abs(A.x - B.x) < 0.0001 && Math.abs(A.y - B.y) < 0.0001
	}

	static Lrp(A: VecLike, B: VecLike, t: number): Vec {
		return new Vec(A.x + (B.x - A.x) * t, A.y + (B.y - A.y) * t)
	}

	static NearestPointOnLineSegment(A: VecLike, B: VecLike, P: VecLike, clamp = true): Vec {
		const dx = B.x - A.x
		const dy = B.y - A.y
		const d2 = dx * dx + dy * dy
		if (d2 === 0) return Vec.From(A)
		let t = ((P.x - A.x) * dx + (P.y - A.y) * dy) / d2
		if (clamp) {
			if (t < 0) t = 0
			else if (t > 1) t = 1
		}
		return new Vec(A.x + t * dx, A.y + t * dy)
	}

	static DistanceToLineSegment(A: VecLike, B: VecLike, P: VecLike, clamp = true): number {
		const dx = B.x - A.x
		const dy = B.y - A.y
		const d2 = dx * dx + dy * dy
		if (d2 === 0) return Vec.Dist(A, P)
		let t = ((P.x - A.x) * dx + (P.y - A.y) * dy) / d2
		if (clamp) {
			if (t < 0) t = 0
			else if (t > 1) t = 1
		}
		const nx = A.x + t * dx - P.x
		const ny = A.y + t * dy - P.y
		return Math.sqrt(nx * nx + ny * ny)
	}

	static Dpr(A: VecLike, B: VecLike): number {
		return A.x * B.x + A.y * B.y
	}

	static Cpr(A: VecLike, B: VecLike): number {
		return A.x * B.y - B.x * A.y
	}

	static Angle(A: VecLike, B: VecLike): number {
		return Math.atan2(B.y - A.y, B.x - A.x)
	}

	static Average(arr: VecLike[]): Vec {
		const len = arr.length
		if (len === 0) return new Vec(0, 0)
		let x = 0,
			y = 0
		for (const p of arr) {
			x += p.x
			y += p.y
		}
		return new Vec(x / len, y / len)
	}

	static Per(A: VecLike): Vec {
		return new Vec(A.y, -A.x)
	}

	static Rot(A: VecLike, r: number): Vec {
		const s = Math.sin(r)
		const c = Math.cos(r)
		return new Vec(A.x * c - A.y * s, A.x * s + A.y * c)
	}

	static FromAngle(r: number, length = 1): Vec {
		return new Vec(Math.cos(r) * length, Math.sin(r) * length)
	}

	static Min(A: VecLike, B: VecLike): Vec {
		return new Vec(Math.min(A.x, B.x), Math.min(A.y, B.y))
	}

	static Max(A: VecLike, B: VecLike): Vec {
		return new Vec(Math.max(A.x, B.x), Math.max(A.y, B.y))
	}
}
