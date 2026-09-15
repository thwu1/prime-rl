import cadquery as cq

# Simple box - identical to candidate
result = cq.Workplane("XY").box(10.0, 10.0, 10.0)
cq.exporters.export(result, "output.stl")
