
import { Vec, VecLike } from './Vec'

/**
 * Find the intersection between two line segments.
 * Returns the intersection point or null if they don't intersect.
 */
export function intersectLineSegmentLineSegment(
	a1: VecLike,
	a2: VecLike,
	b1: VecLike,
	b2: VecLike,
	precision = 1e-10
): Vec | null {
	const ABx = a1.x - b1.x
	const ABy = a1.y - b1.y
	const BVx = b2.x - b1.x
	const BVy = b2.y - b1.y
	const AVx = a2.x - a1.x
	const AVy = a2.y - a1.y
	const ua_t = BVx * ABy - BVy * ABx
	const ub_t = AVx * ABy - AVy * ABx
	const u_b = BVy * AVx - BVx * AVy

	if (Math.abs(ua_t) <= precision || Math.abs(ub_t) <= precision) return null
	if (Math.abs(u_b) <= precision) return null

	const ua = ua_t / u_b
	const ub = ub_t / u_b

	if (
		ua >= -precision &&
		ua <= 1 + precision &&
		ub >= -precision &&
		ub <= 1 + precision
	) {
		return new Vec(a1.x + ua * AVx, a1.y + ua * AVy)
	}

	return null
}

/**
 * Find intersection points between a line segment and a circle.
 */
export function intersectLineSegmentCircle(
	a1: VecLike,
	a2: VecLike,
	c: VecLike,
	r: number
): VecLike[] | null {
	const dx = a2.x - a1.x
	const dy = a2.y - a1.y
	const ocx = a1.x - c.x
	const ocy = a1.y - c.y

	const a = dx * dx + dy * dy
	const b = 2 * (dx * ocx + dy * ocy)
	const cc = ocx * ocx + ocy * ocy - r * r
	const deter = b * b - 4 * a * cc

	if (deter <= 0) return null

	const e = Math.sqrt(deter)
	const u1 = (-b + e) / (2 * a)
	const u2 = (-b - e) / (2 * a)

	if ((u1 < 0 || u1 > 1) && (u2 < 0 || u2 > 1)) return null

	const result: VecLike[] = []
	if (u1 >= 0 && u1 <= 1) result.push(new Vec(a1.x + dx * u1, a1.y + dy * u1))
	if (u2 >= 0 && u2 <= 1) result.push(new Vec(a1.x + dx * u2, a1.y + dy * u2))

	return result.length === 0 ? null : result
}

/**
 * Find intersection points between a line segment and a polyline.
 */
export function intersectLineSegmentPolyline(
	a1: VecLike,
	a2: VecLike,
	points: VecLike[]
): VecLike[] | null {
	const result: VecLike[] = []
	for (let i = 0, n = points.length - 1; i < n; i++) {
		const hit = intersectLineSegmentLineSegment(a1, a2, points[i], points[i + 1])
		if (hit) result.push(hit)
	}
	return result.length === 0 ? null : result
}

/**
 * Find intersection points between a line segment and a closed polygon.
 */
export function intersectLineSegmentPolygon(
	a1: VecLike,
	a2: VecLike,
	points: VecLike[]
): VecLike[] | null {
	const result: VecLike[] = []
	for (let i = 0, n = points.length - 1; i < n; i++) {
		const hit = intersectLineSegmentLineSegment(
			a1,
			a2,
			points[i],
			points[(i + 1) % n]
		)
		if (hit) result.push(hit)
	}
	return result.length === 0 ? null : result
}

/**
 * Find intersection points between a circle and a closed polygon.
 */
export function intersectCirclePolygon(
	c: VecLike,
	r: number,
	points: VecLike[]
): VecLike[] | null {
	const result: VecLike[] = []
	for (let i = 0, n = points.length; i < n; i++) {
		const hits = intersectLineSegmentCircle(points[i], points[(i + 1) % n], c, r)
		if (hits) result.push(...hits)
	}
	return result.length === 0 ? null : result
}

/**
 * Find intersection points between a circle and a polyline.
 */
export function intersectCirclePolyline(
	c: VecLike,
	r: number,
	points: VecLike[]
): VecLike[] | null {
	const result: VecLike[] = []
	for (let i = 0, n = points.length - 1; i < n; i++) {
		const hits = intersectLineSegmentCircle(points[i], points[i + 1], c, r)
		if (hits) result.push(...hits)
	}
	return result.length === 0 ? null : result
}

/** ccw helper for linesIntersect */
function ccw(A: VecLike, B: VecLike, C: VecLike): boolean {
	return (C.y - A.y) * (B.x - A.x) > (B.y - A.y) * (C.x - A.x)
}

/** Check whether two line segments intersect. */
export function linesIntersect(
	A: VecLike,
	B: VecLike,
	C: VecLike,
	D: VecLike
): boolean {
	return ccw(A, C, D) !== ccw(B, C, D) && ccw(A, B, C) !== ccw(A, B, D)
}
