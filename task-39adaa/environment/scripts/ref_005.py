import cadquery as cq
base = cq.Workplane("XY").box(3.0, 3.0, 0.5)
cylinder = cq.Workplane("XY").workplane(offset=0.5).circle(0.75).extrude(1.5)
result = base.union(cylinder)
cq.exporters.export(result, 'output.stl')
