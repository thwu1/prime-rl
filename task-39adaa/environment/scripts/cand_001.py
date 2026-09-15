import cadquery as cq
result = cq.Workplane("XY").box(1.0, 1.0, 1.0)
cq.exporters.export(result, 'output.stl')
