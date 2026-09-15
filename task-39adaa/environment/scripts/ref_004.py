import cadquery as cq
result = cq.Workplane("XY").box(2.0, 2.0, 0.5).faces(">Z").workplane().hole(0.5)
cq.exporters.export(result, 'output.stl')
