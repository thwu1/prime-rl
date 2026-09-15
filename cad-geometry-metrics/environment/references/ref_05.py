import cadquery as cq

# Rectangular plate with hexagonal cutouts - very different from candidate cylinder
result = (
    cq.Workplane("XY")
    .box(3.0, 4.0, 0.25)
    .pushPoints([(0, 0.75), (0, -0.75)])
    .polygon(6, 1.0)
    .cutThruAll()
)
cq.exporters.export(result, "output.stl")
