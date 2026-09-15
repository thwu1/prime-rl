import cadquery as cq
sketch_scale = 0.02
result = (
    cq.Workplane("XY")
    .lineTo(0.0208 * sketch_scale, 0.0)
    .threePointArc((0.0104 * sketch_scale, 0.0104 * sketch_scale), (0.0, 0.0208 * sketch_scale))
    .close()
    .extrude(0.5)
)
cq.exporters.export(result, 'output.stl')
