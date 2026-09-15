
import { VecLike } from './Vec'

/**
 * Find intersection points between a line segment and an ellipse.
 *
 * @param a1 - First endpoint of the line segment
 * @param a2 - Second endpoint of the line segment
 * @param center - Center of the ellipse
 * @param rx - Semi-axis length along the ellipse's local X axis
 * @param ry - Semi-axis length along the ellipse's local Y axis
 * @param rotation - Rotation angle in radians (0 = axis-aligned)
 * @returns Array of intersection points, or null if no intersections.
 */
export function intersectLineSegmentEllipse(
	a1: VecLike,
	a2: VecLike,
	center: VecLike,
	rx: number,
	ry: number,
	rotation: number
): VecLike[] | null {
	// TODO
	throw new Error('intersectLineSegmentEllipse not implemented')
}
