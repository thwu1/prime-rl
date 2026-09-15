import cadquery as cq

# BROKEN: threePointArc with nearly-collinear control points at small scale.
# The three points (start, through, end) are exactly collinear, causing
# OpenCASCADE GC_MakeArcOfCircle to fail with floating-point precision errors.
sketch_scale = 0.75
extrude_depth = 0.0521 * sketch_scale

part = (
    cq.Workplane("XY")
    .moveTo(0.0, 0.0)
    .lineTo(0.0208 * sketch_scale, 0.0)
    .threePointArc(
        (0.0104 * sketch_scale, 0.0104 * sketch_scale),
        (0.0, 0.0208 * sketch_scale)
    )
    .close()
    .extrude(extrude_depth)
)
cq.exporters.export(part, "output.stl")
