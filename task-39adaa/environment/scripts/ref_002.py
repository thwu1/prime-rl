import cadquery as cq
result = cq.Workplane("XY").box(2.0, 1.0, 1.0)
cq.exporters.export(result, 'output.stl')
