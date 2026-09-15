
import { Vec } from '/app/src/Vec'
import { Mat } from '/app/src/Mat'
import { Box } from '/app/src/Box'
import { Polygon2d } from '/app/src/Polygon2d'
import { Circle2d } from '/app/src/Circle2d'
import { TransformedGeometry2d } from '/app/src/TransformedGeometry2d'
import { Group2d } from '/app/src/Group2d'
import { intersectLineSegmentEllipse } from '/app/src/ellipseIntersect'
import type { VecLike } from '/app/src/Vec'
import type { Geometry2d } from '/app/src/Geometry2d'

// ─── Test utilities ──────────────────────────────────────────────────

const TOL = 0.5          // tolerance for vertex-approximated geometry
const STRICT_TOL = 0.001 // tolerance for exact geometry (polygons)

interface TestResult {
	name: string
	pass: boolean
	detail?: string
}

const results: TestResult[] = []

function approxEq(a: number, b: number, tol: number): boolean {
	return Math.abs(a - b) <= tol
}

function vecApprox(a: VecLike, b: VecLike, tol: number): boolean {
	return approxEq(a.x, b.x, tol) && approxEq(a.y, b.y, tol)
}

function test(name: string, fn: () => void): void {
	try {
		fn()
		results.push({ name, pass: true })
	} catch (e: any) {
		results.push({ name, pass: false, detail: e.message || String(e) })
	}
}

function assert(condition: boolean, msg: string): void {
	if (!condition) throw new Error(msg)
}

function assertVec(actual: VecLike, expected: VecLike, tol: number, label: string): void {
	assert(
		vecApprox(actual, expected, tol),
		`${label}: expected (${expected.x.toFixed(3)}, ${expected.y.toFixed(3)}) got (${actual.x.toFixed(3)}, ${actual.y.toFixed(3)})`
	)
}

function assertNum(actual: number, expected: number, tol: number, label: string): void {
	assert(
		approxEq(actual, expected, tol),
		`${label}: expected ${expected.toFixed(4)} got ${actual.toFixed(4)}`
	)
}

// ─── Helper factories ────────────────────────────────────────────────

function makeSquare(filled = true): Polygon2d {
	return new Polygon2d({
		isFilled: filled,
		points: [new Vec(0, 0), new Vec(10, 0), new Vec(10, 10), new Vec(0, 10)],
	})
}

function makeTriangle(filled = true): Polygon2d {
	return new Polygon2d({
		isFilled: filled,
		points: [new Vec(0, 0), new Vec(10, 0), new Vec(10, 10)],
	})
}

function makeCircle(filled = true, radius = 5): Circle2d {
	return new Circle2d({ isFilled: filled, radius })
}

// ═══════════════════════════════════════════════════════════════════════
// TransformedGeometry2d tests
// ═══════════════════════════════════════════════════════════════════════

// --- Translation ---

test('TG_translate_getVertices', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Translate(5, 3))
	const verts = t.getVertices()
	assert(verts.length === 4, `Expected 4 vertices, got ${verts.length}`)
	assertVec(verts[0], { x: 5, y: 3 }, STRICT_TOL, 'v0')
	assertVec(verts[1], { x: 15, y: 3 }, STRICT_TOL, 'v1')
	assertVec(verts[2], { x: 15, y: 13 }, STRICT_TOL, 'v2')
	assertVec(verts[3], { x: 5, y: 13 }, STRICT_TOL, 'v3')
})

test('TG_translate_nearestPoint', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Translate(5, 3))
	const np = t.nearestPoint({ x: 3, y: 8 })
	assertVec(np, { x: 5, y: 8 }, STRICT_TOL, 'nearest')
})

test('TG_translate_distanceToPoint_outside', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Translate(5, 3))
	const d = t.distanceToPoint({ x: 3, y: 8 })
	assertNum(d, 2.0, STRICT_TOL, 'dist')
})

test('TG_translate_distanceToPoint_inside', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Translate(5, 3))
	const d = t.distanceToPoint({ x: 6, y: 8 })
	assertNum(d, -1.0, STRICT_TOL, 'dist')
})

test('TG_translate_hitTestPoint', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Translate(5, 3))
	assert(t.hitTestPoint({ x: 10, y: 8 }, 0, true) === true, 'inside should hit')
	assert(t.hitTestPoint({ x: 3, y: 8 }, 0, false) === false, 'outside no margin')
	assert(t.hitTestPoint({ x: 3, y: 8 }, 3, false) === true, 'within margin')
	assert(t.hitTestPoint({ x: 3, y: 8 }, 1, false) === false, 'outside margin')
})

// --- Non-uniform scaling ---

test('TG_nonuniform_scale_getVertices', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Scale(2, 0.5))
	const verts = t.getVertices()
	assertVec(verts[0], { x: 0, y: 0 }, STRICT_TOL, 'v0')
	assertVec(verts[1], { x: 20, y: 0 }, STRICT_TOL, 'v1')
	assertVec(verts[2], { x: 20, y: 5 }, STRICT_TOL, 'v2')
	assertVec(verts[3], { x: 0, y: 5 }, STRICT_TOL, 'v3')
})

test('TG_nonuniform_scale_nearestPoint', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Scale(2, 0.5))
	const np = t.nearestPoint({ x: 25, y: 2.5 })
	assertVec(np, { x: 20, y: 2.5 }, STRICT_TOL, 'nearest')
})

test('TG_nonuniform_scale_distanceToPoint_inside', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Scale(2, 0.5))
	const d = t.distanceToPoint({ x: 10, y: 2.5 })
	assertNum(d, -2.5, STRICT_TOL, 'dist inside')
})

test('TG_nonuniform_scale_distanceToPoint_outside', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Scale(2, 0.5))
	const d = t.distanceToPoint({ x: 25, y: 2.5 })
	assertNum(d, 5.0, STRICT_TOL, 'dist outside')
})

test('TG_nonuniform_scale_hitTestPoint_margin', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Scale(2, 0.5))
	assert(t.hitTestPoint({ x: 21, y: 2.5 }, 0.5, false) === false, 'margin 0.5 should miss')
	assert(t.hitTestPoint({ x: 21, y: 2.5 }, 1.5, false) === true, 'margin 1.5 should hit')
})

test('TG_nonuniform_scale_intersectLineSegment', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Scale(2, 0.5))
	const hits = t.intersectLineSegment({ x: -5, y: 2.5 }, { x: 25, y: 2.5 })
	assert(hits.length === 2, `Expected 2 intersections, got ${hits.length}`)
	hits.sort((a, b) => a.x - b.x)
	assertVec(hits[0], { x: 0, y: 2.5 }, STRICT_TOL, 'left')
	assertVec(hits[1], { x: 20, y: 2.5 }, STRICT_TOL, 'right')
})

// --- Correctness under non-uniform scaling ---

test('TG_nonuniform_scale_nearestPoint_diagonal_edge', () => {
	// Triangle [(0,0), (10,0), (10,10)] under scale(2, 1)
	const tri = makeTriangle()
	const t = new TransformedGeometry2d(tri, Mat.Scale(2, 1))
	const np = t.nearestPoint({ x: 5, y: 8 })
	assertVec(np, { x: 7.2, y: 3.6 }, STRICT_TOL, 'nearest on scaled hypotenuse')
	const d = t.distanceToPoint({ x: 5, y: 8 })
	assertNum(d, Math.sqrt(24.2), STRICT_TOL, 'distance to scaled hypotenuse')
})

// --- Rotation ---

test('TG_rotation_getBounds', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Rotate(Math.PI / 4))
	const b = t.getBounds()
	const s2 = Math.SQRT2
	assertNum(b.minX, -10 / s2, STRICT_TOL, 'bounds.minX')
	assertNum(b.maxX, 10 / s2, STRICT_TOL, 'bounds.maxX')
	assertNum(b.minY, 0, STRICT_TOL, 'bounds.minY')
	assertNum(b.maxY, 10 * s2, STRICT_TOL, 'bounds.maxY')
})

test('TG_rotation_nearestPoint', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Rotate(Math.PI / 4))
	const np = t.nearestPoint({ x: 10, y: 10 / Math.SQRT2 })
	assertVec(np, { x: 10 / Math.SQRT2, y: 10 / Math.SQRT2 }, STRICT_TOL, 'nearest')
})

// --- Shear transform ---

test('TG_shear_nearestPoint', () => {
	const sq = makeSquare()
	// Shear: x' = x + 0.5*y, y' = y
	const t = new TransformedGeometry2d(sq, { a: 1, b: 0, c: 0.5, d: 1, e: 0, f: 0 })
	const np = t.nearestPoint({ x: 20, y: 5 })
	assertVec(np, { x: 14, y: 8 }, STRICT_TOL, 'nearest')
})

// --- Composed transforms ---

test('TG_compose_transform', () => {
	const sq = makeSquare()
	const composed = Mat.Compose(Mat.Translate(5, 3), Mat.Scale(2, 0.5))
	const t = new TransformedGeometry2d(sq, composed)
	const verts = t.getVertices()
	assertVec(verts[0], { x: 5, y: 3 }, STRICT_TOL, 'v0')
	assertVec(verts[1], { x: 25, y: 3 }, STRICT_TOL, 'v1')
	assertVec(verts[2], { x: 25, y: 8 }, STRICT_TOL, 'v2')
	assertVec(verts[3], { x: 5, y: 8 }, STRICT_TOL, 'v3')
})

test('TG_transform_compose_method', () => {
	const sq = makeSquare()
	const t1 = new TransformedGeometry2d(sq, Mat.Scale(2, 0.5))
	const t2 = t1.transform(Mat.Translate(5, 3))
	const np = t2.nearestPoint({ x: 3, y: 5.5 })
	assertVec(np, { x: 5, y: 5.5 }, STRICT_TOL, 'nearest after compose')
})

// --- Rotation + non-uniform scale composed ---

test('TG_rotation_scale_nearestPoint', () => {
	const tri = makeTriangle()
	// Compose: first scale(2,1), then rotate(π/2)
	// World vertices: (0,0), (0,20), (-10,20)
	const t = new TransformedGeometry2d(tri, Mat.Compose(Mat.Rotate(Math.PI / 2), Mat.Scale(2, 1)))
	// Point (5, 10): nearest to edge (0,0)→(0,20) at (0, 10)
	const np = t.nearestPoint({ x: 5, y: 10 })
	assertVec(np, { x: 0, y: 10 }, STRICT_TOL, 'nearest')
})

// --- Circle under non-uniform scaling (becomes elliptical polygon) ---

test('TG_circle_nonuniform_scale_nearestPoint', () => {
	const c = makeCircle(true, 5)
	const t = new TransformedGeometry2d(c, Mat.Scale(2, 1))
	const np = t.nearestPoint({ x: 10, y: 11 })
	assertVec(np, { x: 10, y: 10 }, TOL, 'nearest top of ellipse')
})

test('TG_circle_nonuniform_scale_nearestPoint_right', () => {
	const c = makeCircle(true, 5)
	const t = new TransformedGeometry2d(c, Mat.Scale(2, 1))
	const np = t.nearestPoint({ x: 21, y: 5 })
	assertVec(np, { x: 20, y: 5 }, TOL, 'nearest right of ellipse')
})

test('TG_circle_nonuniform_hitTestPoint', () => {
	const c = makeCircle(true, 5)
	const t = new TransformedGeometry2d(c, Mat.Scale(2, 1))
	assert(t.hitTestPoint({ x: 10, y: 5 }, 0, true) === true, 'center should be inside')
	assert(t.hitTestPoint({ x: 30, y: 5 }, 0, false) === false, 'far right should miss')
	assert(t.hitTestPoint({ x: 21, y: 5 }, 2, false) === true, 'margin hit right')
})

// --- Unfilled polygon ---

test('TG_unfilled_polygon_hitTest', () => {
	const sq = new Polygon2d({
		isFilled: false,
		points: [new Vec(0, 0), new Vec(10, 0), new Vec(10, 10), new Vec(0, 10)],
	})
	const t = new TransformedGeometry2d(sq, Mat.Translate(0, 0))
	assert(t.hitTestPoint({ x: 5, y: 5 }, 0, false) === false, 'center miss unfilled')
	assert(t.hitTestPoint({ x: 5, y: 5 }, 6, false) === true, 'margin hit')
})

// --- Identity intersectLineSegment (exercises closing edge) ---

test('TG_identity_intersectLineSegment', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Identity())
	const hits = t.intersectLineSegment({ x: -5, y: 5 }, { x: 15, y: 5 })
	assert(hits.length === 2, `Expected 2 intersections, got ${hits.length}`)
	hits.sort((a, b) => a.x - b.x)
	assertVec(hits[0], { x: 0, y: 5 }, STRICT_TOL, 'left')
	assertVec(hits[1], { x: 10, y: 5 }, STRICT_TOL, 'right')
})

// --- Polygon intersectLineSegment (closing edge, no transform) ---

test('P2D_intersectLineSegment_closing_edge', () => {
	const sq = makeSquare()
	// Short horizontal line that only crosses the closing edge (0,10)→(0,0)
	const hits = sq.intersectLineSegment({ x: -5, y: 5 }, { x: 0.5, y: 5 })
	assert(hits.length === 1, `Expected 1 intersection on closing edge, got ${hits.length}`)
	assertVec(hits[0], { x: 0, y: 5 }, STRICT_TOL, 'closing edge intersection')
})

// ═══════════════════════════════════════════════════════════════════════
// Group2d tests
// ═══════════════════════════════════════════════════════════════════════

test('G2D_basic_nearestPoint', () => {
	const p1 = new Polygon2d({
		isFilled: true,
		points: [new Vec(0, 0), new Vec(10, 0), new Vec(5, 10)],
	})
	const p2 = new Polygon2d({
		isFilled: true,
		points: [new Vec(30, 0), new Vec(40, 0), new Vec(35, 10)],
	})
	const g = new Group2d({ children: [p1, p2] })
	const np = g.nearestPoint({ x: 12, y: 5 })
	assertVec(np, { x: 8.4, y: 3.2 }, STRICT_TOL, 'nearest')
})

test('G2D_hitTestPoint', () => {
	const p1 = new Polygon2d({
		isFilled: true,
		points: [new Vec(0, 0), new Vec(10, 0), new Vec(10, 10), new Vec(0, 10)],
	})
	const p2 = new Polygon2d({
		isFilled: true,
		points: [new Vec(20, 0), new Vec(30, 0), new Vec(30, 10), new Vec(20, 10)],
	})
	const g = new Group2d({ children: [p1, p2] })
	assert(g.hitTestPoint({ x: 5, y: 5 }, 0, true) === true, 'inside p1')
	assert(g.hitTestPoint({ x: 25, y: 5 }, 0, true) === true, 'inside p2')
	assert(g.hitTestPoint({ x: 15, y: 5 }, 0, true) === false, 'between')
})

test('G2D_distanceToPoint', () => {
	const p1 = new Polygon2d({
		isFilled: true,
		points: [new Vec(0, 0), new Vec(10, 0), new Vec(10, 10), new Vec(0, 10)],
	})
	const p2 = new Polygon2d({
		isFilled: true,
		points: [new Vec(20, 0), new Vec(30, 0), new Vec(30, 10), new Vec(20, 10)],
	})
	const g = new Group2d({ children: [p1, p2] })
	const d1 = g.distanceToPoint({ x: 5, y: 5 }, true)
	assertNum(d1, -5, STRICT_TOL, 'inside p1 dist')
	const d2 = g.distanceToPoint({ x: 15, y: 5 })
	assertNum(d2, 5, STRICT_TOL, 'between dist')
})

test('G2D_getBounds', () => {
	const p1 = new Polygon2d({
		isFilled: true,
		points: [new Vec(0, 0), new Vec(10, 0), new Vec(10, 10), new Vec(0, 10)],
	})
	const p2 = new Polygon2d({
		isFilled: true,
		points: [new Vec(20, 0), new Vec(30, 0), new Vec(30, 10), new Vec(20, 10)],
	})
	const g = new Group2d({ children: [p1, p2] })
	const b = g.getBounds()
	assertNum(b.minX, 0, STRICT_TOL, 'minX')
	assertNum(b.minY, 0, STRICT_TOL, 'minY')
	assertNum(b.maxX, 30, STRICT_TOL, 'maxX')
	assertNum(b.maxY, 10, STRICT_TOL, 'maxY')
})

test('G2D_intersectLineSegment', () => {
	const p1 = new Polygon2d({
		isFilled: true,
		points: [new Vec(0, 0), new Vec(10, 0), new Vec(10, 10), new Vec(0, 10)],
	})
	const p2 = new Polygon2d({
		isFilled: true,
		points: [new Vec(20, 0), new Vec(30, 0), new Vec(30, 10), new Vec(20, 10)],
	})
	const g = new Group2d({ children: [p1, p2] })
	const hits = g.intersectLineSegment({ x: -5, y: 5 }, { x: 35, y: 5 })
	assert(hits.length === 4, `Expected 4 intersections, got ${hits.length}`)
	// Verify positions span the correct edges
	const xs = hits.map(h => h.x).sort((a, b) => a - b)
	assertNum(xs[0], 0, STRICT_TOL, 'leftmost')
	assertNum(xs[1], 10, STRICT_TOL, 'second')
	assertNum(xs[2], 20, STRICT_TOL, 'third')
	assertNum(xs[3], 30, STRICT_TOL, 'rightmost')
})

test('G2D_with_transformed_children', () => {
	const sq = makeSquare()
	const t1 = new TransformedGeometry2d(sq, Mat.Translate(0, 0))
	const t2 = new TransformedGeometry2d(sq, Mat.Translate(20, 0))
	const g = new Group2d({ children: [t1, t2] })
	assert(g.hitTestPoint({ x: 5, y: 5 }, 0, true) === true, 'inside left')
	assert(g.hitTestPoint({ x: 25, y: 5 }, 0, true) === true, 'inside right')
	assert(g.hitTestPoint({ x: 15, y: 5 }, 0, true) === false, 'between')
})

test('G2D_inside_takes_priority', () => {
	// Point is outside one child but inside another
	const small = new Polygon2d({
		isFilled: true,
		points: [new Vec(0, 0), new Vec(5, 0), new Vec(5, 5), new Vec(0, 5)],
	})
	const large = new Polygon2d({
		isFilled: true,
		points: [new Vec(-10, -10), new Vec(20, -10), new Vec(20, 20), new Vec(-10, 20)],
	})
	const g = new Group2d({ children: [small, large] })
	// (7, 2.5) is outside small but inside large
	const d = g.distanceToPoint({ x: 7, y: 2.5 }, true)
	assert(d < 0, `Distance should be negative when inside a child, got ${d}`)
})

// ═══════════════════════════════════════════════════════════════════════
// intersectLineSegmentEllipse tests
// ═══════════════════════════════════════════════════════════════════════

test('EI_axis_aligned_horizontal', () => {
	const hits = intersectLineSegmentEllipse(
		{ x: -15, y: 0 }, { x: 15, y: 0 },
		{ x: 0, y: 0 }, 10, 5, 0
	)
	assert(hits !== null, 'should intersect')
	assert(hits!.length === 2, `Expected 2, got ${hits!.length}`)
	const sorted = [...hits!].sort((a, b) => a.x - b.x)
	assertVec(sorted[0], { x: -10, y: 0 }, STRICT_TOL, 'left')
	assertVec(sorted[1], { x: 10, y: 0 }, STRICT_TOL, 'right')
})

test('EI_axis_aligned_vertical', () => {
	const hits = intersectLineSegmentEllipse(
		{ x: 0, y: -10 }, { x: 0, y: 10 },
		{ x: 0, y: 0 }, 10, 5, 0
	)
	assert(hits !== null, 'should intersect')
	assert(hits!.length === 2, `Expected 2, got ${hits!.length}`)
	const sorted = [...hits!].sort((a, b) => a.y - b.y)
	assertVec(sorted[0], { x: 0, y: -5 }, STRICT_TOL, 'bottom')
	assertVec(sorted[1], { x: 0, y: 5 }, STRICT_TOL, 'top')
})

test('EI_axis_aligned_diagonal', () => {
	const hits = intersectLineSegmentEllipse(
		{ x: -15, y: 3 }, { x: 15, y: 3 },
		{ x: 0, y: 0 }, 10, 5, 0
	)
	assert(hits !== null, 'should intersect')
	assert(hits!.length === 2, `Expected 2, got ${hits!.length}`)
	const sorted = [...hits!].sort((a, b) => a.x - b.x)
	assertVec(sorted[0], { x: -8, y: 3 }, STRICT_TOL, 'left')
	assertVec(sorted[1], { x: 8, y: 3 }, STRICT_TOL, 'right')
})

test('EI_no_intersection', () => {
	const hits = intersectLineSegmentEllipse(
		{ x: -10, y: 10 }, { x: 10, y: 10 },
		{ x: 0, y: 0 }, 10, 5, 0
	)
	assert(hits === null, 'should not intersect')
})

test('EI_partial_segment', () => {
	const hits = intersectLineSegmentEllipse(
		{ x: 0, y: 0 }, { x: 15, y: 0 },
		{ x: 0, y: 0 }, 10, 5, 0
	)
	assert(hits !== null, 'should intersect')
	assert(hits!.length === 1, `Expected 1, got ${hits!.length}`)
	assertVec(hits![0], { x: 10, y: 0 }, STRICT_TOL, 'right only')
})

test('EI_rotated_ellipse', () => {
	const hits = intersectLineSegmentEllipse(
		{ x: -15, y: 0 }, { x: 15, y: 0 },
		{ x: 0, y: 0 }, 10, 5, Math.PI / 4
	)
	assert(hits !== null, 'should intersect')
	assert(hits!.length === 2, `Expected 2, got ${hits!.length}`)
	const sorted = [...hits!].sort((a, b) => a.x - b.x)
	const expected = Math.sqrt(40)
	assertVec(sorted[0], { x: -expected, y: 0 }, STRICT_TOL, 'left')
	assertVec(sorted[1], { x: expected, y: 0 }, STRICT_TOL, 'right')
})

test('EI_offset_center', () => {
	const hits = intersectLineSegmentEllipse(
		{ x: -5, y: 3 }, { x: 15, y: 3 },
		{ x: 5, y: 3 }, 4, 2, 0
	)
	assert(hits !== null, 'should intersect')
	assert(hits!.length === 2, `Expected 2, got ${hits!.length}`)
	const sorted = [...hits!].sort((a, b) => a.x - b.x)
	assertVec(sorted[0], { x: 1, y: 3 }, STRICT_TOL, 'left')
	assertVec(sorted[1], { x: 9, y: 3 }, STRICT_TOL, 'right')
})

test('EI_tangent', () => {
	// Line tangent to the top of the ellipse: y=5 for ellipse (0,0) rx=10 ry=5
	const hits = intersectLineSegmentEllipse(
		{ x: -15, y: 5 }, { x: 15, y: 5 },
		{ x: 0, y: 0 }, 10, 5, 0
	)
	assert(hits !== null, 'should intersect (tangent)')
	assert(hits!.length === 1, `Expected 1 tangent point, got ${hits!.length}`)
	assertVec(hits![0], { x: 0, y: 5 }, STRICT_TOL, 'tangent point')
})

// ═══════════════════════════════════════════════════════════════════════
// Combined: TransformedGeometry2d + intersectCircle
// ═══════════════════════════════════════════════════════════════════════

test('TG_intersectCircle_polygon', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Scale(2, 0.5))
	const hits = t.intersectCircle({ x: 22, y: 2.5 }, 3)
	assert(hits.length >= 1, `Expected at least 1 intersection, got ${hits.length}`)
	for (const h of hits) {
		assert(approxEq(h.x, 20, STRICT_TOL), `intersection x should be ~20, got ${h.x}`)
	}
})

// ═══════════════════════════════════════════════════════════════════════
// Edge cases
// ═══════════════════════════════════════════════════════════════════════

test('TG_identity_transform', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Identity())
	const np = t.nearestPoint({ x: -2, y: 5 })
	assertVec(np, { x: 0, y: 5 }, STRICT_TOL, 'identity nearest')
	const d = t.distanceToPoint({ x: -2, y: 5 })
	assertNum(d, 2, STRICT_TOL, 'identity dist')
})

test('TG_large_scale', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Scale(100, 0.01))
	const np = t.nearestPoint({ x: 500, y: 1 })
	assertVec(np, { x: 500, y: 0.1 }, STRICT_TOL, 'large scale nearest')
})

test('TG_point_on_vertex', () => {
	const sq = makeSquare()
	const t = new TransformedGeometry2d(sq, Mat.Scale(2, 1))
	const np = t.nearestPoint({ x: 20, y: 0 })
	assertVec(np, { x: 20, y: 0 }, STRICT_TOL, 'on vertex')
	const d = t.distanceToPoint({ x: 20, y: 0 })
	assertNum(d, 0, STRICT_TOL, 'dist at vertex')
})

test('G2D_single_child', () => {
	const sq = makeSquare()
	const g = new Group2d({ children: [sq] })
	const np = g.nearestPoint({ x: -2, y: 5 })
	assertVec(np, { x: 0, y: 5 }, STRICT_TOL, 'single child nearest')
})

// ═══════════════════════════════════════════════════════════════════════
// Output results
// ═══════════════════════════════════════════════════════════════════════

const passed = results.filter((r) => r.pass).length
const failed = results.filter((r) => !r.pass).length

console.log(JSON.stringify({ results, summary: { passed, failed, total: results.length } }))

if (failed > 0) {
	console.error(`\nFAILED TESTS:`)
	for (const r of results) {
		if (!r.pass) {
			console.error(`  FAIL: ${r.name} — ${r.detail}`)
		}
	}
	process.exit(1)
} else {
	console.error(`\nAll ${passed} tests passed.`)
	process.exit(0)
}
