import cadquery as cq

# Solid cylinder
result = cq.Workplane("XY").circle(15.0).extrude(30.0)
cq.exporters.export(result, "output.stl")
