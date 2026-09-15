
import { Vec, VecLike } from './Vec'

/** @public */
export type MatLike = MatModel | Mat

/** @public */
export interface MatModel {
	a: number
	b: number
	c: number
	d: number
	e: number
	f: number
}

/**
 * 2×3 affine transformation matrix.
 *
 * Layout:
 *   | a  c  e |
 *   | b  d  f |
 *   | 0  0  1 |
 *
 * Transforming point (x,y):
 *   x' = a*x + c*y + e
 *   y' = b*x + d*y + f
 */
export class Mat {
	constructor(
		public a: number,
		public b: number,
		public c: number,
		public d: number,
		public e: number,
		public f: number
	) {}

	static Identity(): Mat {
		return new Mat(1, 0, 0, 1, 0, 0)
	}

	static Translate(x: number, y: number): Mat {
		return new Mat(1, 0, 0, 1, x, y)
	}

	static Rotate(r: number): Mat {
		if (r === 0) return Mat.Identity()
		const c = Math.cos(r)
		const s = Math.sin(r)
		return new Mat(c, s, -s, c, 0, 0)
	}

	static Scale(x: number, y: number): Mat {
		return new Mat(x, 0, 0, y, 0, 0)
	}

	static Multiply(m1: MatModel, m2: MatModel): MatModel {
		return {
			a: m1.a * m2.a + m1.c * m2.b,
			c: m1.a * m2.c + m1.c * m2.d,
			e: m1.a * m2.e + m1.c * m2.f + m1.e,
			b: m1.b * m2.a + m1.d * m2.b,
			d: m1.b * m2.c + m1.d * m2.d,
			f: m1.b * m2.e + m1.d * m2.f + m1.f,
		}
	}

	static Inverse(m: MatModel): MatModel {
		const denom = m.a * m.d - m.b * m.c
		return {
			a: m.d / denom,
			b: m.b / -denom,
			c: m.c / -denom,
			d: m.a / denom,
			e: (m.d * m.e - m.c * m.f) / -denom,
			f: (m.b * m.e - m.a * m.f) / denom,
		}
	}

	static Compose(...matrices: MatLike[]): Mat {
		const result = Mat.Identity()
		for (const m of matrices) {
			const { a, b, c, d, e, f } = result
			result.a = a * m.a + c * m.b
			result.c = a * m.c + c * m.d
			result.e = a * m.e + c * m.f + e
			result.b = b * m.a + d * m.b
			result.d = b * m.c + d * m.d
			result.f = b * m.e + d * m.f + f
		}
		return result
	}

	static Decompose(m: MatLike): {
		x: number
		y: number
		scaleX: number
		scaleY: number
		rotation: number
	} {
		let scaleX: number, scaleY: number, rotation: number

		if (m.a !== 0 || m.c !== 0) {
			const hypotAc = Math.sqrt(m.a * m.a + m.c * m.c)
			scaleX = hypotAc
			scaleY = (m.a * m.d - m.b * m.c) / hypotAc
			rotation = Math.acos(m.a / hypotAc) * (m.c > 0 ? -1 : 1)
		} else if (m.b !== 0 || m.d !== 0) {
			const hypotBd = Math.sqrt(m.b * m.b + m.d * m.d)
			scaleX = (m.a * m.d - m.b * m.c) / hypotBd
			scaleY = hypotBd
			rotation = Math.PI / 2 + Math.acos(m.b / hypotBd) * (m.d > 0 ? -1 : 1)
		} else {
			scaleX = 0
			scaleY = 0
			rotation = 0
		}

		return { x: m.e, y: m.f, scaleX, scaleY, rotation }
	}

	static applyToPoint(m: MatLike, point: VecLike): Vec {
		return new Vec(
			m.a * point.x + m.c * point.y + m.e,
			m.b * point.x + m.d * point.y + m.f
		)
	}

	static applyToPoints(m: MatLike, points: VecLike[]): Vec[] {
		return points.map((p) => Mat.applyToPoint(m, p))
	}
}
