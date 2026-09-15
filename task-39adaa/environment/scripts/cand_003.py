import cadquery as cq
result = cq.Workplane("XY").circle(0.5).extrude(1.0)
cq.exporters.export(result, 'output.stl')
