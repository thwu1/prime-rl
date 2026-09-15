
import { VecLike } from './Vec'

/** Helper for winding-number point-in-polygon */
function cross(x: VecLike, y: VecLike, z: VecLike): number {
	return (y.x - x.x) * (z.y - x.y) - (z.x - x.x) * (y.y - x.y)
}

/**
 * Determine whether point A is inside the polygon defined by `points`
 * using the winding number algorithm.
 */
export function pointInPolygon(A: VecLike, points: VecLike[]): boolean {
	let windingNumber = 0
	let a: VecLike, b: VecLike

	for (let i = 0; i < points.length; i++) {
		a = points[i]
		if (a.x === A.x && a.y === A.y) return true

		b = points[(i + 1) % points.length]

		if (a.y <= A.y) {
			if (b.y > A.y && cross(a, b, A) > 0) {
				windingNumber += 1
			}
		} else if (b.y <= A.y && cross(a, b, A) < 0) {
			windingNumber -= 1
		}
	}

	return windingNumber !== 0
}

/**
 * Check approximate equality of two numbers.
 */
export function approximately(a: number, b: number, precision = 0.000001): boolean {
	return Math.abs(a - b) <= precision
}

export const PI = Math.PI
export const PI2 = Math.PI * 2
export const HALF_PI = Math.PI / 2
