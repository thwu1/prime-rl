import cadquery as cq
r=cq.Workplane('XY').box(200,100,80).faces(">Z").workplane().hole(40)
