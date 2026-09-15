
import { Vec, VecLike } from './Vec'

/**
 * Find intersection points between a line segment and an ellipse.
 *
 * The ellipse is defined by center, semi-axis lengths rx and ry,
 * and a rotation angle in radians.
 *
 * Approach: transform the line segment into the ellipse's local coordinate
 * system (translate to center, rotate by -rotation), then normalize by
 * semi-axes to reduce to a unit circle intersection problem. Solve the
 * quadratic, filter by segment parameter, and transform results back.
 */
export function intersectLineSegmentEllipse(
	a1: VecLike,
	a2: VecLike,
	center: VecLike,
	rx: number,
	ry: number,
	rotation: number
): VecLike[] | null {
	const cos = Math.cos(-rotation)
	const sin = Math.sin(-rotation)

	// Transform endpoints to ellipse-local coordinates (centered, axis-aligned)
	const dx1 = a1.x - center.x
	const dy1 = a1.y - center.y
	const lx1 = (dx1 * cos - dy1 * sin) / rx
	const ly1 = (dx1 * sin + dy1 * cos) / ry

	const dx2 = a2.x - center.x
	const dy2 = a2.y - center.y
	const lx2 = (dx2 * cos - dy2 * sin) / rx
	const ly2 = (dx2 * sin + dy2 * cos) / ry

	// Now find intersections with the unit circle: x² + y² = 1
	// Parametric line: P(t) = L1 + t*(L2 - L1), t ∈ [0, 1]
	const ldx = lx2 - lx1
	const ldy = ly2 - ly1

	const A = ldx * ldx + ldy * ldy
	const B = 2 * (lx1 * ldx + ly1 * ldy)
	const C = lx1 * lx1 + ly1 * ly1 - 1

	const discriminant = B * B - 4 * A * C

	if (discriminant < 0) return null
	if (A === 0) return null // degenerate segment (zero length)

	const sqrtD = Math.sqrt(discriminant)
	const t1 = (-B + sqrtD) / (2 * A)
	const t2 = (-B - sqrtD) / (2 * A)

	const result: VecLike[] = []
	const EPS = 1e-10

	for (const t of [t1, t2]) {
		if (t >= -EPS && t <= 1 + EPS) {
			// Compute intersection in world coordinates
			const x = a1.x + (a2.x - a1.x) * t
			const y = a1.y + (a2.y - a1.y) * t
			result.push(new Vec(x, y))
		}
	}

	// Deduplicate near-identical points (tangent case)
	if (result.length === 2) {
		const d = Vec.Dist2(result[0], result[1])
		if (d < 1e-12) {
			result.pop()
		}
	}

	return result.length === 0 ? null : result
}
