import cadquery as cq

# Simple box - identical to reference
result = cq.Workplane("XY").box(10.0, 10.0, 10.0)
cq.exporters.export(result, "output.stl")
