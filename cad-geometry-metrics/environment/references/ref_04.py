import cadquery as cq

# Right triangle prism - the correct geometry for the broken script_04
# (the threePointArc control points are collinear, so the arc degenerates to a line)
sketch_scale = 0.75
extrude_depth = 0.0521 * sketch_scale
side = 0.0208 * sketch_scale

part = (
    cq.Workplane("XY")
    .moveTo(0.0, 0.0)
    .lineTo(side, 0.0)
    .lineTo(0.0, side)
    .close()
    .extrude(extrude_depth)
)
cq.exporters.export(part, "output.stl")
